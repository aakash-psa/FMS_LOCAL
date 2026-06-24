import os
import time
import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from calendar import month
from math import perm
import warnings
import math


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


def _cache_safe_value(value):
    """Convert values into hashable primitives for helper-level caching."""
    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return None if pd.isna(value) else value.isoformat()

    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()

    if isinstance(value, pd.Series):
        return tuple(_cache_safe_value(item) for item in value.tolist())

    if isinstance(value, np.ndarray):
        return tuple(_cache_safe_value(item) for item in value.tolist())

    if isinstance(value, tuple):
        return tuple(_cache_safe_value(item) for item in value)

    if isinstance(value, list):
        return tuple(_cache_safe_value(item) for item in value)

    try:
        return None if pd.isna(value) else value
    except TypeError:
        return value


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

        reallocation_option = None
        escrow_set_up_fee = None


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

def wrapper_for_vars(payload):
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
            - timing_summary: End-of-run timing summary with rows and table text
            
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
                        if 'landco' not in name.lower():
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
    
            assumptions=fn_read_all_named_ranges_json(payload)

            _assumption_value_cache = assumptions.groupby("name", sort=False)["value"].first().to_dict()

            def _get_assumption_value(name):
                return _assumption_value_cache[name]

            _global_class_names = _get_assumption_value("a.landco.global.class")
            _global_attr_names = _get_assumption_value("a.landco.global.attribute")
            _global_attr_values = _get_assumption_value("a.landco.global.value")

            _asset_class_names = _get_assumption_value("a.landco.class.row")
            _asset_attr_names = _get_assumption_value("a.landco.attribute.row")
            _asset_attr_values = _get_assumption_value("a.landco.asset.data")

            _predefined_profile_names = _get_assumption_value("a.landco.predefined.profile.name")[:]
            _predefined_profile_data = _get_assumption_value("a.landco.predefined.profile")
            _predefined_profile_durations = _get_assumption_value("a.landco.predefined.profile.duration")
            _escalation_profile_names = _get_assumption_value("a.landco.escalation.profile.name")[:]
            _escalation_profile_data = _get_assumption_value("a.landco.escalation.profile")
            _default_date = _get_assumption_value("a.landco.default.date")

            # Pre-extract schedule/phasing keys for fast access throughout submodules
            _schedule_cache = {
                k: v for k, v in _assumption_value_cache.items()
                if k.startswith("s.landco.")
            }

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
                        class_names = _global_class_names
                        attr_names = _global_attr_names
                        attr_values = _global_attr_values
                        class_name = cls.__name__
                        for i, attr in enumerate(attr_names):
                            # Error control: check if class name matches for this attribute
                            if class_names[i] != class_name:
                                continue
                    
                            # Error control: check if attribute is defined in the class
                            elif not hasattr(cls, attr):
                                raise ValueError(
                                    f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                                )
                    
                            # Check if the attribute name contains "date" and the value is an integer or float
                            if "date" in attr.lower() and isinstance(attr_values[i], (int, float)):
                                if attr_values[i] == "" or attr_values[i] == 0:
                                    convertedval = None
                                else:
                                    convertedval = datetime.fromtimestamp((attr_values[i] - 25569) * 86400.0).strftime('%Y-%m-%d')
                                setattr(cls, attr, pd.to_datetime(convertedval))
                            else:
                                # Set attribute value directly
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

            # Assign values to class attributes

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
                    class_names = _asset_class_names
                    attr_names = _asset_attr_names
                    attr_values = _asset_attr_values
                    class_name = cls.__name__

                    # Find the index of the inclusion attribute
                    inclusion_idx = attr_names.index("asset_landco_inclusion")
                    inclusion_flags = [row[inclusion_idx] == "Yes" for row in attr_values]

                    for i, attr in enumerate(attr_names):
                        if class_names[i] != class_name:
                            continue
                        elif not hasattr(cls, attr):
                            raise ValueError(
                                f"Attribute '{attr}' at index {i} is not defined in class '{class_name}'."
                            )

                        col = []
                        is_date = "date" in attr.lower()
                        for idx, row in enumerate(attr_values):
                            val = row[i]
                            if not inclusion_flags[idx] or val == "":
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
            _period_start_lookup = pd.to_datetime(model_timeline_me['Period Start'], errors='coerce')
            _period_starts = _period_start_lookup.values
            _period_starts_days = _period_starts.astype('datetime64[D]')
            _timeline_period_cache_key = tuple(_cache_safe_value(period) for period in _period_start_lookup.tolist())
            _period_start_to_idx = {
                period: idx
                for idx, period in enumerate(_period_start_lookup)
                if pd.notna(period)
            }
            _period_months = model_timeline_me['Period Start'].dt.month.values
            _period_years = model_timeline_me["Year"].values
            _unique_years = list(model_timeline_me["Year"].unique())
            _year_indices = np.array([_unique_years.index(year) for year in _period_years], dtype=int)

            _allocation_basis_mapping = {
                "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
                "Built Up Area": Asset.LandAreaModule.built_up_area,
                "Gross Leasable Area": Asset.LandAreaModule.total_nsa__gla,
                "Units": Asset.LandAreaModule.units,
            }
            _land_cost_basis_mapping = {
                "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                "Developable Land Area": Asset.LandAreaModule.developable_land_area,
            }
            _infrastructure_cost_basis_mapping = {
                "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
            }
            _community_cost_basis_mapping = {
                "Gross Land Area": Asset.LandAreaModule.gross_land_area,
                "Developable Land Area": Asset.LandAreaModule.developable_land_area,
                "Gross Floor Area": Asset.LandAreaModule.gross_floor_area,
                "Built Up Area": Asset.LandAreaModule.built_up_area,
            }
            _zero_asset_series = pd.Series(0.0, index=_template_index, dtype='float64')
            _allocation_basis_series_cache = {
                key: pd.Series(value, index=_template_index, dtype='float64')
                for key, value in _allocation_basis_mapping.items()
            }
            _land_cost_basis_series_cache = {
                key: pd.Series(value, index=_template_index, dtype='float64')
                for key, value in _land_cost_basis_mapping.items()
            }
            _infrastructure_cost_basis_series_cache = {
                key: pd.Series(value, index=_template_index, dtype='float64')
                for key, value in _infrastructure_cost_basis_mapping.items()
            }
            _community_cost_basis_series_cache = {
                key: pd.Series(value, index=_template_index, dtype='float64')
                for key, value in _community_cost_basis_mapping.items()
            }
            _predefined_profile_lookup = {}
            for idx, name in enumerate(_predefined_profile_names):
                if name in (None, '') or idx >= len(_predefined_profile_data) or idx >= len(_predefined_profile_durations):
                    continue

                try:
                    profile_values = np.asarray(_predefined_profile_data[idx], dtype='float64')
                except (TypeError, ValueError):
                    continue

                _predefined_profile_lookup[name] = {
                    'values': profile_values,
                    'max_duration': _predefined_profile_durations[idx],
                    'sum': float(profile_values.sum()),
                    'non_zero_count': int(np.count_nonzero(profile_values > 0)),
                }
            _escalation_profile_name_to_idx = {
                name: idx for idx, name in enumerate(_escalation_profile_names)
            }
            _global_predefined_profile_row_cache = {}
            _global_user_defined_profile_row_cache = {}
            _monthly_escalation_curve_cache = {}
            _monthly_escalation_result_cache = {}
            _global_escalation_profile_result_cache = {}
            _transaction_flag_cache = {}
            _start_flag_value_cache = {}
            _dataframe_row_sum_cache = {}
            _max_thread_workers = max(2, min(8, (os.cpu_count() or 1) - 1))  # Leave 1 core free
            _shared_executor = ExecutorManager.get_thread_executor(max_workers=_max_thread_workers)
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
                datetime_arr = pd.to_datetime(values, errors='coerce').to_numpy(dtype='datetime64[ns]').reshape(-1)
                return tuple(datetime_arr.view('int64').tolist())

            def _resolve_start_indices(start_dates):
                start_dates_arr = pd.to_datetime(start_dates, errors='coerce').to_numpy(dtype='datetime64[ns]').reshape(-1)
                start_idx_arr = np.full(start_dates_arr.shape[0], -1, dtype=int)

                for loop_row_idx, start_date_value in enumerate(start_dates_arr.tolist()):
                    if pd.isna(start_date_value):
                        continue
                    start_idx_arr[loop_row_idx] = _period_start_to_idx.get(pd.Timestamp(start_date_value), -1)

                return start_dates_arr, start_idx_arr

            def _should_parallelize(task_count):
                """Only parallelize if overhead is justified."""
                return _max_thread_workers > 1 and task_count > 1 and (_n_assets * _n_periods) >= 2000

            def _map_independent_tasks(task_items, task_callable):
                if not _should_parallelize(len(task_items)):
                    return [task_callable(task_item) for task_item in task_items]

                max_workers = min(len(task_items), _max_thread_workers)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    return list(executor.map(task_callable, task_items))

            def _build_monthly_escalation_curve(task_item):
                profile_name, profile_index = task_item
                if profile_name in (None, '') or profile_index >= len(_escalation_profile_data):
                    return None

                escalation_profile = _escalation_profile_data[profile_index]
                if escalation_profile in (None, ''):
                    return None

                try:
                    escalation_rate = np.asarray([value for value in escalation_profile if value != ''], dtype='float64')
                except (TypeError, ValueError):
                    return None

                if escalation_rate.size == 0:
                    return None

                escalation_rates_by_period = escalation_rate[_year_indices]
                monthly_escalation_percents = ((1 + escalation_rates_by_period) ** (1 / 12)) - 1
                return profile_name, (monthly_escalation_percents, np.cumprod(1 + monthly_escalation_percents))

            escalation_curve_tasks = [
                (profile_name, profile_index)
                for profile_index, profile_name in enumerate(_escalation_profile_names)
            ]
            for profile_result in _map_independent_tasks(escalation_curve_tasks, _build_monthly_escalation_curve):
                if profile_result is None:
                    continue
                profile_name, profile_curve = profile_result
                _monthly_escalation_curve_cache[profile_name] = profile_curve
            
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

            def _get_cached_df_row_sum(df):
                """Cache row sums for finalized DataFrames reused across modules."""
                if df is None:
                    return _zero_asset_series

                cache_key = id(df)
                cached_sum = _dataframe_row_sum_cache.get(cache_key)
                if cached_sum is None:
                    cached_sum = df.sum(axis=1)
                    _dataframe_row_sum_cache[cache_key] = cached_sum
                return cached_sum
            
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
                    template_values = template.values
                    profile_option_arr = np.asarray(profile_option, dtype=object).reshape(-1)
                    selected_profile_arr = np.asarray(selected_pre_defined_profile, dtype=object).reshape(-1)
                    _, start_idx_arr = _resolve_start_indices(start_dates)
                    grouped_row_assignments = {}

                    for loop_row_idx in template.index:

                        # Skip assets that do not use "Pre Defined" payment profiles
                        if profile_option_arr[loop_row_idx] != "Pre Defined":
                            continue

                        selected_profile = selected_profile_arr[loop_row_idx]
                        if not selected_profile or pd.isna(selected_profile):
                            continue

                        profile_details = _predefined_profile_lookup.get(selected_profile)
                        if profile_details is None:
                            continue

                        if abs(profile_details['sum'] - 1) > 1e-6:
                            continue

                        if profile_details['non_zero_count'] > profile_details['max_duration']:
                            continue

                        start_idx = start_idx_arr[loop_row_idx]
                        if start_idx < 0:
                            continue

                        cache_key = (selected_profile, int(start_idx))
                        grouped_row_assignments.setdefault(cache_key, []).append(loop_row_idx)

                    def _build_predefined_profile_row(cache_key):
                        selected_profile_name, start_idx = cache_key
                        row_values = np.zeros(_n_periods, dtype='float64')
                        profile_array = _predefined_profile_lookup[selected_profile_name]['values']
                        valid_length = min(len(profile_array), _n_periods - start_idx)
                        row_values[start_idx:start_idx + valid_length] = profile_array[:valid_length]
                        return cache_key, row_values

                    missing_row_keys = [
                        cache_key
                        for cache_key in grouped_row_assignments
                        if cache_key not in _global_predefined_profile_row_cache
                    ]
                    for cache_key, row_values in _map_independent_tasks(missing_row_keys, _build_predefined_profile_row):
                        _global_predefined_profile_row_cache[cache_key] = row_values

                    for cache_key, row_indices in grouped_row_assignments.items():
                        template_values[row_indices, :] = _global_predefined_profile_row_cache[cache_key]

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
                    template_values = template.values
                    profile_options_arr = np.asarray(profile_options, dtype=object).reshape(-1)
                    durations_arr = np.asarray(durations, dtype=object).reshape(-1)
                    _, start_idx_arr = _resolve_start_indices(start_dates)
                    grouped_row_assignments = {}

                    for loop_row_idx in template.index:

                        # Skip assets that do not use "User Defined" payment profiles
                        if profile_options_arr[loop_row_idx] != "User Defined":
                            continue

                        duration = durations_arr[loop_row_idx]
                        if duration is None or duration <= 0 or pd.isna(duration):
                            continue

                        start_idx = start_idx_arr[loop_row_idx]
                        if start_idx < 0:
                            continue

                        schedule = schedules[loop_row_idx]
                        if isinstance(schedule, list):
                            normalized_schedule = tuple(
                                0 if value == '' or value is None or pd.isna(value) else value
                                for value in schedule
                            )
                            cache_key = ('list', normalized_schedule, int(start_idx), int(duration))
                        else:
                            normalized_schedule = 0 if pd.isna(schedule) or schedule is None else schedule
                            cache_key = ('scalar', _normalize_cache_scalar(normalized_schedule), int(start_idx), int(duration))

                        grouped_row_assignments.setdefault(cache_key, []).append(loop_row_idx)

                    def _build_user_defined_profile_row(cache_key):
                        schedule_kind, normalized_schedule, start_idx, duration = cache_key
                        row_values = np.zeros(_n_periods, dtype='float64')
                        valid_end_idx = min(int(start_idx + duration), _n_periods)

                        if valid_end_idx <= start_idx:
                            return cache_key, row_values

                        if schedule_kind == 'list':
                            schedule_slice = normalized_schedule[start_idx:valid_end_idx]
                            schedule_values = np.array([
                                0 if value == '' or value is None or pd.isna(value) else value
                                for value in schedule_slice
                            ], dtype='float64')
                        else:
                            schedule_values = np.full(
                                valid_end_idx - start_idx,
                                0 if normalized_schedule is None else normalized_schedule,
                                dtype='float64',
                            )

                        row_values[start_idx:valid_end_idx] = schedule_values
                        return cache_key, row_values

                    missing_row_keys = [
                        cache_key
                        for cache_key in grouped_row_assignments
                        if cache_key not in _global_user_defined_profile_row_cache
                    ]
                    for cache_key, row_values in _map_independent_tasks(missing_row_keys, _build_user_defined_profile_row):
                        _global_user_defined_profile_row_cache[cache_key] = row_values

                    for cache_key, row_indices in grouped_row_assignments.items():
                        template_values[row_indices, :] = _global_user_defined_profile_row_cache[cache_key]

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
                    selected_profile_arr = np.asarray(selected_escalation_profile, dtype=object).reshape(-1)
                    selected_profile_key = _normalize_sequence_cache_key(selected_profile_arr)
                    cached_result = _monthly_escalation_result_cache.get(selected_profile_key)

                    if cached_result is None:
                        monthly_percent_values = np.zeros((_n_assets, _n_periods), dtype='float64')
                        monthly_factor_values = np.ones((_n_assets, _n_periods), dtype='float64')
                        valid_selected_profiles = [
                            profile_name
                            for profile_name in pd.unique(pd.Series(selected_profile_arr, dtype='object'))
                            if isinstance(profile_name, str)
                            and profile_name != ''
                            and profile_name in _monthly_escalation_curve_cache
                        ]

                        for profile_name in valid_selected_profiles:
                            profile_curves = _monthly_escalation_curve_cache.get(profile_name)
                            if profile_curves is None:
                                continue

                            profile_mask = selected_profile_arr == profile_name
                            monthly_percent_values[profile_mask, :] = profile_curves[0]
                            monthly_factor_values[profile_mask, :] = profile_curves[1]

                        cached_result = (monthly_percent_values, monthly_factor_values)
                        _monthly_escalation_result_cache[selected_profile_key] = cached_result

                    escalation_percent_template.iloc[:, :] = cached_result[0]
                    escalation_factor_template.iloc[:, :] = cached_result[1]
                    
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
                    allocation_basis_series = _allocation_basis_series_cache.get(global_allocation_basis, _zero_asset_series)
                    cost_basis_series = _land_cost_basis_series_cache.get(global_cost_basis, _zero_asset_series)

                    allocation_basis_filtered = allocation_basis_series.where(~override_mask, pd.NA)
                    total_allocation_basis = allocation_basis_filtered.sum(skipna=True)

                    allocation_percent = allocation_basis_filtered / total_allocation_basis
                    global_ad_hoc_amount = allocation_percent * global_ad_hoc_amount

                    cost_basis_filtered = cost_basis_series.where(~override_mask, pd.NA)
                    global_sar_per_sqm_amount = cost_basis_filtered * global_cost_per_sqm

                    global_percent_of_amount = _get_cached_df_row_sum(acquisition_cost_df) * global_cost_percent

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
                    cache_key = _normalize_datetime_cache_key(transaction_dates)
                    cached_flag_values = _transaction_flag_cache.get(cache_key)
                    if cached_flag_values is None:
                        flag_values = np.zeros((_n_assets, _n_periods), dtype=float)
                        transaction_dates_arr = pd.to_datetime(transaction_dates, errors='coerce').values.astype('datetime64[D]')

                        valid_mask = ~np.isnat(transaction_dates_arr)
                        if valid_mask.any():
                            valid_indices = np.where(valid_mask)[0]
                            valid_trans = transaction_dates_arr[valid_mask]
                            flag_values[valid_indices] = (
                                valid_trans[:, np.newaxis] == _period_starts_days[np.newaxis, :]
                            ).astype(float)

                        _transaction_flag_cache[cache_key] = flag_values
                        cached_flag_values = flag_values

                    return pd.DataFrame(
                        cached_flag_values,
                        index=template.index,
                        columns=template.columns
                    )
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
                    
                    # Corrected logic to get corresponding values from cost_basis_mapping based on cost_basis_key_series
                    cost_basis_values = pd.Series(0.0, index=asset_cost_basis_key.index, dtype='float64')
                    for cost_basis_key, basis_series in _infrastructure_cost_basis_series_cache.items():
                        matching_mask = asset_cost_basis_key == cost_basis_key
                        if matching_mask.any():
                            cost_basis_values.loc[matching_mask] = basis_series.loc[matching_mask]

                    if (override_mask & sar_per_sqm_mask).any():
                        cost_amount.loc[override_mask & sar_per_sqm_mask] = (
                            cost_basis_values.loc[override_mask & sar_per_sqm_mask] * asset_cost_per_sqm.loc[override_mask & sar_per_sqm_mask]
                        )

                    # Apply the logic for override = "No"
                    no_override_mask = ~override_mask

                    if global_calculation_approach == "SAR / SQM of":
                        global_cost_basis_values = _infrastructure_cost_basis_series_cache.get(global_cost_basis_key, _zero_asset_series)
                        cost_amount.loc[no_override_mask] = (
                            global_cost_basis_values.loc[no_override_mask] * global_cost_per_sqm
                        )

                    elif global_calculation_approach == "Ad-Hoc Amount":
                        allocation_basis_series = _allocation_basis_series_cache.get(global_allocation_basis_key, _zero_asset_series)
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

                    percent_of_cost_basis_mapping = {
                        "Primary Infrastructure Cost": _get_cached_df_row_sum(primary_infrastructure_cost_df),
                        "Secondary Infrastructure Cost": _get_cached_df_row_sum(secondary_infrastructure_cost_df),
                        "Total Infrastructure Cost": _get_cached_df_row_sum(total_infrastructure_cost_df),
                        "Soft Cost": _get_cached_df_row_sum(soft_cost_df),
                        "Total Infrastructure + Soft Cost": _get_cached_df_row_sum(total_infrastructure_and_soft_cost_df),
                    }

                    override_mask = pd.Series(asset_override) == "Yes"
                    allocation_basis_series = _allocation_basis_series_cache.get(global_allocation_basis, _zero_asset_series)
                    sar_per_sqm_cost_basis_series = _infrastructure_cost_basis_series_cache.get(global_cost_basis, _zero_asset_series)
                    percent_of_cost_basis_series = percent_of_cost_basis_mapping.get(global_cost_basis, _zero_asset_series)

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
                schedules=_get_assumption_value("s.landco.acquisition.cost.payment"),
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
                predefined_profile_names=_predefined_profile_names,
                predefined_profile_data=_predefined_profile_data,
                predefined_profile_durations=_predefined_profile_durations,
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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

            # ============================================================================================
            # ACQUISITION TRANSACTION COSTS — 7 TYPES (PARALLEL FAN-OUT)  # OPTIMIZED: all 7 types are independent — run concurrently
            # ============================================================================================

            def _compute_single_acquisition_txn_cost_block(  # OPTIMIZED: generic worker for all 7 acquisition transaction cost types
                asset_override, asset_amount, asset_date, asset_esc,
                global_alloc_basis, global_cost_basis,
                global_ad_hoc, global_per_sqm, global_pct, global_approach,
                global_transaction_date, global_esc_profile,
                acquisition_cost_df,
            ):
                """Thread-safe worker: runs the 5-step pipeline for one transaction cost type."""
                _amount, _date, _esc = fn_calculate_acquisition_transaction_cost(
                    template=template_asset_timeline,
                    asset_override=asset_override,
                    asset_cost_amount=pd.Series(asset_amount),
                    asset_cost_transaction_date=pd.Series(asset_date),
                    asset_cost_escalation=pd.Series(asset_esc),
                    global_allocation_basis=global_alloc_basis,
                    global_cost_basis=global_cost_basis,
                    global_ad_hoc_amount=global_ad_hoc,
                    global_cost_per_sqm=global_per_sqm,
                    global_cost_percent=global_pct,
                    global_calculation_approach=global_approach,
                    global_transaction_date=global_transaction_date,
                    global_escalation_profile=global_esc_profile,
                    acquisition_cost_df=acquisition_cost_df,
                )
                _flag = fn_create_transaction_flag(
                    transaction_dates=_date,
                    timeline_periods=model_timeline_me['Period Start'],
                    template=template_asset_timeline
                )
                _esc_pct   = _create_zero_df()
                _esc_facts = _create_zero_df()
                _esc_pct, _esc_facts = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=_esc_pct,
                    escalation_factor_template=_esc_facts,
                    selected_escalation_profile=_esc,
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )
                _esc_mapping = _esc_facts * _flag
                _cost = fn_calculate_escalated_transaction_cost(
                    base_amount_series=_amount,
                    escalation_factor_mapping=_esc_mapping,
                    transaction_cost_flag=_flag,
                    calculation_approach=global_approach,
                    template=template_asset_timeline
                )
                return _flag, _cost

            _txn_cost_specs = {  # OPTIMIZED: maps each cost type to its asset/global params — evaluated at definition time
                "legal": (
                    Asset.AcquisitionTransactionCostModule.legal_cost_override,
                    Asset.AcquisitionTransactionCostModule.legal_cost_amount,
                    Asset.AcquisitionTransactionCostModule.legal_cost_transaction_date,
                    Asset.AcquisitionTransactionCostModule.legal_cost_escalation,
                    Global.AcquisitionTransactionCost.legal_cost_allocation_basis,
                    Global.AcquisitionTransactionCost.legal_cost_cost_basis,
                    Global.AcquisitionTransactionCost.legal_cost_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.legal_cost_cost_per_sqm,
                    Global.AcquisitionTransactionCost.legal_cost_cost_percent,
                    Global.AcquisitionTransactionCost.legal_cost_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.legal_cost_escalation_profile,
                ),
                "agency": (
                    Asset.AcquisitionTransactionCostModule.agency_cost_override,
                    Asset.AcquisitionTransactionCostModule.agency_cost_amount,
                    Asset.AcquisitionTransactionCostModule.agency_cost_transaction_date,
                    Asset.AcquisitionTransactionCostModule.agency_cost_escalation,
                    Global.AcquisitionTransactionCost.agency_cost_allocation_basis,
                    Global.AcquisitionTransactionCost.agency_cost_cost_basis,
                    Global.AcquisitionTransactionCost.agency_cost_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.agency_cost_cost_per_sqm,
                    Global.AcquisitionTransactionCost.agency_cost_cost_percent,
                    Global.AcquisitionTransactionCost.agency_cost_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.agency_cost_escalation_profile,
                ),
                "technical": (
                    Asset.AcquisitionTransactionCostModule.technical_cost_override,
                    Asset.AcquisitionTransactionCostModule.technical_cost_amount,
                    Asset.AcquisitionTransactionCostModule.technical_cost_transaction_date,
                    Asset.AcquisitionTransactionCostModule.technical_cost_escalation,
                    Global.AcquisitionTransactionCost.technical_cost_allocation_basis,
                    Global.AcquisitionTransactionCost.technical_cost_cost_basis,
                    Global.AcquisitionTransactionCost.technical_cost_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.technical_cost_cost_per_sqm,
                    Global.AcquisitionTransactionCost.technical_cost_cost_percent,
                    Global.AcquisitionTransactionCost.technical_cost_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.technical_cost_escalation_profile,
                ),
                "valuation": (
                    Asset.AcquisitionTransactionCostModule.valuation_cost_override,
                    Asset.AcquisitionTransactionCostModule.valuation_cost_amount,
                    Asset.AcquisitionTransactionCostModule.valuation_cost_transaction_date,
                    Asset.AcquisitionTransactionCostModule.valuation_cost_escalation,
                    Global.AcquisitionTransactionCost.valuation_cost_allocation_basis,
                    Global.AcquisitionTransactionCost.valuation_cost_cost_basis,
                    Global.AcquisitionTransactionCost.valuation_cost_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.valuation_cost_cost_per_sqm,
                    Global.AcquisitionTransactionCost.valuation_cost_cost_percent,
                    Global.AcquisitionTransactionCost.valuation_cost_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.valuation_cost_escalation_profile,
                ),
                "due_diligence": (
                    Asset.AcquisitionTransactionCostModule.due_diligence_cost_override,
                    Asset.AcquisitionTransactionCostModule.due_diligence_cost_amount,
                    Asset.AcquisitionTransactionCostModule.due_diligence_cost_transaction_date,
                    Asset.AcquisitionTransactionCostModule.due_diligence_cost_escalation,
                    Global.AcquisitionTransactionCost.due_diligence_cost_allocation_basis,
                    Global.AcquisitionTransactionCost.due_diligence_cost_cost_basis,
                    Global.AcquisitionTransactionCost.due_diligence_cost_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.due_diligence_cost_cost_per_sqm,
                    Global.AcquisitionTransactionCost.due_diligence_cost_cost_percent,
                    Global.AcquisitionTransactionCost.due_diligence_cost_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.due_diligence_cost_escalation_profile,
                ),
                "rett": (
                    Asset.AcquisitionTransactionCostModule.real_estate_transaction_tax_override,
                    Asset.AcquisitionTransactionCostModule.real_estate_transaction_tax_amount,
                    Asset.AcquisitionTransactionCostModule.real_estate_transaction_tax_transaction_date,
                    Asset.AcquisitionTransactionCostModule.real_estate_transaction_tax_escalation,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_allocation_basis,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_cost_basis,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_cost_per_sqm,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_cost_percent,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.real_estate_transaction_tax_escalation_profile,
                ),
                "municipal_fees": (
                    Asset.AcquisitionTransactionCostModule.municipal_fees_override,
                    Asset.AcquisitionTransactionCostModule.municipal_fees_amount,
                    Asset.AcquisitionTransactionCostModule.municipal_fees_transaction_date,
                    Asset.AcquisitionTransactionCostModule.municipal_fees_escalation,
                    Global.AcquisitionTransactionCost.municipal_fees_allocation_basis,
                    Global.AcquisitionTransactionCost.municipal_fees_cost_basis,
                    Global.AcquisitionTransactionCost.municipal_fees_ad_hoc_amount,
                    Global.AcquisitionTransactionCost.municipal_fees_cost_per_sqm,
                    Global.AcquisitionTransactionCost.municipal_fees_cost_percent,
                    Global.AcquisitionTransactionCost.municipal_fees_calculation_approach,
                    w_acquisition_date,
                    Global.AcquisitionTransactionCost.municipal_fees_escalation_profile,
                ),
            }

            _txn_cost_results = _execute_named_threaded_tasks(  # OPTIMIZED: fan-out — 7 types run concurrently, each independent
                {k: (lambda spec=spec: _compute_single_acquisition_txn_cost_block(*spec, o_land_acquisition_cost))
                 for k, spec in _txn_cost_specs.items()}
            )

            # Unpack results to original variable names
            (o_acquisition_transaction_cost_legal_flag,
             o_acquisition_transaction_cost_legal) = _txn_cost_results["legal"]
            (o_acquisition_transaction_cost_agency_flag,
             o_acquisition_transaction_cost_agency) = _txn_cost_results["agency"]
            (o_acquisition_transaction_cost_technical_flag,
             o_acquisition_transaction_cost_technical) = _txn_cost_results["technical"]
            (o_acquisition_transaction_cost_valuation_flag,
             o_acquisition_transaction_cost_valuation) = _txn_cost_results["valuation"]
            (o_acquisition_transaction_cost_due_diligence_flag,
             o_acquisition_transaction_cost_due_diligence) = _txn_cost_results["due_diligence"]
            (o_acquisition_transaction_cost_real_estate_transaction_tax_flag,
             o_acquisition_transaction_cost_real_estate_transaction_tax) = _txn_cost_results["rett"]
            (o_acquisition_transaction_cost_municipal_fees_flag,
             o_acquisition_transaction_cost_municipal_fees) = _txn_cost_results["municipal_fees"]

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

            # ============================================================================================
            # PRIMARY + SECONDARY INFRASTRUCTURE — PARALLEL FAN-OUT
            # OPTIMIZED: primary and secondary infrastructure are independent; run concurrently
            # ============================================================================================

            def _compute_primary_infrastructure_block():  # OPTIMIZED: closure lifting primary infra for parallel execution
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
                    schedules=_get_assumption_value("s.landco.primary.infrastructure.s.curve"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                    schedules=_get_assumption_value("s.landco.primary.infrastructure.payment"),
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_primary_infrastructure_s_curve_percent_user_defined': w_primary_infrastructure_s_curve_percent_user_defined,
                    'w_primary_infrastructure_s_curve_percent_pre_defined': w_primary_infrastructure_s_curve_percent_pre_defined,
                    'o_primary_infrastructure_s_curve_percent': o_primary_infrastructure_s_curve_percent,
                    'o_primary_infrastructure_payment_user_defined_profile': o_primary_infrastructure_payment_user_defined_profile,
                    'primary_infrastructure_cost_amount': primary_infrastructure_cost_amount,
                    'w_primary_infrastructure_monthly_escalation_percent': w_primary_infrastructure_monthly_escalation_percent,
                    'w_primary_infrastructure_monthly_escalation_factors': w_primary_infrastructure_monthly_escalation_factors,
                    'w_primary_infrastructure_construction_start_flag': w_primary_infrastructure_construction_start_flag,
                    'w_primary_infrastructure_monthly_escalation_factor_mapping': w_primary_infrastructure_monthly_escalation_factor_mapping,
                    'o_primary_infrastructure_cost_payment': o_primary_infrastructure_cost_payment,
                    'o_primary_infrastructure_cost_s_curve': o_primary_infrastructure_cost_s_curve,
                }

            def _compute_secondary_infrastructure_block():  # OPTIMIZED: closure lifting secondary infra for parallel execution

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
                    schedules=_get_assumption_value("s.landco.secondary.infrastructure.s.curve"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                    schedules=_get_assumption_value("s.landco.secondary.infrastructure.payment"),
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_secondary_infrastructure_s_curve_percent_user_defined': w_secondary_infrastructure_s_curve_percent_user_defined,
                    'w_secondary_infrastructure_s_curve_percent_pre_defined': w_secondary_infrastructure_s_curve_percent_pre_defined,
                    'o_secondary_infrastructure_s_curve_percent': o_secondary_infrastructure_s_curve_percent,
                    'o_secondary_infrastructure_payment_user_defined_profile': o_secondary_infrastructure_payment_user_defined_profile,
                    'secondary_infrastructure_cost_amount': secondary_infrastructure_cost_amount,
                    'w_secondary_infrastructure_monthly_escalation_percent': w_secondary_infrastructure_monthly_escalation_percent,
                    'w_secondary_infrastructure_monthly_escalation_factors': w_secondary_infrastructure_monthly_escalation_factors,
                    'w_secondary_infrastructure_construction_start_flag': w_secondary_infrastructure_construction_start_flag,
                    'w_secondary_infrastructure_monthly_escalation_factor_mapping': w_secondary_infrastructure_monthly_escalation_factor_mapping,
                    'o_secondary_infrastructure_cost_payment': o_secondary_infrastructure_cost_payment,
                    'o_secondary_infrastructure_cost_s_curve': o_secondary_infrastructure_cost_s_curve,
                }

            _infra_results = _execute_named_threaded_tasks({  # OPTIMIZED: primary + secondary run concurrently
                'primary':   _compute_primary_infrastructure_block,
                'secondary': _compute_secondary_infrastructure_block,
            })
            _infra_primary_result   = _infra_results['primary']
            _infra_secondary_result = _infra_results['secondary']

            # Unpack primary infrastructure results
            w_primary_infrastructure_s_curve_percent_user_defined = _infra_primary_result['w_primary_infrastructure_s_curve_percent_user_defined']
            w_primary_infrastructure_s_curve_percent_pre_defined = _infra_primary_result['w_primary_infrastructure_s_curve_percent_pre_defined']
            o_primary_infrastructure_s_curve_percent = _infra_primary_result['o_primary_infrastructure_s_curve_percent']
            o_primary_infrastructure_payment_user_defined_profile = _infra_primary_result['o_primary_infrastructure_payment_user_defined_profile']
            primary_infrastructure_cost_amount = _infra_primary_result['primary_infrastructure_cost_amount']
            w_primary_infrastructure_monthly_escalation_percent = _infra_primary_result['w_primary_infrastructure_monthly_escalation_percent']
            w_primary_infrastructure_monthly_escalation_factors = _infra_primary_result['w_primary_infrastructure_monthly_escalation_factors']
            w_primary_infrastructure_construction_start_flag = _infra_primary_result['w_primary_infrastructure_construction_start_flag']
            w_primary_infrastructure_monthly_escalation_factor_mapping = _infra_primary_result['w_primary_infrastructure_monthly_escalation_factor_mapping']
            o_primary_infrastructure_cost_payment = _infra_primary_result['o_primary_infrastructure_cost_payment']
            o_primary_infrastructure_cost_s_curve = _infra_primary_result['o_primary_infrastructure_cost_s_curve']

            # Unpack secondary infrastructure results
            w_secondary_infrastructure_s_curve_percent_user_defined = _infra_secondary_result['w_secondary_infrastructure_s_curve_percent_user_defined']
            w_secondary_infrastructure_s_curve_percent_pre_defined = _infra_secondary_result['w_secondary_infrastructure_s_curve_percent_pre_defined']
            o_secondary_infrastructure_s_curve_percent = _infra_secondary_result['o_secondary_infrastructure_s_curve_percent']
            o_secondary_infrastructure_payment_user_defined_profile = _infra_secondary_result['o_secondary_infrastructure_payment_user_defined_profile']
            secondary_infrastructure_cost_amount = _infra_secondary_result['secondary_infrastructure_cost_amount']
            w_secondary_infrastructure_monthly_escalation_percent = _infra_secondary_result['w_secondary_infrastructure_monthly_escalation_percent']
            w_secondary_infrastructure_monthly_escalation_factors = _infra_secondary_result['w_secondary_infrastructure_monthly_escalation_factors']
            w_secondary_infrastructure_construction_start_flag = _infra_secondary_result['w_secondary_infrastructure_construction_start_flag']
            w_secondary_infrastructure_monthly_escalation_factor_mapping = _infra_secondary_result['w_secondary_infrastructure_monthly_escalation_factor_mapping']
            o_secondary_infrastructure_cost_payment = _infra_secondary_result['o_secondary_infrastructure_cost_payment']
            o_secondary_infrastructure_cost_s_curve = _infra_secondary_result['o_secondary_infrastructure_cost_s_curve']


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

            _record_timing("Infrastructure Cost Module")


            def _compute_design_cost_block():  # OPTIMIZED: closure for parallel soft cost execution
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
                    schedules=_get_assumption_value("s.landco.design.cost.phasing"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                _period_starts_dt = pd.to_datetime(_period_starts, errors="coerce")

                # Vectorized design cost start flag creation using broadcasting
                _design_cost_starts_reshaped = np.array(design_cost_start_dates, dtype='datetime64[D]').reshape(-1, 1)
                _period_starts_reshaped = _period_starts_days.reshape(1, -1)  # Pre-computed global

                w_design_cost_start_flag = pd.DataFrame(
                    (_design_cost_starts_reshaped == _period_starts_reshaped).astype(int),
                    index=template_asset_timeline.index,
                    columns=template_asset_timeline.columns
                )

                # Call the generalized function for monthly escalation profile calculation
                w_design_cost_monthly_escalation_percent, w_design_cost_monthly_escalation_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=w_design_cost_monthly_escalation_percent,
                    escalation_factor_template=w_design_cost_monthly_escalation_factors,
                    selected_escalation_profile=design_cost_escalation_profile,
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_design_cost_payment_user_defined_phasing': w_design_cost_payment_user_defined_phasing,
                    'w_design_cost_pre_defined_phasing': w_design_cost_pre_defined_phasing,
                    'o_design_cost_phasing': o_design_cost_phasing,
                    'design_cost_amount': design_cost_amount,
                    'w_design_cost_monthly_escalation_percent': w_design_cost_monthly_escalation_percent,
                    'w_design_cost_monthly_escalation_factors': w_design_cost_monthly_escalation_factors,
                    'w_design_cost_start_flag': w_design_cost_start_flag,
                    'w_design_cost_monthly_escalation_factor_mapping': w_design_cost_monthly_escalation_factor_mapping,
                    'w_design_cost_escalation_applicability_flag': w_design_cost_escalation_applicability_flag,
                    'w_design_cost_escalation_applicability_flag_mapping': w_design_cost_escalation_applicability_flag_mapping,
                    'o_design_cost_payment': o_design_cost_payment,
                }

            def _compute_permitting_cost_block():  # OPTIMIZED: closure for parallel soft cost execution
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
                    schedules=_get_assumption_value("s.landco.permitting.cost.phasing"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                _period_starts_dt = pd.to_datetime(_period_starts, errors="coerce")

                # Vectorized permitting cost start flag creation using broadcasting
                start_dates_arr = np.array(permitting_cost_start_dates).reshape(-1, 1)
                period_starts_arr = _period_starts_dt.to_numpy().reshape(1, -1)
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_permitting_cost_payment_user_defined_phasing': w_permitting_cost_payment_user_defined_phasing,
                    'w_permitting_cost_pre_defined_phasing': w_permitting_cost_pre_defined_phasing,
                    'o_permitting_cost_phasing': o_permitting_cost_phasing,
                    'permitting_cost_amount': permitting_cost_amount,
                    'w_permitting_cost_monthly_escalation_percent': w_permitting_cost_monthly_escalation_percent,
                    'w_permitting_cost_monthly_escalation_factors': w_permitting_cost_monthly_escalation_factors,
                    'w_permitting_cost_start_flag': w_permitting_cost_start_flag,
                    'w_permitting_cost_monthly_escalation_factor_mapping': w_permitting_cost_monthly_escalation_factor_mapping,
                    'w_permitting_cost_escalation_applicability_flag': w_permitting_cost_escalation_applicability_flag,
                    'w_permitting_cost_escalation_applicability_flag_mapping': w_permitting_cost_escalation_applicability_flag_mapping,
                    'o_permitting_cost_payment': o_permitting_cost_payment,
                }

            def _compute_supervision_cost_block():  # OPTIMIZED: closure for parallel soft cost execution
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
                    schedules=_get_assumption_value("s.landco.supervision.cost.phasing"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                _period_starts_dt = pd.to_datetime(_period_starts, errors="coerce")

                # Vectorized supervision cost start flag creation using broadcasting
                start_dates_arr = np.array(supervision_cost_start_dates).reshape(-1, 1)
                period_starts_arr = _period_starts_dt.to_numpy().reshape(1, -1)
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_supervision_cost_payment_user_defined_phasing': w_supervision_cost_payment_user_defined_phasing,
                    'w_supervision_cost_pre_defined_phasing': w_supervision_cost_pre_defined_phasing,
                    'o_supervision_cost_phasing': o_supervision_cost_phasing,
                    'supervision_cost_amount': supervision_cost_amount,
                    'w_supervision_cost_monthly_escalation_percent': w_supervision_cost_monthly_escalation_percent,
                    'w_supervision_cost_monthly_escalation_factors': w_supervision_cost_monthly_escalation_factors,
                    'w_supervision_cost_start_flag': w_supervision_cost_start_flag,
                    'w_supervision_cost_monthly_escalation_factor_mapping': w_supervision_cost_monthly_escalation_factor_mapping,
                    'w_supervision_cost_escalation_applicability_flag': w_supervision_cost_escalation_applicability_flag,
                    'w_supervision_cost_escalation_applicability_flag_mapping': w_supervision_cost_escalation_applicability_flag_mapping,
                    'o_supervision_cost_payment': o_supervision_cost_payment,
                }

            def _compute_project_management_cost_block():  # OPTIMIZED: closure for parallel soft cost execution
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
                    schedules=_get_assumption_value("s.landco.project.management.cost.phasing"),
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
                    predefined_profile_names=_predefined_profile_names,
                    predefined_profile_data=_predefined_profile_data,
                    predefined_profile_durations=_predefined_profile_durations,
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
                _period_starts_dt = pd.to_datetime(_period_starts, errors="coerce")

                # Vectorized project management cost start flag creation using broadcasting
                start_dates_arr = np.array(project_management_cost_start_dates).reshape(-1, 1)
                period_starts_arr = _period_starts_dt.to_numpy().reshape(1, -1)
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                return {
                    'w_project_management_cost_payment_user_defined_phasing': w_project_management_cost_payment_user_defined_phasing,
                    'w_project_management_cost_pre_defined_phasing': w_project_management_cost_pre_defined_phasing,
                    'o_project_management_cost_phasing': o_project_management_cost_phasing,
                    'project_management_cost_amount': project_management_cost_amount,
                    'w_project_management_cost_monthly_escalation_percent': w_project_management_cost_monthly_escalation_percent,
                    'w_project_management_cost_monthly_escalation_factors': w_project_management_cost_monthly_escalation_factors,
                    'w_project_management_cost_start_flag': w_project_management_cost_start_flag,
                    'w_project_management_cost_monthly_escalation_factor_mapping': w_project_management_cost_monthly_escalation_factor_mapping,
                    'w_project_management_cost_escalation_applicability_flag': w_project_management_cost_escalation_applicability_flag,
                    'w_project_management_cost_escalation_applicability_flag_mapping': w_project_management_cost_escalation_applicability_flag_mapping,
                    'o_project_management_cost_payment': o_project_management_cost_payment,
                }

            # ==========================================================================================
            # DESIGN / PERMITTING / SUPERVISION / PROJECT MANAGEMENT COSTS — PARALLEL FAN-OUT
            # OPTIMIZED: 4 soft cost types are independent of each other; run concurrently
            # ==========================================================================================

            _soft_cost_results = _execute_named_threaded_tasks({  # OPTIMIZED: 4-way fan-out
                'design':     _compute_design_cost_block,
                'permitting': _compute_permitting_cost_block,
                'supervision': _compute_supervision_cost_block,
                'pm':         _compute_project_management_cost_block,
            })

            # Unpack design cost results
            w_design_cost_payment_user_defined_phasing = _soft_cost_results['design']['w_design_cost_payment_user_defined_phasing']
            w_design_cost_pre_defined_phasing = _soft_cost_results['design']['w_design_cost_pre_defined_phasing']
            o_design_cost_phasing = _soft_cost_results['design']['o_design_cost_phasing']
            design_cost_amount = _soft_cost_results['design']['design_cost_amount']
            w_design_cost_monthly_escalation_percent = _soft_cost_results['design']['w_design_cost_monthly_escalation_percent']
            w_design_cost_monthly_escalation_factors = _soft_cost_results['design']['w_design_cost_monthly_escalation_factors']
            w_design_cost_start_flag = _soft_cost_results['design']['w_design_cost_start_flag']
            w_design_cost_monthly_escalation_factor_mapping = _soft_cost_results['design']['w_design_cost_monthly_escalation_factor_mapping']
            w_design_cost_escalation_applicability_flag = _soft_cost_results['design']['w_design_cost_escalation_applicability_flag']
            w_design_cost_escalation_applicability_flag_mapping = _soft_cost_results['design']['w_design_cost_escalation_applicability_flag_mapping']
            o_design_cost_payment = _soft_cost_results['design']['o_design_cost_payment']

            # Unpack permitting cost results
            w_permitting_cost_payment_user_defined_phasing = _soft_cost_results['permitting']['w_permitting_cost_payment_user_defined_phasing']
            w_permitting_cost_pre_defined_phasing = _soft_cost_results['permitting']['w_permitting_cost_pre_defined_phasing']
            o_permitting_cost_phasing = _soft_cost_results['permitting']['o_permitting_cost_phasing']
            permitting_cost_amount = _soft_cost_results['permitting']['permitting_cost_amount']
            w_permitting_cost_monthly_escalation_percent = _soft_cost_results['permitting']['w_permitting_cost_monthly_escalation_percent']
            w_permitting_cost_monthly_escalation_factors = _soft_cost_results['permitting']['w_permitting_cost_monthly_escalation_factors']
            w_permitting_cost_start_flag = _soft_cost_results['permitting']['w_permitting_cost_start_flag']
            w_permitting_cost_monthly_escalation_factor_mapping = _soft_cost_results['permitting']['w_permitting_cost_monthly_escalation_factor_mapping']
            w_permitting_cost_escalation_applicability_flag = _soft_cost_results['permitting']['w_permitting_cost_escalation_applicability_flag']
            w_permitting_cost_escalation_applicability_flag_mapping = _soft_cost_results['permitting']['w_permitting_cost_escalation_applicability_flag_mapping']
            o_permitting_cost_payment = _soft_cost_results['permitting']['o_permitting_cost_payment']

            # Unpack supervision cost results
            w_supervision_cost_payment_user_defined_phasing = _soft_cost_results['supervision']['w_supervision_cost_payment_user_defined_phasing']
            w_supervision_cost_pre_defined_phasing = _soft_cost_results['supervision']['w_supervision_cost_pre_defined_phasing']
            o_supervision_cost_phasing = _soft_cost_results['supervision']['o_supervision_cost_phasing']
            supervision_cost_amount = _soft_cost_results['supervision']['supervision_cost_amount']
            w_supervision_cost_monthly_escalation_percent = _soft_cost_results['supervision']['w_supervision_cost_monthly_escalation_percent']
            w_supervision_cost_monthly_escalation_factors = _soft_cost_results['supervision']['w_supervision_cost_monthly_escalation_factors']
            w_supervision_cost_start_flag = _soft_cost_results['supervision']['w_supervision_cost_start_flag']
            w_supervision_cost_monthly_escalation_factor_mapping = _soft_cost_results['supervision']['w_supervision_cost_monthly_escalation_factor_mapping']
            w_supervision_cost_escalation_applicability_flag = _soft_cost_results['supervision']['w_supervision_cost_escalation_applicability_flag']
            w_supervision_cost_escalation_applicability_flag_mapping = _soft_cost_results['supervision']['w_supervision_cost_escalation_applicability_flag_mapping']
            o_supervision_cost_payment = _soft_cost_results['supervision']['o_supervision_cost_payment']

            # Unpack project management cost results
            w_project_management_cost_payment_user_defined_phasing = _soft_cost_results['pm']['w_project_management_cost_payment_user_defined_phasing']
            w_project_management_cost_pre_defined_phasing = _soft_cost_results['pm']['w_project_management_cost_pre_defined_phasing']
            o_project_management_cost_phasing = _soft_cost_results['pm']['o_project_management_cost_phasing']
            project_management_cost_amount = _soft_cost_results['pm']['project_management_cost_amount']
            w_project_management_cost_monthly_escalation_percent = _soft_cost_results['pm']['w_project_management_cost_monthly_escalation_percent']
            w_project_management_cost_monthly_escalation_factors = _soft_cost_results['pm']['w_project_management_cost_monthly_escalation_factors']
            w_project_management_cost_start_flag = _soft_cost_results['pm']['w_project_management_cost_start_flag']
            w_project_management_cost_monthly_escalation_factor_mapping = _soft_cost_results['pm']['w_project_management_cost_monthly_escalation_factor_mapping']
            w_project_management_cost_escalation_applicability_flag = _soft_cost_results['pm']['w_project_management_cost_escalation_applicability_flag']
            w_project_management_cost_escalation_applicability_flag_mapping = _soft_cost_results['pm']['w_project_management_cost_escalation_applicability_flag_mapping']
            o_project_management_cost_payment = _soft_cost_results['pm']['o_project_management_cost_payment']

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
                schedules=_get_assumption_value("s.landco.contingency.cost.phasing"),
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
                predefined_profile_names=_predefined_profile_names,
                predefined_profile_data=_predefined_profile_data,
                predefined_profile_durations=_predefined_profile_durations,
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
            _period_starts_dt = pd.to_datetime(_period_starts, errors="coerce")

            # Vectorized contingency cost start flag creation using broadcasting
            start_dates_arr = np.array(contingency_cost_start_dates).reshape(-1, 1)
            period_starts_arr = _period_starts_dt.to_numpy().reshape(1, -1)
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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
            _lease_start_dates_dt = pd.to_datetime(lease_start_dates, errors='coerce').to_numpy(dtype='datetime64[D]')
            _lease_end_dates_dt = pd.to_datetime(lease_end_dates, errors='coerce').to_numpy(dtype='datetime64[D]')
            _grace_period_end_dates_dt = pd.to_datetime(grace_period_end_dates, errors='coerce').to_numpy(dtype='datetime64[D]')
            # Create start date and end date arrays for broadcasting
            start_arr = _lease_start_dates_dt.reshape(-1, 1)
            lease_end_arr = _lease_end_dates_dt.reshape(-1, 1)
            grace_end_arr = _grace_period_end_dates_dt.reshape(-1, 1)
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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
                schedules=_get_assumption_value("s.landco.land.lease.occupancy"),
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
                schedules=_get_assumption_value("s.landco.land.lease.associated.operating.expenses"),
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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
                schedules=_get_assumption_value("s.landco.sales.phasing"),
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
                predefined_profile_names=_predefined_profile_names,
                predefined_profile_data=_predefined_profile_data,
                predefined_profile_durations=_predefined_profile_durations,
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

            allocation_basis_mapping = _allocation_basis_mapping
            cost_basis_mapping = _land_cost_basis_mapping

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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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

            allocation_basis_mapping = _allocation_basis_mapping
            cost_basis_mapping = _land_cost_basis_mapping
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
                escalation_profile_names=_escalation_profile_names,
                escalation_profile_data=_escalation_profile_data,
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

            _record_timing("Revenue Module")

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
                default_date = _default_date
                prefix_parameter_cache = {}

                # Build normalized attribute names once for all assets
                for loop_row_idx in template_index:
                    asset_class = asset_class_series[loop_row_idx]
                    sub_category = sub_category_series[loop_row_idx]
                    override = asset_cost_module.override[loop_row_idx]

                    # Normalize strings for attribute lookup
                    normalized_asset_class = (
                        asset_class.lower().replace(" ", "_").replace("[", "").replace("]", "")
                        if isinstance(asset_class, str) else ""
                    )
                    normalized_sub_category = (
                        sub_category.lower().replace(" ", "_").replace("[", "").replace("]", "")
                        if isinstance(sub_category, str) else ""
                    )

                    # Build attribute names
                    prefix = f"{normalized_asset_class}_{normalized_sub_category}" if normalized_sub_category else normalized_asset_class
                    
                    cached_prefix_parameters = prefix_parameter_cache.get(prefix)
                    if cached_prefix_parameters is None:
                        global_cost_start_option = getattr(global_cost_module, f"{prefix}_cost_start_option", "")
                        if global_cost_start_option == "Operation Start Date":
                            global_cost_start_date = default_date
                        elif global_cost_start_option == "Override":
                            global_cost_start_date = getattr(global_cost_module, f"{prefix}_cost_start_date", pd.NaT)
                        else:
                            global_cost_start_date = pd.NaT

                        cached_prefix_parameters = {
                            'cost_start_date': global_cost_start_date,
                            'cost_duration': getattr(global_cost_module, f"{prefix}_cost_duration", 0),
                            'cost_per_sqm': getattr(global_cost_module, f"{prefix}_cost_per_sqm", 0.0),
                            'cost_basis': getattr(global_cost_module, f"{prefix}_cost_basis", ""),
                            'escalation_profile': getattr(global_cost_module, f"{prefix}_escalation_profile", ""),
                            'payment_frequency': getattr(global_cost_module, f"{prefix}_payment_frequency", ""),
                            'recovery_duration': getattr(global_cost_module, f"{prefix}_recovery_duration", ""),
                            'recovery_advance': getattr(global_cost_module, f"{prefix}_recovery_advance", ""),
                            'recovery_default_rate': getattr(global_cost_module, f"{prefix}_default_rate", ""),
                        }
                        prefix_parameter_cache[prefix] = cached_prefix_parameters

                    # Apply override or global values
                    if override == "Yes":
                        params['cost_start_date'][loop_row_idx] = asset_cost_module.cost_start_date_override[loop_row_idx]
                        params['cost_duration'][loop_row_idx] = asset_cost_module.cost_duration[loop_row_idx]
                        params['cost_per_sqm'][loop_row_idx] = asset_cost_module.cost_per_sqm[loop_row_idx]
                        params['cost_basis'][loop_row_idx] = asset_cost_module.cost_basis[loop_row_idx]
                        params['escalation_profile'][loop_row_idx] = asset_cost_module.escalation_profile[loop_row_idx]
                        params['payment_frequency'][loop_row_idx] = asset_cost_module.payment_frequency[loop_row_idx]
                        params['recovery_duration'][loop_row_idx] = asset_cost_module.recovery_duration[loop_row_idx]
                        params['recovery_advance'][loop_row_idx] = asset_cost_module.recovery_advance[loop_row_idx]
                        params['recovery_default_rate'][loop_row_idx] = asset_cost_module.recovery_default_rate[loop_row_idx]
                    else:
                        params['cost_start_date'][loop_row_idx] = cached_prefix_parameters['cost_start_date']
                        params['cost_duration'][loop_row_idx] = cached_prefix_parameters['cost_duration']
                        params['cost_per_sqm'][loop_row_idx] = cached_prefix_parameters['cost_per_sqm']
                        params['cost_basis'][loop_row_idx] = cached_prefix_parameters['cost_basis']
                        params['escalation_profile'][loop_row_idx] = cached_prefix_parameters['escalation_profile']
                        params['payment_frequency'][loop_row_idx] = cached_prefix_parameters['payment_frequency']
                        params['recovery_duration'][loop_row_idx] = cached_prefix_parameters['recovery_duration']
                        params['recovery_advance'][loop_row_idx] = cached_prefix_parameters['recovery_advance']
                        params['recovery_default_rate'][loop_row_idx] = cached_prefix_parameters['recovery_default_rate']

                    # Calculate derived values
                    cost_duration_val = params['cost_duration'][loop_row_idx]
                    if pd.notna(cost_duration_val) and cost_duration_val > 0:
                        params['cost_end_date'][loop_row_idx] = params['cost_start_date'][loop_row_idx] + pd.DateOffset(months=int(cost_duration_val)-1)
                    
                    cost_basis_val = params['cost_basis'][loop_row_idx]
                    params['cost_basis_sqm'][loop_row_idx] = cost_basis_mapping.get(cost_basis_val, pd.Series(dtype='float64'))[loop_row_idx] if cost_basis_val in cost_basis_mapping else 0.0
                    params['annual_cost_amount'][loop_row_idx] = params['cost_per_sqm'][loop_row_idx] * params['cost_basis_sqm'][loop_row_idx]
                    params['monthly_cost_amount'][loop_row_idx] = params['annual_cost_amount'][loop_row_idx] / 12 if pd.notna(params['annual_cost_amount'][loop_row_idx]) else 0.0

                return params

            def fn_calculate_community_operations_flags_vectorized(params, model_timeline_me, template):
                """Vectorized flag calculation for all assets at once."""
                period_starts = model_timeline_me['Period Start'].values
                period_ends = model_timeline_me['Period End'].values
                period_months = model_timeline_me['Month'].values
                
                cost_start_dates = params['cost_start_date'].values.reshape(-1, 1)
                cost_end_dates = params['cost_end_date'].values.reshape(-1, 1)
                period_starts_arr = period_starts.reshape(1, -1)
                period_ends_arr = period_ends.reshape(1, -1)
                period_months_arr = period_months.reshape(1, -1)
                
                # Vectorized: (n_assets, n_periods) boolean masks via broadcasting
                cost_mask = (period_ends_arr >= cost_start_dates) & (period_starts_arr <= cost_end_dates)
                
                # Get month from start dates (vectorized)
                start_months = pd.to_datetime(cost_start_dates.ravel()).month.values.reshape(-1, 1)
                escalation_mask = cost_mask & (period_months_arr == start_months)
                
                cost_flag_df = pd.DataFrame(cost_mask.astype(int), index=template.index, columns=template.columns)
                escalation_flag_df = pd.DataFrame(escalation_mask.astype(int), index=template.index, columns=template.columns)
                unescalated_cost_df = pd.DataFrame(
                    np.where(cost_mask, params['monthly_cost_amount'].values.reshape(-1, 1), 0),
                    index=template.index, columns=template.columns
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

                payment_df = _create_zero_df()
                period_starts = model_timeline_me['Period Start']
                period_ends = model_timeline_me['Period End']

                for row_idx in template.index:
                    freq = params['payment_frequency'][row_idx]
                    start_date = params['cost_start_date'][row_idx]
                    end_date = params['cost_end_date'][row_idx]

                    if pd.isna(freq) or pd.isna(start_date) or freq not in frequency_months:
                        continue

                    freq_months = frequency_months[freq]

                    # Create mask for valid period
                    valid_mask = (period_ends >= start_date) & (period_starts <= end_date)
                    valid_cols = model_timeline_me.index[valid_mask]

                    if freq == "Monthly":
                        # Direct assignment for monthly
                        payment_df.loc[row_idx, valid_cols] = unescalated_cost_df.loc[row_idx, valid_cols]
                    else:
                        # For non-monthly frequencies
                        for col_idx in valid_cols:
                            period_start = period_starts[col_idx]
                            if (period_start.month - start_date.month) % freq_months == 0:
                                payment_period_end = period_start + pd.DateOffset(months=freq_months)
                                payment_cols = model_timeline_me[
                                    (model_timeline_me['Period Start'] >= period_start) &
                                    (model_timeline_me['Period Start'] < payment_period_end)
                                ].index
                                payment_df.loc[row_idx, col_idx] = unescalated_cost_df.loc[row_idx, payment_cols].sum()

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
                recovery_df = _create_zero_df()
                period_starts = model_timeline_me['Period Start'].values
                period_ends = model_timeline_me['Period End'].values
                col_indices = model_timeline_me.index

                for row_idx in template.index:
                    recovery_dur = params['recovery_duration'][row_idx]
                    recovery_adv = params['recovery_advance'][row_idx]
                    default_rate = params['recovery_default_rate'][row_idx]
                    start_date = params['cost_start_date'][row_idx]

                    # Validate default rate
                    if pd.isna(default_rate) or not isinstance(default_rate, (int, float)):
                        default_rate = 0

                    # Skip if invalid parameters
                    if pd.isna(recovery_dur) or pd.isna(recovery_adv) or pd.isna(start_date):
                        continue

                    # Calculate adjusted recovery duration
                    try:
                        adjusted_recovery_dur = float(recovery_dur) - float(recovery_adv)
                    except (TypeError, ValueError):
                        continue

                    if adjusted_recovery_dur <= 0:
                        continue

                    # Calculate recovery period dates
                    recovery_start_date = start_date + pd.DateOffset(months=int(recovery_adv))
                    recovery_end_date = recovery_start_date + pd.DateOffset(months=int(adjusted_recovery_dur) - 1)

                    # Create mask for recovery period
                    recovery_mask = (period_ends >= recovery_start_date) & (period_starts <= recovery_end_date)
                    recovery_cols = col_indices[recovery_mask]

                    # Calculate recovery amount
                    if len(recovery_cols) > 0:
                        monthly_costs = unescalated_cost_df.loc[row_idx, recovery_cols]
                        recovery_df.loc[row_idx, recovery_cols] = monthly_costs * (1 - default_rate)

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
                Returns: (cost_flag, unescalated_cost, escalation_flag, payment, recovery, escalation_profile)
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
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
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
                    params['escalation_profile']
                )
            
           


            # ============================================================================================
            # COMMUNITY OPERATIONS AMANAH MODULE (OPTIMIZED)
            # ============================================================================================

            cost_basis_mapping = _community_cost_basis_mapping

            def _run_community_operations_module(asset_cost_module, global_cost_module):
                (
                    _cost_flag,
                    _unescalated_cost,
                    _esc_flag,
                    _cost_payment,
                    _recovery,
                    _esc_profile
                ) = fn_calculate_community_operations(
                    asset_cost_module=asset_cost_module,
                    global_cost_module=global_cost_module,
                    asset_class_series=Asset.ProjectDetails.asset_class,
                    sub_category_series=Asset.ProjectDetails.sub_category,
                    cost_basis_mapping=cost_basis_mapping,
                    assumptions=assumptions,
                    model_timeline_me=model_timeline_me,
                    template=template_asset_timeline,
                    _create_zero_df_func=_create_zero_df
                )
                _esc_pct = _create_zero_df()
                _esc_factors = _create_zero_df()
                _esc_pct, _esc_factors = fn_calculate_monthly_escalation_profile(
                    escalation_percent_template=_esc_pct,
                    escalation_factor_template=_esc_factors,
                    selected_escalation_profile=_esc_profile,
                    escalation_profile_names=_escalation_profile_names,
                    escalation_profile_data=_escalation_profile_data,
                    model_timeline_me=model_timeline_me
                )
                return (_cost_flag, _unescalated_cost, _esc_flag, _cost_payment, _recovery, _esc_profile, _esc_pct, _esc_factors)

            # Run Amanah and ROSHN community operations concurrently via the shared executor.
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
                    schedules=_get_assumption_value(schedule_name),
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
            # PARALLEL CORPORATE OVERHEAD: 7 tasks via shared thread pool
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

            if _max_thread_workers > 1:
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
            
            return {
                "Land Acquisition Cost": o_land_acquisition_cost_cash_payment,
                "Primary Infrastructure Cost S-Curve": o_primary_infrastructure_cost_s_curve,
                "Secondary Infrastructure Cost S-Curve": o_secondary_infrastructure_cost_s_curve,
                "Design Cost": o_design_cost_payment,
                "Permitting Cost": o_permitting_cost_payment,
                "Supervision Cost": o_supervision_cost_payment,
                "Project Management Cost": o_project_management_cost_payment,
                "Capitalized Salaries Expenses": o_corporate_overheads_salaries_capitalized,
                "Capitalized IT Services Expenses": o_corporate_overheads_it_services_capitalized,
                "Capitalized Office Rent and Utilities Expenses": o_corporate_overheads_office_rent_and_utilities_capitalized,
                "Capitalized Professional Services Expenses": o_corporate_overheads_professional_services_capitalized,
                "Capitalized Marketing Expenses": o_corporate_overheads_marketing_capitalized,
                "Capitalized Sales Cost Expenses": o_corporate_overheads_sales_cost_capitalized,
                "Capitalized Additional Expenses": o_corporate_overheads_additional_expenses_capitalized,
            }
            
    except Exception as e:
        return print(f"Failed to initialise values {e}\n{traceback.format_exc()}")

def fninitialising_all_values(payload):
    """
    Entry point function that initializes and executes the cashflow model.
    
    This function serves as the public API entry point for the cashflow module.
    It wraps the main calculation function with error handling.
    
    Args:
        payload (list): JSON payload containing named ranges from Excel.
            Expected format: List of dicts with 'name' and 'values' keys.
            
    Returns:
        dict: Output from fn_wrapper_for_vars containing monthly and annual DataFrames.
        None: If an error occurs during initialization.
        
    Raises:
        Prints error message to console if initialization fails.
        >>> from landco_12_cashflow_module import fninitialising_all_values
        >>> result = fninitialising_all_values(excel_data)
    """
    try:
        output = wrapper_for_vars(payload)
        return output
    except Exception as e:
        print(f"Error in fninitialising_all_values: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise