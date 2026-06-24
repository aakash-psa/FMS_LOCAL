import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
from calendar import month
from contextlib import contextmanager
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import perm
from dateutil.relativedelta import relativedelta
import os
import re
import time

print ("Loading AssetCo Model v3...")

# Timing dictionary to track function execution times
_function_timings = {}

def timed_call(func, func_name=None):
    """Wrapper to time a function call and store the result."""
    name = func_name or func.__name__
    start = time.perf_counter()
    result = func()
    elapsed = time.perf_counter() - start
    _function_timings[name] = elapsed
    return result

def print_timing_summary():
    """Print summary of all timed function calls."""
    print("\n" + "=" * 60)
    print("FUNCTION TIMING SUMMARY")
    print("=" * 60)
    sorted_timings = sorted(_function_timings.items(), key=lambda x: x[1], reverse=True)
    total_time = sum(_function_timings.values())
    for name, elapsed in sorted_timings:
        pct = (elapsed / total_time * 100) if total_time > 0 else 0
        print(f"   {name:<45} {elapsed*1000:>8.2f} ms ({pct:>5.1f}%)")
    print("-" * 60)
    print(f"   {'TOTAL':<45} {total_time*1000:>8.2f} ms")
    print("=" * 60 + "\n")

def yearfrac_30_360(date1, date2):
    """Calculate year fraction using 30/360 (US NASD) day count convention.
    
    Each month is treated as 30 days, each year as 360 days.
    This matches Excel YEARFRAC(..., 0) behavior.
    
    Args:
        date1: Start date (e.g. acquisition date)
        date2: End date (e.g. period end or asset sale date)
    Returns:
        Year fraction as float
    """
    y1, m1, d1 = date1.year, date1.month, date1.day
    y2, m2, d2 = date2.year, date2.month, date2.day
    
    # Adjust day of month per 30/360 NASD rules
    if d1 == 31:
        d1 = 30
    if d2 == 31 and d1 >= 30:
        d2 = 30
    
    days_30_360 = (y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)
    return days_30_360 / 360.0

# ============================================================================================
# GLOBAL CLASS WITH SUBCLASSES
# ============================================================================================

class Global:

    # =========================================================
    # MODEL INPUTS
    # =========================================================
    class ModelInputs:
        analysis_type = None
        model_start_date = None
        model_duration = None
        model_end = None
        acquisition_date = None
        holding_period = None
        asset_sale_date = None
        operations_start = None
        fixed_spread = None

    # =========================================================
    # ASSET DETAILS
    # =========================================================
    class AssetDetails:
        devco_inclusion = None
        assetco_inclusion = None
        project_name = None
        asset_id = None
        asset_class = None
        asset_sub_category = None
        asset_address = None
        asset_longitude = None
        asset_latitude = None
        gfa_transferred_from_devco = None
        building_efficiency = None
        gla_sum_of_assetco_inputs = None
        jvjda_inclusion = None
        venture_type = None
        jv_name = None
        assetco_jv_inclusion = None

    # =========================================================
    # ACQUISITION MODULE
    # =========================================================
    class AcquisitionModule:
        acquisition_price = None
        transfer_tax__stamp_duty = None
        legal_fees = None
        brokerage = None
        due_diligence_costs = None

        acquisition_price_transaction_date = None
        transfer_tax__stamp_duty_transaction_date = None
        legal_fees_transaction_date = None
        brokerage_transaction_date = None
        due_diligence_costs_transaction_date = None

    # =========================================================
    # VALUATION PARAMETERS
    # =========================================================
    class ValuationParameters:
        stabilization = None
        residual_value = None
        discount_rate = None
        exit_yield = None
        terminal_year_escalation_type = None
        gross_rent_escalation = None
        opex_escalation = None
        noi_escalation = None
        noi_top_up = None
        noi_top_up_value = None
        disposal_cost = None
        market_rent = None
        structural_vacancy_allowance = None
        terminal_value_escalation_factor = None
        terminal_year_noi_escalation = None

    # =========================================================
    # NOI STABILIZATION ASSUMPTIONS
    # =========================================================
    class NOIStabalizationAssumptions:
        current_market_rent = None
        inflation_factor = None
        structural_vacancy_allowance = None

    # =========================================================
    # CAPITAL EXPENDITURE
    # =========================================================
    class CapitalExpenditure:
        # Input types (Actuals, Forecast, Actuals + Forecast)

        # Start dates
        maintenance_capex_1_start_date = None
        maintenance_capex_2_start_date = None
        maintenance_capex_3_start_date = None
        maintenance_capex_4_start_date = None

        # Duration in months
        maintenance_capex_1_capex_duration = None
        maintenance_capex_2_capex_duration = None
        maintenance_capex_3_capex_duration = None
        maintenance_capex_4_capex_duration = None

    # =========================================================
    # OPERATING EXPENSES
    # =========================================================
    class OperatingExpenses:
        # Input types
        asset_management_fees_input_type = None
        utilities_input_type = None
        facility_management_fees_input_type = None
        administration_cost_input_type = None
        marketing_cost_input_type = None
        insurance_input_type = None
        other_operating_expenses_input_type = None
        bad_debt_input_type = None
        void_period_cost_input_type = None

        # Cost types
        asset_management_fees_cost_type = None
        utilities_cost_type = None
        facility_management_fees_cost_type = None
        administration_cost_cost_type = None
        marketing_cost_cost_type = None
        insurance_cost_type = None
        other_operating_expenses_cost_type = None
        bad_debt_cost_type = None
        void_period_cost_cost_type = None

        # Cost per sqm
        asset_management_fees_cost_per_sqm = None
        utilities_cost_per_sqm = None
        facility_management_fees_cost_per_sqm = None
        administration_cost_cost_per_sqm = None
        marketing_cost_cost_per_sqm = None
        insurance_cost_per_sqm = None
        other_operating_expenses_cost_per_sqm = None
        bad_debt_cost_per_sqm = None
        void_period_cost_cost_per_sqm = None

        # Ad-hoc amounts
        asset_management_fees_ad_hoc_amount = None
        utilities_ad_hoc_amount = None
        facility_management_fees_ad_hoc_amount = None
        administration_cost_ad_hoc_amount = None
        marketing_cost_ad_hoc_amount = None
        insurance_ad_hoc_amount = None
        other_operating_expenses_ad_hoc_amount = None
        bad_debt_ad_hoc_amount = None
        void_period_cost_ad_hoc_amount = None

        # Percentage of lease revenue
        asset_management_fees_percentage_of_lease_revenue = None
        utilities_percentage_of_lease_revenue = None
        facility_management_fees_percentage_of_lease_revenue = None
        administration_cost_percentage_of_lease_revenue = None
        marketing_cost_percentage_of_lease_revenue = None
        insurance_percentage_of_lease_revenue = None
        other_operating_expenses_percentage_of_lease_revenue = None
        bad_debt_percentage_of_lease_revenue = None
        void_period_cost_percentage_of_lease_revenue = None

        # Start dates
        asset_management_fees_start_date = None
        utilities_start_date = None
        facility_management_fees_start_date = None
        administration_cost_start_date = None
        marketing_cost_start_date = None
        insurance_start_date = None
        other_operating_expenses_start_date = None
        bad_debt_start_date = None
        void_period_cost_start_date = None

        # Escalation profiles
        asset_management_fees_cost_escalation_profile = None
        utilities_cost_escalation_profile = None
        facility_management_fees_cost_escalation_profile = None
        administration_cost_cost_escalation_profile = None
        marketing_cost_cost_escalation_profile = None
        insurance_cost_escalation_profile = None
        other_operating_expenses_cost_escalation_profile = None
        bad_debt_cost_escalation_profile = None
        void_period_cost_cost_escalation_profile = None

    # =========================================================
    # SINKING FUND
    # =========================================================
    class SinkingFund:
        opex_type = None
        cost_type = None
        percentage_of_revenue_or_noi = None
        start_date = None

    # =========================================================
    # PARKING INCOME AND EXPENSES
    # =========================================================
    class ParkingIncomeandExpenses:
        revenue_type = None
        no_of_bays = None
        rate_per_month = None
        start_date = None
        occupancy_profile = None
        parking_rate_escalation = None
        parking_opex_type = None
        fixed_parking_opex = None
        parking_opex_annual_profile = None

    # =========================================================
    # OTHER INCOME AND EXPENSES
    # =========================================================
    class OtherIncomeandExpenses:
        # Input types
        other_income_1_input_type = None
        other_income_2_input_type = None
        other_income_3_input_type = None
        other_expense_1_input_type = None
        other_expense_2_input_type = None
        other_expense_3_input_type = None

        # High-level income/expense flags/labels
        other_income_1_incomeexpense = None
        other_income_2_incomeexpense = None
        other_income_3_incomeexpense = None
        other_expense_1_incomeexpense = None
        other_expense_2_incomeexpense = None
        other_expense_3_incomeexpense = None

        # % of gross revenue (input)
            # % of revenue or NOI
        other_income_1_percentage_of_revenue_or_noi = None
        other_income_2_percentage_of_revenue_or_noi = None
        other_income_3_percentage_of_revenue_or_noi = None
        other_expense_1_percentage_of_revenue_or_noi = None
        other_expense_2_percentage_of_revenue_or_noi = None
        other_expense_3_percentage_of_revenue_or_noi = None

        # per GLA / GFA
        other_income_1_incomeexpense_per_glagfa = None
        other_income_2_incomeexpense_per_glagfa = None
        other_income_3_incomeexpense_per_glagfa = None
        other_expense_1_incomeexpense_per_glagfa = None
        other_expense_2_incomeexpense_per_glagfa = None
        other_expense_3_incomeexpense_per_glagfa = None

        # Ad-hoc amounts
        other_income_1_ad_hoc_amount = None
        other_income_2_ad_hoc_amount = None
        other_income_3_ad_hoc_amount = None
        other_expense_1_ad_hoc_amount = None
        other_expense_2_ad_hoc_amount = None
        other_expense_3_ad_hoc_amount = None

        # Start dates
        other_income_1_start_date = None
        other_income_2_start_date = None
        other_income_3_start_date = None
        other_expense_1_start_date = None
        other_expense_2_start_date = None
        other_expense_3_start_date = None

        # Escalation profiles
        other_income_1_escalation_profile = None
        other_income_2_escalation_profile = None
        other_income_3_escalation_profile = None
        other_expense_1_escalation_profile = None
        other_expense_2_escalation_profile = None
        other_expense_3_escalation_profile = None

    # =========================================================
    # CAPITAL STRUCTURE
    # =========================================================
    class CapitalStructure:
        total_debt_ltv = None
        total_equity = None
        fixed_spread = None

    # =========================================================
    # FINANCING ASSUMPTIONS - LOAN 1
    # =========================================================
    class FinancingAssumptions_Loan1:
        loan_raise_date = None
        loan_term = None
        loan_end = None
        amortization_duration = None
        annual_amortization = None
        balloon_payment = None
        dscr = None
        base_interest_rate = None
        fixed_spread = None
        arrangement_fees = None
        loan_refinancing_ = None
        loan_refinancing_date = None

    # =========================================================
    # REFINANCING ASSUMPTIONS
    # =========================================================
    class RefinancingAssumptions:
        noi_top_up = None
        noi_at_refinance = None
        cap_rate_at_refinance = None
        valuation_at_refinance = None
        ltv = None
        ltv_max_loan = None
        min_dscr = None
        dscr_computed = None
        repayment_type = None
        loan_start = None
        loan_term = None
        loan_end = None
        amortization_duration = None
        annual_amortization = None
        balloon_payment = None
        refinance_interest_rate = None
        arrangement_fees = None


class Unit:

    class UnitInputs:
        sno = None
        asset_name = None
        asset_id = None
        asset_address = None
        asset_longitude = None
        asset_latitude = None
        unit_id = None
        unit_type = None
        sub_unit_type = None
        gross_leasable_area = None
        market_rent = None

    class TenantDetailsFirstTenant:
        tenant_id = None
        tenant_name = None
        sector = None

    class LeaseParametersFirstTenant:
        lease_start_date = None
        lease_tenure = None
        rent_free_duration = None
        cash_collection_start_date = None
        lease_expiration_date = None
        break_option_exercised = None
        break_option_date = None

    class SalesAssumptionsFirstTenantandRenewal:
        sales_turnover = None
        actual_sales_profile = None
        sales_density = None
        sales_growth_profile = None

    class RentParametersFirstTenant:
        agreement_type = None
        rent_input_type = None
        actual_base_rent = None
        forecast_base_rent = None
        escalation_basis = None
        lease_escalation_type = None
        fixed_escalation = None
        variable_escalation_profile = None
        lease_escalation_frequency = None
        service_charge_basis = None
        service_charge_percentage = None
        service_charge_sar_per_sqm = None
        sc_escalation = None
        leasing_commission = None
        tenant_fit_out_allowance = None
        payment_profilestenant_fit_out_allowance = None

    class TurnoverRent_FirstTenant:
        turnover_limit_1 = None
        turnover_rent__percent_1 = None
        turnover_limit_2 = None
        turnover_rent_percent_2 = None
        turnover_limit_3 = None
        turnover_rent_percent_3 = None
        ratchet_percentage = None
        turnover_actuals = None

    class LeaseExpirationTenant1:
        renewal_probability = None
        renewal = None
        void_period_months = None

    class LeaseParametersRenewal:
        lease_start_date = None
        lease_tenure = None
        rent_free_duration = None
        cash_collection_start_date = None
        lease_expiration_date = None
        break_option_exercised = None
        break_option_date = None

    class RentParametersRenewal:
        agreement_type = None
        rent_input_type = None
        actual_base_rent = None
        forecast_base_rent = None
        escalation_basis = None
        lease_escalation_type = None
        fixed_escalation = None
        variable_escalation_profile = None
        lease_escalation_frequency = None
        service_charge_basis = None
        service_charge_percentage = None
        service_charge_sar_per_sqm = None
        sc_escalation = None
        leasing_commission = None

    class TurnoverRentFirstTenantRenewal:
        turnover_limit_1 = None
        turnover_rent__percent_1 = None
        turnover_limit_2 = None
        turnover_rent_percent_2 = None
        turnover_limit_3 = None
        turnover_rent_percent_3 = None
        ratchet_percentage = None

    class SecondTenant:
        second_tenant = None
        void_period_months = None

    class TenantDetailsTenant2:
        tenant_id = None
        tenant_name = None
        sector = None

    class LeaseParametersSecondTenant:
        lease_start_date = None
        lease_tenure = None
        rent_free_duration = None
        cash_collection_start_date = None
        lease_expiration_date = None
        break_option_exercised = None
        break_option_date = None

    class SalesAssumptionsSecondTenant:
        sales_turnover = None
        actual_sales_profile = None
        sales_density = None
        sales_growth_profile = None

    class RentParametersSecondTenant:
        agreement_type = None
        rent_input_type = None
        actual_base_rent = None
        forecast_base_rent = None
        escalation_basis = None
        lease_escalation_type = None
        fixed_escalation = None
        variable_escalation_profile = None
        lease_escalation_frequency = None
        service_charge_basis = None
        service_charge_percentage = None
        service_charge_sar_per_sqm = None
        sc_escalation = None
        leasing_commission = None
        tenant_fit_out_allowance = None
        payment_profilestenant_fit_out_allowance = None

    class TurnoverRentSecondTenant:
        turnover_limit_1 = None
        turnover_rent__percent_1 = None
        turnover_limit_2 = None
        turnover_rent_percent_2 = None
        turnover_limit_3 = None
        turnover_rent_percent_3 = None
        ratchet_percentage = None
        turnover_actuals = None


def wrapper_for_vars(payload,is_save):
    try:
        
        # NORMAL MODE: Load data from Excel payload
        # print("Initializing AssetCo Model v3 variables...")
        # =============================================================================
        # MODULE STATE HOLDERS (must be defined FIRST before any other code)
        # =============================================================================
        class ModuleState:
            """Container for module state variables."""
            def __init__(self):
                self.assumptions = None
                self.model_timeline_me = None
                self.model_timeline_ye = None
                self.template_asset_timeline = None
                self.all_tenant_results = None
                self.all_turnover_results = None
                self._num_assets = None
                self._num_periods = None
                self._period_starts_ts = None
                self._period_ends_ts = None
        
        # Create module state instances
        mod02 = ModuleState()
        mod03 = ModuleState()
        mod04 = ModuleState()
        brm = ModuleState()
        tor = ModuleState()
        toi = ModuleState()
        opex = ModuleState()
        oie = ModuleState()
        mcapex = ModuleState()
        iam = ModuleState()
        
        # Initialize module-level variables
        _num_assets = None
        _num_periods = None
        _period_starts_ts = None
        _period_ends_ts = None
        _period_starts = None
        _period_ends = None
        _num_years = None
        
        # Initialize line item variables
        operations_line_items = []
        investment_line_items = []
        financing_line_items = []
        cashflow_results = {}
        
        
        computation_cache = {}
        local_cache = {}
        profile_cache = {}
        flag_cache = {}
        period_cache = {}
        parallel_timing_log = defaultdict(list)
        cache_log_enabled = True
        parallel_depth = 0

        def _cap_workers(requested, hard_max=None):
            cpu_count = os.cpu_count() or 1
            max_allowed = cpu_count if hard_max is None else min(cpu_count, hard_max)
            return max(1, min(requested, max_allowed))

        def _reset_run_cache():
            computation_cache.clear()
            local_cache.clear()
            profile_cache.clear()
            flag_cache.clear()
            period_cache.clear()
            parallel_timing_log.clear()

        def _local_cache_get(cache, key):
            return cache.get(key)

        def _local_cache_set(cache, key, value):
            cache[key] = value
            return value

        def _local_cache_get_or_set(cache, key, factory):
            if key not in cache:
                cache[key] = factory()
            return cache[key]

        _reset_run_cache()

        def _record_parallel_timing(label, duration):
            if duration is None:
                return
            parallel_timing_log[label].append(duration)

        def _is_parallel_active():
            return parallel_depth > 0

        @contextmanager
        def _parallel_section():
            nonlocal parallel_depth
            parallel_depth += 1
            try:
                yield
            finally:
                parallel_depth = max(0, parallel_depth - 1)

        def _print_parallel_timing_summary():
            if not parallel_timing_log:
                return
            print("\n======================================================================")
            print("PARALLEL EXECUTION SNAPSHOT")
            print("======================================================================")
            for label, entries in parallel_timing_log.items():
                last = entries[-1]
                avg = sum(entries) / len(entries)
                print(f"   {label}: last={last:.3f}s avg={avg:.3f}s n={len(entries)}")
            print("======================================================================\n")

        def _cache_get(key):
            return computation_cache.get(key)

        def _cache_set(key, value):
            computation_cache[key] = value
            return value

        def _cache_get_or_set(key, factory):
            if key not in computation_cache:
                if cache_log_enabled:
                    print(f"   [CACHE MISS] {key}")
                computation_cache[key] = factory()
            else:
                if cache_log_enabled:
                    print(f"   [CACHE HIT]  {key}")
            return computation_cache[key]

        def _get_tenant_other_inputs_results():
            return _cache_get_or_set(
                "module:tenant_other_inputs", fn_compute_all_tenant_other_inputs
            )

        def _get_other_income_expense_results():
            return _cache_get_or_set(
                "module:other_income_expenses", fn_compute_all_other_income_expenses
            )

        def _get_operating_expense_results():
            return _cache_get_or_set(
                "module:operating_expenses", fn_compute_all_operating_expenses
            )

        def _get_maintenance_capex_results():
            return _cache_get_or_set(
                "module:maintenance_capex",
                fn_compute_all_maintenance_capex_and_sinking_fund,
            )

        def fn_read_all_named_ranges_json(payload):
            """
                Reads named ranges from a JSON input and returns a DataFrame with columns ['name', 'value'].
                The JSON is expected to be a list of dicts with keys: 'name', 'values', etc.
                - Single-cell: values[[single_value]]
                - Single-row: values[[v1, v2, ...]]
                - Single-col: values[[v1],[v2],...]
                - Multi-cell: values[r][c]
                """
            # Deduplicate: when a named range appears at both workbook-scope and
            # worksheet-scope, keep the entry with the most data (largest row count).
            # This prevents stale workbook-scope definitions (e.g. 50 rows) from
            # shadowing correct worksheet-scope ones (e.g. 75 rows).
            deduped = {}  # name -> (name, value)
            for entry in payload:
               
                name = entry.get("name")
                if 'assetco' not in name.lower():
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
                    elif all(
                            isinstance(item, list) and len(item) == 1 for item in values
                    ):
                        # Single column, multiple rows: [[a],[b],[c]]
                        value = [item[0] for item in values]
                    else:
                        # Fallback: keep as is (likely a 2d multi-cell range)
                        value = values
                else:
                    value = values

                # Deduplicate: keep the entry with the larger data size
                def _data_size(v):
                    if isinstance(v, list):
                        return len(v)
                    return 1

                if name in deduped:
                    existing_value = deduped[name][1]
                    if _data_size(value) > _data_size(existing_value):
                        deduped[name] = (name, value)
                else:
                    deduped[name] = (name, value)

            named_values = list(deduped.values())

            return pd.DataFrame(named_values, columns=["name", "value"])

        assumptions = fn_read_all_named_ranges_json(payload)

        # Diagnostic: dump all assumption names containing "interest" or "rate"
        _all_assumption_names = sorted(assumptions["name"].unique().tolist()) if not assumptions.empty else []
        _interest_rate_names = [n for n in _all_assumption_names if "interest" in str(n).lower() or ("rate" in str(n).lower() and "assetco" in str(n).lower())]
        if _interest_rate_names:
            print(f"\n--- Assumptions containing 'interest' or 'rate': {_interest_rate_names} ---")
        else:
            print(f"\n--- No assumptions found containing 'interest' or 'rate'. Total named ranges: {len(_all_assumption_names)} ---")
            # Print ALL assetco named ranges to help debug
            _assetco_names = [n for n in _all_assumption_names if "assetco" in str(n).lower()]
            print(f"    All assetco named ranges ({len(_assetco_names)}): {_assetco_names}")

        def fn_assign_global_class_attributes(cls, assumptions):
            try:
                class_names_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.global.class", "value"
                ]
                if class_names_result.empty:
                    return
                class_names = class_names_result.iloc[0]
                
                attr_names_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.global.attribute", "value"
                ]
                if attr_names_result.empty:
                    return
                attr_names = attr_names_result.iloc[0]
                
                attr_values_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.global.value", "value"
                ]
                if attr_values_result.empty:
                    return
                attr_values = attr_values_result.iloc[0]
            except Exception:
                return
            
            class_name = cls.__name__
            
            # Map Python class names to Excel class names (Global classes)
            # Excel uses hyphens/spaces, Python uses underscores
            global_class_name_map = {
                "FinancingAssumptions_Loan1": "FinancingAssumptions-Loan1",
            }
            
            mapped_name = global_class_name_map.get(class_name, class_name)
            attrs_populated = 0
            
            # Collect unique class names from Excel data for diagnostics
            unique_excel_classes = set(class_names) if isinstance(class_names, list) else set()
            
            # Get min length to avoid index errors
            min_len = min(len(attr_names), len(class_names), len(attr_values))
            
            # Try exact match first
            found_exact = any(cn == mapped_name for cn in class_names[:min_len])
            
            # If no exact match, try fuzzy matching (strip spaces, case-insensitive)
            fuzzy_mapped_name = None
            if not found_exact:
                mapped_lower = mapped_name.lower().replace(" ", "").replace("-", "").replace("_", "")
                for cn in unique_excel_classes:
                    if isinstance(cn, str):
                        cn_lower = cn.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
                        if cn_lower == mapped_lower:
                            fuzzy_mapped_name = cn
                            print(f"   ⚠️ Global.{class_name}: fuzzy matched Excel class '{cn}' (expected '{mapped_name}')")
                            break
                if fuzzy_mapped_name is None and class_name != mapped_name:
                    # Try the original Python class name too
                    class_lower = class_name.lower().replace(" ", "").replace("-", "").replace("_", "")
                    for cn in unique_excel_classes:
                        if isinstance(cn, str):
                            cn_lower = cn.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
                            if cn_lower == class_lower:
                                fuzzy_mapped_name = cn
                                print(f"   ⚠️ Global.{class_name}: fuzzy matched Excel class '{cn}' (expected '{mapped_name}')")
                                break
            
            effective_name = fuzzy_mapped_name if fuzzy_mapped_name else mapped_name

            # Build a fuzzy lookup: normalised Python attr name → actual attr name
            _cls_attrs = [a for a in dir(cls) if not a.startswith('_') and not callable(getattr(cls, a, None))]
            _attr_norm_map = {}  # norm_key → python_attr_name
            for _a in _cls_attrs:
                _norm = _a.lower().replace(" ", "").replace("-", "").replace("_", "")
                _attr_norm_map[_norm] = _a

            for i, attr in enumerate(attr_names):
                # Bounds check
                if i >= min_len:
                    break
                    
                # Error control: check if class name matches for this attribute
                if class_names[i] != effective_name:
                    continue

                # Resolve attribute name: try exact first, then fuzzy
                resolved_attr = None
                if hasattr(cls, attr):
                    resolved_attr = attr
                else:
                    # Fuzzy match: normalise Excel attr and look up
                    if isinstance(attr, str):
                        attr_norm = attr.lower().replace(" ", "").replace("-", "").replace("_", "")
                        if attr_norm in _attr_norm_map:
                            resolved_attr = _attr_norm_map[attr_norm]

                if resolved_attr is None:
                    # Skip attributes not defined in class
                    continue

                # Check if the attribute name contains "date" and the value is an integer or float
                date_exceptions = [
                    # Add other exceptions here if needed
                ]

                # Attributes that hold dates but don't have "date" in name
                known_date_attrs = {
                    "loan_end", "repayment_start", "loan_start",
                }

                is_date_attr = ("date" in resolved_attr.lower() or resolved_attr in known_date_attrs)
                is_excel_serial = isinstance(attr_values[i], (int, float)) and 25000 < float(attr_values[i]) < 100000

                if is_date_attr and is_excel_serial and resolved_attr not in date_exceptions:
                    convertedval = datetime.fromtimestamp(
                        (attr_values[i] - 25569) * 86400.0
                    ).strftime("%Y-%m-%d")
                    setattr(cls, resolved_attr, pd.to_datetime(convertedval))
                else:
                    # Set attribute value directly
                    setattr(cls, resolved_attr, attr_values[i])
                attrs_populated += 1
            
            if attrs_populated > 0:
                print(f"   ✅ Global.{class_name}: loaded {attrs_populated} attributes (matched as '{effective_name}')")
            else:
                # Extra diagnostics: show what Excel has for this class
                _matching_rows = [(i, attr_names[i], attr_values[i]) for i in range(min_len) if class_names[i] == effective_name]
                _fuzzy_rows = []
                if not _matching_rows:
                    _eff_norm = effective_name.lower().replace(" ", "").replace("-", "").replace("_", "")
                    _fuzzy_rows = [(i, class_names[i], attr_names[i], attr_values[i]) for i in range(min_len) 
                                   if isinstance(class_names[i], str) and class_names[i].lower().replace(" ", "").replace("-", "").replace("_", "") == _eff_norm]
                print(f"   ❌ Global.{class_name}: 0 attributes loaded! Expected class '{effective_name}'. Exact rows={len(_matching_rows)}, Fuzzy rows={len(_fuzzy_rows)}")
                if _fuzzy_rows:
                    print(f"      Fuzzy class match found but exact failed! Excel class='{_fuzzy_rows[0][1]}'")
                print(f"      Available classes: {sorted(unique_excel_classes)}")
                


        def fn_initialize_global_class(assumptions):
            # Dynamically retrieve all subclasses of the Global class
            for subclass_name in dir(Global):
                if subclass_name.startswith('_'):
                    continue  # Skip dunder/private attributes (e.g. __class__ → type)
                subclass = getattr(Global, subclass_name)
                # Check if the attribute is a class (subclass of Global)
                if isinstance(subclass, type):
                    fn_assign_global_class_attributes(subclass, assumptions)

        # Assign values to class attributes

        def fn_assign_asset_class_attributes(cls, assumptions):
            try:
                class_names_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.inputs.class.row", "value"
                ]
                if class_names_result.empty:
                    return
                class_names = class_names_result.iloc[0]
                
                attr_names_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.attributes.row", "value"
                ]
                if attr_names_result.empty:
                    return
                attr_names = attr_names_result.iloc[0]
                
                attr_values_result = assumptions.loc[
                    assumptions["name"] == "a.assetco.units.data", "value"
                ]
                if attr_values_result.empty:
                    return
                attr_values = attr_values_result.iloc[0]
                
            except Exception:
                return

            class_name = cls.__name__
            
            # Map Python class names to Excel class names
            # Excel names DO NOT have spaces - they match Python names exactly EXCEPT:
            # - UnitInputs in Python is "ProjectDetails" in Excel
            class_name_map = {
                "UnitInputs": "ProjectDetails",
            }
            if class_name in class_name_map:
                mapped_name = class_name_map[class_name]
            else:
                mapped_name = class_name
            
            # Count how many attributes we populate
            attrs_populated = 0
            
            # Build fuzzy lookup map: normalized attr name → actual Python attr name
            _attr_norm_map = {}
            for _a in dir(cls):
                if _a.startswith('_') or callable(getattr(cls, _a)):
                    continue
                _norm = _a.lower().replace(" ", "").replace("-", "").replace("_", "")
                _attr_norm_map[_norm] = _a
            
            # Get min length for bounds checking
            min_len = min(len(attr_names), len(class_names))
            
            for i, attr in enumerate(attr_names):
                # Bounds check
                if i >= min_len:
                    break
                    
                if class_names[i] != mapped_name:
                    continue
                
                # Resolve attribute name: try exact first, then fuzzy
                resolved_attr = None
                if hasattr(cls, attr):
                    resolved_attr = attr
                elif isinstance(attr, str):
                    attr_norm = attr.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if attr_norm in _attr_norm_map:
                        resolved_attr = _attr_norm_map[attr_norm]
                
                if resolved_attr is None:
                    continue

                # Check if the attribute name contains "date" and the value is an integer or float
                column_values = []
                for row in attr_values:
                    # Bounds check: ensure index i is within row length
                    if i >= len(row):
                        column_values.append(None)
                        continue
                    
                    if "date" in resolved_attr.lower() and isinstance(row[i], (int, float)):
                        if row[i] < 25569:
                            column_values.append(None)
                        else:
                            convertedval = datetime.fromtimestamp(
                                (row[i] - 25569) * 86400.0
                            ).strftime("%Y-%m-%d")
                            # Convert to datetime
                            column_values.append(pd.to_datetime(convertedval))
                    elif row[i] == "":
                        column_values.append(None)
                    else:
                        # Set attribute value directly
                        column_values.append(row[i])
                setattr(cls, resolved_attr, column_values)
                attrs_populated += 1
            
            if attrs_populated > 0:
                pass  # {class_name}: loaded
            elif mapped_name != class_name:
                pass  # {class_name} (mapped): 0 attributes


        def fn_initialize_asset_class(assumptions):
            for subclass_name in dir(Unit):
                subclass = getattr(Unit, subclass_name)
                if isinstance(subclass, type):
                    fn_assign_asset_class_attributes(subclass, assumptions)


        def fn_print_all_inputs():
            """Print all Global and Unit class inputs for debugging."""
            print("\n" + "=" * 80)
            print("DEBUG: ALL CLASS INPUTS AFTER INITIALIZATION")
            print("=" * 80)
            
            # Print Global class inputs
            print("\n--- GLOBAL CLASS ---")
            for subclass_name in dir(Global):
                subclass = getattr(Global, subclass_name)
                if isinstance(subclass, type):
                    print(f"\n  {subclass_name}:")
                    for attr_name in dir(subclass):
                        if not attr_name.startswith('_'):
                            val = getattr(subclass, attr_name)
                            if not callable(val):
                                if val is not None:
                                    if isinstance(val, list):
                                        print(f"    {attr_name}: [{len(val)} items] first={val[0] if val else None}")
                                    else:
                                        print(f"    {attr_name}: {val}")
            
            # Print Unit class inputs (sample first asset)
            print("\n--- UNIT CLASS (Sample: Asset 0) ---")
            for subclass_name in dir(Unit):
                subclass = getattr(Unit, subclass_name)
                if isinstance(subclass, type):
                    print(f"\n  {subclass_name}:")
                    attrs_with_values = 0
                    for attr_name in dir(subclass):
                        if not attr_name.startswith('_'):
                            val = getattr(subclass, attr_name)
                            if not callable(val):
                                if val is not None and isinstance(val, list) and len(val) > 0:
                                    print(f"    {attr_name}: {val[0]}")
                                    attrs_with_values += 1
                                elif val is None:
                                    pass  # Skip None values for brevity
                    if attrs_with_values == 0:
                        print(f"    (no data loaded)")
            
            print("\n" + "=" * 80)

        fn_initialize_global_class(assumptions)
        fn_initialize_asset_class(assumptions)

        # Print financing-related Global attributes for debugging
        print("\n" + "=" * 80)
        print("DEBUG: FINANCING GLOBAL INPUTS AFTER INITIALIZATION")
        print("=" * 80)
        print(f"  CapitalStructure.total_debt_ltv:          {Global.CapitalStructure.total_debt_ltv}")
        print(f"  CapitalStructure.total_equity:            {Global.CapitalStructure.total_equity}")
        print(f"  FinancingAssumptions_Loan1 attributes:")
        for attr in dir(Global.FinancingAssumptions_Loan1):
            if not attr.startswith('_'):
                val = getattr(Global.FinancingAssumptions_Loan1, attr)
                if not callable(val):
                    print(f"    {attr}: {val}")
        print(f"  RefinancingAssumptions attributes:")
        for attr in dir(Global.RefinancingAssumptions):
            if not attr.startswith('_'):
                val = getattr(Global.RefinancingAssumptions, attr)
                if not callable(val):
                    print(f"    {attr}: {val}")
        print("=" * 80)

        # Safety check: Ensure Unit.UnitInputs.sno is populated
        if Unit.UnitInputs.sno is None:
            raise ValueError(
                "Unit.UnitInputs.sno was not populated. Check that 'a.assetco.attributes.row' and "
                "'a.assetco.units.data' named ranges exist in the payload."
            )

        def fn_create_model_timeline(start_date, end_date, frequency):
            """
                Create a timeline DataFrame for monthly-end (ME), quarter-end (QE) or year-end (YE) periods.
                """
            freq_map_date_range = {"ME": "ME", "QE": "QE", "YE": "YE"}
            freq_map_period = {"ME": "M", "QE": "Q", "YE": "Y"}
            if frequency not in freq_map_date_range:
                raise ValueError("Unsupported frequency. Use 'ME', 'QE' or 'YE'.")

            pandas_freq_date_range = freq_map_date_range[frequency]
            pandas_freq_period = freq_map_period[frequency]
            date_range = pd.date_range(
                start=start_date, end=end_date, freq=pandas_freq_date_range
            )

            # Convert to PeriodIndex for robust period start/end and day counts
            periods = date_range.to_period(pandas_freq_period)
            period_start = periods.start_time
            period_end = periods.end_time
            number_of_days = (period_end - period_start).days + 1

            df = pd.DataFrame(
                {
                    "Period Start": period_start,
                    "Period End": period_end,
                    "Year": period_end.year,
                    "Month": period_end.month,
                    "# of Days": number_of_days,
                }
            )
            df["# of Period"] = df.index + 1

            # Reorder columns to make '# of Period' the 5th column
            df = df[
                [
                    "Period Start",
                    "Period End",
                    "Year",
                    "Month",
                    "# of Period",
                    "# of Days",
                ]
            ]

            return df

        # Helper to convert Excel serial number to datetime
        def _excel_serial_to_datetime(val):
            """Convert Excel serial number to datetime, or pass through if already datetime."""
            if val is None or pd.isna(val):
                return None
            if isinstance(val, (int, float)) and val > 25569:  # Excel serial numbers are > 25569 for dates after 1970
                from datetime import datetime
                return pd.Timestamp(datetime.fromtimestamp((val - 25569) * 86400.0))
            return pd.Timestamp(val)

        # Ensure model_start_date is the first day of the month
        Global.ModelInputs.model_start_date = _excel_serial_to_datetime(
            Global.ModelInputs.model_start_date
        )
        if Global.ModelInputs.model_start_date:
            Global.ModelInputs.model_start_date = Global.ModelInputs.model_start_date.replace(day=1)

        # Ensure model_end is the last day of the month
        Global.ModelInputs.model_end = _excel_serial_to_datetime(
            Global.ModelInputs.model_end
        )
        if Global.ModelInputs.model_end:
            Global.ModelInputs.model_end = Global.ModelInputs.model_end + pd.offsets.MonthEnd(0)
        
        # Ensure acquisition_date and asset_sale_date are properly formatted if they exist
        if Global.ModelInputs.acquisition_date:
            Global.ModelInputs.acquisition_date = _excel_serial_to_datetime(Global.ModelInputs.acquisition_date)
        if Global.ModelInputs.asset_sale_date:
            Global.ModelInputs.asset_sale_date = _excel_serial_to_datetime(Global.ModelInputs.asset_sale_date)
            if Global.ModelInputs.asset_sale_date:
                Global.ModelInputs.asset_sale_date = Global.ModelInputs.asset_sale_date + pd.offsets.MonthEnd(0)
        
        # Convert operations_start if it's an Excel serial
        if Global.ModelInputs.operations_start:
            Global.ModelInputs.operations_start = _excel_serial_to_datetime(Global.ModelInputs.operations_start)
        
        model_timeline_me = fn_create_model_timeline(
            Global.ModelInputs.model_start_date,
            Global.ModelInputs.model_end,
            "ME",
        )
        model_timeline_ye = fn_create_model_timeline(
            Global.ModelInputs.model_start_date,
            Global.ModelInputs.model_end,
            "YE",
        )
        model_timeline_qe = fn_create_model_timeline(
            Global.ModelInputs.model_start_date,
            Global.ModelInputs.model_end,
            "QE",
        )
        # number_of_assets = assumptions.loc[
        #     assumptions["name"] == "a.number.of.assets", "value"
        # ].iloc[0]
        number_of_assets = len(Unit.UnitInputs.sno)

        # Create empty DataFrame with assets as rows and timeline periods as columns
        timeline_periods = model_timeline_me["# of Period"]
        template_asset_timeline = pd.DataFrame(
            0.0,
            index=range(0, len(Unit.UnitInputs.sno), 1),
            columns=model_timeline_me.index,
        )

        # Step 2: Initialize module variables
        _period_starts = model_timeline_me["Period Start"].values
        _period_ends = model_timeline_me["Period End"].values
        _num_periods = len(model_timeline_me)
        _num_assets = len(Unit.UnitInputs.sno)
        _period_starts_ts = [pd.Timestamp(x) for x in _period_starts]
        _period_ends_ts = [pd.Timestamp(x) for x in _period_ends]

        # ---- KEY INPUT DIAGNOSTICS ----
        print(f"\n   [INPUT CHECK] Key model inputs:")
        print(f"      model_start_date:   {Global.ModelInputs.model_start_date}")
        print(f"      model_end:          {Global.ModelInputs.model_end}")
        print(f"      acquisition_date:   {Global.ModelInputs.acquisition_date}")
        print(f"      asset_sale_date:    {Global.ModelInputs.asset_sale_date}")
        print(f"      operations_start:   {Global.ModelInputs.operations_start}")
        print(f"      analysis_type:      {Global.ModelInputs.analysis_type}")
        print(f"      holding_period:     {Global.ModelInputs.holding_period}")
        print(f"      num_periods (ME):   {_num_periods}")
        print(f"      num_assets:         {_num_assets}")
        print(f"      total_debt_ltv:     {Global.CapitalStructure.total_debt_ltv}")
        print(f"      acq_price input:    {Global.AcquisitionModule.acquisition_price}")


        # =============================================================================
        # VALID PERIOD FLAG - Ensures no cashflows before acquisition or after sale
        # =============================================================================
        # This flag is 1 for periods where cashflows are valid, 0 otherwise
        # All cashflow outputs should be multiplied by this flag
        
        _acquisition_date = Global.ModelInputs.acquisition_date
        _asset_sale_date = Global.ModelInputs.asset_sale_date
        
        # Create validity flag array (1 = valid period, 0 = invalid)
        _valid_period_flag = np.ones(_num_periods)
        
        for col_idx in range(_num_periods):
            period_start = _period_starts_ts[col_idx]
            period_end = _period_ends_ts[col_idx]
            
            # Period is INVALID if it ends BEFORE acquisition date
            if _acquisition_date and period_end < _acquisition_date:
                _valid_period_flag[col_idx] = 0
            
            # Period is INVALID if it starts AFTER asset sale date
            if _asset_sale_date and period_start > _asset_sale_date:
                _valid_period_flag[col_idx] = 0
        
        # Valid period flag computed

        def apply_valid_period_flag(cashflow_array):
            """
            Apply the valid period flag to a cashflow array.
            Sets cashflows to 0 for periods before acquisition or after asset sale.
            Works with both 1D arrays (single unit) and 2D arrays (all units).
            """
            if cashflow_array is None:
                return cashflow_array
            arr = np.array(cashflow_array)
            if arr.ndim == 1:
                # Single unit array: shape (_num_periods,)
                return arr * _valid_period_flag
            elif arr.ndim == 2:
                # Multi-unit array: shape (num_units, _num_periods)
                return arr * _valid_period_flag  # Broadcasting applies flag to each row
            return cashflow_array

        # # print(Global.ModelInputs.model_start_date, Global.ModelInputs.asset_sale_date)

        # =============================================================================
        # DATE BOUNDARY MASKS - Enforce valid date ranges for each module
        # These masks are applied in the fn_get_* output functions so that
        # constraints hold regardless of input type (Actuals/Forecast/both).
        # =============================================================================

        _operations_start = Global.ModelInputs.operations_start
        if _operations_start and not pd.isna(_operations_start):
            _operations_start = pd.to_datetime(_operations_start)
        else:
            _operations_start = None

        def _make_date_mask(earliest=None, latest=None):
            """
            Build a 0/1 numpy mask over _num_periods.
            A period is valid (1) when:
              - period_start >= earliest  (if earliest is given)
              - period_start <= latest    (if latest is given)
            """
            mask = np.ones(_num_periods)
            for col_idx in range(_num_periods):
                ps = _period_starts_ts[col_idx]
                pe = _period_ends_ts[col_idx]
                if earliest is not None and pe < earliest:
                    mask[col_idx] = 0
                if latest is not None and ps > latest:
                    mask[col_idx] = 0
            return mask

        # Pre-operating: acquisition_date <= period < operations_start
        _mask_pre_operating = _make_date_mask(
            earliest=_acquisition_date,
            latest=(_operations_start - pd.DateOffset(days=1)) if _operations_start else _asset_sale_date
        )
        # Also zero out any period whose start is >= operations_start
        if _operations_start:
            for _i in range(_num_periods):
                if _period_starts_ts[_i] >= _operations_start:
                    _mask_pre_operating[_i] = 0

        # Opex: acquisition_date <= period <= asset_sale_date
        _mask_opex = _make_date_mask(
            earliest=_acquisition_date,
            latest=_asset_sale_date
        )

        # Parking revenue/expense: acquisition_date <= period <= asset_sale_date
        _mask_parking = _make_date_mask(
            earliest=_acquisition_date,
            latest=_asset_sale_date
        )

        # Maintenance capex: acquisition_date <= period <= asset_sale_date
        _mask_capex = _make_date_mask(
            earliest=_acquisition_date,
            latest=_asset_sale_date
        )

        # Sinking fund: same as capex (start_date already handled inside compute,
        # but we enforce asset_sale_date here)
        _mask_sinking_fund = _mask_capex

        # Other income/expenses: acquisition_date <= period <= asset_sale_date
        _mask_other_ie = _make_date_mask(
            earliest=_acquisition_date,
            latest=_asset_sale_date
        )

        # Void period cost: operations_start <= period <= asset_sale_date
        # Void period opex should NOT appear between acquisition and operations start
        _mask_void_period = _make_date_mask(
            earliest=_operations_start if _operations_start else _acquisition_date,
            latest=_asset_sale_date
        )

        def _apply_mask(series_or_array, mask):
            """Apply a 0/1 mask to a Series or ndarray, returning a Series."""
            if series_or_array is None:
                return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            if isinstance(series_or_array, pd.Series):
                return pd.Series(series_or_array.values * mask, index=series_or_array.index)
            arr = np.array(series_or_array)
            return pd.Series(arr * mask, index=range(_num_periods))


        # =============================================================================
        # TENANT TYPE CONFIGURATION
        # =============================================================================

        def fn_get_tenant_config():
            """Get tenant configuration after Unit class is initialized."""
            return {
                "tenant1": {
                    "lease_params": Unit.LeaseParametersFirstTenant,
                    "rent_params": Unit.RentParametersFirstTenant,
                    "actual_rent_name": "s.assetco.t1.actual.base.rent",
                },
                "renewal": {
                    "lease_params": Unit.LeaseParametersRenewal,
                    "rent_params": Unit.RentParametersRenewal,
                    "actual_rent_name": "s.assetco.t1.renewal.actual.base.rent",
                },
                "tenant2": {
                    "lease_params": Unit.LeaseParametersSecondTenant,
                    "rent_params": Unit.RentParametersSecondTenant,
                    "actual_rent_name": "s.assetco.t2.actual.base.rent",
                },
            }


        def fn_safe_get(lst, idx, default=None):
            """Safely get an element from a list, returning default if list is None or index out of range."""
            if lst is None:
                return default
            try:
                val = lst[idx]
                return val if val is not None and not pd.isna(val) else default
            except (IndexError, TypeError):
                return default


        def fn_normalize_probability(prob_value, default=1.0):
            """
            Normalize a probability value to be between 0 and 1.
            
            Handles multiple formats:
            - Decimal format: 0.75 → 0.75
            - Percentage number: 75 → 0.75
            - Percentage string: "75%" or "75 %" → 0.75
            
            Returns: float between 0.0 and 1.0
            """
            if prob_value is None or pd.isna(prob_value):
                return default
            
            # Handle string formats like "50%" or "50 %"
            if isinstance(prob_value, str):
                prob_str = prob_value.strip()
                # Remove % symbol if present
                if '%' in prob_str:
                    prob_str = prob_str.replace('%', '').strip()
                    try:
                        prob = float(prob_str) / 100.0
                    except (ValueError, TypeError):
                        return default
                else:
                    try:
                        prob = float(prob_str)
                        # If value > 1, assume percentage
                        if prob > 1.0:
                            prob = prob / 100.0
                    except (ValueError, TypeError):
                        return default
            else:
                try:
                    prob = float(prob_value)
                    # If value > 1, assume it's a percentage (e.g., 75 instead of 0.75)
                    if prob > 1.0:
                        prob = prob / 100.0
                except (ValueError, TypeError):
                    return default
            
            # Clamp between 0 and 1
            return max(0.0, min(1.0, prob))


        def _is_asset_gla_positive(asset_idx):
            """Return True only when the asset has gross_leasable_area > 0.
            Handles None, NaN, blank strings, zero, and non-numeric values."""
            gla_raw = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
            if gla_raw is None:
                return False
            if isinstance(gla_raw, str):
                gla_raw = gla_raw.strip()
                if gla_raw == '':
                    return False
            try:
                if pd.isna(gla_raw):
                    return False
            except (ValueError, TypeError):
                pass
            try:
                return float(gla_raw) > 0
            except (ValueError, TypeError):
                return False

        def fn_get_tenant_applicability():
            """
            Determine which tenants are applicable for each asset.
            
            An asset is ONLY applicable when its gross_leasable_area > 0.
            Beyond that:
            - T1: Applicable if GLA > 0
            - Renewal: Applicable if GLA > 0 AND renewal lease dates populated
            - T2: Applicable if GLA > 0 AND T2 lease dates populated
            
            Cashflows are weighted by renewal_probability later.
            """
            tenant1_applicable = [False] * _num_assets
            renewal_applicable = [False] * _num_assets
            tenant2_applicable = [False] * _num_assets
            
            def is_valid_date(val):
                """Check if a value is a valid date (not None, not NaN, not empty string)."""
                if val is None:
                    return False
                if pd.isna(val):
                    return False
                if isinstance(val, str) and val.strip() == '':
                    return False
                return True
            
            for i in range(_num_assets):
                # Skip assets with zero / missing GLA
                if not _is_asset_gla_positive(i):
                    continue

                # T1 applicable for any asset with GLA > 0
                tenant1_applicable[i] = True

                # Check Renewal applicability: both start and end dates must be populated
                renewal_start = fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, i)
                renewal_end = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, i)
                renewal_applicable[i] = is_valid_date(renewal_start) and is_valid_date(renewal_end)
                
                # Check T2 applicability: both start and end dates must be populated
                t2_start = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, i)
                t2_end = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, i)
                tenant2_applicable[i] = is_valid_date(t2_start) and is_valid_date(t2_end)
            
            return {
                "tenant1": tenant1_applicable,
                "renewal": renewal_applicable,
                "tenant2": tenant2_applicable,
                "tenant1_and_renewal": tenant1_applicable,
                "renewal_flags": renewal_applicable,
            }


        # =============================================================================
        # GENERIC FUNCTIONS FOR ANY TENANT TYPE
        # =============================================================================

        def fn_get_actual_base_rent(tenant_type):
            """Extract actual base rent data from assumptions for specified tenant type.
            
            Named ranges:
            - tenant1: s.assetco.t1.actual.base.rent
            - renewal: s.assetco.t1.renewal.actual.base.rent  
            - tenant2: s.assetco.t2.actual.base.rent
            
            Returns a DataFrame where:
            - Actual values are stored as-is (including 0)
            - Blank/empty cells are stored as NaN
            """
            cache_key = ("actual_base_rent", tenant_type)
            cached = _local_cache_get(local_cache, cache_key)
            if cached is not None:
                return cached
            try:
                config = fn_get_tenant_config()[tenant_type]
                actual_rent_name = config["actual_rent_name"]
                
                # Find the named range in assumptions
                matching_rows = assumptions.loc[assumptions["name"] == actual_rent_name, "value"]
                
                if matching_rows.empty:
                    return None
                
                actual_rent_data = matching_rows.iloc[0]
                
                if actual_rent_data is None:
                    return None
                
                
                # Use NaN as default to distinguish blank from 0
                actual_rent_arr = np.full((_num_assets, _num_periods), np.nan)
                
                # Handle different data structures
                if isinstance(actual_rent_data, list):
                    for asset_idx in range(min(len(actual_rent_data), _num_assets)):
                        row = actual_rent_data[asset_idx]
                        if isinstance(row, list):
                            for period_idx in range(min(len(row), _num_periods)):
                                val = row[period_idx]
                                # Check for blank/empty string
                                if val is None or (isinstance(val, str) and val.strip() == ''):
                                    continue  # Leave as NaN
                                if pd.isna(val):
                                    continue  # Leave as NaN
                                try:
                                    actual_rent_arr[asset_idx, period_idx] = float(val)
                                except (ValueError, TypeError):
                                    pass  # Leave as NaN
                        elif row is not None and not pd.isna(row):
                            # Single value for all periods
                            if not (isinstance(row, str) and row.strip() == ''):
                                try:
                                    actual_rent_arr[asset_idx, :] = float(row)
                                except (ValueError, TypeError):
                                    pass
                
                # Use integer columns (0, 1, 2, ...) to match how they're accessed in fn_compute_escalated_rent_schedule
                df = pd.DataFrame(actual_rent_arr, index=range(_num_assets), columns=range(_num_periods))
                return _local_cache_set(local_cache, cache_key, df)
                
            except Exception:
                return None


        def fn_create_lease_flags(tenant_type):
            """FULLY VECTORIZED: Create lease flags (1 during active lease, 0 otherwise) for all assets at once.
            
            Uses 2D numpy broadcasting to compute all (_num_assets, _num_periods) flags simultaneously.
            """
            cache_key = ("lease_flags", tenant_type)
            cached = _local_cache_get(flag_cache, cache_key)
            if cached is not None:
                return cached
            
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            
            lease_flags = np.zeros((_num_assets, _num_periods), dtype=int)
            
            # Check if lease_start_date and lease_expiration_date are populated
            if lease_params.lease_start_date is None or lease_params.lease_expiration_date is None:
                df = pd.DataFrame(lease_flags, index=range(_num_assets), columns=range(_num_periods))
                return _local_cache_set(flag_cache, cache_key, df)
            
            # Convert period timestamps to numpy datetime64 arrays - shape: (_num_periods,)
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts])
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts])
            
            # Build arrays of lease dates for all assets - shape: (_num_assets,)
            lease_starts_np = []
            lease_exps_np = []
            valid_mask = []
            
            for i in range(_num_assets):
                try:
                    ls = lease_params.lease_start_date[i]
                    le = lease_params.lease_expiration_date[i]
                except (IndexError, TypeError):
                    ls, le = None, None
                
                if ls is not None and le is not None and not pd.isna(ls) and not pd.isna(le):
                    lease_starts_np.append(pd.Timestamp(ls).to_datetime64())
                    lease_exps_np.append(pd.Timestamp(le).to_datetime64())
                    valid_mask.append(True)
                else:
                    lease_starts_np.append(np.datetime64('NaT'))
                    lease_exps_np.append(np.datetime64('NaT'))
                    valid_mask.append(False)
            
            lease_starts_np = np.array(lease_starts_np)  # Shape: (_num_assets,)
            lease_exps_np = np.array(lease_exps_np)       # Shape: (_num_assets,)
            valid_mask = np.array(valid_mask)             # Shape: (_num_assets,)
            
            # 2D Broadcasting: reshape for broadcasting
            # lease_starts_np[:, None] -> shape: (_num_assets, 1)
            # period_ends_np[None, :] -> shape: (1, _num_periods)
            # Result: (_num_assets, _num_periods)
            
            # Compute flags where: period_end >= lease_start AND period_start <= lease_expiration
            with np.errstate(invalid='ignore'):  # Suppress NaT comparison warnings
                condition1 = period_ends_np[None, :] >= lease_starts_np[:, None]
                condition2 = period_starts_np[None, :] <= lease_exps_np[:, None]
                lease_flags = (condition1 & condition2).astype(int)
            
            # Zero out assets with invalid dates
            lease_flags[~valid_mask, :] = 0
            df = pd.DataFrame(lease_flags, index=range(_num_assets), columns=range(_num_periods))
            return _local_cache_set(flag_cache, cache_key, df)


        def fn_create_rent_free_flags(tenant_type):
            """FULLY VECTORIZED: Create rent-free flags (1 during rent-free period, 0 otherwise) for all assets at once.
            
            Uses 2D numpy broadcasting to compute all (_num_assets, _num_periods) flags simultaneously.
            """
            cache_key = ("rent_free_flags", tenant_type)
            cached = _local_cache_get(flag_cache, cache_key)
            if cached is not None:
                return cached
            
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            
            rent_free_flags = np.zeros((_num_assets, _num_periods), dtype=int)
            
            # Check if required attributes are populated
            if lease_params.lease_start_date is None or lease_params.rent_free_duration is None:
                df = pd.DataFrame(
                    rent_free_flags,
                    index=range(_num_assets),
                    columns=range(_num_periods),
                )
                return _local_cache_set(flag_cache, cache_key, df)
            
            # Convert period timestamps to numpy datetime64 arrays
            period_starts_np = np.array(
                [pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts]
            )
            period_ends_np = np.array(
                [pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts]
            )
            
            lease_starts_np = []
            rent_free_ends_np = []
            valid_mask = []
            
            for i in range(_num_assets):
                try:
                    ls = lease_params.lease_start_date[i]
                    rfd = lease_params.rent_free_duration[i]
                except (IndexError, TypeError):
                    ls, rfd = None, None
                
                if (
                    ls is not None
                    and rfd is not None
                    and not pd.isna(ls)
                    and not pd.isna(rfd)
                    and float(rfd) > 0
                ):
                    ls_ts = pd.to_datetime(ls)
                    rf_end_ts = (
                        ls_ts
                        + pd.DateOffset(months=int(rfd))
                        - pd.DateOffset(days=1)
                    )
                    lease_starts_np.append(ls_ts.to_datetime64())
                    rent_free_ends_np.append(rf_end_ts.to_datetime64())
                    valid_mask.append(True)
                else:
                    lease_starts_np.append(np.datetime64("NaT"))
                    rent_free_ends_np.append(np.datetime64("NaT"))
                    valid_mask.append(False)
            
            lease_starts_np = np.array(lease_starts_np)
            rent_free_ends_np = np.array(rent_free_ends_np)
            valid_mask = np.array(valid_mask)
            
            # 2D Broadcasting
            with np.errstate(invalid="ignore"):
                condition1 = period_ends_np[None, :] >= lease_starts_np[:, None]
                condition2 = period_starts_np[None, :] <= rent_free_ends_np[:, None]
                rent_free_flags = (condition1 & condition2).astype(int)
            
            # Zero out invalid assets
            rent_free_flags[~valid_mask, :] = 0
            
            df = pd.DataFrame(
                rent_free_flags,
                index=range(_num_assets),
                columns=range(_num_periods),
            )
            
            return _local_cache_set(flag_cache, cache_key, df)



        def fn_create_cash_collection_flags(tenant_type, lease_flags=None, rent_free_flags=None):
            """Create cash collection flags (lease active AND NOT rent-free) for specified tenant type."""
            use_default_inputs = lease_flags is None and rent_free_flags is None
            if use_default_inputs:
                cache_key = ("cash_collection_flags", tenant_type)
                cached = _local_cache_get(flag_cache, cache_key)
                if cached is not None:
                    return cached
            if lease_flags is None:
                lease_flags = fn_create_lease_flags(tenant_type)
            if rent_free_flags is None:
                rent_free_flags = fn_create_rent_free_flags(tenant_type)
            result = lease_flags * (1 - rent_free_flags)
            if use_default_inputs:
                _local_cache_set(flag_cache, ("cash_collection_flags", tenant_type), result)
            return result


        def fn_convert_annual_to_monthly_rate(annual_rate):
            """Convert annual escalation rate to true monthly compounding rate.

            Monthly rate = (1 + annual_rate)^(1/12) - 1
            Compounding 12 times exactly recovers the annual rate.
            """
            if annual_rate is None or pd.isna(annual_rate):
                return 0.0
            try:
                annual_rate = float(annual_rate)
            except (ValueError, TypeError):
                return 0.0
            if annual_rate == 0:
                return 0.0
            return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


        def fn_get_variable_escalation_profile(profile_name):
            """Retrieve variable escalation profile rates by profile name."""
            # globalassumptions
            cache_key = ("variable_escalation_profile", profile_name)
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached
            try:
                profiles_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant.lease.escalation.profiles", "value"
                ]
                if profiles_df.empty:
                    return None
                profiles = profiles_df.iloc[0]
                
                escalations_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant.lease.escalations", "value"
                ]
                if escalations_df.empty:
                    return None
                escalations = escalations_df.iloc[0]
                
                if isinstance(profiles, list) and profile_name in profiles:
                    profile_idx = profiles.index(profile_name)
                else:
                    return None
                
                if isinstance(escalations, list) and len(escalations) > profile_idx:
                    row = escalations[profile_idx]
                    result = row if isinstance(row, list) else [row]
                    return _local_cache_set(profile_cache, cache_key, result)

                return _local_cache_set(profile_cache, cache_key, [])
                

                
            except Exception:
                return None


        def fn_get_escalation_basis(asset_idx, tenant_type):
            """
            Get the escalation basis for a given asset and tenant type.
            
            Returns: str - "annual_year" or "lease_year" (default)
            
            Escalation Basis options:
            - "Annual Year Basis" / "Calendar Year": Escalations apply from Jan 1st of each year.
              If lease starts Mar Y2, base rate applies for all of Y2. Year 2 rate from Jan Y3.
            - "Lease Year Basis" (default): Escalations apply from lease anniversary.
              If lease starts Mar Y2, Year 2 rate applies from Mar Y3.
            """
            config = fn_get_tenant_config()[tenant_type]
            rent_params = config["rent_params"]
            
            escalation_basis = fn_safe_get(rent_params.escalation_basis, asset_idx)
            
            if escalation_basis is None or pd.isna(escalation_basis):
                return "lease_year"  # Default to lease year basis
            
            if isinstance(escalation_basis, str):
                basis_lower = escalation_basis.lower().strip()
                
                # Check for annual/calendar year basis
                if "annual" in basis_lower or "calendar" in basis_lower:
                    return "annual_year"
                
                # Check for lease year basis
                if "lease" in basis_lower:
                    return "lease_year"
            
            return "lease_year"  # Default


        def fn_compute_escalated_rent_fixed(asset_idx, tenant_type):
            """Compute escalated rent schedule using FIXED escalation for specified tenant type.
            
            Compounding is ALWAYS monthly from model start, regardless of basis.
            The escalation_basis and escalation_frequency determine when the rate "steps up" (locks in).
            
            Annual Year Basis:
            - Rate steps up at end of each calendar year
            - Frequency (must be multiple of 12) determines years between step-ups
            - E.g., Model start Jan 2023, freq=12, 5% annual:
              - 2023 periods: 0 months compounded (no escalation in year 1)
              - 2024 periods: 12 months compounded (escalation from 2023)
              - 2025 periods: 24 months compounded (escalation from 2023-2024)
            - E.g., freq=24 (every 2 years):
              - 2023-2024: 0 months, 2025-2026: 24 months, 2027-2028: 48 months
            
            Lease Year Basis:
            - Rate steps up at each lease anniversary based on frequency
            - E.g., Model start Jan 2023, lease June 2024, freq=12, 5% annual:
              - June 2024 - May 2025: 17 months compounded (Jan 2023 - May 2024)
              - June 2025 - May 2026: 29 months compounded (Jan 2023 - May 2025)
            - E.g., freq=6 (semi-annual step-ups):
              - June-Nov 2024: 17 months, Dec 2024-May 2025: 23 months
            """
            # global_num_periods, _period_starts_ts, _period_ends_ts
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            rent_params = config["rent_params"]
            
            rent_schedule = np.zeros(_num_periods)
            
            # Use safe access for all list attributes
            lease_start = fn_safe_get(lease_params.lease_start_date, asset_idx)
            lease_expiration = fn_safe_get(lease_params.lease_expiration_date, asset_idx)
            forecast_base_rent_per_sqm = fn_safe_get(rent_params.forecast_base_rent, asset_idx)
            fixed_escalation_annual = fn_safe_get(rent_params.fixed_escalation, asset_idx)
            escalation_frequency = fn_safe_get(rent_params.lease_escalation_frequency, asset_idx)
            gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
            model_start = Global.ModelInputs.model_start_date
            
            # Get escalation basis
            escalation_basis = fn_get_escalation_basis(asset_idx, tenant_type)
            
            if lease_start is None or pd.isna(lease_start) or forecast_base_rent_per_sqm is None or pd.isna(forecast_base_rent_per_sqm):
                return pd.Series(rent_schedule, index=range(_num_periods))
            
            lease_start = pd.to_datetime(lease_start)
            lease_expiration = pd.to_datetime(lease_expiration) if not pd.isna(lease_expiration) else None
            model_start = pd.to_datetime(model_start) if model_start and not pd.isna(model_start) else lease_start
            
            # Ensure numeric values are floats
            try:
                base_rent_per_sqm = float(forecast_base_rent_per_sqm)
            except (ValueError, TypeError):
                base_rent_per_sqm = 0.0
            try:
                gla = float(gla) if gla is not None and not pd.isna(gla) else 0.0
            except (ValueError, TypeError):
                gla = 0.0
            try:
                annual_esc_rate = float(fixed_escalation_annual) if not pd.isna(fixed_escalation_annual) else 0.0
            except (ValueError, TypeError):
                annual_esc_rate = 0.0
            monthly_esc_rate = fn_convert_annual_to_monthly_rate(annual_esc_rate)
            try:
                escalation_freq_months = int(float(escalation_frequency)) if not pd.isna(escalation_frequency) and escalation_frequency > 0 else 12
            except (ValueError, TypeError):
                escalation_freq_months = 12
            
            # Handle escalation frequency based on basis type
            # Annual Year Basis: frequency only matters if it's a multiple of 12
            # Lease Year Basis: frequency matters directly (3, 6, 12, 18, etc.)
            if escalation_basis == "annual_year":
                # For annual basis, if frequency is not a multiple of 12, treat as 12
                if escalation_freq_months % 12 == 0:
                    effective_freq_months = escalation_freq_months  # 12, 24, 36, etc.
                else:
                    effective_freq_months = 12  # Ignore sub-annual or non-multiple frequencies
            else:
                # For lease year basis, use frequency as-is
                effective_freq_months = escalation_freq_months
            
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                if period_end < lease_start:
                    continue
                if lease_expiration and period_start > lease_expiration:
                    continue
                
                # Calculate total months from model start to this period
                total_months_from_model = ((period_start.year - model_start.year) * 12 + 
                                          (period_start.month - model_start.month))
                
                if escalation_basis == "annual_year":
                    # Annual Year Basis: Escalation steps up at end of each calendar year
                    # Compound monthly from model start, but rate locks in at Dec 31 of previous year
                    # Frequency determines how many years before escalation steps up (12, 24, 36 months)
                    
                    # Calculate months elapsed from model start to end of previous year
                    years_elapsed = period_start.year - model_start.year
                    if years_elapsed <= 0:
                        # Period is in model start year - no compounding yet
                        total_months_to_compound = 0
                    else:
                        # Months from model start to end of current year (inclusive)
                        months_to_current_year_end = (years_elapsed + 1) * 12
                        
                        # Apply frequency: only count complete escalation periods
                        # E.g., freq=24 means escalation changes every 2 years
                        escalation_periods_complete = months_to_current_year_end // effective_freq_months
                        total_months_to_compound = escalation_periods_complete * effective_freq_months
                else:
                    # Lease Year Basis: Escalation steps up at each lease anniversary based on frequency
                    # Compound monthly from model start, rate locks in at start of each escalation period
                    
                    if period_start >= lease_start:
                        months_since_lease_start = ((period_start.year - lease_start.year) * 12 + 
                                                   (period_start.month - lease_start.month))
                    else:
                        months_since_lease_start = 0
                    
                    # Which escalation period based on frequency (0 = first period, 1 = second, etc.)
                    escalation_period_num = months_since_lease_start // effective_freq_months
                    
                    # Total months to compound = months from model start to lease start +
                    # Snap window to end of the step-up year so the full profile year rate is captured
                    months_model_to_lease = max(0, ((lease_start.year - model_start.year) * 12 +
                                                   (lease_start.month - model_start.month)))
                    step_up_month = months_model_to_lease + (escalation_period_num * effective_freq_months)
                    total_months_to_compound = (step_up_month // 12 + 1) * 12

                # Apply compounding
                if total_months_to_compound <= 0:
                    current_rent_per_sqm = base_rent_per_sqm
                else:
                    current_rent_per_sqm = base_rent_per_sqm * ((1 + monthly_esc_rate) ** total_months_to_compound)
                
                rent_schedule[col_idx] = current_rent_per_sqm * gla
            
            return pd.Series(rent_schedule, index=range(_num_periods))


        def fn_compute_escalated_rent_variable(asset_idx, tenant_type):
            """Compute escalated rent schedule using VARIABLE escalation for specified tenant type.
            
            Compounding is ALWAYS monthly from model start, regardless of basis.
            Variable escalation uses a profile of rates that vary by year from model start.
            The escalation_basis and escalation_frequency determine when the rate "steps up" (locks in).
            
            Annual Year Basis:
            - Rate steps up at end of each calendar year
            - Frequency (must be multiple of 12) determines years between step-ups
            
            Lease Year Basis:
            - Rate steps up at each lease anniversary based on frequency
            """
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            rent_params = config["rent_params"]
            
            rent_schedule = np.zeros(_num_periods)
            
            # Use safe access for all list attributes
            lease_start = fn_safe_get(lease_params.lease_start_date, asset_idx)
            lease_expiration = fn_safe_get(lease_params.lease_expiration_date, asset_idx)
            forecast_base_rent_per_sqm = fn_safe_get(rent_params.forecast_base_rent, asset_idx)
            variable_profile_name = fn_safe_get(rent_params.variable_escalation_profile, asset_idx)
            escalation_frequency = fn_safe_get(rent_params.lease_escalation_frequency, asset_idx)
            gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
            model_start = Global.ModelInputs.model_start_date
            
            # Get escalation basis
            escalation_basis = fn_get_escalation_basis(asset_idx, tenant_type)
            
            if lease_start is None or pd.isna(lease_start) or forecast_base_rent_per_sqm is None or pd.isna(forecast_base_rent_per_sqm):
                return pd.Series(rent_schedule, index=range(_num_periods))
            
            lease_start = pd.to_datetime(lease_start)
            lease_expiration = pd.to_datetime(lease_expiration) if not pd.isna(lease_expiration) else None
            model_start = pd.to_datetime(model_start) if not pd.isna(model_start) else lease_start
            
            # Ensure numeric values are floats
            try:
                base_rent_per_sqm = float(forecast_base_rent_per_sqm)
            except (ValueError, TypeError):
                base_rent_per_sqm = 0.0
            try:
                gla = float(gla) if gla is not None and not pd.isna(gla) else 0.0
            except (ValueError, TypeError):
                gla = 0.0
            try:
                escalation_freq_months = int(float(escalation_frequency)) if not pd.isna(escalation_frequency) and escalation_frequency > 0 else 12
            except (ValueError, TypeError):
                escalation_freq_months = 12
            
            # Handle escalation frequency based on basis type
            # Annual Year Basis: frequency only matters if it's a multiple of 12
            # Lease Year Basis: frequency matters directly (3, 6, 12, 18, etc.)
            if escalation_basis == "annual_year":
                # For annual basis, if frequency is not a multiple of 12, treat as 12
                if escalation_freq_months % 12 == 0:
                    effective_freq_months = escalation_freq_months  # 12, 24, 36, etc.
                else:
                    effective_freq_months = 12  # Ignore sub-annual or non-multiple frequencies
            else:
                # For lease year basis, use frequency as-is
                effective_freq_months = escalation_freq_months
            
            if pd.isna(variable_profile_name):
                return pd.Series(rent_schedule, index=range(_num_periods))
            
            profile_rates = fn_get_variable_escalation_profile(variable_profile_name)
            if profile_rates is None or len(profile_rates) == 0:
                profile_rates = [0]
            
            # Pre-compute monthly rates from profile (avoid repeated lookups)
            # Profile rates are indexed by years from model start
            profile_monthly_rates = []
            for rate_val in profile_rates:
                if rate_val is None or pd.isna(rate_val):
                    annual_rate = 0.0
                else:
                    try:
                        annual_rate = float(rate_val)
                    except (ValueError, TypeError):
                        annual_rate = 0.0
                profile_monthly_rates.append(fn_convert_annual_to_monthly_rate(annual_rate))
            last_monthly_rate = profile_monthly_rates[-1] if profile_monthly_rates else 0
            
            def get_monthly_rate_for_month(month_from_model_start):
                """Get the monthly rate for a specific month from model start."""
                year_from_model_start = month_from_model_start // 12
                if year_from_model_start < len(profile_monthly_rates):
                    return profile_monthly_rates[year_from_model_start]
                return last_monthly_rate
            
            def compound_for_months(start_month_from_model, num_months):
                """Compound variable rate for specified months returning the factor."""
                if num_months <= 0:
                    return 1.0
                factor = 1.0
                for m in range(num_months):
                    rate = get_monthly_rate_for_month(start_month_from_model + m)
                    factor *= (1 + rate)
                return factor
            
            # Build rent schedule
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                if period_end < lease_start:
                    continue
                if lease_expiration and period_start > lease_expiration:
                    continue
                
                # Calculate months since lease start
                if period_start >= lease_start:
                    months_since_lease_start = ((period_start.year - lease_start.year) * 12 + 
                                               (period_start.month - lease_start.month))
                else:
                    months_since_lease_start = 0
                
                # Determine total months to compound based on escalation basis
                if escalation_basis == "annual_year":
                    # Annual Year Basis: Rate for year N applies DURING year N
                    # Compound monthly from model start, including current year's rate
                    # Frequency determines how many years before escalation steps up
                    
                    years_elapsed = period_start.year - model_start.year
                    if years_elapsed <= 0:
                        # Period is in model start year - no compounding yet
                        total_months_to_compound = 0
                    else:
                        # Months from model start to end of current year (inclusive)
                        months_to_current_year_end = (years_elapsed + 1) * 12
                        
                        # Apply frequency: only count complete escalation periods
                        escalation_periods_complete = months_to_current_year_end // effective_freq_months
                        total_months_to_compound = escalation_periods_complete * effective_freq_months
                else:
                    # Lease Year Basis: Rate for current period applies DURING that period
                    # Compound monthly from model start, including current period's rate
                    escalation_period_num = months_since_lease_start // effective_freq_months
                    
                    # Snap window to end of the step-up year so the full profile year rate is captured
                    months_model_to_lease = max(0, ((lease_start.year - model_start.year) * 12 +
                                                   (lease_start.month - model_start.month)))
                    step_up_month = months_model_to_lease + (escalation_period_num * effective_freq_months)
                    total_months_to_compound = (step_up_month // 12 + 1) * 12

                # Compound from month 0 (model start) for total_months_to_compound
                compound_factor = compound_for_months(0, total_months_to_compound)
                current_rent_per_sqm = base_rent_per_sqm * compound_factor
                
                rent_schedule[col_idx] = current_rent_per_sqm * gla
            
            return pd.Series(rent_schedule, index=range(_num_periods))


        def fn_compute_forecast_rent_schedule(asset_idx, tenant_type):
            """Compute forecast rent schedule based on escalation type for specified tenant type."""
            config = fn_get_tenant_config()[tenant_type]
            rent_params = config["rent_params"]
            
            # Use safe access for list attributes
            escalation_type = fn_safe_get(rent_params.lease_escalation_type, asset_idx, "Fixed")
            
            if escalation_type is None or pd.isna(escalation_type):
                escalation_type = "Fixed"
            
            escalation_type_lower = str(escalation_type).lower().strip()
            
            if escalation_type_lower == "fixed":
                return fn_compute_escalated_rent_fixed(asset_idx, tenant_type)
            elif escalation_type_lower == "variable":
                return fn_compute_escalated_rent_variable(asset_idx, tenant_type)
            else:
                return fn_compute_escalated_rent_fixed(asset_idx, tenant_type)


        def fn_compute_escalated_rent_schedule(asset_idx, tenant_type, all_lease_flags=None, actual_base_rent=None):
            """Compute escalated rent based on rent_input_type for specified tenant type."""
            # global_num_periods
            config = fn_get_tenant_config()[tenant_type]
            rent_params = config["rent_params"]
            lease_params = config["lease_params"]
            
            # Get lease expiration date for additional validation
            lease_expiration = None
            try:
                lease_exp_raw = lease_params.lease_expiration_date[asset_idx] if lease_params.lease_expiration_date is not None else None
                if lease_exp_raw is not None and not pd.isna(lease_exp_raw):
                    # Check for empty string
                    if isinstance(lease_exp_raw, str) and lease_exp_raw.strip() == '':
                        lease_expiration = None
                    else:
                        lease_expiration = pd.to_datetime(lease_exp_raw)
            except Exception:
                lease_expiration = None
            
            # Check if rent_input_type is a list/array or single value
            rent_input_type_raw = rent_params.rent_input_type
            if rent_input_type_raw is None:
                rent_input_type = "Forecast"
            elif isinstance(rent_input_type_raw, (list, np.ndarray)):
                if asset_idx < len(rent_input_type_raw):
                    rent_input_type = rent_input_type_raw[asset_idx]
                else:
                    rent_input_type = "Forecast"
            else:
                rent_input_type = rent_input_type_raw
            
            if rent_input_type is None or pd.isna(rent_input_type):
                rent_input_type = "Forecast"
            
            rent_input_type_lower = str(rent_input_type).lower().strip()
            
            if rent_input_type_lower == "forecast":
                return fn_compute_forecast_rent_schedule(asset_idx, tenant_type)
            
            # Get lease flags for this asset
            if all_lease_flags is not None:
                lease_flag_row = all_lease_flags.loc[asset_idx]
            else:
                lease_flags = fn_create_lease_flags(tenant_type)
                lease_flag_row = lease_flags.loc[asset_idx]
            
            if rent_input_type_lower == "actuals":
                # Pure actuals mode - only use actuals, no forecast fallback
                rent_schedule = np.zeros(_num_periods)
                
                if actual_base_rent is not None:
                    actual_rent_row = actual_base_rent.loc[asset_idx]
                    
                    for col_idx in range(_num_periods):
                        # Check lease flag
                        if lease_flag_row[col_idx] != 1:
                            continue
                        # Additional check: ensure period is within lease expiration
                        if lease_expiration is not None:
                            period_start = _period_starts_ts[col_idx]
                            if period_start > lease_expiration:
                                continue
                        actual_val = actual_rent_row[col_idx]
                        if actual_val is not None and not pd.isna(actual_val):
                            rent_schedule[col_idx] = actual_val  # Include even if 0
                
                return pd.Series(rent_schedule, index=range(_num_periods))
            
            if rent_input_type_lower == "actuals + forecast":
                # Start with forecast as base
                rent_schedule = fn_compute_forecast_rent_schedule(asset_idx, tenant_type).values.copy()
                
                if actual_base_rent is None:
                    return pd.Series(rent_schedule, index=range(_num_periods))
                
                actual_rent_row = actual_base_rent.loc[asset_idx]
                
                # Override with actuals when valid (non-blank, non-negative; zero IS valid)
                for col_idx in range(_num_periods):
                    # Check lease flag
                    if lease_flag_row[col_idx] != 1:
                        continue
                    # Additional check: ensure period is within lease expiration
                    if lease_expiration is not None:
                        period_start = _period_starts_ts[col_idx]
                        if period_start > lease_expiration:
                            continue
                    actual_val = actual_rent_row[col_idx]
                    # Override if actual is not None/NaN and not negative
                    if actual_val is not None and not pd.isna(actual_val) and actual_val >= 0:
                        rent_schedule[col_idx] = actual_val
                
                return pd.Series(rent_schedule, index=range(_num_periods))
            
            return fn_compute_forecast_rent_schedule(asset_idx, tenant_type)


        def fn_compute_all_assets_escalated_rent_fixed_vectorized(tenant_type):
            """FULLY VECTORIZED: Compute escalated rent using FIXED escalation for ALL assets at once.
            
            Uses pure 2D numpy broadcasting — no per-asset or per-period Python loops.
            Reads all inputs once into arrays, then computes everything with broadcasting.
            
            GLA=0 or missing → 0 rent (no default to 1.0).
            
            Returns: numpy array of shape (_num_assets, _num_periods)
            """
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            rent_params = config["rent_params"]
            
            model_start = pd.to_datetime(Global.ModelInputs.model_start_date)
            
            # ── Step 1: Read ALL inputs into 1-D arrays (single loop over assets) ──
            lease_starts_dt64 = np.full(_num_assets, np.datetime64('NaT'), dtype='datetime64[ns]')
            lease_exps_dt64 = np.full(_num_assets, np.datetime64('NaT'), dtype='datetime64[ns]')
            base_rents_np = np.zeros(_num_assets)
            glas_np = np.zeros(_num_assets)           # GLA=0 → 0 rent
            monthly_rates_np = np.zeros(_num_assets)
            eff_freqs_np = np.full(_num_assets, 12, dtype=np.int64)
            is_annual_year_np = np.zeros(_num_assets, dtype=bool)
            months_model_to_lease_np = np.zeros(_num_assets, dtype=np.int64)
            lease_start_years = np.zeros(_num_assets, dtype=np.int64)
            lease_start_months = np.zeros(_num_assets, dtype=np.int64)
            valid_mask = np.zeros(_num_assets, dtype=bool)
            
            for i in range(_num_assets):
                ls = fn_safe_get(lease_params.lease_start_date, i)
                le = fn_safe_get(lease_params.lease_expiration_date, i)
                br = fn_safe_get(rent_params.forecast_base_rent, i)
                gla_raw = fn_safe_get(Unit.UnitInputs.gross_leasable_area, i)
                esc = fn_safe_get(rent_params.fixed_escalation, i)
                freq = fn_safe_get(rent_params.lease_escalation_frequency, i)
                basis = fn_get_escalation_basis(i, tenant_type)
                
                # Skip assets with missing lease dates or rent
                if ls is None or le is None or br is None:
                    continue
                
                try:
                    ls_ts = pd.to_datetime(ls)
                    le_ts = pd.to_datetime(le)
                    br_val = float(br)
                except (ValueError, TypeError):
                    continue
                
                lease_starts_dt64[i] = ls_ts.to_datetime64()
                lease_exps_dt64[i] = le_ts.to_datetime64()
                base_rents_np[i] = br_val
                
                # GLA: 0 or missing → 0.0 (no rent if no area)
                try:
                    glas_np[i] = float(gla_raw) if gla_raw is not None and not pd.isna(gla_raw) else 0.0
                except (ValueError, TypeError):
                    glas_np[i] = 0.0
                
                # Monthly escalation rate
                try:
                    esc_val = float(esc) if esc is not None and not pd.isna(esc) else 0.0
                except (ValueError, TypeError):
                    esc_val = 0.0
                monthly_rates_np[i] = ((1.0 + esc_val) ** (1.0 / 12.0) - 1.0) if esc_val != 0 else 0.0
                
                # Escalation frequency
                try:
                    freq_val = int(float(freq)) if freq is not None and not pd.isna(freq) and float(freq) > 0 else 12
                except (ValueError, TypeError):
                    freq_val = 12
                
                is_ay = (basis == "annual_year")
                is_annual_year_np[i] = is_ay
                eff_freqs_np[i] = (freq_val if freq_val % 12 == 0 else 12) if is_ay else freq_val
                
                lease_start_years[i] = ls_ts.year
                lease_start_months[i] = ls_ts.month
                months_model_to_lease_np[i] = max(0, (ls_ts.year - model_start.year) * 12 +
                                                     (ls_ts.month - model_start.month))
                valid_mask[i] = True
            
            # ── Step 2: Build period arrays — shape (_num_periods,) ──
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts],
                                        dtype='datetime64[ns]')
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts],
                                      dtype='datetime64[ns]')
            period_years = np.array([ts.year for ts in _period_starts_ts], dtype=np.int64)
            period_months = np.array([ts.month for ts in _period_starts_ts], dtype=np.int64)
            
            # ── Step 3: Active-lease mask — shape (_num_assets, _num_periods) ──
            with np.errstate(invalid='ignore'):
                active_mask = (
                    (period_ends_np[None, :] >= lease_starts_dt64[:, None]) &
                    (period_starts_np[None, :] <= lease_exps_dt64[:, None])
                )
            active_mask[~valid_mask, :] = False
            
            # ── Step 4: Compute months_to_compound for ALL assets × ALL periods ──
            years_elapsed = period_years[None, :] - model_start.year
            months_to_prev_year = np.maximum(years_elapsed + 1, 0) * 12
            annual_months = np.where(
                years_elapsed > 0,
                (months_to_prev_year // eff_freqs_np[:, None]) * eff_freqs_np[:, None],
                0
            )
            
            months_since_lease = np.maximum(
                (period_years[None, :] - lease_start_years[:, None]) * 12 +
                (period_months[None, :] - lease_start_months[:, None]),
                0
            )
            period_num = months_since_lease // eff_freqs_np[:, None]
            step_up_months = months_model_to_lease_np[:, None] + period_num * eff_freqs_np[:, None]
            lease_months = (step_up_months // 12 + 1) * 12

            months_to_compound = np.where(is_annual_year_np[:, None], annual_months, lease_months)

            # ── Step 5: Compound factor — shape (_num_assets, _num_periods) ──
            compound_factor = np.where(
                months_to_compound > 0,
                (1.0 + monthly_rates_np[:, None]) ** months_to_compound,
                1.0
            )
            
            # ── Step 6: Final rent = base_rent × compound × GLA, masked by active lease ──
            all_rents = np.where(
                active_mask,
                base_rents_np[:, None] * compound_factor * glas_np[:, None],
                0.0
            )
            
            return all_rents


        def fn_compute_all_assets_escalated_rent_variable_vectorized(tenant_type):
            """VECTORIZED: Compute escalated rent using VARIABLE escalation for ALL assets at once.
            
            Returns: numpy array of shape (_num_assets, _num_periods)
            """
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            rent_params = config["rent_params"]
            
            model_start = pd.to_datetime(Global.ModelInputs.model_start_date)
            all_rents = np.zeros((_num_assets, _num_periods))
            
            # ── Step 1: Pre-compute period arrays — shape (_num_periods,) ──
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts],
                                        dtype='datetime64[ns]')
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts],
                                      dtype='datetime64[ns]')
            period_years = np.array([ts.year for ts in _period_starts_ts], dtype=np.int64)
            period_months = np.array([ts.month for ts in _period_starts_ts], dtype=np.int64)
            
            # ── Step 2: Pre-compute & cache cumulative compound factor arrays per profile ──
            max_compound_months = _num_periods * 2 + 240
            profile_cum_factors = {}
            
            def _ensure_profile_cached(pname):
                if pname in profile_cum_factors:
                    return
                rates_raw = fn_get_variable_escalation_profile(pname) or [0]
                monthly_rates = []
                for r in rates_raw:
                    try:
                        ar = float(r) if r is not None and not pd.isna(r) else 0.0
                    except (ValueError, TypeError):
                        ar = 0.0
                    monthly_rates.append(((1.0 + ar) ** (1.0 / 12.0) - 1.0) if ar != 0 else 0.0)
                last_rate = monthly_rates[-1]
                
                cum = np.ones(max_compound_months + 1)
                for m in range(1, max_compound_months + 1):
                    year_idx = (m - 1) // 12
                    rate = monthly_rates[year_idx] if year_idx < len(monthly_rates) else last_rate
                    cum[m] = cum[m - 1] * (1.0 + rate)
                profile_cum_factors[pname] = cum
            
            # ── Step 3: Read ALL inputs into 1-D arrays (single loop) ──
            lease_starts_dt64 = np.full(_num_assets, np.datetime64('NaT'), dtype='datetime64[ns]')
            lease_exps_dt64 = np.full(_num_assets, np.datetime64('NaT'), dtype='datetime64[ns]')
            base_rents_np = np.zeros(_num_assets)
            glas_np = np.zeros(_num_assets)
            eff_freqs_np = np.full(_num_assets, 12, dtype=np.int64)
            is_annual_year_np = np.zeros(_num_assets, dtype=bool)
            months_model_to_lease_np = np.zeros(_num_assets, dtype=np.int64)
            lease_start_years = np.zeros(_num_assets, dtype=np.int64)
            lease_start_months = np.zeros(_num_assets, dtype=np.int64)
            profile_indices = [None] * _num_assets
            valid_mask = np.zeros(_num_assets, dtype=bool)
            
            for i in range(_num_assets):
                ls = fn_safe_get(lease_params.lease_start_date, i)
                le = fn_safe_get(lease_params.lease_expiration_date, i)
                br = fn_safe_get(rent_params.forecast_base_rent, i)
                gla_raw = fn_safe_get(Unit.UnitInputs.gross_leasable_area, i)
                pname = fn_safe_get(rent_params.variable_escalation_profile, i)
                freq = fn_safe_get(rent_params.lease_escalation_frequency, i)
                basis = fn_get_escalation_basis(i, tenant_type)
                
                if ls is None or le is None or br is None or pname is None:
                    continue
                
                try:
                    ls_ts = pd.to_datetime(ls)
                    le_ts = pd.to_datetime(le)
                    br_val = float(br)
                except (ValueError, TypeError):
                    continue
                
                lease_starts_dt64[i] = ls_ts.to_datetime64()
                lease_exps_dt64[i] = le_ts.to_datetime64()
                base_rents_np[i] = br_val
                
                try:
                    glas_np[i] = float(gla_raw) if gla_raw is not None and not pd.isna(gla_raw) else 0.0
                except (ValueError, TypeError):
                    glas_np[i] = 0.0
                
                try:
                    freq_val = int(float(freq)) if freq is not None and not pd.isna(freq) and float(freq) > 0 else 12
                except (ValueError, TypeError):
                    freq_val = 12
                
                is_ay = (basis == "annual_year")
                is_annual_year_np[i] = is_ay
                eff_freqs_np[i] = (freq_val if freq_val % 12 == 0 else 12) if is_ay else freq_val
                
                lease_start_years[i] = ls_ts.year
                lease_start_months[i] = ls_ts.month
                months_model_to_lease_np[i] = max(0, (ls_ts.year - model_start.year) * 12 +
                                                     (ls_ts.month - model_start.month))
                profile_indices[i] = pname
                valid_mask[i] = True
                _ensure_profile_cached(pname)
            
            # ── Step 4: Active-lease mask — shape (_num_assets, _num_periods) ──
            with np.errstate(invalid='ignore'):
                active_mask = (
                    (period_ends_np[None, :] >= lease_starts_dt64[:, None]) &
                    (period_starts_np[None, :] <= lease_exps_dt64[:, None])
                )
            active_mask[~valid_mask, :] = False
            
            # ── Step 5: Compute months_to_compound — shape (_num_assets, _num_periods) ──
            years_elapsed = period_years[None, :] - model_start.year
            months_to_prev_year = np.maximum(years_elapsed + 1, 0) * 12
            annual_months = np.where(
                years_elapsed > 0,
                (months_to_prev_year // eff_freqs_np[:, None]) * eff_freqs_np[:, None],
                0
            )
            
            months_since_lease = np.maximum(
                (period_years[None, :] - lease_start_years[:, None]) * 12 +
                (period_months[None, :] - lease_start_months[:, None]),
                0
            )
            period_num = months_since_lease // eff_freqs_np[:, None]
            step_up_months = months_model_to_lease_np[:, None] + period_num * eff_freqs_np[:, None]
            lease_months = (step_up_months // 12 + 1) * 12

            months_to_compound = np.where(is_annual_year_np[:, None], annual_months, lease_months)
            months_to_compound = np.clip(months_to_compound, 0, max_compound_months).astype(np.int64)
            
            # ── Step 6: Look up precomputed compound factors per profile ──
            unique_profiles = set(p for p in profile_indices if p is not None)
            for pname in unique_profiles:
                cum = profile_cum_factors[pname]
                asset_mask = np.array([profile_indices[i] == pname for i in range(_num_assets)])
                asset_ids = np.where(asset_mask)[0]
                if len(asset_ids) == 0:
                    continue
                
                mtc_subset = months_to_compound[asset_ids, :]
                factors_subset = cum[mtc_subset]
                
                br_subset = base_rents_np[asset_ids, None]
                gla_subset = glas_np[asset_ids, None]
                active_subset = active_mask[asset_ids, :]
                
                all_rents[asset_ids, :] = np.where(
                    active_subset,
                    br_subset * factors_subset * gla_subset,
                    0.0
                )
            
            return all_rents


        def fn_compute_all_assets_escalated_rent(tenant_type):
            """FULLY VECTORIZED: Compute escalated rent schedules for ALL assets for specified tenant type.
            
            Reads all inputs once, computes fixed and variable escalation with 2D broadcasting,
            then applies actuals overlay using numpy masks — no per-cell Python loops.
            
            GLA=0 or missing → 0 rent.  Handles Forecast / Actuals / Actuals+Forecast input modes.
            """
            config = fn_get_tenant_config()[tenant_type]
            rent_params = config["rent_params"]
            lease_params = config["lease_params"]
            
            all_lease_flags = fn_create_lease_flags(tenant_type)
            actual_base_rent = fn_get_actual_base_rent(tenant_type)
            
            # ── Determine escalation type per asset — vectorized arrays ──
            esc_is_variable = np.zeros(_num_assets, dtype=bool)
            for i in range(_num_assets):
                esc_type = fn_safe_get(rent_params.lease_escalation_type, i, "Fixed")
                if esc_type is None or pd.isna(esc_type):
                    esc_type = "Fixed"
                esc_is_variable[i] = str(esc_type).lower().strip() == "variable"
            
            # ── Determine rent input type per asset ──
            # 0 = forecast, 1 = actuals, 2 = actuals + forecast
            rent_input_codes = np.zeros(_num_assets, dtype=np.int8)
            for i in range(_num_assets):
                rit_raw = rent_params.rent_input_type
                if rit_raw is None:
                    rit = "forecast"
                elif isinstance(rit_raw, (list, np.ndarray)):
                    rit = rit_raw[i] if i < len(rit_raw) else "forecast"
                else:
                    rit = rit_raw
                if rit is None or pd.isna(rit):
                    rit = "forecast"
                rit_lower = str(rit).lower().strip()
                if rit_lower == "actuals":
                    rent_input_codes[i] = 1
                elif rit_lower == "actuals + forecast":
                    rent_input_codes[i] = 2
            
            # ── Compute fixed and variable escalated rents ──
            fixed_rents = fn_compute_all_assets_escalated_rent_fixed_vectorized(tenant_type)
            variable_rents = fn_compute_all_assets_escalated_rent_variable_vectorized(tenant_type)
            
            # Combine: pick variable where esc_is_variable, else fixed — fully vectorized
            all_rents = np.where(esc_is_variable[:, None], variable_rents, fixed_rents)
            
            # ── Apply actuals overlay — vectorized with numpy masks ──
            # Valid actual = non-NaN AND non-negative (zero IS a valid actual)
            if actual_base_rent is not None:
                actual_arr = actual_base_rent.values
                lease_flags_arr = all_lease_flags.values
                actual_valid = ~np.isnan(actual_arr) & (actual_arr >= 0)
                
                # "Actuals" mode (code=1): use valid actuals where available, 0 elsewhere
                actuals_only_mask = (rent_input_codes == 1)
                if actuals_only_mask.any():
                    actuals_rent = np.where(
                        (lease_flags_arr == 1) & actual_valid,
                        actual_arr,
                        0.0
                    )
                    all_rents[actuals_only_mask, :] = actuals_rent[actuals_only_mask, :]
                
                # "Actuals + Forecast" mode (code=2): override forecast where
                # actuals are valid (non-NaN, non-negative); blank/negative → keep forecast
                actuals_forecast_mask = (rent_input_codes == 2)
                if actuals_forecast_mask.any():
                    overlay = (lease_flags_arr == 1) & actual_valid
                    blended = np.where(overlay, actual_arr, all_rents)
                    all_rents[actuals_forecast_mask, :] = blended[actuals_forecast_mask, :]
            
            
            return pd.DataFrame(all_rents, index=range(_num_assets), columns=model_timeline_me.index)


        def fn_compute_collectible_rent(tenant_type, escalated_rent_df, lease_flags_df, cash_collection_flags_df):
            """VECTORIZED: Compute collectible rent: first year spread across collection months, then normal.
            
            IMPORTANT: Spreading only occurs when there is a rent-free period.
            If rent_free_duration = 0, then collections = escalated rent directly (no spreading).
            """
            config = fn_get_tenant_config()[tenant_type]
            lease_params = config["lease_params"]
            
            collectible_rent = np.zeros((_num_assets, _num_periods))
            
            escalated_rent_arr = escalated_rent_df.values
            lease_flags_arr = lease_flags_df.values
            cc_flags_arr = cash_collection_flags_df.values
            
            # Pre-compute timestamps as numpy datetime64 for vectorization
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts])
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts])
            
            # Build arrays of lease parameters for all assets
            lease_starts = []
            lease_expirations = []
            rent_free_durations = []
            
            for i in range(_num_assets):
                ls = fn_safe_get(lease_params.lease_start_date, i)
                le = fn_safe_get(lease_params.lease_expiration_date, i)
                rfd = fn_safe_get(lease_params.rent_free_duration, i)
                
                if ls is not None and not pd.isna(ls):
                    lease_starts.append(pd.to_datetime(ls))
                else:
                    lease_starts.append(None)
                
                if le is not None and not pd.isna(le):
                    lease_expirations.append(pd.to_datetime(le))
                else:
                    lease_expirations.append(None)
                
                try:
                    rfd_val = float(rfd) if rfd is not None and not pd.isna(rfd) else 0.0
                except (ValueError, TypeError):
                    rfd_val = 0.0
                rent_free_durations.append(rfd_val)
            
            # Process all assets
            for i in range(_num_assets):
                ls = lease_starts[i]
                le = lease_expirations[i]
                rfd = rent_free_durations[i]
                
                if ls is None or le is None:
                    continue
                
                # Rent-free = true economic discount: zero during rent-free months,
                # contractual rate during collection months (no catch-up / spreading).
                collectible_rent[i, :] = escalated_rent_arr[i, :] * cc_flags_arr[i, :]
            
            return pd.DataFrame(collectible_rent, index=range(_num_assets), columns=model_timeline_me.index)


        # =============================================================================
        # OUTPUT DATAFRAMES FOR OUTPUT MODULE
        # =============================================================================

        # These will be populated after running the module
        # Base Rent Collections (what goes to output module)
        base_rent_collections_monthly = None      # Single row: Total collections across all units/tenants - monthly
        base_rent_collections_annual = None       # Single row: Total collections across all units/tenants - annual
        base_rent_collections_by_tenant_monthly = None  # Dict with tenant type keys, monthly totals
        base_rent_collections_by_tenant_annual = None   # Dict with tenant type keys, annual totals
        all_tenant_results = None  # Full detailed results by asset


        def fn_create_base_rent_output_dataframes(results):
            """
            Create summary DataFrames for the output module.
            Output is BASE RENT COLLECTIONS (collectible rent based on actuals + forecast).
            """
            global base_rent_collections_monthly, base_rent_collections_annual
            global base_rent_collections_by_tenant_monthly, base_rent_collections_by_tenant_annual
            # globalmodel_timeline_me, model_timeline_ye, _period_ends_ts, _num_periods
            
            # =========================================================================
            # MONTHLY COLLECTIONS - Single line item for output
            # =========================================================================
            monthly_t1 = results["tenant1"]["collectible_rent"].sum(axis=0)
            monthly_renewal = results["renewal"]["collectible_rent"].sum(axis=0)
            monthly_t2 = results["tenant2"]["collectible_rent"].sum(axis=0)
            monthly_total = monthly_t1 + monthly_renewal + monthly_t2
            
            # Create DataFrame with period dates as columns (for output module)
            period_dates = [_period_ends_ts[i] for i in range(_num_periods)]
            
            # Single line item - Total Base Rent Collections (Monthly)
            base_rent_collections_monthly = pd.DataFrame(
                [monthly_total.values],
                columns=period_dates,
                index=["Base Rent Collections"]
            )
            
            # By tenant breakdown (monthly) - for detailed output if needed
            base_rent_collections_by_tenant_monthly = {
                "tenant1": pd.Series(monthly_t1.values, index=period_dates, name="Tenant1 Collections"),
                "renewal": pd.Series(monthly_renewal.values, index=period_dates, name="Renewal Collections"),
                "tenant2": pd.Series(monthly_t2.values, index=period_dates, name="Tenant2 Collections"),
                "total": pd.Series(monthly_total.values, index=period_dates, name="Total Collections")
            }
            
            # =========================================================================
            # ANNUAL COLLECTIONS - Single line item for output
            # =========================================================================
            def aggregate_by_year(monthly_series):
                """Aggregate monthly data by year."""
                yearly_totals = {}
                for col_idx in range(_num_periods):
                    year = _period_ends_ts[col_idx].year
                    if year not in yearly_totals:
                        yearly_totals[year] = 0.0
                    yearly_totals[year] += monthly_series.iloc[col_idx]
                return yearly_totals
            
            yearly_t1 = aggregate_by_year(monthly_t1)
            yearly_renewal = aggregate_by_year(monthly_renewal)
            yearly_t2 = aggregate_by_year(monthly_t2)
            
            all_years = sorted(set(yearly_t1.keys()) | set(yearly_renewal.keys()) | set(yearly_t2.keys()))
            yearly_total = {y: yearly_t1.get(y, 0) + yearly_renewal.get(y, 0) + yearly_t2.get(y, 0) for y in all_years}
            
            # Single line item - Total Base Rent Collections (Annual)
            base_rent_collections_annual = pd.DataFrame(
                [[yearly_total.get(y, 0) for y in all_years]],
                columns=all_years,
                index=["Base Rent Collections"]
            )
            
            # By tenant breakdown (annual)
            base_rent_collections_by_tenant_annual = {
                "tenant1": yearly_t1,
                "renewal": yearly_renewal,
                "tenant2": yearly_t2,
                "total": yearly_total
            }
            
            # =========================================================================
            # SUM OF ALL UNITS TOGETHER (ONE LINE ONLY, for all tenants and units combined)
            # =========================================================================
            # Monthly: one row, columns = months
            # Annual: one row, columns = years

            # Already created above as base_rent_collections_monthly and base_rent_collections_annual
            # These are single-row DataFrames for all tenants and units combined

            # Optionally, create Excel workbook for this single line (monthly and annual)


            return base_rent_collections_monthly, base_rent_collections_annual


        # =============================================================================
        # MAIN MODULE FUNCTION
        # =============================================================================

        def fn_run_module_03(assumptions_input=None, timeline_me=None):
            """Main function to run Module 03 - Base Rent Computation."""
            nonlocal all_tenant_results

            # Step 3: Verify escalation profiles exist
            try:
                profiles = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant.lease.escalation.profiles", "value"
                ]
                if not profiles.empty:
                    profile_list = profiles.iloc[0]
                    pass
                else:
                    pass
            except Exception:
                pass

            # Step 4: Check actual rent data
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                config = fn_get_tenant_config()[tenant_type]
                actual_name = config["actual_rent_name"]
                try:
                    actual_data = assumptions.loc[assumptions["name"] == actual_name, "value"]
                    if not actual_data.empty and actual_data.iloc[0] is not None:
                        pass
                    else:
                        pass
                except:
                    pass

            # Step 5: Compute tenant applicability
            tenant_applicability = fn_get_tenant_applicability()
            t1_count = sum(tenant_applicability["tenant1"])
            renewal_count = sum(tenant_applicability["renewal"])
            t2_count = sum(tenant_applicability["tenant2"])

            # Step 6: Compute base rent for all tenants
            all_tenant_results = fn_compute_base_rent_all_tenants()

            # Step 7: Create output DataFrames
            fn_create_base_rent_output_dataframes(all_tenant_results)

            # Step 8: Summary (if needed, can be logged or returned)
            total_t1 = all_tenant_results["tenant1"]["collectible_rent"].sum().sum()
            total_renewal = all_tenant_results["renewal"]["collectible_rent"].sum().sum()
            total_t2 = all_tenant_results["tenant2"]["collectible_rent"].sum().sum()
            total_all = total_t1 + total_renewal + total_t2

            # Return comprehensive results including output dataframes
            return {
                'detailed_results': all_tenant_results,
                'base_rent_collections_monthly': base_rent_collections_monthly,
                'base_rent_collections_annual': base_rent_collections_annual,
                'base_rent_collections_by_tenant_monthly': base_rent_collections_by_tenant_monthly,
                'base_rent_collections_by_tenant_annual': base_rent_collections_by_tenant_annual,
                'summary': {
                    'total_tenant1': total_t1,
                    'total_renewal': total_renewal,
                    'total_tenant2': total_t2,
                    'total_all': total_all
                }
            }


        # =============================================================================
        # COMPUTE ALL TENANT TYPES
        # =============================================================================

        def fn_compute_base_rent_all_tenants():
            """Compute base rent for all tenant types (tenant1, renewal, tenant2)."""
            # global_num_assets, model_timeline_me
            tenant_applicability = fn_get_tenant_applicability()
            
            
            results = {}
            
            # Pre-compute probability arrays for vectorization
            renewal_probs = np.array([
                fn_normalize_probability(fn_safe_get(Unit.LeaseExpirationTenant1.renewal_probability, i, 1.0), default=1.0)
                for i in range(_num_assets)
            ])
            
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                # Create flags (pass precomputed to avoid redundancy)
                lease_flags = fn_create_lease_flags(tenant_type)
                rent_free_flags = fn_create_rent_free_flags(tenant_type)
                cash_collection_flags = fn_create_cash_collection_flags(tenant_type, lease_flags, rent_free_flags)

                # Compute escalated rent
                escalated_rent = fn_compute_all_assets_escalated_rent(tenant_type)

                # VECTORIZED: Zero out non-applicable assets using numpy broadcasting
                applicable = tenant_applicability[tenant_type]
                applicable_mask = np.array(applicable).reshape(-1, 1)  # Shape: (_num_assets, 1) for broadcasting
                
                escalated_rent_arr = escalated_rent.values
                lease_flags_arr = lease_flags.values
                rent_free_flags_arr = rent_free_flags.values
                cash_collection_flags_arr = cash_collection_flags.values

                # Zero out non-applicable assets in one operation
                non_applicable_mask = ~applicable_mask.flatten()
                escalated_rent_arr[non_applicable_mask, :] = 0
                lease_flags_arr[non_applicable_mask, :] = 0
                rent_free_flags_arr[non_applicable_mask, :] = 0
                cash_collection_flags_arr[non_applicable_mask, :] = 0
                
                # VECTORIZED: Check TOR Only agreement type
                is_renewal = (tenant_type == "renewal")
                should_compute_mask = np.array([
                    fn_should_compute_base_rent(i, tenant_type, is_renewal)
                    for i in range(_num_assets)
                ])
                tor_only_mask = ~should_compute_mask
                escalated_rent_arr[tor_only_mask, :] = 0
                cash_collection_flags_arr[tor_only_mask, :] = 0

                # Compute collectible rent
                collectible_rent = fn_compute_collectible_rent(
                    tenant_type, escalated_rent, lease_flags, cash_collection_flags
                )

                # NOTE: Renewal probability is NOT applied here.
                # It is applied only in the final CFS assembly (fn_get_base_rent_collections)
                # so that TOR ratchet/differential computations use raw base rent.

                results[tenant_type] = {
                    "lease_flags": lease_flags,
                    "rent_free_flags": rent_free_flags,
                    "cash_collection_flags": cash_collection_flags,
                    "escalated_rent": escalated_rent,
                    "collectible_rent": collectible_rent,
                    "applicable": applicable,
                }
            
            
            return results


        # =============================================================================
        # OUTPUT ACCESS FUNCTIONS
        # =============================================================================
        
        def fn_get_base_rent_output():
            """Get the base rent output dataframes for external use."""
            return {
                'monthly': base_rent_collections_monthly,
                'annual': base_rent_collections_annual,
                'by_tenant_monthly': base_rent_collections_by_tenant_monthly,
                'by_tenant_annual': base_rent_collections_by_tenant_annual
            }

        # =============================================================================
        # EXPORT TO EXCEL (DEBUG)
        # =============================================================================

        def fn_export_to_excel(results, output_file=None):
            """Export base rent results to Excel for debugging."""
            # global_num_assets, _period_ends_ts, _num_periods
            
            if output_file is None:
                output_file = os.path.join(os.path.dirname(__file__), "Base_Rent_Output.xlsx")
            
            tenant_applicability = fn_get_tenant_applicability()
            
            # Aggregate by year
            def aggregate_by_year(rent_df):
                yearly_totals = {}
                for col_idx in range(_num_periods):
                    year = _period_ends_ts[col_idx].year
                    period_total = rent_df.iloc[:, col_idx].sum()
                    if year not in yearly_totals:
                        yearly_totals[year] = 0.0
                    yearly_totals[year] += period_total
                return yearly_totals
            
            yearly_t1 = aggregate_by_year(results["tenant1"]["collectible_rent"])
            yearly_renewal = aggregate_by_year(results["renewal"]["collectible_rent"])
            yearly_t2 = aggregate_by_year(results["tenant2"]["collectible_rent"])
            all_years = sorted(set(yearly_t1.keys()) | set(yearly_renewal.keys()) | set(yearly_t2.keys()))
            
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                # Sheet 1: Summary by Units
                unit_summary_data = []
                for asset_idx in range(_num_assets):
                    unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                    asset_name = str(fn_safe_get(Unit.UnitInputs.asset_name, asset_idx))
                    
                    t1_rent = results["tenant1"]["collectible_rent"].loc[asset_idx].sum()
                    renewal_rent = results["renewal"]["collectible_rent"].loc[asset_idx].sum()
                    t2_rent = results["tenant2"]["collectible_rent"].loc[asset_idx].sum()
                    total_rent = t1_rent + renewal_rent + t2_rent
                    
                    unit_summary_data.append({
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "T1 Applicable": "Yes" if fn_safe_get(tenant_applicability["tenant1"], asset_idx) else "No",
                        "Renewal Applicable": "Yes" if fn_safe_get(tenant_applicability["renewal"], asset_idx) else "No",
                        "T2 Applicable": "Yes" if fn_safe_get(tenant_applicability["tenant2"], asset_idx) else "No",
                        "Tenant1 Rent": t1_rent,
                        "Renewal Rent": renewal_rent,
                        "Tenant2 Rent": t2_rent,
                        "Total Rent": total_rent,
                    })
                
                df_unit_summary = pd.DataFrame(unit_summary_data)
                df_unit_summary.to_excel(writer, sheet_name="Summary by Units", index=False)
                
                # Sheet 2: Summary by Years
                year_summary_data = []
                for year in all_years:
                    t1_val = yearly_t1.get(year, 0)
                    renewal_val = yearly_renewal.get(year, 0)
                    t2_val = yearly_t2.get(year, 0)
                    year_total = t1_val + renewal_val + t2_val
                    
                    if year_total > 0:
                        year_summary_data.append({
                            "Year": year,
                            "Tenant1 Rent": t1_val,
                            "Renewal Rent": renewal_val,
                            "Tenant2 Rent": t2_val,
                            "Total Rent": year_total,
                        })
                
                df_year_summary = pd.DataFrame(year_summary_data)
                df_year_summary.to_excel(writer, sheet_name="Summary by Years", index=False)
                
                # Sheet 3-5: Monthly collections by tenant
                for tenant_type, sheet_name in [("tenant1", "T1 Collections"), ("renewal", "Renewal Collections"), ("tenant2", "T2 Collections")]:
                    df_rent = results[tenant_type]["collectible_rent"].copy()
                    df_rent.insert(0, "Unit ID", [fn_safe_get(Unit.UnitInputs.unit_id, i, f"Unit {i}") for i in range(_num_assets)])
                    df_rent.insert(1, "Asset Name", [fn_safe_get(Unit.UnitInputs.asset_name, i, "") for i in range(_num_assets)])
                    df_rent.to_excel(writer, sheet_name=sheet_name, index=False)
                
                # Sheet 6-8: Escalated rent by tenant (actuals + forecast before collection adjustment)
                for tenant_type, sheet_name in [("tenant1", "Escalated Rent T1"), ("renewal", "Escalated Rent Renewal"), ("tenant2", "Escalated Rent T2")]:
                    df_esc = results[tenant_type]["escalated_rent"].copy()
                    df_esc.insert(0, "Unit ID", [fn_safe_get(Unit.UnitInputs.unit_id, i, f"Unit {i}") for i in range(_num_assets)])
                    df_esc.insert(1, "Asset Name", [fn_safe_get(Unit.UnitInputs.asset_name, i, "") for i in range(_num_assets)])
                    df_esc.to_excel(writer, sheet_name=sheet_name, index=False)
                
                # Monthly & Annual Collections totals (single line for output module)
                base_rent_collections_monthly.to_excel(writer, sheet_name="Monthly Collections", index=True)
                base_rent_collections_annual.to_excel(writer, sheet_name="Annual Collections", index=True)
            
            # # print(f"✅ Output exported to: {output_file}")
            return output_file
        
        # Output DataFrames for cashflow/output module
        turnover_rent_collections_monthly = None
        turnover_rent_collections_annual = None
        turnover_rent_by_tenant_monthly = None
        turnover_rent_by_tenant_annual = None
        all_turnover_results = None


        # =============================================================================
        # ACTUAL SALES DATA FROM SCHEDULE TAB (NAMED RANGES)
        # =============================================================================

        def fn_get_actual_sales_from_schedule(tenant_type):
            """
            Retrieve actual sales data from the schedule tab named ranges.
            Named ranges: a.t1.actual.sales.data (Tenant 1), a.t2.actual.sales.data (Tenant 2)
            
            Returns: List of lists or None if not found
            """
            # globalassumptions
            cache_key = ("actual_sales_schedule", tenant_type)
            cached = _local_cache_get(local_cache, cache_key)
            if cached is not None:
                return cached
            
            try:
                if tenant_type == "tenant1_and_renewal":
                    named_range = "s.assetco.t1.actual.sales.data"
                else:  # tenant2
                    named_range = "s.assetco.t2.actual.sales.data"
                
                actual_sales = assumptions.loc[
                    assumptions["name"] == named_range, "value"
                ]
                
                if actual_sales.empty:
                    # DEBUG: # print all named ranges containing 'sales'
                    # # print(f"⚠️ Named range '{named_range}' not found. Searching for alternatives...")
                    sales_ranges = [n for n in assumptions["name"] if "sales" in n.lower()]
                    # # print(f"   Available sales-related ranges: {sales_ranges[:10]}")
                    _local_cache_set(local_cache, cache_key, None)
                    return None
                
                result = actual_sales.iloc[0]
                _local_cache_set(local_cache, cache_key, result)
                return result
            
            except Exception as e:
                print(f"⚠️ Error getting actual sales for {tenant_type}: {e}")
                return None


        def fn_get_sales_mode(asset_idx, tenant_type):
            """
            Determine the sales mode based on the sales_turnover variable.
            
            Dropdown values from Excel:
            - "Actuals" - Use only actuals, zeros for periods without actuals
            - "Actuals + Forecast" - Use actuals where available, forecast for remaining periods
            - "Forecast" - Use only forecast, ignore actuals entirely
            
            Returns: str - one of:
                - "actuals_and_forecast": Use actuals where available, forecast for remaining periods
                - "actuals_only": Use only actuals, zeros for periods without actuals
                - "forecast_only": Use only forecast, ignore actuals entirely
            """
            # Get sales turnover setting
            if tenant_type == "tenant1_and_renewal":
                sales_turnover = fn_safe_get(Unit.SalesAssumptionsFirstTenantandRenewal.sales_turnover, asset_idx)
            else:  # tenant2
                sales_turnover = fn_safe_get(Unit.SalesAssumptionsSecondTenant.sales_turnover, asset_idx)
            
            if sales_turnover is None or pd.isna(sales_turnover):
                return "forecast_only"  # Default to forecast if not specified
            
            if isinstance(sales_turnover, str):
                # Normalize: trim whitespace and convert to lowercase
                sales_turnover_normalized = sales_turnover.strip().lower()
                
                # Check for "Actuals + Forecast" (with spaces, the exact dropdown value)
                if sales_turnover_normalized in ["actuals + forecast", "actuals+forecast", "actual + forecast", "actual+forecast"]:
                    return "actuals_and_forecast"
                
                # Check for "Actuals" only (exact match, not containing "forecast")
                if sales_turnover_normalized in ["actuals", "actual"]:
                    return "actuals_only"
                
                # Check for "Forecast" only (exact match)
                if sales_turnover_normalized == "forecast":
                    return "forecast_only"
            
            # Default to forecast if unclear
            return "forecast_only"


        def fn_get_agreement_type_mode(asset_idx, tenant_type, is_renewal_period=False):
            """
            Parse agreement type and return standardized mode.
            
            Agreement Types from Excel:
            - "Base Only" → Only compute base rent, no TOR
            - "TOR Only" → Only compute TOR rent, no base rent
            - "Base+TOR" → Compute both base and TOR rent
            
            Returns: str - one of "base_only", "tor_only", "base_tor"
            """
            # Get agreement type based on tenant type
            if tenant_type in ["tenant1", "tenant1_and_renewal"]:
                if is_renewal_period:
                    agreement_type = fn_safe_get(Unit.RentParametersRenewal.agreement_type, asset_idx)
                else:
                    agreement_type = fn_safe_get(Unit.RentParametersFirstTenant.agreement_type, asset_idx)
            elif tenant_type == "renewal":
                agreement_type = fn_safe_get(Unit.RentParametersRenewal.agreement_type, asset_idx)
            else:  # tenant2
                agreement_type = fn_safe_get(Unit.RentParametersSecondTenant.agreement_type, asset_idx)
            
            if agreement_type is None or pd.isna(agreement_type):
                return "base_only"  # Default to base only if not specified
            
            if isinstance(agreement_type, str):
                agreement_lower = agreement_type.lower().strip()
                
                # Check for "TOR Only" or "Turnover Only"
                if agreement_lower in ["tor only", "turnover only", "tor_only"]:
                    return "tor_only"
                
                # Check for "Base+TOR" or "Base + TOR" or similar
                if "base" in agreement_lower and ("tor" in agreement_lower or "turnover" in agreement_lower):
                    return "base_tor"
                
                # Check for "Base Only"
                if agreement_lower in ["base only", "base_only", "base"]:
                    return "base_only"
                
                # Legacy check: if "tor" or "turnover" is mentioned without "base", treat as base+tor
                if "tor" in agreement_lower or "turnover" in agreement_lower:
                    return "base_tor"
            
            return "base_only"  # Default


        def fn_should_compute_base_rent(asset_idx, tenant_type, is_renewal_period=False):
            """Check if base rent should be computed for this unit/tenant."""
            mode = fn_get_agreement_type_mode(asset_idx, tenant_type, is_renewal_period)
            return mode in ["base_only", "base_tor"]


        def fn_should_compute_tor(asset_idx, tenant_type, is_renewal_period=False):
            """Check if TOR should be computed for this unit/tenant."""
            mode = fn_get_agreement_type_mode(asset_idx, tenant_type, is_renewal_period)
            return mode in ["tor_only", "base_tor"]


        def fn_should_use_actual_sales(asset_idx, tenant_type, is_renewal_period=False):
            """
            Determine if actual sales should be used based on:
            1. Agreement type includes TOR ('TOR Only' or 'Base+TOR')
            2. Sales turnover is 'Actuals+Forecast' or 'Actuals'
            
            Returns: bool
            """
            # Check if TOR is applicable for this agreement type
            should_compute_tor = fn_should_compute_tor(asset_idx, tenant_type, is_renewal_period)
            
            if not should_compute_tor:
                return False
            
            # Check sales turnover type - use actuals if mode is not forecast_only
            sales_mode = fn_get_sales_mode(asset_idx, tenant_type)
            use_actuals = sales_mode in ["actuals_and_forecast", "actuals_only"]
            
            return use_actuals


        def fn_check_unit_type_for_tor(asset_idx):
            """
            Check if the unit type allows TOR to be applicable.
            TOR is now allowed for ALL unit types from ProjectDetails (not just Retail).
            
            Returns: bool - Always True (TOR applicable for all unit types)
            """
            # TOR is allowed for all unit types - no restriction
            return True


        # Legacy function for backward compatibility
        def fn_check_unit_type_retail(asset_idx):
            """
            DEPRECATED: Use fn_check_unit_type_for_tor() instead.
            Now allows TOR for all unit types, not just Retail.
            
            Returns: bool - Always True
            """
            return fn_check_unit_type_for_tor(asset_idx)


        # =============================================================================
        # PRE-EXTRACT PERIOD ARRAYS FOR PERFORMANCE
        # =============================================================================
        # These will be set in fn_initialize_module()


        # =============================================================================
        # TENANT TYPE CONFIGURATION FOR TURNOVER RENT
        # =============================================================================

        def fn_get_turnover_config():
            """Get turnover rent configuration after Unit class is initialized."""
            return {
                "tenant1_and_renewal": {
                    "sales_params": Unit.SalesAssumptionsFirstTenantandRenewal,
                    "turnover_params_t1": Unit.TurnoverRent_FirstTenant,
                    "turnover_params_renewal": Unit.TurnoverRentFirstTenantRenewal,
                    "lease_params_t1": Unit.LeaseParametersFirstTenant,
                    "lease_params_renewal": Unit.LeaseParametersRenewal,
                },
                "tenant2": {
                    "sales_params": Unit.SalesAssumptionsSecondTenant,
                    "turnover_params": Unit.TurnoverRentSecondTenant,
                    "lease_params": Unit.LeaseParametersSecondTenant,
                },
            }


        # =============================================================================
        # HELPER FUNCTIONS
        # =============================================================================

        # fn_get_tenant_applicability is defined earlier in Module 03


        def fn_get_sales_growth_profile(profile_name):
            """
            Retrieve sales growth profile rates by profile name.
            Named ranges: 
            - a.tenant.sales.growth.rate.profiles (row headers)
            - a.tenant.sales.growth.rates (values, rows=profiles, columns=years)
            """
            # globalassumptions
            cache_key = ("sales_growth_profile", profile_name)
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached
            try:
                # Get profiles row headers
                profiles_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant.sales.growth.rate.profiles", "value"
                ]
                if profiles_df.empty:
                    return None
                profiles = profiles_df.iloc[0]
                
                # Get growth rates (correct named range)
                growth_rates_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant.sales.growth.rates", "value"
                ]
                if growth_rates_df.empty:
                    return None
                growth_rates = growth_rates_df.iloc[0]
                
                # Handle profile_name being None or empty
                if profile_name is None or (isinstance(profile_name, str) and profile_name.strip() == ""):
                    return None
                
                if isinstance(profiles, list) and profile_name in profiles:
                    profile_idx = profiles.index(profile_name)
                else:
                    return None
                
                if isinstance(growth_rates, list) and len(growth_rates) > profile_idx:
                    row = growth_rates[profile_idx]
                    result = row if isinstance(row, list) else [row]
                    _local_cache_set(profile_cache, cache_key, result)
                    return result
                
                _local_cache_set(profile_cache, cache_key, [])
                return []
                
            except Exception as e:
                print(f"⚠️ Error getting sales growth profile: {e}")
                return None


        def fn_get_lease_dates_for_turnover(asset_idx, tenant_type, renewal_flags):
            """
            Get lease start and end dates for turnover rent calculation.
            
            For tenant1_and_renewal:
            - Start: T1 lease start
            - End: If renewal=Yes, renewal end; else T1 end
            
            For tenant2:
            - Start: T2 lease start
            - End: T2 lease end
            """
            def parse_date(val):
                """Safely parse date value, return None if invalid."""
                if val is None:
                    return None
                if isinstance(val, str) and val.strip() == "":
                    return None
                if pd.isna(val):
                    return None
                try:
                    return pd.to_datetime(val)
                except:
                    return None
            
            if tenant_type == "tenant1_and_renewal":
                lease_start = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx)
                
                renewal_flag = fn_safe_get(renewal_flags, asset_idx)
                if renewal_flag:
                    lease_end = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx)
                else:
                    lease_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                    
            else:  # tenant2
                lease_start = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx)
                lease_end = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx)
            
            lease_start = parse_date(lease_start)
            lease_end = parse_date(lease_end)
                
            return lease_start, lease_end


        def fn_parse_turnover_limit(limit_str):
            """
            Parse turnover limit from string like "Upto 1 Mn", "Upto 1 Million", "Upto 2.5 Mn" etc.
            Returns the numeric value in millions (e.g., "Upto 1 Mn" -> 1.0)
            """
            import re
            
            if limit_str is None:
                return 0.0
            
            if isinstance(limit_str, (int, float)):
                if pd.isna(limit_str):
                    return 0.0
                return float(limit_str)
            
            if not isinstance(limit_str, str):
                return 0.0
            
            # Try to extract number from string like "Upto 1 Mn", "Upto 1 Million", "Upto 2.5 Mn"
            # Pattern: look for numbers (including decimals)
            match = re.search(r'[\d.]+', limit_str)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    return 0.0
            
            return 0.0


        def fn_check_tor_applicable(asset_idx, tenant_type, is_renewal_period=False, renewal_flags=None):
            """
            Check if turnover rent is applicable based on:
            1. Agreement type is 'TOR Only' or 'Base+TOR'
            2. For renewal period, renewal flag must be Yes
            
            Note: TOR is now allowed for ALL unit types (not just Retail).
            
            Args:
                asset_idx: Asset index
                tenant_type: "tenant1_and_renewal" or "tenant2"
                is_renewal_period: True if checking for renewal period
                renewal_flags: List of renewal flags for all assets (required for renewal check)
            
            Returns: bool - True if TOR is applicable
            """
            # Check if agreement type allows TOR
            if not fn_should_compute_tor(asset_idx, tenant_type, is_renewal_period):
                return False
            
            if tenant_type == "tenant1_and_renewal":
                if is_renewal_period:
                    # For renewal period, must have renewal flag = Yes
                    if renewal_flags is not None:
                        renewal_flag = fn_safe_get(renewal_flags, asset_idx)
                        if not renewal_flag:
                            return False
            
            return True


        def fn_get_turnover_params(asset_idx, tenant_type, is_renewal_period=False):
            """
            Get turnover rent parameters (limits, percentages, ratchet) for a given tenant type.
            
            For tenant1_and_renewal during renewal period, use renewal params.
            """
            if tenant_type == "tenant1_and_renewal":
                if is_renewal_period:
                    params = Unit.TurnoverRentFirstTenantRenewal
                else:
                    params = Unit.TurnoverRent_FirstTenant
            else:  # tenant2
                params = Unit.TurnoverRentSecondTenant
            
            # Get limits and percentages using safe access
            limit_1_raw = fn_safe_get(params.turnover_limit_1, asset_idx, 0) if hasattr(params, 'turnover_limit_1') else 0
            limit_2_raw = fn_safe_get(params.turnover_limit_2, asset_idx, 0) if hasattr(params, 'turnover_limit_2') else 0
            limit_3_raw = fn_safe_get(params.turnover_limit_3, asset_idx, 0) if hasattr(params, 'turnover_limit_3') else 0
            
            pct_1 = fn_safe_get(params.turnover_rent__percent_1, asset_idx, 0) if hasattr(params, 'turnover_rent__percent_1') else 0
            pct_2 = fn_safe_get(params.turnover_rent_percent_2, asset_idx, 0) if hasattr(params, 'turnover_rent_percent_2') else 0
            pct_3 = fn_safe_get(params.turnover_rent_percent_3, asset_idx, 0) if hasattr(params, 'turnover_rent_percent_3') else 0
            
            ratchet = fn_safe_get(params.ratchet_percentage, asset_idx, 0) if hasattr(params, 'ratchet_percentage') else 0
            
            # Parse limits from strings like "Upto 1 Mn" or "Upto 1 Million"
            limit_1 = fn_parse_turnover_limit(limit_1_raw)
            limit_2 = fn_parse_turnover_limit(limit_2_raw)
            limit_3 = fn_parse_turnover_limit(limit_3_raw)
            
            # Helper function to convert percentages to float
            def to_float(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return 0.0
                if isinstance(val, str):
                    try:
                        return float(val)
                    except ValueError:
                        return 0.0
                return float(val)
            
            # Clean NaN values and convert percentages to float
            pct_1 = to_float(pct_1)
            pct_2 = to_float(pct_2)
            pct_3 = to_float(pct_3)
            ratchet = to_float(ratchet)
            
            # Convert limits from millions to actual values
            limit_1 = limit_1 * 1_000_000
            limit_2 = limit_2 * 1_000_000
            limit_3 = limit_3 * 1_000_000
            
            # Sort limits in ascending order with their percentages
            limits_pcts = [(limit_1, pct_1), (limit_2, pct_2), (limit_3, pct_3)]
            limits_pcts = [(l, p) for l, p in limits_pcts if l > 0]  # Filter out zero limits
            limits_pcts.sort(key=lambda x: x[0])  # Sort by limit ascending
            
            return limits_pcts, ratchet


        # =============================================================================
        # SALES VALUE COMPUTATION
        # =============================================================================

        def fn_compute_all_escalated_sales_density_vectorized(tenant_type, renewal_flags):
            """VECTORIZED: Compute escalated sales density for ALL assets at once.
            
            Uses numpy broadcasting instead of per-asset loops.
            Returns: numpy array of shape (_num_assets, _num_periods)
            """
            config = fn_get_turnover_config()[tenant_type]
            sales_params = config["sales_params"]
            
            result = np.zeros((_num_assets, _num_periods))
            
            # Pre-compute period timestamps
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts])
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts])
            period_years = np.array([_period_starts_ts[i].year for i in range(_num_periods)])
            
            # Cache for growth profiles
            growth_profile_cache = {}
            
            for i in range(_num_assets):
                sales_density = fn_safe_get(sales_params.sales_density, i)
                growth_profile_name = fn_safe_get(sales_params.sales_growth_profile, i)
                
                if pd.isna(sales_density) or sales_density == 0:
                    continue
                
                # Get lease dates
                lease_start, lease_end = fn_get_lease_dates_for_turnover(i, tenant_type, renewal_flags)
                if pd.isna(lease_start) or lease_start is None:
                    continue
                
                # Get growth rates from cache or compute
                if growth_profile_name not in growth_profile_cache:
                    rates = fn_get_sales_growth_profile(growth_profile_name)
                    growth_profile_cache[growth_profile_name] = rates if rates else []
                growth_rates = growth_profile_cache[growth_profile_name]
                
                lease_start_year = lease_start.year
                lease_start_np = lease_start.to_datetime64()
                lease_end_np = lease_end.to_datetime64() if lease_end is not None and not pd.isna(lease_end) else np.datetime64('2100-12-31')
                
                # Compute mask for valid periods
                valid_mask = (period_ends_np >= lease_start_np) & (period_starts_np <= lease_end_np)
                
                # For each valid period, calculate cumulative growth
                for col_idx in range(_num_periods):
                    if not valid_mask[col_idx]:
                        continue
                    
                    period_year = period_years[col_idx]
                    lease_year_number = period_year - lease_start_year + 1
                    
                    cumulative_growth = 1.0
                    for yr in range(1, lease_year_number + 1):
                        if yr <= len(growth_rates):
                            rate = growth_rates[yr - 1]
                            if rate is not None and not pd.isna(rate):
                                cumulative_growth *= (1 + rate)
                    
                    result[i, col_idx] = sales_density * cumulative_growth
            
            return result


        def fn_compute_all_monthly_sales_vectorized(tenant_type, renewal_flags, actual_sales_data=None):
            """VECTORIZED: Compute monthly sales value for ALL assets at once.
            
            Returns: numpy array of shape (_num_assets, _num_periods)
            """
            result = np.zeros((_num_assets, _num_periods))
            
            # Pre-compute escalated density for all assets
            escalated_density_all = fn_compute_all_escalated_sales_density_vectorized(tenant_type, renewal_flags)
            
            # Pre-compute period timestamps
            period_starts_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_starts_ts])
            period_ends_np = np.array([pd.Timestamp(ts).to_datetime64() for ts in _period_ends_ts])
            
            for i in range(_num_assets):
                # Check if unit type is Retail (skip if not)
                if not fn_check_unit_type_retail(i):
                    continue
                
                # Get lease dates
                lease_start, lease_end = fn_get_lease_dates_for_turnover(i, tenant_type, renewal_flags)
                
                # Get sales mode
                sales_mode = fn_get_sales_mode(i, tenant_type)
                
                # Get GLA - skip assets with zero/missing GLA
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, i, 0)
                if gla is None or pd.isna(gla) or gla == 0:
                    continue
                
                # FORECAST ONLY MODE
                if sales_mode == "forecast_only":
                    # Sales density is annual, divide by 12 for monthly
                    result[i, :] = (escalated_density_all[i, :] / 12) * gla
                    continue
                
                # ACTUALS + FORECAST or ACTUALS ONLY MODE
                if sales_mode == "actuals_and_forecast":
                    # Start with forecast for all periods
                    forecast_sales = (escalated_density_all[i, :] / 12) * gla
                    
                    if lease_start is not None and lease_end is not None:
                        ls_np = lease_start.to_datetime64()
                        le_np = lease_end.to_datetime64()
                        valid_mask = (period_ends_np >= ls_np) & (period_starts_np <= le_np)
                        result[i, :] = np.where(valid_mask, forecast_sales, 0)
                    else:
                        result[i, :] = forecast_sales
                    
                    # Override with actuals where available
                    if actual_sales_data is not None:
                        if isinstance(actual_sales_data, list) and len(actual_sales_data) > i:
                            asset_actuals = actual_sales_data[i]
                            if isinstance(asset_actuals, (list, np.ndarray)):
                                for col_idx in range(min(len(asset_actuals), _num_periods)):
                                    actual_val = asset_actuals[col_idx]
                                    if actual_val is not None and not pd.isna(actual_val) and actual_val != 0 and actual_val != "":
                                        result[i, col_idx] = float(actual_val)
                
                elif sales_mode == "actuals_only":
                    # Only use actuals, zeros elsewhere
                    if actual_sales_data is not None:
                        if isinstance(actual_sales_data, list) and len(actual_sales_data) > i:
                            asset_actuals = actual_sales_data[i]
                            if isinstance(asset_actuals, (list, np.ndarray)):
                                for col_idx in range(min(len(asset_actuals), _num_periods)):
                                    actual_val = asset_actuals[col_idx]
                                    if actual_val is not None and not pd.isna(actual_val) and actual_val != 0 and actual_val != "":
                                        result[i, col_idx] = float(actual_val)
                else:
                    # Default: forecast
                    result[i, :] = (escalated_density_all[i, :] / 12) * gla
            
            return result


        def fn_compute_escalated_sales_density(asset_idx, tenant_type, renewal_flags):
            """
            Compute escalated sales density for each period.
            
            IMPORTANT: For T1+Renewal, there is only ONE sales profile that runs continuously
            from T1 lease start to Renewal lease end. The escalation is computed based on
            years from T1 start (Year 1 = T1 start year).
            
            - Year 1 = T1 lease start year (not calendar year)
            - Escalation from sales growth profile based on year number from T1 start
            - Covers the entire period from T1 start to Renewal end (if renewal exists)
            
            Returns: Series of escalated sales density per period
            """
            # global_num_periods
            config = fn_get_turnover_config()[tenant_type]
            sales_params = config["sales_params"]
            
            # Use safe access for list attributes
            sales_density = fn_safe_get(sales_params.sales_density, asset_idx)
            growth_profile_name = fn_safe_get(sales_params.sales_growth_profile, asset_idx)
            
            # Get lease dates
            lease_start, lease_end = fn_get_lease_dates_for_turnover(asset_idx, tenant_type, renewal_flags)
            
            # Initialize result
            result = np.zeros(_num_periods)
            
            if pd.isna(sales_density) or sales_density == 0:
                return pd.Series(result, index=range(_num_periods))
            
            if pd.isna(lease_start):
                return pd.Series(result, index=range(_num_periods))
            
            # Get growth rates from profile
            growth_rates = fn_get_sales_growth_profile(growth_profile_name)
            if growth_rates is None:
                growth_rates = []
            
            # Determine lease start year (Year 1)
            lease_start_year = lease_start.year
            
            # For each period, compute the escalated sales density
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                # Check if period is within lease term
                if lease_end is not None and not pd.isna(lease_end):
                    if period_start > lease_end or period_end < lease_start:
                        continue
                else:
                    if period_end < lease_start:
                        continue
                
                # Determine what year of the lease this period falls in
                period_year = period_start.year
                lease_year_number = period_year - lease_start_year + 1  # Year 1, 2, 3, etc.
                
                # Get cumulative growth rate up to this year
                cumulative_growth = 1.0
                for yr in range(1, lease_year_number + 1):
                    if yr <= len(growth_rates):
                        rate = growth_rates[yr - 1]
                        if not pd.isna(rate):
                            cumulative_growth *= (1 + rate)
                
                # Escalated sales density for this period
                escalated_density = sales_density * cumulative_growth
                result[col_idx] = escalated_density
            
            return pd.Series(result, index=range(_num_periods))


        def fn_get_t1_lease_dates(asset_idx):
            """
            Get T1 lease start and end dates.
            Returns: (t1_start, t1_end) as Timestamps or None
            """
            def parse_date(val):
                if val is None or pd.isna(val):
                    return None
                try:
                    return pd.to_datetime(val)
                except:
                    return None
            
            t1_start = parse_date(fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx))
            t1_end = parse_date(fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx))
            return t1_start, t1_end


        def fn_get_renewal_lease_dates(asset_idx):
            """
            Get Renewal lease start and end dates.
            Returns: (renewal_start, renewal_end) as Timestamps or None
            """
            def parse_date(val):
                if val is None or pd.isna(val):
                    return None
                try:
                    return pd.to_datetime(val)
                except:
                    return None
            
            renewal_start = parse_date(fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, asset_idx))
            renewal_end = parse_date(fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx))
            return renewal_start, renewal_end


        def fn_compute_monthly_sales_value(asset_idx, tenant_type, renewal_flags, actual_sales_data=None):
            """
            Compute monthly sales value based on sales turnover type.
            
            IMPORTANT: Sales should NOT be computed if unit type is not 'Retail'
            
            Sales Mode Logic (based on dropdown values: Actuals, Actuals + Forecast, Forecast):
            - "actuals_and_forecast" (Actuals + Forecast): Use actuals within lease period, forecast for remaining
            - "actuals_only" (Actuals): Use only actuals within lease period, zeros elsewhere
            - "forecast_only" (Forecast): Use only forecast, ignore actuals entirely
            
            KEY LOGIC for T1+Renewal:
            - Sales FORECAST: Computed continuously from T1 start to Renewal end (one sales profile)
            - Sales ACTUALS: Fetched only for months within the lease period
            - T1 actuals: Only for periods within T1 lease start to T1 lease end
            - Renewal actuals: Only for periods within Renewal lease start to Renewal lease end
            - For TOR calculation: Sales used for T1 and T1 Renewal are INDEPENDENT of their lease periods
            
            Returns: Series of monthly sales values
            """
            # Initialize result
            result = np.zeros(_num_periods)
            
            # Check if unit type is Retail - if not, return zeros (no sales computation)
            if not fn_check_unit_type_retail(asset_idx):
                return pd.Series(result, index=range(_num_periods))
            
            # Get lease dates for period filtering (T1 start to Renewal end for continuous sales)
            lease_start, lease_end = fn_get_lease_dates_for_turnover(asset_idx, tenant_type, renewal_flags)
            
            # Get sales mode
            sales_mode = fn_get_sales_mode(asset_idx, tenant_type)
            
            # Get T1 and Renewal dates separately for actuals validation
            t1_start, t1_end = fn_get_t1_lease_dates(asset_idx)
            renewal_start, renewal_end = fn_get_renewal_lease_dates(asset_idx)
            has_renewal = fn_safe_get(renewal_flags, asset_idx) if tenant_type == "tenant1_and_renewal" else False
            
            # If renewal_start is not specified, assume it's the day after T1 end
            if has_renewal and renewal_start is None and t1_end is not None:
                renewal_start = t1_end + pd.Timedelta(days=1)
            
            # ==========================================================================
            # FORECAST ONLY MODE
            # ==========================================================================
            if sales_mode == "forecast_only":
                # Use forecast sales (escalated sales density × GLA) from T1 start to Renewal end
                escalated_density = fn_compute_escalated_sales_density(asset_idx, tenant_type, renewal_flags)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx, 0)
                if gla is None or pd.isna(gla) or gla == 0:
                    return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                # Sales density is annual, divide by 12 for monthly
                return (escalated_density / 12) * gla
            
            # ==========================================================================
            # ACTUALS ONLY or ACTUALS+FORECAST MODE
            # ==========================================================================
            if actual_sales_data is not None:
                try:
                    # For ACTUALS+FORECAST: Start with forecast for ALL periods, then overwrite with actuals
                    if sales_mode == "actuals_and_forecast":
                        escalated_density = fn_compute_escalated_sales_density(asset_idx, tenant_type, renewal_flags)
                        gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx, 0)
                        if gla is None or pd.isna(gla) or gla == 0:
                            return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                        forecast_sales = (escalated_density / 12) * gla
                        
                        # Fill ALL periods within lease with forecast first
                        for col_idx in range(_num_periods):
                            period_start = _period_starts_ts[col_idx]
                            period_end = _period_ends_ts[col_idx]
                            
                            if lease_start is not None and period_end < lease_start:
                                continue
                            if lease_end is not None and period_start > lease_end:
                                continue
                            
                            result[col_idx] = forecast_sales.iloc[col_idx]
                    
                    # Now overwrite with actuals where they exist (non-zero values)
                    if isinstance(actual_sales_data, list) and len(actual_sales_data) > asset_idx:
                        asset_actuals = actual_sales_data[asset_idx]
                        
                        if isinstance(asset_actuals, (list, np.ndarray)):
                            for col_idx in range(min(len(asset_actuals), _num_periods)):
                                actual_val = asset_actuals[col_idx]
                                if actual_val is not None and not pd.isna(actual_val) and actual_val != 0 and actual_val != "":
                                    result[col_idx] = float(actual_val)
                    
                    return pd.Series(result, index=range(_num_periods))
                
                except Exception as e:
                    print(f"⚠️ Error using actual sales for asset {asset_idx}: {e}")
            
            # ==========================================================================
            # FALLBACK: If no actuals data provided but mode requires actuals
            # ==========================================================================
            if sales_mode == "actuals_only":
                # No actuals available, return zeros
                return pd.Series(result, index=range(_num_periods))
            
            # Default fallback for actuals_and_forecast with no actual data: Use forecast
            escalated_density = fn_compute_escalated_sales_density(asset_idx, tenant_type, renewal_flags)
            gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx, 0)
            
            if gla is None or pd.isna(gla) or gla == 0:
                return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            # Sales density is annual, divide by 12 for monthly
            return (escalated_density / 12) * gla


        # =============================================================================
        # LEASE YEAR COMPUTATION
        # =============================================================================

        def fn_get_lease_years(asset_idx, tenant_type, renewal_flags):
            """
            Compute lease years for turnover rent calculation.
            
            A lease year runs from the lease start month to the same month next year.
            E.g., if lease starts April 2019, Year 1 = April 2019 - March 2020.
            
            IMPORTANT FOR T1+RENEWAL:
            - T1 period has its own lease years with T1's last year ending at T1 expiration
            - Renewal period has its own lease years starting fresh from renewal start
            - Each period (T1 and Renewal) has its own "last year" with proper TOR collection
            
            LAST YEAR LOGIC:
            - Last year is identified when lease end date falls before completing 12 months
            - For last year: TOR is collected in the EXIT MONTH (same month as lease end)
            - Last year TOR = (Actual Sales for Operating Months) × TOR%
            where TOR% is determined using ANNUALIZED sales = (Actual Sales × 12) / Months Operating
            
            Returns: List of dictionaries with year_num, start, end, collection_period_idx, is_last_year, months_in_year, is_renewal_period
            """
            
            def parse_date(val):
                if val is None or pd.isna(val):
                    return None
                try:
                    return pd.to_datetime(val)
                except:
                    return None
            
            all_lease_years = []
            
            if tenant_type == "tenant1_and_renewal":
                # Get T1 dates
                t1_start = parse_date(fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx))
                t1_end = parse_date(fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx))
                
                if t1_start is None:
                    return []
                
                # Compute T1 lease years
                t1_lease_years = _compute_lease_years_for_period(t1_start, t1_end, is_renewal_period=False)
                all_lease_years.extend(t1_lease_years)
                
                # If renewal exists, compute renewal lease years separately
                if fn_safe_get(renewal_flags, asset_idx):
                    renewal_start = parse_date(fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, asset_idx))
                    renewal_end = parse_date(fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx))
                    
                    # If renewal start is not specified, assume it's the day after T1 end
                    if renewal_start is None and t1_end is not None:
                        renewal_start = t1_end + relativedelta(days=1)
                    
                    if renewal_start is not None and renewal_end is not None:
                        # Renewal lease years start with Year 1 for renewal (fresh numbering)
                        renewal_lease_years = _compute_lease_years_for_period(renewal_start, renewal_end, is_renewal_period=True)
                        all_lease_years.extend(renewal_lease_years)
            
            elif tenant_type == "tenant2":
                t2_start = parse_date(fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx))
                t2_end = parse_date(fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx))
                
                if t2_start is None:
                    return []
                
                t2_lease_years = _compute_lease_years_for_period(t2_start, t2_end, is_renewal_period=False)
                all_lease_years.extend(t2_lease_years)
            
            return all_lease_years


        def _compute_lease_years_for_period(lease_start, lease_end, is_renewal_period=False):
            """
            Helper function to compute lease years for a specific lease period.
            
            Args:
                lease_start: Start date of the lease period
                lease_end: End date of the lease period
                is_renewal_period: Whether this is a renewal period (for tracking)
            
            Returns: List of lease year dictionaries
            """
            if lease_start is None:
                return []
            
            lease_years = []
            year_num = 1
            current_start = lease_start
            
            # First pass: collect all lease years
            temp_lease_years = []
            while True:
                # Year ends one year after start (or at lease end if sooner)
                year_end = current_start + relativedelta(years=1) - relativedelta(days=1)
                
                is_last_year = False
                if lease_end is not None and not pd.isna(lease_end):
                    if current_start > lease_end:
                        break
                    if year_end >= lease_end:
                        year_end = lease_end
                        is_last_year = True
                
                # Calculate months in this lease year
                months_in_year = 0
                for idx in range(_num_periods):
                    period_start = _period_starts_ts[idx]
                    period_end = _period_ends_ts[idx]
                    if period_end < current_start or period_start > year_end:
                        continue
                    months_in_year += 1
                
                temp_lease_years.append({
                    "year_num": year_num,
                    "start": current_start,
                    "end": year_end,
                    "is_last_year": is_last_year,
                    "months_in_year": months_in_year,
                    "is_renewal_period": is_renewal_period
                })
                
                # Move to next year
                current_start = year_end + relativedelta(days=1)
                year_num += 1
                
                # Safety check
                if year_num > 100:
                    break
                
                # Stop if we've passed the lease end
                if lease_end is not None and not pd.isna(lease_end):
                    if current_start > lease_end:
                        break
            
            # Mark the actual last year (the final lease year is always the last year)
            if temp_lease_years:
                temp_lease_years[-1]["is_last_year"] = True
            
            # Second pass: determine collection period for each lease year
            for ly in temp_lease_years:
                year_end = ly["end"]
                is_last_year = ly["is_last_year"]
                months_in_year = ly["months_in_year"]
                
                # CRITICAL: TOR collection logic
                # For LAST YEAR (partial or full):
                #   - Collect in EXIT MONTH (same month as lease end)
                #   - The lease is ending; there is no next period to defer to
                # For non-last years:
                #   - TOR is collected in first month of NEXT lease year
                
                if is_last_year:
                    # Last year: always collect in exit month irrespective of duration
                    collection_date = year_end
                else:
                    # Non-last years: collect TOR in first month after year end
                    collection_date = year_end + relativedelta(days=1)
                
                collection_period_idx = None
                for idx in range(_num_periods):
                    period_start = _period_starts_ts[idx]
                    period_end = _period_ends_ts[idx]
                    if period_start <= collection_date <= period_end:
                        collection_period_idx = idx
                        break
                
                # If collection date is after model end, use last period
                if collection_period_idx is None and collection_date > _period_ends_ts[-1]:
                    collection_period_idx = _num_periods - 1
                
                lease_years.append({
                    "year_num": ly["year_num"],
                    "start": ly["start"],
                    "end": year_end,
                    "collection_period_idx": collection_period_idx,
                    "is_last_year": is_last_year,
                    "months_in_year": ly["months_in_year"],
                    "is_renewal_period": is_renewal_period
                })
            
            return lease_years


        # =============================================================================
        # TURNOVER RENT COMPUTATION
        # =============================================================================

        def fn_compute_turnover_rent_for_period(annual_sales, limits_pcts):
            """
            Compute turnover rent based on annual sales and tiered limits/percentages.
            
            Limits are checked in order: threshold 1, then 2, then 3.
            - If sales <= limit_1: use pct_1
            - Else if sales <= limit_2: use pct_2  
            - Else if sales <= limit_3: use pct_3
            - Else (sales > all limits): use pct_3 (last bracket)
            
            When all thresholds have the same limit (e.g., all 1 Mn):
            - Check threshold 1 first: if sales > 1 Mn, fail
            - Check threshold 2: if sales > 1 Mn, fail
            - Check threshold 3: if sales > 1 Mn, fail
            - Since all fail, use threshold 3's percentage
            """
            if not limits_pcts or annual_sales <= 0:
                return 0, 0
            
            # Check brackets in order (1, 2, 3)
            # If sales <= limit, use that bracket's percentage
            # If sales > all limits, use the last bracket's percentage
            applicable_pct = 0
            
            for i, (limit, pct) in enumerate(limits_pcts):
                if annual_sales <= limit:
                    # Sales fall within this bracket
                    applicable_pct = pct
                    break
                else:
                    # Sales exceed this bracket, move to next
                    # Keep tracking the last bracket's percentage
                    applicable_pct = pct
            
            # At this point:
            # - If we found a bracket where sales <= limit, we use that pct
            # - If sales exceeded all limits, applicable_pct = last bracket's pct
            
            return annual_sales * applicable_pct, applicable_pct


        def fn_compute_turnover_rent(asset_idx, tenant_type, renewal_flags, actual_sales_data=None, base_rent_data=None):
            """
            Compute turnover rent for an asset.

            Agreement-type behaviour
            ========================
            **TOR Only**  – full TOR rent is collected.  Running-max ratchet
                           sets a minimum TOR for the year.
            **Base+TOR**  – Running-max ratchet sets a *floor for base rent*:
                             Year 1 : no floor (establishing baseline)
                             Year 2 : floor = ratchet% × TOR(Y1)
                             Year N : floor = MAX(floor_{N-1},
                                                   ratchet% × TOR_{N-1})
                           The floor can only increase, never decrease.
                           Effective base rent = max(forecast_base, floor).
                           If floor > forecast_base, the floor amount is spread
                           equally (/months) and the per-month uplift is returned
                           as base_rent_adjustment.
                           TOR collected = max(0, TOR_computed − effective_base).
                           Floor and TOR are prorated for partial years.
            **Base Only** – no TOR (function exits early via applicability check).

            Renewal probability
            ===================
            NOT applied here.  The caller applies renewal_prob (or 1-prob for T2)
            to the final cashflow numbers.

            Returns
            -------
            (tor_t1_series, tor_renewal_series, base_rent_adj_series)
                tor_t1_series       – TOR for T1 periods (or all TOR for tenant2)
                tor_renewal_series  – TOR for renewal periods (zeros for tenant2)
                base_rent_adj_series – positive base-rent adjustment from ratchet
            """
            tor_t1_result = np.zeros(_num_periods)
            tor_renewal_result = np.zeros(_num_periods)
            base_rent_adj = np.zeros(_num_periods)

            # Get monthly sales values (with actual sales data if available)
            monthly_sales = fn_compute_monthly_sales_value(asset_idx, tenant_type, renewal_flags, actual_sales_data)

            # Get lease years
            lease_years = fn_get_lease_years(asset_idx, tenant_type, renewal_flags)

            if not lease_years:
                z = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                return (z.copy(), z.copy(), z.copy())

            # ------------------------------------------------------------------
            # Pre-fetch monthly RAW base-rent arrays (no renewal probability)
            # ------------------------------------------------------------------
            _br_t1 = None
            _br_ren = None
            _br_t2 = None
            if base_rent_data is not None:
                if tenant_type == "tenant1_and_renewal":
                    t1_cr = base_rent_data.get("tenant1", {}).get("collectible_rent")
                    if t1_cr is not None and asset_idx < len(t1_cr):
                        _br_t1 = t1_cr.iloc[asset_idx].values
                    ren_cr = base_rent_data.get("renewal", {}).get("collectible_rent")
                    if ren_cr is not None and asset_idx < len(ren_cr):
                        _br_ren = ren_cr.iloc[asset_idx].values
                elif tenant_type == "tenant2":
                    t2_cr = base_rent_data.get("tenant2", {}).get("collectible_rent")
                    if t2_cr is not None and asset_idx < len(t2_cr):
                        _br_t2 = t2_cr.iloc[asset_idx].values

            # ------------------------------------------------------------------
            # Ratchet state – running maximum (high-water mark)
            # The floor can only increase, never decrease.
            # ------------------------------------------------------------------
            prev_floor = 0.0             # running-max annual floor
            prev_floor_renewal = 0.0
            prev_tor = 0.0               # previous year’s raw TOR computed
            prev_tor_renewal = 0.0

            for lease_year in lease_years:
                year_num = lease_year["year_num"]
                year_start = lease_year["start"]
                year_end = lease_year["end"]
                collection_idx = lease_year["collection_period_idx"]
                is_last_year = lease_year["is_last_year"]
                is_renewal_period = lease_year.get("is_renewal_period", False)

                if collection_idx is None:
                    continue

                # Applicability check
                if not fn_check_tor_applicable(asset_idx, tenant_type, is_renewal_period, renewal_flags):
                    continue

                # Agreement mode
                mode = fn_get_agreement_type_mode(asset_idx, tenant_type, is_renewal_period)
                is_base_tor = (mode == "base_tor")

                # Turnover parameters (zero limits already filtered)
                limits_pcts, ratchet = fn_get_turnover_params(asset_idx, tenant_type, is_renewal_period)

                # ----------------------------------------------------------
                # Identify months that belong to this lease year
                # ----------------------------------------------------------
                year_month_indices = []
                actual_year_sales = 0.0
                for col_idx in range(_num_periods):
                    ps = _period_starts_ts[col_idx]
                    pe = _period_ends_ts[col_idx]
                    if pe < year_start or ps > year_end:
                        continue
                    year_month_indices.append(col_idx)
                    actual_year_sales += monthly_sales.iloc[col_idx]

                months_in_year = len(year_month_indices)
                if months_in_year == 0:
                    continue

                is_partial_year = months_in_year < 12

                # ----------------------------------------------------------
                # Step A: Compute raw TOR rent from sales brackets
                # ----------------------------------------------------------
                if is_partial_year:
                    annualized_sales = (actual_year_sales * 12) / months_in_year
                else:
                    annualized_sales = actual_year_sales

                _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                tor_rent_computed = actual_year_sales * tor_pct

                # ----------------------------------------------------------
                # Step B: Apply agreement-specific logic
                # ----------------------------------------------------------
                # ----------------------------------------------------------
                # Running-max ratchet floor (high-water mark)
                # Year 1: no floor (establishing baseline)
                # Year 2: floor = ratchet% × TOR(Y1)
                # Year N: floor = MAX(floor_{N-1}, ratchet% × TOR_{N-1})
                # Floor can only increase, never decrease.
                # ----------------------------------------------------------
                if is_renewal_period:
                    _pf, _pt = prev_floor_renewal, prev_tor_renewal
                else:
                    _pf, _pt = prev_floor, prev_tor

                r_floor = 0.0
                if ratchet > 0 and year_num > 1:
                    new_candidate = ratchet * _pt if _pt > 0 else 0.0
                    r_floor = max(_pf, new_candidate)

                # Prorate floor for partial (first/last) years
                if is_partial_year and r_floor > 0:
                    prorated_floor = (r_floor / 12.0) * months_in_year
                else:
                    prorated_floor = r_floor

                if is_base_tor:
                    # ===========================================================
                    # BASE+TOR — ratchet-on-base-rent + differential
                    # ===========================================================

                    # 1. Sum forecast (raw) base rent for this lease year
                    forecast_base_total = 0.0
                    for m in year_month_indices:
                        if tenant_type == "tenant1_and_renewal":
                            if _br_t1 is not None:
                                forecast_base_total += _br_t1[m]
                            if _br_ren is not None:
                                forecast_base_total += _br_ren[m]
                        else:
                            if _br_t2 is not None:
                                forecast_base_total += _br_t2[m]

                    # 2. Effective base = max(forecast, rolling ratchet floor)
                    effective_base = max(forecast_base_total, prorated_floor)

                    # DEBUG ratchet trace
                    print(f"  🔧 RATCHET [{tenant_type}] asset={asset_idx} Y{year_num} "
                          f"mode={mode} months={months_in_year} partial={is_partial_year} "
                          f"ratchet%={ratchet} prev_tor={_pt:,.2f} prev_floor={_pf:,.2f} "
                          f"r_floor={r_floor:,.2f} prorated_floor={prorated_floor:,.2f} "
                          f"forecast_base={forecast_base_total:,.2f} effective_base={effective_base:,.2f} "
                          f"tor_computed={tor_rent_computed:,.2f} sales={actual_year_sales:,.2f} "
                          f"_br_t2={'None' if _br_t2 is None else 'OK'}")

                    # 3. If ratchet floor > forecast → spread ratchet / months
                    #    equally and record the per-month adjustment
                    if prorated_floor > forecast_base_total and months_in_year > 0:
                        ratchet_monthly = prorated_floor / months_in_year
                        for m in year_month_indices:
                            # Original monthly base for this month
                            orig = 0.0
                            if tenant_type == "tenant1_and_renewal":
                                if _br_t1 is not None:
                                    orig += _br_t1[m]
                                if _br_ren is not None:
                                    orig += _br_ren[m]
                            else:
                                if _br_t2 is not None:
                                    orig += _br_t2[m]
                            adj = ratchet_monthly - orig
                            if adj > 0:
                                base_rent_adj[m] += adj

                    # 4. TOR collected = differential (excess over effective base)
                    tor = max(0.0, tor_rent_computed - effective_base)

                    total_adj = sum(base_rent_adj[m] for m in year_month_indices)
                    print(f"        → adj_total={total_adj:,.2f} tor_collected={tor:,.2f}")

                else:
                    # ===========================================================
                    # TOR ONLY — full TOR, ratchet = rolling minimum TOR
                    # ===========================================================
                    tor = tor_rent_computed

                    if year_num > 1 and ratchet > 0 and prorated_floor > 0:
                        tor = max(tor, prorated_floor)

                # ----------------------------------------------------------
                # Store TOR into T1 or renewal result
                # ----------------------------------------------------------
                if tenant_type == "tenant1_and_renewal" and is_renewal_period:
                    tor_renewal_result[collection_idx] += tor
                else:
                    tor_t1_result[collection_idx] += tor

                # ----------------------------------------------------------
                # Update running-max floor + previous TOR for next year
                # ----------------------------------------------------------
                if is_renewal_period:
                    prev_floor_renewal = r_floor
                    prev_tor_renewal = tor_rent_computed
                else:
                    prev_floor = r_floor
                    prev_tor = tor_rent_computed

            idx = range(_num_periods)
            return (
                pd.Series(tor_t1_result, index=idx),
                pd.Series(tor_renewal_result, index=idx),
                pd.Series(base_rent_adj, index=idx),
            )


        # =============================================================================
        # MAIN COMPUTATION FOR ALL ASSETS
        # =============================================================================

        def fn_compute_all_turnover_rent():
            """
            Compute turnover rent for all assets and tenant types.
            
            Returns: Dictionary with results for each tenant type
            """
            # global_num_assets, _num_periods, model_timeline_me
            cache_key = "module:turnover_rent"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            
            applicability = fn_get_tenant_applicability()
            renewal_flags = applicability["renewal_flags"]
            
            # Retrieve actual sales data from schedule tabs
            actual_sales_t1r = fn_get_actual_sales_from_schedule("tenant1_and_renewal")
            actual_sales_t2 = fn_get_actual_sales_from_schedule("tenant2")
            
            # Fetch base rent results for Base+TOR differential computation
            # (base rent module runs before TOR, so results are available)
            base_rent_results = fn_compute_base_rent_all_tenants()
            base_rent_data = base_rent_results if base_rent_results is not None else None
            
            # Create template DataFrames for results
            template_asset_timeline = pd.DataFrame(
                np.zeros((_num_assets, _num_periods)),
                index=range(_num_assets),
                columns=model_timeline_me.index
            )
            
            results = {
                "tenant1_and_renewal": {
                    "monthly_sales": template_asset_timeline.copy(),
                    "turnover_rent": template_asset_timeline.copy(),
                    "turnover_rent_t1": template_asset_timeline.copy(),
                    "turnover_rent_renewal": template_asset_timeline.copy(),
                    "escalated_sales_density": template_asset_timeline.copy(),
                    "base_rent_adj": template_asset_timeline.copy(),
                },
                "tenant2": {
                    "monthly_sales": template_asset_timeline.copy(),
                    "turnover_rent": template_asset_timeline.copy(),
                    "turnover_rent_t1": template_asset_timeline.copy(),
                    "turnover_rent_renewal": template_asset_timeline.copy(),
                    "escalated_sales_density": template_asset_timeline.copy(),
                    "base_rent_adj": template_asset_timeline.copy(),
                },
            }
            
            for tenant_type in ["tenant1_and_renewal", "tenant2"]:
                # print(f"   Processing {tenant_type}...")
                
                applicable = applicability[tenant_type]
                
                # Select appropriate actual sales data
                if tenant_type == "tenant1_and_renewal":
                    actual_sales_data = actual_sales_t1r
                else:
                    actual_sales_data = actual_sales_t2
                
                # VECTORIZED: Compute escalated sales density for ALL assets at once
                esc_density_all = fn_compute_all_escalated_sales_density_vectorized(tenant_type, renewal_flags)
                results[tenant_type]["escalated_sales_density"] = pd.DataFrame(
                    esc_density_all, index=range(_num_assets), columns=model_timeline_me.index
                )
                
                # VECTORIZED: Compute monthly sales for ALL assets at once
                monthly_sales_all = fn_compute_all_monthly_sales_vectorized(tenant_type, renewal_flags, actual_sales_data)
                results[tenant_type]["monthly_sales"] = pd.DataFrame(
                    monthly_sales_all, index=range(_num_assets), columns=model_timeline_me.index
                )
                
                # Compute TOR + base_rent_adj per asset
                # Renewal probability is NOT applied here – it is applied in the
                # CFS helper functions (fn_get_tor_collections, etc.) so that
                # raw per-asset TOR values are preserved for diagnostics.
                tor_t1_all = np.zeros((_num_assets, _num_periods))
                tor_ren_all = np.zeros((_num_assets, _num_periods))
                br_adj_all = np.zeros((_num_assets, _num_periods))
                for asset_idx in range(_num_assets):
                    if not fn_safe_get(applicable, asset_idx):
                        continue
                    # Skip units with zero / missing GLA
                    if not _is_asset_gla_positive(asset_idx):
                        continue
                    
                    # Returns 3-tuple: (tor_t1, tor_renewal, base_rent_adj)
                    tor_t1, tor_ren, br_adj = fn_compute_turnover_rent(
                        asset_idx, tenant_type, renewal_flags, actual_sales_data, base_rent_data
                    )
                    
                    tor_t1_all[asset_idx, :] = tor_t1.values
                    tor_ren_all[asset_idx, :] = tor_ren.values
                    br_adj_all[asset_idx, :] = br_adj.values
                
                # Store results after loop
                _cols = model_timeline_me.index
                _idx = range(_num_assets)
                results[tenant_type]["turnover_rent_t1"] = pd.DataFrame(
                    tor_t1_all, index=_idx, columns=_cols
                )
                results[tenant_type]["turnover_rent_renewal"] = pd.DataFrame(
                    tor_ren_all, index=_idx, columns=_cols
                )
                # Combined turnover_rent for backward compatibility
                results[tenant_type]["turnover_rent"] = pd.DataFrame(
                    tor_t1_all + tor_ren_all, index=_idx, columns=_cols
                )
                results[tenant_type]["base_rent_adj"] = pd.DataFrame(
                    br_adj_all, index=_idx, columns=_cols
                )
            
            
            # print("✅ Turnover rent computation complete.")
            
            return _cache_set(cache_key, (results, applicability))


        def fn_generate_month_on_month_tor(results, applicability):
            """
            Generate month-on-month TOR output across all tenants.
            
            This function produces a summary with:
            - Each month as a column
            - 3 rows total: T1 (all units), T1 Renewal (all units), T2 (all units)
            
            IMPORTANT: This function uses the pre-computed TOR values from results
            to ensure consistency with NOI and Asset Sale calculations.
            
            The TOR in results is stored at collection periods. We need to split
            T1 vs Renewal by identifying which collection periods belong to each.
            
            Returns: DataFrame with month-on-month TOR totals
            """
            renewal_flags = applicability["renewal_flags"]
            
            # Create month headers from timeline
            month_headers = [_period_starts_ts[i].strftime("%Y-%m") for i in range(_num_periods)]
            
            # Initialize totals for each tenant type
            t1_tor_total = {month_headers[i]: 0.0 for i in range(_num_periods)}
            t1r_tor_total = {month_headers[i]: 0.0 for i in range(_num_periods)}
            t2_tor_total = {month_headers[i]: 0.0 for i in range(_num_periods)}
            
            # Get T1+Renewal TOR from results
            t1r_tor_data = results["tenant1_and_renewal"]["turnover_rent"]
            
            for asset_idx in range(_num_assets):
                # Get TOR values for this asset from pre-computed results
                asset_tor_values = t1r_tor_data.iloc[asset_idx]
                
                # Get lease years to identify which collection periods belong to T1 vs Renewal
                lease_years = fn_get_lease_years(asset_idx, "tenant1_and_renewal", renewal_flags)
                
                # Build mapping of collection_idx -> is_renewal for this asset
                # For periods with TOR from multiple lease years at same collection_idx,
                # we need to track how much TOR comes from T1 vs Renewal
                t1_collection_indices = set()
                renewal_collection_indices = set()
                
                for ly in lease_years:
                    collection_idx = ly["collection_period_idx"]
                    is_renewal = ly.get("is_renewal_period", False)
                    
                    if collection_idx is None:
                        continue
                    
                    if is_renewal:
                        renewal_collection_indices.add(collection_idx)
                    else:
                        t1_collection_indices.add(collection_idx)
                
                # Now sum TOR at each collection period, assigning to T1 or Renewal
                # Note: A collection_idx can only belong to T1 OR Renewal, not both
                # (because T1 ends before Renewal starts)
                for col_idx in range(_num_periods):
                    tor_val = asset_tor_values.iloc[col_idx] if hasattr(asset_tor_values, 'iloc') else asset_tor_values[col_idx]
                    if tor_val == 0:
                        continue
                    
                    month_col = month_headers[col_idx]
                    if col_idx in renewal_collection_indices:
                        t1r_tor_total[month_col] += tor_val
                    elif col_idx in t1_collection_indices:
                        t1_tor_total[month_col] += tor_val
                    # If col_idx not in either set, the TOR value won't be assigned
                    # This shouldn't happen if lease_years is computed correctly
                
                # T2 TOR from results
                t2_tor_values = results["tenant2"]["turnover_rent"].iloc[asset_idx]
                for col_idx in range(_num_periods):
                    month_col = month_headers[col_idx]
                    t2_tor_total[month_col] += t2_tor_values.iloc[col_idx] if hasattr(t2_tor_values, 'iloc') else t2_tor_values[col_idx]
            
            # Create 3 output rows: T1 Total, T1 Renewal Total, T2 Total
            output_rows = []
            
            # ====== T1 ROW (Total across all units) ======
            t1_row = {"Tenant Type": "T1"}
            for col_idx in range(_num_periods):
                month_col = month_headers[col_idx]
                t1_row[month_col] = t1_tor_total[month_col]
            t1_row["Total TOR"] = sum(t1_tor_total.values())
            output_rows.append(t1_row)
            
            # ====== T1 RENEWAL ROW (Total across all units) ======
            t1r_row = {"Tenant Type": "T1 Renewal"}
            for col_idx in range(_num_periods):
                month_col = month_headers[col_idx]
                t1r_row[month_col] = t1r_tor_total[month_col]
            t1r_row["Total TOR"] = sum(t1r_tor_total.values())
            output_rows.append(t1r_row)
            
            # ====== T2 ROW (Total across all units) ======
            t2_row = {"Tenant Type": "T2"}
            for col_idx in range(_num_periods):
                month_col = month_headers[col_idx]
                t2_row[month_col] = t2_tor_total[month_col]
            t2_row["Total TOR"] = sum(t2_tor_total.values())
            output_rows.append(t2_row)
            
            df_month_on_month = pd.DataFrame(output_rows)
            
            # Also create a transposed summary by month (for easy viewing)
            month_summary_rows = []
            for col_idx in range(_num_periods):
                month_col = month_headers[col_idx]
                month_summary_rows.append({
                    "Month": month_col,
                    "T1 TOR": t1_tor_total[month_col],
                    "T1 Renewal TOR": t1r_tor_total[month_col],
                    "T2 TOR": t2_tor_total[month_col],
                    "Total TOR": t1_tor_total[month_col] + t1r_tor_total[month_col] + t2_tor_total[month_col],
                })
            
            df_month_summary = pd.DataFrame(month_summary_rows)
            
            return {
                "month_on_month_detail": df_month_on_month,
                "month_summary": df_month_summary,
            }


        def fn_generate_detailed_tor_output(results, applicability, asset_indices=None):
            """
            Generate detailed turnover rent computation breakdown for specified assets.
            
            Args:
                results: Results from fn_compute_all_turnover_rent()
                applicability: Applicability dict from fn_compute_all_turnover_rent()
                asset_indices: List of asset indices to include (default: first 5 assets)
            
            Returns:
                Dictionary with detailed breakdown DataFrames
            """
            if asset_indices is None:
                asset_indices = list(range(min(5, _num_assets)))
            
            renewal_flags = applicability["renewal_flags"]
            
            # Retrieve actual sales data for detailed output
            actual_sales_t1r = fn_get_actual_sales_from_schedule("tenant1_and_renewal")
            actual_sales_t2 = fn_get_actual_sales_from_schedule("tenant2")
            
            detailed_data = {
                "lease_years_t1r": [],
                "lease_years_t2": [],
                "tor_params": [],
            }
            
            for asset_idx in asset_indices:
                unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                asset_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
                
                # Get T1 lease end for renewal detection
                t1_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                if not pd.isna(t1_end):
                    t1_end = pd.to_datetime(t1_end)
                
                # TOR Parameters
                t1_agreement = fn_safe_get(Unit.RentParametersFirstTenant.agreement_type, asset_idx)
                renewal_agreement = fn_safe_get(Unit.RentParametersRenewal.agreement_type, asset_idx)
                t2_agreement = fn_safe_get(Unit.RentParametersSecondTenant.agreement_type, asset_idx)
                
                t1_limits_pcts, t1_ratchet = fn_get_turnover_params(asset_idx, "tenant1_and_renewal", is_renewal_period=False)
                renewal_limits_pcts, renewal_ratchet = fn_get_turnover_params(asset_idx, "tenant1_and_renewal", is_renewal_period=True)
                t2_limits_pcts, t2_ratchet = fn_get_turnover_params(asset_idx, "tenant2", is_renewal_period=False)
                
                t1_tor_applicable = fn_check_tor_applicable(asset_idx, "tenant1_and_renewal", is_renewal_period=False, renewal_flags=renewal_flags)
                renewal_tor_applicable = fn_check_tor_applicable(asset_idx, "tenant1_and_renewal", is_renewal_period=True, renewal_flags=renewal_flags)
                t2_tor_applicable = fn_check_tor_applicable(asset_idx, "tenant2", is_renewal_period=False, renewal_flags=renewal_flags)
                
                # Format limits for display
                def format_limits(limits_pcts):
                    if not limits_pcts:
                        return "None"
                    return ", ".join([f"({l/1e6:.1f}M, {p*100:.0f}%)" for l, p in limits_pcts])
                
                detailed_data["tor_params"].append({
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "GLA": gla,
                    "Renewal Flag": "Yes" if fn_safe_get(renewal_flags, asset_idx) else "No",
                    "T1 Agreement": t1_agreement,
                    "T1 TOR Applicable": "Yes" if t1_tor_applicable else "No",
                    "T1 Limits/Pcts": format_limits(t1_limits_pcts),
                    "T1 Ratchet": f"{t1_ratchet*100:.0f}%" if t1_ratchet else "N/A",
                    "Renewal Agreement": renewal_agreement,
                    "Renewal TOR Applicable": "Yes" if renewal_tor_applicable else "No",
                    "Renewal Limits/Pcts": format_limits(renewal_limits_pcts),
                    "Renewal Ratchet": f"{renewal_ratchet*100:.0f}%" if renewal_ratchet else "N/A",
                    "T2 Agreement": t2_agreement,
                    "T2 TOR Applicable": "Yes" if t2_tor_applicable else "No",
                    "T2 Limits/Pcts": format_limits(t2_limits_pcts),
                    "T2 Ratchet": f"{t2_ratchet*100:.0f}%" if t2_ratchet else "N/A",
                })
                
                # T1+Renewal Lease Years
                monthly_sales_t1r = fn_compute_monthly_sales_value(asset_idx, "tenant1_and_renewal", renewal_flags, actual_sales_t1r)
                lease_years_t1r = fn_get_lease_years(asset_idx, "tenant1_and_renewal", renewal_flags)
                
                prev_tor = 0
                for ly in lease_years_t1r:
                    year_num = ly["year_num"]
                    year_start = ly["start"]
                    year_end = ly["end"]
                    collection_idx = ly["collection_period_idx"]
                    is_last_year = ly.get("is_last_year", False)
                    
                    # Determine if renewal period
                    is_renewal_period = False
                    if t1_end is not None and year_start > t1_end:
                        is_renewal_period = True
                    
                    # Check TOR applicability (includes renewal flag check)
                    tor_applicable = fn_check_tor_applicable(asset_idx, "tenant1_and_renewal", is_renewal_period, renewal_flags)
                    
                    # Get limits/pcts for this period
                    limits_pcts, ratchet = fn_get_turnover_params(asset_idx, "tenant1_and_renewal", is_renewal_period)
                    
                    # Calculate annual sales and count months
                    annual_sales = 0
                    months_in_year = 0
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        period_end = _period_ends_ts[col_idx]
                        if period_end < year_start or period_start > year_end:
                            continue
                        months_in_year += 1
                        annual_sales += monthly_sales_t1r.iloc[col_idx]
                    
                    # Calculate TOR with LAST YEAR logic
                    # is_last_year: final lease year before lease expiration
                    # For last year: annualize for bracket, apply % to actual, ratchet ONLY if 12 months
                    # For non-last year: apply % to actual/annualized, ratchet applies, collect in first month of next year
                    tor = 0
                    tor_pct = 0
                    annualized_sales = 0
                    
                    if tor_applicable and limits_pcts and months_in_year > 0:
                        is_partial_year = months_in_year < 12
                        
                        if is_last_year:
                            # LAST YEAR LOGIC
                            if is_partial_year:
                                annualized_sales = (annual_sales * 12) / months_in_year
                            else:
                                annualized_sales = annual_sales
                            _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                            tor = annual_sales * tor_pct  # Apply to actual, not annualized
                            # Ratchet applies ONLY if last year is full 12 months
                            if not is_partial_year and ratchet > 0 and prev_tor > 0:
                                min_tor = prev_tor * ratchet
                                tor = max(tor, min_tor)
                        else:
                            # NON-LAST YEAR LOGIC
                            if is_partial_year:
                                annualized_sales = (annual_sales * 12) / months_in_year
                                _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                                tor = annual_sales * tor_pct
                            else:
                                tor, tor_pct = fn_compute_turnover_rent_for_period(annual_sales, limits_pcts)
                            # Ratchet for non-last years
                            if year_num > 1 and ratchet > 0 and prev_tor > 0:
                                min_tor = prev_tor * ratchet
                                tor = max(tor, min_tor)
                    
                    collection_date = _period_starts_ts[collection_idx].strftime("%Y-%m") if collection_idx else "N/A"
                    
                    detailed_data["lease_years_t1r"].append({
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Year": year_num,
                        "Start Date": year_start.strftime("%Y-%m-%d"),
                        "End Date": year_end.strftime("%Y-%m-%d"),
                        "Months": months_in_year,
                        "Is Partial Year": "Yes" if months_in_year < 12 else "No",
                        "In Renewal": "Yes" if is_renewal_period else "No",
                        "TOR Applicable": "Yes" if tor_applicable else "No",
                        "Annual Sales": annual_sales,
                        "Annualized Sales": annualized_sales,
                        "TOR %": f"{tor_pct*100:.1f}%",
                        "Turnover Rent": tor,
                        "Collection Period": collection_date,
                        "Is Last Year": "Yes" if is_last_year else "No",
                    })
                    
                    if not is_last_year and not (months_in_year < 12):  # Only update prev_tor for full non-last years
                        prev_tor = tor
                
                # T2 Lease Years
                monthly_sales_t2 = fn_compute_monthly_sales_value(asset_idx, "tenant2", renewal_flags, actual_sales_t2)
                lease_years_t2 = fn_get_lease_years(asset_idx, "tenant2", renewal_flags)
                
                prev_tor = 0
                for ly in lease_years_t2:
                    year_num = ly["year_num"]
                    year_start = ly["start"]
                    year_end = ly["end"]
                    collection_idx = ly["collection_period_idx"]
                    is_last_year = ly.get("is_last_year", False)
                    
                    # Check TOR applicability (unit type = Retail, agreement type = Base+TOR)
                    tor_applicable = fn_check_tor_applicable(asset_idx, "tenant2", is_renewal_period=False, renewal_flags=renewal_flags)
                    
                    # Get limits/pcts
                    limits_pcts, ratchet = fn_get_turnover_params(asset_idx, "tenant2", is_renewal_period=False)
                    
                    # Calculate annual sales and count months
                    annual_sales = 0
                    months_in_year = 0
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        period_end = _period_ends_ts[col_idx]
                        if period_end < year_start or period_start > year_end:
                            continue
                        months_in_year += 1
                        annual_sales += monthly_sales_t2.iloc[col_idx]
                    
                    # Calculate TOR with LAST YEAR logic
                    tor = 0
                    tor_pct = 0
                    annualized_sales = 0
                    
                    if tor_applicable and limits_pcts and months_in_year > 0:
                        is_partial_year = months_in_year < 12
                        
                        if is_last_year:
                            # LAST YEAR LOGIC
                            if is_partial_year:
                                annualized_sales = (annual_sales * 12) / months_in_year
                            else:
                                annualized_sales = annual_sales
                            _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                            tor = annual_sales * tor_pct  # Apply to actual, not annualized
                            # Ratchet applies ONLY if last year is full 12 months (not partial)
                            if not is_partial_year and year_num > 1 and ratchet > 0 and prev_tor > 0:
                                min_tor = prev_tor * ratchet
                                tor = max(tor, min_tor)
                        else:
                            # NON-LAST YEAR LOGIC
                            if is_partial_year:
                                annualized_sales = (annual_sales * 12) / months_in_year
                                _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                                tor = annual_sales * tor_pct
                            else:
                                tor, tor_pct = fn_compute_turnover_rent_for_period(annual_sales, limits_pcts)
                            # Ratchet for non-last years (full years only, from year 2+)
                            if not is_partial_year and year_num > 1 and ratchet > 0 and prev_tor > 0:
                                min_tor = prev_tor * ratchet
                                tor = max(tor, min_tor)
                    
                    collection_date = _period_starts_ts[collection_idx].strftime("%Y-%m") if collection_idx else "N/A"
                    
                    detailed_data["lease_years_t2"].append({
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Year": year_num,
                        "Start Date": year_start.strftime("%Y-%m-%d"),
                        "End Date": year_end.strftime("%Y-%m-%d"),
                        "Months": months_in_year,
                        "Is Partial Year": "Yes" if months_in_year < 12 else "No",
                        "TOR Applicable": "Yes" if tor_applicable else "No",
                        "Annual Sales": annual_sales,
                        "Annualized Sales": annualized_sales,
                        "TOR %": f"{tor_pct*100:.1f}%",
                        "Turnover Rent": tor,
                        "Collection Period": collection_date,
                        "Is Last Year": "Yes" if is_last_year else "No",
                    })
                    
                    if not is_last_year and not (months_in_year < 12):  # Only update prev_tor for full non-last years
                        prev_tor = tor
            
            return {
                "tor_params": pd.DataFrame(detailed_data["tor_params"]),
                "lease_years_t1r": pd.DataFrame(detailed_data["lease_years_t1r"]),
                "lease_years_t2": pd.DataFrame(detailed_data["lease_years_t2"]),
            }


        def fn_generate_year_on_year_output(results, applicability):
            """
            Generate year-on-year output with monthly sales row and TOR row for each unit.
            
            Format per unit:
            - Row 1: Unit info + Monthly Sales for T1+R
            - Row 2: Unit info + TOR for T1+R (below sales)
            - Row 3: Unit info + Monthly Sales for T2
            - Row 4: Unit info + TOR for T2 (below sales)
            
            Returns: Dictionary with DataFrames for year-on-year output
            """
            renewal_flags = applicability["renewal_flags"]
            
            # Get calendar years from timeline
            years = sorted(set([ts.year for ts in _period_starts_ts]))
            
            # Initialize output data
            output_rows = []
            
            for asset_idx in range(_num_assets):
                unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                unit_num = unit_id  # Using unit_id as unit number
                asset_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx)
                unit_type = fn_safe_get(Unit.UnitInputs.unit_type, asset_idx)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx) or 0
                
                has_renewal = fn_safe_get(applicability["renewal_flags"], asset_idx)
                has_t2 = fn_safe_get(applicability["tenant2"], asset_idx)
                
                # Get T1+R lease dates
                t1_start = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx)
                t1_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                renewal_end = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx) if has_renewal else None
                
                # Get T2 lease dates
                t2_start = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx) if has_t2 else None
                t2_end = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx) if has_t2 else None
                
                # ====== T1+R SALES ROW ======
                t1r_sales_row = {
                    "Unit": unit_num,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Tenant": "T1+Renewal",
                    "Row Type": "Sales",
                    "Renewal": "Yes" if has_renewal else "No",
                    "T1 Start": t1_start,
                    "T1 End": t1_end,
                    "Renewal End": renewal_end,
                }
                
                # Add yearly sales for T1+R
                for year in years:
                    year_sales = 0
                    for col_idx in range(_num_periods):
                        if _period_starts_ts[col_idx].year == year:
                            year_sales += results["tenant1_and_renewal"]["monthly_sales"].iloc[asset_idx, col_idx]
                    t1r_sales_row[str(year)] = year_sales
                
                t1r_sales_row["Total"] = results["tenant1_and_renewal"]["monthly_sales"].iloc[asset_idx].sum()
                output_rows.append(t1r_sales_row)
                
                # ====== T1+R TOR ROW ======
                t1r_tor_row = {
                    "Unit": unit_num,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Tenant": "T1+Renewal",
                    "Row Type": "TOR",
                    "Renewal": "Yes" if has_renewal else "No",
                    "T1 Start": t1_start,
                    "T1 End": t1_end,
                    "Renewal End": renewal_end,
                }
                
                # Add yearly TOR for T1+R
                for year in years:
                    year_tor = 0
                    for col_idx in range(_num_periods):
                        if _period_starts_ts[col_idx].year == year:
                            year_tor += results["tenant1_and_renewal"]["turnover_rent"].iloc[asset_idx, col_idx]
                    t1r_tor_row[str(year)] = year_tor
                
                t1r_tor_row["Total"] = results["tenant1_and_renewal"]["turnover_rent"].iloc[asset_idx].sum()
                output_rows.append(t1r_tor_row)
                
                # ====== T2 SALES ROW ======
                t2_sales_row = {
                    "Unit": unit_num,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Tenant": "T2",
                    "Row Type": "Sales",
                    "Renewal": "N/A",
                    "T1 Start": t2_start,
                    "T1 End": t2_end,
                    "Renewal End": None,
                }
                
                # Add yearly sales for T2
                for year in years:
                    year_sales = 0
                    for col_idx in range(_num_periods):
                        if _period_starts_ts[col_idx].year == year:
                            year_sales += results["tenant2"]["monthly_sales"].iloc[asset_idx, col_idx]
                    t2_sales_row[str(year)] = year_sales
                
                t2_sales_row["Total"] = results["tenant2"]["monthly_sales"].iloc[asset_idx].sum()
                output_rows.append(t2_sales_row)
                
                # ====== T2 TOR ROW ======
                t2_tor_row = {
                    "Unit": unit_num,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Tenant": "T2",
                    "Row Type": "TOR",
                    "Renewal": "N/A",
                    "T1 Start": t2_start,
                    "T1 End": t2_end,
                    "Renewal End": None,
                }
                
                # Add yearly TOR for T2
                for year in years:
                    year_tor = 0
                    for col_idx in range(_num_periods):
                        if _period_starts_ts[col_idx].year == year:
                            year_tor += results["tenant2"]["turnover_rent"].iloc[asset_idx, col_idx]
                    t2_tor_row[str(year)] = year_tor
                
                t2_tor_row["Total"] = results["tenant2"]["turnover_rent"].iloc[asset_idx].sum()
                output_rows.append(t2_tor_row)
            
            # Create DataFrame
            df_year_on_year = pd.DataFrame(output_rows)
            
            # Also create a summary by year
            year_summary = []
            for year in years:
                year_t1r_sales = 0
                year_t1r_tor = 0
                year_t2_sales = 0
                year_t2_tor = 0
                
                for col_idx in range(_num_periods):
                    if _period_starts_ts[col_idx].year == year:
                        year_t1r_sales += results["tenant1_and_renewal"]["monthly_sales"].iloc[:, col_idx].sum()
                        year_t1r_tor += results["tenant1_and_renewal"]["turnover_rent"].iloc[:, col_idx].sum()
                        year_t2_sales += results["tenant2"]["monthly_sales"].iloc[:, col_idx].sum()
                        year_t2_tor += results["tenant2"]["turnover_rent"].iloc[:, col_idx].sum()
                
                if year_t1r_sales > 0 or year_t2_sales > 0:
                    year_summary.append({
                        "Year": year,
                        "T1+R Sales": year_t1r_sales,
                        "T1+R TOR": year_t1r_tor,
                        "T2 Sales": year_t2_sales,
                        "T2 TOR": year_t2_tor,
                        "Total Sales": year_t1r_sales + year_t2_sales,
                        "Total TOR": year_t1r_tor + year_t2_tor,
                    })
            
            df_year_summary = pd.DataFrame(year_summary)
            
            return {
                "year_on_year_detail": df_year_on_year,
                "year_summary": df_year_summary,
            }


        def fn_generate_sales_tor_by_tenant_type(results, applicability):
            """
            Generate separate tabs for T1 (before renewal), T1 Renewal, and T2.
            
            Each tab has format using LEASE YEARS (not calendar years):
            - Columns: Year 1, Year 2, ... (based on lease start date, 12 months each)
            - Unit 1 Sales row (lease year sales)
            - Unit 1 TOR row (lease year TOR)
            - ... and so on
            
            For partial years (last year with < 12 months), shows actual sales for operating months.
            
            Returns: Dictionary with DataFrames for T1, T1 Renewal, and T2
            """
            renewal_flags = applicability["renewal_flags"]
            
            # Retrieve actual sales data
            actual_sales_t1r = fn_get_actual_sales_from_schedule("tenant1_and_renewal")
            actual_sales_t2 = fn_get_actual_sales_from_schedule("tenant2")
            
            # Initialize output rows
            t1_rows = []
            t1_renewal_rows = []
            t2_rows = []
            
            # Determine max lease years across all assets for column headers
            max_lease_years = 20  # Maximum number of lease years to show
            lease_year_cols = [f"Year {i}" for i in range(1, max_lease_years + 1)]
            
            for asset_idx in range(_num_assets):
                unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                unit_num = unit_id  # Using unit_id as unit number
                asset_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx)
                unit_type = fn_safe_get(Unit.UnitInputs.unit_type, asset_idx)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx) or 0
                
                has_renewal = fn_safe_get(renewal_flags, asset_idx)
                has_t2 = fn_safe_get(applicability["tenant2"], asset_idx)
                is_retail = fn_check_unit_type_retail(asset_idx)
                
                # Get lease dates
                t1_start = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx)
                t1_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                renewal_start = None
                renewal_end = None
                
                if has_renewal:
                    renewal_start = fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, asset_idx)
                    renewal_end = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx)
                
                # Convert to timestamps
                t1_start_ts = pd.to_datetime(t1_start) if t1_start and not pd.isna(t1_start) else None
                t1_end_ts = pd.to_datetime(t1_end) if t1_end and not pd.isna(t1_end) else None
                renewal_start_ts = pd.to_datetime(renewal_start) if renewal_start and not pd.isna(renewal_start) else None
                renewal_end_ts = pd.to_datetime(renewal_end) if renewal_end and not pd.isna(renewal_end) else None
                
                # Get monthly sales for T1+R
                monthly_sales_t1r = fn_compute_monthly_sales_value(asset_idx, "tenant1_and_renewal", renewal_flags, actual_sales_t1r)
                
                # Get lease years for T1+R
                lease_years_t1r = fn_get_lease_years(asset_idx, "tenant1_and_renewal", renewal_flags)
                
                # =====================================================================
                # T1 (BEFORE RENEWAL) - Lease Year Sales and TOR
                # =====================================================================
                t1_sales_row = {
                    "Unit": unit_num,
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Row Type": "Sales",
                    "Lease Start": t1_start,
                    "Lease End": t1_end,
                }
                
                t1_tor_row = {
                    "Unit": unit_num,
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Row Type": "TOR",
                    "Lease Start": t1_start,
                    "Lease End": t1_end,
                }
                
                t1_total_sales = 0
                t1_total_tor = 0
                
                # Get TOR parameters
                limits_pcts, ratchet = fn_get_turnover_params(asset_idx, "tenant1_and_renewal", is_renewal_period=False)
                tor_applicable = fn_check_tor_applicable(asset_idx, "tenant1_and_renewal", is_renewal_period=False, renewal_flags=renewal_flags)
                
                # Filter lease years that fall within T1 period (before renewal)
                t1_lease_years = [ly for ly in lease_years_t1r if not (t1_end_ts and ly["start"] > t1_end_ts)]
                total_t1_lease_years = len(t1_lease_years)
                
                prev_tor = 0
                for lease_year_idx, ly in enumerate(t1_lease_years):
                    year_start = ly["start"]
                    year_end = ly["end"]
                    year_num = ly["year_num"]
                    
                    # Calculate sales and months for this lease year
                    ly_sales = 0
                    months_in_year = 0
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        period_end = _period_ends_ts[col_idx]
                        if period_end < year_start or period_start > year_end:
                            continue
                        # Only count sales up to T1 end
                        if t1_end_ts and period_start > t1_end_ts:
                            continue
                        months_in_year += 1
                        ly_sales += monthly_sales_t1r.iloc[col_idx]
                    
                    # Store sales for this lease year
                    col_name = f"Year {year_num}"
                    t1_sales_row[col_name] = ly_sales
                    t1_total_sales += ly_sales
                    
                    # Compute TOR (only if applicable: Retail + TOR agreement)
                    # Check if this is the last lease year for T1
                    is_last_year_t1 = (lease_year_idx == total_t1_lease_years - 1)
                    
                    tor = 0
                    if tor_applicable and is_retail and limits_pcts and ly_sales > 0 and months_in_year > 0:
                        is_partial_year = months_in_year < 12
                        
                        if is_partial_year:
                            # Annualize sales for bracket determination
                            annualized_sales = (ly_sales * 12) / months_in_year
                            # Determine TOR % based on annualized sales
                            _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts)
                            # Apply TOR % to actual sales (not annualized)
                            tor = ly_sales * tor_pct
                            # NO ratchet for partial years
                        else:
                            # Full year: use actual sales directly
                            tor, _ = fn_compute_turnover_rent_for_period(ly_sales, limits_pcts)
                            # Apply ratchet from year 2 onwards (for full years, including last year if 12 months)
                            if year_num > 1 and ratchet > 0 and prev_tor > 0:
                                min_tor = prev_tor * ratchet
                                tor = max(tor, min_tor)
                            prev_tor = tor
                    
                    t1_tor_row[col_name] = tor
                    t1_total_tor += tor
                
                # Fill missing years with 0
                for col in lease_year_cols:
                    if col not in t1_sales_row:
                        t1_sales_row[col] = 0
                    if col not in t1_tor_row:
                        t1_tor_row[col] = 0
                
                t1_sales_row["Total"] = t1_total_sales
                t1_tor_row["Total"] = t1_total_tor
                
                t1_rows.append(t1_sales_row)
                t1_rows.append(t1_tor_row)
                
                # =====================================================================
                # T1 RENEWAL - Lease Year Sales and TOR (show all units, 0 if no renewal)
                # =====================================================================
                if has_renewal:
                    t1r_sales_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "Sales",
                        "Renewal Start": renewal_start,
                        "Renewal End": renewal_end,
                    }
                    
                    t1r_tor_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "TOR",
                        "Renewal Start": renewal_start,
                        "Renewal End": renewal_end,
                    }
                    
                    t1r_total_sales = 0
                    t1r_total_tor = 0
                    
                    # Compute TOR for renewal lease years
                    limits_pcts_renewal, ratchet_renewal = fn_get_turnover_params(asset_idx, "tenant1_and_renewal", is_renewal_period=True)
                    tor_applicable_renewal = fn_check_tor_applicable(asset_idx, "tenant1_and_renewal", is_renewal_period=True, renewal_flags=renewal_flags)
                    
                    # For renewal, compute lease years starting from RENEWAL START DATE
                    # NOT from T1 start date. E.g., if renewal starts Feb 2025, 
                    # Year 1 = Feb 2025 - Jan 2026, Year 2 = Feb 2026 - Jan 2027, etc.
                    renewal_lease_years = []
                    if renewal_start_ts and renewal_end_ts:
                        year_num = 1
                        current_start = renewal_start_ts
                        while current_start <= renewal_end_ts:
                            year_end = current_start + relativedelta(years=1) - relativedelta(days=1)
                            if year_end > renewal_end_ts:
                                year_end = renewal_end_ts
                            renewal_lease_years.append({
                                "year_num": year_num,
                                "start": current_start,
                                "end": year_end,
                            })
                            current_start = year_end + relativedelta(days=1)
                            year_num += 1
                            if year_num > 50:  # Safety check
                                break
                    
                    total_renewal_lease_years = len(renewal_lease_years)
                    
                    prev_tor_renewal = prev_tor  # Continue from T1's last TOR for ratchet
                    
                    for lease_year_idx, ly in enumerate(renewal_lease_years):
                        year_start = ly["start"]
                        year_end = ly["end"]
                        renewal_year_num = ly["year_num"]  # Year 1 of renewal based on renewal start
                        
                        # Calculate sales and months for this lease year
                        ly_sales = 0
                        months_in_year = 0
                        for col_idx in range(_num_periods):
                            period_start = _period_starts_ts[col_idx]
                            period_end = _period_ends_ts[col_idx]
                            if period_end < year_start or period_start > year_end:
                                continue
                            months_in_year += 1
                            ly_sales += monthly_sales_t1r.iloc[col_idx]
                        
                        # Store sales for this lease year
                        col_name = f"Year {renewal_year_num}"
                        t1r_sales_row[col_name] = ly_sales
                        t1r_total_sales += ly_sales
                        
                        # Compute TOR (only if applicable)
                        # Check if this is the last lease year for renewal
                        is_last_year_renewal = (lease_year_idx == total_renewal_lease_years - 1)
                        
                        tor = 0
                        if tor_applicable_renewal and is_retail and limits_pcts_renewal and ly_sales > 0 and months_in_year > 0:
                            is_partial_year = months_in_year < 12
                            
                            if is_partial_year:
                                # Annualize sales for bracket determination
                                annualized_sales = (ly_sales * 12) / months_in_year
                                # Determine TOR % based on annualized sales
                                _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts_renewal)
                                # Apply TOR % to actual sales (not annualized)
                                tor = ly_sales * tor_pct
                                # NO ratchet for partial years
                            else:
                                # Full year
                                tor, _ = fn_compute_turnover_rent_for_period(ly_sales, limits_pcts_renewal)
                                # Apply ratchet from year 2 onwards (for full years, including last year if 12 months)
                                if renewal_year_num > 1 and ratchet_renewal > 0 and prev_tor_renewal > 0:
                                    min_tor = prev_tor_renewal * ratchet_renewal
                                    tor = max(tor, min_tor)
                                prev_tor_renewal = tor
                        
                        t1r_tor_row[col_name] = tor
                        t1r_total_tor += tor
                    
                    # Fill missing years with 0
                    for col in lease_year_cols:
                        if col not in t1r_sales_row:
                            t1r_sales_row[col] = 0
                        if col not in t1r_tor_row:
                            t1r_tor_row[col] = 0
                    
                    t1r_sales_row["Total"] = t1r_total_sales
                    t1r_tor_row["Total"] = t1r_total_tor
                    
                    t1_renewal_rows.append(t1r_sales_row)
                    t1_renewal_rows.append(t1r_tor_row)
                else:
                    # No renewal - still create rows with zeros
                    t1r_sales_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "Sales",
                        "Renewal Start": None,
                        "Renewal End": None,
                    }
                    
                    t1r_tor_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "TOR",
                        "Renewal Start": None,
                        "Renewal End": None,
                    }
                    
                    # Fill all years with 0
                    for col in lease_year_cols:
                        t1r_sales_row[col] = 0
                        t1r_tor_row[col] = 0
                    
                    t1r_sales_row["Total"] = 0
                    t1r_tor_row["Total"] = 0
                    
                    t1_renewal_rows.append(t1r_sales_row)
                    t1_renewal_rows.append(t1r_tor_row)
                
                # =====================================================================
                # T2 - Lease Year Sales and TOR (show all units, 0 if no T2)
                # =====================================================================
                if has_t2:
                    t2_start = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx)
                    t2_end = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx)
                    t2_start_ts = pd.to_datetime(t2_start) if t2_start and not pd.isna(t2_start) else None
                    t2_end_ts = pd.to_datetime(t2_end) if t2_end and not pd.isna(t2_end) else None
                    
                    t2_sales_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "Sales",
                        "Lease Start": t2_start,
                        "Lease End": t2_end,
                    }
                    
                    t2_tor_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "TOR",
                        "Lease Start": t2_start,
                        "Lease End": t2_end,
                    }
                    
                    # Get monthly sales for T2
                    monthly_sales_t2 = fn_compute_monthly_sales_value(asset_idx, "tenant2", renewal_flags, actual_sales_t2)
                    
                    t2_total_sales = 0
                    t2_total_tor = 0
                    
                    # Get lease years for T2
                    lease_years_t2 = fn_get_lease_years(asset_idx, "tenant2", renewal_flags)
                    
                    limits_pcts_t2, ratchet_t2 = fn_get_turnover_params(asset_idx, "tenant2", is_renewal_period=False)
                    tor_applicable_t2 = fn_check_tor_applicable(asset_idx, "tenant2", is_renewal_period=False, renewal_flags=renewal_flags)
                    is_retail_t2 = fn_check_unit_type_retail(asset_idx)
                    
                    total_t2_lease_years = len(lease_years_t2)
                    prev_tor_t2 = 0
                    
                    for lease_year_idx, ly in enumerate(lease_years_t2):
                        year_start = ly["start"]
                        year_end = ly["end"]
                        year_num = ly["year_num"]
                        
                        # Calculate sales and months for this lease year
                        ly_sales = 0
                        months_in_year = 0
                        for col_idx in range(_num_periods):
                            period_start = _period_starts_ts[col_idx]
                            period_end = _period_ends_ts[col_idx]
                            if period_end < year_start or period_start > year_end:
                                continue
                            months_in_year += 1
                            ly_sales += monthly_sales_t2.iloc[col_idx]
                        
                        # Store sales for this lease year
                        col_name = f"Year {year_num}"
                        t2_sales_row[col_name] = ly_sales
                        t2_total_sales += ly_sales
                        
                        # Compute TOR (only if applicable)
                        # Check if this is the last lease year for T2
                        is_last_year_t2 = (lease_year_idx == total_t2_lease_years - 1)
                        
                        tor = 0
                        if tor_applicable_t2 and is_retail_t2 and limits_pcts_t2 and ly_sales > 0 and months_in_year > 0:
                            is_partial_year = months_in_year < 12
                            
                            if is_partial_year:
                                # Annualize sales for bracket determination
                                annualized_sales = (ly_sales * 12) / months_in_year
                                # Determine TOR % based on annualized sales
                                _, tor_pct = fn_compute_turnover_rent_for_period(annualized_sales, limits_pcts_t2)
                                # Apply TOR % to actual sales (not annualized)
                                tor = ly_sales * tor_pct
                                # NO ratchet for partial years
                            else:
                                # Full year
                                tor, _ = fn_compute_turnover_rent_for_period(ly_sales, limits_pcts_t2)
                                # Apply ratchet from year 2 onwards (for full years, including last year if 12 months)
                                if year_num > 1 and ratchet_t2 > 0 and prev_tor_t2 > 0:
                                    min_tor = prev_tor_t2 * ratchet_t2
                                    tor = max(tor, min_tor)
                                prev_tor_t2 = tor
                        
                        t2_tor_row[col_name] = tor
                        t2_total_tor += tor
                    
                    # Fill missing years with 0
                    for col in lease_year_cols:
                        if col not in t2_sales_row:
                            t2_sales_row[col] = 0
                        if col not in t2_tor_row:
                            t2_tor_row[col] = 0
                    
                    t2_sales_row["Total"] = t2_total_sales
                    t2_tor_row["Total"] = t2_total_tor
                    
                    t2_rows.append(t2_sales_row)
                    t2_rows.append(t2_tor_row)
                else:
                    # No T2 - still create rows with zeros
                    t2_sales_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "Sales",
                        "Lease Start": None,
                        "Lease End": None,
                    }
                    
                    t2_tor_row = {
                        "Unit": unit_num,
                        "Unit ID": unit_id,
                        "Asset Name": asset_name,
                        "Unit Type": unit_type,
                        "GLA": gla,
                        "Row Type": "TOR",
                        "Lease Start": None,
                        "Lease End": None,
                    }
                    
                    # Fill all years with 0
                    for col in lease_year_cols:
                        t2_sales_row[col] = 0
                        t2_tor_row[col] = 0
                    
                    t2_sales_row["Total"] = 0
                    t2_tor_row["Total"] = 0
                    
                    t2_rows.append(t2_sales_row)
                    t2_rows.append(t2_tor_row)
            
            # Create DataFrames with proper column ordering
            def create_ordered_df(rows, extra_cols):
                if not rows:
                    return pd.DataFrame()
                
                # Fixed columns first, then lease years, then Total
                fixed_cols = ["Unit", "Unit ID", "Asset Name", "Unit Type", "GLA", "Row Type"] + extra_cols
                all_cols = fixed_cols + lease_year_cols + ["Total"]
                
                # Ensure all rows have all columns
                for row in rows:
                    for col in all_cols:
                        if col not in row:
                            row[col] = 0 if col in lease_year_cols or col == "Total" else ""
                
                df = pd.DataFrame(rows)
                # Reorder columns
                ordered_cols = [c for c in all_cols if c in df.columns]
                return df[ordered_cols]
            
            df_t1 = create_ordered_df(t1_rows, ["Lease Start", "Lease End"])
            df_t1_renewal = create_ordered_df(t1_renewal_rows, ["Renewal Start", "Renewal End"])
            df_t2 = create_ordered_df(t2_rows, ["Lease Start", "Lease End"])
            
            return {
                "T1": df_t1,
                "T1_Renewal": df_t1_renewal,
                "T2": df_t2,
            }


        # =============================================================================
        # OUTPUT DATAFRAMES FOR CASHFLOW/OUTPUT MODULE
        # =============================================================================

        def fn_create_output_dataframes(results, applicability):
            """
            Create summary DataFrames for the output module.
            Output is TURNOVER RENT COLLECTIONS (monthly and annual totals).
            """
            global turnover_rent_collections_monthly, turnover_rent_collections_annual
            global turnover_rent_by_tenant_monthly, turnover_rent_by_tenant_annual
            # global_period_ends_ts, _num_periods
            
            renewal_flags = applicability["renewal_flags"]
            
            # =========================================================================
            # Split T1+Renewal into T1 and Renewal portions based on lease periods
            # =========================================================================
            t1_monthly = np.zeros(_num_periods)
            renewal_monthly = np.zeros(_num_periods)
            t2_monthly = np.zeros(_num_periods)
            
            # For T1+Renewal, we need to identify which collection periods belong to T1 vs Renewal
            for asset_idx in range(_num_assets):
                # Get T1 end date
                t1_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                t1_end_ts = pd.to_datetime(t1_end) if t1_end and not pd.isna(t1_end) else None
                has_renewal = fn_safe_get(renewal_flags, asset_idx)
                
                # Get TOR values for this asset
                tor_values = results["tenant1_and_renewal"]["turnover_rent"].iloc[asset_idx]
                
                # Get lease years to identify T1 vs Renewal collection periods
                lease_years = fn_get_lease_years(asset_idx, "tenant1_and_renewal", renewal_flags)
                
                for ly in lease_years:
                    collection_idx = ly.get("collection_period_idx")
                    if collection_idx is None:
                        continue
                    
                    is_renewal_period = ly.get("is_renewal_period", False)
                    
                    # Get TOR value at this collection period
                    tor_value = tor_values.iloc[collection_idx] if hasattr(tor_values, 'iloc') else tor_values[collection_idx]
                    
                    if is_renewal_period and has_renewal:
                        renewal_monthly[collection_idx] += tor_value
                    else:
                        t1_monthly[collection_idx] += tor_value
            
            # T2 is straightforward
            t2_monthly = results["tenant2"]["turnover_rent"].sum(axis=0).values
            
            # Total monthly TOR
            total_monthly = t1_monthly + renewal_monthly + t2_monthly
            
            # Create period dates for columns
            period_dates = [_period_ends_ts[i] for i in range(_num_periods)]
            
            # =========================================================================
            # MONTHLY COLLECTIONS - Single line item for output
            # =========================================================================
            turnover_rent_collections_monthly = pd.DataFrame(
                [total_monthly],
                columns=period_dates,
                index=["Turnover Rent Collections"]
            )
            
            # By tenant breakdown (monthly)
            turnover_rent_by_tenant_monthly = {
                "T1": pd.Series(t1_monthly, index=period_dates, name="T1 TOR"),
                "Renewal": pd.Series(renewal_monthly, index=period_dates, name="Renewal TOR"),
                "T2": pd.Series(t2_monthly, index=period_dates, name="T2 TOR"),
                "Total": pd.Series(total_monthly, index=period_dates, name="Total TOR")
            }
            
            # =========================================================================
            # ANNUAL COLLECTIONS - Single line item for output
            # =========================================================================
            def aggregate_by_year(monthly_arr):
                """Aggregate monthly data by year."""
                yearly_totals = {}
                for col_idx in range(_num_periods):
                    year = _period_ends_ts[col_idx].year
                    if year not in yearly_totals:
                        yearly_totals[year] = 0.0
                    yearly_totals[year] += monthly_arr[col_idx]
                return yearly_totals
            
            yearly_t1 = aggregate_by_year(t1_monthly)
            yearly_renewal = aggregate_by_year(renewal_monthly)
            yearly_t2 = aggregate_by_year(t2_monthly)
            
            all_years = sorted(set(yearly_t1.keys()) | set(yearly_renewal.keys()) | set(yearly_t2.keys()))
            yearly_total = {y: yearly_t1.get(y, 0) + yearly_renewal.get(y, 0) + yearly_t2.get(y, 0) for y in all_years}
            
            # Single line item - Total Turnover Rent Collections (Annual)
            turnover_rent_collections_annual = pd.DataFrame(
                [[yearly_total.get(y, 0) for y in all_years]],
                columns=all_years,
                index=["Turnover Rent Collections"]
            )
            
            # By tenant breakdown (annual)
            turnover_rent_by_tenant_annual = {
                "T1": yearly_t1,
                "Renewal": yearly_renewal,
                "T2": yearly_t2,
                "Total": yearly_total
            }
            
            return turnover_rent_collections_monthly, turnover_rent_collections_annual


        def fn_generate_unit_sales_report(results, applicability):
            """
            Generate unit-wise, month-wise sales report.
            
            This function produces a detailed report showing:
            - Each unit as a row
            - Each month as a column  
            - Sales values (actual or forecast based on sales mode)
            - Annual totals for each unit
            
            Args:
                results: Results dictionary from fn_compute_all_turnover_rent()
                applicability: Applicability dictionary
            
            Returns:
                Dictionary with:
                - monthly_sales_by_unit: DataFrame with unit x month sales
                - annual_sales_by_unit: DataFrame with unit x year sales
                - sales_mode_by_unit: List showing sales mode for each unit
            """
            renewal_flags = applicability["renewal_flags"]
            
            # Get actual sales data
            actual_sales_t1r = fn_get_actual_sales_from_schedule("tenant1_and_renewal")
            
            # Create month headers
            month_headers = [_period_starts_ts[i].strftime("%Y-%m") for i in range(_num_periods)]
            
            # Initialize output
            unit_sales_rows = []
            annual_sales_rows = []
            sales_modes = []
            
            for asset_idx in range(_num_assets):
                unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                asset_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx) or 0
                unit_type = fn_safe_get(Unit.UnitInputs.unit_type, asset_idx)
                
                # Get sales mode
                sales_mode = fn_get_sales_mode(asset_idx, "tenant1_and_renewal")
                sales_modes.append(sales_mode)
                
                # Get monthly sales from results
                monthly_sales = results["tenant1_and_renewal"]["monthly_sales"].iloc[asset_idx]
                
                # Build monthly row
                monthly_row = {
                    "Unit": asset_idx + 1,
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Sales Mode": sales_mode,
                }
                
                # Add monthly values
                total_sales = 0
                for col_idx in range(_num_periods):
                    month_col = month_headers[col_idx]
                    val = monthly_sales.iloc[col_idx] if hasattr(monthly_sales, 'iloc') else monthly_sales[col_idx]
                    monthly_row[month_col] = val
                    total_sales += val
                
                monthly_row["Total Sales"] = total_sales
                unit_sales_rows.append(monthly_row)
                
                # Build annual row
                annual_row = {
                    "Unit": asset_idx + 1,
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "Unit Type": unit_type,
                    "GLA": gla,
                    "Sales Mode": sales_mode,
                }
                
                # Sum by year
                year_totals = {}
                for col_idx in range(_num_periods):
                    year = _period_starts_ts[col_idx].year
                    val = monthly_sales.iloc[col_idx] if hasattr(monthly_sales, 'iloc') else monthly_sales[col_idx]
                    year_totals[year] = year_totals.get(year, 0) + val
                
                for year in sorted(year_totals.keys()):
                    annual_row[str(year)] = year_totals[year]
                
                annual_row["Total"] = sum(year_totals.values())
                annual_sales_rows.append(annual_row)
            
            # Create DataFrames
            df_monthly = pd.DataFrame(unit_sales_rows)
            df_annual = pd.DataFrame(annual_sales_rows)
            
            return {
                "monthly_sales_by_unit": df_monthly,
                "annual_sales_by_unit": df_annual,
                "sales_mode_by_unit": sales_modes,
            }


        # =============================================================================
        # MAIN MODULE FUNCTION
        # =============================================================================

        def fn_run_module_04(assumptions_input=None, timeline_me=None):
            """Main function to run Module 04 - Turnover Rent Computation."""
            # global assumptions, model_timeline_me, model_timeline_ye
            # global _period_starts, _period_ends, _num_periods, _num_assets
            # global _period_starts_ts, _period_ends_ts, 
            global all_turnover_results
            
            # print("=" * 60)
            # print("MODULE 04: TURNOVER RENT COMPUTATION")
            # print("=" * 60)
            
            # # Step 1: Get assumptions from Module 02 or load fresh
            # if assumptions_input is None:
            #     print("\n📂 Running Module 02 to load assumptions...")
            #     result = fn_run_module_02()
            #     if result is None:
            #         print("❌ Failed to load Module 02")
            #         return None
            #     assumptions, model_timeline_me, model_timeline_ye, _, _, _ = result
            # else:
            #     assumptions = assumptions_input
            #     model_timeline_me = timeline_me
            
            # # Step 2: Initialize module variables
            # print("\n🔧 Initializing turnover rent module...")
            # _period_starts = model_timeline_me["Period Start"].values
            # _period_ends = model_timeline_me["Period End"].values
            # _num_periods = len(model_timeline_me)
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _period_starts_ts = [pd.Timestamp(x) for x in _period_starts]
            # _period_ends_ts = [pd.Timestamp(x) for x in _period_ends]
            
            # print(f"   Model Start: {Global.ModelInputs.model_start_date}")
            # print(f"   Asset Sale Date: {Global.ModelInputs.asset_sale_date}")
            # print(f"   Number of assets: {_num_assets}")
            # print(f"   Number of periods: {_num_periods}")
            
            # Step 3: Compute turnover rent for all tenants
            # print("\n💰 Computing turnover rent for all tenants...")
            all_turnover_results, applicability = fn_compute_all_turnover_rent()
            
            # Step 4: Create output DataFrames
            # print("\n📋 Creating output DataFrames...")
            fn_create_output_dataframes(all_turnover_results, applicability)
            
            # Step 5: Print summary
            total_t1_renewal = all_turnover_results["tenant1_and_renewal"]["turnover_rent"].sum().sum()
            total_t2 = all_turnover_results["tenant2"]["turnover_rent"].sum().sum()
            total_all = total_t1_renewal + total_t2
            
            # print(f"\n📊 Turnover Rent Summary:")
            # print(f"   T1 + Renewal: {total_t1_renewal:,.2f}")
            # print(f"   T2: {total_t2:,.2f}")
            # print(f"   TOTAL:   {total_all:,.2f}")
            
            # Step 6: Generate unit-wise sales report
            # print("\n📋 Generating unit-wise sales report...")
            sales_report = fn_generate_unit_sales_report(all_turnover_results, applicability)
            
            # print("\n📊 Annual Sales by Unit (First 5 units):")
            df_annual = sales_report["annual_sales_by_unit"]
            if len(df_annual) > 0:
                # Get year columns
                year_cols = [c for c in df_annual.columns if c.isdigit()]
                # print(f"   {'Unit':<6} {'Sales Mode':<20} " + " ".join([f"{y:>15}" for y in year_cols[:5]]) + f" {'Total':>15}")
                # print("   " + "-" * (30 + 16 * min(6, len(year_cols) + 1)))
                for idx, row in df_annual.head(5).iterrows():
                    unit = row.get('Unit', idx + 1)
                    mode = row.get('Sales Mode', 'N/A')
                    vals = " ".join([f"{row.get(y, 0):>15,.0f}" for y in year_cols[:5]])
                    total = row.get('Total', 0)
                    # print(f"   {unit:<6} {mode:<20} {vals} {total:>15,.0f}")
            
            # print("\n✅ Module 04 completed successfully!")
            
            return all_turnover_results, applicability, sales_report
        

        # Service Charge
        service_charge_collections_monthly = None  # Single row DataFrame
        service_charge_collections_annual = None   # Single row DataFrame

        # Leasing Commission
        leasing_commission_monthly = None  # Single row DataFrame
        leasing_commission_annual = None   # Single row DataFrame

        # Tenant Fitout Allowance
        tenant_fitout_allowance_monthly = None  # Single row DataFrame
        tenant_fitout_allowance_annual = None   # Single row DataFrame


        # =============================================================================
        # SERVICE CHARGE ESCALATION PROFILES
        # =============================================================================

        def fn_get_service_charge_escalation_profiles():
            """
            Get service charge escalation profiles from assumptions.
            Returns: Dictionary of profile_name -> {year_num: escalation_rate}
            """
            
            cache_key = "service_charge_profiles"
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached
            
            profiles = {}
            
            try:
                # Get profile names
                profile_names = assumptions.loc[
                    assumptions["name"] == "a.assetco.service.charge.escalation.profiles", "value"
                ]
                
                if profile_names.empty:
                    # print("⚠️ No service charge escalation profiles found in 'a.assetco.service.charge.escalation.profiles'.")
                    _local_cache_set(profile_cache, cache_key, profiles)
                    return profiles
                
                profile_names_list = profile_names.iloc[0]
                
                # Get escalation rates - note the correct named range is 'a.assetco.service.charge.escalations' 
                escalation_rates = assumptions.loc[
                    assumptions["name"] == "a.assetco.service.charge.escalations", "value"
                ]
                
                if escalation_rates.empty:
                    # print("⚠️ No service charge escalation rates found in 'a.assetco.service.charge.escalations'.")
                    _local_cache_set(profile_cache, cache_key, profiles)
                    return profiles
                
                escalation_rates_data = escalation_rates.iloc[0]
                
                # Build profile dictionary
                # Structure: profile_names_list = ['Profile1', 'Profile2', ...]
                # escalation_rates_data = [[yr1_rate, yr2_rate, ...], [yr1_rate, yr2_rate, ...], ...]
                
                if isinstance(profile_names_list, list):
                    for idx, name in enumerate(profile_names_list):
                        if name and not pd.isna(name):
                            name_str = str(name).strip()
                            profiles[name_str] = {}
                            
                            # Check if escalation_rates_data is 2D
                            if isinstance(escalation_rates_data, list):
                                if idx < len(escalation_rates_data):
                                    rate_row = escalation_rates_data[idx]
                                    if isinstance(rate_row, list):
                                        for year_idx, rate in enumerate(rate_row):
                                            year_num = year_idx + 1  # Year 1, 2, 3, ...
                                            if rate is not None and not pd.isna(rate) and rate != "":
                                                try:
                                                    profiles[name_str][year_num] = float(rate)
                                                except (ValueError, TypeError):
                                                    pass
                                    else:
                                        # Single rate for all years
                                        if rate_row is not None and not pd.isna(rate_row):
                                            try:
                                                rate_row = 0.0 if rate_row == "" else float(rate_row)
                                                profiles[name_str][1] = rate_row
                                            except (ValueError, TypeError):
                                                profiles[name_str][1] = 0.0
                                            
            except Exception as e:
                print(f"⚠️ Error loading service charge escalation profiles: {e}")
            _local_cache_set(profile_cache, cache_key, profiles)
            return profiles


        def fn_get_sc_escalation_rate(profile_name, year_num, profiles):
            """
            Get service charge escalation rate for a given profile and year.
            
            Args:
                profile_name: Name of the escalation profile
                year_num: Year number (1, 2, 3, ...)
                profiles: Dictionary of profiles from fn_get_service_charge_escalation_profiles()
            
            Returns: Escalation rate (e.g., 0.03 for 3%)
            """
            if not profile_name or pd.isna(profile_name):
                return 0.0
            
            profile_name_str = str(profile_name).strip()
            
            if profile_name_str not in profiles:
                return 0.0
            
            profile = profiles[profile_name_str]
            
            # Get rate for the specific year, or the last available year's rate
            rate = None
            if year_num in profile:
                rate = profile[year_num]
            elif profile:
                # If year not found, use the highest available year's rate
                max_year = max(profile.keys())
                rate = profile[max_year]
            
            if rate is None or pd.isna(rate):
                return 0.0
            try:
                return float(rate)
            except (ValueError, TypeError):
                return 0.0


        # =============================================================================
        # HELPER FUNCTIONS
        # =============================================================================

        def fn_get_lease_dates(asset_idx, tenant_type, renewal_flags):
            """Get lease start and end dates for a given tenant type."""
            def parse_date(val):
                if val is None or pd.isna(val):
                    return None
                try:
                    return pd.to_datetime(val)
                except:
                    return None
            
            if tenant_type == "tenant1":
                lease_start = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx)
                lease_end = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
            elif tenant_type == "renewal":
                lease_start = fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, asset_idx)
                lease_end = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx)
            elif tenant_type == "tenant2":
                lease_start = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx)
                lease_end = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx)
            else:
                return None, None
            
            return parse_date(lease_start), parse_date(lease_end)


        def fn_get_renewal_flags():
            """Get renewal flags for all assets."""
            if _num_assets is None:
                return []
            
            renewal_flags = []
            for asset_idx in range(_num_assets):
                renewal = fn_safe_get(Unit.LeaseExpirationTenant1.renewal, asset_idx)
                if renewal and isinstance(renewal, str) and renewal.strip().lower() == "yes":
                    renewal_flags.append(True)
                else:
                    renewal_flags.append(False)
            return renewal_flags


        def fn_get_lease_year_for_period(period_start, lease_start):
            """
            Determine which lease year a period falls into.
            Year 1 = first 12 months from lease start, Year 2 = next 12 months, etc.
            """
            if lease_start is None or period_start is None:
                return None
            
            if period_start < lease_start:
                return None
            
            months_diff = (period_start.year - lease_start.year) * 12 + (period_start.month - lease_start.month)
            year_num = (months_diff // 12) + 1
            return year_num


        def fn_get_sc_year_for_period(period_start, lease_start):
            """
            Determine which SERVICE CHARGE year a period falls into.
            
            Year 1 = calendar year in which lease starts
            Year 2 = next calendar year
            etc.
            
            Example: If lease starts Apr 2019
            - Apr 2019 to Dec 2019 -> Year 1
            - Jan 2020 to Dec 2020 -> Year 2
            - Jan 2021 to Dec 2021 -> Year 3
            """
            if lease_start is None or period_start is None:
                return None
            
            if period_start < lease_start:
                return None
            
            # Year 1 = calendar year of lease start
            # Year 2 = lease_start.year + 1, etc.
            year_num = period_start.year - lease_start.year + 1
            return year_num


        def fn_get_calendar_year_for_lease(lease_start, year_num):
            """
            Get calendar year for a given lease year number.
            Year 1 is the year in which the lease starts.
            """
            if lease_start is None:
                return None
            return lease_start.year + (year_num - 1)


        # =============================================================================
        # SERVICE CHARGE COMPUTATION
        # =============================================================================

        def fn_check_tenant_applicability(asset_idx, tenant_type):
            """
            Check if a tenant type is applicable for this asset.
            Requires GLA > 0 (skips phantom / empty units) and valid lease dates.
            """
            # Universal guard: GLA must be > 0
            if not _is_asset_gla_positive(asset_idx):
                return False

            def _is_valid_date(val):
                if val is None:
                    return False
                if pd.isna(val):
                    return False
                if isinstance(val, str) and val.strip() == '':
                    return False
                return True
            
            if tenant_type == "tenant1":
                return True
            
            elif tenant_type == "renewal":
                ls = fn_safe_get(Unit.LeaseParametersRenewal.lease_start_date, asset_idx)
                le = fn_safe_get(Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx)
                return _is_valid_date(ls) and _is_valid_date(le)
            
            elif tenant_type == "tenant2":
                ls = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx)
                le = fn_safe_get(Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx)
                return _is_valid_date(ls) and _is_valid_date(le)
            
            return False


        def fn_compute_service_charge(asset_idx, tenant_type, renewal_flags, base_rent_df, sc_profiles):
            """
            Compute service charge for an asset.
            
            First checks:
            - If tenant type is applicable (renewal/T2 flags)
            - If service_charge_basis is valid
            
            Two methods based on service_charge_basis:
            1. % of Base Rent: service_charge_percentage × base_rent (no escalation)
            2. SAR per GLA: escalated_sar_per_sqm × GLA (with escalation)
            
            Escalation is based on LEASE YEAR (not calendar year):
            - Year 1 = first 12 months from lease start
            - Year 2 = months 13-24 from lease start
            - etc.
            
            Returns: Series of service charge per period
            """
            result = np.zeros(_num_periods)
            
            # Check if this tenant type is applicable for this asset
            if not fn_check_tenant_applicability(asset_idx, tenant_type):
                return pd.Series(result, index=range(_num_periods))
            
            # Get lease dates
            lease_start, lease_end = fn_get_lease_dates(asset_idx, tenant_type, renewal_flags)
            
            if lease_start is None:
                return pd.Series(result, index=range(_num_periods))
            
            # Get GLA — 0 or missing → 0.0 (no service charge if no leasable area)
            gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
            if gla is None or pd.isna(gla):
                gla = 0.0
            else:
                try:
                    gla = float(gla)
                except (ValueError, TypeError):
                    gla = 0.0
            # Note: GLA is only used for "SAR per GLA" basis; for "% of Base Rent"
            # the base_rent already includes GLA from the escalation module.
            
            # Get service charge parameters based on tenant type
            if tenant_type == "tenant1":
                sc_basis = fn_safe_get(Unit.RentParametersFirstTenant.service_charge_basis, asset_idx)
                sc_percentage = fn_safe_get(Unit.RentParametersFirstTenant.service_charge_percentage, asset_idx)
                sc_sar_per_sqm = fn_safe_get(Unit.RentParametersFirstTenant.service_charge_sar_per_sqm, asset_idx)
                sc_escalation_profile = fn_safe_get(Unit.RentParametersFirstTenant.sc_escalation, asset_idx)
            elif tenant_type == "renewal":
                sc_basis = fn_safe_get(Unit.RentParametersRenewal.service_charge_basis, asset_idx)
                sc_percentage = fn_safe_get(Unit.RentParametersRenewal.service_charge_percentage, asset_idx)
                sc_sar_per_sqm = fn_safe_get(Unit.RentParametersRenewal.service_charge_sar_per_sqm, asset_idx)
                sc_escalation_profile = fn_safe_get(Unit.RentParametersRenewal.sc_escalation, asset_idx)
            elif tenant_type == "tenant2":
                sc_basis = fn_safe_get(Unit.RentParametersSecondTenant.service_charge_basis, asset_idx)
                sc_percentage = fn_safe_get(Unit.RentParametersSecondTenant.service_charge_percentage, asset_idx)
                sc_sar_per_sqm = fn_safe_get(Unit.RentParametersSecondTenant.service_charge_sar_per_sqm, asset_idx)
                sc_escalation_profile = fn_safe_get(Unit.RentParametersSecondTenant.sc_escalation, asset_idx)
            else:
                return pd.Series(result, index=range(_num_periods))
            
            # Check if service_charge_basis is provided
            if sc_basis is None or pd.isna(sc_basis) or str(sc_basis).strip() == "":
                # No service charge basis defined - return zeros
                return pd.Series(result, index=range(_num_periods))
            
            # Clean up values - ensure floats
            if sc_percentage is None or pd.isna(sc_percentage):
                sc_percentage = 0.0
            else:
                try:
                    sc_percentage = float(sc_percentage)
                except (ValueError, TypeError):
                    sc_percentage = 0.0
            # Normalize: if entered as whole number (e.g. 6 meaning 6%), convert to decimal
            if sc_percentage > 1:
                sc_percentage = sc_percentage / 100.0
            
            if sc_sar_per_sqm is None or pd.isna(sc_sar_per_sqm):
                sc_sar_per_sqm = 0.0
            else:
                try:
                    sc_sar_per_sqm = float(sc_sar_per_sqm)
                except (ValueError, TypeError):
                    sc_sar_per_sqm = 0.0
            
            # Determine basis type - must match EXACTLY one method
            sc_basis_lower = str(sc_basis).lower().strip()
            is_percentage_of_rent = False
            is_sar_per_gla = False
            
            # Check for % of Base Rent
            if "%" in sc_basis_lower or "percent" in sc_basis_lower or "base rent" in sc_basis_lower:
                is_percentage_of_rent = True
                # Validate: percentage must be provided
                if sc_percentage == 0:
                    return pd.Series(result, index=range(_num_periods))
            # Check for SAR per GLA
            elif "sar" in sc_basis_lower or "gla" in sc_basis_lower or "sqm" in sc_basis_lower:
                is_sar_per_gla = True
                # Validate: SAR per sqm must be provided
                if sc_sar_per_sqm == 0:
                    return pd.Series(result, index=range(_num_periods))
            else:
                # Unrecognized basis type - return zeros
                return pd.Series(result, index=range(_num_periods))
            
            # Get base rent series for this asset from the base rent dataframe
            base_rent_row = base_rent_df.iloc[asset_idx].values if base_rent_df is not None else np.zeros(_num_periods)
            
            # Compute service charge for each period
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                # Check if period is within lease
                if lease_start and period_end < lease_start:
                    continue
                if lease_end and period_start > lease_end:
                    continue
                
                if is_percentage_of_rent:
                    # Method 1: % of Base Rent (no escalation)
                    base_rent_month = base_rent_row[col_idx] if col_idx < len(base_rent_row) else 0
                    result[col_idx] = base_rent_month * sc_percentage
                    
                elif is_sar_per_gla:
                    # Method 2: SAR per GLA with escalation
                    # Determine SC YEAR for this period (calendar year based)
                    # Year 1 = calendar year of lease start, Year 2 = next calendar year, etc.
                    year_num = fn_get_sc_year_for_period(period_start, lease_start)
                    
                    if year_num is None or year_num < 1:
                        year_num = 1
                    
                    # Compute escalated SAR per sqm (compound from Year 1)
                    # Year 1: base rate * (1 + esc_yr1)
                    # Year 2: Year1 rate * (1 + esc_yr2), etc.
                    escalated_sar = sc_sar_per_sqm
                    for yr in range(1, year_num + 1):
                        yr_rate = fn_get_sc_escalation_rate(sc_escalation_profile, yr, sc_profiles)
                        escalated_sar = escalated_sar * (1 + yr_rate)
                    
                    # Monthly service charge = escalated SAR per sqm (monthly rate) * GLA
                    # Note: SAR input is already monthly (SAR per month per sqm)
                    result[col_idx] = escalated_sar * gla
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # LEASING COMMISSION COMPUTATION
        # =============================================================================

        def fn_compute_leasing_commission(asset_idx, tenant_type, renewal_flags, base_rent_df, tor_rent_df):
            """
            Compute leasing commission for an asset.
            
            First checks:
            - If tenant type is applicable (renewal/T2 flags)
            - If leasing_commission percentage is provided and > 0
            
            - Compute first 12 months base rent from lease start
            - Multiply by leasing_commission %
            - Pay on lease start date
            
            Returns: Series with leasing commission at lease start period
            """
            result = np.zeros(_num_periods)
            
            # Check if this tenant type is applicable for this asset
            if not fn_check_tenant_applicability(asset_idx, tenant_type):
                return pd.Series(result, index=range(_num_periods))
            
            # Get lease dates
            lease_start, lease_end = fn_get_lease_dates(asset_idx, tenant_type, renewal_flags)
            
            if lease_start is None:
                return pd.Series(result, index=range(_num_periods))
            
            # Get leasing commission percentage
            if tenant_type == "tenant1":
                lc_percentage = fn_safe_get(Unit.RentParametersFirstTenant.leasing_commission, asset_idx)
            elif tenant_type == "renewal":
                lc_percentage = fn_safe_get(Unit.RentParametersRenewal.leasing_commission, asset_idx)
            elif tenant_type == "tenant2":
                lc_percentage = fn_safe_get(Unit.RentParametersSecondTenant.leasing_commission, asset_idx)
            else:
                return pd.Series(result, index=range(_num_periods))
            
            # Check if leasing commission is provided and valid
            if lc_percentage is None or pd.isna(lc_percentage) or lc_percentage == 0:
                return pd.Series(result, index=range(_num_periods))
            try:
                lc_percentage = float(lc_percentage)
            except (ValueError, TypeError):
                return pd.Series(result, index=range(_num_periods))
            if lc_percentage > 1:
                lc_percentage = lc_percentage / 100.0
            
            # Get base rent series for this asset from the base rent dataframe
            base_rent_row = base_rent_df.iloc[asset_idx].values if base_rent_df is not None else np.zeros(_num_periods)
            tor_rent_row = tor_rent_df.iloc[asset_idx].values if tor_rent_df is not None else np.zeros(_num_periods)

            # Resolve the first lease year window for this tenant type
            if tenant_type in ["tenant1", "renewal"]:
                lease_years = fn_get_lease_years(asset_idx, "tenant1_and_renewal", renewal_flags)
                is_renewal_period = (tenant_type == "renewal")
            else:
                lease_years = fn_get_lease_years(asset_idx, "tenant2", renewal_flags)
                is_renewal_period = False

            first_year = None
            for ly in lease_years:
                if ly["year_num"] == 1 and ly.get("is_renewal_period", False) == is_renewal_period:
                    first_year = ly
                    break

            if first_year is None:
                return pd.Series(result, index=range(_num_periods))

            first_year_start = first_year["start"]
            first_year_end = first_year["end"]
            first_year_collection_idx = first_year.get("collection_period_idx")
            
            # Compute first-year gross rent (base + TOR)
            first_year_base_rent = 0.0
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                if period_end < first_year_start:
                    continue
                if period_start > first_year_end:
                    break
                first_year_base_rent += base_rent_row[col_idx] if col_idx < len(base_rent_row) else 0.0

            first_year_tor = 0.0
            if first_year_collection_idx is not None and first_year_collection_idx < len(tor_rent_row):
                first_year_tor = tor_rent_row[first_year_collection_idx]

            first_year_gross_rent = first_year_base_rent + first_year_tor

            # Pay at start of lease period
            payment_period_idx = None
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                if period_start <= first_year_start <= period_end:
                    payment_period_idx = col_idx
                    break

            if payment_period_idx is None:
                return pd.Series(result, index=range(_num_periods))

            leasing_commission = first_year_gross_rent * lc_percentage
            result[payment_period_idx] = leasing_commission
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # TENANT FITOUT ALLOWANCE COMPUTATION
        # =============================================================================

        def fn_get_fitout_payment_profile_values(profile_name):
            """Return monthly fitout payment weights for a profile name.
            Looks up profile_name in dd.assetco.fitout.payment.profiles,
            then returns the corresponding row from a.assetco.tenant_fitout_payment_values.
            """
            if profile_name is None or pd.isna(profile_name) or str(profile_name).strip() == "":
                return None
            try:
                profile_name_str = str(profile_name).strip()
                
                profiles_df = assumptions.loc[
                    assumptions["name"] == "dd.assetco.fitout.payment.profiles", "value"
                ]
                values_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.tenant_fitout_payment_values", "value"
                ]
                if profiles_df.empty or values_df.empty:
                    return None
                profiles = profiles_df.iloc[0]
                values = values_df.iloc[0]
                if not isinstance(profiles, list):
                    return None
                
                # Match profile name (case-insensitive, trimmed)
                profile_idx = None
                for idx, p in enumerate(profiles):
                    if p is not None and str(p).strip().lower() == profile_name_str.lower():
                        profile_idx = idx
                        break
                
                if profile_idx is None:
                    return None
                
                if isinstance(values, list) and len(values) > profile_idx:
                    row = values[profile_idx]
                    if isinstance(row, list):
                        return row
                    return [row]
                return None
            except Exception:
                return None


        def fn_compute_tenant_fitout_allowance(asset_idx, tenant_type, renewal_flags):
            """
            Compute tenant fitout allowance for an asset.
            
            First checks:
            - Only for T1 and T2 (not renewal by definition)
            - For T2: checks if SecondTenant.second_tenant == 'Yes'
            - tenant_fit_out_allowance must be provided and > 0
            - payment_profile_tenant_fit_out_allowance must be provided
            
            - tenant_fit_out_allowance (SAR per sqm) × GLA
            - Pay on payment_profile_tenant_fit_out_allowance
            
            Returns: Series with fitout allowance at payment date period
            """
            result = np.zeros(_num_periods)
            
            # Only for T1 and T2, not renewal
            if tenant_type == "renewal":
                return pd.Series(result, index=range(_num_periods))
            
            # Check if this tenant type is applicable for this asset
            # For T1: always applicable
            # For T2: only if second_tenant == 'Yes'
            if tenant_type == "tenant2":
                if not fn_check_tenant_applicability(asset_idx, tenant_type):
                    return pd.Series(result, index=range(_num_periods))
            
            # Get GLA
            gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
            if pd.isna(gla) or gla == 0:
                return pd.Series(result, index=range(_num_periods))
            
            # Get fitout parameters based on tenant type
            if tenant_type == "tenant1":
                fitout_sar_per_sqm = fn_safe_get(Unit.RentParametersFirstTenant.tenant_fit_out_allowance, asset_idx)
                payment_profile = fn_safe_get(Unit.RentParametersFirstTenant.payment_profilestenant_fit_out_allowance, asset_idx)
            elif tenant_type == "tenant2":
                fitout_sar_per_sqm = fn_safe_get(Unit.RentParametersSecondTenant.tenant_fit_out_allowance, asset_idx)
                payment_profile = fn_safe_get(Unit.RentParametersSecondTenant.payment_profilestenant_fit_out_allowance, asset_idx)
            else:
                return pd.Series(result, index=range(_num_periods))
            
            # Check if fitout allowance is provided and valid
            if fitout_sar_per_sqm is None or pd.isna(fitout_sar_per_sqm) or fitout_sar_per_sqm == 0:
                return pd.Series(result, index=range(_num_periods))
            
            # Resolve lease start for month-1 alignment
            lease_start, _ = fn_get_lease_dates(asset_idx, tenant_type, renewal_flags)
            if lease_start is None or pd.isna(lease_start):
                return pd.Series(result, index=range(_num_periods))

            # Resolve payment profile values (month-wise from lease start)
            profile_values = fn_get_fitout_payment_profile_values(payment_profile)

            # Backward compatibility: allow a specific payment date if profile is not found
            if profile_values is None:
                if payment_profile is None or pd.isna(payment_profile):
                    return pd.Series(result, index=range(_num_periods))
                try:
                    # Handle Excel serial date numbers (e.g. 45678)
                    if isinstance(payment_profile, (int, float)) and not pd.isna(payment_profile):
                        if payment_profile > 25569:
                            payment_date_ts = pd.Timestamp(datetime.fromtimestamp(
                                (payment_profile - 25569) * 86400.0
                            ))
                        else:
                            # Fallback: pay at lease start
                            payment_date_ts = pd.Timestamp(lease_start)
                    elif isinstance(payment_profile, str):
                        payment_date_ts = pd.to_datetime(payment_profile)
                    else:
                        payment_date_ts = pd.Timestamp(payment_profile)
                except Exception:
                    # Last resort fallback: pay at lease start
                    try:
                        payment_date_ts = pd.Timestamp(lease_start)
                    except Exception:
                        return pd.Series(result, index=range(_num_periods))
                payment_period_idx = None
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    period_end = _period_ends_ts[col_idx]
                    if period_start <= payment_date_ts <= period_end:
                        payment_period_idx = col_idx
                        break
                if payment_period_idx is None:
                    return pd.Series(result, index=range(_num_periods))
                fitout_allowance = fitout_sar_per_sqm * gla
                result[payment_period_idx] = fitout_allowance
                return pd.Series(result, index=range(_num_periods))
            
            # Fitout allowance = SAR per sqm × GLA
            fitout_allowance = fitout_sar_per_sqm * gla

            # Normalize weights; allow percent inputs
            weights = []
            for val in profile_values:
                if val is None or (isinstance(val, str) and val.strip() == ""):
                    weights.append(0.0)
                    continue
                if pd.isna(val):
                    weights.append(0.0)
                    continue
                try:
                    weights.append(float(val))
                except (ValueError, TypeError):
                    weights.append(0.0)

            if not weights:
                return pd.Series(result, index=range(_num_periods))

            max_weight = max(weights) if weights else 0.0
            if max_weight > 1:
                weights = [w / 100.0 for w in weights]

            # Apply monthly weights starting from lease start month (month 1)
            for month_offset, weight in enumerate(weights):
                if weight == 0:
                    continue
                pay_date = lease_start + relativedelta(months=month_offset)
                payment_period_idx = None
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    period_end = _period_ends_ts[col_idx]
                    if period_start <= pay_date <= period_end:
                        payment_period_idx = col_idx
                        break
                if payment_period_idx is None:
                    continue
                result[payment_period_idx] += fitout_allowance * weight
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # GET BASE RENT DATAFRAME FOR TENANT TYPE
        # =============================================================================

        def fn_get_base_rent_for_tenant_type(tenant_type):
            """
            Get the appropriate base rent DataFrame based on tenant type.
            Uses all_tenant_results from AM_Co_03_base_rent_module.
            """
            if all_tenant_results is None:
                return None
            
            if tenant_type == "tenant1":
                return all_tenant_results.get("tenant1", {}).get("escalated_rent")
            elif tenant_type == "renewal":
                return all_tenant_results.get("renewal", {}).get("escalated_rent")
            elif tenant_type == "tenant2":
                return all_tenant_results.get("tenant2", {}).get("escalated_rent")
            else:
                return None


        # =============================================================================
        # MAIN COMPUTATION FOR ALL ASSETS
        # =============================================================================

        def fn_compute_all_tenant_other_inputs():
            """
            Compute service charge, leasing commission, and tenant fitout for all assets.
            
            Returns: Dictionary with results for each tenant type
            """
            
            cache_key = "module:tenant_other_inputs"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # global _num_assets, _num_periods, _period_starts, _period_ends, _period_starts_ts, _period_ends_ts
            # global model_timeline_me, assumptions, template_asset_timeline
            
            # Initialize module variables if not already done
            # import AM_Co_02_input_assignment_module as mod02
            # if mod02.model_timeline_me is None:
            #     from AM_Co_02_input_assignment_module import fn_run_module_02
            #     fn_run_module_02()
            
            # model_timeline_me = mod02.model_timeline_me
            # assumptions = mod02.assumptions
            # template_asset_timeline = mod02.template_asset_timeline
            
            # # Initialize module-level variables
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = len(model_timeline_me)
            # _period_starts = model_timeline_me["Period Start"].tolist()
            # _period_ends = model_timeline_me["Period End"].tolist()
            # _period_starts_ts = [pd.Timestamp(d) for d in _period_starts]
            # _period_ends_ts = [pd.Timestamp(d) for d in _period_ends]
            
            # Ensure Module 03 is run (for base rent data)
            # import AM_Co_03_base_rent_module as mod03
            # if mod03.all_tenant_results is None:
            #     fn_run_module_03()
            
            # print("Loading service charge escalation profiles...")
            sc_profiles = fn_get_service_charge_escalation_profiles()
            # print(f"   Found {len(sc_profiles)} SC escalation profiles: {list(sc_profiles.keys())}")
            
            # print("Computing renewal flags...")
            renewal_flags = fn_get_renewal_flags()
            
            # print("Computing tenant other inputs for all assets...")
            
            results = {
                "tenant1": {
                    "service_charge": template_asset_timeline.copy(),
                    "leasing_commission": template_asset_timeline.copy(),
                    "tenant_fitout": template_asset_timeline.copy(),
                },
                "renewal": {
                    "service_charge": template_asset_timeline.copy(),
                    "leasing_commission": template_asset_timeline.copy(),
                    "tenant_fitout": template_asset_timeline.copy(),  # Will be zeros
                },
                "tenant2": {
                    "service_charge": template_asset_timeline.copy(),
                    "leasing_commission": template_asset_timeline.copy(),
                    "tenant_fitout": template_asset_timeline.copy(),
                },
            }
            
            # Pre-compute renewal probability array (same as base rent module)
            renewal_probs = np.array([
                fn_normalize_probability(
                    fn_safe_get(Unit.LeaseExpirationTenant1.renewal_probability, i, 1.0),
                    default=1.0
                )
                for i in range(_num_assets)
            ])
            
            tor_results = None
            try:
                tor_results, _ = fn_compute_all_turnover_rent()
            except Exception:
                tor_results = None

            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                # Get base rent DataFrame for this tenant type (from base rent module)
                base_rent_df = fn_get_base_rent_for_tenant_type(tenant_type)

                if tor_results is None:
                    tor_rent_df = None
                elif tenant_type == "tenant2":
                    tor_rent_df = tor_results.get("tenant2", {}).get("turnover_rent")
                else:
                    tor_rent_df = tor_results.get("tenant1_and_renewal", {}).get("turnover_rent")
                
                for asset_idx in range(_num_assets):
                    # Skip units with zero / missing GLA
                    if not _is_asset_gla_positive(asset_idx):
                        continue

                    # Compute service charge
                    service_charge = fn_compute_service_charge(
                        asset_idx, tenant_type, renewal_flags, base_rent_df, sc_profiles
                    )
                    results[tenant_type]["service_charge"].iloc[asset_idx] = service_charge.values
                    
                    # Compute leasing commission
                    leasing_commission = fn_compute_leasing_commission(
                        asset_idx, tenant_type, renewal_flags, base_rent_df, tor_rent_df
                    )
                    results[tenant_type]["leasing_commission"].iloc[asset_idx] = leasing_commission.values
                    
                    # Compute tenant fitout (only for T1 and T2)
                    tenant_fitout = fn_compute_tenant_fitout_allowance(
                        asset_idx, tenant_type, renewal_flags
                    )
                    results[tenant_type]["tenant_fitout"].iloc[asset_idx] = tenant_fitout.values
                
                # ── Renewal probability weighting ──
                # Full T2 (no probability discount), zero out renewal.
                # T1: unweighted (no change)
                if tenant_type == "renewal":
                    # Zero out renewal — not included in CFS
                    for _key in ["service_charge", "leasing_commission", "tenant_fitout"]:
                        results[tenant_type][_key] = pd.DataFrame(
                            np.zeros_like(results[tenant_type][_key].values),
                            index=results[tenant_type][_key].index,
                            columns=results[tenant_type][_key].columns
                        )
                # tenant2: full weight (no (1-prob) discount)
            
            return _cache_set(cache_key, (results, renewal_flags))


        # =============================================================================
        # OUTPUT DATAFRAMES FOR CFS/OUTPUT MODULE
        # =============================================================================

        def fn_create_output_dataframes(results):
            """
            Create single-line output DataFrames for CFS/Output module.
            
            Each DataFrame is a single row with:
            - Monthly: columns = period end dates
            - Annual: columns = years
            
            Values are sum of all tenants (T1 + Renewal + T2) across all units.
            """
            global service_charge_collections_monthly, service_charge_collections_annual
            global leasing_commission_monthly, leasing_commission_annual
            global tenant_fitout_allowance_monthly, tenant_fitout_allowance_annual
            
            # Period end dates for column headers
            period_dates = _period_ends_ts
            
            # =========================================================================
            # SERVICE CHARGE - Sum across all tenants and units
            # =========================================================================
            sc_total_monthly = np.zeros(_num_periods)
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                sc_total_monthly += results[tenant_type]["service_charge"].sum(axis=0).values
            
            service_charge_collections_monthly = pd.DataFrame(
                [sc_total_monthly],
                columns=period_dates,
                index=["Service Charge"]
            )
            
            # Annual aggregation
            sc_yearly = {}
            for col_idx in range(_num_periods):
                year = _period_ends_ts[col_idx].year
                if year not in sc_yearly:
                    sc_yearly[year] = 0.0
                sc_yearly[year] += sc_total_monthly[col_idx]
            
            all_years = sorted(sc_yearly.keys())
            service_charge_collections_annual = pd.DataFrame(
                [[sc_yearly.get(y, 0) for y in all_years]],
                columns=all_years,
                index=["Service Charge"]
            )
            
            # =========================================================================
            # LEASING COMMISSION - Sum across all tenants and units
            # =========================================================================
            lc_total_monthly = np.zeros(_num_periods)
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                lc_total_monthly += results[tenant_type]["leasing_commission"].sum(axis=0).values
            
            leasing_commission_monthly = pd.DataFrame(
                [lc_total_monthly],
                columns=period_dates,
                index=["Leasing Commission"]
            )
            
            # Annual aggregation
            lc_yearly = {}
            for col_idx in range(_num_periods):
                year = _period_ends_ts[col_idx].year
                if year not in lc_yearly:
                    lc_yearly[year] = 0.0
                lc_yearly[year] += lc_total_monthly[col_idx]
            
            leasing_commission_annual = pd.DataFrame(
                [[lc_yearly.get(y, 0) for y in all_years]],
                columns=all_years,
                index=["Leasing Commission"]
            )
            
            # =========================================================================
            # TENANT FITOUT ALLOWANCE - Sum across all tenants and units
            # =========================================================================
            fitout_total_monthly = np.zeros(_num_periods)
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                fitout_total_monthly += results[tenant_type]["tenant_fitout"].sum(axis=0).values
            
            tenant_fitout_allowance_monthly = pd.DataFrame(
                [fitout_total_monthly],
                columns=period_dates,
                index=["Tenant Fitout Allowance"]
            )
            
            # Annual aggregation
            fitout_yearly = {}
            for col_idx in range(_num_periods):
                year = _period_ends_ts[col_idx].year
                if year not in fitout_yearly:
                    fitout_yearly[year] = 0.0
                fitout_yearly[year] += fitout_total_monthly[col_idx]
            
            tenant_fitout_allowance_annual = pd.DataFrame(
                [[fitout_yearly.get(y, 0) for y in all_years]],
                columns=all_years,
                index=["Tenant Fitout Allowance"]
            )
            
            # print("✅ Output DataFrames created (Service Charge, Leasing Commission, Tenant Fitout)")
            
            return {
                "service_charge_monthly": service_charge_collections_monthly,
                "service_charge_annual": service_charge_collections_annual,
                "leasing_commission_monthly": leasing_commission_monthly,
                "leasing_commission_annual": leasing_commission_annual,
                "tenant_fitout_monthly": tenant_fitout_allowance_monthly,
                "tenant_fitout_annual": tenant_fitout_allowance_annual,
            }


        # =============================================================================
        # SUMMARY FUNCTIONS
        # =============================================================================

        def fn_generate_summary(results):
            """Generate summary statistics for all tenant types."""
            summary_data = []
            
            for asset_idx in range(_num_assets):
                unit_id = fn_safe_get(Unit.UnitInputs.unit_id, asset_idx)
                asset_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx)
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
                
                row = {
                    "Unit ID": unit_id,
                    "Asset Name": asset_name,
                    "GLA": gla,
                    # T1
                    "T1 Service Charge Total": results["tenant1"]["service_charge"].iloc[asset_idx].sum(),
                    "T1 Leasing Commission": results["tenant1"]["leasing_commission"].iloc[asset_idx].sum(),
                    "T1 Tenant Fitout": results["tenant1"]["tenant_fitout"].iloc[asset_idx].sum(),
                    # Renewal
                    "Renewal Service Charge Total": results["renewal"]["service_charge"].iloc[asset_idx].sum(),
                    "Renewal Leasing Commission": results["renewal"]["leasing_commission"].iloc[asset_idx].sum(),
                    # T2
                    "T2 Service Charge Total": results["tenant2"]["service_charge"].iloc[asset_idx].sum(),
                    "T2 Leasing Commission": results["tenant2"]["leasing_commission"].iloc[asset_idx].sum(),
                    "T2 Tenant Fitout": results["tenant2"]["tenant_fitout"].iloc[asset_idx].sum(),
                }
                summary_data.append(row)
            
            return pd.DataFrame(summary_data)


        # =============================================================================
        # MODULE INITIALIZATION
        # =============================================================================

        def fn_run_module_05():
            """Initialize and run Module 05 - Tenant Other Inputs."""
            # global _num_assets, _num_periods, _period_starts, _period_ends, _period_starts_ts, _period_ends_ts
            # global model_timeline_me, assumptions, template_asset_timeline
            
            # print("=" * 60)
            # print("MODULE 05: TENANT OTHER INPUTS")
            # print("=" * 60)
            
            # Ensure Module 02 is run first (for timeline data)
            # from AM_Co_02_input_assignment_module import fn_run_module_02
            # import AM_Co_02_input_assignment_module as mod02
            
            # if mod02.model_timeline_me is None:
            #     print("\n📂 Running Module 02 to load inputs...")
            #     fn_run_module_02()
            
            # Get the updated values from module 02
            # model_timeline_me = mod02.model_timeline_me
            # assumptions = mod02.assumptions
            # template_asset_timeline = mod02.template_asset_timeline
            
            # Ensure Module 03 is run first (for base rent data)
            # import AM_Co_03_base_rent_module as mod03
            # if mod03.all_tenant_results is None:
            #     print("\n📂 Running Module 03 to compute base rent...")
            #     fn_run_module_03()
            
            # # Initialize module variables
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = len(model_timeline_me)
            # _period_starts = model_timeline_me["Period Start"].tolist()
            # _period_ends = model_timeline_me["Period End"].tolist()
            # _period_starts_ts = [pd.Timestamp(d) for d in _period_starts]
            # _period_ends_ts = [pd.Timestamp(d) for d in _period_ends]
            
            # print(f"   Assets: {_num_assets}, Periods: {_num_periods}")
            
            # Compute all tenant other inputs
            # print("\n💰 Computing tenant other inputs...")
            results, renewal_flags = fn_compute_all_tenant_other_inputs()
            
            # Create output DataFrames
            # print("\n📋 Creating output DataFrames...")
            fn_create_output_dataframes(results)
            
            # Print summary
            for tenant_type in ["tenant1", "renewal", "tenant2"]:
                total_sc = results[tenant_type]["service_charge"].values.sum()
                total_lc = results[tenant_type]["leasing_commission"].values.sum()
                total_fitout = results[tenant_type]["tenant_fitout"].values.sum()
                # print(f"   {tenant_type}: SC={total_sc:,.0f}, LC={total_lc:,.0f}, Fitout={total_fitout:,.0f}")
            
            # print("\n✅ Module 05 completed successfully!")
            return results, renewal_flags

        # =============================================================================
        # OUTPUT DATAFRAMES (Single-line items for CFS/Output)
        # =============================================================================

        # Monthly output DataFrames
        operating_expenses_monthly = None  # Total opex (sum of all types)
        asset_management_fees_monthly = None
        facility_management_fees_monthly = None
        administration_cost_monthly = None
        insurance_monthly = None
        marketing_cost_monthly = None
        utilities_monthly = None
        bad_debt_monthly = None
        void_period_cost_monthly = None
        other_operating_expenses_monthly = None
        pre_operating_expenses_monthly = None
        sinking_fund_monthly = None

        # Annual output DataFrames
        operating_expenses_annual = None  # Total opex (sum of all types)
        asset_management_fees_annual = None
        facility_management_fees_annual = None
        administration_cost_annual = None
        insurance_annual = None
        marketing_cost_annual = None
        utilities_annual = None
        bad_debt_annual = None
        void_period_cost_annual = None
        other_operating_expenses_annual = None
        pre_operating_expenses_annual = None
        sinking_fund_annual = None


        # =============================================================================
        # OPERATING EXPENSE TYPES
        # =============================================================================

        OPEX_TYPES = [
            "asset_management_fees",
            "facility_management_fees",
            "administration_cost",
            "insurance",
            "marketing_cost",
            "utilities",
            "bad_debt",
            "void_period_cost",
            "other_operating_expenses",
            "sinking_fund",
        ]

        # Named range mapping for actuals (s.assetco.{name})
        OPEX_NAMED_RANGE_MAP = {
            "asset_management_fees": "s.assetco.asset.management.fees",
            "facility_management_fees": "s.assetco.facility.management.fees",
            "administration_cost": "s.assetco.administration.cost",
            "insurance": "s.assetco.insurance",
            "marketing_cost": "s.assetco.marketing.cost",
            "utilities": "s.assetco.utilities",
            "bad_debt": "s.assetco.bad.debt",
            "void_period_cost": "s.assetco.void.period.cost",
            "other_operating_expenses": "s.assetco.other.operating.expenses",
            "pre_operating_expenses": "s.assetco.pre.operating.expenses",
            "sinking_fund": "s.assetco.sinking.fund",
        }


        # =============================================================================
        # GET OPEX ESCALATION PROFILES
        # =============================================================================

        def fn_get_opex_escalation_profiles():
            """
            Load operating expense escalation profiles from assumptions.
            
            Returns: Dictionary mapping profile_name -> {year: rate}
            """
            
            cache_key = "opex_escalation_profiles"
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached
            
            profiles = {}
            
            try:
                # Get profile names
                profile_names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.opex.escalation.rate.profiles", "value"
                ]
                if profile_names_df.empty:
                    _local_cache_set(profile_cache, cache_key, profiles)
                    return profiles
                profile_names = profile_names_df.iloc[0]
                
                if profile_names is None or (isinstance(profile_names, float) and pd.isna(profile_names)):
                    # print("⚠️ No opex escalation profiles found.")
                    return profiles
                
                # Get escalation rates - each profile has a list of rates per year
                escalation_rates_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.opex.escalation.rates", "value"
                ]
                if escalation_rates_df.empty:
                    return profiles
                escalation_rates = escalation_rates_df.iloc[0]
                
                if escalation_rates is None or (isinstance(escalation_rates, float) and pd.isna(escalation_rates)):
                    # print("⚠️ No opex escalation rates found.")
                    return profiles
                
                # Build profiles dictionary
                # escalation_rates is a list of lists: [profile_rates_list for each profile]
                # Each profile_rates_list has rates for years 1, 2, 3, ...
                for i, profile_name in enumerate(profile_names):
                    profiles[profile_name] = {}
                    if i < len(escalation_rates):
                        year_rates = escalation_rates[i]
                        if isinstance(year_rates, list):
                            for year_idx, rate in enumerate(year_rates):
                                year = year_idx + 1
                                if rate is not None and not (isinstance(rate, float) and pd.isna(rate)):
                                    try:
                                        profiles[profile_name][year] = float(rate)
                                    except (ValueError, TypeError):
                                        profiles[profile_name][year] = 0.0
                                else:
                                    profiles[profile_name][year] = 0.0
                        else:
                            # Single value - use for all years
                            if year_rates is not None:
                                try:
                                    profiles[profile_name][1] = float(year_rates)
                                except (ValueError, TypeError):
                                    profiles[profile_name][1] = 0.0
                            else:
                                profiles[profile_name][1] = 0.0
                
                return profiles
                
            except Exception as e:
                print(f"⚠️ Error loading opex escalation profiles: {e}")
                return profiles


        def fn_get_opex_escalation_rate(profile_name, year_num, profiles):
            """Get escalation rate for a specific profile and year."""
            if profile_name is None or pd.isna(profile_name):
                return 0.0
            
            profile_name = str(profile_name).strip()
            if profile_name not in profiles:
                return 0.0
            
            rate = profiles[profile_name].get(year_num, 0)
            if rate is None or pd.isna(rate):
                return 0.0
            try:
                return float(rate)
            except (ValueError, TypeError):
                return 0.0


        # =============================================================================
        # GET OPEX YEAR FOR PERIOD
        # =============================================================================

        def fn_get_opex_year_for_period(period_start, opex_start_date):
            """
            Determine which OPEX year a period falls into.
            
            Year 1 = calendar year of opex_start_date
            Year 2 = next calendar year, etc.
            """
            if opex_start_date is None or period_start is None:
                return None
            
            if period_start < opex_start_date:
                return None
            
            start_year = opex_start_date.year
            period_year = period_start.year
            
            year_num = period_year - start_year + 1
            return max(1, year_num)


        # =============================================================================
        # GET GLOBAL INPUTS
        # =============================================================================

        def fn_get_asset_sale_date():
            """Get asset sale date from global inputs."""
            try:
                sale_date = Global.ModelInputs.asset_sale_date
                return pd.to_datetime(sale_date) if sale_date and not pd.isna(sale_date) else None
            except:
                return None


        def fn_get_acquisition_date():
            """Get analysis date from global inputs."""
            try:
                acquisition_date = Global.ModelInputs.acquisition_date
                # print(f"   🔍 fn_get_acquisition_date: raw value={acquisition_date}, type={type(acquisition_date)}")
                if acquisition_date and not pd.isna(acquisition_date):
                    result = pd.to_datetime(acquisition_date)
                    # print(f"   🔍 fn_get_acquisition_date: parsed={result}")
                    return result
                # print(f"   ⚠️ fn_get_acquisition_date: returning None (empty/NaN)")
                return None
            except Exception as e:
                print(f"   ⚠️ fn_get_acquisition_date: exception {e}")
                return None


        def fn_get_operations_start():
            """Get operations start date from global inputs."""
            try:
                ops_start = Global.ModelInputs.operations_start
                return pd.to_datetime(ops_start) if ops_start and not pd.isna(ops_start) else None
            except:
                return None


        def fn_get_total_gla():
            """Get total GLA - first try Global.AssetDetails, then sum from Unit data."""
            import datetime as dt
            try:
                # First try Global.AssetDetails
                gla = Global.AssetDetails.gla_sum_of_assetco_inputs
                # print(f"   🔍 fn_get_total_gla: Global.AssetDetails.gla_sum_of_assetco_inputs = {gla}, type={type(gla)}")
                if gla is not None and not pd.isna(gla):
                    # Handle if it's stored as a date (Excel serial number read as datetime)
                    if isinstance(gla, (pd.Timestamp, dt.datetime)):
                        result = float((pd.Timestamp(gla) - pd.Timestamp('1899-12-30')).days)
                        # print(f"   🔍 fn_get_total_gla: from Global (date) = {result}")
                        return result
                    try:
                        result = float(gla)
                        if result > 0:
                            # print(f"   🔍 fn_get_total_gla: from Global = {result}")
                            return result
                    except:
                        pass
                
                # Fallback: Sum from Unit.UnitInputs.gross_leasable_area
                unit_gla = Unit.UnitInputs.gross_leasable_area
                # print(f"   🔍 fn_get_total_gla: Unit.UnitInputs.gross_leasable_area = {unit_gla}, type={type(unit_gla)}")
                if unit_gla is not None:
                    if isinstance(unit_gla, (list, np.ndarray)):
                        total = 0.0
                        # print(f"   🔍 fn_get_total_gla: iterating over {len(unit_gla)} values")
                        for i, val in enumerate(unit_gla):
                            # print(f"      val[{i}] = {val}, type={type(val)}")
                            if val is not None and not pd.isna(val):
                                try:
                                    total += float(val)
                                except Exception as e:
                                    print(f"   ⚠️ fn_get_total_gla: error converting val[{i}]={val}: {e}")
                        # print(f"   🔍 fn_get_total_gla: summed from Units = {total}")
                        return total
                    else:
                        try:
                            result = float(unit_gla)
                            # print(f"   🔍 fn_get_total_gla: single Unit = {result}")
                            return result
                        except:
                            pass
                
                # print(f"   ⚠️ fn_get_total_gla: no GLA found, returning 0")
                return 0.0
            except Exception as e:
                print(f"   ⚠️ fn_get_total_gla: exception {e}")
                import traceback
                traceback.print_exc()
                return 0.0


        def fn_get_total_gfa():
            """Get total GFA - first try Global.AssetDetails, then use GLA."""
            import datetime as dt
            try:
                # First try Global.AssetDetails
                gfa = Global.AssetDetails.gfa_transferred_from_devco
                # print(f"   🔍 fn_get_total_gfa: Global.AssetDetails.gfa_transferred_from_devco = {gfa}, type={type(gfa)}")
                if gfa is not None and not pd.isna(gfa):
                    if isinstance(gfa, (pd.Timestamp, dt.datetime)):
                        result = float((pd.Timestamp(gfa) - pd.Timestamp('1899-12-30')).days)
                        # print(f"   🔍 fn_get_total_gfa: from Global (date) = {result}")
                        return result
                    try:
                        result = float(gfa)
                        if result > 0:
                            # print(f"   🔍 fn_get_total_gfa: from Global = {result}")
                            return result
                    except:
                        pass
                
                # Fallback: Use GLA (same as GFA for simplicity)
                total_gla = fn_get_total_gla()
                if total_gla > 0:
                    # print(f"   🔍 fn_get_total_gfa: using GLA as GFA = {total_gla}")
                    return total_gla
                
                # print(f"   ⚠️ fn_get_total_gfa: no GFA found")
                return 0.0
            except Exception as e:
                print(f"   ⚠️ fn_get_total_gfa: exception {e}")
                import traceback
                traceback.print_exc()
                return 0.0


        # =============================================================================
        # GET OPEX INPUTS FOR EACH TYPE
        # =============================================================================

        def fn_get_opex_inputs(opex_type):
            """
            Get operating expense inputs for a given type.
            
            Returns dict with: input_type, cost_type, start_date, ad_hoc_amount, 
                            cost_per_sqm, percentage_of_revenue, escalation_profile
            """
            oe = Global.OperatingExpenses
            
            try:
                inputs = {
                    "input_type": getattr(oe, f"{opex_type}_input_type", None),
                    "cost_type": getattr(oe, f"{opex_type}_cost_type", None),
                    "start_date": getattr(oe, f"{opex_type}_start_date", None),
                    "ad_hoc_amount": getattr(oe, f"{opex_type}_ad_hoc_amount", 0),
                    "cost_per_sqm": getattr(oe, f"{opex_type}_cost_per_sqm", 0),
                    "percentage_of_revenue": getattr(oe, f"{opex_type}_percentage_of_lease_revenue", 0),
                    "escalation_profile": getattr(oe, f"{opex_type}_cost_escalation_profile", None),
                }
                
                # Debug: # print raw values before processing
                # print(f"   🔍 DEBUG fn_get_opex_inputs({opex_type}):")
                # print(f"      raw input_type = {inputs['input_type']}")
                # print(f"      raw cost_type = {inputs['cost_type']}")
                # print(f"      raw ad_hoc_amount = {inputs['ad_hoc_amount']}")
                # print(f"      raw cost_per_sqm = {inputs['cost_per_sqm']}")
                # print(f"      raw percentage_of_revenue = {inputs['percentage_of_revenue']}")
                # print(f"      raw start_date = {inputs['start_date']}")
                
                # Parse start date
                if inputs["start_date"] and not pd.isna(inputs["start_date"]):
                    inputs["start_date"] = pd.to_datetime(inputs["start_date"])
                else:
                    inputs["start_date"] = None
                
                # Clean numeric values - ensure float conversion
                for key in ["ad_hoc_amount", "cost_per_sqm", "percentage_of_revenue"]:
                    val = inputs[key]
                    if val is None or pd.isna(val):
                        inputs[key] = 0.0
                    else:
                        try:
                            inputs[key] = float(val)
                        except (ValueError, TypeError):
                            inputs[key] = 0.0
                
                # print(f"      processed: ad_hoc={inputs['ad_hoc_amount']}, cost_per_sqm={inputs['cost_per_sqm']}, pct={inputs['percentage_of_revenue']}")
                
                return inputs
                
            except Exception as e:
                print(f"⚠️ Error getting inputs for {opex_type}: {e}")
                return None


        # =============================================================================
        # INPUT MODE HANDLING (Actuals, Forecast, Actuals + Forecast)
        # =============================================================================

        def fn_get_opex_input_mode(input_type):
            """
            Determine input mode from input_type dropdown value.
            
            Args:
                input_type: Value from dropdown (e.g., "Actuals", "Actuals + Forecast", "Forecast")
            
            Returns:
                "actuals_only", "actuals_and_forecast", or "forecast_only"
            """
            if input_type is None or pd.isna(input_type):
                # print(f"   🔍 fn_get_opex_input_mode: input_type is None/NaN, defaulting to forecast_only")
                return "forecast_only"  # Default to forecast if not specified
            
            input_type_str = str(input_type).strip().lower()
            # print(f"   🔍 fn_get_opex_input_mode: input_type_str='{input_type_str}'")
            
            # Check for exact matches (handling dropdown values)
            if input_type_str == "actuals":
                return "actuals_only"
            elif input_type_str == "actuals + forecast" or input_type_str == "actuals+forecast":
                return "actuals_and_forecast"
            elif input_type_str == "forecast":
                return "forecast_only"
            
            # Fallback pattern matching
            if "actual" in input_type_str and "forecast" in input_type_str:
                return "actuals_and_forecast"
            elif "actual" in input_type_str:
                return "actuals_only"
            elif "forecast" in input_type_str:
                return "forecast_only"
            
            # print(f"   ⚠️ fn_get_opex_input_mode: unrecognized '{input_type_str}', defaulting to forecast_only")
            return "forecast_only"  # Default


        def fn_get_opex_actuals(opex_type):
            """
            Read actual opex values from named range.
            
            Args:
                opex_type: Name of the operating expense type
            
            Returns:
                List of monthly values, or None if not found
            """
            named_range = OPEX_NAMED_RANGE_MAP.get(opex_type)
            if named_range is None:
                # print(f"   ⚠️ fn_get_opex_actuals: No named range mapping for {opex_type}")
                return None
            
            try:
                result = assumptions.loc[assumptions["name"] == named_range, "value"]
                if result.empty:
                    # print(f"   ⚠️ Named range '{named_range}' not found for {opex_type}")
                    return None
                
                actuals_data = result.iloc[0]
                
                # print(f"   🔍 fn_get_opex_actuals({opex_type}): raw data type={type(actuals_data)}")
                
                # Handle nested list (if data is 2D array, take first row)
                if isinstance(actuals_data, list) and len(actuals_data) > 0:
                    if isinstance(actuals_data[0], list):
                        actuals_data = actuals_data[0]
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): list with {len(actuals_data)} values")
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): first 5 values={actuals_data[:5]}")
                    return actuals_data
                
                # Handle pandas Series - convert to list for integer indexing
                if isinstance(actuals_data, pd.Series):
                    values_list = actuals_data.values.tolist()
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): Series with {len(values_list)} values")
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): first 5 values={values_list[:5]}")
                    return values_list
                
                # Handle numpy array
                if isinstance(actuals_data, np.ndarray):
                    values_list = actuals_data.tolist()
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): ndarray with {len(values_list)} values")
                    # print(f"   🔍 fn_get_opex_actuals({opex_type}): first 5 values={values_list[:5]}")
                    return values_list
                
                # print(f"   ⚠️ fn_get_opex_actuals({opex_type}): unexpected data type, returning as-is")
                return actuals_data
                
            except Exception as e:
                print(f"   ⚠️ Error reading actuals for {opex_type}: {e}")
                import traceback
                traceback.print_exc()
                return None


        # =============================================================================
        # COMPUTE TOTAL BASE RENT AND TOR FOR EACH PERIOD
        # =============================================================================

        def fn_compute_total_rents():
            """
            Compute total base rent and TOR across all units for each period.
            
            Uses escalated_rent (contracted/accrued amount) so that OPEX
            computed as a % of base rent stays flat when the underlying
            contracted rent is flat.  Collection-curve and probability
            weighting are cash-timing effects that should not bleed into
            the OPEX calculation.
            
            To stay consistent with CFS revenue (which includes T1 + T2,
            renewal excluded), we include only T1 and T2 escalated rent.
            
            Reuses all_tenant_results from Module 03 if already computed.
            
            Returns: (total_base_rent_series, total_gross_rent_series)
            """
            # Use cached Module 03 results if available; otherwise recompute
            if all_tenant_results is not None:
                br = all_tenant_results
            else:
                br = fn_compute_base_rent_all_tenants()
            
            # Use escalated_rent (contracted amount) for % of Rent OPEX
            # Only T1 + T2 to match CFS revenue (renewal excluded)
            base_rent_t1 = br["tenant1"]["escalated_rent"]
            base_rent_t2 = br["tenant2"]["escalated_rent"]
            
            # Sum across all units for each period
            total_base_rent = (
                base_rent_t1.sum(axis=0) + 
                base_rent_t2.sum(axis=0)
            )
            
            # For % of Gross Rent, we need TOR
            # Only compute if needed (will be checked later)
            total_gross_rent = total_base_rent.copy()  # Default to base rent
            
            return total_base_rent, total_gross_rent


        def fn_compute_total_gross_rent_with_tor(total_base_rent):
            """Compute gross rent including TOR - only called if needed."""
            # print("   Computing TOR for gross rent calculation...")
            
            # Get TOR - returns tuple (data_dict, applicability_dict)
            # data_dict has keys: "tenant1_and_renewal" and "tenant2"
            tor_results = fn_compute_all_turnover_rent()
            tor_data, tor_applicability = tor_results
            
            # T1 TOR only (renewal TOR excluded) to match CFS revenue
            tor_t1 = tor_data["tenant1_and_renewal"].get("turnover_rent_t1")
            tor_t2 = tor_data["tenant2"]["turnover_rent"]
            
            total_tor = tor_t2.sum(axis=0)
            if tor_t1 is not None:
                total_tor = total_tor + tor_t1.sum(axis=0)
            
            return total_base_rent + total_tor


        # =============================================================================
        # COMPUTE VOID GLA FOR EACH PERIOD
        # =============================================================================

        def fn_compute_void_gla():
            """
            Compute unoccupied GLA for each period across all units.

            Void periods per unit:
            1. operations_start → T1 start: fully void (unit not yet leased)
            2. T1 active: no void (occupied)
            3. T1 end → T2 start: void = GLA × (1 - renewal_prob)
               - renewal_prob = 0 when renewal is not "Yes" → full void
               - if no T2 and has renewal: weighted void until renewal ends,
                 then full void after renewal ends until asset sale
               - if no T2 and no renewal: full void until asset sale
            4. T2 active: no void (occupied, T2 is certain)
            5. T2 end → asset sale: fully void (all tenants done)

            For ad hoc cost type, the escalated amount is applied whenever
            total void_gla > 0.  For SAR per GLA / SAR per GFA the
            per-period void_gla (or derived void_gfa) is the multiplier.

            Returns: Series of total void GLA per period
            """
            void_gla = np.zeros(_num_periods)
            asset_sale_date = fn_get_asset_sale_date()
            operations_start = fn_get_operations_start()

            for asset_idx in range(_num_assets):
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
                if gla is None or pd.isna(gla):
                    continue
                try:
                    gla = float(gla)
                except (ValueError, TypeError):
                    continue
                if gla <= 0:
                    continue

                # --- Renewal probability ---
                # Renewal excluded from CFS → treat as 0 for void computation
                has_renewal = False
                renewal_prob = 0.0

                # --- T1 dates ---
                t1_start = None
                t1_end = None
                try:
                    t1s = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_start_date, asset_idx)
                    t1e = fn_safe_get(Unit.LeaseParametersFirstTenant.lease_expiration_date, asset_idx)
                    if t1s is not None and not pd.isna(t1s):
                        t1_start = pd.to_datetime(t1s)
                    if t1e is not None and not pd.isna(t1e):
                        t1_end = pd.to_datetime(t1e)
                except Exception:
                    pass

                # --- Renewal end date (only if renewal exists) ---
                renewal_end = None
                if has_renewal:
                    try:
                        re_raw = fn_safe_get(
                            Unit.LeaseParametersRenewal.lease_expiration_date, asset_idx
                        )
                        if re_raw is not None and not pd.isna(re_raw):
                            renewal_end = pd.to_datetime(re_raw)
                    except Exception:
                        pass

                # --- T2 dates (detect by dates, not flag) ---
                t2_start = None
                t2_end = None
                has_t2 = False
                try:
                    t2s = fn_safe_get(
                        Unit.LeaseParametersSecondTenant.lease_start_date, asset_idx
                    )
                    t2e = fn_safe_get(
                        Unit.LeaseParametersSecondTenant.lease_expiration_date, asset_idx
                    )
                    if t2s is not None and not pd.isna(t2s):
                        t2_start = pd.to_datetime(t2s)
                    if t2e is not None and not pd.isna(t2e):
                        t2_end = pd.to_datetime(t2e)
                    if t2_start is not None:
                        has_t2 = True
                except Exception:
                    pass

                # --- Per-period void calculation ---
                # Void = period has NO active tenant (neither T1 nor T2)
                # Bounded by operations_start .. asset_sale_date
                for col_idx in range(_num_periods):
                    ps = _period_starts_ts[col_idx]
                    pe = _period_ends_ts[col_idx]

                    # Skip before operations_start
                    if operations_start and ps < operations_start:
                        continue
                    # Skip after asset sale
                    if asset_sale_date and ps > asset_sale_date:
                        continue

                    # Check if T1 is active this period
                    t1_active = False
                    if t1_start is not None and t1_end is not None:
                        if not (pe < t1_start or ps > t1_end):
                            t1_active = True

                    # Check if T2 is active this period
                    t2_active = False
                    if has_t2 and t2_start is not None:
                        t2_eff_end = t2_end if t2_end is not None else asset_sale_date
                        if t2_eff_end is not None and not (pe < t2_start or ps > t2_eff_end):
                            t2_active = True

                    # If no tenant is active → void
                    if not t1_active and not t2_active:
                        void_gla[col_idx] += gla

            return pd.Series(void_gla, index=range(_num_periods))


        # =============================================================================
        # COMPUTE SINGLE OPERATING EXPENSE
        # =============================================================================

        def fn_compute_opex_forecast(opex_type, col_idx, inputs, opex_profiles, total_base_rent, total_gross_rent, void_gla):
            """
            Compute forecast value for a single period based on cost_type.
            
            Args:
                opex_type: Name of operating expense
                col_idx: Period index
                inputs: Dictionary of opex inputs
                opex_profiles: Escalation profiles dictionary
                total_base_rent: Series of total base rent per period
                total_gross_rent: Series of total gross rent per period
                void_gla: Series of void GLA per period
            
            Returns: Computed value for the period
            """
            cost_type = inputs["cost_type"]
            start_date = inputs["start_date"]
            ad_hoc_amount = inputs["ad_hoc_amount"]
            cost_per_sqm = inputs["cost_per_sqm"]
            pct_revenue = inputs["percentage_of_revenue"]
            esc_profile = inputs["escalation_profile"]
            
            # Get GLA/GFA
            total_gla = fn_get_total_gla()
            total_gfa = fn_get_total_gfa()
            
            # Debug logging (only for first period to avoid spam)
            # if col_idx == 0:
                # print(f"   🔍 DEBUG OPEX {opex_type}: cost_type='{cost_type}', cost_per_sqm={cost_per_sqm}, ad_hoc={ad_hoc_amount}")
                # print(f"   🔍 DEBUG OPEX {opex_type}: total_gla={total_gla}, total_gfa={total_gfa}")
            
            if cost_type is None or pd.isna(cost_type) or str(cost_type).strip() == "":
                # if col_idx == 0:
                    # print(f"   ⚠️ DEBUG OPEX {opex_type}: cost_type is None/empty, returning 0")
                return 0
            
            cost_type_lower = str(cost_type).lower().strip()
            
            # Determine calculation method
            is_ad_hoc = "ad hoc" in cost_type_lower or "adhoc" in cost_type_lower
            is_sar_gfa = "gfa" in cost_type_lower and ("sar" in cost_type_lower or "sqm" in cost_type_lower)
            is_sar_gla = "gla" in cost_type_lower and ("sar" in cost_type_lower or "sqm" in cost_type_lower)
            is_pct_base = "base" in cost_type_lower and ("%" in cost_type_lower or "percent" in cost_type_lower)
            is_pct_gross = "gross" in cost_type_lower and ("%" in cost_type_lower or "percent" in cost_type_lower)
            
            # Debug logging (only for first period)
            # if col_idx == 0:
                # print(f"   🔍 DEBUG OPEX {opex_type}: cost_type_lower='{cost_type_lower}'")
                # print(f"   🔍 DEBUG OPEX {opex_type}: is_ad_hoc={is_ad_hoc}, is_sar_gfa={is_sar_gfa}, is_sar_gla={is_sar_gla}, is_pct_base={is_pct_base}, is_pct_gross={is_pct_gross}")
            
            # For void period cost, only Ad Hoc, SAR per GLA, SAR per GFA allowed
            if opex_type == "void_period_cost":
                if is_pct_base or is_pct_gross:
                    return 0
            
            period_start = _period_starts_ts[col_idx]
            
            # Get escalation year
            year_num = fn_get_opex_year_for_period(period_start, start_date) if start_date else 1
            if year_num is None or year_num < 1:
                year_num = 1
            
            # Calculate base amount
            base_amount = 0
            if is_ad_hoc:
                base_amount = ad_hoc_amount
                # if col_idx == 0:
                    # print(f"   🔍 DEBUG OPEX {opex_type}: AD HOC base_amount = {ad_hoc_amount}")
            elif is_sar_gfa:
                if opex_type == "void_period_cost":
                    # Back-calculate void GFA from void GLA / building_efficiency
                    bldg_eff = Global.AssetDetails.building_efficiency
                    try:
                        bldg_eff_val = float(bldg_eff) if bldg_eff and not pd.isna(bldg_eff) else 0
                    except (ValueError, TypeError):
                        bldg_eff_val = 0
                    if bldg_eff_val > 0:
                        void_gfa = void_gla[col_idx] / bldg_eff_val
                    else:
                        void_gfa = void_gla[col_idx]
                    base_amount = cost_per_sqm * void_gfa
                else:
                    base_amount = cost_per_sqm * total_gfa
            elif is_sar_gla:
                if opex_type == "void_period_cost":
                    # Use void GLA for void period cost
                    base_amount = cost_per_sqm * void_gla[col_idx]
                else:
                    base_amount = cost_per_sqm * total_gla
                # if col_idx == 0:
                    # print(f"   🔍 DEBUG OPEX {opex_type}: SAR per GLA base_amount = {cost_per_sqm} * {total_gla} = {base_amount}")
            elif is_pct_base:
                # % of Base Rent - no escalation
                base_rent_period = total_base_rent[col_idx] if col_idx < len(total_base_rent) else 0
                pct_decimal = pct_revenue if pct_revenue <= 1 else pct_revenue / 100.0
                return pct_decimal * base_rent_period
            elif is_pct_gross:
                # % of Gross Rent - no escalation
                gross_rent_period = total_gross_rent[col_idx] if col_idx < len(total_gross_rent) else 0
                pct_decimal = pct_revenue if pct_revenue <= 1 else pct_revenue / 100.0
                return pct_decimal * gross_rent_period
            else:
                # if col_idx == 0:
                    # print(f"   ⚠️ DEBUG OPEX {opex_type}: NO MATCH for cost_type '{cost_type_lower}', returning 0")
                return 0
            
            # Apply escalation for Ad Hoc, SAR per GFA, SAR per GLA
            # Apply escalation from year 1 onwards
            escalated_amount = base_amount
            for yr in range(1, year_num + 1):
                yr_rate = fn_get_opex_escalation_rate(esc_profile, yr, opex_profiles)
                escalated_amount = escalated_amount * (1 + yr_rate)
            
            # if col_idx == 0:
                # print(f"   🔍 DEBUG OPEX {opex_type}: year_num={year_num}, base={base_amount}, escalated={escalated_amount}")
            
            return escalated_amount


        def fn_compute_opex(opex_type, opex_profiles, total_base_rent, total_gross_rent, void_gla):
            """
            Compute a single operating expense with input mode handling.
            
            Input Modes:
            - Actuals: Read from named range s.assetco.{opex_name}.values
            - Forecast: Compute using cost_type (Ad Hoc, SAR per GFA/GLA, % of Base/Gross Rent)
            - Actuals + Forecast: Actuals for past periods, Forecast for future periods
            
            All values only apply from start_date onwards.
            
            Args:
                opex_type: Name of operating expense
                opex_profiles: Escalation profiles dictionary
                total_base_rent: Series of total base rent per period
                total_gross_rent: Series of total gross rent per period
                void_gla: Series of void GLA per period
            
            Returns: Series of expense per period
            """
            # print(f"\n   🔍 DEBUG fn_compute_opex({opex_type}) STARTING...")
            result = np.zeros(_num_periods)
            
            # Get inputs
            inputs = fn_get_opex_inputs(opex_type)
            if inputs is None:
                # print(f"   ⚠️ DEBUG: inputs is None for {opex_type}, returning zeros")
                return pd.Series(result, index=range(_num_periods))
            
            
            # Get input mode
            input_mode = fn_get_opex_input_mode(inputs["input_type"])
            start_date = inputs["start_date"]
            
            # Get asset sale date and analysis date
            sale_date = fn_get_asset_sale_date()
            acquisition_date = fn_get_acquisition_date()
            operations_start = fn_get_operations_start() if opex_type == "void_period_cost" else None
            
            # print(f"   🔍 DEBUG: sale_date={sale_date}, acquisition_date={acquisition_date}")
            
            # Get actuals if needed
            actuals_data = None
            if input_mode in ["actuals_only", "actuals_and_forecast"]:
                actuals_data = fn_get_opex_actuals(opex_type)
                # print(f"   🔍 DEBUG: actuals_data loaded, type={type(actuals_data)}, len={len(actuals_data) if actuals_data is not None else 'None'}")
                # if actuals_data is None and input_mode == "actuals_only":
                    # print(f"   ⚠️ Actuals mode but no actuals found for {opex_type}")
            
            # Track how many periods are computed
            periods_computed = 0
            periods_skipped_start = 0
            periods_skipped_sale = 0
            actuals_used = 0
            forecast_used = 0
            
            # Debug: count how many periods are past vs future
            past_period_count = 0
            future_period_count = 0
            
            # Compute for each period
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                # Check if before start date - NO expense before start date
                if start_date and period_end < start_date:
                    periods_skipped_start += 1
                    continue
                
                # Check if after sale date
                if sale_date and period_start > sale_date:
                    continue
                
                # Determine if period is in past (actuals) or future (forecast)
                # Past = period_end is BEFORE acquisition_date
                # Future = period_end is ON or AFTER acquisition_date
                is_past_period = acquisition_date and period_end < acquisition_date
                
                if is_past_period:
                    past_period_count += 1
                else:
                    future_period_count += 1
                
                # Log first few periods for debugging
                # if col_idx < 5:
                    # print(f"   🔍 DEBUG Period {col_idx}: period_end={period_end}, acquisition_date={acquisition_date}, is_past={is_past_period}")
                
                # For void_period_cost, skip periods before operations_start and with no void GLA
                if opex_type == "void_period_cost":
                    if operations_start and period_start < operations_start:
                        continue
                    if void_gla[col_idx] == 0:
                        continue
                
                # Compute based on input mode
                if input_mode == "actuals_only":
                    # Use actuals only (but only from start_date onwards)
                    if actuals_data is not None and col_idx < len(actuals_data):
                        val = actuals_data[col_idx]
                        if val is not None and not pd.isna(val):
                            try:
                                result[col_idx] = float(val)
                                actuals_used += 1
                            except:
                                result[col_idx] = 0
                
                elif input_mode == "forecast_only":
                    # Use forecast only (from start_date onwards)
                    computed_val = fn_compute_opex_forecast(
                        opex_type, col_idx, inputs, opex_profiles, 
                        total_base_rent, total_gross_rent, void_gla
                    )
                    result[col_idx] = computed_val
                    if computed_val != 0:
                        periods_computed += 1
                        forecast_used += 1
                
                elif input_mode == "actuals_and_forecast":
                    # Actuals + Forecast: Use actuals where they EXIST (non-zero/non-blank),
                    # forecast for periods where actuals don't exist
                    
                    has_actual = False
                    if actuals_data is not None and col_idx < len(actuals_data):
                        val = actuals_data[col_idx]
                        # Check if actual value exists and is non-zero
                        if val is not None and not pd.isna(val):
                            try:
                                val_float = float(val)
                                if val_float != 0:
                                    result[col_idx] = val_float
                                    actuals_used += 1
                                    has_actual = True
                            except:
                                pass
                    
                    if not has_actual:
                        # No actual available - use forecast
                        computed_val = fn_compute_opex_forecast(
                            opex_type, col_idx, inputs, opex_profiles, 
                            total_base_rent, total_gross_rent, void_gla
                        )
                        result[col_idx] = computed_val
                        if computed_val != 0:
                            forecast_used += 1
            
            # Summary
            total_sum = np.sum(result)
            # print(f"   🔍 DEBUG {opex_type}: past_periods={past_period_count}, future_periods={future_period_count}")
            # print(f"   🔍 DEBUG {opex_type} RESULT: periods_computed={periods_computed}, skipped_start={periods_skipped_start}, skipped_sale={periods_skipped_sale}")
            # print(f"   🔍 DEBUG {opex_type} RESULT: actuals_used={actuals_used}, forecast_used={forecast_used}")
            # print(f"   🔍 DEBUG {opex_type} RESULT: total_sum={total_sum}, first_5_values={result[:5]}")
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # COMPUTE PRE-OPERATING EXPENSES (FROM ACTUALS SCHEDULE)
        # =============================================================================

        def fn_get_pre_operating_expenses_actuals():
            """
            Read pre-operating expenses from actuals schedule named range.
            Named range: s.assetco.pre.operating.expenses
            
            Returns: List of monthly values, or None if not found
            """
            try:
                result = assumptions.loc[assumptions["name"] == "s.assetco.pre.operating.expenses", "value"]
                if result.empty:
                    return None
                return result.iloc[0]
            except Exception as e:
                print(f"⚠️ Error reading pre-operating expenses: {e}")
                return None


        def fn_compute_pre_operating_expenses():
            """
            Compute pre-operating expenses from actuals schedule.
            
            Only applies between acquisition_date and operations_start (exclusive).
            Reads values directly from named range: s.assetco.pre.operating.expenses
            
            Returns: Series of pre-operating expenses per period
            """
            result = np.zeros(_num_periods)
            
            # Get date boundaries
            acquisition_date = fn_get_acquisition_date()
            operations_start = fn_get_operations_start()
            
            # If no operations_start, pre-operating expenses don't apply
            if operations_start is None:
                # print("   ⚠️ No operations_start date - skipping pre-operating expenses")
                return pd.Series(result, index=range(_num_periods))
            
            # Get actuals from named range
            actuals_data = fn_get_pre_operating_expenses_actuals()
            
            if actuals_data is None:
                # print("   ⚠️ Named range 's.assetco.pre.operating.expenses' not found")
                return pd.Series(result, index=range(_num_periods))
            
            # Handle nested list (if data is 2D array, take first row)
            if isinstance(actuals_data, list) and len(actuals_data) > 0:
                if isinstance(actuals_data[0], list):
                    actuals_data = actuals_data[0]
            
            # Apply values only between acquisition_date and operations_start
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                
                # Skip if period is before acquisition_date
                if acquisition_date and period_end < acquisition_date:
                    continue
                
                # Skip if period is >= operations_start (pre-operating ends before operations start)
                if operations_start and period_start >= operations_start:
                    continue
                
                # Get value from actuals schedule
                if isinstance(actuals_data, list) and col_idx < len(actuals_data):
                    val = actuals_data[col_idx]
                    if val is not None and not pd.isna(val):
                        try:
                            result[col_idx] = float(val)
                        except:
                            result[col_idx] = 0
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # COMPUTE ALL OPERATING EXPENSES
        # =============================================================================

        def fn_compute_all_operating_expenses():
            """
            Compute all operating expenses.
            
            Returns: Dictionary with each opex type as key and Series as value
            """

            cache_key = "module:operating_expenses"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

            # Load escalation profiles
            opex_profiles = fn_get_opex_escalation_profiles()

            # Compute total rents
            total_base_rent, total_gross_rent = fn_compute_total_rents()

            # Check if any opex uses % of Gross Rent with non-zero percentage
            needs_tor = False
            for opex_type in OPEX_TYPES:
                inputs = fn_get_opex_inputs(opex_type)
                if inputs and inputs["cost_type"]:
                    input_mode = fn_get_opex_input_mode(inputs["input_type"])
                    if input_mode in ["forecast_only", "actuals_and_forecast"]:
                        ct_lower = str(inputs["cost_type"]).lower().strip()
                        if "gross" in ct_lower and ("%" in ct_lower or "percent" in ct_lower):
                            if inputs.get("percentage_of_revenue", 0) and inputs["percentage_of_revenue"] > 0:
                                needs_tor = True
                                break

            if needs_tor:
                total_gross_rent = fn_compute_total_gross_rent_with_tor(total_base_rent)

            # Compute void GLA
            void_gla = fn_compute_void_gla()

            results = {}

            # ---- Multithreading ----
            max_workers = _cap_workers(min(8, len(OPEX_TYPES)))

            if _is_parallel_active() or max_workers <= 1:
                # Sequential execution
                for opex_type in OPEX_TYPES:
                    results[opex_type] = fn_compute_opex(
                        opex_type,
                        opex_profiles,
                        total_base_rent,
                        total_gross_rent,
                        void_gla,
                    )
            else:
                # Parallel execution
                with _parallel_section():
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            opex_type: executor.submit(
                                fn_compute_opex,
                                opex_type,
                                opex_profiles,
                                total_base_rent,
                                total_gross_rent,
                                void_gla,
                            )
                            for opex_type in OPEX_TYPES
                        }

                        for opex_type, future in futures.items():
                            results[opex_type] = future.result()
            # ---- End multithreading ----

            # Pre-operating expenses
            results["pre_operating_expenses"] = fn_compute_pre_operating_expenses()

            return _cache_set(cache_key, results)



        # =============================================================================
        # CREATE OUTPUT DATAFRAMES (Single-line items for CFS/Output)
        # =============================================================================

        def fn_create_output_dataframes(results):
            """
            Create single-line output DataFrames for each operating expense type.
            
            Args:
                results: Dictionary with opex type as key and Series as value
            """
            global operating_expenses_monthly, operating_expenses_annual
            global asset_management_fees_monthly, asset_management_fees_annual
            global facility_management_fees_monthly, facility_management_fees_annual
            global administration_cost_monthly, administration_cost_annual
            global insurance_monthly, insurance_annual
            global marketing_cost_monthly, marketing_cost_annual
            global utilities_monthly, utilities_annual
            global bad_debt_monthly, bad_debt_annual
            global void_period_cost_monthly, void_period_cost_annual
            global other_operating_expenses_monthly, other_operating_expenses_annual
            global pre_operating_expenses_monthly, pre_operating_expenses_annual
            
            # Create monthly column headers
            monthly_columns = [ps.strftime("%Y-%m") for ps in _period_starts_ts]
            
            # Create annual column headers
            annual_columns = [str(ye) for ye in model_timeline_ye["Year"].values]
            
            # Helper function to create single-line monthly DataFrame
            def create_monthly_df(series, name):
                return pd.DataFrame(
                    [series.values],
                    columns=monthly_columns,
                    index=[name]
                )
            
            # Helper function to aggregate monthly to annual
            def aggregate_to_annual(series):
                annual_values = []
                for year in model_timeline_ye["Year"].values:
                    year_mask = [ps.year == year for ps in _period_starts_ts]
                    year_total = series[year_mask].sum()
                    annual_values.append(year_total)
                return annual_values
            
            # Create individual opex DataFrames
            asset_management_fees_monthly = create_monthly_df(
                results["asset_management_fees"], "Asset Management Fees"
            )
            facility_management_fees_monthly = create_monthly_df(
                results["facility_management_fees"], "Facility Management Fees"
            )
            administration_cost_monthly = create_monthly_df(
                results["administration_cost"], "Administration Cost"
            )
            insurance_monthly = create_monthly_df(
                results["insurance"], "Insurance"
            )
            marketing_cost_monthly = create_monthly_df(
                results["marketing_cost"], "Marketing Cost"
            )
            utilities_monthly = create_monthly_df(
                results["utilities"], "Utilities"
            )
            bad_debt_monthly = create_monthly_df(
                results["bad_debt"], "Bad Debt"
            )
            void_period_cost_monthly = create_monthly_df(
                results["void_period_cost"], "Void Period Cost"
            )
            other_operating_expenses_monthly = create_monthly_df(
                results["other_operating_expenses"], "Other Operating Expenses"
            )
            pre_operating_expenses_monthly = create_monthly_df(
                results["pre_operating_expenses"], "Pre-Operating Expenses"
            )
            
            # Total operating expenses (sum of all 9 types, excluding pre-operating)
            total_opex = sum([results[ot] for ot in OPEX_TYPES])
            operating_expenses_monthly = create_monthly_df(
                total_opex, "Operating Expenses (Total)"
            )
            
            # Create annual DataFrames
            asset_management_fees_annual = pd.DataFrame(
                [aggregate_to_annual(results["asset_management_fees"])],
                columns=annual_columns,
                index=["Asset Management Fees"]
            )
            facility_management_fees_annual = pd.DataFrame(
                [aggregate_to_annual(results["facility_management_fees"])],
                columns=annual_columns,
                index=["Facility Management Fees"]
            )
            administration_cost_annual = pd.DataFrame(
                [aggregate_to_annual(results["administration_cost"])],
                columns=annual_columns,
                index=["Administration Cost"]
            )
            insurance_annual = pd.DataFrame(
                [aggregate_to_annual(results["insurance"])],
                columns=annual_columns,
                index=["Insurance"]
            )
            marketing_cost_annual = pd.DataFrame(
                [aggregate_to_annual(results["marketing_cost"])],
                columns=annual_columns,
                index=["Marketing Cost"]
            )
            utilities_annual = pd.DataFrame(
                [aggregate_to_annual(results["utilities"])],
                columns=annual_columns,
                index=["Utilities"]
            )
            bad_debt_annual = pd.DataFrame(
                [aggregate_to_annual(results["bad_debt"])],
                columns=annual_columns,
                index=["Bad Debt"]
            )
            void_period_cost_annual = pd.DataFrame(
                [aggregate_to_annual(results["void_period_cost"])],
                columns=annual_columns,
                index=["Void Period Cost"]
            )
            other_operating_expenses_annual = pd.DataFrame(
                [aggregate_to_annual(results["other_operating_expenses"])],
                columns=annual_columns,
                index=["Other Operating Expenses"]
            )
            pre_operating_expenses_annual = pd.DataFrame(
                [aggregate_to_annual(results["pre_operating_expenses"])],
                columns=annual_columns,
                index=["Pre-Operating Expenses"]
            )
            
            # Total operating expenses annual
            operating_expenses_annual = pd.DataFrame(
                [aggregate_to_annual(total_opex)],
                columns=annual_columns,
                index=["Operating Expenses (Total)"]
            )
            
            # print("   ✅ Output DataFrames created (monthly and annual)")


        # =============================================================================
        # SUMMARY FUNCTION
        # =============================================================================

        def fn_generate_opex_summary(results):
            """Generate summary of operating expenses."""
            summary = {}
            for opex_type, series in results.items():
                summary[opex_type] = series.sum()
            
            summary["total"] = sum(summary.values())
            return summary


        # =============================================================================
        # MODULE INITIALIZATION
        # =============================================================================

        def fn_run_module_06():
            """Initialize and run Module 06 - Operating Expenses."""
            # global assumptions, model_timeline_me, model_timeline_ye, template_asset_timeline
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts, _num_years
            
            # print("=" * 80)
            # print("AM_Co_06_Operating_Expenses_module")
            # print("=" * 80)
            
            # Step 1: Initialize Module 02 and 03 first
            # print("\n📂 Initializing dependencies...")
            # result = fn_run_module_02()
            # if result is None:
            #     # print("❌ Failed to initialize Module 02")
            #     return None
            
            # assumptions, model_timeline_me, model_timeline_ye, _, _, template_asset_timeline = result
            
            # Initialize Module 03 (base rent) 
            # fn_run_module_03()
            
            # Initialize Module 04 (turnover rent) - needed for gross rent calculation
            # from AM_Co_04_turnover_rent_module import fn_run_module_04
            # fn_run_module_04(assumptions, model_timeline_me)
            
            # Step 2: Set module-level constants
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = template_asset_timeline.shape[1]
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            # _num_years = len(model_timeline_ye)
            
            # # print(f"   Assets: {_num_assets}, Periods: {_num_periods}, Years: {_num_years}")
            
            # Step 3: Compute operating expenses
            results = fn_compute_all_operating_expenses()
            
            # Step 4: Create output DataFrames
            fn_create_output_dataframes(results)
            
            return results

        # =============================================================================
        # OUTPUT DATAFRAMES (Single-line items for CFS/Output)
        # =============================================================================

        # Parking
        parking_revenue_monthly = None
        parking_revenue_annual = None
        parking_opex_monthly = None
        parking_opex_annual = None

        # Other Income
        other_income_1_monthly = None
        other_income_1_annual = None
        other_income_2_monthly = None
        other_income_2_annual = None
        other_income_3_monthly = None
        other_income_3_annual = None
        total_other_income_monthly = None
        total_other_income_annual = None

        # Other Expenses
        other_expense_1_monthly = None
        other_expense_1_annual = None
        other_expense_2_monthly = None
        other_expense_2_annual = None
        other_expense_3_monthly = None
        other_expense_3_annual = None
        total_other_expenses_monthly = None
        total_other_expenses_annual = None


        # =============================================================================
        # HELPER FUNCTIONS
        # NOTE: fn_get_operations_start, fn_get_asset_sale_date, fn_get_total_gla,
        #       fn_get_total_gfa are all defined earlier in the file.
        # =============================================================================


        # NOTE: fn_get_total_gla and fn_get_total_gfa are defined earlier in the file
        # with Unit fallback logic. Do not redefine them here.


        def fn_get_year_for_period(period_start, start_date):
            """
            Determine which year a period falls into.
            Year 1 = calendar year of start_date
            Year 2 = next calendar year, etc.
            """
            if start_date is None or period_start is None:
                return None
            
            if period_start < start_date:
                return None
            
            year_num = period_start.year - start_date.year + 1
            return max(1, year_num)


        # =============================================================================
        # ESCALATION PROFILES
        # =============================================================================

        def fn_get_other_income_expense_escalation_profiles():
            """
            Load other income/expense escalation profiles from assumptions.
            
            Returns: Dictionary mapping profile_name -> {year: rate}
            """
            
            cache_key = "other_income_expense_profiles"
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached
            profiles = {}
            
            try:
                # Try to get from named ranges
                profile_names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.other.income.escalation.profiles", "value"
                ]
                
                escalation_rates_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.other.income.escalations", "value"
                ]
                
                if profile_names_df.empty or escalation_rates_df.empty:
                    # Fallback to OPEX escalation profiles if other I/E profiles not found
                    profile_names_df = assumptions.loc[
                        assumptions["name"] == "a.assetco.opex.escalation.rate.profiles", "value"
                    ]
                    escalation_rates_df = assumptions.loc[
                        assumptions["name"] == "a.assetco.opex.escalation.rates", "value"
                    ]
                
                if not profile_names_df.empty and not escalation_rates_df.empty:
                    profile_names = profile_names_df.iloc[0]
                    escalation_rates = escalation_rates_df.iloc[0]
                    
                    if isinstance(profile_names, list):
                        for idx, name in enumerate(profile_names):
                            if name and not pd.isna(name):
                                name_str = str(name).strip()
                                profiles[name_str] = {}
                                
                                if isinstance(escalation_rates, list) and idx < len(escalation_rates):
                                    rate_row = escalation_rates[idx]
                                    if isinstance(rate_row, list):
                                        for year_idx, rate in enumerate(rate_row):
                                            year_num = year_idx + 1
                                            # Skip None, NaN, and empty strings
                                            if rate is not None and not pd.isna(rate) and str(rate).strip() != '':
                                                try:
                                                    profiles[name_str][year_num] = float(rate)
                                                except (ValueError, TypeError):
                                                    pass
                                    else:
                                        # Skip None, NaN, and empty strings
                                        if rate_row is not None and not pd.isna(rate_row) and str(rate_row).strip() != '':
                                            try:
                                                profiles[name_str][1] = float(rate_row)
                                            except (ValueError, TypeError):
                                                pass
            except Exception as e:
                print(f"⚠️ Error loading other I/E escalation profiles: {e}")
            _local_cache_set(profile_cache, cache_key, profiles)

            return profiles


        def fn_get_parking_escalation_profiles():
            """
            Load parking rate and OPEX escalation profiles from assumptions.
            
            Returns: Dictionary with 'rate' and 'opex' profiles
            """
            cache_key = "parking_escalation_profiles"
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached            

            profiles = {"rate": {}, "opex": {}, "occupancy": {}}
            
            try:
                # Parking rate escalation profiles
                rate_profile_names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.rate.escalation.profiles", "value"
                ]
                rate_escalations_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.rate.escalations", "value"
                ]
                
                if not rate_profile_names_df.empty and not rate_escalations_df.empty:
                    rate_names = rate_profile_names_df.iloc[0]
                    rate_values = rate_escalations_df.iloc[0]
                    
                    if isinstance(rate_names, list):
                        for idx, name in enumerate(rate_names):
                            if name and not pd.isna(name):
                                name_str = str(name).strip()
                                profiles["rate"][name_str] = {}
                                
                                if isinstance(rate_values, list) and idx < len(rate_values):
                                    rate_row = rate_values[idx]
                                    if isinstance(rate_row, list):
                                        for year_idx, rate in enumerate(rate_row):
                                            year_num = year_idx + 1
                                            # Skip None, NaN, and empty strings
                                            if rate is not None and not pd.isna(rate) and str(rate).strip() != '':
                                                try:
                                                    profiles["rate"][name_str][year_num] = float(rate)
                                                except (ValueError, TypeError):
                                                    pass
                
                # Parking OPEX variable profile
                opex_profile_names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.opex.profiles", "value"
                ]
                opex_values_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.opex.values", "value"
                ]
                
                if not opex_profile_names_df.empty and not opex_values_df.empty:
                    opex_names = opex_profile_names_df.iloc[0]
                    opex_values = opex_values_df.iloc[0]
                    
                    if isinstance(opex_names, list):
                        for idx, name in enumerate(opex_names):
                            if name and not pd.isna(name):
                                name_str = str(name).strip()
                                profiles["opex"][name_str] = {}
                                
                                if isinstance(opex_values, list) and idx < len(opex_values):
                                    val_row = opex_values[idx]
                                    if isinstance(val_row, list):
                                        for year_idx, val in enumerate(val_row):
                                            year_num = year_idx + 1
                                            # Skip None, NaN, and empty strings
                                            if val is not None and not pd.isna(val) and str(val).strip() != '':
                                                try:
                                                    profiles["opex"][name_str][year_num] = float(val)
                                                except (ValueError, TypeError):
                                                    pass
                
                # Parking occupancy profile
                occ_profile_names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.occupancy.profiles", "value"
                ]
                occ_values_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.parking.occupancy.rates", "value"
                ]
                
                if not occ_profile_names_df.empty and not occ_values_df.empty:
                    occ_names = occ_profile_names_df.iloc[0]
                    occ_values = occ_values_df.iloc[0]
                    
                    if isinstance(occ_names, list):
                        for idx, name in enumerate(occ_names):
                            if name and not pd.isna(name):
                                name_str = str(name).strip()
                                profiles["occupancy"][name_str] = {}
                                
                                if isinstance(occ_values, list) and idx < len(occ_values):
                                    val_row = occ_values[idx]
                                    if isinstance(val_row, list):
                                        for year_idx, val in enumerate(val_row):
                                            year_num = year_idx + 1
                                            # Skip None, NaN, and empty strings
                                            if val is not None and not pd.isna(val) and str(val).strip() != '':
                                                try:
                                                    profiles["occupancy"][name_str][year_num] = float(val)
                                                except (ValueError, TypeError):
                                                    pass
                                    else:
                                        # Skip None, NaN, and empty strings
                                        if val_row is not None and not pd.isna(val_row) and str(val_row).strip() != '':
                                            try:
                                                profiles["occupancy"][name_str][1] = float(val_row)
                                            except (ValueError, TypeError):
                                                pass
                                            
            except Exception as e:
                print(f"⚠️ Error loading parking escalation profiles: {e}")
            _local_cache_set(profile_cache, cache_key, profiles)

            return profiles


        def fn_get_escalation_rate(profile_name, year_num, profiles):
            """
            Get escalation rate for a given profile and year.
            
            For years beyond the defined profile, return 0 (no escalation).
            This ensures escalation only applies for years with defined rates.
            """
            if not profile_name or pd.isna(profile_name):
                return 0.0
            
            profile_name_str = str(profile_name).strip()
            
            if profile_name_str not in profiles:
                return 0.0
            
            profile = profiles[profile_name_str]
            
            if year_num in profile:
                rate = profile[year_num]
                if rate is None or pd.isna(rate):
                    return 0.0
                try:
                    return float(rate)
                except (ValueError, TypeError):
                    return 0.0
            
            # For years beyond the profile, return 0 (no escalation)
            return 0.0


        def fn_get_profile_value(profile_name, year_num, profiles):
            """
            Get value from profile for a given year (for occupancy, opex amounts).
            
            Unlike escalation rates, profile values should NOT extend beyond defined years.
            If year_num is beyond the profile data, return None (indicating no value/skip).
            """
            if not profile_name or pd.isna(profile_name):
                return None
            
            profile_name_str = str(profile_name).strip()
            
            if profile_name_str not in profiles:
                return None
            
            profile = profiles[profile_name_str]
            
            if year_num in profile:
                val = profile[year_num]
                if val is None or pd.isna(val):
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None
            
            # For occupancy/opex profiles, do NOT extend beyond defined years
            # Return None to indicate parking should stop
            return None


        # =============================================================================
        # INTEREST RATE PROFILES (for financing)
        # =============================================================================

        def fn_get_interest_rate_profiles():
            """
            Load SAIBOR rate profiles from assumptions.
            Tries multiple naming patterns (dd.assetco.saibor.*, a.assetco.saibor.*,
            and legacy dd.assetco.interest.rate.*, a.assetco.interest.rate.*) and
            falls back to fuzzy name search if exact match fails.
            
            Returns: dict mapping profile_name -> {year: annual_rate}
            """
            profiles = {}

            # Candidate naming patterns: (profiles_name, values_name)
            # New SAIBOR named ranges first, then legacy interest rate fallbacks
            _candidates = [
                ("dd.assetco.saibor.profiles", "a.assetco.saibor.values"),
                ("a.assetco.saibor.profiles",  "a.assetco.saibor.values"),
                ("dd.assetco.saibor.profiles", "dd.assetco.saibor.values"),
                ("dd.assetco.interest.rate.profiles", "dd.assetco.interest.rate.values"),
                ("a.assetco.interest.rate.profiles",  "a.assetco.interest.rate.values"),
                ("a.assetco.interest.rate.profiles",  "a.assetco.interest.rates"),
                ("dd.assetco.interest.rate.profiles", "dd.assetco.interest.rates"),
            ]

            profile_names = None
            rate_values = None

            try:
                # Try exact naming patterns first
                for pn_name, rv_name in _candidates:
                    pn_df = assumptions.loc[assumptions["name"] == pn_name, "value"]
                    rv_df = assumptions.loc[assumptions["name"] == rv_name, "value"]
                    if not pn_df.empty and not rv_df.empty:
                        profile_names = pn_df.iloc[0]
                        rate_values = rv_df.iloc[0]
                        print(f"   ✅ Interest rate profiles found via: {pn_name} + {rv_name}")
                        break

                # If exact match failed, try fuzzy search across all assumption names
                if profile_names is None:
                    all_names = assumptions["name"].tolist()
                    fuzzy_pn = None
                    fuzzy_rv = None
                    for n in all_names:
                        nl = str(n).lower()
                        if ("saibor" in nl or "interest" in nl) and "profile" in nl:
                            fuzzy_pn = n
                        elif ("saibor" in nl or "interest" in nl) and ("value" in nl or "rate" in nl) and "profile" not in nl:
                            fuzzy_rv = n
                    if fuzzy_pn and fuzzy_rv:
                        profile_names = assumptions.loc[assumptions["name"] == fuzzy_pn, "value"].iloc[0]
                        rate_values = assumptions.loc[assumptions["name"] == fuzzy_rv, "value"].iloc[0]
                        print(f"   ✅ Interest rate profiles found via fuzzy: {fuzzy_pn} + {fuzzy_rv}")

                if profile_names is None or rate_values is None:
                    print(f"   ❌ SAIBOR rate profiles NOT FOUND in assumptions.")
                    print(f"      Expected named ranges: dd.assetco.saibor.profiles + a.assetco.saibor.values")
                    print(f"      (Legacy fallback: dd.assetco.interest.rate.profiles + dd.assetco.interest.rate.values)")
                    print(f"      Please create these named ranges in the Excel workbook pointing to the SAIBOR rate curve table.")
                    return profiles

                if not isinstance(profile_names, list):
                    profile_names = [profile_names]

                # Handle various data structures
                # rate_values could be:
                # a) list of lists: [[yr1_rate, yr2_rate, ...], [yr1_rate, yr2_rate, ...]]  (one sub-list per profile)
                # b) flat list: [rate1, rate2, ...]  (single profile or single rate per profile)
                # c) list of single values: [0.05, 0.06]
                for i, profile_name in enumerate(profile_names):
                    if profile_name is None or (isinstance(profile_name, float) and pd.isna(profile_name)):
                        continue
                    pname = str(profile_name).strip()
                    if not pname:
                        continue
                    profiles[pname] = {}

                    if isinstance(rate_values, list) and i < len(rate_values):
                        year_rates = rate_values[i]
                        if isinstance(year_rates, list):
                            for year_idx, rate in enumerate(year_rates):
                                year = year_idx + 1
                                if rate is not None and not (isinstance(rate, float) and pd.isna(rate)):
                                    try:
                                        profiles[pname][year] = float(rate)
                                    except (ValueError, TypeError):
                                        profiles[pname][year] = 0.0
                                else:
                                    profiles[pname][year] = 0.0
                        else:
                            # Single value per profile
                            if year_rates is not None and not (isinstance(year_rates, float) and pd.isna(year_rates)):
                                try:
                                    profiles[pname][1] = float(year_rates)
                                except (ValueError, TypeError):
                                    profiles[pname][1] = 0.0
                    elif not isinstance(rate_values, list):
                        # Single scalar for all profiles
                        try:
                            profiles[pname][1] = float(rate_values)
                        except (ValueError, TypeError):
                            profiles[pname][1] = 0.0

                return profiles
            except Exception as e:
                print(f"⚠️ Error loading interest rate profiles: {e}")
                import traceback
                traceback.print_exc()
                return profiles

        # Track warned profiles to avoid spam
        _warned_profiles = set()

        def fn_get_interest_rate_for_period(profile_name, period_date, loan_start_date, profiles):
            """
            Get annual interest rate for a given period from an interest rate profile.
            
            If profile_name is a scalar (float), returns that directly.
            If profile_name is a string referencing a profile, looks up the year-based rate.
            For years beyond the profile, uses the last available rate.
            """
            if profile_name is None:
                return 0.0
            try:
                scalar = float(profile_name)
                if not pd.isna(scalar):
                    return scalar
            except (ValueError, TypeError):
                pass
            
            # It's a profile name string — look up year-based rate
            pname = str(profile_name).strip()
            
            # Exact match first
            if pname in profiles:
                profile = profiles[pname]
            else:
                # Fuzzy match: case-insensitive, normalize spaces/underscores
                pname_norm = " ".join(pname.lower().replace("_", " ").split())
                matched_key = None
                for key in profiles:
                    key_norm = " ".join(str(key).strip().lower().replace("_", " ").split())
                    if key_norm == pname_norm:
                        matched_key = key
                        break
                if matched_key:
                    if pname not in _warned_profiles:
                        print(f"   ⚠️ Interest rate profile: fuzzy matched '{pname}' → '{matched_key}'")
                        _warned_profiles.add(pname)
                    profile = profiles[matched_key]
                else:
                    if pname not in _warned_profiles:
                        print(f"WARNING: Interest rate profile '{pname}' not found. Available: {list(profiles.keys())}. Returning 0%.")
                        _warned_profiles.add(pname)
                    return 0.0
            
            if not profile:
                return 0.0
            
            # Compute year number relative to loan start
            months_from_start = (period_date.year - loan_start_date.year) * 12 + (period_date.month - loan_start_date.month)
            year_num = max(1, (months_from_start // 12) + 1)
            
            if year_num in profile:
                return profile[year_num]
            
            # Beyond profile: use last defined year's rate
            max_year = max(profile.keys()) if profile else 0
            if max_year > 0:
                return profile[max_year]
            return 0.0


        # =============================================================================
        # COMPUTE TOTAL RENTS AND NOI
        # =============================================================================

        def fn_compute_total_base_rent():
            """Compute total base rent per period (sum of all tenants) - computed/accrued.
            
            T1 + T2 only (renewal excluded) to match CFS revenue logic.
            """
            if all_tenant_results is None:
                return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            escalated_rent_tenant1 = all_tenant_results.get("tenant1", {}).get("escalated_rent")
            # Renewal excluded — not included in CFS revenue
            escalated_rent_tenant2 = all_tenant_results.get("tenant2", {}).get("escalated_rent")
            
            total = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            if escalated_rent_tenant1 is not None:
                total = total + escalated_rent_tenant1.sum(axis=0)
            if escalated_rent_tenant2 is not None:
                total = total + escalated_rent_tenant2.sum(axis=0)
            
            return total


        def fn_compute_total_base_rent_collections():
            """Compute total base rent collections per period (sum of all tenants) - cash basis.
            
            T1 + T2 only (renewal excluded) to match CFS revenue logic.
            """
            if all_tenant_results is None:
                return pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            collectible_rent_tenant1 = all_tenant_results.get("tenant1", {}).get("collectible_rent")
            # Renewal excluded — not included in CFS revenue
            collectible_rent_tenant2 = all_tenant_results.get("tenant2", {}).get("collectible_rent")
            
            total = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            if collectible_rent_tenant1 is not None:
                total = total + collectible_rent_tenant1.sum(axis=0)
            if collectible_rent_tenant2 is not None:
                total = total + collectible_rent_tenant2.sum(axis=0)
            
            return total


        def fn_compute_total_gross_rent(total_base_rent, tor_results):
            """Compute total gross rent = base rent + TOR.
            
            T1 TOR + T2 TOR only (renewal TOR excluded) to match CFS.
            """
            tor_data, _ = tor_results
            
            # Handle case where tor_data may be dict with different structure
            if "tenant1_and_renewal" in tor_data:
                # Use turnover_rent_t1 (T1 only, renewal excluded)
                tor_t1 = tor_data["tenant1_and_renewal"].get("turnover_rent_t1")
                tor_t2 = tor_data["tenant2"].get("turnover_rent")
            else:
                # Fallback for empty/different structure
                return total_base_rent
            
            total_tor = pd.Series(np.zeros(len(total_base_rent)), index=total_base_rent.index)
            if tor_t1 is not None:
                total_tor = total_tor + tor_t1.sum(axis=0)
            if tor_t2 is not None:
                total_tor = total_tor + tor_t2.sum(axis=0)
            
            return total_base_rent + total_tor


        def fn_compute_noi(total_gross_rent, tenant_other_results, opex_results):
            """
            Compute NOI for % of NOI calculations.
            
            NOI = Gross Rent - Leasing Commission + Service Charge - All OPEX
            
            Args:
                total_gross_rent: Series of gross rent per period
                tenant_other_results: Results from AM_Co_05 module
                opex_results: Results from AM_Co_06 module
            
            Returns: Series of NOI per period
            """
            # Total leasing commission
            total_lc = (
                tenant_other_results["tenant1"]["leasing_commission"].sum(axis=0) +
                tenant_other_results["renewal"]["leasing_commission"].sum(axis=0) +
                tenant_other_results["tenant2"]["leasing_commission"].sum(axis=0)
            )
            
            # Total service charge (this is income)
            total_sc = (
                tenant_other_results["tenant1"]["service_charge"].sum(axis=0) +
                tenant_other_results["renewal"]["service_charge"].sum(axis=0) +
                tenant_other_results["tenant2"]["service_charge"].sum(axis=0)
            )
            
            # Total OPEX
            total_opex = sum(opex_results[opex_type] for opex_type in opex_results.keys())
            
            # NOI = Gross Rent - Leasing Commission + Service Charge - OPEX
            noi = total_gross_rent - total_lc + total_sc - total_opex
            
            return noi


        # =============================================================================
        # HELPER FUNCTION FOR SAFE FLOAT CONVERSION
        # =============================================================================

        def _safe_float(val, default=0):
            """Safely convert a value to float, returning default for None, NaN, or empty strings."""
            if val is None or pd.isna(val):
                return default
            if isinstance(val, str) and val.strip() == '':
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default


        # =============================================================================
        # PARKING INCOME COMPUTATION
        # =============================================================================

        def fn_compute_parking_revenue():
            """
            Compute parking revenue.
            
            Input Mode (revenue_type):
            - "Actuals": Read from schedule named range (s.assetco.parking.revenue)
            - "Forecast": Compute using formula: No of Bays × Parking Occupancy × Parking Rate (escalated)
            - "Actuals + Forecast": Use actuals for past periods, forecast for future
            
            Rate is monthly (already monthly input).
            Year 1 = calendar year of parking start_date (or operations_start).
            """
            # print("   Computing parking revenue...")
            
            result = np.zeros(_num_periods)
            
            # Get parking inputs
            parking = Global.ParkingIncomeandExpenses
            
            # Get input type (Actuals, Forecast, Actuals + Forecast)
            revenue_type = parking.revenue_type
            input_type_lower = str(revenue_type).lower().strip() if revenue_type and not pd.isna(revenue_type) else "forecast"
            
            no_of_bays = parking.no_of_bays
            rate_per_month = parking.rate_per_month
            start_date_raw = parking.start_date
            occupancy_profile = parking.occupancy_profile
            rate_escalation_profile = parking.parking_rate_escalation
            
            # Convert datetime to number if needed (Excel serial number issue)
            if isinstance(no_of_bays, (pd.Timestamp, datetime)):
                no_of_bays = (pd.Timestamp(no_of_bays) - pd.Timestamp('1899-12-30')).days
            if isinstance(rate_per_month, (pd.Timestamp, datetime)):
                rate_per_month = (pd.Timestamp(rate_per_month) - pd.Timestamp('1899-12-30')).days
            
            # Get actuals if input mode includes actuals
            actuals_values = None
            actuals_available = False
            
            if "actuals" in input_type_lower:
                # import AM_Co_02_input_assignment_module as mod02
                try:
                    actuals_result = assumptions.loc[
                        assumptions["name"] == "s.assetco.parking.revenue", "value"
                    ]
                    if not actuals_result.empty:
                        actuals_values = actuals_result.iloc[0]
                        if actuals_values is not None and len(actuals_values) > 0:
                            actuals_available = True
                            # print(f"      Found parking revenue actuals schedule")
                except Exception as e:
                    print(f"      ⚠️ Could not load parking actuals: {e}")
            
            # Parse start date and compute effective start for all modes
            start_date = None
            if start_date_raw and not pd.isna(start_date_raw):
                start_date = pd.to_datetime(start_date_raw)
            else:
                start_date = fn_get_operations_start()
            
            acquisition_date = fn_get_acquisition_date()
            asset_sale_date = fn_get_asset_sale_date()
            
            # effective_start = max(start_date, acquisition_date)
            effective_start = start_date
            if start_date is not None and acquisition_date is not None:
                effective_start = max(start_date, acquisition_date)
            elif acquisition_date is not None:
                effective_start = acquisition_date
            
            # Handle pure Actuals mode
            if input_type_lower == "actuals" and actuals_available:
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    if col_idx < len(actuals_values):
                        val = actuals_values[col_idx]
                        result[col_idx] = _safe_float(val)
                return pd.Series(result, index=range(_num_periods))
            
            # For Forecast or Actuals + Forecast, compute forecast values
            forecast_values = np.zeros(_num_periods)
            
            # Validate inputs for forecast computation
            can_compute_forecast = True
            
            if not no_of_bays or pd.isna(no_of_bays) or str(no_of_bays).strip() == '':
                can_compute_forecast = False
            else:
                no_of_bays = _safe_float(no_of_bays)
                if no_of_bays <= 0:
                    can_compute_forecast = False
            
            if can_compute_forecast and (not rate_per_month or pd.isna(rate_per_month) or str(rate_per_month).strip() == ''):
                can_compute_forecast = False
            elif can_compute_forecast:
                rate_per_month = _safe_float(rate_per_month)
                if rate_per_month <= 0:
                    can_compute_forecast = False
            
            if start_date is None and can_compute_forecast:
                can_compute_forecast = False
            
            # Compute forecast if possible
            if can_compute_forecast:
                # Get profiles
                parking_profiles = fn_get_parking_escalation_profiles()
                
                # Rate is per month (already monthly input)
                base_rate_monthly = _safe_float(rate_per_month)
                
                # Compute for each period
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    period_end = _period_ends_ts[col_idx]
                    
                    # Skip periods before effective start
                    if effective_start is not None and period_start < effective_start:
                        continue
                    
                    # Skip periods after asset sale date
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    
                    # Get year number (based on original start_date for escalation)
                    year_num = fn_get_year_for_period(period_start, start_date)
                    if year_num is None:
                        continue
                    
                    # Get occupancy for this year - if None, parking stops
                    occupancy = None
                    if occupancy_profile and not pd.isna(occupancy_profile):
                        occ_val = fn_get_profile_value(occupancy_profile, year_num, parking_profiles["occupancy"])
                        if occ_val is not None and occ_val > 0:
                            occupancy = occ_val if occ_val <= 1 else occ_val / 100  # Convert % to decimal if needed
                    
                    # If no occupancy value for this year, skip (parking has ended)
                    if occupancy is None:
                        continue
                    
                    # Escalate rate - Year 1 gets Year 1 escalation, Year 2 gets Year 1 + Year 2 escalation, etc.
                    escalated_rate = base_rate_monthly
                    if rate_escalation_profile and not pd.isna(rate_escalation_profile):
                        for yr in range(1, year_num + 1):  # Include current year's escalation
                            yr_rate = fn_get_escalation_rate(rate_escalation_profile, yr, parking_profiles["rate"])
                            escalated_rate = escalated_rate * (1 + yr_rate)
                    
                    # Revenue = Bays × Occupancy × Rate
                    forecast_values[col_idx] = _safe_float(no_of_bays) * occupancy * escalated_rate
            
            # Combine actuals and forecast based on input mode
            if "actuals" in input_type_lower and "forecast" in input_type_lower:
                # Actuals + Forecast mode: Use actuals where available (non-zero), forecast elsewhere
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    if actuals_available and col_idx < len(actuals_values):
                        val = actuals_values[col_idx]
                        val_float = _safe_float(val)
                        if val_float != 0:
                            result[col_idx] = val_float
                        else:
                            result[col_idx] = forecast_values[col_idx]
                    else:
                        result[col_idx] = forecast_values[col_idx]
            else:
                # Pure Forecast mode
                result = forecast_values
            
            return pd.Series(result, index=range(_num_periods))


        def fn_compute_parking_opex():
            """
            Compute parking operating expenses.
            
            The input mode (Actuals / Forecast / Actuals + Forecast) is determined
            by revenue_type (shared single dropdown for both parking revenue and opex).
            parking_opex_type only determines Fixed vs Variable for forecast computation.
            
            - revenue_type = "Actuals"           → read from s.assetco.parking.opex
            - revenue_type = "Forecast"           → use Fixed or Variable formula
            - revenue_type = "Actuals + Forecast"  → actuals where non-zero, forecast elsewhere
            """
            result = np.zeros(_num_periods)
            
            # Get parking inputs
            parking = Global.ParkingIncomeandExpenses
            
            # Input mode comes from revenue_type (shared with parking revenue)
            revenue_type = parking.revenue_type
            input_type_lower = str(revenue_type).lower().strip() if revenue_type and not pd.isna(revenue_type) else "forecast"
            
            opex_type = parking.parking_opex_type
            fixed_opex = parking.fixed_parking_opex
            opex_profile = parking.parking_opex_annual_profile
            no_of_bays = parking.no_of_bays
            start_date_raw = parking.start_date
            occupancy_profile = parking.occupancy_profile
            
            # Convert datetime to number if needed (Excel serial number issue)
            if isinstance(fixed_opex, (pd.Timestamp, datetime)):
                fixed_opex = (pd.Timestamp(fixed_opex) - pd.Timestamp('1899-12-30')).days
            if isinstance(no_of_bays, (pd.Timestamp, datetime)):
                no_of_bays = (pd.Timestamp(no_of_bays) - pd.Timestamp('1899-12-30')).days
            
            # Determine mode flags from revenue_type
            use_actuals = "actuals" in input_type_lower or "actual" in input_type_lower
            use_forecast = "forecast" in input_type_lower
            is_pure_actuals = use_actuals and not use_forecast
            
            # Determine Fixed vs Variable from parking_opex_type
            opex_type_str = ""
            if opex_type and not pd.isna(opex_type):
                opex_type_str = str(opex_type).strip().lower()
            is_fixed = "fixed" in opex_type_str
            is_variable = "variable" in opex_type_str
            
            # ---- Load actuals if needed ----
            actuals_values = None
            actuals_available = False
            
            if use_actuals:
                try:
                    actuals_result = assumptions.loc[
                        assumptions["name"] == "s.assetco.parking.opex", "value"
                    ]
                    if not actuals_result.empty:
                        raw = actuals_result.iloc[0]
                        if isinstance(raw, list):
                            if len(raw) > 0 and isinstance(raw[0], list):
                                actuals_values = raw[0]
                            else:
                                actuals_values = raw
                        elif isinstance(raw, (pd.Series, np.ndarray)):
                            actuals_values = list(raw) if isinstance(raw, np.ndarray) else raw.values.tolist()
                        else:
                            actuals_values = raw
                        if actuals_values is not None and len(actuals_values) > 0:
                            actuals_available = True
                except Exception:
                    pass
            
            # ---- Parse start date and compute effective_start = max(start_date, acquisition_date) ----
            start_date = None
            if start_date_raw and not pd.isna(start_date_raw):
                start_date = pd.to_datetime(start_date_raw)
            else:
                start_date = fn_get_operations_start()
            
            acquisition_date = fn_get_acquisition_date()
            asset_sale_date = fn_get_asset_sale_date()
            
            effective_start = start_date
            if start_date is not None and acquisition_date is not None:
                effective_start = max(start_date, acquisition_date)
            elif acquisition_date is not None:
                effective_start = acquisition_date
            
            # ---- Pure Actuals mode ----
            if is_pure_actuals and actuals_available:
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    if col_idx < len(actuals_values):
                        result[col_idx] = _safe_float(actuals_values[col_idx])
                return pd.Series(result, index=range(_num_periods))
            
            # ---- Compute forecast values (Fixed or Variable) ----
            parking_profiles = fn_get_parking_escalation_profiles()
            fixed_opex_val = _safe_float(fixed_opex)
            
            forecast_values = np.zeros(_num_periods)
            
            if (is_fixed or (not is_variable and fixed_opex_val > 0)) and fixed_opex_val > 0 and effective_start:
                monthly_opex = fixed_opex_val / 12
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    forecast_values[col_idx] = monthly_opex
                    
            elif is_variable and opex_profile and not pd.isna(opex_profile) and effective_start:
                parking_revenue = fn_compute_parking_revenue()
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    year_num = fn_get_year_for_period(period_start, start_date)
                    if year_num is None:
                        continue
                    opex_pct = fn_get_profile_value(opex_profile, year_num, parking_profiles["opex"])
                    if opex_pct and opex_pct > 0:
                        pct = opex_pct if opex_pct <= 1 else opex_pct / 100
                        forecast_values[col_idx] = parking_revenue.iloc[col_idx] * pct
            
            # ---- Combine actuals + forecast ----
            if use_actuals and use_forecast:
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    has_actual = False
                    if actuals_available and col_idx < len(actuals_values):
                        val_float = _safe_float(actuals_values[col_idx])
                        if val_float != 0:
                            result[col_idx] = val_float
                            has_actual = True
                    if not has_actual:
                        result[col_idx] = forecast_values[col_idx]
            elif not use_actuals:
                result = forecast_values
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # OTHER INCOME/EXPENSE COMPUTATION
        # =============================================================================

        OTHER_INCOME_ITEMS = [
            "other_income_1",
            "other_income_2",
            "other_income_3",
        ]

        OTHER_EXPENSE_ITEMS = [
            "other_expense_1",
            "other_expense_2",
            "other_expense_3",
        ]


        def fn_get_other_ie_inputs(item_name):
            """
            Get inputs for an other income/expense item.
            
            Args:
                item_name: e.g., "other_income_1", "other_expense_2"
            
            Returns: Dictionary with input values
            """
            ie = Global.OtherIncomeandExpenses
            
            inputs = {}
            
            # print(f"   🔍 DEBUG fn_get_other_ie_inputs({item_name}):")
            
            try:
                inputs["input_type"] = getattr(ie, f"{item_name}_input_type", None)
                
                # Get raw values and convert to float
                pct_raw = getattr(ie, f"{item_name}_percentage_of_revenue_or_noi", None)
                if pct_raw is not None and not pd.isna(pct_raw):
                    try:
                        inputs["percentage_of_revenue_or_noi"] = float(pct_raw)
                    except (ValueError, TypeError):
                        inputs["percentage_of_revenue_or_noi"] = 0.0
                else:
                    inputs["percentage_of_revenue_or_noi"] = 0.0
                
                per_gla_raw = getattr(ie, f"{item_name}_incomeexpense_per_glagfa", None)
                if per_gla_raw is not None and not pd.isna(per_gla_raw):
                    try:
                        inputs["per_gla_gfa"] = float(per_gla_raw)
                    except (ValueError, TypeError):
                        inputs["per_gla_gfa"] = 0.0
                else:
                    inputs["per_gla_gfa"] = 0.0
                
                ad_hoc_raw = getattr(ie, f"{item_name}_ad_hoc_amount", None)
                if ad_hoc_raw is not None and not pd.isna(ad_hoc_raw):
                    try:
                        inputs["ad_hoc_amount"] = float(ad_hoc_raw)
                    except (ValueError, TypeError):
                        inputs["ad_hoc_amount"] = 0.0
                else:
                    inputs["ad_hoc_amount"] = 0.0
                
                inputs["start_date"] = getattr(ie, f"{item_name}_start_date", None)
                inputs["escalation_profile"] = getattr(ie, f"{item_name}_escalation_profile", None)
                inputs["income_expense_flag"] = getattr(ie, f"{item_name}_incomeexpense", None)
                
                # print(f"      input_type = {inputs.get('input_type')}")
                # print(f"      income_expense_flag = {inputs.get('income_expense_flag')}")
                # print(f"      percentage = {inputs.get('percentage_of_revenue_or_noi')}")
                # print(f"      per_gla_gfa = {inputs.get('per_gla_gfa')}")
                # print(f"      ad_hoc_amount = {inputs.get('ad_hoc_amount')}")
                # print(f"      start_date = {inputs.get('start_date')}")
                
            except Exception as e:
                print(f"⚠️ Error getting inputs for {item_name}: {e}")
            
            return inputs


        def fn_compute_other_income_expense(item_name, profiles, total_base_rent_collections, total_gross_rent, noi):
            """
            Compute a single other income/expense item.
            
            Input Mode:
            - "Actuals": Read from schedule named range (s.assetco.other.income.1, etc.)
            - "Forecast": Compute using formula below
            - "Actuals + Forecast": Use actuals for past periods, forecast for future
            
            Calculation Types (for Forecast):
            - % of Base Rent: percentage × base_rent_collections (no escalation)
            - % of Gross Rent: percentage × gross_rent (no escalation)
            - % of NOI: percentage × NOI (no escalation)
            - SAR per GLA: rate × GLA (with escalation) - rate is MONTHLY
            - SAR per GFA: rate × GFA (with escalation) - rate is MONTHLY
            - Ad Hoc Amount: fixed MONTHLY amount (with escalation)
            
            Year 1 = calendar year of start_date (or operations_start).
            """
            result = np.zeros(_num_periods)
            
            inputs = fn_get_other_ie_inputs(item_name)
            
            if not inputs:
                return pd.Series(result, index=range(_num_periods))
            
            # input_type determines mode: "Actuals", "Forecast", "Actuals + Forecast"
            input_type = inputs.get("input_type")
            calc_type = inputs.get("income_expense_flag")
            
            if not input_type or pd.isna(input_type):
                return pd.Series(result, index=range(_num_periods))
            
            input_type_lower = str(input_type).lower().strip()
            
            # Parse start date
            start_date_raw = inputs.get("start_date")
            start_date = None
            if start_date_raw and not pd.isna(start_date_raw):
                start_date = pd.to_datetime(start_date_raw)
            else:
                start_date = fn_get_operations_start()
            
            if start_date is None:
                return pd.Series(result, index=range(_num_periods))
            
            asset_sale_date = fn_get_asset_sale_date()
            escalation_profile = inputs.get("escalation_profile")
            
            # Determine named range for actuals
            # Map item_name to named range (e.g., other_income_1 -> s.assetco.other.income.1)
            named_range_map = {
                "other_income_1": "s.assetco.other.income.1",
                "other_income_2": "s.assetco.other.income.2",
                "other_income_3": "s.assetco.other.income.3",
                "other_expense_1": "s.assetco.other.expense.1",
                "other_expense_2": "s.assetco.other.expense.2",
                "other_expense_3": "s.assetco.other.expense.3",
            }
            
            actuals_values = None
            actuals_available = False
            
            # Get actuals if input mode includes actuals
            if "actuals" in input_type_lower:
                named_range = named_range_map.get(item_name)
                # print(f"   🔍 Other I/E {item_name}: looking for actuals in named_range={named_range}")
                if named_range:
                    # import AM_Co_02_input_assignment_module as mod02
                    try:
                        actuals_result = assumptions.loc[
                            assumptions["name"] == named_range, "value"
                        ]
                        if not actuals_result.empty:
                            raw_actuals = actuals_result.iloc[0]
                            # print(f"   🔍 Other I/E {item_name}: raw_actuals type={type(raw_actuals)}")
                            
                            # Convert to list for consistent integer indexing
                            if isinstance(raw_actuals, pd.Series):
                                actuals_values = raw_actuals.values.tolist()
                            elif isinstance(raw_actuals, np.ndarray):
                                actuals_values = raw_actuals.tolist()
                            elif isinstance(raw_actuals, list):
                                # Handle nested list
                                if len(raw_actuals) > 0 and isinstance(raw_actuals[0], list):
                                    actuals_values = raw_actuals[0]
                                else:
                                    actuals_values = raw_actuals
                            else:
                                actuals_values = raw_actuals
                            
                            if actuals_values is not None and len(actuals_values) > 0:
                                actuals_available = True
                                # print(f"   🔍 Other I/E {item_name}: actuals loaded, len={len(actuals_values)}, first 5={actuals_values[:5] if len(actuals_values) >= 5 else actuals_values}")
                    except Exception as e:
                        print(f"   ⚠️ Other I/E {item_name}: error loading actuals: {e}")
                        pass
            
            # Compute effective_start = max(start_date, acquisition_date)
            acquisition_date = fn_get_acquisition_date()
            effective_start = start_date
            if start_date is not None and acquisition_date is not None:
                effective_start = max(start_date, acquisition_date)
            elif acquisition_date is not None:
                effective_start = acquisition_date
            
            # Handle different input modes
            if input_type_lower == "actuals" and actuals_available:
                # Pure Actuals - use schedule values only from effective_start
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    if effective_start is not None and period_start < effective_start:
                        continue
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    if col_idx < len(actuals_values):
                        val = actuals_values[col_idx]
                        result[col_idx] = _safe_float(val)
                return pd.Series(result, index=range(_num_periods))
            
            # For "Forecast" or "Actuals + Forecast", we need calc_type
            if not calc_type or pd.isna(calc_type):
                # If no calc_type but actuals available, use actuals from effective_start
                if actuals_available:
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        if col_idx < len(actuals_values):
                            val = actuals_values[col_idx]
                            result[col_idx] = _safe_float(val)
                return pd.Series(result, index=range(_num_periods))
            
            calc_type_lower = str(calc_type).lower().strip()
            
            # Compute forecast values
            forecast_values = np.zeros(_num_periods)
            
            if "% of base" in calc_type_lower or ("percent" in calc_type_lower and "base" in calc_type_lower):
                # % of Base Rent
                pct = _safe_float(inputs.get("percentage_of_revenue_or_noi"))
                if pct > 0:
                    pct_decimal = pct if pct <= 1 else pct / 100
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        forecast_values[col_idx] = total_base_rent_collections.iloc[col_idx] * pct_decimal
                        
            elif "% of gross" in calc_type_lower or ("percent" in calc_type_lower and "gross" in calc_type_lower):
                # % of Gross Rent
                pct = _safe_float(inputs.get("percentage_of_revenue_or_noi"))
                if pct > 0:
                    pct_decimal = pct if pct <= 1 else pct / 100
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        forecast_values[col_idx] = total_gross_rent.iloc[col_idx] * pct_decimal
                        
            elif "% of noi" in calc_type_lower or ("percent" in calc_type_lower and "noi" in calc_type_lower):
                # % of NOI
                pct = _safe_float(inputs.get("percentage_of_revenue_or_noi"))
                if pct > 0:
                    pct_decimal = pct if pct <= 1 else pct / 100
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        noi_val = noi.iloc[col_idx] if col_idx < len(noi) else 0
                        forecast_values[col_idx] = noi_val * pct_decimal
                        
            elif "sar per gla" in calc_type_lower or "per gla" in calc_type_lower:
                # SAR per GLA (with escalation) - input is MONTHLY rate per sqm
                rate_per_sqm_monthly = _safe_float(inputs.get("per_gla_gfa"))
                gla = fn_get_total_gla()
                
                if rate_per_sqm_monthly > 0 and gla > 0:
                    base_monthly = rate_per_sqm_monthly * gla  # Already monthly, no divide by 12
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        year_num = fn_get_year_for_period(period_start, start_date)
                        if year_num is None:
                            continue
                        
                        # Apply escalation from year 1
                        escalated_amount = base_monthly
                        if escalation_profile and not pd.isna(escalation_profile):
                            for yr in range(1, year_num + 1):
                                yr_rate = fn_get_escalation_rate(escalation_profile, yr, profiles)
                                escalated_amount = escalated_amount * (1 + yr_rate)
                        
                        forecast_values[col_idx] = escalated_amount
                        
            elif "sar per gfa" in calc_type_lower or "per gfa" in calc_type_lower:
                # SAR per GFA (with escalation) - input is MONTHLY rate per sqm
                rate_per_sqm_monthly = _safe_float(inputs.get("per_gla_gfa"))
                gfa = fn_get_total_gfa()
                
                if rate_per_sqm_monthly > 0 and gfa > 0:
                    base_monthly = rate_per_sqm_monthly * gfa  # Already monthly, no divide by 12
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        year_num = fn_get_year_for_period(period_start, start_date)
                        if year_num is None:
                            continue
                        
                        # Apply escalation from year 1
                        escalated_amount = base_monthly
                        if escalation_profile and not pd.isna(escalation_profile):
                            for yr in range(1, year_num + 1):
                                yr_rate = fn_get_escalation_rate(escalation_profile, yr, profiles)
                                escalated_amount = escalated_amount * (1 + yr_rate)
                        
                        forecast_values[col_idx] = escalated_amount
                        
            elif "ad hoc" in calc_type_lower or "adhoc" in calc_type_lower:
                # Ad Hoc Amount (with escalation) - input is MONTHLY amount
                amount_monthly = _safe_float(inputs.get("ad_hoc_amount"))
                
                if amount_monthly > 0:
                    base_monthly = amount_monthly  # Already monthly, no divide by 12
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        if effective_start is not None and period_start < effective_start:
                            continue
                        if asset_sale_date and period_start > asset_sale_date:
                            continue
                        
                        year_num = fn_get_year_for_period(period_start, start_date)
                        if year_num is None:
                            continue
                        
                        # Apply escalation from year 1
                        escalated_amount = base_monthly
                        if escalation_profile and not pd.isna(escalation_profile):
                            for yr in range(1, year_num + 1):
                                yr_rate = fn_get_escalation_rate(escalation_profile, yr, profiles)
                                escalated_amount = escalated_amount * (1 + yr_rate)
                        
                        forecast_values[col_idx] = escalated_amount
            
            # Combine actuals and forecast based on input mode
            if "actuals" in input_type_lower and "forecast" in input_type_lower:
                # Actuals + Forecast mode
                # Use actuals where they EXIST (non-zero/non-blank), forecast elsewhere
                actuals_used = 0
                forecast_used = 0
                
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    
                    # Skip if before effective_start
                    if effective_start is not None and period_start < effective_start:
                        continue
                    
                    # Skip if after asset sale
                    if asset_sale_date and period_start > asset_sale_date:
                        continue
                    
                    # Check if actual value exists and is non-zero
                    has_actual = False
                    if actuals_available and col_idx < len(actuals_values):
                        val = actuals_values[col_idx]
                        val_float = _safe_float(val)
                        if val_float != 0:
                            result[col_idx] = val_float
                            actuals_used += 1
                            has_actual = True
                            # if col_idx < 3:
                            #     print(f"   🔍 Other I/E {item_name} Period {col_idx}: ACTUAL val={val_float}")
                    
                    if not has_actual:
                        # No actual available - use forecast
                        result[col_idx] = forecast_values[col_idx]
                        if forecast_values[col_idx] != 0:
                            forecast_used += 1
                        # if col_idx < 3:
                            # print(f"   🔍 Other I/E {item_name} Period {col_idx}: FORECAST val={forecast_values[col_idx]}")
                
                # print(f"   🔍 Other I/E {item_name} RESULT: actuals_used={actuals_used}, forecast_used={forecast_used}, total={np.sum(result)}")
            elif "actuals" in input_type_lower:
                # Pure Actuals mode
                if actuals_available:
                    for col_idx in range(_num_periods):
                        if col_idx < len(actuals_values):
                            val = actuals_values[col_idx]
                            result[col_idx] = _safe_float(val)
                # print(f"   🔍 Other I/E {item_name} RESULT (Actuals only): total={np.sum(result)}")
            else:
                # Pure Forecast mode
                result = forecast_values
                # print(f"   🔍 Other I/E {item_name} RESULT (Forecast only): total={np.sum(result)}")
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # MAIN COMPUTATION FUNCTION
        # =============================================================================

        def fn_compute_all_other_income_expenses():
            """
            Compute all other income and expenses including parking.
            
            Returns: Dictionary with all results
            """
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts
            # global assumptions, model_timeline_me, template_asset_timeline
            cache_key = "module:other_income_expenses"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # print("Computing Other Income and Expenses...")
            
            # Initialize globals if needed (when called directly, not via fn_run_module_07)
            if _num_periods is None:
                # print("   Initializing module globals...")
                # import AM_Co_02_input_assignment_module as mod02
                # from AM_Co_02_input_assignment_module import fn_run_module_02
                
                # if mod02.model_timeline_me is None:
                #     print("   📂 Running Module 02 to load inputs...")
                #     fn_run_module_02()
                
                # Get updated values
                # assumptions = mod02.assumptions
                # model_timeline_me = mod02.model_timeline_me
                # template_asset_timeline = mod02.template_asset_timeline
                
                # Initialize module variables
                # _num_assets = len(Unit.UnitInputs.unit_id)
                # _num_periods = len(model_timeline_me)
                # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
                # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
                
                # print(f"   Assets: {_num_assets}, Periods: {_num_periods}")
                
                # Initialize Module 03 if needed
                # import AM_Co_03_base_rent_module as mod03
                if all_tenant_results is None:
                    # print("   📂 Running Module 03 to compute base rent...")
                    fn_run_module_03()
                
                # Initialize Module 04 if needed (for TOR)
                # import AM_Co_04_turnover_rent_module as mod04
                if _num_assets is None:
                    # print("   📂 Running Module 04 to compute turnover rent...")
                    fn_run_module_04(mod02.assumptions, mod02.model_timeline_me)
            
            # Get TOR results from Module 04 (already computed in fn_run_module_07)
            # print("   Getting TOR results...")
            # import AM_Co_04_turnover_rent_module as mod04
            
            # Module 04 stores results in all_turnover_results after fn_run_module_04
            if all_turnover_results is not None:
                tor_data = all_turnover_results
                # Get applicability from module
                tor_applicability = {"tenant1_renewal_applicable": [], "tenant2_applicable": [], "renewal_flags": []}
                tor_results = (tor_data, tor_applicability)
            else:
                # Fallback: compute if not already done
                tor_results = fn_compute_all_turnover_rent()
            
            # print("   Getting tenant other inputs results (SC, LC)...")
            tenant_other_results, _ = fn_compute_all_tenant_other_inputs()
            
            # print("   Getting OPEX results...")
            opex_results = fn_compute_all_operating_expenses()
            
            # Compute totals
            # print("   Computing total rents...")
            total_base_rent = fn_compute_total_base_rent()  # Computed/accrued basis
            total_base_rent_collections = fn_compute_total_base_rent_collections()  # Cash basis (for % of Base Rent)
            total_gross_rent = fn_compute_total_gross_rent(total_base_rent, tor_results)
            
            # print("   Computing NOI for % of NOI calculations...")
            noi = fn_compute_noi(total_gross_rent, tenant_other_results, opex_results)
            
            # Get escalation profiles
            # print("   Loading escalation profiles...")
            ie_profiles = fn_get_other_income_expense_escalation_profiles()
            # print(f"      Found {len(ie_profiles)} other I/E profiles: {list(ie_profiles.keys())[:5]}...")
            
            results = {
                "parking": {
                    "revenue": None,
                    "opex": None,
                },
                "other_income": {
                    "other_income_1": None,
                    "other_income_2": None,
                    "other_income_3": None,
                },
                "other_expenses": {
                    "other_expense_1": None,
                    "other_expense_2": None,
                    "other_expense_3": None,
                },
            }
            
            # Compute parking
            # print("   Computing parking income and expenses...")
            results["parking"]["revenue"] = fn_compute_parking_revenue()
            results["parking"]["opex"] = fn_compute_parking_opex()
            
            # Compute other income
            # print("   Computing other income items...")
            for item_name in OTHER_INCOME_ITEMS:
                # print(f"      Processing {item_name}...")
                results["other_income"][item_name] = fn_compute_other_income_expense(
                    item_name, ie_profiles, total_base_rent_collections, total_gross_rent, noi
                )
            
            # Compute other expenses
            # print("   Computing other expense items...")
            for item_name in OTHER_EXPENSE_ITEMS:
                # print(f"      Processing {item_name}...")
                results["other_expenses"][item_name] = fn_compute_other_income_expense(
                    item_name, ie_profiles, total_base_rent_collections, total_gross_rent, noi
                )
            
            # print("✅ Other Income and Expenses computation complete.")
            
            return _cache_set(cache_key, (
                results,
                {
                    "total_base_rent": total_base_rent,
                    "total_base_rent_collections": total_base_rent_collections,
                    "total_gross_rent": total_gross_rent,
                    "noi": noi,
                },
            ))


        # =============================================================================
        # CREATE OUTPUT DATAFRAMES
        # =============================================================================

        def fn_create_output_dataframes(results):
            """
            Create single-line output DataFrames for CFS/Output module.
            
            Creates monthly and annual DataFrames for:
            - Parking revenue and OPEX
            - Other income items (1, 2, 3)
            - Other expense items (1, 2, 3)
            - Totals
            """
            global parking_revenue_monthly, parking_revenue_annual
            global parking_opex_monthly, parking_opex_annual
            global other_income_1_monthly, other_income_1_annual
            global other_income_2_monthly, other_income_2_annual
            global other_income_3_monthly, other_income_3_annual
            global total_other_income_monthly, total_other_income_annual
            global other_expense_1_monthly, other_expense_1_annual
            global other_expense_2_monthly, other_expense_2_annual
            global other_expense_3_monthly, other_expense_3_annual
            global total_other_expenses_monthly, total_other_expenses_annual
            
            # import AM_Co_02_input_assignment_module as mod02
            # model_timeline_me = mod02.model_timeline_me
            # model_timeline_ye = mod02.model_timeline_ye
            
            # Get period to year mapping
            period_years = model_timeline_me["Period Start"].apply(lambda x: x.year).values
            
            # Helper to create annual sum
            def create_annual_df(monthly_series):
                if monthly_series is None:
                    return pd.DataFrame([[0] * len(model_timeline_ye)], columns=model_timeline_ye.index)
                
                annual_values = []
                for year_idx, year_row in model_timeline_ye.iterrows():
                    year_start = year_row["Period Start"]
                    year_end = year_row["Period End"]
                    year_val = year_start.year
                    
                    # Sum monthly values for this year
                    mask = period_years == year_val
                    year_sum = monthly_series.iloc[mask].sum() if mask.any() else 0
                    annual_values.append(year_sum)
                
                return pd.DataFrame([annual_values], columns=model_timeline_ye.index)
            
            # Helper to create monthly DataFrame
            def create_monthly_df(series):
                if series is None:
                    return pd.DataFrame([[0] * _num_periods], columns=model_timeline_me.index)
                return pd.DataFrame([series.values], columns=model_timeline_me.index)
            
            # Parking
            parking_revenue_monthly = create_monthly_df(results["parking"]["revenue"])
            parking_revenue_annual = create_annual_df(results["parking"]["revenue"])
            parking_opex_monthly = create_monthly_df(results["parking"]["opex"])
            parking_opex_annual = create_annual_df(results["parking"]["opex"])
            
            # Other Income
            other_income_1_monthly = create_monthly_df(results["other_income"]["other_income_1"])
            other_income_1_annual = create_annual_df(results["other_income"]["other_income_1"])
            other_income_2_monthly = create_monthly_df(results["other_income"]["other_income_2"])
            other_income_2_annual = create_annual_df(results["other_income"]["other_income_2"])
            other_income_3_monthly = create_monthly_df(results["other_income"]["other_income_3"])
            other_income_3_annual = create_annual_df(results["other_income"]["other_income_3"])
            
            # Total other income
            total_oi = (
                (results["other_income"]["other_income_1"] if results["other_income"]["other_income_1"] is not None else pd.Series(np.zeros(_num_periods))) +
                (results["other_income"]["other_income_2"] if results["other_income"]["other_income_2"] is not None else pd.Series(np.zeros(_num_periods))) +
                (results["other_income"]["other_income_3"] if results["other_income"]["other_income_3"] is not None else pd.Series(np.zeros(_num_periods)))
            )
            total_other_income_monthly = create_monthly_df(total_oi)
            total_other_income_annual = create_annual_df(total_oi)
            
            # Other Expenses
            other_expense_1_monthly = create_monthly_df(results["other_expenses"]["other_expense_1"])
            other_expense_1_annual = create_annual_df(results["other_expenses"]["other_expense_1"])
            other_expense_2_monthly = create_monthly_df(results["other_expenses"]["other_expense_2"])
            other_expense_2_annual = create_annual_df(results["other_expenses"]["other_expense_2"])
            other_expense_3_monthly = create_monthly_df(results["other_expenses"]["other_expense_3"])
            other_expense_3_annual = create_annual_df(results["other_expenses"]["other_expense_3"])
            
            # Total other expenses
            total_oe = (
                (results["other_expenses"]["other_expense_1"] if results["other_expenses"]["other_expense_1"] is not None else pd.Series(np.zeros(_num_periods))) +
                (results["other_expenses"]["other_expense_2"] if results["other_expenses"]["other_expense_2"] is not None else pd.Series(np.zeros(_num_periods))) +
                (results["other_expenses"]["other_expense_3"] if results["other_expenses"]["other_expense_3"] is not None else pd.Series(np.zeros(_num_periods)))
            )
            total_other_expenses_monthly = create_monthly_df(total_oe)
            total_other_expenses_annual = create_annual_df(total_oe)
            
            # print("   Created output DataFrames:")
            # print(f"      parking_revenue_monthly: {parking_revenue_monthly.shape}")
            # print(f"      total_other_income_monthly: {total_other_income_monthly.shape}")
            # print(f"      total_other_expenses_monthly: {total_other_expenses_monthly.shape}")


        # =============================================================================
        # MODULE INITIALIZATION
        # =============================================================================

        def fn_run_module_07():
            """Initialize and run Module 07 - Other Income and Expenses."""
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts
            # global assumptions, model_timeline_me, template_asset_timeline
            
            # print("=" * 60)
            # print("MODULE 07: OTHER INCOME AND EXPENSES")
            # print("=" * 60)
            
            # Initialize dependencies
            # import AM_Co_02_input_assignment_module as mod02
            # from AM_Co_02_input_assignment_module import fn_run_module_02
            
            # if model_timeline_me is None:
            #     print("\n📂 Running Module 02 to load inputs...")
            #     fn_run_module_02()
            
            # Get updated values
            # assumptions = mod02.assumptions
            # model_timeline_me = mod02.model_timeline_me
            # template_asset_timeline = mod02.template_asset_timeline
            
            # Initialize Module 03 if needed
            # import AM_Co_03_base_rent_module as mod03
            if all_tenant_results is None:
                # print("\n📂 Running Module 03 to compute base rent...")
                fn_run_module_03()
            
            # Initialize Module 04 if needed (for TOR)
            # import AM_Co_04_turnover_rent_module as mod04
            if _num_assets is None:
                # print("\n📂 Running Module 04 to compute turnover rent...")
                fn_run_module_04(assumptions, model_timeline_me)
            
            # Initialize module variables
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = len(model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # print(f"   Assets: {_num_assets}, Periods: {_num_periods}")
            
            # Compute other income and expenses
            # print("\n💰 Computing other income and expenses...")
            results, totals = fn_compute_all_other_income_expenses()
            
            # Create output DataFrames
            # print("\n📋 Creating output DataFrames...")
            fn_create_output_dataframes(results)
            
            # Print summary
            summary = fn_generate_summary(results)
            # print(f"\n   Parking Revenue: {summary['Parking Revenue']:,.0f}")
            # print(f"   Parking OPEX: {summary['Parking OPEX']:,.0f}")
            # print(f"   Total Other Income: {summary['Total Other Income']:,.0f}")
            # print(f"   Total Other Expenses: {summary['Total Other Expenses']:,.0f}")
            
            # print("\n✅ Module 07 completed successfully!")
            return results, totals


        # =============================================================================
        # SUMMARY FUNCTION
        # =============================================================================

        def fn_generate_summary(results):
            """Generate summary of other income and expenses."""
            summary = {
                "Parking Revenue": results["parking"]["revenue"].sum() if results["parking"]["revenue"] is not None else 0,
                "Parking OPEX": results["parking"]["opex"].sum() if results["parking"]["opex"] is not None else 0,
            }
            
            total_other_income = 0
            for item_name in OTHER_INCOME_ITEMS:
                val = results["other_income"][item_name].sum() if results["other_income"][item_name] is not None else 0
                summary[item_name.replace("_", " ").title()] = val
                total_other_income += val
            
            total_other_expenses = 0
            for item_name in OTHER_EXPENSE_ITEMS:
                val = results["other_expenses"][item_name].sum() if results["other_expenses"][item_name] is not None else 0
                summary[item_name.replace("_", " ").title()] = val
                total_other_expenses += val
            
            summary["Total Other Income"] = total_other_income
            summary["Total Other Expenses"] = total_other_expenses
            summary["Net Parking"] = summary["Parking Revenue"] - summary["Parking OPEX"]
            summary["Net Other Income/Expenses"] = total_other_income - total_other_expenses
            
            return summary

        # =============================================================================
        # OUTPUT DATAFRAMES (Single-line items for CFS/Output)
        # =============================================================================

        # Maintenance CapEx
        maintenance_capex_1_monthly = None
        maintenance_capex_1_annual = None
        maintenance_capex_2_monthly = None
        maintenance_capex_2_annual = None
        maintenance_capex_3_monthly = None
        maintenance_capex_3_annual = None
        maintenance_capex_4_monthly = None
        maintenance_capex_4_annual = None
        total_maintenance_capex_monthly = None
        total_maintenance_capex_annual = None

        # Sinking Fund
        sinking_fund_monthly = None
        sinking_fund_annual = None

        # Grand Total (Maintenance CapEx + Sinking Fund)
        grand_total_monthly = None
        grand_total_annual = None


        # =============================================================================
        # HELPER FUNCTIONS
        # =============================================================================

        def fn_parse_date(date_val):
            """Parse date value to pandas Timestamp."""
            if date_val is None or pd.isna(date_val):
                return None
            try:
                return pd.to_datetime(date_val)
            except:
                return None


        def fn_get_named_range_value(name):
            """Get value from named range."""
            try:
                result = assumptions.loc[assumptions["name"] == name, "value"]
                if result.empty:
                    return None
                return result.iloc[0]
            except Exception as e:
                print(f"⚠️ Error getting named range '{name}': {e}")
                return None


        # =============================================================================
        # MAINTENANCE CAPEX FUNCTIONS
        # =============================================================================

        def fn_get_maintenance_capex_schedule(item_num):
            """
            Read maintenance capex schedule values from named range for a specific item.
            Named range: s.assetco.maintenance.capex.{item_num}
            Returns: List of monthly values, or None if not found
            """
            named_range = f"s.assetco.maintenance.capex.{item_num}"
            result = fn_get_named_range_value(named_range)
            
            if result is None:
                return None
            
            # Handle nested list (row from schedule)
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], list):
                    return result[0]  # Return first row
                return result
            
            return None


        def fn_compute_maintenance_capex():
            """
            Compute maintenance capex for all 4 line items.
            
            For each maintenance capex item (1-4):
            - Reads actuals from s.assetco.maintenance.capex.X
            - Schedule is aligned to model periods by position (col_idx)
            - effective_start = max(start_date, acquisition_date)
            - If no start_date given, defaults to acquisition_date
            - Output only for periods where period_start >= effective_start
            - Output bounded by asset_sale_date
            - Duration counted from effective_start
            
            Returns: Dictionary with 4 maintenance capex DataFrames
            """
            results = {}
            acquisition_date = fn_get_acquisition_date()
            asset_sale_date = fn_get_asset_sale_date()
            
            for item_num in range(1, 5):
                # Get start date - fallback to acquisition_date if not specified
                start_date_attr = f"maintenance_capex_{item_num}_start_date"
                start_date = getattr(Global.CapitalExpenditure, start_date_attr, None)
                start_date = fn_parse_date(start_date)
                if start_date is None:
                    start_date = acquisition_date
                
                # effective_start: output begins at the later of start_date and acquisition_date
                effective_start = start_date
                if start_date is not None and acquisition_date is not None and start_date < acquisition_date:
                    effective_start = acquisition_date
                
                # Get duration (in months)
                duration_attr = f"maintenance_capex_{item_num}_capex_duration"
                duration = getattr(Global.CapitalExpenditure, duration_attr, None)
                if duration is None or pd.isna(duration):
                    duration = _num_periods
                else:
                    try:
                        duration = int(duration)
                    except:
                        duration = _num_periods
                
                # Create result array
                capex_values = np.zeros(_num_periods)
                
                # Get actuals schedule for this capex item
                # Schedule is position-aligned to model periods (col_idx 0 = period 0)
                actuals_data = fn_get_maintenance_capex_schedule(item_num)
                
                months_applied = 0
                
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    
                    # Only output from effective_start onwards
                    if effective_start is not None and period_start < effective_start:
                        continue
                    
                    # Stop after asset sale date
                    if asset_sale_date and period_start > asset_sale_date:
                        break
                    
                    # Stop after duration months of output
                    if months_applied >= duration:
                        break
                    
                    # Read value using col_idx (schedule aligned to model periods)
                    if actuals_data is not None and col_idx < len(actuals_data):
                        actual_val = actuals_data[col_idx]
                        if actual_val is not None and not pd.isna(actual_val):
                            try:
                                capex_values[col_idx] = float(actual_val)
                            except:
                                capex_values[col_idx] = 0
                    
                    months_applied += 1
                
                results[f"maintenance_capex_{item_num}"] = pd.Series(capex_values, index=range(_num_periods))
                # print(f"   Computed Maintenance CapEx for items {item_num}.")
            return results


        # =============================================================================
        # SINKING FUND FUNCTIONS
        # =============================================================================

        def fn_get_sinking_fund_schedule():
            """
            Read sinking fund schedule from named range: s.assetco.sinking.fund
            Returns: List of monthly values, or None if not found
            """
            result = fn_get_named_range_value("s.assetco.sinking.fund")
            
            if result is None:
                return None
            
            # Handle nested list (row from schedule)
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], list):
                    return result[0]  # Return first row
                return result
            
            return None


        def fn_compute_total_base_rent_collections():
            """
            Compute total base rent collections across all tenants.
            Returns: Series of monthly totals
            """
            # Lazy import to avoid circular dependency
            # brm = _get_base_rent_module()
            
            # Ensure Module 03 has been run
            # if brm.base_rent_collections_monthly is None and brm.all_tenant_results is None:
            #     print("  ⏳ Running Module 03 (Base Rent) to compute collections...")
            #     brm.fn_run_module_03()
            
            # Use the output DataFrame if available (already computed totals)
            # if brm.base_rent_collections_monthly is not None:
            #     # base_rent_collections_monthly is a single-row DataFrame
            #     return pd.Series(brm.base_rent_collections_monthly.values.flatten(), index=range(_num_periods))
            
            # Otherwise compute from all_tenant_results
            if all_tenant_results is not None:
                total = np.zeros(_num_periods)
                # T1 + T2 only (renewal excluded) to match CFS revenue
                for tenant_type in ["tenant1", "tenant2"]:
                    if tenant_type in all_tenant_results:
                        collectible = all_tenant_results[tenant_type].get("collectible_rent")
                        if collectible is not None:
                            total += collectible.sum(axis=0).values
                return pd.Series(total, index=range(_num_periods))
            
            # If nothing computed yet, return zeros
            return pd.Series(np.zeros(_num_periods), index=range(_num_periods))


        def fn_compute_total_tor_collections():
            """
            Compute total TOR collections across all tenants.
            T1 TOR + T2 TOR only (renewal TOR excluded) to match CFS.
            Returns: Series of monthly totals
            """
            total = np.zeros(_num_periods)
            
            try:
                # Get TOR results
                tor_results, _ = fn_compute_all_turnover_rent()
                
                # T1 TOR only (renewal excluded)
                if "tenant1_and_renewal" in tor_results:
                    t1_tor = tor_results["tenant1_and_renewal"].get("turnover_rent_t1")
                    if t1_tor is not None:
                        total += t1_tor.sum(axis=0).values
                
                # T2 TOR (full weight)
                if "tenant2" in tor_results:
                    t2_tor = tor_results["tenant2"].get("turnover_rent")
                    if t2_tor is not None:
                        total += t2_tor.sum(axis=0).values
            
            except Exception as e:
                print(f"⚠️ Error computing TOR collections: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        def fn_compute_total_gross_rent_for_sinking_fund():
            """
            Compute total gross rent (base rent + TOR).
            Returns: Series of monthly totals
            """
            start_ts = time.time()
            if _is_parallel_active():
                base_rent = fn_compute_total_base_rent_collections()
                tor = fn_compute_total_tor_collections()
            else:
                with _parallel_section():
                    with ThreadPoolExecutor(max_workers=_cap_workers(2)) as executor:
                        futures = {
                            "base_rent": executor.submit(fn_compute_total_base_rent_collections),
                            "tor": executor.submit(fn_compute_total_tor_collections),
                        }
                        base_rent = futures["base_rent"].result()
                        tor = futures["tor"].result()
            duration = time.time() - start_ts
            _record_parallel_timing("sinking_fund:gross_rent", duration)

            return base_rent + tor


        def fn_compute_total_opex():
            """
            Compute total operating expenses.
            Returns: Series of monthly totals
            """
            total = np.zeros(_num_periods)
            
            try:
                # Lazy import OPEX module
                # opex_mod = _get_opex_module()
                opex_results = fn_compute_all_operating_expenses()
                
                # Sum all OPEX categories
                for category, data in opex_results.items():
                    if isinstance(data, dict) and "total" in data:
                        total += data["total"].values
                    elif isinstance(data, pd.Series):
                        total += data.values
                    elif isinstance(data, pd.DataFrame):
                        total += data.sum(axis=0).values
            
            except Exception as e:
                print(f"⚠️ Error computing OPEX: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        def fn_compute_noi_for_sinking_fund():
            """
            Compute NOI (Net Operating Income) = Gross Rent - Operating Expenses.
            Returns: Series of monthly totals
            """
            start_ts = time.time()
            if _is_parallel_active():
                gross_rent = fn_compute_total_gross_rent_for_sinking_fund()
                opex = fn_compute_total_opex()
            else:
                with _parallel_section():
                    with ThreadPoolExecutor(max_workers=_cap_workers(2)) as executor:
                        gross_rent_future = executor.submit(fn_compute_total_gross_rent_for_sinking_fund)
                        opex_future = executor.submit(fn_compute_total_opex)

                        gross_rent = gross_rent_future.result()
                        opex = opex_future.result()
            duration = time.time() - start_ts
            _record_parallel_timing("sinking_fund:noi", duration)

            return gross_rent - opex


        def fn_compute_sinking_fund():
            """
            Compute sinking fund based on input parameters.
            
            - input_type: Actuals, Forecast, or Actuals + Forecast
            - cost_type: % of Base Rent, % of Gross Rent, or % of NOI
            - percentage_of_revenue_or_noi: The percentage to apply
            - start_date: When sinking fund starts
            
            For Actuals: read month-on-month from s.assetco.sinking.fund (starting from start_date)
            For Forecast: calculate percentage of base/gross rent/NOI
            For Actuals + Forecast: use actuals where non-zero, forecast elsewhere
            
            Returns: Series of monthly sinking fund values
            """
            result = np.zeros(_num_periods)
            
            # Get sinking fund parameters from Global class
            opex_type = Global.SinkingFund.opex_type
            
            cost_type = Global.SinkingFund.cost_type
            percentage = Global.SinkingFund.percentage_of_revenue_or_noi
            start_date = fn_parse_date(Global.SinkingFund.start_date)
            
            # Validate percentage
            if percentage is None or pd.isna(percentage):
                percentage = 0
            else:
                try:
                    percentage = float(percentage)
                except:
                    percentage = 0
            # Normalize: if entered as whole number (e.g. 5 meaning 5%), convert to decimal
            if percentage > 1:
                percentage = percentage / 100.0
            
            # Normalize opex_type (input mode)
            opex_type_str = ""
            if opex_type is not None and not pd.isna(opex_type):
                opex_type_str = str(opex_type).lower().strip()
            
            # Normalize cost_type
            cost_type_str = ""
            if cost_type is not None and not pd.isna(cost_type):
                cost_type_str = str(cost_type).lower().replace(" ", "")
            
            # Determine if we should use actuals or forecast
            use_actuals = opex_type_str in ["actuals", "actual", "actuals + forecast", "actual + forecast", "actuals+forecast", "actual+forecast"]
            use_forecast = opex_type_str in ["forecast", "forecasts", "actuals + forecast", "actual + forecast", "actuals+forecast", "actual+forecast"]
            
            # Get actuals schedule
            actuals_data = None
            if use_actuals:
                actuals_data = fn_get_sinking_fund_schedule()
            
            # Determine base value for forecast (Base Rent, Gross Rent, or NOI)
            base_values = None
            if use_forecast and percentage > 0:
                if "baserent" in cost_type_str or "base" in cost_type_str:
                    base_values = fn_compute_total_base_rent_collections()
                elif "grossrent" in cost_type_str or "gross" in cost_type_str:
                    base_values = fn_compute_total_gross_rent_for_sinking_fund()
                elif "noi" in cost_type_str:
                    base_values = fn_compute_noi_for_sinking_fund()
                else:
                    # Default to base rent
                    base_values = fn_compute_total_base_rent_collections()
            
            # Compute effective_start = max(start_date, acquisition_date)
            acquisition_date = fn_get_acquisition_date()
            asset_sale_date = fn_get_asset_sale_date()
            effective_start = start_date
            if start_date is not None and acquisition_date is not None:
                effective_start = max(start_date, acquisition_date)
            elif acquisition_date is not None:
                effective_start = acquisition_date
            
            # Calculate sinking fund for each period
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                
                # Check if period is >= effective start
                if effective_start is not None and period_start < effective_start:
                    continue
                
                # Stop after asset sale date
                if asset_sale_date and period_start > asset_sale_date:
                    break
                
                value = 0
                actual_used = False
                
                # Try to use actuals first (schedule is position-aligned to model periods)
                if use_actuals and actuals_data is not None:
                    if col_idx < len(actuals_data):
                        actual_val = actuals_data[col_idx]
                        if actual_val is not None and not pd.isna(actual_val):
                            try:
                                val = float(actual_val)
                                if val != 0:  # Non-zero actual
                                    value = val
                                    actual_used = True
                            except:
                                pass
                
                # Compute forecast value
                forecast_value = 0
                if use_forecast and base_values is not None and percentage > 0:
                    forecast_value = base_values.iloc[col_idx] * percentage
                
                # Apply based on input mode
                if opex_type_str in ["actuals", "actual"]:
                    # Only use actuals
                    result[col_idx] = value
                elif opex_type_str in ["forecast", "forecasts"]:
                    # Only use forecast
                    result[col_idx] = forecast_value
                elif use_actuals and use_forecast:
                    # Actuals + Forecast: use actuals where non-zero, else forecast
                    if actual_used:
                        result[col_idx] = value
                    else:
                        result[col_idx] = forecast_value
                else:
                    # Default: use actuals if available, else forecast
                    if actual_used:
                        result[col_idx] = value
                    else:
                        result[col_idx] = forecast_value
            
            return pd.Series(result, index=range(_num_periods))


        # =============================================================================
        # MAIN COMPUTATION FUNCTION
        # =============================================================================

        def fn_compute_all_maintenance_capex_and_sinking_fund():
            """
            Compute all maintenance capex and sinking fund.
            
            Returns:
                Dictionary containing:
                - maintenance_capex_1 through maintenance_capex_4: Series
                - sinking_fund: Series
                - total_maintenance_capex: Series
                - grand_total: Series (all capex + sinking fund)
            """
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts
            # global assumptions, model_timeline_me
            cache_key = "module:maintenance_capex"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # Initialize globals if not set (when called from other modules)
            # if _num_periods is None:
            #     # import AM_Co_02_input_assignment_module as mod02
                # if mod02.model_timeline_me is None:
                #     from AM_Co_02_input_assignment_module import fn_run_module_02
                #     fn_run_module_02()
                
                # assumptions = mod02.assumptions
                # model_timeline_me = mod02.model_timeline_me
                # _num_assets = len(Unit.UnitInputs.unit_id)
                # _num_periods = len(model_timeline_me)
                # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
                # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # print("Computing Maintenance CapEx...")
            maintenance_capex = fn_compute_maintenance_capex()
            
            # print("Computing Sinking Fund...")
            sinking_fund = fn_compute_sinking_fund()
            
            # Calculate totals
            total_maintenance_capex = np.zeros(_num_periods)
            for key, values in maintenance_capex.items():
                total_maintenance_capex += values.values
            
            total_maintenance_capex = pd.Series(total_maintenance_capex, index=range(_num_periods))
            grand_total = total_maintenance_capex + sinking_fund
            
            results = {
                **maintenance_capex,
                "sinking_fund": sinking_fund,
                "total_maintenance_capex": total_maintenance_capex,
                "grand_total": grand_total,
            }
            
            # print("✅ Maintenance CapEx and Sinking Fund computation complete.")
            
            return _cache_set(cache_key, results)


        # =============================================================================
        # CREATE OUTPUT DATAFRAMES
        # =============================================================================

        def fn_create_output_dataframes(results):
            """
            Create single-line output DataFrames for CFS/Output module.
            
            Creates monthly and annual DataFrames for:
            - Maintenance CapEx items (1-4)
            - Total Maintenance CapEx
            - Sinking Fund
            """
            global maintenance_capex_1_monthly, maintenance_capex_1_annual
            global maintenance_capex_2_monthly, maintenance_capex_2_annual
            global maintenance_capex_3_monthly, maintenance_capex_3_annual
            global maintenance_capex_4_monthly, maintenance_capex_4_annual
            global total_maintenance_capex_monthly, total_maintenance_capex_annual
            global sinking_fund_monthly, sinking_fund_annual
            global grand_total_monthly, grand_total_annual
            
            # import AM_Co_02_input_assignment_module as mod02
            # model_timeline_me = mod02.model_timeline_me
            # model_timeline_ye = mod02.model_timeline_ye
            
            # Get period to year mapping
            period_years = model_timeline_me["Period Start"].apply(lambda x: x.year).values
            
            # Helper to create annual sum
            def create_annual_df(monthly_series):
                if monthly_series is None:
                    return pd.DataFrame([[0] * len(model_timeline_ye)], columns=model_timeline_ye.index)
                
                annual_values = []
                for year_idx, year_row in model_timeline_ye.iterrows():
                    year_start = year_row["Period Start"]
                    year_val = year_start.year
                    
                    # Sum monthly values for this year
                    mask = period_years == year_val
                    year_sum = monthly_series.iloc[mask].sum() if mask.any() else 0
                    annual_values.append(year_sum)
                
                return pd.DataFrame([annual_values], columns=model_timeline_ye.index)
            
            # Helper to create monthly DataFrame
            def create_monthly_df(series):
                if series is None:
                    return pd.DataFrame([[0] * _num_periods], columns=model_timeline_me.index)
                return pd.DataFrame([series.values], columns=model_timeline_me.index)
            
            # Maintenance CapEx items
            maintenance_capex_1_monthly = create_monthly_df(results.get("maintenance_capex_1"))
            maintenance_capex_1_annual = create_annual_df(results.get("maintenance_capex_1"))
            maintenance_capex_2_monthly = create_monthly_df(results.get("maintenance_capex_2"))
            maintenance_capex_2_annual = create_annual_df(results.get("maintenance_capex_2"))
            maintenance_capex_3_monthly = create_monthly_df(results.get("maintenance_capex_3"))
            maintenance_capex_3_annual = create_annual_df(results.get("maintenance_capex_3"))
            maintenance_capex_4_monthly = create_monthly_df(results.get("maintenance_capex_4"))
            maintenance_capex_4_annual = create_annual_df(results.get("maintenance_capex_4"))
            
            # Total Maintenance CapEx
            total_maintenance_capex_monthly = create_monthly_df(results.get("total_maintenance_capex"))
            total_maintenance_capex_annual = create_annual_df(results.get("total_maintenance_capex"))
            
            # Sinking Fund
            sinking_fund_monthly = create_monthly_df(results.get("sinking_fund"))
            sinking_fund_annual = create_annual_df(results.get("sinking_fund"))
            
            # Grand Total (Maintenance CapEx + Sinking Fund)
            grand_total_monthly = create_monthly_df(results.get("grand_total"))
            grand_total_annual = create_annual_df(results.get("grand_total"))
            
            # print("   Created output DataFrames:")
            # print(f"      maintenance_capex_1_monthly: {maintenance_capex_1_monthly.shape}")
            # print(f"      maintenance_capex_2_monthly: {maintenance_capex_2_monthly.shape}")
            # print(f"      maintenance_capex_3_monthly: {maintenance_capex_3_monthly.shape}")
            # print(f"      maintenance_capex_4_monthly: {maintenance_capex_4_monthly.shape}")
            # print(f"      total_maintenance_capex_monthly: {total_maintenance_capex_monthly.shape}")
            # print(f"      sinking_fund_monthly: {sinking_fund_monthly.shape}")
            # print(f"      grand_total_monthly: {grand_total_monthly.shape}")


        # =============================================================================
        # MODULE INITIALIZATION
        # =============================================================================

        def fn_run_module_08():
            """Initialize and run Module 08 - Maintenance CapEx and Sinking Fund."""
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts
            # global assumptions, model_timeline_me, template_asset_timeline
            
            # print("=" * 60)
            # print("MODULE 08: MAINTENANCE CAPEX AND SINKING FUND")
            # print("=" * 60)
            
            # Initialize dependencies
            # import AM_Co_02_input_assignment_module as mod02
            # from AM_Co_02_input_assignment_module import fn_run_module_02
            
            # if mod02.model_timeline_me is None:
            #     print("\n📂 Running Module 02 to load inputs...")
            #     fn_run_module_02()
            
            # Get updated values
            # assumptions = mod02.assumptions
            # model_timeline_me = mod02.model_timeline_me
            # template_asset_timeline = mod02.template_asset_timeline
            
            # Initialize module variables
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = len(model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # print(f"   Assets: {_num_assets}, Periods: {_num_periods}")
            
            # Compute maintenance capex and sinking fund
            # print("\n🔧 Computing Maintenance CapEx and Sinking Fund...")
            results = fn_compute_all_maintenance_capex_and_sinking_fund()
            
            # Create output DataFrames
            # print("\n📋 Creating output DataFrames...")
            fn_create_output_dataframes(results)
            
            # Print summary
            total_capex = results["total_maintenance_capex"].sum()
            total_sf = results["sinking_fund"].sum()
            # print(f"\n   Total Maintenance CapEx: {total_capex:,.0f}")
            # print(f"   Total Sinking Fund: {total_sf:,.0f}")
            # print(f"   Grand Total: {results['grand_total'].sum():,.0f}")
            
            # print("\n✅ Module 08 completed successfully!")
            return results


        # =============================================================================
        # EXPORT FUNCTION
        # =============================================================================

        def fn_export_to_excel(results, output_file=None):
            """
            Export maintenance capex and sinking fund results to Excel.
            """
            if output_file is None:
                output_file = os.path.join(os.path.dirname(__file__), "Maintenance_Capex_Output.xlsx")
            
            # Create month headers
            month_headers = [_period_starts_ts[i].strftime("%Y-%m") for i in range(_num_periods)]
            
            # Prepare summary data
            summary_data = []
            
            # Maintenance CapEx items
            for item_num in range(1, 5):
                key = f"maintenance_capex_{item_num}"
                if key in results:
                    row = {"Line Item": f"Maintenance CapEx {item_num}"}
                    for col_idx in range(_num_periods):
                        row[month_headers[col_idx]] = results[key].iloc[col_idx]
                    row["Total"] = results[key].sum()
                    summary_data.append(row)
            
            # Sinking Fund
            if "sinking_fund" in results:
                row = {"Line Item": "Sinking Fund"}
                for col_idx in range(_num_periods):
                    row[month_headers[col_idx]] = results["sinking_fund"].iloc[col_idx]
                row["Total"] = results["sinking_fund"].sum()
                summary_data.append(row)
            
            # Total Maintenance CapEx
            if "total_maintenance_capex" in results:
                row = {"Line Item": "Total Maintenance CapEx"}
                for col_idx in range(_num_periods):
                    row[month_headers[col_idx]] = results["total_maintenance_capex"].iloc[col_idx]
                row["Total"] = results["total_maintenance_capex"].sum()
                summary_data.append(row)
            
            # Grand Total
            if "grand_total" in results:
                row = {"Line Item": "Grand Total (CapEx + Sinking Fund)"}
                for col_idx in range(_num_periods):
                    row[month_headers[col_idx]] = results["grand_total"].iloc[col_idx]
                row["Total"] = results["grand_total"].sum()
                summary_data.append(row)
            
            df_summary = pd.DataFrame(summary_data)
            
            # Export to Excel
            with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
                df_summary.to_excel(writer, sheet_name="Monthly Summary", index=False)
            
            # print(f"✅ Output saved to: {output_file}")
            
            return output_file

        # =============================================================================
        # OUTPUT DATAFRAMES (Single-line items for CFS/Output)
        # =============================================================================

        # NOI Components
        base_rent_monthly = None
        base_rent_annual = None
        service_charge_monthly = None
        service_charge_annual = None
        tor_monthly = None
        tor_annual = None
        leasing_commission_monthly = None
        leasing_commission_annual = None
        opex_monthly = None
        opex_annual = None
        noi_monthly = None
        noi_annual = None

        # Asset Sale Value
        asset_sale_price = None
        asset_sale_cf_monthly = None
        asset_sale_cf_annual = None

        # Net Operating Cashflows
        net_operating_cf_monthly = None
        net_operating_cf_annual = None

        # Acquisition Costs (separate line items)
        acquisition_price_output = None
        transfer_tax_output = None
        legal_fees_output = None
        brokerage_output = None
        due_diligence_output = None
        total_acquisition_costs_output = None


        # =============================================================================
        # LAZY IMPORTS (to avoid circular dependencies and speed up load)
        # =============================================================================

        _base_rent_module = None
        _tor_module = None
        _tenant_other_inputs_module = None
        _opex_module = None
        _other_income_expenses_module = None
        _maintenance_capex_module = None


        # def _get_base_rent_module():
        #     global _base_rent_module
        #     if _base_rent_module is None:
        #         import AM_Co_03_base_rent_module as brm
        #         _base_rent_module = brm
        #     return _base_rent_module


        # def _get_tor_module():
        #     global _tor_module
        #     if _tor_module is None:
        #         import AM_Co_04_turnover_rent_module as tor
        #         _tor_module = tor
        #     return _tor_module


        # def _get_tenant_other_inputs_module():
        #     global _tenant_other_inputs_module
        #     if _tenant_other_inputs_module is None:
        #         import AM_Co_05_Tenant_Other_Inputs_module as toi
        #         _tenant_other_inputs_module = toi
        #     return _tenant_other_inputs_module


        # def _get_opex_module():
        #     global _opex_module
        #     if _opex_module is None:
        #         import AM_Co_06_Operating_Expenses_module as opex
        #         _opex_module = opex
        #     return _opex_module


        # def _get_other_income_expenses_module():
        #     global _other_income_expenses_module
        #     if _other_income_expenses_module is None:
        #         import AM_Co_07_Other_Income_Expenses_module as oie
        #         _other_income_expenses_module = oie
        #     return _other_income_expenses_module


        # def _get_maintenance_capex_module():
        #     global _maintenance_capex_module
        #     if _maintenance_capex_module is None:
        #         import AM_Co_08_Maintenance_Capex_module as mcapex
        #         _maintenance_capex_module = mcapex
        #     return _maintenance_capex_module


        # =============================================================================
        # HELPER FUNCTIONS - GET GLOBAL INPUTS
        # NOTE: fn_get_acquisition_date and fn_get_asset_sale_date are defined earlier
        # =============================================================================


        def fn_get_analysis_type():
            """Get analysis type (Investment or Valuation)."""
            # Try Global.ModelInputs first
            try:
                val = Global.ModelInputs.analysis_type
                if val and not pd.isna(val) and str(val).strip().lower() not in ("none", ""):
                    return str(val).strip()
            except Exception:
                pass
            
            # Try reading from assumptions DataFrame with various named ranges
            named_range_options = [
                "s.assetco.analysis.type",
                "s.analysis.type",
                "a.assetco.analysis.type",
                "analysis_type",
            ]
            
            for named_range in named_range_options:
                try:
                    result = assumptions.loc[assumptions["name"] == named_range, "value"]
                    if not result.empty:
                        val = result.iloc[0]
                        # Handle nested list
                        if isinstance(val, list):
                            val = val[0] if len(val) > 0 else None
                            if isinstance(val, list):
                                val = val[0] if len(val) > 0 else None
                        if val and not pd.isna(val):
                            val_str = str(val).strip()
                            val_lower = val_str.lower()
                            if "valuat" in val_lower:
                                return "Valuation"
                            elif "invest" in val_lower:
                                return "Investment"
                            elif val_lower not in ("none", ""):
                                return val_str
                except Exception:
                    pass
            
            # Default to valuation if not found
            return "Valuation"


        def fn_get_discount_rate():
            """Get discount rate from valuation parameters."""
            try:
                val = Global.ValuationParameters.discount_rate
                if val and not pd.isna(val):
                    return float(val)
                return 0
            except:
                return 0


        def fn_get_exit_yield():
            """Get exit yield from valuation parameters."""
            try:
                val = Global.ValuationParameters.exit_yield
                if val and not pd.isna(val):
                    return float(val)
                return 0
            except:
                return 0


        def fn_get_noi_escalation():
            """Get NOI escalation rate from valuation parameters."""
            try:
                val = Global.ValuationParameters.noi_escalation
                if val and not pd.isna(val):
                    return float(val)
                return 0
            except:
                return 0


        def fn_compute_per_unit_base_rent_sc():
            """Compute per-unit monthly (base rent + service charge) only.

            Used by the unit-level NOI top-up logic to detect occupied months
            and to fill vacant months with the most recent occupied month's
            base rent + SC.

            Full T2 (no probability discount), renewal excluded.

            Returns
            -------
            numpy array of shape (_num_assets, _num_periods).
            """
            cache_key = "unit_level:per_unit_base_rent_sc"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

            rev = np.zeros((_num_assets, _num_periods))

            # --- Base rent (collectible_rent) per unit ---
            nonlocal all_tenant_results
            if all_tenant_results is None:
                fn_run_module_03()
            if all_tenant_results is not None:
                # T1: full weight
                cr_t1 = all_tenant_results.get("tenant1", {}).get("collectible_rent")
                if cr_t1 is not None:
                    rev += cr_t1.values
                # Renewal: excluded
                # T2: full weight (no probability discount)
                cr_t2 = all_tenant_results.get("tenant2", {}).get("collectible_rent")
                if cr_t2 is not None:
                    rev += cr_t2.values

            # --- Ratchet base-rent adjustment per unit ---
            try:
                tor_results, _ = fn_compute_all_turnover_rent()
                if "tenant1_and_renewal" in tor_results:
                    adj_df = tor_results["tenant1_and_renewal"].get("base_rent_adj")
                    if adj_df is not None:
                        adj_vals = adj_df.values.copy()
                        # Only include T1-period adjustments; exclude renewal months
                        ren_cr = None
                        if all_tenant_results is not None:
                            ren_cr_df = all_tenant_results.get("renewal", {}).get("collectible_rent")
                            if ren_cr_df is not None:
                                ren_cr = ren_cr_df.values
                        if ren_cr is not None:
                            rev += np.where(ren_cr == 0, adj_vals, 0.0)
                        else:
                            rev += adj_vals
                if "tenant2" in tor_results:
                    adj_df = tor_results["tenant2"].get("base_rent_adj")
                    if adj_df is not None:
                        rev += adj_df.values
            except Exception:
                pass

            # --- Service charges per unit ---
            # Renewal prob already handled in fn_compute_all_tenant_other_inputs
            # (renewal zeroed out, T2 at full weight)
            try:
                toi_results, _ = fn_compute_all_tenant_other_inputs()
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    sc_df = toi_results.get(tenant_key, {}).get("service_charge")
                    if sc_df is not None and isinstance(sc_df, pd.DataFrame):
                        rev += sc_df.values
            except Exception:
                pass

            _cache_set(cache_key, rev)
            return rev


        def fn_compute_per_unit_gross_rent():
            """Per-unit monthly gross rent = collectible_rent + ratchet adj + TOR.

            NO service charges.  Used for under/over-rent comparison against
            escalated market rent.

            Returns numpy array of shape (_num_assets, _num_periods).
            """
            cache_key = "unit_level:per_unit_gross_rent"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

            rev = np.zeros((_num_assets, _num_periods))

            nonlocal all_tenant_results
            if all_tenant_results is None:
                fn_run_module_03()
            if all_tenant_results is not None:
                cr_t1 = all_tenant_results.get("tenant1", {}).get("collectible_rent")
                if cr_t1 is not None:
                    rev += cr_t1.values
                cr_t2 = all_tenant_results.get("tenant2", {}).get("collectible_rent")
                if cr_t2 is not None:
                    rev += cr_t2.values

            # Ratchet base-rent adjustment + TOR (from TOR module)
            try:
                tor_results, _ = fn_compute_all_turnover_rent()
                if "tenant1_and_renewal" in tor_results:
                    # Base rent ratchet adjustment
                    adj_df = tor_results["tenant1_and_renewal"].get("base_rent_adj")
                    if adj_df is not None:
                        adj_vals = adj_df.values.copy()
                        ren_cr = None
                        if all_tenant_results is not None:
                            ren_cr_df = all_tenant_results.get("renewal", {}).get("collectible_rent")
                            if ren_cr_df is not None:
                                ren_cr = ren_cr_df.values
                        if ren_cr is not None:
                            rev += np.where(ren_cr == 0, adj_vals, 0.0)
                        else:
                            rev += adj_vals
                    # Turnover rent (excess above base rent)
                    tor_df = tor_results["tenant1_and_renewal"].get("turnover_rent")
                    if tor_df is not None:
                        tor_vals = tor_df.values.copy()
                        ren_cr = None
                        if all_tenant_results is not None:
                            ren_cr_df = all_tenant_results.get("renewal", {}).get("collectible_rent")
                            if ren_cr_df is not None:
                                ren_cr = ren_cr_df.values
                        if ren_cr is not None:
                            rev += np.where(ren_cr == 0, tor_vals, 0.0)
                        else:
                            rev += tor_vals
                if "tenant2" in tor_results:
                    adj_df = tor_results["tenant2"].get("base_rent_adj")
                    if adj_df is not None:
                        rev += adj_df.values
                    tor_df = tor_results["tenant2"].get("turnover_rent")
                    if tor_df is not None:
                        rev += tor_df.values
            except Exception:
                pass

            _cache_set(cache_key, rev)
            return rev


        def fn_get_inflation_profiles():
            """Read inflation escalation profiles from assumptions.

            Named ranges:
              - ``a.assetco.inflation.profiles`` – list of profile names
              - ``a.assetco.inflation.values``   – 2-D list of annual rates per profile

            Returns dict  {profile_name: {year_num: rate, ...}, ...}
            """
            cache_key = "inflation_profiles"
            cached = _local_cache_get(profile_cache, cache_key)
            if cached is not None:
                return cached

            profiles = {}
            try:
                names_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.inflation.profiles", "value"
                ]
                if names_df.empty:
                    return _local_cache_set(profile_cache, cache_key, profiles)
                profile_names_list = names_df.iloc[0]

                values_df = assumptions.loc[
                    assumptions["name"] == "a.assetco.inflation.values", "value"
                ]
                if values_df.empty:
                    return _local_cache_set(profile_cache, cache_key, profiles)
                values_data = values_df.iloc[0]

                if isinstance(profile_names_list, list):
                    for idx, name in enumerate(profile_names_list):
                        if name and not pd.isna(name):
                            name_str = str(name).strip()
                            profiles[name_str] = {}
                            if isinstance(values_data, list) and idx < len(values_data):
                                rate_row = values_data[idx]
                                if isinstance(rate_row, list):
                                    for yr_idx, rate in enumerate(rate_row):
                                        yr = yr_idx + 1
                                        if rate is not None and not pd.isna(rate) and rate != "":
                                            try:
                                                profiles[name_str][yr] = float(rate)
                                            except (ValueError, TypeError):
                                                pass
                                else:
                                    if rate_row is not None and not pd.isna(rate_row):
                                        try:
                                            profiles[name_str][1] = float(rate_row)
                                        except (ValueError, TypeError):
                                            pass
            except Exception as e:
                print(f"⚠️ Error loading inflation profiles: {e}")

            return _local_cache_set(profile_cache, cache_key, profiles)


        def fn_get_inflation_rate_for_year(profiles, year_num, profile_name=None):
            """Return the inflation rate for *year_num*.

            If *profile_name* is given, use that specific profile.
            Otherwise fall back to the first available profile.
            Falls back to the last available year's rate, then to 0.
            """
            if not profiles:
                return 0.0

            # Resolve profile dict
            if profile_name and profile_name in profiles:
                profile = profiles[profile_name]
            else:
                profile = next(iter(profiles.values()))

            if year_num in profile:
                return profile[year_num]
            if profile:
                return profile[max(profile.keys())]
            return 0.0


        def fn_escalate_market_rent_to_date(market_rent_psm, target_date):
            """Escalate a per-sqm market rent from model_start_date to *target_date*
            using the inflation profile specified in NOIStabalizationAssumptions.

            Market rent is stated as-of model_start_date.  Compounding is
            yearly: compound for each full year from model start up to AND
            including the year in which the sale falls.

            Example:  model_start = Jan-2023, sale = Mar-2028
              → 5 full years elapsed + sale falls in Year 6
              → compound for 6 years (Year 1 through Year 6)

            Returns escalated per-sqm value.
            """
            model_start = Global.ModelInputs.model_start_date
            if model_start is None or pd.isna(model_start):
                return market_rent_psm
            model_start = pd.to_datetime(model_start)
            target_date = pd.to_datetime(target_date)

            if target_date <= model_start:
                return market_rent_psm

            inflation_profiles = fn_get_inflation_profiles()

            # Resolve the specific inflation profile name from NOI Stabilization inputs
            inflation_profile_name = None
            try:
                raw = Global.NOIStabalizationAssumptions.inflation_factor
                if raw is not None and not pd.isna(raw) and str(raw).strip():
                    inflation_profile_name = str(raw).strip()
            except (AttributeError, TypeError):
                pass

            # Determine number of compounding years:
            # full years + 1 if there are any remaining months (sale year counts)
            total_months = (target_date.year - model_start.year) * 12 + (target_date.month - model_start.month)
            full_years = total_months // 12
            remaining_months = total_months % 12
            compounding_years = full_years + (1 if remaining_months > 0 else 0)

            escalated = float(market_rent_psm)
            for yr in range(1, compounding_years + 1):
                rate = fn_get_inflation_rate_for_year(inflation_profiles, yr, inflation_profile_name)
                escalated *= (1 + rate)

            return escalated


        def fn_compute_noi_stabilization_adjustment(asset_sale_date):
            """Compute NOI stabilization adjustments (Steps 1–5) for terminal value.

            Step 1 – Vacancy Rent Top-Up (capped at 12 months):
              For each vacant unit in the 12 months prior to sale,
              add Escalated Market Rent × GLA × months_vacant.

            Step 2 – Rent-Free & Void Period deductions:
              For vacant units only: deduct Market Rent × GLA × RF months,
              and Market Rent × GLA × Void months.
              Inputs from T2 first; fall back to T1 only when T2 is
              blank/None/NaN (zero IS a valid T2 value → no fallback).

            Step 3 – Leasing Commission deduction:
              Commission % × Market Rent × GLA × 12.
              T2 first, T1 fallback (same blank-only rule).

            Step 4 – Tenant Fit-Out deduction:
              Fit-Out Cost × GLA.
              T2 first, T1 fallback (same blank-only rule).

            Step 5 – Under-rent / Over-rent:
              For each occupied month in the window compare escalated
              market rent vs actual gross rent and adjust the difference.

            Market rent sourcing (per unit):
              1. Unit-level: Unit.UnitInputs.market_rent (if available & > 0)
              2. Global fallback: NOIStabalizationAssumptions.current_market_rent
              3. If both blank/zero → skip unit (no adjustment)

            Returns (vacancy_adj, reletting_adj, rent_adj).
            """
            if asset_sale_date is None:
                print("  [STABILIZATION] No asset_sale_date — returning 0")
                return 0.0, 0.0, 0.0

            asset_sale_date = pd.to_datetime(asset_sale_date)

            # --- Read global market rent (fallback, per sqm, as of model start) ---
            global_market_rent_raw = 0.0
            try:
                val = Global.NOIStabalizationAssumptions.current_market_rent
                if val is not None and not pd.isna(val):
                    global_market_rent_raw = float(val)
            except (AttributeError, ValueError, TypeError):
                pass

            print(f"  [STABILIZATION] Global market_rent (raw, per sqm): {global_market_rent_raw}")

            # --- Determine index window for last 12 months ---
            last_idx = -1
            for col_idx in range(_num_periods - 1, -1, -1):
                if _period_starts_ts[col_idx] <= asset_sale_date:
                    last_idx = col_idx
                    break
            if last_idx < 0:
                print("  [STABILIZATION] Could not find period for sale date — returning 0")
                return 0.0, 0.0, 0.0
            start_idx = max(0, last_idx - 11)
            window_len = last_idx - start_idx + 1
            print(f"  [STABILIZATION] Window: periods {start_idx}–{last_idx} ({window_len} months)")

            # --- Build per-unit lease-active flags for T1 and T2 ---
            t1_lease = fn_create_lease_flags("tenant1").values   # (_num_assets, _num_periods)
            t2_lease = fn_create_lease_flags("tenant2").values
            combined_active = np.clip(t1_lease + t2_lease, 0, 1)  # 1 if any tenant active

            # --- Per-unit gross rent (no SC) for under/over-rent comparison ---
            per_unit_gross_rent = fn_compute_per_unit_gross_rent()  # (_num_assets, _num_periods)

            # Helper: check if a value is "provided" (not None, not NaN).
            # Zero IS a valid provided value.
            def _is_provided(v):
                if v is None:
                    return False
                try:
                    return not pd.isna(v)
                except (TypeError, ValueError):
                    return True

            vacancy_adj = 0.0
            reletting_adj = 0.0
            rent_adj = 0.0
            units_with_mr = 0
            units_skipped_no_mr = 0

            for asset_idx in range(_num_assets):
                gla = fn_safe_get(Unit.UnitInputs.gross_leasable_area, asset_idx)
                if gla is None or pd.isna(gla):
                    continue
                try:
                    gla = float(gla)
                except (ValueError, TypeError):
                    continue
                if gla <= 0:
                    continue

                # --- Resolve market rent: unit-level first, global fallback ---
                mr_raw = 0.0
                mr_source = "none"

                unit_mr_raw = fn_safe_get(Unit.UnitInputs.market_rent, asset_idx)
                try:
                    if unit_mr_raw is not None and not pd.isna(unit_mr_raw) and float(unit_mr_raw) > 0:
                        mr_raw = float(unit_mr_raw)
                        mr_source = "unit"
                except (ValueError, TypeError):
                    pass

                if mr_raw <= 0 and global_market_rent_raw > 0:
                    mr_raw = global_market_rent_raw
                    mr_source = "global"

                if mr_raw <= 0:
                    units_skipped_no_mr += 1
                    continue  # Both empty/zero → no adjustment for this unit

                units_with_mr += 1

                # Escalate market rent from model start to asset sale date
                market_rent_psm = fn_escalate_market_rent_to_date(mr_raw, asset_sale_date)
                monthly_market_rent = market_rent_psm * gla

                # ============================================================
                # STEP 1: Vacancy Rent Top-Up (capped at 12 months)
                # ============================================================
                unit_vacancy_adj = 0.0
                vacant_months = 0

                for w in range(window_len):
                    pidx = start_idx + w
                    if combined_active[asset_idx, pidx] == 0:
                        vacancy_adj += monthly_market_rent
                        unit_vacancy_adj += monthly_market_rent
                        vacant_months += 1

                # ============================================================
                # STEPS 2-4: Re-letting deductions (vacant units only)
                # Only apply if the unit has any vacant months in the window.
                # T2 first; fall back to T1 only when T2 is blank/None/NaN.
                # Zero in T2 is a valid value — no fallback.
                # ============================================================
                total_reletting = 0.0

                if vacant_months > 0:
                    # STEP 2: Rent-Free & Void Period deductions
                    rf_months = 0.0
                    rf_t2 = fn_safe_get(Unit.LeaseParametersSecondTenant.rent_free_duration, asset_idx)
                    rf_t1 = fn_safe_get(Unit.LeaseParametersFirstTenant.rent_free_duration, asset_idx)
                    try:
                        if _is_provided(rf_t2):
                            rf_months = float(rf_t2)
                        elif _is_provided(rf_t1):
                            rf_months = float(rf_t1)
                    except (ValueError, TypeError):
                        pass

                    void_months_input = 0.0
                    void_t2 = fn_safe_get(Unit.SecondTenant.void_period_months, asset_idx)
                    void_t1 = fn_safe_get(Unit.LeaseExpirationTenant1.void_period_months, asset_idx)
                    try:
                        if _is_provided(void_t2):
                            void_months_input = float(void_t2)
                        elif _is_provided(void_t1):
                            void_months_input = float(void_t1)
                    except (ValueError, TypeError):
                        pass

                    rf_deduction = monthly_market_rent * rf_months
                    void_deduction = monthly_market_rent * void_months_input

                    # Apply renewal probability to void deduction:
                    # Effective void months = void_months × renewal_probability
                    # e.g. 4 months void × 75% renewal = 3 months effective void
                    renewal_prob = 0.0
                    rp_val = fn_safe_get(Unit.LeaseExpirationTenant1.renewal_probability, asset_idx)
                    try:
                        if rp_val is not None and not pd.isna(rp_val):
                            renewal_prob = float(rp_val)
                            if renewal_prob > 1:
                                renewal_prob = renewal_prob / 100.0
                    except (ValueError, TypeError):
                        pass
                    void_deduction = monthly_market_rent * void_months_input * renewal_prob

                    # STEP 3: Leasing Commission deduction
                    # Commission % × Market Rent × GLA × 12
                    lc_pct = 0.0
                    lc_t2 = fn_safe_get(Unit.RentParametersSecondTenant.leasing_commission, asset_idx)
                    lc_t1 = fn_safe_get(Unit.RentParametersFirstTenant.leasing_commission, asset_idx)
                    try:
                        if _is_provided(lc_t2):
                            lc_pct = float(lc_t2)
                        elif _is_provided(lc_t1):
                            lc_pct = float(lc_t1)
                    except (ValueError, TypeError):
                        pass
                    if lc_pct > 1:
                        lc_pct = lc_pct / 100.0

                    lc_deduction = lc_pct * monthly_market_rent * 12

                    # STEP 4: Tenant Fit-Out deduction
                    # Fit-Out Cost × GLA
                    fitout_cost = 0.0
                    fo_t2 = fn_safe_get(Unit.RentParametersSecondTenant.tenant_fit_out_allowance, asset_idx)
                    fo_t1 = fn_safe_get(Unit.RentParametersFirstTenant.tenant_fit_out_allowance, asset_idx)
                    try:
                        if _is_provided(fo_t2):
                            fitout_cost = float(fo_t2)
                        elif _is_provided(fo_t1):
                            fitout_cost = float(fo_t1)
                    except (ValueError, TypeError):
                        pass

                    fitout_deduction = fitout_cost * gla

                    total_reletting = rf_deduction + void_deduction + lc_deduction + fitout_deduction
                    reletting_adj -= total_reletting

                # ============================================================
                # STEP 5: Under-rent / Over-rent (for occupied months)
                # ============================================================
                unit_rent_adj = 0.0
                occupied_months = 0

                for w in range(window_len):
                    pidx = start_idx + w
                    if combined_active[asset_idx, pidx] == 1:
                        actual_gross_rent = per_unit_gross_rent[asset_idx, pidx]
                        diff = monthly_market_rent - actual_gross_rent
                        # diff > 0 → under-rented (add); diff < 0 → over-rented (deduct)
                        rent_adj += diff
                        unit_rent_adj += diff
                        occupied_months += 1

                unit_name = fn_safe_get(Unit.UnitInputs.asset_name, asset_idx, f"Unit#{asset_idx}")
                print(f"  ┌── Unit {asset_idx}: {unit_name}")
                print(f"  │  GLA={gla:,.2f}  MR source={mr_source}  MR raw={mr_raw:.2f}  MR escalated(psm)={market_rent_psm:.2f}")
                print(f"  │  Monthly Market Rent (MR×GLA) = {monthly_market_rent:,.2f}")
                print(f"  │  Step 1  Vacancy Top-Up : vacant_months={vacant_months}  adj={unit_vacancy_adj:,.2f}")
                if vacant_months > 0:
                    print(f"  │  Step 2  Rent-Free Ded  : rf_months={rf_months:.1f}  ded={rf_deduction:,.2f}")
                    print(f"  │  Step 2  Void Period Ded: void_months={void_months_input:.1f}  renewal_prob={renewal_prob:.4f}  ded={void_deduction:,.2f}")
                    print(f"  │  Step 3  Leasing Comm   : lc_pct={lc_pct:.4f}  ded={lc_deduction:,.2f}")
                    print(f"  │  Step 4  Tenant Fit-Out : fitout_psm={fitout_cost:.2f}  ded={fitout_deduction:,.2f}")
                    print(f"  │  Steps 2-4 Total Relet  : {total_reletting:,.2f}")
                else:
                    print(f"  │  Steps 2-4 (skipped — unit not vacant)")
                print(f"  │  Step 5  Under/Over-Rent: occ_months={occupied_months}  adj={unit_rent_adj:,.2f}")
                unit_total = unit_vacancy_adj - total_reletting + unit_rent_adj
                print(f"  └── Unit Total NOI Adj    : {unit_total:,.2f}")

            print(f"")
            print(f"  ╔══ STABILIZATION SUMMARY (Steps 1–5) ══════════════════")
            print(f"  ║  Units processed (with MR): {units_with_mr}")
            print(f"  ║  Units skipped (no MR)    : {units_skipped_no_mr}")
            print(f"  ║  Step 1  Total Vacancy Adj : {vacancy_adj:,.2f}")
            print(f"  ║  Steps2-4 Total Relet Adj  : {reletting_adj:,.2f}")
            print(f"  ║  Step 5  Total Rent Adj    : {rent_adj:,.2f}")
            combined = vacancy_adj + reletting_adj + rent_adj
            print(f"  ║  Net Stabilization Adj     : {combined:,.2f}")
            print(f"  ╚═════════════════════════════════════════════════════")

            return vacancy_adj, reletting_adj, rent_adj


        def fn_get_noi_topup():
            """Compute the NOI stabilization adjustment (Steps 1–5) and return
            the net adjustment plus structural-vacancy % for the caller.

            Steps handled here:
              1. Vacancy rent top-up (12 months max)
              2. Rent-free & void period deductions
              3. Leasing commission deduction
              4. Tenant fit-out deduction
              5. Under-rent / over-rent adjustment
              → net_adj = sum of above → added to last-12m NOI → Gross Stabilized NOI

            Steps handled by callers:
              6. Structural vacancy deduction (% of Gross Stabilized NOI)
              7. Terminal escalation
              8. Terminal value = Escalated NOI / Exit Yield

            Returns (net_adj, details_dict).
            """
            try:
                asset_sale_date = fn_get_asset_sale_date()
                if asset_sale_date is None:
                    return 0.0, {}

                vacancy_adj, reletting_adj, rent_adj = fn_compute_noi_stabilization_adjustment(asset_sale_date)

                # Read structural vacancy allowance (%):
                # Priority: NOIStabalizationAssumptions → ValuationParameters
                sv_pct = 0.0
                try:
                    val = Global.NOIStabalizationAssumptions.structural_vacancy_allowance
                    if val is not None and not pd.isna(val):
                        sv_pct = float(val)
                except (AttributeError, ValueError, TypeError):
                    pass
                if sv_pct <= 0:
                    try:
                        val = Global.ValuationParameters.structural_vacancy_allowance
                        if val is not None and not pd.isna(val):
                            sv_pct = float(val)
                    except (AttributeError, ValueError, TypeError):
                        pass
                if sv_pct > 1:
                    sv_pct = sv_pct / 100.0

                details = {
                    "vacancy_adjustment": vacancy_adj,
                    "reletting_adjustment": reletting_adj,
                    "rent_adjustment": rent_adj,
                    "structural_vacancy_pct": sv_pct,
                    "noi_topup_applied": True,
                }
                # Net adjustment = vacancy fill + re-letting costs + rent correction
                # (structural vacancy is applied later as % of gross stabilized NOI,
                #  not as a flat amount here)
                net_adj = vacancy_adj + reletting_adj + rent_adj

                print(f"  [NOI TOPUP] vacancy_adj={vacancy_adj:,.2f}  reletting_adj={reletting_adj:,.2f}  "
                      f"rent_adj={rent_adj:,.2f}  net_adj={net_adj:,.2f}  "
                      f"structural_vacancy_pct={sv_pct:.4f}")

                return net_adj, details

            except Exception as e:
                print(f"  [NOI TOPUP] EXCEPTION: {e}")
                import traceback; traceback.print_exc()
                return 0.0, {}


        def fn_get_acquisition_price():
            """Get acquisition price from acquisition module."""
            try:
                val = Global.AcquisitionModule.acquisition_price
                if val and not pd.isna(val):
                    return float(val)
                return 0
            except:
                return 0


        # =============================================================================
        # COMPUTE BASE RENT COLLECTIONS
        # =============================================================================

        def fn_compute_base_rent_collections():
            """
            Compute total base rent collections across all tenants.
            Service charges are already included in base rent collections.
            Returns: Series of monthly totals
            """
            # print("   Loading base rent collections...")
            # brm = _get_base_rent_module()
            
            # Ensure Module 03 has been run
            # if brm.base_rent_collections_monthly is None and brm.all_tenant_results is None:
            #     print("      ⏳ Running Module 03 (Base Rent)...")
            #     brm.fn_run_module_03()
            
            # Use the output DataFrame if available
            # if brm.base_rent_collections_monthly is not None:
            #     return pd.Series(brm.base_rent_collections_monthly.values.flatten(), index=range(_num_periods))
            
            # Otherwise compute from all_tenant_results
            total = np.zeros(_num_periods)
            if all_tenant_results is not None:
                for tenant_type in ["tenant1", "renewal", "tenant2"]:
                    if tenant_type in all_tenant_results:
                        collectible = all_tenant_results[tenant_type].get("collectible_rent")
                        if collectible is not None:
                            total += collectible.sum(axis=0).values
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE TOR COLLECTIONS
        # =============================================================================

        def fn_compute_tor_collections():
            """
            Compute total TOR collections across all tenants.
            Returns: Series of monthly totals
            """
            # print("   Loading TOR collections...")
            # tor_mod = _get_tor_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # Check if TOR output already exists
                # if tor_mod.turnover_rent_monthly is not None:
                #     return pd.Series(tor_mod.turnover_rent_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise run and compute
                tor_results, _ = fn_compute_all_turnover_rent()
                
                if "tenant1_and_renewal" in tor_results:
                    t1r_tor = tor_results["tenant1_and_renewal"]["turnover_rent"]
                    total += t1r_tor.sum(axis=0).values
                
                if "tenant2" in tor_results:
                    t2_tor = tor_results["tenant2"]["turnover_rent"]
                    total += t2_tor.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing TOR: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE SERVICE CHARGES
        # =============================================================================

        def fn_compute_service_charges():
            """
            Compute total service charges collected from Tenant Other Inputs module.
            Returns: Series of monthly totals
            """
            # print("   Loading service charges...")
            
            total = np.zeros(_num_periods)
            
            try:
                # fn_compute_all_tenant_other_inputs returns (results, renewal_flags)
                toi_results, _ = fn_compute_all_tenant_other_inputs()
                
                # Sum service charges for all tenants
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "service_charge" in toi_results[tenant_key]:
                        sc = toi_results[tenant_key]["service_charge"]
                        if isinstance(sc, pd.DataFrame):
                            sc_sum = sc.sum(axis=0).values
                            total += sc_sum
                        elif isinstance(sc, pd.Series):
                            total += sc.values
                            # print(f"      {tenant_key} service_charge: {sc.sum():,.2f}")
                # print(f"      Total service charges: {total.sum():,.2f}")
            except Exception as e:
                import traceback
                print(f"   ⚠️ Error computing service charges: {e}")
                print(f"   {traceback.format_exc()}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE LEASING COMMISSIONS
        # =============================================================================

        def fn_compute_leasing_commissions():
            """
            Compute leasing commissions from Tenant Other Inputs module.
            Returns: Series of monthly totals
            """
            # print("   Loading leasing commissions...")
            
            total = np.zeros(_num_periods)
            
            try:
                # fn_compute_all_tenant_other_inputs returns (results, renewal_flags)
                toi_results, _ = fn_compute_all_tenant_other_inputs()
                
                # Sum leasing commissions for all tenants
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "leasing_commission" in toi_results[tenant_key]:
                        lc = toi_results[tenant_key]["leasing_commission"]
                        if isinstance(lc, pd.DataFrame):
                            lc_sum = lc.sum(axis=0).values
                            total += lc_sum
                            # print(f"      {tenant_key} leasing_commission: {lc_sum.sum():,.2f}")
                        elif isinstance(lc, pd.Series):
                            total += lc.values
                            # print(f"      {tenant_key} leasing_commission: {lc.sum():,.2f}")
                # print(f"      Total leasing commissions: {total.sum():,.2f}")
            except Exception as e:
                import traceback
                print(f"   ⚠️ Error computing leasing commissions: {e}")
                print(f"   {traceback.format_exc()}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE OPERATING EXPENSES
        # =============================================================================

        def fn_compute_total_opex():
            """
            Compute total operating expenses (all categories).
            Returns: Series of monthly totals
            """
            # print("   Loading operating expenses...")
            # opex_mod = _get_opex_module()
            
            total = np.zeros(_num_periods)
            
            try:
                opex_results = fn_compute_all_operating_expenses()
                
                for category, data in opex_results.items():
                    if isinstance(data, pd.Series):
                        total += data.values
                    elif isinstance(data, pd.DataFrame):
                        total += data.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing OPEX: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE TENANT FIT OUT CHARGES
        # =============================================================================

        def fn_compute_tenant_fitout():
            """
            Compute tenant fit out charges from Tenant Other Inputs module.
            Returns: Series of monthly totals
            """
            # print("   Loading tenant fit out charges...")
            # toi_mod = _get_tenant_other_inputs_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # First, check if output DataFrame already exists
                # if toi_mod.tenant_fitout_allowance_monthly is not None:
                #     return pd.Series(toi_mod.tenant_fitout_allowance_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute - function returns (results, renewal_flags) tuple
                toi_results, _ = fn_compute_all_tenant_other_inputs()
                
                # Sum tenant fitout for all tenants
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "tenant_fitout" in toi_results[tenant_key]:
                        tfo = toi_results[tenant_key]["tenant_fitout"]
                        if isinstance(tfo, pd.DataFrame):
                            total += tfo.sum(axis=0).values
                        elif isinstance(tfo, pd.Series):
                            total += tfo.values
            except Exception as e:
                print(f"   ⚠️ Error computing tenant fit out: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE MAINTENANCE CAPEX
        # =============================================================================

        # def fn_compute_maintenance_capex():
        #     """
        #     Compute total maintenance capex.
        #     Returns: Series of monthly totals
        #     """
        #     print("   Loading maintenance capex...")
        #     # mcapex_mod = _get_maintenance_capex_module()
            
        #     total = np.zeros(_num_periods)
            
        #     try:
        #         # First, check if output DataFrame already exists
        #         # if mcapex_mod.total_maintenance_capex_monthly is not None:
        #         #     return pd.Series(mcapex_mod.total_maintenance_capex_monthly.values.flatten(), index=range(_num_periods))
                
        #         mcapex_results = fn_compute_all_maintenance_capex_and_sinking_fund()
                
        #         if "total_maintenance_capex" in mcapex_results:
        #             total += mcapex_results["total_maintenance_capex"].values

        #         print(f"      ✅ Maintenance CapEx loaded successfully.")

        #     except Exception as e:
        #         print(f"   ⚠️ Error computing maintenance capex: {e}")
            
        #     return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE SINKING FUND
        # =============================================================================

        # def fn_compute_sinking_fund():
        #     """
        #     Compute sinking fund.
        #     Returns: Series of monthly totals
        #     """
        #     print("   Loading sinking fund...")
        #     # mcapex_mod = _get_maintenance_capex_module()
            
        #     total = np.zeros(_num_periods)
            
        #     try:
        #         # First, check if output DataFrame already exists
        #         # if mcapex_mod.sinking_fund_monthly is not None:
        #         #     return pd.Series(mcapex_mod.sinking_fund_monthly.values.flatten(), index=range(_num_periods))
                
        #         mcapex_results = fn_compute_all_maintenance_capex_and_sinking_fund()
                
        #         if "sinking_fund" in mcapex_results:
        #             total += mcapex_results["sinking_fund"].values
        #     except Exception as e:
        #         print(f"   ⚠️ Error computing sinking fund: {e}")
            
        #     return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE PARKING REVENUE & EXPENSE
        # =============================================================================

        def fn_get_parking_revenue_for_valuation():
            """Compute parking revenue from Other Income Expenses module."""
            # print("   Loading parking revenue...")
            # oie_mod = _get_other_income_expenses_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if oie_mod.parking_revenue_monthly is not None:
                #     return pd.Series(oie_mod.parking_revenue_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute
                oie_results, _ = fn_compute_all_other_income_expenses()
                
                # Module 07 returns nested structure: results["parking"]["revenue"]
                if "parking" in oie_results and oie_results["parking"]["revenue"] is not None:
                    pr = oie_results["parking"]["revenue"]
                    if isinstance(pr, pd.Series):
                        total += pr.values
                    elif isinstance(pr, pd.DataFrame):
                        total += pr.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing parking revenue: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        def fn_get_parking_expense_for_valuation():
            """Compute parking expense from Other Income Expenses module."""
            # print("   Loading parking expense...")
            # oie_mod = _get_other_income_expenses_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if oie_mod.parking_opex_monthly is not None:
                #     return pd.Series(oie_mod.parking_opex_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute
                oie_results, _ = fn_compute_all_other_income_expenses()
                
                # Module 07 returns nested structure: results["parking"]["opex"]
                if "parking" in oie_results and oie_results["parking"]["opex"] is not None:
                    pe = oie_results["parking"]["opex"]
                    if isinstance(pe, pd.Series):
                        total += pe.values
                    elif isinstance(pe, pd.DataFrame):
                        total += pe.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing parking expense: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        # =============================================================================
        # COMPUTE OTHER INCOME & EXPENSES
        # =============================================================================

        def fn_get_other_income_for_valuation():
            """Compute other income from Other Income Expenses module."""
            # print("   Loading other income...")
            # oie_mod = _get_other_income_expenses_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if oie_mod.total_other_income_monthly is not None:
                #     return pd.Series(oie_mod.total_other_income_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute
                oie_results, _ = fn_compute_all_other_income_expenses()
                
                # Module 07 returns nested structure: results["other_income"]["other_income_1"], etc.
                if "other_income" in oie_results:
                    oi_dict = oie_results["other_income"]
                    for item_key in ["other_income_1", "other_income_2", "other_income_3"]:
                        if item_key in oi_dict and oi_dict[item_key] is not None:
                            item = oi_dict[item_key]
                            if isinstance(item, pd.Series):
                                total += item.values
                            elif isinstance(item, pd.DataFrame):
                                total += item.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing other income: {e}")
            
            return pd.Series(total, index=range(_num_periods))


        def fn_get_other_expenses_for_valuation():
            """Compute other expenses from Other Income Expenses module."""
            # print("   Loading other expenses...")
            # oie_mod = _get_other_income_expenses_module()
            
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if oie_mod.total_other_expenses_monthly is not None:
                #     return pd.Series(oie_mod.total_other_expenses_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute
                oie_results, _ = fn_compute_all_other_income_expenses()
                
                # Module 07 returns nested structure: results["other_expenses"]["other_expense_1"], etc.
                if "other_expenses" in oie_results:
                    oe_dict = oie_results["other_expenses"]
                    for item_key in ["other_expense_1", "other_expense_2", "other_expense_3"]:
                        if item_key in oe_dict and oe_dict[item_key] is not None:
                            item = oe_dict[item_key]
                            if isinstance(item, pd.Series):
                                total += item.values
                            elif isinstance(item, pd.DataFrame):
                                total += item.sum(axis=0).values
            except Exception as e:
                print(f"   ⚠️ Error computing other expenses: {e}")
            
            return pd.Series(total, index=range(_num_periods))

        # Aliases for backward compatibility
        fn_compute_parking_expense = fn_get_parking_expense_for_valuation
        fn_compute_other_income = fn_get_other_income_for_valuation
        fn_compute_other_expenses = fn_get_other_expenses_for_valuation


        # =============================================================================
        # COMPUTE NOI (NET OPERATING INCOME)
        # =============================================================================

        def fn_compute_noi_for_valuation():
            """
            Compute NOI (Net Operating Income) per period for valuation.
            
            NOI = Gross Rent + Service Charges - Leasing Commissions
                - Operating Expenses (incl Sinking Fund)
                + Parking Revenue - Parking Expense
            
            Returns: Series of monthly NOI, components dict
            """

            # ---- Parallel Core Computations ----
            task_funcs = {
                "base_rent": fn_compute_base_rent_collections,
                "service_charges": fn_compute_service_charges,
                "tor": fn_compute_tor_collections,
                "leasing_commissions": fn_compute_leasing_commissions,
                "opex": fn_compute_total_opex,
            }

            max_workers = _cap_workers(min(5, len(task_funcs)))

            if _is_parallel_active() or max_workers <= 1:
                results = {name: func() for name, func in task_funcs.items()}
            else:
                with _parallel_section():
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {name: executor.submit(func) for name, func in task_funcs.items()}
                        results = {name: future.result() for name, future in futures.items()}

            # Revenue
            base_rent = results["base_rent"]
            service_charges = results["service_charges"]
            tor = results["tor"]

            # Gross Rent
            gross_rent = base_rent + tor

            # Expenses
            leasing_commissions = results["leasing_commissions"]
            opex = results["opex"]

            # ---- Sequential (kept same logic with try/except) ----

            try:
                sinking_fund = fn_compute_sinking_fund()
            except Exception:
                sinking_fund = pd.Series(np.zeros(_num_periods), index=range(_num_periods))

            total_expenses = opex + sinking_fund

            try:
                parking_revenue = fn_compute_parking_revenue()
            except Exception:
                parking_revenue = pd.Series(np.zeros(_num_periods), index=range(_num_periods))

            try:
                parking_expense = fn_get_parking_expense_for_valuation()
            except Exception:
                parking_expense = pd.Series(np.zeros(_num_periods), index=range(_num_periods))

            # NOI calculation (UNCHANGED)
            noi = (
                gross_rent
                + service_charges
                - leasing_commissions
                - total_expenses
                + parking_revenue
                - parking_expense
            )

            return noi, {
                "base_rent": base_rent,
                "service_charges": service_charges,
                "tor": tor,
                "gross_rent": gross_rent,
                "leasing_commissions": leasing_commissions,
                "opex": opex,
                "sinking_fund": sinking_fund,
                "total_expenses": total_expenses,
                "parking_revenue": parking_revenue,
                "parking_expense": parking_expense,
            }



        # =============================================================================
        # COMPUTE ASSET SALE VALUE
        # =============================================================================

        def fn_compute_asset_sale_value(noi_series, noi_components=None):
            """
            Compute Asset Sale Value (Net Asset Sale Value).

            New logic:
              1. Last 12m NOI from actual cashflows
              2. + Vacancy adjustment (vacant units filled at escalated market rent)
              3. + Rent adjustment (under-rent/over-rent vs market rent)
              = Gross Stabilized NOI
              4. − Structural vacancy deduction (% of Gross Stabilized NOI)
              = Net Stabilized NOI
              5. × (1 + terminal_value_escalation_factor)
              = Escalated NOI
              6. / exit_yield = Gross Asset Sale Value
              7. − disposal fees
              = Net Asset Sale Value

            Returns: (asset_sale_value, details_dict)
            """
            asset_sale_date = fn_get_asset_sale_date()
            if asset_sale_date is None:
                return 0, {}

            exit_yield = fn_get_exit_yield()
            if exit_yield <= 0:
                return 0, {}

            # Disposal cost %
            disposal_cost_pct = 0
            try:
                val = Global.ValuationParameters.disposal_cost
                if val and not pd.isna(val):
                    disposal_cost_pct = float(val)
                    if disposal_cost_pct > 1:
                        disposal_cost_pct = disposal_cost_pct / 100.0
            except Exception:
                pass

            # Helper: sum last 12 monthly values before/at asset_sale_date
            def get_last_12m_sum(series):
                last_idx = -1
                for col_idx in range(_num_periods - 1, -1, -1):
                    if _period_starts_ts[col_idx] <= asset_sale_date:
                        last_idx = col_idx
                        break
                if last_idx < 0:
                    return 0
                start_idx = max(0, last_idx - 11)
                return float(series.iloc[start_idx:last_idx + 1].sum())

            last_12m_noi = get_last_12m_sum(noi_series)

            # --- NOI stabilization (Steps 1–5) — only when toggle is Yes ---
            topup_toggle = str(Global.ValuationParameters.noi_top_up or "").strip().lower() in ["yes", "true", "1"]
            if topup_toggle:
                noi_adj, adj_details = fn_get_noi_topup()
            else:
                noi_adj, adj_details = 0.0, {"noi_topup_applied": False, "structural_vacancy_pct": 0.0}
                print(f"  [NOI TOPUP] Toggle is OFF — skipping NOI top-up")
            gross_stabilized_noi = last_12m_noi + noi_adj

            # --- Step 6: Structural vacancy deduction ---
            sv_pct = adj_details.get("structural_vacancy_pct", 0.0)
            structural_vacancy_deduction = sv_pct * gross_stabilized_noi
            net_stabilized_noi = gross_stabilized_noi - structural_vacancy_deduction

            # --- Step 7: Terminal value escalation ---
            escalation_factor = 0.0
            try:
                val = Global.ValuationParameters.terminal_year_noi_escalation
                if val is not None and not pd.isna(val):
                    escalation_factor = float(val)
                    if escalation_factor > 1:
                        escalation_factor = escalation_factor / 100.0
            except (ValueError, TypeError):
                pass
            if escalation_factor == 0:
                try:
                    val = Global.ValuationParameters.terminal_value_escalation_factor
                    if val is not None and not pd.isna(val):
                        escalation_factor = float(val)
                except (ValueError, TypeError):
                    pass

            escalated_noi = net_stabilized_noi * (1 + escalation_factor)

            # --- Step 8: Terminal value ---
            gross_asset_sale_value = escalated_noi / exit_yield
            disposal_fees = gross_asset_sale_value * disposal_cost_pct
            asset_sale_value = gross_asset_sale_value - disposal_fees

            # --- Full NOI Waterfall Debug ---
            vac = adj_details.get("vacancy_adjustment", 0)
            relet = adj_details.get("reletting_adjustment", 0)
            rent = adj_details.get("rent_adjustment", 0)
            print(f"")
            print(f"  ╔══ NET ASSET SALE VALUE — FULL WATERFALL ═══════════════")
            print(f"  ║  Last 12-Month NOI          : {last_12m_noi:,.2f}")
            print(f"  ║  + Step 1  Vacancy Top-Up    : {vac:,.2f}")
            print(f"  ║  - Steps2-4 Re-letting Costs : {relet:,.2f}")
            print(f"  ║  +/- Step 5 Rent Adjustment  : {rent:,.2f}")
            print(f"  ║  = Gross Stabilized NOI      : {gross_stabilized_noi:,.2f}")
            print(f"  ║  - Step 6  Structural Vacancy: {sv_pct:.4f} × {gross_stabilized_noi:,.2f} = {structural_vacancy_deduction:,.2f}")
            print(f"  ║  = Net Stabilized NOI        : {net_stabilized_noi:,.2f}")
            print(f"  ║  × Step 7  Escalation (1+{escalation_factor:.4f})")
            print(f"  ║  = Escalated NOI             : {escalated_noi:,.2f}")
            print(f"  ║  ÷ Step 8  Exit Yield        : {exit_yield:.4f}")
            print(f"  ║  = Gross Asset Sale Value    : {gross_asset_sale_value:,.2f}")
            print(f"  ║  - Disposal Fees ({disposal_cost_pct:.4f})    : {disposal_fees:,.2f}")
            print(f"  ║  = Net Asset Sale Value      : {asset_sale_value:,.2f}")
            print(f"  ╚═════════════════════════════════════════════════════")

            return asset_sale_value, {
                "last_12m_noi": last_12m_noi,
                "vacancy_adjustment": vac,
                "reletting_adjustment": relet,
                "rent_adjustment": rent,
                "noi_topup_applied": adj_details.get("noi_topup_applied", noi_adj != 0),
                "gross_stabilized_noi": gross_stabilized_noi,
                "structural_vacancy_pct": sv_pct,
                "structural_vacancy_deduction": structural_vacancy_deduction,
                "net_stabilized_noi": net_stabilized_noi,
                "escalation_factor": escalation_factor,
                "escalated_noi": escalated_noi,
                "exit_yield": exit_yield,
                "gross_asset_sale_value": gross_asset_sale_value,
                "disposal_cost_pct": disposal_cost_pct,
                "disposal_fees": disposal_fees,
            }


        # =============================================================================
        # COMPUTE NET OPERATING CASHFLOWS
        # =============================================================================

        def fn_compute_net_operating_cashflows(noi_series, asset_sale_value):
            """
            Compute Net Operating Cashflows per period (used for valuation PV).
            
            NOI already includes: Gross Rent + SC - LC - Total OPEX (incl sinking fund) 
                                + Parking Revenue - Parking Expense
            
            Net CF = NOI + Other Income - Other Expenses - Maintenance CapEx - Tenant Fitout + Asset Sale
            
            Returns: Series of monthly net cashflows, components dict
            """

            # ---- Parallelizable independent fetches ----
            task_funcs = {
                "other_income": fn_get_other_income_for_valuation,
                "other_expenses": fn_get_other_expenses_for_valuation,
                "maintenance_capex": fn_get_maintenance_capex,
                "tenant_fitout": fn_get_tenant_fitout,
            }

            max_workers = _cap_workers(min(4, len(task_funcs)))

            if _is_parallel_active() or max_workers <= 1:
                results = {}
                for name, func in task_funcs.items():
                    try:
                        results[name] = func()
                    except Exception:
                        results[name] = None
            else:
                with _parallel_section():
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {name: executor.submit(func) for name, func in task_funcs.items()}
                        results = {}
                        for name, future in futures.items():
                            try:
                                results[name] = future.result()
                            except Exception:
                                results[name] = None

            # ---- Apply original fallback logic (UNCHANGED behavior) ----

            other_income = (
                results["other_income"]
                if isinstance(results["other_income"], pd.Series)
                else pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            )

            other_expenses = (
                results["other_expenses"]
                if isinstance(results["other_expenses"], pd.Series)
                else pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            )

            # Maintenance CapEx aggregation (same logic as before)
            if isinstance(results["maintenance_capex"], dict):
                total_mcapex = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                for key in results["maintenance_capex"]:
                    total_mcapex += results["maintenance_capex"][key]
            else:
                total_mcapex = pd.Series(np.zeros(_num_periods), index=range(_num_periods))

            tenant_fitout = (
                results["tenant_fitout"]
                if isinstance(results["tenant_fitout"], pd.Series)
                else pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            )

            # ---- Asset Sale (kept sequential exactly as original) ----

            asset_sale_cf = np.zeros(_num_periods)
            asset_sale_date = fn_get_asset_sale_date()

            if asset_sale_date is not None:
                for col_idx in range(_num_periods):
                    period_start = _period_starts_ts[col_idx]
                    period_end = _period_ends_ts[col_idx]
                    if period_start <= asset_sale_date <= period_end:
                        asset_sale_cf[col_idx] = asset_sale_value
                        break

            asset_sale_cf = pd.Series(asset_sale_cf, index=range(_num_periods))

            # ---- Net Cashflow calculation (UNCHANGED) ----

            net_cf = (
                noi_series
                + other_income
                - other_expenses
                - total_mcapex
                - tenant_fitout
                + asset_sale_cf
            )

            return net_cf, {
                "other_income": other_income,
                "other_expenses": other_expenses,
                "maintenance_capex": total_mcapex,
                "tenant_fitout": tenant_fitout,
                "asset_sale_cf": asset_sale_cf,
            }



        # =============================================================================
        # COMPUTE ACQUISITION COSTS
        # =============================================================================

        def fn_get_all_acquisition_costs():
            """
            Get all acquisition cost components from AcquisitionModule.
            Transaction costs are stored as percentages and multiplied by acquisition price.
            
            Returns: Dictionary with each cost component and total
            """
            costs = {}
            
            # Acquisition Price
            val = Global.AcquisitionModule.acquisition_price
            acquisition_price = float(val) if val and not pd.isna(val) else 0
            costs["acquisition_price"] = acquisition_price
            
            # Transfer Tax / Stamp Duty (percentage of acquisition price)
            val = Global.AcquisitionModule.transfer_tax__stamp_duty
            transfer_tax_pct = float(val) if val and not pd.isna(val) else 0
            costs["transfer_tax_pct"] = transfer_tax_pct
            costs["transfer_tax"] = acquisition_price * transfer_tax_pct
            
            # Legal Fees (percentage of acquisition price)
            val = Global.AcquisitionModule.legal_fees
            legal_fees_pct = float(val) if val and not pd.isna(val) else 0
            costs["legal_fees_pct"] = legal_fees_pct
            costs["legal_fees"] = acquisition_price * legal_fees_pct
            
            # Brokerage (percentage of acquisition price)
            val = Global.AcquisitionModule.brokerage
            brokerage_pct = float(val) if val and not pd.isna(val) else 0
            costs["brokerage_pct"] = brokerage_pct
            costs["brokerage"] = acquisition_price * brokerage_pct
            
            # Due Diligence Costs (percentage of acquisition price)
            val = Global.AcquisitionModule.due_diligence_costs
            due_diligence_pct = float(val) if val and not pd.isna(val) else 0
            costs["due_diligence_pct"] = due_diligence_pct
            costs["due_diligence"] = acquisition_price * due_diligence_pct
            
            # Total Transaction Costs (sum of all costs excluding acquisition price itself)
            costs["total_transaction_costs"] = (
                costs["transfer_tax"] +
                costs["legal_fees"] +
                costs["brokerage"] +
                costs["due_diligence"]
            )
            
            # Grand Total (acquisition price + all transaction costs)
            costs["total"] = costs["acquisition_price"] + costs["total_transaction_costs"]
            
            return costs


        def fn_get_acquisition_transaction_dates():
            """
            Get transaction dates for each acquisition cost component.
            Returns: Dictionary with dates
            """
            dates = {}
            
            def parse_date(val):
                if val and not pd.isna(val):
                    return pd.to_datetime(val)
                return None
            
            dates["acquisition_price"] = parse_date(Global.AcquisitionModule.acquisition_price_transaction_date)
            dates["transfer_tax"] = parse_date(Global.AcquisitionModule.transfer_tax__stamp_duty_transaction_date)
            dates["legal_fees"] = parse_date(Global.AcquisitionModule.legal_fees_transaction_date)
            dates["brokerage"] = parse_date(Global.AcquisitionModule.brokerage_transaction_date)
            dates["due_diligence"] = parse_date(Global.AcquisitionModule.due_diligence_costs_transaction_date)
            
            return dates


        # =============================================================================
        # COMPUTE ACQUISITION PRICE
        # =============================================================================

        def fn_compute_acquisition_price(net_cf_series, asset_sale_value_amount=0, asset_sale_date_ts=None):
            """
            Compute Acquisition Price and Total Acquisition Transaction Costs.
            
            For BOTH Investment and Valuation:
            - Acquisition Price: Either from inputs (Investment) or PV of Net CF (Valuation)
            - Acquisition Costs: Sum of (acquisition_price + transfer_tax + legal_fees + brokerage + due_diligence)
            
            Discounting:
            - Cashflows on/before acquisition_date: Taken as is (no discounting)
            - Cashflows after acquisition_date: Discounted using discount_rate to acquisition_date
            
            Returns: Acquisition price, analysis details
            """
            # print("\n📊 Computing Acquisition Price and Costs...")
            
            analysis_type = fn_get_analysis_type()
            acquisition_date = fn_get_acquisition_date()
            discount_rate = fn_get_discount_rate()
            
            # print(f"   Analysis Type: {analysis_type}")
            # print(f"   Analysis Date: {acquisition_date.strftime('%Y-%m-%d') if acquisition_date else 'Not defined'}")
            # print(f"   Discount Rate: {discount_rate:.2%}")
            
            # Get all acquisition costs
            acq_costs = fn_get_all_acquisition_costs()
            acq_dates = fn_get_acquisition_transaction_dates()
            
            # print(f"\n   Acquisition Cost Components:")
            # print(f"      Acquisition Price:        {acq_costs['acquisition_price']:>15,.2f}")
            # print(f"      Transfer Tax ({acq_costs['transfer_tax_pct']:.2%}):      {acq_costs['transfer_tax']:>15,.2f}")
            # print(f"      Legal Fees ({acq_costs['legal_fees_pct']:.2%}):        {acq_costs['legal_fees']:>15,.2f}")
            # print(f"      Brokerage ({acq_costs['brokerage_pct']:.2%}):         {acq_costs['brokerage']:>15,.2f}")
            # print(f"      Due Diligence ({acq_costs['due_diligence_pct']:.2%}):    {acq_costs['due_diligence']:>15,.2f}")
            # print(f"      --------------------------------------")
            # print(f"      Total Transaction Costs:  {acq_costs['total_transaction_costs']:>15,.2f}")
            # print(f"      Grand Total:              {acq_costs['total']:>15,.2f}")
            
            # Calculate present value of net operating cashflows using 30/360 yearfrac
            # net_cf_series should NOT include asset sale (it's discounted separately)
            # All CFs assumed to incur at month-end; yearfrac uses 30/360 convention
            pv_cashflows = np.zeros(_num_periods)
            undiscounted_cf = np.zeros(_num_periods)
            discounted_cf = np.zeros(_num_periods)
            
            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                period_end = _period_ends_ts[col_idx]
                cf = net_cf_series.iloc[col_idx]
                
                if acquisition_date is None:
                    pv_cashflows[col_idx] = cf
                    undiscounted_cf[col_idx] = cf
                elif period_start <= acquisition_date:
                    # Pre-acquisition or acquisition period: include undiscounted
                    pv_cashflows[col_idx] = cf
                    undiscounted_cf[col_idx] = cf
                else:
                    # Monthly CFs: discount using 30/360 yearfrac from acquisition_date to period_end
                    year_fraction = yearfrac_30_360(acquisition_date, period_end)
                    discount_factor = 1 / ((1 + discount_rate) ** year_fraction)
                    
                    pv_cashflows[col_idx] = cf * discount_factor
                    discounted_cf[col_idx] = cf * discount_factor
            
            pv_monthly = pv_cashflows.sum()
            
            # TEMP: Print discounted CFs per month (commented out to reduce log noise)
            # print("\n" + "=" * 90)
            # print("DISCOUNTED CFs (fn_compute_acquisition_price)")
            # print(f"{'Month':<12} {'Period End':<14} {'YearFrac':>10} {'Undiscounted CF':>18} {'Discounted CF':>18}")
            # print("-" * 90)
            # for col_idx in range(_num_periods):
            #     pe = _period_ends_ts[col_idx]
            #     yf = yearfrac_30_360(acquisition_date, pe) if acquisition_date and pe > acquisition_date else 0.0
            #     print(f"{col_idx+1:<12} {pe.strftime('%Y-%m-%d'):<14} {yf:>10.5f} {net_cf_series.iloc[col_idx]:>18,.2f} {pv_cashflows[col_idx]:>18,.2f}")
            # print("-" * 90)
            # print(f"{'TOTAL':<12} {'':14} {'':>10} {net_cf_series.sum():>18,.2f} {pv_monthly:>18,.2f}")
            # print("=" * 90)
            # END TEMP
            
            # Discount Asset Sale using 30/360 yearfrac from acquisition_date to asset_sale_date
            pv_asset_sale = 0
            if asset_sale_value_amount > 0 and asset_sale_date_ts is not None and acquisition_date is not None:
                yf_sale = yearfrac_30_360(acquisition_date, asset_sale_date_ts)
                if yf_sale > 0:
                    df_sale = 1 / ((1 + discount_rate) ** yf_sale)
                    pv_asset_sale = asset_sale_value_amount * df_sale
                else:
                    pv_asset_sale = asset_sale_value_amount
            elif asset_sale_value_amount > 0:
                pv_asset_sale = asset_sale_value_amount
            
            total_pv = pv_monthly + pv_asset_sale
            
            # Determine acquisition price based on analysis type
            # print(f"\n   DEBUG: analysis_type = '{analysis_type}', type = {type(analysis_type)}")
            
            # Normalize analysis type - check for investment explicitly
            analysis_type_lower = str(analysis_type).lower().strip() if analysis_type else ""
            is_investment = analysis_type_lower == "investment"
            is_valuation = analysis_type_lower == "valuation" or not is_investment
            
            # print(f"   DEBUG: analysis_type_lower = '{analysis_type_lower}'")
            # print(f"   DEBUG: is_investment = {is_investment}, is_valuation = {is_valuation}")
            
            if is_investment:
                acquisition_price = acq_costs["acquisition_price"]
                # print(f"\n   📌 Analysis Type = Investment")
                # print(f"   💰 Acquisition Price (from inputs): {acquisition_price:,.2f}")
                # Use input-based transaction costs for investment
                final_acq_costs = acq_costs
            else:
                # Valuation - use PV of cashflows as acquisition price
                acquisition_price = total_pv
                # print(f"\n   📌 Analysis Type = Valuation")
                # print(f"   💰 Computed Acquisition Price (PV): {acquisition_price:,.2f}")
                
                # Recalculate transaction costs based on computed acquisition price
                final_acq_costs = {
                    "acquisition_price": acquisition_price,
                    "transfer_tax_pct": acq_costs["transfer_tax_pct"],
                    "transfer_tax": acquisition_price * acq_costs["transfer_tax_pct"],
                    "legal_fees_pct": acq_costs["legal_fees_pct"],
                    "legal_fees": acquisition_price * acq_costs["legal_fees_pct"],
                    "brokerage_pct": acq_costs["brokerage_pct"],
                    "brokerage": acquisition_price * acq_costs["brokerage_pct"],
                    "due_diligence_pct": acq_costs["due_diligence_pct"],
                    "due_diligence": acquisition_price * acq_costs["due_diligence_pct"],
                }
                final_acq_costs["total_transaction_costs"] = (
                    final_acq_costs["transfer_tax"] +
                    final_acq_costs["legal_fees"] +
                    final_acq_costs["brokerage"] +
                    final_acq_costs["due_diligence"]
                )
                final_acq_costs["total"] = acquisition_price + final_acq_costs["total_transaction_costs"]
                
                # print(f"\n   Recalculated Transaction Costs (based on computed acquisition price):")
                # print(f"      Transfer Tax ({final_acq_costs['transfer_tax_pct']:.2%}):      {final_acq_costs['transfer_tax']:>15,.2f}")
                # print(f"      Legal Fees ({final_acq_costs['legal_fees_pct']:.2%}):        {final_acq_costs['legal_fees']:>15,.2f}")
                # print(f"      Brokerage ({final_acq_costs['brokerage_pct']:.2%}):         {final_acq_costs['brokerage']:>15,.2f}")
                # print(f"      Due Diligence ({final_acq_costs['due_diligence_pct']:.2%}):    {final_acq_costs['due_diligence']:>15,.2f}")
                # print(f"      Total Transaction Costs:  {final_acq_costs['total_transaction_costs']:>15,.2f}")
            
            # Total acquisition transaction costs
            total_acq_transaction_costs = final_acq_costs["total"]
            # print(f"   💰 Total Acquisition Transaction Costs: {total_acq_transaction_costs:,.2f}")
            
            return acquisition_price, {
                "analysis_type": analysis_type,
                "acquisition_date": acquisition_date,
                "discount_rate": discount_rate,
                "pv_cashflows": pd.Series(pv_cashflows, index=range(_num_periods)),
                "total_pv": total_pv,
                "acquisition_costs": final_acq_costs,
                "acquisition_dates": acq_dates,
                "total_acquisition_transaction_costs": total_acq_transaction_costs,
            }


        # =============================================================================
        # MAIN COMPUTATION FUNCTION
        # =============================================================================

        def fn_compute_valuation():
            """
            Main function to compute valuation.
            
            Returns: Dictionary with all valuation results
            """
            # print("=" * 80)
            # print("COMPUTING VALUATION")
            # print("=" * 80)
            
            # Step 1: Compute NOI
            noi_series, noi_components = fn_compute_noi_for_valuation()
            
            # Step 2: Compute Asset Sale Value (pass components for Indirect escalation)
            asset_sale_value, sale_details = fn_compute_asset_sale_value(noi_series, noi_components)
            
            # Step 3: Compute Net Operating Cashflows (includes CapEx and Fitout, but NOT asset sale)
            net_cf_series, cf_components = fn_compute_net_operating_cashflows(noi_series, asset_sale_value)
            
            # Build monthly CF series WITHOUT asset sale (asset sale discounted separately)
            monthly_cf_no_sale = (
                net_cf_series - cf_components.get("asset_sale_cf", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
            )
            
            # Step 4: Compute Acquisition Price (monthly CFs discounted by period_end, asset sale by sale_date)
            asset_sale_date_for_disc = fn_get_asset_sale_date()
            acquisition_price, acq_details = fn_compute_acquisition_price(
                monthly_cf_no_sale, asset_sale_value, asset_sale_date_for_disc
            )
            
            return {
                "noi_series": noi_series,
                "noi_components": noi_components,
                "asset_sale_value": asset_sale_value,
                "sale_details": sale_details,
                "net_cf_series": net_cf_series,
                "cf_components": cf_components,
                "acquisition_price": acquisition_price,
                "acquisition_details": acq_details,
            }


        # =============================================================================
        # EXPORT FUNCTION
        # =============================================================================

        def fn_export_to_excel(results, output_file=None):
            """Export valuation results to Excel."""
            if output_file is None:
                output_file = os.path.join(os.path.dirname(__file__), "Valuation_Output.xlsx")
            
            # Create month headers
            month_headers = [_period_starts_ts[i].strftime("%Y-%m") for i in range(_num_periods)]
            
            # Prepare NOI data
            noi_data = []
            noi_comp = results["noi_components"]
            
            for name, series in [
                ("Base Rent", noi_comp["base_rent"]),
                ("Service Charges", noi_comp["service_charges"]),
                ("TOR", noi_comp["tor"]),
                ("Gross Rent", noi_comp["gross_rent"]),
                ("Leasing Commissions", noi_comp["leasing_commissions"]),
                ("Operating Expenses", noi_comp["opex"]),
                ("Sinking Fund", noi_comp["sinking_fund"]),
                ("Total Expenses", noi_comp["total_expenses"]),
                ("Parking Revenue", noi_comp["parking_revenue"]),
                ("Parking Expense", noi_comp["parking_expense"]),
                ("NOI", results["noi_series"]),
            ]:
                row = {"Line Item": name}
                for col_idx in range(_num_periods):
                    row[month_headers[col_idx]] = series.iloc[col_idx]
                row["Total"] = series.sum()
                noi_data.append(row)
            
            df_noi = pd.DataFrame(noi_data)
            
            # Prepare Net Cashflows data
            cf_data = []
            cf_comp = results["cf_components"]
            
            for name, series in [
                ("NOI", results["noi_series"]),
                ("Other Income", cf_comp["other_income"]),
                ("Other Expenses", cf_comp["other_expenses"]),
                ("Asset Sale", cf_comp["asset_sale_cf"]),
                ("Net Operating Cashflows", results["net_cf_series"]),
            ]:
                row = {"Line Item": name}
                for col_idx in range(_num_periods):
                    row[month_headers[col_idx]] = series.iloc[col_idx]
                row["Total"] = series.sum()
                cf_data.append(row)
            
            df_cf = pd.DataFrame(cf_data)
            
            # Prepare Summary
            acq_costs = results["acquisition_details"].get("acquisition_costs", {})
            summary_data = [
                {"Metric": "Asset Sale Price", "Value": results["asset_sale_value"]},
                {"Metric": "Acquisition Price", "Value": results["acquisition_price"]},
                {"Metric": "Transfer Tax / Stamp Duty", "Value": acq_costs.get("transfer_tax", 0)},
                {"Metric": "Legal Fees", "Value": acq_costs.get("legal_fees", 0)},
                {"Metric": "Brokerage", "Value": acq_costs.get("brokerage", 0)},
                {"Metric": "Due Diligence Costs", "Value": acq_costs.get("due_diligence", 0)},
                {"Metric": "Total Acquisition Costs", "Value": acq_costs.get("total", 0)},
                {"Metric": "Last 12 Months NOI", "Value": results["sale_details"].get("last_12_months_noi", 0)},
                {"Metric": "NOI Escalation", "Value": results["sale_details"].get("noi_escalation", 0)},
                {"Metric": "Escalated NOI", "Value": results["sale_details"].get("escalated_noi", 0)},
                {"Metric": "NOI Top-up Applied", "Value": "Yes" if results["sale_details"].get("noi_topup_applied") else "No"},
                {"Metric": "NOI for Valuation", "Value": results["sale_details"].get("noi_for_valuation", 0)},
                {"Metric": "Exit Yield", "Value": results["sale_details"].get("exit_yield", 0)},
                {"Metric": "Discount Rate", "Value": results["acquisition_details"].get("discount_rate", 0)},
                {"Metric": "Analysis Type", "Value": results["acquisition_details"].get("analysis_type", "")},
            ]
            
            df_summary = pd.DataFrame(summary_data)
            
            # Export to Excel
            with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                df_noi.to_excel(writer, sheet_name="NOI", index=False)
                df_cf.to_excel(writer, sheet_name="Net Cashflows", index=False)
            
            # print(f"\n✅ Output saved to: {output_file}")
            
            return output_file


        # =============================================================================
        # CREATE OUTPUT DATAFRAMES
        # =============================================================================

        def fn_create_output_dataframes(results):
            """
            Create single-line output DataFrames for CFS/Output module.
            
            Creates output DataFrames for:
            - NOI components: base_rent, service_charge, tor, leasing_commission, opex, noi
            - Asset Sale Price
            - Net Operating Cashflows
            - Acquisition Costs: acquisition_price, transfer_tax, legal_fees, brokerage, due_diligence
            """
            global base_rent_monthly, base_rent_annual
            global service_charge_monthly, service_charge_annual
            global tor_monthly, tor_annual
            global leasing_commission_monthly, leasing_commission_annual
            global opex_monthly, opex_annual
            global noi_monthly, noi_annual
            global asset_sale_price, asset_sale_cf_monthly, asset_sale_cf_annual
            global net_operating_cf_monthly, net_operating_cf_annual
            global acquisition_price_output, transfer_tax_output, legal_fees_output
            global brokerage_output, due_diligence_output, total_acquisition_costs_output
            
            # import AM_Co_02_input_assignment_module as mod02
            model_timeline_me_local = model_timeline_me
            model_timeline_ye_local = model_timeline_ye
            
            # Get period to year mapping
            period_years = model_timeline_me_local["Period Start"].apply(lambda x: x.year).values
            
            # Helper to create annual sum
            def create_annual_df(monthly_series):
                if monthly_series is None:
                    return pd.DataFrame([[0] * len(model_timeline_ye_local)], columns=model_timeline_ye_local.index)
                
                annual_values = []
                for year_idx, year_row in model_timeline_ye_local.iterrows():
                    year_start = year_row["Period Start"]
                    year_val = year_start.year
                    
                    # Sum monthly values for this year
                    mask = period_years == year_val
                    year_sum = monthly_series.iloc[mask].sum() if mask.any() else 0
                    annual_values.append(year_sum)
                
                return pd.DataFrame([annual_values], columns=model_timeline_ye_local.index)
            
            # Helper to create monthly DataFrame
            def create_monthly_df(series):
                if series is None:
                    return pd.DataFrame([[0] * _num_periods], columns=model_timeline_me_local.index)
                return pd.DataFrame([series.values], columns=model_timeline_me_local.index)
            
            # NOI Components
            noi_comp = results["noi_components"]
            base_rent_monthly = create_monthly_df(noi_comp["base_rent"])
            base_rent_annual = create_annual_df(noi_comp["base_rent"])
            service_charge_monthly = create_monthly_df(noi_comp["service_charges"])
            service_charge_annual = create_annual_df(noi_comp["service_charges"])
            tor_monthly = create_monthly_df(noi_comp["tor"])
            tor_annual = create_annual_df(noi_comp["tor"])
            leasing_commission_monthly = create_monthly_df(noi_comp["leasing_commissions"])
            leasing_commission_annual = create_annual_df(noi_comp["leasing_commissions"])
            opex_monthly = create_monthly_df(noi_comp["opex"])
            opex_annual = create_annual_df(noi_comp["opex"])
            noi_monthly = create_monthly_df(results["noi_series"])
            noi_annual = create_annual_df(results["noi_series"])
            
            # Asset Sale Price
            asset_sale_price = results["asset_sale_value"]
            asset_sale_cf_monthly = create_monthly_df(results["cf_components"]["asset_sale_cf"])
            asset_sale_cf_annual = create_annual_df(results["cf_components"]["asset_sale_cf"])
            
            # Net Operating Cashflows
            net_operating_cf_monthly = create_monthly_df(results["net_cf_series"])
            net_operating_cf_annual = create_annual_df(results["net_cf_series"])
            
            # Acquisition Costs (separate line items)
            acq_costs = results["acquisition_details"].get("acquisition_costs", {})
            # Use computed acquisition price (from results), not input price (from acq_costs)
            acquisition_price_output = results["acquisition_price"]
            transfer_tax_output = acq_costs.get("transfer_tax", 0)
            legal_fees_output = acq_costs.get("legal_fees", 0)
            brokerage_output = acq_costs.get("brokerage", 0)
            due_diligence_output = acq_costs.get("due_diligence", 0)
            total_acquisition_costs_output = acq_costs.get("total", 0)
            
            # print("   Created output DataFrames:")
            # print(f"      base_rent_monthly: {base_rent_monthly.shape}")
            # print(f"      service_charge_monthly: {service_charge_monthly.shape}")
            # print(f"      tor_monthly: {tor_monthly.shape}")
            # print(f"      leasing_commission_monthly: {leasing_commission_monthly.shape}")
            # print(f"      opex_monthly: {opex_monthly.shape}")
            # print(f"      noi_monthly: {noi_monthly.shape}")
            # print(f"      net_operating_cf_monthly: {net_operating_cf_monthly.shape}")
            # print(f"      asset_sale_price: {asset_sale_price:,.2f}")
            # print(f"   Acquisition Costs:")
            # print(f"      acquisition_price: {acquisition_price_output:,.2f}")
            # print(f"      transfer_tax: {transfer_tax_output:,.2f}")
            # print(f"      legal_fees: {legal_fees_output:,.2f}")
            # print(f"      brokerage: {brokerage_output:,.2f}")
            # print(f"      due_diligence: {due_diligence_output:,.2f}")
            # print(f"      total_acquisition_costs: {total_acquisition_costs_output:,.2f}")

        def fn_run_module_09():
            """Initialize and run Module 09 - Valuation."""
            # global _num_assets, _num_periods, _period_starts_ts, _period_ends_ts
            
            # print("=" * 60)
            # print("MODULE 09: VALUATION")
            # print("=" * 60)
            
            # Initialize dependencies
            # import AM_Co_02_input_assignment_module as mod02
            # from AM_Co_02_input_assignment_module import fn_run_module_02
            
            # if mod02.model_timeline_me is None:
            #     print("\n📂 Running Module 02 to load inputs...")
            #     fn_run_module_02()
            
            # Initialize module variables
            # _num_assets = len(Unit.UnitInputs.unit_id)
            # _num_periods = len(mod02.model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in mod02.model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in mod02.model_timeline_me["Period End"].values]
            
            # print(f"   Assets: {_num_assets}, Periods: {_num_periods}")
            
            # Compute valuation
            results = fn_compute_valuation()
            
            # Create output DataFrames
            # print("\n📋 Creating output DataFrames...")
            fn_create_output_dataframes(results)
            
            # print("\n✅ Module 09 completed successfully!")
            return results

        # ============================================================================================
        # HELPER FUNCTIONS TO GET CASHFLOW COMPONENTS
        # ============================================================================================

        def fn_get_base_rent_collections():
            """Get total base rent collections across all tenants.
            
            Full T2 (no probability discount), renewal excluded:
              - tenant1:  100 % (no weighting)
              - renewal:  excluded (0 %)
              - tenant2:  100 % (full weight)
            """
            cache_key = "output:base_rent_collections"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            
            nonlocal all_tenant_results
            total = np.zeros(_num_periods)
            
            try:
                # Run Module 03 if not already run
                if all_tenant_results is None:
                    fn_run_module_03()
                
                if all_tenant_results is not None:
                    # T1: full weight
                    cr_t1 = all_tenant_results.get("tenant1", {}).get("collectible_rent")
                    if cr_t1 is not None:
                        total += cr_t1.sum(axis=0).values
                    
                    # Renewal: excluded (not included in CFS)
                    
                    # T2: full weight (no probability discount)
                    cr_t2 = all_tenant_results.get("tenant2", {}).get("collectible_rent")
                    if cr_t2 is not None:
                        total += cr_t2.sum(axis=0).values
            except Exception as e:
                import traceback
                print(f"⚠️ Error getting base rent collections: {e}")
                print(traceback.format_exc())
            
            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_tor_collections():
            """Get total TOR collections across all tenants.
            
            Full T2 (no probability discount), renewal excluded:
              - T1+Renewal  turnover_rent_t1:      100 % (no weighting)
              - T1+Renewal  turnover_rent_renewal:  excluded (0 %)
              - tenant2     turnover_rent:           100 % (full weight)
            """
            cache_key = "output:tor_collections"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            total = np.zeros(_num_periods)
            
            try:
                tor_results, applicability = fn_compute_all_turnover_rent()
                
                if "tenant1_and_renewal" in tor_results:
                    # T1 portion: full weight
                    t1_tor = tor_results["tenant1_and_renewal"].get("turnover_rent_t1")
                    if t1_tor is not None:
                        total += t1_tor.sum(axis=0).values
                    
                    # Renewal TOR: excluded (not included in CFS)
                
                if "tenant2" in tor_results:
                    # T2: full weight (no probability discount)
                    t2_tor = tor_results["tenant2"].get("turnover_rent")
                    if t2_tor is not None:
                        total += t2_tor.sum(axis=0).values
            except Exception as e:
                import traceback
                print(f"⚠️ Error computing TOR: {e}")
                print(traceback.format_exc())
            
            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_base_rent_ratchet_adj():
            """Get total base rent adjustment from ratchet clause (Base+TOR).
            
            When ratchet% × previous-year TOR exceeds the forecast base rent
            for a lease year, the difference is spread equally across months.
            This function returns the total positive adjustment across all
            tenants so it can be added to the base-rent line in the CFS.
            
            Full T2 (no probability discount), renewal excluded:
              - T1+Renewal: only T1-period months get adjustments (100 %);
                renewal-period months are excluded.
              - tenant2: 100 % (full weight).
            """
            cache_key = "output:base_rent_ratchet_adj"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

            total = np.zeros(_num_periods)

            try:
                tor_results, _ = fn_compute_all_turnover_rent()
                
                # T1+Renewal: only include adjustments during T1 months
                if "tenant1_and_renewal" in tor_results:
                    adj_df = tor_results["tenant1_and_renewal"].get("base_rent_adj")
                    if adj_df is not None:
                        adj_vals = adj_df.values.copy()  # (n_assets, n_periods)
                        
                        # Identify renewal-period months using renewal collectible_rent
                        ren_cr = None
                        if all_tenant_results is not None:
                            ren_cr_df = all_tenant_results.get("renewal", {}).get("collectible_rent")
                            if ren_cr_df is not None:
                                ren_cr = ren_cr_df.values  # (n_assets, n_periods)
                        
                        if ren_cr is not None:
                            # Only T1-period months (ren_cr == 0); exclude renewal months
                            t1_adj = np.where(ren_cr == 0, adj_vals, 0.0)
                            total += t1_adj.sum(axis=0)
                        else:
                            # No renewal data → all adjustments are T1 (full weight)
                            total += adj_vals.sum(axis=0)
                
                # T2: full weight (no probability discount)
                if "tenant2" in tor_results:
                    adj_df = tor_results["tenant2"].get("base_rent_adj")
                    if adj_df is not None:
                        total += adj_df.values.sum(axis=0)
            except Exception as e:
                import traceback
                print(f"⚠️ Error getting base rent ratchet adj: {e}")
                print(traceback.format_exc())

            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_service_charges():
            """Get service charges collected."""
            cache_key = "output:service_charges"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # toi_mod = _get_tenant_other_inputs_module()
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if toi_mod.service_charge_collections_monthly is not None:
                #     return pd.Series(toi_mod.service_charge_collections_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute - function returns (results, renewal_flags) tuple
                toi_results, _ = _get_tenant_other_inputs_results()
                
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "service_charge" in toi_results[tenant_key]:
                        sc = toi_results[tenant_key]["service_charge"]
                        if isinstance(sc, pd.DataFrame):
                            total += sc.sum(axis=0).values
                        elif isinstance(sc, pd.Series):
                            total += sc.values
            except Exception as e:
                print(f"⚠️ Error computing service charges: {e}")
            
            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_leasing_commissions():
            """Get leasing commissions."""
            cache_key = "output:leasing_commissions"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # toi_mod = _get_tenant_other_inputs_module()
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if toi_mod.leasing_commission_monthly is not None:
                #     return pd.Series(toi_mod.leasing_commission_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute - function returns (results, renewal_flags) tuple
                toi_results, _ = _get_tenant_other_inputs_results()
                
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "leasing_commission" in toi_results[tenant_key]:
                        lc = toi_results[tenant_key]["leasing_commission"]
                        if isinstance(lc, pd.DataFrame):
                            total += lc.sum(axis=0).values
                        elif isinstance(lc, pd.Series):
                            total += lc.values
            except Exception as e:
                print(f"⚠️ Error computing leasing commissions: {e}")
            
            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_tenant_fitout():
            """Get tenant fit out charges."""
            # toi_mod = _get_tenant_other_inputs_module()
            cache_key = "output:tenant_fitout"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            total = np.zeros(_num_periods)
            
            try:
                # Check if output DataFrame already exists
                # if toi_mod.tenant_fitout_allowance_monthly is not None:
                #     return pd.Series(toi_mod.tenant_fitout_allowance_monthly.values.flatten(), index=range(_num_periods))
                
                # Otherwise compute - function returns (results, renewal_flags) tuple
                toi_results, _ = _get_tenant_other_inputs_results()
                
                for tenant_key in ["tenant1", "renewal", "tenant2"]:
                    if tenant_key in toi_results and "tenant_fitout" in toi_results[tenant_key]:
                        tfo = toi_results[tenant_key]["tenant_fitout"]
                        if isinstance(tfo, pd.DataFrame):
                            total += tfo.sum(axis=0).values
                        elif isinstance(tfo, pd.Series):
                            total += tfo.values
            except Exception as e:
                print(f"⚠️ Error computing tenant fit out: {e}")
            
            return _cache_set(cache_key, pd.Series(total, index=range(_num_periods)))


        def fn_get_operating_expenses():
            """Get all operating expenses by category.
            
            Date boundary enforcement:
            - Regular opex categories: only during operations_start..asset_sale_date
            - Pre-operating expenses: only during acquisition_date..operations_start
            """
            cache_key = "output:operating_expenses"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # opex_mod = _get_opex_module()
            results = {}
            
            try:
                opex_results = _get_operating_expense_results()
                
                for category in ["asset_management_fees", "facility_management_fees", 
                                "administration_cost", "insurance", "marketing_cost",
                                "utilities", "bad_debt", "void_period_cost", 
                                "other_operating_expenses", "pre_operating_expenses"]:
                    if category in opex_results:
                        data = opex_results[category]
                        if isinstance(data, pd.Series):
                            raw = data
                        elif isinstance(data, pd.DataFrame):
                            raw = data.sum(axis=0)
                        else:
                            raw = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                    else:
                        raw = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                    
                    # Apply date boundary mask
                    if category == "pre_operating_expenses":
                        results[category] = _apply_mask(raw, _mask_pre_operating)
                    elif category == "void_period_cost":
                        results[category] = _apply_mask(raw, _mask_void_period)
                    else:
                        results[category] = _apply_mask(raw, _mask_opex)
            except Exception as e:
                import traceback
                print(f"⚠️ Error computing operating expenses: {e}")
                print(traceback.format_exc())
                for category in ["asset_management_fees", "facility_management_fees", 
                                "administration_cost", "insurance", "marketing_cost",
                                "utilities", "bad_debt", "void_period_cost", 
                                "other_operating_expenses", "pre_operating_expenses"]:
                    results[category] = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            return _cache_set(cache_key, results)


        def fn_get_parking_income_expenses():
            """Get parking revenue and expense.
            
            Date boundary enforcement:
            - Parking revenue/expense only during operations_start..asset_sale_date
            """
            # oie_mod = _get_other_income_expenses_module()
            cache_key = "output:parking_income_expenses"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            
            parking_revenue = np.zeros(_num_periods)
            parking_expense = np.zeros(_num_periods)
            
            try:
                oie_results, _ = _get_other_income_expense_results()
                
                # Handle the nested structure: results["parking"]["revenue"] and results["parking"]["opex"]
                if "parking" in oie_results:
                    parking_data = oie_results["parking"]
                    if parking_data.get("revenue") is not None:
                        pr = parking_data["revenue"]
                        if isinstance(pr, pd.Series):
                            parking_revenue = pr.values
                        elif isinstance(pr, np.ndarray):
                            parking_revenue = pr
                    
                    if parking_data.get("opex") is not None:
                        pe = parking_data["opex"]
                        if isinstance(pe, pd.Series):
                            parking_expense = pe.values
                        elif isinstance(pe, np.ndarray):
                            parking_expense = pe
            except Exception as e:
                import traceback
                print(f"⚠️ Error computing parking I/E: {e}")
                print(traceback.format_exc())
            
            # Apply date boundary: parking only during acquisition_date..asset_sale_date
            return _cache_set(cache_key, (
                _apply_mask(parking_revenue, _mask_parking),
                _apply_mask(parking_expense, _mask_parking)
            ))


        def fn_get_other_income_expenses():
            """Get other income and expenses.
            
            Date boundary enforcement:
            - Other income/expenses only during acquisition_date..asset_sale_date
            """
            cache_key = "output:other_income_expenses"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            # oie_mod = _get_other_income_expenses_module()
            results = {
                "other_income_1": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "other_income_2": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "other_income_3": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "other_expense_1": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "other_expense_2": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "other_expense_3": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
            }
            
            try:
                oie_results, _ = _get_other_income_expense_results()
                
                # Handle the nested structure: results["other_income"]["other_income_1"] etc.
                if "other_income" in oie_results:
                    oi = oie_results["other_income"]
                    if isinstance(oi, dict):
                        for key in ["other_income_1", "other_income_2", "other_income_3"]:
                            if key in oi and oi[key] is not None:
                                val = oi[key]
                                if isinstance(val, pd.Series):
                                    results[key] = val
                                elif isinstance(val, np.ndarray):
                                    results[key] = pd.Series(val, index=range(_num_periods))
                
                if "other_expenses" in oie_results:
                    oe = oie_results["other_expenses"]
                    if isinstance(oe, dict):
                        for key in ["other_expense_1", "other_expense_2", "other_expense_3"]:
                            if key in oe and oe[key] is not None:
                                val = oe[key]
                                if isinstance(val, pd.Series):
                                    results[key] = val
                                elif isinstance(val, np.ndarray):
                                    results[key] = pd.Series(val, index=range(_num_periods))
            except Exception as e:
                import traceback
                print(f"⚠️ Error computing other I/E: {e}")
                print(traceback.format_exc())
            
            # Apply date boundary: other I/E only during acquisition_date..asset_sale_date
            for key in results:
                results[key] = _apply_mask(results[key], _mask_other_ie)
            
            return _cache_set(cache_key, results)


        def fn_get_maintenance_capex():
            """Get maintenance capex.
            
            Date boundary enforcement:
            - Maintenance capex only during acquisition_date..asset_sale_date
            """
            # mcapex_mod = _get_maintenance_capex_module()
            
            cache_key = "output:maintenance_capex"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            
            results = {
                "maintenance_capex_1": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "maintenance_capex_2": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "maintenance_capex_3": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "maintenance_capex_4": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "total": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
            }
            
            try:
                mcapex_results = _get_maintenance_capex_results()
                
                for i in range(1, 5):
                    key = f"maintenance_capex_{i}"
                    if key in mcapex_results:
                        raw = mcapex_results[key] if isinstance(mcapex_results[key], pd.Series) else pd.Series(mcapex_results[key], index=range(_num_periods))
                        results[key] = _apply_mask(raw, _mask_capex)
                
                if "total_maintenance_capex" in mcapex_results:
                    results["total"] = _apply_mask(mcapex_results["total_maintenance_capex"], _mask_capex)

                # print(f"   Retrieved maintenance capex successfully.")

            except Exception as e:
                print(f"⚠️ Error calculating maintenance capex: {e}")
            
            return _cache_set(cache_key, results)


        def fn_get_sinking_fund():
            """Get sinking fund.
            
            Date boundary enforcement:
            - Sinking fund only during acquisition_date..asset_sale_date
            """
            # mcapex_mod = _get_maintenance_capex_module()
            cache_key = "output:sinking_fund"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            
            total = np.zeros(_num_periods)
            
            try:
                mcapex_results = _get_maintenance_capex_results()
                
                if "sinking_fund" in mcapex_results:
                    total = mcapex_results["sinking_fund"].values
            except Exception as e:
                print(f"⚠️ Error computing sinking fund: {e}")
            
            # Apply date boundary: sinking fund only during acquisition_date..asset_sale_date
            return _cache_set(cache_key, _apply_mask(total, _mask_sinking_fund))


        def fn_get_acquisition_costs():
            """
            Get acquisition price and transaction costs.
            
            For VALUATION mode: Acquisition price = PV of net operating cashflows
            For INVESTMENT mode: Acquisition price = input value from Global.AcquisitionModule
            
            Transaction costs are percentages × acquisition price:
            - Transfer Tax: transfer_tax__stamp_duty (%) × acquisition_price
            - Legal Fees: legal_fees (%) × acquisition_price
            - Brokerage: brokerage (%) × acquisition_price
            - Due Diligence: due_diligence_costs (%) × acquisition_price
            """
            # print("\n📊 fn_get_acquisition_costs: STARTED")
            
            # Debug: Show all AcquisitionModule attributes
            acq = Global.AcquisitionModule
            # print(f"\n   🔍 DEBUG: Global.AcquisitionModule values:")
            # print(f"      acquisition_price = {acq.acquisition_price}")
            # print(f"      transfer_tax__stamp_duty = {acq.transfer_tax__stamp_duty}")
            # print(f"      legal_fees = {acq.legal_fees}")
            # print(f"      brokerage = {acq.brokerage}")
            # print(f"      due_diligence_costs = {acq.due_diligence_costs}")
            # print(f"      acquisition_price_transaction_date = {acq.acquisition_price_transaction_date}")
            # print(f"      transfer_tax__stamp_duty_transaction_date = {acq.transfer_tax__stamp_duty_transaction_date}")
            # print(f"      legal_fees_transaction_date = {acq.legal_fees_transaction_date}")
            # print(f"      brokerage_transaction_date = {acq.brokerage_transaction_date}")
            # print(f"      due_diligence_costs_transaction_date = {acq.due_diligence_costs_transaction_date}")
            
            acquisition_date = Global.ModelInputs.acquisition_date
            # print(f"   fn_get_acquisition_costs: acquisition_date = {acquisition_date}")
            if acquisition_date:
                acquisition_date = pd.to_datetime(acquisition_date)
            
            results = {
                "acquisition_price": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "transfer_tax": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "legal_fees": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "brokerage": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
                "due_diligence": pd.Series(np.zeros(_num_periods), index=range(_num_periods)),
            }
            
            acq = Global.AcquisitionModule
            
            # Get analysis type to determine how to compute acquisition price
            analysis_type = fn_get_analysis_type()
            analysis_type_lower = str(analysis_type).lower().strip() if analysis_type else ""
            is_investment = analysis_type_lower == "investment"
            is_valuation = analysis_type_lower == "valuation" or not is_investment
            
            # Get acquisition price based on analysis type
            if is_valuation:
                # VALUATION: Compute acquisition price as PV of net operating cashflows
                
                # Get discount rate
                discount_rate = fn_get_discount_rate()
                
                # Compute net operating cashflows (NOI + Asset Sale - CapEx)
                try:
                    # Get NOI
                    noi_series, noi_comp = fn_compute_noi_for_valuation()
                    
                    # Get Asset Sale Value (pass components for Indirect escalation)
                    asset_sale_value, sale_details = fn_compute_asset_sale_value(noi_series, noi_comp)
                    
                    # Get Net Operating Cashflow components (NOI, CapEx, Fitout, Other I/E, Asset Sale)
                    net_cf_series, cf_comp = fn_compute_net_operating_cashflows(noi_series, asset_sale_value)
                    
                    # Get asset sale date for separate discounting
                    asset_sale_date = fn_get_asset_sale_date()
                    
                    # Extract components
                    mcapex_comp = cf_comp.get("maintenance_capex", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    fitout_comp = cf_comp.get("tenant_fitout", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    asset_sale_comp = cf_comp.get("asset_sale_cf", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    other_inc = cf_comp.get("other_income", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    other_exp = cf_comp.get("other_expenses", pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    
                    # Monthly operating CFs = NOI + Other Income - Other Expenses - CapEx - Fitout
                    monthly_cf_series = (
                        noi_series
                        + other_inc
                        - other_exp
                        - mcapex_comp
                        - fitout_comp
                    )
                    
                    # Discount monthly operating CFs using 30/360 yearfrac (month-end)
                    pv_monthly = 0
                    pv_noi = 0; pv_mcapex = 0; pv_fitout = 0; pv_oi = 0; pv_oe = 0
                    
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        period_end = _period_ends_ts[col_idx]
                        
                        if acquisition_date is None or period_start <= acquisition_date:
                            df_val = 1.0
                        else:
                            # Monthly CFs at month-end → 30/360 yearfrac from acquisition_date to period_end
                            year_fraction = yearfrac_30_360(acquisition_date, period_end)
                            df_val = 1 / ((1 + discount_rate) ** year_fraction)
                        
                        pv_monthly += monthly_cf_series.iloc[col_idx] * df_val
                        pv_noi += noi_series.iloc[col_idx] * df_val
                        pv_mcapex += mcapex_comp.iloc[col_idx] * df_val
                        pv_fitout += fitout_comp.iloc[col_idx] * df_val
                        pv_oi += other_inc.iloc[col_idx] * df_val
                        pv_oe += other_exp.iloc[col_idx] * df_val
                    
                    # TEMP: Print discounted CFs per month (commented out to reduce log noise)
                    # print(\"\\n\" + \"=\" * 90)
                    # print(\"DISCOUNTED CFs (fn_get_acquisition_costs)\")
                    # ...
                    # END TEMP
                    
                    # Discount Asset Sale using 30/360 yearfrac from acquisition_date to asset_sale_date
                    pv_asset_sale = 0
                    if asset_sale_date is not None and acquisition_date is not None:
                        yf_sale = yearfrac_30_360(acquisition_date, asset_sale_date)
                        if yf_sale > 0:
                            df_sale = 1 / ((1 + discount_rate) ** yf_sale)
                            pv_asset_sale = asset_sale_value * df_sale
                        else:
                            pv_asset_sale = asset_sale_value
                    elif asset_sale_value > 0:
                        pv_asset_sale = asset_sale_value
                    
                    # Total PV = PV of monthly CFs + PV of Asset Sale
                    acquisition_price = pv_monthly + pv_asset_sale
                    
                    # ---- DEBUG: Print discounted CF components for verification (condensed) ----
                    print(f"\\n   [VALUATION] PV Monthly CFs: {pv_monthly:,.2f}, PV Asset Sale: {pv_asset_sale:,.2f}, Total PV (Acquisition Price): {acquisition_price:,.2f}")
                    # ---- END DEBUG ----
                    
                except Exception as e:
                    import traceback
                    acquisition_price = 0
                    if acq.acquisition_price and not pd.isna(acq.acquisition_price):
                        acquisition_price = float(acq.acquisition_price)
            else:
                # INVESTMENT: Use input acquisition price
                # print(f"   fn_get_acquisition_costs: Using INVESTMENT mode - using input price")
                acquisition_price = 0
                if acq.acquisition_price and not pd.isna(acq.acquisition_price):
                    acquisition_price = float(acq.acquisition_price)
                # print(f"   fn_get_acquisition_costs: Input acquisition price = {acquisition_price:,.2f}")
            
            # Get percentages and convert to amounts
            def get_percentage_amount(pct_value, base_amount):
                """Convert percentage to actual amount."""
                if pct_value and not pd.isna(pct_value):
                    pct = float(pct_value)
                    # Check if it's a percentage (<=1) or already a value
                    if pct <= 1:
                        return pct * base_amount
                    elif pct <= 100:
                        return (pct / 100) * base_amount
                    else:
                        # Already an absolute amount
                        return pct
                return 0
            
            transfer_tax_amt = get_percentage_amount(acq.transfer_tax__stamp_duty, acquisition_price)
            legal_fees_amt = get_percentage_amount(acq.legal_fees, acquisition_price)
            brokerage_amt = get_percentage_amount(acq.brokerage, acquisition_price)
            due_diligence_amt = get_percentage_amount(acq.due_diligence_costs, acquisition_price)
            
            # print(f"\n   fn_get_acquisition_costs: Transaction cost amounts:")
            # print(f"      Acquisition Price:    {acquisition_price:,.2f}")
            # print(f"      Transfer Tax:         {transfer_tax_amt:,.2f} (input: {acq.transfer_tax__stamp_duty})")
            # print(f"      Legal Fees:           {legal_fees_amt:,.2f} (input: {acq.legal_fees})")
            # print(f"      Brokerage:            {brokerage_amt:,.2f} (input: {acq.brokerage})")
            # print(f"      Due Diligence:        {due_diligence_amt:,.2f} (input: {acq.due_diligence_costs})")
            
            # print(f"\n   fn_get_acquisition_costs: Transaction dates from input:")
            # print(f"      Acquisition Price Date:    {acq.acquisition_price_transaction_date}")
            # print(f"      Transfer Tax Date:         {acq.transfer_tax__stamp_duty_transaction_date}")
            # print(f"      Legal Fees Date:           {acq.legal_fees_transaction_date}")
            # print(f"      Brokerage Date:            {acq.brokerage_transaction_date}")
            # print(f"      Due Diligence Date:        {acq.due_diligence_costs_transaction_date}")
            
            # Helper to place amount at a specific date
            def place_amount_at_date(amount, trans_date, default_date):
                """Place amount at the period containing trans_date, or default_date if trans_date is None."""
                target_date = trans_date if trans_date and not pd.isna(trans_date) else default_date
                if target_date:
                    target_date = pd.to_datetime(target_date)
                    for idx in range(_num_periods):
                        period_start = _period_starts_ts[idx]
                        period_end = _period_ends_ts[idx]
                        if period_start <= target_date <= period_end:
                            return idx, amount
                return None, 0
            
            # Place acquisition price at analysis date
            acq_idx, _ = place_amount_at_date(acquisition_price, None, acquisition_date)
            if acq_idx is not None:
                results["acquisition_price"].iloc[acq_idx] = acquisition_price
                # print(f"\n   fn_get_acquisition_costs: Placed acquisition_price at period {acq_idx} ({_period_starts_ts[acq_idx].strftime('%Y-%m')})")
            
            # Place each transaction cost at its own date (or default to analysis date)
            tt_idx, tt_amt = place_amount_at_date(transfer_tax_amt, acq.transfer_tax__stamp_duty_transaction_date, acquisition_date)
            if tt_idx is not None and tt_amt > 0:
                results["transfer_tax"].iloc[tt_idx] = tt_amt
                # print(f"   fn_get_acquisition_costs: Placed transfer_tax ({tt_amt:,.2f}) at period {tt_idx} ({_period_starts_ts[tt_idx].strftime('%Y-%m')})")
            
            lf_idx, lf_amt = place_amount_at_date(legal_fees_amt, acq.legal_fees_transaction_date, acquisition_date)
            if lf_idx is not None and lf_amt > 0:
                results["legal_fees"].iloc[lf_idx] = lf_amt
                # print(f"   fn_get_acquisition_costs: Placed legal_fees ({lf_amt:,.2f}) at period {lf_idx} ({_period_starts_ts[lf_idx].strftime('%Y-%m')})")
            
            br_idx, br_amt = place_amount_at_date(brokerage_amt, acq.brokerage_transaction_date, acquisition_date)
            if br_idx is not None and br_amt > 0:
                results["brokerage"].iloc[br_idx] = br_amt
                # print(f"   fn_get_acquisition_costs: Placed brokerage ({br_amt:,.2f}) at period {br_idx} ({_period_starts_ts[br_idx].strftime('%Y-%m')})")
            
            dd_idx, dd_amt = place_amount_at_date(due_diligence_amt, acq.due_diligence_costs_transaction_date, acquisition_date)
            if dd_idx is not None and dd_amt > 0:
                results["due_diligence"].iloc[dd_idx] = dd_amt
                # print(f"   fn_get_acquisition_costs: Placed due_diligence ({dd_amt:,.2f}) at period {dd_idx} ({_period_starts_ts[dd_idx].strftime('%Y-%m')})")
            
            # print(f"\n   fn_get_acquisition_costs: COMPLETED")
            
            return results


        def fn_get_asset_sale_value():
            """
            Get net asset sale value at exit for CFS path.

            New logic:
              1. Compute last 12m NOI from actual cashflows
              2. + NOI stabilization adjustment (vacancy + under/over-rent)
              = Gross Stabilized NOI
              3. − Structural vacancy deduction
              = Net Stabilized NOI
              4. × (1 + terminal_value_escalation_factor)
              = Escalated NOI
              5. / exit_yield − disposal fees
              = Net Asset Sale Value  →  placed at asset sale date
            """
            asset_sale_cf = np.zeros(_num_periods)

            try:
                # Get valuation parameters
                exit_yield = Global.ValuationParameters.exit_yield
                exit_yield = float(exit_yield) if exit_yield and not pd.isna(exit_yield) else 0

                # Read disposal cost as a percentage
                disposal_cost_pct = 0
                try:
                    val = Global.ValuationParameters.disposal_cost
                    if val and not pd.isna(val):
                        disposal_cost_pct = float(val)
                        if disposal_cost_pct > 1:
                            disposal_cost_pct = disposal_cost_pct / 100.0
                except Exception:
                    pass

                asset_sale_date = Global.ModelInputs.asset_sale_date
                if asset_sale_date:
                    asset_sale_date = pd.to_datetime(asset_sale_date)

                if exit_yield > 0 and asset_sale_date:
                    # Compute NOI components
                    base_rent = fn_get_base_rent_collections()
                    base_rent_ratchet = fn_get_base_rent_ratchet_adj()
                    base_rent = base_rent + base_rent_ratchet
                    tor = fn_get_tor_collections()
                    service_charges = fn_get_service_charges()
                    leasing_comm = fn_get_leasing_commissions()
                    opex = fn_get_operating_expenses()
                    sinking_fund = fn_get_sinking_fund()
                    parking_revenue, parking_expense = fn_get_parking_income_expenses()

                    total_opex = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                    for opex_name in opex.keys():
                        total_opex += opex.get(opex_name, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    total_expenses = total_opex + sinking_fund

                    gross_rent = base_rent + tor

                    # NOI = Gross Rent + SC - LC - Total Expenses + Parking Rev - Parking Exp
                    noi_monthly = gross_rent + service_charges - leasing_comm - total_expenses + parking_revenue - parking_expense

                    # Helper: sum last 12 monthly values before/at asset_sale_date
                    def get_last_12m_sum(series):
                        last_idx = -1
                        for col_idx in range(_num_periods - 1, -1, -1):
                            if _period_starts_ts[col_idx] <= asset_sale_date:
                                last_idx = col_idx
                                break
                        if last_idx < 0:
                            return 0
                        start_idx = max(0, last_idx - 11)
                        return float(series.iloc[start_idx:last_idx + 1].sum())

                    last_12m_noi = get_last_12m_sum(noi_monthly)

                    # --- NOI stabilization (Steps 1–5) — only when toggle is Yes ---
                    topup_toggle = str(Global.ValuationParameters.noi_top_up or "").strip().lower() in ["yes", "true", "1"]
                    if topup_toggle:
                        noi_adj, adj_details = fn_get_noi_topup()
                    else:
                        noi_adj, adj_details = 0.0, {"noi_topup_applied": False, "structural_vacancy_pct": 0.0}
                        print(f"  [NOI TOPUP] Toggle is OFF — skipping NOI top-up (CFS path)")
                    gross_stabilized_noi = last_12m_noi + noi_adj

                    # --- Step 6: Structural vacancy deduction ---
                    sv_pct = adj_details.get("structural_vacancy_pct", 0.0)
                    structural_vacancy_deduction = sv_pct * gross_stabilized_noi
                    net_stabilized_noi = gross_stabilized_noi - structural_vacancy_deduction

                    # --- Step 7: Terminal value escalation ---
                    escalation_factor = 0.0
                    try:
                        val = Global.ValuationParameters.terminal_year_noi_escalation
                        if val is not None and not pd.isna(val):
                            escalation_factor = float(val)
                            if escalation_factor > 1:
                                escalation_factor = escalation_factor / 100.0
                    except (ValueError, TypeError):
                        pass
                    if escalation_factor == 0:
                        try:
                            val = Global.ValuationParameters.terminal_value_escalation_factor
                            if val is not None and not pd.isna(val):
                                escalation_factor = float(val)
                        except (ValueError, TypeError):
                            pass

                    escalated_noi = net_stabilized_noi * (1 + escalation_factor)

                    # --- Step 8: Terminal value ---
                    gross_asset_sale_value = escalated_noi / exit_yield
                    disposal_fees = gross_asset_sale_value * disposal_cost_pct
                    asset_sale_value = gross_asset_sale_value - disposal_fees

                    # Place at asset sale date
                    for col_idx in range(_num_periods):
                        period_start = _period_starts_ts[col_idx]
                        period_end = _period_ends_ts[col_idx]

                        if period_start <= asset_sale_date <= period_end:
                            asset_sale_cf[col_idx] = asset_sale_value
                            break
                else:
                    pass  # Exit yield is 0 or no sale date

            except Exception as e:
                print(f"⚠️ Error computing asset sale value: {e}")
                import traceback
                traceback.print_exc()

            return pd.Series(asset_sale_cf, index=range(_num_periods))


        # ============================================================================================
        # READ LINE ITEM NAMES FROM WORKBOOK
        # ============================================================================================

        def fn_get_line_items_from_named_range(named_range_name):
            """
            Read line item names from a named range in the assumptions DataFrame.
            
            Args:
                named_range_name: Name of the named range (e.g., 'o.assetco.cfo.names')
            
            Returns:
                List of line item names
            """
            try:
                # Use assumptions (runtime) instead of imported assumptions (import time)
                runtime_assumptions = assumptions
                if runtime_assumptions is None or (hasattr(runtime_assumptions, 'empty') and runtime_assumptions.empty):
                    # print(f"   [INFO] Assumptions not loaded, using defaults for '{named_range_name}'")
                    return []
                
                result = runtime_assumptions.loc[runtime_assumptions["name"] == named_range_name, "value"]
                if result.empty:
                    # Show all o.assetco named ranges to debug
                    all_names = runtime_assumptions["name"].tolist()
                    o_names = [n for n in all_names if isinstance(n, str) and n.startswith("o.")]
                    print(f"   ⚠️ '{named_range_name}' NOT found. All 'o.*' named ranges received: {o_names}")
                    return []
                
                values = result.iloc[0]
                
                # Handle different formats
                if isinstance(values, list):
                    # Clean up None/0 values and convert to strings
                    line_items = []
                    for v in values:
                        if v is None or (isinstance(v, float) and pd.isna(v)):
                            line_items.append("")  # Empty row
                        elif isinstance(v, (int, float)) and v == 0:
                            line_items.append("")  # Numeric zero = blank row separator
                        else:
                            s = str(v).strip()
                            if s == "0":
                                line_items.append("")  # String "0" = blank row separator
                            else:
                                line_items.append(s)
                    return line_items
                elif isinstance(values, str):
                    return [values.strip()]
                else:
                    return [str(values).strip()] if values else []
            
            except Exception as e:
                print(f"⚠️ Error reading named range '{named_range_name}': {e}")
                return []


        # ============================================================================================
        # OUTPUT DATAFRAMES (initialized in fn_run_module_10)
        # ============================================================================================

        operations_line_items = None
        investment_line_items = None
        financing_line_items = None
        cashflow_from_operations = None
        cashflow_from_investments = None
        cashflow_from_financing = None


        def fn_safe_set_row(df, row_name, values):
            """
            Safely set a row value in a DataFrame using exact matching.
            Only sets value if exact row name exists in DataFrame index.
            """
            # Exact match first
            if row_name in df.index:
                df.loc[row_name, :] = values
                return True
            
            # Try case-insensitive exact match only
            row_name_lower = row_name.lower().strip()
            for idx in df.index:
                if isinstance(idx, str) and idx.lower().strip() == row_name_lower:
                    df.loc[idx, :] = values
                    return True
            
            # No match found - don't use fuzzy matching
            # print(f"   ⚠️ Row '{row_name}' not found in DataFrame index")
            return False


        # ============================================================================================
        # CASHFLOW COMPUTATION FUNCTION
        # ============================================================================================

        def fn_initialize_dataframes():
            """Initialize the cashflow dataframes with line items from workbook or defaults."""
            global operations_line_items, investment_line_items, financing_line_items
            global cashflow_from_operations, cashflow_from_investments, cashflow_from_financing
            # global _num_periods, _period_starts_ts, _period_ends_ts
            
            # Initialize module-level constants
            # _num_periods = len(model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # print("📖 Reading line item names from workbook...")
            
            # CFO Line Items — dynamic from template, hardcoded fallback
            operations_line_items = fn_get_line_items_from_named_range("o.assetco.cfo.names")
            if not operations_line_items:
                print("   ⚠️ CFO: Using default line items (named range not found)")
                operations_line_items = [
                    "Cash Received from Asset Lease",       # 1  Header
                    "Base Rent",                            # 2
                    "Turnover Rent",                        # 3
                    "Gross Rent",                           # 4
                    "Service Charge",                       # 5
                    "Leasing Commissions",                  # 6
                    "Net Lease Revenue",                    # 7
                    "",                                     # 8  Blank row
                    "Expenses",                             # 9
                    "Pre Operating Expenses",               # 10
                    "Asset Management Fees",                # 11
                    "Utilities",                            # 12
                    "Facility Management Fees",             # 13
                    "Administration Cost",                  # 14
                    "Marketing Cost",                       # 15
                    "Insurance",                            # 16
                    "Other Operating Expenses",             # 17
                    "Bad Debt",                             # 18
                    "Void Period Opex",                     # 19
                    "Sinking Fund",                         # 20
                    "Total Operating Expenses",             # 21
                    "Parking Revenue",                      # 22
                    "Parking Expenses",                     # 23
                    "",                                     # 24 Blank
                    "Net Operating Income",                 # 25
                    "",                                     # 26 Blank
                    "Other Income/Expenses",                # 27 Header
                    "Other Income 1",                       # 28
                    "Other Income 2",                       # 29
                    "Other Income 3",                       # 30
                    "Other Expense 1",                      # 31
                    "Other Expense 2",                      # 32
                    "Other Expense 3",                      # 33
                    "",                                     # 34 Blank
                    "Net Cashflow from Operations",         # 35
                    "",                                     # 36 Blank
                    "EBITDA_Hospitality",                   # 37
                    "Change in Working Capital_Hospitality",# 38
                    "",                                     # 39 Blank
                    "Net Cashflow from Operations_Hospitality", # 40
                    "",                                     # 41 Blank
                    "Total Net Cashflow from Operations"    # 42
                ]
            else:
                print(f"   ✅ CFO: Loaded {len(operations_line_items)} line items from template")
            
            # CFI Line Items — dynamic from template, hardcoded fallback
            investment_line_items = fn_get_line_items_from_named_range("o.assetco.cfi.names")
            if not investment_line_items:
                print("   ⚠️ CFI: Using default line items (named range not found)")
                investment_line_items = [
                    "Asset Acquisition Costs",              # 1  Header
                    "Acquisition Price",                    # 2
                    "Transfer Tax / Stamp Duty",            # 3
                    "Legal Fees",                           # 4
                    "Brokerage",                            # 5
                    "Due Diligence Costs",                  # 6
                    "Total Asset Acquisition Cost",         # 7
                    "Maintenance Capex 1",                  # 8
                    "Maintenance Capex 2",                  # 9
                    "Maintenance Capex 3",                  # 10
                    "Maintenance Capex 4",                  # 11
                    "Tenant Fitout Allowance",              # 12
                    "Total Capex",                          # 13
                    "Net Asset Sale Value",                 # 14
                    "",                                     # 15 Blank
                    "Net Cashflow from Investments"         # 16
                ]
            else:
                print(f"   ✅ CFI: Loaded {len(investment_line_items)} line items from template")
            
            # CFF Line Items — dynamic from template, hardcoded fallback
            financing_line_items = fn_get_line_items_from_named_range("o.assetco.cff.names")
            if not financing_line_items:
                print("   ⚠️ CFF: Using default line items (named range not found)")
                financing_line_items = [
                    "Asset Level Term Loan",                         # 1  Header
                    "Principal Drawn",                               # 2
                    "Principal Repaid",                              # 3
                    "Interest Paid",                                 # 4
                    "Arrangement Fees",                              # 5
                    "Asset Level Refinancing Facility",              # 6  Header
                    "Principal Drawn",                               # 7
                    "Principal Repaid",                              # 8
                    "Interest Paid",                                 # 9
                    "Arrangement Fees",                              # 10
                    "Equity Injection",                              # 11
                    "",                                              # 12 Blank
                    "Net Cashflow from Financing"                    # 13
                ]
            else:
                print(f"   ✅ CFF: Loaded {len(financing_line_items)} line items from template")
            
            # Create DataFrames
            columns = model_timeline_me.index
            
            # Header / category rows that should remain blank (not filled with 0)
            _HEADER_ROWS = {
                "cashflow from operations",
                "cash received from asset lease", "expenses",
                "other income/expenses", "other income / expenses",
                "other income/expenses_asset co", "other income / expenses_asset co",
                "cashflow from investments",
                "asset acquisition costs",
                "cashflow from financing",
                "asset level term loan", "asset level refinancing facility",
                "asset level revolver facility",
                "project level term loan", "project level revolver facility",
                "project level refinancing facility",
            }
            
            def _init_df(line_items):
                df = pd.DataFrame(index=line_items, columns=columns)
                for idx in df.index:
                    if isinstance(idx, str) and idx.strip() != "":
                        if idx.strip().lower() in _HEADER_ROWS:
                            df.loc[idx, :] = ""          # header → blank
                        else:
                            df.loc[idx, :] = 0.0         # data row → zero
                    else:
                        df.loc[idx, :] = ""              # blank row → blank
                return df
            
            cashflow_from_operations = _init_df(operations_line_items)
            cashflow_from_investments = _init_df(investment_line_items)
            cashflow_from_financing = _init_df(financing_line_items)


        def fn_compute_all_cashflows():
            """
            Compute all cashflows for Asset Co model.
            
            Returns: Dictionary with cashflow_from_operations, cashflow_from_investments, 
                    cashflow_from_financing DataFrames
            """
            global cashflow_from_operations, cashflow_from_investments, cashflow_from_financing, _function_timings
            # global _num_periods, _period_starts_ts, _period_ends_ts
            
            # Reset timing dictionary
            _function_timings.clear()
            
            # print("=" * 80)
            # print("COMPUTING ASSET CO CASHFLOWS")
            # print("=" * 80)
            
            # Initialize dataframes if not already done
            if cashflow_from_operations is None:
                fn_initialize_dataframes()
            
            # ========================================================================
            # CASHFLOW FROM OPERATIONS
            # ========================================================================
            
            # Cash Received from Asset Lease
            base_rent = timed_call(fn_get_base_rent_collections, "fn_get_base_rent_collections")
            tor = timed_call(fn_get_tor_collections, "fn_get_tor_collections")
            service_charges = timed_call(fn_get_service_charges, "fn_get_service_charges")
            leasing_comm = timed_call(fn_get_leasing_commissions, "fn_get_leasing_commissions")
            
            # Add ratchet-clause base-rent adjustment (positive = extra base rent)
            base_rent_ratchet_adj = timed_call(fn_get_base_rent_ratchet_adj, "fn_get_base_rent_ratchet_adj")
            base_rent = base_rent + base_rent_ratchet_adj
            
            # Debug: log intermediate totals to diagnose zero-output issues
            print(f"\n   [CFS DEBUG] Raw totals BEFORE valid_period_flag:")
            print(f"      base_rent sum:      {base_rent.sum():,.2f}")
            print(f"      base_rent_adj sum:  {base_rent_ratchet_adj.sum():,.2f}")
            print(f"      turnover_rent sum:   {tor.sum():,.2f}")
            print(f"      service_charges sum: {service_charges.sum():,.2f}")
            print(f"      leasing_comm sum:    {leasing_comm.sum():,.2f}")
            print(f"      valid_period_flag:   {_valid_period_flag.sum():.0f} of {_num_periods} periods active")
            
            # Apply valid period flag to prevent cashflows before acquisition or after sale
            base_rent = pd.Series(apply_valid_period_flag(base_rent.values), index=base_rent.index)
            tor = pd.Series(apply_valid_period_flag(tor.values), index=tor.index)
            service_charges = pd.Series(apply_valid_period_flag(service_charges.values), index=service_charges.index)
            leasing_comm = pd.Series(apply_valid_period_flag(leasing_comm.values), index=leasing_comm.index)
            
            fn_safe_set_row(cashflow_from_operations, "Base Rent", base_rent.values)
            fn_safe_set_row(cashflow_from_operations, "Turnover Rent", tor.values)
            
            # Gross Rent = Base Rent + Turnover Rent
            gross_rent = base_rent + tor
            fn_safe_set_row(cashflow_from_operations, "Gross Rent", gross_rent.values)
            # Note: "Cash Received from Asset Lease" is a header row - leave blank
            
            # Service Charges and Leasing Commissions
            fn_safe_set_row(cashflow_from_operations, "Service Charge", service_charges.values)
            fn_safe_set_row(cashflow_from_operations, "Leasing Commissions", (leasing_comm * -1).values)
            
            # Net Lease Revenue = Gross Rent + Service Charge - Leasing Commissions
            net_lease_revenue = gross_rent + service_charges - leasing_comm
            fn_safe_set_row(cashflow_from_operations, "Net Lease Revenue", net_lease_revenue.values)
            
            # Operating Expenses
            opex = timed_call(fn_get_operating_expenses, "fn_get_operating_expenses")
            total_opex = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            for opex_name, df_name in [
                ("pre_operating_expenses", "Pre Operating Expenses"),
                ("asset_management_fees", "Asset Management Fees"),
                ("utilities", "Utilities"),
                ("facility_management_fees", "Facility Management Fees"),
                ("administration_cost", "Administration Cost"),
                ("marketing_cost", "Marketing Cost"),
                ("insurance", "Insurance"),
                ("other_operating_expenses", "Other Operating Expenses"),
                ("bad_debt", "Bad Debt"),
                ("void_period_cost", "Void Period Opex"),
            ]:
                expense = opex.get(opex_name, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                # Apply valid period flag to each OPEX
                expense = pd.Series(apply_valid_period_flag(expense.values), index=expense.index)
                fn_safe_set_row(cashflow_from_operations, df_name, (expense * -1).values)
                total_opex += expense
            
            # Sinking Fund - inside Expenses section (before Total Operating Expenses)
            sinking_fund = timed_call(fn_get_sinking_fund, "fn_get_sinking_fund")
            sinking_fund = pd.Series(apply_valid_period_flag(sinking_fund.values), index=sinking_fund.index)
            fn_safe_set_row(cashflow_from_operations, "Sinking Fund", (sinking_fund * -1).values)
            total_opex += sinking_fund
            
            # Note: "Expenses" is a header row - leave blank
            fn_safe_set_row(cashflow_from_operations, "Total Operating Expenses", (total_opex * -1).values)
            
            # Parking Revenue/Expenses (between Total OPEX and NOI)
            parking_revenue, parking_expense = timed_call(fn_get_parking_income_expenses, "fn_get_parking_income_expenses")
            parking_revenue = pd.Series(apply_valid_period_flag(parking_revenue.values), index=parking_revenue.index)
            parking_expense = pd.Series(apply_valid_period_flag(parking_expense.values), index=parking_expense.index)
            fn_safe_set_row(cashflow_from_operations, "Parking Revenue", parking_revenue.values)
            fn_safe_set_row(cashflow_from_operations, "Parking Expenses", (parking_expense * -1).values)
            
            # Net Operating Income (NOI) = Net Lease Revenue - Total Operating Expenses + Parking Revenue - Parking Expenses
            noi = net_lease_revenue - total_opex + parking_revenue - parking_expense
            # Write NOI — try plain name first, then _Asset Co suffix
            if not fn_safe_set_row(cashflow_from_operations, "Net Operating Income", noi.values):
                fn_safe_set_row(cashflow_from_operations, "Net Operating Income_Asset Co", noi.values)
            
            # Other Income/Expenses section
            other_ie = timed_call(fn_get_other_income_expenses, "fn_get_other_income_expenses")
            other_income_total = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            for i in range(1, 4):
                key = f"other_income_{i}"
                income = other_ie.get(key, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                income = pd.Series(apply_valid_period_flag(income.values), index=income.index)
                fn_safe_set_row(cashflow_from_operations, f"Other Income {i}", income.values)
                other_income_total += income
            
            # Other Expense
            other_expense_total = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            for i in range(1, 4):
                key = f"other_expense_{i}"
                expense = other_ie.get(key, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                expense = pd.Series(apply_valid_period_flag(expense.values), index=expense.index)
                fn_safe_set_row(cashflow_from_operations, f"Other Expense {i}", (expense * -1).values)
                other_expense_total += expense
            
            # Note: "Other Income/Expenses" is a header row - leave blank
            
            # Net Cashflow from Operations = NOI + Other Income - Other Expenses
            net_cf_operations = noi + other_income_total - other_expense_total
            # Write Net CF from Ops — try plain name first, then _Asset Co suffix
            if not fn_safe_set_row(cashflow_from_operations, "Net Cashflow from Operations", net_cf_operations.values):
                fn_safe_set_row(cashflow_from_operations, "Net Cashflow from Operations_Asset Co", net_cf_operations.values)
            # Total = Asset Co (no hospitality computed yet)
            fn_safe_set_row(cashflow_from_operations, "Total Net Cashflow from Operations", net_cf_operations.values)
            
            # ========================================================================
            # CASHFLOW FROM INVESTMENTS
            # ========================================================================
            
            # Acquisition Costs
            # print("\n" + "="*60)
            # print("📊 COMPUTING ACQUISITION COSTS FOR CFS")
            # print("="*60)
            acq_costs = timed_call(fn_get_acquisition_costs, "fn_get_acquisition_costs")
            
            # print(f"\n   📊 acq_costs returned:")
            # print(f"      acquisition_price sum: {acq_costs['acquisition_price'].sum():,.2f}")
            # print(f"      transfer_tax sum:      {acq_costs['transfer_tax'].sum():,.2f}")
            # print(f"      legal_fees sum:        {acq_costs['legal_fees'].sum():,.2f}")
            # print(f"      brokerage sum:         {acq_costs['brokerage'].sum():,.2f}")
            # print(f"      due_diligence sum:     {acq_costs['due_diligence'].sum():,.2f}")
            # print("="*60 + "\n")
            
            # Apply valid period flag to all acquisition costs
            for key in acq_costs:
                acq_costs[key] = pd.Series(apply_valid_period_flag(acq_costs[key].values), index=acq_costs[key].index)
            
            fn_safe_set_row(cashflow_from_investments, "Acquisition Price", (acq_costs["acquisition_price"] * -1).values)
            fn_safe_set_row(cashflow_from_investments, "Transfer Tax / Stamp Duty", (acq_costs["transfer_tax"] * -1).values)
            fn_safe_set_row(cashflow_from_investments, "Legal Fees", (acq_costs["legal_fees"] * -1).values)
            fn_safe_set_row(cashflow_from_investments, "Brokerage", (acq_costs["brokerage"] * -1).values)
            fn_safe_set_row(cashflow_from_investments, "Due Diligence Costs", (acq_costs["due_diligence"] * -1).values)
            
            # Asset Acquisition Cost subtotal
            total_acq_cost = (
                acq_costs["acquisition_price"] + acq_costs["transfer_tax"] + acq_costs["legal_fees"] + 
                acq_costs["brokerage"] + acq_costs["due_diligence"]
            )
            # Try both old and new row names for acquisition cost subtotal
            if not fn_safe_set_row(cashflow_from_investments, "Total Asset Acquisition Cost", (total_acq_cost * -1).values):
                fn_safe_set_row(cashflow_from_investments, "Asset Acquisition Cost", (total_acq_cost * -1).values)
            
            # Maintenance CapEx - Apply valid period flag
            mcapex = timed_call(fn_get_maintenance_capex, "fn_get_maintenance_capex")
            total_mcapex = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
            
            for i in range(1, 5):
                key = f"maintenance_capex_{i}"
                capex = mcapex.get(key, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                # Apply valid period flag to each maintenance capex
                capex = pd.Series(apply_valid_period_flag(capex.values), index=capex.index)
                fn_safe_set_row(cashflow_from_investments, f"Maintenance Capex {i}", (capex * -1).values)
                total_mcapex += capex
            
            # Tenant Fitout Allowance - Apply valid period flag
            tenant_fitout = timed_call(fn_get_tenant_fitout, "fn_get_tenant_fitout")
            tenant_fitout = pd.Series(apply_valid_period_flag(tenant_fitout.values), index=tenant_fitout.index)
            fn_safe_set_row(cashflow_from_investments, "Tenant Fitout Allowance", (tenant_fitout * -1).values)
            
            # Total Capex
            total_capex = total_mcapex + tenant_fitout
            fn_safe_set_row(cashflow_from_investments, "Total Capex", (total_capex * -1).values)
            
            # Asset Sale Value - Apply valid period flag
            asset_sale = timed_call(fn_get_asset_sale_value, "fn_get_asset_sale_value")
            asset_sale = pd.Series(apply_valid_period_flag(asset_sale.values), index=asset_sale.index)
            _sale_total = asset_sale.sum()
            _disp_pct_raw = Global.ValuationParameters.disposal_cost
            print(f"   Asset Sale Value (total): {_sale_total:,.2f}  |  disposal_cost raw from Global: {_disp_pct_raw}")
            fn_safe_set_row(cashflow_from_investments, "Net Asset Sale Value", asset_sale.values)
            
            # Net Cashflow from Investments
            net_cf_investments = -total_acq_cost - total_capex + asset_sale
            fn_safe_set_row(cashflow_from_investments, "Net Cashflow from Investments", net_cf_investments.values)
            
            # ========================================================================
            # CASHFLOW FROM FINANCING – Full Debt + Equity Engine
            # ========================================================================

            # JV inclusion check: if asset is included in a JV/JDA, skip CFF
            _jv_inclusion = str(Global.AssetDetails.jvjda_inclusion or "").strip().lower()
            _assetco_jv_inclusion = str(Global.AssetDetails.assetco_jv_inclusion or "").strip().lower()
            _skip_cff = (_jv_inclusion == "yes" and _assetco_jv_inclusion == "yes")

            if _skip_cff:
                print("\n   ⚠️ JV INCLUSION ACTIVE: jvjda_inclusion=Yes, assetco_jv_inclusion=Yes")
                print("      → Skipping CFF computation. Financing handled at JV level.")
                print(f"      venture_type: {Global.AssetDetails.venture_type}")
                print(f"      jv_name:      {Global.AssetDetails.jv_name}")
                # CFF DataFrame already initialized to zeros/blanks by _init_df
                # Set Net CFF row to zero explicitly
                fn_safe_set_row(cashflow_from_financing, "Net Cashflow from Financing", np.zeros(_num_periods))
                # Still need these for the return dict
                loan1_dscr_series = np.zeros(_num_periods)
                refi_dscr_series = np.zeros(_num_periods)
                opening_cash_series = np.zeros(_num_periods)
                closing_cash_series = np.zeros(_num_periods)
                # Print timing summary
                print_timing_summary()
                return {
                    "cashflow_from_operations": cashflow_from_operations,
                    "cashflow_from_investments": cashflow_from_investments,
                    "cashflow_from_financing": cashflow_from_financing,
                    "loan1_dscr": pd.Series(loan1_dscr_series, index=range(_num_periods)),
                    "loan2_dscr": pd.Series(refi_dscr_series, index=range(_num_periods)),
                    "opening_cash": pd.Series(opening_cash_series, index=range(_num_periods)),
                    "closing_cash": pd.Series(closing_cash_series, index=range(_num_periods)),
                }

            # Load interest rate profiles once
            interest_rate_profiles = fn_get_interest_rate_profiles()
            _profile_keys = list(interest_rate_profiles.keys()) if interest_rate_profiles else []
            print(f"\n   Interest Rate Profiles Loaded: {_profile_keys}")

            # ---- Helpers ----
            def _safe_float(val, default=0.0):
                """Convert value to float safely."""
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            def _safe_pct(val, default=0.0):
                """Convert percentage value (may be 0-1 or 0-100 from Excel)."""
                v = _safe_float(val, default)
                # If > 1, assume it was expressed as %, e.g. 50 → 0.50
                if abs(v) > 1 and abs(v) <= 100:
                    return v / 100.0
                return v

            def _to_date(val):
                """Convert any value to a Timestamp. Handles datetime, string, or Excel serial."""
                if val is None:
                    return None
                if isinstance(val, (pd.Timestamp, datetime)):
                    return pd.to_datetime(val)
                if isinstance(val, str):
                    try:
                        return pd.to_datetime(val)
                    except Exception:
                        return None
                if isinstance(val, (int, float)):
                    serial = float(val)
                    if 25000 < serial < 100000:
                        try:
                            return pd.to_datetime(datetime.fromtimestamp((serial - 25569) * 86400.0))
                        except Exception:
                            return None
                return pd.to_datetime(val)

            def _find_period_idx(target_date):
                """Find the period index that contains target_date."""
                if target_date is None:
                    return None
                target_ts = _to_date(target_date)
                if target_ts is None:
                    return None
                for idx in range(_num_periods):
                    if _period_starts_ts[idx] <= target_ts <= _period_ends_ts[idx]:
                        return idx
                    # Also catch if target is exactly the start of next period
                    if idx < _num_periods - 1 and target_ts == _period_starts_ts[idx + 1]:
                        return idx + 1
                # If before first period, return 0; if after last, return last
                if target_ts < _period_starts_ts[0]:
                    return 0
                return _num_periods - 1

            # ---- Read global inputs ----
            asset_sale_date = _to_date(Global.ModelInputs.asset_sale_date)
            acquisition_date = _to_date(Global.ModelInputs.acquisition_date)

            ltv_pct = _safe_pct(Global.CapitalStructure.total_debt_ltv, 0.0)

            # Loan 1 inputs
            loan1 = Global.FinancingAssumptions_Loan1
            loan1_start = _to_date(loan1.loan_raise_date) if loan1.loan_raise_date else acquisition_date
            loan1_term_years = _safe_float(loan1.loan_term, 0)
            loan1_term_months = int(loan1_term_years * 12) if loan1_term_years < 100 else int(loan1_term_years)
            loan1_end = _to_date(loan1.loan_end) if loan1.loan_end else None
            if loan1_end is None and loan1_start and loan1_term_months > 0:
                loan1_end = loan1_start + relativedelta(months=loan1_term_months)
            # Amortization: annual_amortization % of loan amortized per year over amortization_duration years
            loan1_amort_duration_years = _safe_float(loan1.amortization_duration, 0)
            loan1_annual_amort_pct = _safe_pct(loan1.annual_amortization, 0.0)
            loan1_balloon_pct = _safe_pct(loan1.balloon_payment, 0.0)
            loan1_interest_profile = loan1.base_interest_rate
            # Fixed Spread: applies to both financing and refinancing
            # Interest Rate = SAIBOR (from selected profile) + Fixed Spread
            # Try reading from multiple possible Global Input locations
            fixed_spread = _safe_pct(loan1.fixed_spread, 0.0)
            if fixed_spread == 0.0:
                fixed_spread = _safe_pct(Global.ModelInputs.fixed_spread, 0.0)
            if fixed_spread == 0.0:
                fixed_spread = _safe_pct(Global.CapitalStructure.fixed_spread, 0.0)
            # Direct fallback: scan all Global Input attributes/values for "fixed" + "spread"
            if fixed_spread == 0.0:
                try:
                    _gi_classes = assumptions.loc[assumptions["name"] == "a.assetco.global.class", "value"]
                    _gi_attrs = assumptions.loc[assumptions["name"] == "a.assetco.global.attribute", "value"]
                    _gi_vals = assumptions.loc[assumptions["name"] == "a.assetco.global.value", "value"]
                    if not _gi_classes.empty and not _gi_attrs.empty and not _gi_vals.empty:
                        _classes = _gi_classes.iloc[0]
                        _attrs = _gi_attrs.iloc[0]
                        _vals = _gi_vals.iloc[0]
                        _min_len = min(len(_classes), len(_attrs), len(_vals))
                        for _i in range(_min_len):
                            _attr_lower = str(_attrs[_i]).lower().replace(" ", "").replace("-", "").replace("_", "")
                            if "spread" in _attr_lower or "fixedspread" in _attr_lower or "fixed_spread" in _attr_lower:
                                _found_val = _safe_pct(_vals[_i], 0.0)
                                if _found_val != 0.0:
                                    print(f"   ✅ Fixed Spread found via direct scan: class='{_classes[_i]}', attr='{_attrs[_i]}', value={_vals[_i]} → {_found_val}")
                                    fixed_spread = _found_val
                                    break
                except Exception as _e:
                    print(f"   ⚠️ Fixed Spread direct scan error: {_e}")
            print(f"   CFF: Fixed Spread raw values: Loan1={loan1.fixed_spread}, ModelInputs={Global.ModelInputs.fixed_spread}, CapitalStructure={Global.CapitalStructure.fixed_spread} → resolved={fixed_spread}")
            loan1_arr_fee_pct = _safe_float(loan1.arrangement_fees, 0.0)
            if loan1_arr_fee_pct > 1:
                loan1_arr_fee_pct = loan1_arr_fee_pct / 100.0
            loan1_refinancing = str(loan1.loan_refinancing_ or "").lower().strip() in ["yes", "true", "1"]
            loan1_refinancing_date = _to_date(loan1.loan_refinancing_date) if loan1.loan_refinancing_date else None

            # Refinancing (Loan 2) inputs
            refi = Global.RefinancingAssumptions
            refi_ltv = _safe_pct(refi.ltv, 0.0)
            refi_cap_rate = _safe_float(refi.cap_rate_at_refinance, 0.0)
            if refi_cap_rate > 1:
                refi_cap_rate = refi_cap_rate / 100.0
            refi_min_dscr = _safe_float(refi.min_dscr, 0.0)
            if isinstance(refi.min_dscr, str) and refi.min_dscr.strip().lower().endswith('x'):
                try:
                    refi_min_dscr = float(refi.min_dscr.strip().rstrip('xX'))
                except (ValueError, TypeError):
                    pass
            refi_repayment_type = str(refi.repayment_type or "Amortizing").strip()
            refi_start = _to_date(refi.loan_start) if refi.loan_start else loan1_refinancing_date
            refi_term_years = _safe_float(refi.loan_term, 0)
            refi_term_months = int(refi_term_years * 12) if refi_term_years < 100 else int(refi_term_years)
            refi_end = _to_date(refi.loan_end) if refi.loan_end else None
            if refi_end is None and refi_start and refi_term_months > 0:
                refi_end = refi_start + relativedelta(months=refi_term_months)
            if refi_end and asset_sale_date and refi_end > asset_sale_date:
                refi_end = asset_sale_date
            refi_amort_duration_years = _safe_float(refi.amortization_duration, 0)
            refi_annual_amort_pct = _safe_pct(refi.annual_amortization, 0.0)
            refi_balloon_pct = _safe_pct(refi.balloon_payment, 0.0)
            refi_interest_profile = refi.refinance_interest_rate
            refi_arr_fee_pct = _safe_float(refi.arrangement_fees, 0.0)
            if refi_arr_fee_pct > 1:
                refi_arr_fee_pct = refi_arr_fee_pct / 100.0

            # ---- Acquisition cost for debt sizing ----
            # Loan is sized on ACQUISITION PRICE only (not transaction costs).
            # Transaction costs (transfer tax, legal, brokerage, due diligence) are
            # separate cash outflows paid from equity / available cash.
            acq_price_scalar = acq_costs["acquisition_price"].sum()
            transaction_costs_scalar = (
                acq_costs["transfer_tax"].sum() +
                acq_costs["legal_fees"].sum() +
                acq_costs["brokerage"].sum() +
                acq_costs["due_diligence"].sum()
            )
            total_acquisition_cost = acq_price_scalar + transaction_costs_scalar

            # ---- Loan 1 Amount = LTV × Acquisition Price (excludes transaction costs) ----
            loan1_amount = ltv_pct * acq_price_scalar

            # ---- Loan 1 arrangement fee (cash outflow, never capitalized) ----
            loan1_arrangement_fee = loan1_arr_fee_pct * loan1_amount

            print(f"\n   CFF: Loan1={loan1_amount:,.0f} @ SAIBOR profile={loan1_interest_profile} + spread={fixed_spread*100:.2f}%, Refi={'Yes' if loan1_refinancing else 'No'}")
            print(f"   CFF: LTV={ltv_pct*100:.1f}%, AcqPrice={acq_price_scalar:,.0f}, Loan1AnnualAmort={loan1_annual_amort_pct*100:.2f}%")
            print(f"   CFF: Loan1 monthly principal = {(loan1_annual_amort_pct * loan1_amount / 12.0):,.2f}")
            print(f"   CFF: Loan1 start={loan1_start}, end={loan1_end}, term_months={loan1_term_months}")

            # Net CFO and CFI already computed
            net_cfo = net_cf_operations
            net_cfi = net_cf_investments

            # ================================================================
            # SHARED LOAN SCHEDULE BUILDER
            # ================================================================
            def _build_loan_schedule(
                loan_amount,
                annual_amort_pct,
                interest_profile,
                loan_start_date,
                start_idx,
                effective_end_idx,
                arrangement_fee,
                repayment_type="amortizing",
                spread=0.0,
            ):
                """Build drawn/repaid/interest/fees/balance/dscr arrays for a loan.

                Parameters
                ----------
                loan_amount : float
                annual_amort_pct : float  (e.g. 0.10 for 10%)
                interest_profile : str    Name of the SAIBOR rate profile
                loan_start_date : Timestamp   Used for rate lookup
                start_idx : int|None      Period index when loan is drawn
                effective_end_idx : int|None  Period when outstanding balance is repaid
                                              (refinancing/sale). None ⇒ keep amortizing.
                arrangement_fee : float   Cash outflow at draw (no capitalisation)
                repayment_type : str      "amortizing" | "interest only"
                spread : float            Fixed spread added to SAIBOR rate (e.g. 0.02 for 2%)

                Returns
                -------
                dict with keys: drawn, repaid, interest, fees, balance, dscr  (all np arrays)
                """
                drawn = np.zeros(_num_periods)
                repaid = np.zeros(_num_periods)
                interest = np.zeros(_num_periods)
                fees = np.zeros(_num_periods)
                balance = np.zeros(_num_periods)
                dscr = np.zeros(_num_periods)

                if start_idx is None or loan_amount <= 0:
                    return dict(drawn=drawn, repaid=repaid, interest=interest,
                                fees=fees, balance=balance, dscr=dscr)

                monthly_principal = (annual_amort_pct * loan_amount / 12.0) if annual_amort_pct > 0 else 0.0
                is_io = repayment_type.lower() == "interest only"

                drawn[start_idx] = loan_amount
                fees[start_idx] = arrangement_fee

                opening = 0.0
                for col_idx in range(_num_periods):
                    if col_idx < start_idx:
                        balance[col_idx] = 0.0
                        continue

                    opening = loan_amount if col_idx == start_idx else balance[col_idx - 1]

                    if opening <= 0:
                        balance[col_idx] = 0.0
                        continue

                    # Interest for this period: SAIBOR rate + Fixed Spread
                    period_date = _period_starts_ts[col_idx]
                    saibor_rate = fn_get_interest_rate_for_period(
                        interest_profile, period_date,
                        loan_start_date, interest_rate_profiles,
                    )
                    annual_rate = saibor_rate + spread
                    int_amt = opening * (annual_rate / 12.0)

                    # Debug: log first period's rate breakdown
                    if col_idx == start_idx:
                        print(f"   [LOAN DEBUG] Period {col_idx}: SAIBOR={saibor_rate*100:.4f}% + Spread={spread*100:.4f}% = Total Rate={annual_rate*100:.4f}%, Opening={opening:,.2f}, Interest={int_amt:,.2f}")

                    # Past effective end → already repaid
                    if effective_end_idx is not None and col_idx > effective_end_idx:
                        balance[col_idx] = 0.0
                        continue

                    interest[col_idx] = int_amt
                    _noi_this = noi.iloc[col_idx] if col_idx < len(noi) else 0

                    if effective_end_idx is not None and col_idx == effective_end_idx:
                        # Refinancing / asset sale — repay outstanding balance
                        repaid[col_idx] = opening
                        balance[col_idx] = 0.0
                        _ds = int_amt + opening
                        dscr[col_idx] = _noi_this / _ds if _ds > 0 else 0
                    elif is_io:
                        balance[col_idx] = opening
                        dscr[col_idx] = _noi_this / int_amt if int_amt > 0 else 0
                    else:
                        pp = min(monthly_principal, opening)
                        repaid[col_idx] = pp
                        balance[col_idx] = opening - pp
                        _ds = int_amt + pp
                        dscr[col_idx] = _noi_this / _ds if _ds > 0 else 0

                return dict(drawn=drawn, repaid=repaid, interest=interest,
                            fees=fees, balance=balance, dscr=dscr)

            # ================================================================
            # LOAN 1 SCHEDULE
            # ================================================================
            loan1_start_idx = _find_period_idx(loan1_start)
            loan1_refinance_idx = _find_period_idx(loan1_refinancing_date) if loan1_refinancing and loan1_refinancing_date else None
            loan1_end_idx = _find_period_idx(loan1_end) if loan1_end else (_num_periods - 1)

            # Effective end = earliest of: refinancing date, asset sale date
            # If neither, the loan simply amortizes until fully paid (no hard end / no balloon)
            loan1_effective_end_idx = None
            if loan1_refinancing and loan1_refinance_idx is not None:
                loan1_effective_end_idx = loan1_refinance_idx
            if asset_sale_date:
                sale_idx = _find_period_idx(asset_sale_date)
                if sale_idx is not None:
                    if loan1_effective_end_idx is None:
                        loan1_effective_end_idx = sale_idx
                    else:
                        loan1_effective_end_idx = min(loan1_effective_end_idx, sale_idx)

            _l1 = _build_loan_schedule(
                loan_amount=loan1_amount,
                annual_amort_pct=loan1_annual_amort_pct,
                interest_profile=loan1_interest_profile,
                loan_start_date=loan1_start,
                start_idx=loan1_start_idx,
                effective_end_idx=loan1_effective_end_idx,
                arrangement_fee=loan1_arrangement_fee,
                repayment_type="amortizing",
                spread=fixed_spread,
            )
            loan1_drawn_series = _l1["drawn"]
            loan1_repaid_series = _l1["repaid"]
            loan1_interest_series = _l1["interest"]
            loan1_fees_series = _l1["fees"]
            loan1_balance = _l1["balance"]
            loan1_dscr_series = _l1["dscr"]

            # ================================================================
            # LOAN 2 (REFINANCING) SCHEDULE
            # ================================================================
            refi_drawn_series = np.zeros(_num_periods)
            refi_repaid_series = np.zeros(_num_periods)
            refi_interest_series = np.zeros(_num_periods)
            refi_fees_series = np.zeros(_num_periods)
            refi_balance = np.zeros(_num_periods)
            refi_dscr_series = np.zeros(_num_periods)
            refi_loan_amount = 0.0

            if loan1_refinancing and loan1_refinance_idx is not None:
                # ---- NOI at refinance: sum last 12 months of NOI up to and including refinancing date ----
                refi_noi_12m = 0.0
                months_counted = 0
                for cidx in range(loan1_refinance_idx, -1, -1):
                    if months_counted >= 12:
                        break
                    refi_noi_12m += noi.iloc[cidx] if cidx < len(noi) else 0
                    months_counted += 1

                # ---- Conditional NOI Top-Up (same logic as Asset Sale) ----
                refi_noi_topup = 0.0
                refi_date_ts = _period_starts_ts[loan1_refinance_idx]
                print(f"\n   ╔══════════════════════════════════════════════════════════════╗")
                print(f"   ║  REFINANCING LOAN CALCULATION (NOI Top-Up)                  ║")
                print(f"   ╠══════════════════════════════════════════════════════════════╣")
                print(f"   ║  Refinance Date:           {pd.Timestamp(refi_date_ts).strftime('%d-%b-%Y'):>30s}  ║")
                print(f"   ║  Base NOI (LTM 12m):       {refi_noi_12m:>30,.2f}  ║")
                print(f"   ║  Cap Rate at Refinance:    {refi_cap_rate:>30.4f}  ║")
                print(f"   ║  LTV:                      {refi_ltv:>30.4f}  ║")
                print(f"   ║  NOI Top-Up Toggle (raw):  {str(refi.noi_top_up):>30s}  ║")
                print(f"   ╠══════════════════════════════════════════════════════════════╣")

                refi_topup_toggle = str(refi.noi_top_up or "").strip().lower() in ["yes", "true", "1"]
                if refi_topup_toggle:
                    try:
                        print(f"   ║  NOI Top-Up: ENABLED — computing adjustments at refi date ║")
                        print(f"   ║  Window: 12 months ending at {pd.Timestamp(refi_date_ts).strftime('%d-%b-%Y'):>28s}  ║")
                        print(f"   ╟──────────────────────────────────────────────────────────────╢")
                        vac_adj, relet_adj, rent_adj = fn_compute_noi_stabilization_adjustment(refi_date_ts)
                        raw_topup = vac_adj + relet_adj + rent_adj
                        refi_noi_topup = raw_topup

                        print(f"   ║  Step 1  Vacancy Top-Up:   {vac_adj:>30,.2f}  ║")
                        print(f"   ║  Steps 2-4 Reletting Ded:  {relet_adj:>30,.2f}  ║")
                        print(f"   ║  Step 5  Under/Over Rent:  {rent_adj:>30,.2f}  ║")
                        print(f"   ║  RAW Top-Up (1+2+3+4+5):  {raw_topup:>30,.2f}  ║")
                        print(f"   ╟──────────────────────────────────────────────────────────────╢")

                        # Structural vacancy deduction (same source as asset sale)
                        sv_pct_refi = 0.0
                        try:
                            sv_val = Global.NOIStabalizationAssumptions.structural_vacancy_allowance
                            if sv_val is not None and not pd.isna(sv_val):
                                sv_pct_refi = float(sv_val)
                        except (AttributeError, ValueError, TypeError):
                            pass
                        if sv_pct_refi <= 0:
                            try:
                                sv_val = Global.ValuationParameters.structural_vacancy_allowance
                                if sv_val is not None and not pd.isna(sv_val):
                                    sv_pct_refi = float(sv_val)
                            except (AttributeError, ValueError, TypeError):
                                pass
                        if sv_pct_refi > 1:
                            sv_pct_refi = sv_pct_refi / 100.0

                        gross_stab_refi = refi_noi_12m + refi_noi_topup
                        sv_deduction_refi = sv_pct_refi * gross_stab_refi
                        refi_noi_topup = refi_noi_topup - sv_deduction_refi

                        print(f"   ║  Structural Vacancy %:     {sv_pct_refi:>30.4f}  ║")
                        print(f"   ║  Gross Stab NOI (base+raw):{gross_stab_refi:>30,.2f}  ║")
                        print(f"   ║  SV Deduction:             {sv_deduction_refi:>30,.2f}  ║")
                        print(f"   ║  NET Top-Up (raw - SV ded):{refi_noi_topup:>30,.2f}  ║")
                    except Exception as e:
                        print(f"   ║  EXCEPTION: {e}")
                        import traceback; traceback.print_exc()
                        refi_noi_topup = 0.0
                else:
                    print(f"   ║  NOI Top-Up: DISABLED — using base NOI only              ║")

                adjusted_refi_noi = refi_noi_12m + refi_noi_topup
                valuation_at_refi = adjusted_refi_noi / refi_cap_rate if refi_cap_rate > 0 else 0.0
                ltv_max_loan = refi_ltv * valuation_at_refi
                refi_loan_amount = ltv_max_loan

                print(f"   ╠══════════════════════════════════════════════════════════════╣")
                print(f"   ║  FINAL CALCULATION:                                         ║")
                print(f"   ║  A. Base NOI (LTM):          {refi_noi_12m:>28,.2f}  ║")
                print(f"   ║  B. Net NOI Top-Up:          {refi_noi_topup:>28,.2f}  ║")
                print(f"   ║  C. Adjusted NOI (A+B):      {adjusted_refi_noi:>28,.2f}  ║")
                print(f"   ║  D. Cap Rate:                {refi_cap_rate:>28.4f}  ║")
                print(f"   ║  E. Valuation (C÷D):         {valuation_at_refi:>28,.2f}  ║")
                print(f"   ║  F. LTV:                     {refi_ltv:>28.4f}  ║")
                print(f"   ║  G. LTV Max Loan (E×F):      {ltv_max_loan:>28,.2f}  ║")
                print(f"   ╚══════════════════════════════════════════════════════════════╝\n")

                refi_start_idx = _find_period_idx(refi_start) if refi_start else loan1_refinance_idx
                refi_end_idx = _find_period_idx(refi_end) if refi_end else (_num_periods - 1)
                if asset_sale_date:
                    sale_idx_refi = _find_period_idx(asset_sale_date)
                    if sale_idx_refi is not None:
                        refi_end_idx = min(refi_end_idx, sale_idx_refi)

                refi_effective_end_idx = None
                if asset_sale_date:
                    sale_idx_check = _find_period_idx(asset_sale_date)
                    if sale_idx_check is not None:
                        refi_effective_end_idx = sale_idx_check

                # DSCR monitoring (does NOT reduce loan)
                def _compute_min_dscr(test_loan_size):
                    min_dscr_val = float('inf')
                    ob = test_loan_size
                    _refi_monthly_p = (refi_annual_amort_pct * test_loan_size / 12.0) if refi_annual_amort_pct > 0 else 0.0
                    for cidx in range(refi_start_idx, min(refi_end_idx + 1, _num_periods)):
                        if ob <= 0:
                            break
                        pd_date = _period_starts_ts[cidx]
                        saibor_r = fn_get_interest_rate_for_period(
                            refi_interest_profile, pd_date,
                            refi_start if refi_start else _period_starts_ts[refi_start_idx],
                            interest_rate_profiles
                        )
                        ar = saibor_r + fixed_spread
                        mr = ar / 12.0
                        monthly_interest = ob * mr
                        monthly_noi = noi.iloc[cidx] if cidx < len(noi) else 0
                        if refi_repayment_type.lower() == "interest only":
                            monthly_ds = monthly_interest
                        else:
                            _pp = min(_refi_monthly_p, ob) if _refi_monthly_p > 0 else 0.0
                            monthly_ds = monthly_interest + _pp
                        if monthly_ds > 0:
                            min_dscr_val = min(min_dscr_val, monthly_noi / monthly_ds)
                        if refi_repayment_type.lower() != "interest only":
                            ob = max(0, ob - _pp)
                    return min_dscr_val if min_dscr_val != float('inf') else 0

                refi_dscr_computed = _compute_min_dscr(refi_loan_amount)
                if refi_min_dscr > 0 and refi_dscr_computed < refi_min_dscr:
                    print(f"   DSCR ({refi_dscr_computed:.4f}) below min ({refi_min_dscr:.4f}) — monitoring only")

                Global.RefinancingAssumptions.noi_at_refinance = refi_noi_12m
                Global.RefinancingAssumptions.valuation_at_refinance = valuation_at_refi
                Global.RefinancingAssumptions.ltv_max_loan = ltv_max_loan
                Global.RefinancingAssumptions.dscr_computed = refi_dscr_computed

                refi_arrangement_fee = refi_arr_fee_pct * refi_loan_amount

                _l2 = _build_loan_schedule(
                    loan_amount=refi_loan_amount,
                    annual_amort_pct=refi_annual_amort_pct,
                    interest_profile=refi_interest_profile,
                    loan_start_date=refi_start if refi_start else _period_starts_ts[refi_start_idx],
                    start_idx=refi_start_idx,
                    effective_end_idx=refi_effective_end_idx,
                    arrangement_fee=refi_arrangement_fee,
                    repayment_type=refi_repayment_type,
                    spread=fixed_spread,
                )
                refi_drawn_series = _l2["drawn"]
                refi_repaid_series = _l2["repaid"]
                refi_interest_series = _l2["interest"]
                refi_fees_series = _l2["fees"]
                refi_balance = _l2["balance"]
                refi_dscr_series = _l2["dscr"]

                # Refinance surplus/shortfall info
                if loan1_refinance_idx >= 0:
                    loan1_balance_before_refi = loan1_balance[loan1_refinance_idx - 1] if loan1_refinance_idx > 0 else loan1_amount
                    refi_net_proceeds = refi_loan_amount - loan1_balance_before_refi

            # ================================================================
            # POPULATE CFF ROWS — positional (iloc) assignment
            # 15-row layout: no Capitalization of Arrangement Fees rows
            # ================================================================
            term_loan_drawn = pd.Series(loan1_drawn_series, index=range(_num_periods))
            term_loan_repaid = pd.Series(loan1_repaid_series, index=range(_num_periods))
            term_loan_interest = pd.Series(loan1_interest_series, index=range(_num_periods))
            term_loan_fees = pd.Series(loan1_fees_series, index=range(_num_periods))

            refi_drawn = pd.Series(refi_drawn_series, index=range(_num_periods))
            refi_repaid = pd.Series(refi_repaid_series, index=range(_num_periods))
            refi_interest = pd.Series(refi_interest_series, index=range(_num_periods))
            refi_fees = pd.Series(refi_fees_series, index=range(_num_periods))

            _cff_row_names = cashflow_from_financing.index.tolist()
            _cff_nrows = len(_cff_row_names)

            # Positional assignment — detect loan header positions dynamically
            # Find the two loan header rows by name to anchor the sub-rows
            _L1_HDR = None
            _L2_HDR = None
            for _ri, _rn in enumerate(_cff_row_names):
                if not isinstance(_rn, str):
                    continue
                _rn_l = _rn.strip().lower()
                if _rn_l in ("asset level term loan", "project level term loan") or (
                    "term loan" in _rn_l and _L1_HDR is None
                ):
                    _L1_HDR = _ri
                elif _rn_l in ("asset level refinancing facility", "project level revolver facility") or (
                    ("refinanc" in _rn_l or "revolver" in _rn_l) and _L2_HDR is None
                ):
                    _L2_HDR = _ri

            if _L1_HDR is not None and _L2_HDR is not None:
                # L1 data rows are the 4 rows immediately after L1 header
                _L1_DRAWN    = _L1_HDR + 1
                _L1_REPAID   = _L1_HDR + 2
                _L1_INTEREST = _L1_HDR + 3
                _L1_FEES     = _L1_HDR + 4
                # L2 data rows are the 4 rows immediately after L2 header
                _L2_DRAWN    = _L2_HDR + 1
                _L2_REPAID   = _L2_HDR + 2
                _L2_INTEREST = _L2_HDR + 3
                _L2_FEES     = _L2_HDR + 4
                # Equity and Net CFF — find by name
                _EQUITY = _NET_CFF = None
                for _ri, _rn in enumerate(_cff_row_names):
                    if isinstance(_rn, str):
                        _rn_l = _rn.strip().lower()
                        if _rn_l == "equity injection":
                            _EQUITY = _ri
                        elif _rn_l == "net cashflow from financing":
                            _NET_CFF = _ri
                _HAS_CAP_FEES_ROW = False
            else:
                print(f"   ⚠️ CFF header detection failed: L1_HDR={_L1_HDR}, L2_HDR={_L2_HDR}")
                print(f"   CFF row names: {_cff_row_names}")
                _L1_DRAWN = _L1_REPAID = _L1_INTEREST = _L1_FEES = None
                _L2_DRAWN = _L2_REPAID = _L2_INTEREST = _L2_FEES = None
                _EQUITY = _NET_CFF = None
                _HAS_CAP_FEES_ROW = False

            if _L1_DRAWN is not None:
                cashflow_from_financing.iloc[_L1_DRAWN, :]    = term_loan_drawn.values
                cashflow_from_financing.iloc[_L1_REPAID, :]   = (term_loan_repaid * -1).values
                cashflow_from_financing.iloc[_L1_INTEREST, :] = (term_loan_interest * -1).values
                cashflow_from_financing.iloc[_L1_FEES, :]     = (term_loan_fees * -1).values

                cashflow_from_financing.iloc[_L2_DRAWN, :]    = refi_drawn.values
                cashflow_from_financing.iloc[_L2_REPAID, :]   = (refi_repaid * -1).values
                cashflow_from_financing.iloc[_L2_INTEREST, :] = (refi_interest * -1).values
                cashflow_from_financing.iloc[_L2_FEES, :]     = (refi_fees * -1).values
            else:
                # Fallback: try iloc-based assignment using first two detected header positions
                # Even if only one header found, populate what we can
                print("   ⚠️ CFF: Using fallback row population")
                _data_row_idx = 0
                _loan_data = [
                    ("Loan 1", [
                        ("Principal Drawn", term_loan_drawn.values),
                        ("Principal Repaid", (term_loan_repaid * -1).values),
                        ("Interest Paid", (term_loan_interest * -1).values),
                        ("Arrangement Fees", (term_loan_fees * -1).values),
                    ]),
                    ("Loan 2", [
                        ("Principal Drawn", refi_drawn.values),
                        ("Principal Repaid", (refi_repaid * -1).values),
                        ("Interest Paid", (refi_interest * -1).values),
                        ("Arrangement Fees", (refi_fees * -1).values),
                    ]),
                ]
                _loan_section = 0
                for _ri, _rn in enumerate(_cff_row_names):
                    if not isinstance(_rn, str) or _rn.strip() == "":
                        continue
                    _rn_l = _rn.strip().lower()
                    # Skip header rows, assign the next 4 data rows
                    if _rn_l in ("equity injection", "net cashflow from financing"):
                        continue
                    # Check if this is a header-like row (not a data row name)
                    _is_header_like = any(kw in _rn_l for kw in [
                        "term loan", "refinanc", "revolver", "facility",
                        "senior", "loan 1", "loan 2",
                    ])
                    if _is_header_like and _loan_section < len(_loan_data):
                        _loan_label, _loan_rows = _loan_data[_loan_section]
                        for _offset, (_name, _vals) in enumerate(_loan_rows):
                            _target_idx = _ri + 1 + _offset
                            if _target_idx < _cff_nrows:
                                cashflow_from_financing.iloc[_target_idx, :] = _vals
                        _loan_section += 1

            # ================================================================
            # DYNAMIC EQUITY INJECTION ENGINE
            # ================================================================
            # Equity must cover:
            # 1. Equity portion of acquisition cost (Total Acq Cost - Debt Drawn)
            # 2. Arrangement fees (always cash outflow)
            # 3. Transaction costs
            # 4. Any period where CFO + CFI + CFF(excl equity) < 0

            equity_injection = np.zeros(_num_periods)
            opening_cash_series = np.zeros(_num_periods)
            closing_cash_series = np.zeros(_num_periods)
            cumulative_cash_balance = 0.0

            for col_idx in range(_num_periods):
                period_start = _period_starts_ts[col_idx]
                opening_cash_series[col_idx] = cumulative_cash_balance

                if asset_sale_date and period_start > asset_sale_date:
                    closing_cash_series[col_idx] = cumulative_cash_balance
                    continue

                period_cfo = net_cfo.iloc[col_idx] if col_idx < len(net_cfo) else 0
                period_cfi = net_cfi.iloc[col_idx] if col_idx < len(net_cfi) else 0

                debt_cf = (
                    loan1_drawn_series[col_idx]
                    - loan1_repaid_series[col_idx]
                    - loan1_interest_series[col_idx]
                    - loan1_fees_series[col_idx]
                    + refi_drawn_series[col_idx]
                    - refi_repaid_series[col_idx]
                    - refi_interest_series[col_idx]
                    - refi_fees_series[col_idx]
                )

                projected = cumulative_cash_balance + period_cfo + period_cfi + debt_cf

                if projected < 0:
                    equity_injection[col_idx] = abs(projected)
                    cumulative_cash_balance = 0.0
                else:
                    cumulative_cash_balance = projected

                closing_cash_series[col_idx] = cumulative_cash_balance

            if _EQUITY is not None:
                cashflow_from_financing.iloc[_EQUITY, :] = equity_injection
            else:
                fn_safe_set_row(cashflow_from_financing, "Equity Injection", equity_injection)

            # ================================================================
            # NET CASHFLOW FROM FINANCING
            # ================================================================
            net_cf_financing = (
                term_loan_drawn - term_loan_repaid - term_loan_interest - term_loan_fees +
                refi_drawn - refi_repaid - refi_interest - refi_fees +
                pd.Series(equity_injection, index=range(_num_periods))
            )
            if _NET_CFF is not None:
                cashflow_from_financing.iloc[_NET_CFF, :] = net_cf_financing.values
            else:
                fn_safe_set_row(cashflow_from_financing, "Net Cashflow from Financing", net_cf_financing.values)

            # ================================================================
            # FINANCING DEBUG SUMMARY + VALIDATION CHECKS
            # ================================================================
            total_equity_injected = np.sum(equity_injection)
            _total_l1_drawn = np.sum(loan1_drawn_series)
            _total_l1_repaid = np.sum(loan1_repaid_series)
            _total_l1_interest_cash = np.sum(loan1_interest_series)
            _total_l2_drawn = np.sum(refi_drawn_series)
            _total_l2_repaid = np.sum(refi_repaid_series)
            _total_l2_interest_cash = np.sum(refi_interest_series)

            print("\n" + "=" * 80)
            print("FINANCING MODULE - SUMMARY")
            print("=" * 80)

            # ---- Capital Structure ----
            print(f"   Capital Structure:")
            print(f"      Total Debt LTV:                {ltv_pct:>15.2%}")
            print(f"      Acquisition Price (for LTV):   {acq_price_scalar:>15,.2f}")
            print(f"      Transaction Costs:             {transaction_costs_scalar:>15,.2f}")
            print(f"      Total Acquisition Cost:        {total_acquisition_cost:>15,.2f}")
            print(f"      Debt (Loan 1 = LTV x Acq Price): {loan1_amount:>12,.2f}")
            print(f"      Loan 1 Arrangement Fee:        {loan1_arrangement_fee:>15,.2f}")

            # ---- Loan 1 Details ----
            print(f"   Loan 1:")
            print(f"      Start:                         {loan1_start}")
            print(f"      End:                           {loan1_end}")
            print(f"      Term (years):                  {loan1_term_months / 12:.1f}")
            print(f"      Amortization Duration (years): {loan1_amort_duration_years}")
            print(f"      Annual Amortization %:         {loan1_annual_amort_pct:>15.2%}")
            print(f"      Monthly Principal:             {(loan1_annual_amort_pct * loan1_amount / 12.0):>15,.2f}")
            print(f"      Interest Profile:              {loan1_interest_profile}")
            print(f"      Refinancing:                   {'Yes' if loan1_refinancing else 'No'}")
            if loan1_refinancing:
                print(f"      Refinancing Date:              {loan1_refinancing_date}")

            # ---- Loan 1 Balance Check ----
            print(f"   Loan 1 Validation Checks:")
            print(f"      Principal Drawn:               {_total_l1_drawn:>15,.2f}")
            print(f"      Principal Repaid (total):      {_total_l1_repaid:>15,.2f}")
            print(f"      Cash Interest Paid (total):    {_total_l1_interest_cash:>15,.2f}")
            print(f"      Start Idx: {loan1_start_idx}, End Idx: {loan1_effective_end_idx}")
            nz = np.nonzero(loan1_balance)[0]
            if len(nz) > 0:
                print(f"      Balance: first non-zero={nz[0]}({loan1_balance[nz[0]]:,.2f}), last={nz[-1]}({loan1_balance[nz[-1]]:,.2f})")

            # ---- Loan 2 (Refinancing) ----
            print(f"   Loan 2 (Refinancing):")
            if loan1_refinancing and loan1_refinance_idx is not None:
                print(f"      NOI at Refinance (last 12m):   {refi_noi_12m:>15,.2f}")
                if refi_topup_toggle:
                    print(f"      NOI Top-Up (net):              {refi_noi_topup:>15,.2f}")
                    print(f"      Adjusted NOI at Refinance:     {adjusted_refi_noi:>15,.2f}")
                print(f"      Valuation at Refinance:        {valuation_at_refi:>15,.2f}")
                print(f"      LTV Max Loan:                  {ltv_max_loan:>15,.2f}")
                print(f"      Final Loan Size:               {refi_loan_amount:>15,.2f}")
                print(f"      Repayment Type:                {refi_repayment_type}")
                print(f"      Amort Duration (years):        {refi_amort_duration_years}")
                print(f"      Annual Amortization %:         {refi_annual_amort_pct:>15.2%}")
                print(f"      Arrangement Fee:               {refi_arrangement_fee:>15,.2f}")
                print(f"      Refi Start Idx: {refi_start_idx}, End Idx: {refi_end_idx}")
                print(f"      Principal Drawn:               {_total_l2_drawn:>15,.2f}")
                print(f"      Principal Repaid:              {_total_l2_repaid:>15,.2f}")
                print(f"      Cash Interest Paid:            {_total_l2_interest_cash:>15,.2f}")
                _l1_bal_at_refi = loan1_balance[loan1_refinance_idx - 1] if loan1_refinance_idx > 0 else loan1_amount
                print(f"      Loan 1 Outstanding at Refi:    {_l1_bal_at_refi:>15,.2f}")
                _surplus_shortfall = refi_loan_amount - _l1_bal_at_refi
                if _surplus_shortfall >= 0:
                    print(f"      Surplus (Loan2 - Loan1 out):   {_surplus_shortfall:>15,.2f}")
                else:
                    print(f"      Shortfall (Loan1 out - Loan2): {abs(_surplus_shortfall):>15,.2f} -> equity covers")
            else:
                print(f"      (Refinancing disabled)")

            # ---- Equity ----
            print(f"   Equity:")
            print(f"      Total Equity Injected:         {total_equity_injected:>15,.2f}")
            # Show equity injection waterfall for key periods
            _eq_nz = np.nonzero(equity_injection)[0]
            if len(_eq_nz) > 0:
                print(f"      Equity Injection Periods:")
                for _ei_idx in _eq_nz[:10]:  # Show first 10
                    _ei_date = _period_starts_ts[_ei_idx].strftime('%Y-%m')
                    _ei_open = opening_cash_series[_ei_idx]
                    _ei_cfo = net_cfo.iloc[_ei_idx] if _ei_idx < len(net_cfo) else 0
                    _ei_cfi = net_cfi.iloc[_ei_idx] if _ei_idx < len(net_cfi) else 0
                    _ei_debt = (
                        loan1_drawn_series[_ei_idx] - loan1_repaid_series[_ei_idx]
                        - loan1_interest_series[_ei_idx] - loan1_fees_series[_ei_idx]
                        + refi_drawn_series[_ei_idx] - refi_repaid_series[_ei_idx]
                        - refi_interest_series[_ei_idx] - refi_fees_series[_ei_idx]
                    )
                    _ei_proj = _ei_open + _ei_cfo + _ei_cfi + _ei_debt
                    print(f"         [{_ei_idx}] {_ei_date}: Open={_ei_open:>12,.0f} + CFO={_ei_cfo:>10,.0f} + CFI={_ei_cfi:>10,.0f} + Debt={_ei_debt:>10,.0f} = {_ei_proj:>12,.0f} => Equity={equity_injection[_ei_idx]:>12,.0f}")
                if len(_eq_nz) > 10:
                    print(f"         ... and {len(_eq_nz) - 10} more periods")

            # ---- DSCR / ICR Summary ----
            print(f"   DSCR / ICR:")
            # Loan 1 — show DSCR during amortizing periods (exclude grace and balloon)
            _l1_dscr_amort = []
            for _di in range(_num_periods):
                if (loan1_start_idx is not None and _di >= loan1_start_idx
                        and _di < loan1_effective_end_idx and loan1_dscr_series[_di] > 0):
                    _l1_dscr_amort.append(loan1_dscr_series[_di])
            if _l1_dscr_amort:
                print(f"      Loan 1 Min DSCR (amortizing): {min(_l1_dscr_amort):>12.4f}")
                print(f"      Loan 1 Avg DSCR (amortizing): {sum(_l1_dscr_amort)/len(_l1_dscr_amort):>12.4f}")
            else:
                print(f"      Loan 1 DSCR: N/A (no amortizing periods)")
            # Loan 2 — show DSCR/ICR (exclude balloon)
            _l2_dscr_excl_balloon = []
            _l2_label = "ICR" if refi_repayment_type.lower() == "interest only" else "DSCR"
            if loan1_refinancing and loan1_refinance_idx is not None:
                for _di in range(_num_periods):
                    if refi_dscr_series[_di] > 0 and _di != refi_end_idx:
                        _l2_dscr_excl_balloon.append(refi_dscr_series[_di])
            if _l2_dscr_excl_balloon:
                print(f"      Loan 2 Min {_l2_label}:              {min(_l2_dscr_excl_balloon):>12.4f}")
                print(f"      Loan 2 Avg {_l2_label}:              {sum(_l2_dscr_excl_balloon)/len(_l2_dscr_excl_balloon):>12.4f}")
            else:
                print(f"      Loan 2 {_l2_label}: N/A")

            # ---- CFF Row Totals ----
            print(f"   CFF Totals:")
            print(f"      L1 Drawn:    {_total_l1_drawn:>12,.0f}  L1 Repaid: {_total_l1_repaid:>12,.0f}  L1 Int: {_total_l1_interest_cash:>12,.0f}")
            print(f"      L2 Drawn:    {_total_l2_drawn:>12,.0f}  L2 Repaid: {_total_l2_repaid:>12,.0f}  L2 Int: {_total_l2_interest_cash:>12,.0f}")
            print(f"      Equity:      {total_equity_injected:>12,.0f}")
            print("=" * 80)

            # Print timing summary
            print_timing_summary()
            
            return {
                "cashflow_from_operations": cashflow_from_operations,
                "cashflow_from_investments": cashflow_from_investments,
                "cashflow_from_financing": cashflow_from_financing,
                "loan1_dscr": pd.Series(loan1_dscr_series, index=range(_num_periods)),
                "loan2_dscr": pd.Series(refi_dscr_series, index=range(_num_periods)),
                "opening_cash": pd.Series(opening_cash_series, index=range(_num_periods)),
                "closing_cash": pd.Series(closing_cash_series, index=range(_num_periods)),
            }
        
        def fn_run_module_10():
            """Initialize and run Module 10 - Cashflow."""
            # global _num_periods, _period_starts_ts, _period_ends_ts
            
            # print("=" * 60)
            # print("MODULE 10: CASHFLOW")
            # print("=" * 60)
            
            # Initialize dependencies - ensure Module 02 is run
            # if model_timeline_me is None:
            #     print("\n📂 Running Module 02 to load inputs...")
            #     from AM_Co_02_input_assignment_module import fn_run_module_02
            #     fn_run_module_02()
            
            # Initialize module constants
            # _num_periods = len(model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # Initialize dataframes
            fn_initialize_dataframes()
            
            # Compute all cashflows
            results = fn_compute_all_cashflows()
            
            return results
        
        # Run Module 10 to compute cashflows
        cashflow_results = fn_run_module_10()
        # print(cashflow_results['cashflow_from_operations'])

        # -----------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------

        def fn_get_named_range_value(assumptions_df, range_name):
            """
                Get a specific named range value from assumptions DataFrame.

                Parameters:
                -----------
                assumptions_df : pd.DataFrame
                    Assumptions DataFrame with ['name', 'value'] columns
                range_name : str
                    Name of the named range to retrieve

                Returns:
                --------
                Value from the named range (can be scalar, list, or nested list)
                """
            try:
                return assumptions_df.loc[assumptions_df["name"] == range_name, "value"].iloc[0]
            except (IndexError, KeyError):
                return None

        # ============================================================================================
        # CASHFLOW DATAFRAMES INITIALIZATION
        # ============================================================================================

        # Get the columns from model_timeline_me
        columns = model_timeline_me.index

        # Extract results from fn_run_module_10() — these are the computed DataFrames
        # Do NOT re-create empty DataFrames here (that was overwriting computed results)
        if cashflow_results is not None:
            cashflow_from_operations = cashflow_results.get("cashflow_from_operations")
            cashflow_from_investments = cashflow_results.get("cashflow_from_investments")
            cashflow_from_financing = cashflow_results.get("cashflow_from_financing")
        else:
            print("⚠️ WARNING: cashflow_results is None — fn_run_module_10() likely crashed!")
            # Create empty fallback DataFrames
            cashflow_from_operations = pd.DataFrame(columns=columns)
            cashflow_from_investments = pd.DataFrame(columns=columns)
            cashflow_from_financing = pd.DataFrame(columns=columns)

        cashflow_from_operations = cashflow_from_operations.fillna(0)
        cashflow_from_investments = cashflow_from_investments.fillna(0)
        cashflow_from_financing = cashflow_from_financing.fillna(0)

        # ---- Verification: confirm data actually reached the DataFrames ----
        _cfo_sum = cashflow_from_operations.select_dtypes(include='number').sum().sum() if not cashflow_from_operations.empty else 0
        _cfi_sum = cashflow_from_investments.select_dtypes(include='number').sum().sum() if not cashflow_from_investments.empty else 0
        _cff_sum = cashflow_from_financing.select_dtypes(include='number').sum().sum() if not cashflow_from_financing.empty else 0
        print(f"\n   OUTPUT VERIFICATION: CFO total={_cfo_sum:,.0f}, CFI total={_cfi_sum:,.0f}, CFF total={_cff_sum:,.0f}")
        if _cff_sum == 0:
            print(f"   ⚠️ CFF is ALL ZEROS — data did not reach the DataFrame!")
        else:
            print(f"   ✅ CFF has non-zero values — financing data is in the output")

        # Convert to object dtype so we can mix numbers and empty strings for blank/header rows
        cashflow_from_operations = cashflow_from_operations.astype(object)
        cashflow_from_investments = cashflow_from_investments.astype(object)
        cashflow_from_financing = cashflow_from_financing.astype(object)

        # Clear blank rows and section header rows — they should show empty in Excel
        # Uses dynamic detection: blanks ("") + section headers (position 0 if non-data,
        # and first non-blank after each blank group if non-data). This works regardless
        # of template naming (e.g. "Project Level" vs "Asset Level").
        def _detect_clear_positions(line_items):
            """Detect positions of header and blank rows that should be cleared to ''.
            Blanks: all positions where label is ''.
            Headers: position 0 (if non-data) + first non-blank after each blank group (if non-data).
            Data rows containing these keywords are never cleared.
            """
            positions = set()
            _data_keywords = ["equity", "net cashflow", "acquisition", "total capex",
                              "total operating", "asset acquisition", "net operating",
                              "net lease"]
            _header_keywords = ["term loan", "refinancing facility", "revolver facility",
                                "refinanc", "asset acquisition costs"]
            def _is_data_row(name):
                name_lower = name.lower()
                if any(kw in name_lower for kw in _header_keywords):
                    return False
                return any(kw in name_lower for kw in _data_keywords)
            # All blank rows
            for i, label in enumerate(line_items):
                if label == "":
                    positions.add(i)
            # Position 0: header if non-blank and not a known data row
            if line_items and line_items[0] != "" and not _is_data_row(line_items[0]):
                positions.add(0)
            # After each blank group: first non-blank is a section header (unless it's data)
            found_blank = False
            for i in range(1, len(line_items)):
                if line_items[i] == "":
                    found_blank = True
                elif found_blank:
                    if not _is_data_row(line_items[i]):
                        positions.add(i)
                    found_blank = False
            # Explicitly clear any row that matches a known header keyword
            # (covers loan headers not preceded by a blank row)
            for i, label in enumerate(line_items):
                if isinstance(label, str) and label.strip() != "":
                    if any(kw in label.strip().lower() for kw in _header_keywords):
                        positions.add(i)
            return positions

        for df in [cashflow_from_operations, cashflow_from_investments, cashflow_from_financing]:
            if df is not None and not df.empty:
                items = df.index.tolist()
                if items:
                    clear_pos = _detect_clear_positions(items)
                    for pos in clear_pos:
                        if pos < len(df):
                            df.iloc[pos] = ""

        # print(cashflow_from_investments)

        model_timeline_me["Period Start"] = model_timeline_me[
            "Period Start"
        ].dt.strftime("%Y-%m-%d")
        model_timeline_me["Period End"] = model_timeline_me["Period End"].dt.strftime(
            "%Y-%m-%d"
        )

        model_timeline_ye["Period Start"] = model_timeline_ye[
            "Period Start"
        ].dt.strftime("%Y-%m-%d")
        model_timeline_ye["Period End"] = model_timeline_ye["Period End"].dt.strftime(
            "%Y-%m-%d"
        )

        o_monthly_timtline = model_timeline_me.T
        o_yearly_timeline = model_timeline_ye.T

        def df_to_json_with_index(df: pd.DataFrame):
            # Replace NaN with "" so header/blank rows serialize as empty strings
            df_clean = df.fillna("")
            return {
                "index": df_clean.index.tolist(),
                "columns": df_clean.columns.tolist(),
                "data": df_clean.values.tolist(),
            }

        def fn_copy_output_template_tab(payload):
            """
                Paste values into the named ranges in the template sheet first,
                then create a copy of the template sheet as 'Cashflow Statement'.
                """

        try:
            # Load the workbook
            # wb = load_workbook(file_path)

            year_mapping = model_timeline_me.loc[:, "Year"]

            # Update the columns of the monthly DataFrames to reflect the 'Year'
            cashflow_from_operations.columns = year_mapping
            cashflow_from_investments.columns = year_mapping
            cashflow_from_financing.columns = year_mapping

            # ================================================================
            # HOSPITALITY P&L — zero-filled output for non-hospitality models
            # When assetco and hospitality share the same input sheet, the
            # hospitality P&L named ranges must be written with zeros so that
            # stale data from a previous run is cleared.
            # ================================================================
            hospitality_pl = None
            _hosp_pl_items = fn_get_line_items_from_named_range("o.hospitality.pl.names")
            if _hosp_pl_items:
                # Known header rows in the hospitality P&L (should be "" not 0)
                _PL_HEADER_ROWS = {
                    "operating metrics", "operating revenue",
                    "departmental expenses", "undistributed expenses",
                    "management fees",
                    "non-operating income & expenses",
                    "non operating income and expenses",
                }
                hospitality_pl = pd.DataFrame(index=_hosp_pl_items, columns=year_mapping)
                for idx in hospitality_pl.index:
                    if isinstance(idx, str) and idx.strip() != "":
                        if idx.strip().lower() in _PL_HEADER_ROWS:
                            hospitality_pl.loc[idx, :] = ""
                        else:
                            hospitality_pl.loc[idx, :] = 0.0
                    else:
                        hospitality_pl.loc[idx, :] = ""
                print(f"   ✅ Hospitality P&L: {len(_hosp_pl_items)} line items → zeros (non-hospitality mode)")

            # Define the monthly DataFrames
            monthly_dfs = {
                "Cashflow from Operations": ("o.assetco.cfo.me", cashflow_from_operations),
                "Cashflow from Investments": ("o.assetco.cfi.me", cashflow_from_investments),
                "Cashflow from Financing": ("o.assetco.cff.me", cashflow_from_financing),
                "Monthly Timeline": (
                    "o.assetco.model.timeline.me",
                    o_monthly_timtline,
                ),  # Add Monthly Timeline
            }

            # Add Hospitality P&L zeros if the named range exists
            if hospitality_pl is not None:
                monthly_dfs["Hospitality P&L"] = ("o.hospitality.pl.me", hospitality_pl)

            # Calculate annual sums for each DataFrame
            # Header/blank rows (containing "") must stay "" after grouping
            # Columns are integer period indices (0..N-1); map to calendar years
            # using model_timeline_me["Year"] so monthly values aggregate correctly.
            _col_to_year = {i: int(model_timeline_me.iloc[i]["Year"]) for i in range(len(model_timeline_me))}
            _unique_years = sorted(set(_col_to_year.values()))

            def _annual_sum(df):
                """Group monthly columns by calendar year, summing numeric rows,
                preserving blank/header rows as empty strings."""
                result_rows = []
                result_index = []
                for i in range(len(df)):
                    row = df.iloc[i]
                    idx_name = df.index[i]
                    # Check if this row is a header/blank row (all values are "")
                    is_header = all(v == "" for v in row.values)
                    if is_header:
                        result_rows.append([""] * len(_unique_years))
                    else:
                        # Sum values by year (use positional index, not column value,
                        # because columns may already be year labels after reassignment)
                        year_sums = {y: 0.0 for y in _unique_years}
                        for col_pos, val in enumerate(row.values):
                            yr = _col_to_year.get(col_pos)
                            if yr is not None:
                                try:
                                    year_sums[yr] += float(val)
                                except (ValueError, TypeError):
                                    pass
                        result_rows.append([year_sums[y] for y in _unique_years])
                    result_index.append(idx_name)
                return pd.DataFrame(result_rows, index=result_index, columns=_unique_years)

            annual_dfs = {
                "Cashflow from Operations": (
                    "o.assetco.cfo.ye",
                    _annual_sum(cashflow_from_operations),
                ),
                "Cashflow from Investments": (
                    "o.assetco.cfi.ye",
                    _annual_sum(cashflow_from_investments),
                ),
                "Cashflow from Financing": (
                    "o.assetco.cff.ye",
                    _annual_sum(cashflow_from_financing),
                ),
                "Yearly Timeline": (
                    "o.assetco.model.timeline.ye",
                    o_yearly_timeline,
                ),  # Add Yearly Timeline
            }

            # Add Hospitality P&L annual zeros if the named range exists
            if hospitality_pl is not None:
                annual_dfs["Hospitality P&L"] = (
                    "o.hospitality.pl.ye",
                    _annual_sum(hospitality_pl),
                )
                
            final_output = {
                "assetco_inputs": {
                    "acquisition_date": (Global.ModelInputs.acquisition_date).strftime("%Y-%m-%d") if Global.ModelInputs.acquisition_date else None,
                    "holding_period": Global.ModelInputs.holding_period,
                    "asset_sale_date": (Global.ModelInputs.asset_sale_date).strftime("%Y-%m-%d") if Global.ModelInputs.asset_sale_date else None,
                    "acquisition_price": Global.AcquisitionModule.acquisition_price,
                    "residual_value": Global.ValuationParameters.residual_value * Global.AcquisitionModule.acquisition_price if Global.ValuationParameters.residual_value is not None else 0.0,
                    "asset_unique_id": Global.AssetDetails.asset_id,
                    "devco_inclusion": Global.AssetDetails.devco_inclusion,
                    "assetco_inclusion": Global.AssetDetails.assetco_inclusion,
                    "jvjda_inclusion": Global.AssetDetails.jvjda_inclusion,
                    "venture_type": Global.AssetDetails.venture_type,
                    "jv_name": Global.AssetDetails.jv_name,
                    "assetco_jv_inclusion": Global.AssetDetails.assetco_jv_inclusion,
                },
                "monthly_dfs": {
                    key: (code, df_to_json_with_index(df))
                    for key, (code, df) in monthly_dfs.items()
                },
                "annual_dfs": {
                    key: (code, df_to_json_with_index(df))
                    for key, (code, df) in annual_dfs.items()
                },
            }
            
            _reset_run_cache()
            return final_output

        except Exception as e:
            _reset_run_cache()
            return print(f"Failed to initialise values {e}\n{traceback.format_exc()}")

        # print("Model calculation performed successfully.")
        # fn_copy_output_template_tab(payload)

    except Exception as e:
        _reset_run_cache()
        return print(f"Failed to initialise values {e}\n{traceback.format_exc()}")


def fninitialising_all_values(payload,is_save):
    try:
        # import json
        # with open("assetco_payload.json", "w", encoding="utf-8") as f:
        #     json.dump(payload, f, indent=2, ensure_ascii=False)
        # raise breakpoint("Debug: payload dumped to payload_debug.json")
        output = wrapper_for_vars(payload, is_save)
        return output
    except Exception as e:
        print(f"Error in initialising all values: {e}")
        return None
