"""
JSON/DataFrame conversion and data extraction helpers.

Functions in this module were previously duplicated identically across
project_conso_landco.py, project_conso_devco.py, and project_conso_assetco.py.
"""

import traceback
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

# Split DataFrame payload contract - required keys for JSON DataFrame reconstruction
_SPLIT_DF_REQUIRED_KEYS = {"data", "index", "columns"}


def fn_json_dict_to_dataframe(json_payload: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """
    Convert a split-style JSON payload into a pandas DataFrame.

    Parameters:
    -----------
    json_payload : Dict[str, Any]
        Dictionary containing DataFrame data in split format.
        Expected keys: 'data', 'index', 'columns'

    Returns:
    --------
    Optional[pd.DataFrame]
        Reconstructed DataFrame, or None if the payload is invalid.
    """
    try:
        if not isinstance(json_payload, dict):
            print(
                "Error in fn_json_dict_to_dataframe: payload must be a dictionary, "
                f"got {type(json_payload).__name__}"
            )
            return None

        missing_keys = _SPLIT_DF_REQUIRED_KEYS.difference(json_payload.keys())
        if missing_keys:
            print(
                "Error in fn_json_dict_to_dataframe: missing required keys: "
                f"{sorted(missing_keys)}"
            )
            return None

        return pd.DataFrame(
            data=json_payload["data"],
            index=json_payload["index"],
            columns=json_payload["columns"],
        )

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last_frame = tb[-1]
            error_msg = (
                f"Error in fn_json_dict_to_dataframe at line {last_frame.lineno} "
                f"in {last_frame.filename}: {str(e)}\n"
                f"Full Traceback:\n{traceback.format_exc()}"
            )
            print(error_msg)
        else:
            print(f"Error in fn_json_dict_to_dataframe: {str(e)}")
        return None


def fn_extract_assumptions_module(parent: Dict[str, Any], key: str) -> Optional[pd.DataFrame]:
    """
    Extract a DataFrame from a nested dictionary field.
    """
    if not isinstance(parent, dict):
        print(f"fn_get_df_from_dict: parent is not a dict (got {type(parent).__name__})")
        return None
    return fn_json_dict_to_dataframe(parent.get(key, {}))


def fn_safe_extract_dataframe(
    source_dict: Any,
    key: str,
    source_name: str = "source",
) -> pd.DataFrame:
    """
    Safely extract a split-style DataFrame payload by key with print-based error control.
    """
    if not isinstance(source_dict, dict):
        print(
            f"fn_safe_extract_dataframe: '{source_name}' must be a dict, "
            f"got {type(source_dict).__name__} for key '{key}'"
        )
        return pd.DataFrame()

    if key not in source_dict:
        print(f"fn_safe_extract_dataframe: key '{key}' not found in '{source_name}'")
        return pd.DataFrame()

    payload = source_dict.get(key, {})
    if not isinstance(payload, dict):
        print(
            f"fn_safe_extract_dataframe: value for key '{key}' in '{source_name}' "
            f"must be a dict, got {type(payload).__name__}"
        )
        return pd.DataFrame()

    df = fn_json_dict_to_dataframe(payload)
    if df is None:
        print(
            f"fn_safe_extract_dataframe: could not convert key '{key}' "
            f"from '{source_name}' to DataFrame"
        )
        return pd.DataFrame()

    return df.copy()


def fn_extract_assumptions(parent: Dict[str, Any], module_key: str, col: str) -> Optional[pd.Series]:
    """
    Extract a specific column as a Series from a nested DataFrame structure.
    """
    df = fn_extract_assumptions_module(parent, module_key)
    if df is None or not isinstance(df, pd.DataFrame):
        print(f"fn_get_col_from_df: input is not a DataFrame (got {type(df).__name__})")
        return None
    if col not in df.columns:
        print(f"fn_get_col_from_df: column '{col}' not found in DataFrame")
        return None
    output_series = df.loc[:, col]
    return output_series


def fn_extract_core_sources(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extract normalized source blocks from the raw consolidation payload.
    """
    _landco_source = payload.get("landco", {}) if isinstance(payload.get("landco"), dict) else {}
    _devco_source = payload.get("devco", {}) if isinstance(payload.get("devco"), dict) else {}
    _assetco_source = payload.get("assetco_consolidated", []) if isinstance(payload.get("assetco_consolidated"), list) else []
    _jv_source = payload.get("jv_consolidation", []) if isinstance(payload.get("jv_consolidation"), list) else []

    return _landco_source, _devco_source, _assetco_source, _jv_source


def fn_extract_module_data(
    module_name: str,
    source: Union[Dict[str, Any], List[Dict[str, Any]]],
    module_targets: Dict[str, Dict[str, Any]],
) -> None:
    """
    Populate target dictionaries for each module using configured key mappings.
    """
    if module_name in {"LandCo", "DevCo"}:
        source_dict = source if isinstance(source, dict) else {}
        for key, target in module_targets.items():
            val = source_dict.get(key, {})
            if isinstance(val, dict):
                target.update(val)
        return

    if module_name == "AssetCo":
        assets = source if isinstance(source, list) else []
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue

            for key, target in module_targets.items():
                target[index] = asset.get(key, {})


def _flatten_named_range_values(values: Any) -> Any:
    """
    Flatten Excel named-range values with the same rules used in v3 readers.
    """
    if isinstance(values, list):
        if len(values) == 1 and isinstance(values[0], list):
            return values[0][0] if len(values[0]) == 1 else values[0]
        if all(isinstance(item, list) and len(item) == 1 for item in values):
            return [item[0] for item in values]
        return values
    return values


def _coerce_named_range_vector(values: Any) -> List[Any]:
    """
    Coerce flattened named-range values to a 1-D list.
    """
    if not isinstance(values, list):
        return []
    if values and all(isinstance(item, list) for item in values):
        if len(values) == 1:
            return list(values[0])
        if all(len(item) == 1 for item in values):
            return [item[0] for item in values]
        return list(values[0])
    return list(values)


def _coerce_named_range_matrix(values: Any) -> List[List[Any]]:
    """
    Coerce flattened named-range values to a 2-D row-major matrix.
    """
    if not isinstance(values, list):
        return []

    if (
        len(values) == 1
        and isinstance(values[0], list)
        and values[0]
        and all(isinstance(row, list) for row in values[0])
    ):
        values = values[0]

    matrix: List[List[Any]] = []
    for row in values:
        if isinstance(row, list):
            matrix.append(row)
        else:
            matrix.append([row])
    return matrix


def _normalize_named_token(raw: Any) -> str:
    """
    Normalize named-range class/attribute tokens for tolerant matching.
    """
    if raw is None:
        return ""
    return (
        str(raw)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
    )


def _resolve_named_ranges(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Resolve named-ranges list from payload, supporting both key variants.
    """
    for key in ("namedRanges", "namedranges"):
        values = payload.get(key)
        if isinstance(values, list):
            return values
    return []


def fn_extract_synthetic_asset_ids_from_mastersheet(payload: Dict[str, Any]) -> List[str]:
    """
    Resolve Synthetic-selected asset IDs from MasterSheet named ranges.

    Selection rule:
    - class row column matches FiltrationDropdown variants
    - attribute row matches output_inclusion
    - unit-data row value is Yes

    Asset IDs are taken from ProjectDetails.asset_unique_identifier.
    """
    if not isinstance(payload, dict):
        return []

    named_ranges = _resolve_named_ranges(payload)
    if not named_ranges:
        return []

    nr_lookup: Dict[str, Dict[str, Any]] = {}
    for entry in named_ranges:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            nr_lookup[name] = entry

    class_key = "m.mastersheet.inputs.class.row"
    attr_key = "m.mastersheet.attributes.row"
    data_key = "m.mastersheet.unit.data"

    if class_key not in nr_lookup or attr_key not in nr_lookup or data_key not in nr_lookup:
        return []

    class_values = _flatten_named_range_values(nr_lookup[class_key].get("values"))
    attr_values = _flatten_named_range_values(nr_lookup[attr_key].get("values"))
    unit_values = _flatten_named_range_values(nr_lookup[data_key].get("values"))

    class_row = _coerce_named_range_vector(class_values)
    attr_row = _coerce_named_range_vector(attr_values)
    unit_rows = _coerce_named_range_matrix(unit_values)

    if not class_row or not attr_row or not unit_rows:
        return []

    filtration_classes = {
        "filtrationdropwdown",
        "filtrationdropdown",
        "filtrationdropdowns",
    }

    output_inclusion_idx: Optional[int] = None
    asset_unique_id_idx: Optional[int] = None

    for col_idx in range(max(len(class_row), len(attr_row))):
        class_token = _normalize_named_token(class_row[col_idx] if col_idx < len(class_row) else None)
        attr_token = _normalize_named_token(attr_row[col_idx] if col_idx < len(attr_row) else None)

        if output_inclusion_idx is None:
            if class_token in filtration_classes and attr_token == "outputinclusion":
                output_inclusion_idx = col_idx

        if asset_unique_id_idx is None:
            if class_token == "projectdetails" and attr_token == "assetuniqueidentifier":
                asset_unique_id_idx = col_idx

        if output_inclusion_idx is not None and asset_unique_id_idx is not None:
            break

    if output_inclusion_idx is None or asset_unique_id_idx is None:
        return []

    selected_asset_ids: List[str] = []
    seen_asset_ids = set()

    for row in unit_rows:
        if not isinstance(row, list):
            continue
        if output_inclusion_idx >= len(row) or asset_unique_id_idx >= len(row):
            continue

        include_token = _normalize_named_token(row[output_inclusion_idx])
        if include_token != "yes":
            continue

        asset_id = str(row[asset_unique_id_idx]).strip()
        if not asset_id:
            continue
        if asset_id.lower() in {"none", "nan", "nat"}:
            continue
        if asset_id in seen_asset_ids:
            continue

        seen_asset_ids.add(asset_id)
        selected_asset_ids.append(asset_id)

    return selected_asset_ids
