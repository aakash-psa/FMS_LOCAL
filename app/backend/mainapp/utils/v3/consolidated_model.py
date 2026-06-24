import traceback
from typing import Any, Dict, List, Tuple, Optional, Union
import time
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import pickle
import tempfile
import atexit

import os
import numpy as np
import pandas as pd
import mainapp.utils.v3.consolidation.project_conso_landco as landco_consolidation_wrapper
import mainapp.utils.v3.consolidation.project_conso_devco as devco_consolidation_wrapper
import mainapp.utils.v3.consolidation.project_conso_assetco as assetco_consolidation_wrapper
from mainapp.utils.v3.consolidation.financial_statement_trace_categories import (
    fn_add_trace_hierarchy_levels,
)
import json
from mainapp.utils.v3.consolidation.project_conso_utils import (
    fn_create_timing_context,
    fn_record_timing,
    fn_finalize_timing_summary,
    fn_extract_assumptions,
    fn_extract_synthetic_asset_ids_from_mastersheet,
    fn_trace_payload_to_dataframe,
    fn_trace_dataframe_to_payload,
    fn_concatenate_financial_statement_trace_dataframes,
    fn_build_consolidated_financial_statement_trace_delta,
    fn_append_financial_statement_trace_row,
    fn_build_financial_statement_trace_dataframe,
    fn_add_unique_id_to_trace_df,
    FS_TRACE_ROWS_KEY,
)

_ENABLE_FINANCIAL_STATEMENT_TRACE = False
_TRACE_ENABLE_PAYLOAD_KEY = "_enable_financial_statement_trace"
_LIGHTWEIGHT_ENTITY_OUTPUT_PAYLOAD_KEY = "_lightweight_entity_output"

_ENTITY_PROCESS_POOL: Optional[ProcessPoolExecutor] = None


def _shutdown_entity_process_pool() -> None:
    global _ENTITY_PROCESS_POOL
    if _ENTITY_PROCESS_POOL is not None:
        try:
            _ENTITY_PROCESS_POOL.shutdown(wait=True)
        except Exception:
            pass
        _ENTITY_PROCESS_POOL = None


def _get_entity_process_pool(max_workers: int) -> ProcessPoolExecutor:
    global _ENTITY_PROCESS_POOL
    if _ENTITY_PROCESS_POOL is None:
        _ENTITY_PROCESS_POOL = ProcessPoolExecutor(max_workers=max_workers)
    return _ENTITY_PROCESS_POOL


atexit.register(_shutdown_entity_process_pool)

# ---------------------------------------------------------------------------
# Consolidated Income Statement Proforma
# ---------------------------------------------------------------------------
# Keys are major sections.  Sub-keys are category headings (empty string means
# no sub-header).  Lists contain line-item labels to pull from entity IS
# DataFrames.  An empty list marks a *calculated subtotal* row whose name
# matches the sub-key.
# ---------------------------------------------------------------------------
_CONSOLIDATED_IS_PROFORMA: Dict[str, Dict[str, List[str]]] = {
    "REVENUE": {
        "Core Operating Revenue": [
            "Land Sales Revenue",
            "Asset Sales Revenue",
            "Land Lease Revenue",
            "Lease Revenue - Base Rent",
            "Lease Revenue - Turnover Rent",
            "Lease Revenue - Service Charge",
            "Hospitality - Room Revenue",
            "Hospitality - F&B Revenue",
            "Hospitality - OOD Revenue",
            "Hospitality - Other Operating Income",
        ],
        "Total Revenue": [],
    },
    "COST OF SALES": {
        "": [
            "Cost of Land Sales",
            "Cost of Asset Sales",
            "Cost of Lease Revenue",
        ],
        "Operating Costs": [
            "Land Lease Operating Expenses",
            "Utilities Expense",
            "Facility Management Expense",
            "Sinking Fund Expense",
            "Maintenance Capex Expense",
            "Void Period Expense",
            "Parking Expense",
            "Asset Management Expense",
        ],
        "Gross Profit": [],
    },
    "OPERATING EXPENSES": {
        "Administrative & Corporate Overheads": [
            "Administration Expense",
            "Office Rent and Utilities Expense",
            "IT Services Expense",
            "Professional Services Expense",
            "Insurance Expense",
            "DLP Insurance Expense",
        ],
        "Sales, Marketing & Leasing": [
            "Sales and Marketing Expense",
            "Marketing Overhead Expense",
            "Sales Cost Overhead Expense",
            "Leasing Commissions Expense",
        ],
        "Personnel Costs": [
            "Salaries Expense",
        ],
        "Asset & Community Management": [
            "Community Operations Recovery",            
            "Community Operations Expense",
        ],
        "Hospitality - Departmental Expenses": [
            "Hospitality Departmental Expenses - Room",
            "Hospitality Departmental Expenses - F&B",
            "Hospitality Departmental Expenses - OOD",
            "Hospitality Departmental Expenses - Other",
        ],
        "Hospitality - Undistributed Expenses": [
            "Hospitality Undistributed Expenses - Admin",
            "Hospitality Undistributed Expenses - Sales & Marketing",
            "Hospitality Undistributed Expenses - IT",
            "Hospitality Undistributed Expenses - Utilities",
        ],
        "Other Operating Expenses": [
            "Pre Operating Expenses",
            "Bad Debt Expense",
            "Additional Overhead Expense",
        ],
        "EBITDA": [],
    },
    "DEPRECIATION & AMORTIZATION": {
        "": [
            "Depreciation Expense",
        ],
        "EBIT": [],
    },
    "FINANCE COSTS": {
        "": [
            "Interest Expense - Term Loan",
            "Interest Expense - Revolver",
            "Interest Expense - Other",
            "Debt Fees Expense",
        ],
        "EBT": [],
    },
    "NON-OPERATING ITEMS": {
        "Non-Operating Expenses": [
            "Other Operating Expense",
            "Loss on Asset Disposal",
            "Hospitality Non-Operating Expenses",
        ],
        "Non-Operating Income": [
            "Parking Revenue",
            "Government Subsidies Income",
            "PA Recovery Income",
            "Other Operating Income",
            "Gain on Asset Disposal",
            "Hospitality Non-Operating Income",
            "Share of Profit from JV",
        ],
        "Net Income": [],
    },
}


# ---------------------------------------------------------------------------
# Helper: post-process consolidated Balance Sheet
# ---------------------------------------------------------------------------
_CWIP_MERGE_LABELS = {"CWIP - Serviced Land", "CWIP - Developed Units", "Serviced Land Assets"}

_PROPERTY_INVESTMENT_LABELS = {"Land Assets", "CWIP", "Investment Property"}

_INTERPARTY_ACCOUNT_ROW_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("Interparty Accounts Receivable", "Closing Balance", "ar"),
    ("Interparty Unearned Revenue", "Closing Balance", "ur"),
    ("Interparty Revenue Elimination", "Debit", "revenue"),
    ("Interparty COGS Elimination", "Debit", "cogs"),
    ("Interparty Cash Elimination", "Debit", "cash"),
)


def _extract_numeric_account_row(
    payload: Dict[str, Any],
    row_name: str,
    dataframe_cache: Dict[int, pd.DataFrame],
) -> Optional[pd.Series]:
    """Extract a numeric account row while reusing reconstructed DataFrames."""
    payload_key = id(payload)
    acct_df = dataframe_cache.get(payload_key)
    if acct_df is None:
        acct_df = _payload_to_dataframe(payload)
        dataframe_cache[payload_key] = acct_df

    if row_name not in acct_df.index:
        return None

    row = acct_df.loc[row_name]
    if isinstance(row, pd.DataFrame):
        return row.apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=0)
    return pd.to_numeric(row, errors="coerce").fillna(0.0)


def _extract_interparty_account_series(
    model_results: List[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """Extract all interparty account series in one cached pass."""
    totals: Dict[str, pd.Series] = {
        "ar": pd.Series(dtype=float),
        "ur": pd.Series(dtype=float),
        "revenue": pd.Series(dtype=float),
        "cogs": pd.Series(dtype=float),
        "cash": pd.Series(dtype=float),
    }
    dataframe_cache: Dict[int, pd.DataFrame] = {}

    for result in model_results:
        accounts = result.get("accounts", {})
        for account_name, row_name, target_key in _INTERPARTY_ACCOUNT_ROW_SPECS:
            payload = accounts.get(account_name)
            if payload is None:
                continue

            row = _extract_numeric_account_row(payload, row_name, dataframe_cache)
            if row is None:
                continue

            if totals[target_key].empty:
                totals[target_key] = row.copy()
            else:
                totals[target_key] = totals[target_key].add(row, fill_value=0.0)

    return totals


def _extract_interparty_netting(
    model_results: List[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """
    Extract Interparty Accounts Receivable and Interparty Unearned Revenue
    balance rows from entity results.

    Returns ``{"ar": Series, "ur": Series}`` indexed by period-end dates.
    AR balance is used to net AR vs AP; UR balance to net Advances vs UR.
    """
    account_series = _extract_interparty_account_series(model_results)
    return {
        "ar": account_series["ar"],
        "ur": account_series["ur"],
    }


def _align_balance_to_columns(
    balance: pd.Series, columns: list,
) -> pd.Series:
    """Align an account balance series to target DataFrame columns.

    Works for both monthly columns (date strings) and annual columns
    (year strings) by falling back to year-end mapping when direct
    reindex yields all zeros.
    """
    if balance.empty:
        return pd.Series(0.0, index=columns)
    aligned = balance.reindex(columns, fill_value=0.0).fillna(0.0)
    if not (aligned == 0.0).all() or (balance == 0.0).all():
        return aligned
    # Fallback: map by year — take last value per year (year-end balance)
    try:
        bal_dates = pd.to_datetime(balance.index, errors="coerce")
        year_map: Dict[str, float] = {}
        for i, dt in enumerate(bal_dates):
            if pd.notna(dt):
                year_map[str(dt.year)] = float(balance.iloc[i])
        return pd.Series(
            [year_map.get(str(c), 0.0) for c in columns], index=columns,
        )
    except Exception:
        return aligned


def _extract_interparty_is_elimination(
    model_results: List[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """
    Extract per-period interparty revenue and COGS elimination amounts
    from entity tracking accounts.

    Returns ``{"revenue": Series, "cogs": Series}`` with per-period
    Debit-row values (flow amounts, not cumulative).
    """
    account_series = _extract_interparty_account_series(model_results)
    return {
        "revenue": account_series["revenue"],
        "cogs": account_series["cogs"],
    }


def _extract_interparty_cf_elimination(
    model_results: List[Dict[str, Any]],
) -> pd.Series:
    """
    Extract per-period interparty cash collection amounts from entity
    tracking accounts.  Returns a Series of Debit-row values.
    """
    return _extract_interparty_account_series(model_results)["cash"]


import re as _re

_ASSET_DESC_PATTERN = _re.compile(r"\bAsset\s+(\d+)\b", _re.IGNORECASE)
_IP_REV_REF_PATTERN = _re.compile(r"^([A-Z0-9-]+)-IPRE-(\d+)-")
_IP_COGS_REF_PATTERN = _re.compile(r"^([A-Z0-9-]+)-IPCE-(\d+)-")
_ASSET_REF_PATTERNS = (
    _re.compile(r"-UG-(\d+)$"),
    _re.compile(r"-(\d+)-\d{4}-\d{2}-\d{2}$"),
    _re.compile(r"-(\d+)-\d{4}$"),
)


@lru_cache(maxsize=2048)
def _normalize_period_label_cached(raw_value: str) -> str:
    """Normalize period labels once and reuse across model calls."""
    if not raw_value:
        return ""
    try:
        parsed = pd.to_datetime(raw_value, errors="coerce")
        if pd.notna(parsed):
            return pd.Timestamp(parsed).strftime("%Y-%m-%d")
    except Exception:
        pass
    return raw_value


def _normalize_period_label(period_value: Any) -> str:
    raw = str(period_value or "").strip()
    return _normalize_period_label_cached(raw)


def _collect_asset_period_amounts(
    asset_idx: pd.Series,
    periods: pd.Series,
    amounts: pd.Series,
) -> pd.Series:
    """Aggregate asset-period amounts with pandas groupby for speed."""
    if asset_idx.empty:
        return pd.Series(dtype=float)

    collected = pd.DataFrame(
        {
            "asset_idx_col": pd.to_numeric(asset_idx, errors="coerce"),
            "period_norm": periods,
            "amount": pd.to_numeric(amounts, errors="coerce").fillna(0.0),
        }
    )
    if collected.empty:
        return pd.Series(dtype=float)

    collected["period_norm"] = collected["period_norm"].map(_normalize_period_label)
    valid_mask = (
        collected["asset_idx_col"].notna()
        & collected["period_norm"].astype(str).ne("")
    )
    if not valid_mask.any():
        return pd.Series(dtype=float)

    return (
        collected.loc[valid_mask]
        .groupby(["asset_idx_col", "period_norm"], sort=False)["amount"]
        .sum()
    )


def _extract_asset_idx_from_journal_entry(
    reference: str,
    description: str,
) -> Optional[int]:
    """Best-effort extraction of numeric asset index from journal metadata."""
    m = _ASSET_DESC_PATTERN.search(description or "")
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    ref = reference or ""
    for pat in _ASSET_REF_PATTERNS:
        m = pat.search(ref)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                continue
    return None


def _sort_period_labels(labels: List[str]) -> List[str]:
    """Sort period labels chronologically when parseable, else lexicographically."""
    if not labels:
        return []
    try:
        idx = pd.Index(labels)
        parsed = pd.to_datetime(idx, errors="coerce")
        if parsed.notna().any():
            rows = list(zip(idx.tolist(), parsed.tolist()))
            rows.sort(
                key=lambda t: (
                    pd.isna(t[1]),
                    int(t[1].value) if pd.notna(t[1]) else 0,
                    str(t[0]),
                )
            )
            return [str(t[0]) for t in rows]
    except Exception:
        pass
    return sorted([str(x) for x in labels])


def _nested_period_dict_to_frame(
    period_map: Dict[int, Dict[str, float]],
    asset_index: List[int],
    period_columns: List[str],
) -> pd.DataFrame:
    """Convert ``asset -> period -> amount`` dicts into a dense float DataFrame."""
    if not asset_index or not period_columns:
        return pd.DataFrame(0.0, index=asset_index, columns=period_columns)
    if not period_map:
        return pd.DataFrame(0.0, index=asset_index, columns=period_columns)

    frame = pd.DataFrame.from_dict(period_map, orient="index")
    if frame.empty:
        return pd.DataFrame(0.0, index=asset_index, columns=period_columns)

    return (
        frame.reindex(index=asset_index, columns=period_columns, fill_value=0.0)
        .fillna(0.0)
        .astype(float, copy=False)
    )


def _stack_frames_preserving_rows(
    frames: List[pd.DataFrame],
    columns: List[Any],
) -> pd.DataFrame:
    """Stack presentable statement fragments without pandas concat dtype warnings."""
    materialized = [frame for frame in frames if frame is not None and not frame.empty]
    if not materialized:
        return pd.DataFrame(columns=columns)
    if len(materialized) == 1:
        return materialized[0].copy()

    output_index: List[Any] = []
    output_rows: List[List[Any]] = []
    for frame in materialized:
        output_index.extend(frame.index.tolist())
        output_rows.extend(frame.to_numpy(dtype=object, copy=False).tolist())

    return pd.DataFrame(output_rows, index=output_index, columns=columns, dtype=object)


def _compute_unrealized_gains_adjustments(
    landco_result: Optional[Dict[str, Any]],
    devco_result: Optional[Dict[str, Any]],
    assetco_result: Optional[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
) -> pd.Series:
    """Compute per-period UG adjustments as direct signed values.

    LandCo -> DevCo (per asset, then pooled):
      UG[t] = -(SLA_close[t] + CWIP_DU_close[t]) * margin_lc *
              (cum Dr SLA[t] / (cum Dr SLA[t] + cum Dr CWIP_DU[t]))

      margin_lc = (sum_T interparty Land Sales Revenue - sum_T interparty Cost of Land Sales)
                  / sum_T interparty Land Sales Revenue

    DevCo -> AssetCo (per asset, then pooled):
            UG[t] = UG[t-1] - (DD5[t] + DD9[t])

            DD5[t] = Land Sales Revenue[t] - Cost of Land Sales[t]
            DD9[t] = Asset Sales Revenue[t] - Cost of Asset Sales[t]

            Mask:
                if Investment Property Closing[t] == 0 then UG[t] = 0

    Notes:
      - Returned values are direct adjustment values (raw sign preserved).
"""
    _TOL = 1e-9

    _period_cache: Dict[str, str] = {}

    def _normalize_period_label(period_value: Any) -> str:
        raw = str(period_value or "").strip()
        if not raw:
            return ""
        cached = _period_cache.get(raw)
        if cached is not None:
            return cached
        try:
            parsed = pd.to_datetime(raw, errors="coerce")
            if pd.notna(parsed):
                normalized = pd.Timestamp(parsed).strftime("%Y-%m-%d")
                _period_cache[raw] = normalized
                return normalized
        except Exception:
            pass
        _period_cache[raw] = raw
        return raw

    def _to_pivot(asset_idx_s: pd.Series, period_s: pd.Series, amount_s: pd.Series) -> pd.DataFrame:
        """Groupby-sum amounts by (asset_idx, period_norm); returns pivot DataFrame."""
        valid = asset_idx_s.notna()
        if not valid.any():
            return pd.DataFrame(dtype=float)
        temp = pd.DataFrame({
            "a": asset_idx_s[valid].astype(int),
            "p": period_s[valid].astype(str),
            "v": amount_s[valid].astype(float),
        })
        temp = temp[temp["p"].ne("")]
        if temp.empty:
            return pd.DataFrame(dtype=float)
        return temp.groupby(["a", "p"])["v"].sum().unstack(fill_value=0.0)

    _UG_ASSET_REF_PATTERNS = (
        _re.compile(r"-(\d+)-\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?$") ,
        _re.compile(r"-(\d+)-\d{4}$"),
    )

    def _extract_first_numeric_group(
        text: pd.Series,
        patterns: Tuple[Any, ...],
    ) -> pd.Series:
        result = pd.Series(pd.NA, index=text.index, dtype="Int64")
        if text.empty:
            return result

        normalized_text = text.fillna("").astype(str)
        for pattern in patterns:
            extracted = pd.to_numeric(
                normalized_text.str.extract(pattern, expand=False),
                errors="coerce",
            ).astype("Int64")
            result = result.fillna(extracted)

        return result

    def _prepare_journal_frame(result: Optional[Dict[str, Any]]) -> pd.DataFrame:
        if not isinstance(result, dict):
            return pd.DataFrame()

        journal = result.get("journal", [])
        if not journal:
            return pd.DataFrame()

        journal_df = pd.DataFrame(journal)
        if journal_df.empty:
            return journal_df

        for col_name in [
            "period",
            "amount",
            "reference",
            "description",
            "debit_account",
            "credit_account",
            "asset_no",
        ]:
            if col_name not in journal_df.columns:
                journal_df[col_name] = None

        period_raw = journal_df["period"].fillna("").astype(str).str.strip()
        period_norm = period_raw.map(_normalize_period_label)

        return journal_df.assign(
            period_norm=period_norm,
            amount_num=pd.to_numeric(journal_df["amount"], errors="coerce").fillna(0.0).astype(float),
            reference_str=journal_df["reference"].fillna("").astype(str),
            description_str=journal_df["description"].fillna("").astype(str),
            debit_account_str=journal_df["debit_account"].fillna("").astype(str),
            credit_account_str=journal_df["credit_account"].fillna("").astype(str),
            asset_no_str=journal_df["asset_no"].fillna("").astype(str),
        )

    def _compute_asset_index_columns(
        journal_df: pd.DataFrame,
        include_reference_first: bool = False,
    ) -> Dict[str, pd.Series]:
        empty_idx = pd.Series(pd.NA, index=journal_df.index, dtype="Int64")
        if journal_df.empty:
            output = {"generic": empty_idx, "ug": empty_idx}
            if include_reference_first:
                output["reference_first"] = empty_idx
            return output

        description_idx = _extract_first_numeric_group(
            journal_df["description_str"],
            (_ASSET_DESC_PATTERN,),
        )
        reference_idx = _extract_first_numeric_group(
            journal_df["reference_str"],
            _ASSET_REF_PATTERNS,
        )
        generic_idx = description_idx.fillna(reference_idx)

        ug_reference_idx = _extract_first_numeric_group(
            journal_df["reference_str"],
            _UG_ASSET_REF_PATTERNS,
        )
        ug_idx = generic_idx.fillna(ug_reference_idx)

        output = {
            "generic": generic_idx,
            "ug": ug_idx,
        }
        if include_reference_first:
            output["reference_first"] = ug_reference_idx.fillna(generic_idx)
        return output

    def _extract_interparty_asset_idx(
        reference: pd.Series,
        pattern: Any,
        entity_prefix: str,
    ) -> pd.Series:
        extracted = reference.str.extract(pattern.pattern, expand=True)
        if extracted.empty or extracted.shape[1] < 2:
            return pd.Series(pd.NA, index=reference.index, dtype="Int64")

        prefix_match = extracted.iloc[:, 0].fillna("").astype(str).str.startswith(entity_prefix)
        asset_idx = pd.to_numeric(extracted.iloc[:, 1], errors="coerce").astype("Int64")
        return asset_idx.where(prefix_match, pd.NA)

    def _normalize_uid(uid_value: Any) -> Optional[str]:
        if uid_value is None:
            return None
        uid_text = str(uid_value).strip()
        if uid_text == "" or uid_text.lower() in {"none", "nan", "nat"}:
            return None
        return uid_text

    def _coerce_int_index(index_value: Any) -> Optional[int]:
        if index_value is None:
            return None
        try:
            if isinstance(index_value, (int, np.integer)):
                return int(index_value)
            parsed = float(str(index_value).strip())
            if np.isfinite(parsed) and float(parsed).is_integer():
                return int(parsed)
        except Exception:
            return None
        return None

    _project_uid_to_idx: Dict[str, int] = {}
    _assetco_idx_to_project_idx: Dict[int, int] = {}
    if isinstance(payload, dict):
        try:
            _landco_payload = payload.get("landco", {})
            if isinstance(_landco_payload, dict):
                _landco_asset_assumptions = _landco_payload.get("asset_assumptions", {})
                if isinstance(_landco_asset_assumptions, dict):
                    _project_uids = fn_extract_assumptions(
                        _landco_asset_assumptions,
                        "ProjectDetails",
                        "asset_unique_identifier",
                    )
                    if isinstance(_project_uids, pd.Series) and not _project_uids.empty:
                        for _project_idx_raw, _project_uid_raw in _project_uids.items():
                            _project_idx = _coerce_int_index(_project_idx_raw)
                            _project_uid = _normalize_uid(_project_uid_raw)
                            if _project_idx is None or _project_uid is None:
                                continue
                            _project_uid_to_idx.setdefault(_project_uid, _project_idx)

            _assetco_items = payload.get("assetco_consolidated", [])
            if isinstance(_assetco_items, list) and _project_uid_to_idx:
                for _assetco_idx, _asset_item in enumerate(_assetco_items):
                    if not isinstance(_asset_item, dict):
                        continue

                    _output_json = _asset_item.get("output_json", {})
                    if not isinstance(_output_json, dict):
                        _output_json = {}

                    _assetco_inputs = _output_json.get("assetco_inputs", {})
                    if not isinstance(_assetco_inputs, dict):
                        _assetco_inputs = {}

                    _asset_uid = _normalize_uid(_assetco_inputs.get("asset_unique_id"))
                    if _asset_uid is None:
                        _asset_uid = _normalize_uid(_asset_item.get("asset_unique_id"))
                    if _asset_uid is None:
                        continue

                    _project_idx = _project_uid_to_idx.get(_asset_uid)
                    if _project_idx is None:
                        continue

                    _assetco_idx_to_project_idx[_assetco_idx] = _project_idx
        except Exception:
            _project_uid_to_idx = {}
            _assetco_idx_to_project_idx = {}

    def _collect_horizon_periods(results: List[Optional[Dict[str, Any]]]) -> List[str]:
        periods: set = set()
        for result in results:
            if not isinstance(result, dict):
                continue

            monthly_dfs = result.get("monthly_dfs", {})
            if isinstance(monthly_dfs, dict):
                preferred_entries: List[Any] = []
                for sheet_name in ["Balance Sheet", "Income Statement", "Cashflow Statement"]:
                    entry = monthly_dfs.get(sheet_name)
                    if entry is not None:
                        preferred_entries.append(entry)

                entries = preferred_entries if preferred_entries else list(monthly_dfs.values())

                for entry in entries:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    entry_payload = entry[1]
                    if not isinstance(entry_payload, dict):
                        continue
                    for col in entry_payload.get("columns", []):
                        period = _normalize_period_label(col)
                        if period:
                            periods.add(period)

            for je in result.get("journal", []):
                period = _normalize_period_label(je.get("period", ""))
                if period:
                    periods.add(period)

        return _sort_period_labels(list(periods))

    lc_ip_rev_piv          = pd.DataFrame(dtype=float)
    lc_ip_cogs_piv         = pd.DataFrame(dtype=float)
    dc_ip_rev_piv          = pd.DataFrame(dtype=float)
    dc_ip_cogs_piv         = pd.DataFrame(dtype=float)
    dc_land_rev_ug_piv     = pd.DataFrame(dtype=float)
    dc_land_cogs_ug_piv    = pd.DataFrame(dtype=float)
    dc_asset_rev_ug_piv    = pd.DataFrame(dtype=float)
    dc_asset_cogs_ug_piv   = pd.DataFrame(dtype=float)
    dc_sla_debit_piv       = pd.DataFrame(dtype=float)
    dc_sla_credit_piv      = pd.DataFrame(dtype=float)
    dc_cwip_debit_piv      = pd.DataFrame(dtype=float)
    dc_cwip_credit_piv     = pd.DataFrame(dtype=float)
    ac_ip_debit_piv        = pd.DataFrame(dtype=float)
    ac_ip_credit_piv       = pd.DataFrame(dtype=float)

    landco_journal_df = _prepare_journal_frame(landco_result)
    if not landco_journal_df.empty:
        landco_valid_posting_mask = (
            landco_journal_df["period_norm"].ne("")
            & landco_journal_df["amount_num"].abs().gt(_TOL)
            & ~landco_journal_df["reference_str"].str.endswith("-IE")
        )
        landco_asset_indices = _compute_asset_index_columns(landco_journal_df)
        landco_ip_rev_idx = _extract_interparty_asset_idx(
            landco_journal_df["reference_str"], _IP_REV_REF_PATTERN, "LC-",
        )
        landco_ip_cogs_idx = _extract_interparty_asset_idx(
            landco_journal_df["reference_str"], _IP_COGS_REF_PATTERN, "LC-",
        )

        landco_rev_mask = landco_valid_posting_mask & landco_ip_rev_idx.notna()
        lc_ip_rev_piv = _to_pivot(
            landco_ip_rev_idx.loc[landco_rev_mask],
            landco_journal_df.loc[landco_rev_mask, "period_norm"],
            landco_journal_df.loc[landco_rev_mask, "amount_num"],
        )

        landco_cogs_mask = landco_valid_posting_mask & landco_ip_cogs_idx.notna()
        lc_ip_cogs_piv = _to_pivot(
            landco_ip_cogs_idx.loc[landco_cogs_mask],
            landco_journal_df.loc[landco_cogs_mask, "period_norm"],
            landco_journal_df.loc[landco_cogs_mask, "amount_num"],
        )

        landco_ug_asset_idx = landco_asset_indices["ug"]
        landco_ug_rev_mask = (
            landco_journal_df["period_norm"].ne("")
            & landco_ug_asset_idx.notna()
            & landco_journal_df["credit_account_str"].eq("Land Sales Revenue")
        )
        dc_land_rev_ug_piv = _to_pivot(
            landco_ug_asset_idx.loc[landco_ug_rev_mask],
            landco_journal_df.loc[landco_ug_rev_mask, "period_norm"],
            landco_journal_df.loc[landco_ug_rev_mask, "amount_num"],
        )

        landco_ug_cogs_mask = (
            landco_journal_df["period_norm"].ne("")
            & landco_ug_asset_idx.notna()
            & landco_journal_df["debit_account_str"].eq("Cost of Land Sales")
        )
        dc_land_cogs_ug_piv = _to_pivot(
            landco_ug_asset_idx.loc[landco_ug_cogs_mask],
            landco_journal_df.loc[landco_ug_cogs_mask, "period_norm"],
            landco_journal_df.loc[landco_ug_cogs_mask, "amount_num"],
        )

    devco_journal_df = _prepare_journal_frame(devco_result)
    if not devco_journal_df.empty:
        devco_valid_posting_mask = (
            devco_journal_df["period_norm"].ne("")
            & devco_journal_df["amount_num"].abs().gt(_TOL)
            & ~devco_journal_df["reference_str"].str.endswith("-IE")
        )
        devco_asset_indices = _compute_asset_index_columns(devco_journal_df)
        devco_asset_idx = devco_asset_indices["generic"]

        devco_sla_debit_mask = (
            devco_valid_posting_mask
            & devco_asset_idx.notna()
            & devco_journal_df["debit_account_str"].eq("Serviced Land Assets")
        )
        dc_sla_debit_piv = _to_pivot(
            devco_asset_idx.loc[devco_sla_debit_mask],
            devco_journal_df.loc[devco_sla_debit_mask, "period_norm"],
            devco_journal_df.loc[devco_sla_debit_mask, "amount_num"],
        )

        devco_sla_credit_mask = (
            devco_valid_posting_mask
            & devco_asset_idx.notna()
            & devco_journal_df["credit_account_str"].eq("Serviced Land Assets")
        )
        dc_sla_credit_piv = _to_pivot(
            devco_asset_idx.loc[devco_sla_credit_mask],
            devco_journal_df.loc[devco_sla_credit_mask, "period_norm"],
            devco_journal_df.loc[devco_sla_credit_mask, "amount_num"],
        )

        devco_cwip_debit_mask = (
            devco_valid_posting_mask
            & devco_asset_idx.notna()
            & devco_journal_df["debit_account_str"].eq("CWIP - Developed Units")
        )
        dc_cwip_debit_piv = _to_pivot(
            devco_asset_idx.loc[devco_cwip_debit_mask],
            devco_journal_df.loc[devco_cwip_debit_mask, "period_norm"],
            devco_journal_df.loc[devco_cwip_debit_mask, "amount_num"],
        )

        devco_cwip_credit_mask = (
            devco_valid_posting_mask
            & devco_asset_idx.notna()
            & devco_journal_df["credit_account_str"].eq("CWIP - Developed Units")
        )
        dc_cwip_credit_piv = _to_pivot(
            devco_asset_idx.loc[devco_cwip_credit_mask],
            devco_journal_df.loc[devco_cwip_credit_mask, "period_norm"],
            devco_journal_df.loc[devco_cwip_credit_mask, "amount_num"],
        )

        devco_ip_rev_idx = _extract_interparty_asset_idx(
            devco_journal_df["reference_str"], _IP_REV_REF_PATTERN, "DC-",
        )
        devco_ip_cogs_idx = _extract_interparty_asset_idx(
            devco_journal_df["reference_str"], _IP_COGS_REF_PATTERN, "DC-",
        )

        devco_rev_mask = devco_valid_posting_mask & devco_ip_rev_idx.notna()
        dc_ip_rev_piv = _to_pivot(
            devco_ip_rev_idx.loc[devco_rev_mask],
            devco_journal_df.loc[devco_rev_mask, "period_norm"],
            devco_journal_df.loc[devco_rev_mask, "amount_num"],
        )

        devco_cogs_mask = devco_valid_posting_mask & devco_ip_cogs_idx.notna()
        dc_ip_cogs_piv = _to_pivot(
            devco_ip_cogs_idx.loc[devco_cogs_mask],
            devco_journal_df.loc[devco_cogs_mask, "period_norm"],
            devco_journal_df.loc[devco_cogs_mask, "amount_num"],
        )

        devco_ug_asset_idx = devco_asset_indices["ug"]
        devco_ug_rev_mask = (
            devco_journal_df["period_norm"].ne("")
            & devco_ug_asset_idx.notna()
            & devco_journal_df["credit_account_str"].eq("Developed Unit Sales Revenue")
        )
        dc_asset_rev_ug_piv = _to_pivot(
            devco_ug_asset_idx.loc[devco_ug_rev_mask],
            devco_journal_df.loc[devco_ug_rev_mask, "period_norm"],
            devco_journal_df.loc[devco_ug_rev_mask, "amount_num"],
        )

        devco_ug_cogs_mask = (
            devco_journal_df["period_norm"].ne("")
            & devco_ug_asset_idx.notna()
            & devco_journal_df["debit_account_str"].eq("Cost of Developed Unit Sales")
        )
        dc_asset_cogs_ug_piv = _to_pivot(
            devco_ug_asset_idx.loc[devco_ug_cogs_mask],
            devco_journal_df.loc[devco_ug_cogs_mask, "period_norm"],
            devco_journal_df.loc[devco_ug_cogs_mask, "amount_num"],
        )

    assetco_journal_df = _prepare_journal_frame(assetco_result)
    if not assetco_journal_df.empty:
        assetco_valid_posting_mask = (
            assetco_journal_df["period_norm"].ne("")
            & assetco_journal_df["amount_num"].abs().gt(_TOL)
            & ~assetco_journal_df["reference_str"].str.endswith("-IE")
        )
        assetco_asset_indices = _compute_asset_index_columns(
            assetco_journal_df,
            include_reference_first=True,
        )
        assetco_asset_no_uid = assetco_journal_df["asset_no_str"].astype("string").str.strip()
        invalid_asset_no_mask = (
            assetco_asset_no_uid.isna()
            | assetco_asset_no_uid.eq("")
            | assetco_asset_no_uid.str.lower().isin(["none", "nan", "nat"])
        )
        assetco_asset_no_uid = assetco_asset_no_uid.mask(invalid_asset_no_mask)

        asset_idx_from_uid = assetco_asset_no_uid.map(_project_uid_to_idx)
        raw_asset_idx = assetco_asset_indices["reference_first"]
        if _assetco_idx_to_project_idx:
            mapped_asset_idx = raw_asset_idx.map(_assetco_idx_to_project_idx)
            assetco_asset_idx = asset_idx_from_uid.fillna(mapped_asset_idx.fillna(raw_asset_idx))
        else:
            assetco_asset_idx = asset_idx_from_uid.fillna(raw_asset_idx)
        assetco_asset_idx = pd.to_numeric(assetco_asset_idx, errors="coerce").astype("Int64")

        assetco_ip_debit_mask = (
            assetco_valid_posting_mask
            & assetco_asset_idx.notna()
            & assetco_journal_df["debit_account_str"].eq("Investment Property")
        )
        ac_ip_debit_piv = _to_pivot(
            assetco_asset_idx.loc[assetco_ip_debit_mask],
            assetco_journal_df.loc[assetco_ip_debit_mask, "period_norm"],
            assetco_journal_df.loc[assetco_ip_debit_mask, "amount_num"],
        )

        assetco_ip_credit_mask = (
            assetco_valid_posting_mask
            & assetco_asset_idx.notna()
            & assetco_journal_df["credit_account_str"].eq("Investment Property")
        )
        ac_ip_credit_piv = _to_pivot(
            assetco_asset_idx.loc[assetco_ip_credit_mask],
            assetco_journal_df.loc[assetco_ip_credit_mask, "period_norm"],
            assetco_journal_df.loc[assetco_ip_credit_mask, "amount_num"],
        )

    horizon_periods = _collect_horizon_periods([landco_result, devco_result, assetco_result])

    if horizon_periods:
        all_periods = horizon_periods
    else:
        _all_period_set: set = set()
        for _piv in [
            lc_ip_rev_piv, lc_ip_cogs_piv,
            dc_sla_debit_piv, dc_sla_credit_piv, dc_cwip_debit_piv, dc_cwip_credit_piv,
            dc_ip_rev_piv, dc_ip_cogs_piv,
            dc_land_rev_ug_piv, dc_land_cogs_ug_piv,
            dc_asset_rev_ug_piv, dc_asset_cogs_ug_piv,
            ac_ip_debit_piv, ac_ip_credit_piv,
        ]:
            if not _piv.empty:
                _all_period_set.update(_piv.columns.tolist())
        all_periods = _sort_period_labels(list(_all_period_set))

    lc_assets = (
        lc_ip_rev_piv.index.union(lc_ip_cogs_piv.index)
        if not (lc_ip_rev_piv.empty and lc_ip_cogs_piv.empty)
        else pd.Index([], dtype="int64")
    )
    dc_assets = (
        dc_ip_rev_piv.index.union(dc_ip_cogs_piv.index)
        if not (dc_ip_rev_piv.empty and dc_ip_cogs_piv.empty)
        else pd.Index([], dtype="int64")
    )

    if len(lc_assets) == 0 and len(dc_assets) == 0:
        return pd.Series(dtype=float)
    if not all_periods:
        return pd.Series(dtype=float)

    consolidated_arr = np.zeros(len(all_periods), dtype=float)

    def _reindex_piv(piv: pd.DataFrame, assets: pd.Index) -> pd.DataFrame:
        if piv.empty:
            return pd.DataFrame(0.0, index=assets, columns=all_periods)
        return piv.reindex(index=assets, columns=all_periods, fill_value=0.0)

    # --- LandCo -> DevCo UG (vectorized) ---
    if len(lc_assets) > 0:
        rev_total  = _reindex_piv(lc_ip_rev_piv,  lc_assets).sum(axis=1)
        cogs_total = _reindex_piv(lc_ip_cogs_piv, lc_assets).sum(axis=1)
        valid_margin = rev_total > _TOL
        if valid_margin.any():
            margin = (rev_total - cogs_total).div(
                rev_total.where(valid_margin, np.nan)
            ).fillna(0.0)

            sla_debit   = _reindex_piv(dc_sla_debit_piv,   lc_assets)
            sla_credit  = _reindex_piv(dc_sla_credit_piv,  lc_assets)
            cwip_debit  = _reindex_piv(dc_cwip_debit_piv,  lc_assets)
            cwip_credit = _reindex_piv(dc_cwip_credit_piv, lc_assets)

            cum_sla_debit  = sla_debit.cumsum(axis=1)
            cum_cwip_debit = cwip_debit.cumsum(axis=1)
            sla_close      = (sla_debit  - sla_credit).cumsum(axis=1)
            cwip_close     = (cwip_debit - cwip_credit).cumsum(axis=1)

            ratio_denom = cum_sla_debit + cum_cwip_debit
            alloc_ratio = cum_sla_debit.div(
                ratio_denom.where(ratio_denom > _TOL, np.nan)
            ).fillna(0.0)

            adjustment = -((sla_close + cwip_close).mul(margin, axis=0) * alloc_ratio)
            adjustment = adjustment.where(adjustment.abs() > _TOL, 0.0)
            consolidated_arr += adjustment.loc[valid_margin].sum(axis=0).to_numpy()

    # --- DevCo -> AssetCo UG (vectorized) ---
    if len(dc_assets) > 0:
        land_rev   = _reindex_piv(dc_land_rev_ug_piv,   dc_assets)
        land_cogs  = _reindex_piv(dc_land_cogs_ug_piv,  dc_assets)
        asset_rev  = _reindex_piv(dc_asset_rev_ug_piv,  dc_assets)
        asset_cogs = _reindex_piv(dc_asset_cogs_ug_piv, dc_assets)

        period_profit = (land_rev - land_cogs) + (asset_rev - asset_cogs)
        ug_pre = -period_profit.cumsum(axis=1)
        ug_pre = ug_pre.where(ug_pre.abs() > _TOL, 0.0)

        ip_debit  = _reindex_piv(ac_ip_debit_piv,  dc_assets)
        ip_credit = _reindex_piv(ac_ip_credit_piv, dc_assets)
        ip_close  = (ip_debit - ip_credit).cumsum(axis=1)
        ip_close  = ip_close.where(ip_close.abs() > _TOL, 0.0)

        ug_post = ug_pre.where(ip_close.abs() > _TOL, 0.0)
        consolidated_arr += ug_post.sum(axis=0).to_numpy()

    return pd.Series(consolidated_arr, index=all_periods, dtype=float)
                


def _align_flow_to_columns(
    flow: pd.Series, columns: list,
) -> pd.Series:
    """Align a per-period flow series to target DataFrame columns.

    Works like ``_align_balance_to_columns`` but for flows: when
    direct reindex misses, sums monthly values into annual buckets.
    """
    if flow.empty:
        return pd.Series(0.0, index=columns)
    aligned = flow.reindex(columns, fill_value=0.0).fillna(0.0)
    if not (aligned == 0.0).all() or (flow == 0.0).all():
        return aligned
    # Fallback: aggregate by year (sum all months into that year)
    try:
        flow_dates = pd.to_datetime(flow.index, errors="coerce")
        year_sums: Dict[str, float] = {}
        for i, dt in enumerate(flow_dates):
            if pd.notna(dt):
                yr = str(dt.year)
                year_sums[yr] = year_sums.get(yr, 0.0) + float(flow.iloc[i])
        return pd.Series(
            [year_sums.get(str(c), 0.0) for c in columns], index=columns,
        )
    except Exception:
        return aligned


_CASHFLOW_HOSPITALITY_COMPONENT_LABELS = {
    "Hospitality - Room Revenue",
    "Hospitality - F&B Revenue",
    "Hospitality - OOD Revenue",
    "Hospitality - Other Operating Income",
    "Hospitality Departmental Expenses - Room",
    "Hospitality Departmental Expenses - F&B",
    "Hospitality Departmental Expenses - OOD",
    "Hospitality Departmental Expenses - Other",
    "Hospitality Undistributed Expenses - Admin",
    "Hospitality Undistributed Expenses - Sales & Marketing",
    "Hospitality Undistributed Expenses - IT",
    "Hospitality Undistributed Expenses - Utilities",
    "Hospitality Non-Operating Expenses",
    "Hospitality Non-Operating Income",
}

_CASHFLOW_HOSPITALITY_BLOCK_LABELS = {
    "Hospitality Revenue",
    "Hospitality Departmental Expenses",
    "Hospitality Undistributed Expenses",
    "Hospitality Non-Operating I&E",
    "Hospitality EBITDA",
}.union(_CASHFLOW_HOSPITALITY_COMPONENT_LABELS)


def _normalize_cashflow_hospitality_to_ebitda(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse hospitality cashflow detail rows into ``Hospitality EBITDA``."""
    if df.empty:
        return df.copy()

    result = df.copy()
    idx_series = result.index.to_series().astype(str)

    component_mask = idx_series.isin(_CASHFLOW_HOSPITALITY_COMPONENT_LABELS)
    if component_mask.any():
        ebitda_vals = (
            result.loc[component_mask.values]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .sum(axis=0)
        )
    elif (idx_series == "Hospitality EBITDA").any():
        ebitda_rows = result.loc[(idx_series == "Hospitality EBITDA").values]
        ebitda_numeric = ebitda_rows.apply(pd.to_numeric, errors="coerce")

        if ebitda_numeric.empty:
            ebitda_vals = pd.Series(0.0, index=result.columns)
        else:
            non_na_counts = ebitda_numeric.notna().sum(axis=1).to_numpy()
            best_idx = int(np.argmax(non_na_counts)) if len(non_na_counts) > 0 else 0
            ebitda_vals = ebitda_numeric.iloc[best_idx].fillna(0.0)
    else:
        return result

    ebitda_vals = ebitda_vals.reindex(result.columns, fill_value=0.0)

    block_positions = np.where(idx_series.isin(_CASHFLOW_HOSPITALITY_BLOCK_LABELS).values)[0]
    original_insert_pos = int(block_positions[0]) if len(block_positions) > 0 else len(result)

    remove_mask = idx_series.isin(_CASHFLOW_HOSPITALITY_BLOCK_LABELS).values
    keep_mask = ~remove_mask
    stripped = result.loc[keep_mask]

    insert_pos = int(np.count_nonzero(keep_mask[:original_insert_pos]))

    blank = [None] * len(result.columns)
    header_row = pd.DataFrame(
        [blank],
        index=["Hospitality EBITDA"],
        columns=result.columns,
    )
    line_row = pd.DataFrame(
        [ebitda_vals.tolist()],
        index=["Hospitality EBITDA"],
        columns=result.columns,
    )

    before = stripped.iloc[:insert_pos]
    after = stripped.iloc[insert_pos:]

    return _stack_frames_preserving_rows(
        [before, header_row, line_row, after],
        list(result.columns),
    )


def _emit_interparty_asset_trace_rows(
    model_results: List[Dict[str, Any]],
    financial_statement_trace: Dict[str, Any],
    is_elimination: Dict[str, pd.Series],
    cf_elimination: pd.Series,
    re_ie_series: pd.Series,
    cols: List[str],
) -> pd.Series:
    """
    Compute per-asset interparty Cost of Sales (each asset phased by its own
    DevCo COS curve) and return the summed series for use in the consolidated IS.

    Also appends per-asset trace rows for the five interparty consolidated line
    items when trace is enabled:
      IS  — "Less: Interparty Sales Revenue", "Add: Interparty Cost of Sales"
      CFS — "Less: Interparty Cash Collection", "Add: Interparty Cash Payment"
      BS  — "Less: Interparty Retained Earnings"

    The journal scan and per-asset profit-release computation always run so the
    consolidated IS can use the summed per-asset ip_cos_total regardless of
    whether trace is enabled.
    """
    _emit_trace = _ENABLE_FINANCIAL_STATEMENT_TRACE and isinstance(financial_statement_trace, dict)

    # ── Per-asset interparty revenue, COGS, cash ─────────────────────────────
    # Each entity result holds accounts keyed by name.  The Interparty Revenue/
    # COGS/Cash Elimination accounts store Debit-row flow values per period.
    # We extract them per-asset by reading journal entries whose references
    # contain the asset-index token (-IPRE-, -IPCE-, -IPXE-).
    _asset_rev: Dict[str, Dict[str, float]] = {}   # asset_id -> {period -> value}
    _asset_cogs: Dict[str, Dict[str, float]] = {}
    _asset_cash: Dict[str, Dict[str, float]] = {}

    for result in model_results:
        for _je in result.get("journal", []):
            _ref = str(_je.get("reference", ""))
            _amt = float(_je.get("amount", 0.0) or 0.0)
            _p = str(_je.get("period", ""))
            if not _p or abs(_amt) < 1e-9:
                continue
            if "-IPRE-" in _ref:
                _parts = _ref.split("-IPRE-", 1)
                if len(_parts) == 2:
                    _aid = _parts[1].split("-")[0]
                    _asset_rev.setdefault(_aid, {})
                    _asset_rev[_aid][_p] = _asset_rev[_aid].get(_p, 0.0) + _amt
            elif "-IPCE-" in _ref:
                _parts = _ref.split("-IPCE-", 1)
                if len(_parts) == 2:
                    _remaining = _parts[1]
                    _aid = _remaining[4:].split("-")[0] if _remaining.startswith("SLA-") else _remaining.split("-")[0]
                    _asset_cogs.setdefault(_aid, {})
                    _asset_cogs[_aid][_p] = _asset_cogs[_aid].get(_p, 0.0) + _amt
            elif "-IPXE-" in _ref:
                _parts = _ref.split("-IPXE-", 1)
                if len(_parts) == 2:
                    _aid = _parts[1].split("-")[0]
                    _asset_cash.setdefault(_aid, {})
                    _asset_cash[_aid][_p] = _asset_cash[_aid].get(_p, 0.0) + _amt

    all_asset_ids = sorted(set(_asset_rev) | set(_asset_cogs) | set(_asset_cash))

    # ── Extract per-asset DevCo Cost of Asset Sales from journals ─────────────
    # DevCo posts Cost of Developed Unit Sales (IS label: Cost of Asset Sales)
    # with references of the form *-COGS-LA-{idx}-* and *-COGS-CWIP-{idx}-*.
    # Collecting per-asset COS lets us run the same profit-release formula that
    # _postprocess_consolidated_is uses when the model runs in asset-filter mode
    # (where devco_cos reflects only the filtered asset's sales recognition).
    _asset_devco_cos: Dict[str, Dict[str, float]] = {}
    for result in model_results:
        for _je in result.get("journal", []):
            _ref = str(_je.get("reference", ""))
            _amt = float(_je.get("amount", 0.0) or 0.0)
            _p = str(_je.get("period", ""))
            if not _p or abs(_amt) < 1e-9:
                continue
            _da = str(_je.get("debit_account", "") or "")
            if _da not in ("Cost of Developed Unit Sales", "Cost of Asset Sales"):
                continue
            # Extract asset index from -COGS-LA-{idx}- or -COGS-CWIP-{idx}-
            _aid_cogs: Optional[str] = None
            for _marker in ("-COGS-LA-", "-COGS-CWIP-"):
                if _marker in _ref:
                    _after = _ref.split(_marker, 1)[1]
                    _aid_cogs = _after.split("-")[0]
                    break
            if _aid_cogs is None:
                continue
            _asset_devco_cos.setdefault(_aid_cogs, {})
            _asset_devco_cos[_aid_cogs][_p] = _asset_devco_cos[_aid_cogs].get(_p, 0.0) + _amt

    all_asset_ids = sorted(set(all_asset_ids) | set(_asset_devco_cos))

    # ── Compute per-asset ip_cos_total and accumulate consolidated sum ────────
    _summed_ip_cos_total = pd.Series(0.0, index=cols)

    for _aid in all_asset_ids:
        _rev_by_p = _asset_rev.get(_aid, {})
        _cogs_by_p = _asset_cogs.get(_aid, {})
        _cash_by_p = _asset_cash.get(_aid, {})
        _cos_by_p = _asset_devco_cos.get(_aid, {})

        _ip_rev = pd.Series({p: _rev_by_p.get(p, 0.0) for p in cols}, index=cols)
        _ip_cogs = pd.Series({p: _cogs_by_p.get(p, 0.0) for p in cols}, index=cols)
        _ip_cash = pd.Series({p: _cash_by_p.get(p, 0.0) for p in cols}, index=cols)
        _ip_profit = _ip_rev - _ip_cogs

        # Use per-asset DevCo Cost of Asset Sales so trace rows match the
        # model output when run in per-asset filtration mode.
        _devco_cos_for_release = pd.Series(
            {p: abs(_cos_by_p.get(p, 0.0)) for p in cols}, index=cols
        )
        _total_devco_cos = float(_devco_cos_for_release.sum())

        if _total_devco_cos > 0.0:
            _cum_profit = _ip_profit.cumsum()
            _cum_devco_cos = _devco_cos_for_release.cumsum()
            _target = _cum_profit * _cum_devco_cos / _total_devco_cos
            _profit_adj = _target.diff().fillna(_target.iloc[0] if len(_target) > 0 else 0.0)
        else:
            _profit_adj = pd.Series(0.0, index=cols)

        _ip_cos_total = _ip_cogs + _profit_adj
        _summed_ip_cos_total = _summed_ip_cos_total.add(_ip_cos_total, fill_value=0.0)

        if _emit_trace:
            for _p in cols:
                # IS: "Less: Interparty Sales Revenue"  (sign: negative of ip_rev)
                _rev_val = -float(_ip_rev.get(_p, 0.0))
                if abs(_rev_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_p,
                        value=_rev_val,
                        financial_statement="Income Statement",
                        line_item_name="Less: Interparty Sales Revenue",
                        asset_no=_aid,
                    )

                # IS: "Add: Interparty Cost of Sales"
                _cos_val = float(_ip_cos_total.get(_p, 0.0))
                if abs(_cos_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_p,
                        value=_cos_val,
                        financial_statement="Income Statement",
                        line_item_name="Add: Interparty Cost of Sales",
                        asset_no=_aid,
                    )

                # CFS: "Less: Interparty Cash Collection"  (negative in CFO)
                _cash_val = -float(_ip_cash.get(_p, 0.0))
                if abs(_cash_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_p,
                        value=_cash_val,
                        financial_statement="Cashflow Statement",
                        line_item_name="Less: Interparty Cash Collection",
                        asset_no=_aid,
                    )

                # CFS: "Add: Interparty Cash Payment"  (positive in CFI)
                _cash_pay_val = float(_ip_cash.get(_p, 0.0))
                if abs(_cash_pay_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_p,
                        value=_cash_pay_val,
                        financial_statement="Cashflow Statement",
                        line_item_name="Add: Interparty Cash Payment",
                        asset_no=_aid,
                    )

    # ── BS: "Less: Interparty Retained Earnings" ─────────────────────────────
    if _emit_trace:
        _asset_re_ie: Dict[str, Dict[str, float]] = {}
        for result in model_results:
            for _je in result.get("journal", []):
                _ref = str(_je.get("reference", ""))
                if "CLOSING-RE-IE" not in _ref:
                    continue
                _aid_raw = str(_je.get("asset_no", "") or "")
                if not _aid_raw or _aid_raw == "Consolidated":
                    continue
                _amt = float(_je.get("amount", 0.0) or 0.0)
                _p = str(_je.get("period", ""))
                if not _p or abs(_amt) < 1e-9:
                    continue
                _asset_re_ie.setdefault(_aid_raw, {})
                _dr = str(_je.get("debit_account", ""))
                # Dr RE-IE / Cr RE → negative contribution to RE-IE closing balance
                # Dr RE / Cr RE-IE → positive contribution to RE-IE closing balance
                if _dr == "Retained Earnings - Interparty Elimination":
                    _asset_re_ie[_aid_raw][_p] = _asset_re_ie[_aid_raw].get(_p, 0.0) - _amt
                else:
                    _asset_re_ie[_aid_raw][_p] = _asset_re_ie[_aid_raw].get(_p, 0.0) + _amt

        for _aid, _re_ie_by_p in _asset_re_ie.items():
            for _p, _val in _re_ie_by_p.items():
                if abs(_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_p,
                        value=_val,
                        financial_statement="Balance Sheet",
                        line_item_name="Less: Interparty Retained Earnings",
                        asset_no=_aid,
                    )

    return _summed_ip_cos_total


def _postprocess_consolidated_is(
    df: pd.DataFrame,
    is_elimination: Optional[Dict[str, pd.Series]] = None,
    jv_accounts: Optional[Dict[str, Dict[str, List[float]]]] = None,
    ip_cos_total_override: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Post-process a consolidated Income Statement to insert interparty
    elimination rows and adjust subtotals.

    Inserts:
      1. After ``Total Revenue``: Less: Interparty Sales Revenue,
         Net Revenue, blank.
      2. Before ``Gross Profit``: Add: Interparty Cost of Sales, blank.
         The "Add: Interparty Cost of Sales" value equals:
           (a) LandCo interparty Cost of Land Sales (added back), plus
           (b) a profit adjustment that releases LandCo-to-DevCo unrealized
               profit in proportion to DevCo's cumulative cost-of-asset-sales
               recognition progress.
      3. Adjusts Gross Profit, EBITDA, EBIT, EBT, Net Income accordingly.
    """
    if df.empty:
        return df.copy()
    if is_elimination is None:
        is_elimination = {}

    ip_rev_raw = is_elimination.get("revenue", pd.Series(dtype=float))
    ip_cogs_raw = is_elimination.get("cogs", pd.Series(dtype=float))

    result = df.copy()
    cols = list(result.columns)
    ip_rev = _align_flow_to_columns(ip_rev_raw, cols)
    ip_cogs = _align_flow_to_columns(ip_cogs_raw, cols)
    blank = [None] * len(cols)

    # ------------------------------------------------------------------
    # Compute "Add: Interparty Cost of Sales" using revenue-proportion
    # profit release logic (LandCo → DevCo interparty elimination).
    #
    # Components:
    #   1. Add back LandCo interparty Cost of Land Sales (= ip_cogs)
    #   2. Profit adjustment: releases unrealized LandCo profit as DevCo
    #      recognizes its Cost of Asset Sales.
    #
    # Per-period profit adjustment formula (matching spreadsheet):
    #   profit[t]           = ip_rev[t] - ip_cogs[t]
    #   devco_cos[t]        = Cost of Asset Sales[t] from consolidated IS
    #   total_devco_cos     = sum(devco_cos) across all periods
    #   target[t]           = cum_profit[t] * cum_devco_cos[t] / total_devco_cos
    #   profit_adj[t]       = target[t] - target[t-1]  (incremental)
    #
    # Add: Interparty Cost of Sales[t] = ip_cogs[t] + profit_adj[t]
    # ------------------------------------------------------------------

    # Extract Cost of Asset Sales from the IS before any modifications.
    # The IS at this stage shows expenses as negative; take absolute values.
    idx_str = result.index.astype(str)
    cos_asset_pos = np.where(idx_str == "Cost of Asset Sales")[0]
    if len(cos_asset_pos) > 0:
        devco_cos = pd.to_numeric(
            result.iloc[int(cos_asset_pos[0])], errors="coerce"
        ).fillna(0.0).abs()
    else:
        devco_cos = pd.Series(0.0, index=cols)

    total_devco_cos = float(devco_cos.sum())

    # Per-period interparty profit (LandCo revenue − LandCo cost of sales).
    ip_profit = ip_rev - ip_cogs  # positive when LandCo earns profit

    if total_devco_cos > 0.0:
        cum_profit = ip_profit.cumsum()
        cum_devco_cos = devco_cos.cumsum()
        # target[t] = cum_profit[t] * cum_devco_cos[t] / total_devco_cos
        # (target is already cumulative; incremental = target[t] - target[t-1])
        target = cum_profit * cum_devco_cos / total_devco_cos
        profit_adj = target.diff().fillna(target.iloc[0] if len(target) > 0 else 0.0)
    else:
        profit_adj = pd.Series(0.0, index=cols)

    # Final "Add: Interparty Cost of Sales" values.
    # Use pre-computed per-asset sum when provided — this ensures the consolidated
    # IS reflects the sum of individual asset profit releases (each phased by its
    # own DevCo COS curve) rather than a single portfolio-level phasing.
    if ip_cos_total_override is not None and not ip_cos_total_override.empty:
        ip_cos_total = _align_flow_to_columns(ip_cos_total_override, cols)
    else:
        ip_cos_total = ip_cogs + profit_adj

    # 1. After "Total Revenue" -----------------------------------------------
    idx_str = result.index.astype(str)
    tr_positions = np.where(idx_str == "Total Revenue")[0]
    if len(tr_positions) > 0:
        pos = int(tr_positions[0])
        total_rev = pd.to_numeric(result.iloc[pos], errors="coerce").fillna(0.0)
        net_rev = total_rev - ip_rev

        less_rev_row = pd.DataFrame(
            [(-ip_rev).tolist()], index=["Less: Interparty Sales Revenue"], columns=cols,
        )
        net_rev_row = pd.DataFrame(
            [net_rev.tolist()], index=["Net Revenue"], columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[: pos + 1]
        after = result.iloc[pos + 1 :]
        result = pd.concat([before, less_rev_row, net_rev_row, blank_row, after])

    # 2. Before "Gross Profit" ------------------------------------------------
    idx_str = result.index.astype(str)
    gp_positions = np.where(idx_str == "Gross Profit")[0]
    if len(gp_positions) > 0:
        pos = int(gp_positions[0])
        add_cogs_row = pd.DataFrame(
            [ip_cos_total.tolist()], index=["Add: Interparty Cost of Sales"], columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[:pos]
        after = result.iloc[pos:]
        result = pd.concat([before, add_cogs_row, blank_row, after])

    # 3. Adjust subtotals: net impact = −IP Revenue + IP COGS ----------------
    adjustment = ip_cos_total - ip_rev  # negative if net IP profit > 0

    idx_str = result.index.astype(str)
    for label in ["Gross Profit", "EBITDA", "EBIT", "EBT", "Net Income"]:
        positions = np.where(idx_str == label)[0]
        if len(positions) == 0:
            continue
        pos = int(positions[0])
        old_vals = pd.to_numeric(result.iloc[pos], errors="coerce").fillna(0.0)
        new_vals = old_vals + adjustment
        result.iloc[pos] = new_vals.tolist()

    # 4. Populate "Share of Profit from JV" with consolidated profit accrual.
    #    No rows are added — the IS proforma is unchanged. The account detail
    #    is stored separately in consolidationoutput. -------------------------
    if jv_accounts:
        cols = list(result.columns)
        n_cols = len(cols)

        # Sum profit accrual + land transfer profit across all JV scenarios.
        # land_transfer_profit is IS-only (not in IA closing balance).
        consolidated_accrual: List[float] = [0.0] * n_cols
        for acct in jv_accounts.values():
            pa  = acct.get("profit_accrual", [])
            ltp = acct.get("land_transfer_profit", [])
            for i in range(n_cols):
                consolidated_accrual[i] += (pa[i] if i < len(pa) else 0.0) + (ltp[i] if i < len(ltp) else 0.0)

        # Populate the existing "Share of Profit from JV" row in-place
        idx_str = result.index.astype(str)
        sopjv_pos = np.where(idx_str == "Share of Profit from JV")[0]
        if len(sopjv_pos) > 0:
            result.iloc[int(sopjv_pos[0])] = consolidated_accrual

            # Adjust Net Income only — Share of Profit from JV is below EBT
            accrual_series = pd.Series(consolidated_accrual, index=cols)
            for label in ["Net Income"]:
                idx_str = result.index.astype(str)
                positions = np.where(idx_str == label)[0]
                if len(positions) == 0:
                    continue
                p = int(positions[0])
                old_vals = pd.to_numeric(result.iloc[p], errors="coerce").fillna(0.0)
                result.iloc[p] = (old_vals + accrual_series).tolist()

    return result


def _extract_jv_cashflows_for_roshn(
    jv_consolidation: Dict[str, Any],
) -> Dict[str, List[float]]:
    """Aggregate JV cash flows for ROSHN across all JV scenarios.

    Returns:
        ``"investment_in_jv"``  — ROSHN's cash equity outflows (negative, monthly)
        ``"dividends_from_jv"`` — all distributions received by ROSHN (positive, monthly)

    Source sections and row indices are fixed by the proforma structure, so we
    use index-based extraction to handle repeated labels (e.g. "LP Distributions"
    appears 3 times in Waterfall Distribution under different subsections).

    Waterfall Distribution row index map (fixed by jv_proforma.py structure):
        GP role dividends
          [16] Return of Capital - GP
          [17] GP Distributions          ← GP preferred return
          [25] GP Catchup                ← GP catchup post-preferred (2nd occurrence)
          [40] GP Tier 1 Promote
          [41] GP Tier 1 Catchup
          [56] GP Tier 2 Promote
          [57] GP Tier 2 Catchup
          [64] GP Tier 3 Distributions
        LP role dividends
          [ 7] Return of Capital - LP
          [ 8] LP Distributions          ← LP preferred return (1st occurrence)
          [35] LP Distributions          ← Tier 1 LP (2nd occurrence)
          [51] LP Distributions          ← Tier 2 LP (3rd occurrence)
          [63] LP Tier 3 Distributions

    Clawback Workings row index map:
        GP role: [11] Clawback - GP  (stored negative → negate to positive receipt)
        LP role: [ 7] Clawback - LP  (stored positive already)

    Equity Scehdule row index map:
        GP role: [ 5] GP Commitment                        (cash equity)
        LP role: [ 6] LP Commitment                        (cash equity)
        GP role: [31] Compensation in Lieu of Land (GP)    (positive = inflow)
        LP role: [32] Compensation in Lieu of Land (LP)    (positive = inflow)
    """
    # Fixed row indices per section per role, with sign instruction.
    # Sign convention in Waterfall Distribution section:
    #   Return of Capital rows (16, 7) and LP Distributions rows (8, 35, 51)
    #   are stored NEGATIVE → negate to get positive receipt for ROSHN.
    #   All promote/catchup/tier rows (17, 25, 40, 41, 56, 57, 63, 64) are
    #   stored POSITIVE already → use as-is.
    # Each entry is (row_index, negate: bool).
    _WF_DIST_INDICES: Dict[str, List[tuple]] = {
        "gp": [
            (16, True),   # Return of Capital - GP          (negative in section)
            (17, False),  # GP Preferred Return              (positive in section)
            (25, False),  # GP Catchup Post-Preferred        (positive)
            (40, False),  # GP Tier 1 Promote                (positive)
            (41, False),  # GP Tier 1 Catchup                (positive)
            (56, False),  # GP Tier 2 Promote                (positive)
            (57, False),  # GP Tier 2 Catchup                (positive)
            (64, False),  # GP Tier 3 Distributions          (positive)
        ],
        "lp": [
            ( 7, True),   # Return of Capital - LP           (negative in section)
            ( 8, True),   # LP Preferred Return              (negative)
            (35, True),   # LP Tier 1 Distributions          (negative)
            (51, True),   # LP Tier 2 Distributions          (negative)
            (63, False),  # LP Tier 3 Distributions          (positive)
        ],
    }
    # Clawback Workings: GP clawback stored negative, LP stored positive.
    _CLAWBACK_INDEX: Dict[str, int] = {"gp": 11, "lp": 7}
    _CLAWBACK_NEGATE: Dict[str, bool] = {"gp": True, "lp": False}
    # Equity Scehdule: cash equity rows are positive outflows → negate for CFI.
    _CASH_EQUITY_INDEX: Dict[str, int] = {"gp": 5, "lp": 6}

    def _row_at(section: Dict[str, Any], idx: int) -> List[float]:
        """Return monthly data for row at position *idx*; zeros if missing."""
        monthly = section.get("monthly", [])
        if idx < len(monthly):
            return [v if v is not None else 0.0 for v in monthly[idx]]
        return []

    def _add(a: List[float], b: List[float]) -> List[float]:
        na, nb = len(a), len(b)
        if na == 0:
            return list(b)
        if nb == 0:
            return list(a)
        n = max(na, nb)
        arr = np.zeros(n, dtype=np.float64)
        arr[:na] += a
        arr[:nb] += b
        return arr.tolist()

    investment: List[float] = []
    distributions: List[float] = []

    for _jv_name, jv_data in jv_consolidation.items():
        if not isinstance(jv_data, dict):
            continue

        rr = jv_data.get("roshn_role", {})
        role = str(rr.get("role", "")).strip().lower()
        if role not in ("gp", "lp"):
            continue

        eq_section = jv_data.get("Equity Scehdule", {})
        wf_section = jv_data.get("Waterfall Distribution", {})
        cb_section = jv_data.get("Clawback Workings", {})

        # --- Investment in JV: cash equity only (no in-kind) ---
        # Equity Scehdule values are positive; negate for CFI outflow.
        cash_eq = _row_at(eq_section, _CASH_EQUITY_INDEX[role])
        investment = _add(investment, [-v for v in cash_eq])

        # --- Dividends from JV: all distribution rows for ROSHN's role ---
        for idx, negate in _WF_DIST_INDICES[role]:
            row = _row_at(wf_section, idx)
            distributions = _add(distributions, [-v for v in row] if negate else row)

        # --- Compensation in Lieu of Land (Equity Schedule rows 31/32) ---
        # GP role → row [31] Compensation in Lieu of Land (GP); positive = inflow
        # LP role → row [32] Compensation in Lieu of Land (LP); positive = inflow
        _COMP_INDEX = {"gp": 31, "lp": 32}
        comp_row = _row_at(eq_section, _COMP_INDEX[role])
        distributions = _add(distributions, comp_row)

        # --- Clawback ---
        cb_row = _row_at(cb_section, _CLAWBACK_INDEX[role])
        distributions = _add(
            distributions,
            [-v for v in cb_row] if _CLAWBACK_NEGATE[role] else cb_row,
        )

    return {
        "investment_in_jv": investment,
        "dividends_from_jv": distributions,
    }


def _build_jv_investment_accounts(
    jv_consolidation: Dict[str, Any],
) -> Dict[str, Dict[str, List[float]]]:
    """Build a per-scenario investment account for the consolidated IS.

    For each JV scenario in *jv_consolidation* returns a dict of 5 monthly
    series that represent the running investment account ROSHN holds in the JV:

        opening_balance   — carried-forward closing balance of prior period
        investments       — cash + in-kind equity contributed (negative = outflow)
        profit_accrual    — economic return accrued this period
        distributions     — cash received back from the JV (positive = inflow)
        closing_balance   — cumulative account balance

    Row index maps (fixed by jv_proforma.py structure, verified against payload):

    Equity Schedule
        GP cash equity:   [5]   GP Commitment
        LP cash equity:   [6]   LP Commitment (Others)
        GP in-kind:       [10]  GP Commitment For Land
        LP in-kind:       [11]  Land In Kind (LP Others)

    Waterfall Distribution — profit accrual rows
        GP Preferred Accrual: [15]
        GP Catchup:           [25]  (GP Catchup)
        GP Tier 1 Promote:    [40]
        GP Tier 1 Catchup:    [41]
        GP Tier 2 Promote:    [56]
        GP Tier 2 Catchup:    [57]
        GP Tier 3:            [64]
        LP Preferred Accrual: [6]
        LP Tier 1 Accrual:    [33]
        LP Tier 2 Accrual:    [49]
        LP Tier 3:            [63]

    Waterfall Distribution — distribution (cash received) rows
        Same as _extract_jv_cashflows_for_roshn — GP [16,17,25,40,41,56,57,64]
        LP [7,8,35,51,63] plus clawback.
    """
    # ── Profit accrual rows (value sign in section: positive = accrued) ──
    # GP: preferred accrual + catchup + all tier promotes/catchups/tier3
    # LP: preferred accrual only; Tier 1/2/3 are cash-distribution-based (LP
    #     earns return when hurdle cash is distributed, not on a running accrual).
    _ACCRUAL_INDICES: Dict[str, List[int]] = {
        "gp": [15, 25, 40, 41, 56, 57, 64],  # pref + catchup + t1p + t1cu + t2p + t2cu + t3
        "lp": [6],                            # preferred accrual only
    }
    # ── LP Tier 1/2/3 distributions counted as profit (cash-basis) ──
    # These are the same rows as in _DIST_INDICES but we include them in
    # profit_accrual for LP (excluding Return of Capital rows).
    _LP_CASH_PROFIT_INDICES: List[tuple] = [
        (8,  True),   # LP Preferred Return distributions (neg stored → negate)
        (35, True),   # LP Tier 1 Distributions           (neg stored → negate)
        (51, True),   # LP Tier 2 Distributions           (neg stored → negate)
        (63, False),  # LP Tier 3 Distributions           (pos stored)
    ]
    # ── Distribution indices (same as _extract_jv_cashflows_for_roshn) ──
    _DIST_INDICES: Dict[str, List[tuple]] = {
        "gp": [
            (16, True), (17, False), (25, False), (40, False),
            (41, False), (56, False), (57, False), (64, False),
        ],
        "lp": [
            (7, True), (8, True), (35, True), (51, True), (63, False),
        ],
    }
    _CLAWBACK_INDEX: Dict[str, int] = {"gp": 11, "lp": 7}
    _CLAWBACK_NEGATE: Dict[str, bool] = {"gp": True, "lp": False}
    # Equity Schedule: Compensation in Lieu of Land (non-cash in-kind receipt).
    _COMP_INDEX: Dict[str, int] = {"gp": 31, "lp": 32}
    # ── Equity Schedule investment indices ──
    # _CASH_IDX: cash-only contribution (for BS Cash tracking)
    # _INKIND_IDX: in-kind contribution fallback
    # _TOTAL_IDX: total committed equity (cash + inkind + all other components).
    #   The waterfall ROC row distributes exactly this total, so the IA formula
    #   must use this row to avoid a residual gap between invested and returned.
    _CASH_IDX:   Dict[str, int] = {"gp": 5,  "lp": 6}
    _INKIND_IDX: Dict[str, int] = {"gp": 10, "lp": 11}
    _TOTAL_IDX:  Dict[str, int] = {"gp": 15, "lp": 16}

    def _row_at(section: Dict[str, Any], idx: int) -> List[float]:
        monthly = section.get("monthly", [])
        if idx < len(monthly):
            return [v if v is not None else 0.0 for v in monthly[idx]]
        return []

    def _add(a: List[float], b: List[float]) -> List[float]:
        na, nb = len(a), len(b)
        if na == 0:
            return list(b)
        if nb == 0:
            return list(a)
        n = max(na, nb)
        arr = np.zeros(n, dtype=np.float64)
        arr[:na] += a
        arr[:nb] += b
        return arr.tolist()

    result: Dict[str, Dict[str, List[float]]] = {}

    for jv_name, jv_data in jv_consolidation.items():
        if not isinstance(jv_data, dict):
            continue
        rr = jv_data.get("roshn_role", {})
        role = str(rr.get("role", "")).strip().lower()
        if role not in ("gp", "lp"):
            continue

        eq_section = jv_data.get("Equity Scehdule", {})
        wf_section = jv_data.get("Waterfall Distribution", {})
        cb_section = jv_data.get("Clawback Workings", {})

        # ── Investments: use total equity commitment so IA matches waterfall ROC ──
        # Cash-only row kept separately for BS Cash adjustment.
        # Total equity row includes cash + inkind + any additional components
        # (e.g. arrangement fees capitalised as equity) that the waterfall
        # distributes as ROC.  Using cash+inkind alone leaves a residual gap.
        cash_row        = _row_at(eq_section, _CASH_IDX[role])
        total_equity_row = _row_at(eq_section, _TOTAL_IDX[role])
        cash_investments: List[float] = [-v for v in cash_row]   # cash only
        if total_equity_row:
            investments: List[float] = [-v for v in total_equity_row]
        else:
            inkind_row = _row_at(eq_section, _INKIND_IDX[role])
            investments = _add(cash_investments, [-v for v in inkind_row])

        # ── Profit accrual ──
        # GP: running accruals (preferred, catchup, promotes, tier3)
        # LP: preferred accrual + cash distributions from Tier 1/2/3
        #     (LP profit is recognised when cash hurdles are met, not daily)
        profit_accrual: List[float] = []
        for idx in _ACCRUAL_INDICES[role]:
            row = _row_at(wf_section, idx)
            profit_accrual = _add(profit_accrual, row)
        if role == "lp":
            for idx, negate in _LP_CASH_PROFIT_INDICES:
                row = _row_at(wf_section, idx)
                profit_accrual = _add(profit_accrual, [-v for v in row] if negate else row)

        # ── Land transfer profit (Component 2 of Share of Profit from JV) ──
        # Recognized when ROSHN is the land owner (lik_owner matches ROSHN's role).
        # Profit = Total In Kind Equity (JV valuation) - Land In Kind at cost (ROSHN's books).
        _rr = jv_data.get("roshn_role", {})
        _lik_owner = str(_rr.get("lik_owner") or "").strip().upper()
        _roshn_is_landowner = bool(_lik_owner) and (_lik_owner == role.upper())
        land_transfer_profit: List[float] = []
        if _roshn_is_landowner:
            _lik_per_asset = jv_data.get("land_in_kind_per_asset") or {}
            if _lik_per_asset:
                _total_ik_row = _row_at(eq_section, 12)  # "Total In Kind Equity"
                _ltp_max = max(
                    len(_total_ik_row),
                    max((len(v) for v in _lik_per_asset.values()), default=0),
                )
                _lik_cost = [
                    sum(float(v[i]) if i < len(v) else 0.0 for v in _lik_per_asset.values())
                    for i in range(_ltp_max)
                ]
                land_transfer_profit = [
                    float(_total_ik_row[i] if i < len(_total_ik_row) else 0.0) - _lik_cost[i]
                    for i in range(_ltp_max)
                ]
                # land_transfer_profit is IS-only — do NOT add to profit_accrual here
                # so the IA closing balance (BS) is unaffected.

        # ── Distributions: cash received by ROSHN (positive = inflow) ──
        distributions: List[float] = []
        for idx, negate in _DIST_INDICES[role]:
            row = _row_at(wf_section, idx)
            distributions = _add(distributions, [-v for v in row] if negate else row)
        cb_row = _row_at(cb_section, _CLAWBACK_INDEX[role])
        distributions = _add(
            distributions,
            [-v for v in cb_row] if _CLAWBACK_NEGATE[role] else cb_row,
        )

        # cash_distributions drives BS Cash; distributions (total incl. comp) is kept
        # separately for Cash tracking but must NOT be used in the IA closing balance
        # loop — LP Others Equity / GP Equity are already net of compensation received,
        # so using cash_distributions in the loop avoids double-counting comp in IA.
        cash_distributions: List[float] = list(distributions)

        # Compensation in Lieu of Land: cash received by the land owner from the JV.
        # Added to distributions so BS Cash picks it up, but excluded from the IA loop.
        comp_row = _row_at(eq_section, _COMP_INDEX[role])
        distributions = _add(distributions, comp_row)

        # ── Opening / Closing Balance ──
        n = max(len(investments), len(profit_accrual), len(cash_distributions))
        opening_balance: List[float] = [0.0] * n
        closing_balance: List[float] = [0.0] * n
        running = 0.0
        for i in range(n):
            inv = investments[i]        if i < len(investments)        else 0.0
            acc = profit_accrual[i]     if i < len(profit_accrual)     else 0.0
            dis = cash_distributions[i] if i < len(cash_distributions) else 0.0
            opening_balance[i] = running
            # inv is negative (CFS outflow convention); negate so BS asset
            # increases when equity is contributed.
            running = running - inv + acc - dis
            if running < 0.0:
                if i < len(profit_accrual):
                    profit_accrual[i] -= running   # subtract negative = add |excess|
                running = 0.0
            closing_balance[i] = running

        result[jv_name] = {
            "opening_balance":      opening_balance,
            "investments":          investments,
            "cash_investments":     cash_investments,       # cash-only equity for BS Cash line
            "profit_accrual":       profit_accrual,
            "land_transfer_profit": land_transfer_profit,  # Component 2 of Share of Profit from JV
            "distributions":        distributions,          # total incl. comp (for Cash tracking)
            "cash_distributions":   cash_distributions,    # cash-only (for BS Cash line)
            "closing_balance":      closing_balance,
        }

    return result


def _postprocess_consolidated_cf(
    df: pd.DataFrame,
    cf_elimination: Optional[pd.Series] = None,
    jv_investment: Optional[List[float]] = None,
    jv_dividends: Optional[List[float]] = None,
    jv_lik_per_asset: Optional[Dict[str, List[float]]] = None,
) -> pd.DataFrame:
    """
    Post-process a consolidated Cashflow Statement:
      1. Remove Interparty Elimination rows.
      2. Insert interparty cash collection elimination rows in CFO
         and corresponding offset in CFI.
      3. Adjust ``Net Cash from Operations`` and ``Net Cash from
         Investments`` subtotals.
      4. Collapse consecutive blank rows.
    """
    if df.empty:
        return df.copy()

    result = df.copy()

    # 1. Remove IE rows -------------------------------------------------------
    idx_str = result.index.astype(str)
    ie_mask = idx_str.str.contains("Interparty Eliminat", case=False, na=False)
    result = result.loc[~ie_mask]

    # 1b. Insert JV rows (above interparty eliminations) ----------------------
    cols = list(result.columns)
    blank = [None] * len(cols)
    _zero_row = [0.0] * len(cols)

    def _jv_series_to_row(values: Optional[List[float]]) -> List[float]:
        """Align a JV monthly array to the CF DataFrame columns by position."""
        if not values:
            return list(_zero_row)
        n = len(cols)
        return [float(values[i]) if i < len(values) else 0.0 for i in range(n)]

    # CFO: "Share of Profit from JV" before "Net Cash from Operations"
    idx_str = result.index.astype(str)
    cfo_pos = np.where(idx_str == "Net Cash from Operations")[0]
    if len(cfo_pos) > 0:
        pos = int(cfo_pos[0])
        jv_profit_row = pd.DataFrame(
            [list(_zero_row)], index=["Share of Profit from JV"], columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[:pos]
        after = result.iloc[pos:]
        result = pd.concat([df for df in [before, jv_profit_row, blank_row, after] if not df.empty and not df.isna().all(axis=None)])

    # CFI: "Investment in JV" and "Dividends Received from JV" before
    # "Net Cash from Investments" — populated from JV equity/waterfall data.
    idx_str = result.index.astype(str)
    cfi_pos = np.where(idx_str == "Net Cash from Investments")[0]
    if len(cfi_pos) > 0:
        pos = int(cfi_pos[0])
        inv_jv_row = pd.DataFrame(
            [_jv_series_to_row(jv_investment)], index=["Investment in JV"], columns=cols,
        )
        div_jv_row = pd.DataFrame(
            [_jv_series_to_row(jv_dividends)], index=["Dividends Received from JV"], columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[:pos]
        after = result.iloc[pos:]
        result = pd.concat([df for df in [before, inv_jv_row, div_jv_row, blank_row, after] if not df.empty and not df.isna().all(axis=None)])

        # Adjust Net Cash from Investments to include JV rows
        idx_str = result.index.astype(str)
        cfi_pos2 = np.where(idx_str == "Net Cash from Investments")[0]
        if len(cfi_pos2) > 0:
            p = int(cfi_pos2[0])
            old_cfi = pd.to_numeric(result.iloc[p], errors="coerce").fillna(0.0)
            inv_vals = pd.Series(_jv_series_to_row(jv_investment), index=cols)
            div_vals = pd.Series(_jv_series_to_row(jv_dividends), index=cols)
            result.iloc[p] = (old_cfi + inv_vals + div_vals).tolist()

    # 2. Insert interparty cash elimination rows (always for consistent structure)
    ip_cash = _align_flow_to_columns(
        cf_elimination if cf_elimination is not None else pd.Series(dtype=float), cols,
    )

    # CFO: insert "Less: Interparty Cash Collection" before
    # "Net Cash from Operations"
    idx_str = result.index.astype(str)
    cfo_pos = np.where(idx_str == "Net Cash from Operations")[0]
    if len(cfo_pos) > 0:
        pos = int(cfo_pos[0])
        less_row = pd.DataFrame(
            [(-ip_cash).tolist()],
            index=["Less: Interparty Cash Collection"],
            columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[:pos]
        after = result.iloc[pos:]
        result = pd.concat([df for df in [before, less_row, blank_row, after] if not df.empty and not df.isna().all(axis=None)])

        # Recompute Net Cash from Operations as the sum of all component rows
        # above it (including the newly inserted Less: Interparty row), so the
        # stated subtotal always equals the sum of its visible line items.
        idx_str = result.index.astype(str)
        cfo_pos2 = np.where(idx_str == "Net Cash from Operations")[0]
        if len(cfo_pos2) > 0:
            p = int(cfo_pos2[0])
            component_rows = result.iloc[:p]
            recomputed = (
                component_rows.apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
                .sum(axis=0)
            )
            result.iloc[p] = recomputed.tolist()

    # CFI: insert "Add: Interparty Cash Payment" before
    # "Net Cash from Investments"
    idx_str = result.index.astype(str)
    cfi_pos = np.where(idx_str == "Net Cash from Investments")[0]
    if len(cfi_pos) > 0:
        pos = int(cfi_pos[0])
        add_row = pd.DataFrame(
            [ip_cash.tolist()],
            index=["Add: Interparty Cash Payment"],
            columns=cols,
        )
        blank_row = pd.DataFrame([blank], index=[""], columns=cols)
        before = result.iloc[:pos]
        after = result.iloc[pos:]
        result = pd.concat([df for df in [before, add_row, blank_row, after] if not df.empty and not df.isna().all(axis=None)])

        # Adjust Net Cash from Investments
        idx_str = result.index.astype(str)
        cfi_pos2 = np.where(idx_str == "Net Cash from Investments")[0]
        if len(cfi_pos2) > 0:
            p = int(cfi_pos2[0])
            old_cfi = pd.to_numeric(result.iloc[p], errors="coerce").fillna(0.0)
            result.iloc[p] = (old_cfi + ip_cash).tolist()

    # 3. Move "Land in Kind Contribution" from CFF to non-cash disclosure -----
    _LIK_LABEL = "Land in Kind Contribution"
    idx_str = result.index.astype(str)
    lik_positions = np.where(idx_str == _LIK_LABEL)[0]
    _lik_vals = None
    if len(lik_positions) > 0:
        lik_pos = int(lik_positions[0])
        _lik_vals = pd.to_numeric(result.iloc[lik_pos], errors="coerce").fillna(0.0)
        # Remove the row from CFF
        result = result.drop(result.index[lik_pos])

        # Subtract from Net Cash from Financing
        idx_str = result.index.astype(str)
        cff_pos = np.where(idx_str == "Net Cash from Financing")[0]
        if len(cff_pos) > 0:
            p = int(cff_pos[0])
            old_cff = pd.to_numeric(result.iloc[p], errors="coerce").fillna(0.0)
            result.iloc[p] = (old_cff - _lik_vals).tolist()

        # Subtract from Net Change in Cash (land in kind is non-cash)
        idx_str = result.index.astype(str)
        ncc_adj_pos = np.where(idx_str == "Net Change in Cash")[0]
        if len(ncc_adj_pos) > 0:
            p = int(ncc_adj_pos[0])
            old_ncc = pd.to_numeric(result.iloc[p], errors="coerce").fillna(0.0)
            result.iloc[p] = (old_ncc - _lik_vals).tolist()

        # Also remove "Equity Contributions" header if it preceded LIK and
        # "Project and Asset Equity Contribution" is gone or is the only
        # remaining child — keep it as-is since other equity items may exist.

    # 3b. Add JV LIK aggregate to the existing "Land in Kind Contribution" value.
    # The JV amounts are aggregated here; per-asset detail lives in the trace DF only.
    if jv_lik_per_asset:
        cols = list(result.columns)
        n_cols = len(cols)
        _jv_lik_agg = [
            sum(v[i] if i < len(v) else 0.0 for v in jv_lik_per_asset.values())
            for i in range(n_cols)
        ]
        _jv_lik_series = pd.Series(_jv_lik_agg, index=cols)
        if _lik_vals is not None:
            _lik_vals = _lik_vals + _jv_lik_series
        else:
            _lik_vals = _jv_lik_series

    # 3c-insert. Insert Land in Kind as non-cash disclosure after Net Change in Cash
    if _lik_vals is not None:
        cols = list(result.columns)
        blank = [None] * len(cols)
        idx_str = result.index.astype(str)
        ncc_pos = np.where(idx_str == "Net Change in Cash")[0]
        if len(ncc_pos) > 0:
            pos = int(ncc_pos[0])
            blank_row = pd.DataFrame([blank], index=[""], columns=cols)
            header_row = pd.DataFrame([blank], index=["NON-CASH ITEMS"], columns=cols)
            blank_row2 = pd.DataFrame([blank], index=[""], columns=cols)
            lik_row = pd.DataFrame(
                [_lik_vals.tolist()],
                index=[_LIK_LABEL],
                columns=cols,
            )
            before = result.iloc[: pos + 1]
            after = result.iloc[pos + 1 :]
            result = pd.concat([df for df in [before, blank_row, header_row, blank_row2, lik_row, after] if not df.empty and not df.isna().all(axis=None)])

    # 3c. Recompute Net Change in Cash = CFO + CFI + CFF from the (now
    # corrected) net subtotal rows, so NCC stays consistent after all
    # adjustments above (interparty recomputation, JV rows, LIK removal).
    _NET_SECTION_LABELS = [
        "Net Cash from Operations",
        "Net Cash from Investments",
        "Net Cash from Financing",
    ]
    idx_str = result.index.astype(str)
    ncc_final_pos = np.where(idx_str == "Net Change in Cash")[0]
    if len(ncc_final_pos) > 0:
        p = int(ncc_final_pos[0])
        recomputed_ncc = np.zeros(len(result.columns), dtype=np.float64)
        for _net_label in _NET_SECTION_LABELS:
            _net_pos = np.where(idx_str == _net_label)[0]
            if len(_net_pos) > 0:
                recomputed_ncc += (
                    pd.to_numeric(result.iloc[int(_net_pos[0])], errors="coerce")
                    .fillna(0.0)
                    .to_numpy(dtype=np.float64)
                )
        result.iloc[p] = recomputed_ncc.tolist()

    # 4. Collapse consecutive blank rows ---------------------------------------
    idx_clean = result.index.astype(str).str.strip()
    is_blank = (idx_clean == "") | (idx_clean == "nan") | (idx_clean == "None")
    prev_blank = pd.Series(is_blank).shift(1, fill_value=False).values
    consecutive = is_blank & prev_blank
    result = result.loc[~consecutive]

    return result


def _postprocess_consolidated_bs(
    df: pd.DataFrame,
    unrealized_gains: Optional[pd.Series] = None,
    interparty_netting: Optional[Dict[str, pd.Series]] = None,
    jv_closing_balance: Optional[pd.Series] = None,
    jv_profit_accrual: Optional[pd.Series] = None,
    jv_distributions: Optional[pd.Series] = None,
    jv_investments: Optional[pd.Series] = None,
    jv_lik_cumsum: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Post-process a consolidated Balance Sheet DataFrame:
      1. Combine CWIP - Serviced Land, CWIP - Developed Units, and
         Serviced Land Assets into a single 'CWIP' row.
      2. Insert Total Property Investments, Less: Unrealized Gains,
         and Net Property Investments rows after the property block.
      3. Remove all Interparty Elimination rows and section headers.
      4. Remove Deferred Revenue row.
      5. Insert interparty netting rows (AR/AP, Advances/UR).
      6. Collapse consecutive blank rows.
    """
    if df.empty:
        return df.copy()

    result = df.copy()

    # 1. Merge CWIP lines --------------------------------------------------
    idx_str = result.index.astype(str)
    cwip_mask = idx_str.isin(_CWIP_MERGE_LABELS)
    if cwip_mask.any():
        cwip_sum = (
            result.loc[cwip_mask]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .sum(axis=0)
        )
        first_pos = int(np.argmax(cwip_mask))
        before = result.iloc[:first_pos]
        after_mask = ~idx_str[first_pos:].isin(_CWIP_MERGE_LABELS)
        after = result.iloc[first_pos:].loc[after_mask]
        cwip_row = pd.DataFrame(
            [cwip_sum.tolist()], index=["CWIP"], columns=result.columns
        )
        blank_before_cwip = pd.DataFrame(
            [[None] * len(result.columns)], index=[""], columns=result.columns
        )
        result = pd.concat([df for df in [before, blank_before_cwip, cwip_row, after] if not df.empty and not df.isna().all(axis=None)])

    # 1b. Insert Total Property Investments / Unrealized Gains / Net -------
    idx_str = result.index.astype(str)
    prop_mask = idx_str.isin(_PROPERTY_INVESTMENT_LABELS)
    # Pre-initialise ug_vals so it's available for RE netting below even if
    # no property investment rows exist.
    _ug_vals_masked = pd.Series(0.0, index=result.columns)
    if prop_mask.any():
        prop_sum = (
            result.loc[prop_mask]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .sum(axis=0)
        )
        # Find the position right after the last property row
        prop_positions = np.where(prop_mask)[0]
        last_prop_pos = int(prop_positions[-1])

        total_row = pd.DataFrame(
            [prop_sum.tolist()], index=["Total Property Investments"], columns=result.columns
        )

        # Unrealized Gains row (from entity accounts)
        # Only show UG where property investments are non-zero (tolerance for
        # floating-point rounding).
        if unrealized_gains is not None and not unrealized_gains.empty:
            ug_vals = unrealized_gains.reindex(result.columns, fill_value=0.0).fillna(0.0)
            ug_vals = ug_vals.where(prop_sum.abs() > 0.5, 0.0)
        else:
            ug_vals = pd.Series(0.0, index=result.columns)
        _ug_vals_masked = ug_vals
        ug_row = pd.DataFrame(
            [ug_vals.tolist()], index=["Less: Unrealized Gains (Assets)"], columns=result.columns
        )

        net_vals = prop_sum + ug_vals
        net_row = pd.DataFrame(
            [net_vals.tolist()], index=["Net Property Investments"], columns=result.columns
        )

        blank_after_net = pd.DataFrame(
            [[None] * len(result.columns)], index=[""], columns=result.columns
        )
        before_prop = result.iloc[: last_prop_pos + 1]
        after_prop = result.iloc[last_prop_pos + 1 :]
        result = pd.concat([df for df in [before_prop, total_row, ug_row, net_row, blank_after_net, after_prop] if not df.empty and not df.isna().all(axis=None)])

    # 2. Remove Interparty Elimination rows --------------------------------
    idx_str = result.index.astype(str)
    ie_mask = idx_str.str.contains("Interparty Eliminat", case=False, na=False)
    result = result.loc[~ie_mask]

    # 3. Remove Deferred Revenue -------------------------------------------
    idx_str = result.index.astype(str)
    result = result.loc[idx_str != "Deferred Revenue"]

    # 3b. Remove category sub-headers (Current/Non-Current Assets/Liabilities)
    _CATEGORY_HEADERS = {
        "Current Assets", "Non-Current Assets",
        "Current Liabilities", "Non-Current Liabilities",
    }
    idx_str = result.index.astype(str)
    result = result.loc[~idx_str.isin(_CATEGORY_HEADERS)]

    # 4. Insert interparty netting rows ------------------------------------
    #    Unrealized gains are applied as direct signed adjustments.
    #    Net Retained Earnings = Retained Earnings + Unrealized Gains.
    #    Only apply UG where property investments are non-zero (same mask
    #    used in the property block above).
    #    Always keep the UG series (even if all-zero) so the Less/Net rows
    #    remain visible on the balance sheet.
    _ug_series = _ug_vals_masked.copy()

    # 4a0. Add cumulative JV profit accrual to Retained Earnings -------------
    #      The consolidated IS includes "Share of Profit from JV" in Net Income
    #      via _postprocess_consolidated_is, but the entity-level BS Retained
    #      Earnings don't know about this.  Add the cumulative accrual here so
    #      the BS reflects the same profit as the IS.
    if jv_profit_accrual is not None and not jv_profit_accrual.empty:
        idx_str = result.index.astype(str)
        re_positions = np.where(idx_str == "Retained Earnings")[0]
        if len(re_positions) > 0:
            _re_cols = list(result.columns)
            _pa_vals = jv_profit_accrual.tolist()
            _aligned_pa = [float(_pa_vals[i]) if i < len(_pa_vals) else 0.0 for i in range(len(_re_cols))]
            _old_re = pd.to_numeric(result.iloc[int(re_positions[0])], errors="coerce").fillna(0.0)
            result.iloc[int(re_positions[0])] = (_old_re + pd.Series(_aligned_pa, index=_re_cols)).tolist()

    # 4a. Retained Earnings netting (always, independent of interparty netting)
    if not _ug_series.empty:
        _re_label = "Retained Earnings"
        idx_str = result.index.astype(str)
        re_positions = np.where(idx_str == _re_label)[0]
        if len(re_positions) > 0:
            pos = int(re_positions[0])
            gross_vals = pd.to_numeric(result.iloc[pos], errors="coerce").fillna(0.0)
            aligned_ug = _align_balance_to_columns(_ug_series, list(result.columns))
            net_vals = gross_vals + aligned_ug

            rows_after_re = []
            rows_after_re.append(pd.DataFrame(
                [aligned_ug.tolist()], index=["Less: Unrealized Gains (Equity)"], columns=result.columns,
            ))
            rows_after_re.append(pd.DataFrame(
                [net_vals.tolist()], index=["Net Retained Earnings"], columns=result.columns,
            ))
            rows_after_re.append(pd.DataFrame(
                [[None] * len(result.columns)], index=[""], columns=result.columns,
            ))

            idx_str_check = result.index.astype(str)
            prev_label = str(idx_str_check[pos - 1]).strip() if pos > 0 else ""
            if prev_label and prev_label not in ("", "nan", "None"):
                blank_before = pd.DataFrame(
                    [[None] * len(result.columns)], index=[""], columns=result.columns,
                )
                before = result.iloc[:pos]
                after = result.iloc[pos:]
                result = pd.concat([df for df in [before, blank_before, after] if not df.empty and not df.isna().all(axis=None)])
                idx_str = result.index.astype(str)
                re_positions = np.where(idx_str == _re_label)[0]
                pos = int(re_positions[0])

            before = result.iloc[: pos + 1]
            after = result.iloc[pos + 1 :]
            result = pd.concat(
                [df for df in [before] + rows_after_re + [after] if not df.empty and not df.isna().all(axis=None)]
            )

    # 4b. Interparty AR/AP and Advances/UR netting
    if interparty_netting is not None:
        _ar_net = interparty_netting.get("ar", pd.Series(dtype=float))
        _ur_net = interparty_netting.get("ur", pd.Series(dtype=float))

        # Process bottom-to-top to avoid position-shift issues
        _netting_specs = [
            ("Unearned Revenue",    _ur_net,    "Less: Interparty Advances/UR Netting (Liabilities)",  "Net Unearned Revenue"),
            ("Accounts Payable",    _ar_net,    "Less: Interparty AR/AP Netting (Liabilities)",        "Net Accounts Payable"),
            ("Advances for Land",   _ur_net,    "Less: Interparty Advances/UR Netting (Assets)",       "Net Advances for Land"),
            ("Accounts Receivable", _ar_net,    "Less: Interparty AR/AP Netting (Assets)",             "Net Accounts Receivable"),
        ]

        for gross_label, netting_vals, less_label, net_label in _netting_specs:
            idx_str = result.index.astype(str)
            positions = np.where(idx_str == gross_label)[0]
            if len(positions) == 0:
                continue
            pos = int(positions[0])

            gross_vals = pd.to_numeric(result.iloc[pos], errors="coerce").fillna(0.0)
            aligned = _align_balance_to_columns(netting_vals, list(result.columns))
            net_vals = gross_vals - aligned

            less_row = pd.DataFrame(
                [aligned.tolist()], index=[less_label], columns=result.columns,
            )
            net_row = pd.DataFrame(
                [net_vals.tolist()], index=[net_label], columns=result.columns,
            )
            blank_row = pd.DataFrame(
                [[None] * len(result.columns)], index=[""], columns=result.columns,
            )

            # Insert blank row before the gross label if the prior row is not
            # already blank (ensures visual separation for netting groups).
            idx_str_check = result.index.astype(str)
            prev_label = str(idx_str_check[pos - 1]).strip() if pos > 0 else ""
            if prev_label and prev_label not in ("", "nan", "None"):
                blank_before = pd.DataFrame(
                    [[None] * len(result.columns)], index=[""], columns=result.columns,
                )
                before = result.iloc[:pos]
                after = result.iloc[pos:]
                result = pd.concat([df for df in [before, blank_before, after] if not df.empty and not df.isna().all(axis=None)])
                # Recalculate position after insertion
                idx_str = result.index.astype(str)
                positions = np.where(idx_str == gross_label)[0]
                pos = int(positions[0])

            before = result.iloc[: pos + 1]
            after = result.iloc[pos + 1 :]
            result = pd.concat([df for df in [before, less_row, net_row, blank_row, after] if not df.empty and not df.isna().all(axis=None)])

    # 5b. Populate Investments in Associates from JV closing balance -------
    #     Use positional alignment: closing_balance has integer index (0,1,2,…)
    #     matching the monthly column positions of the BS.
    if jv_closing_balance is not None and not jv_closing_balance.empty:
        idx_str = result.index.astype(str)
        ia_positions = np.where(idx_str == "Investments in Associates")[0]
        if len(ia_positions) > 0:
            _ia_cols = list(result.columns)
            _cb_vals = jv_closing_balance.tolist()
            _aligned_cb = [float(_cb_vals[i]) if i < len(_cb_vals) else 0.0 for i in range(len(_ia_cols))]
            result.iloc[int(ia_positions[0])] = _aligned_cb

    # 5c. Add cumulative JV distributions to Cash and Cash Equivalents ------
    #     When the JV pays cash back to ROSHN, the entity-level BS has no record
    #     of this inflow.  Add the cumulative distributions here so the BS
    #     Cash balance reflects what was actually received from the JV.
    if jv_distributions is not None and not jv_distributions.empty:
        idx_str = result.index.astype(str)
        cash_positions = np.where(idx_str == "Cash and Cash Equivalents")[0]
        if len(cash_positions) > 0:
            _cash_cols = list(result.columns)
            _dist_vals = jv_distributions.tolist()
            _aligned_dist = [float(_dist_vals[i]) if i < len(_dist_vals) else 0.0 for i in range(len(_cash_cols))]
            _old_cash = pd.to_numeric(result.iloc[int(cash_positions[0])], errors="coerce").fillna(0.0)
            result.iloc[int(cash_positions[0])] = (_old_cash + pd.Series(_aligned_dist, index=_cash_cols)).tolist()

    # 5d. Deduct cumulative JV cash investments from Cash and Cash Equivalents --
    #     When ROSHN contributes cash equity to the JV, the entity-level BS has
    #     no record of this outflow.  Deduct the cumulative cash investments here
    #     so the BS Cash balance reflects what was actually paid into the JV.
    if jv_investments is not None and not jv_investments.empty:
        idx_str = result.index.astype(str)
        cash_positions = np.where(idx_str == "Cash and Cash Equivalents")[0]
        if len(cash_positions) > 0:
            _cash_cols = list(result.columns)
            _inv_vals = jv_investments.tolist()
            _aligned_inv = [float(_inv_vals[i]) if i < len(_inv_vals) else 0.0 for i in range(len(_cash_cols))]
            _old_cash = pd.to_numeric(result.iloc[int(cash_positions[0])], errors="coerce").fillna(0.0)
            result.iloc[int(cash_positions[0])] = (_old_cash - pd.Series(_aligned_inv, index=_cash_cols)).tolist()

    # 5e. Add LandCo CFF "Land In Kind" cumulative sum to Share Capital -------
    #     Land contributed in-kind to the JV is funded by shareholders; the
    #     credit side of "Dr Investments in Associates / Cr Share Capital"
    #     for the in-kind portion is recorded here.
    if jv_lik_cumsum is not None and not jv_lik_cumsum.empty:
        idx_str = result.index.astype(str)
        sc_positions = np.where(idx_str == "Share Capital")[0]
        if len(sc_positions) > 0:
            _sc_cols = list(result.columns)
            _lik_vals = jv_lik_cumsum.tolist()
            _aligned_lik = [float(_lik_vals[i]) if i < len(_lik_vals) else 0.0 for i in range(len(_sc_cols))]
            _old_sc = pd.to_numeric(result.iloc[int(sc_positions[0])], errors="coerce").fillna(0.0)
            result.iloc[int(sc_positions[0])] = (_old_sc + pd.Series(_aligned_lik, index=_sc_cols)).tolist()

    # 6. Collapse consecutive blank rows -----------------------------------
    idx_clean = result.index.astype(str).str.strip()
    is_blank = (idx_clean == "") | (idx_clean == "nan") | (idx_clean == "None")
    prev_blank = pd.Series(is_blank).shift(1, fill_value=False).values
    consecutive = is_blank & prev_blank
    result = result.loc[~consecutive]

    # 7. Recompute Total Assets / Total Liabilities / Total Equity ---------
    #    After post-processing the net rows have replaced gross+IE rows, so
    #    the totals inherited from entity-level presentable BSes are stale.
    #    Recompute them from the exact set of net line items.
    _TOTAL_ASSETS_ITEMS = [
        "Cash and Cash Equivalents",
        "Net Accounts Receivable",
        "Net Advances for Land",
        "Advance to Contractor",
        "Escrow Restricted Cash",
        "Restricted Cash - Sinking Fund",
        "Net Property Investments",
        "Accumulated Depreciation",
        "Investments in Associates",
    ]
    _TOTAL_LIABILITIES_ITEMS = [
        "Net Accounts Payable",
        "Net Unearned Revenue",
        "Debt - Revolver",
        "Debt - Term Loan",
        "Debt - Other",
    ]
    _TOTAL_EQUITY_ITEMS = [
        "Share Capital",
        "Net Retained Earnings",
        "Retained Earnings - Interparty Elimination",
    ]

    def _recompute_total(items: List[str]) -> pd.Series:
        total = pd.Series(0.0, index=result.columns)
        idx_s = result.index.astype(str)
        for item in items:
            positions = np.where(idx_s == item)[0]
            if len(positions) > 0:
                row_vals = pd.to_numeric(result.iloc[int(positions[0])], errors="coerce").fillna(0.0)
                total = total + row_vals
        return total

    _new_total_assets = _recompute_total(_TOTAL_ASSETS_ITEMS)
    _new_total_liabilities = _recompute_total(_TOTAL_LIABILITIES_ITEMS)
    _new_total_equity = _recompute_total(_TOTAL_EQUITY_ITEMS)

    idx_s = result.index.astype(str)
    for _label, _vals in [
        ("Total Assets", _new_total_assets),
        ("Total Liabilities", _new_total_liabilities),
        ("Total Equity", _new_total_equity),
        ("Total Liabilities + Equity", _new_total_liabilities + _new_total_equity),
    ]:
        _positions = np.where(idx_s == _label)[0]
        if len(_positions) > 0:
            result.iloc[int(_positions[0])] = _vals.tolist()

    return result


# ---------------------------------------------------------------------------
# Consolidated equity recalculation: balancing figure with cash carry-forward
# ---------------------------------------------------------------------------
def _postprocess_consolidated_equity_as_balancing(
    bs_df: pd.DataFrame,
    cf_df: pd.DataFrame,
    financial_statement_trace: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Replace entity-computed equity in the consolidated BS/CFS with a
    balancing-figure equity calculated using cash carry-forward.

    Entity models post equity period-by-period (each period's shortfall is
    covered independently). This function replaces that with a running-balance
    approach: surplus cash from one period reduces the equity that must be
    raised in a later deficit period.

    Algorithm:
      pre_equity_net[t] = Net Change in Cash[t] - entity equity[t]
      running_bal = 0
      for each period t:
          running_bal += pre_equity_net[t]
          if running_bal < 0:
              new_equity[t] = -running_bal
              running_bal = 0

    Only "Project and Asset Equity Contribution" (CFS), "Net Cash from
    Financing" (CFS), "Net Change in Cash" (CFS), "Share Capital" (BS), and
    "Cash and Cash Equivalents" (BS) are modified.  All other line items are
    unchanged.  BS totals are recomputed after the adjustment.
    """
    if cf_df.empty or bs_df.empty:
        return bs_df.copy(), cf_df.copy()

    cf_result = cf_df.copy()
    bs_result = bs_df.copy()

    cf_idx = cf_result.index.astype(str)
    bs_idx = bs_result.index.astype(str)

    _EQUITY_ROW  = "Project and Asset Equity Contribution"
    _NCC_ROW     = "Net Change in Cash"
    _CFF_NET_ROW = "Net Cash from Financing"

    eq_pos  = np.where(cf_idx == _EQUITY_ROW)[0]
    ncc_pos = np.where(cf_idx == _NCC_ROW)[0]
    cff_pos = np.where(cf_idx == _CFF_NET_ROW)[0]

    if len(eq_pos) == 0 or len(ncc_pos) == 0:
        return bs_result, cf_result

    entity_equity = (
        pd.to_numeric(cf_result.iloc[int(eq_pos[0])], errors="coerce")
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )
    net_change = (
        pd.to_numeric(cf_result.iloc[int(ncc_pos[0])], errors="coerce")
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )

    # Pre-equity net cash per period (excludes the entity-computed equity)
    pre_equity_net = net_change - entity_equity

    # Running-balance equity calculation
    n = len(pre_equity_net)
    new_equity  = np.zeros(n, dtype=np.float64)
    running_bal = 0.0
    for _t in range(n):
        running_bal += pre_equity_net[_t]
        if running_bal < 0.0:
            new_equity[_t] = -running_bal
            running_bal = 0.0

    equity_delta = new_equity - entity_equity          # periodic adjustment
    cum_delta    = np.cumsum(equity_delta)             # cumulative BS adjustment

    if np.all(np.abs(equity_delta) < 1e-6):
        return bs_result, cf_result

    # --- Update CFS ---
    cf_result.iloc[int(eq_pos[0])] = new_equity.tolist()

    if len(cff_pos) > 0:
        old_cff = (
            pd.to_numeric(cf_result.iloc[int(cff_pos[0])], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        cf_result.iloc[int(cff_pos[0])] = (old_cff + equity_delta).tolist()

    cf_result.iloc[int(ncc_pos[0])] = (pre_equity_net + new_equity).tolist()

    # --- Update BS (cumulative delta aligned to BS columns) ---
    n_bs = len(bs_result.columns)
    aligned_delta = np.zeros(n_bs, dtype=np.float64)
    copy_len = min(n, n_bs)
    aligned_delta[:copy_len] = cum_delta[:copy_len]

    sc_pos   = np.where(bs_idx == "Share Capital")[0]
    cash_pos = np.where(bs_idx == "Cash and Cash Equivalents")[0]

    new_sc_array: Optional[np.ndarray] = None
    if len(sc_pos) > 0:
        old_sc = (
            pd.to_numeric(bs_result.iloc[int(sc_pos[0])], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        new_sc_array = old_sc + aligned_delta
        bs_result.iloc[int(sc_pos[0])] = new_sc_array.tolist()

    if len(cash_pos) > 0:
        old_cash = (
            pd.to_numeric(bs_result.iloc[int(cash_pos[0])], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        bs_result.iloc[int(cash_pos[0])] = (old_cash + aligned_delta).tolist()

    # --- Recompute BS totals ---
    _TOTAL_ASSETS_ITEMS = [
        "Cash and Cash Equivalents", "Net Accounts Receivable", "Net Advances for Land",
        "Advance to Contractor", "Escrow Restricted Cash", "Restricted Cash - Sinking Fund",
        "Net Property Investments", "Accumulated Depreciation", "Investments in Associates",
    ]
    _TOTAL_LIABILITIES_ITEMS = [
        "Net Accounts Payable", "Net Unearned Revenue",
        "Debt - Revolver", "Debt - Term Loan", "Debt - Other",
    ]
    _TOTAL_EQUITY_ITEMS_LOCAL = [
        "Share Capital", "Net Retained Earnings", "Retained Earnings - Interparty Elimination",
    ]

    def _recompute_bs_total(items: List[str]) -> pd.Series:
        total = pd.Series(0.0, index=bs_result.columns)
        _idx_s = bs_result.index.astype(str)
        for _item in items:
            _pos = np.where(_idx_s == _item)[0]
            if len(_pos) > 0:
                total = total + pd.to_numeric(bs_result.iloc[int(_pos[0])], errors="coerce").fillna(0.0)
        return total

    _bs_idx_s = bs_result.index.astype(str)
    _new_ta  = _recompute_bs_total(_TOTAL_ASSETS_ITEMS)
    _new_tl  = _recompute_bs_total(_TOTAL_LIABILITIES_ITEMS)
    _new_te  = _recompute_bs_total(_TOTAL_EQUITY_ITEMS_LOCAL)
    for _lbl, _vals in [
        ("Total Assets",               _new_ta),
        ("Total Liabilities",          _new_tl),
        ("Total Equity",               _new_te),
        ("Total Liabilities + Equity", _new_tl + _new_te),
    ]:
        _p = np.where(_bs_idx_s == _lbl)[0]
        if len(_p) > 0:
            bs_result.iloc[int(_p[0])] = _vals.tolist()

    # --- Emit trace rows (only when trace is enabled) ---
    # Phase 7.1 is the sole authoritative source for Share Capital and
    # "Project and Asset Equity Contribution" in the trace.  Entity model traces
    # and the consolidated delta are stripped of these items (see trace assembly
    # below).
    #
    # CFS: new_equity[t] is the equity raised in period t (flow).
    # BS:  emit the period-over-period flow of new_sc_array so that
    #      _apply_balance_sheet_cumulative can reconstruct the full consolidated
    #      SC stock (which includes JV investment SC in addition to equity raises).
    if financial_statement_trace is not None:
        _cf_cols = list(cf_result.columns)
        _bs_cols = list(bs_result.columns)
        for _t_idx, _period in enumerate(_cf_cols):
            if _t_idx < n and abs(new_equity[_t_idx]) > 1e-6:
                fn_append_financial_statement_trace_row(
                    financial_statements=financial_statement_trace,
                    period=_period,
                    value=float(new_equity[_t_idx]),
                    financial_statement="Cashflow Statement",
                    line_item_name=_EQUITY_ROW,
                    asset_no="Consolidated",
                )
        if new_sc_array is not None:
            _sc_flow = np.diff(new_sc_array, prepend=0.0)
            for _t_idx, _period in enumerate(_bs_cols):
                _sc_val = float(_sc_flow[_t_idx])
                if abs(_sc_val) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=financial_statement_trace,
                        period=_period,
                        value=_sc_val,
                        financial_statement="Balance Sheet",
                        line_item_name="Share Capital",
                        asset_no="Consolidated",
                    )

    return bs_result, cf_result


# ---------------------------------------------------------------------------
# Helper: remove Interparty Elimination rows from a presentable DataFrame
# ---------------------------------------------------------------------------
def _postprocess_remove_ie_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove all rows whose index contains 'Interparty Eliminat' and
    collapse consecutive blank rows left behind."""
    if df.empty:
        return df.copy()

    result = df.copy()
    idx_str = result.index.astype(str)
    ie_mask = idx_str.str.contains("Interparty Eliminat", case=False, na=False)
    result = result.loc[~ie_mask]

    idx_clean = result.index.astype(str).str.strip()
    is_blank = (idx_clean == "") | (idx_clean == "nan") | (idx_clean == "None")
    prev_blank = pd.Series(is_blank).shift(1, fill_value=False).values
    consecutive = is_blank & prev_blank
    result = result.loc[~consecutive]

    return result


# ---------------------------------------------------------------------------
# Helper: build consolidated Income Statement from entity IS DataFrames
# ---------------------------------------------------------------------------
def _build_consolidated_income_statement(
    entity_is_dfs: List[pd.DataFrame],
) -> pd.DataFrame:
    """
    Align and sum entity-level Income Statement DataFrames into the
    consolidated IS proforma defined by ``_CONSOLIDATED_IS_PROFORMA``.

    Each entity IS is a presentable DataFrame whose index contains line-item
    labels, section headers, subtotal labels, and blank separator rows.
    This function:
      1. Extracts numeric line-item values from each entity IS.
      2. Sums them across entities.
      3. Re-presents the result according to the consolidated proforma
         with proper section headers, sub-headings, calculated subtotals,
         and blank separator rows.

    Parameters
    ----------
    entity_is_dfs : list of pd.DataFrame
        Non-empty list of entity IS DataFrames (from LandCo, DevCo, AssetCo).

    Returns
    -------
    pd.DataFrame
        Consolidated presentable Income Statement.
    """
    if not entity_is_dfs:
        return pd.DataFrame()

    # Use the columns from the first entity that has them.
    columns = entity_is_dfs[0].columns.tolist()

    # ------------------------------------------------------------------
    # 1. Build a merged line-item lookup: label → summed numeric values
    # ------------------------------------------------------------------
    n_cols = len(columns)
    merged: Dict[str, np.ndarray] = {}
    for df in entity_is_dfs:
        for label in df.index:
            if not label or not str(label).strip():
                continue
            try:
                vals = pd.to_numeric(df.loc[label], errors="coerce").fillna(0.0)
            except Exception:
                continue
            # Handle duplicate index: if loc returns DataFrame, sum rows.
            if isinstance(vals, pd.DataFrame):
                vals = vals.apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=0)
            arr = vals.reindex(columns, fill_value=0.0).to_numpy(dtype=np.float64)
            if label in merged:
                merged[label] = merged[label] + arr
            else:
                merged[label] = arr.copy()

    _zeros = np.zeros(n_cols, dtype=np.float64)

    def _get(label: str) -> np.ndarray:
        return merged.get(label, _zeros)

    def _sum_labels(labels: List[str]) -> np.ndarray:
        result = np.zeros(n_cols, dtype=np.float64)
        for lb in labels:
            result = result + _get(lb)
        return result

    def _negate(vals: np.ndarray) -> np.ndarray:
        return -vals

    def _add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a + b

    def _sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b

    # ------------------------------------------------------------------
    # 2. Gather all line items per major section
    # ------------------------------------------------------------------
    proforma = _CONSOLIDATED_IS_PROFORMA

    revenue_items: List[str] = []
    for cat, items in proforma["REVENUE"].items():
        revenue_items.extend(items)

    cos_items: List[str] = []
    for cat, items in proforma["COST OF SALES"].items():
        cos_items.extend(items)

    opex_items: List[str] = []
    for cat, items in proforma["OPERATING EXPENSES"].items():
        opex_items.extend(items)

    da_items: List[str] = []
    for cat, items in proforma["DEPRECIATION & AMORTIZATION"].items():
        da_items.extend(items)

    finance_items: List[str] = []
    for cat, items in proforma["FINANCE COSTS"].items():
        finance_items.extend(items)

    non_op_expense_items: List[str] = []
    non_op_income_items: List[str] = []
    _NON_OP_INCOME_CATS = {"Non-Operating Income"}
    for cat, items in proforma["NON-OPERATING ITEMS"].items():
        if cat in _NON_OP_INCOME_CATS:
            non_op_income_items.extend(items)
        elif items:
            non_op_expense_items.extend(items)

    # ------------------------------------------------------------------
    # 3. Calculate subtotals
    # ------------------------------------------------------------------
    # Recovery items within OPEX are income-side: they must be added to
    # EBITDA, not subtracted.  Separate them so EBITDA = GP - costs + recoveries.
    _OPEX_RECOVERY_ITEMS: set = {"Community Operations Recovery"}
    _opex_cost_items   = [i for i in opex_items if i not in _OPEX_RECOVERY_ITEMS]
    _opex_recov_items  = [i for i in opex_items if i in _OPEX_RECOVERY_ITEMS]

    total_revenue = _sum_labels(revenue_items)
    total_cos = _sum_labels(cos_items)
    gross_profit = _sub(total_revenue, total_cos)
    total_opex = _sub(_sum_labels(_opex_cost_items), _sum_labels(_opex_recov_items))
    ebitda = _sub(gross_profit, total_opex)
    total_da = _sum_labels(da_items)
    ebit = _sub(ebitda, total_da)
    total_finance = _sum_labels(finance_items)
    ebt = _sub(ebit, total_finance)
    total_non_op_exp = _sum_labels(non_op_expense_items)
    total_non_op_inc = _sum_labels(non_op_income_items)
    net_income = _sub(_sub(ebt, total_non_op_exp), _negate(total_non_op_inc))

    # Map subtotal label → values
    _subtotals = {
        "Total Revenue": total_revenue,
        "Gross Profit": gross_profit,
        "EBITDA": ebitda,
        "EBIT": ebit,
        "EBT": ebt,
        "Net Income": net_income,
    }

    # ------------------------------------------------------------------
    # 4. Build presentable rows
    # ------------------------------------------------------------------
    # Sections whose line-item values should be displayed as negative
    _EXPENSE_SECTIONS = {
        "COST OF SALES", "OPERATING EXPENSES",
        "DEPRECIATION & AMORTIZATION", "FINANCE COSTS",
    }

    output_index: List[str] = []
    output_rows: List[List] = []
    blank = [None] * n_cols

    for section_name, categories in proforma.items():
        # Section header
        output_index.append(section_name)
        output_rows.append(list(blank))
        output_index.append("")
        output_rows.append(list(blank))

        for cat_name, items in categories.items():
            if items:
                # Category sub-heading
                if cat_name:
                    output_index.append(cat_name)
                    output_rows.append(list(blank))

                # Determine if line items should be shown as negative
                negate_items = (
                    section_name in _EXPENSE_SECTIONS
                    or (section_name == "NON-OPERATING ITEMS"
                        and cat_name != "Non-Operating Income")
                )

                # Line items
                for item in items:
                    output_index.append(item)
                    vals = _get(item)
                    # Recovery items within an expense section keep their
                    # positive sign (they reduce the net expense cost).
                    if negate_items and item not in _OPEX_RECOVERY_ITEMS:
                        vals = _negate(vals)
                    output_rows.append(vals.tolist())
                output_index.append("")
                output_rows.append(list(blank))
            else:
                # Calculated subtotal row
                output_index.append(cat_name)
                subtotal = _subtotals.get(cat_name)
                output_rows.append(subtotal.tolist() if subtotal is not None else [0.0] * n_cols)
                output_index.append("")
                output_rows.append(list(blank))

    return pd.DataFrame(
        data=output_rows, index=output_index, columns=columns, dtype=object,
    )


def _annualize_monthly_df(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a monthly presentable financial-statement DataFrame into annual
    by grouping columns on calendar year and summing numeric cells.

    Non-numeric rows (section headers, blank rows) are preserved.
    """
    if monthly_df.empty:
        return monthly_df.copy()

    col_dates = pd.to_datetime(monthly_df.columns, errors="coerce")
    year_labels = col_dates.strftime("%Y")
    unique_years = sorted(set(y for y in year_labels if y != "NaT"))

    if not unique_years:
        return monthly_df.copy()

    n_rows = len(monthly_df)

    # Vectorized numeric conversion: non-numeric cells become NaN
    float_arr = monthly_df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)

    # Identify numeric rows: any non-NaN value in any column
    numeric_row_mask = ~np.isnan(float_arr).all(axis=1)

    # Replace NaN with 0 for summation (in-place)
    np.nan_to_num(float_arr, nan=0.0, copy=False)

    # Build year-to-column-indices mapping
    year_col_map: Dict[str, List[int]] = {}
    for c, yr in enumerate(year_labels):
        if yr != "NaT":
            year_col_map.setdefault(yr, []).append(c)

    # Sum columns per year using numpy advanced indexing
    n_years = len(unique_years)
    annual_float = np.empty((n_rows, n_years), dtype=np.float64)
    for yi, yr in enumerate(unique_years):
        annual_float[:, yi] = float_arr[:, year_col_map[yr]].sum(axis=1)

    annual_arr = annual_float.astype(object)
    annual_arr[~numeric_row_mask] = None

    return pd.DataFrame(
        data=annual_arr,
        index=monthly_df.index,
        columns=unique_years,
        dtype=object,
    )


def _annualize_monthly_bs(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a monthly Balance Sheet DataFrame into annual by picking the
    **last month** (period-end) column in each calendar year.

    Non-numeric rows (section headers, blank rows) are preserved as None.
    """
    if monthly_df.empty:
        return monthly_df.copy()

    col_dates = pd.to_datetime(monthly_df.columns, errors="coerce")
    year_labels = col_dates.strftime("%Y")
    unique_years = sorted(set(y for y in year_labels if y != "NaT"))

    if not unique_years:
        return monthly_df.copy()

    # For each year find the index of the last monthly column
    last_col_idx: Dict[str, int] = {}
    for col_idx, yr in enumerate(year_labels):
        if yr != "NaT":
            last_col_idx[yr] = col_idx  # overwrites → keeps the last

    n_rows = len(monthly_df)

    # Vectorized numeric detection and value extraction
    float_arr = monthly_df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    numeric_row_mask = ~np.isnan(float_arr).all(axis=1)

    # Extract last-month column per year using numpy fancy indexing
    last_col_indices = [last_col_idx[yr] for yr in unique_years]
    annual_float = float_arr[:, last_col_indices]  # shape (n_rows, n_years)
    annual_arr = annual_float.astype(object)
    annual_arr[~numeric_row_mask] = None

    return pd.DataFrame(
        data=annual_arr,
        index=monthly_df.index,
        columns=unique_years,
        dtype=object,
    )


# ---------------------------------------------------------------------------
# Helper: reconstruct a DataFrame from the JSON-serializable payload
# ---------------------------------------------------------------------------
def _payload_to_dataframe(payload: Dict[str, Any]) -> pd.DataFrame:
    """Convert a ``{index, columns, data}`` payload back to a DataFrame."""
    return pd.DataFrame(
        data=payload["data"],
        index=payload["index"],
        columns=payload["columns"],
    )


def _dataframe_to_payload(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"index": [], "columns": [], "data": []}

    # Fast path for index/columns
    def _safe_convert(x):
        if pd.isna(x) or (isinstance(x, float) and x != x):
            return None
        if isinstance(x, (pd.Timestamp, pd.Period)):
            return x.strftime("%Y-%m-%d")
        return x

    safe_index = [_safe_convert(i) for i in df.index]
    safe_columns = [_safe_convert(c) for c in df.columns]

    # Vectorized data conversion (much faster than per-cell Python loop)
    data = df.to_numpy(dtype=object, copy=False).tolist()
    
    for row in data:
        for j in range(len(row)):
            v = row[j]
            if v is None or (isinstance(v, float) and (v != v or np.isnan(v))):
                row[j] = None
            elif isinstance(v, (pd.Timestamp, pd.Period)):
                row[j] = v.strftime("%Y-%m-%d")

    return {
        "index": safe_index,
        "columns": safe_columns,
        "data": data
    }


def _build_asset_index_to_uid_lookup(payload: Any) -> Dict[str, str]:
    """Build asset-key -> Asset Unique Identifier lookup for trace replacement."""
    if not isinstance(payload, dict):
        return {}

    lookup: Dict[str, str] = {}

    def _normalize_uid(uid_value: Any) -> Optional[str]:
        if uid_value is None:
            return None
        uid_text = str(uid_value).strip()
        if uid_text == "" or uid_text.lower() in {"none", "nan", "nat"}:
            return None
        return uid_text

    def _add_mapping(key_value: Any, uid_text: str) -> None:
        key = _normalize_asset_index_key(key_value)
        if key is not None:
            lookup.setdefault(key, uid_text)

    # # Primary mapping source for AssetCo:
    # # payload["assetco_consolidated"][idx]["output_json"]["assetco_inputs"]["asset_unique_id"]
    # assetco_items = payload.get("assetco_consolidated", [])
    # if isinstance(assetco_items, list):
    #     for idx, asset_item in enumerate(assetco_items):
    #         if not isinstance(asset_item, dict):
    #             continue

    #         output_json = asset_item.get("output_json", {})
    #         assetco_inputs = output_json.get("assetco_inputs", {}) if isinstance(output_json, dict) else {}
    #         if not isinstance(assetco_inputs, dict):
    #             assetco_inputs = {}

    #         uid_text = _normalize_uid(assetco_inputs.get("asset_unique_id"))
    #         if uid_text is None:
    #             continue

    #         # idx-based keying is the authoritative AssetCo mapping requested.
    #         _add_mapping(idx, uid_text)
    #         _add_mapping(f"idx:{idx}", uid_text)

    #         # Also map known asset labels that may appear in trace rows.
    #         _add_mapping(asset_item.get("asset_id"), uid_text)
    #         _add_mapping(asset_item.get("asset_identifier"), uid_text)
    #         _add_mapping(assetco_inputs.get("asset_id"), uid_text)
    #         _add_mapping(assetco_inputs.get("asset_no"), uid_text)
    #         _add_mapping(assetco_inputs.get("asset_identifier"), uid_text)

    # LandCo ProjectDetails indexing.
    landco_source = payload.get("landco", {})
    if isinstance(landco_source, dict):
        landco_asset_assumptions = landco_source.get("asset_assumptions", {})
        if isinstance(landco_asset_assumptions, dict):
            uid_series = fn_extract_assumptions(
                landco_asset_assumptions,
                "ProjectDetails",
                "asset_unique_identifier",
            )
            if isinstance(uid_series, pd.Series) and not uid_series.empty:
                for idx_value, uid in uid_series.items():
                    uid_text = _normalize_uid(uid)
                    if uid_text is None:
                        continue
                    _add_mapping(idx_value, uid_text)

    return lookup


def _normalize_asset_index_key(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if text == "":
        return None

    lowered = text.lower()
    if lowered in {"none", "nan", "nat", "unknown", "consolidated"}:
        return None

    if lowered.startswith("asset "):
        text = text[6:].strip()
        if text == "":
            return None

    # Depreciation trace rows may carry month markers, e.g.
    # "10 (month 100/360" or "10 (month 100/360)".
    # Strip the suffix so the base asset key can resolve to UID.
    text = _re.sub(
        r"\s*\(\s*month\s+\d+\s*/\s*\d+\s*\)?\s*$",
        "",
        text,
        flags=_re.IGNORECASE,
    ).strip()
    if text == "":
        return None

    try:
        parsed = float(text)
        if np.isfinite(parsed) and parsed.is_integer():
            return str(int(parsed))
    except Exception:
        pass

    return text


def _replace_trace_asset_no_with_uid(
    trace_df: pd.DataFrame,
    asset_index_to_uid: Dict[str, str],
) -> pd.DataFrame:
    """Replace Asset No. values with Asset Unique Identifier where resolvable."""
    if (
        not isinstance(trace_df, pd.DataFrame)
        or trace_df.empty
        or "Asset No." not in trace_df.columns
        or not asset_index_to_uid
    ):
        return trace_df

    updated = trace_df.copy()

    def _map_asset_no(raw_value: Any) -> Any:
        key = _normalize_asset_index_key(raw_value)
        if key is None:
            return raw_value
        return asset_index_to_uid.get(key, raw_value)

    updated["Asset No."] = updated["Asset No."].map(_map_asset_no)
    return updated


# ---------------------------------------------------------------------------
# Helper: sum financial-statement DataFrames across models
# ---------------------------------------------------------------------------
_FINANCIAL_STATEMENT_SHEETS = [
    "Cashflow Statement",
    "Income Statement",
    "Balance Sheet",
]


def _zero_numeric_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy where numeric cells are replaced with 0 and labels stay intact."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    zeroed_df = df.copy()
    for col in zeroed_df.columns:
        numeric_col = pd.to_numeric(zeroed_df[col], errors="coerce")
        numeric_mask = numeric_col.notna()
        if numeric_mask.any():
            zeroed_df.loc[numeric_mask, col] = 0.0

    return zeroed_df


def _build_zero_financial_statement_result(
    template_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build a model-like result carrying only zeroed financial-statement sheets.

    This is used when a module filter is explicitly invalid and should not
    fall back to consolidated entity inclusion.
    """
    empty_result: Dict[str, Any] = {"monthly_dfs": {}, "annual_dfs": {}}
    if not isinstance(template_result, dict):
        return empty_result

    template_monthly = template_result.get("monthly_dfs", {})
    template_annual = template_result.get("annual_dfs", {})
    zero_monthly_dfs: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    zero_annual_dfs: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    monthly_code_overrides: Dict[str, str] = {
        "Cashflow Statement": "o.consolidated.cfs.me",
        "Income Statement": "o.consolidated.is.me",
        "Balance Sheet": "o.consolidated.bs.me",
    }

    for sheet_name in _FINANCIAL_STATEMENT_SHEETS:
        entry = template_monthly.get(sheet_name)
        if entry is None:
            continue
        entry_code, entry_payload = entry
        entry_df = _payload_to_dataframe(entry_payload)
        zero_monthly_dfs[sheet_name] = (
            monthly_code_overrides.get(sheet_name, entry_code),
            _dataframe_to_payload(_zero_numeric_cells(entry_df)),
        )

    annual_code_overrides: Dict[str, str] = {
        "Cashflow Statement": "o.consolidated.cfs.ye",
        "Income Statement": "o.consolidated.is.ye",
        "Balance Sheet": "o.consolidated.bs.ye",
    }

    for sheet_name in _FINANCIAL_STATEMENT_SHEETS:
        annual_entry = template_annual.get(sheet_name)
        if annual_entry is not None:
            annual_code, annual_payload = annual_entry
            annual_df = _payload_to_dataframe(annual_payload)
            zero_annual_dfs[sheet_name] = (
                annual_code_overrides.get(sheet_name, annual_code),
                _dataframe_to_payload(_zero_numeric_cells(annual_df)),
            )
            continue

        monthly_entry = zero_monthly_dfs.get(sheet_name)
        if monthly_entry is None:
            continue

        _, monthly_payload = monthly_entry
        monthly_df = _payload_to_dataframe(monthly_payload)
        if sheet_name == "Balance Sheet":
            annual_df = _annualize_monthly_bs(monthly_df)
        else:
            annual_df = _annualize_monthly_df(monthly_df)

        zero_annual_dfs[sheet_name] = (
            annual_code_overrides.get(sheet_name, monthly_entry[0]),
            _dataframe_to_payload(annual_df),
        )

    return {
        "monthly_dfs": zero_monthly_dfs,
        "annual_dfs": zero_annual_dfs,
    }


def _sum_monthly_financial_statements(
    model_results: List[Dict[str, Any]],
) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """
    Sum monthly financial-statement DataFrames across models.

    Only the sheets listed in ``_FINANCIAL_STATEMENT_SHEETS`` are summed.
    Non-numeric cells (row labels, header text) are preserved from the first
    model that provides each sheet.

    Parameters
    ----------
    model_results : list of dicts
        Each dict is a non-None model result with a ``"monthly_dfs"`` key.

    Returns
    -------
    dict
        ``{sheet_name: (code, payload)}`` ready for inclusion in an
        ``excel_output``-style structure.
    """
    summed: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    for sheet_name in _FINANCIAL_STATEMENT_SHEETS:
        dfs: List[pd.DataFrame] = []
        code: Optional[str] = None

        for result in model_results:
            monthly_dfs = result.get("monthly_dfs", {})
            entry = monthly_dfs.get(sheet_name)
            if entry is None:
                continue
            entry_code, entry_payload = entry
            if code is None:
                code = entry_code
            df = _payload_to_dataframe(entry_payload)
            if sheet_name == "Cashflow Statement":
                df = _normalize_cashflow_hospitality_to_ebitda(df)
            dfs.append(df)

        if not dfs:
            continue

        # Start from the first DF as the base (preserves non-numeric cells).
        base_df = dfs[0].copy()

        # Vectorized numeric conversion
        base_float = base_df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
        n_rows, n_cols_base = base_float.shape
        numeric_mask = ~np.isnan(base_float)
        base_numeric = np.where(numeric_mask, base_float, 0.0)

        for additional_df in dfs[1:]:
            has_dupes = (
                additional_df.index.has_duplicates or base_df.index.has_duplicates
            )
            length_mismatch = len(additional_df) != len(base_df)

            if has_dupes or length_mismatch:
                # Presentable statements have blank/section rows with
                # duplicate index labels and may differ in row count
                # across models.  Sum by matching uniquely-identifiable
                # non-empty labels; formatting rows are left untouched.
                additional_numeric = additional_df.apply(
                    pd.to_numeric, errors="coerce"
                ).fillna(0.0)

                # Wrap base_numeric back into a DataFrame for label-based addition
                base_numeric_df = pd.DataFrame(base_numeric, index=base_df.index, columns=base_df.columns)
                for label in set(additional_numeric.index):
                    if not label:
                        continue
                    base_hits = (base_numeric_df.index == label).sum()
                    add_hits = (additional_numeric.index == label).sum()
                    if base_hits == 1 and add_hits == 1:
                        base_numeric_df.loc[label] = (
                            base_numeric_df.loc[label].values
                            + additional_numeric.loc[label].values
                        )
                base_numeric = base_numeric_df.to_numpy(dtype=np.float64)
            else:
                # Vectorized numeric conversion of additional DF
                add_float = (
                    additional_df
                    .reindex(index=base_df.index, columns=base_df.columns)
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                    .to_numpy(dtype=np.float64)
                )
                base_numeric = base_numeric + add_float

        # Overlay numeric sums onto the base, keeping non-numeric cells intact.
        result_arr = base_df.to_numpy(dtype=object, copy=True)
        result_arr[numeric_mask] = base_numeric[numeric_mask]
        result_df = pd.DataFrame(result_arr, index=base_df.index, columns=base_df.columns)

        summed[sheet_name] = (code, _dataframe_to_payload(result_df))

    return summed


# ---------------------------------------------------------------------------
# Export flags check
# ---------------------------------------------------------------------------
def fn_is_export_enabled(export_flags: Dict[str, bool], section_name: str) -> bool:
    """Return True if export is enabled for *section_name* (or ``all_sections``)."""
    return bool(export_flags.get("all_sections", False) or export_flags.get(section_name, False))


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------
def _sanitize_sheet_name(name: str) -> str:
    """Truncate and strip invalid Excel sheet-name characters."""
    for ch in ("\\", "/", "*", "?", ":", "[", "]"):
        name = name.replace(ch, "-")
    return name[:31]


def fn_export_dataframes_to_excel(
    dataframes_dict: Dict[str, Any],
    filename: str,
    description: str,
) -> Optional[str]:
    """
    Export a dictionary of DataFrames / payloads to an Excel file.

    Values may be ``pd.DataFrame`` instances or ``{index, columns, data}``
    payload dicts - both are handled.
    """
    if not dataframes_dict:
        return None

    try:
        base_dir = os.path.dirname(__file__)
        output_name = filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx"
        excel_path = os.path.join(base_dir, output_name)
        used: set = set()

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for raw_name, raw_value in dataframes_dict.items():
                sheet = _sanitize_sheet_name(raw_name)
                candidate = sheet
                dup = 1
                while candidate.lower() in used:
                    suffix = f"_{dup}"
                    candidate = f"{sheet[: 31 - len(suffix)]}{suffix}"
                    dup += 1
                used.add(candidate.lower())

                if isinstance(raw_value, pd.DataFrame):
                    df = raw_value
                elif isinstance(raw_value, dict) and "data" in raw_value:
                    df = _payload_to_dataframe(raw_value)
                else:
                    df = pd.DataFrame([{"value": str(raw_value)}])

                df.to_excel(writer, sheet_name=candidate, index=True)

        print(f"  Exported {description} to: {excel_path}")
        if hasattr(os, "startfile"):
            os.startfile(excel_path)
        return excel_path
    except Exception as exc:
        print(f"  Error exporting {description}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Export consolidated output to Excel
# ---------------------------------------------------------------------------
def fn_export_consolidated_output(
    excel_output: Dict[str, Any],
    filename: str = "consolidated_output.xlsx",
) -> None:
    """
    Export the consolidated ``excel_output`` dict to an Excel file.

    Sheet names are prefixed with ``M_`` (monthly) and ``A_`` (annual),
    truncated to 31 characters (Excel limit).
    """
    base_dir = os.path.dirname(__file__)
    filepath = os.path.join(base_dir, filename)

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        for sheet_name, (code, df_json) in excel_output.get("monthly_dfs", {}).items():
            df = pd.DataFrame(
                df_json["data"],
                index=df_json["index"],
                columns=df_json["columns"],
            )
            df.to_excel(writer, sheet_name=f"M_{sheet_name}"[:31])

        for sheet_name, (code, df_json) in excel_output.get("annual_dfs", {}).items():
            df = pd.DataFrame(
                df_json["data"],
                index=df_json["index"],
                columns=df_json["columns"],
            )
            df.to_excel(writer, sheet_name=f"A_{sheet_name}"[:31])

    print(f"Consolidated output exported to {filepath}")
    if hasattr(os, "startfile"):
        os.startfile(filepath)


_ENTITY_MODEL_PAYLOAD_KEYS: Tuple[str, ...] = (
    "landco",
    "devco",
    "assetco_consolidated",
    "jv_consolidation",
    "_asset_filter_mode",
    "_synthetic_asset_ids",
    "_module_filter_mode",
    _TRACE_ENABLE_PAYLOAD_KEY,
    _LIGHTWEIGHT_ENTITY_OUTPUT_PAYLOAD_KEY,
)


def _build_entity_payload_slice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only top-level payload keys consumed by entity model wrappers."""
    if not isinstance(payload, dict):
        return {}
    return {key: payload.get(key) for key in _ENTITY_MODEL_PAYLOAD_KEYS if key in payload}


def _serialize_entity_payload_pickle(payload: Dict[str, Any]) -> str:
    """Serialize the process payload once and share the path with workers."""
    fd, payload_pickle_path = tempfile.mkstemp(prefix="conso_entity_payload_", suffix=".pkl")
    try:
        with os.fdopen(fd, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            if os.path.exists(payload_pickle_path):
                os.remove(payload_pickle_path)
        except Exception:
            pass
        raise
    return payload_pickle_path


def _load_entity_payload_from_pickle(payload_pickle_path: str) -> Dict[str, Any]:
    with open(payload_pickle_path, "rb") as handle:
        loaded = pickle.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _run_landco_model_with_pickled_payload(payload_pickle_path: str) -> Optional[Any]:
    return landco_consolidation_wrapper.fninitialising_all_values(
        _load_entity_payload_from_pickle(payload_pickle_path)
    )


def _run_devco_model_with_pickled_payload(payload_pickle_path: str) -> Optional[Any]:
    return devco_consolidation_wrapper.fninitialising_all_values(
        _load_entity_payload_from_pickle(payload_pickle_path)
    )


def _run_assetco_model_with_pickled_payload(payload_pickle_path: str) -> Optional[Any]:
    return assetco_consolidation_wrapper.fninitialising_all_values(
        _load_entity_payload_from_pickle(payload_pickle_path)
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def fninitialising_all_values(payload: Any, is_save=None) -> Optional[Any]:
    try:
        # import json
        # with open("payload_debug.json", "w", encoding="utf-8") as f:
        #     json.dump(payload, f, indent=2, ensure_ascii=False)
        # raise breakpoint("Debug: payload dumped to payload_debug.json")
        if payload is None:
            print("Error in fninitialising_all_values: payload cannot be None")
            return None
        if not isinstance(payload, (dict, list)):
            print(
                "Error in fninitialising_all_values: payload must be a dictionary or list, "
                f"got {type(payload).__name__}"
            )
            return None

        _timing_ctx = fn_create_timing_context()

        _asset_index_to_uid = _build_asset_index_to_uid_lookup(payload)
        
        if isinstance(payload, dict):
            payload[_TRACE_ENABLE_PAYLOAD_KEY] = _ENABLE_FINANCIAL_STATEMENT_TRACE
            payload[_LIGHTWEIGHT_ENTITY_OUTPUT_PAYLOAD_KEY] = True

        # ------------------------------------------------------------------
        # Extract Asset Filter Mode from Payload Named Ranges
        # ------------------------------------------------------------------
        _asset_filter_mode = "Consolidated"
        _synthetic_asset_ids: List[str] = []
        try:
            _named_ranges = payload.get("namedRanges", [])
            if _named_ranges:
                _nr_lookup = {nr["name"]: nr for nr in _named_ranges}
                _filtration_attr_key = "m.jv.global.attribute"
                _filtration_val_key = "m.jv.global.value"
                if _filtration_attr_key in _nr_lookup and _filtration_val_key in _nr_lookup:
                    _attr_list = [row[0] for row in _nr_lookup[_filtration_attr_key]["values"]]
                    _value_list = [row[0] for row in _nr_lookup[_filtration_val_key]["values"]]
                    if "asset_id" in _attr_list:
                        _asset_filter_raw_value = str(_value_list[_attr_list.index("asset_id")]).strip()
                        _asset_filter_lower = _asset_filter_raw_value.lower()

                        if _asset_filter_lower == "consolidated" or _asset_filter_raw_value == "":
                            _asset_filter_mode = "Consolidated"
                        elif _asset_filter_lower == "synthetic":
                            _asset_filter_mode = "Synthetic"
                        else:
                            _asset_filter_mode = _asset_filter_raw_value
                            
                    print(f"Asset filter mode resolved from payload: '{_asset_filter_mode}'")

            if _asset_filter_mode.strip().lower() == "synthetic":
                _synthetic_asset_ids = fn_extract_synthetic_asset_ids_from_mastersheet(payload)
                if _synthetic_asset_ids:
                    print(
                        "Synthetic asset filter resolved "
                        f"{len(_synthetic_asset_ids)} asset(s): {_synthetic_asset_ids[:10]}"
                    )
                else:
                    print(
                        "WARNING: Synthetic asset filter selected but no 'Yes' rows were "
                        "resolved from MasterSheet output_inclusion. "
                        "Proceeding with an empty synthetic set (all-zero output)."
                    )
        except Exception as _filter_exc:
            print(f"Warning: Could not extract asset filter mode from payload: {_filter_exc}")
            _asset_filter_mode = "Consolidated"
            _synthetic_asset_ids = []

        # ------------------------------------------------------------------
        # Extract Module Filter Mode from Payload Named Ranges
        # ------------------------------------------------------------------
        _module_filter_mode = "Consolidated"
        _module_filter_is_invalid = False
        try:
            _named_ranges = payload.get("namedRanges", [])
            if _named_ranges:
                _nr_lookup = {nr["name"]: nr for nr in _named_ranges}
                _filtration_attr_key = "m.jv.global.attribute"
                _filtration_val_key = "m.jv.global.value"
                if _filtration_attr_key in _nr_lookup and _filtration_val_key in _nr_lookup:
                    _attr_list = [row[0] for row in _nr_lookup[_filtration_attr_key]["values"]]
                    _value_list = [row[0] for row in _nr_lookup[_filtration_val_key]["values"]]
                    if "module_name" in _attr_list:
                        _module_filter_value = str(_value_list[_attr_list.index("module_name")]).strip()
                        _VALID_MODULE_FILTERS = {
                            "consolidated", "landco", "devco", "assetco",
                            "landco + devco", "devco + assetco",
                        }
                        if _module_filter_value.lower() in _VALID_MODULE_FILTERS:
                            _module_filter_mode = _module_filter_value
                        elif _module_filter_value == "":
                            _module_filter_mode = "Consolidated"
                        else:
                            _module_filter_mode = _module_filter_value
                            _module_filter_is_invalid = True
                            print(
                                "WARNING: Invalid module filter "
                                f"'{_module_filter_value}' selected. "
                                "No modules will be included; financial statements will be zeroed."
                            )
                    print(f"Module filter mode resolved from payload: '{_module_filter_mode}'")
        except Exception as _mfilter_exc:
            print(f"Warning: Could not extract module filter mode from payload: {_mfilter_exc}")
            _module_filter_mode = "Consolidated"
            _module_filter_is_invalid = False

        if _ENABLE_FINANCIAL_STATEMENT_TRACE:
            if (
                _asset_filter_mode.strip().lower() != "consolidated"
                or _module_filter_mode.strip().lower() != "consolidated"
            ):
                print(
                    "Financial statement trace enabled: forcing asset and module "
                    "filter modes to 'Consolidated'."
                )
            _asset_filter_mode = "Consolidated"
            _module_filter_mode = "Consolidated"
            _synthetic_asset_ids = []
            _module_filter_is_invalid = False

        payload["_asset_filter_mode"] = _asset_filter_mode
        payload["_synthetic_asset_ids"] = _synthetic_asset_ids
        payload["_module_filter_mode"] = _module_filter_mode

        # ------------------------------------------------------------------
        # Export Flags Configuration
        # ------------------------------------------------------------------
        _EXPORT_FLAGS: Dict[str, bool] = {
            "all_sections": False,
            "consolidated_output": False,
            "landco_output": False,
            "devco_output": False,
            "assetco_output": False,
            "landco_accounts": False,
            "devco_accounts": False,
            "assetco_accounts": False,
            "landco_journal": False,
            "devco_journal": False,
            "assetco_journal": False,
            "combined_journal": False,
        }

        fn_record_timing(_timing_ctx, "PHASE 0: Initialization")

        # ------------------------------------------------------------------
        # Run the three consolidation models in parallel
        # ------------------------------------------------------------------
        
        future_landco = None
        future_devco = None
        future_assetco = None

        # filename = f"payload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        # with open(filename, "w", encoding="utf-8") as f:
        #     json.dump(payload, f, indent=4, ensure_ascii=False)

        _entity_process_payload = payload if isinstance(payload, dict) else {}
        _entity_payload_pickle_path = _serialize_entity_payload_pickle(_entity_process_payload)
        try:
            _entity_worker_count = max(1, min(3, os.cpu_count() or 1))
            executor = _get_entity_process_pool(_entity_worker_count)
            fn_record_timing(_timing_ctx, "PHASE 0.1: Start Parallel Execution of Entity Models")
            future_landco = executor.submit(
                _run_landco_model_with_pickled_payload,
                _entity_payload_pickle_path,
            )
            future_devco = executor.submit(
                _run_devco_model_with_pickled_payload,
                _entity_payload_pickle_path,
            )
            future_assetco = executor.submit(
                _run_assetco_model_with_pickled_payload,
                _entity_payload_pickle_path,
            )

            landco_result = future_landco.result() if future_landco else None
            devco_result = future_devco.result() if future_devco else None
            assetco_result = future_assetco.result() if future_assetco else None
        finally:
            try:
                if os.path.exists(_entity_payload_pickle_path):
                    os.remove(_entity_payload_pickle_path)
            except Exception:
                pass

        fn_record_timing(_timing_ctx, "PHASE 1: Run Entity Models (parallel)")

        # ------------------------------------------------------------------
        # Collect non-None results for summation
        # ------------------------------------------------------------------
        # Always validate all models ran (even if filtered later)
        if landco_result is None:
            print("Warning: LandCo model returned None.")
        if devco_result is None:
            print("Warning: DevCo model returned None.")
        if assetco_result is None:
            print("Warning: AssetCo model returned None.")

        # ------------------------------------------------------------------
        # Gate module results based on _module_filter_mode
        # ------------------------------------------------------------------
        _module_filter_lower = _module_filter_mode.lower()
        _include_landco = _module_filter_lower in (
            "consolidated", "landco", "landco + devco",
        )
        _include_devco = _module_filter_lower in (
            "consolidated", "devco", "landco + devco", "devco + assetco",
        )
        _include_assetco = _module_filter_lower in (
            "consolidated", "assetco", "devco + assetco",
        )

        _model_results: List[Dict[str, Any]] = []
        if _include_landco and landco_result is not None:
            _model_results.append(landco_result)
        elif _include_landco:
            print("Warning: LandCo included in module filter but returned None — skipping.")
        if _include_devco and devco_result is not None:
            _model_results.append(devco_result)
        elif _include_devco:
            print("Warning: DevCo included in module filter but returned None — skipping.")
        if _include_assetco and assetco_result is not None:
            _model_results.append(assetco_result)
        elif _include_assetco:
            print("Warning: AssetCo included in module filter but returned None — skipping.")

        if not _model_results:
            if _module_filter_is_invalid:
                _template_result = next(
                    (
                        result
                        for result in (landco_result, devco_result, assetco_result)
                        if isinstance(result, dict)
                    ),
                    None,
                )
                if _template_result is None:
                    print(
                        "Error: Invalid module filter selected but no entity template result "
                        "is available to build zero financial statements."
                    )
                    return None

                _model_results = [_build_zero_financial_statement_result(_template_result)]
                print(
                    "Invalid module filter mode detected: consolidated output will "
                    "contain zero-valued financial statements only."
                )
            else:
                print("Error: No models available for selected module filter — nothing to consolidate.")
                return None

        # ------------------------------------------------------------------
        # Build elimination results: only the seller entity for the relevant
        # interparty relationship to ensure correct elimination scoping.
        #
        # LandCo→DevCo interparty tracking accounts live in LandCo's results.
        # DevCo→AssetCo interparty tracking accounts live in DevCo's results.
        # ------------------------------------------------------------------
        _elimination_results: List[Dict[str, Any]] = []
        if _module_filter_lower == "consolidated":
            # Full consolidation: all interparty eliminations
            _elimination_results = list(_model_results)
        elif _module_filter_lower == "landco + devco":
            # Only LandCo→DevCo eliminations (tracked in LandCo's accounts)
            if landco_result is not None:
                _elimination_results.append(landco_result)
        elif _module_filter_lower == "devco + assetco":
            # Only DevCo→AssetCo eliminations (tracked in DevCo's accounts)
            if devco_result is not None:
                _elimination_results.append(devco_result)
        # Individual modules (landco, devco, assetco): no eliminations
        # _elimination_results stays empty

        print(f"Module filter '{_module_filter_mode}': "
              f"included={sum([_include_landco, _include_devco, _include_assetco])} modules, "
              f"elimination_sources={len(_elimination_results)}")

        fn_record_timing(_timing_ctx, "PHASE 2: Collect Results & Apply Module Filter")

        # ------------------------------------------------------------------
        # Extract explicit monthly financial-statement DFs per model
        # (gated by module filter — only selected modules)
        # ------------------------------------------------------------------
        _landco_monthly_dfs = (
            landco_result.get("monthly_dfs", {})
            if _include_landco and landco_result is not None else {}
        )
        _devco_monthly_dfs = (
            devco_result.get("monthly_dfs", {})
            if _include_devco and devco_result is not None else {}
        )
        _assetco_monthly_dfs = (
            assetco_result.get("monthly_dfs", {})
            if _include_assetco and assetco_result is not None else {}
        )

        if _ENABLE_FINANCIAL_STATEMENT_TRACE:
            _landco_trace_df = (
                fn_trace_payload_to_dataframe(landco_result.get("financial_statement_trace"))
                if _include_landco and landco_result is not None else pd.DataFrame()
            )
            _devco_trace_df = (
                fn_trace_payload_to_dataframe(devco_result.get("financial_statement_trace"))
                if _include_devco and devco_result is not None else pd.DataFrame()
            )
            _assetco_trace_df = (
                fn_trace_payload_to_dataframe(assetco_result.get("financial_statement_trace"))
                if _include_assetco and assetco_result is not None else pd.DataFrame()
            )

            _entity_statement_dfs_for_trace: List[Dict[str, pd.DataFrame]] = []
            for _entity_monthly_dfs in [_landco_monthly_dfs, _devco_monthly_dfs, _assetco_monthly_dfs]:
                _entity_statement_bundle: Dict[str, pd.DataFrame] = {}
                for _statement_name in _FINANCIAL_STATEMENT_SHEETS:
                    _statement_entry = _entity_monthly_dfs.get(_statement_name)
                    if _statement_entry is None:
                        continue
                    _, _statement_payload = _statement_entry
                    _entity_statement_bundle[_statement_name] = _payload_to_dataframe(_statement_payload)
                if _entity_statement_bundle:
                    _entity_statement_dfs_for_trace.append(_entity_statement_bundle)
        else:
            _landco_trace_df = pd.DataFrame()
            _devco_trace_df = pd.DataFrame()
            _assetco_trace_df = pd.DataFrame()
            _entity_statement_dfs_for_trace = []

        fn_record_timing(_timing_ctx, "PHASE 3: Extract Monthly DFs")

        # ------------------------------------------------------------------
        # Sum monthly financial statements across models
        # ------------------------------------------------------------------
        _summed_monthly_dfs = _sum_monthly_financial_statements(_model_results)

        fn_record_timing(_timing_ctx, "PHASE 4: Sum Monthly Financial Statements")

        # ------------------------------------------------------------------
        # Extract interparty netting and IS/CF elimination data from
        # elimination-scoped entity accounts
        # ------------------------------------------------------------------
        _interparty_account_series = _extract_interparty_account_series(_elimination_results)
        _unrealized_gains = _compute_unrealized_gains_adjustments(
            landco_result if _include_landco else None,
            devco_result if _include_devco else None,
            assetco_result if _include_assetco else None,
            payload if isinstance(payload, dict) else None,
        )

        _interparty_netting = {
            "ar": _interparty_account_series["ar"],
            "ur": _interparty_account_series["ur"],
        }
        _is_elimination = {
            "revenue": _interparty_account_series["revenue"],
            "cogs": _interparty_account_series["cogs"],
        }
        _cf_elimination = _interparty_account_series["cash"]

        fn_record_timing(_timing_ctx, "PHASE 5: Extract Interparty Eliminations & Unrealized Gains")

        fn_record_timing(_timing_ctx, "PHASE 6: Unrealized Gains Calculation")

        # ------------------------------------------------------------------
        # Post-process consolidated Balance Sheet and Cashflow Statement
        #   - BS: merge CWIP lines, property investment block, remove IE rows,
        #         interparty netting rows, inject JV closing balance
        #   - CF: remove IE rows, inject JV cashflows
        # ------------------------------------------------------------------

        # JV data and consolidated-mode gate — used by BS, CF, and IS postprocess.
        _is_full_consolidated = (
            _asset_filter_mode.strip().lower() == "consolidated"
            and _module_filter_mode.strip().lower() == "consolidated"
        )
        _jv_consol_data = payload.get("jv_consolidation", {}) if isinstance(payload, dict) else {}

        # Build JV investment accounts here so the closing balance is available
        # for both BS (PHASE 7) and IS (PHASE 9) postprocessing.
        _jv_accounts = (
            _build_jv_investment_accounts(_jv_consol_data)
            if _jv_consol_data and _is_full_consolidated
            else {}
        )

        # Sum per-period closing balances across all scenarios for BS injection.
        _jv_closing_balance_series: Optional[pd.Series] = None
        if _jv_accounts:
            _jv_cb_arrays = [
                acct["closing_balance"]
                for acct in _jv_accounts.values()
                if "closing_balance" in acct and acct["closing_balance"]
            ]
            if _jv_cb_arrays:
                _max_len = max(len(a) for a in _jv_cb_arrays)
                _cb_sum = [
                    sum(a[i] if i < len(a) else 0.0 for a in _jv_cb_arrays)
                    for i in range(_max_len)
                ]
                _jv_closing_balance_series = pd.Series(_cb_sum, dtype=float)

        # Cumulative JV profit accrual — added to Retained Earnings on BS.
        # Cumulative JV profit accrual for BS Retained Earnings.
        # Includes both waterfall-based profit_accrual AND land_transfer_profit
        # (Component 2 of Share of Profit from JV) since both are IS income that
        # must be reflected in Retained Earnings on the BS.
        _jv_profit_accrual_series: Optional[pd.Series] = None
        if _jv_accounts:
            _jv_pa_arrays = [
                [
                    (acct["profit_accrual"][i] if i < len(acct.get("profit_accrual", [])) else 0.0)
                    + (acct["land_transfer_profit"][i] if i < len(acct.get("land_transfer_profit", [])) else 0.0)
                    for i in range(max(len(acct.get("profit_accrual", [])), len(acct.get("land_transfer_profit", []))))
                ]
                for acct in _jv_accounts.values()
                if acct.get("profit_accrual") or acct.get("land_transfer_profit")
            ]
            if _jv_pa_arrays:
                _pa_max_len = max(len(a) for a in _jv_pa_arrays)
                _pa_sum = [
                    sum(a[i] if i < len(a) else 0.0 for a in _jv_pa_arrays)
                    for i in range(_pa_max_len)
                ]
                _jv_profit_accrual_series = pd.Series(
                    np.cumsum(_pa_sum).tolist(), dtype=float
                )

        # Cumulative JV distributions received — added to BS Cash.
        # Uses total distributions (includes Compensation in Lieu).
        _jv_distributions_series: Optional[pd.Series] = None
        if _jv_accounts:
            _jv_dist_arrays = [
                acct["distributions"]
                for acct in _jv_accounts.values()
                if acct.get("distributions")
            ]
            if _jv_dist_arrays:
                _dist_max_len = max(len(a) for a in _jv_dist_arrays)
                _dist_sum = [
                    sum(a[i] if i < len(a) else 0.0 for a in _jv_dist_arrays)
                    for i in range(_dist_max_len)
                ]
                _jv_distributions_series = pd.Series(
                    np.cumsum(_dist_sum).tolist(), dtype=float
                )

        # Cumulative JV cash-only equity investments — deducted from BS Cash.
        # Uses cash_investments (excludes in-kind) so only actual cash outflows reduce Cash.
        _jv_investments_series: Optional[pd.Series] = None
        if _jv_accounts:
            _jv_inv_arrays = [
                [-v for v in acct["cash_investments"]]  # negate: stored as negative outflow
                for acct in _jv_accounts.values()
                if acct.get("cash_investments")
            ]
            if _jv_inv_arrays:
                _inv_max_len = max(len(a) for a in _jv_inv_arrays)
                _inv_sum = [
                    sum(a[i] if i < len(a) else 0.0 for a in _jv_inv_arrays)
                    for i in range(_inv_max_len)
                ]
                _jv_investments_series = pd.Series(
                    np.cumsum(_inv_sum).tolist(), dtype=float
                )

        # Collect per-asset LandCo CFF "Land In Kind" across all JV scenarios
        _jv_lik_per_asset: Dict[str, List[float]] = {}
        if _jv_consol_data and _is_full_consolidated:
            for _vdata in _jv_consol_data.values():
                if not isinstance(_vdata, dict):
                    continue
                for _aname, _vals in (_vdata.get("land_in_kind_per_asset") or {}).items():
                    if _aname not in _jv_lik_per_asset:
                        _jv_lik_per_asset[_aname] = list(_vals)
                    else:
                        _ex = _jv_lik_per_asset[_aname]
                        _jv_lik_per_asset[_aname] = [
                            (_ex[i] if i < len(_ex) else 0.0) + (_vals[i] if i < len(_vals) else 0.0)
                            for i in range(max(len(_ex), len(_vals)))
                        ]

        # Build cumulative sum of all per-asset LIK for Share Capital
        _jv_lik_cumsum: Optional[pd.Series] = None
        if _jv_lik_per_asset:
            _all_lik = list(_jv_lik_per_asset.values())
            _lik_max = max(len(v) for v in _all_lik)
            _lik_total = [sum(v[i] if i < len(v) else 0.0 for v in _all_lik) for i in range(_lik_max)]
            _jv_lik_cumsum = pd.Series(np.cumsum(_lik_total).tolist(), dtype=float)

        if "Balance Sheet" in _summed_monthly_dfs:
            _bs_code, _bs_payload = _summed_monthly_dfs["Balance Sheet"]
            _bs_df = _postprocess_consolidated_bs(
                _payload_to_dataframe(_bs_payload),
                unrealized_gains=_unrealized_gains,
                interparty_netting=_interparty_netting,
                jv_closing_balance=_jv_closing_balance_series,
                jv_profit_accrual=_jv_profit_accrual_series,
                jv_distributions=_jv_distributions_series,
                jv_investments=_jv_investments_series,
                jv_lik_cumsum=_jv_lik_cumsum,
            )
            _summed_monthly_dfs["Balance Sheet"] = ("o.consolidated.bs.me", _dataframe_to_payload(_bs_df))

        if "Cashflow Statement" in _summed_monthly_dfs:
            _cf_code, _cf_payload = _summed_monthly_dfs["Cashflow Statement"]
            _jv_cf_rows = (
                _extract_jv_cashflows_for_roshn(_jv_consol_data)
                if _jv_consol_data and _is_full_consolidated
                else {}
            )
            _cf_df = _postprocess_consolidated_cf(
                _payload_to_dataframe(_cf_payload),
                cf_elimination=_cf_elimination,
                jv_investment=_jv_cf_rows.get("investment_in_jv"),
                jv_dividends=_jv_cf_rows.get("dividends_from_jv"),
                jv_lik_per_asset=_jv_lik_per_asset if _jv_lik_per_asset else None,
            )
            _summed_monthly_dfs["Cashflow Statement"] = ("o.consolidated.cfs.me", _dataframe_to_payload(_cf_df))

        fn_record_timing(_timing_ctx, "PHASE 7: Post-process BS & CF")

        # Interparty asset trace container — initialised here so it is available
        # for both Phase 7.1 (equity trace rows) and Phase 7.5 (interparty rows).
        _interparty_asset_trace: Dict[str, Any] = {
            FS_TRACE_ROWS_KEY: [],
            "__enable_financial_statement_trace__": True,
        }

        # Add per-asset Land In Kind trace rows (CFS + BS Share Capital)
        for _lik_aname, _lik_vals in _jv_lik_per_asset.items():
            for _pi, _v in enumerate(_lik_vals):
                if abs(_v) > 1e-6:
                    fn_append_financial_statement_trace_row(
                        financial_statements=_interparty_asset_trace,
                        period=_pi,
                        value=_v,
                        financial_statement="Cashflow Statement",
                        line_item_name=f"Land In Kind - {_lik_aname}",
                        asset_no=_lik_aname,
                    )
                    fn_append_financial_statement_trace_row(
                        financial_statements=_interparty_asset_trace,
                        period=_pi,
                        value=_v,
                        financial_statement="Balance Sheet",
                        line_item_name="Share Capital",
                        asset_no=_lik_aname,
                    )

        # Add consolidated-level trace rows for all JV account line items.
        # asset_no = "Consolidated" (project level, not per-asset).
        if _jv_accounts:
            for _jv_tname, _jv_tacct in _jv_accounts.items():
                # IS: Share of Profit from JV — profit_accrual (Component 1: waterfall accruals)
                _pa_vals = _jv_tacct.get("profit_accrual", [])
                _ltp_vals = _jv_tacct.get("land_transfer_profit", [])
                # Subtract land_transfer_profit to get Component 1 only (it was added to profit_accrual)
                _comp1 = [
                    float(_pa_vals[i] if i < len(_pa_vals) else 0.0)
                    - float(_ltp_vals[i] if i < len(_ltp_vals) else 0.0)
                    for i in range(len(_pa_vals))
                ]
                for _pi, _v in enumerate(_comp1):
                    if abs(_v) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=_v,
                            financial_statement="Income Statement",
                            line_item_name="Share of Profit from JV",
                            asset_no="Consolidated",
                        )
                # IS: Share of Profit from JV — land_transfer_profit (Component 2)
                for _pi, _v in enumerate(_ltp_vals):
                    if abs(float(_v)) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=float(_v),
                            financial_statement="Income Statement",
                            line_item_name="Share of Profit from JV",
                            asset_no="Consolidated",
                        )
                # BS: Investments in Associates — period-over-period delta of closing_balance
                _cb_vals = _jv_tacct.get("closing_balance", [])
                for _pi, _cb in enumerate(_cb_vals):
                    _prev = float(_cb_vals[_pi - 1]) if _pi > 0 else 0.0
                    _delta = float(_cb) - _prev
                    if abs(_delta) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=_delta,
                            financial_statement="Balance Sheet",
                            line_item_name="Investments in Associates",
                            asset_no="Consolidated",
                        )
                # CFS: Investment in JV — cash_investments per period (negative = outflow)
                _ci_vals = _jv_tacct.get("cash_investments", [])
                for _pi, _v in enumerate(_ci_vals):
                    if abs(float(_v)) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=float(_v),
                            financial_statement="Cashflow Statement",
                            line_item_name="Investment in JV",
                            asset_no="Consolidated",
                        )
                # CFS: Dividends Received from JV — cash_distributions per period
                _cd_vals = _jv_tacct.get("cash_distributions", [])
                for _pi, _v in enumerate(_cd_vals):
                    if abs(float(_v)) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=float(_v),
                            financial_statement="Cashflow Statement",
                            line_item_name="Dividends Received from JV",
                            asset_no="Consolidated",
                        )
                # CFS: Compensation in Lieu (non-cash portion = distributions - cash_distributions)
                _d_vals = _jv_tacct.get("distributions", [])
                _comp_noncash_len = max(len(_d_vals), len(_cd_vals))
                for _pi in range(_comp_noncash_len):
                    _d = float(_d_vals[_pi]) if _pi < len(_d_vals) else 0.0
                    _cd = float(_cd_vals[_pi]) if _pi < len(_cd_vals) else 0.0
                    _comp_v = _d - _cd
                    if abs(_comp_v) > 1e-6:
                        fn_append_financial_statement_trace_row(
                            financial_statements=_interparty_asset_trace,
                            period=_pi,
                            value=_comp_v,
                            financial_statement="Cashflow Statement",
                            line_item_name="Land in Kind Contribution",
                            asset_no="Consolidated",
                        )

        # ------------------------------------------------------------------
        # PHASE 7.1: Replace entity-computed equity with consolidated running-
        # balance equity.  Runs unconditionally (not gated by filtration mode).
        # Entity models post equity period-by-period; this step replaces that
        # with a balancing figure that carries surplus cash forward so it offsets
        # future shortfalls before new equity is raised.
        # ------------------------------------------------------------------
        if "Balance Sheet" in _summed_monthly_dfs and "Cashflow Statement" in _summed_monthly_dfs:
            _bs_eq_df = _payload_to_dataframe(_summed_monthly_dfs["Balance Sheet"][1])
            _cf_eq_df = _payload_to_dataframe(_summed_monthly_dfs["Cashflow Statement"][1])
            _bs_eq_df, _cf_eq_df = _postprocess_consolidated_equity_as_balancing(
                bs_df=_bs_eq_df,
                cf_df=_cf_eq_df,
                financial_statement_trace=_interparty_asset_trace if _ENABLE_FINANCIAL_STATEMENT_TRACE else None,
            )
            _summed_monthly_dfs["Balance Sheet"] = ("o.consolidated.bs.me", _dataframe_to_payload(_bs_eq_df))
            _summed_monthly_dfs["Cashflow Statement"] = ("o.consolidated.cfs.me", _dataframe_to_payload(_cf_eq_df))
            # Provide the BS DF so fn_build_financial_statement_trace_dataframe
            # can derive model_all_periods for BS forward-fill to all model periods.
            if _ENABLE_FINANCIAL_STATEMENT_TRACE:
                _interparty_asset_trace["balance_sheet"] = _bs_eq_df

        fn_record_timing(_timing_ctx, "PHASE 7.1: Recalculate equity as balancing figure")

        # ------------------------------------------------------------------
        # Build consolidated monthly_dfs:
        #   - Summed FS sheets replace originals
        #   - Non-FS sheets (Timeline, Hospitality P&L, etc.) are carried
        #     forward from whichever model provides them
        # ------------------------------------------------------------------
        _consolidated_monthly_dfs: Dict[str, Tuple[str, Dict[str, Any]]] = {}

        # Carry forward non-FS sheets from all models (first occurrence wins)
        # Override codes with consolidated named ranges.
        _MONTHLY_CODE_OVERRIDES: Dict[str, str] = {
            "Timeline": "o.consolidated.model.timeline.me",
            "Hospitality P&L": "o.consolidated.hospitality.pl.me",
        }
        _MONTHLY_SHEET_RENAME: Dict[str, str] = {
            "Timeline": "Monthly Timeline",
        }
        for mdfs in [_landco_monthly_dfs, _devco_monthly_dfs, _assetco_monthly_dfs]:
            for sheet_name, entry in mdfs.items():
                dest_name = _MONTHLY_SHEET_RENAME.get(sheet_name, sheet_name)
                if sheet_name not in _FINANCIAL_STATEMENT_SHEETS and dest_name not in _consolidated_monthly_dfs:
                    if sheet_name in _MONTHLY_CODE_OVERRIDES:
                        _, payload = entry
                        _consolidated_monthly_dfs[dest_name] = (_MONTHLY_CODE_OVERRIDES[sheet_name], payload)
                    else:
                        _consolidated_monthly_dfs[dest_name] = entry

        # Overlay the summed FS sheets
        _consolidated_monthly_dfs.update(_summed_monthly_dfs)

        fn_record_timing(_timing_ctx, "PHASE 8: Build Consolidated Monthly DFs")

        # ------------------------------------------------------------------
        # Build consolidated Income Statement using the proforma alignment
        # ------------------------------------------------------------------
        _entity_is_monthly: List[pd.DataFrame] = []
        for mdfs in [_landco_monthly_dfs, _devco_monthly_dfs, _assetco_monthly_dfs]:
            is_entry = mdfs.get("Income Statement")
            if is_entry is not None:
                _, is_payload = is_entry
                _entity_is_monthly.append(_payload_to_dataframe(is_payload))

        if _entity_is_monthly:
            _consolidated_is_monthly = _build_consolidated_income_statement(
                _entity_is_monthly
            )

            # ------------------------------------------------------------------
            # Compute per-asset interparty COS (each asset phased by its own
            # DevCo COS curve) and collect the summed series for the consolidated
            # IS.  Trace rows are also emitted here when trace is enabled.
            # Always runs regardless of trace flag so the consolidated IS uses
            # per-asset phasing.
            # ------------------------------------------------------------------
            _is_cols = list(_consolidated_is_monthly.columns)
            _summed_ip_cos_total = _emit_interparty_asset_trace_rows(
                model_results=_model_results,
                financial_statement_trace=_interparty_asset_trace,
                is_elimination=_is_elimination,
                cf_elimination=_cf_elimination,
                re_ie_series=_interparty_account_series.get("re_ie", pd.Series(dtype=float)),
                cols=_is_cols,
            )

            fn_record_timing(_timing_ctx, "PHASE 7.5: Per-asset interparty trace rows")

            _consolidated_is_monthly = _postprocess_consolidated_is(
                _consolidated_is_monthly,
                is_elimination=_is_elimination,
                jv_accounts=_jv_accounts if _jv_accounts else None,
                ip_cos_total_override=_summed_ip_cos_total,
            )
            _consolidated_monthly_dfs["Income Statement"] = (
                "o.consolidated.is.me",
                _dataframe_to_payload(_consolidated_is_monthly),
            )

        fn_record_timing(_timing_ctx, "PHASE 9: Build Consolidated Income Statement")

        # ------------------------------------------------------------------
        # Build consolidated annual_dfs — pass through from individual models
        # (no summation per requirement). First occurrence wins.
        # ------------------------------------------------------------------
        _ANNUAL_CODE_OVERRIDES: Dict[str, str] = {
            "Timeline": "o.consolidated.model.timeline.ye",
            "Hospitality P&L": "o.consolidated.hospitality.pl.ye",
        }
        _ANNUAL_SHEET_RENAME: Dict[str, str] = {
            "Timeline": "Yearly Timeline",
        }
        _consolidated_annual_dfs: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for result in _model_results:
            for sheet_name, entry in result.get("annual_dfs", {}).items():
                dest_name = _ANNUAL_SHEET_RENAME.get(sheet_name, sheet_name)
                if dest_name not in _consolidated_annual_dfs:
                    if sheet_name in _ANNUAL_CODE_OVERRIDES:
                        _, payload = entry
                        _consolidated_annual_dfs[dest_name] = (_ANNUAL_CODE_OVERRIDES[sheet_name], payload)
                    else:
                        _consolidated_annual_dfs[dest_name] = entry

        # Override annual IS with annualized version of consolidated monthly IS
        # (monthly IS is already post-processed with elimination rows, so
        #  annualization preserves them — no further post-processing needed)
        if _entity_is_monthly:
            _consolidated_is_annual = _annualize_monthly_df(_consolidated_is_monthly)
            _consolidated_annual_dfs["Income Statement"] = (
                "o.consolidated.is.ye",
                _dataframe_to_payload(_consolidated_is_annual),
            )

        # Override annual Cashflow Statement — sum consolidated monthly CF by year
        if "Cashflow Statement" in _consolidated_monthly_dfs:
            _cf_monthly_code, _cf_monthly_payload = _consolidated_monthly_dfs["Cashflow Statement"]
            _cf_monthly_df = _payload_to_dataframe(_cf_monthly_payload)
            _consolidated_cf_annual = _annualize_monthly_df(_cf_monthly_df)
            _consolidated_annual_dfs["Cashflow Statement"] = (
                "o.consolidated.cfs.ye",
                _dataframe_to_payload(_consolidated_cf_annual),
            )

        # Override annual Balance Sheet — pick period-end (last month) per year
        if "Balance Sheet" in _consolidated_monthly_dfs:
            _bs_monthly_code, _bs_monthly_payload = _consolidated_monthly_dfs["Balance Sheet"]
            _bs_monthly_df = _payload_to_dataframe(_bs_monthly_payload)
            _consolidated_bs_annual = _annualize_monthly_bs(_bs_monthly_df)
            _consolidated_annual_dfs["Balance Sheet"] = (
                "o.consolidated.bs.ye",
                _dataframe_to_payload(_consolidated_bs_annual),
            )

        fn_record_timing(_timing_ctx, "PHASE 10: Build Consolidated Annual DFs")

        # ------------------------------------------------------------------
        # Transpose timeline DataFrames before final output
        # ------------------------------------------------------------------
        for _tl_key in ("Monthly Timeline", "Yearly Timeline"):
            for _dfs_dict in (_consolidated_monthly_dfs, _consolidated_annual_dfs):
                if _tl_key in _dfs_dict:
                    _tl_code, _tl_payload = _dfs_dict[_tl_key]
                    _tl_df = _payload_to_dataframe(_tl_payload).T
                    _dfs_dict[_tl_key] = (_tl_code, _dataframe_to_payload(_tl_df))

        fn_record_timing(_timing_ctx, "PHASE 11: Transpose Timelines")

        # ------------------------------------------------------------------
        # Remove empty / None Hospitality P&L entries before final output
        # ------------------------------------------------------------------
        for _dfs_dict in (_consolidated_monthly_dfs, _consolidated_annual_dfs):
            if "Hospitality P&L" in _dfs_dict:
                _hp_entry = _dfs_dict["Hospitality P&L"]
                if _hp_entry is None:
                    del _dfs_dict["Hospitality P&L"]
                else:
                    _, _hp_payload = _hp_entry
                    if not _hp_payload:
                        del _dfs_dict["Hospitality P&L"]
                    else:
                        _hp_df = _payload_to_dataframe(_hp_payload)
                        if _hp_df.empty:
                            del _dfs_dict["Hospitality P&L"]

        fn_record_timing(_timing_ctx, "PHASE 12: Clean Hospitality P&L")

        # ------------------------------------------------------------------
        # Build Financial Statement Trace output
        # ------------------------------------------------------------------
        if _ENABLE_FINANCIAL_STATEMENT_TRACE:
            _consolidated_statement_dfs_for_trace: Dict[str, pd.DataFrame] = {}
            for _statement_name in _FINANCIAL_STATEMENT_SHEETS:
                _statement_entry = _consolidated_monthly_dfs.get(_statement_name)
                if _statement_entry is None:
                    continue
                _, _statement_payload = _statement_entry
                _consolidated_statement_dfs_for_trace[_statement_name] = _payload_to_dataframe(_statement_payload)

            _consolidated_trace_delta_df = fn_build_consolidated_financial_statement_trace_delta(
                consolidated_statement_dfs=_consolidated_statement_dfs_for_trace,
                entity_statement_dfs_list=_entity_statement_dfs_for_trace,
                asset_no="Consolidated",
            )

            # Strip interparty line items from all consolidated/entity trace DFs —
            # these are now attributed at asset level via _interparty_asset_trace_df
            # and must not also appear as consolidated-level rows.
            _INTERPARTY_TRACE_LINE_ITEMS = {
                "Less: Interparty Sales Revenue",
                "Add: Interparty Cost of Sales",
                "Less: Interparty Cash Collection",
                "Add: Interparty Cash Payment",
                "Less: Interparty Retained Earnings",
                "Retained Earnings - Interparty Elimination",
            }

            def _strip_interparty_rows(df: pd.DataFrame) -> pd.DataFrame:
                if df.empty or "Line Item Name" not in df.columns:
                    return df
                mask = (
                    df["Line Item Name"].isin(_INTERPARTY_TRACE_LINE_ITEMS)
                    | df["Line Item Name"].str.endswith(" - Interparty Elimination", na=False)
                )
                return df.loc[~mask].copy()

            _landco_trace_df = _strip_interparty_rows(_landco_trace_df)
            _devco_trace_df = _strip_interparty_rows(_devco_trace_df)
            _assetco_trace_df = _strip_interparty_rows(_assetco_trace_df)
            _consolidated_trace_delta_df = _strip_interparty_rows(_consolidated_trace_delta_df)

            # Strip equity-related items from entity traces and the consolidated
            # delta so that Phase 7.1 (_interparty_asset_trace) is the sole
            # authoritative source for "Share Capital" and "Project and Asset
            # Equity Contribution" in the final trace DF.
            _EQUITY_TRACE_ITEMS = {
                "Share Capital",
                "Project and Asset Equity Contribution",
            }

            def _strip_equity_rows(df: pd.DataFrame) -> pd.DataFrame:
                if df.empty or "Line Item Name" not in df.columns:
                    return df
                return df.loc[~df["Line Item Name"].isin(_EQUITY_TRACE_ITEMS)].copy()

            _landco_trace_df = _strip_equity_rows(_landco_trace_df)
            _devco_trace_df = _strip_equity_rows(_devco_trace_df)
            _assetco_trace_df = _strip_equity_rows(_assetco_trace_df)
            _consolidated_trace_delta_df = _strip_equity_rows(_consolidated_trace_delta_df)

            _interparty_asset_trace_df = fn_build_financial_statement_trace_dataframe(_interparty_asset_trace)

            # Populate Unique ID for interparty asset-level rows.
            # _asset_index_to_uid has string keys (e.g. "5"); convert to int keys
            # so fn_add_unique_id_to_trace_df's numeric map lookup works correctly.
            _uid_int_lookup: Dict[int, str] = {}
            for _k, _v in _asset_index_to_uid.items():
                try:
                    _uid_int_lookup[int(float(_k))] = _v
                except (ValueError, TypeError):
                    pass
            _interparty_asset_trace_df = fn_add_unique_id_to_trace_df(
                _interparty_asset_trace_df,
                _uid_int_lookup,
            )

            _financial_statement_trace_df = fn_concatenate_financial_statement_trace_dataframes([
                _landco_trace_df,
                _devco_trace_df,
                _assetco_trace_df,
                _interparty_asset_trace_df,
                _consolidated_trace_delta_df,
            ])
            _financial_statement_trace_df = fn_add_trace_hierarchy_levels(_financial_statement_trace_df)
            
            # _financial_statement_trace_df = _replace_trace_asset_no_with_uid(
            #     _financial_statement_trace_df,
            #     _asset_index_to_uid,
            # )

            fn_record_timing(_timing_ctx, "PHASE 12.5: Build Financial Statement Trace")
        else:
            fn_record_timing(_timing_ctx, "PHASE 12.5: Build Financial Statement Trace (skipped)")

        # _financial_statement_trace_df.to_excel("financial_statement_trace4.xlsx", index=False)
        # os.startfile("financial_statement_trace4.xlsx")
        # raise breakpoint
        # ------------------------------------------------------------------
        # Build final output (same structure as LandCo excel_output)
        # ------------------------------------------------------------------
        excel_output = {
            "monthly_dfs": _consolidated_monthly_dfs,
            "annual_dfs": _consolidated_annual_dfs,
        }

        fn_record_timing(_timing_ctx, "PHASE 13: Build Final Output")

        # ====================================================================
        # EXPORTS (gated by _EXPORT_FLAGS)
        # Wrapped in its own try/except so export errors don't lose the
        # already-computed model result.
        # ====================================================================
        try:

            # E.1 Consolidated output (summed monthly + annual pass-through)
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "consolidated_output"):
                fn_export_consolidated_output(excel_output, "consolidated_output.xlsx")

            # E.2 LandCo individual output
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "landco_output") and _landco_monthly_dfs:
                _landco_export: Dict[str, Any] = {}
                for sheet_name, (code, payload) in _landco_monthly_dfs.items():
                    _landco_export[f"M_{sheet_name}"[:31]] = payload
                fn_export_dataframes_to_excel(_landco_export, "landco_individual_output", "LandCo Individual Output")

            # E.3 DevCo individual output
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "devco_output") and _devco_monthly_dfs:
                _devco_export: Dict[str, Any] = {}
                for sheet_name, (code, payload) in _devco_monthly_dfs.items():
                    _devco_export[f"M_{sheet_name}"[:31]] = payload
                fn_export_dataframes_to_excel(_devco_export, "devco_individual_output", "DevCo Individual Output")

            # E.4 AssetCo individual output
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "assetco_output") and _assetco_monthly_dfs:
                _assetco_export: Dict[str, Any] = {}
                for sheet_name, (code, payload) in _assetco_monthly_dfs.items():
                    _assetco_export[f"M_{sheet_name}"[:31]] = payload
                fn_export_dataframes_to_excel(_assetco_export, "assetco_individual_output", "AssetCo Individual Output")

            # E.5 LandCo accounts
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "landco_accounts") and landco_result is not None:
                _landco_accounts = landco_result.get("accounts", {})
                if _landco_accounts:
                    _la_export = {
                        name[:25].replace("/", "-").replace("\\", "-"): payload
                        for name, payload in _landco_accounts.items()
                    }
                    fn_export_dataframes_to_excel(_la_export, "landco_accounts", "LandCo Accounts")

            # E.6 DevCo accounts
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "devco_accounts") and devco_result is not None:
                _devco_accounts = devco_result.get("accounts", {})
                if _devco_accounts:
                    _da_export = {
                        name[:25].replace("/", "-").replace("\\", "-"): payload
                        for name, payload in _devco_accounts.items()
                    }
                    fn_export_dataframes_to_excel(_da_export, "devco_accounts", "DevCo Accounts")

            # E.7 AssetCo accounts
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "assetco_accounts") and assetco_result is not None:
                _assetco_accounts = assetco_result.get("accounts", {})
                if _assetco_accounts:
                    _aa_export = {
                        name[:25].replace("/", "-").replace("\\", "-"): payload
                        for name, payload in _assetco_accounts.items()
                    }
                    fn_export_dataframes_to_excel(_aa_export, "assetco_accounts", "AssetCo Accounts")

            # E.8 LandCo journal
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "landco_journal") and landco_result is not None:
                _landco_journal = landco_result.get("journal", [])
                if _landco_journal:
                    fn_export_dataframes_to_excel(
                        {"Journal": pd.DataFrame(_landco_journal)},
                        "landco_journal", "LandCo Journal",
                    )

            # E.9 DevCo journal
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "devco_journal") and devco_result is not None:
                _devco_journal = devco_result.get("journal", [])
                if _devco_journal:
                    fn_export_dataframes_to_excel(
                        {"Journal": pd.DataFrame(_devco_journal)},
                        "devco_journal", "DevCo Journal",
                    )

            # E.10 AssetCo journal
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "assetco_journal") and assetco_result is not None:
                _assetco_journal = assetco_result.get("journal", [])
                if _assetco_journal:
                    fn_export_dataframes_to_excel(
                        {"Journal": pd.DataFrame(_assetco_journal)},
                        "assetco_journal", "AssetCo Journal",
                    )

            # E.11 Combined journal (all entities appended)
            # ----------------------------------------------------------------
            if fn_is_export_enabled(_EXPORT_FLAGS, "combined_journal"):
                _combined_journal_parts: List[pd.DataFrame] = []
                for _entity_label, _entity_result in [
                    ("LandCo", landco_result),
                    ("DevCo", devco_result),
                    ("AssetCo", assetco_result),
                ]:
                    if _entity_result is not None:
                        _ej = _entity_result.get("journal", [])
                        if _ej:
                            _ej_df = pd.DataFrame(_ej)
                            _ej_df.insert(0, "Entity", _entity_label)
                            _combined_journal_parts.append(_ej_df)
                if _combined_journal_parts:
                    fn_export_dataframes_to_excel(
                        {"Journal": pd.concat(_combined_journal_parts, ignore_index=True)},
                        "combined_journal", "Combined Journal (All Entities)",
                    )
        except Exception as export_exc:
            print(f"Warning: Export failed (non-fatal): {export_exc}")

        _timing_summary = fn_finalize_timing_summary(
            _timing_ctx, "PHASE 14: Exports & Serialize Output",
            entity_label="CONSOLIDATED MODEL",
        )
        print(_timing_summary["summary_text"])

        return {
            "exceloutput": excel_output
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
