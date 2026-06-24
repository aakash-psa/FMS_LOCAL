from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import traceback


_FS_SHEETS = (
    "Balance Sheet",
    "Income Statement",
    "Cashflow Statement",
)

_FS_CODE_PREFIXES = (
    "o.consolidated.bs.",
    "o.consolidated.is.",
    "o.consolidated.cfs.",
)

_FREQ_KEYS = (
    "monthly_dfs",
    "annual_dfs",
)

_TIMELINE_SHEET_BY_FREQ = {
    "monthly_dfs": "Monthly Timeline",
    "annual_dfs": "Yearly Timeline",
}

_TIMELINE_CODE_BY_FREQ = {
    "monthly_dfs": "o.consolidated.model.timeline.me",
    "annual_dfs": "o.consolidated.model.timeline.ye",
}


def _empty_excel_output() -> Dict[str, Dict[str, Any]]:
    return {
        "monthly_dfs": {},
        "annual_dfs": {},
    }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _to_number(value: Any) -> Optional[float]:
    if _is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(numeric):
        return None
    return numeric


def _normalize_key_value(value: Any) -> Any:
    if _is_missing(value):
        return None

    if isinstance(value, (np.integer, int)):
        return int(value)

    if isinstance(value, (np.floating, float)):
        fval = float(value)
        if np.isnan(fval):
            return None
        if fval.is_integer():
            return int(fval)
        return fval

    if isinstance(value, pd.Period):
        value = value.to_timestamp(how="end").normalize()

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        # Only coerce date-like strings; keep labels like "2019" unchanged.
        if any(sep in stripped for sep in ("-", "/", "T")):
            parsed = pd.to_datetime(stripped, errors="coerce")
            if not pd.isna(parsed):
                return pd.Timestamp(parsed).strftime("%Y-%m-%d")
        return stripped

    return str(value)


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, pd.Period):
        value = value.to_timestamp(how="end").normalize()

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)

    if isinstance(value, float):
        return None if np.isnan(value) else value

    if _is_missing(value):
        return None

    return value


def _parse_sheet_entry(entry: Any) -> Tuple[str, Dict[str, Any]]:
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        code = str(entry[0])
        payload = entry[1]
    else:
        raise ValueError("Invalid sheet entry format")

    if not isinstance(payload, dict):
        raise ValueError("Sheet payload must be a dictionary")

    if not all(key in payload for key in ("index", "columns", "data")):
        raise ValueError("Sheet payload must include index, columns, data")

    return code, payload


def _payload_to_dataframe(payload: Dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        data=payload.get("data", []),
        index=payload.get("index", []),
        columns=payload.get("columns", []),
        dtype=object,
    )


def _dataframe_to_payload(df: pd.DataFrame) -> Dict[str, Any]:
    safe_index = [_safe_json_value(v) for v in df.index.tolist()]
    safe_columns = [_safe_json_value(v) for v in df.columns.tolist()]
    raw = df.to_numpy(dtype=object, copy=False)

    safe_data: List[List[Any]] = []
    for r in range(raw.shape[0]):
        row: List[Any] = []
        for c in range(raw.shape[1]):
            row.append(_safe_json_value(raw[r, c]))
        safe_data.append(row)

    return {
        "index": safe_index,
        "columns": safe_columns,
        "data": safe_data,
    }


def _get_sheet_dict(output_json: Dict[str, Any], freq_key: str) -> Dict[str, Any]:
    sheets = output_json.get(freq_key, {})
    if isinstance(sheets, dict):
        return sheets
    return {}


def _is_financial_statement_sheet(sheet_name: str, entry: Any) -> bool:
    if sheet_name in _FS_SHEETS:
        return True

    try:
        code, _ = _parse_sheet_entry(entry)
    except ValueError:
        return False

    normalized_code = str(code).strip().lower()
    return any(normalized_code.startswith(prefix) for prefix in _FS_CODE_PREFIXES)


def _extract_project_outputs(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    project_rows = payload.get("project_consolidation")
    if not isinstance(project_rows, list) or not project_rows:
        raise ValueError("project_consolidation is required for roshn_consolidation")

    project_outputs: List[Dict[str, Any]] = []
    for row in project_rows:
        if not isinstance(row, dict):
            continue
        output_json = row.get("output_json")
        if isinstance(output_json, dict):
            project_outputs.append(output_json)

    if not project_outputs:
        raise ValueError("No valid output_json found in project_consolidation")

    return project_outputs


def _timeline_key_for_column(timeline_df: pd.DataFrame, column_label: Any) -> Tuple[Any, ...]:
    def _get(index_name: str) -> Any:
        if index_name not in timeline_df.index:
            return None
        return _normalize_key_value(timeline_df.at[index_name, column_label])

    period_number = _get("# of Period")
    if period_number is not None:
        return ("period_number", period_number)

    year_value = _get("Year")
    month_value = _get("Month")
    if year_value is not None and month_value is not None:
        return ("year_month", year_value, month_value)

    period_end = _get("Period End")
    if period_end is not None:
        return ("period_end", period_end)

    period_start = _get("Period Start")
    if period_start is not None:
        return ("period_start", period_start)

    return ("column", _normalize_key_value(column_label))


def _build_position_alignment(
    master_timeline_df: Optional[pd.DataFrame],
    source_timeline_df: Optional[pd.DataFrame],
    master_width: int,
    source_width: int,
) -> Dict[int, int]:
    fallback = {i: i for i in range(min(master_width, source_width))}

    if master_timeline_df is None or source_timeline_df is None:
        return fallback

    master_cols = list(master_timeline_df.columns)
    source_cols = list(source_timeline_df.columns)

    if not master_cols or not source_cols:
        return fallback

    master_key_to_pos: Dict[Tuple[Any, ...], int] = {}
    for master_pos, column_label in enumerate(master_cols[:master_width]):
        key = _timeline_key_for_column(master_timeline_df, column_label)
        if key not in master_key_to_pos:
            master_key_to_pos[key] = master_pos

    position_map: Dict[int, int] = {}
    used_dest_positions = set()

    for source_pos, column_label in enumerate(source_cols[:source_width]):
        key = _timeline_key_for_column(source_timeline_df, column_label)
        dest_pos = master_key_to_pos.get(key)
        if dest_pos is None or dest_pos in used_dest_positions:
            continue
        position_map[source_pos] = dest_pos
        used_dest_positions.add(dest_pos)

    # Fallback to index-based alignment for any unaligned columns.
    for source_pos in range(min(master_width, source_width)):
        if source_pos in position_map or source_pos in used_dest_positions:
            continue
        position_map[source_pos] = source_pos
        used_dest_positions.add(source_pos)

    return position_map


def _align_dataframe_to_master(
    source_df: pd.DataFrame,
    master_df: pd.DataFrame,
    position_map: Dict[int, int],
) -> pd.DataFrame:
    aligned = np.empty(master_df.shape, dtype=object)
    aligned[:] = None

    source_arr = source_df.to_numpy(dtype=object, copy=False)
    row_count = min(source_arr.shape[0], master_df.shape[0])

    for source_pos in range(source_arr.shape[1]):
        dest_pos = position_map.get(source_pos)
        if dest_pos is None:
            continue
        if dest_pos < 0 or dest_pos >= master_df.shape[1]:
            continue
        aligned[:row_count, dest_pos] = source_arr[:row_count, source_pos]

    return pd.DataFrame(
        data=aligned,
        index=master_df.index,
        columns=master_df.columns,
        dtype=object,
    )


def _sum_aligned_dataframes(
    aligned_dfs: List[pd.DataFrame],
    master_df: pd.DataFrame,
) -> pd.DataFrame:
    if not aligned_dfs:
        return master_df.copy()

    arrays = [df.to_numpy(dtype=object, copy=False) for df in aligned_dfs]
    rows, cols = master_df.shape

    result = np.empty((rows, cols), dtype=object)
    result[:] = None

    for r in range(rows):
        for c in range(cols):
            total = 0.0
            has_numeric = False

            for arr in arrays:
                number = _to_number(arr[r, c])
                if number is None:
                    continue
                total += number
                has_numeric = True

            result[r, c] = total if has_numeric else None

    return pd.DataFrame(
        data=result,
        index=master_df.index,
        columns=master_df.columns,
        dtype=object,
    )


def _extract_timeline_dataframe(
    output_json: Dict[str, Any],
    freq_key: str,
) -> Optional[pd.DataFrame]:
    sheets = _get_sheet_dict(output_json, freq_key)
    timeline_code = _TIMELINE_CODE_BY_FREQ[freq_key]

    # Prefer code-based lookup so timeline discovery is payload-driven.
    for entry in sheets.values():
        try:
            code, payload = _parse_sheet_entry(entry)
        except ValueError:
            continue

        if str(code).strip().lower() == timeline_code:
            return _payload_to_dataframe(payload)

    # Fallback to legacy sheet-name lookup if code is unavailable.
    timeline_sheet_name = _TIMELINE_SHEET_BY_FREQ[freq_key]
    entry = sheets.get(timeline_sheet_name)
    if entry is None:
        return None

    try:
        _, payload = _parse_sheet_entry(entry)
    except ValueError:
        return None

    return _payload_to_dataframe(payload)


def _copy_sheet_entry(entry: Any) -> Any:
    return deepcopy(entry)


def _postprocess_equity_as_balancing(
    bs_df: pd.DataFrame,
    cf_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Replace entity-computed equity with a running-balance balancing figure.

    Surplus cash from one period carries forward to offset shortfalls in later
    periods before new equity is raised.

    Algorithm:
      pre_equity_net[t] = Net Change in Cash[t] - entity_equity[t]
      running_bal = 0
      for each t:
          running_bal += pre_equity_net[t]
          if running_bal < 0:
              new_equity[t] = -running_bal; running_bal = 0

    Modified rows:
      CFS  — "Project and Asset Equity Contribution", "Net Cash from Financing",
              "Net Change in Cash"
      BS   — "Share Capital", "Cash and Cash Equivalents"
      BS totals recomputed after the adjustment.
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

    pre_equity_net = net_change - entity_equity

    n = len(pre_equity_net)
    new_equity  = np.zeros(n, dtype=np.float64)
    running_bal = 0.0
    for _t in range(n):
        running_bal += pre_equity_net[_t]
        if running_bal < 0.0:
            new_equity[_t] = -running_bal
            running_bal = 0.0

    equity_delta = new_equity - entity_equity
    cum_delta    = np.cumsum(equity_delta)

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

    # --- Update BS ---
    n_bs = len(bs_result.columns)
    aligned_delta = np.zeros(n_bs, dtype=np.float64)
    copy_len = min(n, n_bs)
    aligned_delta[:copy_len] = cum_delta[:copy_len]

    sc_pos   = np.where(bs_idx == "Share Capital")[0]
    cash_pos = np.where(bs_idx == "Cash and Cash Equivalents")[0]

    if len(sc_pos) > 0:
        old_sc = (
            pd.to_numeric(bs_result.iloc[int(sc_pos[0])], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        bs_result.iloc[int(sc_pos[0])] = (old_sc + aligned_delta).tolist()

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
    _TOTAL_EQUITY_ITEMS = [
        "Share Capital", "Net Retained Earnings", "Retained Earnings - Interparty Elimination",
    ]

    def _recompute_total(items: List[str]) -> pd.Series:
        total = pd.Series(0.0, index=bs_result.columns)
        _idx_s = bs_result.index.astype(str)
        for _item in items:
            _pos = np.where(_idx_s == _item)[0]
            if len(_pos) > 0:
                total = total + pd.to_numeric(
                    bs_result.iloc[int(_pos[0])], errors="coerce"
                ).fillna(0.0)
        return total

    _bs_idx_s = bs_result.index.astype(str)
    _new_ta = _recompute_total(_TOTAL_ASSETS_ITEMS)
    _new_tl = _recompute_total(_TOTAL_LIABILITIES_ITEMS)
    _new_te = _recompute_total(_TOTAL_EQUITY_ITEMS)
    for _lbl, _vals in [
        ("Total Assets",               _new_ta),
        ("Total Liabilities",          _new_tl),
        ("Total Equity",               _new_te),
        ("Total Liabilities + Equity", _new_tl + _new_te),
    ]:
        _p = np.where(_bs_idx_s == _lbl)[0]
        if len(_p) > 0:
            bs_result.iloc[int(_p[0])] = _vals.tolist()

    return bs_result, cf_result


def _build_consolidated_excel_output(project_outputs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    master_output = project_outputs[0]
    consolidated = _empty_excel_output()

    master_timelines: Dict[str, Optional[pd.DataFrame]] = {
        freq: _extract_timeline_dataframe(master_output, freq)
        for freq in _FREQ_KEYS
    }

    project_timelines: List[Dict[str, Optional[pd.DataFrame]]] = []
    for output_json in project_outputs:
        project_timelines.append(
            {
                freq: _extract_timeline_dataframe(output_json, freq)
                for freq in _FREQ_KEYS
            }
        )

    for freq_key in _FREQ_KEYS:
        master_sheets = _get_sheet_dict(master_output, freq_key)
        result_sheets: Dict[str, Any] = {}

        for sheet_name, master_entry in master_sheets.items():
            if not _is_financial_statement_sheet(sheet_name, master_entry):
                result_sheets[sheet_name] = _copy_sheet_entry(master_entry)
                continue

            try:
                master_code, master_payload = _parse_sheet_entry(master_entry)
            except ValueError:
                result_sheets[sheet_name] = _copy_sheet_entry(master_entry)
                continue

            master_df = _payload_to_dataframe(master_payload)
            aligned_dfs: List[pd.DataFrame] = []

            for project_idx, output_json in enumerate(project_outputs):
                project_sheets = _get_sheet_dict(output_json, freq_key)
                source_entry = project_sheets.get(sheet_name)
                if source_entry is None:
                    continue

                try:
                    _, source_payload = _parse_sheet_entry(source_entry)
                except ValueError:
                    continue

                source_df = _payload_to_dataframe(source_payload)
                position_map = _build_position_alignment(
                    master_timeline_df=master_timelines[freq_key],
                    source_timeline_df=project_timelines[project_idx][freq_key],
                    master_width=len(master_df.columns),
                    source_width=len(source_df.columns),
                )

                aligned = _align_dataframe_to_master(
                    source_df=source_df,
                    master_df=master_df,
                    position_map=position_map,
                )
                aligned_dfs.append(aligned)

            summed_df = _sum_aligned_dataframes(aligned_dfs, master_df)
            result_sheets[sheet_name] = [master_code, _dataframe_to_payload(summed_df)]

        # Apply equity-as-balancing post-processing to summed statements.
        _bs_entry  = result_sheets.get("Balance Sheet")
        _cfs_entry = result_sheets.get("Cashflow Statement")
        if _bs_entry is not None and _cfs_entry is not None:
            try:
                _bs_code,  _bs_payload  = _parse_sheet_entry(_bs_entry)
                _cfs_code, _cfs_payload = _parse_sheet_entry(_cfs_entry)
                _bs_df  = _payload_to_dataframe(_bs_payload)
                _cfs_df = _payload_to_dataframe(_cfs_payload)
                _bs_df, _cfs_df = _postprocess_equity_as_balancing(_bs_df, _cfs_df)
                result_sheets["Balance Sheet"]     = [_bs_code,  _dataframe_to_payload(_bs_df)]
                result_sheets["Cashflow Statement"] = [_cfs_code, _dataframe_to_payload(_cfs_df)]
            except Exception:
                pass

        consolidated[freq_key] = result_sheets

    return consolidated


def wrapper_for_vars(payload: Any, is_save: bool) -> Dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("ROSHN payload must be a dictionary")

        project_outputs = _extract_project_outputs(payload)
        excel_output = _build_consolidated_excel_output(project_outputs)

        return {
            "exceloutput": excel_output,
        }

    except Exception as e:
        print(f"Failed to initialise values {e}\n{traceback.format_exc()}")
        return {
            "error": str(e),
            "exceloutput": _empty_excel_output(),
        }


def fninitialising_all_values(payload: Any, is_save: bool) -> Dict[str, Any]:
    try:
        # import json
        # with open("roshn_consolidation_payload.json", "w", encoding="utf-8") as f:
        #     json.dump(payload, f, indent=2, ensure_ascii=False)
        # raise breakpoint("Debug: payload dumped to payload_debug.json")
        output = wrapper_for_vars(payload, is_save)
        if output is None:
            return {
                "error": "Model returned None",
                "exceloutput": _empty_excel_output(),
            }
        return output
    except Exception as e:
        print(f"Error in initialising all values: {e}")
        return {
            "error": str(e),
            "exceloutput": _empty_excel_output(),
        }
