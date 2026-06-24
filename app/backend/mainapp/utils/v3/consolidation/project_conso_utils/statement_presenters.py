"""
Presentable balance-sheet / income-statement / cashflow-statement builders.

fn_build_presentable_income_statement is unified to support the optional
``line_item_aliases`` dict used by DevCo for alias fallback lookups.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def fn_build_presentable_balance_sheet(
    base_df: pd.DataFrame,
    balance_sheet_structure: Dict[str, Dict[str, List[str]]],
) -> pd.DataFrame:
    """
    Build a presentable balance sheet with section headers and empty rows.
    """
    if base_df.empty:
        return base_df.copy()

    columns = base_df.columns.tolist()
    n_cols = len(columns)
    output_rows: List[List[Any]] = []
    output_index: List[str] = []

    def _get_line_values(line_item: str) -> np.ndarray:
        if line_item in base_df.index:
            return base_df.loc[line_item, :].to_numpy(dtype=np.float64, copy=False)
        return np.zeros(n_cols, dtype=np.float64)

    def _sum_section_values(section_items: List[str]) -> np.ndarray:
        running = np.zeros(n_cols, dtype=np.float64)
        for item in section_items:
            running = running + _get_line_values(item)
        return running

    # Skip these categories from sub-section header rendering
    _SKIP_HEADERS = {"Interparty Eliminations"}

    row_spec: List[tuple] = [
        ("ASSETS", "section"),
        ("", "blank"),
    ]

    for category, items in balance_sheet_structure.get("Assets", {}).items():
        if category not in _SKIP_HEADERS:
            row_spec.append((category, "subsection"))
        for item in items:
            row_spec.append((item, "line"))
    row_spec.append(("", "blank"))
    row_spec.append(("Total Assets", "total_assets"))

    row_spec.append(("", "blank"))
    row_spec.append(("LIABILITIES", "section"))
    row_spec.append(("", "blank"))

    for category, items in balance_sheet_structure.get("Liabilities", {}).items():
        if category not in _SKIP_HEADERS:
            row_spec.append((category, "subsection"))
        for item in items:
            row_spec.append((item, "line"))
    row_spec.append(("", "blank"))
    row_spec.append(("Total Liabilities", "total_liabilities"))

    row_spec.append(("", "blank"))
    row_spec.append(("EQUITY", "section"))
    row_spec.append(("", "blank"))

    for category, items in balance_sheet_structure.get("Equity", {}).items():
        if category not in _SKIP_HEADERS:
            row_spec.append((category, "subsection"))
        for item in items:
            row_spec.append((item, "line"))
    row_spec.append(("", "blank"))
    row_spec.append(("Total Equity", "total_equity"))
    row_spec.append(("", "blank"))
    row_spec.append(("Total Liabilities + Equity", "total_liabilities_equity"))

    asset_items = [item for cat in balance_sheet_structure.get("Assets", {}).values() for item in cat]
    liability_items = [item for cat in balance_sheet_structure.get("Liabilities", {}).values() for item in cat]
    equity_items = [item for cat in balance_sheet_structure.get("Equity", {}).values() for item in cat]

    total_assets = _sum_section_values(asset_items)
    total_liabilities = _sum_section_values(liability_items)
    total_equity = _sum_section_values(equity_items)
    total_liabilities_equity = total_liabilities + total_equity

    blank = [None] * n_cols
    for row_label, row_type in row_spec:
        output_index.append(row_label)
        if row_type == "line":
            output_rows.append(_get_line_values(row_label).tolist())
        elif row_type == "total_assets":
            output_rows.append(total_assets.tolist())
        elif row_type == "total_liabilities":
            output_rows.append(total_liabilities.tolist())
        elif row_type == "total_equity":
            output_rows.append(total_equity.tolist())
        elif row_type == "total_liabilities_equity":
            output_rows.append(total_liabilities_equity.tolist())
        elif row_type in {"section", "blank", "subsection"}:
            output_rows.append(list(blank))

    return pd.DataFrame(data=output_rows, index=output_index, columns=columns, dtype=object)


def fn_build_presentable_income_statement(
    base_df: pd.DataFrame,
    income_statement_structure: Dict[str, Dict[str, List[str]]],
    line_item_aliases: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Build a presentable income statement with section headers and subtotals.

    Parameters:
    -----------
    line_item_aliases : Optional[Dict[str, str]]
        When provided, ``_get_line_values`` will fall back to the alias
        mapping if the original line item is not found in *base_df*.
        DevCo passes ``{"Asset Sales Revenue": "Developed Unit Sales Revenue",
        ...}``; LandCo / AssetCo pass ``None``.
    """
    if base_df.empty:
        return base_df.copy()

    columns = base_df.columns.tolist()
    n_cols = len(columns)
    output_rows: List[List[Any]] = []
    output_index: List[str] = []

    _aliases: Dict[str, str] = line_item_aliases or {}

    def _get_line_values(line_item: str) -> np.ndarray:
        if line_item in base_df.index:
            return base_df.loc[line_item, :].to_numpy(dtype=np.float64, copy=False)
        alias_item = _aliases.get(line_item)
        if alias_item and alias_item in base_df.index:
            return base_df.loc[alias_item, :].to_numpy(dtype=np.float64, copy=False)
        return np.zeros(n_cols, dtype=np.float64)

    def _sum_items(items: List[str]) -> np.ndarray:
        running = np.zeros(n_cols, dtype=np.float64)
        for item in items:
            running = running + _get_line_values(item)
        return running

    revenue_items = []
    for cat in income_statement_structure.get("Revenue", {}).values():
        revenue_items.extend(cat)

    cos_items = []
    for cat in income_statement_structure.get("Cost of Sales", {}).values():
        cos_items.extend(cat)

    opex_items = []
    for cat in income_statement_structure.get("Operating Expenses", {}).values():
        opex_items.extend(cat)

    da_items = []
    for cat in income_statement_structure.get("Depreciation and Amortization", {}).values():
        da_items.extend(cat)

    finance_items = []
    for cat in income_statement_structure.get("Finance Costs", {}).values():
        finance_items.extend(cat)

    other_exp_items = []
    for cat in income_statement_structure.get("Other Expenses", {}).values():
        other_exp_items.extend(cat)

    ie_revenue_items = []
    ie_cost_items = []
    ie_all_items = []
    for cat_name, cat_items in income_statement_structure.get("Interparty Eliminations", {}).items():
        ie_all_items.extend(cat_items)
        if "Revenue" in cat_name:
            ie_revenue_items.extend(cat_items)
        else:
            ie_cost_items.extend(cat_items)

    total_revenue = _sum_items(revenue_items)
    total_cos = _sum_items(cos_items)
    gross_profit = total_revenue - total_cos
    total_opex = _sum_items(opex_items)
    ebitda = gross_profit - total_opex
    total_da = _sum_items(da_items)
    ebit = ebitda - total_da
    total_finance = _sum_items(finance_items)
    ebt = ebit - total_finance
    total_other = _sum_items(other_exp_items)
    total_ie_revenue = _sum_items(ie_revenue_items)
    total_ie_cost = _sum_items(ie_cost_items)
    total_ie_net = total_ie_revenue - total_ie_cost
    pre_elimination_net_income = ebt - total_other
    net_income = pre_elimination_net_income + total_ie_net

    row_spec: List[tuple] = [
        ("REVENUE", "section", None),
        ("", "blank", None),
    ]

    for item in revenue_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("Total Revenue", "calculated", total_revenue))

    row_spec.append(("", "blank", None))
    row_spec.append(("COST OF SALES", "section", None))
    row_spec.append(("", "blank", None))

    for item in cos_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("Gross Profit", "calculated", gross_profit))

    row_spec.append(("", "blank", None))
    row_spec.append(("OPERATING EXPENSES", "section", None))
    row_spec.append(("", "blank", None))

    for item in opex_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("EBITDA", "calculated", ebitda))

    row_spec.append(("", "blank", None))
    row_spec.append(("DEPRECIATION & AMORTIZATION", "section", None))
    row_spec.append(("", "blank", None))

    for item in da_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("EBIT", "calculated", ebit))

    row_spec.append(("", "blank", None))
    row_spec.append(("FINANCE COSTS", "section", None))
    row_spec.append(("", "blank", None))

    for item in finance_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("EBT", "calculated", ebt))

    row_spec.append(("", "blank", None))
    row_spec.append(("OTHER EXPENSES", "section", None))
    row_spec.append(("", "blank", None))

    for item in other_exp_items:
        row_spec.append((item, "line", None))
    row_spec.append(("", "blank", None))
    row_spec.append(("Pre-Elimination Net Income", "calculated", pre_elimination_net_income))

    if ie_all_items:
        row_spec.append(("", "blank", None))
        row_spec.append(("INTERPARTY ELIMINATIONS", "section", None))
        row_spec.append(("", "blank", None))
        for item in ie_all_items:
            row_spec.append((item, "line", None))
        row_spec.append(("", "blank", None))

    row_spec.append(("Net Income", "calculated", net_income))

    blank = [None] * n_cols
    for row_label, row_type, calc_values in row_spec:
        output_index.append(row_label)
        if row_type == "line":
            output_rows.append(_get_line_values(row_label).tolist())
        elif row_type == "calculated":
            output_rows.append(calc_values.tolist() if isinstance(calc_values, np.ndarray) else calc_values)
        elif row_type in {"section", "blank"}:
            output_rows.append(list(blank))

    return pd.DataFrame(data=output_rows, index=output_index, columns=columns, dtype=object)


def fn_build_presentable_cashflow_statement(
    base_df: pd.DataFrame,
    cashflow_structure: Dict[str, Dict[str, List[str]]],
) -> pd.DataFrame:
    """
    Build a presentable cashflow statement with section headers and totals.
    """
    if base_df.empty:
        return base_df.copy()

    columns = base_df.columns.tolist()
    n_cols = len(columns)
    output_rows: List[List[Any]] = []
    output_index: List[str] = []

    def _get_line_values(line_item: str) -> np.ndarray:
        if line_item in base_df.index:
            return base_df.loc[line_item, :].to_numpy(dtype=np.float64, copy=False)
        return np.zeros(n_cols, dtype=np.float64)

    def _sum_section(section_key: str) -> np.ndarray:
        running = np.zeros(n_cols, dtype=np.float64)
        for category in cashflow_structure.get(section_key, {}).values():
            for item in category:
                running = running + _get_line_values(item)
        return running

    sections = [
        ("CFO", "CASHFLOW FROM OPERATIONS", "Net Cash from Operations"),
        ("CFI", "CASHFLOW FROM INVESTMENTS", "Net Cash from Investments"),
        ("CFF", "CASHFLOW FROM FINANCING", "Net Cash from Financing"),
    ]

    net_cashflows = []
    blank = [None] * n_cols

    for section_key, section_title, total_label in sections:
        section_total = _sum_section(section_key)
        net_cashflows.append(section_total)

        output_index.append(section_title)
        output_rows.append(list(blank))
        output_index.append("")
        output_rows.append(list(blank))

        for category_name, items in cashflow_structure.get(section_key, {}).items():
            output_index.append(category_name)
            output_rows.append(list(blank))

            for item in items:
                output_index.append(item)
                output_rows.append(_get_line_values(item).tolist())

            output_index.append("")
            output_rows.append(list(blank))

        output_index.append(total_label)
        output_rows.append(section_total.tolist())
        output_index.append("")
        output_rows.append(list(blank))

    net_change = np.zeros(n_cols, dtype=np.float64)
    for section_total in net_cashflows:
        net_change = net_change + section_total

    output_index.append("Net Change in Cash")
    output_rows.append(net_change.tolist())

    return pd.DataFrame(data=output_rows, index=output_index, columns=columns, dtype=object)
