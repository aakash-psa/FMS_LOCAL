"""
JV Consolidation - Utility Functions
=====================================

Named range reading, class attribute assignment, class initialisation,
normalisation helpers, and selection resolution used by the main
jv_consolidation module.
"""

import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =====================================================================
# Named Range Reading
# =====================================================================

def fn_read_all_named_ranges_json(namedranges: list, prefixes: List[str]) -> pd.DataFrame:
    """
    Filter *namedranges* list by *prefixes*, flatten value dimensionality.

    Dimensionality rules (matching LandCo fn_read_all_named_ranges_json):
      [[single]]              -> scalar
      [[v1, v2, ...]]         -> 1-D list  (single row)
      [[v1],[v2],[v3]]        -> 1-D list  (single column)
      [[r0c0,r0c1],[r1c0,...]] -> 2-D list  (multi-row, multi-col)

    Returns DataFrame[name, value].
    """
    if not namedranges:
        return pd.DataFrame(columns=["name", "value"])

    prefix_lower = [p.lower() for p in prefixes]
    named_values: List[Tuple[str, Any]] = []

    for entry in namedranges:
        name = entry.get("name", "")
        if not any(name.lower().startswith(p) for p in prefix_lower):
            continue

        values = entry.get("values")
        if isinstance(values, list):
            if len(values) == 1 and isinstance(values[0], list):
                value = values[0][0] if len(values[0]) == 1 else values[0]
            elif all(isinstance(item, list) and len(item) == 1 for item in values):
                value = [item[0] for item in values]
            else:
                value = values
        else:
            value = values

        named_values.append((name, value))

    if named_values:
        return pd.DataFrame(named_values, columns=["name", "value"])
    return pd.DataFrame(columns=["name", "value"])


def _read_scalar(df: pd.DataFrame, key: str, default=None):
    """Read a single scalar value from an assumptions DataFrame."""
    if df.empty:
        return default
    match = df.loc[df["name"] == key, "value"]
    if match.empty:
        return default
    val = match.iloc[0]
    if isinstance(val, list):
        return val[0] if len(val) == 1 else default
    return val


def _read_array(df: pd.DataFrame, key: str) -> list:
    """Read a 1-D array value from an assumptions DataFrame."""
    if df.empty:
        return []
    match = df.loc[df["name"] == key, "value"]
    if match.empty:
        return []
    val = match.iloc[0]
    if isinstance(val, list):
        if val and isinstance(val[0], list):
            return [row[0] if isinstance(row, list) and len(row) == 1 else row
                    for row in val]
        return val
    return [val]


# =====================================================================
# Class Attribute Assignment (matches JV archive setattr pattern)
# =====================================================================

def _normalize_class_name(name: str) -> str:
    """Normalize a class name for flexible matching.
    Strips spaces, underscores, hyphens, slashes; lowercases."""
    return name.replace(" ", "").replace("_", "").replace("-", "").replace("/", "").lower()


def fn_assign_global_class_attributes(cls, assumptions: pd.DataFrame,
                                       class_key: str, attr_key: str, value_key: str,
                                       class_name_map: Optional[Dict[str, str]] = None):
    """
    Assigns attribute values from assumptions to a Global class.

    Reads global class/attribute/value data from assumptions DataFrame
    and sets corresponding class attributes. Handles date conversion
    from Excel serial number format.
    """
    try:
        class_names_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        attr_names_match  = assumptions.loc[assumptions["name"] == attr_key, "value"]
        attr_values_match = assumptions.loc[assumptions["name"] == value_key, "value"]
        
        if class_names_match.empty or attr_names_match.empty or attr_values_match.empty:
            return

        class_names = class_names_match.iloc[0]
        attr_names  = attr_names_match.iloc[0]
        attr_values = attr_values_match.iloc[0]

        if not isinstance(class_names, list) or not isinstance(attr_names, list):
            return

        class_name = cls.__name__
        mapped_name = (class_name_map or {}).get(class_name, class_name)
        norm_mapped = _normalize_class_name(mapped_name)

        _match_count = 0
        for i, attr in enumerate(attr_names):
            if i >= len(class_names):
                continue
            excel_cls = str(class_names[i]) if class_names[i] is not None else ""
            if excel_cls != mapped_name and _normalize_class_name(excel_cls) != norm_mapped:
                continue
            if not hasattr(cls, attr):
                continue
            if i >= len(attr_values):
                continue

            _match_count += 1
            val = attr_values[i]
            if "date" in attr.lower() and isinstance(val, (int, float)):
                if val == "" or val == 0:
                    setattr(cls, attr, None)
                else:
                    converted = datetime.fromtimestamp(
                        (val - 25569) * 86400.0
                    ).strftime('%Y-%m-%d')
                    setattr(cls, attr, pd.to_datetime(converted))
            else:
                setattr(cls, attr, val)

    except Exception as e:
        raise


def fn_assign_asset_class_attributes(cls, assumptions: pd.DataFrame,
                                      class_key: str, attr_key: str, data_key: str,
                                      inclusion_attr: str = "asset_jv_inclusion",
                                      class_name_map: Optional[Dict[str, str]] = None):
    """
    Assigns attribute values from assumptions to an Asset class.

    Reads asset class/attribute/value data from assumptions DataFrame
    and sets corresponding class attributes as lists (one value per asset).
    Handles date conversion from Excel serial number format.
    """
    try:
        class_names_match = assumptions.loc[assumptions["name"] == class_key, "value"]
        attr_names_match  = assumptions.loc[assumptions["name"] == attr_key, "value"]
        data_match        = assumptions.loc[assumptions["name"] == data_key, "value"]

        if class_names_match.empty or attr_names_match.empty or data_match.empty:
            return

        class_names = class_names_match.iloc[0]
        attr_names  = attr_names_match.iloc[0]
        attr_values = data_match.iloc[0]

        if not isinstance(class_names, list) or not isinstance(attr_names, list):
            return
        if not isinstance(attr_values, list):
            return

        class_name = cls.__name__
        mapped_name = (class_name_map or {}).get(class_name, class_name)
        norm_mapped = _normalize_class_name(mapped_name)
    
        # Find inclusion flag index
        inclusion_idx = None
        if inclusion_attr in attr_names:
            inclusion_idx = attr_names.index(inclusion_attr)

        if inclusion_idx is not None:
            inclusion_flags = [
                row[inclusion_idx] == "Yes"
                for row in attr_values
                if isinstance(row, list) and inclusion_idx < len(row)
            ]
        else:
            inclusion_flags = [True] * len(attr_values)

        for i, attr in enumerate(attr_names):
            if i >= len(class_names):
                continue
            excel_cls = str(class_names[i]) if class_names[i] is not None else ""
            if excel_cls != mapped_name and _normalize_class_name(excel_cls) != norm_mapped:
                continue
            if not hasattr(cls, attr):
                continue

            col = []
            is_date = "date" in attr.lower()
            for idx, row in enumerate(attr_values):
                if not isinstance(row, list) or i >= len(row):
                    col.append(pd.NaT if is_date else np.nan)
                    continue
                val = row[i]
                if idx < len(inclusion_flags) and not inclusion_flags[idx]:
                    col.append(pd.NaT if is_date else np.nan)
                elif val == "" or val is None:
                    col.append(pd.NaT if is_date else np.nan)
                elif is_date:
                    if val == 0:
                        col.append(pd.NaT)
                    else:
                        try:
                            converted = datetime.fromtimestamp(
                                (float(val) - 25569) * 86400.0
                            ).strftime('%Y-%m-%d')
                            col.append(pd.to_datetime(converted))
                        except (ValueError, TypeError, OSError):
                            col.append(pd.NaT)
                else:
                    col.append(val)
            setattr(cls, attr, col)
    except Exception as e:
        raise


def fn_initialize_global_class(assumptions: pd.DataFrame,
                                global_cls, class_key: str,
                                attr_key: str, value_key: str,
                                class_name_map: Optional[Dict[str, str]] = None):
    """
    Initializes all Global subclasses with values from assumptions.
    """
    try:
        for subclass_name in dir(global_cls):
            subclass = getattr(global_cls, subclass_name)
            if isinstance(subclass, type):
                fn_assign_global_class_attributes(
                    subclass, assumptions, class_key, attr_key, value_key,
                    class_name_map,
                )
    except Exception as e:
        raise


def fn_initialize_asset_class(assumptions: pd.DataFrame,
                               asset_cls, class_key: str,
                               attr_key: str, data_key: str,
                               inclusion_attr: str = "asset_jv_inclusion",
                               class_name_map: Optional[Dict[str, str]] = None):
    """
    Initializes all Asset subclasses with values from assumptions.
    """
    try:
        for subclass_name in dir(asset_cls):
            subclass = getattr(asset_cls, subclass_name)
            if isinstance(subclass, type):
                fn_assign_asset_class_attributes(
                    subclass, assumptions, class_key, attr_key, data_key,
                    inclusion_attr, class_name_map,
                )
    except Exception as e:
        raise


# =====================================================================
# AssetCo Entry Normalisation
# =====================================================================

_CFS_SECTIONS  = ("Cashflow from Operations", "Cashflow from Investments", "Cashflow from Financing")


def _normalize_assetco_entries(raw_list: list) -> List[dict]:
    """
    Normalise AssetCo per-asset entries so every entry has direct
    section keys at the top level.

    Handles three formats:
      a) Direct:   entry["Cashflow from Operations"] = {index,columns,data}
      b) Nested:   entry["monthly_dfs"]["Cashflow from Operations"] =
                        ("o.assetco.cfo.me", {index,columns,data})
      c) Legacy:   entry["output_json"]["monthly_dfs"]["Cashflow from Operations"] =
                        ("o.assetco.cfo.me", {index,columns,data})
    """
    normalised: List[dict] = []
    for ei, entry in enumerate(raw_list):
        if not isinstance(entry, dict):
            continue
        asset_name = entry.get("asset_name", f"(unnamed-{ei})")
        norm: Dict[str, Any] = {"asset_name": asset_name}

        # Format A: direct CFS section keys at top level
        for section in _CFS_SECTIONS:
            val = entry.get(section)
            if isinstance(val, dict) and "index" in val:
                norm[section] = val

        if any(section in norm for section in _CFS_SECTIONS):
            normalised.append(norm)
            continue

        # Resolve the monthly_dfs source - try both new and legacy contract
        monthly = entry.get("monthly_dfs")
        if not isinstance(monthly, dict):
            output_json = entry.get("output_json", {})
            if isinstance(output_json, dict):
                monthly = output_json.get("monthly_dfs")

        if isinstance(monthly, dict):
            for section in _CFS_SECTIONS:
                val = monthly.get(section)
                if isinstance(val, (tuple, list)) and len(val) >= 2:
                    payload_val = val[1]
                    if isinstance(payload_val, dict) and "index" in payload_val:
                        norm[section] = payload_val
                elif isinstance(val, dict) and "index" in val:
                    norm[section] = val

        if any(section in norm for section in _CFS_SECTIONS):
            normalised.append(norm)

    return normalised


# =====================================================================
# Asset & Selection Resolution
# =====================================================================

def _safe_str_lower(val) -> str:
    """Convert a value to stripped lowercase string, handling None/NaN/NaT."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("nan", "nat", "none", ""):
        return ""
    return s


def _get_asset_names_from_classes(MasterSheet) -> List[str]:
    """Get asset names from the populated MasterSheet.Asset.ProjectDetails class.
    Returns only valid (non-empty, non-nan) names."""
    names = MasterSheet.Asset.ProjectDetails.asset_name
    if isinstance(names, list):
        return [
            str(n) for n in names
            if n is not None and str(n).strip() and str(n).strip().lower() != "nan"
        ]
    return []


def _get_raw_asset_names_from_classes(MasterSheet) -> List[Optional[str]]:
    """Get the RAW asset name list preserving index alignment with units.data rows.
    Empty/nan entries are kept as None so indices match JVModule attribute lists."""
    names = MasterSheet.Asset.ProjectDetails.asset_name
    if isinstance(names, list):
        result: List[Optional[str]] = []
        for n in names:
            if n is None or str(n).strip() == "" or str(n).strip().lower() == "nan":
                result.append(None)
            else:
                result.append(str(n).strip())
        return result
    return []


def _get_asset_names_from_payload(
    landco_data: dict, devco_data: dict,
) -> List[str]:
    """
    Resolve asset names from LandCo/DevCo asset_assumptions.
    Handles both dict-of-lists and split-payload (class_to_dict) formats.
    """
    for model_data in (landco_data, devco_data):
        if not model_data:
            continue
        assumptions = model_data.get("asset_assumptions", {})
        if not isinstance(assumptions, dict):
            continue
        project_details = assumptions.get("ProjectDetails", {})
        if not isinstance(project_details, dict):
            continue

        # Format A: dict-of-lists {"asset_name": ["A", "B"]}
        names = project_details.get("asset_name")
        if names is not None:
            if isinstance(names, (list, tuple)):
                return [str(n) for n in names if str(n).strip().lower() != "nan"]
            if isinstance(names, dict):
                sorted_items = sorted(
                    names.items(),
                    key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
                )
                return [str(v) for _, v in sorted_items if str(v).strip().lower() != "nan"]

        # Format B: split-payload {index, columns, data} from class_to_dict
        columns = project_details.get("columns")
        data = project_details.get("data")
        if isinstance(columns, list) and isinstance(data, list):
            col_idx = None
            for ci, col_name in enumerate(columns):
                if str(col_name).strip().lower() == "asset_name":
                    col_idx = ci
                    break
            if col_idx is not None:
                result = []
                for row in data:
                    if isinstance(row, list) and col_idx < len(row):
                        result.append(str(row[col_idx]))
                if result:
                    return result

    # Fallback: infer asset count from CFS data rows
    for model_data in (landco_data, devco_data):
        if not model_data:
            continue
        for section in _CFS_SECTIONS:
            section_data = model_data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for item_json in section_data.values():
                if isinstance(item_json, dict) and "data" in item_json:
                    return [f"Asset_{i}" for i in range(len(item_json["data"]))]

    return []


def _resolve_interparty_counterparties(
    land_transformation: bool,
    vertical_development: bool,
    asset_operations: bool,
) -> Dict[str, str]:
    """
    Derive interparty acquisition/exit counterparties for LandCo, DevCo and
    AssetCo based on which lifecycle stages are active for an asset.

    The six scenarios that arise from the three binary lifecycle flags map to:

      LC=Yes, DC=No,  AC=No   (Scenario 1)
        LandCo Acquisition CP : External
        LandCo Exit CP        : External
        DevCo  Acquisition CP : NA
        DevCo  Exit CP        : NA
        AssetCo Acquisition CP: NA
        AssetCo Exit CP       : NA

      LC=No,  DC=Yes, AC=No   (Scenario 2)
        LandCo Acquisition CP : NA
        LandCo Exit CP        : NA
        DevCo  Acquisition CP : External
        DevCo  Exit CP        : External
        AssetCo Acquisition CP: NA
        AssetCo Exit CP       : NA

      LC=No,  DC=No,  AC=Yes  (Scenario 3)
        LandCo Acquisition CP : NA
        LandCo Exit CP        : NA
        DevCo  Acquisition CP : NA
        DevCo  Exit CP        : NA
        AssetCo Acquisition CP: External
        AssetCo Exit CP       : External

      LC=Yes, DC=Yes, AC=No   (Scenario 4)
        LandCo Acquisition CP : External
        LandCo Exit CP        : DevCo
        DevCo  Acquisition CP : LandCo
        DevCo  Exit CP        : External
        AssetCo Acquisition CP: NA
        AssetCo Exit CP       : NA

      LC=No,  DC=Yes, AC=Yes  (Scenario 5)
        LandCo Acquisition CP : NA
        LandCo Exit CP        : NA
        DevCo  Acquisition CP : External
        DevCo  Exit CP        : AssetCo
        AssetCo Acquisition CP: DevCo
        AssetCo Exit CP       : External

      LC=Yes, DC=Yes, AC=Yes  (Scenario 6)
        LandCo Acquisition CP : External
        LandCo Exit CP        : DevCo
        DevCo  Acquisition CP : LandCo
        DevCo  Exit CP        : AssetCo
        AssetCo Acquisition CP: DevCo
        AssetCo Exit CP       : External

    Any combination not covered above (e.g. only AssetCo active without DevCo,
    or none active) returns all NA.
    """
    NA = "NA"

    lc = bool(land_transformation)
    dc = bool(vertical_development)
    ac = bool(asset_operations)

    if lc and not dc and not ac:       # Scenario 1
        return {
            "landco_acquisition_cp":  "External",
            "landco_exit_cp":         "External",
            "devco_acquisition_cp":   NA,
            "devco_exit_cp":          NA,
            "assetco_acquisition_cp": NA,
            "assetco_exit_cp":        NA,
        }
    if not lc and dc and not ac:       # Scenario 2
        return {
            "landco_acquisition_cp":  NA,
            "landco_exit_cp":         NA,
            "devco_acquisition_cp":   "External",
            "devco_exit_cp":          "External",
            "assetco_acquisition_cp": NA,
            "assetco_exit_cp":        NA,
        }
    if not lc and not dc and ac:       # Scenario 3
        return {
            "landco_acquisition_cp":  NA,
            "landco_exit_cp":         NA,
            "devco_acquisition_cp":   NA,
            "devco_exit_cp":          NA,
            "assetco_acquisition_cp": "External",
            "assetco_exit_cp":        "External",
        }
    if lc and dc and not ac:           # Scenario 4
        return {
            "landco_acquisition_cp":  "External",
            "landco_exit_cp":         "DevCo",
            "devco_acquisition_cp":   "LandCo",
            "devco_exit_cp":          "External",
            "assetco_acquisition_cp": NA,
            "assetco_exit_cp":        NA,
        }
    if not lc and dc and ac:           # Scenario 5
        return {
            "landco_acquisition_cp":  NA,
            "landco_exit_cp":         NA,
            "devco_acquisition_cp":   "External",
            "devco_exit_cp":          "AssetCo",
            "assetco_acquisition_cp": "DevCo",
            "assetco_exit_cp":        "External",
        }
    if lc and dc and ac:               # Scenario 6
        return {
            "landco_acquisition_cp":  "External",
            "landco_exit_cp":         "DevCo",
            "devco_acquisition_cp":   "LandCo",
            "devco_exit_cp":          "AssetCo",
            "assetco_acquisition_cp": "DevCo",
            "assetco_exit_cp":        "External",
        }

    # Fallback: no recognised combination
    return {
        "landco_acquisition_cp":  NA,
        "landco_exit_cp":         NA,
        "devco_acquisition_cp":   NA,
        "devco_exit_cp":          NA,
        "assetco_acquisition_cp": NA,
        "assetco_exit_cp":        NA,
    }


def _resolve_selection(
    out_df: pd.DataFrame,
    all_asset_names: List[str],
    raw_asset_names: List[Optional[str]],
    MasterSheet,
    OUT_SELECTED_VEHICLE: str,
    OUT_SELECTED_SCENARIO: str,
) -> dict:
    """
    Resolve selected vehicle/scenario -> asset list -> module flags.
    """
    selected_vehicle  = _read_scalar(out_df, OUT_SELECTED_VEHICLE)
    selected_scenario = _read_scalar(out_df, OUT_SELECTED_SCENARIO)

    context: Dict[str, Any] = {
        "selected_vehicle_type": selected_vehicle,
        "selected_scenario": selected_scenario,
        "selected_assets": [],
        "module_flags": {},
        "lifecycle_flags": {},
        "interparty_counterparties": {},
        "jv_groups": {},
        "all_jv_groups": {},  # unfiltered — every scenario across all vehicles
        "venture_types": {},
    }

    # --- Read JVModule class attributes ---
    jv_inclusion  = MasterSheet.Asset.JVModule.jvjda_inclusion
    jv_names      = MasterSheet.Asset.JVModule.jv_name
    venture_types = MasterSheet.Asset.JVModule.venture_type
    lc_inclusion  = MasterSheet.Asset.JVModule.landco_inclusion
    dc_inclusion  = MasterSheet.Asset.JVModule.devco_inclusion
    ac_inclusion  = MasterSheet.Asset.JVModule.assetco_inclusion

    # --- Read lifecycle flags ---
    lc_lifecycle = MasterSheet.Asset.AssetLifecycleModule.land_development
    dc_lifecycle = MasterSheet.Asset.AssetLifecycleModule.vertical_development
    ac_lifecycle = MasterSheet.Asset.AssetLifecycleModule.asset_operations

    if not isinstance(jv_inclusion, list) or len(jv_inclusion) == 0:
        return context

    scenario_lower = _safe_str_lower(selected_scenario)
    vehicle_lower = _safe_str_lower(selected_vehicle)

    for idx in range(len(jv_inclusion)):
        incl = _safe_str_lower(jv_inclusion[idx])
        if incl != "yes":
            continue

        asset_name = raw_asset_names[idx] if idx < len(raw_asset_names) else None
        if not asset_name:
            continue

        rec_jv = ""
        if isinstance(jv_names, list) and idx < len(jv_names):
            rec_jv = _safe_str_lower(jv_names[idx])

        # Always populate all_jv_groups, module_flags, lifecycle_flags and
        # interparty_counterparties regardless of scenario/vehicle filter so
        # that non-selected scenarios get real FCFF in the consolidation output.
        _all_jv_key = rec_jv or "(unnamed)"
        context["all_jv_groups"].setdefault(_all_jv_key, []).append(asset_name)

        rec_vt_all = ""
        if isinstance(venture_types, list) and idx < len(venture_types):
            rec_vt_all = _safe_str_lower(venture_types[idx])

        lc_flag_all = _safe_str_lower(lc_inclusion[idx]) == "yes" if isinstance(lc_inclusion, list) and idx < len(lc_inclusion) else False
        dc_flag_all = _safe_str_lower(dc_inclusion[idx]) == "yes" if isinstance(dc_inclusion, list) and idx < len(dc_inclusion) else False
        ac_flag_all = _safe_str_lower(ac_inclusion[idx]) == "yes" if isinstance(ac_inclusion, list) and idx < len(ac_inclusion) else False

        lc_life_all = _safe_str_lower(lc_lifecycle[idx]) == "yes" if isinstance(lc_lifecycle, list) and idx < len(lc_lifecycle) else False
        dc_life_all = _safe_str_lower(dc_lifecycle[idx]) == "yes" if isinstance(dc_lifecycle, list) and idx < len(dc_lifecycle) else False
        ac_life_all = _safe_str_lower(ac_lifecycle[idx]) == "yes" if isinstance(ac_lifecycle, list) and idx < len(ac_lifecycle) else False

        if asset_name not in context["module_flags"]:
            context["module_flags"][asset_name] = {
                "landco": lc_flag_all,
                "devco": dc_flag_all,
                "assetco": ac_flag_all,
            }
        if asset_name not in context["lifecycle_flags"]:
            context["lifecycle_flags"][asset_name] = {
                "land_development": lc_life_all,
                "vertical_development": dc_life_all,
                "asset_operations": ac_life_all,
            }
        if asset_name not in context["interparty_counterparties"]:
            context["interparty_counterparties"][asset_name] = _resolve_interparty_counterparties(
                lc_life_all, dc_life_all, ac_life_all,
            )
        if asset_name not in context["venture_types"]:
            context["venture_types"][asset_name] = rec_vt_all or "(not set)"

        if scenario_lower and rec_jv != scenario_lower:
            continue

        rec_vt = rec_vt_all

        if vehicle_lower and rec_vt != vehicle_lower:
            continue

        context["selected_assets"].append(asset_name)

        jv_key = rec_jv or "(unnamed)"
        context["jv_groups"].setdefault(jv_key, []).append(asset_name)

    return context
