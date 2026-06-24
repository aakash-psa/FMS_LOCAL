"""
Financial statement trace utilities.

This module centralizes logic for building a row-level trace dataframe with:
- No.
- Period
- Value
- Financial Statement
- Line Item Name
- Asset No.

The trace is collected during accounting posting and can also be supplemented
with consolidated-only deltas.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


FS_TRACE_ROWS_KEY = "__financial_statement_trace_rows__"
FS_TRACE_ENABLED_KEY = "__enable_financial_statement_trace__"
FS_TRACE_COLUMNS = [
    "No.",
    "Period",
    "Value",
    "Financial Statement",
    "Line Item Name",
    "Asset No.",
    "Unique ID",
]

_FS_TRACE_BASE_COLUMNS = [
    "Period",
    "Value",
    "Financial Statement",
    "Line Item Name",
    "Asset No.",
    "Unique ID",
]

_TRACE_ZERO_TOLERANCE = 1e-3

_CASHFLOW_STATEMENT_LABEL = "Cashflow Statement"
_INCOME_STATEMENT_LABEL = "Income Statement"
_BALANCE_SHEET_LABEL = "Balance Sheet"

_BS_CWIP_MERGE_LABELS = {"CWIP - Serviced Land", "CWIP - Developed Units", "Serviced Land Assets"}
_BS_CWIP_TARGET_LABEL = "CWIP"


def _is_effectively_zero(value: float, tolerance: float = _TRACE_ZERO_TOLERANCE) -> bool:
    return abs(float(value)) <= tolerance


def _coerce_period(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, pd.Period):
        value = value.to_timestamp(how="end").normalize()

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return ""
        parsed = pd.to_datetime(stripped, errors="coerce")
        if pd.isna(parsed):
            return stripped
        return pd.Timestamp(parsed).strftime("%Y-%m-%d")

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _coerce_asset_no(value: Any, fallback: str = "Unknown") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except Exception:
        pass

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return fallback
    return text


def _coerce_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except Exception:
        pass

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return fallback
    return text


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (np.floating, float)) and np.isnan(value):
            return None
        return float(value)
    except Exception:
        return None


def _coerce_period_series(series: pd.Series) -> pd.Series:
    """Vectorized equivalent of applying _coerce_period element-wise."""
    parsed = pd.to_datetime(series, errors="coerce")
    formatted = parsed.dt.strftime("%Y-%m-%d")
    unparseable = parsed.isna()
    if unparseable.any():
        orig = series[unparseable]
        fallback = orig.apply(
            lambda v: "" if v is None else str(v).strip()
        ).replace({"none": "", "nan": ""}, regex=False)
        formatted = formatted.copy()
        formatted.loc[unparseable] = fallback
    return formatted.fillna("")


def _coerce_asset_no_series(series: pd.Series, fallback: str = "Unknown") -> pd.Series:
    """Vectorized equivalent of applying _coerce_asset_no element-wise."""
    as_str = series.astype(str).str.strip()
    bad = as_str.str.lower().isin({"", "none", "nan"})
    as_str = as_str.copy()
    as_str[bad] = fallback
    return as_str


def _extract_asset_no_from_description(description: str) -> str:
    """Extract asset token from the right-most "Asset <...>" fragment."""
    if not description:
        return ""

    matches = list(re.finditer(r"\bAsset\s+", description, flags=re.IGNORECASE))
    if not matches:
        return ""

    candidate = description[matches[-1].end() :].strip()
    if not candidate:
        return ""

    candidate = re.split(r"[,;\)\]\}]", candidate, maxsplit=1)[0].strip()
    return _coerce_asset_no(candidate, fallback="")


def _looks_like_asset_identifier(candidate: str) -> bool:
    """Return True for tokens that plausibly represent asset identifiers."""
    if not candidate:
        return False

    text = str(candidate).strip()
    if text == "":
        return False

    # Synthetic asset IDs used in this codebase typically contain at least one digit.
    return bool(re.search(r"\d", text))


def _extract_asset_no_from_reference(reference: str) -> str:
    """Extract asset token from structured references when it is unambiguous.

    Supported form: "...-<asset_id>-YYYY-MM-DD" (or YYYY-MM), where asset_id
    is treated as valid only if it resembles an asset identifier.
    """
    if not reference:
        return ""

    # Handle explicit "Asset <...>" fragments if present.
    candidate = _extract_asset_no_from_description(reference)
    if candidate:
        return candidate

    date_suffix_patterns = (
        r"-(?P<asset>[^-\s]+)-\d{4}-\d{2}-\d{2}$",
        r"-(?P<asset>[^-\s]+)-\d{4}-\d{2}$",
    )
    for pattern in date_suffix_patterns:
        match = re.search(pattern, reference)
        if not match:
            continue

        candidate = _coerce_asset_no(match.group("asset"), fallback="")
        if _looks_like_asset_identifier(candidate):
            return candidate

    return ""


def fn_is_financial_statement_trace_enabled(financial_statements: Dict[str, Any]) -> bool:
    if not isinstance(financial_statements, dict):
        return False
    return bool(financial_statements.get(FS_TRACE_ENABLED_KEY, False))


def fn_initialize_financial_statement_trace(financial_statements: Dict[str, Any]) -> None:
    if not fn_is_financial_statement_trace_enabled(financial_statements):
        return
    rows = financial_statements.get(FS_TRACE_ROWS_KEY)
    if not isinstance(rows, list):
        financial_statements[FS_TRACE_ROWS_KEY] = []


def fn_append_financial_statement_trace_row(
    financial_statements: Dict[str, Any],
    period: Any,
    value: Any,
    financial_statement: str,
    line_item_name: str,
    asset_no: Any,
    entry_name: Any = "",
    entry_description: Any = "",
    reference_id: Any = "",
    journal_entry_id: Any = "",
) -> None:
    if not fn_is_financial_statement_trace_enabled(financial_statements):
        return

    numeric_value = _safe_float(value)
    if numeric_value is None or _is_effectively_zero(numeric_value):
        return

    fs_name = str(financial_statement).strip()
    li_name = str(line_item_name).strip()
    if fs_name == "" or li_name == "":
        return

    fn_initialize_financial_statement_trace(financial_statements)
    rows: List[Dict[str, Any]] = financial_statements[FS_TRACE_ROWS_KEY]
    rows.append(
        {
            "Period": _coerce_period(period),
            "Value": numeric_value,
            "Financial Statement": fs_name,
            "Line Item Name": li_name,
            "Asset No.": _coerce_asset_no(asset_no),
        }
    )


def fn_extract_asset_no_from_entry(entry: Optional[Dict[str, Any]], fallback: str = "Unknown") -> str:
    if not isinstance(entry, dict):
        return fallback

    for key in ("asset_no", "asset_id", "asset_unique_identifier"):
        if key in entry:
            candidate = _coerce_asset_no(entry.get(key), fallback="")
            if candidate:
                return candidate

    description = str(entry.get("description", "") or "").strip()
    candidate = _extract_asset_no_from_description(description)
    if candidate:
        return candidate

    reference = str(entry.get("reference", "") or "").strip()
    candidate = _extract_asset_no_from_reference(reference)
    if candidate:
        return candidate

    return fallback


def _resolve_bs_signed_movement(
    account_name: str,
    side: str,
    amount: float,
    account_names_dict: Dict[str, Dict[str, str]],
) -> float:
    account_type = account_names_dict.get(account_name, {}).get("type", "Asset")
    debit_normal = account_type in ("Asset", "Expense")

    if side == "debit":
        return amount if debit_normal else -amount
    return -amount if debit_normal else amount


def fn_record_batch_entry_financial_statement_trace(
    financial_statements: Dict[str, Any],
    entry: Dict[str, Any],
    account_names_dict: Dict[str, Dict[str, str]],
    type_aware_is_posting: bool = False,
    interparty_cash_name: Optional[str] = None,
) -> None:
    if not fn_is_financial_statement_trace_enabled(financial_statements):
        return

    if not isinstance(entry, dict) or not isinstance(financial_statements, dict):
        return

    amount = _safe_float(entry.get("amount"))
    if amount is None or amount <= 0.0:
        return

    period = entry.get("period")
    debit_account = str(entry.get("debit_account", "") or "").strip()
    credit_account = str(entry.get("credit_account", "") or "").strip()
    if debit_account == "" or credit_account == "":
        return

    asset_no = fn_extract_asset_no_from_entry(entry)

    # Cashflow trace
    cash_line_item = entry.get("cashflow_line_item")
    if cash_line_item:
        cash_accounts = {"Cash and Cash Equivalents"}
        if interparty_cash_name:
            cash_accounts.add(interparty_cash_name)

        is_cash_dr = debit_account in cash_accounts
        is_cash_cr = credit_account in cash_accounts

        signed_cash = 0.0
        if is_cash_dr and not is_cash_cr:
            signed_cash = amount
        elif is_cash_cr and not is_cash_dr:
            signed_cash = -amount

        fn_append_financial_statement_trace_row(
            financial_statements=financial_statements,
            period=period,
            value=signed_cash,
            financial_statement=_CASHFLOW_STATEMENT_LABEL,
            line_item_name=str(cash_line_item),
            asset_no=asset_no,
        )

    # Income statement trace
    is_line_item = entry.get("income_statement_line_item")
    if is_line_item:
        if type_aware_is_posting:
            credit_type = account_names_dict.get(credit_account, {}).get("type", "")
            debit_type = account_names_dict.get(debit_account, {}).get("type", "")
            if credit_type == "Revenue" or debit_type == "Expense":
                signed_is = amount
            elif debit_type == "Revenue" or credit_type == "Expense":
                signed_is = -amount
            else:
                signed_is = amount
        else:
            signed_is = amount

        fn_append_financial_statement_trace_row(
            financial_statements=financial_statements,
            period=period,
            value=signed_is,
            financial_statement=_INCOME_STATEMENT_LABEL,
            line_item_name=str(is_line_item),
            asset_no=asset_no,
        )

    # Balance sheet trace for touched BS accounts
    bs_df = financial_statements.get("balance_sheet")
    if isinstance(bs_df, pd.DataFrame) and not bs_df.empty:
        bs_index = bs_df.index

        if debit_account in bs_index:
            fn_append_financial_statement_trace_row(
                financial_statements=financial_statements,
                period=period,
                value=_resolve_bs_signed_movement(
                    account_name=debit_account,
                    side="debit",
                    amount=amount,
                    account_names_dict=account_names_dict,
                ),
                financial_statement=_BALANCE_SHEET_LABEL,
                line_item_name=debit_account,
                asset_no=asset_no,
            )

        if credit_account in bs_index:
            fn_append_financial_statement_trace_row(
                financial_statements=financial_statements,
                period=period,
                value=_resolve_bs_signed_movement(
                    account_name=credit_account,
                    side="credit",
                    amount=amount,
                    account_names_dict=account_names_dict,
                ),
                financial_statement=_BALANCE_SHEET_LABEL,
                line_item_name=credit_account,
                asset_no=asset_no,
            )


def fn_record_matrix_entries_financial_statement_trace(
    financial_statements: Dict[str, Any],
    index_maps: Dict[str, Any],
    debit_indices: Sequence[int],
    credit_indices: Sequence[int],
    amounts: Sequence[float],
    period_indices: Sequence[int],
    is_line_item_indices: Sequence[int],
    cf_line_item_indices: Sequence[int],
    account_types: np.ndarray,
    all_periods: List[str],
    idx_to_account: Dict[int, str],
    type_aware_is_posting: bool = False,
    interparty_cash_name: Optional[str] = None,
    asset_indices: Optional[Sequence[int]] = None,
    asset_labels: Optional[List[str]] = None,
    entry_names: Optional[Sequence[Any]] = None,
    entry_descriptions: Optional[Sequence[Any]] = None,
    reference_ids: Optional[Sequence[Any]] = None,
    journal_entry_ids: Optional[Sequence[Any]] = None,
) -> None:
    if not fn_is_financial_statement_trace_enabled(financial_statements):
        return

    if not isinstance(financial_statements, dict):
        return

    n_entries = len(amounts)
    if n_entries == 0:
        return

    fn_initialize_financial_statement_trace(financial_statements)

    account_to_idx = index_maps.get("account_to_idx", {}) or {}
    cf_row_map = index_maps.get("cf_row_map", {}) or {}
    is_row_map = index_maps.get("is_row_map", {}) or {}
    bs_row_map = index_maps.get("bs_row_map", {}) or {}

    cf_idx_to_item = {int(v): k for k, v in cf_row_map.items()}
    is_idx_to_item = {int(v): k for k, v in is_row_map.items()}
    bs_accounts = set(bs_row_map.keys())

    cash_idx = int(account_to_idx.get("Cash and Cash Equivalents", -1))
    interparty_cash_idx = int(account_to_idx.get(interparty_cash_name, -1)) if interparty_cash_name else -1

    rows: List[Dict[str, Any]] = financial_statements[FS_TRACE_ROWS_KEY]

    # Convert all sequences to numpy arrays once so all subsequent operations
    # are vectorised C-level instead of element-wise Python.
    amounts_arr = np.asarray(amounts, dtype=np.float64)
    period_idx_arr = np.asarray(period_indices, dtype=np.intp)
    debit_idx_arr = np.asarray(debit_indices, dtype=np.intp)
    credit_idx_arr = np.asarray(credit_indices, dtype=np.intp)
    cf_item_idx_arr = np.asarray(cf_line_item_indices, dtype=np.intp)
    is_item_idx_arr = np.asarray(is_line_item_indices, dtype=np.intp)

    n_periods = len(all_periods)
    n_acc_types = len(account_types)

    # Base validity: positive amount and period index in bounds.
    valid = (amounts_arr > 0.0) & (period_idx_arr >= 0) & (period_idx_arr < n_periods)
    if not valid.any():
        return

    # Period strings — all_periods is already YYYY-MM-DD formatted.
    all_periods_np = np.asarray(all_periods, dtype=object)
    safe_period_idx = np.where(valid, period_idx_arr, 0)
    period_strs = all_periods_np[safe_period_idx]

    # Asset numbers — vectorised construction from asset_indices + asset_labels.
    asset_no_arr = np.full(n_entries, "Unknown", dtype=object)
    if asset_indices is not None:
        ai_raw = np.asarray(asset_indices, dtype=np.intp)
        cap = min(n_entries, len(ai_raw))
        if cap > 0:
            ai_slice = ai_raw[:cap]
            if asset_labels is not None:
                al_np = np.asarray(asset_labels, dtype=object)
                n_al = len(al_np)
                if n_al > 0:
                    in_range = (ai_slice >= 0) & (ai_slice < n_al)
                    clamped = np.clip(ai_slice, 0, n_al - 1)
                    asset_no_arr[:cap] = np.where(in_range, al_np[clamped], ai_slice.astype(str))
                else:
                    asset_no_arr[:cap] = ai_slice.astype(str)
            else:
                asset_no_arr[:cap] = ai_slice.astype(str)

    # Account types per entry (0 = Asset/debit-normal, 1 = Revenue/credit-normal).
    if n_acc_types > 0:
        at_np = np.asarray(account_types, dtype=np.intp)
        safe_dr = np.clip(debit_idx_arr, 0, n_acc_types - 1)
        safe_cr = np.clip(credit_idx_arr, 0, n_acc_types - 1)
        dr_types = np.where(
            (debit_idx_arr >= 0) & (debit_idx_arr < n_acc_types), at_np[safe_dr], 0
        ).astype(np.intp)
        cr_types = np.where(
            (credit_idx_arr >= 0) & (credit_idx_arr < n_acc_types), at_np[safe_cr], 0
        ).astype(np.intp)
    else:
        dr_types = np.zeros(n_entries, dtype=np.intp)
        cr_types = np.zeros(n_entries, dtype=np.intp)

    # ---- Cashflow rows ----
    if cf_idx_to_item:
        max_cf = max(cf_idx_to_item) + 1
        cf_names_np = np.full(max_cf, "", dtype=object)
        for _k, _v in cf_idx_to_item.items():
            if 0 <= _k < max_cf:
                cf_names_np[_k] = _v

        cf_in_range = (cf_item_idx_arr >= 0) & (cf_item_idx_arr < max_cf)
        cf_mask = valid & cf_in_range
        if cf_mask.any():
            safe_cf = np.where(cf_in_range, cf_item_idx_arr, 0)
            cf_names_row = cf_names_np[safe_cf]
            cf_mask &= cf_names_row != ""

            is_cash_dr = (debit_idx_arr == cash_idx) | (
                (interparty_cash_idx >= 0) & (debit_idx_arr == interparty_cash_idx)
            )
            is_cash_cr = (credit_idx_arr == cash_idx) | (
                (interparty_cash_idx >= 0) & (credit_idx_arr == interparty_cash_idx)
            )
            signed_cash = np.where(
                is_cash_dr & ~is_cash_cr,
                amounts_arr,
                np.where(is_cash_cr & ~is_cash_dr, -amounts_arr, 0.0),
            )
            cf_mask &= np.abs(signed_cash) > _TRACE_ZERO_TOLERANCE

            if cf_mask.any():
                rows.extend(
                    {
                        "Period": period_strs[i],
                        "Value": float(signed_cash[i]),
                        "Financial Statement": _CASHFLOW_STATEMENT_LABEL,
                        "Line Item Name": str(cf_names_row[i]),
                        "Asset No.": str(asset_no_arr[i]),
                    }
                    for i in np.where(cf_mask)[0]
                )

    # ---- Income statement rows ----
    if is_idx_to_item:
        max_is = max(is_idx_to_item) + 1
        is_names_np = np.full(max_is, "", dtype=object)
        for _k, _v in is_idx_to_item.items():
            if 0 <= _k < max_is:
                is_names_np[_k] = _v

        is_in_range = (is_item_idx_arr >= 0) & (is_item_idx_arr < max_is)
        is_mask = valid & is_in_range
        if is_mask.any():
            safe_is = np.where(is_in_range, is_item_idx_arr, 0)
            is_names_row = is_names_np[safe_is]
            is_mask &= is_names_row != ""

            if type_aware_is_posting:
                signed_is = np.where(
                    (cr_types == 1) | (dr_types == 0),
                    amounts_arr,
                    np.where((dr_types == 1) | (cr_types == 0), -amounts_arr, amounts_arr),
                )
            else:
                signed_is = amounts_arr

            is_mask &= np.abs(signed_is) > _TRACE_ZERO_TOLERANCE

            if is_mask.any():
                rows.extend(
                    {
                        "Period": period_strs[i],
                        "Value": float(signed_is[i]),
                        "Financial Statement": _INCOME_STATEMENT_LABEL,
                        "Line Item Name": str(is_names_row[i]),
                        "Asset No.": str(asset_no_arr[i]),
                    }
                    for i in np.where(is_mask)[0]
                )

    # ---- Balance sheet rows ----
    if bs_accounts and idx_to_account:
        max_acc = max(idx_to_account) + 1
        is_bs_np = np.zeros(max_acc, dtype=bool)
        acc_name_np = np.full(max_acc, "", dtype=object)
        for _acc_idx, _acc_name in idx_to_account.items():
            if 0 <= _acc_idx < max_acc:
                acc_name_np[_acc_idx] = _acc_name
                if _acc_name in bs_accounts:
                    is_bs_np[_acc_idx] = True

        safe_dr_acc = np.clip(debit_idx_arr, 0, max_acc - 1)
        safe_cr_acc = np.clip(credit_idx_arr, 0, max_acc - 1)
        dr_in_range = (debit_idx_arr >= 0) & (debit_idx_arr < max_acc)
        cr_in_range = (credit_idx_arr >= 0) & (credit_idx_arr < max_acc)

        # Debit BS
        dr_bs_mask = valid & dr_in_range & is_bs_np[safe_dr_acc]
        if dr_bs_mask.any():
            debit_signed = np.where(dr_types == 0, amounts_arr, -amounts_arr)
            dr_bs_mask &= np.abs(debit_signed) > _TRACE_ZERO_TOLERANCE
            if dr_bs_mask.any():
                rows.extend(
                    {
                        "Period": period_strs[i],
                        "Value": float(debit_signed[i]),
                        "Financial Statement": _BALANCE_SHEET_LABEL,
                        "Line Item Name": str(acc_name_np[debit_idx_arr[i]]),
                        "Asset No.": str(asset_no_arr[i]),
                    }
                    for i in np.where(dr_bs_mask)[0]
                )

        # Credit BS
        cr_bs_mask = valid & cr_in_range & is_bs_np[safe_cr_acc]
        if cr_bs_mask.any():
            credit_signed = np.where(cr_types == 0, -amounts_arr, amounts_arr)
            cr_bs_mask &= np.abs(credit_signed) > _TRACE_ZERO_TOLERANCE
            if cr_bs_mask.any():
                rows.extend(
                    {
                        "Period": period_strs[i],
                        "Value": float(credit_signed[i]),
                        "Financial Statement": _BALANCE_SHEET_LABEL,
                        "Line Item Name": str(acc_name_np[credit_idx_arr[i]]),
                        "Asset No.": str(asset_no_arr[i]),
                    }
                    for i in np.where(cr_bs_mask)[0]
                )


def _apply_balance_sheet_cumulative(
    trace_df: pd.DataFrame,
    model_all_periods: Optional[pd.DatetimeIndex] = None,
) -> pd.DataFrame:
    """Consolidate same-period BS rows, convert to cumulative balances, and
    forward-fill the running balance through every period — including all model
    timeline periods so balances carry forward to the model end even when no
    new entry is posted.

    Cumulative is computed per (Asset No., Line Item Name).
    """
    if trace_df.empty:
        return trace_df

    bs_mask = trace_df["Financial Statement"].str.casefold() == _BALANCE_SHEET_LABEL.casefold()
    if not bs_mask.any():
        return trace_df

    bs_df = trace_df.loc[bs_mask].copy()
    non_bs_df = trace_df.loc[~bs_mask].copy()

    uid_by_asset: Optional[pd.Series] = None
    if "Unique ID" in bs_df.columns:
        uid_by_asset = bs_df.groupby("Asset No.", dropna=False)["Unique ID"].first()

    # First collapse all BS entry movements to a single value per period.
    bs_df = (
        bs_df.groupby(
            ["Financial Statement", "Asset No.", "Line Item Name", "Period"],
            dropna=False,
            as_index=False,
        )["Value"].sum()
    )

    if uid_by_asset is not None:
        bs_df["Unique ID"] = bs_df["Asset No."].map(uid_by_asset).fillna("")

    # Then build cumulative balances per asset + line item across periods.
    bs_df["__period_sort"] = pd.to_datetime(bs_df["Period"], errors="coerce")
    bs_df = bs_df.sort_values(
        by=["Financial Statement", "Asset No.", "Line Item Name", "__period_sort", "Period"],
        kind="stable",
    )
    bs_df["Value"] = bs_df.groupby(
        ["Financial Statement", "Asset No.", "Line Item Name"], dropna=False
    )["Value"].cumsum()
    bs_df = bs_df.drop(columns=["__period_sort"])

    # Build the complete set of reporting periods by combining periods that
    # appear in the trace with the full model timeline (when supplied).  This
    # ensures BS balances are forward-filled all the way to the model end
    # period even when no entry is posted in the intervening months.
    trace_period_dts = pd.to_datetime(
        trace_df["Period"].dropna().unique(), errors="coerce"
    )
    if model_all_periods is not None and len(model_all_periods) > 0:
        combined_dts = trace_period_dts.append(pd.DatetimeIndex(model_all_periods))
    else:
        combined_dts = trace_period_dts
    all_period_dts = pd.DatetimeIndex(sorted(combined_dts.dropna().unique()))

    group_keys = ["Financial Statement", "Asset No.", "Line Item Name"]

    if len(all_period_dts) > 1:
        uid_col_exists = "Unique ID" in bs_df.columns

        # Build a sorted list of period strings that covers the full model timeline.
        all_period_strs: List[str] = [
            pd.Timestamp(p).strftime("%Y-%m-%d") for p in all_period_dts
        ]

        # Pivot to wide format: one row per (FS, Asset No., Line Item Name),
        # one column per period.  After the groupby+cumsum above each
        # (group, period) pair is unique, so aggfunc="last" is a safe no-op.
        pivot = bs_df.pivot_table(
            index=group_keys,
            columns="Period",
            values="Value",
            aggfunc="last",
        )

        # Reindex columns to the full, chronologically-sorted period range.
        # Periods that precede a group's first entry will be NaN; periods after
        # the last entry will receive the forward-filled balance.
        pivot = pivot.reindex(columns=all_period_strs)

        # Forward-fill within each row (group) across time.  NaN cells before
        # the first real entry remain NaN — pandas ffill never back-fills.
        pivot = pivot.ffill(axis=1)

        # Unstack back to long format, discarding the pre-first-entry NaN slots.
        try:
            stacked = pivot.stack(future_stack=True).dropna()
        except TypeError:
            stacked = pivot.stack(dropna=True)

        if not stacked.empty:
            bs_long = stacked.reset_index()
            bs_long.columns = pd.Index(group_keys + ["Period", "Value"])
            bs_long = bs_long.loc[
                bs_long["Value"].abs() > _TRACE_ZERO_TOLERANCE
            ].copy()

            if uid_col_exists and uid_by_asset is not None:
                bs_long["Unique ID"] = bs_long["Asset No."].map(uid_by_asset).fillna("")
            else:
                bs_long["Unique ID"] = ""

            bs_df = bs_long
        else:
            bs_df = pd.DataFrame(columns=group_keys + ["Period", "Value", "Unique ID"])
    else:
        bs_df = bs_df.loc[bs_df["Value"].abs() > _TRACE_ZERO_TOLERANCE].copy()

    combined = pd.concat([non_bs_df, bs_df], ignore_index=True)
    return combined[_FS_TRACE_BASE_COLUMNS]


def fn_finalize_financial_statement_trace_dataframe(
    trace_df: Optional[pd.DataFrame],
    apply_bs_cumulative: bool = True,
    model_all_periods: Optional[pd.DatetimeIndex] = None,
) -> pd.DataFrame:
    if trace_df is None or not isinstance(trace_df, pd.DataFrame) or trace_df.empty:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    df = trace_df.copy()
    if "No." in df.columns:
        df = df.drop(columns=["No."])

    for col in _FS_TRACE_BASE_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "Value" else 0.0

    df = df[_FS_TRACE_BASE_COLUMNS]
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(0.0)
    df = df.loc[df["Value"].abs() > _TRACE_ZERO_TOLERANCE].copy()

    if df.empty:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    df["Period"] = _coerce_period_series(df["Period"])
    df["Financial Statement"] = df["Financial Statement"].astype(str).str.strip()
    df["Line Item Name"] = df["Line Item Name"].astype(str).str.strip()
    df["Asset No."] = _coerce_asset_no_series(df["Asset No."])

    df = df.loc[
        (df["Financial Statement"] != "")
        & (df["Line Item Name"] != "")
        & (df["Period"] != "")
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    # When exactly one non-"Unknown" Asset No. is present in the trace (i.e.
    # a single-asset model), propagate it to all "Unknown" rows so that
    # project-level CF entries (e.g. "Project and Asset Equity Contribution")
    # are attributed to the asset and receive a Unique ID downstream.
    _unknown_asset_mask = df["Asset No."] == "Unknown"
    if _unknown_asset_mask.any():
        _known_assets = [
            a for a in df.loc[~_unknown_asset_mask, "Asset No."].unique()
            if a and a != "Unknown"
        ]
        if len(_known_assets) == 1:
            df.loc[_unknown_asset_mask, "Asset No."] = _known_assets[0]

    if apply_bs_cumulative:
        df = _apply_balance_sheet_cumulative(df, model_all_periods=model_all_periods)

    df["__period_sort"] = pd.to_datetime(df["Period"], errors="coerce")
    df = df.sort_values(
        by=["__period_sort", "Financial Statement", "Line Item Name", "Asset No."],
        kind="stable",
    ).drop(columns=["__period_sort"]) 

    df = df.reset_index(drop=True)
    df.insert(0, "No.", np.arange(1, len(df) + 1, dtype=np.int64))
    return df[FS_TRACE_COLUMNS]


def fn_build_financial_statement_trace_dataframe(financial_statements: Dict[str, Any]) -> pd.DataFrame:
    if not isinstance(financial_statements, dict):
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)
    if not fn_is_financial_statement_trace_enabled(financial_statements):
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)
    rows = financial_statements.get(FS_TRACE_ROWS_KEY, [])
    if not isinstance(rows, list) or len(rows) == 0:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    # Derive the full model period timeline from the balance sheet columns so
    # BS balances are forward-filled all the way to the model end period.
    model_all_periods: Optional[pd.DatetimeIndex] = None
    bs_df = financial_statements.get("balance_sheet")
    if isinstance(bs_df, pd.DataFrame) and not bs_df.empty:
        parsed = pd.to_datetime(bs_df.columns, errors="coerce").dropna()
        if len(parsed) > 0:
            model_all_periods = pd.DatetimeIndex(sorted(parsed))

    return fn_finalize_financial_statement_trace_dataframe(
        pd.DataFrame(rows),
        model_all_periods=model_all_periods,
    )


def fn_trace_dataframe_to_payload(trace_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    # Trace payloads are expected to be serialized from an already-finalized df.
    df = fn_finalize_financial_statement_trace_dataframe(trace_df, apply_bs_cumulative=False)

    def _safe(v: Any) -> Any:
        if isinstance(v, (np.floating, float)):
            if np.isnan(v):
                return None
            return float(v)
        if isinstance(v, np.integer):
            return int(v)
        if v is None:
            return None
        return v

    return {
        "index": [int(i) for i in df.index.tolist()],
        "columns": df.columns.tolist(),
        "data": [[_safe(v) for v in row] for row in df.to_numpy(dtype=object, copy=False)],
    }


def fn_trace_payload_to_dataframe(payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    columns = payload.get("columns", [])
    data = payload.get("data", [])
    index = payload.get("index", None)

    if not isinstance(columns, list) or not isinstance(data, list):
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    try:
        df = pd.DataFrame(data=data, columns=columns)
        if isinstance(index, list) and len(index) == len(df):
            df.index = index
        # Payloads usually come from finalized traces; avoid re-cumulating BS.
        return fn_finalize_financial_statement_trace_dataframe(df, apply_bs_cumulative=False)
    except Exception:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)


def fn_concatenate_financial_statement_trace_dataframes(
    trace_dfs: List[pd.DataFrame],
) -> pd.DataFrame:
    normalized: List[pd.DataFrame] = []
    for df in trace_dfs:
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        _df = df.copy()
        if "No." in _df.columns:
            _df = _df.drop(columns=["No."])
        for col in _FS_TRACE_BASE_COLUMNS:
            if col not in _df.columns:
                _df[col] = "" if col != "Value" else 0.0
        normalized.append(_df[_FS_TRACE_BASE_COLUMNS])

    if not normalized:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    combined = pd.concat(normalized, ignore_index=True)
    # Inputs are typically pre-finalized traces; avoid BS double cumulation.
    return fn_finalize_financial_statement_trace_dataframe(combined, apply_bs_cumulative=False)


def _statement_df_to_long(
    statement_df: pd.DataFrame,
    statement_name: str,
    asset_no: str,
) -> pd.DataFrame:
    if statement_df is None or not isinstance(statement_df, pd.DataFrame) or statement_df.empty:
        return pd.DataFrame(columns=_FS_TRACE_BASE_COLUMNS)

    numeric_df = statement_df.apply(pd.to_numeric, errors="coerce")
    try:
        # pandas >= 2.1: adopt the new stack implementation and drop NaNs explicitly.
        stacked = numeric_df.stack(future_stack=True).dropna().reset_index()
    except TypeError:
        # pandas < 2.1: future_stack is unavailable.
        stacked = numeric_df.stack(dropna=True).reset_index()
    if stacked.empty:
        return pd.DataFrame(columns=_FS_TRACE_BASE_COLUMNS)

    stacked.columns = ["Line Item Name", "Period", "Value"]
    stacked = stacked.loc[stacked["Value"].abs() > _TRACE_ZERO_TOLERANCE].copy()
    if stacked.empty:
        return pd.DataFrame(columns=_FS_TRACE_BASE_COLUMNS)

    stacked["Period"] = _coerce_period_series(stacked["Period"])
    stacked["Financial Statement"] = statement_name
    stacked["Asset No."] = asset_no
    stacked["Unique ID"] = ""
    return stacked[_FS_TRACE_BASE_COLUMNS]


def _sum_entity_statement(
    entity_statement_dfs_list: List[Dict[str, pd.DataFrame]],
    statement_name: str,
) -> pd.DataFrame:
    summed: Optional[pd.DataFrame] = None

    for entity_dfs in entity_statement_dfs_list:
        if not isinstance(entity_dfs, dict):
            continue
        df = entity_dfs.get(statement_name)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        numeric_df = df.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        if summed is None:
            summed = numeric_df.copy()
        else:
            summed, numeric_df = summed.align(numeric_df, join="outer", fill_value=0.0)
            summed = summed + numeric_df

    if summed is None:
        return pd.DataFrame()
    return summed


def _normalize_balance_sheet_cwip_rows(statement_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse BS CWIP component rows into a single ``CWIP`` row."""
    if statement_df is None or not isinstance(statement_df, pd.DataFrame) or statement_df.empty:
        return pd.DataFrame() if statement_df is None else statement_df

    result = statement_df.copy()
    merge_labels = {label.casefold() for label in _BS_CWIP_MERGE_LABELS}
    merge_labels.add(_BS_CWIP_TARGET_LABEL.casefold())

    idx_normalized = np.array([str(idx).strip().casefold() for idx in result.index], dtype=object)
    cwip_mask = np.isin(idx_normalized, list(merge_labels))
    if not cwip_mask.any():
        return result

    cwip_sum = (
        result.iloc[cwip_mask]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .sum(axis=0)
    )

    first_pos = int(np.argmax(cwip_mask))
    before = result.iloc[:first_pos]
    after = result.iloc[first_pos:].iloc[~cwip_mask[first_pos:]]
    cwip_row = pd.DataFrame([cwip_sum.tolist()], index=[_BS_CWIP_TARGET_LABEL], columns=result.columns)

    return pd.concat([before, cwip_row, after], axis=0)


def _align_income_statement_entity_signs(merged_df: pd.DataFrame) -> pd.DataFrame:
    """Align entity IS sign orientation to consolidated orientation per line item."""
    if merged_df is None or not isinstance(merged_df, pd.DataFrame) or merged_df.empty:
        return pd.DataFrame() if merged_df is None else merged_df

    required_cols = {"Line Item Name", "Value_final", "Value_entity"}
    if not required_cols.issubset(set(merged_df.columns)):
        return merged_df

    aligned = merged_df.copy()
    aligned["Value_final"] = pd.to_numeric(aligned.get("Value_final"), errors="coerce").fillna(0.0)
    aligned["Value_entity"] = pd.to_numeric(aligned.get("Value_entity"), errors="coerce").fillna(0.0)

    tol = _TRACE_ZERO_TOLERANCE
    overlap = (aligned["Value_final"].abs() > tol) & (aligned["Value_entity"].abs() > tol)
    aligned["__ras"] = np.where(overlap, (aligned["Value_final"] - aligned["Value_entity"]).abs(), 0.0)
    aligned["__rfl"] = np.where(overlap, (aligned["Value_final"] + aligned["Value_entity"]).abs(), 0.0)

    grp_sums = aligned.groupby("Line Item Name", dropna=False)[["__ras", "__rfl"]].transform("sum")
    should_flip = (grp_sums["__rfl"] + tol) < grp_sums["__ras"]

    aligned["Value_entity"] = np.where(should_flip, -aligned["Value_entity"], aligned["Value_entity"])
    return aligned.drop(columns=["__ras", "__rfl"])


def fn_build_consolidated_financial_statement_trace_delta(
    consolidated_statement_dfs: Dict[str, pd.DataFrame],
    entity_statement_dfs_list: List[Dict[str, pd.DataFrame]],
    asset_no: str = "Consolidated",
) -> pd.DataFrame:
    if not isinstance(consolidated_statement_dfs, dict):
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    deltas: List[pd.DataFrame] = []
    for statement_name in (
        _INCOME_STATEMENT_LABEL,
        _BALANCE_SHEET_LABEL,
        _CASHFLOW_STATEMENT_LABEL,
    ):
        final_df = consolidated_statement_dfs.get(statement_name)
        if not isinstance(final_df, pd.DataFrame) or final_df.empty:
            continue

        final_long = _statement_df_to_long(final_df, statement_name, asset_no)
        if final_long.empty:
            continue

        entity_sum_df = _sum_entity_statement(entity_statement_dfs_list, statement_name)
        if statement_name == _BALANCE_SHEET_LABEL:
            entity_sum_df = _normalize_balance_sheet_cwip_rows(entity_sum_df)
        entity_long = _statement_df_to_long(entity_sum_df, statement_name, asset_no)

        group_cols = ["Period", "Financial Statement", "Line Item Name"]

        final_agg = (
            final_long.groupby(group_cols, dropna=False, as_index=False)["Value"].sum()
            if not final_long.empty
            else pd.DataFrame(columns=group_cols + ["Value"])
        )
        entity_agg = (
            entity_long.groupby(group_cols, dropna=False, as_index=False)["Value"].sum()
            if not entity_long.empty
            else pd.DataFrame(columns=group_cols + ["Value"])
        )

        merged = final_agg.merge(
            entity_agg,
            on=group_cols,
            how="left",
            suffixes=("_final", "_entity"),
        )
        merged["Value_final"] = pd.to_numeric(merged.get("Value_final"), errors="coerce").fillna(0.0)
        merged["Value_entity"] = pd.to_numeric(merged.get("Value_entity"), errors="coerce").fillna(0.0)
        if statement_name == _INCOME_STATEMENT_LABEL:
            merged = _align_income_statement_entity_signs(merged)
        merged["Value"] = merged["Value_final"] - merged["Value_entity"]

        merged = merged.loc[merged["Value"].abs() > _TRACE_ZERO_TOLERANCE].copy()
        if statement_name == _CASHFLOW_STATEMENT_LABEL:
            merged = merged.loc[
                merged["Line Item Name"].astype(str).str.strip().str.lower()
                != "land in kind contribution"
            ].copy()
        if merged.empty:
            continue

        merged["Asset No."] = asset_no
        merged["Unique ID"] = ""
        deltas.append(merged[_FS_TRACE_BASE_COLUMNS])

    if not deltas:
        return pd.DataFrame(columns=FS_TRACE_COLUMNS)

    # Consolidated statement deltas are already at statement-period level.
    return fn_finalize_financial_statement_trace_dataframe(
        pd.concat(deltas, ignore_index=True),
        apply_bs_cumulative=False,
    )


def fn_add_unique_id_to_trace_df(
    trace_df: pd.DataFrame,
    asset_no_int_to_uid: Any,
) -> pd.DataFrame:
    """Add 'Unique ID' column by mapping 'Asset No.' (0-indexed int) to uid.

    asset_no_int_to_uid may be a pd.Series (indexed by int) or a dict {int: str}.
    Rows with no matching uid get an empty string. No fallback is applied.
    """
    if not isinstance(trace_df, pd.DataFrame) or trace_df.empty:
        return trace_df
    if "Asset No." not in trace_df.columns:
        return trace_df

    result = trace_df.copy()

    # Vectorised: parse "Asset No." to numeric (handles "24" → 24.0, non-numeric → NaN),
    # then map directly against the int-keyed Series or dict.
    # Python guarantees hash(24) == hash(24.0), so dict/Series lookup of float keys
    # against int keys works correctly.
    numeric_keys = pd.to_numeric(
        result["Asset No."].astype(str).str.strip(), errors="coerce"
    )

    if isinstance(asset_no_int_to_uid, (pd.Series, dict)):
        uid_raw = numeric_keys.map(asset_no_int_to_uid)
    else:
        uid_raw = pd.Series(np.nan, index=result.index)

    uid_str = uid_raw.fillna("").astype(str).str.strip()
    uid_str = uid_str.replace({"None": "", "nan": "", "NaT": ""})

    # Rows explicitly tagged "Consolidated" carry that label through as Unique ID.
    consolidated_mask = result["Asset No."].astype(str).str.strip() == "Consolidated"
    uid_str = uid_str.where(~consolidated_mask, "Consolidated")

    result["Unique ID"] = uid_str
    return result
