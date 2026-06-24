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
# GLOBAL CLASS WITH SUBCLASSES  (Hospitality Model)
# ============================================================================================

class Global:

    # =========================================================
    # MODEL INPUTS
    # =========================================================
    class ModelInputs:
        analysis_type = None
        model_start_period = None
        model_period = None
        no_of_months_in_a_year = None
        model_end_period = None
        asset_acquisition_dateanalysis_date = None
        asset_holding_period = None
        asset_sale_date = None
        operation_start = None
        override_option = None

    # =========================================================
    # ASSET DETAILS
    # =========================================================
    class AssetDetails:
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

    # =========================================================
    # ACQUISITION MODULE
    # =========================================================
    class AcquisitionModule:
        acquisition_price_assumption = None
        transfers_tax__stamp_duty_assumption = None
        legal_fees_assumption = None
        brokerage_assumption = None
        due_diligence_costs_assumption = None
        acquisition_price_transaction_date = None
        transfers_tax__stamp_duty_transaction_date = None
        legal_fees_transaction_date = None
        brokerage_transaction_date = None
        due_diligence_costs_transaction_date = None

    # =========================================================
    # VALUATION PARAMETERS
    # =========================================================
    class ValuationParameters:
        valuation_date_assumption = None
        discount_rate_assumption = None
        exit_yield_assumption = None
        ebidta_less_reserve_escalation_assumption = None
        ebidta_less_reserve_top_up_assumption = None
        ebidta_less_reserve_top_up_value_assumption = None
        disposal_cost_assumption = None

    # =========================================================
    # CAPITAL EXPENDITURE
    # =========================================================
    class CapitalExpenditure:
        start_date_maintenance_capex_1 = None
        capex_duration_maintenance_capex_1 = None
        actual_capex_maintenance_capex_1 = None
        start_date_maintenance_capex_2 = None
        capex_duration_maintenance_capex_2 = None
        actual_capex_maintenance_capex_2 = None
        start_date_maintenance_capex_3 = None
        capex_duration_maintenance_capex_3 = None
        actual_capex_maintenance_capex_3 = None
        start_date_maintenance_capex_4 = None
        capex_duration_maintenance_capex_4 = None
        actual_capex_maintenance_capex_4 = None

    # =========================================================
    # PRE-OPENING EXPENSES
    # =========================================================
    class PreOpeningExpenses:
        expense__schedules = None

    # =========================================================
    # ROOM TYPE
    # =========================================================
    class RoomType:
        room_size_deluxe = None
        keys_deluxe = None
        gross_leasable_area_deluxe = None
        adr_deluxe = None
        guest_capacity_deluxe = None
        room_size_economy = None
        keys_economy = None
        gross_leasable_area_economy = None
        adr_economy = None
        guest_capacity_economy = None
        room_size_executive = None
        keys_executive = None
        gross_leasable_area_executive = None
        adr_executive = None
        guest_capacity_executive = None
        room_size_royal_suite = None
        keys_royal_suite = None
        gross_leasable_area_royal_suite = None
        adr_royal_suite = None
        guest_capacity_royal_suite = None
        room_size_suite = None
        keys_suite = None
        gross_leasable_area_suite = None
        adr_suite = None
        guest_capacity_suite = None
        room_size_type_6 = None
        keys_type_6 = None
        gross_leasable_area_type_6 = None
        adr_type_6 = None
        guest_capacity_type_6 = None
        room_size_type_7 = None
        keys_type_7 = None
        gross_leasable_area_type_7 = None
        adr_type_7 = None
        guest_capacity_type_7 = None
        room_size_type_8_ = None
        keys_type_8_ = None
        gross_leasable_area_type_8_ = None
        adr_type_8_ = None
        guest_capacity_type_8_ = None
        room_size_type_9 = None
        keys_type_9 = None
        gross_leasable_area_type_9 = None
        adr_type_9 = None
        guest_capacity_type_9 = None
        room_size_type_10 = None
        keys_type_10 = None
        gross_leasable_area_type_10 = None
        adr_type_10 = None
        guest_capacity_type_10 = None

    # =========================================================
    # ROOM REVENUE ASSUMPTIONS
    # =========================================================
    class RoomRevenueAssumptions:
        start_date = None
        gross_leasable_area_per_room = None
        total_gross_leasable_area = None
        rooms_available = None
        average_adr_ = None
        adr_escalation_profile = None
        occupancy_schedule = None
        guest_occupancy_ratio = None

    # =========================================================
    # F&B REVENUE ASSUMPTIONS
    # =========================================================
    class FBRevenueAssumptions:
        in_room_dining__start_date = None
        in_room_dining__revenue_basis = None
        in_room_dining__percentage_of_room_revenue = None
        in_room_dining__inhouse_guest_capture_rate_in_room_dining = None
        in_room_dining__avg_order_value = None
        in_room_dining__escalation_profile = None
        venue__fb_start_date = None
        venue__fb_revenue_basis = None
        venue__fb_percentage_of_room_revenue = None
        venue__fb_venue_capacity = None
        venue__fb_average_daily_walkin_guests = None
        venue__fb_avg_order_value = None
        venue__fb_escalation_profile = None
        other_fb_revenue_start_date = None
        other_fb_revenue_percentage_of_room_revenue = None

    # =========================================================
    # OOD (Other Operating Department) REVENUE ASSUMPTIONS
    # =========================================================
    class OODRevenueAssumptions:
        golf_revenue_start_date = None
        golf_revenue_revenue_basis = None
        golf_revenue__of_room_revenue = None
        golf_revenue_inhouse_guest_capture_rate_golf = None
        golf_revenue_avg_fee_per_guest = None
        golf_revenue_escalation_profile = None
        spa__wellness_start_date = None
        spa__wellness_revenue_basis = None
        spa__wellness__of_room_revenue = None
        spa__wellness_inhouse_guest_capture_rate_spa__wellness = None
        spa__wellness_avg_spa_spend_per_guest = None
        spa__wellness_escalation_profile = None
        laundry_revenue_start_date = None
        laundry_revenue_revenue_basis = None
        laundry_revenue__of_room_revenue = None
        laundry_revenue_inhouse_guest_capture_rate_laundry = None
        laundry_revenue_avg_laundry_spend_per_guest = None
        laundry_revenue_escalation_profile = None
        banquet__conference_revenue_start_date = None
        banquet__conference_revenue_no_of_bookings = None
        banquet__conference_revenue_average_charge_per_event = None
        banquet__conference_revenue_escalation_profile = None
        other_operating_revenue_minor_operating_revenue = None
        other_operating_revenue_cancellation_charges = None
        other_operating_revenue_miscellaneous_income = None
        parking_revenue_start_date = None
        parking_revenue_no_of_bays = None
        parking_revenue_rate_per_month = None
        parking_revenue_occupancy_profile = None

    # =========================================================
    # PARKING REVENUE
    # =========================================================
    class ParkingRevenue:
        parking_revenue_parking_rate_escalation = None
        parking_revenue_parking_revenue_actuals = None

    # =========================================================
    # OTHER INCOME
    # =========================================================
    class OtherIncome:
        other_income_1_start_date = None
        other_income_1_incomeexpense_as_percentage_of_total_revenue = None
        other_income_1_override_schedule = None
        other_income_2_start_date = None
        other_income_2_incomeexpense_as_percentage_of_total_revenue = None
        other_income_2_override_schedule = None
        other_income_3_start_date = None
        other_income_3_incomeexpense_as_percentage_of_total_revenue = None
        other_income_3_override_schedule = None
        other_expense_1_start_date = None
        other_expense_1_incomeexpense_as_percentage_of_total_revenue = None
        other_expense_1_override_schedule = None
        other_expense_2_start_date = None
        other_expense_2_incomeexpense_as_percentage_of_total_revenue = None
        other_expense_2_override_schedule = None
        other_expense_3_start_date = None
        other_expense_3_incomeexpense_as_percentage_of_total_revenue = None
        other_expense_3_override_schedule = None

    # =========================================================
    # DEPARTMENTAL EXPENSE ASSUMPTIONS
    # =========================================================
    class DepartmentalExpenseAssumptions:
        room_expense_percentage_of_rooms_revenue = None
        room_expense_override_schedule = None
        fb_expense_fixed_percentage_of_fb_revenue = None
        fb_expense_override_schedule = None

    # =========================================================
    # OTHER OPERATING DEPARTMENT EXPENSE ASSUMPTIONS
    # =========================================================
    class OtherOperatingDepartmentExpenseAssumptions:
        golf_expense_percentage_of_golf_revenue = None
        golf_expense_override_schedule = None
        spa__wellness_expense_percentage_of_spa__wellness_revenue = None
        spa__wellness_expense_override_schedule = None
        banquet__conference__expense_banquet__conference__expense = None
        laundry_expense_percentage_of_laundry_revenue = None
        laundry_expense_override_schedule = None
        other_departmental_expenses_other_expenses = None
        other_departmental_expenses_override_schedule = None
        parking_opex_parking_opex_type = None
        parking_opex_fixed_parking_opex = None
        parking_opex_parking_opex_profile = None
        parking_opex_parking_opex_actuals = None

    # =========================================================
    # HOSPITALITY UNDISTRIBUTED EXPENSE ASSUMPTIONS
    # =========================================================
    class HospitalityUndistributedExpenseAssumptions:
        admin__general_expense_start_date = None
        admin__general_expense_percentage_of_total_revenue = None
        admin__general_expense_override_schedule = None
        sales_and_marketing_expense_start_date = None
        sales_and_marketing_expense_percentage_of_total_revenue = None
        sales_and_marketing_expense_override_schedule = None
        sales_and_marketing_expense_sm_cost_components = None
        sales_and_marketing_expense_franchise_and_affiliation_advertising = None
        sales_and_marketing_expense_loyalty_programs = None
        sales_and_marketing_expense_other_expense_sm_expense = None
        info__telecom_system_expense_start_date = None
        info__telecom_system_expense_percentage_of_total_revenue = None
        info__telecom_system_expense_override_schedule = None
        utility_costs_start_date = None
        utility_costs_percentage_of_total_revenue = None
        utility_costs_override_schedule = None
        utility_costs__utility_costs_components = None
        utility_costs_electricity = None
        utility_costs_gas = None
        utility_costs_water__sewer = None
        utility_costs_other_expense_utility = None

    # =========================================================
    # BASE MANAGEMENT FEES
    # =========================================================
    class BaseManagementFees:
        base_management_fees_start_date = None
        base_management_fees_fixed_ = None
        base_management_fees_override_schedule = None

    # =========================================================
    # HOSPITALITY OTHER ASSUMPTIONS
    # =========================================================
    class HospitalityOtherAssumptions:
        insurance_start_date = None
        insurance_profiles = None
        insurance_override_schedule = None
        ffe_reserves_start_date = None
        ffe_reserves_profiles = None
        ffe_reserves_override_schedule = None
        capital_reserves_start_date = None
        capital_reserves_profiles = None
        capital_reserves_override_schedule = None
        hospitality_other_assumptions_depreciation__amortization = None
        hospitality_other_assumptions_changes_in_working_capital = None
        hospitality_other_assumptions_income_tax = None

    # =========================================================
    # INCENTIVE FEES ASSUMPTIONS
    # =========================================================
    class IncentiveFeesAssumptions:
        min_gop_gop__20__0 = None
        min_gop_gop__20_but__30__4 = None
        min_gop_gop__30_but__40__6 = None
        min_gop__40_but_45_8 = None
        min_gop_gop__45__10 = None
        max_gop_gop__20__0 = None
        max_gop_gop__20_but__30__4 = None
        max_gop_gop__30_but__40__6 = None
        max_gop__40_but_45_8 = None
        max_gop_gop__45__10 = None
        incentive_fees_gop__20__0 = None
        incentive_fees_gop__20_but__30__4 = None
        incentive_fees_gop__30_but__40__6 = None
        incentive_fees__40_but_45_8 = None
        incentive_fees_gop__45__10 = None

    # =========================================================
    # FINANCING MODULE (Capital Structure + Loan 1 + Refinancing)
    # =========================================================
    class FinancingModule:
        capital_structure_total_debt_ltv = None
        capital_structure_total_equity = None
        financing_assumptions_loan_1_loan_raise_date = None
        financing_assumptions_loan_1_loan_term = None
        financing_assumptions_loan_1_loan_end = None
        financing_assumptions_loan_1_amortization_duration = None
        financing_assumptions_loan_1_annual_amortization = None
        financing_assumptions_loan_1_balloon_payment = None
        financing_assumptions_loan_1_dscr = None
        financing_assumptions_loan_1_base_interest_rate = None
        financing_assumptions_loan_1_arrangement_fees = None
        financing_assumptions_loan_1_loan_refinancing_ = None
        financing_assumptions_loan_1_loan_refinancing_date = None
        refinancing_assumptions_ebitda_less_reserves_at_refinanced_date = None
        refinancing_assumptions_cap_rate_at_refinanced = None
        refinancing_assumptions_valuation_at_refinanced = None
        refinancing_assumptions_ltv = None
        refinancing_assumptions_ltv_max_loan = None
        refinancing_assumptions_min_dscr = None
        refinancing_assumptions_dscr_computed = None
        refinancing_assumptions_repayment_type = None
        refinancing_assumptions_loan_start = None
        refinancing_assumptions_loan_term = None
        refinancing_assumptions_loan_end = None
        refinancing_assumptions_amortization_duration = None
        refinancing_assumptions_amortization_percentage = None
        refinancing_assumptions_balloon_payment = None
        refinancing_assumptions_refinanced_interest_rate = None
        refinancing_assumptions_arrangement_fees = None


# NOTE: No shim/proxy classes needed â€” hospitality code directly uses
# Global subclasses with their native attribute names.
# Unit class removed for hospitality model (no tenant/lease structure).
# Hospitality model uses room-based revenue instead of unit-based leases.


def wrappper_for_vars(payload):
    try:
        
        print ("Loading Hospitality Model v3...")

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
            _raw_count = len(payload) if isinstance(payload, list) else 0
            _first_50 = []
            for entry in payload:
               
                name = entry.get("name")
                if len(_first_50) < 50:
                    _first_50.append(name)

                # Accept ALL named ranges from the payload â€” the workbook may use
                # a.assetco.*, dd.assetco.*, o.assetco.* OR a.hospitality.*, etc.
                # No filtering needed; the add-in only sends relevant ranges.
                if not name:
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

            # -- COMPREHENSIVE DEBUG LOGGING ----------------------------------
            print("\n" + "=" * 80)
            print("DEBUG: NAMED RANGE LOADING DIAGNOSTICS")
            print("=" * 80)
            print(f"  Raw payload entries:        {_raw_count}")
            print(f"  First 50 names in payload:  {_first_50}")
            print(f"  After filter + dedup:       {len(named_values)}")

            # Category breakdown
            _cat_a_hosp = [n for n, _ in named_values if str(n).startswith("a.hospitality.")]
            _cat_a_assetco = [n for n, _ in named_values if str(n).startswith("a.assetco.")]
            _cat_dd_hosp = [n for n, _ in named_values if str(n).startswith("dd.hospitality.")]
            _cat_dd_assetco = [n for n, _ in named_values if str(n).startswith("dd.assetco.")]
            _cat_s = [n for n, _ in named_values if str(n).startswith("s.")]
            _cat_o_hosp = [n for n, _ in named_values if str(n).startswith("o.hospitality.")]
            _cat_o_assetco = [n for n, _ in named_values if str(n).startswith("o.assetco.")]
            print(f"  a.hospitality.*   : {len(_cat_a_hosp)}")
            print(f"  a.assetco.*       : {len(_cat_a_assetco)}")
            print(f"  dd.hospitality.*  : {len(_cat_dd_hosp)}")
            print(f"  dd.assetco.*      : {len(_cat_dd_assetco)}")
            print(f"  s.*               : {len(_cat_s)}")
            print(f"  o.hospitality.*   : {len(_cat_o_hosp)}")
            print(f"  o.assetco.*       : {len(_cat_o_assetco)}")

            # Expected ranges â€“ check found vs missing
            _EXPECTED_RANGES = [
                # Output ranges (critical)
                "o.assetco.cfo.names", "o.assetco.cfo.me", "o.assetco.cfo.ye",
                "o.assetco.cfi.names", "o.assetco.cfi.me", "o.assetco.cfi.ye",
                "o.assetco.cff.names", "o.assetco.cff.me", "o.assetco.cff.ye",
                "o.assetco.model.timeline.me", "o.assetco.model.timeline.ye",
                "o.hospitality.pl.names", "o.hospitality.pl.me", "o.hospitality.pl.ye",
                # Key assumption ranges (assetco namespace â€” current workbook)
                "a.assetco.global.attribute", "a.assetco.global.class",
                "a.assetco.global.value",
                # Key assumption ranges (hospitality namespace)
                "a.hospitality.global.class",
                "a.hospitality.global.values",
            ]
            # Also print all a.hospitality.global.* ranges to diagnose naming
            _a_hosp_global = sorted([n for n, _ in named_values if str(n).startswith("a.hospitality.global")])
            print(f"  a.hospitality.global.* : {_a_hosp_global}")
            _loaded_names = {n for n, _ in named_values}
            _found = [r for r in _EXPECTED_RANGES if r in _loaded_names]
            _missing = [r for r in _EXPECTED_RANGES if r not in _loaded_names]
            print(f"  Expected ranges found:   {len(_found)}/{len(_EXPECTED_RANGES)}")
            if _missing:
                print(f"  [WARN]  MISSING expected ranges: {_missing}")
            else:
                print(f"  [OK] All expected ranges present")
            # Show ALL a.hospitality.* named ranges (to discover escalation/profile tables)
            _all_a_hosp_names = sorted(set(n for n, _ in named_values if isinstance(n, str) and n.startswith("a.hospitality.")))
            print(f"  ALL a.hospitality.* named ranges ({len(_all_a_hosp_names)}): {_all_a_hosp_names}")
            print("=" * 80 + "\n")
            # -- END DEBUG LOGGING --------------------------------------------

            return pd.DataFrame(named_values, columns=["name", "value"])

        assumptions = fn_read_all_named_ranges_json(payload)

        # Diagnostic: dump all assumption names containing "interest" or "rate"
        _all_assumption_names = sorted(assumptions["name"].unique().tolist()) if not assumptions.empty else []
        _interest_rate_names = [n for n in _all_assumption_names if "interest" in str(n).lower() or ("rate" in str(n).lower() and "hospitality" in str(n).lower())]
        if _interest_rate_names:
            print(f"\n--- Assumptions containing 'interest' or 'rate': {_interest_rate_names} ---")
        else:
            print(f"\n--- No assumptions found containing 'interest' or 'rate'. Total named ranges: {len(_all_assumption_names)} ---")
            # Print ALL hospitality named ranges to help debug
            _hospitality_names = [n for n in _all_assumption_names if "hospitality" in str(n).lower()]
            print(f"    All hospitality named ranges ({len(_hospitality_names)}): {_hospitality_names}")

        def fn_assign_global_class_attributes(cls, assumptions):
            try:
                # -- Namespace-coherent lookup ------------------------------
                # All three arrays (class, attribute, value) MUST come from
                # the SAME namespace to stay aligned.  We try each coherent
                # triple in priority order.
                _NAMESPACE_SETS = [
                    # Hospitality â€” plural "attributes" / "values"
                    ("a.hospitality.global.class", "a.hospitality.global.attributes", "a.hospitality.global.values"),
                    # Hospitality â€” singular "attribute" / "values" (common variant)
                    ("a.hospitality.global.class", "a.hospitality.global.attribute",  "a.hospitality.global.values"),
                    # Hospitality â€” singular "attribute" / singular "value"
                    ("a.hospitality.global.class", "a.hospitality.global.attribute",  "a.hospitality.global.value"),
                    # AssetCo fallback
                    ("a.assetco.global.class",     "a.assetco.global.attribute",      "a.assetco.global.value"),
                    ("a.assetco.global.class",     "a.assetco.attributes.row",        "a.assetco.global.value"),
                ]

                def _lookup(range_name):
                    result = assumptions.loc[assumptions["name"] == range_name, "value"]
                    if not result.empty:
                        return result.iloc[0]
                    return None

                class_names = attr_names = attr_values = None
                _used_ns = None
                for cls_rn, attr_rn, val_rn in _NAMESPACE_SETS:
                    c = _lookup(cls_rn)
                    a = _lookup(attr_rn)
                    v = _lookup(val_rn)
                    if c is not None and a is not None and v is not None:
                        class_names, attr_names, attr_values = c, a, v
                        _used_ns = (cls_rn, attr_rn, val_rn)
                        break

                if class_names is None or attr_names is None or attr_values is None:
                    # Print diagnostic once (for first class only)
                    if cls.__name__ == "ModelInputs":
                        print(f"   [ERR] Could not find any coherent (class, attribute, value) namespace triple!")
                        for cls_rn, attr_rn, val_rn in _NAMESPACE_SETS:
                            c_ok = _lookup(cls_rn) is not None
                            a_ok = _lookup(attr_rn) is not None
                            v_ok = _lookup(val_rn) is not None
                            print(f"      {cls_rn}: {'?' if c_ok else '?'}  {attr_rn}: {'?' if a_ok else '?'}  {val_rn}: {'?' if v_ok else '?'}")
                        # Also dump all a.hospitality.global.* names
                        _all_a_names = sorted([n for n in assumptions["name"].tolist() if isinstance(n, str) and n.startswith("a.hospitality.global")])
                        print(f"      All a.hospitality.global.* ranges: {_all_a_names}")
                    return

                if cls.__name__ == "ModelInputs":
                    print(f"   [OK] Namespace selected: {_used_ns}")
            except Exception as exc:
                print(f"   [ERR] fn_assign_global_class_attributes init error: {exc}")
                return
            
            class_name = cls.__name__
            
            # Map Python class names to Excel class names (Global classes)
            # Excel may use special chars (& etc.) that Python identifiers cannot
            # Values can be a single string or a list of strings (for classes
            # that aggregate data from multiple Excel classes, e.g. FinancingModule).
            global_class_name_map = {
                "FBRevenueAssumptions": "F&BRevenueAssumptions",
                "FinancingModule": ["CapitalStructure", "FinancingAssumptions-Loan1", "RefinancingAssumptions"],
            }
            
            # Explicit attribute alias map: Python attr name ? set of Excel aliases
            # Used when the Python class renamed an attribute relative to the Excel source.
            _attr_alias_map = {
                # ValuationParameters
                "discount_rate_assumption": {"discount_rate"},
                "exit_yield_assumption": {"exit_yield"},
                "disposal_cost_assumption": {"disposal_cost"},
                "ebidta_less_reserve_escalation_assumption": {"noi_escalation", "ebidta_less_reserve_escalation"},
                "ebidta_less_reserve_top_up_assumption": {"noi_top_up", "ebidta_less_reserve_top_up"},
                "ebidta_less_reserve_top_up_value_assumption": {"noi_top_up_value", "ebidta_less_reserve_top_up_value"},
                "valuation_date_assumption": {"valuation_date"},
                # ModelInputs â€” Excel may send standard AssetCo names
                "model_start_period": {"model_start_date", "model_start_period", "model_start"},
                "model_period": {"model_duration", "model_period"},
                "model_end_period": {"model_end", "model_end_period", "model_end_date"},
                "no_of_months_in_a_year": {"no_of_months_in_a_year", "months_in_year"},
                "asset_acquisition_dateanalysis_date": {"acquisition_date", "analysis_date", "asset_acquisition_dateanalysis_date", "acquisition_dateanalysis_date"},
                "asset_holding_period": {"holding_period", "asset_holding_period"},
                "operation_start": {"operations_start", "operation_start"},
                "override_option": {"override_option"},
                # AcquisitionModule
                "acquisition_price_assumption": {"acquisition_price"},
                "transfers_tax__stamp_duty_assumption": {"transfer_tax__stamp_duty", "transfers_tax__stamp_duty"},
                "legal_fees_assumption": {"legal_fees"},
                "brokerage_assumption": {"brokerage"},
                "due_diligence_costs_assumption": {"due_diligence_costs"},
                # FinancingModule â€” Excel sends short names under CapitalStructure / Loan1 / Refinancing
                "capital_structure_total_debt_ltv": {"total_debt_ltv"},
                "capital_structure_total_equity": {"total_equity"},
                "financing_assumptions_loan_1_loan_raise_date": {"loan_raise_date"},
                "financing_assumptions_loan_1_loan_term": {"loan_term"},
                "financing_assumptions_loan_1_loan_end": {"loan_end"},
                "financing_assumptions_loan_1_amortization_duration": {"amortization_duration"},
                "financing_assumptions_loan_1_annual_amortization": {"annual_amortization"},
                "financing_assumptions_loan_1_balloon_payment": {"balloon_payment"},
                "financing_assumptions_loan_1_dscr": {"dscr"},
                "financing_assumptions_loan_1_base_interest_rate": {"base_interest_rate"},
                "financing_assumptions_loan_1_arrangement_fees": {"arrangement_fees"},
                "financing_assumptions_loan_1_loan_refinancing_": {"loan_refinancing_", "loan_refinancing"},
                "financing_assumptions_loan_1_loan_refinancing_date": {"loan_refinancing_date"},
                "refinancing_assumptions_ebitda_less_reserves_at_refinanced_date": {"ebitda_less_reserves_at_refinanced_date", "noi_at_refinance"},
                "refinancing_assumptions_cap_rate_at_refinanced": {"cap_rate_at_refinanced", "cap_rate_at_refinance"},
                "refinancing_assumptions_valuation_at_refinanced": {"valuation_at_refinanced", "valuation_at_refinance"},
                "refinancing_assumptions_ltv": {"ltv"},
                "refinancing_assumptions_ltv_max_loan": {"ltv_max_loan"},
                "refinancing_assumptions_min_dscr": {"min_dscr"},
                "refinancing_assumptions_dscr_computed": {"dscr_computed"},
                "refinancing_assumptions_repayment_type": {"repayment_type"},
                "refinancing_assumptions_loan_start": {"loan_start"},
                "refinancing_assumptions_loan_term": {"refinancing_loan_term"},
                "refinancing_assumptions_loan_end": {"refinancing_loan_end"},
                "refinancing_assumptions_amortization_duration": {"refinancing_amortization_duration"},
                "refinancing_assumptions_amortization_percentage": {"amortization_percentage", "annual_amortization_refi"},
                "refinancing_assumptions_balloon_payment": {"refinancing_balloon_payment"},
                "refinancing_assumptions_refinanced_interest_rate": {"refinanced_interest_rate", "refinance_interest_rate"},
                "refinancing_assumptions_arrangement_fees": {"refinancing_arrangement_fees"},
                # HospitalityOtherAssumptions â€” Python names have redundant class prefix;
                # Excel sends short names like "Depreciation & Amortization".
                "hospitality_other_assumptions_depreciation__amortization": {
                    "depreciation__amortization", "depreciation_amortization",
                    "depreciation_&_amortization", "d&a", "depreciation_and_amortization",
                    "depreciation & amortization",
                },
                "hospitality_other_assumptions_income_tax": {
                    "income_tax", "tax", "income tax",
                },
                "hospitality_other_assumptions_changes_in_working_capital": {
                    "changes_in_working_capital", "working_capital",
                    "changes in working capital",
                },
                # OtherOperatingDepartmentExpenseAssumptions â€” doubled name pattern
                "banquet__conference__expense_banquet__conference__expense": {
                    "banquet__conference__expense", "banquet_conference_expense",
                    "banquet_&_conference_expense", "banquet & conference expense",
                },
            }
            
            # Build a reverse lookup: normalised Excel alias ? Python attr name
            _alias_reverse = {}  # norm(excel_alias) ? python_attr
            for py_attr, aliases in _attr_alias_map.items():
                for alias in aliases:
                    _alias_reverse[alias.lower().replace(" ", "").replace("-", "").replace("_", "")] = py_attr
            
            raw_mapped = global_class_name_map.get(class_name, class_name)
            mapped_names = raw_mapped if isinstance(raw_mapped, list) else [raw_mapped]
            attrs_populated = 0
            
            # Collect unique class names from Excel data for diagnostics
            unique_excel_classes = set(class_names) if isinstance(class_names, list) else set()
            
            # Get min length to avoid index errors
            min_len = min(len(attr_names), len(class_names), len(attr_values))
            
            # Build the set of effective Excel class names this Python class should match.
            # Start with the mapped names (may be a list for multi-source classes like FinancingModule).
            effective_names = set(mapped_names)
            
            # Also try fuzzy matching for each mapped name
            for mn in list(mapped_names):
                mn_lower = mn.lower().replace(" ", "").replace("-", "").replace("_", "").replace("&", "")
                for cn in unique_excel_classes:
                    if isinstance(cn, str):
                        cn_lower = cn.strip().lower().replace(" ", "").replace("-", "").replace("_", "").replace("&", "")
                        if cn_lower == mn_lower and cn not in effective_names:
                            effective_names.add(cn)
                            print(f"   [WARN] Global.{class_name}: fuzzy matched Excel class '{cn}' (mapped from '{mn}')")
            
            # Also try the raw Python class name if it's different from the mapped names
            if class_name not in effective_names and class_name not in mapped_names:
                class_lower = class_name.lower().replace(" ", "").replace("-", "").replace("_", "").replace("&", "")
                for cn in unique_excel_classes:
                    if isinstance(cn, str):
                        cn_lower = cn.strip().lower().replace(" ", "").replace("-", "").replace("_", "").replace("&", "")
                        if cn_lower == class_lower and cn not in effective_names:
                            effective_names.add(cn)
                            print(f"   [WARN] Global.{class_name}: fuzzy matched Excel class '{cn}' (from Python name)")

            # Build a fuzzy lookup: normalised Python attr name ? actual attr name
            _cls_attrs = [a for a in dir(cls) if not a.startswith('_') and not callable(getattr(cls, a, None))]
            _attr_norm_map = {}  # norm_key ? python_attr_name
            for _a in _cls_attrs:
                _norm = _a.lower().replace(" ", "").replace("-", "").replace("_", "")
                _attr_norm_map[_norm] = _a

            # -- Diagnostic: dump ALL Excel rows for this class --
            if class_name in ("FBRevenueAssumptions", "OODRevenueAssumptions", "ParkingRevenue", "ModelInputs",
                              "HospitalityOtherAssumptions", "IncentiveFeesAssumptions", "OtherIncome",
                              "OtherOperatingDepartmentExpenseAssumptions", "DepartmentalExpenseAssumptions"):
                _class_rows = [(attr_names[i], attr_values[i], type(attr_values[i]).__name__)
                               for i in range(min_len) if class_names[i] in effective_names]
                print(f"   [DIAG] Excel rows for {class_name} ({len(_class_rows)} rows):")
                for _cr_name, _cr_val, _cr_type in _class_rows:
                    print(f"      attr={_cr_name!r}, val={str(_cr_val)[:80]!r}, type={_cr_type}")
                print(f"   [DIAG] Python attrs for {class_name}: {_cls_attrs}")
                print(f"   [DIAG] Norm map keys: {list(_attr_norm_map.keys())}")
                print(f"   [DIAG] Effective names for {class_name}: {effective_names}")
                # Also dump ALL excel rows where attr or class contains banquet/spa/conference
                if class_name == "OODRevenueAssumptions":
                    _banq_rows = [(i, class_names[i], attr_names[i], str(attr_values[i])[:80])
                                  for i in range(min_len)
                                  if isinstance(attr_names[i], str)
                                  and any(kw in (attr_names[i].lower() + " " + str(class_names[i]).lower())
                                          for kw in ("banquet", "conference", "charge", "booking", "event"))]
                    print(f"   [DIAG-BANQ] ALL Excel rows matching banquet/conference/charge/booking/event ({len(_banq_rows)}):")
                    for _bi, _bc, _ba, _bv in _banq_rows:
                        print(f"      [{_bi}] class={_bc!r}, attr={_ba!r}, val={_bv!r}")
                    # Save OOD diagnostics to file for debugging
                    import os as _os_diag
                    _ood_diag_path = _os_diag.path.join(_os_diag.path.dirname(__file__), "ood_diag.log")
                    with open(_ood_diag_path, "w", encoding="utf-8") as _odf:
                        _odf.write(f"effective_names: {effective_names}\n")
                        _odf.write(f"unique_excel_classes: {unique_excel_classes}\n")
                        _odf.write(f"class_rows ({len(_class_rows)}):\n")
                        for _cr_name, _cr_val, _cr_type in _class_rows:
                            _odf.write(f"  attr={_cr_name!r}, val={str(_cr_val)[:120]!r}, type={_cr_type}\n")
                        _odf.write(f"\nALL banquet-related rows ({len(_banq_rows)}):\n")
                        for _bi, _bc, _ba, _bv in _banq_rows:
                            _odf.write(f"  [{_bi}] class={_bc!r}, attr={_ba!r}, val={_bv!r}\n")
                        _odf.write(f"\nPython attrs: {_cls_attrs}\n")
                        _odf.write(f"Norm map: {_attr_norm_map}\n")
                    print(f"   [DIAG] OOD diagnostics saved to {_ood_diag_path}")

            for i, attr in enumerate(attr_names):
                # Bounds check
                if i >= min_len:
                    break
                    
                # Error control: check if class name matches for this attribute
                if class_names[i] not in effective_names:
                    continue

                # Resolve attribute name: try exact first, then fuzzy, then alias
                resolved_attr = None
                if hasattr(cls, attr):
                    resolved_attr = attr
                else:
                    if isinstance(attr, str):
                        # Fuzzy match: normalise Excel attr and look up
                        attr_norm = attr.lower().replace(" ", "").replace("-", "").replace("_", "")
                        if attr_norm in _attr_norm_map:
                            resolved_attr = _attr_norm_map[attr_norm]
                        # Alias reverse lookup
                        elif attr_norm in _alias_reverse:
                            candidate = _alias_reverse[attr_norm]
                            if hasattr(cls, candidate):
                                resolved_attr = candidate
                        # Prefix match: Excel attr is a prefix of a Python attr
                        if resolved_attr is None and attr_norm:
                            for norm_key, py_attr in _attr_norm_map.items():
                                if norm_key.startswith(attr_norm) and len(attr_norm) >= 4:
                                    resolved_attr = py_attr
                                    break
                        # Suffix match: Python attr ENDS WITH Excel attr (handles
                        # class-prefixed Python names vs short Excel attr names).
                        # Require at least 8 normalised chars to avoid false positives.
                        if resolved_attr is None and attr_norm and len(attr_norm) >= 8:
                            for norm_key, py_attr in _attr_norm_map.items():
                                if norm_key != attr_norm and norm_key.endswith(attr_norm):
                                    resolved_attr = py_attr
                                    break

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

                # Unwrap list-wrapped values for date detection
                _raw_val = attr_values[i]
                _scalar_val = _raw_val
                if isinstance(_raw_val, (list, np.ndarray)) and len(_raw_val) > 0:
                    _scalar_val = _raw_val[0]

                # Detect Excel serial: int/float/numeric-string in 25000-100000
                is_excel_serial = False
                try:
                    _num = float(_scalar_val) if not isinstance(_scalar_val, (pd.Timestamp, datetime)) else None
                    if _num is not None and 25000 < _num < 100000:
                        is_excel_serial = True
                except (ValueError, TypeError):
                    pass

                if is_date_attr and is_excel_serial and resolved_attr not in date_exceptions:
                    convertedval = datetime.fromtimestamp(
                        (float(_scalar_val) - 25569) * 86400.0
                    ).strftime("%Y-%m-%d")
                    _final_val = pd.to_datetime(convertedval)
                    setattr(cls, resolved_attr, _final_val)
                    print(f"      [DATE] {class_name}.{resolved_attr} = {_final_val} (from serial {_scalar_val})")
                elif is_date_attr:
                    # Date attribute but NOT Excel serial â€” try pd.to_datetime directly
                    try:
                        _final_val = pd.to_datetime(_scalar_val)
                        if pd.isna(_final_val):
                            _final_val = None
                    except Exception:
                        _final_val = None
                    if _final_val is not None:
                        setattr(cls, resolved_attr, _final_val)
                        print(f"      [DATE] {class_name}.{resolved_attr} = {_final_val} (from parse of {_raw_val!r})")
                    else:
                        setattr(cls, resolved_attr, _raw_val)
                        print(f"      [WARN] {class_name}.{resolved_attr} = {_raw_val!r} (date parse failed, stored raw)")
                else:
                    # Set attribute value directly
                    setattr(cls, resolved_attr, _raw_val)
                attrs_populated += 1
            
            if attrs_populated > 0:
                print(f"   [OK] Global.{class_name}: loaded {attrs_populated} attributes (matched via {sorted(effective_names)})")
            else:
                # Extra diagnostics: show what Excel has for this class
                _matching_rows = [(i, attr_names[i], attr_values[i]) for i in range(min_len) if class_names[i] in effective_names]
                print(f"   [ERR] Global.{class_name}: 0 attributes loaded! Effective names={sorted(effective_names)}. Matching rows={len(_matching_rows)}")
                if _matching_rows:
                    print(f"      First 5 unmatched attrs: {[r[1] for r in _matching_rows[:5]]}")
                print(f"      Available classes: {sorted(unique_excel_classes)}")
                


        def fn_initialize_global_class(assumptions):
            # Dynamically retrieve all subclasses of the Global class
            for subclass_name in dir(Global):
                if subclass_name.startswith('_'):
                    continue  # Skip dunder/private attributes (e.g. __class__ ? type)
                subclass = getattr(Global, subclass_name)
                # Check if the attribute is a class (subclass of Global)
                if isinstance(subclass, type):
                    fn_assign_global_class_attributes(subclass, assumptions)

        # NOTE: fn_assign_asset_class_attributes and fn_initialize_asset_class
        # removed for hospitality model (no Unit/tenant class structure).


        def fn_print_all_inputs():
            """Print all Global class inputs for debugging."""
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
            
            # NOTE: Unit class print section removed (no Unit class in hospitality model)
            
            print("\n" + "=" * 80)

        fn_initialize_global_class(assumptions)
        # fn_initialize_asset_class removed (no Unit class in hospitality model)

        # Print financing-related Global attributes for debugging
        print("\n" + "=" * 80)
        print("DEBUG: FINANCING GLOBAL INPUTS AFTER INITIALIZATION")
        print("=" * 80)
        print(f"  FinancingModule attributes:")
        for attr in dir(Global.FinancingModule):
            if not attr.startswith('_'):
                val = getattr(Global.FinancingModule, attr)
                if not callable(val):
                    print(f"    {attr}: {val}")
        print("=" * 80)

        # NOTE: Unit.UnitInputs.sno safety check removed (no Unit class in hospitality model)

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

        # Ensure model_start_period is the first day of the month
        Global.ModelInputs.model_start_period = _excel_serial_to_datetime(
            Global.ModelInputs.model_start_period
        )
        if Global.ModelInputs.model_start_period:
            Global.ModelInputs.model_start_period = Global.ModelInputs.model_start_period.replace(day=1)

        # Ensure model_end_period is the last day of the month
        Global.ModelInputs.model_end_period = _excel_serial_to_datetime(
            Global.ModelInputs.model_end_period
        )
        if Global.ModelInputs.model_end_period:
            Global.ModelInputs.model_end_period = Global.ModelInputs.model_end_period + pd.offsets.MonthEnd(0)
        
        # Ensure acquisition date and asset_sale_date are properly formatted if they exist
        if Global.ModelInputs.asset_acquisition_dateanalysis_date:
            Global.ModelInputs.asset_acquisition_dateanalysis_date = _excel_serial_to_datetime(Global.ModelInputs.asset_acquisition_dateanalysis_date)
        if Global.ModelInputs.asset_sale_date:
            Global.ModelInputs.asset_sale_date = _excel_serial_to_datetime(Global.ModelInputs.asset_sale_date)
            if Global.ModelInputs.asset_sale_date:
                Global.ModelInputs.asset_sale_date = Global.ModelInputs.asset_sale_date + pd.offsets.MonthEnd(0)
        
        # Convert operation_start if it's an Excel serial
        if Global.ModelInputs.operation_start:
            Global.ModelInputs.operation_start = _excel_serial_to_datetime(Global.ModelInputs.operation_start)
        
        # -- Safety guard: model_start_period / model_end_period must be set --
        if Global.ModelInputs.model_start_period is None or Global.ModelInputs.model_end_period is None:
            print("\n" + "!" * 80)
            print("FATAL: model_start_period or model_end_period is None â€” cannot build timeline.")
            print(f"   model_start_period = {Global.ModelInputs.model_start_period!r}")
            print(f"   model_end_period   = {Global.ModelInputs.model_end_period!r}")
            print("   This usually means the Global.ModelInputs class attributes were not")
            print("   populated from the Excel named ranges.  Check that the assumption")
            print("   arrays (class / attribute / value) load from the SAME namespace.")
            # Dump ALL ModelInputs attrs so we can see what DID load
            print("   Current ModelInputs attrs:")
            for _a in dir(Global.ModelInputs):
                if not _a.startswith('_'):
                    _v = getattr(Global.ModelInputs, _a, None)
                    if not callable(_v):
                        print(f"      {_a} = {_v!r}")
            print("!" * 80 + "\n")
            raise ValueError(
                "model_start_period and model_end_period are required but were not loaded "
                "from Excel inputs. Ensure the workbook contains valid ModelInputs data."
            )

        model_timeline_me = fn_create_model_timeline(
            Global.ModelInputs.model_start_period,
            Global.ModelInputs.model_end_period,
            "ME",
        )
        model_timeline_ye = fn_create_model_timeline(
            Global.ModelInputs.model_start_period,
            Global.ModelInputs.model_end_period,
            "YE",
        )
        model_timeline_qe = fn_create_model_timeline(
            Global.ModelInputs.model_start_period,
            Global.ModelInputs.model_end_period,
            "QE",
        )

        # Hospitality model: number_of_assets = 1 (single hotel asset)
        number_of_assets = 1

        # Create empty DataFrame with single asset row and timeline periods as columns
        timeline_periods = model_timeline_me["# of Period"]
        template_asset_timeline = pd.DataFrame(
            0.0,
            index=range(0, number_of_assets, 1),
            columns=model_timeline_me.index,
        )

        # Step 2: Initialize module variables
        _period_starts = model_timeline_me["Period Start"].values
        _period_ends = model_timeline_me["Period End"].values
        _num_periods = len(model_timeline_me)
        _num_assets = number_of_assets
        _period_starts_ts = [pd.Timestamp(x) for x in _period_starts]
        _period_ends_ts = [pd.Timestamp(x) for x in _period_ends]

        # ---- KEY INPUT DIAGNOSTICS ----
        print(f"\n   [INPUT CHECK] Key model inputs:")
        print(f"      model_start_period: {Global.ModelInputs.model_start_period}")
        print(f"      model_end_period:   {Global.ModelInputs.model_end_period}")
        print(f"      acquisition_date:   {Global.ModelInputs.asset_acquisition_dateanalysis_date}")
        print(f"      asset_sale_date:    {Global.ModelInputs.asset_sale_date}")
        print(f"      operation_start:    {Global.ModelInputs.operation_start}")
        print(f"      analysis_type:      {Global.ModelInputs.analysis_type}")
        print(f"      holding_period:     {Global.ModelInputs.asset_holding_period}")
        print(f"      num_periods (ME):   {_num_periods}")
        print(f"      num_assets:         {_num_assets}")
        print(f"      total_debt_ltv:     {Global.FinancingModule.capital_structure_total_debt_ltv}")
        print(f"      acq_price input:    {Global.AcquisitionModule.acquisition_price_assumption}")


        # =============================================================================
        # VALID PERIOD FLAG - Ensures no cashflows before acquisition or after sale
        # =============================================================================
        # This flag is 1 for periods where cashflows are valid, 0 otherwise
        # All cashflow outputs should be multiplied by this flag
        
        _acquisition_date = Global.ModelInputs.asset_acquisition_dateanalysis_date
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

        _operations_start = Global.ModelInputs.operation_start
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



        # =============================================================================
        # DATE UTILITY FUNCTIONS (extracted from former Module 06)
        # =============================================================================

        def fn_get_asset_sale_date():
            """Get asset sale date from global inputs."""
            try:
                sale_date = Global.ModelInputs.asset_sale_date
                if sale_date is None:
                    return None
                if isinstance(sale_date, (list, np.ndarray)):
                    sale_date = sale_date[0] if len(sale_date) > 0 else None
                if sale_date is None:
                    return None
                try:
                    if isinstance(sale_date, (float, np.floating)) and pd.isna(sale_date):
                        return None
                except (ValueError, TypeError):
                    pass
                return pd.to_datetime(sale_date)
            except:
                return None


        def fn_get_acquisition_date():
            """Get analysis date from global inputs."""
            try:
                acquisition_date = Global.ModelInputs.asset_acquisition_dateanalysis_date
                if acquisition_date is None:
                    return None
                if isinstance(acquisition_date, (list, np.ndarray)):
                    acquisition_date = acquisition_date[0] if len(acquisition_date) > 0 else None
                if acquisition_date is None:
                    return None
                try:
                    if isinstance(acquisition_date, (float, np.floating)) and pd.isna(acquisition_date):
                        return None
                except (ValueError, TypeError):
                    pass
                return pd.to_datetime(acquisition_date)
            except Exception as e:
                print(f"   [WARN] fn_get_acquisition_date: exception {e}")
                return None


        def fn_get_operations_start():
            """Get operations start date from global inputs."""
            try:
                ops_start = Global.ModelInputs.operation_start
                if ops_start is None:
                    return None
                if isinstance(ops_start, (list, np.ndarray)):
                    ops_start = ops_start[0] if len(ops_start) > 0 else None
                if ops_start is None:
                    return None
                try:
                    if isinstance(ops_start, (float, np.floating)) and pd.isna(ops_start):
                        return None
                except (ValueError, TypeError):
                    pass
                return pd.to_datetime(ops_start)
            except:
                return None



        # =============================================================================
        # INTEREST RATE PROFILES (CFF)
        # =============================================================================

        def fn_get_interest_rate_profiles():
            """
            Load interest rate profiles from assumptions.
            Tries multiple naming patterns (dd.assetco.*, a.assetco.*) and
            falls back to fuzzy name search if exact match fails.
            
            Returns: dict mapping profile_name -> {year: annual_rate}
            """
            profiles = {}

            # Candidate naming patterns: (profiles_name, values_name)
            _candidates = [
                ("a.hospitality.interest.rate.profiles",  "a.hospitality.interest.rate.values"),
                ("dd.hospitality.interest.rate.profiles", "dd.hospitality.interest.rate.values"),
                ("a.hospitality.interest.rate.profiles",  "a.hospitality.interest.rates"),
                ("dd.hospitality.interest.rate.profiles", "dd.hospitality.interest.rates"),
                # Legacy assetco fallbacks (shared workbooks)
                ("dd.assetco.interest.rate.profiles", "dd.assetco.interest.rate.values"),
                ("a.assetco.interest.rate.profiles",  "a.assetco.interest.rate.values"),
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
                        print(f"   [OK] Interest rate profiles found via: {pn_name} + {rv_name}")
                        break

                # If exact match failed, try fuzzy search across all assumption names
                if profile_names is None:
                    all_names = assumptions["name"].tolist()
                    fuzzy_pn = None
                    fuzzy_rv = None
                    for n in all_names:
                        nl = str(n).lower()
                        if "interest" in nl and "profile" in nl:
                            fuzzy_pn = n
                        elif "interest" in nl and ("value" in nl or "rate" in nl) and "profile" not in nl:
                            fuzzy_rv = n
                    if fuzzy_pn and fuzzy_rv:
                        profile_names = assumptions.loc[assumptions["name"] == fuzzy_pn, "value"].iloc[0]
                        rate_values = assumptions.loc[assumptions["name"] == fuzzy_rv, "value"].iloc[0]
                        print(f"   [OK] Interest rate profiles found via fuzzy: {fuzzy_pn} + {fuzzy_rv}")

                if profile_names is None or rate_values is None:
                    print(f"   [ERR] Interest rate profiles NOT FOUND in assumptions.")
                    print(f"      Expected named ranges: dd.assetco.interest.rate.profiles + dd.assetco.interest.rate.values")
                    print(f"      Please create these named ranges in the Excel workbook pointing to the interest rate curve table.")
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
                print(f"[WARN] Error loading interest rate profiles: {e}")
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
            
            # It's a profile name string â€” look up year-based rate
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
                        print(f"   [WARN] Interest rate profile: fuzzy matched '{pname}' ? '{matched_key}'")
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


        # =============================================================================
        # MODULE 08 â€“ MAINTENANCE CAPEX & SINKING FUND
        # =============================================================================

        def fn_parse_date(date_val):
            """Parse date value to pandas Timestamp.
            Handles: None, NaN, 0, empty string, Excel serial numbers,
            list-wrapped values, string dates, and existing Timestamps.
            """
            if date_val is None:
                return None
            # Unwrap list / ndarray
            if isinstance(date_val, (list, np.ndarray)):
                if len(date_val) == 0:
                    return None
                date_val = date_val[0]
                if date_val is None:
                    return None
            # NaN check
            try:
                if isinstance(date_val, (float, int, np.floating, np.integer)) and pd.isna(date_val):
                    return None
            except (ValueError, TypeError):
                pass
            # Empty / whitespace string
            if isinstance(date_val, str) and date_val.strip() == "":
                return None
            # Zero means "not set"
            if isinstance(date_val, (int, float, np.floating, np.integer)):
                try:
                    if float(date_val) == 0:
                        return None
                except (ValueError, TypeError):
                    pass
            # Excel serial number (int / float / numeric string in 25000-100000)
            try:
                num = float(date_val) if not isinstance(date_val, (pd.Timestamp, datetime)) else None
                if num is not None and 25000 < num < 100000:
                    converted = datetime.fromtimestamp(
                        (num - 25569) * 86400.0
                    ).strftime("%Y-%m-%d")
                    return pd.to_datetime(converted)
            except (ValueError, TypeError, OverflowError):
                pass
            # General pd.to_datetime
            try:
                result = pd.to_datetime(date_val)
                if pd.isna(result):
                    return None
                return result
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
                print(f"[WARN] Error getting named range '{name}': {e}")
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
            named_range = f"s.hospitality.maintenance.capex.{item_num}"
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

        def fn_compute_sinking_fund():
            """
            Sinking fund â€” returns zeros for hospitality model.
            
            Hospitality does not use the lease-based sinking fund computation.
            FF&E Reserve and Capital Reserve are handled in the Hospitality P&L instead.
            """
            return pd.Series(np.zeros(_num_periods), index=range(_num_periods))


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
            
            # print("[OK] Maintenance CapEx and Sinking Fund computation complete.")
            
            return _cache_set(cache_key, results)


        # =============================================================================
        # CREATE OUTPUT DATAFRAMES
        # =============================================================================


        # =============================================================================
        # VALUATION PARAMETERS
        # =============================================================================

        def fn_get_analysis_type():
            """Get analysis type (Investment or Valuation)."""
            # Try Global.ModelInputs first
            try:
                val = Global.ModelInputs.analysis_type
                if isinstance(val, (list, np.ndarray)):
                    val = val[0] if len(val) > 0 else None
                if val is not None and str(val).strip().lower() not in ("none", "", "nan"):
                    return str(val).strip()
            except Exception:
                pass
            
            # Try reading from assumptions DataFrame with various named ranges
            named_range_options = [
                "a.hospitality.analysis.type",
                "s.hospitality.analysis.type",
                "dd.hospitality.analysis.type",
                "s.assetco.analysis.type",
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
                val = Global.ValuationParameters.discount_rate_assumption
                return _safe_float(val, 0)
            except:
                return 0

        def fn_get_exit_yield():
            """Get exit yield from valuation parameters."""
            try:
                val = Global.ValuationParameters.exit_yield_assumption
                return _safe_float(val, 0)
            except:
                return 0

        def fn_get_noi_escalation():
            """Get NOI/EBITDA escalation rate from valuation parameters."""
            try:
                val = Global.ValuationParameters.ebidta_less_reserve_escalation_assumption
                return _safe_float(val, 0)
            except:
                return 0


        # =============================================================================
        # CASHFLOW COLLECTORS
        # =============================================================================

        def fn_get_tenant_fitout():
            """Get tenant fit out charges â€” returns zeros for hospitality (no tenants)."""
            cache_key = "output:tenant_fitout"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
            return _cache_set(cache_key, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))

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
                print(f"[WARN] Error calculating maintenance capex: {e}")
            
            return _cache_set(cache_key, results)


        # =============================================================================
        # ACQUISITION COSTS & ASSET SALE VALUE
        # =============================================================================

        def fn_get_acquisition_costs():
            """
            Get acquisition price and transaction costs.
            
            For VALUATION mode: Acquisition price = PV of net operating cashflows
            For INVESTMENT mode: Acquisition price = input value from Global.AcquisitionModule
            
            Transaction costs are percentages Ã— acquisition price:
            - Transfer Tax: transfer_tax__stamp_duty (%) Ã— acquisition_price
            - Legal Fees: legal_fees (%) Ã— acquisition_price
            - Brokerage: brokerage (%) Ã— acquisition_price
            - Due Diligence: due_diligence_costs (%) Ã— acquisition_price
            """
            # print("\n? fn_get_acquisition_costs: STARTED")
            
            # Debug: Show all AcquisitionModule attributes
            acq = Global.AcquisitionModule
            # print(f"\n   ? DEBUG: Global.AcquisitionModule values:")
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
            
            acquisition_date = Global.ModelInputs.asset_acquisition_dateanalysis_date
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
                # VALUATION (Hospitality): PV of EBITDA Less Reserves - CapEx + Asset Sale
                
                # Get discount rate
                discount_rate = fn_get_discount_rate()
                
                try:
                    # ---------- EBITDA Less Reserves from Hospitality P&L ----------
                    pl_results = fn_compute_hospitality_pl()
                    ebitda_lr = pl_results.get("EBITDA Less Reserve", np.zeros(_num_periods))
                    ebitda_lr_series = pd.Series(ebitda_lr, index=range(_num_periods))
                    
                    # Asset Sale Value (uses EBITDA Less Reserves via fn_get_asset_sale_value)
                    asset_sale_series = fn_get_asset_sale_value()
                    asset_sale_value = float(asset_sale_series.sum())
                    
                    # Get asset sale date for separate discounting
                    asset_sale_date = fn_get_asset_sale_date()
                    
                    # Maintenance CapEx
                    mcapex_dict = fn_get_maintenance_capex()
                    mcapex_total = pd.Series(np.zeros(_num_periods), index=range(_num_periods))
                    for i in range(1, 5):
                        key = f"maintenance_capex_{i}"
                        mcapex_total += mcapex_dict.get(key, pd.Series(np.zeros(_num_periods), index=range(_num_periods)))
                    
                    # Monthly operating CFs = EBITDA Less Reserves - CapEx
                    monthly_cf_series = ebitda_lr_series - mcapex_total
                    
                    # Discount monthly operating CFs using 30/360 yearfrac (month-end)
                    pv_monthly = 0
                    
                    for col_idx in range(_num_periods):
                        period_end = _period_ends_ts[col_idx]
                        
                        if acquisition_date is None or _period_starts_ts[col_idx] <= acquisition_date:
                            df_val = 1.0
                        else:
                            year_fraction = yearfrac_30_360(acquisition_date, period_end)
                            df_val = 1 / ((1 + discount_rate) ** year_fraction)
                        
                        pv_monthly += monthly_cf_series.iloc[col_idx] * df_val
                    
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
                    
                    print(f"\n   [HOSPITALITY VALUATION] PV Monthly CFs: {pv_monthly:,.2f}, "
                          f"PV Asset Sale: {pv_asset_sale:,.2f}, "
                          f"Total PV (Acquisition Price): {acquisition_price:,.2f}")
                    
                except Exception as e:
                    import traceback
                    print(f"   [WARN] Valuation failed: {e}")
                    traceback.print_exc()
                    acquisition_price = 0
                    if acq.acquisition_price_assumption and not pd.isna(acq.acquisition_price_assumption):
                        acquisition_price = float(acq.acquisition_price_assumption)
            else:
                # INVESTMENT: Use input acquisition price
                # print(f"   fn_get_acquisition_costs: Using INVESTMENT mode - using input price")
                acquisition_price = 0
                if acq.acquisition_price_assumption and not pd.isna(acq.acquisition_price_assumption):
                    acquisition_price = float(acq.acquisition_price_assumption)
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
            
            transfer_tax_amt = get_percentage_amount(acq.transfers_tax__stamp_duty_assumption, acquisition_price)
            legal_fees_amt = get_percentage_amount(acq.legal_fees_assumption, acquisition_price)
            brokerage_amt = get_percentage_amount(acq.brokerage_assumption, acquisition_price)
            due_diligence_amt = get_percentage_amount(acq.due_diligence_costs_assumption, acquisition_price)
            
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
            tt_idx, tt_amt = place_amount_at_date(transfer_tax_amt, acq.transfers_tax__stamp_duty_transaction_date, acquisition_date)
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
            Get asset sale value at exit for CFS path (Hospitality mode).

            Uses EBITDA Less Reserves from the Hospitality P&L as the valuation basis.

            Steps:
              1. Take last 12 months EBITDA Less Reserves (including asset sale month)
              2. Escalate by (1 + EBITDA LR escalation %)   [direct only]
              3. Add top-up value if top-up = Yes
              4. Divide by exit yield
              5. Subtract disposal cost (% of gross sale value)

            Escalation: direct only (no indirect for hospitality).
            """
            asset_sale_cf = np.zeros(_num_periods)

            try:
                # ---- Read valuation parameters ----
                exit_yield_raw = Global.ValuationParameters.exit_yield_assumption
                noi_esc_raw = Global.ValuationParameters.ebidta_less_reserve_escalation_assumption
                topup_flag_raw = Global.ValuationParameters.ebidta_less_reserve_top_up_assumption
                topup_val_raw = Global.ValuationParameters.ebidta_less_reserve_top_up_value_assumption
                disp_raw = Global.ValuationParameters.disposal_cost_assumption

                exit_yield = float(exit_yield_raw) if exit_yield_raw and not pd.isna(exit_yield_raw) else 0
                noi_escalation_val = float(noi_esc_raw) if noi_esc_raw and not pd.isna(noi_esc_raw) else 0

                # Top-up
                is_top_up = False
                noi_top_up_value = 0.0
                try:
                    if topup_flag_raw and not pd.isna(topup_flag_raw) and str(topup_flag_raw).strip().lower() in ("yes", "true", "1"):
                        is_top_up = True
                        if topup_val_raw is not None and not pd.isna(topup_val_raw) and str(topup_val_raw).strip() != "" and float(topup_val_raw) != 0:
                            noi_top_up_value = float(topup_val_raw)
                except Exception:
                    pass

                # Disposal cost percentage
                disposal_cost_pct = 0.0
                try:
                    if disp_raw and not pd.isna(disp_raw):
                        disposal_cost_pct = float(disp_raw)
                        if disposal_cost_pct > 1:
                            disposal_cost_pct = disposal_cost_pct / 100.0
                except Exception:
                    pass

                asset_sale_date = Global.ModelInputs.asset_sale_date
                if asset_sale_date:
                    asset_sale_date = pd.to_datetime(asset_sale_date)

                # ---- Print all inputs ----
                print(f"\n   [HOSPITALITY ASSET SALE] Inputs:")
                print(f"      Asset Sale Date:           {asset_sale_date}")
                print(f"      Exit Yield:                {exit_yield:.4f}  (raw: {exit_yield_raw})")
                print(f"      EBITDA-LR Escalation:      {noi_escalation_val:.4f}  (raw: {noi_esc_raw})")
                print(f"      Top-Up Flag:               {is_top_up}  (raw: {topup_flag_raw})")
                print(f"      Top-Up Value:              {noi_top_up_value:,.2f}  (raw: {topup_val_raw})")
                print(f"      Disposal Cost %:           {disposal_cost_pct:.4f}  (raw: {disp_raw})")

                if exit_yield <= 0:
                    print(f"   [HOSPITALITY ASSET SALE] Skipped: exit_yield={exit_yield} (<=0)")
                    return pd.Series(asset_sale_cf, index=range(_num_periods))
                if not asset_sale_date:
                    print(f"   [HOSPITALITY ASSET SALE] Skipped: no asset_sale_date")
                    return pd.Series(asset_sale_cf, index=range(_num_periods))

                # ---- EBITDA Less Reserves from Hospitality P&L ----
                pl_results = fn_compute_hospitality_pl()
                ebitda_lr = pl_results.get("EBITDA Less Reserve", np.zeros(_num_periods))
                ebitda_lr_series = pd.Series(ebitda_lr, index=range(_num_periods))

                # Find last period at or before asset_sale_date (includes the sale month)
                last_idx = -1
                for col_idx in range(_num_periods - 1, -1, -1):
                    if _period_starts_ts[col_idx] <= asset_sale_date:
                        last_idx = col_idx
                        break
                if last_idx < 0:
                    print(f"   [HOSPITALITY ASSET SALE] Skipped: no period found at or before sale date")
                    return pd.Series(asset_sale_cf, index=range(_num_periods))

                start_idx = max(0, last_idx - 11)
                last_12m_ebitda_lr = float(ebitda_lr_series.iloc[start_idx:last_idx + 1].sum())

                print(f"   [HOSPITALITY ASSET SALE] Last 12m window: periods [{start_idx}] "
                      f"{_period_starts_ts[start_idx].strftime('%Y-%m')} to [{last_idx}] "
                      f"{_period_starts_ts[last_idx].strftime('%Y-%m')} "
                      f"({last_idx - start_idx + 1} months)")

                # Step 2: Direct escalation
                escalated_value = last_12m_ebitda_lr * (1 + noi_escalation_val)

                # Step 3: Global top-up (added AFTER escalation)
                value_for_valuation = escalated_value
                if is_top_up and noi_top_up_value != 0:
                    value_for_valuation = escalated_value + noi_top_up_value

                # Step 4: Capitalise by exit yield
                gross_asset_sale_value = value_for_valuation / exit_yield

                # Step 5: Deduct disposal cost
                disposal_fees = gross_asset_sale_value * disposal_cost_pct
                asset_sale_value = gross_asset_sale_value - disposal_fees

                print(f"   [HOSPITALITY ASSET SALE] Computation:")
                print(f"      Last 12m EBITDA-LR:        {last_12m_ebitda_lr:>18,.2f}")
                print(f"      x (1 + {noi_escalation_val:.4f}):           {escalated_value:>18,.2f}")
                if is_top_up and noi_top_up_value != 0:
                    print(f"      + Top-Up:                  {noi_top_up_value:>18,.2f}")
                print(f"      Value for Valuation:       {value_for_valuation:>18,.2f}")
                print(f"      / Exit Yield ({exit_yield:.4f}):     {gross_asset_sale_value:>18,.2f}")
                print(f"      - Disposal ({disposal_cost_pct:.2%}):       {disposal_fees:>18,.2f}")
                print(f"      Net Asset Sale Value:      {asset_sale_value:>18,.2f}")

                # Place at asset sale date period
                for col_idx in range(_num_periods):
                    if _period_starts_ts[col_idx] <= asset_sale_date <= _period_ends_ts[col_idx]:
                        asset_sale_cf[col_idx] = asset_sale_value
                        print(f"      Placed at period [{col_idx}] {_period_starts_ts[col_idx].strftime('%Y-%m')}")
                        break

            except Exception as e:
                print(f"[WARN] Error computing asset sale value: {e}")
                import traceback
                traceback.print_exc()

            return pd.Series(asset_sale_cf, index=range(_num_periods))


        # ============================================================================================
        # READ LINE ITEM NAMES FROM WORKBOOK
        # ============================================================================================


        # =============================================================================
        # OUTPUT MODULE (MODULE 10)
        # =============================================================================

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
                    print(f"   [WARN] '{named_range_name}' NOT found. All 'o.*' named ranges received: {o_names}")
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
                print(f"[WARN] Error reading named range '{named_range_name}': {e}")
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

        # Hospitality P&L
        pl_line_items = None
        hospitality_pl = None

        def fn_safe_set_row(df, row_name, values):
            """
            Safely set a row value in a DataFrame.
            Matching priority:
              1. Exact match
              2. Case-insensitive exact match
              3. Normalized containment â€” template row contains our key or vice-versa
                 (stripped of parenthetical suffixes and extra whitespace)
            Only sets value if a match is found in DataFrame index.
            """
            if row_name is None or not isinstance(row_name, str) or row_name.strip() == "":
                return False

            # 1. Exact match
            if row_name in df.index:
                df.loc[row_name, :] = values
                return True

            # 2. Case-insensitive exact match
            rn_lower = row_name.lower().strip()
            for idx in df.index:
                if isinstance(idx, str) and idx.lower().strip() == rn_lower:
                    df.loc[idx, :] = values
                    return True

            # 3. Normalized containment match
            #    Strip parenthetical text, collapse whitespace, compare
            import re
            def _norm(s):
                s = re.sub(r'\(.*?\)', '', s)          # remove (Annually or Monthly) etc.
                s = re.sub(r'[^a-z0-9 ]', ' ', s.lower())  # remove special chars
                return ' '.join(s.split()).strip()       # collapse whitespace

            rn_norm = _norm(row_name)
            if not rn_norm:
                return False

            best_idx = None
            for idx in df.index:
                if not isinstance(idx, str) or idx.strip() == "":
                    continue
                idx_norm = _norm(idx)
                if not idx_norm:
                    continue
                # Either the result key is contained in the template name or vice-versa
                if rn_norm in idx_norm or idx_norm in rn_norm:
                    best_idx = idx
                    break

            if best_idx is not None:
                df.loc[best_idx, :] = values
                return True

            return False


        # ============================================================================================
        # CASHFLOW COMPUTATION FUNCTION
        # ============================================================================================

        def fn_initialize_dataframes():
            """Initialize the cashflow dataframes with line items from workbook or defaults."""
            global operations_line_items, investment_line_items, financing_line_items, pl_line_items
            global cashflow_from_operations, cashflow_from_investments, cashflow_from_financing, hospitality_pl
            # global _num_periods, _period_starts_ts, _period_ends_ts
            
            # Initialize module-level constants
            # _num_periods = len(model_timeline_me)
            # _period_starts_ts = [pd.Timestamp(x) for x in model_timeline_me["Period Start"].values]
            # _period_ends_ts = [pd.Timestamp(x) for x in model_timeline_me["Period End"].values]
            
            # print("? Reading line item names from workbook...")
            
            # CFO Line Items â€” dynamic from template, hardcoded fallback
            operations_line_items = fn_get_line_items_from_named_range("o.assetco.cfo.names")
            if not operations_line_items:
                print("   [WARN] CFO: Using default line items (named range not found)")
                operations_line_items = [
                    # Must match standard AssetCo CFS template (42 rows)
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
                print(f"   [OK] CFO: Loaded {len(operations_line_items)} line items from template")
            
            # CFI Line Items â€” dynamic from template, hardcoded fallback
            investment_line_items = fn_get_line_items_from_named_range("o.assetco.cfi.names")
            if not investment_line_items:
                print("   [WARN] CFI: Using default line items (named range not found)")
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
                    "Asset Sale Value",                     # 14
                    "",                                     # 15 Blank
                    "Net Cashflow from Investments"         # 16
                ]
            else:
                print(f"   [OK] CFI: Loaded {len(investment_line_items)} line items from template")
            
            # CFF Line Items â€” dynamic from template, hardcoded fallback
            financing_line_items = fn_get_line_items_from_named_range("o.assetco.cff.names")
            if not financing_line_items:
                print("   [WARN] CFF: Using default line items (named range not found)")
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
                print(f"   [OK] CFF: Loaded {len(financing_line_items)} line items from template")
            
            # Create DataFrames
            columns = model_timeline_me.index
            
            # Header / category rows that should remain blank (not filled with 0)
            _HEADER_ROWS = {
                "cashflow from operations",
                "cash received from asset lease", "expenses",
                "other income/expenses", "other income / expenses",
                "other income/expenses_asset co", "other income / expenses_asset co",
                "hospitality cashflow from operations",
                "cashflow from investments",
                "asset acquisition costs",
                "cashflow from financing",
            }
            # Dynamically detect CFF loan-section headers from the template:
            # any row immediately before a "Principal Drawn" row is a header.
            for _hi, _hn in enumerate(financing_line_items):
                if isinstance(_hn, str) and _hn.strip().lower() == "principal drawn" and _hi > 0:
                    _prev = financing_line_items[_hi - 1]
                    if isinstance(_prev, str) and _prev.strip():
                        _HEADER_ROWS.add(_prev.strip().lower())
            
            def _init_df(line_items):
                df = pd.DataFrame(index=line_items, columns=columns)
                for idx in df.index:
                    if isinstance(idx, str) and idx.strip() != "":
                        if idx.strip().lower() in _HEADER_ROWS:
                            df.loc[idx, :] = ""          # header ? blank
                        else:
                            df.loc[idx, :] = 0.0         # data row ? zero
                    else:
                        df.loc[idx, :] = ""              # blank row ? blank
                return df
            
            cashflow_from_operations = _init_df(operations_line_items)
            cashflow_from_investments = _init_df(investment_line_items)
            cashflow_from_financing = _init_df(financing_line_items)

            # ----------------------------------------------------------------
            # HOSPITALITY P&L LINE ITEMS  (USALI-style)
            # Try dynamic loading from template first, fall back to hardcoded
            # ----------------------------------------------------------------
            pl_line_items = fn_get_line_items_from_named_range("o.hospitality.pl.names")
            if not pl_line_items:
                print("   [WARN] P&L: Using default line items (named range not found)")
                pl_line_items = [
                    # Operating Metrics
                    "Operating Metrics",                        # Header
                    "Days",
                    "Keys",
                    "Room Nights Available",
                    "Occupancy",
                    "Room Nights Sold",
                    "Guest Nights Sold",
                    "ADR",
                    "RevPAR",
                    "",                                         # Blank
                    # Operating Revenue
                    "Operating Revenue",                        # Header
                    "Room Revenue",
                    "",                                         # Blank
                    "Food & Beverage Revenue",
                    "In Room-Dining",
                    "Venue",
                    "Other F&B Revenue",
                    "",                                         # Blank
                    "Other Operating Department Revenue",
                    "Golf Revenue",
                    "Spa & Wellness",
                    "Banquet & Conference Revenue",
                    "Guest Laundry Revenue",
                    "",                                         # Blank
                    "Other Operating Revenue",
                    "Minor Operating Department",
                    "Cancellation Charges",
                    "Miscellaneous Income",
                    "Parking Revenue",
                    "",                                         # Blank
                    "Total Operating Revenue",
                    "",                                         # Blank
                    # Departmental Expenses
                    "Departmental Expenses",                    # Header
                    "Room Expense",
                    "F&B Expense",
                    "Golf Expense",
                    "Spa & Wellness Expense",
                    "Banquet & Conference Expense",
                    "Laundry Expense",
                    "Other Operating Department Expense",
                    "Other Departmental Expenses",
                    "Other Operating Expenses",
                    "Parking Expense",
                    "Total Departmental Expenses",
                    "",                                         # Blank
                    "Departmental Income",
                    "",                                         # Blank
                    # Undistributed Expenses
                    "Undistributed Expenses",                   # Header
                    "Admin & General",
                    "Sales & Marketing",
                    "Franchise & Affiliation Advertising",
                    "Loyalty Programs",
                    "Other Expense (S&M)",
                    "Info & Telecom Systems",
                    "Utility Costs",
                    "Electricity",
                    "Gas",
                    "Water & Sewer",
                    "Other Expense (Utility)",
                    "Total Undistributed Expenses",
                    "",                                         # Blank
                    "Gross Operating Profit",
                    "GOP Margin",
                    "",                                         # Blank
                    # Management Fees
                    "Management Fees",                          # Header
                    "Base Management Fee",
                    "Incentive Fee",
                    "Total Management Fees",
                    "",                                         # Blank
                    "Income Before Non-Operating I&E",
                    "",                                         # Blank
                    "Insurance",
                    "Other Income 1",
                    "Other Income 2",
                    "Other Income 3",
                    "Other Expense 1",
                    "Other Expense 2",
                    "Other Expense 3",
                    "Total Non-Operating I&E",
                    "",                                         # Blank
                    "EBITDA",
                    "",                                         # Blank
                    "FF&E Reserve",
                    "Capital Reserve",
                    "",                                         # Blank
                    "EBITDA Less Reserve",
                    "EBITDA Margin",
                    "",                                         # Blank
                    "Pre-Opening Expenses",
                    "",                                         # Blank
                    "Depreciation & Amortization",
                    "",                                         # Blank
                    "EBIT",
                    "",                                         # Blank
                    "Interest Expense",
                    "",                                         # Blank
                    "EBT",
                    "Income Tax",
                    "",                                         # Blank
                    "Net Income",
                ]
            else:
                print(f"   [OK] P&L: Loaded {len(pl_line_items)} line items from template")

            # Headers specific to P&L (should contain "" not 0)
            # NOTE: F&B Revenue, OOD Revenue, Other Operating Revenue are SUBTOTALS
            # that MUST be populated â€” they are NOT section headers.
            _PL_HEADER_ROWS = {
                "operating metrics", "operating revenue",
                "departmental expenses", "undistributed expenses",
                "management fees",
                "non-operating income & expenses",
                "non operating income and expenses",
            }

            def _init_pl_df(items):
                df = pd.DataFrame(index=items, columns=columns)
                _header_names = []
                for idx in df.index:
                    if isinstance(idx, str) and idx.strip() != "":
                        _idx_low = idx.strip().lower()
                        _is_header = _idx_low in _PL_HEADER_ROWS
                        if _is_header:
                            df.loc[idx, :] = ""
                            _header_names.append(idx)
                        else:
                            df.loc[idx, :] = 0.0
                    else:
                        df.loc[idx, :] = ""
                if _header_names:
                    print(f"   [PL-INIT] Rows set as HEADER (blank): {_header_names}")
                return df

            hospitality_pl = _init_pl_df(pl_line_items)
            print(f"   [OK] Hospitality P&L: Initialized {len(pl_line_items)} line items")


        # ============================================================================================
        # HOSPITALITY HELPER: Safe float / schedule reader / profile reader
        # ============================================================================================

        def _safe_float(val, default=0.0):
            """Convert value to float safely."""
            if val is None:
                return default
            if isinstance(val, (list, np.ndarray)):
                if len(val) == 0:
                    return default
                val = val[0]
                if val is None:
                    return default
            try:
                if isinstance(val, (float, np.floating)) and pd.isna(val):
                    return default
            except (ValueError, TypeError):
                pass
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        def _safe_pct(val, default=0.0):
            """Convert percentage value (may be 0-1 or 0-100 from Excel)."""
            v = _safe_float(val, default)
            if abs(v) > 1 and abs(v) <= 100:
                return v / 100.0
            return v

        def _read_schedule(named_range_name):
            """Read a schedule (monthly values) from a named range.
            Returns a flat list of values aligned to model periods, or None."""
            try:
                result = assumptions.loc[assumptions["name"] == named_range_name, "value"]
                if result.empty:
                    print(f"   [SCHED] '{named_range_name}' not found in assumptions")
                    return None
                raw = result.iloc[0]
                # Handle list (possibly nested)
                if isinstance(raw, list):
                    if len(raw) > 0 and isinstance(raw[0], list):
                        print(f"   [SCHED] '{named_range_name}' -> nested list, len={len(raw[0])}")
                        return raw[0]
                    print(f"   [SCHED] '{named_range_name}' -> list, len={len(raw)}")
                    return raw
                # Handle numpy array
                if isinstance(raw, np.ndarray):
                    flat = raw.flatten().tolist()
                    print(f"   [SCHED] '{named_range_name}' -> ndarray, len={len(flat)}")
                    return flat
                # Handle pandas Series
                if isinstance(raw, pd.Series):
                    flat = raw.tolist()
                    print(f"   [SCHED] '{named_range_name}' -> Series, len={len(flat)}")
                    return flat
                # Handle JSON string
                if isinstance(raw, str):
                    raw_stripped = raw.strip()
                    if raw_stripped.startswith('['):
                        import json
                        parsed = json.loads(raw_stripped)
                        if isinstance(parsed, list):
                            if len(parsed) > 0 and isinstance(parsed[0], list):
                                print(f"   [SCHED] '{named_range_name}' -> JSON nested list, len={len(parsed[0])}")
                                return parsed[0]
                            print(f"   [SCHED] '{named_range_name}' -> JSON list, len={len(parsed)}")
                            return parsed
                # Handle scalar or other types
                print(f"   [SCHED] '{named_range_name}' -> unhandled type: {type(raw).__name__}")
                return None
            except Exception as e:
                print(f"   [SCHED] '{named_range_name}' error: {e}")
                return None

        def _schedule_to_series(schedule, default_val=0.0):
            """Convert a schedule list to a numpy array of length _num_periods,
            padding with default_val if schedule is shorter."""
            arr = np.full(_num_periods, default_val)
            if schedule is None:
                return arr
            for i in range(min(len(schedule), _num_periods)):
                try:
                    v = float(schedule[i]) if schedule[i] is not None and not (isinstance(schedule[i], float) and pd.isna(schedule[i])) else default_val
                    arr[i] = v
                except (ValueError, TypeError):
                    arr[i] = default_val
            return arr

        def _clean_numeric_string(s):
            """Clean a string value from Excel into a float-parseable form.
            Handles: commas, percentage signs, currency prefixes, parentheses for negatives."""
            if not isinstance(s, str):
                return s
            s = s.strip()
            if not s:
                return s
            # Remove currency prefixes (SAR, USD, AED, etc.)
            import re as _re_local
            s = _re_local.sub(r'^[A-Za-z]{2,4}\s*', '', s).strip()
            # Handle parentheses as negative: (1,234) -> -1234
            if s.startswith('(') and s.endswith(')'):
                s = '-' + s[1:-1]
            # Remove thousands separators (commas)
            s = s.replace(',', '')
            # Handle percentage: "45%" -> "0.45"
            if s.endswith('%'):
                s = s[:-1].strip()
                try:
                    return str(float(s) / 100.0)
                except (ValueError, TypeError):
                    return s
            return s

        def _has_schedule_value(raw_list, idx):
            """Check if raw schedule list has a real value at index idx.
            Returns (True, float_val) or (False, None).
            A zero from the schedule IS a valid override value."""
            if raw_list is None or idx >= len(raw_list):
                return False, None
            v = raw_list[idx]
            if v is None:
                return False, None
            if isinstance(v, str):
                v = _clean_numeric_string(v)
                if not v or v == '':
                    return False, None
                try:
                    return True, float(v)
                except (ValueError, TypeError):
                    return False, None
            if isinstance(v, float) and pd.isna(v):
                return False, None
            try:
                return True, float(v)
            except (ValueError, TypeError):
                return False, None

        def _read_profile_series(profile_named_range, values_named_range):
            """Read a profile (name->year->rate) pair from assumptions.
            Returns dict mapping profile_name -> {year: rate}."""
            profiles = {}
            try:
                pn_df = assumptions.loc[assumptions["name"] == profile_named_range, "value"]
                rv_df = assumptions.loc[assumptions["name"] == values_named_range, "value"]
                if pn_df.empty or rv_df.empty:
                    return profiles
                profile_names = pn_df.iloc[0]
                rate_values = rv_df.iloc[0]
                if not isinstance(profile_names, list):
                    profile_names = [profile_names]
                for i, pname in enumerate(profile_names):
                    if pname is None or (isinstance(pname, float) and pd.isna(pname)):
                        continue
                    pname = str(pname).strip()
                    if not pname:
                        continue
                    profiles[pname] = {}
                    if isinstance(rate_values, list) and i < len(rate_values):
                        yr_rates = rate_values[i]
                        # Single profile with flat list of scalars:
                        # e.g. profile_names=["CPI"], rate_values=[0.03, 0.03, 0.04]
                        # rate_values[0]=0.03 (scalar) but the WHOLE list is year rates
                        if (not isinstance(yr_rates, list)
                                and len(profile_names) == 1
                                and all(not isinstance(v, list) for v in rate_values)):
                            yr_rates = rate_values  # treat entire flat list as year rates
                        if isinstance(yr_rates, list):
                            for yr_idx, rate in enumerate(yr_rates):
                                yr = yr_idx + 1
                                try:
                                    profiles[pname][yr] = float(rate) if rate is not None and not (isinstance(rate, float) and pd.isna(rate)) else 0.0
                                except (ValueError, TypeError):
                                    profiles[pname][yr] = 0.0
                        else:
                            try:
                                profiles[pname][1] = float(yr_rates) if yr_rates is not None else 0.0
                            except (ValueError, TypeError):
                                profiles[pname][1] = 0.0
            except Exception as e:
                print(f"   [WARN] Error reading profiles {profile_named_range}: {e}")
            return profiles

        def _read_all_escalation_profiles():
            """Discover ALL a.hospitality.*escalation* profile/value named ranges
            and merge into a single {profile_name: {year: rate}} dict.
            This ensures every escalation profile name is findable regardless
            of which named range table it lives in."""
            merged = {}
            all_names = assumptions["name"].tolist()
            # Find all profile name ranges with flexible matching:
            #   a.hospitality.*.escalation*.profiles  (primary)
            #   a.hospitality.*.escalation*.profile   (singular variant)
            #   a.hospitality.*profile*  containing 'escalation' (broad)
            prof_ranges = sorted(set(
                n for n in all_names
                if isinstance(n, str)
                and n.startswith("a.hospitality.")
                and "escalation" in n.lower()
                and (n.endswith(".profiles") or n.endswith(".profile"))
            ))
            # Also discover any a.hospitality.* range ending in .profiles
            # that might contain escalation data without 'escalation' in the name
            _extra = sorted(set(
                n for n in all_names
                if isinstance(n, str)
                and n.startswith("a.hospitality.")
                and (n.endswith(".profiles") or n.endswith(".profile"))
                and n not in prof_ranges
            ))
            if _extra:
                print(f"   [ESC] Extra profile-like ranges (no 'escalation' in name): {_extra}")
                prof_ranges = prof_ranges + _extra
            for pr in prof_ranges:
                # Derive the matching values range
                if pr.endswith(".profiles"):
                    base = pr[:-len(".profiles")]
                else:
                    base = pr[:-len(".profile")]
                candidates = [base + ".values", base + ".value",
                              base + ".rates", base + ".rate"]
                vr = None
                for c in candidates:
                    if c in all_names:
                        vr = c
                        break
                if vr is None:
                    print(f"   [ESC] WARN: no values range found for {pr}, tried: {candidates}")
                    continue
                profiles = _read_profile_series(pr, vr)
                if profiles:
                    merged.update(profiles)
                    print(f"   [ESC]   {pr} + {vr} -> {list(profiles.keys())}")
                else:
                    print(f"   [ESC]   {pr} + {vr} -> EMPTY")
            # Summary
            print(f"   [ESC] Merged escalation profiles from {len(prof_ranges)} ranges: "
                  f"{prof_ranges}")
            print(f"   [ESC] Profile names available: {list(merged.keys())}")
            for pn, pdata in merged.items():
                print(f"   [ESC]   '{pn}': {dict(list(pdata.items())[:6])}")
            return merged

        def _get_profile_rate(profile_name, year_num, profiles_dict):
            """Get escalation rate for a given profile name and year number."""
            if not profile_name or not profiles_dict:
                return 0.0
            try:
                if isinstance(profile_name, (float, np.floating)) and pd.isna(profile_name):
                    return 0.0
            except (ValueError, TypeError):
                pass
            pname = str(profile_name).strip()
            if pname not in profiles_dict:
                # Fuzzy match
                pname_lower = pname.lower().replace("_", " ").strip()
                for k in profiles_dict:
                    if str(k).strip().lower().replace("_", " ").strip() == pname_lower:
                        pname = k
                        break
                else:
                    return 0.0
            profile = profiles_dict[pname]
            if year_num in profile:
                return profile[year_num]
            if profile:
                return profile[max(profile.keys())]
            return 0.0

        def _get_year_for_period(period_start, start_date):
            """Determine year number: Year 1 = calendar year of start_date."""
            if start_date is None or period_start is None or period_start < start_date:
                return None
            return max(1, period_start.year - start_date.year + 1)

        def _apply_date_bounds(arr, start_date=None, end_date=None):
            """Zero-out entries outside [start_date, end_date]."""
            out = arr.copy()
            for col_idx in range(_num_periods):
                ps = _period_starts_ts[col_idx]
                pe = _period_ends_ts[col_idx]
                if start_date and pe < start_date:
                    out[col_idx] = 0.0
                if end_date and ps > end_date:
                    out[col_idx] = 0.0
            return out

        def _compute_escalation_factors(profile_name, profiles_dict, model_start, ops_start):
            """
            Compute per-period escalation factors — monthly compounding, flat within year.

            Matches AssetCo model annual_year basis:
              - Monthly rate = annual_profile_rate / 12
              - Compounding runs from model_start month-by-month
              - Factor for a period = compound(0 .. years_elapsed*12)
                where years_elapsed = period.year - model_start.year
              - Model start year: years_elapsed=0 => factor = 1.0
              - Each subsequent calendar year steps up once at Jan 1st

            Example  model_start=2019, Yr1=10%, Yr2=10%:
              2019 (yr1): 1.0                   (0 months compounded)
              2020 (yr2): (1+0.10/12)^12 = 1.10471   (12 months of yr1 rate)
              2021 (yr3): (1+0.10/12)^12 * (1+0.10/12)^12 = 1.22039

            Returns np.ndarray of length _num_periods.
            """
            factors = np.ones(_num_periods)
            if not profile_name or not profiles_dict:
                print(f"   [ESCF] SKIP: profile_name={profile_name!r}, "
                      f"profiles_dict_empty={not profiles_dict}")
                return factors

            ms_year = model_start.year

            print(f"   [ESCF] profile={profile_name!r}, model_start={model_start}, "
                  f"ops_start={ops_start}")

            # --- Helper: monthly rate for a given yr_num ---
            def _monthly_rate(yr_num):
                rate = _get_profile_rate(profile_name, yr_num, profiles_dict)
                # Normalise whole-number percentages (e.g. 3 -> 0.03)
                if abs(rate) > 1 and abs(rate) <= 100:
                    rate = rate / 100.0
                return rate / 12.0

            # --- Build cumulative factor per yr_num (monthly compounding) ---
            last_period_year = (_period_starts_ts[-1].year
                                if _num_periods > 0 else ms_year)
            max_yr_num = last_period_year - ms_year + 2  # +2 safety

            yearly_factor = {1: 1.0}
            cum = 1.0
            for yr_num in range(2, max_yr_num + 1):
                # Year N factor: compound year (N-1) monthly rate for 12 months
                mr = _monthly_rate(yr_num - 1)
                cum *= (1 + mr) ** 12
                yearly_factor[yr_num] = cum

            # Log first few yearly factors
            _show = {k: round(v, 6) for k, v in sorted(yearly_factor.items())[:8]}
            print(f"   [ESCF] yearly_factor (yr_num -> cum): {_show}")

            # --- Assign flat factor per period based on calendar year ---
            for col_idx in range(_num_periods):
                yr_num = _period_starts_ts[col_idx].year - ms_year + 1
                factors[col_idx] = yearly_factor.get(yr_num, cum)

            # Show representative factors
            _sample_years = sorted(set(
                ps.year for ps in _period_starts_ts[:60]))
            for _sy in _sample_years[:6]:
                _sidx = next((i for i in range(_num_periods)
                              if _period_starts_ts[i].year == _sy), None)
                if _sidx is not None:
                    print(f"   [ESCF]   {_sy} (yr_num={_sy - ms_year + 1}): "
                          f"factor={factors[_sidx]:.6f}")

            return factors

        # ============================================================================================
        # HOSPITALITY P&L: OTHER INCOME / EXPENSE COMPUTATION
        # ============================================================================================
        # For hospitality, each OI/OE item has:
        #   - start_date
        #   - incomeexpense_as_percentage_of_total_revenue  (% of Total Revenue)
        #   - override_schedule  (actuals â€” named range like s.hospitality.other.income.1 etc.)
        #
        # Logic: if override_schedule has non-zero values, use those (Actuals).
        #        otherwise compute: Total Operating Revenue Ã— percentage
        #        Bounded by [start_date..asset_sale_date]
        # ============================================================================================

        _OI_OE_ITEMS = [
            "other_income_1", "other_income_2", "other_income_3",
            "other_expense_1", "other_expense_2", "other_expense_3",
        ]

        _OI_OE_SCHEDULE_MAP = {
            "other_income_1":  "s.hospitality.other.income.1",
            "other_income_2":  "s.hospitality.other.income.2",
            "other_income_3":  "s.hospitality.other.income.3",
            "other_expense_1": "s.hospitality.other.expense.1",
            "other_expense_2": "s.hospitality.other.expense.2",
            "other_expense_3": "s.hospitality.other.expense.3",
        }

        def fn_compute_other_income_expense_item(item_name, total_revenue_arr):
            """Compute a single Other Income / Expense item for hospitality.

            Parameters
            ----------
            item_name : str   e.g. "other_income_1"
            total_revenue_arr : np.ndarray  Total Operating Revenue (monthly)

            Returns
            -------
            np.ndarray of shape (_num_periods,)
            """
            result = np.zeros(_num_periods)
            try:
                oi_cls = Global.OtherIncome

                # Read inputs from the class
                start_date_raw = getattr(oi_cls, f"{item_name}_start_date", None)
                pct_raw = getattr(oi_cls, f"{item_name}_incomeexpense_as_percentage_of_total_revenue", None)
                # override_schedule attr is loaded but the ACTUAL schedule is in a named range

                # Parse start date
                start_date = fn_parse_date(start_date_raw) if start_date_raw else fn_get_operations_start()
                if start_date is None:
                    start_date = fn_get_acquisition_date()

                # Effective start = max(start_date, acquisition_date)
                acq_date = fn_get_acquisition_date()
                effective_start = start_date
                if start_date and acq_date:
                    effective_start = max(start_date, acq_date)
                elif acq_date:
                    effective_start = acq_date

                asset_sale_date = fn_get_asset_sale_date()

                # Try to load actuals from override schedule named range
                schedule_name = _OI_OE_SCHEDULE_MAP.get(item_name)
                actuals_raw = _read_schedule(schedule_name) if schedule_name else None

                # Percentage of total revenue
                pct = _safe_pct(pct_raw, 0.0)
                # Expenses computed from % should be stored as negative
                is_expense = "expense" in item_name

                for col_idx in range(_num_periods):
                    # Schedule override priority — taken as-is regardless of dates
                    has_sched, sched_val = _has_schedule_value(actuals_raw, col_idx)
                    if has_sched:
                        result[col_idx] = sched_val
                    elif pct != 0.0:
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if effective_start and pe < effective_start:
                            continue
                        if asset_sale_date and ps > asset_sale_date:
                            continue
                        val = total_revenue_arr[col_idx] * pct
                        result[col_idx] = -val if is_expense else val
            except Exception as e:
                print(f"   [WARN] OI/OE {item_name} error: {e}")
            return result

        def fn_compute_all_other_income_expenses(total_revenue_arr):
            """Compute all 6 OI/OE items. Returns dict item_name -> np.ndarray."""
            results = {}
            for item in _OI_OE_ITEMS:
                results[item] = fn_compute_other_income_expense_item(item, total_revenue_arr)
            return results

        # ============================================================================================
        # HOSPITALITY P&L: WORKING CAPITAL
        # ============================================================================================

        def fn_compute_working_capital(total_revenue):
            """Compute Change in Working Capital for hospitality.

            Working Capital = WC% x Total Revenue for each period.
            Change in Working Capital = WC[t] - WC[t-1].
            Positive change means WC increased (cash outflow).
            Negative change means WC decreased (cash inflow).
            Returns np.ndarray of length _num_periods (the changes, not the levels).
            """
            changes = np.zeros(_num_periods)
            try:
                wc_raw = Global.HospitalityOtherAssumptions.hospitality_other_assumptions_changes_in_working_capital
                if wc_raw is None:
                    print("   [WC] No working capital assumption found, returning zeros")
                    return changes

                # Parse WC percentage(s)
                wc_pct = np.zeros(_num_periods)
                if isinstance(wc_raw, (list, np.ndarray)):
                    for i in range(min(len(wc_raw), _num_periods)):
                        wc_pct[i] = _safe_float(wc_raw[i])
                else:
                    val = _safe_float(wc_raw)
                    wc_pct[:] = val

                print(f"   [WC] WC percentage raw: {wc_raw}")
                print(f"   [WC] WC percentage parsed (first 5): {wc_pct[:5]}")

                # Working Capital level = WC% x Total Revenue
                wc_level = wc_pct * total_revenue

                print(f"   [WC] Total Revenue (first 5): {total_revenue[:5]}")
                print(f"   [WC] WC Level (first 5): {wc_level[:5]}")

                # Changes in Working Capital = WC[t] - WC[t-1]
                # For period 0: change = WC[0] - 0 = WC[0]
                changes[0] = wc_level[0]
                for t in range(1, _num_periods):
                    changes[t] = wc_level[t] - wc_level[t - 1]

                print(f"   [WC] Changes in WC (first 5): {changes[:5]}")
                print(f"   [WC] Total changes sum: {changes.sum():,.2f}")

            except Exception as e:
                print(f"   [WARN] Working capital error: {e}")
            return changes

        # ============================================================================================
        # HOSPITALITY P&L COMPUTATION
        # ============================================================================================

        def fn_compute_hospitality_pl():
            """
            Compute the full Hospitality P&L (USALI-style).

            Revenue & expense lines default to zero when inputs are missing.
            Any calculation failure for a line item is caught and returns zeros
            so the model always completes.

            Returns
            -------
            dict  mapping P&L row name ? np.ndarray of length _num_periods.
            """
            cache_key = "module:hospitality_pl"
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

            z = np.zeros(_num_periods)
            ops_start = fn_get_operations_start() or fn_get_acquisition_date()
            sale_date = fn_get_asset_sale_date()

            # Global model start â€” used as escalation Year 1 anchor everywhere
            _model_start_ts = pd.Timestamp(Global.ModelInputs.model_start_period)

            # ================================================================
            # FILE-BASED LOG â€” write diagnostics to file for debugging
            # ================================================================
            import os as _os
            _log_path = _os.path.join(_os.path.dirname(__file__), "hospitality_debug.log")
            _log_lines = []
            def _log(msg):
                """Print to console AND capture for file."""
                print(msg)
                _log_lines.append(str(msg))

            # ================================================================
            # DIAGNOSTIC: List all a.hospitality.* named ranges in assumptions
            # ================================================================
            _all_hosp_names = sorted(set(
                n for n in assumptions["name"].tolist()
                if isinstance(n, str) and n.startswith("a.hospitality.")
            ))
            _log(f"   [DIAG] a.hospitality.* named ranges ({len(_all_hosp_names)}):")
            for _hn in _all_hosp_names:
                _log(f"      {_hn}")
            # Also dump all RoomRevenueAssumptions attrs
            try:
                _rra_attrs = {k: getattr(Global.RoomRevenueAssumptions, k) for k in dir(Global.RoomRevenueAssumptions) if not k.startswith("_")}
                _log(f"   [DIAG] RoomRevenueAssumptions attrs: {_rra_attrs}")
            except Exception:
                _log("   [DIAG] RoomRevenueAssumptions not available")
            # Dump HospitalityOtherAssumptions
            try:
                _hoa_attrs = {k: getattr(Global.HospitalityOtherAssumptions, k) for k in dir(Global.HospitalityOtherAssumptions) if not k.startswith("_")}
                _log(f"   [DIAG] HospitalityOtherAssumptions attrs: {_hoa_attrs}")
            except Exception:
                _log("   [DIAG] HospitalityOtherAssumptions not available")

            # ---- Early flush: write diagnostics captured so far ----
            try:
                with open(_log_path, "w", encoding="utf-8") as _lf_early:
                    _lf_early.write("\n".join(_log_lines))
                    _lf_early.write("\n--- (early flush, computation continues) ---\n")
            except Exception:
                pass

            # ================================================================
            # DAYS PER PERIOD  (first data row in P&L)
            # ================================================================
            days_per_period = np.array([
                (pe - ps).days + 1
                for ps, pe in zip(_period_starts_ts, _period_ends_ts)
            ], dtype=float)

            # ================================================================
            # OPERATING METRICS â€” Keys / Room Nights / Occupancy / ADR / RevPAR
            # ================================================================
            keys_arr              = z.copy()   # total keys (rooms), constant each month
            room_nights_available = z.copy()   # keys Ã— days in month
            occupancy_arr         = z.copy()   # from schedule s.hospitality.occupancy (0-1)
            room_nights_sold      = z.copy()   # occupancy Ã— room nights available
            guest_nights_sold     = z.copy()   # room nights sold Ã— guest occupancy ratio
            adr_arr               = z.copy()   # escalated ADR
            revpar                = z.copy()   # room revenue / room nights available

            # Pre-initialise so F&B / OOD sections never hit NameError
            _all_esc_profiles = {}

            try:
                rt = Global.RoomType
                rra = Global.RoomRevenueAssumptions

                # -- Total keys from all room types --
                total_keys = 0
                _room_types = [
                    "deluxe", "economy", "executive", "royal_suite", "suite",
                    "type_6", "type_7", "type_8_", "type_9", "type_10",
                ]
                for rtype in _room_types:
                    keys_val = getattr(rt, f"keys_{rtype}", None)
                    if keys_val is not None and not pd.isna(keys_val):
                        total_keys += int(float(keys_val))

                if total_keys == 0:
                    # Fallback: read rooms_available from RoomRevenueAssumptions
                    rooms_raw = rra.rooms_available
                    if rooms_raw is not None and not pd.isna(rooms_raw):
                        total_keys = int(float(rooms_raw))

                _log(f"   [ROOM] Total keys (rooms): {total_keys}")

                # -- Base ADR --
                base_adr = _safe_float(rra.average_adr_, 0.0)

                # -- ALL escalation profiles (merged from all a.hospitality.*escalation* tables) --
                _all_esc_profiles = _read_all_escalation_profiles()

                # -- ADR escalation profiles --
                adr_esc_profile_name = rra.adr_escalation_profile
                adr_profiles = _all_esc_profiles  # ADR profiles are now part of the merged dict

                _log(f"   [ADR-ESC] adr_esc_profile_name={adr_esc_profile_name!r}, "
                      f"esc_profiles_count={len(_all_esc_profiles)}, "
                      f"esc_keys={list(_all_esc_profiles.keys())[:10]}")
                # Fallback: if no dedicated escalation profiles found but we
                # DO have a profile name, try loading from common range names
                if adr_esc_profile_name and not _all_esc_profiles:
                    _fallback_pairs = [
                        ("a.hospitality.escalation.profiles", "a.hospitality.escalation.values"),
                        ("a.hospitality.escalation.profiles", "a.hospitality.escalation.rates"),
                        ("a.hospitality.escalation.profile", "a.hospitality.escalation.values"),
                        ("a.hospitality.escalation.profile", "a.hospitality.escalation.rate"),
                        ("a.hospitality.room.revenue.escalation.profiles", "a.hospitality.room.revenue.escalation.values"),
                        ("a.hospitality.room.revenue.escalation.profile", "a.hospitality.room.revenue.escalation.values"),
                        ("a.hospitality.adr.escalation.profiles", "a.hospitality.adr.escalation.values"),
                    ]
                    for _fp, _fv in _fallback_pairs:
                        _fprof = _read_profile_series(_fp, _fv)
                        if _fprof:
                            _log(f"   [ADR-ESC] Fallback loaded from {_fp} + {_fv}: {list(_fprof.keys())}")
                            adr_profiles = _fprof
                            break
                    if not adr_profiles:
                        _log(f"   [ADR-ESC] WARNING: No escalation profiles found anywhere! ADR will be flat.")

                # -- Occupancy schedule (monthly, from Excel) --
                occ_schedule = _read_schedule("s.hospitality.occupancy")
                occ_raw_arr = _schedule_to_series(occ_schedule) if occ_schedule else None

                # -- Guest occupancy ratio --
                guest_occ_ratio = _safe_float(rra.guest_occupancy_ratio, 1.0)
                if guest_occ_ratio > 10:
                    guest_occ_ratio = guest_occ_ratio / 100.0   # e.g. 150 -> 1.50

                # -- Revenue / operations start date --
                rev_start = fn_parse_date(rra.start_date) if rra.start_date else ops_start

                # -- Pre-compute ADR escalation factors (monthly catch-up -> annual step) --
                _adr_esc_factors = _compute_escalation_factors(
                    adr_esc_profile_name, adr_profiles, _model_start_ts, rev_start)

                # -- Build arrays period-by-period --
                for col_idx in range(_num_periods):
                    ps = _period_starts_ts[col_idx]
                    pe = _period_ends_ts[col_idx]
                    if rev_start and pe < rev_start:
                        continue
                    if sale_date and ps > sale_date:
                        continue

                    days_in_month = (pe - ps).days + 1

                    # Keys â€” constant every month
                    keys_arr[col_idx] = total_keys

                    # Room Nights Available = Keys Ã— Days
                    room_nights_available[col_idx] = total_keys * days_in_month

                    # Occupancy from schedule (convert >1 values to fraction)
                    occ = 0.0
                    if occ_raw_arr is not None and col_idx < len(occ_raw_arr):
                        occ = _safe_float(occ_raw_arr[col_idx])
                        if occ > 1:
                            occ = occ / 100.0
                    occupancy_arr[col_idx] = occ

                    # Room Nights Sold = Occupancy Ã— Room Nights Available
                    room_nights_sold[col_idx] = occupancy_arr[col_idx] * room_nights_available[col_idx]

                    # Guest Nights Sold = Room Nights Sold Ã— Guest Occupancy Ratio
                    guest_nights_sold[col_idx] = room_nights_sold[col_idx] * guest_occ_ratio

                    # ADR: monthly catch-up from Model Start ? rev_start, then annual steps
                    period_adr = base_adr * _adr_esc_factors[col_idx]
                    adr_arr[col_idx] = period_adr

                    # RevPAR = ADR Ã— Occupancy
                    revpar[col_idx] = period_adr * occ

                _log(f"   [ROOM] Base ADR: {base_adr:,.2f}  Guest Occ Ratio: {guest_occ_ratio:.2f}")
                _log(f"   [ROOM] Rev start: {rev_start}  Escalation profile: {adr_esc_profile_name}")
                _log(f"   [ROOM] ADR escalation factors first12: {_adr_esc_factors[:12].tolist()}")
                _log(f"   [ROOM] ADR first12: {adr_arr[:12].tolist()}")
                _log(f"   [ROOM] room_nights_available sum={room_nights_available.sum():,.0f}  first5={room_nights_available[:5].tolist()}")
                _log(f"   [ROOM] room_nights_sold sum={room_nights_sold.sum():,.0f}  first5={room_nights_sold[:5].tolist()}")
                _log(f"   [ROOM] occupancy_arr first5={occupancy_arr[:5].tolist()}")
                _log(f"   [ROOM] keys_arr first5={keys_arr[:5].tolist()}")                
                # Also log rooms_revenue
                _log(f"   [ROOM] rooms_revenue (ADR*sold) first5: {(adr_arr * room_nights_sold)[:5].tolist()}")
            except Exception as e:
                _log(f"   [WARN] Room metrics error: {e}")
                import traceback; traceback.print_exc()

            # ================================================================
            # ROOMS REVENUE = ADR Ã— Room Nights Sold
            # ================================================================
            rooms_revenue = adr_arr * room_nights_sold

            # ================================================================
            # F&B REVENUE â€” 3 components:  In Room-Dining, Venue, Other F&B
            # Each component supports two revenue bases:
            #   High Level  ? percentage_of_room_revenue Ã— rooms_revenue
            #   Detailed    ? guest_nights_sold Ã— capture_rate(profile) Ã— avg_order(escalated)
            # ================================================================
            in_room_dining_rev = z.copy()
            venue_rev = z.copy()
            other_fb_rev = z.copy()
            fb_revenue = z.copy()

            try:
                fb = Global.FBRevenueAssumptions

                # ---- Guest Capture Rate profiles ----
                _gcr_profiles = _read_profile_series(
                    "a.hospitality.guest.capture.rate.profiles",
                    "a.hospitality.guest.capture.rate.values",
                )

                # ---- Escalation profiles for F&B order values (from merged dict) ----
                _fb_esc_profiles = _all_esc_profiles

                # --- Dump ALL F&B class attributes for diagnostics ---
                _fb_attrs = {a: getattr(fb, a) for a in dir(fb)
                             if not a.startswith('_') and not callable(getattr(fb, a, None))}
                _log(f"   [F&B] ALL FBRevenueAssumptions attrs: {_fb_attrs}")

                # =========================================================
                # (A) IN ROOM-DINING
                # =========================================================
                ird_basis = str(getattr(fb, "in_room_dining__revenue_basis", "") or "").strip().lower()
                _ird_start_raw = getattr(fb, "in_room_dining__start_date", None)
                _ird_start_parsed = fn_parse_date(_ird_start_raw)
                ird_start = _ird_start_parsed or ops_start
                ird_pct = _safe_pct(getattr(fb, "in_room_dining__percentage_of_room_revenue", None))
                ird_gcr_name = getattr(fb, "in_room_dining__inhouse_guest_capture_rate_in_room_dining", None)
                ird_avg_order = _safe_float(getattr(fb, "in_room_dining__avg_order_value", None))
                ird_esc_profile = getattr(fb, "in_room_dining__escalation_profile", None)

                _log(f"   [F&B] In-Room-Dining: start_raw={_ird_start_raw!r}, type={type(_ird_start_raw).__name__}, "
                      f"parsed={_ird_start_parsed}, using={ird_start}")
                _log(f"   [F&B] In-Room-Dining: basis={ird_basis!r}, pct={ird_pct}, "
                      f"gcr={ird_gcr_name!r}, avg_order={ird_avg_order}, esc={ird_esc_profile!r}")

                if "high" in ird_basis or (ird_basis == "" and ird_pct != 0):
                    # High Level: % of Room Revenue
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ird_start and pe < ird_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        in_room_dining_rev[col_idx] = rooms_revenue[col_idx] * ird_pct
                elif "detail" in ird_basis:
                    # Detailed: Guest Nights Sold Ã— Capture Rate Ã— Escalated Avg Order
                    _ird_esc_factors = _compute_escalation_factors(
                        ird_esc_profile, _fb_esc_profiles, _model_start_ts, ird_start)
                    _log(f"   [F&B] IRD GCR profiles loaded: {list(_gcr_profiles.keys()) if _gcr_profiles else 'NONE'}")
                    _ird_diag_logged = False
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ird_start and pe < ird_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        yr = _get_year_for_period(ps, ird_start)
                        gcr_raw = _get_profile_rate(ird_gcr_name, yr, _gcr_profiles) if yr else 0.0
                        gcr = gcr_raw
                        if gcr > 1:
                            gcr = gcr / 100.0
                        order_val = ird_avg_order * _ird_esc_factors[col_idx]
                        in_room_dining_rev[col_idx] = guest_nights_sold[col_idx] * gcr * order_val
                        if not _ird_diag_logged:
                            _log(f"   [F&B] IRD period[{col_idx}] {ps.date()}: yr={yr}, gcr_raw={gcr_raw}, gcr={gcr}, "
                                  f"esc_f={_ird_esc_factors[col_idx]:.4f}, avg_order={ird_avg_order}, order_esc={order_val:.2f}, "
                                  f"gns={guest_nights_sold[col_idx]:.1f}, rev={in_room_dining_rev[col_idx]:,.0f}")
                            _ird_diag_logged = True

                # =========================================================
                # (B) VENUE
                # =========================================================
                ven_basis = str(getattr(fb, "venue__fb_revenue_basis", "") or "").strip().lower()
                _ven_start_raw = getattr(fb, "venue__fb_start_date", None)
                _ven_start_parsed = fn_parse_date(_ven_start_raw)
                ven_start = _ven_start_parsed or ops_start
                _log(f"   [F&B] Venue: start_raw={_ven_start_raw!r}, type={type(_ven_start_raw).__name__}, "
                      f"parsed={_ven_start_parsed}, using={ven_start}")
                ven_pct = _safe_pct(getattr(fb, "venue__fb_percentage_of_room_revenue", None))
                ven_capacity = _safe_float(getattr(fb, "venue__fb_venue_capacity", None))
                ven_walkin_profile_name = getattr(fb, "venue__fb_average_daily_walkin_guests", None)
                ven_avg_order = _safe_float(getattr(fb, "venue__fb_avg_order_value", None))
                ven_esc_profile = getattr(fb, "venue__fb_escalation_profile", None)

                # ---- ADWI (Average Daily Walk-in) guest profiles ----
                _adwi_profiles = _read_profile_series(
                    "a.hospitality.adwi.guests.profiles",
                    "a.hospitality.adwi.guests.values",
                )

                _log(f"   [F&B] Venue: basis={ven_basis!r}, pct={ven_pct}, "
                      f"capacity={ven_capacity}, walkin_profile={ven_walkin_profile_name!r}, "
                      f"avg_order={ven_avg_order}, esc={ven_esc_profile!r}")
                _log(f"   [F&B] Venue: ADWI profiles loaded: {list(_adwi_profiles.keys()) if _adwi_profiles else 'NONE'}")

                if "high" in ven_basis or (ven_basis == "" and ven_pct != 0):
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ven_start and pe < ven_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        venue_rev[col_idx] = rooms_revenue[col_idx] * ven_pct
                elif "detail" in ven_basis:
                    _ven_esc_factors = _compute_escalation_factors(
                        ven_esc_profile, _fb_esc_profiles, _model_start_ts, ven_start)
                    _ven_diag_logged = False
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ven_start and pe < ven_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        days_in_month = (pe - ps).days + 1

                        yr_venue = _get_year_for_period(ps, ven_start)
                        walkin_pct = 0.0
                        if ven_walkin_profile_name and _adwi_profiles and yr_venue:
                            walkin_pct = _get_profile_rate(ven_walkin_profile_name, yr_venue, _adwi_profiles)
                            if walkin_pct > 1:
                                walkin_pct = walkin_pct / 100.0
                        daily_walkins = walkin_pct * ven_capacity

                        # Escalated order value
                        order_val = ven_avg_order * _ven_esc_factors[col_idx]
                        venue_rev[col_idx] = daily_walkins * days_in_month * order_val
                        if not _ven_diag_logged:
                            _log(f"   [F&B] Venue period[{col_idx}] {ps.date()}: yr={yr_venue}, walkin_pct={walkin_pct}, "
                                  f"capacity={ven_capacity}, daily_walkins={daily_walkins:.1f}, days={days_in_month}, "
                                  f"esc_f={_ven_esc_factors[col_idx]:.4f}, avg_order={ven_avg_order}, order_esc={order_val:.2f}, "
                                  f"rev={venue_rev[col_idx]:,.0f}")
                            _ven_diag_logged = True

                # =========================================================
                # (C) OTHER F&B REVENUE â€” % of Room Revenue from global input
                # Uses its own start date; falls back to earliest F&B start, then ops_start
                # =========================================================
                _other_fb_start_raw = getattr(fb, "other_fb_revenue_start_date", None)
                _other_fb_start_parsed = fn_parse_date(_other_fb_start_raw)
                other_fb_start = _other_fb_start_parsed or ops_start
                _other_fb_raw = getattr(fb, "other_fb_revenue_percentage_of_room_revenue", None)
                other_fb_pct = _safe_pct(_other_fb_raw)
                _log(f"   [F&B] Other F&B: start_raw={_other_fb_start_raw!r}, parsed={_other_fb_start_parsed}, "
                      f"using={other_fb_start}, pct={other_fb_pct}")
                if other_fb_pct != 0:
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if other_fb_start and pe < other_fb_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        other_fb_rev[col_idx] = rooms_revenue[col_idx] * other_fb_pct

                fb_revenue = in_room_dining_rev + venue_rev + other_fb_rev
                _log(f"   [F&B] In-Room-Dining sum={in_room_dining_rev.sum():,.0f}")
                _log(f"   [F&B] Venue sum={venue_rev.sum():,.0f}")
                _log(f"   [F&B] Other F&B sum={other_fb_rev.sum():,.0f}")
                _log(f"   [F&B] Total F&B Revenue sum={fb_revenue.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] F&B revenue error: {e}")
                import traceback; traceback.print_exc()

            # ================================================================
            # OTHER OPERATING DEPARTMENT (OOD) REVENUE â€” individual sub-items
            # ================================================================
            golf_rev = z.copy()
            spa_rev = z.copy()
            laundry_rev = z.copy()
            banquet_rev = z.copy()
            minor_op_rev = z.copy()
            cancellation_rev = z.copy()
            misc_income_rev = z.copy()
            ood_revenue = z.copy()

            try:
                ood = Global.OODRevenueAssumptions

                # ---- Guest Capture Rate profiles (shared) ----
                _gcr_profiles_ood = _read_profile_series(
                    "a.hospitality.guest.capture.rate.profiles",
                    "a.hospitality.guest.capture.rate.values",
                )

                # ---- OOD Escalation profiles (from merged dict) ----
                _ood_esc_profiles = _all_esc_profiles

                # ==========================================================
                # GOLF REVENUE â€” High Level / Detailed toggle
                # ==========================================================
                golf_basis = str(getattr(ood, "golf_revenue_revenue_basis", "") or "").strip().lower()
                _golf_start_raw = getattr(ood, "golf_revenue_start_date", None)
                _golf_start_parsed = fn_parse_date(_golf_start_raw)
                golf_start = _golf_start_parsed or ops_start
                _log(f"   [OOD] Golf: start_raw={_golf_start_raw!r}, type={type(_golf_start_raw).__name__}, "
                      f"parsed={_golf_start_parsed}, using={golf_start}")
                golf_pct_rev = _safe_pct(getattr(ood, "golf_revenue__of_room_revenue", None))
                golf_gcr_name = getattr(ood, "golf_revenue_inhouse_guest_capture_rate_golf", None)
                golf_avg_fee = _safe_float(getattr(ood, "golf_revenue_avg_fee_per_guest", None))
                golf_esc_profile = getattr(ood, "golf_revenue_escalation_profile", None)

                _log(f"   [OOD] Golf: basis={golf_basis!r}, pct={golf_pct_rev}, "
                      f"gcr={golf_gcr_name!r}, avg_fee={golf_avg_fee}, esc={golf_esc_profile!r}")

                if "high" in golf_basis or (golf_basis == "" and golf_pct_rev != 0):
                    # High Level: % of Room Revenue
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if golf_start and pe < golf_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        golf_rev[col_idx] = rooms_revenue[col_idx] * golf_pct_rev
                elif "detail" in golf_basis:
                    # Detailed: Guest Nights Sold Ã— Capture Rate Ã— Escalated Avg Fee
                    _golf_esc_factors = _compute_escalation_factors(
                        golf_esc_profile, _ood_esc_profiles, _model_start_ts, golf_start)
                    _log(f"   [OOD] Golf GCR profiles loaded: {list(_gcr_profiles_ood.keys()) if _gcr_profiles_ood else 'NONE'}")
                    _first_active_golf_idx = None
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if golf_start and pe < golf_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        if _first_active_golf_idx is None:
                            _first_active_golf_idx = col_idx
                        yr_item = _get_year_for_period(ps, golf_start)
                        gcr = _get_profile_rate(golf_gcr_name, yr_item, _gcr_profiles_ood) if yr_item else 0.0
                        if gcr > 1:
                            gcr = gcr / 100.0
                        fee_val = golf_avg_fee * _golf_esc_factors[col_idx]
                        golf_rev[col_idx] = guest_nights_sold[col_idx] * gcr * fee_val
                        if col_idx == _first_active_golf_idx:
                            _log(f"   [OOD] Golf period[{col_idx}] {ps.date()}: yr={yr_item}, gcr_raw={_get_profile_rate(golf_gcr_name, yr_item, _gcr_profiles_ood) if yr_item else 0}, gcr={gcr}, "
                                  f"esc_f={_golf_esc_factors[col_idx]:.4f}, avg_fee={golf_avg_fee}, fee_esc={fee_val:.2f}, "
                                  f"gns={guest_nights_sold[col_idx]:.1f}, rev={golf_rev[col_idx]:,.0f}")

                _log(f"   [OOD] Golf Revenue sum={golf_rev.sum():,.0f}")

                # ==========================================================
                # SPA & WELLNESS â€” High Level / Detailed toggle
                # ==========================================================
                spa_basis = str(getattr(ood, "spa__wellness_revenue_basis", "") or "").strip().lower()
                _spa_start_raw = getattr(ood, "spa__wellness_start_date", None)
                _spa_start_parsed = fn_parse_date(_spa_start_raw)
                spa_start = _spa_start_parsed or ops_start
                _log(f"   [OOD] Spa: start_raw={_spa_start_raw!r}, type={type(_spa_start_raw).__name__}, "
                      f"parsed={_spa_start_parsed}, using={spa_start}")
                spa_pct = _safe_pct(getattr(ood, "spa__wellness__of_room_revenue", None))
                spa_gcr_name = getattr(ood, "spa__wellness_inhouse_guest_capture_rate_spa__wellness", None)
                spa_avg_spend = _safe_float(getattr(ood, "spa__wellness_avg_spa_spend_per_guest", None))
                spa_esc_profile = getattr(ood, "spa__wellness_escalation_profile", None)

                _log(f"   [OOD] Spa: basis={spa_basis!r}, pct={spa_pct}, "
                      f"gcr={spa_gcr_name!r}, avg_spend={spa_avg_spend}, esc={spa_esc_profile!r}")

                if "high" in spa_basis or (spa_basis == "" and spa_pct != 0):
                    # High Level: % of Room Revenue
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if spa_start and pe < spa_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        spa_rev[col_idx] = rooms_revenue[col_idx] * spa_pct
                elif "detail" in spa_basis:
                    # Detailed: Guest Nights Sold x Capture Rate x Escalated Avg Spa Spend
                    _spa_esc_factors = _compute_escalation_factors(
                        spa_esc_profile, _ood_esc_profiles, _model_start_ts, spa_start)
                    _spa_diag_logged = False
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if spa_start and pe < spa_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        yr_item = _get_year_for_period(ps, spa_start)
                        gcr = _get_profile_rate(spa_gcr_name, yr_item, _gcr_profiles_ood) if yr_item else 0.0
                        if gcr > 1:
                            gcr = gcr / 100.0
                        spend_val = spa_avg_spend * _spa_esc_factors[col_idx]
                        spa_rev[col_idx] = guest_nights_sold[col_idx] * gcr * spend_val
                        if not _spa_diag_logged:
                            _log(f"   [OOD] Spa period[{col_idx}] {ps.date()}: yr={yr_item}, gcr={gcr}, "
                                  f"esc_f={_spa_esc_factors[col_idx]:.4f}, avg_spend={spa_avg_spend}, "
                                  f"spend_esc={spend_val:.2f}, gns={guest_nights_sold[col_idx]:.1f}, "
                                  f"rev={spa_rev[col_idx]:,.0f}")
                            _spa_diag_logged = True

                _log(f"   [OOD] Spa & Wellness Revenue sum={spa_rev.sum():,.0f}")

                # ==========================================================
                # LAUNDRY REVENUE â€” High Level / Detailed toggle
                # ==========================================================
                lndry_basis = str(getattr(ood, "laundry_revenue_revenue_basis", "") or "").strip().lower()
                _lndry_start_raw = getattr(ood, "laundry_revenue_start_date", None)
                _lndry_start_parsed = fn_parse_date(_lndry_start_raw)
                lndry_start = _lndry_start_parsed or ops_start
                _log(f"   [OOD] Laundry: start_raw={_lndry_start_raw!r}, type={type(_lndry_start_raw).__name__}, "
                      f"parsed={_lndry_start_parsed}, using={lndry_start}")
                lndry_pct = _safe_pct(getattr(ood, "laundry_revenue__of_room_revenue", None))
                lndry_gcr_name = getattr(ood, "laundry_revenue_inhouse_guest_capture_rate_laundry", None)
                lndry_avg_spend = _safe_float(getattr(ood, "laundry_revenue_avg_laundry_spend_per_guest", None))
                lndry_esc_profile = getattr(ood, "laundry_revenue_escalation_profile", None)

                _log(f"   [OOD] Laundry: basis={lndry_basis!r}, pct={lndry_pct}, "
                      f"gcr={lndry_gcr_name!r}, avg_spend={lndry_avg_spend}, esc={lndry_esc_profile!r}")

                if "high" in lndry_basis or (lndry_basis == "" and lndry_pct != 0):
                    # High Level: % of Room Revenue
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if lndry_start and pe < lndry_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        laundry_rev[col_idx] = rooms_revenue[col_idx] * lndry_pct
                elif "detail" in lndry_basis:
                    # Detailed: Guest Nights Sold Ã— Capture Rate Ã— Escalated Avg Laundry Spend
                    # Escalation: monthly catch-up Model Start ? laundry start, then annual steps
                    _lndry_esc_factors = _compute_escalation_factors(
                        lndry_esc_profile, _ood_esc_profiles, _model_start_ts, lndry_start)
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if lndry_start and pe < lndry_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        yr_item = _get_year_for_period(ps, lndry_start)
                        gcr = _get_profile_rate(lndry_gcr_name, yr_item, _gcr_profiles_ood) if yr_item else 0.0
                        if gcr > 1:
                            gcr = gcr / 100.0
                        spend_val = lndry_avg_spend * _lndry_esc_factors[col_idx]
                        laundry_rev[col_idx] = guest_nights_sold[col_idx] * gcr * spend_val

                _log(f"   [OOD] Laundry Revenue sum={laundry_rev.sum():,.0f}")

                # ==========================================================
                # BANQUET & CONFERENCE â€” bookings (monthly) Ã— charge Ã— escalation
                # ==========================================================
                banq_charge_raw = getattr(ood, "banquet__conference_revenue_average_charge_per_event", None)
                banq_charge = _safe_float(banq_charge_raw)
                banq_esc_profile = getattr(ood, "banquet__conference_revenue_escalation_profile", None)
                _banq_start_raw = getattr(ood, "banquet__conference_revenue_start_date", None)
                _banq_start_parsed = fn_parse_date(_banq_start_raw)
                banq_start = _banq_start_parsed or ops_start

                # Read no of bookings - single-row monthly schedule from model start
                _banq_bookings_sched = _read_schedule("s.hospitality.no.of.bookings")
                if _banq_bookings_sched is not None and banq_charge > 0:
                    _banq_bookings_arr = _schedule_to_series(_banq_bookings_sched)
                    _banq_esc_factors = _compute_escalation_factors(
                        banq_esc_profile, _all_esc_profiles, _model_start_ts, banq_start)
                    for col_idx in range(_num_periods):
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if banq_start and pe < banq_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        n_bookings = _banq_bookings_arr[col_idx] if col_idx < len(_banq_bookings_arr) else 0.0
                        charge = banq_charge * _banq_esc_factors[col_idx]
                        banquet_rev[col_idx] = n_bookings * charge
                else:
                    if _banq_bookings_sched is None:
                        _log("   [OOD] Banquet: schedule 's.hospitality.no.of.bookings' not found")
                    if banq_charge == 0:
                        _log("   [OOD] Banquet: charge per event is 0")

                _log(f"   [OOD] Banquet & Conference Revenue sum={banquet_rev.sum():,.0f}")

                # ==========================================================
                # Minor Operating / Cancellation / Miscellaneous (% of Room Revenue)
                # ==========================================================
                for attr, arr, label in [
                    ("other_operating_revenue_minor_operating_revenue", minor_op_rev, "Minor Op"),
                    ("other_operating_revenue_cancellation_charges", cancellation_rev, "Cancellation"),
                    ("other_operating_revenue_miscellaneous_income", misc_income_rev, "Misc Income"),
                ]:
                    pct_val = _safe_pct(getattr(ood, attr, None))
                    if pct_val != 0:
                        for col_idx in range(_num_periods):
                            ps = _period_starts_ts[col_idx]
                            pe = _period_ends_ts[col_idx]
                            if ops_start and pe < ops_start:
                                continue
                            if sale_date and ps > sale_date:
                                continue
                            arr[col_idx] = rooms_revenue[col_idx] * pct_val
                        _log(f"   [OOD] {label}: pct={pct_val}, sum={arr.sum():,.0f}")

                ood_revenue = golf_rev + spa_rev + laundry_rev + banquet_rev + minor_op_rev + cancellation_rev + misc_income_rev
                _log(f"   [OOD] Total OOD Revenue sum={ood_revenue.sum():,.0f}")

            except Exception as e:
                _log(f"   [WARN] OOD revenue error: {e}")
                import traceback; traceback.print_exc()

            # ================================================================
            # PARKING REVENUE  =  No. of Bays Ã— Escalated Rate Ã— Occupancy %
            # Occupancy & rate escalation are mapped by operating year
            # (Year 1 = first year from parking start date, NOT calendar year)
            # ================================================================
            parking_revenue = z.copy()
            try:
                ood = Global.OODRevenueAssumptions
                pr = Global.ParkingRevenue
                n_bays = _safe_float(getattr(ood, "parking_revenue_no_of_bays", None))
                rate_pm = _safe_float(getattr(ood, "parking_revenue_rate_per_month", None))
                park_start = fn_parse_date(getattr(ood, "parking_revenue_start_date", None)) or ops_start

                # Occupancy profile  (profile name ? {year: occupancy%})
                _park_occ_profiles = _read_profile_series(
                    "a.hospitality.parking.occupancy.profiles",
                    "a.hospitality.parking.occupancy.values",
                )
                occ_profile_name = getattr(ood, "parking_revenue_occupancy_profile", None)

                # Rate escalation profile  (profile name ? {year: esc_rate})
                _park_esc_profiles = _read_profile_series(
                    "a.hospitality.parking.rate.escalation.profiles",
                    "a.hospitality.parking.rate.escalation.values",
                )
                rate_esc_name = getattr(pr, "parking_revenue_parking_rate_escalation", None)

                # Read actuals schedule for parking revenue
                park_rev_actuals_sched = _read_schedule("s.hospitality.parking.revenue.actuals")

                _log(f"   [PARK] bays={n_bays}, rate_pm={rate_pm}, start={park_start}, "
                      f"occ_profile={occ_profile_name!r}, esc_profile={rate_esc_name!r}, "
                      f"actuals_sched={'YES' if park_rev_actuals_sched else 'NO'}")

                if n_bays > 0 and rate_pm > 0:
                    # Escalation: monthly catch-up Model Start ? parking start, then annual steps
                    _park_esc_factors = _compute_escalation_factors(
                        rate_esc_name, _park_esc_profiles, _model_start_ts, park_start)
                    for col_idx in range(_num_periods):
                        # Actuals from schedule take priority
                        has_val, val = _has_schedule_value(park_rev_actuals_sched, col_idx)
                        if has_val:
                            parking_revenue[col_idx] = val
                            continue

                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if park_start and pe < park_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue

                        yr = _get_year_for_period(ps, park_start)

                        # --- Occupancy % from profile by operating year (item start based) ---
                        occ = 1.0
                        if occ_profile_name and _park_occ_profiles:
                            occ = _get_profile_rate(occ_profile_name, yr, _park_occ_profiles) if yr else 0.0
                            if occ > 1:
                                occ = occ / 100.0

                        # --- Rate with escalation from Model Start ---
                        period_rate = rate_pm * _park_esc_factors[col_idx]

                        parking_revenue[col_idx] = n_bays * period_rate * occ

                _log(f"   [PARK] Parking Revenue sum={parking_revenue.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Parking revenue error: {e}")
                import traceback; traceback.print_exc()

            # ================================================================
            # HEADER AGGREGATION ROWS
            # ================================================================
            # F&B Revenue = IRD + Venue + Other F&B  (already computed as fb_revenue)
            # fb_revenue is already: in_room_dining_rev + venue_rev + other_fb_rev

            # Other Operating Departmental Revenue = Golf + Spa + Laundry + Banquet
            ood_dept_revenue = golf_rev + spa_rev + laundry_rev + banquet_rev

            # Other Operating Revenue = Minor Op + Cancellation + Misc + Parking
            other_operating_revenue = minor_op_rev + cancellation_rev + misc_income_rev + parking_revenue

            # Total Operating Revenue
            total_operating_revenue = (
                rooms_revenue
                + fb_revenue
                + ood_dept_revenue
                + other_operating_revenue
            )

            # ================================================================
            # DEPARTMENTAL EXPENSES
            # ================================================================
            room_expense = z.copy()
            fb_expense = z.copy()
            ood_expense = z.copy()
            other_dept_expense = z.copy()
            parking_expense = z.copy()
            # Individual OOD expense lines (for output mapping)
            golf_exp_line = z.copy()
            spa_exp_line = z.copy()
            banq_exp_line = z.copy()
            laundry_exp_line = z.copy()
            other_operating_exp_line = z.copy()

            # Safe fallbacks for revenue start dates (may not be set if revenue section errored)
            rev_start = rev_start if 'rev_start' in dir() else ops_start
            ven_start = ven_start if 'ven_start' in dir() else ops_start
            golf_start = golf_start if 'golf_start' in dir() else ops_start
            spa_start = spa_start if 'spa_start' in dir() else ops_start
            banq_start = banq_start if 'banq_start' in dir() else ops_start
            lndry_start = lndry_start if 'lndry_start' in dir() else ops_start

            try:
                dep = Global.DepartmentalExpenseAssumptions

                # --- Room Expense: period-by-period ---
                room_raw = _read_schedule("s.hospitality.room.expense")
                room_pct = _safe_pct(getattr(dep, "room_expense_percentage_of_rooms_revenue", None))
                _log(f"   [DEPT-EXP] Room: raw sched={'YES len=' + str(len(room_raw)) if room_raw else 'NO'}, pct={room_pct}")
                if room_raw:
                    _sample = room_raw[:5]
                    _log(f"   [DEPT-EXP] Room sched sample: {_sample}, types: {[type(x).__name__ for x in _sample]}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(room_raw, i)
                    if has_val:
                        room_expense[i] = -abs(val)
                    elif room_pct != 0:
                        pe = _period_ends_ts[i]
                        if rev_start and pe < rev_start:
                            continue
                        room_expense[i] = -(rooms_revenue[i] * room_pct)
                _log(f"   [DEPT-EXP] Room Expense sum={room_expense.sum():,.0f}")

                # --- F&B Expense: period-by-period ---
                fb_raw = _read_schedule("s.hospitality.fb.expense")
                fb_exp_pct = _safe_pct(getattr(dep, "fb_expense_fixed_percentage_of_fb_revenue", None))
                _log(f"   [DEPT-EXP] F&B: raw sched={'YES len=' + str(len(fb_raw)) if fb_raw else 'NO'}, pct={fb_exp_pct}")
                if fb_raw:
                    _sample = fb_raw[:5]
                    _log(f"   [DEPT-EXP] F&B sched sample: {_sample}, types: {[type(x).__name__ for x in _sample]}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(fb_raw, i)
                    if has_val:
                        fb_expense[i] = -abs(val)
                    elif fb_exp_pct != 0:
                        pe = _period_ends_ts[i]
                        if ven_start and pe < ven_start:
                            continue
                        fb_expense[i] = -(fb_revenue[i] * fb_exp_pct)
                _log(f"   [DEPT-EXP] F&B Expense sum={fb_expense.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Dept expense error: {e}")
                import traceback; traceback.print_exc()

            try:
                ood_exp = Global.OtherOperatingDepartmentExpenseAssumptions

                # Golf expense: period-by-period
                golf_raw = _read_schedule("s.hospitality.golf.expense")
                golf_exp_pct = _safe_pct(getattr(ood_exp, "golf_expense_percentage_of_golf_revenue", None))
                _log(f"   [OOD-EXP] Golf: raw sched={'YES len=' + str(len(golf_raw)) if golf_raw else 'NO'}, pct={golf_exp_pct}")
                if golf_raw:
                    _sample = golf_raw[:5]
                    _log(f"   [OOD-EXP] Golf sched sample: {_sample}, types: {[type(x).__name__ for x in _sample]}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(golf_raw, i)
                    if has_val:
                        golf_exp_line[i] = -abs(val)
                    elif golf_exp_pct != 0:
                        pe = _period_ends_ts[i]
                        if golf_start and pe < golf_start:
                            continue
                        golf_exp_line[i] = -(golf_rev[i] * golf_exp_pct)
                ood_expense += golf_exp_line
                _log(f"   [OOD-EXP] Golf Expense sum={golf_exp_line.sum():,.0f}")

                # Spa & Wellness expense: period-by-period
                spa_raw = _read_schedule("s.hospitality.spa.wellness.expense")
                spa_exp_pct = _safe_pct(getattr(ood_exp, "spa__wellness_expense_percentage_of_spa__wellness_revenue", None))
                _log(f"   [OOD-EXP] Spa: raw sched={'YES' if spa_raw else 'NO'}, pct={spa_exp_pct}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(spa_raw, i)
                    if has_val:
                        spa_exp_line[i] = -abs(val)
                    elif spa_exp_pct != 0:
                        pe = _period_ends_ts[i]
                        if spa_start and pe < spa_start:
                            continue
                        spa_exp_line[i] = -(spa_rev[i] * spa_exp_pct)
                ood_expense += spa_exp_line
                _log(f"   [OOD-EXP] Spa Expense sum={spa_exp_line.sum():,.0f}")

                # Banquet & Conference expense: period-by-period
                banq_raw = _read_schedule("s.hospitality.banquet.conference.expense")
                banq_exp_pct = _safe_pct(getattr(ood_exp, "banquet__conference__expense_banquet__conference__expense", None))
                _log(f"   [OOD-EXP] Banquet: raw sched={'YES len=' + str(len(banq_raw)) if banq_raw else 'NO'}, pct={banq_exp_pct}")
                if banq_raw:
                    _sample = banq_raw[:5]
                    _log(f"   [OOD-EXP] Banquet sched sample: {_sample}, types: {[type(x).__name__ for x in _sample]}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(banq_raw, i)
                    if has_val:
                        banq_exp_line[i] = -abs(val)
                    elif banq_exp_pct != 0:
                        pe = _period_ends_ts[i]
                        if banq_start and pe < banq_start:
                            continue
                        banq_exp_line[i] = -(banquet_rev[i] * banq_exp_pct)
                ood_expense += banq_exp_line
                _log(f"   [OOD-EXP] Banquet Expense sum={banq_exp_line.sum():,.0f}")

                # Laundry expense: period-by-period
                laundry_raw = _read_schedule("s.hospitality.laundry.expense")
                laundry_exp_pct = _safe_pct(getattr(ood_exp, "laundry_expense_percentage_of_laundry_revenue", None))
                _log(f"   [OOD-EXP] Laundry: raw sched={'YES len=' + str(len(laundry_raw)) if laundry_raw else 'NO'}, pct={laundry_exp_pct}")
                if laundry_raw:
                    _sample = laundry_raw[:5]
                    _log(f"   [OOD-EXP] Laundry sched sample: {_sample}, types: {[type(x).__name__ for x in _sample]}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(laundry_raw, i)
                    if has_val:
                        laundry_exp_line[i] = -abs(val)
                    elif laundry_exp_pct != 0:
                        pe = _period_ends_ts[i]
                        if lndry_start and pe < lndry_start:
                            continue
                        laundry_exp_line[i] = -(laundry_rev[i] * laundry_exp_pct)
                ood_expense += laundry_exp_line
                _log(f"   [OOD-EXP] Laundry Expense sum={laundry_exp_line.sum():,.0f}")

                _log(f"   [OOD-EXP] Total OOD Expense sum={ood_expense.sum():,.0f}")

                # Other Operating Expenses: period-by-period (% of Other Operating Revenue)
                other_op_raw = _read_schedule("s.hospitality.other.operating.expenses")
                other_op_pct = _safe_pct(getattr(ood_exp, "other_departmental_expenses_other_expenses", None))
                _log(f"   [OTHER-DEPT] Other Operating: raw sched={'YES' if other_op_raw else 'NO'}, pct={other_op_pct}")
                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(other_op_raw, i)
                    if has_val:
                        other_operating_exp_line[i] = -abs(val)
                    elif other_op_pct != 0:
                        pe = _period_ends_ts[i]
                        if ops_start and pe < ops_start:
                            continue
                        other_operating_exp_line[i] = -(other_operating_revenue[i] * other_op_pct)
                other_dept_expense = other_operating_exp_line.copy()
                _log(f"   [OTHER-DEPT] Other Departmental Expense sum={other_dept_expense.sum():,.0f}")

                # Parking opex (Asset Co style: Fixed/Variable with actuals override)
                park_opex_type = getattr(ood_exp, "parking_opex_parking_opex_type", None)
                park_opex_fixed_pct = _safe_pct(getattr(ood_exp, "parking_opex_fixed_parking_opex", None))
                park_opex_profile_name = getattr(ood_exp, "parking_opex_parking_opex_profile", None)
                park_opex_sched = _read_schedule("s.hospitality.parking.opex.actuals")

                # Determine Fixed vs Variable from parking_opex_type
                _park_type_str = str(park_opex_type).strip().lower() if park_opex_type and not pd.isna(park_opex_type) else ""
                _park_is_fixed = "fixed" in _park_type_str
                _park_is_variable = "variable" in _park_type_str

                # Load parking opex profiles for Variable mode
                _park_opex_profiles = _read_profile_series(
                    "a.hospitality.parking.opex.profiles",
                    "a.hospitality.parking.opex.values",
                ) if _park_is_variable else {}

                _park_start = fn_parse_date(getattr(Global.OODRevenueAssumptions, "parking_revenue_start_date", None)) or ops_start
                _log(f"   [PARK-EXP] type={_park_type_str}, fixed_pct={park_opex_fixed_pct}, profile={park_opex_profile_name}, sched={'YES' if park_opex_sched else 'NO'}")

                for col_idx in range(_num_periods):
                    # Actuals from schedule take priority
                    has_val, val = _has_schedule_value(park_opex_sched, col_idx)
                    if has_val:
                        parking_expense[col_idx] = -abs(val)
                    else:
                        # Forecast fallback based on opex type
                        if _park_is_fixed and park_opex_fixed_pct > 0:
                            parking_expense[col_idx] = -(parking_revenue[col_idx] * park_opex_fixed_pct)
                        elif _park_is_variable and park_opex_profile_name:
                            yr = _get_year_for_period(_period_starts_ts[col_idx], _park_start)
                            if yr:
                                opex_pct = _get_profile_rate(park_opex_profile_name, yr, _park_opex_profiles)
                                if opex_pct > 1:
                                    opex_pct = opex_pct / 100.0
                                parking_expense[col_idx] = -(parking_revenue[col_idx] * opex_pct)
                _log(f"   [PARK-EXP] Parking Expense sum={parking_expense.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] OOD/parking expense error: {e}")
                import traceback; traceback.print_exc()

            total_dept_expenses = room_expense + fb_expense + ood_expense + other_dept_expense + parking_expense
            departmental_income = total_operating_revenue + total_dept_expenses

            # ================================================================
            # UNDISTRIBUTED EXPENSES
            # ================================================================
            admin_general   = z.copy()
            sales_marketing = z.copy()
            info_telecom    = z.copy()
            utility_costs   = z.copy()

            # S&M component breakdowns
            sm_franchise_advertising = z.copy()
            sm_loyalty_programs      = z.copy()
            sm_other_expense         = z.copy()

            # Utility component breakdowns
            ut_electricity   = z.copy()
            ut_gas           = z.copy()
            ut_water_sewer   = z.copy()
            ut_other_expense = z.copy()

            try:
                ue = Global.HospitalityUndistributedExpenseAssumptions

                # ----------------------------------------------------------
                # 1. Administrative & General
                # ----------------------------------------------------------
                ag_pct = _safe_pct(getattr(ue, "admin__general_expense_percentage_of_total_revenue", None))
                ag_raw = _read_schedule("s.hospitality.admin.general.expense")
                ag_start = fn_parse_date(getattr(ue, "admin__general_expense_start_date", None)) or ops_start
                _log(f"   [UNDIST] A&G: start={ag_start}, pct={ag_pct}, sched={'YES' if ag_raw else 'NO'}")

                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(ag_raw, i)
                    if has_val:
                        admin_general[i] = -abs(val)
                    elif ag_pct != 0:
                        pe = _period_ends_ts[i]
                        if ag_start and pe < ag_start:
                            continue
                        admin_general[i] = -(total_operating_revenue[i] * ag_pct)
                _log(f"   [UNDIST] A&G sum={admin_general.sum():,.0f}")

                # ----------------------------------------------------------
                # 2. Sales & Marketing
                # ----------------------------------------------------------
                sm_pct = _safe_pct(getattr(ue, "sales_and_marketing_expense_percentage_of_total_revenue", None))
                sm_start = fn_parse_date(getattr(ue, "sales_and_marketing_expense_start_date", None)) or ops_start
                sm_raw = _read_schedule("s.hospitality.sales.and.marketing.expense")
                _log(f"   [UNDIST] S&M: start={sm_start}, pct={sm_pct}, sched={'YES' if sm_raw else 'NO'}")

                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(sm_raw, i)
                    if has_val:
                        sales_marketing[i] = -abs(val)
                    elif sm_pct != 0:
                        pe = _period_ends_ts[i]
                        if sm_start and pe < sm_start:
                            continue
                        sales_marketing[i] = -(total_operating_revenue[i] * sm_pct)
                _log(f"   [UNDIST] S&M sum={sales_marketing.sum():,.0f}")

                # S&M Cost Component Breakdown (normalize weights to sum to 100%)
                sm_franchise_pct = _safe_pct(getattr(ue, "sales_and_marketing_expense_franchise_and_affiliation_advertising", None))
                sm_loyalty_pct   = _safe_pct(getattr(ue, "sales_and_marketing_expense_loyalty_programs", None))
                sm_other_pct     = _safe_pct(getattr(ue, "sales_and_marketing_expense_other_expense_sm_expense", None))
                _sm_total_wt = sm_franchise_pct + sm_loyalty_pct + sm_other_pct
                if _sm_total_wt > 0:
                    sm_franchise_advertising = sales_marketing * (sm_franchise_pct / _sm_total_wt)
                    sm_loyalty_programs      = sales_marketing * (sm_loyalty_pct / _sm_total_wt)
                    sm_other_expense         = sales_marketing * (sm_other_pct / _sm_total_wt)
                else:
                    # No breakdown weights ? assign entire total to "other"
                    sm_franchise_advertising = z.copy()
                    sm_loyalty_programs      = z.copy()
                    sm_other_expense         = sales_marketing.copy()
                _log(f"   [UNDIST] S&M breakdown: franchise={sm_franchise_pct}, loyalty={sm_loyalty_pct}, other={sm_other_pct}, total_wt={_sm_total_wt}")

                # ----------------------------------------------------------
                # 3. Info & Telecom Systems
                # ----------------------------------------------------------
                it_pct = _safe_pct(getattr(ue, "info__telecom_system_expense_percentage_of_total_revenue", None))
                it_start = fn_parse_date(getattr(ue, "info__telecom_system_expense_start_date", None)) or ops_start
                it_raw = _read_schedule("s.hospitality.info.telecom.system.expense")
                _log(f"   [UNDIST] I&T: start={it_start}, pct={it_pct}, sched={'YES' if it_raw else 'NO'}")

                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(it_raw, i)
                    if has_val:
                        info_telecom[i] = -abs(val)
                    elif it_pct != 0:
                        pe = _period_ends_ts[i]
                        if it_start and pe < it_start:
                            continue
                        info_telecom[i] = -(total_operating_revenue[i] * it_pct)
                _log(f"   [UNDIST] I&T sum={info_telecom.sum():,.0f}")

                # ----------------------------------------------------------
                # 4. Utility Costs
                # ----------------------------------------------------------
                ut_pct = _safe_pct(getattr(ue, "utility_costs_percentage_of_total_revenue", None))
                ut_start = fn_parse_date(getattr(ue, "utility_costs_start_date", None)) or ops_start
                ut_raw = _read_schedule("s.hospitality.utility.costs")
                _log(f"   [UNDIST] Utility: start={ut_start}, pct={ut_pct}, sched={'YES' if ut_raw else 'NO'}")

                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(ut_raw, i)
                    if has_val:
                        utility_costs[i] = -abs(val)
                    elif ut_pct != 0:
                        pe = _period_ends_ts[i]
                        if ut_start and pe < ut_start:
                            continue
                        utility_costs[i] = -(total_operating_revenue[i] * ut_pct)
                _log(f"   [UNDIST] Utility sum={utility_costs.sum():,.0f}")

                # Utility Cost Component Breakdown (normalize weights to sum to 100%)
                ut_elec_pct  = _safe_pct(getattr(ue, "utility_costs_electricity", None))
                ut_gas_pct   = _safe_pct(getattr(ue, "utility_costs_gas", None))
                ut_water_pct = _safe_pct(getattr(ue, "utility_costs_water__sewer", None))
                ut_oth_pct   = _safe_pct(getattr(ue, "utility_costs_other_expense_utility", None))
                _ut_total_wt = ut_elec_pct + ut_gas_pct + ut_water_pct + ut_oth_pct
                if _ut_total_wt > 0:
                    ut_electricity   = utility_costs * (ut_elec_pct / _ut_total_wt)
                    ut_gas           = utility_costs * (ut_gas_pct / _ut_total_wt)
                    ut_water_sewer   = utility_costs * (ut_water_pct / _ut_total_wt)
                    ut_other_expense = utility_costs * (ut_oth_pct / _ut_total_wt)
                else:
                    ut_electricity   = z.copy()
                    ut_gas           = z.copy()
                    ut_water_sewer   = z.copy()
                    ut_other_expense = utility_costs.copy()
                _log(f"   [UNDIST] Utility breakdown: elec={ut_elec_pct}, gas={ut_gas_pct}, water={ut_water_pct}, other={ut_oth_pct}, total_wt={_ut_total_wt}")

            except Exception as e:
                _log(f"   [WARN] Undistributed expense error: {e}")
                import traceback; traceback.print_exc()

            total_undistributed    = admin_general + sales_marketing + info_telecom + utility_costs
            gross_operating_profit = departmental_income + total_undistributed

            # GOP Margin = GOP / Total Operating Revenue (avoid div by zero)
            gop_margin = z.copy()
            _tor_safe = np.where(total_operating_revenue != 0, total_operating_revenue, 1.0)
            gop_margin = gross_operating_profit / _tor_safe
            gop_margin[total_operating_revenue == 0] = 0.0

            _log(f"   [P&L] Total Undistributed={total_undistributed.sum():,.0f}")
            _log(f"   [P&L] GOP={gross_operating_profit.sum():,.0f}")

            # ================================================================
            # MANAGEMENT FEES
            # ================================================================
            base_mgmt_fee = z.copy()
            incentive_fee = z.copy()

            # --- Base Management Fee ---
            try:
                bmf = Global.BaseManagementFees
                bmf_pct = _safe_pct(getattr(bmf, "base_management_fees_fixed_", None))
                bmf_start = fn_parse_date(getattr(bmf, "base_management_fees_start_date", None)) or ops_start
                bmf_raw = _read_schedule("s.hospitality.management.fees")
                _log(f"   [MGMT] Base: start={bmf_start}, pct={bmf_pct}, sched={'YES' if bmf_raw else 'NO'}")

                for i in range(_num_periods):
                    has_val, val = _has_schedule_value(bmf_raw, i)
                    if has_val:
                        base_mgmt_fee[i] = -abs(val)
                    elif bmf_pct != 0:
                        pe = _period_ends_ts[i]
                        if bmf_start and pe < bmf_start:
                            continue
                        base_mgmt_fee[i] = -(total_operating_revenue[i] * bmf_pct)
                _log(f"   [MGMT] Base Management Fee sum={base_mgmt_fee.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Base mgmt fee error: {e}")
                import traceback; traceback.print_exc()

            # --- Incentive Management Fee (GOP Margin slab-based) ---
            try:
                ifa = Global.IncentiveFeesAssumptions

                # Dump ALL populated attributes for debugging
                _ifa_attrs = {a: getattr(ifa, a) for a in dir(ifa)
                              if not a.startswith('_') and not callable(getattr(ifa, a, None))}
                _log(f"   [MGMT] IncentiveFeesAssumptions attrs: {_ifa_attrs}")
                # Each slab: (min_gop_attr, max_gop_attr, fee_attr)
                _slab_attrs = [
                    ("min_gop_gop__20__0",         "max_gop_gop__20__0",         "incentive_fees_gop__20__0"),
                    ("min_gop_gop__20_but__30__4", "max_gop_gop__20_but__30__4", "incentive_fees_gop__20_but__30__4"),
                    ("min_gop_gop__30_but__40__6", "max_gop_gop__30_but__40__6", "incentive_fees_gop__30_but__40__6"),
                    ("min_gop__40_but_45_8",       "max_gop__40_but_45_8",       "incentive_fees__40_but_45_8"),
                    ("min_gop_gop__45__10",        "max_gop_gop__45__10",        "incentive_fees_gop__45__10"),
                ]

                _slabs = []  # list of (min_margin, max_margin, fee_pct)
                for min_attr, max_attr, fee_attr in _slab_attrs:
                    min_val = _safe_pct(getattr(ifa, min_attr, None))
                    max_val = _safe_pct(getattr(ifa, max_attr, None))
                    fee_val = _safe_pct(getattr(ifa, fee_attr, None))
                    _slabs.append((min_val, max_val, fee_val))

                _log(f"   [MGMT] Incentive slabs (min, max, fee): {_slabs}")

                # AGOP = GOP before incentive fee (= gross_operating_profit)
                agop = gross_operating_profit.copy()

                for i in range(_num_periods):
                    ps = _period_starts_ts[i]
                    pe = _period_ends_ts[i]
                    if ops_start and pe < ops_start:
                        continue
                    if sale_date and ps > sale_date:
                        continue
                    margin = gop_margin[i]

                    # Find matching slab: margin falls between min and max
                    fee_pct = 0.0
                    for slab_min, slab_max, slab_fee in _slabs:
                        if slab_max > 0 and slab_min <= margin < slab_max:
                            fee_pct = slab_fee
                            break
                        # Last slab: max=0 or margin >= max of last slab
                        if slab_max == 0 and margin >= slab_min:
                            fee_pct = slab_fee
                            break

                    incentive_fee[i] = -(agop[i] * fee_pct)

                _log(f"   [MGMT] Incentive Fee sum={incentive_fee.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Incentive fee error: {e}")
                import traceback; traceback.print_exc()

            total_mgmt_fees    = base_mgmt_fee + incentive_fee
            income_before_nonop = gross_operating_profit + total_mgmt_fees

            _log(f"   [P&L] Total Mgmt Fees={total_mgmt_fees.sum():,.0f}")
            _log(f"   [P&L] Income Before Non-Op I&E={income_before_nonop.sum():,.0f}")

            # ================================================================
            # NON-OPERATING INCOME & EXPENSES
            # ================================================================
            insurance      = z.copy()
            other_income_1 = z.copy()
            other_income_2 = z.copy()
            other_income_3 = z.copy()
            other_expense_1 = z.copy()
            other_expense_2 = z.copy()
            other_expense_3 = z.copy()

            # Insurance
            try:
                ha = Global.HospitalityOtherAssumptions
                ins_start = fn_parse_date(getattr(ha, "insurance_start_date", None)) or ops_start
                ins_profile_name = getattr(ha, "insurance_profiles", None)
                ins_sched_raw = _read_schedule("s.hospitality.insurance")
                ins_profiles = None
                if ins_profile_name:
                    ins_profiles = _read_profile_series(
                        "a.hospitality.insurance.profiles",
                        "a.hospitality.insurance.values" if not assumptions.loc[assumptions["name"] == "a.hospitality.insurance.values"].empty else "a.hospitality.insurance.profiles",
                    )
                    _log(f"   [INS] Raw profiles from _read_profile_series: { {k: dict(list(v.items())[:5]) for k, v in ins_profiles.items()} if ins_profiles else 'EMPTY' }")
                    if not ins_profiles and _all_esc_profiles:
                        ins_profiles = _all_esc_profiles
                        _log(f"   [INS] Fallback to merged esc profiles for insurance")
                _log(f"   [INS] start={ins_start}, profile_name={ins_profile_name!r}, sched={'YES' if ins_sched_raw else 'NO'}, profiles={list(ins_profiles.keys()) if ins_profiles else 'NONE'}")
                if ins_profiles and ins_profile_name:
                    _pn = str(ins_profile_name).strip()
                    _pd = ins_profiles.get(_pn, {})
                    _log(f"   [INS] Profile '{_pn}' year data: {dict(list(_pd.items())[:10]) if _pd else 'EMPTY'}")
                for col_idx in range(_num_periods):
                    has_sched, sched_val = _has_schedule_value(ins_sched_raw, col_idx)
                    if has_sched:
                        insurance[col_idx] = sched_val
                    else:
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ins_start and pe < ins_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        if ins_profile_name and ins_profiles:
                            yr = _get_year_for_period(ps, ins_start)
                            if yr:
                                rate = _get_profile_rate(ins_profile_name, yr, ins_profiles)
                                insurance[col_idx] = -(total_operating_revenue[col_idx] * rate) if rate else 0
                _log(f"   [INS] sum={insurance.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Insurance error: {e}")
                import traceback; traceback.print_exc()

            # Other Income/Expenses (1-3 each)
            try:
                oie_results = fn_compute_all_other_income_expenses(total_operating_revenue)
                other_income_1  = oie_results.get("other_income_1", z.copy())
                other_income_2  = oie_results.get("other_income_2", z.copy())
                other_income_3  = oie_results.get("other_income_3", z.copy())
                other_expense_1 = oie_results.get("other_expense_1", z.copy())
                other_expense_2 = oie_results.get("other_expense_2", z.copy())
                other_expense_3 = oie_results.get("other_expense_3", z.copy())
            except Exception as e:
                _log(f"   [WARN] Other I/E error: {e}")

            _log(f"   [NONOP] Insurance={insurance.sum():,.0f}, OI1={other_income_1.sum():,.0f}, OI2={other_income_2.sum():,.0f}, OI3={other_income_3.sum():,.0f}, OE1={other_expense_1.sum():,.0f}, OE2={other_expense_2.sum():,.0f}, OE3={other_expense_3.sum():,.0f}")

            total_nonop_ie = (
                insurance
                + other_income_1 + other_income_2 + other_income_3
                + other_expense_1 + other_expense_2 + other_expense_3
            )
            _log(f"   [NONOP] total_nonop_ie={total_nonop_ie.sum():,.0f}")

            ebitda = income_before_nonop + total_nonop_ie

            # ================================================================
            # RESERVES (FF&E + Capital)
            # ================================================================
            ffe_reserve     = z.copy()
            capital_reserve = z.copy()

            try:
                ha = Global.HospitalityOtherAssumptions
                # FF&E Reserve â€” period-by-period schedule priority
                ffe_start = fn_parse_date(getattr(ha, "ffe_reserves_start_date", None)) or ops_start
                ffe_profile_name = getattr(ha, "ffe_reserves_profiles", None)
                ffe_sched_raw = _read_schedule("s.hospitality.ffe.reserves")
                ffe_profiles = None
                if ffe_profile_name:
                    ffe_profiles = _read_profile_series(
                        "a.hospitality.ffe.reserves.profile",
                        "a.hospitality.ffe.reserves.values" if not assumptions.loc[assumptions["name"] == "a.hospitality.ffe.reserves.values"].empty else "a.hospitality.ffe.reserves.profile",
                    )
                    if not ffe_profiles and _all_esc_profiles:
                        ffe_profiles = _all_esc_profiles
                        _log(f"   [FFE] Fallback to merged esc profiles")
                _log(f"   [FFE] start={ffe_start}, profile_name={ffe_profile_name!r}, sched={'YES' if ffe_sched_raw else 'NO'}, profiles={list(ffe_profiles.keys()) if ffe_profiles else 'NONE'}")
                for col_idx in range(_num_periods):
                    has_sched, sched_val = _has_schedule_value(ffe_sched_raw, col_idx)
                    if has_sched:
                        ffe_reserve[col_idx] = -abs(sched_val)
                    else:
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if ffe_start and pe < ffe_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        if ffe_profile_name and ffe_profiles:
                            yr = _get_year_for_period(ps, ffe_start)
                            if yr:
                                rate = _get_profile_rate(ffe_profile_name, yr, ffe_profiles)
                                ffe_reserve[col_idx] = -(total_operating_revenue[col_idx] * rate) if rate else 0
                _log(f"   [FFE] sum={ffe_reserve.sum():,.0f}")

                # Capital Reserve â€” period-by-period schedule priority
                cr_start = fn_parse_date(getattr(ha, "capital_reserves_start_date", None)) or ops_start
                cr_profile_name = getattr(ha, "capital_reserves_profiles", None)
                cr_sched_raw = _read_schedule("s.hospitality.capital.reserves")
                cr_profiles = None
                if cr_profile_name:
                    cr_profiles = _read_profile_series(
                        "a.hospitality.capital.reserves.profile",
                        "a.hospitality.capital.reserves.values" if not assumptions.loc[assumptions["name"] == "a.hospitality.capital.reserves.values"].empty else "a.hospitality.capital.reserves.profile",
                    )
                    if not cr_profiles and _all_esc_profiles:
                        cr_profiles = _all_esc_profiles
                        _log(f"   [CAPRES] Fallback to merged esc profiles")
                _log(f"   [CAPRES] start={cr_start}, profile_name={cr_profile_name!r}, sched={'YES' if cr_sched_raw else 'NO'}, profiles={list(cr_profiles.keys()) if cr_profiles else 'NONE'}")
                for col_idx in range(_num_periods):
                    has_sched, sched_val = _has_schedule_value(cr_sched_raw, col_idx)
                    if has_sched:
                        capital_reserve[col_idx] = -abs(sched_val)
                    else:
                        ps = _period_starts_ts[col_idx]
                        pe = _period_ends_ts[col_idx]
                        if cr_start and pe < cr_start:
                            continue
                        if sale_date and ps > sale_date:
                            continue
                        if cr_profile_name and cr_profiles:
                            yr = _get_year_for_period(ps, cr_start)
                            if yr:
                                rate = _get_profile_rate(cr_profile_name, yr, cr_profiles)
                                capital_reserve[col_idx] = -(total_operating_revenue[col_idx] * rate) if rate else 0
                _log(f"   [CAPRES] sum={capital_reserve.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Reserves error: {e}")
                import traceback; traceback.print_exc()

            ebitda_less_reserve = ebitda + ffe_reserve + capital_reserve

            # EBITDA Margin = EBITDA / Total Operating Revenue (safe divide)
            ebitda_margin = np.where(total_operating_revenue != 0,
                                     ebitda / total_operating_revenue, 0.0)

            # ================================================================
            # BELOW EBITDA
            # ================================================================
            pre_opening_expenses = z.copy()
            try:
                poe_sched = _read_schedule("s.hospitality.pre.opening.expenses")
                if poe_sched is None:
                    # Try from Global
                    poe_raw = getattr(Global.PreOpeningExpenses, "expense__schedules", None)
                    if poe_raw and isinstance(poe_raw, (list, np.ndarray)):
                        poe_sched = poe_raw
                if poe_sched:
                    pre_opening_expenses = _apply_date_bounds(
                        _schedule_to_series(poe_sched),
                        fn_get_acquisition_date(),
                        ops_start,  # Pre-opening only before operations start
                    )
            except Exception as e:
                _log(f"   [WARN] Pre-opening expense error: {e}")

            # ----------------------------------------------------------------
            # D&A  â€“  FLAT % of Total Operating Revenue  (schedule override priority)
            # User spec: D&A is a flat rate â€” no profiles, no complex logic.
            # ----------------------------------------------------------------
            depreciation_amort = z.copy()
            try:
                ha_da = Global.HospitalityOtherAssumptions
                da_raw = getattr(ha_da, "hospitality_other_assumptions_depreciation__amortization", None)
                da_sched_raw = _read_schedule("s.hospitality.depreciation.amortization")
                _log(f"   [D&A] da_raw={da_raw!r}, da_sched_raw={'YES' if da_sched_raw else 'NO'}")

                # Flat percentage (always compute â€” no guard)
                da_pct = 0.0
                if da_raw is not None:
                    if isinstance(da_raw, (list, np.ndarray)):
                        # If list, take first non-null element
                        for _dv in da_raw:
                            try:
                                _dvf = float(_dv)
                                if not pd.isna(_dvf) and _dvf != 0:
                                    da_pct = _safe_pct(_dvf)
                                    break
                            except (ValueError, TypeError):
                                continue
                    else:
                        da_pct = _safe_pct(da_raw)
                _log(f"   [D&A] da_pct={da_pct:.6f}")

                for col_idx in range(_num_periods):
                    ps = _period_starts_ts[col_idx]
                    pe = _period_ends_ts[col_idx]
                    if ops_start and pe < ops_start:
                        continue
                    if sale_date and ps > sale_date:
                        continue
                    has_sched, sched_val = _has_schedule_value(da_sched_raw, col_idx)
                    if has_sched:
                        depreciation_amort[col_idx] = -abs(sched_val)
                    elif da_pct != 0:
                        depreciation_amort[col_idx] = -(da_pct * total_operating_revenue[col_idx])
                _log(f"   [D&A] sum={depreciation_amort.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] D&A error: {e}")
                import traceback; traceback.print_exc()

            # ----------------------------------------------------------------
            # EBIT = EBITDA Less Reserve ? Pre-Opening Expenses ? D&A
            # ----------------------------------------------------------------
            ebit = ebitda_less_reserve - pre_opening_expenses + depreciation_amort

            # ----------------------------------------------------------------
            # Interest Expense  â€“  placeholder (filled by CFF after loan schedules)
            # ----------------------------------------------------------------
            interest_expense = z.copy()

            # ----------------------------------------------------------------
            # EBT = EBIT ? Interest Expense
            # ----------------------------------------------------------------
            ebt = ebit + interest_expense

            # ----------------------------------------------------------------
            # Income Tax  â€“  % of EBT  (only when EBT > 0; schedule override priority)
            # ----------------------------------------------------------------
            income_tax = z.copy()
            _stored_tax_pct = 0.0  # keep for CFF recomputation
            try:
                tax_raw = getattr(Global.HospitalityOtherAssumptions, "hospitality_other_assumptions_income_tax", None)
                tax_sched_raw = _read_schedule("s.hospitality.income.tax")
                _log(f"   [TAX] tax_raw={tax_raw!r}, tax_sched_raw={'YES' if tax_sched_raw else 'NO'}")

                # Flat percentage â€” always compute (no guard)
                if tax_raw is not None:
                    if isinstance(tax_raw, (list, np.ndarray)):
                        for _tv in tax_raw:
                            try:
                                _tvf = float(_tv)
                                if not pd.isna(_tvf) and _tvf != 0:
                                    _stored_tax_pct = _safe_pct(_tvf)
                                    break
                            except (ValueError, TypeError):
                                continue
                    else:
                        _stored_tax_pct = _safe_pct(tax_raw)
                _log(f"   [TAX] _stored_tax_pct={_stored_tax_pct:.6f}")

                for col_idx in range(_num_periods):
                    ps = _period_starts_ts[col_idx]
                    pe = _period_ends_ts[col_idx]
                    if ops_start and pe < ops_start:
                        continue
                    if sale_date and ps > sale_date:
                        continue
                    has_sched, sched_val = _has_schedule_value(tax_sched_raw, col_idx)
                    if has_sched:
                        income_tax[col_idx] = -abs(sched_val)
                    elif _stored_tax_pct != 0 and ebt[col_idx] > 0:
                        income_tax[col_idx] = -(ebt[col_idx] * _stored_tax_pct)
                _log(f"   [TAX] sum={income_tax.sum():,.0f}")
            except Exception as e:
                _log(f"   [WARN] Income tax error: {e}")
                import traceback; traceback.print_exc()

            # ----------------------------------------------------------------
            # Net Income = EBT ? Income Tax
            # ----------------------------------------------------------------
            net_income = ebt + income_tax

            # ================================================================
            # Summary log
            # ================================================================
            print(f"\n   [P&L] Rooms Revenue: {rooms_revenue.sum():,.0f}")
            _log(f"   [P&L] F&B Revenue: {fb_revenue.sum():,.0f}")
            _log(f"   [P&L] OOD Revenue: {ood_revenue.sum():,.0f}")
            _log(f"   [P&L] Parking Revenue: {parking_revenue.sum():,.0f}")
            _log(f"   [P&L] Total Revenue: {total_operating_revenue.sum():,.0f}")
            _log(f"   [P&L] EBITDA: {ebitda.sum():,.0f}")
            _log(f"   [P&L] EBITDA Less Reserve: {ebitda_less_reserve.sum():,.0f}")
            _log(f"   [P&L] D&A: {depreciation_amort.sum():,.0f}")
            _log(f"   [P&L] EBIT: {ebit.sum():,.0f}")
            _log(f"   [P&L] Interest Expense: {interest_expense.sum():,.0f}  (placeholder â€“ updated by CFF)")
            _log(f"   [P&L] EBT: {ebt.sum():,.0f}")
            _log(f"   [P&L] Income Tax: {income_tax.sum():,.0f}")
            _log(f"   [P&L] Net Income: {net_income.sum():,.0f}")
            _log(f"   [P&L] Tax % stored for CFF recomputation: {_stored_tax_pct:.4f}")

            # ---- Canonical result dict ----
            # Only canonical names â€” dynamic matching maps these to
            # whatever the Excel template row names actually are.
            result = {
                "Days":                              days_per_period,
                "Keys":                              keys_arr,
                "Room Nights Available":             room_nights_available,
                "Occupancy":                         occupancy_arr,
                "Room Nights Sold":                  room_nights_sold,
                "Guest Nights Sold":                 guest_nights_sold,
                "ADR":                               adr_arr,
                "RevPAR":                            revpar,
                "Room Revenue":                      rooms_revenue,
                "In Room-Dining":                    in_room_dining_rev,
                "Venue - F&B":                       venue_rev,
                "Other F&B Revenue":                 other_fb_rev,
                "Food & Beverage Revenue":           fb_revenue,
                "Golf Revenue":                      golf_rev,
                "Spa & Wellness - Revenue":          spa_rev,
                "Guest Laundry Revenue":             laundry_rev,
                "Banquet & Conference Revenue":       banquet_rev,
                "Other Operating Department Revenue": ood_dept_revenue,
                "Minor Operating Department":        minor_op_rev,
                "Cancellation Charges":              cancellation_rev,
                "Miscellaneous Income":              misc_income_rev,
                "Other Operating Revenue":           other_operating_revenue,
                "Parking Revenue":                   parking_revenue,
                "Total Operating Revenue":           total_operating_revenue,
                "Room Expense":                      room_expense,
                "F&B Expense":                       fb_expense,
                "Golf Expense":                      golf_exp_line,
                "Spa & Wellness Expense":            spa_exp_line,
                "Banquet & Conference Expense":      banq_exp_line,
                "Laundry Expense":                   laundry_exp_line,
                "Other Expense (H,L,P)":             laundry_exp_line,
                "Other Operating Department Expense": ood_expense,
                "Other Departmental Expenses":       other_dept_expense,
                "Other Operating Expenses":          other_operating_exp_line,
                "Parking Expense":                   parking_expense,
                "Total Departmental Expenses":       total_dept_expenses,
                "Departmental Income":               departmental_income,
                "Admin & General":                   admin_general,
                "Sales & Marketing":                 sales_marketing,
                "Franchise & Affiliation Advertising": sm_franchise_advertising,
                "Loyalty Programs":                  sm_loyalty_programs,
                "Other Expense (S&M)":               sm_other_expense,
                "Info & Telecom Systems":            info_telecom,
                "Utility Costs":                     utility_costs,
                "Electricity":                       ut_electricity,
                "Gas":                               ut_gas,
                "Water & Sewer":                     ut_water_sewer,
                "Other Expense (Utility)":           ut_other_expense,
                "Total Undistributed Expenses":      total_undistributed,
                "Gross Operating Profit":            gross_operating_profit,
                "GOP Margin":                        gop_margin,
                "Base Management Fee":               base_mgmt_fee,
                "Incentive Fee":                     incentive_fee,
                "Total Management Fees":             total_mgmt_fees,
                "Income Before Non-Operating I&E":   income_before_nonop,
                "Insurance":                         insurance,
                "Other Income 1":                    other_income_1,
                "Other Income 2":                    other_income_2,
                "Other Income 3":                    other_income_3,
                "Other Expense 1":                   other_expense_1,
                "Other Expense 2":                   other_expense_2,
                "Other Expense 3":                   other_expense_3,
                "Total Non-Operating I&E":           total_nonop_ie,
                "EBITDA":                            ebitda,
                "FF&E Reserve":                      ffe_reserve,
                "Capital Reserve":                   capital_reserve,
                "EBITDA Less Reserve":               ebitda_less_reserve,
                "EBITDA Margin":                     ebitda_margin,
                "Pre-Opening Expenses":              pre_opening_expenses,
                "Depreciation & Amortization":       depreciation_amort,
                "EBIT":                              ebit,
                "Interest Expense":                  interest_expense,
                "EBT":                               ebt,
                "Income Tax":                        income_tax,
                "Net Income":                        net_income,
                # Hidden metadata for CFF recomputation
                "_tax_pct":                          _stored_tax_pct,
                # ---- Aliases for Excel template row names that differ from our
                #      internal canonical names.  The two-pass matcher will use
                #      exact case-insensitive first, so these aliases ensure we
                #      hit the correct rows regardless of template wording. ----
                "Golf":                              golf_exp_line,
                "Laundry":                           laundry_exp_line,
                "Total Departmental Profit":         departmental_income,
                "Total Non Operating Income and Expenses": total_nonop_ie,
                "Interest":                          interest_expense,
                "Income Taxes Paid":                 income_tax,
                "Depreciation and Amortization":     depreciation_amort,
                "Room Revenue":                      rooms_revenue,
                "Food and Beverage Revenue":         fb_revenue,
                "Venue":                             venue_rev,
                "Venue - F&B":                       venue_rev,
                "Venue-F&B":                         venue_rev,
                "Venue F&B":                         venue_rev,
                "Venue F&B Revenue":                 venue_rev,
                "Venue - F&B Revenue":               venue_rev,
                "Venue-F&B Revenue":                 venue_rev,
                "F&B Venue":                         venue_rev,
                "F&B - Venue":                       venue_rev,
                "Room Expenses":                     room_expense,
                "Food and Beverage Expenses":        fb_expense,
                "Other Operating Departmental (OOD)  Revenue": ood_dept_revenue,
                "Other Operating Department (OOD) Expenses": ood_expense,
                "Other Departmental Expenses":       other_dept_expense,
                "Other Operating Expenses":          other_operating_exp_line,
                "Other Expenses":                    z.copy(),  # stop greedy matching of OE1/2/3
                "Undistributed Expense":             z.copy(),  # stop greedy matching of Total Undist
                "EBITDA Less Reserves":              ebitda_less_reserve,
                "EBITDA Margin %":                   ebitda_margin,
                "Income before Non Operating Income and Expenses": income_before_nonop,
                "Franchise and Affiliation Advertising": sm_franchise_advertising,
                "Info & Telecom System":             info_telecom,
                "Spa & Wellness - Revenue":          spa_rev,
                "Spa & Wellness Revenue":            spa_rev,
                "Spa & Wellness":                    spa_exp_line,
                "Banquet & Conference":              banq_exp_line,
            }
            # Flush the debug log to file
            try:
                with open(_log_path, "w", encoding="utf-8") as _lf:
                    _lf.write("\n".join(_log_lines))
                print(f"   [LOG] Debug log written to {_log_path}")
            except Exception as _le:
                print(f"   [LOG] Failed to write debug log: {_le}")
            return _cache_set(cache_key, result)

        def fn_compute_all_cashflows():
            """
            Compute all cashflows for Asset Co model.
            
            Returns: Dictionary with cashflow_from_operations, cashflow_from_investments, 
                    cashflow_from_financing DataFrames
            """
            global cashflow_from_operations, cashflow_from_investments, cashflow_from_financing, hospitality_pl, _function_timings
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
            # CASHFLOW FROM OPERATIONS  (Hospitality Mode)
            # ========================================================================
            # Legacy AssetCo lease rows (Base Rent, TOR, Service Charge, etc.) remain
            # at their initialized value of 0.0 â€” no lease functions are called.
            # Instead we compute the Hospitality P&L and feed EBITDA into the CFO.
            # ========================================================================

            # --- Compute Hospitality P&L (all failures ? zeros so model completes) ---
            try:
                pl_results = timed_call(fn_compute_hospitality_pl, "fn_compute_hospitality_pl")
            except Exception as e:
                import traceback as _tb_pl
                print(f"   [WARN] CRITICAL: P&L computation failed - returning zeros: {e}")
                print(f"   [WARN] TRACEBACK:\n{_tb_pl.format_exc()}")
                pl_results = {}

            # ================================================================
            # Dynamic P&L population â€” word-overlap matching
            # Reads template row names from o.hospitality.pl.names and
            # automatically maps computed values â€” NO hardcoded names.
            # ================================================================
            def _map_results_to_pl(pl_df, results, line_items=None):
                """
                Dynamically map computed arrays to P&L DataFrame rows.
                Uses word-overlap scoring so template naming variations are
                handled automatically â€” no hardcoded name matching needed.
                Header/blank rows (detected from line_items structure) are
                NEVER populated.

                Returns dict:  canonical_key  ?  actual_template_row_name
                """
                import re as _re

                # ---- Detect header/blank positions from the ACTUAL DataFrame values.
                # _init_pl_df sets headers/blanks to "" and data rows to 0.0,
                # so any row where ALL values are "" is a header/blank row.
                _header_positions = set()
                for i in range(len(pl_df)):
                    row_vals = pl_df.iloc[i].values
                    if all(v == "" or (isinstance(v, str) and v.strip() == "") for v in row_vals):
                        _header_positions.add(i)
                _header_labels = [pl_df.index[i] for i in sorted(_header_positions)
                                  if isinstance(pl_df.index[i], str) and pl_df.index[i].strip()]
                print(f"   [MAP] Header/blank rows skipped ({len(_header_positions)}): {_header_labels}")

                _STOP = {"and", "or", "the", "of", "in", "for", "from", "to",
                         "at", "per", "is", "by", "as", "annually", "monthly"}

                def _stem(w):
                    """Strip trailing 's' from words > 3 chars (simple plural)."""
                    if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
                        return w[:-1]
                    return w

                def _to_words(s):
                    """Extract meaningful stemmed words from a string."""
                    if not isinstance(s, str):
                        return set()
                    s = s.lower()
                    s = s.replace("f&b", "food beverage").replace("ff&e", "ffe")
                    # Expand parenthetical section qualifiers BEFORE
                    # stripping punctuation â€” (S&M), (H,L,P), (Utility) etc.
                    s = _re.sub(r'\(\s*s\s*[&,]\s*m\s*\)', ' salesmarketing ', s)
                    s = _re.sub(r'\(\s*h\s*,\s*l\s*,\s*p\s*\)', ' housekeepinglaundryparking ', s)
                    s = s.replace("&", " and ")
                    s = _re.sub(r'[^a-z0-9]', ' ', s)
                    return set(_stem(w) for w in s.split()
                               if len(w) > 1 and w not in _STOP)

                def _fuzzy_overlap(set_a, set_b):
                    """Count matching words including prefix matches (?4 chars)."""
                    count = 0
                    remaining_b = set(set_b)
                    for wa in set_a:
                        if wa in remaining_b:
                            count += 1
                            remaining_b.discard(wa)
                            continue
                        for wb in list(remaining_b):
                            plen = min(len(wa), len(wb))
                            if plen >= 4 and (wa.startswith(wb[:4]) or wb.startswith(wa[:4])):
                                count += 1
                                remaining_b.discard(wb)
                                break
                    return count

                # Pre-compute word sets for every result key
                result_word_map = {k: _to_words(k) for k in results
                                   if not k.startswith("_")}

                matched_count = 0
                unmatched_rows = []
                meta = {}            # canonical_key -> template_row_name
                used_keys = set()

                # Build list of data rows (pos, idx) excluding headers/blanks
                _data_rows = []
                for pos, idx in enumerate(pl_df.index):
                    if not isinstance(idx, str) or idx.strip() == "":
                        continue
                    if pos in _header_positions:
                        continue
                    _data_rows.append((pos, idx))

                # Diagnostic: dump all template data row names
                _all_data_names = [idx for _, idx in _data_rows]
                print(f"   [MAP] Template data rows ({len(_all_data_names)}): {_all_data_names}")
                # Show result dict keys that contain "venue" (case-insensitive)
                _venue_keys = [k for k in results if "venue" in k.lower() or "f&b" in k.lower()]
                print(f"   [MAP] Result keys with venue/f&b: {_venue_keys}")

                # ----- PASS 1: Exact case-insensitive matches for ALL rows -----
                _pass1_matched = set()   # set of pos values matched in pass 1
                for pos, idx in _data_rows:
                    idx_lower = idx.lower().strip()
                    exact_hit = None
                    for key in results:
                        if key not in used_keys and key.lower().strip() == idx_lower:
                            exact_hit = key
                            break
                    if exact_hit:
                        pl_df.iloc[pos, :] = results[exact_hit]
                        meta[exact_hit] = idx
                        used_keys.add(exact_hit)
                        matched_count += 1
                        _pass1_matched.add(pos)

                # ----- PASS 2: Fuzzy word-overlap for remaining rows -----
                for pos, idx in _data_rows:
                    if pos in _pass1_matched:
                        continue

                    idx_words = _to_words(idx)
                    if not idx_words:
                        continue

                    best_key = None
                    best_score = 0.0
                    best_overlap = 0
                    for key, kw in result_word_map.items():
                        if key in used_keys or not kw:
                            continue
                        overlap = _fuzzy_overlap(idx_words, kw)
                        total = max(len(idx_words), len(kw))
                        score = overlap / total if total else 0.0
                        if (overlap > best_overlap
                                or (overlap == best_overlap
                                    and score > best_score)):
                            best_overlap = overlap
                            best_score = score
                            best_key = key

                    if best_key:
                        min_req = 1 if len(result_word_map[best_key]) <= 1 else 2
                        if best_overlap >= min_req and best_score >= 0.4:
                            pl_df.iloc[pos, :] = results[best_key]
                            meta[best_key] = idx
                            used_keys.add(best_key)
                            matched_count += 1
                            continue

                    unmatched_rows.append(idx)

                total_rows = len([i for i in range(len(pl_df.index))
                                  if isinstance(pl_df.index[i], str)
                                  and pl_df.index[i].strip()
                                  and i not in _header_positions])
                print(f"   [OK] P&L: {matched_count}/{total_rows} data rows populated")
                if unmatched_rows:
                    print(f"   [INFO]  Unmatched data rows: {unmatched_rows[:25]}")
                unused = [k for k in results if k not in used_keys]
                if unused:
                    print(f"   [INFO]  Unused result keys: {unused}")
                return meta

            _pl_meta = _map_results_to_pl(hospitality_pl, pl_results, pl_line_items)

            # Diagnostic: check Venue row in P&L DataFrame after mapping
            for _vrow in hospitality_pl.index:
                if isinstance(_vrow, str) and "venue" in _vrow.lower():
                    _vvals = hospitality_pl.loc[_vrow].values
                    _vsum = sum(float(x) for x in _vvals if isinstance(x, (int, float, np.floating, np.integer)))
                    print(f"   [DIAG-VENUE] After MAP: row={_vrow!r}, sum={_vsum:,.0f}, first5={list(_vvals[:5])}")

            # --- Populate Hospitality-specific CFO rows ---
            _hosp_ebitda_less_reserves = pl_results.get("EBITDA Less Reserve", np.zeros(_num_periods))
            # Try the template row name first; fall back to legacy name
            if not fn_safe_set_row(cashflow_from_operations, "EBITDA Less Reserves_Hospitality", _hosp_ebitda_less_reserves):
                fn_safe_set_row(cashflow_from_operations, "EBITDA_Hospitality", _hosp_ebitda_less_reserves)
            print(f"   [Hospitality CFO] EBITDA Less Reserves sum: {_hosp_ebitda_less_reserves.sum():,.2f}")

            # Change in Working Capital: WC = % of revenue, change = WC[t] - WC[t-1]
            try:
                _total_revenue = pl_results.get("Total Operating Revenue", np.zeros(_num_periods))
                _hosp_wc = fn_compute_working_capital(_total_revenue)
            except Exception as e:
                print(f"   [WARN] Working capital fallback to zeros: {e}")
                _hosp_wc = np.zeros(_num_periods)
            fn_safe_set_row(cashflow_from_operations, "Change in Working Capital_Hospitality", _hosp_wc)

            # Net Cashflow from Operations (Hospitality) = EBITDA Less Reserves ? Change in WC
            _hosp_net_cf_ops = _hosp_ebitda_less_reserves - _hosp_wc
            fn_safe_set_row(cashflow_from_operations, "Net Cashflow from Operations_Hospitality", _hosp_net_cf_ops)

            # Total Net Cashflow from Operations = Hospitality net CF
            # (Legacy AssetCo rows are zero; hospitality is the sole contributor)
            net_cf_operations = pd.Series(_hosp_net_cf_ops, index=range(_num_periods))
            fn_safe_set_row(cashflow_from_operations, "Total Net Cashflow from Operations", net_cf_operations.values)

            # NOI proxy for downstream DSCR calculations in loan schedules.
            # In hospitality mode, NOI ? EBITDA Less Reserves.
            noi = pd.Series(_hosp_ebitda_less_reserves, index=range(_num_periods))

            print(f"\n   [Hospitality CFO] EBITDA Less Reserves sum: {_hosp_ebitda_less_reserves.sum():,.2f}")
            print(f"   [Hospitality CFO] Working Capital sum: {_hosp_wc.sum():,.2f}")
            print(f"   [Hospitality CFO] Net CF from Ops sum: {_hosp_net_cf_ops.sum():,.2f}")

            # ========================================================================
            # CASHFLOW FROM INVESTMENTS
            # ========================================================================
            
            # Acquisition Costs
            # print("\n" + "="*60)
            # print("? COMPUTING ACQUISITION COSTS FOR CFS")
            # print("="*60)
            acq_costs = timed_call(fn_get_acquisition_costs, "fn_get_acquisition_costs")
            
            # print(f"\n   ? acq_costs returned:")
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
            _disp_pct_raw = Global.ValuationParameters.disposal_cost_assumption
            print(f"   Asset Sale Value (total): {_sale_total:,.2f}  |  disposal_cost_assumption raw from Global: {_disp_pct_raw}")
            fn_safe_set_row(cashflow_from_investments, "Asset Sale Value", asset_sale.values)
            
            # Net Cashflow from Investments
            net_cf_investments = -total_acq_cost - total_capex + asset_sale
            fn_safe_set_row(cashflow_from_investments, "Net Cashflow from Investments", net_cf_investments.values)
            
            # ========================================================================
            # CASHFLOW FROM FINANCING â€“ Full Debt + Equity Engine
            # ========================================================================

            # Load interest rate profiles once
            interest_rate_profiles = fn_get_interest_rate_profiles()
            _profile_keys = list(interest_rate_profiles.keys()) if interest_rate_profiles else []
            print(f"\n   Interest Rate Profiles Loaded: {_profile_keys}")

            # ---- Helpers ----
            # _safe_float and _safe_pct are defined above in the helper section.

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
            acquisition_date = _to_date(Global.ModelInputs.asset_acquisition_dateanalysis_date)

            ltv_pct = _safe_pct(Global.FinancingModule.capital_structure_total_debt_ltv, 0.0)

            # Loan 1 inputs  (directly from Global.FinancingModule)
            loan1_start = _to_date(Global.FinancingModule.financing_assumptions_loan_1_loan_raise_date) if Global.FinancingModule.financing_assumptions_loan_1_loan_raise_date else acquisition_date
            loan1_term_years = _safe_float(Global.FinancingModule.financing_assumptions_loan_1_loan_term, 0)
            loan1_term_months = int(loan1_term_years * 12) if loan1_term_years < 100 else int(loan1_term_years)
            loan1_end = _to_date(Global.FinancingModule.financing_assumptions_loan_1_loan_end) if Global.FinancingModule.financing_assumptions_loan_1_loan_end else None
            if loan1_end is None and loan1_start and loan1_term_months > 0:
                loan1_end = loan1_start + relativedelta(months=loan1_term_months)
            # Amortization: annual_amortization % of loan amortized per year over amortization_duration years
            loan1_amort_duration_years = _safe_float(Global.FinancingModule.financing_assumptions_loan_1_amortization_duration, 0)
            loan1_annual_amort_pct = _safe_pct(Global.FinancingModule.financing_assumptions_loan_1_annual_amortization, 0.0)
            loan1_balloon_pct = _safe_pct(Global.FinancingModule.financing_assumptions_loan_1_balloon_payment, 0.0)
            loan1_interest_profile = Global.FinancingModule.financing_assumptions_loan_1_base_interest_rate
            loan1_arr_fee_pct = _safe_float(Global.FinancingModule.financing_assumptions_loan_1_arrangement_fees, 0.0)
            if loan1_arr_fee_pct > 1:
                loan1_arr_fee_pct = loan1_arr_fee_pct / 100.0
            loan1_refinancing = str(Global.FinancingModule.financing_assumptions_loan_1_loan_refinancing_ or "").lower().strip() in ["yes", "true", "1"]
            loan1_refinancing_date = _to_date(Global.FinancingModule.financing_assumptions_loan_1_loan_refinancing_date) if Global.FinancingModule.financing_assumptions_loan_1_loan_refinancing_date else None

            # Refinancing (Loan 2) inputs  (directly from Global.FinancingModule)
            refi_ltv = _safe_pct(Global.FinancingModule.refinancing_assumptions_ltv, 0.0)
            refi_cap_rate = _safe_float(Global.FinancingModule.refinancing_assumptions_cap_rate_at_refinanced, 0.0)
            if refi_cap_rate > 1:
                refi_cap_rate = refi_cap_rate / 100.0
            refi_min_dscr = _safe_float(Global.FinancingModule.refinancing_assumptions_min_dscr, 0.0)
            if isinstance(Global.FinancingModule.refinancing_assumptions_min_dscr, str) and Global.FinancingModule.refinancing_assumptions_min_dscr.strip().lower().endswith('x'):
                try:
                    refi_min_dscr = float(Global.FinancingModule.refinancing_assumptions_min_dscr.strip().rstrip('xX'))
                except (ValueError, TypeError):
                    pass
            refi_repayment_type = str(Global.FinancingModule.refinancing_assumptions_repayment_type or "Amortizing").strip()
            refi_start = _to_date(Global.FinancingModule.refinancing_assumptions_loan_start) if Global.FinancingModule.refinancing_assumptions_loan_start else loan1_refinancing_date
            refi_term_years = _safe_float(Global.FinancingModule.refinancing_assumptions_loan_term, 0)
            refi_term_months = int(refi_term_years * 12) if refi_term_years < 100 else int(refi_term_years)
            refi_end = _to_date(Global.FinancingModule.refinancing_assumptions_loan_end) if Global.FinancingModule.refinancing_assumptions_loan_end else None
            if refi_end is None and refi_start and refi_term_months > 0:
                refi_end = refi_start + relativedelta(months=refi_term_months)
            if refi_end and asset_sale_date and refi_end > asset_sale_date:
                refi_end = asset_sale_date
            refi_amort_duration_years = _safe_float(Global.FinancingModule.refinancing_assumptions_amortization_duration, 0)
            refi_annual_amort_pct = _safe_pct(Global.FinancingModule.refinancing_assumptions_amortization_percentage, 0.0)
            refi_balloon_pct = _safe_pct(Global.FinancingModule.refinancing_assumptions_balloon_payment, 0.0)
            refi_interest_profile = Global.FinancingModule.refinancing_assumptions_refinanced_interest_rate
            refi_arr_fee_pct = _safe_float(Global.FinancingModule.refinancing_assumptions_arrangement_fees, 0.0)
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

            # ---- Loan 1 Amount = LTV Ã— Acquisition Price (excludes transaction costs) ----
            loan1_amount = ltv_pct * acq_price_scalar

            # ---- Loan 1 arrangement fee (cash outflow, never capitalized) ----
            loan1_arrangement_fee = loan1_arr_fee_pct * loan1_amount

            print(f"\n   CFF: Loan1={loan1_amount:,.0f} @ {loan1_interest_profile}, Refi={'Yes' if loan1_refinancing else 'No'}")
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
            ):
                """Build drawn/repaid/interest/fees/balance/dscr arrays for a loan.

                Parameters
                ----------
                loan_amount : float
                annual_amort_pct : float  (e.g. 0.10 for 10%)
                interest_profile : str    Name of the interest?rate profile
                loan_start_date : Timestamp   Used for rate lookup
                start_idx : int|None      Period index when loan is drawn
                effective_end_idx : int|None  Period when outstanding balance is repaid
                                              (refinancing/sale). None ? keep amortizing.
                arrangement_fee : float   Cash outflow at draw (no capitalisation)
                repayment_type : str      "amortizing" | "interest only"

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

                    # Interest for this period
                    period_date = _period_starts_ts[col_idx]
                    annual_rate = fn_get_interest_rate_for_period(
                        interest_profile, period_date,
                        loan_start_date, interest_rate_profiles,
                    )
                    int_amt = opening * (annual_rate / 12.0)

                    # Past effective end ? already repaid
                    if effective_end_idx is not None and col_idx > effective_end_idx:
                        balance[col_idx] = 0.0
                        continue

                    interest[col_idx] = int_amt
                    _noi_this = noi.iloc[col_idx] if col_idx < len(noi) else 0

                    if effective_end_idx is not None and col_idx == effective_end_idx:
                        # Refinancing / asset sale â€” repay outstanding balance
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
                # ---- NOI at refinance: sum last 12 months of NOI ending at refinancing date (inclusive) ----
                refi_noi_12m = 0.0
                months_counted = 0
                for cidx in range(loan1_refinance_idx, -1, -1):
                    if months_counted >= 12:
                        break
                    refi_noi_12m += noi.iloc[cidx] if cidx < len(noi) else 0
                    months_counted += 1

                valuation_at_refi = refi_noi_12m / refi_cap_rate if refi_cap_rate > 0 else 0.0
                ltv_max_loan = refi_ltv * valuation_at_refi
                refi_loan_amount = ltv_max_loan

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
                        ar = fn_get_interest_rate_for_period(
                            refi_interest_profile, pd_date,
                            refi_start if refi_start else _period_starts_ts[refi_start_idx],
                            interest_rate_profiles
                        )
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
                    print(f"   DSCR ({refi_dscr_computed:.4f}) below min ({refi_min_dscr:.4f}) â€” monitoring only")

                Global.FinancingModule.refinancing_assumptions_ebitda_less_reserves_at_refinanced_date = refi_noi_12m
                Global.FinancingModule.refinancing_assumptions_valuation_at_refinanced = valuation_at_refi
                Global.FinancingModule.refinancing_assumptions_ltv_max_loan = ltv_max_loan
                Global.FinancingModule.refinancing_assumptions_dscr_computed = refi_dscr_computed

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
            # BACK-PROPAGATE Interest into P&L results
            # Now that both loan schedules are computed, feed total interest
            # back into the P&L and recompute EBT ? Tax ? Net Income.
            # ================================================================
            try:
                _total_interest_for_pl = -(loan1_interest_series + refi_interest_series)
                pl_results["Interest Expense"] = _total_interest_for_pl

                _ebit_arr = pl_results.get("EBIT", np.zeros(_num_periods))
                _ebt_arr = _ebit_arr + _total_interest_for_pl
                pl_results["EBT"] = _ebt_arr

                # Recompute Income Tax (% of EBT, only when EBT > 0)
                # Preserve schedule overrides â€” only recompute percentage-based periods
                _tax_pct = pl_results.get("_tax_pct", 0.0)
                _tax_sched_raw = _read_schedule("s.hospitality.income.tax")
                _new_tax = np.zeros(_num_periods)
                for _ti in range(_num_periods):
                    _has_ts, _ts_val = _has_schedule_value(_tax_sched_raw, _ti)
                    if _has_ts:
                        _new_tax[_ti] = -abs(_ts_val)  # preserve schedule override (negative)
                    elif isinstance(_tax_pct, (int, float)) and _tax_pct != 0 and _ebt_arr[_ti] > 0:
                        _new_tax[_ti] = -(_ebt_arr[_ti] * _tax_pct)
                pl_results["Income Tax"] = _new_tax

                pl_results["Net Income"] = _ebt_arr + _new_tax

                # Update the hospitality_pl DataFrame for the changed rows
                # Try both canonical and alias key names for template lookup
                _rows_to_update = {
                    "Interest Expense": ["Interest Expense", "Interest"],
                    "EBT": ["EBT"],
                    "Income Tax": ["Income Tax", "Income Taxes Paid"],
                    "Net Income": ["Net Income"],
                }
                for _rk, _aliases in _rows_to_update.items():
                    _tpl_name = None
                    for _ak in _aliases:
                        _tpl_name = _pl_meta.get(_ak)
                        if _tpl_name:
                            break
                    if _tpl_name and _tpl_name in hospitality_pl.index:
                        hospitality_pl.loc[_tpl_name, :] = pl_results[_rk]

                print(f"\n   [CFF?P&L] Interest back-propagated: {_total_interest_for_pl.sum():,.0f}")
                print(f"   [CFF?P&L] Updated EBT: {_ebt_arr.sum():,.0f}")
                print(f"   [CFF?P&L] Updated Net Income: {pl_results['Net Income'].sum():,.0f}")
            except Exception as e:
                print(f"   [WARN] Interest back-propagation failed: {e}")

            # ================================================================
            # POPULATE CFF ROWS â€” positional (iloc) assignment
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

            # ---- Fully dynamic CFF row detection ----
            # Find "Principal Drawn" rows as anchors; offsets give the rest.
            _drawn_indices = []
            _EQUITY = None
            _NET_CFF = None
            for _ri, _rn in enumerate(_cff_row_names):
                if not isinstance(_rn, str):
                    continue
                _rn_l = _rn.strip().lower()
                if _rn_l == "principal drawn":
                    _drawn_indices.append(_ri)
                elif "equity" in _rn_l and "injection" in _rn_l:
                    _EQUITY = _ri
                elif "net" in _rn_l and "cashflow" in _rn_l and "financing" in _rn_l:
                    _NET_CFF = _ri

            _L1_HDR = _L1_DRAWN = _L1_REPAID = _L1_INTEREST = _L1_FEES = None
            _L2_HDR = _L2_DRAWN = _L2_REPAID = _L2_INTEREST = _L2_FEES = None

            if len(_drawn_indices) >= 1:
                _L1_DRAWN    = _drawn_indices[0]
                _L1_HDR      = _L1_DRAWN - 1 if _L1_DRAWN > 0 else None
                _L1_REPAID   = _L1_DRAWN + 1
                _L1_INTEREST = _L1_DRAWN + 2
                _L1_FEES     = _L1_DRAWN + 3
            if len(_drawn_indices) >= 2:
                _L2_DRAWN    = _drawn_indices[1]
                _L2_HDR      = _L2_DRAWN - 1 if _L2_DRAWN > 0 else None
                _L2_REPAID   = _L2_DRAWN + 1
                _L2_INTEREST = _L2_DRAWN + 2
                _L2_FEES     = _L2_DRAWN + 3

            print(f"   CFF dynamic layout: L1_HDR={_L1_HDR}, L1_DRAWN={_L1_DRAWN}, "
                  f"L2_HDR={_L2_HDR}, L2_DRAWN={_L2_DRAWN}, "
                  f"EQUITY={_EQUITY}, NET_CFF={_NET_CFF}")

            if _L1_DRAWN is not None:
                cashflow_from_financing.iloc[_L1_DRAWN, :]    = term_loan_drawn.values
                cashflow_from_financing.iloc[_L1_REPAID, :]   = (term_loan_repaid * -1).values
                cashflow_from_financing.iloc[_L1_INTEREST, :] = (term_loan_interest * -1).values
                cashflow_from_financing.iloc[_L1_FEES, :]     = (term_loan_fees * -1).values

            if _L2_DRAWN is not None:
                cashflow_from_financing.iloc[_L2_DRAWN, :]    = refi_drawn.values
                cashflow_from_financing.iloc[_L2_REPAID, :]   = (refi_repaid * -1).values
                cashflow_from_financing.iloc[_L2_INTEREST, :] = (refi_interest * -1).values
                cashflow_from_financing.iloc[_L2_FEES, :]     = (refi_fees * -1).values

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
            # Loan 1 â€” show DSCR during amortizing periods (exclude grace and balloon)
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
            # Loan 2 â€” show DSCR/ICR (exclude balloon)
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
                "hospitality_pl": hospitality_pl,
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
            #     print("\n? Running Module 02 to load inputs...")
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
        try:
            cashflow_results = fn_run_module_10()
        except Exception as e:
            print(f"[WARN] fn_run_module_10 CRASHED: {e}\n{traceback.format_exc()}")
            cashflow_results = None
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

        # Extract results from fn_run_module_10() â€” these are the computed DataFrames
        # Do NOT re-create empty DataFrames here (that was overwriting computed results)
        if cashflow_results is not None:
            cashflow_from_operations = cashflow_results.get("cashflow_from_operations")
            cashflow_from_investments = cashflow_results.get("cashflow_from_investments")
            cashflow_from_financing = cashflow_results.get("cashflow_from_financing")
            hospitality_pl = cashflow_results.get("hospitality_pl")
        else:
            print("[WARN] WARNING: cashflow_results is None â€” fn_run_module_10() likely crashed!")
            # Create empty fallback DataFrames
            cashflow_from_operations = pd.DataFrame(columns=columns)
            cashflow_from_investments = pd.DataFrame(columns=columns)
            cashflow_from_financing = pd.DataFrame(columns=columns)
            hospitality_pl = pd.DataFrame(columns=columns)

        cashflow_from_operations = cashflow_from_operations.fillna(0)
        cashflow_from_investments = cashflow_from_investments.fillna(0)
        cashflow_from_financing = cashflow_from_financing.fillna(0)
        if hospitality_pl is not None:
            hospitality_pl = hospitality_pl.fillna(0)

        # ---- Verification: confirm data actually reached the DataFrames ----
        # NOTE: DataFrames may be object dtype (mixed strings + floats), so
        # select_dtypes(include='number') can return empty. Convert to numeric first.
        def _df_numeric_sum(df):
            if df is None or df.empty:
                return 0.0
            total = 0.0
            for col in df.columns:
                for v in df[col]:
                    try:
                        total += float(v)
                    except (ValueError, TypeError):
                        pass
            return total
        _cfo_sum = _df_numeric_sum(cashflow_from_operations)
        _cfi_sum = _df_numeric_sum(cashflow_from_investments)
        _cff_sum = _df_numeric_sum(cashflow_from_financing)
        _pl_sum = _df_numeric_sum(hospitality_pl)
        print(f"\n   OUTPUT VERIFICATION: CFO total={_cfo_sum:,.0f}, CFI total={_cfi_sum:,.0f}, CFF total={_cff_sum:,.0f}, P&L total={_pl_sum:,.0f}")
        if _cff_sum == 0:
            print(f"   [WARN] CFF is ALL ZEROS â€” data did not reach the DataFrame!")
        else:
            print(f"   [OK] CFF has non-zero values â€” financing data is in the output")

        # Convert to object dtype so we can mix numbers and empty strings for blank/header rows
        cashflow_from_operations = cashflow_from_operations.astype(object)
        cashflow_from_investments = cashflow_from_investments.astype(object)
        cashflow_from_financing = cashflow_from_financing.astype(object)
        if hospitality_pl is not None:
            hospitality_pl = hospitality_pl.astype(object)

        # Clear blank rows and section header rows â€” they should show empty in Excel
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
                              "net lease",
                              # P&L subtotals / data rows that come after blanks
                              "food & beverage", "food and beverage", "f&b revenue",
                              "other operating department", "other operating revenue",
                              "room revenue", "rooms revenue",
                              "departmental income", "gross operating profit",
                              "gop margin", "income before", "ebitda", "ebit",
                              "ebt", "net income", "interest expense",
                              "depreciation", "pre-opening",
                              "ff&e", "capital reserve", "ebitda less",
                              "total departmental", "total undistributed",
                              "total management", "total non-operating",
                              "income tax",
                              # F&B sub-line items (must not be cleared)
                              "venue", "in room", "in-room", "other f&b",
                              # OOD sub-line items (must not be cleared)
                              "golf", "spa", "wellness", "laundry", "banquet",
                              "conference", "parking",
                              # Other Operating Revenue sub-items
                              "minor operating", "cancellation", "miscellaneous",
                              # Undistributed sub-items
                              "admin", "sales & marketing", "sales and marketing",
                              "franchise", "loyalty", "info & telecom", "info and telecom",
                              "utility", "electricity", "water", "sewer",
                              # Management Fees sub-items
                              "base management", "incentive fee",
                              # Non-Operating sub-items
                              "insurance", "other income", "other expense",
                              # Operating Metrics
                              "days", "keys", "room nights", "guest nights",
                              "occupancy", "adr", "revpar",
                              ]
            def _is_data_row(name):
                name_lower = name.lower()
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
            return positions

        for df, items in [
            (cashflow_from_operations, operations_line_items),
            (cashflow_from_investments, investment_line_items),
            (cashflow_from_financing, financing_line_items),
        ]:
            if items:
                clear_pos = _detect_clear_positions(items)
                for pos in clear_pos:
                    if pos < len(df):
                        df.iloc[pos] = ""

        # Clear headers/blanks in P&L too
        if hospitality_pl is not None and pl_line_items:
            _pl_clear = _detect_clear_positions(pl_line_items)
            # Diagnostic: show which P&L positions will be cleared
            _clear_names = [pl_line_items[p] for p in sorted(_pl_clear) if p < len(pl_line_items) and pl_line_items[p]]
            print(f"   [CLEAR-PL] Clearing {len(_pl_clear)} positions: {_clear_names}")
            for pos in _pl_clear:
                if pos < len(hospitality_pl):
                    hospitality_pl.iloc[pos] = ""

            # Diagnostic: check Venue row AFTER clearing
            for _vrow in hospitality_pl.index:
                if isinstance(_vrow, str) and "venue" in _vrow.lower():
                    _vvals = hospitality_pl.loc[_vrow].values
                    _vsum = sum(float(x) for x in _vvals if isinstance(x, (int, float, np.floating, np.integer)))
                    print(f"   [DIAG-VENUE] After CLEAR: row={_vrow!r}, sum={_vsum:,.0f}, first5={list(_vvals[:5])}")

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
            # Replace NaN/Inf with safe values so JSON serialization succeeds
            df_clean = df.copy()
            # Replace numeric NaN/Inf with 0, string NaN with ""
            for col in df_clean.columns:
                df_clean[col] = df_clean[col].apply(
                    lambda x: 0 if (isinstance(x, (float, np.floating)) and (pd.isna(x) or np.isinf(x)))
                    else ("" if x is None or (isinstance(x, float) and pd.isna(x)) else x)
                )
            data = df_clean.values.tolist()
            # Final safety: convert any remaining numpy types to native Python
            clean_data = []
            for row in data:
                clean_row = []
                for v in row:
                    if isinstance(v, (np.integer,)):
                        clean_row.append(int(v))
                    elif isinstance(v, (np.floating,)):
                        if np.isnan(v) or np.isinf(v):
                            clean_row.append(0)
                        else:
                            clean_row.append(float(v))
                    elif isinstance(v, np.ndarray):
                        clean_row.append(v.tolist())
                    else:
                        clean_row.append(v)
                clean_data.append(clean_row)
            return {
                "index": [str(i) if not isinstance(i, str) else i for i in df_clean.index.tolist()],
                "columns": [int(c) if isinstance(c, (np.integer,)) else c for c in df_clean.columns.tolist()],
                "data": clean_data,
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
            if hospitality_pl is not None:
                hospitality_pl.columns = year_mapping

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

            # Add Hospitality P&L if available
            if hospitality_pl is not None:
                monthly_dfs["Hospitality P&L"] = ("o.hospitality.pl.me", hospitality_pl)

            # Calculate annual sums for each DataFrame
            # Header/blank rows (containing "") must stay "" after grouping
            # Columns are integer period indices (0..N-1); map to calendar years
            # using model_timeline_me["Year"] so monthly values aggregate correctly.
            _col_to_year = {i: int(model_timeline_me.iloc[i]["Year"]) for i in range(len(model_timeline_me))}
            _unique_years = sorted(set(_col_to_year.values()))

            # ================================================================
            # Annual aggregation â€” fully dynamic, keyword-based detection
            # No hardcoded row names. Detects rate/ratio rows by keywords
            # and finds helper rows (RNS, RNA, Room Revenue) dynamically.
            # ================================================================
            import re as _re_annual

            _ANN_STOP = {"and", "or", "the", "of", "in", "for", "from", "to",
                         "at", "per", "is", "by", "as", "annually", "monthly"}

            def _ann_stem(w):
                if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
                    return w[:-1]
                return w

            def _ann_words(s):
                """Extract stemmed keyword set from a row name."""
                if not isinstance(s, str):
                    return set()
                s = s.lower()
                s = s.replace("f&b", "food beverage").replace("ff&e", "ffe")
                s = s.replace("&", " and ")
                s = _re_annual.sub(r'[^a-z0-9]', ' ', s)
                return set(_ann_stem(w) for w in s.split()
                           if len(w) > 1 and w not in _ANN_STOP)

            def _is_rate_row(idx_name):
                """True for rows that need weighted-avg / constant annual logic."""
                w = _ann_words(idx_name)
                return bool(w & {"adr", "occupancy", "revpar", "key", "margin", "day"})

            def _find_helper_row(df, required, excluded=None):
                """Find the first row in *df* whose keywords match *required*."""
                excluded = excluded or set()
                for idx in df.index:
                    w = _ann_words(idx) if isinstance(idx, str) else set()
                    if required.issubset(w) and not w & excluded:
                        return df.loc[idx]
                return None

            def _annual_sum(df):
                """Group monthly cols ? calendar years.
                Rate/ratio rows use weighted averages detected by keyword,
                helper rows (RNS, RNA, Room Rev) found dynamically.
                All other rows are summed."""
                result_rows = []
                result_index = []

                # Dynamic helper-row detection (keyword-based)
                # NOTE: _find_helper_row returns a pandas Series when matched,
                # so we CANNOT use `or` (raises ValueError). Use explicit None check.
                _rns_row = _find_helper_row(df, {"room", "night", "sold"})
                if _rns_row is None:
                    _rns_row = _find_helper_row(df, {"room", "night", "occupied"})
                _rna_row = _find_helper_row(df, {"room", "night", "available"})
                _rev_row = _find_helper_row(df, {"room", "revenue"},
                                            {"food", "beverage", "total", "operating"})

                for i in range(len(df)):
                    row = df.iloc[i]
                    idx_name = df.index[i]
                    is_header = all(v == "" for v in row.values)

                    if is_header:
                        result_rows.append([""] * len(_unique_years))

                    elif _is_rate_row(idx_name):
                        words = _ann_words(idx_name)
                        year_vals = {y: 0.0 for y in _unique_years}

                        if "key" in words:
                            # Keys: constant â€” first non-zero per year
                            for col_pos, val in enumerate(row.values):
                                yr = _col_to_year.get(col_pos)
                                if yr is not None and year_vals[yr] == 0.0:
                                    try:
                                        year_vals[yr] = float(val)
                                    except (ValueError, TypeError):
                                        pass

                        elif "adr" in words:
                            # Weighted avg: sum(ADR_m Ã— RNS_m) / sum(RNS_m)

                            y_num = {y: 0.0 for y in _unique_years}
                            y_den = {y: 0.0 for y in _unique_years}
                            for col_pos, val in enumerate(row.values):
                                yr = _col_to_year.get(col_pos)
                                if yr is None:
                                    continue
                                try:
                                    adr_v = float(val)
                                except (ValueError, TypeError):
                                    continue
                                rns = 0.0
                                if _rns_row is not None:
                                    try:
                                        rns = float(_rns_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                y_num[yr] += adr_v * rns
                                y_den[yr] += rns
                            for yr in _unique_years:
                                year_vals[yr] = (y_num[yr] / y_den[yr]) if y_den[yr] else 0.0

                        elif "occupancy" in words:
                            # Occupancy = sum(RNS) / sum(RNA)
                            y_rns = {y: 0.0 for y in _unique_years}
                            y_rna = {y: 0.0 for y in _unique_years}
                            for col_pos in range(len(row.values)):
                                yr = _col_to_year.get(col_pos)
                                if yr is None:
                                    continue
                                if _rns_row is not None:
                                    try:
                                        y_rns[yr] += float(_rns_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                if _rna_row is not None:
                                    try:
                                        y_rna[yr] += float(_rna_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                            for yr in _unique_years:
                                year_vals[yr] = (y_rns[yr] / y_rna[yr]) if y_rna[yr] else 0.0

                        elif "revpar" in words:
                            # RevPAR = sum(Room Revenue) / sum(RNA)
                            y_rev = {y: 0.0 for y in _unique_years}
                            y_rna = {y: 0.0 for y in _unique_years}
                            for col_pos in range(len(row.values)):
                                yr = _col_to_year.get(col_pos)
                                if yr is None:
                                    continue
                                if _rev_row is not None:
                                    try:
                                        y_rev[yr] += float(_rev_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                if _rna_row is not None:
                                    try:
                                        y_rna[yr] += float(_rna_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                            for yr in _unique_years:
                                year_vals[yr] = (y_rev[yr] / y_rna[yr]) if y_rna[yr] else 0.0

                        elif "margin" in words:
                            # Margin rows: recompute as numerator / Total Operating Revenue
                            # Detect which profit metric is the numerator by keywords
                            _tor_row = _find_helper_row(df, {"total", "operating", "revenue"})
                            _profit_row = None
                            if "ebitda" in words:
                                # EBITDA Margin → numerator = EBITDA
                                _profit_row = _find_helper_row(df, {"ebitda"},
                                                               {"less", "reserve", "margin"})
                            elif "gop" in words or "gross" in words:
                                # GOP Margin → numerator = Gross Operating Profit
                                _profit_row = _find_helper_row(df, {"gross", "operating", "profit"},
                                                               {"margin"})
                            if _profit_row is None:
                                # Fallback: scan backwards from this row for the first non-header data row
                                for _back in range(i - 1, -1, -1):
                                    _candidate = df.iloc[_back]
                                    if not all(v == "" for v in _candidate.values):
                                        _profit_row = _candidate
                                        break
                            # Sum numerator and denominator by year, then divide
                            y_num_m = {y: 0.0 for y in _unique_years}
                            y_den_m = {y: 0.0 for y in _unique_years}
                            for col_pos in range(len(row.values)):
                                yr = _col_to_year.get(col_pos)
                                if yr is None:
                                    continue
                                if _profit_row is not None:
                                    try:
                                        y_num_m[yr] += float(_profit_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                if _tor_row is not None:
                                    try:
                                        y_den_m[yr] += float(_tor_row.iloc[col_pos])
                                    except (ValueError, TypeError, IndexError):
                                        pass
                            for yr in _unique_years:
                                year_vals[yr] = (y_num_m[yr] / y_den_m[yr]) if y_den_m[yr] else 0.0

                        elif "day" in words:
                            # Days: sum days per year
                            for col_pos, val in enumerate(row.values):
                                yr = _col_to_year.get(col_pos)
                                if yr is not None:
                                    try:
                                        year_vals[yr] += float(val)
                                    except (ValueError, TypeError):
                                        pass

                        result_rows.append([year_vals[y] for y in _unique_years])

                    else:
                        # Sum values by year
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
            }

            # Add Hospitality P&L annual if available
            if hospitality_pl is not None:
                annual_dfs["Hospitality P&L"] = (
                    "o.hospitality.pl.ye",
                    _annual_sum(hospitality_pl),
                )
            # ================================================================
            # DEBUG: Print all output line items + first-period values
            # ================================================================
            def _print_output_df(label, df):
                print(f"\n   --- {label} ({len(df)} rows x {len(df.columns)} cols) ---")
                for i, idx_name in enumerate(df.index):
                    row_vals = df.iloc[i].values
                    # Show first non-empty value as sample
                    sample = ""
                    for v in row_vals:
                        if v != "" and v != 0 and v != 0.0:
                            try:
                                sample = f"{float(v):,.2f}"
                            except (ValueError, TypeError):
                                sample = str(v)
                            break
                    if idx_name == "":
                        print(f"     [{i:2d}] (blank row)")
                    elif all(v == "" for v in row_vals):
                        print(f"     [{i:2d}] {idx_name}  [HEADER]")
                    else:
                        row_sum = 0
                        try:
                            row_sum = sum(float(v) for v in row_vals if v != "" and v is not None)
                        except (ValueError, TypeError):
                            pass
                        print(f"     [{i:2d}] {idx_name}  sum={row_sum:,.2f}  sample={sample}")

            print("\n" + "=" * 80)
            print("DEBUG: FINAL OUTPUT DATAFRAMES BEING SENT TO EXCEL")
            print("=" * 80)
            _print_output_df("CFO (monthly)", cashflow_from_operations)
            _print_output_df("CFI (monthly)", cashflow_from_investments)
            _print_output_df("CFF (monthly)", cashflow_from_financing)
            if hospitality_pl is not None:
                _print_output_df("P&L (monthly)", hospitality_pl)
            print("=" * 80 + "\n")

            def _df_to_records(df, section_name, period_type, period_starts=None):
                """
                Convert a DataFrame to a relational list of records with hierarchy:
                  - "Cashflow Section"  : statement name (e.g. "Cashflow from Operations")
                  - "Main Category"     : last seen header row (all-empty values, non-empty index)
                  - "Line Item"         : actual data row index name
                  - "Value Type"        : Monthly / Annual
                  - "Period Start"      : period start date
                  - "Year"              : period column label
                  - "Value"             : value for that period

                Blank separator rows (index == "") are skipped.
                Header rows (all values == "") update Main Category and are not emitted.
                """
                d = df.copy()
                d = d.replace([np.inf, -np.inf], 0)
                d = d.where(pd.notna(d), "")
                period_starts = list(period_starts) if period_starts is not None else []

                def _normalize_hosp_label(label):
                    text = "" if label is None else str(label)
                    text = text.strip().lower()
                    text = text.strip("'\" ")
                    text = text.rstrip(",;")
                    text = re.sub(r"\s+", " ", text)
                    return text

                # Mapping: line_item -> (cashflow_section, main_category, line_item)
                hosp_pl_relation_map = {
                    # Key Metrics
                    "days": ("Key Metrics", "Days", ""),
                    "keys": ("Key Metrics", "Keys", ""),
                    "room nights available (annually or monthly)": ("Key Metrics", "Room Nights Available (Annually or Monthly)", ""),
                    "occupancy": ("Key Metrics", "Occupancy", ""),
                    "room nights (sold or occupied)": ("Key Metrics", "Room Nights (Sold or Occupied)", ""),
                    "guest nights (sold or occupied)": ("Key Metrics", "Guest Nights (Sold or Occupied)", ""),
                    "guests nights (sold or occupied)": ("Key Metrics", "Guest Nights (Sold or Occupied)", ""),
                    "adr": ("Key Metrics", "ADR", ""),
                    "revpar": ("Key Metrics", "RevPAR", ""),
                    # Operating Revenue
                    "room revenue": ("Operating Revenue", "Room Revenue", ""),
                    "food and beverage revenue": ("Operating Revenue", "Food and Beverage Revenue", ""),
                    "in room-dining": ("Operating Revenue", "Food and Beverage Revenue", "In-Room Dining"),
                    "in-room dining": ("Operating Revenue", "Food and Beverage Revenue", "In-Room Dining"),
                    "venue - f&b": ("Operating Revenue", "Food and Beverage Revenue", "Venue - F&B"),
                    "other f&b revenue": ("Operating Revenue", "Food and Beverage Revenue", "Other F&B Revenue"),
                    "other operating departmental (ood) revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", ""),
                    "golf revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", "Golf Revenue"),
                    "spa & wellness - revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", "Spa & Wellness Revenue"),
                    "spa & wellness revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", "Spa & Wellness Revenue"),
                    "banquet & conference revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", "Banquet & Conference Revenue"),
                    "guest laundry revenue": ("Operating Revenue", "Other Operating Departmental (OOD) Revenue", "Guest Laundry Revenue"),
                    "other operating revenue": ("Operating Revenue", "Other Operating Revenue", ""),
                    "minor operating department": ("Operating Revenue", "Other Operating Revenue", "Minor Operating Department"),
                    "cancellation charges": ("Operating Revenue", "Other Operating Revenue", "Cancellation Charges"),
                    "miscellaneous income": ("Operating Revenue", "Other Operating Revenue", "Miscellaneous Income"),
                    "parking revenue": ("Operating Revenue", "Parking Revenue", ""),
                    # Departmental Expenses
                    "room expenses": ("Departmental Expenses", "Room Expenses", ""),
                    "food and beverage expenses": ("Departmental Expenses", "Food and Beverage Expenses", ""),
                    "other operating department (ood) expenses": ("Departmental Expenses", "Other Operating Department (OOD) Expenses", ""),
                    "golf": ("Departmental Expenses", "Other Operating Department (OOD) Expenses", "Golf"),
                    "spa & wellness": ("Departmental Expenses", "Other Operating Department (OOD) Expenses", "Spa & Wellness"),
                    "banquet & conference": ("Departmental Expenses", "Other Operating Department (OOD) Expenses", "Banquet & Conference"),
                    "laundry": ("Departmental Expenses", "Other Operating Department (OOD) Expenses", "Laundry"),
                    "other departmental expenses": ("Departmental Expenses", "Other Departmental Expenses", ""),
                    "other operating expenses": ("Departmental Expenses", "Other Departmental Expenses", "Other Operating Expenses"),
                    "parking expense": ("Departmental Expenses", "Parking Expense", ""),
                    # Undistributed Expense
                    "administrative & general": ("Undistributed Expense", "Administrative & General", ""),
                    "sales & marketing": ("Undistributed Expense", "Sales & Marketing", ""),
                    "franchise and affiliation advertising": ("Undistributed Expense", "Sales & Marketing", "Franchise and Affiliation Advertising"),
                    "loyalty programs": ("Undistributed Expense", "Sales & Marketing", "Loyalty Programs"),
                    "other expense (s&m)": ("Undistributed Expense", "Sales & Marketing", "Other Expense (S&M)"),
                    "info & telecom system": ("Undistributed Expense", "Info & Telecom System", ""),
                    "utility costs": ("Undistributed Expense", "Utility Costs", ""),
                    "electricity": ("Undistributed Expense", "Utility Costs", "Electricity"),
                    "gas": ("Undistributed Expense", "Utility Costs", "Gas"),
                    "water & sewer": ("Undistributed Expense", "Utility Costs", "Water & Sewer"),
                    "other expense (utility)": ("Undistributed Expense", "Utility Costs", "Other Expense (Utility)"),
                    # Management Fees
                    "base management fee": ("Management Fees", "Base Management Fee", ""),
                    "incentive management fee": ("Management Fees", "Incentive Management Fee", ""),
                    # Non Operating Income and Expenses
                    "insurance": ("Non Operating Income and Expenses", "Insurance", ""),
                    "other expense 1": ("Non Operating Income and Expenses", "Other Expense 1", ""),
                    "other expense 2": ("Non Operating Income and Expenses", "Other Expense 2", ""),
                    "other expense 3": ("Non Operating Income and Expenses", "Other Expense 3", ""),
                    "ffe reserve": ("Non Operating Income and Expenses", "FFE Reserve", ""),
                    "capital reserve": ("Non Operating Income and Expenses", "Capital Reserve", ""),
                    "depreciation and amortization": ("Non Operating Income and Expenses", "Depreciation and Amortization", ""),
                    "interest": ("Non Operating Income and Expenses", "Interest", ""),
                    "income taxes paid": ("Non Operating Income and Expenses", "Income Taxes Paid", ""),
                    "other income 1": ("Non Operating Income and Expenses", "Other Income 1", ""),
                    "other income 2": ("Non Operating Income and Expenses", "Other Income 2", ""),
                    "other income 3": ("Non Operating Income and Expenses", "Other Income 3", ""),
                }

                is_hospitality_pl = section_name.strip().lower() == "hospitality p&l"

                excluded_line_items = {
                    "Gross Rent",
                    "Net Lease Revenue",
                    "Total Operating Expenses",
                    "Net Operating Income",
                    "Net Cashflow from Operations_Hospitality",
                    "Total Net Cashflow from Operations",
                    "Net Cashflow from Investments",
                    "Net Cashflow from Financing",
                    "Cash Received from Asset Lease",
                    # "Base Rent",
                    # "Turnover Rent",
                    # "Service Charge",
                    # "Leasing Commissions",
                    # "Tenant Fitout Allowance",
                    "Expenses",
                    "Total Operating Expenses",
                    "Net Operating Income",
                    "Other Income/Expenses",
                    "Net Cashflow from Operations",
                    "Net Cashflow from Operations_Hospitality",
                    "Asset Acquisition Costs",
                    "Asset Acquisition Cost",
                    "Total Capex",
                    "Net Cashflow from Investments",
                    "Asset Level Term Loan",
                    "Asset Level Refinancing Facility",
                    "Net Cashflow from Financing",
                    
                    "Food and Beverage Revenue",
                    "Other Operating Departmental (OOD) Revenue",
                    "Other Operating Revenue",
                    "Other Operating Department (OOD) Expenses",
                    "Sales & Marketing",
                    "Utility Costs",
                    "Other Departmental Expenses"
                }
                normalized_excluded_line_items = {
                    _normalize_hosp_label(item) for item in excluded_line_items
                }
                promoted_to_level_2 = {
                    "Parking Revenue",
                    "Parking Expenses",
                    "EBITDA Less Reserves_Hospitality",
                    "Change in Working Capital_Hospitality",
                    "Maintenance Capex 1",
                    "Maintenance Capex 2",
                    "Maintenance Capex 3",
                    "Maintenance Capex 4",
                    "Net Asset Sale Value",
                    "Equity Injection",
                }

                records = []
                current_category = ""

                for idx_name, row in d.iterrows():
                    row_vals = row.tolist()
                    is_blank_label = (idx_name == "" or idx_name is None)
                    is_all_empty = all(v == "" for v in row_vals)
                    raw_label = "" if idx_name is None else str(idx_name).strip()

                    if is_blank_label:
                        continue

                    if is_all_empty:
                        current_category = str(idx_name)
                        continue

                    if (
                        raw_label in excluded_line_items
                        or _normalize_hosp_label(raw_label) in normalized_excluded_line_items
                    ):
                        continue

                    hosp_section = ""
                    hosp_main_category = ""
                    hosp_line_item = ""
                    if is_hospitality_pl:
                        item_name = _normalize_hosp_label(idx_name)
                        relation = hosp_pl_relation_map.get(item_name)
                        if relation is None:
                            continue
                        hosp_section, hosp_main_category, hosp_line_item = relation

                    for col_pos, (col, val) in enumerate(zip(d.columns, row_vals)):
                        col_key = int(col) if isinstance(col, (np.integer,)) else str(col)
                        if isinstance(val, (np.integer,)):
                            val = int(val)
                        elif isinstance(val, (np.floating,)):
                            val = 0 if (np.isnan(val) or np.isinf(val)) else float(val)
                        period_start_val = period_starts[col_pos] if col_pos < len(period_starts) else ""

                        if is_hospitality_pl:
                            record = {
                                "category_level": "Asset",
                                "Cashflow Section": hosp_section,
                                "Main Category": hosp_main_category,
                                "Line Item": hosp_line_item,
                                "Value Type": period_type,
                                "Period Start": period_start_val,
                                "Year": col_key,
                                "Value": val,
                            }
                        else:
                            line_name = str(idx_name)
                            main_category = current_category
                            if line_name in promoted_to_level_2:
                                main_category = line_name
                                line_name = ""
                            record = {
                                "category_level": "Asset",
                                "Cashflow Section": section_name,
                                "Main Category": main_category,
                                "Line Item": line_name,
                                "Value Type": period_type,
                                "Period Start": period_start_val,
                                "Year": col_key,
                                "Value": val,
                            }
                        records.append(record)

                return records

            _monthly_period_starts = model_timeline_me["Period Start"].tolist()
            # _annual_period_starts = model_timeline_ye["Period Start"].tolist()

            final_output = []
            final_output.extend(_df_to_records(cashflow_from_operations, "Cashflow from Operations", "Monthly", _monthly_period_starts))
            final_output.extend(_df_to_records(cashflow_from_investments, "Cashflow from Investments", "Monthly", _monthly_period_starts))
            final_output.extend(_df_to_records(cashflow_from_financing, "Cashflow from Financing", "Monthly", _monthly_period_starts))
            if hospitality_pl is not None:
                final_output.extend(_df_to_records(hospitality_pl, "Hospitality P&L", "Monthly", _monthly_period_starts))

            # for section_name, (_, annual_df) in annual_dfs.items():
            #     final_output.extend(_df_to_records(annual_df, section_name, "Annual", _annual_period_starts))
            
            # ================================================================
            # BUILD MODEL ASSUMPTIONS AND INPUT DETAILS PAYLOADS
            # ================================================================
            def _safe_value(value):
                if value is None:
                    return None
                if isinstance(value, np.generic):
                    value = value.item()
                if isinstance(value, (pd.Timestamp, datetime, date)):
                    return None if pd.isna(value) else value.isoformat()
                if isinstance(value, np.datetime64):
                    return None if np.isnat(value) else pd.Timestamp(value).isoformat()
                if isinstance(value, np.ndarray):
                    return [_safe_value(item) for item in value.tolist()]
                if isinstance(value, tuple):
                    return [_safe_value(item) for item in value]
                if isinstance(value, list):
                    return [_safe_value(item) for item in value]
                if isinstance(value, dict):
                    return {str(key): _safe_value(item) for key, item in value.items()}
                if isinstance(value, float):
                        return None if np.isnan(value) or np.isinf(value) else value
                try:
                    return None if pd.isna(value) else value
                except TypeError:
                    return value

            def _safe_dict(values):
                return {key: _safe_value(value) for key, value in values.items()}

            def _build_model_assumptions_payload():
                return {
                    "ModelInputs": _safe_dict({
                        "analysis_type": Global.ModelInputs.analysis_type,
                        "model_start_period": Global.ModelInputs.model_start_period,
                        "model_period": Global.ModelInputs.model_period,
                        "no_of_months_in_a_year": Global.ModelInputs.no_of_months_in_a_year,
                        "model_end_period": Global.ModelInputs.model_end_period,
                        "asset_acquisition_dateanalysis_date": Global.ModelInputs.asset_acquisition_dateanalysis_date,
                        "asset_holding_period": Global.ModelInputs.asset_holding_period,
                        "asset_sale_date": Global.ModelInputs.asset_sale_date,
                        "operation_start": Global.ModelInputs.operation_start,
                        "override_option": Global.ModelInputs.override_option,
                    }),
                    "AssetDetails": _safe_dict({
                        "project_name": Global.AssetDetails.project_name,
                        "asset_id": Global.AssetDetails.asset_id,
                        "asset_class": Global.AssetDetails.asset_class,
                        "asset_sub_category": Global.AssetDetails.asset_sub_category,
                        "asset_address": Global.AssetDetails.asset_address,
                        "asset_longitude": Global.AssetDetails.asset_longitude,
                        "asset_latitude": Global.AssetDetails.asset_latitude,
                        "gfa_transferred_from_devco": Global.AssetDetails.gfa_transferred_from_devco,
                        "building_efficiency": Global.AssetDetails.building_efficiency,
                        "gla_sum_of_assetco_inputs": Global.AssetDetails.gla_sum_of_assetco_inputs,
                    }),
                    "AcquisitionModule": _safe_dict({
                        "acquisition_price_assumption": Global.AcquisitionModule.acquisition_price_assumption,
                    }),
                    "ValuationParameters": _safe_dict({
                        "valuation_date_assumption": Global.ValuationParameters.valuation_date_assumption,
                        "discount_rate_assumption": Global.ValuationParameters.discount_rate_assumption,
                        "exit_yield_assumption": Global.ValuationParameters.exit_yield_assumption,
                        "ebidta_less_reserve_escalation_assumption": Global.ValuationParameters.ebidta_less_reserve_escalation_assumption,
                        "ebidta_less_reserve_top_up_assumption": Global.ValuationParameters.ebidta_less_reserve_top_up_assumption,
                        "ebidta_less_reserve_top_up_value_assumption": Global.ValuationParameters.ebidta_less_reserve_top_up_value_assumption,
                        "disposal_cost_assumption": Global.ValuationParameters.disposal_cost_assumption,
                    }),
                    "RoomRevenueAssumptions": _safe_dict({
                        "start_date": Global.RoomRevenueAssumptions.start_date,
                        "gross_leasable_area_per_room": Global.RoomRevenueAssumptions.gross_leasable_area_per_room,
                        "total_gross_leasable_area": Global.RoomRevenueAssumptions.total_gross_leasable_area,
                        "rooms_available": Global.RoomRevenueAssumptions.rooms_available,
                        "average_adr_": Global.RoomRevenueAssumptions.average_adr_,
                        "adr_escalation_profile": Global.RoomRevenueAssumptions.adr_escalation_profile,
                        "occupancy_schedule": Global.RoomRevenueAssumptions.occupancy_schedule,
                        "guest_occupancy_ratio": Global.RoomRevenueAssumptions.guest_occupancy_ratio,
                    }),
                    "FinancingModule": _safe_dict({
                        "capital_structure_total_debt_ltv": Global.FinancingModule.capital_structure_total_debt_ltv,
                        "capital_structure_total_equity": Global.FinancingModule.capital_structure_total_equity,
                        "financing_assumptions_loan_1_loan_raise_date": Global.FinancingModule.financing_assumptions_loan_1_loan_raise_date,
                        "financing_assumptions_loan_1_loan_term": Global.FinancingModule.financing_assumptions_loan_1_loan_term,
                        "financing_assumptions_loan_1_loan_end": Global.FinancingModule.financing_assumptions_loan_1_loan_end,
                        "financing_assumptions_loan_1_amortization_duration": Global.FinancingModule.financing_assumptions_loan_1_amortization_duration,
                        "financing_assumptions_loan_1_annual_amortization": Global.FinancingModule.financing_assumptions_loan_1_annual_amortization,
                        "financing_assumptions_loan_1_balloon_payment": Global.FinancingModule.financing_assumptions_loan_1_balloon_payment,
                        "financing_assumptions_loan_1_dscr": Global.FinancingModule.financing_assumptions_loan_1_dscr,
                        "financing_assumptions_loan_1_base_interest_rate": Global.FinancingModule.financing_assumptions_loan_1_base_interest_rate,
                        "financing_assumptions_loan_1_arrangement_fees": Global.FinancingModule.financing_assumptions_loan_1_arrangement_fees,
                        "financing_assumptions_loan_1_loan_refinancing_": Global.FinancingModule.financing_assumptions_loan_1_loan_refinancing_,
                        "financing_assumptions_loan_1_loan_refinancing_date": Global.FinancingModule.financing_assumptions_loan_1_loan_refinancing_date,
                        "refinancing_assumptions_ebitda_less_reserves_at_refinanced_date": Global.FinancingModule.refinancing_assumptions_ebitda_less_reserves_at_refinanced_date,
                        "refinancing_assumptions_cap_rate_at_refinanced": Global.FinancingModule.refinancing_assumptions_cap_rate_at_refinanced,
                        "refinancing_assumptions_valuation_at_refinanced": Global.FinancingModule.refinancing_assumptions_valuation_at_refinanced,
                        "refinancing_assumptions_ltv": Global.FinancingModule.refinancing_assumptions_ltv,
                        "refinancing_assumptions_ltv_max_loan": Global.FinancingModule.refinancing_assumptions_ltv_max_loan,
                        "refinancing_assumptions_min_dscr": Global.FinancingModule.refinancing_assumptions_min_dscr,
                        "refinancing_assumptions_dscr_computed": Global.FinancingModule.refinancing_assumptions_dscr_computed,
                        "refinancing_assumptions_repayment_type": Global.FinancingModule.refinancing_assumptions_repayment_type,
                        "refinancing_assumptions_loan_start": Global.FinancingModule.refinancing_assumptions_loan_start,
                        "refinancing_assumptions_loan_term": Global.FinancingModule.refinancing_assumptions_loan_term,
                        "refinancing_assumptions_loan_end": Global.FinancingModule.refinancing_assumptions_loan_end,
                        "refinancing_assumptions_amortization_duration": Global.FinancingModule.refinancing_assumptions_amortization_duration,
                        "refinancing_assumptions_amortization_percentage": Global.FinancingModule.refinancing_assumptions_amortization_percentage,
                        "refinancing_assumptions_balloon_payment": Global.FinancingModule.refinancing_assumptions_balloon_payment,
                        "refinancing_assumptions_refinanced_interest_rate": Global.FinancingModule.refinancing_assumptions_refinanced_interest_rate,
                        "refinancing_assumptions_arrangement_fees": Global.FinancingModule.refinancing_assumptions_arrangement_fees,
                    }),
                }
            
            _reset_run_cache()
            final_output_df = pd.DataFrame(final_output)
            # final_output_df.to_excel("Hospitality_Excel.xlsx", index=False)
            if "Value" in final_output_df.columns:
                value_numeric = pd.to_numeric(final_output_df["Value"], errors="coerce")
                final_output_df = final_output_df[(value_numeric.isna()) | (value_numeric != 0)].reset_index(drop=True)
            return {
                "ModelAssumptions": _build_model_assumptions_payload(),
                "normalized_dashboard_payload": final_output_df.to_dict(orient="records"),
            }

        except Exception as e:
            _reset_run_cache()
            print(f"Failed to initialise values {e}\n{traceback.format_exc()}")
            return {"error": str(e), "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}

    except Exception as e:
        _reset_run_cache()
        print(f"Failed to initialise values {e}\n{traceback.format_exc()}")
        return {"error": str(e), "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}


def fninitialising_all_values(payload):
    try:
        output = wrappper_for_vars(payload)
        if output is None:
            return {"error": "Model returned None", "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}
        return output
    except Exception as e:
        print(f"Error in initialising all values: {e}")
        return {"error": str(e), "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}
