"""
JV Consolidation - FCFF Extraction Utilities
==============================================

Functions for extracting Free Cash Flow to Firm (FCFF) and
Land In Kind values from upstream LandCo, DevCo, and AssetCo payloads.

All numeric accumulations use numpy vectorised operations.
"""

import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =====================================================================
# Numeric Helpers
# =====================================================================

def _coerce_row(raw_row: list) -> np.ndarray:
    """Convert a raw list to a float64 numpy array (non-numeric -> 0.0)."""
    result = pd.to_numeric(pd.Series(raw_row), errors="coerce").fillna(0.0)
    return result.to_numpy(dtype=np.float64)


def _add_arrays(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Element-wise add two 1-D arrays, zero-padding the shorter one."""
    if a.size == 0:
        return b.copy()
    if b.size == 0:
        return a.copy()
    width = max(a.size, b.size)
    out = np.zeros(width, dtype=np.float64)
    out[: a.size] += a
    out[: b.size] += b
    return out


# =====================================================================
# Asset Name Matching
# =====================================================================

def _normalize_asset_name(name: str) -> str:
    """Normalize an asset name for matching: lowercase, collapse separators."""
    return name.strip().lower().replace("_", " ").replace("-", " ")


def _tokenize(name: str) -> set:
    """Tokenize a normalized asset name into a set of words."""
    return set(_normalize_asset_name(name).split())


# =====================================================================
# Asset Index Resolution
# =====================================================================

def _find_asset_index(model_data: dict, asset_name: str) -> Optional[int]:
    """
    Find the row index of *asset_name* in a LandCo/DevCo payload.

    Handles both dict-of-lists and split-payload formats:
      a) {"asset_name": ["A", "B", "C"]}       -> dict-of-lists
      b) {"index": [...], "columns": [..., "asset_name", ...], "data": [[...]]}  -> split payload
    """
    if not model_data:
        return None
    assumptions = model_data.get("asset_assumptions", {})
    if not isinstance(assumptions, dict):
        return None
    project_details = assumptions.get("ProjectDetails", {})
    if not isinstance(project_details, dict):
        return None

    target = asset_name.strip().lower()

    # --- Format A: dict-of-lists ---
    names = project_details.get("asset_name")
    if names is not None:
        if isinstance(names, dict):
            sorted_items = sorted(
                names.items(),
                key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0,
            )
            name_list = [str(v) for _, v in sorted_items]
        elif isinstance(names, (list, tuple)):
            name_list = [str(n) for n in names]
        else:
            name_list = None

        if name_list:
            for idx, n in enumerate(name_list):
                if n.strip().lower() == target:
                    return idx
            return None

    # --- Format B: split payload {index, columns, data} ---
    columns = project_details.get("columns")
    data = project_details.get("data")
    if isinstance(columns, list) and isinstance(data, list):
        col_idx = None
        for ci, col_name in enumerate(columns):
            if str(col_name).strip().lower() == "asset_name":
                col_idx = ci
                break
        if col_idx is not None:
            for row_idx, row in enumerate(data):
                if isinstance(row, list) and col_idx < len(row):
                    if str(row[col_idx]).strip().lower() == target:
                        return row_idx

    return None


def _find_assetco_entry(
    assetco_per_asset: List[dict], asset_name: str,
) -> Optional[dict]:
    """Find an AssetCo per-asset entry using multi-pass matching.

    Pass 1: Exact match (case-insensitive)
    Pass 2: Prefix/contains match after normalizing separators
    Pass 3: Token overlap - all tokens of the shorter name must appear
            in the longer name
    """
    target = _normalize_asset_name(asset_name)
    target_tokens = _tokenize(asset_name)

    if not target or not target_tokens:
        return None

    # Pass 1: exact normalized match
    for entry in assetco_per_asset:
        name = _normalize_asset_name(str(entry.get("asset_name") or ""))
        if name == target:
            return entry

    # Pass 2: prefix / contains
    for entry in assetco_per_asset:
        name = _normalize_asset_name(str(entry.get("asset_name") or ""))
        if not name:
            continue
        if name.startswith(target) or target.startswith(name):
            return entry

    # Pass 3: token-based subset matching
    best_match = None
    best_overlap = 0
    for entry in assetco_per_asset:
        name_tokens = _tokenize(str(entry.get("asset_name") or ""))
        if not name_tokens:
            continue
        if target_tokens.issubset(name_tokens):
            overlap = len(target_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = entry

    return best_match


# =====================================================================
# LandCo / DevCo Section Summation  (vectorised)
# =====================================================================

# Sections to consume for FCFF
_FCFF_SECTIONS = ("Cashflow from Operations", "Cashflow from Investments")

# Terminal value items to exclude from project cost base (LandCo CFI)
_LANDCO_CFI_TERMINAL_VALUE_ITEMS = {
    "land lease - terminal value", "land bank - exit value",
}

# =====================================================================
# Interparty Add-Back Item Labels
# =====================================================================

# LandCo Support Workings: add back when LC→DC transfer exists and LC is in JV but DC is not
_LC_SW_ADDBACK = {"serviced land sales"}

# DevCo Support Workings (split): acquisition vs sales add-backs fire independently
_DC_SW_ACQ_ADDBACK   = {"serviced land acquisition"}  # add back when LC→DC exists, LC not in JV, DC in JV
_DC_SW_SALES_ADDBACK = {"asset sales"}                # add back when DC→AC exists, DC in JV, AC not in JV

# AssetCo CFI: add back when DC→AC transfer exists and AC is in JV but DC is not
_AC_CFI_ADDBACK = {"acquisition price", "acquisition costs", "asset acquisition cost"}


def _extract_named_items_from_section(
    model_data: dict, section: str, asset_idx: int,
    item_names: set,
) -> np.ndarray:
    """
    Extract and sum specific named line items from a LandCo/DevCo section
    (dict-of-dicts format) for one asset row.

    *item_names* is a set of lowercase label strings to match.
    Returns a 1-D float64 ndarray (empty if nothing matched).
    """
    section_data = model_data.get(section, {})
    if not isinstance(section_data, dict):
        return np.empty(0, dtype=np.float64)

    rows: List[np.ndarray] = []
    max_width = 0

    for item_name, item_json in section_data.items():
        if item_name.strip().lower() not in item_names:
            continue
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if asset_idx >= len(data_rows):
            continue
        arr = _coerce_row(data_rows[asset_idx])
        if arr.size > 0:
            rows.append(arr)
            if arr.size > max_width:
                max_width = arr.size

    if not rows:
        return np.empty(0, dtype=np.float64)

    mat = np.zeros((len(rows), max_width), dtype=np.float64)
    for i, r in enumerate(rows):
        mat[i, : r.size] = r
    return mat.sum(axis=0)


def _extract_named_items_from_assetco_section(
    assetco_df_json: dict,
    item_names: set,
) -> np.ndarray:
    """
    Extract and sum specific named line items from an AssetCo split-payload
    section ({index, columns, data} format).

    *item_names* is a set of lowercase label strings to match.
    Returns a 1-D float64 ndarray (empty if nothing matched).
    """
    if not assetco_df_json or not isinstance(assetco_df_json, dict):
        return np.empty(0, dtype=np.float64)

    index = assetco_df_json.get("index", [])
    data  = assetco_df_json.get("data", [])

    rows: List[np.ndarray] = []
    max_width = 0

    for ri, item_name in enumerate(index):
        if ri >= len(data):
            continue
        if str(item_name).strip().lower() not in item_names:
            continue
        arr = _coerce_row(data[ri])
        if arr.size > 0:
            rows.append(arr)
            if arr.size > max_width:
                max_width = arr.size

    if not rows:
        return np.empty(0, dtype=np.float64)

    mat = np.zeros((len(rows), max_width), dtype=np.float64)
    for i, r in enumerate(rows):
        mat[i, : r.size] = r
    return mat.sum(axis=0)


def _sum_section_for_asset_in_model(
    model_data: dict, section: str, asset_idx: int,
    exclude_items: set = None,
) -> np.ndarray:
    """
    Sum ALL line items in a CFS section for one asset row from a
    LandCo/DevCo jvoutput payload.

    Returns a 1-D float64 ndarray (empty array when nothing found).
    All row coercion and accumulation is vectorised via numpy.
    """
    section_data = model_data.get(section, {})
    if not isinstance(section_data, dict):
        return np.empty(0, dtype=np.float64)

    # Collect valid rows into a list, then stack + sum in one operation
    rows: List[np.ndarray] = []
    max_width = 0

    for item_name, item_json in section_data.items():
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        if exclude_items and item_name.strip().lower() in exclude_items:
            continue
        data_rows = item_json["data"]
        if asset_idx >= len(data_rows):
            continue
        arr = _coerce_row(data_rows[asset_idx])
        if arr.size > 0:
            rows.append(arr)
            if arr.size > max_width:
                max_width = arr.size

    if not rows:
        return np.empty(0, dtype=np.float64)

    # Pad all rows to uniform width, stack into 2-D, and column-sum
    mat = np.zeros((len(rows), max_width), dtype=np.float64)
    for i, r in enumerate(rows):
        mat[i, : r.size] = r

    return mat.sum(axis=0)


# =====================================================================
# AssetCo Section Extraction  (vectorised)
# =====================================================================

_ASSETCO_NET_ROW_NAMES = {
    "Cashflow from Operations": (
        "total net cashflow from operations",
        "net cashflow from operations",
    ),
    "Cashflow from Investments": (
        "net cashflow from investments",
    ),
    "Cashflow from Financing": (
        "net cashflow from financing",
    ),
}

_ASSETCO_CFI_EXCLUDE = {
    "acquisition price",
    "asset acquisition cost",
}


def _sum_section_for_assetco(
    assetco_df_json: dict,
    section_name: str = "",
    exclude_items: Optional[set] = None,
) -> np.ndarray:
    """
    Extract the **Net** total row from an AssetCo CFS section.

    Returns a 1-D float64 ndarray (empty when nothing found).
    Exclusion subtraction is vectorised.
    """
    if not assetco_df_json or not isinstance(assetco_df_json, dict):
        return np.empty(0, dtype=np.float64)

    index = assetco_df_json.get("index", [])
    data  = assetco_df_json.get("data", [])

    # Find the Net total row by name
    net_candidates = _ASSETCO_NET_ROW_NAMES.get(section_name, ())
    net_arr: Optional[np.ndarray] = None

    for ri, item_name in enumerate(index):
        if ri >= len(data):
            continue
        name_lower = str(item_name).strip().lower()
        if name_lower in net_candidates:
            net_arr = _coerce_row(data[ri])
            if name_lower == net_candidates[0]:
                break  # first candidate is highest priority

    # Fallback: last non-blank row
    if net_arr is None:
        for ri in range(len(index) - 1, -1, -1):
            name = str(index[ri]).strip()
            if name and ri < len(data):
                net_arr = _coerce_row(data[ri])
                break

    if net_arr is None or net_arr.size == 0:
        return np.empty(0, dtype=np.float64)

    # Subtract excluded items (vectorised)
    if exclude_items:
        for ri, item_name in enumerate(index):
            if ri >= len(data):
                continue
            if str(item_name).strip().lower() in exclude_items:
                excl_arr = _coerce_row(data[ri])
                if np.abs(excl_arr.sum()) > 0.01:
                    # Align widths then subtract
                    if excl_arr.size < net_arr.size:
                        padded = np.zeros_like(net_arr)
                        padded[: excl_arr.size] = excl_arr
                        excl_arr = padded
                    net_arr = net_arr - excl_arr[: net_arr.size]

    return net_arr


# =====================================================================
# Land In Kind Extraction  (vectorised)
# =====================================================================

_LAND_IN_KIND_CANDIDATES = {
    c.strip().lower() for c in (
        "Land in Kind", "Land In Kind", "Land in Kind Contribution",
        "Land Equity", "Land Acquisition Cost In Kind",
    )
}

# Per-module acquisition source candidates
_LANDCO_SW_LAND_CASH_CANDIDATES = {"land acquisition cost cash payment"}
_DEVCO_CFI_LAND_COST_CANDIDATES  = {"land acquisition cost payment"}
_ASSETCO_CFI_ACQ_CANDIDATES      = {"total asset acquisition cost", "asset acquisition cost"}


def _extract_land_in_kind_from_section(
    section_data: dict, asset_idx: int,
) -> Optional[np.ndarray]:
    """
    Search a single CFS section dict for a Land in Kind item at *asset_idx*.
    Returns a 1-D float64 ndarray or None if not found.
    """
    if not isinstance(section_data, dict):
        return None

    summed: Optional[np.ndarray] = None

    for item_name, item_json in section_data.items():
        if item_name.strip().lower() not in _LAND_IN_KIND_CANDIDATES:
            continue
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if not data_rows or asset_idx >= len(data_rows):
            continue

        arr = _coerce_row(data_rows[asset_idx])
        summed = arr if summed is None else _add_arrays(summed, arr)

    return summed


def _extract_land_in_kind_from_model(
    model_data: dict, asset_idx: int,
) -> np.ndarray:
    """
    Extract the "Land in Kind" row for a specific asset.

    Search order (first match wins):
      1. Support Workings -> always has per-asset rows
      2. Cashflow from Financing -> fallback
    """
    # 1. Try Support Workings first
    sw_section = model_data.get("Support Workings") or model_data.get("support workings")
    if isinstance(sw_section, dict):
        result = _extract_land_in_kind_from_section(sw_section, asset_idx)
        if result is not None:
            return result

    # 2. Fallback to Cashflow from Financing
    cff_section = model_data.get("Cashflow from Financing", {})
    if isinstance(cff_section, dict):
        result = _extract_land_in_kind_from_section(cff_section, asset_idx)
        if result is not None:
            return result

    return np.empty(0, dtype=np.float64)


def _extract_land_cost_from_landco(
    model_data: dict, asset_idx: int, asset_name: str = "",
) -> tuple:
    """
    Extract the land value for a LandCo-in-JV asset.

    Search order:
      1. CFI "Land Acquisition Cost Payment" — cash land purchase, inside FCFF.
         Returns (array, True): add-back required when LIK=Yes.
      2. SW "Land Acquisition Cost Cash Payment" — cash payment fallback.
         Returns (array, True): add-back required when LIK=Yes.

    SW "Land Acquisition Cost In Kind" is deliberately excluded — in-kind land
    contributions must not be counted as a JV land acquisition cost.
    """
    cfi_row = _extract_named_items_from_section(
        model_data, "Cashflow from Investments", asset_idx, _DEVCO_CFI_LAND_COST_CANDIDATES,
    )
    if cfi_row.size > 0 and np.any(cfi_row != 0):
        return cfi_row, True

    sw_cash_row = _extract_named_items_from_section(
        model_data, "Support Workings", asset_idx, _LANDCO_SW_LAND_CASH_CANDIDATES,
    )
    if sw_cash_row.size > 0 and np.any(sw_cash_row != 0):
        return sw_cash_row, True

    return np.empty(0, dtype=np.float64), False


_DEVCO_SW_LAND_COST_CANDIDATES = {"land acquisition cost"}


def _extract_land_cost_from_devco(
    model_data: dict, asset_idx: int,
) -> np.ndarray:
    """
    Extract the land acquisition value for a DevCo-in-JV (no LandCo) asset.

    Search order:
      1. CFI "Land Acquisition Cost Payment"
      2. Support Workings "Land Acquisition Cost" (fallback when CFI is zero/absent)
    """
    cfi_row = _extract_named_items_from_section(
        model_data, "Cashflow from Investments", asset_idx, _DEVCO_CFI_LAND_COST_CANDIDATES,
    )
    if cfi_row.size > 0 and np.any(cfi_row != 0):
        return cfi_row
    return _extract_named_items_from_section(
        model_data, "Support Workings", asset_idx, _DEVCO_SW_LAND_COST_CANDIDATES,
    )


def _extract_land_cost_from_assetco(
    ac_entry: dict,
) -> np.ndarray:
    """
    Extract the acquisition value for an AssetCo-only-in-JV asset.

    Sources: AssetCo CFI "Total Asset Acquisition Cost" / "Asset Acquisition Cost".
    """
    return _extract_named_items_from_assetco_section(
        ac_entry.get("Cashflow from Investments"), _ASSETCO_CFI_ACQ_CANDIDATES,
    )


# =====================================================================
# Per-Asset FCFF Extraction  (vectorised)
# =====================================================================

def _extract_asset_fcff(
    asset_name: str,
    landco_data: dict,
    devco_data: dict,
    assetco_per_asset: List[dict],
    module_flags: dict,
    lifecycle_flags: Optional[dict] = None,
) -> Dict[str, np.ndarray]:
    """
    Compute FCFF for each participating module for one asset.

    For LandCo/DevCo: sums all CFO items + all CFI items at the given
    asset row index (vectorised per section, then added).

    For AssetCo: extracts net CFO + net CFI from the per-asset entry.

    Interparty add-backs
    --------------------
    Upstream payloads have already eliminated interparty line items for
    LC->DC and DC->AC transfers.  This function selectively reinstates
    those items based on which entities are included in the JV.

    Two interparty transfer chains are possible:
      LC->DC: exists when land_development=Yes AND vertical_development=Yes
      DC->AC: exists when vertical_development=Yes AND asset_operations=Yes

    Add-back rules (one per eliminated item, each independently gated):
      LandCo SW "Serviced Land Sales"
          -> add back when LC->DC transfer exists AND LC is in JV AND DC is not
      DevCo SW "Serviced Land Acquisition"
          -> add back when LC->DC transfer exists AND DC is in JV AND LC is not
      DevCo SW "Asset Sales"
          -> add back when DC->AC transfer exists AND DC is in JV AND AC is not
      AssetCo CFI "Acquisition Price" / "Acquisition Costs"
          -> add back when DC->AC transfer exists AND AC is in JV AND DC is not

    *lifecycle_flags* is a dict with keys ``"land_development"``,
    ``"vertical_development"``, ``"asset_operations"`` (bool values).

    Returns ``{key: ndarray}`` where key is one of
    ``"LandCo_FCFF"``, ``"DevCo_FCFF"``, ``"AssetCo_FCFF"``,
    ``"Land_In_Kind"``, ``"LandCo_CFI"``, ``"DevCo_CFI"``.
    """
    flags = module_flags.get(asset_name, {})
    lf    = lifecycle_flags or {}

    lc_flag = flags.get("landco", False)
    dc_flag = flags.get("devco", False)
    ac_flag = flags.get("assetco", False)

    lc_inc = bool(lc_flag)
    dc_inc = bool(dc_flag)
    ac_inc = bool(ac_flag)

    lc_idx   = _find_asset_index(landco_data, asset_name) if lc_flag else None
    dc_idx   = _find_asset_index(devco_data, asset_name)  if dc_flag else None
    ac_entry = _find_assetco_entry(assetco_per_asset, asset_name) if ac_flag else None

    has_lc = lc_idx is not None and bool(landco_data)
    has_dc = dc_idx is not None and bool(devco_data)
    has_ac = ac_entry is not None

    # ------------------------------------------------------------------
    # Interparty transfer chains from lifecycle flags
    # ------------------------------------------------------------------
    lc_to_dc = bool(lf.get("land_development", False)) and bool(lf.get("vertical_development", False))
    dc_to_ac = bool(lf.get("vertical_development", False)) and bool(lf.get("asset_operations", False))

    # Add-back fires when one side of a transfer is in the JV but not the other
    addback_lc_sales = has_lc and lc_to_dc and not dc_inc
    addback_dc_acq   = has_dc and lc_to_dc and not lc_inc
    addback_dc_sales = has_dc and dc_to_ac and not ac_inc
    addback_ac_acq   = has_ac and dc_to_ac and not dc_inc

    result: Dict[str, np.ndarray] = {}

    # --- LandCo FCFF = sum(CFO) + sum(CFI) [+ SW add-back if applicable] ---
    if has_lc:
        lc_fcff = np.empty(0, dtype=np.float64)
        for section in _FCFF_SECTIONS:
            row = _sum_section_for_asset_in_model(landco_data, section, lc_idx)
            lc_fcff = _add_arrays(lc_fcff, row)

        if addback_lc_sales:
            sw_row = _extract_named_items_from_section(
                landco_data, "Support Workings", lc_idx, _LC_SW_ADDBACK,
            )
            lc_fcff = _add_arrays(lc_fcff, sw_row)

        result["LandCo_FCFF"] = lc_fcff

        # LandCo CFI excluding terminal value items (for project cost base)
        lc_cfi = _sum_section_for_asset_in_model(
            landco_data, "Cashflow from Investments", lc_idx,
            exclude_items=_LANDCO_CFI_TERMINAL_VALUE_ITEMS,
        )
        if lc_cfi.size > 0:
            result["LandCo_CFI"] = lc_cfi

    # --- DevCo FCFF = sum(CFO) + sum(CFI) [+ SW add-back if applicable] ---
    if has_dc:
        dc_fcff = np.empty(0, dtype=np.float64)
        for section in _FCFF_SECTIONS:
            row = _sum_section_for_asset_in_model(devco_data, section, dc_idx)
            dc_fcff = _add_arrays(dc_fcff, row)

        if addback_dc_acq:
            sw_row = _extract_named_items_from_section(
                devco_data, "Support Workings", dc_idx, _DC_SW_ACQ_ADDBACK,
            )
            dc_fcff = _add_arrays(dc_fcff, sw_row)
        if addback_dc_sales:
            sw_row = _extract_named_items_from_section(
                devco_data, "Support Workings", dc_idx, _DC_SW_SALES_ADDBACK,
            )
            dc_fcff = _add_arrays(dc_fcff, sw_row)

        result["DevCo_FCFF"] = dc_fcff

        # DevCo CFI (for project cost base)
        dc_cfi = _sum_section_for_asset_in_model(
            devco_data, "Cashflow from Investments", dc_idx,
        )
        if dc_cfi.size > 0:
            result["DevCo_CFI"] = dc_cfi

    # --- AssetCo FCFF = net(CFO) + net(CFI) [+ CFI add-back if applicable] ---
    if has_ac:
        ac_fcff = np.empty(0, dtype=np.float64)
        for section in _FCFF_SECTIONS:
            # Always exclude acquisition items from the net row extraction;
            # we add them back selectively below based on counterparty routing.
            excl = _ASSETCO_CFI_EXCLUDE if section == "Cashflow from Investments" else None
            row = _sum_section_for_assetco(ac_entry.get(section), section, exclude_items=excl)
            ac_fcff = _add_arrays(ac_fcff, row)

        if addback_ac_acq:
            cfi_addback = _extract_named_items_from_assetco_section(
                ac_entry.get("Cashflow from Investments"), _AC_CFI_ADDBACK,
            )
            ac_fcff = _add_arrays(ac_fcff, cfi_addback)

        result["AssetCo_FCFF"] = ac_fcff

    # --- Land / acquisition value: source depends on JV entry module ---
    # _lik_from_cfi=True  → value is inside entity FCFF; add-back required when LIK=Yes
    # _lik_from_cfi=False → value from LandCo CFF "Land in Kind"; not in FCFF, no add-back
    if has_lc:
        lik, lik_from_cfi = _extract_land_cost_from_landco(landco_data, lc_idx, asset_name=asset_name)
    elif has_dc:
        lik = _extract_land_cost_from_devco(devco_data, dc_idx)
        lik_from_cfi = True
    elif has_ac:
        lik = _extract_land_cost_from_assetco(ac_entry)
        lik_from_cfi = True
    else:
        lik = np.empty(0, dtype=np.float64)
        lik_from_cfi = False
    if lik.size > 0:
        result["Land_In_Kind"] = lik
    # Always store _lik_from_cfi so the Phase 7 add-back gate works correctly
    # even in edge cases where lik is empty but the source is known to be CFI.
    result["_lik_from_cfi"] = lik_from_cfi

    return result


# =====================================================================
# FCFF Accumulation  (vectorised)
# =====================================================================

def _accumulate_fcff_rows(
    accumulated: Dict[str, np.ndarray],
    new_rows: Dict[str, np.ndarray],
):
    """
    Merge *new_rows* into *accumulated* in-place, element-wise addition.
    Keys are like "LandCo_FCFF", "DevCo_FCFF", "AssetCo_FCFF", "Land_In_Kind".
    """
    for key, vals in new_rows.items():
        if key not in accumulated:
            accumulated[key] = vals.copy()
        else:
            accumulated[key] = _add_arrays(accumulated[key], vals)


# =====================================================================
# JV Date Window Utilities
# =====================================================================

def _to_float_safe(v) -> float:
    """Coerce a single value to float; non-numeric -> 0.0."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _date_to_month_index(
    date_val, model_start: Optional[pd.Timestamp],
) -> Optional[int]:
    """Convert a date value to a 0-based month index relative to *model_start*."""
    if date_val is None or model_start is None:
        return None
    try:
        # Excel serial numbers (int/float) must be converted via the Excel epoch
        # before passing to pd.Timestamp, which would otherwise interpret them as
        # nanoseconds since the Unix epoch and produce a wildly wrong date.
        if isinstance(date_val, (int, float)) and not isinstance(date_val, bool):
            ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(date_val))
        else:
            ts = pd.Timestamp(date_val)
        if pd.isna(ts):
            return None
        return (ts.year - model_start.year) * 12 + (ts.month - model_start.month)
    except Exception:
        return None


def _apply_jv_window(row: np.ndarray, start_idx, end_idx, n: int) -> np.ndarray:
    """Zero out values outside [start_idx, end_idx). Returns a new array of length *n*."""
    masked = np.zeros(n, dtype=np.float64)
    s = start_idx if start_idx is not None else 0
    e = end_idx if end_idx is not None else n
    src = row[:n] if len(row) >= n else np.pad(row, (0, n - len(row)))
    lo = max(s, 0)
    hi = min(e, n)
    if lo < hi:
        masked[lo:hi] = src[lo:hi]
    return masked


# =====================================================================
# Asset Sales Value Extraction  (per-asset, vectorised)
# =====================================================================

# Candidate item names for sales rows (case-insensitive matching)
_ASSETCO_SALES_CANDIDATES = {
    "asset sale value", "asset sales value", "net asset sale value",
}
_DEVCO_SALES_CANDIDATES = {
    "cash received from asset sales",
    "asset sales through escrow",
    "asset sales through collection (post-dev)",
}
_LANDCO_SALES_CANDIDATES_CFO = {
    "land sales",
}
_LANDCO_SALES_CANDIDATES_CFI = {
    "land lease - terminal value", "land bank - exit value",
}


def _extract_matching_rows_from_section(
    section_data: dict,
    asset_idx: int,
    candidates: set,
) -> np.ndarray:
    """Sum rows whose name matches *candidates* for a given asset index."""
    if not isinstance(section_data, dict):
        return np.empty(0, dtype=np.float64)

    acc = np.empty(0, dtype=np.float64)
    for item_name, item_json in section_data.items():
        if item_name.strip().lower() not in candidates:
            continue
        if not isinstance(item_json, dict) or "data" not in item_json:
            continue
        data_rows = item_json["data"]
        if not data_rows or asset_idx >= len(data_rows):
            continue
        arr = _coerce_row(data_rows[asset_idx])
        acc = _add_arrays(acc, arr) if acc.size else arr
    return acc


def _extract_matching_rows_from_assetco(
    assetco_entry: dict,
    section_name: str,
    candidates: set,
) -> np.ndarray:
    """Sum rows from an AssetCo per-asset split payload matching *candidates*."""
    section = assetco_entry.get(section_name)
    if not isinstance(section, dict):
        return np.empty(0, dtype=np.float64)

    index = section.get("index", [])
    data = section.get("data", [])

    acc = np.empty(0, dtype=np.float64)
    for ri, item_name in enumerate(index):
        if ri >= len(data):
            continue
        if str(item_name).strip().lower() not in candidates:
            continue
        arr = _coerce_row(data[ri])
        acc = _add_arrays(acc, arr) if acc.size else arr
    return acc


def _extract_asset_sales(
    asset_name: str,
    landco_data: dict,
    devco_data: dict,
    assetco_per_asset: list,
    module_flags: dict,
    lifecycle_flags: Optional[dict] = None,
) -> np.ndarray:
    """
    Extract the asset sales value used as the JV liquidation fee base.

    The fee is charged on the exit transaction of the last entity in the chain
    that sells to the external market, so only one entity's sales are returned
    (priority: AssetCo > DevCo > LandCo).

    When interparty add-backs apply (one side of a transfer is outside the JV),
    the Support Workings add-back item is included in the fee base because it
    represents the actual exit sale value for that scenario:
      LandCo SW "Serviced Land Sales"  -- when LC->DC transfer exists, LC in JV, DC not
      DevCo SW "Asset Sales"           -- when DC->AC transfer exists, DC in JV, AC not
    """
    flags = module_flags.get(asset_name, {})
    lf    = lifecycle_flags or {}

    lc_inc = bool(flags.get("landco", False))
    dc_inc = bool(flags.get("devco", False))
    ac_inc = bool(flags.get("assetco", False))

    lc_to_dc = bool(lf.get("land_development", False)) and bool(lf.get("vertical_development", False))
    dc_to_ac = bool(lf.get("vertical_development", False)) and bool(lf.get("asset_operations", False))

    addback_lc_sales = lc_inc and lc_to_dc and not dc_inc
    addback_dc_sales = dc_inc and dc_to_ac and not ac_inc

    acc = np.empty(0, dtype=np.float64)

    # AssetCo: last in chain, exits directly to external market
    if ac_inc:
        ac_entry = _find_assetco_entry(assetco_per_asset, asset_name)
        if ac_entry is not None:
            row = _extract_matching_rows_from_assetco(
                ac_entry, "Cashflow from Investments", _ASSETCO_SALES_CANDIDATES,
            )
            acc = _add_arrays(acc, row) if acc.size else row

    # DevCo: exit entity when AC is not in JV
    elif dc_inc:
        dc_idx = _find_asset_index(devco_data, asset_name)
        if dc_idx is not None:
            cfo = devco_data.get("Cashflow from Operations", {})
            row = _extract_matching_rows_from_section(cfo, dc_idx, _DEVCO_SALES_CANDIDATES)
            acc = _add_arrays(acc, row) if acc.size else row
            if addback_dc_sales:
                sw_row = _extract_named_items_from_section(
                    devco_data, "Support Workings", dc_idx, _DC_SW_SALES_ADDBACK,
                )
                acc = _add_arrays(acc, sw_row)

    # LandCo: exit entity when neither DC nor AC is in JV
    elif lc_inc:
        lc_idx = _find_asset_index(landco_data, asset_name)
        if lc_idx is not None:
            cfo = landco_data.get("Cashflow from Operations", {})
            row = _extract_matching_rows_from_section(cfo, lc_idx, _LANDCO_SALES_CANDIDATES_CFO)
            acc = _add_arrays(acc, row) if acc.size else row
            cfi = landco_data.get("Cashflow from Investments", {})
            row = _extract_matching_rows_from_section(cfi, lc_idx, _LANDCO_SALES_CANDIDATES_CFI)
            acc = _add_arrays(acc, row)
            if addback_lc_sales:
                sw_row = _extract_named_items_from_section(
                    landco_data, "Support Workings", lc_idx, _LC_SW_ADDBACK,
                )
                acc = _add_arrays(acc, sw_row)

    return acc


def _extract_asset_acquisition(
    asset_name: str,
    landco_data: dict,
    devco_data: dict,
    assetco_per_asset: list,
    module_flags: dict,
    lifecycle_flags: Optional[dict] = None,
) -> np.ndarray:
    """
    Extract the acquisition cost base for the JV setup fee when LandCo is not in the JV.

    When LandCo is included, the existing land_cost / land_in_kind path in
    jv_consolidation.py handles the setup fee base; this function returns empty.

    Priority (first entity in chain that is in the JV acquires from outside):
      DevCo (no LandCo): "Serviced Land Acquisition" from DevCo Support Workings
      AssetCo (no DevCo, no LandCo): "Acquisition Price"/"Acquisition Costs" from AssetCo CFI
    """
    flags = module_flags.get(asset_name, {})
    lf    = lifecycle_flags or {}

    lc_inc = bool(flags.get("landco", False))
    dc_inc = bool(flags.get("devco", False))
    ac_inc = bool(flags.get("assetco", False))

    if lc_inc:
        return np.empty(0, dtype=np.float64)  # existing land_cost path handles this

    if dc_inc:
        dc_idx = _find_asset_index(devco_data, asset_name) if bool(devco_data) else None
        if dc_idx is None:
            return np.empty(0, dtype=np.float64)
        return _extract_named_items_from_section(
            devco_data, "Support Workings", dc_idx, _DC_SW_ACQ_ADDBACK,
        )

    if ac_inc:
        ac_entry = _find_assetco_entry(assetco_per_asset, asset_name)
        if ac_entry is None:
            return np.empty(0, dtype=np.float64)
        return _extract_named_items_from_assetco_section(
            ac_entry.get("Cashflow from Investments"), _AC_CFI_ADDBACK,
        )

    return np.empty(0, dtype=np.float64)
