"""
================================================================================
CONSOLIDATED MODEL - VERSION 3
================================================================================

This module provides the complete consolidation framework for building unified
financial statements and cashflows from LandCo, DevCo, and AssetCo payloads.

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
# SECTION C: ENTITY-SPECIFIC PROCESSING FUNCTIONS
# ==============================================================================
# LandCo-specific journal entry processing functions.
# These functions call the shared utilities imported from project_conso_utils.
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
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process land acquisition accounting with advance and payable roll-forward logic.

    Rules implemented:
    1. Before acquisition: Dr Advances for Land / Cr Cash and Cash Equivalents
    2. On acquisition: Dr Land Assets / Cr Advances for Land (if any), Cr Accounts Payable (balance)
    3. After acquisition: Dr Accounts Payable / Cr Cash and Cash Equivalents

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

    if land_acquisition_df.empty and land_acquisition_cost_cash_payment_df.empty:
        print("fn_process_land_acquisition_entries: no acquisition or payment data to process")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_land_acquisition_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Land Assets",
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

    # Accumulate all journal entries, then flush once (single rollforward per account).
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

    _acq_matrix = _extract_matrix(land_acquisition_df)
    _pay_matrix = _extract_matrix(land_acquisition_cost_cash_payment_df)

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        acquisition_values = _acq_matrix[asset_row_idx]
        payment_values = _pay_matrix[asset_row_idx]

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
                        "debit_account": "Land Assets",
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
                        "debit_account": "Land Assets",
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

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
        type_aware_is_posting=True,
    )
    return accounts, journal, financial_statements


def fn_process_infrastructure_entries(
    infra_progress_df: pd.DataFrame,
    infra_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    infra_label: str,
    cashflow_line_item: str = "Primary Infrastructure Cost",
    reference_prefix: str = "LC-PI",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process infrastructure accounting using progress S-curve and cash payments.

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
        print(f"fn_process_infrastructure_entries ({infra_label}): asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not isinstance(infra_progress_df, pd.DataFrame):
        print(f"fn_process_infrastructure_entries ({infra_label}): infra_progress_df is not a DataFrame")
        infra_progress_df = pd.DataFrame()

    if not isinstance(infra_payment_df, pd.DataFrame):
        print(f"fn_process_infrastructure_entries ({infra_label}): infra_payment_df is not a DataFrame")
        infra_payment_df = pd.DataFrame()

    # Normalize index types once so row alignment is consistent and fast.
    if not infra_progress_df.empty:
        infra_progress_df = infra_progress_df.copy()
        infra_progress_df.index = infra_progress_df.index.map(lambda x: str(x).strip())

    if not infra_payment_df.empty:
        infra_payment_df = infra_payment_df.copy()
        infra_payment_df.index = infra_payment_df.index.map(lambda x: str(x).strip())

    if infra_progress_df.empty and infra_payment_df.empty:
        print(f"fn_process_infrastructure_entries ({infra_label}): no progress or payment data to process")
        return accounts, journal, financial_statements

    if not col_to_period:
        print(f"fn_process_infrastructure_entries ({infra_label}): col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "CWIP - Serviced Land",
        "Accounts Payable",
        "Advance to Contractor",
        "Cash and Cash Equivalents",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(
            f"fn_process_infrastructure_entries ({infra_label}): missing required accounts: "
            f"{missing_accounts}"
        )
        return accounts, journal, financial_statements

    period_cols = list(col_to_period.keys())
    if not period_cols:
        print(f"fn_process_infrastructure_entries ({infra_label}): no period columns available")
        return accounts, journal, financial_statements

    period_map = [(period_col, col_to_period.get(period_col)) for period_col in period_cols]

    row_index = (
        infra_progress_df.index
        if not infra_progress_df.empty
        else infra_payment_df.index
    )
    if len(row_index) == 0:
        print(f"fn_process_infrastructure_entries ({infra_label}): no asset rows available")
        return accounts, journal, financial_statements

    # Accumulate all journal entries, then flush once (single rollforward per account).
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

    _progress_matrix = _extract_matrix(infra_progress_df)
    _payment_matrix = _extract_matrix(infra_payment_df)

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

            # LandCo CFI outflows are often provided as negative values.
            # Normalize to absolute magnitudes so accounting entries can post.
            if progress_amount < 0:
                progress_amount = abs(progress_amount)

            if payment_amount < 0:
                payment_amount = abs(payment_amount)

            if progress_amount == 0.0 and payment_amount == 0.0:
                continue

            if progress_amount > 0.0:
                _batch_entries.append({
                    "debit_account": "CWIP - Serviced Land",
                    "credit_account": "Accounts Payable",
                    "amount": progress_amount,
                    "period": period_str,
                    "income_statement_line_item": None,
                    "cashflow_line_item": None,
                    "description": f"{infra_label} Progress - Asset {asset_idx}",
                    "reference": f"{reference_prefix}-PROG-{asset_idx}-{period_col}",
                })
                payable_balance += progress_amount

                if advance_balance > 0.0:
                    adjustment_amount = min(advance_balance, payable_balance)
                    if adjustment_amount > 0.0:
                        _batch_entries.append({
                            "debit_account": "Accounts Payable",
                            "credit_account": "Advance to Contractor",
                            "amount": adjustment_amount,
                            "period": period_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": None,
                            "description": f"{infra_label} Advance Adjustment - Asset {asset_idx}",
                            "reference": f"{reference_prefix}-ADJ-{asset_idx}-{period_col}",
                        })
                        payable_balance -= adjustment_amount
                        advance_balance -= adjustment_amount

            if payment_amount > 0.0:
                payable_settlement = min(payment_amount, payable_balance)

                if payable_settlement > 0.0:
                    _batch_entries.append({
                        "debit_account": "Accounts Payable",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": payable_settlement,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"{infra_label} Payable Settlement - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-AP-{asset_idx}-{period_col}",
                    })
                    payable_balance -= payable_settlement
                    payment_amount -= payable_settlement

                if payment_amount > 0.0:
                    _batch_entries.append({
                        "debit_account": "Advance to Contractor",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": payment_amount,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": cashflow_line_item,
                        "description": f"{infra_label} Advance Payment - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-PAY-ADV-{asset_idx}-{period_col}",
                    })
                    advance_balance += payment_amount

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
        type_aware_is_posting=True,
    )
    return accounts, journal, financial_statements


def fn_process_primary_infrastructure_entries(
    primary_infra_progress_df: pd.DataFrame,
    primary_infra_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    cashflow_line_item: str = "Primary Infrastructure Cost",
    reference_prefix: str = "LC-PI",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    return fn_process_infrastructure_entries(
        infra_progress_df=primary_infra_progress_df,
        infra_payment_df=primary_infra_payment_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        infra_label="Primary Infrastructure",
        cashflow_line_item=cashflow_line_item,
        reference_prefix=reference_prefix,
    )


def fn_process_secondary_infrastructure_entries(
    secondary_infra_progress_df: pd.DataFrame,
    secondary_infra_payment_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    cashflow_line_item: str = "Secondary Infrastructure Cost",
    reference_prefix: str = "LC-SI",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    return fn_process_infrastructure_entries(
        infra_progress_df=secondary_infra_progress_df,
        infra_payment_df=secondary_infra_payment_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        infra_label="Secondary Infrastructure",
        cashflow_line_item=cashflow_line_item,
        reference_prefix=reference_prefix,
    )


def fn_process_land_sales_entries(
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
    reference_prefix: str = "LC-SALES",
    exit_counterparty: Optional[pd.Series] = None,
    cost_incurred_df: Optional[pd.DataFrame] = None,
    cwip_cost_incurred_df: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process LandCo land sales accounting entries across all financial statements.

    When exit_counterparty is provided and an asset's LandCo exit counterparty
    is "DevCo", opposite (reversal) entries are posted to Interparty Elimination
    accounts for consolidation elimination purposes.

    Implements the following entry logic per asset per period:

    1. Revenue Recognition (proportional to infrastructure S-curve):
       Dr Accounts Receivable / Cr Land Sales Revenue

    2. Cost Recognition (proportional to same S-curve):
       (a) Dr Inventory - Serviced Land / Cr Land Assets + Cr CWIP - Serviced Land
       (b) Dr Cost of Land Sales / Cr Inventory - Serviced Land

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
        print("fn_process_land_sales_entries: asset_unique_identifier is missing or empty")
        return accounts, journal, financial_statements

    if not col_to_period:
        print("fn_process_land_sales_entries: col_to_period mapping is empty")
        return accounts, journal, financial_statements

    required_accounts = [
        "Cash and Cash Equivalents",
        "Accounts Receivable",
        "Escrow Restricted Cash",
        "Unearned Revenue",
        "Land Assets",
        "CWIP - Serviced Land",
        "Land Sales Revenue",
        "Cost of Land Sales",
    ]
    missing_accounts = [acc for acc in required_accounts if acc not in accounts]
    if missing_accounts:
        print(f"fn_process_land_sales_entries: missing required accounts: {missing_accounts}")
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
    # CWIP cost matrix (used per-asset for Land/CWIP credit split ratio).
    # ------------------------------------------------------------------
    _cwip_cost_matrix = np.abs(_extract_matrix(cwip_cost_incurred_df)) if isinstance(cwip_cost_incurred_df, pd.DataFrame) and not cwip_cost_incurred_df.empty else np.zeros((len(_str_index), len(period_cols)), dtype="float64")

    for asset_row_idx, (asset_idx, asset_unique_id) in enumerate(zip(row_index, asset_unique_identifier)):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_idx_key = str(asset_idx).strip()

        # Track start position for interparty elimination post-processing.
        _asset_start_pos = len(_batch_entries)

        # Determine if this asset's LandCo exit counterparty is DevCo.
        _is_devco_exit = False
        if exit_counterparty is not None and isinstance(exit_counterparty, pd.Series) and not exit_counterparty.empty:
            try:
                _ec_loc = row_index.get_loc(asset_idx_key) if asset_idx_key in row_index else None
                if _ec_loc is not None:
                    _is_devco_exit = str(exit_counterparty.iloc[_ec_loc]).strip() == "DevCo"
            except Exception:
                pass

        # When interparty entries are disabled, skip interparty assets entirely.
        if _is_devco_exit and not _ENABLE_INTERPARTY_ENTRIES:
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
        # Read both collection sources: escrow inflows AND non-escrow (which
        # may include post-construction residual for escrow assets).
        collection_escrow_values = _coll_escrow_matrix[asset_row_idx] if is_escrow else np.zeros(len(period_cols), dtype="float64")
        collection_non_escrow_values = _coll_non_escrow_matrix[asset_row_idx]
        escrow_release_values = _escrow_release_matrix[asset_row_idx] if is_escrow else np.zeros(len(period_cols), dtype="float64")

        # LandCo support workings provides S-curve as amount phasing (not %).
        # Convert to cumulative percentage profile for recognition logic.
        s_curve_total_amount = float(s_curve_amount_values.sum())
        if s_curve_total_amount > 0.0:
            s_curve_pct_values = np.cumsum(s_curve_amount_values) / s_curve_total_amount
        else:
            print(
                f"fn_process_land_sales_entries: zero total S-curve amount for asset {asset_idx}; "
                "revenue recognition will remain zero for this asset"
            )
            s_curve_pct_values = np.zeros(len(period_cols), dtype="float64")

        # Normalize to absolute values (sources may be negative for outflows).
        collection_escrow_values = np.abs(collection_escrow_values)
        collection_non_escrow_values = np.abs(collection_non_escrow_values)
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

        # Per-asset credit split ratio between Land Assets and CWIP.
        _asset_cwip_cost = float(_cwip_cost_matrix[asset_row_idx].sum())
        _asset_land_cost = max(0.0, total_asset_cost - _asset_cwip_cost)
        if total_asset_cost > 0.0:
            _land_ratio = _asset_land_cost / total_asset_cost
            _cwip_ratio = _asset_cwip_cost / total_asset_cost
        else:
            _land_ratio = 0.0
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

        for period_idx, ((period_col, period_str), s_curve_pct, esc_coll_amt, non_esc_coll_amt, esc_rel_amt) in enumerate(zip(
            period_map,
            s_curve_pct_values,
            collection_escrow_values,
            collection_non_escrow_values,
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
                        "credit_account": "Land Sales Revenue",
                        "amount": unearned_reversal,
                        "period": period_str,
                        "income_statement_line_item": "Land Sales Revenue",
                        "cashflow_line_item": None,
                        "description": f"Revenue Recognition (Unearned Reversal) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-REV-UNR-{asset_idx}-{period_col}",
                    })
                    unearned_balance -= unearned_reversal

                if ar_portion > 0.0:
                    # Dr Accounts Receivable / Cr Land Sales Revenue
                    _batch_entries.append({
                        "debit_account": "Accounts Receivable",
                        "credit_account": "Land Sales Revenue",
                        "amount": ar_portion,
                        "period": period_str,
                        "income_statement_line_item": "Land Sales Revenue",
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
                # Dr Cost of Land Sales / Cr Land Assets + Cr CWIP - Serviced Land
                # Split the credit proportionally between Land Assets and CWIP.
                land_credit = period_cost * _land_ratio
                cwip_credit = period_cost * _cwip_ratio

                if land_credit > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Land Sales",
                        "credit_account": "Land Assets",
                        "amount": land_credit,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Land Sales",
                        "cashflow_line_item": None,
                        "description": f"Cost of Land Sales (Land) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-LA-{asset_idx}-{period_col}",
                    })

                if cwip_credit > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cost of Land Sales",
                        "credit_account": "CWIP - Serviced Land",
                        "amount": cwip_credit,
                        "period": period_str,
                        "income_statement_line_item": "Cost of Land Sales",
                        "cashflow_line_item": None,
                        "description": f"Cost of Land Sales (CWIP) - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COGS-CWIP-{asset_idx}-{period_col}",
                    })

                cumulative_cost_recognized += period_cost

            # ==============================================================
            # 3/4/5. Collection Entries (with adjustment logic)
            # ==============================================================
            # For escrow assets: process escrow collection (to Restricted Cash)
            # AND any non-escrow residual (post-construction, direct to Cash).
            # For non-escrow assets: process non-escrow collection only.
            # ==============================================================

            # --- Escrow collection (escrow assets only) ---
            if is_escrow and esc_coll_amt > 0.0:
                cumulative_collection += esc_coll_amt

                ar_settlement = min(esc_coll_amt, ar_balance)
                unearned_portion = esc_coll_amt - ar_settlement

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

            # --- Non-escrow collection (all assets; includes post-construction
            #     residual for escrow assets) ---
            if non_esc_coll_amt > 0.0:
                cumulative_collection += non_esc_coll_amt

                ar_settlement = min(non_esc_coll_amt, ar_balance)
                unearned_portion = non_esc_coll_amt - ar_settlement

                if ar_settlement > 0.0:
                    _batch_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Accounts Receivable",
                        "amount": ar_settlement,
                        "period": period_str,
                        "income_statement_line_item": None,
                        "cashflow_line_item": "On-plan Sales Collection",
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
                        "cashflow_line_item": "On-plan Sales Collection",
                        "description": f"Collection (Non-Escrow) Unearned Revenue - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-COLL-UNR-{asset_idx}-{period_col}",
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
                    "cashflow_line_item": "Off-plan Sales Collection",
                    "description": f"Escrow Release - Asset {asset_idx}",
                    "reference": f"{reference_prefix}-ESCREL-{asset_idx}-{period_col}",
                })

            # ==============================================================
            # 7. Period-End: Balance tracking is maintained via ar_balance
            #    and unearned_balance, updated in steps 1 and 3/4/5 above.
            # ==============================================================

        # ==============================================================
        # Interparty Elimination: Generate reversed entries for assets
        # whose LandCo exit counterparty is DevCo.
        # ==============================================================
        if _is_devco_exit and _ENABLE_INTERPARTY_ELIMINATION:
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
        # Unrealized Gains: For interparty sales (LandCo → DevCo),
        # record the profit (Revenue − COGS) in a tracking account.
        # Dr Unrealized Gains on Interparty Sales / Cr Unrealized Gains Offset
        # ==============================================================
        if _is_devco_exit:
            _ug_revenue = 0.0
            _ug_cogs = 0.0
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = _be.get("income_statement_line_item", "")
                if _is_item == "Land Sales Revenue":
                    _ug_revenue += float(_be.get("amount", 0.0))
                elif _is_item == "Cost of Land Sales":
                    _ug_cogs += float(_be.get("amount", 0.0))
            _ug_profit = round(_ug_revenue - _ug_cogs, 2)
            if abs(_ug_profit) > 0.01:
                # Use the last period from the asset's entries
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
        # Interparty Netting Tracking: Mirror AR and Unearned Revenue
        # movements for LandCo → DevCo sales into tracking accounts.
        # Used by the consolidated BS to net AR vs AP and Advances vs UR.
        # ==============================================================
        if _is_devco_exit:
            _NETTING_MAP = {
                "Accounts Receivable": "Interparty Accounts Receivable",
                "Unearned Revenue": "Interparty Unearned Revenue",
            }
            _mirror_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                _d = _be.get("debit_account", "")
                _c = _be.get("credit_account", "")
                _a = float(_be.get("amount", 0.0))
                _p = _be.get("period")
                if abs(_a) < 0.01:
                    continue
                if _d in _NETTING_MAP:
                    _mirror_entries.append({
                        "debit_account": _NETTING_MAP[_d],
                        "credit_account": "Interparty Netting Offset",
                        "amount": _a,
                        "period": _p,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Interparty Netting - {_d} - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPNT-{asset_idx}-{_p}",
                    })
                if _c in _NETTING_MAP:
                    _mirror_entries.append({
                        "debit_account": "Interparty Netting Offset",
                        "credit_account": _NETTING_MAP[_c],
                        "amount": _a,
                        "period": _p,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": f"Interparty Netting - {_c} - Asset {asset_idx}",
                        "reference": f"{reference_prefix}-IPNT-{asset_idx}-{_p}",
                    })
            _batch_entries.extend(_mirror_entries)

        # ==============================================================
        # Interparty IS/CF Elimination Tracking: Record periodical
        # interparty revenue, COGS, and cash collection for
        # consolidated IS and CF elimination.
        # ==============================================================
        if _is_devco_exit:
            _elim_entries: List[Dict[str, Any]] = []
            for _be in _batch_entries[_asset_start_pos:]:
                _is_item = (_be.get("income_statement_line_item") or "")
                _cf_item = _be.get("cashflow_line_item")
                _amt = float(_be.get("amount", 0.0))
                _per = _be.get("period")
                if abs(_amt) < 0.01:
                    continue
                if _is_item == "Land Sales Revenue":
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
                if _is_item == "Cost of Land Sales":
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
        print("fn_process_land_sales_entries: no entries to post")
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
        type_aware_is_posting=True,
    )

    return accounts, journal, financial_statements


# ------------------------------------------------------------------------------
# C.4b LandCo Debt & Financing Entries
# ------------------------------------------------------------------------------

def fn_process_landco_debt_entries(
    facility_configs: List[Dict[str, Any]],
    equity_infusion_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    reference_prefix: str = "LC-DEBT",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process LandCo debt facility and equity journal entries.

    Handles three facility types:
      - Revolvers (asset-level and project-level): repayment is split between
        interest expense and principal using capitalized interest comparison.
      - Term Loan: uses pre-split fields for principal, interest, and capitalization.

    Revolver split logic per period:
      Cap interest is always capitalized: Dr CWIP / Cr Loan Account.
      A cumulative cap-interest tracker determines the interest/principal
      split when repayment occurs:
        interest_expense = min(repayment, cumulative_cap_interest)
        principal        = repayment - interest_expense
      This ensures previously capitalized interest is expensed first,
      with the remainder reducing principal.

    Term Loan logic per period:
      Dr CWIP - Serviced Land / Cr Loan Account  (capitalized interest, non-cash)
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
        print("fn_process_landco_debt_entries: col_to_period mapping is empty")
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
            print(f"fn_process_landco_debt_entries: no rows for facility {facility_name}")
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
                            "debit_account": "CWIP - Serviced Land",
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
                            "debit_account": "CWIP - Serviced Land",
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
        print("fn_process_landco_debt_entries: no entries to post")
        return accounts, journal, financial_statements

    accounts, journal, financial_statements = fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
        type_aware_is_posting=True,
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
        _landco_business_model = fn_extract_assumptions(_landco_asset_assumptions, "BusinessModelModule", "business_model")

        _jvjda_inclusion_series = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "jvjda_inclusion")
        _lc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "landco_inclusion")
        _dc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "devco_inclusion")
        _ac_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "assetco_inclusion")

        # Null out asset rows where LandCo is in the JV so entry loops skip them.
        # LandCo is in JV when jvjda_inclusion=Yes AND landco_inclusion=Yes.
        if (
            _asset_unique_identifier is not None
            and _jvjda_inclusion_series is not None
            and _lc_jv_inclusion is not None
        ):
            _lc_in_jv_mask = (
                (_jvjda_inclusion_series == "Yes") & (_lc_jv_inclusion == "Yes")
            )
            _asset_unique_identifier = _asset_unique_identifier.where(~_lc_in_jv_mask, other=None)

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
        # - Processing LandCo cashflows
        # - Processing DevCo cashflows
        # - Processing AssetCo cashflows
        # - Intercompany eliminations
        # - Journal entry recording
        # ====================================================================

        # --------------------------------------------------------------------
        # 9.0 Build LandCo Period End Mapping
        # --------------------------------------------------------------------
        # LandCo cashflows have numeric columns (0, 1, 2, ...) that need to be
        # mapped to period end dates for recording in accounts/statements.
        # --------------------------------------------------------------------
        _landco_timeline_df = fn_json_dict_to_dataframe(_landco_timeline) if _landco_timeline else None
        _landco_period_ends_series = (
            pd.to_datetime(_landco_timeline_df.loc["Period End"]).dt.normalize()
            if _landco_timeline_df is not None and "Period End" in _landco_timeline_df.index
            else pd.Series()
        )
        # Create mapping: column index (int or str) -> period end date string
        # Note: Use strftime to match the format used in account/statement columns ('YYYY-MM-DD')
        _landco_col_to_period: Dict[Any, str] = {}
        for col_idx, period_end in _landco_period_ends_series.items():
            _landco_col_to_period[col_idx] = period_end.strftime('%Y-%m-%d')

        fn_record_timing(_timing_ctx, "PHASE 9.0: Build LandCo Period Mapping")

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
        # 9.1 Process LandCo Land Acquisition Entries
        # --------------------------------------------------------------------

        _landco_land_acquisition_flag = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Land Acquisition Flag",
            source_name="LandCo Support Workings",
        )

        _landco_land_acquisition_cost_cash_payment = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Land Acquisition Cost Cash Payment",
            source_name="LandCo Support Workings",
        )

        _landco_land_acquisition_cost_in_kind = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Land Acquisition Cost In Kind",
            source_name="LandCo Support Workings",
        )
        
        _landco_land_acquisition_cash = _landco_land_acquisition_flag.mul(
            _landco_land_acquisition_cost_cash_payment.sum(axis=1).values,
            axis=0
        )

        if _landco_land_acquisition_cash.empty:
            print("Land Acquisition is empty after summing cash payments and applying acquisition flag. Check source data and calculations.")    

        _all_accounts, _accounting_journal, _financial_statements = fn_process_land_acquisition_entries(
            land_acquisition_df=_landco_land_acquisition_cash,
            land_acquisition_cost_cash_payment_df=_landco_land_acquisition_cost_cash_payment,
            col_to_period=_landco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            cashflow_line_item="Raw Land Acquisition Cost",
            reference_prefix="LC-LA",
        )

        fn_record_timing(_timing_ctx, "PHASE 9.1A: Land Acquisition Cash Entries")

        # Hardcoded control flag for Land in Kind journal posting.
        _ENABLE_LAND_IN_KIND_ENTRY = True

        # Compute in-kind land amount timed to asset acquisition date.
        # Same pattern as cash: total in-kind cost per asset * acquisition flag.
        _landco_land_acquisition_in_kind = _landco_land_acquisition_flag.mul(
            _landco_land_acquisition_cost_in_kind.sum(axis=1).values,
            axis=0,
        ) if not _landco_land_acquisition_cost_in_kind.empty and not _landco_land_acquisition_flag.empty else _landco_land_acquisition_cost_in_kind

        # Record in-kind land contribution as equity-funded land acquisition.
        # Entry: Dr Land Assets / Cr Share Capital
        if _ENABLE_LAND_IN_KIND_ENTRY:
            _all_accounts, _accounting_journal, _financial_statements = fn_process_cashflow_line_item(
                source_df=_landco_land_acquisition_in_kind,
                col_to_period=_landco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                index_maps=_index_maps,
                account_names_dict=_account_names_dict,
                debit_account="Land Assets",
                credit_account="Share Capital",
                income_statement_line_item=None,
                cashflow_line_item=None,
                line_item_name="Land Acquisition In Kind",
                reference_prefix="LC-LA-IK",
            )
            fn_record_timing(_timing_ctx, "PHASE 9.1B.1: Land Acquisition In-Kind Journal Entries")
            # Directly populate the "Land in Kind Contribution" CF row
            # using the raw base data (_landco_land_acquisition_cost_in_kind)
            # from Support Workings, filtered by asset UID.
            _LIK_CF_LABEL = "Land in Kind Contribution"
            if (
                "cashflow_statement" in _financial_statements
                and not _landco_land_acquisition_cost_in_kind.empty
            ):
                _cf_df = _financial_statements["cashflow_statement"]
                if _LIK_CF_LABEL in _cf_df.index:
                    # Filter to rows whose asset UID is valid (non-null,
                    # non-empty string) to respect single-asset mode.
                    _lik_src = _landco_land_acquisition_cost_in_kind
                    if _asset_unique_identifier is not None and not _asset_unique_identifier.empty:
                        _uid_valid = _asset_unique_identifier.apply(
                            lambda x: isinstance(x, str) and x.strip() != ""
                        )
                        if len(_uid_valid) == len(_lik_src):
                            _lik_src = _lik_src.loc[_uid_valid.values]

                    _lik_numeric = _lik_src.apply(pd.to_numeric, errors="coerce").fillna(0.0)

                    # Sum across assets to get per-period totals, then
                    # map entity columns to consolidated periods.
                    _lik_totals = _lik_numeric.sum(axis=0)
                    for _lik_col, _lik_val in _lik_totals.items():
                        _lik_period = _landco_col_to_period.get(_lik_col)
                        if _lik_period is None or _lik_period not in _cf_df.columns:
                            continue
                        if abs(float(_lik_val)) > 1e-6:
                            _cf_df.loc[_LIK_CF_LABEL, _lik_period] += float(_lik_val)
                    _financial_statements["cashflow_statement"] = _cf_df

                    if _enable_financial_statement_trace and not _lik_numeric.empty:
                        _lik_cols = list(_lik_numeric.columns)
                        _lik_asset_nos = list(_lik_numeric.index)
                        _lik_values = _lik_numeric.to_numpy(dtype="float64", copy=False)

                        for _lik_row_idx, _lik_asset_no in enumerate(_lik_asset_nos):
                            for _lik_col_idx, _lik_col in enumerate(_lik_cols):
                                _lik_period = _landco_col_to_period.get(_lik_col)
                                if _lik_period is None:
                                    continue

                                _lik_value = float(_lik_values[_lik_row_idx, _lik_col_idx])
                                if abs(_lik_value) <= 1e-6:
                                    continue

                                fn_append_financial_statement_trace_row(
                                    financial_statements=_financial_statements,
                                    period=_lik_period,
                                    value=_lik_value,
                                    financial_statement="Cashflow Statement",
                                    line_item_name=_LIK_CF_LABEL,
                                    asset_no=_lik_asset_no,
                                )
        else:
            print("Land Acquisition In Kind entry disabled by flag (_ENABLE_LAND_IN_KIND_ENTRY=False)")

        fn_record_timing(_timing_ctx, "PHASE 9.1B.2: Land Acquisition In-Kind Entries")

        # --------------------------------------------------------------------
        # 9.1C Process LandCo Acquisition Transaction Cost Entries (Direct Cash)
        # Entry: Dr Land Assets / Cr Cash and Cash Equivalents
        # --------------------------------------------------------------------
        _landco_acquisition_transaction_cost_items = [
            ("Legal Cost", "LEGAL"),
            ("Agency Cost", "AGENCY"),
            ("Technical Cost", "TECH"),
            ("Valuation Cost", "VALUATION"),
            ("Due Diligence Cost", "DUEDIL"),
            ("Real Estate Transaction Tax", "RETT"),
            ("Municipal Fees", "MUNI"),
        ]

        _txn_cost_batches = []
        _landco_acquisition_txn_cost_dfs: List[pd.DataFrame] = []
        for _txn_cost_line_item, _txn_cost_ref in _landco_acquisition_transaction_cost_items:
            _txn_cost_df = fn_safe_extract_dataframe(
                source_dict=_landco_cfi,
                key=_txn_cost_line_item,
                source_name="LandCo Cashflow from Investments",
            )

            if _txn_cost_df.empty:
                print(
                    "Land Acquisition Transaction Cost line item not found or empty in LandCo CFI: "
                    f"'{_txn_cost_line_item}'"
                )
                continue

            _landco_acquisition_txn_cost_dfs.append(_txn_cost_df)

            _batch = fn_prepare_direct_cash_matrix_batch(
                source_df=_txn_cost_df,
                col_to_period=_landco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account="Land Assets",
                credit_account="Cash and Cash Equivalents",
                cashflow_line_item=_txn_cost_line_item,
                line_item_name=f"Land Acquisition Transaction Cost - {_txn_cost_line_item}",
                reference_prefix=f"LC-LATC-{_txn_cost_ref}",
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
                interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
                type_aware_is_posting=True,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1C: Land Acquisition Transaction Cost Entries")

        # --------------------------------------------------------------------
        # 9.1D Process LandCo Development and Capitalized Cost Entries (Direct Cash)
        # Entry: Dr CWIP - Serviced Land / Cr Cash and Cash Equivalents
        # --------------------------------------------------------------------
        _landco_cwip_direct_cash_items = [
            ("Design Cost", "DESIGN"),
            ("Permitting Cost", "PERMIT"),
            ("Supervision Cost", "SUPERV"),
            ("Project Management Cost", "PM"),
            ("Contingency Cost Payment", "CONT"),
            ("Capitalized Salaries Expenses", "CAPSAL"),
            ("Capitalized IT Services Expenses", "CAPIT"),
            ("Capitalized Office Rent and Utilities Expenses", "CAPRENT"),
            ("Capitalized Professional Services Expenses", "CAPPROF"),
            ("Capitalized Marketing Expenses", "CAPMKT"),
            ("Capitalized Sales Cost Expenses", "CAPSALES"),
            ("Capitalized Additional Expenses", "CAPADD"),
        ]

        _cwip_direct_cash_sum: pd.DataFrame = pd.DataFrame()  # accumulates abs CWIP cost DFs for total CWIP S-curve

        _cwip_batches = []
        for _cwip_line_item, _cwip_ref in _landco_cwip_direct_cash_items:
            _cwip_df = fn_safe_extract_dataframe(
                source_dict=_landco_cfi,
                key=_cwip_line_item,
                source_name="LandCo Cashflow from Investments",
            )

            if _cwip_df.empty:
                print(
                    "CWIP direct-cash line item not found or empty in LandCo CFI: "
                    f"'{_cwip_line_item}'"
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
                col_to_period=_landco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account="CWIP - Serviced Land",
                credit_account="Cash and Cash Equivalents",
                cashflow_line_item=_cwip_line_item,
                line_item_name=f"CWIP Direct Cash - {_cwip_line_item}",
                reference_prefix=f"LC-CWIP-{_cwip_ref}",
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
                interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
                type_aware_is_posting=True,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1D: CWIP Direct-Cash Cost Entries")

        # --------------------------------------------------------------------
        # 9.1E Process LandCo CFO Operating Entries (Direct Cash)
        # --------------------------------------------------------------------
        _landco_cfo_journal_mappings = [
            (
                "Escrow Setup Fees",
                "ESCFEE",
                "Other Operating Expenses",
                "Cash and Cash Equivalents",
                "Escrow Setup Fees",
            ),
            (
                "Lease Collection",
                "LEASECOLL",
                "Cash and Cash Equivalents",
                "Land Lease Revenue",
                "Lease Collection",
            ),
            (
                "Associated Operating Expenses",
                "ASSOPEX",
                "Land Lease Operating Expenses",
                "Cash and Cash Equivalents",
                "Land Lease Operating Expenses",
            ),
            (
                "Leasing Costs",
                "LEASECOST",
                "Sales and Marketing Expense",
                "Cash and Cash Equivalents",
                "Land Leasing Costs",
            ),
            (
                "Sales Transaction Cost",
                "SALESTXCOST",
                "Sales and Marketing Expense",
                "Cash and Cash Equivalents",
                "Sales Transaction Cost",
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
                "Community Operations Expense - Amanah",
                "COMOPEXAM",
                "Community Operations Expense",
                "Cash and Cash Equivalents",
                "Community Operations Expense - Amanah",
            ),
            (
                "Community Operations Recovery - Amanah",
                "COMRECAM",
                "Cash and Cash Equivalents",
                "Community Operations Recovery",
                "Community Operations Recovery - Amanah",
            ),
            (
                "Community Operations Expense - ROSHN",
                "COMOPEXRO",
                "Community Operations Expense",
                "Cash and Cash Equivalents",
                "Community Operations Expense - ROSHN",
            ),
            (
                "Community Operations Recovery - ROSHN",
                "COMRECRO",
                "Cash and Cash Equivalents",
                "Community Operations Recovery",
                "Community Operations Recovery - ROSHN",
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
                "Office Rent and Utilities Expenses",
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
                "Marketing Expenses",
                "OHMKT",
                "Marketing Overhead Expense",
                "Cash and Cash Equivalents",
                "Marketing Expenses",
            ),
            (
                "Sales Cost Expenses",
                "OHSALES",
                "Sales Cost Overhead Expense",
                "Cash and Cash Equivalents",
                "Sales Cost Expenses",
            ),
            (
                "Additional Expenses",
                "OHADD",
                "Additional Overhead Expense",
                "Cash and Cash Equivalents",
                "Additional Expenses",
            ),
        ]

        _cfo_batches = []
        for (
            _cfo_line_item,
            _cfo_ref,
            _cfo_debit_account,
            _cfo_credit_account,
            _cfo_line_label,
        ) in _landco_cfo_journal_mappings:
            _cfo_line_df = fn_safe_extract_dataframe(
                source_dict=_landco_cfo,
                key=_cfo_line_item,
                source_name="LandCo Cashflow from Operations",
            )

            if _cfo_line_df.empty:
                print(
                    "LandCo CFO line item not found or empty for journal posting: "
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
                _cfo_is_line_item = _cfo_debit_account
            elif _credit_acct_type == "Revenue":
                _cfo_is_line_item = _cfo_credit_account

            _batch = fn_prepare_direct_cash_matrix_batch(
                source_df=_cfo_line_df,
                col_to_period=_landco_col_to_period,
                asset_unique_identifier=_asset_unique_identifier,
                debit_account=_cfo_debit_account,
                credit_account=_cfo_credit_account,
                cashflow_line_item=_cfo_line_label,
                line_item_name=f"LandCo CFO Journal - {_cfo_line_label}",
                reference_prefix=f"LC-CFO-{_cfo_ref}",
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
                interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
                type_aware_is_posting=True,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.1E: LandCo CFO Operating Entries")

        # --------------------------------------------------------------------
        # 9.2 Process LandCo Primary Infrastructure Entries
        # 9.3 Process LandCo Secondary Infrastructure Entries
        # --------------------------------------------------------------------
        _landco_primary_infra_progress = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Primary Infrastructure Cost S-Curve",
            source_name="LandCo Support Workings",
        )
        _landco_primary_infra_payment = fn_safe_extract_dataframe(
            source_dict=_landco_cfi,
            key="Primary Infrastructure Cost",
            source_name="LandCo Cashflow from Investments",
        )

        if _landco_primary_infra_progress.sum().sum() == 0.0:
            print(
                "Primary Infrastructure progress data is empty or zero. Check source data and keys."
            )
        elif _landco_primary_infra_payment.sum().sum() == 0.0:
            print(
                "Primary Infrastructure payment data is empty or zero. Check source data and keys."
            )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_primary_infrastructure_entries(
            primary_infra_progress_df=_landco_primary_infra_progress,
            primary_infra_payment_df=_landco_primary_infra_payment,
            col_to_period=_landco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            cashflow_line_item="Primary Infrastructure Cost",
            reference_prefix="LC-PI",
        )

        fn_record_timing(_timing_ctx, "PHASE 9.2: Primary Infrastructure Entries")

        _landco_secondary_infra_progress = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Secondary Infrastructure Cost S-Curve",
            source_name="LandCo Support Workings",
        )
        _landco_secondary_infra_payment = fn_safe_extract_dataframe(
            source_dict=_landco_cfi,
            key="Secondary Infrastructure Cost",
            source_name="LandCo Cashflow from Investments",
        )

        if _landco_secondary_infra_progress.sum().sum() == 0.0:
            print(
                "Secondary Infrastructure progress data is empty or zero. Check source data and keys."
            )
        elif _landco_secondary_infra_payment.sum().sum() == 0.0:
            print(
                "Secondary Infrastructure payment data is empty or zero. Check source data and keys."
            )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_secondary_infrastructure_entries(
            secondary_infra_progress_df=_landco_secondary_infra_progress,
            secondary_infra_payment_df=_landco_secondary_infra_payment,
            col_to_period=_landco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            cashflow_line_item="Secondary Infrastructure Cost",
            reference_prefix="LC-SI",
        )

        fn_record_timing(_timing_ctx, "PHASE 9.3: Secondary Infrastructure Entries")

        # # --------------------------------------------------------------------
        # # 9.3B Reclassify CWIP - Serviced Land at completion
        # # --------------------------------------------------------------------
        # # At the last non-zero CWIP entry period per asset, transfer the
        # # accumulated CWIP - Serviced Land balance to the appropriate account
        # # based on business model:
        # #   Land Lease / Land Bank:  Dr Land Assets              / Cr CWIP - Serviced Land
        # #   Land Sale:               Dr Inventory - Serviced Land / Cr CWIP - Serviced Land
        # # --------------------------------------------------------------------

        # _cwip_reclass_models = ["land lease", "land bank", "land sale"]
        # _cwip_reclass_mask = (
        #     _landco_business_model.str.strip().str.lower().isin(_cwip_reclass_models)
        #     if isinstance(_landco_business_model, pd.Series) and not _landco_business_model.empty
        #     else pd.Series(dtype=bool)
        # )

        # if not _cwip_reclass_mask.empty and _cwip_reclass_mask.any():
        #     # Collect all CFI source DataFrames that feed CWIP - Serviced Land.
        #     _cwip_source_keys = (
        #         [item[0] for item in _landco_cwip_direct_cash_items]
        #         + ["Primary Infrastructure Cost S-Curve", "Secondary Infrastructure Cost S-Curve"]
        #     )
        #     _cwip_source_dfs: List[pd.DataFrame] = []
        #     for _csk in _cwip_source_keys:
        #         # Try support workings first (S-curve), then CFI.
        #         _csk_df = fn_safe_extract_dataframe(
        #             source_dict=_landco_cfi, key=_csk,
        #             source_name="LandCo CFI",
        #         )
        #         if _csk_df.empty:
        #             _csk_df = fn_safe_extract_dataframe(
        #                 source_dict=_landco_support_workings, key=_csk,
        #                 source_name="LandCo Support Workings",
        #             )
        #         if not _csk_df.empty:
        #             _cwip_source_dfs.append(_csk_df)

        #     _period_cols_reclass = list(_landco_col_to_period.keys())
        #     _reclass_batch_entries: List[Dict[str, Any]] = []

        #     for _rc_row_pos in range(len(_cwip_reclass_mask)):
        #         if not _cwip_reclass_mask.iloc[_rc_row_pos]:
        #             continue

        #         # Determine asset UID.
        #         if _asset_unique_identifier is None or _rc_row_pos >= len(_asset_unique_identifier):
        #             continue
        #         _rc_uid = _asset_unique_identifier.iloc[_rc_row_pos]
        #         if _rc_uid is None or pd.isna(_rc_uid) or str(_rc_uid).strip() == "":
        #             continue

        #         # Find the last non-zero CWIP period for this asset across all sources.
        #         _last_cwip_col = None
        #         for _src_df in _cwip_source_dfs:
        #             if _rc_row_pos >= len(_src_df):
        #                 continue
        #             _row_vals = pd.to_numeric(
        #                 _src_df.iloc[_rc_row_pos].reindex(_period_cols_reclass),
        #                 errors="coerce",
        #             ).fillna(0.0)
        #             # Find rightmost non-zero column.
        #             _nonzero_cols = [c for c in _period_cols_reclass if abs(float(_row_vals.get(c, 0.0))) > 1e-2]
        #             if _nonzero_cols:
        #                 _candidate = _nonzero_cols[-1]
        #                 if _last_cwip_col is None:
        #                     _last_cwip_col = _candidate
        #                 else:
        #                     # Keep the later of the two.
        #                     if _period_cols_reclass.index(_candidate) > _period_cols_reclass.index(_last_cwip_col):
        #                         _last_cwip_col = _candidate

        #         if _last_cwip_col is None:
        #             continue

        #         _reclass_period = _landco_col_to_period.get(_last_cwip_col)
        #         if _reclass_period is None:
        #             continue

        #         # Get CWIP closing balance for this period.
        #         _cwip_acct_rc = _all_accounts.get("CWIP - Serviced Land")
        #         if _cwip_acct_rc is None or _cwip_acct_rc.empty:
        #             continue
        #         if _reclass_period not in _cwip_acct_rc.columns:
        #             continue
                
        #         _cwip_bal = float(_cwip_acct_rc.loc["Opening Balance", _reclass_period]) + float(_cwip_acct_rc.loc["Debit", _reclass_period])
        #         # Use a rounding tolerance to avoid floating-point dust.
        #         if _cwip_bal < 0.01:
        #             continue
        #         _cwip_bal = round(_cwip_bal, 2)
                
        #         # Choose debit account based on business model.
        #         _bm_val = str(_landco_business_model.iloc[_rc_row_pos]).strip().lower()
        #         if _bm_val in ("land lease", "land bank"):
        #             _debit_acct_reclass = "Land Assets"
        #         else:
        #             # Land Sale
        #             _debit_acct_reclass = "Inventory - Serviced Land"

        #         _reclass_batch_entries.append({
        #             "debit_account": _debit_acct_reclass,
        #             "credit_account": "CWIP - Serviced Land",
        #             "amount": _cwip_bal,
        #             "period": _reclass_period,
        #             "income_statement_line_item": None,
        #             "cashflow_line_item": None,
        #             "description": f"CWIP reclassification to {_debit_acct_reclass} - Asset {_rc_uid}",
        #             "reference": f"LC-CWIP-RECLASS-{_rc_row_pos}-{_last_cwip_col}",
        #         })

        #     if _reclass_batch_entries:
        #         _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
        #             batch_entries=_reclass_batch_entries,
        #             accounts=_all_accounts,
        #             journal=_accounting_journal,
        #             financial_statements=_financial_statements,
        #             account_names_dict=_account_names_dict,
        #         )
            
        fn_record_timing(_timing_ctx, "PHASE 9.3B: CWIP to Land Assets Reclassification")

        # --------------------------------------------------------------------
        # 9.4 Process LandCo Land Sales Entries
        # --------------------------------------------------------------------
        # Revenue recognition based on Total Infrastructure S-Curve, cost
        # recognition proportional to the same S-curve, collections split
        # by escrow applicability, and escrow release entries.
        # --------------------------------------------------------------------

        _landco_land_sales_revenue = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Land Sales Revenue",
            source_name="LandCo Support Workings",
        )

        _landco_total_infra_s_curve = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Total Infrastructure Cost S-Curve",
            source_name="LandCo Support Workings",
        )

        _landco_on_plan_sales_collection = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="On-plan Sales Collection",
            source_name="LandCo Support Workings",
        )

        _landco_inflows_to_escrow = fn_safe_extract_dataframe(
            source_dict=_landco_escrow_schedule,
            key="Inflows to Escrow",
            source_name="LandCo Escrow Schedule",
        )

        _landco_escrow_release = fn_safe_extract_dataframe(
            source_dict=_landco_escrow_schedule,
            key="Off-plan Cash Inflow",
            source_name="LandCo Escrow Schedule",
        )

        _landco_escrow_applicability = fn_extract_assumptions(
            _landco_asset_assumptions,
            "LandSalesModule",
            "escrow_applicability",
        )

        # Filter collections by escrow applicability.
        # Non-escrow assets: use On-plan Sales Collection, zero out escrow assets.
        # Escrow assets: use Inflows to Escrow, zero out non-escrow assets.
        _escrow_mask = (
            _landco_escrow_applicability.str.strip().str.lower().isin(["yes", "true", "1"])
            if isinstance(_landco_escrow_applicability, pd.Series) and not _landco_escrow_applicability.empty
            else pd.Series(dtype=bool)
        )

        # Business model gate: only "Land Sale" assets participate in sales entries.
        _land_sale_mask = (
            _landco_business_model.str.strip().str.lower().eq("land sale")
            if isinstance(_landco_business_model, pd.Series) and not _landco_business_model.empty
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

        # Zero out non-Land Sale rows from all sales source DFs.
        _landco_land_sales_revenue = _zero_out_non_matching(_landco_land_sales_revenue, _land_sale_mask, keep=True)
        _landco_total_infra_s_curve = _zero_out_non_matching(_landco_total_infra_s_curve, _land_sale_mask, keep=True)
        _landco_on_plan_sales_collection = _zero_out_non_matching(_landco_on_plan_sales_collection, _land_sale_mask, keep=True)
        _landco_inflows_to_escrow = _zero_out_non_matching(_landco_inflows_to_escrow, _land_sale_mask, keep=True)
        _landco_escrow_release = _zero_out_non_matching(_landco_escrow_release, _land_sale_mask, keep=True)

        _collection_non_escrow = _landco_on_plan_sales_collection.copy() if not _landco_on_plan_sales_collection.empty else pd.DataFrame()
        _collection_escrow = _landco_inflows_to_escrow.copy() if not _landco_inflows_to_escrow.empty else pd.DataFrame()

        # Zero out rows based on escrow flag.
        # For escrow assets: keep _collection_non_escrow as-is because
        # On-plan Sales Collection already contains only post-construction
        # amounts for escrow assets. These are direct cash collections that
        # bypass escrow entirely.
        # For non-escrow assets: keep _collection_non_escrow as-is (all their
        # collections go through this path).
        # Only zero out non-escrow assets in _collection_escrow (already done
        # below) so they don't get escrow entries.

        if not _collection_escrow.empty and not _escrow_mask.empty:
            for idx_pos, is_esc in enumerate(_escrow_mask):
                if not is_esc and idx_pos < len(_collection_escrow):
                    _collection_escrow.iloc[idx_pos] = 0.0

        # Extract capitalized interest DFs early so they can be included
        # in the CWIP cost pool for cost-of-sales recognition.
        _lc_arev_cap_interest = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Asset Revolver - Capitalized Interest",
            source_name="LandCo Support Workings",
        )
        _lc_prev_cap_interest = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Project Revolver - Capitalized Interest",
            source_name="LandCo Support Workings",
        )
        _lc_tl_cap_interest = fn_safe_extract_dataframe(
            source_dict=_landco_support_workings,
            key="Project Term Loan - Capitalized Interest",
            source_name="LandCo Support Workings",
        )

        # Build total CWIP S-curve (infrastructure + all direct CWIP costs
        # + capitalized interest) so cost of sales credits include all
        # amounts capitalized to CWIP.
        _landco_total_cwip_s_curve = _landco_total_infra_s_curve.abs()
        if not _cwip_direct_cash_sum.empty:
            _cwip_direct_cash_masked = _zero_out_non_matching(
                _cwip_direct_cash_sum, _land_sale_mask, keep=True
            )
            # Reindex to the infra S-curve columns to prevent duplicate
            # column labels from column-type mismatches (Support Workings vs CFI).
            _cwip_aligned = _cwip_direct_cash_masked.reindex(
                columns=_landco_total_cwip_s_curve.columns, fill_value=0.0
            )
            _landco_total_cwip_s_curve = pd.DataFrame(
                _landco_total_cwip_s_curve.values + _cwip_aligned.values,
                index=_landco_total_cwip_s_curve.index,
                columns=_landco_total_cwip_s_curve.columns,
            )

        # Add capitalized interest to CWIP S-curve.
        # In filtered modes, include only asset-level financing effects.
        _cap_interest_sources = [_lc_arev_cap_interest]
        if not _is_single_asset_mode:
            _cap_interest_sources.extend([_lc_prev_cap_interest, _lc_tl_cap_interest])

        for _cap_int_df in _cap_interest_sources:
            if isinstance(_cap_int_df, pd.DataFrame) and not _cap_int_df.empty:
                _cap_int_aligned = _cap_int_df.abs().reindex(
                    index=_landco_total_cwip_s_curve.index,
                    columns=_landco_total_cwip_s_curve.columns,
                    fill_value=0.0,
                ).fillna(0.0)
                _landco_total_cwip_s_curve = pd.DataFrame(
                    _landco_total_cwip_s_curve.values + _cap_int_aligned.values,
                    index=_landco_total_cwip_s_curve.index,
                    columns=_landco_total_cwip_s_curve.columns,
                )

        # Build total cost incurred DF for COGS calculation.
        # Combines land acquisition (cash + in-kind + transaction costs) with
        # CWIP S-curve costs (including capitalized interest).
        _landco_total_cost_incurred = _landco_total_cwip_s_curve.copy()
        _all_land_cost_sources = [_landco_land_acquisition_cash, _landco_land_acquisition_cost_in_kind] + _landco_acquisition_txn_cost_dfs
        for _cost_source in _all_land_cost_sources:
            if isinstance(_cost_source, pd.DataFrame) and not _cost_source.empty:
                _cost_aligned = _cost_source.abs().reindex(
                    index=_landco_total_cost_incurred.index,
                    columns=_landco_total_cost_incurred.columns,
                    fill_value=0.0,
                ).fillna(0.0)
                _landco_total_cost_incurred = pd.DataFrame(
                    _landco_total_cost_incurred.values + _cost_aligned.values,
                    index=_landco_total_cost_incurred.index,
                    columns=_landco_total_cost_incurred.columns,
                )

        _all_accounts, _accounting_journal, _financial_statements = fn_process_land_sales_entries(
            revenue_df=_landco_land_sales_revenue,
            s_curve_df=_landco_total_cwip_s_curve,
            collection_non_escrow_df=_collection_non_escrow,
            collection_escrow_df=_collection_escrow,
            escrow_release_df=_landco_escrow_release,
            escrow_applicability=_landco_escrow_applicability,
            col_to_period=_landco_col_to_period,
            asset_unique_identifier=_asset_unique_identifier,
            accounts=_all_accounts,
            journal=_accounting_journal,
            financial_statements=_financial_statements,
            account_names_dict=_account_names_dict,
            reference_prefix="LC-SALES",
            exit_counterparty=_interparty_mapping["LandCo_Exit_Counterparty"] if isinstance(_interparty_mapping, pd.DataFrame) and not _interparty_mapping.empty and "LandCo_Exit_Counterparty" in _interparty_mapping.columns else None,
            cost_incurred_df=_landco_total_cost_incurred,
            cwip_cost_incurred_df=_landco_total_cwip_s_curve,
        )

        fn_record_timing(_timing_ctx, "PHASE 9.4: Land Sales Entries")

        # --------------------------------------------------------------------
        # 9.5 Process LandCo Debt & Financing Entries
        # --------------------------------------------------------------------
        # Revolvers: split repayment into interest expense vs principal using
        # capitalized interest comparison. Term Loan: uses pre-split fields.
        # All capitalized interest capitalizes to CWIP - Serviced Land.
        #
        # NOTE: In filtered modes, only asset-level financing is posted.
        #       Project-level financing and input equity are ignored, then
        #       balancing equity is derived from net cashflow.
        # --------------------------------------------------------------------

        if not _is_single_asset_mode:

            # --- Asset Revolver (asset-level, from Support Workings) ---
            _lc_arev_drawdown = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Debt Drawdown",
                source_name="LandCo Support Workings",
            )
            # _lc_arev_cap_interest extracted earlier (before Phase 9.4)
            _lc_arev_repayment = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Debt Repayment",
                source_name="LandCo Support Workings",
            )
            _lc_arev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Arrangement Fees",
                source_name="LandCo Support Workings",
            )
            _lc_arev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Commitment Fees Payment",
                source_name="LandCo Support Workings",
            )

            # --- Project Revolver (project-level, from Support Workings) ---
            _lc_prev_drawdown = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Revolver - Debt Drawdown",
                source_name="LandCo Support Workings",
            )
            # _lc_prev_cap_interest extracted earlier (before Phase 9.4)
            _lc_prev_repayment = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Revolver - Debt Repayment",
                source_name="LandCo Support Workings",
            )
            _lc_prev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Revolver - Arrangement Fees",
                source_name="LandCo Support Workings",
            )
            _lc_prev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Revolver - Commitment Fees Payment",
                source_name="LandCo Support Workings",
            )

            # --- Term Loan (project-level, from Support Workings + CFF) ---
            _lc_tl_drawdown = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Term Loan - Debt Drawdown",
                source_name="LandCo Support Workings",
            )
            # _lc_tl_cap_interest extracted earlier (before Phase 9.4)
            _lc_tl_principal_repayment = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Term Loan - Principal Repayment",
                source_name="LandCo Support Workings",
            )
            _lc_tl_balloon = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Term Loan - Balloon Payment",
                source_name="LandCo Support Workings",
            )
            _lc_tl_interest_expensed = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Project Term Loan - Interest Payment",
                source_name="LandCo Support Workings",
            )
            # Term loan fees are in CFF (not in Support Workings).
            _lc_tl_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_landco_cff,
                key="Term Loan - Arrangement Fees",
                source_name="LandCo CFF",
            )
            _lc_tl_valuation_fees = fn_safe_extract_dataframe(
                source_dict=_landco_cff,
                key="Term Loan - Valuation Fees",
                source_name="LandCo CFF",
            )
            _lc_tl_other_fees = fn_safe_extract_dataframe(
                source_dict=_landco_cff,
                key="Term Loan - Other Debt Fees",
                source_name="LandCo CFF",
            )

            # --- Equity Infusion (project-level, from CFF) ---
            _lc_equity_infusion = fn_safe_extract_dataframe(
                source_dict=_landco_cff,
                key="Equity Infusion",
                source_name="LandCo CFF",
            )

            _debt_facility_configs = [
                {
                    "name": "Asset Revolver",
                    "type": "revolver",
                    "loan_account": "Debt - Revolver",
                    "interest_expense_account": "Interest Expense - Revolver",
                    "cf_drawdown": "Revolver - Debt Drawdown",
                    "cf_repayment": "Revolver - Debt Repayment",
                    "cf_interest": "Revolver - Interest Payments",
                    "cf_fees": "Revolver - Debt Fees",
                    "ref_prefix": "LC-AREV",
                    "drawdown_df": _lc_arev_drawdown,
                    "cap_interest_df": _lc_arev_cap_interest,
                    "repayment_df": _lc_arev_repayment,
                    "arrangement_fees_df": _lc_arev_arrangement_fees,
                    "commitment_fees_df": _lc_arev_commitment_fees,
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
                    "ref_prefix": "LC-PREV",
                    "drawdown_df": _lc_prev_drawdown,
                    "cap_interest_df": _lc_prev_cap_interest,
                    "repayment_df": _lc_prev_repayment,
                    "arrangement_fees_df": _lc_prev_arrangement_fees,
                    "commitment_fees_df": _lc_prev_commitment_fees,
                },
                {
                    "name": "Term Loan",
                    "type": "term_loan",
                    "loan_account": "Debt - Term Loan",
                    "interest_expense_account": "Interest Expense - Term Loan",
                    "cf_drawdown": "Term Loan - Debt Drawdown",
                    "cf_repayment": "Term Loan - Debt Repayment",
                    "cf_interest": "Term Loan - Interest Payments",
                    "cf_fees": "Term Loan - Debt Fees",
                    "ref_prefix": "LC-TL",
                    "drawdown_df": _lc_tl_drawdown,
                    "cap_interest_df": _lc_tl_cap_interest,
                    "repayment_df": pd.DataFrame(),
                    "arrangement_fees_df": _lc_tl_arrangement_fees,
                    "commitment_fees_df": pd.DataFrame(),
                    "principal_repayment_df": _lc_tl_principal_repayment,
                    "balloon_df": _lc_tl_balloon,
                    "interest_expensed_df": _lc_tl_interest_expensed,
                    "valuation_fees_df": _lc_tl_valuation_fees,
                    "other_fees_df": _lc_tl_other_fees,
                },
            ]

            _all_accounts, _accounting_journal, _financial_statements = fn_process_landco_debt_entries(
                facility_configs=_debt_facility_configs,
                equity_infusion_df=_lc_equity_infusion,
                col_to_period=_landco_col_to_period,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                reference_prefix="LC-DEBT",
            )

        else:
            # ----------------------------------------------------------------
            # 9.5B Filtration Mode — Asset Financing + Balancing Equity
            # ----------------------------------------------------------------
            # In filtered modes (single-asset / synthetic):
            # - Keep asset-level financing entries.
            # - Zero out project-level financing inputs by not processing them.
            # - Ignore input Equity Infusion.
            # - Post balancing equity per period based on:
            #     Equity = -(CFO + CFI + Asset-Level Financing Cashflow)
            # ----------------------------------------------------------------
            print(
                "Filtration mode detected: applying asset-level financing only "
                f"with balancing equity for asset filter '{_ASSET_FILTER_MODE}'."
            )

            # --- Asset Revolver (asset-level, from Support Workings) ---
            _lc_arev_drawdown = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Debt Drawdown",
                source_name="LandCo Support Workings",
            )
            # _lc_arev_cap_interest extracted earlier (before Phase 9.4)
            _lc_arev_repayment = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Debt Repayment",
                source_name="LandCo Support Workings",
            )
            _lc_arev_arrangement_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Arrangement Fees",
                source_name="LandCo Support Workings",
            )
            _lc_arev_commitment_fees = fn_safe_extract_dataframe(
                source_dict=_landco_support_workings,
                key="Asset Revolver - Commitment Fees Payment",
                source_name="LandCo Support Workings",
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

            _lc_arev_drawdown = _mask_df_to_selected_assets(_lc_arev_drawdown)
            _lc_arev_cap_interest = _mask_df_to_selected_assets(_lc_arev_cap_interest)
            _lc_arev_repayment = _mask_df_to_selected_assets(_lc_arev_repayment)
            _lc_arev_arrangement_fees = _mask_df_to_selected_assets(_lc_arev_arrangement_fees)
            _lc_arev_commitment_fees = _mask_df_to_selected_assets(_lc_arev_commitment_fees)

            _debt_facility_configs_filtered = [
                {
                    "name": "Asset Revolver",
                    "type": "revolver",
                    "loan_account": "Debt - Revolver",
                    "interest_expense_account": "Interest Expense - Revolver",
                    "cf_drawdown": "Revolver - Debt Drawdown",
                    "cf_repayment": "Revolver - Debt Repayment",
                    "cf_interest": "Revolver - Interest Payments",
                    "cf_fees": "Revolver - Debt Fees",
                    "ref_prefix": "LC-AREV",
                    "drawdown_df": _lc_arev_drawdown,
                    "cap_interest_df": _lc_arev_cap_interest,
                    "repayment_df": _lc_arev_repayment,
                    "arrangement_fees_df": _lc_arev_arrangement_fees,
                    "commitment_fees_df": _lc_arev_commitment_fees,
                },
            ]

            # Ignore project-level financing and input equity in filtered mode.
            _all_accounts, _accounting_journal, _financial_statements = fn_process_landco_debt_entries(
                facility_configs=_debt_facility_configs_filtered,
                equity_infusion_df=pd.DataFrame(),
                col_to_period=_landco_col_to_period,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                reference_prefix="LC-DEBT-FILT",
            )

            # Balancing equity uses net period cash impact after CFO/CFI and
            # asset-level financing postings in filtered mode.
            _period_cash_net: Dict[str, float] = {}
            for _period_val in _landco_col_to_period.values():
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
            for _period_col, _period_str in _landco_col_to_period.items():
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
                        "reference": f"LC-DEBT-FILT-BEQ-RAISE-{_period_col}",
                    })

            if _equity_balance_entries:
                _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                    batch_entries=_equity_balance_entries,
                    accounts=_all_accounts,
                    journal=_accounting_journal,
                    financial_statements=_financial_statements,
                    account_names_dict=_account_names_dict,
                    interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
                    type_aware_is_posting=True,
                )

        fn_record_timing(_timing_ctx, "PHASE 9.5: Debt & Financing Entries")

        # --------------------------------------------------------------------
        # 9.6 Process LandCo Exit Value Entries (Land Bank / Land Lease)
        # --------------------------------------------------------------------
        # For assets with business_model = "Land Bank" or "Land Lease",
        # when terminal / exit value cashflow is non-zero:
        #   Dr Cash / Cr Land Assets (for book value of Land Assets)
        #   Dr Cash / Cr CWIP - Serviced Land (for book value of CWIP)
        #   Gain or Loss = CF amount - (Land Assets + CWIP) book value
        #   If gain > 0: Dr Cash / Cr Gain on Asset Disposal (net already in Cash)
        #   If loss > 0: Dr Loss on Asset Disposal / Cr Cash
        #   CF line: "Land Lease - Terminal Value" or "Land Bank - Exit Value"
        # --------------------------------------------------------------------

        _exit_value_items = [
            ("Land Lease - Terminal Value", "LLTV"),
            ("Land Bank - Exit Value", "LBEV"),
        ]

        # Build mask for Land Bank / Land Lease assets.
        _exit_model_mask = (
            _landco_business_model.str.strip().str.lower().isin(["land bank", "land lease"])
            if isinstance(_landco_business_model, pd.Series) and not _landco_business_model.empty
            else pd.Series(dtype=bool)
        )

        _exit_batch_entries: List[Dict[str, Any]] = []

        for _exit_cf_label, _exit_ref in _exit_value_items:
            _exit_df = fn_safe_extract_dataframe(
                source_dict=_landco_cfi,
                key=_exit_cf_label,
                source_name="LandCo CFI",
            )
            if _exit_df.empty:
                continue

            _exit_df_local = _exit_df.copy()
            _exit_df_local.index = _exit_df_local.index.map(lambda x: str(x).strip())

            _period_cols_exit = list(_landco_col_to_period.keys())
            _period_map_exit = [(_pc, _landco_col_to_period.get(_pc)) for _pc in _period_cols_exit]

            for _asset_row_idx, _asset_uid in zip(_exit_df_local.index, _asset_unique_identifier):
                if _asset_uid is None or pd.isna(_asset_uid) or str(_asset_uid).strip() == "":
                    continue

                # Track start position for interparty elimination post-processing.
                _asset_start_pos = len(_exit_batch_entries)

                # Only process Land Bank / Land Lease assets.
                try:
                    _row_pos = _exit_df_local.index.get_loc(_asset_row_idx)
                except KeyError:
                    continue

                if not _exit_model_mask.empty and _row_pos < len(_exit_model_mask):
                    if not _exit_model_mask.iloc[_row_pos]:
                        continue

                _exit_vals = np.abs(
                    pd.to_numeric(
                        _exit_df_local.loc[_asset_row_idx].reindex(_period_cols_exit),
                        errors="coerce",
                    ).fillna(0.0).to_numpy(dtype="float64")
                )

                for _p_idx, (_p_col, _p_str) in enumerate(_period_map_exit):
                    if _p_str is None:
                        continue
                    _exit_amt = float(_exit_vals[_p_idx])
                    if _exit_amt <= 0.0:
                        continue

                    # Get current Land Assets + CWIP book values for this period.
                    _land_assets_acct = _all_accounts.get("Land Assets")
                    _land_bv = 0.0
                    if _land_assets_acct is not None and not _land_assets_acct.empty and _p_str in _land_assets_acct.columns:
                        _land_bv = max(0.0, float(_land_assets_acct.loc["Closing Balance", _p_str]))

                    _cwip_acct = _all_accounts.get("CWIP - Serviced Land")
                    _cwip_bv = 0.0
                    if _cwip_acct is not None and not _cwip_acct.empty and _p_str in _cwip_acct.columns:
                        _cwip_bv = max(0.0, float(_cwip_acct.loc["Closing Balance", _p_str]))

                    _book_value = _land_bv + _cwip_bv

                    # Fully derecognize Land Assets at book value.
                    if _land_bv > 0.0:
                        _exit_batch_entries.append({
                            "debit_account": "Cash and Cash Equivalents",
                            "credit_account": "Land Assets",
                            "amount": _land_bv,
                            "period": _p_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": _exit_cf_label,
                            "description": f"{_exit_cf_label} - Derecognize Land Assets - Asset {_asset_row_idx}",
                            "reference": f"LC-{_exit_ref}-DEREC-{_asset_row_idx}-{_p_col}",
                        })

                    # Fully derecognize CWIP - Serviced Land at book value.
                    if _cwip_bv > 0.0:
                        _exit_batch_entries.append({
                            "debit_account": "Cash and Cash Equivalents",
                            "credit_account": "CWIP - Serviced Land",
                            "amount": _cwip_bv,
                            "period": _p_str,
                            "income_statement_line_item": None,
                            "cashflow_line_item": _exit_cf_label,
                            "description": f"{_exit_cf_label} - Derecognize CWIP - Asset {_asset_row_idx}",
                            "reference": f"LC-{_exit_ref}-DEREC-CWIP-{_asset_row_idx}-{_p_col}",
                        })

                    # Gain or loss = exit amount - total book value (Land Assets + CWIP).
                    _gain_loss = _exit_amt - _book_value

                    if _gain_loss > 0.0:
                        # Gain: Dr Cash / Cr Gain on Asset Disposal.
                        _exit_batch_entries.append({
                            "debit_account": "Cash and Cash Equivalents",
                            "credit_account": "Gain on Asset Disposal",
                            "amount": _gain_loss,
                            "period": _p_str,
                            "income_statement_line_item": "Gain on Asset Disposal",
                            "cashflow_line_item": _exit_cf_label,
                            "description": f"{_exit_cf_label} - Gain on Disposal - Asset {_asset_row_idx}",
                            "reference": f"LC-{_exit_ref}-GAIN-{_asset_row_idx}-{_p_col}",
                        })
                    elif _gain_loss < 0.0:
                        # Loss on disposal: Dr Loss / Cr Land Assets for
                        # the shortfall, plus Dr Cash / Cr Cash reversal so
                        # net cash = exit proceeds.
                        _exit_batch_entries.append({
                            "debit_account": "Loss on Asset Disposal",
                            "credit_account": "Cash and Cash Equivalents",
                            "amount": abs(_gain_loss),
                            "period": _p_str,
                            "income_statement_line_item": "Loss on Asset Disposal",
                            "cashflow_line_item": _exit_cf_label,
                            "description": f"{_exit_cf_label} - Loss on Disposal - Asset {_asset_row_idx}",
                            "reference": f"LC-{_exit_ref}-LOSS-{_asset_row_idx}-{_p_col}",
                        })

                # Interparty Elimination: reversed entries for DevCo exit assets.
                _is_devco_exit = False
                if not _interparty_mapping.empty and _row_pos < len(_interparty_mapping):
                    _exit_cp = _interparty_mapping.iloc[_row_pos].get("LandCo_Exit_Counterparty", None)
                    _is_devco_exit = str(_exit_cp).strip() == "DevCo" if _exit_cp is not None else False

                if _is_devco_exit and _ENABLE_INTERPARTY_ELIMINATION:
                    _ie_entries = []
                    for _base_entry in _exit_batch_entries[_asset_start_pos:]:
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
                    _exit_batch_entries.extend(_ie_entries)

        if _exit_batch_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_exit_batch_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
                interparty_cash_name="Cash and Cash Equivalents - Interparty Elimination",
                type_aware_is_posting=True,
            )

        fn_record_timing(_timing_ctx, "PHASE 9.6: Exit Value Entries")

        # --------------------------------------------------------------------
        # 9.7 Period-End Closing Entries
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
            # Scan the journal for interparty elimination tracking entries whose
            # references contain -IPRE- (revenue) or -IPCE- (COGS) with an asset_idx
            # token.  Revenue entries credit a nominal IE account (positive net income);
            # COGS entries debit a nominal IE account (positive net income reduction).
            _period_to_idx: Dict[str, int] = {_p: _i for _i, _p in enumerate(_all_period_strs)}
            _asset_ie_rev: Dict[str, np.ndarray] = {}   # asset_idx_str -> per-period array
            _asset_ie_exp: Dict[str, np.ndarray] = {}
            for _je in _accounting_journal:
                _ref = str(_je.get("reference", ""))
                _amt = float(_je.get("amount", 0.0) or 0.0)
                _p_str = str(_je.get("period", ""))
                _p_idx = _period_to_idx.get(_p_str)
                if _p_idx is None or abs(_amt) < 1e-9:
                    continue
                if "-IPRE-" in _ref:
                    # Extract asset_idx from reference: prefix-IPRE-{asset_idx}-period
                    _parts = _ref.split("-IPRE-", 1)
                    if len(_parts) == 2:
                        _aid = _parts[1].split("-")[0]
                        if _aid not in _asset_ie_rev:
                            _asset_ie_rev[_aid] = np.zeros(_n_periods, dtype=float)
                        _asset_ie_rev[_aid][_p_idx] += _amt
                elif "-IPCE-" in _ref:
                    _parts = _ref.split("-IPCE-", 1)
                    if len(_parts) == 2:
                        # SLA references have format -IPCE-SLA-{asset_idx}-period
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

            # Step 1: Close Revenue accounts to P&L
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
                    _abs_neg = np.abs(_net[_neg_mask])
                    for _p, _a in zip(_period_arr[_neg_mask], _abs_neg):
                        _all_closing_entries.append({
                            "debit_account": "Profit & Loss", "credit_account": _rev_name,
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry: P&L reversal for {_rev_name}",
                            "reference": "CLOSING-REV-IE",
                        })
                    _pl_net_from_closing[_neg_mask] += _net[_neg_mask]

            # Step 2: Close Expense accounts to P&L
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
                    _abs_neg = np.abs(_net[_neg_mask])
                    for _p, _a in zip(_period_arr[_neg_mask], _abs_neg):
                        _all_closing_entries.append({
                            "debit_account": _exp_name, "credit_account": "Profit & Loss",
                            "amount": float(_a), "period": str(_p),
                            "income_statement_line_item": None, "cashflow_line_item": None,
                            "description": f"Closing entry: {_exp_name} reversal to P&L",
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
            # The journal entries post at consolidated level (correct for account
            # rollforward); per-asset trace rows are appended separately below.
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
            # These carry the same values as the consolidated closing entries but
            # are split by asset so the trace DF reflects asset-level attribution.
            # Calculation: asset_ie_net[asset][period] = asset_ie_rev - asset_ie_exp
            # which mirrors _pre_closing_ie_net_arr but scoped to one asset.
            for _aid, _aid_ie_net_arr in _asset_pre_closing_ie_net.items():
                for _pi, (_p_str, _ie_net) in enumerate(zip(_all_period_strs, _aid_ie_net_arr)):
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

        fn_record_timing(_timing_ctx, "PHASE 9.7: Period-End Closing Entries")


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
            _income_statement_monthly, _income_statement_structure
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
                "LandCo Timeline DF": _landco_timeline_df if _landco_timeline_df is not None and not _landco_timeline_df.empty else pd.DataFrame([{"placeholder": "No LandCo timeline DF"}]),
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
                "LandCo Col to Period Map": pd.DataFrame([{"col": k, "period": v} for k, v in _landco_col_to_period.items()]) if _landco_col_to_period else pd.DataFrame([{"placeholder": "No column to period mapping"}]),
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
        _timing_summary = fn_finalize_timing_summary(_timing_ctx, "PHASE 13: Final Assembly", entity_label="LANDCO CONSOLIDATION")
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
            "interparty_mapping": _interparty_mapping,
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

def fninitialising_all_values(payload: Any) -> Optional[Any]:
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