"""
Shared utility functions for LandCo / DevCo / AssetCo consolidation models.

This package extracts identical (or near-identical) functions that were
previously duplicated across project_conso_landco.py, project_conso_devco.py,
and project_conso_assetco.py into a single source of truth.

Sub-modules
-----------
data_utils          - JSON/DataFrame conversion, data extraction helpers
timeline_utils      - Master / monthly / yearly timeline construction
template_utils      - Template row indices, consolidated DF init, interparty mapping
output_utils        - Payload serialisation, annual aggregation, Excel export, debug helpers
timing_utils        - Performance timing context and summary
accounting_engine   - Double-entry accounts, journal entries, financial statements, batch flush
processing_utils    - Cashflow line-item processors, direct-cash capex helpers
statement_presenters - Presentable balance-sheet / income-statement / cashflow builders
"""

# --- data_utils ---------------------------------------------------------------
from .data_utils import (
    _SPLIT_DF_REQUIRED_KEYS,
    fn_json_dict_to_dataframe,
    fn_extract_assumptions_module,
    fn_safe_extract_dataframe,
    fn_extract_assumptions,
    fn_extract_core_sources,
    fn_extract_module_data,
    fn_extract_synthetic_asset_ids_from_mastersheet,
)

# --- timeline_utils -----------------------------------------------------------
from .timeline_utils import (
    fn_build_master_timeline,
    fn_build_monthly_model_timeline,
    fn_build_yearly_model_timeline,
)

# --- template_utils -----------------------------------------------------------
from .template_utils import (
    fn_build_template_row_index,
    fn_initialize_consolidated_dataframe,
    fn_build_financial_statement_row_index,
    fn_build_interparty_mapping,
)

# --- output_utils -------------------------------------------------------------
from .output_utils import (
    fn_dataframe_to_output_payload,
    fn_build_annual_dataframe,
    fn_export_excel_output_to_file,
    fn_debug_value_preview,
    fn_to_debug_dataframe,
    fn_sanitize_excel_sheet_name,
    fn_export_dataframes_to_excel,
    fn_is_debug_export_enabled,
    fn_export_debug_sections,
)

# --- timing_utils -------------------------------------------------------------
from .timing_utils import (
    fn_format_timing_table,
    fn_create_timing_context,
    fn_record_timing,
    fn_finalize_timing_summary,
)

# --- accounting_engine --------------------------------------------------------
from .accounting_engine import (
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
    fn_flush_matrix_entries_multi,
    fn_allocate_entry_array,
    fn_trim_entry_array,
    _ENTRY_DTYPE,
    fn_propagate_opening_balances,
    fn_get_account_balance,
)

# --- processing_utils ---------------------------------------------------------
from .processing_utils import (
    fn_build_structured_entries_from_source,
    fn_build_matrix_entries_from_source,
    fn_process_cashflow_line_item,
    fn_build_direct_cash_batch_entries,
    fn_build_direct_cash_matrix_entries,
    fn_prepare_direct_cash_matrix_batch,
    fn_process_direct_cash_capex_line_item_entries,
    fn_get_row_by_compatible_index,
)

# --- financial_statement_trace_utils -----------------------------------------
from .financial_statement_trace_utils import (
    FS_TRACE_ROWS_KEY,
    FS_TRACE_COLUMNS,
    fn_initialize_financial_statement_trace,
    fn_append_financial_statement_trace_row,
    fn_extract_asset_no_from_entry,
    fn_record_batch_entry_financial_statement_trace,
    fn_record_matrix_entries_financial_statement_trace,
    fn_build_financial_statement_trace_dataframe,
    fn_finalize_financial_statement_trace_dataframe,
    fn_trace_dataframe_to_payload,
    fn_trace_payload_to_dataframe,
    fn_concatenate_financial_statement_trace_dataframes,
    fn_build_consolidated_financial_statement_trace_delta,
    fn_add_unique_id_to_trace_df,
)

# --- statement_presenters -----------------------------------------------------
from .statement_presenters import (
    fn_build_presentable_balance_sheet,
    fn_build_presentable_income_statement,
    fn_build_presentable_cashflow_statement,
)
