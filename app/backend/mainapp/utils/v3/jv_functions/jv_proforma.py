"""
JV Consolidation — Proforma Structure and CFF Key Map
======================================================

``proforma_structure``
    Canonical layout of the JV Consolidation output, organised into six
    top-level sections.  Each entry carries a ``type`` that controls how
    the output renderer treats it:

    * ``section``     — top-level section header row; no numeric values
    * ``subsection``  — second-level header row; no numeric values
    * ``line_item``   — data row; values are assigned from monthly CFF/FCFF arrays
    * ``empty_row``   — blank separator row; all values are ``None``

``PROFORMA_CFF_KEY_MAP``
    Maps every ``line_item`` to its resolution descriptor.

    Key format:
        ``(section_name, item_name)``           — unambiguous items
        ``(section_name, "SubsecName / item")`` — items whose label repeats
            within the same section under different subsections

    The renderer tries the subsection-contextual key first, then the plain key,
    so only the *non-default* occurrences need a disambiguated entry.

    Resolution descriptor fields (one required):
        ``"key"``     — direct lookup in the vehicle CFF dict
        ``"source"``  — FCFF sentinel resolved from the ``fcff_sources`` dict
        ``"compute"`` — ``{"op": "sub"|"add", "a": cff_key, "b": cff_key}``
        ``"combine"`` — list of CFF keys summed element-wise
        ``"zero"``    — ``True``; always emit a zero row (key not yet in engine)

    FCFF sentinel constants (matched against ``"source"`` at render time):
        ``FCFF_LANDCO``    LandCo FCFF aggregate across all assets
        ``FCFF_DEVCO``     DevCo FCFF aggregate
        ``FCFF_ASSETCO``   AssetCo FCFF aggregate
        ``FCFF_TOTAL``     Total FCFF before financing and SPV cost
"""

from typing import Any, Dict, List

# =====================================================================
# Proforma Structure
# =====================================================================

proforma_structure: Dict[str, Any] = {

    "Cash Waterfall and Return distribution": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Entity Level Free Cashflows",
                "type": "subsection",
                "items": [
                    {"name": "LandCo Free Cashflow",                            "type": "line_item"},
                    {"name": "DevCo Free Cashflow",                             "type": "line_item"},
                    {"name": "AssetCo Free Cashflow",                           "type": "line_item"},
                    {"name": "Cash Flow before Financing and SPV-related Cost", "type": "line_item"},
                    {"type": "empty_row"},
                ]
            },
            {
                "name": "Fund-related Expenses",
                "type": "subsection",
                "items": [
                    {"name": "JV Setup Fees",                       "type": "line_item"},
                    {"name": "Fund Management Fees",                "type": "line_item"},
                    {"name": "Other Fees",                          "type": "line_item"},
                    {"name": "JV Liquidation Fees",                 "type": "line_item"},
                    {"name": "Cash Flow before Financing Cost",     "type": "line_item"},
                    {"type": "empty_row"},
                ]
            },
            {
                "name": "Funding-related Cost",
                "type": "subsection",
                "items": [
                    {"name": "Arrangement Fees",        "type": "line_item"},
                    {"name": "Commitment Fees",         "type": "line_item"},
                    {"name": "Interest Cost",           "type": "line_item"},
                    {"name": "Cash Flow before Financing", "type": "line_item"},
                    {"type": "empty_row"},
                ]
            },
            {
                "name": "Source of Funding",
                "type": "subsection",
                "items": [
                    {"name": "Loan Raised",                             "type": "subsection"},
                    {"name": "Debt 1",                                  "type": "line_item"},
                    {"name": "Debt 2",                                  "type": "line_item"},
                    {"name": "Equity Raised",                           "type": "subsection"},
                    {"name": "LP",                                      "type": "line_item"},
                    {"name": "GP",                                      "type": "line_item"},
                    {"name": "Cash Flow before Distributions and Repayments", "type": "line_item"},
                    {"type": "empty_row"},
                ]
            },
            {
                "name": "Distributions and Repayments",
                "type": "subsection",
                "items": [
                    {"name": "Loan Repaid",             "type": "subsection"},
                    {"name": "Debt 1",                  "type": "line_item"},
                    {"name": "Debt 2",                  "type": "line_item"},
                    {"name": "Return of Capital",       "type": "subsection"},
                    {"name": "LP",                      "type": "line_item"},
                    {"name": "GP",                      "type": "line_item"},
                    {"name": "Distributions",                        "type": "subsection"},
                    {"name": "Preferred Return",                     "type": "line_item"},
                    {"name": "GP Promote & Catchup (Post Preferred)", "type": "line_item"},
                    {"name": "Tier 1 LP Distributions",              "type": "line_item"},
                    {"name": "Tier 1 GP Promote",                    "type": "line_item"},
                    {"name": "Tier 1 GP Catchup",                    "type": "line_item"},
                    {"name": "Tier 2 LP Distributions",              "type": "line_item"},
                    {"name": "Tier 2 GP Promote",                    "type": "line_item"},
                    {"name": "Tier 2 GP Catchup",                    "type": "line_item"},
                    {"name": "Tier 3 LP Distributions",              "type": "line_item"},
                    {"name": "Tier 3 GP Distributions",              "type": "line_item"},
                    {"name": "Compensation in Lieu of Land (GP)",    "type": "line_item"},
                    {"name": "Compensation in Lieu of Land (LP)",    "type": "line_item"},
                    {"name": "Net Cashflow from Projects",           "type": "line_item"},
                ]
            },
        ]
    },

    "Debt 1 Account": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Debt 1 Schedule",
                "type": "subsection",
                "items": [
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "Amount Raised",                       "type": "line_item"},
                    {"name": "Arrangement Fees Capitalization",     "type": "line_item"},
                    {"name": "Commitment Fees Capitalization",      "type": "line_item"},
                    {"name": "Interest During Constuction (IDC)",   "type": "line_item"},
                    {"name": "Principal Repayment",                 "type": "line_item"},
                    {"name": "Bullet Payment",                      "type": "line_item"},
                    {"name": "Closing Balance",                     "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Interest Expense",                    "type": "line_item"},
                    {"name": "Arrangement Fees",                    "type": "line_item"},
                    {"name": "Commitment Fees",                     "type": "line_item"},
                ]
            },
        ]
    },

    "Refinancing Debt Account": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Refinancing Debt Schedule",
                "type": "subsection",
                "items": [
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "Amount Raised",                       "type": "line_item"},
                    {"name": "Arrangement Fees Capitalization",     "type": "line_item"},
                    {"name": "Commitment Fees Capitalization",      "type": "line_item"},
                    {"name": "Interest During Constuction (IDC)",   "type": "line_item"},
                    {"name": "Principal Repayment",                 "type": "line_item"},
                    {"name": "Bullet Payment",                      "type": "line_item"},
                    {"name": "Closing Balance",                     "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Interest Expense",                    "type": "line_item"},
                    {"name": "Arrangement Fees",                    "type": "line_item"},
                    {"name": "Commitment Fees",                     "type": "line_item"},
                ]
            },
        ]
    },

    "Equity Scehdule": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Equity",
                "type": "subsection",
                "items": [
                    {"name": "Cash Equity Infusion Requirement",    "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Cash Equity Commitment",              "type": "subsection"},
                    {"name": "GP Commitment",                       "type": "line_item"},
                    {"name": "LP Commitment",                       "type": "line_item"},
                    {"name": "Total Cash Equity",                   "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Equity In Kind",                      "type": "subsection"},
                    {"name": "Land In Kind (GP)",                   "type": "line_item"},
                    {"name": "Land In Kind (LP)",                   "type": "line_item"},
                    {"name": "Total In Kind Equity",                "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Total Equity Commitment",             "type": "subsection"},
                    {"name": "GP Equity",                           "type": "line_item"},
                    {"name": "LP Others Equity",                    "type": "line_item"},
                    {"name": "Total Equity Commitment",             "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Distribution Summary",                         "type": "subsection"},
                    {"name": "Return of Capital",                            "type": "line_item"},
                    {"name": "Preferred Return",                             "type": "line_item"},
                    {"name": "GP Promote & Catchup (Post Preferred)",        "type": "line_item"},
                    {"name": "Tier 1 LP Distributions",                      "type": "line_item"},
                    {"name": "Tier 1 GP Promote",                            "type": "line_item"},
                    {"name": "Tier 1 GP Catchup",                            "type": "line_item"},
                    {"name": "Tier 2 LP Distributions",                      "type": "line_item"},
                    {"name": "Tier 2 GP Promote",                            "type": "line_item"},
                    {"name": "Tier 2 GP Catchup",                            "type": "line_item"},
                    {"name": "Tier 3 LP Distributions",                      "type": "line_item"},
                    {"name": "Tier 3 GP Distributions",                      "type": "line_item"},
                    {"name": "Compensation in Lieu of Land (GP)",            "type": "line_item"},
                    {"name": "Compensation in Lieu of Land (LP)",            "type": "line_item"},
                    {"name": "Total Cash Distributions",                     "type": "line_item"},
                ]
            },
        ]
    },

    "Waterfall Distribution": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Preferred Returns",
                "type": "subsection",
                "items": [
                    {"type": "empty_row"},
                    {"name": "LP Preferred Returns",                "type": "subsection"},
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "LP Capital Contributions",            "type": "line_item"},
                    {"name": "Preferred Accural",                   "type": "line_item"},
                    {"name": "Return of Capital - LP",              "type": "line_item"},
                    {"name": "LP Distributions",                    "type": "line_item"},
                    {"name": "Undistributed Accrual",               "type": "line_item"},
                    {"name": "Ending Balance",                      "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "GP Preferred Returns",                "type": "subsection"},
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "GP Capital Contributions",            "type": "line_item"},
                    {"name": "Preferred Accural",                   "type": "line_item"},
                    {"name": "Return of Capital - GP",              "type": "line_item"},
                    {"name": "GP Distributions",                    "type": "line_item"},
                    {"name": "Undistributed Accrual",               "type": "line_item"},
                    {"name": "Ending Balance",                      "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Total Distributions",                                 "type": "line_item"},
                    {"name": "Remaining Cash Flow after Preferred Return",          "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "GP Catchup",                          "type": "subsection"},
                    {"name": "GP Catchup",                          "type": "line_item"},
                    {"name": "Total Distributions",                 "type": "line_item"},
                    {"name": "Remaining Cash Flow after Preferred Return & GP Catchup", "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Tier 1 Distributions",                "type": "subsection"},
                    {"type": "empty_row"},
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "LP Capital Contributions",            "type": "line_item"},
                    {"name": "Tier 1 Accural",                      "type": "line_item"},
                    {"name": "Previous LP Distributions",           "type": "line_item"},
                    {"name": "LP Distributions",                    "type": "line_item"},
                    {"name": "Ending Balance",                      "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Remaining Cash Flow after Tier 1 LP distribution",           "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "GP Tier 1 Promote",                   "type": "line_item"},
                    {"name": "GP Tier 1 Catchup",                   "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Remaining Cash Flow after Tier 1 Distribution & Catchup",    "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Tier 2 Distributions",                "type": "subsection"},
                    {"type": "empty_row"},
                    {"name": "Opening Balance",                     "type": "line_item"},
                    {"name": "LP Capital Contributions",            "type": "line_item"},
                    {"name": "Tier 2 Accural",                      "type": "line_item"},
                    {"name": "Previous LP Distributions",           "type": "line_item"},
                    {"name": "LP Distributions",                    "type": "line_item"},
                    {"name": "Ending Balance",                      "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Remaining Cash Flow after Tier 2 LP distribution",           "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "GP Tier 2 Promote",                   "type": "line_item"},
                    {"name": "GP Tier 2 Catchup",                   "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Remaining Cash Flow after Tier 2 Distribution & Catchup",    "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "Tier 3 Distributions",                "type": "subsection"},
                    {"type": "empty_row"},
                    {"name": "LP Tier 3 Distributions",             "type": "line_item"},
                    {"name": "GP Tier 3 Distributions",             "type": "line_item"},
                ]
            },
        ]
    },

    "Clawback Workings": {
        "type": "section",
        "content": [
            {"type": "empty_row"},
            {
                "name": "Clawback",
                "type": "subsection",
                "items": [
                    {"name": "LP's Cash Flows",                     "type": "line_item"},
                    {"name": "Rolling IRR",                         "type": "line_item"},
                    {"name": "Clawback Amount",                     "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "LP Net Cashflows before Clawback",    "type": "line_item"},
                    {"name": "Clawback - LP",                       "type": "line_item"},
                    {"name": "LP Net Cashflows after Clawback",     "type": "line_item"},
                    {"type": "empty_row"},
                    {"name": "GP Net Cashflows before Clawback",    "type": "line_item"},
                    {"name": "Clawback - GP",                       "type": "line_item"},
                    {"name": "GP Net Cashflows after Clawback",     "type": "line_item"},
                ]
            },
        ]
    },
}


# =====================================================================
# FCFF Sentinel Constants
# =====================================================================
# Resolved from the ``fcff_sources`` dict passed at render time, not from
# the vehicle CFF dict.
FCFF_LANDCO       = "__fcff_landco__"
FCFF_DEVCO        = "__fcff_devco__"
FCFF_ASSETCO      = "__fcff_assetco__"
FCFF_TOTAL        = "__fcff_total__"
FCFF_LAND_IN_KIND = "__fcff_land_in_kind__"


# =====================================================================
# Section name aliases (used as key-map prefix)
# =====================================================================
_SEC1 = "Cash Waterfall and Return distribution"
_SEC2 = "Debt 1 Account"
_SEC3 = "Refinancing Debt Account"
_SEC4 = "Equity Scehdule"
_SEC5 = "Waterfall Distribution"
_SEC6 = "Clawback Workings"


# =====================================================================
# CFF Key Map
# =====================================================================
# Lookup order in the renderer (see _render_proforma_section):
#   1. (section_name, "CurrentSubsec / item_name")  — contextual, tried first
#   2. (section_name, item_name)                    — plain fallback
#
# Consequence: only the *non-default* occurrence of an ambiguous label needs
# an explicit disambiguated entry.  The default occurrence falls through to
# the plain entry automatically.
# =====================================================================

PROFORMA_CFF_KEY_MAP: Dict[tuple, Dict[str, Any]] = {

    # =================================================================
    # Section 1 — Cash Waterfall and Return distribution
    # =================================================================

    # ── Entity Level Free Cashflows ──────────────────────────────────
    (_SEC1, "LandCo Free Cashflow"):                            {"source": FCFF_LANDCO},
    (_SEC1, "DevCo Free Cashflow"):                             {"source": FCFF_DEVCO},
    (_SEC1, "AssetCo Free Cashflow"):                           {"source": FCFF_ASSETCO},
    (_SEC1, "Cash Flow before Financing and SPV-related Cost"): {"source": FCFF_TOTAL},

    # ── Fund-related Expenses ────────────────────────────────────────
    (_SEC1, "JV Setup Fees"):                   {"key": "JV Setup Fees"},
    (_SEC1, "Fund Management Fees"):            {"key": "Fund Management Expenses"},
    (_SEC1, "Other Fees"):                      {"key": "Other Fees"},
    (_SEC1, "JV Liquidation Fees"):             {"key": "JV Liquidation Fees"},
    (_SEC1, "Cash Flow before Financing Cost"): {"key": "Total Free Cashflow before Financing"},

    # ── Funding-related Cost ─────────────────────────────────────────
    (_SEC1, "Arrangement Fees"):        {"key": "Arrangement Fees"},
    (_SEC1, "Commitment Fees"):         {"key": "Commitment Fees"},
    (_SEC1, "Interest Cost"):           {"key": "Interest Cost"},
    (_SEC1, "Cash Flow before Financing"): {"key": "Net Funding Requirement"},

    # ── Source of Funding — Loan Raised (default "Debt 1" / "Debt 2") ─
    (_SEC1, "Debt 1"):  {"key": "_tl1_loan_additions"},
    (_SEC1, "Debt 2"):  {"key": "_tl2_loan_additions"},

    # ── Source of Funding — Equity Raised (default "LP" / "GP") ──────
    # LP/GP contributions are stored as negative (cash-out from investor view); negate for display.
    (_SEC1, "LP"):  {"key": "LP Contributions", "negate": True},
    (_SEC1, "GP"):  {"key": "GP Contributions", "negate": True},

    (_SEC1, "Cash Flow before Distributions and Repayments"): {"key": "Net Cash"},

    # ── Distributions and Repayments — Loan Repaid ───────────────────
    # Disambiguated: "Loan Repaid" is the active subsection at this point,
    # so the renderer tries "Loan Repaid / Debt 1" before the plain "Debt 1".
    (_SEC1, "Loan Repaid / Debt 1"): {"key": "TL1 Principal Repaid"},
    (_SEC1, "Loan Repaid / Debt 2"): {"key": "TL2 Principal Repaid"},

    # ── Distributions and Repayments — Return of Capital ─────────────
    (_SEC1, "Return of Capital / LP"): {"key": "Return of Capital - LP", "negate": True},
    (_SEC1, "Return of Capital / GP"): {"key": "Return of Capital - GP", "negate": True},

    # ── Distributions and Repayments — Distributions ─────────────────
    # All distribution values are stored positive (cash out); negate for cash waterfall display.
    (_SEC1, "Preferred Return"):                      {"combine": ["Preferred Returns - LP", "Preferred Returns - GP"], "negate": True},
    (_SEC1, "GP Promote & Catchup (Post Preferred)"): {"key": "Catchup Returns - GP",  "negate": True},
    (_SEC1, "Tier 1 LP Distributions"):               {"key": "Tier 1 Returns - LP",   "negate": True},
    (_SEC1, "Tier 1 GP Promote"):                     {"key": "Tier 1 Promote",        "negate": True},
    (_SEC1, "Tier 1 GP Catchup"):                     {"key": "Tier 1 GP Catchup",     "negate": True},
    (_SEC1, "Tier 2 LP Distributions"):               {"key": "Tier 2 Returns - LP",   "negate": True},
    (_SEC1, "Tier 2 GP Promote"):                     {"key": "Tier 2 Promote",        "negate": True},
    (_SEC1, "Tier 2 GP Catchup"):                     {"key": "Tier 2 GP Catchup",     "negate": True},
    (_SEC1, "Tier 3 LP Distributions"): {"key": "Tier 3 Returns - LP",   "negate": True},
    (_SEC1, "Tier 3 GP Distributions"): {"key": "Tier 3 Promote",        "negate": True},
    (_SEC1, "Compensation in Lieu of Land (GP)"): {"key": "Compensation in Lieu of Land - GP", "negate": True},
    (_SEC1, "Compensation in Lieu of Land (LP)"): {"key": "Compensation in Lieu of Land - LP", "negate": True},
    (_SEC1, "Net Cashflow from Projects"): {"key": "Net Cashflow from Projects"},

    # =================================================================
    # Section 2 — Debt 1 Account
    # =================================================================
    (_SEC2, "Opening Balance"):                  {"key": "_tl1_opening_balance"},
    (_SEC2, "Amount Raised"):                    {"key": "_tl1_loan_additions"},
    (_SEC2, "Arrangement Fees Capitalization"):  {"key": "_tl1_capitalized_arr_fees"},
    (_SEC2, "Commitment Fees Capitalization"):   {"zero": True},
    (_SEC2, "Interest During Constuction (IDC)"): {"key": "_tl1_capitalized_interest"},
    (_SEC2, "Principal Repayment"):              {"compute": {"op": "sub", "a": "_tl1_repayments", "b": "_tl1_balloon_payment"}},
    (_SEC2, "Bullet Payment"):                   {"key": "_tl1_balloon_payment"},
    (_SEC2, "Closing Balance"):                  {"key": "_tl1_closing_balance"},
    (_SEC2, "Interest Expense"):                 {"key": "_tl1_interest_paid"},
    (_SEC2, "Arrangement Fees"):                 {"key": "_tl1_arr_fee_incurred"},
    (_SEC2, "Commitment Fees"):                  {"key": "TL1 Commitment Fees"},

    # =================================================================
    # Section 3 — Refinancing Debt Account
    # =================================================================
    (_SEC3, "Opening Balance"):                  {"key": "_tl2_opening_balance"},
    (_SEC3, "Amount Raised"):                    {"key": "_tl2_loan_additions"},
    (_SEC3, "Arrangement Fees Capitalization"):  {"key": "_tl2_capitalized_arr_fees"},
    (_SEC3, "Commitment Fees Capitalization"):   {"zero": True},
    (_SEC3, "Interest During Constuction (IDC)"): {"key": "_tl2_capitalized_interest"},
    (_SEC3, "Principal Repayment"):              {"compute": {"op": "sub", "a": "_tl2_repayments", "b": "_tl2_balloon_payment"}},
    (_SEC3, "Bullet Payment"):                   {"key": "_tl2_balloon_payment"},
    (_SEC3, "Closing Balance"):                  {"key": "_tl2_closing_balance"},
    (_SEC3, "Interest Expense"):                 {"key": "_tl2_interest_paid"},
    (_SEC3, "Arrangement Fees"):                 {"key": "_tl2_arr_fee_incurred"},
    (_SEC3, "Commitment Fees"):                  {"key": "TL2 Commitment Fees"},

    # =================================================================
    # Section 4 — Equity Schedule
    # =================================================================
    (_SEC4, "Cash Equity Infusion Requirement"): {"key": "Equity Infused"},

    # Cash Equity Commitment
    (_SEC4, "GP Commitment"):           {"key": "_gp_commitment"},
    (_SEC4, "LP Commitment"):           {"key": "_lp_commitment"},
    (_SEC4, "Total Cash Equity"):       {"key": "_equity_funding"},

    # Equity In Kind
    (_SEC4, "Land In Kind (GP)"):       {"key": "_gp_lik_commit"},
    (_SEC4, "Land In Kind (LP)"):       {"key": "_lp_lik_commit"},
    (_SEC4, "Total In Kind Equity"):    {"key": "_lik_commitment"},

    # Total Equity Commitment
    (_SEC4, "GP Equity"):               {"key": "_total_gp_commit"},
    (_SEC4, "LP Others Equity"):        {"key": "_total_lp_commit"},
    (_SEC4, "Total Equity Commitment"): {"key": "_total_equity_funding"},

    # Distribution Summary
    (_SEC4, "Return of Capital"):       {"combine": ["Return of Capital - LP", "Return of Capital - GP"]},
    (_SEC4, "Preferred Return"):                      {"combine": ["Preferred Returns - LP", "Preferred Returns - GP"]},
    (_SEC4, "GP Promote & Catchup (Post Preferred)"): {"key": "Catchup Returns - GP"},
    (_SEC4, "Tier 1 LP Distributions"):               {"key": "Tier 1 Returns - LP"},
    (_SEC4, "Tier 1 GP Promote"):                     {"key": "Tier 1 Promote"},
    (_SEC4, "Tier 1 GP Catchup"):                     {"key": "Tier 1 GP Catchup"},
    (_SEC4, "Tier 2 LP Distributions"):               {"key": "Tier 2 Returns - LP"},
    (_SEC4, "Tier 2 GP Promote"):                     {"key": "Tier 2 Promote"},
    (_SEC4, "Tier 2 GP Catchup"):                     {"key": "Tier 2 GP Catchup"},
    (_SEC4, "Tier 3 LP Distributions"): {"key": "Tier 3 Returns - LP"},
    (_SEC4, "Tier 3 GP Distributions"): {"key": "Tier 3 Promote"},
    (_SEC4, "Compensation in Lieu of Land (GP)"): {"key": "Compensation in Lieu of Land - GP"},
    (_SEC4, "Compensation in Lieu of Land (LP)"): {"key": "Compensation in Lieu of Land - LP"},
    (_SEC4, "Total Cash Distributions"):{"key": "Total Distributions"},

    # =================================================================
    # Section 5 — Waterfall Distribution
    # =================================================================
    # Non-ambiguous items (appear once; plain key suffices)
    (_SEC5, "LP Capital Contributions"):    {"key": "_lp_contributions_incl", "negate": True},
    (_SEC5, "GP Capital Contributions"):    {"key": "_gp_contributions_incl", "negate": True},
    (_SEC5, "Remaining Cash Flow after Preferred Return"):          {"key": "_wf_cash_pre_catchup"},
    (_SEC5, "GP Catchup"):                  {"key": "Catchup Returns - GP"},
    (_SEC5, "Remaining Cash Flow after Preferred Return & GP Catchup"): {"key": "_wf_cash_post_catchup"},
    (_SEC5, "Tier 1 Accural"):              {"key": "_wf_t1_accrual"},
    (_SEC5, "Remaining Cash Flow after Tier 1 LP distribution"):    {"key": "_wf_cash_post_t1_lp"},
    (_SEC5, "GP Tier 1 Promote"):           {"key": "Tier 1 Promote"},
    (_SEC5, "GP Tier 1 Catchup"):           {"key": "Tier 1 GP Catchup"},
    (_SEC5, "Remaining Cash Flow after Tier 1 Distribution & Catchup"): {"key": "_wf_cash_post_t1_gp"},
    (_SEC5, "Tier 2 Accural"):              {"key": "_wf_t2_accrual"},
    (_SEC5, "Remaining Cash Flow after Tier 2 LP distribution"):    {"key": "_wf_cash_post_t2_lp"},
    (_SEC5, "GP Tier 2 Promote"):           {"key": "Tier 2 Promote"},
    (_SEC5, "GP Tier 2 Catchup"):           {"key": "Tier 2 GP Catchup"},
    (_SEC5, "Remaining Cash Flow after Tier 2 Distribution & Catchup"): {"key": "_wf_cash_post_t2_gp"},
    (_SEC5, "LP Tier 3 Distributions"):     {"key": "Tier 3 Returns - LP"},
    (_SEC5, "GP Tier 3 Distributions"):     {"key": "Tier 3 Promote"},

    # Ambiguous: "Opening Balance" — disambiguated by active subsection header
    (_SEC5, "LP Preferred Returns / Opening Balance"):  {"key": "_wf_pref_begin_lp"},
    (_SEC5, "GP Preferred Returns / Opening Balance"):  {"key": "_wf_pref_begin_gp"},
    (_SEC5, "Tier 1 Distributions / Opening Balance"):  {"key": "_wf_t1_begin"},
    (_SEC5, "Tier 2 Distributions / Opening Balance"):  {"key": "_wf_t2_begin"},

    # Ambiguous: "Undistributed Accrual" — LP vs GP preferred return subsections
    (_SEC5, "LP Preferred Returns / Undistributed Accrual"): {"key": "_undist_accrual_lp"},
    (_SEC5, "GP Preferred Returns / Undistributed Accrual"): {"key": "_undist_accrual_gp"},

    # Ambiguous: "Ending Balance" — disambiguated by active subsection header
    (_SEC5, "LP Preferred Returns / Ending Balance"):   {"key": "_pref_closing_lp"},
    (_SEC5, "GP Preferred Returns / Ending Balance"):   {"key": "_pref_closing_gp"},
    (_SEC5, "Tier 1 Distributions / Ending Balance"):   {"key": "_wf_t1_end"},
    (_SEC5, "Tier 2 Distributions / Ending Balance"):   {"key": "_wf_t2_end"},

    # Ambiguous: "Preferred Accural" — LP vs GP subsection
    (_SEC5, "LP Preferred Returns / Preferred Accural"): {"key": "_pref_accrual_lp"},
    (_SEC5, "GP Preferred Returns / Preferred Accural"): {"key": "_pref_accrual_gp"},

    # Ambiguous: "Return of Capital" — LP vs GP preferred return subsections
    (_SEC5, "LP Preferred Returns / Return of Capital - LP"): {"key": "Return of Capital - LP", "negate": True},
    (_SEC5, "GP Preferred Returns / Return of Capital - GP"): {"key": "Return of Capital - GP", "negate": True},

    # Ambiguous: "LP Capital Contributions" — Pref, Tier 1, Tier 2 all show LP equity drawn per period
    (_SEC5, "Tier 1 Distributions / LP Capital Contributions"): {"key": "_lp_contributions_incl", "negate": True},
    (_SEC5, "Tier 2 Distributions / LP Capital Contributions"): {"key": "_lp_contributions_incl", "negate": True},

    # Ambiguous: "Previous LP Distributions" — Tier 1 and Tier 2
    (_SEC5, "Tier 1 Distributions / Previous LP Distributions"): {"key": "Tier 1 Previous LP Distributions"},
    (_SEC5, "Tier 2 Distributions / Previous LP Distributions"): {"key": "Tier 2 Previous LP Distributions"},

    # Ambiguous: "LP Distributions" — LP Pref, Tier 1, Tier 2
    # Uses pure preferred only (ROC shown separately above as its own line)
    (_SEC5, "LP Preferred Returns / LP Distributions"): {"key": "Preferred Returns - LP", "negate": True},
    (_SEC5, "Tier 1 Distributions / LP Distributions"): {"key": "Tier 1 Returns - LP", "negate": True},
    (_SEC5, "Tier 2 Distributions / LP Distributions"): {"key": "Tier 2 Returns - LP", "negate": True},

    # Ambiguous: "GP Distributions" — GP Pref subsection
    # Uses pure preferred only (ROC shown separately above as its own line)
    (_SEC5, "GP Preferred Returns / GP Distributions"): {"key": "Preferred Returns - GP", "negate": True},

    # Ambiguous: "Total Distributions" — GP Promote vs GP Catchup
    (_SEC5, "GP Promote / Total Distributions"):  {"key": "_wf_total_dist_pref"},
    (_SEC5, "GP Catchup / Total Distributions"):  {"key": "_wf_total_dist_catchup"},

    # =================================================================
    # Section 6 — Clawback Workings
    # =================================================================
    (_SEC6, "LP's Cash Flows"):                  {"key": "_lp_cf_pre_clawback"},
    (_SEC6, "Rolling IRR"):                      {"key": "_clawback_rolling_irr"},
    (_SEC6, "Clawback Amount"):                  {"key": "_clawback_amount"},
    (_SEC6, "LP Net Cashflows before Clawback"): {"key": "_lp_cf_pre_clawback"},
    (_SEC6, "Clawback - LP"):                    {"key": "_clawback_amount"},
    (_SEC6, "LP Net Cashflows after Clawback"):  {"combine": ["_lp_cf_pre_clawback", "Clawback Additions - LP"]},
    (_SEC6, "GP Net Cashflows before Clawback"): {"key": "_gp_cf_pre_clawback"},
    (_SEC6, "Clawback - GP"):                    {"key": "_clawback_amount", "negate": True},
    (_SEC6, "GP Net Cashflows after Clawback"):  {"combine": ["_gp_cf_pre_clawback", "Clawback Deductions - GP"]},
}


# =====================================================================
# Balance row label registry
# Used by the renderer to pass correct labels to _fix_balance_yearly()
# so yearly values use last-month-of-year instead of sum.
# =====================================================================
BALANCE_ROW_NAMES: List[str] = [
    "Opening Balance",
    "Closing Balance",
    "Ending Balance",
]
