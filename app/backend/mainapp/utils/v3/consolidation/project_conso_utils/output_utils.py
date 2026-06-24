"""
Payload serialisation, annual aggregation, Excel export, and debug helpers.
"""

import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def fn_dataframe_to_output_payload(dataframe: pd.DataFrame) -> Dict[str, Any]:
    """
    Convert a DataFrame to a JSON-serializable output payload.
    """
    def _json_safe_cell(value: Any) -> Any:
        if isinstance(value, pd.Period):
            value = value.to_timestamp(how="end").normalize()

        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")

        if isinstance(value, str):
            stripped = value.strip()
            if stripped and any(separator in stripped for separator in ("-", "/", "T")):
                parsed = pd.to_datetime(stripped, errors="coerce")
                if not pd.isna(parsed):
                    return pd.Timestamp(parsed).strftime("%Y-%m-%d")

        try:
            return None if pd.isna(value) else value
        except TypeError:
            return value

    safe_index = [_json_safe_cell(value) for value in dataframe.index.tolist()]
    safe_columns = [_json_safe_cell(value) for value in dataframe.columns.tolist()]

    # Fast path for data cells: most are float/int/None — skip expensive
    # date parsing and isinstance checks for those.
    raw_data = dataframe.to_numpy(dtype=object, copy=False)
    n_rows, n_cols = raw_data.shape
    safe_data = []
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            v = raw_data[r, c]
            if v is None:
                row.append(None)
            elif isinstance(v, (int, float)):
                if isinstance(v, float) and v != v:  # NaN check
                    row.append(None)
                else:
                    row.append(v)
            elif isinstance(v, np.integer):
                row.append(int(v))
            elif isinstance(v, np.floating):
                row.append(None if np.isnan(v) else float(v))
            else:
                row.append(_json_safe_cell(v))
        safe_data.append(row)

    return {"index": safe_index, "columns": safe_columns, "data": safe_data}


def fn_build_annual_dataframe(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a monthly DataFrame to annual by summing values by year.
    """
    if monthly_df.empty:
        return monthly_df.copy()

    parsed_columns = pd.to_datetime(monthly_df.columns, errors="coerce")
    if parsed_columns.notna().all():
        # Vectorized: group column indices by year, sum via numpy
        year_labels = parsed_columns.year.astype(int)
        unique_years = sorted(set(year_labels))
        raw = monthly_df.to_numpy(dtype=object, copy=True)
        n_rows, n_cols = raw.shape

        # Convert to float array
        float_arr = np.zeros((n_rows, n_cols), dtype=np.float64)
        for r in range(n_rows):
            for c in range(n_cols):
                try:
                    float_arr[r, c] = float(raw[r, c])
                except (TypeError, ValueError):
                    pass

        # Build year-to-column mapping and sum
        year_col_map: Dict[int, List[int]] = {}
        for c, yr in enumerate(year_labels):
            year_col_map.setdefault(yr, []).append(c)

        annual_arr = np.empty((n_rows, len(unique_years)), dtype=np.float64)
        for yi, yr in enumerate(unique_years):
            annual_arr[:, yi] = float_arr[:, year_col_map[yr]].sum(axis=1)

        return pd.DataFrame(
            data=annual_arr,
            index=monthly_df.index,
            columns=unique_years,
        )

    return monthly_df.T.groupby(level=0, sort=False).sum(min_count=1).T


def fn_export_excel_output_to_file(
    excel_output: Dict[str, Any],
    filename: str = "consolidated_output.xlsx"
) -> None:
    """
    Export excel_output dictionary to an Excel file.
    """
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        # Export monthly_dfs
        for sheet_name, (code, df_json) in excel_output.get("monthly_dfs", {}).items():
            df = pd.DataFrame(
                df_json["data"],
                index=df_json["index"],
                columns=df_json["columns"]
            )
            df.to_excel(writer, sheet_name=f"M_{sheet_name}"[:31])

        # Export annual_dfs
        for sheet_name, (code, df_json) in excel_output.get("annual_dfs", {}).items():
            df = pd.DataFrame(
                df_json["data"],
                index=df_json["index"],
                columns=df_json["columns"]
            )
            df.to_excel(writer, sheet_name=f"A_{sheet_name}"[:31])

    print(f"Exported to {filename}")
    if hasattr(os, "startfile"):
        os.startfile(filename)


def fn_debug_value_preview(value: Any, max_chars: int = 300) -> str:
    """
    Create a truncated string preview of a value for debugging.
    """
    text = repr(value)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def fn_to_debug_dataframe(value: Any, fallback_label: str = "value") -> pd.DataFrame:
    """
    Convert various data types to a DataFrame for debugging/export.
    """
    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, pd.Series):
        series_name = value.name if value.name is not None else fallback_label
        return value.to_frame(name=series_name)

    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return pd.DataFrame(value)
        if value and all(isinstance(item, (list, tuple)) for item in value):
            return pd.DataFrame(value)
        return pd.DataFrame({fallback_label: value})

    if isinstance(value, dict):
        if value and all(not isinstance(item, (list, tuple, dict)) for item in value.values()):
            return pd.DataFrame([value])

        if value and all(isinstance(item, list) for item in value.values()):
            try:
                return pd.DataFrame(value)
            except ValueError:
                pass

        rows = []
        for key, nested_value in value.items():
            rows.append(
                {
                    "key": str(key),
                    "value_type": type(nested_value).__name__,
                    "value_preview": fn_debug_value_preview(nested_value),
                }
            )
        return pd.DataFrame(rows)

    return pd.DataFrame([{fallback_label: fn_debug_value_preview(value)}])


def fn_sanitize_excel_sheet_name(sheet_name: str) -> str:
    """
    Sanitize a string to be a valid Excel sheet name.
    """
    sanitized = str(sheet_name)
    for invalid_char in ["/", "\\", "[", "]", "*", "?", ":"]:
        sanitized = sanitized.replace(invalid_char, "-")
    sanitized = sanitized.strip() or "Sheet"
    return sanitized[:31]


def fn_export_dataframes_to_excel(
    dataframes_dict: Dict[str, Any],
    filename: str,
    description: str,
) -> Optional[str]:
    """
    Export a dictionary of DataFrames to an Excel file.
    """
    if not dataframes_dict:
        return None

    try:
        base_dir = os.path.dirname(__file__)
        output_name = filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx"
        excel_path = os.path.join(base_dir, output_name)
        used_sheet_names: set = set()

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for raw_sheet_name, raw_value in dataframes_dict.items():
                sheet_name = fn_sanitize_excel_sheet_name(raw_sheet_name)
                candidate = sheet_name
                duplicate_counter = 1
                while candidate.lower() in used_sheet_names:
                    suffix = f"_{duplicate_counter}"
                    candidate = f"{sheet_name[: 31 - len(suffix)]}{suffix}"
                    duplicate_counter += 1
                used_sheet_names.add(candidate.lower())

                debug_df = fn_to_debug_dataframe(raw_value, fallback_label=str(raw_sheet_name))
                debug_df.to_excel(writer, sheet_name=candidate, index=True)

        print(f"  Exported {description} to: {excel_path}")
        if hasattr(os, "startfile"):
            os.startfile(excel_path)
        return excel_path
    except Exception as exc:
        print(f"  Error exporting {description}: {exc}")
        return None


def fn_is_debug_export_enabled(export_flags: Dict[str, bool], section_name: str) -> bool:
    """
    Check if debug export is enabled for a specific section.
    """
    return bool(export_flags.get("all_sections", False) or export_flags.get(section_name, False))


def fn_export_debug_sections(
    export_flags: Dict[str, bool],
    section_exports: Dict[str, Dict[str, Any]],
    filename_prefix: str = "consolidated_model_debug",
) -> None:
    """
    Export debug sections to separate Excel files based on export flags.
    """
    for section_name, frames in section_exports.items():
        if not fn_is_debug_export_enabled(export_flags, section_name):
            continue

        fn_export_dataframes_to_excel(
            dataframes_dict=frames,
            filename=f"{filename_prefix}_{section_name}",
            description=f"Consolidated debug section '{section_name}'",
        )
