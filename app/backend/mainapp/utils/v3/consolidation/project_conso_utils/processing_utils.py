"""
Cashflow line-item processors, direct-cash capex helpers, and row-key
compatibility utilities.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .accounting_engine import (
    fn_flush_batch_entries,
    fn_flush_matrix_entries,
    _ENTRY_DTYPE,
)


# ---------------------------------------------------------------------------
# Structured-array entry builder (zero Python per-cell loops)
# ---------------------------------------------------------------------------

def fn_build_structured_entries_from_source(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    debit_acct_idx: int,
    credit_acct_idx: int,
    period_to_idx: Dict[str, int],
    is_line_item_idx: int = -1,
    cf_line_item_idx: int = -1,
    normalize_negative_to_abs: bool = True,
) -> Tuple[np.ndarray, List[str], List[str]]:
    """
    Build a structured ``_ENTRY_DTYPE`` array from a 2-D source DataFrame
    (assets × periods) using vectorized stack + filter — **no Python
    per-cell loop**.

    Returns ``(entries, asset_labels, period_col_labels)``.
    *entries* is a structured numpy array; *asset_labels* / *period_col_labels*
    are string lists whose indices match the ``asset_idx`` / ``period_col_idx``
    fields of *entries* (used by ``fn_flush_matrix_entries`` for journal
    construction).
    """
    _empty = (np.zeros(0, dtype=_ENTRY_DTYPE), [], [])

    if asset_unique_identifier is None or not isinstance(asset_unique_identifier, pd.Series) or asset_unique_identifier.empty:
        return _empty
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        return _empty
    if not col_to_period:
        return _empty

    period_cols = [c for c in source_df.columns if c in col_to_period]
    if not period_cols:
        return _empty

    # -- Build aligned index arrays ----------------------------------------
    sub_df = source_df[period_cols]
    uid_values = asset_unique_identifier.values

    uid_valid = np.array([
        uid is not None and not (isinstance(uid, float) and np.isnan(uid))
        and str(uid).strip() != ""
        for uid in uid_values
    ], dtype=bool)

    if not np.any(uid_valid):
        return _empty

    # -- Numeric matrix (all assets × period_cols) -------------------------
    mat = sub_df.apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    if normalize_negative_to_abs:
        mat = np.abs(mat)
    mat[~uid_valid, :] = 0.0

    # -- Non-zero coordinates -----------------------------------------------
    nz_rows, nz_cols = np.nonzero(mat)
    if nz_rows.size == 0:
        return _empty

    nz_amounts = mat[nz_rows, nz_cols]

    # -- Map column indices → period indices --------------------------------
    _period_strs = [col_to_period[period_cols[ci]] for ci in nz_cols]
    _period_indices = np.array(
        [period_to_idx.get(ps, -1) for ps in _period_strs], dtype=np.int32,
    )
    valid_mask = _period_indices >= 0
    if not np.any(valid_mask):
        return _empty

    nz_rows = nz_rows[valid_mask]
    nz_cols = nz_cols[valid_mask]
    nz_amounts = nz_amounts[valid_mask]
    _period_indices = _period_indices[valid_mask]

    # -- Labels for journal construction ------------------------------------
    asset_labels = sub_df.index.astype(str).str.strip().tolist()
    period_col_labels = [str(pc) for pc in period_cols]

    # -- Build structured array ---------------------------------------------
    n = len(nz_amounts)
    entries = np.zeros(n, dtype=_ENTRY_DTYPE)
    entries["debit_acct_idx"] = debit_acct_idx
    entries["credit_acct_idx"] = credit_acct_idx
    entries["amount"] = nz_amounts
    entries["period_idx"] = _period_indices
    entries["is_line_item_idx"] = is_line_item_idx
    entries["cf_line_item_idx"] = cf_line_item_idx
    entries["asset_idx"] = nz_rows
    entries["period_col_idx"] = nz_cols

    return entries, asset_labels, period_col_labels


# ---------------------------------------------------------------------------
# Legacy dict-based entry builder (kept for backward compatibility)
# ---------------------------------------------------------------------------

def fn_build_matrix_entries_from_source(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: pd.Series,
    debit_account: str,
    credit_account: str,
    line_item_name: str,
    reference_prefix: str,
    income_statement_line_item: Optional[str] = None,
    cashflow_line_item: Optional[str] = None,
    normalize_negative_to_abs: bool = True,
) -> List[Dict[str, Any]]:
    """
    Build batch-entry dicts from a 2-D source DataFrame (assets × periods)
    using vectorized operations.  No Python loop over individual cells.

    Steps
    -----
    1. Restrict columns to those present in *col_to_period*.
    2. Convert the sub-DataFrame to a numeric numpy matrix in one pass.
    3. Optionally take absolute values.
    4. Identify all non-zero cells via ``np.argwhere``.
    5. Build the entry list from the coordinate array.

    Returns
    -------
    list[dict]
        Batch entries ready for ``fn_flush_batch_entries``.
    """
    if source_df.empty or not col_to_period:
        return []

    if (
        asset_unique_identifier is None
        or not isinstance(asset_unique_identifier, pd.Series)
        or asset_unique_identifier.empty
    ):
        return []

    period_cols = [c for c in source_df.columns if c in col_to_period]
    if not period_cols:
        return []

    # -- Build aligned index arrays ----------------------------------------
    sub_df = source_df[period_cols]
    asset_ids = sub_df.index.astype(str).str.strip().values          # (n_assets,)
    uid_values = asset_unique_identifier.values                       # (n_assets,)
    period_col_arr = np.array(period_cols, dtype=object)              # (n_periods,)
    period_str_arr = np.array(
        [col_to_period[pc] for pc in period_cols], dtype=object,
    )

    # -- Numeric matrix in one pass ----------------------------------------
    amount_matrix = sub_df.apply(pd.to_numeric, errors="coerce").fillna(0.0).values
    if normalize_negative_to_abs:
        amount_matrix = np.abs(amount_matrix)

    # -- Mask out rows with invalid asset UIDs ----------------------------
    uid_valid = np.array([
        uid is not None and not (isinstance(uid, float) and np.isnan(uid))
        and str(uid).strip() != ""
        for uid in uid_values
    ], dtype=bool)
    amount_matrix[~uid_valid, :] = 0.0

    # -- Locate all non-zero (row, col) coordinates -----------------------
    nz_coords = np.argwhere(amount_matrix != 0.0)  # (K, 2) array
    if nz_coords.size == 0:
        return []

    # -- Build entry list from coordinates --------------------------------
    batch_entries: List[Dict[str, Any]] = []
    for row_idx, col_idx in nz_coords:
        batch_entries.append({
            "debit_account": debit_account,
            "credit_account": credit_account,
            "amount": float(amount_matrix[row_idx, col_idx]),
            "period": period_str_arr[col_idx],
            "income_statement_line_item": income_statement_line_item,
            "cashflow_line_item": cashflow_line_item,
            "description": f"{line_item_name} - Asset {asset_ids[row_idx]}",
            "reference": f"{reference_prefix}-{asset_ids[row_idx]}-{period_col_arr[col_idx]}",
        })

    return batch_entries


def fn_process_cashflow_line_item(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: pd.Series,
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    debit_account: str,
    credit_account: str,
    income_statement_line_item: str,
    cashflow_line_item: str,
    line_item_name: str,
    reference_prefix: str,
    index_maps: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process a CFO line item by building batch entries from the source
    DataFrame and flushing once (single rollforward per account).

    When *index_maps* is supplied (from ``fn_build_flush_index_maps``),
    the fast structured-array → ``fn_flush_matrix_entries`` path is used,
    eliminating all per-cell Python dict allocation.
    """
    # Early exit if DataFrame is empty or all zeros
    if source_df.empty or not col_to_period or source_df.abs().sum().sum() < 1e-6:
        return accounts, journal, financial_statements

    # ------------------------------------------------------------------
    # Fast path: matrix-based flush
    # ------------------------------------------------------------------
    if index_maps is not None:
        account_to_idx = index_maps["account_to_idx"]
        period_to_idx = index_maps["period_to_idx"]
        dr_idx = account_to_idx.get(debit_account, -1)
        cr_idx = account_to_idx.get(credit_account, -1)
        if dr_idx < 0 or cr_idx < 0:
            return accounts, journal, financial_statements

        is_row_map = index_maps.get("is_row_map") or {}
        cf_row_map = index_maps.get("cf_row_map") or {}
        is_li_idx = is_row_map.get(income_statement_line_item, -1) if income_statement_line_item else -1
        cf_li_idx = cf_row_map.get(cashflow_line_item, -1) if cashflow_line_item else -1

        entries, asset_labels, period_col_labels = fn_build_structured_entries_from_source(
            source_df=source_df,
            col_to_period=col_to_period,
            asset_unique_identifier=asset_unique_identifier,
            debit_acct_idx=dr_idx,
            credit_acct_idx=cr_idx,
            period_to_idx=period_to_idx,
            is_line_item_idx=is_li_idx,
            cf_line_item_idx=cf_li_idx,
            normalize_negative_to_abs=False,
        )
        if len(entries) == 0:
            return accounts, journal, financial_statements

        return fn_flush_matrix_entries(
            entries=entries,
            accounts=accounts,
            journal=journal,
            financial_statements=financial_statements,
            account_names_dict=account_names_dict,
            index_maps=index_maps,
            reference_prefix=reference_prefix,
            line_item_name=line_item_name,
            asset_labels=asset_labels,
            period_col_labels=period_col_labels,
        )

    # ------------------------------------------------------------------
    # Legacy path: build batch entries and flush
    # ------------------------------------------------------------------

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return accounts, journal, financial_statements

    period_map = [(pc, col_to_period.get(pc)) for pc in period_cols]

    _batch_entries: List[Dict[str, Any]] = []

    for asset_idx, asset_unique_id in zip(source_df.index, asset_unique_identifier):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        asset_row = source_df.loc[asset_idx]
        amount_values = pd.to_numeric(
            asset_row.reindex(period_cols), errors="coerce",
        ).fillna(0.0).to_numpy(dtype="float64")

        if not np.any(amount_values):
            continue

        for (period_col, period_str), amount in zip(period_map, amount_values):
            if period_str is None or amount == 0.0:
                continue

            _batch_entries.append({
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": float(amount),
                "period": period_str,
                "income_statement_line_item": income_statement_line_item,
                "cashflow_line_item": cashflow_line_item,
                "description": f"{line_item_name} - Asset {asset_idx}",
                "reference": f"{reference_prefix}-{asset_idx}-{period_col}",
            })

    if not _batch_entries:
        return accounts, journal, financial_statements

    return fn_flush_batch_entries(
        batch_entries=_batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
    )


def fn_build_direct_cash_batch_entries(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    debit_account: str,
    credit_account: str,
    cashflow_line_item: str,
    line_item_name: str,
    reference_prefix: str,
    normalize_negative_to_abs: bool = True,
    income_statement_line_item: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build batch entry dicts for direct-cash capex line items (no flush).

    Uses vectorized extraction: all period values for an asset are pulled as a
    numpy array in one call, and non-zero entries are identified via boolean
    masking before building the batch dicts.
    """
    if (
        asset_unique_identifier is None
        or not isinstance(asset_unique_identifier, pd.Series)
        or asset_unique_identifier.empty
    ):
        return []

    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        return []

    if not col_to_period:
        return []

    period_cols = list(col_to_period.keys())
    if not period_cols:
        return []

    source_df_local = source_df.copy()
    source_df_local.index = source_df_local.index.map(lambda x: str(x).strip())

    # Pre-compute period column → period string mapping arrays.
    period_col_arr = np.array(period_cols, dtype=object)
    period_str_arr = np.array(
        [col_to_period.get(pc) for pc in period_cols], dtype=object,
    )
    # Mask for valid (non-None) period mappings.
    valid_period_mask = np.array(
        [col_to_period.get(pc) is not None for pc in period_cols], dtype=bool,
    )

    # Extract the entire matrix for all assets at once.
    amount_matrix = pd.to_numeric(
        source_df_local.reindex(columns=period_cols).stack(dropna=False),
        errors="coerce",
    ).fillna(0.0).values.reshape(len(source_df_local), len(period_cols))

    if normalize_negative_to_abs:
        amount_matrix = np.abs(amount_matrix)

    batch_entries: List[Dict[str, Any]] = []

    for row_idx, (asset_idx, asset_unique_id) in enumerate(
        zip(source_df_local.index, asset_unique_identifier)
    ):
        if asset_unique_id is None or pd.isna(asset_unique_id) or str(asset_unique_id).strip() == "":
            continue

        row_amounts = amount_matrix[row_idx]

        # Non-zero AND valid-period mask — identifies entries to create.
        nz_mask = (row_amounts != 0.0) & valid_period_mask
        if not np.any(nz_mask):
            continue

        nz_indices = np.flatnonzero(nz_mask)
        for j in nz_indices:
            batch_entries.append({
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": float(row_amounts[j]),
                "period": period_str_arr[j],
                "income_statement_line_item": income_statement_line_item,
                "cashflow_line_item": cashflow_line_item,
                "description": f"{line_item_name} - Asset {asset_idx}",
                "reference": f"{reference_prefix}-{asset_idx}-{period_col_arr[j]}",
            })

    return batch_entries


# ---------------------------------------------------------------------------
# Structured-array direct-cash entry builder
# ---------------------------------------------------------------------------

def fn_build_direct_cash_matrix_entries(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    debit_acct_idx: int,
    credit_acct_idx: int,
    period_to_idx: Dict[str, int],
    cf_line_item_idx: int = -1,
    is_line_item_idx: int = -1,
    normalize_negative_to_abs: bool = True,
) -> Tuple[np.ndarray, List[str], List[str]]:
    """
    Structured-array equivalent of ``fn_build_direct_cash_batch_entries``.

    Returns ``(entries, asset_labels, period_col_labels)`` — same triple
    expected by ``fn_flush_matrix_entries``.
    """
    return fn_build_structured_entries_from_source(
        source_df=source_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        debit_acct_idx=debit_acct_idx,
        credit_acct_idx=credit_acct_idx,
        period_to_idx=period_to_idx,
        is_line_item_idx=is_line_item_idx,
        cf_line_item_idx=cf_line_item_idx,
        normalize_negative_to_abs=normalize_negative_to_abs,
    )


def fn_prepare_direct_cash_matrix_batch(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    debit_account: str,
    credit_account: str,
    cashflow_line_item: str,
    line_item_name: str,
    reference_prefix: str,
    index_maps: Dict[str, Any],
    normalize_negative_to_abs: bool = True,
    income_statement_line_item: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build a batch dict for ``fn_flush_matrix_entries_multi``.

    Performs the same index resolution and entry construction as the fast
    path inside ``fn_process_direct_cash_capex_line_item_entries`` but
    returns the batch dict instead of flushing immediately — enabling
    callers to accumulate many batches and flush once.

    Returns ``None`` when no non-zero entries exist.
    """
    account_to_idx = index_maps["account_to_idx"]
    period_to_idx = index_maps["period_to_idx"]

    dr_idx = account_to_idx.get(debit_account, -1)
    cr_idx = account_to_idx.get(credit_account, -1)
    if dr_idx < 0 or cr_idx < 0:
        return None

    cf_row_map = index_maps.get("cf_row_map") or {}
    is_row_map = index_maps.get("is_row_map") or {}
    cf_li_idx = cf_row_map.get(cashflow_line_item, -1) if cashflow_line_item else -1
    is_li_idx = (
        is_row_map.get(income_statement_line_item, -1)
        if income_statement_line_item
        else -1
    )

    entries, asset_labels, period_col_labels = fn_build_direct_cash_matrix_entries(
        source_df=source_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        debit_acct_idx=dr_idx,
        credit_acct_idx=cr_idx,
        period_to_idx=period_to_idx,
        cf_line_item_idx=cf_li_idx,
        is_line_item_idx=is_li_idx,
        normalize_negative_to_abs=normalize_negative_to_abs,
    )

    if len(entries) == 0:
        return None

    return {
        "entries": entries,
        "reference_prefix": reference_prefix,
        "line_item_name": line_item_name,
        "asset_labels": asset_labels,
        "period_col_labels": period_col_labels,
    }


def fn_process_direct_cash_capex_line_item_entries(
    source_df: pd.DataFrame,
    col_to_period: Dict[Any, str],
    asset_unique_identifier: Optional[pd.Series],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    debit_account: str,
    credit_account: str,
    cashflow_line_item: str,
    line_item_name: str,
    reference_prefix: str,
    normalize_negative_to_abs: bool = True,
    income_statement_line_item: Optional[str] = None,
    index_maps: Optional[Dict[str, Any]] = None,
    interparty_cash_name: Optional[str] = None,
    type_aware_is_posting: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Process direct cash capex entries with batched postings.

    When *index_maps* is supplied, the fast structured-array path is used.
    """
    if debit_account not in accounts or credit_account not in accounts:
        print(
            "fn_process_direct_cash_capex_line_item_entries: missing required accounts: "
            f"{[acct for acct in [debit_account, credit_account] if acct not in accounts]}"
        )
        return accounts, journal, financial_statements

    # ------------------------------------------------------------------
    # Fast path: matrix-based flush
    # ------------------------------------------------------------------
    if index_maps is not None:
        account_to_idx = index_maps["account_to_idx"]
        period_to_idx = index_maps["period_to_idx"]
        dr_idx = account_to_idx.get(debit_account, -1)
        cr_idx = account_to_idx.get(credit_account, -1)
        if dr_idx < 0 or cr_idx < 0:
            return accounts, journal, financial_statements

        cf_row_map = index_maps.get("cf_row_map") or {}
        is_row_map = index_maps.get("is_row_map") or {}
        cf_li_idx = cf_row_map.get(cashflow_line_item, -1) if cashflow_line_item else -1
        is_li_idx = is_row_map.get(income_statement_line_item, -1) if income_statement_line_item else -1

        entries, asset_labels, period_col_labels = fn_build_direct_cash_matrix_entries(
            source_df=source_df,
            col_to_period=col_to_period,
            asset_unique_identifier=asset_unique_identifier,
            debit_acct_idx=dr_idx,
            credit_acct_idx=cr_idx,
            period_to_idx=period_to_idx,
            cf_line_item_idx=cf_li_idx,
            is_line_item_idx=is_li_idx,
            normalize_negative_to_abs=normalize_negative_to_abs,
        )
        if len(entries) == 0:
            return accounts, journal, financial_statements

        return fn_flush_matrix_entries(
            entries=entries,
            accounts=accounts,
            journal=journal,
            financial_statements=financial_statements,
            account_names_dict=account_names_dict,
            index_maps=index_maps,
            reference_prefix=reference_prefix,
            line_item_name=line_item_name,
            asset_labels=asset_labels,
            period_col_labels=period_col_labels,
            interparty_cash_name=interparty_cash_name,
            type_aware_is_posting=type_aware_is_posting,
        )

    # ------------------------------------------------------------------
    # Legacy path: dict-based batch entries
    # ------------------------------------------------------------------
    batch_entries = fn_build_direct_cash_batch_entries(
        source_df=source_df,
        col_to_period=col_to_period,
        asset_unique_identifier=asset_unique_identifier,
        debit_account=debit_account,
        credit_account=credit_account,
        cashflow_line_item=cashflow_line_item,
        line_item_name=line_item_name,
        reference_prefix=reference_prefix,
        normalize_negative_to_abs=normalize_negative_to_abs,
        income_statement_line_item=income_statement_line_item,
    )

    if not batch_entries:
        return accounts, journal, financial_statements

    return fn_flush_batch_entries(
        batch_entries=batch_entries,
        accounts=accounts,
        journal=journal,
        financial_statements=financial_statements,
        account_names_dict=account_names_dict,
        interparty_cash_name=interparty_cash_name,
        type_aware_is_posting=type_aware_is_posting,
    )


def fn_get_row_by_compatible_index(
    source_df: pd.DataFrame,
    row_key: Any,
) -> pd.Series:
    """
    Resolve and return a row using compatible key types (e.g., int <-> str).
    """
    if source_df is None or source_df.empty:
        return pd.Series(dtype="float64")

    candidates: List[Any] = [row_key]

    row_key_str = str(row_key).strip()
    if row_key_str not in {str(candidate).strip() for candidate in candidates}:
        candidates.append(row_key_str)

    try:
        row_key_float = float(row_key_str)
        if row_key_float.is_integer():
            row_key_int = int(row_key_float)
            if row_key_int not in candidates:
                candidates.append(row_key_int)
            row_key_int_str = str(row_key_int)
            if row_key_int_str not in candidates:
                candidates.append(row_key_int_str)
    except Exception:
        pass

    for candidate in candidates:
        if candidate in source_df.index:
            return source_df.loc[candidate]

    return pd.Series(dtype="float64")
