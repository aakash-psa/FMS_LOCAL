import numpy as np
import pandas as pd

from typing import List, Optional, Tuple, Union

# =============================================================================
# FINANCIAL METRIC FUNCTIONS (Excel-compatible: NPV, XNPV, IRR, XIRR, MIRR)
# =============================================================================

def _npv(rate: float, values: List[float]) -> float:
    """
    Calculate Net Present Value (Excel: NPV).
    Note: Excel NPV starts discounting from period 1, not period 0.
    """
    if not values:
        return 0.0
    return sum(v / (1 + rate) ** i for i, v in enumerate(values, start=1))


def _xnpv(rate: float, values: List[float], dates: List[pd.Timestamp]) -> float:
    """
    Calculate Net Present Value with irregular dates (Excel: XNPV).
    """
    if len(values) != len(dates) or not values:
        return 0.0

    # XNPV is undefined for rates <= -100%.
    if (1 + rate) <= 0:
        return np.inf
    
    t0 = dates[0]
    with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
        value = sum(
            v / (1 + rate) ** ((d - t0).days / 365.0)
            for v, d in zip(values, dates)
        )
    return value if np.isfinite(value) else np.inf


def _irr(values: List[float], guess: float = 0.1, tol: float = 1e-9, max_iter: int = 100) -> Optional[Union[float, str]]:
    """
    Calculate Internal Rate of Return (Excel: IRR) using Newton-Raphson method.
    Excel IRR finds rate where NPV=0, with values[0] at period 0 (not discounted).
    Returns None if convergence fails.
    If multiple distinct valid roots are found, returns them concatenated with ' | '.
    """
    if not values or len(values) < 2:
        return None
    
    # Check if there's at least one positive and one negative cashflow
    has_positive = any(v > 0 for v in values)
    has_negative = any(v < 0 for v in values)
    if not (has_positive and has_negative):
        return None
    
    def _try_newton_raphson(initial_guess: float) -> Optional[float]:
        rate = initial_guess
        for _ in range(max_iter):
            try:
                # NPV with period 0 at face value
                npv_val = sum(v / (1 + rate) ** i for i, v in enumerate(values))
                # Derivative of NPV
                d_npv = sum(-i * v / (1 + rate) ** (i + 1) for i, v in enumerate(values))
            except (OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
                return None

            if not np.isfinite(npv_val) or not np.isfinite(d_npv):
                return None
            
            if abs(d_npv) < 1e-12:
                return None
            
            new_rate = rate - npv_val / d_npv

            if not np.isfinite(new_rate):
                return None
            
            # Prevent rate from going too negative
            if new_rate <= -1:
                new_rate = -0.99
            
            if abs(new_rate - rate) < tol:
                return new_rate
            
            rate = new_rate
        
        return None
    
    def _npv_at_rate(rate: float) -> float:
        try:
            value = sum(v / (1 + rate) ** i for i, v in enumerate(values))
        except (OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
            return np.inf
        return value if np.isfinite(value) else np.inf

    default_guesses = [
        guess,
        -0.99,
        -0.9,
        -0.75,
        -0.5,
        -0.25,
        -0.1,
        0.0,
        0.1,
        0.25,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
    ]

    guesses: List[float] = []
    seen_guesses = set()
    for g in default_guesses:
        if g in seen_guesses:
            continue
        seen_guesses.add(g)
        guesses.append(g)

    roots: List[float] = []
    for g in guesses:
        result = _try_newton_raphson(g)
        if result is None or not np.isfinite(result) or result <= -1:
            continue

        # Keep only numerically valid roots where NPV is effectively zero.
        if abs(_npv_at_rate(result)) > 1e-5:
            continue

        if any(abs(result - existing_root) <= 1e-7 for existing_root in roots):
            continue
        roots.append(result)

    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    return " | ".join(f"{root:.12f}" for root in sorted(roots))


def _xirr(values: List[float], dates: List[pd.Timestamp], guess: float = 0.1, tol: float = 1e-9, max_iter: int = 100) -> Optional[Union[float, str]]:
    """
    Calculate Internal Rate of Return with irregular dates (Excel: XIRR).
    Excel XIRR finds rate where XNPV=0, using 365 days per year.
    Returns None if convergence fails.
    If multiple distinct valid roots are found, returns them concatenated with ' | '.
    """
    if len(values) != len(dates) or len(values) < 2:
        return None
    
    # Check if there's at least one positive and one negative cashflow
    has_positive = any(v > 0 for v in values)
    has_negative = any(v < 0 for v in values)
    if not (has_positive and has_negative):
        return None
    
    t0 = dates[0]
    day_fractions = [(d - t0).days / 365.0 for d in dates]
    
    def _try_newton_raphson(initial_guess: float) -> Optional[float]:
        rate = initial_guess
        for _ in range(max_iter):
            try:
                base = 1 + rate
                if base <= 0:
                    return None

                with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
                    f = sum(
                        v / base ** frac
                        for v, frac in zip(values, day_fractions)
                    )

                    df = sum(
                        -frac * v / base ** (frac + 1)
                        for v, frac in zip(values, day_fractions)
                    )
            except (OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
                return None

            if not np.isfinite(f) or not np.isfinite(df):
                return None
            
            if abs(df) < 1e-12:
                return None
            
            new_rate = rate - f / df

            if not np.isfinite(new_rate):
                return None
            
            # Prevent rate from going too negative
            if new_rate <= -1:
                new_rate = -0.99
            
            if abs(new_rate - rate) < tol:
                return new_rate
            
            rate = new_rate
        
        return None
    
    def _xnpv_at_rate(rate: float) -> float:
        try:
            base = 1 + rate
            if base <= 0:
                return np.inf

            with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
                value = sum(
                    v / base ** frac
                    for v, frac in zip(values, day_fractions)
                )
        except (OverflowError, ZeroDivisionError, ValueError, FloatingPointError):
            return np.inf
        return value if np.isfinite(value) else np.inf

    default_guesses = [
        guess,
        -0.99,
        -0.9,
        -0.75,
        -0.5,
        -0.25,
        -0.1,
        0.0,
        0.1,
        0.25,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
    ]

    guesses: List[float] = []
    seen_guesses = set()
    for g in default_guesses:
        if g in seen_guesses:
            continue
        seen_guesses.add(g)
        guesses.append(g)

    roots: List[float] = []
    for g in guesses:
        result = _try_newton_raphson(g)
        if result is None or not np.isfinite(result) or result <= -1:
            continue

        # Keep only numerically valid roots where XNPV is effectively zero.
        if abs(_xnpv_at_rate(result)) > 1e-5:
            continue

        if any(abs(result - existing_root) <= 1e-7 for existing_root in roots):
            continue
        roots.append(result)

    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    return " | ".join(f"{root:.12f}" for root in sorted(roots))


def _mirr(values: List[float], finance_rate: float, reinvest_rate: float) -> Optional[float]:
    """
    Calculate Modified Internal Rate of Return (Excel: MIRR).
    
    Excel MIRR formula:
    - PV of negative cashflows (discounted to period 0 at finance_rate)
    - FV of positive cashflows (compounded to period n-1 at reinvest_rate)
    - MIRR = (FV / -PV)^(1/(n-1)) - 1
    
    Returns None if calculation is not possible.
    """
    if not values or len(values) < 2:
        return None
    
    n = len(values)
    
    # Present value of negative cashflows (discounted to period 0 at finance rate)
    pv_neg = sum(v / (1 + finance_rate) ** i for i, v in enumerate(values) if v < 0)
    
    # Future value of positive cashflows (compounded to period n-1 at reinvestment rate)
    fv_pos = sum(v * (1 + reinvest_rate) ** (n - 1 - i) for i, v in enumerate(values) if v > 0)
    
    # MIRR requires both negative and positive cashflows
    if pv_neg == 0 or fv_pos == 0:
        return None
    
    # MIRR = (FV / -PV)^(1/(n-1)) - 1
    return (fv_pos / -pv_neg) ** (1.0 / (n - 1)) - 1


def _annual_to_monthly_rate(annual_rate: float) -> float:
    """Convert annual rate to monthly compounding rate."""
    if annual_rate is None:
        return 0.0
    return ((1 + annual_rate) ** (1/12)) - 1


def _annual_to_quarterly_rate(annual_rate: float) -> float:
    """Convert annual rate to quarterly compounding rate."""
    if annual_rate is None:
        return 0.0
    return ((1 + annual_rate) ** (1/4)) - 1


def _monthly_rate_to_annual(monthly_rate: float) -> float:
    """Convert monthly compounding rate to annual rate."""
    if monthly_rate is None:
        return 0.0
    return ((1 + monthly_rate) ** 12) - 1


def _quarterly_rate_to_annual(quarterly_rate: float) -> float:
    """Convert quarterly compounding rate to annual rate."""
    if quarterly_rate is None:
        return 0.0
    return ((1 + quarterly_rate) ** 4) - 1


def _aggregate_cashflows_by_frequency(
    monthly_cashflows: List[float],
    period_end_dates: List[pd.Timestamp],
    frequency: str,
) -> Tuple[List[float], List[pd.Timestamp]]:
    """
    Aggregate monthly cashflows to quarterly or annual frequency.
    
    Args:
        monthly_cashflows: List of monthly cashflow values
        period_end_dates: List of period end dates
        frequency: 'Monthly', 'Quarterly', or 'Annual'
    
    Returns:
        Tuple of (aggregated_cashflows, aggregated_dates)
    """
    if not monthly_cashflows or not period_end_dates:
        return [], []
    
    if frequency.lower() == "monthly":
        return monthly_cashflows, period_end_dates
    
    df = pd.DataFrame({
        "cashflow": monthly_cashflows,
        "date": period_end_dates,
    })
    
    if frequency.lower() == "quarterly":
        df["period"] = pd.to_datetime(df["date"]).dt.to_period("Q")
    else:  # Annual
        df["period"] = pd.to_datetime(df["date"]).dt.to_period("Y")
    
    agg = df.groupby("period").agg({
        "cashflow": "sum",
        "date": "max",  # Use period end date
    }).reset_index(drop=True)
    
    return agg["cashflow"].tolist(), agg["date"].tolist()
