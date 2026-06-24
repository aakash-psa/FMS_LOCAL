import copy
import os
import pickle
import tempfile
import traceback
from typing import Dict, List, Optional, Tuple


def serialize_sensitivity_payload(payload: Tuple) -> str:
    """Pickle payload to a temp file and return the path."""
    fd, path = tempfile.mkstemp(prefix="sens_", suffix=".pkl")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        raise
    return path


def extract_sensitivity_params(
    payload: List[Dict],
    named_range_name: str,
) -> Tuple[Optional[Tuple], Optional[Tuple]]:
    """
    Reads the named sensitivity range and returns:
        (label1, pct1), (label2, pct2)
    Returns (None, None) when the range is missing or malformed.
    """
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("name") != named_range_name:
            continue
        values = item.get("values", [])
        if (
            len(values) >= 2
            and len(values[0]) >= 2
            and len(values[1]) >= 2
        ):
            return (
                (str(values[0][0]), float(values[0][1])),
                (str(values[1][0]), float(values[1][1])),
            )
    return None, None


def build_index_maps(
    payload: List[Dict],
    prefix: str,
) -> Tuple[Dict[str, int], Dict[Tuple[str, str], int]]:
    """
    Builds two lookup maps for a given module prefix
    (e.g. "a.landco" or "a.devco").

    global_attr_idx : {attr_name: row_index}
        Maps a flat attribute name from <prefix>.global.attribute to its
        row index in <prefix>.global.value.

    asset_col_idx : {(class_name, attr_name): col_index}
        Maps a (class, attribute) pair to its column index in <prefix>.asset.data.
        Resolution mirrors fn_assign_asset_class_attributes: a column is
        identified by the intersection of <prefix>.class.row and
        <prefix>.attribute.row.
    """
    global_attr_idx: Dict[str, int] = {}
    asset_col_idx: Dict[Tuple[str, str], int] = {}

    class_row: List = []
    attr_row: List = []

    for item in payload:
        name = item.get("name")
        if name == f"{prefix}.global.attribute":
            for i, row in enumerate(item.get("values", [])):
                if row and row[0]:
                    global_attr_idx[str(row[0])] = i
        elif name == f"{prefix}.class.row":
            class_row = item.get("values", [[]])[0]
        elif name == f"{prefix}.attribute.row":
            attr_row = item.get("values", [[]])[0]

    if class_row and attr_row:
        for j, (cls, attr) in enumerate(zip(class_row, attr_row)):
            if cls and attr:
                asset_col_idx[(str(cls), str(attr))] = j

    return global_attr_idx, asset_col_idx


def apply_multipliers(
    payload: List[Dict],
    label1: str,
    mult1: float,
    label2: str,
    mult2: float,
    global_attr_idx: Dict[str, int],
    asset_col_idx: Dict[Tuple[str, str], int],
    label_global_map: Dict[str, List[str]],
    label_asset_map: Dict[str, List[Tuple[str, str]]],
    global_value_key: str,
    asset_data_key: str,
) -> List[Dict]:
    """
    Deep-copies the payload and applies the two sensitivity multipliers.

    Global values (<global_value_key>):
        Scales numeric values at the rows identified by label_global_map.

    Asset values (<asset_data_key>):
        Scales numeric cell values at the columns identified by label_asset_map,
        using (class_name, attr_name) lookups built from build_index_maps.

    Zero values are left as zero (multiplying zero has no effect regardless).
    """
    payload_copy = copy.deepcopy(payload)

    for item in payload_copy:
        name = item.get("name")

        if name == global_value_key:
            for label, mult in ((label1, mult1), (label2, mult2)):
                for attr in label_global_map.get(label, []):
                    idx = global_attr_idx.get(attr)
                    if idx is None or idx >= len(item["values"]):
                        continue
                    row = item["values"][idx]
                    if row and isinstance(row[0], (int, float)):
                        row[0] = row[0] * mult

        elif name == asset_data_key:
            for label, mult in ((label1, mult1), (label2, mult2)):
                for class_attr in label_asset_map.get(label, []):
                    col_idx = asset_col_idx.get(class_attr)
                    if col_idx is None:
                        continue
                    for row in item["values"]:
                        if len(row) > col_idx and isinstance(row[col_idx], (int, float)):
                            row[col_idx] = row[col_idx] * mult

    return payload_copy


def extract_rows_from_json_df(json_df: Dict, row_names: frozenset) -> Dict:
    """Return a JSON-df dict containing only rows whose names are in row_names."""
    index = json_df.get("index", [])
    data = json_df.get("data", [])
    columns = json_df.get("columns", [])
    pairs = [(i, name) for i, name in enumerate(index) if name in row_names]
    return {
        "index": [name for _, name in pairs],
        "columns": columns,
        "data": [data[i] for i, _ in pairs],
    }


def export_sensitivity_to_excel(
    sensitivity_results: List[Dict],
    output_path: str,
) -> None:
    """
    Exports all sensitivity scenario results to an Excel workbook.

    Sheet layout:
      "Index"       — mapping of sheet name (S01–S25) to full scenario label
      "S01"–"S25"  — per-scenario sheets, each containing:
                       • scenario label at the top
                       • one section per monthly_dfs entry with row labels
                       columns = monthly time periods
    """
    try:
        import pandas as pd

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

            index_rows = [
                {"Sheet": f"S{k:02d}", "Scenario": item["scenario"]}
                for k, item in enumerate(sensitivity_results, 1)
            ]
            pd.DataFrame(index_rows).to_excel(
                writer, sheet_name="Index", index=False
            )

            for k, item in enumerate(sensitivity_results, 1):
                sheet_name = f"S{k:02d}"
                scenario_label = item["scenario"]
                result = item["result"]

                if result is None:
                    pd.DataFrame([[f"{scenario_label} — no result"]]).to_excel(
                        writer, sheet_name=sheet_name, index=False, header=False
                    )
                    continue

                monthly_dfs = result.get("exceloutput", {}).get("monthly_dfs", {})
                row_offset = 0

                pd.DataFrame([[scenario_label]]).to_excel(
                    writer, sheet_name=sheet_name,
                    startrow=row_offset, index=False, header=False,
                )
                row_offset += 2

                for section_name, entry in monthly_dfs.items():
                    _, json_df = entry
                    df = pd.DataFrame(
                        json_df.get("data", []),
                        index=json_df.get("index", []),
                        columns=json_df.get("columns", []),
                    )

                    pd.DataFrame([[section_name]]).to_excel(
                        writer, sheet_name=sheet_name,
                        startrow=row_offset, index=False, header=False,
                    )
                    row_offset += 1

                    df.to_excel(
                        writer, sheet_name=sheet_name,
                        startrow=row_offset,
                    )
                    row_offset += len(df) + 2

        print(f"Sensitivity export written to: {output_path}")

    except Exception as e:
        print(f"export_sensitivity_to_excel error: {e}\n{traceback.format_exc()}")
