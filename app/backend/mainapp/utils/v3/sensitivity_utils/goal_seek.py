"""
Goal seek for LandCo and DevCo models.

Reads parameters from 'a.<module>.goal.seek' (2×2 named range):
    values[0] = [variable_label, ""]    e.g. ["Infrastructure Cost", ""]
    values[1] = [target_metric, target] e.g. ["XNPV", 2_000_000_000]

For LandCo, the XNPV basis is:
    Net Cashflow from Operations
  + Net Cashflow from Investments
  - Land in Kind  (sign-flipped because it is a financing inflow)

The goal seek does NOT re-run the model.  It uses the linear relationship:
    XNPV_new(δ) = XNPV_base + δ × XNPV_variable
where XNPV_variable is the XNPV of the variable's own cashflow rows.
Solving for δ:
    δ = (target − XNPV_base) / XNPV_variable
    % change required = δ × 100

Discount rate is read from the model's global attribute 'discount_rate'.
Dates are read from the Monthly Timeline in the base scenario output.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional, Tuple

from mainapp.utils.v3.sensitivity_utils.financial_functions import xnpv, _to_date


# ---------------------------------------------------------------------------
# Variable → cashflow row mappings
# ---------------------------------------------------------------------------

# Each entry is a list of (monthly_dfs key, row name, sign) tuples.
# sign=+1 → use the row value as-is; sign=-1 → negate the row.
_LANDCO_VARIABLE_CF_MAP: Dict[str, List[Tuple[str, str, int]]] = {
    "Infrastructure Cost": [
        ("Cashflow from Investments", "Primary Infrastructure Cost",   1),
        ("Cashflow from Investments", "Secondary Infrastructure Cost", 1),
    ],
    "Land Sales Price": [
        ("Cashflow from Operations", "On-plan Sales Collection", 1),
        ("Cashflow from Operations", "Off-plan Sales Collection", 1),
    ],
}

# LandCo XNPV basis: rows that form the total cashflow.
_LANDCO_XNPV_BASIS: List[Tuple[str, str, int]] = [
    ("Cashflow from Operations",   "Net Cashflow from Operations",   1),
    ("Cashflow from Investments",  "Net Cashflow from Investments",  1),
    ("Cashflow from Financing",    "Land in Kind",                  -1),
]

# DevCo mappings — extend when DevCo goal seek CF composition is confirmed.
_DEVCO_VARIABLE_CF_MAP: Dict[str, List[Tuple[str, str, int]]] = {
    "Vertical Construction Cost": [
        ("Cashflow from Investments", "Vertical Construction Cost", 1),
    ],
}

_DEVCO_XNPV_BASIS: List[Tuple[str, str, int]] = [
    ("Cashflow from Operations",  "Net Cashflow from Operations",  1),
    ("Cashflow from Investments", "Net Cashflow from Investments", 1),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_goal_seek_params(
    payload: List[Dict],
    named_range_name: str,
) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """
    Reads the 2×2 goal seek named range and returns
        (variable_label, target_metric, target_value).
    Returns (None, None, None) when the range is missing or malformed.
    """
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("name") != named_range_name:
            continue
        values = item.get("values", [])
        if len(values) >= 2 and len(values[0]) >= 1 and len(values[1]) >= 2:
            variable_label = str(values[0][0]).strip()
            target_metric  = str(values[1][0]).strip()
            try:
                target_value = float(values[1][1])
            except (TypeError, ValueError):
                return None, None, None
            return variable_label, target_metric, target_value
    return None, None, None


def _get_discount_rate(payload: List[Dict], prefix: str) -> float:
    """
    Reads 'discount_rate' from <prefix>.global.attribute / .global.value.
    Falls back to 0.10 if not found.
    """
    attrs: List[str] = []
    vals:  List[Any] = []

    for item in payload:
        name = item.get("name", "")
        if name == f"{prefix}.global.attribute":
            attrs = [r[0] if r else "" for r in item.get("values", [])]
        elif name == f"{prefix}.global.value":
            vals = [r[0] if r else None for r in item.get("values", [])]

    if "discount_rate" in attrs:
        idx = attrs.index("discount_rate")
        try:
            return float(vals[idx])
        except (TypeError, ValueError):
            pass
    return 0.10


def _get_irr_params(payload: List[Dict], prefix: str) -> Dict:
    """
    Reads MIRR finance/reinvestment rates and the IRR calculation option
    (Monthly / Quarterly / Annual) from global attributes.
    Falls back to 10 % / 10 % / Monthly if not found.
    """
    attrs: List[str] = []
    vals:  List[Any] = []

    for item in payload:
        name = item.get("name", "")
        if name == f"{prefix}.global.attribute":
            attrs = [r[0] if r else "" for r in item.get("values", [])]
        elif name == f"{prefix}.global.value":
            vals = [r[0] if r else None for r in item.get("values", [])]

    def _read(key: str, default: Any) -> Any:
        if key in attrs:
            try:
                v = vals[attrs.index(key)]
                return v if v is not None else default
            except (IndexError, KeyError):
                pass
        return default

    return {
        "finance_rate":  float(_read("mirr_finance_rate",      0.10)),
        "reinvest_rate": float(_read("mirr_reinvestment_rate", 0.10)),
        "option":        str(_read("irr_calculation_option",   "Monthly")).strip(),
    }


def _group_cashflows(cashflows: List[float], option: str) -> List[float]:
    """
    Aggregates monthly cashflows into sub-periods.
    Monthly → unchanged.  Quarterly → sum each 3 months.  Annual → sum each 12.
    """
    opt = option.strip().lower()
    if opt == "monthly":
        return list(cashflows)
    step = 3 if opt == "quarterly" else 12
    return [sum(cashflows[i : i + step]) for i in range(0, len(cashflows), step)]


def _compute_mirr_annual(
    cashflows:           List[float],
    finance_rate_annual: float,
    reinvest_rate_annual: float,
    option:              str,
) -> Optional[float]:
    """
    Computes annualised MIRR with sub-period compounding.

    Steps
    -----
    1. Determine sub-period count n (12 / 4 / 1 for Monthly / Quarterly / Annual).
    2. Convert annual rates to sub-period: r_sub = (1 + r_annual)^(1/n) - 1.
    3. Aggregate monthly cashflows into sub-periods.
    4. Compute MIRR(grouped, sub_fr, sub_rr) → sub-period MIRR.
    5. Re-compound to annual: (1 + mirr_sub)^n - 1.
    """
    from mainapp.utils.v3.sensitivity_utils.financial_functions import mirr as _mirr

    opt = option.strip().lower()
    n   = 12 if opt == "monthly" else (4 if opt == "quarterly" else 1)

    sub_fr = (1.0 + finance_rate_annual)  ** (1.0 / n) - 1.0
    sub_rr = (1.0 + reinvest_rate_annual) ** (1.0 / n) - 1.0

    grouped  = _group_cashflows(cashflows, option)
    mirr_sub = _mirr(grouped, sub_fr, sub_rr)
    if mirr_sub is None:
        return None
    return (1.0 + mirr_sub) ** n - 1.0


def _extract_row(json_df: Dict, row_name: str) -> List[float]:
    """
    Extracts a single named row from a JSON-serialised DataFrame as a list
    of floats.  None / missing values are treated as 0.
    """
    index = json_df.get("index", [])
    data  = json_df.get("data",  [])
    for i, name in enumerate(index):
        if name == row_name:
            return [float(v) if v is not None else 0.0 for v in data[i]]
    return []


def _extract_row_raw(json_df: Dict, row_name: str) -> List[Any]:
    """Extracts a single named row as raw values (no type conversion)."""
    index = json_df.get("index", [])
    data  = json_df.get("data",  [])
    for i, name in enumerate(index):
        if name == row_name:
            return [v for v in data[i]]
    return []


def _get_dates(base_result: Dict) -> List[Any]:
    """
    Extracts period-end dates from the Monthly Timeline in the base result.
    Period End matches Excel's XNPV convention: cashflows are at month-end.
    Returns a list of date-like objects usable by xnpv().
    """
    monthly_dfs = base_result.get("exceloutput", {}).get("monthly_dfs", {})
    timeline_entry = monthly_dfs.get("Monthly Timeline")
    if not timeline_entry:
        return []
    json_df = timeline_entry[1]
    return _extract_row_raw(json_df, "Period End")


def _combine_rows(
    monthly_dfs: Dict,
    spec: List[Tuple[str, str, int]],
    n_periods: int,
) -> List[float]:
    """
    Sums signed cashflow rows from monthly_dfs into a single list of n_periods
    floats.  Missing rows contribute zeros.
    """
    total = [0.0] * n_periods
    for sheet_key, row_name, sign in spec:
        entry = monthly_dfs.get(sheet_key)
        if not entry:
            continue
        row = _extract_row(entry[1], row_name)
        for t in range(min(len(row), n_periods)):
            total[t] += sign * row[t]
    return total


def _run_goal_seek(
    payload:      List[Dict],
    base_result:  Dict,
    named_range:  str,
    prefix:       str,
    variable_map: Dict[str, List[Tuple[str, str, int]]],
    xnpv_basis:   List[Tuple[str, str, int]],
    module_label: str,
) -> Optional[Dict]:
    """
    Core goal seek logic shared by both modules.
    """
    variable_label, target_metric, target_value = _extract_goal_seek_params(
        payload, named_range
    )
    if variable_label is None:
        print(
            f"[{module_label} goal seek] '{named_range}' not found or malformed."
        )
        return None

    _SUPPORTED = {"XNPV", "MIRR", "XIRR"}
    metric_upper = target_metric.upper()
    if metric_upper not in _SUPPORTED:
        print(
            f"[{module_label} goal seek] '{target_metric}' not supported. "
            f"Supported: {_SUPPORTED}"
        )
        return None

    if variable_label not in variable_map:
        print(f"[{module_label} goal seek] Variable '{variable_label}' has no CF mapping.")
        return None

    dates = _get_dates(base_result)
    if not dates:
        print(f"[{module_label} goal seek] Monthly Timeline not found in base result.")
        return None

    n = len(dates)
    monthly_dfs = base_result.get("exceloutput", {}).get("monthly_dfs", {})
    total_cf    = _combine_rows(monthly_dfs, xnpv_basis,                   n)
    variable_cf = _combine_rows(monthly_dfs, variable_map[variable_label], n)

    # ── XNPV — exact linear decomposition ───────────────────────────────────
    if metric_upper == "XNPV":
        rate        = _get_discount_rate(payload, prefix)
        base_metric = xnpv(rate, total_cf,    dates)
        xnpv_var    = xnpv(rate, variable_cf, dates)
        if xnpv_var == 0.0:
            print(f"[{module_label} goal seek] XNPV of variable cashflows is zero.")
            return None
        delta      = (target_value - base_metric) / xnpv_var
        pct_change = round(delta * 100, 6)
        return {
            "variable":            variable_label,
            "target_metric":       target_metric,
            "target_value":        target_value,
            "base_xnpv":           round(base_metric, 2),
            "xnpv_variable":       round(xnpv_var, 2),
            "pct_change_required": pct_change,
            "discount_rate":       _get_discount_rate(payload, prefix),
        }

    # ── MIRR — finite-difference with sub-period compounding ─────────────────
    if metric_upper == "MIRR":
        irr_p = _get_irr_params(payload, prefix)
        fr, rr, opt = irr_p["finance_rate"], irr_p["reinvest_rate"], irr_p["option"]

        base_metric = _compute_mirr_annual(total_cf, fr, rr, opt)
        if base_metric is None:
            print(f"[{module_label} goal seek] Cannot compute base MIRR.")
            return None

        perturbed_cf = [tc + vc for tc, vc in zip(total_cf, variable_cf)]
        mirr_pert    = _compute_mirr_annual(perturbed_cf, fr, rr, opt)
        if mirr_pert is None:
            print(f"[{module_label} goal seek] Cannot compute perturbed MIRR.")
            return None

        sensitivity = mirr_pert - base_metric
        if sensitivity == 0.0:
            print(f"[{module_label} goal seek] MIRR sensitivity is zero — cannot solve.")
            return None

        delta      = (target_value - base_metric) / sensitivity
        pct_change = round(delta * 100, 6)
        return {
            "variable":            variable_label,
            "target_metric":       target_metric,
            "target_value":        target_value,
            "base_mirr":           round(base_metric,  8),
            "mirr_sensitivity":    round(sensitivity,  8),
            "pct_change_required": pct_change,
            "finance_rate":        fr,
            "reinvest_rate":       rr,
            "irr_option":          opt,
        }

    # ── XIRR — finite-difference using exact dates ───────────────────────────
    from mainapp.utils.v3.sensitivity_utils.financial_functions import xirr as _xirr

    base_metric = _xirr(total_cf, dates)
    if base_metric is None:
        print(
            f"[{module_label} goal seek] XIRR of base cashflows did not converge "
            "(requires at least one sign change in total cashflows)."
        )
        return None

    perturbed_cf = [tc + vc for tc, vc in zip(total_cf, variable_cf)]
    xirr_pert    = _xirr(perturbed_cf, dates)
    if xirr_pert is None:
        print(f"[{module_label} goal seek] XIRR of perturbed cashflows did not converge.")
        return None

    sensitivity = xirr_pert - base_metric
    if sensitivity == 0.0:
        print(f"[{module_label} goal seek] XIRR sensitivity is zero — cannot solve.")
        return None

    delta      = (target_value - base_metric) / sensitivity
    pct_change = round(delta * 100, 6)
    return {
        "variable":            variable_label,
        "target_metric":       target_metric,
        "target_value":        target_value,
        "base_xirr":           round(base_metric, 8),
        "xirr_sensitivity":    round(sensitivity, 8),
        "pct_change_required": pct_change,
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def fn_run_landco_goal_seek(
    payload:     List[Dict],
    base_result: Dict,
) -> Optional[Dict]:
    """
    Runs the LandCo goal seek using the base scenario output.

    Reads parameters from 'a.landco.goal.seek', computes XNPV from
    Net CFO + Net CFI − Land in Kind, and returns the % change required
    in the variable to hit the target XNPV.
    """
    try:
        return _run_goal_seek(
            payload      = payload,
            base_result  = base_result,
            named_range  = "a.landco.goal.seek",
            prefix       = "a.landco",
            variable_map = _LANDCO_VARIABLE_CF_MAP,
            xnpv_basis   = _LANDCO_XNPV_BASIS,
            module_label = "LandCo",
        )
    except Exception as e:
        print(f"fn_run_landco_goal_seek error: {e}\n{traceback.format_exc()}")
        return None


def fn_run_devco_goal_seek(
    payload:     List[Dict],
    base_result: Dict,
) -> Optional[Dict]:
    """
    Runs the DevCo goal seek using the base scenario output.

    Reads parameters from 'a.devco.goal.seek', computes XNPV from
    Net CFO + Net CFI, and returns the % change required in the variable
    to hit the target XNPV.
    """
    try:
        return _run_goal_seek(
            payload      = payload,
            base_result  = base_result,
            named_range  = "a.devco.goal.seek",
            prefix       = "a.devco",
            variable_map = _DEVCO_VARIABLE_CF_MAP,
            xnpv_basis   = _DEVCO_XNPV_BASIS,
            module_label = "DevCo",
        )
    except Exception as e:
        print(f"fn_run_devco_goal_seek error: {e}\n{traceback.format_exc()}")
        return None


# ---------------------------------------------------------------------------
# Iterative goal seek — payload field mappings
# (mirrors the sensitivity label maps for apply_multipliers compatibility)
# ---------------------------------------------------------------------------

_LANDCO_ITER_GLOBAL_MAP: Dict[str, List[str]] = {
    "Infrastructure Cost": [
        "primary_infrastructure_cost_per_sqm",
        "primary_infrastructure_ad_hoc_amount",
        "secondary_infrastructure_cost_per_sqm",
        "secondary_infrastructure_ad_hoc_amount",
    ],
    "Land Sales Price": [
        "sales_price",
    ],
}
_LANDCO_ITER_ASSET_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Infrastructure Cost": [
        ("PrimaryInfrastructureModule",   "cost_per_sqm"),
        ("PrimaryInfrastructureModule",   "ad_hoc_amount"),
        ("SecondaryInfrastructureModule", "cost_per_sqm"),
        ("SecondaryInfrastructureModule", "ad_hoc_amount"),
    ],
    "Land Sales Price": [
        ("LandSalesModule", "sales_price"),
    ],
}

_DEVCO_ITER_GLOBAL_MAP: Dict[str, List[str]] = {
    "Vertical Construction Cost": [],
}
_DEVCO_ITER_ASSET_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Vertical Construction Cost": [
        ("VerticalDevelopmentModule", "vd_cost_per_sqm"),
    ],
}

# AssetCo mappings
_ASSETCO_VARIABLE_CF_MAP: Dict[str, List[Tuple[str, str, int]]] = {
    "Forecast Base Rent": [
        ("Cashflow from Operations", "Base Rent", 1),
    ],
}

_ASSETCO_XNPV_BASIS: List[Tuple[str, str, int]] = [
    ("Cashflow from Operations",  "Total Net Cashflow from Operations", 1),
    ("Cashflow from Investments", "Net Cashflow from Investments",      1),
]

_ASSETCO_ITER_GLOBAL_MAP: Dict[str, List[str]] = {
    "Forecast Base Rent": [],
}
_ASSETCO_ITER_UNIT_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Forecast Base Rent": [
        ("RentParametersFirstTenant",  "forecast_base_rent"),
        ("RentParametersSecondTenant", "forecast_base_rent"),
    ],
}


# ---------------------------------------------------------------------------
# Subprocess worker for iterative goal seek
# ---------------------------------------------------------------------------

def _goal_seek_worker(args: Tuple) -> Tuple[float, Optional[float]]:
    """
    Module-level subprocess worker.  Applies pct_change to the goal seek
    variable, runs wrapper_for_vars, and returns (pct_change, metric_value).
    metric_config selects the metric: {"metric": "XNPV"|"MIRR"|"XIRR", ...}
    Must be module-level for pickle compatibility with ProcessPoolExecutor.
    """
    (pkl_path, pct_change, module_name,
     variable_label, label_global_map, label_asset_map,
     prefix, global_value_key, asset_data_key,
     xnpv_basis_spec, metric_config) = args

    import os
    import pickle
    import traceback as _tb

    try:
        with open(pkl_path, "rb") as f:
            payload = pickle.load(f)

        from mainapp.utils.v3.sensitivity_utils.common import (
            build_index_maps, apply_multipliers,
        )
        global_attr_idx, asset_col_idx = build_index_maps(payload, prefix)
        mult = 1.0 + pct_change / 100.0

        modified_payload = apply_multipliers(
            payload,
            variable_label, mult,
            "",             1.0,   # dummy second label → no-op
            global_attr_idx, asset_col_idx,
            label_global_map, label_asset_map,
            global_value_key, asset_data_key,
        )

        if module_name == "landco":
            from mainapp.utils.sensitivity.landco_module import wrapper_for_vars, ExecutorManager
            try:
                if ExecutorManager._thread_executor is not None:
                    ExecutorManager._thread_executor.shutdown(wait=True)
                    ExecutorManager._thread_executor = None
            except Exception:
                pass
        else:
            from mainapp.utils.sensitivity.devco_model import wrapper_for_vars, ExecutorManager
            try:
                if ExecutorManager._thread_executor is not None:
                    ExecutorManager._thread_executor.shutdown(wait=True)
                    ExecutorManager._thread_executor = None
                if ExecutorManager._process_executor is not None:
                    ExecutorManager._process_executor.shutdown(wait=True)
                    ExecutorManager._process_executor = None
            except Exception:
                pass

        result = wrapper_for_vars(modified_payload)
        if result is None:
            return pct_change, None

        dates = _get_dates(result)
        if not dates:
            return pct_change, None

        n = len(dates)
        monthly_dfs = result.get("exceloutput", {}).get("monthly_dfs", {})
        total_cf    = _combine_rows(monthly_dfs, xnpv_basis_spec, n)

        metric = (metric_config or {}).get("metric", "XNPV").upper()

        if metric == "XNPV":
            rate = _get_discount_rate(modified_payload, prefix)
            return pct_change, xnpv(rate, total_cf, dates)

        if metric == "MIRR":
            fr  = metric_config.get("finance_rate",  0.10)
            rr  = metric_config.get("reinvest_rate", 0.10)
            opt = metric_config.get("option",        "Monthly")
            return pct_change, _compute_mirr_annual(total_cf, fr, rr, opt)

        # XIRR
        from mainapp.utils.v3.sensitivity_utils.financial_functions import xirr as _xirr
        return pct_change, _xirr(total_cf, dates)

    except Exception as e:
        print(f"_goal_seek_worker error at pct={pct_change}: {e}\n{_tb.format_exc()}")
        return pct_change, None
    finally:
        try:
            os.remove(pkl_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Iterative core: parallel trisection
# ---------------------------------------------------------------------------

def _run_trisection_goal_seek(
    payload:          List[Dict],
    base_result:      Dict,
    named_range:      str,
    prefix:           str,
    module_name:      str,
    variable_map:     Dict[str, List[Tuple[str, str, int]]],
    xnpv_basis:       List[Tuple[str, str, int]],
    label_global_map: Dict[str, List[str]],
    label_asset_map:  Dict[str, List[Tuple[str, str]]],
    global_value_key: str,
    asset_data_key:   str,
    module_label:     str,
    max_rounds:       int            = 25,
    tolerance:        Optional[float] = None,   # auto: 1.0 SAR for XNPV, 1e-8 for MIRR/XIRR
) -> Optional[Dict]:
    """
    Iterative goal seek using parallel trisection.

    Each round evaluates two interior points simultaneously via
    ProcessPoolExecutor(max_workers=2), reducing the bracket by 1/3 per
    round.  This gives ~37 % less wall-clock time vs sequential bisection
    for the same final precision.

    Algorithm
    ---------
    1. Compute linear estimate (zero model re-runs).
    2. Establish bracket [lo, hi] centred on linear_pct ± spread; confirm
       with 2 parallel model runs.
    3. Each trisection round: split [lo, hi] at t1 = lo+width/3 and
       t2 = lo+2*width/3; run both in parallel; narrow bracket to the
       sub-interval that contains the root; repeat until converged.
    """
    from concurrent.futures import ProcessPoolExecutor
    from mainapp.utils.v3.sensitivity_utils.common import serialize_sensitivity_payload

    # Step 1 — linear estimate (fast, no model re-run)
    linear_result = _run_goal_seek(
        payload, base_result, named_range, prefix,
        variable_map, xnpv_basis, module_label,
    )
    if linear_result is None:
        return None

    variable_label = linear_result["variable"]
    target_metric  = linear_result["target_metric"]
    target_value   = linear_result["target_value"]
    linear_pct     = linear_result["pct_change_required"]
    metric_upper   = target_metric.upper()

    # Base metric value and auto-tolerance
    if metric_upper == "XNPV":
        base_metric_value = linear_result["base_xnpv"]
        if tolerance is None:
            tolerance = 1.0                       # 1 SAR
        metric_config = {"metric": "XNPV", "discount_rate": linear_result["discount_rate"]}
    elif metric_upper == "MIRR":
        base_metric_value = linear_result["base_mirr"]
        if tolerance is None:
            tolerance = 1e-8                      # ~0.000001 %
        metric_config = {
            "metric":       "MIRR",
            "finance_rate":  linear_result["finance_rate"],
            "reinvest_rate": linear_result["reinvest_rate"],
            "option":        linear_result["irr_option"],
        }
    else:  # XIRR
        base_metric_value = linear_result["base_xirr"]
        if tolerance is None:
            tolerance = 1e-8
        metric_config = {"metric": "XIRR"}

    # Step 2 — initial bracket centred on linear estimate
    spread = max(abs(linear_pct) * 2.0, 50.0)
    lo_pct = max(linear_pct - spread, -95.0)
    hi_pct = min(linear_pct + spread, 500.0)

    def _make_args(pct: float) -> Tuple:
        pkl_path = serialize_sensitivity_payload((payload))
        return (
            pkl_path, pct, module_name,
            variable_label, label_global_map, label_asset_map,
            prefix, global_value_key, asset_data_key,
            xnpv_basis, metric_config,
        )

    print(f"[{module_label} iterative] Metric: {target_metric}  |  Linear estimate: {linear_pct:.6f}%")
    print(f"[{module_label} iterative] Confirming bracket [{lo_pct:.4f}%, {hi_pct:.4f}%]...")

    with ProcessPoolExecutor(max_workers=2) as ex:
        fut_lo = ex.submit(_goal_seek_worker, _make_args(lo_pct))
        fut_hi = ex.submit(_goal_seek_worker, _make_args(hi_pct))
        _, metric_lo = fut_lo.result()
        _, metric_hi = fut_hi.result()

    if metric_lo is None or metric_hi is None:
        print(f"[{module_label} iterative] Bracket evaluation failed.")
        return None

    total_evals = 2

    if (metric_lo - target_value) * (metric_hi - target_value) > 0:
        print(
            f"[{module_label} iterative] Root not bracketed — "
            f"{target_metric}({lo_pct:.2f}%)={metric_lo}, "
            f"{target_metric}({hi_pct:.2f}%)={metric_hi}, target={target_value}"
        )
        return None

    # Step 3 — trisection: 2 parallel evaluations per round
    final_pct    = (lo_pct + hi_pct) / 2.0
    final_metric = None

    with ProcessPoolExecutor(max_workers=2) as ex:
        for rnd in range(max_rounds):
            t1_pct = lo_pct + (hi_pct - lo_pct) / 3.0
            t2_pct = lo_pct + 2.0 * (hi_pct - lo_pct) / 3.0

            fut1 = ex.submit(_goal_seek_worker, _make_args(t1_pct))
            fut2 = ex.submit(_goal_seek_worker, _make_args(t2_pct))
            _, m1 = fut1.result()
            _, m2 = fut2.result()
            total_evals += 2

            if m1 is None or m2 is None:
                print(f"[{module_label} iterative] Worker error at round {rnd + 1}.")
                break

            if abs(m1 - target_value) <= tolerance:
                final_pct, final_metric = t1_pct, m1
                print(f"[{module_label} iterative] Converged at round {rnd + 1}.")
                break
            if abs(m2 - target_value) <= tolerance:
                final_pct, final_metric = t2_pct, m2
                print(f"[{module_label} iterative] Converged at round {rnd + 1}.")
                break

            if (metric_lo - target_value) * (m1 - target_value) <= 0:
                hi_pct, metric_hi = t1_pct, m1
            elif (m1 - target_value) * (m2 - target_value) <= 0:
                lo_pct, metric_lo = t1_pct, m1
                hi_pct, metric_hi = t2_pct, m2
            else:
                lo_pct, metric_lo = t2_pct, m2

            final_pct = (lo_pct + hi_pct) / 2.0
            print(
                f"  [{module_label}] Round {rnd + 1:2d}: "
                f"bracket=[{lo_pct:.6f}%, {hi_pct:.6f}%], "
                f"width={hi_pct - lo_pct:.8f}%"
            )
        else:
            print(f"[{module_label} iterative] Max rounds ({max_rounds}) reached.")

    if final_metric is None:
        with ProcessPoolExecutor(max_workers=1) as ex:
            _, final_metric = ex.submit(_goal_seek_worker, _make_args(final_pct)).result()
        total_evals += 1
        if final_metric is None:
            final_metric = (metric_lo + metric_hi) / 2.0

    return {
        "variable":             variable_label,
        "target_metric":        target_metric,
        "target_value":         target_value,
        "base_metric_value":    round(base_metric_value, 8),
        "pct_change_required":  round(final_pct, 6),
        "achieved_metric_value": round(final_metric, 8),
        "metric_error":         round(abs(final_metric - target_value), 10),
        "model_evaluations":    total_evals,
        "linear_pct_change":    linear_pct,
    }


# ---------------------------------------------------------------------------
# Public entry points — iterative
# ---------------------------------------------------------------------------

def fn_run_landco_goal_seek_iterative(
    payload:     List[Dict],
    base_result: Dict,
    max_rounds:  int   = 25,
    tolerance:   Optional[float] = None,
) -> Optional[Dict]:
    """
    Runs the LandCo iterative goal seek via parallel trisection.

    Re-runs wrapper_for_vars with adjusted Infrastructure Cost inputs until
    the actual model XNPV converges to the target within `tolerance` SAR.
    Each trisection round runs two model evaluations in parallel.

    Returns the same dict as fn_run_landco_goal_seek plus:
        achieved_xnpv      — actual XNPV at the final pct_change
        xnpv_error         — |achieved_xnpv − target_value|
        model_evaluations  — total wrapper_for_vars calls made
        linear_pct_change  — the one-shot linear estimate (for comparison)
    """
    try:
        return _run_trisection_goal_seek(
            payload          = payload,
            base_result      = base_result,
            named_range      = "a.landco.goal.seek",
            prefix           = "a.landco",
            module_name      = "landco",
            variable_map     = _LANDCO_VARIABLE_CF_MAP,
            xnpv_basis       = _LANDCO_XNPV_BASIS,
            label_global_map = _LANDCO_ITER_GLOBAL_MAP,
            label_asset_map  = _LANDCO_ITER_ASSET_MAP,
            global_value_key = "a.landco.global.value",
            asset_data_key   = "a.landco.asset.data",
            module_label     = "LandCo",
            max_rounds       = max_rounds,
            tolerance        = tolerance,
        )
    except Exception as e:
        print(f"fn_run_landco_goal_seek_iterative error: {e}\n{traceback.format_exc()}")
        return None


def fn_run_devco_goal_seek_iterative(
    payload:     List[Dict],
    base_result: Dict,
    max_rounds:  int   = 25,
    tolerance:   Optional[float] = None,
) -> Optional[Dict]:
    """
    Runs the DevCo iterative goal seek via parallel trisection.

    Re-runs wrapper_for_vars with adjusted Vertical Construction Cost inputs
    until the actual model XNPV converges to the target within `tolerance` SAR.
    """
    try:
        return _run_trisection_goal_seek(
            payload          = payload,
            base_result      = base_result,
            named_range      = "a.devco.goal.seek",
            prefix           = "a.devco",
            module_name      = "devco",
            variable_map     = _DEVCO_VARIABLE_CF_MAP,
            xnpv_basis       = _DEVCO_XNPV_BASIS,
            label_global_map = _DEVCO_ITER_GLOBAL_MAP,
            label_asset_map  = _DEVCO_ITER_ASSET_MAP,
            global_value_key = "a.devco.global.value",
            asset_data_key   = "a.devco.asset.data",
            module_label     = "DevCo",
            max_rounds       = max_rounds,
            tolerance        = tolerance,
        )
    except Exception as e:
        print(f"fn_run_devco_goal_seek_iterative error: {e}\n{traceback.format_exc()}")
        return None

# ---------------------------------------------------------------------------
# AssetCo goal seek — subprocess worker
# (module-level for pickle compatibility with ProcessPoolExecutor)
# ---------------------------------------------------------------------------

def _assetco_goal_seek_worker(args: Tuple) -> Tuple[float, Optional[float]]:
    """
    Subprocess worker for AssetCo iterative goal seek.
    Applies pct_change to Forecast Base Rent, runs wrapper_for_vars,
    and returns (pct_change, metric_value).
    AssetCo result has monthly_dfs at top level (no exceloutput wrapper).
    """
    pkl_path, pct_change, xnpv_basis_spec, metric_config = args

    import os
    import pickle
    import traceback as _tb

    try:
        with open(pkl_path, "rb") as f:
            payload, _ = pickle.load(f)

        from mainapp.utils.v3.sensitivity_utils.assetco_sensitivity import build_assetco_index_maps
        from mainapp.utils.v3.sensitivity_utils.common import apply_multipliers

        global_attr_idx, unit_col_idx = build_assetco_index_maps(payload)
        mult = 1.0 + pct_change / 100.0

        modified_payload = apply_multipliers(
            payload,
            "Forecast Base Rent", mult,
            "",                   1.0,
            global_attr_idx, unit_col_idx,
            _ASSETCO_ITER_GLOBAL_MAP, _ASSETCO_ITER_UNIT_MAP,
            "a.assetco.global.value", "a.assetco.units.data",
        )

        from mainapp.utils.sensitivity.assetco_model import wrapper_for_vars
        result = wrapper_for_vars(modified_payload)
        if result is None:
            return pct_change, None

        monthly_dfs = result.get("monthly_dfs", {})

        timeline_entry = monthly_dfs.get("Monthly Timeline")
        if not timeline_entry:
            return pct_change, None
        dates = _extract_row_raw(timeline_entry[1], "Period End")
        if not dates:
            return pct_change, None

        n        = len(dates)
        total_cf = _combine_rows(monthly_dfs, xnpv_basis_spec, n)
        metric   = (metric_config or {}).get("metric", "XNPV").upper()

        if metric == "XNPV":
            rate = _get_discount_rate(modified_payload, "a.assetco")
            return pct_change, xnpv(rate, total_cf, dates)

        if metric == "MIRR":
            fr  = metric_config.get("finance_rate",  0.10)
            rr  = metric_config.get("reinvest_rate", 0.10)
            opt = metric_config.get("option",        "Monthly")
            return pct_change, _compute_mirr_annual(total_cf, fr, rr, opt)

        from mainapp.utils.v3.sensitivity_utils.financial_functions import xirr as _xirr
        return pct_change, _xirr(total_cf, dates)

    except Exception as e:
        print(f"_assetco_goal_seek_worker error at pct={pct_change}: {e}\n{_tb.format_exc()}")
        return pct_change, None
    finally:
        try:
            os.remove(pkl_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AssetCo public entry point — iterative goal seek
# ---------------------------------------------------------------------------

def fn_run_assetco_goal_seek_iterative(
    payload:     List[Dict],
    base_result: Dict,
    max_rounds:  int            = 25,
    tolerance:   Optional[float] = None,
) -> Optional[Dict]:
    """
    Runs the AssetCo iterative goal seek via parallel trisection.

    Reads parameters from 'a.assetco.goal.seek' (2×2 named range):
        values[0] = [variable_label, ""]    e.g. ["Forecast Base Rent", ""]
        values[1] = [target_metric, target] e.g. ["XNPV", 5_000_000_000]

    Supported variable: "Forecast Base Rent"
    Supported metrics:  XNPV, MIRR, XIRR

    AssetCo result has monthly_dfs at top level (no exceloutput wrapper).
    Uses build_assetco_index_maps + apply_multipliers on a.assetco.units.data.
    """
    try:
        from concurrent.futures import ProcessPoolExecutor
        from mainapp.utils.v3.sensitivity_utils.common import serialize_sensitivity_payload

        variable_label, target_metric, target_value = _extract_goal_seek_params(
            payload, "a.assetco.goal.seek"
        )
        if variable_label is None:
            print("[AssetCo goal seek] 'a.assetco.goal.seek' not found or malformed.")
            return None

        metric_upper = target_metric.upper()
        if metric_upper not in {"XNPV", "MIRR", "XIRR"}:
            print(f"[AssetCo goal seek] '{target_metric}' not supported. Use XNPV/MIRR/XIRR.")
            return None

        if variable_label not in _ASSETCO_VARIABLE_CF_MAP:
            print(f"[AssetCo goal seek] Variable '{variable_label}' has no CF mapping.")
            return None

        # AssetCo monthly_dfs is at top level
        assetco_monthly_dfs = base_result.get("monthly_dfs", {})
        timeline_entry = assetco_monthly_dfs.get("Monthly Timeline")
        if not timeline_entry:
            print("[AssetCo goal seek] Monthly Timeline not found in base result.")
            return None
        dates = _extract_row_raw(timeline_entry[1], "Period End")
        if not dates:
            print("[AssetCo goal seek] 'Period End' row missing from Monthly Timeline.")
            return None

        n           = len(dates)
        prefix      = "a.assetco"
        total_cf    = _combine_rows(assetco_monthly_dfs, _ASSETCO_XNPV_BASIS,                              n)
        variable_cf = _combine_rows(assetco_monthly_dfs, _ASSETCO_VARIABLE_CF_MAP[variable_label], n)

        # Linear estimate + metric config
        if metric_upper == "XNPV":
            rate        = _get_discount_rate(payload, prefix)
            base_metric = xnpv(rate, total_cf,    dates)
            xnpv_var    = xnpv(rate, variable_cf, dates)
            if xnpv_var == 0.0:
                print("[AssetCo goal seek] XNPV of variable cashflows is zero.")
                return None
            linear_pct = round((target_value - base_metric) / xnpv_var * 100, 6)
            if tolerance is None:
                tolerance = 1.0
            metric_config = {"metric": "XNPV"}

        elif metric_upper == "MIRR":
            irr_p       = _get_irr_params(payload, prefix)
            fr, rr, opt = irr_p["finance_rate"], irr_p["reinvest_rate"], irr_p["option"]
            base_metric = _compute_mirr_annual(total_cf, fr, rr, opt)
            if base_metric is None:
                print("[AssetCo goal seek] Cannot compute base MIRR.")
                return None
            pert_cf  = [tc + vc for tc, vc in zip(total_cf, variable_cf)]
            mirr_pert = _compute_mirr_annual(pert_cf, fr, rr, opt)
            if mirr_pert is None or (mirr_pert - base_metric) == 0.0:
                print("[AssetCo goal seek] MIRR sensitivity is zero or perturbed MIRR failed.")
                return None
            linear_pct = round((target_value - base_metric) / (mirr_pert - base_metric) * 100, 6)
            if tolerance is None:
                tolerance = 1e-8
            metric_config = {"metric": "MIRR", "finance_rate": fr, "reinvest_rate": rr, "option": opt}

        else:  # XIRR
            from mainapp.utils.v3.sensitivity_utils.financial_functions import xirr as _xirr
            base_metric = _xirr(total_cf, dates)
            if base_metric is None:
                print("[AssetCo goal seek] XIRR of base cashflows did not converge.")
                return None
            pert_cf   = [tc + vc for tc, vc in zip(total_cf, variable_cf)]
            xirr_pert = _xirr(pert_cf, dates)
            if xirr_pert is None or (xirr_pert - base_metric) == 0.0:
                print("[AssetCo goal seek] XIRR sensitivity is zero or perturbed XIRR failed.")
                return None
            linear_pct = round((target_value - base_metric) / (xirr_pert - base_metric) * 100, 6)
            if tolerance is None:
                tolerance = 1e-8
            metric_config = {"metric": "XIRR"}

        # Trisection bracket
        spread = max(abs(linear_pct) * 2.0, 50.0)
        lo_pct = max(linear_pct - spread, -95.0)
        hi_pct = min(linear_pct + spread, 500.0)

        def _make_args(pct: float) -> Tuple:
            pkl_path = serialize_sensitivity_payload((payload, True))
            return (pkl_path, pct, _ASSETCO_XNPV_BASIS, metric_config)

        print(f"[AssetCo iterative] Metric: {target_metric}  |  Linear estimate: {linear_pct:.6f}%")
        print(f"[AssetCo iterative] Confirming bracket [{lo_pct:.4f}%, {hi_pct:.4f}%]...")

        with ProcessPoolExecutor(max_workers=2) as ex:
            _, metric_lo = ex.submit(_assetco_goal_seek_worker, _make_args(lo_pct)).result()
            _, metric_hi = ex.submit(_assetco_goal_seek_worker, _make_args(hi_pct)).result()

        if metric_lo is None or metric_hi is None:
            print("[AssetCo iterative] Bracket evaluation failed.")
            return None

        total_evals = 2

        if (metric_lo - target_value) * (metric_hi - target_value) > 0:
            print(
                f"[AssetCo iterative] Root not bracketed — "
                f"{target_metric}({lo_pct:.2f}%)={metric_lo:.4f}, "
                f"{target_metric}({hi_pct:.2f}%)={metric_hi:.4f}, target={target_value}"
            )
            return None

        final_pct    = (lo_pct + hi_pct) / 2.0
        final_metric = None

        with ProcessPoolExecutor(max_workers=2) as ex:
            for rnd in range(max_rounds):
                t1_pct = lo_pct + (hi_pct - lo_pct) / 3.0
                t2_pct = lo_pct + 2.0 * (hi_pct - lo_pct) / 3.0

                _, m1 = ex.submit(_assetco_goal_seek_worker, _make_args(t1_pct)).result()
                _, m2 = ex.submit(_assetco_goal_seek_worker, _make_args(t2_pct)).result()
                total_evals += 2

                if m1 is None or m2 is None:
                    print(f"[AssetCo iterative] Worker error at round {rnd + 1}.")
                    break

                if abs(m1 - target_value) <= tolerance:
                    final_pct, final_metric = t1_pct, m1
                    print(f"[AssetCo iterative] Converged at round {rnd + 1}.")
                    break
                if abs(m2 - target_value) <= tolerance:
                    final_pct, final_metric = t2_pct, m2
                    print(f"[AssetCo iterative] Converged at round {rnd + 1}.")
                    break

                if (metric_lo - target_value) * (m1 - target_value) <= 0:
                    hi_pct, metric_hi = t1_pct, m1
                elif (m1 - target_value) * (m2 - target_value) <= 0:
                    lo_pct, metric_lo = t1_pct, m1
                    hi_pct, metric_hi = t2_pct, m2
                else:
                    lo_pct, metric_lo = t2_pct, m2

                final_pct = (lo_pct + hi_pct) / 2.0
                print(
                    f"  [AssetCo] Round {rnd + 1:2d}: "
                    f"bracket=[{lo_pct:.6f}%, {hi_pct:.6f}%], "
                    f"width={hi_pct - lo_pct:.8f}%"
                )
            else:
                print(f"[AssetCo iterative] Max rounds ({max_rounds}) reached.")

        if final_metric is None:
            with ProcessPoolExecutor(max_workers=1) as ex:
                _, final_metric = ex.submit(_assetco_goal_seek_worker, _make_args(final_pct)).result()
            total_evals += 1
            if final_metric is None:
                final_metric = (metric_lo + metric_hi) / 2.0

        return {
            "variable":              variable_label,
            "target_metric":         target_metric,
            "target_value":          target_value,
            "base_metric_value":     round(base_metric, 8),
            "pct_change_required":   round(final_pct, 6),
            "achieved_metric_value": round(final_metric, 8),
            "metric_error":          round(abs(final_metric - target_value), 10),
            "model_evaluations":     total_evals,
            "linear_pct_change":     linear_pct,
        }

    except Exception as e:
        print(f"fn_run_assetco_goal_seek_iterative error: {e}\n{traceback.format_exc()}")
        return None
