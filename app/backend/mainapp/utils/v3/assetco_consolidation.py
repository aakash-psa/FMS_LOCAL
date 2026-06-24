
import os
import traceback
import copy
import numpy as np
import pandas as pd
from typing import Any, Dict, Optional
import json
from datetime import date, datetime
import datetime as dt

def _json_safe_value(value):
    """Convert scalar values into JSON-safe primitives for split serialization."""
    if value is None:
        return None

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return None if pd.isna(value) else value.isoformat()

    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()

    if isinstance(value, (pd.Timedelta, dt.timedelta)):
        return None if pd.isna(value) else str(value)

    if isinstance(value, np.timedelta64):
        return None if np.isnat(value) else str(pd.Timedelta(value))

    if isinstance(value, pd.Period):
        return None if pd.isna(value) else str(value)

    try:
        return None if pd.isna(value) else value
    except TypeError:
        return value


def fn_replace_nan(obj, fill_value=None):
    """
    Replace NaN/NaT values in a DataFrame or Series with a JSON-safe value.
    - For DataFrame: Only rows where index != "" are replaced.
    - For Series: All NaN/NaT are replaced.

    Args:
        obj (pd.DataFrame or pd.Series): The object to process.
        fill_value: Value to replace NaN/NaT with (default: None).

    Returns:
        Same type as input, with NaNs replaced as specified.
    """
    try:
        if isinstance(obj, pd.Series):
            return obj.where(pd.notna(obj), fill_value)
        elif isinstance(obj, pd.DataFrame):
            if obj.index.dtype != object:
                obj.index = obj.index.astype(str)
            mask = obj.index != ""
            if not mask.any():
                return obj

            df_to_replace = obj.loc[mask].copy()
            obj.loc[mask] = df_to_replace.where(pd.notna(df_to_replace), fill_value)
            return obj
        else:
            raise TypeError("Input must be a pandas DataFrame or Series.")
    except Exception as e:
        print(f"Error in fn_replace_nan: {e}")
        return obj


def _df_to_split_payload(df: pd.DataFrame) -> dict:
    """Serialize a DataFrame to split orientation with JSON-safe cell values."""
    return {
        "index": [_json_safe_value(item) for item in df.index.tolist()],
        "columns": [_json_safe_value(item) for item in df.columns.tolist()],
        "data": [
            [_json_safe_value(value) for value in row]
            for row in df.to_numpy(dtype=object, copy=False).tolist()
        ],
    }


def _json_to_df(json_dict: dict) -> pd.DataFrame:
    """Reconstruct a DataFrame from the serialized {index, columns, data} format."""
    return pd.DataFrame(
        data=json_dict["data"],
        index=json_dict["index"],
        columns=json_dict["columns"],
    )


def _coerce_flag_bool(value: Any) -> Optional[bool]:
    """Coerce common Yes/No style flag values into booleans."""
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False

    return None


def _pick_asset_payload_value(asset_payload: Dict[str, Any], *keys: str) -> Any:
    """Pick a value from known payload shapes, including Global.AssetDetails fallback."""
    if not isinstance(asset_payload, dict):
        return None

    output_json = asset_payload.get("output_json")
    output_asset_inputs = (
        output_json.get("assetco_inputs")
        if isinstance(output_json, dict) and isinstance(output_json.get("assetco_inputs"), dict)
        else None
    )

    candidate_dicts = [
        asset_payload.get("assetco_inputs") if isinstance(asset_payload.get("assetco_inputs"), dict) else None,
        asset_payload,
        output_asset_inputs,
        output_json if isinstance(output_json, dict) else None,
    ]

    for candidate in candidate_dicts:
        if not isinstance(candidate, dict):
            continue

        for key in keys:
            if key in candidate:
                return candidate.get(key)

        global_obj = candidate.get("Global")
        asset_details = global_obj.get("AssetDetails") if isinstance(global_obj, dict) else None
        if isinstance(asset_details, dict):
            for key in keys:
                if key in asset_details:
                    return asset_details.get(key)

    return None


def _is_jv_payload_item(asset_payload: Dict[str, Any]) -> bool:
    """Resolve JV classification from jvjda/assetco_jv/venture_type flags."""

    jvjda_inclusion = _pick_asset_payload_value(asset_payload, "jvjda_inclusion")
    assetco_jv_inclusion = _pick_asset_payload_value(asset_payload, "assetco_jv_inclusion")
    venture_type = _pick_asset_payload_value(asset_payload, "venture_type")

    jvjda_yes = _coerce_flag_bool(jvjda_inclusion) is True
    assetco_jv_yes = _coerce_flag_bool(assetco_jv_inclusion) is True
    venture_is_jv = str(venture_type).strip().lower() == "jv"

    # Business rule: classify as JV only when all three conditions are satisfied.
    return jvjda_yes and assetco_jv_yes and venture_is_jv


def _resolve_output_json(asset_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize asset payload to an output-json-like dict for both old and new contracts."""
    if not isinstance(asset_payload, dict):
        return None

    resolved_is_jv = _is_jv_payload_item(asset_payload)

    # Legacy contract: payload contains nested "output_json".
    nested_output = asset_payload.get("output_json")
    if isinstance(nested_output, dict):
        normalized_output = dict(nested_output)
        normalized_output["_is_jv"] = resolved_is_jv
        return normalized_output

    # New contract: payload directly carries monthly_dfs / annual_dfs.
    has_annual = isinstance(asset_payload.get("annual_dfs"), dict)
    has_monthly = isinstance(asset_payload.get("monthly_dfs"), dict)
    if not (has_annual or has_monthly):
        return None

    normalized_output: Dict[str, Any] = {}
    if has_annual:
        normalized_output["annual_dfs"] = asset_payload.get("annual_dfs", {})
    if has_monthly:
        normalized_output["monthly_dfs"] = asset_payload.get("monthly_dfs", {})

    # Keep a normalized JV marker consistent with the business-rule split logic.
    normalized_output["_is_jv"] = resolved_is_jv

    return normalized_output


def _is_assetco_included_item(asset_payload: Dict[str, Any]) -> bool:
    """Resolve AssetCo inclusion from supported payload shapes.

    Defaults to True when the flag is missing/unrecognized, to preserve current behavior.
    """

    raw_inclusion = _pick_asset_payload_value(asset_payload, "assetco_inclusion")
    inclusion_value = _coerce_flag_bool(raw_inclusion)
    return True if inclusion_value is None else inclusion_value


def _should_zero_acquisition_price(asset_payload: Dict[str, Any]) -> bool:
    """Zero CFI Acquisition Price when both DevCo and AssetCo inclusion flags are yes."""
    devco_inclusion = _pick_asset_payload_value(asset_payload, "devco_inclusion")
    assetco_inclusion = _pick_asset_payload_value(asset_payload, "assetco_inclusion")

    return (
        _coerce_flag_bool(devco_inclusion) is True
        and _coerce_flag_bool(assetco_inclusion) is True
    )


def _zero_cfi_acquisition_price(freq_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of frequency payload with CFI Acquisition Price row zeroed if present."""
    result = dict(freq_data)
    cfi_value = freq_data.get("Cashflow from Investments")
    if not isinstance(cfi_value, (tuple, list)) or len(cfi_value) < 2:
        return result

    df_json = cfi_value[1]
    if not isinstance(df_json, dict):
        return result

    df = _json_to_df(df_json)
    # List of line items to eliminate (case-insensitive, stripped)
    elimination_lines = [
        "acquisition price",
        "transfer tax / stamp duty",
        "legal fees",
        "brokerage",
        "due diligence cost",
        "asset acquisition cost",
    ]

    net_cashflow_from_investments_line = "Net Cashflow from Investments"

    # Normalize index for matching
    norm_index = df.index.astype(str).str.strip().str.lower()
    for elim_line in elimination_lines:
        row_mask = norm_index == elim_line
        if row_mask.any():
            df.loc[row_mask, :] = 0.0
    # Recompute Net Cashflow from Investments using the same formula as assetco_model.py:
    #   net_cf_investments = -total_acq_cost - total_capex + asset_sale
    # i.e. sum only the three subtotal rows whose stored signs already match that formula:
    #   "Asset Acquisition Cost" (now zeroed) + "Total Capex" + "Net Asset Sale Value"
    # Summing all non-net rows would double-count capex because both the individual
    # Maintenance Capex lines and the "Total Capex" subtotal are present in the dataframe.
    if net_cashflow_from_investments_line.lower() in norm_index.values:
        net_cashflow_mask = norm_index == net_cashflow_from_investments_line.lower()
        if net_cashflow_mask.any():
            subtotal_row_names = {
                "asset acquisition cost",
                "total asset acquisition cost",
                "total capex",
                "net asset sale value",
            }
            subtotal_mask = norm_index.isin(subtotal_row_names) & ~net_cashflow_mask
            numeric_view = df.loc[subtotal_mask, :].apply(pd.to_numeric, errors="coerce")
            recomputed_totals = numeric_view.sum(axis=0, min_count=1)
            numeric_cols = recomputed_totals.index[recomputed_totals.notna()]

            if len(numeric_cols) > 0:
                df.loc[net_cashflow_mask, numeric_cols] = recomputed_totals.loc[numeric_cols].to_numpy()

    updated_cfi = list(cfi_value)
    updated_cfi[1] = _df_to_split_payload(df)
    result["Cashflow from Investments"] = tuple(updated_cfi) if isinstance(cfi_value, tuple) else updated_cfi
    return result


def _apply_acquisition_elimination_for_jv_asset(asset_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply acquisition-price elimination only for JV output payload rows."""
    if not _should_zero_acquisition_price(asset_payload):
        return asset_payload

    updated_payload = copy.deepcopy(asset_payload)

    nested_output = updated_payload.get("output_json")
    if isinstance(nested_output, dict):
        for freq in ("annual_dfs", "monthly_dfs"):
            freq_data = nested_output.get(freq)
            if isinstance(freq_data, dict):
                nested_output[freq] = _zero_cfi_acquisition_price(freq_data)
        return updated_payload

    for freq in ("annual_dfs", "monthly_dfs"):
        freq_data = updated_payload.get(freq)
        if isinstance(freq_data, dict):
            updated_payload[freq] = _zero_cfi_acquisition_price(freq_data)

    return updated_payload


def _split_payload_by_jv_flag(payload: list[Dict[str, Any]]) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Split the incoming payload into JV and non-JV buckets without transforming item structure."""
    jv_payload = []
    consolidation_payload = []

    for asset_payload in payload:
        if not _is_assetco_included_item(asset_payload):
            continue

        if _is_jv_payload_item(asset_payload):
            jv_payload.append(asset_payload)
        else:
            consolidation_payload.append(asset_payload)

    return jv_payload, consolidation_payload


def _empty_like_scalar(value: Any) -> Any:
    """Convert scalar values to None/0 while keeping numeric cells zeroed."""
    if value is None:
        return None

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, bool):
        return 0

    if isinstance(value, (int, float, complex)):
        try:
            return None if pd.isna(value) else 0
        except TypeError:
            return 0

    if isinstance(
        value,
        (
            pd.Timestamp,
            datetime,
            date,
            np.datetime64,
            pd.Timedelta,
            dt.timedelta,
            np.timedelta64,
            pd.Period,
            str,
            bytes,
        ),
    ):
        return None

    try:
        return None if pd.isna(value) else None
    except TypeError:
        return None


def _empty_like_structure(value: Any) -> Any:
    """Recursively clone nested containers, replacing leaf values with None/0."""
    if isinstance(value, dict):
        return {key: _empty_like_structure(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_empty_like_structure(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_empty_like_structure(item) for item in value)

    if isinstance(value, set):
        return {_empty_like_structure(item) for item in value}

    if isinstance(value, pd.Series):
        return value.map(_empty_like_structure)

    if isinstance(value, pd.DataFrame):
        return value.map(_empty_like_structure)

    if isinstance(value, np.ndarray):
        if np.issubdtype(value.dtype, np.number) and not np.issubdtype(value.dtype, np.bool_):
            return np.zeros_like(value)

        transformed = [_empty_like_structure(item) for item in value.ravel().tolist()]
        return np.array(transformed, dtype=object).reshape(value.shape)

    return _empty_like_scalar(value)


def _build_empty_payload_template(payload: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Return a one-item placeholder mirroring the full nested asset payload shape."""
    for asset_payload in payload:
        if not isinstance(asset_payload, dict):
            continue

        return [_empty_like_structure(asset_payload)]

    return []


def _get_first_output_json(payload: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the first output payload available in either supported contract shape."""
    for asset_payload in payload:
        output_json = _resolve_output_json(asset_payload)
        if isinstance(output_json, dict):
            return output_json
    return None


def _build_zeroed_freq_result(freq_data: Dict[str, Any], cashflow_keys: set[str]) -> Dict[str, Any]:
    """Clone the frequency structure and zero only the cashflow section values."""
    freq_result = {}

    for section_key, section_value in freq_data.items():
        if not isinstance(section_value, (tuple, list)) or len(section_value) < 2:
            continue

        code, df_json = section_value
        if section_key not in cashflow_keys:
            freq_result[section_key] = (code, df_json)
            continue

        zero_df = _json_to_df(df_json)
        zero_df.loc[:, :] = 0.0
        freq_result[section_key] = (code, _df_to_split_payload(zero_df))

    return freq_result


def wrapper_for_vars(payload: Any, is_save) -> Optional[Any]:
    
    try:
        # ====================================================================
        # EXTRACT INPUT DATA
        # ====================================================================

        n_assets = len(payload)
        if n_assets == 0:
            print("Warning: empty payload, nothing to consolidate")
            return None

        jv_output, consolidated_output = _split_payload_by_jv_flag(payload)
        jv_output = [_apply_acquisition_elimination_for_jv_asset(asset_payload) for asset_payload in jv_output]
        # Use real non-JV rows for consolidation math; return placeholders only if a bucket is empty.
        consolidation_assets = consolidated_output

        if not jv_output:
            jv_output = _build_empty_payload_template(payload)
        if not consolidated_output:
            consolidated_output = _build_empty_payload_template(payload)

        template_output_json = _get_first_output_json(payload)

        # ====================================================================
        # CONSOLIDATE CASHFLOW DATAFRAMES
        # ====================================================================
        # For each frequency (annual / monthly) and each cashflow section
        # (CFO, CFI, CFF), sum the DataFrames across all assets.
        # Timelines are taken from the first asset (they are identical).
        # ====================================================================

        # Keys that hold summable cashflow DataFrames (skip timeline keys)
        _cashflow_keys = {
            "Cashflow from Operations",
            "Cashflow from Investments",
            "Cashflow from Financing",
            "Hospitality P&L"
        }

        _EXPORT_TO_EXCEL = False

        excel_output = {}  # {"annual_dfs": {...}, "monthly_dfs": {...}}

        for freq in ("annual_dfs", "monthly_dfs"):

            # Accumulators: section_key -> running-sum DataFrame
            accum: Dict[str, pd.DataFrame] = {}
            # Store code strings and timeline from first asset
            codes: Dict[str, str] = {}
            timeline_key = None
            timeline_value = None

            for idx, asset_payload in enumerate(consolidation_assets):
                output_json = _resolve_output_json(asset_payload)
                if output_json is None:
                    print(f"Warning: asset index {idx} has no recognized cashflow output payload, skipping")
                    continue

                freq_data = output_json.get(freq, {})
                if not isinstance(freq_data, dict):
                    continue

                for section_key, section_value in freq_data.items():
                    print(f"Processing asset {idx}, frequency '{freq}', section '{section_key}'")
                    if not isinstance(section_value, (tuple, list)) or len(section_value) < 2:
                        continue

                    code, df_json = section_value[0], section_value[1]
                    if not isinstance(df_json, dict):
                        continue

                    # Timeline rows — just keep the first one
                    if section_key not in _cashflow_keys:
                        if timeline_key is None:
                            timeline_key = section_key
                            timeline_value = (code, df_json)
                        continue

                    df = _json_to_df(df_json)
                    # Convert to numeric, coerce non-numeric (headers/separators) to NaN
                    df = df.apply(pd.to_numeric, errors="coerce")

                    if section_key not in accum:
                        accum[section_key] = df
                        codes[section_key] = code
                    else:
                        # Align and sum — NaN + NaN stays NaN, NaN + number = number
                        accum[section_key] = accum[section_key].add(df, fill_value=0.0)

            # Build consolidated output for this frequency
            freq_result = {}
            for section_key in accum:
                # Preserve missing values as null while keeping separator rows untouched.
                result_df = fn_replace_nan(accum[section_key].copy(), fill_value=None)
                freq_result[section_key] = (
                    codes[section_key],
                    _df_to_split_payload(result_df),
                )

            # Add timeline if present
            if timeline_key is not None:
                freq_result[timeline_key] = timeline_value

            if not freq_result and template_output_json is not None:
                freq_result = _build_zeroed_freq_result(
                    template_output_json.get(freq, {}),
                    _cashflow_keys,
                )

            excel_output[freq] = freq_result

        if _EXPORT_TO_EXCEL:
            fn_export_to_excel(excel_output)
        
        if is_save:
            return {
                "exceloutput": excel_output,
                "jvoutput": jv_output,
                "consolidatedoutput": consolidated_output
            }
        
        return {
            "exceloutput": excel_output,
            # "jvoutput": jv_output,
            # "consolidatedoutput": consolidated_output
        }
    
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            error_msg = (
                f"Error in wrapper_for_vars at line {last_frame.lineno} "
                f"in {last_frame.filename}: {str(e)}\n"
                f"Full Traceback:\n{traceback.format_exc()}"
            )
            print(error_msg)
        else:
            print(f"Error in wrapper_for_vars: {str(e)}")
        return None

def fninitialising_all_values(payload: Any, is_save) -> Optional[Any]:
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
        

        # Call the consolidation wrapper
        output = wrapper_for_vars(payload, is_save)
        return output
        
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

def fninitialising_assetco_consolidation_values(consolidated_input: Any, is_save) -> Optional[Any]:
    try:
        if not consolidated_input:
            print("Error in fninitialising_assetco_consolidation_values: consolidated_input must be non-empty")
            return None


        # Reuse core consolidated business logic; it gracefully handles missing models.
        return fninitialising_all_values(consolidated_input,is_save)
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            print(
                f"Error in fninitialising_assetco_consolidation_values at line {last_frame.lineno}: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}"
            )
        else:
            print(f"Error in fninitialising_assetco_consolidation_values: {str(e)}")
        return None


def fn_export_to_excel(output: Dict[str, Any], file_path: str = "assetco_consolidated_output.xlsx") -> Optional[str]:
    """
    Export the AssetCo consolidated output to an Excel file with separate tabs
    for each cashflow section (monthly and annual).

    Args:
        output: Dictionary with monthly_dfs and annual_dfs from wrapper_for_vars.
        file_path: Destination path for the Excel file.

    Returns:
        The file path on success, or None on failure.
    """
    try:
        if output is None:
            print("Error in fn_export_to_excel: output cannot be None")
            return None

        if not isinstance(output, dict):
            print(f"Error in fn_export_to_excel: output must be a dictionary, got {type(output).__name__}")
            return None

        # Mapping of (frequency key, section key) → Excel sheet name
        _sheet_map = [
            # Monthly tabs
            ("monthly_dfs", "Cashflow from Operations",  "Monthly CFO"),
            ("monthly_dfs", "Cashflow from Investments", "Monthly CFI"),
            ("monthly_dfs", "Cashflow from Financing",   "Monthly CFF"),
            ("monthly_dfs", "Monthly Timeline",          "Monthly Timeline"),
            # Annual tabs
            ("annual_dfs",  "Cashflow from Operations",  "Annual CFO"),
            ("annual_dfs",  "Cashflow from Investments", "Annual CFI"),
            ("annual_dfs",  "Cashflow from Financing",   "Annual CFF"),
            ("annual_dfs",  "Yearly Timeline",           "Yearly Timeline"),
        ]

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            for freq_key, section_key, sheet_name in _sheet_map:
                freq_data = output.get(freq_key, {})
                section_data = freq_data.get(section_key)
                if section_data is None:
                    continue

                # Each section is stored as (code, {index, columns, data})
                if not isinstance(section_data, (tuple, list)) or len(section_data) < 2:
                    continue

                df_json = section_data[1]
                if not isinstance(df_json, dict):
                    continue
                if not all(k in df_json for k in ("index", "columns", "data")):
                    continue

                df = pd.DataFrame(
                    data=df_json["data"],
                    index=df_json["index"],
                    columns=df_json["columns"],
                )
                df.to_excel(writer, sheet_name=sheet_name)
                print(f"Exported: {sheet_name}")

        print(f"\nExcel file saved successfully: {file_path}")

        # Try to open the file automatically (Windows)
        try:
            os.startfile(file_path)
            print(f"Opening Excel file: {file_path}")
        except Exception as open_error:
            print(f"Could not open Excel file automatically: {open_error}")

        return file_path

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            print(
                f"Error in fn_export_to_excel at line {last_frame.lineno}: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}"
            )
        else:
            print(f"Error in fn_export_to_excel: {str(e)}")
        return None
