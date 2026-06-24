"""
Excel-equivalent financial functions: IRR, XIRR, MIRR, XNPV.

Each function replicates Excel's exact algorithm and conventions:

  IRR   — Newton-Raphson; NPV at t=0,1,2,...; default guess 0.1; max 100 iterations;
           tolerance 1e-7 (Excel: "accurate within 0.00001 percent").
  XIRR  — Newton-Raphson; day-count = actual days / 365 from dates[0] (Excel convention).
  MIRR  — Negative flows discounted to t=0 at finance_rate via Excel's NPV convention
           (first flow one period away); positive flows compounded to t=n at reinvest_rate.
  XNPV  — sum(values[i] / (1+rate)^((dates[i]-dates[0]).days/365)); same day-count as XIRR.

Return values mirror Excel error behaviour:
  None  — equivalent to Excel's #NUM! or #DIV/0! (invalid inputs or no convergence).

Date inputs accepted as:
  • Python datetime.date / datetime.datetime
  • pandas Timestamp
  • Excel serial number (int/float; epoch 1899-12-30)
  • ISO-format string "YYYY-MM-DD"
"""

from __future__ import annotations

import datetime
from typing import List, Optional, Sequence, Union

DateLike = Union[datetime.date, datetime.datetime, float, int, str]

# Excel day-count epoch: serial 1 corresponds to 1899-12-31
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

# Newton-Raphson parameters matching Excel's internal engine
_MAX_ITER = 100
_TOLERANCE = 1e-7  # "0.00001 percent" per Excel documentation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_date(d: DateLike) -> datetime.date:
    """Normalise any date-like value to a Python datetime.date."""
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, datetime.date):
        return d
    if isinstance(d, (int, float)):
        # Excel serial number
        return _EXCEL_EPOCH + datetime.timedelta(days=int(d))
    if isinstance(d, str):
        return datetime.date.fromisoformat(d)
    raise TypeError(f"Cannot convert {type(d).__name__!r} to a date")


def _year_fractions(dates: Sequence[DateLike]) -> List[float]:
    """
    Return list of year-fractions from dates[0] using actual days / 365,
    matching Excel's XIRR / XNPV day-count convention.
    """
    d0 = _to_date(dates[0])
    return [(_to_date(d) - d0).days / 365.0 for d in dates]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def irr(values: List[float], guess: float = 0.1) -> Optional[float]:
    """
    Internal Rate of Return — Excel IRR(values, [guess]).

    Finds r such that:
        sum(values[t] / (1+r)^t  for t in range(n)) = 0

    The first cash flow (values[0]) is at t=0 (today); subsequent flows at
    t=1, 2, … — exactly as Excel treats the IRR argument list.

    Parameters
    ----------
    values : sequence of float
        Cash flows in chronological order. Must contain at least one positive
        and one negative value (otherwise Excel returns #NUM!).
    guess  : float, optional
        Starting estimate; default 0.1 (10%), matching Excel's default.

    Returns
    -------
    float or None
        Converged IRR, or None if the algorithm does not converge within
        _MAX_ITER iterations (Excel returns #NUM! in this case).
    """
    if not any(v > 0 for v in values) or not any(v < 0 for v in values):
        return None  # Excel: #NUM!

    rate = float(guess)
    for _ in range(_MAX_ITER):
        # f(r)  = NPV at current rate
        # f'(r) = derivative with respect to r
        f = sum(v / (1.0 + rate) ** t for t, v in enumerate(values))
        df = sum(-t * v / (1.0 + rate) ** (t + 1) for t, v in enumerate(values))
        if df == 0.0:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < _TOLERANCE:
            return new_rate
        rate = new_rate

    return None  # did not converge


def xirr(
    values: List[float],
    dates: List[DateLike],
    guess: float = 0.1,
) -> Optional[float]:
    """
    Extended IRR with irregular dates — Excel XIRR(values, dates, [guess]).

    Finds r such that:
        sum(values[i] / (1+r)^((dates[i]-dates[0]).days/365)  for i) = 0

    Day-count convention: actual days / 365 (identical to Excel).

    Parameters
    ----------
    values : sequence of float
        Cash flows. Must contain at least one positive and one negative value.
    dates  : sequence of date-like
        One date per cash flow. dates[0] is the reference (t=0). Later dates
        may be in any order, but dates[0] must be the earliest date to match
        Excel behaviour.
    guess  : float, optional
        Starting estimate; default 0.1 (10%), matching Excel's default.

    Returns
    -------
    float or None
        Converged XIRR, or None on failure.
    """
    if len(values) != len(dates):
        raise ValueError("values and dates must have the same length")
    if not any(v > 0 for v in values) or not any(v < 0 for v in values):
        return None

    years = _year_fractions(dates)
    rate = float(guess)

    for _ in range(_MAX_ITER):
        try:
            f  = sum(v / (1.0 + rate) ** y       for v, y in zip(values, years))
            df = sum(-y * v / (1.0 + rate) ** (y + 1) for v, y in zip(values, years))
        except (OverflowError, ZeroDivisionError):
            return None
        if df == 0.0:
            break
        new_rate = rate - f / df
        # Clamp to prevent divergence — Excel bounds rate search to (-1, very large)
        if new_rate <= -1.0:
            new_rate = -0.9999
        if abs(new_rate - rate) < _TOLERANCE:
            return new_rate
        rate = new_rate

    return None


def mirr(
    values: List[float],
    finance_rate: float,
    reinvest_rate: float,
) -> Optional[float]:
    """
    Modified Internal Rate of Return — Excel MIRR(values, finance_rate, reinvest_rate).

    Mirrors Excel's internal formula exactly:

        n       = len(values)
        pv_neg  = NPV(finance_rate,  [v if v<0 else 0])   ← Excel NPV convention
        npv_pos = NPV(reinvest_rate, [v if v>0 else 0])   ← Excel NPV convention
        MIRR    = (-npv_pos*(1+reinvest_rate)^n / (pv_neg*(1+finance_rate)))^(1/(n-1)) - 1

    Excel's NPV convention used here: first value is ONE period in the future,
        NPV(r, flows) = sum(flows[i] / (1+r)^(i+1))

    Economically:
      • Negative flows are discounted back to t=0 using finance_rate (cost of capital).
      • Positive flows are compounded forward to t=n-1 using reinvest_rate.
      • MIRR is the single rate that equates those two terminal values over n-1 periods.

    Parameters
    ----------
    values        : sequence of float
        Cash flows in order. Must contain at least one positive and one negative value.
    finance_rate  : float
        Rate paid on negative cash flows (borrowing / financing cost).
    reinvest_rate : float
        Rate earned on reinvested positive cash flows.

    Returns
    -------
    float or None
        The MIRR, or None if there are no positive flows, no negative flows,
        or fewer than 2 values (Excel returns #DIV/0! / #VALUE!).
    """
    n = len(values)
    if n < 2:
        return None

    neg = [v if v < 0 else 0.0 for v in values]
    pos = [v if v > 0 else 0.0 for v in values]

    # Excel NPV: first cash flow is one period away → exponent (i+1)
    pv_neg  = sum(neg[i] / (1.0 + finance_rate)  ** (i + 1) for i in range(n))
    npv_pos = sum(pos[i] / (1.0 + reinvest_rate) ** (i + 1) for i in range(n))

    if pv_neg == 0.0 or npv_pos == 0.0:
        return None  # Excel: #DIV/0!

    ratio = (-npv_pos * (1.0 + reinvest_rate) ** n) / (pv_neg * (1.0 + finance_rate))

    if ratio < 0:
        return None  # cannot take real root of negative number

    return ratio ** (1.0 / (n - 1)) - 1.0


def xnpv(
    rate: float,
    values: List[float],
    dates: List[DateLike],
) -> float:
    """
    Net Present Value with irregular dates — Excel XNPV(rate, values, dates).

    Formula:
        XNPV = sum(values[i] / (1+rate)^((dates[i]-dates[0]).days/365))

    The first cash flow (at dates[0]) is NOT discounted (exponent = 0).
    Day-count convention: actual days / 365 (identical to Excel).

    Parameters
    ----------
    rate   : float
        Discount rate per year.
    values : sequence of float
        Cash flows, one per date.
    dates  : sequence of date-like
        Dates for each cash flow. dates[0] is the reference date (t=0).

    Returns
    -------
    float
        The XNPV value.
    """
    if len(values) != len(dates):
        raise ValueError("values and dates must have the same length")

    years = _year_fractions(dates)
    return sum(v / (1.0 + rate) ** y for v, y in zip(values, years))
