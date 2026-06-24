import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from pyxirr import xirr


# ─────────────────────────────────────────────────────────────────────────────
# IRR DECOMPOSITION LINE ITEMS  (used by wrappper_for_vars)
# ─────────────────────────────────────────────────────────────────────────────

IRR_DECOMPOSITION_LINE_ITEMS = {
    "Net Cashflow from Operations":  ["Net Cashflow from Operations"],
    "Net Cashflow from Investments": ["Net Cashflow from Investments"],
    "Net Cashflow from Financing":   ["Net Cashflow from Financing"],
    "Equity Injection":              ["Equity Injection"],
    "Total Asset Acquisition Cost":  ["Total Asset Acquisition Cost"],
}


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: class -> dict
# ─────────────────────────────────────────────────────────────────────────────

def _class_to_dict(obj):
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _class_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_class_to_dict(item) for item in obj]
    if isinstance(obj, type):
        return {k: _class_to_dict(v) for k, v in vars(obj).items()
                if not k.startswith("_")}
    if hasattr(obj, "__dict__"):
        return {k: _class_to_dict(v) for k, v in vars(obj).items()
                if not k.startswith("_")}
    try:
        return obj.item() if hasattr(obj, "item") else str(obj)
    except Exception:
        return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: extract a line item from a cashflow DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def _extract_line_item_value(df, line_item_name, value_type="Monthly"):
    try:
        if df is None or df.empty:
            return None
        d = df.copy().replace([np.inf, -np.inf], 0)
        d = d.where(pd.notna(d), 0)
        for idx_name, row in d.iterrows():
            if str(idx_name).strip() == line_item_name.strip():
                row_vals = row.tolist()
                total = sum(
                    float(v) if isinstance(v, (int, float, np.integer, np.floating))
                    and not (isinstance(v, float) and np.isnan(v)) else 0
                    for v in row_vals
                )
                return total if total != 0 else None
        return None
    except Exception as e:
        print(f"Error extracting line item '{line_item_name}': {e}")
        return None


def _extract_line_item_series(df, line_item_name):
    """Return the full pandas Series for a named row in a cashflow DataFrame."""
    try:
        if df is None or df.empty:
            return None
        d = df.copy().replace([np.inf, -np.inf], 0).where(pd.notna(df), 0)
        for idx_name, row in d.iterrows():
            if str(idx_name).strip() == line_item_name.strip():
                return row
        return None
    except Exception as e:
        print(f"Error extracting series '{line_item_name}': {e}")
        return None


def _extract_first_matching_line_item_value(df, line_item_names, value_type="Monthly"):
    for name in line_item_names:
        v = _extract_line_item_value(df, name, value_type)
        if v is not None:
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CONSOLIDATION: assign unit values to Global
# ─────────────────────────────────────────────────────────────────────────────

def wrappper_for_vars(
    Global, Unit,
    cashflow_from_operations, cashflow_section, value_type, monthly_period_starts,
    cashflow_from_investments=None, cashflow_from_financing=None,
):
    try:
        def _get(key):
            src = (cashflow_from_operations if "Operations" in key
                   else cashflow_from_investments if "Investments" in key or "Asset" in key
                   else cashflow_from_financing)
            return _extract_first_matching_line_item_value(
                src, IRR_DECOMPOSITION_LINE_ITEMS[key], value_type)

        irr_values = {k: _get(k) for k in IRR_DECOMPOSITION_LINE_ITEMS}
        return {"Model Start Date": Global.ModelInputs.model_start_date, **irr_values}
    except Exception as e:
        print(f"Failed to initialise values: {e}\n{traceback.format_exc()}")
        return None


def fninitialising_all_values(
    Global, Unit,
    cashflow_from_operations, cashflow_section, value_type, monthly_period_starts,
    cashflow_from_investments=None, cashflow_from_financing=None,
):
    try:
        return wrappper_for_vars(
            Global, Unit, cashflow_from_operations, cashflow_section,
            value_type, monthly_period_starts,
            cashflow_from_investments=cashflow_from_investments,
            cashflow_from_financing=cashflow_from_financing,
        )
    except Exception as e:
        print(f"Error in initialising all values: {e}")
        return None




# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: NOI Yield % at Entry (NIY)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_noi_yield_percent(first_year_noi, acquisition_price):
    """
    Entry NIY = first_year_noi / acquisition_price.
    This is Component 1 (NIY / Income Return) and is DEFINED directly,
    not computed as an XIRR.
    """
    try:
        if not acquisition_price:
            print("Error: acquisition_price is zero or None")
            return None
        if first_year_noi is None:
            print("Error: first_year_noi is None")
            return None

        noi_yield = float(first_year_noi) / float(acquisition_price)

        # print(f"\n{'='*80}")
        # print(f"STEP 1: NOI YIELD % AT TIME OF ENTRY  (NIY)")
        # print(f"{'='*80}")
        # print(f"  First Year NOI:    {first_year_noi:>22,.2f}")
        # print(f"  Acquisition Price: {acquisition_price:>22,.2f}")
        # print(f"  NIY:               {noi_yield:>22.6f}  ({noi_yield*100:.4f}%)")

        return noi_yield
    except Exception as e:
        print(f"Error in Step 1: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2A: Exit Price @ NIY Constant
# ─────────────────────────────────────────────────────────────────────────────

def calculate_step_2a(
    last_12m_unescalated_noi,
    terminal_value_escalation_factor,
    noi_yield_percent,
    acquisition_price,
):
    """
    NIY exit price = last_12m_unescalated_noi × (1 + esc) / entry_NIY

    Used in Components 2A and 2B as the terminal capital inflow.

    Verified:
        last_12m_unescalated_noi = 5,474,049
        esc = 4.96%
        entry_NIY = 4.4153%
        => Exit Price = 5,474,049 × 1.0496 / 0.044153 = 130,127,826  ✓
    """
    try:
        if terminal_value_escalation_factor is None:
            print("Error: terminal_value_escalation_factor is None")
            return None
        if not noi_yield_percent:
            print("Error: noi_yield_percent is zero or None")
            return None
        if last_12m_unescalated_noi is None:
            print("Error: last_12m_unescalated_noi is None")
            return None

        escalated_noi = last_12m_unescalated_noi * (1 + terminal_value_escalation_factor)
        exit_price    = escalated_noi / noi_yield_percent

        # print(f"\n{'='*80}")
        # print(f"STEP 2A: EXIT PRICE @ NIY CONSTANT  (Capital CF @NIY)")
        # print(f"{'='*80}")
        # print(f"  Last 12M Unescalated NOI:          {last_12m_unescalated_noi:>20,.2f}")
        # print(f"  Terminal Value Escalation Factor:  {terminal_value_escalation_factor:>20.6f}")
        # print(f"  Escalated NOI (×(1+esc)):          {escalated_noi:>20,.2f}")
        # print(f"  Entry NIY:                         {noi_yield_percent:>20.6f}")
        # print(f"  NIY Exit Price:                    {exit_price:>20,.2f}")

        return {
            "noi_without_inflation":            last_12m_unescalated_noi,
            "acquisition_price":                acquisition_price,
            "terminal_value_escalation_factor": terminal_value_escalation_factor,
            "noi_yield_percent":                noi_yield_percent,
            "exit_price":                       exit_price,
        }
    except Exception as e:
        print(f"Error in Step 2A: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# BUILD MONTHLY CASHFLOW SERIES
# ─────────────────────────────────────────────────────────────────────────────

def _build_monthly_cf(monthly_noi_series, entry_outflow, exit_capital,
                      entry_date, exit_date=None):
    """
    Construct monthly dates and net cashflows for a single IRR component.

    Cash-flow convention (matching Excel Leo Email sheet):
        - All dates are first-of-month (entry_date must be 1st of month)
        - entry outflow is COMBINED with month-1 operating CF
        - exit capital is COMBINED with last-month operating CF (dated 1st of exit month)

    Args:
        monthly_noi_series : list[float], one value per month (120 for 10-year hold)
        entry_outflow      : float, negative (e.g. -acquisition_price)
        exit_capital       : float, positive capital inflow at exit
        entry_date         : datetime, acquisition/entry date (must be 1st of month)
        exit_date          : unused, kept for API compatibility

    Returns:
        (dates, cfs) where both are lists of length n
    """
    n      = len(monthly_noi_series)
    cfs    = list(monthly_noi_series)
    cfs[0] = cfs[0] + entry_outflow      # combine entry outflow with first-month NOI
    cfs[-1] = cfs[-1] + exit_capital     # combine exit capital with last-month NOI

    # All dates are 1st of each month — matches Excel's first-of-month convention
    dates = [entry_date + relativedelta(months=i) for i in range(n)]

    return dates, cfs


# ─────────────────────────────────────────────────────────────────────────────
# FULL IRR DECOMPOSITION (MONTHLY XIRR — PRIMARY)
# ─────────────────────────────────────────────────────────────────────────────

def compute_irr_decomposition(
    acquisition_price,
    asset_sale_value,
    entry_date,
    exit_date,
    first_year_noi,
    flat_noi_series,
    rampup_noi_series,
    full_noi_series,
    terminal_value_escalation_factor,
    exit_yield=None,
    last_12m_unescalated_noi=None,
    niy_exit_price=None,
):
    """
    Five-component IRR decomposition (Leo Email methodology).

    Component cash-flow structure (monthly series, T0=entry, Tn=exit):
        NIY (Comp 1)  : defined as first_year_noi / acquisition_price (no XIRR needed)
        Comp 2A       : entry −acq, monthly rampup NOI, exit @ NIY price
        Comp 2B       : entry −acq, monthly full NOI,   exit @ NIY price
        Comp 3        : entry −acq, monthly flat NOI,   exit @ (first_year_noi/exit_yield)
        Actual        : entry −acq, monthly full NOI,   exit @ asset_sale_value

    IMPORTANT distinctions:
        Comp-3 exit  = first_year_noi / exit_yield  (theoretical value at actual yield)
                       NOT asset_sale_value
        Actual exit  = asset_sale_value             (true net sale proceeds)

    Args:
        acquisition_price:                Total purchase price (positive)
        asset_sale_value:                 Net sale proceeds for Actual IRR
        entry_date:                       datetime, acquisition date
        exit_date:                        datetime, sale date
        first_year_noi:                   First-year annual NOI  (= NIY × acquisition_price)
        flat_noi_series:                  list[float], monthly flat NOI (len = holding months)
        rampup_noi_series:                list[float], monthly ramp-up NOI (no inflation)
        full_noi_series:                  list[float], monthly full NOI (incl. inflation)
        terminal_value_escalation_factor: e.g. 0.0496 for NIY exit computation
        exit_yield:                       actual exit cap rate (for Comp-3 exit price)
        last_12m_unescalated_noi:         annual unescalated NOI for NIY exit (sum of last 12m)
        niy_exit_price:                   override NIY exit price directly (skips Step 2A)

    Returns:
        dict with all component IRRs, incremental decomposition, and inputs.
    """
    try:
        # print(f"\n{'#'*80}")
        # print(f"# IRR DECOMPOSITION ANALYSIS")
        # print(f"# Entry: {entry_date.strftime('%d-%b-%y')}  |  "
        #       f"Exit: {exit_date.strftime('%d-%b-%y')}")
        # print(f"#{'='*78}#\n")

        n_months = len(flat_noi_series)
        hp       = (exit_date - entry_date).days / 365.25

        # print(f"  Holding Period:    {hp:.2f} years  ({n_months} monthly periods)")
        # print(f"  Acquisition Price: {acquisition_price:>20,.2f}")
        # print(f"  Asset Sale Value:  {asset_sale_value:>20,.2f}")

        # ── Step 1: Entry NIY (defined, not XIRR) ────────────────────────────
        entry_niy = calculate_noi_yield_percent(first_year_noi, acquisition_price)
        if entry_niy is None:
            return None

        # ── Step 2A: NIY exit price ───────────────────────────────────────────
        if niy_exit_price is not None:
            capital_niy_exit = niy_exit_price
            print(f"\n  NIY Exit Price (override):  {capital_niy_exit:>20,.2f}")
        else:
            if last_12m_unescalated_noi is None:
                # Annualised last-month NOI — same logic as in the wrapper above.
                last_12m_unescalated_noi = full_noi_series[-1] * 12
            step2a = calculate_step_2a(
                last_12m_unescalated_noi,
                terminal_value_escalation_factor,
                entry_niy,
                acquisition_price,
            )
            if step2a is None:
                return None
            capital_niy_exit = step2a["exit_price"]

        # ── Capital exit prices ───────────────────────────────────────────────
        # Comp 3: theoretical exit at actual yield using FLAT (first-year) NOI
        if exit_yield and exit_yield > 0:
            capital_comp3_exit = first_year_noi / exit_yield
        else:
            capital_comp3_exit = asset_sale_value
            print("  WARNING: exit_yield not provided; Comp-3 exit defaults to asset_sale_value")

        capital_actual_exit = asset_sale_value   # Actual Unlevered IRR

        # print(f"\n{'='*80}")
        # print(f"CAPITAL CASH FLOWS SUMMARY")
        # print(f"{'='*80}")
        # print(f"  Entry outflow:                         {-acquisition_price:>20,.2f}")
        # print(f"  NIY Exit (Comps 2A, 2B):               {capital_niy_exit:>20,.2f}")
        # print(f"  Comp-3 Exit (flat NOI / exit yield):   {capital_comp3_exit:>20,.2f}")
        # print(f"  Actual Exit (asset sale value):        {capital_actual_exit:>20,.2f}")
        if exit_yield:
            print(f"  Actual Exit Yield:                     {exit_yield:>18.4f}"
                  f"  ({exit_yield*100:.2f}%)")

        entry_outflow = -acquisition_price

        # ── Debug CSV: save all series used in XIRR calls ────────────────────
        try:
            n = len(full_noi_series)
            _dates_col = [entry_date + relativedelta(months=i) for i in range(n)]

            # Reconstruct capital-only vectors (matching old schedule array columns)
            _exit_value_cf      = [0.0] * n
            _exit_value_cf[0]  += entry_outflow       # -acq at entry  (col 6)
            _exit_value_cf[-1] += capital_niy_exit    # NIY exit at last

            _acq_cf      = [0.0] * n
            _acq_cf[0]  += entry_outflow              # -acq at entry  (col 4)
            _acq_cf[-1] += acquisition_price          # +acq at last

            _capture_cf      = [0.0] * n
            _capture_cf[0]  += entry_outflow          # -acq at entry  (col 8)
            _capture_cf[-1] += capital_comp3_exit     # comp-3 exit at last

            _debug_df = pd.DataFrame({
                "period_end_date":       [d.strftime("%Y-%m-%d") for d in _dates_col],
                "acquisition_cashflow":  _acq_cf,                      # col 4
                "noi_escalated":         list(flat_noi_series),         # col 5  (first_year_noi/12, flat)
                "exit_value_cashflow":   _exit_value_cf,                # col 6
                "noi_unescalated":       list(rampup_noi_series),       # col 7
                "capture_sale_cashflow": _capture_cf,                   # col 8
            })
            # _debug_df.to_csv("schedule_array.csv", index=False)
            # print(f"  [debug] schedule_array.csv saved ({n} rows)")
            # print(_debug_df.to_string(max_rows=10))
        except Exception as _e:
            print(f"  [debug] CSV save failed: {_e}")

        # ── Component 2A: CF Growth Ramp-up ──────────────────────────────────
        # print(f"\n{'='*80}")
        # print(f"COMPONENT 2A: CF GROWTH - RAMP-UP  (rampup NOI, NIY exit)")
        # print(f"{'='*80}")
        dates_2a, cf_2a = _build_monthly_cf(
            rampup_noi_series, entry_outflow, capital_niy_exit, entry_date, exit_date)
        irr_2a = xirr(dates_2a, cf_2a)
        comp_2a = irr_2a - entry_niy
        # print(f"  Sum of monthly rampup NOI: {sum(rampup_noi_series):>18,.2f}")
        # print(f"  IRR 2A (total):            {irr_2a*100:>18.4f}%")
        # print(f"  CF Growth: Ramp-up (2A-NIY): {comp_2a*100:>16.4f}%  (target: 11.44%)")

        # ── Component 2B: CF Growth Inflation & Reletting ────────────────────
        # print(f"\n{'='*80}")
        # print(f"COMPONENT 2B: CF GROWTH - INFLATION & RELETTING  (full NOI, NIY exit)")
        # print(f"{'='*80}")
        dates_2b, cf_2b = _build_monthly_cf(
            full_noi_series, entry_outflow, capital_niy_exit, entry_date, exit_date)
        irr_2b = xirr(dates_2b, cf_2b)
        comp_2b = irr_2b - irr_2a
        # print(f"  Sum of monthly full NOI:   {sum(full_noi_series):>18,.2f}")
        # print(f"  IRR 2B (total):            {irr_2b*100:>18.4f}%")
        # print(f"  CF Growth: Inflation (2B-2A): {comp_2b*100:>15.4f}%  (target: 0.31%)")

        # ── Component 3: Yield Differential ──────────────────────────────────
        # print(f"\n{'='*80}")
        # print(f"COMPONENT 3: YIELD DIFFERENTIAL  (flat NOI, exit @ first_year_noi/exit_yield)")
        # print(f"{'='*80}")
        dates_3, cf_3 = _build_monthly_cf(
            flat_noi_series, entry_outflow, capital_comp3_exit, entry_date, exit_date)
        irr_3  = xirr(dates_3, cf_3)
        comp_3 = irr_3 - entry_niy
        # print(f"  Sum of monthly flat NOI:   {sum(flat_noi_series):>18,.2f}")
        # print(f"  Comp-3 exit price:         {capital_comp3_exit:>18,.2f}")
        # print(f"  IRR 3 (total):             {irr_3*100:>18.4f}%")
        # print(f"  Yield Differential (3-NIY): {comp_3*100:>16.4f}%  (target: -4.03%)")

        # # ── Actual Unlevered IRR ──────────────────────────────────────────────
        # print(f"\n{'='*80}")
        # print(f"ACTUAL UNLEVERED IRR  (full NOI, exit @ asset sale value)")
        # print(f"{'='*80}")
        dates_act, cf_act = _build_monthly_cf(
            full_noi_series, entry_outflow, capital_actual_exit, entry_date, exit_date)
        irr_act = xirr(dates_act, cf_act)
        # print(f"  Actual exit (asset sale value): {capital_actual_exit:>16,.2f}")
        # print(f"  Actual Unlevered IRR: {irr_act*100:>18.4f}%  (target: 11.74%)")

        # ── Interaction Effects ───────────────────────────────────────────────
        named_sum   = entry_niy + comp_2a + comp_2b + comp_3
        interaction = irr_act - named_sum
        # print(f"\n  Sum of named components:  {named_sum*100:.4f}%")
        # print(f"  Interaction Effects:      {interaction*100:.4f}%  (target: -0.39%)")

        # ── Equivalent of old calculate_irr_components print ─────────────────
        # irr1=entry_niy  irr2a=irr_2a(total)  irr2b=irr_2b(total)  irr3=irr_3(total)
        # print(f"\n  [irr_components] irr1={entry_niy:.6f}  irr2a={irr_2a:.6f}  "
        #       f"irr2b={irr_2b:.6f}  irr3={irr_3:.6f}  irr_actual={irr_act:.6f}")
        # print(f"  [irr_components] irr1={entry_niy*100:.4f}%  irr2a={irr_2a*100:.4f}%  "
        #       f"irr2b={irr_2b*100:.4f}%  irr3={irr_3*100:.4f}%  irr_actual={irr_act*100:.4f}%")

        # ── Summary ───────────────────────────────────────────────────────────
        W = 80
        # print(f"\n{'#'*W}")
        # print(f"  IRR DECOMPOSITION SUMMARY")
        # print(f"{'='*W}")
        # _row("NIY Component",                    entry_niy,)
        # _row("CF Growth: Ramp-up",               comp_2a,  )
        # _row("CF Growth: Inflation & Reletting", comp_2b,  )
        # _row("Yield Differential",               comp_3,   )
        # _row("Interaction Effects",              interaction,)
        # print(f"  {'-'*58}")
        # _row("Unlevered IRR",                    irr_act,)
        # print(f"{'#'*W}\n")

        return {
            # inputs
            "acquisition_price":                acquisition_price,
            "asset_sale_value":                 asset_sale_value,
            "entry_date":                       entry_date,
            "exit_date":                        exit_date,
            "holding_years":                    hp,
            "n_months":                         n_months,
            "first_year_noi":                   first_year_noi,
            "entry_niy":                        entry_niy,
            "exit_yield":                       exit_yield,
            "terminal_value_escalation_factor": terminal_value_escalation_factor,
            "last_12m_unescalated_noi":         last_12m_unescalated_noi,
            # capital CF reference values
            "capital_cf_niy_exit":              capital_niy_exit,
            "capital_cf_comp3_exit":            capital_comp3_exit,
            "capital_cf_actual_exit":           capital_actual_exit,
            # component IRRs (total XIRR for 2A, 2B, 3)
            "irr_comp2a_total":                 irr_2a,
            "irr_comp2b_total":                 irr_2b,
            "irr_comp3_total":                  irr_3,
            "irr_actual_unlevered":             irr_act,
            # incremental decomposition  (the reported components)
            "component_niy":                    entry_niy,
            "component_cf_growth_rampup":       comp_2a,
            "component_cf_growth_inflation":    comp_2b,
            "component_yield_differential":     comp_3,
            "component_interaction_effects":    interaction,
            "unlevered_irr":                    irr_act,
        }

    except Exception as e:
        print(f"Error in compute_irr_decomposition: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MODEL INTEGRATION: extract monthly NOI series from cashflow DataFrames
# ─────────────────────────────────────────────────────────────────────────────

def compute_irr_decomposition_from_cashflows(
    Global,
    cashflow_from_operations,
    cashflow_from_investments,
    terminal_value_escalation_factor,
    exit_yield,
    last_12m_unescalated_noi=None,
    niy_exit_price=None,
    noi_line_item="Net Operating Income",
    rampup_noi_line_item="Net Operating Income (Unescalated)",
    acq_price_line_item="Total Asset Acquisition Cost",
    sale_value_line_item="Net Asset Sale Value",
):
    """
    High-level wrapper: pulls monthly NOI series from the model's cashflow DataFrames
    and calls compute_irr_decomposition.

    The holding period is inferred from Global.ModelInputs.acquisition_date /
    asset_sale_date and the cashflow DataFrame columns.

    Args:
        Global:                          Model globals object
        cashflow_from_operations (df):   CFO DataFrame, rows indexed by line-item name,
                                         columns = monthly period-start dates
        cashflow_from_investments (df):  CFI DataFrame (same structure)
        terminal_value_escalation_factor: e.g. 0.0496
        exit_yield:                      actual exit cap rate (e.g. 0.075)
        last_12m_unescalated_noi:        optional, sum of last 12 unescalated monthly NOIs
        niy_exit_price:                  optional, override the NIY exit price directly
        noi_line_item:                   row label for full (escalated) NOI in CFO df
        rampup_noi_line_item:            row label for unescalated NOI in CFO df
        acq_price_line_item:             row label for acquisition cost in CFI df
        sale_value_line_item:            row label for net sale value in CFI df

    Returns:
        dict (same as compute_irr_decomposition) or None on failure
    """
    try:
        # ── dates ─────────────────────────────────────────────────────────────
        entry_date = getattr(Global.ModelInputs, "acquisition_date", None)
        exit_date  = getattr(Global.ModelInputs, "asset_sale_date", None)
        if entry_date is None or exit_date is None:
            print("ERROR: acquisition_date or asset_sale_date missing from Global.ModelInputs")
            return None

        # Ensure datetime
        if not isinstance(entry_date, datetime):
            entry_date = datetime.combine(entry_date, datetime.min.time())
        if not isinstance(exit_date, datetime):
            exit_date = datetime.combine(exit_date, datetime.min.time())

        # ── acquisition price ─────────────────────────────────────────────────
        acq_price = None
        if hasattr(Global, "AcquisitionModule") and getattr(
                Global.AcquisitionModule, "acquisition_price", None):
            acq_price = float(Global.AcquisitionModule.acquisition_price)
        else:
            acq_row = _extract_line_item_series(cashflow_from_investments, acq_price_line_item)
            if acq_row is not None:
                acq_price = float(abs(acq_row.sum()))
        if not acq_price:
            print(f"ERROR: could not resolve acquisition_price")
            return None

        # ── asset sale value ─────────────────────────────────────────────────
        sale_row = _extract_line_item_series(cashflow_from_investments, sale_value_line_item)
        if sale_row is None:
            print(f"ERROR: '{sale_value_line_item}' not found in cashflow_from_investments")
            return None
        asset_sale_value = float(sale_row.sum())

        # asset_sale_value = 75_856_440.00  # HARDCODED FOR TESTING
        # print(f"  [DEBUG] asset_sale_value hardcoded to: {asset_sale_value:,.2f}")

        # ── slice to holding period ────────────────────────────────────────────
        # CFO columns are monthly period-start dates
        columns = pd.to_datetime(cashflow_from_operations.columns)
        holding_mask = (columns >= entry_date) & (columns <= exit_date)
        cfo_holding  = cashflow_from_operations.loc[:, holding_mask]

        # ── extract monthly NOI series ────────────────────────────────────────
        full_noi_row   = _extract_line_item_series(cfo_holding, noi_line_item)
        rampup_noi_row = _extract_line_item_series(cfo_holding, rampup_noi_line_item)

        if full_noi_row is None:
            print(f"ERROR: '{noi_line_item}' not found in cashflow_from_operations")
            return None

        full_noi_monthly = full_noi_row.tolist()

        if rampup_noi_row is not None:
            rampup_noi_monthly = rampup_noi_row.tolist()
        else:
            print(f"  WARNING: '{rampup_noi_line_item}' not found; "
                  f"rampup series defaults to full_noi (no ramp-up decomposition)")
            rampup_noi_monthly = full_noi_monthly

        # First-year NOI = sum of first 12 monthly full-NOI values
        first_year_noi = float(sum(full_noi_monthly[:12]))

        # Flat NOI = first_year_noi/12 for every month in holding period
        monthly_flat   = first_year_noi / 12.0
        flat_noi_monthly = [monthly_flat] * len(full_noi_monthly)

        # last_12m_unescalated for NIY exit (if not supplied)
        if last_12m_unescalated_noi is None:
            # Use annualised last-month NOI (last_month × 12), NOT sum(last_12m).
            # Cap-rate valuation needs the current run-rate at exit. Summing the
            # actual last 12 months blends old and new rent levels when a step-up
            # falls mid-period, understating the reversionary NOI.
            last_12m_unescalated_noi = float(full_noi_monthly[-1] * 12)

        return compute_irr_decomposition(
            acquisition_price                = acq_price,
            asset_sale_value                 = asset_sale_value,
            entry_date                       = entry_date,
            exit_date                        = exit_date,
            first_year_noi                   = first_year_noi,
            flat_noi_series                  = flat_noi_monthly,
            rampup_noi_series                = rampup_noi_monthly,
            full_noi_series                  = full_noi_monthly,
            terminal_value_escalation_factor = terminal_value_escalation_factor,
            exit_yield                       = exit_yield,
            last_12m_unescalated_noi         = last_12m_unescalated_noi,
            niy_exit_price                   = niy_exit_price,
        )

    except Exception as e:
        print(f"Error in compute_irr_decomposition_from_cashflows: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: approximate decomposition (no XIRR series)
# ─────────────────────────────────────────────────────────────────────────────

def compute_irr_decomposition_advanced(
    acquisition_price, asset_sale_value,
    entry_date, exit_date,
    flat_noi, actual_total_noi,
    rampup_noi_without_inflation, rampup_noi_with_inflation,
):
    """Legacy approximate decomposition (kept for backward compatibility)."""
    try:
        # print(f"\n{'='*80}")
        # print(f"ADVANCED IRR DECOMPOSITION  (legacy approximate method)")
        # print(f"{'='*80}\n")

        hp          = (exit_date - entry_date).days / 365.25
        entry_niy   = flat_noi / acquisition_price
        sale_at_niy = flat_noi / entry_niy
        exit_niy    = flat_noi / asset_sale_value
        yd_irr      = (asset_sale_value - sale_at_niy) / acquisition_price / hp
        cf_contrib  = (actual_total_noi - flat_noi) / acquisition_price / hp
        infl_contrib= (rampup_noi_with_inflation - rampup_noi_without_inflation) / acquisition_price / hp
        ann_return  = (actual_total_noi * hp + asset_sale_value - acquisition_price) / acquisition_price / hp

        print(f"  {'Income Return:':<40} {entry_niy*100:.4f}%")
        print(f"  {'CF Growth Component:':<40} {cf_contrib*100:.4f}%")
        print(f"  {'Inflation Component:':<40} {infl_contrib*100:.4f}%")
        print(f"  {'Yield Differential Component:':<40} {yd_irr*100:.4f}%")
        print(f"  {'Total Annualized Return (approx):':<40} {ann_return*100:.4f}%")

        return {
            "holding_period_years":         hp,
            "acquisition_price":            acquisition_price,
            "asset_sale_value":             asset_sale_value,
            "entry_niy":                    entry_niy,
            "exit_niy":                     exit_niy,
            "yield_differential":           exit_niy - entry_niy,
            "income_return_component":      entry_niy,
            "cf_growth_component":          cf_contrib,
            "inflation_component":          infl_contrib,
            "yield_differential_component": yd_irr,
            "total_annualized_return":      ann_return,
        }
    except Exception as e:
        print(f"Error in legacy decomposition: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _print_cashflows(label, dates, flows, max_rows=5):
    print(f"\n  Cash Flows - {label} (first/last {max_rows}):")
    print(f"  {'Date':<14}  {'Cash Flow':>20}")
    print(f"  {'-'*36}")
    items = list(zip(dates, flows))
    show  = items[:max_rows] + [None] + items[-max_rows:]
    for item in show:
        if item is None:
            print(f"  {'...':<14}  {'...':>20}")
            continue
        d, f = item
        ds = d.strftime("%d-%b-%y") if isinstance(d, datetime) else str(d)
        print(f"  {ds:<14}  {f:>20,.2f}")


def _row(label, value, target=""):
    print(f"  {label:<44} {value*100:>8.2f}%   (target: {target})")

