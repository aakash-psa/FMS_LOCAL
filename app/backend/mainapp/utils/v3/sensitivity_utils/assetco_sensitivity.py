import os
import pickle
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from mainapp.utils.v3.sensitivity_utils.common import (
    serialize_sensitivity_payload,
    extract_sensitivity_params,
    apply_multipliers,
)


# ---------------------------------------------------------------------------
# Label → named-range field mappings
# ---------------------------------------------------------------------------

# Label → attribute names to scale in a.assetco.global.value.
_LABEL_GLOBAL_ATTR_MAP: Dict[str, List[str]] = {
    "Acquisition Price": [
        "acquisition_price",
    ],
    "Forecast Base Rent": [],
}

# Label → (class_name, attr_name) pairs to scale in a.assetco.units.data.
# Uses a.assetco.inputs.class.row + a.assetco.attributes.row for column resolution.
_LABEL_UNIT_COL_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Acquisition Price": [],
    "Forecast Base Rent": [
        ("RentParametersFirstTenant", "forecast_base_rent"),
        ("RentParametersSecondTenant", "forecast_base_rent"),
    ],
}

# Row labels for net cashflow extraction from monthly_dfs JSON dicts.
_CFO_NET_ROW = "Total Net Cashflow from Operations"
_CFI_NET_ROW = "Net Cashflow from Investments"


# ---------------------------------------------------------------------------
# AssetCo-specific index map builder
# ---------------------------------------------------------------------------

def build_assetco_index_maps(
    payload: List[Dict],
) -> Tuple[Dict[str, int], Dict[Tuple[str, str], int]]:
    """
    Builds lookup maps for AssetCo's non-standard named range keys.

    global_attr_idx : {attr_name: row_index}
        From a.assetco.global.attribute.

    unit_col_idx : {(class_name, attr_name): col_index}
        From a.assetco.inputs.class.row + a.assetco.attributes.row.
    """
    global_attr_idx: Dict[str, int] = {}
    unit_col_idx: Dict[Tuple[str, str], int] = {}

    class_row: List = []
    attr_row: List = []

    for item in payload:
        name = item.get("name")
        if name == "a.assetco.global.attribute":
            for i, row in enumerate(item.get("values", [])):
                if row and row[0]:
                    global_attr_idx[str(row[0])] = i
        elif name == "a.assetco.inputs.class.row":
            class_row = item.get("values", [[]])[0]
        elif name == "a.assetco.attributes.row":
            attr_row = item.get("values", [[]])[0]

    if class_row and attr_row:
        for j, (cls, attr) in enumerate(zip(class_row, attr_row)):
            if cls and attr:
                unit_col_idx[(str(cls), str(attr))] = j

    return global_attr_idx, unit_col_idx


# ---------------------------------------------------------------------------
# Worker-process function  (must be module-level for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

def _run_sensitivity_scenario(pickle_path: str) -> Optional[Any]:
    """
    Worker function executed in a child process. Loads (payload, is_save)
    from the pickle file and calls wrapper_for_vars.

    AssetCo uses locally scoped ThreadPoolExecutors inside wrapper_for_vars
    (no global ExecutorManager), so no executor cleanup is needed between runs.
    """
    from mainapp.utils.sensitivity.assetco_model import wrapper_for_vars

    try:
        with open(pickle_path, "rb") as f:
            payload = pickle.load(f)
        return wrapper_for_vars(payload)
    except Exception as e:
        print(f"AssetCo sensitivity scenario failed: {e}\n{traceback.format_exc()}")
        return None


# ---------------------------------------------------------------------------
# Output stripping
# ---------------------------------------------------------------------------

def fn_strip_sensitivity_result(result: Optional[Dict]) -> Optional[Dict]:
    """
    Strips a single wrapper_for_vars output down to the sensitivity-relevant
    subset: the net unlevered cashflow per period.

    AssetCo is already a single-asset model, so monthly_dfs contains
    aggregated cashflow statements (not per-unit rows). The strip function
    extracts:
        "Total Net Cashflow from Operations"  from CFO
      + "Net Cashflow from Investments"       from CFI
    and returns their element-wise sum as a single-row "Asset Net Cashflows"
    DataFrame (1 row × N periods).
    """
    if result is None:
        return None

    # AssetCo wrapper_for_vars returns {"monthly_dfs": ..., "annual_dfs": ...}
    # directly (no "exceloutput" wrapper, unlike LandCo/DevCo).
    monthly_dfs = result.get("monthly_dfs", {})

    cfo_entry = monthly_dfs.get("Cashflow from Operations")
    cfi_entry = monthly_dfs.get("Cashflow from Investments")

    if cfo_entry is None or cfi_entry is None:
        return None

    # Each entry is (code, json_dict) after df_to_json_with_index serialization.
    _, cfo_json = cfo_entry if isinstance(cfo_entry, tuple) else (None, cfo_entry)
    _, cfi_json = cfi_entry if isinstance(cfi_entry, tuple) else (None, cfi_entry)

    # Prefer period-start date strings from the Monthly Timeline; fall back to
    # CFO columns (which are year-mapped integers and won't map to PERIOD_DATES).
    _tl_entry = monthly_dfs.get("Monthly Timeline")
    cols: list = []
    if _tl_entry is not None:
        _, _tl_json = _tl_entry if isinstance(_tl_entry, tuple) else (None, _tl_entry)
        try:
            _ps_idx = _tl_json["index"].index("Period Start")
            cols = _tl_json["data"][_ps_idx]
        except (ValueError, IndexError, TypeError, KeyError):
            pass
    if not cols:
        cols = cfo_json.get("columns", []) or cfi_json.get("columns", [])
    n_cols = len(cols)

    cfo_net_row = None
    for label, row_data in zip(cfo_json.get("index", []), cfo_json.get("data", [])):
        if label == _CFO_NET_ROW:
            cfo_net_row = row_data
            break

    cfi_net_row = None
    for label, row_data in zip(cfi_json.get("index", []), cfi_json.get("data", [])):
        if label == _CFI_NET_ROW:
            cfi_net_row = row_data
            break

    if cfo_net_row is None and cfi_net_row is None:
        return None

    cfo_vals = cfo_net_row if cfo_net_row is not None else [0.0] * n_cols
    cfi_vals = cfi_net_row if cfi_net_row is not None else [0.0] * n_cols

    try:
        net_vals = [
            (a if isinstance(a, (int, float)) else 0.0)
            + (b if isinstance(b, (int, float)) else 0.0)
            for a, b in zip(cfo_vals, cfi_vals)
        ]
    except Exception:
        return None

    net_json = {
        "index": ["Asset Net Cashflow"],
        "columns": cols,
        "data": [net_vals],
    }

    return {
        "exceloutput": {
            "monthly_dfs": {
                "Asset Net Cashflows": ("o.assetco.asset.net.cf.me", net_json),
            }
        }
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fn_run_assetco_sensitivity(
    payload: List[Dict],
) -> Optional[List[Dict]]:
    """
    Runs a 25-scenario sensitivity analysis on the AssetCo model.

    Reads two sensitivity labels and step percentages from
    'a.assetco.sensitivity' (rows: [[label1, pct1], [label2, pct2]]).

    Generates 5 multiplier steps for each label:
        -2x pct,  -1x pct,  base (1.0),  +1x pct,  +2x pct

    Produces all 25 combinations (5 × 5), modifies the relevant fields in
    a.assetco.global.value and a.assetco.units.data for each scenario, and
    runs all 25 modified payloads through wrapper_for_vars in parallel via
    ProcessPoolExecutor.

    Supported sensitivity labels:
        "Acquisition Price"  — scales a.assetco.global.value[acquisition_price]
        "Forecast Base Rent" — scales forecast_base_rent columns in
                               a.assetco.units.data for both tenant slots

    Returns:
        List of 25 dicts ordered (label1_step outermost, label2_step inner):
            [{"scenario": "<label1>_<±pct>%__<label2>_<±pct>%",
              "result":   <stripped wrapper_for_vars output>}, ...]
        Returns None on unrecoverable error.
    """
    try:
        param1, param2 = extract_sensitivity_params(payload, "a.assetco.sensitivity")
        if param1 is None or param2 is None:
            print(
                "fn_run_assetco_sensitivity: 'a.assetco.sensitivity' named range "
                "not found or malformed — aborting sensitivity run."
            )
            return None

        label1, pct1 = param1
        label2, pct2 = param2

        if label1 not in _LABEL_GLOBAL_ATTR_MAP and label1 not in _LABEL_UNIT_COL_MAP:
            print(
                f"fn_run_assetco_sensitivity: label '{label1}' has no field mapping — "
                "no values will be scaled for this label."
            )
        if label2 not in _LABEL_GLOBAL_ATTR_MAP and label2 not in _LABEL_UNIT_COL_MAP:
            print(
                f"fn_run_assetco_sensitivity: label '{label2}' has no field mapping — "
                "no values will be scaled for this label."
            )

        steps1 = [
            round(1 - 2 * pct1, 10),
            round(1 - pct1, 10),
            1.0,
            round(1 + pct1, 10),
            round(1 + 2 * pct1, 10),
        ]
        steps2 = [
            round(1 - 2 * pct2, 10),
            round(1 - pct2, 10),
            1.0,
            round(1 + pct2, 10),
            round(1 + 2 * pct2, 10),
        ]

        global_attr_idx, unit_col_idx = build_assetco_index_maps(payload)

        scenario_labels: List[str] = []
        pickle_paths: List[str] = []

        for m1 in steps1:
            for m2 in steps2:
                modified = apply_multipliers(
                    payload, label1, m1, label2, m2,
                    global_attr_idx, unit_col_idx,
                    _LABEL_GLOBAL_ATTR_MAP, _LABEL_UNIT_COL_MAP,
                    "a.assetco.global.value", "a.assetco.units.data",
                )
                pct1_disp = round((m1 - 1) * 100)
                pct2_disp = round((m2 - 1) * 100)
                scenario_labels.append(
                    f"{label1}_{pct1_disp:+d}%__{label2}_{pct2_disp:+d}%"
                )
                pickle_paths.append(
                    serialize_sensitivity_payload((modified))
                )

        results: List[Optional[Any]] = []
        n_workers = max(1, min(len(pickle_paths), os.cpu_count() or 1))

        try:
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = [
                    executor.submit(_run_sensitivity_scenario, p)
                    for p in pickle_paths
                ]
                results = [f.result() for f in futures]
        finally:
            for path in pickle_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

        return [
            {
                "scenario": scenario_labels[k],
                "result": fn_strip_sensitivity_result(results[k]),
            }
            for k in range(len(scenario_labels))
        ]

    except Exception as e:
        print(f"fn_run_assetco_sensitivity error: {e}\n{traceback.format_exc()}")
        return None
