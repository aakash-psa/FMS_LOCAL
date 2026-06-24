# ============================================================================
# DEVCO CASHFLOW MODULE
# ============================================================================
# Module: devco_model.py
# Description: Calculates cash flows for development company (DevCo) projects
#              including land acquisition, vertical construction, soft costs,
#              escrow mechanism, disposal/sales, forward funding, forward sales,
#              and financing.
# Version: 1.1
# Last Updated: 2026-02-06
# ============================================================================
#
# NAMING CONVENTIONS:
# ============================================================================
# This module follows standardized naming conventions for maintainability:
#
# FUNCTIONS:
#   fn_<function_name>     - All functions start with 'fn_' prefix
#                            Example: fn_create_model_timeline()
#
# DATAFRAMES & VARIABLES:
#   o_<name>               - Output dataframes (used in cashflow statements)
#                            Example: o_vertical_construction_cost
#
#   w_<name>               - Working/intermediate dataframes (internal calcs)
#                            Example: w_acquisition_date
#
#   g_<name>               - Global configuration variables
#                            Example: g_model_timeline_me
#
#   df_<name>              - Template/base dataframes
#                            Example: df_asset_timeline_template
#
# CLASSES:
#   PascalCase             - Class names use PascalCase
#                            Example: Global, Asset
#
# LOOP VARIABLES:
#   loop_row_idx           - Row index in loops
#   loop_col_idx           - Column index in loops
#
# ERROR HANDLING:
#   All functions include try-except blocks with traceback printing
#   Errors are logged with function name and line number
#
# ============================================================================

# ============================================================================
# MODULE 0: IMPORTS AND DEPENDENCIES
# ============================================================================

import os
import time
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
import datetime as dt
from calendar import month
import math
from dateutil.relativedelta import relativedelta
from typing import Any, Dict, List, Tuple
import warnings
import mainapp.utils.v3.landco_capex_module as landco_capex_module


class ExecutorManager:
    """Singleton managing shared executors for the module."""
    _thread_executor = None
    _thread_lock = threading.Lock()
    _process_executor = None
    _process_lock = threading.Lock()

    @classmethod
    def get_thread_executor(cls, max_workers=None):
        if cls._thread_executor is None:
            with cls._thread_lock:
                if cls._thread_executor is None:
                    workers = max_workers or max(1, min(8, (os.cpu_count() or 1)))
                    cls._thread_executor = ThreadPoolExecutor(max_workers=workers)
        return cls._thread_executor

    @classmethod
    def get_process_executor(cls, max_workers=None):
        if cls._process_executor is None:
            with cls._process_lock:
                if cls._process_executor is None:
                    workers = max_workers or max(1, min(4, (os.cpu_count() or 1)))
                    cls._process_executor = ProcessPoolExecutor(max_workers=workers)
        return cls._process_executor

    @classmethod
    def shutdown(cls, wait=True):
        with cls._thread_lock:
            if cls._thread_executor is not None:
                cls._thread_executor.shutdown(wait=wait)
                cls._thread_executor = None
        with cls._process_lock:
            if cls._process_executor is not None:
                cls._process_executor.shutdown(wait=wait)
                cls._process_executor = None


# ============================================================================
# UTILITY FUNCTION: CLASS TO DICTIONARY CONVERTER
# ============================================================================

def _json_safe_class_value(value):
    """Convert values into JSON-safe primitives for split payload serialization."""
    if value is None:
        return None

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return None if pd.isna(value) else value.isoformat()

    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()

    if isinstance(value, (pd.Timedelta, dt.timedelta)):
        return None if pd.isna(value) else str(value)

    if isinstance(value, np.timedelta64):
        return None if np.isnat(value) else str(pd.Timedelta(value))

    if isinstance(value, pd.Period):
        return None if pd.isna(value) else str(value)

    if isinstance(value, pd.Series):
        return [_json_safe_class_value(item) for item in value.tolist()]

    if isinstance(value, np.ndarray):
        return [_json_safe_class_value(item) for item in value.tolist()]

    if isinstance(value, tuple):
        return [_json_safe_class_value(item) for item in value]

    if isinstance(value, list):
        return [_json_safe_class_value(item) for item in value]

    if isinstance(value, dict):
        return {str(key): _json_safe_class_value(item) for key, item in value.items()}

    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value

    try:
        return None if pd.isna(value) else value
    except TypeError:
        return value


def _class_attrs_to_split_payload(attributes):
    """Convert a flat class attribute mapping into split-orientation JSON."""
    columns = list(attributes.keys())
    sequence_values = {}
    scalar_values = {}

    for key, value in attributes.items():
        if isinstance(value, (list, tuple, pd.Series, np.ndarray)):
            sequence_values[key] = _json_safe_class_value(value)
        else:
            scalar_values[key] = _json_safe_class_value(value)

    sequence_lengths = {len(value) for value in sequence_values.values()}
    use_multi_row_split = (
        bool(sequence_lengths)
        and len(sequence_lengths) == 1
        and next(iter(sequence_lengths)) > 1
    )

    if use_multi_row_split:
        row_count = next(iter(sequence_lengths))
        data = []
        for row_index in range(row_count):
            row = []
            for column in columns:
                if column in sequence_values:
                    row.append(sequence_values[column][row_index])
                else:
                    row.append(scalar_values[column])
            data.append(row)
        index = list(range(row_count))
    else:
        data = [[
            sequence_values[column] if column in sequence_values else scalar_values[column]
            for column in columns
        ]]
        index = [0]

    return {
        "index": index,
        "columns": columns,
        "data": data,
    }


def class_to_dict(cls):
    """
    Recursively converts a class hierarchy into split-oriented JSON payloads.
    Nested classes remain nested mappings, while leaf classes become split
    payloads with JSON-safe values.
    """
    nested_classes = {}
    leaf_attributes = {}

    for key, value in cls.__dict__.items():
        if key.startswith("__"):
            continue
        if isinstance(value, type):
            nested_classes[key] = class_to_dict(value)
            continue
        leaf_attributes[key] = value

    if nested_classes:
        if leaf_attributes:
            nested_classes["_class_values"] = _class_attrs_to_split_payload(leaf_attributes)
        return nested_classes

    return _class_attrs_to_split_payload(leaf_attributes)


# ============================================================================
# MODULE 1: GLOBAL CLASS DEFINITIONS
# ============================================================================
# Contains global configuration classes for model assumptions, area program,
# land acquisition, vertical construction, soft costs, escrow, and financing.
# ============================================================================

class Global:
    class ModelAssumptions:
        model_start_date = None
        model_duration = None
        model_end_date = None
        default_date = None
    
    class FiltrationDropdowns:
        asset_id = None
        asset_name = None

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
        master_plan_efficiency = None
        developable_land_area = None
        master_plan_far = None

    class ValuationAssumptions:
        npv_calculation_start_option = None
        npv_calculation_start_date_override = None
        npv_calculation_start_date = None
        discount_rate = None
        mirr_finance_rate = None
        mirr_reinvestment_rate = None
        irr_calculation_option = None

    class AreaProgram:
        title_deed_area = None
        master_plan_efficiency = None
        developable_land_area = None
        master_plan_far = None

    class LandAcquisitionCostAssumptions:

        acquisition_date = None
        cost_per_sqm = None
        transaction_date = None
        acquisition_profile = None
        acquisition_escalation = None

    class AcquisitionTransactionCostAssumptions:
        # Legal Cost
        legal_cost_transaction_date = None
        legal_cost_calculation_approach = None
        legal_cost_ad_hoc_amount = None
        legal_cost_allocation_basis = None
        legal_cost_cost_percentage = None
        legal_cost_cost_per_sqm = None
        legal_cost_cost_basis = None
        legal_cost_escalation_profile = None

        # Agency Cost
        agency_cost_transaction_date = None
        agency_cost_calculation_approach = None
        agency_cost_ad_hoc_amount = None
        agency_cost_allocation_basis = None
        agency_cost_cost_percentage = None
        agency_cost_cost_per_sqm = None
        agency_cost_cost_basis = None
        agency_cost_escalation_profile = None

        # Technical Cost
        technical_cost_transaction_date = None
        technical_cost_calculation_approach = None
        technical_cost_ad_hoc_amount = None
        technical_cost_allocation_basis = None
        technical_cost_cost_percentage = None
        technical_cost_cost_per_sqm = None
        technical_cost_cost_basis = None
        technical_cost_escalation_profile = None

        # Valuation Cost
        valuation_cost_transaction_date = None
        valuation_cost_calculation_approach = None
        valuation_cost_ad_hoc_amount = None
        valuation_cost_allocation_basis = None
        valuation_cost_cost_percentage = None
        valuation_cost_cost_per_sqm = None
        valuation_cost_cost_basis = None
        valuation_cost_escalation_profile = None

        # Due Diligence Cost
        due_diligence_cost_transaction_date = None
        due_diligence_cost_calculation_approach = None
        due_diligence_cost_ad_hoc_amount = None
        due_diligence_cost_allocation_basis = None
        due_diligence_cost_cost_percentage = None
        due_diligence_cost_cost_per_sqm = None
        due_diligence_cost_cost_basis = None
        due_diligence_cost_escalation_profile = None

    class VerticalConstructionAssumptions:
        pass  # Dynamic attributes set at runtime for 24 phases

    # Add phase attributes dynamically for 24 phases
    for _phase_num in range(1, 25):
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_vertical_award_date', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_vertical_construction_start_date', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_vertical_construction_s_curve_', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_vertical_construction_esclation_profile', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_contractor_void_period', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_asset_handover_void_period', None)
        setattr(VerticalConstructionAssumptions, f'phase_{_phase_num}_payment_follows_s_curve', None)

    class DLPInsurance:
        calculation_approach = None
        percentage_of_vertical = None
        cost_per_sqm = None
        cost_basis = None
        dlp_profile = None
        escalation_profile = None

    class VoidPeriodOpex:
        void_period_opex_calculation_approach = None
        escalation_profile = None
        percentage_of_vertical_construction = None
        cost_per_sqm = None
        cost_basis = None

    class SoftCostAssumptions:
        # Design Cost
        design_cost_calculation_approach = None
        design_cost_percentage_of_vertical_construction = None
        design_cost_cost_per_sqm = None
        design_cost_cost_basis = None
        design_cost_cost_start_date = None
        design_cost_profiles = None
        design_cost_escalation_profile = None

        # Permitting Cost
        permitting_cost_calculation_approach = None
        permitting_cost_percentage_of_vertical_construction = None
        permitting_cost_cost_per_sqm = None
        permitting_cost_cost_basis = None
        permitting_cost_cost_start_date = None
        permitting_cost_profiles = None
        permitting_cost_escalation_profile = None

        # Supervision Cost
        supervision_cost_calculation_approach = None
        supervision_cost_percentage_of_vertical_construction = None
        supervision_cost_cost_per_sqm = None
        supervision_cost_cost_basis = None
        supervision_cost_cost_start_date = None
        supervision_cost_profiles = None
        supervision_cost_escalation_profile = None

        # PM Fee
        pm_fees_calculation_approach = None
        pm_fees_percentage_of_vertical_construction = None
        pm_fees_cost_per_sqm = None
        pm_fees_cost_basis = None
        pm_fees_cost_start_date = None
        pm_fees_profiles = None
        pm_fees_escalation_profile = None

        # Contingency
        contingency_calculation_approach = None
        contingency_percentage_of_vertical_construction = None
        contingency_cost_per_sqm = None
        contingency_cost_basis = None
        contingency_cost_start_date = None
        contingency_profiles = None
        contingency_escalation_profile = None

    class CorporateOverheadCost:
        # Salaries
        salaries_cost_basis = None
        salaries_hard_cost = None
        salaries_design_cost = None
        salaries_supervision_cost = None
        salaries_permitting_cost = None
        salaries_pm_fees = None
        salaries_contingency_cost = None
        salaries_percentage_of_cost_basis = None
        salaries_percentage_capitalized = None

        # IT Services
        it_services_cost_basis = None
        it_services_hard_cost = None
        it_services_design_cost = None
        it_services_supervision_cost = None
        it_services_permitting_cost = None
        it_services_pm_fees = None
        it_services_contingency_cost = None
        it_services_percentage_of_cost_basis = None
        it_services_percentage_capitalized = None

        # Office Rent & Utilities
        office_rent_and_utilities_cost_basis = None
        office_rent_and_utilities_hard_cost = None
        office_rent_and_utilities_design_cost = None
        office_rent_and_utilities_supervision_cost = None
        office_rent_and_utilities_permitting_cost = None
        office_rent_and_utilities_pm_fees = None
        office_rent_and_utilities_contingency_cost = None
        office_rent_and_utilities_percentage_of_cost_basis = None
        office_rent_and_utilities_percentage_capitalized = None

        # Professional Services
        professional_services_cost_basis = None
        professional_services_hard_cost = None
        professional_services_design_cost = None
        professional_services_supervision_cost = None
        professional_services_permitting_cost = None
        professional_services_pm_fees = None
        professional_services_contingency_cost = None
        professional_services_percentage_of_cost_basis = None
        professional_services_percentage_capitalized = None

        # Marketing
        marketing_cost_basis = None
        marketing_hard_cost = None
        marketing_design_cost = None
        marketing_supervision_cost = None
        marketing_permitting_cost = None
        marketing_pm_fees = None
        marketing_contingency_cost = None
        marketing_percentage_of_cost_basis = None
        marketing_percentage_capitalized = None

        # Sales Cost
        sales_cost_cost_basis = None
        sales_cost_hard_cost = None
        sales_cost_design_cost = None
        sales_cost_supervision_cost = None
        sales_cost_permitting_cost = None
        sales_cost_pm_fees = None
        sales_cost_contingency_cost = None
        sales_cost_percentage_of_cost_basis = None
        sales_cost_percentage_capitalized = None

        # Additional Expenses
        additonal_expenses_cost_basis = None
        additonal_expenses_hard_cost = None
        additonal_expenses_design_cost = None
        additonal_expenses_supervision_cost = None
        additonal_expenses_permitting_cost = None
        additonal_expenses_pm_fees = None
        additonal_expenses_contingency_cost = None
        additonal_expenses_percentage_of_cost_basis = None
        additonal_expenses_percentage_capitalized = None

    class SalesInputs:
        sales_sales_start_date = None
        sales_sales_cost_per_sqm = None
        sales_sales_phasing_profile = None
        sales_sales_escalation_profile = None

    class SalesandMarketingCost:
        # Sales Cost
        sales_cost_calculation_approach = None
        sales_cost_percentage_of_sales_value = None
        sales_cost_cost_per_sqm = None
        sales_cost_cost_basis = None
        sales_cost_profiles = None
        sales_cost_escalation_profile = None

        # Marketing Cost
        marketing_cost_calculation_approach = None
        marketing_cost_percentage_of_sales_value = None
        marketing_cost_cost_per_sqm = None
        marketing_cost_cost_basis = None
        marketing_cost_profiles = None
        marketing_cost_escalation_profile = None

    class EscrowMechanism:
        # Installment Milestones
        downpayment_construction_milestone = None
        downpayment_payment_into_escrow = None
        downpayment_cumulative_payment = None
        first_installment_construction_milestone = None
        first_installment_payment_into_escrow = None
        first_installment_cumulative_payment = None
        second_installment_construction_milestone = None
        second_installment_payment_into_escrow = None
        second_installment_cumulative_payment = None
        third_installment_construction_milestone = None
        third_installment_payment_into_escrow = None
        third_installment_cumulative_payment = None
        fourth_installment_construction_milestone = None
        fourth_installment_payment_into_escrow = None
        fourth_installment_cumulative_payment = None
        fifth_installment_construction_milestone = None
        fifth_installment_payment_into_escrow = None
        fifth_installment_cumulative_payment = None
        sixth_installment_construction_milestone = None
        sixth_installment_payment_into_escrow = None
        sixth_installment_cumulative_payment = None

        # Other Escrow parameters
        retention_reserve_retention_reserve = None
        hard_cost_hard_cost = None
        admin_and_soft_cost_admin_and_soft_cost = None
        approval_duration_approval_duration = None
        retention_release_grace_period_retention_release_grace_period = None
        last_year_release_option_last_year_release_option = None
        last_year_release_post_construction_last_year_release_post_construction = None

        # Escrow Applicability by Asset Category
        # Maps asset category to Yes/No for escrow applicability
        escrow_applicability_residential_units = None
        escrow_applicability_residential_land = None
        escrow_applicability_commercial_land = None
        escrow_applicability_retail = None
        escrow_applicability_schools = None
        escrow_applicability_office = None
        escrow_applicability_hospitality = None
        escrow_applicability_logistics = None
        escrow_applicability_cec = None
        escrow_applicability_canal = None
        escrow_applicability_public_amenities = None
        escrow_applicability_placeholder_1 = None
        escrow_applicability_placeholder_2 = None
        escrow_applicability_placeholder_3 = None
        escrow_applicability_placeholder_4 = None
        
        # Escrow Reallocation & Fees
        escrow_applicability_reallocation_option = None
        escrow_applicability_escrow_set_up_fee = None

    class CostAllocationInputs:
        public_amenity_cost = None
        cec_cost = None
        canal_cost = None
    
    class OtherIncomeandExpenses:
        government_subsidies_start_date = None
        government_subsidies_duration = None
        government_subsidies_calculation_approach = None
        government_subsidies_cost_basis = None
        government_subsidies_percent_of_revenue = None
        government_subsidies_cost_per_sqm = None
        government_subsidies_escalation_profile = None
        
        other_income_1_start_date = None
        other_income_1_duration = None
        other_income_1_calculation_approach = None
        other_income_1_cost_basis = None
        other_income_1_percent_of_revenue = None
        other_income_1_cost_per_sqm = None
        other_income_1_escalation_profile = None
        
        other_income_2_start_date = None
        other_income_2_duration = None
        other_income_2_calculation_approach = None
        other_income_2_cost_basis = None
        other_income_2_percent_of_revenue = None
        other_income_2_cost_per_sqm = None
        other_income_2_escalation_profile = None
        
        other_expense_1_start_date = None
        other_expense_1_duration = None
        other_expense_1_calculation_approach = None
        other_expense_1_cost_basis = None
        other_expense_1_percent_of_revenue = None
        other_expense_1_cost_per_sqm = None
        other_expense_1_escalation_profile = None
        
        other_expense_2_start_date = None
        other_expense_2_duration = None
        other_expense_2_calculation_approach = None
        other_expense_2_cost_basis = None
        other_expense_2_percent_of_revenue = None
        other_expense_2_cost_per_sqm = None
        other_expense_2_escalation_profile = None
        
        other_expense_3_start_date = None
        other_expense_3_duration = None
        other_expense_3_calculation_approach = None
        other_expense_3_cost_basis = None
        other_expense_3_percent_of_revenue = None
        other_expense_3_cost_per_sqm = None
        other_expense_3_escalation_profile = None
    
    class AssetLevelFundingAssumptions:
        # Term Loan Assumptions
        term_loan_assumptions_debt_drawdown_date = None
        term_loan_assumptions_term_loan_amount_calculation_approach = None
        term_loan_assumptions_loan_amount_percent_of_dev_cost = None
        term_loan_assumptions_loan_amount_as_ad_hoc_amount = None
        term_loan_assumptions_loan_term = None
        term_loan_assumptions_grace_period = None
        term_loan_assumptions_base_rate_pa = None
        term_loan_assumptions_credit_spread_pa = None
        term_loan_assumptions_debt_arrangement_fees = None
        term_loan_assumptions_baloon_payment = None
        term_loan_assumptions_amotized_loan_amount = None
        term_loan_assumptions_term_loan_interest_capitalization = None
        term_loan_assumptions_debt_arrangement_fees_capitalization = None

        # Asset Debt Revolver Assumptions
        asset_debt_revolver_assumptions_revolver_facility_start_date = None
        asset_debt_revolver_assumptions_revolver_facility_duration = None
        asset_debt_revolver_assumptions_revolver_limit = None
        asset_debt_revolver_assumptions_base_rate_pa = None
        asset_debt_revolver_assumptions_credit_spread_pa = None
        asset_debt_revolver_assumptions_debt_arrangement_fees = None
        asset_debt_revolver_assumptions_commitment_fees = None
        asset_debt_revolver_assumptions_interest_and_fees_capitalization = None

    class ProjectLevelFundingAssumptions:
        # Term Loan Assumptions
        term_loan_assumptions_debt_drawdown_date = None
        term_loan_assumptions_term_loan_amount_calculation_approach = None
        term_loan_assumptions_loan_amount_as_percentage_of_dev_cost = None
        term_loan_assumptions_loan_amount_as_ad_hoc_amount = None
        term_loan_assumptions_loan_term = None
        term_loan_assumptions_grace_period = None
        term_loan_assumptions_base_rate_pa = None
        term_loan_assumptions_credit_spread_pa = None
        term_loan_assumptions_debt_arrangement_fees = None
        term_loan_assumptions_baloon_payment = None
        term_loan_assumptions_amotized_loan_amount = None
        term_loan_assumptions_term_loan_interest_capitalization = None
        term_loan_assumptions_debt_arrangement_fees_capitalization = None

        # Project Debt Revolver Assumptions
        project_debt_revolver_assumptions_revolver_facility_start_date = None
        project_debt_revolver_assumptions_revolver_facility_duration = None
        project_debt_revolver_assumptions_revolver_limit = None
        project_debt_revolver_assumptions_base_rate_pa = None
        project_debt_revolver_assumptions_credit_spread_pa = None
        project_debt_revolver_assumptions_debt_arrangement_fees = None
        project_debt_revolver_assumptions_commitment_fees = None
        project_debt_revolver_assumptions_interest_and_fees_capitalization = None


# ============================================================================
# MODULE 2: ASSET CLASS DEFINITIONS
# ============================================================================
# Contains asset-level configuration classes for project details, land area,
# business model, acquisition, vertical development, disposal, and financing.
# ============================================================================

class Asset:
    class ProjectDetails:
        
        number = None
        project_name = None
        region = None
        city = None
        asset_class = None
        sub_category = None
        typology = None
        sub_typology = None
        construction_phase = None
        asset_name = None
        asset_unique_identifier = None
        asset_devco_inclusion = None
        devco_output_inclusion = None

    class LandAreaProgram:
        units = None
        developable_land_area = None
        developable_land_area_per_unit = None
        master_plan_efficiency = None
        gross_land_area = None
        gross_land_area_per_unit = None
        site_coverage_ratio = None
        site_coverage_area = None
        gross_floor_area = None
        gfa_per_unit = None
        built_up_area = None
        built_up_area_per_unit = None
        floor_plan_efficiency = None
        total_nsa__gla = None
        nsa__gla_per_unit = None
        floor_area_ratio = None
        parking_bays = None

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
    
    class BusinessModel:
        funding_type = None
        strike_price = None
        contract_date = None
        exit_counterparty = None

    class AcquisitionModule:

        acquisition_module_override = None
        acquisition_date = None
        acquisition_payment_start_date = None
        acquisition_payment_profile_option = None
        acquisition_payment_profile = None
        acquisition_payment_duration = None
        acquisition_payment_schedule = None
        acquisition_price = None
        escalation_profile = None
        payment_type = None

        legal_actual_payment_date = None
        legal_cost_override = None

        agency_actual_payment_date = None
        agency_cost_override = None

        technical_actual_payment_date = None
        technical_cost_override = None

        valuation_actual_payment_date = None
        valuation_cost_override = None

        due_diligence_actual_payment_date = None
        due_diligence_cost_override = None

    class VerticalDevelopmentModule:

        vd_override = None
        award_date = None
        construction_start_date = None
        s_curve_option = None
        vd_pre_defined_s_curve = None
        pre_defined_duration = None
        vd_user_defined_duration = None
        user_defined_s_curve = None
        contractor_void_period = None
        handover_from_contractor = None
        asset_handover_void_period = None
        asset_handover_date = None
        vd_payment_start_date = None
        vd_payment_duration = None
        vd_payment_schedule = None
        vd_cost_basis = None
        vd_cost_per_sqm = None
        vd_escalation_profile = None

        void_period_opex_override = None
        void_period_start_date = None
        void_period = None
        void_period_opex_payment_schedule = None
        void_period_opex_calculation_approach = None
        void_period_opex_escalation_profile = None
        void_period_opex_rate_of_vertical_construction = None
        void_period_opex_ad_hoc_amount = None
        void_period_opex_cost_per_sqm = None
        void_period_opex_cost_basis = None

        design_cost_override = None
        design_start_date = None
        design_duration = None
        design_cost_payment_schedule = None
        design_cost_calculation_approach = None
        design_cost_escalation_profile = None
        design_cost_percent_of_vertical_construction = None
        design_cost_cost_per_sqm = None
        design_cost_cost_basis = None

        permitting_cost_override = None
        permitting_cost_start_date = None
        permitting_cost_duration = None
        permitting_cost_payment_schedule = None
        permitting_cost_calculation_approach = None
        permitting_cost_escalation_profile = None
        permitting_cost_percent_of_vertical_construction = None
        permitting_cost_cost_per_sqm = None
        permitting_cost_cost_basis = None

        supervision_override = None
        supervision_start_date = None
        supervision_duration = None
        supervision_payment_schedule = None
        supervision_calculation_approach = None
        supervision_escalation_profile = None
        supervision_percent_of_vertical_construction = None
        supervision_cost_per_sqm = None
        supervision_cost_basis = None

        pm_fees_override = None
        pm_fees_start_date = None
        pm_fees_duration = None
        pm_fees_payment_schedule = None
        pm_fees_calculation_approach = None
        pm_fees_escalation_profile = None
        pm_fees_percent_of_vertical_development = None
        pm_fees_cost_per_sqm = None
        pm_fees_cost_basis = None

        contingency_override = None
        contingency_start_date = None
        contingency_duration = None
        contingency_payment_schedule = None
        contingency_calculation_approach = None
        contingency_escalation_profile = None
        contingency_percent_of_vertical_construction = None
        contingency_cost_per_sqm = None
        contingency_cost_basis = None

        dlp_insurance_override = None
        dlp_insurance_start_date = None
        dlp_insurance_duration = None
        dlp_insurance_payment_schedule = None
        dlp_insurance_calculation_approach = None
        dlp_insurance_escalation_profile = None
        dlp_insurance_percent_of_vertical_cost = None
        dlp_insurance_cost_per_sqm = None
        dlp_insurance_cost_basis = None

    class CorporateOverhead:
        # Salaries
        coh_salaries_override = None
        coh_salaries_cost_start_date = None
        coh_salaries_cost_duration = None
        coh_salaries_cost_schedule = None
        coh_salaries_ad_hoc_amount = None
        coh_salaries_percent_capitalized = None

        # IT Services
        coh_it_services_override = None
        coh_it_services_cost_start_date = None
        coh_it_services_cost_duration = None
        coh_it_services_cost_schedule = None
        coh_it_services_ad_hoc_amount = None
        coh_it_services_percent_capitalized = None

        # Office Rent & Utilities
        coh_office_rent_and_utilities_override = None
        coh_office_rent_and_utilities_cost_start_date = None
        coh_office_rent_and_utilities_cost_duration = None
        coh_office_rent_and_utilities_cost_schedule = None
        coh_office_rent_and_utilities_ad_hoc_amount = None
        coh_office_rent_and_utilities_percent_capitalized = None

        # Professional Services
        coh_professional_services_override = None
        coh_professional_services_cost_start_date = None
        coh_professional_services_cost_duration = None
        coh_professional_services_cost_schedule = None
        coh_professional_services_ad_hoc_amount = None
        coh_professional_services_percent_capitalized = None

        # Marketing
        coh_marketing_override = None
        coh_marketing_cost_start_date = None
        coh_marketing_cost_duration = None
        coh_marketing_cost_schedule = None
        coh_marketing_ad_hoc_amount = None
        coh_marketing_percent_capitalized = None

        # Sales Cost
        coh_sales_cost_override = None
        coh_sales_cost_cost_start_date = None
        coh_sales_cost_cost_duration = None
        coh_sales_cost_cost_schedule = None
        coh_sales_cost_ad_hoc_amount = None
        coh_sales_cost_percent_capitalized = None

        # Additional Expenses
        coh_additional_exp_override = None
        coh_additional_exp_cost_start_date = None
        coh_additional_exp_cost_duration = None
        coh_additional_exp_cost_schedule = None
        coh_additional_exp_ad_hoc_amount = None
        coh_additional_exp_percent_capitalized = None

    class Disposal:

        sales_override = None
        escrow_applicability = None
        escrow_sales_start_date = None
        sales_value = None
        sales_phasing_option = None
        sales_phasing_profile = None
        sales_escalation_profile = None
        sales_duration = None
        sales_phasing_link = None

        sales_start_date = None
        sales_collection_duration = None
        sales_collection_phasing = None

        sales_cost_override = None
        sales_cost_cost_start_date = None
        sales_cost_user_defined_phasing = None
        sales_cost_pre_defined_profile = None
        sales_cost_pre_defined_duration = None
        sales_cost_cost_duration = None
        sales_cost_user_defined_s_curve = None
        sales_cost_calculation_approach = None
        sales_cost_escalation_profile = None
        sales_cost_percent_of_sales_value = None
        sales_cost = None
        sales_cost_cost_basis = None

        marketing_cost_override = None
        marketing_cost_cost_start_date = None
        marketing_cost_user_defined_phasing = None
        marketing_cost_pre_defined_profile = None
        marketing_cost_pre_defined_duration = None
        marketing_cost_cost_duration = None
        marketing_cost_user_defined_s_curve = None
        marketing_cost_calculation_approach = None
        marketing_cost_escalation_profile = None
        marketing_cost_percent_of_sales_value = None
        marketing_cost = None
        marketing_cost_cost_basis = None

    class CostAllocation:
        public_amenities = None
        cec = None
        canal = None

    class PARecovery:
        start_date = None
        duration = None
        schedule = None
        recovery_percent = None
    
    class OtherIncomeandExpense:
        governement_subsidies_override = None
        governement_subsidies_start_date = None
        governement_subsidies_duration = None
        governement_subsidies_phasing = None
        governement_subsidies_calculation_approach = None
        governement_subsidies_escalation_profile = None
        governement_subsidies_percent = None
        governement_subsidies_ad_hoc_amount = None
        governement_subsidies_sarsqm = None
        governement_subsidies_cost_basis = None
        
        other_income_1_override = None
        other_income_1_start_date = None
        other_income_1_duration = None
        other_income_1_phasing = None
        other_income_1_calculation_approach = None
        other_income_1_escalation_profile = None
        other_income_1_percent = None
        other_income_1_ad_hoc_amount = None
        other_income_1_sarsqm = None
        other_income_1_cost_basis = None

        other_income_2_override = None
        other_income_2_start_date = None
        other_income_2_duration = None
        other_income_2_phasing = None
        other_income_2_calculation_approach = None
        other_income_2_escalation_profile = None
        other_income_2_percent = None
        other_income_2_ad_hoc_amount = None
        other_income_2_sarsqm = None
        other_income_2_cost_basis = None

        other_expense_1_override = None
        other_expense_1_start_date = None
        other_expense_1_duration = None
        other_expense_1_phasing = None
        other_expense_1_calculation_approach = None
        other_expense_1_escalation_profile = None
        other_expense_1_percent = None
        other_expense_1_ad_hoc_amount = None
        other_expense_1_sarsqm = None
        other_expense_1_cost_basis = None

        other_expense_2_override = None
        other_expense_2_start_date = None
        other_expense_2_duration = None
        other_expense_2_phasing = None
        other_expense_2_calculation_approach = None
        other_expense_2_escalation_profile = None
        other_expense_2_percent = None
        other_expense_2_ad_hoc_amount = None
        other_expense_2_sarsqm = None
        other_expense_2_cost_basis = None

        other_expense_3_override = None
        other_expense_3_start_date = None
        other_expense_3_duration = None
        other_expense_3_phasing = None
        other_expense_3_calculation_approach = None
        other_expense_3_escalation_profile = None
        other_expense_3_percent = None
        other_expense_3_ad_hoc_amount = None
        other_expense_3_sarsqm = None
        other_expense_3_cost_basis = None

    class Financing:
        funding_type = None
        asset_financing_override = None
        revolver_facility_start_date = None
        revolver_facility_period = None
        revolver_limit = None
        base_rate_profile_revolver = None
        credit_spread_percent_revolver = None
        revolver_debt_arrangement_fees = None
        revolver_commitment_fees = None
        interest_and_fees_capitalized = None
        
        term_loan_facility_start_date = None
        term_loan_grace_period = None
        term_loan_facility_period = None
        term_loan_amount_approach = None
        term_loan_ad_hoc_amount = None
        percent_of_development_cost = None
        base_rate_profile_term_loan = None
        credit_spread_percent_term_loan = None
        balloon_payment = None
        amortization_percent = None
        term_loan_interest_capitalized = None
        ftl_debt_arrangement_fees = None
        debt_arrangement_fees_capitalized = None

# ============================================================================
# MODULE 3: MAIN CALCULATION ENGINE
# ============================================================================
# Contains the main wrapper function that orchestrates all calculations.
# Sub-modules within:
#   - 3.1: Input Processing Functions
#   - 3.2: Utility Functions (Timeline, Profiles, Escalation)
#   - 3.3: Generic Calculation Functions
#   - 3.4: Acquisition & Transaction Cost Functions
#   - 3.5: Vertical Development Cost Functions
#   - 3.6: Soft Cost & DLP Insurance Functions
#   - 3.7: Corporate Overhead Functions
#   - 3.8: Sales Revenue Calculation
#   - 3.9: Escrow Mechanism Functions
#   - 3.10: Disposal/Sales Revenue Functions
#   - 3.11: Forward Funding & Forward Sales Functions
#   - 3.12: Other Income and Expenses Functions
#   - 3.13: Cost Allocation Submodule
#   - 3.14: Financing Module
#       - 3.14.1: Asset Level Financing
#       - 3.14.2: Project Level Financing
#   - 3.15: Cashflow Statement Generation
# ============================================================================

def wrapper_for_vars(payload):
    """
    Main wrapper function that orchestrates the entire DevCo cashflow model calculation.
    
    This function processes input data from Excel named ranges and calculates all
    components of a development company feasibility model including:
    - Land acquisition costs and timing
    - Vertical construction costs (24 phases with S-curves)
    - Soft costs (design, permitting, supervision, project management)
    - Contingency costs
    - DLP Insurance
    - Escrow mechanism and milestone-based payments
    - Disposal/Sales revenue and costs
    - Forward Funding (milestone-based payments linked to construction progress)
    - Forward Sales (lump-sum payment at asset handover)
    - Corporate overhead allocations
    - Cost allocation (Public Amenities, CEC, Canal)
    - Development financing (asset-level and project-level)
    - Cashflow statements and valuations
    
    Args:
        payload (list): JSON payload containing named ranges from Excel.
            Expected format: List of dicts with 'name' and 'values' keys.
            template_asset_timeline
    Returns:
        dict: Final output containing:
            - exceloutput: Monthly and annual cashflow outputs
            - jvoutput: JV-filtered output payload
            - consolidationoutput: Non-JV filtered output payload
            - timing_summary: End-of-run timing summary with rows and table text
            
    Raises:
        Exception: Prints error message with traceback if calculation fails.
        
    Example:
        >>> result = wrapper_for_vars(excel_payload)
        >>> monthly_data = result['monthly_dfs']
        >>> annual_data = result['annual_dfs']
    """
    try:
        _start_time = time.perf_counter()
        _section_time = _start_time
        _model_started_at = time.strftime('%Y-%m-%d %H:%M:%S')
        _timing_measurements = []
        landco_capex = landco_capex_module.fninitialising_all_values(payload,is_save=False)

        def _record_timing(section_name):
            nonlocal _section_time
            current_time = time.perf_counter()
            _timing_measurements.append({
                "step": len(_timing_measurements) + 1,
                "section": section_name,
                "elapsed_seconds": round(current_time - _section_time, 4),
                "cumulative_seconds": round(current_time - _start_time, 4),
            })
            _section_time = current_time

        _record_timing("LandCo CapEx Module")

        def _format_timing_table(rows):
            headers = ("Step", "Section", "Elapsed (s)", "Cumulative (s)")
            formatted_rows = [
                (
                    str(row["step"]),
                    row["section"],
                    f'{row["elapsed_seconds"]:.4f}',
                    f'{row["cumulative_seconds"]:.4f}',
                )
                for row in rows
            ]
            widths = []
            for column_index, header in enumerate(headers):
                column_lengths = [len(header)]
                column_lengths.extend(len(row[column_index]) for row in formatted_rows)
                widths.append(max(column_lengths))

            def _format_row(values):
                return "| " + " | ".join(
                    value.ljust(widths[idx]) for idx, value in enumerate(values)
                ) + " |"

            divider = "+-" + "-+-".join("-" * width for width in widths) + "-+"
            table_lines = [divider, _format_row(headers), divider]
            table_lines.extend(_format_row(row) for row in formatted_rows)
            table_lines.append(divider)
            return "\n".join(table_lines)

        def _finalize_timing_summary(final_section_name):
            _record_timing(final_section_name)
            total_duration = _timing_measurements[-1]["cumulative_seconds"] if _timing_measurements else 0.0
            timing_table = _format_timing_table(_timing_measurements)
            summary_text = "\n".join([
                "Timing Summary",
                f"Started at: {_model_started_at}",
                f"Total duration (s) (DevCo): {round(total_duration, 4):.4f}",
                timing_table,
            ])
            return {
                "started_at": _model_started_at,
                "total_duration_seconds": round(total_duration, 4),
                "rows": _timing_measurements,
                "table": timing_table,
                "summary_text": summary_text,
            }
        
        # ========================================================================
        # EXPORT CONFIGURATION FLAGS
        # ========================================================================
        # Set to True to export the corresponding submodule's data to Excel
        # Each submodule will create a separate Excel file in the current directory
        # Export happens inline within each submodule when flag is True
        # ========================================================================
        
        _EXPORT_FLAGS = {
            # Land Acquisition Module (Split into 2 files)
            'land_acquisition_cost': False,      # Land Acquisition Cost (base cost, escalation, phasing)
            'land_acquisition_txn': False,       # Land Acquisition Transaction Costs (legal, agency, etc.)
            # Vertical Development Module
            'vertical_construction': False,      # Vertical Construction Costs (timeline, S-curve, escalation)
            # Soft Cost & DLP Module
            'soft_cost_dlp': False,              # Design, Permitting, Supervision, PM, Contingency, DLP
            'void_period_opex': False,           # Void Period OPEX during contractor & handover void
            # Escrow Module
            'escrow_mechanism': False,           # Escrow workings and milestone payments
            # Disposal/Sales Module
            'disposal_sales': False,             # Disposal/Sales Revenue & Costs
            # Forward Funding & Forward Sales Module
            'forward_funding_sales': False,      # Forward Funding & Forward Sales Cash Flows
            # Corporate Overhead Module
            'corporate_overhead': False,         # Corporate Overhead Costs (7 line items)
            # Other Income/Expense Module
            'other_income_expense': False,       # Other Income and Expenses
            # Cost Allocation Module
            'cost_allocation': False,            # PA, CEC, Canal Cost Allocation
            # Financing Module (Split into 2 files)
            'asset_level_financing': False,      # Asset Level Debt Revolver workings
            'project_level_financing': False,    # Project Level Term Loan & Revolver workings
            # Cashflow Statements
            'cashflow_statements': False,        # Cashflow from Operations, Investments, Financing
            'dashboard_data': False              # DevCo Dashboard Data
        }
        
        # ========================================================================
        # EXPORT HELPER FUNCTION
        # ========================================================================
        
        def _export_to_excel(dataframes_dict, filename, description):
            """
            Export a dictionary of DataFrames to Excel with each DataFrame as a separate sheet.
            
            Args:
                dataframes_dict (dict): Dictionary where keys are sheet names and values are DataFrames
                filename (str): Name of the Excel file (without extension)
                description (str): Description of the export for logging
            """
            try:
                excel_path = os.path.join(os.path.dirname(__file__), f'{filename}.xlsx')
                with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                    for sheet_name, df in dataframes_dict.items():
                        # Sanitize sheet name (Excel has 31 char limit)
                        safe_name = sheet_name[:31].replace("/", "-").replace("\\", "-")
                        if df is not None and isinstance(df, pd.DataFrame):
                            # styled_df = df.style.format("#,##0;(#,##0);-")
                            df.to_excel(writer, sheet_name=safe_name, index=True)
                            ws = writer.book[safe_name]
                            # Apply number format to numeric cells (skip header row and index column)
                            for row in range(2, ws.max_row + 1):
                                for col in range(2, ws.max_column + 1):
                                    cell = ws.cell(row=row, column=col)
                                    if isinstance(cell.value, (int, float)):
                                        cell.number_format = '#,##0;(#,##0);-'
                print(f"  Exported {description} to: {excel_path}")
                os.startfile(excel_path)
                return excel_path
            except Exception as e:
                print(f"  Error exporting {description}: {e}")
                return None
        
        # ========================================================================
        # SUB-MODULE 3.1: INPUT PROCESSING FUNCTIONS
        # ========================================================================
        
        def fn_read_all_named_ranges_json(payload):
            """
            Reads named ranges from a JSON input and returns a DataFrame with columns ['name', 'value'].
            The JSON is expected to be a list of dicts with keys: 'name', 'values', etc.
            - Single-cell: values[[single_value]]
            - Single-row: values[[v1, v2, ...]]
            - Single-col: values[[v1],[v2],...]
            - Multi-cell: values[r][c]
            """
            try:
                named_values = []
                for entry in payload:
                    name = entry.get("name")
                    if 'devco' not in name.lower():
                        continue 
                    values = entry.get("values")
                    # Flatten values according to dimensionality like Excel reading logic
                    # Single value cell ([[v]])
                    if isinstance(values, list):
                        if len(values) == 1 and isinstance(values[0], list):
                            if len(values[0]) == 1:
                                value = values[0][0]
                            else:
                                value = values[0]  # Single row (multiple columns)
                        elif all(isinstance(item, list) and len(item) == 1 for item in values):
                            # Single column, multiple rows: [[a],[b],[c]]
                            value = [item[0] for item in values]
                        else:
                            # Fallback: keep as is (likely a 2d multi-cell range)
                            value = values
                    else:
                        value = values
                    named_values.append((name, value))

                return pd.DataFrame(named_values, columns=["name", "value"])
            except Exception as e:
                print(f"Error in fn_read_all_named_ranges_json: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        assumptions = fn_read_all_named_ranges_json(payload)
        _assumptions_value_cache = {}
        for _named_range_name, _named_range_value in assumptions[["name", "value"]].itertuples(index=False, name=None):
            _assumptions_value_cache.setdefault(_named_range_name, _named_range_value)

        _assumption_values_cache = _assumptions_value_cache  # OPTIMIZED: alias the flattened input cache for repeated direct reads.

        # Pre-extract schedule/phasing keys for fast access throughout submodules
        _schedule_cache = {
            k: v for k, v in _assumption_values_cache.items()
            if k.startswith("s.devco.")
        }

        # OPTIMIZED: cache class-to-row index mappings once instead of rescanning attribute lists per subclass.
        _global_class_names = _assumption_values_cache.get("a.devco.global.class", [])
        _global_attr_names = _assumption_values_cache.get("a.devco.global.attribute", [])
        _global_attr_values = _assumption_values_cache.get("a.devco.global.value", [])
        _global_class_index_cache = {}
        for _global_row_idx, _global_class_name in enumerate(_global_class_names):
            _global_class_index_cache.setdefault(_global_class_name, []).append(_global_row_idx)

        # OPTIMIZED: cache asset class row groupings and inclusion flags once for reuse across all Asset subclasses.
        _asset_class_names = _assumption_values_cache.get("a.devco.class.row", [])
        _asset_attr_names = _assumption_values_cache.get("a.devco.attribute.row", [])
        _asset_attr_values = _assumption_values_cache.get("a.devco.asset.data", [])
        _asset_class_index_cache = {}
        for _asset_row_idx, _asset_class_name in enumerate(_asset_class_names):
            _asset_class_index_cache.setdefault(_asset_class_name, []).append(_asset_row_idx)
        _asset_inclusion_idx = _asset_attr_names.index("asset_devco_inclusion") if "asset_devco_inclusion" in _asset_attr_names else -1
        if _asset_inclusion_idx >= 0:
            _asset_inclusion_flags = [
                (row[_asset_inclusion_idx] == "Yes") if len(row) > _asset_inclusion_idx else False
                for row in _asset_attr_values
            ]
        else:
            _asset_inclusion_flags = [True] * len(_asset_attr_values)

        def fn_assign_global_class_attributes(cls, assumptions):
            """
            Assigns attribute values from assumptions to a Global class.
            
            Reads global class/attribute/value data from assumptions DataFrame
            and sets corresponding class attributes. Handles date conversion
            from Excel serial number format.
            
            Args:
                cls: The Global subclass to assign attributes to.
                assumptions (pd.DataFrame): DataFrame with 'name' and 'value' columns
                    containing named range data.
                    
            Raises:
                ValueError: If attribute is not defined in the class.
            """
            try:
                class_name = cls.__name__

                for i in _global_class_index_cache.get(class_name, []):
                    attr = _global_attr_names[i]
                
                    # Error control: check if attribute is defined in the class
                    if not hasattr(cls, attr):
                        raise ValueError(
                            f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                        )
                
                    # Check if the attribute name contains "date" and the value is an integer or float
                    date_exceptions = [
                        # Add other exceptions here if needed
                    ]

                    if "date" in attr.lower() and isinstance(_global_attr_values[i], (int, float)):
                        if _global_attr_values[i] == "" or _global_attr_values[i] == 0:
                            convertedval = None
                        else:
                            convertedval = datetime.fromtimestamp((_global_attr_values[i] - 25569) * 86400.0).strftime('%Y-%m-%d')
                        setattr(cls, attr, pd.to_datetime(convertedval))
                    else:
                        # Set attribute value directly
                        setattr(cls, attr, _global_attr_values[i])
            except Exception as e:
                print(f"Error in fn_assign_global_class_attributes for class {cls.__name__}: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_initialize_global_class(assumptions):
            """
            Initializes all Global subclasses with values from assumptions.
            
            Iterates through all subclasses of the Global class and assigns
            their attribute values from the assumptions DataFrame.
            
            Args:
                assumptions (pd.DataFrame): DataFrame with 'name' and 'value' columns.
            """
            try:
                # Dynamically retrieve all subclasses of the Global class
                for subclass_name in dir(Global):
                    subclass = getattr(Global, subclass_name)
                    # Check if the attribute is a class (subclass of Global)
                    if isinstance(subclass, type):
                        fn_assign_global_class_attributes(subclass, assumptions)
            except Exception as e:
                print(f"Error in fn_initialize_global_class: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_assign_asset_class_attributes(cls, assumptions):
            """
            Assigns attribute values from assumptions to an Asset class.

            Reads asset class/attribute/value data from assumptions DataFrame
            and sets corresponding class attributes as lists (one value per asset).
            Handles date conversion from Excel serial number format.
            If attr_values[idx][attr_names.index("asset_landco_inclusion")] != "Yes" or row[i] == "",
            sets the attribute value for that asset to np.nan (or pd.NaT for dates).

            Args:
                cls: The Asset subclass to assign attributes to.
                assumptions (pd.DataFrame): DataFrame with 'name' and 'value' columns.

            Raises:
                ValueError: If attribute is not defined in the class.
            """
            try:
                class_name = cls.__name__

                for i in _asset_class_index_cache.get(class_name, []):
                    attr = _asset_attr_names[i]
                    
                    # Error control: check if class name matches for this attribute
                    if not hasattr(cls, attr):
                        raise ValueError(
                            f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                        )

                    col = []
                    is_date = "date" in attr.lower()
                    for idx, row in enumerate(_asset_attr_values):
                        val = row[i]
                        if not _asset_inclusion_flags[idx] or val == "":
                            col.append(pd.NaT if is_date else np.nan)
                        elif is_date:
                            if val == 0 or val is None:
                                col.append(pd.NaT)
                            else:
                                col.append(pd.to_datetime(datetime.fromtimestamp((float(val) - 25569) * 86400.0).strftime('%Y-%m-%d')))
                        else:
                            col.append(val)
                    setattr(cls, attr, col)
            except Exception as e:
                print(f"Error in fn_assign_asset_class_attributes for class {cls.__name__}: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_initialize_asset_class(assumptions):
            """
            Initializes all Asset subclasses with values from assumptions.
            
            Iterates through all subclasses of the Asset class and assigns
            their attribute values from the assumptions DataFrame.
            
            Args:
                assumptions (pd.DataFrame): DataFrame with 'name' and 'value' columns.
            """
            try:
                # Dynamically retrieve all subclasses of the Asset class
                for subclass_name in dir(Asset):
                    subclass = getattr(Asset, subclass_name)
                    # Check if the attribute is a class (subclass of Asset)
                    if isinstance(subclass, type):
                        fn_assign_asset_class_attributes(subclass, assumptions)
            except Exception as e:
                print(f"Error in fn_initialize_asset_class: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        fn_initialize_global_class(assumptions)
        fn_initialize_asset_class(assumptions)

        _record_timing("Input processing and class initialization")
        

        # ========================================================================
        # SUB-MODULE 3.2: UTILITY FUNCTIONS (Timeline, Profiles, Escalation)
        # ========================================================================

        def fn_replace_nan(obj, fill_value=0):
            """
            Replace NaN/NaT values in a DataFrame or Series.
            - For DataFrame: Only rows where index != "" are replaced.
            - For Series: All NaN/NaT are replaced.

            Args:
                obj (pd.DataFrame or pd.Series): The object to process.
                fill_value: Value to replace NaN/NaT with (default: 0).

            Returns:
                Same type as input, with NaNs replaced as specified.
            """
            try:
                if isinstance(obj, pd.Series):
                    return obj.where(pd.notna(obj), fill_value).infer_objects(copy=False)
                elif isinstance(obj, pd.DataFrame):
                    if obj.index.dtype != object:
                        obj.index = obj.index.astype(str)
                    mask = obj.index != ""
                    if not mask.any():
                        return obj

                    df_to_replace = obj.loc[mask].copy()
                    filled_values = df_to_replace.where(pd.notna(df_to_replace), fill_value)
                    obj.loc[mask] = filled_values.infer_objects(copy=False)
                    return obj
                else:
                    raise TypeError("Input must be a pandas DataFrame or Series.")
            except Exception as e:
                print(f"Error in fn_replace_nan: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                return obj
        
        def fn_create_model_timeline(start_date, end_date, frequency):
            """
            Create a timeline DataFrame for monthly-end (ME), quarter-end (QE) or year-end (YE) periods.
            
            Args:
                start_date: Start date of the model timeline
                end_date: End date of the model timeline
                frequency: 'ME' for monthly, 'QE' for quarterly, 'YE' for yearly
                
            Returns:
                pd.DataFrame: Timeline with Period Start, Period End, Year, Month, # of Period, # of Days
            """
            try:
                freq_map_date_range = {'ME': 'ME', 'QE': 'QE', 'YE': 'YE'}
                freq_map_period = {'ME': 'M', 'QE': 'Q', 'YE': 'Y'}
                if frequency not in freq_map_date_range:
                    raise ValueError("Unsupported frequency. Use 'ME', 'QE' or 'YE'.")

                pandas_freq_date_range = freq_map_date_range[frequency]
                pandas_freq_period = freq_map_period[frequency]
                date_range = pd.date_range(start=start_date, end=end_date, freq=pandas_freq_date_range)

                # Convert to PeriodIndex for robust period start/end and day counts
                periods = date_range.to_period(pandas_freq_period)
                period_start = periods.start_time
                period_end = periods.end_time
                number_of_days = (period_end - period_start).days + 1

                df = pd.DataFrame({
                    'Period Start': period_start,
                    'Period End': period_end,
                    'Year': period_end.year,
                    'Month': period_end.month,
                    '# of Days': number_of_days
                })
                df['# of Period'] = df.index + 1

                # Reorder columns to make '# of Period' the 5th column
                df = df[['Period Start', 'Period End', 'Year', 'Month', '# of Period', '# of Days']]

                return df
            except Exception as e:
                print(f"Error in fn_create_model_timeline: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # Ensure model_start_date is the first day of the month   
        Global.ModelAssumptions.model_start_date = pd.Timestamp(Global.ModelAssumptions.model_start_date).replace(day=1)

        # Ensure model_end_date is the last day of the month
        Global.ModelAssumptions.model_end_date = pd.Timestamp(Global.ModelAssumptions.model_end_date) + pd.offsets.MonthEnd(0)
        
        model_timeline_me = fn_create_model_timeline(
            Global.ModelAssumptions.model_start_date,
            Global.ModelAssumptions.model_end_date,
            "ME",
        )
        model_timeline_ye = fn_create_model_timeline(
            Global.ModelAssumptions.model_start_date,
            Global.ModelAssumptions.model_end_date,
            "YE",
        )
        model_timeline_qe = fn_create_model_timeline(
            Global.ModelAssumptions.model_start_date,
            Global.ModelAssumptions.model_end_date,
            "QE",
        )
        
        # Create empty DataFrame with assets as rows and timeline periods as columns
        timeline_periods = model_timeline_me["# of Period"]
        
        # Cache frequently used values for performance optimization
        _template_index = range(0, len(Asset.ProjectDetails.number), 1)
        _template_columns = model_timeline_me.index
        _n_assets = len(Asset.ProjectDetails.number)
        _n_periods = len(model_timeline_me)
        _period_starts = model_timeline_me['Period Start'].values
        _period_ends = model_timeline_me['Period End'].dt.normalize().values
        _period_months = model_timeline_me['Period Start'].dt.month.values
        _period_years = model_timeline_me["Year"].values
        _unique_years = list(model_timeline_me["Year"].unique())
        # Pre-compute date-only array and year lookup for fast binary search
        _period_starts_days = _period_starts.astype('datetime64[D]')
        _period_starts_broadcast = pd.to_datetime(_period_starts, errors="coerce").to_numpy().reshape(1, -1)
        _year_to_idx = {y: i for i, y in enumerate(_unique_years)}
        _period_start_to_idx = {
            period_start: idx
            for idx, period_start in enumerate(pd.to_datetime(_period_starts, errors="coerce"))
        }
        _predefined_profile_lookup_cache = {}  # OPTIMIZED: cache resolved pre-defined profiles once per wrapper execution.
        _predefined_profile_lookup = _predefined_profile_lookup_cache
        _predefined_profile_row_cache = {}
        _predefined_profile_row_cache_lock = threading.Lock()  # OPTIMIZED: protect shared row cache writes across worker tasks.
        _user_defined_profile_row_cache = {}
        _user_defined_profile_row_cache_lock = threading.Lock()  # OPTIMIZED: protect shared row cache writes across worker tasks.
        _escalation_profile_compute_cache = {}  # OPTIMIZED: memoize per-profile escalation curves for reuse across modules.
        _monthly_escalation_curve_cache = _escalation_profile_compute_cache
        _escalation_profile_compute_lock = threading.Lock()  # OPTIMIZED: protect shared escalation-curve cache writes.
        _monthly_escalation_result_cache = {}
        _monthly_escalation_result_cache_lock = threading.Lock()  # OPTIMIZED: protect shared escalation-matrix cache writes.
        _start_flag_value_cache = {}
        _transaction_flag_value_cache = {}
        _row_sum_cache = {}  # OPTIMIZED: reuse axis-1 sums and max values for shared DataFrames.
        _row_sum_cache_lock = threading.Lock()  # OPTIMIZED: protect aggregate cache writes from concurrent helper calls.
        _max_parallel_workers = max(1, min(4, os.cpu_count() or 1))
        _shared_executor = ExecutorManager.get_thread_executor(max_workers=max(2, min(8, os.cpu_count() or 1)))

        def _build_numeric_basis_series(values):
            # OPTIMIZED: normalize static area and unit bases once so later cost modules can reuse aligned numeric Series.
            return pd.to_numeric(pd.Series(values if values else [0.0] * _n_assets, index=_template_index), errors="coerce").fillna(0.0)

        # OPTIMIZED: cache reusable allocation and area basis series once after asset initialization.
        _allocation_basis_series_cache = {
            "Gross Land Area": _build_numeric_basis_series(Asset.LandAreaProgram.gross_land_area),
            "Developable Land Area": _build_numeric_basis_series(Asset.LandAreaProgram.developable_land_area),
            "Gross Floor Area": _build_numeric_basis_series(Asset.LandAreaProgram.gross_floor_area),
            "Built Up Area": _build_numeric_basis_series(Asset.LandAreaProgram.built_up_area),
            "Units": _build_numeric_basis_series(Asset.LandAreaProgram.units),
            "Total NSA/GLA": _build_numeric_basis_series(getattr(Asset.LandAreaProgram, "total_nsa__gla", None)),
        }
        _allocation_basis_array_cache = {
            basis_name: basis_series.to_numpy(dtype=float, copy=False)
            for basis_name, basis_series in _allocation_basis_series_cache.items()
        }
        _transaction_cost_basis_series_cache = {
            basis_name: basis_series
            for basis_name, basis_series in _allocation_basis_series_cache.items()
            if basis_name in {"Gross Land Area", "Developable Land Area", "Gross Floor Area", "Built Up Area", "Units"}
        }
        _soft_cost_sqm_basis_series_cache = {
            basis_name: basis_series
            for basis_name, basis_series in _allocation_basis_series_cache.items()
            if basis_name in {"Gross Floor Area", "Built Up Area"}
        }

        def _execute_named_threaded_tasks(tasks_dict):
            """
            Submit a dict of {name: callable} to the shared thread executor.
            Returns {name: result} preserving insertion order.
            """
            if not tasks_dict:
                return {}

            if not _should_parallelize(len(tasks_dict)):
                return {name: fn() for name, fn in tasks_dict.items()}

            futures = {_shared_executor.submit(fn): name for name, fn in tasks_dict.items()}
            results = {}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
            return {name: results[name] for name in tasks_dict}

        def _normalize_cache_scalar(value):
            if isinstance(value, np.generic):
                value = value.item()

            if isinstance(value, (pd.Timestamp, datetime, date)):
                return None if pd.isna(value) else pd.Timestamp(value).value

            if isinstance(value, np.datetime64):
                return None if np.isnat(value) else pd.Timestamp(value).value

            if value is None:
                return None

            if isinstance(value, float):
                return None if math.isnan(value) else value

            try:
                return None if pd.isna(value) else value
            except TypeError:
                return value

        def _normalize_sequence_cache_key(values):
            values_arr = np.asarray(values, dtype=object).reshape(-1)
            return tuple(_normalize_cache_scalar(value) for value in values_arr.tolist())

        def _normalize_datetime_cache_key(values):
            datetime_arr = pd.to_datetime(values, errors="coerce").to_numpy(dtype="datetime64[ns]").reshape(-1)
            return tuple(datetime_arr.view("int64").tolist())

        def _resolve_start_indices(start_dates):
            start_dates_arr = pd.to_datetime(start_dates, errors="coerce").to_numpy(dtype="datetime64[ns]").reshape(-1)
            start_idx_arr = np.full(start_dates_arr.shape[0], -1, dtype=int)

            for loop_row_idx, start_date_value in enumerate(start_dates_arr.tolist()):
                if pd.isna(start_date_value):
                    continue
                start_idx_arr[loop_row_idx] = _period_start_to_idx.get(pd.Timestamp(start_date_value), -1)

            return start_dates_arr, start_idx_arr

        def _should_parallelize(task_count):
            # OPTIMIZED: keep nested helper calls inside worker threads sequential to avoid shared-pool fan-out deadlocks.
            return (
                threading.current_thread() is threading.main_thread()
                and _max_parallel_workers > 1
                and task_count > 1
                and (_n_assets * _n_periods) >= 2000
            )

        def _map_independent_tasks(task_items, task_callable):
            if not _should_parallelize(len(task_items)):
                return [task_callable(task_item) for task_item in task_items]

            futures = {_shared_executor.submit(task_callable, item): idx for idx, item in enumerate(task_items)}
            results = [None] * len(task_items)
            for future in as_completed(futures):
                results[futures[future]] = future.result()
            return results
        
        # Helper function to create zero-initialized DataFrame efficiently
        def _create_zero_df(dtype='float64'):
            """Create a zero-initialized DataFrame with cached index/columns."""
            return pd.DataFrame(
                np.zeros((_n_assets, _n_periods), dtype=dtype),
                index=_template_index,
                columns=_template_columns
            )
        
        # Helper function to create single-row zero-initialized DataFrame (for project-level calculations)
        def _create_zero_df_single_row(dtype='float64'):
            """Create a single-row zero-initialized DataFrame with index [0] and same columns."""
            return pd.DataFrame(
                np.zeros((1, _n_periods), dtype=dtype),
                index=[0],
                columns=_template_columns
            )

        def _get_cached_axis_aggregate(df, aggregate):
            # OPTIMIZED: memoize repeated axis-1 aggregates for stable DataFrame objects used across multiple cost modules.
            cache_key = (id(df), aggregate)
            with _row_sum_cache_lock:
                cached_result = _row_sum_cache.get(cache_key)

            if cached_result is None:
                if aggregate == "sum":
                    computed_result = df.sum(axis=1)
                elif aggregate == "max":
                    computed_result = df.max(axis=1)
                else:
                    raise ValueError(f"Unsupported aggregate '{aggregate}'")

                with _row_sum_cache_lock:
                    cached_result = _row_sum_cache.setdefault(cache_key, computed_result)

            return cached_result.copy()
        
        # ============================================================================================
        # FINANCIAL HELPER FUNCTIONS (Excel PMT, IPMT, PPMT equivalents)
        # ============================================================================================
        
        def _ppmt(rate, per, nper, pv, fv=0):
                """
                Compute the principal component of the payment in a given period
                for a standard fully amortizing loan.

                Mathematical basis
                -------------------
                EMI:
                    EMI = (pv * rate) / (1 - (1 + rate)^(-nper))

                Outstanding balance before period `per`:
                    B_(per-1) =
                        pv * (1 + rate)^(per-1)
                        - EMI * (( (1 + rate)^(per-1) - 1 ) / rate)

                Principal in period `per`:
                    Principal_per = EMI - (B_(per-1) * rate)

                Parameters
                ----------
                rate : float
                    Interest rate per period (e.g., annual_rate / periods_per_year).
                per : int
                    Target period (1-based index).
                nper : int
                    Total number of payment periods.
                pv : float
                    Present value (initial loan amount).
                fv : float, optional
                    Future value after final payment (default is 0).

                Returns
                -------
                float
                    Principal portion of the payment in the specified period.

                Notes
                -----
                - Assumes end-of-period payments.
                - `rate` must be per-period, not annual unless payments are annual.
                - `per` must satisfy 1 <= per <= nper.
                - Uses standard amortization logic (annuity-based repayment).
                """
                if per < 1 or per > nper:
                    raise ValueError("per must be between 1 and nper")

                if rate == 0:
                    return -(pv + fv) / nper

                # Direct EMI formula
                emi = (pv * rate) / (1 - (1 + rate) ** (-nper))

                # Direct balance before period (no rearrangement)
                balance_before = (
                    pv * (1 + rate) ** (per - 1)
                    - emi * (((1 + rate) ** (per - 1) - 1) / rate)
                )

                # Direct principal formula
                principal = emi - (balance_before * rate)

                return principal * -1
        
        template_asset_timeline = _create_zero_df()
        number_of_assets = _n_assets

        # ========================================================================
        # SUB-MODULE 3.3: GENERIC CALCULATION FUNCTIONS
        # ========================================================================

        def fn_calculate_pre_defined_profile(
            template,
            profile_option,
            selected_pre_defined_profile,
            start_dates,
            predefined_profile_names,
            predefined_profile_data,
            predefined_profile_durations,
            model_timeline_me
        ):
            """
            Calculate pre-defined profiles for cost phasing or payment schedules.

            Args:
                template (pd.DataFrame): A DataFrame template initialized with zeros.
                profile_option (pd.Series): A series indicating the profile option for each asset.
                selected_pre_defined_profile (pd.Series): A series indicating the selected pre-defined profile.
                start_dates (pd.Series): A series of start dates for each asset.
                predefined_profile_names (list): A list of names for the pre-defined profiles.
                predefined_profile_data (dict): A dictionary containing the data for the pre-defined profiles.
                predefined_profile_durations (dict): A dictionary containing the durations for the pre-defined profiles.
                model_timeline_me (pd.DataFrame): The model timeline DataFrame with monthly periods.

            Returns:
                pd.DataFrame: A DataFrame containing the calculated pre-defined profile for each asset.
            """
            try:
                template_values = template.values
                profile_option_arr = np.asarray(profile_option, dtype=object).reshape(-1)
                selected_profile_arr = np.asarray(selected_pre_defined_profile, dtype=object).reshape(-1)
                _, start_idx_arr = _resolve_start_indices(start_dates)
                grouped_row_assignments = {}

                for loop_row_idx in template.index:

                    # Skip assets that do not use "Pre defined" payment profiles
                    if profile_option_arr[loop_row_idx] != "Pre defined":
                        continue

                    selected_profile = selected_profile_arr[loop_row_idx]

                    # Skip if the selected profile is invalid
                    if pd.isna(selected_profile) or selected_profile in (None, ""):
                        continue

                    profile_details = _predefined_profile_lookup.get(selected_profile)

                    # Validate if the selected profile exists in predefined profile names
                    if profile_details is None:
                        continue

                    # Validate if the profile sums to 1 (100%)
                    if abs(profile_details["sum"] - 1) > 1e-6:
                        continue

                    # Validate if the profile duration exceeds the maximum allowed duration
                    if profile_details["non_zero_count"] > profile_details["max_duration"]:
                        continue

                    start_idx = start_idx_arr[loop_row_idx]
                    if start_idx < 0:
                        continue

                    cache_key = (selected_profile, int(start_idx))
                    grouped_row_assignments.setdefault(cache_key, []).append(loop_row_idx)

                def _build_predefined_profile_row(cache_key):
                    selected_profile_name, start_idx = cache_key
                    row_values = np.zeros(_n_periods, dtype=float)
                    predefined_profile = _predefined_profile_lookup[selected_profile_name]["values"]
                    valid_length = min(len(predefined_profile), _n_periods - start_idx)
                    row_values[start_idx:start_idx + valid_length] = predefined_profile[:valid_length]
                    return cache_key, row_values

                missing_row_keys = [
                    cache_key
                    for cache_key in grouped_row_assignments
                    if cache_key not in _predefined_profile_row_cache
                ]
                for cache_key, row_values in _map_independent_tasks(missing_row_keys, _build_predefined_profile_row):
                    with _predefined_profile_row_cache_lock:
                        # OPTIMIZED: ensure only the first completed worker publishes each cached predefined profile row.
                        _predefined_profile_row_cache.setdefault(cache_key, row_values)

                for cache_key, row_indices in grouped_row_assignments.items():
                    template_values[row_indices, :] = _predefined_profile_row_cache[cache_key]

                return template
            except Exception as e:
                print(f"Error in fn_calculate_pre_defined_profile: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_user_defined_profile(
            template,
            profile_options,
            schedules,
            start_dates,
            durations,
            model_timeline_me
        ):
            """
            Calculate user-defined profiles for cost phasing or payment schedules.

            Args:
                template (pd.DataFrame): A DataFrame template initialized with zeros.
                profile_options (pd.Series): A series indicating the profile option for each asset.
                schedules (dict): A dictionary containing user-defined schedules for cost phasing or payments.
                start_dates (pd.Series): A series of start dates for each asset.
                durations (pd.Series): A series of durations (in months) for each asset.
                model_timeline_me (pd.DataFrame): The model timeline DataFrame with monthly periods.

            Returns:
                pd.DataFrame: A DataFrame containing the calculated user-defined profile for each asset.
            """
            try:
                template_values = template.values
                profile_options_arr = np.asarray(profile_options, dtype=object).reshape(-1)
                durations_arr = np.asarray(durations, dtype=object).reshape(-1)
                _, start_idx_arr = _resolve_start_indices(start_dates)
                grouped_row_assignments = {}

                for loop_row_idx in template.index:

                    # Skip assets that do not use "User defined" payment profiles
                    if profile_options_arr[loop_row_idx] != "User defined":
                        continue

                    duration = durations_arr[loop_row_idx]

                    # Validate if the duration is valid
                    if pd.isna(duration) or duration <= 0:
                        continue

                    start_idx = start_idx_arr[loop_row_idx]
                    if start_idx < 0:
                        continue

                    schedule = schedules[loop_row_idx]

                    # Validate the payment schedule
                    if isinstance(schedule, list):
                        normalized_schedule = tuple(
                            0 if value == "" or value is None or pd.isna(value) else value
                            for value in schedule
                        )
                        cache_key = ("list", normalized_schedule, int(start_idx), int(duration))
                    else:
                        normalized_schedule = 0 if pd.isna(schedule) or schedule is None else schedule
                        cache_key = ("scalar", _normalize_cache_scalar(normalized_schedule), int(start_idx), int(duration))

                    grouped_row_assignments.setdefault(cache_key, []).append(loop_row_idx)

                def _build_user_defined_profile_row(cache_key):
                    schedule_kind, normalized_schedule, start_idx, duration = cache_key
                    row_values = np.zeros(_n_periods, dtype=float)
                    valid_end_idx = min(int(start_idx + duration), _n_periods)

                    if valid_end_idx <= start_idx:
                        return cache_key, row_values

                    if schedule_kind == "list":
                        schedule_slice = normalized_schedule[start_idx:valid_end_idx]
                        schedule_values = np.array([
                            0 if value == "" or value is None or pd.isna(value) else value
                            for value in schedule_slice
                        ], dtype=float)
                    else:
                        schedule_values = np.full(
                            valid_end_idx - start_idx,
                            0 if normalized_schedule is None else normalized_schedule,
                            dtype=float,
                        )

                    row_values[start_idx:valid_end_idx] = schedule_values
                    return cache_key, row_values

                missing_row_keys = [
                    cache_key
                    for cache_key in grouped_row_assignments
                    if cache_key not in _user_defined_profile_row_cache
                ]
                for cache_key, row_values in _map_independent_tasks(missing_row_keys, _build_user_defined_profile_row):
                    with _user_defined_profile_row_cache_lock:
                        # OPTIMIZED: ensure only the first completed worker publishes each cached user-defined profile row.
                        _user_defined_profile_row_cache.setdefault(cache_key, row_values)

                for cache_key, row_indices in grouped_row_assignments.items():
                    template_values[row_indices, :] = _user_defined_profile_row_cache[cache_key]

                template.fillna(0, inplace=True)
                template.replace('', 0, inplace=True)            

                return template
            except Exception as e:
                print(f"Error in fn_calculate_user_defined_profile: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_monthly_escalation_profile(
            escalation_percent_template,
            escalation_factor_template,
            selected_escalation_profile,
            escalation_profile_names,
            escalation_profile_data,
            model_timeline_me
        ):
            """
            Generalized function to calculate monthly escalation profiles and cumulative escalation factors.

            Parameters:
                escalation_percent_template (DataFrame): Template DataFrame to store the calculated escalation percentages.
                escalation_factor_template (DataFrame): Template DataFrame to store the cumulative escalation factors.
                selected_escalation_profile (list): List of selected escalation profiles for each asset.
                escalation_profile_names (list): List of valid escalation profile names.
                escalation_profile_data (list): List of escalation rates corresponding to the profile names.
                model_timeline_me (DataFrame): Timeline DataFrame with 'Year' column.

            Returns:
                tuple: Updated escalation_percent_template and escalation_factor_template DataFrames.
            """
            try:
                selected_profile_arr = np.asarray(selected_escalation_profile, dtype=object).reshape(-1)
                selected_profile_key = _normalize_sequence_cache_key(selected_profile_arr)
                with _monthly_escalation_result_cache_lock:
                    cached_result = _monthly_escalation_result_cache.get(selected_profile_key)

                if cached_result is None:
                    monthly_percent_values = np.zeros((_n_assets, _n_periods), dtype=float)
                    monthly_factor_values = np.ones((_n_assets, _n_periods), dtype=float)

                    if selected_profile_key and len(set(selected_profile_key)) == 1:
                        selected_profile_name = selected_profile_arr[0]
                        if pd.notna(selected_profile_name) and selected_profile_name != '':
                            profile_curves = _monthly_escalation_curve_cache.get(selected_profile_name)
                            if profile_curves is not None:
                                monthly_percent_values[:, :] = profile_curves[0]
                                monthly_factor_values[:, :] = profile_curves[1]
                    else:
                        valid_profile_names = pd.unique(pd.Series(selected_profile_arr, dtype=object))
                        for selected_profile_name in valid_profile_names:
                            if pd.isna(selected_profile_name) or selected_profile_name == '':
                                continue
                            profile_curves = _monthly_escalation_curve_cache.get(selected_profile_name)
                            if profile_curves is None:
                                continue

                            profile_mask = selected_profile_arr == selected_profile_name
                            monthly_percent_values[profile_mask, :] = profile_curves[0]
                            monthly_factor_values[profile_mask, :] = profile_curves[1]

                    cached_result = (monthly_percent_values, monthly_factor_values)
                    with _monthly_escalation_result_cache_lock:
                        # OPTIMIZED: publish escalation matrices once so concurrent cost modules reuse the same immutable arrays.
                        cached_result = _monthly_escalation_result_cache.setdefault(selected_profile_key, cached_result)

                escalation_percent_template.iloc[:, :] = cached_result[0]
                escalation_factor_template.iloc[:, :] = cached_result[1]
                
                return escalation_percent_template, escalation_factor_template
            except Exception as e:
                print(f"Error in fn_calculate_monthly_escalation_profile: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        _record_timing("Timeline and utility setup")

        # ========================================================================
        # SUB-MODULE 3.4: ACQUISITION & TRANSACTION COST FUNCTIONS
        # ========================================================================
        
        def fn_get_named_range_value(assumptions_df, name, default=None):
            """
            Helper to get a named range value from assumptions DataFrame.
            
            Args:
                assumptions_df: DataFrame with 'name' and 'value' columns
                name: Name of the named range to retrieve
                default: Default value if not found
            
            Returns:
                Value from the named range or default if not found
            """
            try:
                return _assumptions_value_cache.get(name, default)
            except (IndexError, KeyError):
                return default

        def fn_calculate_acquisition_transaction_cost(
            template,
            asset_cost_override,
            asset_transaction_date,
            global_allocation_basis,
            global_cost_basis,
            global_ad_hoc_amount,
            global_cost_per_sqm,
            global_cost_percent,
            global_calculation_approach,
            global_transaction_date,
            global_escalation_profile,
            acquisition_cost_df
        ):
            """
            Calculate acquisition transaction costs (legal, agency, technical, valuation, due diligence).
            
            Override Logic:
            - If asset_cost_override has a value (not None/NaN/0), use that as the cost amount
              and use asset_transaction_date for timing
            - Otherwise, use global calculation approach to determine cost
            
            Global Calculation Approaches:
            - % of Acquisition Price: percentage Ã— acquisition_cost (per asset)
            - SAR / SQM of: cost_per_sqm Ã— area (based on cost_basis)
            - Ad-Hoc Amount: Fixed total amount allocated across NON-OVERRIDE assets
              based on allocation_basis
            
            Escalation is ALWAYS from global_escalation_profile.
            
            Args:
                template (pd.DataFrame): Zero-initialized template DataFrame
                asset_cost_override (list): Override amounts per asset (if value exists, it's the amount)
                asset_transaction_date (list): Transaction dates per asset (used when override exists)
                global_allocation_basis (str): For Ad-Hoc - how to allocate across assets
                global_cost_basis (str): For SAR/SQM - which area to use
                global_ad_hoc_amount (float): Total ad-hoc amount to allocate
                global_cost_per_sqm (float): Cost per sqm
                global_cost_percent (float): Percent of acquisition price
                global_calculation_approach (str): "% of Acquisition Price", "SAR / SQM of", "Ad-Hoc Amount"
                global_transaction_date: Default transaction date
                global_escalation_profile: Escalation profile (always used)
                acquisition_cost_df (pd.DataFrame): DataFrame of acquisition costs (for % calculation)
            
            Returns:
                tuple: (cost_amount_series, transaction_date_series, escalation_profile)
            """
            try:
                n_assets = len(template)
                
                # Convert to series for easier handling
                asset_cost_override = pd.Series(asset_cost_override if asset_cost_override is not None else [None] * n_assets)
                asset_transaction_date = pd.Series(asset_transaction_date if asset_transaction_date is not None else [None] * n_assets)
                
                # Determine override mask - override if value exists and is not 0
                override_mask = asset_cost_override.notna() & (asset_cost_override != 0) & (asset_cost_override != '')
                
                # ========================================================================
                # ALLOCATION BASIS MAPPING (for Ad-Hoc allocation)
                # ========================================================================
                allocation_basis_mapping = _transaction_cost_basis_series_cache
                
                # ========================================================================
                # COST BASIS MAPPING (for SAR/SQM calculation)
                # ========================================================================
                cost_basis_mapping = _transaction_cost_basis_series_cache
                
                # ========================================================================
                # CALCULATE GLOBAL AMOUNTS BASED ON APPROACH
                # ========================================================================
                
                # Initialize global amount series
                global_amount = pd.Series([0.0] * n_assets)
                
                if global_calculation_approach == "% of Acquisition Cost":
                    # Percentage of acquisition cost per asset
                    global_amount = (
                        _get_cached_axis_aggregate(acquisition_cost_df, "sum") * (global_cost_percent or 0)
                        if acquisition_cost_df is not None
                        else pd.Series([0.0] * n_assets)
                    )
                
                elif global_calculation_approach == "SAR/SQM":
                    # Cost per sqm Ã— area
                    cost_basis_series = cost_basis_mapping.get(global_cost_basis, pd.Series([0.0] * n_assets, index=template.index))
                    global_amount = cost_basis_series * (global_cost_per_sqm or 0)
                
                elif global_calculation_approach == "Ad-Hoc Amount":
                    # Allocate ad-hoc amount across NON-OVERRIDE assets based on allocation_basis
                    allocation_basis_series = allocation_basis_mapping.get(global_allocation_basis, pd.Series([0.0] * n_assets, index=template.index))
                    
                    # Only allocate to non-override assets
                    allocation_basis_filtered = allocation_basis_series.where(~override_mask, 0)
                    total_allocation_basis = allocation_basis_filtered.sum()
                    
                    if total_allocation_basis > 0:
                        allocation_percent = allocation_basis_filtered / total_allocation_basis
                        global_amount = allocation_percent * (global_ad_hoc_amount or 0)
                    else:
                        global_amount = pd.Series([0.0] * n_assets)
                
                # ========================================================================
                # APPLY OVERRIDE LOGIC
                # ========================================================================
                
                # Cost amount: use override if exists, otherwise use global calculated amount
                final_cost_amount = asset_cost_override.where(override_mask, global_amount).astype(float).fillna(0)
                
                # Transaction date: use asset date if override, otherwise use global date
                final_transaction_date = asset_transaction_date.where(override_mask, global_transaction_date)
                
                # Escalation is ALWAYS from global
                final_escalation_profile = global_escalation_profile
                
                return final_cost_amount, final_transaction_date, final_escalation_profile
                
            except Exception as e:
                print(f"Error in fn_calculate_acquisition_transaction_cost: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_create_transaction_flag(
            transaction_dates,
            timeline_periods,
            template
        ):
            # """
            # Creates a transaction flag DataFrame based on transaction dates and timeline periods.
            
                transaction_dates_key = _normalize_datetime_cache_key(transaction_dates)
                flag_arr = _transaction_flag_value_cache.get(transaction_dates_key)

                if flag_arr is None:
                    # Fully vectorized: broadcast date comparison across all assets and periods
                    flag_arr = np.zeros((_n_assets, _n_periods), dtype=float)

                    trans_dates = pd.to_datetime(transaction_dates, errors='coerce').values.astype('datetime64[D]')

                    valid_mask = ~np.isnat(trans_dates)
                    if valid_mask.any():
                        valid_indices = np.where(valid_mask)[0]
                        valid_trans = trans_dates[valid_mask]
                        # Broadcasting: (n_valid, 1) == (1, n_periods) -> match matrix
                        match_matrix = (valid_trans[:, np.newaxis] == _period_starts_days[np.newaxis, :])
                        flag_arr[valid_indices] = match_matrix.astype(float)

                    _transaction_flag_value_cache[transaction_dates_key] = flag_arr

                return pd.DataFrame(flag_arr, index=template.index, columns=template.columns)
                
                trans_dates = pd.to_datetime(transaction_dates, errors='coerce').values.astype('datetime64[D]')
                
                valid_mask = ~np.isnat(trans_dates)
                if valid_mask.any():
                    valid_indices = np.where(valid_mask)[0]
                    valid_trans = trans_dates[valid_mask]
                    # Broadcasting: (n_valid, 1) == (1, n_periods) â†’ match matrix
                    match_matrix = (valid_trans[:, np.newaxis] == _period_starts_days[np.newaxis, :])
                    flag_arr[valid_indices] = match_matrix.astype(float)

                return pd.DataFrame(flag_arr, index=template.index, columns=template.columns)
            # except Exception as e:
            #     print(f"Error in fn_create_transaction_flag: {e}")
            #     print(f"Traceback: {traceback.format_exc()}")
            #     raise

        def fn_calculate_escalated_transaction_cost(
            base_amount_series,
            escalation_factor_mapping,
            transaction_cost_flag,
            calculation_approach,
            template
        ):
            """
            Calculates the escalated transaction cost matrix for each asset and period.
            
            For % of Acquisition Price: Apply cost directly (no escalation - already escalated in acquisition)
            For other approaches: Apply base_amount Ã— escalation_factor Ã— transaction_flag
            
            Args:
                base_amount_series (pd.Series): Series of base cost amounts per asset
                escalation_factor_mapping (pd.DataFrame): DataFrame of escalation factors
                transaction_cost_flag (pd.DataFrame): Transaction flag DataFrame
                calculation_approach (str): Calculation approach string
                template (pd.DataFrame): Template DataFrame for output shape

            Returns:
                pd.DataFrame: Escalated transaction cost matrix (N_assets Ã— N_periods)
            """
            try:
                # Fully vectorized: build base amount array and apply matrix operations
                n = len(template)
                base_arr = np.array([
                    float(base_amount_series[i]) if i < len(base_amount_series) and pd.notna(base_amount_series[i]) else 0.0
                    for i in range(n)
                ], dtype=float)

                if calculation_approach == "% of Acquisition Price":
                    result_arr = base_arr[:, np.newaxis] * transaction_cost_flag.values
                else:
                    result_arr = base_arr[:, np.newaxis] * escalation_factor_mapping.values * transaction_cost_flag.values

                # Zero out rows with no base amount
                zero_mask = (base_arr == 0)
                result_arr[zero_mask] = 0

                return pd.DataFrame(result_arr, index=template.index, columns=template.columns)
            except Exception as e:
                print(f"Error in fn_calculate_escalated_transaction_cost: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_create_start_flag_df(start_dates, template):
            """Create a period start flag matrix using cached timeline broadcasts."""
            start_dates_key = _normalize_datetime_cache_key(start_dates)
            start_flag_values = _start_flag_value_cache.get(start_dates_key)

            if start_flag_values is None:
                start_dates_arr = pd.to_datetime(start_dates, errors="coerce").to_numpy().reshape(-1, 1)
                start_flag_values = (start_dates_arr == _period_starts_broadcast).astype(int)
                _start_flag_value_cache[start_dates_key] = start_flag_values

            return pd.DataFrame(
                start_flag_values,
                index=template.index,
                columns=template.columns
            )

        def fn_calculate_cost_start_escalation_mapping(
            start_dates,
            selected_escalation_profile,
            escalation_profile_names,
            escalation_profile_data,
            escalation_applicability_flag,
            template,
        ):
            """Build escalation factors mapped to cost start periods without changing calculation logic."""
            monthly_escalation_percent = _create_zero_df()
            monthly_escalation_factors = _create_zero_df()
            start_flag = fn_create_start_flag_df(start_dates, template)

            monthly_escalation_percent, monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=monthly_escalation_percent,
                escalation_factor_template=monthly_escalation_factors,
                selected_escalation_profile=selected_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            escalation_applicability_arr = np.asarray(escalation_applicability_flag, dtype=int).reshape(-1, 1)
            mapped_values = np.where(
                escalation_applicability_arr == 1,
                monthly_escalation_factors.values * start_flag.values,
                start_flag.values,
            )

            return (
                monthly_escalation_percent,
                monthly_escalation_factors,
                pd.DataFrame(mapped_values, index=template.index, columns=template.columns),
            )

        # ========================================================================
        # EXECUTE ACQUISITION COST CALCULATIONS
        # ========================================================================
        
        _record_timing("Land Acquisition Module start")
        
        # Load escalation profile data for acquisition calculations
        escalation_profile_names = _assumption_values_cache.get("a.devco.escalation.profile.name", [])
        escalation_profile_data = _assumption_values_cache.get("a.devco.escalation.profile", [])
        
        # Load predefined profile data
        predefined_profile_names = _assumption_values_cache.get("a.devco.predefined.profile.name", [])
        predefined_profile_data = _assumption_values_cache.get("a.devco.predefined.profile", [])
        predefined_profile_durations = _assumption_values_cache.get("a.devco.predefined.profile.duration", [])
        _predefined_profile_lookup.clear()
        for profile_idx, profile_name in enumerate(predefined_profile_names):
            if profile_name in (None, ""):
                continue

            if profile_idx >= len(predefined_profile_data) or profile_idx >= len(predefined_profile_durations):
                continue

            try:
                predefined_profile = np.array(predefined_profile_data[profile_idx], dtype=float)
            except (TypeError, ValueError):
                continue

            _predefined_profile_lookup[profile_name] = {
                "values": predefined_profile,
                "max_duration": predefined_profile_durations[profile_idx],
                "sum": float(predefined_profile.sum()),
                "non_zero_count": int(np.count_nonzero(predefined_profile > 0)),
            }

        _monthly_escalation_curve_cache.clear()
        _monthly_escalation_result_cache.clear()
        _start_flag_value_cache.clear()
        _transaction_flag_value_cache.clear()
        _year_index_array = np.array([_year_to_idx[y] for y in _period_years], dtype=int)

        def _build_monthly_escalation_curve(task_item):
            profile_name, escalation_profile = task_item
            if profile_name in (None, "") or escalation_profile in (None, ""):
                return None

            try:
                escalation_rate_arr = np.array([value for value in escalation_profile if value != ""], dtype=float)
            except (TypeError, ValueError):
                return None

            if escalation_rate_arr.size == 0:
                return None

            monthly_escalation_percents = ((1 + escalation_rate_arr[_year_index_array]) ** (1 / 12)) - 1
            return profile_name, (
                monthly_escalation_percents,
                np.cumprod(1 + monthly_escalation_percents),
            )

        escalation_curve_tasks = [
            (profile_name, escalation_profile_data[profile_idx])
            for profile_idx, profile_name in enumerate(escalation_profile_names)
            if profile_idx < len(escalation_profile_data)
        ]
        for profile_result in _map_independent_tasks(escalation_curve_tasks, _build_monthly_escalation_curve):
            if profile_result is None:
                continue
            profile_name, profile_curves = profile_result
            with _escalation_profile_compute_lock:
                # OPTIMIZED: publish each per-profile escalation curve once for all downstream modules.
                _monthly_escalation_curve_cache.setdefault(profile_name, profile_curves)

        _cached_user_defined_schedules = {
            "acquisition": _schedule_cache.get("s.devco.acquisition.cost.payment", []),
            "vertical_phasing": _schedule_cache.get("s.devco.vertical.phasing", []),
            "vertical_payment": _schedule_cache.get("s.devco.vertical.payment", []),
            "design": _schedule_cache.get("s.devco.design.cost.payment", []),
            "permitting": _schedule_cache.get("s.devco.permitting.cost.payment", []),
            "supervision": _schedule_cache.get("s.devco.supervision.cost.payment", []),
            "pm_fees": _schedule_cache.get("s.devco.PM.cost.payment", []),
            "contingency": _schedule_cache.get("s.devco.contingency.cost.payment", []),
            "dlp_insurance": _schedule_cache.get("s.devco.DLP.Insurance.cost.payment", []),
            "void_period": _schedule_cache.get("s.devco.void.period.payment", []),
            "sales_phasing": _schedule_cache.get("s.devco.sales.phasing", []),
            "sales_collection": _schedule_cache.get("s.devco.sales.collection", []),
            "pa_recovery": _schedule_cache.get("s.devco.PA.recovery", []),
            "sales_cost": _schedule_cache.get("s.devco.sales.cost.payment", []),
            "marketing_cost": _schedule_cache.get("s.devco.marketing.cost.payment", []),
        }
        
        # ========================================================================
        # STEP 1: Determine Acquisition Date (Asset Override vs Global)
        # ========================================================================
        
        w_acquisition_date = np.where(
            pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
            pd.Series(Asset.AcquisitionModule.acquisition_date),
            Global.LandAcquisitionCostAssumptions.acquisition_date
        ).astype('datetime64[ns]')
        
        # ========================================================================
        # STEP 2: Create Land Acquisition Flag (Vectorized)
        # ========================================================================
        
        o_land_acquisition_flag = fn_create_start_flag_df(w_acquisition_date, template_asset_timeline)
        
        # ========================================================================
        # STEP 3: Calculate User-Defined Acquisition Payment Profile
        # ========================================================================
        
        w_land_acquisition_payment_user_defined_profile = _create_zero_df()
            
        w_acquisition_payment_start_dates = (
            pd.Series(Asset.AcquisitionModule.acquisition_payment_start_date)
            .where(
                pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
                Global.LandAcquisitionCostAssumptions.transaction_date
            )
        )

        w_acquisition_payment_start_dates = pd.to_datetime(w_acquisition_payment_start_dates)

        # Call the generalized function for user-defined profile calculation
        w_land_acquisition_payment_user_defined_profile = fn_calculate_user_defined_profile(
            template=w_land_acquisition_payment_user_defined_profile,
            profile_options=Asset.AcquisitionModule.acquisition_payment_profile_option,
            schedules=_cached_user_defined_schedules["acquisition"],
            start_dates=w_acquisition_payment_start_dates,
            durations=Asset.AcquisitionModule.acquisition_payment_duration,
            model_timeline_me=model_timeline_me
        )
        
        # ========================================================================
        # STEP 4: Calculate Pre-Defined Acquisition Payment Profile
        # ========================================================================
        
        w_land_acquisition_payment_pre_defined_profile = _create_zero_df()
        
        w_acquisition_payment_profile_option = np.where(
            pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
            pd.Series(Asset.AcquisitionModule.acquisition_payment_profile_option),
            "Pre defined"
        )
        
        w_pre_defined_profile = np.where(
            pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
            pd.Series(Asset.AcquisitionModule.acquisition_payment_profile),
            Global.LandAcquisitionCostAssumptions.acquisition_profile
        )
        
        # Call the generalized function for pre-defined profile calculation
        w_land_acquisition_payment_pre_defined_profile = fn_calculate_pre_defined_profile(
            template=w_land_acquisition_payment_pre_defined_profile,
            profile_option=w_acquisition_payment_profile_option,
            selected_pre_defined_profile=w_pre_defined_profile,
            start_dates=w_acquisition_payment_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )
        
        

        # ========================================================================
        # STEP 5: Consolidated Acquisition Payment Profile
        # ========================================================================
        
        o_land_acquisition_payment_profile = _create_zero_df()
        
        # Sum the pre-defined and user-defined profiles
        o_land_acquisition_payment_profile = (
            w_land_acquisition_payment_pre_defined_profile + w_land_acquisition_payment_user_defined_profile
        )
        
        # ========================================================================
        # STEP 6: Calculate Acquisition Escalation Factors
        # ========================================================================
        
        w_land_acquisition_monthly_escalation_percent = _create_zero_df()
        w_land_acquisition_monthly_escalation_factors = _create_zero_df()
        
        w_acquisition_escalation_profile = np.where(
            pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
            pd.Series(Asset.AcquisitionModule.escalation_profile).astype(str),
            str(Global.LandAcquisitionCostAssumptions.acquisition_escalation)
        )
        
        # Call the generalized function for monthly escalation profile calculation
        w_land_acquisition_monthly_escalation_percent, w_land_acquisition_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
            escalation_percent_template=w_land_acquisition_monthly_escalation_percent,
            escalation_factor_template=w_land_acquisition_monthly_escalation_factors,
            selected_escalation_profile=w_acquisition_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            model_timeline_me=model_timeline_me
        )
        
        # Map escalation factors to acquisition flag
        w_land_acquisition_monthly_escalation_factor_mapping = _create_zero_df()
        w_land_acquisition_monthly_escalation_factor_mapping = w_land_acquisition_monthly_escalation_factors * o_land_acquisition_flag
        
        # ========================================================================
        # STEP 7: Calculate Land Acquisition Cost
        # ========================================================================
        
        o_land_acquisition_cost = _create_zero_df()
        
        # Get gross land area for cost calculation
        gross_land_area = _allocation_basis_array_cache["Gross Land Area"]
        developable_land_area = _allocation_basis_array_cache["Developable Land Area"]
        
        # Determine acquisition price (Asset Override vs Global)
        w_acquisition_price = np.where(
            pd.Series(Asset.AcquisitionModule.acquisition_module_override) == 'Yes',
            pd.Series(Asset.AcquisitionModule.acquisition_price),
            Global.LandAcquisitionCostAssumptions.cost_per_sqm
        ).astype(float)
        
        # Calculate base land acquisition cost (area * price per sqm)
        w_land_acquisition_cost = developable_land_area * w_acquisition_price
        
        # Sum escalation factors across all columns for each row
        total_escalation_factor = _get_cached_axis_aggregate(w_land_acquisition_monthly_escalation_factor_mapping, "sum")
        
        # Calculate total escalated cost per asset
        total_escalated_cost = w_land_acquisition_cost * total_escalation_factor
        
        # Multiply payment profile by total escalated cost using broadcasting
        o_land_acquisition_cost = o_land_acquisition_payment_profile.mul(total_escalated_cost, axis=0)
        
        _record_timing("Land acquisition costs calculated")
        
        # ========================================================================
        # STEP 8: Calculate Transaction Costs (Legal, Agency, Technical, Valuation, Due Diligence)
        # ========================================================================
        # 
        # Override Logic:
        # - If {cost_type}_cost_override has a value, it IS the override amount
        # - Use {cost_type}_actual_payment_date for timing when override exists
        # - Otherwise use global calculation approach and global transaction date
        # - Escalation is ALWAYS from global
        # 
        # Global Calculation Approaches:
        # - % of Acquisition Price: cost_percentage Ã— land_acquisition_cost
        # - SAR / SQM of: cost_per_sqm Ã— area (based on cost_basis)
        # - Ad-Hoc Amount: Total amount allocated across non-override assets by allocation_basis
        # ========================================================================
        
        transaction_cost_types = ['legal', 'agency', 'technical', 'valuation', 'due_diligence']
        transaction_cost_outputs = {}
        transaction_cost_workings = {}
        o_legal_cost = None
        o_agency_cost = None
        o_technical_cost = None
        o_valuation_cost = None
        o_due_diligence_cost = None
        o_total_transaction_cost = None
        o_total_acquisition_cost = None

        def fn_process_transaction_cost(cost_type):
            # Get global assumptions for this cost type
            global_atc = Global.AcquisitionTransactionCostAssumptions
            
            global_calculation_approach = getattr(global_atc, f'{cost_type}_cost_calculation_approach', None)
            global_ad_hoc = getattr(global_atc, f'{cost_type}_cost_ad_hoc_amount', 0) or 0
            global_cost_percent = getattr(global_atc, f'{cost_type}_cost_cost_percentage', 0) or 0
            global_cost_per_sqm = getattr(global_atc, f'{cost_type}_cost_cost_per_sqm', 0) or 0
            global_allocation_basis = getattr(global_atc, f'{cost_type}_cost_allocation_basis', None)
            global_cost_basis = getattr(global_atc, f'{cost_type}_cost_cost_basis', None)
            global_transaction_date = getattr(global_atc, f'{cost_type}_cost_transaction_date', None)
            global_escalation_profile = getattr(global_atc, f'{cost_type}_cost_escalation_profile', None)
            
            # Get asset-level override (this IS the amount if it has a value)
            asset_cost_override = getattr(Asset.AcquisitionModule, f'{cost_type}_cost_override', None)
            asset_transaction_date = getattr(Asset.AcquisitionModule, f'{cost_type}_actual_payment_date', None)
            
            # Calculate transaction cost amounts
            w_trans_cost_amount, w_trans_date, w_trans_escalation_profile = fn_calculate_acquisition_transaction_cost(
                template=template_asset_timeline,
                asset_cost_override=asset_cost_override,
                asset_transaction_date=asset_transaction_date,
                global_allocation_basis=global_allocation_basis,
                global_cost_basis=global_cost_basis,
                global_ad_hoc_amount=global_ad_hoc,
                global_cost_per_sqm=global_cost_per_sqm,
                global_cost_percent=global_cost_percent,
                global_calculation_approach=global_calculation_approach,
                global_transaction_date=global_transaction_date,
                global_escalation_profile=global_escalation_profile,
                acquisition_cost_df=o_land_acquisition_cost
            )

            # Create transaction flag
            w_trans_flag = fn_create_transaction_flag(
                transaction_dates=w_trans_date,
                timeline_periods=model_timeline_me['Period Start'],
                template=_create_zero_df()
            )
            
            # Calculate escalation factors using the global escalation profile
            w_trans_escalation_percent = _create_zero_df()
            w_trans_escalation_factor = _create_zero_df()
            w_trans_escalation_factor.iloc[:, :] = 1
            
            # Create escalation profile array (same profile for all assets since it's global)
            escalation_profile_array = [w_trans_escalation_profile] * _n_assets
            
            w_trans_escalation_percent, w_trans_escalation_factor = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_trans_escalation_percent,
                escalation_factor_template=w_trans_escalation_factor,
                selected_escalation_profile=escalation_profile_array,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )
            
            # Map escalation factors to transaction flag
            w_trans_escalation_factor_mapped = w_trans_escalation_factor * w_trans_flag
            
            # Calculate escalated transaction cost
            o_trans_cost = fn_calculate_escalated_transaction_cost(
                base_amount_series=w_trans_cost_amount,
                escalation_factor_mapping=w_trans_escalation_factor_mapped,
                transaction_cost_flag=w_trans_flag,
                calculation_approach=global_calculation_approach,
                template=_create_zero_df()
            )

            return cost_type, o_trans_cost, {
                'amount': w_trans_cost_amount,
                'date': w_trans_date,
                'flag': w_trans_flag,
                'escalation_factor': w_trans_escalation_factor,
                'escalation_factor_mapped': w_trans_escalation_factor_mapped,
            }

        def _compute_transaction_cost_batch():
            # OPTIMIZED: use the named threaded helper so transaction categories share one deterministic fan-out entry point.
            return _execute_named_threaded_tasks({
                cost_type: (lambda _cost_type=cost_type: fn_process_transaction_cost(_cost_type))
                for cost_type in transaction_cost_types
            })

        _transaction_cost_batch_future = None
        if _should_parallelize(len(transaction_cost_types)):
            # OPTIMIZED: wave 1 starts independent transaction-cost work in the background while later modules continue.
            _transaction_cost_batch_future = _shared_executor.submit(_compute_transaction_cost_batch)

        def _ensure_transaction_cost_results():
            # OPTIMIZED: gather transaction outputs only when first consumed so background work can overlap safely.
            nonlocal transaction_cost_outputs, transaction_cost_workings
            nonlocal o_legal_cost, o_agency_cost, o_technical_cost, o_valuation_cost, o_due_diligence_cost
            nonlocal o_total_transaction_cost, o_total_acquisition_cost

            if o_total_transaction_cost is not None:
                return

            if _transaction_cost_batch_future is not None:
                transaction_cost_results = _transaction_cost_batch_future.result()
            else:
                transaction_cost_results = _compute_transaction_cost_batch()

            for cost_type, task_result in transaction_cost_results.items():
                _, o_trans_cost, working_dict = task_result
                transaction_cost_outputs[cost_type] = o_trans_cost
                transaction_cost_workings[cost_type] = working_dict

            o_legal_cost = transaction_cost_outputs['legal']
            o_agency_cost = transaction_cost_outputs['agency']
            o_technical_cost = transaction_cost_outputs['technical']
            o_valuation_cost = transaction_cost_outputs['valuation']
            o_due_diligence_cost = transaction_cost_outputs['due_diligence']

            o_total_transaction_cost = (
                o_legal_cost + o_agency_cost + o_technical_cost +
                o_valuation_cost + o_due_diligence_cost
            )
            o_total_acquisition_cost = o_land_acquisition_cost + o_total_transaction_cost

            _record_timing("Transaction costs calculated")
        
        # ========================================================================
        # EXPORT ACQUISITION COSTS (if enabled)
        # ========================================================================
        
        # ========================================================================
        # EXPORT ACQUISITION COSTS (if enabled) - SPLIT INTO 2 FILES
        # ========================================================================
        
        if _EXPORT_FLAGS['land_acquisition_cost']:
            acquisition_cost_export_dict = {
                # Final Output
                'o_Land_Acquisition_Cost': o_land_acquisition_cost,
                # Working - Acquisition Date & Flag
                'w_Acquisition_Date': pd.DataFrame({'Acquisition_Date': w_acquisition_date}),
                'w_Acquisition_Flag': o_land_acquisition_flag,
                # Working - Payment Start Dates
                'w_Payment_Start_Dates': pd.DataFrame({'Payment_Start_Date': w_acquisition_payment_start_dates}),
                # Working - User-Defined Profile Inputs
                'w_Profile_Option': pd.DataFrame({'Profile_Option': Asset.AcquisitionModule.acquisition_payment_profile_option}),
                'w_Payment_Duration': pd.DataFrame({'Payment_Duration': Asset.AcquisitionModule.acquisition_payment_duration}),
                # Working - Payment Profiles
                'w_User_Defined_Profile': w_land_acquisition_payment_user_defined_profile,
                'w_Pre_Defined_Profile_Name': pd.DataFrame({'Pre_Defined_Profile': w_pre_defined_profile}),
                'w_Pre_Defined_Profile': w_land_acquisition_payment_pre_defined_profile,
                'w_Payment_Profile': o_land_acquisition_payment_profile,
                # Working - Escalation Inputs
                'w_Escalation_Profile_Name': pd.DataFrame({'Escalation_Profile': w_acquisition_escalation_profile}),
                # Working - Escalation Calculations
                'w_Escalation_Percent': w_land_acquisition_monthly_escalation_percent,
                'w_Escalation_Factor': w_land_acquisition_monthly_escalation_factors,
                'w_Escalation_Factor_Mapped': w_land_acquisition_monthly_escalation_factor_mapping,
                # Working - Cost Calculation Inputs
                'w_Gross_Land_Area': pd.DataFrame({'Gross_Land_Area': gross_land_area}),
                'w_Acquisition_Price': pd.DataFrame({'Acquisition_Price': w_acquisition_price}),
                # Working - Cost Calculation
                'w_Base_Cost': pd.DataFrame({'Base_Cost': w_land_acquisition_cost}),
                'w_Total_Escalation_Factor': pd.DataFrame({'Total_Escalation_Factor': total_escalation_factor}),
                'w_Total_Escalated_Cost': pd.DataFrame({'Total_Escalated_Cost': total_escalated_cost}),
            }
            _export_to_excel(acquisition_cost_export_dict, 'devco_land_acquisition_cost', 'Land Acquisition Cost')
        
        if _EXPORT_FLAGS['land_acquisition_txn']:
            _ensure_transaction_cost_results()  # OPTIMIZED: exports require the deferred transaction-cost results to be materialized first.
            acquisition_txn_export_dict = {
                # Final Outputs - Transaction Costs
                'o_Legal_Cost': o_legal_cost,
                'o_Agency_Cost': o_agency_cost,
                'o_Technical_Cost': o_technical_cost,
                'o_Valuation_Cost': o_valuation_cost,
                'o_Due_Diligence_Cost': o_due_diligence_cost,
                'o_Total_Transaction_Cost': o_total_transaction_cost,
                'o_Total_Acquisition_Cost': o_total_acquisition_cost,
                # Working - Reference to Land Cost
                'w_Land_Acquisition_Cost': o_land_acquisition_cost,
                # Working - Legal Cost
                'w_Legal_Amount': pd.DataFrame({'Legal_Amount': transaction_cost_workings['legal']['amount']}),
                'w_Legal_Date': pd.DataFrame({'Legal_Date': transaction_cost_workings['legal']['date']}),
                'w_Legal_Flag': transaction_cost_workings['legal']['flag'],
                'w_Legal_Esc_Factor': transaction_cost_workings['legal']['escalation_factor'],
                # Working - Agency Cost
                'w_Agency_Amount': pd.DataFrame({'Agency_Amount': transaction_cost_workings['agency']['amount']}),
                'w_Agency_Date': pd.DataFrame({'Agency_Date': transaction_cost_workings['agency']['date']}),
                'w_Agency_Flag': transaction_cost_workings['agency']['flag'],
                'w_Agency_Esc_Factor': transaction_cost_workings['agency']['escalation_factor'],
                # Working - Technical Cost
                'w_Technical_Amount': pd.DataFrame({'Technical_Amount': transaction_cost_workings['technical']['amount']}),
                'w_Technical_Date': pd.DataFrame({'Technical_Date': transaction_cost_workings['technical']['date']}),
                'w_Technical_Flag': transaction_cost_workings['technical']['flag'],
                'w_Technical_Esc_Factor': transaction_cost_workings['technical']['escalation_factor'],
                # Working - Valuation Cost
                'w_Valuation_Amount': pd.DataFrame({'Valuation_Amount': transaction_cost_workings['valuation']['amount']}),
                'w_Valuation_Date': pd.DataFrame({'Valuation_Date': transaction_cost_workings['valuation']['date']}),
                'w_Valuation_Flag': transaction_cost_workings['valuation']['flag'],
                'w_Valuation_Esc_Factor': transaction_cost_workings['valuation']['escalation_factor'],
                # Working - Due Diligence Cost
                'w_DueDiligence_Amount': pd.DataFrame({'DueDiligence_Amount': transaction_cost_workings['due_diligence']['amount']}),
                'w_DueDiligence_Date': pd.DataFrame({'DueDiligence_Date': transaction_cost_workings['due_diligence']['date']}),
                'w_DueDiligence_Flag': transaction_cost_workings['due_diligence']['flag'],
                'w_DueDiligence_Esc_Factor': transaction_cost_workings['due_diligence']['escalation_factor'],
            }
            _export_to_excel(acquisition_txn_export_dict, 'devco_acquisition_txn_cost', 'Acquisition Transaction Costs')

        # ========================================================================
        # SUB-MODULE 3.5: VERTICAL DEVELOPMENT COST FUNCTIONS
        # ========================================================================
        
        def fn_calculate_construction_timeline(assets_data, global_obj, timeline_df):
            """
            Calculate construction start and end dates for each asset.
            
            Override Logic:
            - vd_override == 'Yes': Use asset's construction_start_date and asset's s_curve_option for duration
            - vd_override == 'No': Use global phase start date and global phase s_curve_option for duration
            
            Duration Source (based on s_curve_option):
            - 'Pre defined' or 'Pre Defined': Duration from pre_defined_duration attribute
            - 'User defined' or 'User Defined': Duration from vd_user_defined_duration attribute
            
            Args:
                assets_data: Asset class with list attributes
                global_obj: Global class with phase-specific attributes
                timeline_df (pd.DataFrame): Model timeline with Period Start/End dates
            
            Returns:
                tuple: (construction_start_dates, construction_end_dates, construction_durations)
            """
            try:
                n_assets = _n_assets
                construction_starts = []
                construction_ends = []
                durations = []
                
                vd = Asset.VerticalDevelopmentModule
                pd_attr = Asset.ProjectDetails
                global_vca = Global.VerticalConstructionAssumptions
                
                for idx in range(n_assets):
                    # Get override setting
                    vd_override = vd.vd_override[idx] if idx < len(vd.vd_override) else 'No'
                    vd_override_yes = str(vd_override).lower() == 'yes'
                    
                    # Get phase number for global lookups
                    phase = pd_attr.construction_phase[idx] if idx < len(pd_attr.construction_phase) else 1
                    phase_num = int(phase) if pd.notna(phase) and phase else 1
                    
                    if vd_override_yes:
                        # Asset-level override: use asset values
                        start_date = vd.construction_start_date[idx] if idx < len(vd.construction_start_date) else None
                        s_curve_option = vd.s_curve_option[idx] if idx < len(vd.s_curve_option) else 'Pre defined'
                        
                        if s_curve_option == 'Pre defined' or s_curve_option == 'Pre Defined':
                            duration_months = vd.pre_defined_duration[idx] if idx < len(vd.pre_defined_duration) else 0
                        else:
                            duration_months = vd.vd_user_defined_duration[idx] if idx < len(vd.vd_user_defined_duration) else 0
                    else:
                        # Global level (no override): use global phase values
                        start_date = getattr(global_vca, f'phase_{phase_num}_vertical_construction_start_date', None)
                        
                        # Get global phase s_curve_option
                        global_s_curve_option = getattr(global_vca, f'phase_{phase_num}_s_curve_option', 'Pre defined')
                        
                        if global_s_curve_option == 'Pre defined' or global_s_curve_option == 'Pre Defined':
                            # Get the selected profile name from global phase settings
                            global_profile_name = getattr(global_vca, f'phase_{phase_num}_vertical_construction_s_curve_', None)
                            
                            # Look up duration from the predefined profile
                            if global_profile_name and global_profile_name in predefined_profile_names:
                                profile_index = predefined_profile_names.index(global_profile_name)
                                duration_months = predefined_profile_durations[profile_index] if profile_index < len(predefined_profile_durations) else 0
                            else:
                                duration_months = 0
                        else:
                            duration_months = 0
                    
                    # Validate and convert
                    if pd.notna(start_date):
                        start_date = pd.to_datetime(start_date)
                    else:
                        start_date = None
                    
                    duration_months = int(duration_months) if pd.notna(duration_months) and duration_months else 0
                    
                    # Calculate end date
                    if start_date and duration_months > 0:
                        end_date = start_date + relativedelta(months=duration_months)
                    else:
                        end_date = start_date
                    
                    construction_starts.append(start_date)
                    construction_ends.append(end_date)
                    durations.append(duration_months)
                
                return pd.Series(construction_starts), pd.Series(construction_ends), pd.Series(durations)
            except Exception as e:
                print(f"Error in fn_calculate_construction_timeline: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_vertical_payment_profile(
            template,
            vd_override_series,
            phase_series,
            s_curve_option_series,
            pre_defined_s_curve_series,
            pre_defined_duration_series,
            user_defined_duration_series,
            construction_start_dates,
            global_obj,
            predefined_profile_names,
            predefined_profile_data,
            predefined_profile_durations,
            model_timeline_me
        ):
            """
            Calculate payment profiles for vertical construction costs.
            
            Payment Logic:
            1. If vd_override == 'Yes': Use asset-level S-curve settings
            2. If vd_override == 'No': Use global phase S-curve settings
            
            S-Curve Options:
            - 'Pre defined': Use selected predefined S-curve profile
            - 'User defined': Use user-defined duration with uniform distribution
            
            Args:
                template (pd.DataFrame): Zero-initialized template
                vd_override_series: Override flags per asset
                phase_series: Phase numbers per asset
                s_curve_option_series: S-curve option per asset
                pre_defined_s_curve_series: Selected predefined profile per asset
                pre_defined_duration_series: Predefined duration per asset
                user_defined_duration_series: User-defined duration per asset
                construction_start_dates: Construction start dates per asset
                global_obj: Global class
                predefined_profile_names: List of profile names
                predefined_profile_data: List of profile data arrays
                predefined_profile_durations: List of profile durations
                model_timeline_me: Model timeline DataFrame
                
            Returns:
                pd.DataFrame: Payment schedule as percentage per period (0-1)
            """
            try:
                result_df = template.copy()
                result_df.iloc[:, :] = 0
                
                global_vca = Global.VerticalConstructionAssumptions
                
                for loop_row_idx in template.index:
                    # Get override and phase
                    vd_override = vd_override_series[loop_row_idx] if loop_row_idx < len(vd_override_series) else 'No'
                    vd_override_yes = str(vd_override).lower() == 'yes'
                    
                    phase = phase_series[loop_row_idx] if loop_row_idx < len(phase_series) else 1
                    phase_num = int(phase) if pd.notna(phase) and phase else 1
                    
                    # Get start date
                    start_date = construction_start_dates[loop_row_idx] if loop_row_idx < len(construction_start_dates) else None
                    if pd.isna(start_date) or start_date is None:
                        continue
                    start_date = pd.to_datetime(start_date)
                    
                    # Determine S-curve settings based on override
                    if vd_override_yes:
                        s_curve_option = s_curve_option_series[loop_row_idx] if loop_row_idx < len(s_curve_option_series) else 'Pre defined'
                        profile_name = pre_defined_s_curve_series[loop_row_idx] if loop_row_idx < len(pre_defined_s_curve_series) else None
                        duration = pre_defined_duration_series[loop_row_idx] if loop_row_idx < len(pre_defined_duration_series) else 36
                    else:
                        # Get from global phase settings
                        s_curve_option = getattr(global_vca, f'phase_{phase_num}_s_curve_option', 'Pre defined')
                        profile_name = getattr(global_vca, f'phase_{phase_num}_vertical_construction_s_curve_', None)
                        duration = pre_defined_duration_series[loop_row_idx] if loop_row_idx < len(pre_defined_duration_series) else 36
                    
                    # Get profile values
                    if (s_curve_option == 'Pre defined' or s_curve_option == 'Pre Defined') and profile_name and profile_name in predefined_profile_names:
                        profile_index = predefined_profile_names.index(profile_name)
                        profile_values = list(predefined_profile_data[profile_index])
                        duration = predefined_profile_durations[profile_index] if profile_index < len(predefined_profile_durations) else len(profile_values)
                    else:
                        # User-defined: uniform distribution
                        duration = user_defined_duration_series[loop_row_idx] if loop_row_idx < len(user_defined_duration_series) else 36
                        duration = int(duration) if pd.notna(duration) and duration > 0 else 36
                        profile_values = [1.0 / duration] * duration
                    
                    duration = int(duration) if pd.notna(duration) and duration > 0 else len(profile_values)
                    
                    # Ensure profile values match duration
                    if len(profile_values) < duration:
                        profile_values = profile_values + [0.0] * (duration - len(profile_values))
                    elif len(profile_values) > duration:
                        profile_values = profile_values[:duration]
                    
                    # Normalize to sum to 1
                    total = sum(filter(lambda x: pd.notna(x) and x != '', profile_values))
                    if total > 0:
                        profile_values = [(v / total if pd.notna(v) and v != '' else 0) for v in profile_values]
                    
                    # Find start period index using binary search (O(log n) instead of O(n))
                    start_idx = np.searchsorted(_period_starts, np.datetime64(start_date))
                    if start_idx >= _n_periods:
                        continue
                    
                    # Apply profile to timeline using vectorized slice assignment
                    end_idx = min(start_idx + duration, _n_periods)
                    valid_len = min(len(profile_values), end_idx - start_idx)
                    result_df.iloc[loop_row_idx, start_idx:start_idx + valid_len] = profile_values[:valid_len]
                
                return result_df
            except Exception as e:
                print(f"Error in fn_calculate_vertical_payment_profile: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_base_vertical_cost(
            template,
            cost_basis_series,
            cost_per_sqm_series,
            gross_floor_area_series,
            built_up_area_series,
            developable_land_area_series,
            number_of_units_series
        ):
            """
            Calculate base vertical construction cost per asset.
            Cost = Area (based on cost basis) Ã— Cost per SQM
            
            Cost Basis Options:
            - 'Built Up Area': built_up_area Ã— cost_per_sqm
            - 'Gross Floor Area': gross_floor_area Ã— cost_per_sqm
            - 'Developable Land Area': developable_land_area Ã— cost_per_sqm
            - 'Number of Units': number_of_units Ã— cost_per_unit
            
            Args:
                template (pd.DataFrame): Template DataFrame
                cost_basis_series: Cost basis per asset
                cost_per_sqm_series: Cost per sqm/unit per asset
                gross_floor_area_series: GFA per asset
                built_up_area_series: BUA per asset
                developable_land_area_series: DLA per asset
                number_of_units_series: Number of units per asset
                
            Returns:
                pd.Series: Base cost per asset
            """
            try:
                n_assets = len(template)
                
                # Vectorized: build arrays for all inputs
                cost_basis_arr = np.array([
                    cost_basis_series[i] if i < len(cost_basis_series) else 'Built Up Area'
                    for i in range(n_assets)
                ])
                cost_per_unit_arr = np.array([
                    float(cost_per_sqm_series[i]) if i < len(cost_per_sqm_series) and pd.notna(cost_per_sqm_series[i]) else 0.0
                    for i in range(n_assets)
                ], dtype=float)
                
                bua_arr = np.array([
                    float(built_up_area_series[i]) if i < len(built_up_area_series) and pd.notna(built_up_area_series[i]) else 0.0
                    for i in range(n_assets)
                ], dtype=float)
                gfa_arr = np.array([
                    float(gross_floor_area_series[i]) if i < len(gross_floor_area_series) and pd.notna(gross_floor_area_series[i]) else 0.0
                    for i in range(n_assets)
                ], dtype=float)
                dla_arr = np.array([
                    float(developable_land_area_series[i]) if i < len(developable_land_area_series) and pd.notna(developable_land_area_series[i]) else 0.0
                    for i in range(n_assets)
                ], dtype=float)
                units_arr = np.array([
                    float(number_of_units_series[i]) if i < len(number_of_units_series) and pd.notna(number_of_units_series[i]) else 0.0
                    for i in range(n_assets)
                ], dtype=float)
                
                # Vectorized area selection using np.select
                area_arr = np.select(
                    [
                        cost_basis_arr == 'Built Up Area',
                        cost_basis_arr == 'Gross Floor Area',
                        cost_basis_arr == 'Developable Land Area',
                        cost_basis_arr == 'Number of Units'
                    ],
                    [bua_arr, gfa_arr, dla_arr, units_arr],
                    default=0.0
                )
                
                base_costs = pd.Series(area_arr * cost_per_unit_arr, index=range(n_assets), dtype='float64')
                
                return base_costs
            except Exception as e:
                print(f"Error in fn_calculate_base_vertical_cost: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_phased_vertical_cost(
            base_cost_series,
            payment_schedule_df,
            escalation_factor_df,
            template
        ):
            """
            Apply S-curve payment schedule and escalation to base vertical cost.
            
            Calculation: base_cost Ã— payment_schedule Ã— escalation_factor
            
            Args:
                base_cost_series (pd.Series): Base cost per asset
                payment_schedule_df (pd.DataFrame): Payment schedule (0-1 per period)
                escalation_factor_df (pd.DataFrame): Escalation factors per period
                template (pd.DataFrame): Template DataFrame
                
            Returns:
                pd.DataFrame: Phased vertical construction costs (N_assets Ã— N_periods)
            """
            try:
                # Fully vectorized: base_cost Ã— payment_schedule Ã— escalation_factor
                base_arr = base_cost_series.reindex(template.index, fill_value=0.0).values.astype(float)
                valid_mask = (~np.isnan(base_arr)) & (base_arr > 0)
                
                escalation_scalar = _get_cached_axis_aggregate(escalation_factor_df, "max").values[:, np.newaxis]

                result_arr = base_arr[:, np.newaxis] * payment_schedule_df.values * escalation_scalar
                result_arr[~valid_mask] = 0
                
                return pd.DataFrame(result_arr, index=template.index, columns=template.columns)
            except Exception as e:
                print(f"Error in fn_calculate_phased_vertical_cost: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # ========================================================================
        # EXECUTE VERTICAL DEVELOPMENT CALCULATIONS
        # ========================================================================
        
        # Step 1: Calculate Construction Timeline
        w_construction_start_dates, w_construction_end_dates, w_construction_durations = fn_calculate_construction_timeline(
            assets_data=Asset,
            global_obj=Global,
            timeline_df=model_timeline_me
        )
        
        # ====================================================================
        # Step 2: Construction Phasing (S-Curve) â€” w_vertical_construction_phasing
        # ====================================================================
        # This is the physical construction progress profile (% per period).
        # It is used by escrow and elsewhere to monitor construction progress.
        #
        # Profile source depends on s_curve_option (per asset or global phase):
        #   - 'Pre Defined': predefined S-curve profile from vd_pre_defined_s_curve
        #   - 'User Defined': user-defined profile from s.devco.vertical.phasing
        #     with vd_user_defined_duration
        # ====================================================================
        
        _vd = Asset.VerticalDevelopmentModule
        _global_vca = Global.VerticalConstructionAssumptions
        
        # Resolve s_curve_option per asset (override vs global phase)
        _vd_override_arr = np.array(_vd.vd_override if _vd.vd_override else ['No'] * _n_assets)
        _vd_override_yes = _vd_override_arr == 'Yes'
        
        _phase_arr = np.array([
            int(p) if pd.notna(p) and p else 1
            for p in (Asset.ProjectDetails.construction_phase if Asset.ProjectDetails.construction_phase else [1] * _n_assets)
        ])
        
        # Build resolved s_curve_option per asset
        _resolved_s_curve_option = []
        for idx in range(_n_assets):
            if _vd_override_yes[idx]:
                opt = _vd.s_curve_option[idx] if idx < len(_vd.s_curve_option) else 'Pre defined'
            else:
                opt = getattr(_global_vca, f'phase_{_phase_arr[idx]}_s_curve_option', 'Pre defined')
            _resolved_s_curve_option.append(opt if opt else 'Pre defined')
        _resolved_s_curve_option = np.array(_resolved_s_curve_option)
        
        # Build resolved pre_defined_s_curve name per asset
        _resolved_pre_defined_s_curve = []
        for idx in range(_n_assets):
            if _vd_override_yes[idx]:
                name = _vd.vd_pre_defined_s_curve[idx] if idx < len(_vd.vd_pre_defined_s_curve) else None
            else:
                name = getattr(_global_vca, f'phase_{_phase_arr[idx]}_vertical_construction_s_curve_', None)
            _resolved_pre_defined_s_curve.append(name)
        
        # --- 2a: Pre-defined S-curve phasing ---
        # For assets with s_curve_option == 'Pre Defined' or 'Pre defined',
        # use fn_calculate_pre_defined_profile with the resolved profile name.
        _phasing_profile_option_for_predef = [
            "Pre defined" if str(opt).lower().replace(' ', '') == 'predefined' else "None"
            for opt in _resolved_s_curve_option
        ]

        w_vertical_construction_phasing = fn_calculate_pre_defined_profile(
            template=_create_zero_df(),
            profile_option=_phasing_profile_option_for_predef,
            selected_pre_defined_profile=_resolved_pre_defined_s_curve,
            start_dates=w_construction_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )
        
        # --- 2b: User-defined S-curve phasing ---
        # For assets with s_curve_option == 'User Defined' or 'User defined',
        # use fn_calculate_user_defined_profile with s.devco.vertical.phasing.
        _phasing_profile_option_for_userdef = [
            "User defined" if str(opt).lower().replace(' ', '') == 'userdefined' else "None"
            for opt in _resolved_s_curve_option
        ]
        
        # Resolve user-defined duration per asset
        _resolved_user_defined_duration = []
        for idx in range(_n_assets):
            if _vd_override_yes[idx]:
                dur = _vd.vd_user_defined_duration[idx] if idx < len(_vd.vd_user_defined_duration) else 0
            else:
                dur = 0  # Global pre-defined assets won't enter this branch
            _resolved_user_defined_duration.append(int(dur) if pd.notna(dur) and dur else 0)
        
        _user_def_phasing = fn_calculate_user_defined_profile(
            template=_create_zero_df(),
            profile_options=_phasing_profile_option_for_userdef,
            schedules=_cached_user_defined_schedules["vertical_phasing"],
            start_dates=w_construction_start_dates,
            durations=_resolved_user_defined_duration,
            model_timeline_me=model_timeline_me
        )
        
        # Merge: pre-defined where applicable, user-defined where applicable
        _is_user_defined = np.array([
            str(opt).lower().replace(' ', '') == 'userdefined'
            for opt in _resolved_s_curve_option
        ]).reshape(-1, 1)
        
        w_vertical_construction_phasing = pd.DataFrame(
            np.where(_is_user_defined, _user_def_phasing.values, w_vertical_construction_phasing.values),
            index=_template_index,
            columns=_template_columns
        )
        
        # ====================================================================
        # Step 3: Escalation Factors (based on construction start date)
        # ====================================================================
        w_vertical_escalation_percent = _create_zero_df()
        w_vertical_escalation_factor = _create_zero_df()
        w_vertical_escalation_factor.iloc[:, :] = 1

        def pick_profile(_phase_num):
            if pd.isna(_phase_num):
                return None
            
            return getattr(
                Global.VerticalConstructionAssumptions,
                f'phase_{int(_phase_num)}_vertical_construction_esclation_profile',
                None
            )

        w_phase_wise_escalation_profiles = pd.Series(Asset.ProjectDetails.construction_phase).apply(pick_profile)

        w_vertical_construction_escalation_profile = np.where(
            _vd_override_yes,
            pd.Series(Asset.VerticalDevelopmentModule.vd_escalation_profile).astype(str),
            w_phase_wise_escalation_profiles.astype(str)
        )
        
        w_vertical_escalation_percent, w_vertical_escalation_factor = fn_calculate_monthly_escalation_profile(
            escalation_percent_template=w_vertical_escalation_percent,
            escalation_factor_template=w_vertical_escalation_factor,
            selected_escalation_profile=w_vertical_construction_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            model_timeline_me=model_timeline_me
        )

        # Initialize mapping DataFrame
        w_vertical_escalation_factor_mapping = _create_zero_df()

        # --- Normalize and standardize dates first ---
        period_starts_arr = (
            pd.to_datetime(_period_starts)
            .normalize()
            .to_numpy(dtype="datetime64[D]")
        )

        construction_start_dates_arr = (
            pd.to_datetime(w_construction_start_dates)
            .dt.normalize()
            .to_numpy(dtype="datetime64[D]")
        )

        # --- Reshape for broadcasting ---
        construction_start_dates_arr = construction_start_dates_arr[:, np.newaxis]
        period_starts_arr = period_starts_arr[np.newaxis, :]

        # --- Build start flag matrix ---
        start_flag_matrix = (
            construction_start_dates_arr == period_starts_arr
        ).astype(int)

        w_vertical_construction_cost_start_flag = pd.DataFrame(
            start_flag_matrix,
            index=template_asset_timeline.index,
            columns=template_asset_timeline.columns
        )

        # --- Apply escalation mapping ---
        w_vertical_escalation_factor_mapping = (
            w_vertical_escalation_factor
            * w_vertical_construction_cost_start_flag
        )

        # ====================================================================
        # Step 4: Calculate Base Vertical Cost
        # ====================================================================
        w_base_vertical_cost = fn_calculate_base_vertical_cost(
            template=template_asset_timeline,
            cost_basis_series=Asset.VerticalDevelopmentModule.vd_cost_basis,
            cost_per_sqm_series=Asset.VerticalDevelopmentModule.vd_cost_per_sqm,
            gross_floor_area_series=Asset.LandAreaProgram.gross_floor_area,
            built_up_area_series=Asset.LandAreaProgram.built_up_area,
            developable_land_area_series=Asset.LandAreaProgram.developable_land_area,
            number_of_units_series=Asset.LandAreaProgram.units
        )
        
        # ====================================================================
        # Step 5: Phased Construction Amount (base_cost Ã— phasing Ã— escalation)
        # ====================================================================
        # This intermediate result gives cost distributed per phasing profile,
        # used to derive payment amounts.
        w_phased_vertical_amount = fn_calculate_phased_vertical_cost(
            base_cost_series=w_base_vertical_cost,
            payment_schedule_df=w_vertical_construction_phasing,
            escalation_factor_df=w_vertical_escalation_factor_mapping,
            template=_create_zero_df()
        )
        
        # ====================================================================
        # Step 6: Vertical Payment Profile
        # ====================================================================
        # Two modes:
        #   A) payment_follows_s_curve == "Yes" (from Global per phase):
        #      payment = phasing (i.e., w_phased_vertical_amount as-is)
        #   B) Otherwise: payment uses s.devco.vertical.payment user-defined
        #      profile with vd_payment_start_date and vd_payment_duration.
        #      total_amount = w_base_vertical_cost (same cost), re-phased by
        #      payment schedule Ã— escalation.
        #
        # Escalation is ALWAYS based on construction start date (already
        # computed above), NOT payment start date.
        # ====================================================================
        
        # Resolve payment_follows_s_curve flag per asset from Global phase
        _payment_follows_s_curve = np.array([
            str(getattr(_global_vca, f'phase_{_phase_arr[idx]}_payment_follows_s_curve', 'No') or 'No').strip()
            for idx in range(_n_assets)
        ])
        _payment_follows = _payment_follows_s_curve == 'Yes'
        
        # Build payment profile using s.devco.vertical.payment for non-follows assets
        _payment_profile_options = [
            "None" if _payment_follows[idx] else "User defined"
            for idx in range(_n_assets)
        ]
        
        _vd_payment_start = _vd.vd_payment_start_date if _vd.vd_payment_start_date else [None] * _n_assets
        _vd_payment_dur = _vd.vd_payment_duration if _vd.vd_payment_duration else [0] * _n_assets
        
        w_vertical_payment_profile = fn_calculate_user_defined_profile(
            template=_create_zero_df(),
            profile_options=_payment_profile_options,
            schedules=_cached_user_defined_schedules["vertical_payment"],
            start_dates=_vd_payment_start,
            durations=_vd_payment_dur,
            model_timeline_me=model_timeline_me
        )
       
        
        # For assets where payment follows s-curve: payment = phased amount
        # For others: payment = base_cost Ã— payment_profile Ã— escalation_factor
        w_payment_based_vertical = fn_calculate_phased_vertical_cost(
            base_cost_series=w_base_vertical_cost,
            payment_schedule_df=w_vertical_payment_profile,
            escalation_factor_df=w_vertical_escalation_factor_mapping,
            template=_create_zero_df()
        )
        
        # Merge: if payment_follows_s_curve, use phased amount; else use payment-based
        _payment_follows_broadcast = _payment_follows.reshape(-1, 1)
        o_vertical_construction_cost = pd.DataFrame(
            np.where(
                _payment_follows_broadcast,
                w_phased_vertical_amount.values,
                w_payment_based_vertical.values
            ),
            index=_template_index,
            columns=_template_columns
        )

        _record_timing("Vertical construction costs calculated")
        
        # ========================================================================
        # EXPORT VERTICAL DEVELOPMENT COSTS (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS['vertical_construction']:
            vd_export_dict = {
                # Final Outputs
                'o_Vertical_Cost_Payment': o_vertical_construction_cost,
                'w_Phased_Vertical_Amount': w_phased_vertical_amount,
                # Working - Construction Timeline
                'w_Construction_Start': pd.DataFrame({'Construction_Start': w_construction_start_dates}),
                'w_Construction_End': pd.DataFrame({'Construction_End': w_construction_end_dates}),
                'w_Construction_Duration': pd.DataFrame({'Duration_Months': w_construction_durations}),
                # Working - S-Curve / Phasing Inputs
                'w_VD_Override': pd.DataFrame({'VD_Override': Asset.VerticalDevelopmentModule.vd_override}),
                'w_S_Curve_Option': pd.DataFrame({'S_Curve_Option': list(_resolved_s_curve_option)}),
                'w_Pre_Defined_S_Curve': pd.DataFrame({'Pre_Defined_S_Curve': _resolved_pre_defined_s_curve}),
                'w_User_Defined_Duration': pd.DataFrame({'User_Defined_Duration': _resolved_user_defined_duration}),
                # Working - Construction Phasing Profile
                'w_Construction_Phasing': w_vertical_construction_phasing,
                # Working - Payment Profile
                'w_Payment_Profile': w_vertical_payment_profile,
                'w_Payment_Follows_S_Curve': pd.DataFrame({'Payment_Follows_S_Curve': _payment_follows_s_curve}),
                'w_VD_Payment_Start': pd.DataFrame({'Payment_Start': _vd_payment_start}),
                'w_VD_Payment_Duration': pd.DataFrame({'Payment_Duration': _vd_payment_dur}),
                # Working - Escalation (based on construction start date)
                'w_Escalation_Profile': pd.DataFrame({'Escalation_Profile': w_vertical_construction_escalation_profile}),
                'w_Escalation_Percent': w_vertical_escalation_percent,
                'w_Escalation_Factor': w_vertical_escalation_factor,
                'w_Escalation_Factor_Mapping': w_vertical_escalation_factor_mapping,
                # Working - Base Cost Inputs
                'w_Cost_Basis': pd.DataFrame({'Cost_Basis': Asset.VerticalDevelopmentModule.vd_cost_basis}),
                'w_Cost_Per_Sqm': pd.DataFrame({'Cost_Per_Sqm': Asset.VerticalDevelopmentModule.vd_cost_per_sqm}),
                'w_GFA': pd.DataFrame({'GFA': Asset.LandAreaProgram.gross_floor_area}),
                'w_BUA': pd.DataFrame({'BUA': Asset.LandAreaProgram.built_up_area}),
                # Working - Base Cost Calculation
                'w_Base_Vertical_Cost': pd.DataFrame({'Base_Cost': w_base_vertical_cost}),
            }
            _export_to_excel(vd_export_dict, 'devco_vertical_construction', 'Vertical Construction Costs')

        # ========================================================================
        # SUB-MODULE 3.6: SOFT COST & DLP INSURANCE FUNCTIONS
        # ========================================================================
        
        def fn_calculate_soft_and_contingency_cost_amount(
            template: pd.DataFrame,
            
            asset_override: pd.Series,
            
            global_cost_basis: str,
            global_cost_per_sqm: float,
            global_cost_percent: float,
            global_calculation_approach: str,

            asset_cost_basis: pd.Series,
            asset_cost_per_sqm: pd.Series,
            asset_cost_percent: pd.Series,
            asset_calculation_approach: pd.Series,
            
            vertical_construction_df: pd.DataFrame,

            asset_ad_hoc_amount: pd.Series | None = None,
        ):
            """
            Generalized function to calculate acquisition transaction costs.

            Args:
                asset_override (pd.Series): Series indicating override ("Yes"/"No").
                asset_cost_amount (pd.Series): Cost amounts per asset.
                global_allocation_basis (str): Key for allocation basis mapping.
                global_cost_basis (str): Key for cost basis mapping.
                global_ad_hoc_amount (float): Ad-hoc amount for cost type.
                global_cost_per_sqm (float): Cost per sqm for cost type.
                global_cost_percent (float): Percent of acquisition price for cost type.
                global_calculation_approach (str): Calculation approach for cost type.
                acquisition_cost_df (pd.DataFrame): DataFrame of acquisition costs.
            Returns:
                asset_cost_amount (pd.Series): Final calculated cost amounts.
            """
            try:
                if not isinstance(asset_override, pd.Series):
                    asset_override = pd.Series(asset_override)
                
                sar_per_sqm_cost_basis_mapping = _soft_cost_sqm_basis_series_cache

                override_mask = pd.Series(asset_override) == "Yes"
                sar_per_sqm_cost_basis_series = sar_per_sqm_cost_basis_mapping.get(global_cost_basis, pd.Series(0.0, index=template.index))
                percent_of_cost_basis_series = _get_cached_axis_aggregate(vertical_construction_df, "sum")

                sar_per_sqm_cost_basis_filtered = sar_per_sqm_cost_basis_series.where(~override_mask, pd.NA)
                global_sar_per_sqm_amount = sar_per_sqm_cost_basis_filtered * global_cost_per_sqm

                percent_of_cost_basis_filtered = percent_of_cost_basis_series.where(~override_mask, pd.NA)
                global_percent_of_amount = percent_of_cost_basis_filtered * global_cost_percent

                if global_calculation_approach == "SAR/SQM":
                    global_amount = global_sar_per_sqm_amount
                elif global_calculation_approach == "% of Vertical Construction":
                    global_amount = global_percent_of_amount
                else:
                    global_amount = pd.Series(0.0, index=template.index)

                asset_amount = pd.Series(0.0, index=template.index)
                
                # SAR/SQM logic
                sar_mask = asset_calculation_approach == "SAR/SQM"
                bua_mask = asset_cost_basis == "Built Up Area"
                gfa_mask = asset_cost_basis == "Gross Floor Area"

                asset_amount.loc[sar_mask & bua_mask] = _soft_cost_sqm_basis_series_cache["Built Up Area"] * asset_cost_per_sqm
                asset_amount.loc[sar_mask & gfa_mask] = _soft_cost_sqm_basis_series_cache["Gross Floor Area"] * asset_cost_per_sqm

                # Percent logic
                percent_mask = asset_calculation_approach == "% of Vertical Construction"
                asset_amount.loc[percent_mask] = percent_of_cost_basis_series * asset_cost_percent

                if asset_ad_hoc_amount is None:
                    asset_ad_hoc_amount = pd.Series(0, index=template.index)

                ad_hoc_mask = asset_calculation_approach == "Ad-Hoc Amount"
                asset_amount.loc[ad_hoc_mask] = asset_ad_hoc_amount if asset_ad_hoc_amount is not None else 0.0
                
                asset_cost_amount = asset_amount.where(override_mask, global_amount)

                return asset_cost_amount
            except Exception as e:
                print(f"Error in fn_calculate_soft_and_contingency_cost_amount: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount: pd.Series,
            schedule: pd.DataFrame,
            escalation_factor_mapping: pd.DataFrame,
            template: pd.DataFrame
        ) -> pd.DataFrame:
            """
            Calculate the payment schedule for soft or contingency costs.

            Args:
                asset_base_amount (pd.Series): A Series containing the base amounts for each asset.
                schedule (pd.DataFrame): A DataFrame containing the payment schedule for each asset.
                escalation_factor_mapping (pd.DataFrame): A DataFrame containing the escalation factor mapping for each asset.
                template (pd.DataFrame): A DataFrame template initialized with zeros, used to store the calculated payments.

            Returns:
                pd.DataFrame: A DataFrame containing the calculated payment schedule for each asset.
            """
            try:
                # Vectorized calculation: multiply base amount by escalation factors and schedule
                # Use broadcasting with .values to ensure proper alignment
                base_amounts = asset_base_amount.values.reshape(-1, 1)
                escalation_sums = _get_cached_axis_aggregate(escalation_factor_mapping, "sum").values.reshape(-1, 1)

                result_df = pd.DataFrame(
                    base_amounts * escalation_sums * schedule.values,
                    index=template.index,
                    columns=template.columns
                )
                return result_df
            except Exception as e:
                print(f"Error in fn_calculate_soft_and_contingency_cost_payment: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # ========================================================================
        # EXECUTE SOFT COST CALCULATIONS
        # ========================================================================
        
        # ============================================================================================
        # USER DEFINED DESIGN COST PHASING PROFILE
        # ============================================================================================
        
        w_design_cost_payment_user_defined_phasing = _create_zero_df()

        design_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_design_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_design_cost_payment_user_defined_phasing,
            profile_options=design_cost_phasing_option,
            schedules=_cached_user_defined_schedules["design"],
            start_dates=Asset.VerticalDevelopmentModule.design_start_date,
            durations=Asset.VerticalDevelopmentModule.design_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED DESIGN COST PHASING PROFILE
        # ============================================================================================

        w_design_cost_pre_defined_phasing = _create_zero_df()

        # Determine start dates for design cost (vectorized calculation)
        design_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_override) == "Yes",
            Asset.VerticalDevelopmentModule.design_start_date,
            Global.SoftCostAssumptions.design_cost_cost_start_date
        )

        design_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_override) == "Yes",
            "None",
            str(Global.SoftCostAssumptions.design_cost_profiles)
        )

        # Call the generalized function for pre-defined profile calculation
        w_design_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_design_cost_pre_defined_phasing,
            profile_option=design_cost_phasing_option,
            selected_pre_defined_profile=design_pre_defined_profile,
            start_dates=design_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED DESIGN COST PHASING PROFILE
        # ============================================================================================

        o_design_cost_phasing = _create_zero_df()

        o_design_cost_phasing = (
            w_design_cost_payment_user_defined_phasing + w_design_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # DESIGN COST (AMOUNT)
        # ============================================================================================

        design_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.design_cost_override),
            
            global_cost_basis=Global.SoftCostAssumptions.design_cost_cost_basis,
            global_cost_per_sqm=Global.SoftCostAssumptions.design_cost_cost_per_sqm,
            global_cost_percent=Global.SoftCostAssumptions.design_cost_percentage_of_vertical_construction,
            global_calculation_approach=Global.SoftCostAssumptions.design_cost_calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.design_cost_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.design_cost_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.design_cost_percent_of_vertical_construction),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.design_cost_calculation_approach),

            vertical_construction_df=o_vertical_construction_cost
        )

        # ============================================================================================
        # DESIGN COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        design_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_escalation_profile).astype(str),
            str(Global.SoftCostAssumptions.design_cost_escalation_profile)
        )

        w_design_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.design_cost_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.design_cost_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.SoftCostAssumptions.design_cost_calculation_approach == "SAR/SQM")
        )

        (
            w_design_cost_monthly_escalation_percent,
            w_design_cost_monthly_escalation_factors,
            w_design_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=design_cost_start_dates,
            selected_escalation_profile=design_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_design_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # DESIGN COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_design_cost_payment = _create_zero_df()

        o_design_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=design_cost_amount,
            schedule=o_design_cost_phasing,
            escalation_factor_mapping=w_design_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        # ============================================================================================
        # USER DEFINED PERMITTING COST PHASING PROFILE
        # ============================================================================================
        
        w_permitting_cost_payment_user_defined_phasing = _create_zero_df()

        permitting_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_permitting_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_permitting_cost_payment_user_defined_phasing,
            profile_options=permitting_cost_phasing_option,
            schedules=_cached_user_defined_schedules["permitting"],
            start_dates=Asset.VerticalDevelopmentModule.permitting_cost_start_date,
            durations=Asset.VerticalDevelopmentModule.permitting_cost_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED PERMITTING COST PHASING PROFILE
        # ============================================================================================

        w_permitting_cost_pre_defined_phasing = _create_zero_df()

        # Determine start dates for permitting cost (vectorized calculation)
        permitting_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override) == "Yes",
            Asset.VerticalDevelopmentModule.permitting_cost_start_date,
            Global.SoftCostAssumptions.permitting_cost_cost_start_date
        )

        permitting_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override) == "Yes",
            "None",
            str(Global.SoftCostAssumptions.permitting_cost_profiles)
        )

        # Call the generalized function for pre-defined profile calculation
        w_permitting_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_permitting_cost_pre_defined_phasing,
            profile_option=permitting_cost_phasing_option,
            selected_pre_defined_profile=permitting_pre_defined_profile,
            start_dates=permitting_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED PERMITTING COST PHASING PROFILE
        # ============================================================================================

        o_permitting_cost_phasing = _create_zero_df()

        o_permitting_cost_phasing = (
            w_permitting_cost_payment_user_defined_phasing + w_permitting_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # PERMITTING COST (AMOUNT)
        # ============================================================================================

        permitting_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override),
            
            global_cost_basis=Global.SoftCostAssumptions.permitting_cost_cost_basis,
            global_cost_per_sqm=Global.SoftCostAssumptions.permitting_cost_cost_per_sqm,
            global_cost_percent=Global.SoftCostAssumptions.permitting_cost_percentage_of_vertical_construction,
            global_calculation_approach=Global.SoftCostAssumptions.permitting_cost_calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_percent_of_vertical_construction),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_calculation_approach),

            vertical_construction_df=o_vertical_construction_cost
        )

        # ============================================================================================
        # PERMITTING COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        permitting_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_escalation_profile).astype(str),
            str(Global.SoftCostAssumptions.permitting_cost_escalation_profile)
        )

        w_permitting_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.permitting_cost_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.SoftCostAssumptions.permitting_cost_calculation_approach == "SAR/SQM")
        )

        (
            w_permitting_cost_monthly_escalation_percent,
            w_permitting_cost_monthly_escalation_factors,
            w_permitting_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=permitting_cost_start_dates,
            selected_escalation_profile=permitting_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_permitting_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # PERMITTING COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_permitting_cost_payment = _create_zero_df()

        o_permitting_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=permitting_cost_amount,
            schedule=o_permitting_cost_phasing,
            escalation_factor_mapping=w_permitting_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        # ============================================================================================
        # USER DEFINED SUPERVISION COST PHASING PROFILE
        # ============================================================================================
        
        w_supervision_cost_payment_user_defined_phasing = _create_zero_df()

        supervision_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.supervision_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_supervision_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_supervision_cost_payment_user_defined_phasing,
            profile_options=supervision_cost_phasing_option,
            schedules=_cached_user_defined_schedules["supervision"],
            start_dates=Asset.VerticalDevelopmentModule.supervision_start_date,
            durations=Asset.VerticalDevelopmentModule.supervision_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED SUPERVISION COST PHASING PROFILE
        # ============================================================================================

        w_supervision_cost_pre_defined_phasing = _create_zero_df()

        # Determine start dates for supervision cost (vectorized calculation)
        supervision_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.supervision_override) == "Yes",
            Asset.VerticalDevelopmentModule.supervision_start_date,
            Global.SoftCostAssumptions.supervision_cost_cost_start_date
        )

        supervision_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.supervision_override) == "Yes",
            "None",
            str(Global.SoftCostAssumptions.supervision_cost_profiles)
        )

        # Call the generalized function for pre-defined profile calculation
        w_supervision_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_supervision_cost_pre_defined_phasing,
            profile_option=supervision_cost_phasing_option,
            selected_pre_defined_profile=supervision_pre_defined_profile,
            start_dates=supervision_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED SUPERVISION COST PHASING PROFILE
        # ============================================================================================

        o_supervision_cost_phasing = _create_zero_df()

        o_supervision_cost_phasing = (
            w_supervision_cost_payment_user_defined_phasing + w_supervision_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # SUPERVISION COST (AMOUNT)
        # ============================================================================================

        supervision_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.supervision_override),
            
            global_cost_basis=Global.SoftCostAssumptions.supervision_cost_cost_basis,
            global_cost_per_sqm=Global.SoftCostAssumptions.supervision_cost_cost_per_sqm,
            global_cost_percent=Global.SoftCostAssumptions.supervision_cost_percentage_of_vertical_construction,
            global_calculation_approach=Global.SoftCostAssumptions.supervision_cost_calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.supervision_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.supervision_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.supervision_percent_of_vertical_construction),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.supervision_calculation_approach),

            vertical_construction_df=o_vertical_construction_cost
        )

        # ============================================================================================
        # SUPERVISION COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        supervision_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.supervision_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.supervision_escalation_profile).astype(str),
            str(Global.SoftCostAssumptions.supervision_cost_escalation_profile)
        )

        w_supervision_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.supervision_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.supervision_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.SoftCostAssumptions.supervision_cost_calculation_approach == "SAR/SQM")
        )

        (
            w_supervision_cost_monthly_escalation_percent,
            w_supervision_cost_monthly_escalation_factors,
            w_supervision_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=supervision_cost_start_dates,
            selected_escalation_profile=supervision_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_supervision_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # SUPERVISION COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_supervision_cost_payment = _create_zero_df()

        o_supervision_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=supervision_cost_amount,
            schedule=o_supervision_cost_phasing,
            escalation_factor_mapping=w_supervision_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        # ============================================================================================
        # USER DEFINED PROJECT MANAGEMENT FEES COST PHASING PROFILE
        # ============================================================================================
        
        w_pm_fees_cost_payment_user_defined_phasing = _create_zero_df()

        pm_fees_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_pm_fees_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_pm_fees_cost_payment_user_defined_phasing,
            profile_options=pm_fees_cost_phasing_option,
            schedules=_cached_user_defined_schedules["pm_fees"],
            start_dates=Asset.VerticalDevelopmentModule.pm_fees_start_date,
            durations=Asset.VerticalDevelopmentModule.pm_fees_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED PROJECT MANAGEMENT FEES COST PHASING PROFILE
        # ============================================================================================

        w_pm_fees_cost_pre_defined_phasing = _create_zero_df()

        # Determine start dates for pm_fees cost (vectorized calculation)
        pm_fees_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override) == "Yes",
            Asset.VerticalDevelopmentModule.pm_fees_start_date,
            Global.SoftCostAssumptions.pm_fees_cost_start_date
        )

        pm_fees_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override) == "Yes",
            "None",
            str(Global.SoftCostAssumptions.pm_fees_profiles)
        )

        # Call the generalized function for pre-defined profile calculation
        w_pm_fees_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_pm_fees_cost_pre_defined_phasing,
            profile_option=pm_fees_cost_phasing_option,
            selected_pre_defined_profile=pm_fees_pre_defined_profile,
            start_dates=pm_fees_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED PROJECT MANAGEMENT FEES COST PHASING PROFILE
        # ============================================================================================

        o_pm_fees_cost_phasing = _create_zero_df()

        o_pm_fees_cost_phasing = (
            w_pm_fees_cost_payment_user_defined_phasing + w_pm_fees_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # PROJECT MANAGEMENT FEES COST (AMOUNT)
        # ============================================================================================

        pm_fees_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override),
            
            global_cost_basis=Global.SoftCostAssumptions.pm_fees_cost_basis,
            global_cost_per_sqm=Global.SoftCostAssumptions.pm_fees_cost_per_sqm,
            global_cost_percent=Global.SoftCostAssumptions.pm_fees_percentage_of_vertical_construction,
            global_calculation_approach=Global.SoftCostAssumptions.pm_fees_calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.pm_fees_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.pm_fees_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.pm_fees_percent_of_vertical_development),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.pm_fees_calculation_approach),

            vertical_construction_df=o_vertical_construction_cost
        )

        # ============================================================================================
        # PROJECT MANAGEMENT FEES COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        pm_fees_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_escalation_profile).astype(str),
            str(Global.SoftCostAssumptions.pm_fees_escalation_profile)
        )

        w_pm_fees_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.pm_fees_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.pm_fees_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.SoftCostAssumptions.pm_fees_calculation_approach == "SAR/SQM")
        )

        (
            w_pm_fees_cost_monthly_escalation_percent,
            w_pm_fees_cost_monthly_escalation_factors,
            w_pm_fees_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=pm_fees_cost_start_dates,
            selected_escalation_profile=pm_fees_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_pm_fees_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # PROJECT MANAGEMENT FEES COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_pm_fees_cost_payment = _create_zero_df()

        o_pm_fees_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=pm_fees_cost_amount,
            schedule=o_pm_fees_cost_phasing,
            escalation_factor_mapping=w_pm_fees_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        o_design_cost = o_design_cost_payment
        o_permitting_cost = o_permitting_cost_payment
        o_supervision_cost = o_supervision_cost_payment
        o_pm_fees = o_pm_fees_cost_payment

        # Total Soft Costs
        o_total_soft_cost = o_design_cost + o_permitting_cost + o_supervision_cost + o_pm_fees
        _vertical_plus_total_soft_cost = o_vertical_construction_cost.add(o_total_soft_cost, fill_value=0.0)  # OPTIMIZED: reuse one combined DataFrame for repeated downstream %-of-cost basis calculations.

        # ============================================================================================
        # USER DEFINED CONTINGENCY COST PHASING PROFILE
        # ============================================================================================
        
        w_contingency_cost_payment_user_defined_phasing = _create_zero_df()

        contingency_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.contingency_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_contingency_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_contingency_cost_payment_user_defined_phasing,
            profile_options=contingency_cost_phasing_option,
            schedules=_cached_user_defined_schedules["contingency"],
            start_dates=Asset.VerticalDevelopmentModule.contingency_start_date,
            durations=Asset.VerticalDevelopmentModule.contingency_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED CONTINGENCY COST PHASING PROFILE
        # ============================================================================================

        w_contingency_cost_pre_defined_phasing = _create_zero_df()

        # Determine start dates for contingency cost (vectorized calculation)
        contingency_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.contingency_override) == "Yes",
            Asset.VerticalDevelopmentModule.contingency_start_date,
            Global.SoftCostAssumptions.contingency_cost_start_date
        )

        contingency_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.contingency_override) == "Yes",
            "None",
            str(Global.SoftCostAssumptions.contingency_profiles)
        )

        # Call the generalized function for pre-defined profile calculation
        w_contingency_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_contingency_cost_pre_defined_phasing,
            profile_option=contingency_cost_phasing_option,
            selected_pre_defined_profile=contingency_pre_defined_profile,
            start_dates=contingency_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED CONTINGENCY COST PHASING PROFILE
        # ============================================================================================

        o_contingency_cost_phasing = _create_zero_df()

        o_contingency_cost_phasing = (
            w_contingency_cost_payment_user_defined_phasing + w_contingency_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # CONTINGENCY COST (AMOUNT)
        # ============================================================================================

        contingency_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.contingency_override),
            
            global_cost_basis=Global.SoftCostAssumptions.contingency_cost_basis,
            global_cost_per_sqm=Global.SoftCostAssumptions.contingency_cost_per_sqm,
            global_cost_percent=Global.SoftCostAssumptions.contingency_percentage_of_vertical_construction,
            global_calculation_approach=Global.SoftCostAssumptions.contingency_calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.contingency_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.contingency_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.contingency_percent_of_vertical_construction),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.contingency_calculation_approach),

            vertical_construction_df=_vertical_plus_total_soft_cost
        )

        # ============================================================================================
        # CONTINGENCY COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        contingency_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.contingency_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.contingency_escalation_profile).astype(str),
            str(Global.SoftCostAssumptions.contingency_escalation_profile)
        )

        w_contingency_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.contingency_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.contingency_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.SoftCostAssumptions.contingency_calculation_approach == "SAR/SQM")
        )

        (
            w_contingency_cost_monthly_escalation_percent,
            w_contingency_cost_monthly_escalation_factors,
            w_contingency_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=contingency_cost_start_dates,
            selected_escalation_profile=contingency_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_contingency_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # CONTINGENCY COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_contingency_cost_payment = _create_zero_df()

        o_contingency_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=contingency_cost_amount,
            schedule=o_contingency_cost_phasing,
            escalation_factor_mapping=w_contingency_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        o_contingency_cost = o_contingency_cost_payment
        
        # ============================================================================================
        # DLP INSURANCE
        # ============================================================================================

        # ============================================================================================
        # USER DEFINED DLP INSURANCE COST PHASING PROFILE
        # ============================================================================================
        
        w_dlp_insurance_cost_payment_user_defined_phasing = _create_zero_df()

        dlp_insurance_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override) == "Yes",
            "User defined",
            "Pre defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_dlp_insurance_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_dlp_insurance_cost_payment_user_defined_phasing,
            profile_options=dlp_insurance_cost_phasing_option,
            schedules=_cached_user_defined_schedules["dlp_insurance"],
            start_dates=Asset.VerticalDevelopmentModule.dlp_insurance_start_date,
            durations=Asset.VerticalDevelopmentModule.dlp_insurance_duration,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # PRE DEFINED DLP INSURANCE COST PHASING PROFILE
        # ============================================================================================

        w_dlp_insurance_cost_pre_defined_phasing = _create_zero_df()

        w_dlp_insurance_start_date = w_construction_end_dates + pd.to_timedelta(1, unit="D")

        phase_series = pd.Series(Asset.ProjectDetails.construction_phase).fillna(0).astype(int)
        
        w_global_contractor_void_period = phase_series.apply(lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_contractor_void_period", 0))
        w_global_asset_handover_void_period = phase_series.apply(lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_asset_handover_void_period", 0))

        temp_contractor_void_period = pd.Series(
            np.where(
                pd.Series(Asset.VerticalDevelopmentModule.vd_override) == "Yes",
                pd.Series(Asset.VerticalDevelopmentModule.contractor_void_period),
                w_global_contractor_void_period
            )
        )

        temp_handover_void_period = pd.Series(
            np.where(
                pd.Series(Asset.VerticalDevelopmentModule.vd_override) == "Yes",
                pd.Series(Asset.VerticalDevelopmentModule.asset_handover_void_period),
                w_global_asset_handover_void_period
            )
        )

        # Base date (+1 day after construction end)
        w_dlp_insurance_start_date = (
            pd.to_datetime(w_construction_end_dates, errors="coerce")
        )

        # Ensure numeric and safe handling
        void_months = (
            pd.to_numeric(temp_contractor_void_period, errors="coerce").fillna(0)
            + pd.to_numeric(temp_handover_void_period, errors="coerce").fillna(0)
        ).astype(int)

        # Fully vectorized month addition
        w_dlp_insurance_start_date = (
            w_dlp_insurance_start_date.dt.to_period("M") + void_months
        ).dt.to_timestamp()

        # Determine start dates for dlp_insurance cost (vectorized calculation)
        dlp_insurance_cost_start_dates = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override) == "Yes",
            Asset.VerticalDevelopmentModule.dlp_insurance_start_date,
            w_dlp_insurance_start_date
        )

        dlp_insurance_pre_defined_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override) == "Yes",
            "None",
            str(Global.DLPInsurance.dlp_profile)
        )

        # Call the generalized function for pre-defined profile calculation
        w_dlp_insurance_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
            template=w_dlp_insurance_cost_pre_defined_phasing,
            profile_option=dlp_insurance_cost_phasing_option,
            selected_pre_defined_profile=dlp_insurance_pre_defined_profile,
            start_dates=dlp_insurance_cost_start_dates,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED DLP INSURANCE COST PHASING PROFILE
        # ============================================================================================

        o_dlp_insurance_cost_phasing = _create_zero_df()

        o_dlp_insurance_cost_phasing = (
            w_dlp_insurance_cost_payment_user_defined_phasing + w_dlp_insurance_cost_pre_defined_phasing
        )
        
        # ============================================================================================
        # DLP INSURANCE COST (AMOUNT)
        # ============================================================================================

        dlp_insurance_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override),
            
            global_cost_basis=Global.DLPInsurance.cost_basis,
            global_cost_per_sqm=Global.DLPInsurance.cost_per_sqm,
            global_cost_percent=Global.DLPInsurance.percentage_of_vertical,
            global_calculation_approach=Global.DLPInsurance.calculation_approach,
            
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_percent_of_vertical_cost),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_calculation_approach),

            vertical_construction_df=_vertical_plus_total_soft_cost
        )

        # ============================================================================================
        # DLP INSURANCE COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        dlp_insurance_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_escalation_profile).astype(str),
            str(Global.DLPInsurance.escalation_profile)
        )

        w_dlp_insurance_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.dlp_insurance_calculation_approach) == "SAR/SQM").astype(int),
            int(Global.DLPInsurance.calculation_approach == "SAR/SQM")
        )

        (
            w_dlp_insurance_cost_monthly_escalation_percent,
            w_dlp_insurance_cost_monthly_escalation_factors,
            w_dlp_insurance_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=dlp_insurance_cost_start_dates,
            selected_escalation_profile=dlp_insurance_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_dlp_insurance_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # DLP INSURANCE COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_dlp_insurance_cost_payment = _create_zero_df()

        o_dlp_insurance_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=dlp_insurance_cost_amount,
            schedule=o_dlp_insurance_cost_phasing,
            escalation_factor_mapping=w_dlp_insurance_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        o_dlp_insurance = o_dlp_insurance_cost_payment
        
        # ========================================================================
        # SUB-MODULE 3.6b: VOID PERIOD OPEX CALCULATION
        # ========================================================================
        # Void Period Opex during contractor and asset handover void periods.
        #
        # Void Period Start = Construction End (construction_start + duration)
        # Void Duration = Contractor Void Period + Asset Handover Void Period
        #
        # Override Logic for void periods (contractor & handover):
        #   - vd_override == 'Yes': Use asset-level contractor/handover void periods
        #   - vd_override == 'No': Use global phase-level values
        #
        # Other void period opex assumptions (calculation approach, escalation,
        # rate, cost per sqm) are ALWAYS from asset-level.
        #
        # Calculation Approaches:
        #   - % of Vertical Construction: Base VD Cost Ã— rate% (no additional escalation)
        #   - SAR/SQM: Area Ã— cost per sqm (can apply escalation)
        #   - Ad-Hoc Amount: Fixed amount (can apply escalation)
        #
        # Phasing: Distributed uniformly over void period duration
        # ========================================================================

        # ============================================================================================
        # VOID PERIOD OPEX
        # ============================================================================================

        # ============================================================================================
        # USER DEFINED VOID PERIOD OPEX COST PHASING PROFILE
        # ============================================================================================

        w_void_period_opex_start_date = w_construction_end_dates + pd.to_timedelta(1, unit="D")

        phase_series = pd.Series(Asset.ProjectDetails.construction_phase).fillna(0).astype(int)
        
        w_global_contractor_void_period = phase_series.apply(lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_contractor_void_period", 0))
        w_global_asset_handover_void_period = phase_series.apply(lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_asset_handover_void_period", 0))

        temp_contractor_void_period = pd.Series(
            np.where(
                pd.Series(Asset.VerticalDevelopmentModule.vd_override) == "Yes",
                pd.Series(Asset.VerticalDevelopmentModule.contractor_void_period),
                w_global_contractor_void_period
            )
        )

        temp_handover_void_period = pd.Series(
            np.where(
                pd.Series(Asset.VerticalDevelopmentModule.vd_override) == "Yes",
                pd.Series(Asset.VerticalDevelopmentModule.asset_handover_void_period),
                w_global_asset_handover_void_period
            )
        )

        # Base date (+1 day after construction end)
        w_void_period_opex_start_date = (
            pd.to_datetime(w_construction_end_dates, errors="coerce")
        )

        # Ensure numeric and safe handling
        void_months = (
            pd.to_numeric(temp_contractor_void_period, errors="coerce").fillna(0)
            + pd.to_numeric(temp_handover_void_period, errors="coerce").fillna(0)
        ).astype(int)

        w_void_period_opex_cost_payment_user_defined_phasing = _create_zero_df()

        void_period_opex_cost_phasing_option = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_override) == "Yes",
            "User defined",
            "User defined"  
        )

        # Call the generalized function for user-defined profile calculation
        w_void_period_opex_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
            template=w_void_period_opex_cost_payment_user_defined_phasing,
            profile_options=void_period_opex_cost_phasing_option,
            schedules=_cached_user_defined_schedules["void_period"],
            start_dates=w_void_period_opex_start_date,
            durations=void_months,
            model_timeline_me=model_timeline_me
        )

        # ============================================================================================
        # CONSOLIDATED VOID PERIOD OPEX COST PHASING PROFILE
        # ============================================================================================

        o_void_period_opex_cost_phasing = _create_zero_df()

        o_void_period_opex_cost_phasing = w_void_period_opex_cost_payment_user_defined_phasing
        
        # ============================================================================================
        # VOID PERIOD OPEX COST (AMOUNT)
        # ============================================================================================

        void_period_opex_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
            template=template_asset_timeline.copy(),
            
            asset_override=pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_override),
            
            global_cost_basis=Global.VoidPeriodOpex.cost_basis,
            global_cost_per_sqm=Global.VoidPeriodOpex.cost_per_sqm,
            global_cost_percent=Global.VoidPeriodOpex.percentage_of_vertical_construction,
            global_calculation_approach=Global.VoidPeriodOpex.void_period_opex_calculation_approach,
            
            asset_ad_hoc_amount = pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_ad_hoc_amount),
            asset_cost_basis=pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_cost_basis),
            asset_cost_per_sqm=pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_cost_per_sqm),
            asset_cost_percent=pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_rate_of_vertical_construction),
            asset_calculation_approach=pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_calculation_approach),

            vertical_construction_df=_vertical_plus_total_soft_cost
        )

        # ============================================================================================
        # VOID PERIOD OPEX COST (ESCALATION WORKING)
        # ============================================================================================

        # Determine payment profile option for transformation (vectorized calculation)
        void_period_opex_cost_escalation_profile = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_override) == "Yes",
            pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_escalation_profile).astype(str),
            str(Global.VoidPeriodOpex.escalation_profile)
        )

        w_void_period_opex_cost_escalation_applicability_flag = np.where(
            pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_override) == "Yes",
            (pd.Series(Asset.VerticalDevelopmentModule.void_period_opex_calculation_approach) != "% of Vertical Construction").astype(int),
            int(Global.VoidPeriodOpex.void_period_opex_calculation_approach != "% of Vertical Construction")
        )

        (
            w_void_period_opex_cost_monthly_escalation_percent,
            w_void_period_opex_cost_monthly_escalation_factors,
            w_void_period_opex_cost_monthly_escalation_factor_mapping,
        ) = fn_calculate_cost_start_escalation_mapping(
            start_dates=w_void_period_opex_start_date,
            selected_escalation_profile=void_period_opex_cost_escalation_profile,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            escalation_applicability_flag=w_void_period_opex_cost_escalation_applicability_flag,
            template=template_asset_timeline,
        )
        
        # ============================================================================================
        # VOID PERIOD OPEX COST PAYMENT (ESCALATED)
        # ============================================================================================

        o_void_period_opex_cost_payment = _create_zero_df()

        o_void_period_opex_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
            asset_base_amount=void_period_opex_cost_amount,
            schedule=o_void_period_opex_cost_phasing,
            escalation_factor_mapping=w_void_period_opex_cost_monthly_escalation_factor_mapping,
            template=template_asset_timeline.copy()
        )

        o_void_period_opex = o_void_period_opex_cost_payment
        
        _record_timing("Soft costs, DLP insurance and void period opex calculated")
        # ========================================================================
        # EXPORT: VOID PERIOD OPEX
        # ========================================================================

        if _EXPORT_FLAGS['void_period_opex']:

            void_period_opex_export_dict = {

                # --------------------------------------------------------------
                # Final Output
                # --------------------------------------------------------------
                'o_Void_Period_OPEX': o_void_period_opex,

                # --------------------------------------------------------------
                # Working Inputs â€“ Construction Timing
                # --------------------------------------------------------------
                'w_Construction_Start_Dates': pd.DataFrame({
                    'Construction_Start_Date': w_construction_start_dates
                }),

                'w_Construction_Duration': pd.DataFrame({
                    'Construction_Duration': w_construction_durations
                }),

                # --------------------------------------------------------------
                # Working Inputs â€“ Void Duration Logic
                # --------------------------------------------------------------
                'w_Void_Override_Flag': Asset.VerticalDevelopmentModule.void_period_opex_override,

                'w_Contractor_Void_Period': pd.DataFrame({
                    'Contractor_Void_Period': Asset.VerticalDevelopmentModule.contractor_void_period
                }),

                'w_Asset_Handover_Void_Period': pd.DataFrame({
                    'Asset_Handover_Void_Period': Asset.VerticalDevelopmentModule.asset_handover_void_period
                }),

                'w_Construction_Phase': pd.DataFrame({
                    'Construction_Phase': Asset.ProjectDetails.construction_phase
                }),

                # --------------------------------------------------------------
                # Working Inputs â€“ Calculation Approach
                # --------------------------------------------------------------
                'w_Calculation_Approach': pd.DataFrame({
                    'Calculation_Approach': Asset.VerticalDevelopmentModule.void_period_opex_calculation_approach
                }),

                'w_Rate_of_Vertical_Construction': pd.DataFrame({
                    'Rate_of_Vertical': Asset.VerticalDevelopmentModule.void_period_opex_rate_of_vertical_construction
                }),

                'w_AdHoc_Amount': pd.DataFrame({
                    'AdHoc_Amount': Asset.VerticalDevelopmentModule.void_period_opex_ad_hoc_amount
                }),

                'w_Cost_Per_SQM': pd.DataFrame({
                    'Cost_Per_SQM': Asset.VerticalDevelopmentModule.void_period_opex_cost_per_sqm
                }),

                'w_Cost_Basis': pd.DataFrame({
                    'Cost_Basis': Asset.VerticalDevelopmentModule.void_period_opex_cost_basis
                }),

                # --------------------------------------------------------------
                # Working Inputs â€“ Area
                # --------------------------------------------------------------
                'w_Gross_Floor_Area': pd.DataFrame({
                    'Gross_Floor_Area': Asset.LandAreaProgram.gross_floor_area
                }),

                'w_Built_Up_Area': pd.DataFrame({
                    'Built_Up_Area': Asset.LandAreaProgram.built_up_area
                }),

                # --------------------------------------------------------------
                # Working Inputs â€“ Escalation
                # --------------------------------------------------------------
                'w_Escalation_Profile': pd.DataFrame({
                    'Escalation_Profile': Asset.VerticalDevelopmentModule.void_period_opex_escalation_profile
                }),
            }

            _export_to_excel(
                void_period_opex_export_dict,
                'devco_void_period_opex',
                'Void Period OPEX'
            )



        # ========================================================================
        # EXPORT SOFT COSTS (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS['soft_cost_dlp']:
            soft_cost_export_dict = {
                # Final Outputs
                'o_Design_Cost': o_design_cost,
                'o_Permitting_Cost': o_permitting_cost,
                'o_Supervision_Cost': o_supervision_cost,
                'o_PM_Fees': o_pm_fees,
                'o_Contingency_Cost': o_contingency_cost,
                'o_Total_Soft_Cost': o_total_soft_cost,
                'o_DLP_Insurance': o_dlp_insurance,
                'o_Void_Period_Opex': o_void_period_opex,
                # Working - Base Vertical Cost Reference
                'w_Base_Vertical_Cost': pd.DataFrame({'Base_Vertical_Cost': w_base_vertical_cost}),
                # Working - Construction End Dates (for DLP)
                'w_Construction_End': pd.DataFrame({'Construction_End': w_construction_end_dates}),
                # Working - Area References
                'w_GFA': pd.DataFrame({'GFA': Asset.LandAreaProgram.gross_floor_area}),
                'w_BUA': pd.DataFrame({'BUA': Asset.LandAreaProgram.built_up_area}),
            }
            _export_to_excel(soft_cost_export_dict, 'devco_soft_costs_dlp', 'Soft Costs & DLP')

        # ========================================================================
        # SUB-MODULE 3.7: CORPORATE OVERHEAD FUNCTIONS (Moved before Escrow)
        # ========================================================================
        # Corporate Overhead is calculated here so that o_total_coh_capitalized
        # is available for the escrow soft cost payment requirement calculation.
        # ========================================================================
        
        def fn_calculate_corporate_overhead_cost(
            template,
            cost_type,
            override_series,
            ad_hoc_amount_series,
            percent_capitalized_series,
            global_cost_basis,
            global_percentage_of_cost_basis,
            global_percent_capitalized,
            base_cost_df,
            schedule_df
        ):
            try:
                # Ensure alignment
                override_flag = (
                    override_series
                        .fillna("No")
                        .astype(str)
                        .str.strip()
                        .str.lower()
                        .eq("yes")
                        .astype(int)
                )

                # Broadcast row-level series across columns
                override_matrix = pd.DataFrame(
                    np.repeat(override_flag.values[:, None], template.shape[1], axis=1),
                    index=template.index,
                    columns=template.columns
                )

                ad_hoc_matrix = pd.DataFrame(
                    np.repeat(ad_hoc_amount_series.values[:, None], template.shape[1], axis=1),
                    index=template.index,
                    columns=template.columns
                )

                percent_cap_matrix = pd.DataFrame(
                    np.repeat(percent_capitalized_series.values[:, None], template.shape[1], axis=1),
                    index=template.index,
                    columns=template.columns
                )

                # Global calculation
                total_global = base_cost_df * global_percentage_of_cost_basis
                cap_global = total_global * global_percent_capitalized
                exp_global = total_global * (1 - global_percent_capitalized)

                # Override calculation
                total_override = schedule_df * ad_hoc_matrix
                cap_override = total_override * percent_cap_matrix
                exp_override = total_override * (1 - percent_cap_matrix)

                # Combine using vectorized selection
                total_cost = np.where(override_matrix == 1, total_override, total_global)
                capitalized_cost = np.where(override_matrix == 1, cap_override, cap_global)
                expensed_cost = np.where(override_matrix == 1, exp_override, exp_global)

                # Convert back to DataFrame
                total_cost = pd.DataFrame(total_cost, index=template.index, columns=template.columns)
                capitalized_cost = pd.DataFrame(capitalized_cost, index=template.index, columns=template.columns)
                expensed_cost = pd.DataFrame(expensed_cost, index=template.index, columns=template.columns)

                return total_cost, capitalized_cost, expensed_cost

            except Exception as e:
                print(f"Error in fn_calculate_corporate_overhead_cost ({cost_type}): {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # ========================================================================
        # EXECUTE CORPORATE OVERHEAD CALCULATIONS
        # ========================================================================

        _base_costs_dict: Dict[str, pd.DataFrame] = {
            "hard_cost": o_vertical_construction_cost,
            "design_cost": o_design_cost,
            "permitting_cost": o_permitting_cost,
            "supervision_cost": o_supervision_cost,
            "pm_fees": o_pm_fees,
            "contingency_cost": o_contingency_cost
        }

        _coh_type_list = [
            "salaries",
            "it_services",
            "office_rent_and_utilities",
            "professional_services",
            "marketing",
            "sales_cost",
            "additional_expenses"
        ]

        def fn_get_base_cost(
            cost_type: str,
            base_costs_dict: Dict[str, pd.DataFrame],
            corporate_overhead: Global.CorporateOverheadCost
        ) -> pd.DataFrame:

            base_cost_df: pd.DataFrame | None = None

            for key, df in base_costs_dict.items():
                
                attr_name = f"{cost_type}_{key}"
                
                flag = getattr(corporate_overhead, attr_name, "No")

                if flag == "Yes":
                    if base_cost_df is None:
                        base_cost_df = df.copy()
                    else:
                        base_cost_df = base_cost_df.add(df, fill_value=0)

            if base_cost_df is None:
                sample_df = next(iter(base_costs_dict.values()))
                base_cost_df = sample_df * 0

            return base_cost_df

        coh_base_cost_dict: Dict[str, pd.DataFrame] = {
            cost_type: fn_get_base_cost(
                cost_type,
                _base_costs_dict,
                Global.CorporateOverheadCost
            )
            for cost_type in _coh_type_list
        }
        
        # =====================================================================================
        # CORPORATE OVERHEAD CONFIGURATION
        # =====================================================================================

        coh_config = {
            "salaries": {
                "override": pd.Series(Asset.CorporateOverhead.coh_salaries_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_salaries_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_salaries_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_salaries_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_salaries_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.salaries_cost_basis,
                "global_pct": Global.CorporateOverheadCost.salaries_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.salaries_percentage_capitalized,
                "schedule_key": "s.devco.COH.salaries.cost.payment",
                "base_key": "salaries"
            },
            "it_services": {
                "override": pd.Series(Asset.CorporateOverhead.coh_it_services_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_it_services_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_it_services_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_it_services_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_it_services_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.it_services_cost_basis,
                "global_pct": Global.CorporateOverheadCost.it_services_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.it_services_percentage_capitalized,
                "schedule_key": "s.devco.COH.it.services.cost.payment",
                "base_key": "it_services"
            },
            "office_rent_utilities": {
                "override": pd.Series(Asset.CorporateOverhead.coh_office_rent_and_utilities_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_office_rent_and_utilities_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_office_rent_and_utilities_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_office_rent_and_utilities_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_office_rent_and_utilities_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.office_rent_and_utilities_cost_basis,
                "global_pct": Global.CorporateOverheadCost.office_rent_and_utilities_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.office_rent_and_utilities_percentage_capitalized,
                "schedule_key": "s.devco.COH.rent.cost.payment",
                "base_key": "office_rent_and_utilities"
            },
            "professional_services": {
                "override": pd.Series(Asset.CorporateOverhead.coh_professional_services_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_professional_services_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_professional_services_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_professional_services_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_professional_services_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.professional_services_cost_basis,
                "global_pct": Global.CorporateOverheadCost.professional_services_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.professional_services_percentage_capitalized,
                "schedule_key": "s.devco.COH.professional.services.cost.payment",
                "base_key": "professional_services"
            },
            "coh_marketing": {
                "override": pd.Series(Asset.CorporateOverhead.coh_marketing_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_marketing_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_marketing_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_marketing_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_marketing_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.marketing_cost_basis,
                "global_pct": Global.CorporateOverheadCost.marketing_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.marketing_percentage_capitalized,
                "schedule_key": "s.devco.COH.marketing.cost.payment",
                "base_key": "marketing"
            },
            "coh_sales_cost": {
                "override": pd.Series(Asset.CorporateOverhead.coh_sales_cost_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_sales_cost_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_sales_cost_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_sales_cost_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_sales_cost_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.sales_cost_cost_basis,
                "global_pct": Global.CorporateOverheadCost.sales_cost_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.sales_cost_percentage_capitalized,
                "schedule_key": "s.devco.COH.sales.cost.payment",
                "base_key": "sales_cost"
            },
            "additional": {
                "override": pd.Series(Asset.CorporateOverhead.coh_additional_exp_override),
                "start_date": pd.Series(Asset.CorporateOverhead.coh_additional_exp_cost_start_date),
                "duration": pd.Series(Asset.CorporateOverhead.coh_additional_exp_cost_duration),
                "ad_hoc": pd.Series(Asset.CorporateOverhead.coh_additional_exp_ad_hoc_amount),
                "percent_cap": pd.Series(Asset.CorporateOverhead.coh_additional_exp_percent_capitalized),
                "global_basis": Global.CorporateOverheadCost.additonal_expenses_cost_basis,
                "global_pct": Global.CorporateOverheadCost.additonal_expenses_percentage_of_cost_basis,
                "global_cap_pct": Global.CorporateOverheadCost.additonal_expenses_percentage_capitalized,
                "schedule_key": "s.devco.COH.additional.expense.payment",
                "base_key": "additional_expenses"
            }
        }

        # =====================================================================================
        # GENERIC USER DEFINED PROFILE BUILDER
        # =====================================================================================

        def build_coh_user_defined_profile(config):
            return fn_calculate_user_defined_profile(
                template=_create_zero_df(),
                profile_options=np.where(
                    pd.Series(config["override"]).fillna("No").astype(str).str.strip().str.lower().eq("yes"),
                    "User defined",
                    "None"
                ),
                schedules=_assumptions_value_cache.get(config["schedule_key"]),
                start_dates=pd.Series(config["start_date"]),
                durations=pd.Series(config["duration"]),
                model_timeline_me=model_timeline_me
            )

        # =====================================================================================
        # EXECUTION LOOP
        # =====================================================================================

        coh_results = {}

        def fn_process_coh_cost(item):
            cost_type, config = item

            schedule_df = build_coh_user_defined_profile(config)

            total_df, cap_df, exp_df = fn_calculate_corporate_overhead_cost(
                template=_create_zero_df(),
                cost_type=cost_type,
                override_series=config["override"],
                ad_hoc_amount_series=config["ad_hoc"],
                percent_capitalized_series=config["percent_cap"],
                global_cost_basis=config["global_basis"],
                global_percentage_of_cost_basis=config["global_pct"],
                global_percent_capitalized=config["global_cap_pct"],
                base_cost_df=coh_base_cost_dict[config["base_key"]],
                schedule_df=schedule_df
            )

            return cost_type, {
                "total": total_df,
                "capitalized": cap_df,
                "expensed": exp_df
            }

        for cost_type, cost_result in _map_independent_tasks(list(coh_config.items()), fn_process_coh_cost):
            coh_results[cost_type] = cost_result
        
        # =====================================================================================
        # TOTAL CORPORATE OVERHEAD (Dynamic Aggregation)
        # =====================================================================================

        o_total_coh = sum(
            result["total"] for result in coh_results.values()
        )

        o_total_coh_capitalized = sum(
            result["capitalized"] for result in coh_results.values()
        )

        o_total_coh_expensed = sum(
            result["expensed"] for result in coh_results.values()
        )
        
        _record_timing("Corporate overhead calculated")

        # ========================================================================
        # SUB-MODULE 3.8: SALES REVENUE CALCULATION (LandCo-style)
        # ========================================================================
        # This module calculates sales revenue for ALL assets using same approach as LandCo:
        # Sales Revenue = Escalated Price Ã— Total NSA/GLA Ã— Phasing
        # 
        # The revenue is calculated BEFORE escrow calculations so it can be:
        # 1. Used in escrow inflows calculation (for escrow-applicable assets)
        # 2. Used for non-escrow collection (for non-escrow assets)
        # 3. Used as basis for Sales Cost and Marketing Cost (for ALL assets)
        # ========================================================================
        
        _record_timing("Sales revenue module start")
        
        # ============================================================================================
        # SALES PRICE - ESCALATION WORKING
        # ============================================================================================
        
        w_sales_price_monthly_escalation_percent = _create_zero_df()
        w_sales_price_monthly_escalation_factors = _create_zero_df()
        
        w_escalation_profile_for_sales = np.where(
            pd.Series(Asset.Disposal.sales_override) == "Yes",
            pd.Series(Asset.Disposal.sales_escalation_profile),
            Global.SalesInputs.sales_sales_escalation_profile
        )
        
        # Call the generalized function for monthly escalation profile calculation
        w_sales_price_monthly_escalation_percent, w_sales_price_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
            escalation_percent_template=w_sales_price_monthly_escalation_percent,
            escalation_factor_template=w_sales_price_monthly_escalation_factors,
            selected_escalation_profile=w_escalation_profile_for_sales,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            model_timeline_me=model_timeline_me
        )
        
        # ============================================================================================
        # SALES PRICE - ESCALATED
        # ============================================================================================
        
        w_sales_price_escalated = _create_zero_df()
        
        w_sales_price = np.where(
            pd.Series(Asset.Disposal.sales_override) == "Yes",
            pd.Series(Asset.Disposal.sales_value),
            Global.SalesInputs.sales_sales_cost_per_sqm
        )
        
        w_sales_price_escalated = w_sales_price_monthly_escalation_factors.mul(w_sales_price, axis=0)
        
        # ============================================================================================
        # SALES VALUE (Total = Price Ã— GFA)
        # ============================================================================================
        
        # Vectorized sales value calculation: price Ã— GFA
        _gfa_arr = np.array([
            float(Asset.LandAreaProgram.gross_floor_area[i]) if i < len(Asset.LandAreaProgram.gross_floor_area) and pd.notna(Asset.LandAreaProgram.gross_floor_area[i]) else 0.0
            for i in range(_n_assets)
        ], dtype=float)
        _price_arr = np.array([
            float(w_sales_price[i]) if pd.notna(w_sales_price[i]) else 0.0
            for i in range(_n_assets)
        ], dtype=float)
        w_sales_value = pd.Series(_price_arr * _gfa_arr, index=_template_index, dtype=float)
        
        # ============================================================================================
        # USER DEFINED SALES PHASING PROFILE (for ALL assets)
        # ============================================================================================
        
        w_sales_phasing_user_defined_all = _create_zero_df()
        
        # Determine phasing profile option (vectorized calculation)
        w_sales_phasing_option_all = np.where(
            pd.Series(Asset.Disposal.sales_override) == "Yes",
            pd.Series(Asset.Disposal.sales_phasing_option),
            "Pre defined"
        )
        
        w_sales_start_date = (
            pd.Series(Asset.Disposal.escrow_sales_start_date)
            .where(
                pd.Series(Asset.Disposal.sales_override) == "Yes",
                pd.to_datetime(Global.SalesInputs.sales_sales_start_date)
            )
        )
        
        # Call the generalized function for user-defined profile calculation
        w_sales_phasing_user_defined_all = fn_calculate_user_defined_profile(
            template=w_sales_phasing_user_defined_all,
            profile_options=w_sales_phasing_option_all,
            schedules=_cached_user_defined_schedules["sales_phasing"],
            start_dates=w_sales_start_date,
            durations=Asset.Disposal.sales_duration,
            model_timeline_me=model_timeline_me
        )
        
        # ============================================================================================
        # PRE DEFINED SALES PHASING PROFILE (for ALL assets)
        # ============================================================================================
        
        w_sales_phasing_pre_defined_all = _create_zero_df()
        
        # Determine the pre-defined profile name based on override
        w_sales_selected_profile = np.where(
            pd.Series(Asset.Disposal.sales_override) == "Yes",
            pd.Series(Asset.Disposal.sales_phasing_profile),
            Global.SalesInputs.sales_sales_phasing_profile
        )
        
        # Call the generalized function for pre-defined profile calculation
        w_sales_phasing_pre_defined_all = fn_calculate_pre_defined_profile(
            template=w_sales_phasing_pre_defined_all,
            profile_option=w_sales_phasing_option_all,
            selected_pre_defined_profile=w_sales_selected_profile,
            start_dates=w_sales_start_date,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            model_timeline_me=model_timeline_me
        )
        
        # ============================================================================================
        # CONSOLIDATED SALES PHASING PROFILE (for ALL assets)
        # ============================================================================================
        
        o_sales_phasing = _create_zero_df()
        
        # Sum the pre-defined and user-defined profiles
        o_sales_phasing = w_sales_phasing_pre_defined_all + w_sales_phasing_user_defined_all
        
        # ============================================================================================
        # SALES REVENUE CALCULATION (for ROSHN.Developed assets only)
        # ============================================================================================
        # This is the unified sales revenue used as basis for:
        # 1. Sales Cost calculation (all assets)
        # 2. Marketing Cost calculation (all assets)
        # 3. Escrow inflows (after applying escrow mask)
        # 4. Non-escrow collection (after applying non-escrow mask)
        #
        # IMPORTANT: Sales revenue is only calculated for assets with:
        #   Asset.BusinessModel.funding_type == "ROSHN.Developed"
        # Other business models (Forward Funding, Forward Sales) have separate calculations.
        # ============================================================================================
        
        o_sales_revenue = _create_zero_df()
        
        # Create ROSHN.Developed mask - only these assets have sales revenue
        w_is_roshn_developed = pd.Series(
            [(1.0 if str(ft).lower() == 'roshn.developed' else 0.0) for ft in Asset.BusinessModel.funding_type],
            index=_template_index
        )
        w_roshn_developed_mask = w_is_roshn_developed.values.reshape(-1, 1)
        
        # Get Total NSA/GLA with None handling for sales revenue calculation
        w_nsa_gla_for_sales = [0 if x is None else x for x in Asset.LandAreaProgram.total_nsa__gla]
        
        # Sales Revenue = Escalated Price Ã— Total NSA/GLA Ã— Phasing Ã— ROSHN.Developed Mask
        o_sales_revenue = w_sales_price_escalated.mul(w_nsa_gla_for_sales, axis=0) * o_sales_phasing
        o_sales_revenue = pd.DataFrame(
            o_sales_revenue.values * w_roshn_developed_mask,
            index=_template_index,
            columns=_template_columns
        )
        
        # ============================================================================================
        # SALES COLLECTION PHASING (for non-escrow assets)
        # ============================================================================================
        
        w_sales_collection_phasing = _create_zero_df()
        
        w_collection_profile_option = pd.Series("User defined", index=_template_index)
        
        w_sales_collection_phasing = fn_calculate_user_defined_profile(
            template=w_sales_collection_phasing,
            profile_options=w_collection_profile_option,
            schedules=_cached_user_defined_schedules["sales_collection"],
            start_dates=Asset.Disposal.sales_start_date,
            durations=pd.Series(Asset.Disposal.sales_collection_duration).fillna(0.0),
            model_timeline_me=model_timeline_me
        )
        
        # ============================================================================================
        # SALES COLLECTION (for non-escrow assets)
        # ============================================================================================
        # Collection for non-escrow assets = Revenue Ã— Collection Phasing
        # For escrow assets, collection is handled in escrow section
        # ============================================================================================
        
        o_sales_collection_without_escrow = _create_zero_df()
        
        # Calculate sales amount for collection (same as revenue but using collection phasing)
        w_sales_amount_for_collection = w_sales_price_escalated.mul(w_nsa_gla_for_sales, axis=0)
        o_sales_collection_without_escrow = w_sales_collection_phasing * w_sales_amount_for_collection
        
        # Apply non-escrow mask AND ROSHN.Developed mask
        # Only non-escrow assets with ROSHN.Developed business model have collection here
        w_escrow_applicability = pd.Series(Asset.Disposal.escrow_applicability)
        non_escrow_mask = (w_escrow_applicability != "Yes").values.reshape(-1, 1)
        combined_collection_mask = non_escrow_mask * w_roshn_developed_mask
        o_sales_collection_without_escrow = pd.DataFrame(
            o_sales_collection_without_escrow.values * combined_collection_mask,
            index=_template_index,
            columns=_template_columns
        )
        
        _record_timing("Sales revenue calculated")

        # ========================================================================
        # SUB-MODULE 3.9: ESCROW MECHANISM FUNCTIONS
        # ========================================================================
        # This module implements the full escrow mechanism matching LandCo logic:
        # - Construction progress tracking (cumulative S-curve)
        # - Payment absorption based on milestone achievements
        # - Inflows to escrow calculation
        # - Transfer to retention
        # - Funds available for hard/soft costs
        # - Permanent license date flag
        # - Soft/Hard cost opening & closing balances
        # - Reallocation logic between soft and hard costs
        # - Last year release calculations
        # - Cash inflow from off-plan sales
        # - On-plan sales collection post-construction
        # - Escrow setup fees
        #
        # KEY DIFFERENCE FROM LANDCO:
        # - DevCo uses Gross Floor Area for revenue calculation (vs Developable Land Area)
        # - DevCo uses Vertical Construction S-Curve (vs Infrastructure S-Curves)
        # - DevCo business model filter: Asset.Disposal.escrow_applicability == "Yes"
        # ========================================================================
        
        # ========================================================================
        # SUB-MODULE 3.9: ESCROW MECHANISM FUNCTIONS
        # ========================================================================
        
        def fn_get_escrow_applicability_by_category(category_series):
            escrow_mapping = {
                'residential units': Global.EscrowMechanism.escrow_applicability_residential_units,
                'residential land': Global.EscrowMechanism.escrow_applicability_residential_land,
                'commercial land': Global.EscrowMechanism.escrow_applicability_commercial_land,
                'retail': Global.EscrowMechanism.escrow_applicability_retail,
                'schools': Global.EscrowMechanism.escrow_applicability_schools,
                'office': Global.EscrowMechanism.escrow_applicability_office,
                'hospitality': Global.EscrowMechanism.escrow_applicability_hospitality,
                'logistics': Global.EscrowMechanism.escrow_applicability_logistics,
                'cec': Global.EscrowMechanism.escrow_applicability_cec,
                'canal': Global.EscrowMechanism.escrow_applicability_canal,
                'public amenities': Global.EscrowMechanism.escrow_applicability_public_amenities,
                '[placeholder 1]': Global.EscrowMechanism.escrow_applicability_placeholder_1,
                '[placeholder 2]': Global.EscrowMechanism.escrow_applicability_placeholder_2,
                '[placeholder 3]': Global.EscrowMechanism.escrow_applicability_placeholder_3,
                '[placeholder 4]': Global.EscrowMechanism.escrow_applicability_placeholder_4,
            }
            if category_series is None or len(category_series) == 0:
                return []
            category_arr = np.array([
                str(cat).lower().strip() if pd.notna(cat) and cat is not None else ''
                for cat in category_series
            ])
            result = []
            for cat_normalized in category_arr:
                if cat_normalized == '':
                    result.append('No')
                else:
                    applicability = escrow_mapping.get(cat_normalized, 'No')
                    if pd.isna(applicability) or applicability is None:
                        result.append('No')
                    else:
                        result.append(str(applicability))
            return result

        def fn_calculate_construction_end_date_from_scurve(s_curve_percent_df, model_timeline_me):
            cumsum_df = s_curve_percent_df.cumsum(axis=1)
            completed_mask = cumsum_df >= 0.999
            first_completed_col = completed_mask.values.argmax(axis=1)
            has_completion = completed_mask.any(axis=1).values
            num_periods = len(model_timeline_me['Period Start'])
            end_col_indices = np.where(
                has_completion,
                np.minimum(first_completed_col + 1, num_periods - 1),
                -1
            )
            period_starts = model_timeline_me['Period Start'].values
            end_dates = np.where(
                end_col_indices >= 0,
                period_starts[np.maximum(end_col_indices, 0)],
                np.datetime64('NaT')
            )
            end_dates_series = pd.Series(end_dates, index=s_curve_percent_df.index, dtype='datetime64[ns]')
            end_dates_series = end_dates_series - pd.Timedelta(days=1)
            return end_dates_series

        _record_timing("Escrow module start")

        # ============================================================================================
        # CONSTRUCTION PROGRESS (from Vertical Construction Phasing S-Curve)
        # ============================================================================================

        w_construction_progress_percent = w_vertical_construction_phasing.div(
            w_vertical_construction_phasing.sum(axis=1).replace(0, 1), axis=0
        )

        # ============================================================================================
        # CUMULATIVE CONSTRUCTION PROGRESS
        # ============================================================================================

        w_cumulative_construction_progress_percent = w_construction_progress_percent.cumsum(axis=1)

        _ccpp_vals = w_cumulative_construction_progress_percent.values
        _ccpp_prev = np.concatenate([np.zeros((_ccpp_vals.shape[0], 1)), _ccpp_vals[:, :-1]], axis=1)

        w_cumulative_construction_progress_percent = pd.DataFrame(
            np.where(
                _ccpp_prev >= 1 - 1e-6,
                0.0,
                np.where(_ccpp_vals > 1 - 1e-6, 1.0, _ccpp_vals)
            ),
            index=_template_index,
            columns=_template_columns
        )
        w_cumulative_construction_progress_percent = np.ceil(w_cumulative_construction_progress_percent * 1000) / 1000

        # ============================================================================================
        # HANDOVER FLAG (vectorized)
        # ============================================================================================

        _cumsum_values = w_cumulative_construction_progress_percent.values
        _construction_completion_mask = _cumsum_values >= 1 - 1e-6
        _first_completion_col = np.where(
            _construction_completion_mask.any(axis=1),
            _construction_completion_mask.argmax(axis=1),
            -1
        )
        _period_ends_me = model_timeline_me['Period End'].values
        _period_starts_me = model_timeline_me['Period Start'].values

        _construction_end_dates = np.where(
            _first_completion_col >= 0,
            _period_ends_me[np.maximum(_first_completion_col, 0)],
            np.datetime64('NaT')
        )
        # mask out invalid indices
        _construction_end_dates = np.where(_first_completion_col >= 0, _construction_end_dates, np.datetime64('NaT'))
        w_construction_end_for_handover = pd.to_datetime(pd.Series(_construction_end_dates, index=_template_index))

        phase_series_for_handover = pd.Series(Asset.ProjectDetails.construction_phase).fillna(0).astype(int)
        w_global_contractor_void = phase_series_for_handover.map(
            lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_contractor_void_period", 0)
        )
        w_global_handover_void = phase_series_for_handover.map(
            lambda phase: getattr(Global.VerticalConstructionAssumptions, f"phase_{int(phase)}_asset_handover_void_period", 0)
        )

        _vd_override_mask = (pd.Series(Asset.VerticalDevelopmentModule.vd_override) == "Yes").values
        temp_contractor_void_for_handover = pd.Series(
            np.where(
                _vd_override_mask,
                pd.to_numeric(pd.Series(Asset.VerticalDevelopmentModule.contractor_void_period), errors='coerce').fillna(0),
                pd.to_numeric(w_global_contractor_void, errors='coerce').fillna(0)
            )
        )
        temp_handover_void_for_handover = pd.Series(
            np.where(
                _vd_override_mask,
                pd.to_numeric(pd.Series(Asset.VerticalDevelopmentModule.asset_handover_void_period), errors='coerce').fillna(0),
                pd.to_numeric(w_global_handover_void, errors='coerce').fillna(0)
            )
        )

        void_months_for_handover = (
            pd.to_numeric(temp_contractor_void_for_handover, errors="coerce").fillna(0)
            + pd.to_numeric(temp_handover_void_for_handover, errors="coerce").fillna(0)
        ).astype(int).values

        # Vectorized handover date: add void months using offsets via MonthOffset broadcasting
        _construction_end_ns = w_construction_end_for_handover.values.astype('datetime64[ns]').astype(np.int64)
        _void_ns = (void_months_for_handover * 30 * 24 * 3600 * int(1e9)).astype(np.int64)  # approximate
        # Use pandas for accurate month arithmetic (MonthOffset not vectorizable directly)
        _handover_dates_list = np.empty(len(_template_index), dtype='datetime64[ns]')
        for _i in range(len(_template_index)):
            _ce = w_construction_end_for_handover.iloc[_i]
            _vm = int(void_months_for_handover[_i])
            if pd.notna(_ce):
                _handover_dates_list[_i] = np.datetime64(_ce + pd.DateOffset(months=_vm))
            else:
                _handover_dates_list[_i] = np.datetime64('NaT')
        w_asset_handover_date = pd.Series(_handover_dates_list, index=_template_index, dtype='datetime64[ns]')

        _period_starts_2d = _period_starts_me.reshape(1, -1)
        _period_ends_2d = _period_ends_me.reshape(1, -1)
        _handover_dates_2d = w_asset_handover_date.values.reshape(-1, 1)
        _handover_arr = (
            (_handover_dates_2d >= _period_starts_2d) & (_handover_dates_2d <= _period_ends_2d)
        ).astype(float)
        o_handover_flag = pd.DataFrame(_handover_arr, index=_template_index, columns=_template_columns)

        # ============================================================================================
        # CALCULATE CONSTRUCTION END DATES FROM S-CURVES
        # ============================================================================================

        w_construction_end_date_for_escrow = fn_calculate_construction_end_date_from_scurve(
            w_construction_progress_percent, model_timeline_me
        )

        # ============================================================================================
        # ESCROW SALES REVENUE
        # ============================================================================================

        escrow_mask_for_revenue = (w_escrow_applicability == "Yes").values.reshape(-1, 1)
        o_escrow_sales_revenue = pd.DataFrame(
            o_sales_revenue.values * escrow_mask_for_revenue,
            index=_template_index,
            columns=_template_columns
        )

        # ============================================================================================
        # PAYMENT ABSORPTION (vectorized, no per-column Python overhead for date conversions)
        # ============================================================================================

        o_payment_absorption = _create_zero_df()
        o_payment_absorption_forward_funding = _create_zero_df()

        _period_starts_escrow = _period_starts_me
        _period_ends_escrow = _period_ends_me
        _construction_start_arr = pd.to_datetime(w_construction_start_dates).values.reshape(-1, 1)
        _construction_end_arr = w_construction_end_date_for_escrow.values.reshape(-1, 1)
        _cumulative_progress = w_cumulative_construction_progress_percent.values
        _escrow_applicability_arr = (w_escrow_applicability == 'Yes').values.reshape(-1, 1)  # (n_assets, 1)

        _milestones = np.array([
            Global.EscrowMechanism.sixth_installment_construction_milestone,
            Global.EscrowMechanism.fifth_installment_construction_milestone,
            Global.EscrowMechanism.fourth_installment_construction_milestone,
            Global.EscrowMechanism.third_installment_construction_milestone,
            Global.EscrowMechanism.second_installment_construction_milestone,
            Global.EscrowMechanism.first_installment_construction_milestone,
            Global.EscrowMechanism.downpayment_construction_milestone,
        ], dtype=float)
        _cumulative_payments = np.array([
            Global.EscrowMechanism.sixth_installment_cumulative_payment,
            Global.EscrowMechanism.fifth_installment_cumulative_payment,
            Global.EscrowMechanism.fourth_installment_cumulative_payment,
            Global.EscrowMechanism.third_installment_cumulative_payment,
            Global.EscrowMechanism.second_installment_cumulative_payment,
            Global.EscrowMechanism.first_installment_cumulative_payment,
            Global.EscrowMechanism.downpayment_cumulative_payment,
        ], dtype=float)
        _downpayment = float(Global.EscrowMechanism.downpayment_cumulative_payment)
        _sixth_installment_milestone = float(Global.EscrowMechanism.sixth_installment_construction_milestone)

        n_rows = len(_template_index)
        n_cols = len(model_timeline_me)

        # Fully vectorized payment absorption: (n_assets, n_cols)
        _period_starts_bc = _period_starts_escrow.reshape(1, -1)   # (1, n_cols)
        _period_ends_bc   = _period_ends_escrow.reshape(1, -1)      # (1, n_cols)

        _cumulative_progress_limit = np.zeros_like(_cumulative_progress)
        if _cumulative_progress.shape[1] > 1:
            _cumulative_progress_limit[:, 1:] = np.maximum.accumulate(_cumulative_progress[:, :-1], axis=1)

        _in_construction_period = (
            (_period_starts_bc >= _construction_start_arr) &
            (_cumulative_progress_limit != 1)
        )  # (n_assets, n_cols)

        _in_downpayment_period = (
            (_period_starts_bc >= _construction_start_arr) &
            (_period_starts_bc < _construction_end_arr)
        )  # (n_assets, n_cols)

        # Build values array fully vectorized: start from downpayment, apply milestones in order
        _values_full = np.where(_in_downpayment_period, _downpayment, 0.0)  # (n_assets, n_cols)

        _milestones_rev = _milestones[::-1]
        _payments_rev = _cumulative_payments[::-1]
        for _m, _p in zip(_milestones_rev, _payments_rev):
            if np.isnan(_m) or np.isnan(_p):
                continue
            if _m == _sixth_installment_milestone:
                _cond = (_cumulative_progress == _m)
            else:
                _cond = (_cumulative_progress >= _m)
            _values_full = np.where(_cond, _p, _values_full)

        _payment_absorption_arr = np.where(
            _in_construction_period & _escrow_applicability_arr,
            _values_full,
            0.0
        )
        _payment_absorption_ff_arr = np.where(
            _in_construction_period,
            _values_full,
            0.0
        )

        o_payment_absorption = pd.DataFrame(_payment_absorption_arr, index=_template_index, columns=_template_columns)
        o_payment_absorption_forward_funding = pd.DataFrame(_payment_absorption_ff_arr, index=_template_index, columns=_template_columns)

        # ============================================================================================
        # ESCROW FLAG AND TEMPORARY LICENSE FLAG (vectorized)
        # ============================================================================================

        w_escrow_applicability_by_category = fn_get_escrow_applicability_by_category(
            category_series=Asset.ProjectDetails.sub_category
        )

        _asset_escrow_arr = np.array([
            Asset.Disposal.escrow_applicability[i] if i < len(Asset.Disposal.escrow_applicability) else 'No'
            for i in range(n_rows)
        ])
        _category_escrow_arr = np.array([
            w_escrow_applicability_by_category[i] if i < len(w_escrow_applicability_by_category) else 'No'
            for i in range(n_rows)
        ])
        # Use asset-level if it is 'yes'/'no', else fall back to category
        _asset_escrow_lower = np.array([str(v).lower() for v in _asset_escrow_arr])
        _use_asset = np.isin(_asset_escrow_lower, ['yes', 'no'])
        _escrow_val_arr = np.where(_use_asset, _asset_escrow_lower, np.array([str(v).lower() for v in _category_escrow_arr]))

        _escrow_flag_vals = (_escrow_val_arr == 'yes').astype(float)
        w_escrow_flag = pd.Series(_escrow_flag_vals, index=_template_index, dtype='float64')

        _sales_start_dates_arr = (
            pd.to_datetime(pd.Series(Asset.Disposal.escrow_sales_start_date))
            .where(
                pd.Series(Asset.Disposal.sales_override) == "Yes",
                pd.to_datetime(Global.SalesInputs.sales_sales_start_date)
            )
        ).values

        _temp_license_vals = np.where(_escrow_flag_vals == 1.0, _sales_start_dates_arr, np.datetime64('NaT'))
        w_temporary_license_flag = pd.Series(_temp_license_vals, index=_template_index, dtype='datetime64[ns]')

        # ============================================================================================
        # INFLOWS TO ESCROW (vectorized â€” eliminate column loop)
        # ============================================================================================

        o_inflows_to_escrow = _create_zero_df()

        _payment_absorption_arr2 = o_payment_absorption.values
        _sales_revenue_arr2 = o_escrow_sales_revenue.values
        _escrow_flag_arr2 = w_escrow_flag.values  # (n_rows,)
        _cumulative_progress_arr = w_cumulative_construction_progress_percent.values

        _sales_cumulative = np.cumsum(_sales_revenue_arr2, axis=1)   # (n_rows, n_cols)

        _progress_limit = np.zeros_like(_cumulative_progress_arr)
        if _cumulative_progress_arr.shape[1] > 1:
            _progress_limit[:, 1:] = np.maximum.accumulate(_cumulative_progress_arr[:, :-1], axis=1)

        # Flag: construction not yet complete
        _calc_flag_arr = np.where(_progress_limit >= (1 - 1e-3), 0.0, _escrow_flag_arr2.reshape(-1, 1))

        # Payment direction: current vs previous
        _payment_prev = np.concatenate([np.zeros((n_rows, 1)), _payment_absorption_arr2[:, :-1]], axis=1)

        # Two candidate values per cell
        _candidate_same = _payment_absorption_arr2 * _sales_revenue_arr2   # payment <= prev
        # candidate_up requires cumulative inflows up to previous col â€” must be computed sequentially
        _inflows_arr2 = np.zeros((n_rows, n_cols), dtype=float)
        _inflows_cumulative2 = np.zeros(n_rows, dtype=float)

        for col in range(n_cols):
            _p_curr = _payment_absorption_arr2[:, col]
            _p_prev = _payment_prev[:, col]
            _r_cumul = _sales_cumulative[:, col]
            _r_curr  = _sales_revenue_arr2[:, col]
            _cf      = _calc_flag_arr[:, col]

            _val = np.where(
                _p_curr <= _p_prev,
                _p_curr * _r_curr,
                _p_curr * _r_cumul - _inflows_cumulative2
            )
            _inflows_arr2[:, col] = _val * _cf
            _inflows_cumulative2 += _inflows_arr2[:, col]

        o_inflows_to_escrow = pd.DataFrame(_inflows_arr2, index=_template_index, columns=_template_columns)

        # ============================================================================================
        # TRANSFER TO RETENTION / FUNDS AVAILABLE
        # ============================================================================================

        retention_reserve_pct     = Global.EscrowMechanism.retention_reserve_retention_reserve
        soft_cost_utilization_pct = Global.EscrowMechanism.admin_and_soft_cost_admin_and_soft_cost
        hard_cost_utilization_pct = Global.EscrowMechanism.hard_cost_hard_cost

        o_transfer_to_retention        = o_inflows_to_escrow * retention_reserve_pct
        o_funds_available_for_soft_cost = o_inflows_to_escrow * soft_cost_utilization_pct
        o_funds_available_for_hard_cost = o_inflows_to_escrow * hard_cost_utilization_pct

        # ============================================================================================
        # PERMANENT LICENSE DATE FLAG (vectorized)
        # ============================================================================================

        w_temporary_license_date = w_temporary_license_flag.min()
        approval_duration = Global.EscrowMechanism.approval_duration_approval_duration
        w_permanent_license_date = w_temporary_license_date + pd.DateOffset(months=int(approval_duration))

        _period_starts_license = pd.to_datetime(model_timeline_me['Period Start']).dt.normalize().values
        _permanent_license_date_val = (
            np.datetime64(pd.to_datetime(w_permanent_license_date).normalize())
            if w_permanent_license_date is not pd.NaT else pd.NaT
        )
        _license_flag_arr = (_period_starts_license >= _permanent_license_date_val).astype(float)
        w_permanent_license_date_flag = pd.DataFrame(
            np.broadcast_to(_license_flag_arr.reshape(1, -1), (n_rows, n_cols)).copy(),
            index=_template_index,
            columns=_template_columns
        )

        # ============================================================================================
        # ESCROW PAYMENT REQUIREMENTS â€” precompute LandCo CAPEX split
        # ============================================================================================

        _landco_hard_keys = {
            "Land Acquisition Cost",
            "Primary Infrastructure Cost S-Curve",
            "Secondary Infrastructure Cost S-Curve",
        }

        def _coerce_landco_capex_df(value: Any) -> pd.DataFrame:
            if not isinstance(value, pd.DataFrame):
                return _create_zero_df()
            return (
                value.reindex(index=_template_index, columns=_template_columns)
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
            )

        _landco_hard_requirement = _create_zero_df()
        _landco_soft_requirement = _create_zero_df()
        if isinstance(landco_capex, dict):
            for capex_key, capex_value in landco_capex.items():
                if not isinstance(capex_value, pd.DataFrame):
                    continue
                capex_df = _coerce_landco_capex_df(capex_value)
                if capex_key in _landco_hard_keys:
                    _landco_hard_requirement = _landco_hard_requirement.add(capex_df, fill_value=0.0)
                else:
                    _landco_soft_requirement = _landco_soft_requirement.add(capex_df, fill_value=0.0)

        w_soft_cost_payment_requirement = (
            o_total_soft_cost
            .add(o_total_coh_capitalized, fill_value=0.0)
            .add(_landco_soft_requirement, fill_value=0.0)
        )
        w_hard_cost_payment_requirement = (
            o_vertical_construction_cost
            .add(_landco_hard_requirement, fill_value=0.0)
        )

        # ============================================================================================
        # ESCROW DATE CALCULATIONS (sales duration, construction end, key release dates)
        # ============================================================================================

        escrow_applicability_flags = pd.Series(Asset.Disposal.escrow_applicability)
        escrow_mask = (escrow_applicability_flags == "Yes") & (w_escrow_flag == 1.0)

        _sales_revenue_arr3 = o_sales_revenue.values
        _has_revenue = _sales_revenue_arr3 > 0
        _first_revenue_col = np.where(_has_revenue.any(axis=1), _has_revenue.argmax(axis=1), -1)
        _reversed_has_revenue = np.flip(_has_revenue, axis=1)
        _last_revenue_col = np.where(
            _has_revenue.any(axis=1),
            _has_revenue.shape[1] - 1 - _reversed_has_revenue.argmax(axis=1),
            -1
        )

        temp_sales_start_date_raw = (
            pd.Series(Asset.Disposal.escrow_sales_start_date)
            .where(pd.Series(Asset.Disposal.sales_override) == "Yes",
                   pd.to_datetime(Global.SalesInputs.sales_sales_start_date))
        )
        temp_sales_start_date = pd.Series(
            temp_sales_start_date_raw, index=_template_index, dtype='datetime64[ns]'
        ).where(w_escrow_flag == 1.0, pd.NaT)

        temp_post_construction_end_date = (
            w_construction_end_date_for_escrow + pd.Timedelta(days=1)
        ).where(escrow_mask, pd.NaT)

        # Soft cost end date
        soft_cost_payment = o_total_soft_cost.astype(float)
        soft_cost_cumsum = soft_cost_payment.cumsum(axis=1)
        soft_cost_total  = soft_cost_payment.sum(axis=1)
        completion_mask  = soft_cost_cumsum.round(3).eq(soft_cost_total.round(3), axis=0)
        _scc_first = completion_mask.values.argmax(axis=1)
        _scc_has   = completion_mask.any(axis=1).values
        _scc_end_idx = np.where(_scc_has, np.minimum(_scc_first + 1, n_cols - 1), -1)
        temp_post_soft_cost_end_date = pd.Series(
            np.where(_scc_end_idx >= 0, _period_starts_me[np.maximum(_scc_end_idx, 0)], np.datetime64('NaT')),
            index=_template_index, dtype='datetime64[ns]'
        )

        _period_ends_norm = model_timeline_me['Period End'].dt.normalize().values
        temp_sales_exit_date = pd.Series(
            np.where(
                (_last_revenue_col >= 0) & (w_escrow_flag == 1.0),
                _period_ends_norm[np.clip(_last_revenue_col, 0, len(_period_ends_norm) - 1)],
                np.datetime64('NaT')
            ),
            index=_template_index, dtype='datetime64[ns]'
        )

        last_unit_exit_date = max(
            temp_sales_exit_date.max()            if pd.notna(temp_sales_exit_date.max())            else pd.Timestamp.min,
            temp_post_construction_end_date.max() if pd.notna(temp_post_construction_end_date.max()) else pd.Timestamp.min,
            temp_post_soft_cost_end_date.max()    if pd.notna(temp_post_soft_cost_end_date.max())    else pd.Timestamp.min,
        )

        retention_release_duration   = Global.EscrowMechanism.retention_release_grace_period_retention_release_grace_period
        retention_release_final_date = (
            last_unit_exit_date
            + pd.DateOffset(months=int(retention_release_duration))
            + pd.DateOffset(days=1)
        ).replace(day=1)

        last_year_release_option   = Global.EscrowMechanism.last_year_release_option_last_year_release_option
        last_year_release_duration = Global.EscrowMechanism.last_year_release_post_construction_last_year_release_post_construction

        if last_year_release_option == "Retention Release Date":
            last_year_release_date = retention_release_final_date
        else:
            last_year_release_date = (
                temp_post_construction_end_date.max()
                + pd.DateOffset(months=int(last_year_release_duration))
            )

        # ============================================================================================
        # MAIN ESCROW COLUMN LOOP
        # Pre-normalize all date scalars ONCE before the loop to avoid repeated conversion overhead
        # ============================================================================================

        # ============================================================================================
        # MAIN ESCROW CALCULATIONS (fully vectorized â€” no column loop)
        # ============================================================================================

        temp_release_flags = (w_construction_progress_percent.sum(axis=1).round(3) >= 0.999)
        reallocation_flag = 1.0 if str(Global.EscrowMechanism.escrow_applicability_reallocation_option).lower() == "yes" else 0.0

        _last_year_release_date_norm = (
            pd.to_datetime(last_year_release_date).normalize()
            if last_year_release_date is not pd.NaT else pd.NaT
        )
        _retention_release_final_date_norm = pd.to_datetime(retention_release_final_date).normalize()
        _temporary_license_date_norm = (
            pd.to_datetime(w_temporary_license_date).normalize()
            if pd.notna(w_temporary_license_date) else pd.NaT
        )

        _period_starts_norm = pd.to_datetime(model_timeline_me['Period Start']).dt.normalize().values

        _sales_revenue_sum         = o_escrow_sales_revenue.sum(axis=1)
        _inflows_to_escrow_sum     = o_inflows_to_escrow.sum(axis=1)
        escrow_setup_fee_rate      = Global.EscrowMechanism.escrow_applicability_escrow_set_up_fee
        _escrow_setup_fee_amount_vals = (escrow_setup_fee_rate * _sales_revenue_sum).values
        _escrow_setup_eligible_vals   = (_inflows_to_escrow_sum != 0.0).values

        _cumulative_retention_vals = o_transfer_to_retention.cumsum(axis=1).values

        _perm_license_flag  = w_permanent_license_date_flag.values          # (n_rows, n_cols)
        _funds_soft         = o_funds_available_for_soft_cost.values
        _funds_hard         = o_funds_available_for_hard_cost.values
        _soft_req_raw       = w_soft_cost_payment_requirement.values
        _hard_req_raw       = w_hard_cost_payment_requirement.values
        _temp_release_flags = temp_release_flags.values                      # (n_rows,)

        # â”€â”€ Boolean column flags (scalar comparisons, done once) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _is_last_year_col      = (_period_starts_norm == _last_year_release_date_norm)       # (n_cols,)
        _is_retention_col      = np.array([
            pd.Timestamp(p).date() == pd.Timestamp(_retention_release_final_date_norm).date()
            for p in _period_starts_norm
        ], dtype=bool)
        _is_temp_license_col   = (_period_starts_norm == _temporary_license_date_norm)       # (n_cols,)

        # â”€â”€ Soft cost: cumulative-scan recurrence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Recurrence: cumul_req[col] = req[col] + addl_req[col-1]
        #             addl_req[col]  = cumul_req[col] - payment[col]   (when perm_license active)
        #             addl_req[col]  = cumul_req[col]                  (when perm_license inactive)
        #
        # Because perm_license_flag is a step function (0 then 1), we can split:
        # Phase 1 (flag==0): payment=0, addl_req accumulates requirement
        # Phase 2 (flag==1): standard min/max logic
        # We solve this with a vectorized scan using np operations.

        # Opening balances are the cumsum of funds MINUS payments â€” but payments depend on
        # opening balance. We handle the scan column-by-column but purely with numpy slices
        # (no Python-object overhead, no pd.to_datetime, no conditional branching per col).

        _soft_opening_balance                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _soft_cost_total_availability        = np.empty((n_rows, n_cols), dtype=np.float64)
        _soft_cost_cumulative_requirement    = np.empty((n_rows, n_cols), dtype=np.float64)
        _soft_cost_payment_from_escrow       = np.empty((n_rows, n_cols), dtype=np.float64)
        _additional_requirements_for_soft    = np.zeros((n_rows, n_cols), dtype=np.float64)
        _amount_available_for_reallocation   = np.empty((n_rows, n_cols), dtype=np.float64)
        _hard_opening_balance                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _hard_cost_total_availability        = np.empty((n_rows, n_cols), dtype=np.float64)
        _hard_cost_cumulative_requirement    = np.empty((n_rows, n_cols), dtype=np.float64)
        _hard_cost_payment_from_escrow       = np.empty((n_rows, n_cols), dtype=np.float64)
        _additional_requirements_for_hard    = np.zeros((n_rows, n_cols), dtype=np.float64)
        _reallocation_amount                 = np.empty((n_rows, n_cols), dtype=np.float64)
        _reallocated_funds_hard              = np.empty((n_rows, n_cols), dtype=np.float64)
        _additional_req_after_alloc          = np.zeros((n_rows, n_cols), dtype=np.float64)
        _avail_after_hard_payment            = np.empty((n_rows, n_cols), dtype=np.float64)
        _last_yr_release_hard                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _hard_closing_balance                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _avail_after_soft_and_reallocated    = np.empty((n_rows, n_cols), dtype=np.float64)
        _last_yr_release_soft                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _soft_closing_balance                = np.zeros((n_rows, n_cols), dtype=np.float64)
        _retention_release                   = np.zeros((n_rows, n_cols), dtype=np.float64)
        _cash_inflow                         = np.empty((n_rows, n_cols), dtype=np.float64)
        _escrow_setup_fees                   = np.zeros((n_rows, n_cols), dtype=np.float64)

        # Pre-extract column slices as contiguous C arrays for cache efficiency
        _pf = np.ascontiguousarray(_perm_license_flag)
        _fs = np.ascontiguousarray(_funds_soft)
        _fh = np.ascontiguousarray(_funds_hard)
        _sr = np.ascontiguousarray(_soft_req_raw)
        _hr = np.ascontiguousarray(_hard_req_raw)

        for col in range(n_cols):
            pf  = _pf[:, col]
            fs  = _fs[:, col]
            fh  = _fh[:, col]

            # â”€â”€ SOFT â”€â”€
            soa = _soft_opening_balance[:, col]              # already set (0 or prev closing)
            sta = soa + fs
            _soft_cost_total_availability[:, col] = sta

            scr = _sr[:, col] + (_additional_requirements_for_soft[:, col - 1] if col else 0.0)
            _soft_cost_cumulative_requirement[:, col] = scr

            spf = np.minimum(sta, scr * pf)
            spf = np.where(spf < 0.0, 0.0, spf)
            _soft_cost_payment_from_escrow[:, col] = spf

            _additional_requirements_for_soft[:, col] = np.where(pf == 0.0, scr, scr - spf)
            aar = sta - spf
            _amount_available_for_reallocation[:, col] = aar

            # â”€â”€ HARD â”€â”€
            hoa = _hard_opening_balance[:, col]
            hta = hoa + fh
            _hard_cost_total_availability[:, col] = hta

            hcr = _hr[:, col] + (_additional_req_after_alloc[:, col - 1] if col else 0.0)
            _hard_cost_cumulative_requirement[:, col] = hcr

            hpf = np.minimum(hta, hcr * pf)
            hpf = np.where(hpf < 0.0, 0.0, hpf)
            _hard_cost_payment_from_escrow[:, col] = hpf

            adh = np.where(pf == 0.0, hcr, hcr - hpf)
            _additional_requirements_for_hard[:, col] = adh

            # â”€â”€ REALLOCATION â”€â”€
            ra = aar * pf * reallocation_flag
            _reallocation_amount[:, col] = ra
            rf = np.minimum(ra, adh)
            _reallocated_funds_hard[:, col] = rf
            _additional_req_after_alloc[:, col] = np.where((hcr - hpf - rf) < 0.0, 0.0, hcr - hpf - rf)

            avh = np.where((hta - hpf) < 0.0, 0.0, hta - hpf)
            _avail_after_hard_payment[:, col] = avh

            # â”€â”€ LAST YEAR RELEASE â”€â”€
            lyr = _is_last_year_col[col]
            lyrh = np.where(lyr & _temp_release_flags, avh, 0.0)
            _last_yr_release_hard[:, col] = lyrh
            _hard_closing_balance[:, col] = avh - lyrh
            if col < n_cols - 1:
                _hard_opening_balance[:, col + 1] = avh - lyrh

            # â”€â”€ SOFT CLOSING â”€â”€
            avs = aar - pf * (rf + _additional_requirements_for_soft[:, col])
            avs = np.where(avs < 0.0, 0.0, avs)
            _avail_after_soft_and_reallocated[:, col] = avs

            lyrs = np.where(lyr & _temp_release_flags, avs, 0.0)
            _last_yr_release_soft[:, col] = lyrs
            _soft_closing_balance[:, col] = avs - lyrs
            if col < n_cols - 1:
                _soft_opening_balance[:, col + 1] = avs - lyrs

            # â”€â”€ RETENTION RELEASE â”€â”€
            ret = np.where(_is_retention_col[col] & _temp_release_flags, _cumulative_retention_vals[:, col], 0.0)
            _retention_release[:, col] = ret

            # â”€â”€ CASH INFLOW â”€â”€
            _cash_inflow[:, col] = ret + lyrh + lyrs + hpf + spf + rf

            # â”€â”€ ESCROW SETUP FEES â”€â”€
            if _is_temp_license_col[col]:
                _escrow_setup_fees[:, col] = np.where(
                    _escrow_setup_eligible_vals, _escrow_setup_fee_amount_vals, 0.0
                )

        # ============================================================================================
        # DATAFRAME ASSIGNMENTS
        # ============================================================================================

        _idx  = _template_index
        _cols = _template_columns

        w_soft_opening_balance          = pd.DataFrame(_soft_opening_balance, index=_idx, columns=_cols)
        w_soft_cost_total_availability  = pd.DataFrame(_soft_cost_total_availability, index=_idx, columns=_cols)
        w_soft_cost_cumulative_requirement = pd.DataFrame(_soft_cost_cumulative_requirement, index=_idx, columns=_cols)
        w_soft_cost_payment_from_escrow = pd.DataFrame(_soft_cost_payment_from_escrow, index=_idx, columns=_cols)
        w_additional_requirements_for_soft_cost = pd.DataFrame(_additional_requirements_for_soft, index=_idx, columns=_cols)
        w_amount_available_for_reallocation     = pd.DataFrame(_amount_available_for_reallocation, index=_idx, columns=_cols)
        w_hard_opening_balance          = pd.DataFrame(_hard_opening_balance, index=_idx, columns=_cols)
        w_hard_cost_total_availability  = pd.DataFrame(_hard_cost_total_availability, index=_idx, columns=_cols)
        w_hard_cost_cumulative_requirement = pd.DataFrame(_hard_cost_cumulative_requirement, index=_idx, columns=_cols)
        w_hard_cost_payment_from_escrow = pd.DataFrame(_hard_cost_payment_from_escrow, index=_idx, columns=_cols)
        w_additional_requirements_for_hard_cost = pd.DataFrame(_additional_requirements_for_hard, index=_idx, columns=_cols)
        w_reallocation_amount           = pd.DataFrame(_reallocation_amount, index=_idx, columns=_cols)
        w_reallocated_funds_for_hard_cost_payment = pd.DataFrame(_reallocated_funds_hard, index=_idx, columns=_cols)
        w_additional_requirement_after_allocation = pd.DataFrame(_additional_req_after_alloc, index=_idx, columns=_cols)
        w_amount_available_after_hard_cost_payment = pd.DataFrame(_avail_after_hard_payment, index=_idx, columns=_cols)
        w_last_year_release_hard_cost   = pd.DataFrame(_last_yr_release_hard, index=_idx, columns=_cols)
        w_hard_closing_balance          = pd.DataFrame(_hard_closing_balance, index=_idx, columns=_cols)
        w_amount_available_after_soft_cost_and_reallocated_payment = pd.DataFrame(_avail_after_soft_and_reallocated, index=_idx, columns=_cols)
        w_last_year_release_soft_cost   = pd.DataFrame(_last_yr_release_soft, index=_idx, columns=_cols)
        w_soft_closing_balance          = pd.DataFrame(_soft_closing_balance, index=_idx, columns=_cols)
        w_retention_release             = pd.DataFrame(_retention_release, index=_idx, columns=_cols)
        o_cash_inflow_from_off_plan_sales = pd.DataFrame(_cash_inflow, index=_idx, columns=_cols)
        o_escrow_setup_fees             = pd.DataFrame(_escrow_setup_fees, index=_idx, columns=_cols)
        # ============================================================================================
        # ESCROW RELEASE SUMMARY
        # ============================================================================================

        o_escrow_release_hard  = w_hard_cost_payment_from_escrow + w_reallocated_funds_for_hard_cost_payment + w_last_year_release_hard_cost
        o_escrow_release_soft  = w_soft_cost_payment_from_escrow + w_last_year_release_soft_cost
        o_total_escrow_release = o_escrow_release_hard + o_escrow_release_soft + w_retention_release

        # ============================================================================================
        # ON-PLAN SALES COLLECTION (Post-Construction)
        # ============================================================================================

        o_on_plan_sales_collection      = _create_zero_df()
        w_on_plan_sales_collection_phasing = _create_zero_df()

        _escrow_app_series = pd.Series(Asset.Disposal.escrow_applicability)
        w_on_plan_sales_profile_option = np.where(
            _escrow_app_series == "Yes", "User defined", "None"
        )

        w_collection_start_dates = np.where(
            _escrow_app_series == "Yes",
            temp_post_construction_end_date,
            pd.Series(Asset.Disposal.sales_start_date)
        ).astype('datetime64[ns]')

        start_dates_arr   = pd.to_datetime(pd.Series(w_collection_start_dates)).values.reshape(-1, 1)
        period_starts_arr = _period_starts_me.reshape(1, -1)
        valid_periods_mask = period_starts_arr >= start_dates_arr
        has_valid_period   = valid_periods_mask.any(axis=1)
        slice_idx_arr = np.where(has_valid_period, valid_periods_mask.argmax(axis=1), -1)
        slice_idx_arr = np.where(pd.isna(w_collection_start_dates), -1, slice_idx_arr)

        escrow_yes_mask_bc = (_escrow_app_series == "Yes").values.reshape(-1, 1)
        col_indices_bc     = np.arange(n_cols).reshape(1, -1)
        slice_idx_bc       = slice_idx_arr.reshape(-1, 1)
        revenue_mask       = (col_indices_bc >= slice_idx_bc) & (slice_idx_bc >= 0)

        masked_revenue_sum = (o_escrow_sales_revenue.values * revenue_mask).sum(axis=1)
        full_revenue_sum   = o_escrow_sales_revenue.values.sum(axis=1)
        w_on_plan_sales_amount = pd.Series(
            np.where((_escrow_app_series == "Yes").values, masked_revenue_sum, full_revenue_sum),
            index=_template_index, dtype=float
        )

        w_on_plan_sales_collection_phasing = fn_calculate_user_defined_profile(
            template=w_on_plan_sales_collection_phasing,
            profile_options=w_on_plan_sales_profile_option,
            schedules=_cached_user_defined_schedules["sales_collection"],
            start_dates=w_collection_start_dates,
            durations=pd.Series(Asset.Disposal.sales_collection_duration).fillna(0),
            model_timeline_me=model_timeline_me
        )

        o_on_plan_sales_collection_no_escrow    = w_on_plan_sales_collection_phasing.mul(w_on_plan_sales_amount, axis=0)
        o_on_plan_sales_collection_with_escrow  = pd.DataFrame(
            o_escrow_sales_revenue.values * revenue_mask,
            index=_template_index, columns=_template_columns
        )
        o_on_plan_sales_collection = pd.DataFrame(
            np.where(
                escrow_yes_mask_bc,
                o_on_plan_sales_collection_with_escrow.values,
                o_on_plan_sales_collection_no_escrow.values
            ),
            index=_template_index, columns=_template_columns
        )

        _record_timing("Escrow mechanism calculated")
        
        # ========================================================================
        # EXPORT ESCROW (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS['escrow_mechanism']:
            escrow_export_dict = {
                # ============================================================
                # 1. INPUT REFERENCES (Asset Details & Parameters)
                # ============================================================
                'i_Asset_Category': pd.DataFrame({'Sub_Category': Asset.ProjectDetails.sub_category}),
                'i_GFA': pd.DataFrame({'GFA': Asset.LandAreaProgram.gross_floor_area}),
                'i_Sales_Value': pd.DataFrame({'Sales_Value': w_sales_value}),
                'i_Sales_Start_Date': pd.DataFrame({'Sales_Start_Date': Asset.Disposal.sales_start_date}),
                'i_Sales_Duration': pd.DataFrame({'Sales_Duration': Asset.Disposal.sales_duration}),
                'i_Escrow_Applicability_Input': pd.DataFrame({'Escrow_Applicable_Input': Asset.Disposal.escrow_applicability}),
                
                # ============================================================
                # 2. ESCROW APPLICABILITY (Category-based determination)
                # ============================================================
                'w_Escrow_By_Category': pd.DataFrame({'Escrow_By_Category': w_escrow_applicability_by_category}),
                'w_Escrow_Flag': pd.DataFrame({'Escrow_Flag': w_escrow_flag}),
                'w_Escrow_Applicability': pd.DataFrame({'Escrow_Applicable': w_escrow_applicability}),
                
                # ============================================================
                # 3. CONSTRUCTION PROGRESS (From S-Curve)
                # ============================================================
                'w_Construction_Progress': w_construction_progress_percent,
                'w_Cumulative_Progress': w_cumulative_construction_progress_percent,
                'w_Construction_End': pd.DataFrame({'Construction_End': w_construction_end_date_for_escrow}),
                'w_Construction_Start': pd.DataFrame({'Construction_Start': w_construction_start_dates}),
                
                # ============================================================
                # 4. SALES REVENUE & PHASING
                # ============================================================
                'o_Sales_Phasing': o_sales_phasing,
                'o_Sales_Revenue': o_sales_revenue,
                'o_Escrow_Sales_Revenue': o_escrow_sales_revenue,
                
                # ============================================================
                # 5. PAYMENT ABSORPTION & ESCROW INFLOWS
                # ============================================================
                'o_Payment_Absorption': o_payment_absorption,
                'o_Inflows_To_Escrow': o_inflows_to_escrow,
                
                # ============================================================
                # 6. ESCROW FUND ALLOCATION
                # ============================================================
                'o_Transfer_To_Retention': o_transfer_to_retention,
                'o_Funds_Soft_Cost': o_funds_available_for_soft_cost,
                'o_Funds_Hard_Cost': o_funds_available_for_hard_cost,
                
                # ============================================================
                # 7. LICENSE FLAGS
                # ============================================================
                'w_Temp_License_Flag': pd.DataFrame({'Temp_License_Date': w_temporary_license_flag}),
                'w_Perm_License_Flag': w_permanent_license_date_flag,
                
                # ============================================================
                # 8. SOFT COST ESCROW WORKINGS
                # ============================================================
                'w_Soft_Opening_Bal': w_soft_opening_balance,
                'w_Soft_Total_Avail': w_soft_cost_total_availability,
                'w_Soft_Payment_Req': w_soft_cost_payment_requirement,
                'w_Soft_Cumul_Req': w_soft_cost_cumulative_requirement,
                'w_Soft_Payment_Escrow': w_soft_cost_payment_from_escrow,
                'w_Soft_Addl_Req': w_additional_requirements_for_soft_cost,
                'w_Soft_Avail_Realloc': w_amount_available_for_reallocation,
                'w_Soft_Avail_After_Pmt': w_amount_available_after_soft_cost_and_reallocated_payment,
                'w_Soft_LastYr_Release': w_last_year_release_soft_cost,
                'w_Soft_Closing_Bal': w_soft_closing_balance,
                
                # ============================================================
                # 9. HARD COST ESCROW WORKINGS
                # ============================================================
                'w_Hard_Opening_Bal': w_hard_opening_balance,
                'w_Hard_Total_Avail': w_hard_cost_total_availability,
                'w_Hard_Payment_Req': w_hard_cost_payment_requirement,
                'w_Hard_Cumul_Req': w_hard_cost_cumulative_requirement,
                'w_Hard_Payment_Escrow': w_hard_cost_payment_from_escrow,
                'w_Hard_Addl_Req': w_additional_requirements_for_hard_cost,
                'w_Hard_Avail_After_Pmt': w_amount_available_after_hard_cost_payment,
                'w_Hard_LastYr_Release': w_last_year_release_hard_cost,
                'w_Hard_Closing_Bal': w_hard_closing_balance,
                
                # ============================================================
                # 10. REALLOCATION WORKINGS
                # ============================================================
                'w_Reallocation_Amt': w_reallocation_amount,
                'w_Reallocated_Hard': w_reallocated_funds_for_hard_cost_payment,
                'w_Addl_Req_After_Alloc': w_additional_requirement_after_allocation,
                
                # ============================================================
                # 11. RETENTION WORKINGS
                # ============================================================
                'w_Retention_Release': w_retention_release,
                
                # ============================================================
                # 12. ESCROW RELEASE SUMMARY (Final Outputs)
                # ============================================================
                'o_Escrow_Release_Hard': o_escrow_release_hard,
                'o_Escrow_Release_Soft': o_escrow_release_soft,
                'o_Total_Escrow_Release': o_total_escrow_release,
                
                # ============================================================
                # 13. CASH FLOWS & FEES
                # ============================================================
                'o_Cash_Inflow_OffPlan': o_cash_inflow_from_off_plan_sales,
                'o_OnPlan_Sales_Coll': o_on_plan_sales_collection,
                'o_Escrow_Setup_Fees': o_escrow_setup_fees,
            }
            _export_to_excel(escrow_export_dict, 'devco_escrow', 'Escrow Mechanism')

        # ========================================================================
        # SUB-MODULE 3.10: DISPOSAL/SALES REVENUE FUNCTIONS
        # ========================================================================
        
        def fn_calculate_sales_revenue(
            template,
            sales_value_series,
            sales_start_date_series,
            sales_duration_series,
            sales_phasing_option_series,
            sales_phasing_profile_series,
            escalation_profile_series,
            predefined_profile_names,
            predefined_profile_data,
            predefined_profile_durations,
            escalation_factor_df
        ):
            """
            Calculate phased sales revenue based on sales value and phasing profile.
            
            Sales Phasing Options:
            - 'Pre Defined': Use selected predefined profile
            - 'User Defined': Use user-defined schedule
            - 'Linked to Construction': Link to construction S-curve
            
            Args:
                template: Zero-initialized template
                sales_value_series: Sales value per asset
                sales_start_date_series: Sales start dates
                sales_duration_series: Sales durations
                sales_phasing_option_series: Phasing option per asset
                sales_phasing_profile_series: Selected profile per asset
                escalation_profile_series: Escalation profiles
                predefined_profile_*: Profile data
                escalation_factor_df: Escalation factors
                
            Returns:
                pd.DataFrame: Sales revenue per asset per period
            """
            try:
                result_df = template.copy()
                result_df.iloc[:, :] = 0
                
                for idx in template.index:
                    sales_value = sales_value_series[idx] if idx < len(sales_value_series) else 0
                    if pd.isna(sales_value) or sales_value <= 0:
                        continue
                    
                    start_date = sales_start_date_series[idx] if idx < len(sales_start_date_series) else None
                    if pd.isna(start_date) or start_date is None:
                        continue
                    
                    start_date = pd.to_datetime(start_date)
                    
                    # Find start period using binary search
                    start_idx = np.searchsorted(_period_starts, np.datetime64(start_date))
                    if start_idx >= _n_periods:
                        continue
                    
                    # Get phasing option and duration
                    phasing_option = sales_phasing_option_series[idx] if idx < len(sales_phasing_option_series) else 'Pre defined'
                    duration = sales_duration_series[idx] if idx < len(sales_duration_series) else 12
                    duration = int(duration) if pd.notna(duration) and duration > 0 else 12
                    
                    # Get profile
                    if phasing_option == 'Pre Defined' or phasing_option == 'Pre defined':
                        profile_name = sales_phasing_profile_series[idx] if idx < len(sales_phasing_profile_series) else None
                        if profile_name and profile_name in predefined_profile_names:
                            profile_index = predefined_profile_names.index(profile_name)
                            profile_values = list(predefined_profile_data[profile_index])
                            duration = predefined_profile_durations[profile_index] if profile_index < len(predefined_profile_durations) else len(profile_values)
                        else:
                            profile_values = [1.0 / duration] * duration
                    else:
                        # User defined or default
                        profile_values = [1.0 / duration] * duration
                    
                    # Normalize profile
                    total_profile = sum(filter(lambda x: pd.notna(x) and x != '', profile_values))
                    if total_profile > 0:
                        profile_values = [(v / total_profile if pd.notna(v) and v != '' else 0) for v in profile_values]
                    
                    # Vectorized sales distribution using numpy slice operations
                    end_idx = min(start_idx + len(profile_values), _n_periods)
                    valid_len = end_idx - start_idx
                    profile_arr = np.array(profile_values[:valid_len])
                    esc_factors = escalation_factor_df.iloc[idx, start_idx:end_idx].values
                    result_df.iloc[idx, start_idx:end_idx] = sales_value * profile_arr * esc_factors
                
                return result_df
            except Exception as e:
                print(f"Error in fn_calculate_sales_revenue: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        def fn_calculate_sales_cost(
            template,
            sales_revenue_df,
            override_series,
            calculation_approach_series,
            percent_of_sales_series,
            cost_per_sqm_series,
            cost_basis_series,
            start_date_series,
            duration_series,
            user_defined_phasing_series,
            user_defined_schedule_series,
            pre_defined_profile_series,
            pre_defined_duration_series,
            user_defined_s_curve_series,
            escalation_profile_series,
            global_calculation_approach,
            global_percent_of_sales,
            global_cost_per_sqm,
            global_cost_basis,
            global_profile,
            global_escalation_profile,
            predefined_profile_names,
            predefined_profile_data,
            predefined_profile_durations,
            escalation_profile_names,
            escalation_profile_data,
            model_timeline_me
        ):
            """
            Calculate sales and marketing costs with proper phasing and escalation (vectorized).
            
            Override Logic:
            - If override == "Yes": Use asset-level inputs for all parameters
            - Otherwise: Use global inputs
            
            Phasing Logic:
            - If user_defined_phasing == "Yes": Use user-defined S-curve with duration
            - Otherwise: Use pre-defined profile with duration
            
            Calculation Approaches:
            - '% of Sales Value': percentage Ã— total_sales_revenue (escalated)
            - 'SAR/SQM of': area Ã— cost_per_sqm (escalated, based on cost_basis)
            - 'Ad-Hoc Amount': Fixed amount (escalated)
            """
            try:
                n_assets = int(len(template.index))
                n_periods = int(len(template.columns))
                
                # ========== VECTORIZED OVERRIDE MASK ==========
                override_arr = np.array([
                    str(override_series[i]).lower() == 'yes' if i < len(override_series) else False
                    for i in range(n_assets)
                ])
                
                # ========== VECTORIZED CALCULATION APPROACH ==========
                calc_approach_arr = np.array([
                    calculation_approach_series[i] if override_arr[i] and i < len(calculation_approach_series) else global_calculation_approach
                    for i in range(n_assets)
                ])
                
                # ========== VECTORIZED PERCENT OF SALES ==========
                pct_arr = np.array([
                    float(percent_of_sales_series[i]) if override_arr[i] and i < len(percent_of_sales_series) and pd.notna(percent_of_sales_series[i]) else (float(global_percent_of_sales) if pd.notna(global_percent_of_sales) else 0.0)
                    for i in range(n_assets)
                ], dtype=float)
                
                # ========== VECTORIZED COST PER SQM / AD-HOC ==========
                cost_sqm_arr = np.array([
                    float(cost_per_sqm_series[i]) if override_arr[i] and i < len(cost_per_sqm_series) and pd.notna(cost_per_sqm_series[i]) else (float(global_cost_per_sqm) if pd.notna(global_cost_per_sqm) else 0.0)
                    for i in range(n_assets)
                ], dtype=float)
                
                # ========== VECTORIZED COST BASIS AREA ==========
                cost_basis_mapping = {
                    "Gross Floor Area": Asset.LandAreaProgram.gross_floor_area,
                    "Net Saleable Area": Asset.LandAreaProgram.total_nsa__gla,
                    "Built Up Area": Asset.LandAreaProgram.built_up_area,
                    "Developable Land Area": Asset.LandAreaProgram.developable_land_area
                }
                
                # Get cost basis per asset
                cost_basis_arr = np.array([
                    cost_basis_series[i] if override_arr[i] and i < len(cost_basis_series) and pd.notna(cost_basis_series[i]) else global_cost_basis
                    for i in range(n_assets)
                ])
                
                # Calculate area based on cost basis
                area_arr = np.zeros(n_assets, dtype=float)
                for basis_name, basis_series in cost_basis_mapping.items():
                    if basis_series is not None:
                        mask = cost_basis_arr == basis_name
                        for i in np.where(mask)[0]:
                            if i < len(basis_series) and pd.notna(basis_series[i]):
                                area_arr[i] = float(basis_series[i])
                
                # ========== VECTORIZED BASE COST CALCULATION ==========
                total_sales_arr = sales_revenue_df.values.sum(axis=1)
                
                base_cost_arr = np.zeros(n_assets, dtype=float)
                
                # % of Sales Value
                pct_mask = (calc_approach_arr == '% of Sales Value')
                base_cost_arr = np.where(pct_mask & (pct_arr > 0), total_sales_arr * pct_arr, base_cost_arr)
                
                # SAR/SQM of
                sqm_mask = (calc_approach_arr == 'SAR/SQM')
                base_cost_arr = np.where(sqm_mask & (cost_sqm_arr > 0), area_arr * cost_sqm_arr, base_cost_arr)
                
                # Ad-Hoc Amount
                adhoc_mask = (calc_approach_arr == 'Ad-Hoc Amount')
                base_cost_arr = np.where(adhoc_mask & (cost_sqm_arr != 0), cost_sqm_arr, base_cost_arr)

                # ========== VECTORIZED START DATES ==========
                start_date_arr = np.array([
                    pd.to_datetime(start_date_series[i]) if override_arr[i] and i < len(start_date_series) and pd.notna(start_date_series[i]) 
                    else (pd.to_datetime(Global.SalesInputs.sales_sales_start_date) if pd.notna(Global.SalesInputs.sales_sales_start_date) else pd.NaT)
                    for i in range(n_assets)
                ], dtype='datetime64[ns]')
                
                # Convert timeline period starts to numpy array
                period_starts_arr = model_timeline_me['Period Start'].values.astype('datetime64[ns]')
                
                # Find start column for each asset (vectorized comparison)
                # Reshape for broadcasting: (n_assets, 1) vs (1, n_periods)
                start_date_broadcast = start_date_arr.reshape(-1, 1)
                period_broadcast = period_starts_arr.reshape(1, -1)
                
                # Find first column where period >= start_date
                valid_periods = period_broadcast >= start_date_broadcast
                has_valid = valid_periods.any(axis=1)
                start_col_arr = np.where(has_valid, valid_periods.argmax(axis=1), -1)
                
                # ========== VECTORIZED DURATION ==========
                # User-defined phasing flag
                use_user_defined_arr = np.array([
                    str(user_defined_phasing_series[i]).lower() == 'yes' if override_arr[i] and i < len(user_defined_phasing_series) else False
                    for i in range(n_assets)
                ])
                
                # Duration based on phasing type
                duration_arr = np.array([
                    (duration_series[i] if use_user_defined_arr[i] and i < len(duration_series) and pd.notna(duration_series[i]) and duration_series[i] > 0
                     else (pre_defined_duration_series[i] if not use_user_defined_arr[i] and i < len(pre_defined_duration_series) and pd.notna(pre_defined_duration_series[i]) and pre_defined_duration_series[i] > 0
                           else 12))
                    for i in range(n_assets)
                ], dtype=int)
                
                # ========== BUILD PHASING MATRIX (Vectorized where possible) ==========
                phasing_matrix = np.zeros((n_assets, n_periods), dtype=float)

                # Build user-defined phasing matrix using the same helper used in other modules.
                raw_schedules = user_defined_schedule_series if user_defined_schedule_series is not None else []
                if isinstance(raw_schedules, (pd.Series, np.ndarray)):
                    raw_schedules = raw_schedules.tolist()
                elif not isinstance(raw_schedules, list):
                    raw_schedules = []

                normalized_schedules = []
                for i in range(n_assets):
                    schedule_i = raw_schedules[i] if i < len(raw_schedules) else []
                    if isinstance(schedule_i, np.ndarray):
                        schedule_i = schedule_i.tolist()
                    normalized_schedules.append(schedule_i)

                user_defined_profile_df = fn_calculate_user_defined_profile(
                    template=_create_zero_df(),
                    profile_options=np.where(use_user_defined_arr, "User defined", "None"),
                    schedules=normalized_schedules,
                    start_dates=pd.to_datetime(start_date_arr),
                    durations=duration_arr,
                    model_timeline_me=model_timeline_me
                )
                
                # Create column indices matrix
                col_indices = np.arange(n_periods).reshape(1, -1)
                start_col_broadcast = start_col_arr.reshape(-1, 1)
                duration_broadcast = duration_arr.reshape(-1, 1)
                
                # Mask for valid phasing columns
                valid_mask = (col_indices >= start_col_broadcast) & (col_indices < start_col_broadcast + duration_broadcast) & (start_col_broadcast >= 0)
                
                # Pre-defined profile handling (for assets not using user-defined)
                # Build profile lookup dictionary
                profile_lookup = {}
                if predefined_profile_names is not None and predefined_profile_data is not None:
                    for p_idx, p_name in enumerate(predefined_profile_names):
                        if p_idx < len(predefined_profile_data) and p_name is not None:
                            profile_lookup[p_name] = predefined_profile_data[p_idx]
                
                # Get profile names per asset
                profile_name_arr = np.array([
                    pre_defined_profile_series[i] if override_arr[i] and i < len(pre_defined_profile_series) and pd.notna(pre_defined_profile_series[i]) else global_profile
                    for i in range(n_assets)
                ])
                
                # Apply pre-defined profiles where applicable
                for i in range(n_assets):
                    if base_cost_arr[i] <= 0 or start_col_arr[i] < 0:
                        continue

                    if use_user_defined_arr[i]:
                        phasing_matrix[i, :] = user_defined_profile_df.iloc[i, :].values.astype(float)
                        continue
                    
                    if not use_user_defined_arr[i]:
                        profile_name = profile_name_arr[i]
                        if profile_name in profile_lookup:
                            profile_values = profile_lookup[profile_name]
                            if profile_values is not None and len(profile_values) > 0:
                                duration = duration_arr[i]
                                start_col = start_col_arr[i]
                                profile_len = len(profile_values)
                                
                                # Apply profile values
                                for j in range(min(profile_len, n_periods - start_col)):
                                    val = profile_values[j]
                                    phasing_matrix[i, start_col + j] = float(val) if pd.notna(val) else 0
                                
                                # Normalize
                                row_sum = phasing_matrix[i, :].sum()
                                if row_sum > 0:
                                    phasing_matrix[i, :] = phasing_matrix[i, :] / row_sum
                
                # ========== VECTORIZED ESCALATION FACTORS ==========
                # Build escalation lookup
                escalation_lookup = {}
                if escalation_profile_names is not None and escalation_profile_data is not None:
                    for e_idx, e_name in enumerate(escalation_profile_names):
                        if e_idx < len(escalation_profile_data) and e_name is not None:
                            escalation_lookup[e_name] = escalation_profile_data[e_idx]
                
                # Get escalation profile per asset
                esc_profile_arr = np.array([
                    escalation_profile_series[i] if override_arr[i] and i < len(escalation_profile_series) and pd.notna(escalation_profile_series[i]) else global_escalation_profile
                    for i in range(n_assets)
                ])
                
                # Pre-compute year indices for each period
                period_years = model_timeline_me['Year'].values
                year_indices = np.clip((period_years - 2019).astype(int), 0, 100)
                
                # Build escalation matrix
                escalation_matrix = np.ones((n_assets, n_periods), dtype=float)
                
                for i in range(n_assets):
                    esc_profile = esc_profile_arr[i]
                    if esc_profile in escalation_lookup:
                        esc_data = escalation_lookup[esc_profile]
                        esc_data = [x for x in esc_data if x != ""]
                        if esc_data is not None and len(esc_data) > 0:
                            # Vectorized: build cumulative escalation using numpy cumprod
                            esc_data_arr = np.array(esc_data, dtype=float)
                            valid_year_idx = np.clip(year_indices, 0, len(esc_data_arr) - 1)
                            rates = np.where(year_indices < len(esc_data_arr), esc_data_arr[valid_year_idx], 0.0)
                            rates = np.where(np.isnan(rates), 0.0, rates)
                            escalation_matrix[i, :] = np.cumprod(1 + rates)
                
                # ========== FINAL COST CALCULATION (Vectorized) ==========
                # Cost = Base Cost Ã— Phasing Ã— Escalation
                result_arr = base_cost_arr.reshape(-1, 1) * phasing_matrix * escalation_matrix
                
                # Zero out rows with no base cost
                result_arr = np.where(base_cost_arr.reshape(-1, 1) > 0, result_arr, 0.0)
                
                result_df = pd.DataFrame(result_arr, index=template.index, columns=template.columns)
                
                return result_df
            except Exception as e:
                print(f"Error in fn_calculate_sales_cost: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # ============================================================================================
        # FORWARD FUNDING PAYMENT ABSORPTION
        # ============================================================================================

        def fn_calculate_forward_funding_cash(assets, template, w_ff_payment_absorption,
                                            is_forward_funding, model_timeline_me):
            """
            Calculate Forward Funding cash receipts.
           
            Forward Funding Value = Strike Price (SAR/SQM) Ã— Total NSA (SQM)
            NO ESCALATION applied to Forward Funding.
            Payments follow construction milestone schedule.
            Cash = Change in Absorption Ã— Total Contract Value
           
            Args:
                assets (list): List of asset objects
                template (pd.DataFrame): Asset-timeline template
                w_ff_payment_absorption (pd.DataFrame): Payment absorption percentages
                is_forward_funding (pd.Series): Forward funding flag
                model_timeline_me (pd.DataFrame): Model timeline
           
            Returns:
                pd.DataFrame: Forward funding cash receipts (N_assets x N_periods)
            """
           
            # Vectorized calculation for absorption change
            absorption_values = w_ff_payment_absorption.values
           
            cash_values = np.zeros_like(absorption_values)
           
            # Calculate per-asset: Total Value = Strike Price Ã— Total NSA
            for loop_row_idx in template.index:
                if is_forward_funding[loop_row_idx] != 1.0:
                    continue
               
                # Get strike price (SAR/SQM)
                strike_price = assets[loop_row_idx].BusinessModel.strike_price
                if pd.isna(strike_price) or strike_price == 0:
                    continue
               
                # Get Total NSA from LandAreaProgram
                total_nsa = getattr(assets[loop_row_idx].LandAreaProgram, 'total_nsa__gla', None)
                if pd.isna(total_nsa) or total_nsa is None or total_nsa == 0:
                    continue
               
                # Total Contract Value = Strike Price Ã— Total NSA (NO ESCALATION)
                total_contract_value = strike_price * total_nsa
 
                # Cash = Change in absorption Ã— Total Contract Value
                cash_values[loop_row_idx, :] = np.maximum(0.0,
                    (absorption_values[loop_row_idx, :]) * total_contract_value)
           
            o_forward_funding_cash = pd.DataFrame(cash_values, index=template.index, columns=template.columns)
           
            return o_forward_funding_cash

        # ============================================================================================
        # FORWARD SALES CASH CALCULATION
        # ============================================================================================
        # Single lump-sum payment at Asset Handover = Strike Price Ã— Total NSA
        # Asset Handover = Construction End + Contractor Void Period + Asset Handover Void Period

        def fn_calculate_forward_sales_cash(assets, template, is_forward_sales, model_timeline_me, 
                                            construction_timeline=None, global_obj=None):
            """
            Calculate Forward Sales cash receipts.
            Single payment of Strike Price Ã— Total NSA at Asset Handover date.
            
            Forward Sales Value = Strike Price (SAR/SQM) Ã— Total NSA (SQM)
            Payment timing: Asset Handover Date (Construction End + Void Periods)
            
            Args:
                assets (list): List of asset objects
                template (pd.DataFrame): Asset-timeline template
                is_forward_sales (pd.Series): Forward sales flag
                model_timeline_me (pd.DataFrame): Model timeline
                construction_timeline (pd.DataFrame): Construction timeline with ConstructionEnd dates
                global_obj: Global assumptions object (for void period defaults)
            
            Returns:
                pd.DataFrame: Forward sales cash receipts (N_assets x N_periods)
            """
            
            o_forward_sales_cash = template.copy()
            o_forward_sales_cash.iloc[:, :] = 0.0
            
            if global_obj is not None:
                if hasattr(global_obj, 'VoidPeriod'):
                    if pd.notna(getattr(global_obj.VoidPeriod, 'contractor_void_period_months', None)):
                        contractor_void_default = int(global_obj.VoidPeriod.contractor_void_period_months)
                    if pd.notna(getattr(global_obj.VoidPeriod, 'asset_handover_void_period_months', None)):
                        handover_void_default = int(global_obj.VoidPeriod.asset_handover_void_period_months)
            
            for loop_row_idx in template.index:
                
                # Skip if not Forward Sales
                if is_forward_sales[loop_row_idx] != 1.0:
                    continue
                
                # Get strike price (SAR/SQM) from BusinessModel
                strike_price = assets[loop_row_idx].BusinessModel.strike_price
                
                # Get Total NSA (Net Saleable Area) from LandAreaProgram
                total_nsa = getattr(assets[loop_row_idx].LandAreaProgram, 'total_nsa__gla', None)
                
                if pd.isna(strike_price) or strike_price == 0:
                    continue
                
                if pd.isna(total_nsa) or total_nsa is None or total_nsa == 0:
                    continue
                
                # Calculate forward sales value = Strike Price Ã— Total NSA
                forward_sales_value = strike_price * total_nsa
                
                # Determine asset handover date
                # Priority: 1) Asset-level override, 2) Construction End + Void Periods
                asset_handover_date = None
                
                # Check for asset-level handover date override
                if hasattr(assets[loop_row_idx].VerticalDevelopmentModule, 'asset_handover_date'):
                    asset_handover_date = assets[loop_row_idx].VerticalDevelopmentModule.asset_handover_date
                    if pd.notna(asset_handover_date):
                        # Handle datetime.time objects by skipping them (they're invalid dates)
                        import datetime
                        if isinstance(asset_handover_date, datetime.time):
                            asset_handover_date = None
                        else:
                            asset_handover_date = pd.to_datetime(asset_handover_date)
                
                # If no override, calculate from construction end + void periods
                if pd.isna(asset_handover_date) and construction_timeline is not None:
                    construction_end = construction_timeline.loc[loop_row_idx, 'ConstructionEnd']
                    
                    if pd.notna(construction_end):
                        # Get asset-level void periods or use defaults
                        contractor_void = contractor_void_default
                        handover_void = handover_void_default
                        
                        if hasattr(assets[loop_row_idx].VerticalDevelopmentModule, 'contractor_void_period'):
                            asset_void = assets[loop_row_idx].VerticalDevelopmentModule.contractor_void_period
                            if pd.notna(asset_void):
                                contractor_void = int(asset_void)
                        
                        if hasattr(assets[loop_row_idx].VerticalDevelopmentModule, 'asset_handover_void_period'):
                            asset_hvoid = assets[loop_row_idx].VerticalDevelopmentModule.asset_handover_void_period
                            if pd.notna(asset_hvoid):
                                handover_void = int(asset_hvoid)
                        
                        # Asset Handover = Construction End + Contractor Void + Handover Void
                        total_void_months = contractor_void + handover_void
                        asset_handover_date = pd.to_datetime(construction_end) + pd.DateOffset(months=total_void_months)
                
                # Fallback: use contract date if no handover date available
                if pd.isna(asset_handover_date):
                    contract_date = assets[loop_row_idx].BusinessModel.contract_date
                    if pd.notna(contract_date):
                        asset_handover_date = pd.to_datetime(contract_date)
                        print(f"       [WARN] Asset {loop_row_idx}: Using contract date as fallback for handover")
                
                if pd.isna(asset_handover_date):
                    continue
                
                # Find handover date in timeline
                for loop_col_idx, period_start in enumerate(model_timeline_me['Period Start']):
                    
                    # Match period containing handover date
                    period_end = model_timeline_me['Period End'].iloc[loop_col_idx]
                    
                    if period_start <= asset_handover_date <= period_end:
                        o_forward_sales_cash.loc[loop_row_idx, loop_col_idx] = forward_sales_value
                        break
            
            return o_forward_sales_cash
        
        # ========================================================================
        # EXECUTE DISPOSAL/SALES CALCULATIONS (LandCo-style)
        # ========================================================================
        # Sales Revenue and Collection calculations are done in SUB-MODULE 3.8 
        # (before Escrow section) to provide unified values for:
        # - o_sales_revenue: All assets (used for costs)
        # - o_escrow_sales_revenue: Escrow assets only (from escrow section)
        # - o_sales_collection_without_escrow: Non-escrow assets collection (for cashflow)
        #
        # This section only calculates Sales Cost and Marketing Cost using 
        # o_sales_revenue (ALL assets, before escrow mask) to ensure costs are 
        # calculated for both escrow and non-escrow assets.
        # ========================================================================
        
        # Calculate Sales Cost (using o_sales_revenue from SUB-MODULE 3.8)
        # Note: Uses ALL assets revenue (before escrow mask) so costs apply to both types
        o_sales_cost = fn_calculate_sales_cost(
            template=_create_zero_df(),
            sales_revenue_df=o_sales_revenue,
            override_series=Asset.Disposal.sales_cost_override,
            calculation_approach_series=Asset.Disposal.sales_cost_calculation_approach,
            percent_of_sales_series=Asset.Disposal.sales_cost_percent_of_sales_value,
            cost_per_sqm_series=Asset.Disposal.sales_cost,
            cost_basis_series=Asset.Disposal.sales_cost_cost_basis,
            start_date_series=Asset.Disposal.sales_cost_cost_start_date,
            duration_series=Asset.Disposal.sales_cost_cost_duration,
            user_defined_phasing_series=Asset.Disposal.sales_cost_user_defined_phasing,
            user_defined_schedule_series=fn_get_named_range_value(assumptions, "s.devco.sales.cost.payment", []),
            pre_defined_profile_series=Asset.Disposal.sales_cost_pre_defined_profile,
            pre_defined_duration_series=Asset.Disposal.sales_cost_pre_defined_duration,
            user_defined_s_curve_series=Asset.Disposal.sales_cost_user_defined_s_curve,
            escalation_profile_series=Asset.Disposal.sales_cost_escalation_profile,
            global_calculation_approach=Global.SalesandMarketingCost.sales_cost_calculation_approach,
            global_percent_of_sales=Global.SalesandMarketingCost.sales_cost_percentage_of_sales_value,
            global_cost_per_sqm=Global.SalesandMarketingCost.sales_cost_cost_per_sqm,
            global_cost_basis=Global.SalesandMarketingCost.sales_cost_cost_basis,
            global_profile=Global.SalesandMarketingCost.sales_cost_profiles,
            global_escalation_profile=Global.SalesandMarketingCost.sales_cost_escalation_profile,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            model_timeline_me=model_timeline_me
        )
        
        # Calculate Marketing Cost (using o_sales_revenue from SUB-MODULE 3.8)
        # Note: Uses ALL assets revenue (before escrow mask) so costs apply to both types
        o_marketing_cost = fn_calculate_sales_cost(
            template=_create_zero_df(),
            sales_revenue_df=o_sales_revenue,
            override_series=Asset.Disposal.marketing_cost_override,
            calculation_approach_series=Asset.Disposal.marketing_cost_calculation_approach,
            percent_of_sales_series=Asset.Disposal.marketing_cost_percent_of_sales_value,
            cost_per_sqm_series=Asset.Disposal.marketing_cost,
            cost_basis_series=Asset.Disposal.marketing_cost_cost_basis,
            start_date_series=Asset.Disposal.marketing_cost_cost_start_date,
            duration_series=Asset.Disposal.marketing_cost_cost_duration,
            user_defined_phasing_series=Asset.Disposal.marketing_cost_user_defined_phasing,
            user_defined_schedule_series=fn_get_named_range_value(assumptions, "s.devco.marketing.cost.payment", []),
            pre_defined_profile_series=Asset.Disposal.marketing_cost_pre_defined_profile,
            pre_defined_duration_series=Asset.Disposal.marketing_cost_pre_defined_duration,
            user_defined_s_curve_series=Asset.Disposal.marketing_cost_user_defined_s_curve,
            escalation_profile_series=Asset.Disposal.marketing_cost_escalation_profile,
            global_calculation_approach=Global.SalesandMarketingCost.marketing_cost_calculation_approach,
            global_percent_of_sales=Global.SalesandMarketingCost.marketing_cost_percentage_of_sales_value,
            global_cost_per_sqm=Global.SalesandMarketingCost.marketing_cost_cost_per_sqm,
            global_cost_basis=Global.SalesandMarketingCost.marketing_cost_cost_basis,
            global_profile=Global.SalesandMarketingCost.marketing_cost_profiles,
            global_escalation_profile=Global.SalesandMarketingCost.marketing_cost_escalation_profile,
            predefined_profile_names=predefined_profile_names,
            predefined_profile_data=predefined_profile_data,
            predefined_profile_durations=predefined_profile_durations,
            escalation_profile_names=escalation_profile_names,
            escalation_profile_data=escalation_profile_data,
            model_timeline_me=model_timeline_me
        )
        
        # Total Sales & Marketing Cost
        o_total_sales_marketing_cost = o_sales_cost + o_marketing_cost
        
        _record_timing("Disposal/Sales calculated")
        
        # ========================================================================
        # SUB-MODULE 3.11: FORWARD FUNDING & FORWARD SALES FUNCTIONS
        # ========================================================================
        # Determine Forward Funding and Forward Sales flags based on funding_type
        # funding_type: "Forward Funding" or "Forward Sales" from Asset.BusinessModel
        #
        # Forward Funding: Milestone-based payments linked to construction progress
        #   - Payment absorption calculated from cumulative construction progress
        #   - Cash = Change in Absorption Ã— (Strike Price Ã— Total NSA/GLA)
        #
        # Forward Sales: Lump-sum payment at asset handover
        #   - Single payment at Construction End + Void Periods
        #   - Cash = Strike Price Ã— Total NSA/GLA
        # ========================================================================
        
        # Create flags based on funding_type
        w_is_forward_funding = pd.Series(
            [(1.0 if str(ft).lower() == 'forward.funding' else 0.0) for ft in Asset.BusinessModel.funding_type],
            index=_template_index
        )
        w_is_forward_sales = pd.Series(
            [(1.0 if str(ft).lower() == 'forward.sales' else 0.0) for ft in Asset.BusinessModel.funding_type],
            index=_template_index
        )
        
        # Reuse Payment Absorption from Escrow calculations (already computed with correct milestones)
        # o_payment_absorption uses the same milestone structure from Global.EscrowMechanism
        # This ensures consistency and avoids duplicate calculations
        w_ff_payment_absorption = o_payment_absorption_forward_funding.copy()

        # Forward funding cash should follow construction S-curve progression.
        # Keep milestone absorption above for reporting/export compatibility.
        w_ff_payment_absorption_for_cash = w_cumulative_construction_progress_percent.copy()
        
        # Create asset list for forward funding/sales functions
        # Build a list of asset-like objects from the Asset class arrays
        class AssetProxy:
            def __init__(self, idx):
                self.idx = idx
                self.BusinessModel = type('BusinessModel', (), {
                    'strike_price': Asset.BusinessModel.strike_price[idx] if idx < len(Asset.BusinessModel.strike_price) else None,
                    'contract_date': Asset.BusinessModel.contract_date[idx] if idx < len(Asset.BusinessModel.contract_date) else None,
                })()
                self.LandAreaProgram = type('LandAreaProgram', (), {
                    'total_nsa__gla': Asset.LandAreaProgram.total_nsa__gla[idx] if idx < len(Asset.LandAreaProgram.total_nsa__gla) else None,
                })()
                self.VerticalDevelopmentModule = type('VerticalDevelopmentModule', (), {
                    'asset_handover_date': getattr(Asset.VerticalDevelopmentModule, 'asset_handover_date', [None] * _n_assets)[idx] if idx < _n_assets else None,
                    'contractor_void_period': Asset.VerticalDevelopmentModule.contractor_void_period[idx] if idx < len(Asset.VerticalDevelopmentModule.contractor_void_period) else None,
                    'asset_handover_void_period': Asset.VerticalDevelopmentModule.asset_handover_void_period[idx] if idx < len(Asset.VerticalDevelopmentModule.asset_handover_void_period) else None,
                })()
        
        _asset_proxy_list = [AssetProxy(i) for i in range(_n_assets)]
        
        # Calculate Forward Funding Cash
        o_forward_funding_cash = fn_calculate_forward_funding_cash(
            assets=_asset_proxy_list,
            template=_create_zero_df(),
            w_ff_payment_absorption=w_vertical_construction_phasing,
            is_forward_funding=w_is_forward_funding,
            model_timeline_me=model_timeline_me
        )
        
        # Create construction timeline DataFrame for forward sales
        _construction_timeline_df = pd.DataFrame({
            'ConstructionEnd': w_construction_end_date_for_escrow
        })
        
        # Calculate Forward Sales Cash
        o_forward_sales_cash = fn_calculate_forward_sales_cash(
            assets=_asset_proxy_list,
            template=_create_zero_df(),
            is_forward_sales=w_is_forward_sales,
            model_timeline_me=model_timeline_me,
            construction_timeline=_construction_timeline_df,
            global_obj=Global
        )
        
        _record_timing("Forward Funding & Sales calculated")
        
        # ========================================================================
        # EXPORT FORWARD FUNDING & FORWARD SALES (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS['forward_funding_sales']:
            ff_fs_export_dict = {
                # Final Outputs - Forward Funding
                'o_Forward_Funding_Cash': o_forward_funding_cash,
                # Final Outputs - Forward Sales
                'o_Forward_Sales_Cash': o_forward_sales_cash,
                # Working - Forward Funding Payment Absorption
                'w_FF_Payment_Absorption': w_ff_payment_absorption,
                # Working - Forward Funding/Sales Flags
                'w_Is_Forward_Funding': pd.DataFrame({'Is_Forward_Funding': w_is_forward_funding}),
                'w_Is_Forward_Sales': pd.DataFrame({'Is_Forward_Sales': w_is_forward_sales}),
                'w_Is_ROSHN_Developed': pd.DataFrame({'Is_ROSHN_Developed': w_is_roshn_developed}),
                # Working - Construction Progress (used for milestone calculation)
                'w_Cumulative_Construction_Progress': w_cumulative_construction_progress_percent,
                # Working - Business Model Inputs
                'w_Funding_Type': pd.DataFrame({'Funding_Type': Asset.BusinessModel.funding_type}),
                'w_Strike_Price': pd.DataFrame({'Strike_Price': Asset.BusinessModel.strike_price}),
                'w_Contract_Date': pd.DataFrame({'Contract_Date': Asset.BusinessModel.contract_date}),
                # Working - Area Reference
                'w_Total_NSA_GLA': pd.DataFrame({'Total_NSA_GLA': Asset.LandAreaProgram.total_nsa__gla}),
            }
            _export_to_excel(ff_fs_export_dict, 'devco_forward_funding_sales', 'Forward Funding & Forward Sales')
        
        # ========================================================================
        # EXPORT DISPOSAL/SALES (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS['disposal_sales']:
            disposal_export_dict = {
                # Final Outputs (from SUB-MODULE 3.8 Sales Revenue Calculation)
                'o_Sales_Phasing': o_sales_phasing,
                'o_Sales_Revenue': o_sales_revenue,
                'o_Sales_Collection_Non_Escrow': o_sales_collection_without_escrow,
                # Working - Business Model Mask
                'w_Is_ROSHN_Developed': pd.DataFrame({'Is_ROSHN_Developed': w_is_roshn_developed}),
                # Final Outputs - Costs
                'o_Sales_Cost': o_sales_cost,
                'o_Marketing_Cost': o_marketing_cost,
                'o_Total_Sales_Mktg_Cost': o_total_sales_marketing_cost,
                # Working - Sales Price Escalation (from SUB-MODULE 3.8)
                'w_Sales_Price_Esc_Pct': w_sales_price_monthly_escalation_percent,
                'w_Sales_Price_Esc_Factor': w_sales_price_monthly_escalation_factors,
                'w_Sales_Price_Escalated': w_sales_price_escalated,
                # Working - Sales Phasing (from SUB-MODULE 3.8)
                'w_Sales_Phasing_User_Def': w_sales_phasing_user_defined_all,
                'w_Sales_Phasing_Pre_Def': w_sales_phasing_pre_defined_all,
                # Working - Collection Phasing (from SUB-MODULE 3.8)
                'w_Sales_Collection_Phasing': w_sales_collection_phasing,
                # Working - Sales Input Values
                'w_Sales_Value': pd.DataFrame({'Sales_Value': w_sales_value}),
                'w_Sales_Start_Date': pd.DataFrame({'Sales_Start_Date': Asset.Disposal.sales_start_date}),
                'w_Sales_Duration': pd.DataFrame({'Sales_Duration': Asset.Disposal.sales_duration}),
                'w_Sales_Phasing_Option': pd.DataFrame({'Phasing_Option': Asset.Disposal.sales_phasing_option}),
                'w_Sales_Phasing_Profile': pd.DataFrame({'Phasing_Profile': Asset.Disposal.sales_phasing_profile}),
                # Working - Area Reference
                'w_GFA': pd.DataFrame({'GFA': Asset.LandAreaProgram.gross_floor_area}),
            }
            _export_to_excel(disposal_export_dict, 'devco_disposal_sales', 'Disposal & Sales')

        # ========================================================================
        # EXPORT CORPORATE OVERHEAD (if enabled)
        # ========================================================================
        # Note: Corporate Overhead calculations are done earlier (before Escrow section)
        # to make o_total_coh_capitalized available for escrow calculations.
        # ========================================================================
        
        if _EXPORT_FLAGS['corporate_overhead']:

            coh_export_dict = {

                # Salaries
                'o_Salaries_Total': coh_results['salaries']['total'],
                'o_Salaries_Capitalized': coh_results['salaries']['capitalized'],
                'o_Salaries_Expensed': coh_results['salaries']['expensed'],

                # IT Services
                'o_IT_Services_Total': coh_results['it_services']['total'],
                'o_IT_Services_Capitalized': coh_results['it_services']['capitalized'],
                'o_IT_Services_Expensed': coh_results['it_services']['expensed'],

                # Office Rent & Utilities
                'o_Office_Rent_Total': coh_results['office_rent_utilities']['total'],
                'o_Office_Rent_Capitalized': coh_results['office_rent_utilities']['capitalized'],
                'o_Office_Rent_Expensed': coh_results['office_rent_utilities']['expensed'],

                # Professional Services
                'o_Prof_Services_Total': coh_results['professional_services']['total'],
                'o_Prof_Services_Capitalized': coh_results['professional_services']['capitalized'],
                'o_Prof_Services_Expensed': coh_results['professional_services']['expensed'],

                # Marketing
                'o_COH_Marketing_Total': coh_results['coh_marketing']['total'],
                'o_COH_Marketing_Capitalized': coh_results['coh_marketing']['capitalized'],
                'o_COH_Marketing_Expensed': coh_results['coh_marketing']['expensed'],

                # Sales Cost
                'o_COH_Sales_Cost_Total': coh_results['coh_sales_cost']['total'],
                'o_COH_Sales_Cost_Capitalized': coh_results['coh_sales_cost']['capitalized'],
                'o_COH_Sales_Cost_Expensed': coh_results['coh_sales_cost']['expensed'],

                # Additional
                'o_Additional_Total': coh_results['additional']['total'],
                'o_Additional_Capitalized': coh_results['additional']['capitalized'],
                'o_Additional_Expensed': coh_results['additional']['expensed'],

                # Aggregated Totals
                'o_Total_COH': o_total_coh,
                'o_Total_COH_Capitalized': o_total_coh_capitalized,
                'o_Total_COH_Expensed': o_total_coh_expensed,
            }

            _export_to_excel(
                coh_export_dict,
                'devco_corporate_overhead',
                'Corporate Overhead'
            )

        # ========================================================================
        # SUB-MODULE 3.12: OTHER INCOME AND EXPENSES FUNCTIONS
        # ========================================================================

        def fn_calculate_other_income_expense_item(
            template,
            item_type,
            start_date_series,
            duration_series,
            calculation_approach_series,
            percent_series,
            ad_hoc_series,
            cost_per_sqm_series,
            cost_basis_series,
            sales_revenue_df,
            escalation_factor_df,
            phasing_profile_df
        ):
            """
            Calculate a single other income or expense item.

            Calculation flow:
            1. Determine total amount per asset based on calculation approach
            2. Apply user-defined phasing profile (from fn_calculate_user_defined_profile)
            3. Multiply by escalation factors

            Calculation Approaches:
            - '% of Revenue': sales_revenue_total Ã— percentage
            - 'Ad-Hoc Amount': Fixed amount
            - 'SAR/SQM': area (dynamically resolved from cost_basis) Ã— cost_per_sqm

            Args:
                template: Zero-initialized template
                item_type: 'income' or 'expense'
                start_date_series: Start dates per asset
                duration_series: Durations per asset
                calculation_approach_series: Calculation approach per asset
                percent_series: Percentages per asset
                ad_hoc_series: Ad-hoc amounts
                cost_per_sqm_series: Cost per sqm
                cost_basis_series: Cost basis per asset (determines area for SAR/SQM)
                sales_revenue_df: Sales revenue DataFrame (asset Ã— period)
                escalation_factor_df: Escalation factors (asset Ã— period)
                phasing_profile_df: User-defined phasing profile (asset Ã— period)

            Returns:
                pd.DataFrame: Other income/expense per asset per period
            """
            try:
                result_df = template.copy()
                result_df.iloc[:, :] = 0.0

                # --- Pre-compute area per asset dynamically from cost_basis ---
                _cb_arr = np.array([
                    cost_basis_series[i] if i < len(cost_basis_series) and pd.notna(cost_basis_series[i]) else 'Gross Floor Area'
                    for i in range(len(template))
                ])
                _gfa = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.gross_floor_area if Asset.LandAreaProgram.gross_floor_area else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)
                _bua = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.built_up_area if Asset.LandAreaProgram.built_up_area else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)
                _dla = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.developable_land_area if Asset.LandAreaProgram.developable_land_area else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)
                _gla = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.gross_land_area if Asset.LandAreaProgram.gross_land_area else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)
                _units = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.units if hasattr(Asset.LandAreaProgram, 'units') and Asset.LandAreaProgram.units else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)
                _nsa = pd.to_numeric(
                    pd.Series(Asset.LandAreaProgram.total_nsa__gla if hasattr(Asset.LandAreaProgram, 'total_nsa__gla') and Asset.LandAreaProgram.total_nsa__gla else [0] * _n_assets),
                    errors='coerce'
                ).fillna(0.0).values.astype(float)

                _resolved_area = np.select(
                    [
                        _cb_arr == 'Built Up Area',
                        _cb_arr == 'Gross Floor Area',
                        _cb_arr == 'Developable Land Area',
                        _cb_arr == 'Gross Land Area',
                        _cb_arr == 'Units',
                        _cb_arr == 'Net Saleable Area'
                    ],
                    [_bua, _gfa, _dla, _gla, _units, _nsa],
                    default=_gfa
                )

                for idx in template.index:
                    start_date = start_date_series[idx] if idx < len(start_date_series) else None
                    duration = duration_series[idx] if idx < len(duration_series) else 12
                    calc_approach = calculation_approach_series[idx] if idx < len(calculation_approach_series) else 'Ad-Hoc Amount'

                    if pd.isna(start_date) or start_date is None:
                        continue

                    start_date = pd.to_datetime(start_date)
                    duration = int(duration) if pd.notna(duration) and duration > 0 else 12

                    # Calculate total amount
                    total_amount = 0.0

                    if calc_approach == '% of Revenue':
                        pct = percent_series[idx] if idx < len(percent_series) else 0
                        revenue_total = sales_revenue_df.iloc[idx, :].sum() if hasattr(sales_revenue_df, 'iloc') else 0
                        total_amount = revenue_total * (float(pct) if pd.notna(pct) else 0)
                    elif calc_approach == 'Ad-Hoc Amount':
                        ad_hoc = ad_hoc_series[idx] if idx < len(ad_hoc_series) else 0
                        total_amount = float(ad_hoc) if pd.notna(ad_hoc) else 0
                    elif calc_approach == 'SAR/SQM':
                        cost_sqm = cost_per_sqm_series[idx] if idx < len(cost_per_sqm_series) else 0
                        area = _resolved_area[idx]
                        total_amount = (float(cost_sqm) if pd.notna(cost_sqm) else 0) * area

                    if total_amount <= 0:
                        continue

                    # Find start period
                    start_idx = np.searchsorted(_period_starts, np.datetime64(start_date))
                    if start_idx >= _n_periods:
                        continue

                    end_idx = min(start_idx + duration, _n_periods)

                    # Apply: total_amount Ã— phasing_profile Ã— escalation_factor
                    profile_vals = phasing_profile_df.iloc[idx, start_idx:end_idx].values.astype(float)
                    esc_factors = escalation_factor_df.iloc[idx, start_idx:end_idx].values.astype(float)
                    result_df.iloc[idx, start_idx:end_idx] = total_amount * profile_vals * esc_factors

                return result_df
            except Exception as e:
                print(f"Error in fn_calculate_other_income_expense_item ({item_type}): {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

        # ========================================================================
        # EXECUTE OTHER INCOME/EXPENSE CALCULATIONS
        # ========================================================================

        # --- Define all 6 OIE items with their config ---
        # Each entry: (output_var_name, item_type, asset_prefix, global_prefix, schedule_named_range)
        _oie_items_config = [
            ('government_subsidies', 'income',  'governement_subsidies', 'government_subsidies', 's.devco.governement.subsidies.phasing'),
            ('other_income_1',       'income',  'other_income_1',        'other_income_1',        's.devco.other.income1.payment'),
            ('other_income_2',       'income',  'other_income_2',        'other_income_2',        's.devco.other.income2.payment'),
            ('other_expense_1',      'expense', 'other_expense_1',       'other_expense_1',       's.devco.other.expense1.cost.payment'),
            ('other_expense_2',      'expense', 'other_expense_2',       'other_expense_2',       's.devco.other.expense2.cost.payment'),
            ('other_expense_3',      'expense', 'other_expense_3',       'other_expense_3',       's.devco.other.expense3.cost.payment'),
        ]

        _oie_asset = Asset.OtherIncomeandExpense
        _oie_global = Global.OtherIncomeandExpenses

        # --- Loop through all 6 items, applying override + escalation + phasing ---
        _oie_outputs = {}

        def _compute_oie_item(item_config):
            item_name, item_type, asset_pfx, global_pfx, schedule_range = item_config

            # --- Step 1: Resolve override (asset vs global) ---
            _override_series = getattr(_oie_asset, f'{asset_pfx}_override', None)
            _override_flags = np.array(
                _override_series if _override_series else ['No'] * _n_assets
            )
            _is_override = _override_flags == 'Yes'

            # Start date
            _asset_start = getattr(_oie_asset, f'{asset_pfx}_start_date', None) or [None] * _n_assets
            _global_start = getattr(_oie_global, f'{global_pfx}_start_date', None)
            w_start_dates = np.where(_is_override, _asset_start, _global_start)

            # Duration
            _asset_dur = getattr(_oie_asset, f'{asset_pfx}_duration', None) or [0] * _n_assets
            _global_dur = getattr(_oie_global, f'{global_pfx}_duration', None)
            w_durations = np.where(_is_override, _asset_dur, _global_dur)

            # Calculation approach
            _asset_calc = getattr(_oie_asset, f'{asset_pfx}_calculation_approach', None) or ['Ad-Hoc Amount'] * _n_assets
            _global_calc = getattr(_oie_global, f'{global_pfx}_calculation_approach', None)
            w_calc_approach = np.where(_is_override, _asset_calc, _global_calc)

            # Cost basis
            _asset_cb = getattr(_oie_asset, f'{asset_pfx}_cost_basis', None) or [None] * _n_assets
            _global_cb = getattr(_oie_global, f'{global_pfx}_cost_basis', None)
            w_cost_basis = np.where(_is_override, _asset_cb, _global_cb)

            # Percent
            _asset_pct = getattr(_oie_asset, f'{asset_pfx}_percent', None) or [0] * _n_assets
            _global_pct = getattr(_oie_global, f'{global_pfx}_percent_of_revenue', None)
            w_percent = np.where(_is_override, _asset_pct, _global_pct)

            # Cost per sqm
            _asset_sqm = getattr(_oie_asset, f'{asset_pfx}_sarsqm', None) or [0] * _n_assets
            _global_sqm = getattr(_oie_global, f'{global_pfx}_cost_per_sqm', None)
            w_cost_per_sqm = np.where(_is_override, _asset_sqm, _global_sqm)

            # Escalation profile
            _asset_esc = getattr(_oie_asset, f'{asset_pfx}_escalation_profile', None) or [None] * _n_assets
            _global_esc = getattr(_oie_global, f'{global_pfx}_escalation_profile', None)
            w_escalation_profile = np.where(_is_override, pd.Series(_asset_esc).astype(str), str(_global_esc) if _global_esc is not None else '')

            # Ad-hoc amount (asset-level only, no global equivalent)
            w_ad_hoc = getattr(_oie_asset, f'{asset_pfx}_ad_hoc_amount', None) or [0] * _n_assets

            # --- Step 2: Compute escalation factors using fn_calculate_monthly_escalation_profile ---
            w_oie_esc_percent = _create_zero_df()
            w_oie_esc_factor = _create_zero_df()

            w_oie_esc_percent, w_oie_esc_factor = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_oie_esc_percent,
                escalation_factor_template=w_oie_esc_factor,
                selected_escalation_profile=w_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            # --- Step 3: Build user-defined phasing profile ---
            w_oie_phasing_profile = _create_zero_df()
            _profile_options = ["User defined"] * _n_assets

            w_oie_phasing_profile = fn_calculate_user_defined_profile(
                template=w_oie_phasing_profile,
                profile_options=_profile_options,
                schedules=fn_get_named_range_value(assumptions, schedule_range, []),
                start_dates=w_start_dates,
                durations=w_durations,
                model_timeline_me=model_timeline_me
            )

            # --- Step 4: Calculate the item ---
            return fn_calculate_other_income_expense_item(
                template=_create_zero_df(),
                item_type=item_type,
                start_date_series=w_start_dates,
                duration_series=w_durations,
                calculation_approach_series=w_calc_approach,
                percent_series=w_percent,
                ad_hoc_series=w_ad_hoc,
                cost_per_sqm_series=w_cost_per_sqm,
                cost_basis_series=w_cost_basis,
                sales_revenue_df=o_sales_revenue,
                escalation_factor_df=w_oie_esc_factor,
                phasing_profile_df=w_oie_phasing_profile
            )

        if _max_parallel_workers > 1:
            _oie_outputs.update(_execute_named_threaded_tasks({
                cfg[0]: (lambda c=cfg: _compute_oie_item(c))
                for cfg in _oie_items_config
            }))
        else:
            for cfg in _oie_items_config:
                _oie_outputs[cfg[0]] = _compute_oie_item(cfg)

        # --- Extract outputs ---
        o_government_subsidies = _oie_outputs['government_subsidies']
        o_other_income_1 = _oie_outputs['other_income_1']
        o_other_income_2 = _oie_outputs['other_income_2']
        o_other_expense_1 = _oie_outputs['other_expense_1']
        o_other_expense_2 = _oie_outputs['other_expense_2']
        o_other_expense_3 = _oie_outputs['other_expense_3']

        # Totals
        o_total_other_income = o_government_subsidies + o_other_income_1 + o_other_income_2
        o_total_other_expense = o_other_expense_1 + o_other_expense_2 + o_other_expense_3

        _record_timing("Other income/expense calculated")

        # ========================================================================
        # EXPORT OTHER INCOME/EXPENSE (if enabled)
        # ========================================================================

        if _EXPORT_FLAGS['other_income_expense']:
            oie_export_dict = {
                # Final Outputs - Income
                'o_Government_Subsidies': o_government_subsidies,
                'o_Other_Income_1': o_other_income_1,
                'o_Other_Income_2': o_other_income_2,
                'o_Total_Other_Income': o_total_other_income,
                # Final Outputs - Expense
                'o_Other_Expense_1': o_other_expense_1,
                'o_Other_Expense_2': o_other_expense_2,
                'o_Other_Expense_3': o_other_expense_3,
                'o_Total_Other_Expense': o_total_other_expense,
                # Working - Sales Revenue Reference
                'w_Sales_Revenue': o_sales_revenue,
                # Working - Area Reference
                'w_GFA': pd.DataFrame({'GFA': Asset.LandAreaProgram.gross_floor_area}),
                'w_BUA': pd.DataFrame({'BUA': Asset.LandAreaProgram.built_up_area}),
                'w_DLA': pd.DataFrame({'DLA': Asset.LandAreaProgram.developable_land_area}),
                'w_GLA': pd.DataFrame({'GLA': Asset.LandAreaProgram.gross_land_area}),
            }
            _export_to_excel(oie_export_dict, 'devco_other_income_expense', 'Other Income & Expense')

        # ========================================================================
        # SUB-MODULE 3.13: COST ALLOCATION SUBMODULE
        # ========================================================================
        # Cost allocation for Public Amenities, CEC, and Canal costs.
        #
        # These costs from source assets (PA/CEC/Canal asset classes) are
        # reallocated to eligible recipient assets based on GFA or BUA.
        #
        # NO ADDITIONAL ESCALATION is applied â€” costs are already escalated in
        # their respective upstream modules. This is purely a reallocation.
        #
        # Cost components included:
        #   1. Land acquisition cost          (Acquisition module)
        #   2. Transaction costs              (Acquisition module)
        #   3. Vertical construction costs    (VD module)
        #   4. Soft costs (incl. contingency) (VD module)
        #   5. Corporate overheads            (COH module)
        #   6. Other income/expenses (net)    (OIE module)
        #
        # Outputs produced (used in cashflow statement):
        #   o_pa_allocation                              â€” PA costs allocated TO recipients (asset Ã— period)
        #   o_cec_allocation                             â€” CEC costs allocated TO recipients
        #   o_canal_allocation                           â€” Canal costs allocated TO recipients
        #   o_total_allocation                           â€” Sum of PA + CEC + Canal allocations
        #   o_pa_recovery                                â€” PA recovery income per asset Ã— period
        #   o_vertical_construction_cost_post_allocation â€” VD cost after removing PA/CEC/Canal share
        #   o_*_post_allocation                          â€” Other costs after removing allocated portion
        # ========================================================================

        _special_classes = ["Public Amenities", "CEC", "Canal"]
        _round_dp = 2

        # --- Build asset attribute arrays from Asset class ---
        _asset_ids = list(range(_n_assets))
        _asset_classes = list(Asset.ProjectDetails.asset_class) if Asset.ProjectDetails.asset_class else [''] * _n_assets
        _asset_gfa = pd.to_numeric(
            pd.Series(Asset.LandAreaProgram.gross_floor_area if Asset.LandAreaProgram.gross_floor_area else [0] * _n_assets),
            errors='coerce'
        ).fillna(0.0).values.astype(float)
        _asset_bua = pd.to_numeric(
            pd.Series(Asset.LandAreaProgram.built_up_area if Asset.LandAreaProgram.built_up_area else [0] * _n_assets),
            errors='coerce'
        ).fillna(0.0).values.astype(float)

        # --- Normalize allocation basis from Global inputs ---
        def _normalize_alloc_basis(value):
            return {"Gross Floor Area": "GFA", "Built Up Area": "BUA"}.get(value, "GFA")

        _alloc_config = {
            "Public Amenities": _normalize_alloc_basis(Global.CostAllocationInputs.public_amenity_cost),
            "CEC": _normalize_alloc_basis(Global.CostAllocationInputs.cec_cost),
            "Canal": _normalize_alloc_basis(Global.CostAllocationInputs.canal_cost),
        }

        

        # --- Identify source and recipient indices (vectorized) ---
        _source_mask = np.isin(_asset_classes, _special_classes)
        _recipient_mask = ~_source_mask  # All non-special-class assets are recipients

        w_source_indices = np.where(_source_mask)[0].tolist()
        w_recipient_indices = np.where(_recipient_mask)[0].tolist()

        # --- Assemble cost component arrays for allocation ---
        # These are the costs that get reallocated from source to recipient assets.
        # Each sub-component is tracked individually so post-allocation can be computed directly.
        #
        # Sign convention in pool:
        #   Costs    â†’ positive (adds to total development cost)
        #   Income   â†’ positive (reduces net cost â€” allocated as offset)
        #   Expenses â†’ negative (increases net cost via income âˆ’ expense)
        _ensure_transaction_cost_results()  # OPTIMIZED: materialize deferred transaction-cost outputs at the first unconditional downstream use.
        _alloc_cost_components = {
            # Acquisition
            "land_acquisition": o_land_acquisition_cost.values.copy(),
            # Transaction cost sub-components
            "legal_cost": o_legal_cost.values.copy(),
            "agency_cost": o_agency_cost.values.copy(),
            "technical_cost": o_technical_cost.values.copy(),
            "valuation_cost": o_valuation_cost.values.copy(),
            "due_diligence_cost": o_due_diligence_cost.values.copy(),
            # Vertical construction
            "vertical": o_vertical_construction_cost.values.copy(),
            # Soft cost sub-components
            "design_cost": o_design_cost.values.copy(),
            "permitting_cost": o_permitting_cost.values.copy(),
            "supervision_cost": o_supervision_cost.values.copy(),
            "pm_fees": o_pm_fees.values.copy(),
            "contingency_cost": o_contingency_cost.values.copy(),
            # COH capitalized sub-components
            "coh_salaries_capitalized": coh_results["salaries"]["capitalized"].values.copy(),
            "coh_it_services_capitalized": coh_results["it_services"]["capitalized"].values.copy(),
            "coh_office_rent_capitalized": coh_results["office_rent_utilities"]["capitalized"].values.copy(),
            "coh_professional_services_capitalized": coh_results["professional_services"]["capitalized"].values.copy(),
            "coh_marketing_capitalized": coh_results["coh_marketing"]["capitalized"].values.copy(),
            "coh_sales_cost_capitalized": coh_results["coh_sales_cost"]["capitalized"].values.copy(),
            "coh_additional_capitalized": coh_results["additional"]["capitalized"].values.copy(),
            # COH expensed sub-components
            "coh_salaries_expensed": coh_results["salaries"]["expensed"].values.copy(),
            "coh_it_services_expensed": coh_results["it_services"]["expensed"].values.copy(),
            "coh_office_rent_expensed": coh_results["office_rent_utilities"]["expensed"].values.copy(),
            "coh_professional_services_expensed": coh_results["professional_services"]["expensed"].values.copy(),
            "coh_marketing_expensed": coh_results["coh_marketing"]["expensed"].values.copy(),
            "coh_sales_cost_expensed": coh_results["coh_sales_cost"]["expensed"].values.copy(),
            "coh_additional_expensed": coh_results["additional"]["expensed"].values.copy(),
            # Other income (positive in pool)
            "government_subsidies": o_government_subsidies.values.copy(),
            "other_income_1": o_other_income_1.values.copy(),
            "other_income_2": o_other_income_2.values.copy(),
            # Other expenses (negative in pool: income âˆ’ expense convention)
            "other_expense_1": (-o_other_expense_1).values.copy(),
            "other_expense_2": (-o_other_expense_2).values.copy(),
            "other_expense_3": (-o_other_expense_3).values.copy(),
        }

        # Total development cost for allocation (working variable, for export/debug)
        w_total_dev_cost_for_allocation = _create_zero_df()
        for _comp_vals in _alloc_cost_components.values():
            w_total_dev_cost_for_allocation.values[:] += _comp_vals

        # --- Pre-compute recipient area arrays (zero out source assets) ---
        _recip_gfa = _asset_gfa.copy()
        _recip_gfa[_source_mask] = 0.0
        _recip_bua = _asset_bua.copy()
        _recip_bua[_source_mask] = 0.0

        # --- Output accumulators (asset Ã— period) ---
        o_pa_allocation = _create_zero_df()
        o_cec_allocation = _create_zero_df()
        o_canal_allocation = _create_zero_df()

        # Track amounts subtracted from source assets per component
        _allocated_from_source = {comp: np.zeros((_n_assets, _n_periods)) for comp in _alloc_cost_components}

        _alloc_output_map = {
            "Public Amenities": o_pa_allocation,
            "CEC": o_cec_allocation,
            "Canal": o_canal_allocation,
        }

        # --- Vectorized allocation per special class ---
        for cls in _special_classes:
            # Source asset mask for this class
            cls_mask = np.array([c == cls for c in _asset_classes])
            cls_indices = np.where(cls_mask)[0]

            allocation_attr_map = {
                "Public Amenities": "public_amenities",
                "CEC": "cec",
                "Canal": "canal",
            }

            attr_name = allocation_attr_map.get(cls)

            if attr_name:
                allocation_mask = (
                    pd.Series(getattr(Asset.CostAllocation, attr_name))
                    .eq("Cost Allocation")
                    .to_numpy()
                )
            else:
                allocation_mask = np.zeros(_n_assets, dtype=bool)

            w_recipient_indices = np.where(_recipient_mask & allocation_mask)[0].tolist() if cls == "Public Amenities" else np.where(_recipient_mask)[0].tolist()

            if len(cls_indices) == 0:
                continue

            # Allocation basis for this class (GFA or BUA)
            basis = _alloc_config[cls]
            recip_area = _recip_gfa.copy() if basis == "GFA" else _recip_bua.copy()

            recip_area[~allocation_mask] = 0.0  # Zero out non-allocating assets (if any)

            total_recip_area = recip_area.sum()
            if total_recip_area <= 0.0:
                print(f"  Cost Allocation: No recipient area for {cls}. Skipping.")
                continue

            # Weights for recipient assets (n_assets,) â€” zero for source assets
            weights = recip_area / total_recip_area  # shape: (n_assets,)

            # Compute total pool per period from source assets across all components
            cls_total_per_period = np.zeros(_n_periods)
            cls_comp_per_period = {}

            for comp, comp_vals in _alloc_cost_components.items():
                # Sum across source assets of this class for each period
                comp_period_total = comp_vals[cls_indices, :].sum(axis=0)  # (n_periods,)
                cls_comp_per_period[comp] = comp_period_total
                cls_total_per_period += comp_period_total

            # Allocate total pool to recipients using np.outer broadcasting
            # allocated_to_recipients[i, t] = weights[i] * cls_total_per_period[t]
            allocated_total = np.outer(weights, cls_total_per_period)  # (n_assets, n_periods)
            allocated_total = np.round(allocated_total, _round_dp)

            # Reconcile rounding: push residual to largest-weight recipient
            residuals = cls_total_per_period - allocated_total.sum(axis=0)
            max_weight_idx = int(np.argmax(weights))
            allocated_total[max_weight_idx, :] += np.round(residuals, _round_dp)

            # Store in the appropriate output DataFrame
            _alloc_output_map[cls].values[:] = allocated_total

            # Track per-component subtraction from source assets
            for comp, comp_period_total in cls_comp_per_period.items():
                src_vals = _alloc_cost_components[comp][cls_indices, :]  # (n_source, n_periods)
                src_total = src_vals.sum(axis=0)  # (n_periods,)

                # Avoid division by zero
                safe_total = np.where(src_total != 0, src_total, 1.0)
                src_weights = src_vals / safe_total[np.newaxis, :]  # (n_source, n_periods)

                # Amount to subtract per source asset
                subtraction = src_weights * comp_period_total[np.newaxis, :]
                subtraction = np.round(subtraction, _round_dp)

                # Accumulate subtraction tracking
                for idx_pos, src_idx in enumerate(cls_indices):
                    _allocated_from_source[comp][src_idx, :] += subtraction[idx_pos, :]

        # --- Compute total allocation across all three classes ---
        o_total_allocation = _create_zero_df()
        o_total_allocation.values[:] = (
            o_pa_allocation.values + o_cec_allocation.values + o_canal_allocation.values
        )

        # --- Produce updated cost DataFrames (original minus allocated portion) ---
        # These represent the costs AFTER removing the portion that was reallocated
        # from source (PA/CEC/Canal) assets. Used downstream in cashflow statement.
        # Each sub-component is computed directly from its own _allocated_from_source entry.

        # Helper to build a post-allocation DataFrame
        def _post_alloc(original_values, alloc_key):
            result = _create_zero_df()
            result.values[:] = np.round(original_values - _allocated_from_source[alloc_key], _round_dp)
            return result

        # --- Land acquisition ---
        o_land_acquisition_cost_post_allocation = _post_alloc(o_land_acquisition_cost.values, "land_acquisition")

        # --- Transaction cost sub-components ---
        o_legal_cost_post_allocation = _post_alloc(o_legal_cost.values, "legal_cost")
        o_agency_cost_post_allocation = _post_alloc(o_agency_cost.values, "agency_cost")
        o_technical_cost_post_allocation = _post_alloc(o_technical_cost.values, "technical_cost")
        o_valuation_cost_post_allocation = _post_alloc(o_valuation_cost.values, "valuation_cost")
        o_due_diligence_cost_post_allocation = _post_alloc(o_due_diligence_cost.values, "due_diligence_cost")
        o_total_transaction_cost_post_allocation = (
            o_legal_cost_post_allocation + o_agency_cost_post_allocation +
            o_technical_cost_post_allocation + o_valuation_cost_post_allocation +
            o_due_diligence_cost_post_allocation
        )
        o_total_acquisition_cost_post_allocation = o_land_acquisition_cost_post_allocation + o_total_transaction_cost_post_allocation

        # --- Vertical construction ---
        o_vertical_construction_cost_post_allocation = _post_alloc(o_vertical_construction_cost.values, "vertical")

        # --- Soft cost sub-components ---
        o_design_cost_post_allocation = _post_alloc(o_design_cost.values, "design_cost")
        o_permitting_cost_post_allocation = _post_alloc(o_permitting_cost.values, "permitting_cost")
        o_supervision_cost_post_allocation = _post_alloc(o_supervision_cost.values, "supervision_cost")
        o_pm_fees_post_allocation = _post_alloc(o_pm_fees.values, "pm_fees")
        o_contingency_cost_post_allocation = _post_alloc(o_contingency_cost.values, "contingency_cost")
        o_total_soft_cost_post_allocation = (
            o_design_cost_post_allocation + o_permitting_cost_post_allocation +
            o_supervision_cost_post_allocation + o_pm_fees_post_allocation +
            o_contingency_cost_post_allocation
        )

        # --- COH capitalized sub-components ---
        o_coh_salaries_capitalized_post_allocation = _post_alloc(
            coh_results["salaries"]["capitalized"].values,
            "coh_salaries_capitalized"
        )
        o_coh_it_services_capitalized_post_allocation = _post_alloc(
            coh_results["it_services"]["capitalized"].values,
            "coh_it_services_capitalized"
        )
        o_coh_office_rent_capitalized_post_allocation = _post_alloc(
            coh_results["office_rent_utilities"]["capitalized"].values,
            "coh_office_rent_capitalized"
        )
        o_coh_professional_services_capitalized_post_allocation = _post_alloc(
            coh_results["professional_services"]["capitalized"].values,
            "coh_professional_services_capitalized"
        )
        o_coh_marketing_capitalized_post_allocation = _post_alloc(
            coh_results["coh_marketing"]["capitalized"].values,
            "coh_marketing_capitalized"
        )
        o_coh_sales_cost_capitalized_post_allocation = _post_alloc(
            coh_results["coh_sales_cost"]["capitalized"].values,
            "coh_sales_cost_capitalized"
        )
        o_coh_additional_capitalized_post_allocation = _post_alloc(
            coh_results["additional"]["capitalized"].values,
            "coh_additional_capitalized"
        )

        o_total_coh_capitalized_post_allocation = (
            o_coh_salaries_capitalized_post_allocation +
            o_coh_it_services_capitalized_post_allocation +
            o_coh_office_rent_capitalized_post_allocation +
            o_coh_professional_services_capitalized_post_allocation +
            o_coh_marketing_capitalized_post_allocation +
            o_coh_sales_cost_capitalized_post_allocation +
            o_coh_additional_capitalized_post_allocation
        )


        # --- COH expensed sub-components ---
        o_coh_salaries_expensed_post_allocation = _post_alloc(
            coh_results["salaries"]["expensed"].values,
            "coh_salaries_expensed"
        )
        o_coh_it_services_expensed_post_allocation = _post_alloc(
            coh_results["it_services"]["expensed"].values,
            "coh_it_services_expensed"
        )
        o_coh_office_rent_expensed_post_allocation = _post_alloc(
            coh_results["office_rent_utilities"]["expensed"].values,
            "coh_office_rent_expensed"
        )
        o_coh_professional_services_expensed_post_allocation = _post_alloc(
            coh_results["professional_services"]["expensed"].values,
            "coh_professional_services_expensed"
        )
        o_coh_marketing_expensed_post_allocation = _post_alloc(
            coh_results["coh_marketing"]["expensed"].values,
            "coh_marketing_expensed"
        )
        o_coh_sales_cost_expensed_post_allocation = _post_alloc(
            coh_results["coh_sales_cost"]["expensed"].values,
            "coh_sales_cost_expensed"
        )
        o_coh_additional_expensed_post_allocation = _post_alloc(
            coh_results["additional"]["expensed"].values,
            "coh_additional_expensed"
        )

        o_total_coh_expensed_post_allocation = (
            o_coh_salaries_expensed_post_allocation +
            o_coh_it_services_expensed_post_allocation +
            o_coh_office_rent_expensed_post_allocation +
            o_coh_professional_services_expensed_post_allocation +
            o_coh_marketing_expensed_post_allocation +
            o_coh_sales_cost_expensed_post_allocation +
            o_coh_additional_expensed_post_allocation
        )

        # --- Total COH post-allocation ---
        o_total_coh_post_allocation = o_total_coh_capitalized_post_allocation + o_total_coh_expensed_post_allocation

        # --- Other income sub-components (positive in pool â†’ subtract allocation) ---
        o_government_subsidies_post_allocation = _post_alloc(o_government_subsidies.values, "government_subsidies")
        o_other_income_1_post_allocation = _post_alloc(o_other_income_1.values, "other_income_1")
        o_other_income_2_post_allocation = _post_alloc(o_other_income_2.values, "other_income_2")
        o_total_other_income_post_allocation = (
            o_government_subsidies_post_allocation + o_other_income_1_post_allocation +
            o_other_income_2_post_allocation
        )

        # --- Other expense sub-components (negative in pool â†’ post = original + allocated) ---
        # _allocated_from_source["other_expense_*"] tracks values from the negative pool entries.
        # Post-allocation expense = original_expense - |allocated| = original + allocated (allocated is negative)
        o_other_expense_1_post_allocation = _create_zero_df()
        o_other_expense_1_post_allocation.values[:] = np.round(
            o_other_expense_1.values + _allocated_from_source["other_expense_1"], _round_dp
        )
        o_other_expense_2_post_allocation = _create_zero_df()
        o_other_expense_2_post_allocation.values[:] = np.round(
            o_other_expense_2.values + _allocated_from_source["other_expense_2"], _round_dp
        )
        o_other_expense_3_post_allocation = _create_zero_df()
        o_other_expense_3_post_allocation.values[:] = np.round(
            o_other_expense_3.values + _allocated_from_source["other_expense_3"], _round_dp
        )
        o_total_other_expense_post_allocation = (
            o_other_expense_1_post_allocation + o_other_expense_2_post_allocation +
            o_other_expense_3_post_allocation
        )

        # --- Aggregate other_net post-allocation (for backward compatibility / export) ---
        o_other_net_post_allocation = o_total_other_income_post_allocation - o_total_other_expense_post_allocation

        # --- PA Recovery Calculation ---
        # PA Recovery is income received by recipient assets to compensate for
        # public amenity costs allocated to them. Phased using the user-defined
        # profile from s.devco.PA.recovery via fn_calculate_user_defined_profile.
        # The profile % is directly multiplied to (PA allocation Ã— recovery %).

        # Step 1: Build the user-defined recovery profile (asset Ã— period)
        # using fn_calculate_user_defined_profile â€” same pattern as acquisition/VD schedules
        w_pa_recovery_profile = _create_zero_df()

        _pa_recovery_start = Asset.PARecovery.start_date if Asset.PARecovery.start_date else [None] * _n_assets
        _pa_recovery_duration = Asset.PARecovery.duration if Asset.PARecovery.duration else [0] * _n_assets
        _pa_recovery_pct = Asset.PARecovery.recovery_percent if Asset.PARecovery.recovery_percent else [0] * _n_assets

        # All PA recovery assets use the user-defined profile
        _pa_recovery_profile_options = ["User defined"] * _n_assets

        w_pa_recovery_profile = fn_calculate_user_defined_profile(
            template=w_pa_recovery_profile,
            profile_options=_pa_recovery_profile_options,
            schedules=_cached_user_defined_schedules["pa_recovery"],
            start_dates=_pa_recovery_start,
            durations=_pa_recovery_duration,
            model_timeline_me=model_timeline_me
        )

        # Step 2: Compute recoverable amount per asset = PA allocation total Ã— recovery %
        # Step 3: Multiply profile by recoverable amount to get phased PA recovery
        o_pa_recovery = _create_zero_df()

        for i in w_recipient_indices:
            pa_alloc_total = o_pa_allocation.values[i, :].sum()
            if pa_alloc_total <= 0.0:
                continue

            recovery_pct = float(_pa_recovery_pct[i]) if _pa_recovery_pct[i] else 0.0
            if recovery_pct <= 0.0:
                continue

            recoverable_amount = pa_alloc_total * recovery_pct

            # Profile % Ã— recoverable amount
            o_pa_recovery.values[i, :] = np.round(
                w_pa_recovery_profile.values[i, :] * recoverable_amount, _round_dp
            )

        _record_timing("Cost allocation and PA recovery calculated")

        # ========================================================================
        # EXPORT COST ALLOCATION (if enabled)
        # ========================================================================

        if _EXPORT_FLAGS['cost_allocation']:
            allocation_export_dict = {
                # Final Outputs â€” Allocations per class
                'o_PA_Allocation': o_pa_allocation,
                'o_CEC_Allocation': o_cec_allocation,
                'o_Canal_Allocation': o_canal_allocation,
                'o_Total_Allocation': o_total_allocation,
                'o_PA_Recovery': o_pa_recovery,
                # Final Outputs â€” Post-allocation costs
                'o_VD_Post_Allocation': o_vertical_construction_cost_post_allocation,
                'o_Soft_Post_Allocation': o_total_soft_cost_post_allocation,
                'o_Acquisition_Post_Allocation': o_land_acquisition_cost_post_allocation,
                'o_Transaction_Post_Allocation': o_total_transaction_cost_post_allocation,
                'o_COH_Post_Allocation': o_total_coh_post_allocation,
                'o_OtherNet_Post_Allocation': o_other_net_post_allocation,
                # Sub-component Post-Allocation
                'o_Legal_Post_Alloc': o_legal_cost_post_allocation,
                'o_Agency_Post_Alloc': o_agency_cost_post_allocation,
                'o_Technical_Post_Alloc': o_technical_cost_post_allocation,
                'o_Valuation_Post_Alloc': o_valuation_cost_post_allocation,
                'o_DueDiligence_Post_Alloc': o_due_diligence_cost_post_allocation,
                'o_Design_Post_Alloc': o_design_cost_post_allocation,
                'o_Permitting_Post_Alloc': o_permitting_cost_post_allocation,
                'o_Supervision_Post_Alloc': o_supervision_cost_post_allocation,
                'o_PM_Fees_Post_Alloc': o_pm_fees_post_allocation,
                'o_Contingency_Post_Alloc': o_contingency_cost_post_allocation,
                'o_COH_Cap_Post_Alloc': o_total_coh_capitalized_post_allocation,
                'o_COH_Exp_Post_Alloc': o_total_coh_expensed_post_allocation,
                'o_GovtSub_Post_Alloc': o_government_subsidies_post_allocation,
                'o_OI1_Post_Alloc': o_other_income_1_post_allocation,
                'o_OI2_Post_Alloc': o_other_income_2_post_allocation,
                'o_OE1_Post_Alloc': o_other_expense_1_post_allocation,
                'o_OE2_Post_Alloc': o_other_expense_2_post_allocation,
                'o_OE3_Post_Alloc': o_other_expense_3_post_allocation,
                # Working â€” Source/Recipient Identification
                'w_Asset_Class': pd.DataFrame({'Asset_Class': _asset_classes}),
                'w_Source_Indices': pd.DataFrame({'Source_Indices': w_source_indices if w_source_indices else []}),
                'w_Recipient_Indices': pd.DataFrame({'Recipient_Indices': w_recipient_indices if w_recipient_indices else []}),
                # Working â€” Total Development Cost for Allocation
                'w_Total_Dev_Cost': w_total_dev_cost_for_allocation,
                # Working â€” Allocation Basis (Area)
                'w_GFA': pd.DataFrame({'GFA': _asset_gfa}),
                'w_BUA': pd.DataFrame({'BUA': _asset_bua}),
            }
            _export_to_excel(allocation_export_dict, 'devco_cost_allocation', 'Cost Allocation')

        # ========================================================================
        # SUB-MODULE 3.14: FINANCING MODULE
        # ========================================================================
        # This module handles all financing-related calculations including:
        #   - 3.14.1: Asset Level Financing (Asset Debt Revolver)
        #   - 3.14.2: Project Level Financing (Term Loan & Project Revolver)
        # ========================================================================
        
        _record_timing("Financing module start")

        # ========================================================================
        # SUB-MODULE 3.14.1: ASSET LEVEL FINANCING
        # ========================================================================
        # This sub-module handles asset-level financing calculations:
        #   - Asset Level Debt Revolver: Drawdown, Repayment, Cash Reserve
        #   - Asset Level Arrangement Fees
        #   - Asset Level Interest Calculations
        #   - Asset to Project Fund Transfers
        # ========================================================================
        
        _record_timing("Asset level financing start")

        # ============================================================================================
        # PRE-FINANCING CASHFLOWS (Asset-wise)
        # ============================================================================================
        # Net Cashflow from Operations + Net Cashflow from Investments
        
        def fn_validate_dataframe_dimensions(dataframes_list: list, template: pd.DataFrame) -> list:
            """
            Validate and normalize DataFrames to match template dimensions.
            """
            expected_shape = template.shape
            normalized_dfs = []
            
            for i, df in enumerate(dataframes_list):
                if not isinstance(df, pd.DataFrame):
                    df = pd.DataFrame(df, index=template.index, columns=template.columns)
                df = df.fillna(0.0)
                normalized_dfs.append(df)
            
            return normalized_dfs
        
        # Define inflows and outflows for pre-financing cashflows
        # Note: Uses post-allocation costs to avoid double counting with o_total_allocation
        # Inflows include: non-escrow collection, on-plan collection, escrow releases,
        #   forward funding/sales, other income (post-alloc), PA recovery
        # Outflows include: all costs post-allocation, DLP, void opex, sales & marketing,
        #   escrow setup fees, cost allocation to recipients
        _inflow_dfs = [
            fn_replace_nan(o_sales_collection_without_escrow),              # Non-escrow off-plan sales collection
            fn_replace_nan(o_on_plan_sales_collection),                     # On-plan sales collection (escrow + non-escrow, post-construction)
            fn_replace_nan(o_total_escrow_release),                         # Escrow releases (hard + soft + retention)
            fn_replace_nan(o_forward_funding_cash),                         # Forward funding milestone payments
            fn_replace_nan(o_forward_sales_cash),                           # Forward sales lump-sum payment
            fn_replace_nan(o_government_subsidies_post_allocation),         # Government subsidies (post-allocation)
            fn_replace_nan(o_other_income_1_post_allocation),               # Other income 1 (post-allocation)
            fn_replace_nan(o_other_income_2_post_allocation),               # Other income 2 (post-allocation)
            fn_replace_nan(o_pa_recovery),                                  # PA recovery income
        ]
        
        _outflow_dfs = [
            fn_replace_nan(o_land_acquisition_cost_post_allocation),        # Land acquisition (post-allocation)
            fn_replace_nan(o_total_transaction_cost_post_allocation),       # Transaction costs (post-allocation)
            fn_replace_nan(o_vertical_construction_cost_post_allocation),   # Vertical construction (post-allocation)
            fn_replace_nan(o_total_soft_cost_post_allocation),              # Soft costs (post-allocation)
            fn_replace_nan(o_dlp_insurance),                                # DLP insurance
            fn_replace_nan(o_void_period_opex),                             # Void period opex
            fn_replace_nan(o_total_coh_expensed_post_allocation),           # COH expensed (post-allocation)
            fn_replace_nan(o_total_coh_capitalized_post_allocation),        # COH capitalized (post-allocation)
            fn_replace_nan(o_other_expense_1_post_allocation),              # Other expense 1 (post-allocation)
            fn_replace_nan(o_other_expense_2_post_allocation),              # Other expense 2 (post-allocation)
            fn_replace_nan(o_other_expense_3_post_allocation),              # Other expense 3 (post-allocation)
            fn_replace_nan(o_total_sales_marketing_cost),                   # Sales & marketing cost
            fn_replace_nan(o_escrow_setup_fees),                            # Escrow setup fees
            fn_replace_nan(o_total_allocation),                             # Cost allocation to recipients (PA + CEC + Canal)
        ]
        
        # Validate and normalize DataFrames
        _inflow_dfs = fn_validate_dataframe_dimensions(_inflow_dfs, _create_zero_df())
        _outflow_dfs = fn_validate_dataframe_dimensions(_outflow_dfs, _create_zero_df())
        
        # Optimized calculation using numpy stacking
        _inflows_sum = np.stack([df.values for df in _inflow_dfs], axis=0).sum(axis=0)
        _outflows_sum = np.stack([df.values for df in _outflow_dfs], axis=0).sum(axis=0)
        
        w_pre_financing_cashflows = pd.DataFrame(
            _inflows_sum - _outflows_sum,
            index=template_asset_timeline.index,
            columns=template_asset_timeline.columns
        )

        # ============================================================================================
        # JV ASSET LEVEL INCLUSION FLAG
        # ============================================================================================
        _jv_inclusion_flag = pd.Series(Asset.JVModule.jvjda_inclusion) == "Yes"
        _jv_devco_inclusion_flag = pd.Series(Asset.JVModule.devco_inclusion) == "Yes"
        _jv_asset_level_inclusion_flag = _jv_inclusion_flag & _jv_devco_inclusion_flag

        w_pre_financing_cashflows_jv_included = _create_zero_df()
        w_pre_financing_cashflows_jv_excluded = _create_zero_df()

        w_pre_financing_cashflows_jv_included[_jv_asset_level_inclusion_flag] = w_pre_financing_cashflows[_jv_asset_level_inclusion_flag]

        w_pre_financing_cashflows_jv_excluded = w_pre_financing_cashflows.copy()
        w_pre_financing_cashflows_jv_excluded[_jv_asset_level_inclusion_flag] = 0.0

        # ============================================================================================
        # ASSET DEBT REVOLVER FLAGS AND DATES (VECTORIZED)
        # ============================================================================================

        # Pre-compute override mask (Asset.Financing.asset_financing_override)
        _override_mask = np.array(Asset.Financing.asset_financing_override if Asset.Financing.asset_financing_override else ['No'] * _n_assets) == "Yes"
        
        # Funding Type flag per asset: "Asset Financing" or "Project Financing"
        # Assets with "Asset Financing" use asset-level revolver.
        # Assets with "Project Financing" skip asset-level revolver; their
        # pre-financing cashflows flow directly to project-level financing.
        _funding_type_raw = Asset.Financing.funding_type if Asset.Financing.funding_type else ['None'] * _n_assets
        _funding_type_updated = ['None' if not (isinstance(n, (int, float)) and not (isinstance(n, float) and math.isnan(n))) else ft for ft, n in zip(_funding_type_raw, Asset.ProjectDetails.number)]

        _is_asset_financing = np.array([str(ft).strip().lower() == 'asset financing' for ft in _funding_type_updated])
        _is_project_financing = np.array([str(ft).strip().lower() == 'project financing' for ft in _funding_type_updated])
        
        # Asset Debt Revolver - Start Date, Duration, End Date (vectorized)
        w_asset_revolver_start_date = pd.to_datetime(np.where(
            _override_mask,
            Asset.Financing.revolver_facility_start_date if Asset.Financing.revolver_facility_start_date else [None] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_revolver_facility_start_date
        ))
        
        w_asset_revolver_duration = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.revolver_facility_period if Asset.Financing.revolver_facility_period else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_revolver_facility_duration
        ), errors='coerce').astype(float)
        
        # Vectorized end date calculation
        w_asset_revolver_end_date = pd.Series([
            start_date + pd.DateOffset(years=int(duration)) - pd.Timedelta(days=1) if pd.notna(start_date) and pd.notna(duration) else pd.NaT
            for start_date, duration in zip(w_asset_revolver_start_date, w_asset_revolver_duration)
        ], dtype='datetime64[ns]')

        # Asset Debt Revolver Withdrawal Flag (fully vectorized with broadcasting)
        _period_starts_dt = pd.to_datetime(_period_starts).values
        _period_ends_dt = pd.to_datetime(_period_ends).values
        
        # Reshape for broadcasting: (n_assets, 1) vs (n_periods,)
        _start_dates_bcast = w_asset_revolver_start_date.values[:, np.newaxis]
        _end_dates_bcast = w_asset_revolver_end_date.values[:, np.newaxis]
        
        # Vectorized overlap check
        _overlap_mask = (_period_starts_dt <= _end_dates_bcast) & (_period_ends_dt >= _start_dates_bcast)
        _valid_dates = pd.notna(w_asset_revolver_start_date.values) & pd.notna(w_asset_revolver_end_date.values)
        _overlap_mask = _overlap_mask & _valid_dates[:, np.newaxis]
        
        w_asset_revolver_withdrawal_flag = pd.DataFrame(
            _overlap_mask.astype(float),
            index=template_asset_timeline.index,
            columns=template_asset_timeline.columns
        )

        # ============================================================================================
        # BASE RATE AND CREDIT SPREAD PROFILE CALCULATION
        # ============================================================================================
        
        w_asset_revolver_base_rate_profile = np.where(
            _override_mask,
            Asset.Financing.base_rate_profile_revolver if Asset.Financing.base_rate_profile_revolver else [''] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_base_rate_pa or ''
        )
        
        # Credit spread is a direct annual % (not a profile name)
        w_asset_revolver_credit_spread_pct = pd.to_numeric(pd.Series(np.where(
            _override_mask,
            Asset.Financing.credit_spread_percent_revolver if Asset.Financing.credit_spread_percent_revolver else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_credit_spread_pa or 0
        )), errors='coerce').fillna(0).values.astype(float)
        
        # Fetch interest profile data
        _interest_profile_names = fn_get_named_range_value(assumptions, "a.devco.interest.profile.name", [])
        _interest_profile_data = fn_get_named_range_value(assumptions, "a.devco.interest.profile", [])
        
        # Pre-compute year-to-index mapping
        _unique_years = sorted(list(set([pd.Timestamp(d).year for d in _period_starts])))
        _year_to_idx = {y: i for i, y in enumerate(_unique_years)}
        _period_years = [pd.Timestamp(d).year for d in _period_starts]
        _period_year_indices = np.array([_year_to_idx[y] for y in _period_years])
        
        # Build profile name to index lookup
        _interest_profile_name_to_idx = {name: idx for idx, name in enumerate(_interest_profile_names)} if _interest_profile_names else {}
        
        # Initialize base rate percent array (fully vectorized)
        _base_rate_percent_arr = np.zeros((_n_assets, _n_periods))
        _credit_spread_percent_arr = np.zeros((_n_assets, _n_periods))
        
        # Vectorized interest rate calculation
        # Pre-compute all profile data into a 2D array for efficient lookup
        if _interest_profile_data and len(_interest_profile_data) > 0:
            # Build interest rates matrix for all profiles
            max_years = len(_unique_years)
            _profile_rates_matrix = np.zeros((len(_interest_profile_data), max_years))
            for p_idx, profile_data in enumerate(_interest_profile_data):
                # Handle empty strings and None values by converting to 0
                cleaned_data = [float(v) if v is not None and v != '' and pd.notna(v) else 0.0 for v in profile_data]
                profile_arr = np.array(cleaned_data, dtype=float)
                _profile_rates_matrix[p_idx, :len(profile_arr)] = profile_arr[:max_years] if len(profile_arr) >= max_years else np.pad(profile_arr, (0, max_years - len(profile_arr)), 'edge')
            
            # Vectorized base rate calculation (from profiles)
            for row_idx in range(_n_assets):
                profile_name = w_asset_revolver_base_rate_profile[row_idx]
                if profile_name and pd.notna(profile_name) and profile_name != '' and profile_name in _interest_profile_name_to_idx:
                    profile_idx = _interest_profile_name_to_idx[profile_name]
                    rates_by_period = _profile_rates_matrix[profile_idx, _period_year_indices]
                    _base_rate_percent_arr[row_idx, :] = ((1 + rates_by_period) ** (1/12)) - 1
        
        # Credit spread: direct annual % converted to monthly (independent of profiles)
        for row_idx in range(_n_assets):
            _credit_spread_percent_arr[row_idx, :] = ((1 + w_asset_revolver_credit_spread_pct[row_idx]) ** (1/12)) - 1
        
        w_asset_revolver_base_rate_percent = pd.DataFrame(
            _base_rate_percent_arr,
            index=template_asset_timeline.index,
            columns=template_asset_timeline.columns
        )
        
        w_asset_revolver_credit_spread = pd.DataFrame(
            _credit_spread_percent_arr,
            index=template_asset_timeline.index,
            columns=template_asset_timeline.columns
        )
        
        # Net Interest Rate = Base Rate + Credit Spread
        w_asset_revolver_net_interest_rate = w_asset_revolver_base_rate_percent + w_asset_revolver_credit_spread

        # ============================================================================================
        # ASSET TERM LOAN - PARAMETERS (VECTORIZED with override)
        # ============================================================================================
        # Hierarchy: Term Loan drawn first â†’ Revolver covers shortfall â†’ Equity injection
        # Term Loan interest capitalized during grace period, expensed during repayment.
        # ============================================================================================
        
        # --- Term Loan Start Date (= drawdown date) ---
        w_asset_tl_start_date = pd.to_datetime(np.where(
            _override_mask,
            Asset.Financing.term_loan_facility_start_date if Asset.Financing.term_loan_facility_start_date else [None] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_debt_drawdown_date
        ))
        
        # --- Term Loan Grace Period (months) ---
        _asset_tl_grace_period = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.term_loan_grace_period if Asset.Financing.term_loan_grace_period else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_grace_period
        ), errors='coerce').astype(float)
        
        # --- Term Loan Tenure (years â†’ months) ---
        _asset_tl_tenure_years = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.term_loan_facility_period if Asset.Financing.term_loan_facility_period else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_loan_term
        ), errors='coerce').astype(float)
        _asset_tl_tenure_months = _asset_tl_tenure_years * 12
        _asset_tl_tenure_excl_grace = _asset_tl_tenure_months - _asset_tl_grace_period
        
        # --- Term Loan Amount Calculation ---
        _asset_tl_calc_approach = np.where(
            _override_mask,
            Asset.Financing.term_loan_amount_approach if Asset.Financing.term_loan_amount_approach else [''] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_term_loan_amount_calculation_approach or ''
        )
        
        _asset_tl_ad_hoc = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.term_loan_ad_hoc_amount if Asset.Financing.term_loan_ad_hoc_amount else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_loan_amount_as_ad_hoc_amount or 0
        ), errors='coerce').astype(float)
        
        _asset_tl_pct_dev = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.percent_of_development_cost if Asset.Financing.percent_of_development_cost else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_loan_amount_percent_of_dev_cost or 0
        ), errors='coerce').astype(float)
        
        # Per-asset development cost for % approach  (acquisition + vertical construction + soft costs)
        _asset_dev_cost = (
            o_vertical_construction_cost.sum(axis=1).values +
            o_total_soft_cost.sum(axis=1).values
        )
        
        _asset_tl_amount = np.where(
            np.char.strip(np.array(_asset_tl_calc_approach, dtype=str)) == "% of Development Cost",
            _asset_tl_pct_dev * _asset_dev_cost,
            np.where(
                np.char.strip(np.array(_asset_tl_calc_approach, dtype=str)) == "Ad-Hoc Amount",
                _asset_tl_ad_hoc,
                0.0
            )
        )

        # --- Term Loan Balloon & Fees ---
        _asset_tl_balloon_pct = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.balloon_payment if Asset.Financing.balloon_payment else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_baloon_payment or 0
        ), errors='coerce').astype(float)
        _asset_tl_balloon_amt = _asset_tl_amount * _asset_tl_balloon_pct
        
        _asset_tl_arr_fees_pct = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.ftl_debt_arrangement_fees if Asset.Financing.ftl_debt_arrangement_fees else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_debt_arrangement_fees or 0
        ), errors='coerce').astype(float)
        _asset_tl_arr_fees_amt = _asset_tl_amount * _asset_tl_arr_fees_pct * _is_asset_financing
        
        _asset_tl_amort_pct = pd.to_numeric(np.where(
            _override_mask,
            Asset.Financing.amortization_percent if Asset.Financing.amortization_percent else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_amotized_loan_amount or 0
        ), errors='coerce').astype(float)
        
        # --- Term Loan Interest Rates (per-asset, from profiles with override) ---
        _asset_tl_base_rate_profile = np.where(
            _override_mask,
            Asset.Financing.base_rate_profile_term_loan if Asset.Financing.base_rate_profile_term_loan else [''] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_base_rate_pa or ''
        )
        # Credit spread is a direct annual % (not a profile name)
        _asset_tl_spread_pct = pd.to_numeric(pd.Series(np.where(
            _override_mask,
            Asset.Financing.credit_spread_percent_term_loan if Asset.Financing.credit_spread_percent_term_loan else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.term_loan_assumptions_credit_spread_pa or 0
        )), errors='coerce').fillna(0).values.astype(float)
        
        _asset_tl_base_rate_arr = np.zeros((_n_assets, _n_periods))
        _asset_tl_spread_arr = np.zeros((_n_assets, _n_periods))
        
        if _interest_profile_data and len(_interest_profile_data) > 0:
            for row_idx in range(_n_assets):
                br_name = _asset_tl_base_rate_profile[row_idx]
                if br_name and pd.notna(br_name) and br_name != '' and br_name in _interest_profile_name_to_idx:
                    pidx = _interest_profile_name_to_idx[br_name]
                    rates = _profile_rates_matrix[pidx, _period_year_indices]
                    _asset_tl_base_rate_arr[row_idx, :] = ((1 + rates) ** (1/12)) - 1
        
        # Credit spread: direct annual % converted to monthly (independent of profiles)
        for row_idx in range(_n_assets):
            _asset_tl_spread_arr[row_idx, :] = ((1 + _asset_tl_spread_pct[row_idx]) ** (1/12)) - 1
        
        _asset_tl_net_rate = _asset_tl_base_rate_arr + _asset_tl_spread_arr
        
        # --- Term Loan Flags (per-asset, vectorized with broadcasting) ---
        _period_starts_arr = pd.to_datetime(_period_starts).values
        _period_ends_arr = pd.to_datetime(_period_ends).normalize().values
        
        # Drawdown flag: period_start == drawdown_date
        _asset_tl_drawdown_flag = np.zeros((_n_assets, _n_periods))
        for i in range(_n_assets):
            if pd.notna(w_asset_tl_start_date[i]):
                _asset_tl_drawdown_flag[i, :] = (_period_starts_arr == w_asset_tl_start_date[i]).astype(float)
        
        # Repayment start/end dates per asset
        _asset_tl_repay_start = pd.Series([
            w_asset_tl_start_date[i] + pd.DateOffset(months=int(_asset_tl_grace_period[i]))
            if pd.notna(w_asset_tl_start_date[i]) and pd.notna(_asset_tl_grace_period[i]) else pd.NaT
            for i in range(_n_assets)
        ])
        _asset_tl_repay_end = pd.Series([
            w_asset_tl_start_date[i] + pd.DateOffset(months=int(_asset_tl_tenure_months[i])) - pd.Timedelta(days=1)
            if pd.notna(w_asset_tl_start_date[i]) and pd.notna(_asset_tl_tenure_months[i]) else pd.NaT
            for i in range(_n_assets)
        ])
        
        # Repayment flag: periods that fall within repayment window
        _asset_tl_repay_flag = np.zeros((_n_assets, _n_periods))
        _asset_tl_balloon_flag = np.zeros((_n_assets, _n_periods))
        for i in range(_n_assets):
            if pd.notna(_asset_tl_repay_start[i]) and pd.notna(_asset_tl_repay_end[i]):
                _asset_tl_repay_flag[i, :] = (
                    (_period_starts_arr < _asset_tl_repay_end[i].to_numpy()) &
                    (_period_ends_arr > _asset_tl_repay_start[i].to_numpy())
                ).astype(float)
                _asset_tl_repay_end_norm = _asset_tl_repay_end[i].normalize().to_numpy()
                _asset_tl_balloon_flag[i, :] = (_period_ends_arr == _asset_tl_repay_end_norm).astype(float)
        
        # Number of repayment periods per asset (monthly frequency)
        _asset_tl_n_payments = np.maximum(_asset_tl_tenure_excl_grace, 1.0)

        # ============================================================================================
        # REVOLVER PARAMETERS (VECTORIZED)
        # ============================================================================================
        
        # Revolver limit
        _revolver_limit = np.where(
            _override_mask,
            Asset.Financing.revolver_limit if Asset.Financing.revolver_limit else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_revolver_limit
        ).astype(float)
        
        # Arrangement fees
        _arrangement_fees_percent = np.where(
            _override_mask,
            Asset.Financing.revolver_debt_arrangement_fees if Asset.Financing.revolver_debt_arrangement_fees else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_debt_arrangement_fees
        ).astype(float)
        
        # Commitment fees
        _commitment_fees_percent = np.where(
            _override_mask,
            Asset.Financing.revolver_commitment_fees if Asset.Financing.revolver_commitment_fees else [0] * _n_assets,
            Global.AssetLevelFundingAssumptions.asset_debt_revolver_assumptions_commitment_fees
        ).astype(float)
        _commitment_fees_monthly = _commitment_fees_percent / 12

        # ============================================================================================
        # ASSET LEVEL FINANCING WORKINGS â€” TERM LOAN â†’ REVOLVER â†’ EQUITY
        # ============================================================================================
        # Financing hierarchy per asset (for "Asset Financing" assets):
        #   1. Term Loan is drawn first (lump sum at drawdown date)
        #   2. Shortfall after term loan goes to Revolver
        #   3. Any remaining shortfall is covered by Equity Injection
        # "Project Financing" assets skip asset-level financing entirely.
        # ============================================================================================
        
        # --- Initialize Asset Term Loan arrays ---
        _atl_open = np.zeros((_n_assets, _n_periods))
        _atl_drawdown = np.zeros((_n_assets, _n_periods))
        _atl_cap_int = np.zeros((_n_assets, _n_periods))
        _atl_principal = np.zeros((_n_assets, _n_periods))
        _atl_balloon = np.zeros((_n_assets, _n_periods))
        _atl_int_exp = np.zeros((_n_assets, _n_periods))
        _atl_close = np.zeros((_n_assets, _n_periods))
        _atl_arr_fees = np.zeros((_n_assets, _n_periods))
        _atl_cap_int_flag = np.zeros((_n_assets, _n_periods))
        
        
        # --- Initialize Asset Revolver arrays ---
        w_asset_debt_revolver_opening_balance = _create_zero_df()
        w_asset_debt_revolver_debt_withdrawal = _create_zero_df()
        w_asset_debt_revolver_capitalization_of_interest = _create_zero_df()
        w_asset_debt_revolver_debt_repayment = _create_zero_df()
        w_asset_debt_revolver_closing_balance = _create_zero_df()
        w_asset_debt_revolver_debt_arrangement_fees = _create_zero_df()
        w_asset_debt_revolver_debt_arrangement_fees_capitalized = _create_zero_df()
        w_asset_debt_revolver_debt_commitment_fees = _create_zero_df()
        w_asset_debt_revolver_debt_commitment_fees_capitalized = _create_zero_df()
        w_asset_debt_revolver_interest_expense = _create_zero_df()
        _opening_cash_balance = np.zeros((_n_assets, _n_periods))
        _net_cash = np.zeros((_n_assets, _n_periods))
        _closing_cash_balance = np.zeros((_n_assets, _n_periods))
        
        # --- Initialize Asset Equity Injection array ---
        _asset_equity_injection = np.zeros((_n_assets, _n_periods))

        # Extract numpy arrays for fast access
        _pre_fin_cf = w_pre_financing_cashflows_jv_excluded.values
        _withdrawal_flag = w_asset_revolver_withdrawal_flag.values
        _net_interest = w_asset_revolver_net_interest_rate.values
        
        # Apply funding_type mask: zero out asset-level financing for "Project Financing" assets
        _revolver_limit = _revolver_limit * _is_asset_financing
        _withdrawal_flag = _withdrawal_flag * _is_asset_financing[:, np.newaxis]
        _asset_tl_amount_masked = _asset_tl_amount * _is_asset_financing
        
        _opening_bal = w_asset_debt_revolver_opening_balance.values
        _debt_withdrawal = w_asset_debt_revolver_debt_withdrawal.values
        _cap_interest = w_asset_debt_revolver_capitalization_of_interest.values
        _exp_interest = w_asset_debt_revolver_interest_expense.values

        _debt_repayment = w_asset_debt_revolver_debt_repayment.values
        _closing_bal = w_asset_debt_revolver_closing_balance.values
        _arr_fees = w_asset_debt_revolver_debt_arrangement_fees.values
        _arr_fees_cap = w_asset_debt_revolver_debt_arrangement_fees_capitalized.values
        _commit_fees = w_asset_debt_revolver_debt_commitment_fees.values
        _commit_fees_cap = w_asset_debt_revolver_debt_commitment_fees_capitalized.values
        
        # Pre-compute per-asset cumulative amortization counters
        _asset_cumul_amort = np.zeros(_n_assets)
        
        # Vectorized pre-computations for term loan
        _atl_drawdown = _asset_tl_amount_masked[:, np.newaxis] * _asset_tl_drawdown_flag
        _atl_balloon = -_asset_tl_balloon_amt[:, np.newaxis] * _asset_tl_balloon_flag * _is_asset_financing[:, np.newaxis]
        _atl_arr_fees = _asset_tl_arr_fees_amt[:, np.newaxis] * _asset_tl_drawdown_flag if Global.AssetLevelFundingAssumptions.term_loan_assumptions_debt_arrangement_fees_capitalization == "No" else np.zeros((_n_assets, _n_periods))
        _atl_arr_fees_cap = _asset_tl_arr_fees_amt[:, np.newaxis] * _asset_tl_drawdown_flag if Global.AssetLevelFundingAssumptions.term_loan_assumptions_debt_arrangement_fees_capitalization == "Yes" else np.zeros((_n_assets, _n_periods))

        # Capitalization flags (1 during grace period, 0 during repayment, for assets with term loan)
        _atl_cap_int_flag = (1 - _asset_tl_repay_flag) if Global.AssetLevelFundingAssumptions.term_loan_assumptions_term_loan_interest_capitalization == "Yes" else np.zeros((_n_assets, _n_periods))
        
        # Revolver arrangement fees (at revolver start)
        _start_dates_arr = w_asset_revolver_start_date.values
        _end_dates_arr = w_asset_revolver_end_date.values
        
        # Column-by-column iteration with row-vectorized operations
        for col in range(_n_periods):
            period_start = _period_starts_arr[col]
            period_end = _period_ends_arr[col]
            
            # Opening cash balance: for "Asset Financing" assets, it's the closing cash balance from previous period; for "Project Financing" assets, it's always 0 (as they skip asset-level financing)
            _opening_cash_balance[:, col] = np.where(_is_asset_financing, _closing_cash_balance[:, col - 1], 0.0) if col > 0 else 0.0
            
            # === ASSET TERM LOAN ===
            # Opening balance
            if col > 0:
                _atl_open[:, col] = _atl_close[:, col - 1]
            
            # Interest Capitalization (during grace period, i.e. NOT in repayment period)
            _atl_cap_int[:, col] = ((_atl_open[:, col] + _atl_drawdown[:, col]) * _asset_tl_net_rate[:, col] * _atl_cap_int_flag[:, col]) + (_atl_arr_fees_cap[:, col])
            
            # Principal Repayment (PPMT-based, during repayment period)
            for i in range(_n_assets):
                if _asset_tl_repay_flag[i, col] == 1 and _asset_tl_n_payments[i] > 0:
                    _nper_rem = _asset_tl_n_payments[i] - _asset_cumul_amort[i]
                    
                    _pv = _atl_open[i, col] + _atl_drawdown[i, col] + _atl_cap_int[i, col] + _atl_balloon[i, :].sum()
                    try:
                        _ppmt_v = _ppmt(_asset_tl_net_rate[i, col], 1, _nper_rem, _pv) if _nper_rem > 0 and _pv != 0 else 0.0
                    except Exception:
                        _ppmt_v = 0.0
                    _atl_principal[i, col] = _ppmt_v * _asset_tl_repay_flag[i, col]
                    _asset_cumul_amort[i] += 1
            
            # Interest Expensed (during repayment period)
            _atl_int_exp[:, col] = (_atl_open[:, col] + _atl_drawdown[:, col]) * _asset_tl_net_rate[:, col] * (1 - _atl_cap_int_flag[:, col])
            
            # Closing balance
            _atl_close[:, col] = (_atl_open[:, col] + _atl_drawdown[:, col] + _atl_cap_int[:, col] +
                                  _atl_principal[:, col] + _atl_balloon[:, col])
            
            # === ASSET TERM LOAN â†’ NET REQUIREMENT FOR REVOLVER ===
            # Net cashflow after term loan for this period
            _prev_rev_close = np.zeros(_n_assets) if col == 0 else _closing_bal[:, col - 1]
            
            _net_after_tl = (
                _opening_cash_balance[:, col] +
                _pre_fin_cf[:, col] +
                _atl_drawdown[:, col] + _atl_principal[:, col] + _atl_balloon[:, col] -
                _atl_int_exp[:, col] - _atl_arr_fees[:, col]
            )
            _net_req_for_revolver = np.minimum(_net_after_tl, 0.0)
            _net_avail_for_revolver = np.maximum(_net_after_tl, 0.0)
            
            # === ASSET REVOLVER ===
            # Opening balance
            _opening_bal[:, col] = _prev_rev_close
            
            # Drawdown: covers shortfall post term-loan, capped by available limit
            _shortfall = -_net_req_for_revolver  # positive amount needed
            _available_limit = np.maximum(_revolver_limit - _opening_bal[:, col], 0.0)
            _debt_withdrawal[:, col] = (np.minimum(_shortfall, _available_limit)) * _withdrawal_flag[:, col]
            
            # -------------------------------------------------------------------
            # Capitalization Flag
            # -------------------------------------------------------------------
            _int_capitalize_flag = (
                Global.AssetLevelFundingAssumptions
                .asset_debt_revolver_assumptions_interest_and_fees_capitalization
                == "Yes"
            )

            # -------------------------------------------------------------------
            # Arrangement Fees (at revolver start)
            # -------------------------------------------------------------------
            _is_start_period = (period_start == _start_dates_arr)

            _arr_fee_amount = (
                np.where(
                    _is_start_period,
                    _arrangement_fees_percent * _revolver_limit,
                    0.0
                ) * _is_asset_financing
            )

            if _int_capitalize_flag:
                _arr_fees[:, col] = 0.0
                _arr_fees_cap[:, col] = _arr_fee_amount
            else:
                _arr_fees[:, col] = _arr_fee_amount

            # -------------------------------------------------------------------
            # Commitment Fees
            # -------------------------------------------------------------------
            _unused_limit = _revolver_limit - _opening_bal[:, col] - _debt_withdrawal[:, col]

            _commit_fee_amount = (
                _commitment_fees_monthly
                * np.maximum(_unused_limit, 0.0)
                * _withdrawal_flag[:, col]
            )

            if _int_capitalize_flag:
                _commit_fees[:, col] = 0.0
                _commit_fees_cap[:, col] = _commit_fee_amount
            else:
                _commit_fees[:, col] = _commit_fee_amount

            # -------------------------------------------------------------------
            # Interest
            # -------------------------------------------------------------------
            _interest_amount = (
                (_opening_bal[:, col] + _debt_withdrawal[:, col])
                * _net_interest[:, col]
            )

            if _int_capitalize_flag:
                _cap_interest[:, col] = _interest_amount
                _exp_interest[:, col] = 0.0
            else:
                _cap_interest[:, col] = 0.0
                _exp_interest[:, col] = _interest_amount

            # -------------------------------------------------------------------
            # Repayment Base Calculation
            # -------------------------------------------------------------------
            _temp_val = (
                _opening_bal[:, col]
                + _debt_withdrawal[:, col]
                + _cap_interest[:, col]
                + (_arr_fees_cap[:, col] if _int_capitalize_flag else 0.0)
                + (_commit_fees_cap[:, col] if _int_capitalize_flag else 0.0)
            )

            _is_end_period = (period_end == _end_dates_arr)

            _debt_repayment[:, col] = -np.where(
                _is_end_period,
                _temp_val,
                np.maximum(
                    0.0,
                    np.minimum(
                        _net_avail_for_revolver
                        + np.maximum(0.0, _temp_val - _revolver_limit),
                        _temp_val
                    )
                )
            )

            # -------------------------------------------------------------------
            # Closing Balance
            # -------------------------------------------------------------------
            _closing_bal[:, col] = (
                _opening_bal[:, col]
                + _debt_withdrawal[:, col]
                + _cap_interest[:, col]
                + (_arr_fees_cap[:, col] if _int_capitalize_flag else 0.0)
                + (_commit_fees_cap[:, col] if _int_capitalize_flag else 0.0)
                + _debt_repayment[:, col]
            )
            
            # === EQUITY INJECTION (after revolver) ===
            _net_after_revolver = (
                _net_after_tl +
                _debt_withdrawal[:, col] + _debt_repayment[:, col] - 
                _exp_interest[:, col] - _arr_fees[:, col] - _commit_fees[:, col]
            )
            _asset_equity_injection[:, col] = -np.minimum(_net_after_revolver, 0.0) * _is_asset_financing

            _net_cash[:, col] = (_net_after_revolver + _asset_equity_injection[:, col] - _opening_cash_balance[:, col])

            _closing_cash_balance[:, col] = np.where(_is_asset_financing, _opening_cash_balance[:, col] + _net_cash[:, col], 0.0)
        
        # Assign computed values back to DataFrames
        w_asset_debt_revolver_opening_balance = pd.DataFrame(
            _opening_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_debt_withdrawal = pd.DataFrame(
            _debt_withdrawal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_capitalization_of_interest = pd.DataFrame(
            _cap_interest, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_debt_repayment = pd.DataFrame(
            _debt_repayment, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_closing_balance = pd.DataFrame(
            _closing_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_debt_arrangement_fees = pd.DataFrame(
            _arr_fees, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_debt_revolver_debt_commitment_fees = pd.DataFrame(
            _commit_fees, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        
        # Asset Term Loan DataFrames
        o_asset_term_loan_opening_balance = pd.DataFrame(
            _atl_open, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_drawdown = pd.DataFrame(
            _atl_drawdown, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_cap_interest = pd.DataFrame(
            _atl_cap_int, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_principal = pd.DataFrame(
            _atl_principal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_balloon = pd.DataFrame(
            _atl_balloon, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_interest_expensed = pd.DataFrame(
            _atl_int_exp, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_closing_balance = pd.DataFrame(
            _atl_close, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_term_loan_arrangement_fees = pd.DataFrame(
            _atl_arr_fees, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        o_asset_equity_injection = pd.DataFrame(
            _asset_equity_injection, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        
        # Backward compatibility
        o_asset_term_loan_interest = o_asset_term_loan_interest_expensed
        o_asset_term_loan_repayment = pd.DataFrame(
            _atl_principal + _atl_balloon, index=template_asset_timeline.index, columns=template_asset_timeline.columns
        )
        w_asset_loan_balance = o_asset_term_loan_closing_balance

        # ============================================================================================
        # EXPORT ASSET LEVEL FINANCING DATAFRAMES TO EXCEL
        # ============================================================================================
        
        if _EXPORT_FLAGS.get('asset_level_financing', False):
            _idx = template_asset_timeline.index
            _cols = template_asset_timeline.columns
            _asset_financing_exports = {
                # â”€â”€ 1. CONFIGURATION & FLAGS â”€â”€
                'w_01A_Funding_Type': pd.DataFrame({'Funding_Type': _funding_type_raw}),
                'w_01B_Funding_Type': pd.DataFrame({'Funding_Type_Updated': _funding_type_updated}),
                'w_02_Is_Asset_Financing': pd.DataFrame({'Is_Asset_Financing': _is_asset_financing}),
                'w_03_Override_Mask': pd.DataFrame({'Override': _override_mask}),
                # â”€â”€ 2. PRE-FINANCING CASHFLOWS â”€â”€
                'w_04_Pre_Financing_CF': w_pre_financing_cashflows_jv_excluded,
                # â”€â”€ 3. ASSET TERM LOAN â€” INPUTS â”€â”€
                'w_05_ATL_Start_Date': pd.DataFrame({'Start_Date': w_asset_tl_start_date}),
                'w_06_ATL_Grace_Period': pd.DataFrame({'Grace_Months': _asset_tl_grace_period}),
                'w_07_ATL_Tenure_Months': pd.DataFrame({'Tenure_Months': _asset_tl_tenure_months}),
                'w_08_ATL_Tenure_Excl_Grace': pd.DataFrame({'Tenure_Excl_Grace': _asset_tl_tenure_excl_grace}),
                'w_09_ATL_N_Payments': pd.DataFrame({'N_Payments': _asset_tl_n_payments}),
                'w_10_ATL_Amount': pd.DataFrame({'Amount': _asset_tl_amount}),
                'w_11_ATL_Amount_Masked': pd.DataFrame({'Amount_Masked': _asset_tl_amount_masked}),
                'w_12_ATL_Balloon_Pct': pd.DataFrame({'Balloon_Pct': _asset_tl_balloon_pct}),
                'w_13_ATL_Balloon_Amt': pd.DataFrame({'Balloon_Amt': _asset_tl_balloon_amt}),
                'w_14_ATL_Arr_Fees_Pct': pd.DataFrame({'Arr_Fees_Pct': _asset_tl_arr_fees_pct}),
                'w_15_ATL_Arr_Fees_Amt': pd.DataFrame({'Arr_Fees_Amt': _asset_tl_arr_fees_amt}),
                'w_16_ATL_Amort_Pct': pd.DataFrame({'Amort_Pct': _asset_tl_amort_pct}),
                # â”€â”€ 4. ASSET TERM LOAN â€” INTEREST RATES â”€â”€
                'w_17_ATL_Base_Rate': pd.DataFrame(_asset_tl_base_rate_arr, index=_idx, columns=_cols),
                'w_18_ATL_Credit_Spread': pd.DataFrame(_asset_tl_spread_arr, index=_idx, columns=_cols),
                'w_19_ATL_Net_Rate': pd.DataFrame(_asset_tl_net_rate, index=_idx, columns=_cols),
                # â”€â”€ 5. ASSET TERM LOAN â€” FLAGS â”€â”€
                'w_20_ATL_Drawdown_Flag': pd.DataFrame(_asset_tl_drawdown_flag, index=_idx, columns=_cols),
                'w_21_ATL_Repay_Flag': pd.DataFrame(_asset_tl_repay_flag, index=_idx, columns=_cols),
                'w_22_ATL_Balloon_Flag': pd.DataFrame(_asset_tl_balloon_flag, index=_idx, columns=_cols),
                # â”€â”€ 6. ASSET TERM LOAN â€” SCHEDULE (OUTPUT) â”€â”€
                'o_23_ATL_Opening_Bal': o_asset_term_loan_opening_balance,
                'o_24_ATL_Drawdown': o_asset_term_loan_drawdown,
                'o_25_ATL_Cap_Interest': o_asset_term_loan_cap_interest,
                'o_26_ATL_Principal': o_asset_term_loan_principal,
                'o_27_ATL_Balloon': o_asset_term_loan_balloon,
                'o_28_ATL_Int_Expensed': o_asset_term_loan_interest_expensed,
                'o_29_ATL_Closing_Bal': o_asset_term_loan_closing_balance,
                'o_30_ATL_Arr_Fees': o_asset_term_loan_arrangement_fees,
                # â”€â”€ 7. ASSET REVOLVER â€” INPUTS â”€â”€
                'w_31_Rev_Start_Date': pd.DataFrame({'Start_Date': w_asset_revolver_start_date}),
                'w_32_Rev_Duration': pd.DataFrame({'Duration_Years': w_asset_revolver_duration}),
                'w_33_Rev_End_Date': pd.DataFrame({'End_Date': w_asset_revolver_end_date}),
                'w_34_Rev_Limit': pd.DataFrame({'Limit': _revolver_limit}),
                # â”€â”€ 8. ASSET REVOLVER â€” INTEREST RATES â”€â”€
                'w_35_Rev_Base_Rate': w_asset_revolver_base_rate_percent,
                'w_36_Rev_Credit_Spread': w_asset_revolver_credit_spread,
                'w_37_Rev_Net_Rate': w_asset_revolver_net_interest_rate,
                # â”€â”€ 9. ASSET REVOLVER â€” FLAGS â”€â”€
                'w_38_Rev_Withdrawal_Flag': w_asset_revolver_withdrawal_flag,
                # â”€â”€ 10. ASSET REVOLVER â€” SCHEDULE (OUTPUT) â”€â”€
                'o_39_Rev_Opening_Bal': w_asset_debt_revolver_opening_balance,
                'o_40_Rev_Withdrawal': w_asset_debt_revolver_debt_withdrawal,
                'o_41_Rev_Cap_Interest': w_asset_debt_revolver_capitalization_of_interest,
                'o_42_Rev_Repayment': w_asset_debt_revolver_debt_repayment,
                'o_43_Rev_Closing_Bal': w_asset_debt_revolver_closing_balance,
                'o_44_Rev_Arr_Fees': w_asset_debt_revolver_debt_arrangement_fees,
                'o_45_Rev_Commit_Fees': w_asset_debt_revolver_debt_commitment_fees,
                'o_46_Rev_Int_Expensed': w_asset_debt_revolver_interest_expense,
                # â”€â”€ 11. ASSET CASH BALANCE â”€â”€
                'o_47_Opening_Cash_Bal': pd.DataFrame(_opening_cash_balance, index=_idx, columns=_cols),
                'o_48_Net_Cash': pd.DataFrame(_net_cash, index=_idx, columns=_cols),
                'o_49_Closing_Cash_Bal': pd.DataFrame(_closing_cash_balance, index=_idx, columns=_cols),
                # â”€â”€ 12. ASSET EQUITY INJECTION (OUTPUT) â”€â”€
                'o_50_Equity_Injection': o_asset_equity_injection,
            }
            _export_to_excel(_asset_financing_exports, 'devco_asset_financing', 'Asset Level Financing')

        # ========================================================================
        # SUB-MODULE 3.14.2: PROJECT LEVEL FINANCING
        # ========================================================================
        # Financing hierarchy (aligned with LandCo project-level approach):
        #   1. Project Term Loan drawn first (lump sum at drawdown date)
        #   2. Shortfall after term loan â†’ Project Revolver
        #   3. Any remaining shortfall â†’ Equity Injection
        # 
        # Term Loan: Interest capitalized during grace period, PPMT-based
        #            principal repayment after grace, balloon at maturity.
        # Revolver:  Capitalized interest, repay when surplus available,
        #            full repay at facility end, commitment fee accrual cycle.
        # No transfer mechanism or asset cash reserve at project level.
        # ========================================================================
        
        _record_timing("Asset level financing calculated")

        # ========================================================================
        # PROJECT TERM LOAN - FLAGS AND PARAMETERS
        # ========================================================================
        
        _term_loan_drawdown_date = pd.to_datetime(Global.ProjectLevelFundingAssumptions.term_loan_assumptions_debt_drawdown_date)
        _term_loan_grace_period = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_grace_period
        _term_loan_tenure_months = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_loan_term * 12
        _term_loan_tenure_excl_grace = _term_loan_tenure_months - _term_loan_grace_period
        
        # Grace end & repayment start dates
        if pd.notna(_term_loan_drawdown_date):
            _term_loan_grace_end_date = _term_loan_drawdown_date + pd.DateOffset(months=int(_term_loan_grace_period)) - pd.Timedelta(days=1)
            _term_loan_repay_start_date = _term_loan_grace_end_date + pd.DateOffset(days=1)
            _term_loan_repay_end_date = (_term_loan_repay_start_date + pd.DateOffset(months=int(_term_loan_tenure_excl_grace)) - pd.Timedelta(days=1)).normalize()
        else:
            _term_loan_grace_end_date = pd.NaT
            _term_loan_repay_start_date = pd.NaT
            _term_loan_repay_end_date = pd.NaT
        
        # Calculate term loan amount
        _debt_calc_approach = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_term_loan_amount_calculation_approach
        _dev_cost_total = 0.0
        if _debt_calc_approach == "% of Development Cost":
            # Only project-financing assets contribute to dev cost
            _pf_mask = _is_project_financing  # boolean array (n_assets,)
            _dev_cost_total = (
                o_vertical_construction_cost.values[_pf_mask].sum() + 
                o_total_soft_cost.values[_pf_mask].sum()
            )
            _term_loan_amount = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_loan_amount_as_percentage_of_dev_cost * _dev_cost_total
        elif _debt_calc_approach == "Ad-Hoc Amount":
            _term_loan_amount = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_loan_amount_as_ad_hoc_amount
        else:
            _term_loan_amount = 0.0

        _term_loan_balloon_pct = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_baloon_payment
        _term_loan_balloon_amt = _term_loan_amount * _term_loan_balloon_pct
        _term_loan_arr_fees_pct = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_debt_arrangement_fees
        _term_loan_arr_fees_amt = _term_loan_amount * _term_loan_arr_fees_pct
        
        # Arrangement fees capitalization toggle
        _term_loan_arr_fees_cap = int(
            getattr(Global.ProjectLevelFundingAssumptions, 'term_loan_assumptions_debt_arrangement_fees_capitalization', 'No') == "Yes"
        )

        # Vectorized flag calculations
        _term_loan_drawdown_flag = (_period_starts_arr == _term_loan_drawdown_date).astype(float) if pd.notna(_term_loan_drawdown_date) else np.zeros(_n_periods)
        
        if pd.notna(_term_loan_repay_start_date) and pd.notna(_term_loan_repay_end_date):
            _term_loan_repay_flag = ((_period_starts_arr < _term_loan_repay_end_date.to_numpy()) & 
                                     (_period_ends_arr > _term_loan_repay_start_date.to_numpy())).astype(float)
            _balloon_flag = (_period_ends_arr == _term_loan_repay_end_date.to_numpy()).astype(float)
        else:
            _term_loan_repay_flag = np.zeros(_n_periods)
            _balloon_flag = np.zeros(_n_periods)
        
        # Number of repayment periods (monthly)
        _n_payments = _term_loan_tenure_excl_grace if _term_loan_tenure_excl_grace > 0 else 1

        # ========================================================================
        # PROJECT TERM LOAN - INTEREST RATE CALCULATION
        # ========================================================================
        
        _term_loan_base_rate_profile = Global.ProjectLevelFundingAssumptions.term_loan_assumptions_base_rate_pa or ''
        _term_loan_spread_annual = float(Global.ProjectLevelFundingAssumptions.term_loan_assumptions_credit_spread_pa or 0)
        
        _term_loan_base_rate = np.zeros(_n_periods)
        # Credit spread: direct annual % converted to monthly (constant across periods)
        _term_loan_spread = np.full(_n_periods, ((1 + _term_loan_spread_annual) ** (1/12)) - 1)
        
        if _term_loan_base_rate_profile and _term_loan_base_rate_profile in _interest_profile_name_to_idx:
            profile_idx = _interest_profile_name_to_idx[_term_loan_base_rate_profile]
            annual_rates = np.array(_interest_profile_data[profile_idx], dtype=float)[_period_year_indices]
            _term_loan_base_rate = ((1 + annual_rates) ** (1/12)) - 1
        
        _term_loan_net_rate = _term_loan_base_rate + _term_loan_spread

        # ========================================================================
        # PROJECT DEBT REVOLVER - FLAGS AND PARAMETERS
        # ========================================================================
        
        _proj_revolver_start = pd.to_datetime(Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_revolver_facility_start_date)
        _proj_revolver_duration = Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_revolver_facility_duration
        _proj_revolver_limit = Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_revolver_limit
        
        if pd.notna(_proj_revolver_start):
            _proj_revolver_end = _proj_revolver_start + pd.DateOffset(years=int(_proj_revolver_duration)) - pd.Timedelta(days=1)
            _proj_revolver_flag = ((_period_ends_arr > _proj_revolver_start.to_numpy()) & 
                                   (_period_starts_arr < _proj_revolver_end.to_numpy())).astype(float)
            _proj_revolver_start_flag = (_period_starts_arr == _proj_revolver_start.to_numpy()).astype(float)
            _proj_revolver_end_flag = (_period_ends_arr == _proj_revolver_end.normalize().to_numpy()).astype(float)
        else:
            _proj_revolver_flag = np.zeros(_n_periods)
            _proj_revolver_start_flag = np.zeros(_n_periods)
            _proj_revolver_end_flag = np.zeros(_n_periods)
        
        _proj_revolver_arr_fees_pct = Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_debt_arrangement_fees
        _proj_revolver_commit_fees_pct = Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_commitment_fees
        _proj_revolver_commit_fees_monthly = _proj_revolver_commit_fees_pct / 12

        # Project Revolver Interest Rate
        _proj_revolver_base_profile = Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_base_rate_pa or ''
        _proj_revolver_spread_annual = float(Global.ProjectLevelFundingAssumptions.project_debt_revolver_assumptions_credit_spread_pa or 0)
        
        _proj_revolver_base_rate = np.zeros(_n_periods)
        # Credit spread: direct annual % converted to monthly (constant across periods)
        _proj_revolver_spread = np.full(_n_periods, ((1 + _proj_revolver_spread_annual) ** (1/12)) - 1)
        
        if _proj_revolver_base_profile and _proj_revolver_base_profile in _interest_profile_name_to_idx:
            profile_idx = _interest_profile_name_to_idx[_proj_revolver_base_profile]
            annual_rates = np.array(_interest_profile_data[profile_idx], dtype=float)[_period_year_indices]
            _proj_revolver_base_rate = ((1 + annual_rates) ** (1/12)) - 1
        
        _proj_revolver_net_rate = _proj_revolver_base_rate + _proj_revolver_spread

        # ========================================================================
        # PRE-COMPUTE PROJECT LEVEL AGGREGATES
        # ========================================================================
        # Project-level financing operates independently of asset-level financing.
        # Pre-financing cashflows are aggregated across ALL assets.
        
        _project_prefinancing_cf = (
            w_pre_financing_cashflows_jv_excluded.loc[_is_project_financing].sum(axis=0).values
            if _is_project_financing.any()
            else np.zeros(_n_periods)
        )

        # Interest and fees capitalization toggle for project revolver
        _proj_revolver_cap_flag = getattr(Global.ProjectLevelFundingAssumptions, 'project_debt_revolver_assumptions_interest_and_fees_capitalization', 'No')

        # ========================================================================
        # INITIALIZE OUTPUT ARRAYS
        # ========================================================================
        
        # Term Loan arrays
        _tl_open = np.zeros(_n_periods)
        _tl_drawdown = np.zeros(_n_periods)
        _tl_cap_int_arr_fees = np.zeros(_n_periods)
        _tl_principal = np.zeros(_n_periods)
        _tl_balloon = np.zeros(_n_periods)
        _tl_int_exp = np.zeros(_n_periods)
        _tl_close = np.zeros(_n_periods)
        _tl_arr_fees = np.zeros(_n_periods)
        
        # Project Revolver arrays
        _pr_open = np.zeros(_n_periods)
        _pr_drawdown = np.zeros(_n_periods)
        _pr_cap_int = np.zeros(_n_periods)
        _pr_exp_int = np.zeros(_n_periods)
        _pr_repay = np.zeros(_n_periods)
        _pr_close = np.zeros(_n_periods)
        _pr_arr_fees = np.zeros(_n_periods)
        _pr_commit_fees = np.zeros(_n_periods)
        
        # Net requirement/availability arrays
        _net_req_post_tl = np.zeros(_n_periods)
        _net_avail_post_tl = np.zeros(_n_periods)
        _net_req_pre_equity = np.zeros(_n_periods)
        _net_avail_pre_equity = np.zeros(_n_periods)
        _equity_infusion = np.zeros(_n_periods)
        
        # Cash schedule arrays
        _cash_open = np.zeros(_n_periods)
        _cash_net = np.zeros(_n_periods)
        _cash_close = np.zeros(_n_periods)

        # ========================================================================
        # VECTORIZED CALCULATIONS (NON-SEQUENTIAL)
        # ========================================================================
        
        # Term Loan - Drawdown, Balloon, Fees (fully vectorized)
        _tl_drawdown = _term_loan_amount * _term_loan_drawdown_flag
        _tl_balloon = -_term_loan_balloon_amt * _balloon_flag
        _tl_arr_fees = _term_loan_arr_fees_amt * _term_loan_drawdown_flag * (1 - _term_loan_arr_fees_cap)
        
        # Project Revolver - Arrangement Fees (vectorized, toggle-aware)
        _pr_arr_fees = (_proj_revolver_limit * _proj_revolver_arr_fees_pct * _proj_revolver_start_flag) if _proj_revolver_cap_flag == "No" else np.zeros(_n_periods)

        # ========================================================================
        # SEQUENTIAL CALCULATIONS (COLUMN ITERATION - LandCo-aligned)
        # ========================================================================
        # Waterfall: Term Loan â†’ Revolver â†’ Equity
        # 1. Term Loan: open â†’ drawdown â†’ cap interest (grace) + arr fees cap â†’
        #    PPMT principal (repayment) â†’ balloon â†’ int expensed (repayment) â†’ close
        # 2. Net requirement post TL: pre-fin CF + TL flows + prior cash
        # 3. Revolver: drawdown from shortfall, cap/exp interest (toggle), repay from surplus,
        #    commitment fees (toggle), arrangement fees (toggle)
        # 4. Net requirement pre-equity: shortfall after revolver
        # 5. Equity: covers remaining shortfall
        # 6. Cash schedule: aggregate all flows (independent of asset-level financing)
        # ========================================================================
        
        _cumulative_amort_count = 0
        
        for col in range(_n_periods):
            # Previous period values
            _prev_tl_close = 0.0 if col == 0 else _tl_close[col - 1]
            _prev_pr_close = 0.0 if col == 0 else _pr_close[col - 1]
            _prev_cash_close = 0.0 if col == 0 else _cash_close[col - 1]
            
            # === TERM LOAN ===
            _tl_open[col] = _prev_tl_close
            
            # Interest Capitalization + Arrangement Fees (during grace period)
            _tl_cap_int_arr_fees[col] = (
                (_tl_open[col] * _term_loan_net_rate[col] * (1 - _term_loan_repay_flag[col])) +
                (_term_loan_arr_fees_amt * _term_loan_drawdown_flag[col] * _term_loan_arr_fees_cap)
            )
            
            # Principal Repayment (PPMT-based)
            _nper_remaining = _n_payments - _cumulative_amort_count
            _pv = _tl_open[col] + _tl_drawdown[col] +  _tl_cap_int_arr_fees[col] + _tl_balloon[:].sum()
            try:
                _ppmt_val = _ppmt(_term_loan_net_rate[col], 1, _nper_remaining, _pv, fv=0) if _nper_remaining > 0 and _pv != 0 else 0.0
            except Exception:
                _ppmt_val = 0.0
            _tl_principal[col] = _ppmt_val * _term_loan_repay_flag[col]
            
            if _term_loan_repay_flag[col] == 1:
                _cumulative_amort_count += 1
            
            # Interest Expensed (during repayment period)
            _tl_int_exp[col] = _tl_open[col] * _term_loan_net_rate[col] * _term_loan_repay_flag[col]
            
            # Closing Balance
            _tl_close[col] = _tl_open[col] + _tl_drawdown[col] + _tl_cap_int_arr_fees[col] + _tl_principal[col] + _tl_balloon[col]
            
            # === NET REQUIREMENT POST TERM LOAN ===
            _net_req_calc = (
                _project_prefinancing_cf[col] +
                _tl_drawdown[col] + _tl_principal[col] + _tl_balloon[col] +
                _tl_int_exp[col] * -1 - _tl_arr_fees[col] +
                _prev_cash_close
            )
            _net_req_post_tl[col] = min(0.0, _net_req_calc)
            _net_avail_post_tl[col] = max(0.0, _net_req_calc)
            
            # === PROJECT REVOLVER ===
            _pr_open[col] = _prev_pr_close
            
            # Drawdown: cover shortfall, capped by available limit (incorporating opening cash)
            _shortfall = -_net_req_post_tl[col]  # positive amount needed
            _available_limit = max(0.0, _proj_revolver_limit - _pr_open[col])
            _pr_drawdown[col] = (_prev_cash_close - min(_shortfall, _available_limit)) * _proj_revolver_flag[col]
            
            # Arrangement fees (at revolver start, expensed when cap_flag="No")
            # Note: _pr_arr_fees is pre-computed vectorized above (zero when cap_flag="Yes")
            
            # Commitment fees
            _unused_limit = _proj_revolver_limit - _pr_open[col]
            _pr_commit_fees[col] = (_proj_revolver_commit_fees_monthly * max(0.0, _unused_limit) * _proj_revolver_flag[col]) if _proj_revolver_cap_flag == "No" else 0.0
            
            # Capitalization of interest (when cap_flag="Yes") or Interest Expensed (when cap_flag="No")
            _pr_cap_int[col] = ((_pr_open[col] + _pr_drawdown[col]) * _proj_revolver_net_rate[col]) if _proj_revolver_cap_flag == "Yes" else 0.0
            _pr_exp_int[col] = ((_pr_open[col] + _pr_drawdown[col]) * _proj_revolver_net_rate[col]) if _proj_revolver_cap_flag == "No" else 0.0
            
            # Repayment
            _pr_total_before_repay = (
                _pr_open[col] + _pr_drawdown[col] + _pr_cap_int[col] +
                (_pr_arr_fees[col] if _proj_revolver_cap_flag == "Yes" else 0.0) +
                (_pr_commit_fees[col] if _proj_revolver_cap_flag == "Yes" else 0.0)
            )
            if _proj_revolver_end_flag[col] == 1:
                _pr_repay[col] = -_pr_total_before_repay
            else:
                _pr_repay[col] = -max(0.0, min(_net_avail_post_tl[col] + max(0.0, _pr_total_before_repay - _proj_revolver_limit), _pr_total_before_repay))
            
            # Closing Balance
            _pr_close[col] = _pr_open[col] + _pr_drawdown[col] + _pr_cap_int[col] + _pr_repay[col]
            
            # === NET REQUIREMENT PRE-EQUITY ===
            _net_calc_pre_equity = (
                _net_req_calc +
                _pr_drawdown[col] + _pr_repay[col] -
                _pr_exp_int[col] - _pr_arr_fees[col] - _pr_commit_fees[col]
            )
            _net_req_pre_equity[col] = min(0.0, _net_calc_pre_equity)
            _net_avail_pre_equity[col] = max(0.0, _net_calc_pre_equity)
            
            # === EQUITY INFUSION ===
            _equity_infusion[col] = -_net_req_pre_equity[col]
            
            # === CASH SCHEDULE ===
            _cash_open[col] = _prev_cash_close
            _cash_net[col] = (
                _project_prefinancing_cf[col] +
                _tl_drawdown[col] + _tl_principal[col] + _tl_balloon[col] +
                _tl_int_exp[col] * -1 - _tl_arr_fees[col] +
                _pr_drawdown[col] + _pr_repay[col] -
                _pr_exp_int[col] - _pr_arr_fees[col] - _pr_commit_fees[col] +
                _equity_infusion[col]
            )
            _cash_close[col] = _cash_open[col] + _cash_net[col]

        # ========================================================================
        # CONVERT ARRAYS TO DATAFRAMES
        # ========================================================================
        
        # Project Term Loan
        o_project_term_loan_opening_balance = pd.Series(_tl_open, index=template_asset_timeline.columns)
        o_project_term_loan_drawdown = pd.Series(_tl_drawdown, index=template_asset_timeline.columns)
        o_project_term_loan_cap_interest = pd.Series(_tl_cap_int_arr_fees, index=template_asset_timeline.columns)
        o_project_term_loan_principal = pd.Series(_tl_principal, index=template_asset_timeline.columns)
        o_project_term_loan_balloon = pd.Series(_tl_balloon, index=template_asset_timeline.columns)
        o_project_term_loan_interest_expensed = pd.Series(_tl_int_exp, index=template_asset_timeline.columns)
        o_project_term_loan_closing_balance = pd.Series(_tl_close, index=template_asset_timeline.columns)
        o_project_term_loan_arrangement_fees = pd.Series(_tl_arr_fees, index=template_asset_timeline.columns)
        
        # Project Revolver
        o_project_revolver_opening_balance = pd.Series(_pr_open, index=template_asset_timeline.columns)
        o_project_revolver_drawdown = pd.Series(_pr_drawdown, index=template_asset_timeline.columns)
        o_project_revolver_cap_interest = pd.Series(_pr_cap_int, index=template_asset_timeline.columns)
        o_project_revolver_interest_expense = pd.Series(_pr_exp_int, index=template_asset_timeline.columns)
        o_project_revolver_repayment = pd.Series(_pr_repay, index=template_asset_timeline.columns)
        o_project_revolver_closing_balance = pd.Series(_pr_close, index=template_asset_timeline.columns)
        o_project_revolver_arrangement_fees = pd.Series(_pr_arr_fees, index=template_asset_timeline.columns)
        o_project_revolver_commitment_fees = pd.Series(_pr_commit_fees, index=template_asset_timeline.columns)
        
        # Equity and Cash
        o_equity_infusion = pd.Series(_equity_infusion, index=template_asset_timeline.columns)
        o_cash_opening_balance = pd.Series(_cash_open, index=template_asset_timeline.columns)
        o_cash_net_movement = pd.Series(_cash_net, index=template_asset_timeline.columns)
        o_cash_closing_balance = pd.Series(_cash_close, index=template_asset_timeline.columns)
        
        # ========================================================================
        # EXPORT PROJECT LEVEL FINANCING (if enabled)
        # ========================================================================
        
        if _EXPORT_FLAGS.get('project_level_financing', False):
            _project_financing_exports = {
                # â”€â”€ 1. PRE-FINANCING INPUTS â”€â”€
                'w_01_PreFin_CF': pd.DataFrame({'Value': _project_prefinancing_cf}),
                # â”€â”€ 2. PROJECT TERM LOAN â€” INPUTS â”€â”€
                'w_02_TL_Drawdown_Date': pd.DataFrame({'Value': [_term_loan_drawdown_date]}),
                'w_03_TL_Grace_Period': pd.DataFrame({'Value': [_term_loan_grace_period]}),
                'w_04_TL_Grace_End_Date': pd.DataFrame({'Value': [_term_loan_grace_end_date]}),
                'w_05_TL_Repay_Start_Date': pd.DataFrame({'Value': [_term_loan_repay_start_date]}),
                'w_06_TL_Repay_End_Date': pd.DataFrame({'Value': [_term_loan_repay_end_date]}),
                'w_07_TL_Tenure_Months': pd.DataFrame({'Value': [_term_loan_tenure_months]}),
                'w_08_TL_Tenure_Excl_Grace': pd.DataFrame({'Value': [_term_loan_tenure_excl_grace]}),
                'w_09_TL_N_Payments': pd.DataFrame({'Value': [_n_payments]}),
                'w_10_TL_Dev_Cost_Total': pd.DataFrame({'Value': [_dev_cost_total if _debt_calc_approach == '% of Development Cost' else 0]}),
                'w_11_TL_Amount': pd.DataFrame({'Value': [_term_loan_amount]}),
                'w_12_TL_Balloon_Pct': pd.DataFrame({'Value': [_term_loan_balloon_pct]}),
                'w_13_TL_Balloon_Amt': pd.DataFrame({'Value': [_term_loan_balloon_amt]}),
                'w_14_TL_Arr_Fees_Pct': pd.DataFrame({'Value': [_term_loan_arr_fees_pct]}),
                'w_15_TL_Arr_Fees_Amt': pd.DataFrame({'Value': [_term_loan_arr_fees_amt]}),
                'w_16_TL_Arr_Fees_Cap': pd.DataFrame({'Value': [_term_loan_arr_fees_cap]}),
                # â”€â”€ 3. PROJECT TERM LOAN â€” INTEREST RATES â”€â”€
                'w_17_TL_Base_Rate': pd.DataFrame({'Value': _term_loan_base_rate}),
                'w_18_TL_Credit_Spread': pd.DataFrame({'Value': _term_loan_spread}),
                'w_19_TL_Net_Rate': pd.DataFrame({'Value': _term_loan_net_rate}),
                # â”€â”€ 4. PROJECT TERM LOAN â€” FLAGS â”€â”€
                'w_20_TL_Drawdown_Flag': pd.DataFrame({'Value': _term_loan_drawdown_flag}),
                'w_21_TL_Repay_Flag': pd.DataFrame({'Value': _term_loan_repay_flag}),
                'w_22_TL_Balloon_Flag': pd.DataFrame({'Value': _balloon_flag}),
                # â”€â”€ 5. PROJECT TERM LOAN â€” SCHEDULE (OUTPUT) â”€â”€
                'o_23_TL_Opening_Bal': pd.DataFrame({'Value': o_project_term_loan_opening_balance}),
                'o_24_TL_Drawdown': pd.DataFrame({'Value': o_project_term_loan_drawdown}),
                'o_25_TL_Cap_Int_ArrFees': pd.DataFrame({'Value': o_project_term_loan_cap_interest}),
                'o_26_TL_Principal': pd.DataFrame({'Value': o_project_term_loan_principal}),
                'o_27_TL_Balloon': pd.DataFrame({'Value': o_project_term_loan_balloon}),
                'o_28_TL_Int_Expensed': pd.DataFrame({'Value': o_project_term_loan_interest_expensed}),
                'o_29_TL_Closing_Bal': pd.DataFrame({'Value': o_project_term_loan_closing_balance}),
                'o_30_TL_Arr_Fees': pd.DataFrame({'Value': o_project_term_loan_arrangement_fees}),
                # â”€â”€ 6. NET REQUIREMENT POST TERM LOAN â”€â”€
                'w_31_Net_Req_Post_TL': pd.DataFrame({'Value': _net_req_post_tl}),
                'w_32_Net_Avail_Post_TL': pd.DataFrame({'Value': _net_avail_post_tl}),
                # â”€â”€ 7. PROJECT REVOLVER â€” INPUTS â”€â”€
                'w_33_Rev_Start_Date': pd.DataFrame({'Value': [_proj_revolver_start]}),
                'w_34_Rev_Duration': pd.DataFrame({'Value': [_proj_revolver_duration]}),
                'w_35_Rev_End_Date': pd.DataFrame({'Value': [_proj_revolver_end if pd.notna(_proj_revolver_start) else pd.NaT]}),
                'w_36_Rev_Limit': pd.DataFrame({'Value': [_proj_revolver_limit]}),
                'w_37_Rev_Arr_Fees_Pct': pd.DataFrame({'Value': [_proj_revolver_arr_fees_pct]}),
                'w_38_Rev_Commit_Fees_Pct': pd.DataFrame({'Value': [_proj_revolver_commit_fees_pct]}),
                'w_39_Rev_Commit_Fees_Monthly': pd.DataFrame({'Value': [_proj_revolver_commit_fees_monthly]}),
                'w_40_Rev_Cap_Flag': pd.DataFrame({'Value': [_proj_revolver_cap_flag]}),
                # â”€â”€ 8. PROJECT REVOLVER â€” INTEREST RATES â”€â”€
                'w_41_Rev_Base_Rate': pd.DataFrame({'Value': _proj_revolver_base_rate}),
                'w_42_Rev_Credit_Spread': pd.DataFrame({'Value': _proj_revolver_spread}),
                'w_43_Rev_Net_Rate': pd.DataFrame({'Value': _proj_revolver_net_rate}),
                # â”€â”€ 9. PROJECT REVOLVER â€” FLAGS â”€â”€
                'w_44_Rev_Active_Flag': pd.DataFrame({'Value': _proj_revolver_flag}),
                'w_45_Rev_Start_Flag': pd.DataFrame({'Value': _proj_revolver_start_flag}),
                'w_46_Rev_End_Flag': pd.DataFrame({'Value': _proj_revolver_end_flag}),
                # â”€â”€ 10. PROJECT REVOLVER â€” SCHEDULE (OUTPUT) â”€â”€
                'o_47_Rev_Opening_Bal': pd.DataFrame({'Value': o_project_revolver_opening_balance}),
                'o_48_Rev_Drawdown': pd.DataFrame({'Value': o_project_revolver_drawdown}),
                'o_49_Rev_Cap_Interest': pd.DataFrame({'Value': o_project_revolver_cap_interest}),
                'o_50_Rev_Int_Expensed': pd.DataFrame({'Value': o_project_revolver_interest_expense}),
                'o_51_Rev_Repayment': pd.DataFrame({'Value': o_project_revolver_repayment}),
                'o_52_Rev_Closing_Bal': pd.DataFrame({'Value': o_project_revolver_closing_balance}),
                'o_53_Rev_Arr_Fees': pd.DataFrame({'Value': o_project_revolver_arrangement_fees}),
                'o_54_Rev_Commit_Fees': pd.DataFrame({'Value': o_project_revolver_commitment_fees}),
                # â”€â”€ 11. NET REQUIREMENT PRE-EQUITY â”€â”€
                'w_55_Net_Req_Pre_Equity': pd.DataFrame({'Value': _net_req_pre_equity}),
                'w_56_Net_Avail_Pre_Equity': pd.DataFrame({'Value': _net_avail_pre_equity}),
                # â”€â”€ 12. EQUITY & CASH SCHEDULE (OUTPUT) â”€â”€
                'o_57_Equity_Infusion': pd.DataFrame({'Value': o_equity_infusion}),
                'o_58_Cash_Opening_Bal': pd.DataFrame({'Value': o_cash_opening_balance}),
                'o_59_Cash_Net_Movement': pd.DataFrame({'Value': o_cash_net_movement}),
                'o_60_Cash_Closing_Bal': pd.DataFrame({'Value': o_cash_closing_balance}),
            }
            _export_to_excel(_project_financing_exports, 'devco_project_financing', 'Project Level Financing')
        
        _record_timing("Project level financing calculated")
        
        
        # ========================================================================
        # SUB-MODULE 3.15: CASHFLOW STATEMENT GENERATION
        # ========================================================================
        # CASHFLOW STATEMENT LINE ITEMS DEFINITION
        # ========================================================================
        # Define line items for structured cashflow statements (matches Excel template)
        # Headers (first item after empty row) are totals of sub-items below until next empty row
        # ========================================================================
        
        # Define the line items for Cashflow from Operations
        # ========================================================================
        # SUB-MODULE 3.15: CASHFLOW STATEMENT GENERATION
        # ========================================================================
        # CASHFLOW STATEMENT LINE ITEMS DEFINITION
        # ========================================================================

        operations_line_items = [
            "Cash Received from Asset Sales",      # TOTAL of items below
            "Asset Sales through Escrow",
            "Asset Sales through Collection (Post-Dev)",
            "Forward Funding",
            "Forward Sales",
            "",
            "Escrow Setup Fees",                   # Single item (no sub-items)
            "",
            "Disposal Costs",                      # TOTAL of items below
            "Sales Cost",
            "Marketing Cost",
            "",
            "Associated Opex",                     # TOTAL of items below
            "DLP Insurance",
            "Void Period Opex",
            "",
            "PA Recovery",                         # Single item
            "",
            "Corporate Overhead Expenses",         # TOTAL of items below
            "Salaries",
            "IT Services",
            "Office Rent & Utilities",
            "Professional Services",
            "Marketing (COH)",
            "Sales Cost (COH)",
            "Additional Expenses",
            "",
            "Other Income",                        # TOTAL of items below
            "Government Subsidies",
            "Other Income 1",
            "Other Income 2",
            "",
            "Other Expense",                       # TOTAL of items below
            "Other Expense 1",
            "Other Expense 2",
            "Other Expense 3",
            "",
            "Net Cashflow from Operations"
        ]

        investment_line_items = [
            "Land Acquisition Cost Payment",       # Single item
            "",
            "Land Acquisition Transaction Costs",  # TOTAL of items below
            "Legal Cost",
            "Agency Cost",
            "Technical Cost",
            "Valuation Cost",
            "Due Diligence Cost",
            "",
            "Development Costs",                   # TOTAL of items below
            "Vertical Construction Cost",
            "Public Amenity Cost",
            "CEC Cost",
            "Canal Cost",
            "",
            "Soft Costs Payment",                  # TOTAL of items below
            "Design Cost",
            "Permitting Cost",
            "Supervision Cost",
            "Project Management Cost",
            "",
            "Contingency Cost Payment",            # Single item
            "",
            "Corporate Overhead Capitalized",      # TOTAL of items below
            "Capitalized Salaries",
            "Capitalized IT Services",
            "Capitalized Office Rent & Utilities",
            "Capitalized Professional Services",
            "Capitalized Marketing (COH)",
            "Capitalized Sales Cost (COH)",
            "Capitalized Additional Expenses",
            "",
            "Net Cashflow from Investments"
        ]

        financing_line_items = [
            "Asset Level Term Loan",               # TOTAL of items below
            "Principal Drawn",
            "Principal Repaid",
            "Interest Paid",
            "Arrangement Fees",
            "",
            "Asset Level Revolver Facility",       # TOTAL of items below
            "Principal Drawn",
            "Principal Repaid",
            "Fees and Interest Paid",
            "",
            "Project Level Term Loan",             # TOTAL of items below
            "Principal Drawn",
            "Principal Repaid",
            "Interest Paid",
            "Arrangement Fees",
            "",
            "Project Level Revolver Facility",     # TOTAL of items below
            "Principal Drawn",
            "Principal Repaid",
            "Fees and Interest Paid",
            "",
            "Equity Injection",                    # TOTAL of items below
            "Asset Level",
            "Project Level",
            "",
            "Net Cashflow from Financing",
        ]

        # ========================================================================
        # ASSET FILTRATION MECHANISM FOR EXCEL OUTPUT
        # ========================================================================

        cf_columns = model_timeline_me.index
        _n_periods_cf = len(cf_columns)

        _asset_id_output_flag = pd.Series(False, index=template_asset_timeline.index)

        devco_output_inclusion_flag = (
            pd.Series(Asset.ProjectDetails.devco_output_inclusion)
                .eq("Yes")
                .reindex(template_asset_timeline.index)
        )
        asset_unique_id = pd.Series(Asset.ProjectDetails.asset_unique_identifier)
        asset_name = pd.Series(Asset.ProjectDetails.asset_name)

        asset_id_dropdown = Global.FiltrationDropdowns.asset_id
        asset_name_dropdown = Global.FiltrationDropdowns.asset_name

        if asset_id_dropdown == "Consolidated":
            _asset_id_output_flag.loc[:] = True
        elif asset_id_dropdown == "Synthetic":
            _asset_id_output_flag.loc[devco_output_inclusion_flag] = True
        elif asset_id_dropdown in asset_unique_id.values:
            _asset_id_output_flag.loc[asset_unique_id == asset_id_dropdown] = True
        elif asset_name_dropdown == "Consolidated":
            _asset_id_output_flag.loc[:] = True
        elif asset_name_dropdown == "Synthetic":
            _asset_id_output_flag.loc[devco_output_inclusion_flag] = True
        elif asset_name_dropdown in asset_name.values:
            _asset_id_output_flag.loc[asset_name == asset_name_dropdown] = True
        else:
            _asset_id_output_flag.loc[:] = True

        # JV exclusion mask: zeros out JV-included assets, keeps non-JV assets
        _jv_exclusion_mask = (~_jv_asset_level_inclusion_flag).values[:, np.newaxis].astype(float)
        _jv_mask_1d = _jv_exclusion_mask[:, 0].astype(bool)

        _all_assets_included = _asset_id_output_flag.all()
        _project_level_multiplier = 1.0 if _all_assets_included else 0.0

        # ========================================================================
        # PRE-COMPUTE FILTER MASKS ONCE (avoids repeated per-call mask creation)
        # ========================================================================
        _af_mask_1d  = _asset_id_output_flag.values.astype(bool)
        _af_mask_2d  = _af_mask_1d[:, np.newaxis]

        # Project-financing + JV-exclusion combined mask (used only when not all assets included)
        _pf_jv_mask_1d = _af_mask_1d & _is_project_financing & _jv_mask_1d
        _pf_jv_mask_2d = _pf_jv_mask_1d[:, np.newaxis]

        # Selected-asset mask for weighted escrow calculations
        _selected_asset_mask    = _af_mask_1d & _jv_mask_1d
        _selected_asset_mask_2d = _selected_asset_mask[:, np.newaxis]

        # ========================================================================
        # CORE HELPERS â€” no intermediate DataFrame construction
        # ========================================================================

        def _to_f64(df):
            """Return a clean float64 numpy array (NaN â†’ 0). No copy if already float64."""
            if isinstance(df, pd.Series):
                arr = df.to_numpy(dtype=float, copy=False)
                np.nan_to_num(arr, copy=False, nan=0.0)
                return arr[:, np.newaxis]
            arr = df.to_numpy(dtype=float, copy=False)
            np.nan_to_num(arr, copy=False, nan=0.0)
            return arr

        def _fsum(df, mask_2d):
            """Apply boolean 2-D mask and sum across assets (axis=0) â†’ 1-D float64 array."""
            return np.where(mask_2d, _to_f64(df), 0.0).sum(axis=0)

        def _pos(df):   return  _fsum(df, _af_mask_2d)
        def _neg(df):   return -_fsum(df, _af_mask_2d)

        # ========================================================================
        # PRECOMPUTE ALL LEAF VALUES AS 1-D NUMPY ARRAYS
        # ========================================================================

        # --- CFO leaf values ---
        _v_offplan_escrow    =  _pos(o_cash_inflow_from_off_plan_sales)
        _v_on_plan           =  _pos(o_on_plan_sales_collection)
        _v_coll_postdev      =  _pos(o_sales_collection_without_escrow)
        _v_fwd_funding       =  _pos(o_forward_funding_cash)
        _v_fwd_sales         =  _pos(o_forward_sales_cash)
        _v_escrow_fees       =  _neg(o_escrow_setup_fees)
        _v_sales_cost        =  _neg(o_sales_cost)
        _v_mkt_cost          =  _neg(o_marketing_cost)
        _v_dlp               =  _neg(o_dlp_insurance)
        _v_void_opex         =  _neg(o_void_period_opex)
        _v_pa_recovery       =  _pos(o_pa_recovery)
        _v_sal_exp           =  _neg(o_coh_salaries_expensed_post_allocation)
        _v_it_exp            =  _neg(o_coh_it_services_expensed_post_allocation)
        _v_rent_exp          =  _neg(o_coh_office_rent_expensed_post_allocation)
        _v_prof_exp          =  _neg(o_coh_professional_services_expensed_post_allocation)
        _v_mkt_exp           =  _neg(o_coh_marketing_expensed_post_allocation)
        _v_sc_exp            =  _neg(o_coh_sales_cost_expensed_post_allocation)
        _v_add_exp           =  _neg(o_coh_additional_expensed_post_allocation)
        _v_gov_sub           =  _pos(o_government_subsidies_post_allocation)
        _v_oi1               =  _pos(o_other_income_1_post_allocation)
        _v_oi2               =  _pos(o_other_income_2_post_allocation)
        _v_oe1               =  _neg(o_other_expense_1_post_allocation)
        _v_oe2               =  _neg(o_other_expense_2_post_allocation)
        _v_oe3               =  _neg(o_other_expense_3_post_allocation)

        # --- CFO section totals ---
        _v_asset_sales   = _v_offplan_escrow + _v_on_plan + _v_coll_postdev + _v_fwd_funding + _v_fwd_sales
        _v_disposal      = _v_sales_cost + _v_mkt_cost
        _v_assoc_opex    = _v_dlp + _v_void_opex
        _v_coh_exp       = _v_sal_exp + _v_it_exp + _v_rent_exp + _v_prof_exp + _v_mkt_exp + _v_sc_exp + _v_add_exp
        _v_other_inc     = _v_gov_sub + _v_oi1 + _v_oi2
        _v_other_exp     = _v_oe1 + _v_oe2 + _v_oe3
        _v_cfo_net       = (_v_asset_sales + _v_escrow_fees + _v_disposal + _v_assoc_opex
                            + _v_pa_recovery + _v_coh_exp + _v_other_inc + _v_other_exp)

        # --- CFI leaf values ---
        _v_land_acq    =  _neg(o_land_acquisition_cost_post_allocation)
        _v_legal       =  _neg(o_legal_cost_post_allocation)
        _v_agency      =  _neg(o_agency_cost_post_allocation)
        _v_technical   =  _neg(o_technical_cost_post_allocation)
        _v_valuation   =  _neg(o_valuation_cost_post_allocation)
        _v_dd          =  _neg(o_due_diligence_cost_post_allocation)
        _v_vert_const  =  _neg(o_vertical_construction_cost_post_allocation)
        _v_pa_alloc    =  _neg(o_pa_allocation)
        _v_cec_alloc   =  _neg(o_cec_allocation)
        _v_canal_alloc =  _neg(o_canal_allocation)
        _v_design      =  _neg(o_design_cost_post_allocation)
        _v_permit      =  _neg(o_permitting_cost_post_allocation)
        _v_supervision =  _neg(o_supervision_cost_post_allocation)
        _v_pm_fees     =  _neg(o_pm_fees_post_allocation)
        _v_contingency =  _neg(o_contingency_cost_post_allocation)
        _v_sal_cap     =  _neg(o_coh_salaries_capitalized_post_allocation)
        _v_it_cap      =  _neg(o_coh_it_services_capitalized_post_allocation)
        _v_rent_cap    =  _neg(o_coh_office_rent_capitalized_post_allocation)
        _v_prof_cap    =  _neg(o_coh_professional_services_capitalized_post_allocation)
        _v_mkt_cap     =  _neg(o_coh_marketing_capitalized_post_allocation)
        _v_sc_cap      =  _neg(o_coh_sales_cost_capitalized_post_allocation)
        _v_add_cap     =  _neg(o_coh_additional_capitalized_post_allocation)

        # --- CFI section totals ---
        _v_land_trans  = _v_legal + _v_agency + _v_technical + _v_valuation + _v_dd
        _v_dev_costs   = _v_vert_const + _v_pa_alloc + _v_cec_alloc + _v_canal_alloc
        _v_soft_costs  = _v_design + _v_permit + _v_supervision + _v_pm_fees
        _v_coh_cap     = _v_sal_cap + _v_it_cap + _v_rent_cap + _v_prof_cap + _v_mkt_cap + _v_sc_cap + _v_add_cap
        _v_cfi_net     = (_v_land_acq + _v_land_trans + _v_dev_costs + _v_soft_costs
                          + _v_contingency + _v_coh_cap)

        # --- CFF leaf values ---
        _v_atl_drawn   =  _pos(o_asset_term_loan_drawdown)
        _v_atl_repaid  =  _pos(o_asset_term_loan_principal) + _pos(o_asset_term_loan_balloon)
        _v_atl_int     =  _neg(o_asset_term_loan_interest_expensed)
        _v_atl_fees    =  _neg(o_asset_term_loan_arrangement_fees)
        _v_atl_total   =  _v_atl_drawn + _v_atl_repaid + _v_atl_int + _v_atl_fees

        _v_arl_drawn   =  _pos(w_asset_debt_revolver_debt_withdrawal)
        _v_arl_repaid  =  _pos(w_asset_debt_revolver_debt_repayment)
        _v_arl_fees    = -(_pos(w_asset_debt_revolver_interest_expense)
                           + _pos(w_asset_debt_revolver_debt_arrangement_fees)
                           + _pos(w_asset_debt_revolver_debt_commitment_fees))
        _v_arl_total   =  _v_arl_drawn + _v_arl_repaid + _v_arl_fees

        _plm = _project_level_multiplier
        _v_ptl_drawn   =  o_project_term_loan_drawdown.to_numpy(dtype=float, copy=False) * _plm
        _v_ptl_repaid  = (o_project_term_loan_principal.to_numpy(dtype=float, copy=False)
                          + o_project_term_loan_balloon.to_numpy(dtype=float, copy=False)) * _plm
        _v_ptl_int     = -o_project_term_loan_interest_expensed.to_numpy(dtype=float, copy=False) * _plm
        _v_ptl_fees    = -o_project_term_loan_arrangement_fees.to_numpy(dtype=float, copy=False) * _plm
        _v_ptl_total   =  _v_ptl_drawn + _v_ptl_repaid + _v_ptl_int + _v_ptl_fees

        _v_prl_drawn   =  o_project_revolver_drawdown.to_numpy(dtype=float, copy=False) * _plm
        _v_prl_repaid  =  o_project_revolver_repayment.to_numpy(dtype=float, copy=False) * _plm
        _v_prl_fees    = -(o_project_revolver_interest_expense.to_numpy(dtype=float, copy=False)
                           + o_project_revolver_arrangement_fees.to_numpy(dtype=float, copy=False)
                           + o_project_revolver_commitment_fees.to_numpy(dtype=float, copy=False)) * _plm
        _v_prl_total   =  _v_prl_drawn + _v_prl_repaid + _v_prl_fees

        # --- Project-level equity ---
        _v_asset_equity = _pos(o_asset_equity_injection)
        if _all_assets_included:
            _v_proj_equity = o_equity_infusion.to_numpy(dtype=float, copy=False)
        else:
            # Only project-financing assets (already JV-excluded via _pf_jv_mask_2d)
            _cfo_pf = (
                 _fsum(o_cash_inflow_from_off_plan_sales, _pf_jv_mask_2d)
                + _fsum(o_on_plan_sales_collection, _pf_jv_mask_2d)
                + _fsum(o_sales_collection_without_escrow, _pf_jv_mask_2d)
                + _fsum(o_forward_funding_cash, _pf_jv_mask_2d)
                + _fsum(o_forward_sales_cash, _pf_jv_mask_2d)
                - _fsum(o_escrow_setup_fees, _pf_jv_mask_2d)
                - _fsum(o_sales_cost, _pf_jv_mask_2d)
                - _fsum(o_marketing_cost, _pf_jv_mask_2d)
                - _fsum(o_dlp_insurance, _pf_jv_mask_2d)
                - _fsum(o_void_period_opex, _pf_jv_mask_2d)
                + _fsum(o_pa_recovery, _pf_jv_mask_2d)
                - _fsum(o_coh_salaries_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_it_services_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_office_rent_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_professional_services_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_marketing_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_sales_cost_expensed_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_additional_expensed_post_allocation, _pf_jv_mask_2d)
                + _fsum(o_government_subsidies_post_allocation, _pf_jv_mask_2d)
                + _fsum(o_other_income_1_post_allocation, _pf_jv_mask_2d)
                + _fsum(o_other_income_2_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_other_expense_1_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_other_expense_2_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_other_expense_3_post_allocation, _pf_jv_mask_2d)
            )
            _cfi_pf = (
                - _fsum(o_land_acquisition_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_legal_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_agency_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_technical_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_valuation_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_due_diligence_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_vertical_construction_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_pa_allocation, _pf_jv_mask_2d)
                - _fsum(o_cec_allocation, _pf_jv_mask_2d)
                - _fsum(o_canal_allocation, _pf_jv_mask_2d)
                - _fsum(o_design_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_permitting_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_supervision_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_pm_fees_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_contingency_cost_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_salaries_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_it_services_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_office_rent_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_professional_services_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_marketing_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_sales_cost_capitalized_post_allocation, _pf_jv_mask_2d)
                - _fsum(o_coh_additional_capitalized_post_allocation, _pf_jv_mask_2d)
            )
            _v_proj_equity = np.maximum(-(_cfo_pf + _cfi_pf), 0.0)

        _v_equity_total = _v_asset_equity + _v_proj_equity
        _v_cff_net      = _v_atl_total + _v_arl_total + _v_ptl_total + _v_prl_total + _v_equity_total

        # ========================================================================
        # BUILD DATAFRAMES IN ONE SHOT (no row-by-row .loc assignment)
        # ========================================================================

        def _arr_to_obj(arr):
            """Convert float64 array to object array with NaN replaced by None."""
            out = arr.astype(object)
            nan_pos = np.isnan(arr)
            if nan_pos.any():
                out[nan_pos] = None
            return out

        def _build_df(line_items, value_map):
            """
            Build a DataFrame in a single constructor call.
            value_map: {label: 1-D float64 array} for all non-empty labels.
            Empty-string labels get a row of None.
            """
            n = len(line_items)
            data = np.empty((n, _n_periods_cf), dtype=object)
            data[:] = None
            for i, label in enumerate(line_items):
                if label != "":
                    data[i] = _arr_to_obj(value_map[label])
            return pd.DataFrame(data, index=line_items, columns=cf_columns)

        # --- CFO value map ---
        _cfo_map = {
            "Cash Received from Asset Sales":                _v_asset_sales,
            "Asset Sales through Escrow":                    _v_offplan_escrow + _v_on_plan,
            "Asset Sales through Collection (Post-Dev)":     _v_coll_postdev,
            "Forward Funding":                               _v_fwd_funding,
            "Forward Sales":                                 _v_fwd_sales,
            "Escrow Setup Fees":                             _v_escrow_fees,
            "Disposal Costs":                                _v_disposal,
            "Sales Cost":                                    _v_sales_cost,
            "Marketing Cost":                                _v_mkt_cost,
            "Associated Opex":                               _v_assoc_opex,
            "DLP Insurance":                                 _v_dlp,
            "Void Period Opex":                              _v_void_opex,
            "PA Recovery":                                   _v_pa_recovery,
            "Corporate Overhead Expenses":                   _v_coh_exp,
            "Salaries":                                      _v_sal_exp,
            "IT Services":                                   _v_it_exp,
            "Office Rent & Utilities":                       _v_rent_exp,
            "Professional Services":                         _v_prof_exp,
            "Marketing (COH)":                               _v_mkt_exp,
            "Sales Cost (COH)":                              _v_sc_exp,
            "Additional Expenses":                           _v_add_exp,
            "Other Income":                                  _v_other_inc,
            "Government Subsidies":                          _v_gov_sub,
            "Other Income 1":                                _v_oi1,
            "Other Income 2":                                _v_oi2,
            "Other Expense":                                 _v_other_exp,
            "Other Expense 1":                               _v_oe1,
            "Other Expense 2":                               _v_oe2,
            "Other Expense 3":                               _v_oe3,
            "Net Cashflow from Operations":                  _v_cfo_net,
        }

        # --- CFI value map ---
        _cfi_map = {
            "Land Acquisition Cost Payment":        _v_land_acq,
            "Land Acquisition Transaction Costs":   _v_land_trans,
            "Legal Cost":                           _v_legal,
            "Agency Cost":                          _v_agency,
            "Technical Cost":                       _v_technical,
            "Valuation Cost":                       _v_valuation,
            "Due Diligence Cost":                   _v_dd,
            "Development Costs":                    _v_dev_costs,
            "Vertical Construction Cost":           _v_vert_const,
            "Public Amenity Cost":                  _v_pa_alloc,
            "CEC Cost":                             _v_cec_alloc,
            "Canal Cost":                           _v_canal_alloc,
            "Soft Costs Payment":                   _v_soft_costs,
            "Design Cost":                          _v_design,
            "Permitting Cost":                      _v_permit,
            "Supervision Cost":                     _v_supervision,
            "Project Management Cost":              _v_pm_fees,
            "Contingency Cost Payment":             _v_contingency,
            "Corporate Overhead Capitalized":       _v_coh_cap,
            "Capitalized Salaries":                 _v_sal_cap,
            "Capitalized IT Services":              _v_it_cap,
            "Capitalized Office Rent & Utilities":  _v_rent_cap,
            "Capitalized Professional Services":    _v_prof_cap,
            "Capitalized Marketing (COH)":          _v_mkt_cap,
            "Capitalized Sales Cost (COH)":         _v_sc_cap,
            "Capitalized Additional Expenses":      _v_add_cap,
            "Net Cashflow from Investments":        _v_cfi_net,
        }

        cashflow_from_operations  = _build_df(operations_line_items,  _cfo_map)
        cashflow_from_investments = _build_df(investment_line_items,   _cfi_map)

        # --- CFF: built positionally (duplicate label names prevent label-based lookup) ---
        _cff_data = np.empty((len(financing_line_items), _n_periods_cf), dtype=object)
        _cff_data[:] = None
        # Asset Level Term Loan (rows 0-4)
        _cff_data[0]  = _arr_to_obj(_v_atl_total)
        _cff_data[1]  = _arr_to_obj(_v_atl_drawn)
        _cff_data[2]  = _arr_to_obj(_v_atl_repaid)
        _cff_data[3]  = _arr_to_obj(_v_atl_int)
        _cff_data[4]  = _arr_to_obj(_v_atl_fees)
        # row 5: empty
        # Asset Level Revolver Facility (rows 6-9)
        _cff_data[6]  = _arr_to_obj(_v_arl_total)
        _cff_data[7]  = _arr_to_obj(_v_arl_drawn)
        _cff_data[8]  = _arr_to_obj(_v_arl_repaid)
        _cff_data[9]  = _arr_to_obj(_v_arl_fees)
        # row 10: empty
        # Project Level Term Loan (rows 11-15)
        _cff_data[11] = _arr_to_obj(_v_ptl_total)
        _cff_data[12] = _arr_to_obj(_v_ptl_drawn)
        _cff_data[13] = _arr_to_obj(_v_ptl_repaid)
        _cff_data[14] = _arr_to_obj(_v_ptl_int)
        _cff_data[15] = _arr_to_obj(_v_ptl_fees)
        # row 16: empty
        # Project Level Revolver Facility (rows 17-20)
        _cff_data[17] = _arr_to_obj(_v_prl_total)
        _cff_data[18] = _arr_to_obj(_v_prl_drawn)
        _cff_data[19] = _arr_to_obj(_v_prl_repaid)
        _cff_data[20] = _arr_to_obj(_v_prl_fees)
        # row 21: empty
        # Equity Injection (rows 22-24)
        _cff_data[22] = _arr_to_obj(_v_equity_total)
        _cff_data[23] = _arr_to_obj(_v_asset_equity)
        _cff_data[24] = _arr_to_obj(_v_proj_equity)
        # row 25: empty
        # Net CFF (row 26)
        _cff_data[26] = _arr_to_obj(_v_cff_net)

        cashflow_from_financing = pd.DataFrame(
            _cff_data, index=financing_line_items, columns=cf_columns
        )

        # ========================================================================
        # ESCROW SCHEDULE
        # ========================================================================

        def _calculate_weighted_progress_curve(underlying_df):
            arr = _to_f64(underlying_df)
            masked = np.where(_selected_asset_mask_2d, arr, 0.0)
            period_totals = masked.sum(axis=0)
            total = period_totals.sum()
            return np.zeros(_n_periods_cf) if total <= 0 else period_totals / total

        def _calculate_weighted_series(series_df, weight_series):
            arr = _to_f64(series_df)
            values = np.where(_selected_asset_mask_2d, arr, 0.0)
            weights_raw = np.asarray(weight_series, dtype=float)
            np.nan_to_num(weights_raw, copy=False, nan=0.0)
            weights = np.where(_selected_asset_mask, weights_raw, 0.0)
            wt = weights.sum()
            return np.zeros(_n_periods_cf) if wt <= 0 else (values * weights[:, np.newaxis]).sum(axis=0) / wt

        _escrow_construction_progress_output = _calculate_weighted_progress_curve(w_vertical_construction_phasing)
        _escrow_cumulative_progress_output = np.ceil(
            np.minimum(np.cumsum(_escrow_construction_progress_output), 1.0) * 1000
        ) / 1000

        _escrow_sales_arr = _to_f64(o_escrow_sales_revenue)
        _escrow_sales_total_by_asset = _escrow_sales_arr.sum(axis=1)
        _escrow_sales_payment_absorption_output = _calculate_weighted_series(
            o_payment_absorption, _escrow_sales_total_by_asset
        )

        escrow_schedule_line_items = [
            "Construction Progress",
            "Cumulative Construction Progress",
            "Sales Payment Absorption",
            "Inflows to Escrow",
            "Funds Available for Soft Cost",
            "Funds Available for Hard Cost",
            "Transfer to Retention",
            "",
            "Soft Opening Balance",
            "Soft Inflows",
            "Soft Cost Total Availability",
            "Soft Cost Payment Requirement",
            "Soft Cost Cumulative Requirement",
            "Soft Cost Payment from Escrow",
            "Soft Additional Requirement",
            "Soft Amount Available After Reallocation",
            "Soft Last Year Release",
            "Soft Closing Balance",
            "",
            "Hard Opening Balance",
            "Hard Inflows",
            "Hard Cost Total Availability",
            "Hard Cost Payment Requirement",
            "Hard Cost Cumulative Requirement",
            "Hard Cost Payment from Escrow",
            "Hard Additional Requirement",
            "Hard Amount Available After Payment",
            "Hard Last Year Release",
            "Hard Closing Balance",
            "",
            "Amount Available for Reallocation",
            "Reallocation Amount",
            "Reallocated Funds for Hard Cost Payment",
            "Additional Requirement After Allocation",
            "",
            "Off-plan Cash Inflow",
            "Escrow Setup Fees",
        ]

        # Reuse already-computed arrays where possible (_v_offplan_escrow, _v_escrow_fees)
        _escrow_map = {
            "Construction Progress":                    _escrow_construction_progress_output,
            "Cumulative Construction Progress":         _escrow_cumulative_progress_output,
            "Sales Payment Absorption":                 _escrow_sales_payment_absorption_output,
            "Inflows to Escrow":                        _pos(o_inflows_to_escrow),
            "Funds Available for Soft Cost":            _pos(o_funds_available_for_soft_cost),
            "Funds Available for Hard Cost":            _pos(o_funds_available_for_hard_cost),
            "Transfer to Retention":                    _pos(o_transfer_to_retention),
            "Soft Opening Balance":                     _pos(w_soft_opening_balance),
            "Soft Inflows":                             _pos(o_funds_available_for_soft_cost),
            "Soft Cost Total Availability":             _pos(w_soft_cost_total_availability),
            "Soft Cost Payment Requirement":            _pos(w_soft_cost_payment_requirement),
            "Soft Cost Cumulative Requirement":         _pos(w_soft_cost_cumulative_requirement),
            "Soft Cost Payment from Escrow":            _pos(w_soft_cost_payment_from_escrow),
            "Soft Additional Requirement":              _pos(w_additional_requirements_for_soft_cost),
            "Soft Amount Available After Reallocation": _pos(w_amount_available_after_soft_cost_and_reallocated_payment),
            "Soft Last Year Release":                   _pos(w_last_year_release_soft_cost),
            "Soft Closing Balance":                     _pos(w_soft_closing_balance),
            "Hard Opening Balance":                     _pos(w_hard_opening_balance),
            "Hard Inflows":                             _pos(o_funds_available_for_hard_cost),
            "Hard Cost Total Availability":             _pos(w_hard_cost_total_availability),
            "Hard Cost Payment Requirement":            _pos(w_hard_cost_payment_requirement),
            "Hard Cost Cumulative Requirement":         _pos(w_hard_cost_cumulative_requirement),
            "Hard Cost Payment from Escrow":            _pos(w_hard_cost_payment_from_escrow),
            "Hard Additional Requirement":              _pos(w_additional_requirements_for_hard_cost),
            "Hard Amount Available After Payment":      _pos(w_amount_available_after_hard_cost_payment),
            "Hard Last Year Release":                   _pos(w_last_year_release_hard_cost),
            "Hard Closing Balance":                     _pos(w_hard_closing_balance),
            "Amount Available for Reallocation":        _pos(w_amount_available_for_reallocation),
            "Reallocation Amount":                      _pos(w_reallocation_amount),
            "Reallocated Funds for Hard Cost Payment":  _pos(w_reallocated_funds_for_hard_cost_payment),
            "Additional Requirement After Allocation":  _pos(w_additional_requirement_after_allocation),
            "Off-plan Cash Inflow":                     _v_offplan_escrow,   # reused â€” already computed
            "Escrow Setup Fees":                        _v_escrow_fees,      # reused â€” already computed
        }

        escrow_schedule = _build_df(escrow_schedule_line_items, _escrow_map)

        _record_timing("Structured cashflow statements built")

        # ========================================================================
        # PREPARE TIMELINE FOR OUTPUT
        # ========================================================================
        
        # Format dates for output
        model_timeline_me_output = model_timeline_me.copy()
        model_timeline_me_output["Period Start"] = model_timeline_me_output["Period Start"].dt.strftime("%Y-%m-%d")
        model_timeline_me_output["Period End"] = model_timeline_me_output["Period End"].dt.strftime("%Y-%m-%d")
        
        model_timeline_ye_output = model_timeline_ye.copy()
        model_timeline_ye_output["Period Start"] = model_timeline_ye_output["Period Start"].dt.strftime("%Y-%m-%d")
        model_timeline_ye_output["Period End"] = model_timeline_ye_output["Period End"].dt.strftime("%Y-%m-%d")
        
        o_monthly_timeline = model_timeline_me_output.T
        o_yearly_timeline = model_timeline_ye_output.T

        # ============================================================================================
        # SUB-MODULE 3.16: DATA NORMALIZATION FOR DASHBOARD
        # ============================================================================================
        # This section normalizes all calculated DataFrames into a long-format structure
        # suitable for dashboard visualization and analytics. Each DataFrame is flattened
        # from wide format (assets x periods) to long format with metadata columns.
        #
        # Output Structure:
        #   - Model: Source model identifier ("DevCo")
        #   - Value Type: "Monthly" or "Annual" aggregation
        #   - Cashflow Section: CFO, CFI, or CFF classification
        #   - Main Category: Primary grouping (e.g., "Cash Received from Asset Sale")
        #   - Line Item: Specific line item name
        #   - Asset: Asset identifier
        #   - Period Start / Year: Time dimension
        #   - Value: Numeric value
        #   - Additional metadata: Region, City, Asset Class, etc.
        # ============================================================================================
        
        _record_timing("Dashboard normalization preparation")

        def flatten_asset_timeseries(
            data,
            period_start,
            registry_meta,
            additional_columns=None,
            expected_shape=(75, 504)
        ):
            """
            Flattens asset timeseries data (DataFrame, ndarray, or Series) to long format for dashboard analytics.
            Handles pd.Series by converting to DataFrame.
            """
            data = fn_replace_nan(data)
            
            # Handle numpy array
            if isinstance(data, np.ndarray):
                data = pd.DataFrame(data)

            # Handle pandas Series
            if isinstance(data, pd.Series):
                # Convert Series to DataFrame with one row (project-level) or one column (asset-level)
                if len(data.index) == len(period_start):
                    # Series indexed by period_start: treat as single asset, shape (periods,)
                    data = pd.DataFrame([data.values], columns=period_start)
                else:
                    # Series indexed by asset: treat as single period, shape (assets,)
                    data = pd.DataFrame(data.values.reshape(-1, 1), index=data.index, columns=[period_start[0]])

            if not isinstance(data, pd.DataFrame):
                raise TypeError("Input data must be DataFrame, ndarray, or Series.")

            rows, cols = data.shape

            if len(period_start) != cols:
                raise ValueError(
                    f"Period length mismatch. Expected {cols}, got {len(period_start)}."
                )

            # Determine category level
            if rows == 1 and cols == expected_shape[1]:
                category_level = "Project"
            elif rows == expected_shape[0] and cols == expected_shape[1]:
                category_level = "Asset"
            else:
                category_level = "Other"
                warnings.warn(f"Unexpected shape {data.shape}")

            data = data.copy()
            data.columns = period_start
            data["Asset"] = data.index

            df_long = data.melt(
                id_vars="Asset",
                var_name="Period Start",
                value_name="Value"
            )

            # Drop zero values
            df_long = df_long[df_long["Value"] != 0]

            df_long["Asset"] = df_long["Asset"].astype(int)

            # Add metadata columns
            if additional_columns:

                if category_level == "Asset":
                    # Asset level â†’ metadata must align with asset rows
                    for col_name, col_values in additional_columns.items():

                        if len(col_values) != rows:
                            warnings.warn(
                                f"Metadata mismatch for {col_name} since length {len(col_values)} "
                                f"does not match number of rows {rows}. Skipping."
                            )
                            continue

                        mapping = dict(zip(range(rows), col_values))
                        df_long[col_name] = df_long["Asset"].map(mapping)

                elif category_level == "Project":
                    # Project level â†’ assign first value silently
                    for col_name, col_values in additional_columns.items():
                        df_long[col_name] = col_values[0]

                else:
                    # Unknown structure
                    warnings.warn("Unknown category level. Metadata not applied.")

            # Add reporting columns (Monthly first)
            df_long["Model"] = registry_meta["Model"]
            df_long["Value Type"] = "Monthly"
            df_long["Cashflow Section"] = registry_meta["Cashflow Section"]
            df_long["Main Category"] = registry_meta["Main Category"]
            df_long["Line Item"] = registry_meta["Line Item"]
            df_long["Value"] = df_long["Value"] * registry_meta["Sign"]
            df_long["Category"] = category_level

            # ---------- Annual Aggregation ----------
            df_long["Year"] = pd.to_datetime(df_long["Period Start"]).dt.year

            # Identify metadata columns that actually exist
            meta_cols = []
            if additional_columns:
                meta_cols = [col for col in additional_columns.keys() if col in df_long.columns]

            group_cols = [
                "Model",
                "Asset",
                "Year",
                "Cashflow Section",
                "Main Category",
                "Line Item",
                "Category"
            ] + meta_cols

            annual_df = (
                df_long
                .groupby(group_cols, as_index=False)["Value"]
                .sum()
            )

            annual_df["Value Type"] = "Annual"

            # Combine Monthly + Annual
            final_df = pd.concat([df_long, annual_df], ignore_index=True)

            # Reorder columns (first 5 as requested)
            first_cols = [
                "Model",
                "Value Type",
                "Cashflow Section",
                "Main Category",
                "Line Item"
            ]

            remaining_cols = [c for c in final_df.columns if c not in first_cols]

            final_df = final_df[first_cols + remaining_cols]

            return final_df.reset_index(drop=True)

        # Prepare combined escrow collection with proper index alignment
        _on_plan_reindexed = o_on_plan_sales_collection.reindex(o_cash_inflow_from_off_plan_sales.index)
        _asset_sales_through_escrow = o_cash_inflow_from_off_plan_sales.add(_on_plan_reindexed, fill_value=0)

        data_registry = {

            # =====================================================
            # CASHFLOW FROM OPERATIONS
            # =====================================================

            # Asset Sale Receipts
            "Asset Sales through Escrow": {
                "df": _asset_sales_through_escrow,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Cash Received from Asset Sale",
                "Line Item": "Asset Sales through Escrow",
                "Sign": 1
            },
            "Asset Sales through Collection Plan": {
                "df": o_sales_collection_without_escrow,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Cash Received from Asset Sale",
                "Line Item": "Asset Sales through Collection Plan",
                "Sign": 1
            },
            "Forward Funding": {
                "df": o_forward_funding_cash,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Cash Received from Asset Sale",
                "Line Item": "Forward Funding",
                "Sign": 1
            },
            "Forward Sales": {
                "df": o_forward_sales_cash,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Cash Received from Asset Sale",
                "Line Item": "Forward Sales",
                "Sign": 1
            },

            # Escrow Fees
            "Escrow Set Up Fees": {
                "df": o_escrow_setup_fees,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Escrow Set Up Fees",
                "Line Item": "Escrow Set Up Fees",
                "Sign": -1
            },

            # Disposal Cost
            "Sales Cost": {
                "df": o_sales_cost,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Disposal Cost",
                "Line Item": "Sales Cost",
                "Sign": -1
            },
            "Marketing Cost": {
                "df": o_marketing_cost,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Disposal Cost",
                "Line Item": "Marketing Cost",
                "Sign": -1
            },

            # Associated Opex
            "DLP Insurance": {
                "df": o_dlp_insurance,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Associated Opex",
                "Line Item": "DLP Insurance",
                "Sign": -1
            },
            "Void Period Opex": {
                "df": o_void_period_opex,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Associated Opex",
                "Line Item": "Void Period Opex",
                "Sign": -1
            },

            # PA Recovery
            "PA Recovery": {
                "df": o_pa_recovery,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "PA Recovery",
                "Line Item": "PA Recovery",
                "Sign": 1
            },

            # Corporate Overheads Expensed
            "Salaries Expense": {
                "df": o_coh_salaries_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Salaries Expense",
                "Sign": -1
            },
            "IT Services Expense": {
                "df": o_coh_it_services_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "IT Services Expense",
                "Sign": -1
            },
            "Office Rent and Utilities Expense": {
                "df": o_coh_office_rent_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Office Rent and Utilities Expense",
                "Sign": -1
            },
            "Professional Services Expense": {
                "df": o_coh_professional_services_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Professional Services Expense",
                "Sign": -1
            },
            "Marketing Expense": {
                "df": o_coh_marketing_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Marketing Expense",
                "Sign": -1
            },
            "Sales Cost (COH) Expense": {
                "df": o_coh_sales_cost_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Sales Cost (COH) Expense",
                "Sign": -1
            },
            "Additional Expenses": {
                "df": o_coh_additional_expensed_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Corporate Overhead Expenses",
                "Line Item": "Additional Expenses",
                "Sign": -1
            },

            # Other Income
            "Government Subsidies": {
                "df": o_government_subsidies_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Income",
                "Line Item": "Government Subsidies",
                "Sign": 1
            },
            "Other Income 1": {
                "df": o_other_income_1_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Income",
                "Line Item": "Other Income 1",
                "Sign": 1
            },
            "Other Income 2": {
                "df": o_other_income_2_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Income",
                "Line Item": "Other Income 2",
                "Sign": 1
            },

            # Other Expense
            "Other Expense 1": {
                "df": o_other_expense_1_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Expense",
                "Line Item": "Other Expense 1",
                "Sign": -1
            },
            "Other Expense 2": {
                "df": o_other_expense_2_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Expense",
                "Line Item": "Other Expense 2",
                "Sign": -1
            },
            "Other Expense 3": {
                "df": o_other_expense_3_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Operations",
                "Main Category": "Other Expense",
                "Line Item": "Other Expense 3",
                "Sign": -1
            },

            # =====================================================
            # CASHFLOW FROM INVESTMENTS
            # =====================================================

            "Land Acquisition Cost Payment": {
                "df": o_land_acquisition_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition",
                "Line Item": "Land Acquisition Cost Payment",
                "Sign": -1
            },

            # Land Acquisition Transaction Costs
            "Legal Cost": {
                "df": o_legal_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition Transaction Costs",
                "Line Item": "Legal Cost",
                "Sign": -1
            },
            "Agency Cost": {
                "df": o_agency_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition Transaction Costs",
                "Line Item": "Agency Cost",
                "Sign": -1
            },
            "Technical Cost": {
                "df": o_technical_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition Transaction Costs",
                "Line Item": "Technical Cost",
                "Sign": -1
            },
            "Valuation Cost": {
                "df": o_valuation_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition Transaction Costs",
                "Line Item": "Valuation Cost",
                "Sign": -1
            },
            "Due Diligence Cost": {
                "df": o_due_diligence_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Land Acquisition Transaction Costs",
                "Line Item": "Due Diligence Cost",
                "Sign": -1
            },

            # Development Costs
            "Vertical Construction Cost": {
                "df": o_vertical_construction_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Development Costs",
                "Line Item": "Vertical Construction Cost",
                "Sign": -1
            },
            "Public Amenity Cost": {
                "df": o_pa_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Development Costs",
                "Line Item": "Public Amenity Cost",
                "Sign": -1
            },
            "CEC Cost": {
                "df": o_cec_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Development Costs",
                "Line Item": "CEC Cost",
                "Sign": -1
            },
            "Canal Cost": {
                "df": o_canal_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Development Costs",
                "Line Item": "Canal Cost",
                "Sign": -1
            },

            # Soft Costs
            "Design Cost": {
                "df": o_design_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Soft Costs Payment",
                "Line Item": "Design Cost",
                "Sign": -1
            },
            "Permitting Cost": {
                "df": o_permitting_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Soft Costs Payment",
                "Line Item": "Permitting Cost",
                "Sign": -1
            },
            "Supervision Cost": {
                "df": o_supervision_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Soft Costs Payment",
                "Line Item": "Supervision Cost",
                "Sign": -1
            },
            "Project Management Cost": {
                "df": o_pm_fees_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Soft Costs Payment",
                "Line Item": "Project Management Cost",
                "Sign": -1
            },

            "Contingency Cost Payment": {
                "df": o_contingency_cost_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Contingency",
                "Line Item": "Contingency Cost Payment",
                "Sign": -1
            },

            # Corporate Overhead Capitalized
            "Capitalized Salaries": {
                "df": o_coh_salaries_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Salaries",
                "Sign": -1
            },
            "Capitalized IT Services": {
                "df": o_coh_it_services_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized IT Services",
                "Sign": -1
            },
            "Capitalized Office Rent & Utilities": {
                "df": o_coh_office_rent_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Office Rent & Utilities",
                "Sign": -1
            },
            "Capitalized Professional Services": {
                "df": o_coh_professional_services_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Professional Services",
                "Sign": -1
            },
            "Capitalized Marketing (COH)": {
                "df": o_coh_marketing_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Marketing (COH)",
                "Sign": -1
            },
            "Capitalized Sales Cost (COH)": {
                "df": o_coh_sales_cost_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Sales Cost (COH)",
                "Sign": -1
            },
            "Capitalized Additional Expenses": {
                "df": o_coh_additional_capitalized_post_allocation,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Investments",
                "Main Category": "Corporate Overhead Capitalized",
                "Line Item": "Capitalized Additional Expenses",
                "Sign": -1
            },

            # =====================================================
            # CASHFLOW FROM FINANCING
            # =====================================================

            # Asset Level Term Loan
            "Asset Level Term Loan - Principal Drawn": {
                "df": o_asset_term_loan_drawdown,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Term Loan",
                "Line Item": "Principal Drawn",
                "Sign": 1
            },
            "Asset Level Term Loan - Principal Repaid": {
                "df": o_asset_term_loan_principal + o_asset_term_loan_balloon,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Term Loan",
                "Line Item": "Principal Repaid",
                "Sign": 1
            },
            "Asset Level Term Loan - Interest Paid": {
                "df": o_asset_term_loan_interest_expensed,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Term Loan",
                "Line Item": "Interest Paid",
                "Sign": 1
            },
            "Asset Level Term Loan - Arrangement Fees": {
                "df": o_asset_term_loan_arrangement_fees,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Term Loan",
                "Line Item": "Arrangement Fees",
                "Sign": 1
            },

            # Asset Level Revolver Facility
            "Asset Level Revolver - Principal Drawn": {
                "df": w_asset_debt_revolver_debt_withdrawal,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Revolver Facility",
                "Line Item": "Principal Drawn",
                "Sign": 1
            },
            "Asset Level Revolver - Principal Repaid": {
                "df": w_asset_debt_revolver_debt_repayment,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Revolver Facility",
                "Line Item": "Principal Repaid",
                "Sign": 1
            },
            "Asset Level Revolver - Fees and Interest Paid": {
                "df": w_asset_debt_revolver_interest_expense + w_asset_debt_revolver_debt_arrangement_fees + w_asset_debt_revolver_debt_commitment_fees,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Asset Level Revolver Facility",
                "Line Item": "Fees and Interest Paid",
                "Sign": 1
            },

            # Project Level Term Loan
            "Project Level Term Loan - Principal Drawn": {
                "df": o_project_term_loan_drawdown,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Term Loan",
                "Line Item": "Principal Drawn",
                "Sign": 1
            },
            "Project Level Term Loan - Principal Repaid": {
                "df": o_project_term_loan_principal + o_project_term_loan_balloon,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Term Loan",
                "Line Item": "Principal Repaid",
                "Sign": 1
            },
            "Project Level Term Loan - Interest Paid": {
                "df": o_project_term_loan_interest_expensed,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Term Loan",
                "Line Item": "Interest Paid",
                "Sign": 1
            },
            "Project Level Term Loan - Arrangement Fees": {
                "df": o_project_term_loan_arrangement_fees,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Term Loan",
                "Line Item": "Arrangement Fees",
                "Sign": 1
            },

            # Project Level Revolver Facility
            "Project Level Revolver - Principal Drawn": {
                "df": o_project_revolver_drawdown,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Revolver Facility",
                "Line Item": "Principal Drawn",
                "Sign": 1
            },
            "Project Level Revolver - Principal Repaid": {
                "df": o_project_revolver_repayment,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Revolver Facility",
                "Line Item": "Principal Repaid",
                "Sign": 1
            },
            "Project Level Revolver - Fees and Interest Paid": {
                "df": o_project_revolver_interest_expense + o_project_revolver_arrangement_fees + o_project_revolver_commitment_fees,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Project Level Revolver Facility",
                "Line Item": "Fees and Interest Paid",
                "Sign": 1
            },

            # Equity Injection
            "Equity Injection - Asset Level": {
                "df": o_asset_equity_injection,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Equity Injection",
                "Line Item": "Asset Level",
                "Sign": 1
            },
            "Equity Injection - Project Level": {
                "df": o_equity_infusion,
                "Model": "DevCo",
                "Cashflow Section": "Cashflow from Financing",
                "Main Category": "Equity Injection",
                "Line Item": "Project Level",
                "Sign": 1
            }

        }

        common_metadata = {
            "Region": Asset.ProjectDetails.region,
            "City": Asset.ProjectDetails.city,
            "Asset Class": Asset.ProjectDetails.asset_class,
            "Sub Category": Asset.ProjectDetails.sub_category,
            "Typology": Asset.ProjectDetails.typology,
            "Construction Phase": Asset.ProjectDetails.construction_phase,
            "Asset Unique ID": Asset.ProjectDetails.asset_unique_identifier,
            "Business Model": Asset.BusinessModel.funding_type,
            "Exit Counterparty": Asset.BusinessModel.exit_counterparty,
            "JV Inclusion": Asset.JVModule.devco_inclusion
        }
        
        normalized_tables = []

        # for key, meta in data_registry.items():
            
        #     normalized_df = flatten_asset_timeseries(
        #         data=meta["df"],
        #         period_start=model_timeline_me["Period Start"],
        #         registry_meta=meta,
        #         additional_columns=common_metadata
        #     )

        #     normalized_tables.append(normalized_df)

        # # Concatenate everything
        # normalized_dashboard_data = pd.concat(normalized_tables, ignore_index=True)

        # normalized_dashboard_data.to_excel("normalized_dashboard_data.xlsx", index=False)
        # os.startfile("normalized_dashboard_data.xlsx")
        # raise breakpoint

        _record_timing("Dashboard data normalized")
        
        # ========================================================================
        # HELPER FUNCTION FOR JSON SERIALIZATION
        # ========================================================================
        
        def fn_df_to_json_with_index(df: pd.DataFrame):
            """
            Convert DataFrame to JSON-serializable format with index.
            
            Args:
                df: DataFrame to convert
                
            Returns:
                dict with index, columns, and data
            """
            return {
                "index": df.index.tolist(),
                "columns": df.columns.tolist(),
                "data": df.values.tolist(),
            }

        # ========================================================================
        # fn_copy_output_template_tab - FINAL OUTPUT ASSEMBLY
        # ========================================================================
        
        try:
            # Get year mapping from model timeline
            year_mapping = model_timeline_me.loc[:, "Year"]
            
            # Update the columns of the monthly DataFrames to reflect the 'Year'
            cf_ops = cashflow_from_operations.copy()
            cf_inv = cashflow_from_investments.copy()
            cf_fin = cashflow_from_financing.copy()
            cf_escrow = escrow_schedule.copy()
            
            cf_ops.columns = year_mapping
            cf_inv.columns = year_mapping
            cf_fin.columns = year_mapping
            cf_escrow.columns = year_mapping
            
            # Per-asset net cashflow (N_assets × N_periods) for sensitivity output.
            # Uses the same filtered per-asset DataFrames that feed monthly_dfs but
            # skips the axis=0 sum so each asset row is preserved.
            # Basis: Net CFO + Net CFI (DevCo has no Land in Kind component).
            def _paf(df):
                """Filter per-asset, return 2-D numpy array without summing."""
                return np.where(_af_mask_2d, _to_f64(df), 0.0)

            _pa_cfo_cfi = (
                # ── CFO ─────────────────────────────────────────────────────
                + _paf(o_cash_inflow_from_off_plan_sales)
                + _paf(o_on_plan_sales_collection)
                + _paf(o_sales_collection_without_escrow)
                + _paf(o_forward_funding_cash)
                + _paf(o_forward_sales_cash)
                - _paf(o_escrow_setup_fees)
                - _paf(o_sales_cost)
                - _paf(o_marketing_cost)
                - _paf(o_dlp_insurance)
                - _paf(o_void_period_opex)
                + _paf(o_pa_recovery)
                - _paf(o_coh_salaries_expensed_post_allocation)
                - _paf(o_coh_it_services_expensed_post_allocation)
                - _paf(o_coh_office_rent_expensed_post_allocation)
                - _paf(o_coh_professional_services_expensed_post_allocation)
                - _paf(o_coh_marketing_expensed_post_allocation)
                - _paf(o_coh_sales_cost_expensed_post_allocation)
                - _paf(o_coh_additional_expensed_post_allocation)
                + _paf(o_government_subsidies_post_allocation)
                + _paf(o_other_income_1_post_allocation)
                + _paf(o_other_income_2_post_allocation)
                - _paf(o_other_expense_1_post_allocation)
                - _paf(o_other_expense_2_post_allocation)
                - _paf(o_other_expense_3_post_allocation)
                # ── CFI ─────────────────────────────────────────────────────
                - _paf(o_land_acquisition_cost_post_allocation)
                - _paf(o_legal_cost_post_allocation)
                - _paf(o_agency_cost_post_allocation)
                - _paf(o_technical_cost_post_allocation)
                - _paf(o_valuation_cost_post_allocation)
                - _paf(o_due_diligence_cost_post_allocation)
                - _paf(o_vertical_construction_cost_post_allocation)
                - _paf(o_pa_allocation)
                - _paf(o_cec_allocation)
                - _paf(o_canal_allocation)
                - _paf(o_design_cost_post_allocation)
                - _paf(o_permitting_cost_post_allocation)
                - _paf(o_supervision_cost_post_allocation)
                - _paf(o_pm_fees_post_allocation)
                - _paf(o_contingency_cost_post_allocation)
                - _paf(o_coh_salaries_capitalized_post_allocation)
                - _paf(o_coh_it_services_capitalized_post_allocation)
                - _paf(o_coh_office_rent_capitalized_post_allocation)
                - _paf(o_coh_professional_services_capitalized_post_allocation)
                - _paf(o_coh_marketing_capitalized_post_allocation)
                - _paf(o_coh_sales_cost_capitalized_post_allocation)
                - _paf(o_coh_additional_capitalized_post_allocation)
            )
            _pa_net_cf_df = pd.DataFrame(
                np.nan_to_num(_pa_cfo_cfi, nan=0.0),
                index=asset_name.values,
                columns=model_timeline_me['Period Start'].dt.strftime('%Y-%m-%d').tolist(),
            )

            # Define the monthly DataFrames with named range codes
            monthly_dfs = {
                "Cashflow from Operations": ("o.devco.cfo.me", cf_ops),
                "Cashflow from Investments": ("o.devco.cfi.me", cf_inv),
                "Cashflow from Financing": ("o.devco.cff.me", cf_fin),
                "Escrow Schedule": ("o.devco.escrow.schedule.me", cf_escrow),
                "Monthly Timeline": (
                    "o.devco.model.timeline.me",
                    o_monthly_timeline,
                ),
                "Asset Net Cashflows": ("o.devco.asset.net.cf.me", _pa_net_cf_df),
            }

            _escrow_annual_sum = cf_escrow.T.groupby(level=0).sum(min_count=1).T
            _escrow_annual_last = cf_escrow.T.groupby(level=0).last().T
            _escrow_cumulative_rows = [
                "Cumulative Construction Progress",
                "Sales Payment Absorption",
                "Soft Cost Cumulative Requirement",
                "Hard Cost Cumulative Requirement",
            ]
            for _row in _escrow_cumulative_rows:
                if _row in _escrow_annual_sum.index and _row in _escrow_annual_last.index:
                    _escrow_annual_sum.loc[_row, :] = _escrow_annual_last.loc[_row, :]
            
            # Calculate annual sums for each DataFrame
            annual_dfs = {
                "Cashflow from Operations": (
                    "o.devco.cfo.ye",
                    cf_ops.T.groupby(level=0).sum(min_count=1).T,
                ),
                "Cashflow from Investments": (
                    "o.devco.cfi.ye",
                    cf_inv.T.groupby(level=0).sum(min_count=1).T,
                ),
                "Cashflow from Financing": (
                    "o.devco.cff.ye",
                    cf_fin.T.groupby(level=0).sum(min_count=1).T,
                ),
                "Escrow Schedule": (
                    "o.devco.escrow.schedule.ye",
                    _escrow_annual_sum,
                ),
                "Yearly Timeline": (
                    "o.devco.model.timeline.ye",
                    o_yearly_timeline,
                ),
            }
            
            # Build final output with JSON serialization
            excel_output = {
                "monthly_dfs": {
                    key: (code, fn_df_to_json_with_index(df))
                    for key, (code, df) in monthly_dfs.items()
                },
                "annual_dfs": {
                    key: (code, fn_df_to_json_with_index(df))
                    for key, (code, df) in annual_dfs.items()
                },
            }

            # ============================================================================================
            # JV OUTPUT â€” Base dataframes filtered by JV inclusion flag (sign-adjusted)
            # ============================================================================================

            # JV mask: zero out non-JV asset rows, keep full shape
            _jv_mask = _jv_asset_level_inclusion_flag.values[:, np.newaxis].astype(float)

            def _df_to_split_payload(df: pd.DataFrame, values=None, index=None, columns=None):
                """Serialize a DataFrame using split orientation without pandas to_dict overhead."""
                return {
                    "index": df.index.tolist() if index is None else index,
                    "columns": df.columns.tolist() if columns is None else columns,
                    "data": (df.values if values is None else values).tolist(),
                }

            def _coerce_numeric_values(df: pd.DataFrame):
                """Get numeric values with NaNs filled, avoiding DataFrame reconstruction where possible."""
                values = df.to_numpy(copy=True)
                if np.issubdtype(values.dtype, np.number):
                    np.nan_to_num(values, copy=False, nan=0.0)
                    return values
                return fn_replace_nan(df.copy(), 0.0).to_numpy(copy=True)

            def _serialize_masked_asset_df(df: pd.DataFrame, row_mask, sign=1):
                # Ensure float dtype before masked multiplication to avoid
                # int64 in-place casting errors and handle shape mismatches
                # for project-level (1xN) frames.
                values = _coerce_numeric_values(df).astype(np.float64, copy=False)
                mask_values = np.asarray(row_mask, dtype=np.float64)

                if mask_values.ndim == 0:
                    mask_values = mask_values.reshape(1, 1)
                elif mask_values.ndim == 1:
                    mask_values = mask_values.reshape(-1, 1)

                if mask_values.shape[0] == values.shape[0]:
                    values = values * mask_values
                elif mask_values.size == 1:
                    values = values * float(mask_values.reshape(-1)[0])
                # Else: row mask is asset-level but values are project-level.
                # Skip masking and preserve project-level payload as-is.
                if sign == -1:
                    values = -values
                return _df_to_split_payload(df, values=values)

            def _serialize_unmasked_item(item, sign=1):
                if isinstance(item, pd.Series):
                    values = item.to_numpy(copy=True)
                    if np.issubdtype(values.dtype, np.number):
                        np.nan_to_num(values, copy=False, nan=0.0)
                    else:
                        values = item.fillna(0.0).to_numpy(copy=True)
                    if sign == -1:
                        values = -values
                    return {
                        "index": [0],
                        "columns": item.index.tolist(),
                        "data": [values.tolist()],
                    }

                values = _coerce_numeric_values(item)
                if sign == -1:
                    values = -values
                return _df_to_split_payload(item, values=values)

            def _build_section_output(section_items, row_mask):
                section_output = {}
                for section_item in section_items:
                    if len(section_item) == 3:
                        item_name, item_df, item_sign = section_item
                        apply_row_mask = True
                    else:
                        item_name, item_df, item_sign, apply_row_mask = section_item

                    section_output[item_name] = (
                        _serialize_masked_asset_df(item_df, row_mask, item_sign)
                        if apply_row_mask
                        else _serialize_unmasked_item(item_df, item_sign)
                    )

                return section_output

            def _build_output_payload(row_mask):
                return {
                    section_name: _build_section_output(section_items, row_mask)
                    for section_name, section_items in output_section_mappings.items()
                }

            def _apply_asset_keep_mask(df: pd.DataFrame, keep_mask: np.ndarray) -> pd.DataFrame:
                values = _coerce_numeric_values(df).astype(np.float64)
                values *= keep_mask
                return pd.DataFrame(values, index=df.index, columns=df.columns)

            _landco_inclusion_flag = (
                pd.Series(Asset.AssetLifecycleModule.land_development)
                .eq("Yes")
                .reindex(o_sales_revenue.index, fill_value=False)
            )
            _devco_inclusion_flag = (
                pd.Series(Asset.AssetLifecycleModule.vertical_development)
                .eq("Yes")
                .reindex(o_sales_revenue.index, fill_value=False)
            )
            _assetco_inclusion_flag = (
                pd.Series(Asset.AssetLifecycleModule.asset_operations)
                .eq("Yes")
                .reindex(o_sales_revenue.index, fill_value=False)
            )

            # Internal transfer elimination masks.
            # 1) LandCo -> DevCo: eliminate DevCo land acquisition lines.
            # 2) DevCo -> AssetCo: eliminate DevCo sales lines.
            _landco_to_devco_internal_transfer_mask = (
                _landco_inclusion_flag & _devco_inclusion_flag
            ).values[:, np.newaxis].astype(float)
            _devco_to_assetco_internal_transfer_mask = (
                _devco_inclusion_flag & _assetco_inclusion_flag
            ).values[:, np.newaxis].astype(float)

            _devco_acquisition_keep_mask = 1.0 - _landco_to_devco_internal_transfer_mask
            _devco_sales_keep_mask = 1.0 - _devco_to_assetco_internal_transfer_mask

            _o_land_acquisition_flag_elim = _apply_asset_keep_mask(
                o_land_acquisition_flag,
                _devco_acquisition_keep_mask,
            )
            _o_land_acquisition_payment_profile_elim = _apply_asset_keep_mask(
                o_land_acquisition_payment_profile,
                _devco_acquisition_keep_mask,
            )
            _o_land_acquisition_cost_post_allocation_elim = _apply_asset_keep_mask(
                o_land_acquisition_cost_post_allocation,
                _devco_acquisition_keep_mask,
            )

            _o_sales_phasing_elim = _apply_asset_keep_mask(
                o_sales_phasing,
                _devco_sales_keep_mask,
            )
            _o_sales_revenue_elim = _apply_asset_keep_mask(
                o_sales_revenue,
                _devco_sales_keep_mask,
            )
            _o_handover_flag_elim = _apply_asset_keep_mask(
                o_handover_flag,
                _devco_sales_keep_mask,
            )
            _o_inflows_to_escrow_elim = _apply_asset_keep_mask(
                o_inflows_to_escrow,
                _devco_sales_keep_mask,
            )
            _o_total_escrow_release_elim = _apply_asset_keep_mask(
                o_total_escrow_release,
                _devco_sales_keep_mask,
            )
            _w_construction_progress_percent_elim = _apply_asset_keep_mask(
                w_construction_progress_percent,
                _devco_sales_keep_mask,
            )
            _w_cumulative_construction_progress_percent_elim = _apply_asset_keep_mask(
                w_cumulative_construction_progress_percent,
                _devco_sales_keep_mask,
            )
            _o_payment_absorption_elim = _apply_asset_keep_mask(
                o_payment_absorption,
                _devco_sales_keep_mask,
            )
            _o_transfer_to_retention_elim = _apply_asset_keep_mask(
                o_transfer_to_retention,
                _devco_sales_keep_mask,
            )
            _o_funds_available_for_soft_cost_elim = _apply_asset_keep_mask(
                o_funds_available_for_soft_cost,
                _devco_sales_keep_mask,
            )
            _o_funds_available_for_hard_cost_elim = _apply_asset_keep_mask(
                o_funds_available_for_hard_cost,
                _devco_sales_keep_mask,
            )
            _w_soft_opening_balance_elim = _apply_asset_keep_mask(
                w_soft_opening_balance,
                _devco_sales_keep_mask,
            )
            _w_soft_cost_total_availability_elim = _apply_asset_keep_mask(
                w_soft_cost_total_availability,
                _devco_sales_keep_mask,
            )
            _w_soft_cost_payment_requirement_elim = _apply_asset_keep_mask(
                w_soft_cost_payment_requirement,
                _devco_sales_keep_mask,
            )
            _w_soft_cost_cumulative_requirement_elim = _apply_asset_keep_mask(
                w_soft_cost_cumulative_requirement,
                _devco_sales_keep_mask,
            )
            _w_soft_cost_payment_from_escrow_elim = _apply_asset_keep_mask(
                w_soft_cost_payment_from_escrow,
                _devco_sales_keep_mask,
            )
            _w_additional_requirements_for_soft_cost_elim = _apply_asset_keep_mask(
                w_additional_requirements_for_soft_cost,
                _devco_sales_keep_mask,
            )
            _w_amount_available_after_soft_cost_and_reallocated_payment_elim = _apply_asset_keep_mask(
                w_amount_available_after_soft_cost_and_reallocated_payment,
                _devco_sales_keep_mask,
            )
            _w_last_year_release_soft_cost_elim = _apply_asset_keep_mask(
                w_last_year_release_soft_cost,
                _devco_sales_keep_mask,
            )
            _w_soft_closing_balance_elim = _apply_asset_keep_mask(
                w_soft_closing_balance,
                _devco_sales_keep_mask,
            )
            _w_hard_opening_balance_elim = _apply_asset_keep_mask(
                w_hard_opening_balance,
                _devco_sales_keep_mask,
            )
            _w_hard_cost_total_availability_elim = _apply_asset_keep_mask(
                w_hard_cost_total_availability,
                _devco_sales_keep_mask,
            )
            _w_hard_cost_payment_requirement_elim = _apply_asset_keep_mask(
                w_hard_cost_payment_requirement,
                _devco_sales_keep_mask,
            )
            _w_hard_cost_cumulative_requirement_elim = _apply_asset_keep_mask(
                w_hard_cost_cumulative_requirement,
                _devco_sales_keep_mask,
            )
            _w_hard_cost_payment_from_escrow_elim = _apply_asset_keep_mask(
                w_hard_cost_payment_from_escrow,
                _devco_sales_keep_mask,
            )
            _w_additional_requirements_for_hard_cost_elim = _apply_asset_keep_mask(
                w_additional_requirements_for_hard_cost,
                _devco_sales_keep_mask,
            )
            _w_amount_available_after_hard_cost_payment_elim = _apply_asset_keep_mask(
                w_amount_available_after_hard_cost_payment,
                _devco_sales_keep_mask,
            )
            _w_last_year_release_hard_cost_elim = _apply_asset_keep_mask(
                w_last_year_release_hard_cost,
                _devco_sales_keep_mask,
            )
            _w_hard_closing_balance_elim = _apply_asset_keep_mask(
                w_hard_closing_balance,
                _devco_sales_keep_mask,
            )
            _w_amount_available_for_reallocation_elim = _apply_asset_keep_mask(
                w_amount_available_for_reallocation,
                _devco_sales_keep_mask,
            )
            _w_reallocation_amount_elim = _apply_asset_keep_mask(
                w_reallocation_amount,
                _devco_sales_keep_mask,
            )
            _w_reallocated_funds_for_hard_cost_payment_elim = _apply_asset_keep_mask(
                w_reallocated_funds_for_hard_cost_payment,
                _devco_sales_keep_mask,
            )
            _w_additional_requirement_after_allocation_elim = _apply_asset_keep_mask(
                w_additional_requirement_after_allocation,
                _devco_sales_keep_mask,
            )
            _o_cash_inflow_from_off_plan_sales_elim = _apply_asset_keep_mask(
                o_cash_inflow_from_off_plan_sales,
                _devco_sales_keep_mask,
            )
            _o_escrow_setup_fees_elim = _apply_asset_keep_mask(
                o_escrow_setup_fees,
                _devco_sales_keep_mask,
            )
            _asset_sales_through_escrow_elim = _apply_asset_keep_mask(
                _asset_sales_through_escrow,
                _devco_sales_keep_mask,
            )
            _o_sales_collection_without_escrow_elim = _apply_asset_keep_mask(
                o_sales_collection_without_escrow,
                _devco_sales_keep_mask,
            )
            _o_forward_funding_cash_elim = _apply_asset_keep_mask(
                o_forward_funding_cash,
                _devco_sales_keep_mask,
            )
            _o_forward_sales_cash_elim = _apply_asset_keep_mask(
                o_forward_sales_cash,
                _devco_sales_keep_mask,
            )

            _o_serviced_land_acquisition_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(o_land_acquisition_cost_post_allocation)
                - _coerce_numeric_values(_o_land_acquisition_cost_post_allocation_elim),
                index=o_land_acquisition_cost_post_allocation.index,
                columns=o_land_acquisition_cost_post_allocation.columns,
            )

            _o_asset_sales_through_escrow_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(_asset_sales_through_escrow)
                - _coerce_numeric_values(_asset_sales_through_escrow_elim),
                index=_asset_sales_through_escrow.index,
                columns=_asset_sales_through_escrow.columns,
            )
            _o_asset_sales_collection_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(o_sales_collection_without_escrow)
                - _coerce_numeric_values(_o_sales_collection_without_escrow_elim),
                index=o_sales_collection_without_escrow.index,
                columns=o_sales_collection_without_escrow.columns,
            )
            _o_forward_funding_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(o_forward_funding_cash)
                - _coerce_numeric_values(_o_forward_funding_cash_elim),
                index=o_forward_funding_cash.index,
                columns=o_forward_funding_cash.columns,
            )
            _o_forward_sales_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(o_forward_sales_cash)
                - _coerce_numeric_values(_o_forward_sales_cash_elim),
                index=o_forward_sales_cash.index,
                columns=o_forward_sales_cash.columns,
            )
            _o_asset_sales_internal_transfer = pd.DataFrame(
                _coerce_numeric_values(_o_asset_sales_through_escrow_internal_transfer)
                + _coerce_numeric_values(_o_asset_sales_collection_internal_transfer)
                + _coerce_numeric_values(_o_forward_funding_internal_transfer)
                + _coerce_numeric_values(_o_forward_sales_internal_transfer),
                index=o_forward_sales_cash.index,
                columns=o_forward_sales_cash.columns,
            )

            output_section_mappings = {
                "Support Workings": [
                    ("Land Acquisition Flag", o_land_acquisition_flag, 1),
                    ("Land Acquisition Cost", o_land_acquisition_cost_post_allocation, 1),
                    ("Handover Flag", o_handover_flag, 1),
                    ("Sales Phasing", o_sales_phasing, 1),
                    ("Sales Revenue", o_sales_revenue, 1),
                    ("On-plan Sales Collection", o_sales_collection_without_escrow, 1),
                    ("Inflows to Escrow", o_inflows_to_escrow, 1),
                    ("Escrow Release and Payments", o_total_escrow_release, 1),
                    ("Forward Funding Flag", pd.DataFrame(w_is_forward_funding.values.reshape(-1, 1) * np.ones((1, len(_template_columns))), index=_template_index, columns=_template_columns), 1),
                    ("Forward Funding Cash", o_forward_funding_cash, 1),
                    ("Forward Sales Flag", pd.DataFrame(w_is_forward_sales.values.reshape(-1, 1) * np.ones((1, len(_template_columns))), index=_template_index, columns=_template_columns), 1),
                    ("Forward Sales Cash", o_forward_sales_cash, 1),
                    ("Land Acquisition Cost Phasing", o_land_acquisition_payment_profile, 1),
                    ("Land Acquisition Cost (Elimination)", o_land_acquisition_cost_post_allocation, 1),
                    ("Serviced Land Acquisition", _o_serviced_land_acquisition_internal_transfer, 1),
                    ("Asset Sales", _o_asset_sales_internal_transfer, 1),
                    ("Vertical Construction S-Curve Phasing", w_vertical_construction_phasing, 1),
                    ("Phased Vertical Amount", w_phased_vertical_amount, 1),
                    ("Vertical Construction Cost", o_vertical_construction_cost_post_allocation, 1),
                    ("Soft Cost", o_total_soft_cost_post_allocation, 1),
                    ("Total Development Cost", o_vertical_construction_cost_post_allocation + o_total_soft_cost_post_allocation, 1),
                    # --- Debt / Financing Support Workings ---
                    # Asset Term Loan (asset-level 2D)
                    ("Asset Term Loan - Debt Drawdown", o_asset_term_loan_drawdown, 1),
                    ("Asset Term Loan - Capitalized Interest", o_asset_term_loan_cap_interest, 1),
                    ("Asset Term Loan - Principal Repayment", o_asset_term_loan_principal, 1),
                    ("Asset Term Loan - Balloon Payment", o_asset_term_loan_balloon, 1),
                    ("Asset Term Loan - Interest Payment", o_asset_term_loan_interest_expensed, 1),
                    ("Asset Term Loan - Arrangement Fees", o_asset_term_loan_arrangement_fees, 1),
                    # Asset Revolver (asset-level 2D)
                    ("Asset Revolver - Debt Drawdown", w_asset_debt_revolver_debt_withdrawal, 1),
                    ("Asset Revolver - Capitalized Interest", w_asset_debt_revolver_capitalization_of_interest, 1),
                    ("Asset Revolver - Debt Repayment", w_asset_debt_revolver_debt_repayment, 1),
                    ("Asset Revolver - Arrangement Fees", w_asset_debt_revolver_debt_arrangement_fees, 1),
                    ("Asset Revolver - Commitment Fees Payment", w_asset_debt_revolver_debt_commitment_fees, 1),
                    # Project Term Loan (project-level 1D â†’ broadcast to 2D)
                    ("Project Term Loan - Debt Drawdown", pd.DataFrame(o_project_term_loan_drawdown.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Term Loan - Capitalized Interest", pd.DataFrame(o_project_term_loan_cap_interest.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Term Loan - Principal Repayment", pd.DataFrame(o_project_term_loan_principal.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Term Loan - Balloon Payment", pd.DataFrame(o_project_term_loan_balloon.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Term Loan - Interest Payment", pd.DataFrame(o_project_term_loan_interest_expensed.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Term Loan - Arrangement Fees", pd.DataFrame(o_project_term_loan_arrangement_fees.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    # Project Revolver (project-level 1D â†’ broadcast to 2D)
                    ("Project Revolver - Debt Drawdown", pd.DataFrame(o_project_revolver_drawdown.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Revolver - Capitalized Interest", pd.DataFrame(o_project_revolver_cap_interest.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Revolver - Debt Repayment", pd.DataFrame(o_project_revolver_repayment.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Revolver - Arrangement Fees", pd.DataFrame(o_project_revolver_arrangement_fees.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    ("Project Revolver - Commitment Fees Payment", pd.DataFrame(o_project_revolver_commitment_fees.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                    # Equity (asset-level 2D + project-level 1D â†’ broadcast)
                    ("Asset Equity Injection", o_asset_equity_injection, 1),
                    ("Project Equity Infusion", pd.DataFrame(o_equity_infusion.values.reshape(1, -1), index=[0], columns=_template_columns), 1),
                ],
                "Escrow Schedule": [
                    ("Construction Progress", _w_construction_progress_percent_elim, 1),
                    ("Cumulative Construction Progress", _w_cumulative_construction_progress_percent_elim, 1),
                    ("Sales Payment Absorption", _o_payment_absorption_elim, 1),
                    ("Inflows to Escrow", _o_inflows_to_escrow_elim, 1),
                    ("Funds Available for Soft Cost", _o_funds_available_for_soft_cost_elim, 1),
                    ("Funds Available for Hard Cost", _o_funds_available_for_hard_cost_elim, 1),
                    ("Transfer to Retention", _o_transfer_to_retention_elim, 1),
                    ("Soft Opening Balance", _w_soft_opening_balance_elim, 1),
                    ("Soft Inflows", _o_funds_available_for_soft_cost_elim, 1),
                    ("Soft Cost Total Availability", _w_soft_cost_total_availability_elim, 1),
                    ("Soft Cost Payment Requirement", _w_soft_cost_payment_requirement_elim, 1),
                    ("Soft Cost Cumulative Requirement", _w_soft_cost_cumulative_requirement_elim, 1),
                    ("Soft Cost Payment from Escrow", _w_soft_cost_payment_from_escrow_elim, 1),
                    ("Soft Additional Requirement", _w_additional_requirements_for_soft_cost_elim, 1),
                    ("Soft Amount Available After Reallocation", _w_amount_available_after_soft_cost_and_reallocated_payment_elim, 1),
                    ("Soft Last Year Release", _w_last_year_release_soft_cost_elim, 1),
                    ("Soft Closing Balance", _w_soft_closing_balance_elim, 1),
                    ("Hard Opening Balance", _w_hard_opening_balance_elim, 1),
                    ("Hard Inflows", _o_funds_available_for_hard_cost_elim, 1),
                    ("Hard Cost Total Availability", _w_hard_cost_total_availability_elim, 1),
                    ("Hard Cost Payment Requirement", _w_hard_cost_payment_requirement_elim, 1),
                    ("Hard Cost Cumulative Requirement", _w_hard_cost_cumulative_requirement_elim, 1),
                    ("Hard Cost Payment from Escrow", _w_hard_cost_payment_from_escrow_elim, 1),
                    ("Hard Additional Requirement", _w_additional_requirements_for_hard_cost_elim, 1),
                    ("Hard Amount Available After Payment", _w_amount_available_after_hard_cost_payment_elim, 1),
                    ("Hard Last Year Release", _w_last_year_release_hard_cost_elim, 1),
                    ("Hard Closing Balance", _w_hard_closing_balance_elim, 1),
                    ("Amount Available for Reallocation", _w_amount_available_for_reallocation_elim, 1),
                    ("Reallocation Amount", _w_reallocation_amount_elim, 1),
                    ("Reallocated Funds for Hard Cost Payment", _w_reallocated_funds_for_hard_cost_payment_elim, 1),
                    ("Additional Requirement After Allocation", _w_additional_requirement_after_allocation_elim, 1),
                    ("Off-plan Cash Inflow", _o_cash_inflow_from_off_plan_sales_elim, 1),
                    ("Escrow Setup Fees", _o_escrow_setup_fees_elim, -1),
                ],
                "Cashflow from Operations": [
                    ("Asset Sales through Escrow (Off-plan + On-plan)", _asset_sales_through_escrow_elim, 1),
                    ("Asset Sales through Collection (Post-Dev)", _o_sales_collection_without_escrow_elim, 1),
                    ("Forward Funding", _o_forward_funding_cash_elim, 1),
                    ("Forward Sales", _o_forward_sales_cash_elim, 1),
                    ("Escrow Setup Fees", o_escrow_setup_fees, -1),
                    ("Sales Cost", o_sales_cost, -1),
                    ("Marketing Cost", o_marketing_cost, -1),
                    ("DLP Insurance", o_dlp_insurance, -1),
                    ("Void Period Opex", o_void_period_opex, -1),
                    ("PA Recovery", o_pa_recovery, 1),
                    ("Salaries Expenses", o_coh_salaries_expensed_post_allocation, -1),
                    ("IT Services Expenses", o_coh_it_services_expensed_post_allocation, -1),
                    ("Office Rent & Utilities Expenses", o_coh_office_rent_expensed_post_allocation, -1),
                    ("Professional Services Expenses", o_coh_professional_services_expensed_post_allocation, -1),
                    ("Marketing Expenses (COH)", o_coh_marketing_expensed_post_allocation, -1),
                    ("Sales Cost Expenses (COH)", o_coh_sales_cost_expensed_post_allocation, -1),
                    ("Additional Expenses", o_coh_additional_expensed_post_allocation, -1),
                    ("Government Subsidies", o_government_subsidies_post_allocation, 1),
                    ("Other Income 1", o_other_income_1_post_allocation, 1),
                    ("Other Income 2", o_other_income_2_post_allocation, 1),
                    ("Other Expense 1", o_other_expense_1_post_allocation, -1),
                    ("Other Expense 2", o_other_expense_2_post_allocation, -1),
                    ("Other Expense 3", o_other_expense_3_post_allocation, -1),
                ],
                "Cashflow from Investments": [
                    ("Land Acquisition Cost Payment", _o_land_acquisition_cost_post_allocation_elim, -1),
                    ("Legal Cost", o_legal_cost_post_allocation, -1),
                    ("Agency Cost", o_agency_cost_post_allocation, -1),
                    ("Technical Cost", o_technical_cost_post_allocation, -1),
                    ("Valuation Cost", o_valuation_cost_post_allocation, -1),
                    ("Due Diligence Cost", o_due_diligence_cost_post_allocation, -1),
                    ("Vertical Construction Cost", o_vertical_construction_cost_post_allocation, -1),
                    ("Public Amenity Cost", o_pa_allocation, -1),
                    ("CEC Cost", o_cec_allocation, -1),
                    ("Canal Cost", o_canal_allocation, -1),
                    ("Design Cost", o_design_cost_post_allocation, -1),
                    ("Permitting Cost", o_permitting_cost_post_allocation, -1),
                    ("Supervision Cost", o_supervision_cost_post_allocation, -1),
                    ("Project Management Cost", o_pm_fees_post_allocation, -1),
                    ("Contingency Cost Payment", o_contingency_cost_post_allocation, -1),
                    ("Capitalized Salaries", o_coh_salaries_capitalized_post_allocation, -1),
                    ("Capitalized IT Services", o_coh_it_services_capitalized_post_allocation, -1),
                    ("Capitalized Office Rent & Utilities", o_coh_office_rent_capitalized_post_allocation, -1),
                    ("Capitalized Professional Services", o_coh_professional_services_capitalized_post_allocation, -1),
                    ("Capitalized Marketing (COH)", o_coh_marketing_capitalized_post_allocation, -1),
                    ("Capitalized Sales Cost (COH)", o_coh_sales_cost_capitalized_post_allocation, -1),
                    ("Capitalized Additional Expenses", o_coh_additional_capitalized_post_allocation, -1),
                ],
                "Cashflow from Financing": [
                    ("Asset Level Term Loan - Principal Drawn", o_asset_term_loan_drawdown, 1, True),
                    ("Asset Level Term Loan - Principal Repaid", o_asset_term_loan_principal + o_asset_term_loan_balloon, 1, True),
                    ("Asset Level Term Loan - Interest Paid", o_asset_term_loan_interest_expensed, -1, True),
                    ("Asset Level Term Loan - Arrangement Fees", o_asset_term_loan_arrangement_fees, -1, True),
                    ("Asset Level Revolver - Principal Drawn", w_asset_debt_revolver_debt_withdrawal, 1, True),
                    ("Asset Level Revolver - Principal Repaid", w_asset_debt_revolver_debt_repayment, 1, True),
                    ("Asset Level Revolver - Fees and Interest Paid", w_asset_debt_revolver_interest_expense + w_asset_debt_revolver_debt_arrangement_fees + w_asset_debt_revolver_debt_commitment_fees, -1, True),
                    ("Project Level Term Loan - Principal Drawn", o_project_term_loan_drawdown, 1, False),
                    ("Project Level Term Loan - Principal Repaid", o_project_term_loan_principal + o_project_term_loan_balloon, 1, False),
                    ("Project Level Term Loan - Interest Paid", o_project_term_loan_interest_expensed, -1, False),
                    ("Project Level Term Loan - Arrangement Fees", o_project_term_loan_arrangement_fees, -1, False),
                    ("Project Level Revolver - Principal Drawn", o_project_revolver_drawdown, 1, False),
                    ("Project Level Revolver - Principal Repaid", o_project_revolver_repayment, 1, False),
                    ("Project Level Revolver - Fees and Interest Paid", o_project_revolver_interest_expense + o_project_revolver_arrangement_fees + o_project_revolver_commitment_fees, -1, False),
                    ("Equity Injection - Asset Level", o_asset_equity_injection, 1, True),
                    ("Equity Injection - Project Level", o_equity_infusion, 1, False),
                ],
            }

            _timeline_payload = _df_to_split_payload(o_monthly_timeline)
            _global_assumptions_payload = class_to_dict(Global)
            _asset_assumptions_payload = class_to_dict(Asset)

            jv_output = _build_output_payload(_jv_mask)
            jv_output["Timeline"] = _timeline_payload
            jv_output["global_assumptions"] = _global_assumptions_payload
            jv_output["asset_assumptions"] = _asset_assumptions_payload

            # ============================================================================================
            # CONSOLIDATED OUTPUT â€” Base dataframes filtered by JV exclusion flag (sign-adjusted)
            # ============================================================================================

            _jv_exclusion_mask = (~_jv_asset_level_inclusion_flag).values[:, np.newaxis].astype(float)

            consolidation_output = _build_output_payload(_jv_exclusion_mask)
            consolidation_output["Timeline"] = _timeline_payload
            consolidation_output["global_assumptions"] = _global_assumptions_payload
            consolidation_output["asset_assumptions"] = _asset_assumptions_payload

            timing_summary = _finalize_timing_summary("Final response assembly")
            print(timing_summary["summary_text"])

            return {
                "exceloutput": excel_output
            }
            
        except Exception as e:
            print(f"Error in fn_copy_output_template_tab: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

        # ========================================================================
        # FINAL OUTPUT ASSEMBLY
        # ========================================================================
        # Compile all calculated DataFrames into structured output
        # ========================================================================
        
        print(f"\n{'='*80}")
        print(f"DevCo Model COMPLETED SUCCESSFULLY")
        print(f"Total Execution Time: {time.time() - _start_time:.2f}s")
        print(f"Assets Processed: {_n_assets}")
        print(f"Monthly Periods: {_n_periods}")
        print(f"{'='*80}\n")

    except Exception as e:
        print(f"Failed to initialise values {e}\n{traceback.format_exc()}")
        return None


def fninitialising_all_values(payload):
    try:
            from mainapp.utils.v3.sensitivity_utils.devco_sensitivity import (
                fn_run_devco_sensitivity,
                fn_strip_sensitivity_result,
            )
            from mainapp.utils.v3.sensitivity_utils.common import (
                export_sensitivity_to_excel,
            )
            
            _ALLOWED_TYPES = {"Vertical Construction Cost", "Developed Units Sales Price"}

            def _get_payload_values(name):
                for item in payload:
                    if item.get("name") == name:
                        vals = item.get("values", [[]])
                        result = {v for row in vals for v in row if isinstance(v, str) and v != ""}
                        print(f"[_get_payload_values] {name} = {result}")
                        return result
                print(f"[_get_payload_values] {name} = set() (not found)")
                return set()

            _sensitivity_types = _get_payload_values("a.devco.sensitivity")
            _goal_seek_types   = _get_payload_values("a.devco.goal.seek")

            if not (_sensitivity_types & _ALLOWED_TYPES) and not (_goal_seek_types & _ALLOWED_TYPES):
                print(f"There is not a valid sensitivity or goal seek type in the payload. Allowed types are: {_ALLOWED_TYPES}. Received sensitivity types: {_sensitivity_types}, goal seek types: {_goal_seek_types}. Skipping sensitivity and goal seek execution.")
                return None

            # Sensitivity and goal seek are independent — each checks its own values
            _can_run_sensitivity = bool(_sensitivity_types & _ALLOWED_TYPES)
            _can_run_goal_seek   = bool(_goal_seek_types & _ALLOWED_TYPES)

            all_records = []
            if _can_run_sensitivity:
                raw_results = fn_run_devco_sensitivity(payload)
                if raw_results is None:
                    print(f"[sensitivity] fn_run_devco_sensitivity returned None — skipping sensitivity, goal seek may still run")
                    raw_results = []

                sensitivity_section = [
                    {
                        "scenario": item["scenario"],
                        "result": fn_strip_sensitivity_result(item["result"]),
                    }
                    for item in raw_results
                ]

                import json as _json
                import pandas as _pd

                import re as _re
                def _parse_scenario(name):
                    parts = name.split("__", 1)
                    def _split(s):
                        m = _re.match(r'^(.+)_([-+]?\d+(?:\.\d+)?%)$', s.strip())
                        return (m.group(1).strip(), m.group(2)) if m else (s.strip(), "")
                    l1, p1 = _split(parts[0]) if parts else ("", "")
                    l2, p2 = _split(parts[1]) if len(parts) > 1 else ("", "")
                    return l1, p1, l2, p2

                for _k, _item in enumerate(sensitivity_section, 1):
                    _scenario = _item["scenario"]
                    _scenario_code = f"S{_k:02d}"
                    _param1, _param1_pct, _param2, _param2_pct = _parse_scenario(_scenario)
                    _res = _item.get("result")
                    if not isinstance(_res, dict):
                        continue
                    try:
                        _, _json_df = _res["exceloutput"]["monthly_dfs"]["Asset Net Cashflows"]
                        _index = [("" if isinstance(i, float) else i) for i in _json_df["index"]]
                        _df = _pd.DataFrame(
                            data=_json_df["data"],
                            index=_index,
                            columns=_json_df["columns"],
                        )
                        _df.index.name = "asset"
                        _df = _df.reset_index()
                        _melted = _df.melt(id_vars="asset", var_name="period", value_name="value")
                        _melted = _melted[(_melted["asset"] != "") & (_melted["value"] != 0.0)]
                        _melted["scenario"] = _scenario
                        _melted["scenario_code"] = _scenario_code
                        _melted["param1"] = _param1
                        _melted["param1_pct"] = _param1_pct
                        _melted["param2"] = _param2
                        _melted["param2_pct"] = _param2_pct
                        all_records.extend(
                            _json.loads(_melted.to_json(orient="records"))
                        )
                    except (KeyError, TypeError, ValueError):
                        pass
            else:
                print(f"Sensitivity skipped: no sensitivity types match _ALLOWED_TYPES. sensitivity={_sensitivity_types}")
            # export_sensitivity_to_excel(raw_results, "devco_sensitivity_export.xlsx")
            if _can_run_goal_seek:
                from mainapp.utils.v3.sensitivity_utils.goal_seek import fn_run_devco_goal_seek_iterative
                base_result = wrapper_for_vars(payload)
                if base_result is None:
                    print(f"[goal seek] base_result is None — skipping goal seek, returning sensitivity data only")
                    goal_seek_result = None
                else:
                    goal_seek_result = fn_run_devco_goal_seek_iterative(payload, base_result)
                    if goal_seek_result is None:
                        print(f"[goal seek] fn_run_devco_goal_seek_iterative returned None — returning sensitivity data only")
            else:
                print(f"Goal seek skipped: no goal seek types match _ALLOWED_TYPES. goal_seek={_goal_seek_types}")
                goal_seek_result = None

            if goal_seek_result is None and not all_records:
                print(f"[devco] Both goal_seek and all_records are empty — returning None")
                return None

            return { "goal_seek": goal_seek_result, "all_records": all_records}

    except Exception as e:
        print(f"Error in fninitialising_all_values: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise