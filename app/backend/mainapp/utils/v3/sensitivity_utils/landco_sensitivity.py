import os
import pickle
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from mainapp.utils.v3.sensitivity_utils.common import (
    serialize_sensitivity_payload,
    extract_sensitivity_params,
    build_index_maps,
    apply_multipliers,
)


# ---------------------------------------------------------------------------
# Label → named-range field mappings
# ---------------------------------------------------------------------------

# Label → attribute names to scale in a.landco.global.value.
_LABEL_GLOBAL_ATTR_MAP: Dict[str, List[str]] = {
    "Land Sales Price": [
        "sales_price",
    ],
    "Infrastructure Cost": [
        "primary_infrastructure_cost_per_sqm",
        "primary_infrastructure_ad_hoc_amount",
        "secondary_infrastructure_cost_per_sqm",
        "secondary_infrastructure_ad_hoc_amount",
    ],
}

# Label → (class_name, attr_name) pairs to scale in a.landco.asset.data.
# Column resolution mirrors fn_assign_asset_class_attributes.
_LABEL_ASSET_COL_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Land Sales Price": [
        ("LandSalesModule", "sales_price"),
    ],
    "Infrastructure Cost": [
        ("PrimaryInfrastructureModule", "cost_per_sqm"),
        ("PrimaryInfrastructureModule", "ad_hoc_amount"),
        ("SecondaryInfrastructureModule", "cost_per_sqm"),
        ("SecondaryInfrastructureModule", "ad_hoc_amount"),
    ],
}


# ---------------------------------------------------------------------------
# Worker-process function  (must be module-level for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

def _run_sensitivity_scenario(pickle_path: str) -> Optional[Any]:
    """
    Worker function executed in a child process.  Loads (payload, is_save)
    from the pickle file and calls wrapper_for_vars.

    The import of wrapper_for_vars is deferred to inside the function body to
    avoid a circular import: this module is called from within landco_module
    via fninitialising_all_values, so a top-level import would create a cycle.

    ExecutorManager is reset before every call so that ProcessPoolExecutor
    worker processes — which are reused across multiple submitted tasks — each
    start with a fresh ThreadPoolExecutor.  Without this, unawaited futures
    from a previous scenario's failed wrapper_for_vars call linger in the
    shared pool and run concurrently with the next scenario's tasks, corrupting
    shared Pandas state and producing InvalidIndexError in fn_create_transaction_flag.
    """
    from mainapp.utils.sensitivity.landco_module import wrapper_for_vars, ExecutorManager

    def _drain_executor():
        ex = ExecutorManager._thread_executor
        if ex is not None:
            try:
                ex.shutdown(wait=True)
            except Exception:
                pass
            ExecutorManager._thread_executor = None

    try:
        _drain_executor()
        with open(pickle_path, "rb") as f:
            payload = pickle.load(f)
        result = wrapper_for_vars(payload)
        _drain_executor()
        return result
    except Exception as e:
        _drain_executor()
        print(f"Sensitivity scenario failed: {e}\n{traceback.format_exc()}")
        return None


# ---------------------------------------------------------------------------
# Output stripping
# ---------------------------------------------------------------------------

def fn_strip_sensitivity_result(result: Optional[Dict]) -> Optional[Dict]:
    """
    Strips a single wrapper_for_vars output down to the sensitivity-relevant
    subset: only the pre-computed per-asset net cashflow DataFrame
    (Net CFO + Net CFI − Land in Kind, one row per asset, columns = periods).
    All other output sections are discarded to keep sensitivity payloads small.
    """
    if result is None:
        return None

    monthly_dfs = result.get("exceloutput", {}).get("monthly_dfs", {})
    asset_net_cf = monthly_dfs.get("Asset Net Cashflows")
    if asset_net_cf is None:
        return None

    return {
        "exceloutput": {
            "monthly_dfs": {
                "Asset Net Cashflows": asset_net_cf,
            }
        }
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fn_run_landco_sensitivity(
    payload: List[Dict],
) -> Optional[List[Dict]]:
    """
    Runs a 25-scenario sensitivity analysis on the LandCo model.

    Reads two sensitivity labels and step percentages from
    'a.landco.sensitivity' (rows: [[label1, pct1], [label2, pct2]]).

    Generates 5 multiplier steps for each label:
        -2x pct,  -1x pct,  base (1.0),  +1x pct,  +2x pct

    Produces all 25 combinations (5 × 5), modifies the relevant fields in
    a.landco.global.value and a.landco.asset.data for each scenario, and
    runs all 25 modified payloads through wrapper_for_vars in parallel via
    ProcessPoolExecutor.

    Returns:
        List of 25 dicts ordered (label1_step outermost, label2_step inner):
            [{"scenario": "<label1>_<±pct>%__<label2>_<±pct>%",
              "result":   <wrapper_for_vars output>}, ...]
        Returns None on unrecoverable error.
    """
    try:
        param1, param2 = extract_sensitivity_params(payload, "a.landco.sensitivity")
        if param1 is None or param2 is None:
            print(
                "fn_run_landco_sensitivity: 'a.landco.sensitivity' named range "
                "not found or malformed — aborting sensitivity run."
            )
            return None

        label1, pct1 = param1
        label2, pct2 = param2

        if label1 not in _LABEL_GLOBAL_ATTR_MAP and label1 not in _LABEL_ASSET_COL_MAP:
            print(
                f"fn_run_landco_sensitivity: label '{label1}' has no field mapping — "
                "no values will be scaled for this label."
            )
        if label2 not in _LABEL_GLOBAL_ATTR_MAP and label2 not in _LABEL_ASSET_COL_MAP:
            print(
                f"fn_run_landco_sensitivity: label '{label2}' has no field mapping — "
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

        global_attr_idx, asset_col_idx = build_index_maps(payload, "a.landco")

        scenario_labels: List[str] = []
        pickle_paths: List[str] = []

        for m1 in steps1:
            for m2 in steps2:
                modified = apply_multipliers(
                    payload, label1, m1, label2, m2,
                    global_attr_idx, asset_col_idx,
                    _LABEL_GLOBAL_ATTR_MAP, _LABEL_ASSET_COL_MAP,
                    "a.landco.global.value", "a.landco.asset.data",
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
            {"scenario": scenario_labels[k], "result": results[k]}
            for k in range(len(scenario_labels))
        ]

    except Exception as e:
        print(f"fn_run_landco_sensitivity error: {e}\n{traceback.format_exc()}")
        return None
