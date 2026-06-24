"""Hierarchy mapping for financial statement trace rows.

This module stores category dictionaries and provides a single helper that
adds L1/L2/L3 columns to a trace dataframe.
"""

import re
from typing import Any, Dict, Tuple

import pandas as pd


_MAIN_CATEGORY_BY_SECTION = {
    "Cashflow from Operations": {
        "land sales": "Land Sales",
        "asset sales": "Asset Sales",
        "land lease income": "Land Lease Income",
        "lease revenue": "Lease Revenue",
        "hospitality ebitda": "Hospitality EBITDA",
        "parking revenue": "Parking Revenue",
        "other operating income": "Other Operating Income",
        "operating expenses": "Operating Expenses",
        "other expenses": "Other Expenses",
        "community operations": "Community Operations",
        "sales and marketing costs": "Sales and Marketing Costs",
        "corporate overheads": "Corporate Overheads",
        "share of profit from jv": "Share of Profit from JV",
        "less: interparty cash collection": "Less: Interparty Cash Collection",
    },
    "Cashflow from Investments": {
        "acquisition cost": "Acquisition Cost",
        "acquisition transaction costs": "Acquisition Transaction Costs",
        "infrastructure capex": "Infrastructure Capex",
        "development capex": "Development Capex",
        "soft costs": "Soft Costs",
        "contingency cost": "Contingency Cost",
        "maintenance capex": "Maintenance Capex",
        "tenant improvements": "Tenant Improvements",
        "capitalized corporate costs": "Capitalized Corporate Costs",
        "asset sale proceeds": "Asset Sale Proceeds",
        "investment in jv": "Investment in JV",
        "dividends received from jv": "Dividends Received from JV",
        "add: interparty cash payment": "Add: Interparty Cash Payment",
    },
    "Cashflow from Financing": {
        "debt drawdown": "Debt Drawdown",
        "debt repayment": "Debt Repayment",
        "interest payments": "Interest Payments",
        "debt fees": "Debt Fees",
        "equity contributions": "Equity Contributions",
        "land in kind contribution": "Land in Kind Contribution",
    },
    "Income Statement": {
        "core operating revenue": "Core Operating Revenue",
        "cost of sales": "COST OF SALES",
        "operating costs": "Operating Costs",
        "administrative and corporate overheads": "Administrative & Corporate Overheads",
        "sales marketing leasing": "Sales, Marketing & Leasing",
        "personnel costs": "Personnel Costs",
        "asset community management": "Asset & Community Management",
        "hospitality departmental expenses": "Hospitality - Departmental Expenses",
        "hospitality undistributed expenses": "Hospitality - Undistributed Expenses",
        "other operating expenses": "Other Operating Expenses",
        "depreciation amortization": "DEPRECIATION & AMORTIZATION",
        "finance costs": "FINANCE COSTS",
        "non operating income expenses": "NON-OPERATING INCOME / EXPENSES",
    },
    "Balance Sheet": {
        "assets": "ASSETS",
        "liabilities": "LIABILITIES",
        "equity": "EQUITY",
    },
}


_LINE_ITEM_TO_MAIN_BY_SECTION = {
    "Cashflow from Operations": {
        "on plan sales collection": "Land Sales",
        "off plan sales collection": "Land Sales",
        "escrow setup fees": "Land Sales",
        "asset sales through escrow": "Asset Sales",
        "asset sales through collection post dev": "Asset Sales",
        "forward funding": "Asset Sales",
        "forward sales": "Asset Sales",
        "lease collection": "Land Lease Income",
        "base rent": "Lease Revenue",
        "turnover rent": "Lease Revenue",
        "service charge": "Lease Revenue",
        "leasing commissions": "Lease Revenue",
        "other income 1": "Other Operating Income",
        "other income 2": "Other Operating Income",
        "other income 3": "Other Operating Income",
        "government subsidies": "Other Operating Income",
        "pa recovery": "Other Operating Income",
        "land lease operating expenses": "Operating Expenses",
        "dlp insurance": "Operating Expenses",
        "pre operating expenses": "Operating Expenses",
        "utilities": "Operating Expenses",
        "facility management fees": "Operating Expenses",
        "administration cost": "Operating Expenses",
        "insurance": "Operating Expenses",
        "other operating expenses": "Operating Expenses",
        "bad debt": "Operating Expenses",
        "void period opex": "Operating Expenses",
        "sinking fund": "Operating Expenses",
        "parking expenses": "Operating Expenses",
        "other expense 1": "Other Expenses",
        "other expense 2": "Other Expenses",
        "other expense 3": "Other Expenses",
        "community operations expense amanah": "Community Operations",
        "community operations recovery amanah": "Community Operations",
        "community operations expense roshn": "Community Operations",
        "community operations recovery roshn": "Community Operations",
        "land leasing costs": "Sales and Marketing Costs",
        "sales transaction cost": "Sales and Marketing Costs",
        "sales cost": "Sales and Marketing Costs",
        "marketing cost": "Sales and Marketing Costs",
        "salaries expenses": "Corporate Overheads",
        "it services expenses": "Corporate Overheads",
        "office rent and utilities expenses": "Corporate Overheads",
        "professional services expenses": "Corporate Overheads",
        "marketing expenses": "Corporate Overheads",
        "sales cost expenses": "Corporate Overheads",
        "additional expenses": "Corporate Overheads",
    },
    "Cashflow from Investments": {
        "raw land acquisition cost": "Acquisition Cost",
        "serviced land acquisition cost": "Acquisition Cost",
        "asset acquisition cost": "Acquisition Cost",
        "legal cost": "Acquisition Transaction Costs",
        "agency cost": "Acquisition Transaction Costs",
        "technical cost": "Acquisition Transaction Costs",
        "valuation cost": "Acquisition Transaction Costs",
        "due diligence cost": "Acquisition Transaction Costs",
        "real estate transaction tax": "Acquisition Transaction Costs",
        "municipal fees": "Acquisition Transaction Costs",
        "transfer tax stamp duty": "Acquisition Transaction Costs",
        "brokerage": "Acquisition Transaction Costs",
        "primary infrastructure cost": "Infrastructure Capex",
        "secondary infrastructure cost": "Infrastructure Capex",
        "vertical construction cost": "Development Capex",
        "public amenity cost": "Development Capex",
        "cec cost": "Development Capex",
        "canal cost": "Development Capex",
        "design cost": "Soft Costs",
        "permitting cost": "Soft Costs",
        "supervision cost": "Soft Costs",
        "project management cost": "Soft Costs",
        "contingency cost payment": "Contingency Cost",
        "maintenance capex 1": "Maintenance Capex",
        "maintenance capex 2": "Maintenance Capex",
        "maintenance capex 3": "Maintenance Capex",
        "maintenance capex 4": "Maintenance Capex",
        "tenant fitout allowance": "Tenant Improvements",
        "capitalized salaries expenses": "Capitalized Corporate Costs",
        "capitalized it services expenses": "Capitalized Corporate Costs",
        "capitalized office rent and utilities expenses": "Capitalized Corporate Costs",
        "capitalized professional services expenses": "Capitalized Corporate Costs",
        "capitalized marketing expenses": "Capitalized Corporate Costs",
        "capitalized sales cost expenses": "Capitalized Corporate Costs",
        "capitalized additional expenses": "Capitalized Corporate Costs",
        "asset sale value": "Asset Sale Proceeds",
        "land bank exit value": "Asset Sale Proceeds",
        "land lease terminal value": "Asset Sale Proceeds",
    },
    "Cashflow from Financing": {
        "term loan debt drawdown": "Debt Drawdown",
        "revolver debt drawdown": "Debt Drawdown",
        "other debt drawdown": "Debt Drawdown",
        "term loan debt repayment": "Debt Repayment",
        "revolver debt repayment": "Debt Repayment",
        "other debt repayment": "Debt Repayment",
        "term loan interest payments": "Interest Payments",
        "revolver interest payments": "Interest Payments",
        "other interest payments": "Interest Payments",
        "term loan debt fees": "Debt Fees",
        "revolver debt fees": "Debt Fees",
        "other debt fees": "Debt Fees",
        "project and asset equity contribution": "Equity Contributions",
    },
    "Balance Sheet": {
        "cash and cash equivalents": "ASSETS",
        "accounts receivable": "ASSETS",
        "less: interparty ar ap netting (assets)": "ASSETS",
        "advances for land": "ASSETS",
        "less: interparty advances ur netting (assets)": "ASSETS",
        "advance to contractor": "ASSETS",
        "escrow restricted cash": "ASSETS",
        "restricted cash sinking fund": "ASSETS",
        "cwip serviced land": "ASSETS",
        "cwip developed units": "ASSETS",
        "serviced land assets": "ASSETS",
        "cwip": "ASSETS",
        "land assets": "ASSETS",
        "investment property": "ASSETS",
        "less: unrealized gains (assets)": "ASSETS",
        "accumulated depreciation": "ASSETS",
        "investments in associates": "ASSETS",
        "accounts payable": "LIABILITIES",
        "less: interparty ar ap netting (liabilities)": "LIABILITIES",
        "unearned revenue": "LIABILITIES",
        "less: interparty advances ur netting (liabilities)": "LIABILITIES",
        "debt revolver": "LIABILITIES",
        "debt term loan": "LIABILITIES",
        "debt other": "LIABILITIES",
        "shareholders equity": "EQUITY",
        "share capital": "EQUITY",
        "retained earnings": "EQUITY",
        "less: unrealized gains (equity)": "EQUITY",
        "less: interparty retained earnings": "EQUITY",
    },
    "Income Statement": {
        "Land Sales Revenue": "Core Operating Revenue",
        "Asset Sales Revenue": "Core Operating Revenue",
        "Land Lease Revenue": "Core Operating Revenue",
        "Lease Revenue - Base Rent": "Core Operating Revenue",
        "Lease Revenue - Turnover Rent": "Core Operating Revenue",
        "Lease Revenue - Service Charge": "Core Operating Revenue",
        "Hospitality - Room Revenue": "Core Operating Revenue",
        "Hospitality - F&B Revenue": "Core Operating Revenue",
        "Hospitality - OOD Revenue": "Core Operating Revenue",
        "Hospitality - Other Operating Income": "Core Operating Revenue",
        "Less: Interparty Sales Revenue": "Core Operating Revenue",
        "Cost of Land Sales": "COST OF SALES",
        "Cost of Asset Sales": "COST OF SALES",
        "Cost of Lease Revenue": "COST OF SALES",
        "Add: Interparty Cost of Sales": "COST OF SALES",
        "Land Lease Operating Expenses": "Operating Costs",
        "Utilities Expense": "Operating Costs",
        "Facility Management Expense": "Operating Costs",
        "Sinking Fund Expense": "Operating Costs",
        "Maintenance Capex Expense": "Operating Costs",
        "Void Period Expense": "Operating Costs",
        "Parking Expense": "Operating Costs",
        "Administration Expense": "Administrative & Corporate Overheads",
        "Office Rent and Utilities Expense": "Administrative & Corporate Overheads",
        "IT Services Expense": "Administrative & Corporate Overheads",
        "Professional Services Expense": "Administrative & Corporate Overheads",
        "Insurance Expense": "Administrative & Corporate Overheads",
        "DLP Insurance Expense": "Administrative & Corporate Overheads",
        "Sales and Marketing Expense": "Sales, Marketing & Leasing",
        "Marketing Overhead Expense": "Sales, Marketing & Leasing",
        "Sales Cost Overhead Expense": "Sales, Marketing & Leasing",
        "Leasing Commissions Expense": "Sales, Marketing & Leasing",
        "Salaries Expense": "Personnel Costs",
        "Asset Management Expense": "Operating Costs",
        "Community Management Expense": "Asset & Community Management",
        "Community Operations Expense": "Asset & Community Management",
        "Hospitality Departmental Expenses - Room": "Hospitality - Departmental Expenses",
        "Hospitality Departmental Expenses - F&B": "Hospitality - Departmental Expenses",
        "Hospitality Departmental Expenses - OOD": "Hospitality - Departmental Expenses",
        "Hospitality Departmental Expenses - Other": "Hospitality - Departmental Expenses",
        "Hospitality Undistributed Expenses - Admin": "Hospitality - Undistributed Expenses",
        "Hospitality Undistributed Expenses - Sales & Marketing": "Hospitality - Undistributed Expenses",
        "Hospitality Undistributed Expenses - IT": "Hospitality - Undistributed Expenses",
        "Hospitality Undistributed Expenses - Utilities": "Hospitality - Undistributed Expenses",
        "Pre Operating Expenses": "Other Operating Expenses",
        "Bad Debt Expense": "Other Operating Expenses",
        "Additional Overhead Expense": "Other Operating Expenses",
        "Depreciation Expense": "DEPRECIATION & AMORTIZATION",
        "Interest Expense - Term Loan": "FINANCE COSTS",
        "Interest Expense - Revolver": "FINANCE COSTS",
        "Interest Expense - Other": "FINANCE COSTS",
        "Debt Fees Expense": "FINANCE COSTS",
        "Other Operating Expense": "NON-OPERATING INCOME / EXPENSES",
        "Loss on Asset Disposal": "NON-OPERATING INCOME / EXPENSES",
        "Hospitality Non-Operating Expenses": "NON-OPERATING INCOME / EXPENSES",
        "Parking Revenue": "NON-OPERATING INCOME / EXPENSES",
        "Community Operations Recovery": "Asset & Community Management",
        "Government Subsidies Income": "NON-OPERATING INCOME / EXPENSES",
        "PA Recovery Income": "NON-OPERATING INCOME / EXPENSES",
        "Other Operating Income": "NON-OPERATING INCOME / EXPENSES",
        "Gain on Asset Disposal": "NON-OPERATING INCOME / EXPENSES",
        "Hospitality Non-Operating Income": "NON-OPERATING INCOME / EXPENSES",
        "Share of Profit from JV": "NON-OPERATING INCOME / EXPENSES",
    },
}


_LINE_ITEM_POSITION_RULES = {
    "less: interparty cash collection": {
        "Cashflow Section": "Cashflow from Operations",
        "Main Category": "Less: Interparty Cash Collection",
    },
    "add: interparty cash payment": {
        "Cashflow Section": "Cashflow from Investments",
        "Main Category": "Add: Interparty Cash Payment",
    },
    "dividends received from jv": {
        "Cashflow Section": "Cashflow from Investments",
        "Main Category": "Investment in JV",
    },
    "land in kind contribution": {
        "Cashflow Section": "Cashflow from Financing",
        "Main Category": "Equity Contributions",
    },
    "less: interparty ar/ap netting (assets)": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "ASSETS",
    },
    "less: interparty ar/ap netting (liabilities)": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "LIABILITIES",
    },
    "less: interparty advances/ur netting (assets)": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "ASSETS",
    },
    "less: interparty advances/ur netting (liabilities)": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "LIABILITIES",
    },
    "less: interparty retained earnings": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "EQUITY",
    },
}


_SECTION_CANDIDATES_BY_FS = {
    "cashflow statement": [
        "Cashflow from Operations",
        "Cashflow from Investments",
        "Cashflow from Financing",
    ],
    "income statement": ["Income Statement"],
    "balance sheet": ["Balance Sheet"],
    "cashflow from operations": ["Cashflow from Operations"],
    "cashflow from investments": ["Cashflow from Investments"],
    "cashflow from financing": ["Cashflow from Financing"],
}


_LINE_ITEM_L3_OVERRIDES = {
    "cwip serviced land": "CWIP",
    "cwip developed units": "CWIP",
    "serviced land assets": "CWIP",
}

# Flat sign-multiplier lookup keyed by NORMALIZED line item name.
# Normalization: lowercase → "&"→"and" → strip non-[a-z0-9] → collapse spaces.
# +1 = inflow / revenue / gain   |   -1 = outflow / expense / cost / deduction
# Used in fn_add_trace_hierarchy_levels for a fully vectorised Value sign fix.
_LINE_ITEM_SIGN: Dict[str, int] = {
    # ── CASHFLOW FROM OPERATIONS ──────────────────────────────────────────
    # Land Sales
    "on plan sales collection":                          1,
    "off plan sales collection":                         1,
    "escrow setup fees":                                 1,
    # Asset Sales
    "asset sales through escrow":                        1,
    "asset sales through collection post dev":           1,
    "forward funding":                                   1,
    "forward sales":                                     1,
    # Land Lease Income
    "lease collection":                                  1,
    # Lease Revenue
    "base rent":                                         1,
    "turnover rent":                                     1,
    "service charge":                                    1,
    "leasing commissions":                               1,
    # Other Operating Income
    "other income 1":                                    1,
    "other income 2":                                    1,
    "other income 3":                                    1,
    "government subsidies":                              1,
    "pa recovery":                                       1,
    # Operating Expenses
    "land lease operating expenses":                    1,
    "dlp insurance":                                    1,
    "pre operating expenses":                           1,
    "utilities":                                        1,
    "facility management fees":                         1,
    "administration cost":                              1,
    "insurance":                                        1,
    "other operating expenses":                         1,
    "bad debt":                                         1,
    "void period opex":                                 1,
    "sinking fund":                                     1,
    "parking expenses":                                 1,
    # Other Expenses
    "other expense 1":                                  1,
    "other expense 2":                                  1,
    "other expense 3":                                  1,
    # Community Operations (expenses out, recoveries in)
    "community operations expense amanah":              1,
    "community operations recovery amanah":             1,
    "community operations expense roshn":               1,
    "community operations recovery roshn":              1,
    # Sales and Marketing Costs
    "land leasing costs":                               1,
    "sales transaction cost":                           1,
    "sales cost":                                       1,
    "marketing cost":                                   1,
    # Corporate Overheads
    "salaries expenses":                                1,
    "it services expenses":                             1,
    "office rent and utilities expenses":               1,
    "professional services expenses":                   1,
    "marketing expenses":                               1,
    "sales cost expenses":                              1,
    "additional expenses":                              1,
    # ── CASHFLOW FROM INVESTMENTS ─────────────────────────────────────────
    # Acquisition Cost
    "raw land acquisition cost":                        1,
    "serviced land acquisition cost":                   1,
    "asset acquisition cost":                           1,
    # Acquisition Transaction Costs
    "legal cost":                                       1,
    "agency cost":                                      1,
    "technical cost":                                   1,
    "valuation cost":                                   1,
    "due diligence cost":                               1,
    "real estate transaction tax":                      1,
    "municipal fees":                                   1,
    "transfer tax stamp duty":                          1,
    "brokerage":                                        1,
    # Infrastructure Capex
    "primary infrastructure cost":                      1,
    "secondary infrastructure cost":                    1,
    # Development Capex
    "vertical construction cost":                       1,
    "public amenity cost":                              1,
    "cec cost":                                         1,
    "canal cost":                                       1,
    # Soft Costs
    "design cost":                                      1,
    "permitting cost":                                  1,
    "supervision cost":                                 1,
    "project management cost":                          1,
    # Contingency Cost
    "contingency cost payment":                         1,
    # Maintenance Capex
    "maintenance capex 1":                              1,
    "maintenance capex 2":                              1,
    "maintenance capex 3":                              1,
    "maintenance capex 4":                              1,
    # Tenant Improvements
    "tenant fitout allowance":                          1,
    # Capitalized Corporate Costs
    "capitalized salaries expenses":                    1,
    "capitalized it services expenses":                 1,
    "capitalized office rent and utilities expenses":   1,
    "capitalized professional services expenses":       1,
    "capitalized marketing expenses":                   1,
    "capitalized sales cost expenses":                  1,
    "capitalized additional expenses":                  1,
    # Asset Sale Proceeds
    "asset sale value":                                  1,
    "land bank exit value":                              1,
    "land lease terminal value":                         1,
    # ── CASHFLOW FROM FINANCING ───────────────────────────────────────────
    "term loan debt drawdown":                           1,
    "revolver debt drawdown":                            1,
    "other debt drawdown":                               1,
    "term loan debt repayment":                         1,
    "revolver debt repayment":                          1,
    "other debt repayment":                             1,
    "term loan interest payments":                      1,
    "revolver interest payments":                       1,
    "other interest payments":                          1,
    "term loan debt fees":                              1,
    "revolver debt fees":                               1,
    "other debt fees":                                  1,
    "project and asset equity contribution":             1,
    # ── INCOME STATEMENT ──────────────────────────────────────────────────
    # Core Operating Revenue  (IS keys are title-case; normalized → lowercase)
    "land sales revenue":                                1,
    "asset sales revenue":                               1,
    "land lease revenue":                                1,
    "lease revenue base rent":                           1,   # "Lease Revenue - Base Rent"
    "lease revenue turnover rent":                       1,
    "lease revenue service charge":                      1,
    "hospitality room revenue":                          1,   # "Hospitality - Room Revenue"
    "hospitality f and b revenue":                       1,   # "Hospitality - F&B Revenue"
    "hospitality ood revenue":                           1,
    "hospitality other operating income":                1,
    "less interparty sales revenue":                    1,   # deduction from revenue
    # COST OF SALES
    "cost of land sales":                               -1,
    "cost of asset sales":                              -1,
    "cost of lease revenue":                            -1,
    "add interparty cost of sales":                      1,   # elimination reduces cost
    # Operating Costs
    "utilities expense":                                -1,
    "facility management expense":                      -1,
    "sinking fund expense":                             -1,
    "maintenance capex expense":                        -1,
    "void period expense":                              -1,
    "parking expense":                                  -1,
    "asset management expense":                         -1,
    # Administrative & Corporate Overheads
    "administration expense":                           -1,
    "office rent and utilities expense":                -1,
    "it services expense":                              -1,
    "professional services expense":                    -1,
    "insurance expense":                                -1,
    "dlp insurance expense":                            -1,
    # Sales, Marketing & Leasing
    "sales and marketing expense":                      -1,
    "marketing overhead expense":                       -1,
    "sales cost overhead expense":                      -1,
    "leasing commissions expense":                      -1,
    # Personnel Costs
    "salaries expense":                                 -1,
    # Asset & Community Management
    "community management expense":                     -1,
    "community operations expense":                     -1,
    "community operations recovery":                     1,
    # Hospitality - Departmental Expenses  ("F&B" → "f and b")
    "hospitality departmental expenses room":           -1,
    "hospitality departmental expenses f and b":        -1,
    "hospitality departmental expenses ood":            -1,
    "hospitality departmental expenses other":          -1,
    # Hospitality - Undistributed Expenses
    "hospitality undistributed expenses admin":         -1,
    "hospitality undistributed expenses sales and marketing": -1,
    "hospitality undistributed expenses it":            -1,
    "hospitality undistributed expenses utilities":     -1,
    # Other Operating Expenses
    "bad debt expense":                                 -1,
    "additional overhead expense":                      -1,
    # DEPRECIATION & AMORTIZATION
    "depreciation expense":                             -1,
    # FINANCE COSTS
    "interest expense term loan":                       -1,
    "interest expense revolver":                        -1,
    "interest expense other":                           -1,
    "debt fees expense":                                -1,
    # NON-OPERATING INCOME / EXPENSES (mixed — sign per item)
    "other operating expense":                          -1,
    "loss on asset disposal":                           -1,
    "hospitality non operating expenses":               -1,
    "parking revenue":                                   1,
    "government subsidies income":                       1,
    "pa recovery income":                                1,
    "other operating income":                            1,
    "gain on asset disposal":                            1,
    "hospitality non operating income":                  1,
    "share of profit from jv":                           1,
    # ── BALANCE SHEET ─────────────────────────────────────────────────────
    "cash and cash equivalents":                         1,
    "accounts receivable":                               1,
    "less interparty ar ap netting (assets)":           -1,
    "less interparty ar ap netting (liabilities)":      -1,
    "advances for land":                                 1,
    "less interparty advances ur netting (assets)":     -1,
    "less interparty advances ur netting (liabilities)":-1,
    "advance to contractor":                             1,
    "escrow restricted cash":                            1,
    "restricted cash sinking fund":                      1,
    "cwip serviced land":                                1,
    "cwip developed units":                              1,
    "serviced land assets":                              1,
    "cwip":                                              1,
    "land assets":                                       1,
    "investment property":                               1,
    "less unrealized gains (assets)":                   -1,
    "less unrealized gains (equity)":                   -1,
    "accumulated depreciation":                         -1,
    "investments in associates":                         1,
    "accounts payable":                                  1,
    "unearned revenue":                                  1,
    "debt revolver":                                     1,
    "debt term loan":                                    1,
    "debt other":                                        1,
    "shareholders equity":                               1,
    "share capital":                                     1,
    "retained earnings":                                 1,
    "less interparty retained earnings":                -1,
}


def _normalize_position_key(text: Any) -> str:
    if text is None:
        return ""
    value = str(text).strip().lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_nested_mapping(
    mapping: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    normalized: Dict[str, Dict[str, str]] = {}
    for section, values in mapping.items():
        section_key = _normalize_position_key(section)
        normalized[section_key] = {
            _normalize_position_key(k): str(v) for k, v in values.items()
        }
    return normalized


_MAIN_CATEGORY_BY_SECTION_NORM = _normalize_nested_mapping(_MAIN_CATEGORY_BY_SECTION)
_LINE_ITEM_TO_MAIN_BY_SECTION_NORM = _normalize_nested_mapping(_LINE_ITEM_TO_MAIN_BY_SECTION)
_LINE_ITEM_POSITION_RULES_NORM = {
    _normalize_position_key(k): {
        "Cashflow Section": str(v.get("Cashflow Section", "")),
        "Main Category": str(v.get("Main Category", "")),
    }
    for k, v in _LINE_ITEM_POSITION_RULES.items()
}


_BS_SECTION_SUFFIX_RE = re.compile(r'\s*\((Assets|Liabilities|Equity)\)\s*$', re.IGNORECASE)


def _resolve_trace_hierarchy(financial_statement: Any, line_item_name: Any) -> Tuple[str, str, str]:
    line_item = "" if line_item_name is None else str(line_item_name).strip()
    line_key = _normalize_position_key(line_item)
    fs_label = "" if financial_statement is None else str(financial_statement).strip()
    fs_key = _normalize_position_key(fs_label)
    # Strip section qualifier suffix so "Line Item" column shows the base name
    line_item_display = _BS_SECTION_SUFFIX_RE.sub('', line_item).strip()
    l3_value = _LINE_ITEM_L3_OVERRIDES.get(line_key, line_item_display)

    if not line_item:
        return fs_label, "", ""

    rule = _LINE_ITEM_POSITION_RULES_NORM.get(line_key)
    if rule:
        l1 = str(rule.get("Cashflow Section") or fs_label)
        l2 = str(rule.get("Main Category") or "")
        return l1, l2, l3_value

    section_candidates = _SECTION_CANDIDATES_BY_FS.get(fs_key, [fs_label])

    for section in section_candidates:
        section_key = _normalize_position_key(section)
        mapped = _LINE_ITEM_TO_MAIN_BY_SECTION_NORM.get(section_key, {}).get(line_key)
        if mapped:
            return section, mapped, l3_value

    for section in section_candidates:
        section_key = _normalize_position_key(section)
        mapped = _MAIN_CATEGORY_BY_SECTION_NORM.get(section_key, {}).get(line_key)
        if mapped:
            return section, mapped, l3_value

    fallback_l1 = fs_label if fs_label else ""
    return fallback_l1, "", l3_value


def fn_add_trace_hierarchy_levels(trace_df: pd.DataFrame) -> pd.DataFrame:
    """Add Cashflow Section / Main Category / Line Item columns to the trace dataframe using mapping rules."""
    if not isinstance(trace_df, pd.DataFrame):
        return pd.DataFrame()

    df = trace_df.copy()

    if df.empty:
        for col in ("Cashflow Section", "Main Category", "Line Item"):
            if col not in df.columns:
                df[col] = ""
        return df

    if "Financial Statement" not in df.columns or "Line Item Name" not in df.columns:
        for col in ("Cashflow Section", "Main Category", "Line Item"):
            if col not in df.columns:
                df[col] = ""
        return df

    l1_values = []
    l2_values = []
    l3_values = []

    for fs_value, li_value in zip(df["Financial Statement"].tolist(), df["Line Item Name"].tolist()):
        l1, l2, l3 = _resolve_trace_hierarchy(fs_value, li_value)
        l1_values.append(l1)
        l2_values.append(l2)
        l3_values.append(l3)

    df["Cashflow Section"] = l1_values
    df["Main Category"] = l2_values
    df["Line Item"] = l3_values

    # ------------------------------------------------------------------
    # Apply sign convention — fully vectorised on the Value column.
    # Normalise Line Item Name with pandas str methods (no Python loop),
    # then map each row to its sign multiplier via the flat _LINE_ITEM_SIGN
    # dict.  Unknown items default to +1 (no change).
    # ------------------------------------------------------------------
    if "Value" in df.columns:
        li_norm: pd.Series = (
            df["Line Item Name"]
            .fillna("")
            .str.strip()
            .str.lower()
            .str.replace("&", " and ", regex=False)
            .str.replace(r"[^a-z0-9]+", " ", regex=True)
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )
        sign_series: pd.Series = li_norm.map(_LINE_ITEM_SIGN).fillna(1).astype(int)
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(0.0).mul(sign_series)

    return df
