
"""
JV Consolidation Module
=======================
Reads named ranges from Master Sheet, JV Inputs, and JV Output sheets.
Declares structured classes (Global, Asset, JVGlobal) matching the
LandCo/DevCo/AssetCo pattern.  Resolves selected JV/scenario, maps
assets to vehicles, and builds FCFF per module (LandCo, DevCo, AssetCo).

FCFF Approach
-------------
For each selected asset in the JV/JDA, we sum ALL individual line items
from Cashflow from Operations (CFO) and Cashflow from Investments (CFI)
in the upstream jvoutput payloads.  The upstream modules already apply:
  - Sign adjustment (expenses negative, income positive)
  - Inter-company elimination (LandCo sales zeroed when DevCo participates,
    DevCo acquisition zeroed when LandCo participates, etc.)
  - JV mask (non-JV asset rows zeroed out)

FCFF per module = sum(all CFO items) + sum(all CFI items), accumulated
across all assets in the selected JV for that module.
"""

import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =====================================================================
# Constants  Named Range Keys
# =====================================================================

# Master Sheet (shared across all modules)
MS_GLOBAL_CLASS     = "m.mastersheet.global.class"
MS_GLOBAL_ATTRIBUTE = "m.mastersheet.global.attribute"
MS_GLOBAL_VALUE     = "m.mastersheet.global.value"
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
OUT_ADDL_EQUITY_COMMIT_ME    = "o.jv.additional.equity.drawn.me"    # workbook typo: 'addtional' not 'additional'
OUT_ADDL_EQUITY_COMMIT_YE    = "o.jv.additional.equity.drawn.ye"    # workbook typo: 'addtional' not 'additional'

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

# Prefix groups for filtering named ranges
_PREFIXES_MS  = ["m.mastersheet"]
_PREFIXES_JV  = ["j.jv", "dd.jv"]
_PREFIXES_OUT = ["o.jv"]

# CFS sections consumed from upstream payloads
_CFS_SECTIONS  = ("Cashflow from Operations", "Cashflow from Investments", "Cashflow from Financing")
_MODULE_LABELS = ("LandCo", "DevCo", "AssetCo")


# Mapping: Python class name aa a Excel class name (for Master Sheet Asset classes)
MS_CLASS_NAME_MAP = {
    "JVModule": "JVInputsModule",
}

# =====================================================================
# CLASS 1: MasterSheet  All Master Sheet data
# =====================================================================
# Contains two sub-classes:
#   Global   scalar globals  (from m.mastersheet.global.{class,attribute,value})
#   Asset    per-asset matrix (from m.mastersheet.{inputs.class.row,attributes.row,units.data})
# Populated by fn_assign_global/asset_class_attributes using setattr.

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
# Contains two sub-classes:
#   Global  scalar globals (from j.jv.global.{class,attribute,value})
#   Asset   per-asset matrix (from j.jv.{inputs.class.row,attributes.row,units.data})
# Populated by fn_assign_global/asset_class_attributes using setattr.
#
# Class names match Excel j.jv.global.class values exactly.
# Python class names use underscores where Excel uses hyphens
# (e.g. FinancingAssumptions_Loan1 aa a "FinancingAssumptions-Loan1").

# Mapping: Python class name aa a Excel class name (for hyphenated names)
JV_CLASS_NAME_MAP = {
    "FinancingAssumptions_Loan1": "FinancingAssumptions-Loan1",
}

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
# Output Line-Item Registry  JV Consolidated Output
# =====================================================================
# Maps display labels aa a machine-safe attribute names.
# Used for: building FCFF rows, output paste, and label cleaning.

OUTPUT_LINE_ITEMS = [
    # --- Free Cashflow (FCFF = sum of all CFO + CFI items per module) ---
    ("Land Co Free Cashflow",                                        "landco_free_cashflow"),
    ("Dev Co Free Cashflow",                                         "devco_free_cashflow"),
    ("Asset Co Free Cashflow",                                       "assetco_free_cashflow"),
    ("Total Free Cashflow before Financing and SPV Related Cost",    "total_free_cashflow_before_financing_and_spv_related_cost"),
    # --- Fund-related expenses ---
    ("JV Setup Fees",                                                "jv_setup_fees"),
    ("Fund Management Expenses",                                     "fund_management_expenses"),
    ("Other Fees",                                                   "other_fees"),
    ("Project Management Fees",                                      "project_management_fees"),
    ("JV Liquidation Fees",                                          "jv_liquidation_fees"),
    ("Total Free Cashflow before Financing",                         "total_free_cashflow_before_financing"),
    # --- Financing Cost ---
    ("Arrangement Fees",                                             "arrangement_fees"),
    ("Commitment Fees",                                              "commitment_fees"),
    ("Interest Cost",                                                "interest_cost"),
    ("Net Funding Requirement",                                      "net_funding_requirement"),
    # --- Cashflow from Financing: Term Loan 1 ---
    ("TL1 Principal Drawn",                                          "tl1_principal_drawn"),
    ("TL1 Principal Repaid",                                         "tl1_principal_repaid"),
    ("TL1 Interest Paid",                                            "tl1_interest_paid"),
    ("TL1 Arrangement Fees",                                         "tl1_arrangement_fees"),
    ("TL1 Commitment Fees",                                          "tl1_commitment_fees"),
    # --- Cashflow from Financing: Term Loan 2 ---
    ("TL2 Principal Drawn",                                          "tl2_principal_drawn"),
    ("TL2 Principal Repaid",                                         "tl2_principal_repaid"),
    ("TL2 Interest Paid",                                            "tl2_interest_paid"),
    ("TL2 Arrangement Fees",                                         "tl2_arrangement_fees"),
    ("TL2 Commitment Fees",                                          "tl2_commitment_fees"),
    # --- Equity ---
    ("Equity Infused",                                               "equity_infused"),
    ("Equity Returns",                                               "equity_returns"),
    ("Net Financing Cashflows",                                      "net_financing_cashflows"),
    # --- Total Distributions (combined investor summary) ---
    ("Total Distributions",                                          "total_distributions"),
    ("Investor Contributions",                                       "investor_contributions"),
    ("Total Equity Infused",                                         "total_equity_infused"),
    ("Total Equity Returned",                                        "total_equity_returned"),
    ("Net Cashflow to Investors",                                    "net_cashflow_to_investors"),
    # --- LP Distributions ---
    ("LP Contributions",                                             "lp_contributions"),
    ("In kind Equity",                                               "lp_in_kind_equity"),
    ("Cash Equity",                                                  "lp_cash_equity"),
    ("LP Distributions",                                             "lp_distributions"),
    ("Return of Capital - LP",                                       "return_of_capital_lp"),
    ("Preferred Returns - LP",                                       "preferred_returns_lp"),
    ("Catchup Returns - LP",                                         "catchup_returns_lp"),
    ("Tier 1 Returns - LP",                                          "tier1_returns_lp"),
    ("Tier 2 Returns - LP",                                          "tier2_returns_lp"),
    ("Tier 3 Returns - LP",                                          "tier3_returns_lp"),
    ("Clawback Additions - LP",                                      "clawback_additions_lp"),
    ("Other LP Distributions",                                       "other_lp_distributions"),
    ("JV Setup Fees - LP",                                           "jv_setup_fees_lp"),
    ("Fund Management Expenses - LP",                                "fund_management_expenses_lp"),
    ("Other Fees - LP",                                              "other_fees_lp"),
    ("Project Management Fees - LP",                                 "project_management_fees_lp"),
    ("JV Liquidation Fees - LP",                                     "jv_liquidation_fees_lp"),
    ("Total LP Distributions",                                       "total_lp_distributions"),
    # --- GP Distributions ---
    ("GP Contributions",                                             "gp_contributions"),
    ("In kind Equity - GP",                                          "gp_in_kind_equity"),
    ("Cash Equity - GP",                                             "gp_cash_equity"),
    ("GP Distributions",                                             "gp_distributions"),
    ("Return of Capital - GP",                                       "return_of_capital_gp"),
    ("Catchup Returns - GP",                                         "catchup_returns_gp"),
    ("Tier 1 Promote",                                               "tier1_promote_gp"),
    ("Tier 2 Promote",                                               "tier2_promote_gp"),
    ("Tier 3 Promote",                                               "tier3_promote_gp"),
    ("Clawback Deductions - GP",                                     "clawback_deductions_gp"),
    ("Other GP Distributions",                                       "other_gp_distributions"),
    ("JV Setup Fees - GP",                                           "jv_setup_fees_gp"),
    ("Fund Management Expenses - GP",                                "fund_management_expenses_gp"),
    ("Other Fees - GP",                                              "other_fees_gp"),
    ("Project Management Fees - GP",                                 "project_management_fees_gp"),
    ("JV Liquidation Fees - GP",                                     "jv_liquidation_fees_gp"),
    ("Total GP Distributions",                                       "total_gp_distributions"),
    # --- Cash Schedule ---
    ("Opening Balance",                                              "opening_balance"),
    ("Net Cash",                                                     "net_cash"),
    ("Closing Balance",                                              "closing_balance"),
    ("Distributions Check",                                          "distributions_check"),
    # --- Project Returns ---
    ("Unlevered IRR",                                                "project_unlevered_irr"),
    ("Project NPV",                                                  "project_npv"),
    ("Levered IRR",                                                  "project_levered_irr"),
    ("NPV",                                                          "project_equity_npv"),
    ("DSCR",                                                         "project_dscr"),
    ("MOIC",                                                         "project_moic"),
    # --- LP Returns ---
    ("LP MOIC",                                                      "lp_moic"),
    ("LP IRR",                                                       "lp_irr"),
    ("LP NPV",                                                       "lp_npv"),
    # --- GP Returns ---
    ("GP MOIC",                                                      "gp_moic"),
    ("GP IRR",                                                       "gp_irr"),
    ("GP NPV",                                                       "gp_npv"),
]

# Lookup dicts derived from OUTPUT_LINE_ITEMS
_LABEL_TO_ATTR = {label: attr for label, attr in OUTPUT_LINE_ITEMS}
_ATTR_TO_LABEL = {attr: label for label, attr in OUTPUT_LINE_ITEMS}

# Valid output line item labels (used to clean fcff_names from Excel)
_VALID_OUTPUT_LABELS = {label for label, _ in OUTPUT_LINE_ITEMS}

# Section headers (not data rows  used to filter out from fcff_names)
_SECTION_HEADERS = {
    "Cashflow from Operations", "Cashflow from Investing",
    "Free Cashflow", "Fund-related expenses", "Financing Cost",
    "Cashflow from Financing", "Term Loan 1", "Term Loan 2",
    "Equity", "Total Distributions", "LP Distributions",
    "GP Distributions", "Cash Schedule", "Project Returns",
    "LP Returns", "GP Returns", "Direct Cashflow Statement",
    "Consolidated",
}

# Output paste mapping: attribute aa a named range code for Excel write-back
OUTPUT_PASTE_MAP = {
    "fcff_names":        OUT_FCFF_NAMES,
    "fcff_me":           OUT_FCFF_ME,
    "fcff_ye":           OUT_FCFF_YE,
    "cashflows_names":      OUT_CASHFLOWS_NAMES,
    "cashflows_me":         OUT_CASHFLOWS_ME,
    "cashflows_ye":         OUT_CASHFLOWS_YE,
    "project_cost_names":   OUT_PROJECT_COST_NAMES,
    "project_cost_me":      OUT_PROJECT_COST_ME,
    "project_cost_ye":      OUT_PROJECT_COST_YE,
    "fees_names":           OUT_FEES_NAMES,
    "fees_me":              OUT_FEES_ME,
    "fees_ye":              OUT_FEES_YE,
    "asset_sales_values":   OUT_ASSET_SALES_VALUES,
    "asset_sales_me":       OUT_ASSET_SALES_ME,
    "asset_sales_ye":       OUT_ASSET_SALES_YE,
    "total_funding_names":  OUT_TOTAL_FUNDING_NAMES,
    "total_funding_me":     OUT_TOTAL_FUNDING_ME,
    "total_funding_ye":     OUT_TOTAL_FUNDING_YE,
    "tl1_names":            OUT_TL1_NAMES,
    "tl1_me":               OUT_TL1_ME,
    "tl1_ye":               OUT_TL1_YE,
    "refi_names":           OUT_REFI_NAMES,
    "refi_me":              OUT_REFI_ME,
    "refi_ye":              OUT_REFI_YE,
    "equity_sched_names":   OUT_EQUITY_SCHED_NAMES,
    "equity_sched_me":      OUT_EQUITY_SCHED_ME,
    "equity_sched_ye":      OUT_EQUITY_SCHED_YE,
    "addl_equity_req_names": OUT_ADDL_EQUITY_REQ_NAMES,
    "addl_equity_req_me":    OUT_ADDL_EQUITY_REQ_ME,
    "addl_equity_req_ye":    OUT_ADDL_EQUITY_REQ_YE,
    "addl_equity_commit_names": OUT_ADDL_EQUITY_COMMIT_NAMES,
    "addl_equity_commit_me":    OUT_ADDL_EQUITY_COMMIT_ME,
    "addl_equity_commit_ye":    OUT_ADDL_EQUITY_COMMIT_YE,
    "tl1_sched_names":      OUT_TL1_SCHED_NAMES,
    "tl1_sched_me":         OUT_TL1_SCHED_ME,
    "tl1_sched_ye":         OUT_TL1_SCHED_YE,
    "refi_sched_names":     OUT_REFI_SCHED_NAMES,
    "refi_sched_me":        OUT_REFI_SCHED_ME,
    "refi_sched_ye":        OUT_REFI_SCHED_YE,
    "refi_mindscr_names":   OUT_REFI_MINDSCR_NAMES,
    "refi_mindscr_me":      OUT_REFI_MINDSCR_ME,
    "refi_mindscr_ye":      OUT_REFI_MINDSCR_YE,
    "lik_commit_names":     OUT_LIK_COMMIT_NAMES,
    "lik_commit_me":        OUT_LIK_COMMIT_ME,
    "lik_commit_ye":        OUT_LIK_COMMIT_YE,
    "total_commit_names":   OUT_TOTAL_COMMIT_NAMES,
    "total_commit_me":      OUT_TOTAL_COMMIT_ME,
    "total_commit_ye":      OUT_TOTAL_COMMIT_YE,
    "cash_dist_names":      OUT_CASH_DIST_NAMES,
    "cash_dist_me":         OUT_CASH_DIST_ME,
    "cash_dist_ye":         OUT_CASH_DIST_YE,
    "pref_returns_names":   OUT_PREF_RETURNS_NAMES,
    "pref_returns_me":      OUT_PREF_RETURNS_ME,
    "pref_returns_ye":      OUT_PREF_RETURNS_YE,
    "gp_catchup_names":     OUT_GP_CATCHUP_NAMES,
    "gp_catchup_me":        OUT_GP_CATCHUP_ME,
    "gp_catchup_ye":        OUT_GP_CATCHUP_YE,
    "tier1_lp_names":       OUT_TIER1_LP_NAMES,
    "tier1_lp_me":          OUT_TIER1_LP_ME,
    "tier1_lp_ye":          OUT_TIER1_LP_YE,
    "tier1_gp_cu_names":    OUT_TIER1_GP_CU_NAMES,
    "tier1_gp_cu_me":       OUT_TIER1_GP_CU_ME,
    "tier1_gp_cu_ye":       OUT_TIER1_GP_CU_YE,
    "tier2_lp_names":       OUT_TIER2_LP_NAMES,
    "tier2_lp_me":          OUT_TIER2_LP_ME,
    "tier2_lp_ye":          OUT_TIER2_LP_YE,
    "tier2_gp_cu_names":    OUT_TIER2_GP_CU_NAMES,
    "tier2_gp_cu_me":       OUT_TIER2_GP_CU_ME,
    "tier2_gp_cu_ye":       OUT_TIER2_GP_CU_YE,
    "tier3_names":          OUT_TIER3_NAMES,
    "tier3_me":             OUT_TIER3_ME,
    "tier3_ye":             OUT_TIER3_YE,
    "timeline_me":          OUT_TIMELINE_ME,
    "timeline_ye":          OUT_TIMELINE_YE,
}


# =====================================================================
# Helper Utilities
# =====================================================================

def _normalize_class_name(name: str) -> str:
    """Normalize a class name for flexible matching.
    Strips spaces, underscores, hyphens, slashes; lowercases."""
    return name.replace(" ", "").replace("_", "").replace("-", "").replace("/", "").lower()


def _to_float(val) -> float:
    """Convert a value to float; return 0.0 for non-numeric."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _print_stage(stage: int, title: str, details: Optional[Dict[str, Any]] = None):
    """Print a structured checkpoint stage message."""
    if details:
        for k, v in details.items():
            pass


def fn_create_model_timeline(start_date, end_date, frequency: str) -> pd.DataFrame:
    """Create a timeline DataFrame for monthly-end (ME) or year-end (YE) periods.

    Matches LandCo fn_create_model_timeline exactly.
    """
    freq_map_date_range = {'ME': 'ME', 'QE': 'QE', 'YE': 'YE'}
    freq_map_period = {'ME': 'M', 'QE': 'Q', 'YE': 'Y'}

    date_range = pd.date_range(
        start=start_date, end=end_date,
        freq=freq_map_date_range[frequency],
    )
    periods = date_range.to_period(freq_map_period[frequency])
    period_start = periods.start_time
    period_end = periods.end_time
    number_of_days = (period_end - period_start).days + 1

    df = pd.DataFrame({
        'Period Start': period_start,
        'Period End': period_end,
        'Year': period_end.year,
        'Month': period_end.month,
        '# of Days': number_of_days,
    })
    df['# of Period'] = df.index + 1
    df = df[['Period Start', 'Period End', 'Year', 'Month', '# of Period', '# of Days']]
    return df


# =====================================================================
# 1. Named Range Reading (matches LandCo fn_read_all_named_ranges_json)
# =====================================================================

def fn_read_all_named_ranges_json(namedranges: list, prefixes: List[str]) -> pd.DataFrame:
    """
    Filter *namedranges* list by *prefixes*, flatten value dimensionality.

    Dimensionality rules (matching LandCo fn_read_all_named_ranges_json):
      [[single]]              aa a scalar
      [[v1, v2, aa,]]          aa a 1-D list  (single row)
      [[v1],[v2],[v3]]       aa a 1-D list  (single column)
      [[r0c0,r0c1],[r1c0,aa,]] aa a 2-D list  (multi-row, multi-col)

    Returns DataFrame[name, value].
    """
    if not namedranges:
        return pd.DataFrame(columns=["name", "value"])

    prefix_lower = [p.lower() for p in prefixes]
    named_values: List[Tuple[str, Any]] = []

    for entry in namedranges:
        name = entry.get("name", "")
        if not any(name.lower().startswith(p) for p in prefix_lower):
            continue

        values = entry.get("values")
        if isinstance(values, list):
            if len(values) == 1 and isinstance(values[0], list):
                value = values[0][0] if len(values[0]) == 1 else values[0]
            elif all(isinstance(item, list) and len(item) == 1 for item in values):
                value = [item[0] for item in values]
            else:
                value = values
        else:
            value = values

        named_values.append((name, value))

    if named_values:
        return pd.DataFrame(named_values, columns=["name", "value"])
    return pd.DataFrame(columns=["name", "value"])


def _read_scalar(df: pd.DataFrame, key: str, default=None):
    """Read a single scalar value from an assumptions DataFrame."""
    if df.empty:
        return default
    match = df.loc[df["name"] == key, "value"]
    if match.empty:
        return default
    val = match.iloc[0]
    if isinstance(val, list):
        return val[0] if len(val) == 1 else default
    return val


def _read_array(df: pd.DataFrame, key: str) -> list:
    """Read a 1-D array value from an assumptions DataFrame."""
    if df.empty:
        return []
    match = df.loc[df["name"] == key, "value"]
    if match.empty:
        return []
    val = match.iloc[0]
    if isinstance(val, list):
        if val and isinstance(val[0], list):
            return [row[0] if isinstance(row, list) and len(row) == 1 else row
                    for row in val]
        return val
    return [val]


# =====================================================================
# 2. Class Attribute Assignment (matches LandCo setattr pattern)
# =====================================================================

def fn_assign_global_class_attributes(cls, assumptions: pd.DataFrame, 
                                       class_key: str, attr_key: str, value_key: str,
                                       class_name_map: Optional[Dict[str, str]] = None):
    """
    Assign scalar attributes to a Global subclass using setattr.
    
    Reads class/attribute/value triplets from the assumptions DataFrame.
    Only sets attributes where class_name matches cls.__name__.
    Handles date conversion from Excel serial number format.
    
    *class_name_map* maps Python class name aa a Excel class name for cases where
    Excel uses characters invalid in Python identifiers (e.g. hyphens).
    
    Matches LandCo fn_assign_global_class_attributes exactly.
    """
    try:
        class_names_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        attr_names_match  = assumptions.loc[assumptions["name"] == attr_key, "value"]
        attr_values_match = assumptions.loc[assumptions["name"] == value_key, "value"]

        if class_names_match.empty or attr_names_match.empty or attr_values_match.empty:
            return

        class_names = class_names_match.iloc[0]
        attr_names  = attr_names_match.iloc[0]
        attr_values = attr_values_match.iloc[0]

        if not isinstance(class_names, list) or not isinstance(attr_names, list):
            return

        class_name = cls.__name__
        # Map Python class name to Excel class name if needed
        mapped_name = (class_name_map or {}).get(class_name, class_name)
        norm_mapped = _normalize_class_name(mapped_name)

        # Diagnostic: show Excel vs Python attribute matching for this class
        _match_attrs_g = []
        set_count = 0
        for i, attr in enumerate(attr_names):
            if i >= len(class_names):
                continue
            excel_cls = str(class_names[i]) if class_names[i] is not None else ""
            if excel_cls == mapped_name or _normalize_class_name(excel_cls) == norm_mapped:
                _match_attrs_g.append(attr)
        _py_attrs_g = [a for a in dir(cls) if not a.startswith("_")]
        _g_matched = sum(1 for a in _match_attrs_g if hasattr(cls, a))
        if _match_attrs_g:
            if _g_matched < len(_match_attrs_g):
                _missing_g = [a for a in _match_attrs_g if not hasattr(cls, a)]
        elif class_name != mapped_name:
            pass

        for i, attr in enumerate(attr_names):
            if i >= len(class_names):
                continue
            # Exact match first, then normalized fallback
            excel_cls = str(class_names[i]) if class_names[i] is not None else ""
            if excel_cls != mapped_name and _normalize_class_name(excel_cls) != norm_mapped:
                continue
            if not hasattr(cls, attr):
                # Skip attributes not pre-defined on the class (may come from
                # other modules sharing the same named-range block).
                continue
            if i >= len(attr_values):
                continue

            val = attr_values[i]
            if "date" in attr.lower() and isinstance(val, (int, float)):
                if val == "" or val == 0:
                    setattr(cls, attr, None)
                else:
                    converted = datetime.fromtimestamp(
                        (val - 25569) * 86400.0
                    ).strftime('%Y-%m-%d')
                    setattr(cls, attr, pd.to_datetime(converted))
            else:
                setattr(cls, attr, val)
    except Exception as e:
        raise


def fn_assign_asset_class_attributes(cls, assumptions: pd.DataFrame,
                                      class_key: str, attr_key: str, data_key: str,
                                      inclusion_attr: str = "asset_jv_inclusion",
                                      class_name_map: Optional[Dict[str, str]] = None):
    """
    Assign per-asset list attributes to an Asset subclass using setattr.
    
    Reads class.row + attribute.row + units.data from the assumptions DataFrame.
    Each attribute becomes a list (one value per asset row).
    Respects inclusion flag: excluded rows get np.nan / pd.NaT.
    
    *class_name_map* maps Python class name aa a Excel class name for cases where
    Excel uses characters invalid in Python identifiers (e.g. hyphens).
    
    Matches LandCo fn_assign_asset_class_attributes exactly.
    """
    try:
        class_names_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        attr_names_match  = assumptions.loc[assumptions["name"] == attr_key, "value"]
        data_match        = assumptions.loc[assumptions["name"] == data_key, "value"]

        if class_names_match.empty or attr_names_match.empty or data_match.empty:
            missing = []
            if class_names_match.empty:
                missing.append(f"class_key='{class_key}'")
            if attr_names_match.empty:
                missing.append(f"attr_key='{attr_key}'")
            if data_match.empty:
                missing.append(f"data_key='{data_key}'")
            # Show what keys ARE available for diagnosis
            available = sorted(assumptions["name"].unique().tolist()) if not assumptions.empty else []
            # Show close matches
            for mk in missing:
                k = mk.split("'")[1]
                close = [a for a in available if k.split(".")[-1] in a or a.split(".")[-1] in k]
                if close:
                    pass
            return

        class_names = class_names_match.iloc[0]
        attr_names  = attr_names_match.iloc[0]
        attr_values = data_match.iloc[0]

        if not isinstance(class_names, list) or not isinstance(attr_names, list):
            return
        if not isinstance(attr_values, list):
            return

        class_name = cls.__name__
        # Map Python class name to Excel class name if needed
        mapped_name = (class_name_map or {}).get(class_name, class_name)
        norm_mapped = _normalize_class_name(mapped_name)

        # Diagnostic: show Excel vs Python attribute matching for this class
        matching_excel_attrs = []
        for _i, _attr in enumerate(attr_names):
            if _i >= len(class_names):
                continue
            _ecls = str(class_names[_i]) if class_names[_i] is not None else ""
            if _ecls == mapped_name or _normalize_class_name(_ecls) == norm_mapped:
                matching_excel_attrs.append(_attr)
        python_attrs = [a for a in dir(cls) if not a.startswith("_")]
        matched_count = sum(1 for a in matching_excel_attrs if hasattr(cls, a))
        if matching_excel_attrs:
            if matched_count < len(matching_excel_attrs):
                missing = [a for a in matching_excel_attrs if not hasattr(cls, a)]
        elif class_name != mapped_name:
            pass

        # Find inclusion flag index
        inclusion_idx = None
        if inclusion_attr in attr_names:
            inclusion_idx = attr_names.index(inclusion_attr)

        if inclusion_idx is not None:
            inclusion_flags = [
                row[inclusion_idx] == "Yes"
                for row in attr_values
                if isinstance(row, list) and inclusion_idx < len(row)
            ]
        else:
            inclusion_flags = [True] * len(attr_values)

        for i, attr in enumerate(attr_names):
            if i >= len(class_names):
                continue
            # Exact match first, then normalized fallback
            excel_cls = str(class_names[i]) if class_names[i] is not None else ""
            if excel_cls != mapped_name and _normalize_class_name(excel_cls) != norm_mapped:
                continue
            if not hasattr(cls, attr):
                # Skip attributes not pre-defined on the class (may come from
                # other modules sharing the same named-range block).
                continue

            col = []
            is_date = "date" in attr.lower()
            for idx, row in enumerate(attr_values):
                if not isinstance(row, list) or i >= len(row):
                    col.append(pd.NaT if is_date else np.nan)
                    continue
                val = row[i]
                if idx < len(inclusion_flags) and not inclusion_flags[idx]:
                    col.append(pd.NaT if is_date else np.nan)
                elif val == "" or val is None:
                    col.append(pd.NaT if is_date else np.nan)
                elif is_date:
                    if val == 0:
                        col.append(pd.NaT)
                    else:
                        try:
                            converted = datetime.fromtimestamp(
                                (float(val) - 25569) * 86400.0
                            ).strftime('%Y-%m-%d')
                            col.append(pd.to_datetime(converted))
                        except (ValueError, TypeError, OSError):
                            col.append(pd.NaT)
                else:
                    col.append(val)
            setattr(cls, attr, col)
    except Exception as e:
        raise


def fn_initialize_global_class(assumptions: pd.DataFrame,
                                global_cls, class_key: str,
                                attr_key: str, value_key: str,
                                class_name_map: Optional[Dict[str, str]] = None):
    """
    Initialize all subclasses of *global_cls* with values from assumptions.
    Iterates through all nested classes and calls fn_assign_global_class_attributes.
    """
    try:
        # Diagnostic: discover class names present in the Excel data
        _cls_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        if not _cls_match.empty:
            _cls_list = _cls_match.iloc[0]
            if isinstance(_cls_list, list):
                _unique = sorted(set(str(c) for c in _cls_list if c is not None and str(c).strip()))

        for subclass_name in dir(global_cls):
            subclass = getattr(global_cls, subclass_name)
            if isinstance(subclass, type):
                fn_assign_global_class_attributes(
                    subclass, assumptions, class_key, attr_key, value_key,
                    class_name_map,
                )
    except Exception as e:
        raise


def fn_initialize_asset_class(assumptions: pd.DataFrame,
                               asset_cls, class_key: str,
                               attr_key: str, data_key: str,
                               inclusion_attr: str = "asset_jv_inclusion",
                               class_name_map: Optional[Dict[str, str]] = None):
    """
    Initialize all subclasses of *asset_cls* with values from assumptions.
    Iterates through all nested classes and calls fn_assign_asset_class_attributes.
    """
    try:
        # Diagnostic: discover class names present in the Excel data
        _cls_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        excel_class_names: List[str] = []
        if not _cls_match.empty:
            _cls_list = _cls_match.iloc[0]
            if isinstance(_cls_list, list):
                excel_class_names = sorted(set(str(c) for c in _cls_list if c is not None and str(c).strip()))

        # Show Python subclasses and their mapped Excel names
        python_subclasses = [n for n in dir(asset_cls) if isinstance(getattr(asset_cls, n), type)]
        for sc_name in python_subclasses:
            mapped = (class_name_map or {}).get(sc_name, sc_name)
            norm = _normalize_class_name(mapped)
            matched_excel = [ec for ec in excel_class_names
                             if ec == mapped or _normalize_class_name(ec) == norm]
            status = f"MATCHED aa a {matched_excel}" if matched_excel else "NO MATCH"
            if not matched_excel and excel_class_names:
                # Try fuzzy: check if any Excel name contains the mapped name or vice versa
                close = [ec for ec in excel_class_names
                         if norm in _normalize_class_name(ec) or _normalize_class_name(ec) in norm]
                if close:
                    status += f" (close: {close})"

        for subclass_name in dir(asset_cls):
            subclass = getattr(asset_cls, subclass_name)
            if isinstance(subclass, type):
                fn_assign_asset_class_attributes(
                    subclass, assumptions, class_key, attr_key, data_key,
                    inclusion_attr, class_name_map,
                )
    except Exception as e:
        raise


def _clean_fcff_names(raw_names: list) -> List[str]:
    """
    Clean FCFF name labels from the Excel output sheet.
    Removes section headers, blank rows, and numeric filler (0, "0").
    Only keeps labels that match OUTPUT_LINE_ITEMS or are actual data rows.
    """
    cleaned: List[str] = []
    for name in raw_names:
        if name is None or name == "" or name == 0 or str(name).strip() == "0":
            continue
        label = str(name).strip()
        if label in _SECTION_HEADERS:
            continue
        cleaned.append(label)
    return cleaned


# =====================================================================
# 3. AssetCo Entry Normalisation
# =====================================================================

def _normalize_assetco_entries(raw_list: list) -> List[dict]:
    """
    Normalise AssetCo per-asset entries so every entry has direct
    section keys at the top level.

    Handles three formats:
      a) Direct:   entry["Cashflow from Operations"] = {index,columns,data}
      b) Nested:   entry["monthly_dfs"]["Cashflow from Operations"] =
                        ("o.assetco.cfo.me", {index,columns,data})
      c) Legacy:   entry["output_json"]["monthly_dfs"]["Cashflow from Operations"] =
                        ("o.assetco.cfo.me", {index,columns,data})
    """
    normalised: List[dict] = []
    for ei, entry in enumerate(raw_list):
        if not isinstance(entry, dict):
            continue
        asset_name = entry.get("asset_name", f"(unnamed-{ei})")
        norm: Dict[str, Any] = {"asset_name": asset_name}

        format_used = "none"

        # Format A: direct CFS section keys at top level
        for section in _CFS_SECTIONS:
            val = entry.get(section)
            if isinstance(val, dict) and "index" in val:
                norm[section] = val
                format_used = "A (direct)"

        if any(section in norm for section in _CFS_SECTIONS):
            sections_found = [s for s in _CFS_SECTIONS if s in norm]
            normalised.append(norm)
            continue

        # Resolve the monthly_dfs source  try both new and legacy contract
        monthly = entry.get("monthly_dfs")
        source = "monthly_dfs"
        if not isinstance(monthly, dict):
            output_json = entry.get("output_json", {})
            if isinstance(output_json, dict):
                monthly = output_json.get("monthly_dfs")
                source = "output_json.monthly_dfs"

        if isinstance(monthly, dict):
            for section in _CFS_SECTIONS:
                val = monthly.get(section)
                if isinstance(val, (tuple, list)) and len(val) >= 2:
                    payload = val[1]
                    if isinstance(payload, dict) and "index" in payload:
                        norm[section] = payload
                        format_used = f"B (tuple from {source})"
                elif isinstance(val, dict) and "index" in val:
                    norm[section] = val
                    format_used = f"C (direct dict from {source})"

        if any(section in norm for section in _CFS_SECTIONS):
            sections_found = [s for s in _CFS_SECTIONS if s in norm]
            normalised.append(norm)
        else:
            top_keys = list(entry.keys())[:8]
            if isinstance(entry.get("output_json"), dict):
                oj_keys = list(entry["output_json"].keys())[:8]

    return normalised


# =====================================================================
# 4. Asset & Selection Resolution (class-based)
# =====================================================================

def _get_asset_names_from_payload(
    landco_data: dict, devco_data: dict,
) -> List[str]:
    """
    Resolve asset names from LandCo/DevCo asset_assumptions.
    
    Handles both dict-of-lists and split-payload (class_to_dict) formats.
    """
    for model_data in (landco_data, devco_data):
        if not model_data:
            continue
        assumptions = model_data.get("asset_assumptions", {})
        if not isinstance(assumptions, dict):
            continue
        project_details = assumptions.get("ProjectDetails", {})
        if not isinstance(project_details, dict):
            continue

        # Format A: dict-of-lists {"asset_name": ["A", "B"]}
        names = project_details.get("asset_name")
        if names is not None:
            if isinstance(names, (list, tuple)):
                return [str(n) for n in names if str(n).strip().lower() != "nan"]
            if isinstance(names, dict):
                sorted_items = sorted(
                    names.items(),
                    key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
                )
                return [str(v) for _, v in sorted_items if str(v).strip().lower() != "nan"]

        # Format B: split-payload {index, columns, data} from class_to_dict
        columns = project_details.get("columns")
        data = project_details.get("data")
        if isinstance(columns, list) and isinstance(data, list):
            col_idx = None
            for ci, col_name in enumerate(columns):
                if str(col_name).strip().lower() == "asset_name":
                    col_idx = ci
                    break
            if col_idx is not None:
                result = []
                for row in data:
                    if isinstance(row, list) and col_idx < len(row):
                        result.append(str(row[col_idx]))
                if result:
                    return result

    # Fallback: infer asset count from CFS data rows
    for model_data in (landco_data, devco_data):
        if not model_data:
            continue
        for section in _CFS_SECTIONS:
            section_data = model_data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for item_json in section_data.values():
                if isinstance(item_json, dict) and "data" in item_json:
                    return [f"Asset_{i}" for i in range(len(item_json["data"]))]

    return []


def _get_asset_names_from_classes() -> List[str]:
    """Get asset names from the populated MasterSheet.Asset.ProjectDetails class.
    Returns only valid (non-empty, non-nan) names  used for display/payload lookup."""
    names = MasterSheet.Asset.ProjectDetails.asset_name
    if isinstance(names, list):
        return [
            str(n) for n in names
            if n is not None and str(n).strip() and str(n).strip().lower() != "nan"
        ]
    return []


def _get_raw_asset_names_from_classes() -> List[Optional[str]]:
    """Get the RAW asset name list preserving index alignment with units.data rows.
    Empty/nan entries are kept as None so indices match JVModule attribute lists."""
    names = MasterSheet.Asset.ProjectDetails.asset_name
    if isinstance(names, list):
        result: List[Optional[str]] = []
        for n in names:
            if n is None or str(n).strip() == "" or str(n).strip().lower() == "nan":
                result.append(None)
            else:
                result.append(str(n).strip())
        return result
    return []


def _find_asset_index(model_data: dict, asset_name: str) -> Optional[int]:
    """
    Find the row index of *asset_name* in a LandCo/DevCo payload.
    
    Handles both dict-of-lists and split-payload formats:
      a) {"asset_name": ["A", "B", "C"]}       aa a dict-of-lists
      b) {"index": [...], "columns": [..., "asset_name", ...], "data": [[...]]}  aa a split payload
    """
    if not model_data:
        return None
    assumptions = model_data.get("asset_assumptions", {})
    if not isinstance(assumptions, dict):
        return None
    project_details = assumptions.get("ProjectDetails", {})
    if not isinstance(project_details, dict):
        return None

    target = asset_name.strip().lower()

    # --- Format A: dict-of-lists (e.g. {"asset_name": ["A", "B"]}) ---
    names = project_details.get("asset_name")
    if names is not None:
        if isinstance(names, dict):
            sorted_items = sorted(
                names.items(),
                key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
            )
            name_list = [str(v) for _, v in sorted_items]
        elif isinstance(names, (list, tuple)):
            name_list = [str(n) for n in names]
        else:
            name_list = None

        if name_list:
            for idx, n in enumerate(name_list):
                if n.strip().lower() == target:
                    return idx
            return None

    # --- Format B: split payload {index, columns, data} from class_to_dict ---
    columns = project_details.get("columns")
    data = project_details.get("data")
    if isinstance(columns, list) and isinstance(data, list):
        col_idx = None
        for ci, col_name in enumerate(columns):
            if str(col_name).strip().lower() == "asset_name":
                col_idx = ci
                break
        if col_idx is not None:
            for row_idx, row in enumerate(data):
                if isinstance(row, list) and col_idx < len(row):
                    if str(row[col_idx]).strip().lower() == target:
                        return row_idx
            # Not found  show available names
            available = []
            for row in data[:10]:
                if isinstance(row, list) and col_idx < len(row):
                    available.append(str(row[col_idx]))

    return None


def _normalize_asset_name(name: str) -> str:
    """Normalize an asset name for matching: lowercase, collapse separators."""
    return name.strip().lower().replace("_", " ").replace("-", " ")


def _tokenize(name: str) -> set:
    """Tokenize a normalized asset name into a set of words."""
    return set(_normalize_asset_name(name).split())


def _find_assetco_entry(
    assetco_per_asset: List[dict], asset_name: str,
) -> Optional[dict]:
    """Find an AssetCo per-asset entry using multi-pass matching.

    Pass 1: Exact match (case-insensitive)
    Pass 2: Prefix/contains match after normalizing separators
    Pass 3: Token overlap  all tokens of the shorter name must appear
            in the longer name (handles suffixes like _DBR_With Escalation)
    """
    target = _normalize_asset_name(asset_name)
    target_tokens = _tokenize(asset_name)

    if not target or not target_tokens:
        return None

    # Pass 1: exact normalized match
    for entry in assetco_per_asset:
        name = _normalize_asset_name(str(entry.get("asset_name") or ""))
        if name == target:
            return entry

    # Pass 2: prefix / contains  target contained in entry name or vice versa
    for entry in assetco_per_asset:
        name = _normalize_asset_name(str(entry.get("asset_name") or ""))
        if not name:
            continue
        if name.startswith(target) or target.startswith(name):
            return entry

    # Pass 3: token-based  all tokens from the master name must appear
    # in the AssetCo name (allows extra suffixes/scenario tags)
    best_match = None
    best_overlap = 0
    for entry in assetco_per_asset:
        name_tokens = _tokenize(str(entry.get("asset_name") or ""))
        if not name_tokens:
            continue

        # Check if the master name's tokens are a subset of the entry name's tokens
        if target_tokens.issubset(name_tokens):
            overlap = len(target_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = entry

    if best_match:
        matched_name = str(best_match.get("asset_name", ""))
        return best_match

    return None


def _safe_str_lower(val) -> str:
    """Convert a value to stripped lowercase string, handling None/NaN/NaT."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("nan", "nat", "none", ""):
        return ""
    return s


def _resolve_selection(
    out_df: pd.DataFrame,
    all_asset_names: List[str],
    raw_asset_names: List[Optional[str]],
) -> dict:
    """
    Resolve selected vehicle/scenario aa a asset list aa a module flags.

    Uses *raw_asset_names* (index-aligned with MasterSheet.Asset data rows)
    for proper alignment with JVModule attribute lists.
    Uses *all_asset_names* only as a fallback lookup when raw list is unavailable.

    Uses MasterSheet.Asset.JVModule (jvjda_inclusion, jv_name, venture_type,
    landco_inclusion, devco_inclusion, assetco_inclusion) and
    MasterSheet.Asset.AssetLifecycleModule (land_development,
    vertical_development, asset_operations) to determine:
      1. Which assets are JV/JDA-eligible
      2. Which JV each asset belongs to
      3. Which modules contribute cash flows per asset

    No fallback mode  if JVModule data is not populated, an error is raised.
    """
    selected_vehicle  = _read_scalar(out_df, OUT_SELECTED_VEHICLE)
    selected_scenario = _read_scalar(out_df, OUT_SELECTED_SCENARIO)

    context: Dict[str, Any] = {
        "selected_vehicle_type": selected_vehicle,
        "selected_scenario": selected_scenario,
        "selected_assets": [],
        "module_flags": {},
        "lifecycle_flags": {},
        "jv_groups": {},          # jv_name aa a [asset_names]
        "venture_types": {},      # asset_name aa a venture_type
    }

    # --- Read JVModule class attributes ---
    jv_inclusion  = MasterSheet.Asset.JVModule.jvjda_inclusion
    jv_names      = MasterSheet.Asset.JVModule.jv_name
    venture_types = MasterSheet.Asset.JVModule.venture_type
    lc_inclusion  = MasterSheet.Asset.JVModule.landco_inclusion
    dc_inclusion  = MasterSheet.Asset.JVModule.devco_inclusion
    ac_inclusion  = MasterSheet.Asset.JVModule.assetco_inclusion

    # --- Read lifecycle flags ---
    lc_lifecycle = MasterSheet.Asset.AssetLifecycleModule.land_development
    dc_lifecycle = MasterSheet.Asset.AssetLifecycleModule.vertical_development
    ac_lifecycle = MasterSheet.Asset.AssetLifecycleModule.asset_operations

    if not isinstance(jv_inclusion, list) or len(jv_inclusion) == 0:
        # Return empty selection  caller must handle this
        return context

    scenario_lower = _safe_str_lower(selected_scenario)
    vehicle_lower = _safe_str_lower(selected_vehicle)


    for idx in range(len(jv_inclusion)):
        incl = _safe_str_lower(jv_inclusion[idx])
        if incl != "yes":
            continue

        # Use raw_asset_names for index alignment (preserves empty rows)
        asset_name = raw_asset_names[idx] if idx < len(raw_asset_names) else None
        if not asset_name:
            # Empty/nan row in data  skip
            continue

        # --- Check jv_name filter (if a scenario is selected) ---
        rec_jv = ""
        if isinstance(jv_names, list) and idx < len(jv_names):
            rec_jv = _safe_str_lower(jv_names[idx])

        if scenario_lower and rec_jv and rec_jv != scenario_lower:
            continue

        # --- Check venture_type filter (if a vehicle is selected) ---
        rec_vt = ""
        if isinstance(venture_types, list) and idx < len(venture_types):
            rec_vt = _safe_str_lower(venture_types[idx])

        if vehicle_lower and rec_vt and rec_vt != vehicle_lower:
            continue

        # asset_name already resolved from raw_asset_names above

        # Module inclusion flags from JVInputsModule
        lc_flag = _safe_str_lower(lc_inclusion[idx]) == "yes" if isinstance(lc_inclusion, list) and idx < len(lc_inclusion) else False
        dc_flag = _safe_str_lower(dc_inclusion[idx]) == "yes" if isinstance(dc_inclusion, list) and idx < len(dc_inclusion) else False
        ac_flag = _safe_str_lower(ac_inclusion[idx]) == "yes" if isinstance(ac_inclusion, list) and idx < len(ac_inclusion) else False

        # Lifecycle flags from AssetLifecycleModule
        lc_life = _safe_str_lower(lc_lifecycle[idx]) == "yes" if isinstance(lc_lifecycle, list) and idx < len(lc_lifecycle) else False
        dc_life = _safe_str_lower(dc_lifecycle[idx]) == "yes" if isinstance(dc_lifecycle, list) and idx < len(dc_lifecycle) else False
        ac_life = _safe_str_lower(ac_lifecycle[idx]) == "yes" if isinstance(ac_lifecycle, list) and idx < len(ac_lifecycle) else False

        context["selected_assets"].append(asset_name)
        context["module_flags"][asset_name] = {
            "landco": lc_flag,
            "devco": dc_flag,
            "assetco": ac_flag,
        }
        context["lifecycle_flags"][asset_name] = {
            "land_development": lc_life,
            "vertical_development": dc_life,
            "asset_operations": ac_life,
        }
        context["venture_types"][asset_name] = rec_vt or "(not set)"

        # Group by jv_name
        jv_key = rec_jv or "(unnamed)"
        context["jv_groups"].setdefault(jv_key, []).append(asset_name)

    return context


# =====================================================================
# 5. Payload Extraction  SUM ALL ITEMS approach
# =====================================================================
# Instead of searching for a single "net" line, we sum ALL line items
# in the CFO and CFI sections for the given asset row.  The upstream
# payloads already have sign-adjusted, post-elimination values so a
# straight element-wise sum across items yields the correct net figure.
# FCFF = sum(CFO items) + sum(CFI items).
# =====================================================================

# Sections to consume for FCFF
_FCFF_SECTIONS = ("Cashflow from Operations", "Cashflow from Investments")


def _sum_section_for_asset_in_model(
    model_data: dict, section: str, asset_idx: int,
) -> Tuple[List[float], List[Tuple[str, float]]]:
    """
    Sum ALL line items in a CFS section for one asset row from a
    LandCo/DevCo jvoutput payload.

    LandCo/DevCo jvoutput structure per section:
        section_data[item_name] = {
            "index": [asset_name_0, ...],
            "columns": [0, 1, ...],
            "data": [[asset0_p0, asset0_p1, ...], [asset1_p0, ...], ...]
        }

    The values are already sign-adjusted and post-elimination by the
    upstream module.  We sum every item's ``data[asset_idx]`` row
    element-wise to get the net section cashflow for this asset.

    Returns ``(summed_row, [(item_name, item_total), ...])`` for
    diagnostics.
    """
    section_data = model_data.get(section, {})
    if not isinstance(section_data, dict):
        return [], []

    summed: Optional[List[float]] = None
    item_details: List[Tuple[str, float]] = []

    for item_name, item_json in section_data.items():
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if asset_idx >= len(data_rows):
            continue

        row = [_to_float(v) for v in data_rows[asset_idx]]
        item_total = sum(row)
        item_details.append((item_name, item_total))

        if summed is None:
            summed = list(row)
        else:
            width = max(len(summed), len(row))
            summed = [
                (summed[j] if j < len(summed) else 0.0)
                + (row[j] if j < len(row) else 0.0)
                for j in range(width)
            ]

    return summed or [], item_details


_ASSETCO_NET_ROW_NAMES = {
    "Cashflow from Operations": (
        "total net cashflow from operations",
        "net cashflow from operations",
    ),
    "Cashflow from Investments": (
        "net cashflow from investments",
    ),
    "Cashflow from Financing": (
        "net cashflow from financing",
    ),
}

# AssetCo CFI items to EXCLUDE from the net row  these are handled
# elsewhere (through LandCo / capital structure) and should not be
# double-counted via AssetCo cashflows.
_ASSETCO_CFI_EXCLUDE = {
    "acquisition price",
    "asset acquisition cost",
}


def _sum_section_for_assetco(
    assetco_df_json: dict,
    section_name: str = "",
    exclude_items: Optional[set] = None,
) -> Tuple[List[float], List[Tuple[str, float]]]:
    """
    Extract the **Net** total row from an AssetCo CFS section.

    AssetCo CFS sections contain individual line items AND a Net total
    row (e.g. "Net Cashflow from Operations").  Summing all rows would
    double-count.  Instead we look for the Net total row by name, and
    fall back to the last non-blank row if not found.

    Returns ``(net_row, [(item_name, item_total), ...])`` for
    diagnostics.
    """
    if not assetco_df_json or not isinstance(assetco_df_json, dict):
        return [], []

    index = assetco_df_json.get("index", [])
    data  = assetco_df_json.get("data", [])

    # Build diagnostics for all rows
    item_details: List[Tuple[str, float]] = []
    for ri, item_name in enumerate(index):
        if ri >= len(data):
            continue
        row = [_to_float(v) for v in data[ri]]
        item_total = sum(row)
        item_details.append((str(item_name), item_total))

    # Find the Net total row by name
    net_candidates = _ASSETCO_NET_ROW_NAMES.get(section_name, ())
    net_row: Optional[List[float]] = None
    net_row_name = ""

    # Priority: match by known net row names
    for ri, item_name in enumerate(index):
        if ri >= len(data):
            continue
        name_lower = str(item_name).strip().lower()
        if name_lower in net_candidates:
            net_row = [_to_float(v) for v in data[ri]]
            net_row_name = str(item_name)
            # For CFO, prefer "Total Net Cashflow from Operations" over
            # "Net Cashflow from Operations" (it includes hospitality)
            if name_lower == net_candidates[0]:
                break  # first candidate is highest priority

    # Fallback: last non-blank row in the section
    if net_row is None:
        for ri in range(len(index) - 1, -1, -1):
            name = str(index[ri]).strip()
            if name and ri < len(data):
                net_row = [_to_float(v) for v in data[ri]]
                net_row_name = name
                break

    if net_row is not None:

        # Subtract excluded items from the net row
        if exclude_items and net_row:
            for ri, item_name in enumerate(index):
                if ri >= len(data):
                    continue
                name_lower = str(item_name).strip().lower()
                if name_lower in exclude_items:
                    excl_row = [_to_float(v) for v in data[ri]]
                    excl_total = sum(excl_row)
                    if abs(excl_total) > 0.01:
                        net_row = [
                            net_row[j] - (excl_row[j] if j < len(excl_row) else 0.0)
                            for j in range(len(net_row))
                        ]
            if exclude_items:
                pass
    else:
        pass

    return net_row or [], item_details


# aaa, Sales Value Extraction Helpers aaa,
# Used by the fees section (step 7d) to extract asset sales value per module.

# AssetCo: "Asset Sale Value" in CFI
_ASSETCO_SALES_CANDIDATES = (
    "asset sale value", "asset sales value", "net asset sale value",
)
# DevCo: CFO items for sales revenue
_DEVCO_SALES_CANDIDATES = (
    "cash received from asset sales",
    "asset sales through escrow",
    "asset sales through collection (post-dev)",
)
# LandCo: CFO + CFI exit items
_LANDCO_SALES_CANDIDATES_CFO = (
    "land sales",
)
_LANDCO_SALES_CANDIDATES_CFI = (
    "land lease - terminal value", "land bank - exit value",
)


def _extract_item_from_lc_dc_section(
    model_data: dict, section: str, asset_idx: int,
    candidate_names: Tuple[str, ...],
) -> List[float]:
    """
    Extract and sum specific named items from a LandCo/DevCo CFS section
    for a single asset row.

    Returns the summed row across all matched candidate items.
    """
    section_data = model_data.get(section, {})
    if not isinstance(section_data, dict):
        return []

    candidates_lower = {c.strip().lower() for c in candidate_names}
    summed: Optional[List[float]] = None

    for item_name, item_json in section_data.items():
        if item_name.strip().lower() not in candidates_lower:
            continue
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if asset_idx >= len(data_rows):
            continue

        row = [_to_float(v) for v in data_rows[asset_idx]]
        if summed is None:
            summed = list(row)
        else:
            width = max(len(summed), len(row))
            summed = [
                (summed[j] if j < len(summed) else 0.0)
                + (row[j] if j < len(row) else 0.0)
                for j in range(width)
            ]

    return summed or []


def _extract_item_from_assetco_section(
    ac_entry: dict, section: str,
    candidate_names: Tuple[str, ...],
) -> List[float]:
    """
    Extract specific named items from an AssetCo CFS section.

    AssetCo sections use {index: [...], data: [[...], ...]} structure
    where index lists row labels.
    """
    section_data = ac_entry.get(section)
    if not section_data or not isinstance(section_data, dict):
        return []

    index = section_data.get("index", [])
    data = section_data.get("data", [])
    candidates_lower = {c.strip().lower() for c in candidate_names}

    summed: Optional[List[float]] = None

    for ri, item_name in enumerate(index):
        if str(item_name).strip().lower() not in candidates_lower:
            continue
        if ri >= len(data):
            continue

        row = [_to_float(v) for v in data[ri]]
        if summed is None:
            summed = list(row)
        else:
            width = max(len(summed), len(row))
            summed = [
                (summed[j] if j < len(summed) else 0.0)
                + (row[j] if j < len(row) else 0.0)
                for j in range(width)
            ]

    return summed or []


_LAND_IN_KIND_CANDIDATES = (
    "Land in Kind", "Land In Kind", "Land in Kind Contribution", "Land Equity",
    "Land Acquisition Cost In Kind",
)


def _extract_land_in_kind_from_section(
    section_data: dict, asset_idx: int, section_label: str,
) -> Optional[List[float]]:
    """
    Search a single CFS section dict for a Land in Kind item at *asset_idx*.

    Uses the same per-asset extraction logic as _sum_section_for_asset_in_model:
    iterates all items, matches Land in Kind candidate names, picks
    data[asset_idx].  Items where asset_idx >= len(data) are skipped to
    prevent returning project-level totals.

    Returns the extracted row or None if not found / out-of-range.
    """
    if not isinstance(section_data, dict):
        return None

    _candidates_lower = {c.strip().lower() for c in _LAND_IN_KIND_CANDIDATES}

    summed: Optional[List[float]] = None

    for item_name, item_json in section_data.items():
        if item_name.strip().lower() not in _candidates_lower:
            continue
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if not data_rows:
            continue

        if asset_idx >= len(data_rows):
            continue

        row = [_to_float(v) for v in data_rows[asset_idx]]
        row_total = sum(row)
        idx_names = item_json.get("index", [])
        asset_at_idx = idx_names[asset_idx] if asset_idx < len(idx_names) else "?"

        if summed is None:
            summed = list(row)
        else:
            width = max(len(summed), len(row))
            summed = [
                (summed[j] if j < len(summed) else 0.0)
                + (row[j] if j < len(row) else 0.0)
                for j in range(width)
            ]

    return summed


def _extract_land_in_kind_from_model(
    model_data: dict, asset_idx: int,
) -> List[float]:
    """
    Extract the "Land in Kind" row for a specific asset.

    Search order (first match wins):
      1. **Support Workings**  always has per-asset rows (one row per
         asset, JV-masked).  Key: ``"Support Workings"`` or
         ``"support workings"``.
      2. **Cashflow from Financing**  fallback; some payloads may store
         project-level totals here (single row) which would be incorrect
         for per-asset extraction.

    Within each section the same per-asset guard is used: items where
    asset_idx >= len(data) are skipped, preventing accidental use of
    project-level totals.
    """
    # Log CFF items for diagnostics
    cff_section = model_data.get("Cashflow from Financing", {})
    if isinstance(cff_section, dict):
        for key, val in cff_section.items():
            if isinstance(val, dict) and "data" in val:
                nrows = len(val["data"])

    # 1. Try Support Workings first (reliable per-asset data)
    sw_section = model_data.get("Support Workings") or model_data.get("support workings")
    if isinstance(sw_section, dict):
        sw_keys = [k for k in sw_section if isinstance(sw_section[k], dict) and "data" in sw_section[k]]
        result = _extract_land_in_kind_from_section(sw_section, asset_idx, "SW")
        if result is not None:
            return result

    # 2. Fallback to Cashflow from Financing
    if isinstance(cff_section, dict):
        result = _extract_land_in_kind_from_section(cff_section, asset_idx, "CFF")
        if result is not None:
            return result

    return []


def _show_cff_items_at_idx(model_data: dict, asset_idx: int, module_label: str):
    """Diagnostic: show all CFF items and their values at asset_idx."""
    cff = model_data.get("Cashflow from Financing", {})
    if not isinstance(cff, dict):
        return
    for item_name, item_json in cff.items():
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data = item_json["data"]
        n_rows = len(data)
        idx_names = item_json.get("index", [])
        if asset_idx < n_rows:
            row = data[asset_idx]
            total = sum(_to_float(v) for v in row)
            asset_at = idx_names[asset_idx] if asset_idx < len(idx_names) else "?"
            if abs(total) > 0.01:
                pass
        elif n_rows == 1:
            row = data[0]
            total = sum(_to_float(v) for v in row)


def _extract_asset_fcff(
    asset_name: str,
    landco_data: dict,
    devco_data: dict,
    assetco_per_asset: List[dict],
    module_flags: dict,
) -> Dict[str, List[float]]:
    """
    Compute FCFF for each participating module for one asset.

    For LandCo/DevCo: sums all CFO items + all CFI items at the given
    asset row index.  The data is already sign-adjusted and
    post-elimination in the jvoutput.

    For AssetCo: sums all CFO items + all CFI items from the per-asset
    entry.

    Returns ``{key: [period_values]}`` where key is
    ``"LandCo_FCFF"``, ``"DevCo_FCFF"``, ``"AssetCo_FCFF"``.
    """
    flags = module_flags.get(asset_name, {})

    lc_idx   = _find_asset_index(landco_data, asset_name) if flags.get("landco") else None
    dc_idx   = _find_asset_index(devco_data, asset_name) if flags.get("devco") else None
    ac_entry = _find_assetco_entry(assetco_per_asset, asset_name) if flags.get("assetco") else None

    has_lc = lc_idx is not None and bool(landco_data)
    has_dc = dc_idx is not None and bool(devco_data)
    has_ac = ac_entry is not None


    result: Dict[str, List[float]] = {}

    # aaa, LandCo FCFF = sum(CFO items) + sum(CFI items) aaa,
    if has_lc:
        lc_fcff: Optional[List[float]] = None
        for section in _FCFF_SECTIONS:
            row, details = _sum_section_for_asset_in_model(landco_data, section, lc_idx)
            section_total = sum(row) if row else 0
            for iname, itotal in details:
                if abs(itotal) > 0.01:
                    pass
            if row:
                if lc_fcff is None:
                    lc_fcff = list(row)
                else:
                    width = max(len(lc_fcff), len(row))
                    lc_fcff = [
                        (lc_fcff[j] if j < len(lc_fcff) else 0.0)
                        + (row[j] if j < len(row) else 0.0)
                        for j in range(width)
                    ]
        result["LandCo_FCFF"] = lc_fcff or []

        # Also store LandCo CFI (Cashflow from Investments) separately
        lc_cfi, lc_cfi_details = _sum_section_for_asset_in_model(
            landco_data, "Cashflow from Investments", lc_idx)
        result["LandCo_CFI"] = lc_cfi
        lc_cfi_total = sum(lc_cfi) if lc_cfi else 0

    # aaa, DevCo FCFF = sum(CFO items) + sum(CFI items) aaa,
    if has_dc:
        dc_fcff: Optional[List[float]] = None
        for section in _FCFF_SECTIONS:
            row, details = _sum_section_for_asset_in_model(devco_data, section, dc_idx)
            section_total = sum(row) if row else 0
            for iname, itotal in details:
                if abs(itotal) > 0.01:
                    pass
            if row:
                if dc_fcff is None:
                    dc_fcff = list(row)
                else:
                    width = max(len(dc_fcff), len(row))
                    dc_fcff = [
                        (dc_fcff[j] if j < len(dc_fcff) else 0.0)
                        + (row[j] if j < len(row) else 0.0)
                        for j in range(width)
                    ]
        result["DevCo_FCFF"] = dc_fcff or []

        # Also store DevCo CFI (Cashflow from Investments) separately
        dc_cfi, dc_cfi_details = _sum_section_for_asset_in_model(
            devco_data, "Cashflow from Investments", dc_idx)
        result["DevCo_CFI"] = dc_cfi
        dc_cfi_total = sum(dc_cfi) if dc_cfi else 0

    # aaa, AssetCo FCFF = sum(CFO items) + sum(CFI items) aaa,
    if has_ac:
        ac_fcff: Optional[List[float]] = None
        for section in _FCFF_SECTIONS:
            # Exclude acquisition price & transaction costs from CFI
            excl = _ASSETCO_CFI_EXCLUDE if section == "Cashflow from Investments" else None
            row, details = _sum_section_for_assetco(ac_entry.get(section), section, exclude_items=excl)
            section_total = sum(row) if row else 0
            for iname, itotal in details:
                if abs(itotal) > 0.01:
                    pass
            if row:
                if ac_fcff is None:
                    ac_fcff = list(row)
                else:
                    width = max(len(ac_fcff), len(row))
                    ac_fcff = [
                        (ac_fcff[j] if j < len(ac_fcff) else 0.0)
                        + (row[j] if j < len(row) else 0.0)
                        for j in range(width)
                    ]
        result["AssetCo_FCFF"] = ac_fcff or []

    # aaa, CFF Section Diagnostic: show all items at asset index aaa,
    if has_lc:
        _show_cff_items_at_idx(landco_data, lc_idx, "LandCo")
    if has_dc:
        _show_cff_items_at_idx(devco_data, dc_idx, "DevCo")

    # aaa, Land in Kind: prefer LandCo; if LandCo not present, try DevCo aaa,
    lik_values: List[float] = []
    if has_lc:
        lik_values = _extract_land_in_kind_from_model(landco_data, lc_idx)
    elif has_dc:
        lik_values = _extract_land_in_kind_from_model(devco_data, dc_idx)
    if lik_values:
        result["Land_In_Kind"] = lik_values


    return result


# =====================================================================
# 6. Multi-Asset Accumulation
# =====================================================================

def _accumulate_fcff_rows(
    accumulated: Dict[str, List[float]],
    new_rows: Dict[str, List[float]],
):
    """
    Merge *new_rows* into *accumulated* in-place, element-wise addition.
    Keys are like "LandCo_FCFF", "DevCo_FCFF", "AssetCo_FCFF".
    """
    for key, vals in new_rows.items():
        if key not in accumulated:
            accumulated[key] = list(vals)
        else:
            existing = accumulated[key]
            width = max(len(existing), len(vals))
            accumulated[key] = [
                (existing[j] if j < len(existing) else 0.0)
                + (vals[j] if j < len(vals) else 0.0)
                for j in range(width)
            ]


# =====================================================================
# 7. FCFF Construction (from summed CFO + CFI per module)
# =====================================================================

def _pad(row: List[float], n: int) -> List[float]:
    """Ensure *row* has exactly *n* elements."""
    if len(row) >= n:
        return row[:n]
    return row + [0.0] * (n - len(row))


def _zeros(n: int) -> List[float]:
    """Return a zero-filled row of length *n*."""
    return [0.0] * n


def _row_add(*rows: List[float]) -> List[float]:
    """Element-wise sum of multiple rows (all same length)."""
    if not rows:
        return []
    n = len(rows[0])
    return [sum(r[j] for r in rows) for j in range(n)]


def _row_negate(row: List[float]) -> List[float]:
    """Return element-wise negation of a row."""
    return [-v for v in row]


# =====================================================================
# 7a. Interest Rate Profile Reading
# =====================================================================

def _read_interest_rate_profiles(jv_df: pd.DataFrame) -> Dict[str, List[float]]:
    """
    Read interest rate profiles from ``j.jv.interest.rate.profiles`` and
    ``j.jv.interest.rate.values``.

    Returns a dict mapping profile name aa a list of monthly rates (as decimals).
    If the named ranges are absent, returns an empty dict.
    """
    profiles: Dict[str, List[float]] = {}

    profile_names_raw = _read_array(jv_df, JV_INTEREST_PROFILES)
    profile_values_raw = _read_array(jv_df, JV_INTEREST_VALUES)

    if not profile_names_raw or not profile_values_raw:
        # Try dd.jv prefix as fallback
        profile_names_raw = _read_array(jv_df, DD_INTEREST_PROFILES)

    if not profile_names_raw or not profile_values_raw:
        return profiles

    # profile_names_raw could be a flat list of names or a 2D matrix
    # profile_values_raw is a 2D matrix where each row = one profile's rate values
    for i, name in enumerate(profile_names_raw):
        name_str = str(name).strip() if name is not None else ""
        if not name_str or name_str == "0":
            continue

        if i < len(profile_values_raw):
            raw_vals = profile_values_raw[i]
            if isinstance(raw_vals, list):
                rates = [_to_float(v) for v in raw_vals]
            else:
                rates = [_to_float(raw_vals)]

            # Convert annual rates to monthly if they look annual (> 0.5 means %)
            # Rates stored as decimals (e.g. 0.05 = 5%)  use as-is per month
            profiles[name_str] = rates

    return profiles


# =====================================================================
# 7b. Per-Vehicle JV Inputs Resolution
# =====================================================================

def _resolve_vehicle_jv_inputs(
    jv_name: str,
    jv_asset_scenario_names: Optional[list],
) -> dict:
    """
    Resolve JV input parameters for a specific vehicle (jv_name).

    Returns a dict with all financing assumptions, GP/LP splits, fees,
    dates, and capital structure for the vehicle.

    Looks up the per-asset (JVInputs.Asset) row matching jv_name,
    falling back to JVInputs.Global for scalars.
    """
    jv_name_lower = jv_name.lower() if jv_name else ""
    ji = None  # matched asset index

    # Find matching row index in JVInputs.Asset
    if isinstance(jv_asset_scenario_names, list):
        for idx, sn in enumerate(jv_asset_scenario_names):
            if _safe_str_lower(sn) == jv_name_lower:
                ji = idx
                break


    def _get_asset_val(cls, attr: str, default=None):
        """Get per-asset value from JVInputs.Asset at index ji."""
        if ji is None:
            return default
        val = getattr(cls, attr, None)
        if isinstance(val, list) and ji < len(val):
            return val[ji]
        return default

    def _get_global_val(cls, attr: str, default=None):
        """Get scalar value from JVInputs.Global."""
        return getattr(cls, attr, default)

    def _resolve(asset_cls, global_cls, attr: str, default=None):
        """Asset value if available, otherwise Global fallback."""
        v = _get_asset_val(asset_cls, attr)
        if v is not None and v is not pd.NaT and not (isinstance(v, float) and np.isnan(v)):
            return v
        return _get_global_val(global_cls, attr, default)

    def _resolve_new_or_old(asset_cls, global_cls, new_attr: str, old_attr: str, default=0):
        """Try new-name field; fall back to old-name only when new is absent (None/NaN/NaT), not when zero."""
        raw = _resolve(asset_cls, global_cls, new_attr, None)
        if raw is not None and raw is not pd.NaT and not (isinstance(raw, float) and np.isnan(raw)):
            return _to_float(raw)
        return _to_float(_resolve(asset_cls, global_cls, old_attr, default))

    # Capital Structure
    debt_pct = _to_float(_resolve(
        JVInputs.Asset.CapitalStructure,
        JVInputs.Global.CapitalStructure, "debt_", 0))
    equity_pct = _to_float(_resolve(
        JVInputs.Asset.CapitalStructure,
        JVInputs.Global.CapitalStructure, "equity", 0))
    if debt_pct > 1:
        debt_pct /= 100.0
    if equity_pct > 1:
        equity_pct /= 100.0

    # InKindEquity
    # JV-wise: read land_in__kind from the per-JV Asset row (index ji).
    # No global fallback  this flag is strictly JV-wise.
    _lik_asset = _get_asset_val(JVInputs.Asset.InKindEquity, "land_in__kind")
    if _lik_asset is not None and not (isinstance(_lik_asset, float) and np.isnan(_lik_asset)):
        lik_override = _lik_asset
    else:
        lik_override = None
    lik_gp_pct = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "land_in_kind_gp", 0))
    lik_lp_pct = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "land_in_kind_lp", 0))
    lik_gp_contrib = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "gp_contribution", 0))
    lik_lp_contrib = _to_float(_resolve(
        JVInputs.Asset.InKindEquity,
        JVInputs.Global.InKindEquity, "lp_contribution", 0))

    # Normalise percentages
    if lik_gp_pct > 1:
        lik_gp_pct /= 100.0
    if lik_lp_pct > 1:
        lik_lp_pct /= 100.0
    if lik_gp_contrib > 1:
        lik_gp_contrib /= 100.0
    if lik_lp_contrib > 1:
        lik_lp_contrib /= 100.0

    # CashEquity  try active workbook field names first, then legacy
    _gp_raw = _resolve(
        JVInputs.Asset.CashEquity,
        JVInputs.Global.CashEquity, "gp_contribution_", None)
    if _gp_raw is None:
        _gp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "gp_contribution_cash", None)
    if _gp_raw is None:
        _gp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "gp_contribution", 0)
    cash_gp_pct = _to_float(_gp_raw)
    _lp_raw = _resolve(
        JVInputs.Asset.CashEquity,
        JVInputs.Global.CashEquity, "lp_contribution_", None)
    if _lp_raw is None:
        _lp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "lp_contribution_cash", None)
    if _lp_raw is None:
        _lp_raw = _resolve(
            JVInputs.Asset.CashEquity,
            JVInputs.Global.CashEquity, "lp_contribution_others", 0)
    cash_lp_pct = _to_float(_lp_raw)
    if cash_gp_pct > 1:
        cash_gp_pct /= 100.0
    if cash_lp_pct > 1:
        cash_lp_pct /= 100.0

    # ComputedOwnership
    computed_gp_pct = _to_float(_resolve(
        JVInputs.Asset.ComputedOwnership,
        JVInputs.Global.ComputedOwnership, "gp_owernship", 0))
    computed_lp_pct = _to_float(_resolve(
        JVInputs.Asset.ComputedOwnership,
        JVInputs.Global.ComputedOwnership, "lp_ownership_others", 0))
    if computed_gp_pct > 1:
        computed_gp_pct /= 100.0
    if computed_lp_pct > 1:
        computed_lp_pct /= 100.0

    # UserDefinedOwnership  try new field names first
    ownership_override_raw = _resolve(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "ownership_over_ride")
    user_gp_pct = _resolve_new_or_old(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "gp_ownership_input", "gp_ownership")
    user_lp_pct = _resolve_new_or_old(
        JVInputs.Asset.UserDefinedOwnership,
        JVInputs.Global.UserDefinedOwnership, "lp_ownership_input", "lp_ownership_others")
    if user_gp_pct > 1:
        user_gp_pct /= 100.0
    if user_lp_pct > 1:
        user_lp_pct /= 100.0

    # Determine effective ownership branch
    if ownership_override_raw is None:
        _own_override_is_yes = False
    elif isinstance(ownership_override_raw, bool):
        _own_override_is_yes = ownership_override_raw
    elif isinstance(ownership_override_raw, (int, float)):
        _own_override_is_yes = bool(ownership_override_raw)
    else:
        _own_override_is_yes = str(ownership_override_raw).strip().lower() in ("yes", "true", "1")

    if _own_override_is_yes:
        effective_gp_pct = user_gp_pct
        effective_lp_pct = user_lp_pct
    else:
        effective_gp_pct = computed_gp_pct
        effective_lp_pct = computed_lp_pct

    # RoleAllocation
    gp_role = _resolve(
        JVInputs.Asset.RoleAllocation,
        JVInputs.Global.RoleAllocation, "gp")
    lp_role = _resolve(
        JVInputs.Asset.RoleAllocation,
        JVInputs.Global.RoleAllocation, "lp")

    # JVDates
    jv_start_date = _resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates,
        "start_date_based_on_the_earliest_project_acquisition")
    fund_tenure = _to_float(_resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates, "fund_tenure_in_months", 0))
    fund_close_date = _resolve(
        JVInputs.Asset.JVDates,
        JVInputs.Global.JVDates,
        "end_date_based_on_the_last_exit_of_the_assets")

    # FinancingAssumptions_Loan1 (Term Loan 1)
    # Try new _tl1 suffixed field names first, fall back to legacy generic names
    tl1_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "start_date_tl1")
    if tl1_start is None:
        tl1_start = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "start_date")
    tl1_tenure = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "tenure_tl1", "tenure")
    tl1_end = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_datetl1")
    if tl1_end is None:
        tl1_end = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_date")
    tl1_amort_duration = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "amortization_durationtl1", "amortization_duration")
    tl1_annual_amort = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "annual_amortizationtl1", "annual_amortization")
    tl1_balloon = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "balloon_paymenttl1", "balloon_payment")
    tl1_interest_cap = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_capitalization_")
    tl1_interest_profile = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile_tl1")
    if tl1_interest_profile is None:
        tl1_interest_profile = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile")
    tl1_arr_fee = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_tl1", "arrangement_fees")
    tl1_commit_fee = _to_float(_resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "commitment_fees", 0))
    tl1_refinancing = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "refinacning")
    tl1_repay_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "repayment_start_date_tl1")
    if tl1_repay_start is None:
        tl1_repay_start = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "repayment_start_date")
    tl1_arr_fee_cap = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization_tl1")
    if tl1_arr_fee_cap is None:
        tl1_arr_fee_cap = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization_")
    if tl1_arr_fee_cap is None:
        tl1_arr_fee_cap = _resolve(
            JVInputs.Asset.FinancingAssumptions_Loan1,
            JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_fees_capitalization")

    # Normalise fee percentages
    if tl1_arr_fee > 1:
        tl1_arr_fee /= 100.0
    if tl1_commit_fee > 1:
        tl1_commit_fee /= 100.0
    if tl1_annual_amort > 1:
        tl1_annual_amort /= 100.0
    if tl1_balloon > 1:
        tl1_balloon /= 100.0


    # aaa, Refinancing fields aaa,
    # Workbook class: FinancingAssumptions-Loan1 (Python: FinancingAssumptions_Loan1)
    # All refinancing fields live in the same class as TL1 fields.
    # Primary source: FinancingAssumptions_Loan1 with _refinancing suffix.
    # Fallback: RefinancingAssumptions class (backward compat only).

    # start_date_refinancing
    tl2_start = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "start_date_refinancing")
    if tl2_start is None:
        tl2_start = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "start_date_refinancing")
    if tl2_start is None:
        tl2_start = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "start_date")
    # Derive from TL1 loan_end_datetl1 if refi flag is on but start missing
    if tl2_start is None and str(tl1_refinancing or "").strip().lower() in ("yes", "true", "1"):
        if tl1_end is not None:
            tl2_start = tl1_end

    # tenure__refinancing
    tl2_tenure = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "tenure__refinancing", "__skip__")
    if tl2_tenure == 0:
        tl2_tenure = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "tenure__refinancing", "tenure")

    # loan_end_date_refinancing
    tl2_end = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "loan_end_date_refinancing")
    if tl2_end is None:
        tl2_end = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "loan_end_date_refinancing")
    if tl2_end is None:
        tl2_end = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "loan_end_date")

    # amortizationrefinancing
    tl2_amort_duration = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "amortizationrefinancing", "__skip__")
    if tl2_amort_duration == 0:
        tl2_amort_duration = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "amortizationrefinancing", "amortization_duration")

    # annual_amortizationrefinancing
    tl2_annual_amort = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "annual_amortizationrefinancing", "__skip__")
    if tl2_annual_amort == 0:
        tl2_annual_amort = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "annual_amortizationrefinancing", "annual_amortization")

    # balloon_payment_refinancing
    tl2_balloon = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "balloon_payment_refinancing", "__skip__")
    if tl2_balloon == 0:
        tl2_balloon = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "balloon_payment_refinancing", "balloon_payment")

    # interest_rate_profile___refinancing
    tl2_interest_profile = _resolve(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "interest_rate_profile___refinancing")
    if tl2_interest_profile is None:
        tl2_interest_profile = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "interest_rate_profile___refinancing")
    if tl2_interest_profile is None:
        tl2_interest_profile = _resolve(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "interest_rate_profile")

    # arrangement_feesrefinancing
    tl2_arr_fee = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "arrangement_feesrefinancing", "__skip__")
    if tl2_arr_fee == 0:
        tl2_arr_fee = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "arrangement_feesrefinancing", "arrangement_fees")

    # commitment_fees (shared field name)
    tl2_commit_fee = _to_float(_resolve(
        JVInputs.Asset.RefinancingAssumptions,
        JVInputs.Global.RefinancingAssumptions, "commitment_fees", 0))

    # ltv (RefinancingAssumptions only)
    tl2_ltv = _to_float(_resolve(
        JVInputs.Asset.RefinancingAssumptions,
        JVInputs.Global.RefinancingAssumptions, "ltv", 0))

    # min_dscrrefinancing
    tl2_min_dscr = _resolve_new_or_old(
        JVInputs.Asset.FinancingAssumptions_Loan1,
        JVInputs.Global.FinancingAssumptions_Loan1, "min_dscrrefinancing", "__skip__")
    if tl2_min_dscr == 0:
        tl2_min_dscr = _resolve_new_or_old(
            JVInputs.Asset.RefinancingAssumptions,
            JVInputs.Global.RefinancingAssumptions, "min_dscrrefinancing", "min_dscr")

    if tl2_arr_fee > 1:
        tl2_arr_fee /= 100.0
    if tl2_commit_fee > 1:
        tl2_commit_fee /= 100.0
    if tl2_annual_amort > 1:
        tl2_annual_amort /= 100.0
    if tl2_balloon > 1:
        tl2_balloon /= 100.0
    if tl2_ltv > 1:
        tl2_ltv /= 100.0


    # Fees Definition
    jv_setup_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition,
        "jv_setup_structuring__acquisition_fees", 0))
    jv_liquidation_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition,
        "jv_liquidation__exit_related_fees", 0))
    other_fees = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition, "other_fees", 0))
    fund_mgmt_fee = _to_float(_resolve(
        JVInputs.Asset.FeesDefinition,
        JVInputs.Global.FeesDefinition, "fund_management_exp", 0))

    # Normalise fee percentages (Excel may store as e.g. 1 meaning 1%)
    if jv_setup_fee > 1:
        jv_setup_fee /= 100.0
    if jv_liquidation_fee > 1:
        jv_liquidation_fee /= 100.0
    if other_fees > 1:
        other_fees /= 100.0
    if fund_mgmt_fee > 1:
        fund_mgmt_fee /= 100.0

    # Fees Allocation (GP/LP split of fees)
    fee_alloc_setup = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation,
        "jv_setup_structuring__acquisition_fees", 0))
    fee_alloc_liq = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation,
        "jv_liquidation__exit_related_fees", 0))
    fee_alloc_other = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation, "other_fees", 0))
    fee_alloc_mgmt = _to_float(_resolve(
        JVInputs.Asset.FeesAllocation,
        JVInputs.Global.FeesAllocation, "fund_management_exp", 0))

    # PreferredReturnsandCatchup
    pref_dist_frequency = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "distribution_frequency")
    pref_return_type = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "preferred_return_type")
    pref_return_rate = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "preferred_return", 0))
    gp_cf_during_pref = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_cashflow_duringpreferred_return", 0))
    gp_promote_raw = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_promote_", 0))
    gp_promote_post_pref = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup,
        "gp_promote_post_preferred", 0))
    # Use gp_promote_ as fallback for gp_promote_post_pref if latter is zero
    if gp_promote_post_pref == 0 and gp_promote_raw > 0:
        gp_promote_post_pref = gp_promote_raw
    catchup_enabled = _resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "catchup_enabled")
    catchup_pct = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "catch_up_", 0))
    gp_cashflows_during_catchup = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "gp_cashflows_during_catch_up", 0))
    lp_cashflows_during_catchup = _to_float(_resolve(
        JVInputs.Asset.PreferredReturnsandCatchup,
        JVInputs.Global.PreferredReturnsandCatchup, "lp_cashflows_during_catch_up", 0))

    # Normalise pref rate and promote percentages
    if pref_return_rate > 1:
        pref_return_rate /= 100.0
    if gp_cf_during_pref > 1:
        gp_cf_during_pref /= 100.0
    if gp_promote_raw > 1:
        gp_promote_raw /= 100.0
    if gp_promote_post_pref > 1:
        gp_promote_post_pref /= 100.0
    if catchup_pct > 1:
        catchup_pct /= 100.0
    if gp_cashflows_during_catchup > 1:
        gp_cashflows_during_catchup /= 100.0
    if lp_cashflows_during_catchup > 1:
        lp_cashflows_during_catchup /= 100.0

    # Tier 1  try new field names first, fall back to legacy
    # Try irr__tier_1 first, then t1_irr_, then irr_ (legacy)
    _t1_irr_new = _to_float(_resolve(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "irr__tier_1", None))
    if _t1_irr_new is not None and _t1_irr_new != 0:
        tier1_irr = _t1_irr_new
    else:
        tier1_irr = _resolve_new_or_old(
            JVInputs.Asset.Tier1,
            JVInputs.Global.Tier1, "t1_irr_", "irr_")
    tier1_lp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "lp_share___tier_1", "lp_share")
    tier1_gp_promote = _resolve_new_or_old(
        JVInputs.Asset.Tier1,
        JVInputs.Global.Tier1, "gp_promote___tier_1", "gp_promote")
    if tier1_irr > 1:
        tier1_irr /= 100.0
    if tier1_lp_share > 1:
        tier1_lp_share /= 100.0
    if tier1_gp_promote > 1:
        tier1_gp_promote /= 100.0

    # Tier 2  try new field names first, fall back to legacy
    # Try irr__tier_2 first, then t2_irr_, then irr_ (legacy)
    _t2_irr_new = _to_float(_resolve(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "irr__tier_2", None))
    if _t2_irr_new is not None and _t2_irr_new != 0:
        tier2_irr = _t2_irr_new
    else:
        tier2_irr = _resolve_new_or_old(
            JVInputs.Asset.Tier2,
            JVInputs.Global.Tier2, "t2_irr_", "irr_")
    tier2_lp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "lp_share___tier_2", "lp_share")
    tier2_gp_promote = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "gp_promote___tier_2", "gp_promote")
    if tier2_irr > 1:
        tier2_irr /= 100.0
    if tier2_lp_share > 1:
        tier2_lp_share /= 100.0
    if tier2_gp_promote > 1:
        tier2_gp_promote /= 100.0

    # Tier 3 - resides on Tier2 class (lp_share___tier_3 / gp_promote___tier_3)
    # Workbook contract: LP = lp_share___tier_3, GP = gp_promote___tier_3
    tier3_lp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "lp_share___tier_3", "lp_share___tier_3")
    tier3_gp_share = _resolve_new_or_old(
        JVInputs.Asset.Tier2,
        JVInputs.Global.Tier2, "gp_promote___tier_3", "gp_share___tier_3")
    if tier3_lp_share > 1:
        tier3_lp_share /= 100.0
    if tier3_gp_share > 1:
        tier3_gp_share /= 100.0
    _t3_share_sum = tier3_lp_share + tier3_gp_share
    if abs(_t3_share_sum - 1.0) > 0.01:
        pass

    result = {
        "debt_pct": debt_pct,
        "equity_pct": equity_pct,
        "lik_override": lik_override,
        "lik_gp_pct": lik_gp_pct,
        "lik_lp_pct": lik_lp_pct,
        "lik_gp_contrib": lik_gp_contrib,
        "lik_lp_contrib": lik_lp_contrib,
        "cash_gp_pct": cash_gp_pct,
        "cash_lp_pct": cash_lp_pct,
        "ownership_override": _own_override_is_yes,
        "computed_gp_pct": computed_gp_pct,
        "computed_lp_pct": computed_lp_pct,
        "user_gp_pct": user_gp_pct,
        "user_lp_pct": user_lp_pct,
        "effective_gp_pct": effective_gp_pct,
        "effective_lp_pct": effective_lp_pct,
        "gp_role": gp_role,
        "lp_role": lp_role,
        "jv_start_date": jv_start_date,
        "fund_tenure": fund_tenure,
        "fund_close_date": fund_close_date,
        # TL1
        "tl1_start": tl1_start,
        "tl1_tenure": tl1_tenure,
        "tl1_end": tl1_end,
        "tl1_amort_duration": tl1_amort_duration,
        "tl1_annual_amort": tl1_annual_amort,
        "tl1_balloon": tl1_balloon,
        "tl1_interest_cap": tl1_interest_cap,
        "tl1_interest_profile": tl1_interest_profile,
        "tl1_arr_fee": tl1_arr_fee,
        "tl1_commit_fee": tl1_commit_fee,
        "tl1_refinancing": tl1_refinancing,
        "tl1_repay_start": tl1_repay_start,
        "tl1_arr_fee_cap": tl1_arr_fee_cap,
        # TL2 (Refinancing)
        "tl2_start": tl2_start,
        "tl2_tenure": tl2_tenure,
        "tl2_end": tl2_end,
        "tl2_amort_duration": tl2_amort_duration,
        "tl2_annual_amort": tl2_annual_amort,
        "tl2_balloon": tl2_balloon,
        "tl2_interest_profile": tl2_interest_profile,
        "tl2_arr_fee": tl2_arr_fee,
        "tl2_commit_fee": tl2_commit_fee,
        "tl2_ltv": tl2_ltv,
        "tl2_min_dscr": tl2_min_dscr,
        # Fees
        "jv_setup_fee": jv_setup_fee,
        "jv_liquidation_fee": jv_liquidation_fee,
        "other_fees": other_fees,
        "fund_mgmt_fee": fund_mgmt_fee,
        "fee_alloc_setup": fee_alloc_setup,
        "fee_alloc_liq": fee_alloc_liq,
        "fee_alloc_other": fee_alloc_other,
        "fee_alloc_mgmt": fee_alloc_mgmt,
        # Preferred Returns & Catchup
        "pref_dist_frequency": pref_dist_frequency,
        "pref_return_type": pref_return_type,
        "pref_return_rate": pref_return_rate,
        "gp_cf_during_pref": gp_cf_during_pref,
        "gp_promote_raw": gp_promote_raw,
        "gp_promote_post_pref": gp_promote_post_pref,
        "catchup_enabled": catchup_enabled,
        "catchup_pct": catchup_pct,
        "gp_cashflows_during_catchup": gp_cashflows_during_catchup,
        "lp_cashflows_during_catchup": lp_cashflows_during_catchup,
        # Tier 1
        "tier1_irr": tier1_irr,
        "tier1_lp_share": tier1_lp_share,
        "tier1_gp_promote": tier1_gp_promote,
        # Tier 2
        "tier2_irr": tier2_irr,
        "tier2_lp_share": tier2_lp_share,
        "tier2_gp_promote": tier2_gp_promote,
        # Tier 3
        "tier3_lp_share": tier3_lp_share,
        "tier3_gp_share": tier3_gp_share,
    }

    for k, v in result.items():
        pass

    return result


# =====================================================================
# 7c. CFF Computation (Cashflow from Financing)
# =====================================================================

def _date_to_month_index(
    date_val, model_start: Optional[pd.Timestamp],
) -> Optional[int]:
    """
    Convert a date value to a 0-based month index relative to model_start.
    Returns None if date_val or model_start is not usable.
    """
    if date_val is None or model_start is None:
        return None
    try:
        ts = pd.Timestamp(date_val)
        if pd.isna(ts):
            return None
        # Month difference: (year_diff * 12) + month_diff
        return (ts.year - model_start.year) * 12 + (ts.month - model_start.month)
    except Exception:
        return None


def _get_monthly_rate(
    interest_profiles: Dict[str, List[float]],
    profile_name: Optional[str],
    period: int,
) -> float:
    """
    Look up the monthly interest rate for a given period from the profiles.
    If the profile is not found, returns 0.0.
    Profile rates are stored as annual decimals (year-wise); divide by 12
    for monthly.  ``period`` is the month offset from loan start;
    the year index is ``period // 12``.
    """
    if not profile_name or not interest_profiles:
        return 0.0
    name_str = str(profile_name).strip()
    rates = interest_profiles.get(name_str, [])
    if not rates:
        return 0.0
    # Rates are year-wise  one entry per year.  Map month to year index.
    year_idx = period // 12 if period >= 0 else 0
    idx = min(year_idx, len(rates) - 1)
    annual_rate = _to_float(rates[idx])
    return annual_rate / 12.0


def _compute_term_loan(
    max_periods: int,
    funding_req_debt: List[float],
    model_start: Optional[pd.Timestamp],
    loan_start,
    loan_tenure: float,
    loan_end,
    repay_start_date,
    amort_duration: float,
    annual_amort: float,
    balloon_pct: float,
    interest_cap: Optional[str],
    interest_profile_name: Optional[str],
    arr_fee_pct: float,
    arr_fee_capitalize: Optional[str],
    commit_fee_pct: float,
    fund_end_idx: Optional[int],
    interest_profiles: Dict[str, List[float]],
    equity_pct: float = 0.0,
) -> Dict[str, List[float]]:
    """
    Compute a two-phase term loan schedule.

    Phase 1  Construction (loan_start aa a repay_start):
      - Draws from funding_req_debt (positive = cash needed)
      - Interest is capitalized if interest_cap = Yes
      - Arrangement fees capitalized if arr_fee_capitalize = Yes

    Phase 2  Repayment (repay_start aa a loan_end):
      - No new draws
      - Interest is paid as cashflow (not capitalized)
      - Amortization repayments begin
      - Balloon payment at min(loan_end, fund_end) clears remaining balance

    Output schedule rows:
      Opening Balance, Loan Additions, Capitalized Interest,
      Capitalized Arrangement Fees, Repayments, Closing Balance,
      Equity Infusion for Interest, Equity Infusion for Arrangement Fees.
    """
    principal_drawn = _zeros(max_periods)
    principal_repaid = _zeros(max_periods)
    interest_paid = _zeros(max_periods)
    arrangement_fees = _zeros(max_periods)
    commitment_fees = _zeros(max_periods)
    outstanding = _zeros(max_periods)

    # Debt schedule rows
    opening_bal = _zeros(max_periods)
    loan_additions = _zeros(max_periods)
    cap_interest = _zeros(max_periods)
    cap_arr_fees = _zeros(max_periods)
    repayments = _zeros(max_periods)
    closing_bal = _zeros(max_periods)
    eq_infusion_interest = _zeros(max_periods)
    eq_infusion_arr_fees = _zeros(max_periods)

    # Separate balloon tracking
    balloon_payment = _zeros(max_periods)

    # Arrangement fee incurred (always shows fee amount, regardless of capitalization)
    arr_fee_incurred = _zeros(max_periods)

    # Diagnostic / validation rows for printed schedule
    interest_incurred = _zeros(max_periods)
    interest_rate_applied = _zeros(max_periods)
    amort_pct_applied = _zeros(max_periods)

    # Resolve loan start/end/repay_start as month indices
    start_idx = _date_to_month_index(loan_start, model_start)
    end_idx = _date_to_month_index(loan_end, model_start)
    repay_idx = _date_to_month_index(repay_start_date, model_start)


    # If no explicit start, find first period with positive funding req
    if start_idx is None:
        for t in range(max_periods):
            if funding_req_debt[t] > 0.01:
                start_idx = t
                break

    _empty_result = {
        "principal_drawn": principal_drawn,
        "principal_repaid": principal_repaid,
        "interest_paid": interest_paid,
        "arrangement_fees": arrangement_fees,
        "commitment_fees": commitment_fees,
        "outstanding_balance": outstanding,
        "opening_balance": opening_bal,
        "loan_additions": loan_additions,
        "capitalized_interest": cap_interest,
        "capitalized_arr_fees": cap_arr_fees,
        "repayments": repayments,
        "closing_balance": closing_bal,
        "eq_infusion_interest": eq_infusion_interest,
        "eq_infusion_arr_fees": eq_infusion_arr_fees,
        "interest_incurred": interest_incurred,
        "interest_rate_applied": interest_rate_applied,
        "amort_pct_applied": amort_pct_applied,
        "balloon_payment": balloon_payment,
        "arr_fee_incurred": arr_fee_incurred,
    }

    if start_idx is None:
        return _empty_result

    # If no explicit end, compute from tenure
    if end_idx is None and loan_tenure > 0:
        end_idx = start_idx + int(loan_tenure)
    if end_idx is None:
        end_idx = max_periods - 1
    end_idx = min(end_idx, max_periods - 1)

    # Repayment start: capitalization period = tenure - amortization_duration.
    # Amortization (repayment) occurs during the LAST amort_duration of the loan.
    if repay_idx is None:
        if amort_duration > 0:
            if end_idx is not None and start_idx is not None:
                # Derive from known start/end month indices (reliable when dates are provided)
                total_months = end_idx - start_idx
                # Heuristic: if amort_duration is small relative to total loan
                # months, it is likely expressed in years aa a convert to months
                if total_months > 12 and amort_duration <= total_months / 12:
                    amort_m = int(amort_duration * 12)
                else:
                    amort_m = int(amort_duration)
                repay_idx = max(end_idx - amort_m, start_idx)
            elif loan_tenure > 0:
                # Fallback: compute cap = tenure - amort (same units)
                cap_dur = max(loan_tenure - amort_duration, 0)
                repay_idx = start_idx + int(cap_dur)
            else:
                repay_idx = start_idx
        else:
            repay_idx = end_idx  # no amort aa a balloon only at end

    capitalize_interest = (
        str(interest_cap).strip().lower() in ("yes", "true", "1")
        if interest_cap is not None else False
    )
    # Business rule: if no explicit flag but repayment starts later than
    # loan start, interest capitalizes during the construction phase
    # (from start until repayment start).
    if not capitalize_interest and interest_cap is None:
        if repay_idx is not None and start_idx is not None and repay_idx > start_idx:
            capitalize_interest = True

    capitalize_arr_fee = (
        str(arr_fee_capitalize).strip().lower() in ("yes", "true", "1")
        if arr_fee_capitalize is not None else False
    )

    monthly_amort_rate = annual_amort / 12.0 if annual_amort > 0 else 0.0

    # Balloon payment index: min(loan_end, fund_end)
    balloon_idx = end_idx
    if fund_end_idx is not None and fund_end_idx < balloon_idx:
        balloon_idx = fund_end_idx
    balloon_idx = min(balloon_idx, max_periods - 1)


    total_drawn = 0.0

    # Accumulate any unfunded debt requirement from before loan start
    # so it gets drawn as a lump sum when the loan begins
    accumulated_prior_debt = 0.0
    if start_idx > 0:
        for i in range(start_idx):
            if funding_req_debt[i] > 0.01:
                accumulated_prior_debt += funding_req_debt[i]
        if accumulated_prior_debt > 0.01:
            pass

    for t in range(max_periods):
        prev_outstanding = outstanding[t - 1] if t > 0 else 0.0
        opening_bal[t] = prev_outstanding

        if t < start_idx or t > end_idx:
            outstanding[t] = prev_outstanding
            closing_bal[t] = outstanding[t]
            continue

        # aaa, Draw phase: only before repayment start aaa,
        draw = 0.0
        if t < repay_idx:
            period_need = funding_req_debt[t] if funding_req_debt[t] > 0.01 else 0.0
            # At loan start, also draw accumulated unfunded prior debt
            if t == start_idx and accumulated_prior_debt > 0.01:
                period_need += accumulated_prior_debt
            if period_need > 0.01:
                draw = period_need
                principal_drawn[t] = draw
                loan_additions[t] = draw
                total_drawn += draw

        # aaa, Arrangement fee on drawdown aaa,
        if draw > 0 and arr_fee_pct > 0:
            fee = draw * arr_fee_pct
            arr_fee_incurred[t] = fee    # always record incurred amount
            if capitalize_arr_fee:
                # Capitalized: increases loan balance, NOT a cash outflow
                cap_arr_fees[t] = fee
                arrangement_fees[t] = 0.0  # no cash paid
                # No equity infusion  fee is capitalised into debt, no cash leaves
                eq_infusion_arr_fees[t] = 0.0
            else:
                # Not capitalized: cash outflow, does NOT increase loan balance
                arrangement_fees[t] = fee
                cap_arr_fees[t] = 0.0

        # aaa, Interest calculation aaa,
        balance_for_interest = prev_outstanding + loan_additions[t] + cap_arr_fees[t]
        monthly_rate = _get_monthly_rate(
            interest_profiles, interest_profile_name, t - start_idx,
        )
        period_interest = balance_for_interest * monthly_rate

        # Store diagnostic values
        interest_incurred[t] = period_interest
        interest_rate_applied[t] = monthly_rate * 12.0   # annual rate for display

        if t < repay_idx and capitalize_interest:
            # aaa, Capitalization phase: interest increases balance, NOT paid aaa,
            cap_interest[t] = period_interest
            interest_paid[t] = 0.0                       # explicitly zero during cap
            outstanding[t] = prev_outstanding + loan_additions[t] + cap_arr_fees[t] + period_interest
            # No equity infusion  interest is capitalised into debt, no cash leaves
            eq_infusion_interest[t] = 0.0
        else:
            # aaa, Payment phase: interest is cash-paid, NOT capitalized aaa,
            cap_interest[t] = 0.0
            interest_paid[t] = period_interest
            outstanding[t] = prev_outstanding + loan_additions[t] + cap_arr_fees[t]

        # aaa, Commitment fee aaa,
        if commit_fee_pct > 0 and outstanding[t] > 0:
            commitment_fees[t] = outstanding[t] * (commit_fee_pct / 12.0)

        # aaa, Amortization repayments (repayment phase only) aaa,
        if t >= repay_idx and monthly_amort_rate > 0 and outstanding[t] > 0:
            repay = total_drawn * monthly_amort_rate
            repay = min(repay, outstanding[t])
            principal_repaid[t] = repay
            repayments[t] = repay
            outstanding[t] -= repay
            amort_pct_applied[t] = monthly_amort_rate * 12.0   # annualised for display

        # aaa, Balloon payment at min(loan_end, fund_end) aaa,
        if t == balloon_idx and outstanding[t] > 0:
            balloon_amount = outstanding[t]
            balloon_payment[t] = balloon_amount
            principal_repaid[t] += balloon_amount
            repayments[t] += balloon_amount
            outstanding[t] = 0.0

        closing_bal[t] = outstanding[t]


    return {
        "principal_drawn": principal_drawn,
        "principal_repaid": principal_repaid,
        "interest_paid": interest_paid,
        "arrangement_fees": arrangement_fees,
        "commitment_fees": commitment_fees,
        "outstanding_balance": outstanding,
        "opening_balance": opening_bal,
        "loan_additions": loan_additions,
        "capitalized_interest": cap_interest,
        "capitalized_arr_fees": cap_arr_fees,
        "repayments": repayments,
        "closing_balance": closing_bal,
        "eq_infusion_interest": eq_infusion_interest,
        "eq_infusion_arr_fees": eq_infusion_arr_fees,
        "interest_incurred": interest_incurred,
        "interest_rate_applied": interest_rate_applied,
        "amort_pct_applied": amort_pct_applied,
        "balloon_payment": balloon_payment,
        "arr_fee_incurred": arr_fee_incurred,
    }


def _compute_cff(
    total_fcf: List[float],
    land_in_kind: List[float],
    max_periods: int,
    vehicle_inputs: dict,
    interest_profiles: Dict[str, List[float]],
    model_start: Optional[pd.Timestamp],
) -> Dict[str, List[float]]:
    """
    Compute the full Cashflow from Financing section including:
      - Fund-related expenses
      - Funding requirement (debt / equity split)
      - Term Loan 1 (drawdown from funding requirement)
      - Term Loan 2 / Refinancing (draws from TL1 outstanding at refi start)
      - Financing cost summary
      - Equity infusion (equity portion of funding requirement)
      - Preferred return schedule (cumulative unreturned capital based)
      - LP / GP distribution waterfall (sequential: pref aa a return of capital)
      - Cash schedule (opening aa a net aa a closing with reconciliation)

    Returns a dict of label aa a data rows for all CFF line items.
    """
    vi = vehicle_inputs
    debt_pct = vi["debt_pct"]
    equity_pct = vi["equity_pct"]

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # A. Fund-related expenses
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Pre-resolve JV start index (needed by setup fee placement below
    # and later by section B-pre).
    jv_start = vi.get("jv_start_date")
    jv_start_idx = _date_to_month_index(jv_start, model_start)

    jv_setup_fees = _zeros(max_periods)
    # NOTE: fund_mgmt_exp is resolved in vehicle_inputs as vi["fund_mgmt_fee"]
    # but is NOT yet consumed here.  The row remains zero until the fund
    # management expense logic is implemented.  Step 7d (Fees output) also
    # does not currently apply this value.
    fund_mgmt_exp = _zeros(max_periods)
    other_fees_row = _zeros(max_periods)
    pm_fees = _zeros(max_periods)
    jv_liq_fees = _zeros(max_periods)

    # Setup fee: percentage of land acquisition cost at JV start date
    if vi["jv_setup_fee"] > 0:
        _setup_fee_base = sum(abs(_to_float(v)) for v in land_in_kind) if land_in_kind else 0.0
        _setup_amount = vi["jv_setup_fee"] * _setup_fee_base
        if _setup_amount > 0:
            _sf_idx = jv_start_idx if jv_start_idx is not None and 0 <= jv_start_idx < max_periods else None
            if _sf_idx is None:
                for t in range(max_periods):
                    if abs(total_fcf[t]) > 0.01:
                        _sf_idx = t
                        break
            if _sf_idx is not None:
                jv_setup_fees[_sf_idx] = -abs(_setup_amount)

    # Liquidation fee: one-time in last period with cashflow
    if vi["jv_liquidation_fee"] > 0:
        for t in range(max_periods - 1, -1, -1):
            if abs(total_fcf[t]) > 0.01:
                jv_liq_fees[t] = -abs(vi["jv_liquidation_fee"])
                break

    total_fund_expenses = _row_add(jv_setup_fees, fund_mgmt_exp,
                                   other_fees_row, pm_fees, jv_liq_fees)
    total_fcf_before_fin = _row_add(total_fcf, total_fund_expenses)

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # B-pre. JV window & fund end index (needed before debt base)
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    fund_end_idx = None
    fund_tenure = vi.get("fund_tenure", 0)
    # jv_start / jv_start_idx already resolved in section A above
    jv_end_idx = None
    if jv_start_idx is not None and fund_tenure > 0:
        jv_end_idx = jv_start_idx + int(fund_tenure)
        fund_end_idx = jv_end_idx
        if fund_end_idx >= max_periods:
            fund_end_idx = max_periods - 1

    # Also resolve fund close date (end_date_based_on_the_last_exit_of_the_assets)
    _fund_close_raw = vi.get("fund_close_date")
    fund_close_idx = _date_to_month_index(_fund_close_raw, model_start)
    if fund_close_idx is not None:
        if fund_close_idx >= max_periods:
            fund_close_idx = max_periods - 1
        # Cap fund_end_idx at fund close date if it comes earlier
        if fund_end_idx is None:
            fund_end_idx = fund_close_idx
        else:
            fund_end_idx = min(fund_end_idx, fund_close_idx)

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # B. Debt base = "Total FCFF before Financing and SPV Related Cost - JV"
    #    This is the ONLY source for debt sizing.
    #    Fees (setup, liquidation, arrangement, commitment) are equity-only
    #    and must NOT be included in the debt base.
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    # Step 1: Apply JV date window to total_fcf (same logic as 7b cashflows)
    _windowed_fcf = [0.0] * max_periods
    _w_start = jv_start_idx if jv_start_idx is not None else 0
    _w_end = jv_end_idx if jv_end_idx is not None else max_periods
    for t in range(max(_w_start, 0), min(_w_end, max_periods)):
        _windowed_fcf[t] = _to_float(total_fcf[t])

    # Step 2: Determine LIK flag (same robust logic as 7c)
    _lik_flag = vi.get("lik_override")
    if _lik_flag is None:
        _lik_is_yes_cff = False
    elif isinstance(_lik_flag, bool):
        _lik_is_yes_cff = _lik_flag
    elif isinstance(_lik_flag, (int, float)):
        _lik_is_yes_cff = bool(_lik_flag)
    else:
        _lik_is_yes_cff = str(_lik_flag).strip().lower() in ("yes", "true", "1")

    # Step 3: Build debt_base = windowed_fcf + land_cost
    # When LIK = Yes the land is contributed in-kind (non-cash) and must NOT
    # be included in the funding requirement.  Only include when LIK = No.
    _land_cost_for_debt = [0.0] * max_periods
    if not _lik_is_yes_cff:
        if jv_start_idx is not None and 0 <= jv_start_idx < max_periods:
            _lik_sum = sum(_to_float(v) for v in land_in_kind)
            # Convention: land costs are always negative (outflow)
            _land_cost_for_debt[jv_start_idx] = -abs(_lik_sum) if _lik_sum != 0 else 0.0
    debt_base = _row_add(_windowed_fcf, _land_cost_for_debt)

    # Step 4: Period-wise debt funding requirement (NO cumulative gating)
    # If debt_base[t] < 0: funding needed = abs(debt_base[t])
    # If debt_base[t] >= 0: no debt needed
    funding_req = _zeros(max_periods)
    for t in range(max_periods):
        if debt_base[t] < 0:
            funding_req[t] = abs(debt_base[t])

    debt_funding = [v * debt_pct for v in funding_req]
    # Equity funding from the same base (residual after debt)  fees excluded,
    # fees will be covered separately by equity when that section is built.
    equity_funding = [v * equity_pct for v in funding_req]

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # C. (moved to B-pre above  JV window & fund end index)
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # D-pre. Refinancing flag & TL1 end-date adjustment
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    refi_enabled = str(vi.get("tl1_refinancing") or "").strip().lower() in (
        "yes", "true", "1",
    )
    tl2_start_idx = _date_to_month_index(vi["tl2_start"], model_start)

    # When refinancing is enabled, TL1 must NOT pay its balloon before the
    # refi date  otherwise TL1 outstanding at refi = 0 and TL2 draws nothing.
    # Extend TL1's effective end past the refi start so the balloon is deferred.
    tl1_effective_end = vi["tl1_end"]
    if refi_enabled and tl2_start_idx is not None:
        _tl1_end_idx_pre = _date_to_month_index(vi["tl1_end"], model_start)
        if _tl1_end_idx_pre is None or _tl1_end_idx_pre <= tl2_start_idx:
            try:
                tl1_effective_end = pd.Timestamp(vi["tl2_start"]) + pd.DateOffset(months=1)
            except Exception:
                tl1_effective_end = vi["tl1_end"]

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # D. Term Loan 1
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # When refi is enabled, ensure fund_end for TL1 is NOT before
    # the refi date  otherwise TL1 balloons prematurely and TL2 gets zero.
    tl1_fund_end_idx = fund_end_idx
    if refi_enabled and tl2_start_idx is not None and tl1_fund_end_idx is not None:
        if tl1_fund_end_idx < tl2_start_idx + 1:
            tl1_fund_end_idx = tl2_start_idx + 1

    tl1 = _compute_term_loan(
        max_periods=max_periods,
        funding_req_debt=debt_funding,
        model_start=model_start,
        loan_start=vi["tl1_start"],
        loan_tenure=vi["tl1_tenure"],
        loan_end=tl1_effective_end,
        repay_start_date=vi.get("tl1_repay_start"),
        amort_duration=vi["tl1_amort_duration"],
        annual_amort=vi["tl1_annual_amort"],
        balloon_pct=vi["tl1_balloon"],
        interest_cap=vi["tl1_interest_cap"],
        interest_profile_name=vi.get("tl1_interest_profile"),
        arr_fee_pct=vi["tl1_arr_fee"],
        arr_fee_capitalize=vi.get("tl1_arr_fee_cap"),
        commit_fee_pct=vi["tl1_commit_fee"],
        fund_end_idx=tl1_fund_end_idx,
        interest_profiles=interest_profiles,
        equity_pct=equity_pct,
    )

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # D. Term Loan 2 / Refinancing
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Refinancing: TL2 draws from TL1 outstanding balance at refi start,
    # repays TL1 outstanding, then TL2 follows its own schedule.

    # Build TL2 funding_req_debt: at refi start, draw = TL1 outstanding * LTV
    tl2_funding = _zeros(max_periods)
    if refi_enabled and tl2_start_idx is not None and 0 <= tl2_start_idx < max_periods:
        tl1_outstanding_at_refi = tl1["outstanding_balance"][tl2_start_idx]
        refi_ltv = vi["tl2_ltv"] if vi["tl2_ltv"] > 0 else 1.0
        refi_draw = tl1_outstanding_at_refi * refi_ltv
        if refi_draw > 0.01:
            tl2_funding[tl2_start_idx] = refi_draw

    tl2 = _compute_term_loan(
        max_periods=max_periods,
        funding_req_debt=tl2_funding,
        model_start=model_start,
        loan_start=vi["tl2_start"],
        loan_tenure=vi["tl2_tenure"],
        loan_end=vi["tl2_end"],
        repay_start_date=None,
        amort_duration=vi["tl2_amort_duration"],
        annual_amort=vi["tl2_annual_amort"],
        balloon_pct=vi["tl2_balloon"],
        interest_cap="No",                              # Refi has NO interest capitalization
        interest_profile_name=vi.get("tl2_interest_profile"),
        arr_fee_pct=vi["tl2_arr_fee"],
        arr_fee_capitalize="No",                        # Refi arrangement fees are NOT capitalized
        commit_fee_pct=vi["tl2_commit_fee"],
        fund_end_idx=fund_end_idx,
        interest_profiles=interest_profiles,
        equity_pct=equity_pct,
    )

    # aaa, Post-process TL1 for refinancing event aaa,
    # At the refi month, TL2 takes out TL1.  Adjust TL1's schedule in-place
    # so that repayments, balances, and interest reflect the full payoff.
    if refi_enabled and tl2_start_idx is not None and 0 <= tl2_start_idx < max_periods:
        _refi_bal = tl1["outstanding_balance"][tl2_start_idx]
        if _refi_bal > 0.01:
            # At refi point: add full payoff to existing amort repayment
            tl1["repayments"][tl2_start_idx] += _refi_bal
            tl1["principal_repaid"][tl2_start_idx] += _refi_bal
            tl1["balloon_payment"][tl2_start_idx] = _refi_bal
            tl1["outstanding_balance"][tl2_start_idx] = 0.0
            tl1["closing_balance"][tl2_start_idx] = 0.0
            # Zero out TL1 after refi  loan is fully taken out
            for _t_adj in range(tl2_start_idx + 1, max_periods):
                for _k_adj in ("opening_balance", "outstanding_balance",
                               "closing_balance", "repayments",
                               "principal_repaid", "loan_additions",
                               "capitalized_interest", "capitalized_arr_fees",
                               "interest_paid", "interest_incurred",
                               "arrangement_fees", "commitment_fees",
                               "principal_drawn", "balloon_payment"):
                    tl1[_k_adj][_t_adj] = 0.0

    # After refi adjustment, tl1["principal_repaid"] already includes the
    # refinancing payoff  no separate tl1_refi_repayment needed.
    tl1_repaid_total = tl1["principal_repaid"]

    # aaa, Cashflow From Financing Activity aaa,
    # Always computed regardless of refinancing flag.
    # Derived from the 4 gross presentation top rows per loan:
    #   Debt Issued (adds + cap_int + cap_arr)       [positive]
    # + Debt Repaid (-principal_repaid)               [negative]
    # + Interest Expense Paid (-(int_paid+cap_int))   [negative]
    # + Arrangement Fees Paid (-(arr_fees+cap_arr))   [negative]
    # Caps cancel aa a net = adds - repaid - int_paid - arr_fees  (CASH ONLY)
    # Interest Expense Capitalized is disclosure only  NOT included.
    cashflow_from_financing_activity = _row_add(
        # --- Term Loan 1 (4 gross top rows) ---
        _row_add(tl1["loan_additions"], tl1["capitalized_interest"],
                 tl1["capitalized_arr_fees"]),                        # Debt Issued
        _row_negate(tl1["principal_repaid"]),                         # Debt Repaid
        _row_negate(_row_add(tl1["interest_paid"],
                             tl1["capitalized_interest"])),           # Interest Expense Paid
        _row_negate(_row_add(tl1["arrangement_fees"],
                             tl1["capitalized_arr_fees"])),           # Arrangement Fees Paid
        # --- Refinancing Facility (4 gross top rows) ---
        _row_add(tl2["loan_additions"], tl2["capitalized_interest"],
                 tl2["capitalized_arr_fees"]),                        # Debt Issued
        _row_negate(tl2["principal_repaid"]),                         # Debt Repaid
        _row_negate(_row_add(tl2["interest_paid"],
                             tl2["capitalized_interest"])),           # Interest Expense Paid
        _row_negate(_row_add(tl2["arrangement_fees"],
                             tl2["capitalized_arr_fees"])),           # Arrangement Fees Paid
    )

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # E. Financing Cost summary
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    total_arr_fees = _row_add(tl1["arrangement_fees"], tl2["arrangement_fees"])
    total_commit_fees = _row_add(tl1["commitment_fees"], tl2["commitment_fees"])
    total_interest = _row_add(tl1["interest_paid"], tl2["interest_paid"])

    net_funding_req = _row_add(
        funding_req,
        _row_negate(total_arr_fees),
        _row_negate(total_commit_fees),
        _row_negate(total_interest),
    )

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # F. Equity infusion (SPV perspective: positive = cash IN)
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # equity_funding is positive (amount needed), which is cash IN to SPV
    equity_infused = list(equity_funding)

    # Net Financing Cashflows (before distributions)
    net_financing_cf = _row_add(
        tl1["principal_drawn"], _row_negate(tl1_repaid_total),
        tl2["principal_drawn"], _row_negate(tl2["principal_repaid"]),
        _row_negate(total_arr_fees), _row_negate(total_commit_fees),
        _row_negate(total_interest),
        equity_infused,
    )

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # G. LP / GP Equity Splits (investor perspective: negative = cash OUT)
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # land_in_kind from model is positive (value of land contributed).
    # From investor perspective, contributions are outflows aa a negate.
    lp_in_kind = [-abs(v) * vi["lik_lp_pct"] for v in land_in_kind]
    gp_in_kind = [-abs(v) * vi["lik_gp_pct"] for v in land_in_kind]
    # equity_funding is positive (amount needed) aa a contributions are negative (cash out from investor)
    lp_cash_equity = [-v * vi["cash_lp_pct"] for v in equity_funding]
    gp_cash_equity = [-v * vi["cash_gp_pct"] for v in equity_funding]
    lp_contributions = _row_add(lp_in_kind, lp_cash_equity)
    gp_contributions = _row_add(gp_in_kind, gp_cash_equity)

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # H + I + J.  Unified cash schedule & distribution waterfall
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Single forward pass: rolling cash balance drives distribution
    # availability.  Distributions reduce closing balance immediately so
    # subsequent periods see the correct opening balance.

    net_cash_pre_dist = _row_add(total_fcf_before_fin, net_financing_cf)

    # Preferred return parameters
    pref_rate_annual = vi.get("pref_return_rate", 0.0)
    pref_rate_monthly = pref_rate_annual / 12.0
    gp_cf_during_pref = vi.get("gp_cf_during_pref", 0.0)

    # Output arrays  preferred
    pref_accrual_lp = _zeros(max_periods)
    pref_paid_lp = _zeros(max_periods)
    pref_unpaid_lp = _zeros(max_periods)

    # Output arrays  return of capital
    roc_lp = _zeros(max_periods)
    roc_gp = _zeros(max_periods)

    # Output arrays  GP during pref
    gp_during_pref = _zeros(max_periods)

    # Output arrays  waterfall tiers
    catchup_lp = _zeros(max_periods)
    catchup_gp = _zeros(max_periods)
    tier1_lp = _zeros(max_periods)
    tier1_gp = _zeros(max_periods)
    tier2_lp = _zeros(max_periods)
    tier2_gp = _zeros(max_periods)
    tier3_lp = _zeros(max_periods)
    tier3_gp = _zeros(max_periods)

    # Output arrays  cash schedule
    opening_balance_final = _zeros(max_periods)
    closing_balance = _zeros(max_periods)
    net_cash = _zeros(max_periods)
    equity_returns = _zeros(max_periods)
    total_distributions_paid = _zeros(max_periods)

    # Cumulative trackers
    cum_lp_capital = 0.0
    cum_lp_roc = 0.0
    cum_pref_unpaid = 0.0

    # Distribution frequency
    dist_freq_str = str(vi.get("pref_dist_frequency") or "Monthly").strip().lower()
    if "quarter" in dist_freq_str:
        dist_interval = 3
    elif "annual" in dist_freq_str or "year" in dist_freq_str:
        dist_interval = 12
    else:
        dist_interval = 1

    # Waterfall parameters (resolve once)
    catchup_en = str(vi.get("catchup_enabled") or "").strip().lower() in (
        "yes", "true", "1",
    )
    catchup_rate = vi.get("catchup_pct", 0.0)
    t1_lp_share = vi.get("tier1_lp_share", 0.0)
    t1_gp_promote_rate = vi.get("tier1_gp_promote", 0.0)
    t2_lp_share = vi.get("tier2_lp_share", 0.0)
    t2_gp_promote_rate = vi.get("tier2_gp_promote", 0.0)
    t3_lp_share = vi.get("tier3_lp_share", 0.0)
    t3_gp_share_rate = vi.get("tier3_gp_share", 0.0)

    for t in range(max_periods):
        # aaa, Cash: opening balance aaa,
        opening_balance_final[t] = closing_balance[t - 1] if t > 0 else 0.0

        # aaa, Cash before distributions aaa,
        cash_before_dist = opening_balance_final[t] + net_cash_pre_dist[t]

        # aaa, LP capital tracking (contributions are negative = outflow) aaa,
        lp_contrib_t = abs(lp_contributions[t]) if lp_contributions[t] < 0 else 0.0
        cum_lp_capital += lp_contrib_t

        # aaa, Preferred accrual aaa,
        unreturned = max(cum_lp_capital - cum_lp_roc, 0.0)
        accrual = unreturned * pref_rate_monthly
        pref_accrual_lp[t] = accrual
        cum_pref_unpaid += accrual

        # aaa, Distribute only on distribution periods aaa,
        is_dist_period = ((t + 1) % dist_interval == 0) or (t == max_periods - 1)
        total_dist_t = 0.0

        if is_dist_period and cash_before_dist > 0.01:
            remaining = cash_before_dist

            # Step 1: Preferred return to LP
            pref_to_pay = min(cum_pref_unpaid, remaining)
            if pref_to_pay > 0.01:
                pref_paid_lp[t] = pref_to_pay
                cum_pref_unpaid -= pref_to_pay
                remaining -= pref_to_pay
                # GP share during pref period
                if gp_cf_during_pref > 0 and remaining > 0:
                    gp_share = min(pref_to_pay * gp_cf_during_pref, remaining)
                    gp_during_pref[t] = gp_share
                    remaining -= gp_share

            # Step 2: Return of Capital to LP
            lp_unreturned = max(cum_lp_capital - cum_lp_roc, 0.0)
            roc_amount = min(lp_unreturned, remaining)
            if roc_amount > 0.01:
                roc_lp[t] = roc_amount
                cum_lp_roc += roc_amount
                remaining -= roc_amount

            # Step 3: Catchup
            if catchup_en and catchup_rate > 0 and remaining > 0.01:
                catchup_amount = remaining * catchup_rate
                catchup_gp[t] = catchup_amount
                catchup_lp[t] = remaining - catchup_amount
                remaining = 0.0

            # Step 4: Tier 1 split
            if remaining > 0.01 and (t1_lp_share > 0 or t1_gp_promote_rate > 0):
                tier1_lp[t] = remaining * t1_lp_share
                tier1_gp[t] = remaining * t1_gp_promote_rate
                remaining -= (tier1_lp[t] + tier1_gp[t])

            # Step 5: Tier 2 split
            if remaining > 0.01 and (t2_lp_share > 0 or t2_gp_promote_rate > 0):
                tier2_lp[t] = remaining * t2_lp_share
                tier2_gp[t] = remaining * t2_gp_promote_rate
                remaining -= (tier2_lp[t] + tier2_gp[t])

            # Step 6: Tier 3 split (residual bucket)
            if remaining > 0.01 and (t3_lp_share > 0 or t3_gp_share_rate > 0):
                tier3_lp[t] = remaining * t3_lp_share
                tier3_gp[t] = remaining * t3_gp_share_rate
                remaining -= (tier3_lp[t] + tier3_gp[t])

            # Total distributions this period
            lp_dist_t = (pref_paid_lp[t] + roc_lp[t] + catchup_lp[t]
                         + tier1_lp[t] + tier2_lp[t] + tier3_lp[t])
            gp_dist_t = (gp_during_pref[t] + roc_gp[t] + catchup_gp[t]
                         + tier1_gp[t] + tier2_gp[t] + tier3_gp[t])
            total_dist_t = lp_dist_t + gp_dist_t

        pref_unpaid_lp[t] = cum_pref_unpaid
        total_distributions_paid[t] = total_dist_t
        equity_returns[t] = total_dist_t

        # aaa, Cash: closing balance (after distributions) aaa,
        net_cash[t] = net_cash_pre_dist[t] - total_dist_t
        closing_balance[t] = opening_balance_final[t] + net_cash[t]

    # Distributions check: closing balance should never be negative
    distributions_check = _zeros(max_periods)
    for t in range(max_periods):
        if closing_balance[t] < -0.01:
            distributions_check[t] = closing_balance[t]

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # K. Assemble all CFF rows
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # LP totals
    total_lp_distributions = _row_add(
        lp_contributions, pref_paid_lp, roc_lp, catchup_lp,
        tier1_lp, tier2_lp, tier3_lp,
    )
    # GP totals
    total_gp_distributions = _row_add(
        gp_contributions, gp_during_pref, roc_gp, catchup_gp,
        tier1_gp, tier2_gp, tier3_gp,
    )

    investor_contributions = _row_add(lp_contributions, gp_contributions)
    total_equity_infused = list(equity_infused)
    total_equity_returned = list(equity_returns)
    net_cashflow_investors = _row_add(investor_contributions, equity_returns)

    cff: Dict[str, List[float]] = {
        # Fund-related expenses
        "JV Setup Fees": jv_setup_fees,
        "Fund Management Expenses": fund_mgmt_exp,
        "Other Fees": other_fees_row,
        "Project Management Fees": pm_fees,
        "JV Liquidation Fees": jv_liq_fees,
        "Total Free Cashflow before Financing": total_fcf_before_fin,
        # Financing Cost
        "Arrangement Fees": _row_negate(total_arr_fees),
        "Commitment Fees": _row_negate(total_commit_fees),
        "Interest Cost": _row_negate(total_interest),
        "Net Funding Requirement": net_funding_req,
        # TL1
        "TL1 Principal Drawn": tl1["principal_drawn"],
        "TL1 Principal Repaid": _row_negate(tl1_repaid_total),
        "TL1 Interest Paid": _row_negate(tl1["interest_paid"]),
        "TL1 Arrangement Fees": _row_negate(tl1["arrangement_fees"]),
        "TL1 Commitment Fees": _row_negate(tl1["commitment_fees"]),
        # TL2
        "TL2 Principal Drawn": tl2["principal_drawn"],
        "TL2 Principal Repaid": _row_negate(tl2["principal_repaid"]),
        "TL2 Interest Paid": _row_negate(tl2["interest_paid"]),
        "TL2 Arrangement Fees": _row_negate(tl2["arrangement_fees"]),
        "TL2 Commitment Fees": _row_negate(tl2["commitment_fees"]),
        # Equity
        "Equity Infused": equity_infused,
        "Equity Returns": equity_returns,
        "Net Financing Cashflows": net_financing_cf,
        # Total Distributions
        "Total Distributions": total_distributions_paid,
        "Investor Contributions": investor_contributions,
        "Total Equity Infused": total_equity_infused,
        "Total Equity Returned": total_equity_returned,
        "Net Cashflow to Investors": net_cashflow_investors,
        # LP Distributions
        "LP Contributions": lp_contributions,
        "In kind Equity": lp_in_kind,
        "Cash Equity": lp_cash_equity,
        "LP Distributions": _row_add(pref_paid_lp, roc_lp, catchup_lp,
                                     tier1_lp, tier2_lp, tier3_lp),
        "Return of Capital - LP": roc_lp,
        "Preferred Returns - LP": pref_paid_lp,
        "Catchup Returns - LP": catchup_lp,
        "Tier 1 Returns - LP": tier1_lp,
        "Tier 2 Returns - LP": tier2_lp,
        "Tier 3 Returns - LP": tier3_lp,
        "Clawback Additions - LP": _zeros(max_periods),
        "Total LP Distributions": total_lp_distributions,
        # GP Distributions
        "GP Contributions": gp_contributions,
        "In kind Equity - GP": gp_in_kind,
        "Cash Equity - GP": gp_cash_equity,
        "GP Distributions": _row_add(gp_during_pref, roc_gp, catchup_gp,
                                     tier1_gp, tier2_gp, tier3_gp),
        "Return of Capital - GP": roc_gp,
        "Catchup Returns - GP": catchup_gp,
        "Tier 1 Promote": tier1_gp,
        "Tier 2 Promote": tier2_gp,
        "Tier 3 Promote": tier3_gp,
        "Clawback Deductions - GP": _zeros(max_periods),
        "Total GP Distributions": total_gp_distributions,
        # Cash Schedule
        "Opening Balance": opening_balance_final,
        "Net Cash": net_cash,
        "Closing Balance": closing_balance,
        "Distributions Check": distributions_check,
    }

    # aaa, Preferred return schedule (separate output) aaa,
    cff["_pref_accrual_lp"] = pref_accrual_lp
    cff["_pref_paid_lp"] = pref_paid_lp
    cff["_pref_unpaid_lp"] = pref_unpaid_lp

    # aaa, Term Loan 1 debt schedule (separate output) aaa,
    cff["_tl1_opening_balance"] = tl1["opening_balance"]
    cff["_tl1_loan_additions"] = tl1["loan_additions"]
    # "Debt Issued" = gross debt raised = loan_additions + cap_interest + cap_arr_fees.
    cff["_tl1_debt_issued"] = _row_add(
        tl1["loan_additions"], tl1["capitalized_interest"], tl1["capitalized_arr_fees"],
    )
    # Gross presentation rows for top section:
    # Interest Expense Paid (gross) = cash interest + capitalized interest
    cff["_tl1_gross_interest_expense"] = _row_add(
        tl1["interest_paid"], tl1["capitalized_interest"],
    )
    # Arrangement Fees Paid (gross) = cash arr fees + capitalized arr fees
    cff["_tl1_gross_arr_fee_expense"] = _row_add(
        tl1["arrangement_fees"], tl1["capitalized_arr_fees"],
    )
    cff["_tl1_capitalized_interest"] = tl1["capitalized_interest"]
    cff["_tl1_capitalized_arr_fees"] = tl1["capitalized_arr_fees"]
    cff["_tl1_repayments"] = tl1["repayments"]
    cff["_tl1_closing_balance"] = tl1["closing_balance"]
    cff["_tl1_eq_infusion_interest"] = tl1["eq_infusion_interest"]
    cff["_tl1_eq_infusion_arr_fees"] = tl1["eq_infusion_arr_fees"]
    cff["_tl1_interest_paid"] = tl1["interest_paid"]
    cff["_tl1_arrangement_fees"] = tl1["arrangement_fees"]
    cff["_tl1_arr_fee_incurred"] = tl1["arr_fee_incurred"]
    cff["_tl1_principal_drawn"] = tl1["principal_drawn"]
    cff["_tl1_interest_incurred"] = tl1["interest_incurred"]
    cff["_tl1_interest_rate_applied"] = tl1["interest_rate_applied"]
    cff["_tl1_amort_pct_applied"] = tl1["amort_pct_applied"]
    cff["_tl1_balloon_payment"] = tl1["balloon_payment"]

    # aaa, Term Loan 2 / Refinancing Facility debt schedule aaa,
    cff["_tl2_opening_balance"] = tl2["opening_balance"]
    cff["_tl2_loan_additions"] = tl2["loan_additions"]
    # "Debt Issued" for Refinancing Facility = gross = loan_additions + cap_interest + cap_arr_fees
    cff["_tl2_debt_issued"] = _row_add(
        tl2["loan_additions"], tl2["capitalized_interest"], tl2["capitalized_arr_fees"],
    )
    # Gross presentation rows for Refinancing top section
    cff["_tl2_gross_interest_expense"] = _row_add(
        tl2["interest_paid"], tl2["capitalized_interest"],
    )
    cff["_tl2_gross_arr_fee_expense"] = _row_add(
        tl2["arrangement_fees"], tl2["capitalized_arr_fees"],
    )
    cff["_tl2_capitalized_interest"] = tl2["capitalized_interest"]
    cff["_tl2_capitalized_arr_fees"] = tl2["capitalized_arr_fees"]
    cff["_tl2_repayments"] = tl2["repayments"]
    cff["_tl2_closing_balance"] = tl2["closing_balance"]
    cff["_tl2_interest_paid"] = tl2["interest_paid"]
    cff["_tl2_arrangement_fees"] = tl2["arrangement_fees"]
    cff["_tl2_arr_fee_incurred"] = tl2["arr_fee_incurred"]
    cff["_tl2_principal_drawn"] = tl2["principal_drawn"]
    cff["_tl2_interest_incurred"] = tl2["interest_incurred"]
    cff["_tl2_interest_rate_applied"] = tl2["interest_rate_applied"]
    cff["_tl2_amort_pct_applied"] = tl2["amort_pct_applied"]
    cff["_tl2_balloon_payment"] = tl2["balloon_payment"]
    cff["_tl2_eq_infusion_interest"] = tl2["eq_infusion_interest"]
    cff["_tl2_eq_infusion_arr_fees"] = tl2["eq_infusion_arr_fees"]

    # aaa, Min DSCR threshold (scalar replicated per period) aaa,
    cff["_tl2_min_dscr"] = [vi.get("tl2_min_dscr", 0.0)] * max_periods

    # aaa, Cashflow From Financing Activity (combined TL1 + TL2) aaa,
    cff["_cashflow_from_financing_activity"] = cashflow_from_financing_activity

    # Log CFF summary

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # SECTION A: Equity Schedule
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # equity_funding is already computed as funding_req * equity_pct (positive = funding needed)
    # GP/LP split uses CashEquity contribution inputs (gp_contribution_ / lp_contribution_)
    # Ownership override is NOT used for equity-raised logic.
    _cash_gp = vi.get("cash_gp_pct", 0.0)
    _cash_lp = vi.get("cash_lp_pct", 0.0)

    gp_commitment = [v * _cash_gp for v in equity_funding]
    lp_commitment = [v * _cash_lp for v in equity_funding]

    cff["_equity_funding"] = list(equity_funding)
    cff["_gp_commitment"] = gp_commitment
    cff["_lp_commitment"] = lp_commitment


    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # SECTION B: Additional Equity Requirement
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Cash Balance After Capital Infusion =
    #   Total FCFF before Financing and SPV Related Cost - JV
    #   (= total_fcf + total_fund_expenses, includes JV fees)
    #   + Cashflow From Financing Activity  (cash only: adds - repaid - int_paid - arr_fees)
    #   + Equity Funding (positive = cash IN)
    # Capitalized interest and capitalized arrangement fees cancel inside
    # CFF Activity (gross presentation), so they do NOT create additional
    # equity requirement.

    _cash_bal_after_infusion = _row_add(
        total_fcf_before_fin,
        cashflow_from_financing_activity,
        equity_funding,
    )

    # Roll-forward: Opening aa a + Cash Balance After Capital Infusion aa a Additional Equity Req aa a Closing
    _addl_eq_opening = _zeros(max_periods)
    _addl_eq_req = _zeros(max_periods)
    _addl_eq_closing = _zeros(max_periods)

    for t in range(max_periods):
        if t > 0:
            _addl_eq_opening[t] = _addl_eq_closing[t - 1]

        # Additional equity requirement: if Opening + Cash Balance < 0,
        # additional equity = abs(Opening + Cash Balance).
        _pre_addl = _addl_eq_opening[t] + _cash_bal_after_infusion[t]
        if _pre_addl < 0:
            _addl_eq_req[t] = abs(_pre_addl)
        else:
            _addl_eq_req[t] = 0.0

        # Closing = opening + cash balance after capital infusion + additional equity requirement
        _addl_eq_closing[t] = _addl_eq_opening[t] + _cash_bal_after_infusion[t] + _addl_eq_req[t]

    cff["_addl_eq_opening"] = _addl_eq_opening
    cff["_cash_bal_after_infusion"] = _cash_bal_after_infusion
    cff["_addl_eq_req"] = _addl_eq_req
    cff["_addl_eq_closing"] = _addl_eq_closing


    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # SECTION C: Additional Equity Commitment
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    _addl_equity_funding = list(_addl_eq_req)
    _gp_addl_commit = [v * _cash_gp for v in _addl_equity_funding]
    _lp_addl_commit = [v * _cash_lp for v in _addl_equity_funding]

    cff["_addl_equity_funding"] = _addl_equity_funding
    cff["_gp_addl_commit"] = _gp_addl_commit
    cff["_lp_addl_commit"] = _lp_addl_commit


    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # SECTION D: Land In-Kind Commitment
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Source: Land In Kind - JV  (the JV-specific row, NOT the upstream
    # Free Cashflows Land In Kind).
    # Timing: total land-in-kind posted at JV initiation date only,
    # mirroring Land In Kind - JV from section 7b.
    # GP/LP split uses lik_gp_pct / lik_lp_pct from InKindEquity inputs.
    _lik_commitment = _zeros(max_periods)
    _gp_lik_commit = _zeros(max_periods)
    _lp_lik_commit = _zeros(max_periods)

    if _lik_is_yes_cff:
        # Compute total of upstream land_in_kind, then post at jv_start_idx
        # exactly like section 7b builds land_in_kind_jv.
        _lik_total_cff = sum(abs(_to_float(v)) for v in land_in_kind)
        if jv_start_idx is not None and 0 <= jv_start_idx < max_periods and _lik_total_cff != 0:
            _lik_commitment[jv_start_idx] = abs(_lik_total_cff)
        _gp_lik_commit = [v * vi.get("lik_gp_pct", 0.0) for v in _lik_commitment]
        _lp_lik_commit = [v * vi.get("lik_lp_pct", 0.0) for v in _lik_commitment]

    cff["_lik_commitment"] = _lik_commitment
    cff["_gp_lik_commit"] = _gp_lik_commit
    cff["_lp_lik_commit"] = _lp_lik_commit

    # aaa, Validation: Land In-kind Commitment vs Land In Kind - JV aaa,
    # land_in_kind_jv (section 7b) posts negative at jv_start_idx.
    # _lik_commitment posts positive (absolute) at the same index.
    _lik_first_nonzero_idx = next((i for i, v in enumerate(_lik_commitment) if v != 0), None)
    if _lik_is_yes_cff:
        pass
    else:
        pass

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # SECTION E: Total Commitment
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    _total_equity_funding = _row_add(equity_funding, _addl_equity_funding, _lik_commitment)
    _total_gp_commit = _row_add(gp_commitment, _gp_addl_commit, _gp_lik_commit)
    _total_lp_commit = _row_add(lp_commitment, _lp_addl_commit, _lp_lik_commit)

    cff["_total_equity_funding"] = _total_equity_funding
    cff["_total_gp_commit"] = _total_gp_commit
    cff["_total_lp_commit"] = _total_lp_commit


    return cff


def _build_fcff_layout(
    fcff_rows: Dict[str, List[float]],
    raw_template_names: Optional[list] = None,
    debt_pct: float = 0.0,
    equity_pct: float = 0.0,
    cff_rows: Optional[Dict[str, List[float]]] = None,
) -> Tuple[List[str], List[list], int]:
    """
    Build FCFF output from the accumulated per-module FCFF rows, aligned
    to the Excel template layout.

    ``fcff_rows`` maps keys like ``"LandCo_FCFF"``, ``"DevCo_FCFF"``,
    ``"AssetCo_FCFF"`` to period-value lists.  Each is the sum of all
    CFO + CFI items across selected assets for that module.

    ``cff_rows`` (optional) provides pre-computed CFF line items from
    ``_compute_cff()``, keyed by display label (e.g. "TL1 Principal Drawn").

    Additional computed rows:
      - **Land In Kind**: from ``fcff_rows["Land_In_Kind"]``
      - **Funding Requirement**: period-by-period  if cumulative total
        FCFF up to that period is negative, the requirement for that
        period equals the FCFF of that period (negative).
      - **Debt**: ``Funding Requirement a" debt_pct``
      - **Equity**: ``Funding Requirement a" equity_pct``

    When ``raw_template_names`` is provided (the raw ``o.jv.fcff.names``
    from the Excel template including spacers and section headers),
    the output rows are aligned 1-to-1 with the template.  Spacer and
    header rows get zero-filled data so the paste lands in the correct
    Excel rows.

    Without a template, produces contiguous data rows.
    """
    # Determine max periods from available data
    max_periods = 0
    for row in fcff_rows.values():
        max_periods = max(max_periods, len(row))

    if max_periods == 0:
        return [], [], 0

    # Get each module's FCFF, padded to max_periods
    lc_fcf = _pad(fcff_rows.get("LandCo_FCFF", []), max_periods)
    dc_fcf = _pad(fcff_rows.get("DevCo_FCFF", []), max_periods)
    ac_fcf = _pad(fcff_rows.get("AssetCo_FCFF", []), max_periods)
    total_fcf = _row_add(lc_fcf, dc_fcf, ac_fcf)

    # Land In Kind (already extracted from LandCo/DevCo CFF)
    lik_raw = fcff_rows.get("Land_In_Kind", [])
    land_in_kind = _pad(lik_raw, max_periods)

    # NOTE: Funding Requirement / Debt / Equity computation has been
    #       removed from this first section.  It will be implemented
    #       in a separate output block (o.jv.total.funding.*) later.


    # Map of normalised label aa a data row
    _norm = lambda s: " ".join(s.lower().split())
    data_lookup: Dict[str, List[float]] = {}
    data_specs: List[Tuple[str, List[float]]] = [
        ("Land Co Free Cashflow",                                     lc_fcf),
        ("Dev Co Free Cashflow",                                      dc_fcf),
        ("Asset Co Free Cashflow",                                    ac_fcf),
        ("Total Free Cashflow before Financing and SPV Related Cost", total_fcf),
        ("Land In Kind",                                              land_in_kind),
    ]
    for label, row_data in data_specs:
        data_lookup[_norm(label)] = row_data

    # Merge CFF rows into the lookup (CFF rows are keyed by display label)
    if cff_rows:
        for label, row_data in cff_rows.items():
            padded = _pad(row_data, max_periods)
            data_lookup[_norm(label)] = padded
            data_specs.append((label, padded))

    # --- Build template-aligned output ---
    if raw_template_names and len(raw_template_names) > 0:
        # Use the RAW template names (including spacers/headers/blanks)
        # so output rows align 1:1 with the Excel named range.
        all_labels: List[str] = []
        all_rows: List[list] = []
        zero_row = _zeros(max_periods)
        blank_row = [""] * max_periods  # spacer rows aa a empty strings (blank in Excel)


        for ti, raw_name in enumerate(raw_template_names):
            # Normalise template label for matching
            label_str = str(raw_name).strip() if raw_name is not None else ""
            norm_label = _norm(label_str) if label_str else ""

            if norm_label and norm_label in data_lookup:
                # Data row  use actual values
                all_labels.append(label_str)
                all_rows.append(list(data_lookup[norm_label]))
                total = sum(data_lookup[norm_label])
            else:
                # Spacer/header/blank  empty strings preserve blank cells
                display = label_str if label_str and label_str != "0" else "(blank)"
                all_labels.append(label_str if label_str else "0")
                all_rows.append(list(blank_row))


    else:
        # No template  use contiguous data rows (fallback)
        all_labels = [label for label, _ in data_specs]
        all_rows   = [list(data) for _, data in data_specs]

    # aaa, FCFF Validation: log per-row totals and first 5 values aaa,
    for i, (label, row) in enumerate(zip(all_labels, all_rows)):
        total = sum(_to_float(v) for v in row)
        if abs(total) > 0.01:
            first5 = [f"{_to_float(v):,.2f}" for v in row[:5]]

    return all_labels, all_rows, max_periods


def _compute_year_boundaries(
    max_periods: int, start_month: int = 1,
) -> List[Tuple[int, int]]:
    """Return calendar-year boundaries as ``[(start_inclusive, end_exclusive), ...]``.

    When the model starts in a month other than January, the first year
    covers only the remaining months of that calendar year
    (``13 - start_month`` months).  Subsequent years are full 12-month
    blocks.  The last chunk is truncated to *max_periods*.
    """
    if max_periods <= 0:
        return []
    first_year_months = 13 - start_month  # e.g. July start aa a 6 months
    boundaries: List[Tuple[int, int]] = []
    pos = 0
    # First (possibly partial) calendar year
    end = min(first_year_months, max_periods)
    boundaries.append((pos, end))
    pos = end
    # Subsequent full calendar years
    while pos < max_periods:
        end = min(pos + 12, max_periods)
        boundaries.append((pos, end))
        pos = end
    return boundaries


def _monthly_to_yearly(
    data_rows: List[list], max_periods: int,
    start_month: int = 1,
) -> Tuple[List[list], List[int]]:
    """
    Aggregate monthly rows to yearly using calendar-year boundaries.

    Returns ``(yearly_data_rows, yearly_column_indices)``.
    """
    boundaries = _compute_year_boundaries(max_periods, start_month)
    n_years = len(boundaries)
    yearly_cols = list(range(n_years))
    yearly_rows: List[list] = []

    for row in data_rows:
        # Preserve blank spacer rows (all empty strings)
        if all(v == "" for v in row):
            yearly_rows.append([""] * n_years)
            continue
        yearly_row: List[float] = []
        for ys, ye in boundaries:
            end = min(ye, len(row))
            yearly_row.append(sum(_to_float(v) for v in row[ys:end]))
        yearly_rows.append(yearly_row)

    return yearly_rows, yearly_cols


# =====================================================================
# 8. Output Assembly
# =====================================================================

def _sanitize_data(data: list) -> list:
    """Ensure every cell in a 2D data array is JSON-safe (no NaN/None/Infinity)."""
    import math
    clean: List[list] = []
    for row in data:
        clean_row = []
        for v in row:
            if v is None:
                clean_row.append(0)
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean_row.append(0)
            else:
                clean_row.append(v)
        clean.append(clean_row)
    return clean


def _build_split_payload(
    index: list, columns: list, data: list,
) -> dict:
    """Create ``{index, columns, data}`` split payload dict."""
    return {"index": index, "columns": columns, "data": _sanitize_data(data)}


def _build_section_output(
    cff_rows: Dict[str, List[float]],
    labels: List[str],
    max_periods: int,
) -> Tuple[List[str], List[list]]:
    """
    Extract a subset of CFF rows by label, returning (names, data_rows).
    Missing labels become zero-filled rows.
    """
    names: List[str] = []
    data: List[list] = []
    for label in labels:
        names.append(label)
        row = cff_rows.get(label, _zeros(max_periods))
        data.append(list(_pad(row, max_periods)))
    return names, data


def _build_excel_output(
    fcff_names: List[str],
    fcff_me_data: List[list],
    fcff_ye_data: List[list],
    monthly_cols: list,
    yearly_cols: list,
    timeline_me_payload: Optional[dict],
    timeline_ye_payload: Optional[dict],
    cff_rows: Optional[Dict[str, List[float]]] = None,
    max_periods: int = 0,
    cashflows_names: Optional[List[str]] = None,
    cashflows_me_data: Optional[List[list]] = None,
    cashflows_ye_data: Optional[List[list]] = None,
    project_cost_names: Optional[List[str]] = None,
    project_cost_ye_data: Optional[List[list]] = None,
    project_cost_me_data: Optional[List[list]] = None,
    fees_names: Optional[List[str]] = None,
    fees_me_data: Optional[List[list]] = None,
    fees_ye_data: Optional[List[list]] = None,
    asset_sales_names: Optional[List[str]] = None,
    asset_sales_me_data: Optional[List[list]] = None,
    asset_sales_ye_data: Optional[List[list]] = None,
    total_funding_names: Optional[List[str]] = None,
    total_funding_me_data: Optional[List[list]] = None,
    total_funding_ye_data: Optional[List[list]] = None,
    tl1_names: Optional[List[str]] = None,
    tl1_me_data: Optional[List[list]] = None,
    tl1_ye_data: Optional[List[list]] = None,
    refi_names: Optional[List[str]] = None,
    refi_me_data: Optional[List[list]] = None,
    refi_ye_data: Optional[List[list]] = None,
    tl1_sched_names: Optional[List[str]] = None,
    tl1_sched_me_data: Optional[List[list]] = None,
    tl1_sched_ye_data: Optional[List[list]] = None,
    refi_sched_names: Optional[List[str]] = None,
    refi_sched_me_data: Optional[List[list]] = None,
    refi_sched_ye_data: Optional[List[list]] = None,
    refi_mindscr_names: Optional[List[str]] = None,
    refi_mindscr_me_data: Optional[List[list]] = None,
    refi_mindscr_ye_data: Optional[List[list]] = None,
    equity_sched_names: Optional[List[str]] = None,
    equity_sched_me_data: Optional[List[list]] = None,
    equity_sched_ye_data: Optional[List[list]] = None,
    addl_eq_req_names: Optional[List[str]] = None,
    addl_eq_req_me_data: Optional[List[list]] = None,
    addl_eq_req_ye_data: Optional[List[list]] = None,
    addl_eq_commit_names: Optional[List[str]] = None,
    addl_eq_commit_me_data: Optional[List[list]] = None,
    addl_eq_commit_ye_data: Optional[List[list]] = None,
    lik_commit_names: Optional[List[str]] = None,
    lik_commit_me_data: Optional[List[list]] = None,
    lik_commit_ye_data: Optional[List[list]] = None,
    total_commit_names: Optional[List[str]] = None,
    total_commit_me_data: Optional[List[list]] = None,
    total_commit_ye_data: Optional[List[list]] = None,
    cash_dist_names: Optional[List[str]] = None,
    cash_dist_me_data: Optional[List[list]] = None,
    cash_dist_ye_data: Optional[List[list]] = None,
    pref_returns_names: Optional[List[str]] = None,
    pref_returns_me_data: Optional[List[list]] = None,
    pref_returns_ye_data: Optional[List[list]] = None,
    gp_catchup_names: Optional[List[str]] = None,
    gp_catchup_me_data: Optional[List[list]] = None,
    gp_catchup_ye_data: Optional[List[list]] = None,
    tier1_lp_names: Optional[List[str]] = None,
    tier1_lp_me_data: Optional[List[list]] = None,
    tier1_lp_ye_data: Optional[List[list]] = None,
    tier1_gp_cu_names: Optional[List[str]] = None,
    tier1_gp_cu_me_data: Optional[List[list]] = None,
    tier1_gp_cu_ye_data: Optional[List[list]] = None,
    tier2_lp_names: Optional[List[str]] = None,
    tier2_lp_me_data: Optional[List[list]] = None,
    tier2_lp_ye_data: Optional[List[list]] = None,
    tier2_gp_cu_names: Optional[List[str]] = None,
    tier2_gp_cu_me_data: Optional[List[list]] = None,
    tier2_gp_cu_ye_data: Optional[List[list]] = None,
    tier3_names: Optional[List[str]] = None,
    tier3_me_data: Optional[List[list]] = None,
    tier3_ye_data: Optional[List[list]] = None,
) -> dict:
    """
    Assemble the ``excel_output`` dict with ``monthly_dfs`` and ``annual_dfs``.

    Each value is ``(named_range_code, split_payload_dict)``.
    Now also emits separate sections for Finance Costs, Preferred Schedule,
    LP/GP Distributions, and Cash Schedule when cff_rows is available.
    """
    fcff_me = _build_split_payload(fcff_names, monthly_cols, fcff_me_data)
    fcff_ye = _build_split_payload(fcff_names, yearly_cols, fcff_ye_data)

    monthly_dfs: Dict[str, tuple] = {"FCFF": (OUT_FCFF_ME, fcff_me)}
    annual_dfs:  Dict[str, tuple] = {"FCFF": (OUT_FCFF_YE, fcff_ye)}

    # aaa, First JV Cashflow section (o.jv.cashflows.*) aaa,
    if cashflows_names and cashflows_me_data:
        cf_me = _build_split_payload(cashflows_names, monthly_cols, cashflows_me_data)
        cf_ye = _build_split_payload(cashflows_names, yearly_cols, cashflows_ye_data)
        monthly_dfs["Cashflows"] = (OUT_CASHFLOWS_ME, cf_me)
        annual_dfs["Cashflows"]  = (OUT_CASHFLOWS_YE, cf_ye)

    # aaa, Project Cost section (o.jv.project.cost.*  monthly + yearly) aaa,
    if project_cost_names:
        if project_cost_me_data:
            pc_me = _build_split_payload(project_cost_names, monthly_cols, project_cost_me_data)
            monthly_dfs["Project Cost"] = (OUT_PROJECT_COST_ME, pc_me)
        if project_cost_ye_data:
            pc_ye = _build_split_payload(project_cost_names, yearly_cols, project_cost_ye_data)
            annual_dfs["Project Cost"] = (OUT_PROJECT_COST_YE, pc_ye)

    # aaa, Asset Sales Value section (o.jv.assetsales.*) aaa,
    if asset_sales_names and asset_sales_me_data:
        as_me = _build_split_payload(asset_sales_names, monthly_cols, asset_sales_me_data)
        as_ye = _build_split_payload(asset_sales_names, yearly_cols, asset_sales_ye_data or [])
        monthly_dfs["Asset Sales"] = (OUT_ASSET_SALES_ME, as_me)
        annual_dfs["Asset Sales"]  = (OUT_ASSET_SALES_YE, as_ye)

    # aaa, Fees section (o.jv.fees.*) aaa,
    if fees_names and fees_me_data:
        f_me = _build_split_payload(fees_names, monthly_cols, fees_me_data)
        f_ye = _build_split_payload(fees_names, yearly_cols, fees_ye_data or [])
        monthly_dfs["Fees"] = (OUT_FEES_ME, f_me)
        annual_dfs["Fees"]  = (OUT_FEES_YE, f_ye)

    # aaa, Total Funding Required section (o.jv.total.funding.*) aaa,
    if total_funding_names and total_funding_me_data:
        tf_me = _build_split_payload(total_funding_names, monthly_cols, total_funding_me_data)
        tf_ye = _build_split_payload(total_funding_names, yearly_cols, total_funding_ye_data or [])
        monthly_dfs["Total Funding"] = (OUT_TOTAL_FUNDING_ME, tf_me)
        annual_dfs["Total Funding"]  = (OUT_TOTAL_FUNDING_YE, tf_ye)

    # aaa, Term Loan 1 section (o.jv.termloan1.*) aaa,
    if tl1_names and tl1_me_data:
        t1_me = _build_split_payload(tl1_names, monthly_cols, tl1_me_data)
        t1_ye = _build_split_payload(tl1_names, yearly_cols, tl1_ye_data or [])
        monthly_dfs["Term Loan 1"] = (OUT_TL1_ME, t1_me)
        annual_dfs["Term Loan 1"]  = (OUT_TL1_YE, t1_ye)

    # aaa, Refinancing section (o.jv.refinancing.*) aaa,
    if refi_names and refi_me_data:
        rf_me = _build_split_payload(refi_names, monthly_cols, refi_me_data)
        rf_ye = _build_split_payload(refi_names, yearly_cols, refi_ye_data or [])
        monthly_dfs["Refinancing"] = (OUT_REFI_ME, rf_me)
        annual_dfs["Refinancing"]  = (OUT_REFI_YE, rf_ye)

    # aaa, Term Loan 1 Schedule section (o.jv.termloan1schedule.*) aaa,
    if tl1_sched_names and tl1_sched_me_data:
        t1s_me = _build_split_payload(tl1_sched_names, monthly_cols, tl1_sched_me_data)
        t1s_ye = _build_split_payload(tl1_sched_names, yearly_cols, tl1_sched_ye_data or [])
        monthly_dfs["TL1 Schedule"] = (OUT_TL1_SCHED_ME, t1s_me)
        annual_dfs["TL1 Schedule"]  = (OUT_TL1_SCHED_YE, t1s_ye)

    # aaa, Refinancing Schedule section (o.jv.refinanceschedule.*) aaa,
    if refi_sched_names and refi_sched_me_data:
        r2s_me = _build_split_payload(refi_sched_names, monthly_cols, refi_sched_me_data)
        r2s_ye = _build_split_payload(refi_sched_names, yearly_cols, refi_sched_ye_data or [])
        monthly_dfs["Refi Schedule"] = (OUT_REFI_SCHED_ME, r2s_me)
        annual_dfs["Refi Schedule"]  = (OUT_REFI_SCHED_YE, r2s_ye)

    # aaa, Refinancing Min DSCR section (o.jv.refinancingloan.mindscr.*) aaa,
    if refi_mindscr_names and refi_mindscr_me_data:
        rmd_me = _build_split_payload(refi_mindscr_names, monthly_cols, refi_mindscr_me_data)
        rmd_ye = _build_split_payload(refi_mindscr_names, yearly_cols, refi_mindscr_ye_data or [])
        monthly_dfs["Refi Min DSCR"] = (OUT_REFI_MINDSCR_ME, rmd_me)
        annual_dfs["Refi Min DSCR"]  = (OUT_REFI_MINDSCR_YE, rmd_ye)

    # aaa, Equity Schedule section (o.jv.equity.schedule.*) aaa,
    if equity_sched_names and equity_sched_me_data:
        es_me = _build_split_payload(equity_sched_names, monthly_cols, equity_sched_me_data)
        es_ye = _build_split_payload(equity_sched_names, yearly_cols, equity_sched_ye_data or [])
        monthly_dfs["Equity Schedule"] = (OUT_EQUITY_SCHED_ME, es_me)
        annual_dfs["Equity Schedule"]  = (OUT_EQUITY_SCHED_YE, es_ye)

    # aaa, Additional Equity REQUIREMENT schedule (4 rows aa a o.jv.additional.equity.*) aaa,
    # Rows: Opening Balance, Cash Bal After Infusion, Addl Equity Req, Closing Balance
    if addl_eq_req_names and addl_eq_req_me_data:
        aer_me = _build_split_payload(addl_eq_req_names, monthly_cols, addl_eq_req_me_data)
        aer_ye = _build_split_payload(addl_eq_req_names, yearly_cols, addl_eq_req_ye_data or [])
        monthly_dfs["Additional Equity Requirement"] = (OUT_ADDL_EQUITY_REQ_ME, aer_me)
        annual_dfs["Additional Equity Requirement"]  = (OUT_ADDL_EQUITY_REQ_YE, aer_ye)
    else:
        pass

    # aaa, Additional Equity DRAWN/FUNDING (3 rows aa a o.jv.additional.equity.drawn.*) aaa,
    # Rows: Addition Equity Drawn - Total, Additional Equity Drawn - GP, - LP
    if addl_eq_commit_names and addl_eq_commit_me_data:
        aec_me = _build_split_payload(addl_eq_commit_names, monthly_cols, addl_eq_commit_me_data)
        aec_ye = _build_split_payload(addl_eq_commit_names, yearly_cols, addl_eq_commit_ye_data or [])
        monthly_dfs["Additional Equity Drawn"] = (OUT_ADDL_EQUITY_COMMIT_ME, aec_me)
        annual_dfs["Additional Equity Drawn"]  = (OUT_ADDL_EQUITY_COMMIT_YE, aec_ye)
    else:
        pass

    # aaa, Land In-kind Commitment section (o.jv.landinkind.comittment.*) aaa,
    if lik_commit_names and lik_commit_me_data:
        lk_me = _build_split_payload(lik_commit_names, monthly_cols, lik_commit_me_data)
        lk_ye = _build_split_payload(lik_commit_names, yearly_cols, lik_commit_ye_data or [])
        monthly_dfs["Land In-kind Commitment"] = (OUT_LIK_COMMIT_ME, lk_me)
        annual_dfs["Land In-kind Commitment"]  = (OUT_LIK_COMMIT_YE, lk_ye)

    # aaa, Total Commitment section (o.jv.total.commitment.*) aaa,
    if total_commit_names and total_commit_me_data:
        tc_me = _build_split_payload(total_commit_names, monthly_cols, total_commit_me_data)
        tc_ye = _build_split_payload(total_commit_names, yearly_cols, total_commit_ye_data or [])
        monthly_dfs["Total Commitment"] = (OUT_TOTAL_COMMIT_ME, tc_me)
        annual_dfs["Total Commitment"]  = (OUT_TOTAL_COMMIT_YE, tc_ye)

    # aaa, Cash Distribution section (o.jv.cash.distribution.*) aaa,
    if cash_dist_names and cash_dist_me_data:
        cd_me = _build_split_payload(cash_dist_names, monthly_cols, cash_dist_me_data)
        cd_ye = _build_split_payload(cash_dist_names, yearly_cols, cash_dist_ye_data or [])
        monthly_dfs["Cash Distribution"] = (OUT_CASH_DIST_ME, cd_me)
        annual_dfs["Cash Distribution"]  = (OUT_CASH_DIST_YE, cd_ye)

    # aaa, Preferred Returns section (o.jv.preferred.returns.*) aaa,
    if pref_returns_names and pref_returns_me_data:
        pr_me = _build_split_payload(pref_returns_names, monthly_cols, pref_returns_me_data)
        pr_ye = _build_split_payload(pref_returns_names, yearly_cols, pref_returns_ye_data or [])
        monthly_dfs["Preferred Returns"] = (OUT_PREF_RETURNS_ME, pr_me)
        annual_dfs["Preferred Returns"]  = (OUT_PREF_RETURNS_YE, pr_ye)

    # -- GP Catchup section (o.jv.preferred.returns.gpcatchup.*) --
    if gp_catchup_names and gp_catchup_me_data:
        gc_me = _build_split_payload(gp_catchup_names, monthly_cols, gp_catchup_me_data)
        gc_ye = _build_split_payload(gp_catchup_names, yearly_cols, gp_catchup_ye_data or [])
        monthly_dfs["GP Catchup"] = (OUT_GP_CATCHUP_ME, gc_me)
        annual_dfs["GP Catchup"]  = (OUT_GP_CATCHUP_YE, gc_ye)

    # -- Tier 1 LP Distributions section (o.jv.tier1.lpdistributions.*) --
    if tier1_lp_names and tier1_lp_me_data:
        t1l_me = _build_split_payload(tier1_lp_names, monthly_cols, tier1_lp_me_data)
        t1l_ye = _build_split_payload(tier1_lp_names, yearly_cols, tier1_lp_ye_data or [])
        monthly_dfs["Tier 1 LP Distributions"] = (OUT_TIER1_LP_ME, t1l_me)
        annual_dfs["Tier 1 LP Distributions"]  = (OUT_TIER1_LP_YE, t1l_ye)

    # -- Tier 1 GP Catchup section (o.jv.tier1.gp.catchup.*) --
    if tier1_gp_cu_names and tier1_gp_cu_me_data:
        t1g_me = _build_split_payload(tier1_gp_cu_names, monthly_cols, tier1_gp_cu_me_data)
        t1g_ye = _build_split_payload(tier1_gp_cu_names, yearly_cols, tier1_gp_cu_ye_data or [])
        monthly_dfs["Tier 1 GP Catchup"] = (OUT_TIER1_GP_CU_ME, t1g_me)
        annual_dfs["Tier 1 GP Catchup"]  = (OUT_TIER1_GP_CU_YE, t1g_ye)

    # -- Tier 2 LP Distributions section (o.jv.tier2.lpdistributions.*) --
    if tier2_lp_names and tier2_lp_me_data:
        t2l_me = _build_split_payload(tier2_lp_names, monthly_cols, tier2_lp_me_data)
        t2l_ye = _build_split_payload(tier2_lp_names, yearly_cols, tier2_lp_ye_data or [])
        monthly_dfs["Tier 2 LP Distributions"] = (OUT_TIER2_LP_ME, t2l_me)
        annual_dfs["Tier 2 LP Distributions"]  = (OUT_TIER2_LP_YE, t2l_ye)

    # -- Tier 2 GP Catchup section (o.jv.tier2.gp.catchup.*) --
    if tier2_gp_cu_names and tier2_gp_cu_me_data:
        t2g_me = _build_split_payload(tier2_gp_cu_names, monthly_cols, tier2_gp_cu_me_data)
        t2g_ye = _build_split_payload(tier2_gp_cu_names, yearly_cols, tier2_gp_cu_ye_data or [])
        monthly_dfs["Tier 2 GP Catchup"] = (OUT_TIER2_GP_CU_ME, t2g_me)
        annual_dfs["Tier 2 GP Catchup"]  = (OUT_TIER2_GP_CU_YE, t2g_ye)

    # -- Tier 3 section (o.jv.tier3.*) --
    if tier3_names and tier3_me_data:
        t3_me = _build_split_payload(tier3_names, monthly_cols, tier3_me_data)
        t3_ye = _build_split_payload(tier3_names, yearly_cols, tier3_ye_data or [])
        monthly_dfs["Tier 3"] = (OUT_TIER3_ME, t3_me)
        annual_dfs["Tier 3"]  = (OUT_TIER3_YE, t3_ye)

    if timeline_me_payload:
        tl_me = dict(timeline_me_payload)
        tl_me["data"] = _sanitize_data(tl_me.get("data", []))
        monthly_dfs["Monthly Timeline"] = (OUT_TIMELINE_ME, tl_me)
    if timeline_ye_payload:
        tl_ye = dict(timeline_ye_payload)
        tl_ye["data"] = _sanitize_data(tl_ye.get("data", []))
        annual_dfs["Yearly Timeline"] = (OUT_TIMELINE_YE, tl_ye)

    # aaa, Additional CFF sections aaa,
    # if cff_rows and max_periods > 0:
    #
    #     # Term Loan 1 Debt Schedule
    #     tl1_labels = [
    #         "Opening Balance", "Loan Additions", "Capitalized Interest",
    #         "Capitalized Arrangement Fees", "Repayments", "Closing Balance",
    #         "Equity Infusion for Interest", "Equity Infusion for Arrangement Fees",
    #     ]
    #     tl1_internal_keys = [
    #         "_tl1_opening_balance", "_tl1_loan_additions",
    #         "_tl1_capitalized_interest", "_tl1_capitalized_arr_fees",
    #         "_tl1_repayments", "_tl1_closing_balance",
    #         "_tl1_eq_infusion_interest", "_tl1_eq_infusion_arr_fees",
    #     ]
    #     tl1_names = list(tl1_labels)
    #     tl1_me = []
    #     for key in tl1_internal_keys:
    #         row = cff_rows.get(key, _zeros(max_periods))
    #         tl1_me.append(list(row[:max_periods]))
    #     tl1_ye, _ = _monthly_to_yearly(tl1_me, max_periods)
    #     _fix_balance_yearly(tl1_me, tl1_ye, tl1_names,
    #                         ["Opening Balance", "Closing Balance"],
    #                         max_periods)
    #     monthly_dfs["Term Loan 1"] = (
    #         OUT_TL1_ME,
    #         _build_split_payload(tl1_names, monthly_cols, tl1_me),
    #     )
    #     annual_dfs["Term Loan 1"] = (
    #         OUT_TL1_YE,
    #         _build_split_payload(tl1_names, yearly_cols, tl1_ye),
    #     )

    return {"monthly_dfs": monthly_dfs, "annual_dfs": annual_dfs}


def _fix_balance_yearly(
    me_data: List[list],
    ye_data: List[list],
    names: List[str],
    balance_labels: List[str],
    max_periods: int,
    start_month: int = 1,
):
    """
    For balance rows (Opening/Closing), yearly should be last-month-of-year
    value, not the sum of 12 months.
    """
    boundaries = _compute_year_boundaries(max_periods, start_month)
    for i, label in enumerate(names):
        if label in balance_labels:
            yearly_row: List[float] = []
            for ys, ye in boundaries:
                end = min(ye - 1, max_periods - 1)
                yearly_row.append(_to_float(me_data[i][end]))
            ye_data[i] = yearly_row


# =====================================================================
# 9. Diagnostics
# =====================================================================


def _print_fcff_summary(
    fcff_names: List[str],
    fcff_me_data: List[list],
    max_periods: int,
):
    """Print a compact FCFF CFS to terminal for inspection."""

    current_module = ""
    for label, row in zip(fcff_names, fcff_me_data):
        total = sum(_to_float(v) for v in row)

        # Print module separator when the module prefix changes
        parts = label.split(" - ", 1)
        module_prefix = parts[0] if len(parts) > 1 else ""
        if module_prefix and module_prefix != current_module:
            current_module = module_prefix

        # Show non-zero rows and the FCFF total
        if label == "FCFF" or abs(total) > 0.01:
            pass


# =====================================================================
# Main Consolidation
# =====================================================================

def wrapper_for_vars(payload: Any) -> Optional[Any]:
    """
    Main entry point for JV consolidation.

    Orchestration sequence:
      1. Read named ranges  (Master Sheet / JV Inputs / JV Output)
      2. Initialize classes (Global, Asset, JVGlobal via setattr)
      3. Unpack upstream payloads
      4. Resolve selection  (vehicle type / scenario aa a assets / modules)
      5. Extract CFO + CFI + CFF  (per selected asset, per module, with acquisition elimination)
      6. Verify acquisition elimination (diagnostic)
      7. Build FCFF monthly + yearly
      8. Resolve timeline from upstream
      9. Assemble excel output
     10. Print FCFF CFS
    """
    try:

        # ----------------------------------------------------------------
        # 1. Read named ranges
        # ----------------------------------------------------------------
        namedranges = payload.get("namedranges") or []

        ms_df  = fn_read_all_named_ranges_json(namedranges, _PREFIXES_MS)
        jv_df  = fn_read_all_named_ranges_json(namedranges, _PREFIXES_JV)
        out_df = fn_read_all_named_ranges_json(namedranges, _PREFIXES_OUT)

        # _print_stage(1, "NAMED RANGE READS", {
        #     "Master Sheet ranges": len(ms_df),
        #     "JV Input ranges": len(jv_df),
        #     "Output ranges": len(out_df),
        #     "Total": len(ms_df) + len(jv_df) + len(out_df),
        # })

        # Diagnostic: list all named range keys per group
        if not ms_df.empty:
            pass
        if not jv_df.empty:
            pass
        if not out_df.empty:
            pass

        if ms_df.empty and jv_df.empty and out_df.empty:
            pass

        # ----------------------------------------------------------------
        # 2. Initialize classes via setattr (LandCo/DevCo pattern)
        # ----------------------------------------------------------------
        # 2a. MasterSheet.Global aa a ProjectInputs, ModelAssumptions, etc.
        if not ms_df.empty:
            fn_initialize_global_class(
                ms_df, MasterSheet.Global,
                MS_GLOBAL_CLASS, MS_GLOBAL_ATTRIBUTE, MS_GLOBAL_VALUE,
            )

            # Log key values for verification
            if MasterSheet.Global.ProjectInputs.project_name is not None:
                pass
            if MasterSheet.Global.ModelAssumptions.model_start_date is not None:
                pass
            if MasterSheet.Global.ValuationAssumptions.discount_rate is not None:
                pass

        # 2b. MasterSheet.Asset aa a ProjectDetails, JVModule
        if not ms_df.empty:
            ms_keys = sorted(ms_df["name"].unique().tolist()) if "name" in ms_df.columns else []
            for needed in [MS_CLASS_ROW, MS_ATTRIBUTES_ROW, MS_UNITS_DATA]:
                found = needed in ms_keys
            fn_initialize_asset_class(
                ms_df, MasterSheet.Asset,
                MS_CLASS_ROW, MS_ATTRIBUTES_ROW, MS_UNITS_DATA,
                inclusion_attr="__no_filter__",  # Read ALL rows; JV filtering in _resolve_selection
                class_name_map=MS_CLASS_NAME_MAP,
            )
            asset_names_raw = _get_raw_asset_names_from_classes()
            asset_names_valid = [n for n in asset_names_raw if n]

            # --- Asset-JV Mapping Summary (use RAW list for index alignment) ---
            jv_incl = MasterSheet.Asset.JVModule.jvjda_inclusion
            jv_names_list = MasterSheet.Asset.JVModule.jv_name
            lc_incl = MasterSheet.Asset.JVModule.landco_inclusion
            dc_incl = MasterSheet.Asset.JVModule.devco_inclusion
            ac_incl = MasterSheet.Asset.JVModule.assetco_inclusion
            lc_life = MasterSheet.Asset.AssetLifecycleModule.land_development
            dc_life = MasterSheet.Asset.AssetLifecycleModule.vertical_development
            ac_life = MasterSheet.Asset.AssetLifecycleModule.asset_operations

            if isinstance(jv_incl, list) and len(jv_incl) > 0:
                jv_enabled_count = 0
                for i in range(len(jv_incl)):
                    name = asset_names_raw[i] if i < len(asset_names_raw) else f"(row {i})"
                    if not name:
                        name = f"(blank row {i})"
                    incl = _safe_str_lower(jv_incl[i])
                    jv_n = _safe_str_lower(jv_names_list[i]) if isinstance(jv_names_list, list) and i < len(jv_names_list) else ""
                    lc = _safe_str_lower(lc_incl[i]) if isinstance(lc_incl, list) and i < len(lc_incl) else ""
                    dc = _safe_str_lower(dc_incl[i]) if isinstance(dc_incl, list) and i < len(dc_incl) else ""
                    ac = _safe_str_lower(ac_incl[i]) if isinstance(ac_incl, list) and i < len(ac_incl) else ""
                    ld = _safe_str_lower(lc_life[i]) if isinstance(lc_life, list) and i < len(lc_life) else ""
                    vd = _safe_str_lower(dc_life[i]) if isinstance(dc_life, list) and i < len(dc_life) else ""
                    ao = _safe_str_lower(ac_life[i]) if isinstance(ac_life, list) and i < len(ac_life) else ""
                    if incl == "yes":
                        jv_enabled_count += 1
            else:
                pass

        # 2c. JVInputs.Global aa a SPVInputs, RoleAllocation, JVDates, etc.
        if not jv_df.empty:
            fn_initialize_global_class(
                jv_df, JVInputs.Global,
                JV_GLOBAL_CLASS, JV_GLOBAL_ATTRIBUTE, JV_GLOBAL_VALUE,
                class_name_map=JV_CLASS_NAME_MAP,
            )

            if JVInputs.Global.SPVInputs.vehicle_type is not None:
                pass
            if JVInputs.Global.RoleAllocation.gp is not None:
                pass
            if JVInputs.Global.IterationSettings.no_of_iterations is not None:
                pass

        # 2d. JVInputs.Asset aa a per-asset SPVInputs, CapitalStructure, etc.
        if not jv_df.empty:
            fn_initialize_asset_class(
                jv_df, JVInputs.Asset,
                JV_CLASS_ROW, JV_ATTRIBUTES_ROW, JV_UNITS_DATA,
                inclusion_attr="__no_filter__",  # sno is serial number, not Yes/No flag
                class_name_map=JV_CLASS_NAME_MAP,
            )
            # Diagnostic: dump capital structure values

        # 2e. Read no. of iterations (standalone scalar named range)
        no_of_iterations_raw = _read_scalar(jv_df, JV_NUM_ITERATIONS, default=1)
        no_of_iterations = int(_to_float(no_of_iterations_raw)) if no_of_iterations_raw else 1
        if no_of_iterations < 1:
            no_of_iterations = 1

        # 2f. Read interest rate profiles
        interest_profiles = _read_interest_rate_profiles(jv_df)

        _print_stage(2, "CLASS INITIALIZATION COMPLETE", {
            "MasterSheet.Global classes": sum(1 for n in dir(MasterSheet.Global) if isinstance(getattr(MasterSheet.Global, n), type)),
            "MasterSheet.Asset classes": sum(1 for n in dir(MasterSheet.Asset) if isinstance(getattr(MasterSheet.Asset, n), type)),
            "JVInputs.Global classes": sum(1 for n in dir(JVInputs.Global) if isinstance(getattr(JVInputs.Global, n), type)),
            "JVInputs.Asset classes": sum(1 for n in dir(JVInputs.Asset) if isinstance(getattr(JVInputs.Asset, n), type)),
        })

        # ----------------------------------------------------------------
        # 3. Unpack upstream payloads
        # ----------------------------------------------------------------
        landco_devco = payload.get("landco_devco") or {}

        # Debug: log top-level payload keys for traceability

        landco_data = landco_devco.get("landco", {})
        devco_data  = landco_devco.get("devco", {})

        # AssetCo per-asset data: prefer the raw per-asset entries from
        # "assetco_per_asset" (injected by views with actual CFS data),
        # falling back to "assetco" / "assetco_consolidation" jvoutput.
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

        if raw_ac_list:
            first = raw_ac_list[0]

        assetco_per_asset = _normalize_assetco_entries(raw_ac_list)

        _print_stage(3, "PAYLOAD AVAILABILITY", {
            "LandCo": "PRESENT" if landco_data else "ABSENT",
            "DevCo": "PRESENT" if devco_data else "ABSENT",
            "AssetCo per-asset entries (raw)": len(raw_ac_list),
            "AssetCo per-asset entries (normalized)": len(assetco_per_asset),
        })

        if landco_data:
            lc_sections = [k for k in landco_data if k in _CFS_SECTIONS]
            lc_all_keys = list(landco_data.keys())
            # Validate LandCo CFS structure
            for sec in lc_sections:
                sec_data = landco_data[sec]
                if isinstance(sec_data, dict):
                    item_names = list(sec_data.keys())
                    # Verify first item has correct shape
                    if item_names:
                        first_item = sec_data[item_names[0]]
                        if isinstance(first_item, dict) and "data" in first_item:
                            d = first_item["data"]
        if devco_data:
            dc_sections = [k for k in devco_data if k in _CFS_SECTIONS]
            for sec in dc_sections:
                sec_data = devco_data[sec]
                if isinstance(sec_data, dict):
                    item_names = list(sec_data.keys())
                    if item_names:
                        first_item = sec_data[item_names[0]]
                        if isinstance(first_item, dict) and "data" in first_item:
                            d = first_item["data"]
        if assetco_per_asset:
            ac_names = [e.get("asset_name", "?") for e in assetco_per_asset]
            # Validate each entry has CFS sections
            for ei, entry in enumerate(assetco_per_asset):
                name = entry.get("asset_name", "?")
                sections = [s for s in _CFS_SECTIONS if s in entry]
                missing = [s for s in _CFS_SECTIONS if s not in entry]
                if missing:
                    pass
                # Show row counts for each section
                for sec in sections:
                    sec_data = entry[sec]
                    if isinstance(sec_data, dict):
                        index = sec_data.get("index", [])
                        data = sec_data.get("data", [])
                        n_periods = len(data[0]) if data else 0
                        # Show ALL non-zero items and flag the net line
                        for ii, iname in enumerate(index):
                            total = sum(_to_float(v) for v in data[ii]) if ii < len(data) else 0
                            is_net = any(c.lower() in str(iname).lower()
                                         for c in ("net cashflow", "total net"))
                            marker = " >>>,>>>,>>>, NET LINE" if is_net else ""
                            if abs(total) > 0.01 or is_net:
                                first3 = [f"{_to_float(v):,.2f}" for v in data[ii][:3]] if ii < len(data) else []

        # ----------------------------------------------------------------
        # 3b. Fallback: populate MasterSheet.Asset from upstream
        #     asset_assumptions when m.mastersheet.units.data is absent
        # ----------------------------------------------------------------
        if MasterSheet.Asset.ProjectDetails.asset_name is None:
            _ms_class_map = {
                "ProjectDetails": MasterSheet.Asset.ProjectDetails,
                "JVInputsModule": MasterSheet.Asset.JVModule,
                "AssetLifecycleModule": MasterSheet.Asset.AssetLifecycleModule,
            }
            for _src in (landco_data, devco_data):
                if not _src:
                    continue
                _aa = _src.get("asset_assumptions")
                if not isinstance(_aa, dict):
                    continue
                _populated = False
                for _excel_cls, _py_cls in _ms_class_map.items():
                    _cls_data = _aa.get(_excel_cls)
                    if not isinstance(_cls_data, dict):
                        continue
                    _set_count = 0
                    for _attr, _vals in _cls_data.items():
                        if not hasattr(_py_cls, _attr):
                            continue
                        if isinstance(_vals, (list, tuple)):
                            setattr(_py_cls, _attr, list(_vals))
                            _set_count += 1
                        elif isinstance(_vals, dict):
                            # dict keyed by index: {"0": val, "1": val, ...}
                            sorted_items = sorted(
                                _vals.items(),
                                key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
                            )
                            setattr(_py_cls, _attr, [v for _, v in sorted_items])
                            _set_count += 1
                    if _set_count > 0:
                        _populated = True
                if _populated:
                    # Log what we got
                    _fb_names = MasterSheet.Asset.ProjectDetails.asset_name
                    _fb_jv = MasterSheet.Asset.JVModule.jvjda_inclusion
                    break  # use first available source

        # ----------------------------------------------------------------
        # 4. Resolve selection
        # ----------------------------------------------------------------
        # Build asset name lists:
        # - raw list (with None for empty rows) for index alignment with JVModule
        # - filtered list for display and payload lookups
        raw_asset_names = _get_raw_asset_names_from_classes()
        all_asset_names = _get_asset_names_from_classes()

        if not all_asset_names:
            all_asset_names = _get_asset_names_from_payload(landco_data, devco_data)
            raw_asset_names = [n for n in all_asset_names]  # no filtering needed

        existing_lower = {n.strip().lower() for n in all_asset_names}
        for entry in assetco_per_asset:
            name = str(entry.get("asset_name") or "").strip()
            if name and name.lower() not in existing_lower:
                all_asset_names.append(name)
                existing_lower.add(name.lower())

        selection = _resolve_selection(out_df, all_asset_names, raw_asset_names)

        _print_stage(4, "SELECTION RESOLUTION", {
            "Selected vehicle type": selection["selected_vehicle_type"] or "(not set)",
            "Selected scenario": selection["selected_scenario"] or "(not set)",
            "Selected assets count": len(selection["selected_assets"]),
            "JV groups": selection.get("jv_groups", {}),
        })

        if not selection["selected_assets"]:
            return {"exceloutput": {}, "consolidationoutput": {}}

        for asset_name in selection["selected_assets"]:
            flags = selection["module_flags"].get(asset_name, {})
            lifecycle = selection.get("lifecycle_flags", {}).get(asset_name, {})
            vtype = selection.get("venture_types", {}).get(asset_name, "?")

        # ----------------------------------------------------------------
        # 5. Compute FCFF per vehicle (per jv_name group)
        # ----------------------------------------------------------------
        # vehicle_fcff: jv_name aa a {module_key aa a [period_values]}
        # Each jv_name gets its own aggregated LandCo/DevCo/AssetCo FCFF.
        vehicle_fcff: Dict[str, Dict[str, List[float]]] = {}
        jv_groups = selection["jv_groups"]  # jv_name aa a [asset_names]

        _print_stage(5, "VEHICLE-WISE FCFF COMPUTATION", {
            "Number of vehicles": len(jv_groups),
            "Vehicles": list(jv_groups.keys()),
        })

        for jv_name, group_assets in jv_groups.items():
            group_fcff: Dict[str, List[float]] = {}

            # Determine venture type for logging (from first asset)
            first_vtype = selection["venture_types"].get(
                group_assets[0], "?"
            ) if group_assets else "?"


            for asset_name in group_assets:
                asset_fcff = _extract_asset_fcff(
                    asset_name, landco_data, devco_data,
                    assetco_per_asset, selection["module_flags"],
                )

                for key, row in asset_fcff.items():
                    total = sum(row) if row else 0

                _accumulate_fcff_rows(group_fcff, asset_fcff)

            # aaa, Vehicle-level JV inputs (capital structure, financing, GP/LP) aaa,
            jv_asset_scenario_names = JVInputs.Asset.SPVInputs.scenario_name
            vi = _resolve_vehicle_jv_inputs(jv_name, jv_asset_scenario_names)
            vehicle_debt_pct = vi["debt_pct"]
            vehicle_equity_pct = vi["equity_pct"]

            vehicle_fcff[jv_name] = {
                "fcff": group_fcff,
                "debt_pct": vehicle_debt_pct,
                "equity_pct": vehicle_equity_pct,
                "vehicle_inputs": vi,
            }

            # Log vehicle-level totals
            for key, row in sorted(group_fcff.items()):
                total = sum(row)

        # ----------------------------------------------------------------
        # 6. Select the target vehicle's FCFF for output
        # ----------------------------------------------------------------
        selected_scenario = _safe_str_lower(selection.get("selected_scenario", ""))
        selected_vehicle_type = selection["selected_vehicle_type"]

        # Determine which vehicle to output
        chosen_debt_pct = 0.0
        chosen_equity_pct = 0.0
        chosen_vehicle_inputs = None
        if selected_scenario and selected_scenario in vehicle_fcff:
            # Exact match on jv_name (selected scenario)
            vdata = vehicle_fcff[selected_scenario]
            output_fcff = vdata["fcff"]
            chosen_debt_pct = vdata["debt_pct"]
            chosen_equity_pct = vdata["equity_pct"]
            chosen_vehicle_inputs = vdata.get("vehicle_inputs")
            chosen_vehicle = selected_scenario
        elif len(vehicle_fcff) == 1:
            # Only one vehicle  use it regardless
            chosen_vehicle = next(iter(vehicle_fcff))
            vdata = vehicle_fcff[chosen_vehicle]
            output_fcff = vdata["fcff"]
            chosen_debt_pct = vdata["debt_pct"]
            chosen_equity_pct = vdata["equity_pct"]
            chosen_vehicle_inputs = vdata.get("vehicle_inputs")
        else:
            # Multiple vehicles but no specific match  aggregate all.
            # Pick the vehicle with actual JV configuration for inputs
            # (non-None jv_start_date or non-zero debt/equity pct),
            # rather than blindly using the first vehicle which may be
            # an unnamed/unconfigured placeholder.
            output_fcff = {}
            _best_vdata = None
            _best_has_jv = False
            for vname, vdata in vehicle_fcff.items():
                _accumulate_fcff_rows(output_fcff, vdata["fcff"])
                _cvi = vdata.get("vehicle_inputs") or {}
                _has_jv_config = (
                    _cvi.get("jv_start_date") is not None
                    or vdata["debt_pct"] + vdata["equity_pct"] > 0
                )
                if _best_vdata is None:
                    _best_vdata = vdata
                    _best_has_jv = _has_jv_config
                elif _has_jv_config and not _best_has_jv:
                    # Prefer the vehicle that actually has JV inputs
                    _best_vdata = vdata
                    _best_has_jv = _has_jv_config
            chosen_vehicle = "(all vehicles aggregated)"
            if _best_vdata is not None:
                chosen_debt_pct = _best_vdata["debt_pct"]
                chosen_equity_pct = _best_vdata["equity_pct"]
                chosen_vehicle_inputs = _best_vdata.get("vehicle_inputs")

        _print_stage(6, "SELECTED VEHICLE FOR OUTPUT", {
            "Selected scenario": selected_scenario or "(not set)",
            "Selected vehicle type": selected_vehicle_type or "(not set)",
            "Chosen vehicle": chosen_vehicle,
            "Available vehicles": list(vehicle_fcff.keys()),
        })
        for key, row in sorted(output_fcff.items()):
            total = sum(row)
            has_ac = "AssetCo_FCFF" in output_fcff
        if "AssetCo_FCFF" not in output_fcff:
            pass

        # ----------------------------------------------------------------
        # 7. Build FCFF
        # ----------------------------------------------------------------
        raw_fcff_names = _read_array(out_df, OUT_FCFF_NAMES)

        # Log raw template names so we can see spacers/headers
        if raw_fcff_names:
            for ti, nm in enumerate(raw_fcff_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

        # Capital structure from selected vehicle

        # aaa, Compute CFF (Cashflow from Financing) aaa,
        cff_rows: Optional[Dict[str, List[float]]] = None
        model_start = None                               # ensure variable exists for downstream blocks
        if chosen_vehicle_inputs is not None:
            # Determine max_periods first from output_fcff
            _pre_max = max((len(r) for r in output_fcff.values()), default=0)
            if _pre_max > 0:
                # Build total FCF and land in kind for CFF computation
                _lc = _pad(output_fcff.get("LandCo_FCFF", []), _pre_max)
                _dc = _pad(output_fcff.get("DevCo_FCFF", []), _pre_max)
                _ac = _pad(output_fcff.get("AssetCo_FCFF", []), _pre_max)
                _total_fcf = _row_add(_lc, _dc, _ac)
                _lik = _pad(output_fcff.get("Land_In_Kind", []), _pre_max)

                model_start = MasterSheet.Global.ModelAssumptions.model_start_date
                if model_start is not None:
                    model_start = pd.Timestamp(model_start).replace(day=1)
                else:
                    # Derive model_start from upstream Timeline data
                    for _src in (landco_data, devco_data):
                        if not _src or "Timeline" not in _src:
                            continue
                        _tl = _src["Timeline"]
                        if isinstance(_tl, dict) and "data" in _tl:
                            _tl_data = _tl["data"]
                            if _tl_data and _tl_data[0]:
                                try:
                                    model_start = pd.Timestamp(_tl_data[0][0]).replace(day=1)
                                except Exception:
                                    pass
                            break
                    # Still None? Try columns from upstream CFS payload
                    if model_start is None:
                        for _src in (landco_data, devco_data):
                            if not _src:
                                continue
                            for _sec_name in ("Cashflow from Operations", "Cashflow from Investments"):
                                _sec = _src.get(_sec_name)
                                if not isinstance(_sec, dict):
                                    continue
                                for _item_key, _item_val in _sec.items():
                                    if isinstance(_item_val, dict):
                                        _cols = _item_val.get("columns", [])
                                        if _cols:
                                            try:
                                                model_start = pd.Timestamp(_cols[0]).replace(day=1)
                                            except Exception:
                                                pass
                                    if model_start is not None:
                                        break
                                if model_start is not None:
                                    break
                            if model_start is not None:
                                break
                    # Last resort: assume 2019-01-01 based on 504 periods = 42 years
                    if model_start is None and _pre_max == 504:
                        model_start = pd.Timestamp("2019-01-01")


                cff_rows = _compute_cff(
                    total_fcf=_total_fcf,
                    land_in_kind=_lik,
                    max_periods=_pre_max,
                    vehicle_inputs=chosen_vehicle_inputs,
                    interest_profiles=interest_profiles,
                    model_start=model_start,
                )

        fcff_names, fcff_me_data, max_periods = _build_fcff_layout(
            output_fcff,
            raw_fcff_names,   # Pass RAW names (with spacers)  NOT cleaned
            debt_pct=chosen_debt_pct,
            equity_pct=chosen_equity_pct,
            cff_rows=cff_rows,
        )

        # Calendar-year start month for yearly aggregation
        _start_month = model_start.month if model_start is not None else 1

        # aaa, 7b. Build first JV Cashflow section (o.jv.cashflows.*) aaa,
        # This section produces date-windowed entity cashflows aligned to
        # o.jv.cashflows.names.  Values only appear between JV start date
        # and JV end date (start + fund_tenure).  Land Cost - JV is a
        # one-time value on JV start date only.
        raw_cashflows_names = _read_array(out_df, OUT_CASHFLOWS_NAMES)
        cashflows_names: Optional[List[str]] = None
        cashflows_me_data: Optional[List[list]] = None
        cashflows_ye_data: Optional[List[list]] = None
        # Elevate key cashflows variables so step 7e (Total Funding) can access them
        module_consolidation_jv: Optional[List[float]] = None
        land_in_kind_jv: Optional[List[float]] = None
        land_cost_jv: Optional[List[float]] = None
        total_fcff_jv: Optional[List[float]] = None

        if raw_cashflows_names:
            for ti, nm in enumerate(raw_cashflows_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            # aaa, Resolve JV date window aaa,
            _jv_start_date = chosen_vehicle_inputs.get("jv_start_date") if chosen_vehicle_inputs else None
            _fund_tenure = chosen_vehicle_inputs.get("fund_tenure", 0) if chosen_vehicle_inputs else 0
            _fund_tenure = _to_float(_fund_tenure) if _fund_tenure else 0

            # model_start is already resolved above in the CFF block
            _jv_start_idx = _date_to_month_index(_jv_start_date, model_start)
            if _jv_start_idx is not None and _fund_tenure > 0:
                _jv_end_idx = _jv_start_idx + int(_fund_tenure)
            else:
                _jv_end_idx = None  # no end constraint

            _cf_max = max((len(r) for r in output_fcff.values()), default=0)


            if _cf_max > 0:
                # aaa, Source data from already-computed output_fcff aaa,
                _lc = _pad(output_fcff.get("LandCo_FCFF", []), _cf_max)
                _dc = _pad(output_fcff.get("DevCo_FCFF", []), _cf_max)
                _ac = _pad(output_fcff.get("AssetCo_FCFF", []), _cf_max)
                _lik_raw = _pad(output_fcff.get("Land_In_Kind", []), _cf_max)

                # aaa, Apply JV date window mask aaa,
                def _apply_jv_window(row: List[float], start_idx, end_idx, n: int) -> List[float]:
                    """Zero out values outside [start_idx, end_idx)."""
                    masked = [0.0] * n
                    s = start_idx if start_idx is not None else 0
                    e = end_idx if end_idx is not None else n
                    for t in range(max(s, 0), min(e, n)):
                        masked[t] = _to_float(row[t])
                    return masked

                lc_jv = _apply_jv_window(_lc, _jv_start_idx, _jv_end_idx, _cf_max)
                dc_jv = _apply_jv_window(_dc, _jv_start_idx, _jv_end_idx, _cf_max)
                ac_jv = _apply_jv_window(_ac, _jv_start_idx, _jv_end_idx, _cf_max)

                # Row 4: Module Cashflow Consolidation = LC + DC + AC
                module_consolidation_jv = _row_add(lc_jv, dc_jv, ac_jv)

                # aaa, Resolve Land In Kind flag aaa,
                _lik_flag_cf = chosen_vehicle_inputs.get("lik_override") if chosen_vehicle_inputs else None
                if _lik_flag_cf is None:
                    _lik_is_yes_cf = False
                elif isinstance(_lik_flag_cf, bool):
                    _lik_is_yes_cf = _lik_flag_cf
                elif isinstance(_lik_flag_cf, (int, float)):
                    _lik_is_yes_cf = bool(_lik_flag_cf)
                else:
                    _lik_is_yes_cf = str(_lik_flag_cf).strip().lower() in ("yes", "true", "1")

                # aaa, Row 6: Land In Kind - JV aaa,
                # aaa, Row 7: Land Cost - JV aaa,
                # Mutually exclusive: only one populates.
                # Whichever is active is negative (economic land outflow at JV start).
                _lik_total = sum(_to_float(v) for v in _lik_raw)

                if _lik_is_yes_cf:
                    # Land is contributed in-kind aa a LIK row = negative at JV start, Land Cost = zeros
                    land_in_kind_jv = _zeros(_cf_max)
                    if _jv_start_idx is not None and 0 <= _jv_start_idx < _cf_max and _lik_total != 0:
                        land_in_kind_jv[_jv_start_idx] = -abs(_lik_total)
                    land_cost_jv = _zeros(_cf_max)
                else:
                    # Land is cash/expensed aa a Land Cost row = negative at JV start, LIK = zeros
                    land_in_kind_jv = _zeros(_cf_max)
                    land_cost_jv = _zeros(_cf_max)
                    if _jv_start_idx is not None and 0 <= _jv_start_idx < _cf_max and _lik_total != 0:
                        land_cost_jv[_jv_start_idx] = -abs(_lik_total)

                # aaa, Row 9: Total FCFF before Financing and SPV Related Cost - JV aaa,
                # CASE A (LIK=Yes): = Module Consolidation (land is non-cash, excluded)
                # CASE B (LIK=No):  = Module Consolidation + Land Cost - JV (land IS cash outflow)
                if _lik_is_yes_cf:
                    total_fcff_jv = list(module_consolidation_jv)
                else:
                    total_fcff_jv = _row_add(module_consolidation_jv, land_cost_jv)

                # aaa, Row 10: Total FCFF ... (Including Land inkind) aaa,
                # CASE A (LIK=Yes): = Total FCFF + Land In Kind - JV
                # CASE B (LIK=No):  = same as Total FCFF (land already included, no LIK)
                if _lik_is_yes_cf:
                    total_fcff_incl_lik_jv = _row_add(total_fcff_jv, land_in_kind_jv)
                else:
                    total_fcff_incl_lik_jv = list(total_fcff_jv)

                # aaa, Map template labels to data aaa,
                _norm_cf = lambda s: " ".join(s.lower().split())
                _cf_data_lookup: Dict[str, List[float]] = {
                    _norm_cf("Land Co Free Cashflow - JV"):                                                        lc_jv,
                    _norm_cf("Dev Co Free Cashflow - JV"):                                                         dc_jv,
                    _norm_cf("Asset Co Free Cashflow - JV"):                                                       ac_jv,
                    _norm_cf("Module Cashflow Consolidation before Financing and  SPV Related Cost"):               module_consolidation_jv,
                    _norm_cf("Land In Kind - JV"):                                                                 land_in_kind_jv,
                    _norm_cf("Land Cost - JV"):                                                                    land_cost_jv,
                    _norm_cf("Total FCFF before Financing and  SPV Related Cost - JV"):                             total_fcff_jv,
                    _norm_cf("Total FCFF before Financing and  SPV Related Cost - JV  (Including Land inkind)"):    total_fcff_incl_lik_jv,
                }

                blank_row = [""] * _cf_max
                cashflows_names = []
                cashflows_me_data = []

                for ti, raw_name in enumerate(raw_cashflows_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_cf(label_str) if label_str else ""

                    if norm_label and norm_label in _cf_data_lookup:
                        cashflows_names.append(label_str)
                        cashflows_me_data.append(list(_cf_data_lookup[norm_label]))
                        total = sum(_cf_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        cashflows_names.append(label_str if label_str else "0")
                        cashflows_me_data.append(list(blank_row))


                cashflows_ye_data, _ = _monthly_to_yearly(cashflows_me_data, _cf_max, _start_month)
            else:
                pass
        else:
            pass

        # aaa, 7c. Build Project Cost section (o.jv.project.cost.*) aaa,
        # This section is yearly-only.  Row order from the name manager:
        #   1. Total FCFF before Financing and  SPV Related Cost - JV
        #   2. Infra Cost
        #   3. Vertical Cost
        #   4. Land Cost
        #   5. (blank structural row if present)
        #   6. Total Project Cost
        # Initialise cost variables at outer scope so step 7d can access them
        infra_cost: Optional[List[float]] = None
        vertical_cost: Optional[List[float]] = None
        land_cost: Optional[List[float]] = None
        total_proj_cost: Optional[List[float]] = None
        total_fcff_spv: Optional[List[float]] = None
        raw_project_cost_names = _read_array(out_df, OUT_PROJECT_COST_NAMES)
        project_cost_names: Optional[List[str]] = None
        project_cost_me_data: Optional[List[list]] = None
        project_cost_ye_data: Optional[List[list]] = None

        if raw_project_cost_names:
            for ti, nm in enumerate(raw_project_cost_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            _pc_max = max((len(r) for r in output_fcff.values()), default=0)

            if _pc_max > 0:
                # aaa, Resolve JV date window (same as 7b) aaa,
                _pc_jv_start_date = chosen_vehicle_inputs.get("jv_start_date") if chosen_vehicle_inputs else None
                _pc_fund_tenure = chosen_vehicle_inputs.get("fund_tenure", 0) if chosen_vehicle_inputs else 0
                _pc_fund_tenure = _to_float(_pc_fund_tenure) if _pc_fund_tenure else 0
                _pc_jv_start_idx = _date_to_month_index(_pc_jv_start_date, model_start)
                if _pc_jv_start_idx is not None and _pc_fund_tenure > 0:
                    _pc_jv_end_idx = _pc_jv_start_idx + int(_pc_fund_tenure)
                else:
                    _pc_jv_end_idx = None

                # aaa, Helper: apply JV date window (reuse pattern from 7b) aaa,
                def _apply_jv_window_pc(row: List[float], start_idx, end_idx, n: int) -> List[float]:
                    masked = [0.0] * n
                    s = start_idx if start_idx is not None else 0
                    e = end_idx if end_idx is not None else n
                    for t in range(max(s, 0), min(e, n)):
                        masked[t] = _to_float(row[t])
                    return masked

                # aaa, Source data aaa,
                # Normaliser used throughout this section
                _norm_pc = lambda s: " ".join(s.lower().split())

                # Infra Cost = LandCo CFI (Cashflow from Investments)
                _lc_cfi_raw = _pad(output_fcff.get("LandCo_CFI", []), _pc_max)
                infra_cost = _apply_jv_window_pc(_lc_cfi_raw, _pc_jv_start_idx, _pc_jv_end_idx, _pc_max)

                # Vertical Cost = DevCo CFI (Cashflow from Investments)
                _dc_cfi_raw = _pad(output_fcff.get("DevCo_CFI", []), _pc_max)
                vertical_cost = _apply_jv_window_pc(_dc_cfi_raw, _pc_jv_start_idx, _pc_jv_end_idx, _pc_max)

                # Land Cost = sourced from "Land Cost - JV" in the cashflows
                # section (step 7b).  This is a one-time hit on the JV start
                # date only, already enforced negative in step 7b.
                land_cost = None
                if cashflows_me_data and cashflows_names:
                    _land_jv_norm = _norm_pc("Land Cost - JV")
                    for _li, _ln in enumerate(cashflows_names):
                        if _norm_pc(str(_ln)) == _land_jv_norm:
                            land_cost = [_to_float(v) for v in cashflows_me_data[_li]]
                            break
                if land_cost is None:
                    # Fallback: one-time hit on JV start date from raw Land_In_Kind
                    _land_cost_raw = _pad(output_fcff.get("Land_In_Kind", []), _pc_max)
                    land_cost = [0.0] * _pc_max
                    if _pc_jv_start_idx is not None and 0 <= _pc_jv_start_idx < _pc_max:
                        _lik_sum = sum(_to_float(v) for v in _land_cost_raw)
                        land_cost[_pc_jv_start_idx] = -abs(_lik_sum) if _lik_sum != 0 else 0.0
                land_cost = _pad(land_cost, _pc_max)
                # Convention: land costs are always negative (outflow).
                # Defensive: only negate non-zero values, avoid double-negation.
                land_cost = [-abs(v) if v != 0.0 else 0.0 for v in land_cost]

                # Total Project Cost = Infra Cost + Vertical Cost + Land Cost
                total_proj_cost = _row_add(_row_add(infra_cost, vertical_cost), land_cost)

                # aaa, Row 1: Total FCFF before Financing and  SPV Related Cost - JV aaa,
                # Source: upstream JV cashflow section's
                # "Total FCFF before Financing and SPV Related Cost" (built in 7b).
                # Then apply Land In Kind condition.
                _lik_flag_raw = chosen_vehicle_inputs.get("lik_override") if chosen_vehicle_inputs else None
                # Robust check: handle "yes"/"Yes"/"YES", True, 1, etc.
                if _lik_flag_raw is None:
                    _lik_is_yes = False
                elif isinstance(_lik_flag_raw, bool):
                    _lik_is_yes = _lik_flag_raw
                elif isinstance(_lik_flag_raw, (int, float)):
                    _lik_is_yes = bool(_lik_flag_raw)
                else:
                    _lik_is_yes = str(_lik_flag_raw).strip().lower() in ("yes", "true", "1")

                # Fetch upstream total FCFF explicitly from the cashflows section
                _total_fcff_jv_raw = None
                if cashflows_me_data and cashflows_names:
                    _target_norm = _norm_pc("Total FCFF before Financing and SPV Related Cost - JV")
                    for _ci, _cn in enumerate(cashflows_names):
                        if _norm_pc(str(_cn)) == _target_norm:
                            _total_fcff_jv_raw = cashflows_me_data[_ci]
                            break

                if _total_fcff_jv_raw is None:
                    # Fallback: compute from entity FCFFs with JV window
                    _lc_f = _apply_jv_window_pc(_pad(output_fcff.get("LandCo_FCFF", []), _pc_max), _pc_jv_start_idx, _pc_jv_end_idx, _pc_max)
                    _dc_f = _apply_jv_window_pc(_pad(output_fcff.get("DevCo_FCFF", []), _pc_max), _pc_jv_start_idx, _pc_jv_end_idx, _pc_max)
                    _ac_f = _apply_jv_window_pc(_pad(output_fcff.get("AssetCo_FCFF", []), _pc_max), _pc_jv_start_idx, _pc_jv_end_idx, _pc_max)
                    _total_fcff_jv_raw = _row_add(_row_add(_lc_f, _dc_f), _ac_f)

                _total_fcff_jv_padded = _pad([_to_float(v) for v in _total_fcff_jv_raw], _pc_max)

                if _lik_is_yes:
                    # Land is in-kind aa a Total FCFF SPV = upstream Total FCFF unchanged
                    total_fcff_spv = list(_total_fcff_jv_padded)
                else:
                    # Land is NOT in-kind aa a add land cost (already negative)
                    total_fcff_spv = _row_add(_total_fcff_jv_padded, land_cost)


                # aaa, Map template labels to data (handle repeated labels safely) aaa,
                _pc_data_list: List[Tuple[str, List[float]]] = [
                    (_norm_pc("Total FCFF before Financing and SPV Related Cost - JV"), total_fcff_spv),
                    (_norm_pc("Infra Cost"),           infra_cost),
                    (_norm_pc("Vertical Cost"),        vertical_cost),
                    (_norm_pc("Land Cost"),             land_cost),
                    (_norm_pc("Total Project Cost"),    total_proj_cost),
                ]
                # Build a lookup that pops consumed entries for repeated labels
                _pc_consume_counts: Dict[str, int] = {}
                _pc_data_by_key: Dict[str, List[List[float]]] = {}
                for nk, drow in _pc_data_list:
                    _pc_data_by_key.setdefault(nk, []).append(drow)

                blank_row_pc = [""] * _pc_max
                project_cost_names = []
                project_cost_me_data = []

                for ti, raw_name in enumerate(raw_project_cost_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_pc(label_str) if label_str else ""

                    if norm_label and norm_label in _pc_data_by_key:
                        consume_idx = _pc_consume_counts.get(norm_label, 0)
                        available = _pc_data_by_key[norm_label]
                        if consume_idx < len(available):
                            row_data = available[consume_idx]
                        else:
                            # Repeated beyond what we have  reuse last
                            row_data = available[-1]
                        _pc_consume_counts[norm_label] = consume_idx + 1

                        project_cost_names.append(label_str)
                        project_cost_me_data.append(list(row_data))
                        total = sum(_to_float(v) for v in row_data)
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        project_cost_names.append(label_str if label_str else "0")
                        project_cost_me_data.append(list(blank_row_pc))


                # aaa, Defence: ensure Total FCFF SPV row is explicitly populated aaa,
                # The first template row should be Total FCFF SPV.  If the
                # normalised label didn't match (e.g. double-space in name
                # manager vs single-space in key), force-populate row 0.
                _fcff_spv_key = _norm_pc("Total FCFF before Financing and SPV Related Cost - JV")
                if _pc_consume_counts.get(_fcff_spv_key, 0) == 0 and len(project_cost_me_data) > 0:
                    project_cost_me_data[0] = list(total_fcff_spv)

                # Project cost is yearly only  derive from monthly
                project_cost_ye_data, _ = _monthly_to_yearly(project_cost_me_data, _pc_max, _start_month)
            else:
                pass
        else:
            pass

        # aaa, 7d. Build Asset Sales Value + Fees sections aaa,
        # Asset Sales Value is now a separate output section:
        #   o.jv.assetsale.values / o.jv.assetsales.me / o.jv.assetsales.ye
        # Fees section (o.jv.fees.*) rows:
        #   1. JV Setup, Structuring & Acquisition Fees  (% of land cost at JV start)
        #   2. JV Liquidation & Exit-related Fees        (% of sales value at JV exit)
        #   3. Other Fees                                (% of total project cost, spread equally)
        #   4. (blank)
        #   5. Total Fees                                (sum of rows 1-3)

        # -- Asset Sales Value output --
        raw_asset_sales_names = _read_array(out_df, OUT_ASSET_SALES_VALUES)
        asset_sales_names: Optional[List[str]] = None
        asset_sales_me_data: Optional[List[list]] = None
        asset_sales_ye_data: Optional[List[list]] = None

        # -- Fees output --
        raw_fees_names = _read_array(out_df, OUT_FEES_NAMES)
        fees_names: Optional[List[str]] = None
        fees_me_data: Optional[List[list]] = None
        fees_ye_data: Optional[List[list]] = None
        # Elevate total_fees_cf so step 7e (Total Funding) can access it
        total_fees_cf: Optional[List[float]] = None
        # Elevate individual fee rows so step 7d-post (Addl Equity recompute) can access them
        setup_fee_cf: Optional[List[float]] = None
        liq_fee_cf: Optional[List[float]] = None
        other_fee_cf: Optional[List[float]] = None

        # Compute asset sales and fees together (fees depend on sales value)
        _fee_max = max((len(r) for r in output_fcff.values()), default=0)

        if _fee_max > 0 and chosen_vehicle_inputs:
            # aaa, Resolve JV date window aaa,
            _fee_jv_start_date = chosen_vehicle_inputs.get("jv_start_date")
            _fee_fund_tenure = _to_float(chosen_vehicle_inputs.get("fund_tenure", 0) or 0)
            _fee_jv_start_idx = _date_to_month_index(_fee_jv_start_date, model_start)
            if _fee_jv_start_idx is not None and _fee_fund_tenure > 0:
                _fee_jv_end_idx = _fee_jv_start_idx + int(_fee_fund_tenure)
            else:
                _fee_jv_end_idx = None

            # aaa, Fee percentages aaa,
            _setup_fee_pct = _to_float(chosen_vehicle_inputs.get("jv_setup_fee", 0))
            _liq_fee_pct = _to_float(chosen_vehicle_inputs.get("jv_liquidation_fee", 0))
            _other_fee_pct = _to_float(chosen_vehicle_inputs.get("other_fees", 0))


            # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            # Asset Sales Value computation
            # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            _asset_sales_cf = [0.0] * _fee_max
            _chosen_assets = jv_groups.get(chosen_vehicle, [])

            for _sv_asset in _chosen_assets:
                _sv_flags = selection["module_flags"].get(_sv_asset, {})
                _has_ac = _sv_flags.get("assetco", False)
                _has_dc = _sv_flags.get("devco", False)
                _has_lc = _sv_flags.get("landco", False)

                _sv_row: List[float] = []

                if _has_ac:
                    _ac_entry = _find_assetco_entry(assetco_per_asset, _sv_asset)
                    if _ac_entry:
                        _sv_row = _extract_item_from_assetco_section(
                            _ac_entry, "Cashflow from Investments",
                            _ASSETCO_SALES_CANDIDATES)
                        if _sv_row:
                            pass
                elif _has_dc:
                    _dc_idx = _find_asset_index(devco_data, _sv_asset)
                    if _dc_idx is not None:
                        _sv_row = _extract_item_from_lc_dc_section(
                            devco_data, "Cashflow from Operations",
                            _dc_idx, _DEVCO_SALES_CANDIDATES)
                        if _sv_row:
                            pass
                elif _has_lc:
                    _lc_idx = _find_asset_index(landco_data, _sv_asset)
                    if _lc_idx is not None:
                        _sv_cfo = _extract_item_from_lc_dc_section(
                            landco_data, "Cashflow from Operations",
                            _lc_idx, _LANDCO_SALES_CANDIDATES_CFO)
                        _sv_cfi = _extract_item_from_lc_dc_section(
                            landco_data, "Cashflow from Investments",
                            _lc_idx, _LANDCO_SALES_CANDIDATES_CFI)
                        _sv_row = _row_add(
                            _pad(_sv_cfo, _fee_max),
                            _pad(_sv_cfi, _fee_max))
                        if sum(abs(v) for v in _sv_row) > 0.01:
                            pass

                if _sv_row:
                    _asset_sales_cf = _row_add(_asset_sales_cf, _pad(_sv_row, _fee_max))

            # Apply JV window to sales value
            def _apply_jv_window_fee(row: List[float], start_idx, end_idx, n: int) -> List[float]:
                masked = [0.0] * n
                s = start_idx if start_idx is not None else 0
                e = end_idx if end_idx is not None else n
                for t in range(max(s, 0), min(e, n)):
                    masked[t] = _to_float(row[t])
                return masked

            _asset_sales_cf = _apply_jv_window_fee(
                _asset_sales_cf, _fee_jv_start_idx, _fee_jv_end_idx, _fee_max)


            # aaa, Build Asset Sales output section aaa,
            if raw_asset_sales_names:
                _norm_as = lambda s: " ".join(s.lower().split())
                _as_data_lookup: Dict[str, List[float]] = {
                    _norm_as("Asset Sales Value"): _asset_sales_cf,
                }
                blank_row_as = [""] * _fee_max
                asset_sales_names = []
                asset_sales_me_data = []

                for ti, raw_name in enumerate(raw_asset_sales_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_as(label_str) if label_str else ""
                    if norm_label and norm_label in _as_data_lookup:
                        asset_sales_names.append(label_str)
                        asset_sales_me_data.append(list(_as_data_lookup[norm_label]))
                        _total = sum(_as_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        asset_sales_names.append(label_str if label_str else "0")
                        asset_sales_me_data.append(list(blank_row_as))

                asset_sales_ye_data, _ = _monthly_to_yearly(asset_sales_me_data, _fee_max, _start_month)
            else:
                pass

            # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            # Fee computation
            # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

            # aaa, Row 1: JV Setup, Structuring & Acquisition Fees aaa,
            # = % of Acquisition Price (land cost / land in-kind) at JV start date.
            # When LIK=Yes, land_cost is zero and the acquisition price is
            # the land_in_kind_jv value; check that path first.
            _fee_land_cost_total = 0.0
            _fee_land_source = "none"
            # Try Land In Kind - JV first (populated when LIK=Yes)
            if land_in_kind_jv is not None and sum(abs(_to_float(v)) for v in land_in_kind_jv) > 0:
                _fee_land_cost_total = sum(abs(_to_float(v)) for v in land_in_kind_jv)
                _fee_land_source = "land_in_kind_jv"
            elif land_cost is not None and sum(abs(v) for v in land_cost) > 0:
                _fee_land_cost_total = sum(abs(v) for v in land_cost)
                _fee_land_source = "land_cost"
            elif land_cost_jv is not None and sum(abs(_to_float(v)) for v in land_cost_jv) > 0:
                _fee_land_cost_total = sum(abs(_to_float(v)) for v in land_cost_jv)
                _fee_land_source = "land_cost_jv"
            elif cashflows_me_data and cashflows_names:
                _land_jv_norm_fee = " ".join("Land Cost - JV".lower().split())
                for _fi, _fn in enumerate(cashflows_names):
                    if " ".join(str(_fn).lower().split()) == _land_jv_norm_fee:
                        _fee_land_cost_total = sum(abs(_to_float(v)) for v in cashflows_me_data[_fi])
                        _fee_land_source = "cashflows Land Cost - JV"
                        break

            setup_fee_cf = [0.0] * _fee_max
            if _fee_jv_start_idx is not None and 0 <= _fee_jv_start_idx < _fee_max:
                _setup_amount = _setup_fee_pct * _fee_land_cost_total
                setup_fee_cf[_fee_jv_start_idx] = -abs(_setup_amount) if _setup_amount != 0 else 0.0


            # aaa, Row 2: JV Liquidation & Exit-related Fees aaa,
            # = % of Sales Value at JV exit date
            liq_fee_cf = [0.0] * _fee_max
            _fee_exit_idx = _fee_jv_end_idx
            if _fee_exit_idx is not None:
                _fee_exit_idx = min(_fee_exit_idx, _fee_max) - 1
                if _fee_exit_idx < 0:
                    _fee_exit_idx = None

            if _fee_exit_idx is not None and 0 <= _fee_exit_idx < _fee_max:
                _sales_total_abs = sum(abs(v) for v in _asset_sales_cf)
                _liq_amount = _liq_fee_pct * _sales_total_abs
                liq_fee_cf[_fee_exit_idx] = -abs(_liq_amount) if _liq_amount != 0 else 0.0
            else:
                pass

            # aaa, Row 3: Other Fees aaa,
            # = % of Total Project Cost, spread equally across JV period
            other_fee_cf = [0.0] * _fee_max
            _tpc_base = total_proj_cost if total_proj_cost is not None else [0.0] * _fee_max
            _tpc_base = _pad(_tpc_base, _fee_max)
            _tpc_total = sum(abs(_to_float(v)) for v in _tpc_base)

            _other_total = _other_fee_pct * _tpc_total
            if _other_total != 0 and _fee_jv_start_idx is not None:
                _spread_start = max(_fee_jv_start_idx, 0)
                _spread_end = min(_fee_jv_end_idx, _fee_max) if _fee_jv_end_idx is not None else _fee_max
                _spread_months = _spread_end - _spread_start
                if _spread_months > 0:
                    _monthly_fee = _other_total / _spread_months
                    for t in range(_spread_start, _spread_end):
                        other_fee_cf[t] = -abs(_monthly_fee)
                else:
                    pass
            else:
                pass

            # aaa, Row 5: Total Fees = Setup + Liquidation + Other aaa,
            total_fees_cf = _row_add(_row_add(setup_fee_cf, liq_fee_cf), other_fee_cf)

            # aaa, Fees template alignment aaa,
            if raw_fees_names:
                for ti, nm in enumerate(raw_fees_names):
                    display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

                _norm_fee = lambda s: " ".join(s.lower().split())
                # Also build a variant with '&' replaced for fuzzy matching
                _norm_fee_no_amp = lambda s: " ".join(s.lower().replace("&", "and").split())
                _fee_data_list: List[Tuple[str, List[float]]] = [
                    (_norm_fee("JV Setup, Structuring & Acquisition Fees"), setup_fee_cf),
                    (_norm_fee("JV Liquidation & Exit-related Fees"),       liq_fee_cf),
                    (_norm_fee("Other Fees"),                               other_fee_cf),
                    (_norm_fee("Total Fees"),                               total_fees_cf),
                ]
                _fee_data_by_key: Dict[str, List[List[float]]] = {}
                for nk, drow in _fee_data_list:
                    _fee_data_by_key.setdefault(nk, []).append(drow)
                    # Also register the no-ampersand variant for fuzzy matching
                    nk_no_amp = _norm_fee_no_amp(nk.replace("&", "and"))
                    if nk_no_amp != nk:
                        _fee_data_by_key.setdefault(nk_no_amp, []).append(drow)
                _fee_consume_counts: Dict[str, int] = {}

                blank_row_fee = [""] * _fee_max
                fees_names = []
                fees_me_data = []

                for ti, raw_name in enumerate(raw_fees_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_fee(label_str) if label_str else ""
                    # Try exact match first, then fuzzy (& aa a and)
                    matched_key = None
                    if norm_label and norm_label in _fee_data_by_key:
                        matched_key = norm_label
                    elif norm_label:
                        alt = _norm_fee_no_amp(label_str)
                        if alt in _fee_data_by_key:
                            matched_key = alt

                    if matched_key:
                        _ci = _fee_consume_counts.get(matched_key, 0)
                        entries = _fee_data_by_key[matched_key]
                        if _ci < len(entries):
                            fees_names.append(label_str)
                            fees_me_data.append(list(entries[_ci]))
                            _fee_consume_counts[matched_key] = _ci + 1
                            _total = sum(entries[_ci])
                        else:
                            fees_names.append(label_str if label_str else "0")
                            fees_me_data.append(list(blank_row_fee))
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        fees_names.append(label_str if label_str else "0")
                        fees_me_data.append(list(blank_row_fee))


                fees_ye_data, _ = _monthly_to_yearly(fees_me_data, _fee_max, _start_month)

                # aaa, Fee output validation aaa,
                _setup_month_total = sum(setup_fee_cf)
                _setup_first_nonzero = next((i for i, v in enumerate(setup_fee_cf) if abs(v) > 0.01), None)
                _matched_setup = any(
                    "setup" in _norm_fee(fn) for fn in fees_names if fn and fn != "0"
                )
                if fees_ye_data:
                    for ri, (fn, yr_row) in enumerate(zip(fees_names, fees_ye_data)):
                        yr_total = sum(_to_float(v) for v in yr_row)
                        if abs(yr_total) > 0.01 or "setup" in fn.lower():
                            pass

            else:
                pass
        else:
            pass

        # aaa, 7d-post. Recompute Additional Equity Requirement using output-level fees aaa,
        # The original computation in _compute_cff() used CFF-level fees.
        # Now override with the exact user specification:
        #   Cash Balance After Capital Infusion =
        #       Opening Balance
        #     + Total FCFF before Financing and SPV Related Cost - JV   (total_fcff_jv  includes land cost when LIK=No)
        #     + Cashflow From Financing Activity                        (cff_rows)
        #     + Equity Funding                                          (cff_rows)
        #     + JV Setup Fee                                            (setup_fee_cf, already signed negative)
        #     + JV Liquidation Fee                                      (liq_fee_cf, already signed negative)
        #     + Other Fees                                              (other_fee_cf, already signed negative)
        #   Additional equity requirement = max(0, - Cash Balance After Capital Infusion)
        #   Closing Balance = Cash Balance After Capital Infusion + Additional equity requirement
        if cff_rows and max_periods > 0:
            _ae_max = max_periods
            _ae_zeros = _zeros(_ae_max)

            # Source rows  use total_fcff_jv (NOT module_consolidation_jv)
            # so that land cost is already included when LIK=No
            _ae_fcff = _pad(list(total_fcff_jv), _ae_max) if total_fcff_jv else list(_ae_zeros)
            _ae_cff_activity = list(cff_rows.get("_cashflow_from_financing_activity", _ae_zeros))
            _ae_equity = list(cff_rows.get("_equity_funding", _ae_zeros))
            _ae_setup = _pad(list(setup_fee_cf), _ae_max) if setup_fee_cf else list(_ae_zeros)
            _ae_liq = _pad(list(liq_fee_cf), _ae_max) if liq_fee_cf else list(_ae_zeros)
            _ae_other = _pad(list(other_fee_cf), _ae_max) if other_fee_cf else list(_ae_zeros)

            # Roll-forward
            _ae_opening = _zeros(_ae_max)
            _ae_cash_bal = _zeros(_ae_max)
            _ae_req = _zeros(_ae_max)
            _ae_closing = _zeros(_ae_max)

            for t in range(_ae_max):
                if t > 0:
                    _ae_opening[t] = _ae_closing[t - 1]

                # Cash Balance After Capital Infusion = period flows ONLY.
                # Opening balance is NOT included here because prior shortfalls
                # were already funded by additional equity (Closing >= 0).
                # Including opening would double-count and cause cascading inflation.
                _ae_cash_bal[t] = (
                    _ae_fcff[t]
                    + _ae_cff_activity[t]
                    + _ae_equity[t]
                    + _ae_setup[t]
                    + _ae_liq[t]
                    + _ae_other[t]
                )

                # Additional equity requirement = max(0, -cash_bal)
                if _ae_cash_bal[t] < 0:
                    _ae_req[t] = abs(_ae_cash_bal[t])
                else:
                    _ae_req[t] = 0.0

                # Closing = opening + cash_bal + addl equity
                _ae_closing[t] = _ae_opening[t] + _ae_cash_bal[t] + _ae_req[t]

            # Override cff_rows with recomputed values
            cff_rows["_addl_eq_opening"] = _ae_opening
            cff_rows["_cash_bal_after_infusion"] = _ae_cash_bal
            cff_rows["_addl_eq_req"] = _ae_req
            cff_rows["_addl_eq_closing"] = _ae_closing

            # Recompute Additional Equity Drawn (mirrors requirement)
            _cash_gp_pct = cff_rows.get("_cash_gp_pct", [0.0])[0] if isinstance(cff_rows.get("_cash_gp_pct"), list) else 0.0
            _cash_lp_pct = cff_rows.get("_cash_lp_pct", [0.0])[0] if isinstance(cff_rows.get("_cash_lp_pct"), list) else 0.0
            # Fallback: derive from equity schedule if not stored
            if _cash_gp_pct == 0.0 and _cash_lp_pct == 0.0:
                _eq_total = sum(abs(v) for v in cff_rows.get("_equity_funding", _ae_zeros))
                _gp_total = sum(abs(v) for v in cff_rows.get("_gp_commitment", _ae_zeros))
                if _eq_total > 0.01:
                    _cash_gp_pct = _gp_total / _eq_total
                    _cash_lp_pct = 1.0 - _cash_gp_pct

            _ae_addl_funding = list(_ae_req)
            _ae_gp_addl = [v * _cash_gp_pct for v in _ae_addl_funding]
            _ae_lp_addl = [v * _cash_lp_pct for v in _ae_addl_funding]

            cff_rows["_addl_equity_funding"] = _ae_addl_funding
            cff_rows["_gp_addl_commit"] = _ae_gp_addl
            cff_rows["_lp_addl_commit"] = _ae_lp_addl

            # Recompute Total Commitment
            _ae_base_equity = list(cff_rows.get("_equity_funding", _ae_zeros))
            _ae_base_gp = list(cff_rows.get("_gp_commitment", _ae_zeros))
            _ae_base_lp = list(cff_rows.get("_lp_commitment", _ae_zeros))
            _ae_lik = list(cff_rows.get("_lik_commitment", _ae_zeros))
            _ae_gp_lik = list(cff_rows.get("_gp_lik_commit", _ae_zeros))
            _ae_lp_lik = list(cff_rows.get("_lp_lik_commit", _ae_zeros))

            cff_rows["_total_equity_funding"] = _row_add(_ae_base_equity, _ae_addl_funding, _ae_lik)
            cff_rows["_total_gp_commit"] = _row_add(_ae_base_gp, _ae_gp_addl, _ae_gp_lik)
            cff_rows["_total_lp_commit"] = _row_add(_ae_base_lp, _ae_lp_addl, _ae_lp_lik)

            _ae_first_nz = next((t for t in range(_ae_max) if _ae_req[t] > 0.01), None)

            # aaa, First 24 monthly values for key rows aaa,
            _p24 = lambda r: [round(v, 2) for v in r[:24]]
            _cb_24     = _p24(_ae_cash_bal)
            _aeq_24    = _p24(_ae_req)

            # aaa, Yearly values (SUM for both cash bal and req  both are flows) aaa,
            _yr_bounds_dbg = _compute_year_boundaries(_ae_max, _start_month)
            _cb_ye_dbg = []
            _aeq_ye_dbg = []
            for _ys, _ye_e in _yr_bounds_dbg:
                _cb_ye_dbg.append(round(sum(_ae_cash_bal[_ys:_ye_e]), 2))
                _aeq_ye_dbg.append(round(sum(_ae_req[_ys:_ye_e]), 2))

        # aaa, 7e. Build Total Funding Required section (o.jv.total.funding.*) aaa,
        # Rows (from updated template):
        #   1. Opening Balance_Funding requirement
        #   2. Net Cashflows_Funding requirement
        #   3. Funding Requirement_Funding requirement
        #   4. Closing Balance_Funding requirement
        #   5. (blank / section spacing)
        #   6. Cashflow Before Financing_Funding requirement
        raw_total_funding_names = _read_array(out_df, OUT_TOTAL_FUNDING_NAMES)
        total_funding_names: Optional[List[str]] = None
        total_funding_me_data: Optional[List[list]] = None
        total_funding_ye_data: Optional[List[list]] = None

        if raw_total_funding_names:
            for ti, nm in enumerate(raw_total_funding_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            _tf_max = max((len(r) for r in output_fcff.values()), default=0)

            if _tf_max > 0:
                _tf_mod   = _pad([_to_float(v) for v in module_consolidation_jv], _tf_max) if module_consolidation_jv is not None else [0.0] * _tf_max
                _tf_lik   = _pad([_to_float(v) for v in land_in_kind_jv], _tf_max)         if land_in_kind_jv is not None else [0.0] * _tf_max
                _tf_lc    = _pad([_to_float(v) for v in land_cost_jv], _tf_max)             if land_cost_jv is not None else [0.0] * _tf_max
                _tf_fees  = _pad([_to_float(v) for v in total_fees_cf], _tf_max)            if total_fees_cf is not None else [0.0] * _tf_max


                net_cashflows_funding = _row_add(_tf_mod, _tf_lik, _tf_lc, _tf_fees)

                # aaa, Row 6: Cashflow Before Financing = Net Cashflows (mirror) aaa,
                cashflow_before_financing = list(net_cashflows_funding)

                # aaa, Rows 1, 3, 4: Opening / Funding Requirement / Closing (monthly roll-forward) aaa,
                opening_balance_funding = [0.0] * _tf_max
                funding_requirement = [0.0] * _tf_max
                closing_balance_funding = [0.0] * _tf_max

                for _t in range(_tf_max):
                    opening_balance_funding[_t] = closing_balance_funding[_t - 1] if _t > 0 else 0.0
                    _pre_funding = opening_balance_funding[_t] + net_cashflows_funding[_t]
                    if _pre_funding < 0:
                        funding_requirement[_t] = abs(_pre_funding)
                    else:
                        funding_requirement[_t] = 0.0
                    closing_balance_funding[_t] = opening_balance_funding[_t] + net_cashflows_funding[_t] + funding_requirement[_t]


                # aaa, Template alignment aaa,
                _norm_tf = lambda s: " ".join(s.lower().split())
                _tf_data_list: List[Tuple[str, List[float]]] = [
                    (_norm_tf("Opening Balance_Funding requirement"),          opening_balance_funding),
                    (_norm_tf("Net Cashflows_Funding requirement"),            net_cashflows_funding),
                    (_norm_tf("Funding Requirement_Funding requirement"),      funding_requirement),
                    (_norm_tf("Closing Balance_Funding requirement"),          closing_balance_funding),
                    (_norm_tf("Cashflow Before Financing_Funding requirement"), cashflow_before_financing),
                ]
                _tf_data_by_key: Dict[str, List[List[float]]] = {}
                for nk, drow in _tf_data_list:
                    _tf_data_by_key.setdefault(nk, []).append(drow)
                _tf_consume_counts: Dict[str, int] = {}

                blank_row_tf = [""] * _tf_max
                total_funding_names = []
                total_funding_me_data = []

                for ti, raw_name in enumerate(raw_total_funding_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_tf(label_str) if label_str else ""

                    if norm_label and norm_label in _tf_data_by_key:
                        _ci = _tf_consume_counts.get(norm_label, 0)
                        entries = _tf_data_by_key[norm_label]
                        if _ci < len(entries):
                            total_funding_names.append(label_str)
                            total_funding_me_data.append(list(entries[_ci]))
                            _tf_consume_counts[norm_label] = _ci + 1
                            _total = sum(entries[_ci])
                        else:
                            total_funding_names.append(label_str if label_str else "0")
                            total_funding_me_data.append(list(blank_row_tf))
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        total_funding_names.append(label_str if label_str else "0")
                        total_funding_me_data.append(list(blank_row_tf))


                # aaa, Yearly conversion aaa,
                # Opening Balance aa a previous year closing (year 0 uses initial opening)
                # Closing Balance aa a last month of that year (NOT sum)
                # Flow rows (Net Cashflows, Funding Req, Cashflow Before Financing)
                # use sums.  Blank/spacer rows stay blank.
                _tf_opening_label = _norm_tf("Opening Balance_Funding requirement")
                _tf_closing_label = _norm_tf("Closing Balance_Funding requirement")
                _yr_bounds_tf = _compute_year_boundaries(_tf_max, _start_month)
                n_years_tf = len(_yr_bounds_tf)
                total_funding_ye_data = []
                for ri, (row, name) in enumerate(zip(total_funding_me_data, total_funding_names)):
                    if all(v == "" for v in row):
                        total_funding_ye_data.append([""] * n_years_tf)
                        continue
                    norm_name = _norm_tf(str(name)) if name else ""
                    if norm_name == _tf_opening_label:
                        # Opening Balance: previous year closing (NOT first month opening)
                        yr_row: List[float] = []
                        for yi, (ys, ye) in enumerate(_yr_bounds_tf):
                            if yi == 0:
                                yr_row.append(_to_float(row[0]))
                            else:
                                prev_last_m = _yr_bounds_tf[yi - 1][1] - 1
                                prev_last_m = min(prev_last_m, len(closing_balance_funding) - 1)
                                yr_row.append(_to_float(closing_balance_funding[prev_last_m]))
                        total_funding_ye_data.append(yr_row)
                    elif norm_name == _tf_closing_label:
                        # Closing Balance: last month of each year
                        yr_row2: List[float] = []
                        for ys, ye in _yr_bounds_tf:
                            last_m = min(ye, len(row)) - 1
                            yr_row2.append(_to_float(row[last_m]))
                        total_funding_ye_data.append(yr_row2)
                    else:
                        # Flow row: sum across the year
                        yr_row = []
                        for ys, ye in _yr_bounds_tf:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        total_funding_ye_data.append(yr_row)

            else:
                pass
        else:
            pass

        # aaa, 7f. Build Term Loan 1 output section (o.jv.termloan1.*) aaa,
        # Named output rows (preserve existing):
        #   1. Debt Issued - Term Loan 1
        #   2. Debt Repaid - Term Loan 1
        #   3. Interest Expense Paid - Term Loan 1
        #   4. Arrangement Fees Paid - Term Loan 1
        # Extended movement schedule rows (added for full loan schedule view):
        #   5. Opening Balance - Term Loan 1
        #   6. Loan Drawn - Term Loan 1
        #   7. Capitalized Interest - Term Loan 1
        #   8. Interest Paid - Term Loan 1
        #   9. Debt Repaid - Term Loan 1 (duplicate label  positional)
        #  10. Closing Balance - Term Loan 1
        # Diagnostic rows:
        #  11. Interest Incurred - Term Loan 1
        #  12. Interest Rate % Applied - Term Loan 1
        #  13. Amortization % Applied - Term Loan 1
        raw_tl1_names = _read_array(out_df, OUT_TL1_NAMES)
        tl1_output_names: Optional[List[str]] = None
        tl1_output_me_data: Optional[List[list]] = None
        tl1_output_ye_data: Optional[List[list]] = None

        if raw_tl1_names:
            for ti, nm in enumerate(raw_tl1_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_tl1 = lambda s: " ".join(s.lower().split())
                _tl1_max = max_periods
                _zeros_tl1 = _zeros(_tl1_max)

                # Map normalised output labels to CFF data (correct sign conventions)
                # Original 4 named rows  gross presentation
                _tl1_data_lookup: Dict[str, List[float]] = {
                    _norm_tl1("Debt Issued - Term Loan 1"):
                        list(cff_rows.get("_tl1_debt_issued", _zeros_tl1)),
                    _norm_tl1("Debt Repaid - Term Loan 1"):
                        _row_negate(cff_rows.get("_tl1_repayments", _zeros_tl1)),
                    _norm_tl1("Interest Expense Paid - Term Loan 1"):
                        _row_negate(cff_rows.get("_tl1_gross_interest_expense", _zeros_tl1)),
                    _norm_tl1("Arrangement Fees Paid - Term Loan 1"):
                        _row_negate(cff_rows.get("_tl1_gross_arr_fee_expense", _zeros_tl1)),
                    # Interest Expense Capitalized (disclosure only  NOT in CFF Activity)
                    _norm_tl1("Interest Expense Capitalized- Term Loan 1"):
                        list(cff_rows.get("_tl1_capitalized_interest", _zeros_tl1)),
                    # Extended movement schedule rows
                    _norm_tl1("Opening Balance - Term Loan 1"):
                        list(cff_rows.get("_tl1_opening_balance", _zeros_tl1)),
                    _norm_tl1("Loan Drawn - Term Loan 1"):
                        list(cff_rows.get("_tl1_loan_additions", _zeros_tl1)),
                    _norm_tl1("Capitalized Interest - Term Loan 1"):
                        list(cff_rows.get("_tl1_capitalized_interest", _zeros_tl1)),
                    _norm_tl1("Capitalized Arrangement Fees - Term Loan 1"):
                        list(cff_rows.get("_tl1_capitalized_arr_fees", _zeros_tl1)),
                    _norm_tl1("Interest Paid - Term Loan 1"):
                        _row_negate(cff_rows.get("_tl1_interest_paid", _zeros_tl1)),
                    _norm_tl1("Closing Balance - Term Loan 1"):
                        list(cff_rows.get("_tl1_closing_balance", _zeros_tl1)),
                    # Diagnostic rows
                    _norm_tl1("Interest Incurred - Term Loan 1"):
                        list(cff_rows.get("_tl1_interest_incurred", _zeros_tl1)),
                    _norm_tl1("Interest Rate % Applied - Term Loan 1"):
                        list(cff_rows.get("_tl1_interest_rate_applied", _zeros_tl1)),
                    _norm_tl1("Amortization % Applied - Term Loan 1"):
                        list(cff_rows.get("_tl1_amort_pct_applied", _zeros_tl1)),
                    # Cashflow From Financing Activity (always produced)
                    _norm_tl1("Cashflow From Financing Activity"):
                        list(cff_rows.get("_cashflow_from_financing_activity", _zeros_tl1)),
                }

                # Balance label tracking for annual roll-forward correction
                _tl1_balance_labels: List[str] = []

                blank_row_tl1 = [""] * _tl1_max
                tl1_output_names = []
                tl1_output_me_data = []

                for ti, raw_name in enumerate(raw_tl1_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_tl1(label_str) if label_str else ""

                    if norm_label and norm_label in _tl1_data_lookup:
                        tl1_output_names.append(label_str)
                        tl1_output_me_data.append(list(_tl1_data_lookup[norm_label]))
                        total = sum(_tl1_data_lookup[norm_label])
                        # Track balance rows for annual fix
                        if "opening balance" in norm_label or "closing balance" in norm_label:
                            _tl1_balance_labels.append(label_str)
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        tl1_output_names.append(label_str if label_str else "0")
                        tl1_output_me_data.append(list(blank_row_tl1))

                # Derive yearly from monthly  then fix balance rows
                tl1_output_ye_data, _ = _monthly_to_yearly(tl1_output_me_data, _tl1_max, _start_month)

                # Annual balance fix: Opening = previous-year-closing,
                # Closing = last-month-of-year (NOT monthly sum)
                _yr_bounds_tl1 = _compute_year_boundaries(_tl1_max, _start_month)
                n_years_tl1 = len(_yr_bounds_tl1)
                for _ri, _rl in enumerate(tl1_output_names):
                    _rl_norm = _norm_tl1(_rl)
                    if "opening balance" in _rl_norm:
                        # Annual opening = previous year closing (NOT first month opening)
                        _tl1_cls_me = list(cff_rows.get("_tl1_closing_balance", _zeros_tl1))
                        yr_row: List[float] = []
                        for _yi, (_ys, _ye) in enumerate(_yr_bounds_tl1):
                            if _yi == 0:
                                yr_row.append(_to_float(tl1_output_me_data[_ri][0]) if _tl1_max > 0 else 0.0)
                            else:
                                prev_last_m = min(_yr_bounds_tl1[_yi - 1][1] - 1, _tl1_max - 1)
                                yr_row.append(_to_float(_tl1_cls_me[prev_last_m]))
                        tl1_output_ye_data[_ri] = yr_row
                    elif "closing balance" in _rl_norm:
                        # Annual closing = last month of that year
                        yr_row2: List[float] = []
                        for _ys, _ye in _yr_bounds_tl1:
                            last_m = min(_ye - 1, _tl1_max - 1)
                            yr_row2.append(_to_float(tl1_output_me_data[_ri][last_m]))
                        tl1_output_ye_data[_ri] = yr_row2
                    elif "interest rate" in _rl_norm or "amortization %" in _rl_norm:
                        # Rate / percentage rows: use last month of year (not sum)
                        yr_row3: List[float] = []
                        for _ys, _ye in _yr_bounds_tl1:
                            last_m = min(_ye - 1, _tl1_max - 1)
                            yr_row3.append(_to_float(tl1_output_me_data[_ri][last_m]))
                        tl1_output_ye_data[_ri] = yr_row3

            else:
                pass
        else:
            pass

        # aaa, 7f2. Build Term Loan 1 Schedule output (o.jv.termloan1schedule.*) aaa,
        # 15-row detailed debt movement schedule
        raw_tl1_sched_names = _read_array(out_df, OUT_TL1_SCHED_NAMES)
        tl1_sched_output_names: Optional[List[str]] = None
        tl1_sched_output_me_data: Optional[List[list]] = None
        tl1_sched_output_ye_data: Optional[List[list]] = None

        if raw_tl1_sched_names:
            for ti, nm in enumerate(raw_tl1_sched_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_t1s = lambda s: " ".join(s.lower().split())
                _t1s_max = max_periods
                _zeros_t1s = _zeros(_t1s_max)

                # EMI = repayments - balloon
                _tl1_emi = [
                    cff_rows.get("_tl1_repayments", _zeros_t1s)[t]
                    - cff_rows.get("_tl1_balloon_payment", _zeros_t1s)[t]
                    for t in range(_t1s_max)
                ]

                # Data lookup keyed by normalised template label
                # Duplicate-looking labels (e.g. Amortization Repayments appearing
                # twice) are handled by the consume-count pattern below.
                _t1s_data_list: List[Tuple[str, List[float]]] = [
                    # === Balance movement block (rows 1-7) ===
                    (_norm_t1s("Opening Balance - Term Loan 1"),
                        list(cff_rows.get("_tl1_opening_balance", _zeros_t1s))),
                    (_norm_t1s("Additions - Term Loan 1"),
                        list(cff_rows.get("_tl1_loan_additions", _zeros_t1s))),
                    (_norm_t1s("Interest Capitalized - Term Loan 1"),
                        list(cff_rows.get("_tl1_capitalized_interest", _zeros_t1s))),
                    (_norm_t1s("Arrangement Fees - Capitalized"),
                        list(cff_rows.get("_tl1_capitalized_arr_fees", _zeros_t1s))),
                    (_norm_t1s("Amortization Repayments - Term Loan 1"),
                        _row_negate(cff_rows.get("_tl1_repayments", _zeros_t1s))),
                    (_norm_t1s("Ballon Payment- Term Loan 1"),
                        _row_negate(cff_rows.get("_tl1_balloon_payment", _zeros_t1s))),
                    (_norm_t1s("Closing Balance"),
                        list(cff_rows.get("_tl1_closing_balance", _zeros_t1s))),
                    # === Cashflow detail block (rows 8-12) ===
                    (_norm_t1s("Interest Incurred - Term Loan 1"),
                        list(cff_rows.get("_tl1_interest_incurred", _zeros_t1s))),
                    (_norm_t1s("Arrangement Fees Incurred - Term Loan 1"),
                        list(cff_rows.get("_tl1_arr_fee_incurred", _zeros_t1s))),
                    (_norm_t1s("Interest Paid - Term Loan 1"),
                        _row_negate(cff_rows.get("_tl1_interest_paid", _zeros_t1s))),
                    (_norm_t1s("Arrangement Fees Paid - Term Loan 1"),
                        _row_negate(cff_rows.get("_tl1_arrangement_fees", _zeros_t1s))),
                    (_norm_t1s("Amortization Repayments - Term Loan 2"),
                        _row_negate(cff_rows.get("_tl2_repayments", _zeros_t1s))),
                    # === Equity infusion block (rows 13-15) ===
                    (_norm_t1s("Equity Infusion for Loan Repayment  - Term Loan 1"),
                        list(_zeros_t1s)),  # not yet modelled  placeholder
                    (_norm_t1s("Equity Infusion for interest payment - Term Loan 1"),
                        list(cff_rows.get("_tl1_eq_infusion_interest", _zeros_t1s))),
                    (_norm_t1s("Equity Infusion for arrangement fees - Term Loan 1"),
                        list(cff_rows.get("_tl1_eq_infusion_arr_fees", _zeros_t1s))),
                ]

                # Build keyed lookup (multi-entry for duplicate-looking labels)
                _t1s_data_by_key: Dict[str, List[List[float]]] = {}
                for nk, drow in _t1s_data_list:
                    _t1s_data_by_key.setdefault(nk, []).append(drow)
                _t1s_consume: Dict[str, int] = {}

                blank_row_t1s = [""] * _t1s_max
                tl1_sched_output_names = []
                tl1_sched_output_me_data = []

                for ti, raw_name in enumerate(raw_tl1_sched_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_t1s(label_str) if label_str else ""

                    if norm_label and norm_label in _t1s_data_by_key:
                        _ci = _t1s_consume.get(norm_label, 0)
                        entries = _t1s_data_by_key[norm_label]
                        if _ci < len(entries):
                            tl1_sched_output_names.append(label_str)
                            tl1_sched_output_me_data.append(list(entries[_ci]))
                            _t1s_consume[norm_label] = _ci + 1
                            _total = sum(entries[_ci])
                        else:
                            tl1_sched_output_names.append(label_str if label_str else "0")
                            tl1_sched_output_me_data.append(list(blank_row_t1s))
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        tl1_sched_output_names.append(label_str if label_str else "0")
                        tl1_sched_output_me_data.append(list(blank_row_t1s))

                # Yearly conversion + balance/rate fix
                tl1_sched_output_ye_data, _ = _monthly_to_yearly(tl1_sched_output_me_data, _t1s_max, _start_month)
                _yr_bounds_t1s = _compute_year_boundaries(_t1s_max, _start_month)
                n_years_t1s = len(_yr_bounds_t1s)
                _tl1_cls_me_sched = list(cff_rows.get("_tl1_closing_balance", _zeros_t1s))
                for _ri, _rl in enumerate(tl1_sched_output_names):
                    _rl_norm = _norm_t1s(_rl) if _rl else ""
                    if "opening balance" in _rl_norm:
                        yr_row: List[float] = []
                        for _yi, (_ys, _ye) in enumerate(_yr_bounds_t1s):
                            if _yi == 0:
                                yr_row.append(_to_float(tl1_sched_output_me_data[_ri][0]) if _t1s_max > 0 else 0.0)
                            else:
                                prev_last_m = min(_yr_bounds_t1s[_yi - 1][1] - 1, _t1s_max - 1)
                                yr_row.append(_to_float(_tl1_cls_me_sched[prev_last_m]))
                        tl1_sched_output_ye_data[_ri] = yr_row
                    elif "closing" in _rl_norm and ("balance" in _rl_norm or "blaance" in _rl_norm):
                        yr_row2: List[float] = []
                        for _ys, _ye in _yr_bounds_t1s:
                            last_m = min(_ye - 1, _t1s_max - 1)
                            yr_row2.append(_to_float(_tl1_cls_me_sched[last_m]))
                        tl1_sched_output_ye_data[_ri] = yr_row2

            else:
                pass
        else:
            pass

        # aaa, 7g. Build Refinancing output section (o.jv.refinancing.*) aaa,
        # Rows:
        #   1. Debt Issued -Re-Financing        aa a loan additions (positive = cash in)
        #   2. Debt Repaid -Re-Financing         aa a repayments (negative = cash out)
        #   3. Interest Expense Paid -Re-Financing aa a interest paid (negative)
        #   4. Arrangement Fees Paid -Re-Financing aa a arrangement fees (negative)
        #   5. [blank structural row if present]
        #   6. Cashflow From Financing Activity  aa a net of above
        raw_refi_names = _read_array(out_df, OUT_REFI_NAMES)
        refi_output_names: Optional[List[str]] = None
        refi_output_me_data: Optional[List[list]] = None
        refi_output_ye_data: Optional[List[list]] = None

        if raw_refi_names:
            for ti, nm in enumerate(raw_refi_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_rf = lambda s: " ".join(s.lower().split())
                _rf_max = max_periods
                _zeros_rf = _zeros(_rf_max)

                # Refinancing Facility individual rows  gross presentation
                _rf_debt_issued = list(cff_rows.get("_tl2_debt_issued", _zeros_rf))
                _rf_debt_repaid = _row_negate(cff_rows.get("_tl2_repayments", _zeros_rf))
                _rf_interest_paid = _row_negate(cff_rows.get("_tl2_gross_interest_expense", _zeros_rf))
                _rf_arr_fees_paid = _row_negate(cff_rows.get("_tl2_gross_arr_fee_expense", _zeros_rf))

                # Cashflow From Financing Activity = TL1 + TL2 combined
                # (excl. capitalized interest)  always produced
                _rf_financing_cf = list(cff_rows.get(
                    "_cashflow_from_financing_activity", _zeros_rf))

                _rf_data_lookup: Dict[str, List[float]] = {
                    _norm_rf("Debt Issued -Re-Financing"):
                        _rf_debt_issued,
                    _norm_rf("Debt Repaid -Re-Financing"):
                        _rf_debt_repaid,
                    _norm_rf("Interest Expense Paid -Re-Financing"):
                        _rf_interest_paid,
                    _norm_rf("Arrangement Fees Paid -Re-Financing"):
                        _rf_arr_fees_paid,
                    # Interest Expense Capitalized (disclosure only  NOT in CFF Activity)
                    _norm_rf("Interest Expense Capitalized -Re-Financing"):
                        list(cff_rows.get("_tl2_capitalized_interest", _zeros_rf)),
                    _norm_rf("Capitalized Interest -Re-Financing"):
                        list(cff_rows.get("_tl2_capitalized_interest", _zeros_rf)),
                    _norm_rf("Capitalized Arrangement Fees -Re-Financing"):
                        list(cff_rows.get("_tl2_capitalized_arr_fees", _zeros_rf)),
                    _norm_rf("Opening Balance -Re-Financing"):
                        list(cff_rows.get("_tl2_opening_balance", _zeros_rf)),
                    _norm_rf("Closing Balance -Re-Financing"):
                        list(cff_rows.get("_tl2_closing_balance", _zeros_rf)),
                    _norm_rf("Cashflow From Financing Activity"):
                        _rf_financing_cf,
                }

                blank_row_rf = [""] * _rf_max
                refi_output_names = []
                refi_output_me_data = []

                for ti, raw_name in enumerate(raw_refi_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_rf(label_str) if label_str else ""

                    if norm_label and norm_label in _rf_data_lookup:
                        refi_output_names.append(label_str)
                        refi_output_me_data.append(list(_rf_data_lookup[norm_label]))
                        total = sum(_rf_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        refi_output_names.append(label_str if label_str else "0")
                        refi_output_me_data.append(list(blank_row_rf))

                # Derive yearly from monthly  then fix balance/rate rows
                refi_output_ye_data, _ = _monthly_to_yearly(refi_output_me_data, _rf_max, _start_month)
                _yr_bounds_rf = _compute_year_boundaries(_rf_max, _start_month)
                n_years_rf = len(_yr_bounds_rf)

                # Annual balance fix: Opening = prev-year-closing, Closing = last-month
                for _ri, _rl in enumerate(refi_output_names):
                    _rl_norm = _norm_rf(_rl) if _rl else ""
                    if "opening balance" in _rl_norm:
                        # Annual opening = previous year closing (NOT first month opening)
                        _tl2_cls_me = list(cff_rows.get("_tl2_closing_balance", _zeros_rf))
                        yr_row: List[float] = []
                        for _yi, (_ys, _ye) in enumerate(_yr_bounds_rf):
                            if _yi == 0:
                                yr_row.append(_to_float(refi_output_me_data[_ri][0]) if _rf_max > 0 else 0.0)
                            else:
                                prev_last_m = min(_yr_bounds_rf[_yi - 1][1] - 1, _rf_max - 1)
                                yr_row.append(_to_float(_tl2_cls_me[prev_last_m]))
                        refi_output_ye_data[_ri] = yr_row
                    elif "closing balance" in _rl_norm:
                        yr_row2: List[float] = []
                        for _ys, _ye in _yr_bounds_rf:
                            last_m = min(_ye - 1, _rf_max - 1)
                            yr_row2.append(_to_float(refi_output_me_data[_ri][last_m]))
                        refi_output_ye_data[_ri] = yr_row2

            else:
                pass
        else:
            pass

        # aaa, 7g2. Build Refinancing Schedule output (o.jv.refinanceschedule.*) aaa,
        # 15-row detailed debt movement schedule for Loan 2
        # Diagnostic: list all out_df named ranges containing "refinance" or "refinancing"
        if not out_df.empty and "name" in out_df.columns:
            _refi_keys = [n for n in out_df["name"].tolist()
                          if "refinanc" in str(n).lower()]
        raw_refi_sched_names = _read_array(out_df, OUT_REFI_SCHED_NAMES)
        refi_sched_output_names: Optional[List[str]] = None
        refi_sched_output_me_data: Optional[List[list]] = None
        refi_sched_output_ye_data: Optional[List[list]] = None

        if raw_refi_sched_names:
            for ti, nm in enumerate(raw_refi_sched_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_r2s = lambda s: " ".join(s.lower().split())
                _r2s_max = max_periods
                _zeros_r2s = _zeros(_r2s_max)

                _r2s_data_list: List[Tuple[str, List[float]]] = [
                    # === Balance movement block (rows 1-7) ===
                    (_norm_r2s("Opening Balance - Refinancing"),
                        list(cff_rows.get("_tl2_opening_balance", _zeros_r2s))),
                    (_norm_r2s("Additions - Refinancing"),
                        list(cff_rows.get("_tl2_loan_additions", _zeros_r2s))),
                    (_norm_r2s("Interest Capitalized - Refinancing"),
                        list(cff_rows.get("_tl2_capitalized_interest", _zeros_r2s))),
                    (_norm_r2s("Arrangement Fees - Refinancing"),
                        list(cff_rows.get("_tl2_capitalized_arr_fees", _zeros_r2s))),
                    (_norm_r2s("Amortization Repayments - Refinancing"),
                        _row_negate(cff_rows.get("_tl2_repayments", _zeros_r2s))),
                    (_norm_r2s("Ballon Payment- Refinancing"),
                        _row_negate(cff_rows.get("_tl2_balloon_payment", _zeros_r2s))),
                    (_norm_r2s("Closing Balance"),
                        list(cff_rows.get("_tl2_closing_balance", _zeros_r2s))),
                    # === Cashflow detail block (rows 8-12) ===
                    (_norm_r2s("Interest Incurred - Refinancing"),
                        list(cff_rows.get("_tl2_interest_incurred", _zeros_r2s))),
                    (_norm_r2s("Arrangement Fees Incurred - Refinancing"),
                        list(cff_rows.get("_tl2_arr_fee_incurred", _zeros_r2s))),
                    (_norm_r2s("Interest Paid - Refinancing"),
                        _row_negate(cff_rows.get("_tl2_interest_paid", _zeros_r2s))),
                    (_norm_r2s("Arrangement Fees Paid - Refinancing"),
                        _row_negate(cff_rows.get("_tl2_arrangement_fees", _zeros_r2s))),
                    (_norm_r2s("Amortization Repayments - Refinancing"),
                        _row_negate(cff_rows.get("_tl2_repayments", _zeros_r2s))),
                    # === Equity infusion block (rows 13-15) ===
                    (_norm_r2s("Equity Infusion for Loan Repayment  - Refinancing"),
                        list(_zeros_r2s)),  # not yet modelled  placeholder
                    (_norm_r2s("Equity Infusion for interest payment - Refinancing"),
                        list(cff_rows.get("_tl2_eq_infusion_interest", _zeros_r2s))),
                    (_norm_r2s("Equity Infusion for arrangement fees - Refinancing"),
                        list(cff_rows.get("_tl2_eq_infusion_arr_fees", _zeros_r2s))),
                    # === Min DSCR row (row 16) ===
                    (_norm_r2s("Min DSCR - Refinancing"),
                        list(cff_rows.get("_tl2_min_dscr", _zeros_r2s))),
                ]

                _r2s_data_by_key: Dict[str, List[List[float]]] = {}
                for nk, drow in _r2s_data_list:
                    _r2s_data_by_key.setdefault(nk, []).append(drow)
                _r2s_consume: Dict[str, int] = {}

                blank_row_r2s = [""] * _r2s_max
                refi_sched_output_names = []
                refi_sched_output_me_data = []

                for ti, raw_name in enumerate(raw_refi_sched_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_r2s(label_str) if label_str else ""

                    if norm_label and norm_label in _r2s_data_by_key:
                        _ci = _r2s_consume.get(norm_label, 0)
                        entries = _r2s_data_by_key[norm_label]
                        if _ci < len(entries):
                            refi_sched_output_names.append(label_str)
                            refi_sched_output_me_data.append(list(entries[_ci]))
                            _r2s_consume[norm_label] = _ci + 1
                            _total = sum(entries[_ci])
                        else:
                            refi_sched_output_names.append(label_str if label_str else "0")
                            refi_sched_output_me_data.append(list(blank_row_r2s))
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        refi_sched_output_names.append(label_str if label_str else "0")
                        refi_sched_output_me_data.append(list(blank_row_r2s))

                # Yearly conversion + balance fix
                refi_sched_output_ye_data, _ = _monthly_to_yearly(refi_sched_output_me_data, _r2s_max, _start_month)
                _yr_bounds_r2s = _compute_year_boundaries(_r2s_max, _start_month)
                n_years_r2s = len(_yr_bounds_r2s)
                _tl2_cls_me_sched = list(cff_rows.get("_tl2_closing_balance", _zeros_r2s))
                for _ri, _rl in enumerate(refi_sched_output_names):
                    _rl_norm = _norm_r2s(_rl) if _rl else ""
                    if "opening balance" in _rl_norm:
                        yr_row: List[float] = []
                        for _yi, (_ys, _ye) in enumerate(_yr_bounds_r2s):
                            if _yi == 0:
                                yr_row.append(_to_float(refi_sched_output_me_data[_ri][0]) if _r2s_max > 0 else 0.0)
                            else:
                                prev_last_m = min(_yr_bounds_r2s[_yi - 1][1] - 1, _r2s_max - 1)
                                yr_row.append(_to_float(_tl2_cls_me_sched[prev_last_m]))
                        refi_sched_output_ye_data[_ri] = yr_row
                    elif "closing" in _rl_norm and ("balance" in _rl_norm or "blaance" in _rl_norm):
                        yr_row2: List[float] = []
                        for _ys, _ye in _yr_bounds_r2s:
                            last_m = min(_ye - 1, _r2s_max - 1)
                            yr_row2.append(_to_float(_tl2_cls_me_sched[last_m]))
                        refi_sched_output_ye_data[_ri] = yr_row2


                # aaa, REFINANCING DIAGNOSTIC: why top refi output may have data while schedule is blank aaa,
                _refi_diag_keys = [
                    "_tl2_opening_balance", "_tl2_loan_additions", "_tl2_closing_balance",
                    "_tl2_interest_paid", "_tl2_repayments", "_tl2_interest_incurred",
                    "_tl2_capitalized_interest", "_tl2_debt_issued",
                    "_cashflow_from_financing_activity",
                ]
                for _rdk in _refi_diag_keys:
                    _rdv = cff_rows.get(_rdk, _zeros_r2s)
                    _rds = sum(abs(v) for v in _rdv)
                    _rd_nz = next((i for i, v in enumerate(_rdv) if abs(v) > 0.01), None)
            else:
                pass
        else:
            pass

        # aaa, 7g3. Build Refinancing Min DSCR output family aaa,
        # (o.jv.refinancingloan.mindscr.*)
        # Emits the threshold assumption only during active refi months.
        raw_refi_mindscr_names = _read_array(out_df, OUT_REFI_MINDSCR_NAMES)
        refi_mindscr_output_names: Optional[List[str]] = None
        refi_mindscr_output_me_data: Optional[List[list]] = None
        refi_mindscr_output_ye_data: Optional[List[list]] = None

        if raw_refi_mindscr_names:
            for ti, nm in enumerate(raw_refi_mindscr_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0 and chosen_vehicle_inputs:
                _norm_rmd = lambda s: " ".join(s.lower().split())
                _rmd_max = max_periods
                _zeros_rmd = _zeros(_rmd_max)

                # Determine active refi window
                _rmd_refi_on = str(
                    chosen_vehicle_inputs.get("tl1_refinancing") or ""
                ).strip().lower() in ("yes", "true", "1")
                _rmd_tl2_start = _date_to_month_index(
                    chosen_vehicle_inputs.get("tl2_start"), model_start)
                _rmd_tl2_end = _date_to_month_index(
                    chosen_vehicle_inputs.get("tl2_end"), model_start)
                _rmd_min_dscr_val = _to_float(
                    chosen_vehicle_inputs.get("tl2_min_dscr", 0.0))

                # Build monthly row: constant within active window, zero outside
                _rmd_row = _zeros(_rmd_max)
                if (_rmd_refi_on
                        and _rmd_tl2_start is not None
                        and _rmd_min_dscr_val > 0):
                    _rmd_end = _rmd_max
                    if _rmd_tl2_end is not None:
                        _rmd_end = min(_rmd_end, _rmd_tl2_end + 1)
                    # Cap at fund/JV end
                    _rmd_ft = _to_float(
                        chosen_vehicle_inputs.get("fund_tenure", 0) or 0)
                    _rmd_js = _date_to_month_index(
                        chosen_vehicle_inputs.get("jv_start_date"),
                        model_start)
                    if _rmd_js is not None and _rmd_ft > 0:
                        _rmd_end = min(_rmd_end, _rmd_js + int(_rmd_ft))
                    _rmd_fc = _date_to_month_index(
                        chosen_vehicle_inputs.get("fund_close_date"),
                        model_start)
                    if _rmd_fc is not None:
                        _rmd_end = min(_rmd_end, _rmd_fc + 1)
                    for _t in range(max(_rmd_tl2_start, 0),
                                    min(_rmd_end, _rmd_max)):
                        _rmd_row[_t] = _rmd_min_dscr_val

                _rmd_data_lookup: Dict[str, List[float]] = {
                    _norm_rmd("Min DSCR - Refinancing"): _rmd_row,
                }

                blank_row_rmd = [""] * _rmd_max
                refi_mindscr_output_names = []
                refi_mindscr_output_me_data = []

                for ti, raw_name in enumerate(raw_refi_mindscr_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_rmd(label_str) if label_str else ""

                    if norm_label and norm_label in _rmd_data_lookup:
                        refi_mindscr_output_names.append(label_str)
                        refi_mindscr_output_me_data.append(
                            list(_rmd_data_lookup[norm_label]))
                        _total = sum(_rmd_data_lookup[norm_label])
                    else:
                        display = (label_str
                                   if label_str and label_str != "0"
                                   else "(blank)")
                        refi_mindscr_output_names.append(
                            label_str if label_str else "0")
                        refi_mindscr_output_me_data.append(
                            list(blank_row_rmd))

                # Yearly: year-end value (threshold, not summed)
                _yr_bounds_rmd = _compute_year_boundaries(_rmd_max, _start_month)
                n_years_rmd = len(_yr_bounds_rmd)
                refi_mindscr_output_ye_data = []
                for row in refi_mindscr_output_me_data:
                    if all(v == "" for v in row):
                        refi_mindscr_output_ye_data.append(
                            [""] * n_years_rmd)
                        continue
                    yr_row: List[float] = []
                    for ys, ye in _yr_bounds_rmd:
                        last_m = min(ye - 1, len(row) - 1)
                        yr_row.append(_to_float(row[last_m]))
                    refi_mindscr_output_ye_data.append(yr_row)

            else:
                pass
        else:
            pass

        # aaa, 7h. Build Equity Schedule output section (o.jv.equity.schedule.*) aaa,
        raw_eq_sched_names = _read_array(out_df, OUT_EQUITY_SCHED_NAMES)
        eq_sched_output_names: Optional[List[str]] = None
        eq_sched_output_me_data: Optional[List[list]] = None
        eq_sched_output_ye_data: Optional[List[list]] = None

        if raw_eq_sched_names:
            for ti, nm in enumerate(raw_eq_sched_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_es = lambda s: " ".join(s.lower().split())
                _es_max = max_periods
                _zeros_es = _zeros(_es_max)

                _es_data_lookup: Dict[str, List[float]] = {
                    _norm_es("Equity Funding"):
                        list(cff_rows.get("_equity_funding", _zeros_es)),
                    _norm_es("GP Commitment"):
                        list(cff_rows.get("_gp_commitment", _zeros_es)),
                    _norm_es("LP Commitment"):
                        list(cff_rows.get("_lp_commitment", _zeros_es)),
                }

                blank_row_es = [""] * _es_max
                eq_sched_output_names = []
                eq_sched_output_me_data = []

                for ti, raw_name in enumerate(raw_eq_sched_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_es(label_str) if label_str else ""

                    if norm_label and norm_label in _es_data_lookup:
                        eq_sched_output_names.append(label_str)
                        eq_sched_output_me_data.append(list(_es_data_lookup[norm_label]))
                        total = sum(_es_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        eq_sched_output_names.append(label_str if label_str else "0")
                        eq_sched_output_me_data.append(list(blank_row_es))

                eq_sched_output_ye_data, _ = _monthly_to_yearly(eq_sched_output_me_data, _es_max, _start_month)
            else:
                pass
        else:
            pass

        # aaa, 7i. Build Additional Equity Requirement output aaa,
        # 4-row schedule: Opening Balance, Cash Bal After Infusion, Addl Equity Req, Closing Balance
        # Named ranges: o.jv.additional.equity.names / .me / .ye
        # Diagnostic: list all out_df named ranges containing "additional" or "equity.drawn"
        if not out_df.empty and "name" in out_df.columns:
            _addl_keys = [n for n in out_df["name"].tolist()
                          if "additional" in str(n).lower() or "equity.drawn" in str(n).lower()]
        raw_addl_eq_req_names = _read_array(out_df, OUT_ADDL_EQUITY_REQ_NAMES)
        addl_eq_req_output_names: Optional[List[str]] = None
        addl_eq_req_output_me_data: Optional[List[list]] = None
        addl_eq_req_output_ye_data: Optional[List[list]] = None

        if raw_addl_eq_req_names:
            for ti, nm in enumerate(raw_addl_eq_req_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_aer = lambda s: " ".join(s.lower().split())
                _aer_max = max_periods
                _zeros_aer = _zeros(_aer_max)

                _aer_data_lookup: Dict[str, List[float]] = {
                    _norm_aer("Opening Balance_Additional equity requirement"):
                        list(cff_rows.get("_addl_eq_opening", _zeros_aer)),
                    _norm_aer("Cash Balance After Capital Infusion"):
                        list(cff_rows.get("_cash_bal_after_infusion", _zeros_aer)),
                    _norm_aer("Additional equity requirement"):
                        list(cff_rows.get("_addl_eq_req", _zeros_aer)),
                    _norm_aer("Closing Balance_Additional equity requirement"):
                        list(cff_rows.get("_addl_eq_closing", _zeros_aer)),
                }
                # Balance label tracking for annual roll-forward fix
                _aer_balance_labels: List[str] = []

                blank_row_aer = [""] * _aer_max
                addl_eq_req_output_names = []
                addl_eq_req_output_me_data = []

                for ti, raw_name in enumerate(raw_addl_eq_req_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_aer(label_str) if label_str else ""

                    if norm_label and norm_label in _aer_data_lookup:
                        addl_eq_req_output_names.append(label_str)
                        addl_eq_req_output_me_data.append(list(_aer_data_lookup[norm_label]))
                        total = sum(_aer_data_lookup[norm_label])
                        # Track balance rows for annual fix
                        if "opening balance" in norm_label or "closing balance" in norm_label:
                            _aer_balance_labels.append(label_str)
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        addl_eq_req_output_names.append(label_str if label_str else "0")
                        addl_eq_req_output_me_data.append(list(blank_row_aer))

                # Derive yearly from monthly
                addl_eq_req_output_ye_data, _ = _monthly_to_yearly(
                    addl_eq_req_output_me_data, _aer_max, _start_month)
                _yr_bounds_aer = _compute_year_boundaries(_aer_max, _start_month)
                n_years_aer = len(_yr_bounds_aer)

                # Fix balance / running-balance rows for annual output.
                # Opening Balance  aa a first monthly opening of that year
                # Cash Balance After Capital Infusion aa a last monthly value of that year (year-end)
                # Additional equity requirement aa a SUM of monthly values (already correct from _monthly_to_yearly)
                # Closing Balance aa a last monthly closing of that year
                for _ri, _rl in enumerate(addl_eq_req_output_names):
                    _rl_norm = _norm_aer(_rl) if _rl else ""
                    if "opening balance" in _rl_norm:
                        _aer_cls_me = list(cff_rows.get("_addl_eq_closing", _zeros_aer))
                        yr_row: List[float] = []
                        for _yi, (_ys, _ye) in enumerate(_yr_bounds_aer):
                            if _yi == 0:
                                yr_row.append(_to_float(addl_eq_req_output_me_data[_ri][0]) if _aer_max > 0 else 0.0)
                            else:
                                prev_last_m = min(_yr_bounds_aer[_yi - 1][1] - 1, _aer_max - 1)
                                yr_row.append(_to_float(_aer_cls_me[prev_last_m]))
                        addl_eq_req_output_ye_data[_ri] = yr_row
                        _aer_balance_labels.append(_rl)
                    elif "closing balance" in _rl_norm:
                        _aer_cls_me2 = list(cff_rows.get("_addl_eq_closing", _zeros_aer))
                        yr_row2: List[float] = []
                        for _ys, _ye in _yr_bounds_aer:
                            last_m = min(_ye - 1, _aer_max - 1)
                            yr_row2.append(_to_float(_aer_cls_me2[last_m]))
                        addl_eq_req_output_ye_data[_ri] = yr_row2
                        _aer_balance_labels.append(_rl)
                    elif "cash balance after capital infusion" in _rl_norm:
                        # Cash Bal is a FLOW (sum of period flows, no opening).
                        # Yearly = SUM of 12 monthly flows  already correct
                        # from _monthly_to_yearly, so no override needed.
                        pass

            else:
                pass
        else:
            pass

        # aaa, 7j. Build Additional Equity Funding output aaa,
        # 3-row section: Addition Equity Drawn - Total / GP / LP
        # Named ranges: o.jv.additional.equity.drawn.names / .me / .ye
        raw_addl_eq_commit_names = _read_array(out_df, OUT_ADDL_EQUITY_COMMIT_NAMES)
        _addl_me_range_exists = bool(_read_array(out_df, OUT_ADDL_EQUITY_COMMIT_ME))
        _addl_ye_range_exists = bool(_read_array(out_df, OUT_ADDL_EQUITY_COMMIT_YE))
        addl_eq_commit_output_names: Optional[List[str]] = None
        addl_eq_commit_output_me_data: Optional[List[list]] = None
        addl_eq_commit_output_ye_data: Optional[List[list]] = None


        if raw_addl_eq_commit_names:
            for ti, nm in enumerate(raw_addl_eq_commit_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_aec = lambda s: " ".join(s.lower().split())
                _aec_max = max_periods
                _zeros_aec = _zeros(_aec_max)

                _aec_data_lookup: Dict[str, List[float]] = {
                    _norm_aec("Addition Equity Drawn - Total"):
                        list(cff_rows.get("_addl_equity_funding", _zeros_aec)),
                    _norm_aec("Additional Equity Drawn - GP"):
                        list(cff_rows.get("_gp_addl_commit", _zeros_aec)),
                    _norm_aec("Additional Equity Drawn - LP"):
                        list(cff_rows.get("_lp_addl_commit", _zeros_aec)),
                }

                blank_row_aec = [""] * _aec_max
                addl_eq_commit_output_names = []
                addl_eq_commit_output_me_data = []

                for ti, raw_name in enumerate(raw_addl_eq_commit_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_aec(label_str) if label_str else ""

                    if norm_label and norm_label in _aec_data_lookup:
                        addl_eq_commit_output_names.append(label_str)
                        addl_eq_commit_output_me_data.append(list(_aec_data_lookup[norm_label]))
                        total = sum(_aec_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        addl_eq_commit_output_names.append(label_str if label_str else "0")
                        addl_eq_commit_output_me_data.append(list(blank_row_aec))

                addl_eq_commit_output_ye_data, _ = _monthly_to_yearly(
                    addl_eq_commit_output_me_data, _aec_max, _start_month)

                # aaa, Validation diagnostics aaa,
                _aed_total = sum(cff_rows.get("_addl_equity_funding", _zeros_aec))
                _aed_gp_total = sum(cff_rows.get("_gp_addl_commit", _zeros_aec))
                _aed_lp_total = sum(cff_rows.get("_lp_addl_commit", _zeros_aec))
                _aed_first_nz = next((i for i, v in enumerate(
                    cff_rows.get("_addl_equity_funding", _zeros_aec)) if abs(v) > 0.01), None)
                if addl_eq_commit_output_ye_data:
                    for ri, (fn, yr_row) in enumerate(zip(
                            addl_eq_commit_output_names, addl_eq_commit_output_ye_data)):
                        yr_total = sum(_to_float(v) for v in yr_row)
                # Row match confirmation
                for fn in addl_eq_commit_output_names:
                    if fn and fn != "0":
                        nm = _norm_aec(fn)
                        matched = nm in _aec_data_lookup

                if not _addl_me_range_exists:
                    pass

            else:
                pass
        elif not raw_addl_eq_commit_names:
            pass

        # aaa, 7k. Build Land In-Kind Commitment output (o.jv.landinkind.comittment.*) aaa,
        raw_lik_commit_names = _read_array(out_df, OUT_LIK_COMMIT_NAMES)
        lik_commit_output_names: Optional[List[str]] = None
        lik_commit_output_me_data: Optional[List[list]] = None
        lik_commit_output_ye_data: Optional[List[list]] = None

        if raw_lik_commit_names:
            for ti, nm in enumerate(raw_lik_commit_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_lkc = lambda s: " ".join(s.lower().split())
                _lkc_max = max_periods
                _zeros_lkc = _zeros(_lkc_max)

                _lkc_data_lookup: Dict[str, List[float]] = {
                    _norm_lkc("Land In-kind Commitment- Total"):
                        list(cff_rows.get("_lik_commitment", _zeros_lkc)),
                    _norm_lkc("Land In-kind Commitment- GP"):
                        list(cff_rows.get("_gp_lik_commit", _zeros_lkc)),
                    _norm_lkc("Land In-kind Commitment- LP"):
                        list(cff_rows.get("_lp_lik_commit", _zeros_lkc)),
                    # Legacy aliases for backward compatibility
                    _norm_lkc("Land InKind Comittment- Total"):
                        list(cff_rows.get("_lik_commitment", _zeros_lkc)),
                    _norm_lkc("Land InKind Comittment- GP"):
                        list(cff_rows.get("_gp_lik_commit", _zeros_lkc)),
                    _norm_lkc("Land InKind Comittment- LP"):
                        list(cff_rows.get("_lp_lik_commit", _zeros_lkc)),
                }

                blank_row_lkc = [""] * _lkc_max
                lik_commit_output_names = []
                lik_commit_output_me_data = []

                for ti, raw_name in enumerate(raw_lik_commit_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_lkc(label_str) if label_str else ""

                    if norm_label and norm_label in _lkc_data_lookup:
                        lik_commit_output_names.append(label_str)
                        lik_commit_output_me_data.append(list(_lkc_data_lookup[norm_label]))
                        total = sum(_lkc_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        lik_commit_output_names.append(label_str if label_str else "0")
                        lik_commit_output_me_data.append(list(blank_row_lkc))

                lik_commit_output_ye_data, _ = _monthly_to_yearly(
                    lik_commit_output_me_data, _lkc_max, _start_month)

                # aaa, Cross-validation: Land In Kind - JV vs Land In-kind Commitment aaa,
                _lik_from_cff = list(cff_rows.get("_lik_commitment", _zeros_lkc))
                _lik_jv_total = sum(abs(_to_float(v)) for v in land_in_kind_jv) if land_in_kind_jv is not None else 0
                _lik_commit_total = sum(_to_float(v) for v in _lik_from_cff)
                _lik_jv_first = next((i for i, v in enumerate(land_in_kind_jv) if _to_float(v) != 0), None) if land_in_kind_jv is not None else None
                _lik_commit_first = next((i for i, v in enumerate(_lik_from_cff) if _to_float(v) != 0), None)
                _lik_match = abs(_lik_jv_total - _lik_commit_total) < 0.01 and _lik_jv_first == _lik_commit_first
            else:
                pass
        else:
            pass

        # aaa, 7l. Build Total Commitment output (o.jv.total.commitment.*) aaa,
        raw_total_commit_names = _read_array(out_df, OUT_TOTAL_COMMIT_NAMES)
        total_commit_output_names: Optional[List[str]] = None
        total_commit_output_me_data: Optional[List[list]] = None
        total_commit_output_ye_data: Optional[List[list]] = None

        if raw_total_commit_names:
            for ti, nm in enumerate(raw_total_commit_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            if cff_rows and max_periods > 0:
                _norm_tc = lambda s: " ".join(s.lower().split())
                _tc_max = max_periods
                _zeros_tc = _zeros(_tc_max)

                _tc_data_lookup: Dict[str, List[float]] = {
                    _norm_tc("Total Equity funding"):
                        list(cff_rows.get("_total_equity_funding", _zeros_tc)),
                    _norm_tc("Total GP Commitment"):
                        list(cff_rows.get("_total_gp_commit", _zeros_tc)),
                    _norm_tc("Total LP Commitment"):
                        list(cff_rows.get("_total_lp_commit", _zeros_tc)),
                }

                blank_row_tc = [""] * _tc_max
                total_commit_output_names = []
                total_commit_output_me_data = []

                for ti, raw_name in enumerate(raw_total_commit_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_tc(label_str) if label_str else ""

                    if norm_label and norm_label in _tc_data_lookup:
                        total_commit_output_names.append(label_str)
                        total_commit_output_me_data.append(list(_tc_data_lookup[norm_label]))
                        total = sum(_tc_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        total_commit_output_names.append(label_str if label_str else "0")
                        total_commit_output_me_data.append(list(blank_row_tc))

                total_commit_output_ye_data, _ = _monthly_to_yearly(
                    total_commit_output_me_data, _tc_max, _start_month)
            else:
                pass
        else:
            pass

        # =================================================================
        # 7m. Cash Distribution Schedule Output
        # =================================================================
        # Cash Distribution is a downstream schedule built from the
        # selected vehicle's already-computed rows:
        #   Cash Available = Total FCFF before Financing and SPV Related Cost - JV
        #                  + Cashflow From Financing Activity
        #                  + Equity Funding
        #                  + Addition Equity Drawn - Total
        # It does NOT include Land In-kind (non-cash) or Total Commitment.
        # GP/LP distributions are zero placeholders for now.
        cash_dist_output_names: Optional[List[str]] = None
        cash_dist_output_me_data: Optional[List[list]] = None
        cash_dist_output_ye_data: Optional[List[list]] = None
        cash_avail: Optional[List[float]] = None  # set by cash dist; used by pref returns
        opening_cd: Optional[List[float]] = None  # set by cash dist; used by pref returns

        raw_cash_dist_names = _read_array(out_df, OUT_CASH_DIST_NAMES)
        if raw_cash_dist_names:
            _cd_max = max((len(r) for r in output_fcff.values()), default=0)

            if _cd_max > 0 and cff_rows and total_fcff_jv is not None:
                # aaa, Source arrays (padded to _cd_max) aaa,
                _cd_fcff     = _pad([_to_float(v) for v in total_fcff_jv], _cd_max)
                _cd_cff_act  = _pad(list(cff_rows.get("_cashflow_from_financing_activity", [])), _cd_max)
                _cd_eq_fund  = _pad(list(cff_rows.get("_equity_funding", [])), _cd_max)
                _cd_addl_eq  = _pad(list(cff_rows.get("_addl_equity_funding", [])), _cd_max)
                _cd_fees     = _pad(list(total_fees_cf), _cd_max) if total_fees_cf is not None else [0.0] * _cd_max

                # aaa, Cash Available for Distribution (monthly flow) aaa,
                # = FCFF + CFF Activity + Equity Funding + Addl Equity + Total Fees
                cash_avail = _row_add(_cd_fcff, _cd_cff_act, _cd_eq_fund, _cd_addl_eq, _cd_fees)

                # aaa, GP / LP distributions (zero placeholders) aaa,
                gp_dist = [0.0] * _cd_max
                lp_dist = [0.0] * _cd_max

                # aaa, Opening / Closing balance roll-forward (monthly) aaa,
                opening_cd = [0.0] * _cd_max
                closing_cd = [0.0] * _cd_max
                for _t in range(_cd_max):
                    opening_cd[_t] = closing_cd[_t - 1] if _t > 0 else 0.0
                    closing_cd[_t] = opening_cd[_t] + cash_avail[_t] + gp_dist[_t] + lp_dist[_t]

                # aaa, Sanity print: source totals for selected vehicle aaa,

                # aaa, Build lookup dict aaa,
                def _norm_cd(s):
                    return s.strip().lower().replace(" ", "").replace("_", "")

                _cd_data_lookup = {
                    "openingbalancecashdistribution": opening_cd,
                    "cashavailablefordistribution": cash_avail,
                    "totaldistributions-gp": gp_dist,
                    "totaldistributionsgp": gp_dist,
                    "totaldistributions-lp": lp_dist,
                    "totaldistributionslp": lp_dist,
                    "closingcashbalancecashdistributions": closing_cd,
                }

                blank_row_cd = [0.0] * _cd_max
                cash_dist_output_names = []
                cash_dist_output_me_data = []

                for ti, raw_name in enumerate(raw_cash_dist_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    norm_label = _norm_cd(label_str) if label_str else ""

                    if norm_label and norm_label in _cd_data_lookup:
                        cash_dist_output_names.append(label_str)
                        cash_dist_output_me_data.append(list(_cd_data_lookup[norm_label]))
                        total = sum(_cd_data_lookup[norm_label])
                    else:
                        display = label_str if label_str and label_str != "0" else "(blank)"
                        cash_dist_output_names.append(label_str if label_str else "0")
                        cash_dist_output_me_data.append(list(blank_row_cd))

                # aaa, Yearly aggregation (independent annual roll-forward) aaa,
                _yr_bounds_cd = _compute_year_boundaries(_cd_max, _start_month)
                _n_years_cd = len(_yr_bounds_cd)
                _cd_opening_norm = _norm_cd("Opening Balance_Cash Distribution")
                _cd_closing_norm = _norm_cd("Closing Cash Balance_Cash Distributions")

                cash_dist_output_ye_data = []
                # First pass: sum flow rows, placeholder balance rows
                for ri, (row, name) in enumerate(zip(cash_dist_output_me_data, cash_dist_output_names)):
                    if all(v == 0.0 or v == "" for v in row):
                        # blank/spacer row or all-zero flow
                        norm_name = _norm_cd(str(name)) if name else ""
                        if norm_name in (_cd_opening_norm, _cd_closing_norm):
                            cash_dist_output_ye_data.append([0.0] * _n_years_cd)
                        else:
                            yr_row = []
                            for ys, ye in _yr_bounds_cd:
                                end = min(ye, len(row))
                                yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                            cash_dist_output_ye_data.append(yr_row)
                        continue
                    norm_name = _norm_cd(str(name)) if name else ""
                    if norm_name in (_cd_opening_norm, _cd_closing_norm):
                        # placeholder  will be recomputed in second pass
                        cash_dist_output_ye_data.append([0.0] * _n_years_cd)
                    else:
                        # Flow row: sum across calendar year
                        yr_row = []
                        for ys, ye in _yr_bounds_cd:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        cash_dist_output_ye_data.append(yr_row)

                # Second pass: independent annual opening/closing roll-forward
                _cd_opening_idx = None
                _cd_closing_idx = None
                _cd_flow_indices = []
                for ri, name in enumerate(cash_dist_output_names):
                    norm_name = _norm_cd(str(name)) if name else ""
                    if norm_name == _cd_opening_norm:
                        _cd_opening_idx = ri
                    elif norm_name == _cd_closing_norm:
                        _cd_closing_idx = ri
                    elif norm_name in _cd_data_lookup:
                        _cd_flow_indices.append(ri)

                if _cd_opening_idx is not None and _cd_closing_idx is not None:
                    for yi in range(_n_years_cd):
                        if yi == 0:
                            cash_dist_output_ye_data[_cd_opening_idx][yi] = 0.0
                        else:
                            cash_dist_output_ye_data[_cd_opening_idx][yi] = \
                                cash_dist_output_ye_data[_cd_closing_idx][yi - 1]
                        annual_opening = cash_dist_output_ye_data[_cd_opening_idx][yi]
                        annual_flows = sum(
                            cash_dist_output_ye_data[fi][yi] for fi in _cd_flow_indices
                        )
                        cash_dist_output_ye_data[_cd_closing_idx][yi] = annual_opening + annual_flows

            else:
                pass
        else:
            pass

        # =================================================================
        # 7n. Preferred Returns Schedule Output
        # =================================================================
        pref_returns_output_names: Optional[List[str]] = None
        pref_returns_output_me_data: Optional[List[list]] = None
        pref_returns_output_ye_data: Optional[List[list]] = None
        gp_catchup_output_names: Optional[List[str]] = None
        gp_catchup_output_me_data: Optional[List[list]] = None
        gp_catchup_output_ye_data: Optional[List[list]] = None
        tier1_lp_output_names: Optional[List[str]] = None
        tier1_lp_output_me_data: Optional[List[list]] = None
        tier1_lp_output_ye_data: Optional[List[list]] = None
        tier1_gp_cu_output_names: Optional[List[str]] = None
        tier1_gp_cu_output_me_data: Optional[List[list]] = None
        tier1_gp_cu_output_ye_data: Optional[List[list]] = None

        raw_pref_returns_names = _read_array(out_df, OUT_PREF_RETURNS_NAMES)
        if raw_pref_returns_names:
            for ti, nm in enumerate(raw_pref_returns_names):
                display = repr(nm) if nm is not None and str(nm).strip() and str(nm).strip() != "0" else "(blank/0)"

            _pr_max = max((len(r) for r in output_fcff.values()), default=0)

            if _pr_max > 0 and cff_rows and chosen_vehicle_inputs is not None:
                vi = chosen_vehicle_inputs

                # ================================================================
                # PREFERRED WATERFALL INPUT RESOLUTION
                # ================================================================

                # -- PreferredReturnsandCatchup fields --
                _wf_pref_fields = [
                    ("pref_dist_frequency",        "distribution_frequency"),
                    ("pref_return_type",            "preferred_return_type"),
                    ("pref_return_rate",            "preferred_return"),
                    ("gp_cf_during_pref",           "gp_cashflow_duringpreferred_return"),
                    ("gp_promote_raw",              "gp_promote_"),
                    ("catchup_enabled",             "catchup_enabled"),
                    ("gp_cashflows_during_catchup", "gp_cashflows_during_catch_up"),
                    ("lp_cashflows_during_catchup", "lp_cashflows_during_catch_up"),
                ]
                # -- Tier fields --
                _wf_tier_fields = [
                    ("tier1_irr",       "irr__tier_1"),
                    ("tier1_lp_share",  "lp_share___tier_1"),
                    ("tier1_gp_promote","gp_promote___tier_1"),
                    ("tier2_irr",       "irr__tier_2"),
                    ("tier2_lp_share",  "lp_share___tier_2"),
                    ("tier2_gp_promote","gp_promote___tier_2"),
                    ("tier3_lp_share",  "lp_share___tier_3"),
                    ("tier3_gp_share",  "gp_promote___tier_3"),
                ]
                for _wf_key, _wf_src in _wf_pref_fields + _wf_tier_fields:
                    _raw_v = vi.get(_wf_key, "<<MISSING>>")
                    _norm_v = _to_float(_raw_v) if isinstance(_raw_v, (int, float, str)) and _wf_key not in ("pref_dist_frequency", "pref_return_type", "catchup_enabled") else _raw_v

                # -- Resolve preferred return inputs --
                _pref_freq = str(vi.get("pref_dist_frequency") or "").strip()
                _pref_type = str(vi.get("pref_return_type") or "").strip().lower()
                _pref_annual_rate = _to_float(vi.get("pref_return_rate", 0))
                _gp_cf_during = _to_float(vi.get("gp_cf_during_pref", 0))
                _gp_promote_raw = _to_float(vi.get("gp_promote_raw", 0))

                _is_hard_pref = _pref_type in ("hard", "")
                _is_soft_pref = _pref_type == "soft"

                # Normalise promote if given as percentage
                if _gp_promote_raw > 1.0:
                    _gp_promote_raw /= 100.0

                # Monthly compounded rate from annual rate
                # monthly_pref_rate = (1 + preferred_return)^(1/12) - 1
                _monthly_pref_rate = (1 + _pref_annual_rate) ** (1.0 / 12.0) - 1 if _pref_annual_rate > 0 else 0.0

                # -- Resolve GP Catchup inputs --
                _ce_raw = vi.get("catchup_enabled", 0)
                if isinstance(_ce_raw, (int, float)):
                    _catchup_enabled = float(_ce_raw)
                elif isinstance(_ce_raw, str):
                    _catchup_enabled = 1.0 if _ce_raw.strip().lower() in (
                        "yes", "true", "1", "y", "on") else _to_float(_ce_raw)
                else:
                    _catchup_enabled = 0.0
                _catchup_pct = _to_float(vi.get("catchup_pct", 0))
                if _catchup_pct > 1.0:
                    _catchup_pct /= 100.0
                _gp_cf_during_catchup = _to_float(vi.get("gp_cashflows_during_catchup", 0))
                _lp_cf_during_catchup = _to_float(vi.get("lp_cashflows_during_catchup", 0))
                if _gp_cf_during_catchup > 1.0:
                    _gp_cf_during_catchup /= 100.0
                if _lp_cf_during_catchup > 1.0:
                    _lp_cf_during_catchup /= 100.0
                # Catchup shares: prefer gp_cashflows_during_catch_up, fall back to catch_up_
                if _catchup_enabled:
                    if _gp_cf_during_catchup > 0 or _lp_cf_during_catchup > 0:
                        _gp_cu_share = _gp_cf_during_catchup
                        _lp_cu_share = _lp_cf_during_catchup if _lp_cf_during_catchup > 0 else (1.0 - _gp_cf_during_catchup)
                    elif _catchup_pct > 0:
                        _gp_cu_share = _catchup_pct
                        _lp_cu_share = 1.0 - _catchup_pct
                    else:
                        _gp_cu_share = 0.0
                        _lp_cu_share = 0.0
                else:
                    _gp_cu_share = 0.0
                    _lp_cu_share = 0.0

                # -- Resolve Tier 1 inputs --
                _t1_irr = _to_float(vi.get("tier1_irr", 0))
                if _t1_irr > 1.0:
                    _t1_irr /= 100.0
                _t1_lp_share = _to_float(vi.get("tier1_lp_share", 0))
                if _t1_lp_share > 1.0:
                    _t1_lp_share /= 100.0
                _t1_gp_promote = _to_float(vi.get("tier1_gp_promote", 0))
                if _t1_gp_promote > 1.0:
                    _t1_gp_promote /= 100.0
                # Monthly compounded Tier 1 rate
                _monthly_t1_rate = (1 + _t1_irr) ** (1.0 / 12.0) - 1 if _t1_irr > 0 else 0.0

                # -- Resolve Tier 3 shares --
                _t3_lp_share = _to_float(vi.get("tier3_lp_share", 0))
                _t3_gp_share = _to_float(vi.get("tier3_gp_share", 0))
                if _t3_lp_share > 1.0:
                    _t3_lp_share /= 100.0
                if _t3_gp_share > 1.0:
                    _t3_gp_share /= 100.0

                _freq_lower = _pref_freq.lower().replace(" ", "").replace("-", "")
                if _freq_lower in ("quarterly",):
                    _months_per_period = 3
                elif _freq_lower in ("semiannual", "semiannually"):
                    _months_per_period = 6
                elif _freq_lower in ("annual", "annually"):
                    _months_per_period = 12
                else:
                    _months_per_period = 1  # default monthly

                # -- JV start index --
                _pr_jv_start_idx = None
                _pr_jv_start = vi.get("jv_start_date")
                if _pr_jv_start is not None and model_start is not None:
                    _pr_jv_start_idx = _date_to_month_index(_pr_jv_start, model_start)

                # -- Exit / fund close boundary --
                _pr_fund_end_idx = None
                _pr_fund_tenure = _to_float(vi.get("fund_tenure", 0))
                if _pr_jv_start_idx is not None and _pr_fund_tenure > 0:
                    _pr_fund_end_idx = _pr_jv_start_idx + int(_pr_fund_tenure)
                _pr_fund_close_raw = vi.get("fund_close_date")
                _pr_fund_close_idx = _date_to_month_index(_pr_fund_close_raw, model_start)
                if _pr_fund_close_idx is not None:
                    if _pr_fund_close_idx >= _pr_max:
                        _pr_fund_close_idx = _pr_max - 1
                    if _pr_fund_end_idx is None:
                        _pr_fund_end_idx = _pr_fund_close_idx
                    else:
                        _pr_fund_end_idx = min(_pr_fund_end_idx, _pr_fund_close_idx)
                if _pr_fund_end_idx is not None and _pr_fund_end_idx >= _pr_max:
                    _pr_fund_end_idx = _pr_max - 1
                _pr_exit_idx = _pr_fund_end_idx  # None means run to model end

                # -- Build masks --
                active_pref_mask = [False] * _pr_max
                _pref_start = _pr_jv_start_idx if _pr_jv_start_idx is not None else 0
                _pref_end = _pr_exit_idx if _pr_exit_idx is not None else (_pr_max - 1)
                for _t in range(_pref_start, min(_pref_end + 1, _pr_max)):
                    active_pref_mask[_t] = True

                # normal_distribution_mask: JV-start-anchored cadence
                normal_dist_mask = [False] * _pr_max
                for _t in range(_pr_max):
                    if not active_pref_mask[_t]:
                        continue
                    if _months_per_period <= 1:
                        normal_dist_mask[_t] = True
                    elif _pr_jv_start_idx is not None and _t >= _pr_jv_start_idx:
                        _months_since = _t - _pr_jv_start_idx + 1
                        if _months_since > 0 and (_months_since % _months_per_period) == 0:
                            normal_dist_mask[_t] = True

                # Force distribution in exit month
                exit_dist_mask = [False] * _pr_max
                if _pr_exit_idx is not None and 0 <= _pr_exit_idx < _pr_max:
                    exit_dist_mask[_pr_exit_idx] = True

                eff_dist_mask = [False] * _pr_max
                for _t in range(_pr_max):
                    eff_dist_mask[_t] = normal_dist_mask[_t] or exit_dist_mask[_t]

                # -- Frequency validation debug --
                _first_dist_months = [t for t in range(_pr_max) if eff_dist_mask[t]][:8]
                if _pr_exit_idx is not None and 0 <= _pr_exit_idx < _pr_max and exit_dist_mask[_pr_exit_idx]:
                    _exit_is_normal = normal_dist_mask[_pr_exit_idx]

                # ── WATERFALL INPUT RESOLUTION (TILL TIER 1) ──
                _wfir_fields = [
                    ("distribution_frequency",              "pref_dist_frequency",        _pref_freq),
                    ("preferred_return_type",               "pref_return_type",            _pref_type),
                    ("preferred_return",                    "pref_return_rate",            vi.get("pref_return_rate", "?")),
                    ("gp_cashflow_duringpreferred_return",  "gp_cf_during_pref",           vi.get("gp_cf_during_pref", "?")),
                    ("gp_promote_",                        "gp_promote_raw",              vi.get("gp_promote_raw", "?")),
                    ("catchup_enabled",                    "catchup_enabled (raw)",       vi.get("catchup_enabled", "?")),
                    ("gp_cashflows_during_catch_up",       "gp_cashflows_during_catchup", vi.get("gp_cashflows_during_catchup", "?")),
                    ("irr__tier_1",                        "tier1_irr",                   vi.get("tier1_irr", "?")),
                    ("lp_share___tier_1",                  "tier1_lp_share",              vi.get("tier1_lp_share", "?")),
                    ("gp_promote___tier_1",                "tier1_gp_promote",            vi.get("tier1_gp_promote", "?")),
                ]
                for _src_field, _int_key, _raw in _wfir_fields:
                    _nv = _to_float(_raw) if isinstance(_raw, (int, float, str)) and _src_field not in (
                        "distribution_frequency", "preferred_return_type", "catchup_enabled") else _raw

                # ── STAGE ENABLEMENT CHECK ──

                # -- Source arrays --
                _total_lp_commit = _pad(list(cff_rows.get("_total_lp_commit", [])), _pr_max)
                _total_gp_commit = _pad(list(cff_rows.get("_total_gp_commit", [])), _pr_max)

                # Cash Available for Distribution (flow from cash dist section)
                _pr_cash_avail = _pad(list(cash_avail), _pr_max) if cash_avail is not None else [0.0] * _pr_max
                # Opening Balance_Cash Distribution (from cash dist section)
                _pr_opening_cd = _pad(list(opening_cd), _pr_max) if opening_cd is not None else [0.0] * _pr_max

                # ================================================================
                # PREFERRED RETURNS MONTHLY LOOP (SINGLE RUNNING BALANCE)
                # ================================================================
                # Formula:
                #   Preferred Accrual[t] = monthly_pref_rate * (Beginning Balance[t] + LP Capital Contributions[t])
                #   Ending Balance[t] = Beginning Balance[t] + LP Capital Contributions[t] + Preferred Accrual[t] + LP Distributions[t]
                #
                # Hard pref: entire preferred_distribution_pool goes to LP, GP gets 0
                # Soft pref: pool split by gp_promote_ / (1 - gp_promote_) between GP/LP
                #
                # preferred_distribution_pool = min(available_cash_for_event, preferred_balance_due_before_distribution)
                # available_cash_for_event = Opening Balance_Cash Distribution[t] + Cash Available for Distribution[t]

                # -- STAGE 1 output arrays: Preferred Returns --
                begin_bal_pref     = [0.0] * _pr_max
                lp_cap_contrib     = [0.0] * _pr_max
                pref_accrual       = [0.0] * _pr_max
                lp_dist            = [0.0] * _pr_max   # LP distributions in preferred (negative)
                unpaid_pref        = [0.0] * _pr_max   # zero-safe placeholder (not used in logic)
                ending_bal_pref    = [0.0] * _pr_max
                total_lp_cf        = [0.0] * _pr_max
                gp_contrib         = [0.0] * _pr_max
                gp_dist_pref       = [0.0] * _pr_max   # GP distributions during preferred (negative)
                total_dist_pref    = [0.0] * _pr_max
                cash_remaining     = [0.0] * _pr_max   # Cash Flow Remaining - Post Preferred Returns Distributions

                # -- STAGES 2-7: DISABLED (zeroed) --
                cu_lp_dist         = [0.0] * _pr_max
                cu_gp_dist         = [0.0] * _pr_max
                cu_total_dist      = [0.0] * _pr_max
                cu_cash_remaining  = [0.0] * _pr_max
                cu_post_cash       = [0.0] * _pr_max
                t1_begin_bal       = [0.0] * _pr_max
                t1_lp_contrib      = [0.0] * _pr_max
                t1_accrual         = [0.0] * _pr_max
                t1_lp_dist_prior   = [0.0] * _pr_max
                t1_addl_lp_dist    = [0.0] * _pr_max
                t1_unpaid          = [0.0] * _pr_max
                t1_ending_bal      = [0.0] * _pr_max
                t1_total_lp_cf     = [0.0] * _pr_max
                t1_cash_remaining  = [0.0] * _pr_max
                t1gp_gp_dist       = [0.0] * _pr_max
                t1gp_lp_dist       = [0.0] * _pr_max
                t1gp_total_dist    = [0.0] * _pr_max
                t1gp_cash_remaining = [0.0] * _pr_max
                t2_begin_bal       = [0.0] * _pr_max
                t2_lp_contrib      = [0.0] * _pr_max
                t2_accrual         = [0.0] * _pr_max
                t2_lp_dist         = [0.0] * _pr_max
                t2_ending_bal      = [0.0] * _pr_max
                t2_cash_remaining  = [0.0] * _pr_max
                t2gp_gp_dist       = [0.0] * _pr_max
                t2gp_total_dist    = [0.0] * _pr_max
                t2gp_cash_remaining = [0.0] * _pr_max
                t3_lp_dist         = [0.0] * _pr_max
                t3_gp_dist         = [0.0] * _pr_max
                t3_cash_remaining  = [0.0] * _pr_max

                # -- Dynamic cash distribution balance --
                _dyn_cd_opening = [0.0] * _pr_max
                _dyn_cd_closing = [0.0] * _pr_max

                # -- Internal tracking --
                _t1_deficiency = [0.0] * _pr_max
                _pref_settled = False
                _TOLERANCE = 0.005

                for _t in range(_pr_max):
                    # -- Dynamic cash distribution opening --
                    _dyn_cd_opening[_t] = _dyn_cd_closing[_t - 1] if _t > 0 else 0.0

                    # ======================================================
                    # STAGE 1: PREFERRED RETURNS (SINGLE RUNNING BALANCE)
                    # ======================================================
                    if active_pref_mask[_t] and not _pref_settled:
                        begin_bal_pref[_t] = ending_bal_pref[_t - 1] if _t > 0 else 0.0
                        lp_cap_contrib[_t] = _total_lp_commit[_t]
                        gp_contrib[_t] = _total_gp_commit[_t]

                        # Monthly compounded accrual
                        _accrual_base = begin_bal_pref[_t] + lp_cap_contrib[_t]
                        if _pref_annual_rate > 0 and _accrual_base > _TOLERANCE:
                            pref_accrual[_t] = _monthly_pref_rate * _accrual_base
                        else:
                            pref_accrual[_t] = 0.0

                        # Preferred balance due before distribution
                        _pref_bal_due = begin_bal_pref[_t] + lp_cap_contrib[_t] + pref_accrual[_t]

                        # Distribution event logic
                        if eff_dist_mask[_t] and _pref_bal_due > _TOLERANCE:
                            # available_cash_for_event = Opening Balance_CD[t] + Cash Available for Distribution[t]
                            _avail_cash_event = max(_dyn_cd_opening[_t] + _pr_cash_avail[_t], 0.0)

                            # preferred_distribution_pool = min(available_cash, balance_due)
                            _pref_dist_pool = min(_avail_cash_event, _pref_bal_due)

                            if _is_hard_pref:
                                # HARD: entire pool goes to LP, GP gets zero
                                lp_dist[_t] = -_pref_dist_pool
                                gp_dist_pref[_t] = 0.0
                            elif _is_soft_pref:
                                # SOFT: pool split by gp_promote_ / (1 - gp_promote_)
                                _gp_share = _gp_promote_raw
                                _lp_share = 1.0 - _gp_share
                                gp_dist_pref[_t] = -(_pref_dist_pool * _gp_share)
                                lp_dist[_t] = -(_pref_dist_pool * _lp_share)
                            else:
                                # Default to hard behavior
                                lp_dist[_t] = -_pref_dist_pool
                                gp_dist_pref[_t] = 0.0
                        else:
                            lp_dist[_t] = 0.0
                            gp_dist_pref[_t] = 0.0

                        # Ending Balance = Beginning + LP Capital + Accrual + LP Distributions
                        # (GP distribution does NOT reduce LP preferred-stage balance)
                        ending_bal_pref[_t] = begin_bal_pref[_t] + lp_cap_contrib[_t] + pref_accrual[_t] + lp_dist[_t]

                        # Total LP Cashflows (LP perspective)
                        total_lp_cf[_t] = lp_dist[_t]

                        # Total Distributions - Preferred = LP Dist + GP Dist
                        total_dist_pref[_t] = lp_dist[_t] + gp_dist_pref[_t]

                        # Cash Remaining Post Preferred = available_cash + LP Dist + GP Dist
                        if eff_dist_mask[_t]:
                            _avail_cash_event = max(_dyn_cd_opening[_t] + _pr_cash_avail[_t], 0.0)
                            cash_remaining[_t] = _avail_cash_event + lp_dist[_t] + gp_dist_pref[_t]
                            # Safety: ensure non-negative
                            if cash_remaining[_t] < 0:
                                cash_remaining[_t] = 0.0
                        else:
                            cash_remaining[_t] = 0.0

                        # Check stop condition
                        if ending_bal_pref[_t] <= _TOLERANCE:
                            _pref_settled = True

                    else:
                        # Inactive or settled: zero outputs
                        begin_bal_pref[_t] = 0.0
                        lp_cap_contrib[_t] = 0.0
                        pref_accrual[_t] = 0.0
                        lp_dist[_t] = 0.0
                        gp_dist_pref[_t] = 0.0
                        ending_bal_pref[_t] = 0.0
                        total_lp_cf[_t] = 0.0
                        gp_contrib[_t] = 0.0
                        total_dist_pref[_t] = 0.0
                        cash_remaining[_t] = 0.0

                    # ======================================================
                    # STAGE 2: GP CATCHUP
                    # Split cash_remaining by GP/LP catchup shares.
                    # cu_cash_in = cash_remaining from preferred stage
                    # ======================================================
                    if eff_dist_mask[_t] and _catchup_enabled and (_gp_cu_share > 0 or _lp_cu_share > 0):
                        _cu_cash_in = max(cash_remaining[_t], 0.0)
                        if _cu_cash_in > _TOLERANCE:
                            cu_gp_dist[_t] = -(_cu_cash_in * _gp_cu_share)
                            cu_lp_dist[_t] = -(_cu_cash_in * _lp_cu_share)
                            cu_total_dist[_t] = cu_gp_dist[_t] + cu_lp_dist[_t]
                            cu_cash_remaining[_t] = _cu_cash_in + cu_total_dist[_t]
                            if cu_cash_remaining[_t] < 0:
                                cu_cash_remaining[_t] = 0.0
                            cu_post_cash[_t] = cu_cash_remaining[_t]
                        else:
                            cu_gp_dist[_t] = 0.0
                            cu_lp_dist[_t] = 0.0
                            cu_total_dist[_t] = 0.0
                            cu_cash_remaining[_t] = 0.0
                            cu_post_cash[_t] = 0.0
                    else:
                        cu_gp_dist[_t] = 0.0
                        cu_lp_dist[_t] = 0.0
                        cu_total_dist[_t] = 0.0
                        cu_cash_remaining[_t] = max(cash_remaining[_t], 0.0)
                        cu_post_cash[_t] = cu_cash_remaining[_t]

                    # ======================================================
                    # STAGE 3: TIER 1 LP DISTRIBUTIONS
                    # Deficiency structure similar to preferred returns.
                    # t1_lp_dist_prior = lp_dist + cu_lp_dist  (cumulative LP
                    #   distributions from all prior stages)
                    # requirement = begin + contrib + accrual + dist_prior
                    # addl_lp_dist = -min(tier1_cash_in, max(0, requirement))
                    # ======================================================
                    if active_pref_mask[_t]:
                        t1_begin_bal[_t] = t1_ending_bal[_t - 1] if _t > 0 else 0.0
                        t1_lp_contrib[_t] = _total_lp_commit[_t]

                        _t1_accrual_base = t1_begin_bal[_t] + t1_lp_contrib[_t]
                        if _monthly_t1_rate > 0 and _t1_accrual_base > _TOLERANCE:
                            t1_accrual[_t] = _monthly_t1_rate * _t1_accrual_base
                        else:
                            t1_accrual[_t] = 0.0

                        # LP distributions prior to tier 1 = preferred LP + catchup LP
                        t1_lp_dist_prior[_t] = lp_dist[_t] + cu_lp_dist[_t]

                        # Tier 1 requirement (deficiency before additional dist)
                        _t1_requirement = (t1_begin_bal[_t] + t1_lp_contrib[_t]
                                           + t1_accrual[_t] + t1_lp_dist_prior[_t])

                        # Additional LP dist to meet Tier 1 IRR
                        if eff_dist_mask[_t] and _t1_requirement > _TOLERANCE:
                            _tier1_cash_in = max(cu_cash_remaining[_t], 0.0)
                            t1_addl_lp_dist[_t] = -min(_tier1_cash_in, max(0.0, _t1_requirement))
                        else:
                            t1_addl_lp_dist[_t] = 0.0

                        # Ending balance = begin + contrib + accrual + dist_prior + addl_lp_dist
                        t1_ending_bal[_t] = (t1_begin_bal[_t] + t1_lp_contrib[_t]
                                             + t1_accrual[_t] + t1_lp_dist_prior[_t]
                                             + t1_addl_lp_dist[_t])

                        # Unpaid = max(ending_bal, 0) i.e. remaining deficiency
                        t1_unpaid[_t] = max(t1_ending_bal[_t], 0.0)

                        # Total LP Cashflows post Tier 1 = dist_prior + addl
                        t1_total_lp_cf[_t] = t1_lp_dist_prior[_t] + t1_addl_lp_dist[_t]

                        # Cash remaining post Tier 1 LP
                        if eff_dist_mask[_t]:
                            _tier1_cash_in = max(cu_cash_remaining[_t], 0.0)
                            t1_cash_remaining[_t] = _tier1_cash_in + t1_addl_lp_dist[_t]
                            if t1_cash_remaining[_t] < 0:
                                t1_cash_remaining[_t] = 0.0
                        else:
                            t1_cash_remaining[_t] = 0.0

                        # Track deficiency for output assembly
                        _t1_deficiency[_t] = t1_ending_bal[_t]
                    else:
                        t1_begin_bal[_t] = 0.0
                        t1_lp_contrib[_t] = 0.0
                        t1_accrual[_t] = 0.0
                        t1_lp_dist_prior[_t] = 0.0
                        t1_addl_lp_dist[_t] = 0.0
                        t1_unpaid[_t] = 0.0
                        t1_ending_bal[_t] = 0.0
                        t1_total_lp_cf[_t] = 0.0
                        t1_cash_remaining[_t] = 0.0
                        _t1_deficiency[_t] = 0.0

                    # ======================================================
                    # STAGE 4: TIER 1 GP CATCHUP
                    # Only distributes when Tier 1 LP deficiency = 0
                    # (i.e. ending_bal_t1 <= TOLERANCE).
                    # Splits t1_cash_remaining by gp_promote / (1 - gp_promote).
                    # ======================================================
                    if eff_dist_mask[_t] and t1_ending_bal[_t] <= _TOLERANCE:
                        _t1gp_cash_in = max(t1_cash_remaining[_t], 0.0)
                        if _t1gp_cash_in > _TOLERANCE and _t1_gp_promote > 0:
                            t1gp_gp_dist[_t] = -(_t1gp_cash_in * _t1_gp_promote)
                            t1gp_lp_dist[_t] = -(_t1gp_cash_in * (1.0 - _t1_gp_promote))
                            t1gp_total_dist[_t] = t1gp_gp_dist[_t] + t1gp_lp_dist[_t]
                            t1gp_cash_remaining[_t] = _t1gp_cash_in + t1gp_total_dist[_t]
                            if t1gp_cash_remaining[_t] < 0:
                                t1gp_cash_remaining[_t] = 0.0
                        else:
                            t1gp_gp_dist[_t] = 0.0
                            t1gp_lp_dist[_t] = 0.0
                            t1gp_total_dist[_t] = 0.0
                            t1gp_cash_remaining[_t] = max(t1_cash_remaining[_t], 0.0)
                    else:
                        t1gp_gp_dist[_t] = 0.0
                        t1gp_lp_dist[_t] = 0.0
                        t1gp_total_dist[_t] = 0.0
                        t1gp_cash_remaining[_t] = max(t1_cash_remaining[_t], 0.0)

                    # ======================================================
                    # STAGES 5-7: TIER 2 / TIER 3 (DISABLED)
                    # All arrays stay zeroed from initialisation.
                    # ======================================================

                    # ======================================================
                    # CLOSING: Dynamic cash distribution balance
                    # Closing = Opening + CashAvail + all active distributions
                    # ======================================================
                    _dyn_cd_closing[_t] = (_dyn_cd_opening[_t] + _pr_cash_avail[_t]
                                          + lp_dist[_t] + gp_dist_pref[_t]
                                          + cu_lp_dist[_t] + cu_gp_dist[_t]
                                          + t1_addl_lp_dist[_t]
                                          + t1gp_gp_dist[_t] + t1gp_lp_dist[_t])
                    if _dyn_cd_closing[_t] < 0:
                        _dyn_cd_closing[_t] = 0.0

                # ================================================================
                # PREFERRED RETURNS VALIDATION
                # ================================================================

                # 1. Preferred monthly validation (first 24 relevant months)
                _pr_relevant = [t for t in range(_pr_max) if active_pref_mask[t]][:24]
                for _t in _pr_relevant:
                    _avail = max(_dyn_cd_opening[_t] + _pr_cash_avail[_t], 0.0) if eff_dist_mask[_t] else 0.0
                    _bal_due = begin_bal_pref[_t] + lp_cap_contrib[_t] + pref_accrual[_t]
                    _pool = min(_avail, _bal_due) if eff_dist_mask[_t] else 0.0

                # 2. Hard vs Soft validation
                _total_gp_during_pref = sum(gp_dist_pref)
                if _is_hard_pref:
                    pass
                else:
                    pass
                if _is_hard_pref:
                    pass
                else:
                    pass

                # 3. Reconciliation validation
                _recon_lp_contrib = sum(lp_cap_contrib)
                _recon_pref_accrual = sum(pref_accrual)
                _recon_lp_dist = sum(lp_dist)
                _recon_gp_dist = sum(gp_dist_pref)
                _recon_final_ending = ending_bal_pref[_pr_max - 1] if _pr_max > 0 else 0.0
                _recon_final_cash_rem = cash_remaining[_pr_max - 1] if _pr_max > 0 else 0.0

                # 4. Over-distribution validation
                _od_violations = 0
                _neg_residuals = 0
                for _t in range(_pr_max):
                    if not eff_dist_mask[_t]:
                        continue
                    _avail = max(_dyn_cd_opening[_t] + _pr_cash_avail[_t], 0.0)
                    _pref_bal = begin_bal_pref[_t] + lp_cap_contrib[_t] + pref_accrual[_t]
                    _total_dist_abs = abs(lp_dist[_t]) + abs(gp_dist_pref[_t])
                    if _total_dist_abs > _avail + 0.01:
                        _od_violations += 1
                        if _od_violations <= 3:
                            pass
                    if _total_dist_abs > _pref_bal + 0.01:
                        _od_violations += 1
                        if _od_violations <= 3:
                            pass
                    if cash_remaining[_t] < -0.01:
                        _neg_residuals += 1
                        if _neg_residuals <= 3:
                            pass

                # ================================================================
                # ── PREFERRED RESIDUAL VALIDATION ──
                # ================================================================
                _pr_relevant24 = [t for t in range(_pr_max) if active_pref_mask[t]][:24]
                for _t in _pr_relevant24:
                    _pci = max(_dyn_cd_opening[_t] + _pr_cash_avail[_t], 0.0) if eff_dist_mask[_t] else 0.0

                # ================================================================
                # ── GP CATCHUP VALIDATION ──
                # ================================================================
                _cu_relevant24 = [t for t in range(_pr_max) if active_pref_mask[t]][:24]
                for _t in _cu_relevant24:
                    pass

                # ================================================================
                # ── TIER 1 LP VALIDATION ──
                # ================================================================
                _t1_relevant = [t for t in range(_pr_max) if active_pref_mask[t]][:24]
                for _t in _t1_relevant:
                    pass

                # ================================================================
                # ── TIER 1 GP CATCHUP VALIDATION ──
                # ================================================================
                _t1gp_relevant24 = [t for t in range(_pr_max) if active_pref_mask[t]][:24]
                for _t in _t1gp_relevant24:
                    pass

                # ================================================================
                # ── OVER-DISTRIBUTION VALIDATION ──
                # ================================================================
                _od_any = False
                _stage_checks = [
                    ("Preferred", lambda t: max(_dyn_cd_opening[t] + _pr_cash_avail[t], 0.0),
                     lambda t: abs(lp_dist[t]) + abs(gp_dist_pref[t]), lambda t: cash_remaining[t]),
                    ("GP Catchup", lambda t: max(cash_remaining[t], 0.0),
                     lambda t: abs(cu_lp_dist[t]) + abs(cu_gp_dist[t]), lambda t: cu_cash_remaining[t]),
                    ("Tier 1 LP", lambda t: max(cu_cash_remaining[t], 0.0),
                     lambda t: abs(t1_addl_lp_dist[t]), lambda t: t1_cash_remaining[t]),
                    ("Tier 1 GP CU", lambda t: max(t1_cash_remaining[t], 0.0),
                     lambda t: abs(t1gp_gp_dist[t]) + abs(t1gp_lp_dist[t]), lambda t: t1gp_cash_remaining[t]),
                ]
                for _sname, _in_fn, _dist_fn, _res_fn in _stage_checks:
                    _s_over = 0
                    _s_neg = 0
                    for _t in range(_pr_max):
                        if not eff_dist_mask[_t]:
                            continue
                        if _dist_fn(_t) > _in_fn(_t) + 0.01:
                            _s_over += 1
                        if _res_fn(_t) < -0.01:
                            _s_neg += 1
                    if _s_over > 0 or _s_neg > 0:
                        _od_any = True

                # ================================================================
                # CASH DISTRIBUTION LINKAGE (PREF + CU + T1 + T1GP)
                # ================================================================
                if cash_dist_output_me_data and cash_dist_output_names:
                    _cd_norm = lambda s: s.strip().lower().replace(" ", "").replace("_", "")
                    _cd_open_norm = _cd_norm("Opening Balance_Cash Distribution")
                    _cd_close_norm = _cd_norm("Closing Cash Balance_Cash Distributions")
                    _cd_oi = None
                    _cd_ci = None

                    # Total LP = Pref LP + CU LP + T1 Addl LP + T1GP LP
                    _cd_total_lp = [
                        lp_dist[t] + cu_lp_dist[t] + t1_addl_lp_dist[t] + t1gp_lp_dist[t]
                        for t in range(_pr_max)
                    ]
                    # Total GP = Pref GP + CU GP + T1GP GP
                    _cd_total_gp = [
                        gp_dist_pref[t] + cu_gp_dist[t] + t1gp_gp_dist[t]
                        for t in range(_pr_max)
                    ]

                    for ri, name in enumerate(cash_dist_output_names):
                        _nn = _cd_norm(str(name)) if name else ""
                        if _nn in ("totaldistributions-gp", "totaldistributionsgp"):
                            cash_dist_output_me_data[ri] = list(_cd_total_gp)
                        elif _nn in ("totaldistributions-lp", "totaldistributionslp"):
                            cash_dist_output_me_data[ri] = list(_cd_total_lp)
                        if _nn == _cd_open_norm:
                            _cd_oi = ri
                            cash_dist_output_me_data[ri] = list(_dyn_cd_opening)
                        elif _nn == _cd_close_norm:
                            _cd_ci = ri
                            cash_dist_output_me_data[ri] = list(_dyn_cd_closing)

                    # Recompute yearly cash distribution with updated rows
                    _cd_flow_ri = []
                    for ri, name in enumerate(cash_dist_output_names):
                        _nn = _cd_norm(str(name)) if name else ""
                        if _nn in ("cashavailablefordistribution",
                                   "totaldistributions-gp", "totaldistributionsgp",
                                   "totaldistributions-lp", "totaldistributionslp"):
                            _cd_flow_ri.append(ri)

                    _yr_bounds_cd2 = _compute_year_boundaries(len(cash_dist_output_me_data[0]), _start_month)
                    _n_years_cd2 = len(_yr_bounds_cd2)
                    cash_dist_output_ye_data = []
                    for ri, (row, name) in enumerate(zip(cash_dist_output_me_data, cash_dist_output_names)):
                        _nn = _cd_norm(str(name)) if name else ""
                        if _nn in (_cd_open_norm, _cd_close_norm):
                            cash_dist_output_ye_data.append([0.0] * _n_years_cd2)
                        else:
                            yr_row = []
                            for ys, ye in _yr_bounds_cd2:
                                end = min(ye, len(row))
                                yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                            cash_dist_output_ye_data.append(yr_row)

                    if _cd_oi is not None and _cd_ci is not None:
                        for yi in range(_n_years_cd2):
                            cash_dist_output_ye_data[_cd_oi][yi] = (
                                cash_dist_output_ye_data[_cd_ci][yi - 1] if yi > 0 else 0.0
                            )
                            _af = sum(cash_dist_output_ye_data[fi][yi] for fi in _cd_flow_ri)
                            cash_dist_output_ye_data[_cd_ci][yi] = (
                                cash_dist_output_ye_data[_cd_oi][yi] + _af
                            )

                    # ── CASH DISTRIBUTION LINKAGE VALIDATION ──
                    _cd_lp_total = sum(_cd_total_lp)
                    _cd_gp_total = sum(_cd_total_gp)
                    _stage_lp_sum = sum(lp_dist) + sum(cu_lp_dist) + sum(t1_addl_lp_dist) + sum(t1gp_lp_dist)
                    _stage_gp_sum = sum(gp_dist_pref) + sum(cu_gp_dist) + sum(t1gp_gp_dist)
                    _final_res = t1gp_cash_remaining[-1] if _pr_max > 0 else 0.0

                # ================================================================
                # PREFERRED RETURNS OUTPUT ASSEMBLY
                # ================================================================
                def _norm_pr(s):
                    return s.strip().lower().replace(" ", "").replace("_", "").replace("-", "")

                _pr_data_lookup = {
                    "beginningbalancepreferredreturns": begin_bal_pref,
                    "lpcapitalcontributions": lp_cap_contrib,
                    "preferredaccrual": pref_accrual,
                    "preferredaccural": pref_accrual,
                    "lpdistributions": lp_dist,
                    "unpaidpreferredreturns": unpaid_pref,
                    "endingbalance": ending_bal_pref,
                    "totallpcashflows": total_lp_cf,
                    "gpcontributions": gp_contrib,
                    "gpdistributionsduringpreferred": gp_dist_pref,
                    "totaldistributionspreferred": total_dist_pref,
                    "cashflowremainingpostpreferredreturnsdistributions": cash_remaining,
                }

                _pr_balance_norms = {
                    "beginningbalancepreferredreturns",
                    "endingbalance",
                }

                blank_row_pr = [0.0] * _pr_max
                pref_returns_output_names = []
                pref_returns_output_me_data = []

                for ti, raw_name in enumerate(raw_pref_returns_names):
                    label_str = str(raw_name).strip() if raw_name is not None else ""
                    _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                    norm_label = _norm_pr(label_str) if not _is_blank else ""

                    if _is_blank:
                        pref_returns_output_names.append("")
                        pref_returns_output_me_data.append([""] * _pr_max)
                    elif norm_label in _pr_data_lookup:
                        pref_returns_output_names.append(label_str)
                        pref_returns_output_me_data.append(list(_pr_data_lookup[norm_label]))
                    else:
                        pref_returns_output_names.append(label_str)
                        pref_returns_output_me_data.append(list(blank_row_pr))

                # Yearly
                _yr_bounds_pr = _compute_year_boundaries(_pr_max, _start_month)
                _n_years_pr = len(_yr_bounds_pr)

                pref_returns_output_ye_data = []
                for ri, (row, name) in enumerate(zip(pref_returns_output_me_data, pref_returns_output_names)):
                    if all(v == "" for v in row):
                        pref_returns_output_ye_data.append([""] * _n_years_pr)
                        continue
                    norm_name = _norm_pr(str(name)) if name else ""
                    if norm_name in _pr_balance_norms:
                        pref_returns_output_ye_data.append([0.0] * _n_years_pr)
                    else:
                        yr_row = []
                        for ys, ye in _yr_bounds_pr:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        pref_returns_output_ye_data.append(yr_row)

                # Independent annual balance roll-forward
                _pr_begin_idx = None
                _pr_unpaid_idx = None
                _pr_ending_idx = None
                for ri, name in enumerate(pref_returns_output_names):
                    nn = _norm_pr(str(name)) if name else ""
                    if nn == "beginningbalancepreferredreturns":
                        _pr_begin_idx = ri
                    elif nn == "endingbalance":
                        _pr_ending_idx = ri

                if _pr_begin_idx is not None and _pr_ending_idx is not None:
                    for yi in range(_n_years_pr):
                        ys, ye = _yr_bounds_pr[yi]
                        _last_month = min(ye, _pr_max) - 1
                        if _last_month >= 0:
                            pref_returns_output_ye_data[_pr_ending_idx][yi] = ending_bal_pref[_last_month]
                        if yi == 0:
                            pref_returns_output_ye_data[_pr_begin_idx][yi] = 0.0
                        else:
                            pref_returns_output_ye_data[_pr_begin_idx][yi] = \
                                pref_returns_output_ye_data[_pr_ending_idx][yi - 1]


                # ================================================================
                # GP CATCHUP OUTPUT ASSEMBLY
                # ================================================================
                raw_gp_catchup_names = _read_array(out_df, OUT_GP_CATCHUP_NAMES)

                _cu_data_lookup = {
                    "lpdistributionscatchupphase": cu_lp_dist,
                    "gpdistributionscatchupphase": cu_gp_dist,
                    "gpcatchupdistributionspostpreferred": cu_gp_dist,
                    "totaldistributionscatchuphurdle": cu_total_dist,
                    "cashflowremainingpostcatchuphurdle": cu_cash_remaining,
                    "cashflowremainingpostgpcatchup": cu_post_cash,
                }
                _cu_fallback_names = [
                    "LP Distributions - Catchup phase",
                    "GP Distributions  - Catchup phase",
                    "Total Distributions - Catchup Hurdle",
                    "Cash Flow Remaining - Post Catchup Hurdle",
                ]
                _cu_fallback_data = [cu_lp_dist, cu_gp_dist, cu_total_dist, cu_cash_remaining]

                gp_catchup_output_names = []
                gp_catchup_output_me_data = []

                if raw_gp_catchup_names:
                    for ti, raw_name in enumerate(raw_gp_catchup_names):
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        norm_label = _norm_pr(label_str) if not _is_blank else ""
                        if _is_blank:
                            gp_catchup_output_names.append("")
                            gp_catchup_output_me_data.append([""] * _pr_max)
                        elif norm_label in _cu_data_lookup:
                            gp_catchup_output_names.append(label_str)
                            gp_catchup_output_me_data.append(list(_cu_data_lookup[norm_label]))
                        else:
                            gp_catchup_output_names.append(label_str)
                            gp_catchup_output_me_data.append([0.0] * _pr_max)
                else:
                    gp_catchup_output_names = list(_cu_fallback_names)
                    gp_catchup_output_me_data = [list(d) for d in _cu_fallback_data]

                # GP Catchup yearly (all flow rows - no balance rows)
                gp_catchup_output_ye_data = []
                for row in gp_catchup_output_me_data:
                    if all(v == "" for v in row):
                        gp_catchup_output_ye_data.append([""] * _n_years_pr)
                    else:
                        yr_row = []
                        for ys, ye in _yr_bounds_pr:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        gp_catchup_output_ye_data.append(yr_row)


                # ================================================================
                # TIER 1 LP OUTPUT ASSEMBLY
                # ================================================================
                raw_tier1_lp_names = _read_array(out_df, OUT_TIER1_LP_NAMES)

                _t1l_data_lookup = {
                    "beginningbalance": t1_begin_bal,
                    "beginningbalancetier1lpdistributions": t1_begin_bal,
                    "lpcapitalcontributions": t1_lp_contrib,
                    "lpcapitalcontributionstier1": t1_lp_contrib,
                    "tier1accural": t1_accrual,
                    "tier1accrual": t1_accrual,
                    "lpdistributionstier1": t1_lp_dist_prior,
                    "lpdistributionspriortotier1": t1_lp_dist_prior,
                    "lppriordistributions(preferred)": t1_lp_dist_prior,
                    "lppriordistributionspreferred": t1_lp_dist_prior,
                    "additionallpdistributionstomeettier1irr": t1_addl_lp_dist,
                    "lpadditionaltier1distributions": t1_addl_lp_dist,
                    "unpaidtier1distributions": t1_unpaid,
                    "endingbalance": t1_ending_bal,
                    "endingbalancetier1lpdistributions": t1_ending_bal,
                    "cashflowremainingposttier1lpdistributions": t1_cash_remaining,
                    "totallpcashflowsposttier1": t1_total_lp_cf,
                }
                _t1l_balance_norms = {
                    "beginningbalance",
                    "beginningbalancetier1lpdistributions",
                    "unpaidtier1distributions",
                    "endingbalance",
                    "endingbalancetier1lpdistributions",
                }
                _t1l_fallback_names = [
                    "Beginning Balance",
                    "LP Capital Contributions - Tier 1",
                    "Tier 1 Accural",
                    "LP Distributions prior to tier 1",
                    "Additional LP Distributions to meet tier 1 IRR",
                    "Unpaid Tier 1 Distributions",
                    "Ending Balance",
                    "Total LP Cashflows  - Post Tier 1",
                    "Cash Flow Remaining - Post Tier 1 LP Distributions",
                ]
                _t1l_fallback_data = [
                    t1_begin_bal, t1_lp_contrib, t1_accrual, t1_lp_dist_prior,
                    t1_addl_lp_dist, t1_unpaid, t1_ending_bal, t1_total_lp_cf,
                    t1_cash_remaining,
                ]

                tier1_lp_output_names = []
                tier1_lp_output_me_data = []

                if raw_tier1_lp_names:
                    for ti, raw_name in enumerate(raw_tier1_lp_names):
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        norm_label = _norm_pr(label_str) if not _is_blank else ""
                        if _is_blank:
                            tier1_lp_output_names.append("")
                            tier1_lp_output_me_data.append([""] * _pr_max)
                        elif norm_label in _t1l_data_lookup:
                            tier1_lp_output_names.append(label_str)
                            tier1_lp_output_me_data.append(list(_t1l_data_lookup[norm_label]))
                        else:
                            tier1_lp_output_names.append(label_str)
                            tier1_lp_output_me_data.append([0.0] * _pr_max)
                else:
                    tier1_lp_output_names = list(_t1l_fallback_names)
                    tier1_lp_output_me_data = [list(d) for d in _t1l_fallback_data]

                # Tier 1 LP yearly
                tier1_lp_output_ye_data = []
                for ri, (row, name) in enumerate(zip(tier1_lp_output_me_data, tier1_lp_output_names)):
                    if all(v == "" for v in row):
                        tier1_lp_output_ye_data.append([""] * _n_years_pr)
                        continue
                    norm_name = _norm_pr(str(name)) if name else ""
                    if norm_name in _t1l_balance_norms:
                        tier1_lp_output_ye_data.append([0.0] * _n_years_pr)
                    else:
                        yr_row = []
                        for ys, ye in _yr_bounds_pr:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        tier1_lp_output_ye_data.append(yr_row)

                # Independent annual balance for Tier 1 LP
                _t1_begin_ri = None
                _t1_unpaid_ri = None
                _t1_ending_ri = None
                for ri, name in enumerate(tier1_lp_output_names):
                    nn = _norm_pr(str(name)) if name else ""
                    if nn == "beginningbalance":
                        _t1_begin_ri = ri
                    elif nn == "unpaidtier1distributions":
                        _t1_unpaid_ri = ri
                    elif nn == "endingbalance":
                        _t1_ending_ri = ri

                if _t1_begin_ri is not None and _t1_ending_ri is not None:
                    for yi in range(_n_years_pr):
                        ys, ye = _yr_bounds_pr[yi]
                        _last_month = min(ye, _pr_max) - 1
                        if _last_month >= 0:
                            tier1_lp_output_ye_data[_t1_ending_ri][yi] = _t1_deficiency[_last_month]
                        if yi == 0:
                            tier1_lp_output_ye_data[_t1_begin_ri][yi] = 0.0
                        else:
                            tier1_lp_output_ye_data[_t1_begin_ri][yi] = \
                                tier1_lp_output_ye_data[_t1_ending_ri][yi - 1]

                if _t1_unpaid_ri is not None:
                    for yi in range(_n_years_pr):
                        ys, ye = _yr_bounds_pr[yi]
                        _last_month = min(ye, _pr_max) - 1
                        if _last_month >= 0:
                            tier1_lp_output_ye_data[_t1_unpaid_ri][yi] = _t1_deficiency[_last_month]


                # ================================================================
                # TIER 1 GP CATCHUP OUTPUT ASSEMBLY
                # ================================================================
                raw_tier1_gp_cu_names = _read_array(out_df, OUT_TIER1_GP_CU_NAMES)

                _t1g_data_lookup = {
                    "gpdistributionstier1gpcatchup": t1gp_gp_dist,
                    "tier1gpcatchup": t1gp_gp_dist,
                    "lpdistributionstier1gpcatchup": t1gp_lp_dist,
                    "totaldistributionstier1gpcatchup": t1gp_total_dist,
                    "cashflowremainingposttier1gpcatchup": t1gp_cash_remaining,
                    # Common normalized variants
                    "gpdistributions": t1gp_gp_dist,
                    "totaldistributions": t1gp_total_dist,
                }
                _t1g_fallback_names = [
                    "GP Distributions - Tier 1 GP Catch up",
                    "Total Distributions - Tier 1 GP Catch up",
                    "Cash Flow Remaining - Post Tier 1 GP Catch up",
                ]
                _t1g_fallback_data = [t1gp_gp_dist, t1gp_total_dist, t1gp_cash_remaining]

                tier1_gp_cu_output_names = []
                tier1_gp_cu_output_me_data = []

                if raw_tier1_gp_cu_names:
                    for ti, raw_name in enumerate(raw_tier1_gp_cu_names):
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        norm_label = _norm_pr(label_str) if not _is_blank else ""
                        if _is_blank:
                            tier1_gp_cu_output_names.append("")
                            tier1_gp_cu_output_me_data.append([""] * _pr_max)
                        elif norm_label in _t1g_data_lookup:
                            tier1_gp_cu_output_names.append(label_str)
                            tier1_gp_cu_output_me_data.append(list(_t1g_data_lookup[norm_label]))
                        else:
                            tier1_gp_cu_output_names.append(label_str)
                            tier1_gp_cu_output_me_data.append([0.0] * _pr_max)
                else:
                    tier1_gp_cu_output_names = list(_t1g_fallback_names)
                    tier1_gp_cu_output_me_data = [list(d) for d in _t1g_fallback_data]

                # Tier 1 GP CU yearly (all flow rows - no balance rows)
                tier1_gp_cu_output_ye_data = []
                for row in tier1_gp_cu_output_me_data:
                    if all(v == "" for v in row):
                        tier1_gp_cu_output_ye_data.append([""] * _n_years_pr)
                    else:
                        yr_row = []
                        for ys, ye in _yr_bounds_pr:
                            end = min(ye, len(row))
                            yr_row.append(sum(_to_float(v) for v in row[ys:end]))
                        tier1_gp_cu_output_ye_data.append(yr_row)


                # ================================================================
                # TIER 2 / TIER 3 OUTPUT ASSEMBLY — DISABLED IN THIS PATCH
                # All computation arrays are zeroed; template rows preserved
                # with zero data so workbook structure is intact.
                # ================================================================
                enable_tier2_and_beyond = False

                # -- Tier 2 LP: read template, fill all data rows with zeros --
                raw_tier2_lp_names = _read_array(out_df, OUT_TIER2_LP_NAMES)
                tier2_lp_output_names = []
                tier2_lp_output_me_data = []
                tier2_lp_output_ye_data = []
                if raw_tier2_lp_names:
                    for raw_name in raw_tier2_lp_names:
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        tier2_lp_output_names.append("" if _is_blank else label_str)
                        tier2_lp_output_me_data.append([""] * _pr_max if _is_blank else [0.0] * _pr_max)
                    tier2_lp_output_ye_data = [
                        [""] * _n_years_pr if all(v == "" for v in r) else [0.0] * _n_years_pr
                        for r in tier2_lp_output_me_data
                    ]

                # -- Tier 2 GP CU: read template, fill all data rows with zeros --
                raw_tier2_gp_cu_names = _read_array(out_df, OUT_TIER2_GP_CU_NAMES)
                tier2_gp_cu_output_names = []
                tier2_gp_cu_output_me_data = []
                tier2_gp_cu_output_ye_data = []
                if raw_tier2_gp_cu_names:
                    for raw_name in raw_tier2_gp_cu_names:
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        tier2_gp_cu_output_names.append("" if _is_blank else label_str)
                        tier2_gp_cu_output_me_data.append([""] * _pr_max if _is_blank else [0.0] * _pr_max)
                    tier2_gp_cu_output_ye_data = [
                        [""] * _n_years_pr if all(v == "" for v in r) else [0.0] * _n_years_pr
                        for r in tier2_gp_cu_output_me_data
                    ]

                # -- Tier 3: read template, fill all data rows with zeros --
                raw_tier3_names = _read_array(out_df, OUT_TIER3_NAMES)
                tier3_output_names = []
                tier3_output_me_data = []
                tier3_output_ye_data = []
                if raw_tier3_names:
                    for raw_name in raw_tier3_names:
                        label_str = str(raw_name).strip() if raw_name is not None else ""
                        _is_blank = (not label_str) or label_str == "0" or label_str.lower() == "nan"
                        tier3_output_names.append("" if _is_blank else label_str)
                        tier3_output_me_data.append([""] * _pr_max if _is_blank else [0.0] * _pr_max)
                    tier3_output_ye_data = [
                        [""] * _n_years_pr if all(v == "" for v in r) else [0.0] * _n_years_pr
                        for r in tier3_output_me_data
                    ]

            else:
                pass
        else:
            pass

        if max_periods == 0:
            return {"exceloutput": {}, "consolidationoutput": {}}

        fcff_ye_data, yearly_cols = _monthly_to_yearly(fcff_me_data, max_periods, _start_month)
        monthly_cols = list(range(max_periods))

        _print_stage(7, "FCFF ASSEMBLY", {
            "FCFF rows": len(fcff_names),
            "Monthly periods": max_periods,
            "Yearly periods": len(yearly_cols),
        })

        # Log consolidated totals for each summary row
        for label, row in zip(fcff_names, fcff_me_data):
            if label != "0":
                total = sum(_to_float(v) for v in row)
                if abs(total) > 0.01:
                    pass

        # ----------------------------------------------------------------
        # 8. Build timeline from model dates
        # ----------------------------------------------------------------
        timeline_me_payload: Optional[dict] = None
        timeline_ye_payload: Optional[dict] = None

        _tl_model_start = MasterSheet.Global.ModelAssumptions.model_start_date
        _tl_model_end = MasterSheet.Global.ModelAssumptions.model_end_date

        if _tl_model_start is not None and _tl_model_end is not None:
            # Normalise dates: start aa a first of month, end aa a last of month
            ts_start = pd.Timestamp(_tl_model_start).replace(day=1)
            ts_end = pd.Timestamp(_tl_model_end) + pd.offsets.MonthEnd(0)

            tl_me_df = fn_create_model_timeline(ts_start, ts_end, "ME")

            # Derive yearly timeline from monthly timeline using calendar-year
            # boundaries so column count matches _monthly_to_yearly output.
            _tl_bounds = _compute_year_boundaries(len(tl_me_df), _start_month)
            ye_rows: List[dict] = []
            for ys, ye in _tl_bounds:
                chunk = tl_me_df.iloc[ys:ye]
                ye_rows.append({
                    'Period Start': chunk['Period Start'].iloc[0],
                    'Period End':   chunk['Period End'].iloc[-1],
                    'Year':         int(chunk['Year'].iloc[-1]),
                    'Month':        int(chunk['Month'].iloc[-1]),
                    '# of Days':    int(chunk['# of Days'].sum()),
                })
            tl_ye_df = pd.DataFrame(ye_rows)
            tl_ye_df['# of Period'] = list(range(1, len(tl_ye_df) + 1))
            tl_ye_df = tl_ye_df[['Period Start', 'Period End', 'Year', 'Month', '# of Period', '# of Days']]

            # Transpose so rows = attribute, cols = periods (matching LandCo)
            tl_me_T = tl_me_df.T
            tl_ye_T = tl_ye_df.T

            # Convert dates to ISO strings for JSON serialisation
            def _serialise_row(row):
                out = []
                for v in row:
                    if isinstance(v, (pd.Timestamp, datetime)):
                        out.append(v.strftime("%Y-%m-%d"))
                    else:
                        try:
                            out.append(int(v) if float(v) == int(float(v)) else float(v))
                        except (ValueError, TypeError):
                            out.append(str(v))
                return out

            me_data = [_serialise_row(tl_me_T.iloc[r]) for r in range(len(tl_me_T))]
            ye_data = [_serialise_row(tl_ye_T.iloc[r]) for r in range(len(tl_ye_T))]

            timeline_me_payload = {
                "index": list(tl_me_T.index),
                "columns": list(range(len(tl_me_T.columns))),
                "data": me_data,
            }
            timeline_ye_payload = {
                "index": list(tl_ye_T.index),
                "columns": list(range(len(tl_ye_T.columns))),
                "data": ye_data,
            }
        else:
            # Fallback: try upstream Timeline from LandCo/DevCo
            for src in (landco_data, devco_data):
                if not src or "Timeline" not in src:
                    continue
                tl = src["Timeline"]
                if not isinstance(tl, dict) or "data" not in tl:
                    continue
                timeline_me_payload = tl

                tl_cols = tl.get("columns", [])
                _fb_bounds = _compute_year_boundaries(len(tl_cols), _start_month)
                yearly_tl_cols = list(range(len(_fb_bounds)))

                tl_data = tl.get("data", [])
                tl_index = tl.get("index", [])
                yearly_tl_data: List[list] = []
                for ri, tl_row in enumerate(tl_data):
                    row_label = str(tl_index[ri]).lower() if ri < len(tl_index) else ""
                    yr_row: List[Any] = []
                    for yi, (ys, ye) in enumerate(_fb_bounds):
                        end = min(ye, len(tl_row))
                        chunk = tl_row[ys:end]
                        if not chunk:
                            yr_row.append("")
                        elif "period start" in row_label:
                            yr_row.append(chunk[0])
                        elif "# of period" in row_label:
                            yr_row.append(yi + 1)
                        elif "# of days" in row_label:
                            yr_row.append(sum(int(float(v)) for v in chunk
                                              if str(v).replace('.', '').replace('-', '').isdigit()))
                        else:
                            yr_row.append(chunk[-1])
                    yearly_tl_data.append(yr_row)

                timeline_ye_payload = {
                    "index": tl.get("index", []),
                    "columns": yearly_tl_cols,
                    "data": yearly_tl_data,
                }
                break

        _print_stage(8, "TIMELINE", {
            "Monthly timeline": "PRESENT" if timeline_me_payload else "ABSENT",
            "Yearly timeline": "PRESENT" if timeline_ye_payload else "ABSENT",
        })

        # ----------------------------------------------------------------
        # 9. Assemble excel output
        # ----------------------------------------------------------------
        # === PRE-PASTE VALIDATION ===
        # Validate FCFF monthly
        for ri, (label, row) in enumerate(zip(fcff_names, fcff_me_data)):
            if len(row) != max_periods:
                pass
        # Validate FCFF yearly
        for ri, row in enumerate(fcff_ye_data):
            if len(row) != len(yearly_cols):
                pass
        # Validate timeline
        if timeline_me_payload:
            tl_data = timeline_me_payload.get("data", [])
        if timeline_ye_payload:
            tl_data = timeline_ye_payload.get("data", [])

        excel_output = _build_excel_output(
            fcff_names, fcff_me_data, fcff_ye_data,
            monthly_cols, yearly_cols,
            timeline_me_payload, timeline_ye_payload,
            cff_rows=cff_rows,
            max_periods=max_periods,
            cashflows_names=cashflows_names,
            cashflows_me_data=cashflows_me_data,
            cashflows_ye_data=cashflows_ye_data,
            project_cost_names=project_cost_names,
            project_cost_ye_data=project_cost_ye_data,
            project_cost_me_data=project_cost_me_data,
            fees_names=fees_names,
            fees_me_data=fees_me_data,
            fees_ye_data=fees_ye_data,
            asset_sales_names=asset_sales_names,
            asset_sales_me_data=asset_sales_me_data,
            asset_sales_ye_data=asset_sales_ye_data,
            total_funding_names=total_funding_names,
            total_funding_me_data=total_funding_me_data,
            total_funding_ye_data=total_funding_ye_data,
            tl1_names=tl1_output_names,
            tl1_me_data=tl1_output_me_data,
            tl1_ye_data=tl1_output_ye_data,
            refi_names=refi_output_names,
            refi_me_data=refi_output_me_data,
            refi_ye_data=refi_output_ye_data,
            tl1_sched_names=tl1_sched_output_names,
            tl1_sched_me_data=tl1_sched_output_me_data,
            tl1_sched_ye_data=tl1_sched_output_ye_data,
            refi_sched_names=refi_sched_output_names,
            refi_sched_me_data=refi_sched_output_me_data,
            refi_sched_ye_data=refi_sched_output_ye_data,
            refi_mindscr_names=refi_mindscr_output_names,
            refi_mindscr_me_data=refi_mindscr_output_me_data,
            refi_mindscr_ye_data=refi_mindscr_output_ye_data,
            equity_sched_names=eq_sched_output_names,
            equity_sched_me_data=eq_sched_output_me_data,
            equity_sched_ye_data=eq_sched_output_ye_data,
            addl_eq_req_names=addl_eq_req_output_names,
            addl_eq_req_me_data=addl_eq_req_output_me_data,
            addl_eq_req_ye_data=addl_eq_req_output_ye_data,
            addl_eq_commit_names=addl_eq_commit_output_names,
            addl_eq_commit_me_data=addl_eq_commit_output_me_data,
            addl_eq_commit_ye_data=addl_eq_commit_output_ye_data,
            lik_commit_names=lik_commit_output_names,
            lik_commit_me_data=lik_commit_output_me_data,
            lik_commit_ye_data=lik_commit_output_ye_data,
            total_commit_names=total_commit_output_names,
            total_commit_me_data=total_commit_output_me_data,
            total_commit_ye_data=total_commit_output_ye_data,
            cash_dist_names=cash_dist_output_names,
            cash_dist_me_data=cash_dist_output_me_data,
            cash_dist_ye_data=cash_dist_output_ye_data,
            pref_returns_names=pref_returns_output_names,
            pref_returns_me_data=pref_returns_output_me_data,
            pref_returns_ye_data=pref_returns_output_ye_data,
            gp_catchup_names=gp_catchup_output_names,
            gp_catchup_me_data=gp_catchup_output_me_data,
            gp_catchup_ye_data=gp_catchup_output_ye_data,
            tier1_lp_names=tier1_lp_output_names,
            tier1_lp_me_data=tier1_lp_output_me_data,
            tier1_lp_ye_data=tier1_lp_output_ye_data,
            tier1_gp_cu_names=tier1_gp_cu_output_names,
            tier1_gp_cu_me_data=tier1_gp_cu_output_me_data,
            tier1_gp_cu_ye_data=tier1_gp_cu_output_ye_data,
            tier2_lp_names=tier2_lp_output_names,
            tier2_lp_me_data=tier2_lp_output_me_data,
            tier2_lp_ye_data=tier2_lp_output_ye_data,
            tier2_gp_cu_names=tier2_gp_cu_output_names,
            tier2_gp_cu_me_data=tier2_gp_cu_output_me_data,
            tier2_gp_cu_ye_data=tier2_gp_cu_output_ye_data,
            tier3_names=tier3_output_names,
            tier3_me_data=tier3_output_me_data,
            tier3_ye_data=tier3_output_ye_data,
        )

        # === POST-BUILD VALIDATION: verify actual payload structure ===
        for freq_key in ("monthly_dfs", "annual_dfs"):
            dfs = excel_output.get(freq_key, {})
            for df_name, (nr_key, split) in dfs.items():
                d = split.get("data", [])
                rows_out = len(d)
                cols_out = len(d[0]) if d else 0
                # Check for inconsistent column counts
                bad = [i for i, r in enumerate(d) if len(r) != cols_out]
                if bad:
                    pass
                # Show first row values (first 5 cols)
                if d:
                    preview = d[0][:5]

        _print_stage(9, "OUTPUT POPULATION", {
            "o.jv.fcff.me": f"{len(fcff_names)} rows x {max_periods} cols",
            "o.jv.fcff.ye": f"{len(fcff_names)} rows x {len(yearly_cols)} cols",
            "Monthly Timeline": "YES" if timeline_me_payload else "NO",
            "Yearly Timeline": "YES" if timeline_ye_payload else "NO",
        })

        # Log output paste mapping
        for key, code in OUTPUT_PASTE_MAP.items():
            pass

        # ----------------------------------------------------------------
        # 10. Print FCFF CFS
        # ----------------------------------------------------------------
        _print_fcff_summary(fcff_names, fcff_me_data, max_periods)

        # Print class attribute summary
        for cls_name in sorted(n for n in dir(MasterSheet.Global) if isinstance(getattr(MasterSheet.Global, n), type)):
            cls = getattr(MasterSheet.Global, cls_name)
            attrs = [a for a in dir(cls) if not a.startswith("_")]
            set_count = sum(1 for a in attrs if getattr(cls, a) is not None)
        for cls_name in sorted(n for n in dir(MasterSheet.Asset) if isinstance(getattr(MasterSheet.Asset, n), type)):
            cls = getattr(MasterSheet.Asset, cls_name)
            attrs = [a for a in dir(cls) if not a.startswith("_")]
            is_list = any(isinstance(getattr(cls, a), list) for a in attrs)
            if is_list:
                sample = next((getattr(cls, a) for a in attrs if isinstance(getattr(cls, a), list)), [])
            else:
                pass
        for cls_name in sorted(n for n in dir(JVInputs.Global) if isinstance(getattr(JVInputs.Global, n), type)):
            cls = getattr(JVInputs.Global, cls_name)
            attrs = [a for a in dir(cls) if not a.startswith("_")]
            set_count = sum(1 for a in attrs if getattr(cls, a) is not None)
        for cls_name in sorted(n for n in dir(JVInputs.Asset) if isinstance(getattr(JVInputs.Asset, n), type)):
            cls = getattr(JVInputs.Asset, cls_name)
            attrs = [a for a in dir(cls) if not a.startswith("_")]
            is_list = any(isinstance(getattr(cls, a), list) for a in attrs)
            if is_list:
                sample = next((getattr(cls, a) for a in attrs if isinstance(getattr(cls, a), list)), [])
            else:
                pass


        # aaa, Build detailed loan schedule workbook data aaa,
        # Two worksheets: "Term Loan 1 Schedule" and "Refinancing Schedule"
        # Each has Month Start / Month End timeline + schedule rows.
        loan_schedule_sheets: Dict[str, dict] = {}
        if cff_rows and max_periods > 0:
            # Generate month-start / month-end arrays
            _ls_model_start = model_start
            if _ls_model_start is None:
                _ls_model_start = MasterSheet.Global.ModelAssumptions.model_start_date
            _ls_month_starts: List[str] = []
            _ls_month_ends: List[str] = []
            if _ls_model_start is not None:
                _ts_base = pd.Timestamp(_ls_model_start).replace(day=1)
                for _m in range(max_periods):
                    _ms = _ts_base + pd.DateOffset(months=_m)
                    _me = _ms + pd.offsets.MonthEnd(0)
                    _ls_month_starts.append(_ms.strftime("%Y-%m-%d"))
                    _ls_month_ends.append(_me.strftime("%Y-%m-%d"))
            else:
                _ls_month_starts = [str(i) for i in range(max_periods)]
                _ls_month_ends = [str(i) for i in range(max_periods)]

            _ls_zeros = _zeros(max_periods)

            # aaa, Term Loan 1 Schedule worksheet aaa,
            _tl1_sched_amort = [
                cff_rows.get("_tl1_repayments", _ls_zeros)[t]
                - cff_rows.get("_tl1_balloon_payment", _ls_zeros)[t]
                for t in range(max_periods)
            ]
            tl1_schedule = {
                "sheet_name": "Term Loan 1 Schedule",
                "headers": {
                    "Month Start": _ls_month_starts,
                    "Month End": _ls_month_ends,
                },
                "rows": [
                    ("Opening Balance",                  list(cff_rows.get("_tl1_opening_balance", _ls_zeros))),
                    ("Principal / Loan Raised",          list(cff_rows.get("_tl1_loan_additions", _ls_zeros))),
                    ("Interest Expense Incurred",        list(cff_rows.get("_tl1_interest_incurred", _ls_zeros))),
                    ("Interest Expense Paid",            list(cff_rows.get("_tl1_interest_paid", _ls_zeros))),
                    ("Interest Expense Capitalized",     list(cff_rows.get("_tl1_capitalized_interest", _ls_zeros))),
                    ("Arrangement Fees Paid",            list(cff_rows.get("_tl1_arrangement_fees", _ls_zeros))),
                    ("Arrangement Fees Capitalized",     list(cff_rows.get("_tl1_capitalized_arr_fees", _ls_zeros))),
                    ("EMI / Scheduled Principal Repayment", _tl1_sched_amort),
                    ("Balloon Payment",                  list(cff_rows.get("_tl1_balloon_payment", _ls_zeros))),
                    ("Total Debt Repaid",                list(cff_rows.get("_tl1_repayments", _ls_zeros))),
                    ("Closing Balance",                  list(cff_rows.get("_tl1_closing_balance", _ls_zeros))),
                    ("Interest Rate Applied",            list(cff_rows.get("_tl1_interest_rate_applied", _ls_zeros))),
                    ("Amortization % Applied",           list(cff_rows.get("_tl1_amort_pct_applied", _ls_zeros))),
                ],
            }
            loan_schedule_sheets["tl1"] = tl1_schedule

            # aaa, Refinancing Schedule worksheet aaa,
            _tl2_sched_amort = [
                cff_rows.get("_tl2_repayments", _ls_zeros)[t]
                - cff_rows.get("_tl2_balloon_payment", _ls_zeros)[t]
                for t in range(max_periods)
            ]
            # DSCR month on month: operating CF / debt service
            # Operating CF = Total Free Cashflow before Financing (from CFF)
            _tl2_op_cf = cff_rows.get(
                "Total Free Cashflow before Financing", _ls_zeros)
            _tl2_dscr: List[float] = []
            for _t in range(max_periods):
                _ds = (cff_rows.get("_tl2_repayments", _ls_zeros)[_t]
                       + cff_rows.get("_tl2_interest_paid", _ls_zeros)[_t])
                if abs(_ds) > 0.01:
                    _tl2_dscr.append(_tl2_op_cf[_t] / _ds)
                else:
                    _tl2_dscr.append(0.0)

            tl2_schedule = {
                "sheet_name": "Refinancing Schedule",
                "headers": {
                    "Month Start": _ls_month_starts,
                    "Month End": _ls_month_ends,
                },
                "rows": [
                    ("Opening Balance",                  list(cff_rows.get("_tl2_opening_balance", _ls_zeros))),
                    ("Principal / Loan Raised",          list(cff_rows.get("_tl2_loan_additions", _ls_zeros))),
                    ("Interest Expense Incurred",        list(cff_rows.get("_tl2_interest_incurred", _ls_zeros))),
                    ("Interest Expense Paid",            list(cff_rows.get("_tl2_interest_paid", _ls_zeros))),
                    ("Interest Expense Capitalized",     list(cff_rows.get("_tl2_capitalized_interest", _ls_zeros))),
                    ("Arrangement Fees Paid",            list(cff_rows.get("_tl2_arrangement_fees", _ls_zeros))),
                    ("Arrangement Fees Capitalized",     list(cff_rows.get("_tl2_capitalized_arr_fees", _ls_zeros))),
                    ("EMI / Scheduled Principal Repayment", _tl2_sched_amort),
                    ("Balloon Payment",                  list(cff_rows.get("_tl2_balloon_payment", _ls_zeros))),
                    ("Total Debt Repaid",                list(cff_rows.get("_tl2_repayments", _ls_zeros))),
                    ("Closing Balance",                  list(cff_rows.get("_tl2_closing_balance", _ls_zeros))),
                    ("Interest Rate Applied",            list(cff_rows.get("_tl2_interest_rate_applied", _ls_zeros))),
                    ("Amortization % Applied",           list(cff_rows.get("_tl2_amort_pct_applied", _ls_zeros))),
                    ("DSCR",                             _tl2_dscr),
                ],
            }
            loan_schedule_sheets["tl2"] = tl2_schedule


        # return {
        #     "exceloutput": excel_output,
        #     "consolidationoutput": {},
        # }
        return {
            "exceloutput": excel_output,
            "consolidationoutput": {},
            "loan_schedule_sheets": loan_schedule_sheets
                if loan_schedule_sheets else {},
        }

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
        else:
            pass
        return None


def fninitialising_all_values(payload: Any, is_save: bool) -> Optional[Any]:
    """Entry point  delegates to wrapper_for_vars.  Signature unchanged."""
    try:
        if payload is None:
            return None
        if not isinstance(payload, (dict, list)):
            return None

        return wrapper_for_vars(payload)

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
        else:
            pass
        return None
