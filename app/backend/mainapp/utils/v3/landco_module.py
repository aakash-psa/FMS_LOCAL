# ============================================================================
# LANDCO CASHFLOW MODULE
# ============================================================================
# Module: landco_12_cashflow_module.py
# Description: Calculates cash flows for land development projects including
#              acquisition, infrastructure, soft costs, revenue, and financing.
# Version: 2.0
# Last Updated: 2026-02-02
# ============================================================================
#
# MODULE STRUCTURE:
# ============================================================================
#   MODULE 0: IMPORTS AND DEPENDENCIES
#   MODULE 1: GLOBAL CLASS DEFINITIONS
#   MODULE 2: ASSET CLASS DEFINITIONS
#   MODULE 3: MAIN CALCULATIONS
#
#   SUB-MODULES (within MODULE 3):
#     3.1  - Input Processing Functions
#     3.2  - Utility Functions (Timeline, Profiles, Escalation)
#     3.3  - Generic Calculation Functions
#     3.4  - Acquisition & Transaction Cost Functions
#     3.5  - Infrastructure Cost Functions & Calculations
#     3.6  - Soft Cost & Contingency Functions & Calculations
#     3.7  - Land Acquisition Calculations
#     3.8  - Revenue Module (Land Lease, Land Bank, Land Sale)
#     3.9  - Community Operations Module (Amanah, ROSHN)
#     3.10 - Corporate Overhead Functions
#     3.11 - Other Income and Expenses
#     3.12 - Escrow Module Calculations
#     3.13 - Financing Module
#       3.13.1 - Asset Level Financing (Debt Revolver)
#       3.13.2 - Project Level Financing (Term Loan, Revolver, Equity)
#     3.14 - Cashflow Statement Generation (CFO, CFI, CFF)
#     3.15 - Data Normalization for Dashboard
#
# EXPORT FLAGS:
# ============================================================================
#   Each submodule has an export flag in _EXPORT_FLAGS dictionary that can be
#   set to True to export intermediate calculations to Excel for debugging.
#   Available exports: land_acquisition, infrastructure, soft_cost_contingency,
#   land_lease, land_bank, land_sale, leasing_and_disposal_cost, escrow,
#   community_operations, corporate_overhead, other_income_and_expenses,
#   on_plan_sales_collection, asset_level_financing, project_level_financing,
#   cashflow_dataframes, cashflow_statements
#
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
#                            Example: o_land_acquisition_cost
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
import datetime as dt
from calendar import month
from math import perm
import warnings
import math


# ============================================================================
# EXECUTOR MANAGER: SINGLETON THREAD POOL
# ============================================================================

class ExecutorManager:
    """Singleton managing a shared ThreadPoolExecutor for the module."""
    _thread_executor = None
    _thread_lock = threading.Lock()

    @classmethod
    def get_thread_executor(cls, max_workers=None):
        if cls._thread_executor is None:
            with cls._thread_lock:
                if cls._thread_executor is None:
                    workers = max_workers or max(1, min(8, (os.cpu_count() or 1)))
                    cls._thread_executor = ThreadPoolExecutor(max_workers=workers)
        return cls._thread_executor

    @classmethod
    def shutdown(cls, wait=True):
        with cls._thread_lock:
            if cls._thread_executor is not None:
                cls._thread_executor.shutdown(wait=wait)
                cls._thread_executor = None


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
# Contains global configuration classes for model assumptions, valuation,
# project inputs, acquisition, infrastructure, soft costs, and financing.
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

    class ValuationAssumptions:
        npv_calculation_start_option = None
        npv_calculation_start_date_override = None
        npv_calculation_start_date = None
        discount_rate = None
        mirr_finance_rate = None
        mirr_reinvestment_rate = None
        irr_calculation_option = None

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

    class AcquisitionInputs:
        acquisition_counterparty = None
        acquired_land_type = None
        acquisition_date_selection_input = None
        acquisition_date = None
        acquisition_price = None
        payment_type = None
        payment_start_date = None
        pre_defined_profile = None
        escalation_profile = None

    class AcquisitionTransactionCost:
        legal_cost_calculation_approach = None
        legal_cost_allocation_basis = None
        legal_cost_cost_basis = None
        legal_cost_ad_hoc_amount = None
        legal_cost_cost_percent = None
        legal_cost_cost_per_sqm = None
        legal_cost_escalation_profile = None

        agency_cost_calculation_approach = None
        agency_cost_allocation_basis = None
        agency_cost_cost_basis = None
        agency_cost_ad_hoc_amount = None
        agency_cost_cost_percent = None
        agency_cost_cost_per_sqm = None
        agency_cost_escalation_profile = None

        technical_cost_calculation_approach = None
        technical_cost_allocation_basis = None
        technical_cost_cost_basis = None
        technical_cost_ad_hoc_amount = None
        technical_cost_cost_percent = None
        technical_cost_cost_per_sqm = None
        technical_cost_escalation_profile = None

        valuation_cost_calculation_approach = None
        valuation_cost_allocation_basis = None
        valuation_cost_cost_basis = None
        valuation_cost_ad_hoc_amount = None
        valuation_cost_cost_percent = None
        valuation_cost_cost_per_sqm = None
        valuation_cost_escalation_profile = None

        due_diligence_cost_calculation_approach = None
        due_diligence_cost_allocation_basis = None
        due_diligence_cost_cost_basis = None
        due_diligence_cost_ad_hoc_amount = None
        due_diligence_cost_cost_percent = None
        due_diligence_cost_cost_per_sqm = None
        due_diligence_cost_escalation_profile = None

        real_estate_transaction_tax_calculation_approach = None
        real_estate_transaction_tax_allocation_basis = None
        real_estate_transaction_tax_cost_basis = None
        real_estate_transaction_tax_ad_hoc_amount = None
        real_estate_transaction_tax_cost_percent = None
        real_estate_transaction_tax_cost_per_sqm = None
        real_estate_transaction_tax_escalation_profile = None

        municipal_fees_calculation_approach = None
        municipal_fees_allocation_basis = None
        municipal_fees_cost_basis = None
        municipal_fees_ad_hoc_amount = None
        municipal_fees_cost_percent = None
        municipal_fees_cost_per_sqm = None
        municipal_fees_escalation_profile = None

    class InfrastructureCosts:
        primary_infrastructure_calculation_approach = None
        primary_infrastructure_allocation_basis = None
        primary_infrastructure_cost_basis = None
        primary_infrastructure_ad_hoc_amount = None
        primary_infrastructure_cost_percent = None
        primary_infrastructure_cost_per_sqm = None
        primary_infrastructure_phasing = None
        primary_infrastructure_start_date = None
        primary_infrastructure_escalation_profile = None

        secondary_infrastructure_calculation_approach = None
        secondary_infrastructure_allocation_basis = None
        secondary_infrastructure_cost_basis = None
        secondary_infrastructure_ad_hoc_amount = None
        secondary_infrastructure_cost_percent = None
        secondary_infrastructure_cost_per_sqm = None
        secondary_infrastructure_phasing = None
        secondary_infrastructure_start_date = None
        secondary_infrastructure_escalation_profile = None

    class SoftCosts:
        design_cost_calculation_approach = None
        design_cost_allocation_basis = None
        design_cost_cost_basis = None
        design_cost_ad_hoc_amount = None
        design_cost_cost_percent = None
        design_cost_cost_per_sqm = None
        design_cost_phasing = None
        design_cost_start_date = None
        design_cost_escalation_profile = None

        permitting_cost_calculation_approach = None
        permitting_cost_allocation_basis = None
        permitting_cost_cost_basis = None
        permitting_cost_ad_hoc_amount = None
        permitting_cost_cost_percent = None
        permitting_cost_cost_per_sqm = None
        permitting_cost_phasing = None
        permitting_cost_start_date = None
        permitting_cost_escalation_profile = None

        supervision_cost_calculation_approach = None
        supervision_cost_allocation_basis = None
        supervision_cost_cost_basis = None
        supervision_cost_ad_hoc_amount = None
        supervision_cost_cost_percent = None
        supervision_cost_cost_per_sqm = None
        supervision_cost_phasing = None
        supervision_cost_start_date = None
        supervision_cost_escalation_profile = None

        project_management_cost_calculation_approach = None
        project_management_cost_allocation_basis = None
        project_management_cost_cost_basis = None
        project_management_cost_ad_hoc_amount = None
        project_management_cost_cost_percent = None
        project_management_cost_cost_per_sqm = None
        project_management_cost_phasing = None
        project_management_cost_start_date = None
        project_management_cost_escalation_profile = None

    class ContingencyCosts:
        contingency_cost_calculation_approach = None
        contingency_cost_allocation_basis = None
        contingency_cost_cost_basis = None
        contingency_cost_ad_hoc_amount = None
        contingency_cost_cost_percent = None
        contingency_cost_cost_per_sqm = None
        contingency_cost_phasing = None
        contingency_cost_start_date = None
        contingency_cost_escalation_profile = None

    class LandSalesInputs:
        sales_price = None
        sales_start_date = None
        sales_phasing_option = None
        sales_phasing_profile = None
        escalation_profile = None

    class LandLeaseInputs:
        lease_calculation_basis = None
        annual_lease_amount = None
        annual_yield = None
        lease_start_date = None
        grace_period = None
        escalation_profile = None

    class LandBankInputs:
        holding_period = None
        escalation_profile = None

    class CorporateOverheadCost:
        salaries_cost_basis = None
        salaries_design_cost_inclusion = None
        salaries_permitting_cost_inclusion = None
        salaries_supervision_cost_inclusion = None
        salaries_project_management_cost_inclusion = None
        salaries_contingency_cost_inclusion = None
        salaries_cost_percent = None
        salaries_capitalization_percent = None

        it_services_cost_basis = None
        it_services_design_cost_inclusion = None
        it_services_permitting_cost_inclusion = None
        it_services_supervision_cost_inclusion = None
        it_services_project_management_cost_inclusion = None
        it_services_contingency_cost_inclusion = None
        it_services_cost_percent = None
        it_services_capitalization_percent = None

        office_rent_and_utitlities_cost_basis = None
        office_rent_and_utitlities_design_cost_inclusion = None
        office_rent_and_utitlities_permitting_cost_inclusion = None
        office_rent_and_utitlities_supervision_cost_inclusion = None
        office_rent_and_utitlities_project_management_cost_inclusion = None
        office_rent_and_utitlities_contingency_cost_inclusion = None
        office_rent_and_utitlities_cost_percent = None
        office_rent_and_utitlities_capitalization_percent = None

        professional_services_cost_basis = None
        professional_services_design_cost_inclusion = None
        professional_services_permitting_cost_inclusion = None
        professional_services_supervision_cost_inclusion = None
        professional_services_project_management_cost_inclusion = None
        professional_services_contingency_cost_inclusion = None
        professional_services_cost_percent = None
        professional_services_capitalization_percent = None

        marketing_cost_basis = None
        marketing_design_cost_inclusion = None
        marketing_permitting_cost_inclusion = None
        marketing_supervision_cost_inclusion = None
        marketing_project_management_cost_inclusion = None
        marketing_contingency_cost_inclusion = None
        marketing_cost_percent = None
        marketing_capitalization_percent = None

        sales_cost_cost_basis = None
        sales_cost_design_cost_inclusion = None
        sales_cost_permitting_cost_inclusion = None
        sales_cost_supervision_cost_inclusion = None
        sales_cost_project_management_cost_inclusion = None
        sales_cost_contingency_cost_inclusion = None
        sales_cost_cost_percent = None
        sales_cost_capitalization_percent = None

        additional_expenses_cost_basis = None
        additional_expenses_design_cost_inclusion = None
        additional_expenses_permitting_cost_inclusion = None
        additional_expenses_supervision_cost_inclusion = None
        additional_expenses_project_management_cost_inclusion = None
        additional_expenses_contingency_cost_inclusion = None
        additional_expenses_cost_percent = None
        additional_expenses_capitalization_percent = None

    class CommunityOperationsAmanah:
        residential_units_single_family_cost_per_sqm = None
        residential_units_single_family_cost_basis = None
        residential_units_single_family_cost_start_option = None
        residential_units_single_family_cost_start_date = None
        residential_units_single_family_cost_duration = None
        residential_units_single_family_payment_frequency = None
        residential_units_single_family_escalation_profile = None
        residential_units_single_family_recovery_duration = None
        residential_units_single_family_recovery_advance = None
        residential_units_single_family_default_rate = None

        residential_units_multi_family_cost_per_sqm = None
        residential_units_multi_family_cost_basis = None
        residential_units_multi_family_cost_start_option = None
        residential_units_multi_family_cost_start_date = None
        residential_units_multi_family_cost_duration = None
        residential_units_multi_family_payment_frequency = None
        residential_units_multi_family_escalation_profile = None
        residential_units_multi_family_recovery_duration = None
        residential_units_multi_family_recovery_advance = None
        residential_units_multi_family_default_rate = None

        residential_land_single_family_cost_per_sqm = None
        residential_land_single_family_cost_basis = None
        residential_land_single_family_cost_start_option = None
        residential_land_single_family_cost_start_date = None
        residential_land_single_family_cost_duration = None
        residential_land_single_family_payment_frequency = None
        residential_land_single_family_escalation_profile = None
        residential_land_single_family_recovery_duration = None
        residential_land_single_family_recovery_advance = None
        residential_land_single_family_default_rate = None

        residential_land_multi_family_cost_per_sqm = None
        residential_land_multi_family_cost_basis = None
        residential_land_multi_family_cost_start_option = None
        residential_land_multi_family_cost_start_date = None
        residential_land_multi_family_cost_duration = None
        residential_land_multi_family_payment_frequency = None
        residential_land_multi_family_escalation_profile = None
        residential_land_multi_family_recovery_duration = None
        residential_land_multi_family_recovery_advance = None
        residential_land_multi_family_default_rate = None

        commercial_land_cost_per_sqm = None
        commercial_land_cost_basis = None
        commercial_land_cost_start_option = None
        commercial_land_cost_start_date = None
        commercial_land_cost_duration = None
        commercial_land_payment_frequency = None
        commercial_land_escalation_profile = None
        commercial_land_recovery_duration = None
        commercial_land_recovery_advance = None
        commercial_land_default_rate = None

        # Category 4: Retail
        retail_cost_per_sqm = None
        retail_cost_basis = None
        retail_cost_start_option = None
        retail_cost_start_date = None
        retail_cost_duration = None
        retail_payment_frequency = None
        retail_escalation_profile = None
        retail_recovery_duration = None
        retail_recovery_advance = None
        retail_default_rate = None

        # Category 5: Schools
        schools_cost_per_sqm = None
        schools_cost_basis = None
        schools_cost_start_option = None
        schools_cost_start_date = None
        schools_cost_duration = None
        schools_payment_frequency = None
        schools_escalation_profile = None
        schools_recovery_duration = None
        schools_recovery_advance = None
        schools_default_rate = None

        # Category 6: Office
        office_cost_per_sqm = None
        office_cost_basis = None
        office_cost_start_option = None
        office_cost_start_date = None
        office_cost_duration = None
        office_payment_frequency = None
        office_escalation_profile = None
        office_recovery_duration = None
        office_recovery_advance = None
        office_default_rate = None

        # Category 7: Hospitality
        hospitality_cost_per_sqm = None
        hospitality_cost_basis = None
        hospitality_cost_start_option = None
        hospitality_cost_start_date = None
        hospitality_cost_duration = None
        hospitality_payment_frequency = None
        hospitality_escalation_profile = None
        hospitality_recovery_duration = None
        hospitality_recovery_advance = None
        hospitality_default_rate = None

        # Category 8: Logistics
        logistics_cost_per_sqm = None
        logistics_cost_basis = None
        logistics_cost_start_option = None
        logistics_cost_start_date = None
        logistics_cost_duration = None
        logistics_payment_frequency = None
        logistics_escalation_profile = None
        logistics_recovery_duration = None
        logistics_recovery_advance = None
        logistics_default_rate = None

        # Category 9: CEC
        cec_cost_per_sqm = None
        cec_cost_basis = None
        cec_cost_start_option = None
        cec_cost_start_date = None
        cec_cost_duration = None
        cec_payment_frequency = None
        cec_escalation_profile = None
        cec_recovery_duration = None
        cec_recovery_advance = None
        cec_default_rate = None

        # Category 10: Canal
        canal_cost_per_sqm = None
        canal_cost_basis = None
        canal_cost_start_option = None
        canal_cost_start_date = None
        canal_cost_duration = None
        canal_payment_frequency = None
        canal_escalation_profile = None
        canal_recovery_duration = None
        canal_recovery_advance = None
        canal_default_rate = None

        # Category 11: Public Amenities
        public_amenities_cost_per_sqm = None
        public_amenities_cost_basis = None
        public_amenities_cost_start_option = None
        public_amenities_cost_start_date = None
        public_amenities_cost_duration = None
        public_amenities_payment_frequency = None
        public_amenities_escalation_profile = None
        public_amenities_recovery_duration = None
        public_amenities_recovery_advance = None
        public_amenities_default_rate = None

        # Category 12: [Placeholder 1]
        placeholder_1_cost_per_sqm = None
        placeholder_1_cost_basis = None
        placeholder_1_cost_start_option = None
        placeholder_1_cost_start_date = None
        placeholder_1_cost_duration = None
        placeholder_1_payment_frequency = None
        placeholder_1_escalation_profile = None
        placeholder_1_recovery_duration = None
        placeholder_1_recovery_advance = None
        placeholder_1_default_rate = None

        # Category 13: [Placeholder 2]
        placeholder_2_cost_per_sqm = None
        placeholder_2_cost_basis = None
        placeholder_2_cost_start_option = None
        placeholder_2_cost_start_date = None
        placeholder_2_cost_duration = None
        placeholder_2_payment_frequency = None
        placeholder_2_escalation_profile = None
        placeholder_2_recovery_duration = None
        placeholder_2_recovery_advance = None
        placeholder_2_default_rate = None

        # Category 14: [Placeholder 3]
        placeholder_3_cost_per_sqm = None
        placeholder_3_cost_basis = None
        placeholder_3_cost_start_option = None
        placeholder_3_cost_start_date = None
        placeholder_3_cost_duration = None
        placeholder_3_payment_frequency = None
        placeholder_3_escalation_profile = None
        placeholder_3_recovery_duration = None
        placeholder_3_recovery_advance = None
        placeholder_3_default_rate = None

        # Category 15: [Placeholder 4]
        placeholder_4_cost_per_sqm = None
        placeholder_4_cost_basis = None
        placeholder_4_cost_start_option = None
        placeholder_4_cost_start_date = None
        placeholder_4_cost_duration = None
        placeholder_4_payment_frequency = None
        placeholder_4_escalation_profile = None
        placeholder_4_recovery_duration = None
        placeholder_4_recovery_advance = None
        placeholder_4_default_rate = None

    class CommunityOperationsRoshn:
        residential_units_single_family_cost_per_sqm = None
        residential_units_single_family_cost_basis = None
        residential_units_single_family_cost_start_option = None
        residential_units_single_family_cost_start_date = None
        residential_units_single_family_cost_duration = None
        residential_units_single_family_payment_frequency = None
        residential_units_single_family_escalation_profile = None
        residential_units_single_family_recovery_duration = None
        residential_units_single_family_recovery_advance = None
        residential_units_single_family_default_rate = None

        residential_units_multi_family_cost_per_sqm = None
        residential_units_multi_family_cost_basis = None
        residential_units_multi_family_cost_start_option = None
        residential_units_multi_family_cost_start_date = None
        residential_units_multi_family_cost_duration = None
        residential_units_multi_family_payment_frequency = None
        residential_units_multi_family_escalation_profile = None
        residential_units_multi_family_recovery_duration = None
        residential_units_multi_family_recovery_advance = None
        residential_units_multi_family_default_rate = None

        residential_land_single_family_cost_per_sqm = None
        residential_land_single_family_cost_basis = None
        residential_land_single_family_cost_start_option = None
        residential_land_single_family_cost_start_date = None
        residential_land_single_family_cost_duration = None
        residential_land_single_family_payment_frequency = None
        residential_land_single_family_escalation_profile = None
        residential_land_single_family_recovery_duration = None
        residential_land_single_family_recovery_advance = None
        residential_land_single_family_default_rate = None

        residential_land_multi_family_cost_per_sqm = None
        residential_land_multi_family_cost_basis = None
        residential_land_multi_family_cost_start_option = None
        residential_land_multi_family_cost_start_date = None
        residential_land_multi_family_cost_duration = None
        residential_land_multi_family_payment_frequency = None
        residential_land_multi_family_escalation_profile = None
        residential_land_multi_family_recovery_duration = None
        residential_land_multi_family_recovery_advance = None
        residential_land_multi_family_default_rate = None

        commercial_land_cost_per_sqm = None
        commercial_land_cost_basis = None
        commercial_land_cost_start_option = None
        commercial_land_cost_start_date = None
        commercial_land_cost_duration = None
        commercial_land_payment_frequency = None
        commercial_land_escalation_profile = None
        commercial_land_recovery_duration = None
        commercial_land_recovery_advance = None
        commercial_land_default_rate = None

        # Category 4: Retail
        retail_cost_per_sqm = None
        retail_cost_basis = None
        retail_cost_start_option = None
        retail_cost_start_date = None
        retail_cost_duration = None
        retail_payment_frequency = None
        retail_escalation_profile = None
        retail_recovery_duration = None
        retail_recovery_advance = None
        retail_default_rate = None

        # Category 5: Schools
        schools_cost_per_sqm = None
        schools_cost_basis = None
        schools_cost_start_option = None
        schools_cost_start_date = None
        schools_cost_duration = None
        schools_payment_frequency = None
        schools_escalation_profile = None
        schools_recovery_duration = None
        schools_recovery_advance = None
        schools_default_rate = None

        # Category 6: Office
        office_cost_per_sqm = None
        office_cost_basis = None
        office_cost_start_option = None
        office_cost_start_date = None
        office_cost_duration = None
        office_payment_frequency = None
        office_escalation_profile = None
        office_recovery_duration = None
        office_recovery_advance = None
        office_default_rate = None

        # Category 7: Hospitality
        hospitality_cost_per_sqm = None
        hospitality_cost_basis = None
        hospitality_cost_start_option = None
        hospitality_cost_start_date = None
        hospitality_cost_duration = None
        hospitality_payment_frequency = None
        hospitality_escalation_profile = None
        hospitality_recovery_duration = None
        hospitality_recovery_advance = None
        hospitality_default_rate = None

        # Category 8: Logistics
        logistics_cost_per_sqm = None
        logistics_cost_basis = None
        logistics_cost_start_option = None
        logistics_cost_start_date = None
        logistics_cost_duration = None
        logistics_payment_frequency = None
        logistics_escalation_profile = None
        logistics_recovery_duration = None
        logistics_recovery_advance = None
        logistics_default_rate = None

        # Category 9: CEC
        cec_cost_per_sqm = None
        cec_cost_basis = None
        cec_cost_start_option = None
        cec_cost_start_date = None
        cec_cost_duration = None
        cec_payment_frequency = None
        cec_escalation_profile = None
        cec_recovery_duration = None
        cec_recovery_advance = None
        cec_default_rate = None

        # Category 10: Canal
        canal_cost_per_sqm = None
        canal_cost_basis = None
        canal_cost_start_option = None
        canal_cost_start_date = None
        canal_cost_duration = None
        canal_payment_frequency = None
        canal_escalation_profile = None
        canal_recovery_duration = None
        canal_recovery_advance = None
        canal_default_rate = None

        # Category 11: Public Amenities
        public_amenities_cost_per_sqm = None
        public_amenities_cost_basis = None
        public_amenities_cost_start_option = None
        public_amenities_cost_start_date = None
        public_amenities_cost_duration = None
        public_amenities_payment_frequency = None
        public_amenities_escalation_profile = None
        public_amenities_recovery_duration = None
        public_amenities_recovery_advance = None
        public_amenities_default_rate = None

        # Category 12: [Placeholder 1]
        placeholder_1_cost_per_sqm = None
        placeholder_1_cost_basis = None
        placeholder_1_cost_start_option = None
        placeholder_1_cost_start_date = None
        placeholder_1_cost_duration = None
        placeholder_1_payment_frequency = None
        placeholder_1_escalation_profile = None
        placeholder_1_recovery_duration = None
        placeholder_1_recovery_advance = None
        placeholder_1_default_rate = None

        # Category 13: [Placeholder 2]
        placeholder_2_cost_per_sqm = None
        placeholder_2_cost_basis = None
        placeholder_2_cost_start_option = None
        placeholder_2_cost_start_date = None
        placeholder_2_cost_duration = None
        placeholder_2_payment_frequency = None
        placeholder_2_escalation_profile = None
        placeholder_2_recovery_duration = None
        placeholder_2_recovery_advance = None
        placeholder_2_default_rate = None

        # Category 14: [Placeholder 3]
        placeholder_3_cost_per_sqm = None
        placeholder_3_cost_basis = None
        placeholder_3_cost_start_option = None
        placeholder_3_cost_start_date = None
        placeholder_3_cost_duration = None
        placeholder_3_payment_frequency = None
        placeholder_3_escalation_profile = None
        placeholder_3_recovery_duration = None
        placeholder_3_recovery_advance = None
        placeholder_3_default_rate = None

        # Category 15: [Placeholder 4]
        placeholder_4_cost_per_sqm = None
        placeholder_4_cost_basis = None
        placeholder_4_cost_start_option = None
        placeholder_4_cost_start_date = None
        placeholder_4_cost_duration = None
        placeholder_4_payment_frequency = None
        placeholder_4_escalation_profile = None
        placeholder_4_recovery_duration = None
        placeholder_4_recovery_advance = None
        placeholder_4_default_rate = None

    class LeasingandDisposalCosts:
        leasing_costs_calculation_approach = None
        leasing_costs_allocation_basis = None
        leasing_costs_cost_basis = None
        leasing_costs_ad_hoc_amount = None
        leasing_costs_cost_percent = None
        leasing_costs_cost_per_sqm = None
        leasing_costs_escalation_profile = None
        sales_transaction_cost_calculation_approach = None
        sales_transaction_cost_allocation_basis = None
        sales_transaction_cost_cost_basis = None
        sales_transaction_cost_ad_hoc_amount = None
        sales_transaction_cost_cost_percent = None
        sales_transaction_cost_cost_per_sqm = None
        sales_transaction_cost_escalation_profile = None

    class EscrowAssumptions:
        construction_milestone_downpayment = None
        construction_milestone_1st_instalment = None
        construction_milestone_2nd_instalment = None
        construction_milestone_3rd_instalment = None
        construction_milestone_4th_instalment = None
        construction_milestone_5th_instalment = None
        construction_milestone_6th_instalment = None
        payment_into_escrow_downpayment = None
        payment_into_escrow_1st_instalment = None
        payment_into_escrow_2nd_instalment = None
        payment_into_escrow_3rd_instalment = None
        payment_into_escrow_4th_instalment = None
        payment_into_escrow_5th_instalment = None
        payment_into_escrow_6th_instalment = None
        cumulative_payment_downpayment = None
        cumulative_payment_1st_instalment = None
        cumulative_payment_2nd_instalment = None
        cumulative_payment_3rd_instalment = None
        cumulative_payment_4th_instalment = None
        cumulative_payment_5th_instalment = None
        cumulative_payment_6th_instalment = None
        retention_reserve = None
        hard_cost_utilization = None
        admin_and_soft_cost_utilization = None
        permanent_license_approval_duration = None
        retention_release_duration = None
        last_year_release_option = None
        last_year_release_duration = None
        
        # Escrow Inclusion by Asset Category (15 categories)
        # Maps asset sub_category to Yes/No for escrow applicability
        escrow_inclusion_residential_units = None
        escrow_inclusion_residential_land = None
        escrow_inclusion_commercial_land = None
        escrow_inclusion_retail = None
        escrow_inclusion_schools = None
        escrow_inclusion_office = None
        escrow_inclusion_hospitality = None
        escrow_inclusion_logistics = None
        escrow_inclusion_cec = None
        escrow_inclusion_canal = None
        escrow_inclusion_public_amenities = None
        escrow_inclusion_placeholder_1 = None
        escrow_inclusion_placeholder_2 = None
        escrow_inclusion_placeholder_3 = None
        escrow_inclusion_placeholder_4 = None
        
        # Escrow Reallocation & Fees
        reallocation_option = None
        escrow_set_up_fee = None

    class CostAllocationInputs:
        public_amenity_cost = None
        cec_cost = None
        canal_cost = None

    class OtherIncomeandExpensesAssumptions:

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

    class FinancingAssumptions:
        project_term_loan_debt_drawdown_date = None
        project_term_loan_term_loan_amount_calculation_approach = None
        project_term_loan_percent_of = None
        project_term_loan_ad_hoc_amount = None
        project_term_loan_loan_term = None
        project_term_loan_grace_period = None
        project_term_loan_ballon_payment_percent = None
        project_term_loan_amortization_percent = None
        project_term_loan_repayment_frequency = None
        project_term_loan_base_rate_profile = None
        project_term_loan_credit_spread = None
        project_term_loan_debt_arrangement_fees = None
        project_term_loan_arrangement_fees_inclusion = None
        project_term_loan_valuation_fees = None
        project_term_loan_other_debt_fees = None
        
        project_debt_revolver_revolver_facility_start_date = None
        project_debt_revolver_revolver_facility_duration = None
        project_debt_revolver_revolver_limit = None
        project_debt_revolver_autodraw_threshold = None
        project_debt_revolver_reborrowing_toggle = None
        project_debt_revolver_base_rate_profile = None
        project_debt_revolver_credit_spread = None
        project_debt_revolver_debt_arrangement_fees = None
        project_debt_revolver_arrangement_fees_inclusion = None
        project_debt_revolver_commitment_fees = None
        project_debt_revolver_commitment_fees_payment_frequency = None
        
        asset_debt_revolver_revolver_facility_start_date = None
        asset_debt_revolver_revolver_facility_duration = None
        asset_debt_revolver_revolver_limit = None
        asset_debt_revolver_reborrowing_toggle = None
        asset_debt_revolver_base_rate_profile = None
        asset_debt_revolver_credit_spread = None
        asset_debt_revolver_asset_cash_reserve_applicability = None
        asset_debt_revolver_cash_transfer_date = None
        asset_debt_revolver_debt_arrangement_fees = None
        asset_debt_revolver_arrangement_fees_inclusion = None
        asset_debt_revolver_commitment_fees = None
        asset_debt_revolver_commitment_fees_payment_frequency = None


# Assign values to class attributes

# ============================================================================
# MODULE 2: ASSET CLASS DEFINITIONS
# ============================================================================
# Contains asset-level configuration classes for project details, business
# model, land area, acquisition, infrastructure, costs, and financing.
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
        construction_phase = None
        asset_name = None
        asset_unique_identifier = None
        asset_landco_inclusion = None
        landco_output_inclusion = None

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

    class BusinessModelModule:
        business_model = None
        exit_counterparty = None
    
    class LandAreaModule:
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

    class AcquisitionModule:
        override = None
        acquisition_counterparty = None
        acquired_land_type = None
        acquisition_price = None
        acquisition_date = None
        payment_type = None
        payment_start_date = None
        payment_profile_option = None
        pre_defined_profile = None
        payment_duration = None
        payment_schedule = None
        escalation_profile = None

    class AcquisitionTransactionCostModule:
        legal_cost_override = None
        legal_cost_transaction_date = None
        legal_cost_amount = None
        legal_cost_escalation = None

        agency_cost_override = None
        agency_cost_transaction_date = None
        agency_cost_amount = None
        agency_cost_escalation = None

        technical_cost_override = None
        technical_cost_transaction_date = None
        technical_cost_amount = None
        technical_cost_escalation = None

        valuation_cost_override = None
        valuation_cost_transaction_date = None
        valuation_cost_amount = None
        valuation_cost_escalation = None

        due_diligence_cost_override = None
        due_diligence_cost_transaction_date = None
        due_diligence_cost_amount = None
        due_diligence_cost_escalation = None

        real_estate_transaction_tax_override = None
        real_estate_transaction_tax_transaction_date = None
        real_estate_transaction_tax_amount = None
        real_estate_transaction_tax_escalation = None

        municipal_fees_override = None
        municipal_fees_transaction_date = None
        municipal_fees_amount = None
        municipal_fees_escalation = None

    class PrimaryInfrastructureModule:
        override = None
        calculation_approach = None
        cost_basis = None
        ad_hoc_amount = None
        cost_per_sqm = None
        construction_start_date = None
        s_curve_option = None
        construction_s_curve = None
        construction_duration = None
        user_defined_s_curve = None
        payment_start_date = None
        payment_duration = None
        escalation_profile = None
        payment_schedule = None


    class SecondaryInfrastructureModule:
        override = None
        calculation_approach = None
        cost_basis = None
        ad_hoc_amount = None
        cost_per_sqm = None
        construction_start_date = None
        s_curve_option = None
        construction_s_curve = None
        construction_duration = None
        user_defined_s_curve = None
        payment_start_date = None
        payment_duration = None
        escalation_profile = None
        payment_schedule = None

    class DesignCostModule:
        override = None
        amount = None
        start_date = None
        s_curve_option = None
        pre_defined_s_curve = None
        duration = None
        user_defined_s_curve = None
        escalation_profile = None

    class PermittingCostModule:
        override = None
        amount = None
        start_date = None
        s_curve_option = None
        pre_defined_s_curve = None
        duration = None
        user_defined_s_curve = None
        escalation_profile = None

    class SupervisionCostModule:
        override = None
        amount = None
        start_date = None
        s_curve_option = None
        pre_defined_s_curve = None
        duration = None
        user_defined_s_curve = None
        escalation_profile = None

    class ProjectManagementCostModule:
        override = None
        amount = None
        start_date = None
        s_curve_option = None
        pre_defined_s_curve = None
        duration = None
        user_defined_s_curve = None
        escalation_profile = None

    class ContingencyCostModule:
        override = None
        amount = None
        start_date = None
        s_curve_option = None
        pre_defined_s_curve = None
        duration = None
        user_defined_s_curve = None
        escalation_profile = None

    class LandSalesModule:
        land_sales_override = None
        escrow_applicability = None
        sales_price = None
        sales_start_date = None
        sales_phasing_option = None
        sales_phasing_profile = None
        sales_duration = None
        sales_phasing = None
        escalation_profile = None
        collection_start_date = None
        collection_duration = None
        payment_schedule = None


    class LandLeaseModule:
        land_lease_override = None
        lease_calculation_basis = None
        annual_lease_amount = None
        annual_yield = None
        lease_start_date = None
        lease_duration = None
        lease_occupancy = None
        grace_period = None
        escalation_profile = None
        associated_opex = None

    class LandBankModule:
        land_bank_override = None
        holding_period = None
        escalation_profile = None

    class LeasingandDisposalCostModule:
        leasing_cost_override = None
        leasing_cost_amount = None
        leasing_cost_escalation = None

        sales_transaction_cost_override = None
        sales_transaction_cost_amount = None
        sales_transaction_cost_escalation_profile = None

    class OtherIncome1:
        other_income_1_override = None
        calculation_approach = None
        calculation_basis = None
        other_income_percent_of = None
        other_income_ad_hoc_amount = None
        other_income_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class OtherIncome2:
        other_income_2_override = None
        calculation_approach = None
        calculation_basis = None
        other_income_percent_of = None
        other_income_ad_hoc_amount = None
        other_income_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class GovernmentSubsidies:
        government_subsidies_override = None
        calculation_approach = None
        calculation_basis = None
        other_income_percent_of = None
        other_income_ad_hoc_amount = None
        other_income_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class OtherExpense1:
        other_expense_1_override = None
        calculation_approach = None
        calculation_basis = None
        other_expense_percent_of = None
        other_expense_ad_hoc_amount = None
        other_expense_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class OtherExpense2:
        other_expense_2_override = None
        calculation_approach = None
        calculation_basis = None
        other_expense_percent_of = None
        other_expense_ad_hoc_amount = None
        other_expense_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class OtherExpense3:
        other_expense_3_override = None
        calculation_approach = None
        calculation_basis = None
        other_expense_percent_of = None
        other_expense_ad_hoc_amount = None
        other_expense_sar_per_sqm = None
        start_date = None
        duration = None
        phasing = None
        escalation_profile = None

    class CommunityOperationsCostAmanah:
        override = None
        cost_basis = None
        cost_per_sqm = None
        cost_start_date_override = None
        cost_duration = None
        payment_frequency = None
        escalation_profile = None
        recovery_duration = None
        recovery_advance = None
        recovery_default_rate = None

    class CommunityOperationsCostRoshn:
        override = None
        cost_basis = None
        cost_per_sqm = None
        cost_start_date_override = None
        cost_duration = None
        payment_frequency = None
        escalation_profile = None
        recovery_duration = None
        recovery_advance = None
        recovery_default_rate = None

    class CorporateOverheadExpensesSalaries:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CorporateOverheadExpensesITServices:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CorporateOverheadExpensesOfficeRentandUtilities:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None
    
    class CorporateOverheadExpensesProfessionalServices:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CorporateOverheadExpensesMarketing:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CorporateOverheadExpensesSalesCost:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CorporateOverheadExpensesAdditionalExpenses:
        override = None
        ad_hoc_amount = None
        percent_capitalized = None
        cost_start_date = None
        cost_duration = None
        cost_schedule = None

    class CostAllocation:
        public_amenities = None
        cec = None
        canal = None

    class AssetDebtRevolver:
        override = None
        revolver_facility_start_date = None
        revolver_facility_duration = None
        revolver_limit = None
        re_borrowing_toggle = None
        base_rate_profile = None
        credit_spread = None
        credit_spread_profile = None
        asset_cash_reserve_applicability = None
        cash_transfer_date = None
        debt_arrangement_fees = None
        arrangement_fees_inclusion = None
        commitment_fees = None
        commitment_fees_payment_frequency = None

# ============================================================================
# MODULE 3: MAIN CALCULATION ENGINE
# ============================================================================
# Contains the main wrapper function that orchestrates all calculations.
# Sub-modules within:
#   - 3.1: Input Processing Functions
#   - 3.2: Utility Functions (Timeline, Profiles, Escalation)
#   - 3.3: Generic Calculation Functions
#   - 3.4: Acquisition & Transaction Cost Functions
#   - 3.5: Infrastructure Cost Functions
#   - 3.6: Soft Cost & Contingency Functions
#   - 3.7: Land Acquisition Calculations
#   - 3.8: Revenue Module - Land Lease
#   - 3.9: Community Operations Module
#   - 3.10: Corporate Overhead Functions
#   - 3.11: Other Income and Expenses
#   - 3.12: Escrow Module Calculations
#   - 3.13: Financing Module
#       - 3.13.1: Asset Level Financing
#       - 3.13.2: Project Level Financing
#   - 3.14: Cashflow Statement Generation
# ============================================================================

def wrapper_for_vars(payload, is_save):
    """
    Main wrapper function that orchestrates the entire cashflow model calculation.
    
    This function processes input data from Excel named ranges and calculates all
    components of a land development feasibility model including:
    - Land acquisition costs and timing
    - Infrastructure costs (primary and secondary)
    - Soft costs (design, permitting, supervision, project management)
    - Contingency costs
    - Revenue from land lease, land bank exit, and land sales
    - Leasing and sales transaction costs
    - Community operations costs
    - Corporate overhead allocations
    - Development financing (senior and mezzanine debt)
    - Cashflow statements and valuations
    
    Args:
        payload (list): JSON payload containing named ranges from Excel.
            Expected format: List of dicts with 'name' and 'values' keys.
            
    Returns:
        dict: Final output containing:
            - exceloutput: Monthly and annual cashflow outputs
            - jvoutput: JV-filtered output payload
            - consolidationoutput: Non-JV filtered output payload
            
    Raises:
        Exception: Prints error message with traceback if calculation fails.
        
    Example:
        >>> result = fn_wrapper_for_vars(excel_payload)
        >>> monthly_data = result['monthly_dfs']
        >>> annual_data = result['annual_dfs']
    """
    try:
            _start_time = time.perf_counter()
            _section_time = _start_time
            _model_started_at = time.strftime('%Y-%m-%d %H:%M:%S')
            _timing_measurements = []

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
                    f"Total duration (s) (LandCo): {round(total_duration, 4):.4f}",
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
                # ===== CASHFLOW FROM INVESTMENTS =====
                'land_acquisition': False,           # 3.7: Land Acquisition Cost & Transaction Costs
                'infrastructure': False,             # 3.5: Primary & Secondary Infrastructure S-Curves & Payments
                'soft_cost_contingency': False,      # 3.6: Design, Permitting, Supervision, PM, Contingency
                
                # ===== CASHFLOW FROM OPERATIONS =====
                'land_lease': False,                 # 3.8: Land Lease Revenue, Grace Period & Exit Value
                'land_bank': False,                  # 3.8: Land Bank Exit Value
                'land_sale': False,                  # 3.8: Land Sales Revenue & Phasing
                'leasing_and_disposal_cost': False,  # 3.8: Leasing Costs & Sales Transaction Costs
                'community_operations': False,       # 3.9: Community Operations Costs & Recovery (Amanah/ROSHN)
                'corporate_overhead': False,         # 3.10: Corporate Overhead Costs (Salaries, IT, Rent, etc.)
                'other_income_and_expenses': False,  # 3.11: Other Income (1-3), Govt Subsidies, Other Expenses (1-3)
                'cost_allocation': False,  
                # ===== ESCROW & SALES COLLECTION =====
                'escrow': False,                     # 3.12: Escrow Calculations, Inflows, Soft/Hard Cost Releases
                'on_plan_sales_collection': False,   # 3.12: On-Plan Sales Collection Phasing
                
                # ===== CASHFLOW FROM FINANCING =====
                'asset_level_financing': False,      # 3.13.1: Asset Level Debt Revolver workings
                'project_level_financing': False,    # 3.13.2: Project Level Term Loan & Revolver workings
                
                # ===== CASHFLOW STATEMENTS =====
                'cashflow_dataframes': False,        # 3.14: Individual CF DataFrames for debugging
                'cashflow_statements': False,        # 3.14: Cashflow from Operations, Investments, Financing
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
                                df.to_excel(writer, sheet_name=safe_name, index=True)
                    print(f"  Exported {description} to: {excel_path}")
                    os.startfile(excel_path)
                    return excel_path
                except Exception as e:
                    print(f"  Error exporting {description}: {e}")
                    return None
            
            # ========================================================================
            # SUB-MODULE 3.1: INPUT PROCESSING FUNCTIONS
            # ========================================================================
            
            
            # ========================================================================
            # SUB-MODULE 3.1: INPUT PROCESSING FUNCTIONS
            # ========================================================================

            def fn_read_all_named_ranges_json(payload):
                """
                Reads named ranges from a JSON input and returns a DataFrame with columns
                ['name', 'value'] AND a pre-built {name: value} lookup dict (first-seen wins).
                The JSON is expected to be a list of dicts with keys: 'name', 'values', etc.
                - Single-cell: values[[single_value]]
                - Single-row: values[[v1, v2, ...]]
                - Single-col: values[[v1],[v2],...]
                - Multi-cell: values[r][c]
                """
                try:
                    named_values = []
                    lookup = {}
                    for entry in payload:
                        name = entry.get("name", "")
                        if not name or 'landco' not in name.lower():
                            continue
                        values = entry.get("values")
                        # Flatten values according to dimensionality like Excel reading logic
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
                        # Build lookup inline: first-seen wins (mirrors drop_duplicates keep='first')
                        if name not in lookup:
                            lookup[name] = value

                    return pd.DataFrame(named_values, columns=["name", "value"]), lookup
                except Exception as e:
                    print(f"Error in fn_read_all_named_ranges_json: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            # Single pass: DataFrame + lookup dict built together, no extra pandas passes
            assumptions, _assumption_value_lookup = fn_read_all_named_ranges_json(payload)

            def _get_named_range_value(name, default=None):
                return _assumption_value_lookup.get(name, default)

            predefined_profile_names = list(_assumption_value_lookup.get("a.landco.predefined.profile.name", []))
            predefined_profile_data = _assumption_value_lookup.get("a.landco.predefined.profile", [])
            predefined_profile_durations = _assumption_value_lookup.get("a.landco.predefined.profile.duration", [])
            escalation_profile_names = list(_assumption_value_lookup.get("a.landco.escalation.profile.name", []))
            escalation_profile_data = _assumption_value_lookup.get("a.landco.escalation.profile", [])

            # Pre-extract schedule/phasing keys for fast access throughout submodules
            _schedule_cache = {
                k: v for k, v in _assumption_value_lookup.items()
                if k.startswith("s.landco.")
            }

            # Pre-extract class/attribute/value arrays to avoid repeated DataFrame .loc scans
            # during class initialization (these are reused across all subclass calls)
            _global_class_names_cache = _assumption_value_lookup.get("a.landco.global.class")
            _global_attr_names_cache = _assumption_value_lookup.get("a.landco.global.attribute")
            _global_attr_values_cache = _assumption_value_lookup.get("a.landco.global.value")
            _asset_class_names_row_cache = _assumption_value_lookup.get("a.landco.class.row")
            _asset_attr_names_cache_row = _assumption_value_lookup.get("a.landco.attribute.row")
            _asset_attr_values_cache_row = _assumption_value_lookup.get("a.landco.asset.data")

            # ------------------------------------------------------------------
            # OPTIMIZATION: Pre-build class → attribute-index maps.
            # Without this, every fn_assign_*_class_attributes call iterates the
            # ENTIRE attribute list and skips non-matching entries:
            #   ~15 Global subclasses × N global attrs  +  ~40 Asset subclasses × M asset attrs
            # With this, each call iterates only its own indices (O(1) lookup).
            # ------------------------------------------------------------------
            _global_class_to_indices = {}
            if _global_class_names_cache and _global_attr_names_cache:
                for _i, _cls_name in enumerate(_global_class_names_cache):
                    _global_class_to_indices.setdefault(_cls_name, []).append(_i)

            _asset_class_to_indices = {}
            if _asset_class_names_row_cache and _asset_attr_names_cache_row:
                for _i, _cls_name in enumerate(_asset_class_names_row_cache):
                    _asset_class_to_indices.setdefault(_cls_name, []).append(_i)

            # ------------------------------------------------------------------
            # OPTIMIZATION: Pre-compute inclusion flags once.
            # Previously recomputed (list comprehension over all asset rows) on
            # every single Asset subclass call (~40 times).
            # ------------------------------------------------------------------
            _inclusion_flags_cache = []
            if _asset_attr_names_cache_row and _asset_attr_values_cache_row:
                _inclusion_idx_cache = _asset_attr_names_cache_row.index("asset_landco_inclusion")
                _inclusion_flags_cache = [
                    row[_inclusion_idx_cache] == "Yes"
                    for row in _asset_attr_values_cache_row
                ]

            # ------------------------------------------------------------------
            # OPTIMIZATION: Pre-transpose asset data to column-oriented layout.
            # Previously, extracting column i required `row[i]` inside a Python
            # loop over every asset row.  After transposing, column i is a
            # direct tuple access: _asset_attr_values_by_col[i].
            # ------------------------------------------------------------------
            _asset_attr_values_by_col = None
            if _asset_attr_values_cache_row and isinstance(
                _asset_attr_values_cache_row[0], (list, tuple)
            ):
                _asset_attr_values_by_col = list(zip(*_asset_attr_values_cache_row))

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
                    attr_names = _global_attr_names_cache
                    attr_values = _global_attr_values_cache
                    class_name = cls.__name__
                    # Iterate only the indices that belong to this class (pre-built map)
                    for i in _global_class_to_indices.get(class_name, []):
                        attr = attr_names[i]
                        if not hasattr(cls, attr):
                            raise ValueError(
                                f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                            )
                        # Check if the attribute name contains "date" and the value is an integer or float
                        if "date" in attr.lower() and isinstance(attr_values[i], (int, float)):
                            if attr_values[i] == "" or attr_values[i] == 0:
                                convertedval = None
                            else:
                                convertedval = datetime.fromtimestamp(
                                    (attr_values[i] - 25569) * 86400.0
                                ).strftime('%Y-%m-%d')
                            setattr(cls, attr, pd.to_datetime(convertedval))
                        else:
                            setattr(cls, attr, attr_values[i])
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
                    for subclass_name in dir(Global):
                        subclass = getattr(Global, subclass_name)
                        if isinstance(subclass, type):
                            fn_assign_global_class_attributes(subclass, assumptions)
                except Exception as e:
                    print(f"Error in fn_initialize_global_class: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            # Assign values to class attributes

            def fn_assign_asset_class_attributes(cls, assumptions):
                """
                Assigns attribute values from assumptions to an Asset class.

                Reads asset class/attribute/value data from assumptions DataFrame
                and sets corresponding class attributes as lists (one value per asset).
                Handles date conversion from Excel serial number format.
                If asset_landco_inclusion != "Yes" or the cell value is "",
                sets the attribute value for that asset to np.nan (or pd.NaT for dates).

                Args:
                    cls: The Asset subclass to assign attributes to.
                    assumptions (pd.DataFrame): DataFrame with 'name' and 'value' columns.

                Raises:
                    ValueError: If attribute is not defined in the class.
                """
                try:
                    attr_names = _asset_attr_names_cache_row
                    class_name = cls.__name__
                    # Reuse pre-computed inclusion flags (not recomputed per-class call)
                    inclusion_flags = _inclusion_flags_cache
                    # Reuse pre-transposed column data for O(1) column access
                    col_data = _asset_attr_values_by_col

                    # Iterate only the indices that belong to this class (pre-built map)
                    for i in _asset_class_to_indices.get(class_name, []):
                        attr = attr_names[i]
                        if not hasattr(cls, attr):
                            raise ValueError(
                                f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                            )
                        col = []
                        is_date = "date" in attr.lower()
                        # Direct column access via pre-transposed tuple; fallback to row scan
                        col_vals = (
                            col_data[i]
                            if col_data is not None
                            else [row[i] for row in _asset_attr_values_cache_row]
                        )
                        for idx, val in enumerate(col_vals):
                            if not inclusion_flags[idx] or val == "":
                                col.append(pd.NaT if is_date else np.nan)
                            elif is_date:
                                if val == 0 or val is None:
                                    col.append(pd.NaT)
                                else:
                                    col.append(pd.to_datetime(
                                        datetime.fromtimestamp(
                                            (float(val) - 25569) * 86400.0
                                        ).strftime('%Y-%m-%d')
                                    ))
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
                    for subclass_name in dir(Asset):
                        subclass = getattr(Asset, subclass_name)
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

            def fn_replace_nan(df, fill_value=0):
                """
                Replace NaN/NaT values in the DataFrame for rows where index != "".
                Rows with index == "" are excluded from replacement.

                Args:
                    df (pd.DataFrame): The cashflow DataFrame.
                    fill_value: Value to replace NaN/NaT with (default: 0).

                Returns:
                    pd.DataFrame: DataFrame with NaNs replaced as specified.
                """
                try:
                    if not isinstance(df, pd.DataFrame):
                        raise TypeError("Input must be a pandas DataFrame.")
                    if df.index.dtype != object:
                        df.index = df.index.astype(str)
                    mask = df.index != ""
                    if not mask.any():
                        return df

                    # Replace missing values without triggering pandas object downcast warnings.
                    df_to_replace = df.loc[mask].copy()
                    filled_values = df_to_replace.where(pd.notna(df_to_replace), fill_value)
                    df.loc[mask] = filled_values.infer_objects(copy=False)
                    return df
                except Exception as e:
                    print(f"Error in fn_replace_nan: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    return df
            
            def fn_create_model_timeline(start_date, end_date, frequency):
                """
                Create a timeline DataFrame for monthly-end (ME), quarter-end (QE) or year-end (YE) periods.
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
            # number_of_assets = assumptions.loc[assumptions["name"] == "a.number.of.assets", "value"].iloc[0]
            # Create empty DataFrame with assets as rows and timeline periods as columns
            timeline_periods = model_timeline_me["# of Period"]
            
            # Cache frequently used values for performance optimization
            _template_index = range(0, len(Asset.ProjectDetails.number), 1)
            _template_columns = model_timeline_me.index
            _n_assets = len(Asset.ProjectDetails.number)
            _n_periods = len(model_timeline_me)
            _period_starts = model_timeline_me['Period Start'].values
            _period_months = model_timeline_me['Period Start'].dt.month.values
            _period_years = model_timeline_me["Year"].values
            _unique_years = list(model_timeline_me["Year"].unique())
            _period_start_lookup = {
                pd.Timestamp(period_start): idx for idx, period_start in enumerate(_period_starts)
            }
            _cached_timeline_period_index = pd.Index(pd.to_datetime(_period_starts, errors="coerce"))
            _period_year_indices = np.array([_unique_years.index(year) for year in _period_years])
            _zero_df_template_cache = {}
            _zero_df_single_row_template_cache = {}
            _thread_worker_count = max(1, min(4, os.cpu_count() or 1))
            _shared_executor = ExecutorManager.get_thread_executor(max_workers=max(2, min(8, os.cpu_count() or 1)))

            def _execute_named_threaded_tasks(tasks_dict):
                """
                Submit a dict of {name: callable} to the shared thread executor.
                Returns {name: result} preserving insertion order.
                """
                futures = {_shared_executor.submit(fn): name for name, fn in tasks_dict.items()}
                results = {}
                for future in as_completed(futures):
                    results[futures[future]] = future.result()
                return results

            _zero_asset_series = pd.Series(0.0, index=_template_index, dtype='float64')
            _land_area_basis_series_cache = {
                "Gross Land Area": pd.Series(Asset.LandAreaModule.gross_land_area, index=_template_index),
                "Developable Land Area": pd.Series(Asset.LandAreaModule.developable_land_area, index=_template_index),
                "Gross Floor Area": pd.Series(Asset.LandAreaModule.gross_floor_area, index=_template_index),
                "Built Up Area": pd.Series(Asset.LandAreaModule.built_up_area, index=_template_index),
                "Gross Leasable Area": pd.Series(Asset.LandAreaModule.total_nsa__gla, index=_template_index),
                "Units": pd.Series(Asset.LandAreaModule.units, index=_template_index),
            }
            _land_cost_basis_series_cache = {
                key: _land_area_basis_series_cache[key]
                for key in ("Gross Land Area", "Developable Land Area")
            }
            _infrastructure_cost_basis_series_cache = {
                key: _land_area_basis_series_cache[key]
                for key in ("Gross Land Area", "Developable Land Area", "Gross Floor Area")
            }
            _community_cost_basis_series_cache = {
                key: _land_area_basis_series_cache[key]
                for key in ("Gross Land Area", "Developable Land Area", "Gross Floor Area", "Built Up Area")
            }
            # Named alias reused by acquisition transaction cost calculations
            _transaction_cost_basis_series_cache = _land_cost_basis_series_cache
            # Named subset reused by soft cost and contingency sqm-based calculations
            _soft_cost_sqm_basis_series_cache = {
                key: _land_area_basis_series_cache[key]
                for key in ("Gross Floor Area", "Built Up Area", "Gross Leasable Area", "Units")
            }
            _predefined_profile_lookup = {name: idx for idx, name in enumerate(predefined_profile_names)}
            _escalation_profile_lookup = {name: idx for idx, name in enumerate(escalation_profile_names)}
            _predefined_profile_validation_cache = {}
            _predefined_profile_row_cache = {}
            _monthly_escalation_vector_cache = {}

            # Thread-safe alias for the escalation vector cache (shared, pre-computed at setup).
            # The lock guards concurrent reads/writes when fn_calculate_monthly_escalation_profile
            # is invoked from parallel threads during revenue or community-operations waves.
            _escalation_profile_compute_cache = _monthly_escalation_vector_cache
            _escalation_profile_compute_cache_lock = threading.Lock()

            # Row-sum memoization: avoids recomputing df.sum(axis=1) on the same DataFrame
            # object across multiple submodules. Keyed by id(df); invalidated by garbage
            # collection, so only stable output DataFrames should be passed to _get_row_sum_series.
            _row_sum_cache = {}
            _row_sum_cache_lock = threading.Lock()

            def _coerce_numeric_sequence(values, fill_value=0.0):
                numeric_values = pd.to_numeric(pd.Series(values), errors='coerce')
                return numeric_values.fillna(fill_value).to_numpy(dtype='float64')

            for profile_name, profile_index in _predefined_profile_lookup.items():
                predefined_profile = _coerce_numeric_sequence(predefined_profile_data[profile_index])
                max_duration = pd.to_numeric(
                    pd.Series([predefined_profile_durations[profile_index]]),
                    errors='coerce'
                ).fillna(0).iloc[0]

                if abs(sum(predefined_profile) - 1) > 1e-6:
                    _predefined_profile_validation_cache[profile_name] = False
                    continue

                non_zero_count = sum(1 for value in predefined_profile if value > 0)
                if non_zero_count > max_duration:
                    _predefined_profile_validation_cache[profile_name] = False
                    continue

                _predefined_profile_validation_cache[profile_name] = predefined_profile

            for profile_name, profile_index in _escalation_profile_lookup.items():
                escalation_rate = _coerce_numeric_sequence(escalation_profile_data[profile_index])
                escalation_rates_by_period = np.array([escalation_rate[yi] for yi in _period_year_indices], dtype='float64')
                monthly_escalation_percents = ((1 + escalation_rates_by_period) ** (1 / 12)) - 1
                cumulative_factors = np.cumprod(1 + monthly_escalation_percents)
                _monthly_escalation_vector_cache[profile_name] = (monthly_escalation_percents, cumulative_factors)

            def _normalize_timestamp_for_cache(value):
                timestamp = pd.to_datetime(value, errors="coerce")
                return None if pd.isna(timestamp) else pd.Timestamp(timestamp)

            def _get_row_sum_series(df):
                """Return df.sum(axis=1), memoized by object id to avoid redundant computation."""
                df_id = id(df)
                cached = _row_sum_cache.get(df_id)
                if cached is not None:
                    return cached
                result = df.sum(axis=1)
                with _row_sum_cache_lock:
                    _row_sum_cache[df_id] = result
                return result
            
            # Helper function to create zero-initialized DataFrame efficiently
            def _create_zero_df(dtype='float64'):
                """Create a zero-initialized DataFrame with cached index/columns."""
                dtype_key = np.dtype(dtype).str
                if dtype_key not in _zero_df_template_cache:
                    _zero_df_template_cache[dtype_key] = np.zeros((_n_assets, _n_periods), dtype=dtype)
                return pd.DataFrame(
                    _zero_df_template_cache[dtype_key].copy(),
                    index=_template_index,
                    columns=_template_columns
                )
            
            # Helper function to create single-row zero-initialized DataFrame (for project-level calculations)
            def _create_zero_df_single_row(dtype='float64'):
                """Create a single-row zero-initialized DataFrame with index [0] and same columns."""
                dtype_key = np.dtype(dtype).str
                if dtype_key not in _zero_df_single_row_template_cache:
                    _zero_df_single_row_template_cache[dtype_key] = np.zeros((1, _n_periods), dtype=dtype)
                return pd.DataFrame(
                    _zero_df_single_row_template_cache[dtype_key].copy(),
                    index=[0],
                    columns=_template_columns
                )
            
            # ============================================================================================
            # FINANCIAL HELPER FUNCTIONS (Excel PMT equivalents)
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
                    template (pd.DataFrame): A DataFrame template initialized with zeros, used to store the calculated profile.
                    profile_option (pd.Series): A series indicating the profile option for each asset (e.g., "Pre Defined").
                    selected_pre_defined_profile (pd.Series): A series indicating the selected pre-defined profile for each asset.
                    start_dates (pd.Series): A series of start dates for each asset.
                    predefined_profile_names (list): A list of names for the pre-defined profiles.
                    predefined_profile_data (dict): A dictionary containing the data for the pre-defined profiles.
                    predefined_profile_durations (dict): A dictionary containing the durations for the pre-defined profiles.
                    model_timeline_me (pd.DataFrame): The model timeline DataFrame with monthly periods.

                Returns:
                    pd.DataFrame: A DataFrame containing the calculated pre-defined profile for each asset.
                """
                try:
                    for loop_row_idx in template.index:
                        
                        # Skip assets that do not use "Pre Defined" payment profiles
                        if profile_option[loop_row_idx] != "Pre Defined":
                            continue

                        selected_profile = selected_pre_defined_profile[loop_row_idx]
                        start_date = _normalize_timestamp_for_cache(start_dates[loop_row_idx])

                        # Skip if the selected profile is invalid
                        if start_date is None or pd.isna(selected_profile) or selected_profile in ("", None):
                            continue

                        cached_profile = _predefined_profile_validation_cache.get(selected_profile)
                        if cached_profile is None or cached_profile is False:
                            continue

                        # Validate if the start date exists in the timeline
                        start_idx = _period_start_lookup.get(start_date)
                        if start_idx is None:
                            continue

                        cache_key = (selected_profile, start_idx)
                        cached_row = _predefined_profile_row_cache.get(cache_key)
                        if cached_row is None:
                            cached_row = np.zeros(_n_periods, dtype='float64')
                            valid_length = min(len(cached_profile), _n_periods - start_idx)
                            cached_row[start_idx:start_idx + valid_length] = cached_profile[:valid_length]
                            _predefined_profile_row_cache[cache_key] = cached_row

                        template.iloc[loop_row_idx, :] = cached_row

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
                    template (pd.DataFrame): A DataFrame template initialized with zeros, used to store the calculated profile.
                    profile_options (pd.Series): A series indicating the profile option for each asset (e.g., "User Defined").
                    schedules (dict): A dictionary containing user-defined schedules for cost phasing or payments.
                    start_dates (pd.Series): A series of start dates for each asset.
                    durations (pd.Series): A series of durations (in months) for each asset.
                    model_timeline_me (pd.DataFrame): The model timeline DataFrame with monthly periods.

                Returns:
                    pd.DataFrame: A DataFrame containing the calculated user-defined profile for each asset.
                """
                try:
                    for loop_row_idx in template.index:

                        # Skip assets that do not use "User Defined" payment profiles
                        if profile_options[loop_row_idx] != "User Defined":
                            continue

                        schedule = schedules[loop_row_idx]
                        start_date = _normalize_timestamp_for_cache(start_dates[loop_row_idx])
                        duration = durations[loop_row_idx]

                        # Validate the payment schedule
                        if isinstance(schedule, list):
                            schedule = [0 if pd.isna(value) or value is None else value for value in schedule]
                        else:
                            schedule = 0 if pd.isna(schedule) or schedule is None else schedule

                        # Validate if the start date exists in the timeline
                        start_idx = _period_start_lookup.get(start_date)
                        if start_idx is None:
                            continue

                        # Validate if the duration is valid
                        if duration is None or pd.isna(duration):
                            continue
                        duration = int(duration)
                        if duration <= 0:
                            continue

                        
                        # Calculate the start and end indices in the timeline
                        end_idx = start_idx + duration

                        # Vectorized application of user-defined profile
                        # Get the schedule values for the valid range
                        valid_end_idx = min(end_idx, _n_periods)
                        if isinstance(schedule, list):
                            schedule_slice = schedule[start_idx:valid_end_idx]
                            schedule_values = np.array([0 if v == "" or pd.isna(v) else v for v in schedule_slice])
                        else:
                            schedule_value = 0 if schedule == "" or pd.isna(schedule) else schedule
                            schedule_values = np.full(valid_end_idx - start_idx, schedule_value)
                        template.iloc[loop_row_idx, start_idx:valid_end_idx] = schedule_values

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
                Generalized function to calculate monthly escalation profiles and cumulative escalation factors for assets.

                Parameters:
                    escalation_percent_template (DataFrame): Template DataFrame to store the calculated escalation percentages.
                    escalation_factor_template (DataFrame): Template DataFrame to store the cumulative escalation factors.
                    selected_escalation_profile (list): List of selected escalation profiles for each asset.
                    escalation_profile_names (list): List of valid escalation profile names.
                    escalation_profile_data (list): List of escalation rates corresponding to the profile names.
                    asset_numbers (list): List of asset numbers (indices of assets).
                    model_timeline_me (DataFrame): Timeline DataFrame with 'Year' column.

                Returns:
                    tuple: Updated escalation_percent_template and escalation_factor_template DataFrames.

                Notes:
                    - This function calculates monthly escalation percentages and cumulative factors.
                    - It validates the selected profile and applies escalation rates based on the timeline.
                """
                try:
                    escalation_factor_template.iloc[:, :] = 1  # Start all cumulative factors at 1
                    
                    selected_profile_series = pd.Series(
                        selected_escalation_profile,
                        index=escalation_factor_template.index,
                    )
                    valid_profile_series = selected_profile_series[
                        selected_profile_series.notna() & selected_profile_series.astype(str).ne("")
                    ]

                    for selected_profile_name in pd.unique(valid_profile_series):
                        cached_vectors = _monthly_escalation_vector_cache.get(selected_profile_name)
                        if cached_vectors is None:
                            continue

                        monthly_escalation_percents, cumulative_factors = cached_vectors
                        matched_rows = valid_profile_series[valid_profile_series == selected_profile_name].index

                        # Assign the cached vectors to all rows using the same profile
                        escalation_percent_template.loc[matched_rows, :] = monthly_escalation_percents
                        escalation_factor_template.loc[matched_rows, :] = cumulative_factors
                    
                    return escalation_percent_template, escalation_factor_template
                except Exception as e:
                    print(f"Error in fn_calculate_monthly_escalation_profile: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise
            
            # ========================================================================
            # SUB-MODULE 3.4: ACQUISITION & TRANSACTION COST FUNCTIONS
            # ========================================================================

            def fn_calculate_acquisition_transaction_cost(
                template: pd.DataFrame,
                
                asset_override: pd.Series,
                asset_cost_amount: pd.Series,
                asset_cost_transaction_date: pd.Series,
                asset_cost_escalation: pd.Series,

                global_allocation_basis: str,
                global_cost_basis: str,
                global_ad_hoc_amount: float,
                global_cost_per_sqm: float,
                global_cost_percent: float,
                global_calculation_approach: str,
                global_transaction_date,
                global_escalation_profile,

                acquisition_cost_df: pd.DataFrame,
            ):
                """
                Generalized function to calculate acquisition transaction costs.

                Args:
                    asset_override (pd.Series): Series indicating override ("Yes"/"No").
                    asset_cost_amount (pd.Series): Cost amounts per asset.
                    asset_cost_transaction_date (pd.Series): Transaction dates per asset.
                    asset_cost_escalation (pd.Series): Escalation profiles per asset.
                    global_allocation_basis (str): Key for allocation basis mapping.
                    global_cost_basis (str): Key for cost basis mapping.
                    global_ad_hoc_amount (float): Ad-hoc amount for cost type.
                    global_cost_per_sqm (float): Cost per sqm for cost type.
                    global_cost_percent (float): Percent of acquisition price for cost type.
                    global_calculation_approach (str): Calculation approach for cost type.
                    global_transaction_date: Default transaction date.
                    global_escalation_profile: Default escalation profile.
                    acquisition_cost_df (pd.DataFrame): DataFrame of acquisition costs.
                Returns:
                    asset_cost_amount (pd.Series): Final calculated cost amounts.
                    asset_cost_transaction_date (pd.Series): Final transaction dates.
                    asset_cost_escalation (pd.Series): Final escalation profiles.
                """
                try:
                    override_mask = pd.Series(asset_override) == "Yes"
                    zero_basis_series = _zero_asset_series.copy()
                    allocation_basis_series = _land_area_basis_series_cache.get(global_allocation_basis, zero_basis_series)
                    cost_basis_series = _land_cost_basis_series_cache.get(global_cost_basis, zero_basis_series)

                    allocation_basis_filtered = allocation_basis_series.where(~override_mask, pd.NA)
                    total_allocation_basis = allocation_basis_filtered.sum(skipna=True)

                    allocation_percent = allocation_basis_filtered / total_allocation_basis
                    global_ad_hoc_amount = allocation_percent * global_ad_hoc_amount

                    cost_basis_filtered = cost_basis_series.where(~override_mask, pd.NA)
                    global_sar_per_sqm_amount = cost_basis_filtered * global_cost_per_sqm

                    global_percent_of_amount = acquisition_cost_df.sum(axis=1) * global_cost_percent

                    if global_calculation_approach == "SAR / SQM of":
                        global_amount = global_sar_per_sqm_amount
                    elif global_calculation_approach == "% of Acquisition Price":
                        global_amount = global_percent_of_amount
                    elif global_calculation_approach == "Ad-Hoc Amount":
                        global_amount = global_ad_hoc_amount

                    asset_cost_amount = asset_cost_amount.where(override_mask, global_amount)
                    asset_cost_transaction_date = asset_cost_transaction_date.where(override_mask, global_transaction_date)
                    asset_cost_escalation = asset_cost_escalation.where(override_mask, global_escalation_profile)

                    return asset_cost_amount, asset_cost_transaction_date, asset_cost_escalation
                except Exception as e:
                    print(f"Error in fn_calculate_acquisition_transaction_cost: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            def fn_create_transaction_flag(
                transaction_dates: pd.Series,
                timeline_periods: pd.Series,
                template: pd.DataFrame
            ) -> pd.DataFrame:
                """
                Creates a transaction flag DataFrame based on transaction dates and timeline periods.

                Args:
                    transaction_dates (pd.Series): Series of transaction dates per asset.
                    asset_numbers (list): List of asset indices.
                    timeline_periods (pd.Series): Series of period start dates in the timeline.
                    template (pd.DataFrame): Template DataFrame for output shape.

                Returns:
                    pd.DataFrame: Transaction flag DataFrame.
                """
                try:
                    # Enforce consistent datetime dtype
                    transaction_dates = pd.to_datetime(transaction_dates, errors="coerce")
                    timeline_period_index = pd.Index(pd.to_datetime(timeline_periods, errors="coerce"))

                    if timeline_period_index.equals(_cached_timeline_period_index):
                        timeline_period_index = _cached_timeline_period_index

                    flag_matrix = np.zeros((len(transaction_dates), len(template.columns)), dtype=int)
                    if timeline_period_index.is_unique:
                        matched_positions = timeline_period_index.get_indexer(transaction_dates)
                    else:
                        # Duplicate dates in timeline: map each date to its first occurrence
                        first_pos = {d: i for i, d in reversed(list(enumerate(timeline_period_index)))}
                        matched_positions = np.array([first_pos.get(d, -1) for d in transaction_dates])
                    valid_rows = np.flatnonzero(matched_positions >= 0)
                    if len(valid_rows) > 0:
                        flag_matrix[valid_rows, matched_positions[valid_rows]] = 1

                    flag_df = pd.DataFrame(
                        flag_matrix,
                        index=template.index,
                        columns=template.columns
                    )
                    return flag_df
                except Exception as e:
                    print(f"Error in fn_create_transaction_flag: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            def fn_calculate_escalated_transaction_cost(
                base_amount_series: pd.Series,
                escalation_factor_mapping: pd.DataFrame,
                transaction_cost_flag: pd.DataFrame,
                calculation_approach: str,
                template: pd.DataFrame
            ) -> pd.DataFrame:
                """
                Calculates the escalated transaction cost matrix for each asset and period.

                Args:
                    base_amount_series (pd.Series): Series of base cost amounts per asset.
                    escalation_factor_mapping (pd.DataFrame): DataFrame of escalation factors.
                    asset_numbers (list): List of asset indices.
                    calculation_approach (str): Calculation approach string.
                    template (pd.DataFrame, optional): Template DataFrame for output shape.

                Returns:
                    pd.DataFrame: Escalated transaction cost matrix.
                """
                try:
                    # Vectorized calculation using broadcasting
                    base_amounts = base_amount_series.values.reshape(-1, 1)
                    
                    if calculation_approach == "% of Acquisition Price":
                        result_df = pd.DataFrame(
                            base_amounts * transaction_cost_flag.values,
                            index=template.index,
                            columns=template.columns
                        )
                    else:
                        # Multiply base amount by escalation factors and transaction cost flag
                        result_df = pd.DataFrame(
                            base_amounts * escalation_factor_mapping.values * transaction_cost_flag.values,
                            index=template.index,
                            columns=template.columns
                        )
                    return result_df
                except Exception as e:
                    print(f"Error in fn_calculate_escalated_transaction_cost: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            def fn_calculate_acquisition_transaction_cost_outputs(cost_prefix: str):
                asset_cost_amount, transaction_date, escalation_profile = fn_calculate_acquisition_transaction_cost(
                    template=template_asset_timeline,
                    asset_override=getattr(Asset.AcquisitionTransactionCostModule, f"{cost_prefix}_override"),
                    asset_cost_amount=pd.Series(getattr(Asset.AcquisitionTransactionCostModule, f"{cost_prefix}_amount")),
                    asset_cost_transaction_date=pd.Series(getattr(Asset.AcquisitionTransactionCostModule, f"{cost_prefix}_transaction_date")),
                    asset_cost_escalation=pd.Series(getattr(Asset.AcquisitionTransactionCostModule, f"{cost_prefix}_escalation")),
                    global_allocation_basis=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_allocation_basis"),
                    global_cost_basis=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_cost_basis"),
                    global_ad_hoc_amount=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_ad_hoc_amount"),
                    global_cost_per_sqm=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_cost_per_sqm"),
                    global_cost_percent=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_cost_percent"),
                    global_calculation_approach=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_calculation_approach"),
                    global_transaction_date=w_acquisition_date,
                    global_escalation_profile=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_escalation_profile"),
                    acquisition_cost_df=o_land_acquisition_cost,
                )

                transaction_flag = fn_create_transaction_flag(
                    transaction_dates=transaction_date,
                    timeline_periods=model_timeline_me['Period Start'],
                    template=template_asset_timeline,
                )

                _, escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=_create_zero_df(),
                    escalation_factor_template=_create_zero_df(),
                    selected_escalation_profile=escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me,
                )

                escalation_factor_mapping = escalation_factors * transaction_flag
                cost_output = fn_calculate_escalated_transaction_cost(
                    base_amount_series=asset_cost_amount,
                    escalation_factor_mapping=escalation_factor_mapping,
                    transaction_cost_flag=transaction_flag,
                    calculation_approach=getattr(Global.AcquisitionTransactionCost, f"{cost_prefix}_calculation_approach"),
                    template=template_asset_timeline,
                )

                return cost_prefix, (transaction_flag, cost_output)

            # ========================================================================
            # SUB-MODULE 3.5: INFRASTRUCTURE COST FUNCTIONS
            # ========================================================================

            def fn_calculate_infrastructure_cost_amount(
                asset_override,
                asset_calculation_approach,
                asset_ad_hoc_amount,
                asset_cost_basis_key,
                asset_cost_per_sqm,

                global_calculation_approach,
                global_allocation_basis_key,
                global_cost_basis_key,
                global_cost_per_sqm,
                global_ad_hoc_amount
            ):
                """
                Calculate the total infrastructure cost amount for primary or secondary infrastructure.

                Args:
                    asset_override (pd.Series): A series indicating whether asset-level overrides are applied.
                    asset_calculation_approach (pd.Series): A series indicating the calculation approach for each asset.
                    asset_ad_hoc_amount (pd.Series): A series of ad-hoc amounts for each asset.
                    asset_cost_basis_key (pd.Series): A series of cost basis keys for each asset.
                    asset_cost_per_sqm (pd.Series): A series of cost per square meter for each asset.
                    global_calculation_approach (str): The global calculation approach for infrastructure costs.
                    global_allocation_basis_key (str): The global allocation basis key for infrastructure costs.
                    global_cost_basis_key (str): The global cost basis key for infrastructure costs.
                    global_cost_per_sqm (float): The global cost per square meter for infrastructure costs.
                    global_ad_hoc_amount (float): The global ad-hoc amount for infrastructure costs.

                Returns:
                    pd.DataFrame: A DataFrame containing the calculated infrastructure cost amounts for each asset.
                """
                try:
                    # Convert all inputs to pandas.Series if they are lists
                    if isinstance(asset_override, list):
                        asset_override = pd.Series(asset_override)
                    if isinstance(asset_calculation_approach, list):
                        asset_calculation_approach = pd.Series(asset_calculation_approach)
                    if isinstance(asset_ad_hoc_amount, list):
                        asset_ad_hoc_amount = pd.Series(asset_ad_hoc_amount)
                    if isinstance(asset_cost_basis_key, list):
                        asset_cost_basis_key = pd.Series(asset_cost_basis_key)
                    if isinstance(asset_cost_per_sqm, list):
                        asset_cost_per_sqm = pd.Series(asset_cost_per_sqm)

                    allocation_basis_mapping = _land_area_basis_series_cache
                    cost_basis_mapping = _infrastructure_cost_basis_series_cache
                    zero_basis_series = pd.Series(0.0, index=asset_override.index, dtype='float64')

                    # Initialize the result series with zeros
                    cost_amount = pd.Series(0.0, index=asset_override.index)

                    # Apply the logic for override = "Yes"
                    override_mask = asset_override == "Yes"

                    # Logic for "Ad-Hoc Amount"
                    ad_hoc_mask = asset_calculation_approach == "Ad-Hoc Amount"
                    if (override_mask & ad_hoc_mask).any():
                        cost_amount.loc[override_mask & ad_hoc_mask] = asset_ad_hoc_amount.loc[override_mask & ad_hoc_mask]

                    # Logic for "SAR / SQM of"
                    sar_per_sqm_mask = asset_calculation_approach == "SAR / SQM of"
                    
                    cost_basis_values = zero_basis_series.copy()
                    for cost_basis_key_name, cost_basis_series in cost_basis_mapping.items():
                        matching_rows = asset_cost_basis_key.eq(cost_basis_key_name)
                        if matching_rows.any():
                            cost_basis_values.loc[matching_rows] = cost_basis_series.loc[matching_rows]

                    if (override_mask & sar_per_sqm_mask).any():
                        cost_amount.loc[override_mask & sar_per_sqm_mask] = (
                            cost_basis_values.loc[override_mask & sar_per_sqm_mask] * asset_cost_per_sqm.loc[override_mask & sar_per_sqm_mask]
                        )

                    # Apply the logic for override = "No"
                    no_override_mask = ~override_mask

                    if global_calculation_approach == "SAR / SQM of":
                        global_cost_basis_values = cost_basis_mapping.get(global_cost_basis_key, zero_basis_series)
                        cost_amount.loc[no_override_mask] = (
                            global_cost_basis_values.loc[no_override_mask] * global_cost_per_sqm
                        )

                    elif global_calculation_approach == "Ad-Hoc Amount":
                        allocation_basis_series = allocation_basis_mapping.get(global_allocation_basis_key, zero_basis_series)
                        allocation_basis_filtered = allocation_basis_series.where(no_override_mask, pd.NA)
                        total_allocation_basis = allocation_basis_filtered.sum(skipna=True)

                        allocation_percent = allocation_basis_filtered / total_allocation_basis
                        global_ad_hoc_amount_series = allocation_percent * global_ad_hoc_amount

                        cost_amount.loc[no_override_mask] = global_ad_hoc_amount_series

                    return cost_amount
                except Exception as e:
                    print(f"Error in fn_calculate_infrastructure_cost_amount: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise

            def fn_calculate_infrastructure_cost_payment(
                asset_base_amount: pd.Series,
                schedule: pd.DataFrame,
                escalation_factor_mapping: pd.DataFrame,
                template: pd.DataFrame
            ) -> pd.DataFrame:
                """
                Calculates the escalated transaction cost matrix for each asset and period.

                Args:
                    base_amount_series (pd.Series): Series of base cost amounts per asset.
                    escalation_factor_mapping (pd.DataFrame): DataFrame of escalation factors.
                    asset_numbers (list): List of asset indices.
                    calculation_approach (str): Calculation approach string.
                    template (pd.DataFrame, optional): Template DataFrame for output shape.

                Returns:
                    pd.DataFrame: Escalated transaction cost matrix.
                """
                try:
                    # Vectorized calculation: multiply base amount by sum of escalation factors and schedule
                    # Use broadcasting with .values to ensure proper alignment
                    escalation_sums = escalation_factor_mapping.sum(axis=1).values.reshape(-1, 1)
                    base_amounts = asset_base_amount.values.reshape(-1, 1)
                    result_df = pd.DataFrame(
                        base_amounts * escalation_sums * schedule.values,
                        index=template.index,
                        columns=template.columns
                    )
                    return result_df
                except Exception as e:
                    print(f"Error in fn_calculate_infrastructure_cost_payment: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise


            # ========================================================================
            # SUB-MODULE 3.6: SOFT COST & CONTINGENCY FUNCTIONS
            # ========================================================================

            def fn_calculate_soft_and_contingency_cost_amount(
                template: pd.DataFrame,
                
                asset_override: pd.Series,
                asset_cost_amount: pd.Series,

                global_allocation_basis: str,
                global_cost_basis: str,
                global_ad_hoc_amount: float,
                global_cost_per_sqm: float,
                global_cost_percent: float,
                global_calculation_approach: str,
                
                primary_infrastructure_cost_df: pd.DataFrame,
                secondary_infrastructure_cost_df: pd.DataFrame,
                total_infrastructure_cost_df: pd.DataFrame,
                soft_cost_df: pd.DataFrame = None,
                total_infrastructure_and_soft_cost_df: pd.DataFrame = None,
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
                    if not isinstance(asset_cost_amount, pd.Series):
                        asset_cost_amount = pd.Series(asset_cost_amount)

                    allocation_basis_mapping = _land_area_basis_series_cache
                    sar_per_sqm_cost_basis_mapping = _infrastructure_cost_basis_series_cache
                    zero_basis_series = _zero_asset_series.copy()

                    percent_of_cost_basis_mapping = {
                        "Primary Infrastructure Cost": primary_infrastructure_cost_df.sum(axis=1),
                        "Secondary Infrastructure Cost": secondary_infrastructure_cost_df.sum(axis=1),
                        "Total Infrastructure Cost": total_infrastructure_cost_df.sum(axis=1),
                        "Soft Cost": soft_cost_df.sum(axis=1) if soft_cost_df is not None else template.sum(axis=1),
                        "Total Infrastructure + Soft Cost": total_infrastructure_and_soft_cost_df.sum(axis=1) if total_infrastructure_and_soft_cost_df is not None else template.sum(axis=1),
                    }

                    override_mask = pd.Series(asset_override) == "Yes"
                    allocation_basis_series = allocation_basis_mapping.get(global_allocation_basis, zero_basis_series)
                    sar_per_sqm_cost_basis_series = sar_per_sqm_cost_basis_mapping.get(global_cost_basis, zero_basis_series)
                    percent_of_cost_basis_series = percent_of_cost_basis_mapping.get(global_cost_basis, zero_basis_series)

                    allocation_basis_filtered = allocation_basis_series.where(~override_mask, pd.NA)
                    total_allocation_basis = allocation_basis_filtered.sum(skipna=True)

                    allocation_percent = allocation_basis_filtered / total_allocation_basis
                    global_ad_hoc_amount = allocation_percent * global_ad_hoc_amount

                    sar_per_sqm_cost_basis_filtered = sar_per_sqm_cost_basis_series.where(~override_mask, pd.NA)
                    global_sar_per_sqm_amount = sar_per_sqm_cost_basis_filtered * global_cost_per_sqm

                    percent_of_cost_basis_filtered = percent_of_cost_basis_series.where(~override_mask, pd.NA)
                    global_percent_of_amount = percent_of_cost_basis_filtered * global_cost_percent

                    if global_calculation_approach == "SAR / SQM of":
                        global_amount = global_sar_per_sqm_amount
                    elif global_calculation_approach == "% of":
                        global_amount = global_percent_of_amount
                    elif global_calculation_approach == "Ad-Hoc Amount":
                        global_amount = global_ad_hoc_amount
                    else:
                        global_amount = pd.Series(0.0, index=template.index)

                    asset_cost_amount = asset_cost_amount.where(override_mask, global_amount)

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
                    asset_base_amount (pd.DataFrame): A DataFrame containing the base amounts for each asset.
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
                    escalation_sums = escalation_factor_mapping.sum(axis=1).values.reshape(-1, 1)

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
            # SUB-MODULE 3.7: LAND ACQUISITION CALCULATIONS
            # ========================================================================
            # LAND ACQUISITION FLAG
            # ========================================================================

            _record_timing("Utility setup and timeline preparation")
            
            primary_infrastructure_construction_start_dates = np.where(
                pd.Series(Asset.PrimaryInfrastructureModule.override) == "Yes",
                pd.Series(Asset.PrimaryInfrastructureModule.construction_start_date),
                Global.InfrastructureCosts.primary_infrastructure_start_date
            ).astype('datetime64[ns]')

            secondary_infrastructure_construction_start_dates = np.where(
                pd.Series(Asset.SecondaryInfrastructureModule.override) == "Yes",
                pd.Series(Asset.SecondaryInfrastructureModule.construction_start_date),
                Global.InfrastructureCosts.secondary_infrastructure_start_date
            ).astype('datetime64[ns]')

            if Global.AcquisitionInputs.acquisition_date_selection_input == 'Primary Infrastructure Start':
                global_acquisition_date = primary_infrastructure_construction_start_dates
            elif Global.AcquisitionInputs.acquisition_date_selection_input == 'Secondary Infrastructure Start':
                global_acquisition_date = secondary_infrastructure_construction_start_dates
            elif Global.AcquisitionInputs.acquisition_date_selection_input == 'Vertical Construction Start':
                global_acquisition_date = Global.ModelAssumptions.default_date          #This will be udpated to match vertical contruction start date from DevCo
            elif Global.AcquisitionInputs.acquisition_date_selection_input == 'Override':
                global_acquisition_date = Global.AcquisitionInputs.acquisition_date
            else:
                raise ValueError("Invalid acquisition date selection input.")

            w_acquisition_date = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.acquisition_date),
                global_acquisition_date
            ).astype('datetime64[ns]')

            # Vectorized land acquisition flag calculation
            # Compare each acquisition date against all timeline period starts using broadcasting

            o_land_acquisition_flag = _create_zero_df()
            acquisition_dates_arr = np.array(w_acquisition_date).reshape(-1, 1)
            period_starts_arr = _period_starts.reshape(1, -1)
            o_land_acquisition_flag = pd.DataFrame(
                (acquisition_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # ============================================================================================
            # USER DEFINED LAND ACQUISITION PAYMENT PROFILE
            # ============================================================================================

            w_land_acquisition_payment_user_defined_profile = _create_zero_df()

            w_acquisition_payment_start_dates = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.payment_start_date),
                Global.AcquisitionInputs.payment_start_date
            )
            
            w_acquisition_payment_profile_option = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.payment_profile_option),
                "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_land_acquisition_payment_user_defined_profile = fn_calculate_user_defined_profile(
                template=w_land_acquisition_payment_user_defined_profile,
                profile_options=w_acquisition_payment_profile_option,
                schedules=_get_named_range_value("s.landco.acquisition.cost.payment"),
                start_dates=w_acquisition_payment_start_dates,
                durations=Asset.AcquisitionModule.payment_duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED LAND ACQUISITION PAYMENT PROFILE
            # ============================================================================================

            w_land_acquisition_payment_pre_defined_profile = _create_zero_df()

            w_pre_defined_profile = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.pre_defined_profile),
                Global.AcquisitionInputs.pre_defined_profile
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

            # ============================================================================================
            # CONSOLIDATED ACQUISITION PAYMENT PROFILE
            # ============================================================================================

            o_land_acquisition_payment_profile = _create_zero_df()


            # Sum the pre-defined and user-defined profiles
            o_land_acquisition_payment_profile = (
                w_land_acquisition_payment_pre_defined_profile + w_land_acquisition_payment_user_defined_profile
            )
            
            # ============================================================================================
            # ESCALATION CALCULATIONS
            # ============================================================================================

            w_land_acquisition_monthly_escalation_percent = _create_zero_df()

            w_land_acquisition_monthly_escalation_factors = _create_zero_df()

            w_acquisition_escalation_profile = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.escalation_profile).astype(str),
                str(Global.AcquisitionInputs.escalation_profile)
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

            w_land_acquisition_monthly_escalation_factor_mapping = _create_zero_df()

            w_land_acquisition_monthly_escalation_factor_mapping = w_land_acquisition_monthly_escalation_factors * o_land_acquisition_flag

            # ============================================================================================
            # LAND ACQUISITION PAYMENT
            # ============================================================================================

            o_land_acquisition_cost = _create_zero_df()

            gross_land_area = Asset.LandAreaModule.gross_land_area

            w_acquisition_price = np.where(
                pd.Series(Asset.AcquisitionModule.override) == 'Yes',
                pd.Series(Asset.AcquisitionModule.acquisition_price),
                Global.AcquisitionInputs.acquisition_price
            ).astype('float64')
            
            # Vectorized land acquisition cost calculation
            # Calculate base land acquisition cost for all assets
            w_land_acquisition_cost = gross_land_area * w_acquisition_price
            
            # Sum escalation factors across all columns for each row
            total_escalation_factor = w_land_acquisition_monthly_escalation_factor_mapping.sum(axis=1)
            
            # Calculate total escalated cost per asset
            total_escalated_cost = w_land_acquisition_cost * total_escalation_factor
            
            # Multiply payment profile by total escalated cost using broadcasting
            o_land_acquisition_cost = o_land_acquisition_payment_profile.mul(total_escalated_cost, axis=0)

            # Split land acquisition cost by effective payment type (asset override aware).
            _acq_override_mask = pd.Series(Asset.AcquisitionModule.override).astype(str).str.strip().str.lower().eq("yes")
            _asset_payment_type = pd.Series(Asset.AcquisitionModule.payment_type)
            _global_payment_type = Global.AcquisitionInputs.payment_type
            _effective_payment_type = pd.Series(
                np.where(
                    _acq_override_mask,
                    _asset_payment_type,
                    _global_payment_type,
                ),
                index=template_asset_timeline.index,
            ).fillna("")

            _normalized_payment_type = (
                _effective_payment_type.astype(str)
                .str.strip()
                .str.lower()
                .str.replace("_", " ", regex=False)
            )
            _in_kind_payment_mask = _normalized_payment_type.eq("in kind payment")
            _cash_payment_mask = ~_in_kind_payment_mask

            _cash_payment_mask_df = pd.DataFrame(
                np.repeat(_cash_payment_mask.values[:, np.newaxis], o_land_acquisition_cost.shape[1], axis=1),
                index=o_land_acquisition_cost.index,
                columns=o_land_acquisition_cost.columns,
            )
            _in_kind_payment_mask_df = pd.DataFrame(
                np.repeat(_in_kind_payment_mask.values[:, np.newaxis], o_land_acquisition_cost.shape[1], axis=1),
                index=o_land_acquisition_cost.index,
                columns=o_land_acquisition_cost.columns,
            )

            o_land_acquisition_cost_cash_payment = o_land_acquisition_cost.where(_cash_payment_mask_df, 0.0)
            o_land_acquisition_cost_in_kind = o_land_acquisition_cost.where(_in_kind_payment_mask_df, 0.0)

            _acquisition_transaction_cost_prefixes = (
                "legal_cost",
                "agency_cost",
                "technical_cost",
                "valuation_cost",
                "due_diligence_cost",
                "real_estate_transaction_tax",
                "municipal_fees",
            )

            # Run all 7 transaction cost types in parallel via the shared executor.
            # Each lambda captures its own cp to avoid late-binding closure issues.
            # The [1] slice drops the echoed cost_prefix from the return tuple.
            _acquisition_transaction_cost_results = _execute_named_threaded_tasks({
                cost_prefix: (lambda cp=cost_prefix: fn_calculate_acquisition_transaction_cost_outputs(cp)[1])
                for cost_prefix in _acquisition_transaction_cost_prefixes
            })

            o_acquisition_transaction_cost_legal_flag, o_acquisition_transaction_cost_legal = _acquisition_transaction_cost_results["legal_cost"]
            o_acquisition_transaction_cost_agency_flag, o_acquisition_transaction_cost_agency = _acquisition_transaction_cost_results["agency_cost"]
            o_acquisition_transaction_cost_technical_flag, o_acquisition_transaction_cost_technical = _acquisition_transaction_cost_results["technical_cost"]
            o_acquisition_transaction_cost_valuation_flag, o_acquisition_transaction_cost_valuation = _acquisition_transaction_cost_results["valuation_cost"]
            o_acquisition_transaction_cost_due_diligence_flag, o_acquisition_transaction_cost_due_diligence = _acquisition_transaction_cost_results["due_diligence_cost"]
            o_acquisition_transaction_cost_real_estate_transaction_tax_flag, o_acquisition_transaction_cost_real_estate_transaction_tax = _acquisition_transaction_cost_results["real_estate_transaction_tax"]
            o_acquisition_transaction_cost_municipal_fees_flag, o_acquisition_transaction_cost_municipal_fees = _acquisition_transaction_cost_results["municipal_fees"]

            # ============================================================================================
            # EXPORT LAND ACQUISITION DATAFRAMES TO EXCEL
            # ============================================================================================
            
            if _EXPORT_FLAGS.get('land_acquisition', False):
                _land_acquisition_exports = {
                    'Acquisition Flag': o_land_acquisition_flag,
                    'User Defined Profile': w_land_acquisition_payment_user_defined_profile,
                    'Pre Defined Profile': w_land_acquisition_payment_pre_defined_profile,
                    'Payment Profile': o_land_acquisition_payment_profile,
                    'Monthly Esc Percent': w_land_acquisition_monthly_escalation_percent,
                    'Monthly Esc Factors': w_land_acquisition_monthly_escalation_factors,
                    'Esc Factor Mapping': w_land_acquisition_monthly_escalation_factor_mapping,
                    'Acquisition Cost': o_land_acquisition_cost,
                    'Legal Cost Flag': o_acquisition_transaction_cost_legal_flag,
                    'Legal Cost': o_acquisition_transaction_cost_legal,
                    'Agency Cost Flag': o_acquisition_transaction_cost_agency_flag,
                    'Agency Cost': o_acquisition_transaction_cost_agency,
                    'Technical Cost Flag': o_acquisition_transaction_cost_technical_flag,
                    'Technical Cost': o_acquisition_transaction_cost_technical,
                    'Valuation Cost Flag': o_acquisition_transaction_cost_valuation_flag,
                    'Valuation Cost': o_acquisition_transaction_cost_valuation,
                    'Due Diligence Flag': o_acquisition_transaction_cost_due_diligence_flag,
                    'Due Diligence Cost': o_acquisition_transaction_cost_due_diligence,
                    'RE Trans Tax Flag': o_acquisition_transaction_cost_real_estate_transaction_tax_flag,
                    'RE Trans Tax': o_acquisition_transaction_cost_real_estate_transaction_tax,
                    'Municipal Fees Flag': o_acquisition_transaction_cost_municipal_fees_flag,
                    'Municipal Fees': o_acquisition_transaction_cost_municipal_fees,
                }
                _export_to_excel(_land_acquisition_exports, 'export_land_acquisition', 'Land Acquisition')

            # ============================================================================================
            # USER DEFINED PRIMARY INFRASTRUCTURE S CURVE
            # ============================================================================================

            _record_timing("Land Acquisition Module")

            # ============================================================
            # WAVE-1: Submit infrastructure calculation as background future
            # (runs concurrently with soft cost calculations on main thread)
            # ============================================================
            def _compute_infrastructure():

                w_primary_infrastructure_s_curve_percent_user_defined = _create_zero_df()

                # Determine payment profile option for primary infrastructure (vectorized calculation)
                primary_infrastructure_s_curve_option = np.where(
                    pd.Series(Asset.PrimaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.PrimaryInfrastructureModule.s_curve_option),
                    "Pre Defined"
                )

                primary_infrastructure_construction_start_dates = np.where(
                    pd.Series(Asset.PrimaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.PrimaryInfrastructureModule.construction_start_date),
                    Global.InfrastructureCosts.primary_infrastructure_start_date
                ).astype('datetime64[ns]')

                # Call the generalized function for user-defined profile calculation
                w_primary_infrastructure_s_curve_percent_user_defined = fn_calculate_user_defined_profile(
                    template=w_primary_infrastructure_s_curve_percent_user_defined,
                    profile_options=primary_infrastructure_s_curve_option,
                    schedules=_get_named_range_value("s.landco.primary.infrastructure.s.curve"),
                    start_dates=primary_infrastructure_construction_start_dates,
                    durations=Asset.PrimaryInfrastructureModule.construction_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # PRE DEFINED PRIMARY INFRASTRUCTURE S CURVE
                # ============================================================================================

                w_primary_infrastructure_s_curve_percent_pre_defined = _create_zero_df()

                # Determine payment profile option for transformation (vectorized calculation)
                primary_infrastructure_s_curve_selected_profile = np.where(
                    pd.Series(Asset.PrimaryInfrastructureModule.override) == "Yes",
                    Asset.PrimaryInfrastructureModule.construction_s_curve,
                    Global.InfrastructureCosts.primary_infrastructure_phasing
                )

                # Call the generalized function for pre-defined profile calculation
                w_primary_infrastructure_s_curve_percent_pre_defined = fn_calculate_pre_defined_profile(
                    template=w_primary_infrastructure_s_curve_percent_pre_defined,
                    profile_option=primary_infrastructure_s_curve_option,
                    selected_pre_defined_profile=primary_infrastructure_s_curve_selected_profile,
                    start_dates=primary_infrastructure_construction_start_dates,
                    predefined_profile_names=predefined_profile_names,
                    predefined_profile_data=predefined_profile_data,
                    predefined_profile_durations=predefined_profile_durations,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # CONSOLIDATED PRIMARY INFRASTRUCTURE S CURVE
                # ============================================================================================

                o_primary_infrastructure_s_curve_percent = _create_zero_df()

                # Sum the pre-defined and user-defined profiles
                o_primary_infrastructure_s_curve_percent = (
                    w_primary_infrastructure_s_curve_percent_pre_defined + w_primary_infrastructure_s_curve_percent_user_defined
                )

                # ============================================================================================
                # USER DEFINED PRIMARY INFRASTRUCTURE PAYMENT PROFILE
                # ============================================================================================

                o_primary_infrastructure_payment_user_defined_profile = _create_zero_df()

                # Replace payment profile option with "User Defined" series
                payment_profile_option_series = pd.Series(["User Defined"] * len(Asset.ProjectDetails.number))

                # Call the generalized function for user-defined profile calculation
                o_primary_infrastructure_payment_user_defined_profile = fn_calculate_user_defined_profile(
                    template=o_primary_infrastructure_payment_user_defined_profile,
                    profile_options=payment_profile_option_series,
                    schedules=_get_named_range_value("s.landco.primary.infrastructure.payment"),
                    start_dates=Asset.PrimaryInfrastructureModule.payment_start_date,
                    durations=Asset.PrimaryInfrastructureModule.payment_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # PRIMARY INFRASTRUCTURE COST (AMOUNT)
                # ============================================================================================

                # Call the function to calculate the primary infrastructure cost amount
                primary_infrastructure_cost_amount = fn_calculate_infrastructure_cost_amount(
                    asset_override=Asset.PrimaryInfrastructureModule.override,
                    asset_calculation_approach=Asset.PrimaryInfrastructureModule.calculation_approach,
                    asset_ad_hoc_amount=Asset.PrimaryInfrastructureModule.ad_hoc_amount,
                    asset_cost_basis_key=Asset.PrimaryInfrastructureModule.cost_basis,
                    asset_cost_per_sqm=Asset.PrimaryInfrastructureModule.cost_per_sqm,
                
                    global_calculation_approach=Global.InfrastructureCosts.primary_infrastructure_calculation_approach,
                    global_allocation_basis_key=Global.InfrastructureCosts.primary_infrastructure_allocation_basis,
                    global_cost_basis_key=Global.InfrastructureCosts.primary_infrastructure_cost_basis,
                    global_cost_per_sqm=Global.InfrastructureCosts.primary_infrastructure_cost_per_sqm,
                    global_ad_hoc_amount=Global.InfrastructureCosts.primary_infrastructure_ad_hoc_amount
                )

                # ============================================================================================
                # PRIMARY INFRASTRUCTURE COST (ESCALATION WORKING)
                # ============================================================================================

                w_primary_infrastructure_monthly_escalation_percent = _create_zero_df()

                w_primary_infrastructure_monthly_escalation_factors = _create_zero_df()

                # Determine payment profile option for transformation (vectorized calculation)
                primary_infrastructure_escalation_profile = np.where(
                    pd.Series(Asset.PrimaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.PrimaryInfrastructureModule.escalation_profile).astype(str),
                    str(Global.InfrastructureCosts.primary_infrastructure_escalation_profile)
                )

                # Vectorized construction start flag creation using broadcasting
                start_dates_arr = np.array(primary_infrastructure_construction_start_dates).reshape(-1, 1)
                period_starts_arr = _period_starts.reshape(1, -1)
                w_primary_infrastructure_construction_start_flag = pd.DataFrame(
                    (start_dates_arr == period_starts_arr).astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # Call the generalized function for monthly escalation profile calculation
                w_primary_infrastructure_monthly_escalation_percent, w_primary_infrastructure_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_primary_infrastructure_monthly_escalation_percent,
                    escalation_factor_template=w_primary_infrastructure_monthly_escalation_factors,
                    selected_escalation_profile=primary_infrastructure_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                w_primary_infrastructure_monthly_escalation_factor_mapping = _create_zero_df()
            
                w_primary_infrastructure_monthly_escalation_factor_mapping = w_primary_infrastructure_monthly_escalation_factors * w_primary_infrastructure_construction_start_flag

                # ============================================================================================
                # PRIMARY INFRASTRUCTURE COST PAYMENT (ESCALATED)
                # ============================================================================================

                o_primary_infrastructure_cost_payment = _create_zero_df()

                o_primary_infrastructure_cost_payment = fn_calculate_infrastructure_cost_payment(
                    asset_base_amount=primary_infrastructure_cost_amount,
                    schedule=o_primary_infrastructure_payment_user_defined_profile,
                    escalation_factor_mapping=w_primary_infrastructure_monthly_escalation_factor_mapping,
                    template=template_asset_timeline.copy()
                )

                # ============================================================================================
                # PRIMARY INFRASTRUCTURE COST S-CURVE (ESCALATED)
                # ============================================================================================

                o_primary_infrastructure_cost_s_curve = _create_zero_df()
            
                o_primary_infrastructure_cost_s_curve = o_primary_infrastructure_s_curve_percent.mul(o_primary_infrastructure_cost_payment.sum(axis=1), axis=0)

                # ============================================================================================
                # USER DEFINED SECONDARY INFRASTRUCTURE S CURVE
                # ============================================================================================

                w_secondary_infrastructure_s_curve_percent_user_defined = _create_zero_df()

                # Determine payment profile option for secondary infrastructure (vectorized calculation)
                secondary_infrastructure_s_curve_option = np.where(
                    pd.Series(Asset.SecondaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.SecondaryInfrastructureModule.s_curve_option),
                    "Pre Defined"  # Replaced Global.InfrastructureCosts.secondary_infrastructure_phasing with "Pre Defined"
                )

                secondary_infrastructure_construction_start_dates = np.where(
                    pd.Series(Asset.SecondaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.SecondaryInfrastructureModule.construction_start_date),
                    Global.InfrastructureCosts.secondary_infrastructure_start_date
                ).astype('datetime64[ns]')

                # Call the generalized function for user-defined profile calculation
                w_secondary_infrastructure_s_curve_percent_user_defined = fn_calculate_user_defined_profile(
                    template=w_secondary_infrastructure_s_curve_percent_user_defined,
                    profile_options=secondary_infrastructure_s_curve_option,
                    schedules=_get_named_range_value("s.landco.secondary.infrastructure.s.curve"),
                    start_dates=secondary_infrastructure_construction_start_dates,
                    durations=Asset.SecondaryInfrastructureModule.construction_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # PRE DEFINED SECONDARY INFRASTRUCTURE S CURVE
                # ============================================================================================

                w_secondary_infrastructure_s_curve_percent_pre_defined = _create_zero_df()

                # Determine payment profile option for transformation (vectorized calculation)
                secondary_infrastructure_s_curve_selected_profile = np.where(
                    pd.Series(Asset.SecondaryInfrastructureModule.override) == "Yes",
                    Asset.SecondaryInfrastructureModule.construction_s_curve,
                    Global.InfrastructureCosts.secondary_infrastructure_phasing
                )

                # Call the generalized function for pre-defined profile calculation
                w_secondary_infrastructure_s_curve_percent_pre_defined = fn_calculate_pre_defined_profile(
                    template=w_secondary_infrastructure_s_curve_percent_pre_defined,
                    profile_option=secondary_infrastructure_s_curve_option,
                    selected_pre_defined_profile=secondary_infrastructure_s_curve_selected_profile,
                    start_dates=secondary_infrastructure_construction_start_dates,
                    predefined_profile_names=predefined_profile_names,
                    predefined_profile_data=predefined_profile_data,
                    predefined_profile_durations=predefined_profile_durations,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # CONSOLIDATED SECONDARY INFRASTRUCTURE S CURVE
                # ============================================================================================

                o_secondary_infrastructure_s_curve_percent = _create_zero_df()

                # Sum the pre-defined and user-defined profiles
                o_secondary_infrastructure_s_curve_percent = (
                    w_secondary_infrastructure_s_curve_percent_pre_defined + w_secondary_infrastructure_s_curve_percent_user_defined
                )

                # ============================================================================================
                # USER DEFINED SECONDARY INFRASTRUCTURE PAYMENT PROFILE
                # ============================================================================================

                o_secondary_infrastructure_payment_user_defined_profile = _create_zero_df()
            
                # Replace payment profile option with "User Defined" series
                payment_profile_option_series = pd.Series(["User Defined"] * len(Asset.ProjectDetails.number))

                # Call the generalized function for user-defined profile calculation
                o_secondary_infrastructure_payment_user_defined_profile = fn_calculate_user_defined_profile(
                    template=o_secondary_infrastructure_payment_user_defined_profile,
                    profile_options=payment_profile_option_series,
                    schedules=_get_named_range_value("s.landco.secondary.infrastructure.payment"),
                    start_dates=Asset.SecondaryInfrastructureModule.payment_start_date,
                    durations=Asset.SecondaryInfrastructureModule.payment_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # SECONDARY INFRASTRUCTURE COST (AMOUNT)
                # ============================================================================================
            
                # Call the function to calculate the secondary infrastructure cost amount
                secondary_infrastructure_cost_amount = fn_calculate_infrastructure_cost_amount(
                    asset_override=Asset.SecondaryInfrastructureModule.override,
                    asset_calculation_approach=Asset.SecondaryInfrastructureModule.calculation_approach,
                    asset_ad_hoc_amount=Asset.SecondaryInfrastructureModule.ad_hoc_amount,
                    asset_cost_basis_key=Asset.SecondaryInfrastructureModule.cost_basis,
                    asset_cost_per_sqm=Asset.SecondaryInfrastructureModule.cost_per_sqm,
                
                    global_calculation_approach=Global.InfrastructureCosts.secondary_infrastructure_calculation_approach,
                    global_allocation_basis_key=Global.InfrastructureCosts.secondary_infrastructure_allocation_basis,
                    global_cost_basis_key=Global.InfrastructureCosts.secondary_infrastructure_cost_basis,
                    global_cost_per_sqm=Global.InfrastructureCosts.secondary_infrastructure_cost_per_sqm,
                    global_ad_hoc_amount=Global.InfrastructureCosts.secondary_infrastructure_ad_hoc_amount
                )
           
                # ============================================================================================
                # SECONDARY INFRASTRUCTURE COST (ESCALATION WORKING)
                # ============================================================================================

                w_secondary_infrastructure_monthly_escalation_percent = _create_zero_df()

                w_secondary_infrastructure_monthly_escalation_factors = _create_zero_df()

                # Determine payment profile option for transformation (vectorized calculation)
                secondary_infrastructure_escalation_profile = np.where(
                    pd.Series(Asset.SecondaryInfrastructureModule.override) == "Yes",
                    pd.Series(Asset.SecondaryInfrastructureModule.escalation_profile).astype(str),
                    str(Global.InfrastructureCosts.secondary_infrastructure_escalation_profile)
                )

                # Vectorized construction start flag creation using broadcasting
                start_dates_arr = np.array(secondary_infrastructure_construction_start_dates).reshape(-1, 1)
                period_starts_arr = _period_starts.reshape(1, -1)
                w_secondary_infrastructure_construction_start_flag = pd.DataFrame(
                    (start_dates_arr == period_starts_arr).astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # Call the generalized function for monthly escalation profile calculation
                w_secondary_infrastructure_monthly_escalation_percent, w_secondary_infrastructure_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_secondary_infrastructure_monthly_escalation_percent,
                    escalation_factor_template=w_secondary_infrastructure_monthly_escalation_factors,
                    selected_escalation_profile=secondary_infrastructure_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                w_secondary_infrastructure_monthly_escalation_factor_mapping = _create_zero_df()

                w_secondary_infrastructure_monthly_escalation_factor_mapping = w_secondary_infrastructure_monthly_escalation_factors * w_secondary_infrastructure_construction_start_flag
            
                # ============================================================================================
                # SECONDARY INFRASTRUCTURE COST PAYMENT (ESCALATED)
                # ============================================================================================

                o_secondary_infrastructure_cost_payment = _create_zero_df()

                o_secondary_infrastructure_cost_payment = fn_calculate_infrastructure_cost_payment(
                    asset_base_amount=secondary_infrastructure_cost_amount,
                    schedule=o_secondary_infrastructure_payment_user_defined_profile,
                    escalation_factor_mapping=w_secondary_infrastructure_monthly_escalation_factor_mapping,
                    template=template_asset_timeline.copy()
                )

                # ============================================================================================
                # SECONDARY INFRASTRUCTURE COST S-CURVE (ESCALATED)
                # ============================================================================================

                o_secondary_infrastructure_cost_s_curve = _create_zero_df()

                o_secondary_infrastructure_cost_s_curve = o_secondary_infrastructure_s_curve_percent.mul(o_secondary_infrastructure_cost_payment.sum(axis=1), axis=0)

                # ============================================================================================
                # TOTAL INFRASTRUCTURE COST PAYMENT (ESCALATED)
                # ============================================================================================
            
                o_total_infrastructure_cost_payment = _create_zero_df()

                o_total_infrastructure_cost_payment = (
                    o_primary_infrastructure_cost_payment + o_secondary_infrastructure_cost_payment
                )

                # ============================================================================================
                # TOTAL INFRASTRUCTURE COST S-CURVE (ESCALATED)
                # ============================================================================================

                o_total_infrastructure_cost_s_curve = _create_zero_df()

                o_total_infrastructure_cost_s_curve = (
                    o_primary_infrastructure_cost_s_curve + o_secondary_infrastructure_cost_s_curve
                )

                # ============================================================================================
                # EXPORT INFRASTRUCTURE DATAFRAMES TO EXCEL
                # ============================================================================================

                if _EXPORT_FLAGS.get('infrastructure', False):
                    _infrastructure_exports = {
                        # Primary Infrastructure: Base Amount & Phasing
                        'Pri Infra Amount': primary_infrastructure_cost_amount,
                        'Pri Infra User Phasing': w_primary_infrastructure_s_curve_percent_user_defined,
                        'Pri Infra Pre Phasing': w_primary_infrastructure_s_curve_percent_pre_defined,
                        'Pri Infra Phasing': o_primary_infrastructure_s_curve_percent,
                        # Primary Infrastructure: Construction Period & Payment
                        'Pri Infra Cons Start': w_primary_infrastructure_construction_start_flag,
                        'Pri Infra Payment Profile': o_primary_infrastructure_payment_user_defined_profile,
                        # Primary Infrastructure: Escalation
                        'Pri Infra Esc %': w_primary_infrastructure_monthly_escalation_percent,
                        'Pri Infra Esc Factor': w_primary_infrastructure_monthly_escalation_factors,
                        'Pri Infra Esc Mapping': w_primary_infrastructure_monthly_escalation_factor_mapping,
                        # Primary Infrastructure: Payment & Cost S-Curve
                        'Pri Infra Payment': o_primary_infrastructure_cost_payment,
                        'Pri Infra Cost S-Curve': o_primary_infrastructure_cost_s_curve,
                        # Secondary Infrastructure: Base Amount & Phasing
                        'Sec Infra Amount': secondary_infrastructure_cost_amount,
                        'Sec Infra User Phasing': w_secondary_infrastructure_s_curve_percent_user_defined,
                        'Sec Infra Pre Phasing': w_secondary_infrastructure_s_curve_percent_pre_defined,
                        'Sec Infra Phasing': o_secondary_infrastructure_s_curve_percent,
                        # Secondary Infrastructure: Construction Period & Payment
                        'Sec Infra Cons Start': w_secondary_infrastructure_construction_start_flag,
                        'Sec Infra Payment Profile': o_secondary_infrastructure_payment_user_defined_profile,
                        # Secondary Infrastructure: Escalation
                        'Sec Infra Esc %': w_secondary_infrastructure_monthly_escalation_percent,
                        'Sec Infra Esc Factor': w_secondary_infrastructure_monthly_escalation_factors,
                        'Sec Infra Esc Mapping': w_secondary_infrastructure_monthly_escalation_factor_mapping,
                        # Secondary Infrastructure: Payment & Cost S-Curve
                        'Sec Infra Payment': o_secondary_infrastructure_cost_payment,
                        'Sec Infra Cost S-Curve': o_secondary_infrastructure_cost_s_curve,
                        # Total Infrastructure: Payment & Cost S-Curve
                        'Total Infra Payment': o_total_infrastructure_cost_payment,
                        'Total Infra S-Curve': o_total_infrastructure_cost_s_curve
                    }
                    _export_to_excel(_infrastructure_exports, 'export_infrastructure', 'Infrastructure')

                # ============================================================================================
                # USER DEFINED DESIGN COST PHASING PROFILE
                # ============================================================================================


                return (
                    o_primary_infrastructure_s_curve_percent,
                    o_primary_infrastructure_cost_payment,
                    o_primary_infrastructure_cost_s_curve,
                    o_secondary_infrastructure_s_curve_percent,
                    o_secondary_infrastructure_cost_payment,
                    o_secondary_infrastructure_cost_s_curve,
                    o_total_infrastructure_cost_payment,
                    o_total_infrastructure_cost_s_curve,
                )

            _fut_infrastructure = _shared_executor.submit(_compute_infrastructure)

            # ============================================================
            # WAVE-1 GATHER: Resolve infrastructure future results
            # ============================================================
            (
                o_primary_infrastructure_s_curve_percent,
                o_primary_infrastructure_cost_payment,
                o_primary_infrastructure_cost_s_curve,
                o_secondary_infrastructure_s_curve_percent,
                o_secondary_infrastructure_cost_payment,
                o_secondary_infrastructure_cost_s_curve,
                o_total_infrastructure_cost_payment,
                o_total_infrastructure_cost_s_curve,
            ) = _fut_infrastructure.result()

            _record_timing("Infrastructure Cost Module")

            w_design_cost_payment_user_defined_phasing = _create_zero_df()

            design_cost_user_defined_phasing = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                pd.Series(Asset.DesignCostModule.s_curve_option),
                "Pre Defined"  # Replaced Global.InfrastructureCosts.primary_infrastructure_phasing with "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_design_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
                template=w_design_cost_payment_user_defined_phasing,
                profile_options=design_cost_user_defined_phasing,
                schedules=_get_named_range_value("s.landco.design.cost.phasing"),
                start_dates=Asset.DesignCostModule.start_date,
                durations=Asset.DesignCostModule.duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED DESIGN COST PHASING PROFILE
            # ============================================================================================

            w_design_cost_pre_defined_phasing = _create_zero_df()

            # Determine payment profile option for design cost (vectorized calculation)
            design_cost_pre_defined_phasing_option = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                Asset.DesignCostModule.s_curve_option,
                "Pre Defined"
            )

            # Determine payment profile for design cost (vectorized calculation)
            design_cost_selected_phasing_profile = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                Asset.DesignCostModule.pre_defined_s_curve,
                Global.SoftCosts.design_cost_phasing
            )

            # Determine start dates for design cost (vectorized calculation)
            design_cost_start_dates = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                Asset.DesignCostModule.start_date,
                Global.SoftCosts.design_cost_start_date
            )

            # Call the generalized function for pre-defined profile calculation
            w_design_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
                template=w_design_cost_pre_defined_phasing,
                profile_option=design_cost_pre_defined_phasing_option,
                selected_pre_defined_profile=design_cost_selected_phasing_profile,
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
                
                asset_override=Asset.DesignCostModule.override,
                asset_cost_amount=Asset.DesignCostModule.amount,
                
                global_allocation_basis=Global.SoftCosts.design_cost_allocation_basis,
                global_cost_basis=Global.SoftCosts.design_cost_cost_basis,
                global_ad_hoc_amount=Global.SoftCosts.design_cost_ad_hoc_amount,
                global_cost_per_sqm=Global.SoftCosts.design_cost_cost_per_sqm,
                global_cost_percent=Global.SoftCosts.design_cost_cost_percent,
                global_calculation_approach=Global.SoftCosts.design_cost_calculation_approach,
                
                primary_infrastructure_cost_df=o_primary_infrastructure_cost_payment,
                secondary_infrastructure_cost_df=o_secondary_infrastructure_cost_payment,
                total_infrastructure_cost_df=o_total_infrastructure_cost_payment
            )

            # ============================================================================================
            # DESIGN COST (ESCALATION WORKING)
            # ============================================================================================

            w_design_cost_monthly_escalation_percent = _create_zero_df()

            w_design_cost_monthly_escalation_factors = _create_zero_df()

            # Determine payment profile option for transformation (vectorized calculation)
            design_cost_escalation_profile = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                pd.Series(Asset.DesignCostModule.escalation_profile).astype(str),
                str(Global.SoftCosts.design_cost_escalation_profile)
            )

            # Enforce consistent datetime dtype before broadcasting
            design_cost_start_dates = pd.to_datetime(design_cost_start_dates, errors="coerce")
            _period_starts = pd.to_datetime(_period_starts, errors="coerce")

            # Vectorized design cost start flag creation using broadcasting
            start_dates_arr = np.array(design_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts.to_numpy().reshape(1, -1)
            w_design_cost_start_flag = pd.DataFrame(
                (start_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # Call the generalized function for monthly escalation profile calculation
            w_design_cost_monthly_escalation_percent, w_design_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_design_cost_monthly_escalation_percent,
                escalation_factor_template=w_design_cost_monthly_escalation_factors,
                selected_escalation_profile=design_cost_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            w_design_cost_monthly_escalation_factor_mapping = _create_zero_df()

            temp_zero_escalation_factor = _create_zero_df()
            temp_zero_escalation_factor.iloc[:, :] = 1

            w_design_cost_escalation_applicability_flag = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                1,
                0 if Global.SoftCosts.design_cost_calculation_approach == "% of" else 1
            )

            w_design_cost_escalation_applicability_flag_mapping = _create_zero_df()
            w_design_cost_escalation_applicability_flag_mapping.iloc[:, :] = 1

            w_design_cost_escalation_applicability_flag_mapping = w_design_cost_escalation_applicability_flag_mapping.mul(w_design_cost_escalation_applicability_flag, axis=0)

            w_design_cost_monthly_escalation_factor_mapping = (
                w_design_cost_monthly_escalation_factors
                .mul(w_design_cost_start_flag)
                .where(w_design_cost_escalation_applicability_flag_mapping == 1,
                    w_design_cost_start_flag)
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

            permitting_cost_user_defined_phasing = np.where(
                pd.Series(Asset.PermittingCostModule.override) == "Yes",
                pd.Series(Asset.PermittingCostModule.s_curve_option),
                "Pre Defined"  # Replaced Global.InfrastructureCosts.primary_infrastructure_phasing with "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_permitting_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
                template=w_permitting_cost_payment_user_defined_phasing,
                profile_options=permitting_cost_user_defined_phasing,
                schedules=_get_named_range_value("s.landco.permitting.cost.phasing"),
                start_dates=Asset.PermittingCostModule.start_date,
                durations=Asset.PermittingCostModule.duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED PERMITTING COST PHASING PROFILE
            # ============================================================================================

            w_permitting_cost_pre_defined_phasing = _create_zero_df()

            # Determine payment profile option for permitting cost (vectorized calculation)
            permitting_cost_pre_defined_phasing_option = np.where(
                pd.Series(Asset.PermittingCostModule.override) == "Yes",
                Asset.PermittingCostModule.s_curve_option,
                "Pre Defined"
            )
            
            # Determine payment profile for permitting cost (vectorized calculation)
            permitting_cost_selected_phasing_profile = np.where(
                pd.Series(Asset.PermittingCostModule.override) == "Yes",
                Asset.PermittingCostModule.pre_defined_s_curve,
                Global.SoftCosts.permitting_cost_phasing
            )

            # Determine start dates for permitting cost (vectorized calculation)
            permitting_cost_start_dates = np.where(
                pd.Series(Asset.PermittingCostModule.override) == "Yes",
                Asset.PermittingCostModule.start_date,
                Global.SoftCosts.permitting_cost_start_date
            )

            # Call the generalized function for pre-defined profile calculation
            w_permitting_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
                template=w_permitting_cost_pre_defined_phasing,
                profile_option=permitting_cost_pre_defined_phasing_option,
                selected_pre_defined_profile=permitting_cost_selected_phasing_profile,
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
                
                asset_override=Asset.PermittingCostModule.override,
                asset_cost_amount=Asset.PermittingCostModule.amount,
                
                global_allocation_basis=Global.SoftCosts.permitting_cost_allocation_basis,
                global_cost_basis=Global.SoftCosts.permitting_cost_cost_basis,
                global_ad_hoc_amount=Global.SoftCosts.permitting_cost_ad_hoc_amount,
                global_cost_per_sqm=Global.SoftCosts.permitting_cost_cost_per_sqm,
                global_cost_percent=Global.SoftCosts.permitting_cost_cost_percent,
                global_calculation_approach=Global.SoftCosts.permitting_cost_calculation_approach,
                
                primary_infrastructure_cost_df=o_primary_infrastructure_cost_payment,
                secondary_infrastructure_cost_df=o_secondary_infrastructure_cost_payment,
                total_infrastructure_cost_df=o_total_infrastructure_cost_payment
            )

            # ============================================================================================
            # PERMITTING COST (ESCALATION WORKING)
            # ============================================================================================

            w_permitting_cost_monthly_escalation_percent = _create_zero_df()

            w_permitting_cost_monthly_escalation_factors = _create_zero_df()

            # Determine payment profile option for transformation (vectorized calculation)
            permitting_cost_escalation_profile = np.where(
                pd.Series(Asset.PermittingCostModule.override) == "Yes",
                pd.Series(Asset.PermittingCostModule.escalation_profile).astype(str),
                str(Global.SoftCosts.permitting_cost_escalation_profile)
            )

            # Enforce consistent datetime dtype before broadcasting
            permitting_cost_start_dates = pd.to_datetime(permitting_cost_start_dates, errors="coerce")

            # Vectorized permitting cost start flag creation using broadcasting
            start_dates_arr = np.array(permitting_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts.to_numpy().reshape(1, -1)
            w_permitting_cost_start_flag = pd.DataFrame(
                (start_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # Call the generalized function for monthly escalation profile calculation
            w_permitting_cost_monthly_escalation_percent, w_permitting_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_permitting_cost_monthly_escalation_percent,
                escalation_factor_template=w_permitting_cost_monthly_escalation_factors,
                selected_escalation_profile=permitting_cost_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            w_permitting_cost_monthly_escalation_factor_mapping = _create_zero_df()

            temp_zero_escalation_factor = _create_zero_df()
            temp_zero_escalation_factor.iloc[:, :] = 1

            w_permitting_cost_escalation_applicability_flag = np.where(
                pd.Series(Asset.DesignCostModule.override) == "Yes",
                1,
                0 if Global.SoftCosts.permitting_cost_calculation_approach == "% of" else 1
            )

            w_permitting_cost_escalation_applicability_flag_mapping = _create_zero_df()
            w_permitting_cost_escalation_applicability_flag_mapping.iloc[:, :] = 1

            w_permitting_cost_escalation_applicability_flag_mapping = w_permitting_cost_escalation_applicability_flag_mapping.mul(w_permitting_cost_escalation_applicability_flag, axis=0)

            w_permitting_cost_monthly_escalation_factor_mapping = (
                w_permitting_cost_monthly_escalation_factors
                .mul(w_permitting_cost_start_flag)
                .where(w_permitting_cost_escalation_applicability_flag_mapping == 1,
                    w_permitting_cost_start_flag)
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

            supervision_cost_user_defined_phasing = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                pd.Series(Asset.SupervisionCostModule.s_curve_option),
                "Pre Defined"  # Replaced Global.InfrastructureCosts.primary_infrastructure_phasing with "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_supervision_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
                template=w_supervision_cost_payment_user_defined_phasing,
                profile_options=supervision_cost_user_defined_phasing,
                schedules=_get_named_range_value("s.landco.supervision.cost.phasing"),
                start_dates=Asset.SupervisionCostModule.start_date,
                durations=Asset.SupervisionCostModule.duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED SUPERVISION COST PHASING PROFILE
            # ============================================================================================

            w_supervision_cost_pre_defined_phasing = _create_zero_df()

            # Determine payment profile option for supervision cost (vectorized calculation)
            supervision_cost_pre_defined_phasing_option = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                Asset.SupervisionCostModule.s_curve_option,
                "Pre Defined"
            )

            # Determine payment profile for supervision cost (vectorized calculation)
            supervision_cost_selected_phasing_profile = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                Asset.SupervisionCostModule.pre_defined_s_curve,
                Global.SoftCosts.supervision_cost_phasing
            )

            # Determine start dates for supervision cost (vectorized calculation)
            supervision_cost_start_dates = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                Asset.SupervisionCostModule.start_date,
                Global.SoftCosts.supervision_cost_start_date
            )

            # Call the generalized function for pre-defined profile calculation
            w_supervision_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
                template=w_supervision_cost_pre_defined_phasing,
                profile_option=supervision_cost_pre_defined_phasing_option,
                selected_pre_defined_profile=supervision_cost_selected_phasing_profile,
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
                
                asset_override=Asset.SupervisionCostModule.override,
                asset_cost_amount=Asset.SupervisionCostModule.amount,
                
                global_allocation_basis=Global.SoftCosts.supervision_cost_allocation_basis,
                global_cost_basis=Global.SoftCosts.supervision_cost_cost_basis,
                global_ad_hoc_amount=Global.SoftCosts.supervision_cost_ad_hoc_amount,
                global_cost_per_sqm=Global.SoftCosts.supervision_cost_cost_per_sqm,
                global_cost_percent=Global.SoftCosts.supervision_cost_cost_percent,
                global_calculation_approach=Global.SoftCosts.supervision_cost_calculation_approach,
                
                primary_infrastructure_cost_df=o_primary_infrastructure_cost_payment,
                secondary_infrastructure_cost_df=o_secondary_infrastructure_cost_payment,
                total_infrastructure_cost_df=o_total_infrastructure_cost_payment
            )

            # ============================================================================================
            # SUPERVISION COST (ESCALATION WORKING)
            # ============================================================================================

            w_supervision_cost_monthly_escalation_percent = _create_zero_df()

            w_supervision_cost_monthly_escalation_factors = _create_zero_df()

            # Determine payment profile option for transformation (vectorized calculation)
            supervision_cost_escalation_profile = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                pd.Series(Asset.SupervisionCostModule.escalation_profile).astype(str),
                str(Global.SoftCosts.supervision_cost_escalation_profile)
            )

            # Enforce consistent datetime dtype before broadcasting
            supervision_cost_start_dates = pd.to_datetime(supervision_cost_start_dates, errors="coerce")

            # Vectorized supervision cost start flag creation using broadcasting
            start_dates_arr = np.array(supervision_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts.to_numpy().reshape(1, -1)
            w_supervision_cost_start_flag = pd.DataFrame(
                (start_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # Call the generalized function for monthly escalation profile calculation
            w_supervision_cost_monthly_escalation_percent, w_supervision_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_supervision_cost_monthly_escalation_percent,
                escalation_factor_template=w_supervision_cost_monthly_escalation_factors,
                selected_escalation_profile=supervision_cost_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            w_supervision_cost_monthly_escalation_factor_mapping = _create_zero_df()

            temp_zero_escalation_factor = _create_zero_df()
            temp_zero_escalation_factor.iloc[:, :] = 1

            w_supervision_cost_escalation_applicability_flag = np.where(
                pd.Series(Asset.SupervisionCostModule.override) == "Yes",
                1,
                0 if Global.SoftCosts.supervision_cost_calculation_approach == "% of" else 1
            )

            w_supervision_cost_escalation_applicability_flag_mapping = _create_zero_df()
            w_supervision_cost_escalation_applicability_flag_mapping.iloc[:, :] = 1

            w_supervision_cost_escalation_applicability_flag_mapping = w_supervision_cost_escalation_applicability_flag_mapping.mul(w_supervision_cost_escalation_applicability_flag, axis=0)

            w_supervision_cost_monthly_escalation_factor_mapping = (
                w_supervision_cost_monthly_escalation_factors
                .mul(w_supervision_cost_start_flag)
                .where(w_supervision_cost_escalation_applicability_flag_mapping == 1,
                    w_supervision_cost_start_flag)
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
            # USER DEFINED PROJECT MANAGEMENT COST PHASING PROFILE
            # ============================================================================================

            w_project_management_cost_payment_user_defined_phasing = _create_zero_df()

            project_management_cost_user_defined_phasing = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                pd.Series(Asset.ProjectManagementCostModule.s_curve_option),
                "Pre Defined"  # Replaced Global.InfrastructureCosts.primary_infrastructure_phasing with "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_project_management_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
                template=w_project_management_cost_payment_user_defined_phasing,
                profile_options=project_management_cost_user_defined_phasing,
                schedules=_get_named_range_value("s.landco.project.management.cost.phasing"),
                start_dates=Asset.ProjectManagementCostModule.start_date,
                durations=Asset.ProjectManagementCostModule.duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED PROJECT MANAGEMENT COST PHASING PROFILE
            # ============================================================================================

            w_project_management_cost_pre_defined_phasing = _create_zero_df()

            # Determine payment profile option for project management cost (vectorized calculation)
            project_management_cost_pre_defined_phasing_option = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                Asset.ProjectManagementCostModule.s_curve_option,
                "Pre Defined"
            )

            # Determine payment profile for project management cost (vectorized calculation)
            project_management_cost_selected_phasing_profile = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                Asset.ProjectManagementCostModule.pre_defined_s_curve,
                Global.SoftCosts.project_management_cost_phasing
            )

            # Determine start dates for project management cost (vectorized calculation)
            project_management_cost_start_dates = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                Asset.ProjectManagementCostModule.start_date,
                Global.SoftCosts.project_management_cost_start_date
            )

            # Call the generalized function for pre-defined profile calculation
            w_project_management_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
                template=w_project_management_cost_pre_defined_phasing,
                profile_option=project_management_cost_pre_defined_phasing_option,
                selected_pre_defined_profile=project_management_cost_selected_phasing_profile,
                start_dates=project_management_cost_start_dates,
                predefined_profile_names=predefined_profile_names,
                predefined_profile_data=predefined_profile_data,
                predefined_profile_durations=predefined_profile_durations,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # CONSOLIDATED PROJECT MANAGEMENT COST PHASING PROFILE
            # ============================================================================================

            o_project_management_cost_phasing = _create_zero_df()

            o_project_management_cost_phasing = (
                w_project_management_cost_payment_user_defined_phasing + w_project_management_cost_pre_defined_phasing
            )

            # ============================================================================================
            # PROJECT MANAGEMENT COST (AMOUNT)
            # ============================================================================================

            project_management_cost_amount = fn_calculate_soft_and_contingency_cost_amount(
                template=template_asset_timeline.copy(),
                
                asset_override=Asset.ProjectManagementCostModule.override,
                asset_cost_amount=Asset.ProjectManagementCostModule.amount,

                global_allocation_basis=Global.SoftCosts.project_management_cost_allocation_basis,
                global_cost_basis=Global.SoftCosts.project_management_cost_cost_basis,
                global_ad_hoc_amount=Global.SoftCosts.project_management_cost_ad_hoc_amount,
                global_cost_per_sqm=Global.SoftCosts.project_management_cost_cost_per_sqm,
                global_cost_percent=Global.SoftCosts.project_management_cost_cost_percent,
                global_calculation_approach=Global.SoftCosts.project_management_cost_calculation_approach,
                
                primary_infrastructure_cost_df=o_primary_infrastructure_cost_payment,
                secondary_infrastructure_cost_df=o_secondary_infrastructure_cost_payment,
                total_infrastructure_cost_df=o_total_infrastructure_cost_payment
            )

            # ============================================================================================
            # PROJECT MANAGEMENT COST (ESCALATION WORKING)
            # ============================================================================================

            w_project_management_cost_monthly_escalation_percent = _create_zero_df()

            w_project_management_cost_monthly_escalation_factors = _create_zero_df()

            # Determine payment profile option for transformation (vectorized calculation)
            project_management_cost_escalation_profile = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                pd.Series(Asset.ProjectManagementCostModule.escalation_profile).astype(str),
                str(Global.SoftCosts.project_management_cost_escalation_profile)
            )

            # Enforce consistent datetime dtype before broadcasting
            project_management_cost_start_dates = pd.to_datetime(project_management_cost_start_dates, errors="coerce")

            # Vectorized project management cost start flag creation using broadcasting
            start_dates_arr = np.array(project_management_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts.to_numpy().reshape(1, -1)
            w_project_management_cost_start_flag = pd.DataFrame(
                (start_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # Call the generalized function for monthly escalation profile calculation
            w_project_management_cost_monthly_escalation_percent, w_project_management_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_project_management_cost_monthly_escalation_percent,
                escalation_factor_template=w_project_management_cost_monthly_escalation_factors,
                selected_escalation_profile=project_management_cost_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            w_project_management_cost_monthly_escalation_factor_mapping = _create_zero_df()

            temp_zero_escalation_factor = _create_zero_df()
            temp_zero_escalation_factor.iloc[:, :] = 1

            w_project_management_cost_escalation_applicability_flag = np.where(
                pd.Series(Asset.ProjectManagementCostModule.override) == "Yes",
                1,
                0 if Global.SoftCosts.project_management_cost_calculation_approach == "% of" else 1
            )

            w_project_management_cost_escalation_applicability_flag_mapping = _create_zero_df()
            w_project_management_cost_escalation_applicability_flag_mapping.iloc[:, :] = 1
                
            w_project_management_cost_escalation_applicability_flag_mapping = w_project_management_cost_escalation_applicability_flag_mapping.mul(w_project_management_cost_escalation_applicability_flag, axis=0)

            w_project_management_cost_monthly_escalation_factor_mapping = (
                w_project_management_cost_monthly_escalation_factors
                .mul(w_project_management_cost_start_flag)
                .where(w_project_management_cost_escalation_applicability_flag_mapping == 1,
                    w_project_management_cost_start_flag)
            )

            # ============================================================================================
            # PROJECT MANAGEMENT COST PAYMENT (ESCALATED)
            # ============================================================================================

            o_project_management_cost_payment = _create_zero_df()

            o_project_management_cost_payment = fn_calculate_soft_and_contingency_cost_payment(
                asset_base_amount=project_management_cost_amount,
                schedule=o_project_management_cost_phasing,
                escalation_factor_mapping=w_project_management_cost_monthly_escalation_factor_mapping,
                template=template_asset_timeline.copy()
            )

            # ============================================================================================
            # TOTAL SOFT COST PAYMENT
            # ============================================================================================

            o_total_soft_cost_payment = _create_zero_df()

            o_total_soft_cost_payment = o_design_cost_payment + o_permitting_cost_payment + o_supervision_cost_payment + o_project_management_cost_payment

            # ============================================================================================
            # USER DEFINED CONTINGENCY COST PHASING PROFILE
            # ============================================================================================

            w_contingency_cost_payment_user_defined_phasing = _create_zero_df()

            contingency_cost_user_defined_phasing = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                pd.Series(Asset.ContingencyCostModule.s_curve_option),
                "Pre Defined"  # Replaced Global.InfrastructureCosts.primary_infrastructure_phasing with "Pre Defined"
            )

            # Call the generalized function for user-defined profile calculation
            w_contingency_cost_payment_user_defined_phasing = fn_calculate_user_defined_profile(
                template=w_contingency_cost_payment_user_defined_phasing,
                profile_options=contingency_cost_user_defined_phasing,
                schedules=_get_named_range_value("s.landco.contingency.cost.phasing"),
                start_dates=Asset.ContingencyCostModule.start_date,
                durations=Asset.ContingencyCostModule.duration,
                model_timeline_me=model_timeline_me
            )

            # ============================================================================================
            # PRE DEFINED CONTINGENCY COST PHASING PROFILE
            # ============================================================================================

            w_contingency_cost_pre_defined_phasing = _create_zero_df()

            # Determine payment profile option for project management cost (vectorized calculation)
            contingency_cost_pre_defined_phasing_option = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                Asset.ContingencyCostModule.s_curve_option,
                "Pre Defined"
            )

            # Determine payment profile for project management cost (vectorized calculation)
            contingency_cost_selected_phasing_profile = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                Asset.ContingencyCostModule.pre_defined_s_curve,
                Global.ContingencyCosts.contingency_cost_phasing
            )

            # Determine start dates for project management cost (vectorized calculation)
            contingency_cost_start_dates = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                Asset.ContingencyCostModule.start_date,
                Global.ContingencyCosts.contingency_cost_start_date
            )

            # Call the generalized function for pre-defined profile calculation
            w_contingency_cost_pre_defined_phasing = fn_calculate_pre_defined_profile(
                template=w_contingency_cost_pre_defined_phasing,
                profile_option=contingency_cost_pre_defined_phasing_option,
                selected_pre_defined_profile=contingency_cost_selected_phasing_profile,
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
                
                asset_override=Asset.ContingencyCostModule.override,
                asset_cost_amount=Asset.ContingencyCostModule.amount,

                global_allocation_basis=Global.ContingencyCosts.contingency_cost_allocation_basis,
                global_cost_basis=Global.ContingencyCosts.contingency_cost_cost_basis,
                global_ad_hoc_amount=Global.ContingencyCosts.contingency_cost_ad_hoc_amount,
                global_cost_per_sqm=Global.ContingencyCosts.contingency_cost_cost_per_sqm,
                global_cost_percent=Global.ContingencyCosts.contingency_cost_cost_percent,
                global_calculation_approach=Global.ContingencyCosts.contingency_cost_calculation_approach,
                
                primary_infrastructure_cost_df=o_primary_infrastructure_cost_payment,
                secondary_infrastructure_cost_df=o_secondary_infrastructure_cost_payment,
                total_infrastructure_cost_df=o_total_infrastructure_cost_payment,
                soft_cost_df=o_total_soft_cost_payment,
                total_infrastructure_and_soft_cost_df=o_total_infrastructure_cost_payment + o_total_soft_cost_payment
            )

            # ============================================================================================
            # CONTINGENCY COST (ESCALATION WORKING)
            # ============================================================================================

            w_contingency_cost_monthly_escalation_percent = _create_zero_df()

            w_contingency_cost_monthly_escalation_factors = _create_zero_df()

            # Determine payment profile option for transformation (vectorized calculation)
            contingency_cost_escalation_profile = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                pd.Series(Asset.ContingencyCostModule.escalation_profile).astype(str),
                str(Global.ContingencyCosts.contingency_cost_escalation_profile)
            )

            # Enforce consistent datetime dtype before broadcasting
            contingency_cost_start_dates = pd.to_datetime(contingency_cost_start_dates, errors="coerce")

            # Vectorized contingency cost start flag creation using broadcasting
            start_dates_arr = np.array(contingency_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts.to_numpy().reshape(1, -1)
            w_contingency_cost_start_flag = pd.DataFrame(
                (start_dates_arr == period_starts_arr).astype(int),
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # Call the generalized function for monthly escalation profile calculation
            w_contingency_cost_monthly_escalation_percent, w_contingency_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                escalation_percent_template=w_contingency_cost_monthly_escalation_percent,
                escalation_factor_template=w_contingency_cost_monthly_escalation_factors,
                selected_escalation_profile=contingency_cost_escalation_profile,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                model_timeline_me=model_timeline_me
            )

            w_contingency_cost_monthly_escalation_factor_mapping = _create_zero_df()

            temp_zero_escalation_factor = _create_zero_df()
            temp_zero_escalation_factor.iloc[:, :] = 1

            w_contingency_cost_escalation_applicability_flag = np.where(
                pd.Series(Asset.ContingencyCostModule.override) == "Yes",
                1,
                0 if Global.ContingencyCosts.contingency_cost_calculation_approach == "% of" else 1
            )

            w_contingency_cost_escalation_applicability_flag_mapping = _create_zero_df()
            w_contingency_cost_escalation_applicability_flag_mapping.iloc[:, :] = 1
                
            w_contingency_cost_escalation_applicability_flag_mapping = w_contingency_cost_escalation_applicability_flag_mapping.mul(w_contingency_cost_escalation_applicability_flag, axis=0)

            w_contingency_cost_monthly_escalation_factor_mapping = (
                w_contingency_cost_monthly_escalation_factors
                .mul(w_contingency_cost_start_flag)
                .where(w_contingency_cost_escalation_applicability_flag_mapping == 1,
                    w_contingency_cost_start_flag)
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

            # ============================================================================================
            # EXPORT SOFT COST AND CONTINGENCY DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('soft_cost_contingency', False):
                _soft_cost_contingency_exports = {
                    'Design Cost Amount': design_cost_amount,
                    'Design Cost Phasing': o_design_cost_phasing,
                    'Design Cost Esc %': w_design_cost_monthly_escalation_percent,
                    'Design Cost Esc Factor': w_design_cost_monthly_escalation_factors,
                    'Design Cost Mapping': w_design_cost_monthly_escalation_factor_mapping,
                    'Design Cost Payment': o_design_cost_payment,
                    'Permitting Cost Amount': permitting_cost_amount,
                    'Permitting Cost Phasing': o_permitting_cost_phasing,
                    'Permitting Cost Esc %': w_permitting_cost_monthly_escalation_percent,
                    'Permitting Esc Factor': w_permitting_cost_monthly_escalation_factors,
                    'Permitting Cost Mapping': w_permitting_cost_monthly_escalation_factor_mapping,
                    'Permitting Cost Payment': o_permitting_cost_payment,
                    'Supervision Cost Amount': supervision_cost_amount,
                    'Supervision Phasing': o_supervision_cost_phasing,
                    'Supervision Esc %': w_supervision_cost_monthly_escalation_percent,
                    'Supervision Esc Factor': w_supervision_cost_monthly_escalation_factors,
                    'Supervision Mapping': w_supervision_cost_monthly_escalation_factor_mapping,
                    'Supervision Payment': o_supervision_cost_payment,
                    'PM Cost Amount': project_management_cost_amount,
                    'PM Cost Phasing': o_project_management_cost_phasing,
                    'PM Cost Esc %': w_project_management_cost_monthly_escalation_percent,
                    'PM Cost Esc Factor': w_project_management_cost_monthly_escalation_factors,
                    'PM Cost Mapping': w_project_management_cost_monthly_escalation_factor_mapping,
                    'PM Cost Payment': o_project_management_cost_payment,
                    'Total Soft Cost Payment': o_total_soft_cost_payment,
                    'Contingency Amount': contingency_cost_amount,
                    'Contingency Phasing': o_contingency_cost_phasing,
                    'Contingency Esc %': w_contingency_cost_monthly_escalation_percent,
                    'Contingency Esc Factor': w_contingency_cost_monthly_escalation_factors,
                    'Contingency Mapping': w_contingency_cost_monthly_escalation_factor_mapping,
                    'Contingency Payment': o_contingency_cost_payment
                }
                _export_to_excel(_soft_cost_contingency_exports, 'export_soft_cost_contingency', 'Soft Cost & Contingency')

            # ========================================================================
            # SUB-MODULE 3.8: REVENUE MODULE
            # ========================================================================
            
            # ========================================================================
            # LAND LEASE MODULE
            # ========================================================================
            
            # ========================================================================
            # LAND LEASE FLAG AND GRACE PERIOD FLAG
            # ========================================================================

            _record_timing("Soft Cost & Contingency Module")

            # ============================================================
            # WAVE-2: Submit revenue calculation as background future
            # (runs concurrently with soft cost & contingency on main thread)
            # ============================================================
            def _compute_revenue():

                # Initialize flags
                o_land_lease_flag = _create_zero_df()

                o_land_lease_grace_period_flag = _create_zero_df()

                # Vectorized calculation of land lease flag and grace period flag
                business_models = pd.Series(Asset.BusinessModelModule.business_model)
                lease_start_dates = pd.Series(Asset.LandLeaseModule.lease_start_date)
                lease_durations = pd.Series(Asset.LandLeaseModule.lease_duration)
            
                grace_period_durations = np.where(
                    pd.Series(Asset.LandLeaseModule.land_lease_override) == "Yes",
                    pd.Series(Asset.LandLeaseModule.grace_period),
                    Global.LandLeaseInputs.grace_period
                )
                        
                # Calculate lease end dates vectorized
                lease_end_dates = pd.Series([pd.NaT] * len(lease_start_dates), index=lease_start_dates.index)
                valid_lease_mask = ~(pd.isna(lease_start_dates) | pd.isna(lease_durations))
                for idx in lease_start_dates.index[valid_lease_mask]:
                    lease_end_dates[idx] = lease_start_dates[idx] + pd.DateOffset(months=int(lease_durations[idx]))
            
                # Calculate grace period end dates vectorized
                grace_period_end_dates = pd.Series([pd.NaT] * len(lease_start_dates), index=lease_start_dates.index)
                valid_grace_mask = ~(pd.isna(lease_start_dates) | pd.isna(grace_period_durations))
                for idx in lease_start_dates.index[valid_grace_mask]:
                    grace_period_end_dates[idx] = lease_start_dates[idx] + pd.DateOffset(months=int(grace_period_durations[idx]))
            
                # Get period starts as numpy array for broadcasting
                period_starts = model_timeline_me["Period Start"].values
            
                # Create masks for Land Lease business model
                is_land_lease = (business_models == "Land Lease").values.reshape(-1, 1)
            
                # Replace None or NaT in dates with 0 for comparison, and ensure datetime dtype
                lease_start_dates = pd.to_datetime(lease_start_dates, errors="coerce").fillna(pd.Timestamp(0))
                lease_end_dates = pd.to_datetime(lease_end_dates, errors="coerce").fillna(pd.Timestamp(0))

                # Create start date and end date arrays for broadcasting
                start_arr = lease_start_dates.values.reshape(-1, 1)
                lease_end_arr = lease_end_dates.values.reshape(-1, 1)
                grace_end_arr = grace_period_end_dates.values.reshape(-1, 1)
                period_arr = period_starts.reshape(1, -1)
            
                # Vectorized comparison: start <= period < end for lease flag
                lease_flag_matrix = (start_arr <= period_arr) & (period_arr < lease_end_arr) & is_land_lease
                o_land_lease_flag = pd.DataFrame(
                    lease_flag_matrix.astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )
            
                # Vectorized comparison: start <= period < grace_end for grace period flag
                grace_flag_matrix = (start_arr <= period_arr) & (period_arr < grace_end_arr) & is_land_lease
                o_land_lease_grace_period_flag = pd.DataFrame(
                    grace_flag_matrix.astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # ============================================================================================
                # LAND LEASE (ESCALATION WORKING)
                # ============================================================================================
            
                w_land_lease_monthly_escalation_percent = _create_zero_df()

                w_land_lease_monthly_escalation_factors = _create_zero_df()

                w_land_lease_escalation_flag = _create_zero_df()

                # Vectorized escalation flag calculation: check if month matches lease start date
                lease_start_dates_esc = pd.Series(Asset.LandLeaseModule.lease_start_date)
                period_months = _period_months.reshape(1, -1)
            
                # Extract months from lease start dates using vectorized datetime accessor (handle NaT)
                lease_months_raw = pd.to_datetime(lease_start_dates_esc).dt.month.values
                lease_start_months = np.where(pd.notna(lease_months_raw), lease_months_raw, -1).reshape(-1, 1)
            
                # Vectorized comparison: month matches
                escalation_flag_matrix = (lease_start_months == period_months) & (lease_start_months != -1)
                w_land_lease_escalation_flag = pd.DataFrame(
                    escalation_flag_matrix.astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )
            
                w_land_lease_escalation_profile = np.where(
                    pd.Series(Asset.LandLeaseModule.land_lease_override) == "Yes",
                    pd.Series(Asset.LandLeaseModule.escalation_profile).astype(str),
                    str(Global.LandLeaseInputs.escalation_profile)
                )

                # Call the generalized function for monthly escalation profile calculation
                w_land_lease_monthly_escalation_percent, w_land_lease_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_land_lease_monthly_escalation_percent,
                    escalation_factor_template=w_land_lease_monthly_escalation_factors,
                    selected_escalation_profile=w_land_lease_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                w_land_lease_monthly_escalation_factor_mapping = _create_zero_df()

                w_land_lease_monthly_escalation_factor_mapping = w_land_lease_monthly_escalation_factors * w_land_lease_escalation_flag

                # Vectorized forward-fill: Replace 0s with NaN, set first column to 1 where 0, then forward fill
                w_land_lease_monthly_escalation_factor_mapping = w_land_lease_monthly_escalation_factor_mapping.replace(0, np.nan)
                w_land_lease_monthly_escalation_factor_mapping.iloc[:, 0] = w_land_lease_monthly_escalation_factor_mapping.iloc[:, 0].fillna(1)
                w_land_lease_monthly_escalation_factor_mapping = w_land_lease_monthly_escalation_factor_mapping.ffill(axis=1)

                # ============================================================================================
                # LAND LEASE - LEASE RATE
                # ============================================================================================

                # Vectorized lease rate calculation
                business_models = pd.Series(Asset.BusinessModelModule.business_model)

                lease_basis = np.where(
                    pd.Series(Asset.LandLeaseModule.land_lease_override) == "Yes",
                    pd.Series(Asset.LandLeaseModule.lease_calculation_basis),
                    Global.LandLeaseInputs.lease_calculation_basis
                )
            
                annual_lease_amount = np.where(
                    pd.Series(Asset.LandLeaseModule.land_lease_override) == "Yes",
                    pd.Series(Asset.LandLeaseModule.annual_lease_amount),
                    Global.LandLeaseInputs.annual_lease_amount
                )
            
                annual_yield = np.where(
                    pd.Series(Asset.LandLeaseModule.land_lease_override) == "Yes",
                    pd.Series(Asset.LandLeaseModule.annual_yield),
                    Global.LandLeaseInputs.annual_yield
                )
            
                sales_price = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_price),
                    Global.LandSalesInputs.sales_price
                )

                # Create masks for conditions
                lease_basis_mask = (business_models == "Land Lease") & (lease_basis == "Lease Basis")
                yield_basis_mask = (business_models == "Land Lease") & (lease_basis == "Yield Basis")

                # Calculate base rates per asset using np.where for vectorized assignment
                # This avoids FutureWarning about incompatible dtype when mask is all False
                w_land_lease_base_rate = pd.Series(
                    np.where(
                        lease_basis_mask,
                        annual_lease_amount,
                        np.where(
                            yield_basis_mask,
                            np.array(annual_yield, dtype=float) * np.array(sales_price, dtype=float),
                            0.0
                        )
                    ),
                    index=template_asset_timeline.index,
                    dtype=float
                )

                # Multiply by lease flag using broadcasting
                w_land_lease_rate = o_land_lease_flag.mul(w_land_lease_base_rate, axis=0)

                w_land_lease_rate /= 12  # Convert annual lease rate to monthly

                # ============================================================================================
                # LAND LEASE - LEASE RATE (ESCALATED)
                # ============================================================================================

                o_land_lease_rate_escalated = _create_zero_df()

                o_land_lease_rate_escalated = w_land_lease_rate * w_land_lease_monthly_escalation_factor_mapping

                # ============================================================================================
                # LAND LEASE OCCUPANCY
                # ============================================================================================

                o_land_lease_occupancy_percent = _create_zero_df()

                o_land_lease_profile_option = np.where(
                    pd.Series(Asset.BusinessModelModule.business_model) == "Land Lease",
                    "User Defined",
                    "None"
                )

                # Call the generalized function for user-defined profile calculation
                o_land_lease_occupancy_percent = fn_calculate_user_defined_profile(
                    template=o_land_lease_occupancy_percent,
                    profile_options=o_land_lease_profile_option,
                    schedules=_get_named_range_value("s.landco.land.lease.occupancy"),
                    start_dates=Asset.LandLeaseModule.lease_start_date,
                    durations=Asset.LandLeaseModule.lease_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # LAND LEASE REVENUE - (ESCALATED)
                # ============================================================================================

                o_land_lease_revenue = _create_zero_df()
                o_land_lease_revenue = o_land_lease_rate_escalated.mul(Asset.LandAreaModule.developable_land_area, axis=0) * o_land_lease_occupancy_percent

                # ============================================================================================
                # LAND LEASE REVENUE INCLUDING GRACE PERIOD - (ESCALATED)
                # ============================================================================================

                o_land_lease_revenue_including_grace_period = _create_zero_df()

                o_land_lease_revenue_including_grace_period = o_land_lease_revenue * (o_land_lease_flag - o_land_lease_grace_period_flag)

                # ============================================================================================
                # LAND LEASE ASSOCIATED OPERATING EXPENSES - (PERCENT OF LEASE)
                # ============================================================================================

                o_land_lease_associated_operating_expenses_percent = _create_zero_df()

                # Call the generalized function for user-defined profile calculation
                o_land_lease_associated_operating_expenses_percent = fn_calculate_user_defined_profile(
                    template=o_land_lease_associated_operating_expenses_percent,
                    profile_options=o_land_lease_profile_option,
                    schedules=_get_named_range_value("s.landco.land.lease.associated.operating.expenses"),
                    start_dates=Asset.LandLeaseModule.lease_start_date,
                    durations=Asset.LandLeaseModule.lease_duration,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # LAND LEASE ASSOCIATED OPERATING EXPENSES - (ESCALATED)
                # ============================================================================================

                o_land_lease_associated_operating_expenses = _create_zero_df()
            
                o_land_lease_associated_operating_expenses = o_land_lease_revenue * o_land_lease_associated_operating_expenses_percent
            
                # ============================================================================================
                # LAND LEASE EXIT PRICE - (ESCALATION WORKING)
                # ============================================================================================

                w_land_lease_exit_price_monthly_escalation_percent = _create_zero_df()

                w_land_lease_exit_price_monthly_escalation_factors = _create_zero_df()

                w_escalation_profile_for_land_lease_exit = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.escalation_profile),
                    Global.LandSalesInputs.escalation_profile
                )

                # Call the generalized function for monthly escalation profile calculation
                w_land_lease_exit_price_monthly_escalation_percent, w_land_lease_exit_price_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_land_lease_exit_price_monthly_escalation_percent,
                    escalation_factor_template=w_land_lease_exit_price_monthly_escalation_factors,
                    selected_escalation_profile=w_escalation_profile_for_land_lease_exit,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )
            
                # ============================================================================================
                # LAND LEASE EXIT PRICE - (ESCALATED)
                # ============================================================================================

                w_land_lease_exit_price_escalated = _create_zero_df()

                w_sales_price_for_land_lease = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_price),
                    Global.LandSalesInputs.sales_price
                )
    
                w_land_lease_exit_price_escalated = w_land_lease_exit_price_monthly_escalation_factors.mul(w_sales_price_for_land_lease, axis=0)

                # ============================================================================================
                # LAND LEASE - EXIT FLAG
                # ============================================================================================

                o_land_lease_exit_flag = _create_zero_df()
            
                # Vectorized land lease exit flag calculation
                business_models_exit = pd.Series(Asset.BusinessModelModule.business_model)
                lease_start_dates_exit = pd.Series(Asset.LandLeaseModule.lease_start_date)
                lease_durations_exit = pd.Series(Asset.LandLeaseModule.lease_duration)
            
                # Calculate lease end dates (start + duration - 1 month) vectorized
                lease_exit_dates = pd.Series([pd.NaT] * len(lease_start_dates_exit), index=lease_start_dates_exit.index)
                valid_exit_mask = (~pd.isna(lease_start_dates_exit)) & (~pd.isna(lease_durations_exit)) & (business_models_exit == "Land Lease")
                for idx in lease_start_dates_exit.index[valid_exit_mask]:
                    lease_exit_dates[idx] = lease_start_dates_exit[idx] + pd.DateOffset(months=int(lease_durations_exit[idx]) - 1)
            
                # Vectorized comparison: period_start == lease_exit_date
                exit_dates_arr = lease_exit_dates.values.reshape(-1, 1)
                period_starts_arr = model_timeline_me["Period Start"].values.reshape(1, -1)
                exit_flag_matrix = (exit_dates_arr == period_starts_arr)
                o_land_lease_exit_flag = pd.DataFrame(
                    exit_flag_matrix.astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # ============================================================================================
                # LAND LEASE - EXIT VALUE
                # ============================================================================================

                o_land_lease_exit_value = _create_zero_df()
            
                o_land_lease_exit_value = w_land_lease_exit_price_escalated.mul(Asset.LandAreaModule.developable_land_area, axis=0) * o_land_lease_exit_flag

                # ============================================================================================
                # EXPORT LAND LEASE DATAFRAMES TO EXCEL
                # ============================================================================================

                if _EXPORT_FLAGS.get('land_lease', False):
                    _land_lease_exports = {
                        'Lease Flag': o_land_lease_flag,
                        'Lease Grace Flag': o_land_lease_grace_period_flag,
                        'Lease Esc %': w_land_lease_monthly_escalation_percent,
                        'Lease Esc Factor': w_land_lease_monthly_escalation_factors,
                        'Lease Esc Flag': w_land_lease_escalation_flag,
                        'Lease Esc Mapping': w_land_lease_monthly_escalation_factor_mapping,
                        'Lease Rate': w_land_lease_rate,
                        'Lease Rate Escalated': o_land_lease_rate_escalated,
                        'Lease Occupancy %': o_land_lease_occupancy_percent,
                        'Lease Revenue': o_land_lease_revenue,
                        'Lease Rev Incl Grace': o_land_lease_revenue_including_grace_period,
                        'Lease OpEx %': o_land_lease_associated_operating_expenses_percent,
                        'Lease OpEx': o_land_lease_associated_operating_expenses,
                        'Exit Price Esc %': w_land_lease_exit_price_monthly_escalation_percent,
                        'Exit Price Esc Factor': w_land_lease_exit_price_monthly_escalation_factors,
                        'Exit Price Escalated': w_land_lease_exit_price_escalated,
                        'Exit Flag': o_land_lease_exit_flag,
                        'Exit Value': o_land_lease_exit_value,
                    }
                    _export_to_excel(_land_lease_exports, 'export_land_lease', 'Land Lease')

                # ============================================================================================
                # LANAD BANK MODULE
                # ============================================================================================

                # ============================================================================================
                # LAND BANK EXIT PRICE - (ESCALATION WORKING)
                # ============================================================================================

                w_land_bank_exit_price_monthly_escalation_percent = _create_zero_df()

                w_land_bank_exit_price_monthly_escalation_factors = _create_zero_df()
            
                w_land_bank_escalation_profile = np.where(
                    pd.Series(Asset.LandBankModule.land_bank_override) == "Yes",
                    pd.Series(Asset.LandBankModule.escalation_profile).astype(str),
                    str(Global.LandBankInputs.escalation_profile)
                )

                #  Call the generalized function for monthly escalation profile calculation
                w_land_bank_exit_price_monthly_escalation_percent, w_land_bank_exit_price_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_land_bank_exit_price_monthly_escalation_percent,
                    escalation_factor_template=w_land_bank_exit_price_monthly_escalation_factors,
                    selected_escalation_profile=w_land_bank_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )


                # ============================================================================================
                # LAND BANK EXIT PRICE - (ESCALATED)
                # ============================================================================================

                w_land_bank_exit_price_escalated = _create_zero_df()
            
                w_sales_price_for_land_bank = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_price),
                    Global.LandSalesInputs.sales_price
                )

                w_land_bank_exit_price_escalated = w_land_bank_exit_price_monthly_escalation_factors.mul(w_sales_price_for_land_bank, axis=0)

                # ============================================================================================
                # LAND BANK - EXIT FLAG
                # ============================================================================================

                o_land_bank_exit_flag = _create_zero_df()

                # Vectorized land bank exit flag calculation
                business_models_bank = pd.Series(Asset.BusinessModelModule.business_model)
            
                holding_periods = np.where(
                    pd.Series(Asset.LandBankModule.land_bank_override) == "Yes",
                    pd.Series(Asset.LandBankModule.holding_period),
                    Global.LandBankInputs.holding_period
                )
            
                # Calculate exit dates vectorized
                bank_exit_dates = pd.Series([pd.NaT] * len(w_acquisition_date), index=template_asset_timeline.index)
                valid_bank_mask = (~pd.isna(holding_periods)) & (holding_periods != 0) & (business_models_bank == "Land Bank")
                for idx in template_asset_timeline.index[valid_bank_mask]:
                    bank_exit_dates[idx] = w_acquisition_date[idx] + pd.DateOffset(months=int(holding_periods[idx]))
            
                # Vectorized comparison: period_start == exit_date
                bank_exit_arr = bank_exit_dates.values.reshape(-1, 1)
                period_starts_bank = model_timeline_me["Period Start"].values.reshape(1, -1)
                bank_exit_matrix = (bank_exit_arr == period_starts_bank)
                o_land_bank_exit_flag = pd.DataFrame(
                    bank_exit_matrix.astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # ============================================================================================
                # LAND BANK - EXIT VALUE
                # ============================================================================================
            
                o_land_bank_exit_value = _create_zero_df()

                o_land_bank_exit_value = w_land_bank_exit_price_escalated.mul(Asset.LandAreaModule.developable_land_area, axis=0) * o_land_bank_exit_flag

                # ============================================================================================
                # EXPORT LAND BANK DATAFRAMES TO EXCEL
                # ============================================================================================

                if _EXPORT_FLAGS.get('land_bank', False):
                    _land_bank_exports = {
                        'Exit Price Esc %': w_land_bank_exit_price_monthly_escalation_percent,
                        'Exit Price Esc Factor': w_land_bank_exit_price_monthly_escalation_factors,
                        'Exit Price Escalated': w_land_bank_exit_price_escalated,
                        'Exit Flag': o_land_bank_exit_flag,
                        'Exit Value': o_land_bank_exit_value,
                    }
                    _export_to_excel(_land_bank_exports, 'export_land_bank', 'Land Bank')

                # ============================================================================================
                # LAND SALE
                # ============================================================================================

                # ============================================================================================
                # LAND SALES PRICE - (ESCALATION WORKING)
                # ============================================================================================

                w_land_sales_price_monthly_escalation_percent = _create_zero_df()

                w_land_sales_price_monthly_escalation_factors = _create_zero_df()

                w_escalation_profile_for_land_sales = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.escalation_profile),
                    Global.LandSalesInputs.escalation_profile
                )

                # Call the generalized function for monthly escalation profile calculation
                w_land_sales_price_monthly_escalation_percent, w_land_sales_price_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_land_sales_price_monthly_escalation_percent,
                    escalation_factor_template=w_land_sales_price_monthly_escalation_factors,
                    selected_escalation_profile=w_escalation_profile_for_land_sales,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )
            
                # ============================================================================================
                # LAND SALES PRICE - (ESCALATED)
                # ============================================================================================

                w_land_sales_price_escalated = _create_zero_df()
            
                w_land_sales_price = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_price),
                    Global.LandSalesInputs.sales_price
                )

                w_land_sales_price_escalated = w_land_sales_price_monthly_escalation_factors.mul(w_land_sales_price, axis=0)

                # ============================================================================================
                # USER DEFINED SALES PHASING PROFILE
                # ============================================================================================
            
                w_land_sales_phasing_user_defined = _create_zero_df()

                # Determine phasing profile option (vectorized calculation)
                # If override is Yes, use asset-level option; otherwise use global option
                w_land_sale_phasing_option = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_phasing_option),
                    "Pre Defined"
                )

                # Apply "None" for non-Land Sale business models
                w_land_sale_phasing_option = np.where(
                    pd.Series(Asset.BusinessModelModule.business_model) == "Land Sale",
                    w_land_sale_phasing_option,
                    "None"
                )

                w_land_sales_start_date = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_start_date),
                    Global.LandSalesInputs.sales_start_date
                )

                # Call the generalized function for user-defined profile calculation
                w_land_sales_phasing_user_defined = fn_calculate_user_defined_profile(
                    template=w_land_sales_phasing_user_defined,
                    profile_options=w_land_sale_phasing_option,
                    schedules=_get_named_range_value("s.landco.sales.phasing"),
                    start_dates=w_land_sales_start_date,
                    durations=pd.Series(Asset.LandSalesModule.sales_duration),
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # PRE DEFINED SALES PHASING PROFILE
                # ============================================================================================

                w_land_sales_phasing_pre_defined = _create_zero_df()

                # Determine the pre-defined profile name based on override
                w_land_sale_selected_profile = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_phasing_profile),
                    Global.LandSalesInputs.sales_phasing_profile
                )

                # Call the generalized function for pre-defined profile calculation
                w_land_sales_phasing_pre_defined = fn_calculate_pre_defined_profile(
                    template=w_land_sales_phasing_pre_defined,
                    profile_option=w_land_sale_phasing_option,
                    selected_pre_defined_profile=w_land_sale_selected_profile,
                    start_dates=w_land_sales_start_date,
                    predefined_profile_names=predefined_profile_names,
                    predefined_profile_data=predefined_profile_data,
                    predefined_profile_durations=predefined_profile_durations,
                    model_timeline_me=model_timeline_me
                )

                # ============================================================================================
                # CONSOLIDATED SALES PHASING PROFILE
                # ============================================================================================

                o_land_sales_phasing = _create_zero_df()

                # Sum the pre-defined and user-defined profiles
                o_land_sales_phasing = (
                    w_land_sales_phasing_pre_defined + w_land_sales_phasing_user_defined
                )

                # ============================================================================================
                # SALES REVENUE CALCULATION
                # ============================================================================================
                o_land_sales_revenue = _create_zero_df()
            
                o_land_sales_revenue = w_land_sales_price_escalated.mul([0 if x is None else x for x in Asset.LandAreaModule.developable_land_area], axis=0) * o_land_sales_phasing

                # ============================================================================================
                # EXPORT LAND SALE DATAFRAMES TO EXCEL
                # ============================================================================================

                if _EXPORT_FLAGS.get('land_sale', False):
                    _land_sale_exports = {
                        'Sales Price Esc %': w_land_sales_price_monthly_escalation_percent,
                        'Sales Price Esc Factor': w_land_sales_price_monthly_escalation_factors,
                        'Sales Price Escalated': w_land_sales_price_escalated,
                        'Sales Phasing User Def': w_land_sales_phasing_user_defined,
                        'Sales Phasing Pre Def': w_land_sales_phasing_pre_defined,
                        'Sales Phasing': o_land_sales_phasing,
                        'Sales Revenue': o_land_sales_revenue,
                    }
                    _export_to_excel(_land_sale_exports, 'export_land_sale', 'Land Sale')

                # ============================================================================================
                # LEASING COSTS
                # ============================================================================================

                allocation_basis_mapping = {
                    "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                    "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                    "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
                    "Built Up Area": Asset.LandAreaModule.built_up_area,
                    "Gross Leasable Area": Asset.LandAreaModule.total_nsa__gla,
                    "Units": Asset.LandAreaModule.units,
                }

                cost_basis_mapping = {
                    "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                    "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                }

                w_lease_start_date = Asset.LandLeaseModule.lease_start_date
                w_leasing_cost_override = Asset.LeasingandDisposalCostModule.leasing_cost_override
                w_business_model = Asset.BusinessModelModule.business_model

                w_global_allocation_basis_values = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_allocation_basis_percent = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_ad_hoc_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized allocation basis calculation
                allocation_basis = Global.LeasingandDisposalCosts.leasing_costs_allocation_basis
                allocation_values = allocation_basis_mapping.get(allocation_basis, pd.Series(0, index=template_asset_timeline.index))
                is_land_lease_mask = pd.Series(w_business_model) == "Land Lease"
                is_not_override_mask = pd.Series(w_leasing_cost_override) != "Yes"
                w_global_allocation_basis_values = np.where(
                    is_land_lease_mask & is_not_override_mask,
                    allocation_values,
                    0
                )
                w_global_allocation_basis_values = pd.Series(w_global_allocation_basis_values, index=template_asset_timeline.index, dtype=float)

                w_global_allocation_basis_percent = w_global_allocation_basis_values / w_global_allocation_basis_values.sum() if w_global_allocation_basis_values.sum() != 0 else 0

                w_global_ad_hoc_amount = Global.LeasingandDisposalCosts.leasing_costs_ad_hoc_amount * w_global_allocation_basis_percent

                w_global_revenue_basis_values = pd.DataFrame(index=template_asset_timeline.index, columns=model_timeline_me["# of Period"], dtype=float)
                w_global_percent_of_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized revenue basis calculation using broadcasting
                lease_start_arr = pd.Series(w_lease_start_date).values.reshape(-1, 1)
                period_starts_arr = model_timeline_me["Period Start"].values.reshape(1, -1)
                start_match_mask = (lease_start_arr == period_starts_arr)
            
                # Calculate base revenue values (escalated rate * area * 12)
                base_revenue = o_land_lease_rate_escalated.values * pd.Series(Asset.LandAreaModule.developable_land_area).values.reshape(-1, 1) * 12
            
                # Apply mask: only keep values where period matches lease start date
                w_global_revenue_basis_values = pd.DataFrame(
                    np.where(start_match_mask, base_revenue, 0),
                    index=template_asset_timeline.index,
                    columns=model_timeline_me["# of Period"]
                )
            
                w_global_percent_of_amount = w_global_revenue_basis_values.sum(axis=1) * Global.LeasingandDisposalCosts.leasing_costs_cost_percent

                w_global_cost_basis_values = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_cost_per_sqm_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized cost basis calculation
                cost_basis = Global.LeasingandDisposalCosts.leasing_costs_cost_basis
                w_global_cost_basis_values = pd.Series(cost_basis_mapping.get(cost_basis, pd.Series(0, index=template_asset_timeline.index)))
            
                w_global_cost_per_sqm_amount = w_global_cost_basis_values * Global.LeasingandDisposalCosts.leasing_costs_cost_per_sqm

                w_global_cost_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                if Global.LeasingandDisposalCosts.leasing_costs_calculation_approach == "Ad-Hoc Amount":
                    w_global_cost_amount = np.where(is_land_lease_mask, w_global_ad_hoc_amount, 0)
                elif Global.LeasingandDisposalCosts.leasing_costs_calculation_approach == "SAR / SQM of":
                    w_global_cost_amount = np.where(is_land_lease_mask, w_global_cost_per_sqm_amount, 0)
                elif Global.LeasingandDisposalCosts.leasing_costs_calculation_approach == "% of Revenue":
                    w_global_cost_amount = w_global_percent_of_amount
 
                else:
                    w_global_cost_amount = 0

                w_cost_amount = pd.Series(index=template_asset_timeline.index, dtype=float)
            
                w_cost_amount = np.where(
                    pd.Series(w_leasing_cost_override) == "Yes",
                    pd.Series(Asset.LeasingandDisposalCostModule.leasing_cost_amount),
                    w_global_cost_amount
                )

                # ============================================================================================
                # LEASING COST - (ESCALATION WORKING)
                # ============================================================================================

                w_leasing_cost_monthly_escalation_percent = _create_zero_df()

                w_leasing_cost_monthly_escalation_factors = _create_zero_df()

                w_escalation_profile = np.where(
                    pd.Series(w_leasing_cost_override) == "Yes",
                    pd.Series(Asset.LeasingandDisposalCostModule.leasing_cost_escalation).astype(str),
                    str(Global.LeasingandDisposalCosts.leasing_costs_escalation_profile)
                )
           
                # Call the generalized function for monthly escalation profile calculation
                w_leasing_cost_monthly_escalation_percent, w_leasing_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_leasing_cost_monthly_escalation_percent,
                    escalation_factor_template=w_leasing_cost_monthly_escalation_factors,
                    selected_escalation_profile=w_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                w_leasing_cost_monthly_escalation_mapping = _create_zero_df()

                # Vectorized escalation mapping using broadcasting
                lease_start_dates_esc = pd.Series(Asset.LandLeaseModule.lease_start_date).values.reshape(-1, 1)
                period_starts_esc = model_timeline_me["Period Start"].values.reshape(1, -1)
                start_match_esc = (lease_start_dates_esc == period_starts_esc)
            
                w_leasing_cost_monthly_escalation_mapping = pd.DataFrame(
                    np.where(start_match_esc, w_leasing_cost_monthly_escalation_factors.values, 0),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                o_leasing_cost = _create_zero_df() # Initialize with 0.0

                o_leasing_cost = w_leasing_cost_monthly_escalation_mapping.mul(w_cost_amount, axis=0)

                # ============================================================================================
                # SALES TRANSACTION COSTS
                # ============================================================================================

                allocation_basis_mapping = {
                    "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                    "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                    "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
                    "Built Up Area": Asset.LandAreaModule.built_up_area,
                    "Gross Leasable Area": Asset.LandAreaModule.total_nsa__gla,
                    "Units": Asset.LandAreaModule.units,
                }

                cost_basis_mapping = {
                    "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                    "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                }
                w_land_lease_exit_date = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')
                w_sales_start_date = np.where(
                    pd.Series(Asset.LandSalesModule.land_sales_override) == "Yes",
                    pd.Series(Asset.LandSalesModule.sales_start_date),
                    Global.LandSalesInputs.sales_start_date
                )
                w_land_bank_exit_date = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')
                w_land_sale_date = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')

                w_business_model = Asset.BusinessModelModule.business_model

                # Vectorized calculation of exit dates
                lease_start_dates_v = pd.Series(Asset.LandLeaseModule.lease_start_date)
                lease_durations_v = pd.Series(Asset.LandLeaseModule.lease_duration)
                holding_periods_v = pd.Series(Asset.LandBankModule.holding_period)
                business_models_v = pd.Series(w_business_model)
            
                # Calculate land lease exit dates
                is_land_lease_v = (business_models_v == "Land Lease")
                for idx in template_asset_timeline.index[is_land_lease_v]:
                    if pd.notna(lease_start_dates_v[idx]) and pd.notna(lease_durations_v[idx]):
                        w_land_lease_exit_date[idx] = lease_start_dates_v[idx] + pd.DateOffset(months=int(lease_durations_v[idx]) - 1)
            
                # Calculate land bank exit dates
                is_land_bank_v = (business_models_v == "Land Bank") & (~pd.isna(w_acquisition_date))
                for idx in template_asset_timeline.index[is_land_bank_v]:
                    if pd.notna(holding_periods_v[idx]):
                        w_land_bank_exit_date[idx] = w_acquisition_date[idx] + pd.DateOffset(months=int(holding_periods_v[idx]))
            
                # Vectorized land sale date assignment
                w_land_sale_date = np.where(
                    business_models_v == "Land Sale",
                    w_sales_start_date,
                    np.where(
                        business_models_v == "Land Bank",
                        w_land_bank_exit_date,
                        np.where(
                            business_models_v == "Land Lease",
                            w_land_lease_exit_date,
                            pd.NaT
                        )
                    )
                )
                w_land_sale_date = pd.Series(w_land_sale_date, index=template_asset_timeline.index, dtype='datetime64[ns]')

                w_sales_transaction_cost_override = Asset.LeasingandDisposalCostModule.sales_transaction_cost_override


                w_global_allocation_basis_values = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_allocation_basis_percent = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_ad_hoc_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized allocation basis calculation
                allocation_basis_stc = Global.LeasingandDisposalCosts.sales_transaction_cost_allocation_basis
                allocation_values_stc = allocation_basis_mapping.get(allocation_basis_stc, pd.Series(0, index=template_asset_timeline.index))
                is_not_override_stc = pd.Series(w_sales_transaction_cost_override) != "Yes"
                w_global_allocation_basis_values = np.where(
                    is_not_override_stc,
                    allocation_values_stc,
                    0
                )
                w_global_allocation_basis_values = pd.Series(w_global_allocation_basis_values, index=template_asset_timeline.index, dtype=float)

                w_global_allocation_basis_percent = w_global_allocation_basis_values / w_global_allocation_basis_values.sum() if w_global_allocation_basis_values.sum() != 0 else 0

                w_global_ad_hoc_amount = Global.LeasingandDisposalCosts.leasing_costs_ad_hoc_amount * w_global_allocation_basis_percent


                w_global_percent_of_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized percent of amount calculation based on business model
                business_models_pct = pd.Series(w_business_model)
                cost_percent_stc = Global.LeasingandDisposalCosts.sales_transaction_cost_cost_percent
            
                w_global_percent_of_amount = pd.Series(0.0, index=template_asset_timeline.index, dtype=float)
                land_lease_mask_pct = (business_models_pct == "Land Lease")
                land_sale_mask_pct = (business_models_pct == "Land Sale")
                land_bank_mask_pct = (business_models_pct == "Land Bank")
            
                w_global_percent_of_amount[land_lease_mask_pct] = o_land_lease_exit_value.sum(axis=1)[land_lease_mask_pct] * cost_percent_stc
                w_global_percent_of_amount[land_sale_mask_pct] = o_land_sales_revenue.sum(axis=1)[land_sale_mask_pct] * cost_percent_stc
                w_global_percent_of_amount[land_bank_mask_pct] = o_land_bank_exit_value.sum(axis=1)[land_bank_mask_pct] * cost_percent_stc

                w_global_cost_basis_values = pd.Series(index=template_asset_timeline.index, dtype=float)
                w_global_cost_per_sqm_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                # Vectorized cost basis calculation
                cost_basis_stc = Global.LeasingandDisposalCosts.sales_transaction_cost_cost_basis
                w_global_cost_basis_values = pd.Series(cost_basis_mapping.get(cost_basis_stc, pd.Series(0, index=template_asset_timeline.index)))

                w_global_cost_per_sqm_amount = w_global_cost_basis_values * Global.LeasingandDisposalCosts.sales_transaction_cost_cost_per_sqm
                w_global_cost_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                if Global.LeasingandDisposalCosts.sales_transaction_cost_calculation_approach == "Ad-Hoc Amount":
                    w_global_cost_amount = w_global_ad_hoc_amount
                elif Global.LeasingandDisposalCosts.sales_transaction_cost_calculation_approach == "SAR / SQM of":
                    w_global_cost_amount = w_global_cost_per_sqm_amount
                elif Global.LeasingandDisposalCosts.sales_transaction_cost_calculation_approach == "% of Revenue":
                    w_global_cost_amount = w_global_percent_of_amount
                else:
                    w_global_cost_amount = 0
            
                w_cost_amount = pd.Series(index=template_asset_timeline.index, dtype=float)

                w_cost_amount = np.where(
                    pd.Series(w_sales_transaction_cost_override) == "Yes",
                    pd.Series(Asset.LeasingandDisposalCostModule.sales_transaction_cost_amount),
                    w_global_cost_amount
                )
            
                # ============================================================================================
                # SALES TRANSACTION COST - (ESCALATION WORKING)
                # ============================================================================================

                w_sales_transaction_cost_monthly_escalation_percent = _create_zero_df()

                w_sales_transaction_cost_monthly_escalation_factors = _create_zero_df()

                w_escalation_profile = np.where(
                    pd.Series(w_sales_transaction_cost_override) == "Yes",
                    pd.Series(Asset.LeasingandDisposalCostModule.sales_transaction_cost_escalation_profile).astype(str),
                    str(Global.LeasingandDisposalCosts.sales_transaction_cost_escalation_profile)
                )

                # Call the generalized function for monthly escalation profile calculation
                w_sales_transaction_cost_monthly_escalation_percent, w_sales_transaction_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_sales_transaction_cost_monthly_escalation_percent,
                    escalation_factor_template=w_sales_transaction_cost_monthly_escalation_factors,
                    selected_escalation_profile=w_escalation_profile,
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                w_sales_transaction_cost_monthly_escalation_mapping = _create_zero_df()

                # Apply escalation factors where sales phasing is non-zero (linked to sales phasing)
                w_sales_transaction_cost_monthly_escalation_mapping = pd.DataFrame(
                    np.where(o_land_sales_phasing.values > 0, w_sales_transaction_cost_monthly_escalation_factors.values, 0),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                o_sales_transaction_cost = _create_zero_df() # Initialize with 0.0

                # Sales transaction cost is multiplied by sales phasing to spread across the sales timeline
                o_sales_transaction_cost = o_land_sales_phasing.mul(w_cost_amount, axis=0) * w_sales_transaction_cost_monthly_escalation_mapping

                # ============================================================================================
                # COMBINED LEASING AND DISPOSAL COSTS
                # ============================================================================================

                o_leasing_and_disposal_costs = o_leasing_cost + o_sales_transaction_cost

                # ============================================================================================
                # EXPORT LEASING AND DISPOSAL COST DATAFRAMES TO EXCEL
                # ============================================================================================

                if _EXPORT_FLAGS.get('leasing_and_disposal_cost', False):
                    _leasing_and_disposal_cost_exports = {
                        'Leasing Cost Esc %': w_leasing_cost_monthly_escalation_percent,
                        'Leasing Cost Esc Factor': w_leasing_cost_monthly_escalation_factors,
                        'Leasing Cost Esc Mapping': w_leasing_cost_monthly_escalation_mapping,
                        'Leasing Cost': o_leasing_cost,
                        'Sales Trans Cost Esc %': w_sales_transaction_cost_monthly_escalation_percent,
                        'Sales Trans Cost Esc Factor': w_sales_transaction_cost_monthly_escalation_factors,
                        'Sales Trans Cost Esc Mapping': w_sales_transaction_cost_monthly_escalation_mapping,
                        'Sales Transaction Cost': o_sales_transaction_cost,
                        'Leasing and Disposal Costs': o_leasing_and_disposal_costs,
                    }
                    _export_to_excel(_leasing_and_disposal_cost_exports, 'export_leasing_and_disposal_cost', 'Leasing and Disposal Cost')

                # ========================================================================
                # SUB-MODULE 3.9: COMMUNITY OPERATIONS MODULE
                # ========================================================================
                # COMMUNITY OPERATIONS AMANAH
                # ========================================================================


                return (
                    o_land_lease_revenue,
                    o_land_lease_revenue_including_grace_period,
                    o_land_lease_exit_value,
                    o_land_lease_associated_operating_expenses,
                    o_land_sales_revenue,
                    o_land_sales_phasing,
                    o_land_bank_exit_value,
                    o_leasing_cost,
                    o_sales_transaction_cost,
                )

            _fut_revenue = _shared_executor.submit(_compute_revenue)

            # ============================================================
            # WAVE-2 GATHER: Resolve revenue future results
            # ============================================================
            (
                o_land_lease_revenue,
                o_land_lease_revenue_including_grace_period,
                o_land_lease_exit_value,
                o_land_lease_associated_operating_expenses,
                o_land_sales_revenue,
                o_land_sales_phasing,
                o_land_bank_exit_value,
                o_leasing_cost,
                o_sales_transaction_cost,
            ) = _fut_revenue.result()

            _record_timing("Revenue Module")

            # ========================================================================
            # COMMUNITY OPERATIONS HELPER FUNCTIONS
            # ========================================================================

            # ========================================================================
            # COMMUNITY OPERATIONS HELPER FUNCTIONS
            # ========================================================================

            def fn_get_community_operations_parameters(
                asset_cost_module,
                global_cost_module,
                asset_class_series: pd.Series,
                sub_category_series: pd.Series,
                cost_basis_mapping: dict,
                assumptions: pd.DataFrame,
                template_index: pd.Index
            ) -> dict:
                """
                Vectorized extraction of community operations parameters for all assets.
                Returns a dictionary with all parameter Series.
                
                Asset Categories (15):
                1. Residential Units
                2. Residential Land
                3. Commercial Land
                4. Retail
                5. Schools
                6. Office
                7. Hospitality
                8. Logistics
                9. CEC
                10. Canal
                11. Public Amenities
                12. [Placeholder 1]
                13. [Placeholder 2]
                14. [Placeholder 3]
                15. [Placeholder 4]
                
                The function looks up global parameters using the sub_category name
                (e.g., 'residential_units_cost_per_sqm' for 'Residential Units')
                """
                # Initialize output Series
                params = {
                    'cost_start_date': pd.Series(index=template_index, dtype='datetime64[ns]'),
                    'cost_duration': pd.Series(index=template_index, dtype='float64'),
                    'cost_end_date': pd.Series(index=template_index, dtype='datetime64[ns]'),
                    'cost_per_sqm': pd.Series(index=template_index, dtype='float64'),
                    'cost_basis': pd.Series(index=template_index, dtype='object'),
                    'escalation_profile': pd.Series(index=template_index, dtype='object'),
                    'payment_frequency': pd.Series(index=template_index, dtype='object'),
                    'recovery_duration': pd.Series(index=template_index, dtype='object'),
                    'recovery_advance': pd.Series(index=template_index, dtype='object'),
                    'recovery_default_rate': pd.Series(index=template_index, dtype='object'),
                    'cost_basis_sqm': pd.Series(index=template_index, dtype='float64'),
                    'annual_cost_amount': pd.Series(index=template_index, dtype='float64'),
                    'monthly_cost_amount': pd.Series(index=template_index, dtype='float64'),
                }

                # Get default date once
                default_date = _get_named_range_value("a.landco.default.date")

                # OPTIMIZATION: Cache global attribute lookups keyed by normalized prefix.
                # Many rows share the same (asset_class, sub_category), so each unique
                # prefix triggers only one set of getattr calls regardless of row count.
                _global_prefix_cache = {}

                def _fetch_global_for_prefix(prefix):
                    if prefix not in _global_prefix_cache:
                        gcs_opt   = getattr(global_cost_module, f"{prefix}_cost_start_option", "")
                        g_cost_dur = getattr(global_cost_module, f"{prefix}_cost_duration", 0)
                        g_cost_psm = getattr(global_cost_module, f"{prefix}_cost_per_sqm", 0.0)
                        g_cost_bas = getattr(global_cost_module, f"{prefix}_cost_basis", "")
                        g_esc_prof = getattr(global_cost_module, f"{prefix}_escalation_profile", "")
                        g_pay_freq = getattr(global_cost_module, f"{prefix}_payment_frequency", "")
                        g_rec_dur  = getattr(global_cost_module, f"{prefix}_recovery_duration", "")
                        g_rec_adv  = getattr(global_cost_module, f"{prefix}_recovery_advance", "")
                        g_def_rate = getattr(global_cost_module, f"{prefix}_default_rate", "")
                        if gcs_opt == "Operation Start Date":
                            g_cost_sd = default_date
                        elif gcs_opt == "Override":
                            g_cost_sd = getattr(global_cost_module, f"{prefix}_cost_start_date", pd.NaT)
                        else:
                            g_cost_sd = pd.NaT
                        _global_prefix_cache[prefix] = (
                            g_cost_sd, g_cost_dur, g_cost_psm, g_cost_bas,
                            g_esc_prof, g_pay_freq, g_rec_dur, g_rec_adv, g_def_rate
                        )
                    return _global_prefix_cache[prefix]

                # Build normalized attribute names once for all assets
                for loop_row_idx in template_index:
                    asset_class  = asset_class_series[loop_row_idx]
                    sub_category = sub_category_series[loop_row_idx]
                    override     = asset_cost_module.override[loop_row_idx]

                    normalized_asset_class = (
                        asset_class.lower().replace(" ", "_").replace("[", "").replace("]", "")
                        if isinstance(asset_class, str) else ""
                    )
                    normalized_sub_category = (
                        sub_category.lower().replace(" ", "_").replace("[", "").replace("]", "")
                        if isinstance(sub_category, str) else ""
                    )
                    prefix = f"{normalized_asset_class}_{normalized_sub_category}" if normalized_sub_category else normalized_asset_class

                    if override == "Yes":
                        params['cost_start_date'][loop_row_idx]    = asset_cost_module.cost_start_date_override[loop_row_idx]
                        params['cost_duration'][loop_row_idx]      = asset_cost_module.cost_duration[loop_row_idx]
                        params['cost_per_sqm'][loop_row_idx]       = asset_cost_module.cost_per_sqm[loop_row_idx]
                        params['cost_basis'][loop_row_idx]         = asset_cost_module.cost_basis[loop_row_idx]
                        params['escalation_profile'][loop_row_idx] = asset_cost_module.escalation_profile[loop_row_idx]
                        params['payment_frequency'][loop_row_idx]  = asset_cost_module.payment_frequency[loop_row_idx]
                        params['recovery_duration'][loop_row_idx]  = asset_cost_module.recovery_duration[loop_row_idx]
                        params['recovery_advance'][loop_row_idx]   = asset_cost_module.recovery_advance[loop_row_idx]
                        params['recovery_default_rate'][loop_row_idx] = asset_cost_module.recovery_default_rate[loop_row_idx]
                    else:
                        (g_cost_sd, g_cost_dur, g_cost_psm, g_cost_bas,
                         g_esc_prof, g_pay_freq, g_rec_dur, g_rec_adv, g_def_rate) = _fetch_global_for_prefix(prefix)
                        params['cost_start_date'][loop_row_idx]    = g_cost_sd
                        params['cost_duration'][loop_row_idx]      = g_cost_dur
                        params['cost_per_sqm'][loop_row_idx]       = g_cost_psm
                        params['cost_basis'][loop_row_idx]         = g_cost_bas
                        params['escalation_profile'][loop_row_idx] = g_esc_prof
                        params['payment_frequency'][loop_row_idx]  = g_pay_freq
                        params['recovery_duration'][loop_row_idx]  = g_rec_dur
                        params['recovery_advance'][loop_row_idx]   = g_rec_adv
                        params['recovery_default_rate'][loop_row_idx] = g_def_rate

                # OPTIMIZATION: Vectorize all derived-value calculations after the main loop.

                # cost_end_date — list comprehension only over the valid (non-zero-duration) subset
                cost_dur   = params['cost_duration']
                cost_start = params['cost_start_date']
                valid_dur_mask = cost_dur.notna() & (cost_dur > 0) & cost_start.notna()
                valid_dur_idx  = valid_dur_mask[valid_dur_mask].index
                params['cost_end_date'][valid_dur_idx] = [
                    s + pd.DateOffset(months=int(d) - 1)
                    for s, d in zip(cost_start[valid_dur_idx], cost_dur[valid_dur_idx])
                ]

                # cost_basis_sqm — iterate over mapping keys (typically << n_rows) instead of rows
                cost_basis_s  = params['cost_basis']
                cost_basis_sqm = pd.Series(0.0, index=template_index)
                for basis_val, sqm_series in cost_basis_mapping.items():
                    mask = cost_basis_s == basis_val
                    if mask.any():
                        cost_basis_sqm[mask] = sqm_series[mask]
                params['cost_basis_sqm'] = cost_basis_sqm

                # annual and monthly amounts — fully vectorized
                params['annual_cost_amount']  = params['cost_per_sqm'] * params['cost_basis_sqm']
                params['monthly_cost_amount'] = (params['annual_cost_amount'] / 12).fillna(0.0)

                return params

            def fn_calculate_community_operations_flags_vectorized(
                params: dict,
                model_timeline_me: pd.DataFrame,
                template: pd.DataFrame
            ) -> tuple:
                """
                Vectorized calculation of cost flags, escalation flags, and unescalated costs.
                Returns: (cost_flag_df, escalation_flag_df, unescalated_cost_df)
                """
                period_starts  = model_timeline_me['Period Start'].values
                period_ends    = model_timeline_me['Period End'].values
                period_months  = model_timeline_me['Month'].values
                col_indices    = model_timeline_me.index

                cost_start_dates = params['cost_start_date'].values
                cost_end_dates   = params['cost_end_date'].values
                monthly_costs    = params['monthly_cost_amount'].values

                n_rows = len(cost_start_dates)
                n_cols = len(period_starts)

                # OPTIMIZATION: Replace the Python row loop with full 2D numpy broadcasting.
                # This eliminates O(n_rows × n_cols) Python iterations in favour of O(1) numpy ops.

                valid_rows = ~(
                    params['cost_start_date'].isna().values |
                    params['cost_end_date'].isna().values
                )

                # Reshape to (n_rows, 1) vs (1, n_cols) for broadcasting
                start_2d         = cost_start_dates.reshape(n_rows, 1)
                end_2d           = cost_end_dates.reshape(n_rows, 1)
                period_starts_2d = period_starts.reshape(1, n_cols)
                period_ends_2d   = period_ends.reshape(1, n_cols)
                period_months_2d = period_months.reshape(1, n_cols)

                # Vectorized start-month extraction for escalation flag
                start_dates_filled = params['cost_start_date'].fillna(pd.Timestamp('1900-01-01'))
                start_months_raw   = pd.DatetimeIndex(start_dates_filled).month.values
                # Use -1 for invalid rows so they never match any real period month
                start_months = np.where(valid_rows, start_months_raw, -1).reshape(n_rows, 1)

                # 2D boolean masks
                cost_mask_2d = (
                    (period_ends_2d >= start_2d) &
                    (period_starts_2d <= end_2d) &
                    valid_rows.reshape(n_rows, 1)
                )
                escalation_mask_2d = cost_mask_2d & (period_months_2d == start_months)

                # Build result DataFrames directly from arrays (no intermediate zero allocation)
                cost_flag_df = pd.DataFrame(
                    cost_mask_2d.astype(float),
                    index=template.index, columns=col_indices
                )
                escalation_flag_df = pd.DataFrame(
                    escalation_mask_2d.astype(float),
                    index=template.index, columns=col_indices
                )
                unescalated_cost_df = pd.DataFrame(
                    cost_mask_2d * monthly_costs.reshape(n_rows, 1),
                    index=template.index, columns=col_indices
                )

                return cost_flag_df, escalation_flag_df, unescalated_cost_df

            def fn_calculate_community_operations_payment_vectorized(
                params: dict,
                unescalated_cost_df: pd.DataFrame,
                model_timeline_me: pd.DataFrame,
                template: pd.DataFrame
            ) -> pd.DataFrame:
                """
                Vectorized calculation of payment amounts based on payment frequency.
                """
                frequency_months = {
                    "Monthly": 1,
                    "Quarterly": 3,
                    "Semi Annual": 6,
                    "Annual": 12
                }

                payment_df    = _create_zero_df()
                period_starts = model_timeline_me['Period Start']
                period_ends   = model_timeline_me['Period End']

                for row_idx in template.index:
                    freq       = params['payment_frequency'][row_idx]
                    start_date = params['cost_start_date'][row_idx]
                    end_date   = params['cost_end_date'][row_idx]

                    if pd.isna(freq) or pd.isna(start_date) or pd.isna(end_date) or freq not in frequency_months:
                        continue

                    freq_months = frequency_months[freq]
                    valid_mask  = (period_ends >= start_date) & (period_starts <= end_date)
                    valid_cols  = model_timeline_me.index[valid_mask]

                    if len(valid_cols) == 0:
                        continue

                    if freq == "Monthly":
                        payment_df.loc[row_idx, valid_cols] = unescalated_cost_df.loc[row_idx, valid_cols]
                    else:
                        # OPTIMIZATION: Replace inner col_idx loop with a forward-cumsum
                        # rolling window.  O(n_valid) instead of the original O(n_valid²).
                        valid_period_starts = period_starts[valid_cols].values
                        row_costs = unescalated_cost_df.loc[row_idx, valid_cols].values
                        n_valid   = len(row_costs)

                        # Vectorized trigger-column detection
                        months_offset = (
                            pd.DatetimeIndex(valid_period_starts).month - start_date.month
                        ) % freq_months
                        trigger_mask = (months_offset == 0)

                        # Forward rolling sum via cumsum
                        cs        = np.concatenate([[0.0], np.cumsum(row_costs)])
                        end_idxs  = np.minimum(np.arange(n_valid) + freq_months, n_valid)
                        fwd_sums  = cs[end_idxs] - cs[np.arange(n_valid)]

                        payment_df.loc[row_idx, valid_cols] = np.where(trigger_mask, fwd_sums, 0.0)

                return payment_df

            def fn_calculate_community_operations_recovery_vectorized(
                params: dict,
                unescalated_cost_df: pd.DataFrame,
                model_timeline_me: pd.DataFrame,
                template: pd.DataFrame
            ) -> pd.DataFrame:
                """
                Vectorized calculation of recovery amounts.
                """
                recovery_df    = _create_zero_df()
                period_starts  = model_timeline_me['Period Start'].values
                period_ends    = model_timeline_me['Period End'].values
                col_indices    = model_timeline_me.index

                # OPTIMIZATION: Coerce recovery_duration and recovery_advance to float once
                # (replaces per-row try/except float() conversion).
                recovery_dur_coerced = pd.to_numeric(params['recovery_duration'], errors='coerce')
                recovery_adv_coerced = pd.to_numeric(params['recovery_advance'],  errors='coerce')

                for row_idx in template.index:
                    recovery_dur = recovery_dur_coerced[row_idx]
                    recovery_adv = recovery_adv_coerced[row_idx]
                    default_rate = params['recovery_default_rate'][row_idx]
                    start_date   = params['cost_start_date'][row_idx]

                    if pd.isna(default_rate) or not isinstance(default_rate, (int, float)):
                        default_rate = 0

                    if pd.isna(recovery_dur) or pd.isna(recovery_adv) or pd.isna(start_date):
                        continue

                    adjusted_recovery_dur = recovery_dur - recovery_adv
                    if adjusted_recovery_dur <= 0:
                        continue

                    recovery_start_date = start_date + pd.DateOffset(months=int(recovery_adv))
                    recovery_end_date   = recovery_start_date + pd.DateOffset(months=int(adjusted_recovery_dur) - 1)

                    recovery_mask = (period_ends >= recovery_start_date) & (period_starts <= recovery_end_date)
                    recovery_cols = col_indices[recovery_mask]

                    if len(recovery_cols) > 0:
                        monthly_costs_row = unescalated_cost_df.loc[row_idx, recovery_cols]
                        recovery_df.loc[row_idx, recovery_cols] = monthly_costs_row * (1 - default_rate)

                return recovery_df

            def fn_calculate_community_operations(
                asset_cost_module,
                global_cost_module,
                asset_class_series: pd.Series,
                sub_category_series: pd.Series,
                cost_basis_mapping: dict,
                assumptions: pd.DataFrame,
                model_timeline_me: pd.DataFrame,
                template: pd.DataFrame,
                _create_zero_df_func
            ) -> tuple:
                """
                Main function to calculate community operations for either Amanah or Roshn.
                Returns: (cost_flag, unescalated_cost, escalation_flag, payment, recovery, escalation_profile, escalation_percent, escalation_factors)
                """
                # Get parameters
                params = fn_get_community_operations_parameters(
                    asset_cost_module=asset_cost_module,
                    global_cost_module=global_cost_module,
                    asset_class_series=asset_class_series,
                    sub_category_series=sub_category_series,
                    cost_basis_mapping=cost_basis_mapping,
                    assumptions=assumptions,
                    template_index=template.index
                )

                # Calculate flags and unescalated costs (vectorized)
                cost_flag_df, escalation_flag_df, unescalated_cost_df = fn_calculate_community_operations_flags_vectorized(
                    params=params,
                    model_timeline_me=model_timeline_me,
                    template=template
                )

                # Calculate escalation
                escalation_percent_df = _create_zero_df_func()
                escalation_factors_df = _create_zero_df_func()
                
                escalation_percent_df, escalation_factors_df = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=escalation_percent_df,
                    escalation_factor_template=escalation_factors_df,
                    selected_escalation_profile=params['escalation_profile'],
                    escalation_profile_names=escalation_profile_names,
                    escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )

                # Apply escalation factor mapping
                escalation_factor_mapping = escalation_factors_df * escalation_flag_df
                escalation_factor_mapping = escalation_factor_mapping.replace(0, np.nan)
                escalation_factor_mapping.iloc[:, 0] = escalation_factor_mapping.iloc[:, 0].fillna(1)
                escalation_factor_mapping = escalation_factor_mapping.ffill(axis=1)

                # Apply escalation to unescalated costs
                escalated_cost_df = cost_flag_df * escalation_factor_mapping * unescalated_cost_df

                # Calculate payment (vectorized)
                payment_df = fn_calculate_community_operations_payment_vectorized(
                    params=params,
                    unescalated_cost_df=escalated_cost_df,
                    model_timeline_me=model_timeline_me,
                    template=template
                )

                # Calculate recovery (vectorized)
                recovery_df = fn_calculate_community_operations_recovery_vectorized(
                    params=params,
                    unescalated_cost_df=escalated_cost_df,
                    model_timeline_me=model_timeline_me,
                    template=template
                )

                return (
                    cost_flag_df,
                    escalated_cost_df,
                    escalation_flag_df,
                    payment_df,
                    recovery_df,
                    params['escalation_profile'],
                    escalation_percent_df,
                    escalation_factors_df,
                )



            # ============================================================================================
            # COMMUNITY OPERATIONS AMANAH MODULE (OPTIMIZED)
            # ============================================================================================

            def _run_community_operations_module(asset_cost_module, global_cost_module):
                return fn_calculate_community_operations(
                    asset_cost_module=asset_cost_module,
                    global_cost_module=global_cost_module,
                    asset_class_series=Asset.ProjectDetails.asset_class,
                    sub_category_series=Asset.ProjectDetails.sub_category,
                    cost_basis_mapping=_community_cost_basis_series_cache,
                    assumptions=assumptions,
                    model_timeline_me=model_timeline_me,
                    template=template_asset_timeline,
                    _create_zero_df_func=_create_zero_df
                )

            # Run Amanah and ROSHN community operations concurrently via the shared executor.
            # Replacing two separate ThreadPoolExecutor context managers with a single
            # _execute_named_threaded_tasks call avoids thread-pool creation overhead and
            # keeps all concurrent work on the warm shared executor.
            _community_ops_results = _execute_named_threaded_tasks({
                "amanah": lambda: _run_community_operations_module(
                    Asset.CommunityOperationsCostAmanah,
                    Global.CommunityOperationsAmanah,
                ),
                "roshn": lambda: _run_community_operations_module(
                    Asset.CommunityOperationsCostRoshn,
                    Global.CommunityOperationsRoshn,
                ),
            })
            (
                w_community_operations_cost_amanah_flag,
                o_community_operations_unescalated_cost_amanah,
                w_community_operations_amanah_escalation_flag,
                o_community_operations_cost_payment_amanah,
                o_community_operations_amanah_recovery,
                _amanah_escalation_profile,
                w_community_operations_amanah_escalation_percent,
                w_community_operations_amanah_escalation_factors,
            ) = _community_ops_results["amanah"]
            (
                w_community_operations_cost_roshn_flag,
                o_community_operations_unescalated_cost_roshn,
                w_community_operations_roshn_escalation_flag,
                o_community_operations_cost_payment_roshn,
                o_community_operations_roshn_recovery,
                _roshn_escalation_profile,
                w_community_operations_roshn_escalation_percent,
                w_community_operations_roshn_escalation_factors,
            ) = _community_ops_results["roshn"]

            w_community_operations_amanah_escalation_factor_mapping = _create_zero_df()
            w_community_operations_amanah_escalation_factor_mapping = w_community_operations_amanah_escalation_factors * w_community_operations_amanah_escalation_flag
            w_community_operations_amanah_escalation_factor_mapping = w_community_operations_amanah_escalation_factor_mapping.replace(0, np.nan)
            w_community_operations_amanah_escalation_factor_mapping.iloc[:, 0] = w_community_operations_amanah_escalation_factor_mapping.iloc[:, 0].fillna(1)
            w_community_operations_amanah_escalation_factor_mapping = w_community_operations_amanah_escalation_factor_mapping.ffill(axis=1)

            # ============================================================================================
            # COMMUNITY OPERATIONS ROSHN MODULE (OPTIMIZED)
            # ============================================================================================

            w_community_operations_roshn_escalation_factor_mapping = _create_zero_df()
            w_community_operations_roshn_escalation_factor_mapping = w_community_operations_roshn_escalation_factors * w_community_operations_roshn_escalation_flag
            w_community_operations_roshn_escalation_factor_mapping = w_community_operations_roshn_escalation_factor_mapping.replace(0, np.nan)
            w_community_operations_roshn_escalation_factor_mapping.iloc[:, 0] = w_community_operations_roshn_escalation_factor_mapping.iloc[:, 0].fillna(1)
            w_community_operations_roshn_escalation_factor_mapping = w_community_operations_roshn_escalation_factor_mapping.ffill(axis=1)

            # ============================================================================================
            # EXPORT COMMUNITY OPERATIONS DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('community_operations', False):
                _community_operations_exports = {
                    # Amanah
                    'Amanah Cost Flag': w_community_operations_cost_amanah_flag,
                    'Amanah Unescalated Cost': o_community_operations_unescalated_cost_amanah,
                    'Amanah Esc Flag': w_community_operations_amanah_escalation_flag,
                    'Amanah Esc %': w_community_operations_amanah_escalation_percent,
                    'Amanah Esc Factor': w_community_operations_amanah_escalation_factors,
                    'Amanah Esc Mapping': w_community_operations_amanah_escalation_factor_mapping,
                    'Amanah Cost Payment': o_community_operations_cost_payment_amanah,
                    'Amanah Recovery': o_community_operations_amanah_recovery,
                    
                    # Roshn
                    'Roshn Cost Flag': w_community_operations_cost_roshn_flag,
                    'Roshn Unescalated Cost': o_community_operations_unescalated_cost_roshn,
                    'Roshn Esc Flag': w_community_operations_roshn_escalation_flag,
                    'Roshn Esc %': w_community_operations_roshn_escalation_percent,
                    'Roshn Esc Factor': w_community_operations_roshn_escalation_factors,
                    'Roshn Esc Mapping': w_community_operations_roshn_escalation_factor_mapping,
                    'Roshn Cost Payment': o_community_operations_cost_payment_roshn,
                    'Roshn Recovery': o_community_operations_roshn_recovery,
                }
                _export_to_excel(_community_operations_exports, 'export_community_operations', 'Community Operations')



            # ========================================================================
            # SUB-MODULE 3.10: CORPORATE OVERHEAD FUNCTIONS
            # ========================================================================

            _record_timing("Community Operations Module")

            # ========================================================================
            # CORPORATE OVERHEAD CALCULATION FUNCTION (OPTIMIZED)
            # ========================================================================
            def fn_calculate_corporate_overhead(
                asset_expense_class,
                cost_prefix,
                schedule_name,
                global_cost_class,
                o_total_infrastructure_cost_s_curve,
                o_design_cost_payment,
                o_permitting_cost_payment,
                o_supervision_cost_payment,
                o_project_management_cost_payment,
                o_contingency_cost_payment,
                assumptions,
                model_timeline_me,
                _create_zero_df,
                fn_calculate_user_defined_profile
            ):
                """
                Calculate corporate overhead for a given expense category (optimized/vectorized).
                
                Args:
                    asset_expense_class: Asset class containing override, ad_hoc_amount, etc.
                    cost_prefix: Prefix for global cost attributes (e.g., 'salaries', 'it_services')
                    schedule_name: Name of the schedule in assumptions
                    global_cost_class: Global.CorporateOverheadCost class
                    ... (other cost curves and utilities)
                
                Returns:
                    tuple: (overhead, overhead_expensed, overhead_capitalized) DataFrames
                """
                # Get override flags as Series for vectorized operations
                override_flags = pd.Series(asset_expense_class.override)
                
                # User-defined phasing
                s_curve_user_defined = _create_zero_df()
                profile_option = np.where(
                    override_flags == "Yes",
                    "User Defined",
                    "Global"
                )
                s_curve_user_defined = fn_calculate_user_defined_profile(
                    template=s_curve_user_defined,
                    profile_options=profile_option,
                    schedules=_get_named_range_value(schedule_name),
                    start_dates=asset_expense_class.cost_start_date,
                    durations=asset_expense_class.cost_duration,
                    model_timeline_me=model_timeline_me
                )

                # Override calculation
                overhead_override = s_curve_user_defined.mul(asset_expense_class.ad_hoc_amount, axis=0)

                # Global calculation
                overhead_global = _create_zero_df()
                cost_basis = getattr(global_cost_class, f"{cost_prefix}_cost_basis")
                
                if cost_basis in [
                    "Infrastructure Cost",
                    "Infrastructure + Soft Cost",
                    "Infrastructure + Soft Cost + Contingency"
                ]:
                    overhead_global = o_total_infrastructure_cost_s_curve.copy()

                # Define optional inclusions
                optional_costs = {
                    f"{cost_prefix}_design_cost_inclusion": o_design_cost_payment,
                    f"{cost_prefix}_permitting_cost_inclusion": o_permitting_cost_payment,
                    f"{cost_prefix}_supervision_cost_inclusion": o_supervision_cost_payment,
                    f"{cost_prefix}_project_management_cost_inclusion": o_project_management_cost_payment,
                    f"{cost_prefix}_contingency_cost_inclusion": o_contingency_cost_payment,
                }

                include_contingency = cost_basis == "Infrastructure + Soft Cost + Contingency"
                include_soft_costs = cost_basis in [
                    "Infrastructure + Soft Cost",
                    "Infrastructure + Soft Cost + Contingency"
                ]

                for key, cost_curve in optional_costs.items():
                    is_contingency = "contingency" in key.lower()
                    if is_contingency and not include_contingency:
                        continue
                    if not is_contingency and not include_soft_costs:
                        continue
                    if getattr(global_cost_class, key, "No") == "Yes":
                        overhead_global = overhead_global + cost_curve

                overhead_global = overhead_global * getattr(global_cost_class, f"{cost_prefix}_cost_percent")

                # Final output - VECTORIZED (replacing for loop)
                # Create boolean masks for Yes/No overrides
                yes_mask = (override_flags == "Yes").values
                no_mask = (override_flags == "No").values
                
                # Initialize overhead with zeros
                overhead = _create_zero_df()
                
                # Apply override values where flag is "Yes"
                if yes_mask.any():
                    overhead.values[yes_mask, :] = overhead_override.values[yes_mask, :]
                
                # Apply global values where flag is "No"
                if no_mask.any():
                    overhead.values[no_mask, :] = overhead_global.values[no_mask, :]
                
                # Rows with neither "Yes" nor "No" remain as 0 (already initialized)

                # Capitalization percent - VECTORIZED
                global_cap_percent = getattr(global_cost_class, f"{cost_prefix}_capitalization_percent")
                asset_cap_percent = pd.Series(asset_expense_class.percent_capitalized)
                
                capitalization_percent = np.where(
                    override_flags == "Yes",
                    asset_cap_percent.values,
                    global_cap_percent
                )

                # Expensed and Capitalized - already vectorized
                overhead_expensed = overhead.mul(1 - capitalization_percent, axis=0)
                overhead_capitalized = overhead.mul(capitalization_percent, axis=0)

                return overhead, overhead_expensed, overhead_capitalized

            # ========================================================================
            # CALCULATE ALL CORPORATE OVERHEADS USING THE FUNCTION
            # ========================================================================

            # ============================================================
            # PARALLEL CORPORATE OVERHEAD: 7 tasks via thread pool
            # ============================================================
            def _run_corporate_overhead_task(asset_expense_class, cost_prefix, schedule_name):
                return fn_calculate_corporate_overhead(
                    asset_expense_class=asset_expense_class,
                    cost_prefix=cost_prefix,
                    schedule_name=schedule_name,
                    global_cost_class=Global.CorporateOverheadCost,
                    o_total_infrastructure_cost_s_curve=o_total_infrastructure_cost_s_curve,
                    o_design_cost_payment=o_design_cost_payment,
                    o_permitting_cost_payment=o_permitting_cost_payment,
                    o_supervision_cost_payment=o_supervision_cost_payment,
                    o_project_management_cost_payment=o_project_management_cost_payment,
                    o_contingency_cost_payment=o_contingency_cost_payment,
                    assumptions=assumptions,
                    model_timeline_me=model_timeline_me,
                    _create_zero_df=_create_zero_df,
                    fn_calculate_user_defined_profile=fn_calculate_user_defined_profile
                )

            _corporate_overhead_specs = {
                "salaries": (Asset.CorporateOverheadExpensesSalaries, "salaries", "s.landco.corporate.overheads.salaries"),
                "it_services": (Asset.CorporateOverheadExpensesITServices, "it_services", "s.landco.corporate.overheads.it.services"),
                "office_rent_and_utilities": (Asset.CorporateOverheadExpensesOfficeRentandUtilities, "office_rent_and_utitlities", "s.landco.corporate.overheads.office.rent"),
                "professional_services": (Asset.CorporateOverheadExpensesProfessionalServices, "professional_services", "s.landco.corporate.overheads.professional.services"),
                "marketing": (Asset.CorporateOverheadExpensesMarketing, "marketing", "s.landco.corporate.overheads.marketing"),
                "sales_cost": (Asset.CorporateOverheadExpensesSalesCost, "sales_cost", "s.landco.corporate.overheads.sales.cost"),
                "additional_expenses": (Asset.CorporateOverheadExpensesAdditionalExpenses, "additional_expenses", "s.landco.corporate.overheads.additional.expenses"),
            }

            if _thread_worker_count > 1:
                _co_results = _execute_named_threaded_tasks({
                    name: (lambda spec=spec: _run_corporate_overhead_task(*spec))
                    for name, spec in _corporate_overhead_specs.items()
                })
            else:
                _co_results = {
                    name: _run_corporate_overhead_task(*spec)
                    for name, spec in _corporate_overhead_specs.items()
                }

            o_corporate_overheads_salaries, o_corporate_overheads_salaries_expensed, o_corporate_overheads_salaries_capitalized = _co_results["salaries"]
            o_corporate_overheads_it_services, o_corporate_overheads_it_services_expensed, o_corporate_overheads_it_services_capitalized = _co_results["it_services"]
            o_corporate_overheads_office_rent_and_utilities, o_corporate_overheads_office_rent_and_utilities_expensed, o_corporate_overheads_office_rent_and_utilities_capitalized = _co_results["office_rent_and_utilities"]
            o_corporate_overheads_professional_services, o_corporate_overheads_professional_services_expensed, o_corporate_overheads_professional_services_capitalized = _co_results["professional_services"]
            o_corporate_overheads_marketing, o_corporate_overheads_marketing_expensed, o_corporate_overheads_marketing_capitalized = _co_results["marketing"]
            o_corporate_overheads_sales_cost, o_corporate_overheads_sales_cost_expensed, o_corporate_overheads_sales_cost_capitalized = _co_results["sales_cost"]
            o_corporate_overheads_additional_expenses, o_corporate_overheads_additional_expenses_expensed, o_corporate_overheads_additional_expenses_capitalized = _co_results["additional_expenses"]
                        # ============================================================================================
            # TOTAL CORPORATE OVERHEADS - ALL COMPONENTS
            # ============================================================================================

            o_total_corporate_overheads_expensed = (
                o_corporate_overheads_salaries_expensed + 
                o_corporate_overheads_it_services_expensed + 
                o_corporate_overheads_office_rent_and_utilities_expensed + 
                o_corporate_overheads_professional_services_expensed + 
                o_corporate_overheads_marketing_expensed + 
                o_corporate_overheads_sales_cost_expensed + 
                o_corporate_overheads_additional_expenses_expensed
            )
            o_total_corporate_overheads_capitalized = (
                o_corporate_overheads_salaries_capitalized + 
                o_corporate_overheads_it_services_capitalized + 
                o_corporate_overheads_office_rent_and_utilities_capitalized + 
                o_corporate_overheads_professional_services_capitalized + 
                o_corporate_overheads_marketing_capitalized + 
                o_corporate_overheads_sales_cost_capitalized + 
                o_corporate_overheads_additional_expenses_capitalized
            )



            # ============================================================================================
            # EXPORT CORPORATE OVERHEAD DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('corporate_overhead', False):
                _corporate_overhead_exports = {
                    # Salaries
                    'Salaries Total': o_corporate_overheads_salaries,
                    'Salaries Expensed': o_corporate_overheads_salaries_expensed,
                    'Salaries Capitalized': o_corporate_overheads_salaries_capitalized,
                    
                    # IT Services
                    'IT Services Total': o_corporate_overheads_it_services,
                    'IT Services Expensed': o_corporate_overheads_it_services_expensed,
                    'IT Services Capitalized': o_corporate_overheads_it_services_capitalized,
                    
                    # Office Rent and Utilities
                    'Office Rent & Utilities Total': o_corporate_overheads_office_rent_and_utilities,
                    'Office Rent & Utilities Expensed': o_corporate_overheads_office_rent_and_utilities_expensed,
                    'Office Rent & Utilities Capitalized': o_corporate_overheads_office_rent_and_utilities_capitalized,
                    
                    # Professional Services
                    'Professional Services Total': o_corporate_overheads_professional_services,
                    'Professional Services Expensed': o_corporate_overheads_professional_services_expensed,
                    'Professional Services Capitalized': o_corporate_overheads_professional_services_capitalized,
                    
                    # Marketing
                    'Marketing Total': o_corporate_overheads_marketing,
                    'Marketing Expensed': o_corporate_overheads_marketing_expensed,
                    'Marketing Capitalized': o_corporate_overheads_marketing_capitalized,
                    
                    # Sales Cost
                    'Sales Cost Total': o_corporate_overheads_sales_cost,
                    'Sales Cost Expensed': o_corporate_overheads_sales_cost_expensed,
                    'Sales Cost Capitalized': o_corporate_overheads_sales_cost_capitalized,
                    
                    # Additional Expenses
                    'Additional Expenses Total': o_corporate_overheads_additional_expenses,
                    'Additional Expenses Expensed': o_corporate_overheads_additional_expenses_expensed,
                    'Additional Expenses Capitalized': o_corporate_overheads_additional_expenses_capitalized,
                    
                    # Totals
                    'Total Corporate Overheads Expensed': o_total_corporate_overheads_expensed,
                    'Total Corporate Overheads Capitalized': o_total_corporate_overheads_capitalized,
                }
                _export_to_excel(_corporate_overhead_exports, 'export_corporate_overhead', 'Corporate Overhead')

            # ========================================================================
            # SUB-MODULE 3.11: OTHER INCOME AND EXPENSES
            # ========================================================================

            _record_timing("Corporate Overhead Module")

            # ========================================================================
            # OTHER INCOME AND EXPENSES HELPER FUNCTIONS
            # ========================================================================

            def fn_calculate_other_income_amount_vectorized(
                asset_module,
                cost_basis_mapping: dict,
                o_land_sales_revenue: pd.DataFrame,
                o_land_lease_revenue: pd.DataFrame,
                o_land_bank_exit_value: pd.DataFrame,
                template_index: pd.Index
            ) -> pd.Series:
                """
                Vectorized calculation of other income amounts based on calculation approach.
                Supports: Ad-Hoc Amount, SAR / SQM of, % of Revenue
                """
                amount = pd.Series(index=template_index, dtype='float64')
                amount[:] = 0.0
                
                calculation_approach = pd.Series(asset_module.calculation_approach)
                
                # Ad-Hoc Amount calculation
                adhoc_mask = calculation_approach == "Ad-Hoc Amount"
                if adhoc_mask.any():
                    amount[adhoc_mask] = pd.Series(asset_module.other_income_ad_hoc_amount)[adhoc_mask]
                
                # SAR / SQM of calculation
                sar_sqm_mask = calculation_approach == "SAR / SQM of"
                if sar_sqm_mask.any():
                    calculation_basis = pd.Series(asset_module.calculation_basis)
                    cost_per_sqm = pd.Series(asset_module.other_income_sar_per_sqm)
                    
                    for basis_name, basis_series in cost_basis_mapping.items():
                        basis_mask = sar_sqm_mask & (calculation_basis == basis_name)
                        if basis_mask.any():
                            amount[basis_mask] = basis_series[basis_mask] * cost_per_sqm[basis_mask]
                
                # % of Revenue calculation
                pct_mask = calculation_approach == "% of Revenue"
                if pct_mask.any():
                    cost_percentage = pd.Series(asset_module.other_income_percent_of)
                    revenue_sum = (
                        o_land_sales_revenue.sum(axis=1) + 
                        o_land_lease_revenue.sum(axis=1) + 
                        o_land_bank_exit_value.sum(axis=1)
                    )
                    amount[pct_mask] = revenue_sum[pct_mask] * cost_percentage[pct_mask]
                
                return amount

            def fn_calculate_other_expense_amount_vectorized(
                asset_module,
                cost_basis_mapping: dict,
                o_land_sales_revenue: pd.DataFrame,
                o_land_lease_revenue: pd.DataFrame,
                o_land_bank_exit_value: pd.DataFrame,
                o_other_income_1: pd.DataFrame,
                o_other_income_2: pd.DataFrame,
                template_index: pd.Index
            ) -> pd.Series:
                """
                Vectorized calculation of other expense amounts based on calculation approach.
                Supports: Ad-Hoc Amount, SAR / SQM of, % of (with multiple basis options)
                """
                amount = pd.Series(index=template_index, dtype='float64')
                amount[:] = 0.0
                
                calculation_approach = pd.Series(asset_module.calculation_approach)
                
                # Ad-Hoc Amount calculation
                adhoc_mask = calculation_approach == "Ad-Hoc Amount"
                if adhoc_mask.any():
                    amount[adhoc_mask] = pd.Series(asset_module.other_expense_ad_hoc_amount)[adhoc_mask]
                
                # SAR / SQM of calculation
                sar_sqm_mask = calculation_approach == "SAR / SQM of"
                if sar_sqm_mask.any():
                    calculation_basis = pd.Series(asset_module.calculation_basis)
                    cost_per_sqm = pd.Series(asset_module.other_expense_sar_per_sqm)
                    
                    for basis_name, basis_series in cost_basis_mapping.items():
                        basis_mask = sar_sqm_mask & (calculation_basis == basis_name)
                        if basis_mask.any():
                            amount[basis_mask] = basis_series[basis_mask] * cost_per_sqm[basis_mask]
                
                # % of calculation (with different basis options)
                pct_mask = calculation_approach == "% of"
                if pct_mask.any():
                    calculation_basis = pd.Series(asset_module.calculation_basis)
                    cost_percentage = pd.Series(asset_module.other_expense_percent_of)
                    
                    # Pre-calculate sums for efficiency
                    other_income_sum = o_other_income_1.sum(axis=1) + o_other_income_2.sum(axis=1)
                    core_revenue_sum = (
                        o_land_sales_revenue.sum(axis=1) + 
                        o_land_lease_revenue.sum(axis=1) + 
                        o_land_bank_exit_value.sum(axis=1)
                    )
                    
                    # Other Income basis
                    other_income_basis_mask = pct_mask & (calculation_basis == "Other Income")
                    if other_income_basis_mask.any():
                        amount[other_income_basis_mask] = other_income_sum[other_income_basis_mask] * cost_percentage[other_income_basis_mask]
                    
                    # Core Revenue basis
                    core_revenue_basis_mask = pct_mask & (calculation_basis == "Core Revenue")
                    if core_revenue_basis_mask.any():
                        amount[core_revenue_basis_mask] = core_revenue_sum[core_revenue_basis_mask] * cost_percentage[core_revenue_basis_mask]
                    
                    # Core Revenue + Other Income basis
                    combined_basis_mask = pct_mask & (calculation_basis == "Core Revenue + Other Income")
                    if combined_basis_mask.any():
                        combined_sum = core_revenue_sum + other_income_sum
                        amount[combined_basis_mask] = combined_sum[combined_basis_mask] * cost_percentage[combined_basis_mask]
                
                return amount

            def fn_calculate_escalation_flag_vectorized(
                start_dates,
                period_months: np.ndarray,
                template_index: pd.Index,
                template_columns: pd.Index
            ) -> pd.DataFrame:
                """
                Vectorized calculation of escalation flags based on start date months.
                """
                start_dates_v = pd.Series(start_dates)
                period_months_2d = period_months.reshape(1, -1)
                
                # Extract months from start dates using vectorized datetime accessor (handle NaT)
                months_raw = pd.to_datetime(start_dates_v).dt.month.values
                start_months = np.where(pd.notna(months_raw), months_raw, -1).reshape(-1, 1)
                
                # Vectorized comparison: month matches
                escalation_matrix = (start_months == period_months_2d) & (start_months != -1)
                
                return pd.DataFrame(
                    escalation_matrix.astype(int),
                    index=template_index,
                    columns=template_columns
                )

            def fn_calculate_other_income_expense(
                asset_module,
                global_module,
                global_prefix: str,
                is_expense: bool,
                schedule_name: str,
                cost_basis_mapping: dict,
                o_land_sales_revenue: pd.DataFrame,
                o_land_lease_revenue: pd.DataFrame,
                o_land_bank_exit_value: pd.DataFrame,
                o_other_income_1: pd.DataFrame,
                o_other_income_2: pd.DataFrame,
                o_other_income_3: pd.DataFrame,
                assumptions: pd.DataFrame,
                model_timeline_me: pd.DataFrame,
                template: pd.DataFrame,
                _period_months: np.ndarray,
                _create_zero_df_func,
                fn_calculate_user_defined_profile_func,
                fn_calculate_monthly_escalation_profile_func
            ) -> pd.DataFrame:
                """
                Main function to calculate other income or expense with phasing and escalation.
                Supports asset-level overrides - if override is "Yes", uses asset values; otherwise uses global values.
                
                Override-able inputs:
                - Start Date
                - Duration
                - Calculation Approach
                - Cost Basis
                - Percent of Revenue / Cost Per SQM
                - Escalation Profile
                """
                # Get override flags - use global_prefix to construct override attribute name
                override_attr = f"{global_prefix}_override"
                
                override_flags = pd.Series(getattr(asset_module, override_attr, None))
                override_mask = override_flags == "Yes"
                
                # Build effective values based on override
                n_assets = len(template.index)
                
                # Start Date
                asset_start_dates = pd.Series(asset_module.start_date)
                global_start_date = getattr(global_module, f"{global_prefix}_start_date", None)
                effective_start_dates = np.where(
                    override_mask,
                    asset_start_dates,
                    global_start_date
                )
                effective_start_dates = pd.to_datetime(pd.Series(effective_start_dates, index=template.index))
                
                # Duration
                asset_durations = pd.Series(asset_module.duration)
                global_duration = getattr(global_module, f"{global_prefix}_duration", None)
                effective_durations = np.where(
                    override_mask,
                    asset_durations,
                    global_duration
                )
                
                # Calculation Approach
                asset_calc_approach = pd.Series(asset_module.calculation_approach)
                global_calc_approach = getattr(global_module, f"{global_prefix}_calculation_approach", None)
                effective_calc_approach = np.where(
                    override_mask,
                    asset_calc_approach,
                    global_calc_approach
                )
                effective_calc_approach = pd.Series(effective_calc_approach, index=template.index)
                
                # Cost Basis
                asset_cost_basis = pd.Series(asset_module.calculation_basis)
                global_cost_basis = getattr(global_module, f"{global_prefix}_cost_basis", None)
                effective_cost_basis = np.where(
                    override_mask,
                    asset_cost_basis,
                    global_cost_basis
                )
                effective_cost_basis = pd.Series(effective_cost_basis, index=template.index)
                
                # Percent of Revenue / Cost Percent
                if is_expense:
                    asset_percent = pd.Series(asset_module.other_expense_percent_of)
                    global_percent = getattr(global_module, f"{global_prefix}_percent_of_revenue", None)
                else:
                    asset_percent = pd.Series(asset_module.other_income_percent_of)
                    global_percent = getattr(global_module, f"{global_prefix}_percent_of_revenue", None)
                effective_percent = np.where(
                    override_mask,
                    asset_percent,
                    global_percent if global_percent is not None else 0.0
                )
                effective_percent = pd.Series(effective_percent, index=template.index, dtype='float64')
                
                # Cost Per SQM
                if is_expense:
                    asset_cost_per_sqm = pd.Series(asset_module.other_expense_sar_per_sqm)
                else:
                    asset_cost_per_sqm = pd.Series(asset_module.other_income_sar_per_sqm)
                global_cost_per_sqm = getattr(global_module, f"{global_prefix}_cost_per_sqm", None)
                effective_cost_per_sqm = np.where(
                    override_mask,
                    asset_cost_per_sqm,
                    global_cost_per_sqm if global_cost_per_sqm is not None else 0.0
                )
                effective_cost_per_sqm = pd.Series(effective_cost_per_sqm, index=template.index, dtype='float64')
                
                # Escalation Profile
                asset_escalation = pd.Series(asset_module.escalation_profile)
                global_escalation = getattr(global_module, f"{global_prefix}_escalation_profile", None)
                effective_escalation = np.where(
                    override_mask,
                    asset_escalation,
                    global_escalation
                )
                effective_escalation = pd.Series(effective_escalation, index=template.index)
                
                # Ad-Hoc Amount (only from asset module)
                if is_expense:
                    asset_adhoc = pd.Series(asset_module.other_expense_ad_hoc_amount)
                else:
                    asset_adhoc = pd.Series(asset_module.other_income_ad_hoc_amount)
                
                # Calculate amount based on effective calculation approach
                amount = pd.Series(index=template.index, dtype='float64')
                amount[:] = 0.0
                
                # Ad-Hoc Amount calculation
                # Note: For expenses, if global calculation approach is "Ad-Hoc Amount" (i.e., no override),
                # the expense should be 0. Only use ad-hoc amount when asset override is "Yes".
                adhoc_mask = effective_calc_approach == "Ad-Hoc Amount"
                if adhoc_mask.any():
                    # Only apply ad-hoc amount for assets that have override="Yes"
                    # For non-overriding assets with global "Ad-Hoc Amount", keep amount as 0
                    adhoc_with_override_mask = adhoc_mask & override_mask
                    if adhoc_with_override_mask.any():
                        amount[adhoc_with_override_mask] = asset_adhoc[adhoc_with_override_mask].astype(float)
                
                # SAR / SQM of calculation
                sar_sqm_mask = effective_calc_approach == "SAR / SQM of"
                if sar_sqm_mask.any():
                    for basis_name, basis_series in cost_basis_mapping.items():
                        basis_mask = sar_sqm_mask & (effective_cost_basis == basis_name)
                        if basis_mask.any():
                            amount[basis_mask] = pd.Series(basis_series)[basis_mask].astype(float) * effective_cost_per_sqm[basis_mask]
                
                # % of Revenue / % of calculation
                if is_expense:
                    pct_mask = effective_calc_approach == "% of"
                else:
                    pct_mask = effective_calc_approach == "% of Revenue"
                
                if pct_mask.any():
                    # Pre-calculate sums for efficiency
                    other_income_sum = o_other_income_1.sum(axis=1) + o_other_income_2.sum(axis=1) + o_other_income_3.sum(axis=1)
                    core_revenue_sum = (
                        o_land_sales_revenue.sum(axis=1) + 
                        o_land_lease_revenue.sum(axis=1) + 
                        o_land_bank_exit_value.sum(axis=1)
                    )
                    
                    if is_expense:
                        # Other Income basis
                        other_income_basis_mask = pct_mask & (effective_cost_basis == "Other Income")
                        if other_income_basis_mask.any():
                            amount[other_income_basis_mask] = other_income_sum[other_income_basis_mask] * effective_percent[other_income_basis_mask]
                        
                        # Core Revenue basis
                        core_revenue_basis_mask = pct_mask & (effective_cost_basis == "Core Revenue")
                        if core_revenue_basis_mask.any():
                            amount[core_revenue_basis_mask] = core_revenue_sum[core_revenue_basis_mask] * effective_percent[core_revenue_basis_mask]
                        
                        # Core Revenue + Other Income basis
                        combined_basis_mask = pct_mask & (effective_cost_basis == "Core Revenue + Other Income")
                        if combined_basis_mask.any():
                            combined_sum = core_revenue_sum + other_income_sum
                            amount[combined_basis_mask] = combined_sum[combined_basis_mask] * effective_percent[combined_basis_mask]
                    else:
                        # For income: % of Revenue uses total revenue
                        revenue_sum = core_revenue_sum
                        amount[pct_mask] = revenue_sum[pct_mask] * effective_percent[pct_mask]
                
                # Calculate phasing
                phasing = _create_zero_df_func()
                phasing_option = np.where(
                    ~pd.isna(effective_calc_approach),
                    "User Defined",
                    "None"
                )
                
                phasing = fn_calculate_user_defined_profile_func(
                    template=phasing,
                    profile_options=phasing_option,
                    schedules=_get_named_range_value(schedule_name),
                    start_dates=effective_start_dates,
                    durations=effective_durations,
                    model_timeline_me=model_timeline_me
                )
                
                # Calculate escalation flag (vectorized)
                escalation_flag = fn_calculate_escalation_flag_vectorized(
                    start_dates=effective_start_dates,
                    period_months=_period_months,
                    template_index=template.index,
                    template_columns=template.columns
                )
                
                # Calculate escalation factors
                escalation_percent = _create_zero_df_func()
                escalation_factors = _create_zero_df_func()
                
                escalation_percent, escalation_factors = fn_calculate_monthly_escalation_profile_func(
                    escalation_percent_template=escalation_percent,
                    escalation_factor_template=escalation_factors,
                    selected_escalation_profile=effective_escalation,
                escalation_profile_names=escalation_profile_names,
                escalation_profile_data=escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )
                
                # Apply escalation factor mapping with forward-fill
                escalation_factor_mapping = escalation_factors * escalation_flag
                escalation_factor_mapping = escalation_factor_mapping.replace(0, np.nan)
                escalation_factor_mapping.iloc[:, 0] = escalation_factor_mapping.iloc[:, 0].fillna(1)
                escalation_factor_mapping = escalation_factor_mapping.ffill(axis=1)
                
                # Calculate final output
                output = (phasing * escalation_factor_mapping).mul(amount, axis=0)
                
                return output

            cost_basis_mapping = {
                    "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                    "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                    "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
                    "Built Up Area": Asset.LandAreaModule.built_up_area,
                }

            # ============================================================
            # PARALLEL OTHER INCOME: 3 tasks (income_1, income_2, govt subsidies)
            # ============================================================
            def _make_other_income_task(asset_module, global_prefix, schedule_name):
                def _task():
                    return fn_calculate_other_income_expense(
                        asset_module=asset_module,
                        global_module=Global.OtherIncomeandExpensesAssumptions,
                        global_prefix=global_prefix,
                        is_expense=False,
                        schedule_name=schedule_name,
                        cost_basis_mapping=cost_basis_mapping,
                        o_land_sales_revenue=o_land_sales_revenue,
                        o_land_lease_revenue=o_land_lease_revenue,
                        o_land_bank_exit_value=o_land_bank_exit_value,
                        o_other_income_1=_create_zero_df(),
                        o_other_income_2=_create_zero_df(),
                        o_other_income_3=_create_zero_df(),
                        assumptions=assumptions,
                        model_timeline_me=model_timeline_me,
                        template=template_asset_timeline,
                        _period_months=_period_months,
                        _create_zero_df_func=_create_zero_df,
                        fn_calculate_user_defined_profile_func=fn_calculate_user_defined_profile,
                        fn_calculate_monthly_escalation_profile_func=fn_calculate_monthly_escalation_profile
                    )
                return _task

            if _thread_worker_count > 1:
                _income_results = _execute_named_threaded_tasks({
                    "other_income_1": _make_other_income_task(Asset.OtherIncome1, "other_income_1", "s.landco.other.income.1"),
                    "other_income_2": _make_other_income_task(Asset.OtherIncome2, "other_income_2", "s.landco.other.income.2"),
                    "other_income_3": _make_other_income_task(Asset.GovernmentSubsidies, "government_subsidies", "s.landco.government.subsidies.phasing"),
                })
            else:
                _income_results = {
                    "other_income_1": _make_other_income_task(Asset.OtherIncome1, "other_income_1", "s.landco.other.income.1")(),
                    "other_income_2": _make_other_income_task(Asset.OtherIncome2, "other_income_2", "s.landco.other.income.2")(),
                    "other_income_3": _make_other_income_task(Asset.GovernmentSubsidies, "government_subsidies", "s.landco.government.subsidies.phasing")(),
                }

            o_other_income_1 = _income_results["other_income_1"]
            o_other_income_2 = _income_results["other_income_2"]
            o_other_income_3 = _income_results["other_income_3"]

                        # ============================================================
            # PARALLEL OTHER EXPENSES: 3 tasks concurrently
            # (each depends on o_other_income_1/2/3 but not on each other)
            # ============================================================
            def _make_other_expense_task(asset_module, global_prefix, schedule_name):
                def _task():
                    return fn_calculate_other_income_expense(
                        asset_module=asset_module,
                        global_module=Global.OtherIncomeandExpensesAssumptions,
                        global_prefix=global_prefix,
                        is_expense=True,
                        schedule_name=schedule_name,
                        cost_basis_mapping=cost_basis_mapping,
                        o_land_sales_revenue=o_land_sales_revenue,
                        o_land_lease_revenue=o_land_lease_revenue,
                        o_land_bank_exit_value=o_land_bank_exit_value,
                        o_other_income_1=o_other_income_1,
                        o_other_income_2=o_other_income_2,
                        o_other_income_3=o_other_income_3,
                        assumptions=assumptions,
                        model_timeline_me=model_timeline_me,
                        template=template_asset_timeline,
                        _period_months=_period_months,
                        _create_zero_df_func=_create_zero_df,
                        fn_calculate_user_defined_profile_func=fn_calculate_user_defined_profile,
                        fn_calculate_monthly_escalation_profile_func=fn_calculate_monthly_escalation_profile
                    )
                return _task

            if _thread_worker_count > 1:
                _expense_results = _execute_named_threaded_tasks({
                    "other_expense_1": _make_other_expense_task(Asset.OtherExpense1, "other_expense_1", "s.landco.other.expense.1"),
                    "other_expense_2": _make_other_expense_task(Asset.OtherExpense2, "other_expense_2", "s.landco.other.expense.2"),
                    "other_expense_3": _make_other_expense_task(Asset.OtherExpense3, "other_expense_3", "s.landco.other.expense.3"),
                })
            else:
                _expense_results = {
                    "other_expense_1": _make_other_expense_task(Asset.OtherExpense1, "other_expense_1", "s.landco.other.expense.1")(),
                    "other_expense_2": _make_other_expense_task(Asset.OtherExpense2, "other_expense_2", "s.landco.other.expense.2")(),
                    "other_expense_3": _make_other_expense_task(Asset.OtherExpense3, "other_expense_3", "s.landco.other.expense.3")(),
                }

            o_other_expense_1 = _expense_results["other_expense_1"]
            o_other_expense_2 = _expense_results["other_expense_2"]
            o_other_expense_3 = _expense_results["other_expense_3"]

                        # ============================================================================================
            # COMBINED OTHER INCOME AND EXPENSES
            # ============================================================================================

            o_total_other_income = o_other_income_1 + o_other_income_2 + o_other_income_3
            o_total_other_expenses = o_other_expense_1 + o_other_expense_2 + o_other_expense_3
            o_net_other_income = o_total_other_income - o_total_other_expenses

            # ============================================================================================
            # EXPORT OTHER INCOME AND EXPENSES DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('other_income_and_expenses', False):
                _other_income_and_expenses_exports = {
                    'Other Income 1': o_other_income_1,
                    'Other Income 2': o_other_income_2,
                    'Government Subsidies': o_other_income_3,
                    'Total Other Income': o_total_other_income,
                    'Other Expense 1': o_other_expense_1,
                    'Other Expense 2': o_other_expense_2,
                    'Other Expense 3': o_other_expense_3,
                    'Total Other Expenses': o_total_other_expenses,
                    'Net Other Income': o_net_other_income,
                }
                _export_to_excel(_other_income_and_expenses_exports, 'export_other_income_and_expenses', 'Other Income and Expenses')

            # ========================================================================
            # SUB-MODULE 3.12: ESCROW MODULE CALCULATIONS
            # ========================================================================

            _record_timing("Other Income and Expenses Module")

            # ============================================================================================
            # CONSTRUCTION PROGRESS
            # ============================================================================================

            w_construction_progress_percent = _create_zero_df() # Initialize with zeros

            w_construction_progress_percent = o_total_infrastructure_cost_s_curve.div(o_total_infrastructure_cost_s_curve.sum(axis=1), axis=0)

            # ============================================================================================
            # CUMULATIVE CONSTRUCTION PROGRESS
            # ============================================================================================

            # Initialize cumulative construction progress percent
            w_cumulative_construction_progress_percent = _create_zero_df()  # Initialize with zeros

            # Calculate cumulative sum
            w_cumulative_construction_progress_percent = w_construction_progress_percent.cumsum(axis=1)

            # Apply the condition: if cumsum till the previous column is 1, set cumsum to 0; otherwise, keep cumsum
            w_cumulative_construction_progress_percent[:] = np.where(
                w_cumulative_construction_progress_percent.shift(axis=1, fill_value=0).values >= 1 - 1e-6,
                0.0,
                w_cumulative_construction_progress_percent.values
            )

            # Ensure values greater than 1 are capped at 1
            w_cumulative_construction_progress_percent[:] = np.where(
                w_cumulative_construction_progress_percent.values > 1 - 1e-6,
                1.0,
                w_cumulative_construction_progress_percent.values
            )

            # Round up to 3 decimal places
            w_cumulative_construction_progress_percent = np.ceil(w_cumulative_construction_progress_percent * 1000) / 1000

            # ============================================================================================
            # CALCULATE INFRASTRUCTURE END DATES FROM S-CURVES (PRE-CALCULATION)
            # ============================================================================================
            # This calculation is done early so it can be used in LAND SALES PAYMENT ABSORPTION
            # It calculates the end date when cumulative S-curve reaches ~100% (>= 0.999)
            
            def fn_calculate_infra_end_date_from_scurve(s_curve_percent_df, model_timeline_me):
                """
                Vectorized calculation of infrastructure end dates from S-curve completion.
                Returns end dates for all assets regardless of escrow applicability.
                """
                # Calculate cumulative sum across periods
                cumsum_df = s_curve_percent_df.cumsum(axis=1)
                
                # Create boolean mask where cumsum >= 0.999 (100% completion)
                completed_mask = cumsum_df >= 0.999
                
                # Find first column index where completion is reached
                first_completed_col = completed_mask.values.argmax(axis=1)
                has_completion = completed_mask.any(axis=1).values
                
                # Calculate end column index (next period after completion)
                num_periods = len(model_timeline_me['Period Start'])
                end_col_indices = np.where(
                    has_completion,
                    np.minimum(first_completed_col + 1, num_periods - 1),
                    -1
                )
                
                # Get period start dates array
                period_starts = model_timeline_me['Period Start'].values
                
                # Map column indices to dates
                end_dates = np.where(
                    end_col_indices >= 0,
                    period_starts[np.maximum(end_col_indices, 0)],
                    np.datetime64('NaT')
                )
                
                # Subtract one day from end dates
                end_dates_series = pd.Series(end_dates, index=s_curve_percent_df.index, dtype='datetime64[ns]')
                end_dates_series = end_dates_series - pd.Timedelta(days=1)
                
                return end_dates_series
            
            # Calculate primary and secondary infrastructure end dates
            w_primary_infra_end_date = fn_calculate_infra_end_date_from_scurve(
                o_primary_infrastructure_s_curve_percent, model_timeline_me
            )
            w_secondary_infra_end_date = fn_calculate_infra_end_date_from_scurve(
                o_secondary_infrastructure_s_curve_percent, model_timeline_me
            )
            
            # Calculate combined infrastructure end date as the max of primary and secondary
            w_infrastructure_end_date = pd.concat(
                [w_primary_infra_end_date, w_secondary_infra_end_date], axis=1
            ).max(axis=1)

            # ========================================================================
            # LAND SALES PAYMENT ABSORPTION (OPTIMIZED - VECTORIZED)
            # ========================================================================
            
            o_land_sales_payment_absorption = _create_zero_df() # Initialize with zeroes

            infrastructure_start_dates = np.minimum(
                primary_infrastructure_construction_start_dates,
                secondary_infrastructure_construction_start_dates
            )

            # Pre-compute values for vectorized calculation
            _period_starts_escrow = model_timeline_me['Period Start'].values
            _infra_start_arr = infrastructure_start_dates.reshape(-1, 1)  # (n_assets, 1)
            _infra_end_arr = w_infrastructure_end_date.values.reshape(-1, 1)  # (n_assets, 1)
            _cumulative_progress = w_cumulative_construction_progress_percent.values  # (n_assets, n_periods)
            _business_model = np.array(Asset.BusinessModelModule.business_model)
            _is_land_sale = (_business_model == 'Land Sale').reshape(-1, 1)  # (n_assets, 1)
            
            # Get milestones and payments from Global.EscrowAssumptions
            _milestones = np.array([
                Global.EscrowAssumptions.construction_milestone_6th_instalment,
                Global.EscrowAssumptions.construction_milestone_5th_instalment,
                Global.EscrowAssumptions.construction_milestone_4th_instalment,
                Global.EscrowAssumptions.construction_milestone_3rd_instalment,
                Global.EscrowAssumptions.construction_milestone_2nd_instalment,
                Global.EscrowAssumptions.construction_milestone_1st_instalment,
                Global.EscrowAssumptions.construction_milestone_downpayment,
            ])
            _payments = np.array([
                Global.EscrowAssumptions.cumulative_payment_6th_instalment,
                Global.EscrowAssumptions.cumulative_payment_5th_instalment,
                Global.EscrowAssumptions.cumulative_payment_4th_instalment,
                Global.EscrowAssumptions.cumulative_payment_3rd_instalment,
                Global.EscrowAssumptions.cumulative_payment_2nd_instalment,
                Global.EscrowAssumptions.cumulative_payment_1st_instalment,
                Global.EscrowAssumptions.cumulative_payment_downpayment,
            ])
            _downpayment = Global.EscrowAssumptions.cumulative_payment_downpayment
            
            # Get numpy array for direct assignment
            _payment_absorption = o_land_sales_payment_absorption.values
            
            # Calculate cumulative progress limit (max of previous columns) - vectorized
            # Shift right by 1 and take cummax
            _cumulative_progress_limit = np.zeros_like(_cumulative_progress)
            if _cumulative_progress.shape[1] > 1:
                _cumulative_progress_limit[:, 1:] = np.maximum.accumulate(_cumulative_progress[:, :-1], axis=1)
            
            n_rows = len(template_asset_timeline.index)
            n_cols = len(model_timeline_me)
            
            # Column-by-column iteration with row-vectorized operations
            for col in range(n_cols):
                period_start = _period_starts_escrow[col]
                
                # Conditions (vectorized across all assets)
                _in_construction_period = (period_start >= _infra_start_arr[:, 0]) & (_cumulative_progress_limit[:, col] != 1)
                _in_downpayment_period = (period_start >= _infra_start_arr[:, 0]) & (period_start < _infra_end_arr[:, 0])
                
                # Calculate values based on milestones (vectorized)
                _col_progress = _cumulative_progress[:, col]
                
                # Start with zeros
                _values = np.zeros(n_rows)
                
                # Apply milestone conditions (in reverse order of priority - lowest first, highest last to overwrite)
                _values = np.where(_in_downpayment_period, _downpayment, _values)
                
                for milestone, payment in zip(_milestones[::-1], _payments[::-1]):
                    if milestone == Global.EscrowAssumptions.construction_milestone_6th_instalment:
                        # Exact match for 6th instalment
                        _values = np.where(_col_progress == milestone, payment, _values)
                    else:
                        # >= comparison for other milestones
                        _values = np.where(_col_progress >= milestone, payment, _values)
                
                # Apply conditions
                _values = np.where(_in_construction_period & _is_land_sale[:, 0], _values, 0.0)
                
                _payment_absorption[:, col] = _values
            
            # Assign back to DataFrame
            o_land_sales_payment_absorption = pd.DataFrame(
                _payment_absorption, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
                    
            # ============================================================================================
            # INFLOWS TO ESCROW
            # ============================================================================================

            w_escrow_flag = pd.Series(index=template_asset_timeline.index, dtype='object')
            w_temporary_license_flag = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')

            # ========================================================================
            # ESCROW FLAG (OPTIMIZED - VECTORIZED)
            # ========================================================================
            
            _asset_classes = np.array(Asset.ProjectDetails.asset_class)
            _sales_start_dates = np.array(Asset.LandSalesModule.sales_start_date)
            
            # Vectorized normalization and flag lookup
            for loop_row_idx in template_asset_timeline.index:
                asset_class = _asset_classes[loop_row_idx]
                
                normalized_asset_class = (
                    asset_class
                    .lower()
                    .replace(" ", "_")
                    .replace("[", "")
                    .replace("]", "") if isinstance(asset_class, str) else ""
                )
                
                attr = f"escrow_inclusion_{normalized_asset_class}"
                escrow_val = getattr(Global.EscrowAssumptions, attr, "No")
                w_escrow_flag[loop_row_idx] = 1.0 if escrow_val == "Yes" else 0.0
                w_temporary_license_flag[loop_row_idx] = _sales_start_dates[loop_row_idx] if w_escrow_flag[loop_row_idx] == 1.0 else pd.NaT

            # ========================================================================
            # INFLOWS TO ESCROW (OPTIMIZED - VECTORIZED)
            # ========================================================================
            
            o_inflows_to_escrow = _create_zero_df() # Initialize with zero

            # Pre-extract numpy arrays for fast computation
            _payment_absorption_arr = o_land_sales_payment_absorption.values
            _land_sales_revenue_arr = o_land_sales_revenue.values
            _escrow_flag_arr = w_escrow_flag.values.reshape(-1, 1)  # (n_assets, 1)
            _cumulative_progress_arr = w_cumulative_construction_progress_percent.values
            
            # Initialize cumulative arrays
            _land_sales_cumulative = np.zeros_like(_land_sales_revenue_arr)
            _inflows_cumulative = np.zeros(n_rows)
            _inflows_arr = o_inflows_to_escrow.values
            
            # Calculate cumulative land sales (shifted cumsum including current column)
            _land_sales_cumulative = np.cumsum(_land_sales_revenue_arr, axis=1)
            
            # Calculate cumulative progress limit (max of previous columns) - already computed earlier but recalculate for this section
            _progress_limit = np.zeros_like(_cumulative_progress_arr)
            if _cumulative_progress_arr.shape[1] > 1:
                _progress_limit[:, 1:] = np.maximum.accumulate(_cumulative_progress_arr[:, :-1], axis=1)
            
            # Column-by-column iteration with row-vectorized operations
            for col in range(n_cols):
                _payment_curr = _payment_absorption_arr[:, col]
                _payment_prev = _payment_absorption_arr[:, col - 1] if col > 0 else np.zeros(n_rows)
                _revenue_curr = _land_sales_revenue_arr[:, col]
                _revenue_cumul = _land_sales_cumulative[:, col]
                _progress_lim = _progress_limit[:, col]
                _progress_curr = _cumulative_progress_arr[:, col]
                
                # Calculate value based on payment absorption comparison
                _values = np.where(
                    _payment_curr <= _payment_prev,
                    _payment_curr * _revenue_curr,
                    (_payment_curr * _revenue_cumul) - _inflows_cumulative
                )
                
                # Calculate calculation flag
                _calc_flag = np.where(_progress_lim >= (1 - 1e-3), 0.0, _escrow_flag_arr[:, 0])
                
                # Apply flag and store
                _inflows_arr[:, col] = _values * _calc_flag
                
                # Update cumulative inflows for next iteration
                _inflows_cumulative += _inflows_arr[:, col]
            
            # Assign back to DataFrame
            o_inflows_to_escrow = pd.DataFrame(
                _inflows_arr, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
                    
            # ============================================================================================
            # TRANSFER TO RETENTION
            # ============================================================================================

            o_transfer_to_retention = _create_zero_df() # Initialize with zero

            o_transfer_to_retention = o_inflows_to_escrow * Global.EscrowAssumptions.retention_reserve

            # ============================================================================================
            # FUNDS AVAILABLE FOR SOFT COST
            # ============================================================================================

            o_funds_available_for_soft_cost = _create_zero_df() # Initialize with zero

            o_funds_available_for_soft_cost = o_inflows_to_escrow * Global.EscrowAssumptions.admin_and_soft_cost_utilization

            # ============================================================================================
            # FUNDS AVAILABLE FOR HARD COST
            # ============================================================================================

            o_funds_available_for_hard_cost = _create_zero_df() # Initialize with zero

            o_funds_available_for_hard_cost = o_inflows_to_escrow * Global.EscrowAssumptions.hard_cost_utilization

            # ============================================================================================
            # PERMANENT LICENSE DATE FLAG (OPTIMIZED - VECTORIZED)
            # ============================================================================================

            w_temporary_license_date = w_temporary_license_flag.min()
            w_permanent_license_date = w_temporary_license_date + pd.DateOffset(months=Global.EscrowAssumptions.permanent_license_approval_duration)

            w_permanent_license_date_flag = _create_zero_df() # Initialize with zero

            # Vectorized: broadcast comparison across all columns
            _period_starts_license = pd.to_datetime(model_timeline_me['Period Start']).values
            _permanent_license_date_val = pd.to_datetime(w_permanent_license_date)
            _license_flag_arr = (_period_starts_license >= _permanent_license_date_val).astype(float)
            w_permanent_license_date_flag.loc[:, :] = _license_flag_arr

            # ============================================================================================
            # DATAFRAME INITIALIZAZION FOR ESCROW CALCULATIONS
            # ============================================================================================

            w_soft_opening_balance = _create_zero_df() # Initialize with zero

            w_soft_cost_total_availability = _create_zero_df() # Initialize with zero

            w_soft_cost_payment_requirement = _create_zero_df() # Initialize with zero

            w_soft_cost_cumulative_requirement = _create_zero_df() # Initialize with zero

            w_soft_cost_payment_from_escrow = _create_zero_df() # Initialize with zero

            w_additional_requirements_for_soft_cost = _create_zero_df() # Initialize with zero

            w_amount_available_for_reallocation = _create_zero_df() # Initialize with zero

            w_hard_opening_balance = _create_zero_df() # Initialize with zero

            w_hard_cost_total_availability = _create_zero_df() # Initialize with zero

            w_hard_cost_payment_requirement = _create_zero_df() # Initialize with zero

            w_hard_cost_cumulative_requirement = _create_zero_df() # Initialize with zero

            w_hard_cost_payment_from_escrow = _create_zero_df() # Initialize with zero

            w_additional_requirements_for_hard_cost = _create_zero_df() # Initialize with zero

            w_reallocation_amount = _create_zero_df() # Initialize with zero

            w_reallocated_funds_for_hard_cost_payment = _create_zero_df() # Initialize with zero

            w_additional_requirement_after_allocation = _create_zero_df() # Initialize with zero

            w_amount_available_after_hard_cost_payment = _create_zero_df() # Initialize with zero

            w_last_year_release_hard_cost = _create_zero_df() # Initialize with zero

            w_hard_closing_balance = _create_zero_df() # Initialize with zero

            w_amount_available_after_soft_cost_and_reallocated_payment = _create_zero_df() # Initialize with zero

            w_last_year_release_soft_cost = _create_zero_df() # Initialize with zero

            w_soft_closing_balance = _create_zero_df() # Initialize with zero

            w_retention_release = _create_zero_df() # Initialize with zero

            o_cash_inflow_from_off_plan_sales = _create_zero_df() # Initialize with zero

            o_escrow_setup_fees = _create_zero_df() # Initialize with zero

            # ============================================================================================
            # ESCROW CALCULATIONS
            # ============================================================================================

            # Ensure reallocation_flag is set correctly
            reallocation_flag = 1.0 if Global.EscrowAssumptions.reallocation_option == "Yes" else 0.0

            # Initialize Series for sales start dates
            temp_sales_start_date = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')
            temp_post_infrastructure_end_date = pd.Series(index=template_asset_timeline.index, dtype='datetime64[ns]')

            # Use pandas.Series.where to conditionally assign values
            temp_sales_start_date = pd.Series(Asset.LandSalesModule.sales_start_date).where(w_escrow_flag == 1.0, pd.NaT)
            temp_sales_duration = pd.Series(Asset.LandSalesModule.sales_duration).where(w_escrow_flag == 1.0, pd.NaT)

            # ============================================================================================
            # APPLY ESCROW FILTER TO INFRASTRUCTURE END DATES
            # ============================================================================================
            # Use the pre-calculated w_infrastructure_end_date and apply escrow filters
            
            # Get escrow applicability flags per asset
            escrow_applicability_flags = pd.Series(Asset.LandSalesModule.escrow_applicability)
            
            # Create combined mask for escrow applicability and escrow flag
            escrow_mask = (escrow_applicability_flags == "Yes") & (w_escrow_flag == 1.0)
            
            # Apply escrow filter to infrastructure end date (use pre-calculated w_infrastructure_end_date)
            # Add one day to compensate for the day subtracted in fn_calculate_infra_end_date_from_scurve
            temp_post_infrastructure_end_date = (w_infrastructure_end_date + pd.Timedelta(days=1)).where(escrow_mask, pd.NaT)

            # ============================================================================================
            # CALCULATE SOFT COST END DATE (VECTORIZED)
            # ============================================================================================
            # Calculate cumulative and total soft cost payment
            soft_cost_payment = o_total_soft_cost_payment.astype(float)
            soft_cost_cumsum = soft_cost_payment.cumsum(axis=1)
            soft_cost_total = soft_cost_payment.sum(axis=1)
            
            # Round for comparison (to handle floating point precision)
            soft_cost_cumsum_rounded = soft_cost_cumsum.round(3)
            soft_cost_total_rounded = soft_cost_total.round(3)
            
            # Create mask where cumulative equals total (completion)
            completion_mask = soft_cost_cumsum_rounded.eq(soft_cost_total_rounded, axis=0)
            
            # Find first column where completion is reached
            first_completion_col = completion_mask.values.argmax(axis=1)
            has_completion = completion_mask.any(axis=1).values
            
            # Calculate end column index (next period after completion)
            num_periods = len(model_timeline_me['Period Start'])
            end_col_indices = np.where(
                has_completion,
                np.minimum(first_completion_col + 1, num_periods - 1),
                -1
            )
            
            # Get period start dates array
            period_starts = model_timeline_me['Period Start'].values
            
            # Map column indices to dates
            temp_post_soft_cost_end_date = pd.Series(
                np.where(
                    end_col_indices >= 0,
                    period_starts[np.maximum(end_col_indices, 0)],
                    np.datetime64('NaT')
                ),
                index=template_asset_timeline.index,
                dtype='datetime64[ns]'
            )

            # Calculate sales exit date
            # Sales exit date = Period End date of the last month with revenue
            # This is more accurate than adding duration to start date
            _land_sales_revenue_arr_exit = o_land_sales_revenue.values
            _has_revenue = _land_sales_revenue_arr_exit > 0
            
            # Last non-zero column index per row (reverse argmax)
            _reversed_has_revenue = np.flip(_has_revenue, axis=1)
            _last_revenue_col_reversed = _reversed_has_revenue.argmax(axis=1)
            _last_revenue_col = np.where(
                _has_revenue.any(axis=1),
                _has_revenue.shape[1] - 1 - _last_revenue_col_reversed,
                -1
            )
            
            # Get the period end date for the last revenue column
            _period_ends_arr = model_timeline_me['Period End'].values
            
            temp_sales_exit_date = pd.Series(
                np.where(
                    (_last_revenue_col >= 0) & (w_escrow_flag == 1.0),
                    _period_ends_arr[np.clip(_last_revenue_col, 0, len(_period_ends_arr) - 1)],
                    np.datetime64('NaT')
                ),
                index=template_asset_timeline.index,
                dtype='datetime64[ns]'
            )

            # Calculate key dates
            last_unit_exit_date = max(temp_sales_exit_date.max(), temp_post_infrastructure_end_date.max(), temp_post_soft_cost_end_date.max())
            retention_release_final_date = (last_unit_exit_date + pd.DateOffset(months=Global.EscrowAssumptions.retention_release_duration) + pd.Timedelta(days=1)).replace(day=1)  # Add one day to move to next period after last unit exit

            # Determine last year release date based on assumptions
            if Global.EscrowAssumptions.last_year_release_option == "Retention Release Date":
                last_year_release_date = retention_release_final_date
            else:
                last_year_release_date = temp_post_infrastructure_end_date.max() + pd.DateOffset(months=Global.EscrowAssumptions.last_year_release_duration)

            # ============================================================================================
            # ESCROW CALCULATIONS (VECTORIZED ACROSS ROWS)
            # ============================================================================================
            # Pre-compute values that don't change per column iteration
            
            # Calculate temp_release_flag for all rows (vectorized)
            temp_release_flags = (w_construction_progress_percent.sum(axis=1).round(3) >= 0.999)
            
            # Pre-compute soft cost payment requirement (independent of column iteration)
            w_soft_cost_payment_requirement = o_total_soft_cost_payment + o_total_corporate_overheads_capitalized
            
            # Pre-compute hard cost payment requirement (independent of column iteration)
            w_hard_cost_payment_requirement = o_total_infrastructure_cost_payment.copy()
            
            # Pre-compute escrow setup fees conditions (vectorized)
            _land_sales_revenue_sum = o_land_sales_revenue.sum(axis=1)
            _inflows_to_escrow_sum = o_inflows_to_escrow.sum(axis=1)
            _escrow_setup_fee_amount = Global.EscrowAssumptions.escrow_set_up_fee * _land_sales_revenue_sum
            _escrow_setup_eligible = _inflows_to_escrow_sum != 0.0
            
            # Pre-compute cumulative retention for retention release calculation
            _cumulative_retention = o_transfer_to_retention.cumsum(axis=1)
            
            # Get numpy arrays for faster access
            _perm_license_flag = w_permanent_license_date_flag.values
            _funds_soft = o_funds_available_for_soft_cost.values
            _funds_hard = o_funds_available_for_hard_cost.values
            _period_starts = model_timeline_me['Period Start'].values
            
            # Get underlying numpy arrays for direct assignment (avoids pandas dtype warnings)
            _soft_opening_balance = w_soft_opening_balance.values
            _soft_cost_total_availability = w_soft_cost_total_availability.values
            _soft_cost_cumulative_requirement = w_soft_cost_cumulative_requirement.values
            _soft_cost_payment_from_escrow = w_soft_cost_payment_from_escrow.values
            _additional_requirements_for_soft_cost = w_additional_requirements_for_soft_cost.values
            _amount_available_for_reallocation = w_amount_available_for_reallocation.values
            _hard_opening_balance = w_hard_opening_balance.values
            _hard_cost_total_availability = w_hard_cost_total_availability.values
            _hard_cost_cumulative_requirement = w_hard_cost_cumulative_requirement.values
            _hard_cost_payment_from_escrow = w_hard_cost_payment_from_escrow.values
            _additional_requirements_for_hard_cost = w_additional_requirements_for_hard_cost.values
            _reallocation_amount = w_reallocation_amount.values
            _reallocated_funds_for_hard_cost_payment = w_reallocated_funds_for_hard_cost_payment.values
            _additional_requirement_after_allocation = w_additional_requirement_after_allocation.values
            _amount_available_after_hard_cost_payment = w_amount_available_after_hard_cost_payment.values
            _last_year_release_hard_cost = w_last_year_release_hard_cost.values
            _hard_closing_balance = w_hard_closing_balance.values
            _amount_available_after_soft_cost_and_reallocated_payment = w_amount_available_after_soft_cost_and_reallocated_payment.values
            _last_year_release_soft_cost = w_last_year_release_soft_cost.values
            _soft_closing_balance = w_soft_closing_balance.values
            _retention_release = w_retention_release.values
            _cash_inflow_from_off_plan_sales = o_cash_inflow_from_off_plan_sales.values
            _escrow_setup_fees = o_escrow_setup_fees.values
            _soft_cost_payment_req = w_soft_cost_payment_requirement.values
            _hard_cost_payment_req = w_hard_cost_payment_requirement.values
            _cumulative_retention_vals = _cumulative_retention.values
            _temp_release_flags = temp_release_flags.values
            _escrow_setup_eligible_vals = _escrow_setup_eligible.values
            _escrow_setup_fee_amount_vals = _escrow_setup_fee_amount.values
            
            # Column-by-column iteration (required due to sequential dependencies)
            # but vectorized across all rows within each column
            for col in range(len(model_timeline_me)):
                period_start = _period_starts[col]
                
                # ========== SOFT COST CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Soft opening balance: previous column's closing balance (or 0 for first column)
                if col > 0:
                    _soft_opening_balance[:, col] = _soft_closing_balance[:, col - 1]
                # else: already initialized to 0.0
                
                # Soft cost total availability
                _soft_cost_total_availability[:, col] = _soft_opening_balance[:, col] + _funds_soft[:, col]
                
                # Soft cost cumulative requirement
                if col > 0:
                    _soft_cost_cumulative_requirement[:, col] = (
                        _soft_cost_payment_req[:, col] + _additional_requirements_for_soft_cost[:, col - 1]
                    )
                else:
                    _soft_cost_cumulative_requirement[:, col] = _soft_cost_payment_req[:, col]
                
                # Soft cost payment from escrow
                _soft_cost_payment_from_escrow[:, col] = np.maximum(
                    0.0,
                    np.minimum(
                        _soft_cost_total_availability[:, col],
                        _soft_cost_cumulative_requirement[:, col] * _perm_license_flag[:, col]
                    )
                )
                
                # Additional requirements for soft cost
                _additional_requirements_for_soft_cost[:, col] = np.where(
                    _perm_license_flag[:, col] == 0.0,
                    _soft_cost_cumulative_requirement[:, col],
                    _soft_cost_cumulative_requirement[:, col] - _soft_cost_payment_from_escrow[:, col]
                )
                
                # Amount available for reallocation
                _amount_available_for_reallocation[:, col] = (
                    _soft_cost_total_availability[:, col] - _soft_cost_payment_from_escrow[:, col]
                )
                
                # ========== HARD COST CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Hard opening balance: previous column's closing balance (or 0 for first column)
                if col > 0:
                    _hard_opening_balance[:, col] = _hard_closing_balance[:, col - 1]
                # else: already initialized to 0.0
                
                # Hard cost total availability
                _hard_cost_total_availability[:, col] = _hard_opening_balance[:, col] + _funds_hard[:, col]
                
                # Hard cost cumulative requirement
                if col > 0:
                    _hard_cost_cumulative_requirement[:, col] = (
                        _hard_cost_payment_req[:, col] + _additional_requirement_after_allocation[:, col - 1]
                    )
                else:
                    _hard_cost_cumulative_requirement[:, col] = _hard_cost_payment_req[:, col]
                
                # Hard cost payment from escrow
                _hard_cost_payment_from_escrow[:, col] = np.maximum(
                    0.0,
                    np.minimum(
                        _hard_cost_total_availability[:, col],
                        _hard_cost_cumulative_requirement[:, col] * _perm_license_flag[:, col]
                    )
                )
                
                # Additional requirements for hard cost
                _additional_requirements_for_hard_cost[:, col] = np.where(
                    _perm_license_flag[:, col] == 0.0,
                    _hard_cost_cumulative_requirement[:, col],
                    _hard_cost_cumulative_requirement[:, col] - _hard_cost_payment_from_escrow[:, col]
                )
                
                # ========== REALLOCATION CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Reallocation amount
                _reallocation_amount[:, col] = (
                    _amount_available_for_reallocation[:, col] * _perm_license_flag[:, col] * reallocation_flag
                )
                
                # Reallocated funds for hard cost payment
                _reallocated_funds_for_hard_cost_payment[:, col] = np.minimum(
                    _reallocation_amount[:, col],
                    _additional_requirements_for_hard_cost[:, col]
                )
                
                # Additional requirement after allocation
                _additional_requirement_after_allocation[:, col] = np.maximum(
                    0.0,
                    _additional_requirements_for_hard_cost[:, col] - _reallocated_funds_for_hard_cost_payment[:, col]
                )
                
                # Amount available after hard cost payment
                _amount_available_after_hard_cost_payment[:, col] = np.maximum(
                    0.0,
                    _hard_cost_total_availability[:, col] - _hard_cost_payment_from_escrow[:, col]
                )
                
                # ========== LAST YEAR RELEASE - HARD COST (VECTORIZED) ==========
                # Release only if period_start == last_year_release_date AND temp_release_flag is True
                is_last_year_release = (pd.Timestamp(period_start) == pd.Timestamp(last_year_release_date))

                _last_year_release_hard_cost[:, col] = np.where(
                    is_last_year_release & _temp_release_flags,
                    _amount_available_after_hard_cost_payment[:, col],
                    0.0
                )
                
                # Hard closing balance
                _hard_closing_balance[:, col] = (
                    _amount_available_after_hard_cost_payment[:, col] - _last_year_release_hard_cost[:, col]
                )
                
                # ========== SOFT COST CLOSING CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Amount available after soft cost and reallocated payment
                _amount_available_after_soft_cost_and_reallocated_payment[:, col] = np.maximum(
                    0.0,
                    _amount_available_for_reallocation[:, col] - (
                        _perm_license_flag[:, col] * (
                            _reallocated_funds_for_hard_cost_payment[:, col] + 
                            _additional_requirements_for_soft_cost[:, col]
                        )
                    )
                )
                
                # Last year release - soft cost
                _last_year_release_soft_cost[:, col] = np.where(
                    is_last_year_release & _temp_release_flags,
                    _amount_available_after_soft_cost_and_reallocated_payment[:, col],
                    0.0
                )
                
                # Soft closing balance
                _soft_closing_balance[:, col] = (
                    _amount_available_after_soft_cost_and_reallocated_payment[:, col] - _last_year_release_soft_cost[:, col]
                )
                
                # ========== RETENTION RELEASE (VECTORIZED) ==========
                # Release cumulative retention if period_start == retention_release_final_date AND temp_release_flag is True
                
                is_retention_release = (pd.Timestamp(period_start).date() == pd.Timestamp(retention_release_final_date).date())
                _retention_release[:, col] = np.where(
                    is_retention_release & _temp_release_flags,
                    _cumulative_retention_vals[:, col],
                    0.0
                )
                
                # ========== CASH INFLOW FROM OFF-PLAN SALES (VECTORIZED) ==========
                _cash_inflow_from_off_plan_sales[:, col] = (
                    _retention_release[:, col] +
                    _last_year_release_hard_cost[:, col] +
                    _last_year_release_soft_cost[:, col] +
                    _hard_cost_payment_from_escrow[:, col] +
                    _soft_cost_payment_from_escrow[:, col] +
                    _reallocated_funds_for_hard_cost_payment[:, col]
                )
                
                # ========== ESCROW SETUP FEES (VECTORIZED) ==========
                is_temp_license_date = (period_start == w_temporary_license_date)
                _escrow_setup_fees[:, col] = np.where(
                    is_temp_license_date & _escrow_setup_eligible_vals,
                    _escrow_setup_fee_amount_vals,
                    0.0
                )
            
            # ============================================================================================
            # EXPLICIT DATAFRAME ASSIGNMENTS FROM NUMPY ARRAYS (ESCROW CALCULATIONS)
            # ============================================================================================
            
            _idx = template_asset_timeline.index
            _cols = template_asset_timeline.columns
            
            w_soft_opening_balance = pd.DataFrame(_soft_opening_balance, index=_idx, columns=_cols)
            w_soft_cost_total_availability = pd.DataFrame(_soft_cost_total_availability, index=_idx, columns=_cols)
            w_soft_cost_cumulative_requirement = pd.DataFrame(_soft_cost_cumulative_requirement, index=_idx, columns=_cols)
            w_soft_cost_payment_from_escrow = pd.DataFrame(_soft_cost_payment_from_escrow, index=_idx, columns=_cols)
            w_additional_requirements_for_soft_cost = pd.DataFrame(_additional_requirements_for_soft_cost, index=_idx, columns=_cols)
            w_amount_available_for_reallocation = pd.DataFrame(_amount_available_for_reallocation, index=_idx, columns=_cols)
            w_hard_opening_balance = pd.DataFrame(_hard_opening_balance, index=_idx, columns=_cols)
            w_hard_cost_total_availability = pd.DataFrame(_hard_cost_total_availability, index=_idx, columns=_cols)
            w_hard_cost_cumulative_requirement = pd.DataFrame(_hard_cost_cumulative_requirement, index=_idx, columns=_cols)
            w_hard_cost_payment_from_escrow = pd.DataFrame(_hard_cost_payment_from_escrow, index=_idx, columns=_cols)
            w_additional_requirements_for_hard_cost = pd.DataFrame(_additional_requirements_for_hard_cost, index=_idx, columns=_cols)
            w_reallocation_amount = pd.DataFrame(_reallocation_amount, index=_idx, columns=_cols)
            w_reallocated_funds_for_hard_cost_payment = pd.DataFrame(_reallocated_funds_for_hard_cost_payment, index=_idx, columns=_cols)
            w_additional_requirement_after_allocation = pd.DataFrame(_additional_requirement_after_allocation, index=_idx, columns=_cols)
            w_amount_available_after_hard_cost_payment = pd.DataFrame(_amount_available_after_hard_cost_payment, index=_idx, columns=_cols)
            w_last_year_release_hard_cost = pd.DataFrame(_last_year_release_hard_cost, index=_idx, columns=_cols)
            w_hard_closing_balance = pd.DataFrame(_hard_closing_balance, index=_idx, columns=_cols)
            w_amount_available_after_soft_cost_and_reallocated_payment = pd.DataFrame(_amount_available_after_soft_cost_and_reallocated_payment, index=_idx, columns=_cols)
            w_last_year_release_soft_cost = pd.DataFrame(_last_year_release_soft_cost, index=_idx, columns=_cols)
            w_soft_closing_balance = pd.DataFrame(_soft_closing_balance, index=_idx, columns=_cols)
            w_retention_release = pd.DataFrame(_retention_release, index=_idx, columns=_cols)
            o_cash_inflow_from_off_plan_sales = pd.DataFrame(_cash_inflow_from_off_plan_sales, index=_idx, columns=_cols)
            o_escrow_setup_fees = pd.DataFrame(_escrow_setup_fees, index=_idx, columns=_cols)
            
            # ============================================================================================
            # EXPORT ESCROW DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('escrow', False):
                _escrow_exports = {
                    # Construction Progress & S-Curve
                    'Cons Progress %': w_construction_progress_percent,
                    'Cumulative Cons Progress %': w_cumulative_construction_progress_percent,
                    'Primary Infra End Date': w_primary_infra_end_date,
                    'Secondary Infra End Date': w_secondary_infra_end_date,
                    'Combined Infra End Date': w_infrastructure_end_date,
                    # Payment Absorption
                    'Payment Absorption %': o_land_sales_payment_absorption,
                    # Escrow Flags & Dates
                    'Escrow Flag': w_escrow_flag,
                    'Temporary License Flag': w_temporary_license_flag,
                    'Permanent License Date': w_permanent_license_date,
                    'Permanent License Flag': w_permanent_license_date_flag,
                    # Key Dates
                    'Post Infra End Date': temp_post_infrastructure_end_date,
                    'Post Soft Cost End Date': temp_post_soft_cost_end_date,
                    'Sales Exit Date': temp_sales_exit_date,
                    'Last Year Release Date': last_year_release_date,
                    # Inflows & Utilization
                    'Total Inflows': o_inflows_to_escrow,
                    'Funds Avail Soft': o_funds_available_for_soft_cost,
                    'Funds Avail Hard': o_funds_available_for_hard_cost,
                    # Retention & Release
                    'Transfer to Retention': o_transfer_to_retention,
                    'Retention Release': w_retention_release,
                    # Soft Cost Workings
                    'Soft Opening Bal': w_soft_opening_balance,
                    'Soft Inflows': o_funds_available_for_soft_cost,
                    'Soft Cost Total Avail': w_soft_cost_total_availability,
                    'Soft Cost Payment Req': w_soft_cost_payment_requirement,
                    'Soft Cost Cumulative Req': w_soft_cost_cumulative_requirement,
                    'Soft Cost Payment': w_soft_cost_payment_from_escrow,
                    'Soft Additional Req': w_additional_requirements_for_soft_cost,
                    'Soft After Realloc': w_amount_available_after_soft_cost_and_reallocated_payment,
                    'Soft Last Yr Release': w_last_year_release_soft_cost,
                    'Soft Closing Bal': w_soft_closing_balance,
                    # Hard Cost Workings
                    'Hard Opening Bal': w_hard_opening_balance,
                    'Hard Inflows': o_funds_available_for_hard_cost,
                    'Hard Cost Total Avail': w_hard_cost_total_availability,
                    'Hard Cost Payment Req': w_hard_cost_payment_requirement,
                    'Hard Cost Cumulative Req': w_hard_cost_cumulative_requirement,
                    'Hard Cost Payment': w_hard_cost_payment_from_escrow,
                    'Hard Additional Req': w_additional_requirements_for_hard_cost,
                    'Hard After Realloc': w_amount_available_after_hard_cost_payment,
                    'Hard Last Yr Release': w_last_year_release_hard_cost,
                    'Hard Closing Bal': w_hard_closing_balance,
                    # Reallocation Workings
                    'Amount Avail for Reallocation': w_amount_available_for_reallocation,
                    'Reallocation Amount': w_reallocation_amount,
                    'Reallocated Funds for Hard Cost': w_reallocated_funds_for_hard_cost_payment,
                    'Additional Req After Allocation': w_additional_requirement_after_allocation,
                    # Escrow Outputs
                    'Off-Plan Cash Inflow': o_cash_inflow_from_off_plan_sales,
                    'Escrow Setup Fees': o_escrow_setup_fees,
                }
                _export_to_excel(_escrow_exports, 'export_escrow', 'Escrow')
                
            # ============================================================================================
            # ON-PLAN SALES COLLECTION
            # ============================================================================================

            o_on_plan_sales_collection = _create_zero_df() # Initialize all to 0.0

            w_on_plan_sales_collection_phasing = _create_zero_df()

            w_on_plan_sales_profile_option = np.where(
                pd.Series(Asset.BusinessModelModule.business_model) == "Land Sale",
                "User Defined",
                "None"
            )

            w_start_dates = np.where(
                pd.Series(Asset.LandSalesModule.escrow_applicability) == "Yes",
                temp_post_infrastructure_end_date,
                pd.Series(Asset.LandSalesModule.collection_start_date)
            ).astype('datetime64[ns]')

            # Vectorized calculation of slice_idx_series
            # Convert start dates to numpy array for broadcasting
            start_dates_arr = pd.to_datetime(pd.Series(w_start_dates)).values.reshape(-1, 1)
            period_starts_arr = model_timeline_me['Period Start'].values.reshape(1, -1)
            
            # Create mask where period_start >= start_date for each asset
            valid_periods_mask = period_starts_arr >= start_dates_arr
            
            # Find first valid column index for each row (argmax returns first True)
            # Use -1 for rows with no valid periods (all False or NaT start date)
            has_valid_period = valid_periods_mask.any(axis=1)
            slice_idx_arr = np.where(
                has_valid_period,
                valid_periods_mask.argmax(axis=1),
                -1
            )
            
            # Handle NaT start dates
            start_dates_nat_mask = pd.isna(w_start_dates)
            slice_idx_arr = np.where(start_dates_nat_mask, -1, slice_idx_arr)
            
            slice_idx_series = pd.Series(
                np.where(slice_idx_arr >= 0, slice_idx_arr, pd.NA),
                index=template_asset_timeline.index,
                dtype='Int64'
            )
            
            # Get escrow applicability for each asset
            escrow_applicability = pd.Series(Asset.LandSalesModule.escrow_applicability)
            
            # Vectorized calculation of on-plan sales amount
            # Create a mask where columns >= slice_idx for each row
            num_cols = o_land_sales_revenue.shape[1]
            col_indices = np.arange(num_cols).reshape(1, -1)
            slice_idx_broadcast = slice_idx_arr.reshape(-1, 1)
            
            # Mask: True for columns >= slice_idx, False otherwise (also False if slice_idx is -1)
            revenue_mask = (col_indices >= slice_idx_broadcast) & (slice_idx_broadcast >= 0)
            
            # Apply mask and sum for escrow applicability = "Yes"
            masked_revenue = o_land_sales_revenue.values * revenue_mask
            masked_revenue_sum = masked_revenue.sum(axis=1)
            
            # Full revenue sum for escrow applicability != "Yes"
            full_revenue_sum = o_land_sales_revenue.values.sum(axis=1)
            
            # Use masked sum for escrow_applicability = "Yes", otherwise full sum
            escrow_yes_mask = (escrow_applicability == "Yes").values
            w_on_plan_sales_amount = pd.Series(
                np.where(escrow_yes_mask, masked_revenue_sum, full_revenue_sum),
                index=template_asset_timeline.index,
                dtype=float
            )

            # Call the generalized function for user-defined profile calculation
            w_on_plan_sales_collection_phasing = fn_calculate_user_defined_profile(
                template=w_on_plan_sales_collection_phasing,
                profile_options=w_on_plan_sales_profile_option,
                schedules=_get_named_range_value("s.landco.sales.collection"),
                start_dates=w_start_dates,
                durations=Asset.LandSalesModule.collection_duration,
                model_timeline_me=model_timeline_me
            )

            # For escrow applicability = "No": use phasing * sum of revenue from slice_idx
            # For escrow applicability = "Yes": use revenue directly from slice_idx (no phasing)
            o_on_plan_sales_collection_no_escrow = w_on_plan_sales_collection_phasing.mul(w_on_plan_sales_amount, axis=0)
            
            # Vectorized creation of o_on_plan_sales_collection_with_escrow
            # Apply revenue_mask to copy values only from slice_idx onwards per asset
            o_on_plan_sales_collection_with_escrow = pd.DataFrame(
                o_land_sales_revenue.values * revenue_mask,
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )
            
            # Apply conditional logic based on escrow applicability per row
            escrow_mask = (escrow_applicability == "Yes").values.reshape(-1, 1)
            o_on_plan_sales_collection = pd.DataFrame(
                np.where(
                    escrow_mask,
                    o_on_plan_sales_collection_with_escrow.values,
                    o_on_plan_sales_collection_no_escrow.values),
                index=o_on_plan_sales_collection_no_escrow.index,
                columns=o_on_plan_sales_collection_no_escrow.columns
            )

            # ============================================================================================
            # EXPORT ON-PLAN SALES COLLECTION DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('on_plan_sales_collection', False):
                _on_plan_sales_exports = {
                    'Land Sales Revenue': o_land_sales_revenue,
                    'Collection Phasing': w_on_plan_sales_collection_phasing,
                    'Collection No Escrow': o_on_plan_sales_collection_no_escrow,
                    'Collection With Escrow': o_on_plan_sales_collection_with_escrow,
                    'On-Plan Sales': o_on_plan_sales_collection,
                    'Sales Amount': pd.DataFrame({'On-Plan Sales Amount': w_on_plan_sales_amount}),
                    'Slice Index': pd.DataFrame({'Slice Index': slice_idx_series}),
                    'Escrow Applicability': pd.DataFrame({'Escrow Applicability': escrow_applicability}),
                    'Start Dates': pd.DataFrame({'Collection Start Date': pd.Series(w_start_dates, index=template_asset_timeline.index)}),
                    'Infra End Date': pd.DataFrame({'Post Infra End Date': temp_post_infrastructure_end_date}),
                    'Profile Option': pd.DataFrame({'Profile Option': pd.Series(w_on_plan_sales_profile_option, index=template_asset_timeline.index)}),
                    'Collection Duration': pd.DataFrame({'Collection Duration': pd.Series(Asset.LandSalesModule.collection_duration)}),
                }
                _export_to_excel(_on_plan_sales_exports, 'export_on_plan_sales_collection', 'On-Plan Sales Collection')

            # ========================================================================
            # SUB-MODULE 3.13: FINANCING MODULE
            # ========================================================================
            # This module handles all financing-related calculations including:
            #   - 3.13.1: Asset Level Financing
            #   - 3.13.2: Project Level Financing
            # ========================================================================

            _record_timing("Escrow Module")
            
            # ========================================================================
            # SUB-MODULE 3.13: COST ALLOCATION SUBMODULE
            # ========================================================================
            # Reallocate costs from source asset classes (Public Amenities, CEC, Canal)
            # to recipient assets using area-based weights. Post-allocation values are
            # pushed into existing line items (no new PA/CEC/Canal line items added).
            # ========================================================================

            _allocation_classes = [
                ("Public Amenities", "public amenities"),
                ("CEC", "cec"),
                ("Canal", "canal"),
            ]

            _asset_class_keys = (
                pd.Series(Asset.ProjectDetails.asset_class)
                .fillna("")
                .astype(str)
                .str.strip()
                .str.lower()
                .to_numpy()
            )

            _asset_gfa = pd.to_numeric(
                pd.Series(Asset.LandAreaModule.gross_floor_area),
                errors='coerce'
            ).fillna(0.0).to_numpy(dtype=float)
            _asset_bua = pd.to_numeric(
                pd.Series(Asset.LandAreaModule.built_up_area),
                errors='coerce'
            ).fillna(0.0).to_numpy(dtype=float)

            def _normalize_alloc_basis(value):
                _value = str(value).strip() if value is not None else ""
                return {"Gross Floor Area": "GFA", "Built Up Area": "BUA"}.get(_value, "GFA")

            _alloc_config = {
                "Public Amenities": _normalize_alloc_basis(Global.CostAllocationInputs.public_amenity_cost),
                "CEC": _normalize_alloc_basis(Global.CostAllocationInputs.cec_cost),
                "Canal": _normalize_alloc_basis(Global.CostAllocationInputs.canal_cost),
            }

            _special_class_keys = [cls_key for _, cls_key in _allocation_classes]
            _source_mask_all = np.isin(_asset_class_keys, _special_class_keys)
            _recipient_mask_default = ~_source_mask_all

            def _get_class_recipient_mask(attr_name):
                if not hasattr(Asset, "CostAllocation"):
                    return _recipient_mask_default.copy()

                _raw = getattr(Asset.CostAllocation, attr_name, None)
                if _raw is None:
                    return _recipient_mask_default.copy()

                _mask_series = pd.Series(_raw)
                if len(_mask_series) != _n_assets:
                    return _recipient_mask_default.copy()

                _allocation_mask = (
                    _mask_series
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .eq("cost allocation")
                    .to_numpy()
                )

                if not _allocation_mask.any():
                    return _recipient_mask_default.copy()

                return _recipient_mask_default & _allocation_mask

            _allocation_attr_map = {
                "Public Amenities": "public_amenities",
                "CEC": "cec",
                "Canal": "canal",
            }

            _allocation_components = {
                "land_acquisition_cost_cash_payment": o_land_acquisition_cost_cash_payment,
                "land_acquisition_cost_in_kind": o_land_acquisition_cost_in_kind,
                "transaction_legal": o_acquisition_transaction_cost_legal,
                "transaction_agency": o_acquisition_transaction_cost_agency,
                "transaction_technical": o_acquisition_transaction_cost_technical,
                "transaction_valuation": o_acquisition_transaction_cost_valuation,
                "transaction_due_diligence": o_acquisition_transaction_cost_due_diligence,
                "transaction_real_estate_tax": o_acquisition_transaction_cost_real_estate_transaction_tax,
                "transaction_municipal_fees": o_acquisition_transaction_cost_municipal_fees,
                "infrastructure_primary": o_primary_infrastructure_cost_payment,
                "infrastructure_secondary": o_secondary_infrastructure_cost_payment,
                "soft_design": o_design_cost_payment,
                "soft_permitting": o_permitting_cost_payment,
                "soft_supervision": o_supervision_cost_payment,
                "soft_pm": o_project_management_cost_payment,
                "soft_contingency": o_contingency_cost_payment,
                "coh_salaries_expensed": o_corporate_overheads_salaries_expensed,
                "coh_it_services_expensed": o_corporate_overheads_it_services_expensed,
                "coh_office_rent_expensed": o_corporate_overheads_office_rent_and_utilities_expensed,
                "coh_professional_services_expensed": o_corporate_overheads_professional_services_expensed,
                "coh_marketing_expensed": o_corporate_overheads_marketing_expensed,
                "coh_sales_cost_expensed": o_corporate_overheads_sales_cost_expensed,
                "coh_additional_expensed": o_corporate_overheads_additional_expenses_expensed,
                "coh_salaries_capitalized": o_corporate_overheads_salaries_capitalized,
                "coh_it_services_capitalized": o_corporate_overheads_it_services_capitalized,
                "coh_office_rent_capitalized": o_corporate_overheads_office_rent_and_utilities_capitalized,
                "coh_professional_services_capitalized": o_corporate_overheads_professional_services_capitalized,
                "coh_marketing_capitalized": o_corporate_overheads_marketing_capitalized,
                "coh_sales_cost_capitalized": o_corporate_overheads_sales_cost_capitalized,
                "coh_additional_capitalized": o_corporate_overheads_additional_expenses_capitalized,
                "other_income_1": o_other_income_1,
                "other_income_2": o_other_income_2,
                "government_subsidies": o_other_income_3,
                "other_expense_1": o_other_expense_1,
                "other_expense_2": o_other_expense_2,
                "other_expense_3": o_other_expense_3,
            }

            _component_values = {}
            for _comp_name, _comp_df in _allocation_components.items():
                _values = _comp_df.to_numpy(copy=True).astype(float)
                _values = np.where(np.isfinite(_values), _values, 0.0)
                _component_values[_comp_name] = _values

            o_pa_allocation = _create_zero_df()
            o_cec_allocation = _create_zero_df()
            o_canal_allocation = _create_zero_df()

            _allocation_output_map = {
                "Public Amenities": o_pa_allocation,
                "CEC": o_cec_allocation,
                "Canal": o_canal_allocation,
            }

            for _class_name, _class_key in _allocation_classes:
                _class_source_indices = np.where(_asset_class_keys == _class_key)[0]
                if len(_class_source_indices) == 0:
                    continue

                _recipient_mask = _get_class_recipient_mask(_allocation_attr_map[_class_name])
                _basis = _alloc_config.get(_class_name, "GFA")

                _recipient_area = _asset_gfa.copy() if _basis == "GFA" else _asset_bua.copy()
                _recipient_area[~_recipient_mask] = 0.0
                _recipient_area = np.where(np.isfinite(_recipient_area), _recipient_area, 0.0)

                _total_recipient_area = _recipient_area.sum()
                if _total_recipient_area <= 0.0:
                    continue

                _recipient_weights = _recipient_area / _total_recipient_area
                _allocated_total = np.zeros((_n_assets, _n_periods), dtype=float)

                for _comp_name, _comp_values in _component_values.items():
                    _class_pool = _comp_values[_class_source_indices, :].sum(axis=0)
                    if not np.any(_class_pool):
                        continue

                    _comp_values[_class_source_indices, :] = 0.0
                    _allocated_component = np.outer(_recipient_weights, _class_pool)
                    _comp_values += _allocated_component
                    _allocated_total += _allocated_component

                _allocation_output_map[_class_name].loc[:, :] = _allocated_total

            o_total_allocation = _create_zero_df()
            o_total_allocation.loc[:, :] = (
                o_pa_allocation.values + o_cec_allocation.values + o_canal_allocation.values
            )

            def _values_to_df(values):
                return pd.DataFrame(
                    np.round(values, 6),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns,
                )

            o_land_acquisition_cost_cash_payment_post_allocation = _values_to_df(_component_values["land_acquisition_cost_cash_payment"])
            o_land_acquisition_cost_in_kind_post_allocation = _values_to_df(_component_values["land_acquisition_cost_in_kind"])

            o_acquisition_transaction_cost_legal_post_allocation = _values_to_df(_component_values["transaction_legal"])
            o_acquisition_transaction_cost_agency_post_allocation = _values_to_df(_component_values["transaction_agency"])
            o_acquisition_transaction_cost_technical_post_allocation = _values_to_df(_component_values["transaction_technical"])
            o_acquisition_transaction_cost_valuation_post_allocation = _values_to_df(_component_values["transaction_valuation"])
            o_acquisition_transaction_cost_due_diligence_post_allocation = _values_to_df(_component_values["transaction_due_diligence"])
            o_acquisition_transaction_cost_real_estate_transaction_tax_post_allocation = _values_to_df(_component_values["transaction_real_estate_tax"])
            o_acquisition_transaction_cost_municipal_fees_post_allocation = _values_to_df(_component_values["transaction_municipal_fees"])

            o_primary_infrastructure_cost_payment_post_allocation = _values_to_df(_component_values["infrastructure_primary"])
            o_secondary_infrastructure_cost_payment_post_allocation = _values_to_df(_component_values["infrastructure_secondary"])

            o_design_cost_payment_post_allocation = _values_to_df(_component_values["soft_design"])
            o_permitting_cost_payment_post_allocation = _values_to_df(_component_values["soft_permitting"])
            o_supervision_cost_payment_post_allocation = _values_to_df(_component_values["soft_supervision"])
            o_project_management_cost_payment_post_allocation = _values_to_df(_component_values["soft_pm"])
            o_contingency_cost_payment_post_allocation = _values_to_df(_component_values["soft_contingency"])

            o_corporate_overheads_salaries_expensed_post_allocation = _values_to_df(_component_values["coh_salaries_expensed"])
            o_corporate_overheads_it_services_expensed_post_allocation = _values_to_df(_component_values["coh_it_services_expensed"])
            o_corporate_overheads_office_rent_and_utilities_expensed_post_allocation = _values_to_df(_component_values["coh_office_rent_expensed"])
            o_corporate_overheads_professional_services_expensed_post_allocation = _values_to_df(_component_values["coh_professional_services_expensed"])
            o_corporate_overheads_marketing_expensed_post_allocation = _values_to_df(_component_values["coh_marketing_expensed"])
            o_corporate_overheads_sales_cost_expensed_post_allocation = _values_to_df(_component_values["coh_sales_cost_expensed"])
            o_corporate_overheads_additional_expenses_expensed_post_allocation = _values_to_df(_component_values["coh_additional_expensed"])

            o_corporate_overheads_salaries_capitalized_post_allocation = _values_to_df(_component_values["coh_salaries_capitalized"])
            o_corporate_overheads_it_services_capitalized_post_allocation = _values_to_df(_component_values["coh_it_services_capitalized"])
            o_corporate_overheads_office_rent_and_utilities_capitalized_post_allocation = _values_to_df(_component_values["coh_office_rent_capitalized"])
            o_corporate_overheads_professional_services_capitalized_post_allocation = _values_to_df(_component_values["coh_professional_services_capitalized"])
            o_corporate_overheads_marketing_capitalized_post_allocation = _values_to_df(_component_values["coh_marketing_capitalized"])
            o_corporate_overheads_sales_cost_capitalized_post_allocation = _values_to_df(_component_values["coh_sales_cost_capitalized"])
            o_corporate_overheads_additional_expenses_capitalized_post_allocation = _values_to_df(_component_values["coh_additional_capitalized"])

            o_other_income_1_post_allocation = _values_to_df(_component_values["other_income_1"])
            o_other_income_2_post_allocation = _values_to_df(_component_values["other_income_2"])
            o_other_income_3_post_allocation = _values_to_df(_component_values["government_subsidies"])
            o_other_expense_1_post_allocation = _values_to_df(_component_values["other_expense_1"])
            o_other_expense_2_post_allocation = _values_to_df(_component_values["other_expense_2"])
            o_other_expense_3_post_allocation = _values_to_df(_component_values["other_expense_3"])

            o_total_infrastructure_cost_payment_post_allocation = (
                o_primary_infrastructure_cost_payment_post_allocation + o_secondary_infrastructure_cost_payment_post_allocation
            )
            o_total_soft_cost_payment_post_allocation = (
                o_design_cost_payment_post_allocation + o_permitting_cost_payment_post_allocation +
                o_supervision_cost_payment_post_allocation + o_project_management_cost_payment_post_allocation
            )
            o_total_corporate_overheads_expensed_post_allocation = (
                o_corporate_overheads_salaries_expensed_post_allocation +
                o_corporate_overheads_it_services_expensed_post_allocation +
                o_corporate_overheads_office_rent_and_utilities_expensed_post_allocation +
                o_corporate_overheads_professional_services_expensed_post_allocation +
                o_corporate_overheads_marketing_expensed_post_allocation +
                o_corporate_overheads_sales_cost_expensed_post_allocation +
                o_corporate_overheads_additional_expenses_expensed_post_allocation
            )
            o_total_corporate_overheads_capitalized_post_allocation = (
                o_corporate_overheads_salaries_capitalized_post_allocation +
                o_corporate_overheads_it_services_capitalized_post_allocation +
                o_corporate_overheads_office_rent_and_utilities_capitalized_post_allocation +
                o_corporate_overheads_professional_services_capitalized_post_allocation +
                o_corporate_overheads_marketing_capitalized_post_allocation +
                o_corporate_overheads_sales_cost_capitalized_post_allocation +
                o_corporate_overheads_additional_expenses_capitalized_post_allocation
            )
            o_total_other_income_post_allocation = (
                o_other_income_1_post_allocation + o_other_income_2_post_allocation + o_other_income_3_post_allocation
            )
            o_total_other_expenses_post_allocation = (
                o_other_expense_1_post_allocation + o_other_expense_2_post_allocation + o_other_expense_3_post_allocation
            )
            o_net_other_income_post_allocation = (
                o_total_other_income_post_allocation - o_total_other_expenses_post_allocation
            )

            # Route downstream logic through post-allocation dataframes so final/JV/
            # consolidation outputs reflect allocation without adding new line items.
            o_land_acquisition_cost_cash_payment = o_land_acquisition_cost_cash_payment_post_allocation
            o_land_acquisition_cost_in_kind = o_land_acquisition_cost_in_kind_post_allocation
            o_land_acquisition_cost = o_land_acquisition_cost_cash_payment + o_land_acquisition_cost_in_kind

            o_acquisition_transaction_cost_legal = o_acquisition_transaction_cost_legal_post_allocation
            o_acquisition_transaction_cost_agency = o_acquisition_transaction_cost_agency_post_allocation
            o_acquisition_transaction_cost_technical = o_acquisition_transaction_cost_technical_post_allocation
            o_acquisition_transaction_cost_valuation = o_acquisition_transaction_cost_valuation_post_allocation
            o_acquisition_transaction_cost_due_diligence = o_acquisition_transaction_cost_due_diligence_post_allocation
            o_acquisition_transaction_cost_real_estate_transaction_tax = o_acquisition_transaction_cost_real_estate_transaction_tax_post_allocation
            o_acquisition_transaction_cost_municipal_fees = o_acquisition_transaction_cost_municipal_fees_post_allocation

            o_primary_infrastructure_cost_payment = o_primary_infrastructure_cost_payment_post_allocation
            o_secondary_infrastructure_cost_payment = o_secondary_infrastructure_cost_payment_post_allocation
            o_total_infrastructure_cost_payment = o_total_infrastructure_cost_payment_post_allocation

            o_design_cost_payment = o_design_cost_payment_post_allocation
            o_permitting_cost_payment = o_permitting_cost_payment_post_allocation
            o_supervision_cost_payment = o_supervision_cost_payment_post_allocation
            o_project_management_cost_payment = o_project_management_cost_payment_post_allocation
            o_contingency_cost_payment = o_contingency_cost_payment_post_allocation
            o_total_soft_cost_payment = o_total_soft_cost_payment_post_allocation

            o_corporate_overheads_salaries_expensed = o_corporate_overheads_salaries_expensed_post_allocation
            o_corporate_overheads_it_services_expensed = o_corporate_overheads_it_services_expensed_post_allocation
            o_corporate_overheads_office_rent_and_utilities_expensed = o_corporate_overheads_office_rent_and_utilities_expensed_post_allocation
            o_corporate_overheads_professional_services_expensed = o_corporate_overheads_professional_services_expensed_post_allocation
            o_corporate_overheads_marketing_expensed = o_corporate_overheads_marketing_expensed_post_allocation
            o_corporate_overheads_sales_cost_expensed = o_corporate_overheads_sales_cost_expensed_post_allocation
            o_corporate_overheads_additional_expenses_expensed = o_corporate_overheads_additional_expenses_expensed_post_allocation
            o_total_corporate_overheads_expensed = o_total_corporate_overheads_expensed_post_allocation

            o_corporate_overheads_salaries_capitalized = o_corporate_overheads_salaries_capitalized_post_allocation
            o_corporate_overheads_it_services_capitalized = o_corporate_overheads_it_services_capitalized_post_allocation
            o_corporate_overheads_office_rent_and_utilities_capitalized = o_corporate_overheads_office_rent_and_utilities_capitalized_post_allocation
            o_corporate_overheads_professional_services_capitalized = o_corporate_overheads_professional_services_capitalized_post_allocation
            o_corporate_overheads_marketing_capitalized = o_corporate_overheads_marketing_capitalized_post_allocation
            o_corporate_overheads_sales_cost_capitalized = o_corporate_overheads_sales_cost_capitalized_post_allocation
            o_corporate_overheads_additional_expenses_capitalized = o_corporate_overheads_additional_expenses_capitalized_post_allocation
            o_total_corporate_overheads_capitalized = o_total_corporate_overheads_capitalized_post_allocation

            o_other_income_1 = o_other_income_1_post_allocation
            o_other_income_2 = o_other_income_2_post_allocation
            o_other_income_3 = o_other_income_3_post_allocation
            o_total_other_income = o_total_other_income_post_allocation

            o_other_expense_1 = o_other_expense_1_post_allocation
            o_other_expense_2 = o_other_expense_2_post_allocation
            o_other_expense_3 = o_other_expense_3_post_allocation
            o_total_other_expenses = o_total_other_expenses_post_allocation
            o_net_other_income = o_net_other_income_post_allocation

            if _EXPORT_FLAGS.get('cost_allocation', False):
                _allocation_exports = {
                    'PA Allocation': o_pa_allocation,
                    'CEC Allocation': o_cec_allocation,
                    'Canal Allocation': o_canal_allocation,
                    'Total Allocation': o_total_allocation,
                    'Land Acq Cash Post Allocation': o_land_acquisition_cost_cash_payment_post_allocation,
                    'Primary Infra Post Allocation': o_primary_infrastructure_cost_payment_post_allocation,
                    'Secondary Infra Post Allocation': o_secondary_infrastructure_cost_payment_post_allocation,
                    'Soft Cost Post Allocation': o_total_soft_cost_payment_post_allocation,
                    'COH Expensed Post Allocation': o_total_corporate_overheads_expensed_post_allocation,
                    'COH Capitalized Post Allocation': o_total_corporate_overheads_capitalized_post_allocation,
                    'Other Income Post Allocation': o_total_other_income_post_allocation,
                    'Other Expenses Post Allocation': o_total_other_expenses_post_allocation,
                }
                _export_to_excel(_allocation_exports, 'export_cost_allocation', 'Cost Allocation')

            _record_timing("Cost Allocation Module")
            # ========================================================================
            # SUB-MODULE 3.13.1: ASSET LEVEL FINANCING
            # ========================================================================
            # This sub-module handles asset-level financing calculations:
            #   - Asset Level Debt Revolver: Drawdown, Repayment, Cash Reserve
            #   - Asset Level Arrangement Fees
            #   - Asset Level Interest Calculations
            #   - Asset to Project Fund Transfers
            # ========================================================================

            # ============================================================================================
            # PRE-FINANCING CASHFLOWS (Asset-wise)
            # ============================================================================================
            # Net Cashflow from Operations + Net Cashflow from Investments (including cash land acquisition payment)
            
            def fn_validate_dataframe_dimensions(dataframes_list: list, template: pd.DataFrame) -> list:
                """
                Validate and normalize DataFrames to match template dimensions.
                - Converts non-DataFrame objects to DataFrames
                - Replaces NaN/empty values with 0
                - Validates dimensions match template
                
                Args:
                    dataframes_list: List of DataFrames (or array-like) to validate
                    template: Reference DataFrame (template_asset_timeline)
                    
                Returns:
                    list: Normalized list of DataFrames with NaN replaced by 0
                    
                Raises:
                    ValueError: If any DataFrame has mismatched dimensions after conversion
                """
                expected_shape = template.shape
                normalized_dfs = []
                mismatched = []
                
                for i, df in enumerate(dataframes_list):
                    df = fn_replace_nan(df)
                    
                    # Convert to DataFrame if not already
                    if not isinstance(df, pd.DataFrame):
                        df = pd.DataFrame(df, index=template.index, columns=template.columns)
                    
                    # Replace NaN/empty with 0
                    df_values = df.to_numpy(copy=True)
                    df = pd.DataFrame(
                        np.where(pd.isna(df_values), 0.0, df_values),
                        index=df.index,
                        columns=df.columns,
                    )
                    
                    # Validate dimensions
                    if df.shape != expected_shape:
                        mismatched.append(f"  - item_{i}: {df.shape} (expected {expected_shape})")
                    
                    normalized_dfs.append(df)
                
                if mismatched:
                    raise ValueError(f"DataFrame dimension mismatch detected:\n" + "\n".join(mismatched))
                
                return normalized_dfs
            
            # Define inflows and outflows as lists for efficient stacking
            _inflow_dfs = [
                o_on_plan_sales_collection, o_cash_inflow_from_off_plan_sales,
                o_land_lease_revenue_including_grace_period,
                o_other_income_1, o_other_income_2, o_other_income_3,
                o_community_operations_amanah_recovery, o_community_operations_roshn_recovery,
                o_land_lease_exit_value, o_land_bank_exit_value
            ]
            
            _outflow_dfs = [
                o_escrow_setup_fees, o_land_lease_associated_operating_expenses,
                o_leasing_cost, o_sales_transaction_cost,
                o_other_expense_1, o_other_expense_2, o_other_expense_3,
                o_community_operations_cost_payment_amanah, o_community_operations_cost_payment_roshn,
                o_corporate_overheads_salaries_expensed, o_corporate_overheads_it_services_expensed,
                o_corporate_overheads_office_rent_and_utilities_expensed, o_corporate_overheads_professional_services_expensed,
                o_corporate_overheads_marketing_expensed, o_corporate_overheads_sales_cost_expensed,
                o_corporate_overheads_additional_expenses_expensed,
                o_land_acquisition_cost_cash_payment,
                o_acquisition_transaction_cost_legal, o_acquisition_transaction_cost_agency,
                o_acquisition_transaction_cost_technical, o_acquisition_transaction_cost_valuation,
                o_acquisition_transaction_cost_due_diligence, o_acquisition_transaction_cost_real_estate_transaction_tax,
                o_acquisition_transaction_cost_municipal_fees,
                o_primary_infrastructure_cost_payment, o_secondary_infrastructure_cost_payment,
                o_design_cost_payment, o_permitting_cost_payment, o_supervision_cost_payment, o_project_management_cost_payment,
                o_contingency_cost_payment,
                o_corporate_overheads_salaries_capitalized, o_corporate_overheads_it_services_capitalized,
                o_corporate_overheads_office_rent_and_utilities_capitalized, o_corporate_overheads_professional_services_capitalized,
                o_corporate_overheads_marketing_capitalized, o_corporate_overheads_sales_cost_capitalized,
                o_corporate_overheads_additional_expenses_capitalized
            ]
            
            # Validate, normalize, and fill NaN with 0 for all components
            _inflow_dfs = fn_validate_dataframe_dimensions(_inflow_dfs, template_asset_timeline)
            _outflow_dfs = fn_validate_dataframe_dimensions(_outflow_dfs, template_asset_timeline)
            
            # Optimized calculation using numpy stacking (single operation per group)
            _inflows_sum = np.stack([df.values for df in _inflow_dfs], axis=0).sum(axis=0)
            _outflows_sum = np.stack([df.values for df in _outflow_dfs], axis=0).sum(axis=0)
            
            w_pre_financing_cashflows = pd.DataFrame(
                _inflows_sum - _outflows_sum,
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            _jv_inclusion_flag = pd.Series(Asset.JVModule.jvjda_inclusion) == "Yes"
            _jv_landco_inclusion_flag = pd.Series(Asset.JVModule.landco_inclusion) == "Yes"
            
            _jv_asset_level_inclusion_flag = _jv_inclusion_flag & _jv_landco_inclusion_flag

            w_pre_financing_cashflows_jv_included = _create_zero_df()
            w_pre_financing_cashflows_jv_excluded = _create_zero_df()

            w_pre_financing_cashflows_jv_included[_jv_asset_level_inclusion_flag] = w_pre_financing_cashflows[_jv_asset_level_inclusion_flag]
            
            w_pre_financing_cashflows_jv_excluded = w_pre_financing_cashflows.copy()
            w_pre_financing_cashflows_jv_excluded[_jv_asset_level_inclusion_flag] = 0.0

            # ============================================================================================
            # SUPPORT WORKINGS (ASSET LEVEL FINANCING) - OPTIMIZED
            # ============================================================================================
            # Optimization strategy:
            # 1. Pre-compute all scalar values and flags at asset level (vectorized)
            # 2. Extract numpy arrays for faster access in column iteration
            # 3. Use column-by-column iteration with row-vectorized operations (like Escrow module)
            # 4. Eliminate redundant pd.Series() conversions inside loops
            # ============================================================================================

            # ============================================================================================
            # ASSET DEBT REVOLVER FLAGS AND DATES (VECTORIZED)
            # ============================================================================================

            # Pre-compute override mask once (reused for all override checks)
            _override_mask = np.array(Asset.AssetDebtRevolver.override) == "Yes"
            
            # Asset Debt Revolver - Start Date, Duration, End Date (vectorized)
            w_asset_revolver_start_date = pd.to_datetime(np.where(
                _override_mask,
                Asset.AssetDebtRevolver.revolver_facility_start_date,
                Global.FinancingAssumptions.asset_debt_revolver_revolver_facility_start_date
            ))
            
            w_asset_revolver_duration = pd.to_numeric(np.where(
                _override_mask,
                Asset.AssetDebtRevolver.revolver_facility_duration,
                Global.FinancingAssumptions.asset_debt_revolver_revolver_facility_duration
            ), errors='coerce').astype(float)
            
            # Vectorized end date calculation using DateOffset (avoid list comprehension)
            w_asset_revolver_end_date = pd.Series([
                start_date + pd.DateOffset(years=int(duration)) - pd.Timedelta(days=1)
                for start_date, duration in zip(w_asset_revolver_start_date, w_asset_revolver_duration)
            ], dtype='datetime64[ns]')

            # Asset Debt Revolver Withdrawal Flag (fully vectorized with broadcasting)
            _period_starts_dt = pd.to_datetime(model_timeline_me['Period Start']).values
            _period_ends_dt = pd.to_datetime(model_timeline_me['Period End']).values
            
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
            # BASE RATE PROFILE CALCULATION (OPTIMIZED - VECTORIZED WHERE POSSIBLE)
            # ============================================================================================
            
            w_asset_revolver_base_rate_profile = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.base_rate_profile,
                Global.FinancingAssumptions.asset_debt_revolver_base_rate_profile
            )
            
            # Fetch interest profile data once
            _interest_profile_names = assumptions.loc[
                assumptions["name"] == "a.landco.interest.profile.name", "value"
            ].iloc[0][:]
            _interest_profile_data = assumptions.loc[
                assumptions["name"] == "a.landco.interest.profile", "value"
            ].iloc[0]
            
            # Pre-compute year-to-index mapping for faster lookup
            _year_to_idx = {y: i for i, y in enumerate(_unique_years)}
            _period_year_indices = np.array([_year_to_idx[y] for y in _period_years])
            
            # Build profile name to index lookup
            _interest_profile_name_to_idx = {name: idx for idx, name in enumerate(_interest_profile_names)}
            
            # Initialize base rate percent array
            _base_rate_percent_arr = np.zeros((len(template_asset_timeline.index), len(model_timeline_me)))
            
            # Optimized: Pre-compute monthly rates for all profiles, then assign
            _valid_profile_mask = np.array([
                p in _interest_profile_names and pd.notna(p) and p != ''
                for p in w_asset_revolver_base_rate_profile
            ])
            
            for row_idx in np.where(_valid_profile_mask)[0]:
                profile_name = w_asset_revolver_base_rate_profile[row_idx]
                profile_idx = _interest_profile_name_to_idx[profile_name]
                interest_rates = np.array(_interest_profile_data[profile_idx])
                # Map rates to periods using pre-computed year indices
                rates_by_period = interest_rates[_period_year_indices]
                # Convert annual to monthly (compounded)
                _base_rate_percent_arr[row_idx, :] = rates_by_period
            
            w_asset_revolver_base_rate_percent = pd.DataFrame(
                _base_rate_percent_arr,
                index=template_asset_timeline.index,
                columns=template_asset_timeline.columns
            )

            # ============================================================================================
            # CREDIT SPREAD PROFILE CALCULATION (OPTIMIZED - VECTORIZED WHERE POSSIBLE)
            # ============================================================================================
            
            w_asset_revolver_credit_spread_percent = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.credit_spread,
                Global.FinancingAssumptions.asset_debt_revolver_credit_spread
            )
            
            # Net Interest Rate = Base Rate + Credit Spread
            w_asset_revolver_net_interest_rate_annual = w_asset_revolver_base_rate_percent.add(
                pd.Series(w_asset_revolver_credit_spread_percent,
                        index=w_asset_revolver_base_rate_percent.index),
                axis=0
            )

            w_asset_revolver_net_interest_rate_monthly = ((1 + w_asset_revolver_net_interest_rate_annual) ** (1/12)) - 1

            # ============================================================================================
            # REVOLVER PARAMETERS (VECTORIZED - PRE-COMPUTE ALL SCALARS)
            # ============================================================================================
            
            # Revolver limit (1D array - one value per asset)
            _revolver_limit = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.revolver_limit,
                Global.FinancingAssumptions.asset_debt_revolver_revolver_limit
            ).astype(float)
            
            # Reborrowing toggle (boolean mask)
            _reborrowing_toggle = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.re_borrowing_toggle,
                Global.FinancingAssumptions.asset_debt_revolver_reborrowing_toggle
            )
            _reborrowing_yes_mask = (_reborrowing_toggle == "Yes")

            # ============================================================================================
            # DEBT FEES PARAMETERS (VECTORIZED)
            # ============================================================================================
            
            _arrangement_fees_percent = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.debt_arrangement_fees,
                Global.FinancingAssumptions.asset_debt_revolver_debt_arrangement_fees
            ).astype(float)
            
            _arrangement_fees_inclusion = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.arrangement_fees_inclusion,
                Global.FinancingAssumptions.asset_debt_revolver_arrangement_fees_inclusion
            )
            _arrangement_fees_in_revolver = (_arrangement_fees_inclusion == "Yes")
            _arrangement_fees_not_in_revolver = (_arrangement_fees_inclusion == "No")
            
            _commitment_fees_percent = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.commitment_fees,
                Global.FinancingAssumptions.asset_debt_revolver_commitment_fees
            ).astype(float)
            _commitment_fees_monthly = _commitment_fees_percent / 12
            
            _commitment_fees_frequency = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.commitment_fees_payment_frequency,
                Global.FinancingAssumptions.asset_debt_revolver_commitment_fees_payment_frequency
            )
            
            # Map frequency to numeric values
            _freq_mapping = {"Annual": 12, "Quarterly": 3, "Monthly": 1}
            _commitment_freq_flag = np.array([_freq_mapping.get(f, 1) for f in _commitment_fees_frequency])
            _commitment_freq_mod = np.maximum((w_asset_revolver_start_date.month.values % _commitment_freq_flag) - 1 , 0)

            # ============================================================================================
            # CASH RESERVE PARAMETERS (VECTORIZED)
            # ============================================================================================
            
            _cash_reserve_applicability = np.where(
                _override_mask,
                Asset.AssetDebtRevolver.asset_cash_reserve_applicability,
                Global.FinancingAssumptions.asset_debt_revolver_asset_cash_reserve_applicability
            )
            _cash_reserve_flag = np.zeros_like(_cash_reserve_applicability, dtype=bool)
            
            _cash_transfer_date = pd.to_datetime(np.where(
                _override_mask,
                Asset.AssetDebtRevolver.cash_transfer_date,
                Global.FinancingAssumptions.asset_debt_revolver_cash_transfer_date
            ))

            # ============================================================================================
            # ASSET LEVEL FINANCING WORKINGS (OPTIMIZED - COLUMN-VECTORIZED)
            # ============================================================================================
            
            # Initialize DataFrames
            w_asset_debt_revolver_opening_balance = _create_zero_df()
            w_asset_debt_revolver_debt_withdrawal = _create_zero_df()
            w_asset_debt_revolver_capitalization_of_interest = _create_zero_df()
            w_asset_debt_revolver_debt_repayment = _create_zero_df()
            w_asset_debt_revolver_closing_balance = _create_zero_df()

            w_asset_debt_revolver_debt_arrangement_fees = _create_zero_df()
            w_asset_debt_revolver_debt_commitment_fees_opening_balance = _create_zero_df()
            w_asset_debt_revolver_debt_commitment_fees_accrual = _create_zero_df()
            w_asset_debt_revolver_debt_commitment_fees_payment = _create_zero_df()
            w_asset_debt_revolver_debt_commitment_fees_closing_balance = _create_zero_df()

            w_asset_cash_schedule_opening_balance = _create_zero_df()
            w_asset_cash_schedule_addition = _create_zero_df()
            w_asset_cash_schedule_cash_utilization = _create_zero_df()
            w_asset_cash_schedule_transfer_to_project = _create_zero_df()
            w_asset_cash_schedule_closing_balance = _create_zero_df()

            w_additional_requirement = _create_zero_df()

            # Extract numpy arrays for fast access (avoids pandas indexing overhead)
            _pre_fin_cf = w_pre_financing_cashflows_jv_excluded.values
            _withdrawal_flag = w_asset_revolver_withdrawal_flag.values
            _net_interest = w_asset_revolver_net_interest_rate_monthly.values
            
            _opening_bal = w_asset_debt_revolver_opening_balance.values
            _debt_withdrawal = w_asset_debt_revolver_debt_withdrawal.values
            _cap_interest = w_asset_debt_revolver_capitalization_of_interest.values
            _debt_repayment = w_asset_debt_revolver_debt_repayment.values
            _closing_bal = w_asset_debt_revolver_closing_balance.values
            
            _arr_fees = w_asset_debt_revolver_debt_arrangement_fees.values
            _commit_open_bal = w_asset_debt_revolver_debt_commitment_fees_opening_balance.values
            _commit_accrual = w_asset_debt_revolver_debt_commitment_fees_accrual.values
            _commit_payment = w_asset_debt_revolver_debt_commitment_fees_payment.values
            _commit_close_bal = w_asset_debt_revolver_debt_commitment_fees_closing_balance.values
            
            _cash_open_bal = w_asset_cash_schedule_opening_balance.values
            _cash_addition = w_asset_cash_schedule_addition.values
            _cash_utilization = w_asset_cash_schedule_cash_utilization.values
            _cash_transfer = w_asset_cash_schedule_transfer_to_project.values
            _cash_close_bal = w_asset_cash_schedule_closing_balance.values
            
            _add_req = w_additional_requirement.values
            
            # Pre-compute period data arrays (ensure datetime64 type for date comparisons)
            _period_starts_arr = pd.to_datetime(model_timeline_me['Period Start']).values
            _period_ends_arr = pd.to_datetime(model_timeline_me['Period End']).dt.normalize().values
            _months_arr = model_timeline_me['Month'].values
            _start_dates_arr = w_asset_revolver_start_date.values
            _end_dates_arr = w_asset_revolver_end_date.values
            _transfer_dates_arr = _cash_transfer_date.values
            
            # Pre-compute cumulative withdrawal tracking for non-reborrowing assets
            _cumulative_withdrawal = np.zeros(len(template_asset_timeline.index))
            
            n_rows = len(template_asset_timeline.index)
            n_cols = len(model_timeline_me)
            
            # Column-by-column iteration with row-vectorized operations
            for col in range(n_cols):
                period_start = _period_starts_arr[col]
                period_end = _period_ends_arr[col]
                month = _months_arr[col]
                
                # ========== DEBT REVOLVER CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Opening balance: previous closing (or 0 for first column)
                if col > 0:
                    _opening_bal[:, col] = _closing_bal[:, col - 1]
                # else: already initialized to 0.0
                
                # Cash schedule opening balance (needed for withdrawal calc)
                if col > 0:
                    _cash_open_bal[:, col] = _cash_close_bal[:, col - 1]
                
                # Debt withdrawal calculation (vectorized)
                _cf_plus_cash = _pre_fin_cf[:, col] + _cash_open_bal[:, col]
                _shortfall = -np.minimum(_cf_plus_cash, 0.0)
                
                # Calculate available limit based on reborrowing toggle
                # For reborrowing=Yes: limit - opening_balance
                # For reborrowing=No: limit - cumulative_withdrawal
                _available_limit = np.where(
                    _reborrowing_yes_mask,
                    _revolver_limit - _opening_bal[:, col],
                    _revolver_limit - _cumulative_withdrawal
                )
                _available_limit = np.maximum(_available_limit, 0.0)
                
                # Withdrawal = min(shortfall, available_limit) * withdrawal_flag
                _debt_withdrawal[:, col] = np.minimum(_shortfall, _available_limit) * _withdrawal_flag[:, col]
                
                # Update cumulative withdrawal for non-reborrowing assets
                _cumulative_withdrawal += _debt_withdrawal[:, col]
                
                # Arrangement fees flag (1 if period_start == revolver_start_date)
                _is_start_period = (period_start == _start_dates_arr)
                
                # Calculate arrangement fees FIRST (needed for capitalization)
                _arr_fees[:, col] = np.where(
                    _is_start_period & _arrangement_fees_not_in_revolver,
                    -_arrangement_fees_percent * _revolver_limit,
                    0.0
                )
                
                # Capitalization of interest (vectorized)
                _base_interest = _opening_bal[:, col] * _net_interest[:, col]
                _arr_fee_adj = np.where(_arrangement_fees_in_revolver, -_arr_fees[:, col], 0.0)
                _cap_arr_fee = np.where(
                    _is_start_period & _arrangement_fees_in_revolver,
                    _revolver_limit * _arrangement_fees_percent,
                    0.0
                )

                _cap_interest[:, col] = _base_interest - _arr_fee_adj + _cap_arr_fee
                
                # Temp value for repayment calculation
                _temp_val = _opening_bal[:, col] + _debt_withdrawal[:, col] + _cap_interest[:, col]
                
                # Debt repayment (vectorized with conditional logic)
                _is_end_period = (period_end == _end_dates_arr)
                _cf_positive = np.maximum(_pre_fin_cf[:, col], 0.0)
                
                # Case 1: End period - repay everything
                # Case 2: Over limit after positive CF - repay excess above limit
                # Case 3: Normal - repay min of positive CF and temp_val
                _excess_over_limit = _temp_val - _cf_positive >= _revolver_limit
                _repay_excess = _temp_val - _revolver_limit
                _repay_normal = np.maximum(0.0, np.minimum(_pre_fin_cf[:, col], _temp_val))
                
                _debt_repayment[:, col] = -np.where(
                    _is_end_period,
                    _temp_val,
                    np.where(_excess_over_limit, _repay_excess, _repay_normal)
                )
                
                # Closing balance
                _closing_bal[:, col] = _opening_bal[:, col] + _debt_withdrawal[:, col] + _cap_interest[:, col] + _debt_repayment[:, col]
                
                # ========== COMMITMENT FEES CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Opening balance
                if col > 0:
                    _commit_open_bal[:, col] = _commit_close_bal[:, col - 1]
                
                # Accrual = monthly_percent * (limit - opening - withdrawal) * withdrawal_flag
                _unused_limit = _revolver_limit - _opening_bal[:, col] - _debt_withdrawal[:, col]
                _commit_accrual[:, col] = _commitment_fees_monthly * _unused_limit * _withdrawal_flag[:, col]
                
                # Payment: if month matches frequency schedule, sum accruals
                _payment_due = (month % _commitment_freq_flag == _commitment_freq_mod)
                if col >= 0:
                    # Sum accruals over the frequency period
                    for row in range(n_rows):
                        if _payment_due[row]:
                            freq = int(_commitment_freq_flag[row])
                            start_col = max(0, col - freq + 1)
                            _commit_payment[row, col] = -_commit_accrual[row, start_col:col+1].sum()
                
                # Closing balance
                _commit_close_bal[:, col] = _commit_open_bal[:, col] + _commit_accrual[:, col] + _commit_payment[:, col]
                
                # ========== CASH SCHEDULE CALCULATIONS (ALL ROWS AT ONCE) ==========
                
                # Cash addition: max(0, CF + withdrawal + repayment) * reserve_flag * (prev_period < transfer_date)
                _net_cf = _pre_fin_cf[:, col] + _debt_withdrawal[:, col] + _debt_repayment[:, col]
                _positive_cf = np.maximum(0.0, _net_cf)
                
                if col > 0:
                    prev_period_end = _period_ends_arr[col - 1]
                    _before_transfer = (prev_period_end < _transfer_dates_arr)
                else:
                    _before_transfer = np.ones(n_rows, dtype=bool)
                
                _cash_addition[:, col] = _positive_cf * _cash_reserve_flag * _before_transfer.astype(float)
                
                # Cash utilization: max(min(0, CF), -opening_balance)
                _cash_utilization[:, col] = np.maximum(
                    np.minimum(0.0, _pre_fin_cf[:, col]),
                    -_cash_open_bal[:, col]
                )

                # Transfer to project: -(opening + addition + utilization) * (period_start >= transfer_date)
                _after_transfer = (period_start >= _transfer_dates_arr)
                _total_cash = _cash_open_bal[:, col] + _cash_addition[:, col] + _cash_utilization[:, col]

                _cash_transfer[:, col] = -_total_cash * _after_transfer.astype(float)
                
                # Closing balance
                _cash_close_bal[:, col] = _cash_open_bal[:, col] + _cash_addition[:, col] - _cash_utilization[:, col] + _cash_transfer[:, col]
                
                # Additional requirement
                _add_req[:, col] = _pre_fin_cf[:, col] + _debt_withdrawal[:, col] + _debt_repayment[:, col] - _cash_addition[:, col] - _cash_transfer[:, col] - _cash_utilization[:, col] + _arr_fees[:, col] + _commit_payment[:, col]
            
            # ============================================================================================
            # ASSIGN COMPUTED VALUES BACK TO DATAFRAMES
            # ============================================================================================
            # Note: Since we extracted .values (numpy views) and modified in-place, the DataFrames
            # are already updated. However, for clarity and safety, we explicitly assign:
            
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
            w_asset_debt_revolver_debt_commitment_fees_opening_balance = pd.DataFrame(
                _commit_open_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_debt_revolver_debt_commitment_fees_accrual = pd.DataFrame(
                _commit_accrual, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_debt_revolver_debt_commitment_fees_payment = pd.DataFrame(
                _commit_payment, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_debt_revolver_debt_commitment_fees_closing_balance = pd.DataFrame(
                _commit_close_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            
            w_asset_cash_schedule_opening_balance = pd.DataFrame(
                _cash_open_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_cash_schedule_addition = pd.DataFrame(
                _cash_addition, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_cash_schedule_cash_utilization = pd.DataFrame(
                _cash_utilization, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_cash_schedule_transfer_to_project = pd.DataFrame(
                -_cash_transfer, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            w_asset_cash_schedule_closing_balance = pd.DataFrame(
                _cash_close_bal, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            
            w_additional_requirement = pd.DataFrame(
                _add_req, index=template_asset_timeline.index, columns=template_asset_timeline.columns
            )
            
            # Preserve backward compatibility for w_asset_revolver_limit (used later)
            w_asset_revolver_limit = pd.DataFrame(
                _revolver_limit, index=template_asset_timeline.index, columns=['Revolver Limit']
            )

            # ============================================================================================
            # EXPORT ASSET LEVEL FINANCING DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('asset_level_financing', False):
                _asset_financing_exports = {
                    # Pre-Financing Cashflows
                    'Asset Timeline': template_asset_timeline,
                    'Inflows': pd.DataFrame(_inflows_sum, index=template_asset_timeline.index, columns=template_asset_timeline.columns),
                    'Outflows': pd.DataFrame(_outflows_sum, index=template_asset_timeline.index, columns=template_asset_timeline.columns),
                    'Pre-Financing CF': w_pre_financing_cashflows_jv_excluded,
                    # Revolver Parameters
                    'Revolver Start Date': pd.DataFrame({'Revolver Start Date': w_asset_revolver_start_date}),
                    'Revolver Duration': pd.DataFrame({'Revolver Duration (Years)': w_asset_revolver_duration}),
                    'Revolver End Date': pd.DataFrame({'Revolver End Date': w_asset_revolver_end_date}),
                    'Withdrawal Flag': w_asset_revolver_withdrawal_flag,
                    'Revolver Limit': pd.DataFrame({'Revolver Limit': _revolver_limit}),
                    'Reborrowing Toggle': pd.DataFrame({'Reborrowing Toggle': _reborrowing_toggle}),
                    # Interest Rate Components
                    'Base Rate Profile': pd.DataFrame({'Base Rate Profile': w_asset_revolver_base_rate_profile}),
                    'Base Rate Percent': w_asset_revolver_base_rate_percent,
                    'Credit Spread': w_asset_revolver_credit_spread_percent,
                    'Net Interest Rate': w_asset_revolver_net_interest_rate_monthly,
                    # Debt Revolver Schedule
                    'Revolver Opening Bal': w_asset_debt_revolver_opening_balance,
                    'Revolver Withdrawal': w_asset_debt_revolver_debt_withdrawal,
                    'Revolver Cap Interest': w_asset_debt_revolver_capitalization_of_interest,
                    'Revolver Repayment': w_asset_debt_revolver_debt_repayment,
                    'Revolver Closing Bal': w_asset_debt_revolver_closing_balance,
                    # Debt Fees
                    'Arrangement Fees': w_asset_debt_revolver_debt_arrangement_fees,
                    'Commit Fees Open': w_asset_debt_revolver_debt_commitment_fees_opening_balance,
                    'Commit Fees Accrual': w_asset_debt_revolver_debt_commitment_fees_accrual,
                    'Commit Fees Payment': w_asset_debt_revolver_debt_commitment_fees_payment,
                    'Commit Fees Close': w_asset_debt_revolver_debt_commitment_fees_closing_balance,
                    # Cash Schedule
                    'Cash Open Balance': w_asset_cash_schedule_opening_balance,
                    'Cash Addition': w_asset_cash_schedule_addition,
                    'Cash Utilization': w_asset_cash_schedule_cash_utilization,
                    'Cash Transfer': w_asset_cash_schedule_transfer_to_project,
                    'Cash Close Balance': w_asset_cash_schedule_closing_balance,
                    # Additional
                    'Additional Requirement': w_additional_requirement,
                }
                _export_to_excel(_asset_financing_exports, 'export_asset_level_financing', 'Asset Level Financing')

            # ========================================================================
            # SUB-MODULE 3.13.2: PROJECT LEVEL FINANCING
            # ========================================================================
            # This sub-module handles project-level financing calculations:
            #   - Project Level Term Loan: Drawdown, Principal Repayment, Balloon Payment
            #   - Project Level Debt Revolver: Drawdown, Repayment, Commitment Fees
            #   - Project Level Interest Calculations
            #   - Equity Injection: Land in Kind, Equity Infusion
            #   - Project to Asset Fund Transfers
            # ========================================================================

            _record_timing("Asset Level Financing")

            # ========================================================================
            # PROJECT LEVEL FINANCING - PRE-COMPUTE PARAMETERS (VECTORIZED)
            # ========================================================================
            
            _n_periods = len(model_timeline_me)
            _period_starts_arr = pd.to_datetime(model_timeline_me['Period Start']).values
            _period_ends_arr = pd.to_datetime(model_timeline_me['Period End']).dt.normalize().values
            _period_months_arr = model_timeline_me['Month'].values
            
            # ========================================================================
            # PROJECT TERM LOAN - FLAGS AND PARAMETERS (VECTORIZED)
            # ========================================================================
            
            _term_loan_drawdown_date = pd.to_datetime(Global.FinancingAssumptions.project_term_loan_debt_drawdown_date)
            _term_loan_grace_period = Global.FinancingAssumptions.project_term_loan_grace_period
            _term_loan_grace_end_date = _term_loan_drawdown_date + pd.DateOffset(months=_term_loan_grace_period) - pd.Timedelta(days=1)
            _term_loan_repay_start_date = _term_loan_grace_end_date + pd.DateOffset(days=1)
            _term_loan_tenure_months = Global.FinancingAssumptions.project_term_loan_loan_term * 12
            _term_loan_tenure_excl_grace = _term_loan_tenure_months - _term_loan_grace_period
            _term_loan_repay_end_date = (_term_loan_repay_start_date + pd.DateOffset(months=_term_loan_tenure_excl_grace) - pd.Timedelta(days=1)).normalize()
            
            _repay_freq = Global.FinancingAssumptions.project_term_loan_repayment_frequency
            _repay_freq_mapping = {"Monthly": 1, "Quarterly": 3, "Annual": 12}
            _repay_freq_divisor = _repay_freq_mapping.get(_repay_freq, 1)
            _repay_freq_mod = (_term_loan_drawdown_date.month % _repay_freq_divisor) - (0 if _repay_freq_divisor == 1 else 1)
            
            # Vectorized flag calculations
            _term_loan_drawdown_flag = (_period_starts_arr == _term_loan_drawdown_date).astype(float)
            _term_loan_repay_flag = ((_period_starts_arr < _term_loan_repay_end_date) & (_period_ends_arr > _term_loan_repay_start_date)).astype(float)
            _balloon_flag = (_period_ends_arr == _term_loan_repay_end_date).astype(float)
            _repay_freq_flag = ((_period_months_arr % _repay_freq_divisor) == _repay_freq_mod).astype(float)
            _principal_amort_flag = _term_loan_repay_flag * _repay_freq_flag
            
            _infra_end_date_max = max(w_infrastructure_end_date)
            _infra_end_date_max_norm = pd.to_datetime(_infra_end_date_max).normalize()
            _interest_cap_flag = _repay_freq_flag * (1 - _term_loan_repay_flag)
            _interest_exp_flag = _repay_freq_flag * _term_loan_repay_flag

            # ========================================================================
            # PROJECT TERM LOAN - INTEREST RATE CALCULATION (VECTORIZED)
            # ========================================================================
            
            def _get_interest_rate_profile(profile_name, apply_flag=None):
                """Helper to get interest rate profile as monthly rates."""
                rate_arr = np.zeros(_n_periods)
                if profile_name and pd.notna(profile_name) and profile_name != '' and profile_name in _interest_profile_name_to_idx:
                    profile_idx = _interest_profile_name_to_idx[profile_name]
                    annual_rates = np.array(_interest_profile_data[profile_idx])[_period_year_indices]
                    rate_arr = annual_rates
                    if apply_flag is not None:
                        rate_arr = rate_arr * apply_flag
                return rate_arr
            
            _term_loan_base_rate = _get_interest_rate_profile(Global.FinancingAssumptions.project_term_loan_base_rate_profile)
            _term_loan_credit_spread = Global.FinancingAssumptions.project_term_loan_credit_spread
            
            _term_loan_net_rate_annual = _term_loan_base_rate + _term_loan_credit_spread

            _term_loan_net_rate_monthly = ((1 + _term_loan_net_rate_annual) ** (_repay_freq_divisor/12)) - 1

            # ========================================================================
            # PROJECT TERM LOAN - AMOUNT CALCULATIONS (SCALAR)
            # ========================================================================
            
            _debt_calc_approach = Global.FinancingAssumptions.project_term_loan_term_loan_amount_calculation_approach
            if _debt_calc_approach == "% of Development Cost":
                _term_loan_amount = Global.FinancingAssumptions.project_term_loan_percent_of * (
                    o_total_infrastructure_cost_payment.sum().sum() + 
                    o_total_soft_cost_payment.sum().sum()
                )
            elif _debt_calc_approach == "Ad-Hoc Amount":
                _term_loan_amount = Global.FinancingAssumptions.project_term_loan_ad_hoc_amount
            else:
                _term_loan_amount = 0.0

            _term_loan_arr_fees_amt = _term_loan_amount * Global.FinancingAssumptions.project_term_loan_debt_arrangement_fees
            _term_loan_val_fees_amt = _term_loan_amount * Global.FinancingAssumptions.project_term_loan_valuation_fees
            _term_loan_other_fees_amt = _term_loan_amount * Global.FinancingAssumptions.project_term_loan_other_debt_fees
            _term_loan_balloon_amt = _term_loan_amount * Global.FinancingAssumptions.project_term_loan_ballon_payment_percent
            _term_loan_arr_fees_in_revolver = int(Global.FinancingAssumptions.project_term_loan_arrangement_fees_inclusion == "Yes")
            _n_payments = _term_loan_tenure_excl_grace / _repay_freq_divisor

            # ========================================================================
            # PROJECT DEBT REVOLVER - FLAGS AND PARAMETERS (VECTORIZED)
            # ========================================================================
            
            _proj_revolver_start = pd.to_datetime(Global.FinancingAssumptions.project_debt_revolver_revolver_facility_start_date)
            _proj_revolver_duration = Global.FinancingAssumptions.project_debt_revolver_revolver_facility_duration
            _proj_revolver_end = _proj_revolver_start + pd.DateOffset(years=_proj_revolver_duration) - pd.Timedelta(days=1)
            _proj_revolver_limit = Global.FinancingAssumptions.project_debt_revolver_revolver_limit
            _proj_revolver_autodraw = Global.FinancingAssumptions.project_debt_revolver_autodraw_threshold
            _proj_reborrow_toggle = int(Global.FinancingAssumptions.project_debt_revolver_reborrowing_toggle == "Yes")
            
            # Vectorized revolver flags
            _proj_revolver_flag = ((_period_ends_arr > _proj_revolver_start) & (_period_starts_arr < _proj_revolver_end)).astype(float)
            _proj_revolver_start_flag = (_period_starts_arr == _proj_revolver_start).astype(float)
            _proj_revolver_end_flag = (_period_ends_arr == _proj_revolver_end).astype(float)

            # ========================================================================
            # PROJECT DEBT REVOLVER - INTEREST RATE CALCULATION (VECTORIZED)
            # ========================================================================
            
            _proj_revolver_base_rate = _get_interest_rate_profile(Global.FinancingAssumptions.project_debt_revolver_base_rate_profile)
            _proj_revolver_credit_spread = Global.FinancingAssumptions.project_debt_revolver_credit_spread
            _proj_revolver_net_rate_annual = _proj_revolver_base_rate + _proj_revolver_credit_spread

            _proj_revolver_net_rate_monthly = ((1 + _proj_revolver_net_rate_annual) ** (1/12)) - 1

            # ========================================================================
            # PROJECT DEBT REVOLVER - DEBT FEES PARAMETERS
            # ========================================================================
            
            _proj_revolver_arr_fees_pct = Global.FinancingAssumptions.project_debt_revolver_debt_arrangement_fees
            _proj_revolver_arr_fees_inclusion = Global.FinancingAssumptions.project_debt_revolver_arrangement_fees_inclusion
            _proj_revolver_commit_fees_pct = Global.FinancingAssumptions.project_debt_revolver_commitment_fees
            _proj_revolver_commit_fees_monthly = _proj_revolver_commit_fees_pct / 12
            _proj_revolver_commit_freq = Global.FinancingAssumptions.project_debt_revolver_commitment_fees_payment_frequency
            _proj_revolver_freq_mapping = {"Annual": 12, "Quarterly": 3, "Monthly": 1}
            _proj_revolver_commit_freq_flag = _proj_revolver_freq_mapping.get(_proj_revolver_commit_freq, 1)
            _proj_revolver_commit_freq_mod = (_proj_revolver_start.month % _proj_revolver_commit_freq_flag) - 1

            # ========================================================================
            # PRE-COMPUTE ELIGIBILITY MASKS AND FILTERED SUMS
            # ========================================================================
            
            def _filtered_sum(df):
                df = fn_replace_nan(df, 0.0)
                return (df.values * 1.0).sum(axis=0)

            def _inverse_filtered_sum(df):
                df = fn_replace_nan(df, 0.0)
                return (df.values * 1.0).sum(axis=0)
            
            # Pre-compute filtered sums for project cash schedule
            _project_prefinancing_cf = (w_pre_financing_cashflows_jv_excluded.values).sum(axis=0)
            _project_land_cost = o_land_acquisition_cost_in_kind.sum(axis=0).values * -1
            _project_land_in_kind = o_land_acquisition_cost_in_kind.sum(axis=0).values
            _project_asset_drawdown = _filtered_sum(w_asset_debt_revolver_debt_withdrawal)
            _project_asset_repayment = _filtered_sum(w_asset_debt_revolver_debt_repayment)
            _project_asset_arr_fees = _filtered_sum(w_asset_debt_revolver_debt_arrangement_fees) * -1
            _project_asset_commit_fees = _filtered_sum(w_asset_debt_revolver_debt_commitment_fees_payment) * -1
            _project_funds_from_assets = _filtered_sum(w_asset_cash_schedule_transfer_to_project)
            _project_funds_to_assets = _inverse_filtered_sum(w_additional_requirement) * -1
            _net_req_post_asset = w_additional_requirement.sum(axis=0).values

            # ========================================================================
            # INITIALIZE OUTPUT ARRAYS (NUMPY FOR PERFORMANCE)
            # ========================================================================
            
            # Term Loan arrays
            _tl_open = np.zeros(_n_periods)
            _tl_drawdown = np.zeros(_n_periods)
            _tl_cap_int_arr = np.zeros(_n_periods)
            _tl_principal = np.zeros(_n_periods)
            _tl_balloon = np.zeros(_n_periods)
            _tl_int_exp = np.zeros(_n_periods)
            _tl_close = np.zeros(_n_periods)
            _tl_arr_fees = np.zeros(_n_periods)
            _tl_val_fees = np.zeros(_n_periods)
            _tl_other_fees = np.zeros(_n_periods)
            
            # Project Revolver arrays
            _pr_open = np.zeros(_n_periods)
            _pr_drawdown = np.zeros(_n_periods)
            _pr_cap_int = np.zeros(_n_periods)
            _pr_repay = np.zeros(_n_periods)
            _pr_close = np.zeros(_n_periods)
            _pr_arr_fees = np.zeros(_n_periods)
            _pr_commit_open = np.zeros(_n_periods)
            _pr_commit_accrual = np.zeros(_n_periods)
            _pr_commit_pay = np.zeros(_n_periods)
            _pr_commit_close = np.zeros(_n_periods)
            
            # Net requirement/availability arrays
            _net_req_post_tl = np.zeros(_n_periods)
            _net_avail_post_tl = np.zeros(_n_periods)
            _net_req_pre_equity = np.zeros(_n_periods)
            _net_avail_pre_equity = np.zeros(_n_periods)
            
            # Cash schedule arrays
            _cash_open = np.zeros(_n_periods)
            _cash_net = np.zeros(_n_periods)
            _cash_close = np.zeros(_n_periods)
            _equity_infusion = np.zeros(_n_periods)
            _land_in_kind = np.zeros(_n_periods)

            # ========================================================================
            # VECTORIZED CALCULATIONS (NON-SEQUENTIAL)
            # ========================================================================
            
            # Term Loan - Drawdown, Balloon, Fees (fully vectorized)
            _tl_drawdown = _term_loan_amount * _term_loan_drawdown_flag
            _tl_balloon = -_term_loan_balloon_amt * _balloon_flag
            _tl_arr_fees = _term_loan_arr_fees_amt * _term_loan_drawdown_flag * (1 - _term_loan_arr_fees_in_revolver)
            _tl_val_fees = _term_loan_val_fees_amt * _term_loan_drawdown_flag
            _tl_other_fees = _term_loan_other_fees_amt * _term_loan_drawdown_flag
            
            # Project Revolver - Arrangement Fees (vectorized)
            _pr_arr_fees = _proj_revolver_limit * _proj_revolver_arr_fees_pct * _proj_revolver_start_flag * int(_proj_revolver_arr_fees_inclusion == "No")
            
            # Land in Kind (non-cash financing disclosure)
            _land_in_kind = _project_land_in_kind

            # ========================================================================
            # SEQUENTIAL CALCULATIONS (COLUMN ITERATION - OPTIMIZED)
            # ========================================================================
            
            _cumulative_amort_count = 0
            _cumulative_pr_drawdown = 0.0
            
            for col in range(_n_periods):
                # Previous period values
                _prev_tl_close = 0.0 if col == 0 else _tl_close[col - 1]
                _prev_pr_close = 0.0 if col == 0 else _pr_close[col - 1]
                _prev_cash_close = 0.0 if col == 0 else _cash_close[col - 1]
                _prev_commit_close = 0.0 if col == 0 else _pr_commit_close[col - 1]
                
                # Term Loan - Opening Balance
                _tl_open[col] = _prev_tl_close
                
                # Term Loan - Interest Capitalization + Arrangement Fees (in revolver)
                _tl_cap_int_arr[col] = (
                    ((_tl_open[col] + _tl_drawdown[col]) * _term_loan_net_rate_monthly[col] * _interest_cap_flag[col]) +
                    (_term_loan_arr_fees_amt * _term_loan_drawdown_flag[col] * _term_loan_arr_fees_in_revolver)
                )
            
                # Term Loan - Principal Repayment (PPMT calculation)
                _nper_remaining = _n_payments - _cumulative_amort_count

                _pv = _tl_open[col] + _tl_drawdown[col] + _tl_cap_int_arr[col] + _tl_balloon[:].sum()
                try:
                    _ppmt_val = _ppmt(_term_loan_net_rate_monthly[col], 1, _nper_remaining, _pv, fv=0) if _nper_remaining > 0 and _pv != 0 else 0.0
                except Exception:
                    _ppmt_val = 0.0
                _tl_principal[col] = _ppmt_val * _term_loan_repay_flag[col] * _repay_freq_flag[col]
            
                # Update cumulative amortization count
                if _principal_amort_flag[col] == 1:
                    _cumulative_amort_count += 1
                
                # Term Loan - Interest Expensed
                _tl_int_exp[col] = -1 * (_tl_open[col] + _tl_drawdown[col]) * _term_loan_net_rate_monthly[col] * _interest_exp_flag[col]
                
                # Term Loan - Closing Balance
                _tl_close[col] = _tl_open[col] + _tl_drawdown[col] + _tl_cap_int_arr[col] + _tl_principal[col] + _tl_balloon[col]
                
                # Net Requirement Post Asset Revolver and Term Loan
                # Original: w_net_requirement_post_asset_revolver + drawdown + principal + balloon + interest_expensed + arr_fees + val_fees + other_fees - autodraw + prev_cash_close
                # Note: Fees are added (positive values in the original), interest_expensed is added (not negated)
                _net_req_calc = (
                    _net_req_post_asset[col] +
                    _tl_drawdown[col] + _tl_principal[col] + _tl_balloon[col] +
                    _tl_int_exp[col] +
                    _tl_arr_fees[col] + _tl_val_fees[col] + _tl_other_fees[col] -
                    _proj_revolver_autodraw + _prev_cash_close
                )
                _net_req_post_tl[col] = min(0.0, _net_req_calc)
                _net_avail_post_tl[col] = max(0.0, _net_req_calc)
                
                # Project Revolver - Opening Balance
                _pr_open[col] = _prev_pr_close
                
                # Project Revolver - Drawdown
                # For non-reborrowing: use cumulative drawdown (sum of all previous drawdowns)
                if _proj_reborrow_toggle:
                    _available_limit = _proj_revolver_limit - _pr_open[col]
                else:
                    _available_limit = _proj_revolver_limit - _cumulative_pr_drawdown
                _pr_drawdown[col] = min(-_net_req_post_tl[col], max(0.0, _available_limit)) * _proj_revolver_flag[col]
                _cumulative_pr_drawdown += _pr_drawdown[col]
                
                # Project Revolver - Capitalization of Interest
                _pr_cap_int[col] = (_pr_open[col] + _pr_drawdown[col]) * _proj_revolver_net_rate_monthly[col]
                
                # Project Revolver - Repayment
                _pr_total_before_repay = _pr_open[col] + _pr_cap_int[col] + _pr_drawdown[col]
                if _proj_revolver_end_flag[col] == 1:
                    _pr_repay[col] = _pr_total_before_repay
                else:
                    _pr_repay[col] = max(0.0, min(_pr_total_before_repay, max(0.0, _pr_total_before_repay - _proj_revolver_limit) + _net_avail_post_tl[col]))
                
                _pr_repay[col] = -1 * _pr_repay[col]

                # Project Revolver - Closing Balance
                _pr_close[col] = _pr_open[col] + _pr_drawdown[col] + _pr_cap_int[col] + _pr_repay[col]
                
                # Project Revolver - Commitment Fees
                _pr_commit_open[col] = _prev_commit_close
                _pr_commit_accrual[col] = (_proj_revolver_limit - _pr_close[col]) * _proj_revolver_commit_fees_monthly * _proj_revolver_flag[col]
                _is_commit_pay_period = ((_period_months_arr[col] % _proj_revolver_commit_freq_flag) == _proj_revolver_commit_freq_mod) if _proj_revolver_commit_freq_flag > 1 else True
                _pr_commit_pay[col] = (_pr_commit_open[col] + _pr_commit_accrual[col]) * int(_is_commit_pay_period) * _proj_revolver_flag[col]
                _pr_commit_close[col] = _pr_commit_open[col] + _pr_commit_accrual[col] - _pr_commit_pay[col]
                
                # Net Requirement/Availability Pre-Equity Infusion
                # Original: net_req_post_tl + pr_drawdown + pr_repay - pr_arr_fees - pr_commit_pay
                _net_calc_pre_equity = (
                    _net_req_calc +
                    _pr_drawdown[col] + _pr_repay[col] -
                    _pr_arr_fees[col] - _pr_commit_pay[col]
                )

                _net_req_pre_equity[col] = min(0.0, _net_calc_pre_equity)
                _net_avail_pre_equity[col] = max(0.0, _net_calc_pre_equity)
                
                # Equity Infusion
                _equity_infusion[col] = -_net_req_pre_equity[col]
                
                # Cash Schedule
                _cash_open[col] = _prev_cash_close
                _cash_net[col] = (
                    _project_prefinancing_cf[col] + _project_land_cost[col] +
                    _project_asset_drawdown[col] + _project_asset_repayment[col] -
                    _project_asset_arr_fees[col] - _project_asset_commit_fees[col] +
                    _tl_drawdown[col] + _tl_principal[col] + _tl_balloon[col] + _tl_int_exp[col] -
                    _tl_arr_fees[col] - _tl_val_fees[col] - _tl_other_fees[col] +
                    _pr_drawdown[col] + _pr_repay[col] -
                    _pr_arr_fees[col] - _pr_commit_pay[col] +
                    _land_in_kind[col] + _equity_infusion[col]
                )
                _cash_close[col] = _cash_open[col] + _cash_net[col]

            # ========================================================================
            # CONVERT ARRAYS TO DATAFRAMES FOR OUTPUT
            # ========================================================================
            
            _single_row_idx = [0]
            _cols = template_asset_timeline.columns
            
            # Term Loan DataFrames
            w_term_loan_opening_balance = pd.DataFrame([_tl_open], index=_single_row_idx, columns=_cols)
            w_term_loan_drawdown = pd.DataFrame([_tl_drawdown], index=_single_row_idx, columns=_cols)
            w_term_loan_interest_capitalization_arrangement_fees = pd.DataFrame([_tl_cap_int_arr], index=_single_row_idx, columns=_cols)
            w_term_loan_principal_repayment = pd.DataFrame([_tl_principal], index=_single_row_idx, columns=_cols)
            w_term_loan_balloon_payment = pd.DataFrame([_tl_balloon], index=_single_row_idx, columns=_cols)
            w_term_loan_interest_expensed = pd.DataFrame([_tl_int_exp], index=_single_row_idx, columns=_cols)
            w_term_loan_closing_balance = pd.DataFrame([_tl_close], index=_single_row_idx, columns=_cols)
            w_term_loan_arrangement_fees = pd.DataFrame([_tl_arr_fees], index=_single_row_idx, columns=_cols)
            w_term_loan_valuation_fees = pd.DataFrame([_tl_val_fees], index=_single_row_idx, columns=_cols)
            w_term_loan_other_debt_fees = pd.DataFrame([_tl_other_fees], index=_single_row_idx, columns=_cols)
            
            # Project Revolver DataFrames
            w_project_debt_revolver_opening_balance = pd.DataFrame([_pr_open], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_debt_withdrawal = pd.DataFrame([_pr_drawdown], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_capitalization_of_interest_and_arrangement_fees = pd.DataFrame([_pr_cap_int], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_debt_repayment = pd.DataFrame([_pr_repay], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_closing_balance = pd.DataFrame([_pr_close], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_arrangement_fees = pd.DataFrame([_pr_arr_fees], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_commitment_fees_opening_balance = pd.DataFrame([_pr_commit_open], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_commitment_fees_accrual = pd.DataFrame([_pr_commit_accrual], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_commitment_fees_payment = pd.DataFrame([_pr_commit_pay], index=_single_row_idx, columns=_cols)
            w_project_debt_revolver_commitment_fees_closing_balance = pd.DataFrame([_pr_commit_close], index=_single_row_idx, columns=_cols)
            
            # Net Requirement/Availability DataFrames
            w_net_requirement_post_asset_revolver_and_project_term_loan = pd.DataFrame([_net_req_post_tl], index=_single_row_idx, columns=_cols)
            w_net_availability_post_asset_revolver_and_project_term_loan = pd.DataFrame([_net_avail_post_tl], index=_single_row_idx, columns=_cols)
            w_net_requirement_pre_equity_infusion = pd.DataFrame([_net_req_pre_equity], index=_single_row_idx, columns=_cols)
            w_net_availability_pre_equity_infusion = pd.DataFrame([_net_avail_pre_equity], index=_single_row_idx, columns=_cols)
            
            # Cash Schedule DataFrames
            w_project_cash_schedule_opening_balance = pd.DataFrame([_cash_open], index=_single_row_idx, columns=_cols)
            w_project_cash_schedule_net_cash = pd.DataFrame([_cash_net], index=_single_row_idx, columns=_cols)
            w_project_cash_schedule_closing_balance = pd.DataFrame([_cash_close], index=_single_row_idx, columns=_cols)
            
            # Equity DataFrames
            w_equity_infusion = pd.DataFrame([_equity_infusion], index=_single_row_idx, columns=_cols)
            w_land_in_kind = pd.DataFrame([_land_in_kind], index=_single_row_idx, columns=_cols)

            # ============================================================================================
            # EXPORT PROJECT LEVEL FINANCING DATAFRAMES TO EXCEL
            # ============================================================================================

            if _EXPORT_FLAGS.get('project_level_financing', False):
                _project_financing_exports = {
                    # Supporting Workings
                    'Proj Pre-Fin CF': pd.DataFrame([_project_prefinancing_cf], index=_single_row_idx, columns=_cols),
                    'Proj Land Cost': pd.DataFrame([_project_land_cost], index=_single_row_idx, columns=_cols),
                    'Proj Land In Kind': pd.DataFrame([_project_land_in_kind], index=_single_row_idx, columns=_cols),
                    'Proj Asset Drawdown': pd.DataFrame([_project_asset_drawdown], index=_single_row_idx, columns=_cols),
                    'Proj Asset Repayment': pd.DataFrame([_project_asset_repayment], index=_single_row_idx, columns=_cols),
                    'Proj Asset Arr Fees': pd.DataFrame([_project_asset_arr_fees], index=_single_row_idx, columns=_cols),
                    'Proj Asset Commit Fees': pd.DataFrame([_project_asset_commit_fees], index=_single_row_idx, columns=_cols),
                    'Proj Funds From Assets': pd.DataFrame([_project_funds_from_assets], index=_single_row_idx, columns=_cols),
                    'Proj Funds To Assets': pd.DataFrame([_project_funds_to_assets], index=_single_row_idx, columns=_cols),
                    'Net Req Post Asset': pd.DataFrame([_net_req_post_asset], index=_single_row_idx, columns=_cols),
                    # Term Loan Schedule
                    'TL Opening Bal': w_term_loan_opening_balance,
                    'TL Drawdown': w_term_loan_drawdown,
                    'TL Cap Interest': w_term_loan_interest_capitalization_arrangement_fees,
                    'TL Principal Repay': w_term_loan_principal_repayment,
                    'TL Balloon Payment': w_term_loan_balloon_payment,
                    'TL Interest Expensed': w_term_loan_interest_expensed,
                    'TL Closing Bal': w_term_loan_closing_balance,
                    # Term Loan Fees
                    'TL Arrangement Fees': w_term_loan_arrangement_fees,
                    'TL Valuation Fees': w_term_loan_valuation_fees,
                    'TL Other Fees': w_term_loan_other_debt_fees,
                    # Project Revolver Schedule
                    'PR Opening Bal': w_project_debt_revolver_opening_balance,
                    'PR Drawdown': w_project_debt_revolver_debt_withdrawal,
                    'PR Cap Interest': w_project_debt_revolver_capitalization_of_interest_and_arrangement_fees,
                    'PR Repayment': w_project_debt_revolver_debt_repayment,
                    'PR Closing Bal': w_project_debt_revolver_closing_balance,
                    # Project Revolver Fees
                    'PR Arrangement Fees': w_project_debt_revolver_arrangement_fees,
                    'PR Commit Open': w_project_debt_revolver_commitment_fees_opening_balance,
                    'PR Commit Accrual': w_project_debt_revolver_commitment_fees_accrual,
                    'PR Commit Payment': w_project_debt_revolver_commitment_fees_payment,
                    'PR Commit Close': w_project_debt_revolver_commitment_fees_closing_balance,
                    # Net Requirement/Availability
                    'Net Req Post TL': w_net_requirement_post_asset_revolver_and_project_term_loan,
                    'Net Avail Post TL': w_net_availability_post_asset_revolver_and_project_term_loan,
                    'Net Req Pre Equity': w_net_requirement_pre_equity_infusion,
                    'Net Avail Pre Equity': w_net_availability_pre_equity_infusion,
                    # Cash Schedule
                    'Proj Cash Open': w_project_cash_schedule_opening_balance,
                    'Proj Cash Net': w_project_cash_schedule_net_cash,
                    'Proj Cash Close': w_project_cash_schedule_closing_balance,
                    # Equity
                    'Land in Kind': w_land_in_kind,
                    'Equity Infusion': w_equity_infusion,
                }
                _export_to_excel(_project_financing_exports, 'export_project_level_financing', 'Project Level Financing')

            # ========================================================================
            # SUB-MODULE 3.14: CASHFLOW STATEMENT GENERATION
            # ========================================================================
            # CASHFLOW DATAFRAMES INITIALIZATION
            # ========================================================================

            _record_timing("Project Level Financing")

            def _pos(x):
                return _filtered_sum(x)

            def _neg(x):
                return _filtered_sum(x) * -1

            def _init_cashflow_df(line_items, columns, header_rows=None):
                """Initialize a cashflow DataFrame with 0.0 for data rows and None for separator/header rows."""
                df = pd.DataFrame(index=line_items, columns=columns)
                empty_rows = {""}
                if header_rows:
                    empty_rows.update(header_rows)
                data_rows = [item for item in line_items if item.strip() != "" and item not in empty_rows]
                df.loc[data_rows] = 0.0
                df = df.where(~pd.isna(df), None)
                return df

            columns = model_timeline_me.index

            # Line item definitions
            operations_line_items = [
                "Land Sales", "On-plan Sales Collection", "Off-plan Sales Collection", "Escrow Setup Fees", "",
                "Land Lease", "Lease Collection", "Associated Operating Expenses", "",
                "Leasing & Disposal Costs", "Leasing Costs", "Sales Transaction Cost", "",
                "Other Income", "Other Income 1", "Other Income 2", "Government Subsidies", "",
                "Other Expense", "Other Expense 1", "Other Expense 2", "Other Expense 3", "",
                "Community Operations - Amanah", "Community Operations Expense - Amanah", "Community Operations Recovery - Amanah", "",
                "Community Operations - ROSHN", "Community Operations Expense - ROSHN", "Community Operations Recovery - ROSHN", "",
                "Corporate Overhead Expenses", "Salaries Expenses", "IT Services Expenses",
                "Office Rent and Utilities Expenses", "Professional Services Expenses",
                "Marketing Expenses", "Sales Cost Expenses", "Additional Expenses", "",
                "Net Cashflow from Operations"
            ]

            investment_line_items = [
                "Land Acquisition Cost Payment", "",
                "Land Acquisition Transaction Costs", "Legal Cost", "Agency Cost", "Technical Cost",
                "Valuation Cost", "Due Diligence Cost", "Real Estate Transaction Tax", "Municipal Fees", "",
                "Infrastructure Cost Payment", "Primary Infrastructure Cost", "Secondary Infrastructure Cost", "",
                "Soft Costs Payment", "Design Cost", "Permitting Cost", "Supervision Cost", "Project Management Cost", "",
                "Contingency Cost Payment", "",
                "Capitalized Corporate Overheads Expenses", "Capitalized Salaries Expenses",
                "Capitalized IT Services Expenses", "Capitalized Office Rent and Utilities Expenses",
                "Capitalized Professional Services Expenses", "Capitalized Marketing Expenses",
                "Capitalized Sales Cost Expenses", "Capitalized Additional Expenses", "",
                "Land Lease - Terminal Value", "", "Land Bank - Exit Value", "",
                "Net Cashflow from Investments"
            ]

            financing_line_items = [
                "Asset Level Debt Revolver", "Asset Revolver - Debt Drawdown", "Asset Revolver - Debt Repayment", "",
                "Asset Level Debt Revolver - Debt Fees", "Asset Revolver - Arrangement Fees", "Asset Revolver - Commitment Fees", "",
                "Project Level Term Loan", "Term Loan - Debt Drawdown", "Term Loan - Principal Repayment",
                "Term Loan - Balloon Payment", "Term Loan - Interest Payment", "",
                "Project Level Term Loan - Debt Fees", "Term Loan - Arrangement Fees",
                "Term Loan - Valuation Fees", "Term Loan - Other Debt Fees", "",
                "Project Level Debt Revolver", "Project Revolver - Debt Drawdown", "Project Revolver - Debt Repayment", "",
                "Project Level Debt Revolver - Debt Fees", "Project Revolver - Arrangement Fees", "Project Revolver - Commitment Fees", "",
                "Equity Injection - Project", "Equity Infusion", "",
                "Net Cashflow from Financing", "", "Land in Kind"
            ]

            # Initialize DataFrames
            cashflow_from_operations = _init_cashflow_df(operations_line_items, columns)
            cashflow_from_investments = _init_cashflow_df(investment_line_items, columns)
            cashflow_from_financing = _init_cashflow_df(financing_line_items, columns, header_rows={
                "Asset Level Debt Revolver", "Asset Level Debt Revolver - Debt Fees",
                "Project Level Term Loan", "Project Level Term Loan - Debt Fees",
                "Project Level Debt Revolver", "Project Level Debt Revolver - Debt Fees",
                "Equity Injection - Project"
            })

            # ============================================================================================
            # CASHFLOW FROM OPERATIONS
            # ============================================================================================

            _asset_id_output_flag = pd.Series(False, index=template_asset_timeline.index)


            landco_output_inclusion_flag = (
                pd.Series(Asset.ProjectDetails.landco_output_inclusion)
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
                _asset_id_output_flag.loc[landco_output_inclusion_flag] = True
            elif asset_id_dropdown in asset_unique_id.values:
                _asset_id_output_flag.loc[asset_unique_id == asset_id_dropdown] = True
            elif asset_name_dropdown == "Consolidated":
                _asset_id_output_flag.loc[:] = True
            elif asset_name_dropdown == "Synthetic":
                _asset_id_output_flag.loc[landco_output_inclusion_flag] = True
            elif asset_name_dropdown in asset_name.values:
                _asset_id_output_flag.loc[asset_name == asset_name_dropdown] = True
            else:
                _asset_id_output_flag.loc[:] = True

            # JV exclusion mask: zeros out JV-included assets, keeps non-JV assets
            _jv_exclusion_mask = (~_jv_asset_level_inclusion_flag).values[:, np.newaxis].astype(float)

            def _apply_asset_filter(df):
                """
                Applies _asset_id_output_flag and _jv_exclusion_mask to the input DataFrame or Series.
                Keeps values where flag is True and JV exclusion applies, sets others to 0.
                Preserves index and columns.
                """
                # Ensure df is a DataFrame
                if isinstance(df, pd.Series):
                    df = df.to_frame()
                # Broadcast flag to match DataFrame shape
                mask = _asset_id_output_flag.values[:, np.newaxis]
                df_values = df.to_numpy(copy=True)
                df_values = np.where(pd.isna(df_values), 0.0, df_values)
                
                # Replace NaN with 0 for safe multiplication
                filtered = pd.DataFrame(
                    np.where(mask, df_values, 0.0),
                    index=df.index,
                    columns=df.columns
                )
                # Apply JV exclusion mask to exclude JV assets
                # filtered = pd.DataFrame(
                #     filtered.values * _jv_exclusion_mask,
                #     index=filtered.index,
                #     columns=filtered.columns
                # )
                return filtered

            operations_map = {
                "On-plan Sales Collection": _pos(_apply_asset_filter(o_on_plan_sales_collection)),
                "Off-plan Sales Collection": _pos(_apply_asset_filter(o_cash_inflow_from_off_plan_sales)),
                "Escrow Setup Fees": _neg(_apply_asset_filter(o_escrow_setup_fees)),
                "Lease Collection": _pos(_apply_asset_filter(o_land_lease_revenue_including_grace_period)),
                "Associated Operating Expenses": _neg(_apply_asset_filter(o_land_lease_associated_operating_expenses)),
                "Leasing Costs": _neg(_apply_asset_filter(o_leasing_cost)),
                "Sales Transaction Cost": _neg(_apply_asset_filter(o_sales_transaction_cost)),
                "Other Income 1": _pos(_apply_asset_filter(o_other_income_1)),
                "Other Income 2": _pos(_apply_asset_filter(o_other_income_2)),
                "Government Subsidies": _pos(_apply_asset_filter(o_other_income_3)),
                "Other Expense 1": _neg(_apply_asset_filter(o_other_expense_1)),
                "Other Expense 2": _neg(_apply_asset_filter(o_other_expense_2)),
                "Other Expense 3": _neg(_apply_asset_filter(o_other_expense_3)),
                "Community Operations Expense - Amanah": _neg(_apply_asset_filter(o_community_operations_cost_payment_amanah)),
                "Community Operations Recovery - Amanah": _pos(_apply_asset_filter(o_community_operations_amanah_recovery)),
                "Community Operations Expense - ROSHN": _neg(_apply_asset_filter(o_community_operations_cost_payment_roshn)),
                "Community Operations Recovery - ROSHN": _pos(_apply_asset_filter(o_community_operations_roshn_recovery)),
                "Salaries Expenses": _neg(_apply_asset_filter(o_corporate_overheads_salaries_expensed)),
                "IT Services Expenses": _neg(_apply_asset_filter(o_corporate_overheads_it_services_expensed)),
                "Office Rent and Utilities Expenses": _neg(_apply_asset_filter(o_corporate_overheads_office_rent_and_utilities_expensed)),
                "Professional Services Expenses": _neg(_apply_asset_filter(o_corporate_overheads_professional_services_expensed)),
                "Marketing Expenses": _neg(_apply_asset_filter(o_corporate_overheads_marketing_expensed)),
                "Sales Cost Expenses": _neg(_apply_asset_filter(o_corporate_overheads_sales_cost_expensed)),
                "Additional Expenses": _neg(_apply_asset_filter(o_corporate_overheads_additional_expenses_expensed)),
            }

            for k, v in operations_map.items():
                cashflow_from_operations.loc[k, :] = v

            # Subtotals
            cashflow_from_operations.loc["Land Sales", :] = (
                operations_map["On-plan Sales Collection"] + operations_map["Off-plan Sales Collection"] + operations_map["Escrow Setup Fees"]
            )
            cashflow_from_operations.loc["Land Lease", :] = (
                operations_map["Lease Collection"] + operations_map["Associated Operating Expenses"]
            )
            cashflow_from_operations.loc["Leasing & Disposal Costs", :] = (
                operations_map["Leasing Costs"] + operations_map["Sales Transaction Cost"]
            )
            cashflow_from_operations.loc["Other Income", :] = (
                operations_map["Other Income 1"] + operations_map["Other Income 2"] + operations_map["Government Subsidies"]
            )
            cashflow_from_operations.loc["Other Expense", :] = (
                operations_map["Other Expense 1"] + operations_map["Other Expense 2"] + operations_map["Other Expense 3"]
            )
            cashflow_from_operations.loc["Community Operations - Amanah", :] = (
                operations_map["Community Operations Expense - Amanah"] + operations_map["Community Operations Recovery - Amanah"]
            )
            cashflow_from_operations.loc["Community Operations - ROSHN", :] = (
                operations_map["Community Operations Expense - ROSHN"] + operations_map["Community Operations Recovery - ROSHN"]
            )
            cashflow_from_operations.loc["Corporate Overhead Expenses", :] = sum(
                v for k, v in operations_map.items() if "Expenses" in k and "Community" not in k
            )

            # Net
            cashflow_from_operations.loc["Net Cashflow from Operations", :] = cashflow_from_operations.loc[[
                "Land Sales", "Land Lease", "Leasing & Disposal Costs", "Other Income", "Other Expense",
                "Community Operations - Amanah", "Community Operations - ROSHN", "Corporate Overhead Expenses"
            ]].sum()

            _record_timing("Cashflow from Operations assembly")

            # ============================================================================================
            # CASHFLOW FROM INVESTMENTS
            # ============================================================================================

            investments_map = {
                "Land Acquisition Cost Payment": _apply_asset_filter(o_land_acquisition_cost_cash_payment).sum(axis=0) * -1,
                "Legal Cost": _neg(_apply_asset_filter(o_acquisition_transaction_cost_legal)),
                "Agency Cost": _neg(_apply_asset_filter(o_acquisition_transaction_cost_agency)),
                "Technical Cost": _neg(_apply_asset_filter(o_acquisition_transaction_cost_technical)),
                "Valuation Cost": _neg(_apply_asset_filter(o_acquisition_transaction_cost_valuation)),
                "Due Diligence Cost": _neg(_apply_asset_filter(o_acquisition_transaction_cost_due_diligence)),
                "Real Estate Transaction Tax": _neg(_apply_asset_filter(o_acquisition_transaction_cost_real_estate_transaction_tax)),
                "Municipal Fees": _neg(_apply_asset_filter(o_acquisition_transaction_cost_municipal_fees)),
                "Primary Infrastructure Cost": _neg(_apply_asset_filter(o_primary_infrastructure_cost_payment)),
                "Secondary Infrastructure Cost": _neg(_apply_asset_filter(o_secondary_infrastructure_cost_payment)),
                "Design Cost": _neg(_apply_asset_filter(o_design_cost_payment)),
                "Permitting Cost": _neg(_apply_asset_filter(o_permitting_cost_payment)),
                "Supervision Cost": _neg(_apply_asset_filter(o_supervision_cost_payment)),
                "Project Management Cost": _neg(_apply_asset_filter(o_project_management_cost_payment)),
                "Contingency Cost Payment": _neg(_apply_asset_filter(o_contingency_cost_payment)),
                "Capitalized Salaries Expenses": _neg(_apply_asset_filter(o_corporate_overheads_salaries_capitalized)),
                "Capitalized IT Services Expenses": _neg(_apply_asset_filter(o_corporate_overheads_it_services_capitalized)),
                "Capitalized Office Rent and Utilities Expenses": _neg(_apply_asset_filter(o_corporate_overheads_office_rent_and_utilities_capitalized)),
                "Capitalized Professional Services Expenses": _neg(_apply_asset_filter(o_corporate_overheads_professional_services_capitalized)),
                "Capitalized Marketing Expenses": _neg(_apply_asset_filter(o_corporate_overheads_marketing_capitalized)),
                "Capitalized Sales Cost Expenses": _neg(_apply_asset_filter(o_corporate_overheads_sales_cost_capitalized)),
                "Capitalized Additional Expenses": _neg(_apply_asset_filter(o_corporate_overheads_additional_expenses_capitalized)),
                "Land Lease - Terminal Value": _pos(_apply_asset_filter(o_land_lease_exit_value)),
                "Land Bank - Exit Value": _pos(_apply_asset_filter(o_land_bank_exit_value)),
            }

            for k, v in investments_map.items():
                cashflow_from_investments.loc[k, :] = v

            # Subtotals
            cashflow_from_investments.loc["Land Acquisition Transaction Costs", :] = (
                investments_map["Legal Cost"] + investments_map["Agency Cost"] + investments_map["Technical Cost"] +
                investments_map["Valuation Cost"] + investments_map["Due Diligence Cost"] +
                investments_map["Real Estate Transaction Tax"] + investments_map["Municipal Fees"]
            )
            cashflow_from_investments.loc["Infrastructure Cost Payment", :] = (
                investments_map["Primary Infrastructure Cost"] + investments_map["Secondary Infrastructure Cost"]
            )
            cashflow_from_investments.loc["Soft Costs Payment", :] = (
                investments_map["Design Cost"] + investments_map["Permitting Cost"] +
                investments_map["Supervision Cost"] + investments_map["Project Management Cost"]
            )
            cashflow_from_investments.loc["Capitalized Corporate Overheads Expenses", :] = sum(
                v for k, v in investments_map.items() if k.startswith("Capitalized")
            )

            # Net
            cashflow_from_investments.loc["Net Cashflow from Investments", :] = cashflow_from_investments.loc[[
                "Land Acquisition Cost Payment", "Land Acquisition Transaction Costs",
                "Infrastructure Cost Payment", "Soft Costs Payment", "Contingency Cost Payment",
                "Capitalized Corporate Overheads Expenses", "Land Lease - Terminal Value", "Land Bank - Exit Value"
            ]].sum()

            _record_timing("Cashflow from Investments assembly")

            # ============================================================================================
            # CASHFLOW FROM FINANCING
            # ============================================================================================

            # Check if all assets pass the filter (no filtering applied) - show project-level items only when all assets are included
            # Note: JV exclusion is not checked here because project financing is already calculated excluding JV assets
            _all_assets_included = _asset_id_output_flag.all()
            _project_level_multiplier = 1.0 if _all_assets_included else 0.0

            # Equity infusion for filtered view: balancing figure with cash carry-forward.
            # Surpluses in one period reduce the equity needed in future deficit periods.
            if not _all_assets_included:
                _filt_net = _inverse_filtered_sum(_apply_asset_filter(w_additional_requirement))
                _filt_equity = np.zeros(len(_filt_net))
                _filt_running_bal = 0.0
                for _t in range(len(_filt_net)):
                    _filt_running_bal += _filt_net[_t]
                    if _filt_running_bal < 0:
                        _filt_equity[_t] = -_filt_running_bal
                        _filt_running_bal = 0.0

            financing_map = {
                "Asset Revolver - Debt Drawdown": _pos(_apply_asset_filter(w_asset_debt_revolver_debt_withdrawal)),
                "Asset Revolver - Debt Repayment": _pos(_apply_asset_filter(w_asset_debt_revolver_debt_repayment)),
                "Asset Revolver - Arrangement Fees": _neg(_apply_asset_filter(w_asset_debt_revolver_debt_arrangement_fees * -1)),
                "Asset Revolver - Commitment Fees": _neg(_apply_asset_filter(w_asset_debt_revolver_debt_commitment_fees_payment * -1)),
                "Term Loan - Debt Drawdown": w_term_loan_drawdown.iloc[0, :] * _project_level_multiplier,
                "Term Loan - Principal Repayment": w_term_loan_principal_repayment.iloc[0, :] * _project_level_multiplier,
                "Term Loan - Balloon Payment": w_term_loan_balloon_payment.iloc[0, :] * _project_level_multiplier,
                "Term Loan - Interest Payment": w_term_loan_interest_expensed.iloc[0, :] * _project_level_multiplier,
                "Term Loan - Arrangement Fees": w_term_loan_arrangement_fees.iloc[0, :] * -1 * _project_level_multiplier,
                "Term Loan - Valuation Fees": w_term_loan_valuation_fees.iloc[0, :] * -1 * _project_level_multiplier,
                "Term Loan - Other Debt Fees": w_term_loan_other_debt_fees.iloc[0, :] * -1 * _project_level_multiplier,
                "Project Revolver - Debt Drawdown": w_project_debt_revolver_debt_withdrawal.iloc[0, :] * _project_level_multiplier,
                "Project Revolver - Debt Repayment": w_project_debt_revolver_debt_repayment.iloc[0, :] * _project_level_multiplier,
                "Project Revolver - Arrangement Fees": w_project_debt_revolver_arrangement_fees.iloc[0, :] * -1 * _project_level_multiplier,
                "Project Revolver - Commitment Fees": w_project_debt_revolver_commitment_fees_payment.iloc[0, :] * -1 * _project_level_multiplier,
                "Equity Infusion": w_equity_infusion.iloc[0, :] * _project_level_multiplier if _all_assets_included else _filt_equity,
                "Land in Kind": _pos(_apply_asset_filter(o_land_acquisition_cost_in_kind)),
            }

            for k, v in financing_map.items():
                cashflow_from_financing.loc[k, :] = v

            # Net
            cashflow_from_financing.loc["Net Cashflow from Financing", :] = sum(
                value for key, value in financing_map.items() if key != "Land in Kind"
            )

            _selected_asset_mask = (
                _asset_id_output_flag.values.astype(bool)
                & (_jv_exclusion_mask[:, 0] > 0)
            )
            _selected_asset_mask_2d = _selected_asset_mask[:, np.newaxis]
            _n_periods_cf = len(columns)

            def _calculate_weighted_progress_curve(underlying_df):
                _underlying_values = underlying_df.to_numpy(copy=True)
                _underlying = np.where(
                    _selected_asset_mask_2d,
                    np.where(pd.isna(_underlying_values), 0.0, _underlying_values),
                    0.0,
                )
                _period_totals = _underlying.sum(axis=0)
                _total_underlying = _period_totals.sum()
                if _total_underlying <= 0:
                    return np.zeros(_n_periods_cf)
                return _period_totals / _total_underlying

            def _calculate_weighted_series(series_df, weight_series):
                _series_values = series_df.to_numpy(copy=True)
                _values = np.where(
                    _selected_asset_mask_2d,
                    np.where(pd.isna(_series_values), 0.0, _series_values),
                    0.0,
                )
                _weight_values = pd.Series(weight_series).to_numpy(copy=True)
                _weights = np.where(
                    _selected_asset_mask,
                    np.where(pd.isna(_weight_values), 0.0, _weight_values),
                    0.0,
                )
                _weight_total = _weights.sum()
                if _weight_total <= 0:
                    return np.zeros(_n_periods_cf)
                return (_values * _weights[:, np.newaxis]).sum(axis=0) / _weight_total

            _escrow_construction_progress_output = _calculate_weighted_progress_curve(
                o_total_infrastructure_cost_s_curve
            )
            _escrow_cumulative_progress_output = np.minimum(
                np.cumsum(_escrow_construction_progress_output),
                1.0,
            )
            _escrow_cumulative_progress_output = np.ceil(
                _escrow_cumulative_progress_output * 1000
            ) / 1000

            _land_sales_values = o_land_sales_revenue.to_numpy(copy=True)
            _land_sales_values = np.where(pd.isna(_land_sales_values), 0.0, _land_sales_values)
            _land_sales_total_by_asset = _land_sales_values.sum(axis=1)
            _escrow_sales_payment_absorption_output = _calculate_weighted_series(
                o_land_sales_payment_absorption,
                _land_sales_total_by_asset,
            )

            # ============================================================================================
            # ESCROW SCHEDULE (FILTERED AND SUMMED)
            # ============================================================================================

            escrow_schedule_map = {
                "Construction Progress": _escrow_construction_progress_output,
                "Cumulative Construction Progress": _escrow_cumulative_progress_output,
                "Sales Payment Absorption": _escrow_sales_payment_absorption_output,
                "Inflows to Escrow": _pos(_apply_asset_filter(o_inflows_to_escrow)),
                "Funds Available for Soft Cost": _pos(_apply_asset_filter(o_funds_available_for_soft_cost)),
                "Funds Available for Hard Cost": _pos(_apply_asset_filter(o_funds_available_for_hard_cost)),
                "Transfer to Retention": _pos(_apply_asset_filter(o_transfer_to_retention)),
                "Soft Opening Balance": _pos(_apply_asset_filter(w_soft_opening_balance)),
                "Soft Inflows": _pos(_apply_asset_filter(o_funds_available_for_soft_cost)),
                "Soft Cost Total Availability": _pos(_apply_asset_filter(w_soft_cost_total_availability)),
                "Soft Cost Payment Requirement": _pos(_apply_asset_filter(w_soft_cost_payment_requirement)),
                "Soft Cost Cumulative Requirement": _pos(_apply_asset_filter(w_soft_cost_cumulative_requirement)),
                "Soft Cost Payment from Escrow": _pos(_apply_asset_filter(w_soft_cost_payment_from_escrow)),
                "Soft Additional Requirement": _pos(_apply_asset_filter(w_additional_requirements_for_soft_cost)),
                "Soft Amount Available After Reallocation": _pos(_apply_asset_filter(w_amount_available_after_soft_cost_and_reallocated_payment)),
                "Soft Last Year Release": _pos(_apply_asset_filter(w_last_year_release_soft_cost)),
                "Soft Closing Balance": _pos(_apply_asset_filter(w_soft_closing_balance)),
                "Hard Opening Balance": _pos(_apply_asset_filter(w_hard_opening_balance)),
                "Hard Inflows": _pos(_apply_asset_filter(o_funds_available_for_hard_cost)),
                "Hard Cost Total Availability": _pos(_apply_asset_filter(w_hard_cost_total_availability)),
                "Hard Cost Payment Requirement": _pos(_apply_asset_filter(w_hard_cost_payment_requirement)),
                "Hard Cost Cumulative Requirement": _pos(_apply_asset_filter(w_hard_cost_cumulative_requirement)),
                "Hard Cost Payment from Escrow": _pos(_apply_asset_filter(w_hard_cost_payment_from_escrow)),
                "Hard Additional Requirement": _pos(_apply_asset_filter(w_additional_requirements_for_hard_cost)),
                "Hard Amount Available After Payment": _pos(_apply_asset_filter(w_amount_available_after_hard_cost_payment)),
                "Hard Last Year Release": _pos(_apply_asset_filter(w_last_year_release_hard_cost)),
                "Hard Closing Balance": _pos(_apply_asset_filter(w_hard_closing_balance)),
                "Amount Available for Reallocation": _pos(_apply_asset_filter(w_amount_available_for_reallocation)),
                "Reallocation Amount": _pos(_apply_asset_filter(w_reallocation_amount)),
                "Reallocated Funds for Hard Cost Payment": _pos(_apply_asset_filter(w_reallocated_funds_for_hard_cost_payment)),
                "Additional Requirement After Allocation": _pos(_apply_asset_filter(w_additional_requirement_after_allocation)),
                "Off-plan Cash Inflow": _pos(_apply_asset_filter(o_cash_inflow_from_off_plan_sales)),
                "Escrow Setup Fees": _neg(_apply_asset_filter(o_escrow_setup_fees)),
            }

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

            escrow_schedule = _init_cashflow_df(escrow_schedule_line_items, columns)
            for k, v in escrow_schedule_map.items():
                escrow_schedule.loc[k, :] = v

            _record_timing("Cashflow from Financing assembly")

            model_timeline_me['Period Start'] = model_timeline_me['Period Start'].dt.strftime('%Y-%m-%d')
            model_timeline_me['Period End'] = model_timeline_me['Period End'].dt.strftime('%Y-%m-%d')


            model_timeline_ye['Period Start'] = model_timeline_ye['Period Start'].dt.strftime('%Y-%m-%d')
            model_timeline_ye['Period End'] = model_timeline_ye['Period End'].dt.strftime('%Y-%m-%d')

            
            o_monthly_timtline = model_timeline_me.T
            o_yearly_timeline = model_timeline_ye.T
            
            cashflow_from_operations = fn_replace_nan(cashflow_from_operations)
            cashflow_from_investments = fn_replace_nan(cashflow_from_investments)
            cashflow_from_financing = fn_replace_nan(cashflow_from_financing)
            escrow_schedule = fn_replace_nan(escrow_schedule)
            
            def fn_df_to_json_with_index(df: pd.DataFrame):
                """
                Convert a DataFrame to a JSON-serializable dictionary with index.
                
                Args:
                    df (pd.DataFrame): The DataFrame to convert.
                    
                Returns:
                    dict: Dictionary with index, columns, and data.
                """
                try:
                    return {
                        "index": df.index.tolist(),
                        "columns": df.columns.tolist(),
                        "data": df.values.tolist()
                    }
                except Exception as e:
                    print(f"Error in fn_df_to_json_with_index: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
                    raise


            # def fn_copy_output_template_tab(payload):
            #     """
            #     Paste values into the named ranges in the template sheet first,
            #     then create a copy of the template sheet as 'Cashflow Statement'.
            #     """
            try:
                # Load the workbook
                # wb = load_workbook(file_path)

                year_mapping = model_timeline_me.loc[:, "Year"]

                # Update the columns of the monthly DataFrames to reflect the 'Year'
                cashflow_from_operations.columns = year_mapping
                cashflow_from_investments.columns = year_mapping
                cashflow_from_financing.columns = year_mapping
                escrow_schedule.columns = year_mapping

                # Define the monthly DataFrames
                monthly_dfs = {
                    "Cashflow from Operations": ("o.landco.cfo.me", cashflow_from_operations),
                    "Cashflow from Investments": ("o.landco.cfi.me", cashflow_from_investments),
                    "Cashflow from Financing": ("o.landco.cff.me", cashflow_from_financing),
                    "Escrow Schedule": ("o.landco.escrow.schedule.me", escrow_schedule),
                    "Monthly Timeline": (
                        "o.landco.model.timeline.me",
                        o_monthly_timtline,
                    ),  # Add Monthly Timeline
                }

                _escrow_annual_sum = escrow_schedule.T.groupby(level=0).sum(min_count=1).T
                _escrow_annual_last = escrow_schedule.T.groupby(level=0).last().T
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
                        "o.landco.cfo.ye",
                        cashflow_from_operations.T.groupby(level=0)
                        .sum(min_count=1)
                        .T ,  # Transpose, group, and transpose back
                    ),
                    "Cashflow from Investments": (
                        "o.landco.cfi.ye",
                        cashflow_from_investments.T.groupby(level=0)
                        .sum(min_count=1)
                        .T ,  # Transpose, group, and transpose back
                    ),
                    "Cashflow from Financing": (
                        "o.landco.cff.ye",
                        cashflow_from_financing.T.groupby(level=0)
                        .sum(min_count=1)
                        .T ,  # Transpose, group, and transpose back
                    ),
                    "Escrow Schedule": (
                        "o.landco.escrow.schedule.ye",
                        _escrow_annual_sum,
                    ),
                    "Yearly Timeline": (
                        "o.landco.model.timeline.ye",
                        o_yearly_timeline,
                    ),  # Add Yearly Timeline
                }
                excel_output = {
                    "monthly_dfs": {    
                        key: (code, fn_df_to_json_with_index(df))
                        for key, (code, df) in monthly_dfs.items()
                    },
                    "annual_dfs": {
                        key: (code, fn_df_to_json_with_index(df))
                        for key, (code, df) in annual_dfs.items()
                    }
                }
                # ============================================================================================
                # JV OUTPUT — Base dataframes filtered by JV inclusion flag (sign-adjusted)
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
                    values = _coerce_numeric_values(df)
                    values = values * row_mask
                    if sign == -1:
                        values = -values
                    return _df_to_split_payload(df, values=values)

                def _serialize_df(df: pd.DataFrame, sign=1):
                    values = _coerce_numeric_values(df)
                    if sign == -1:
                        values = -values
                    return _df_to_split_payload(df, values=values)

                def _build_section_output(section_items, row_mask):
                    return {
                        item_name: (
                            _serialize_masked_asset_df(item_df, row_mask, item_sign)
                            if apply_row_mask
                            else _serialize_df(item_df, item_sign)
                        )
                        for item_name, item_df, item_sign, apply_row_mask in section_items
                    }

                def _build_output_payload(row_mask):
                    return {
                        section_name: _build_section_output(section_items, row_mask)
                        for section_name, section_items in output_section_mappings.items()
                    }

                def _apply_asset_keep_mask(df: pd.DataFrame, keep_mask: np.ndarray) -> pd.DataFrame:
                    values = _coerce_numeric_values(df)
                    values = values * keep_mask
                    return pd.DataFrame(values, index=df.index, columns=df.columns)

                _landco_inclusion_flag = (
                    pd.Series(Asset.AssetLifecycleModule.land_development)
                    .eq("Yes")
                    .reindex(template_asset_timeline.index, fill_value=False)
                )
                _devco_inclusion_flag = (
                    pd.Series(Asset.AssetLifecycleModule.vertical_development)
                    .eq("Yes")
                    .reindex(template_asset_timeline.index, fill_value=False)
                )

                _landco_jv_inclusion_flag = (
                    pd.Series(Asset.JVModule.landco_inclusion)
                    .eq("Yes")
                    .reindex(template_asset_timeline.index, fill_value=False)
                )
                _devco_jv_inclusion_flag = (
                    pd.Series(Asset.JVModule.devco_inclusion)
                    .eq("Yes")
                    .reindex(template_asset_timeline.index, fill_value=False)
                )

                # Internal transfer elimination: when asset exits LandCo to DevCo,
                # eliminate LandCo sales lines and corresponding support workings.
                _landco_to_devco_internal_transfer_mask = (
                    _landco_inclusion_flag & _devco_inclusion_flag & _landco_jv_inclusion_flag & _devco_jv_inclusion_flag
                ).values[:, np.newaxis].astype(float)
                _landco_sales_keep_mask = 1.0 - _landco_to_devco_internal_transfer_mask

                _o_on_plan_sales_collection_elim = _apply_asset_keep_mask(
                    o_on_plan_sales_collection,
                    _landco_sales_keep_mask,
                )
                _o_off_plan_sales_collection_elim = _apply_asset_keep_mask(
                    o_cash_inflow_from_off_plan_sales,
                    _landco_sales_keep_mask,
                )
                _o_land_sales_phasing_elim = _apply_asset_keep_mask(
                    o_land_sales_phasing,
                    _landco_sales_keep_mask,
                )
                _o_land_sales_revenue_elim = _apply_asset_keep_mask(
                    o_land_sales_revenue,
                    _landco_sales_keep_mask,
                )
                _o_inflows_to_escrow_elim = _apply_asset_keep_mask(
                    o_inflows_to_escrow,
                    _landco_sales_keep_mask,
                )
                _o_transfer_to_retention_elim = _apply_asset_keep_mask(
                    o_transfer_to_retention,
                    _landco_sales_keep_mask,
                )
                _w_retention_release_elim = _apply_asset_keep_mask(
                    w_retention_release,
                    _landco_sales_keep_mask,
                )
                _w_soft_cost_payment_from_escrow_elim = _apply_asset_keep_mask(
                    w_soft_cost_payment_from_escrow,
                    _landco_sales_keep_mask,
                )
                _w_hard_cost_payment_from_escrow_elim = _apply_asset_keep_mask(
                    w_hard_cost_payment_from_escrow,
                    _landco_sales_keep_mask,
                )
                _w_reallocated_funds_for_hard_cost_payment_elim = _apply_asset_keep_mask(
                    w_reallocated_funds_for_hard_cost_payment,
                    _landco_sales_keep_mask,
                )
                _w_last_year_release_hard_cost_elim = _apply_asset_keep_mask(
                    w_last_year_release_hard_cost,
                    _landco_sales_keep_mask,
                )
                _w_last_year_release_soft_cost_elim = _apply_asset_keep_mask(
                    w_last_year_release_soft_cost,
                    _landco_sales_keep_mask,
                )
                _o_cash_inflow_from_off_plan_sales_elim = _apply_asset_keep_mask(
                    o_cash_inflow_from_off_plan_sales,
                    _landco_sales_keep_mask,
                )

                _o_on_plan_sales_collection_internal_transfer = pd.DataFrame(
                    _coerce_numeric_values(o_on_plan_sales_collection)
                    - _coerce_numeric_values(_o_on_plan_sales_collection_elim),
                    index=o_on_plan_sales_collection.index,
                    columns=o_on_plan_sales_collection.columns,
                )
                _o_off_plan_sales_collection_internal_transfer = pd.DataFrame(
                    _coerce_numeric_values(o_cash_inflow_from_off_plan_sales)
                    - _coerce_numeric_values(_o_off_plan_sales_collection_elim),
                    index=o_cash_inflow_from_off_plan_sales.index,
                    columns=o_cash_inflow_from_off_plan_sales.columns,
                )
                _o_serviced_land_sales_internal_transfer = pd.DataFrame(
                    _coerce_numeric_values(_o_on_plan_sales_collection_internal_transfer)
                    + _coerce_numeric_values(_o_off_plan_sales_collection_internal_transfer),
                    index=o_on_plan_sales_collection.index,
                    columns=o_on_plan_sales_collection.columns,
                )

                output_section_mappings = {
                    "Support Workings": [
                        ("Land Acquisition Flag", o_land_acquisition_flag, 1, True),
                        ("Land Sales Phasing", o_land_sales_phasing, 1, True),
                        ("Land Sales Revenue", o_land_sales_revenue, 1, True),
                        ("On-plan Sales Collection", o_on_plan_sales_collection, 1, True),
                        ("Serviced Land Sales", _o_serviced_land_sales_internal_transfer, 1, True),
                        ("Inflows to Escrow", _o_inflows_to_escrow_elim, 1, True),
                        ("Transfer to Retention", _o_transfer_to_retention_elim, 1, True),
                        ("Retention Release", _w_retention_release_elim, 1, True),
                        ("Soft Cost Payment from Escrow", _w_soft_cost_payment_from_escrow_elim, 1, True),
                        ("Hard Cost Payment from Escrow", _w_hard_cost_payment_from_escrow_elim, 1, True),
                        ("Reallocated Funds for Hard Cost Payment", _w_reallocated_funds_for_hard_cost_payment_elim, 1, True),
                        ("Last Year Release - Hard Cost", _w_last_year_release_hard_cost_elim, 1, True),
                        ("Last Year Release - Soft Cost", _w_last_year_release_soft_cost_elim, 1, True),
                        ("Escrow Release and Payments", _o_cash_inflow_from_off_plan_sales_elim, 1, True),
                        ("Land Acquisition Cost Phasing", o_land_acquisition_payment_profile, 1, True),
                        ("Land Acquisition Cost Cash Payment", o_land_acquisition_cost_cash_payment, 1, True),
                        ("Land Acquisition Cost", o_land_acquisition_cost, 1, True),
                        ("Land Acquisition Cost In Kind", o_land_acquisition_cost_in_kind, 1, True),
                        ("Primary Infrastructure S-Curve Phasing", o_primary_infrastructure_s_curve_percent, 1, True),
                        ("Primary Infrastructure Cost S-Curve", o_primary_infrastructure_cost_s_curve, 1, True),
                        ("Secondary Infrastructure S-Curve Phasing", o_secondary_infrastructure_s_curve_percent, 1, True),
                        ("Secondary Infrastructure Cost S-Curve", o_secondary_infrastructure_cost_s_curve, 1, True),
                        ("Total Infrastructure Cost S-Curve", o_total_infrastructure_cost_s_curve, 1, True),
                        ("Asset Revolver - Opening Balance", w_asset_debt_revolver_opening_balance, 1, True),
                        ("Asset Revolver - Debt Drawdown", w_asset_debt_revolver_debt_withdrawal, 1, True),
                        ("Asset Revolver - Capitalized Interest", w_asset_debt_revolver_capitalization_of_interest, 1, True),
                        ("Asset Revolver - Debt Repayment", w_asset_debt_revolver_debt_repayment, 1, True),
                        ("Asset Revolver - Closing Balance", w_asset_debt_revolver_closing_balance, 1, True),
                        ("Asset Revolver - Arrangement Fees", w_asset_debt_revolver_debt_arrangement_fees, -1, True),
                        ("Asset Revolver - Commitment Fees Opening Balance", w_asset_debt_revolver_debt_commitment_fees_opening_balance, 1, True),
                        ("Asset Revolver - Commitment Fees Accrual", w_asset_debt_revolver_debt_commitment_fees_accrual, 1, True),
                        ("Asset Revolver - Commitment Fees Payment", w_asset_debt_revolver_debt_commitment_fees_payment, -1, True),
                        ("Asset Revolver - Commitment Fees Closing Balance", w_asset_debt_revolver_debt_commitment_fees_closing_balance, 1, True),
                        ("Project Revolver - Opening Balance", w_project_debt_revolver_opening_balance, 1, False),
                        ("Project Revolver - Debt Drawdown", w_project_debt_revolver_debt_withdrawal, 1, False),
                        ("Project Revolver - Capitalized Interest", w_project_debt_revolver_capitalization_of_interest_and_arrangement_fees, 1, False),
                        ("Project Revolver - Debt Repayment", w_project_debt_revolver_debt_repayment, 1, False),
                        ("Project Revolver - Closing Balance", w_project_debt_revolver_closing_balance, 1, False),
                        ("Project Revolver - Arrangement Fees", w_project_debt_revolver_arrangement_fees, -1, False),
                        ("Project Revolver - Commitment Fees Opening Balance", w_project_debt_revolver_commitment_fees_opening_balance, 1, False),
                        ("Project Revolver - Commitment Fees Accrual", w_project_debt_revolver_commitment_fees_accrual, 1, False),
                        ("Project Revolver - Commitment Fees Payment", w_project_debt_revolver_commitment_fees_payment, -1, False),
                        ("Project Revolver - Commitment Fees Closing Balance", w_project_debt_revolver_commitment_fees_closing_balance, 1, False),
                        # Project Level Term Loan Balance Sheet Entries
                        ("Project Term Loan - Opening Balance", w_term_loan_opening_balance, 1, False),
                        ("Project Term Loan - Debt Drawdown", w_term_loan_drawdown, 1, False),
                        ("Project Term Loan - Capitalized Interest", w_term_loan_interest_capitalization_arrangement_fees, 1, False),
                        ("Project Term Loan - Principal Repayment", w_term_loan_principal_repayment, 1, False),
                        ("Project Term Loan - Balloon Payment", w_term_loan_balloon_payment, 1, False),
                        ("Project Term Loan - Interest Payment", w_term_loan_interest_expensed, 1, False),
                        ("Project Term Loan - Closing Balance", w_term_loan_closing_balance, 1, False),
                    ],
                    "Escrow Schedule": [
                        ("Construction Progress", w_construction_progress_percent, 1, True),
                        ("Cumulative Construction Progress", w_cumulative_construction_progress_percent, 1, True),
                        ("Sales Payment Absorption", o_land_sales_payment_absorption, 1, True),
                        ("Inflows to Escrow", o_inflows_to_escrow, 1, True),
                        ("Funds Available for Soft Cost", o_funds_available_for_soft_cost, 1, True),
                        ("Funds Available for Hard Cost", o_funds_available_for_hard_cost, 1, True),
                        ("Transfer to Retention", o_transfer_to_retention, 1, True),
                        ("Soft Opening Balance", w_soft_opening_balance, 1, True),
                        ("Soft Inflows", o_funds_available_for_soft_cost, 1, True),
                        ("Soft Cost Total Availability", w_soft_cost_total_availability, 1, True),
                        ("Soft Cost Payment Requirement", w_soft_cost_payment_requirement, 1, True),
                        ("Soft Cost Cumulative Requirement", w_soft_cost_cumulative_requirement, 1, True),
                        ("Soft Cost Payment from Escrow", w_soft_cost_payment_from_escrow, 1, True),
                        ("Soft Additional Requirement", w_additional_requirements_for_soft_cost, 1, True),
                        ("Soft Amount Available After Reallocation", w_amount_available_after_soft_cost_and_reallocated_payment, 1, True),
                        ("Soft Last Year Release", w_last_year_release_soft_cost, 1, True),
                        ("Soft Closing Balance", w_soft_closing_balance, 1, True),
                        ("Hard Opening Balance", w_hard_opening_balance, 1, True),
                        ("Hard Inflows", o_funds_available_for_hard_cost, 1, True),
                        ("Hard Cost Total Availability", w_hard_cost_total_availability, 1, True),
                        ("Hard Cost Payment Requirement", w_hard_cost_payment_requirement, 1, True),
                        ("Hard Cost Cumulative Requirement", w_hard_cost_cumulative_requirement, 1, True),
                        ("Hard Cost Payment from Escrow", w_hard_cost_payment_from_escrow, 1, True),
                        ("Hard Additional Requirement", w_additional_requirements_for_hard_cost, 1, True),
                        ("Hard Amount Available After Payment", w_amount_available_after_hard_cost_payment, 1, True),
                        ("Hard Last Year Release", w_last_year_release_hard_cost, 1, True),
                        ("Hard Closing Balance", w_hard_closing_balance, 1, True),
                        ("Amount Available for Reallocation", w_amount_available_for_reallocation, 1, True),
                        ("Reallocation Amount", w_reallocation_amount, 1, True),
                        ("Reallocated Funds for Hard Cost Payment", w_reallocated_funds_for_hard_cost_payment, 1, True),
                        ("Additional Requirement After Allocation", w_additional_requirement_after_allocation, 1, True),
                        ("Off-plan Cash Inflow", o_cash_inflow_from_off_plan_sales, 1, True),
                        ("Escrow Setup Fees", o_escrow_setup_fees, -1, True),
                    ],
                    "Cashflow from Operations": [
                        ("On-plan Sales Collection", _o_on_plan_sales_collection_elim, 1, True),
                        ("Off-plan Sales Collection", _o_off_plan_sales_collection_elim, 1, True),
                        ("Escrow Setup Fees", o_escrow_setup_fees, -1, True),
                        ("Lease Collection", o_land_lease_revenue_including_grace_period, 1, True),
                        ("Associated Operating Expenses", o_land_lease_associated_operating_expenses, -1, True),
                        ("Leasing Costs", o_leasing_cost, -1, True),
                        ("Sales Transaction Cost", o_sales_transaction_cost, -1, True),
                        ("Other Income 1", o_other_income_1, 1, True),
                        ("Other Income 2", o_other_income_2, 1, True),
                        ("Government Subsidies", o_other_income_3, 1, True),
                        ("Other Expense 1", o_other_expense_1, -1, True),
                        ("Other Expense 2", o_other_expense_2, -1, True),
                        ("Other Expense 3", o_other_expense_3, -1, True),
                        ("Community Operations Expense - Amanah", o_community_operations_cost_payment_amanah, -1, True),
                        ("Community Operations Recovery - Amanah", o_community_operations_amanah_recovery, 1, True),
                        ("Community Operations Expense - ROSHN", o_community_operations_cost_payment_roshn, -1, True),
                        ("Community Operations Recovery - ROSHN", o_community_operations_roshn_recovery, 1, True),
                        ("Salaries Expenses", o_corporate_overheads_salaries_expensed, -1, True),
                        ("IT Services Expenses", o_corporate_overheads_it_services_expensed, -1, True),
                        ("Office Rent and Utilities Expenses", o_corporate_overheads_office_rent_and_utilities_expensed, -1, True),
                        ("Professional Services Expenses", o_corporate_overheads_professional_services_expensed, -1, True),
                        ("Marketing Expenses", o_corporate_overheads_marketing_expensed, -1, True),
                        ("Sales Cost Expenses", o_corporate_overheads_sales_cost_expensed, -1, True),
                        ("Additional Expenses", o_corporate_overheads_additional_expenses_expensed, -1, True),
                    ],
                    "Cashflow from Investments": [
                        ("Land Acquisition Cost Payment", o_land_acquisition_cost_cash_payment, -1, True),
                        ("Legal Cost", o_acquisition_transaction_cost_legal, -1, True),
                        ("Agency Cost", o_acquisition_transaction_cost_agency, -1, True),
                        ("Technical Cost", o_acquisition_transaction_cost_technical, -1, True),
                        ("Valuation Cost", o_acquisition_transaction_cost_valuation, -1, True),
                        ("Due Diligence Cost", o_acquisition_transaction_cost_due_diligence, -1, True),
                        ("Real Estate Transaction Tax", o_acquisition_transaction_cost_real_estate_transaction_tax, -1, True),
                        ("Municipal Fees", o_acquisition_transaction_cost_municipal_fees, -1, True),
                        ("Primary Infrastructure Cost", o_primary_infrastructure_cost_payment, -1, True),
                        ("Secondary Infrastructure Cost", o_secondary_infrastructure_cost_payment, -1, True),
                        ("Design Cost", o_design_cost_payment, -1, True),
                        ("Permitting Cost", o_permitting_cost_payment, -1, True),
                        ("Supervision Cost", o_supervision_cost_payment, -1, True),
                        ("Project Management Cost", o_project_management_cost_payment, -1, True),
                        ("Contingency Cost Payment", o_contingency_cost_payment, -1, True),
                        ("Capitalized Salaries Expenses", o_corporate_overheads_salaries_capitalized, -1, True),
                        ("Capitalized IT Services Expenses", o_corporate_overheads_it_services_capitalized, -1, True),
                        ("Capitalized Office Rent and Utilities Expenses", o_corporate_overheads_office_rent_and_utilities_capitalized, -1, True),
                        ("Capitalized Professional Services Expenses", o_corporate_overheads_professional_services_capitalized, -1, True),
                        ("Capitalized Marketing Expenses", o_corporate_overheads_marketing_capitalized, -1, True),
                        ("Capitalized Sales Cost Expenses", o_corporate_overheads_sales_cost_capitalized, -1, True),
                        ("Capitalized Additional Expenses", o_corporate_overheads_additional_expenses_capitalized, -1, True),
                        ("Land Lease - Terminal Value", o_land_lease_exit_value, 1, True),
                        ("Land Bank - Exit Value", o_land_bank_exit_value, 1, True),
                    ],
                    "Cashflow from Financing": [
                        ("Asset Revolver - Debt Drawdown", w_asset_debt_revolver_debt_withdrawal, 1, True),
                        ("Asset Revolver - Debt Repayment", w_asset_debt_revolver_debt_repayment, 1, True),
                        ("Asset Revolver - Arrangement Fees", w_asset_debt_revolver_debt_arrangement_fees, -1, True),
                        ("Asset Revolver - Commitment Fees", w_asset_debt_revolver_debt_commitment_fees_payment, -1, True),
                        ("Term Loan - Debt Drawdown", w_term_loan_drawdown, 1, False),
                        ("Term Loan - Principal Repayment", w_term_loan_principal_repayment, 1, False),
                        ("Term Loan - Balloon Payment", w_term_loan_balloon_payment, 1, False),
                        ("Term Loan - Interest Payment", w_term_loan_interest_expensed, 1, False),
                        ("Term Loan - Arrangement Fees", w_term_loan_arrangement_fees, -1, False),
                        ("Term Loan - Valuation Fees", w_term_loan_valuation_fees, -1, False),
                        ("Term Loan - Other Debt Fees", w_term_loan_other_debt_fees, -1, False),
                        ("Project Revolver - Debt Drawdown", w_project_debt_revolver_debt_withdrawal, 1, False),
                        ("Project Revolver - Debt Repayment", w_project_debt_revolver_debt_repayment, 1, False),
                        ("Project Revolver - Arrangement Fees", w_project_debt_revolver_arrangement_fees, -1, False),
                        ("Project Revolver - Commitment Fees", w_project_debt_revolver_commitment_fees_payment, -1, False),
                        ("Equity Infusion", w_equity_infusion, 1, False),
                        ("Land in Kind", w_land_in_kind, 1, False),
                    ],
                }

                _timeline_payload = _df_to_split_payload(o_monthly_timtline)
                if _thread_worker_count > 1:
                    with ThreadPoolExecutor(max_workers=min(4, _thread_worker_count)) as executor:
                        _global_future = executor.submit(class_to_dict, Global)
                        _asset_future = executor.submit(class_to_dict, Asset)
                        _jv_future = executor.submit(_build_output_payload, _jv_mask)
                        _consolidation_future = executor.submit(_build_output_payload, _jv_exclusion_mask)
                        _global_assumptions_payload = _global_future.result()
                        _asset_assumptions_payload = _asset_future.result()
                        jv_output = _jv_future.result()
                        consolidation_output = _consolidation_future.result()
                else:
                    _global_assumptions_payload = class_to_dict(Global)
                    _asset_assumptions_payload = class_to_dict(Asset)
                    jv_output = _build_output_payload(_jv_mask)
                    consolidation_output = _build_output_payload(_jv_exclusion_mask)

                jv_output["Timeline"] = _timeline_payload
                jv_output["global_assumptions"] = _global_assumptions_payload
                jv_output["asset_assumptions"] = _asset_assumptions_payload

                # ============================================================================================
                # CONSOLIDATED OUTPUT — Base dataframes filtered by JV exclusion flag (sign-adjusted)
                # ============================================================================================
                consolidation_output["Timeline"] = _timeline_payload
                consolidation_output["global_assumptions"] = _global_assumptions_payload
                consolidation_output["asset_assumptions"] = _asset_assumptions_payload

                if _EXPORT_FLAGS.get('cashflow_dataframes', False):
                    _cashflow_dataframe_exports = {
                        # =========================
                        # CFO: CASHFLOW FROM OPERATIONS
                        # =========================
                        'CFO OnPlan Sales': o_on_plan_sales_collection,
                        'CFO OffPlan Sales': o_cash_inflow_from_off_plan_sales,
                        'CFO Escrow Fees': o_escrow_setup_fees,

                        'CFO Lease Revenue': o_land_lease_revenue_including_grace_period,
                        'CFO Lease Opex': o_land_lease_associated_operating_expenses,

                        'CFO Leasing Cost': o_leasing_cost,
                        'CFO Sales Tx Cost': o_sales_transaction_cost,

                        'CFO Other Inc 1': o_other_income_1,
                        'CFO Other Inc 2': o_other_income_2,
                        'CFO Other Inc 3': o_other_income_3,

                        'CFO Other Exp 1': o_other_expense_1,
                        'CFO Other Exp 2': o_other_expense_2,
                        'CFO Other Exp 3': o_other_expense_3,

                        'CFO Comm Opex Amanah': o_community_operations_cost_payment_amanah,
                        'CFO Comm Rec Amanah': o_community_operations_amanah_recovery,

                        'CFO Comm Opex Roshn': o_community_operations_cost_payment_roshn,
                        'CFO Comm Rec Roshn': o_community_operations_roshn_recovery,

                        'CFO OH Sal Exp': o_corporate_overheads_salaries_expensed,
                        'CFO OH IT Exp': o_corporate_overheads_it_services_expensed,
                        'CFO OH Rent Exp': o_corporate_overheads_office_rent_and_utilities_expensed,
                        'CFO OH Prof Exp': o_corporate_overheads_professional_services_expensed,
                        'CFO OH Mkt Exp': o_corporate_overheads_marketing_expensed,
                        'CFO OH Sales Exp': o_corporate_overheads_sales_cost_expensed,
                        'CFO OH Add Exp': o_corporate_overheads_additional_expenses_expensed,

                        # =========================
                        # CFI: CASHFLOW FROM INVESTING
                        # =========================
                        'CFI Land Acq Cost': o_land_acquisition_cost_cash_payment,
                        'CFF Land In Kind': w_land_in_kind,

                        'CFI Tx Legal': o_acquisition_transaction_cost_legal,
                        'CFI Tx Agency': o_acquisition_transaction_cost_agency,
                        'CFI Tx Tech': o_acquisition_transaction_cost_technical,
                        'CFI Tx Val': o_acquisition_transaction_cost_valuation,
                        'CFI Tx DD': o_acquisition_transaction_cost_due_diligence,
                        'CFI Tx Tax': o_acquisition_transaction_cost_real_estate_transaction_tax,
                        'CFI Tx Muni': o_acquisition_transaction_cost_municipal_fees,

                        'CFI Infra Primary': o_primary_infrastructure_cost_payment,
                        'CFI Infra Secondary': o_secondary_infrastructure_cost_payment,

                        'CFI Design': o_design_cost_payment,
                        'CFI Permit': o_permitting_cost_payment,
                        'CFI Supervision': o_supervision_cost_payment,
                        'CFI PM': o_project_management_cost_payment,

                        'CFI Contingency': o_contingency_cost_payment,

                        'CFI OH Sal Cap': o_corporate_overheads_salaries_capitalized,
                        'CFI OH IT Cap': o_corporate_overheads_it_services_capitalized,
                        'CFI OH Rent Cap': o_corporate_overheads_office_rent_and_utilities_capitalized,
                        'CFI OH Prof Cap': o_corporate_overheads_professional_services_capitalized,
                        'CFI OH Mkt Cap': o_corporate_overheads_marketing_capitalized,
                        'CFI OH Sales Cap': o_corporate_overheads_sales_cost_capitalized,
                        'CFI OH Add Cap': o_corporate_overheads_additional_expenses_capitalized,

                        'CFI Lease Exit': o_land_lease_exit_value,
                        'CFI LandBank Exit': o_land_bank_exit_value,

                        # =========================
                        # CFF: CASHFLOW FROM FINANCING
                        # =========================
                        'CFF Asset Rev Draw': w_asset_debt_revolver_debt_withdrawal,
                        'CFF Asset Rev Repay': w_asset_debt_revolver_debt_repayment,
                        'CFF Asset Rev Arr Fee': w_asset_debt_revolver_debt_arrangement_fees,
                        'CFF Asset Rev Com Fee': w_asset_debt_revolver_debt_commitment_fees_payment,

                        'CFF Asset To Proj': w_asset_cash_schedule_transfer_to_project,
                        'CFF Proj To Asset': w_additional_requirement,

                        'CFF Term Draw': w_term_loan_drawdown,
                        'CFF Term Principal': w_term_loan_principal_repayment,
                        'CFF Term Balloon': w_term_loan_balloon_payment,
                        'CFF Term Interest': w_term_loan_interest_expensed,
                        'CFF Term Arr Fee': w_term_loan_arrangement_fees,
                        'CFF Term Val Fee': w_term_loan_valuation_fees,
                        'CFF Term Other Fee': w_term_loan_other_debt_fees,

                        'CFF Proj Rev Draw': w_project_debt_revolver_debt_withdrawal,
                        'CFF Proj Rev Repay': w_project_debt_revolver_debt_repayment,
                        'CFF Proj Rev Arr Fee': w_project_debt_revolver_arrangement_fees,
                        'CFF Proj Rev Com Fee': w_project_debt_revolver_commitment_fees_payment,

                        'CFF Equity Inject': w_equity_infusion,
                    }

                # ============================================================================================
                # SUB-MODULE 3.15: DATA NORMALIZATION FOR DASHBOARD
                # ============================================================================================
                # This section normalizes all calculated DataFrames into a long-format structure
                # suitable for dashboard visualization and analytics. Each DataFrame is flattened
                # from wide format (assets x periods) to long format with metadata columns.
                #
                # OPTIMIZATION NOTES:
                #   - Uses vectorized pandas operations for melt and groupby
                #   - Filters zero values early to reduce downstream processing
                #   - Pre-allocates list for normalized tables
                #   - Single concat at end instead of incremental concatenation
                #
                # Output Structure:
                #   - Model: Source model identifier ("LandCo")
                #   - Value Type: "Monthly" or "Annual" aggregation
                #   - Cashflow Section: CFO, CFI, or CFF classification
                #   - Main Category: Primary grouping (e.g., "Land Sale Revenue")
                #   - Line Item: Specific line item name
                #   - Asset: Asset identifier
                #   - Period Start / Year: Time dimension
                #   - Value: Numeric value
                #   - Additional metadata: Region, City, Asset Class, etc.
                # ============================================================================================

                _record_timing("Output serialization and packaging")

                def flatten_asset_timeseries(
                    data,
                    period_start,
                    registry_meta,
                    additional_columns=None,
                    expected_shape=(75, 504)
                ):
                    """
                    Flatten wide-format DataFrame (assets x periods) to long-format for dashboard.
                    
                    Args:
                        data: DataFrame or ndarray with shape (n_assets, n_periods)
                        period_start: Series of period start dates for columns
                        registry_meta: Dict with Model, Cashflow Section, Main Category, Line Item
                        additional_columns: Optional dict of metadata columns to add
                        expected_shape: Expected (n_assets, n_periods) for determining category level
                    
                    Returns:
                        DataFrame in long format with monthly + annual aggregations
                    """
                    data = fn_replace_nan(data)

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
                        raise TypeError("Input data must be DataFrame or ndarray.")

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
                            # Asset level → metadata must align with asset rows
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
                             # Project level → do not assign any value for metadata columns
                            pass

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

                    # annual_df = annual_df.rename(columns={"Year": "Period Start"})
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

                data_registry = {

                    # ===============================
                    # CASHFLOW FROM OPERATIONS
                    # ===============================

                    # Land Sales
                    "On-plan Sales Collection": {
                        "df": o_on_plan_sales_collection,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Land Sales",
                        "Line Item": "On-plan Sales Collection",
                        "Sign": 1
                    },
                    "Off-plan Sales Collection": {
                        "df": o_cash_inflow_from_off_plan_sales,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Land Sales",
                        "Line Item": "Off-plan Sales Collection",
                        "Sign": 1
                    },
                    "Escrow Setup Fees": {
                        "df": o_escrow_setup_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Land Sales",
                        "Line Item": "Escrow Setup Fees",
                        "Sign": -1
                    },

                    # Land Lease
                    "Lease Collection": {
                        "df": o_land_lease_revenue_including_grace_period,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Land Lease",
                        "Line Item": "Lease Collection",
                        "Sign": 1
                    },
                    "Associated Operating Expenses": {
                        "df": o_land_lease_associated_operating_expenses,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Land Lease",
                        "Line Item": "Associated Operating Expenses",
                        "Sign": -1
                    },

                    # Leasing & Disposal Costs
                    "Leasing Costs": {
                        "df": o_leasing_cost,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Leasing & Disposal Costs",
                        "Line Item": "Leasing Costs",
                        "Sign": -1
                    },
                    "Sales Transaction Cost": {
                        "df": o_sales_transaction_cost,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Leasing & Disposal Costs",
                        "Line Item": "Sales Transaction Cost",
                        "Sign": -1
                    },

                    # Other Income
                    "Other Income 1": {
                        "df": o_other_income_1,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Income",
                        "Line Item": "Other Income 1",
                        "Sign": 1
                    },
                    "Other Income 2": {
                        "df": o_other_income_2,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Income",
                        "Line Item": "Other Income 2",
                        "Sign": 1
                    },
                    "Government Subsidies": {
                        "df": o_other_income_3,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Income",
                        "Line Item": "Government Subsidies",
                        "Sign": 1
                    },

                    # Other Expense
                    "Other Expense 1": {
                        "df": o_other_expense_1,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Expense",
                        "Line Item": "Other Expense 1",
                        "Sign": -1
                    },
                    "Other Expense 2": {
                        "df": o_other_expense_2,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Expense",
                        "Line Item": "Other Expense 2",
                        "Sign": -1
                    },
                    "Other Expense 3": {
                        "df": o_other_expense_3,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Other Expense",
                        "Line Item": "Other Expense 3",
                        "Sign": -1
                    },

                    # Community Operations - Amanah
                    "Amanah Expense": {
                        "df": o_community_operations_cost_payment_amanah,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Community Operations - Amanah",
                        "Line Item": "Expense",
                        "Sign": -1
                    },
                    "Amanah Recovery": {
                        "df": o_community_operations_amanah_recovery,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Community Operations - Amanah",
                        "Line Item": "Recovery",
                        "Sign": 1
                    },

                    # Community Operations - ROSHN
                    "ROSHN Expense": {
                        "df": o_community_operations_cost_payment_roshn,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Community Operations - ROSHN",
                        "Line Item": "Expense",
                        "Sign": -1
                    },
                    "ROSHN Recovery": {
                        "df": o_community_operations_roshn_recovery,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Community Operations - ROSHN",
                        "Line Item": "Recovery",
                        "Sign": 1
                    },

                    # Corporate Overheads - Expensed
                    "Salaries Expenses": {
                        "df": o_corporate_overheads_salaries_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Salaries Expenses",
                        "Sign": -1
                    },
                    "IT Services Cost": {
                        "df": o_corporate_overheads_it_services_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "IT Services Cost",
                        "Sign": -1
                    },
                    "Office Rent and Utilities Cost": {
                        "df": o_corporate_overheads_office_rent_and_utilities_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Office Rent and Utilities Cost",
                        "Sign": -1
                    },
                    "Professional Services Cost": {
                        "df": o_corporate_overheads_professional_services_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Professional Services Cost",
                        "Sign": -1
                    },
                    "Marketing Cost": {
                        "df": o_corporate_overheads_marketing_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Marketing Cost",
                        "Sign": -1
                    },
                    "Sales Cost": {
                        "df": o_corporate_overheads_sales_cost_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Sales Cost",
                        "Sign": -1
                    },
                    "Additional Expenses": {
                        "df": o_corporate_overheads_additional_expenses_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Operations",
                        "Main Category": "Corporate Overhead Expenses",
                        "Line Item": "Additional Expenses",
                        "Sign": -1
                    },

                    # ===============================
                    # CASHFLOW FROM INVESTMENTS
                    # ===============================

                    "Land Acquisition Cost Payment": {
                        "df": o_land_acquisition_cost_cash_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Land Acquisition Cost Payment",
                        "Line Item": "",
                        "Sign": -1
                    },

                    "Legal Cost": {
                        "df": o_acquisition_transaction_cost_legal,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Legal Cost",
                        "Sign": -1
                    },

                    "Agency Cost": {
                        "df": o_acquisition_transaction_cost_agency,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Agency Cost",
                        "Sign": -1
                    },

                    "Technical Cost": {
                        "df": o_acquisition_transaction_cost_technical,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Technical Cost",
                        "Sign": -1
                    },

                    "Valuation Cost": {
                        "df": o_acquisition_transaction_cost_valuation,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Valuation Cost",
                        "Sign": -1
                    },

                    "Due Diligence Cost": {
                        "df": o_acquisition_transaction_cost_due_diligence,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Due Diligence Cost",
                        "Sign": -1
                    },

                    "Real Estate Transaction Tax": {
                        "df": o_acquisition_transaction_cost_real_estate_transaction_tax,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Real Estate Transaction Tax",
                        "Sign": -1
                    },

                    "Municipal Fees": {
                        "df": o_acquisition_transaction_cost_municipal_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Acquisition Transaction Costs",
                        "Line Item": "Municipal Fees",
                        "Sign": -1
                    },

                    "Primary Infrastructure Cost": {
                        "df": o_primary_infrastructure_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Infrastructure Cost Payment",
                        "Line Item": "Primary Infrastructure Cost",
                        "Sign": -1
                    },
                    "Secondary Infrastructure Cost": {
                        "df": o_secondary_infrastructure_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Infrastructure Cost Payment",
                        "Line Item": "Secondary Infrastructure Cost",
                        "Sign": -1
                    },

                    "Design Cost": {
                        "df": o_design_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Soft Costs Payment",
                        "Line Item": "Design Cost",
                        "Sign": -1
                    },
                    "Permitting Cost": {
                        "df": o_permitting_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Soft Costs Payment",
                        "Line Item": "Permitting Cost",
                        "Sign": -1
                    },
                    "Supervision Cost": {
                        "df": o_supervision_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Soft Costs Payment",
                        "Line Item": "Supervision Cost",
                        "Sign": -1
                    },
                    "Project Management Cost": {
                        "df": o_project_management_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Soft Costs Payment",
                        "Line Item": "Project Management Cost",
                        "Sign": -1
                    },

                    "Contingency Cost Payment": {
                        "df": o_contingency_cost_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Contingency Cost Payment",
                        "Line Item": "",
                        "Sign": -1
                    },

                    # Corporate Overheads - Capitalized
                    "Salaries Expenses - Capitalized": {
                        "df": o_corporate_overheads_salaries_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Salaries Expenses",
                        "Sign": -1
                    },
                    "IT Services Cost": {
                        "df": o_corporate_overheads_it_services_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "IT Services Cost",
                        "Sign": -1
                    },
                    "Office Rent and Utilities Cost": {
                        "df": o_corporate_overheads_office_rent_and_utilities_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Office Rent and Utilities Cost",
                        "Sign": -1
                    },
                    "Professional Services Cost": {
                        "df": o_corporate_overheads_professional_services_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Professional Services Cost",
                        "Sign": -1
                    },
                    "Marketing Cost": {
                        "df": o_corporate_overheads_marketing_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Marketing Cost",
                        "Sign": -1
                    },
                    "Sales Cost": {
                        "df": o_corporate_overheads_sales_cost_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Sales Cost",
                        "Sign": -1
                    },
                    "Additional Expenses": {
                        "df": o_corporate_overheads_additional_expenses_capitalized,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Corporate Overhead Expenses Capitalized",
                        "Line Item": "Additional Expenses",
                        "Sign": -1
                    },

                    "Land Lease - Terminal Value": {
                        "df": o_land_lease_exit_value,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Land Lease - Terminal Value",
                        "Line Item": "",
                        "Sign": 1
                    },
                    "Land Bank - Exit Value": {
                        "df": o_land_bank_exit_value,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Investments",
                        "Main Category": "Land Bank - Exit Value",
                        "Line Item": "",
                        "Sign": 1
                    },

                    # ===============================
                    # CASHFLOW FROM FINANCING
                    # ===============================

                    "Asset Revolver - Debt Drawdown": {
                        "df": w_asset_debt_revolver_debt_withdrawal,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Asset Level Debt Revolver",
                        "Line Item": "Debt Drawdown",
                        "Sign": 1
                    },

                    "Asset Revolver - Debt Repayment": {
                        "df": w_asset_debt_revolver_debt_repayment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Asset Level Debt Revolver",
                        "Line Item": "Debt Repayment",
                        "Sign": 1
                    },

                    "Debt Arrangement Fees": {
                        "df": w_asset_debt_revolver_debt_arrangement_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Asset Level Debt Revolver - Debt Fees",
                        "Line Item": "Debt Arrangement Fees",
                        "Sign": 1
                    },

                    "Commitment Fees Payment": {
                        "df": w_asset_debt_revolver_debt_commitment_fees_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Asset Level Debt Revolver - Debt Fees",
                        "Line Item": "Commitment Fees Payment",
                        "Sign": 1
                    },

                    "Term Loan - Debt Drawdown": {
                        "df": w_term_loan_drawdown,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan",
                        "Line Item": "Debt Drawdown",
                        "Sign": 1
                    },

                    "Term Loan - Principal Repayment": {
                        "df": w_term_loan_principal_repayment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan",
                        "Line Item": "Principal Repayment",
                        "Sign": 1
                    },

                    "Term Loan - Balloon Payment": {
                        "df": w_term_loan_balloon_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan",
                        "Line Item": "Balloon Payment",
                        "Sign": 1
                    },

                    "Term Loan - Interest Payment": {
                        "df": w_term_loan_interest_expensed,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan",
                        "Line Item": "Interest Payment - Expensed",
                        "Sign": 1
                    },

                    "Term Loan - Arrangement Fees": {
                        "df": w_term_loan_arrangement_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan - Debt Fees",
                        "Line Item": "Debt Arrangement Fees",
                        "Sign": 1
                    },

                    "Term Loan - Valuation Fees": {
                        "df": w_term_loan_valuation_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan - Debt Fees",
                        "Line Item": "Valuation Fees",
                        "Sign": 1
                    },

                    "Term Loan - Other Debt Fees": {
                        "df": w_term_loan_other_debt_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Term Loan - Debt Fees",
                        "Line Item": "Other Debt Fees",
                        "Sign": 1
                    },

                    "Project Revolver - Debt Drawdown": {
                        "df": w_project_debt_revolver_debt_withdrawal,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Debt Revolver",
                        "Line Item": "Debt Drawdown",
                        "Sign": 1
                    },

                    "Project Revolver - Debt Repayment": {
                        "df": w_project_debt_revolver_debt_repayment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Debt Revolver",
                        "Line Item": "Debt Repayment",
                        "Sign": 1
                    },

                    "Project Revolver - Arrangement Fees": {
                        "df": w_project_debt_revolver_arrangement_fees,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Debt Revolver - Debt Fees",
                        "Line Item": "Debt Arrangement Fees",
                        "Sign": 1
                    },

                    "Project Revolver - Commitment Fees": {
                        "df": w_project_debt_revolver_commitment_fees_payment,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Project Level Debt Revolver - Debt Fees",
                        "Line Item": "Commitment Fees Payment",
                        "Sign": 1
                    },

                    "Land in Kind": {
                        "df": pd.DataFrame(w_land_in_kind.iloc[0, :]).T,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Equity Injection - Project",
                        "Line Item": "Land in Kind",
                        "Sign": 1
                    },
                    "Equity Infusion": {
                        "df": pd.DataFrame(w_equity_infusion.iloc[0, :]).T,
                        "Model": "LandCo",
                        "Cashflow Section": "Cashflow from Financing",
                        "Main Category": "Equity Injection - Project",
                        "Line Item": "Equity Infusion",
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
                    "Business Model": Asset.BusinessModelModule.business_model,
                    "Exit Counterparty": Asset.BusinessModelModule.exit_counterparty,
                    "JV Inclusion": Asset.JVModule.landco_inclusion
                }
                
                # Pre-allocate list with known size for better memory efficiency
                _registry_count = len(data_registry)
                normalized_tables = [None] * _registry_count


                # Uncomment below section for normalization with progress tracking and error handling at individual table level
                # for idx, (key, meta) in enumerate(data_registry.items()):

                #     normalized_df = flatten_asset_timeseries(
                #         data=meta["df"],
                #         period_start=model_timeline_me["Period Start"],
                #         registry_meta=meta,
                #         additional_columns=common_metadata
                #     )

                #     normalized_tables[idx] = normalized_df

                # # Filter out any None values (shouldn't happen but defensive)
                # normalized_tables = [df for df in normalized_tables if df is not None]

                # # Concatenate everything in single operation
                # normalized_dashboard_data = pd.concat(normalized_tables, ignore_index=True)

                # normalized_dashboard_data.to_excel("normalized_dashboard_data.xlsx", index=False)
                # os.startfile("normalized_dashboard_data.xlsx")
                # raise breakpoint

                _record_timing(f"Dashboard normalization preparation ({_registry_count} tables)")

                # ============================================================================================
                # EXPORT CASHFLOW STATEMENTS TO EXCEL
                # ============================================================================================
                
                if _EXPORT_FLAGS.get('cashflow_statements', False):
                    _cashflow_exports = {
                        # Monthly Cashflows
                        'CF Operations (Monthly)': cashflow_from_operations,
                        'CF Investments (Monthly)': cashflow_from_investments,
                        'CF Financing (Monthly)': cashflow_from_financing,
                        # Annual Cashflows
                        'CF Operations (Annual)': cashflow_from_operations.T.groupby(level=0).sum(min_count=1).T,
                        'CF Investments (Annual)': cashflow_from_investments.T.groupby(level=0).sum(min_count=1).T,
                        'CF Financing (Annual)': cashflow_from_financing.T.groupby(level=0).sum(min_count=1).T,
                        # Timeline
                        'Monthly Timeline': o_monthly_timtline,
                        'Yearly Timeline': o_yearly_timeline,
                    }
                    _export_to_excel(_cashflow_exports, 'export_cashflow_statements', 'Cashflow Statements')

                timing_summary = _finalize_timing_summary("Final response assembly")
                print(timing_summary["summary_text"])

                # return excel_output
                if is_save:
                    return {
                        "exceloutput": excel_output,
                        "jvoutput": jv_output,
                        "consolidationoutput": consolidation_output   
                    }
                return {
                    "exceloutput": excel_output,
                    # "jvoutput": jv_output,
                    # "consolidationoutput": consolidation_output
                }

            except Exception as e:
                print(f"Error in fn_copy_output_template_tab: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                raise

            # fn_copy_output_template_tab(payload)

    except Exception as e:
        return print(f"Failed to initialise values {e}\n{traceback.format_exc()}")

def fninitialising_all_values(payload,is_save):
    try:
        output = wrapper_for_vars(payload, is_save)
        return output
    except Exception as e:
        print(f"Error in fninitialising_all_values: {e}")
        print(f"Traceback: {traceback.format_exc()}")