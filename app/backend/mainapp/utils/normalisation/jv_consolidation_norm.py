import traceback
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import os

from mainapp.utils.v3.jv_functions.jv_utils import (
    fn_read_all_named_ranges_json,
    _read_scalar,
    _read_array,
    fn_initialize_global_class,
    fn_initialize_asset_class,
    _normalize_assetco_entries,
    _safe_str_lower,
    _get_asset_names_from_classes,
    _get_raw_asset_names_from_classes,
    _get_asset_names_from_payload,
    _resolve_selection,
)
from mainapp.utils.v3.jv_functions.jv_fcff_utils import (
    _extract_asset_fcff,
    _accumulate_fcff_rows,
    _date_to_month_index,
    _apply_jv_window,
    _extract_asset_sales,
    _extract_asset_acquisition,
    _find_asset_index,
    _extract_land_in_kind_from_section,
)
from mainapp.utils.v3.jv_functions.jv_cff_utils import (
    _to_float,
    _zeros,
    _pad,
    _row_add,
    _row_negate,
    _read_interest_rate_profiles,
    _get_monthly_rate,
    _resolve_vehicle_jv_inputs,
    _compute_term_loan,
    _compute_cff,
)
from mainapp.utils.v3.consolidation.project_conso_utils.timing_utils import (
    fn_create_timing_context,
    fn_record_timing,
    fn_finalize_timing_summary,
)
from mainapp.utils.v3.consolidation.project_conso_utils.financial_metric_util import (
    _irr,
    _npv,
    _xirr,
    _mirr,
)
from mainapp.utils.v3.jv_functions.jv_output_utils import (
    build_consolidated_output,
    _sanitize_data,
)


# =====================================================================
# Export helpers (same pattern as consolidated_model.py)
# =====================================================================

def _sanitize_sheet_name(name: str) -> str:
    """Truncate and strip invalid Excel sheet-name characters."""
    for ch in ("\\", "/", "*", "?", ":", "[", "]"):
        name = name.replace(ch, "-")
    return name[:31]


def fn_is_export_enabled(export_flags: Dict[str, bool], section_name: str) -> bool:
    """Return True if export is enabled for *section_name* (or ``all_sections``)."""
    return bool(export_flags.get("all_sections", False) or export_flags.get(section_name, False))


def fn_export_dataframes_to_excel(
    dataframes_dict: Dict[str, Any],
    filename: str,
    description: str,
) -> Optional[str]:
    """
    Export a dictionary of DataFrames / payloads to an Excel file.

    Values may be ``pd.DataFrame`` instances or ``{index, columns, data}``
    payload dicts — both are handled.
    """
    if not dataframes_dict:
        return None

    try:
        base_dir = os.path.dirname(__file__)
        output_name = filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx"
        excel_path = os.path.join(base_dir, output_name)
        used: set = set()

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for raw_name, raw_value in dataframes_dict.items():
                sheet = _sanitize_sheet_name(raw_name)
                candidate = sheet
                dup = 1
                while candidate.lower() in used:
                    suffix = f"_{dup}"
                    candidate = f"{sheet[: 31 - len(suffix)]}{suffix}"
                    dup += 1
                used.add(candidate.lower())

                if isinstance(raw_value, pd.DataFrame):
                    df = raw_value
                elif isinstance(raw_value, dict) and "data" in raw_value:
                    df = pd.DataFrame(
                        data=raw_value["data"],
                        index=raw_value.get("index"),
                        columns=raw_value.get("columns"),
                    )
                else:
                    df = pd.DataFrame([{"value": str(raw_value)}])

                df.to_excel(writer, sheet_name=candidate, index=True)

        if hasattr(os, "startfile"):
            os.startfile(excel_path)
        return excel_path
    except Exception as exc:
        return None


def fn_export_jv_consolidated_output(
    excel_output: Dict[str, Any],
    filename: str = "jv_consolidated_output.xlsx",
) -> None:
    """
    Export the JV consolidated ``excel_output`` dict to a single Excel tab
    per frequency (Monthly / Annual).  Sections are separated by an empty
    row and prefixed with a bold section-header row for readability.
    """
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    base_dir = os.path.dirname(__file__)
    filepath = os.path.join(base_dir, filename)

    # Styling constants
    header_font = Font(bold=True, size=11)
    section_font = Font(bold=True, size=12, color="FFFFFF")
    section_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    col_header_font = Font(bold=True, size=10)
    col_header_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    thin_border = Border(
        bottom=Side(style="thin", color="B0B0B0"),
    )
    num_fmt = '#,##0;(#,##0);"-"'

    def _write_all_sections(ws, sections_dict):
        """Write all sections onto *ws*, returning nothing."""
        # Layout: col A empty, B=Line Item, C=Total, D=empty separator, E+=periods
        # Row 1 empty, Row 2 = timeline header (written once), data from row 3
        label_col = 2       # B
        total_col = 3       # C
        sep_col = 4         # D (empty)
        data_start_col = 5  # E onwards

        # Determine n_data_cols from first section for the timeline header
        first_entry = next(iter(sections_dict.values()), None)
        all_col_vals = first_entry[1].get("columns", []) if first_entry else []
        n_data_cols = len(all_col_vals)

        # Row 1: empty (left blank)
        # Row 2: timeline period headers
        ws.cell(row=2, column=label_col, value="Line Item").font = col_header_font
        ws.cell(row=2, column=label_col).fill = col_header_fill
        ws.cell(row=2, column=total_col, value="Total").font = col_header_font
        ws.cell(row=2, column=total_col).fill = col_header_fill
        ws.cell(row=2, column=total_col).alignment = Alignment(horizontal="center")
        ws.cell(row=2, column=sep_col).fill = col_header_fill  # empty separator
        for ci, cv in enumerate(all_col_vals):
            cell = ws.cell(row=2, column=data_start_col + ci, value=cv)
            cell.font = col_header_font
            cell.fill = col_header_fill
            cell.alignment = Alignment(horizontal="center")

        current_row = 3  # data starts here

        for section_name, (code, df_json) in sections_dict.items():
            index_vals = df_json.get("index", [])
            col_vals = df_json.get("columns", [])
            data_rows = df_json.get("data", [])
            n_data_cols = len(col_vals)

            # --- Section header row (coloured) ---
            for c in range(1, data_start_col + n_data_cols):
                cell = ws.cell(row=current_row, column=c)
                cell.fill = section_fill
                cell.font = section_font
            ws.cell(row=current_row, column=label_col, value=section_name).font = section_font
            ws.cell(row=current_row, column=label_col).fill = section_fill
            current_row += 1

            # --- Data rows ---
            for ri, row_data in enumerate(data_rows):
                label = index_vals[ri] if ri < len(index_vals) else ""
                ws.cell(row=current_row, column=label_col, value=label).font = header_font

                # Total column
                row_total = sum(v for v in row_data if isinstance(v, (int, float)))
                total_cell = ws.cell(row=current_row, column=total_col, value=row_total)
                total_cell.number_format = num_fmt
                total_cell.alignment = Alignment(horizontal="right")
                total_cell.font = Font(bold=True, size=10)

                # Column D stays empty (separator)

                for ci, val in enumerate(row_data):
                    cell = ws.cell(row=current_row, column=data_start_col + ci, value=val)
                    if isinstance(val, (int, float)):
                        cell.number_format = num_fmt
                        cell.alignment = Alignment(horizontal="right")
                current_row += 1

            # --- Empty separator row ---
            current_row += 1

        # Column widths
        ws.column_dimensions["A"].width = 3    # Empty first column
        max_len = 12
        for row_cells in ws.iter_rows(min_col=label_col, max_col=label_col, max_row=current_row):
            for cell in row_cells:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(label_col)].width = min(max_len + 4, 50)
        ws.column_dimensions[get_column_letter(total_col)].width = 16
        ws.column_dimensions[get_column_letter(sep_col)].width = 3

        # Reasonable width for data columns
        _final_n = n_data_cols or len(all_col_vals) or 12
        for ci in range(data_start_col, data_start_col + _final_n):
            ws.column_dimensions[get_column_letter(ci)].width = 14

    try:
        from openpyxl import Workbook
        wb = Workbook()

        # Monthly tab
        ws_m = wb.active
        ws_m.title = "Monthly"
        monthly_dfs = excel_output.get("monthly_dfs", {})
        if monthly_dfs:
            _write_all_sections(ws_m, monthly_dfs)
        ws_m.sheet_view.showGridLines = False
        ws_m.freeze_panes = "E3"

        # Annual tab
        annual_dfs = excel_output.get("annual_dfs", {})
        if annual_dfs:
            ws_a = wb.create_sheet(title="Annual")
            _write_all_sections(ws_a, annual_dfs)
            ws_a.sheet_view.showGridLines = False
            ws_a.freeze_panes = "E3"

        # Distribution Waterfall is now merged into the Monthly/Annual tabs

        wb.save(filepath)
        if hasattr(os, "startfile"):
            os.startfile(filepath)
    except Exception as exc:
        pass


def fn_export_loan_schedules(
    loan_schedule_sheets: Dict[str, dict],
    filename: str = "jv_loan_schedules.xlsx",
) -> None:
    """Export loan schedule worksheets (TL1 + Refi) to Excel."""
    if not loan_schedule_sheets:
        return

    base_dir = os.path.dirname(__file__)
    filepath = os.path.join(base_dir, filename)

    try:
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            for key, sched in loan_schedule_sheets.items():
                sheet_name = _sanitize_sheet_name(sched.get("sheet_name", key))
                headers = sched.get("headers", {})
                rows = sched.get("rows", [])

                # Build DataFrame: headers as first rows, then schedule rows
                all_labels: List[str] = list(headers.keys()) + [r[0] for r in rows]
                all_data: List[list] = list(headers.values()) + [r[1] for r in rows]

                df = pd.DataFrame(all_data, index=all_labels)
                df.to_excel(writer, sheet_name=sheet_name)

        if hasattr(os, "startfile"):
            os.startfile(filepath)
    except Exception as exc:
        pass


# =====================================================================
# Constants  Named Range Keys
# =====================================================================

# Master Sheet (shared across all modules)
MS_GLOBAL_CLASS     = "m.jv.global.class"
MS_GLOBAL_ATTRIBUTE = "m.jv.global.attribute"
MS_GLOBAL_VALUE     = "m.jv.global.value"
MS_CLASS_ROW        = "m.mastersheet.inputs.class.row"
MS_ATTRIBUTES_ROW   = "m.mastersheet.attributes.row"
MS_UNITS_DATA       = "m.mastersheet.unit.data"

# JV Inputs
JV_GLOBAL_CLASS      = "j.jv.global.class"
JV_GLOBAL_ATTRIBUTE  = "j.jv.global.attribute"
JV_GLOBAL_VALUE      = "j.jv.global.value"
JV_CLASS_ROW         = "j.jv.inputs.class.row"
JV_ATTRIBUTES_ROW    = "j.jv.attributes.row"
JV_UNITS_DATA        = "j.jv.units.data"
JV_INTEREST_PROFILES = "j.jv.interest.rate.profiles"
DD_INTEREST_PROFILES = "dd.jv.interest.rate.profiles"
JV_INTEREST_VALUES   = "j.jv.interest.rate.values"
JV_NUM_ITERATIONS    = "j.jv.no.of.iterations"

# JV Output (paste targets)
OUT_FCFF_NAMES        = "o.jv.fcff.names"
OUT_FCFF_YE           = "o.jv.fcff.ye"
OUT_FCFF_ME           = "o.jv.fcff.me"
OUT_TIMELINE_YE       = "o.jv.model.timeline.ye"
OUT_TIMELINE_ME       = "o.jv.model.timeline.me"
OUT_SELECTED_VEHICLE  = "o.jv.selected.vehicle.type"
OUT_SELECTED_SCENARIO = "o.jv.selected.scenario"

# First JV cashflow output section (entity FCFF + Land In Kind)
OUT_CASHFLOWS_NAMES   = "o.jv.cashflows.names"
OUT_CASHFLOWS_ME      = "o.jv.cashflows.me"
OUT_CASHFLOWS_YE      = "o.jv.cashflows.ye"

# Project Cost output section (yearly + monthly)
OUT_PROJECT_COST_NAMES = "o.jv.project.cost.names"
OUT_PROJECT_COST_ME    = "o.jv.project.cost.me"
OUT_PROJECT_COST_YE    = "o.jv.project.cost.ye"

# Fees output section
OUT_FEES_NAMES = "o.jv.fees.names"
OUT_FEES_ME    = "o.jv.fees.me"
OUT_FEES_YE    = "o.jv.fees.ye"

# Asset Sales Value output section (separate from fees)
OUT_ASSET_SALES_VALUES = "o.jv.assetsale.values"
OUT_ASSET_SALES_ME     = "o.jv.assetsales.me"
OUT_ASSET_SALES_YE     = "o.jv.assetsales.ye"

# Total Funding Required output section
OUT_TOTAL_FUNDING_NAMES = "o.jv.total.funding.names"
OUT_TOTAL_FUNDING_ME    = "o.jv.total.funding.me"
OUT_TOTAL_FUNDING_YE    = "o.jv.total.funding.ye"

OUT_TL1_NAMES           = "o.jv.termloan1.names"
OUT_TL1_ME              = "o.jv.termloan1.me"
OUT_TL1_YE              = "o.jv.termloan1.ye"

OUT_REFI_NAMES          = "o.jv.refinancing.names"
OUT_REFI_ME             = "o.jv.refinancing.me"
OUT_REFI_YE             = "o.jv.refinancing.ye"

# Detailed TL1 schedule (15-row debt movement schedule)
OUT_TL1_SCHED_NAMES     = "o.jv.termloan1schedule.names"
OUT_TL1_SCHED_ME        = "o.jv.termloan1schedule.me"
OUT_TL1_SCHED_YE        = "o.jv.termloan1schedule.ye"

# Detailed Refinancing schedule (15-row debt movement schedule)
OUT_REFI_SCHED_NAMES    = "o.jv.refinanceschedule.names"
OUT_REFI_SCHED_ME       = "o.jv.refinanceschedule.me"
OUT_REFI_SCHED_YE       = "o.jv.refinanceschedule.ye"

# Refinancing Min DSCR assumption (separate output family)
OUT_REFI_MINDSCR_NAMES  = "o.jv.refinancingloan.mindscr.name"
OUT_REFI_MINDSCR_ME     = "o.jv.refinancingloan.mindscr.me"
OUT_REFI_MINDSCR_YE     = "o.jv.refinancingloan.mindscr.ye"

OUT_EQUITY_SCHED_NAMES  = "o.jv.equity.schedule.names"
OUT_EQUITY_SCHED_ME     = "o.jv.equity.schedule.me"
OUT_EQUITY_SCHED_YE     = "o.jv.equity.schedule.ye"

OUT_ADDL_EQUITY_REQ_NAMES = "o.jv.additional.equity.names"
OUT_ADDL_EQUITY_REQ_ME    = "o.jv.additional.equity.me"
OUT_ADDL_EQUITY_REQ_YE    = "o.jv.additional.equity.ye"

OUT_ADDL_EQUITY_COMMIT_NAMES = "o.jv.additional.equity.drawn.names"
OUT_ADDL_EQUITY_COMMIT_ME    = "o.jv.additional.equity.drawn.me"
OUT_ADDL_EQUITY_COMMIT_YE    = "o.jv.additional.equity.drawn.ye"

OUT_LIK_COMMIT_NAMES    = "o.jv.landinkind.comittment.names"
OUT_LIK_COMMIT_ME       = "o.jv.landinkind.comittment.me"
OUT_LIK_COMMIT_YE       = "o.jv.landinkind.comittment.ye"

OUT_TOTAL_COMMIT_NAMES  = "o.jv.total.commitment.names"
OUT_TOTAL_COMMIT_ME     = "o.jv.total.commitment.me"
OUT_TOTAL_COMMIT_YE     = "o.jv.total.commitment.ye"

OUT_CASH_DIST_NAMES     = "o.jv.cash.distribution.names"
OUT_CASH_DIST_ME        = "o.jv.cash.distribution.me"
OUT_CASH_DIST_YE        = "o.jv.cash.distribution.ye"

OUT_PREF_RETURNS_NAMES  = "o.jv.preferred.returns.names"
OUT_PREF_RETURNS_ME     = "o.jv.preferred.returns.me"
OUT_PREF_RETURNS_YE     = "o.jv.preferred.returns.ye"

OUT_GP_CATCHUP_NAMES    = "o.jv.preferred.returns.gpcatchup.names"
OUT_GP_CATCHUP_ME       = "o.jv.preferred.returns.gpcatchup.me"
OUT_GP_CATCHUP_YE       = "o.jv.preferred.returns.gpcatchup.ye"

OUT_TIER1_LP_NAMES      = "o.jv.tier1.lpdistributions.names"
OUT_TIER1_LP_ME         = "o.jv.tier1.lpdistributions.me"
OUT_TIER1_LP_YE         = "o.jv.tier1.lpdistributions.ye"

OUT_TIER1_GP_CU_NAMES   = "o.jv.tier1.gp.catchup.names"
OUT_TIER1_GP_CU_ME      = "o.jv.tier1.gp.catchup.me"
OUT_TIER1_GP_CU_YE      = "o.jv.tier1.gp.catchup.ye"

OUT_TIER2_LP_NAMES      = "o.jv.tier2.lpdistributions.names"
OUT_TIER2_LP_ME         = "o.jv.tier2.lpdistributions.me"
OUT_TIER2_LP_YE         = "o.jv.tier2.lpdistributions.ye"

OUT_TIER2_GP_CU_NAMES   = "o.jv.tier2.gp.catchup.names"
OUT_TIER2_GP_CU_ME      = "o.jv.tier2.gp.catchup.me"
OUT_TIER2_GP_CU_YE      = "o.jv.tier2.gp.catchup.ye"

OUT_TIER3_NAMES         = "o.jv.tier3.names"
OUT_TIER3_ME            = "o.jv.tier3.me"
OUT_TIER3_YE            = "o.jv.tier3.ye"

OUT_DETAILED_CALC_ME    = "o.jv.detailed.calculations.me"

# Prefix groups for filtering named ranges
_PREFIXES_MS  = ["m.mastersheet", "m.jv"]
_PREFIXES_JV  = ["j.jv", "dd.jv"]
_PREFIXES_OUT = ["o.jv"]

# CFS sections consumed from upstream payloads
_CFS_SECTIONS  = ("Cashflow from Operations", "Cashflow from Investments", "Cashflow from Financing")
_MODULE_LABELS = ("LandCo", "DevCo", "AssetCo")

# Mapping: Python class name -> Excel class name (for Master Sheet Asset classes)
MS_CLASS_NAME_MAP = {
    "JVModule": "JVInputsModule",
}

# Mapping: Python class name -> Excel class name (for hyphenated names)
JV_CLASS_NAME_MAP = {
    "FinancingAssumptions_Loan1": "FinancingAssumptions-Loan1",
}


# =====================================================================
# CLASS 1: MasterSheet  All Master Sheet data
# =====================================================================

class MasterSheet:

    class Global:
        class ProjectInputs:
            project_name = None
            project_start_date = None
            project_id = None
            location = None
            current_sg = None
            approval_date = None
            committee_approval = None
            number_of_assets = None
            title_deed_area = None
            masterplan_efficiency = None
            total_developable_area = None
            masterplan_far = None

        class ModelAssumptions:
            model_start_date = None
            model_duration = None
            model_end_date = None
            default_date = None

        class FiltrationDropdowns:
            asset_id = None
            asset_name = None

        class ValuationAssumptions:
            npv_calculation_start_option = None
            npv_calculation_start_date_override = None
            npv_calculation_start_date = None
            discount_rate = None
            mirr_finance_rate = None
            mirr_reinvestment_rate = None
            irr_calculation_option = None

    class Asset:
        class ProjectDetails:
            sno = None
            number = None
            project_name = None
            region = None
            city = None
            asset_class = None
            sub_category = None
            typology = None
            construction_phase = None
            asset_name = None
            asset_unique_identifier = None
            asset_jv_inclusion = None
            jv_output_inclusion = None

        class AssetLifecycleModule:
            land_development = None
            vertical_development = None
            asset_operations = None

        class JVModule:
            jvjda_inclusion = None
            venture_type = None
            jv_name = None
            landco_inclusion = None
            devco_inclusion = None
            assetco_inclusion = None


# =====================================================================
# CLASS 2: JVInputs  All JV Inputs sheet data
# =====================================================================

class JVInputs:

    class Global:

        class SPVInputs:
            sno = None
            vehicle_type = None
            scenario_name = None

        class RoleAllocation:
            gp = None
            lp = None

        class JVDates:
            start_date_based_on_the_earliest_project_acquisition = None
            fund_tenure_in_months = None
            end_date_based_on_the_last_exit_of_the_assets = None

        class CapitalStructure:
            land_acquisition_cost = None
            capex = None
            total_capex = None
            debt_ = None
            equity = None

        class InKindEquity:
            land_in__kind = None
            land_owner = None
            land_in_kind_gp = None
            land_in_kind_lp = None
            land_in_kind_gp_sar = None
            gp_contribution = None
            lp_contribution = None

        class CashEquity:
            gp_contribution = None
            lp_contribution_others = None
            gp_contribution_ = None
            lp_contribution_ = None
            gp_contribution_cash = None
            lp_contribution_cash = None

        class ComputedOwnership:
            gp_owernship = None
            lp_ownership_others = None

        class UserDefinedOwnership:
            ownership_over_ride = None
            gp_ownership = None
            gp_ownership_input = None
            lp_ownership_others = None
            lp_ownership_input = None

        class FeesDefinition:
            jv_setup_structuring__acquisition_fees = None
            jv_liquidation__exit_related_fees = None
            other_fees = None
            fund_management_exp = None

        class FeesAllocation:
            jv_setup_structuring__acquisition_fees = None
            jv_liquidation__exit_related_fees = None
            other_fees = None
            fund_management_exp = None

        class PreferredReturnsandCatchup:
            distribution_frequency = None
            preferred_return_type = None
            preferred_return = None
            gp_cashflow_duringpreferred_return = None
            gp_promote_ = None
            gp_promote_post_preferred = None
            catchup_enabled = None
            catch_up_ = None
            gp_cashflows_during_catch_up = None
            lp_cashflows_during_catch_up = None

        class Tier1:
            irr_ = None
            t1_irr_ = None
            irr__tier_1 = None
            lp_share = None
            lp_share___tier_1 = None
            gp_promote = None
            gp_promote___tier_1 = None

        class Tier2:
            irr_ = None
            t2_irr_ = None
            irr__tier_2 = None
            lp_share = None
            lp_share___tier_2 = None
            gp_promote = None
            gp_promote___tier_2 = None
            lp_share___tier_3 = None
            gp_share___tier_3 = None
            gp_promote___tier_3 = None

        class Tier3:
            lp_share___tier_3 = None
            gp_promote___tier_3 = None

        class FinancingAssumptions_Loan1:
            start_date = None
            start_date_tl1 = None
            start_date_refinancing = None
            tenure = None
            tenure_tl1 = None
            tenure__refinancing = None
            loan_end_date = None
            loan_end_datetl1 = None
            loan_end_date_refinancing = None
            repayment_start_date = None
            repayment_start_date_tl1 = None
            amortization_duration = None
            amortization_durationtl1 = None
            annual_amortization = None
            annual_amortizationtl1 = None
            balloon_payment = None
            balloon_paymenttl1 = None
            interest_capitalization_ = None
            interest_rate_profile = None
            interest_rate_profile_tl1 = None
            arrangement_fees = None
            arrangement_fees_tl1 = None
            arrangement_fees_capitalization = None
            arrangement_fees_capitalization_ = None
            arrangement_fees_capitalization_tl1 = None
            commitment_fees = None
            refinacning = None
            amortizationrefinancing = None
            annual_amortizationrefinancing = None
            balloon_payment_refinancing = None
            interest_rate_profile___refinancing = None
            arrangement_feesrefinancing = None
            min_dscrrefinancing = None

        class RefinancingAssumptions:
            start_date = None
            start_date_refinancing = None
            tenure = None
            tenure__refinancing = None
            ltv = None
            loan_end_date = None
            loan_end_date_refinancing = None
            amortization_duration = None
            amortizationrefinancing = None
            annual_amortization = None
            annual_amortizationrefinancing = None
            balloon_payment = None
            balloon_payment_refinancing = None
            interest_rate_profile = None
            interest_rate_profile___refinancing = None
            arrangement_fees = None
            arrangement_feesrefinancing = None
            commitment_fees = None
            min_dscr = None
            min_dscrrefinancing = None

        class IterationSettings:
            no_of_iterations = None

    class Asset:
        """Per-asset data from j.jv.{inputs.class.row,attributes.row,units.data}.
        Each attribute is a list (one value per asset row)."""

        class SPVInputs:
            sno = None
            vehicle_type = None
            scenario_name = None

        class RoleAllocation:
            gp = None
            lp = None

        class JVDates:
            start_date_based_on_the_earliest_project_acquisition = None
            fund_tenure_in_months = None
            end_date_based_on_the_last_exit_of_the_assets = None

        class CapitalStructure:
            land_acquisition_cost = None
            capex = None
            total_capex = None
            debt_ = None
            equity = None
        class InKindEquity:
            land_in__kind = None
            land_in__kind_overrirde = None
            land_owner = None
            land_in_kind_gp = None
            land_in_kind_lp = None
            land_in_kind_gp_sar = None
            gp_contribution = None
            lp_contribution = None

        class CashEquity:
            gp_contribution = None
            lp_contribution_others = None
            gp_contribution_ = None
            lp_contribution_ = None
            gp_contribution_cash = None
            lp_contribution_cash = None

        class ComputedOwnership:
            gp_owernship = None
            lp_ownership_others = None

        class UserDefinedOwnership:
            ownership_over_ride = None
            gp_ownership = None
            gp_ownership_input = None
            lp_ownership_others = None
            lp_ownership_input = None

        class FeesDefinition:
            jv_setup_structuring__acquisition_fees = None
            jv_liquidation__exit_related_fees = None
            other_fees = None
            fund_management_exp = None

        class FeesAllocation:
            jv_setup_structuring__acquisition_fees = None
            jv_liquidation__exit_related_fees = None
            other_fees = None
            fund_management_exp = None

        class PreferredReturnsandCatchup:
            distribution_frequency = None
            preferred_return_type = None
            preferred_return = None
            gp_cashflow_duringpreferred_return = None
            gp_promote_ = None
            gp_promote_post_preferred = None
            catchup_enabled = None
            catch_up_ = None
            gp_cashflows_during_catch_up = None
            lp_cashflows_during_catch_up = None

        class Tier1:
            irr_ = None
            t1_irr_ = None
            irr__tier_1 = None
            lp_share = None
            lp_share___tier_1 = None
            gp_promote = None
            gp_promote___tier_1 = None

        class Tier2:
            irr_ = None
            t2_irr_ = None
            irr__tier_2 = None
            lp_share = None
            lp_share___tier_2 = None
            gp_promote = None
            gp_promote___tier_2 = None
            lp_share___tier_3 = None
            gp_share___tier_3 = None
            gp_promote___tier_3 = None

        class Tier3:
            lp_share___tier_3 = None
            gp_promote___tier_3 = None

        class FinancingAssumptions_Loan1:
            start_date = None
            start_date_tl1 = None
            start_date_refinancing = None
            tenure = None
            tenure_tl1 = None
            tenure__refinancing = None
            loan_end_date = None
            loan_end_datetl1 = None
            loan_end_date_refinancing = None
            repayment_start_date = None
            repayment_start_date_tl1 = None
            amortization_duration = None
            amortization_durationtl1 = None
            annual_amortization = None
            annual_amortizationtl1 = None
            balloon_payment = None
            balloon_paymenttl1 = None
            interest_capitalization_ = None
            interest_rate_profile = None
            interest_rate_profile_tl1 = None
            arrangement_fees = None
            arrangement_fees_tl1 = None
            arrangement_fees_capitalization = None
            arrangement_fees_capitalization_ = None
            arrangement_fees_capitalization_tl1 = None
            commitment_fees = None
            refinacning = None
            amortizationrefinancing = None
            annual_amortizationrefinancing = None
            balloon_payment_refinancing = None
            interest_rate_profile___refinancing = None
            arrangement_feesrefinancing = None
            min_dscrrefinancing = None

        class RefinancingAssumptions:
            start_date = None
            start_date_refinancing = None
            tenure = None
            tenure__refinancing = None
            ltv = None
            loan_end_date = None
            loan_end_date_refinancing = None
            amortization_duration = None
            amortizationrefinancing = None
            annual_amortization = None
            annual_amortizationrefinancing = None
            balloon_payment = None
            balloon_payment_refinancing = None
            interest_rate_profile = None
            interest_rate_profile___refinancing = None
            arrangement_fees = None
            arrangement_feesrefinancing = None
            commitment_fees = None
            min_dscr = None
            min_dscrrefinancing = None


# =====================================================================
# Main Consolidation
# =====================================================================

def wrapper_for_vars(payload: Any) -> Any:
    try:
        excel_output = None
        _timing_ctx = fn_create_timing_context()

        # ================================================================
        # Export Flags Configuration
        # ================================================================
        _EXPORT_FLAGS: Dict[str, bool] = {
            "all_sections": False,
            "consolidated_output": False,
            "loan_schedules": False,
            "vehicle_cff": False,
            "vehicle_returns": False,
        }

        # ================================================================
        # PHASE 0: Initialization
        # ================================================================
        fn_record_timing(_timing_ctx, "PHASE 0: Initialization")

        # ----------------------------------------------------------------
        # PHASE 1: Read named ranges
        # ----------------------------------------------------------------
        namedranges = payload.get("namedranges") or []

        ms_df  = fn_read_all_named_ranges_json(namedranges, _PREFIXES_MS)
        jv_df  = fn_read_all_named_ranges_json(namedranges, _PREFIXES_JV)
        out_df = fn_read_all_named_ranges_json(namedranges, _PREFIXES_OUT)

        fn_record_timing(_timing_ctx, "PHASE 1: Read Named Ranges")

        # ----------------------------------------------------------------
        # PHASE 2: Initialize classes via setattr (LandCo/DevCo pattern)
        # ----------------------------------------------------------------

        # 2a. MasterSheet.Global <- ProjectInputs, ModelAssumptions, etc.
        if not ms_df.empty:
            fn_initialize_global_class(
                ms_df, MasterSheet.Global,
                MS_GLOBAL_CLASS, MS_GLOBAL_ATTRIBUTE, MS_GLOBAL_VALUE,
            )

        # 2b. MasterSheet.Asset <- ProjectDetails, JVModule
        if not ms_df.empty:
            fn_initialize_asset_class(
                ms_df, MasterSheet.Asset,
                MS_CLASS_ROW, MS_ATTRIBUTES_ROW, MS_UNITS_DATA,
                inclusion_attr="__no_filter__",
                class_name_map=MS_CLASS_NAME_MAP,
            )

        # 2c. JVInputs.Global <- SPVInputs, RoleAllocation, JVDates, etc.
        if not jv_df.empty:
            fn_initialize_global_class(
                jv_df, JVInputs.Global,
                JV_GLOBAL_CLASS, JV_GLOBAL_ATTRIBUTE, JV_GLOBAL_VALUE,
                class_name_map=JV_CLASS_NAME_MAP,
            )

        # 2d. JVInputs.Asset <- per-asset SPVInputs, CapitalStructure, etc.
        if not jv_df.empty:
            fn_initialize_asset_class(
                jv_df, JVInputs.Asset,
                JV_CLASS_ROW, JV_ATTRIBUTES_ROW, JV_UNITS_DATA,
                inclusion_attr="__no_filter__",
                class_name_map=JV_CLASS_NAME_MAP,
            )
            

        # 2e. Read no. of iterations (standalone scalar named range)
        no_of_iterations_raw = _read_scalar(jv_df, JV_NUM_ITERATIONS, default=1)
        no_of_iterations = int(float(no_of_iterations_raw)) if no_of_iterations_raw else 1
        if no_of_iterations < 1:
            no_of_iterations = 1

        fn_record_timing(_timing_ctx, "PHASE 2: Initialize Classes")

        # ----------------------------------------------------------------
        # PHASE 3: Unpack upstream payloads
        # ----------------------------------------------------------------
        landco_devco = payload.get("landco_devco") or {}

        landco_data = landco_devco.get("landco", {})
        devco_data  = landco_devco.get("devco", {})

        # AssetCo per-asset data
        raw_ac_list = []
        assetco_per_asset_direct = payload.get("assetco_per_asset")
        if isinstance(assetco_per_asset_direct, list) and assetco_per_asset_direct:
            raw_ac_list = assetco_per_asset_direct
        else:
            assetco_raw = payload.get("assetco") or payload.get("assetco_consolidation")
            if isinstance(assetco_raw, dict):
                raw_ac_list = assetco_raw.get("per_asset", [])
            elif isinstance(assetco_raw, list):
                raw_ac_list = assetco_raw

        assetco_per_asset = _normalize_assetco_entries(raw_ac_list)

        fn_record_timing(_timing_ctx, "PHASE 3: Unpack Upstream Payloads")

        # ----------------------------------------------------------------
        # PHASE 4: Resolve selection (vehicle type / scenario -> assets / modules)
        # ----------------------------------------------------------------
        raw_asset_names = _get_raw_asset_names_from_classes(MasterSheet)
        all_asset_names = _get_asset_names_from_classes(MasterSheet)

        if not all_asset_names:
            all_asset_names = _get_asset_names_from_payload(landco_data, devco_data)
            raw_asset_names = [n for n in all_asset_names]

        # Merge AssetCo asset names not already in list
        existing_lower = {n.strip().lower() for n in all_asset_names}
        for entry in assetco_per_asset:
            name = str(entry.get("asset_name") or "").strip()
            if name and name.lower() not in existing_lower:
                all_asset_names.append(name)
                existing_lower.add(name.lower())

        selection = _resolve_selection(
            out_df, all_asset_names, raw_asset_names,
            MasterSheet, OUT_SELECTED_VEHICLE, OUT_SELECTED_SCENARIO,
        )

        selected_vehicle_type = selection["selected_vehicle_type"]
        selected_scenario     = selection["selected_scenario"]
        selected_assets       = selection["selected_assets"]
        module_flags          = selection["module_flags"]
        lifecycle_flags       = selection["lifecycle_flags"]
        jv_groups             = selection["jv_groups"]
        all_jv_groups         = selection["all_jv_groups"]
        venture_types         = selection["venture_types"]

        fn_record_timing(_timing_ctx, "PHASE 4: Resolve Selection")

        # ----------------------------------------------------------------
        # PHASE 5: Build per-asset FCFF DataFrames (one DF per module)
        # ----------------------------------------------------------------
        # Extract FCFF arrays (numpy) per asset.
        # all_selected_assets covers every JV-included asset across all scenarios
        # so that non-selected scenarios have real FCFF in the consolidation output.
        _all_jv_asset_set = {
            a for assets in all_jv_groups.values() for a in assets
        }
        all_selected_assets = list(dict.fromkeys(
            list(selected_assets) +
            [a for a in _all_jv_asset_set if a not in selected_assets]
        ))

        max_periods = 0
        per_asset_fcff_raw: Dict[str, Dict[str, np.ndarray]] = {}

        for asset_name in all_selected_assets:
            asset_fcff = _extract_asset_fcff(
                asset_name,
                landco_data,
                devco_data,
                assetco_per_asset,
                module_flags,
                lifecycle_flags=lifecycle_flags.get(asset_name),
            )
            per_asset_fcff_raw[asset_name] = asset_fcff
            for arr in asset_fcff.values():
                if isinstance(arr, np.ndarray) and arr.size > max_periods:
                    max_periods = arr.size

        # Fallback: if no upstream FCFF data set max_periods, derive it from
        # MasterSheet model_duration so the output timeline is never empty.
        if max_periods == 0:
            _dur_raw = MasterSheet.Global.ModelAssumptions.model_duration
            if _dur_raw is not None:
                try:
                    max_periods = max(1, int(float(_dur_raw * 12)))
                    print(f"Derived max_periods={max_periods} from MasterSheet.Global.ModelAssumptions.model_duration='{_dur_raw}'")
                except (TypeError, ValueError):
                    pass

        # Build 4 DataFrames (rows=assets, cols=periods) via numpy stacking
        _FCFF_KEYS = ("LandCo_FCFF", "DevCo_FCFF", "AssetCo_FCFF", "Land_In_Kind",
                      "LandCo_CFI", "DevCo_CFI")
        period_cols = list(range(max_periods))
        n_assets = len(all_selected_assets)

        fcff_matrices: Dict[str, np.ndarray] = {
            key: np.zeros((n_assets, max_periods), dtype=np.float64)
            for key in _FCFF_KEYS
        }
        
        # Track whether each asset's Land_In_Kind came from CFI (needs add-back when LIK=Yes)
        per_asset_lik_from_cfi: Dict[str, bool] = {}

        for i, asset_name in enumerate(all_selected_assets):
            fcff = per_asset_fcff_raw.get(asset_name, {})
            per_asset_lik_from_cfi[asset_name] = bool(fcff.get("_lik_from_cfi", False))
            for key in _FCFF_KEYS:
                arr = fcff.get(key)
                if arr is not None and arr.size > 0:
                    fcff_matrices[key][i, : arr.size] = arr

        landco_fcff_df  = pd.DataFrame(fcff_matrices["LandCo_FCFF"],  index=all_selected_assets, columns=period_cols)
        devco_fcff_df   = pd.DataFrame(fcff_matrices["DevCo_FCFF"],   index=all_selected_assets, columns=period_cols)
        assetco_fcff_df = pd.DataFrame(fcff_matrices["AssetCo_FCFF"], index=all_selected_assets, columns=period_cols)
        land_in_kind_df = pd.DataFrame(fcff_matrices["Land_In_Kind"], index=all_selected_assets, columns=period_cols)
        landco_cfi_df   = pd.DataFrame(fcff_matrices["LandCo_CFI"],   index=all_selected_assets, columns=period_cols)
        devco_cfi_df    = pd.DataFrame(fcff_matrices["DevCo_CFI"],    index=all_selected_assets, columns=period_cols)

        # Extract LandCo CFF "Land in Kind" directly for display as a standalone output line.
        # This is separate from land_in_kind_df (used for LIK calculation) and is sourced
        # exclusively from LandCo's Cashflow from Financing section.
        _lc_cff_lik_mat = np.zeros((n_assets, max_periods), dtype=np.float64)
        _lc_cff_section = landco_data.get("Cashflow from Financing", {})
        if isinstance(_lc_cff_section, dict):
            for i, asset_name in enumerate(all_selected_assets):
                _flags = module_flags.get(asset_name, {})
                if not _flags.get("landco", False):
                    continue
                lc_idx = _find_asset_index(landco_data, asset_name)
                if lc_idx is None:
                    continue
                _row = _extract_land_in_kind_from_section(_lc_cff_section, lc_idx)
                if _row is not None and _row.size > 0:
                    _lc_cff_lik_mat[i, : _row.size] = _row
        landco_cff_lik_df = pd.DataFrame(_lc_cff_lik_mat, index=all_selected_assets, columns=period_cols)

        fn_record_timing(_timing_ctx, "PHASE 5: Build FCFF DataFrames")

        # ----------------------------------------------------------------
        # PHASE 6: Build JV-windowed FCFF DataFrames
        # ----------------------------------------------------------------

        # --- 6a. Resolve model_start from MasterSheet Global (populated from named ranges) ---
        model_start_raw = MasterSheet.Global.ModelAssumptions.model_start_date
        if model_start_raw is not None:
            if isinstance(model_start_raw, (int, float)) and not isinstance(model_start_raw, bool):
                model_start = (pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(model_start_raw))).replace(day=1)
            else:
                model_start = pd.Timestamp(model_start_raw).replace(day=1)
        else:
            model_start = None
        
        # --- 6b. Resolve per-vehicle JV window by matching jv_name -> SPV scenario_name ---
        # Build lookup: jv_name (lower) -> ji (index into JVInputs.Asset lists)
        jv_scenario_names = JVInputs.Asset.SPVInputs.scenario_name or []
        jv_start_dates_list = JVInputs.Asset.JVDates.start_date_based_on_the_earliest_project_acquisition or []
        jv_fund_tenure_list = JVInputs.Asset.JVDates.fund_tenure_in_months or []

        def _find_ji(jv_name_lower: str) -> Optional[int]:
            """Find index into JVInputs.Asset lists matching jv_name."""
            if not isinstance(jv_scenario_names, list):
                return None
            for idx, sn in enumerate(jv_scenario_names):
                if _safe_str_lower(sn) == jv_name_lower:
                    return idx
            return None

        def _resolve_jv_window(ji: Optional[int]):
            """Return (start_idx, end_idx) for the JV vehicle at index ji."""
            if ji is None:
                return None, None
            raw_date = jv_start_dates_list[ji] if ji < len(jv_start_dates_list) else None
            raw_tenure = jv_fund_tenure_list[ji] if ji < len(jv_fund_tenure_list) else None
            start_idx = _date_to_month_index(raw_date, model_start)
            tenure = 0
            if raw_tenure is not None:
                try:
                    tenure = int(float(raw_tenure))
                except (TypeError, ValueError):
                    tenure = 0
            end_idx = (start_idx + tenure) if (start_idx is not None and tenure > 0) else None
            return start_idx, end_idx

        # Build asset_name -> (start_idx, end_idx) mapping via all_jv_groups
        asset_jv_window: Dict[str, tuple] = {}
        for jv_name_lower, group_assets in all_jv_groups.items():
            ji = _find_ji(jv_name_lower)
            start_idx, end_idx = _resolve_jv_window(ji)
            for aname in group_assets:
                asset_jv_window[aname] = (start_idx, end_idx)

        # Apply per-asset JV window mask to FCFF matrices
        landco_fcff_jv_mat  = np.zeros_like(fcff_matrices["LandCo_FCFF"])
        devco_fcff_jv_mat   = np.zeros_like(fcff_matrices["DevCo_FCFF"])
        assetco_fcff_jv_mat = np.zeros_like(fcff_matrices["AssetCo_FCFF"])
        landco_cfi_jv_mat   = np.zeros_like(fcff_matrices["LandCo_CFI"])
        devco_cfi_jv_mat    = np.zeros_like(fcff_matrices["DevCo_CFI"])

        for i, asset_name in enumerate(all_selected_assets):
            s_idx, e_idx = asset_jv_window.get(asset_name, (None, None))
            landco_fcff_jv_mat[i]  = _apply_jv_window(fcff_matrices["LandCo_FCFF"][i],  s_idx, e_idx, max_periods)
            devco_fcff_jv_mat[i]   = _apply_jv_window(fcff_matrices["DevCo_FCFF"][i],   s_idx, e_idx, max_periods)
            assetco_fcff_jv_mat[i] = _apply_jv_window(fcff_matrices["AssetCo_FCFF"][i], s_idx, e_idx, max_periods)
            landco_cfi_jv_mat[i]   = _apply_jv_window(fcff_matrices["LandCo_CFI"][i],   s_idx, e_idx, max_periods)
            devco_cfi_jv_mat[i]    = _apply_jv_window(fcff_matrices["DevCo_CFI"][i],    s_idx, e_idx, max_periods)

        landco_fcff_jv_df  = pd.DataFrame(landco_fcff_jv_mat,  index=all_selected_assets, columns=period_cols)
        devco_fcff_jv_df   = pd.DataFrame(devco_fcff_jv_mat,   index=all_selected_assets, columns=period_cols)
        assetco_fcff_jv_df = pd.DataFrame(assetco_fcff_jv_mat, index=all_selected_assets, columns=period_cols)
        landco_cfi_jv_df   = pd.DataFrame(landco_cfi_jv_mat,   index=all_selected_assets, columns=period_cols)
        devco_cfi_jv_df    = pd.DataFrame(devco_cfi_jv_mat,    index=all_selected_assets, columns=period_cols)

        # Diff DataFrames: full-timeline minus JV-windowed
        landco_fcff_diff_df  = landco_fcff_df  - landco_fcff_jv_df
        devco_fcff_diff_df   = devco_fcff_df   - devco_fcff_jv_df
        assetco_fcff_diff_df = assetco_fcff_df - assetco_fcff_jv_df

        fn_record_timing(_timing_ctx, "PHASE 6: Build JV-Windowed FCFF DataFrames")

        # ----------------------------------------------------------------
        # PHASE 7: JV Cashflows – Module Consolidation, LIK, Land Cost, Totals
        # ----------------------------------------------------------------

        # 7a. Module Cashflow Consolidation = LC-JV + DC-JV + AC-JV (per-asset)
        module_consol_jv_df = landco_fcff_jv_df + devco_fcff_jv_df + assetco_fcff_jv_df

        # 7b. Resolve LIK override flag per-asset (from JVInputs.Asset.InKindEquity)
        lik_override_list = JVInputs.Asset.InKindEquity.land_in__kind or []

        def _is_lik_yes(val) -> bool:
            if val is None:
                return False
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
            return str(val).strip().lower() in ("yes", "true", "1")

        # Build per-asset LIK flag via ji (same JV group -> same flag)
        asset_lik_flag: Dict[str, bool] = {}
        for jv_name_lower, group_assets in all_jv_groups.items():
            ji = _find_ji(jv_name_lower)
            lik_val = lik_override_list[ji] if (ji is not None and isinstance(lik_override_list, list) and ji < len(lik_override_list)) else None
            flag = _is_lik_yes(lik_val)
            for aname in group_assets:
                asset_lik_flag[aname] = flag

        # 7c. Land In Kind total per-asset (sum across full timeline)
        lik_totals = land_in_kind_df.values.sum(axis=1)  # shape (n_assets,)

        # 7d. Build Land In Kind - JV and Land Cost - JV DataFrames
        # LIK=Yes -> land_in_kind_jv[jv_start_idx] = -|total|, land_cost_jv = 0
        # LIK=No  -> land_in_kind_jv = 0, land_cost_jv[jv_start_idx] = -|total|
        lik_jv_mat  = np.zeros((n_assets, max_periods), dtype=np.float64)
        land_cost_jv_mat = np.zeros((n_assets, max_periods), dtype=np.float64)

        for i, asset_name in enumerate(all_selected_assets):
            s_idx, _ = asset_jv_window.get(asset_name, (None, None))
            if s_idx is None or s_idx < 0 or s_idx >= max_periods:
                continue
            total_val = abs(lik_totals[i])
            if total_val < 0.01:
                continue
            if asset_lik_flag.get(asset_name, False):
                lik_jv_mat[i, s_idx] = -total_val
            else:
                land_cost_jv_mat[i, s_idx] = -total_val

        land_in_kind_jv_df = pd.DataFrame(lik_jv_mat, index=all_selected_assets, columns=period_cols)
        land_cost_jv_df    = pd.DataFrame(land_cost_jv_mat, index=all_selected_assets, columns=period_cols)

        # 7e. Acquisition base for JV setup fee when LandCo is not in the JV.
        # When DC or AC is the first entity in the chain, its acquisition cost/
        # (DC SW "Serviced Land Acquisition" or AC CFI items) is summed and
        # placed at the JV start index, mirroring the land_cost_jv_mat pattern.
        acquisition_base_mat = np.zeros((n_assets, max_periods), dtype=np.float64)
        for i, asset_name in enumerate(all_selected_assets):
            if module_flags.get(asset_name, {}).get("landco", False):
                continue  # LC in JV -- existing land_cost path handles setup fee base
            acq_arr = _extract_asset_acquisition(
                asset_name,
                landco_data,
                devco_data,
                assetco_per_asset,
                module_flags,
                lifecycle_flags=lifecycle_flags.get(asset_name),
            )
            if acq_arr.size > 0:
                s_idx, _ = asset_jv_window.get(asset_name, (None, None))
                if s_idx is not None and 0 <= s_idx < max_periods:
                    acq_total = abs(float(acq_arr.sum()))
                    if acq_total > 0.01:
                        acquisition_base_mat[i, s_idx] = -acq_total
        acquisition_base_jv_df = pd.DataFrame(
            acquisition_base_mat, index=all_selected_assets, columns=period_cols,
        )
        
        # 7f_addback. When LIK=Yes and Land_In_Kind was sourced from CFI (already in
        # entity FCFF), subtract it back to prevent double-counting.
        # Exception: LandCo CFF "Land in Kind" is not part of FCFF — skip add-back.
        for i, asset_name in enumerate(all_selected_assets):
            if not asset_lik_flag.get(asset_name, False):
                continue
            if not per_asset_lik_from_cfi.get(asset_name, False):
                continue  # LandCo CFF source — not in FCFF, no add-back needed
            _flags = module_flags.get(asset_name, {})
            lik_row = land_in_kind_df.iloc[i].values
            s_idx, e_idx = asset_jv_window.get(asset_name, (None, None))
            lik_row_windowed = _apply_jv_window(lik_row, s_idx, e_idx, max_periods)
            if _flags.get("landco", False):
                landco_fcff_jv_mat[i] -= lik_row_windowed
            elif _flags.get("devco", False):
                devco_fcff_jv_mat[i] -= lik_row_windowed
            else:
                assetco_fcff_jv_mat[i] -= lik_row_windowed
                
        # 7f. Allocate acquisition cost (LIK=No) to the appropriate entity FCFF.
        # Uses the same basis as JV setup fees:
        #   LandCo in JV  → land_cost_jv_mat  → LandCo FCFF
        #   DevCo in JV   → acquisition_base_mat → DevCo FCFF
        #   AssetCo only  → acquisition_base_mat → AssetCo FCFF
        for i, asset_name in enumerate(all_selected_assets):
            if not asset_lik_flag.get(asset_name, False):
                _flags = module_flags.get(asset_name, {})
                if _flags.get("landco", False):
                    landco_fcff_jv_mat[i] += land_cost_jv_mat[i]
                elif _flags.get("devco", False):
                    devco_fcff_jv_mat[i] += acquisition_base_mat[i]
                else:
                    assetco_fcff_jv_mat[i] += acquisition_base_mat[i]

        # Rebuild entity DataFrames and consolidation after acquisition cost allocation.
        landco_fcff_jv_df  = pd.DataFrame(landco_fcff_jv_mat,  index=all_selected_assets, columns=period_cols)
        devco_fcff_jv_df   = pd.DataFrame(devco_fcff_jv_mat,   index=all_selected_assets, columns=period_cols)
        assetco_fcff_jv_df = pd.DataFrame(assetco_fcff_jv_mat, index=all_selected_assets, columns=period_cols)
        module_consol_jv_df = landco_fcff_jv_df + devco_fcff_jv_df + assetco_fcff_jv_df

        # 7g. Total FCFF before Financing and SPV Related Cost - JV (per-asset)
        # LIK=Yes -> module_consol only (land is non-cash, excluded)
        # LIK=No  -> acquisition cost is now in entity FCFFs (step 7f), so
        #            module_consol already carries the correct total.
        total_fcff_jv_mat = module_consol_jv_df.values.copy()

        total_fcff_jv_df = pd.DataFrame(total_fcff_jv_mat, index=all_selected_assets, columns=period_cols)

        # 7h. Total FCFF - JV (Including Land inkind) per-asset
        # LIK=Yes -> total_fcff + land_in_kind_jv (adds in-kind lump back)
        # LIK=No  -> same as total_fcff (land already included as cash)
        total_fcff_incl_lik_jv_mat = total_fcff_jv_mat.copy()
        for i, asset_name in enumerate(all_selected_assets):
            if asset_lik_flag.get(asset_name, False):
                total_fcff_incl_lik_jv_mat[i] += lik_jv_mat[i]

        total_fcff_incl_lik_jv_df = pd.DataFrame(
            total_fcff_incl_lik_jv_mat, index=all_selected_assets, columns=period_cols,
        )

        fn_record_timing(_timing_ctx, "PHASE 7: JV Cashflows")

        # ----------------------------------------------------------------
        # PHASE 8: Asset Sales Value (per-asset, JV-windowed)
        # ----------------------------------------------------------------
        asset_sales_mat = np.zeros((n_assets, max_periods), dtype=np.float64)

        for i, asset_name in enumerate(all_selected_assets):
            sales_arr = _extract_asset_sales(
                asset_name, landco_data, devco_data, assetco_per_asset, module_flags,
                lifecycle_flags=lifecycle_flags.get(asset_name),
            )
            if sales_arr.size > 0:
                s_idx, e_idx = asset_jv_window.get(asset_name, (None, None))
                windowed = _apply_jv_window(sales_arr, s_idx, e_idx, max_periods)
                asset_sales_mat[i, :] = windowed

        asset_sales_jv_df = pd.DataFrame(asset_sales_mat, index=all_selected_assets, columns=period_cols)

        fn_record_timing(_timing_ctx, "PHASE 8: Asset Sales Value")

        # ----------------------------------------------------------------
        # PHASE 9: Read Interest Rate Profiles
        # ----------------------------------------------------------------
        interest_profiles = _read_interest_rate_profiles(
            jv_df,
            _read_array,
            JV_INTEREST_PROFILES,
            DD_INTEREST_PROFILES,
            JV_INTEREST_VALUES,
        )

        fn_record_timing(_timing_ctx, "PHASE 9: Interest Rate Profiles")

        # ----------------------------------------------------------------
        # PHASE 10: Per-Vehicle JV Inputs Resolution
        # ----------------------------------------------------------------
        # jv_scenario_names_list = scenario names from JVInputs.Asset rows
        jv_asset_scenario_names = jv_scenario_names  # already extracted in PHASE 4

        vehicle_inputs = {}  # jv_name -> resolved dict
        for jv_name in all_jv_groups.keys():
            vi = _resolve_vehicle_jv_inputs(
                jv_name,
                jv_asset_scenario_names,
                JVInputs,
                _safe_str_lower,
            )
            vehicle_inputs[jv_name] = vi


        fn_record_timing(_timing_ctx, "PHASE 10: Per-Vehicle JV Inputs")

        # ----------------------------------------------------------------
        # PHASE 11: CFF Engine (per vehicle)
        # ----------------------------------------------------------------
        vehicle_cff = {}  # jv_name -> cff dict

        for jv_name, v_assets in all_jv_groups.items():
            vi = vehicle_inputs[jv_name]

            # Aggregate total_fcff, land_in_kind, asset_sales, project_cost, land_cost across this vehicle's assets
            v_total_fcff = [0.0] * max_periods
            v_land_in_kind = [0.0] * max_periods
            v_asset_sales = [0.0] * max_periods
            v_project_cost = [0.0] * max_periods
            v_land_cost = [0.0] * max_periods

            for asset_name in v_assets:
                if asset_name in total_fcff_jv_df.index:
                    row = total_fcff_jv_df.loc[asset_name].values
                    v_total_fcff = [v_total_fcff[j] + float(row[j])
                                    for j in range(max_periods)]
                if asset_name in land_in_kind_jv_df.index:
                    row = land_in_kind_jv_df.loc[asset_name].values
                    v_land_in_kind = [v_land_in_kind[j] + float(row[j])
                                      for j in range(max_periods)]
                if asset_name in asset_sales_jv_df.index:
                    row = asset_sales_jv_df.loc[asset_name].values
                    v_asset_sales = [v_asset_sales[j] + float(row[j])
                                     for j in range(max_periods)]
                # Project cost = LandCo CFI (excl terminal values) + DevCo CFI + Land Cost
                for src_df in (landco_cfi_jv_df, devco_cfi_jv_df, land_cost_jv_df):
                    if asset_name in src_df.index:
                        row = src_df.loc[asset_name].values
                        v_project_cost = [v_project_cost[j] + float(row[j])
                                          for j in range(max_periods)]
                # Land cost (raw land acquisition outflow, for setup fee base)
                if asset_name in land_cost_jv_df.index:
                    row = land_cost_jv_df.loc[asset_name].values
                    v_land_cost = [v_land_cost[j] + float(row[j])
                                   for j in range(max_periods)]

            # When LandCo is not in the JV, land_cost is 0 (no LC CFI captured).
            # Use the acquisition base from DevCo/AssetCo as the setup fee base instead.
            if sum(abs(v) for v in v_land_cost) < 0.01:
                for asset_name in v_assets:
                    if asset_name in acquisition_base_jv_df.index:
                        row = acquisition_base_jv_df.loc[asset_name].values
                        v_land_cost = [v_land_cost[j] + float(row[j])
                                       for j in range(max_periods)]

            cff_result = _compute_cff(
                total_fcf=v_total_fcff,
                land_in_kind=v_land_in_kind,
                max_periods=max_periods,
                vehicle_inputs=vi,
                interest_profiles=interest_profiles,
                model_start=model_start,
                asset_sales=v_asset_sales,
                project_cost=v_project_cost,
                land_cost=v_land_cost,
            )
            vehicle_cff[jv_name] = cff_result

        fn_record_timing(_timing_ctx, "PHASE 11: CFF Engine")

        # ----------------------------------------------------------------
        # PHASE 12: Returns (IRR / NPV / MOIC per vehicle)
        # ----------------------------------------------------------------
        # Valuation assumptions from MasterSheet
        _va = MasterSheet.Global.ValuationAssumptions
        discount_rate = _to_float(getattr(_va, 'discount_rate', 0)) or 0.0
        if discount_rate > 1:
            discount_rate /= 100.0
        mirr_finance_rate = _to_float(getattr(_va, 'mirr_finance_rate', 0)) or 0.0
        if mirr_finance_rate > 1:
            mirr_finance_rate /= 100.0
        mirr_reinvest_rate = _to_float(getattr(_va, 'mirr_reinvestment_rate', 0)) or 0.0
        if mirr_reinvest_rate > 1:
            mirr_reinvest_rate /= 100.0
        irr_option = str(getattr(_va, 'irr_calculation_option', '') or '').strip().lower()

        # Monthly discount rate for NPV
        monthly_discount = (1 + discount_rate) ** (1 / 12) - 1 if discount_rate > 0 else 0.0

        # Build monthly date timeline for XIRR
        _dates_for_xirr = None
        if model_start is not None:
            _dates_for_xirr = [
                model_start + pd.DateOffset(months=t) for t in range(max_periods)
            ]

        def _safe_irr(cashflows: list) -> object:
            """Compute IRR/XIRR/MIRR based on irr_calculation_option."""
            if not any(v != 0 for v in cashflows):
                return None
            if irr_option == 'mirr':
                return _mirr(cashflows, mirr_finance_rate, mirr_reinvest_rate)
            if irr_option == 'xirr' and _dates_for_xirr is not None:
                return _xirr(cashflows, _dates_for_xirr)
            # Default: standard IRR (monthly); annualise
            monthly = _irr(cashflows)
            if monthly is None:
                return None
            if isinstance(monthly, str):
                return monthly  # multi-root string
            return (1 + monthly) ** 12 - 1

        def _safe_npv(cashflows: list) -> float:
            """NPV at monthly discount rate (period-1 start)."""
            if monthly_discount <= 0:
                return 0.0
            return _npv(monthly_discount, cashflows)

        def _safe_moic(outflows: list, inflows: list) -> object:
            """MOIC = total inflows / total outflows."""
            total_out = sum(abs(v) for v in outflows if v < 0)
            total_in = sum(v for v in inflows if v > 0)
            return total_in / total_out if total_out > 0.01 else None

        vehicle_returns = {}  # jv_name -> returns dict

        for jv_name in all_jv_groups.keys():
            cff = vehicle_cff[jv_name]

            # --- Project-level cashflows ---
            unlevered_cf = cff.get("Total Free Cashflow before Financing", _zeros(max_periods))
            levered_cf = cff.get("Net Cash", _zeros(max_periods))

            # --- LP cashflows (contributions negative, distributions positive) ---
            lp_cf = _row_add(
                cff.get("LP Contributions", _zeros(max_periods)),
                cff.get("LP Distributions", _zeros(max_periods)),
            )

            # --- GP cashflows ---
            gp_cf = _row_add(
                cff.get("GP Contributions", _zeros(max_periods)),
                cff.get("GP Distributions", _zeros(max_periods)),
            )

            # --- Equity cashflows (infusion negative, returns positive) ---
            equity_cf = _row_add(
                _row_negate(cff.get("Equity Infused", _zeros(max_periods))),
                cff.get("Equity Returns", _zeros(max_periods)),
            )

            returns = {
                "project_unlevered_irr": _safe_irr(unlevered_cf),
                "project_npv": _safe_npv(unlevered_cf),
                "project_levered_irr": _safe_irr(equity_cf),
                "project_equity_npv": _safe_npv(equity_cf),
                "project_moic": _safe_moic(
                    cff.get("Equity Infused", _zeros(max_periods)),
                    cff.get("Equity Returns", _zeros(max_periods)),
                ),
                "lp_irr": _safe_irr(lp_cf),
                "lp_npv": _safe_npv(lp_cf),
                "lp_moic": _safe_moic(
                    cff.get("LP Contributions", _zeros(max_periods)),
                    cff.get("LP Distributions", _zeros(max_periods)),
                ),
                "gp_irr": _safe_irr(gp_cf),
                "gp_npv": _safe_npv(gp_cf),
                "gp_moic": _safe_moic(
                    cff.get("GP Contributions", _zeros(max_periods)),
                    cff.get("GP Distributions", _zeros(max_periods)),
                ),
            }
            vehicle_returns[jv_name] = returns

            for k, v in returns.items():
                if isinstance(v, float):
                    pass
                else:
                    pass

        fn_record_timing(_timing_ctx, "PHASE 12: Returns")

        # ----------------------------------------------------------------
        # PHASE 13: Output Assembly (consolidated)
        # ----------------------------------------------------------------
        NR = {
            "OUT_CASHFLOWS_ME":    OUT_CASHFLOWS_ME,
            "OUT_CASHFLOWS_YE":    OUT_CASHFLOWS_YE,
            "OUT_TIMELINE_ME":     OUT_TIMELINE_ME,
            "OUT_TIMELINE_YE":     OUT_TIMELINE_YE,
            "OUT_TL1_SCHED_ME":    OUT_TL1_SCHED_ME,
            "OUT_TL1_SCHED_YE":    OUT_TL1_SCHED_YE,
            "OUT_REFI_SCHED_ME":   OUT_REFI_SCHED_ME,
            "OUT_REFI_SCHED_YE":   OUT_REFI_SCHED_YE,
            "OUT_EQUITY_SCHED_ME": OUT_EQUITY_SCHED_ME,
            "OUT_EQUITY_SCHED_YE": OUT_EQUITY_SCHED_YE,
            "OUT_PREF_RETURNS_ME": OUT_PREF_RETURNS_ME,
            "OUT_PREF_RETURNS_YE": OUT_PREF_RETURNS_YE,
        }

        output = build_consolidated_output(
            landco_fcff_df=landco_fcff_jv_df,
            devco_fcff_df=devco_fcff_jv_df,
            assetco_fcff_df=assetco_fcff_jv_df,
            total_fcff_jv_df=total_fcff_jv_df,
            total_fcff_incl_lik_jv_df=total_fcff_incl_lik_jv_df,
            land_in_kind_jv_df=land_in_kind_jv_df,
            land_cost_jv_df=land_cost_jv_df,
            landco_cff_lik_df=landco_cff_lik_df,
            module_consol_jv_df=module_consol_jv_df,
            asset_sales_jv_df=asset_sales_jv_df,
            vehicle_cff=vehicle_cff,
            max_periods=max_periods,
            model_start=model_start,
            selected_assets=selected_assets,
            period_cols=period_cols,
            NR=NR,
            selected_vehicle=selected_scenario,
            jv_groups=all_jv_groups,
            vehicle_inputs=vehicle_inputs,
        )

        fn_record_timing(_timing_ctx, "PHASE 13: Output Assembly")

        # ================================================================
        # PHASE 14: Exports (gated by _EXPORT_FLAGS)
        # Wrapped in its own try/except so export errors don't lose the
        # already-computed model result.
        # ================================================================
        try:
            # E.1 Consolidated output (monthly + annual dfs → Excel)
            if fn_is_export_enabled(_EXPORT_FLAGS, "consolidated_output"):
                fn_export_jv_consolidated_output(
                    output.get("exceloutput", {}),
                    "jv_consolidated_output.xlsx",
                )

            # E.2 Loan schedules (TL1 + Refinancing → Excel)
            if fn_is_export_enabled(_EXPORT_FLAGS, "loan_schedules"):
                fn_export_loan_schedules(
                    output.get("loan_schedule_sheets", {}),
                    "jv_loan_schedules.xlsx",
                )

            # E.3 Vehicle CFF (per-vehicle cashflow rows → Excel)
            if fn_is_export_enabled(_EXPORT_FLAGS, "vehicle_cff"):
                for vname, cff_rows in vehicle_cff.items():
                    _cff_export: Dict[str, Any] = {}
                    public_rows = {k: v for k, v in cff_rows.items()
                                   if not k.startswith("_")}
                    if public_rows:
                        _cff_df = pd.DataFrame(public_rows, index=period_cols).T
                        _cff_export["CFF"] = _cff_df
                    fn_export_dataframes_to_excel(
                        _cff_export,
                        f"jv_cff_{vname}",
                        f"Vehicle CFF: {vname}",
                    )

            # E.4 Vehicle Returns (scalar metrics → Excel)
            if fn_is_export_enabled(_EXPORT_FLAGS, "vehicle_returns"):
                _ret_rows = []
                for vname, rets in vehicle_returns.items():
                    for metric, val in rets.items():
                        _ret_rows.append({
                            "Vehicle": vname,
                            "Metric": metric,
                            "Value": val,
                        })
                if _ret_rows:
                    fn_export_dataframes_to_excel(
                        {"Returns": pd.DataFrame(_ret_rows)},
                        "jv_returns",
                        "JV Vehicle Returns",
                    )

        except Exception as export_exc:
            pass

        fn_record_timing(_timing_ctx, "PHASE 14: Exports")

        # ----------------------------------------------------------------
        # Finalize timing summary
        # ----------------------------------------------------------------
        timing_summary = fn_finalize_timing_summary(
            _timing_ctx,
            "PHASE 14: Exports",
            entity_label="JV CONSOLIDATION",
        )

        return output

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            print(f"[jv_consolidation.wrapper_for_vars] ERROR at {last_frame.filename}:{last_frame.lineno} in {last_frame.name}")
            print(f"[jv_consolidation.wrapper_for_vars]   line: {last_frame.line}")
        print(f"[jv_consolidation.wrapper_for_vars] Exception: {type(e).__name__}: {e}")
        print(f"[jv_consolidation.wrapper_for_vars] Full traceback:\n{traceback.format_exc()}")
        return None


def _normalize_payload_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return 0 if (np.isnan(value) or np.isinf(value)) else float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return 0
        return value
    try:
        return "" if pd.isna(value) else value
    except Exception:
        return value


def _normalize_split_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    index_vals = payload.get("index", [])
    column_vals = payload.get("columns", [])
    data_vals = payload.get("data", [])

    normalized_index = [_normalize_payload_cell(v) for v in index_vals]
    normalized_columns = [_normalize_payload_cell(v) for v in column_vals]

    normalized_data = []
    for row in data_vals:
        if isinstance(row, list):
            normalized_data.append([_normalize_payload_cell(v) for v in row])
        else:
            normalized_data.append(row)

    return {
        "index": normalized_index,
        "columns": normalized_columns,
        "data": normalized_data,
    }


def _normalize_excel_output_payloads(excel_output: Any) -> Any:
    if not isinstance(excel_output, dict):
        return excel_output

    normalized: Dict[str, Any] = {}
    for section_key in ("monthly_dfs", "annual_dfs"):
        section = excel_output.get(section_key, {})
        if not isinstance(section, dict):
            normalized[section_key] = section
            continue

        normalized_section: Dict[str, Any] = {}
        for sheet_name, entry in section.items():
            if (
                isinstance(entry, tuple)
                and len(entry) == 2
                and isinstance(entry[1], dict)
                and "index" in entry[1]
                and "columns" in entry[1]
                and "data" in entry[1]
            ):
                code, payload = entry
                normalized_section[sheet_name] = (code, _normalize_split_payload(payload))
            else:
                normalized_section[sheet_name] = entry

        normalized[section_key] = normalized_section

    for key, value in excel_output.items():
        if key not in normalized:
            normalized[key] = value

    return normalized


def _is_blank_normalization_cell(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    try:
        return value != value
    except Exception:
        return False


def _normalize_numeric_cell(value):
    if isinstance(value, float):
        if value == float("inf") or value == float("-inf"):
            return 0.0
        if value != value:
            return ""
        return value
    return value


def _is_zero_or_null_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"", "null", "none"}:
            return True
        try:
            return float(text) == 0.0
        except ValueError:
            return False
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    return False


def _normalize_position_key(text):
    raw = "" if text is None else str(text).strip().lower()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9\s]", " ", raw)
    return " ".join(raw.split())


def _normalize_jv_period_label(col, base_ts):
    if col is None:
        return "", ""

    if isinstance(col, (int, np.integer)):
        if base_ts is not None and col >= 0:
            return (base_ts + pd.DateOffset(months=int(col))).date().isoformat(), ""
        return "", ""

    if isinstance(col, np.floating):
        if np.isnan(col) or np.isinf(col):
            return "", ""
        if float(col).is_integer():
            offset = int(col)
            if base_ts is not None and offset >= 0:
                return (base_ts + pd.DateOffset(months=offset)).date().isoformat(), ""
        return "", ""

    col_text = str(col).strip()
    if "-" in col_text or "/" in col_text:
        return col_text, ""

    if col_text.isdigit():
        year_value = int(col_text)
        if 1 <= year_value <= 9999:
            return "", col_text
        if base_ts is not None and year_value >= 0:
            return (base_ts + pd.DateOffset(months=year_value)).date().isoformat(), ""

    return "", ""


_JV_HIERARCHY = {
    "Cash Waterfall and Return distribution": {
        "Entity Level Free Cashflows": [
            "LandCo Free Cashflow", "DevCo Free Cashflow",
            "AssetCo Free Cashflow", "Cash Flow before Financing and SPV-related Cost",
            "Entity Level Free Cashflows",
        ],
        "Fund-related Expenses": [
            "JV Setup Fees", "Fund Management Fees",
            "Other Fees", "JV Liquidation Fees",
            "Cash Flow before Financing Cost", "Fund-related Expenses",
        ],
        "Funding-related Cost": [
            "Arrangement Fees", "Commitment Fees", "Interest Cost",
            "Cash Flow before Financing", "Funding-related Cost",
        ],
        "Loan Raised": [
            "Debt 1", "Debt 2", "Loan Raised",
        ],
        "Equity Raised": [
            "LP", "GP", "Equity Raised",
        ],
        "Source of Funding Summary": [
            "Cash Flow before Distributions and Repayments", "Source of Funding Summary",
        ],
        "Loan Repaid": [
            "Debt 1", "Debt 2", "Loan Repaid",
        ],
        "Return of Capital": [
            "LP", "GP", "Return of Capital",
        ],
        "Distributions": [
            "Preferred Return",
            "GP Promote & Catchup (Post Preferred)", "Tier 1 LP Distributions",
            "Tier 1 GP Promote", "Tier 1 GP Catchup",
            "Tier 2 LP Distributions", "Tier 2 GP Promote", "Tier 2 GP Catchup",
            "Tier 3 LP Distributions", "Tier 3 GP Distributions",
            "Distributions",
        ],
        "Distributions and Repayments Summary": [
            "Net Cashflow from Projects", "Distributions and Repayments Summary",
        ],
    },
    "Debt 1 Account": {
        "Debt 1 Schedule": [
            "Opening Balance", "Amount Raised",
            "Arrangement Fees Capitalization", "Commitment Fees Capitalization",
            "Interest During Construction (IDC)", "Principal Repayment",
            "Bullet Payment", "Closing Balance",
            "Interest Expense", "Arrangement Fees", "Commitment Fees",
            "Debt 1 Schedule",
        ],
    },
    "Refinancing Debt Account": {
        "Refinancing Debt Schedule": [
            "Opening Balance", "Amount Raised",
            "Arrangement Fees Capitalization", "Commitment Fees Capitalization",
            "Interest During Construction (IDC)", "Principal Repayment",
            "Bullet Payment", "Closing Balance",
            "Interest Expense", "Arrangement Fees", "Commitment Fees",
            "Refinancing Debt Schedule",
        ],
    },
    "Equity Schedule": {
        "Equity Infusion": [
            "Cash Equity Infusion Requirement", "Equity Infusion",
        ],
        "Cash Equity Commitment": [
            "GP Commitment", "LP Commitment", "Total Cash Equity", "Cash Equity Commitment",
        ],
        "Equity In Kind": [
            "Land In Kind (GP)", "Land In Kind (LP)", "Total In Kind Equity", "Equity In Kind",
        ],
        "Total Equity Commitment": [
            "GP Equity", "LP Others Equity", "Total Equity Commitment",
        ],
        "Distribution Summary": [
            "Return of Capital", "Preferred Return",
            "GP Promote & Catchup (Post Preferred)", "Tier 1 LP Distributions",
            "Tier 1 GP Promote", "Tier 1 GP Catchup",
            "Tier 2 LP Distributions", "Tier 2 GP Promote", "Tier 2 GP Catchup",
            "Tier 3 LP Distributions", "Tier 3 GP Distributions",
            "Total Cash Distributions", "Distribution Summary",
            "Compensation in Lieu of Land to GP", "Compensation in Lieu of Land to LP",
        ],
    },
    "Waterfall Distribution": {
        "Preferred Returns": [
            "Total Distributions", "Remaining Cash Flow after Preferred Return",
            "Preferred Returns",
        ],
        "LP Preferred Returns": [
            "Opening Balance", "LP Capital Contributions", "Preferred Accrual",
            "Return of Capital", "LP Distributions", "Undistributed Cash",
            "Ending Balance", "LP Preferred Returns",
        ],
        "GP Preferred Returns": [
            "Opening Balance", "GP Capital Contributions", "Preferred Accrual",
            "Return of Capital", "GP Distributions", "Undistributed Cash",
            "Ending Balance", "GP Preferred Returns",
        ],
        "GP Catchup": [
            "GP Catchup", "Total Distributions", "Remaining Cash Flow after Preferred Return & GP Catchup",
        ],
        "Tier 1 Distributions": [
            "Opening Balance", "LP Capital Contributions", "Tier 1 Accrual", "Previous LP Distributions",
            "LP Distributions", "Ending Balance",
            "Remaining Cash Flow after Tier 1 LP distribution",
            "GP Tier 1 Promote", "GP Tier 1 Catchup",
            "Remaining Cash Flow after Tier 1 Distribution & Catchup",
            "Tier 1 Distributions",
        ],
        "Tier 2 Distributions": [
            "Opening Balance", "LP Capital Contributions", "Tier 2 Accrual", "Previous LP Distributions",
            "LP Distributions", "Ending Balance",
            "Remaining Cash Flow after Tier 2 LP distribution",
            "GP Tier 2 Promote", "GP Tier 2 Catchup",
            "Remaining Cash Flow after Tier 2 Distribution & Catchup",
            "Tier 2 Distributions",
        ],
        "Tier 3 Distributions": [
            "LP Tier 3 Distributions", "GP Tier 3 Distributions", "Tier 3 Distributions",
        ],
    },
    "Clawback Workings": {
        "Clawback Workings": [
            "LP's Cash Flows", "Rolling IRR", "Clawback Amount",
            "LP Net Cashflows before Clawback", "Clawback - LP", "LP Net Cashflows after Clawback",
            "GP Net Cashflows before Clawback", "Clawback - GP", "GP Net Cashflows after Clawback",
            "Clawback Workings",
        ],
    },
}

_JV_SECTION_KEYS = {
    _normalize_position_key(k): k for k in _JV_HIERARCHY.keys()
}
_JV_SHEET_SECTION_ALIASES = {
    "jv cashflows": "Cash Waterfall and Return distribution",
    "fcff": "Cash Waterfall and Return distribution",
    "cashflows": "Cash Waterfall and Return distribution",
    "fees": "Cash Waterfall and Return distribution",
    "asset sales": "Cash Waterfall and Return distribution",
    "total funding": "Cash Waterfall and Return distribution",
    "term loan 1": "Cash Waterfall and Return distribution",
    "refinancing": "Cash Waterfall and Return distribution",
    "additional equity requirement": "Equity Schedule",
    "additional equity drawn": "Equity Schedule",
    "land in kind commitment": "Equity Schedule",
    "total commitment": "Equity Schedule",
    "cash distribution": "Cash Waterfall and Return distribution",
    "preferred returns": "Waterfall Distribution",
    "project cost": "Cash Waterfall and Return distribution",
    "tl1 schedule": "Debt 1 Account",
    "refi schedule": "Refinancing Debt Account",
    "refi min dscr": "Refinancing Debt Account",
    "equity schedule": "Equity Schedule",
    "equity scehdule": "Equity Schedule",
}
_JV_MAIN_BY_SECTION = {
    section: {
        _normalize_position_key(main): main for main in mains.keys()
    }
    for section, mains in _JV_HIERARCHY.items()
}
_JV_ITEM_TO_MAIN_BY_SECTION = {
    section: {
        _normalize_position_key(item): main
        for main, items in mains.items()
        for item in items
    }
    for section, mains in _JV_HIERARCHY.items()
}
_JV_ALLOWED_ITEMS_BY_SECTION = {
    section: set(item_map.keys())
    for section, item_map in _JV_ITEM_TO_MAIN_BY_SECTION.items()
}


def _resolve_jv_section_and_main(sheet_name, current_section, current_category, line_item):
    sheet_key = _normalize_position_key(sheet_name)
    section_from_sheet = _JV_SHEET_SECTION_ALIASES.get(sheet_key)
    resolved_section = _JV_SECTION_KEYS.get(
        _normalize_position_key(current_section),
        _JV_SECTION_KEYS.get(
            _normalize_position_key(section_from_sheet),
            _JV_SECTION_KEYS.get(sheet_key, str(sheet_name)),
        ),
    )

    item_to_main = _JV_ITEM_TO_MAIN_BY_SECTION.get(resolved_section, {})
    main_map = _JV_MAIN_BY_SECTION.get(resolved_section, {})

    mapped_main = item_to_main.get(_normalize_position_key(line_item))
    if mapped_main:
        return resolved_section, mapped_main

    current_main = main_map.get(_normalize_position_key(current_category), current_category)
    return resolved_section, current_main


def _exceloutput_monthly_to_dashboard_rows(excel_output):
    if not isinstance(excel_output, dict):
        return []

    monthly_dfs = excel_output.get("monthly_dfs") or {}
    if not isinstance(monthly_dfs, dict):
        return []

    model_start_raw = MasterSheet.Global.ModelAssumptions.model_start_date
    try:
        base_ts = pd.Timestamp(model_start_raw).replace(day=1) if model_start_raw is not None else None
    except Exception:
        base_ts = None

    excluded_sheets = {"monthly timeline", "timeline", "yearly timeline"}
    records = []

    for sheet_name, entry in monthly_dfs.items():
        if str(sheet_name or "").strip().lower() in excluded_sheets:
            continue
        if not (isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[1], dict)):
            continue

        payload = entry[1]
        row_labels = payload.get("index") or []
        columns = payload.get("columns") or []
        data_rows = payload.get("data") or []

        sheet_key = _normalize_position_key(sheet_name)
        section_from_sheet = _JV_SHEET_SECTION_ALIASES.get(sheet_key)
        current_section = _JV_SECTION_KEYS.get(
            _normalize_position_key(section_from_sheet),
            _JV_SECTION_KEYS.get(sheet_key, str(sheet_name)),
        )
        current_category = ""
        for row_idx, row_label in enumerate(row_labels):
            label = "" if row_label is None else str(row_label).strip()
            row_vals = data_rows[row_idx] if row_idx < len(data_rows) and isinstance(data_rows[row_idx], list) else []

            if label.strip() == "":
                continue

            label_section = _JV_SECTION_KEYS.get(_normalize_position_key(label))
            if label_section:
                current_section = label_section
                current_category = ""
                continue

            is_all_empty = True
            for cell in row_vals:
                if not _is_blank_normalization_cell(cell):
                    is_all_empty = False
                    break

            if is_all_empty:
                canonical_main = _JV_MAIN_BY_SECTION.get(current_section, {}).get(
                    _normalize_position_key(label),
                    label,
                )
                current_category = canonical_main
                continue

            resolved_section, resolved_category = _resolve_jv_section_and_main(
                sheet_name,
                current_section,
                current_category,
                label,
            )
            if not resolved_category:
                continue
            allowed_items = _JV_ALLOWED_ITEMS_BY_SECTION.get(resolved_section)
            if allowed_items is not None and _normalize_position_key(label) not in allowed_items:
                continue

            for col_idx, col in enumerate(columns):
                value = row_vals[col_idx] if col_idx < len(row_vals) else None
                value = _normalize_numeric_cell(value)

                if _is_blank_normalization_cell(value) or _is_zero_or_null_value(value):
                    continue

                period_start, year = _normalize_jv_period_label(col, base_ts)

                records.append(
                    {
                        "Cashflow Section": resolved_section,
                        "Main Category": resolved_category,
                        "Line Item": label,
                        "Value Type": "Monthly",
                        "Period Start": period_start,
                        "Year": year,
                        "Value": value,
                    }
                )

    return records


def fninitialising_all_values(payload: Any) -> Optional[Any]:
    """Entry point delegates to wrapper_for_vars and returns normalized dashboard payload."""
    try:
        if payload is None:
            return None
        if not isinstance(payload, (dict, list)):
            return None

        output = wrapper_for_vars(payload)
        if not isinstance(output, dict):
            return None

        excel_output = output.get("exceloutput") or {}
        excel_output = _normalize_excel_output_payloads(excel_output)
        dashboard_rows = _exceloutput_monthly_to_dashboard_rows(excel_output)
        return {
            "normalized_dashboard_payload": dashboard_rows,
        }

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            print(f"[jv_consolidation.fninitialising_all_values] ERROR at {last_frame.filename}:{last_frame.lineno} in {last_frame.name}")
            print(f"[jv_consolidation.fninitialising_all_values]   line: {last_frame.line}")
        print(f"[jv_consolidation.fninitialising_all_values] Exception: {type(e).__name__}: {e}")
        print(f"[jv_consolidation.fninitialising_all_values] Full traceback:\n{traceback.format_exc()}")
        return None
