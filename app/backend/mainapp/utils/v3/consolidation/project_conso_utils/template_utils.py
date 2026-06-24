"""
Template row indices, consolidated DataFrame initialisation, and interparty mapping.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def fn_build_template_row_index(
    consolidated_structure: Dict[str, Dict[str, List[str]]]
) -> List[str]:
    """
    Flatten unique line items across CFO/CFI/CFF into a stable row index.
    """
    row_index: List[str] = []
    seen_subitems = set()

    for cashflow_type in ["CFO", "CFI", "CFF"]:
        categories = consolidated_structure.get(cashflow_type, {})
        for _, subitems in categories.items():
            if not isinstance(subitems, list):
                continue
            for subitem in subitems:
                normalized_subitem = str(subitem)
                if normalized_subitem in seen_subitems:
                    continue
                seen_subitems.add(normalized_subitem)
                row_index.append(normalized_subitem)

    return row_index


def fn_initialize_consolidated_dataframe(
    template_row_index: List[str],
    monthly_timeline: List[str]
) -> pd.DataFrame:
    """
    Initialize an empty consolidated cashflow DataFrame.
    """
    unique_periods = list(dict.fromkeys(str(period) for period in monthly_timeline))
    return pd.DataFrame(
        data=0.0,
        index=template_row_index,
        columns=unique_periods,
        dtype="float64",
    )


def fn_build_financial_statement_row_index(
    statement_structure: Dict[str, Dict[str, List[str]]]
) -> List[str]:
    """
    Flatten unique line items from a financial statement structure.
    """
    row_index: List[str] = []
    seen_items = set()

    for section, categories in statement_structure.items():
        if not isinstance(categories, dict):
            continue
        for category_name, line_items in categories.items():
            if not isinstance(line_items, list):
                continue
            for item in line_items:
                normalized_item = str(item)
                if normalized_item in seen_items:
                    continue
                seen_items.add(normalized_item)
                row_index.append(normalized_item)

    return row_index


def fn_build_interparty_mapping(
    asset_ids: pd.Series,
    landco_acq_counterparty: pd.Series,
    land_development: pd.Series,
    vertical_development: pd.Series,
    asset_operations: pd.Series,
    asset_identifier_mask: pd.Series,
    lc_jv_inclusion: Optional[pd.Series] = None,
    dc_jv_inclusion: Optional[pd.Series] = None,
    ac_jv_inclusion: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Build vectorized interparty mapping for LandCo, DevCo, and AssetCo.

    JV inclusion flags suppress interparty routing to an entity that is in the JV,
    because that entity's cashflows do not appear in the consolidated output and
    there is nothing to eliminate against.

    Rules:
      LC→DC transfer (land_dev=Yes AND vert_dev=Yes):
        LandCo_Exit_Counterparty   = "DevCo"  only when LC is NOT in JV
        DevCo_Acquisition_CP       = "LandCo" only when DC is NOT in JV
      DC→AC transfer (vert_dev=Yes AND asset_ops=Yes):
        DevCo_Exit_Counterparty    = "AssetCo" only when DC is NOT in JV
        AssetCo_Acquisition_CP     = "DevCo"   only when AC is NOT in JV
    """
    _lc_in_jv = lc_jv_inclusion == "Yes" if lc_jv_inclusion is not None else pd.Series(False, index=asset_ids.index)
    _dc_in_jv = dc_jv_inclusion == "Yes" if dc_jv_inclusion is not None else pd.Series(False, index=asset_ids.index)
    _ac_in_jv = ac_jv_inclusion == "Yes" if ac_jv_inclusion is not None else pd.Series(False, index=asset_ids.index)

    cols = [
        "LandCo_Acquisition_Counterparty",
        "LandCo_Exit_Counterparty",
        "DevCo_Acquisition_Counterparty",
        "DevCo_Exit_Counterparty",
        "AssetCo_Acquisition_Counterparty",
        "AssetCo_Exit_Counterparty"
    ]
    df = pd.DataFrame(index=asset_ids, columns=cols)

    # LandCo Acquisition Counterparty (always from input)
    df["LandCo_Acquisition_Counterparty"] = np.where(
        asset_identifier_mask,
        landco_acq_counterparty,
        None
    )

    # LandCo Exit Counterparty: "DevCo" only when LC→DC transfer exists AND neither LC nor DC is in JV.
    # If DC is in JV there is nothing to eliminate against on the DevCo side, so LC exits to "External".
    _lc_to_dc = (land_development == "Yes") & (vertical_development == "Yes")
    _lc_exit_to_devco = _lc_to_dc & ~_lc_in_jv & ~_dc_in_jv
    df["LandCo_Exit_Counterparty"] = np.where(
        _lc_exit_to_devco, "DevCo",
        np.where(
            (land_development == "Yes") & (~_lc_exit_to_devco), "External", None
        )
    )

    # DevCo Acquisition Counterparty: "LandCo" only when LC→DC transfer exists AND neither side is in JV.
    _dc_acq_from_landco = _lc_to_dc & ~_lc_in_jv & ~_dc_in_jv
    df["DevCo_Acquisition_Counterparty"] = np.where(
        _dc_acq_from_landco, "LandCo",
        np.where(
            (vertical_development == "Yes") & (~_dc_acq_from_landco), "External", None
        )
    )

    # DevCo Exit Counterparty: "AssetCo" only when DC→AC transfer exists AND neither DC nor AC is in JV.
    # If AC is in JV there is nothing to eliminate against on the AssetCo side, so DC exits to "External".
    _dc_to_ac = (vertical_development == "Yes") & (asset_operations == "Yes")
    _dc_exit_to_assetco = _dc_to_ac & ~_dc_in_jv & ~_ac_in_jv
    df["DevCo_Exit_Counterparty"] = np.where(
        _dc_exit_to_assetco, "AssetCo",
        np.where(
            (vertical_development == "Yes") & (~_dc_exit_to_assetco), "External", None
        )
    )

    # AssetCo Acquisition Counterparty: "DevCo" only when DC→AC transfer exists AND neither side is in JV.
    _ac_acq_from_devco = _dc_to_ac & ~_dc_in_jv & ~_ac_in_jv
    df["AssetCo_Acquisition_Counterparty"] = np.where(
        _ac_acq_from_devco, "DevCo",
        np.where(
            (asset_operations == "Yes") & (~_ac_acq_from_devco), "External", None
        )
    )

    # AssetCo Exit Counterparty (always External for now)
    df["AssetCo_Exit_Counterparty"] = np.where(
        asset_identifier_mask,
        "External",
        None
    )

    return df
