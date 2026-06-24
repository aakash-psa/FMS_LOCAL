import traceback
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


def _normalize_payload_cell(value: Any) -> Any:
    """Normalize payload cell values using AssetCo-like rules.

    Mirrors the behavior used in AssetCo ``_df_to_records``:
      - infinities -> 0
      - NaN / None -> ""
      - numeric values preserved
    """
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
    """Normalize a single split payload dict: {index, columns, data}."""
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


# ---------------------------------------------------------------------------
# Module-level constants (built once at import time)
# ---------------------------------------------------------------------------

_SKIP_LINE_ITEMS = {
    "total liabilities + equity",
    "total liabilities equity",
    "total liabilities",
    "net unearned revenue",
    "net accounts payable",
    "total assets",
    "net property investments",
    "total property investments",
    "net income",
    "net accounts receivable",
    "net advances for land",
    "net retained earnings",
    "total equity",
    "gross profit",
    "ebitda",
    "ebit",
    "ebt",
    "net revenue",
    "total revenue",
    "net cash from financing",
    "net change in cash",
    "net cash from operations",
    "net cash from investments",
}

_SECTION_CANONICAL = {
    "cashflow from operations": "Cashflow from Operations",
    "cashflow from investments": "Cashflow from Investments",
    "cashflow from financing": "Cashflow from Financing",
    "income statement": "Income Statement",
    "balance sheet": "Balance Sheet",
    "assets": "ASSETS",
    "liabilities": "LIABILITIES",
    "equity": "EQUITY",
}

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
        "less: interparty ar ap netting": "ASSETS",
        "advances for land": "ASSETS",
        "less: interparty advances ur netting": "ASSETS",
        "advance to contractor": "ASSETS",
        "escrow restricted cash": "ASSETS",
        "restricted cash sinking fund": "ASSETS",
        "cwip": "ASSETS",
        "land assets": "ASSETS",
        "investment property": "ASSETS",
        "less: unrealized gains": "ASSETS",
        "accumulated depreciation": "ASSETS",
        "investments in associates": "ASSETS",
        "accounts payable": "LIABILITIES",
        "unearned revenue": "LIABILITIES",
        "debt revolver": "LIABILITIES",
        "debt term loan": "LIABILITIES",
        "debt other": "LIABILITIES",
        "shareholders equity": "EQUITY",
        "share capital": "EQUITY",
        "retained earnings": "EQUITY",
        "less: interparty retained earnings": "EQUITY",
    },
}

_LINE_ITEM_POSITION_RULES = {
    "less: interparty cash collection": {
        "Cashflow Section": "CASHFLOW FROM OPERATIONS",
        "Main Category": "Share of Profit from JV",
    },
    "add: interparty cash payment": {
        "Cashflow Section": "CASHFLOW FROM INVESTMENTS",
        "Main Category": "Investment in JV",
    },
    "dividends received from jv": {
        "Cashflow Section": "CASHFLOW FROM INVESTMENTS",
        "Main Category": "Investment in JV",
    },
    "land in kind contribution": {
        "Cashflow Section": "CASHFLOW FROM FINANCING",
        "Main Category": "Equity Contributions",
    },
    "less: interparty ar/ap netting": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "ASSETS",
    },
    "less: interparty advances/ur netting": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "ASSETS",
    },
    "less: interparty retained earnings": {
        "Cashflow Section": "Balance Sheet",
        "Main Category": "EQUITY",
    },
}

_EXCLUDED_SHEETS = {"monthly timeline", "timeline", "yearly timeline", "hospitality p&l"}
_BS_SECTION_SET = {"ASSETS", "LIABILITIES", "EQUITY"}


# ---------------------------------------------------------------------------
# Module-level pure helpers (defined once at import time)
# ---------------------------------------------------------------------------

def _is_blank_normalization_cell(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    try:
        return value != value  # NaN
    except Exception:
        return False


def _normalize_numeric_cell(value):
    if isinstance(value, float):
        if value == float("inf") or value == float("-inf"):
            return 0.0
        if value != value:  # NaN
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
    return "" if text is None else str(text).strip().lower()


def _canonical_section_name(label, fallback):
    section = _SECTION_CANONICAL.get(_normalize_position_key(label))
    if section:
        if section in _BS_SECTION_SET:
            return "Balance Sheet"
        return section
    return fallback


def _is_major_section_header(label):
    key = _normalize_position_key(label)
    return key in _SECTION_CANONICAL or key.startswith("cashflow from ")


def _resolve_row_position(sheet_name, current_section, current_category, line_item):
    rule = _LINE_ITEM_POSITION_RULES.get(_normalize_position_key(line_item))
    if not rule:
        resolved_section = _canonical_section_name(current_section, str(current_section or sheet_name))
        section_main_map = _MAIN_CATEGORY_BY_SECTION.get(resolved_section, {})
        section_item_map = _LINE_ITEM_TO_MAIN_BY_SECTION.get(resolved_section, {})

        normalized_line = _normalize_position_key(line_item)
        mapped_main = section_item_map.get(normalized_line)
        if mapped_main:
            return resolved_section, mapped_main

        normalized_main = _normalize_position_key(current_category)
        canonical_main = section_main_map.get(normalized_main, current_category)
        return resolved_section, canonical_main
    return (
        str(rule.get("Cashflow Section") or _canonical_section_name(current_section, str(current_section or sheet_name))),
        str(rule.get("Main Category") or current_category),
    )


def _process_sheet_rows(row_labels, columns, data_rows, sheet_name, value_type):
    """Shared row-processing loop for monthly and annual sheets."""
    records = []
    current_section = str(sheet_name)
    current_category = ""

    for row_idx, row_label in enumerate(row_labels):
        label = "" if row_label is None else str(row_label).strip()
        row_vals = data_rows[row_idx] if row_idx < len(data_rows) and isinstance(data_rows[row_idx], list) else []

        if not label or _normalize_position_key(label) in _SKIP_LINE_ITEMS:
            continue

        is_all_empty = all(_is_blank_normalization_cell(cell) for cell in row_vals)

        if is_all_empty:
            if _is_major_section_header(label):
                current_section = _canonical_section_name(label, label)
                current_category = ""
            else:
                resolved_section = _canonical_section_name(current_section, str(current_section or sheet_name))
                current_category = _MAIN_CATEGORY_BY_SECTION.get(resolved_section, {}).get(
                    _normalize_position_key(label), label
                )
            continue

        resolved_section, resolved_category = _resolve_row_position(
            sheet_name, current_section, current_category, label
        )

        for col_idx, col in enumerate(columns):
            value = row_vals[col_idx] if col_idx < len(row_vals) else None
            value = _normalize_numeric_cell(value)

            if _is_blank_normalization_cell(value) or _is_zero_or_null_value(value):
                continue

            col_text = "" if col is None else str(col)
            period_start = col_text if value_type == "Monthly" and ("-" in col_text or "/" in col_text) else ""

            records.append(
                {
                    "Cashflow Section": resolved_section,
                    "Main Category": resolved_category,
                    "Line Item": label,
                    "Value Type": value_type,
                    "Period Start": period_start,
                    "Year": col_text,
                    "Value": value,
                }
            )

    return records


def _exceloutput_monthly_to_dashboard_rows(excel_output):
    """Flatten exceloutput.monthly_dfs / annual_dfs payloads into dashboard records."""
    if not isinstance(excel_output, dict):
        return []

    monthly_dfs = excel_output.get("monthly_dfs") or {}
    annual_dfs = excel_output.get("annual_dfs") or {}
    if not isinstance(monthly_dfs, dict):
        return []
    if not isinstance(annual_dfs, dict):
        annual_dfs = {}

    records = []

    for sheet_name, entry in monthly_dfs.items():
        if str(sheet_name or "").strip().lower() in _EXCLUDED_SHEETS:
            continue
        if not (isinstance(entry, (tuple, list)) and len(entry) == 2 and isinstance(entry[1], dict)):
            continue
        payload = entry[1]
        records.extend(
            _process_sheet_rows(
                payload.get("index") or [],
                payload.get("columns") or [],
                payload.get("data") or [],
                sheet_name,
                "Monthly",
            )
        )

    bs_entry = annual_dfs.get("Balance Sheet")
    if isinstance(bs_entry, (tuple, list)) and len(bs_entry) == 2 and isinstance(bs_entry[1], dict):
        payload = bs_entry[1]
        records.extend(
            _process_sheet_rows(
                payload.get("index") or [],
                payload.get("columns") or [],
                payload.get("data") or [],
                "Balance Sheet",
                "Annual",
            )
        )

    return records


def _normalize_excel_output_payloads(excel_output: Any) -> Any:
    """Normalize all monthly/annual payloads inside excel_output."""
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
                isinstance(entry, (tuple, list))
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def fninitialising_all_values(payload: Any) -> Optional[Any]:
    try:
        if payload is None:
            print("Error in fninitialising_all_values: payload cannot be None")
            return None
        if not isinstance(payload, (dict, list)):
            print(
                "Error in fninitialising_all_values: payload must be a dictionary or list, "
                f"got {type(payload).__name__}"
            )
            return None

        # ------------------------------------------------------------------
        # Build final output
        # ------------------------------------------------------------------
        output_json = payload.get("output_json", {})
        excel_output = {
            "monthly_dfs": output_json.get("monthly_dfs", {}),
            "annual_dfs": output_json.get("annual_dfs", {}),
        }

        # ------------------------------------------------------------------
        # Resolve asset filter mode from named ranges
        # ------------------------------------------------------------------
        _asset_filter_mode = "Consolidated"
        _named_ranges = payload.get("namedRanges", []) or payload.get("namedranges", [])
        try:
            if _named_ranges:
                _nr_lookup = {nr["name"]: nr for nr in _named_ranges}
                _attr_key = "m.jv.global.attribute"
                _val_key = "m.jv.global.value"
                if _attr_key in _nr_lookup and _val_key in _nr_lookup:
                    _attr_list = [row[0] for row in _nr_lookup[_attr_key]["values"]]
                    _value_list = [row[0] for row in _nr_lookup[_val_key]["values"]]
                    if "asset_id" in _attr_list:
                        _asset_name_value = str(_value_list[_attr_list.index("asset_id")]).strip()
                        _asset_filter_mode = "Consolidated" if _asset_name_value.lower() == "consolidated" else _asset_name_value
        except Exception as _filter_exc:
            print(f"Warning: Could not extract asset filter mode from payload: {_filter_exc}")

        payload["_asset_filter_mode"] = _asset_filter_mode

        # ------------------------------------------------------------------
        # Extract JV global map from named ranges
        # ------------------------------------------------------------------
        def _normalize_named_range_value(values):
            if isinstance(values, list):
                if len(values) == 1 and isinstance(values[0], list):
                    return values[0][0] if len(values[0]) == 1 else values[0]
                if all(isinstance(item, list) and len(item) == 1 for item in values):
                    return [item[0] for item in values]
                return values
            return values

        def _extract_named_range(name):
            entry = next((nr for nr in _named_ranges if nr.get("name") == name), None)
            if not isinstance(entry, dict):
                return None
            return _normalize_named_range_value(entry.get("values"))

        _jv_global_class = _extract_named_range("m.jv.global.class")
        _jv_global_attribute = _extract_named_range("m.jv.global.attribute")
        _jv_global_data = _extract_named_range("m.jv.global.data")
        _jv_global_value = _extract_named_range("m.jv.global.value")
        if _jv_global_data is None and _jv_global_value is not None:
            _jv_global_data = _jv_global_value

        _jv_global_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(_jv_global_class, list) and isinstance(_jv_global_attribute, list):
            if isinstance(_jv_global_data, list):
                max_len = min(len(_jv_global_class), len(_jv_global_attribute), len(_jv_global_data))
                for idx in range(max_len):
                    cls_name = _jv_global_class[idx]
                    attr_name = _jv_global_attribute[idx]
                    if cls_name is not None and attr_name is not None:
                        _jv_global_map.setdefault(str(cls_name), {})[str(attr_name)] = _jv_global_data[idx]
            else:
                max_len = min(len(_jv_global_class), len(_jv_global_attribute))
                for idx in range(max_len):
                    cls_name = _jv_global_class[idx]
                    attr_name = _jv_global_attribute[idx]
                    if cls_name is not None and attr_name is not None:
                        _jv_global_map.setdefault(str(cls_name), {})[str(attr_name)] = _jv_global_data

        # ------------------------------------------------------------------
        # Normalize and flatten to dashboard rows
        # ------------------------------------------------------------------
        excel_output = _normalize_excel_output_payloads(excel_output)
        attached_payload = _exceloutput_monthly_to_dashboard_rows(excel_output)

        return {
            "normalized_dashboard_payload": attached_payload,
            "ModelAssumptions": _jv_global_map,
        }

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            error_msg = (
                f"Error in fninitialising_all_values at line {last_frame.lineno} "
                f"in {last_frame.filename}: {str(e)}\n"
                f"Full Traceback:\n{traceback.format_exc()}"
            )
            print(error_msg)
        else:
            print(f"Error in fninitialising_all_values: {str(e)}")
        return None
