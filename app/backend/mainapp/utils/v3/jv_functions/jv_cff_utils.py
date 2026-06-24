"""
JV Consolidation - CFF (Cashflow from Financing) Utilities
============================================================

Contains:
  - Row-level list helpers (_zeros, _pad, _row_add, _row_negate, _to_float)
  - Interest rate profile reading (_read_interest_rate_profiles)
  - Monthly rate lookup (_get_monthly_rate)
  - Per-vehicle JV inputs resolution (_resolve_vehicle_jv_inputs)
  - Term loan schedule computation (_compute_term_loan)
  - Full CFF engine (_compute_cff)

All calculation logic is faithfully preserved from the archive.
"""

import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =====================================================================
# Scalar / Row Helpers
# =====================================================================

def _to_float(val) -> float:
    """Convert a value to float; return 0.0 for non-numeric."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _zeros(n: int) -> List[float]:
    """Return a zero-filled row of length *n*."""
    return [0.0] * n


def _pad(row: List[float], n: int) -> List[float]:
    """Ensure *row* has exactly *n* elements."""
    if len(row) >= n:
        return row[:n]
    return row + [0.0] * (n - len(row))


def _row_add(*rows: List[float]) -> List[float]:
    """Element-wise sum of multiple rows (all same length)."""
    if not rows:
        return []
    n = len(rows[0])
    return [sum(r[j] for r in rows) for j in range(n)]


def _row_negate(row: List[float]) -> List[float]:
    """Return element-wise negation of a row."""
    return [-v for v in row]


# =====================================================================
# Interest Rate Profile Reading
# =====================================================================

def _read_interest_rate_profiles(
    jv_df: pd.DataFrame,
    _read_array_fn,
    JV_INTEREST_PROFILES: str,
    DD_INTEREST_PROFILES: str,
    JV_INTEREST_VALUES: str,
) -> Dict[str, List[float]]:
    """
    Read interest rate profiles from ``j.jv.interest.rate.profiles`` and
    ``j.jv.interest.rate.values``.

    Returns a dict mapping profile name -> list of rates (as decimals).
    If the named ranges are absent, returns an empty dict.
    """
    profiles: Dict[str, List[float]] = {}

    profile_names_raw = _read_array_fn(jv_df, JV_INTEREST_PROFILES)
    profile_values_raw = _read_array_fn(jv_df, JV_INTEREST_VALUES)

    if not profile_names_raw or not profile_values_raw:
        # Try dd.jv prefix as fallback
        profile_names_raw = _read_array_fn(jv_df, DD_INTEREST_PROFILES)

    if not profile_names_raw or not profile_values_raw:
        return profiles

    # profile_values_raw shape depends on how the named range is stored:
    #   Case A — 2D (profiles × years): [[r00, r01, ...], [r10, r11, ...], ...]
    #            _read_array returns this as-is when row length > 1.
    #   Case B — column vector flattened by _read_array: [r00, r01, r02, ...]
    #            This happens when the sheet stores one profile as a single column,
    #            and _read_array collapses [[r00],[r01],...] -> [r00, r01, ...].
    #            In this case all values belong to the first (and only) profile.
    #
    # Detect Case B: profile_values_raw is a flat list of scalars.
    if profile_values_raw and not isinstance(profile_values_raw[0], list):
        # Wrap into a single-profile 2D structure so the loop below works uniformly.
        profile_values_raw = [profile_values_raw]

    # profile_names_raw could be a flat list of names or a 2D matrix
    # profile_values_raw is a 2D matrix where each row = one profile's rate values
    for i, name in enumerate(profile_names_raw):
        name_str = str(name).strip() if name is not None else ""
        if not name_str or name_str == "0":
            continue

        if i < len(profile_values_raw):
            raw_vals = profile_values_raw[i]
            if isinstance(raw_vals, list):
                rates = [_to_float(v) for v in raw_vals]
            else:
                rates = [_to_float(raw_vals)]

            # Rates stored as decimals (e.g. 0.05 = 5%) - use as-is per month
            profiles[name_str] = rates

    return profiles


# =====================================================================
# Monthly Interest Rate Lookup
# =====================================================================

def _get_monthly_rate(
    interest_profiles: Dict[str, List[float]],
    profile_name: Optional[str],
    period: int,
) -> float:
    """
    Look up the monthly interest rate for a given period from the profiles.
    If the profile is not found, returns 0.0.
    Profile rates are stored as annual decimals (year-wise); monthly rate is
    derived via monthly compounding: (1 + annual_rate)^(1/12) - 1.
    ``period`` is the absolute model month index (t); the year index is
    ``period // 12``, matching the calendar year columns in the profile table.
    """
    if not profile_name or not interest_profiles:
        return 0.0
    name_str = str(profile_name).strip()
    rates = interest_profiles.get(name_str, [])
    if not rates:
        return 0.0
    # Rates are year-wise against model calendar years — use absolute month index.
    year_idx = period // 12 if period >= 0 else 0
    idx = min(year_idx, len(rates) - 1)
    annual_rate = _to_float(rates[idx])
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


# =====================================================================
# Date -> Month Index
# =====================================================================

def _date_to_month_index(
    date_val, model_start: Optional[pd.Timestamp],
) -> Optional[int]:
    """
    Convert a date value to a 0-based month index relative to model_start.
    Returns None if date_val or model_start is not usable.
    """
    if date_val is None or model_start is None:
        return None
    try:
        ts = pd.Timestamp(date_val)
        if pd.isna(ts):
            return None
        # Month difference: (year_diff * 12) + month_diff
        return (ts.year - model_start.year) * 12 + (ts.month - model_start.month)
    except Exception:
        return None


# =====================================================================
# Per-Vehicle JV Inputs Resolution
# =====================================================================

def _resolve_vehicle_jv_inputs(
    jv_name: str,
    jv_asset_scenario_names: Optional[list],
    JVInputs,
    _safe_str_lower_fn,
) -> dict:
    """
    Resolve JV input parameters for a specific vehicle (jv_name).

    Returns a dict with all financing assumptions, GP/LP splits, fees,
    dates, and capital structure for the vehicle.

    Looks up the per-asset (JVInputs.Asset) row matching jv_name,
    falling back to JVInputs.Global for scalars.
    """
    jv_name_lower = jv_name.lower() if jv_name else ""
    ji = None  # matched asset index

    # Find matching row index in JVInputs.Asset
    if isinstance(jv_asset_scenario_names, list):
        for idx, sn in enumerate(jv_asset_scenario_names):
            if _safe_str_lower_fn(sn) == jv_name_lower:
                ji = idx
                break


    def _get_asset_val(cls, attr: str, default=None):
        """Get per-asset value from JVInputs.Asset at index ji."""
        if ji is None:
            return default
        val = getattr(cls, attr, None)
        if isinstance(val, list) and ji < len(val):
            return val[ji]
        return default

    def _get_global_val(cls, attr: str, default=None):
        """Get scalar value from JVInputs.Global."""
        return getattr(cls, attr, default)

    def _resolve(asset_cls, global_cls, attr: str, default=None):
        """Asset value if available, otherwise Global fallback."""
        v = _get_asset_val(asset_cls, attr)
        if v is not None and v is not pd.NaT and not (isinstance(v, float) and np.isnan(v)):
            return v
        return _get_global_val(global_cls, attr, default)

    def _resolve_new_or_old(asset_cls, global_cls, new_attr: str, old_attr: str, default=0):
        """Try new-name field; fall back to old-name only when new is absent (None/NaN/NaT), not when zero."""
        raw = _resolve(asset_cls, global_cls, new_attr, None)
        if raw is not None and raw is not pd.NaT and not (isinstance(raw, float) and np.isnan(raw)):
            return _to_float(raw)
        return _to_float(_resolve(asset_cls, global_cls, old_attr, default))

    # Capital Structure
    debt_pct = _to_float(_resolve(
        JVInputs.Asset.CapitalStructure,
        JVInputs.Global.CapitalStructure, "debt_", 0))
    equity_pct = _to_float(_resolve(
        JVInputs.Asset.CapitalStructure,
        JVInputs.Global.CapitalStructure, "equity", 0))
    if debt_pct > 1:
        debt_pct /= 100.0
    if equity_pct > 1:
        equity_pct /= 100.0

    # InKindEquity
    # JV-wise: read land_in__kind from the per-JV Asset row (index ji).
    # No global fallback - this flag is strictly JV-wise.
    _lik_asset = _get_asset_val(JVInputs.Asset.InKindEquity, "land_in__kind")
    if _lik_asset is not None and not (isinstance(_lik_asset, float) and np.isnan(_lik_asset)):
        lik_override = _lik_asset
    else:
        lik_override = None
    lik_gp_pct = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "land_in_kind_gp", 0))
    lik_lp_pct = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "land_in_kind_lp", 0))
    lik_gp_contrib = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "gp_contribution", 0))
    lik_lp_contrib = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "lp_contribution", 0))
    _lik_owner_raw = _resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "land_owner")
    lik_owner = str(_lik_owner_raw or "").strip().upper() if _lik_owner_raw is not None else ""

    # Normalise percentages
    if lik_gp_pct > 1:
        lik_gp_pct /= 100.0
    if lik_lp_pct > 1:
        lik_lp_pct /= 100.0
    if lik_gp_contrib > 1:
        lik_gp_contrib /= 100.0
    if lik_lp_contrib > 1:
        lik_lp_contrib /= 100.0

    # CashEquity - try active workbook field names first, then legacy
    _gp_raw = _resolve(
        JVInputs.Asset.CashEquity,
        JVInputs.Global.CashEquity, "gp_contribution_", None)
    if _gp_raw is None:
        _gp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "gp_contribution_cash", None)
    if _gp_raw is None:
        _gp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "gp_contribution", 0)
    cash_gp_pct = _to_float(_gp_raw)
    _lp_raw = _resolve(
        JVInputs.Asset.CashEquity,
        JVInputs.Global.CashEquity, "lp_contribution_", None)
    if _lp_raw is None:
        _lp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "lp_contribution_cash", None)
    if _lp_raw is None:
        _lp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "lp_contribution_others", 0)
    cash_lp_pct = _to_float(_lp_raw)
    if cash_gp_pct > 1:
        cash_gp_pct /= 100.0
    if cash_lp_pct > 1:
        cash_lp_pct /= 100.0

    # ComputedOwnership
    computed_gp_pct = _to_float(_resolve(
        JVInputs.Asset.ComputedOwnership,
        JVInputs.Global.ComputedOwnership, "gp_owernship", 0))
    computed_lp_pct = _to_float(_resolve(
        JVInputs.Asset.ComputedOwnership,
        JVInputs.Global.ComputedOwnership, "lp_ownership_others", 0))
    if computed_gp_pct > 1:
        computed_gp_pct /= 100.0
    if computed_lp_pct > 1:
        computed_lp_pct /= 100.0

    # UserDefinedOwnership - try new field names first
    ownership_override_raw = _resolve(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "ownership_over_ride")
    user_gp_pct = _resolve_new_or_old(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "gp_ownership_input", "gp_ownership")
    user_lp_pct = _resolve_new_or_old(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "lp_ownership_input", "lp_ownership_others")
    if user_gp_pct > 1:
        user_gp_pct /= 100.0
    if user_lp_pct > 1:
        user_lp_pct /= 100.0

    # Determine effective ownership branch
    if ownership_override_raw is None:
        _own_override_is_yes = False
    elif isinstance(ownership_override_raw, bool):
        _own_override_is_yes = ownership_override_raw
    elif isinstance(ownership_override_raw, (int, float)):
        _own_override_is_yes = bool(ownership_override_raw)
    else:
        _own_override_is_yes = str(ownership_override_raw).strip().lower() in ("yes", "true", "1")

    if _own_override_is_yes:
        effective_gp_pct = user_gp_pct
        effective_lp_pct = user_lp_pct
    else:
        effective_gp_pct = computed_gp_pct
        effective_lp_pct = computed_lp_pct

    # RoleAllocation
    gp_role = _resolve(
        JVInputs.Asset.RoleAllocation,
        JVInputs.Global.RoleAllocation, "gp")
    lp_role = _resolve(
        JVInputs.Asset.RoleAllocation,
        JVInputs.Global.RoleAllocation, "lp")

    # JVDates
    jv_start_date = _resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates,
        "start_date_based_on_the_earliest_project_acquisition")
    fund_tenure = _to_float(_resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates, "fund_tenure_in_months", 0))
    fund_close_date = _resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates,
        "end_date_based_on_the_last_exit_of_the_assets")

    # FinancingAssumptions_Loan1 (Term Loan 1)
    # Try new _tl1 suffixed field names first, fall back to legacy generic names
    tl1_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "start_date_tl1")
    if tl1_start is None:
        tl1_start = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "start_date")
    tl1_tenure = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "tenure_tl1", "tenure")
    tl1_end = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_datetl1")
    if tl1_end is None:
        tl1_end = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_date")
    tl1_amort_duration = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "amortization_durationtl1", "amortization_duration")
    tl1_annual_amort = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "annual_amortizationtl1", "annual_amortization")
    tl1_balloon = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "balloon_paymenttl1", "balloon_payment")
    tl1_interest_cap = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_capitalization_")
    tl1_interest_profile = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile_tl1")
    if tl1_interest_profile is None:
        tl1_interest_profile = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile")
    tl1_arr_fee = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_tl1", "arrangement_fees")
    tl1_commit_fee = _to_float(_resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "commitment_fees", 0))
    tl1_refinancing = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "refinacning")
    tl1_repay_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "repayment_start_date_tl1")
    if tl1_repay_start is None:
        tl1_repay_start = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "repayment_start_date")
    tl1_arr_fee_cap = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization_tl1")
    if tl1_arr_fee_cap is None:
        tl1_arr_fee_cap = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization_")
    if tl1_arr_fee_cap is None:
        tl1_arr_fee_cap = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization")

    # Normalise fee percentages
    if tl1_arr_fee > 1:
        tl1_arr_fee /= 100.0
    if tl1_commit_fee > 1:
        tl1_commit_fee /= 100.0
    if tl1_annual_amort > 1:
        tl1_annual_amort /= 100.0
    if tl1_balloon > 1:
        tl1_balloon /= 100.0


    # --- Refinancing fields ---
    # Primary source: FinancingAssumptions_Loan1 with _refinancing suffix.
    # Fallback: RefinancingAssumptions class (backward compat only).

    # start_date_refinancing
    tl2_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "start_date_refinancing")
    if tl2_start is None:
        tl2_start = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "start_date_refinancing")
    if tl2_start is None:
        tl2_start = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "start_date")
    # Derive from TL1 loan_end_datetl1 if refi flag is on but start missing
    if tl2_start is None and str(tl1_refinancing or "").strip().lower() in ("yes", "true", "1"):
        if tl1_end is not None:
            tl2_start = tl1_end

    # tenure__refinancing
    tl2_tenure = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "tenure__refinancing", "__skip__")
    if tl2_tenure == 0:
        tl2_tenure = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "tenure__refinancing", "tenure")

    # loan_end_date_refinancing
    tl2_end = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_date_refinancing")
    if tl2_end is None:
        tl2_end = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "loan_end_date_refinancing")
    if tl2_end is None:
        tl2_end = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "loan_end_date")

    # amortizationrefinancing
    tl2_amort_duration = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "amortizationrefinancing", "__skip__")
    if tl2_amort_duration == 0:
        tl2_amort_duration = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "amortizationrefinancing", "amortization_duration")

    # annual_amortizationrefinancing
    tl2_annual_amort = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "annual_amortizationrefinancing", "__skip__")
    if tl2_annual_amort == 0:
        tl2_annual_amort = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "annual_amortizationrefinancing", "annual_amortization")

    # balloon_payment_refinancing
    tl2_balloon = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "balloon_payment_refinancing", "__skip__")
    if tl2_balloon == 0:
        tl2_balloon = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "balloon_payment_refinancing", "balloon_payment")

    # interest_rate_profile___refinancing
    tl2_interest_profile = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile___refinancing")
    if tl2_interest_profile is None:
        tl2_interest_profile = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "interest_rate_profile___refinancing")
    if tl2_interest_profile is None:
        tl2_interest_profile = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "interest_rate_profile")

    # arrangement_feesrefinancing
    tl2_arr_fee = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_feesrefinancing", "__skip__")
    if tl2_arr_fee == 0:
        tl2_arr_fee = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "arrangement_feesrefinancing", "arrangement_fees")

    # commitment_fees (shared field name)
    tl2_commit_fee = _to_float(_resolve(
        JVInputs.Asset.RefinancingAssumptions,
        JVInputs.Global.RefinancingAssumptions, "commitment_fees", 0))

    # ltv (RefinancingAssumptions only)
    tl2_ltv = _to_float(_resolve(
        JVInputs.Asset.RefinancingAssumptions,
        JVInputs.Global.RefinancingAssumptions, "ltv", 0))

    # min_dscrrefinancing
    tl2_min_dscr = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "min_dscrrefinancing", "__skip__")
    if tl2_min_dscr == 0:
        tl2_min_dscr = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "min_dscrrefinancing", "min_dscr")

    if tl2_arr_fee > 1:
        tl2_arr_fee /= 100.0
    if tl2_commit_fee > 1:
        tl2_commit_fee /= 100.0
    if tl2_annual_amort > 1:
        tl2_annual_amort /= 100.0
    if tl2_balloon > 1:
        tl2_balloon /= 100.0
    if tl2_ltv > 1:
        tl2_ltv /= 100.0


    # Fees Definition
    jv_setup_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition,
        "jv_setup_structuring__acquisition_fees", 0))
    jv_liquidation_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition,
        "jv_liquidation__exit_related_fees", 0))
    other_fees = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition, "other_fees", 0))
    fund_mgmt_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition, "fund_management_exp", 0))

    # Normalise fee percentages (Excel may store as e.g. 1 meaning 1%)
    if jv_setup_fee > 1:
        jv_setup_fee /= 100.0
    if jv_liquidation_fee > 1:
        jv_liquidation_fee /= 100.0
    if other_fees > 1:
        other_fees /= 100.0
    if fund_mgmt_fee > 1:
        fund_mgmt_fee /= 100.0

    # Fees Allocation (GP/LP split of fees)
    fee_alloc_setup = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation,
        "jv_setup_structuring__acquisition_fees", 0))
    fee_alloc_liq = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation,
        "jv_liquidation__exit_related_fees", 0))
    fee_alloc_other = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation, "other_fees", 0))
    fee_alloc_mgmt = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation, "fund_management_exp", 0))

    # PreferredReturnsandCatchup
    pref_dist_frequency = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "distribution_frequency")
    pref_return_type = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "preferred_return_type")
    pref_return_rate = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "preferred_return", 0))
    gp_cf_during_pref = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_cashflow_duringpreferred_return", 0))
    gp_promote_raw = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_promote_", 0))
    gp_promote_post_pref = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_promote_post_preferred", 0))
    # Use gp_promote_ as fallback for gp_promote_post_pref if latter is zero
    if gp_promote_post_pref == 0 and gp_promote_raw > 0:
        gp_promote_post_pref = gp_promote_raw
    catchup_enabled = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "catchup_enabled")
    catchup_pct = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "catch_up_", 0))
    gp_cashflows_during_catchup = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "gp_cashflows_during_catch_up", 0))
    lp_cashflows_during_catchup = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "lp_cashflows_during_catch_up", 0))

    # Normalise pref rate and promote percentages
    if pref_return_rate > 1:
        pref_return_rate /= 100.0
    if gp_cf_during_pref > 1:
        gp_cf_during_pref /= 100.0
    if gp_promote_raw > 1:
        gp_promote_raw /= 100.0
    if gp_promote_post_pref > 1:
        gp_promote_post_pref /= 100.0
    if catchup_pct > 1:
        catchup_pct /= 100.0
    if gp_cashflows_during_catchup > 1:
        gp_cashflows_during_catchup /= 100.0
    if lp_cashflows_during_catchup > 1:
        lp_cashflows_during_catchup /= 100.0

    # Tier 1 - try new field names first, fall back to legacy
    # Try irr__tier_1 first, then t1_irr_, then irr_ (legacy)
    _t1_irr_new = _to_float(_resolve(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "irr__tier_1", None))
    if _t1_irr_new is not None and _t1_irr_new != 0:
        tier1_irr = _t1_irr_new
    else:
        tier1_irr = _resolve_new_or_old(
            JVInputs.Asset.Tier1,
            JVInputs.Global.Tier1, "t1_irr_", "irr_")
    tier1_lp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "lp_share___tier_1", "lp_share")
    tier1_gp_promote = _resolve_new_or_old(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "gp_promote___tier_1", "gp_promote")
    if tier1_irr > 1:
        tier1_irr /= 100.0
    if tier1_lp_share > 1:
        tier1_lp_share /= 100.0
    if tier1_gp_promote > 1:
        tier1_gp_promote /= 100.0

    # Tier 2 - try new field names first, fall back to legacy
    # Try irr__tier_2 first, then t2_irr_, then irr_ (legacy)
    _t2_irr_new = _to_float(_resolve(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "irr__tier_2", None))
    if _t2_irr_new is not None and _t2_irr_new != 0:
        tier2_irr = _t2_irr_new
    else:
        tier2_irr = _resolve_new_or_old(
            JVInputs.Asset.Tier2,
            JVInputs.Global.Tier2, "t2_irr_", "irr_")
    tier2_lp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "lp_share___tier_2", "lp_share")
    tier2_gp_promote = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "gp_promote___tier_2", "gp_promote")
    if tier2_irr > 1:
        tier2_irr /= 100.0
    if tier2_lp_share > 1:
        tier2_lp_share /= 100.0
    if tier2_gp_promote > 1:
        tier2_gp_promote /= 100.0

    # Tier 3 — check dedicated Tier3 class first, then fall back to Tier2 legacy fields
    _t3_asset_cls  = getattr(JVInputs.Asset,  "Tier3", JVInputs.Asset.Tier2)
    _t3_global_cls = getattr(JVInputs.Global, "Tier3", JVInputs.Global.Tier2)
    tier3_lp_share = _resolve_new_or_old(
        _t3_asset_cls, _t3_global_cls, "lp_share___tier_3", "lp_share___tier_3")
    tier3_gp_share = _resolve_new_or_old(
        _t3_asset_cls, _t3_global_cls, "gp_promote___tier_3", "gp_share___tier_3")
    if tier3_lp_share > 1:
        tier3_lp_share /= 100.0
    if tier3_gp_share > 1:
        tier3_gp_share /= 100.0
    _t3_share_sum = tier3_lp_share + tier3_gp_share
    if abs(_t3_share_sum - 1.0) > 0.01:
        pass

    result = {
        "debt_pct": debt_pct,
        "equity_pct": equity_pct,
        "lik_override": lik_override,
        "lik_owner": lik_owner,
        "lik_gp_pct": lik_gp_pct,
        "lik_lp_pct": lik_lp_pct,
        "lik_gp_contrib": lik_gp_contrib,
        "lik_lp_contrib": lik_lp_contrib,
        "cash_gp_pct": cash_gp_pct,
        "cash_lp_pct": cash_lp_pct,
        "ownership_override": _own_override_is_yes,
        "computed_gp_pct": computed_gp_pct,
        "computed_lp_pct": computed_lp_pct,
        "user_gp_pct": user_gp_pct,
        "user_lp_pct": user_lp_pct,
        "effective_gp_pct": effective_gp_pct,
        "effective_lp_pct": effective_lp_pct,
        "gp_role": gp_role,
        "lp_role": lp_role,
        "jv_start_date": jv_start_date,
        "fund_tenure": fund_tenure,
        "fund_close_date": fund_close_date,
        # TL1
        "tl1_start": tl1_start,
        "tl1_tenure": tl1_tenure,
        "tl1_end": tl1_end,
        "tl1_amort_duration": tl1_amort_duration,
        "tl1_annual_amort": tl1_annual_amort,
        "tl1_balloon": tl1_balloon,
        "tl1_interest_cap": tl1_interest_cap,
        "tl1_interest_profile": tl1_interest_profile,
        "tl1_arr_fee": tl1_arr_fee,
        "tl1_commit_fee": tl1_commit_fee,
        "tl1_refinancing": tl1_refinancing,
        "tl1_repay_start": tl1_repay_start,
        "tl1_arr_fee_cap": tl1_arr_fee_cap,
        # TL2 (Refinancing)
        "tl2_start": tl2_start,
        "tl2_tenure": tl2_tenure,
        "tl2_end": tl2_end,
        "tl2_amort_duration": tl2_amort_duration,
        "tl2_annual_amort": tl2_annual_amort,
        "tl2_balloon": tl2_balloon,
        "tl2_interest_profile": tl2_interest_profile,
        "tl2_arr_fee": tl2_arr_fee,
        "tl2_commit_fee": tl2_commit_fee,
        "tl2_ltv": tl2_ltv,
        "tl2_min_dscr": tl2_min_dscr,
        # Fees
        "jv_setup_fee": jv_setup_fee,
        "jv_liquidation_fee": jv_liquidation_fee,
        "other_fees": other_fees,
        "fund_mgmt_fee": fund_mgmt_fee,
        "fee_alloc_setup": fee_alloc_setup,
        "fee_alloc_liq": fee_alloc_liq,
        "fee_alloc_other": fee_alloc_other,
        "fee_alloc_mgmt": fee_alloc_mgmt,
        # Preferred Returns & Catchup
        "pref_dist_frequency": pref_dist_frequency,
        "pref_return_type": pref_return_type,
        "pref_return_rate": pref_return_rate,
        "gp_cf_during_pref": gp_cf_during_pref,
        "gp_promote_raw": gp_promote_raw,
        "gp_promote_post_pref": gp_promote_post_pref,
        "catchup_enabled": catchup_enabled,
        "catchup_pct": catchup_pct,
        "gp_cashflows_during_catchup": gp_cashflows_during_catchup,
        "lp_cashflows_during_catchup": lp_cashflows_during_catchup,
        # Tier 1
        "tier1_irr": tier1_irr,
        "tier1_lp_share": tier1_lp_share,
        "tier1_gp_promote": tier1_gp_promote,
        # Tier 2
        "tier2_irr": tier2_irr,
        "tier2_lp_share": tier2_lp_share,
        "tier2_gp_promote": tier2_gp_promote,
        # Tier 3
        "tier3_lp_share": tier3_lp_share,
        "tier3_gp_share": tier3_gp_share,
    }

    for k, v in result.items():
        pass

    return result


# =====================================================================
# Term Loan Schedule Computation
# =====================================================================

def _compute_term_loan(
    max_periods: int,
    funding_req_debt: List[float],
    model_start: Optional[pd.Timestamp],
    loan_start,
    loan_tenure: float,
    loan_end,
    repay_start_date,
    amort_duration: float,
    balloon_pct: float,
    interest_cap: Optional[str],
    interest_profile_name: Optional[str],
    arr_fee_pct: float,
    arr_fee_capitalize: Optional[str],
    commit_fee_pct: float,
    fund_end_idx: Optional[int],
    interest_profiles: Dict[str, List[float]],
    equity_pct: float = 0.0,
) -> Dict[str, List[float]]:
    """
    Compute a two-phase term loan schedule.

    Phase 1 - Construction (loan_start -> repay_start):
      - Draws from funding_req_debt (positive = cash needed)
      - Interest is capitalized if interest_cap = Yes
      - Arrangement fees capitalized if arr_fee_capitalize = Yes

    Phase 2 - Repayment (repay_start -> loan_end):
      - No new draws
      - Interest is paid as cashflow (not capitalized)
      - Amortization repayments begin
      - Balloon payment at min(loan_end, fund_end) clears remaining balance

    Output schedule rows:
      Opening Balance, Loan Additions, Capitalized Interest,
      Capitalized Arrangement Fees, Repayments, Closing Balance,
      Equity Infusion for Interest, Equity Infusion for Arrangement Fees.
    """
    principal_drawn = _zeros(max_periods)
    principal_repaid = _zeros(max_periods)
    interest_paid = _zeros(max_periods)
    arrangement_fees = _zeros(max_periods)
    commitment_fees = _zeros(max_periods)
    outstanding = _zeros(max_periods)

    # Debt schedule rows
    opening_bal = _zeros(max_periods)
    loan_additions = _zeros(max_periods)
    cap_interest = _zeros(max_periods)
    cap_arr_fees = _zeros(max_periods)
    repayments = _zeros(max_periods)
    closing_bal = _zeros(max_periods)
    eq_infusion_interest = _zeros(max_periods)
    eq_infusion_arr_fees = _zeros(max_periods)

    # Separate balloon tracking
    balloon_payment = _zeros(max_periods)

    # Arrangement fee incurred (always shows fee amount, regardless of capitalization)
    arr_fee_incurred = _zeros(max_periods)

    # Diagnostic / validation rows for printed schedule
    interest_incurred = _zeros(max_periods)
    interest_rate_applied = _zeros(max_periods)
    amort_pct_applied = _zeros(max_periods)

    # Resolve loan start/end/repay_start as month indices
    start_idx = _date_to_month_index(loan_start, model_start)
    end_idx = _date_to_month_index(loan_end, model_start)
    repay_idx = _date_to_month_index(repay_start_date, model_start)


    # If no explicit start, find first period with positive funding req
    if start_idx is None:
        for t in range(max_periods):
            if funding_req_debt[t] > 0.01:
                start_idx = t
                break

    _empty_result = {
        "principal_drawn": principal_drawn,
        "principal_repaid": principal_repaid,
        "interest_paid": interest_paid,
        "arrangement_fees": arrangement_fees,
        "commitment_fees": commitment_fees,
        "outstanding_balance": outstanding,
        "opening_balance": opening_bal,
        "loan_additions": loan_additions,
        "capitalized_interest": cap_interest,
        "capitalized_arr_fees": cap_arr_fees,
        "repayments": repayments,
        "closing_balance": closing_bal,
        "eq_infusion_interest": eq_infusion_interest,
        "eq_infusion_arr_fees": eq_infusion_arr_fees,
        "interest_incurred": interest_incurred,
        "interest_rate_applied": interest_rate_applied,
        "amort_pct_applied": amort_pct_applied,
        "balloon_payment": balloon_payment,
        "arr_fee_incurred": arr_fee_incurred,
    }

    if start_idx is None:
        return _empty_result

    # If no explicit end, compute from tenure
    if end_idx is None and loan_tenure > 0:
        end_idx = start_idx + int(loan_tenure)
    if end_idx is None:
        end_idx = max_periods - 1
    end_idx = min(end_idx, max_periods - 1)

    # Repayment start: amort_duration is always in years -> convert to months.
    if repay_idx is None:
        if amort_duration > 0:
            amort_m = int(amort_duration * 12)
            if end_idx is not None and start_idx is not None:
                repay_idx = max(end_idx - amort_m, start_idx)
            elif loan_tenure > 0:
                cap_dur_m = max(int(loan_tenure * 12) - amort_m, 0)
                repay_idx = start_idx + cap_dur_m
            else:
                repay_idx = start_idx
        else:
            repay_idx = end_idx  # no amort -> balloon only at end

    capitalize_interest = (
        str(interest_cap).strip().lower() in ("yes", "true", "1")
        if interest_cap is not None else False
    )
    # Business rule: if no explicit flag but repayment starts later than
    # loan start, interest capitalizes during the construction phase
    # (from start until repayment start).
    if not capitalize_interest and interest_cap is None:
        if repay_idx is not None and start_idx is not None and repay_idx > start_idx:
            capitalize_interest = True

    capitalize_arr_fee = (
        str(arr_fee_capitalize).strip().lower() in ("yes", "true", "1")
        if arr_fee_capitalize is not None else False
    )

    # Number of monthly amortization periods (nper for PMT formula).
    # amort_duration is always in years.
    amort_nper = int(amort_duration * 12) if amort_duration > 0 else 0

    # Balloon payment at the earlier of loan end or JV end (premature closure).
    # If the JV ends before the scheduled loan end, the outstanding balance is
    # cleared via balloon at JV end rather than waiting for the loan's own end date.
    effective_end_idx = end_idx
    if fund_end_idx is not None and fund_end_idx < end_idx:
        effective_end_idx = fund_end_idx
    balloon_idx = min(effective_end_idx, max_periods - 1)

    # Repayment period counter: increments each repayment period so remaining
    # nper decreases correctly as: remaining = amort_nper - periods_elapsed
    _repay_periods_elapsed = 0

    total_drawn = 0.0

    # Accumulate any unfunded debt requirement from before loan start
    # so it gets drawn as a lump sum when the loan begins
    accumulated_prior_debt = 0.0
    if start_idx > 0:
        for i in range(start_idx):
            if funding_req_debt[i] > 0.01:
                accumulated_prior_debt += funding_req_debt[i]
        if accumulated_prior_debt > 0.01:
            pass

    # Arrangement fee is computed once at debt start date on the total loan
    # commitment (all draw requirements + accumulated prior debt), because the
    # debt facility is arranged at start date even though drawdowns happen later.
    # Include start_idx itself: when repay_idx == start_idx (e.g. refinancing
    # debt with amort_duration >= loan_tenure), the draw window is just [start_idx]
    # and the commitment equals that single draw.
    if arr_fee_pct > 0:
        total_commitment = sum(
            funding_req_debt[t] for t in range(start_idx, max_periods)
            if funding_req_debt[t] > 0.01 and (t < repay_idx or t == start_idx)
        ) + accumulated_prior_debt
        total_arr_fee_upfront = total_commitment * arr_fee_pct
    else:
        total_arr_fee_upfront = 0.0
    _arr_fee_applied_at_start = False

    for t in range(max_periods):
        prev_outstanding = outstanding[t - 1] if t > 0 else 0.0
        opening_bal[t] = prev_outstanding

        if t < start_idx or t > effective_end_idx:
            outstanding[t] = prev_outstanding
            closing_bal[t] = outstanding[t]
            continue

        # --- Draw phase: before repayment start, or at loan start ---
        # Always allow the initial draw at start_idx even when repay_idx == start_idx
        # (e.g. refinancing debt where amort_duration >= loan_tenure).
        draw = 0.0
        if t < repay_idx or t == start_idx:
            period_need = funding_req_debt[t] if funding_req_debt[t] > 0.01 else 0.0
            # At loan start, also draw accumulated unfunded prior debt
            if t == start_idx and accumulated_prior_debt > 0.01:
                period_need += accumulated_prior_debt
            if period_need > 0.01:
                draw = period_need
                principal_drawn[t] = draw
                loan_additions[t] = draw
                total_drawn += draw

        # --- Arrangement fee: one-off at debt start date ---
        if t == start_idx and total_arr_fee_upfront > 0 and not _arr_fee_applied_at_start:
            fee = total_arr_fee_upfront
            arr_fee_incurred[t] = fee
            _arr_fee_applied_at_start = True
            if capitalize_arr_fee:
                cap_arr_fees[t] = fee
                arrangement_fees[t] = 0.0
                eq_infusion_arr_fees[t] = 0.0
            else:
                arrangement_fees[t] = fee
                cap_arr_fees[t] = 0.0

        # --- Interest calculation ---
        balance_for_interest = prev_outstanding + loan_additions[t] + cap_arr_fees[t]
        monthly_rate = _get_monthly_rate(
            interest_profiles, interest_profile_name, t,
        )
        period_interest = balance_for_interest * monthly_rate

        # Store diagnostic values
        interest_incurred[t] = period_interest
        interest_rate_applied[t] = monthly_rate * 12.0   # annual rate for display

        if t < repay_idx and capitalize_interest:
            # --- Capitalization phase: interest increases balance, NOT paid ---
            cap_interest[t] = period_interest
            interest_paid[t] = 0.0                       # explicitly zero during cap
            outstanding[t] = prev_outstanding + loan_additions[t] + cap_arr_fees[t] + period_interest
            # No equity infusion - interest is capitalised into debt, no cash leaves
            eq_infusion_interest[t] = 0.0
        else:
            # --- Payment phase: interest is cash-paid, NOT capitalized ---
            cap_interest[t] = 0.0
            interest_paid[t] = period_interest
            outstanding[t] = prev_outstanding + loan_additions[t] + cap_arr_fees[t]

        # --- Commitment fee ---
        if commit_fee_pct > 0 and outstanding[t] > 0:
            commitment_fees[t] = outstanding[t] * ((1.0 + commit_fee_pct) ** (1.0 / 12.0) - 1.0)

        # --- Amortization repayments: period-by-period PPMT (repayment phase only) ---
        if t >= repay_idx and amort_nper > 0 and outstanding[t] > 0:
            # Recompute PMT every period using current outstanding balance, current
            # rate, and remaining periods — mirrors Excel PPMT(rate, period, nper, pv)
            # where pv is re-anchored each month to the actual outstanding balance.
            #
            # PMT  = PV * r / (1 - (1+r)^-n)
            # IPMT = period_interest  (already computed above on balance_for_interest)
            # PPMT = PMT - IPMT
            _remaining_nper = max(1, amort_nper - _repay_periods_elapsed)
            _r = monthly_rate if monthly_rate > 0 else 1e-10
            # PV for PMT = opening balance of this period (before interest/principal)
            _pv = balance_for_interest  # = prev_outstanding + loan_additions + cap_arr_fees
            _pmt = _pv * _r / (1.0 - (1.0 + _r) ** (-_remaining_nper))
            # period_interest is IPMT for this period (computed on same base)
            _ppmt = max(0.0, _pmt - period_interest)
            repay = min(_ppmt, outstanding[t])
            principal_repaid[t] = repay
            repayments[t] = repay
            outstanding[t] -= repay
            amort_pct_applied[t] = (repay / _pv * 12.0) if _pv > 0.01 else 0.0
            _repay_periods_elapsed += 1

        # --- Balloon payment at min(loan_end, fund_end) ---
        if t == balloon_idx and outstanding[t] > 0:
            balloon_amount = outstanding[t]
            balloon_payment[t] = balloon_amount
            principal_repaid[t] += balloon_amount
            repayments[t] += balloon_amount
            outstanding[t] = 0.0

        closing_bal[t] = outstanding[t]


    return {
        "principal_drawn": principal_drawn,
        "principal_repaid": principal_repaid,
        "interest_paid": interest_paid,
        "arrangement_fees": arrangement_fees,
        "commitment_fees": commitment_fees,
        "outstanding_balance": outstanding,
        "opening_balance": opening_bal,
        "loan_additions": loan_additions,
        "capitalized_interest": cap_interest,
        "capitalized_arr_fees": cap_arr_fees,
        "repayments": repayments,
        "closing_balance": closing_bal,
        "eq_infusion_interest": eq_infusion_interest,
        "eq_infusion_arr_fees": eq_infusion_arr_fees,
        "interest_incurred": interest_incurred,
        "interest_rate_applied": interest_rate_applied,
        "amort_pct_applied": amort_pct_applied,
        "balloon_payment": balloon_payment,
        "arr_fee_incurred": arr_fee_incurred,
    }


# =====================================================================
# Full CFF Computation Engine
# =====================================================================

def _compute_cff(
    total_fcf: List[float],
    land_in_kind: List[float],
    max_periods: int,
    vehicle_inputs: dict,
    interest_profiles: Dict[str, List[float]],
    model_start: Optional[pd.Timestamp],
    asset_sales: Optional[List[float]] = None,
    project_cost: Optional[List[float]] = None,
    land_cost: Optional[List[float]] = None,
) -> Dict[str, List[float]]:
    """
    Compute the full Cashflow from Financing section including:
      - Fund-related expenses
      - Funding requirement (debt / equity split)
      - Term Loan 1 (drawdown from funding requirement)
      - Term Loan 2 / Refinancing (draws from TL1 outstanding at refi start)
      - Financing cost summary
      - Equity infusion (equity portion of funding requirement)
      - Preferred return schedule (cumulative unreturned capital based)
      - LP / GP distribution waterfall (sequential: pref -> return of capital)
      - Cash schedule (opening -> net -> closing with reconciliation)

    Returns a dict of label -> data rows for all CFF line items.
    """
    vi = vehicle_inputs
    debt_pct = vi["debt_pct"]
    equity_pct = vi["equity_pct"]

    # =================================================================
    # A. Fund-related expenses
    # =================================================================
    # Pre-resolve JV start index (needed by setup fee placement below
    # and later by section B-pre).
    jv_start = vi.get("jv_start_date")
    jv_start_idx = _date_to_month_index(jv_start, model_start)

    jv_setup_fees = _zeros(max_periods)
    fund_mgmt_exp = _zeros(max_periods)    # populated after equity_infused (Section F-post)
    other_fees_row = _zeros(max_periods)
    jv_liq_fees = _zeros(max_periods)

    _asset_sales = asset_sales if asset_sales else _zeros(max_periods)
    _project_cost = project_cost if project_cost else _zeros(max_periods)

    # Setup fee: percentage of land acquisition price at JV start date.
    # Use land_cost (explicit land acquisition cash outflow) when provided;
    # fall back to land_in_kind total when land_cost is absent or zero.
    if vi["jv_setup_fee"] > 0:
        _land_cost_arr = land_cost if land_cost else _zeros(max_periods)
        _setup_fee_base = sum(abs(_to_float(v)) for v in _land_cost_arr)
        if _setup_fee_base < 0.01:
            _setup_fee_base = sum(abs(_to_float(v)) for v in land_in_kind) if land_in_kind else 0.0
        _setup_amount = vi["jv_setup_fee"] * _setup_fee_base
        if _setup_amount > 0:
            _sf_idx = jv_start_idx if jv_start_idx is not None and 0 <= jv_start_idx < max_periods else None
            if _sf_idx is None:
                for t in range(max_periods):
                    if abs(total_fcf[t]) > 0.01:
                        _sf_idx = t
                        break
            if _sf_idx is not None:
                jv_setup_fees[_sf_idx] = -abs(_setup_amount)

    # Other Fees: percentage of project cost (infra + dev + land) per period.
    if vi["other_fees"] > 0:
        for t in range(max_periods):
            _pc_val = abs(_to_float(_project_cost[t]))
            if _pc_val > 0.01:
                other_fees_row[t] = -abs(vi["other_fees"] * _pc_val)

    # Liquidation fee: percentage of asset sales value, applied per period.
    if vi["jv_liquidation_fee"] > 0:
        for t in range(max_periods):
            if abs(_asset_sales[t]) > 0.01:
                jv_liq_fees[t] = -abs(vi["jv_liquidation_fee"] * _asset_sales[t])

    # Fund management expenses are computed after equity_infused (Section F-post)
    # so we build total_fund_expenses initially without it.
    total_fund_expenses = _row_add(jv_setup_fees, other_fees_row, jv_liq_fees)
    total_fcf_before_fin = _row_add(total_fcf, total_fund_expenses)

    # =================================================================
    # B-pre. JV window & fund end index (needed before debt base)
    # =================================================================
    fund_end_idx = None
    fund_tenure = vi.get("fund_tenure", 0)
    jv_end_idx = None
    if jv_start_idx is not None and fund_tenure > 0:
        jv_end_idx = jv_start_idx + int(fund_tenure)
        fund_end_idx = jv_end_idx
        if fund_end_idx >= max_periods:
            fund_end_idx = max_periods - 1

    # Also resolve fund close date (end_date_based_on_the_last_exit_of_the_assets)
    _fund_close_raw = vi.get("fund_close_date")
    fund_close_idx = _date_to_month_index(_fund_close_raw, model_start)
    if fund_close_idx is not None:
        if fund_close_idx >= max_periods:
            fund_close_idx = max_periods - 1
        # Cap fund_end_idx at fund close date if it comes earlier
        if fund_end_idx is None:
            fund_end_idx = fund_close_idx
        else:
            fund_end_idx = min(fund_end_idx, fund_close_idx)

    # =================================================================
    # B. Debt base = "Total FCFF before Financing and SPV Related Cost - JV"
    #    This is the ONLY source for debt sizing.
    #    Fees (setup, liquidation, arrangement, commitment) are equity-only
    #    and must NOT be included in the debt base.
    # =================================================================

    # Step 1: Apply JV date window to total_fcf (same logic as 7b cashflows)
    _windowed_fcf = [0.0] * max_periods
    _w_start = jv_start_idx if jv_start_idx is not None else 0
    _w_end = jv_end_idx if jv_end_idx is not None else max_periods
    for t in range(max(_w_start, 0), min(_w_end, max_periods)):
        _windowed_fcf[t] = _to_float(total_fcf[t])

    # Step 2: Determine LIK flag (same robust logic as 7c)
    _lik_flag = vi.get("lik_override")
    if _lik_flag is None:
        _lik_is_yes_cff = False
    elif isinstance(_lik_flag, bool):
        _lik_is_yes_cff = _lik_flag
    elif isinstance(_lik_flag, (int, float)):
        _lik_is_yes_cff = bool(_lik_flag)
    else:
        _lik_is_yes_cff = str(_lik_flag).strip().lower() in ("yes", "true", "1")

    # Step 3: Build debt_base = windowed_fcf + land_cost
    # When LIK = Yes the land is contributed in-kind (non-cash) and must NOT
    # be included in the funding requirement.  Only include when LIK = No.
    _land_cost_for_debt = [0.0] * max_periods
    if not _lik_is_yes_cff:
        if jv_start_idx is not None and 0 <= jv_start_idx < max_periods:
            _lik_sum = sum(_to_float(v) for v in land_in_kind)
            # Convention: land costs are always negative (outflow)
            _land_cost_for_debt[jv_start_idx] = -abs(_lik_sum) if _lik_sum != 0 else 0.0
    debt_base = _row_add(_windowed_fcf, _land_cost_for_debt)

    # Step 4: Period-wise debt funding requirement (NO cumulative gating)
    # If debt_base[t] < 0: funding needed = abs(debt_base[t])
    # If debt_base[t] >= 0: no debt needed
    funding_req = _zeros(max_periods)
    for t in range(max_periods):
        if debt_base[t] < 0:
            funding_req[t] = abs(debt_base[t])

    debt_funding = [v * debt_pct for v in funding_req]
    # Equity funding from the same base (residual after debt) - fees excluded,
    # fees will be covered separately by equity when that section is built.
    equity_funding = [v * equity_pct for v in funding_req]

    # =================================================================
    # D-pre. Refinancing flag
    # =================================================================
    refi_enabled = str(vi.get("tl1_refinancing") or "").strip().lower() in (
        "yes", "true", "1",
    )
    tl2_start_idx = _date_to_month_index(vi["tl2_start"], model_start)

    # =================================================================
    # D. Term Loan 1
    # =================================================================
    # Run TL1 with its natural end date. When refinancing is enabled, TL1's
    # balloon at refi start becomes the TL2 draw — no end-date manipulation needed.
    tl1 = _compute_term_loan(
        max_periods=max_periods,
        funding_req_debt=debt_funding,
        model_start=model_start,
        loan_start=vi["tl1_start"],
        loan_tenure=vi["tl1_tenure"],
        loan_end=vi["tl1_end"],
        repay_start_date=vi.get("tl1_repay_start"),
        amort_duration=vi["tl1_amort_duration"],
        balloon_pct=vi["tl1_balloon"],
        interest_cap=vi["tl1_interest_cap"],
        interest_profile_name=vi.get("tl1_interest_profile"),
        arr_fee_pct=vi["tl1_arr_fee"],
        arr_fee_capitalize=vi.get("tl1_arr_fee_cap"),
        commit_fee_pct=vi["tl1_commit_fee"],
        fund_end_idx=fund_end_idx,
        interest_profiles=interest_profiles,
        equity_pct=equity_pct,
    )

    # =================================================================
    # D. Term Loan 2 / Refinancing
    # =================================================================
    # TL2 is raised at the refi start date to pay off TL1's outstanding balloon.
    # The drawdown amount equals TL1's outstanding balance at the refi date
    # (i.e. the balloon that TL1 would otherwise have to pay).
    # TL2 then follows its own amortization/balloon schedule from that point.

    tl2_funding = _zeros(max_periods)
    if refi_enabled and tl2_start_idx is not None and 0 <= tl2_start_idx < max_periods:
        # TL1 typically fires its balloon at its end date (the period just before
        # tl2_start_idx), zeroing outstanding_balance[tl2_start_idx] to 0.
        # Read the balloon from TL1's balloon_payment array covering the window
        # [tl2_start_idx-1, tl2_start_idx] to handle both same-period and
        # next-period refi start conventions.
        _search_start = max(0, tl2_start_idx - 1)
        tl1_balloon_at_refi = 0.0
        for _bt in range(_search_start, tl2_start_idx + 1):
            if _bt < max_periods and tl1["balloon_payment"][_bt] > tl1_balloon_at_refi:
                tl1_balloon_at_refi = tl1["balloon_payment"][_bt]
        # Fallback: if no balloon recorded yet (e.g. tl2_start == tl1_start),
        # use the outstanding balance at tl2_start_idx directly.
        if tl1_balloon_at_refi < 0.01:
            tl1_balloon_at_refi = tl1["outstanding_balance"][tl2_start_idx]
        if tl1_balloon_at_refi > 0.01:
            tl2_funding[tl2_start_idx] = tl1_balloon_at_refi

    tl2 = _compute_term_loan(
        max_periods=max_periods,
        funding_req_debt=tl2_funding,
        model_start=model_start,
        loan_start=vi["tl2_start"],
        loan_tenure=vi["tl2_tenure"],
        loan_end=vi["tl2_end"],
        repay_start_date=None,
        amort_duration=vi["tl2_amort_duration"],
        balloon_pct=vi["tl2_balloon"],
        interest_cap="No",
        interest_profile_name=vi.get("tl2_interest_profile"),
        arr_fee_pct=vi["tl2_arr_fee"],
        arr_fee_capitalize="No",
        commit_fee_pct=vi["tl2_commit_fee"],
        fund_end_idx=fund_end_idx,
        interest_profiles=interest_profiles,
        equity_pct=equity_pct,
    )

    # --- Post-process TL1 for refinancing event ---
    # TL1's balloon fires at tl1_end (typically tl2_start_idx - 1), clearing
    # TL1's own balance. If tl2_start coincides with tl1_end (same period),
    # TL1's outstanding balance at that period is still non-zero before the
    # balloon fires, so we force it closed and record the payoff explicitly.
    # In the normal next-period case TL1 is already zeroed; the zero-forward
    # loop is still applied to guard against any residual balance.
    if refi_enabled and tl2_start_idx is not None and 0 <= tl2_start_idx < max_periods:
        _refi_bal = tl1["outstanding_balance"][tl2_start_idx]
        if _refi_bal > 0.01:
            # Same-period case: TL1 hasn't ballooned yet at tl2_start_idx
            tl1["repayments"][tl2_start_idx] += _refi_bal
            tl1["principal_repaid"][tl2_start_idx] += _refi_bal
            tl1["balloon_payment"][tl2_start_idx] = _refi_bal
            tl1["outstanding_balance"][tl2_start_idx] = 0.0
            tl1["closing_balance"][tl2_start_idx] = 0.0
        # Zero out TL1 after refi in all cases (normal path: already zero, harmless)
        for _t_adj in range(tl2_start_idx + 1, max_periods):
            for _k_adj in ("opening_balance", "outstanding_balance",
                           "closing_balance", "repayments",
                           "principal_repaid", "loan_additions",
                           "capitalized_interest", "capitalized_arr_fees",
                           "interest_paid", "interest_incurred",
                           "arrangement_fees", "commitment_fees",
                           "principal_drawn", "balloon_payment"):
                tl1[_k_adj][_t_adj] = 0.0

    # After refi adjustment, tl1["principal_repaid"] already includes the
    # refinancing payoff - no separate tl1_refi_repayment needed.
    tl1_repaid_total = tl1["principal_repaid"]

    # --- Cashflow From Financing Activity ---
    # Always computed regardless of refinancing flag.
    # Derived from the 4 gross presentation top rows per loan:
    #   Debt Issued (adds + cap_int + cap_arr)       [positive]
    # + Debt Repaid (-principal_repaid)               [negative]
    # + Interest Expense Paid (-(int_paid+cap_int))   [negative]
    # + Arrangement Fees Paid (-(arr_fees+cap_arr))   [negative]
    cashflow_from_financing_activity = _row_add(
        # --- Term Loan 1 (4 gross top rows) ---
        _row_add(tl1["loan_additions"], tl1["capitalized_interest"],
                 tl1["capitalized_arr_fees"]),                        # Debt Issued
        _row_negate(tl1["principal_repaid"]),                         # Debt Repaid
        _row_negate(_row_add(tl1["interest_paid"],
                             tl1["capitalized_interest"])),           # Interest Expense Paid
        _row_negate(_row_add(tl1["arrangement_fees"],
                             tl1["capitalized_arr_fees"])),           # Arrangement Fees Paid
        # --- Refinancing Facility (4 gross top rows) ---
        _row_add(tl2["loan_additions"], tl2["capitalized_interest"],
                 tl2["capitalized_arr_fees"]),                        # Debt Issued
        _row_negate(tl2["principal_repaid"]),                         # Debt Repaid
        _row_negate(_row_add(tl2["interest_paid"],
                             tl2["capitalized_interest"])),           # Interest Expense Paid
        _row_negate(_row_add(tl2["arrangement_fees"],
                             tl2["capitalized_arr_fees"])),           # Arrangement Fees Paid
    )

    # =================================================================
    # E. Financing Cost summary
    # =================================================================
    total_arr_fees = _row_add(tl1["arrangement_fees"], tl2["arrangement_fees"])
    total_commit_fees = _row_add(tl1["commitment_fees"], tl2["commitment_fees"])
    total_interest = _row_add(tl1["interest_paid"], tl2["interest_paid"])

    # =================================================================
    # F. Equity infusion (SPV perspective: positive = cash IN)
    # =================================================================
    # equity_funding is positive (amount needed), which is cash IN to SPV
    equity_infused = list(equity_funding)

    # F-post: fund management fees are computed after all committed capital
    # components are known (cash equity + additional equity + land-in-kind).
    # Deferred — computed below after _addl_equity_funding and land_in_kind are available.

    # Net Funding Requirement = Cash Flow before Financing Cost + financing costs
    # (arr fees, commitment fees, interest are already negative outflows)
    net_funding_req = _row_add(
        total_fcf_before_fin,
        _row_negate(total_arr_fees),
        _row_negate(total_commit_fees),
        _row_negate(total_interest),
    )

    # =================================================================
    # F2. Balloon equity funding (no-refi case only)
    # Use the period's cashflow before financing to cover the balloon first;
    # only raise equity for the shortfall (balloon - available CF).
    # For TL2 balloon in the refi case, the G-post additional equity section
    # handles it naturally via the cumulative cash balance.
    # =================================================================
    _balloon_equity = _zeros(max_periods)
    if not refi_enabled:
        for _t in range(max_periods):
            _bal_amt = tl1["balloon_payment"][_t]
            if _bal_amt > 0.01:
                _available_cf = max(0.0, total_fcf_before_fin[_t])
                _balloon_equity[_t] = max(0.0, _bal_amt - _available_cf)

    # Net Financing Cashflows (before distributions)
    net_financing_cf = _row_add(
        tl1["principal_drawn"], _row_negate(tl1_repaid_total),
        tl2["principal_drawn"], _row_negate(tl2["principal_repaid"]),
        _row_negate(total_arr_fees), _row_negate(total_commit_fees),
        _row_negate(total_interest),
        equity_infused,
        _balloon_equity,
    )

    # =================================================================
    # G. LP / GP Equity Splits (investor perspective: negative = cash OUT)
    # =================================================================
    # land_in_kind from model is positive (value of land contributed).
    # From investor perspective, contributions are outflows -> negate.
    # When land_owner is set, the non-owner pays cash (not in-kind); the owner's
    # in-kind share stays at their split percentage.  The non-owner's cash
    # compensation is injected as additional equity and distributed to the owner.
    _lik_owner = str(vi.get("lik_owner") or "").strip().upper()
    if _lik_owner == "LP":
        lp_in_kind = [-abs(v) * vi["lik_lp_pct"] for v in land_in_kind]
        gp_in_kind = _zeros(max_periods)
    elif _lik_owner == "GP":
        gp_in_kind = [-abs(v) * vi["lik_gp_pct"] for v in land_in_kind]
        lp_in_kind = _zeros(max_periods)
    else:
        lp_in_kind = [-abs(v) * vi["lik_lp_pct"] for v in land_in_kind]
        gp_in_kind = [-abs(v) * vi["lik_gp_pct"] for v in land_in_kind]
    # equity_funding is positive (amount needed) -> contributions are negative (cash out from investor)
    lp_cash_equity = [-v * vi["cash_lp_pct"] for v in equity_funding]
    gp_cash_equity = [-v * vi["cash_gp_pct"] for v in equity_funding]
    # Balloon equity split LP/GP (cash out from investor, shown as negative)
    lp_balloon_equity = [-v * vi["cash_lp_pct"] for v in _balloon_equity]
    gp_balloon_equity = [-v * vi["cash_gp_pct"] for v in _balloon_equity]
    lp_contributions = _row_add(lp_in_kind, lp_cash_equity, lp_balloon_equity)
    gp_contributions = _row_add(gp_in_kind, gp_cash_equity, gp_balloon_equity)

    # =================================================================
    # G-post.  Additional Equity Requirement (computed BEFORE waterfall
    #          so that additional equity injections appear in net_cash)
    # =================================================================
    _cash_gp = vi.get("cash_gp_pct", 0.0)
    _cash_lp = vi.get("cash_lp_pct", 0.0)

    _cash_bal_after_infusion = _row_add(
        total_fcf_before_fin,
        cashflow_from_financing_activity,
        equity_funding,
        _balloon_equity,
    )

    _addl_eq_opening = _zeros(max_periods)
    _addl_eq_req = _zeros(max_periods)
    _addl_eq_closing = _zeros(max_periods)

    for t in range(max_periods):
        if t > 0:
            _addl_eq_opening[t] = _addl_eq_closing[t - 1]
        _pre_addl = _addl_eq_opening[t] + _cash_bal_after_infusion[t]
        if _pre_addl < 0:
            _addl_eq_req[t] = abs(_pre_addl)
        else:
            _addl_eq_req[t] = 0.0
        # Never carry forward a positive surplus: sale proceeds and other inflows
        # will be distributed by the waterfall, so they must not act as a buffer
        # for future debt repayments.  Only a residual deficit (closing < 0) would
        # need to be carried, but addl_eq_req already fills it to exactly 0, so
        # the closing is always 0.
        _raw_closing = _addl_eq_opening[t] + _cash_bal_after_infusion[t] + _addl_eq_req[t]
        _addl_eq_closing[t] = min(0.0, _raw_closing)

    # LIK compensation: non-owner raises cash at JV start; owner receives it as a
    # Tier 3 distribution (GP "buys" their land % from LP, or vice versa).
    # This is tracked separately so 100% falls on the non-owner, not split by cash %.
    _lik_comp_amount = 0.0
    _lik_comp_idx = None
    if _lik_owner in ("LP", "GP") and _lik_is_yes_cff:
        _lik_total_comp = sum(abs(_to_float(v)) for v in land_in_kind)
        if _lik_total_comp > 0.01:
            _non_owner_pct = vi.get("lik_gp_pct", 0.0) if _lik_owner == "LP" else vi.get("lik_lp_pct", 0.0)
            _lik_comp_amount = _lik_total_comp * _non_owner_pct
            if jv_start_idx is not None and 0 <= jv_start_idx < max_periods:
                _lik_comp_idx = jv_start_idx

    # Additional equity commitment (GP/LP split)
    _addl_equity_funding = list(_addl_eq_req)
    _gp_addl_commit = [v * _cash_gp for v in _addl_equity_funding]
    _lp_addl_commit = [v * _cash_lp for v in _addl_equity_funding]

    # Inject LIK compensation into non-owner's additional equity: 100% from non-owner.
    if _lik_comp_idx is not None and _lik_comp_amount > 0.01:
        _addl_equity_funding[_lik_comp_idx] += _lik_comp_amount
        if _lik_owner == "LP":
            _gp_addl_commit[_lik_comp_idx] += _lik_comp_amount
        else:
            _lp_addl_commit[_lik_comp_idx] += _lik_comp_amount

    # -----------------------------------------------------------------
    # F-post (deferred). Fund Management Expenses = fee% * cumulative committed capital
    # Committed capital = cash equity + additional equity + land-in-kind (LP + GP)
    # -----------------------------------------------------------------
    if vi["fund_mgmt_fee"] > 0:
        _fm_end = jv_end_idx if jv_end_idx is not None else max_periods
        _fm_end = min(_fm_end, max_periods)
        _cum_committed = 0.0
        for t in range(_fm_end):
            _cum_committed += (
                _to_float(equity_funding[t])
                + _to_float(_addl_equity_funding[t])
                + abs(_to_float(land_in_kind[t]))
            )
            if _cum_committed > 0.01:
                fund_mgmt_exp[t] = -abs(vi["fund_mgmt_fee"] * _cum_committed)
        # Re-derive total_fund_expenses and total_fcf_before_fin.
        total_fund_expenses = _row_add(jv_setup_fees, other_fees_row,
                                       jv_liq_fees, fund_mgmt_exp)
        total_fcf_before_fin = _row_add(total_fcf, total_fund_expenses)

    # Inclusive contributions (initial + additional equity)
    _lp_addl_contrib = _row_negate(_lp_addl_commit)
    _gp_addl_contrib = _row_negate(_gp_addl_commit)
    lp_contributions_incl = _row_add(lp_contributions, _lp_addl_contrib)
    gp_contributions_incl = _row_add(gp_contributions, _gp_addl_contrib)

    # Cash-only equity for display (excludes LIK — land in-kind is non-cash)
    lp_cash_contributions_display = _row_add(lp_cash_equity, lp_balloon_equity, _lp_addl_contrib)
    gp_cash_contributions_display = _row_add(gp_cash_equity, gp_balloon_equity, _gp_addl_contrib)

    # Equity schedule
    gp_commitment = [v * _cash_gp for v in equity_funding]
    lp_commitment = [v * _cash_lp for v in equity_funding]

    # =================================================================
    # H + I + J.  Unified cash schedule & distribution waterfall
    # =================================================================
    # Single forward pass: rolling cash balance drives distribution
    # availability.  Distributions reduce closing balance immediately so
    # subsequent periods see the correct opening balance.

    # net_cash includes: FCFF + all fees + debt activity + initial equity
    # + additional equity raised to cover shortfalls + LIK compensation from non-owner
    _lik_comp_total = _zeros(max_periods)
    if _lik_comp_idx is not None and _lik_comp_amount > 0.01:
        _lik_comp_total[_lik_comp_idx] = _lik_comp_amount
    net_cash_pre_dist = _row_add(total_fcf, total_fund_expenses, net_financing_cf,
                                 _addl_eq_req, _lik_comp_total)

    # Preferred return parameters
    pref_rate_annual = vi.get("pref_return_rate", 0.0)
    gp_cf_during_pref_rate = vi.get("gp_cf_during_pref", 0.0)

    # Daily compounding rate per period: (1 + annual_rate) ^ (days_in_month / 365) - 1
    import calendar as _calendar
    def _daily_compound_rate(annual_rate: float, period_idx: int) -> float:
        if model_start is not None:
            try:
                ts = model_start + pd.DateOffset(months=period_idx)
                days = _calendar.monthrange(ts.year, ts.month)[1]
            except Exception:
                days = 30
        else:
            days = 30
        return (1.0 + annual_rate) ** (days / 365.0) - 1.0

    _pref_rate_per_period = [_daily_compound_rate(pref_rate_annual,          t) for t in range(max_periods)]
    _t1_rate_per_period   = [_daily_compound_rate(vi.get("tier1_irr", 0.0),  t) for t in range(max_periods)]
    _t2_rate_per_period   = [_daily_compound_rate(vi.get("tier2_irr", 0.0),  t) for t in range(max_periods)]

    # Output arrays - preferred (LP)
    pref_accrual_lp = _zeros(max_periods)
    pref_paid_lp = _zeros(max_periods)
    pref_unpaid_lp = _zeros(max_periods)

    # Output arrays - preferred (GP)
    pref_accrual_gp = _zeros(max_periods)
    pref_paid_gp = _zeros(max_periods)
    pref_unpaid_gp = _zeros(max_periods)

    # GP non-LIK contributions (cash + additional equity) for pref eligibility
    gp_cash_plus_addl = _row_add(gp_cash_equity, _gp_addl_contrib)

    # Output arrays - return of capital
    roc_lp = _zeros(max_periods)
    roc_gp = _zeros(max_periods)

    # Preferred account closing balances (opening + contributions + accrual - distributions)
    _pref_closing_lp = _zeros(max_periods)
    _pref_closing_gp = _zeros(max_periods)

    # Undistributed accrual: clears residual pref balance at last JV period (negative sign)
    _undist_accrual_lp = _zeros(max_periods)
    _undist_accrual_gp = _zeros(max_periods)

    # Output arrays - GP during pref
    gp_during_pref = _zeros(max_periods)

    # Output arrays - waterfall tiers
    catchup_lp = _zeros(max_periods)
    catchup_gp = _zeros(max_periods)
    tier1_lp = _zeros(max_periods)
    tier1_gp = _zeros(max_periods)
    tier1_gp_catchup = _zeros(max_periods)
    tier2_lp = _zeros(max_periods)
    tier2_gp = _zeros(max_periods)
    tier2_gp_catchup = _zeros(max_periods)
    tier3_lp = _zeros(max_periods)
    tier3_gp = _zeros(max_periods)
    lik_comp_lp = _zeros(max_periods)
    lik_comp_gp = _zeros(max_periods)
    # "Previous LP Distributions" lines (negative) for Tier 1 and Tier 2 hurdle schedules
    t1_prev_lp_dist = _zeros(max_periods)   # -(roc_lp + pref_paid_lp) cumulative through each period
    t2_prev_lp_dist = _zeros(max_periods)   # -(roc_lp + pref_paid_lp + tier1_lp) cumulative through each period

    # Output arrays - cash schedule
    opening_balance_final = _zeros(max_periods)
    closing_balance = _zeros(max_periods)
    net_cash = _zeros(max_periods)
    equity_returns = _zeros(max_periods)
    total_distributions_paid = _zeros(max_periods)

    # Cumulative trackers
    cum_lp_capital = 0.0
    cum_lp_roc = 0.0
    cum_pref_unpaid = 0.0
    cum_pref_unpaid_gp = 0.0
    _cum_gp_cash_eq_abs = 0.0   # Cumulative GP non-LIK equity (cash + addl)

    # Distribution frequency
    dist_freq_str = str(vi.get("pref_dist_frequency") or "Monthly").strip().lower()
    if "quarter" in dist_freq_str:
        dist_interval = 3
    elif "annual" in dist_freq_str or "year" in dist_freq_str:
        dist_interval = 12
    else:
        dist_interval = 1

    # Waterfall parameters (resolve once)
    catchup_en = str(vi.get("catchup_enabled") or "").strip().lower() in (
        "yes", "true", "1",
    )
    catchup_gp_split = vi.get("gp_cashflows_during_catchup", 0.0)   # GP share during catch-up phase (e.g. 0.25)
    catchup_lp_split = vi.get("lp_cashflows_during_catchup", 0.0)   # LP share during catch-up phase (e.g. 0.75)
    # Fall back to legacy catchup_pct (100% GP) if split inputs are absent
    catchup_alloc = catchup_gp_split if catchup_gp_split > 0 else vi.get("catchup_pct", 0.0)
    gp_base_share = vi.get("gp_promote_post_pref", 0.0)  # GP target promote % (e.g. 0.10)
    t1_lp_share = vi.get("tier1_lp_share", 0.0)
    t1_gp_promote_rate = vi.get("tier1_gp_promote", 0.0)
    t2_lp_share = vi.get("tier2_lp_share", 0.0)
    t2_gp_promote_rate = vi.get("tier2_gp_promote", 0.0)
    t3_lp_share = vi.get("tier3_lp_share", 0.0)
    t3_gp_share_rate = vi.get("tier3_gp_share", 0.0)

    net_cash_available_for_dist = _zeros(max_periods)

    # --- Waterfall detail tracking arrays ---
    _wf_pref_begin_lp = _zeros(max_periods)
    _wf_pref_begin_gp = _zeros(max_periods)
    _wf_cash_post_pref = _zeros(max_periods)
    _wf_total_dist_pref = _zeros(max_periods)
    _wf_total_dist_catchup = _zeros(max_periods)
    _wf_cash_pre_catchup = _zeros(max_periods)
    _wf_cash_post_catchup = _zeros(max_periods)
    _wf_t1_begin = _zeros(max_periods)
    _wf_t1_accrual = _zeros(max_periods)
    _wf_t1_end = _zeros(max_periods)
    _wf_t1_gp_catchup_arr = _zeros(max_periods)
    _wf_cash_post_t1_lp = _zeros(max_periods)
    _wf_cash_post_t1_gp = _zeros(max_periods)
    _wf_t2_begin = _zeros(max_periods)
    _wf_t2_accrual = _zeros(max_periods)
    _wf_t2_end = _zeros(max_periods)
    _wf_t2_gp_catchup_arr = _zeros(max_periods)
    _wf_t2_cum_dist_prior = _zeros(max_periods)
    _wf_cash_post_t2_lp = _zeros(max_periods)
    _wf_cash_post_t2_gp = _zeros(max_periods)

    # --- Additional internal trackers for tier hurdle balances ---
    _t1_hurdle_end = 0.0    # Tier 1: running hurdle ending balance (carries forward each period)
    _t2_hurdle_end = 0.0    # Tier 2: running hurdle ending balance (carries forward each period)
    _cum_gp_promote = 0.0   # Cumulative GP promote for catch-up tracking
    _cum_total_dist = 0.0   # Cumulative total distributions (all parties)
    _cum_gp_during_pref = 0.0  # Cumulative GP distributions during pref
    _cum_roc_lp = 0.0       # Cumulative LP capital returned
    _cum_roc_gp = 0.0       # Cumulative GP capital returned
    _cum_lp_equity_abs = 0.0   # Cumulative LP equity contributed (absolute)
    _cum_gp_equity_abs = 0.0   # Cumulative GP equity contributed (absolute)
    _cum_pref_paid_lp = 0.0    # Cumulative LP preferred return distributions
    _cum_pref_paid_gp = 0.0    # Cumulative GP preferred return distributions
    _cum_catchup_gp = 0.0      # Cumulative GP catchup distributed so far
    _cum_t1_lp_dist = 0.0      # Cumulative Tier 1 LP distributions
    _cum_t1_gp_promote = 0.0   # Cumulative Tier 1 GP promote (Soft: paid alongside LP)
    _cum_t1_gp_catchup = 0.0   # Cumulative Tier 1 GP catchup (Hard: separate phase)
    _cum_t2_lp_dist = 0.0      # Cumulative Tier 2 LP distributions
    _cum_t2_gp_promote = 0.0   # Cumulative Tier 2 GP promote (Soft: paid alongside LP)
    _cum_t2_gp_catchup = 0.0   # Cumulative Tier 2 GP catchup (Hard: separate phase)
    # is_hard_pref: True if preferred_return_type is 'Hard'
    _pref_type_str = str(vi.get("pref_return_type") or "").strip().lower()
    _is_hard_pref = (_pref_type_str == "hard")

    # Per-period rates are pre-computed in _t1_rate_per_period / _t2_rate_per_period above.

    for t in range(max_periods):
        # === Cash Schedule: Opening Balance ===
        opening_balance_final[t] = closing_balance[t - 1] if t > 0 else 0.0
        net_cash[t] = net_cash_pre_dist[t]
        pool = opening_balance_final[t] + net_cash[t]

        # === Track equity contributions this period (absolute values) ===
        # LIK compensation is the non-owner's real cash investment (buying their land %)
        # so it IS included in pref/ROC/hurdle account balances. It is reserved from
        # `remaining` below so it pays out as 100% Tier 3 to the land owner.
        _lp_eq_t = abs(lp_contributions_incl[t])
        _gp_eq_t = abs(gp_contributions_incl[t])
        _lik_comp_this_t = 0.0
        if t == _lik_comp_idx and _lik_comp_amount > 0.01:
            _lik_comp_this_t = _lik_comp_amount
        _cum_lp_equity_abs += _lp_eq_t
        _cum_gp_equity_abs += _gp_eq_t
        _cum_gp_cash_eq_abs += abs(gp_cash_plus_addl[t])

        # === Distribution frequency check ===
        is_dist_period = ((t + 1) % dist_interval == 0) or (t == max_periods - 1)

        # === Preferred return account (every period) ===
        # Account structure: closing = opening + contributions + accrual - distributions
        # Opening of current period = closing of previous period (cum_pref_unpaid tracks this).
        _wf_pref_begin_lp[t] = cum_pref_unpaid
        _wf_pref_begin_gp[t] = cum_pref_unpaid_gp
        # Accrual on opening balance only (contributions do not earn in the period received)
        pref_accrual_lp[t] = _wf_pref_begin_lp[t] * _pref_rate_per_period[t]

        # GP accrues only if GP has cash / additional equity (not LIK-only)
        if _cum_gp_cash_eq_abs > 0.01 and _wf_pref_begin_gp[t] > 0.01:
            pref_accrual_gp[t] = _wf_pref_begin_gp[t] * _pref_rate_per_period[t]
        else:
            pref_accrual_gp[t] = 0.0

        if not is_dist_period or pool <= 0.01:
            # --- Non-distribution period: accrue only, no distributions ---
            # closing = opening + contributions + accrual
            _pref_closing_lp[t] = _wf_pref_begin_lp[t] + _lp_eq_t + pref_accrual_lp[t]
            _pref_closing_gp[t] = _wf_pref_begin_gp[t] + _gp_eq_t + pref_accrual_gp[t]
            cum_pref_unpaid = _pref_closing_lp[t]
            cum_pref_unpaid_gp = _pref_closing_gp[t]
            pref_unpaid_lp[t] = cum_pref_unpaid
            pref_unpaid_gp[t] = cum_pref_unpaid_gp

            # Tier hurdle balances accrue on opening balance only; no distributions this period
            _wf_t1_begin[t] = _t1_hurdle_end
            _t1_incurred = _t1_hurdle_end * _t1_rate_per_period[t]
            _wf_t1_accrual[t] = _t1_incurred
            _t1_hurdle_end = _t1_hurdle_end + _lp_eq_t + _t1_incurred
            _wf_t1_end[t] = _t1_hurdle_end

            _wf_t2_begin[t] = _t2_hurdle_end
            _t2_incurred = _t2_hurdle_end * _t2_rate_per_period[t]
            _wf_t2_accrual[t] = _t2_incurred
            _t2_hurdle_end = _t2_hurdle_end + _lp_eq_t + _t2_incurred
            _wf_t2_end[t] = _t2_hurdle_end

            closing_balance[t] = pool
            net_cash_available_for_dist[t] = 0.0
            continue

        # ============================================================
        # DISTRIBUTION PERIOD
        # ============================================================
        # Reserve the LIK compensation from the distributable pool so the normal
        # waterfall (pref, ROC, tiers) only runs on the remainder. The LIK amount
        # is added directly to the owner's Tier 3 bucket after the normal Tier 3 step.
        remaining = max(0.0, pool - _lik_comp_this_t)
        net_cash_available_for_dist[t] = remaining

        # === 1. RETURN OF CAPITAL (Pro-rata LP & GP) ===
        if remaining > 0.01:
            _lp_outstanding = max(0.0, _cum_lp_equity_abs - _cum_roc_lp)
            _gp_outstanding = max(0.0, _cum_gp_equity_abs - _cum_roc_gp)
            _total_outstanding = _lp_outstanding + _gp_outstanding
            if _total_outstanding > 0.01:
                _roc_total = min(remaining, _total_outstanding)
                _lp_share = _lp_outstanding / _total_outstanding
                _gp_share = _gp_outstanding / _total_outstanding
                roc_lp[t] = _roc_total * _lp_share
                roc_gp[t] = _roc_total * _gp_share
                _cum_roc_lp += roc_lp[t]
                _cum_roc_gp += roc_gp[t]
                remaining -= _roc_total

        # === 2. PREFERRED RETURN (LP & GP, pro-rata) ===
        # Each party's preferred return is paid once their own ROC is complete.
        # ROC cumulative trackers were updated in step 1, so a party whose ROC
        # finishes this period correctly triggers preferred in the same period.
        _lp_roc_complete = (_cum_lp_equity_abs - _cum_roc_lp) < 0.01
        _gp_roc_complete = (_cum_gp_equity_abs - _cum_roc_gp) < 0.01

        # Post-accrual balances available for distribution this period
        _pref_avail_lp = _wf_pref_begin_lp[t] + _lp_eq_t + pref_accrual_lp[t]
        _pref_avail_gp = _wf_pref_begin_gp[t] + _gp_eq_t + pref_accrual_gp[t]

        # Only include parties whose ROC is complete in the preferred distribution pool.
        # Cap each party's eligible amount to (account balance - ROC already paid this
        # period) so pref distributions can never drive the account closing negative.
        _pref_eligible_lp = max(0.0, _pref_avail_lp - roc_lp[t]) if _lp_roc_complete else 0.0
        _pref_eligible_gp = max(0.0, _pref_avail_gp - roc_gp[t]) if _gp_roc_complete else 0.0

        _wf_cash_post_pref[t] = remaining  # default: if pref not paid
        if remaining > 0.01:
            _total_pref_due = _pref_eligible_lp + _pref_eligible_gp
            if _total_pref_due > 0.01:
                _pref_payable = min(remaining, _total_pref_due)
                # Pro-rata between eligible parties based on post-accrual balances
                _lp_pref_share = _pref_eligible_lp / _total_pref_due
                _gp_pref_share = _pref_eligible_gp / _total_pref_due
                pref_paid_lp[t] = _pref_payable * _lp_pref_share
                pref_paid_gp[t] = _pref_payable * _gp_pref_share
                remaining -= _pref_payable

            _wf_cash_post_pref[t] = remaining  # after pref, before GP during pref

            # GP cashflow during preferred return period
            if gp_cf_during_pref_rate > 0 and pref_paid_lp[t] > 0.01:
                _gp_pref_amt = pref_paid_lp[t] * gp_cf_during_pref_rate
                gp_during_pref[t] = min(remaining, _gp_pref_amt)
                remaining -= gp_during_pref[t]

        # closing = opening + contributions + accrual - return_of_capital - pref_distributions
        # ROC reduces the preferred account balance since it returns invested capital
        # cum_pref_unpaid is set to closing so next period's opening = this closing
        _pref_closing_lp[t] = _pref_avail_lp - roc_lp[t] - pref_paid_lp[t]
        _pref_closing_gp[t] = _pref_avail_gp - roc_gp[t] - pref_paid_gp[t]
        cum_pref_unpaid = _pref_closing_lp[t]
        cum_pref_unpaid_gp = _pref_closing_gp[t]
        pref_unpaid_lp[t] = cum_pref_unpaid
        pref_unpaid_gp[t] = cum_pref_unpaid_gp

        # Waterfall detail: cash state before catchup
        _wf_cash_pre_catchup[t] = remaining
        _wf_total_dist_pref[t] = (roc_lp[t] + roc_gp[t] + pref_paid_lp[t]
                                   + pref_paid_gp[t] + gp_during_pref[t])

        # === 3. GP CATCH-UP ===
        # Catchup target = (cum_pref_paid_lp + cum_pref_paid_gp) * promote% / (1 - promote%)
        # All available cash goes 100% to GP until this target is met (split ignored).
        # Update cumulative trackers with this period's pre-catchup distributions
        _period_dist_pre_catchup = (
            pref_paid_lp[t] + pref_paid_gp[t] + gp_during_pref[t]
            + roc_lp[t] + roc_gp[t]
        )
        _cum_total_dist += _period_dist_pre_catchup
        _cum_gp_during_pref += gp_during_pref[t]
        _cum_pref_paid_lp += pref_paid_lp[t]
        _cum_pref_paid_gp += pref_paid_gp[t]

        if catchup_en and remaining > 0.01:
            _promote = gp_base_share  # promote% (e.g. 0.20)
            if _promote > 0 and _promote < 1.0:
                # Total catchup GP must receive = pref_total * promote / (1 - promote)
                _pref_total = _cum_pref_paid_lp + _cum_pref_paid_gp
                _catchup_target = _pref_total * _promote / (1.0 - _promote)
                _catchup_still_needed = max(0.0, _catchup_target - _cum_catchup_gp)
                if _catchup_still_needed > 0.01:
                    catchup_gp[t] = min(remaining, _catchup_still_needed)
                    catchup_lp[t] = 0.0
                    _cum_catchup_gp += catchup_gp[t]
                    _cum_gp_promote += catchup_gp[t]
                    remaining -= catchup_gp[t]

        _wf_total_dist_catchup[t] = _wf_total_dist_pref[t] + catchup_gp[t] + catchup_lp[t]
        _wf_cash_post_catchup[t] = remaining

        # === 4. TIER 1 ===
        # Tier 1 hurdle: accrual on opening balance only (contributions do not earn in period received)
        _wf_t1_begin[t] = _t1_hurdle_end
        _t1_incurred = _t1_hurdle_end * _t1_rate_per_period[t]
        _wf_t1_accrual[t] = _t1_incurred
        # Running hurdle: opening + LP equity this period + accrual
        _t1_hurdle_end = _t1_hurdle_end + _lp_eq_t + _t1_incurred

        # Previous LP distributions (ROC + pref paid this period) reduce the hurdle directly
        _t1_prev_this_period = roc_lp[t] + pref_paid_lp[t]
        t1_prev_lp_dist[t] = -_t1_prev_this_period
        _t1_hurdle_end = max(0.0, _t1_hurdle_end - _t1_prev_this_period)
        _t1_needed = _t1_hurdle_end  # remaining hurdle after prev distributions

        if t1_lp_share > 0 and remaining > 0.01 and _t1_needed > 0.01:
            if _is_hard_pref:
                # Hard pref: LP hurdle first, GP gets nothing alongside LP
                _t1_lp_dist = min(remaining, _t1_needed)
                _t1_gp_dist = 0.0
            else:
                # Soft pref: LP and GP promote distributed simultaneously
                _t1_lp_dist = min(remaining * t1_lp_share, _t1_needed)
                _t1_gp_dist = (
                    _t1_lp_dist * t1_gp_promote_rate / t1_lp_share
                    if t1_lp_share > 0 else 0.0
                )
                _t1_total = _t1_lp_dist + _t1_gp_dist
                if _t1_total > remaining:
                    _ratio = remaining / _t1_total if _t1_total > 0 else 0.0
                    _t1_lp_dist *= _ratio
                    _t1_gp_dist *= _ratio

            tier1_lp[t] = _t1_lp_dist
            tier1_gp[t] = _t1_gp_dist
            _t1_hurdle_end = max(0.0, _t1_hurdle_end - _t1_lp_dist)
            _cum_t1_lp_dist += _t1_lp_dist
            _cum_t1_gp_promote += _t1_gp_dist   # Soft: promote paid alongside LP; Hard: 0
            remaining -= _t1_lp_dist

        _wf_t1_end[t] = _t1_hurdle_end
        _wf_cash_post_t1_lp[t] = remaining

        # Deduct GP promote from remaining after the LP snapshot is taken
        remaining -= tier1_gp[t]

        # Tier 1 GP catchup after LP hurdle is cleared (only when catchup is enabled)
        # Catchup needed = (pref_lp + pref_gp + t1_lp) * promote/(1-promote)
        #                  - catchup_gp_after_pref - t1_gp_promote
        if catchup_en and t1_gp_promote_rate > 0 and remaining > 0.01 and _t1_hurdle_end < 0.01:
            if t1_gp_promote_rate < 1.0:
                _t1_cu_target = (
                    (_cum_pref_paid_lp + _cum_pref_paid_gp + _cum_t1_lp_dist)
                    * t1_gp_promote_rate / (1.0 - t1_gp_promote_rate)
                    - _cum_catchup_gp
                    - _cum_t1_gp_promote
                )
                _t1_cu_needed = max(0.0, _t1_cu_target - _cum_t1_gp_catchup)
                _gp_t1_catchup = min(remaining, _t1_cu_needed)
            else:
                _gp_t1_catchup = 0.0
            _wf_t1_gp_catchup_arr[t] = _gp_t1_catchup
            tier1_gp_catchup[t] = _gp_t1_catchup   # Always goes to Catchup line
            _cum_t1_gp_catchup += _gp_t1_catchup
            remaining -= _gp_t1_catchup

        _wf_cash_post_t1_gp[t] = remaining

        # === 5. TIER 2 ===
        # Tier 2 hurdle: accrual on opening balance only (contributions do not earn in period received)
        _wf_t2_begin[t] = _t2_hurdle_end
        _wf_t2_cum_dist_prior[t] = _t2_hurdle_end
        _t2_incurred = _t2_hurdle_end * _t2_rate_per_period[t]
        _wf_t2_accrual[t] = _t2_incurred
        # Running hurdle: opening + LP equity this period + accrual
        _t2_hurdle_end = _t2_hurdle_end + _lp_eq_t + _t2_incurred

        # Previous LP distributions (ROC + pref + tier1_lp this period) reduce the hurdle directly
        _t2_prev_this_period = roc_lp[t] + pref_paid_lp[t] + tier1_lp[t]
        t2_prev_lp_dist[t] = -_t2_prev_this_period
        _t2_hurdle_end = max(0.0, _t2_hurdle_end - _t2_prev_this_period)
        _t2_needed = _t2_hurdle_end  # remaining hurdle after prev distributions

        if t2_lp_share > 0 and remaining > 0.01 and _t2_needed > 0.01:
            if _is_hard_pref:
                # Hard pref: LP hurdle first, GP gets nothing alongside LP
                _t2_lp_dist = min(remaining, _t2_needed)
                _t2_gp_dist = 0.0
            else:
                # Soft pref: LP and GP promote distributed simultaneously
                _t2_lp_dist = min(remaining * t2_lp_share, _t2_needed)
                _t2_gp_dist = (
                    _t2_lp_dist * t2_gp_promote_rate / t2_lp_share
                    if t2_lp_share > 0 else 0.0
                )
                _t2_total = _t2_lp_dist + _t2_gp_dist
                if _t2_total > remaining:
                    _ratio = remaining / _t2_total if _t2_total > 0 else 0.0
                    _t2_lp_dist *= _ratio
                    _t2_gp_dist *= _ratio

            tier2_lp[t] = _t2_lp_dist
            tier2_gp[t] = _t2_gp_dist
            _t2_hurdle_end = max(0.0, _t2_hurdle_end - _t2_lp_dist)
            _cum_t2_lp_dist += _t2_lp_dist
            _cum_t2_gp_promote += _t2_gp_dist   # Soft: promote paid alongside LP; Hard: 0
            remaining -= _t2_lp_dist

        _wf_t2_end[t] = _t2_hurdle_end
        _wf_cash_post_t2_lp[t] = remaining

        # Deduct GP promote from remaining after the LP snapshot is taken
        remaining -= tier2_gp[t]

        # Tier 2 GP catchup after LP hurdle is cleared (only when catchup is enabled)
        # Catchup needed = (pref_lp + pref_gp + t1_lp + t2_lp) * promote/(1-promote)
        #                  - catchup_gp_after_pref - t1_gp_promote - t1_gp_catchup - t2_gp_promote
        if catchup_en and t2_gp_promote_rate > 0 and remaining > 0.01 and _t2_hurdle_end < 0.01:
            if t2_gp_promote_rate < 1.0:
                _t2_cu_target = (
                    (_cum_pref_paid_lp + _cum_pref_paid_gp + _cum_t1_lp_dist + _cum_t2_lp_dist)
                    * t2_gp_promote_rate / (1.0 - t2_gp_promote_rate)
                    - _cum_catchup_gp
                    - _cum_t1_gp_promote
                    - _cum_t1_gp_catchup
                    - _cum_t2_gp_promote
                )
                _t2_cu_needed = max(0.0, _t2_cu_target - _cum_t2_gp_catchup)
                _gp_t2_catchup = min(remaining, _t2_cu_needed)
            else:
                _gp_t2_catchup = 0.0

            _wf_t2_gp_catchup_arr[t] = _gp_t2_catchup
            tier2_gp_catchup[t] = _gp_t2_catchup   # Always goes to Catchup line
            _cum_t2_gp_catchup += _gp_t2_catchup
            remaining -= _gp_t2_catchup

        _wf_cash_post_t2_gp[t] = remaining

        # === 6. TIER 3 (RESIDUAL) ===
        if remaining > 0.01 and (t3_lp_share > 0 or t3_gp_share_rate > 0):
            tier3_lp[t] = remaining * t3_lp_share
            tier3_gp[t] = remaining * t3_gp_share_rate
            remaining -= (tier3_lp[t] + tier3_gp[t])

        # === LIK compensation: 100% to owner, standalone line item ===
        if _lik_comp_this_t > 0.01:
            if _lik_owner == "LP":
                lik_comp_lp[t] = _lik_comp_this_t
            else:
                lik_comp_gp[t] = _lik_comp_this_t

        # === Cash Schedule: Total Distributions & Closing ===
        total_distributions_paid[t] = (
            pref_paid_lp[t] + pref_paid_gp[t] + gp_during_pref[t]
            + roc_lp[t] + roc_gp[t]
            + catchup_lp[t] + catchup_gp[t]
            + tier1_lp[t] + tier1_gp[t] + tier1_gp_catchup[t]
            + tier2_lp[t] + tier2_gp[t] + tier2_gp_catchup[t]
            + tier3_lp[t] + tier3_gp[t]
            + lik_comp_lp[t] + lik_comp_gp[t]
        )
        equity_returns[t] = total_distributions_paid[t]
        closing_balance[t] = pool - total_distributions_paid[t]

        # Update cumulative total dist with tier distributions (post-catchup)
        _tier_dist = (
            tier1_lp[t] + tier1_gp[t] + tier1_gp_catchup[t]
            + tier2_lp[t] + tier2_gp[t] + tier2_gp_catchup[t]
            + tier3_lp[t] + tier3_gp[t]
        )
        _cum_total_dist += _tier_dist
    distributions_check = _zeros(max_periods)
    for t in range(max_periods):
        if closing_balance[t] < -0.01:
            distributions_check[t] = closing_balance[t]

    # =================================================================
    # Post undistributed accrual at the final JV period.
    # This clears any residual preferred return account balance at JV end.
    # =================================================================
    _last_pref_t = fund_end_idx if fund_end_idx is not None else max_periods - 1
    _last_pref_t = max(0, min(_last_pref_t, max_periods - 1))
    _undist_accrual_lp[_last_pref_t] = -_pref_closing_lp[_last_pref_t]
    _undist_accrual_gp[_last_pref_t] = -_pref_closing_gp[_last_pref_t]
    # Adjust the ending balance at that period to reflect the clearing entry
    _pref_closing_lp[_last_pref_t] += _undist_accrual_lp[_last_pref_t]
    _pref_closing_gp[_last_pref_t] += _undist_accrual_gp[_last_pref_t]
    # Zero out opening balance, accrual, and ending balance for all periods
    # after the clearing period — the loop set these before the patch was applied
    for _t in range(_last_pref_t + 1, max_periods):
        _wf_pref_begin_lp[_t] = 0.0
        _wf_pref_begin_gp[_t] = 0.0
        pref_accrual_lp[_t] = 0.0
        pref_accrual_gp[_t] = 0.0
        _pref_closing_lp[_t] = 0.0
        _pref_closing_gp[_t] = 0.0
        _wf_t1_begin[_t] = 0.0
        _wf_t1_accrual[_t] = 0.0
        _wf_t1_end[_t] = 0.0
        _wf_t2_begin[_t] = 0.0
        _wf_t2_accrual[_t] = 0.0
        _wf_t2_end[_t] = 0.0
        _wf_t2_cum_dist_prior[_t] = 0.0

    # =================================================================
    # Clawback: GP compensates LP for any undistributed LP preferred accrual.
    # Amount = min(|undist_accrual_lp|, cumulative GP promotes + catchups).
    # Posted as a lump sum at _last_pref_t.
    # =================================================================
    _cum_gp_promotes = sum(
        tier1_gp[_t] + tier2_gp[_t] + tier3_gp[_t]
        + catchup_gp[_t] + tier1_gp_catchup[_t] + tier2_gp_catchup[_t]
        for _t in range(max_periods)
    )
    _undist_lp_abs = abs(_undist_accrual_lp[_last_pref_t])
    _clawback_amt = min(_undist_lp_abs, _cum_gp_promotes)

    _clawback_amount_arr = _zeros(max_periods)
    _clawback_additions_lp = _zeros(max_periods)
    _clawback_deductions_gp = _zeros(max_periods)
    if _clawback_amt > 0.01:
        _clawback_amount_arr[_last_pref_t] = _clawback_amt
        _clawback_additions_lp[_last_pref_t] = _clawback_amt
        _clawback_deductions_gp[_last_pref_t] = -_clawback_amt

    # =================================================================
    # K. Assemble all CFF rows
    # =================================================================
    # LP totals
    total_lp_distributions = _row_add(
        lp_contributions, pref_paid_lp, roc_lp, catchup_lp,
        tier1_lp, tier2_lp, tier3_lp, lik_comp_lp,
    )
    # GP totals
    total_gp_distributions = _row_add(
        gp_contributions, gp_during_pref, pref_paid_gp, roc_gp, catchup_gp,
        tier1_gp, tier1_gp_catchup, tier2_gp, tier2_gp_catchup, tier3_gp, lik_comp_gp,
    )

    investor_contributions = _row_add(lp_contributions, gp_contributions)
    total_equity_infused = list(equity_infused)
    total_equity_returned = list(equity_returns)
    net_cashflow_investors = _row_add(investor_contributions, equity_returns)

    cff: Dict[str, List[float]] = {
        # Fund-related expenses
        "JV Setup Fees": jv_setup_fees,
        "Fund Management Expenses": fund_mgmt_exp,
        "Other Fees": other_fees_row,
        "JV Liquidation Fees": jv_liq_fees,
        "Total Free Cashflow before Financing": total_fcf_before_fin,
        # Financing Cost
        "Arrangement Fees": _row_negate(total_arr_fees),
        "Commitment Fees": _row_negate(total_commit_fees),
        "Interest Cost": _row_negate(total_interest),
        "Net Funding Requirement": net_funding_req,
        # TL1
        "TL1 Principal Drawn": tl1["principal_drawn"],
        "TL1 Principal Repaid": _row_negate(tl1_repaid_total),
        "TL1 Interest Paid": _row_negate(tl1["interest_paid"]),
        "TL1 Arrangement Fees": _row_negate(tl1["arrangement_fees"]),
        "TL1 Commitment Fees": _row_negate(tl1["commitment_fees"]),
        # TL2
        "TL2 Principal Drawn": tl2["principal_drawn"],
        "TL2 Principal Repaid": _row_negate(tl2["principal_repaid"]),
        "TL2 Interest Paid": _row_negate(tl2["interest_paid"]),
        "TL2 Arrangement Fees": _row_negate(tl2["arrangement_fees"]),
        "TL2 Commitment Fees": _row_negate(tl2["commitment_fees"]),
        # Equity
        "Equity Infused": equity_infused,
        "Equity Returns": equity_returns,
        "Net Financing Cashflows": net_financing_cf,
        # Total Distributions
        "Total Distributions": total_distributions_paid,
        "Investor Contributions": investor_contributions,
        "Total Equity Infused": total_equity_infused,
        "Total Equity Returned": total_equity_returned,
        "Net Cashflow to Investors": net_cashflow_investors,
        # LP Distributions
        "LP Contributions": lp_contributions,
        "In kind Equity": lp_in_kind,
        "Cash Equity": lp_cash_equity,
        "LP Distributions": _row_add(pref_paid_lp, roc_lp, catchup_lp,
                                     tier1_lp, tier2_lp, tier3_lp, lik_comp_lp),
        "Return of Capital - LP": roc_lp,
        "Preferred Returns - LP": pref_paid_lp,
        "Preferred Returns with ROC - LP": pref_paid_lp,
        "Catchup Returns - LP": catchup_lp,
        "Tier 1 Previous LP Distributions": t1_prev_lp_dist,
        "Tier 1 Returns - LP": tier1_lp,
        "Tier 2 Previous LP Distributions": t2_prev_lp_dist,
        "Tier 2 Returns - LP": tier2_lp,
        "Tier 3 Returns - LP": tier3_lp,
        "Clawback Additions - LP": _clawback_additions_lp,
        "Total LP Distributions": total_lp_distributions,
        # GP Distributions
        "GP Contributions": gp_contributions,
        "In kind Equity - GP": gp_in_kind,
        "Cash Equity - GP": gp_cash_equity,
        "GP Distributions": _row_add(gp_during_pref, pref_paid_gp, roc_gp, catchup_gp,
                                     tier1_gp, tier1_gp_catchup, tier2_gp, tier2_gp_catchup, tier3_gp, lik_comp_gp),
        "Return of Capital - GP": roc_gp,
        "Preferred Returns - GP": pref_paid_gp,
        "Preferred Returns with ROC - GP": pref_paid_gp,
        "Catchup Returns - GP": catchup_gp,
        "Tier 1 Promote": tier1_gp,
        "Tier 1 GP Catchup": tier1_gp_catchup,
        "Tier 2 Promote": tier2_gp,
        "Tier 2 GP Catchup": tier2_gp_catchup,
        "Tier 3 Promote": tier3_gp,
        "Compensation in Lieu of Land - GP": lik_comp_gp,
        "Compensation in Lieu of Land - LP": lik_comp_lp,
        "Clawback Deductions - GP": _clawback_deductions_gp,
        "Total GP Distributions": total_gp_distributions,
        # Cash Schedule
        "Opening Balance": opening_balance_final,
        # Cash Flow before Distributions and Repayments =
        #   Cash Flow before Financing + Debt 1 + Debt 2 + LP cash equity + GP cash equity
        "Net Cash": _row_add(
            net_funding_req,
            tl1["loan_additions"],
            tl2["loan_additions"],
            _row_negate(lp_cash_contributions_display),
            _row_negate(gp_cash_contributions_display),
        ),
        # Net Cashflow from Projects = Cash Flow before Distributions and Repayments
        #   + all Distributions and Repayments items (loan repaid, ROC, all distributions)
        "Net Cashflow from Projects": _row_add(
            net_funding_req,
            tl1["loan_additions"],
            tl2["loan_additions"],
            _row_negate(lp_cash_contributions_display),
            _row_negate(gp_cash_contributions_display),
            _row_negate(tl1_repaid_total),
            _row_negate(tl2["principal_repaid"]),
            _row_negate(roc_lp),
            _row_negate(roc_gp),
            _row_negate(pref_paid_lp),
            _row_negate(pref_paid_gp),
            _row_negate(catchup_gp),
            _row_negate(tier1_lp),
            _row_negate(tier1_gp),
            _row_negate(tier1_gp_catchup),
            _row_negate(tier2_lp),
            _row_negate(tier2_gp),
            _row_negate(tier2_gp_catchup),
            _row_negate(tier3_lp),
            _row_negate(tier3_gp),
            _row_negate(lik_comp_lp),
            _row_negate(lik_comp_gp),
        ),
        "Closing Balance": closing_balance,
        "Distributions Check": distributions_check,
    }

    # --- Preferred return schedule (separate output) ---
    cff["_pref_accrual_lp"] = pref_accrual_lp
    cff["_pref_paid_lp"] = pref_paid_lp
    cff["_pref_unpaid_lp"] = pref_unpaid_lp
    cff["_pref_accrual_gp"] = pref_accrual_gp
    cff["_pref_paid_gp"] = pref_paid_gp
    cff["_pref_unpaid_gp"] = pref_unpaid_gp
    cff["GP Distributions During Pref"] = gp_during_pref

    # --- Waterfall detail arrays ---
    cff["_wf_pref_begin_lp"] = _wf_pref_begin_lp
    cff["_wf_pref_begin_gp"] = _wf_pref_begin_gp
    cff["_wf_cash_post_pref"] = _wf_cash_post_pref
    cff["_wf_total_dist_pref"] = _wf_total_dist_pref
    cff["_wf_total_dist_catchup"] = _wf_total_dist_catchup
    cff["_wf_cash_pre_catchup"] = _wf_cash_pre_catchup
    cff["_wf_cash_post_catchup"] = _wf_cash_post_catchup
    cff["_wf_t1_begin"] = _wf_t1_begin
    cff["_wf_t1_accrual"] = _wf_t1_accrual
    cff["_wf_t1_end"] = _wf_t1_end
    cff["_wf_t1_gp_catchup"] = _wf_t1_gp_catchup_arr
    cff["_wf_cash_post_t1_lp"] = _wf_cash_post_t1_lp
    cff["_wf_cash_post_t1_gp"] = _wf_cash_post_t1_gp
    cff["_wf_t2_begin"] = _wf_t2_begin
    cff["_wf_t2_accrual"] = _wf_t2_accrual
    cff["_wf_t2_end"] = _wf_t2_end
    cff["_wf_t2_gp_catchup"] = _wf_t2_gp_catchup_arr
    cff["_wf_t2_cum_dist_prior"] = _wf_t2_cum_dist_prior
    cff["_wf_cash_post_t2_lp"] = _wf_cash_post_t2_lp
    cff["_wf_cash_post_t2_gp"] = _wf_cash_post_t2_gp
    cff["_net_cash_available_for_dist"] = net_cash_available_for_dist
    cff["_lp_contributions_incl"] = lp_contributions_incl
    cff["_gp_contributions_incl"] = gp_contributions_incl
    cff["_pref_closing_lp"] = _pref_closing_lp
    cff["_pref_closing_gp"] = _pref_closing_gp
    cff["_undist_accrual_lp"] = _undist_accrual_lp
    cff["_undist_accrual_gp"] = _undist_accrual_gp

    # --- Term Loan 1 debt schedule (separate output) ---
    cff["_tl1_opening_balance"] = tl1["opening_balance"]
    cff["_tl1_loan_additions"] = tl1["loan_additions"]
    # "Debt Issued" = gross debt raised = loan_additions + cap_interest + cap_arr_fees.
    cff["_tl1_debt_issued"] = _row_add(
        tl1["loan_additions"], tl1["capitalized_interest"], tl1["capitalized_arr_fees"],
    )
    # Gross presentation rows for top section:
    # Interest Expense Paid (gross) = cash interest + capitalized interest
    cff["_tl1_gross_interest_expense"] = _row_add(
        tl1["interest_paid"], tl1["capitalized_interest"],
    )
    # Arrangement Fees Paid (gross) = cash arr fees + capitalized arr fees
    cff["_tl1_gross_arr_fee_expense"] = _row_add(
        tl1["arrangement_fees"], tl1["capitalized_arr_fees"],
    )
    cff["_tl1_capitalized_interest"] = tl1["capitalized_interest"]
    cff["_tl1_capitalized_arr_fees"] = tl1["capitalized_arr_fees"]
    cff["_tl1_repayments"] = tl1["repayments"]
    cff["_tl1_closing_balance"] = tl1["closing_balance"]
    cff["_tl1_eq_infusion_interest"] = tl1["eq_infusion_interest"]
    cff["_tl1_eq_infusion_arr_fees"] = tl1["eq_infusion_arr_fees"]
    cff["_tl1_interest_paid"] = tl1["interest_paid"]
    cff["_tl1_arrangement_fees"] = tl1["arrangement_fees"]
    cff["_tl1_arr_fee_incurred"] = tl1["arr_fee_incurred"]
    cff["_tl1_principal_drawn"] = tl1["principal_drawn"]
    cff["_tl1_interest_incurred"] = tl1["interest_incurred"]
    cff["_tl1_interest_rate_applied"] = tl1["interest_rate_applied"]
    cff["_tl1_amort_pct_applied"] = tl1["amort_pct_applied"]
    cff["_tl1_balloon_payment"] = tl1["balloon_payment"]

    # --- Term Loan 2 / Refinancing Facility debt schedule ---
    cff["_tl2_opening_balance"] = tl2["opening_balance"]
    cff["_tl2_loan_additions"] = tl2["loan_additions"]
    # "Debt Issued" for Refinancing Facility = gross = loan_additions + cap_interest + cap_arr_fees
    cff["_tl2_debt_issued"] = _row_add(
        tl2["loan_additions"], tl2["capitalized_interest"], tl2["capitalized_arr_fees"],
    )
    # Gross presentation rows for Refinancing top section
    cff["_tl2_gross_interest_expense"] = _row_add(
        tl2["interest_paid"], tl2["capitalized_interest"],
    )
    cff["_tl2_gross_arr_fee_expense"] = _row_add(
        tl2["arrangement_fees"], tl2["capitalized_arr_fees"],
    )
    cff["_tl2_capitalized_interest"] = tl2["capitalized_interest"]
    cff["_tl2_capitalized_arr_fees"] = tl2["capitalized_arr_fees"]
    cff["_tl2_repayments"] = tl2["repayments"]
    cff["_tl2_closing_balance"] = tl2["closing_balance"]
    cff["_tl2_interest_paid"] = tl2["interest_paid"]
    cff["_tl2_arrangement_fees"] = tl2["arrangement_fees"]
    cff["_tl2_arr_fee_incurred"] = tl2["arr_fee_incurred"]
    cff["_tl2_principal_drawn"] = tl2["principal_drawn"]
    cff["_tl2_interest_incurred"] = tl2["interest_incurred"]
    cff["_tl2_interest_rate_applied"] = tl2["interest_rate_applied"]
    cff["_tl2_amort_pct_applied"] = tl2["amort_pct_applied"]
    cff["_tl2_balloon_payment"] = tl2["balloon_payment"]
    cff["_tl2_eq_infusion_interest"] = tl2["eq_infusion_interest"]
    cff["_tl2_eq_infusion_arr_fees"] = tl2["eq_infusion_arr_fees"]

    # --- Min DSCR threshold (scalar replicated per period) ---
    cff["_tl2_min_dscr"] = [vi.get("tl2_min_dscr", 0.0)] * max_periods

    # --- Cashflow From Financing Activity (combined TL1 + TL2) ---
    cff["_cashflow_from_financing_activity"] = cashflow_from_financing_activity

    # Log CFF summary

    # =================================================================
    # SECTION A: Equity Schedule (computed pre-loop, just store in cff)
    # =================================================================
    cff["_equity_funding"] = list(equity_funding)
    cff["_gp_commitment"] = gp_commitment
    cff["_lp_commitment"] = lp_commitment

    # =================================================================
    # SECTION B: Additional Equity Requirement (computed pre-loop)
    # =================================================================
    cff["_addl_eq_opening"] = _addl_eq_opening
    cff["_cash_bal_after_infusion"] = _cash_bal_after_infusion
    cff["_addl_eq_req"] = _addl_eq_req
    cff["_addl_eq_closing"] = _addl_eq_closing

    # =================================================================
    # SECTION C: Additional Equity Commitment (computed pre-loop)
    # =================================================================
    cff["_addl_equity_funding"] = _addl_equity_funding
    cff["_gp_addl_commit"] = _gp_addl_commit
    cff["_lp_addl_commit"] = _lp_addl_commit

    investor_contributions = _row_add(lp_contributions_incl, gp_contributions_incl)
    net_cashflow_investors = _row_add(investor_contributions, equity_returns)

    total_lp_distributions = _row_add(
        lp_contributions_incl, pref_paid_lp, roc_lp, catchup_lp,
        tier1_lp, tier2_lp, tier3_lp,
    )
    total_gp_distributions = _row_add(
        gp_contributions_incl, gp_during_pref, pref_paid_gp, roc_gp, catchup_gp,
        tier1_gp, tier1_gp_catchup, tier2_gp, tier2_gp_catchup, tier3_gp,
    )

    cff["LP Contributions"] = lp_cash_contributions_display
    cff["GP Contributions"] = gp_cash_contributions_display
    cff["Total LP Distributions"] = total_lp_distributions
    cff["Total GP Distributions"] = total_gp_distributions
    cff["Investor Contributions"] = investor_contributions
    cff["Net Cashflow to Investors"] = net_cashflow_investors

    # Clawback workings — exclude in-kind equity (non-cash) from net cashflows.
    # total_lp/gp_distributions include lp/gp_in_kind (negative); strip them out.
    cff["_clawback_rolling_irr"] = _zeros(max_periods)
    cff["_clawback_amount"] = _clawback_amount_arr
    cff["_lp_cf_pre_clawback"] = _row_add(total_lp_distributions, _row_negate(lp_in_kind))
    cff["_gp_cf_pre_clawback"] = _row_add(total_gp_distributions, _row_negate(gp_in_kind))


    # =================================================================
    # SECTION D: Land In-Kind Commitment
    # =================================================================
    _lik_commitment = _zeros(max_periods)
    _gp_lik_commit = _zeros(max_periods)
    _lp_lik_commit = _zeros(max_periods)

    if _lik_is_yes_cff:
        # Compute total of upstream land_in_kind, then post at jv_start_idx
        # exactly like section 7b builds land_in_kind_jv.
        _lik_total_cff = sum(abs(_to_float(v)) for v in land_in_kind)
        if jv_start_idx is not None and 0 <= jv_start_idx < max_periods and _lik_total_cff != 0:
            _lik_commitment[jv_start_idx] = abs(_lik_total_cff)
        # Each party's land equity is always their % share of the total land value,
        # regardless of who owns the land. The _lik_owner only determines who pays
        # cash vs contributes in-kind; the non-owner's cash payment is reclassified
        # from additional equity to land in-kind equity in the totals (Section E).
        _gp_lik_commit = [v * vi.get("lik_gp_pct", 0.0) for v in _lik_commitment]
        _lp_lik_commit = [v * vi.get("lik_lp_pct", 0.0) for v in _lik_commitment]

    cff["_lik_commitment"] = _lik_commitment
    cff["_gp_lik_commit"] = _gp_lik_commit
    cff["_lp_lik_commit"] = _lp_lik_commit

    _lik_first_nonzero_idx = next((i for i, v in enumerate(_lik_commitment) if v != 0), None)
    if _lik_is_yes_cff:
        pass
    else:
        pass

    # =================================================================
    # SECTION E: Total Commitment
    # =================================================================
    # _gp_lik_commit / _lp_lik_commit now show the full land value under the owner.
    # _addl_equity_funding includes the non-owner's cash compensation (lik_comp).
    # To avoid double-counting, use _addl_eq_req (pre-injection) for the equity
    # schedule totals when there is a designated land owner.
    # When a land owner is designated, the non-owner's lik_comp sits in _addl_equity_funding.
    # Since it's reclassified to land in-kind equity (shown in _gp/_lp_lik_commit), use
    # _addl_eq_req (pre-injection base) here to avoid double-counting in the equity totals.
    if _lik_comp_amount > 0.01:
        _addl_equity_eq_display = list(_addl_eq_req)
        _gp_addl_eq_display = [v * _cash_gp for v in _addl_equity_eq_display]
        _lp_addl_eq_display = [v * _cash_lp for v in _addl_equity_eq_display]
    else:
        _addl_equity_eq_display = _addl_equity_funding
        _gp_addl_eq_display = _gp_addl_commit
        _lp_addl_eq_display = _lp_addl_commit

    _total_equity_funding = _row_add(equity_funding, _addl_equity_eq_display, _lp_lik_commit, _gp_lik_commit)
    _total_gp_commit = _row_add(gp_commitment, _gp_addl_eq_display, _gp_lik_commit)
    _total_lp_commit = _row_add(lp_commitment, _lp_addl_eq_display, _lp_lik_commit)

    cff["_total_equity_funding"] = _total_equity_funding
    cff["_total_gp_commit"] = _total_gp_commit
    cff["_total_lp_commit"] = _total_lp_commit


    return cff
