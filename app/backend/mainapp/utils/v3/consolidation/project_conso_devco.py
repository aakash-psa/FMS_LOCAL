"""  """"""
================================================================================
CONSOLIDATED MODEL - VERSION 3
================================================================================

This module provides the complete consolidation framework for building unified
financial statements and cashflows for the DevCo consolidation model.

================================================================================
ARCHITECTURE OVERVIEW
================================================================================

The module is organized into four distinct sections:

SECTION A: IMPORTS
    - Standard library imports (os, traceback, time, datetime)
    - Type hints (Any, Dict, List, Tuple, Optional, Union)
    - Data processing libraries (pandas, numpy)
    - Module constants and configuration values

SECTION B: SUPPORT FUNCTIONS
    - JSON/DataFrame conversion utilities
    - Data extraction and validation helpers
    - Timeline construction functions
    - Template building utilities
    - Output payload transformation functions

SECTION C: CALCULATION LOGIC FUNCTIONS
    - Double-entry accounting functions
    - Account creation and management
    - Journal entry recording (scalar and vectorized)
    - Financial statement initialization and updates
    - Balance propagation and calculations
    - Presentable statement formatting functions

SECTION D: EXECUTION
    - Configuration structures (account names, financial statement layouts)
    - Main consolidation wrapper (wrapper_for_vars)
    - Entry point function (fninitialising_all_values)

================================================================================
OUTPUT FORMAT
================================================================================

The module produces three output dictionaries:

monthly_dfs = {
    "Sheet Name": ("o.consolidated.code.me", DataFrame),
    ...
}

annual_dfs = {
    "Sheet Name": ("o.consolidated.code.ye", DataFrame),
    ...
}

excel_output = {
    "monthly_dfs": {
        "Sheet Name": ("code", {"index": [], "columns": [], "data": []}),
        ...
    },
    "annual_dfs": {...}
}

================================================================================
USAGE
================================================================================

    from consolidated_model import fninitialising_all_values
    
    payload = {
        "landco": {...},
        "devco": {...},
        "assetco_consolidated": [...],
        "jv_consolidation": [...]
    }
    
    result = fninitialising_all_values(payload)

================================================================================
"""

# ==============================================================================
# SECTION A: IMPORTS
# ==============================================================================
# This section contains all module imports and global constants.
# ==============================================================================

import os
import traceback
import time
from collections import defaultdict
from datetime import datetime

from typing import Any, Dict, List, Tuple, Optional, Union

import pandas as pd
import numpy as np

import json

from .project_conso_utils import (
    _SPLIT_DF_REQUIRED_KEYS,
    fn_json_dict_to_dataframe,
    fn_extract_assumptions_module,
    fn_safe_extract_dataframe,
    fn_extract_assumptions,
    fn_extract_core_sources,
    fn_extract_module_data,
    fn_build_master_timeline,
    fn_build_monthly_model_timeline,
    fn_build_yearly_model_timeline,
    fn_build_template_row_index,
    fn_initialize_consolidated_dataframe,
    fn_build_financial_statement_row_index,
    fn_build_interparty_mapping,
    fn_dataframe_to_output_payload,
    fn_export_excel_output_to_file,
    fn_debug_value_preview,
    fn_to_debug_dataframe,
    fn_sanitize_excel_sheet_name,
    fn_export_dataframes_to_excel,
    fn_is_debug_export_enabled,
    fn_export_debug_sections,
    fn_format_timing_table,
    fn_create_timing_context,
    fn_record_timing,
    fn_finalize_timing_summary,
    fn_create_double_entry_account,
    fn_create_all_accounts,
    fn_recalculate_account_rollforward,
    fn_record_journal_entry,
    fn_initialize_financial_statement,
    fn_record_financial_statement_entry,
    fn_record_financial_statement_entry_vectorized,
    fn_create_all_financial_statements,
    fn_record_integrated_entry,
    fn_resolve_signed_cashflow_amount,
    fn_flush_batch_entries,
    fn_build_flush_index_maps,
    fn_flush_matrix_entries,
    fn_flush_matrix_entries_multi,
    fn_propagate_opening_balances,
    fn_get_account_balance,
    fn_process_cashflow_line_item,
    fn_build_direct_cash_batch_entries,
    fn_build_direct_cash_matrix_entries,
    fn_prepare_direct_cash_matrix_batch,
    fn_process_direct_cash_capex_line_item_entries,
    fn_get_row_by_compatible_index,
    fn_append_financial_statement_trace_row,
    fn_build_financial_statement_trace_dataframe,
    fn_add_unique_id_to_trace_df,
    fn_trace_dataframe_to_payload,
    fn_build_presentable_balance_sheet,
    fn_build_presentable_income_statement,
    fn_build_presentable_cashflow_statement,
)

# When True, interparty transactions record both base entries and reversed
# elimination entries in the journal (net-zero impact on statements).  When
# False, interparty assets are skipped entirely — no base entries and no
# elimination entries are posted, producing zero journal/statement impact.
_ENABLE_INTERPARTY_ENTRIES = True

# When True, interparty elimination (reversal) entries are posted alongside
# the base entries (net-zero P&L / BS impact).  When False, only the base
# interparty entries are recorded — no elimination reversals are generated.
# Only meaningful when _ENABLE_INTERPARTY_ENTRIES is True.
_ENABLE_INTERPARTY_ELIMINATION = True

_LIGHTWEIGHT_INTERPARTY_ACCOUNT_NAMES = {
    "Interparty Accounts Receivable",
    "Interparty Unearned Revenue",
    "Interparty Revenue Elimination",
    "Interparty COGS Elimination",
    "Interparty Cash Elimination",
}




# ==============================================================================
# SECTIONS B & C (shared): Imported from .project_conso_utils
# ==============================================================================


# ==============================================================================
# ENTITY-SPECIFIC PROCESSING FUNCTIONS
# ==============================================================================

def fn_process_land_acquisition_entries(
    land_acquisition_df: pd.DataFrame,
    land_acquisition_cost_cash_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    cashflow_line_item: str = "Raw Land Acquisition Cost",
    reference_prefix: str = "LC-LA",
    acquisition_counterparty: Optional[pd.Series] = None,
    s_curve_df: Optional[pd.DataFrame] = None,
    revenue_df: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process land acquisition accounting with advance and payable roll-forward logic.

    Rules implemented (external / lump-sum):
    1. Before acquisition: Dr Advances for Land / Cr Cash and Cash Equivalents
    2. On acquisition: Dr Land Assets / Cr Advances for Land (if any), Cr Accounts Payable (balance)
    3. After acquisition: Dr Accounts Payable / Cr Cash and Cash Equivalents

    For interparty acquisitions (acquisition_counterparty == "LandCo") when
    s_curve_df and revenue_df are provided, capitalization follows the same
    S-curve-based progressive recognition used by the counterpart's cost of
    sales, producing a one-to-one match in timing and proportion. Cash
    payments are unchanged.

    Cashflow treatment:
    ------------------
    Only cash payments are posted to cashflow using the provided CFI line item.
    Non-cash capitalization entries are not posted to cashflow.

    This function uses print-based error control and does not raise exceptions.
    """
    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        print("fn_process_land_acquisition_entries: asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not isinstance(land_acquisition_df, pd.DataFrame):
        print("fn_process_land_acquisition_entries: land_acquisition_df is not a DataFrame")
        land_acquisition_df = pd.DataFrame()

    if not isinstance(land_acquisition_cost_cash_payment_df, pd.DataFrame):
        print("fn_process_land_acquisition_entries: land_acquisition_cost_cash_payment_df is not a DataFrame")
        land_acquisition_cost_cash_payment_df = pd.DataFrame()

    # Normalize index types once for consistent, fast row alignment.
    if not land_acquisition_df.empty:
        land_acquisition_df = land_acquisition_df.copy()
        land_acquisition_df.index = land_acquisition_df.index.map(lambda x: str(x).strip())

    if not land_acquisition_cost_cash_payment_df.empty:
        land_acquisition_cost_cash_payment_df = land_acquisition_cost_cash_payment_df.copy()
        land_acquisition_cost_cash_payment_df.index = land_acquisition_cost_cash_payment_df.index.map(lambda x: str(x).strip())

    # Normalize optional interparty DataFrames.
    _have_scurve_data = (
        isinstance(s_curve_df, pd.DataFrame) and not s_curve_df.empty
        and isinstance(revenue_df, pd.DataFrame) and not revenue_df.empty
    )
    if _have_scurve_data:
        s_curve_df = s_curve_df.copy()
        s_curve_df.index = s_curve_df.index.map(lambda x: str(x).strip())
        revenue_df = revenue_df.copy()
        revenue_df.index = revenue_df.index.map(lambda x: str(x).strip())

    if land_acquisition_df.empty and land_acquisition_cost_cash_payment_df.empty:
        print("fn_process_land_acquisition_entries: no acquisition or payment data to process")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_land_acquisition_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Serviced Land Assets",
        "Advances for Land",
        "Accounts Payable",
        "Cash and Cash Equivalents",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(
            "fn_process_land_acquisition_entries: missing required accounts: "
            f"{missing_accounts}"
        )
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        print("fn_process_land_acquisition_entries: no period columns available")
        return accounts, journal, financial_statements

    # Precompute (period_col, period_str) pairs so the inner loop is O(1) per step.
    period_map = [(pc, col_to_period.get(pc)) for pc in period_cols]

    row_index = (
        land_acquisition_df.index
        if not land_acquisition_df.empty
        else land_acquisition_cost_cash_payment_df.index
    )
    if len(row_index) == 0:
        print("fn_process_land_acquisition_entries: no asset rows available")
        return accounts, journal, financial_statements

    # -- Pre-extract all asset data into numpy matrices (one-time cost). --
    n_periods = len(period_cols)
    _str_index = row_index.map(lambda x: str(x).strip())

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        """Extract (n_assets × n_periods) float64 matrix, aligned to period_cols."""
        if df.empty:
            return np.zeros((len(_str_index), n_periods), dtype="float64")
        aligned = df.reindex(index=_str_index, columns=period_cols)
        return aligned.apply(pd.to_numeric, errors="coerce").fillna(0.0).values

    _acq_matrix = _extract_matrix(land_acquisition_df)
    _pay_matrix = _extract_matrix(land_acquisition_cost_cash_payment_df)
    _scurve_matrix = _extract_matrix(s_curve_df) if _have_scurve_data else None
    _revenue_matrix = _extract_matrix(revenue_df) if _have_scurve_data else None

    # Accumulate all journal entries, then flush once (single rollforward per account).
    _batch_entries: List[Dict[str, Any]] = []

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        # Track start position for interparty elimination post-processing.
        _asset_start_pos = len(_batch_entries)

        # Determine if this asset's DevCo acquisition counterparty is LandCo.
        _is_landco_acquisition = False
        if acquisition_counterparty is not None and isinstance(acquisition_counterparty, pd.Series) and not acquisition_counterparty.empty:
            try:
                _ac_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ac_loc is not None:
                    _is_landco_acquisition = str(acquisition_counterparty.iloc[_ac_loc]).strip() == "LandCo"
            except Exception:
                pass

        # When interparty entries are disabled, skip interparty assets entirely.
        if _is_landco_acquisition and not _ENABLE_INTERPARTY_ENTRIES:
            continue

        # Fast matrix row access (pre-extracted above).
        acquisition_values = _acq_matrix[asset_row_idx]
        payment_values = _pay_matrix[asset_row_idx]

        # ==============================================================
        # Interparty S-curve progressive capitalization:
        # Mirror the counterpart's cost-of-sales recognition timing.
        # Replace lump-sum acquisition_values with progressive amounts.
        # ==============================================================
        if _is_landco_acquisition and _have_scurve_data:
            _rev_vals = np.abs(_revenue_matrix[asset_row_idx])
            _sc_vals = np.abs(_scurve_matrix[asset_row_idx])
            _total_revenue = float(_rev_vals.sum())
            _sc_total = float(_sc_vals.sum())
            _total_acquisition = float(np.abs(acquisition_values).sum())

            if _total_revenue > 0.0 and _sc_total > 0.0 and _total_acquisition > 0.0:
                _sc_pct = np.cumsum(_sc_vals) / _sc_total
                _cum_absorption = np.cumsum(_rev_vals)

                _progressive = np.zeros(len(period_cols), dtype="float64")
                _prev_sc = 0.0
                _cum_recognized = 0.0

                for _pi in range(len(period_cols)):
                    _sp = float(_sc_pct[_pi])
                    if pd.isna(_sp):
                        _sp = _prev_sc
                    _sp = max(_prev_sc, max(0.0, min(1.0, _sp)))

                    _cum_target = float(_cum_absorption[_pi]) * _sp
                    _period_recog = max(0.0, _cum_target - _cum_recognized)

                    if _period_recog > 0.0:
                        _progressive[_pi] = _total_acquisition * (_period_recog / _total_revenue)

                    _cum_recognized += _period_recog
                    _prev_sc = _sp

                acquisition_values = _progressive

        advance_balance = 0.0
        payable_balance = 0.0

        for (period_col, period_str), acquisition_amount, cash_payment_amount in zip(
            period_map, acquisition_values, payment_values
        ):
            if period_str is None:
                continue

            if acquisition_amount < 0 or cash_payment_amount < 0:
                print(
                    f"Skipping negative amount for asset {asset_unique_id}, period {period_str}: "
                    f"acquisition={acquisition_amount}, cash_payment={cash_payment_amount}"
                )
                continue

            if acquisition_amount == 0.0 and cash_payment_amount == 0.0:
                continue

            if acquisition_amount > 0.0:
                advance_applied = min(advance_balance, acquisition_amount)
                payable_addition = acquisition_amount - advance_applied

                if advance_applied > 0.0:
                    _batch_entries.append({
                        "debit_account": "Serviced Land Assets",
                        "credit_account": "Advances for Land",
                        "amount": advance_applied,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Land Acquisition (advance adjustment) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-ACQ-ADV-{asset_idx}-{period_col}",
                    })
                    advance_balance -= advance_applied

                if payable_addition > 0.0:
                    _batch_entries.append({
                        "debit_account": "Serviced Land Assets",
                        "credit_account": "Accounts Payable",
                        "amount": payable_addition,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Land Acquisition (payable recognition) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-ACQ-AP-{asset_idx}-{period_col}",
                    })
                    payable_balance += payable_addition

            if cash_payment_amount > 0.0:
                payable_settlement = min(cash_payment_amount, payable_balance)

                if payable_settlement > 0.0:
                    _batch_entries.append({
                        "debit_account": "Accounts Payable",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": payable_settlement,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"Land Acquisition cash settlement - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-AP-{asset_idx}-{period_col}",
                    })
                    payable_balance -= payable_settlement
                    cash_payment_amount -= payable_settlement

                if cash_payment_amount > 0.0:
                    _batch_entries.append({
                        "debit_account": "Advances for Land",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": cash_payment_amount,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"Land Acquisition advance payment - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-ADV-{asset_idx}-{period_col}",
                    })
                    advance_balance += cash_payment_amount

        # ==============================================================
        # Interparty Elimination: Generate reversed entries for assets
        # whose DevCo acquisition counterparty is LandCo.
        # ==============================================================
        if _is_landco_acquisition and _ENABLE_INTERPARTY_ELIMINATION:
            _ie_entries = []
            for _base_entry in _batch_entries[_asset_start_pos:]:
                _ie_entries.append({
                    "debit_account": _base_entry["credit_account"] + " - Interparty Elimination",
                    "credit_account": _base_entry["debit_account"] + " - Interparty Elimination",
                    "amount": _base_entry["amount"],
                    "period": _base_entry["period"],
                    "income_statement_line_item": (
                        _base_entry["income_statement_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("income_statement_line_item")
                        else None
                    ),
                    "cashflow_line_item": (
                        _base_entry["cashflow_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("cashflow_line_item")
                        else None
                    ),
                    "description": _base_entry["description"] + " (Interparty Elimination)",
                    "reference": _base_entry["reference"] + "-IE",
                })
            _batch_entries.extend(_ie_entries)

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )
    return accounts, journal, financial_statements


def fn_build_serviced_land_acquisition_debit_basis(
    land_acquisition_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    acquisition_counterparty: Optional[pd.Series] = None,
    s_curve_df: Optional[pd.DataFrame] = None,
    revenue_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build per-asset/per-period Serviced Land Assets debit basis using the same
    acquisition-recognition timing logic as fn_process_land_acquisition_entries.

    For interparty acquisitions (counterparty == "LandCo"), debit timing follows
    progressive recognition driven by counterpart revenue and S-curve. For
    non-interparty acquisitions, debit timing follows the provided acquisition
    phasing directly.
    """
    if not isinstance(land_acquisition_df, pd.DataFrame) or land_acquisition_df.empty:
        return pd.DataFrame()

    if not col_to_period:
        return pd.DataFrame(index=land_acquisition_df.index)

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return pd.DataFrame(index=land_acquisition_df.index)

    # Preserve original row labels for output so downstream alignments do not
    # lose values on int<->str index mismatches.
    _output_index = land_acquisition_df.index.copy()

    land_acquisition_df = land_acquisition_df.copy()
    land_acquisition_df.index = land_acquisition_df.index.map(lambda x: str(x).strip())

    _have_scurve_data = (
        isinstance(s_curve_df, pd.DataFrame)
        and not s_curve_df.empty
        and isinstance(revenue_df, pd.DataFrame)
        and not revenue_df.empty
    )
    if _have_scurve_data:
        s_curve_df = s_curve_df.copy()
        s_curve_df.index = s_curve_df.index.map(lambda x: str(x).strip())
        revenue_df = revenue_df.copy()
        revenue_df.index = revenue_df.index.map(lambda x: str(x).strip())

    row_index = land_acquisition_df.index
    _str_index = row_index.map(lambda x: str(x).strip())

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(_str_index), len(period_cols)), dtype="float64")
        aligned = df.reindex(index=_str_index, columns=period_cols)
        return aligned.apply(pd.to_numeric, errors="coerce").fillna(0.0).values

    _acq_matrix = _extract_matrix(land_acquisition_df)
    _scurve_matrix = _extract_matrix(s_curve_df) if _have_scurve_data else None
    _revenue_matrix = _extract_matrix(revenue_df) if _have_scurve_data else None

    _basis_matrix = np.zeros((len(_str_index), len(period_cols)), dtype="float64")

    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        return pd.DataFrame(_basis_matrix, index=_output_index, columns=period_cols)

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        _is_landco_acquisition = False
        if acquisition_counterparty is not None and isinstance(acquisition_counterparty, pd.Series) and not acquisition_counterparty.empty:
            try:
                _ac_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ac_loc is not None:
                    _is_landco_acquisition = str(acquisition_counterparty.iloc[_ac_loc]).strip() == "LandCo"
            except Exception:
                pass

        # Keep basis consistent with posting behavior when interparty entries are disabled.
        if _is_landco_acquisition and not _ENABLE_INTERPARTY_ENTRIES:
            continue

        acquisition_values = _acq_matrix[asset_row_idx].copy()

        if _is_landco_acquisition and _have_scurve_data:
            _rev_vals = np.abs(_revenue_matrix[asset_row_idx])
            _sc_vals = np.abs(_scurve_matrix[asset_row_idx])
            _total_revenue = float(_rev_vals.sum())
            _sc_total = float(_sc_vals.sum())
            _total_acquisition = float(np.abs(acquisition_values).sum())

            if _total_revenue > 0.0 and _sc_total > 0.0 and _total_acquisition > 0.0:
                _sc_pct = np.cumsum(_sc_vals) / _sc_total
                _cum_absorption = np.cumsum(_rev_vals)

                _progressive = np.zeros(len(period_cols), dtype="float64")
                _prev_sc = 0.0
                _cum_recognized = 0.0

                for _pi in range(len(period_cols)):
                    _sp = float(_sc_pct[_pi])
                    if pd.isna(_sp):
                        _sp = _prev_sc
                    _sp = max(_prev_sc, max(0.0, min(1.0, _sp)))

                    _cum_target = float(_cum_absorption[_pi]) * _sp
                    _period_recog = max(0.0, _cum_target - _cum_recognized)

                    if _period_recog > 0.0:
                        _progressive[_pi] = _total_acquisition * (_period_recog / _total_revenue)

                    _cum_recognized += _period_recog
                    _prev_sc = _sp

                acquisition_values = _progressive

        # Debit basis only captures positive acquisition recognition amounts.
        _basis_matrix[asset_row_idx] = np.where(acquisition_values > 0.0, acquisition_values, 0.0)

    return pd.DataFrame(_basis_matrix, index=_output_index, columns=period_cols)


def fn_process_construction_entries(
    construction_progress_df: pd.DataFrame,
    construction_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    construction_label: str,
    cashflow_line_item: str = "Vertical Construction Cost",
    reference_prefix: str = "DC-VC",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process construction accounting using progress S-curve and cash payments.

    Rules implemented:
    1. On progress (S-curve): Dr CWIP - Serviced Land / Cr Accounts Payable
    2. On payment:
       - If payable exists: Dr Accounts Payable / Cr Cash and Cash Equivalents
       - If no payable: Dr Advance to Contractor / Cr Cash and Cash Equivalents
    3. Adjustment when progress exists and advance exists:
       Dr Accounts Payable / Cr Advance to Contractor

    Outcome rule:
    - Payment > Progress -> advance balance
    - Progress > Payment -> payable balance
    """
    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        print(f"fn_process_construction_entries ({construction_label}): asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not isinstance(construction_progress_df, pd.DataFrame):
        print(f"fn_process_construction_entries ({construction_label}): construction_progress_df is not a DataFrame")
        construction_progress_df = pd.DataFrame()

    if not isinstance(construction_payment_df, pd.DataFrame):
        print(f"fn_process_construction_entries ({construction_label}): construction_payment_df is not a DataFrame")
        construction_payment_df = pd.DataFrame()

    # Normalize index types once so row alignment is consistent and fast.
    if not construction_progress_df.empty:
        construction_progress_df = construction_progress_df.copy()
        construction_progress_df.index = construction_progress_df.index.map(lambda x: str(x).strip())

    if not construction_payment_df.empty:
        construction_payment_df = construction_payment_df.copy()
        construction_payment_df.index = construction_payment_df.index.map(lambda x: str(x).strip())

    if construction_progress_df.empty and construction_payment_df.empty:
        print(f"fn_process_construction_entries ({construction_label}): no progress or payment data to process")
        return accounts, journal, financial_statements

    if not col_to_period:
        print(f"fn_process_construction_entries ({construction_label}): col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "CWIP - Developed Units",
        "Accounts Payable",
        "Advance to Contractor",
        "Cash and Cash Equivalents",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(
            f"fn_process_construction_entries ({construction_label}): missing required accounts: "
            f"{missing_accounts}"
        )
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        print(f"fn_process_construction_entries ({construction_label}): no period columns available")
        return accounts, journal, financial_statements

    period_map = [(period_col, col_to_period.get(period_col)) for period_col in period_cols]

    row_index = (
        construction_progress_df.index
        if not construction_progress_df.empty
        else construction_payment_df.index
    )
    if len(row_index) == 0:
        print(f"fn_process_construction_entries ({construction_label}): no asset rows available")
        return accounts, journal, financial_statements

    # ------------------------------------------------------------------
    # Pre-extract all source DataFrames as numpy matrices (n_assets × n_periods).
    # ------------------------------------------------------------------
    _str_index = [str(idx).strip() for idx in row_index]

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(_str_index), len(period_cols)), dtype="float64")
        return (
            df.reindex(index=_str_index, columns=period_cols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .values
        )

    _progress_matrix = _extract_matrix(construction_progress_df)
    _payment_matrix = _extract_matrix(construction_payment_df)

    # Accumulate all journal entries, then flush once (single rollforward per account).
    _batch_entries: List[Dict[str, Any]] = []

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        progress_values = _progress_matrix[asset_row_idx]
        payment_values = _payment_matrix[asset_row_idx]

        payable_balance = 0.0
        advance_balance = 0.0

        for (period_col, period_str), progress_amount, payment_amount in zip(
            period_map,
            progress_values,
            payment_values,
        ):
            if period_str is None:
                continue

            # DevCo CFI outflows are often provided as negative values.
            # Normalize to absolute magnitudes so accounting entries can post.
            if progress_amount < 0:
                progress_amount = abs(progress_amount)

            if payment_amount < 0:
                payment_amount = abs(payment_amount)

            progress_amount = round(progress_amount, 2)
            payment_amount = round(payment_amount, 2)

            if progress_amount == 0.0 and payment_amount == 0.0:
                continue

            if progress_amount > 0.0:
                _batch_entries.append({
                    "debit_account": "CWIP - Developed Units",
                    "credit_account": "Accounts Payable",
                    "amount": progress_amount,
                    "period": period_str,
                    "income_statement_line_item": None,
                    "cashflow_line_item": None,
                    "description": f"{construction_label} Progress - Asset {asset_idx}",
                    "reference": f"{reference_prefix}-PROG-{asset_idx}-{period_col}",
                })
                payable_balance = round(payable_balance + progress_amount, 2)
                
                if advance_balance > 0.0:
                    adjustment_amount = round(min(advance_balance, payable_balance), 2)
                    if adjustment_amount > 0.0:
                        _batch_entries.append({
                            "debit_account": "Accounts Payable",
                            "credit_account": "Advance to Contractor",
                            "amount": adjustment_amount,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"{construction_label} Advance Adjustment - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-ADJ-{asset_idx}-{period_col}",
                        })
                        payable_balance = round(payable_balance - adjustment_amount, 2)
                        advance_balance = round(advance_balance - adjustment_amount, 2)

            if payment_amount > 0.0:
                payable_settlement = round(min(payment_amount, payable_balance), 2)

                if payable_settlement > 0.0:
                    _batch_entries.append({
                        "debit_account": "Accounts Payable",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": payable_settlement,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"{construction_label} Payable Settlement - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-AP-{asset_idx}-{period_col}",
                    })
                    payable_balance = round(payable_balance - payable_settlement, 2)
                    payment_amount = round(payment_amount - payable_settlement, 2)

                if payment_amount > 0.0:
                    _batch_entries.append({
                        "debit_account": "Advance to Contractor",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": payment_amount,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"{construction_label} Advance Payment - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-ADV-{asset_idx}-{period_col}",
                    })
                    advance_balance = round(advance_balance + payment_amount, 2)
            
    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )
    return accounts, journal, financial_statements


def fn_process_vertical_construction_entries(
    vertical_construction_progress_df: pd.DataFrame,
    vertical_construction_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    cashflow_line_item: str = "Vertical Construction Cost",
    reference_prefix: str = "DC-VC",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    return fn_process_construction_entries(
        construction_progress_df=vertical_construction_progress_df,
        construction_payment_df=vertical_construction_payment_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        construction_label="Vertical Construction",
        cashflow_line_item=cashflow_line_item,
        reference_prefix=reference_prefix,
    )


def fn_process_developed_unit_sales_entries(
    revenue_df: pd.DataFrame,
    s_curve_df: pd.DataFrame,
    collection_non_escrow_df: pd.DataFrame,
    collection_escrow_df: pd.DataFrame,
    escrow_release_df: pd.DataFrame,
    escrow_applicability: pd.Series,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    reference_prefix: str = "DC-SALES",
    exit_counterparty: Optional[pd.Series] = None,
    cost_incurred_df: Optional[pd.DataFrame] = None,
    cwip_cost_incurred_df: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process DevCo developed unit sales accounting entries across all financial statements.

    Implements the following entry logic per asset per period:

    1. Revenue Recognition (proportional to infrastructure S-curve):
       Dr Accounts Receivable / Cr Developed Unit Sales Revenue

    2. Cost Recognition (proportional to same S-curve):
       (a) Dr Inventory - Developed Units / Cr Serviced Land Assets + Cr CWIP - Developed Units
       (b) Dr Cost of Developed Unit Sales / Cr Inventory - Developed Units

    3. Collection - ESCROW OFF:
       Dr Cash / Cr Accounts Receivable (up to AR balance)
       Excess ? Dr Cash / Cr Unearned Revenue
       Cashflow line: "On-plan Sales Collection"

    4. Collection - ESCROW ON:
       Dr Escrow Restricted Cash / Cr Accounts Receivable (up to AR balance)
       Excess ? Dr Escrow Restricted Cash / Cr Unearned Revenue

    5. Escrow Release:
       Dr Cash / Cr Escrow Restricted Cash
       Cashflow line: "Off-plan Sales Collection"

    6. Adjustment each period:
       If cumulative collection > cumulative revenue ? excess in Unearned Revenue
       If cumulative revenue > cumulative collection ? excess in Receivable
       (Handled implicitly by the entry sequence above.)
    """
    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        print("fn_process_developed_unit_sales_entries: asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_developed_unit_sales_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Cash and Cash Equivalents",
        "Accounts Receivable",
        "Escrow Restricted Cash",
        "Unearned Revenue",
        "Serviced Land Assets",
        "CWIP - Developed Units",
        "Developed Unit Sales Revenue",
        "Cost of Developed Unit Sales",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(f"fn_process_developed_unit_sales_entries: missing required accounts: {missing_accounts}")
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return accounts, journal, financial_statements

    # Normalize index types for consistent lookup.
    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            df.index = df.index.map(lambda x: str(x).strip())
        return df

    revenue_df = _normalize_df(revenue_df) if isinstance(revenue_df, pd.DataFrame) else pd.DataFrame()
    s_curve_df = _normalize_df(s_curve_df) if isinstance(s_curve_df, pd.DataFrame) else pd.DataFrame()
    collection_non_escrow_df = _normalize_df(collection_non_escrow_df) if isinstance(collection_non_escrow_df, pd.DataFrame) else pd.DataFrame()
    collection_escrow_df = _normalize_df(collection_escrow_df) if isinstance(collection_escrow_df, pd.DataFrame) else pd.DataFrame()
    escrow_release_df = _normalize_df(escrow_release_df) if isinstance(escrow_release_df, pd.DataFrame) else pd.DataFrame()
    cost_incurred_df = _normalize_df(cost_incurred_df) if isinstance(cost_incurred_df, pd.DataFrame) else pd.DataFrame()
    cwip_cost_incurred_df = _normalize_df(cwip_cost_incurred_df) if isinstance(cwip_cost_incurred_df, pd.DataFrame) else pd.DataFrame()

    # Determine the row index from the first non-empty source.
    row_index = None
    for candidate_df in [revenue_df, s_curve_df, collection_non_escrow_df, collection_escrow_df]:
        if isinstance(candidate_df, pd.DataFrame) and not candidate_df.empty:
            row_index = candidate_df.index
            break
    if row_index is None or len(row_index) == 0:
        print("fn_process_land_sales_entries: no asset rows found in any source DataFrame")
        return accounts, journal, financial_statements

    period_map = [(pc, col_to_period.get(pc)) for pc in period_cols]
    _batch_entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-extract all source DataFrames as numpy matrices (n_assets × n_periods).
    # ------------------------------------------------------------------
    _str_index = [str(idx).strip() for idx in row_index]

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(_str_index), len(period_cols)), dtype="float64")
        return (
            df.reindex(index=_str_index, columns=period_cols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .values
        )

    _revenue_matrix = _extract_matrix(revenue_df)
    _s_curve_matrix = _extract_matrix(s_curve_df)
    _coll_non_escrow_matrix = _extract_matrix(collection_non_escrow_df)
    _coll_escrow_matrix = _extract_matrix(collection_escrow_df)
    _escrow_release_matrix = _extract_matrix(escrow_release_df)
    _cost_incurred_matrix = np.abs(_extract_matrix(cost_incurred_df)) if not cost_incurred_df.empty else np.zeros((len(_str_index), len(period_cols)), dtype="float64")

    # Pre-compute total revenue across all assets (used for cost allocation).
    _total_all_assets_revenue = float(np.abs(_revenue_matrix).sum())
    _total_all_assets_cost = float(_cost_incurred_matrix.sum())

    # ------------------------------------------------------------------
    # CWIP cost matrix (used per-asset for SLA/CWIP credit split ratio).
    # ------------------------------------------------------------------
    _cwip_cost_matrix = np.abs(_extract_matrix(cwip_cost_incurred_df)) if isinstance(cwip_cost_incurred_df, pd.DataFrame) and not cwip_cost_incurred_df.empty else np.zeros((len(_str_index), len(period_cols)), dtype="float64")

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        # Track start position for interparty elimination post-processing.
        _asset_start_pos = len(_batch_entries)

        # Determine if this asset's DevCo exit counterparty is AssetCo.
        _is_assetco_exit = False
        if exit_counterparty is not None and isinstance(exit_counterparty, pd.Series) and not exit_counterparty.empty:
            try:
                _ec_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ec_loc is not None:
                    _is_assetco_exit = str(exit_counterparty.iloc[_ec_loc]).strip() == "AssetCo"
            except Exception:
                pass

        # When interparty entries are disabled, skip interparty assets entirely.
        if _is_assetco_exit and not _ENABLE_INTERPARTY_ENTRIES:
            continue

        # ------------------------------------------------------------------
        # Determine escrow applicability for this asset
        # ------------------------------------------------------------------
        is_escrow = False
        if isinstance(escrow_applicability, pd.Series) and not escrow_applicability.empty:
            try:
                raw_escrow_val = escrow_applicability.iloc[row_index.get_loc(asset_idx_key)] if asset_idx_key in row_index else None
            except Exception:
                raw_escrow_val = None
            if raw_escrow_val is not None and str(raw_escrow_val).strip().lower() in ("yes", "true", "1"):
                is_escrow = True

        # ------------------------------------------------------------------
        # Extract per-asset row data from pre-computed matrices
        # ------------------------------------------------------------------
        revenue_values = _revenue_matrix[asset_row_idx]
        s_curve_amount_values = np.abs(_s_curve_matrix[asset_row_idx])
        collection_values = _coll_escrow_matrix[asset_row_idx] if is_escrow else _coll_non_escrow_matrix[asset_row_idx]
        escrow_release_values = _escrow_release_matrix[asset_row_idx] if is_escrow else np.zeros(len(period_cols), dtype="float64")

        # DevCo support workings provides S-curve as amount phasing (not %).
        # Convert to cumulative percentage profile for recognition logic.
        
        s_curve_total_amount = float(s_curve_amount_values.sum())
        if s_curve_total_amount > 0.0:
            s_curve_pct_values = np.cumsum(s_curve_amount_values) / s_curve_total_amount
        else:
            print(
                f"fn_process_developed_unit_sales_entries: zero total S-curve amount for asset {asset_idx}; "
                "revenue recognition will remain zero for this asset"
            )
            s_curve_pct_values = np.zeros(len(period_cols), dtype="float64")

        # Normalize to absolute values (sources may be negative for outflows).
        collection_values = np.abs(collection_values)
        escrow_release_values = np.abs(escrow_release_values)

        # ------------------------------------------------------------------
        # Compute total revenue for this asset (sum across all periods)
        # ------------------------------------------------------------------
        revenue_values_abs = np.abs(revenue_values)
        total_revenue = float(revenue_values_abs.sum())
        if total_revenue == 0.0:
            continue

        # Revenue recognition base uses cumulative sales absorption amounts.
        cumulative_sales_absorption_values = np.cumsum(revenue_values_abs)

        # ------------------------------------------------------------------
        # Compute per-period cost incurred for this asset from source data.
        # cost_incurred_df provides the total cost (land + CWIP) per asset
        # per period directly, avoiding order-of-execution issues with
        # reading account debits.
        # ------------------------------------------------------------------
        cost_incurred_values = _cost_incurred_matrix[asset_row_idx]
        total_asset_cost = float(cost_incurred_values.sum())
        _cum_cost_incurred = np.cumsum(cost_incurred_values)

        # Per-asset credit split ratio between Serviced Land Assets and CWIP.
        _asset_cwip_cost = min(
            total_asset_cost,
            max(0.0, float(_cwip_cost_matrix[asset_row_idx].sum())),
        )
        _asset_sla_cost = max(0.0, total_asset_cost - _asset_cwip_cost)
        if total_asset_cost > 0.0:
            _sla_ratio = _asset_sla_cost / total_asset_cost
            _cwip_ratio = _asset_cwip_cost / total_asset_cost
        else:
            _sla_ratio = 0.0
            _cwip_ratio = 0.0

        # ------------------------------------------------------------------
        # Track cumulative amounts per asset for adjustment logic
        # ------------------------------------------------------------------
        cumulative_revenue_recognized = 0.0
        cumulative_cost_recognized = 0.0
        cumulative_collection = 0.0
        prev_s_curve = 0.0
        ar_balance = 0.0           # running Accounts Receivable balance for this asset
        unearned_balance = 0.0     # running Unearned Revenue balance for this asset

        for period_idx, ((period_col, period_str), s_curve_pct, coll_amt, esc_rel_amt) in enumerate(zip(
            period_map,
            s_curve_pct_values,
            collection_values,
            escrow_release_values,
        )):
            if period_str is None:
                continue

            # ==============================================================
            # 1. Revenue Recognition (based on S-curve increment)
            # ==============================================================
            # S-curve represents cumulative % completion.
            # Incremental revenue = total_revenue * (current_s_curve - prev_s_curve)
            try:
                s_curve_pct_numeric = float(s_curve_pct)
            except (TypeError, ValueError):
                s_curve_pct_numeric = prev_s_curve

            if pd.isna(s_curve_pct_numeric):
                s_curve_pct_numeric = prev_s_curve

            # Prevent regressions in cumulative profile and clamp to [0, 1].
            s_curve_pct_clean = max(prev_s_curve, max(0.0, min(1.0, s_curve_pct_numeric)))
            incremental_s_curve = s_curve_pct_clean - prev_s_curve
            prev_s_curve = s_curve_pct_clean

            # Revenue recognition formula:
            # Current period recognized revenue =
            # (Cumulative Sales Absorption to date * Cumulative S-curve %) -
            # cumulative revenue already recognized in prior periods.
            cumulative_sales_absorption_to_date = float(cumulative_sales_absorption_values[period_idx])
            current_revenue_recognition_target = cumulative_sales_absorption_to_date * s_curve_pct_clean
            period_revenue = max(0.0, current_revenue_recognition_target - cumulative_revenue_recognized)

            if period_revenue > 0.0:
                # When Unearned Revenue balance exists (collections received
                # before revenue was recognized), first reverse Unearned
                # Revenue, then create AR for any remainder.
                unearned_reversal = min(period_revenue, unearned_balance)
                ar_portion = period_revenue - unearned_reversal

                if unearned_reversal > 0.0:
                    # Dr Unearned Revenue / Cr Land Sales Revenue
                    _batch_entries.append({
                        "debit_account": "Unearned Revenue",
                        "credit_account": "Developed Unit Sales Revenue",
                        "amount": unearned_reversal,
                        "period": period_str,
                        "income_statement_line_item": "Asset Sales Revenue",
                        "cashflow_line_item": None,
                        "description": f"Revenue Recognition (Unearned Reversal) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-REV-UNR-{asset_idx}-{period_col}",
                    })
                    unearned_balance -= unearned_reversal

                if ar_portion > 0.0:
                    # Dr Accounts Receivable / Cr Land Sales Revenue
                    _batch_entries.append({
                        "debit_account": "Accounts Receivable",
                        "credit_account": "Developed Unit Sales Revenue",
                        "amount": ar_portion,
                        "period": period_str,
                        "income_statement_line_item": "Asset Sales Revenue",
                        "cashflow_line_item": None,
                        "description": f"Revenue Recognition (S-Curve) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-REV-{asset_idx}-{period_col}",
                    })
                    ar_balance += ar_portion

                cumulative_revenue_recognized += period_revenue

            # ==============================================================
            # 2. Cost Recognition (revenue proportion)
            # ==============================================================
            # Formula: COGS[t] = AssetCost * (Revenue[t] / TotalRevenue)
            # AssetCost = per-asset total from cost_incurred_df.
            if period_revenue > 0.0 and total_revenue > 0.0 and total_asset_cost > 0.0:
                period_cost = total_asset_cost * (period_revenue / total_revenue)
            else:
                period_cost = 0.0

            if period_cost > 0.0:
                # Dr Cost of Developed Unit Sales / Cr Serviced Land Assets + Cr CWIP - Developed Units
                # Split the credit proportionally between Serviced Land Assets and CWIP.
                serviced_land_assets_credit = period_cost * _sla_ratio
                cwip_credit = period_cost * _cwip_ratio

                if serviced_land_assets_credit > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "Serviced Land Assets",
                        "amount": serviced_land_assets_credit,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Cost of Developed Unit Sales (Land) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-LA-{asset_idx}-{period_col}",
                    })

                if cwip_credit > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "CWIP - Developed Units",
                        "amount": cwip_credit,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Cost of Developed Unit Sales (CWIP) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-CWIP-{asset_idx}-{period_col}",
                    })

                cumulative_cost_recognized += period_cost

            # ==============================================================
            # 3/4/5. Collection Entries (with adjustment logic)
            # ==============================================================
            if coll_amt > 0.0:
                cumulative_collection += coll_amt

                if not is_escrow:
                    # ---------------------------------------------------
                    # ESCROW OFF: Dr Cash / Cr AR or Unearned Revenue
                    # ---------------------------------------------------
                    # Settle AR first (up to its balance), excess goes to Unearned Revenue.
                    ar_settlement = min(coll_amt, ar_balance)
                    unearned_portion = coll_amt - ar_settlement

                    if ar_settlement > 0.0:
                        _batch_entries.append({
                            "debit_account": "Cash and Cash Equivalents",
                            "credit_account": "Accounts Receivable",
                            "amount": ar_settlement,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": "Asset Sales through Collection (Post-Dev)",
                            "description": f"Collection (Non-Escrow) AR Settlement - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-COLL-AR-{asset_idx}-{period_col}",
                        })
                        ar_balance -= ar_settlement

                    if unearned_portion > 0.0:
                        _batch_entries.append({
                            "debit_account": "Cash and Cash Equivalents",
                            "credit_account": "Unearned Revenue",
                            "amount": unearned_portion,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": "Asset Sales through Collection (Post-Dev)",
                            "description": f"Collection (Non-Escrow) Unearned Revenue - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-COLL-UNR-{asset_idx}-{period_col}",
                        })
                        unearned_balance += unearned_portion

                else:
                    # ---------------------------------------------------
                    # ESCROW ON: Dr Escrow Restricted Cash / Cr AR or Unearned Revenue
                    # ---------------------------------------------------
                    ar_settlement = min(coll_amt, ar_balance)
                    unearned_portion = coll_amt - ar_settlement

                    if ar_settlement > 0.0:
                        _batch_entries.append({
                            "debit_account": "Escrow Restricted Cash",
                            "credit_account": "Accounts Receivable",
                            "amount": ar_settlement,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"Escrow Collection AR Settlement - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-ESC-AR-{asset_idx}-{period_col}",
                        })
                        ar_balance -= ar_settlement

                    if unearned_portion > 0.0:
                        _batch_entries.append({
                            "debit_account": "Escrow Restricted Cash",
                            "credit_account": "Unearned Revenue",
                            "amount": unearned_portion,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"Escrow Collection Unearned Revenue - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-ESC-UNR-{asset_idx}-{period_col}",
                        })
                        unearned_balance += unearned_portion

            # ==============================================================
            # 6. Escrow Release: Dr Cash / Cr Escrow Restricted Cash
            # ==============================================================
            if is_escrow and esc_rel_amt > 0.0:
                _batch_entries.append({
                    "debit_account": "Cash and Cash Equivalents",
                    "credit_account": "Escrow Restricted Cash",
                    "amount": esc_rel_amt,
                    "period": period_str,
                    "income_statement_line_item": None,
                    "cashflow_line_item": "Asset Sales through Escrow",
                    "description": f"Escrow Release - Asset {asset_idx}",
                    "reference": f"{reference_prefix}-ESCREL-{asset_idx}-{period_col}",
                })

            # ==============================================================
            # 7. Period-End: Balance tracking is maintained via ar_balance
            #    and unearned_balance, updated in steps 1 and 3/4/5 above.
            # ==============================================================

        # ==============================================================
        # Interparty Elimination: Generate reversed entries for assets
        # whose DevCo exit counterparty is AssetCo.
        # ==============================================================
        if _is_assetco_exit and _ENABLE_INTERPARTY_ELIMINATION:
            _ie_entries = []
            for _base_entry in _batch_entries[_asset_start_pos:]:
                _ie_entries.append({
                    "debit_account": _base_entry["credit_account"] + " - Interparty Elimination",
                    "credit_account": _base_entry["debit_account"] + " - Interparty Elimination",
                    "amount": _base_entry["amount"],
                    "period": _base_entry["period"],
                    "income_statement_line_item": (
                        _base_entry["income_statement_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("income_statement_line_item")
                        else None
                    ),
                    "cashflow_line_item": (
                        _base_entry["cashflow_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("cashflow_line_item")
                        else None
                    ),
                    "description": _base_entry["description"] + " (Interparty Elimination)",
                    "reference": _base_entry["reference"] + "-IE",
                })
            _batch_entries.extend(_ie_entries)

        # ==============================================================
        # Unrealized Gains: For interparty sales (DevCo → AssetCo),
        # record the profit (Revenue − COGS) in a tracking account.
        # Dr Unrealized Gains on Interparty Sales / Cr Unrealized Gains Offset
        # ==============================================================
        if _is_assetco_exit:
            _ug_revenue = 0.0
            _ug_cogs = 0.0
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = _be.get("income_statement_line_item", "")
                if _is_item == "Asset Sales Revenue":
                    _ug_revenue += float(_be.get("amount", 0.0))
                elif _is_item == "Cost of Asset Sales":
                    _ug_cogs += float(_be.get("amount", 0.0))
            _ug_profit = round(_ug_revenue - _ug_cogs, 2)
            if abs(_ug_profit) > 0.01:
                _ug_period = _batch_entries[-1]["period"] if _batch_entries[_asset_start_pos:] else None
                if _ug_period:
                    _batch_entries.append({
                        "debit_account": "Unrealized Gains on Interparty Sales",
                        "credit_account": "Unrealized Gains Offset",
                        "amount": abs(_ug_profit),
                        "period": _ug_period,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Unrealized Gains on Interparty Sale - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-UG-{asset_idx}",
                    })

        # ==============================================================
        # Interparty IS/CF Elimination Tracking: Record periodical
        # interparty revenue, COGS, and cash collection for
        # consolidated IS and CF elimination.
        # ==============================================================
        if _is_assetco_exit:
            _elim_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = (_be.get("income_statement_line_item") or "")
                _cf_item = _be.get("cashflow_line_item")
                _amt = float(_be.get("amount", 0.0))
                _per = _be.get("period")
                if abs(_amt) < 0.01:
                    continue
                if _is_item == "Asset Sales Revenue":
                    _elim_entries.append({
                        "debit_account": "Interparty Revenue Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Revenue Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPRE-{asset_idx}-{_per}",
                    })
                if _is_item == "Cost of Asset Sales":
                    _elim_entries.append({
                        "debit_account": "Interparty COGS Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP COGS Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPCE-{asset_idx}-{_per}",
                    })
                if _cf_item and _be.get("debit_account") == "Cash and Cash Equivalents":
                    _elim_entries.append({
                        "debit_account": "Interparty Cash Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Cash Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPXE-{asset_idx}-{_per}",
                    })
            _batch_entries.extend(_elim_entries)

        # ==============================================================
        # Interparty COGS Tracking (LandCo → DevCo): The serviced land
        # portion of DevCo's COGS originates from the interparty land
        # acquisition from LandCo.  Track it in the same elimination
        # account so the consolidated IS "Add: Interparty Cost of Sales"
        # includes DevCo's serviced land cost component.
        # Skip when asset is sold to AssetCo — in that case the full
        # COGS (including the serviced land portion) is already tracked
        # by the _is_assetco_exit block above.
        # ==============================================================
        if not _is_assetco_exit:
            _sla_cogs_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                if _be.get("credit_account") == "Serviced Land Assets" and _be.get("income_statement_line_item") == "Cost of Asset Sales":
                    _sla_amt = float(_be.get("amount", 0.0))
                    if abs(_sla_amt) < 0.01:
                        continue
                    _sla_cogs_entries.append({
                        "debit_account": "Interparty COGS Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _sla_amt,
                        "period": _be.get("period"),
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP COGS Elim (Serviced Land from LandCo) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPCE-SLA-{asset_idx}-{_be.get('period')}",
                    })
            _batch_entries.extend(_sla_cogs_entries)

    if not _batch_entries:
        print("fn_process_developed_unit_sales_entries: no entries to post")
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )

    return accounts, journal, financial_statements


# ------------------------------------------------------------------------------
# C.4a-ii Forward Sales Entries
# ------------------------------------------------------------------------------

def fn_process_forward_sales_entries(
    forward_sales_cash_df: pd.DataFrame,
    total_dev_cost_df: pd.DataFrame,
    land_acquisition_cost_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    reference_prefix: str = "DC-FSALES",
    exit_counterparty: Optional[pd.Series] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process Forward Sales accounting entries.

    Forward Sales: Cash is received as a lump sum at asset handover.
    Revenue is recognized immediately and the *entire* cost of sales is
    recorded in the same period.

    Entry logic per asset per period (when Forward Sales Cash > 0):

    1. Revenue Recognition:
       Dr Cash and Cash Equivalents / Cr Developed Unit Sales Revenue

    2. Cost Reclassification (entire accumulated cost):
       Dr Inventory - Developed Units / Cr Serviced Land Assets   (land portion)
       Dr Inventory - Developed Units / Cr CWIP - Developed Units (dev cost portion)

    3. Cost of Sales (entire cost):
       Dr Cost of Developed Unit Sales / Cr Inventory - Developed Units
    """
    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        print("fn_process_forward_sales_entries: asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_forward_sales_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Cash and Cash Equivalents",
        "Serviced Land Assets",
        "CWIP - Developed Units",
        "Developed Unit Sales Revenue",
        "Cost of Developed Unit Sales",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(f"fn_process_forward_sales_entries: missing required accounts: {missing_accounts}")
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return accounts, journal, financial_statements

    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            df.index = df.index.map(lambda x: str(x).strip())
        return df

    forward_sales_cash_df = _normalize_df(forward_sales_cash_df) if isinstance(forward_sales_cash_df, pd.DataFrame) else pd.DataFrame()
    total_dev_cost_df = _normalize_df(total_dev_cost_df) if isinstance(total_dev_cost_df, pd.DataFrame) else pd.DataFrame()
    land_acquisition_cost_df = _normalize_df(land_acquisition_cost_df) if isinstance(land_acquisition_cost_df, pd.DataFrame) else pd.DataFrame()

    if forward_sales_cash_df.empty:
        return accounts, journal, financial_statements

    row_index = forward_sales_cash_df.index
    period_map = {pc: col_to_period.get(pc) for pc in period_cols}
    _batch_entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-extract all source DataFrames as numpy matrices (n_assets × n_periods).
    # ------------------------------------------------------------------
    _str_index = [str(idx).strip() for idx in row_index]

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(_str_index), len(period_cols)), dtype="float64")
        return (
            df.reindex(index=_str_index, columns=period_cols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .values
        )

    _cash_matrix = np.abs(_extract_matrix(forward_sales_cash_df))
    _dev_cost_matrix = np.abs(_extract_matrix(total_dev_cost_df))
    _land_cost_matrix = np.abs(_extract_matrix(land_acquisition_cost_df))

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        # Track start position for interparty elimination post-processing.
        _asset_start_pos = len(_batch_entries)

        # Determine if this asset's DevCo exit counterparty is AssetCo.
        _is_assetco_exit = False
        if exit_counterparty is not None and isinstance(exit_counterparty, pd.Series) and not exit_counterparty.empty:
            try:
                _ec_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ec_loc is not None:
                    _is_assetco_exit = str(exit_counterparty.iloc[_ec_loc]).strip() == "AssetCo"
            except Exception:
                pass

        # When interparty entries are disabled, skip interparty assets entirely.
        if _is_assetco_exit and not _ENABLE_INTERPARTY_ENTRIES:
            continue

        cash_values = _cash_matrix[asset_row_idx]
        dev_cost_values = _dev_cost_matrix[asset_row_idx]
        land_cost_values = _land_cost_matrix[asset_row_idx]

        # Per-asset total costs (sum across all periods).
        total_dev_cost = float(dev_cost_values.sum())
        total_land_cost = float(land_cost_values.sum())
        total_cost = total_dev_cost + total_land_cost

        # Total revenue for this asset (sum of all cash receipts).
        total_revenue_fs = float(np.abs(cash_values).sum())

        for period_idx, period_col in enumerate(period_cols):
            period_str = period_map.get(period_col)
            if period_str is None:
                continue

            cash_amt = float(cash_values[period_idx])
            if cash_amt <= 0.0:
                continue

            # 1. Revenue: Dr Cash / Cr Developed Unit Sales Revenue
            _batch_entries.append({
                "debit_account": "Cash and Cash Equivalents",
                "credit_account": "Developed Unit Sales Revenue",
                "amount": cash_amt,
                "period": period_str,
                "income_statement_line_item": "Asset Sales Revenue",
                "cashflow_line_item": "Forward Sales",
                "description": f"Forward Sales Revenue - Asset {asset_idx}",
                "reference": f"{reference_prefix}-REV-{asset_idx}-{period_col}",
            })

            # 2 & 3. Cost of sales proportional to revenue.
            if total_cost > 0.0 and total_revenue_fs > 0.0:
                period_cost = total_cost * (cash_amt / total_revenue_fs)

                # Split between land and development cost proportionally.
                land_portion = period_cost * (total_land_cost / total_cost) if total_cost > 0.0 else 0.0
                dev_portion = period_cost * (total_dev_cost / total_cost) if total_cost > 0.0 else 0.0

                # Dr Cost of Developed Unit Sales / Cr Serviced Land Assets
                if land_portion > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "Serviced Land Assets",
                        "amount": land_portion,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Forward Sales Cost of Sales (Land) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-LA-{asset_idx}-{period_col}",
                    })

                # Dr Cost of Developed Unit Sales / Cr CWIP - Developed Units
                if dev_portion > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "CWIP - Developed Units",
                        "amount": dev_portion,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Forward Sales Cost of Sales (CWIP) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-CWIP-{asset_idx}-{period_col}",
                    })

        # ==============================================================
        # Interparty Elimination: Generate reversed entries for assets
        # whose DevCo exit counterparty is AssetCo.
        # ==============================================================
        if _is_assetco_exit and _ENABLE_INTERPARTY_ELIMINATION:
            _ie_entries = []
            for _base_entry in _batch_entries[_asset_start_pos:]:
                _ie_entries.append({
                    "debit_account": _base_entry["credit_account"] + " - Interparty Elimination",
                    "credit_account": _base_entry["debit_account"] + " - Interparty Elimination",
                    "amount": _base_entry["amount"],
                    "period": _base_entry["period"],
                    "income_statement_line_item": (
                        _base_entry["income_statement_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("income_statement_line_item")
                        else None
                    ),
                    "cashflow_line_item": (
                        _base_entry["cashflow_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("cashflow_line_item")
                        else None
                    ),
                    "description": _base_entry["description"] + " (Interparty Elimination)",
                    "reference": _base_entry["reference"] + "-IE",
                })
            _batch_entries.extend(_ie_entries)

        # ==============================================================
        # Interparty IS/CF Elimination Tracking
        # ==============================================================
        if _is_assetco_exit:
            _elim_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = (_be.get("income_statement_line_item") or "")
                _cf_item = _be.get("cashflow_line_item")
                _amt = float(_be.get("amount", 0.0))
                _per = _be.get("period")
                if abs(_amt) < 0.01:
                    continue
                if _is_item == "Asset Sales Revenue":
                    _elim_entries.append({
                        "debit_account": "Interparty Revenue Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Revenue Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPRE-{asset_idx}-{_per}",
                    })
                if _is_item == "Cost of Asset Sales":
                    _elim_entries.append({
                        "debit_account": "Interparty COGS Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP COGS Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPCE-{asset_idx}-{_per}",
                    })
                if _cf_item and _be.get("debit_account") == "Cash and Cash Equivalents":
                    _elim_entries.append({
                        "debit_account": "Interparty Cash Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Cash Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPXE-{asset_idx}-{_per}",
                    })
            _batch_entries.extend(_elim_entries)

    if not _batch_entries:
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )

    return accounts, journal, financial_statements


# ------------------------------------------------------------------------------
# C.4a-iii Forward Funding Entries
# ------------------------------------------------------------------------------

def fn_process_forward_funding_entries(
    forward_funding_cash_df: pd.DataFrame,
    s_curve_df: pd.DataFrame,
    total_dev_cost_df: pd.DataFrame,
    land_acquisition_cost_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    reference_prefix: str = "DC-FFUND",
    exit_counterparty: Optional[pd.Series] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process Forward Funding accounting entries.

    Forward Funding: Cash is received progressively based on construction
    milestones (S-curve). Revenue is recognized based on construction
    progress. Cost of sales is proportional to revenue recognised.

    Entry logic per asset per period:

    1. Cash Receipt:
       Dr Cash and Cash Equivalents / Cr Unearned Revenue

    2. Revenue Recognition (based on construction S-curve progress):
       Dr Unearned Revenue / Cr Developed Unit Sales Revenue

    3. Cost Reclassification (proportional to revenue):
       Dr Inventory - Developed Units / Cr Serviced Land Assets   (land portion)
       Dr Inventory - Developed Units / Cr CWIP - Developed Units (dev cost portion)

    4. Cost of Sales (proportional to revenue):
       Dr Cost of Developed Unit Sales / Cr Inventory - Developed Units
    """
    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        print("fn_process_forward_funding_entries: asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_forward_funding_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Cash and Cash Equivalents",
        "Unearned Revenue",
        "Serviced Land Assets",
        "CWIP - Developed Units",
        "Developed Unit Sales Revenue",
        "Cost of Developed Unit Sales",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(f"fn_process_forward_funding_entries: missing required accounts: {missing_accounts}")
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return accounts, journal, financial_statements

    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            df.index = df.index.map(lambda x: str(x).strip())
        return df

    forward_funding_cash_df = _normalize_df(forward_funding_cash_df) if isinstance(forward_funding_cash_df, pd.DataFrame) else pd.DataFrame()
    s_curve_df = _normalize_df(s_curve_df) if isinstance(s_curve_df, pd.DataFrame) else pd.DataFrame()
    total_dev_cost_df = _normalize_df(total_dev_cost_df) if isinstance(total_dev_cost_df, pd.DataFrame) else pd.DataFrame()
    land_acquisition_cost_df = _normalize_df(land_acquisition_cost_df) if isinstance(land_acquisition_cost_df, pd.DataFrame) else pd.DataFrame()

    if forward_funding_cash_df.empty:
        return accounts, journal, financial_statements

    row_index = forward_funding_cash_df.index
    period_map = {pc: col_to_period.get(pc) for pc in period_cols}
    _batch_entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-extract all source DataFrames as numpy matrices (n_assets × n_periods).
    # ------------------------------------------------------------------
    _str_index = [str(idx).strip() for idx in row_index]

    def _extract_matrix(df: pd.DataFrame) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(_str_index), len(period_cols)), dtype="float64")
        return (
            df.reindex(index=_str_index, columns=period_cols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .values
        )

    _cash_matrix = np.abs(_extract_matrix(forward_funding_cash_df))
    _s_curve_matrix = np.abs(_extract_matrix(s_curve_df))
    _dev_cost_matrix = np.abs(_extract_matrix(total_dev_cost_df))
    _land_cost_matrix = np.abs(_extract_matrix(land_acquisition_cost_df))

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        # Track start position for interparty elimination post-processing.
        _asset_start_pos = len(_batch_entries)

        # Determine if this asset's DevCo exit counterparty is AssetCo.
        _is_assetco_exit = False
        if exit_counterparty is not None and isinstance(exit_counterparty, pd.Series) and not exit_counterparty.empty:
            try:
                _ec_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ec_loc is not None:
                    _is_assetco_exit = str(exit_counterparty.iloc[_ec_loc]).strip() == "AssetCo"
            except Exception:
                pass

        # When interparty entries are disabled, skip interparty assets entirely.
        if _is_assetco_exit and not _ENABLE_INTERPARTY_ENTRIES:
            continue

        cash_values = _cash_matrix[asset_row_idx]
        s_curve_amount_values = _s_curve_matrix[asset_row_idx]
        dev_cost_values = _dev_cost_matrix[asset_row_idx]
        land_cost_values = _land_cost_matrix[asset_row_idx]

        # Per-asset total costs (sum across all periods).
        total_dev_cost = float(dev_cost_values.sum())
        total_land_cost = float(land_cost_values.sum())
        total_cost = total_dev_cost + total_land_cost

        # Total contract value = sum of all forward funding cash receipts.
        total_contract_value = float(cash_values.sum())
        if total_contract_value == 0.0:
            continue

        # Convert S-curve amount phasing to cumulative percentage.
        s_curve_total = float(s_curve_amount_values.sum())
        if s_curve_total > 0.0:
            s_curve_pct_values = np.cumsum(s_curve_amount_values) / s_curve_total
        else:
            s_curve_pct_values = np.zeros(len(period_cols), dtype="float64")

        # Running trackers for this asset.
        cumulative_revenue_recognized = 0.0
        cumulative_cost_recognized = 0.0
        unearned_balance = 0.0
        prev_s_curve = 0.0

        for period_idx, period_col in enumerate(period_cols):
            period_str = period_map.get(period_col)
            if period_str is None:
                continue

            cash_amt = float(cash_values[period_idx])

            # ==============================================================
            # 1. Cash Receipt: Dr Cash / Cr Unearned Revenue
            # ==============================================================
            if cash_amt > 0.0:
                _batch_entries.append({
                    "debit_account": "Cash and Cash Equivalents",
                    "credit_account": "Unearned Revenue",
                    "amount": cash_amt,
                    "period": period_str,
                    "income_statement_line_item": None,
                    "cashflow_line_item": "Forward Funding",
                    "description": f"Forward Funding Cash Receipt - Asset {asset_idx}",
                    "reference": f"{reference_prefix}-CASH-{asset_idx}-{period_col}",
                })
                unearned_balance += cash_amt

            # ==============================================================
            # 2. Revenue Recognition (based on S-curve progress)
            # ==============================================================
            try:
                s_curve_pct_numeric = float(s_curve_pct_values[period_idx])
            except (TypeError, ValueError):
                s_curve_pct_numeric = prev_s_curve

            if pd.isna(s_curve_pct_numeric):
                s_curve_pct_numeric = prev_s_curve

            s_curve_pct_clean = max(prev_s_curve, max(0.0, min(1.0, s_curve_pct_numeric)))
            prev_s_curve = s_curve_pct_clean

            # Revenue target = total contract value � cumulative S-curve %
            revenue_target = total_contract_value * s_curve_pct_clean
            period_revenue = max(0.0, revenue_target - cumulative_revenue_recognized)

            if period_revenue > 0.0:
                # Recognise revenue up to the available Unearned Revenue balance.
                recognizable = min(period_revenue, unearned_balance) if unearned_balance > 0.0 else 0.0

                if recognizable > 0.0:
                    _batch_entries.append({
                        "debit_account": "Unearned Revenue",
                        "credit_account": "Developed Unit Sales Revenue",
                        "amount": recognizable,
                        "period": period_str,
                        "income_statement_line_item": "Asset Sales Revenue",
                        "cashflow_line_item": None,
                        "description": f"Forward Funding Revenue Recognition - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-REV-{asset_idx}-{period_col}",
                    })
                    unearned_balance -= recognizable
                    cumulative_revenue_recognized += recognizable

            # ==============================================================
            # 3 & 4. Cost Recognition (proportional to revenue)
            # ==============================================================
            actual_revenue_this_period = min(period_revenue, recognizable) if period_revenue > 0.0 else 0.0
            if actual_revenue_this_period > 0.0 and total_contract_value > 0.0 and total_cost > 0.0:
                period_cost = total_cost * (actual_revenue_this_period / total_contract_value)

                # Split between land and development cost proportionally.
                if total_cost > 0.0:
                    land_portion = period_cost * (total_land_cost / total_cost)
                    dev_portion = period_cost * (total_dev_cost / total_cost)
                else:
                    land_portion = 0.0
                    dev_portion = 0.0

                # Dr Cost of Developed Unit Sales / Cr Serviced Land Assets
                if land_portion > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "Serviced Land Assets",
                        "amount": land_portion,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Forward Funding Cost of Sales (Land) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-LA-{asset_idx}-{period_col}",
                    })

                # Dr Cost of Developed Unit Sales / Cr CWIP - Developed Units
                if dev_portion > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Developed Unit Sales",
                        "credit_account": "CWIP - Developed Units",
                        "amount": dev_portion,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Asset Sales",
                        "cashflow_line_item": None,
                        "description": f"Forward Funding Cost of Sales (CWIP) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-CWIP-{asset_idx}-{period_col}",
                    })

                cumulative_cost_recognized += period_cost

        # ==============================================================
        # Interparty Elimination: Generate reversed entries for assets
        # whose DevCo exit counterparty is AssetCo.
        # ==============================================================
        if _is_assetco_exit and _ENABLE_INTERPARTY_ELIMINATION:
            _ie_entries = []
            for _base_entry in _batch_entries[_asset_start_pos:]:
                _ie_entries.append({
                    "debit_account": _base_entry["credit_account"] + " - Interparty Elimination",
                    "credit_account": _base_entry["debit_account"] + " - Interparty Elimination",
                    "amount": _base_entry["amount"],
                    "period": _base_entry["period"],
                    "income_statement_line_item": (
                        _base_entry["income_statement_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("income_statement_line_item")
                        else None
                    ),
                    "cashflow_line_item": (
                        _base_entry["cashflow_line_item"] + " - Interparty Elimination"
                        if _base_entry.get("cashflow_line_item")
                        else None
                    ),
                    "description": _base_entry["description"] + " (Interparty Elimination)",
                    "reference": _base_entry["reference"] + "-IE",
                })
            _batch_entries.extend(_ie_entries)

        # ==============================================================
        # Unrealized Gains: For interparty forward funding (DevCo → AssetCo),
        # record the profit (Revenue − COGS) in a tracking account.
        # ==============================================================
        if _is_assetco_exit:
            _ug_revenue = 0.0
            _ug_cogs = 0.0
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = _be.get("income_statement_line_item", "")
                if _is_item == "Asset Sales Revenue":
                    _ug_revenue += float(_be.get("amount", 0.0))
                elif _is_item == "Cost of Asset Sales":
                    _ug_cogs += float(_be.get("amount", 0.0))
            _ug_profit = round(_ug_revenue - _ug_cogs, 2)
            if abs(_ug_profit) > 0.01:
                _ug_period = _batch_entries[-1]["period"] if _batch_entries[_asset_start_pos:] else None
                if _ug_period:
                    _batch_entries.append({
                        "debit_account": "Unrealized Gains on Interparty Sales",
                        "credit_account": "Unrealized Gains Offset",
                        "amount": abs(_ug_profit),
                        "period": _ug_period,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Unrealized Gains on Forward Funding - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-UG-{asset_idx}",
                    })

        # ==============================================================
        # Interparty IS/CF Elimination Tracking
        # ==============================================================
        if _is_assetco_exit:
            _elim_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = (_be.get("income_statement_line_item") or "")
                _cf_item = _be.get("cashflow_line_item")
                _amt = float(_be.get("amount", 0.0))
                _per = _be.get("period")
                if abs(_amt) < 0.01:
                    continue
                if _is_item == "Asset Sales Revenue":
                    _elim_entries.append({
                        "debit_account": "Interparty Revenue Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Revenue Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPRE-{asset_idx}-{_per}",
                    })
                if _is_item == "Cost of Asset Sales":
                    _elim_entries.append({
                        "debit_account": "Interparty COGS Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP COGS Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPCE-{asset_idx}-{_per}",
                    })
                if _cf_item and _be.get("debit_account") == "Cash and Cash Equivalents":
                    _elim_entries.append({
                        "debit_account": "Interparty Cash Elimination",
                        "credit_account": "Interparty Netting Offset",
                        "amount": _amt,
                        "period": _per,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"IP Cash Elim Tracking - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPXE-{asset_idx}-{_per}",
                    })
            _batch_entries.extend(_elim_entries)

    if not _batch_entries:
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )

    return accounts, journal, financial_statements


# ------------------------------------------------------------------------------
# C.4b DevCo Debt & Financing Entries
# ------------------------------------------------------------------------------

def fn_process_devco_debt_entries(
    facility_configs: List[Dict[str, Any]],
    equity_infusion_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    reference_prefix: str = "LC-DEBT",
    cwip_account: str = "CWIP - Serviced Land",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process debt facility and equity journal entries.

    Handles four facility types:
      - Revolvers (asset-level and project-level): repayment is split between
        interest expense and principal using capitalized interest comparison.
      - Term Loans (asset-level and project-level): uses pre-split fields for
        principal, interest, and capitalization.

    Revolver split logic per period:
      Cap interest is always capitalized: Dr CWIP / Cr Loan Account.
      A cumulative cap-interest tracker determines the interest/principal
      split when repayment occurs:
        interest_expense = min(repayment, cumulative_cap_interest)
        principal        = repayment - interest_expense
      This ensures previously capitalized interest is expensed first,
      with the remainder reducing principal.

    Term Loan logic per period:
      Dr CWIP / Cr Loan Account  (capitalized interest, non-cash)
      Dr Interest Expense / Cr Cash              (expensed interest)
      Dr Loan Account / Cr Cash                  (principal + balloon repayment)

    All facilities:
      Drawdown:   Dr Cash / Cr Loan Account
      Arr. Fees:  Dr Debt Fees Expense / Cr Cash
      Comm. Fees: Dr Debt Fees Expense / Cr Cash

    Equity Infusion:
      Dr Cash / Cr Share Capital

    Parameters:
    -----------
    facility_configs : list of dict
        Each dict describes a facility with keys:
          "name", "type" ("revolver" | "term_loan"),
          "loan_account", "interest_expense_account",
          "cf_drawdown", "cf_repayment", "cf_interest", "cf_fees",
          "drawdown_df", "cap_interest_df", "repayment_df",
          "arrangement_fees_df", "commitment_fees_df",
          For term_loan additionally:
            "principal_repayment_df", "balloon_df",
            "interest_expensed_df", "valuation_fees_df", "other_fees_df"
    equity_infusion_df : pd.DataFrame
        Equity infusion data (project-level).
    col_to_period : dict
        Column-name ? period-string mapping.
    accounts, journal, financial_statements : current state
    account_names_dict : dict
    reference_prefix : str
    """
    if not col_to_period:
        print("fn_process_devco_debt_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return accounts, journal, financial_statements

    period_map = [(pc, col_to_period.get(pc)) for pc in period_cols]
    _batch_entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Helper: extract all rows as a numpy matrix aligned to period_cols
    # ------------------------------------------------------------------
    def _extract_matrix(df: pd.DataFrame, str_index) -> np.ndarray:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return np.zeros((len(str_index), len(period_cols)), dtype="float64")
        return np.abs(
            df.reindex(index=str_index, columns=period_cols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .values
        )

    # ------------------------------------------------------------------
    # Process each facility
    # ------------------------------------------------------------------
    for config in facility_configs:
        facility_name = config.get("name", "Unknown")
        facility_type = config.get("type", "revolver")
        loan_account = config.get("loan_account", "")
        interest_expense_account = config.get("interest_expense_account", "")
        cf_drawdown = config.get("cf_drawdown")
        cf_repayment = config.get("cf_repayment")
        cf_interest = config.get("cf_interest")
        cf_fees = config.get("cf_fees")
        ref = config.get("ref_prefix", reference_prefix)

        drawdown_df = config.get("drawdown_df", pd.DataFrame())
        cap_interest_df = config.get("cap_interest_df", pd.DataFrame())
        repayment_df = config.get("repayment_df", pd.DataFrame())
        arrangement_fees_df = config.get("arrangement_fees_df", pd.DataFrame())
        commitment_fees_df = config.get("commitment_fees_df", pd.DataFrame())

        # Determine row index from any non-empty source DF.
        row_index = None
        for candidate in [drawdown_df, repayment_df, cap_interest_df]:
            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                row_index = candidate.index
                break
        if row_index is None or len(row_index) == 0:
            print(f"fn_process_devco_debt_entries: no rows for facility {facility_name}")
            continue

        # Normalize indices to string.
        def _norm_idx(df):
            if isinstance(df, pd.DataFrame) and not df.empty:
                df = df.copy()
                df.index = df.index.map(lambda x: str(x).strip())
            return df

        drawdown_df = _norm_idx(drawdown_df)
        cap_interest_df = _norm_idx(cap_interest_df)
        repayment_df = _norm_idx(repayment_df)
        arrangement_fees_df = _norm_idx(arrangement_fees_df)
        commitment_fees_df = _norm_idx(commitment_fees_df)

        # Term loan specific DFs.
        principal_repayment_df = _norm_idx(config.get("principal_repayment_df", pd.DataFrame()))
        balloon_df = _norm_idx(config.get("balloon_df", pd.DataFrame()))
        interest_expensed_df = _norm_idx(config.get("interest_expensed_df", pd.DataFrame()))
        valuation_fees_df = _norm_idx(config.get("valuation_fees_df", pd.DataFrame()))
        other_fees_df = _norm_idx(config.get("other_fees_df", pd.DataFrame()))

        # Re-derive row_index after normalization.
        for candidate in [drawdown_df, repayment_df, cap_interest_df]:
            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                row_index = candidate.index
                break

        # Pre-extract all source DataFrames as numpy matrices (n_rows × n_periods).
        _str_index = [str(idx).strip() for idx in row_index]
        _drawdown_matrix = _extract_matrix(drawdown_df, _str_index)
        _cap_interest_matrix = _extract_matrix(cap_interest_df, _str_index)
        _arr_fee_matrix = _extract_matrix(arrangement_fees_df, _str_index)
        _comm_fee_matrix = _extract_matrix(commitment_fees_df, _str_index)

        if facility_type == "revolver":
            _repayment_matrix = _extract_matrix(repayment_df, _str_index)
        else:
            _principal_matrix = _extract_matrix(principal_repayment_df, _str_index)
            _balloon_matrix = _extract_matrix(balloon_df, _str_index)
            _int_exp_matrix = _extract_matrix(interest_expensed_df, _str_index)
            _val_fee_matrix = _extract_matrix(valuation_fees_df, _str_index)
            _oth_fee_matrix = _extract_matrix(other_fees_df, _str_index)

        for row_idx, row_key in enumerate(row_index):
            row_key_str = str(row_key).strip()
            _entry_asset_no = "Consolidated" if facility_name.startswith("Project") else row_key_str

            drawdown_vals = _drawdown_matrix[row_idx]
            cap_interest_vals = _cap_interest_matrix[row_idx]
            arrangement_fee_vals = _arr_fee_matrix[row_idx]
            commitment_fee_vals = _comm_fee_matrix[row_idx]

            if facility_type == "revolver":
                repayment_vals = _repayment_matrix[row_idx]
            else:
                # Term loan: separate fields.
                principal_vals = _principal_matrix[row_idx]
                balloon_vals = _balloon_matrix[row_idx]
                interest_exp_vals = _int_exp_matrix[row_idx]
                valuation_fee_vals = _val_fee_matrix[row_idx]
                other_fee_vals = _oth_fee_matrix[row_idx]

            # Cumulative capitalized interest tracker for revolvers.
            # Repayment is split: accumulated cap interest is expensed
            # first, remainder reduces principal.
            _cumulative_cap_interest = 0.0

            for period_idx, (period_col, period_str) in enumerate(period_map):
                if period_str is None:
                    continue

                drawdown_amt = float(drawdown_vals[period_idx])
                cap_interest_amt = float(cap_interest_vals[period_idx])
                arr_fee_amt = float(arrangement_fee_vals[period_idx])
                comm_fee_amt = float(commitment_fee_vals[period_idx])

                # ==========================================
                # 1. Drawdown: Dr Cash / Cr Loan Account
                # ==========================================
                if drawdown_amt > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": loan_account,
                        "amount": drawdown_amt,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cf_drawdown,
                        "description": f"{facility_name} Drawdown - Row {row_key_str}",
                        "reference": f"{ref}-DD-{row_key_str}-{period_col}",
                        "asset_no": _entry_asset_no,
                    })

                # ==========================================
                # 2. Interest & Repayment
                # ==========================================
                if facility_type == "revolver":
                    repayment_amt = float(repayment_vals[period_idx])

                    # Always capitalize current period's interest to CWIP/Loan.
                    if cap_interest_amt > 0.0:
                        _cumulative_cap_interest += cap_interest_amt
                        _batch_entries.append({
                            "debit_account": cwip_account,
                            "credit_account": loan_account,
                            "amount": cap_interest_amt,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"{facility_name} Capitalized Interest to CWIP - Row {row_key_str}",
                            "reference": f"{ref}-CAPIT-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    # Split repayment using cumulative cap interest.
                    if repayment_amt > 0.0:
                        interest_expense = min(repayment_amt, _cumulative_cap_interest)
                        principal_payment = repayment_amt - interest_expense
                        _cumulative_cap_interest -= interest_expense

                        if interest_expense > 0.0:
                            _batch_entries.append({
                                "debit_account": interest_expense_account,
                                "credit_account": "Cash and Cash Equivalents",
                                "amount": interest_expense,
                                "period": period_str,
                                "income_statement_line_item": interest_expense_account,
                                "cashflow_line_item": cf_interest,
                                "description": f"{facility_name} Interest Expense - Row {row_key_str}",
                                "reference": f"{ref}-INTEXP-{row_key_str}-{period_col}",
                                "asset_no": _entry_asset_no,
                            })

                        if principal_payment > 0.0:
                            _batch_entries.append({
                                "debit_account": loan_account,
                                "credit_account": "Cash and Cash Equivalents",
                                "amount": principal_payment,
                                "period": period_str,
                                "income_statement_line_item": None,
                                "cashflow_line_item": cf_repayment,
                                "description": f"{facility_name} Principal Repayment - Row {row_key_str}",
                                "reference": f"{ref}-PRINC-{row_key_str}-{period_col}",
                                "asset_no": _entry_asset_no,
                            })

                else:  # term_loan
                    principal_amt = float(principal_vals[period_idx])
                    balloon_amt_val = float(balloon_vals[period_idx])
                    interest_exp_amt = float(interest_exp_vals[period_idx])

                    # Capitalized interest ? Dr CWIP / Cr Loan (non-cash).
                    if cap_interest_amt > 0.0:
                        _batch_entries.append({
                            "debit_account": cwip_account,
                            "credit_account": loan_account,
                            "amount": cap_interest_amt,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"{facility_name} Capitalized Interest to CWIP - Row {row_key_str}",
                            "reference": f"{ref}-CAPIT-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    # Interest expensed ? Dr Interest Expense / Cr Cash.
                    if interest_exp_amt > 0.0:
                        _batch_entries.append({
                            "debit_account": interest_expense_account,
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": interest_exp_amt,
                            "period": period_str,
                            "income_statement_line_item": interest_expense_account,
                            "cashflow_line_item": cf_interest,
                            "description": f"{facility_name} Interest Payment - Row {row_key_str}",
                            "reference": f"{ref}-INTPAY-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    # Principal repayment ? Dr Loan / Cr Cash.
                    if principal_amt > 0.0:
                        _batch_entries.append({
                            "debit_account": loan_account,
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": principal_amt,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": cf_repayment,
                            "description": f"{facility_name} Principal Repayment - Row {row_key_str}",
                            "reference": f"{ref}-PRINC-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    # Balloon payment ? Dr Loan / Cr Cash.
                    if balloon_amt_val > 0.0:
                        _batch_entries.append({
                            "debit_account": loan_account,
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": balloon_amt_val,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": cf_repayment,
                            "description": f"{facility_name} Balloon Payment - Row {row_key_str}",
                            "reference": f"{ref}-BALLOON-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    # Term loan additional fees.
                    valuation_fee_val = float(valuation_fee_vals[period_idx])
                    other_fee_val = float(other_fee_vals[period_idx])

                    if valuation_fee_val > 0.0:
                        _batch_entries.append({
                            "debit_account": "Debt Fees Expense",
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": valuation_fee_val,
                            "period": period_str,
                            "income_statement_line_item": "Debt Fees Expense",
                            "cashflow_line_item": cf_fees,
                            "description": f"{facility_name} Valuation Fees - Row {row_key_str}",
                            "reference": f"{ref}-VALFEE-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                    if other_fee_val > 0.0:
                        _batch_entries.append({
                            "debit_account": "Debt Fees Expense",
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": other_fee_val,
                            "period": period_str,
                            "income_statement_line_item": "Debt Fees Expense",
                            "cashflow_line_item": cf_fees,
                            "description": f"{facility_name} Other Debt Fees - Row {row_key_str}",
                            "reference": f"{ref}-OTHFEE-{row_key_str}-{period_col}",
                            "asset_no": _entry_asset_no,
                        })

                # ==========================================
                # 3. Arrangement Fees: Dr Debt Fees / Cr Cash
                # ==========================================
                if arr_fee_amt > 0.0:
                    _batch_entries.append({
                        "debit_account": "Debt Fees Expense",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": arr_fee_amt,
                        "period": period_str,
                        "income_statement_line_item": "Debt Fees Expense",
                        "cashflow_line_item": cf_fees,
                        "description": f"{facility_name} Arrangement Fees - Row {row_key_str}",
                        "reference": f"{ref}-ARRFEE-{row_key_str}-{period_col}",
                        "asset_no": _entry_asset_no,
                    })

                # ==========================================
                # 4. Commitment Fees: Dr Debt Fees / Cr Cash
                # ==========================================
                if comm_fee_amt > 0.0:
                    _batch_entries.append({
                        "debit_account": "Debt Fees Expense",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": comm_fee_amt,
                        "period": period_str,
                        "income_statement_line_item": "Debt Fees Expense",
                        "cashflow_line_item": cf_fees,
                        "description": f"{facility_name} Commitment Fees - Row {row_key_str}",
                        "reference": f"{ref}-COMFEE-{row_key_str}-{period_col}",
                        "asset_no": _entry_asset_no,
                    })

    # ------------------------------------------------------------------
    # Equity Infusion: Dr Cash / Cr Share Capital
    # ------------------------------------------------------------------
    if isinstance(equity_infusion_df, pd.DataFrame) and not equity_infusion_df.empty:
        equity_df = equity_infusion_df.copy()
        equity_df.index = equity_df.index.map(lambda x: str(x).strip())
        for row_key in equity_df.index:
            row_key_str = str(row_key).strip()
            eq_vals = np.abs(
                pd.to_numeric(
                    equity_df.loc[row_key_str].reindex(period_cols), errors="coerce"
                ).fillna(0.0).to_numpy(dtype="float64")
            )
            for period_idx, (period_col, period_str) in enumerate(period_map):
                if period_str is None:
                    continue
                eq_amt = float(eq_vals[period_idx])
                if eq_amt > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Share Capital",
                        "amount": eq_amt,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": "Project and Asset Equity Contribution",
                        "description": f"Equity Infusion - Row {row_key_str}",
                        "reference": f"{reference_prefix}-EQ-{row_key_str}-{period_col}",
                    })

    # ------------------------------------------------------------------
    # Flush all entries
    # ------------------------------------------------------------------
    if not _batch_entries:
        print("fn_process_devco_debt_entries: no entries to post")
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )

    return accounts, journal, financial_statements



# ==============================================================================
# SECTION D: EXECUTION
# ==============================================================================
# This section contains the main execution logic including:
# - Configuration structures (account names, financial statement layouts)
# - Main consolidation wrapper function
# - Entry point function for external callers
# ==============================================================================

# ------------------------------------------------------------------------------
# D.1 Main Consolidation Wrapper
# ------------------------------------------------------------------------------

def wrapper_for_vars(payload: Any) -> Optional[Any]:
    """
    Main wrapper for consolidated model pre-processing and execution.
    
    This function orchestrates the entire consolidation pipeline from
    raw payload extraction through financial statement generation.

    Workflow Phases:
    ----------------
    PHASE 1: Extract Input Sources
        - Extract LandCo, DevCo, AssetCo, and JV data from payload
        - Initialize target containers for each module
        
    PHASE 2: Define Consolidated Cashflow Template
        - Build CFO/CFI/CFF structure with all line items
        
    PHASE 3: Extract Section Data
        - Populate target containers using module key mappings
        
    PHASE 4: Normalize AssetCo Nested Outputs
        - Extract monthly/annual DataFrames from AssetCo outputs
        
    PHASE 5: Build Shared Timeline
        - Create master timeline from LandCo/DevCo
        - Build template row index for consolidated DataFrame
        
    PHASE 6: Interparty Mapping
        - Determine acquisition/exit counterparties by asset
        
    PHASE 7: Financial Statement Structures
        - Define account names dictionary
        - Define balance sheet, income statement structures
        
    PHASE 8: Initialize Accounts and Statements
        - Create all double-entry accounts
        - Initialize financial statements
        
    PHASE 9: (Reserved for calculation logic)
        
    PHASE 10: Build Output Structures
        - Create monthly_dfs, annual_dfs, excel_output

    Parameters:
    -----------
    payload : Any
        Raw input payload containing:
        - landco: Dict with LandCo module data
        - devco: Dict with DevCo module data
        - assetco_consolidated: List of AssetCo payloads
        - jv_consolidation: List of JV payloads

    Returns:
    --------
    Optional[Any]
        Currently returns None as the final output structure is under development.
        Will return consolidated model outputs when complete.
    """

    try:
        if not isinstance(payload, dict):
            print(
                "Error in wrapper_for_vars: payload must be a dictionary, "
                f"got {type(payload).__name__}"
            )
            return None

        _enable_financial_statement_trace = bool(payload.get("_enable_financial_statement_trace", False))
        _enable_lightweight_output = bool(payload.get("_lightweight_entity_output", False))

        # --------------------------------------------------------------------
        # Initialize Timing Context
        # --------------------------------------------------------------------
        _timing_ctx = fn_create_timing_context()

        # --------------------------------------------------------------------
        # Export Flags Configuration
        # --------------------------------------------------------------------
        _EXPORT_FLAGS: Dict[str, bool] = {
            "all_sections": False,
            "input_sources": False,
            "cashflow_template": False,
            "section_data": False,
            "assetco_outputs": False,
            "timeline": False,
            "interparty_mapping": False,
            "accounts": False,
            "financial_statements": False,
            "calculations": False,
            "output_structures": False,
        }

        # --------------------------------------------------------------------
        # Asset Filter Mode Configuration
        # --------------------------------------------------------------------
        # Options:
        #   "Consolidated"  ? process all assets with full financing flow.
        #   "<asset_id>"    ? process only that single asset;
        #                     skip debt/financing and use equity-funded mode.
        # Dynamically read from payload (injected by consolidated_model.py).
        # --------------------------------------------------------------------
        _ASSET_FILTER_MODE: str = payload.get("_asset_filter_mode", "Consolidated") if isinstance(payload, dict) else "Consolidated"

        # ====================================================================
        # PHASE 1: EXTRACT INPUT SOURCES
        # ====================================================================
        
        _landco_source, _devco_source, _assetco_source, _jv_source = fn_extract_core_sources(payload)

        _landco_timeline = {}
        _landco_global_assumptions = {}
        _landco_asset_assumptions = {}
        _landco_escrow_schedule = {}
        _landco_support_workings = {}
        _landco_cfo = {}
        _landco_cfi = {}
        _landco_cff = {}

        _devco_timeline = {}
        _devco_global_assumptions = {}
        _devco_asset_assumptions = {}
        _devco_escrow_schedule = {}
        _devco_support_workings = {}
        _devco_cfo = {}
        _devco_cfi = {}
        _devco_cff = {}

        _assetco_asset_id = {}
        _assetco_asset_name = {}
        _assetco_output_json = {}
        _assetco_scenario_id = {}
        _assetco_scenario_name = {}
        _assetco_is_hospitality = {}
        _assetco_asset_identifier = {}

        _assetco_annual_dfs = {}
        _assetco_monthly_dfs = {}
        _assetco_inputs = {}

        _assetco_cfo = {}
        _assetco_cfi = {}
        _assetco_cff = {}
        _assetco_timeline = {}

        _jv_name = {}
        _venture_type = {}
        _asset_unique_id = {}
        _jvjda_inclusion = {}
        _assetco_inclusion = {}
        _assetco_jv_inclusion = {}

        _assetco_number_of_assets = len(_assetco_source) if isinstance(_assetco_source, list) else 0
        
        _module_key_mapping: Dict[str, Dict[str, Any]] = {
            "LandCo": {
                "Timeline": _landco_timeline,
                "global_assumptions": _landco_global_assumptions,
                "asset_assumptions": _landco_asset_assumptions,
                "Escrow Schedule": _landco_escrow_schedule,
                "Support Workings": _landco_support_workings,
                "Cashflow from Operations": _landco_cfo,
                "Cashflow from Investments": _landco_cfi,
                "Cashflow from Financing": _landco_cff
            },
            "DevCo": {
                "Timeline": _devco_timeline,
                "global_assumptions": _devco_global_assumptions,
                "asset_assumptions": _devco_asset_assumptions,
                "Escrow Schedule": _devco_escrow_schedule,
                "Support Workings": _devco_support_workings,
                "Cashflow from Operations": _devco_cfo,
                "Cashflow from Investments": _devco_cfi,
                "Cashflow from Financing": _devco_cff
            },
            "AssetCo": {
                "asset_id": _assetco_asset_id,
                "asset_name": _assetco_asset_name,
                "output_json": _assetco_output_json,
                "scenario_id": _assetco_scenario_id,
                "scenario_name": _assetco_scenario_name,
                "is_hospitality": _assetco_is_hospitality,
                "asset_identifier": _assetco_asset_identifier
            }
        }

        _assetco_vars = {
            "Cashflow from Operations": _assetco_cfo,
            "Cashflow from Investments": _assetco_cfi,
            "Cashflow from Financing": _assetco_cff,
            "Monthly Timeline": _assetco_timeline,
        }

        _asset_inputs_vars = {
            'jv_name': _jv_name,
            'venture_type': _venture_type,
            'asset_unique_id': _asset_unique_id,
            'jvjda_inclusion': _jvjda_inclusion,
            'assetco_inclusion': _assetco_inclusion,
            'assetco_jv_inclusion': _assetco_jv_inclusion
        }

        module_sources = {
            "LandCo": _landco_source,
            "DevCo": _devco_source,
            "AssetCo": _assetco_source,
        }

        fn_record_timing(_timing_ctx, "PHASE 1: Extract Input Sources")

        # ====================================================================
        # PHASE 2: DEFINE CONSOLIDATED CASHFLOW TEMPLATE
        # ====================================================================

        _consolidated_structure = {
            "CFO": {
                "Land Sales": [
                    "On-plan Sales Collection",
                    "Off-plan Sales Collection",
                    "Escrow Setup Fees",
                ],
                "Asset Sales": [
                    "Asset Sales through Escrow",
                    "Asset Sales through Collection (Post-Dev)",
                    "Forward Funding",
                    "Forward Sales"
                ],
                "Land Lease Income": [
                    "Lease Collection"
                ],
                "Lease Revenue": [
                    "Base Rent",
                    "Turnover Rent",
                    "Service Charge",
                    "Leasing Commissions"
                ],
                "Hospitality EBITDA": [
                    "Hospitality EBITDA"
                ],
                "Parking Revenue": [
                    "Parking Revenue"
                ],
                "Other Operating Income": [
                    "Other Income 1",
                    "Other Income 2",
                    "Other Income 3",
                    "Government Subsidies",
                    "PA Recovery",
                ],
                "Operating Expenses": [
                    "Land Lease Operating Expenses",
                    "DLP Insurance",
                    "Pre Operating Expenses",
                    "Utilities",
                    "Facility Management Fees",
                    "Administration Cost",
                    "Insurance",
                    "Other Operating Expenses",
                    "Bad Debt",
                    "Void Period Opex",
                    "Sinking Fund",
                    "Parking Expenses"
                ],
                "Other Expenses": [
                    "Other Expense 1",
                    "Other Expense 2",
                    "Other Expense 3"
                ],
                "Community Operations": [
                    "Community Operations Expense - Amanah",
                    "Community Operations Recovery - Amanah",
                    "Community Operations Expense - ROSHN",
                    "Community Operations Recovery - ROSHN",
                ],
                "Sales and Marketing Costs": [
                    "Land Leasing Costs",
                    "Sales Transaction Cost",
                    "Sales Cost",
                    "Marketing Cost"
                ],
                "Corporate Overheads": [
                    "Salaries Expenses",
                    "IT Services Expenses",
                    "Office Rent and Utilities Expenses",
                    "Professional Services Expenses",
                    "Marketing Expenses",
                    "Sales Cost Expenses",
                    "Additional Expenses"
                ],
                "Interparty Eliminations": [
                    "On-plan Sales Collection - Interparty Elimination",
                    "Off-plan Sales Collection - Interparty Elimination",
                    "Escrow Setup Fees - Interparty Elimination",
                    "Asset Sales through Collection (Post-Dev) - Interparty Elimination",
                    "Asset Sales through Escrow - Interparty Elimination",
                    "Forward Sales - Interparty Elimination",
                    "Forward Funding - Interparty Elimination",
                ]
            },
            "CFI": {
                "Acquisition Cost": [
                    "Raw Land Acquisition Cost",
                    "Serviced Land Acquisition Cost",
                    "Asset Acquisition Cost"
                ],
                "Acquisition Transaction Costs": [
                    "Legal Cost",
                    "Agency Cost",
                    "Technical Cost",
                    "Valuation Cost",
                    "Due Diligence Cost",
                    "Real Estate Transaction Tax",
                    "Municipal Fees",
                    "Transfer Tax / Stamp Duty",
                    "Brokerage"
                ],
                "Infrastructure Capex": [
                    "Primary Infrastructure Cost",
                    "Secondary Infrastructure Cost"
                ],
                "Development Capex": [
                    "Vertical Construction Cost",
                    "Public Amenity Cost",
                    "CEC Cost",
                    "Canal Cost"
                ],
                "Soft Costs": [
                    "Design Cost",
                    "Permitting Cost",
                    "Supervision Cost",
                    "Project Management Cost"
                ],
                "Contingency Cost": [
                    "Contingency Cost Payment"
                ],
                "Maintenance Capex": [
                    "Maintenance Capex 1",
                    "Maintenance Capex 2",
                    "Maintenance Capex 3",
                    "Maintenance Capex 4"
                ],
                "Tenant Improvements": [
                    "Tenant Fitout Allowance"
                ],
                "Capitalized Corporate Costs": [
                    "Capitalized Salaries Expenses",
                    "Capitalized IT Services Expenses",
                    "Capitalized Office Rent and Utilities Expenses",
                    "Capitalized Professional Services Expenses",
                    "Capitalized Marketing Expenses",
                    "Capitalized Sales Cost Expenses",
                    "Capitalized Additional Expenses"
                ],
                "Asset Sale Proceeds": [
                    "Asset Sale Value",
                    "Land Bank - Exit Value",
                    "Land Lease - Terminal Value"
                ],
                "Interparty Eliminations": [
                    "Land Bank - Exit Value - Interparty Elimination",
                    "Land Lease - Terminal Value - Interparty Elimination",
                    "Serviced Land Acquisition Cost - Interparty Elimination",
                    "Asset Acquisition Cost - Interparty Elimination",
                ]
            },
            "CFF": {
                "Debt Drawdown": [
                    "Term Loan - Debt Drawdown",
                    "Revolver - Debt Drawdown",
                    "Other Debt Drawdown"
                ],
                "Debt Repayment": [
                    "Term Loan - Debt Repayment",
                    "Revolver - Debt Repayment",
                    "Other Debt Repayment"
                ],
                "Interest Payments": [
                    "Term Loan - Interest Payments",
                    "Revolver - Interest Payments",
                    "Other Interest Payments"
                ],
                "Debt Fees": [
                    "Term Loan - Debt Fees",
                    "Revolver - Debt Fees",
                    "Other Debt Fees"
                ],
                "Equity Contributions": [
                    "Land in Kind Contribution",
                    "Project and Asset Equity Contribution"
                ]
            }
        }

        fn_record_timing(_timing_ctx, "PHASE 2: Define Cashflow Template")

        # ====================================================================
        # PHASE 3: EXTRACT SECTION DATA INTO TARGET CONTAINERS
        # ====================================================================
        for module_name, source in module_sources.items():
            fn_extract_module_data(
                module_name,
                source,
                _module_key_mapping.get(module_name, {}),
            )

        fn_record_timing(_timing_ctx, "PHASE 3: Extract Section Data")

        # ====================================================================
        # PHASE 4: NORMALIZE ASSETCO NESTED OUTPUTS
        # ====================================================================
        for index, asset_output_json in (_assetco_output_json.items() if isinstance(_assetco_output_json, dict) else {}):
            if not isinstance(asset_output_json, dict):
                continue

            _assetco_monthly_dfs = asset_output_json.get("monthly_dfs", {})
            _assetco_annual_dfs = asset_output_json.get("annual_dfs", {})
            _assetco_inputs = asset_output_json.get("assetco_inputs", {})

            for key, target_dict in _assetco_vars.items():
                value = _assetco_monthly_dfs.get(key, {})
                if isinstance(value, dict):
                    target_dict[index] = value
                elif isinstance(value, list):
                    target_dict[index] = value[1] if len(value) > 1 else None
            for key, target_dict in _asset_inputs_vars.items():
                value = _assetco_inputs.get(key, None)
                if isinstance(value, str):
                    target_dict[index] = value
                else:
                    target_dict[index] = value

        fn_record_timing(_timing_ctx, "PHASE 4: Normalize AssetCo Outputs")

        # ====================================================================
        # PHASE 5: BUILD SHARED TIMELINE AND TEMPLATE INDEX
        # ====================================================================
        master_timeline_df = fn_build_master_timeline(_devco_timeline, landco_timeline=_landco_timeline)

        _template_row_index = fn_build_template_row_index(_consolidated_structure)
        if not _template_row_index:
            print("Error in wrapper_for_vars: Consolidated template row index could not be built")
            return None
        
        _consolidated_cashflows_df = fn_initialize_consolidated_dataframe(
            _template_row_index,
            master_timeline_df.loc["# of Period"] if master_timeline_df is not None and "# of Period" in master_timeline_df.index else [],
        )

        if _consolidated_cashflows_df.empty:
            print("Error in wrapper_for_vars: Consolidated template dataframe is empty")
            return None

        fn_record_timing(_timing_ctx, "PHASE 5: Build Timeline")

        # ====================================================================
        # PHASE 6: INTERPARTY ACQUISITION AND EXIT COUNTERPARTY MAPPING
        # ====================================================================

        _asset_unique_identifier = fn_extract_assumptions(_landco_asset_assumptions, "ProjectDetails", "asset_unique_identifier")
        _landco_acquisition_override = fn_extract_assumptions(_landco_asset_assumptions, "AcquisitionModule", "override")
        _landco_acquisition_counterparty = fn_extract_assumptions(_landco_asset_assumptions, "AcquisitionModule", "acquisition_counterparty")
        _landco_global_acquisition_counterparty = fn_extract_assumptions(_landco_global_assumptions, "AcquisitionInputs", "acquisition_counterparty")

        _asset_unique_identifier_mask = _asset_unique_identifier.apply(lambda x: isinstance(x, str) and x.strip() != "" and x is not None) if _asset_unique_identifier is not None else pd.Series()

        _landco_acquisition_counterparty = pd.Series(
            np.where(
                _asset_unique_identifier_mask,    
                np.where(
                    _landco_acquisition_override == "Yes",
                    _landco_acquisition_counterparty,
                    _landco_global_acquisition_counterparty
                ),
                None
            )
        ) if _asset_unique_identifier is not None else pd.Series()

        _land_development_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "AssetLifecycleModule", "land_development")
        _vertical_development_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "AssetLifecycleModule", "vertical_development")
        _asset_operations_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "AssetLifecycleModule", "asset_operations")
        _devco_business_model = fn_extract_assumptions(_devco_asset_assumptions, "BusinessModel", "funding_type")

        _jvjda_inclusion_series = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "jvjda_inclusion")
        _lc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "landco_inclusion")
        _dc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "devco_inclusion")
        _ac_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "assetco_inclusion")

        # Null out asset rows where DevCo is in the JV so entry loops skip them.
        # DevCo is in JV when jvjda_inclusion=Yes AND devco_inclusion=Yes.
        if (
            _asset_unique_identifier is not None
            and _jvjda_inclusion_series is not None
            and _dc_jv_inclusion is not None
        ):
            _dc_in_jv_mask = (
                (_jvjda_inclusion_series == "Yes") & (_dc_jv_inclusion == "Yes")
            )
            _asset_unique_identifier = _asset_unique_identifier.where(~_dc_in_jv_mask, other=None)

        if _asset_unique_identifier is not None:
            _interparty_mapping = fn_build_interparty_mapping(
                _asset_unique_identifier,
                _landco_acquisition_counterparty,
                _land_development_inclusion,
                _vertical_development_inclusion,
                _asset_operations_inclusion,
                _asset_unique_identifier_mask,
                lc_jv_inclusion=_lc_jv_inclusion,
                dc_jv_inclusion=_dc_jv_inclusion,
                ac_jv_inclusion=_ac_jv_inclusion,
            )
        else:
            _interparty_mapping = pd.DataFrame()

        fn_record_timing(_timing_ctx, "PHASE 6: Interparty Mapping")

        # ====================================================================
        # PHASE 7: ACCOUNT AND FINANCIAL STATEMENT STRUCTURES
        # ====================================================================

        # --------------------------------------------------------------------
        # Account Names Dictionary with Account Types
        # --------------------------------------------------------------------
        _account_names_dict = {
            # Asset Accounts
            "Cash and Cash Equivalents": {"type": "Asset", "category": "Current Assets"},
            "Accounts Receivable": {"type": "Asset", "category": "Current Assets"},
            "Advances for Land": {"type": "Asset", "category": "Current Assets"},
            "Advance to Contractor": {"type": "Asset", "category": "Current Assets"},
            "Escrow Restricted Cash": {"type": "Asset", "category": "Current Assets"},
            "Restricted Cash - Sinking Fund": {"type": "Asset", "category": "Current Assets"},
            "CWIP - Serviced Land": {"type": "Asset", "category": "Current Assets"},
            "CWIP - Developed Units": {"type": "Asset", "category": "Current Assets"},
            "Land Assets": {"type": "Asset", "category": "Non-Current Assets"},
            "Serviced Land Assets": {"type": "Asset", "category": "Non-Current Assets"},
            "Investment Property": {"type": "Asset", "category": "Non-Current Assets"},
            "Accumulated Depreciation": {"type": "Asset", "category": "Non-Current Assets"},
            "Investments in Associates": {"type": "Asset", "category": "Non-Current Assets"},

            # Unrealized Gains Tracking (consolidated BS only — not in entity BS structure)
            "Unrealized Gains on Interparty Sales": {"type": "Asset", "category": "Non-Current Assets"},
            "Unrealized Gains Offset": {"type": "Equity", "category": "Shareholders Equity"},

            # Interparty Netting Tracking (consolidated BS only — not in entity BS structure)
            "Interparty Accounts Receivable": {"type": "Asset", "category": "Current Assets"},
            "Interparty Unearned Revenue": {"type": "Liability", "category": "Current Liabilities"},
            "Interparty Netting Offset": {"type": "Equity", "category": "Shareholders Equity"},

            # Interparty IS/CF Elimination Tracking (consolidated only — not in entity structures)
            "Interparty Revenue Elimination": {"type": "Asset", "category": "Current Assets"},
            "Interparty COGS Elimination": {"type": "Asset", "category": "Current Assets"},
            "Interparty Cash Elimination": {"type": "Asset", "category": "Current Assets"},
            
            # Liability Accounts
            "Accounts Payable": {"type": "Liability", "category": "Current Liabilities"},
            "Unearned Revenue": {"type": "Liability", "category": "Current Liabilities"},
            "Debt - Term Loan": {"type": "Liability", "category": "Non-Current Liabilities"},
            "Debt - Revolver": {"type": "Liability", "category": "Current Liabilities"},
            "Debt - Other": {"type": "Liability", "category": "Non-Current Liabilities"},

            # Equity Accounts
            "Share Capital": {"type": "Equity", "category": "Shareholders Equity"},
            "Retained Earnings": {"type": "Equity", "category": "Shareholders Equity"},
            "Profit & Loss": {"type": "Equity", "category": "Shareholders Equity"},
            
            # Revenue Accounts
            "Land Sales Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Land Lease Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Asset Sales Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Developed Unit Sales Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Lease Revenue - Base Rent": {"type": "Revenue", "category": "Operating Revenue"},
            "Lease Revenue - Turnover Rent": {"type": "Revenue", "category": "Operating Revenue"},
            "Lease Revenue - Service Charge": {"type": "Revenue", "category": "Operating Revenue"},
            "Hospitality - Room Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Hospitality - F&B Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Hospitality - OOD Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Hospitality - Other Operating Income": {"type": "Revenue", "category": "Operating Revenue"},
            "Parking Revenue": {"type": "Revenue", "category": "Operating Revenue"},
            "Government Subsidies Income": {"type": "Revenue", "category": "Other Income"},
            "PA Recovery Income": {"type": "Revenue", "category": "Other Income"},
            "Other Operating Income": {"type": "Revenue", "category": "Other Income"},
            "Gain on Asset Disposal": {"type": "Revenue", "category": "Other Income"},
            "Community Operations Recovery": {"type": "Revenue", "category": "Other Income"},

            # Expense Accounts
            "Cost of Land Sales": {"type": "Expense", "category": "Cost of Sales"},
            "Cost of Asset Sales": {"type": "Expense", "category": "Cost of Sales"},
            "Cost of Developed Unit Sales": {"type": "Expense", "category": "Cost of Sales"},
            "Cost of Lease Revenue": {"type": "Expense", "category": "Cost of Sales"},
            "Land Lease Operating Expenses": {"type": "Expense", "category": "Operating Expenses"},
            "DLP Insurance Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Pre Operating Expenses": {"type": "Expense", "category": "Operating Expenses"},
            "Utilities Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Facility Management Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Administration Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Insurance Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Other Operating Expenses": {"type": "Expense", "category": "Operating Expenses"},
            "Bad Debt Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Void Period Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Sinking Fund Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Maintenance Capex Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Parking Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Asset Management Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Community Operations Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Sales and Marketing Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Leasing Commissions Expense": {"type": "Expense", "category": "Operating Expenses"},
            "Hospitality Departmental Expenses - Room": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Departmental Expenses - F&B": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Departmental Expenses - OOD": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Departmental Expenses - Other": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Undistributed Expenses - Admin": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Undistributed Expenses - Sales & Marketing": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Undistributed Expenses - IT": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Undistributed Expenses - Utilities": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Non-Operating Expenses": {"type": "Expense", "category": "Hospitality Expenses"},
            "Hospitality Non-Operating Income": {"type": "Revenue", "category": "Operating Revenue"},
            "Salaries Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "IT Services Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Office Rent and Utilities Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Professional Services Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Marketing Overhead Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Sales Cost Overhead Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Additional Overhead Expense": {"type": "Expense", "category": "Corporate Overheads"},
            "Depreciation Expense": {"type": "Expense", "category": "Depreciation and Amortization"},
            "Interest Expense - Term Loan": {"type": "Expense", "category": "Finance Costs"},
            "Interest Expense - Revolver": {"type": "Expense", "category": "Finance Costs"},
            "Interest Expense - Other": {"type": "Expense", "category": "Finance Costs"},
            "Debt Fees Expense": {"type": "Expense", "category": "Finance Costs"},
            "Loss on Asset Disposal": {"type": "Expense", "category": "Other Expenses"},

            # Interparty Elimination Accounts - Exit / Terminal Value
            "Gain on Asset Disposal - Interparty Elimination": {"type": "Revenue", "category": "Other Income"},
            "Loss on Asset Disposal - Interparty Elimination": {"type": "Expense", "category": "Other Expenses"},

            # Interparty Elimination Accounts - DevCo Sales
            "Developed Unit Sales Revenue - Interparty Elimination": {"type": "Revenue", "category": "Operating Revenue"},
            "Cost of Developed Unit Sales - Interparty Elimination": {"type": "Expense", "category": "Cost of Sales"},
            "CWIP - Developed Units - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "Serviced Land Assets - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},

            # Interparty Elimination Accounts
            "Cash and Cash Equivalents - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "Accounts Receivable - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "Escrow Restricted Cash - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "CWIP - Serviced Land - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "Land Assets - Interparty Elimination": {"type": "Asset", "category": "Non-Current Assets"},
            "Investment Property - Interparty Elimination": {"type": "Asset", "category": "Non-Current Assets"},
            "Advances for Land - Interparty Elimination": {"type": "Asset", "category": "Current Assets"},
            "Accounts Payable - Interparty Elimination": {"type": "Liability", "category": "Current Liabilities"},
            "Unearned Revenue - Interparty Elimination": {"type": "Liability", "category": "Current Liabilities"},
            "Land Sales Revenue - Interparty Elimination": {"type": "Revenue", "category": "Operating Revenue"},
            "Cost of Land Sales - Interparty Elimination": {"type": "Expense", "category": "Cost of Sales"},
            "Retained Earnings - Interparty Elimination": {"type": "Equity", "category": "Shareholders Equity"},
        }

        # --------------------------------------------------------------------
        # Balance Sheet Line Items Structure
        # --------------------------------------------------------------------
        _balance_sheet_structure = {
            "Assets": {
                "Current Assets": [
                    "Cash and Cash Equivalents",
                    "Accounts Receivable",
                    "Advances for Land",
                    "Advance to Contractor",
                    "Escrow Restricted Cash",
                    "Restricted Cash - Sinking Fund",
                    "CWIP - Serviced Land",
                    "CWIP - Developed Units",
                ],
                "Non-Current Assets": [
                    "Land Assets",
                    "Serviced Land Assets",
                    "Investment Property",
                    "Accumulated Depreciation",
                    "Investments in Associates",
                ],
                "Interparty Eliminations": [
                    "Cash and Cash Equivalents - Interparty Elimination",
                    "Accounts Receivable - Interparty Elimination",
                    "Escrow Restricted Cash - Interparty Elimination",
                    "CWIP - Serviced Land - Interparty Elimination",
                    "CWIP - Developed Units - Interparty Elimination",
                    "Land Assets - Interparty Elimination",
                    "Serviced Land Assets - Interparty Elimination",
                    "Advances for Land - Interparty Elimination",
                    "Investment Property - Interparty Elimination",
                ],
            },
            "Liabilities": {
                "Current Liabilities": [
                    "Accounts Payable",
                    "Unearned Revenue",
                    "Debt - Revolver",
                ],
                "Non-Current Liabilities": [
                    "Debt - Term Loan",
                    "Debt - Other",
                ],
                "Interparty Eliminations": [
                    "Unearned Revenue - Interparty Elimination",
                    "Accounts Payable - Interparty Elimination",
                ],
            },
            "Equity": {
                "Shareholders Equity": [
                    "Share Capital",
                    "Retained Earnings",
                ],
                "Interparty Eliminations": [
                    "Retained Earnings - Interparty Elimination",
                ],
            },
        }

        # --------------------------------------------------------------------
        # Income Statement Line Items Structure
        # --------------------------------------------------------------------
        _income_statement_structure = {
            "Revenue": {
                "Operating Revenue": [
                    "Land Sales Revenue",
                    "Asset Sales Revenue",
                    "Land Lease Revenue",
                    "Lease Revenue - Base Rent",
                    "Lease Revenue - Turnover Rent",
                    "Lease Revenue - Service Charge",
                    "Hospitality - Room Revenue",
                    "Hospitality - F&B Revenue",
                    "Hospitality - OOD Revenue",
                    "Hospitality - Other Operating Income",
                    "Parking Revenue",
                ],
                "Other Income": [
                    "Government Subsidies Income",
                    "PA Recovery Income",
                    "Community Operations Recovery",
                    "Other Operating Income",
                    "Gain on Asset Disposal",
                ],
            },
            "Gross Profit": {
                "Subtotals": [
                    "Total Revenue",
                    "Gross Profit",
                ],
            },
            "Cost of Sales": {
                "Direct Costs": [
                    "Cost of Land Sales",
                    "Cost of Asset Sales",
                    "Cost of Lease Revenue",
                ],
            },
            "Operating Expenses": {
                "Property Operating Expenses": [
                    "Land Lease Operating Expenses",
                    "DLP Insurance Expense",
                    "Pre Operating Expenses",
                    "Utilities Expense",
                    "Facility Management Expense",
                    "Administration Expense",
                    "Insurance Expense",
                    "Other Operating Expenses",
                    "Bad Debt Expense",
                    "Void Period Expense",
                    "Sinking Fund Expense",
                    "Maintenance Capex Expense",
                    "Parking Expense",
                    "Asset Management Expense",
                ],
                "Sales and Marketing Expenses": [
                    "Sales and Marketing Expense",
                    "Leasing Commissions Expense",
                ],
                "Corporate Overheads": [
                    "Salaries Expense",
                    "IT Services Expense",
                    "Office Rent and Utilities Expense",
                    "Professional Services Expense",
                    "Marketing Overhead Expense",
                    "Sales Cost Overhead Expense",
                    "Additional Overhead Expense",
                ],
                "Community Operations": [
                    "Community Operations Expense",
                ],
                "Hospitality Departmental Expenses": [
                    "Hospitality Departmental Expenses - Room",
                    "Hospitality Departmental Expenses - F&B",
                    "Hospitality Departmental Expenses - OOD",
                    "Hospitality Departmental Expenses - Other",
                ],
                "Hospitality Undistributed Expenses": [
                    "Hospitality Undistributed Expenses - Admin",
                    "Hospitality Undistributed Expenses - Sales & Marketing",
                    "Hospitality Undistributed Expenses - IT",
                    "Hospitality Undistributed Expenses - Utilities",
                ],
                "Hospitality Non-Operating I&E": [
                    "Hospitality Non-Operating Expenses",
                    "Hospitality Non-Operating Income",
                ],
            },
            "EBITDA": {
                "Subtotals": [
                    "Total Operating Expenses",
                    "EBITDA",
                ],
            },
            "Depreciation and Amortization": {
                "D&A": [
                    "Depreciation Expense",
                ],
            },
            "EBIT": {
                "Subtotals": [
                    "EBIT",
                ],
            },
            "Finance Costs": {
                "Interest Expenses": [
                    "Interest Expense - Term Loan",
                    "Interest Expense - Revolver",
                    "Interest Expense - Other",
                    "Debt Fees Expense",
                ],
            },
            "EBT": {
                "Subtotals": [
                    "Total Finance Costs",
                    "EBT",
                ],
            },
            "Other Expenses": {
                "Non-Operating Expenses": [
                    "Other Operating Expense",
                    "Loss on Asset Disposal",
                ],
            },
            "Interparty Eliminations": {
                "Revenue Eliminations": [
                    "Land Sales Revenue - Interparty Elimination",
                    "Gain on Asset Disposal - Interparty Elimination",
                    "Asset Sales Revenue - Interparty Elimination",
                ],
                "Cost Eliminations": [
                    "Cost of Land Sales - Interparty Elimination",
                    "Loss on Asset Disposal - Interparty Elimination",
                    "Cost of Asset Sales - Interparty Elimination",
                ],
            },
            "Net Income": {
                "Subtotals": [
                    "Net Income",
                ],
            },
        }

        fn_record_timing(_timing_ctx, "PHASE 7: Financial Statement Structures")

        # ====================================================================
        # PHASE 8: INITIALIZE ACCOUNTS AND FINANCIAL STATEMENTS
        # ====================================================================

        _period_ends = (
            pd.to_datetime(master_timeline_df.loc["Period End"]).dt.normalize()
            if master_timeline_df is not None and "Period End" in master_timeline_df.index
            else pd.Series()
        )

        _all_accounts = fn_create_all_accounts(
            account_names_dict=_account_names_dict,
            period_ends=_period_ends,
        )

        _financial_statements = fn_create_all_financial_statements(
            balance_sheet_structure=_balance_sheet_structure,
            income_statement_structure=_income_statement_structure,
            cashflow_structure=_consolidated_structure,
            period_ends=_period_ends,
        )
        _financial_statements["__enable_financial_statement_trace__"] = _enable_financial_statement_trace

        _accounting_journal: List[Dict[str, Any]] = []

        # Pre-compute index maps for the matrix-based flush path.
        _index_maps = fn_build_flush_index_maps(
            accounts=_all_accounts,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
        )

        fn_record_timing(_timing_ctx, "PHASE 8: Initialize Accounts")

        # ====================================================================
        # PHASE 9: (RESERVED FOR CALCULATION LOGIC)
        # ====================================================================
        # This phase will contain the main calculation logic for:
        # - Processing DevCo cashflows
        # - Processing AssetCo cashflows
        # - Intercompany eliminations
        # - Journal entry recording
        # ====================================================================

        # --------------------------------------------------------------------
        # 9.0 Build DevCo Period End Mapping
        # --------------------------------------------------------------------
        # DevCo cashflows have numeric columns (0, 1, 2, ...) that need to be
        # mapped to period end dates for recording in accounts/statements.
        # --------------------------------------------------------------------
        devco_timeline_df = fn_json_dict_to_dataframe(_devco_timeline) if _devco_timeline else None
        _devco_period_ends_series = (
            pd.to_datetime(devco_timeline_df.loc["Period End"]).dt.normalize()
            if devco_timeline_df is not None and "Period End" in devco_timeline_df.index
            else pd.Series()
        )
        # Create mapping: column index (int or str) -> period end date string
        # Note: Use strftime to match the format used in account/statement columns ('YYYY-MM-DD')
        _devco_col_to_period: Dict[Any, str] = {}
        for col_idx, period_end in _devco_period_ends_series.items():
            _devco_col_to_period[col_idx] = period_end.strftime('%Y-%m-%d')

        fn_record_timing(_timing_ctx, "PHASE 9.0: Build DevCo Period Mapping")

        # --------------------------------------------------------------------
        # 9.0B Apply Asset Filter Mode
        # --------------------------------------------------------------------
        # If _ASSET_FILTER_MODE is a specific asset ID (not "Consolidated"),
        # null out all other asset UIDs so entry loops only process that asset.
        # Also set _is_single_asset_mode flag for later gating logic.
        # --------------------------------------------------------------------
        _asset_filter_mode_key = _ASSET_FILTER_MODE.strip().lower()
        _is_synthetic_mode = _asset_filter_mode_key == "synthetic"
        _is_single_asset_mode = (
            _asset_filter_mode_key != "consolidated"
            and _ASSET_FILTER_MODE.strip() != ""
        )

        if _is_single_asset_mode and _asset_unique_identifier is not None and not _asset_unique_identifier.empty:
            if _is_synthetic_mode:
                _synthetic_asset_ids = (
                    payload.get("_synthetic_asset_ids", []) if isinstance(payload, dict) else []
                )
                _synthetic_asset_ids_set = {
                    str(_aid).strip() for _aid in _synthetic_asset_ids if str(_aid).strip() != ""
                }

                if not _synthetic_asset_ids_set:
                    print(
                        "WARNING: Synthetic asset filter selected but no synthetic asset IDs "
                        "were supplied. Returning all-zero output."
                    )
                    _asset_unique_identifier = _asset_unique_identifier.where(
                        pd.Series(False, index=_asset_unique_identifier.index), other=None
                    )
                else:
                    _asset_match_mask = _asset_unique_identifier.astype(str).str.strip().isin(_synthetic_asset_ids_set)

                    if not _asset_match_mask.any():
                        print(
                            "WARNING: Synthetic asset filter IDs were not found in "
                            f"asset_unique_identifier. IDs: {sorted(_synthetic_asset_ids_set)}. "
                            "Returning all-zero output."
                        )
                        _asset_unique_identifier = _asset_unique_identifier.where(
                            pd.Series(False, index=_asset_unique_identifier.index), other=None
                        )
                    else:
                        # Null out non-selected assets so all entry loops skip them.
                        _asset_unique_identifier = _asset_unique_identifier.where(_asset_match_mask, other=None)
                        print(
                            "Asset filter mode: processing Synthetic asset set "
                            f"({int(_asset_match_mask.sum())} row(s) matched)."
                        )
            else:
                _selected_asset_id = _ASSET_FILTER_MODE.strip()
                _asset_match_mask = _asset_unique_identifier.astype(str).str.strip() == _selected_asset_id

                if not _asset_match_mask.any():
                    print(
                        f"WARNING: Asset filter '{_selected_asset_id}' not found in "
                        f"asset_unique_identifier. Available: {_asset_unique_identifier.tolist()}. "
                        "Returning all-zero output."
                    )
                    _asset_unique_identifier = _asset_unique_identifier.where(
                        pd.Series(False, index=_asset_unique_identifier.index), other=None
                    )
                else:
                    # Null out non-matching assets so all entry loops skip them.
                    _asset_unique_identifier = _asset_unique_identifier.where(_asset_match_mask, other=None)
                    print(
                        f"Asset filter mode: processing only asset '{_selected_asset_id}' "
                        f"({int(_asset_match_mask.sum())} row(s) matched)."
                    )
        elif _is_single_asset_mode and _is_synthetic_mode:
            print(
                "WARNING: Synthetic asset filter selected but asset_unique_identifier is "
                "missing or empty. Returning all-zero output."
            )

        
        # --------------------------------------------------------------------
        # 9.1 Process DevCo Serviced Land Acquisition Entries
        # --------------------------------------------------------------------

        _devco_land_acquisition_flag = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Land Acquisition Flag",
            source_name="DevCo Support Workings",
        )

        _devco_land_acquisition_cost = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Land Acquisition Cost",
            source_name="DevCo Support Workings",
        )

        _devco_land_acquisition = _devco_land_acquisition_flag.mul(
            _devco_land_acquisition_cost.sum(axis=1).values,
            axis=0
        )

        if _devco_land_acquisition_cost.empty:
            print("Serviced Land Acquisition is empty after summing cash payments and applying acquisition flag. Check source data and calculations.")    

        # Build LandCo total CWIP S-curve and revenue for interparty
        # progressive capitalization (mirrors LandCo's COS recognition).
        _landco_revenue_for_acq = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Land Sales Revenue",
            source_name="LandCo Support Workings",
        )
        _landco_infra_sc_for_acq = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Total Infrastructure Cost S-Curve",
            source_name="LandCo Support Workings",
        )
        _landco_cwip_sc_for_acq = _landco_infra_sc_for_acq.abs() if not _landco_infra_sc_for_acq.empty else pd.DataFrame()
        _landco_cwip_items_for_acq = [
            "Design Cost", "Permitting Cost", "Supervision Cost",
            "Project Management Cost", "Contingency Cost Payment",
            "Capitalized Salaries Expenses",
            "Capitalized IT Services Expenses",
            "Capitalized Office Rent and Utilities Expenses",
            "Capitalized Professional Services Expenses",
            "Capitalized Marketing Expenses",
            "Capitalized Sales Cost Expenses",
            "Capitalized Additional Expenses",
        ]
        _cwip_sum_for_acq: pd.DataFrame = pd.DataFrame()
        for _citem in _landco_cwip_items_for_acq:
            _cdf = fn_safe_extract_dataframe(_landco_cfi, _citem, "LandCo CFI")
            if not _cdf.empty:
                _cdf_abs = _cdf.abs()
                _cwip_sum_for_acq = (
                    _cwip_sum_for_acq.add(_cdf_abs, fill_value=0.0)
                    if not _cwip_sum_for_acq.empty
                    else _cdf_abs.copy()
                )
        if not _cwip_sum_for_acq.empty and not _landco_cwip_sc_for_acq.empty:
            _cwip_aligned_acq = _cwip_sum_for_acq.reindex(
                columns=_landco_cwip_sc_for_acq.columns, fill_value=0.0
            )
            _landco_cwip_sc_for_acq = pd.DataFrame(
                _landco_cwip_sc_for_acq.values + _cwip_aligned_acq.values,
                index=_landco_cwip_sc_for_acq.index,
                columns=_landco_cwip_sc_for_acq.columns,
            )

        _devco_acquisition_counterparty = (
            _interparty_mapping["DevCo_Acquisition_Counterparty"]
            if not _interparty_mapping.empty and "DevCo_Acquisition_Counterparty" in _interparty_mapping.columns
            else pd.Series()
        )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_land_acquisition_entries(
            land_acquisition_df=_devco_land_acquisition,
            land_acquisition_cost_cash_payment_df=_devco_land_acquisition_cost,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            cashflow_line_item="Serviced Land Acquisition Cost",
            reference_prefix="DC-LA",
            acquisition_counterparty=_devco_acquisition_counterparty,
            s_curve_df=_landco_cwip_sc_for_acq,
            revenue_df=_landco_revenue_for_acq,
        )

        fn_record_timing(_timing_ctx, "PHASE 9.1A: Serviced Land Acquisition Cash Entries")

        # --------------------------------------------------------------------
        # 9.1C Process DevCo Acquisition Transaction Cost Entries (Direct Cash)
        # Entry: Dr Serviced Land Assets / Cr Cash and Cash Equivalents
        # --------------------------------------------------------------------
        _devco_acquisition_transaction_cost_items = [
            ("Legal Cost", "LEGAL"),
            ("Agency Cost", "AGENCY"),
            ("Technical Cost", "TECH"),
            ("Valuation Cost", "VALUATION"),
            ("Due Diligence Cost", "DUEDIL"),
        ]

        _txn_cost_batches = []
        for _txn_cost_line_item, _txn_cost_ref in _devco_acquisition_transaction_cost_items:
            _txn_cost_df = fn_safe_extract_dataframe(
                source_dict=_devco_cfi,
                key=_txn_cost_line_item,
                source_name="DevCo Cashflow from Investments",
            )

            if _txn_cost_df.empty:
                print(
                    "DevCo Acquisition Transaction Cost line item not found or empty in DevCo CFI: "
                    f"'{_txn_cost_line_item}'"
                )
                continue

            _batch = fn_prepare_direct_cash_matrix_batch(
                source_df=_txn_cost_df,
                col_to_period=_devco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account="Serviced Land Assets",
                credit_account="Cash and Cash Equivalents",
                cashflow_line_item=_txn_cost_line_item,
                line_item_name=f"Serviced Land Acquisition Transaction Cost - {_txn_cost_line_item}",
                reference_prefix=f"DC-LATC-{_txn_cost_ref}",
                index_maps=_index_maps,
                normalize_negative_to_abs=True,
            )
            if _batch is not None:
                _txn_cost_batches.append(_batch)

        if _txn_cost_batches:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_matrix_entries_multi(
                entry_batches=_txn_cost_batches,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                index_maps=_index_maps,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1C: Serviced Land Acquisition Transaction Cost Entries")

        # --------------------------------------------------------------------
        # 9.1D Process DevCo Development and Capitalized Cost Entries (Direct Cash)
        # Entry: Dr CWIP - Developed Units / Cr Cash and Cash Equivalents
        # --------------------------------------------------------------------
        _devco_cwip_direct_cash_items = [
            ("Design Cost", "Design Cost", "DESIGN"),
            ("Permitting Cost", "Permitting Cost", "PERMIT"),
            ("Supervision Cost", "Supervision Cost", "SUPERV"),
            ("Project Management Cost", "Project Management Cost", "PM"),
            ("Contingency Cost Payment", "Contingency Cost Payment", "CONT"),
            ("Public Amenity Cost", "Public Amenity Cost", "PA"),
            ("CEC Cost", "CEC Cost", "CEC"),
            ("Canal Cost", "Canal Cost", "CANAL"),
            ("Capitalized Salaries", "Capitalized Salaries Expenses", "CAPSAL"),
            ("Capitalized IT Services", "Capitalized IT Services Expenses", "CAPIT"),
            ("Capitalized Office Rent & Utilities", "Capitalized Office Rent and Utilities Expenses", "CAPRENT"),
            ("Capitalized Professional Services", "Capitalized Professional Services Expenses", "CAPPROF"),
            ("Capitalized Marketing (COH)", "Capitalized Marketing Expenses", "CAPMKT"),
            ("Capitalized Sales Cost (COH)", "Capitalized Sales Cost Expenses", "CAPSALES"),
            ("Capitalized Additional Expenses", "Capitalized Additional Expenses", "CAPADD"),
        ]

        _cwip_direct_cash_sum: pd.DataFrame = pd.DataFrame()  # accumulates abs CWIP cost DFs for total CWIP S-curve

        _cwip_batches = []
        for _cwip_source_line_item, _cwip_cashflow_line_item, _cwip_ref in _devco_cwip_direct_cash_items:
            _cwip_df = fn_safe_extract_dataframe(
                source_dict=_devco_cfi,
                key=_cwip_source_line_item,
                source_name="DevCo Cashflow from Investments",
            )

            if abs(_cwip_df.sum().sum()) <= 10e-6:
                continue

            if _cwip_df.empty:
                print(
                    "CWIP direct-cash line item not found or empty in DevCo CFI: "
                    f"'{_cwip_source_line_item}'"
                )
                continue

            # Accumulate absolute cost amounts for total CWIP S-curve.
            _cwip_df_abs = _cwip_df.abs()
            _cwip_direct_cash_sum = (
                _cwip_direct_cash_sum.add(_cwip_df_abs, fill_value=0.0)
                if not _cwip_direct_cash_sum.empty
                else _cwip_df_abs.copy()
            )

            _batch = fn_prepare_direct_cash_matrix_batch(
                source_df=_cwip_df,
                col_to_period=_devco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account="CWIP - Developed Units",
                credit_account="Cash and Cash Equivalents",
                cashflow_line_item=_cwip_cashflow_line_item,
                line_item_name=f"CWIP Direct Cash - {_cwip_source_line_item}",
                reference_prefix=f"DC-CWIP-{_cwip_ref}",
                index_maps=_index_maps,
                normalize_negative_to_abs=True,
            )
            if _batch is not None:
                _cwip_batches.append(_batch)

        if _cwip_batches:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_matrix_entries_multi(
                entry_batches=_cwip_batches,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                index_maps=_index_maps,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1D: CWIP Direct-Cash Cost Entries")

        # --------------------------------------------------------------------
        # 9.1E Process DevCo CFO Operating Entries (Direct Cash)
        # --------------------------------------------------------------------
        _devco_cfo_journal_mappings = [
            (
                "Escrow Setup Fees",                     # Key in CFO dict
                "ESCFEE",                                # Reference code for journal entry
                "Other Operating Expenses",              # Debit account
                "Cash and Cash Equivalents",             # Credit account
                "Escrow Setup Fees",                     # Line item label for journal entry description and potential IS mapping
            ),
            (
                "Sales Cost",
                "SALESCOST",
                "Sales and Marketing Expense",
                "Cash and Cash Equivalents",
                "Sales Cost",
            ),
            (
                "Marketing Cost",
                "MARKETINGCOST",
                "Sales and Marketing Expense",
                "Cash and Cash Equivalents",
                "Marketing Cost",
            ),
            (
                "DLP Insurance",
                "DLPI",
                "DLP Insurance Expense",
                "Cash and Cash Equivalents",
                "DLP Insurance",
            ),
            (
                "Void Period Opex",
                "VOIDOPEX",
                "Void Period Expense",
                "Cash and Cash Equivalents",
                "Void Period Opex",
            ),
            (
                "Other Income 1",
                "OTHINC1",
                "Cash and Cash Equivalents",
                "Other Operating Income",
                "Other Income 1",
            ),
            (
                "Other Income 2",
                "OTHINC2",
                "Cash and Cash Equivalents",
                "Other Operating Income",
                "Other Income 2",
            ),
            (
                "Government Subsidies",
                "GOVSUB",
                "Cash and Cash Equivalents",
                "Government Subsidies Income",
                "Government Subsidies",
            ),
            (
                "PA Recovery",
                "PARECOV",
                "Cash and Cash Equivalents",
                "PA Recovery Income",
                "PA Recovery",
            ),
            (
                "Other Expense 1",
                "OTHEXP1",
                "Other Operating Expenses",
                "Cash and Cash Equivalents",
                "Other Expense 1",
            ),
            (
                "Other Expense 2",
                "OTHEXP2",
                "Other Operating Expenses",
                "Cash and Cash Equivalents",
                "Other Expense 2",
            ),
            (
                "Other Expense 3",
                "OTHEXP3",
                "Other Operating Expenses",
                "Cash and Cash Equivalents",
                "Other Expense 3",
            ),
            (
                "Salaries Expenses",
                "OHSAL",
                "Salaries Expense",
                "Cash and Cash Equivalents",
                "Salaries Expenses",
            ),
            (
                "IT Services Expenses",
                "OHIT",
                "IT Services Expense",
                "Cash and Cash Equivalents",
                "IT Services Expenses",
            ),
            (
                "Office Rent & Utilities Expenses",
                "OHRENT",
                "Office Rent and Utilities Expense",
                "Cash and Cash Equivalents",
                "Office Rent and Utilities Expenses",
            ),
            (
                "Professional Services Expenses",
                "OHPROF",
                "Professional Services Expense",
                "Cash and Cash Equivalents",
                "Professional Services Expenses",
            ),
            (
                "Marketing Expenses (COH)",
                "OHMKT",
                "Marketing Overhead Expense",
                "Cash and Cash Equivalents",
                "Marketing Expenses (COH)",
            ),
            (
                "Sales Cost Expenses (COH)",
                "OHSALES",
                "Sales Cost Overhead Expense",
                "Cash and Cash Equivalents",
                "Sales Cost Expenses (COH)",
            ),
            (
                "Additional Expenses",
                "OHADD",
                "Additional Overhead Expense",
                "Cash and Cash Equivalents",
                "Additional Expenses",
            ),
        ]

        _devco_cfo_cashflow_line_item_overrides = {
            "Office Rent & Utilities Expenses": "Office Rent and Utilities Expenses",
            "Marketing Expenses (COH)": "Marketing Expenses",
            "Sales Cost Expenses (COH)": "Sales Cost Expenses",
        }

        _devco_cfo_income_statement_line_item_overrides = {
            "Other Operating Expenses": "Other Operating Expense",
        }

        _cfo_batches = []
        for (
            _cfo_line_item,
            _cfo_ref,
            _cfo_debit_account,
            _cfo_credit_account,
            _cfo_line_label,
        ) in _devco_cfo_journal_mappings:
            _cfo_line_df = fn_safe_extract_dataframe(
                source_dict=_devco_cfo,
                key=_cfo_line_item,
                source_name="DevCo Cashflow from Operations",
            )

            if _cfo_line_df.empty:
                print(
                    "DevCo CFO line item not found or empty for journal posting: "
                    f"'{_cfo_line_item}'"
                )
                continue

            if abs(_cfo_line_df.sum().sum()) <= 10e-6:  # Threshold to treat as zero considering potential floating point issues
                continue

            # Derive IS line item: Expense accounts ? debit name, Revenue accounts ? credit name.
            _cfo_is_line_item: Optional[str] = None
            _debit_acct_type = _account_names_dict.get(_cfo_debit_account, {}).get("type")
            _credit_acct_type = _account_names_dict.get(_cfo_credit_account, {}).get("type")
            if _debit_acct_type == "Expense":
                _cfo_is_line_item = _devco_cfo_income_statement_line_item_overrides.get(
                    _cfo_debit_account,
                    _cfo_debit_account,
                )
            elif _credit_acct_type == "Revenue":
                _cfo_is_line_item = _cfo_credit_account

            _cfo_cashflow_line_item = _devco_cfo_cashflow_line_item_overrides.get(
                _cfo_line_item,
                _cfo_line_item,
            )

            _batch = fn_prepare_direct_cash_matrix_batch(
                source_df=_cfo_line_df,
                col_to_period=_devco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account=_cfo_debit_account,
                credit_account=_cfo_credit_account,
                cashflow_line_item=_cfo_cashflow_line_item,
                line_item_name=f"DevCo CFO Journal - {_cfo_line_label}",
                reference_prefix=f"DC-CFO-{_cfo_ref}",
                index_maps=_index_maps,
                normalize_negative_to_abs=True,
                income_statement_line_item=_cfo_is_line_item,
            )
            if _batch is not None:
                _cfo_batches.append(_batch)

        if _cfo_batches:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_matrix_entries_multi(
                entry_batches=_cfo_batches,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                index_maps=_index_maps,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1E: DevCo CFO Operating Entries")

        # --------------------------------------------------------------------
        # 9.2 Process DevCo Vertical Construction Entries
        # --------------------------------------------------------------------
        _devco_vertical_construction_progress = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Phased Vertical Amount",
            source_name="DevCo Support Workings",
        )
        _devco_vertical_construction_payment = fn_safe_extract_dataframe(
            source_dict=_devco_cfi,
            key="Vertical Construction Cost",
            source_name="DevCo Cashflow from Investments",
        )

        if _devco_vertical_construction_progress.sum().sum() == 0.0:
            print(
                "Vertical Construction progress data is empty or zero. Check source data and keys."
            )
        elif _devco_vertical_construction_payment.sum().sum() == 0.0:
            print(
                "Vertical Construction payment data is empty or zero. Check source data and keys."
            )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_vertical_construction_entries(
            vertical_construction_progress_df=_devco_vertical_construction_progress,
            vertical_construction_payment_df=_devco_vertical_construction_payment,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            cashflow_line_item="Vertical Construction Cost",
            reference_prefix="DC-VC",
        )

        fn_record_timing(_timing_ctx, "PHASE 9.2: Vertical Construction Entries")

        # --------------------------------------------------------------------
        # 9.3 Process DevCo Developed Unit Sales Entries
        # --------------------------------------------------------------------
        # Revenue recognition based on Vertical Construction S-Curve, cost
        # recognition proportional to the same S-curve, collections split
        # by escrow applicability, and escrow release entries.
        # --------------------------------------------------------------------

        _devco_developed_unit_sales_revenue = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Sales Revenue",
            source_name="DevCo Support Workings",
        )

        _devco_construction_s_curve = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Phased Vertical Amount",
            source_name="DevCo Support Workings",
        )

        _devco_on_plan_sales_collection = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="On-plan Sales Collection",
            source_name="DevCo Support Workings",
        )

        # Read from Support Workings (unfiltered) so interparty/AssetCo-exit assets
        # are included. The Escrow Schedule applies _devco_sales_keep_mask which
        # zeros out those assets before they reach the payload, causing missing
        # cashflow entries. The consolidation model handles interparty eliminations
        # independently, so it needs the full unfiltered values here.
        _devco_inflows_to_escrow = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Inflows to Escrow",
            source_name="DevCo Support Workings",
        )

        _devco_escrow_release = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Escrow Release and Payments",
            source_name="DevCo Support Workings",
        )

        _devco_escrow_applicability = fn_extract_assumptions(
            _devco_asset_assumptions,
            "Disposal",
            "escrow_applicability",
        )

        # Filter collections by escrow applicability.
        # Non-escrow assets: use On-plan Sales Collection, zero out escrow assets.
        # Escrow assets: use Inflows to Escrow, zero out non-escrow assets.
        _escrow_mask = (
            _devco_escrow_applicability.str.strip().str.lower().isin(["yes", "true", "1"])
            if isinstance(_devco_escrow_applicability, pd.Series) and not _devco_escrow_applicability.empty
            else pd.Series(dtype=bool)
        )

        # Business model gate: only "Land Sale" assets participate in sales entries.
        _developed_unit_sale_mask = (
            _devco_business_model.str.strip().str.lower().eq("roshn.developed")
            if isinstance(_devco_business_model, pd.Series) and not _devco_business_model.empty
            else pd.Series(dtype=bool)
        )

        def _zero_out_non_matching(df: pd.DataFrame, mask: pd.Series, keep: bool) -> pd.DataFrame:
            """Zero out rows where mask does (not) match keep flag."""
            if df.empty or mask.empty:
                return df
            out = df.copy()
            for idx_pos, flag in enumerate(mask):
                if (keep and not flag) or (not keep and flag):
                    if idx_pos < len(out):
                        out.iloc[idx_pos] = 0.0
            return out

        def _align_to_template_matrix(df: pd.DataFrame, template_df: pd.DataFrame) -> pd.DataFrame:
            """
            Align a source matrix to a template matrix, preserving values when
            row/column labels differ only by type (e.g., int vs str).
            """
            if not isinstance(template_df, pd.DataFrame) or template_df.empty:
                return pd.DataFrame()

            if not isinstance(df, pd.DataFrame) or df.empty:
                return pd.DataFrame(0.0, index=template_df.index, columns=template_df.columns)

            src = df.apply(pd.to_numeric, errors="coerce").fillna(0.0)

            # Fast path: when shape matches, align by position to avoid losing
            # values on label-type mismatches.
            if src.shape == template_df.shape:
                return pd.DataFrame(src.values, index=template_df.index, columns=template_df.columns)

            # Fallback: normalize labels and reindex by normalized labels.
            src_norm = src.copy()
            src_norm.index = src_norm.index.map(lambda x: str(x).strip())
            src_norm.columns = src_norm.columns.map(lambda x: str(x).strip())

            target_index_norm = template_df.index.map(lambda x: str(x).strip())
            target_columns_norm = template_df.columns.map(lambda x: str(x).strip())

            aligned_norm = src_norm.reindex(
                index=target_index_norm,
                columns=target_columns_norm,
                fill_value=0.0,
            ).fillna(0.0)

            return pd.DataFrame(
                aligned_norm.values,
                index=template_df.index,
                columns=template_df.columns,
            )

        # Zero out non-Land Sale rows from all sales source DFs.
        _devco_developed_unit_sales_revenue = _zero_out_non_matching(_devco_developed_unit_sales_revenue, _developed_unit_sale_mask, keep=True)
        _devco_construction_s_curve = _zero_out_non_matching(_devco_construction_s_curve, _developed_unit_sale_mask, keep=True)
        _devco_on_plan_sales_collection = _zero_out_non_matching(_devco_on_plan_sales_collection, _developed_unit_sale_mask, keep=True)
        _devco_inflows_to_escrow = _zero_out_non_matching(_devco_inflows_to_escrow, _developed_unit_sale_mask, keep=True)
        _devco_escrow_release = _zero_out_non_matching(_devco_escrow_release, _developed_unit_sale_mask, keep=True)

        _collection_non_escrow = _devco_on_plan_sales_collection.copy() if not _devco_on_plan_sales_collection.empty else pd.DataFrame()
        _collection_escrow = _devco_inflows_to_escrow.copy() if not _devco_inflows_to_escrow.empty else pd.DataFrame()

        # Total Development Cost is used as a fallback CWIP-cost basis
        # when the CWIP S-curve cost basis is zero for an asset.
        _devco_total_dev_cost_du = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Total Development Cost",
            source_name="DevCo Support Workings",
        )
        _devco_total_dev_cost_du = _zero_out_non_matching(
            _devco_total_dev_cost_du,
            _developed_unit_sale_mask,
            keep=True,
        )

        # Build serviced-land debit basis from acquisition recognition timing
        # (interparty progressive vs non-interparty standard), then apply the
        # same business-model mask used by developed-unit sales.
        _devco_serviced_land_debit_basis = fn_build_serviced_land_acquisition_debit_basis(
            land_acquisition_df=_devco_land_acquisition,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            acquisition_counterparty=_devco_acquisition_counterparty,
            s_curve_df=_landco_cwip_sc_for_acq,
            revenue_df=_landco_revenue_for_acq,
        )

        _devco_serviced_land_debit_basis_du = _zero_out_non_matching(
            _devco_serviced_land_debit_basis,
            _developed_unit_sale_mask,
            keep=True,
        )

        # Zero out rows based on escrow flag.
        if not _collection_non_escrow.empty and not _escrow_mask.empty:
            for idx_pos, is_esc in enumerate(_escrow_mask):
                if is_esc and idx_pos < len(_collection_non_escrow):
                    _collection_non_escrow.iloc[idx_pos] = 0.0

        if not _collection_escrow.empty and not _escrow_mask.empty:
            for idx_pos, is_esc in enumerate(_escrow_mask):
                if not is_esc and idx_pos < len(_collection_escrow):
                    _collection_escrow.iloc[idx_pos] = 0.0

        # Build total CWIP S-curve (vertical construction + all direct CWIP costs)
        # so revenue recognition is based on all costs capitalized to CWIP,
        # not just vertical construction.
        _devco_total_cwip_s_curve = _devco_construction_s_curve.abs()
        if not _cwip_direct_cash_sum.empty:
            _cwip_direct_cash_masked = _zero_out_non_matching(
                _cwip_direct_cash_sum, _developed_unit_sale_mask, keep=True
            )
            # Reindex to construction S-curve columns to prevent duplicate
            # column labels from column-type mismatches (Support Workings vs CFI).
            _cwip_aligned = _cwip_direct_cash_masked.reindex(
                columns=_devco_total_cwip_s_curve.columns, fill_value=0.0
            )
            _devco_total_cwip_s_curve = pd.DataFrame(
                _devco_total_cwip_s_curve.values + _cwip_aligned.values,
                index=_devco_total_cwip_s_curve.index,
                columns=_devco_total_cwip_s_curve.columns,
            )

        # Revenue-recognition S-curve basis should include all costs
        # capitalized to the project: CWIP + Serviced Land Assets debit timing.
        _devco_total_recognition_s_curve = _devco_total_cwip_s_curve.copy()
        _sla_debit_aligned_du = pd.DataFrame()
        if isinstance(_devco_serviced_land_debit_basis_du, pd.DataFrame) and not _devco_serviced_land_debit_basis_du.empty:
            _sla_debit_aligned_du = _align_to_template_matrix(
                _devco_serviced_land_debit_basis_du.abs(),
                _devco_total_recognition_s_curve,
            )

            _devco_total_recognition_s_curve = pd.DataFrame(
                # _devco_total_recognition_s_curve.values + _sla_debit_aligned_du.values,
                _devco_total_recognition_s_curve.values,
                index=_devco_total_recognition_s_curve.index,
                columns=_devco_total_recognition_s_curve.columns,
            )

        # Build CWIP cost basis for COGS split/total cost.
        # If CWIP S-curve basis is zero for an asset but Total Development
        # Cost exists, use the latter for that asset as fallback.
        _devco_total_cwip_cost_basis = _devco_total_cwip_s_curve.copy()
        if isinstance(_devco_total_dev_cost_du, pd.DataFrame) and not _devco_total_dev_cost_du.empty:
            _devco_total_dev_cost_du_aligned = _devco_total_dev_cost_du.abs().reindex(
                index=_devco_total_cwip_cost_basis.index,
                columns=_devco_total_cwip_cost_basis.columns,
                fill_value=0.0,
            ).fillna(0.0)
            _cwip_row_sum = _devco_total_cwip_cost_basis.abs().sum(axis=1)
            _dev_row_sum = _devco_total_dev_cost_du_aligned.abs().sum(axis=1)
            _fallback_rows = (_cwip_row_sum <= 1e-9) & (_dev_row_sum > 1e-9)
            if _fallback_rows.any():
                _devco_total_cwip_cost_basis.loc[_fallback_rows, :] = _devco_total_dev_cost_du_aligned.loc[
                    _fallback_rows,
                    :,
                ].values

        # Build total cost incurred DF for COGS calculation.
        # Combines land acquisition cost + transaction costs (Serviced Land Assets)
        # with CWIP costs (vertical construction + direct cash items).
        _devco_total_cost_incurred = _devco_total_cwip_cost_basis.copy()
        # Add serviced-land acquisition component using the same debit timing
        # used by land acquisition postings.
        if not _sla_debit_aligned_du.empty:
            _devco_total_cost_incurred = pd.DataFrame(
                _devco_total_cost_incurred.values + _sla_debit_aligned_du.values,
                index=_devco_total_cost_incurred.index,
                columns=_devco_total_cost_incurred.columns,
            )
        # Add acquisition transaction costs (Legal, Agency, Technical, Valuation, Due Diligence).
        for _txn_cost_line_item, _txn_cost_ref in _devco_acquisition_transaction_cost_items:
            _txn_df = fn_safe_extract_dataframe(
                source_dict=_devco_cfi,
                key=_txn_cost_line_item,
                source_name="DevCo Cashflow from Investments",
            )
            if isinstance(_txn_df, pd.DataFrame) and not _txn_df.empty:
                _txn_aligned = _txn_df.abs().reindex(
                    index=_devco_total_cost_incurred.index,
                    columns=_devco_total_cost_incurred.columns,
                    fill_value=0.0,
                ).fillna(0.0)
                _devco_total_cost_incurred = pd.DataFrame(
                    _devco_total_cost_incurred.values + _txn_aligned.values,
                    index=_devco_total_cost_incurred.index,
                    columns=_devco_total_cost_incurred.columns,
                )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_developed_unit_sales_entries(
            revenue_df=_devco_developed_unit_sales_revenue,
            s_curve_df=_devco_total_recognition_s_curve,
            collection_non_escrow_df=_collection_non_escrow,
            collection_escrow_df=_collection_escrow,
            escrow_release_df=_devco_escrow_release,
            escrow_applicability=_devco_escrow_applicability,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            reference_prefix="DC-SALES",
            exit_counterparty=_interparty_mapping["DevCo_Exit_Counterparty"] if not _interparty_mapping.empty and "DevCo_Exit_Counterparty" in _interparty_mapping.columns else pd.Series(),
            cost_incurred_df=_devco_total_cost_incurred,
            cwip_cost_incurred_df=_devco_total_cwip_cost_basis,
        )

        fn_record_timing(_timing_ctx, "PHASE 9.3: Developed Unit Sales Entries")

        # --------------------------------------------------------------------
        # 9.3A Process DevCo Forward Sales Entries
        # --------------------------------------------------------------------
        # Forward Sales: Lump-sum cash at asset handover.
        # Revenue recognized and entire cost of sales recorded on receipt.
        # --------------------------------------------------------------------

        _forward_sales_mask = (
            _devco_business_model.str.strip().str.lower().eq("forward.sales")
            if isinstance(_devco_business_model, pd.Series) and not _devco_business_model.empty
            else pd.Series(dtype=bool)
        )

        _devco_forward_sales_cash = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Forward Sales Cash",
            source_name="DevCo Support Workings",
        )

        _devco_total_dev_cost = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Total Development Cost",
            source_name="DevCo Support Workings",
        )

        _devco_land_acquisition_cost_fs = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Land Acquisition Cost",
            source_name="DevCo Support Workings",
        )

        # Zero out non-forward-sales rows so only forward.sales assets are processed.
        _devco_forward_sales_cash = _zero_out_non_matching(_devco_forward_sales_cash, _forward_sales_mask, keep=True)
        _devco_total_dev_cost_fs = _zero_out_non_matching(_devco_total_dev_cost, _forward_sales_mask, keep=True)
        _devco_land_acquisition_cost_fs = _zero_out_non_matching(_devco_land_acquisition_cost_fs, _forward_sales_mask, keep=True)

        _all_accounts, _accounting_journal, _financial_statements = fn_process_forward_sales_entries(
            forward_sales_cash_df=_devco_forward_sales_cash,
            total_dev_cost_df=_devco_total_dev_cost_fs,
            land_acquisition_cost_df=_devco_land_acquisition_cost_fs,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            reference_prefix="DC-FSALES",
            exit_counterparty=_interparty_mapping["DevCo_Exit_Counterparty"] if not _interparty_mapping.empty and "DevCo_Exit_Counterparty" in _interparty_mapping.columns else pd.Series(),
        )

        fn_record_timing(_timing_ctx, "PHASE 9.3A: Forward Sales Entries")

        # --------------------------------------------------------------------
        # 9.3B Process DevCo Forward Funding Entries
        # --------------------------------------------------------------------
        # Forward Funding: Cash received progressively (construction S-curve).
        # Cash ? Unearned Revenue; revenue recognized on S-curve progress;
        # cost of sales proportional to revenue.
        # --------------------------------------------------------------------

        _forward_funding_mask = (
            _devco_business_model.str.strip().str.lower().eq("forward.funding")
            if isinstance(_devco_business_model, pd.Series) and not _devco_business_model.empty
            else pd.Series(dtype=bool)
        )

        _devco_forward_funding_cash = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Forward Funding Cash",
            source_name="DevCo Support Workings",
        )

        _devco_construction_s_curve_ff = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Phased Vertical Amount",
            source_name="DevCo Support Workings",
        )

        _devco_total_dev_cost_ff = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Total Development Cost",
            source_name="DevCo Support Workings",
        )

        _devco_land_acquisition_cost_ff = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Land Acquisition Cost",
            source_name="DevCo Support Workings",
        )

        # Zero out non-forward-funding rows.
        _devco_forward_funding_cash = _zero_out_non_matching(_devco_forward_funding_cash, _forward_funding_mask, keep=True)
        _devco_construction_s_curve_ff = _zero_out_non_matching(_devco_construction_s_curve_ff, _forward_funding_mask, keep=True)
        _devco_total_dev_cost_ff = _zero_out_non_matching(_devco_total_dev_cost_ff, _forward_funding_mask, keep=True)
        _devco_land_acquisition_cost_ff = _zero_out_non_matching(_devco_land_acquisition_cost_ff, _forward_funding_mask, keep=True)

        # Build total CWIP S-curve for forward funding (vertical construction + all direct CWIP costs).
        _devco_total_cwip_s_curve_ff = _devco_construction_s_curve_ff.abs()
        if not _cwip_direct_cash_sum.empty:
            _cwip_direct_cash_masked_ff = _zero_out_non_matching(
                _cwip_direct_cash_sum, _forward_funding_mask, keep=True
            )
            # Reindex to construction S-curve columns to prevent duplicate
            # column labels from column-type mismatches (Support Workings vs CFI).
            _cwip_aligned_ff = _cwip_direct_cash_masked_ff.reindex(
                columns=_devco_total_cwip_s_curve_ff.columns, fill_value=0.0
            )
            _devco_total_cwip_s_curve_ff = pd.DataFrame(
                _devco_total_cwip_s_curve_ff.values + _cwip_aligned_ff.values,
                index=_devco_total_cwip_s_curve_ff.index,
                columns=_devco_total_cwip_s_curve_ff.columns,
            )

        _devco_serviced_land_debit_basis_ff = _zero_out_non_matching(
            _devco_serviced_land_debit_basis,
            _forward_funding_mask,
            keep=True,
        )

        _devco_total_recognition_s_curve_ff = _devco_total_cwip_s_curve_ff.copy()
        if isinstance(_devco_serviced_land_debit_basis_ff, pd.DataFrame) and not _devco_serviced_land_debit_basis_ff.empty:
            _sla_debit_aligned_ff = _align_to_template_matrix(
                _devco_serviced_land_debit_basis_ff.abs(),
                _devco_total_recognition_s_curve_ff,
            )
            _devco_total_recognition_s_curve_ff = pd.DataFrame(
                _devco_total_recognition_s_curve_ff.values + _sla_debit_aligned_ff.values,
                index=_devco_total_recognition_s_curve_ff.index,
                columns=_devco_total_recognition_s_curve_ff.columns,
            )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_forward_funding_entries(
            forward_funding_cash_df=_devco_forward_funding_cash,
            s_curve_df=_devco_total_recognition_s_curve_ff,
            total_dev_cost_df=_devco_total_dev_cost_ff,
            land_acquisition_cost_df=_devco_land_acquisition_cost_ff,
            col_to_period=_devco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            reference_prefix="DC-FFUND",
            exit_counterparty=_interparty_mapping["DevCo_Exit_Counterparty"] if not _interparty_mapping.empty and "DevCo_Exit_Counterparty" in _interparty_mapping.columns else pd.Series(),
        )

        fn_record_timing(_timing_ctx, "PHASE 9.3B: Forward Funding Entries")

        # # --------------------------------------------------------------------
        # # 9.3C Reclassify CWIP - Developed Units at completion
        # # --------------------------------------------------------------------
        # # For ROSHN Developed assets, at the last non-zero CWIP entry period,
        # # transfer accumulated CWIP - Developed Units balance to Inventory:
        # #   Entry: Dr Inventory - Developed Units / Cr CWIP - Developed Units
        # # We determine the last non-zero CWIP period per asset by scanning
        # # all CFI items that flow into CWIP plus the vertical construction
        # # progress S-curve.
        # # --------------------------------------------------------------------

        # _cwip_reclass_devco_mask = (
        #     _devco_business_model.str.strip().str.lower().eq("roshn.developed")
        #     if isinstance(_devco_business_model, pd.Series) and not _devco_business_model.empty
        #     else pd.Series(dtype=bool)
        # )

        # if not _cwip_reclass_devco_mask.empty and _cwip_reclass_devco_mask.any():
        #     # Collect all source DataFrames that feed CWIP - Developed Units.
        #     _cwip_dc_source_keys = (
        #         [item[0] for item in _devco_cwip_direct_cash_items]
        #         + ["Phased Vertical Amount"]
        #     )
        #     _cwip_dc_source_dfs: List[pd.DataFrame] = []
        #     for _csk in _cwip_dc_source_keys:
        #         _csk_df = fn_safe_extract_dataframe(
        #             source_dict=_devco_cfi, key=_csk,
        #             source_name="DevCo CFI",
        #         )
        #         if _csk_df.empty:
        #             _csk_df = fn_safe_extract_dataframe(
        #                 source_dict=_devco_support_workings, key=_csk,
        #                 source_name="DevCo Support Workings",
        #             )
        #         if not _csk_df.empty:
        #             _cwip_dc_source_dfs.append(_csk_df)

        #     _period_cols_dc_reclass = list(_devco_col_to_period.keys())
        #     _reclass_dc_batch_entries: List[Dict[str, Any]] = []

        #     for _rc_row_pos in range(len(_cwip_reclass_devco_mask)):
        #         if not _cwip_reclass_devco_mask.iloc[_rc_row_pos]:
        #             continue

        #         # Determine asset UID.
        #         if _asset_unique_identifier is None or _rc_row_pos >= len(_asset_unique_identifier):
        #             continue
        #         _rc_uid = _asset_unique_identifier.iloc[_rc_row_pos]
        #         if _rc_uid is None or pd.isna(_rc_uid) or str(_rc_uid).strip() == "":
        #             continue

        #         # Find the last non-zero CWIP period for this asset across all sources.
        #         _last_cwip_col = None
        #         for _src_df in _cwip_dc_source_dfs:
        #             if _rc_row_pos >= len(_src_df):
        #                 continue
        #             _row_vals = pd.to_numeric(
        #                 _src_df.iloc[_rc_row_pos].reindex(_period_cols_dc_reclass),
        #                 errors="coerce",
        #             ).fillna(0.0)
        #             _nonzero_cols = [c for c in _period_cols_dc_reclass if abs(float(_row_vals.get(c, 0.0))) > 1e-2]
        #             if _nonzero_cols:
        #                 _candidate = _nonzero_cols[-1]
        #                 if _last_cwip_col is None:
        #                     _last_cwip_col = _candidate
        #                 else:
        #                     if _period_cols_dc_reclass.index(_candidate) > _period_cols_dc_reclass.index(_last_cwip_col):
        #                         _last_cwip_col = _candidate

        #         if _last_cwip_col is None:
        #             continue

        #         _reclass_period = _devco_col_to_period.get(_last_cwip_col)
        #         if _reclass_period is None:
        #             continue

        #         # Get CWIP - Developed Units closing balance for this period.
        #         _cwip_dev_acct = _all_accounts.get("CWIP - Developed Units")
        #         if _cwip_dev_acct is None or _cwip_dev_acct.empty:
        #             continue
        #         if _reclass_period not in _cwip_dev_acct.columns:
        #             continue

        #         _cwip_dev_bal = float(_cwip_dev_acct.loc["Closing Balance", _reclass_period])
        #         if _cwip_dev_bal < 0.01:
        #             continue
        #         _cwip_dev_bal = round(_cwip_dev_bal, 2)

        #         _reclass_dc_batch_entries.append({
        #             "debit_account": "Inventory - Developed Units",
        #             "credit_account": "CWIP - Developed Units",
        #             "amount": _cwip_dev_bal,
        #             "period": _reclass_period,
        #             "income_statement_line_item": None,
        #             "cashflow_line_item": None,
        #             "description": f"CWIP reclassification to Inventory - Developed Units - Asset {_rc_uid}",
        #             "reference": f"DC-CWIP-RECLASS-{_rc_row_pos}-{_last_cwip_col}",
        #         })

        #     if _reclass_dc_batch_entries:
        #         _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
        #             batch_entries=_reclass_dc_batch_entries,
        #             accounts=_all_accounts,
        #             journal=_accounting_journal,
        #             financial_statements=_financial_statements,
        #             account_names_dict=_account_names_dict,
        #         )

        fn_record_timing(_timing_ctx, "PHASE 9.3C: CWIP to Inventory Reclassification")

        # --------------------------------------------------------------------
        # 9.4 Process DevCo Debt & Financing Entries
        # --------------------------------------------------------------------
        # Uses DevCo financing data (4 facilities + equity):
        #   - Asset Term Loan (asset-level, from DevCo Support Workings)
        #   - Asset Revolver  (asset-level, from DevCo Support Workings)
        #   - Project Term Loan (project-level, from DevCo Support Workings)
        #   - Project Revolver  (project-level, from DevCo Support Workings)
        # All capitalized interest capitalizes to CWIP - Developed Units.
        #
        # NOTE: In filtered modes, only asset-level financing is posted.
        #       Project-level financing is ignored and balancing equity is
        #       derived from net cashflow. DevCo also includes asset-level
        #       equity in filtered mode.
        # --------------------------------------------------------------------

        if not _is_single_asset_mode:

            # --- Asset Term Loan (asset-level, from DevCo Support Workings) ---
            _dc_atl_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_atl_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_atl_principal_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Principal Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_balloon = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Balloon Payment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_interest_expensed = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Interest Payment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Arrangement Fees",
                source_name="DevCo Support Workings",
            )

            # --- Asset Revolver (asset-level, from DevCo Support Workings) ---
            _dc_arev_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_arev_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_arev_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Debt Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_arev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Arrangement Fees",
                source_name="DevCo Support Workings",
            )
            _dc_arev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Commitment Fees Payment",
                source_name="DevCo Support Workings",
            )

            # --- Project Term Loan (project-level, from DevCo Support Workings) ---
            _dc_ptl_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_ptl_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_ptl_principal_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Principal Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_ptl_balloon = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Balloon Payment",
                source_name="DevCo Support Workings",
            )
            _dc_ptl_interest_expensed = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Interest Payment",
                source_name="DevCo Support Workings",
            )
            _dc_ptl_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Term Loan - Arrangement Fees",
                source_name="DevCo Support Workings",
            )

            # --- Project Revolver (project-level, from DevCo Support Workings) ---
            _dc_prev_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Revolver - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_prev_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Revolver - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_prev_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Revolver - Debt Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_prev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Revolver - Arrangement Fees",
                source_name="DevCo Support Workings",
            )
            _dc_prev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Revolver - Commitment Fees Payment",
                source_name="DevCo Support Workings",
            )

            # --- Equity (from DevCo Support Workings) ---
            _dc_asset_equity = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Equity Injection",
                source_name="DevCo Support Workings",
            )
            _dc_project_equity = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Project Equity Infusion",
                source_name="DevCo Support Workings",
            )
            # Combine asset + project equity into a single DataFrame for the debt processor.
            _dc_equity_combined = pd.DataFrame()
            if not _dc_asset_equity.empty and not _dc_project_equity.empty:
                _dc_equity_combined = pd.concat([_dc_asset_equity, _dc_project_equity], ignore_index=True)
            elif not _dc_asset_equity.empty:
                _dc_equity_combined = _dc_asset_equity
            elif not _dc_project_equity.empty:
                _dc_equity_combined = _dc_project_equity

            _debt_facility_configs = [
                {
                    "name": "Asset Term Loan",
                    "type": "term_loan",
                    "loan_account": "Debt - Term Loan",
                    "interest_expense_account": "Interest Expense - Term Loan",
                    "cf_drawdown": "Term Loan - Debt Drawdown",
                    "cf_repayment": "Term Loan - Debt Repayment",
                    "cf_interest": "Term Loan - Interest Payments",
                    "cf_fees": "Term Loan - Debt Fees",
                    "ref_prefix": "DC-ATL",
                    "drawdown_df": _dc_atl_drawdown,
                    "cap_interest_df": _dc_atl_cap_interest,
                    "repayment_df": pd.DataFrame(),
                    "arrangement_fees_df": _dc_atl_arrangement_fees,
                    "commitment_fees_df": pd.DataFrame(),
                    "principal_repayment_df": _dc_atl_principal_repayment,
                    "balloon_df": _dc_atl_balloon,
                    "interest_expensed_df": _dc_atl_interest_expensed,
                    "valuation_fees_df": pd.DataFrame(),
                    "other_fees_df": pd.DataFrame(),
                },
                {
                    "name": "Asset Revolver",
                    "type": "revolver",
                    "loan_account": "Debt - Revolver",
                    "interest_expense_account": "Interest Expense - Revolver",
                    "cf_drawdown": "Revolver - Debt Drawdown",
                    "cf_repayment": "Revolver - Debt Repayment",
                    "cf_interest": "Revolver - Interest Payments",
                    "cf_fees": "Revolver - Debt Fees",
                    "ref_prefix": "DC-AREV",
                    "drawdown_df": _dc_arev_drawdown,
                    "cap_interest_df": _dc_arev_cap_interest,
                    "repayment_df": _dc_arev_repayment,
                    "arrangement_fees_df": _dc_arev_arrangement_fees,
                    "commitment_fees_df": _dc_arev_commitment_fees,
                },
                {
                    "name": "Project Term Loan",
                    "type": "term_loan",
                    "loan_account": "Debt - Term Loan",
                    "interest_expense_account": "Interest Expense - Term Loan",
                    "cf_drawdown": "Term Loan - Debt Drawdown",
                    "cf_repayment": "Term Loan - Debt Repayment",
                    "cf_interest": "Term Loan - Interest Payments",
                    "cf_fees": "Term Loan - Debt Fees",
                    "ref_prefix": "DC-PTL",
                    "drawdown_df": _dc_ptl_drawdown,
                    "cap_interest_df": _dc_ptl_cap_interest,
                    "repayment_df": pd.DataFrame(),
                    "arrangement_fees_df": _dc_ptl_arrangement_fees,
                    "commitment_fees_df": pd.DataFrame(),
                    "principal_repayment_df": _dc_ptl_principal_repayment,
                    "balloon_df": _dc_ptl_balloon,
                    "interest_expensed_df": _dc_ptl_interest_expensed,
                    "valuation_fees_df": pd.DataFrame(),
                    "other_fees_df": pd.DataFrame(),
                },
                {
                    "name": "Project Revolver",
                    "type": "revolver",
                    "loan_account": "Debt - Revolver",
                    "interest_expense_account": "Interest Expense - Revolver",
                    "cf_drawdown": "Revolver - Debt Drawdown",
                    "cf_repayment": "Revolver - Debt Repayment",
                    "cf_interest": "Revolver - Interest Payments",
                    "cf_fees": "Revolver - Debt Fees",
                    "ref_prefix": "DC-PREV",
                    "drawdown_df": _dc_prev_drawdown,
                    "cap_interest_df": _dc_prev_cap_interest,
                    "repayment_df": _dc_prev_repayment,
                    "arrangement_fees_df": _dc_prev_arrangement_fees,
                    "commitment_fees_df": _dc_prev_commitment_fees,
                },
            ]

            _all_accounts, _accounting_journal, _financial_statements = fn_process_devco_debt_entries(
                facility_configs=_debt_facility_configs,
                equity_infusion_df=_dc_equity_combined,
                col_to_period=_devco_col_to_period,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                reference_prefix="DC-DEBT",
                cwip_account="CWIP - Developed Units",
            )

        else:
            # ----------------------------------------------------------------
            # 9.4B Filtration Mode — Asset Financing + Balancing Equity
            # ----------------------------------------------------------------
            # In filtered modes (single-asset / synthetic):
            # - Keep asset-level financing entries (Asset Term Loan, Asset Revolver).
            # - Keep asset-level equity injections.
            # - Ignore project-level financing and project-level equity.
            # - Post balancing equity per period based on:
            #     Equity = -(CFO + CFI + Asset-Level Financing Cashflow)
            # ----------------------------------------------------------------
            print(
                "Filtration mode detected: applying asset-level financing "
                f"and asset-level equity only for asset filter '{_ASSET_FILTER_MODE}'."
            )

            # --- Asset Term Loan (asset-level, from DevCo Support Workings) ---
            _dc_atl_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_atl_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_atl_principal_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Principal Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_balloon = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Balloon Payment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_interest_expensed = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Interest Payment",
                source_name="DevCo Support Workings",
            )
            _dc_atl_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Term Loan - Arrangement Fees",
                source_name="DevCo Support Workings",
            )

            # --- Asset Revolver (asset-level, from DevCo Support Workings) ---
            _dc_arev_drawdown = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Debt Drawdown",
                source_name="DevCo Support Workings",
            )
            _dc_arev_cap_interest = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Capitalized Interest",
                source_name="DevCo Support Workings",
            )
            _dc_arev_repayment = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Debt Repayment",
                source_name="DevCo Support Workings",
            )
            _dc_arev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Arrangement Fees",
                source_name="DevCo Support Workings",
            )
            _dc_arev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Revolver - Commitment Fees Payment",
                source_name="DevCo Support Workings",
            )

            # --- Asset Equity (asset-level, from DevCo Support Workings) ---
            _dc_asset_equity = fn_safe_extract_dataframe(
                source_dict=_devco_support_workings,
                key="Asset Equity Injection",
                source_name="DevCo Support Workings",
            )

            def _mask_df_to_selected_assets(_df: pd.DataFrame) -> pd.DataFrame:
                if not isinstance(_df, pd.DataFrame) or _df.empty:
                    return _df

                _out = _df.copy()
                if not isinstance(_asset_unique_identifier, pd.Series) or _asset_unique_identifier.empty:
                    return _out

                _max_rows = min(len(_out), len(_asset_unique_identifier))
                for _row_pos in range(_max_rows):
                    _uid = _asset_unique_identifier.iloc[_row_pos]
                    if _uid is None or pd.isna(_uid) or str(_uid).strip() == "":
                        _out.iloc[_row_pos] = 0.0

                if len(_out) > _max_rows:
                    _out.iloc[_max_rows:] = 0.0

                return _out

            _dc_atl_drawdown = _mask_df_to_selected_assets(_dc_atl_drawdown)
            _dc_atl_cap_interest = _mask_df_to_selected_assets(_dc_atl_cap_interest)
            _dc_atl_principal_repayment = _mask_df_to_selected_assets(_dc_atl_principal_repayment)
            _dc_atl_balloon = _mask_df_to_selected_assets(_dc_atl_balloon)
            _dc_atl_interest_expensed = _mask_df_to_selected_assets(_dc_atl_interest_expensed)
            _dc_atl_arrangement_fees = _mask_df_to_selected_assets(_dc_atl_arrangement_fees)

            _dc_arev_drawdown = _mask_df_to_selected_assets(_dc_arev_drawdown)
            _dc_arev_cap_interest = _mask_df_to_selected_assets(_dc_arev_cap_interest)
            _dc_arev_repayment = _mask_df_to_selected_assets(_dc_arev_repayment)
            _dc_arev_arrangement_fees = _mask_df_to_selected_assets(_dc_arev_arrangement_fees)
            _dc_arev_commitment_fees = _mask_df_to_selected_assets(_dc_arev_commitment_fees)

            _dc_asset_equity = _mask_df_to_selected_assets(_dc_asset_equity)

            _debt_facility_configs_filtered = [
                {
                    "name": "Asset Term Loan",
                    "type": "term_loan",
                    "loan_account": "Debt - Term Loan",
                    "interest_expense_account": "Interest Expense - Term Loan",
                    "cf_drawdown": "Term Loan - Debt Drawdown",
                    "cf_repayment": "Term Loan - Debt Repayment",
                    "cf_interest": "Term Loan - Interest Payments",
                    "cf_fees": "Term Loan - Debt Fees",
                    "ref_prefix": "DC-ATL",
                    "drawdown_df": _dc_atl_drawdown,
                    "cap_interest_df": _dc_atl_cap_interest,
                    "repayment_df": pd.DataFrame(),
                    "arrangement_fees_df": _dc_atl_arrangement_fees,
                    "commitment_fees_df": pd.DataFrame(),
                    "principal_repayment_df": _dc_atl_principal_repayment,
                    "balloon_df": _dc_atl_balloon,
                    "interest_expensed_df": _dc_atl_interest_expensed,
                    "valuation_fees_df": pd.DataFrame(),
                    "other_fees_df": pd.DataFrame(),
                },
                {
                    "name": "Asset Revolver",
                    "type": "revolver",
                    "loan_account": "Debt - Revolver",
                    "interest_expense_account": "Interest Expense - Revolver",
                    "cf_drawdown": "Revolver - Debt Drawdown",
                    "cf_repayment": "Revolver - Debt Repayment",
                    "cf_interest": "Revolver - Interest Payments",
                    "cf_fees": "Revolver - Debt Fees",
                    "ref_prefix": "DC-AREV",
                    "drawdown_df": _dc_arev_drawdown,
                    "cap_interest_df": _dc_arev_cap_interest,
                    "repayment_df": _dc_arev_repayment,
                    "arrangement_fees_df": _dc_arev_arrangement_fees,
                    "commitment_fees_df": _dc_arev_commitment_fees,
                },
            ]

            # Ignore project-level financing and project-level equity in filtered mode.
            _all_accounts, _accounting_journal, _financial_statements = fn_process_devco_debt_entries(
                facility_configs=_debt_facility_configs_filtered,
                equity_infusion_df=_dc_asset_equity,
                col_to_period=_devco_col_to_period,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                reference_prefix="DC-DEBT-FILT",
                cwip_account="CWIP - Developed Units",
            )

            # Balancing equity uses net period cash impact after CFO/CFI and
            # asset-level financing/equity postings in filtered mode.
            _period_cash_net: Dict[str, float] = {}
            for _period_val in _devco_col_to_period.values():
                if _period_val is not None and _period_val not in _period_cash_net:
                    _period_cash_net[_period_val] = 0.0

            for _entry in _accounting_journal:
                if not isinstance(_entry, dict):
                    continue

                _period = _entry.get("period")
                if _period not in _period_cash_net:
                    continue

                _amount = float(_entry.get("amount", 0.0) or 0.0)
                _debit_account = _entry.get("debit_account")
                _credit_account = _entry.get("credit_account")

                if _debit_account == "Cash and Cash Equivalents" and _credit_account != "Cash and Cash Equivalents":
                    _period_cash_net[_period] += _amount
                elif _credit_account == "Cash and Cash Equivalents" and _debit_account != "Cash and Cash Equivalents":
                    _period_cash_net[_period] -= _amount

            _equity_balance_entries: List[Dict[str, Any]] = []
            for _period_col, _period_str in _devco_col_to_period.items():
                if _period_str is None:
                    continue

                _equity_amount = -float(_period_cash_net.get(_period_str, 0.0))
                if abs(_equity_amount) <= 1e-6:
                    continue

                if _equity_amount > 0.0:
                    # Equity raise: Dr Cash / Cr Share Capital
                    _equity_balance_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Share Capital",
                        "amount": _equity_amount,
                        "period": _period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": "Project and Asset Equity Contribution",
                        "description": "Balancing Equity Raise (Filtration Mode)",
                        "reference": f"DC-DEBT-FILT-BEQ-RAISE-{_period_col}",
                    })

            if _equity_balance_entries:
                _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                    batch_entries=_equity_balance_entries,
                    accounts=_all_accounts,
                    journal=_accounting_journal,
                    financial_statements=_financial_statements,
                    account_names_dict=_account_names_dict,
                )

        fn_record_timing(_timing_ctx, "PHASE 9.4: Debt & Financing Entries")

        # --------------------------------------------------------------------
        # 9.5 Period-End Closing Entries
        # --------------------------------------------------------------------
        # Standard period-end closing sequence:
        #   1. Close Revenues:  Dr Revenue,           Cr Profit & Loss
        #   2. Close Expenses:  Dr Profit & Loss,     Cr Expenses
        #   3. Transfer to Equity:
        #        If profit:  Dr Profit & Loss,  Cr Retained Earnings
        #        If loss:    Dr Retained Earnings, Cr Profit & Loss
        # After all three steps the Profit & Loss account nets to zero
        # each period and net income accumulates in Retained Earnings.
        # --------------------------------------------------------------------

        _pl_acct = _all_accounts.get("Profit & Loss")
        _re_acct = _all_accounts.get("Retained Earnings")

        if _pl_acct is not None and _re_acct is not None:
            _revenue_account_names = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Revenue"
            ]
            _expense_account_names = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Expense"
            ]
            _all_period_strs = _pl_acct.columns.tolist()
            _n_periods = len(_all_period_strs)
            _period_arr = np.array(_all_period_strs)

            # ------ Pre-compute IE net income — entity total (vectorized) ------
            _ie_revenue_names = [n for n in _revenue_account_names if n.endswith(" - Interparty Elimination")]
            _ie_expense_names = [n for n in _expense_account_names if n.endswith(" - Interparty Elimination")]
            _ie_rev_total = np.zeros(_n_periods, dtype=float)
            for _rn in _ie_revenue_names:
                _racct = _all_accounts.get(_rn)
                if _racct is not None and not _racct.empty:
                    _ie_rev_total += _racct.loc["Credit"].values.astype(float) - _racct.loc["Debit"].values.astype(float)
            _ie_exp_total = np.zeros(_n_periods, dtype=float)
            for _en in _ie_expense_names:
                _eacct = _all_accounts.get(_en)
                if _eacct is not None and not _eacct.empty:
                    _ie_exp_total += _eacct.loc["Debit"].values.astype(float) - _eacct.loc["Credit"].values.astype(float)
            _pre_closing_ie_net_arr = _ie_rev_total - _ie_exp_total

            # ------ Per-asset IE net income (from journal, for asset-level trace) ------
            _period_to_idx: Dict[str, int] = {_p: _i for _i, _p in enumerate(_all_period_strs)}
            _asset_ie_rev: Dict[str, np.ndarray] = {}
            _asset_ie_exp: Dict[str, np.ndarray] = {}
            for _je in _accounting_journal:
                _ref = str(_je.get("reference", ""))
                _amt = float(_je.get("amount", 0.0) or 0.0)
                _p_str = str(_je.get("period", ""))
                _p_idx = _period_to_idx.get(_p_str)
                if _p_idx is None or abs(_amt) < 1e-9:
                    continue
                if "-IPRE-" in _ref:
                    _parts = _ref.split("-IPRE-", 1)
                    if len(_parts) == 2:
                        _aid = _parts[1].split("-")[0]
                        if _aid not in _asset_ie_rev:
                            _asset_ie_rev[_aid] = np.zeros(_n_periods, dtype=float)
                        _asset_ie_rev[_aid][_p_idx] += _amt
                elif "-IPCE-" in _ref:
                    _parts = _ref.split("-IPCE-", 1)
                    if len(_parts) == 2:
                        _remaining = _parts[1]
                        if _remaining.startswith("SLA-"):
                            _aid = _remaining[4:].split("-")[0]
                        else:
                            _aid = _remaining.split("-")[0]
                        if _aid not in _asset_ie_exp:
                            _asset_ie_exp[_aid] = np.zeros(_n_periods, dtype=float)
                        _asset_ie_exp[_aid][_p_idx] += _amt
            _all_asset_ie_ids = sorted(set(_asset_ie_rev) | set(_asset_ie_exp))
            _asset_pre_closing_ie_net: Dict[str, np.ndarray] = {
                _aid: (
                    _asset_ie_rev.get(_aid, np.zeros(_n_periods, dtype=float))
                    - _asset_ie_exp.get(_aid, np.zeros(_n_periods, dtype=float))
                )
                for _aid in _all_asset_ie_ids
            }

            # ------ Build all closing entries in one batch ------
            _all_closing_entries: List[Dict[str, Any]] = []
            _pl_net_from_closing = np.zeros(_n_periods, dtype=float)

            # Step 1: Close Revenue accounts to P&L.
            # Normal direction: net credit (Credit > Debit) → Dr Revenue / Cr P&L.
            # Reversed direction: net debit (Debit > Credit, e.g. IE revenue eliminations)
            # → Dr P&L / Cr Revenue-IE. Both directions must be closed so that the
            # interparty IS effect flows through P&L into RE before Step 4 reclassifies
            # the IE portion from RE into RE-IE. Without the reversed close, Step 4's
            # Dr RE / Cr RE-IE entry reduces RE by the IE amount even though that amount
            # was never in RE, creating a BS imbalance equal to the IE net income.
            for _rev_name in _revenue_account_names:
                _rev_acct = _all_accounts.get(_rev_name)
                if _rev_acct is None or _rev_acct.empty:
                    continue
                _net = _rev_acct.loc["Credit"].values.astype(float) - _rev_acct.loc["Debit"].values.astype(float)
                _pos_mask = _net > 0
                if _pos_mask.any():
                    for _p, _a in zip(_period_arr[_pos_mask], _net[_pos_mask]):
                        _all_closing_entries.append({
                            "debit_account": _rev_name, "credit_account": "Profit & Loss",
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry: {_rev_name} to P&L",
                            "reference": "CLOSING-REV",
                        })
                    _pl_net_from_closing[_pos_mask] += _net[_pos_mask]
                _neg_mask = _net < 0
                if _neg_mask.any():
                    for _p, _a in zip(_period_arr[_neg_mask], np.abs(_net[_neg_mask])):
                        _all_closing_entries.append({
                            "debit_account": "Profit & Loss", "credit_account": _rev_name,
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry (reversed): P&L to {_rev_name}",
                            "reference": "CLOSING-REV-IE",
                        })
                    _pl_net_from_closing[_neg_mask] += _net[_neg_mask]

            # Step 2: Close Expense accounts to P&L.
            # Normal direction: net debit (Debit > Credit) → Dr P&L / Cr Expense.
            # Reversed direction: net credit (Credit > Debit, e.g. IE COGS eliminations)
            # → Dr Expense-IE / Cr P&L. Same rationale as Step 1 reversed handling.
            for _exp_name in _expense_account_names:
                _exp_acct = _all_accounts.get(_exp_name)
                if _exp_acct is None or _exp_acct.empty:
                    continue
                _net = _exp_acct.loc["Debit"].values.astype(float) - _exp_acct.loc["Credit"].values.astype(float)
                _pos_mask = _net > 0
                if _pos_mask.any():
                    for _p, _a in zip(_period_arr[_pos_mask], _net[_pos_mask]):
                        _all_closing_entries.append({
                            "debit_account": "Profit & Loss", "credit_account": _exp_name,
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry: P&L to {_exp_name}",
                            "reference": "CLOSING-EXP",
                        })
                    _pl_net_from_closing[_pos_mask] -= _net[_pos_mask]
                _neg_mask = _net < 0
                if _neg_mask.any():
                    for _p, _a in zip(_period_arr[_neg_mask], np.abs(_net[_neg_mask])):
                        _all_closing_entries.append({
                            "debit_account": _exp_name, "credit_account": "Profit & Loss",
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry (reversed): {_exp_name} to P&L",
                            "reference": "CLOSING-EXP-IE",
                        })
                    _pl_net_from_closing[_neg_mask] -= _net[_neg_mask]

            # Step 3: Transfer P&L to Retained Earnings (analytical)
            _pl_pre_net = _pl_acct.loc["Credit"].values.astype(float) - _pl_acct.loc["Debit"].values.astype(float)
            _net_pl = _pl_pre_net + _pl_net_from_closing
            _profit_mask = _net_pl > 0
            if _profit_mask.any():
                for _p, _a in zip(_period_arr[_profit_mask], _net_pl[_profit_mask]):
                    _all_closing_entries.append({
                        "debit_account": "Profit & Loss", "credit_account": "Retained Earnings",
                        "amount": float(_a), "period": str(_p),
                        "asset_no": "Consolidated",
                        "income_statement_line_item": None, "cashflow_line_item": None,
                        "description": "Closing entry: P&L profit to Retained Earnings",
                        "reference": "CLOSING-PL-RE",
                    })
            _loss_mask = _net_pl < 0
            if _loss_mask.any():
                for _p, _a in zip(_period_arr[_loss_mask], np.abs(_net_pl[_loss_mask])):
                    _all_closing_entries.append({
                        "debit_account": "Retained Earnings", "credit_account": "Profit & Loss",
                        "amount": float(_a), "period": str(_p),
                        "asset_no": "Consolidated",
                        "income_statement_line_item": None, "cashflow_line_item": None,
                        "description": "Closing entry: Retained Earnings absorbs P&L loss",
                        "reference": "CLOSING-PL-RE",
                    })

            # Step 4: Split IE net income into RE - Interparty Elimination
            # Journal entries post at consolidated level; per-asset trace rows
            # are appended separately below.
            _re_ie_acct = _all_accounts.get("Retained Earnings - Interparty Elimination")
            if _re_ie_acct is not None:
                _ie_neg_mask = _pre_closing_ie_net_arr < 0
                if _ie_neg_mask.any():
                    for _p, _a in zip(_period_arr[_ie_neg_mask], np.abs(_pre_closing_ie_net_arr[_ie_neg_mask])):
                        _all_closing_entries.append({
                            "debit_account": "Retained Earnings - Interparty Elimination",
                            "credit_account": "Retained Earnings",
                            "amount": float(_a), "period": str(_p),
                            "asset_no": "Consolidated",
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": "RE split: IE net income reduction to RE-IE",
                            "reference": "CLOSING-RE-IE",
                        })
                _ie_pos_mask = _pre_closing_ie_net_arr > 0
                if _ie_pos_mask.any():
                    for _p, _a in zip(_period_arr[_ie_pos_mask], _pre_closing_ie_net_arr[_ie_pos_mask]):
                        _all_closing_entries.append({
                            "debit_account": "Retained Earnings",
                            "credit_account": "Retained Earnings - Interparty Elimination",
                            "amount": float(_a), "period": str(_p),
                            "asset_no": "Consolidated",
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": "RE split: IE net income increase from RE-IE",
                            "reference": "CLOSING-RE-IE",
                        })

            # Single flush: posts all entries, rollforwards each account once,
            # and syncs touched accounts (RE, RE-IE) to balance sheet.
            if _all_closing_entries:
                _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                    batch_entries=_all_closing_entries,
                    accounts=_all_accounts,
                    journal=_accounting_journal,
                    financial_statements=_financial_statements,
                    account_names_dict=_account_names_dict,
                )

            # Per-asset trace rows for "Retained Earnings - Interparty Elimination".
            for _aid, _aid_ie_net_arr in _asset_pre_closing_ie_net.items():
                for _p_str, _ie_net in zip(_all_period_strs, _aid_ie_net_arr):
                    if abs(_ie_net) < 1e-6:
                        continue
                    fn_append_financial_statement_trace_row(
                        financial_statements=_financial_statements,
                        period=_p_str,
                        value=_ie_net,
                        financial_statement="Balance Sheet",
                        line_item_name="Retained Earnings - Interparty Elimination",
                        asset_no=str(_aid),
                    )

        fn_record_timing(_timing_ctx, "PHASE 9.5: Period-End Closing Entries")


        fn_record_timing(_timing_ctx, "PHASE 9: Calculation Logic")

        # ====================================================================
        # PHASE 10: BUILD OUTPUT STRUCTURES
        # ====================================================================

        _balance_sheet_monthly = _financial_statements.get("balance_sheet", pd.DataFrame())
        _income_statement_monthly = _financial_statements.get("income_statement", pd.DataFrame())
        _cashflow_statement_monthly = _financial_statements.get("cashflow_statement", pd.DataFrame())

        fn_record_timing(_timing_ctx, "PHASE 10.1: Extract Monthly Statements")

        _balance_sheet_presentable = fn_build_presentable_balance_sheet(
            _balance_sheet_monthly, _balance_sheet_structure
        )
        fn_record_timing(_timing_ctx, "PHASE 10.2: Build Presentable Balance Sheet")

        _income_statement_presentable = fn_build_presentable_income_statement(
            _income_statement_monthly, _income_statement_structure,
            line_item_aliases={"Asset Sales Revenue": "Developed Unit Sales Revenue", "Cost of Asset Sales": "Cost of Developed Unit Sales", "Other Operating Expense": "Other Operating Expenses"},
        )
        fn_record_timing(_timing_ctx, "PHASE 10.3: Build Presentable Income Statement")

        _cashflow_statement_presentable = fn_build_presentable_cashflow_statement(
            _cashflow_statement_monthly, _consolidated_structure
        )
        fn_record_timing(_timing_ctx, "PHASE 10.4: Build Presentable Cashflow Statement")

        _period_end_list = _period_ends.tolist() if isinstance(_period_ends, pd.Series) else []
        _monthly_timeline_df = fn_build_monthly_model_timeline(_period_end_list)
        _annual_timeline_df = fn_build_yearly_model_timeline(_period_end_list)
        fn_record_timing(_timing_ctx, "PHASE 10.6: Build Model Timelines")

        monthly_dfs = {
            "Cashflow Statement": ("o.consolidated.cfs.me", _cashflow_statement_presentable),
            "Income Statement": ("o.consolidated.is.me", _income_statement_presentable),
            "Balance Sheet": ("o.consolidated.bs.me", _balance_sheet_presentable),
            "Monthly Timeline": ("o.consolidated.model.timeline.me", _monthly_timeline_df),
        }

        annual_dfs = {
            "Yearly Timeline": ("o.consolidated.model.timeline.ye", _annual_timeline_df),
        }

        excel_output = {
            "monthly_dfs": {
                key: (code, fn_dataframe_to_output_payload(df))
                for key, (code, df) in monthly_dfs.items()
            },
            "annual_dfs": {
                key: (code, fn_dataframe_to_output_payload(df))
                for key, (code, df) in annual_dfs.items()
            },
        }
        fn_record_timing(_timing_ctx, "PHASE 10.7: Serialize Output Payloads")

        # ====================================================================
        # VALIDATION CHECKS
        # ====================================================================

        # ------------------------------------------------------------------
        # CHECK 1: Cash Balance  (Opening Cash + Cumulative CFO+CFI+CFF = Cash Closing Balance)
        # ------------------------------------------------------------------
        _cash_acct = _all_accounts.get("Cash and Cash Equivalents")
        _cf_monthly = _cashflow_statement_monthly

        _cash_check_rows: List[Dict[str, Any]] = []
        _cfo_totals_arr = None
        _cfi_totals_arr = None
        _cff_totals_arr = None
        if _cash_acct is not None and not _cash_acct.empty and not _cf_monthly.empty:
            _all_periods_check = _cash_acct.columns.tolist()

            _cfo_items = set()
            _cfi_items = set()
            _cff_items = set()
            for _cat, _items_dict in _consolidated_structure.get("CFO", {}).items():
                _cfo_items.update(_items_dict)
            for _cat, _items_dict in _consolidated_structure.get("CFI", {}).items():
                _cfi_items.update(_items_dict)
            for _cat, _items_dict in _consolidated_structure.get("CFF", {}).items():
                _cff_items.update(_items_dict)

            # Vectorized: filter rows once, sum across all periods at once
            _cf_numeric = _cf_monthly.apply(pd.to_numeric, errors="coerce").fillna(0.0)
            _cfo_rows = [i for i in _cfo_items if i in _cf_numeric.index]
            _cfi_rows = [i for i in _cfi_items if i in _cf_numeric.index]
            _cff_rows = [i for i in _cff_items if i in _cf_numeric.index]
            _cfo_totals = _cf_numeric.loc[_cfo_rows].sum(axis=0) if _cfo_rows else pd.Series(0.0, index=_cf_numeric.columns)
            _cfi_totals = _cf_numeric.loc[_cfi_rows].sum(axis=0) if _cfi_rows else pd.Series(0.0, index=_cf_numeric.columns)
            _cff_totals = _cf_numeric.loc[_cff_rows].sum(axis=0) if _cff_rows else pd.Series(0.0, index=_cf_numeric.columns)

            _opening = _cash_acct.loc["Opening Balance"].astype(float)
            _closing = _cash_acct.loc["Closing Balance"].astype(float)

            for _p_str in _all_periods_check:
                if _p_str not in _cf_monthly.columns:
                    continue
                _cfo_v = float(_cfo_totals.get(_p_str, 0.0))
                _cfi_v = float(_cfi_totals.get(_p_str, 0.0))
                _cff_v = float(_cff_totals.get(_p_str, 0.0))
                _open_v = float(_opening.get(_p_str, 0.0))
                _expected = _open_v + _cfo_v + _cfi_v + _cff_v
                _actual = float(_closing.get(_p_str, 0.0))
                _diff = round(_actual - _expected, 2)
                _cash_check_rows.append({
                    "Period": _p_str,
                    "Opening Cash": round(_open_v, 2),
                    "CFO": round(_cfo_v, 2),
                    "CFI": round(_cfi_v, 2),
                    "CFF": round(_cff_v, 2),
                    "Expected Closing": round(_expected, 2),
                    "Actual Closing": round(_actual, 2),
                    "Difference": _diff,
                    "Status": "OK" if abs(_diff) < 0.01 else "MISMATCH",
                })
            # Cache for CHECK 3 reuse
            _cfo_totals_arr = _cfo_totals
            _cfi_totals_arr = _cfi_totals
            _cff_totals_arr = _cff_totals

        _cash_check_df = pd.DataFrame(_cash_check_rows) if _cash_check_rows else pd.DataFrame()

        _cash_ok = _cash_check_df.empty or (_cash_check_df["Status"] == "OK").all()
        print("\n" + "=" * 80)
        print("CASH BALANCE CHECK: " + ("PASS" if _cash_ok else "FAIL"))
        print("=" * 80)

        fn_record_timing(_timing_ctx, "PHASE 11.1: Validation - Cash Balance Check")

        # ------------------------------------------------------------------
        # CHECK 2: Balance Sheet  (Total Assets = Total Liabilities + Total Equity)
        # ------------------------------------------------------------------
        _bs_check_rows: List[Dict[str, Any]] = []

        if not _balance_sheet_monthly.empty:
            _asset_accounts = []
            for _cat, _accts in _balance_sheet_structure.get("Assets", {}).items():
                _asset_accounts.extend(_accts)
            _liability_accounts = []
            for _cat, _accts in _balance_sheet_structure.get("Liabilities", {}).items():
                _liability_accounts.extend(_accts)
            _equity_accounts = []
            for _cat, _accts in _balance_sheet_structure.get("Equity", {}).items():
                _equity_accounts.extend(_accts)

            # Vectorized: reindex to known accounts, sum across all periods
            _bs_numeric = _balance_sheet_monthly.apply(pd.to_numeric, errors="coerce").fillna(0.0)
            _existing_assets = [a for a in _asset_accounts if a in _bs_numeric.index]
            _existing_liabilities = [a for a in _liability_accounts if a in _bs_numeric.index]
            _existing_equity = [a for a in _equity_accounts if a in _bs_numeric.index]
            _total_assets_series = _bs_numeric.loc[_existing_assets].sum(axis=0) if _existing_assets else pd.Series(0.0, index=_bs_numeric.columns)
            _total_liabilities_series = _bs_numeric.loc[_existing_liabilities].sum(axis=0) if _existing_liabilities else pd.Series(0.0, index=_bs_numeric.columns)
            _total_equity_series = _bs_numeric.loc[_existing_equity].sum(axis=0) if _existing_equity else pd.Series(0.0, index=_bs_numeric.columns)

            _bs_periods = _balance_sheet_monthly.columns.tolist()
            for _p_str in _bs_periods:
                _ta = float(_total_assets_series.get(_p_str, 0.0))
                _tl = float(_total_liabilities_series.get(_p_str, 0.0))
                _te = float(_total_equity_series.get(_p_str, 0.0))
                _diff_bs = round(_ta - (_tl + _te), 2)
                _bs_check_rows.append({
                    "Period": _p_str,
                    "Total Assets": round(_ta, 2),
                    "Total Liabilities": round(_tl, 2),
                    "Total Equity": round(_te, 2),
                    "L + E": round(_tl + _te, 2),
                    "Difference": _diff_bs,
                    "Status": "OK" if abs(_diff_bs) < 0.01 else "MISMATCH",
                })

        _bs_check_df = pd.DataFrame(_bs_check_rows) if _bs_check_rows else pd.DataFrame()

        _bs_ok = _bs_check_df.empty or (_bs_check_df["Status"] == "OK").all()
        print("=" * 80)
        print("BALANCE SHEET CHECK: " + ("PASS" if _bs_ok else "FAIL"))
        print("=" * 80)
        
        print("=" * 80 + "\n")

        fn_record_timing(_timing_ctx, "PHASE 11.2: Validation - Balance Sheet Check")

        # ------------------------------------------------------------------
        # CHECK 3: Cash Non-Negativity  (tolerance = 1e-3)
        # Reuses cached CFO/CFI/CFF totals from CHECK 1.
        # ------------------------------------------------------------------
        _cash_neg_tolerance = 1e-3
        _cash_neg_rows: List[Dict[str, Any]] = []

        if _cash_acct is not None and not _cash_acct.empty and not _cf_monthly.empty:
            _opening = _cash_acct.loc["Opening Balance"].astype(float)
            _closing = _cash_acct.loc["Closing Balance"].astype(float)

            for _p_str in _cash_acct.columns.tolist():
                _actual_close = float(_closing.get(_p_str, 0.0))

                _open_bal = float(_opening.get(_p_str, 0.0))
                _cfo_v = float(_cfo_totals_arr.get(_p_str, 0.0)) if _cfo_totals_arr is not None else 0.0
                _cfi_v = float(_cfi_totals_arr.get(_p_str, 0.0)) if _cfi_totals_arr is not None else 0.0
                _cff_v = float(_cff_totals_arr.get(_p_str, 0.0)) if _cff_totals_arr is not None else 0.0
                _computed_close = _open_bal + _cfo_v + _cfi_v + _cff_v

                _acct_negative = _actual_close < -_cash_neg_tolerance
                _computed_negative = _computed_close < -_cash_neg_tolerance

                if _acct_negative or _computed_negative:
                    _cash_neg_rows.append({
                        "Period": _p_str,
                        "Account Closing": round(_actual_close, 4),
                        "Computed Closing": round(_computed_close, 4),
                        "Account Neg": "YES" if _acct_negative else "no",
                        "Computed Neg": "YES" if _computed_negative else "no",
                    })

        _cash_neg_df = pd.DataFrame(_cash_neg_rows) if _cash_neg_rows else pd.DataFrame()

        _cash_neg_ok = _cash_neg_df.empty
        print("=" * 80)
        print("CASH NON-NEGATIVITY CHECK: " + ("PASS" if _cash_neg_ok else "FAIL"))
        print("=" * 80)

        fn_record_timing(_timing_ctx, "PHASE 11.3: Validation - Cash Non-Negativity Check")

        # ====================================================================
        # SECTION E: DEBUG EXPORTS
        # ====================================================================
        # This section exports debug data based on _EXPORT_FLAGS configuration.
        # Each flag corresponds to a specific section of the model.
        # If a flag is True, the corresponding data is exported to Excel.
        # ====================================================================

        # --------------------------------------------------------------------
        # E.1 Input Sources Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "input_sources"):
            _input_sources_export = {
                "LandCo Source": pd.DataFrame([{"key": k, "type": type(v).__name__} for k, v in _landco_source.items()]) if _landco_source else pd.DataFrame([{"placeholder": "No LandCo source data"}]),
                "DevCo Source": pd.DataFrame([{"key": k, "type": type(v).__name__} for k, v in _devco_source.items()]) if _devco_source else pd.DataFrame([{"placeholder": "No DevCo source data"}]),
                "AssetCo Count": pd.DataFrame([{"asset_count": _assetco_number_of_assets}]),
                "JV Source Count": pd.DataFrame([{"jv_count": len(_jv_source) if _jv_source else 0}]),
            }
            fn_export_dataframes_to_excel(_input_sources_export, "debug_input_sources", "Input Sources")

        # --------------------------------------------------------------------
        # E.2 Cashflow Template Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "cashflow_template"):
            _cashflow_template_export = {
                "CFO Items": pd.DataFrame([{"category": cat, "item": item} for cat, items in _consolidated_structure.get("CFO", {}).items() for item in items]),
                "CFI Items": pd.DataFrame([{"category": cat, "item": item} for cat, items in _consolidated_structure.get("CFI", {}).items() for item in items]),
                "CFF Items": pd.DataFrame([{"category": cat, "item": item} for cat, items in _consolidated_structure.get("CFF", {}).items() for item in items]),
                "Template Row Index": pd.DataFrame({"row_index": _template_row_index}) if _template_row_index else pd.DataFrame([{"placeholder": "No template row index"}]),
            }
            fn_export_dataframes_to_excel(_cashflow_template_export, "debug_cashflow_template", "Cashflow Template")

        # --------------------------------------------------------------------
        # E.3 Section Data Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "section_data"):
            _section_data_export = {
                "LandCo Timeline": fn_json_dict_to_dataframe(_landco_timeline) if _landco_timeline else pd.DataFrame([{"placeholder": "No LandCo timeline"}]),
                "DevCo Timeline": fn_json_dict_to_dataframe(_devco_timeline) if _devco_timeline else pd.DataFrame([{"placeholder": "No DevCo timeline"}]),
                "LandCo Global Assumptions": fn_json_dict_to_dataframe(_landco_global_assumptions) if _landco_global_assumptions else pd.DataFrame([{"placeholder": "No LandCo global assumptions"}]),
                "LandCo Asset Assumptions": fn_json_dict_to_dataframe(_landco_asset_assumptions) if _landco_asset_assumptions else pd.DataFrame([{"placeholder": "No LandCo asset assumptions"}]),
                "DevCo Global Assumptions": fn_json_dict_to_dataframe(_devco_global_assumptions) if _devco_global_assumptions else pd.DataFrame([{"placeholder": "No DevCo global assumptions"}]),
                "DevCo Asset Assumptions": fn_json_dict_to_dataframe(_devco_asset_assumptions) if _devco_asset_assumptions else pd.DataFrame([{"placeholder": "No DevCo asset assumptions"}]),
            }
            fn_export_dataframes_to_excel(_section_data_export, "debug_section_data", "Section Data")

        # --------------------------------------------------------------------
        # E.4 AssetCo Outputs Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "assetco_outputs"):
            _assetco_outputs_export = {
                "AssetCo Asset IDs": pd.DataFrame([{"index": k, "asset_id": v} for k, v in _assetco_asset_id.items()]) if _assetco_asset_id else pd.DataFrame([{"placeholder": "No AssetCo asset IDs"}]),
                "AssetCo Asset Names": pd.DataFrame([{"index": k, "asset_name": v} for k, v in _assetco_asset_name.items()]) if _assetco_asset_name else pd.DataFrame([{"placeholder": "No AssetCo asset names"}]),
                "AssetCo Scenario IDs": pd.DataFrame([{"index": k, "scenario_id": v} for k, v in _assetco_scenario_id.items()]) if _assetco_scenario_id else pd.DataFrame([{"placeholder": "No AssetCo scenario IDs"}]),
                "AssetCo Is Hospitality": pd.DataFrame([{"index": k, "is_hospitality": v} for k, v in _assetco_is_hospitality.items()]) if _assetco_is_hospitality else pd.DataFrame([{"placeholder": "No AssetCo hospitality flags"}]),
            }
            fn_export_dataframes_to_excel(_assetco_outputs_export, "debug_assetco_outputs", "AssetCo Outputs")

        # --------------------------------------------------------------------
        # E.5 Timeline Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "timeline"):
            _timeline_export = {
                "Master Timeline": master_timeline_df if master_timeline_df is not None and not master_timeline_df.empty else pd.DataFrame([{"placeholder": "No master timeline"}]),
                "Monthly Timeline": _monthly_timeline_df if _monthly_timeline_df is not None and not _monthly_timeline_df.empty else pd.DataFrame([{"placeholder": "No monthly timeline"}]),
                "Annual Timeline": _annual_timeline_df if _annual_timeline_df is not None and not _annual_timeline_df.empty else pd.DataFrame([{"placeholder": "No annual timeline"}]),
                "Period Ends": pd.DataFrame({"period_end": _period_ends.tolist()}) if isinstance(_period_ends, pd.Series) and not _period_ends.empty else pd.DataFrame([{"placeholder": "No period ends"}]),
            }
            fn_export_dataframes_to_excel(_timeline_export, "debug_timeline", "Timeline")

        # --------------------------------------------------------------------
        # E.6 Interparty Mapping Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "interparty_mapping"):
            _interparty_export = {
                "Interparty Mapping": _interparty_mapping if isinstance(_interparty_mapping, pd.DataFrame) and not _interparty_mapping.empty else pd.DataFrame([{"placeholder": "No interparty mapping"}]),
                "Asset Unique Identifier": pd.DataFrame({"asset_id": _asset_unique_identifier.tolist()}) if isinstance(_asset_unique_identifier, pd.Series) and not _asset_unique_identifier.empty else pd.DataFrame([{"placeholder": "No asset unique identifier"}]),
                "Acquisition Counterparty": pd.DataFrame({"counterparty": _landco_acquisition_counterparty.tolist()}) if isinstance(_landco_acquisition_counterparty, pd.Series) and not _landco_acquisition_counterparty.empty else pd.DataFrame([{"placeholder": "No acquisition counterparty"}]),
            }
            fn_export_dataframes_to_excel(_interparty_export, "debug_interparty_mapping", "Interparty Mapping")

        # --------------------------------------------------------------------
        # E.7 Accounts Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "accounts"):
            _accounts_export = {}
            if _all_accounts:
                for account_name, account_df in _all_accounts.items():
                    # Sanitize account name for sheet naming
                    safe_name = account_name[:25].replace("/", "-").replace("\\", "-")
                    _accounts_export[safe_name] = account_df if account_df is not None else pd.DataFrame([{"placeholder": f"No data for {account_name}"}])
            else:
                _accounts_export["Placeholder"] = pd.DataFrame([{"placeholder": "No accounts created"}])
            fn_export_dataframes_to_excel(_accounts_export, "debug_accounts", "Accounts")

        # --------------------------------------------------------------------
        # E.8 Financial Statements Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "financial_statements"):
            _financial_statements_export = {
                "Balance Sheet": _balance_sheet_monthly if _balance_sheet_monthly is not None and not _balance_sheet_monthly.empty else pd.DataFrame([{"placeholder": "No balance sheet"}]),
                "Income Statement": _income_statement_monthly if _income_statement_monthly is not None and not _income_statement_monthly.empty else pd.DataFrame([{"placeholder": "No income statement"}]),
                "Cashflow Statement": _cashflow_statement_monthly if _cashflow_statement_monthly is not None and not _cashflow_statement_monthly.empty else pd.DataFrame([{"placeholder": "No cashflow statement"}]),
            }
            fn_export_dataframes_to_excel(_financial_statements_export, "debug_financial_statements", "Financial Statements")

        # --------------------------------------------------------------------
        # E.9 Calculations Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "calculations"):
            _calculations_export = {
                "Accounting Journal": pd.DataFrame(_accounting_journal) if _accounting_journal else pd.DataFrame([{"placeholder": "No journal entries"}]),
                "DevCo Col to Period Map": pd.DataFrame([{"col": k, "period": v} for k, v in _devco_col_to_period.items()]) if _devco_col_to_period else pd.DataFrame([{"placeholder": "No column to period mapping"}]),
            }
            fn_export_dataframes_to_excel(_calculations_export, "debug_calculations", "Calculations")

        # --------------------------------------------------------------------
        # E.10 Output Structures Export
        # --------------------------------------------------------------------
        if fn_is_debug_export_enabled(_EXPORT_FLAGS, "output_structures"):
            _output_structures_export = {
                "BS Presentable": _balance_sheet_presentable if _balance_sheet_presentable is not None and not _balance_sheet_presentable.empty else pd.DataFrame([{"placeholder": "No balance sheet presentable"}]),
                "IS Presentable": _income_statement_presentable if _income_statement_presentable is not None and not _income_statement_presentable.empty else pd.DataFrame([{"placeholder": "No income statement presentable"}]),
                "CFS Presentable": _cashflow_statement_presentable if _cashflow_statement_presentable is not None and not _cashflow_statement_presentable.empty else pd.DataFrame([{"placeholder": "No cashflow statement presentable"}]),
            }
            fn_export_dataframes_to_excel(_output_structures_export, "debug_output_structures", "Output Structures")

        fn_record_timing(_timing_ctx, "PHASE 12: Debug Exports")

        # --------------------------------------------------------------------
        # Finalize Timing Summary
        # --------------------------------------------------------------------
        _timing_summary = fn_finalize_timing_summary(_timing_ctx, "PHASE 13: Final Assembly", entity_label="DEVCO CONSOLIDATION")
        print(_timing_summary["summary_text"])

        _accounts_source = _all_accounts if isinstance(_all_accounts, dict) else {}
        if _enable_lightweight_output:
            _accounts_source = {
                name: df
                for name, df in _accounts_source.items()
                if name in _LIGHTWEIGHT_INTERPARTY_ACCOUNT_NAMES
            }

        _output = {
            "monthly_dfs": excel_output.get("monthly_dfs", {}),
            "annual_dfs": excel_output.get("annual_dfs", {}),
            "accounts": {
                name: fn_dataframe_to_output_payload(df)
                for name, df in _accounts_source.items()
            },
            "journal": _accounting_journal if _accounting_journal else [],
        }

        if _enable_financial_statement_trace:
            _financial_statement_trace_df = fn_build_financial_statement_trace_dataframe(_financial_statements)
            _financial_statement_trace_df = fn_add_unique_id_to_trace_df(
                _financial_statement_trace_df,
                _asset_unique_identifier,
            )
            _output["financial_statement_trace"] = fn_trace_dataframe_to_payload(_financial_statement_trace_df)

        return _output

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            error_msg = (
                f"Error in wrapper_for_vars at line {last_frame.lineno} "
                f"in {last_frame.filename}: {str(e)}\n"
                f"Full Traceback:\n{traceback.format_exc()}"
            )
            print(error_msg)
        else:
            print(f"Error in wrapper_for_vars: {str(e)}")


# ------------------------------------------------------------------------------
# D.2 Entry Point Function
# ------------------------------------------------------------------------------

def fninitialising_all_values(payload: Any, is_save=None) -> Optional[Any]:
    try:
        if payload is None:
            print("Error in fninitialising_all_values: payload cannot be None")
            return None
        if not isinstance(payload, (dict, list)):
            print(
                "Error in fninitialising_all_values: payload must be a dictionary or list, "
                f"got {type(payload).__name__}"
            )
            return None
        
        output = wrapper_for_vars(payload)
        return output
        
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            error_msg = (
                f"Error in fninitialising_all_values at line {last_frame.lineno} "
                f"in {last_frame.filename}: {str(e)}\n"
                f"Full Traceback:\n{traceback.format_exc()}"
            )
            print(error_msg)
        else:
            print(f"Error in fninitialising_all_values: {str(e)}")
        return None