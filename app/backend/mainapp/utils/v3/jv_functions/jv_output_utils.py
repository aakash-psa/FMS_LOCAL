"""
JV Consolidation - Output Assembly Utilities
=============================================

Builds the ``exceloutput`` dict consumed by the Office.js add-in.
Consolidated approach: single-pass assembly from CFF/FCFF data into all
26 named-range families (monthly + annual).

Key contract:
  exceloutput = {
      "monthly_dfs": { section_name: (named_range_code, split_payload), ... },
      "annual_dfs":  { section_name: (named_range_code, split_payload), ... },
  }
  split_payload = { "index": [...], "columns": [...], "data": [[...], ...] }
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from mainapp.utils.v3.jv_functions.jv_proforma import (
    proforma_structure,
    PROFORMA_CFF_KEY_MAP,
    BALANCE_ROW_NAMES,
    FCFF_LANDCO,
    FCFF_DEVCO,
    FCFF_ASSETCO,
    FCFF_TOTAL,
    FCFF_LAND_IN_KIND,
)


# =====================================================================
# Low-level helpers
# =====================================================================

def _to_float(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _zeros(n: int) -> List[float]:
    return [0.0] * n


def _sanitize_data(data: list) -> list:
    """Ensure every cell in a 2D data array is JSON-safe.

    ``None`` is kept as-is (becomes ``null`` in JSON / empty Excel cell).
    NaN and Inf are replaced with ``None``.
    """
    clean: List[list] = []
    for row in data:
        clean_row = []
        for v in row:
            if v is None:
                clean_row.append(None)
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean_row.append(None)
            else:
                clean_row.append(v)
        clean.append(clean_row)
    return clean


def _build_split_payload(
    index: list, columns: list, data: list,
) -> dict:
    """Create ``{index, columns, data}`` split payload dict."""
    return {"index": index, "columns": columns, "data": _sanitize_data(data)}


# =====================================================================
# Monthly → Yearly aggregation
# =====================================================================

def _compute_year_boundaries(
    max_periods: int, start_month: int = 1,
) -> List[Tuple[int, int]]:
    """Return calendar-year boundaries as ``[(start_inclusive, end_exclusive), ...]``."""
    if max_periods <= 0:
        return []
    first_year_months = 13 - start_month
    boundaries: List[Tuple[int, int]] = []
    pos = 0
    end = min(first_year_months, max_periods)
    boundaries.append((pos, end))
    pos = end
    while pos < max_periods:
        end = min(pos + 12, max_periods)
        boundaries.append((pos, end))
        pos = end
    return boundaries


def _monthly_to_yearly(
    data_rows: List[list], max_periods: int,
    start_month: int = 1,
) -> Tuple[List[list], List[int]]:
    """Aggregate monthly rows to yearly using calendar-year boundaries."""
    boundaries = _compute_year_boundaries(max_periods, start_month)
    n_years = len(boundaries)
    yearly_cols = list(range(n_years))
    yearly_rows: List[list] = []

    for row in data_rows:
        if all(v is None or v == "" for v in row):
            yearly_rows.append([None] * n_years)
            continue
        yearly_row: List[float] = []
        for ys, ye in boundaries:
            end = min(ye, len(row))
            yearly_row.append(sum(_to_float(v) for v in row[ys:end]))
        yearly_rows.append(yearly_row)

    return yearly_rows, yearly_cols


def _fix_balance_yearly(
    me_data: List[list],
    ye_data: List[list],
    names: List[str],
    balance_labels: List[str],
    max_periods: int,
    start_month: int = 1,
):
    """For balance rows, yearly = last-month-of-year value (not sum)."""
    boundaries = _compute_year_boundaries(max_periods, start_month)
    for i, label in enumerate(names):
        if label in balance_labels:
            yearly_row: List[float] = []
            for ys, ye in boundaries:
                end = min(ye - 1, max_periods - 1)
                yearly_row.append(_to_float(me_data[i][end]))
            ye_data[i] = yearly_row


# =====================================================================
# Section builder: rows from CFF dict by label
# =====================================================================

def _section_rows(
    cff: Dict[str, List[float]],
    labels: List[str],
    max_periods: int,
    key_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], List[list]]:
    """
    Extract data rows from CFF result by label.

    *key_map* optionally remaps display label → CFF dict key when they differ.
    Missing keys become zero rows.
    """
    names: List[str] = []
    data: List[list] = []
    for label in labels:
        names.append(label)
        key = key_map.get(label, label) if key_map else label
        row = cff.get(key, _zeros(max_periods))
        data.append(list(row[:max_periods]))
    return names, data


# =====================================================================
# Timeline builder
# =====================================================================

def _build_timeline(
    model_start, max_periods: int,
) -> Tuple[Optional[dict], Optional[dict]]:
    """Build monthly and yearly timeline payloads."""
    if model_start is None:
        return None, None

    try:
        ts_base = pd.Timestamp(model_start).replace(day=1)
    except Exception:
        return None, None

    start_month = ts_base.month

    tl_index = ["Period Start", "Period End", "Year", "Month", "# of Periods", "# of Days"]
    period_starts = []
    period_ends = []
    years = []
    months = []
    period_numbers = []
    days = []

    for m in range(max_periods):
        ms = ts_base + pd.DateOffset(months=m)
        me = ms + pd.offsets.MonthEnd(0)
        period_starts.append(ms.strftime("%Y-%m-%d"))
        period_ends.append(me.strftime("%Y-%m-%d"))
        years.append(ms.year)
        months.append(ms.month)
        period_numbers.append(m + 1)
        days.append((me - ms).days + 1)

    me_data = [period_starts, period_ends, years, months, period_numbers, days]
    me_cols = list(range(max_periods))
    me_payload = {"index": tl_index, "columns": me_cols, "data": me_data}

    # Yearly timeline
    boundaries = _compute_year_boundaries(max_periods, start_month)
    ye_cols = list(range(len(boundaries)))
    ye_data: List[list] = []
    for ri, row in enumerate(me_data):
        yr_row: List[Any] = []
        for yi, (ys, ye) in enumerate(boundaries):
            chunk = row[ys:ye]
            if not chunk:
                yr_row.append("")
            elif tl_index[ri] == "Period Start":
                yr_row.append(chunk[0])
            elif tl_index[ri] == "Period End":
                yr_row.append(chunk[-1])
            elif tl_index[ri] == "Year":
                yr_row.append(chunk[0])
            elif tl_index[ri] == "Month":
                yr_row.append(yi + 1)
            elif tl_index[ri] == "# of Periods":
                yr_row.append(len(chunk))
            elif tl_index[ri] == "# of Days":
                yr_row.append(sum(int(float(v)) for v in chunk
                                  if str(v).replace('.', '').replace('-', '').isdigit()))
            else:
                yr_row.append(chunk[-1])
        ye_data.append(yr_row)

    ye_payload = {"index": tl_index, "columns": ye_cols, "data": ye_data}

    return me_payload, ye_payload


# =====================================================================
# Detailed Calculation Tab builder
# =====================================================================

def _build_detailed_calculation_tab(
    cff: Dict[str, List[float]],
    fcff_names: List[str],
    fcff_me_data: List[list],
    max_periods: int,
) -> Tuple[List[str], List[list]]:
    """
    Build a single consolidated tab containing ALL calculation rows
    arranged in computation order.  This mirrors the internal CFF
    calculation flow so every intermediate step is visible.

    Returns ``(names, data_rows)`` where each row is ``max_periods`` wide.
    """
    z = _zeros(max_periods)
    names: List[str] = []
    data: List[list] = []

    def _pad_row(row, n):
        row = list(row)
        if len(row) < n:
            row.extend([0.0] * (n - len(row)))
        return row[:n]

    def _section(title: str):
        names.append(title)
        data.append([""] * max_periods)

    def _row(label: str, key: str):
        names.append(label)
        row = cff.get(key, z)
        data.append(list(_pad_row(row, max_periods)))

    # ── 1. FCFF (upstream inputs) ──
    _section("── FCFF (Upstream) ──")
    for label, row in zip(fcff_names, fcff_me_data):
        if label and label != "0":
            names.append(label)
            data.append(list(_pad_row(row, max_periods)))

    # ── 2. Fund-Related Expenses ──
    _section("── Fund-Related Expenses ──")
    _row("JV Setup Fees",                       "JV Setup Fees")
    _row("Fund Management Expenses",            "Fund Management Expenses")
    _row("Other Fees",                          "Other Fees")
    _row("JV Liquidation Fees",                 "JV Liquidation Fees")
    _row("Total Free Cashflow before Financing","Total Free Cashflow before Financing")

    # ── 3. Financing Cost ──
    _section("── Financing Cost ──")
    _row("Arrangement Fees",   "Arrangement Fees")
    _row("Commitment Fees",    "Commitment Fees")
    _row("Interest Cost",      "Interest Cost")
    _row("Net Funding Requirement", "Net Funding Requirement")

    # ── 4. Term Loan 1 ──
    _section("── Term Loan 1 ──")
    _row("TL1 Principal Drawn",    "TL1 Principal Drawn")
    _row("TL1 Principal Repaid",   "TL1 Principal Repaid")
    _row("TL1 Interest Paid",      "TL1 Interest Paid")
    _row("TL1 Arrangement Fees",   "TL1 Arrangement Fees")
    _row("TL1 Commitment Fees",    "TL1 Commitment Fees")

    # ── 5. TL1 Debt Schedule ──
    _section("── TL1 Debt Schedule ──")
    _row("TL1 Opening Balance",             "_tl1_opening_balance")
    _row("TL1 Loan Additions",              "_tl1_loan_additions")
    _row("TL1 Debt Issued",                 "_tl1_debt_issued")
    _row("TL1 Gross Interest Expense",      "_tl1_gross_interest_expense")
    _row("TL1 Gross Arr Fee Expense",       "_tl1_gross_arr_fee_expense")
    _row("TL1 Capitalized Interest",        "_tl1_capitalized_interest")
    _row("TL1 Capitalized Arr Fees",        "_tl1_capitalized_arr_fees")
    _row("TL1 Repayments",                  "_tl1_repayments")
    _row("TL1 Closing Balance",             "_tl1_closing_balance")
    _row("TL1 Eq Infusion Interest",        "_tl1_eq_infusion_interest")
    _row("TL1 Eq Infusion Arr Fees",        "_tl1_eq_infusion_arr_fees")
    _row("TL1 Interest Paid (Schedule)",     "_tl1_interest_paid")
    _row("TL1 Arrangement Fees (Schedule)",  "_tl1_arrangement_fees")
    _row("TL1 Arr Fee Incurred",            "_tl1_arr_fee_incurred")
    _row("TL1 Principal Drawn (Schedule)",   "_tl1_principal_drawn")
    _row("TL1 Interest Incurred",           "_tl1_interest_incurred")
    _row("TL1 Interest Rate Applied",       "_tl1_interest_rate_applied")
    _row("TL1 Amort % Applied",            "_tl1_amort_pct_applied")
    _row("TL1 Balloon Payment",            "_tl1_balloon_payment")

    # ── 6. Term Loan 2 / Refinancing ──
    _section("── Term Loan 2 / Refinancing ──")
    _row("TL2 Principal Drawn",    "TL2 Principal Drawn")
    _row("TL2 Principal Repaid",   "TL2 Principal Repaid")
    _row("TL2 Interest Paid",      "TL2 Interest Paid")
    _row("TL2 Arrangement Fees",   "TL2 Arrangement Fees")
    _row("TL2 Commitment Fees",    "TL2 Commitment Fees")

    # ── 7. TL2 Debt Schedule ──
    _section("── TL2 Debt Schedule ──")
    _row("TL2 Opening Balance",             "_tl2_opening_balance")
    _row("TL2 Loan Additions",              "_tl2_loan_additions")
    _row("TL2 Debt Issued",                 "_tl2_debt_issued")
    _row("TL2 Gross Interest Expense",      "_tl2_gross_interest_expense")
    _row("TL2 Gross Arr Fee Expense",       "_tl2_gross_arr_fee_expense")
    _row("TL2 Capitalized Interest",        "_tl2_capitalized_interest")
    _row("TL2 Capitalized Arr Fees",        "_tl2_capitalized_arr_fees")
    _row("TL2 Repayments",                  "_tl2_repayments")
    _row("TL2 Closing Balance",             "_tl2_closing_balance")
    _row("TL2 Interest Paid (Schedule)",     "_tl2_interest_paid")
    _row("TL2 Arrangement Fees (Schedule)",  "_tl2_arrangement_fees")
    _row("TL2 Arr Fee Incurred",            "_tl2_arr_fee_incurred")
    _row("TL2 Principal Drawn (Schedule)",   "_tl2_principal_drawn")
    _row("TL2 Interest Incurred",           "_tl2_interest_incurred")
    _row("TL2 Interest Rate Applied",       "_tl2_interest_rate_applied")
    _row("TL2 Amort % Applied",            "_tl2_amort_pct_applied")
    _row("TL2 Balloon Payment",            "_tl2_balloon_payment")
    _row("TL2 Eq Infusion Interest",        "_tl2_eq_infusion_interest")
    _row("TL2 Eq Infusion Arr Fees",        "_tl2_eq_infusion_arr_fees")
    _row("TL2 Min DSCR",                   "_tl2_min_dscr")

    # ── 8. Cashflow From Financing Activity ──
    _section("── Cashflow From Financing Activity ──")
    _row("Cashflow From Financing Activity", "_cashflow_from_financing_activity")

    # ── 9. Equity Split ──
    _section("── Equity ──")
    _row("Equity Infused",         "Equity Infused")
    _row("Equity Returns",         "Equity Returns")
    _row("Net Financing Cashflows","Net Financing Cashflows")

    # ── 10. Equity Schedule (Section A) ──
    _section("── Equity Schedule ──")
    _row("Equity Funding",   "_equity_funding")
    _row("GP Commitment",    "_gp_commitment")
    _row("LP Commitment",    "_lp_commitment")

    # ── 11. Additional Equity Requirement (Section B) ──
    _section("── Additional Equity Requirement ──")
    _row("Opening Balance",                    "_addl_eq_opening")
    _row("Cash Balance After Capital Infusion","_cash_bal_after_infusion")
    _row("Additional Equity Requirement",      "_addl_eq_req")
    _row("Closing Balance",                    "_addl_eq_closing")

    # ── 12. Additional Equity Commitment (Section C) ──
    _section("── Additional Equity Commitment ──")
    _row("Additional Equity Funding", "_addl_equity_funding")
    _row("GP Additional Commitment",  "_gp_addl_commit")
    _row("LP Additional Commitment",  "_lp_addl_commit")

    # ── 13. Land In-Kind Commitment (Section D) ──
    _section("── Land In-Kind Commitment ──")
    _row("LIK Commitment",       "_lik_commitment")
    _row("GP LIK Commitment",    "_gp_lik_commit")
    _row("LP LIK Commitment",    "_lp_lik_commit")

    # ── 14. Total Commitment (Section E) ──
    _section("── Total Commitment ──")
    _row("Total Equity Funding", "_total_equity_funding")
    _row("Total GP Commitment",  "_total_gp_commit")
    _row("Total LP Commitment",  "_total_lp_commit")

    # ── 15. Preferred Return Schedule ──
    _section("── Preferred Return Schedule ──")
    _row("Preferred Accrual - LP", "_pref_accrual_lp")
    _row("Preferred Paid - LP",    "_pref_paid_lp")
    _row("Preferred Unpaid - LP",  "_pref_unpaid_lp")
    _row("Preferred Accrual - GP", "_pref_accrual_gp")
    _row("Preferred Paid - GP",    "_pref_paid_gp")
    _row("Preferred Unpaid - GP",  "_pref_unpaid_gp")

    # ── 16. Distribution Waterfall ──
    _section("── Distribution Waterfall ──")
    _row("Total Distributions",      "Total Distributions")
    _row("Investor Contributions",   "Investor Contributions")
    _row("Total Equity Infused",     "Total Equity Infused")
    _row("Total Equity Returned",    "Total Equity Returned")
    _row("Net Cashflow to Investors","Net Cashflow to Investors")

    # ── 17. LP Distributions ──
    _section("── LP Distributions ──")
    _row("LP Contributions",       "LP Contributions")
    _row("In kind Equity",         "In kind Equity")
    _row("Cash Equity",            "Cash Equity")
    _row("LP Distributions",       "LP Distributions")
    _row("Return of Capital - LP", "Return of Capital - LP")
    _row("Preferred Returns - LP", "Preferred Returns - LP")
    _row("Catchup Returns - LP",   "Catchup Returns - LP")
    _row("Tier 1 Previous LP Distributions", "Tier 1 Previous LP Distributions")
    _row("Tier 1 Returns - LP",    "Tier 1 Returns - LP")
    _row("Tier 2 Previous LP Distributions", "Tier 2 Previous LP Distributions")
    _row("Tier 2 Returns - LP",    "Tier 2 Returns - LP")
    _row("Tier 3 Returns - LP",    "Tier 3 Returns - LP")
    _row("Clawback Additions - LP","Clawback Additions - LP")
    _row("Total LP Distributions", "Total LP Distributions")

    # ── 18. GP Distributions ──
    _section("── GP Distributions ──")
    _row("GP Contributions",        "GP Contributions")
    _row("In kind Equity - GP",     "In kind Equity - GP")
    _row("Cash Equity - GP",        "Cash Equity - GP")
    _row("GP Distributions",        "GP Distributions")
    _row("Return of Capital - GP",  "Return of Capital - GP")
    _row("Preferred Returns - GP",  "Preferred Returns - GP")
    _row("Catchup Returns - GP",    "Catchup Returns - GP")
    _row("Tier 1 Promote",          "Tier 1 Promote")
    _row("Tier 1 GP Catchup",       "Tier 1 GP Catchup")
    _row("Tier 2 Promote",          "Tier 2 Promote")
    _row("Tier 2 GP Catchup",       "Tier 2 GP Catchup")
    _row("Tier 3 Promote",          "Tier 3 Promote")
    _row("Clawback Deductions - GP","Clawback Deductions - GP")
    _row("Total GP Distributions",  "Total GP Distributions")

    # ── 19. Cash Schedule ──
    _section("── Cash Schedule ──")
    _row("Opening Balance",      "Opening Balance")
    _row("Net Cash",             "Net Cash")
    _row("Closing Balance",      "Closing Balance")
    _row("Distributions Check",  "Distributions Check")

    return names, data


# =====================================================================
# Proforma renderer
# =====================================================================

def _render_proforma_section(
    section_name: str,
    content: List[dict],
    cff: Dict[str, List[float]],
    fcff_sources: Dict[str, List[float]],
    max_periods: int,
) -> Tuple[List[str], List[list]]:
    """
    Walk one proforma section's ``content`` list and produce parallel
    ``(names, data_rows)`` lists ready for ``_build_split_payload``.

    Dispatch rules per item type:
        ``section`` / ``subsection``  → header row with ``[None] * max_periods``
        ``empty_row``                 → blank label, ``[None] * max_periods``
        ``line_item``                 → resolved numeric row (zeros on miss)

    Disambiguation: items whose label repeats within the same section are
    resolved by the *active subsection* context.  The renderer tries:
        1. ``(section_name, f"{active_subsec} / {item_name}")``
        2. ``(section_name, item_name)``
    Only the non-default occurrence needs an explicit disambiguated entry in
    ``PROFORMA_CFF_KEY_MAP``; the default falls through to the plain key.
    """
    z_none: List = [None] * max_periods
    z_float: List[float] = [0.0] * max_periods

    def _pad(row, fill=0.0) -> List[float]:
        row = list(row)
        if len(row) < max_periods:
            row.extend([fill] * (max_periods - len(row)))
        return row[:max_periods]

    def _resolve_descriptor(desc: Optional[Dict]) -> List:
        if desc is None:
            return list(z_float)

        if desc.get("zero"):
            return list(z_float)

        if "source" in desc:
            src = fcff_sources.get(desc["source"], z_float)
            return _pad(src)

        if "key" in desc:
            row = _pad(cff.get(desc["key"], z_float))
            if desc.get("negate"):
                return [-v for v in row]
            return row

        if "compute" in desc:
            op = desc["compute"]["op"]
            a = _pad(cff.get(desc["compute"]["a"], z_float))
            b = _pad(cff.get(desc["compute"]["b"], z_float))
            if op == "sub":
                return [a[i] - b[i] for i in range(max_periods)]
            if op == "add":
                return [a[i] + b[i] for i in range(max_periods)]
            return list(z_float)

        if "combine" in desc:
            result = list(z_float)
            for k in desc["combine"]:
                row = _pad(cff.get(k, z_float))
                result = [result[i] + _to_float(row[i]) for i in range(max_periods)]
            if desc.get("negate"):
                return [-v for v in result]
            return result

        return list(z_float)

    names: List[str] = []
    data:  List[list] = []
    active_subsec: Optional[str] = None

    def _process(items: List[dict]):
        nonlocal active_subsec
        for item in items:
            itype = item.get("type")
            iname = item.get("name", "")

            if itype == "empty_row":
                names.append("")
                data.append(list(z_none))

            elif itype in ("section", "subsection"):
                names.append(iname)
                data.append(list(z_none))
                if iname:
                    active_subsec = iname
                if "items" in item:
                    _process(item["items"])

            elif itype == "line_item":
                # Try contextual key first, fall back to plain key
                desc = None
                if active_subsec:
                    desc = PROFORMA_CFF_KEY_MAP.get(
                        (section_name, f"{active_subsec} / {iname}")
                    )
                if desc is None:
                    desc = PROFORMA_CFF_KEY_MAP.get((section_name, iname))

                names.append(iname)
                data.append(_resolve_descriptor(desc))

    _process(content)
    return names, data


# =====================================================================
# Main consolidated output assembly
# =====================================================================

def build_consolidated_output(
    *,
    # FCFF DataFrames (per-asset)
    landco_fcff_df: pd.DataFrame,
    devco_fcff_df: pd.DataFrame,
    assetco_fcff_df: pd.DataFrame,
    total_fcff_jv_df: pd.DataFrame,
    total_fcff_incl_lik_jv_df: pd.DataFrame,
    land_in_kind_jv_df: pd.DataFrame,
    land_cost_jv_df: pd.DataFrame,
    landco_cff_lik_df: Optional[pd.DataFrame] = None,
    module_consol_jv_df: pd.DataFrame = None,
    asset_sales_jv_df: pd.DataFrame,
    # CFF result per vehicle
    vehicle_cff: Dict[str, Dict[str, List[float]]],
    # Resolved inputs per vehicle (contains gp_role / lp_role)
    vehicle_inputs: Optional[Dict[str, dict]] = None,
    # Dimensions
    max_periods: int,
    model_start,
    selected_assets: list,
    period_cols: list,
    # Named range constants (passed from caller to avoid circular import)
    NR: dict,
    # Selected vehicle/scenario filter
    selected_vehicle: Optional[str] = None,
    jv_groups: Optional[Dict[str, list]] = None,
) -> dict:
    """
    Assemble the full ``exceloutput`` payload in a single consolidated pass.

    Returns ``{"exceloutput": {...}, "consolidationoutput": {},
               "loan_schedule_sheets": {...}}``.
    """
    try:
        ts_base = pd.Timestamp(model_start).replace(day=1) if model_start else None
    except Exception:
        ts_base = None

    start_month = ts_base.month if ts_base else 1
    monthly_cols = list(range(max_periods))
    boundaries = _compute_year_boundaries(max_periods, start_month)
    yearly_cols = list(range(len(boundaries)))

    z = _zeros(max_periods)

    # Resolve which vehicle's CFF to display based on selected_vehicle.
    # Match by lowercased name; fall back to first vehicle if no match.
    _active_vname = None
    if vehicle_cff:
        if selected_vehicle:
            _sv_lower = selected_vehicle.strip().lower()
            for _vname in vehicle_cff:
                if _vname.strip().lower() == _sv_lower:
                    _active_vname = _vname
                    break
        if _active_vname is None:
            _active_vname = next(iter(vehicle_cff))
        cff = vehicle_cff[_active_vname]
    else:
        cff = {}

    # Resolve which assets belong to the active vehicle for FCFF aggregation.
    _vehicle_assets = None
    if _active_vname and jv_groups:
        _vg = jv_groups.get(_active_vname)
        if not _vg:
            # Try case-insensitive match
            _al = _active_vname.strip().lower()
            for _k, _v in jv_groups.items():
                if _k.strip().lower() == _al:
                    _vg = _v
                    break
        if _vg:
            _vehicle_assets = [a.strip().lower() for a in _vg]

    def _filter_df(df: pd.DataFrame) -> pd.DataFrame:
        """Return rows belonging to the active vehicle; fall back to all rows."""
        if _vehicle_assets is None or df is None or df.empty:
            return df
        mask = [str(idx).strip().lower() in _vehicle_assets for idx in df.index]
        filtered = df[mask]
        return filtered if not filtered.empty else df

    monthly_dfs: Dict[str, tuple] = {}
    annual_dfs:  Dict[str, tuple] = {}

    def _add_section(
        section_name: str,
        me_nr: str,
        ye_nr: str,
        labels: List[str],
        key_map: Optional[Dict[str, str]] = None,
        balance_labels: Optional[List[str]] = None,
    ):
        """Helper: build one output section (monthly + yearly) and register it."""
        names, me_data = _section_rows(cff, labels, max_periods, key_map)
        ye_data, _ = _monthly_to_yearly(me_data, max_periods, start_month)
        if balance_labels:
            _fix_balance_yearly(me_data, ye_data, names, balance_labels,
                                max_periods, start_month)
        me_pl = _build_split_payload(names, monthly_cols, me_data)
        ye_pl = _build_split_payload(names, yearly_cols, ye_data)
        monthly_dfs[section_name] = (me_nr, me_pl)
        annual_dfs[section_name] = (ye_nr, ye_pl)

    def _add_section_raw(
        section_name: str,
        me_nr: str,
        ye_nr: str,
        names: List[str],
        me_data: List[list],
        balance_labels: Optional[List[str]] = None,
    ):
        """Helper: register pre-built data rows."""
        ye_data, _ = _monthly_to_yearly(me_data, max_periods, start_month)
        if balance_labels:
            _fix_balance_yearly(me_data, ye_data, names, balance_labels,
                                max_periods, start_month)
        me_pl = _build_split_payload(names, monthly_cols, me_data)
        ye_pl = _build_split_payload(names, yearly_cols, ye_data)
        monthly_dfs[section_name] = (me_nr, me_pl)
        annual_dfs[section_name] = (ye_nr, ye_pl)

    # =================================================================
    # Proforma-driven output — one section per proforma_structure entry
    # =================================================================

    # FCFF aggregates (summed across active vehicle's assets only)
    _lc_df  = _filter_df(landco_fcff_df)
    _dc_df  = _filter_df(devco_fcff_df)
    _ac_df  = _filter_df(assetco_fcff_df)
    _tf_df  = _filter_df(total_fcff_jv_df)
    _lk_df  = _filter_df(landco_cff_lik_df) if landco_cff_lik_df is not None else None
    landco_total    = _lc_df.values.sum(axis=0).tolist()  if _lc_df  is not None and _lc_df.shape[0]  > 0 else z
    devco_total     = _dc_df.values.sum(axis=0).tolist()  if _dc_df  is not None and _dc_df.shape[0]  > 0 else z
    assetco_total   = _ac_df.values.sum(axis=0).tolist()  if _ac_df  is not None and _ac_df.shape[0]  > 0 else z
    total_fcff_sum  = _tf_df.values.sum(axis=0).tolist()  if _tf_df  is not None and _tf_df.shape[0]  > 0 else z
    landco_cff_lik_total = _lk_df.values.sum(axis=0).tolist() if _lk_df is not None and _lk_df.shape[0] > 0 else z

    # Sentinel-keyed dict consumed by _render_proforma_section
    fcff_sources: Dict[str, list] = {
        FCFF_LANDCO:       landco_total[:max_periods],
        FCFF_DEVCO:        devco_total[:max_periods],
        FCFF_ASSETCO:      assetco_total[:max_periods],
        FCFF_TOTAL:        total_fcff_sum[:max_periods],
        FCFF_LAND_IN_KIND: landco_cff_lik_total[:max_periods],
    }

    # Named-range codes per proforma section — (monthly_nr, annual_nr)
    _SECTION_NR: Dict[str, tuple] = {
        "Cash Waterfall and Return distribution": (
            NR.get("OUT_CASHFLOWS_ME",    "o.jv.cashflows.me"),
            NR.get("OUT_CASHFLOWS_YE",    "o.jv.cashflows.ye"),
        ),
        "Debt 1 Account": (
            NR.get("OUT_TL1_SCHED_ME",    "o.jv.termloan1schedule.me"),
            NR.get("OUT_TL1_SCHED_YE",    "o.jv.termloan1schedule.ye"),
        ),
        "Refinancing Debt Account": (
            NR.get("OUT_REFI_SCHED_ME",   "o.jv.refinanceschedule.me"),
            NR.get("OUT_REFI_SCHED_YE",   "o.jv.refinanceschedule.ye"),
        ),
        "Equity Scehdule": (
            NR.get("OUT_EQUITY_SCHED_ME", "o.jv.equity.schedule.me"),
            NR.get("OUT_EQUITY_SCHED_YE", "o.jv.equity.schedule.ye"),
        ),
        "Waterfall Distribution": (
            NR.get("OUT_PREF_RETURNS_ME", "o.jv.preferred.returns.me"),
            NR.get("OUT_PREF_RETURNS_YE", "o.jv.preferred.returns.ye"),
        ),
        "Clawback Workings": (
            NR.get("OUT_CLAWBACK_ME",     "o.jv.clawback.me"),
            NR.get("OUT_CLAWBACK_YE",     "o.jv.clawback.ye"),
        ),
    }

    for section_name, section_def in proforma_structure.items():
        sec_names, sec_data = _render_proforma_section(
            section_name,
            section_def["content"],
            cff,
            fcff_sources,
            max_periods,
        )

        ye_data, _ = _monthly_to_yearly(sec_data, max_periods, start_month)

        # Balance rows use last-month-of-year value, not annual sum
        _fix_balance_yearly(
            sec_data, ye_data, sec_names,
            BALANCE_ROW_NAMES, max_periods, start_month,
        )

        me_pl = _build_split_payload(sec_names, monthly_cols, sec_data)
        ye_pl = _build_split_payload(sec_names, yearly_cols, ye_data)

        nr_me, nr_ye = _SECTION_NR.get(section_name, ("", ""))
        monthly_dfs[section_name] = (nr_me, me_pl)
        annual_dfs[section_name]  = (nr_ye, ye_pl)

    # Keep FCFF arrays available for downstream use (detailed calcs, etc.)
    fcff_names = [
        "Land Co Free Cashflow",
        "Dev Co Free Cashflow",
        "Asset Co Free Cashflow",
        "Total Free Cashflow before Financing and SPV Related Cost",
    ]
    fcff_me = [
        list(landco_total[:max_periods]),
        list(devco_total[:max_periods]),
        list(assetco_total[:max_periods]),
        list(total_fcff_sum[:max_periods]),
    ]

    # -----------------------------------------------------------------
    # Timeline
    # -----------------------------------------------------------------
    tl_me_payload, tl_ye_payload = _build_timeline(model_start, max_periods)
    if tl_me_payload:
        tl_me = dict(tl_me_payload)
        tl_me["data"] = _sanitize_data(tl_me.get("data", []))
        monthly_dfs["Monthly Timeline"] = (NR.get("OUT_TIMELINE_ME", "o.jv.model.timeline.me"), tl_me)
    if tl_ye_payload:
        tl_ye = dict(tl_ye_payload)
        tl_ye["data"] = _sanitize_data(tl_ye.get("data", []))
        annual_dfs["Yearly Timeline"] = (NR.get("OUT_TIMELINE_YE", "o.jv.model.timeline.ye"), tl_ye)

    # -----------------------------------------------------------------
    # Returns (scalar metrics - encoded as single-row sections)
    # -----------------------------------------------------------------
    def _scalar_val(v):
        """Format scalar return for JSON."""
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return ""
            return round(v, 8)
        return v

    # -----------------------------------------------------------------
    # Loan schedule sheets (diagnostic worksheets)
    # -----------------------------------------------------------------
    loan_schedule_sheets: Dict[str, dict] = {}
    if cff and max_periods > 0 and ts_base is not None:
        _ls_starts: List[str] = []
        _ls_ends: List[str] = []
        for _m in range(max_periods):
            _ms = ts_base + pd.DateOffset(months=_m)
            _me = _ms + pd.offsets.MonthEnd(0)
            _ls_starts.append(_ms.strftime("%Y-%m-%d"))
            _ls_ends.append(_me.strftime("%Y-%m-%d"))

        # TL1 schedule worksheet
        _tl1_sched_amort = [
            _to_float(cff.get("_tl1_repayments", z)[t])
            - _to_float(cff.get("_tl1_balloon_payment", z)[t])
            for t in range(max_periods)
        ]
        loan_schedule_sheets["tl1"] = {
            "sheet_name": "Term Loan 1 Schedule",
            "headers": {"Month Start": _ls_starts, "Month End": _ls_ends},
            "rows": [
                ("Opening Balance",                    list(cff.get("_tl1_opening_balance", z))),
                ("Principal / Loan Raised",            list(cff.get("_tl1_loan_additions", z))),
                ("Interest Expense Incurred",          list(cff.get("_tl1_interest_incurred", z))),
                ("Interest Expense Paid",              list(cff.get("_tl1_interest_paid", z))),
                ("Interest Expense Capitalized",       list(cff.get("_tl1_capitalized_interest", z))),
                ("Arrangement Fees Paid",              list(cff.get("_tl1_arrangement_fees", z))),
                ("Arrangement Fees Capitalized",       list(cff.get("_tl1_capitalized_arr_fees", z))),
                ("EMI / Scheduled Principal Repayment", _tl1_sched_amort),
                ("Balloon Payment",                    list(cff.get("_tl1_balloon_payment", z))),
                ("Total Debt Repaid",                  list(cff.get("_tl1_repayments", z))),
                ("Closing Balance",                    list(cff.get("_tl1_closing_balance", z))),
                ("Interest Rate Applied",              list(cff.get("_tl1_interest_rate_applied", z))),
                ("Amortization % Applied",             list(cff.get("_tl1_amort_pct_applied", z))),
            ],
        }

        # TL2 / Refinancing schedule worksheet
        _tl2_sched_amort = [
            _to_float(cff.get("_tl2_repayments", z)[t])
            - _to_float(cff.get("_tl2_balloon_payment", z)[t])
            for t in range(max_periods)
        ]
        _tl2_op_cf = cff.get("Total Free Cashflow before Financing", z)
        _tl2_dscr: List[float] = []
        for _t in range(max_periods):
            _ds = (_to_float(cff.get("_tl2_repayments", z)[_t])
                   + _to_float(cff.get("_tl2_interest_paid", z)[_t]))
            _tl2_dscr.append(_tl2_op_cf[_t] / _ds if abs(_ds) > 0.01 else 0.0)

        loan_schedule_sheets["tl2"] = {
            "sheet_name": "Refinancing Schedule",
            "headers": {"Month Start": _ls_starts, "Month End": _ls_ends},
            "rows": [
                ("Opening Balance",                    list(cff.get("_tl2_opening_balance", z))),
                ("Principal / Loan Raised",            list(cff.get("_tl2_loan_additions", z))),
                ("Interest Expense Incurred",          list(cff.get("_tl2_interest_incurred", z))),
                ("Interest Expense Paid",              list(cff.get("_tl2_interest_paid", z))),
                ("Interest Expense Capitalized",       list(cff.get("_tl2_capitalized_interest", z))),
                ("Arrangement Fees Paid",              list(cff.get("_tl2_arrangement_fees", z))),
                ("Arrangement Fees Capitalized",       list(cff.get("_tl2_capitalized_arr_fees", z))),
                ("EMI / Scheduled Principal Repayment", _tl2_sched_amort),
                ("Balloon Payment",                    list(cff.get("_tl2_balloon_payment", z))),
                ("Total Debt Repaid",                  list(cff.get("_tl2_repayments", z))),
                ("Closing Balance",                    list(cff.get("_tl2_closing_balance", z))),
                ("Interest Rate Applied",              list(cff.get("_tl2_interest_rate_applied", z))),
                ("Amortization % Applied",             list(cff.get("_tl2_amort_pct_applied", z))),
                ("DSCR",                               _tl2_dscr),
            ],
        }

    # -----------------------------------------------------------------
    # Consolidation output — proforma for every scenario/vehicle
    # -----------------------------------------------------------------
    consolidation_output: Dict[str, Any] = {}

    for vname, vcff in vehicle_cff.items():
        # FCFF aggregation scoped to this vehicle's assets
        if jv_groups:
            _vg = jv_groups.get(vname)
            if not _vg:
                _al = vname.strip().lower()
                for _k, _v in jv_groups.items():
                    if _k.strip().lower() == _al:
                        _vg = _v
                        break
            _vassets = [a.strip().lower() for a in _vg] if _vg else None
        else:
            _vassets = None

        def _filter_for_vehicle(df: pd.DataFrame, vassets) -> pd.DataFrame:
            if vassets is None or df is None or df.empty:
                return df
            mask = [str(idx).strip().lower() in vassets for idx in df.index]
            filtered = df[mask]
            return filtered if not filtered.empty else df

        _v_lc = _filter_for_vehicle(landco_fcff_df, _vassets)
        _v_dc = _filter_for_vehicle(devco_fcff_df, _vassets)
        _v_ac = _filter_for_vehicle(assetco_fcff_df, _vassets)
        _v_tf = _filter_for_vehicle(total_fcff_jv_df, _vassets)
        _v_lk = _filter_for_vehicle(landco_cff_lik_df, _vassets) if landco_cff_lik_df is not None else None

        _v_landco_total      = _v_lc.values.sum(axis=0).tolist() if _v_lc is not None and _v_lc.shape[0] > 0 else z
        _v_devco_total       = _v_dc.values.sum(axis=0).tolist() if _v_dc is not None and _v_dc.shape[0] > 0 else z
        _v_assetco_total     = _v_ac.values.sum(axis=0).tolist() if _v_ac is not None and _v_ac.shape[0] > 0 else z
        _v_total_fcff        = _v_tf.values.sum(axis=0).tolist() if _v_tf is not None and _v_tf.shape[0] > 0 else z
        _v_landco_cff_lik    = _v_lk.values.sum(axis=0).tolist() if _v_lk is not None and _v_lk.shape[0] > 0 else z

        _v_fcff_sources: Dict[str, list] = {
            FCFF_LANDCO:       _v_landco_total[:max_periods],
            FCFF_DEVCO:        _v_devco_total[:max_periods],
            FCFF_ASSETCO:      _v_assetco_total[:max_periods],
            FCFF_TOTAL:        _v_total_fcff[:max_periods],
            FCFF_LAND_IN_KIND: _v_landco_cff_lik[:max_periods],
        }

        scenario_proforma: Dict[str, Any] = {}
        for section_name, section_def in proforma_structure.items():
            sec_names, sec_me_data = _render_proforma_section(
                section_name,
                section_def["content"],
                vcff,
                _v_fcff_sources,
                max_periods,
            )
            sec_ye_data, _ = _monthly_to_yearly(sec_me_data, max_periods, start_month)
            _fix_balance_yearly(
                sec_me_data, sec_ye_data, sec_names,
                BALANCE_ROW_NAMES, max_periods, start_month,
            )
            scenario_proforma[section_name] = {
                "rows": sec_names,
                "monthly": _sanitize_data(sec_me_data),
                "annual":  _sanitize_data(sec_ye_data),
            }

        # Per-asset LandCo CFF "Land In Kind" — consumed by consolidated_model for CFS/BS/trace
        if _v_lk is not None and not _v_lk.empty:
            scenario_proforma["land_in_kind_per_asset"] = {
                str(idx).strip(): [float(v) for v in _v_lk.loc[idx].values]
                for idx in _v_lk.index
                if abs(float(_v_lk.loc[idx].sum())) > 0.01
            }
        else:
            scenario_proforma["land_in_kind_per_asset"] = {}

        # ROSHN role for this vehicle (LP or GP), plus equity split percentages
        _vi = (vehicle_inputs or {}).get(vname, {})
        _gp_role = _vi.get("gp_role", "")
        _lp_role = _vi.get("lp_role", "")
        _roshn_role = "lp" if str(_lp_role).strip().lower() == "roshn" else (
                      "gp" if str(_gp_role).strip().lower() == "roshn" else "unknown")
        scenario_proforma["roshn_role"] = {
            "role": _roshn_role,
            "gp_party": _gp_role,
            "lp_party": _lp_role,
            "gp_pct": _scalar_val(_vi.get("effective_gp_pct")),
            "lp_pct": _scalar_val(_vi.get("effective_lp_pct")),
            "lik_owner": str(_vi.get("lik_owner") or "").strip().upper(),
        }

        consolidation_output[vname] = scenario_proforma

    # -----------------------------------------------------------------
    # Final assembly
    # -----------------------------------------------------------------
    excel_output = {
        "monthly_dfs": monthly_dfs,
        "annual_dfs": annual_dfs,
    }

    return {
        "exceloutput": excel_output,
        "consolidationoutput": consolidation_output,
    }
