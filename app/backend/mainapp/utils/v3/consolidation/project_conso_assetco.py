"""
================================================================================
ASSETCO CONSOLIDATED MODEL - VERSION 3
================================================================================

This module provides the AssetCo consolidation framework for building unified
financial statements and cashflows from AssetCo payloads.

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
    fn_build_annual_dataframe,
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
    fn_record_journal_entry_vectorized,
    fn_initialize_financial_statement,
    fn_record_financial_statement_entry,
    fn_record_financial_statement_entry_vectorized,
    fn_create_all_financial_statements,
    fn_record_integrated_entry,
    fn_resolve_signed_cashflow_amount,
    fn_flush_batch_entries,
    fn_build_flush_index_maps,
    fn_flush_matrix_entries,
    fn_propagate_opening_balances,
    fn_get_account_balance,
    fn_process_cashflow_line_item,
    fn_build_direct_cash_batch_entries,
    fn_process_direct_cash_capex_line_item_entries,
    fn_get_row_by_compatible_index,
    fn_build_financial_statement_trace_dataframe,
    fn_add_unique_id_to_trace_df,
    fn_trace_dataframe_to_payload,
    fn_append_financial_statement_trace_row,
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
    Main wrapper for AssetCo consolidated model pre-processing and execution.
    
    This function orchestrates the entire AssetCo consolidation pipeline from
    raw payload extraction through financial statement generation.

    Workflow Phases:
    ----------------
    PHASE 1: Extract Input Sources
        - Extract AssetCo and JV data from payload
        - Initialize target containers for each module
        
    PHASE 2: Define Consolidated Cashflow Template
        - Build CFO/CFI/CFF structure with all line items
        
    PHASE 3: Extract Section Data
        - Populate target containers using module key mappings
        
    PHASE 4: Normalize AssetCo Nested Outputs
        - Extract monthly/annual DataFrames from AssetCo outputs
        
    PHASE 5: Build Shared Timeline
        - Build template row index for consolidated DataFrame
        
    PHASE 6: Account and Financial Statement Structures
        - Define account names dictionary
        - Define balance sheet, income statement structures
        
    PHASE 7: Initialize Accounts and Statements
        - Create all double-entry accounts
        - Initialize financial statements
        
    PHASE 9: AssetCo Calculation Logic
        - 9.0:  Build AssetCo Period Mapping
        - 9.0B: AssetCo Asset Filter and DF Extraction
        - 9.1:  AssetCo CFI Acquisition Entries
        - 9.1E: AssetCo CFO Operating Entries
        - 9.1F: Sinking Fund & Maintenance Capex Entries
        - 9.1G: Tenant Fitout Allowance Entries
        - 9.5:  AssetCo CFF Debt & Financing Entries
        - 9.5B: AssetCo Depreciation Entries
        - 9.5C: Maintenance Capex Depreciation Entries
        - 9.6:  AssetCo Asset Sale / Exit Value Entries
        - 9.7:  Net Income ? Retained Earnings
        
    PHASE 10: Build Output Structures
        - Create monthly_dfs, annual_dfs, excel_output

    Parameters:
    -----------
    payload : Any
        Raw input payload containing:
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
        #   "<asset_id>"    ? process only the selected asset.
        #   "Synthetic"     ? process only synthetic-selected assets.
        # In filtered modes, AssetCo still processes asset-level financing
        # for the active assets (no financing skip gate).
        # Dynamically read from payload (injected by consolidated_model.py).
        # --------------------------------------------------------------------
        _ASSET_FILTER_MODE: str = payload.get("_asset_filter_mode", "Consolidated") if isinstance(payload, dict) else "Consolidated"

        # ====================================================================
        # PHASE 1: EXTRACT INPUT SOURCES
        # ====================================================================
        
        _landco_source, _devco_source, _assetco_source, _jv_source = fn_extract_core_sources(payload)

        _devco_timeline = {}
        _devco_support_workings = {}
        _devco_cfi = {}

        _landco_global_assumptions = {}
        _landco_asset_assumptions = {}
        _landco_support_workings = {}
        _landco_cfi = {}

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

        # Depreciation-related inputs per asset (extracted from assetco_inputs)
        _assetco_acquisition_price = {}
        _assetco_residual_value = {}
        _assetco_holding_period = {}
        _assetco_acquisition_date = {}
        _assetco_asset_sale_date = {}

        _assetco_number_of_assets = len(_assetco_source) if isinstance(_assetco_source, list) else 0
        
        _module_key_mapping: Dict[str, Dict[str, Any]] = {
            "LandCo": {
                "global_assumptions": _landco_global_assumptions,
                "asset_assumptions": _landco_asset_assumptions,
                "Support Workings": _landco_support_workings,
                "Cashflow from Investments": _landco_cfi,
            },
            "DevCo": {
                "Timeline": _devco_timeline,
                "Support Workings": _devco_support_workings,
                "Cashflow from Investments": _devco_cfi,
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
                "Hospitality Revenue": [
                    "Hospitality - Room Revenue",
                    "Hospitality - F&B Revenue",
                    "Hospitality - OOD Revenue",
                    "Hospitality - Other Operating Income",
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

            # Extract depreciation-related numeric inputs per asset
            _assetco_acquisition_price[index] = _assetco_inputs.get("acquisition_price", None)
            _assetco_residual_value[index] = _assetco_inputs.get("residual_value", None)
            _assetco_holding_period[index] = _assetco_inputs.get("holding_period", None)
            _assetco_acquisition_date[index] = _assetco_inputs.get("acquisition_date", None)
            _assetco_asset_sale_date[index] = _assetco_inputs.get("asset_sale_date", None)

        fn_record_timing(_timing_ctx, "PHASE 4: Normalize AssetCo Outputs")

        # ====================================================================
        # PHASE 5: BUILD SHARED TIMELINE AND TEMPLATE INDEX
        # ====================================================================
        master_timeline_df = fn_build_master_timeline(_devco_timeline)

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
        # PHASE 5B: INTERPARTY ACQUISITION AND EXIT COUNTERPARTY MAPPING
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

        _lc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "landco_inclusion")
        _dc_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "devco_inclusion")
        _ac_jv_inclusion = fn_extract_assumptions(_landco_asset_assumptions, "JVModule", "assetco_inclusion")


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

        fn_record_timing(_timing_ctx, "PHASE 5B: Interparty Mapping")

        # ====================================================================
        # PHASE 6: ACCOUNT AND FINANCIAL STATEMENT STRUCTURES
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

        fn_record_timing(_timing_ctx, "PHASE 6: Financial Statement Structures")

        # ====================================================================
        # PHASE 7: INITIALIZE ACCOUNTS AND FINANCIAL STATEMENTS
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

        fn_record_timing(_timing_ctx, "PHASE 7: Initialize Accounts")

        # ====================================================================
        # PHASE 9: ASSETCO CALCULATION LOGIC
        # ====================================================================
        # This phase contains the AssetCo calculation logic:
        # - Processing AssetCo CFI acquisition entries
        # - Processing AssetCo CFO operating entries
        # - Sinking fund & maintenance capex entries
        # - AssetCo CFF debt & financing entries
        # - AssetCo asset sale / exit value entries
        # - Journal entry recording
        # ====================================================================

        # --------------------------------------------------------------------
        # 9.0 Build AssetCo Period End Mapping
        # --------------------------------------------------------------------
        # AssetCo cashflows have numeric columns (0, 1, 2, ...) that need to
        # be mapped to period end dates for recording in accounts/statements.
        # --------------------------------------------------------------------
        
        _assetco_timeline_df = fn_json_dict_to_dataframe(_assetco_timeline[0]) if _assetco_timeline[0] else None
        _assetco_period_ends_series = (
            pd.to_datetime(_assetco_timeline_df.loc["Period End"]).dt.normalize()
            if _assetco_timeline_df is not None and "Period End" in _assetco_timeline_df.index
            else pd.Series()
        )
        # Create mapping: column index (int or str) -> period end date string
        # Note: Use strftime to match the format used in account/statement columns ('YYYY-MM-DD')
        _assetco_col_to_period: Dict[Any, str] = {}
        for col_idx, period_end in _assetco_period_ends_series.items():
            _assetco_col_to_period[col_idx] = period_end.strftime('%Y-%m-%d')

        fn_record_timing(_timing_ctx, "PHASE 9.0: Build AssetCo Period Mapping")

        # --------------------------------------------------------------------
        # 9.0B Apply Asset Filter Mode (AssetCo)
        # --------------------------------------------------------------------
        # Determine which AssetCo assets to process based on filter mode.
        # For each active asset, convert extracted CFO/CFI/CFF payloads from
        # output_json into DataFrames. Each financial section in monthly_dfs /
        # annual_dfs is structured as [metadata, {data, columns, index}] where
        # index [1] is the dict convertible via fn_json_dict_to_dataframe.
        # Optional sections (e.g. Hospitality P&L) are handled gracefully.
        # --------------------------------------------------------------------

        _asset_filter_mode_key = _ASSET_FILTER_MODE.strip().lower()
        _is_synthetic_mode = _asset_filter_mode_key == "synthetic"
        _is_single_asset_mode = (
            _asset_filter_mode_key != "consolidated"
            and _ASSET_FILTER_MODE.strip() != ""
        )

        # Build set of active AssetCo asset indices (all by default)
        _active_assetco_indices: set = set(range(_assetco_number_of_assets))

        # Build per-index lookup of asset_unique_id from payload for filtration.
        _assetco_unique_id_lookup: Dict[int, str] = {}
        _assetco_consolidated_list = payload.get("assetco_consolidated", []) if isinstance(payload, dict) else []
        for i in range(_assetco_number_of_assets):
            if i < len(_assetco_consolidated_list):
                _aid = str(
                    _assetco_consolidated_list[i]
                    .get("output_json", {})
                    .get("assetco_inputs", {})
                    .get("asset_unique_id", "")
                ).strip()
                _assetco_unique_id_lookup[i] = _aid

        if _is_single_asset_mode:
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
                        "were supplied for AssetCo. Returning all-zero output."
                    )
                    _active_assetco_indices = set()
                else:
                    _matched_indices: set = set()
                    for idx in range(_assetco_number_of_assets):
                        _uid = _assetco_unique_id_lookup.get(idx, "")
                        if _uid in _synthetic_asset_ids_set:
                            _matched_indices.add(idx)

                    if not _matched_indices:
                        _available = list(_assetco_unique_id_lookup.values())
                        print(
                            "WARNING: Synthetic asset filter IDs were not found in "
                            f"AssetCo assets. IDs: {sorted(_synthetic_asset_ids_set)}, "
                            f"available: {_available}. Returning all-zero output."
                        )
                        _active_assetco_indices = set()
                    else:
                        _active_assetco_indices = _matched_indices
                        print(
                            "Asset filter mode: processing Synthetic AssetCo set "
                            f"({len(_matched_indices)} asset(s) matched, indices: {sorted(_matched_indices)})."
                        )
            else:
                _selected_asset_id = _ASSET_FILTER_MODE.strip()
                _matched_indices: set = set()
                for idx in range(_assetco_number_of_assets):
                    _uid = _assetco_unique_id_lookup.get(idx, "")
                    if _uid == _selected_asset_id:
                        _matched_indices.add(idx)

                if not _matched_indices:
                    _available = list(_assetco_unique_id_lookup.values())
                    print(
                        f"WARNING: Asset filter '{_selected_asset_id}' not found in "
                        f"AssetCo assets. Available: {_available}. "
                        f"Returning all-zero output."
                    )
                    _active_assetco_indices = set()
                else:
                    _active_assetco_indices = _matched_indices
                    print(
                        f"Asset filter mode: processing only AssetCo asset '{_selected_asset_id}' "
                        f"({len(_matched_indices)} asset(s) matched, indices: {sorted(_matched_indices)})."
                    )

        # Remove JV assets from active indices: AssetCo is in JV when
        # jvjda_inclusion=Yes AND assetco_jv_inclusion=Yes.
        # These assets belong to the JV output, not consolidation.
        _jv_asset_indices: set = set()
        for _jv_idx in list(_active_assetco_indices):
            _jvjda = str(_jvjda_inclusion.get(_jv_idx, "") or "").strip().lower()
            _ac_jv = str(_assetco_jv_inclusion.get(_jv_idx, "") or "").strip().lower()
            if _jvjda == "yes" and _ac_jv == "yes":
                _jv_asset_indices.add(_jv_idx)
        if _jv_asset_indices:
            _active_assetco_indices -= _jv_asset_indices
            print(
                f"AssetCo JV filter: removed {len(_jv_asset_indices)} JV asset(s) "
                f"from consolidation processing (indices: {sorted(_jv_asset_indices)})."
            )

        # Local helper: convert section data to DataFrame.
        # Handles both [metadata, {data, columns, index}] list format
        # and bare {data, columns, index} dict format.
        def _section_to_df(section_data):
            if section_data is None:
                return None
            if isinstance(section_data, list) and len(section_data) > 1:
                payload = section_data[1]
            elif isinstance(section_data, dict):
                payload = section_data
            else:
                return None
            if isinstance(payload, dict):
                return fn_json_dict_to_dataframe(payload)
            return None

        # Prepared DataFrame containers for active AssetCo assets
        _assetco_cfo_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_cfi_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_cff_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_hospitality_pnl_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_annual_cfo_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_annual_cfi_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_annual_cff_dfs: Dict[int, pd.DataFrame] = {}
        _assetco_col_to_period_per_asset: Dict[int, Dict[Any, str]] = {}

        _monthly_cf_sections = {
            "Cashflow from Operations": _assetco_cfo_dfs,
            "Cashflow from Investments": _assetco_cfi_dfs,
            "Cashflow from Financing": _assetco_cff_dfs,
        }
        _annual_cf_sections = {
            "Cashflow from Operations": _assetco_annual_cfo_dfs,
            "Cashflow from Investments": _assetco_annual_cfi_dfs,
            "Cashflow from Financing": _assetco_annual_cff_dfs,
        }

        for idx in sorted(_active_assetco_indices):
          try:
            asset_output = _assetco_output_json.get(idx, {})
            if not isinstance(asset_output, dict):
                print(f"AssetCo asset {idx}: output_json is {type(asset_output).__name__}, not dict. Skipping.")
                continue

            asset_monthly = asset_output.get("monthly_dfs", {})
            asset_annual = asset_output.get("annual_dfs", {})
            if not isinstance(asset_monthly, dict):
                print(f"AssetCo asset {idx}: monthly_dfs is {type(asset_monthly).__name__}, defaulting to empty.")
                asset_monthly = {}
            if not isinstance(asset_annual, dict):
                print(f"AssetCo asset {idx}: annual_dfs is {type(asset_annual).__name__}, defaulting to empty.")
                asset_annual = {}

            # --- Monthly cashflow sections ---
            for section_key, target_dfs in _monthly_cf_sections.items():
                raw_section = asset_monthly.get(section_key)
                
                if isinstance(raw_section, list) and len(raw_section) > 1:
                    inner = raw_section[1]
                df = _section_to_df(raw_section)
                if df is not None and not df.empty:
                    target_dfs[idx] = df
                else:
                    print(f"    -> DF is None or empty for '{section_key}'.")

            # --- Annual cashflow sections ---
            for section_key, target_dfs in _annual_cf_sections.items():
                df = _section_to_df(asset_annual.get(section_key))
                if df is not None and not df.empty:
                    target_dfs[idx] = df

            # --- Optional: Hospitality P&L (monthly) ---
            hosp_df = _section_to_df(asset_monthly.get("Hospitality P&L"))
            if hosp_df is not None and not hosp_df.empty:
                _assetco_hospitality_pnl_dfs[idx] = hosp_df

            # --- Per-asset timeline and column-to-period mapping ---
            # Try both "Monthly Timeline" and "Timeline" keys
            tl_raw = asset_monthly.get("Monthly Timeline") or asset_monthly.get("Timeline")
            tl_df = _section_to_df(tl_raw)
            if tl_df is not None and "Period End" in tl_df.index:
                pe_series = pd.to_datetime(tl_df.loc["Period End"]).dt.normalize()
                _period_end_list = [pe.strftime('%Y-%m-%d') for pe in pe_series]
                _assetco_col_to_period_per_asset[idx] = {
                    pe_str: pe_str for pe_str in _period_end_list
                }
            else:
                print(f"  asset {idx}: No per-asset Timeline found (tl_df={'None' if tl_df is None else 'empty'}).")
                _period_end_list = None

            # Fallback to shared AssetCo col-to-period mapping built in 9.0
            if idx not in _assetco_col_to_period_per_asset:
                print(f"  asset {idx}: Using shared _assetco_col_to_period ({len(_assetco_col_to_period)} entries).")
                _assetco_col_to_period_per_asset[idx] = _assetco_col_to_period
                _period_end_list = list(_assetco_col_to_period.values())

            # --- Positionally assign period-end dates as columns ---
            # Source DFs have non-unique column labels (e.g. year numbers
            # like 2019, 2019, ...). Replace them positionally with the
            # unique period-end date strings from the timeline.
            if _period_end_list is not None:
                for _dfs_dict in [_assetco_cfo_dfs, _assetco_cfi_dfs, _assetco_cff_dfs, _assetco_hospitality_pnl_dfs]:
                    if idx in _dfs_dict:
                        _df = _dfs_dict[idx]
                        if _df.shape[1] == len(_period_end_list):
                            _df.columns = _period_end_list
                            _dfs_dict[idx] = _df
                        else:
                            print(
                                f"  WARNING asset {idx}: DF cols={_df.shape[1]} != "
                                f"timeline periods={len(_period_end_list)}, skipping column rename."
                            )

          except Exception as _e90b:
            print(f"ERROR in 9.0B for asset {idx}: {_e90b}")
            traceback.print_exc()

        fn_record_timing(_timing_ctx, "PHASE 9.0B: AssetCo Asset Filter and DF Extraction")

        # --------------------------------------------------------------------
        # 9.1 Process AssetCo CFI Entries
        # --------------------------------------------------------------------
        # For each active AssetCo asset, extract line items from its Cashflow
        # from Investments DataFrame (rows = line items, columns = periods).
        #
        # 9.1A  Acquisition & Transaction Costs:
        #         Dr Investment Property / Cr Cash and Cash Equivalents
        #         Source rows ? Consolidated CF line item:
        #           Acquisition Price       ? Asset Acquisition Cost
        #           Transfer Tax / Stamp Duty ? Transfer Tax / Stamp Duty
        #           Legal Fees              ? Legal Cost
        #           Brokerage               ? Brokerage
        #           Due Diligence Costs     ? Due Diligence Cost
        #
        # 9.1B  Maintenance Capex:
        #         Dr Investment Property / Cr Cash and Cash Equivalents
        #           Maintenance Capex 1-4   ? Maintenance Capex 1-4
        # --------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Build DevCo recognition basis & revenue for interparty progressive
        # capitalization (mirrors DevCo's updated recognition basis:
        # CWIP + serviced-land debit timing).
        # ------------------------------------------------------------------
        _devco_timeline_df_acq = fn_json_dict_to_dataframe(_devco_timeline) if _devco_timeline else None
        _devco_col_to_period_acq: Dict[Any, str] = {}
        if _devco_timeline_df_acq is not None and "Period End" in _devco_timeline_df_acq.index:
            for _dtci, _dtpe in pd.to_datetime(_devco_timeline_df_acq.loc["Period End"]).dt.normalize().items():
                _devco_col_to_period_acq[_dtci] = _dtpe.strftime('%Y-%m-%d')
        _devco_period_cols_acq = list(_devco_col_to_period_acq.keys())

        def _build_serviced_land_acquisition_debit_basis(
            land_acquisition_df: pd.DataFrame,
            col_to_period: Dict[Any, str],
            asset_unique_identifier: Optional[pd.Series],
            acquisition_counterparty: Optional[pd.Series] = None,
            s_curve_df: Optional[pd.DataFrame] = None,
            revenue_df: Optional[pd.DataFrame] = None,
        ) -> pd.DataFrame:
            """
            Build per-asset/per-period Serviced Land Assets debit basis using
            the same acquisition-timing logic as DevCo land acquisition posting.
            """
            if not isinstance(land_acquisition_df, pd.DataFrame) or land_acquisition_df.empty:
                return pd.DataFrame()

            if not col_to_period:
                return pd.DataFrame(index=land_acquisition_df.index)

            period_cols = list(col_to_period.keys())
            if not period_cols:
                return pd.DataFrame(index=land_acquisition_df.index)

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

                _basis_matrix[asset_row_idx] = np.where(acquisition_values > 0.0, acquisition_values, 0.0)

            return pd.DataFrame(_basis_matrix, index=_output_index, columns=period_cols)

        _devco_revenue_for_acq = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Sales Revenue",
            source_name="DevCo Support Workings",
        )
        _devco_sc_raw_for_acq = fn_safe_extract_dataframe(
            source_dict=_devco_support_workings,
            key="Phased Vertical Amount",
            source_name="DevCo Support Workings",
        )
        _devco_cwip_sc_for_acq = _devco_sc_raw_for_acq.abs() if not _devco_sc_raw_for_acq.empty else pd.DataFrame()

        # Accumulate DevCo CWIP direct cash items to build total S-curve.
        _devco_cwip_items_for_acq = [
            "Design Cost", "Permitting Cost", "Supervision Cost",
            "Project Management Cost", "Contingency Cost Payment",
            "Public Amenity Cost", "CEC Cost", "Canal Cost",
            "Capitalized Salaries", "Capitalized IT Services",
            "Capitalized Office Rent & Utilities",
            "Capitalized Professional Services",
            "Capitalized Marketing (COH)", "Capitalized Sales Cost (COH)",
            "Capitalized Additional Expenses",
        ]
        _cwip_sum_acq: pd.DataFrame = pd.DataFrame()
        for _citem in _devco_cwip_items_for_acq:
            _cdf = fn_safe_extract_dataframe(_devco_cfi, _citem, "DevCo CFI")
            if not _cdf.empty:
                _cdf_abs = _cdf.abs()
                _cwip_sum_acq = (
                    _cwip_sum_acq.add(_cdf_abs, fill_value=0.0)
                    if not _cwip_sum_acq.empty
                    else _cdf_abs.copy()
                )
        if not _cwip_sum_acq.empty and not _devco_cwip_sc_for_acq.empty:
            _cwip_aligned_acq = _cwip_sum_acq.reindex(
                columns=_devco_cwip_sc_for_acq.columns, fill_value=0.0
            )
            _devco_cwip_sc_for_acq = pd.DataFrame(
                _devco_cwip_sc_for_acq.values + _cwip_aligned_acq.values,
                index=_devco_cwip_sc_for_acq.index,
                columns=_devco_cwip_sc_for_acq.columns,
            )

        # Build DevCo serviced-land debit basis using DevCo acquisition timing
        # (including interparty progressive LandCo timing).
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
        _devco_land_acquisition = pd.DataFrame()
        if not _devco_land_acquisition_flag.empty and not _devco_land_acquisition_cost.empty:
            _devco_land_acquisition = _devco_land_acquisition_flag.mul(
                _devco_land_acquisition_cost.sum(axis=1).values,
                axis=0,
            )

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
        _landco_cwip_sum_for_acq: pd.DataFrame = pd.DataFrame()
        for _lc_item in _landco_cwip_items_for_acq:
            _lc_df = fn_safe_extract_dataframe(_landco_cfi, _lc_item, "LandCo CFI")
            if not _lc_df.empty:
                _lc_abs = _lc_df.abs()
                _landco_cwip_sum_for_acq = (
                    _landco_cwip_sum_for_acq.add(_lc_abs, fill_value=0.0)
                    if not _landco_cwip_sum_for_acq.empty
                    else _lc_abs.copy()
                )
        if not _landco_cwip_sum_for_acq.empty and not _landco_cwip_sc_for_acq.empty:
            _landco_cwip_aligned_acq = _landco_cwip_sum_for_acq.reindex(
                columns=_landco_cwip_sc_for_acq.columns,
                fill_value=0.0,
            )
            _landco_cwip_sc_for_acq = pd.DataFrame(
                _landco_cwip_sc_for_acq.values + _landco_cwip_aligned_acq.values,
                index=_landco_cwip_sc_for_acq.index,
                columns=_landco_cwip_sc_for_acq.columns,
            )

        _devco_acquisition_counterparty = (
            _interparty_mapping["DevCo_Acquisition_Counterparty"]
            if isinstance(_interparty_mapping, pd.DataFrame)
            and not _interparty_mapping.empty
            and "DevCo_Acquisition_Counterparty" in _interparty_mapping.columns
            else pd.Series()
        )

        _devco_serviced_land_debit_basis_for_acq = _build_serviced_land_acquisition_debit_basis(
            land_acquisition_df=_devco_land_acquisition,
            col_to_period=_devco_col_to_period_acq,
            asset_unique_identifier=_asset_unique_identifier,
            acquisition_counterparty=_devco_acquisition_counterparty,
            s_curve_df=_landco_cwip_sc_for_acq,
            revenue_df=_landco_revenue_for_acq,
        )

        _devco_total_recognition_basis_for_acq = _devco_cwip_sc_for_acq.copy()
        if _devco_total_recognition_basis_for_acq.empty and not _devco_serviced_land_debit_basis_for_acq.empty:
            _devco_total_recognition_basis_for_acq = _devco_serviced_land_debit_basis_for_acq.abs().copy()
        elif not _devco_serviced_land_debit_basis_for_acq.empty:
            _sla_aligned_acq = _devco_serviced_land_debit_basis_for_acq.abs().reindex(
                index=_devco_total_recognition_basis_for_acq.index,
                columns=_devco_total_recognition_basis_for_acq.columns,
                fill_value=0.0,
            ).fillna(0.0)
            _devco_total_recognition_basis_for_acq = pd.DataFrame(
                _devco_total_recognition_basis_for_acq.values + _sla_aligned_acq.values,
                index=_devco_total_recognition_basis_for_acq.index,
                columns=_devco_total_recognition_basis_for_acq.columns,
            )

        _have_devco_scurve = (
            not _devco_total_recognition_basis_for_acq.empty
            and not _devco_revenue_for_acq.empty
            and bool(_devco_period_cols_acq)
        )

        def _normalize_uid_key(uid_value: Any) -> Optional[str]:
            if uid_value is None:
                return None
            if isinstance(uid_value, float) and pd.isna(uid_value):
                return None
            uid_text = str(uid_value).strip()
            if uid_text == "" or uid_text.lower() in {"none", "nan", "nat"}:
                return None
            return uid_text

        # Map ProjectDetails UID -> project row index so AssetCo UID can resolve
        # to the correct DevCo row even when payload ordering differs.
        _project_uid_to_idx: Dict[str, Any] = {}
        if isinstance(_asset_unique_identifier, pd.Series) and not _asset_unique_identifier.empty:
            for _project_idx, _project_uid_raw in _asset_unique_identifier.items():
                _project_uid = _normalize_uid_key(_project_uid_raw)
                if _project_uid is None:
                    continue
                _project_uid_to_idx.setdefault(_project_uid, _project_idx)

        def _resolve_devco_asset_row_key(
            source_df: pd.DataFrame,
            assetco_idx: int,
            asset_uid: Any,
        ) -> Optional[Any]:
            if not isinstance(source_df, pd.DataFrame) or source_df.empty:
                return None

            _uid = _normalize_uid_key(asset_uid)
            _project_idx = _project_uid_to_idx.get(_uid) if _uid is not None else None

            _candidates: List[Any] = []
            if _project_idx is not None:
                _candidates.append(_project_idx)
                _candidates.append(str(_project_idx))
                try:
                    _candidates.append(int(_project_idx))
                except (TypeError, ValueError):
                    pass

            _candidates.extend([assetco_idx, str(assetco_idx)])
            if _uid is not None:
                _candidates.append(_uid)

            _seen: set = set()
            for _candidate in _candidates:
                _token = (type(_candidate).__name__, str(_candidate))
                if _token in _seen:
                    continue
                _seen.add(_token)
                if _candidate in source_df.index:
                    return _candidate

            return None

        # Pre-compute progressive capitalization for each interparty asset.
        # Maps: {asset_idx: {period_date_str: amount}}
        _progressive_acq: Dict[int, Dict[str, float]] = {}
        if _have_devco_scurve:
            for _pa_idx in sorted(_active_assetco_indices):
                _pa_uid = _asset_unique_id.get(_pa_idx)
                _pa_is_devco = False
                if (
                    _pa_uid is not None
                    and isinstance(_interparty_mapping, pd.DataFrame)
                    and not _interparty_mapping.empty
                    and _pa_uid in _interparty_mapping.index
                    and "AssetCo_Acquisition_Counterparty" in _interparty_mapping.columns
                ):
                    _pa_is_devco = (
                        str(_interparty_mapping.at[_pa_uid, "AssetCo_Acquisition_Counterparty"]).strip() == "DevCo"
                    )
                if not _pa_is_devco:
                    continue

                # Total acquisition cost from CFI
                _pa_cfi = _assetco_cfi_dfs.get(_pa_idx)
                if _pa_cfi is None or _pa_cfi.empty or "Acquisition Price" not in _pa_cfi.index:
                    continue
                _pa_acq_row = _pa_cfi.loc["Acquisition Price"]
                if isinstance(_pa_acq_row, pd.DataFrame):
                    _pa_acq_row = _pa_acq_row.iloc[0]
                _total_acq = float(np.abs(pd.to_numeric(_pa_acq_row, errors="coerce").fillna(0.0)).sum())
                if _total_acq <= 0.0:
                    continue

                # Resolve DevCo row by UID->ProjectDetails index first, then fallback.
                _pa_idx_key = _resolve_devco_asset_row_key(
                    _devco_total_recognition_basis_for_acq,
                    assetco_idx=_pa_idx,
                    asset_uid=_pa_uid,
                )
                if _pa_idx_key is None:
                    continue

                _sc_row = pd.to_numeric(
                    _devco_total_recognition_basis_for_acq.loc[_pa_idx_key].reindex(_devco_period_cols_acq),
                    errors="coerce",
                ).fillna(0.0).to_numpy(dtype="float64")
                _rev_row_key = _resolve_devco_asset_row_key(
                    _devco_revenue_for_acq,
                    assetco_idx=_pa_idx,
                    asset_uid=_pa_uid,
                )
                _rev_row = (
                    pd.to_numeric(
                        _devco_revenue_for_acq.loc[_rev_row_key].reindex(_devco_period_cols_acq),
                        errors="coerce",
                    ).fillna(0.0).to_numpy(dtype="float64")
                    if _rev_row_key is not None
                    else np.zeros(len(_devco_period_cols_acq), dtype="float64")
                )

                _sc_vals = np.abs(_sc_row)
                _rev_vals = np.abs(_rev_row)
                _sc_total = float(_sc_vals.sum())
                _total_rev = float(_rev_vals.sum())
                if _sc_total <= 0.0 or _total_rev <= 0.0:
                    continue

                _sc_pct = np.cumsum(_sc_vals) / _sc_total
                _cum_absorption = np.cumsum(_rev_vals)

                _prog_map: Dict[str, float] = {}
                _prev_sc = 0.0
                _cum_recog = 0.0
                for _pi in range(len(_devco_period_cols_acq)):
                    _sp = float(_sc_pct[_pi])
                    if pd.isna(_sp):
                        _sp = _prev_sc
                    _sp = max(_prev_sc, max(0.0, min(1.0, _sp)))
                    _cum_tgt = float(_cum_absorption[_pi]) * _sp
                    _pr = max(0.0, _cum_tgt - _cum_recog)
                    if _pr > 0.0:
                        _amt = _total_acq * (_pr / _total_rev)
                        _date_str = _devco_col_to_period_acq.get(_devco_period_cols_acq[_pi])
                        if _date_str and _amt > 0.01:
                            _prog_map[_date_str] = _prog_map.get(_date_str, 0.0) + _amt
                    _cum_recog += _pr
                    _prev_sc = _sp

                if _prog_map:
                    _progressive_acq[_pa_idx] = _prog_map

        # Mapping: (CFI row index label, consolidated cashflow line item, ref code)
        _assetco_cfi_acquisition_items = [
            ("Acquisition Price",           "Asset Acquisition Cost",    "ACQPRICE"),
            ("Transfer Tax / Stamp Duty",   "Transfer Tax / Stamp Duty", "TXSTAMP"),
            ("Legal Fees",                  "Legal Cost",                "LEGAL"),
            ("Brokerage",                   "Brokerage",                 "BROKER"),
            ("Due Diligence Costs",         "Due Diligence Cost",        "DUEDIL"),
        ]

        _all_assetco_cfi_items = _assetco_cfi_acquisition_items

        # ====================================================================
        # Item / config definitions (consolidated here for the combined pass)
        # ====================================================================

        # CFO line-item mappings (Revenue and Expense)
        _assetco_cfo_revenue_items = [
            ("Base Rent",        "Base Rent",        "Cash and Cash Equivalents", "Lease Revenue - Base Rent",     "BASERENT"),
            ("Turnover Rent",    "Turnover Rent",    "Cash and Cash Equivalents", "Lease Revenue - Turnover Rent", "TORENT"),
            ("Service Charge",   "Service Charge",   "Cash and Cash Equivalents", "Lease Revenue - Service Charge","SVCCHG"),
            ("Parking Revenue",  "Parking Revenue",  "Cash and Cash Equivalents", "Parking Revenue",               "PARKREV"),
            ("Other Income 1",   "Other Income 1",   "Cash and Cash Equivalents", "Other Operating Income",        "OTHINC1"),
            ("Other Income 2",   "Other Income 2",   "Cash and Cash Equivalents", "Other Operating Income",        "OTHINC2"),
            ("Other Income 3",   "Other Income 3",   "Cash and Cash Equivalents", "Other Operating Income",        "OTHINC3"),
        ]
        _assetco_cfo_expense_items = [
            ("Leasing Commissions",      "Leasing Commissions",      "Leasing Commissions Expense",  "Cash and Cash Equivalents", "LEASCOMM"),
            ("Pre Operating Expenses",   "Pre Operating Expenses",   "Pre Operating Expenses",       "Cash and Cash Equivalents", "PREOPEX"),
            ("Asset Management Fees",    "Other Operating Expenses", "Asset Management Expense",     "Cash and Cash Equivalents", "AMFEES"),
            ("Utilities",                "Utilities",                "Utilities Expense",            "Cash and Cash Equivalents", "UTIL"),
            ("Facility Management Fees", "Facility Management Fees", "Facility Management Expense",  "Cash and Cash Equivalents", "FACMGMT"),
            ("Administration Cost",      "Administration Cost",      "Administration Expense",       "Cash and Cash Equivalents", "ADMIN"),
            ("Marketing Cost",           "Marketing Cost",           "Marketing Overhead Expense",   "Cash and Cash Equivalents", "MKTCOST"),
            ("Insurance",                "Insurance",                "Insurance Expense",            "Cash and Cash Equivalents", "INSUR"),
            ("Other Operating Expenses", "Other Operating Expenses", "Other Operating Expenses",     "Cash and Cash Equivalents", "OTHOPEX"),
            ("Bad Debt",                 "Bad Debt",                 "Bad Debt Expense",             "Cash and Cash Equivalents", "BADDEBT"),
            ("Void Period Opex",         "Void Period Opex",         "Void Period Expense",          "Cash and Cash Equivalents", "VOIDOPEX"),
            ("Parking Expenses",         "Parking Expenses",         "Parking Expense",              "Cash and Cash Equivalents", "PARKEXP"),
            ("Other Expense 1",          "Other Expense 1",          "Other Operating Expenses",     "Cash and Cash Equivalents", "OTHEXP1"),
            ("Other Expense 2",          "Other Expense 2",          "Other Operating Expenses",     "Cash and Cash Equivalents", "OTHEXP2"),
            ("Other Expense 3",          "Other Expense 3",          "Other Operating Expenses",     "Cash and Cash Equivalents", "OTHEXP3"),
        ]
        _all_assetco_cfo_items = _assetco_cfo_revenue_items + _assetco_cfo_expense_items

        # Maintenance capex rows
        _assetco_maintenance_capex_items = [
            ("Maintenance Capex 1", "Maintenance Capex 1", "MAINT1"),
            ("Maintenance Capex 2", "Maintenance Capex 2", "MAINT2"),
            ("Maintenance Capex 3", "Maintenance Capex 3", "MAINT3"),
            ("Maintenance Capex 4", "Maintenance Capex 4", "MAINT4"),
        ]

        # Acquisition cost rows (used in depreciation base calculation)
        _acquisition_cost_row_labels = [
            "Transfer Tax / Stamp Duty",
            "Legal Fees",
            "Brokerage",
            "Due Diligence Costs",
        ]

        # Hospitality revenue mapping
        _hospitality_revenue_mapping = {
            "Hospitality - Room Revenue": {
                "pnl_rows": ["Room Revenue"],
                "cf_line_item": "Hospitality - Room Revenue",
                "ref_code": "HOSPROOM",
            },
            "Hospitality - F&B Revenue": {
                "pnl_rows": ["In Room-Dining", "Venue - F&B", "Other F&B Revenue"],
                "cf_line_item": "Hospitality - F&B Revenue",
                "ref_code": "HOSPFB",
            },
            "Hospitality - OOD Revenue": {
                "pnl_rows": ["Golf Revenue", "Spa & Wellness - Revenue", "Banquet & Conference Revenue", "Guest Laundry Revenue"],
                "cf_line_item": "Hospitality - OOD Revenue",
                "ref_code": "HOSPOOD",
            },
            "Hospitality - Other Operating Income": {
                "pnl_rows": ["Minor Operating Department", "Cancellation Charges", "Miscellaneous Income", "Parking Revenue"],
                "cf_line_item": "Hospitality - Other Operating Income",
                "ref_code": "HOSPOTHER",
            },
        }

        # Hospitality expense mapping
        _hospitality_expense_mapping = {
            "Hospitality Departmental Expenses - Room": {
                "pnl_rows": ["Room Expense", "Room Expenses"],
                "cf_line_item": "Hospitality Departmental Expenses - Room",
                "ref_code": "HOSPRMEXP",
            },
            "Hospitality Departmental Expenses - F&B": {
                "pnl_rows": ["F&B Expense", "Food and Beverage Expenses"],
                "cf_line_item": "Hospitality Departmental Expenses - F&B",
                "ref_code": "HOSPFBEXP",
            },
            "Hospitality Departmental Expenses - OOD": {
                "pnl_rows": [
                    "Golf Expense", "Golf",
                    "Spa & Wellness Expense", "Spa & Wellness",
                    "Banquet & Conference Expense", "Banquet & Conference",
                    "Laundry Expense", "Laundry",
                ],
                "cf_line_item": "Hospitality Departmental Expenses - OOD",
                "ref_code": "HOSPOODEXP",
            },
            "Hospitality Departmental Expenses - Other": {
                "pnl_rows": ["Other Departmental Expenses", "Parking Expense"],
                "cf_line_item": "Hospitality Departmental Expenses - Other",
                "ref_code": "HOSPOTHEXP",
            },
            "Hospitality Undistributed Expenses - Admin": {
                "pnl_rows": ["Admin & General"],
                "cf_line_item": "Hospitality Undistributed Expenses - Admin",
                "ref_code": "HOSPADMIN",
            },
            "Hospitality Undistributed Expenses - Sales & Marketing": {
                "pnl_rows": [
                    "Franchise & Affiliation Advertising",
                    "Franchise and Affiliation Advertising",
                    "Loyalty Programs",
                    "Other Expense (S&M)",
                ],
                "cf_line_item": "Hospitality Undistributed Expenses - Sales & Marketing",
                "ref_code": "HOSPSM",
            },
            "Hospitality Undistributed Expenses - IT": {
                "pnl_rows": ["Info & Telecom Systems", "Info & Telecom System"],
                "cf_line_item": "Hospitality Undistributed Expenses - IT",
                "ref_code": "HOSPIT",
            },
            "Hospitality Undistributed Expenses - Utilities": {
                "pnl_rows": [
                    "Electricity", "Gas", "Water & Sewer",
                    "Other Expense (Utility)", "Other Expense (H,L,P)",
                ],
                "cf_line_item": "Hospitality Undistributed Expenses - Utilities",
                "ref_code": "HOSPUTIL",
            },
        }

        # Hospitality non-operating row labels
        _hospitality_nonop_expense_rows = ["Insurance", "Other Expense 1", "Other Expense 2", "Other Expense 3"]
        _hospitality_nonop_income_rows  = ["Other Income 1", "Other Income 2", "Other Income 3"]

        # CFF facility configs
        _assetco_cff_facility_configs = [
            {
                "name": "Term Loan",
                "header_label": "Asset Level Term Loan",
                "items": [
                    (1, "Term Loan - Debt Drawdown",     "Cash and Cash Equivalents",    "Debt - Term Loan",             None,                           "DD"),
                    (2, "Term Loan - Debt Repayment",    "Debt - Term Loan",             "Cash and Cash Equivalents",    None,                           "REPAY"),
                    (3, "Term Loan - Interest Payments", "Interest Expense - Term Loan", "Cash and Cash Equivalents",    "Interest Expense - Term Loan", "INT"),
                    (4, "Term Loan - Debt Fees",         "Debt Fees Expense",            "Cash and Cash Equivalents",    "Debt Fees Expense",            "ARRFEE"),
                ],
                "ref_prefix": "AC-TL",
            },
            {
                "name": "Asset Level Revolver",
                "header_label": "Asset Level Refinancing Facility",
                "items": [
                    (1, "Revolver - Debt Drawdown",      "Cash and Cash Equivalents",    "Debt - Revolver",              None,                            "DD"),
                    (2, "Revolver - Debt Repayment",     "Debt - Revolver",              "Cash and Cash Equivalents",    None,                            "REPAY"),
                    (3, "Revolver - Interest Payments",  "Interest Expense - Revolver",  "Cash and Cash Equivalents",    "Interest Expense - Revolver",  "INT"),
                    (4, "Revolver - Debt Fees",          "Debt Fees Expense",            "Cash and Cash Equivalents",    "Debt Fees Expense",            "ARRFEE"),
                ],
                "ref_prefix": "AC-REV",
            },
        ]

        # ====================================================================
        # Combined per-asset entry generation (Phases 9.1 through 9.5C)
        # -------
        # Each asset's processing is fully independent.  Running all phases
        # for one asset at once avoids repeated DataFrame numeric-conversion
        # overhead and enables parallel execution across assets.
        # ====================================================================

        def _generate_entries_for_asset_all_phases(idx: int) -> Dict[str, List[Dict[str, Any]]]:
            """
            Generate all batch journal entries for one AssetCo asset across
            phases 9.1 – 9.5C.  Returns a dict keyed by phase name so the
            caller can flush each phase's entries in the correct order.

            All numpy / pandas work that releases the GIL runs concurrently
            when called from a ThreadPoolExecutor thread.
            """
            _entries: Dict[str, List[Dict[str, Any]]] = {
                "9.1": [], "9.1E": [], "9.1F": [],
                "9.1G": [], "9.1H": [], "9.1I": [],
                "9.1J": [], "9.5":  [], "9.5B": [], "9.5C": [],
            }
            try:
                # ── Common per-asset setup (computed once, reused all phases) ─────────
                _asset_id_label = str(
                    _assetco_asset_id.get(idx, _assetco_asset_identifier.get(idx, f"idx:{idx}"))
                ).strip()
                _col_map     = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
                _period_cols = list(_col_map.keys())
                _arr_period_cols = np.array(_period_cols)

                cfi_df  = _assetco_cfi_dfs.get(idx)
                cfo_df  = _assetco_cfo_dfs.get(idx)
                cff_df  = _assetco_cff_dfs.get(idx)
                hosp_df = _assetco_hospitality_pnl_dfs.get(idx)

                # Pre-convert to numeric once – reused across all phases to avoid
                # repeated apply(pd.to_numeric) calls per asset per phase.
                _cfi_numeric = (
                    cfi_df.reindex(columns=_period_cols)
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                ) if (cfi_df is not None and not cfi_df.empty) else None

                _cfo_numeric = (
                    cfo_df.reindex(columns=_period_cols)
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                ) if (cfo_df is not None and not cfo_df.empty) else None

                # ── Interparty status (Phase 9.1) ────────────────────────────────────
                _is_devco_acquisition = False
                _asset_uid = _asset_unique_id.get(idx)
                if (
                    _asset_uid is not None
                    and isinstance(_interparty_mapping, pd.DataFrame)
                    and not _interparty_mapping.empty
                    and _asset_uid in _interparty_mapping.index
                    and "AssetCo_Acquisition_Counterparty" in _interparty_mapping.columns
                ):
                    _is_devco_acquisition = (
                        str(_interparty_mapping.at[_asset_uid, "AssetCo_Acquisition_Counterparty"]).strip() == "DevCo"
                    )
                _skip_progressive = _is_devco_acquisition and not _ENABLE_INTERPARTY_ENTRIES

                # ================================================================
                # PHASE 9.1 – CFI Acquisition Entries
                # ================================================================
                if _cfi_numeric is not None:
                    _e91 = _entries["9.1"]
                    for _cfi_row_label, _cf_line_item, _ref_code in _all_assetco_cfi_items:
                        # ── Interparty progressive capitalisation ───────────────────
# ── Interparty progressive capitalisation ───────────────────
                        if _ref_code == "ACQPRICE" and _is_devco_acquisition and not _skip_progressive and idx in _progressive_acq:
                            _prog = _progressive_acq[idx]
                            if _cfi_row_label not in _cfi_numeric.index:
                                continue
                            _acq_row_data = _cfi_numeric.loc[_cfi_row_label]
                            if isinstance(_acq_row_data, pd.DataFrame):
                                _acq_row_data = _acq_row_data.iloc[0]
                            _cash_amts = np.abs(_acq_row_data.to_numpy(dtype="float64"))
                            
                            # OPTIMIZATION 1: Vectorized cash_by_date aggregation
                            # Instead of loop + dict.get(), use NumPy masking + grouping
                            _nz_mask = _cash_amts > 0.0
                            if not np.any(_nz_mask):
                                continue
                            
                            _nz_period_cols = _arr_period_cols[_nz_mask]
                            _nz_cash_amts = _cash_amts[_nz_mask]
                            
                            # Map columns to periods once (vectorized lookup)
                            _nz_periods = np.array([_col_map.get(pc) for pc in _nz_period_cols], dtype=object)
                            _valid_mask = _nz_periods != None  # Filter out unmapped periods
                            _nz_periods = _nz_periods[_valid_mask]
                            _nz_cash_amts = _nz_cash_amts[_valid_mask]
                            
                            # Use pandas for fast aggregation by period
                            _cash_by_date_series = pd.Series(_nz_cash_amts, index=_nz_periods)
                            _cash_by_date = _cash_by_date_series.groupby(level=0).sum().to_dict()
                            
                            _all_dates = sorted(set(list(_prog.keys()) + list(_cash_by_date.keys())))
                            
                            # OPTIMIZATION 2: Pre-allocate entry list for this block
                            _prog_entries = []
                            _adv_bal = 0.0
                            _pay_bal = 0.0
                            
                            for _dt in _all_dates:
                                _cap  = _prog.get(_dt, 0.0)
                                _cash = _cash_by_date.get(_dt, 0.0)
                                
                                if _cap > 0.01:
                                    _adv_apply = min(_adv_bal, _cap)
                                    _pay_add   = _cap - _adv_apply
                                    
                                    if _adv_apply > 0.0:
                                        _prog_entries.append({
                                            "debit_account": "Investment Property",
                                            "credit_account": "Advances for Land",
                                            "amount": _adv_apply,
                                            "period": _dt,
                                            "income_statement_line_item": None,
                                            "cashflow_line_item": None,
                                            "description": f"AssetCo Acquisition (advance offset) - Asset {idx}",
                                            "reference": f"AC-CFI-{_ref_code}-ADV-{idx}-{_dt}",
                                        })
                                        _adv_bal -= _adv_apply
                                    
                                    if _pay_add > 0.0:
                                        _prog_entries.append({
                                            "debit_account": "Investment Property",
                                            "credit_account": "Accounts Payable",
                                            "amount": _pay_add,
                                            "period": _dt,
                                            "income_statement_line_item": None,
                                            "cashflow_line_item": None,
                                            "description": f"AssetCo Acquisition (payable recognition) - Asset {idx}",
                                            "reference": f"AC-CFI-{_ref_code}-AP-{idx}-{_dt}",
                                        })
                                        _pay_bal += _pay_add
                                
                                if _cash > 0.01:
                                    _pay_settle = min(_cash, _pay_bal)
                                    if _pay_settle > 0.0:
                                        _prog_entries.append({
                                            "debit_account": "Accounts Payable",
                                            "credit_account": "Cash and Cash Equivalents",
                                            "amount": _pay_settle,
                                            "period": _dt,
                                            "income_statement_line_item": None,
                                            "cashflow_line_item": _cf_line_item,
                                            "description": f"AssetCo Acquisition cash settlement - Asset {idx}",
                                            "reference": f"AC-CFI-{_ref_code}-PAY-{idx}-{_dt}",
                                        })
                                        _pay_bal -= _pay_settle
                                        _cash    -= _pay_settle
                                    
                                    if _cash > 0.01:
                                        _prog_entries.append({
                                            "debit_account": "Advances for Land",
                                            "credit_account": "Cash and Cash Equivalents",
                                            "amount": _cash,
                                            "period": _dt,
                                            "income_statement_line_item": None,
                                            "cashflow_line_item": _cf_line_item,
                                            "description": f"AssetCo Acquisition advance payment - Asset {idx}",
                                            "reference": f"AC-CFI-{_ref_code}-ADVP-{idx}-{_dt}",
                                        })
                                        _adv_bal += _cash
                            
                            # OPTIMIZATION 3: Batch append instead of individual appends
                            _e91.extend(_prog_entries)
                            continue

                        # ── Standard cash entry ─────────────────────────────────────
                        if _cfi_row_label not in _cfi_numeric.index:
                            print(f"AssetCo asset {idx} ({_asset_id_label}): CFI row '{_cfi_row_label}' not found, skipping.")
                            continue
                        row_data = _cfi_numeric.loc[_cfi_row_label]
                        if isinstance(row_data, pd.DataFrame):
                            row_data = row_data.iloc[0]
                        amounts = np.abs(row_data.to_numpy(dtype="float64"))
                        if not np.any(amounts):
                            continue
                        # Vectorised: only iterate non-zero periods
                        _nz_mask = amounts != 0.0
                        for _pc, _amt in zip(_arr_period_cols[_nz_mask], amounts[_nz_mask]):
                            _ps = _col_map.get(_pc)
                            if _ps is None:
                                continue
                            _e91.append({
                                "debit_account": "Investment Property",
                                "credit_account": "Cash and Cash Equivalents",
                                "amount": float(_amt),
                                "period": _ps,
                                "income_statement_line_item": None,
                                "cashflow_line_item": _cf_line_item,
                                "description": f"AssetCo CFI - {_cfi_row_label} - Asset {idx}",
                                "reference": f"AC-CFI-{_ref_code}-{idx}-{_pc}",
                            })

                    # Interparty elimination (reversal)
                    if _is_devco_acquisition and _ENABLE_INTERPARTY_ELIMINATION:
                        for _base_entry in list(_e91):
                            if "-ACQPRICE-" not in _base_entry["reference"]:
                                continue
                            _e91.append({
                                "debit_account":  _base_entry["credit_account"] + " - Interparty Elimination",
                                "credit_account": _base_entry["debit_account"]  + " - Interparty Elimination",
                                "amount":  _base_entry["amount"],
                                "period":  _base_entry["period"],
                                "income_statement_line_item": None,
                                "cashflow_line_item": (
                                    _base_entry["cashflow_line_item"] + " - Interparty Elimination"
                                    if _base_entry.get("cashflow_line_item") else None
                                ),
                                "description": _base_entry["description"] + " (Interparty Elimination)",
                                "reference":   _base_entry["reference"]   + "-IE",
                            })

                # ================================================================
                # PHASE 9.1E – CFO Operating Entries
                # ================================================================
                if _cfo_numeric is not None:
                    _e91e = _entries["9.1E"]
                    for (_cfo_row_label, _cf_line_item, _debit_acct, _credit_acct, _ref_code) in _all_assetco_cfo_items:
                        if _cfo_row_label not in _cfo_numeric.index:
                            print(f"AssetCo asset {idx} ({_asset_id_label}): CFO row '{_cfo_row_label}' not found, skipping.")
                            continue
                        row_data = _cfo_numeric.loc[_cfo_row_label]
                        if isinstance(row_data, pd.DataFrame):
                            row_data = row_data.iloc[0]
                        amounts = np.abs(row_data.to_numpy(dtype="float64"))
                        if not np.any(amounts):
                            continue
                        _debit_type  = _account_names_dict.get(_debit_acct,  {}).get("type")
                        _credit_type = _account_names_dict.get(_credit_acct, {}).get("type")
                        _is_line_item: Optional[str] = (
                            _debit_acct  if _debit_type  == "Expense" else
                            _credit_acct if _credit_type == "Revenue" else None
                        )
                        _nz_mask = amounts != 0.0
                        for _pc, _amt in zip(_arr_period_cols[_nz_mask], amounts[_nz_mask]):
                            _ps = _col_map.get(_pc)
                            if _ps is None:
                                continue
                            _e91e.append({
                                "debit_account":  _debit_acct,
                                "credit_account": _credit_acct,
                                "amount": float(_amt),
                                "period": _ps,
                                "income_statement_line_item": _is_line_item,
                                "cashflow_line_item": _cf_line_item,
                                "description": f"AssetCo CFO - {_cfo_row_label} - Asset {idx}",
                                "reference": f"AC-CFO-{_ref_code}-{idx}-{_pc}",
                            })

                # ================================================================
                # PHASE 9.1F – Sinking Fund & Maintenance Capex
                # ================================================================
                _sf_vals   = np.zeros(len(_period_cols), dtype="float64")
                _mc_by_row: Dict[str, np.ndarray] = {}
                _total_mc  = np.zeros(len(_period_cols), dtype="float64")

                if _cfo_numeric is not None and "Sinking Fund" in _cfo_numeric.index:
                    sf_row = _cfo_numeric.loc["Sinking Fund"]
                    if isinstance(sf_row, pd.DataFrame):
                        sf_row = sf_row.iloc[0]
                    _sf_vals = np.abs(sf_row.to_numpy(dtype="float64"))

                if _cfi_numeric is not None:
                    for _maint_row_label, _maint_cf_item, _maint_ref in _assetco_maintenance_capex_items:
                        if _maint_row_label not in _cfi_numeric.index:
                            continue
                        m_row = _cfi_numeric.loc[_maint_row_label]
                        if isinstance(m_row, pd.DataFrame):
                            m_row = m_row.iloc[0]
                        m_vals = np.abs(m_row.to_numpy(dtype="float64"))
                        _mc_by_row[_maint_row_label] = m_vals
                        _total_mc += m_vals

                if np.any(_sf_vals) or np.any(_total_mc):
                    _e91f = _entries["9.1F"]
                    _sf_balance = 0.0
                    for p_idx, period_col in enumerate(_period_cols):
                        period_str = _col_map.get(period_col)
                        if period_str is None:
                            continue
                        sf_c = float(_sf_vals[p_idx])
                        if sf_c > 0.0:
                            _e91f.append({
                                "debit_account": "Restricted Cash - Sinking Fund",
                                "credit_account": "Cash and Cash Equivalents",
                                "amount": sf_c,
                                "period": period_str,
                                "income_statement_line_item": None,
                                "cashflow_line_item": "Sinking Fund",
                                "description": f"Sinking Fund Contribution - Asset {idx}",
                                "reference": f"AC-SF-CONTRIB-{idx}-{period_col}",
                            })
                            _sf_balance += sf_c
                        period_total_capex = float(_total_mc[p_idx])
                        if period_total_capex > 0.0:
                            sf_release = min(period_total_capex, _sf_balance)
                            if sf_release > 0.0:
                                _e91f.append({
                                    "debit_account": "Cash and Cash Equivalents",
                                    "credit_account": "Restricted Cash - Sinking Fund",
                                    "amount": sf_release,
                                    "period": period_str,
                                    "income_statement_line_item": None,
                                    "cashflow_line_item": None,
                                    "description": f"Sinking Fund Release for Maintenance Capex - Asset {idx}",
                                    "reference": f"AC-SF-RELEASE-{idx}-{period_col}",
                                })
                                _sf_balance -= sf_release
                            for _maint_row_label, _maint_cf_item, _maint_ref in _assetco_maintenance_capex_items:
                                item_vals = _mc_by_row.get(_maint_row_label)
                                if item_vals is None:
                                    continue
                                item_amount = float(item_vals[p_idx])
                                if item_amount == 0.0:
                                    continue
                                _e91f.append({
                                    "debit_account": "Maintenance Capex Expense",
                                    "credit_account": "Cash and Cash Equivalents",
                                    "amount": item_amount,
                                    "period": period_str,
                                    "income_statement_line_item": "Maintenance Capex Expense",
                                    "cashflow_line_item": _maint_cf_item,
                                    "description": f"AssetCo CFI - {_maint_row_label} - Asset {idx}",
                                    "reference": f"AC-CFI-{_maint_ref}-{idx}-{period_col}",
                                })

            except Exception as _e91f:
                print(f"ERROR in Phase 9.1F for asset {idx}: {_e91f}")
                traceback.print_exc()

            return _entries

        # --------------------------------------------------------------------
        # 9.1G Process AssetCo Tenant Fitout Allowance Entries
        # --------------------------------------------------------------------
        # For each active AssetCo asset, extract Tenant Fitout Allowance from
        # CFI and record capex entries. Unlike Maintenance Capex, Tenant Fitout
        # Allowance does NOT participate in the sinking fund release logic.
        #
        # Dr Investment Property / Cr Cash and Cash Equivalents
        # --------------------------------------------------------------------

        _batched_tfa_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            cfi_df = _assetco_cfi_dfs.get(idx)
            if cfi_df is None or cfi_df.empty:
                continue

            if "Tenant Fitout Allowance" not in cfi_df.index:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            # Pre-convert CFI DataFrame to numeric once per asset.
            _cfi_numeric = (
                cfi_df.reindex(columns=_period_cols)
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
            )

            if "Tenant Fitout Allowance" not in _cfi_numeric.index:
                continue

            tfa_row = _cfi_numeric.loc["Tenant Fitout Allowance"]
            if isinstance(tfa_row, pd.DataFrame):
                tfa_row = tfa_row.iloc[0]

            tfa_values = np.abs(tfa_row.to_numpy(dtype="float64"))

            if not np.any(tfa_values):
                continue

            for p_idx, period_col in enumerate(_period_cols):
                period_str = _col_map.get(period_col)
                if period_str is None:
                    continue
                tfa_amount = float(tfa_values[p_idx])
                if tfa_amount == 0.0:
                    continue

                _batched_tfa_entries.append({
                    "debit_account": "Investment Property",
                    "credit_account": "Cash and Cash Equivalents",
                    "amount": tfa_amount,
                    "period": period_str,
                    "income_statement_line_item": None,
                    "cashflow_line_item": "Tenant Fitout Allowance",
                    "description": (
                        f"AssetCo CFI - Tenant Fitout Allowance - "
                        f"Asset {_asset_id_label}"
                    ),
                    "reference": f"AC-CFI-TFA-{idx}-{period_col}",
                })

          except Exception as _e91g:
            print(f"ERROR in Phase 9.1G for asset {idx}: {_e91g}")
            traceback.print_exc()

        if _batched_tfa_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_tfa_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
        else:
            print("Phase 9.1G: No Tenant Fitout Allowance entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.1G: Tenant Fitout Allowance Entries")

        # --------------------------------------------------------------------
        # 9.1H Process AssetCo Hospitality Revenue Entries
        # --------------------------------------------------------------------
        # For each hospitality asset, extract revenue line items from the
        # asset's Hospitality P&L DataFrame and post journal entries.
        #
        # Revenue items: Dr Cash and Cash Equivalents / Cr Revenue Account
        #
        # Mapping from Hospitality P&L row labels to consolidated accounts:
        #   Room Revenue                  ? Hospitality - Room Revenue
        #   In Room-Dining + Venue - F&B
        #     + Other F&B Revenue         ? Hospitality - F&B Revenue
        #   Golf Revenue + Spa & Wellness - Revenue
        #     + Banquet & Conference Revenue
        #     + Guest Laundry Revenue     ? Hospitality - OOD Revenue
        #   Minor Operating Department + Cancellation Charges
        #     + Miscellaneous Income
        #     + Parking Revenue           ? Hospitality - Other Operating Income
        # --------------------------------------------------------------------

        _hospitality_revenue_mapping = {
            "Hospitality - Room Revenue": {
                "pnl_rows": ["Room Revenue"],
                "cf_line_item": "Hospitality - Room Revenue",
                "ref_code": "HOSPROOM",
            },
            "Hospitality - F&B Revenue": {
                "pnl_rows": ["In Room-Dining", "Venue - F&B", "Other F&B Revenue"],
                "cf_line_item": "Hospitality - F&B Revenue",
                "ref_code": "HOSPFB",
            },
            "Hospitality - OOD Revenue": {
                "pnl_rows": ["Golf Revenue", "Spa & Wellness - Revenue", "Banquet & Conference Revenue", "Guest Laundry Revenue"],
                "cf_line_item": "Hospitality - OOD Revenue",
                "ref_code": "HOSPOOD",
            },
            "Hospitality - Other Operating Income": {
                "pnl_rows": ["Minor Operating Department", "Cancellation Charges", "Miscellaneous Income", "Parking Revenue"],
                "cf_line_item": "Hospitality - Other Operating Income",
                "ref_code": "HOSPOTHER",
            },
        }

        _batched_hosp_revenue_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            hosp_df = _assetco_hospitality_pnl_dfs.get(idx)
            if hosp_df is None or hosp_df.empty:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            for _credit_acct, _cfg in _hospitality_revenue_mapping.items():
                _pnl_rows = _cfg["pnl_rows"]
                _cf_line = _cfg["cf_line_item"]
                _ref_code = _cfg["ref_code"]

                # Sum amounts across all P&L rows that map to this account
                _combined_amounts = np.zeros(len(_period_cols), dtype="float64")
                _found_any = False
                for _row_label in _pnl_rows:
                    if _row_label not in hosp_df.index:
                        continue
                    _found_any = True
                    _row_data = hosp_df.loc[_row_label]
                    if isinstance(_row_data, pd.DataFrame):
                        _row_data = _row_data.iloc[0]
                    _row_vals = pd.to_numeric(
                        _row_data.reindex(_period_cols), errors="coerce"
                    ).fillna(0.0).to_numpy(dtype="float64")
                    _combined_amounts += np.abs(_row_vals)

                if not _found_any or not np.any(_combined_amounts):
                    continue

                for (period_col, amount) in zip(_period_cols, _combined_amounts):
                    period_str = _col_map.get(period_col)
                    if period_str is None or amount == 0.0:
                        continue

                    _batched_hosp_revenue_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": _credit_acct,
                        "amount": float(amount),
                        "period": period_str,
                        "income_statement_line_item": _credit_acct,
                        "cashflow_line_item": _cf_line,
                        "description": (
                            f"AssetCo Hospitality Revenue - {_credit_acct} - "
                            f"Asset {_asset_id_label}"
                        ),
                        "reference": f"AC-HOSP-{_ref_code}-{idx}-{period_col}",
                    })

          except Exception as _e91h:
            print(f"ERROR in Phase 9.1H for asset {idx}: {_e91h}")
            traceback.print_exc()

        if _batched_hosp_revenue_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_hosp_revenue_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
            
        else:
            print("Phase 9.1H: No hospitality revenue entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.1H: Hospitality Revenue Entries")

        # --------------------------------------------------------------------
        # 9.1I Process AssetCo Hospitality Expense Entries
        # --------------------------------------------------------------------
        # For each hospitality asset, extract expense line items from the
        # asset's Hospitality P&L DataFrame and post journal entries.
        #
        # Expense items: Dr Expense Account / Cr Cash and Cash Equivalents
        #
        # Departmental Expenses:
        #   Room Expense                  ? Hospitality Departmental Expenses - Room
        #   F&B Expense                   ? Hospitality Departmental Expenses - F&B
        #   Golf + Spa & Wellness + Banquet & Conference
        #     + Laundry                   ? Hospitality Departmental Expenses - OOD
        #   Other Departmental Expenses
        #     + Parking Expense           ? Hospitality Departmental Expenses - Other
        #
        # Undistributed Expenses:
        #   Admin & General               ? Hospitality Undistributed Expenses - Admin
        #   Franchise & Affil. Adv. + Loyalty Programs
        #     + Other Expense (S&M)       ? Hospitality Undistributed Expenses - S&M
        #   Info & Telecom Systems        ? Hospitality Undistributed Expenses - IT
        #   Electricity + Gas + Water & Sewer
        #     + Other Expense (Utility)
        #     + Other Expense (H,L,P)     ? Hospitality Undistributed Expenses - Utilities
        # --------------------------------------------------------------------

        _hospitality_expense_mapping = {
            "Hospitality Departmental Expenses - Room": {
                "pnl_rows": ["Room Expense", "Room Expenses"],
                "cf_line_item": "Hospitality Departmental Expenses - Room",
                "ref_code": "HOSPRMEXP",
            },
            "Hospitality Departmental Expenses - F&B": {
                "pnl_rows": ["F&B Expense", "Food and Beverage Expenses"],
                "cf_line_item": "Hospitality Departmental Expenses - F&B",
                "ref_code": "HOSPFBEXP",
            },
            "Hospitality Departmental Expenses - OOD": {
                "pnl_rows": [
                    "Golf Expense", "Golf",
                    "Spa & Wellness Expense", "Spa & Wellness",
                    "Banquet & Conference Expense", "Banquet & Conference",
                    "Laundry Expense", "Laundry",
                ],
                "cf_line_item": "Hospitality Departmental Expenses - OOD",
                "ref_code": "HOSPOODEXP",
            },
            "Hospitality Departmental Expenses - Other": {
                "pnl_rows": ["Other Departmental Expenses", "Parking Expense"],
                "cf_line_item": "Hospitality Departmental Expenses - Other",
                "ref_code": "HOSPOTHEXP",
            },
            "Hospitality Undistributed Expenses - Admin": {
                "pnl_rows": ["Admin & General"],
                "cf_line_item": "Hospitality Undistributed Expenses - Admin",
                "ref_code": "HOSPADMIN",
            },
            "Hospitality Undistributed Expenses - Sales & Marketing": {
                "pnl_rows": [
                    "Franchise & Affiliation Advertising",
                    "Franchise and Affiliation Advertising",
                    "Loyalty Programs",
                    "Other Expense (S&M)",
                ],
                "cf_line_item": "Hospitality Undistributed Expenses - Sales & Marketing",
                "ref_code": "HOSPSM",
            },
            "Hospitality Undistributed Expenses - IT": {
                "pnl_rows": ["Info & Telecom Systems", "Info & Telecom System"],
                "cf_line_item": "Hospitality Undistributed Expenses - IT",
                "ref_code": "HOSPIT",
            },
            "Hospitality Undistributed Expenses - Utilities": {
                "pnl_rows": [
                    "Electricity", "Gas", "Water & Sewer",
                    "Other Expense (Utility)", "Other Expense (H,L,P)",
                ],
                "cf_line_item": "Hospitality Undistributed Expenses - Utilities",
                "ref_code": "HOSPUTIL",
            },
        }

        _batched_hosp_expense_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            hosp_df = _assetco_hospitality_pnl_dfs.get(idx)
            if hosp_df is None or hosp_df.empty:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            print(
                f"Phase 9.1I asset {idx} ({_asset_id_label}): "
                f"Processing hospitality expense entries"
            )

            for _debit_acct, _cfg in _hospitality_expense_mapping.items():
                _pnl_rows = _cfg["pnl_rows"]
                _cf_line = _cfg["cf_line_item"]
                _ref_code = _cfg["ref_code"]

                # Sum amounts across all P&L rows that map to this account
                _combined_amounts = np.zeros(len(_period_cols), dtype="float64")
                _found_any = False
                for _row_label in _pnl_rows:
                    if _row_label not in hosp_df.index:
                        continue
                    _found_any = True
                    _row_data = hosp_df.loc[_row_label]
                    if isinstance(_row_data, pd.DataFrame):
                        _row_data = _row_data.iloc[0]
                    _row_vals = pd.to_numeric(
                        _row_data.reindex(_period_cols), errors="coerce"
                    ).fillna(0.0).to_numpy(dtype="float64")
                    _combined_amounts += np.abs(_row_vals)

                if not _found_any or not np.any(_combined_amounts):
                    continue

                for (period_col, amount) in zip(_period_cols, _combined_amounts):
                    period_str = _col_map.get(period_col)
                    if period_str is None or amount == 0.0:
                        continue

                    _batched_hosp_expense_entries.append({
                        "debit_account": _debit_acct,
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": float(amount),
                        "period": period_str,
                        "income_statement_line_item": _debit_acct,
                        "cashflow_line_item": _cf_line,
                        "description": (
                            f"AssetCo Hospitality Expense - {_debit_acct} - "
                            f"Asset {_asset_id_label}"
                        ),
                        "reference": f"AC-HOSP-{_ref_code}-{idx}-{period_col}",
                    })

          except Exception as _e91i:
            print(f"ERROR in Phase 9.1I for asset {idx}: {_e91i}")
            traceback.print_exc()

        if _batched_hosp_expense_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_hosp_expense_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
            
        else:
            print("Phase 9.1I: No hospitality expense entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.1I: Hospitality Expense Entries")

        # --------------------------------------------------------------------
        # 9.1J Process AssetCo Hospitality Non-Operating I&E Entries
        # --------------------------------------------------------------------
        # Non-Operating Expenses (Dr Expense / Cr Cash):
        #   Insurance, Other Expense 1/2/3
        # Non-Operating Income (Dr Cash / Cr Revenue):
        #   Other Income 1/2/3
        # --------------------------------------------------------------------

        _hospitality_nonop_expense_rows = ["Insurance", "Other Expense 1", "Other Expense 2", "Other Expense 3"]
        _hospitality_nonop_income_rows = ["Other Income 1", "Other Income 2", "Other Income 3"]

        _batched_hosp_nonop_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            hosp_df = _assetco_hospitality_pnl_dfs.get(idx)
            if hosp_df is None or hosp_df.empty:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            # --- Non-Operating Expenses ---
            _nonop_exp_amounts = np.zeros(len(_period_cols), dtype="float64")
            _found_exp = False
            for _row_label in _hospitality_nonop_expense_rows:
                if _row_label not in hosp_df.index:
                    continue
                _found_exp = True
                _row_data = hosp_df.loc[_row_label]
                if isinstance(_row_data, pd.DataFrame):
                    _row_data = _row_data.iloc[0]
                _row_vals = pd.to_numeric(
                    _row_data.reindex(_period_cols), errors="coerce"
                ).fillna(0.0).to_numpy(dtype="float64")
                _nonop_exp_amounts += np.abs(_row_vals)

            if _found_exp and np.any(_nonop_exp_amounts):
                for (period_col, amount) in zip(_period_cols, _nonop_exp_amounts):
                    period_str = _col_map.get(period_col)
                    if period_str is None or amount == 0.0:
                        continue
                    _batched_hosp_nonop_entries.append({
                        "debit_account": "Hospitality Non-Operating Expenses",
                        "credit_account": "Cash and Cash Equivalents",
                        "amount": float(amount),
                        "period": period_str,
                        "income_statement_line_item": "Hospitality Non-Operating Expenses",
                        "cashflow_line_item": "Hospitality Non-Operating Expenses",
                        "description": (
                            f"AssetCo Hospitality Non-Op Expense - Asset {_asset_id_label}"
                        ),
                        "reference": f"AC-HOSP-NONOPEXP-{idx}-{period_col}",
                    })

            # --- Non-Operating Income ---
            _nonop_inc_amounts = np.zeros(len(_period_cols), dtype="float64")
            _found_inc = False
            for _row_label in _hospitality_nonop_income_rows:
                if _row_label not in hosp_df.index:
                    continue
                _found_inc = True
                _row_data = hosp_df.loc[_row_label]
                if isinstance(_row_data, pd.DataFrame):
                    _row_data = _row_data.iloc[0]
                _row_vals = pd.to_numeric(
                    _row_data.reindex(_period_cols), errors="coerce"
                ).fillna(0.0).to_numpy(dtype="float64")
                _nonop_inc_amounts += np.abs(_row_vals)

            if _found_inc and np.any(_nonop_inc_amounts):
                for (period_col, amount) in zip(_period_cols, _nonop_inc_amounts):
                    period_str = _col_map.get(period_col)
                    if period_str is None or amount == 0.0:
                        continue
                    _batched_hosp_nonop_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Hospitality Non-Operating Income",
                        "amount": float(amount),
                        "period": period_str,
                        "income_statement_line_item": "Hospitality Non-Operating Income",
                        "cashflow_line_item": "Hospitality Non-Operating Income",
                        "description": (
                            f"AssetCo Hospitality Non-Op Income - Asset {_asset_id_label}"
                        ),
                        "reference": f"AC-HOSP-NONOPINC-{idx}-{period_col}",
                    })

          except Exception as _e91j:
            print(f"ERROR in Phase 9.1J for asset {idx}: {_e91j}")
            traceback.print_exc()

        if _batched_hosp_nonop_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_hosp_nonop_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
            
        else:
            print("Phase 9.1J: No hospitality non-operating entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.1J: Hospitality Non-Operating I&E Entries")

        # --------------------------------------------------------------------
        # 9.5 Process AssetCo CFF Debt & Financing Entries
        # --------------------------------------------------------------------
        # For each active AssetCo asset, extract CFF line items from the
        # asset's Cashflow from Financing DataFrame (rows = line items).
        #
        # Term Loan:
        #   Principal Drawn:   Dr Cash / Cr Debt - Term Loan
        #   Principal Repaid:  Dr Debt - Term Loan / Cr Cash
        #   Interest Paid:     Dr Interest Expense - Term Loan / Cr Cash
        #   Arrangement Fees:  Dr Debt Fees Expense / Cr Cash
        #
        # Asset Level Revolver:
        #   Principal Drawn:   Dr Cash / Cr Debt - Revolver
        #   Principal Repaid:  Dr Debt - Revolver / Cr Cash
        #   Interest Paid:     Dr Interest Expense - Revolver / Cr Cash
        #   Arrangement Fees:  Dr Debt Fees Expense / Cr Cash
        #
        # No interest or fee capitalization. All interest/fees expensed.
        # Debt schedules maintained via T-account rollforward
        # (Opening + Drawdowns - Repayments = Closing).
        #
        # Equity Injection: Dr Cash / Cr Share Capital (direct cash inflow).
        # --------------------------------------------------------------------

        _assetco_cff_facility_configs = [
            {
                "name": "Term Loan",
                "header_label": "Asset Level Term Loan",
                "items": [
                    # (offset_from_header, cf_line_item, debit_acct, credit_acct, is_line_item, ref_code)
                    (1, "Term Loan - Debt Drawdown",     "Cash and Cash Equivalents",    "Debt - Term Loan",   None,                           "DD"),
                    (2, "Term Loan - Debt Repayment",    "Debt - Term Loan",   "Cash and Cash Equivalents",    None,                           "REPAY"),
                    (3, "Term Loan - Interest Payments", "Interest Expense - Term Loan", "Cash and Cash Equivalents",    "Interest Expense - Term Loan", "INT"),
                    (4, "Term Loan - Debt Fees",         "Debt Fees Expense",            "Cash and Cash Equivalents",    "Debt Fees Expense",            "ARRFEE"),
                ],
                "ref_prefix": "AC-TL",
            },
            {
                "name": "Asset Level Revolver",
                "header_label": "Asset Level Refinancing Facility",
                "items": [
                    (1, "Revolver - Debt Drawdown",      "Cash and Cash Equivalents",    "Debt - Revolver",    None,                            "DD"),
                    (2, "Revolver - Debt Repayment",     "Debt - Revolver",    "Cash and Cash Equivalents",    None,                            "REPAY"),
                    (3, "Revolver - Interest Payments",  "Interest Expense - Revolver",  "Cash and Cash Equivalents",    "Interest Expense - Revolver",  "INT"),
                    (4, "Revolver - Debt Fees",          "Debt Fees Expense",            "Cash and Cash Equivalents",    "Debt Fees Expense",            "ARRFEE"),
                ],
                "ref_prefix": "AC-REV",
            },
        ]

        _batched_assetco_cff_entries: List[Dict[str, Any]] = []
        _batched_depreciation_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            cff_df = _assetco_cff_dfs.get(idx)
            if cff_df is None or cff_df.empty:
                print(f"AssetCo asset {idx}: CFF DataFrame not available, skipping 9.5 debt entries.")
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            # --- Process each debt facility ---
            _cff_index_list = cff_df.index.tolist()
            _cff_index_lower = [str(l).strip().lower() for l in _cff_index_list]

            for _fac_config in _assetco_cff_facility_configs:
                _fac_name = _fac_config["name"]
                _fac_ref = _fac_config["ref_prefix"]
                _header_label = _fac_config["header_label"]

                # Find the header row position by case-insensitive match
                _header_pos = None
                _header_lower = _header_label.strip().lower()
                for _hi, _hl in enumerate(_cff_index_lower):
                    if _hl == _header_lower:
                        _header_pos = _hi
                        break

                if _header_pos is None:
                    continue

                for (_offset, _cf_line, _debit_acct, _credit_acct, _is_line, _item_ref) in _fac_config["items"]:
                    _row_pos = _header_pos + _offset
                    if _row_pos >= len(_cff_index_list):
                        continue

                    row_data = cff_df.iloc[_row_pos]

                    amounts = pd.to_numeric(
                        row_data.reindex(_period_cols), errors="coerce"
                    ).fillna(0.0).to_numpy(dtype="float64")

                    amounts = np.abs(amounts)

                    if not np.any(amounts):
                        continue

                    for period_col, amount in zip(_period_cols, amounts):
                        period_str = _col_map.get(period_col)
                        if period_str is None or amount == 0.0:
                            continue

                        _batched_assetco_cff_entries.append({
                            "debit_account": _debit_acct,
                            "credit_account": _credit_acct,
                            "amount": float(amount),
                            "period": period_str,
                            "income_statement_line_item": _is_line,
                            "cashflow_line_item": _cf_line,
                            "description": (
                                f"AssetCo CFF - {_fac_name} {_cff_index_list[_row_pos]} - "
                                f"Asset {_asset_id_label}"
                            ),
                            "reference": f"{_fac_ref}-{_item_ref}-{idx}-{period_col}",
                        })

            # --- Equity injection (once per asset, outside facility loop) ---
            _equity_label = next(
                (c for c in ["Equity Injection", "Equity Contribution", "Share Capital Injection"]
                 if c in cff_df.index), None
            )
            if _equity_label is not None:
                eq_row = cff_df.loc[_equity_label]
                if isinstance(eq_row, pd.DataFrame):
                    eq_row = eq_row.iloc[0]
                eq_amounts = np.abs(
                    pd.to_numeric(eq_row.reindex(_period_cols), errors="coerce")
                    .fillna(0.0).to_numpy(dtype="float64")
                )
                _nz_mask = eq_amounts != 0.0
                for _pc, _amt in zip(np.array(_period_cols)[_nz_mask], eq_amounts[_nz_mask]):
                    _ps = _col_map.get(_pc)
                    if _ps is None:
                        continue
                    _batched_assetco_cff_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Share Capital",
                        "amount": float(_amt),
                        "period": _ps,
                        "income_statement_line_item": None,
                        "cashflow_line_item": "Project and Asset Equity Contribution",
                        "description": f"AssetCo CFF - Equity Injection - Asset {idx}",
                        "reference": f"AC-EQ-{idx}-{_pc}",
                    })

          except Exception as _e95a:
            print(f"ERROR in Phase 9.5 for asset {idx}: {_e95a}")
            traceback.print_exc()

        if _batched_assetco_cff_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_assetco_cff_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
        else:
            print("Phase 9.5: No CFF debt/financing/equity entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.5: AssetCo CFF Debt & Financing Entries")

        for idx in sorted(_active_assetco_indices):
          try:
            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()
            _acq_price_raw = _assetco_acquisition_price.get(idx, None)
            _residual_raw  = _assetco_residual_value.get(idx, None)
            _holding_raw   = _assetco_holding_period.get(idx, None)
            _acq_date_raw  = _assetco_acquisition_date.get(idx, None)
            try:
                _acq_price = float(_acq_price_raw) if _acq_price_raw is not None else 0.0
            except (ValueError, TypeError):
                _acq_price = 0.0
            try:
                _residual_val = float(_residual_raw) if _residual_raw is not None else 0.0
            except (ValueError, TypeError):
                _residual_val = 0.0
            try:
                _holding_months = int(float(_holding_raw)) if _holding_raw is not None else 0
            except (ValueError, TypeError):
                _holding_months = 0

            if _acq_price <= 0.0 or _holding_months <= 0:
                print(
                    f"AssetCo asset {idx} ({_asset_id_label}): Skipping depreciation - "
                    f"acq_price={_acq_price}, holding_months={_holding_months}"
                )
                continue

            # --- Sum acquisition costs from CFI ---
            _total_acq_costs = 0.0
            cfi_df = _assetco_cfi_dfs.get(idx)
            if cfi_df is not None and not cfi_df.empty:
                _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
                _period_cols = list(_col_map.keys())
                for _acq_row_label in _acquisition_cost_row_labels:
                    if _acq_row_label in cfi_df.index:
                        _acq_row = cfi_df.loc[_acq_row_label]
                        if isinstance(_acq_row, pd.DataFrame):
                            _acq_row = _acq_row.iloc[0]
                        _acq_vals = np.abs(
                            pd.to_numeric(
                                _acq_row.reindex(_period_cols), errors="coerce"
                            ).fillna(0.0).to_numpy(dtype="float64")
                        )
                        _total_acq_costs += float(np.sum(_acq_vals))

            # --- Compute depreciable base and monthly depreciation ---
            _depreciable_base = _acq_price + _total_acq_costs - _residual_val
            if _depreciable_base <= 0.0:
                print(
                    f"AssetCo asset {idx} ({_asset_id_label}): Skipping depreciation - "
                    f"depreciable_base={_depreciable_base:.2f} "
                    f"(acq={_acq_price:.2f} + costs={_total_acq_costs:.2f} - residual={_residual_val:.2f})"
                )
                continue

            _monthly_depreciation = _depreciable_base / _holding_months

            # --- Find acquisition start period ---
            _acq_date_ts = None
            if _acq_date_raw:
                try:
                    _acq_date_ts = pd.Timestamp(_acq_date_raw)
                except Exception:
                    pass

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            # Determine the period index at which acquisition occurs
            _depr_start_p_idx = 0
            if _acq_date_ts is not None and _period_ends is not None and len(_period_ends) > 0:
                for _pi, _pe in enumerate(_period_ends):
                    if pd.Timestamp(_pe) >= _acq_date_ts:
                        _depr_start_p_idx = _pi
                        break

            # --- Generate monthly depreciation entries ---
            _months_posted = 0
            for p_idx in range(len(_period_cols)):
                if p_idx < _depr_start_p_idx:
                    continue
                if _months_posted >= _holding_months:
                    break

                period_col = _period_cols[p_idx]
                period_str = _col_map.get(period_col)
                if period_str is None:
                    continue

                _batched_depreciation_entries.append({
                    "debit_account": "Depreciation Expense",
                    "credit_account": "Accumulated Depreciation",
                    "amount": _monthly_depreciation,
                    "period": period_str,
                    "income_statement_line_item": "Depreciation Expense",
                    "cashflow_line_item": None,
                    "description": f"Monthly Depreciation - Asset {idx}",
                    "reference": f"AC-DEPR-{idx}-{period_col}",
                })
                _months_posted += 1

          except Exception as _e95b:
            print(f"ERROR in Phase 9.5B for asset {idx}: {_e95b}")
            traceback.print_exc()

        if _batched_depreciation_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_batched_depreciation_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
        else:
            print("Phase 9.5B: No depreciation entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.5B: AssetCo Depreciation Entries")

        # --------------------------------------------------------------------
        # 9.5C Process AssetCo Tenant Fitout Depreciation Entries
        # --------------------------------------------------------------------
        # For each active AssetCo asset, depreciate each period's tenant
        # fitout allowance from the period it is recorded until the asset
        # sale date.
        #
        # Monthly Depreciation per capex tranche =
        #     capex_amount / remaining_periods_to_asset_sale_date
        #
        # Entry each month from the capex period through end of holding:
        #   Dr Depreciation Expense / Cr Accumulated Depreciation
        #
        # This is separate from the acquisition-based depreciation in 9.5B.
        # Maintenance capex depreciation is intentionally not posted.
        # Each tenant fitout tranche gets its own depreciation schedule.
        # --------------------------------------------------------------------

        _batched_tfa_depr_entries: List[Dict[str, Any]] = []

        for idx in sorted(_active_assetco_indices):
          try:
            cfi_df = _assetco_cfi_dfs.get(idx)
            if cfi_df is None or cfi_df.empty:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            # --- Determine the asset sale period index ---
            _sale_date_raw = _assetco_asset_sale_date.get(idx, None)
            _sale_date_ts = None
            if _sale_date_raw:
                try:
                    _sale_date_ts = pd.Timestamp(_sale_date_raw)
                except Exception:
                    pass

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())
            _n_total_periods = len(_period_cols)

            # Find the period index of the asset sale date
            _sale_p_idx = _n_total_periods  # default: end of timeline
            if _sale_date_ts is not None and _period_ends is not None and len(_period_ends) > 0:
                for _pi, _pe in enumerate(_period_ends):
                    if pd.Timestamp(_pe) >= _sale_date_ts:
                        _sale_p_idx = _pi
                        break

            # --- Extract maintenance capex amounts per period ---
            _tenant_fitout_items_for_depr = [
                ("Tenant Fitout Allowance", "TFA"),
            ]

            # Pre-convert CFI DataFrame to numeric once per asset.
            _cfi_numeric = (
                cfi_df.reindex(columns=_period_cols)
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
            )

            _asset_tfa_depr_count = 0
            for _tfa_row_label, _tfa_ref in _tenant_fitout_items_for_depr:
                if _tfa_row_label not in _cfi_numeric.index:
                    continue

                m_row = _cfi_numeric.loc[_tfa_row_label]
                if isinstance(m_row, pd.DataFrame):
                    m_row = m_row.iloc[0]

                m_vals = np.abs(m_row.to_numpy(dtype="float64"))

                # For each period with capex, create depreciation schedule
                for capex_p_idx in range(_n_total_periods):
                    capex_amount = float(m_vals[capex_p_idx])
                    if capex_amount == 0.0:
                        continue

                    # Remaining periods from this capex period to asset sale
                    _remaining_periods = _sale_p_idx - capex_p_idx
                    if _remaining_periods <= 0:
                        continue

                    _monthly_maint_depr = capex_amount / _remaining_periods

                    # Post depreciation from the capex period through sale date
                    for depr_p_idx in range(capex_p_idx, _sale_p_idx):
                        if depr_p_idx >= _n_total_periods:
                            break

                        period_col = _period_cols[depr_p_idx]
                        period_str = _col_map.get(period_col)
                        if period_str is None:
                            continue

                        _batched_tfa_depr_entries.append({
                            "debit_account": "Depreciation Expense",
                            "credit_account": "Accumulated Depreciation",
                            "amount": _monthly_maint_depr,
                            "period": period_str,
                            "income_statement_line_item": "Depreciation Expense",
                            "cashflow_line_item": None,
                            "description": (
                                f"Tenant Fitout Depreciation - {_tfa_row_label} "
                                f"(tranche {capex_p_idx}) - Asset {idx}"
                            ),
                            "reference": f"AC-MDEPR-{_tfa_ref}-{idx}-{capex_p_idx}-{depr_p_idx}",
                        })
                        _asset_tfa_depr_count += 1

          except Exception as _e_combined:
            print(f"ERROR in combined entry generation for asset {idx}: {_e_combined}")
            traceback.print_exc()

        # ====================================================================
        # Run combined entry generation in parallel across all assets
        # ====================================================================
        _sorted_active = sorted(_active_assetco_indices)
        _n_workers     = min(len(_sorted_active), os.cpu_count() or 4)

        from concurrent.futures import ThreadPoolExecutor as _TPE

        if _sorted_active:
            if _n_workers > 1:
                with _TPE(max_workers=_n_workers) as _executor:
                    _per_asset_results: List[Dict[str, List[Dict[str, Any]]]] = list(
                        _executor.map(_generate_entries_for_asset_all_phases, _sorted_active)
                    )
            else:
                _per_asset_results = [
                    _generate_entries_for_asset_all_phases(i) for i in _sorted_active
                ]
        else:
            _per_asset_results = []

        # Collect entries per phase (maintains per-asset ordering)
        _phase_order = ["9.1", "9.1E", "9.1F", "9.1G", "9.1H", "9.1I", "9.1J", "9.5", "9.5B", "9.5C"]
        _all_phase_entries: Dict[str, List[Dict[str, Any]]] = {k: [] for k in _phase_order}
        for _ar in _per_asset_results:
            for _pk in _phase_order:
                _all_phase_entries[_pk].extend(_ar.get(_pk, []))

        fn_record_timing(_timing_ctx, "PHASE 9: Parallel per-asset entry generation (9.1 – 9.5C)")

        # ====================================================================
        # Flush each phase's entries sequentially (mutates shared state)
        # ====================================================================
        def _flush_phase(phase_key: str, label: str) -> None:
            nonlocal _all_accounts, _accounting_journal, _financial_statements
            _entries_list = _all_phase_entries[phase_key]
            if _entries_list:
                _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                    batch_entries=_entries_list,
                    accounts=_all_accounts,
                    journal=_accounting_journal,
                    financial_statements=_financial_statements,
                    account_names_dict=_account_names_dict,
                )
            else:
                print(f"Phase {label}: No entries to flush.")
            fn_record_timing(_timing_ctx, f"PHASE {label}")

        _flush_phase("9.1",   "9.1: AssetCo CFI Acquisition Entries")
        _flush_phase("9.1E",  "9.1E: AssetCo CFO Operating Entries")
        _flush_phase("9.1F",  "9.1F: Sinking Fund & Maintenance Capex Entries")
        _flush_phase("9.1G",  "9.1G: Tenant Fitout Allowance Entries")
        _flush_phase("9.1H",  "9.1H: Hospitality Revenue Entries")
        _flush_phase("9.1I",  "9.1I: Hospitality Expense Entries")
        _flush_phase("9.1J",  "9.1J: Hospitality Non-Operating I&E Entries")
        _flush_phase("9.5",   "9.5: AssetCo CFF Debt & Financing Entries")
        _flush_phase("9.5B",  "9.5B: AssetCo Depreciation Entries")
        _flush_phase("9.5C",  "9.5C: Tenant Fitout Depreciation Entries")


        # --------------------------------------------------------------------
        # 9.6 Process AssetCo Asset Sale / Exit Value Entries
        # --------------------------------------------------------------------
        # For each active AssetCo asset, extract sale proceeds from its
        # Cashflow from Investments DataFrame (sum of all matching sale rows).
        # When non-zero in a period:
        #
        #   Step 1: Reverse accumulated depreciation against Investment Property
        #      Dr Accumulated Depreciation / Cr Investment Property
        #      ? Reduces gross carrying amount to net book value
        #
        #   Step 2: Record sale proceeds and balancing gain/loss
        #      Compare sale proceeds vs net book value (post Step 1)
        #      Dr Cash / Cr Investment Property (NBV portion)
        #      Plug difference to:
        #        Gain > 0: Dr Cash / Cr Gain on Asset Disposal
        #        Loss > 0: Dr Loss on Asset Disposal / Cr Investment Property
        #
        #   CF line: "Asset Sale Value"
        # --------------------------------------------------------------------

        _exit_batch_entries: List[Dict[str, Any]] = []

        # Pre-build per-asset journal index for O(1) lookup in Phase 9.6.
        # Groups journal entries by asset index token to avoid O(n*m) scan.
        _journal_by_asset: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for _je in _accounting_journal:
            _je_ref = str(_je.get("reference", ""))
            for _ai in _active_assetco_indices:
                if f"-{_ai}-" in _je_ref:
                    _journal_by_asset[_ai].append(_je)
                    break

        def _sum_asset_account_net_to_period(
            account_name: str,
            asset_index: int,
            up_to_period: str,
        ) -> float:
            """
            Sum net movement (debit - credit) for a specific account and asset
            up to and including a given period.  Uses pre-built per-asset index
            for O(k) lookup instead of scanning the full journal.
            """
            _net = 0.0
            for _je in _journal_by_asset.get(asset_index, []):
                _je_period = str(_je.get("period", ""))
                if not _je_period or _je_period > up_to_period:
                    continue
                _amt = float(_je.get("amount", 0.0) or 0.0)
                if str(_je.get("debit_account", "")) == account_name:
                    _net += _amt
                if str(_je.get("credit_account", "")) == account_name:
                    _net -= _amt
            return _net

        for idx in sorted(_active_assetco_indices):
          try:
            cfi_df = _assetco_cfi_dfs.get(idx)
            if cfi_df is None or cfi_df.empty:
                continue

            # Locate all sale value rows and aggregate them (additive capture).
            _sale_row_labels = []
            for _candidate in [
                "Net Asset Sale Value",
                "Asset Sale Value",
                "Asset Sale Proceeds",
                "Asset Sale",
                "Sale Value",
            ]:
                if _candidate in cfi_df.index:
                    _sale_row_labels.append(_candidate)

            if not _sale_row_labels:
                continue

            _asset_id_label = str(
                _assetco_asset_id.get(idx,
                    _assetco_asset_identifier.get(idx, f"idx:{idx}"))
            ).strip()

            _col_map = _assetco_col_to_period_per_asset.get(idx, _assetco_col_to_period)
            _period_cols = list(_col_map.keys())

            sale_amounts = np.zeros(len(_period_cols), dtype="float64")
            for _sale_row_label in _sale_row_labels:
                _sale_row_data = cfi_df.loc[_sale_row_label]
                if isinstance(_sale_row_data, pd.DataFrame):
                    _sale_vals_df = _sale_row_data.reindex(columns=_period_cols)
                    _sale_vals = np.abs(
                        _sale_vals_df.apply(pd.to_numeric, errors="coerce")
                        .fillna(0.0)
                        .to_numpy(dtype="float64")
                    ).sum(axis=0)
                else:
                    _sale_vals = np.abs(
                        pd.to_numeric(
                            _sale_row_data.reindex(_period_cols), errors="coerce"
                        ).fillna(0.0).to_numpy(dtype="float64")
                    )
                sale_amounts += _sale_vals

            if not np.any(sale_amounts):
                continue

            for period_col, sale_amt in zip(_period_cols, sale_amounts):
                period_str = _col_map.get(period_col)
                if period_str is None or sale_amt == 0.0:
                    continue

                # --- Step 1: Reverse accumulated depreciation ---
                # Dr Accumulated Depreciation / Cr Investment Property
                # Asset-specific accumulated depreciation is derived from posted
                # journal movements up to the sale period.
                _accum_depr_net = _sum_asset_account_net_to_period(
                    account_name="Accumulated Depreciation",
                    asset_index=idx,
                    up_to_period=period_str,
                )
                _accum_depr_balance = max(0.0, -_accum_depr_net)

                if _accum_depr_balance > 0.0:
                    _exit_batch_entries.append({
                        "debit_account": "Accumulated Depreciation",
                        "credit_account": "Investment Property",
                        "amount": _accum_depr_balance,
                        "period": period_str,
                        "asset_no": idx,
                        "income_statement_line_item": None,
                        "cashflow_line_item": None,
                        "description": (
                            f"Asset Sale Step 1 - Reverse Accumulated Depreciation - "
                            f"Asset {idx}"
                        ),
                        "reference": f"AC-SALE-REVDEPR-{idx}-{period_col}",
                    })

                # --- Step 2: Record sale and derive gain/loss ---
                # Compute asset-specific net book value before sale.
                _ip_net = _sum_asset_account_net_to_period(
                    account_name="Investment Property",
                    asset_index=idx,
                    up_to_period=period_str,
                )
                _book_value_post = max(0.0, _ip_net - _accum_depr_balance)

                # Cash proceeds up to NBV portion.
                _cash_to_ip = min(sale_amt, _book_value_post)
                if _cash_to_ip > 0.0:
                    _exit_batch_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Investment Property",
                        "amount": _cash_to_ip,
                        "period": period_str,
                        "asset_no": idx,
                        "income_statement_line_item": None,
                        "cashflow_line_item": "Asset Sale Value",
                        "description": (
                            f"Asset Sale Step 2 - Record Proceeds vs Investment Property - "
                            f"Asset {idx}"
                        ),
                        "reference": f"AC-SALE-PROCEEDS-IP-{idx}-{period_col}",
                    })

                # Gain or Loss = sale proceeds - post-depreciation net book value
                _gain_loss = sale_amt - _book_value_post

                if _gain_loss > 0.0:
                    # Extra proceeds above NBV are recognized as gain.
                    _exit_batch_entries.append({
                        "debit_account": "Cash and Cash Equivalents",
                        "credit_account": "Gain on Asset Disposal",
                        "amount": _gain_loss,
                        "period": period_str,
                        "asset_no": idx,
                        "income_statement_line_item": "Gain on Asset Disposal",
                        "cashflow_line_item": "Asset Sale Value",
                        "description": (
                            f"Asset Sale - Gain on Disposal - "
                            f"Asset {idx}"
                        ),
                        "reference": f"AC-SALE-GAIN-{idx}-{period_col}",
                    })
                elif _gain_loss < 0.0:
                    # When proceeds are below NBV, derecognize the shortfall to loss.
                    _exit_batch_entries.append({
                        "debit_account": "Loss on Asset Disposal",
                        "credit_account": "Investment Property",
                        "amount": abs(_gain_loss),
                        "period": period_str,
                        "asset_no": idx,
                        "income_statement_line_item": "Loss on Asset Disposal",
                        "cashflow_line_item": None,
                        "description": (
                            f"Asset Sale - Loss on Disposal - "
                            f"Asset {idx}"
                        ),
                        "reference": f"AC-SALE-LOSS-{idx}-{period_col}",
                    })

          except Exception as _e96:
            print(f"ERROR in Phase 9.6 for asset {idx}: {_e96}")
            traceback.print_exc()

        if _exit_batch_entries:
            _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                batch_entries=_exit_batch_entries,
                accounts=_all_accounts,
                journal=_accounting_journal,
                financial_statements=_financial_statements,
                account_names_dict=_account_names_dict,
            )
            
        else:
            print("Phase 9.6: No AssetCo asset sale entries to flush.")

        fn_record_timing(_timing_ctx, "PHASE 9.6: AssetCo Asset Sale / Exit Value Entries")

        # --------------------------------------------------------------------
        # 9.6B Filtration Mode — Balancing Equity
        # --------------------------------------------------------------------
        # In filtered modes (single-asset / synthetic):
        # - Asset-level financing entries (Term Loan, Revolver) are already posted.
        # - Project-level equity inputs are ignored.
        # - Post balancing equity per period based on:
        #     Equity = -(CFO + CFI + Asset-Level Financing Cashflow)
        # i.e. net the cash impact of all posted entries and plug the difference.
        # --------------------------------------------------------------------
        _is_filtration_mode = (
            _ASSET_FILTER_MODE.strip().lower() != "consolidated"
            and _ASSET_FILTER_MODE.strip() != ""
        )
        if _is_filtration_mode:
            print(
                "Filtration mode detected: applying balancing equity "
                f"for asset filter '{_ASSET_FILTER_MODE}'."
            )

            # Net cash per period from all journal entries posted so far.
            _period_cash_net: Dict[str, float] = {}
            for _je in _accounting_journal:
                _period = str(_je.get("period", ""))
                if not _period:
                    continue
                _amount = float(_je.get("amount", 0.0) or 0.0)
                _debit_account = _je.get("debit_account")
                _credit_account = _je.get("credit_account")

                if _debit_account == "Cash and Cash Equivalents" and _credit_account != "Cash and Cash Equivalents":
                    _period_cash_net[_period] = _period_cash_net.get(_period, 0.0) + _amount
                elif _credit_account == "Cash and Cash Equivalents" and _debit_account != "Cash and Cash Equivalents":
                    _period_cash_net[_period] = _period_cash_net.get(_period, 0.0) - _amount

            _equity_balance_entries: List[Dict[str, Any]] = []
            for _period_col, _period_str in _assetco_col_to_period.items():
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
                        "reference": f"AC-DEBT-FILT-BEQ-RAISE-{_period_col}",
                    })

            if _equity_balance_entries:
                _all_accounts, _accounting_journal, _financial_statements = fn_flush_batch_entries(
                    batch_entries=_equity_balance_entries,
                    accounts=_all_accounts,
                    journal=_accounting_journal,
                    financial_statements=_financial_statements,
                    account_names_dict=_account_names_dict,
                )

        fn_record_timing(_timing_ctx, "PHASE 9.6B: Filtration Mode Balancing Equity")

        # --------------------------------------------------------------------
        # 9.7 Link Net Income to Retained Earnings
        # --------------------------------------------------------------------
        # Net Income (bottom line of IS) flows to Retained Earnings (BS equity).
        # Revenue credits and Expense debits already exist in accounts.
        # Retained Earnings is credited by net income each period:
        #   If net income > 0: Dr (dummy pass-through) / effect is Cr Retained Earnings
        # We compute net income from the IS and post directly to the
        # Retained Earnings account as a credit (profit) or debit (loss).
        # --------------------------------------------------------------------

        _is_df = _financial_statements.get("income_statement", pd.DataFrame())
        _re_acct = _all_accounts.get("Retained Earnings")
        _re_ie_acct = _all_accounts.get("Retained Earnings - Interparty Elimination")
        _bs_df = _financial_statements.get("balance_sheet", pd.DataFrame())

        if _re_acct is not None and not _re_acct.empty:
            # Split accounts into non-IE (feeds RE) and IE (feeds RE-IE).
            _revenue_accounts = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Revenue" and not name.endswith(" - Interparty Elimination")
            ]
            _expense_accounts = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Expense" and not name.endswith(" - Interparty Elimination")
            ]
            _ie_revenue_accounts = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Revenue" and name.endswith(" - Interparty Elimination")
            ]
            _ie_expense_accounts = [
                name for name, info in _account_names_dict.items()
                if info.get("type") == "Expense" and name.endswith(" - Interparty Elimination")
            ]

            _all_period_strs = _re_acct.columns.tolist()
            _n_periods = len(_all_period_strs)

            # Compute net income from account movements (credits/debits),
            # matching LandCo closing logic and avoiding IS sign-shape issues.
            _rev_total = np.zeros(_n_periods, dtype=float)
            for _rev_name in _revenue_accounts:
                _rev_acct = _all_accounts.get(_rev_name)
                if _rev_acct is None or _rev_acct.empty:
                    continue
                _rev_aligned = _rev_acct.reindex(columns=_all_period_strs, fill_value=0.0)
                _rev_total += (
                    _rev_aligned.loc["Credit"].values.astype(float)
                    - _rev_aligned.loc["Debit"].values.astype(float)
                )

            _exp_total = np.zeros(_n_periods, dtype=float)
            for _exp_name in _expense_accounts:
                _exp_acct = _all_accounts.get(_exp_name)
                if _exp_acct is None or _exp_acct.empty:
                    continue
                _exp_aligned = _exp_acct.reindex(columns=_all_period_strs, fill_value=0.0)
                _exp_total += (
                    _exp_aligned.loc["Debit"].values.astype(float)
                    - _exp_aligned.loc["Credit"].values.astype(float)
                )

            _net_income_arr = _rev_total - _exp_total

            for _p_str, _net_income in zip(_all_period_strs, _net_income_arr):
                _net_income = float(_net_income)
                if _net_income > 0.0:
                    _re_acct.loc["Credit", _p_str] += _net_income
                elif _net_income < 0.0:
                    _re_acct.loc["Debit", _p_str] += abs(_net_income)

                if abs(_net_income) > 1e-9:
                    fn_append_financial_statement_trace_row(
                        financial_statements=_financial_statements,
                        period=_p_str,
                        value=_net_income,
                        financial_statement="Balance Sheet",
                        line_item_name="Retained Earnings",
                        asset_no="Consolidated",
                    )

            if _re_ie_acct is not None and (_ie_revenue_accounts or _ie_expense_accounts):
                _ie_rev_total = np.zeros(_n_periods, dtype=float)
                for _ie_rev_name in _ie_revenue_accounts:
                    _ie_rev_acct = _all_accounts.get(_ie_rev_name)
                    if _ie_rev_acct is None or _ie_rev_acct.empty:
                        continue
                    _ie_rev_aligned = _ie_rev_acct.reindex(columns=_all_period_strs, fill_value=0.0)
                    _ie_rev_total += (
                        _ie_rev_aligned.loc["Credit"].values.astype(float)
                        - _ie_rev_aligned.loc["Debit"].values.astype(float)
                    )

                _ie_exp_total = np.zeros(_n_periods, dtype=float)
                for _ie_exp_name in _ie_expense_accounts:
                    _ie_exp_acct = _all_accounts.get(_ie_exp_name)
                    if _ie_exp_acct is None or _ie_exp_acct.empty:
                        continue
                    _ie_exp_aligned = _ie_exp_acct.reindex(columns=_all_period_strs, fill_value=0.0)
                    _ie_exp_total += (
                        _ie_exp_aligned.loc["Debit"].values.astype(float)
                        - _ie_exp_aligned.loc["Credit"].values.astype(float)
                    )

                _ie_net_income_arr = _ie_rev_total - _ie_exp_total

                for _p_str, _ie_net in zip(_all_period_strs, _ie_net_income_arr):
                    _ie_net = float(_ie_net)
                    if _ie_net > 0.0:
                        _re_ie_acct.loc["Credit", _p_str] += _ie_net
                    elif _ie_net < 0.0:
                        _re_ie_acct.loc["Debit", _p_str] += abs(_ie_net)

                # Per-asset trace rows: scan the journal for -IPRE-/-IPCE-
                # references to derive IE net income attributed to each asset.
                _ac_period_to_idx: Dict[str, int] = {_p: _i for _i, _p in enumerate(_all_period_strs)}
                _n_ac_periods = len(_all_period_strs)
                _ac_asset_ie_rev: Dict[str, np.ndarray] = {}
                _ac_asset_ie_exp: Dict[str, np.ndarray] = {}
                for _je in _accounting_journal:
                    _ref = str(_je.get("reference", ""))
                    _amt = float(_je.get("amount", 0.0) or 0.0)
                    _jp_str = str(_je.get("period", ""))
                    _jp_idx = _ac_period_to_idx.get(_jp_str)
                    if _jp_idx is None or abs(_amt) < 1e-9:
                        continue
                    if "-IPRE-" in _ref:
                        _parts = _ref.split("-IPRE-", 1)
                        if len(_parts) == 2:
                            _aid = _parts[1].split("-")[0]
                            if _aid not in _ac_asset_ie_rev:
                                _ac_asset_ie_rev[_aid] = np.zeros(_n_ac_periods, dtype=float)
                            _ac_asset_ie_rev[_aid][_jp_idx] += _amt
                    elif "-IPCE-" in _ref:
                        _parts = _ref.split("-IPCE-", 1)
                        if len(_parts) == 2:
                            _remaining = _parts[1]
                            if _remaining.startswith("SLA-"):
                                _aid = _remaining[4:].split("-")[0]
                            else:
                                _aid = _remaining.split("-")[0]
                            if _aid not in _ac_asset_ie_exp:
                                _ac_asset_ie_exp[_aid] = np.zeros(_n_ac_periods, dtype=float)
                            _ac_asset_ie_exp[_aid][_jp_idx] += _amt
                _ac_all_asset_ids = sorted(set(_ac_asset_ie_rev) | set(_ac_asset_ie_exp))
                for _aid in _ac_all_asset_ids:
                    _aid_ie_net_arr = (
                        _ac_asset_ie_rev.get(_aid, np.zeros(_n_ac_periods, dtype=float))
                        - _ac_asset_ie_exp.get(_aid, np.zeros(_n_ac_periods, dtype=float))
                    )
                    for _p_str, _ie_net in zip(_all_period_strs, _aid_ie_net_arr):
                        if abs(_ie_net) < 1e-6:
                            continue
                        fn_append_financial_statement_trace_row(
                            financial_statements=_financial_statements,
                            period=_p_str,
                            value=float(_ie_net),
                            financial_statement="Balance Sheet",
                            line_item_name="Retained Earnings - Interparty Elimination",
                            asset_no=str(_aid),
                        )

            # Recalculate rollforward for Retained Earnings from period 0.
            _all_accounts["Retained Earnings"] = fn_recalculate_account_rollforward(
                account_df=_re_acct,
                account_type="Equity",
                start_period_index=0,
            )

            if _re_ie_acct is not None:
                _all_accounts["Retained Earnings - Interparty Elimination"] = fn_recalculate_account_rollforward(
                    account_df=_re_ie_acct,
                    account_type="Equity",
                    start_period_index=0,
                )

            # Sync Retained Earnings and RE-IE to balance sheet.
            if not _bs_df.empty:
                if "Retained Earnings" in _bs_df.index:
                    for _p_str in _all_period_strs:
                        if _p_str in _bs_df.columns:
                            _bs_df.loc["Retained Earnings", _p_str] = float(
                                _all_accounts["Retained Earnings"].loc["Closing Balance", _p_str]
                            )
                if _re_ie_acct is not None and "Retained Earnings - Interparty Elimination" in _bs_df.index:
                    for _p_str in _all_period_strs:
                        if _p_str in _bs_df.columns:
                            _bs_df.loc["Retained Earnings - Interparty Elimination", _p_str] = float(
                                _all_accounts["Retained Earnings - Interparty Elimination"].loc["Closing Balance", _p_str]
                            )
                _financial_statements["balance_sheet"] = _bs_df
        fn_record_timing(_timing_ctx, "PHASE 9.7: Net Income ? Retained Earnings")


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

        # --- Consolidated Hospitality P&L (sum all assets) ---
        _consolidated_hosp_pl_monthly = pd.DataFrame()
        if _assetco_hospitality_pnl_dfs:
            for _h_idx, _h_df in _assetco_hospitality_pnl_dfs.items():
                if _h_df is None or _h_df.empty:
                    continue
                # Ensure numeric
                _h_numeric = _h_df.apply(pd.to_numeric, errors="coerce").fillna(0.0)
                if _consolidated_hosp_pl_monthly.empty:
                    _consolidated_hosp_pl_monthly = _h_numeric.copy()
                else:
                    # Align columns and index, then add
                    _consolidated_hosp_pl_monthly, _h_numeric = _consolidated_hosp_pl_monthly.align(
                        _h_numeric, fill_value=0.0
                    )
                    _consolidated_hosp_pl_monthly = _consolidated_hosp_pl_monthly + _h_numeric

        _consolidated_hosp_pl_annual = (
            fn_build_annual_dataframe(_consolidated_hosp_pl_monthly)
            if not _consolidated_hosp_pl_monthly.empty
            else pd.DataFrame()
        )
        fn_record_timing(_timing_ctx, "PHASE 10.6B: Build Consolidated Hospitality P&L")

        monthly_dfs = {
            "Cashflow Statement": ("o.consolidated.cfs.me", _cashflow_statement_presentable),
            "Income Statement": ("o.consolidated.is.me", _income_statement_presentable),
            "Balance Sheet": ("o.consolidated.bs.me", _balance_sheet_presentable),
            "Hospitality P&L": ("o.consolidated.hospitality.pl.me", _consolidated_hosp_pl_monthly),
            "Monthly Timeline": ("o.consolidated.model.timeline.me", _monthly_timeline_df),
        }

        annual_dfs = {
            "Hospitality P&L": ("o.consolidated.hospitality.pl.ye", _consolidated_hosp_pl_annual),
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
        if _cash_acct is not None and not _cash_acct.empty and not _cf_monthly.empty:
            _all_periods_check = _cash_acct.columns.tolist()

            # Identify CFO / CFI / CFF line-item rows from the cashflow statement.
            _cfo_items = set()
            _cfi_items = set()
            _cff_items = set()
            for _cat, _items_dict in _consolidated_structure.get("CFO", {}).items():
                _cfo_items.update(_items_dict)
            for _cat, _items_dict in _consolidated_structure.get("CFI", {}).items():
                _cfi_items.update(_items_dict)
            for _cat, _items_dict in _consolidated_structure.get("CFF", {}).items():
                _cff_items.update(_items_dict)

            for _p_str in _all_periods_check:
                if _p_str not in _cf_monthly.columns:
                    continue

                _col_vals = _cf_monthly[_p_str]
                _cfo_total = sum(
                    float(_col_vals.get(_item, 0.0)) if not pd.isna(_col_vals.get(_item, 0.0)) else 0.0
                    for _item in _cfo_items if _item in _col_vals.index
                )
                _cfi_total = sum(
                    float(_col_vals.get(_item, 0.0)) if not pd.isna(_col_vals.get(_item, 0.0)) else 0.0
                    for _item in _cfi_items if _item in _col_vals.index
                )
                _cff_total = sum(
                    float(_col_vals.get(_item, 0.0)) if not pd.isna(_col_vals.get(_item, 0.0)) else 0.0
                    for _item in _cff_items if _item in _col_vals.index
                )

                _opening_cash = float(_cash_acct.loc["Opening Balance", _p_str])
                _expected_closing = _opening_cash + _cfo_total + _cfi_total + _cff_total
                _actual_closing = float(_cash_acct.loc["Closing Balance", _p_str])
                _diff = round(_actual_closing - _expected_closing, 2)

                _cash_check_rows.append({
                    "Period": _p_str,
                    "Opening Cash": round(_opening_cash, 2),
                    "CFO": round(_cfo_total, 2),
                    "CFI": round(_cfi_total, 2),
                    "CFF": round(_cff_total, 2),
                    "Expected Closing": round(_expected_closing, 2),
                    "Actual Closing": round(_actual_closing, 2),
                    "Difference": _diff,
                    "Status": "OK" if abs(_diff) < 0.01 else "MISMATCH",
                })

        _cash_check_df = pd.DataFrame(_cash_check_rows) if _cash_check_rows else pd.DataFrame()

        _cash_ok = _cash_check_df.empty or (_cash_check_df["Status"] == "OK").all()
        print("\n" + "=" * 80)
        print("CASH BALANCE CHECK: " + ("PASS" if _cash_ok else "FAIL"))
        print("=" * 80)
        
        print("=" * 80 + "\n")
        fn_record_timing(_timing_ctx, "PHASE 11.1: Cash Balance Validation")

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

            _bs_periods = _balance_sheet_monthly.columns.tolist()

            for _p_str in _bs_periods:
                if _p_str not in _balance_sheet_monthly.columns:
                    continue

                _total_assets = 0.0
                for _a_name in _asset_accounts:
                    if _a_name in _balance_sheet_monthly.index:
                        _v = _balance_sheet_monthly.loc[_a_name, _p_str]
                        _total_assets += float(_v) if not pd.isna(_v) else 0.0

                _total_liabilities = 0.0
                for _l_name in _liability_accounts:
                    if _l_name in _balance_sheet_monthly.index:
                        _v = _balance_sheet_monthly.loc[_l_name, _p_str]
                        _total_liabilities += float(_v) if not pd.isna(_v) else 0.0

                _total_equity = 0.0
                for _e_name in _equity_accounts:
                    if _e_name in _balance_sheet_monthly.index:
                        _v = _balance_sheet_monthly.loc[_e_name, _p_str]
                        _total_equity += float(_v) if not pd.isna(_v) else 0.0

                _diff_bs = round(_total_assets - (_total_liabilities + _total_equity), 2)

                _bs_check_rows.append({
                    "Period": _p_str,
                    "Total Assets": round(_total_assets, 2),
                    "Total Liabilities": round(_total_liabilities, 2),
                    "Total Equity": round(_total_equity, 2),
                    "L + E": round(_total_liabilities + _total_equity, 2),
                    "Difference": _diff_bs,
                    "Status": "OK" if abs(_diff_bs) < 0.01 else "MISMATCH",
                })

        _bs_check_df = pd.DataFrame(_bs_check_rows) if _bs_check_rows else pd.DataFrame()

        _bs_ok = _bs_check_df.empty or (_bs_check_df["Status"] == "OK").all()
        print("=" * 80)
        print("BALANCE SHEET CHECK: " + ("PASS" if _bs_ok else "FAIL"))
        print("=" * 80)
        
        print("=" * 80 + "\n")
        fn_record_timing(_timing_ctx, "PHASE 11.2: Balance Sheet Validation")

        # ------------------------------------------------------------------
        # CHECK 3: Cash Non-Negativity  (tolerance = 1e-3)
        # ------------------------------------------------------------------
        _cash_neg_tolerance = 1e-3
        _cash_neg_rows: List[Dict[str, Any]] = []

        if _cash_acct is not None and not _cash_acct.empty and not _cf_monthly.empty:
            for _p_str in _cash_acct.columns.tolist():
                _actual_close = float(_cash_acct.loc["Closing Balance", _p_str])

                # Computed closing = Opening + CFO + CFI + CFF
                _open_bal = float(_cash_acct.loc["Opening Balance", _p_str])
                _cfo_v = 0.0
                _cfi_v = 0.0
                _cff_v = 0.0
                if _p_str in _cf_monthly.columns:
                    _col_v = _cf_monthly[_p_str]
                    _cfo_v = sum(
                        float(_col_v.get(_i, 0.0)) if not pd.isna(_col_v.get(_i, 0.0)) else 0.0
                        for _i in _cfo_items if _i in _col_v.index
                    )
                    _cfi_v = sum(
                        float(_col_v.get(_i, 0.0)) if not pd.isna(_col_v.get(_i, 0.0)) else 0.0
                        for _i in _cfi_items if _i in _col_v.index
                    )
                    _cff_v = sum(
                        float(_col_v.get(_i, 0.0)) if not pd.isna(_col_v.get(_i, 0.0)) else 0.0
                        for _i in _cff_items if _i in _col_v.index
                    )
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
        
        fn_record_timing(_timing_ctx, "PHASE 11.3: Cash Non-Negativity Validation")

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
                "DevCo Timeline": fn_json_dict_to_dataframe(_devco_timeline) if _devco_timeline else pd.DataFrame([{"placeholder": "No DevCo timeline"}]),
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
                "AssetCo Timeline DF": _assetco_timeline_df if _assetco_timeline_df is not None and not _assetco_timeline_df.empty else pd.DataFrame([{"placeholder": "No AssetCo timeline DF"}]),
                "Period Ends": pd.DataFrame({"period_end": _period_ends.tolist()}) if isinstance(_period_ends, pd.Series) and not _period_ends.empty else pd.DataFrame([{"placeholder": "No period ends"}]),
            }
            fn_export_dataframes_to_excel(_timeline_export, "debug_timeline", "Timeline")

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
                "AssetCo Col to Period Map": pd.DataFrame([{"col": k, "period": v} for k, v in _assetco_col_to_period.items()]) if _assetco_col_to_period else pd.DataFrame([{"placeholder": "No column to period mapping"}]),
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
        _timing_summary = fn_finalize_timing_summary(_timing_ctx, "PHASE 13: Final Assembly", entity_label="ASSETCO CONSOLIDATION")
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
            _assetco_items_for_uid = payload.get("assetco_consolidated", []) if isinstance(payload, dict) else []
            _assetco_uid_map: Dict[int, str] = {}
            for _uid_idx, _uid_item in enumerate(_assetco_items_for_uid):
                if not isinstance(_uid_item, dict):
                    continue
                _uid_output_json = _uid_item.get("output_json", {})
                if not isinstance(_uid_output_json, dict):
                    _uid_output_json = {}
                _uid_assetco_inputs = _uid_output_json.get("assetco_inputs", {})
                if not isinstance(_uid_assetco_inputs, dict):
                    _uid_assetco_inputs = {}
                _uid_val = _uid_assetco_inputs.get("asset_unique_id")
                if _uid_val is None:
                    continue
                _uid_text = str(_uid_val).strip()
                if not _uid_text or _uid_text.lower() in {"none", "nan", "nat"}:
                    continue
                _assetco_uid_map[_uid_idx] = _uid_text
            _financial_statement_trace_df = fn_add_unique_id_to_trace_df(
                _financial_statement_trace_df,
                _assetco_uid_map,
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