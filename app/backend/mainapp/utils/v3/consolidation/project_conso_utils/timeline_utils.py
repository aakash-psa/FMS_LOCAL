"""
Master / monthly / yearly timeline construction.

fn_build_master_timeline is unified to support both the 2-parameter
calling convention (LandCo / DevCo) and the 1-parameter convention
(AssetCo) via an optional ``landco_timeline`` argument.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from .data_utils import fn_json_dict_to_dataframe


def fn_build_master_timeline(
    devco_timeline: Dict[str, Any],
    landco_timeline: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Build a master timeline from DevCo (and optionally LandCo) timeline payloads.

    When *landco_timeline* is ``None`` the function uses *devco_timeline*
    alone — this matches the original AssetCo behaviour.

    When *landco_timeline* is provided the function validates that both
    timelines align before returning the LandCo timeline as master — this
    matches the original LandCo / DevCo behaviour.

    Parameters:
    -----------
    devco_timeline : Dict[str, Any]
        DevCo timeline in split DataFrame format.
    landco_timeline : Optional[Dict[str, Any]]
        LandCo timeline in split DataFrame format.  Pass ``None`` for
        AssetCo-style single-timeline usage.

    Returns:
    --------
    pd.DataFrame
        Master timeline DataFrame, or empty DataFrame if unavailable.
    """
    master_timeline_df = pd.DataFrame()

    devco_timeline_df = fn_json_dict_to_dataframe(devco_timeline) if devco_timeline else None

    # AssetCo path — single timeline only.
    if landco_timeline is None:
        if devco_timeline_df is not None and not devco_timeline_df.empty:
            master_timeline_df = devco_timeline_df
        return master_timeline_df

    # LandCo / DevCo path — validate both timelines.
    landco_timeline_df = fn_json_dict_to_dataframe(landco_timeline) if landco_timeline else None

    landco_period_ends = (
        pd.to_datetime(landco_timeline_df.loc["Period End"]).dt.normalize()
    ) if landco_timeline_df is not None else pd.Series()

    devco_period_ends = (
        pd.to_datetime(devco_timeline_df.loc["Period End"]).dt.normalize()
    ) if devco_timeline_df is not None else pd.Series()

    if (
        landco_timeline_df is not None
        and devco_timeline_df is not None
        and not landco_timeline_df.empty
        and not devco_timeline_df.empty
    ):
        if not landco_timeline_df.index.equals(devco_timeline_df.index):
            print(
                "Warning: LandCo and DevCo timelines have different indices. "
                "Master timeline construction may be affected."
            )
        elif not landco_period_ends.equals(devco_period_ends):
            diff = pd.DataFrame({
                "landco": landco_period_ends,
                "devco": devco_period_ends,
            })
            diff = diff[diff["landco"] != diff["devco"]]
            print(diff)
            print(
                "Warning: LandCo and DevCo timelines have different 'Period End' "
                "values. Master timeline construction may be affected."
            )
        else:
            master_timeline_df = landco_timeline_df

    return master_timeline_df


def fn_build_monthly_model_timeline(period_end_dates: List[pd.Timestamp]) -> pd.DataFrame:
    """
    Build a monthly timeline DataFrame from period end dates.
    """
    if not period_end_dates:
        return pd.DataFrame(
            columns=["Period Start", "Period End", "Year", "Month", "# of Period", "# of Days"]
        )

    unique_period_ends = pd.DatetimeIndex(period_end_dates).sort_values().drop_duplicates()
    periods = unique_period_ends.to_period("M")
    period_start = periods.start_time
    period_end = periods.end_time.normalize()
    number_of_days = (period_end - period_start).days + 1

    timeline_df = pd.DataFrame(
        {
            "Period Start": period_start,
            "Period End": period_end,
            "Year": period_end.year,
            "Month": period_end.month,
            "# of Days": number_of_days,
        }
    )
    timeline_df["# of Period"] = timeline_df.index + 1

    return timeline_df[["Period Start", "Period End", "Year", "Month", "# of Period", "# of Days"]]


def fn_build_yearly_model_timeline(period_end_dates: List[pd.Timestamp]) -> pd.DataFrame:
    """
    Build a yearly timeline DataFrame from period end dates.
    """
    if not period_end_dates:
        return pd.DataFrame(
            columns=["Period Start", "Period End", "Year", "Month", "# of Period", "# of Days"]
        )

    unique_years = sorted({int(period_end.year) for period_end in period_end_dates})
    yearly_period_start = pd.to_datetime([f"{year}-01-01" for year in unique_years])
    yearly_period_end = pd.to_datetime([f"{year}-12-31" for year in unique_years])
    number_of_days = (yearly_period_end - yearly_period_start).days + 1

    timeline_df = pd.DataFrame(
        {
            "Period Start": yearly_period_start,
            "Period End": yearly_period_end,
            "Year": [period.year for period in yearly_period_end],
            "Month": [period.month for period in yearly_period_end],
            "# of Days": number_of_days,
        }
    )
    timeline_df["# of Period"] = timeline_df.index + 1

    return timeline_df[["Period Start", "Period End", "Year", "Month", "# of Period", "# of Days"]]
