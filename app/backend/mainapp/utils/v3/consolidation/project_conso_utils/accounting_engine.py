"""
Double-entry accounting engine: accounts, journal entries, rollforward,
financial statements, and batch-flush logic.

fn_flush_batch_entries is unified to support both:
- LandCo behaviour (interparty cash recognition + Revenue/Expense-aware IS posting)
- DevCo / AssetCo behaviour (simple cash recognition + simple IS posting)

via the optional *interparty_cash_name* and *type_aware_is_posting* parameters.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .template_utils import fn_build_financial_statement_row_index
from .financial_statement_trace_utils import (
    fn_record_batch_entry_financial_statement_trace,
    fn_record_matrix_entries_financial_statement_trace,
)

_FS_TRACE_ENABLED_STATE_KEY = "__enable_financial_statement_trace__"


def _is_financial_statement_trace_enabled(financial_statements: Dict[str, Any]) -> bool:
    if not isinstance(financial_statements, dict):
        return False
    return bool(financial_statements.get(_FS_TRACE_ENABLED_STATE_KEY, False))


# ---------------------------------------------------------------------------
# C.1  Account Creation
# ---------------------------------------------------------------------------

def fn_create_double_entry_account(
    account_name: str,
    account_names_dict: Dict[str, Dict[str, str]],
    period_ends: pd.Series,
    opening_balance: float = 0.0,
) -> Optional[pd.DataFrame]:
    """
    Create a double entry account DataFrame for a given account.
    """
    if account_name not in account_names_dict:
        print(f"fn_create_double_entry_account: Account '{account_name}' not found in account_names_dict")
        return None

    if period_ends is None or period_ends.empty:
        print("fn_create_double_entry_account: period_ends cannot be None or empty")
        return None

    try:
        normalized_periods = pd.to_datetime(period_ends).dt.normalize()
        unique_periods = list(dict.fromkeys(normalized_periods.astype(str).tolist()))
    except Exception as e:
        print(f"fn_create_double_entry_account: Error normalizing period ends: {str(e)}")
        return None

    account_df = pd.DataFrame(
        data=0.0,
        index=["Opening Balance", "Debit", "Credit", "Closing Balance"],
        columns=unique_periods,
        dtype="float64",
    )

    if len(unique_periods) > 0:
        account_df.loc["Opening Balance", unique_periods[0]] = opening_balance

    account_df.attrs["account_name"] = account_name
    account_df.attrs["account_type"] = account_names_dict[account_name]["type"]
    account_df.attrs["account_category"] = account_names_dict[account_name]["category"]

    return account_df


def fn_create_all_accounts(
    account_names_dict: Dict[str, Dict[str, str]],
    period_ends: pd.Series,
) -> Dict[str, pd.DataFrame]:
    """
    Create all double entry accounts based on account names dictionary.

    Pre-computes period normalization once and uses a shared numpy template
    to avoid redundant per-account work.
    """
    accounts: Dict[str, pd.DataFrame] = {}

    if period_ends is None or period_ends.empty:
        print("fn_create_all_accounts: period_ends cannot be None or empty")
        return accounts

    try:
        normalized_periods = pd.to_datetime(period_ends).dt.normalize()
        unique_periods = list(dict.fromkeys(normalized_periods.astype(str).tolist()))
    except Exception as e:
        print(f"fn_create_all_accounts: Error normalizing period ends: {str(e)}")
        return accounts

    _row_index = ["Opening Balance", "Debit", "Credit", "Closing Balance"]
    _n_cols = len(unique_periods)
    _template = np.zeros((4, _n_cols), dtype=np.float64)

    for account_name, acct_meta in account_names_dict.items():
        data = _template.copy()
        account_df = pd.DataFrame(
            data=data,
            index=_row_index,
            columns=unique_periods,
        )
        account_df.attrs["account_name"] = account_name
        account_df.attrs["account_type"] = acct_meta["type"]
        account_df.attrs["account_category"] = acct_meta["category"]
        accounts[account_name] = account_df

    return accounts


# ---------------------------------------------------------------------------
# C.2  Rollforward
# ---------------------------------------------------------------------------

def fn_recalculate_account_rollforward(
    account_df: pd.DataFrame,
    account_type: str,
    start_period_index: int = 0,
) -> pd.DataFrame:
    """
    Recalculate opening and closing balances from a start period onward.

    Uses numpy cumsum for vectorized balance calculation.
    """
    if account_df is None or account_df.empty:
        print("fn_recalculate_account_rollforward: account_df is None or empty")
        return account_df

    n_periods = len(account_df.columns)
    if n_periods == 0:
        print("fn_recalculate_account_rollforward: account_df has no periods")
        return account_df

    start_idx = max(0, min(int(start_period_index), n_periods - 1))

    ob_ridx = account_df.index.get_loc("Opening Balance")
    cb_ridx = account_df.index.get_loc("Closing Balance")
    dr_ridx = account_df.index.get_loc("Debit")
    cr_ridx = account_df.index.get_loc("Credit")

    raw = account_df.values
    debits = raw[dr_ridx].astype("float64", copy=False)
    credits = raw[cr_ridx].astype("float64", copy=False)

    if account_type in ("Asset", "Expense"):
        net = debits - credits
    else:
        net = credits - debits

    if start_idx == 0:
        initial_bal = float(raw[ob_ridx, 0])
    else:
        initial_bal = float(raw[cb_ridx, start_idx - 1])

    closing_slice = initial_bal + np.cumsum(net[start_idx:])

    opening_slice = np.empty_like(closing_slice)
    opening_slice[0] = initial_bal
    if len(closing_slice) > 1:
        opening_slice[1:] = closing_slice[:-1]

    raw[ob_ridx, start_idx:] = opening_slice
    raw[cb_ridx, start_idx:] = closing_slice

    return account_df


# ---------------------------------------------------------------------------
# C.2b  Journal Entry Recording
# ---------------------------------------------------------------------------

def fn_record_journal_entry(
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    account_names_dict: Dict[str, Dict[str, str]],
    debit_account: str,
    credit_account: str,
    amount: float,
    period: str,
    description: str = "",
    reference: str = "",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]]]:
    """
    Record a double entry journal entry in the respective accounts.
    """
    if amount <= 0:
        print(f"fn_record_journal_entry: Amount must be positive, got {amount}")
        return accounts, journal

    if debit_account not in accounts:
        print(f"fn_record_journal_entry: Debit account '{debit_account}' not found")
        return accounts, journal

    if credit_account not in accounts:
        print(f"fn_record_journal_entry: Credit account '{credit_account}' not found")
        return accounts, journal

    if period not in accounts[debit_account].columns:
        print(f"fn_record_journal_entry: Period '{period}' not found in debit account columns")
        return accounts, journal

    if period not in accounts[credit_account].columns:
        print(f"fn_record_journal_entry: Period '{period}' not found in credit account columns")
        return accounts, journal

    accounts[debit_account].loc["Debit", period] += amount
    accounts[credit_account].loc["Credit", period] += amount

    debit_account_type = account_names_dict[debit_account]["type"]
    credit_account_type = account_names_dict[credit_account]["type"]

    periods = accounts[debit_account].columns.tolist()
    period_idx = periods.index(period)

    accounts[debit_account] = fn_recalculate_account_rollforward(
        account_df=accounts[debit_account],
        account_type=debit_account_type,
        start_period_index=period_idx,
    )
    accounts[credit_account] = fn_recalculate_account_rollforward(
        account_df=accounts[credit_account],
        account_type=credit_account_type,
        start_period_index=period_idx,
    )

    journal_entry = {
        "entry_id": len(journal) + 1,
        "period": period,
        "debit_account": debit_account,
        "credit_account": credit_account,
        "amount": amount,
        "description": description,
        "reference": reference,
        "timestamp": datetime.now().isoformat(),
    }
    journal.append(journal_entry)

    return accounts, journal


def fn_record_journal_entry_vectorized(
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    account_names_dict: Dict[str, Dict[str, str]],
    debit_account: str,
    credit_account: str,
    amounts: Union[float, pd.Series, List[float]],
    periods: Union[str, pd.Series, List[str]],
    description: str = "",
    reference: str = "",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]]]:
    """
    Record double entry journal entries supporting both single values and pd.Series.
    """
    if isinstance(amounts, (int, float)):
        amounts_series = pd.Series([amounts])
    elif isinstance(amounts, list):
        amounts_series = pd.Series(amounts)
    else:
        amounts_series = amounts

    if isinstance(periods, str):
        periods_series = pd.Series([periods])
    elif isinstance(periods, list):
        periods_series = pd.Series(periods)
    else:
        periods_series = periods

    if debit_account not in accounts:
        print(f"fn_record_journal_entry_vectorized: Debit account '{debit_account}' not found")
        return accounts, journal

    if credit_account not in accounts:
        print(f"fn_record_journal_entry_vectorized: Credit account '{credit_account}' not found")
        return accounts, journal

    debit_account_type = account_names_dict[debit_account]["type"]
    credit_account_type = account_names_dict[credit_account]["type"]
    touched_period_indices: List[int] = []
    debit_periods = accounts[debit_account].columns.tolist()

    for period, amount in zip(periods_series, amounts_series):
        period_str = str(period)
        amount_float = float(amount) if pd.notna(amount) else 0.0

        if amount_float <= 0:
            continue

        if period_str not in debit_periods:
            continue

        period_idx = debit_periods.index(period_str)
        touched_period_indices.append(period_idx)

        accounts[debit_account].loc["Debit", period_str] += amount_float
        accounts[credit_account].loc["Credit", period_str] += amount_float

        journal_entry = {
            "entry_id": len(journal) + 1,
            "period": period_str,
            "debit_account": debit_account,
            "credit_account": credit_account,
            "amount": amount_float,
            "description": description,
            "reference": reference,
            "timestamp": datetime.now().isoformat(),
        }
        journal.append(journal_entry)

    if touched_period_indices:
        start_idx = min(touched_period_indices)
        accounts[debit_account] = fn_recalculate_account_rollforward(
            account_df=accounts[debit_account],
            account_type=debit_account_type,
            start_period_index=start_idx,
        )
        accounts[credit_account] = fn_recalculate_account_rollforward(
            account_df=accounts[credit_account],
            account_type=credit_account_type,
            start_period_index=start_idx,
        )

    return accounts, journal


# ---------------------------------------------------------------------------
# C.3  Financial Statement Functions
# ---------------------------------------------------------------------------

def fn_initialize_financial_statement(
    statement_structure: Dict[str, Dict[str, List[str]]],
    period_ends: pd.Series,
) -> pd.DataFrame:
    """
    Initialize a financial statement DataFrame with line items as rows and periods as columns.
    """
    row_index = fn_build_financial_statement_row_index(statement_structure)

    if not row_index:
        print("fn_initialize_financial_statement: Could not build row index from structure")
        return pd.DataFrame()

    if period_ends is None or period_ends.empty:
        print("fn_initialize_financial_statement: period_ends cannot be None or empty")
        return pd.DataFrame()

    try:
        normalized_periods = pd.to_datetime(period_ends).dt.normalize()
        unique_periods = list(dict.fromkeys(normalized_periods.astype(str).tolist()))
    except Exception as e:
        print(f"fn_initialize_financial_statement: Error normalizing periods: {str(e)}")
        return pd.DataFrame()

    return pd.DataFrame(
        data=0.0,
        index=row_index,
        columns=unique_periods,
        dtype="float64",
    )


def fn_record_financial_statement_entry(
    statement_df: pd.DataFrame,
    line_item: str,
    period: str,
    amount: float,
    is_addition: bool = True,
) -> pd.DataFrame:
    """
    Record an entry in a financial statement line item.
    """
    if statement_df is None or statement_df.empty:
        print("fn_record_financial_statement_entry: statement_df is None or empty")
        return statement_df

    if line_item not in statement_df.index:
        print(f"fn_record_financial_statement_entry: Line item '{line_item}' not found in statement")
        return statement_df

    if period not in statement_df.columns:
        print(f"fn_record_financial_statement_entry: Period '{period}' not found in statement columns")
        return statement_df

    if is_addition:
        statement_df.loc[line_item, period] += amount
    else:
        statement_df.loc[line_item, period] -= amount

    return statement_df


def fn_record_financial_statement_entry_vectorized(
    statement_df: pd.DataFrame,
    line_item: str,
    periods: Union[str, pd.Series, List[str]],
    amounts: Union[float, pd.Series, List[float]],
    is_addition: bool = True,
) -> pd.DataFrame:
    """
    Record entries in a financial statement line item - supports pd.Series.
    """
    if statement_df is None or statement_df.empty:
        return statement_df

    if line_item not in statement_df.index:
        print(f"fn_record_financial_statement_entry_vectorized: Line item '{line_item}' not found")
        return statement_df

    if isinstance(amounts, (int, float)):
        amounts_series = pd.Series([amounts])
    elif isinstance(amounts, list):
        amounts_series = pd.Series(amounts)
    else:
        amounts_series = amounts

    if isinstance(periods, str):
        periods_series = pd.Series([periods])
    elif isinstance(periods, list):
        periods_series = pd.Series(periods)
    else:
        periods_series = periods

    for period, amount in zip(periods_series, amounts_series):
        period_str = str(period)
        amount_float = float(amount) if pd.notna(amount) else 0.0

        if period_str not in statement_df.columns:
            continue

        if is_addition:
            statement_df.loc[line_item, period_str] += amount_float
        else:
            statement_df.loc[line_item, period_str] -= amount_float

    return statement_df


def fn_create_all_financial_statements(
    balance_sheet_structure: Dict[str, Dict[str, List[str]]],
    income_statement_structure: Dict[str, Dict[str, List[str]]],
    cashflow_structure: Dict[str, Dict[str, List[str]]],
    period_ends: pd.Series,
) -> Dict[str, pd.DataFrame]:
    """
    Create all three financial statement DataFrames.
    """
    financial_statements: Dict[str, pd.DataFrame] = {}

    financial_statements["balance_sheet"] = fn_initialize_financial_statement(
        balance_sheet_structure, period_ends
    )

    financial_statements["income_statement"] = fn_initialize_financial_statement(
        income_statement_structure, period_ends
    )

    financial_statements["cashflow_statement"] = fn_initialize_financial_statement(
        cashflow_structure, period_ends
    )

    return financial_statements


# ---------------------------------------------------------------------------
# C.4  Integrated Entry and Balance Functions
# ---------------------------------------------------------------------------

def fn_resolve_signed_cashflow_amount(
    debit_account: str,
    credit_account: str,
    amount: float,
    cash_account_name: str = "Cash and Cash Equivalents",
) -> float:
    """
    Resolve signed cashflow amount from journal direction.
    """
    amount_abs = abs(float(amount))
    if amount_abs == 0.0:
        return 0.0

    if debit_account == cash_account_name and credit_account != cash_account_name:
        return amount_abs

    if credit_account == cash_account_name and debit_account != cash_account_name:
        return -amount_abs

    return 0.0


def fn_get_account_balance(
    accounts: Dict[str, pd.DataFrame],
    account_name: str,
    period: str,
    balance_type: str = "Closing Balance",
) -> Optional[float]:
    """
    Get the balance of a specific account for a given period.
    """
    if account_name not in accounts:
        print(f"fn_get_account_balance: Account '{account_name}' not found")
        return None

    account_df = accounts[account_name]
    if account_df is None or account_df.empty:
        print(f"fn_get_account_balance: Account '{account_name}' DataFrame is empty")
        return None

    if balance_type not in account_df.index:
        print(f"fn_get_account_balance: Balance type '{balance_type}' not found")
        return None

    if period not in account_df.columns:
        print(f"fn_get_account_balance: Period '{period}' not found")
        return None

    return float(account_df.loc[balance_type, period])


def fn_record_integrated_entry(
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    debit_account: str,
    credit_account: str,
    amount: float,
    period: str,
    income_statement_line_item: Optional[str] = None,
    balance_sheet_line_item: Optional[str] = None,
    cashflow_line_item: Optional[str] = None,
    description: str = "",
    reference: str = "",
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Record an integrated entry across accounts and financial statements.
    """
    accounts, journal = fn_record_journal_entry(
        accounts=accounts,
        journal=journal,
        account_names_dict=account_names_dict,
        debit_account=debit_account,
        credit_account=credit_account,
        amount=amount,
        period=period,
        description=description,
        reference=reference,
    )

    # Update income statement if line item provided
    if income_statement_line_item and "income_statement" in financial_statements:
        credit_account_type = account_names_dict.get(credit_account, {}).get("type", "")
        debit_account_type = account_names_dict.get(debit_account, {}).get("type", "")

        if credit_account_type == "Revenue":
            financial_statements["income_statement"] = fn_record_financial_statement_entry(
                financial_statements["income_statement"],
                income_statement_line_item,
                period,
                amount,
                is_addition=True,
            )
        elif debit_account_type == "Expense":
            financial_statements["income_statement"] = fn_record_financial_statement_entry(
                financial_statements["income_statement"],
                income_statement_line_item,
                period,
                amount,
                is_addition=True,
            )

    # Update balance sheet by synchronizing touched account closing balances.
    if "balance_sheet" in financial_statements:
        balance_sheet_df = financial_statements["balance_sheet"]
        touched_accounts = [debit_account, credit_account]

        for touched_account in touched_accounts:
            if touched_account not in balance_sheet_df.index:
                continue

            if touched_account not in accounts:
                continue

            account_df = accounts[touched_account]
            account_periods = account_df.columns.tolist()
            if period not in account_periods:
                continue

            start_idx = account_periods.index(period)
            for sync_period in account_periods[start_idx:]:
                if sync_period not in balance_sheet_df.columns:
                    continue

                closing_balance = fn_get_account_balance(
                    accounts=accounts,
                    account_name=touched_account,
                    period=sync_period,
                    balance_type="Closing Balance",
                )
                if closing_balance is not None:
                    balance_sheet_df.loc[touched_account, sync_period] = float(closing_balance)

        # Backward-compatible path for custom non-account mapping.
        if balance_sheet_line_item and balance_sheet_line_item not in touched_accounts:
            balance_sheet_df = fn_record_financial_statement_entry(
                balance_sheet_df,
                balance_sheet_line_item,
                period,
                amount,
                is_addition=True,
            )

        financial_statements["balance_sheet"] = balance_sheet_df

    # Update cashflow statement using signed cash direction.
    if cashflow_line_item and "cashflow_statement" in financial_statements:
        signed_cashflow_amount = fn_resolve_signed_cashflow_amount(
            debit_account=debit_account,
            credit_account=credit_account,
            amount=amount,
        )
        if signed_cashflow_amount != 0.0:
            cf_df = financial_statements["cashflow_statement"]
            if cashflow_line_item in cf_df.index and period in cf_df.columns:
                cf_df.loc[cashflow_line_item, period] += signed_cashflow_amount
                financial_statements["cashflow_statement"] = cf_df

    _latest_entry_id = ""
    if journal and isinstance(journal[-1], dict):
        _latest_entry_id = journal[-1].get("entry_id", "")

    _entry_name = (
        str(description or "").strip()
        or str(income_statement_line_item or "").strip()
        or str(cashflow_line_item or "").strip()
        or f"{debit_account} -> {credit_account}"
    )

    # Record trace row(s) for integrated scalar entries.
    if _is_financial_statement_trace_enabled(financial_statements):
        fn_record_batch_entry_financial_statement_trace(
            financial_statements=financial_statements,
            entry={
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": amount,
                "period": period,
                "income_statement_line_item": income_statement_line_item,
                "cashflow_line_item": cashflow_line_item,
                "description": description,
                "reference": reference,
                "entry_name": _entry_name,
                "entry_id": _latest_entry_id,
            },
            account_names_dict=account_names_dict,
            type_aware_is_posting=True,
        )

    return accounts, journal, financial_statements


# ---------------------------------------------------------------------------
# C.5  Batch Flush
# ---------------------------------------------------------------------------

def fn_flush_batch_entries(
    batch_entries: List[Dict[str, Any]],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    interparty_cash_name: Optional[str] = None,
    type_aware_is_posting: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Bulk-post accumulated journal entries and run rollforward once per account.

    This unified version supports both entity variants:

    * **LandCo** — pass ``interparty_cash_name="Cash and Cash Equivalents -
      Interparty Elimination"`` and ``type_aware_is_posting=True``.
    * **DevCo / AssetCo** — use the defaults (``None`` / ``False``).

    Parameters:
    -----------
    interparty_cash_name : Optional[str]
        When set, this cash account name is also recognised when determining
        cashflow sign (LandCo needs this for interparty elimination entries).
    type_aware_is_posting : bool
        When ``True``, income-statement sign is derived from the account-type
        direction (Revenue credited / Expense debited → positive; reversed →
        negative).  When ``False``, the amount is posted as-is (DevCo/AssetCo
        behaviour).
    """
    if not batch_entries:
        return accounts, journal, financial_statements

    # -- Period-to-column-index map (shared by all accounts). --
    _sample_acct_df = next(iter(accounts.values())) if accounts else pd.DataFrame()
    all_periods_list: List[str] = _sample_acct_df.columns.tolist()
    period_to_idx: Dict[str, int] = {p: i for i, p in enumerate(all_periods_list)}

    # -- Pre-compute row indices for every account (avoids repeated .loc). --
    _acct_dr_ridx: Dict[str, int] = {}
    _acct_cr_ridx: Dict[str, int] = {}
    for acct_name, acct_df in accounts.items():
        _acct_dr_ridx[acct_name] = acct_df.index.get_loc("Debit")
        _acct_cr_ridx[acct_name] = acct_df.index.get_loc("Credit")

    # -- Pre-aggregate: (account, period_idx) -> total debit / credit --
    dr_agg: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    cr_agg: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    cf_agg: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    is_agg: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))

    cash_name = "Cash and Cash Equivalents"
    has_cf = "cashflow_statement" in financial_statements
    has_is = "income_statement" in financial_statements

    # Single timestamp for the entire flush (avoid per-entry datetime.now).
    _ts = datetime.now().isoformat()
    _journal_start_id = len(journal) + 1
    _new_journal: List[Dict[str, Any]] = []
    _trace_enabled = _is_financial_statement_trace_enabled(financial_statements)

    for entry in batch_entries:
        debit_acct: str = entry["debit_account"]
        credit_acct: str = entry["credit_account"]
        amount: float = float(entry["amount"])
        period: str = entry["period"]

        if amount <= 0.0 or period not in period_to_idx:
            continue

        _next_entry_id = _journal_start_id + len(_new_journal)
        if _trace_enabled:
            _trace_entry = dict(entry)
            _trace_entry["entry_id"] = _next_entry_id

            if not str(_trace_entry.get("entry_name", "") or "").strip():
                _trace_entry["entry_name"] = (
                    str(_trace_entry.get("description", "") or "").strip()
                    or str(_trace_entry.get("income_statement_line_item", "") or "").strip()
                    or str(_trace_entry.get("cashflow_line_item", "") or "").strip()
                    or f"{debit_acct} -> {credit_acct}"
                )

            fn_record_batch_entry_financial_statement_trace(
                financial_statements=financial_statements,
                entry=_trace_entry,
                account_names_dict=account_names_dict,
                type_aware_is_posting=type_aware_is_posting,
                interparty_cash_name=interparty_cash_name,
            )

        p_idx: int = period_to_idx[period]

        if debit_acct in accounts:
            dr_agg[debit_acct][p_idx] += amount
        if credit_acct in accounts:
            cr_agg[credit_acct][p_idx] += amount

        # Cashflow: inline sign logic (avoids fn_resolve_signed_cashflow_amount call).
        cf_item: Optional[str] = entry.get("cashflow_line_item")
        if cf_item and has_cf:
            # Recognise both base and (optionally) interparty elimination cash accounts.
            _is_cash_dr = (debit_acct == cash_name)
            _is_cash_cr = (credit_acct == cash_name)
            if interparty_cash_name:
                _is_cash_dr = _is_cash_dr or (debit_acct == interparty_cash_name)
                _is_cash_cr = _is_cash_cr or (credit_acct == interparty_cash_name)

            if _is_cash_dr and not _is_cash_cr:
                cf_agg[cf_item][p_idx] += amount
            elif _is_cash_cr and not _is_cash_dr:
                cf_agg[cf_item][p_idx] -= amount

        # Income statement.
        is_item: Optional[str] = entry.get("income_statement_line_item")
        if is_item and has_is:
            if type_aware_is_posting:
                _cr_type = account_names_dict.get(credit_acct, {}).get("type", "")
                _dr_type = account_names_dict.get(debit_acct, {}).get("type", "")
                if _cr_type == "Revenue" or _dr_type == "Expense":
                    is_agg[is_item][p_idx] += amount
                elif _dr_type == "Revenue" or _cr_type == "Expense":
                    is_agg[is_item][p_idx] -= amount
                else:
                    is_agg[is_item][p_idx] += amount
            else:
                is_agg[is_item][p_idx] += amount

        _new_journal.append({
            "entry_id": _next_entry_id,
            "period": period,
            "debit_account": debit_acct,
            "credit_account": credit_acct,
            "amount": amount,
            "description": entry.get("description", ""),
            "reference": entry.get("reference", ""),
            "timestamp": _ts,
        })

    journal.extend(_new_journal)

    # -- Earliest-touched period per account (for rollforward range). --
    earliest_touched: Dict[str, int] = {}

    # -- Post aggregated debits to account numpy arrays. --
    for acct_name, period_map in dr_agg.items():
        raw = accounts[acct_name].values
        row = _acct_dr_ridx[acct_name]
        min_idx = None
        for p_idx, total in period_map.items():
            raw[row, p_idx] += total
            if min_idx is None or p_idx < min_idx:
                min_idx = p_idx
        if min_idx is not None:
            earliest_touched[acct_name] = min_idx

    # -- Post aggregated credits. --
    for acct_name, period_map in cr_agg.items():
        raw = accounts[acct_name].values
        row = _acct_cr_ridx[acct_name]
        min_idx = None
        for p_idx, total in period_map.items():
            raw[row, p_idx] += total
            if min_idx is None or p_idx < min_idx:
                min_idx = p_idx
        prev = earliest_touched.get(acct_name)
        if min_idx is not None and (prev is None or min_idx < prev):
            earliest_touched[acct_name] = min_idx

    # -- Post aggregated cashflow. --
    if has_cf and cf_agg:
        cf_df = financial_statements["cashflow_statement"]
        cf_raw = cf_df.values
        cf_row_map: Dict[str, int] = {}
        cf_periods = cf_df.columns.tolist()
        cf_p2i: Dict[str, int] = {p: i for i, p in enumerate(cf_periods)}
        for cf_item, period_map in cf_agg.items():
            if cf_item not in cf_df.index:
                continue
            if cf_item not in cf_row_map:
                cf_row_map[cf_item] = cf_df.index.get_loc(cf_item)
            row = cf_row_map[cf_item]
            for p_idx, total in period_map.items():
                p_str = all_periods_list[p_idx]
                if p_str in cf_p2i:
                    cf_raw[row, cf_p2i[p_str]] += total

    # -- Post aggregated income statement. --
    if has_is and is_agg:
        is_df = financial_statements["income_statement"]
        is_raw = is_df.values
        is_row_map: Dict[str, int] = {}
        is_periods = is_df.columns.tolist()
        is_p2i: Dict[str, int] = {p: i for i, p in enumerate(is_periods)}
        for is_item, period_map in is_agg.items():
            if is_item not in is_df.index:
                continue
            if is_item not in is_row_map:
                is_row_map[is_item] = is_df.index.get_loc(is_item)
            row = is_row_map[is_item]
            for p_idx, total in period_map.items():
                p_str = all_periods_list[p_idx]
                if p_str in is_p2i:
                    is_raw[row, is_p2i[p_str]] += total

    # -- Rollforward once per touched account from its earliest touched period. --
    for account_name, start_idx in earliest_touched.items():
        account_type = account_names_dict.get(account_name, {}).get("type", "Asset")
        accounts[account_name] = fn_recalculate_account_rollforward(
            account_df=accounts[account_name],
            account_type=account_type,
            start_period_index=start_idx,
        )

    # -- Sync balance sheet closing balances (vectorized per account). --
    if "balance_sheet" in financial_statements and earliest_touched:
        bs_df = financial_statements["balance_sheet"]
        bs_raw = bs_df.values
        bs_col_list = bs_df.columns.tolist()
        bs_p2i: Dict[str, int] = {p: i for i, p in enumerate(bs_col_list)}
        for account_name, start_idx in earliest_touched.items():
            if account_name not in bs_df.index or account_name not in accounts:
                continue
            bs_row = bs_df.index.get_loc(account_name)
            acct_raw = accounts[account_name].values
            cb_ridx = accounts[account_name].index.get_loc("Closing Balance")
            acct_periods = accounts[account_name].columns.tolist()
            n_acct = len(acct_periods)

            # Build aligned column-index array once, then copy via slice.
            _bs_col_indices = np.array(
                [bs_p2i[acct_periods[pi]] for pi in range(start_idx, n_acct)
                 if acct_periods[pi] in bs_p2i],
                dtype=np.intp,
            )
            # Source slice from account Closing Balance row.
            _src_indices = np.array(
                [pi for pi in range(start_idx, n_acct)
                 if acct_periods[pi] in bs_p2i],
                dtype=np.intp,
            )
            if _bs_col_indices.size > 0:
                bs_raw[bs_row, _bs_col_indices] = acct_raw[cb_ridx, _src_indices]
        financial_statements["balance_sheet"] = bs_df

    return accounts, journal, financial_statements


# ---------------------------------------------------------------------------
# C.5b  Index-Map Builder (for matrix-based flush)
# ---------------------------------------------------------------------------

def fn_build_flush_index_maps(
    accounts: Dict[str, pd.DataFrame],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """
    Pre-compute integer index mappings for the matrix-based flush path.

    Call this **once per entity model** (after account/statement creation,
    before the processing phases) and pass the result to
    ``fn_flush_matrix_entries``.

    Returns
    -------
    dict with keys:
        account_to_idx : Dict[str, int]
            Account name → integer index (for debit/credit arrays).
        period_to_idx : Dict[str, int]
            Period-end string → integer index.
        all_periods : List[str]
            Ordered period-end strings.
        n_accounts : int
        n_periods : int
        account_types : np.ndarray (int8, shape n_accounts)
            0 = Asset/Expense (debit-normal), 1 = Liability/Equity/Revenue (credit-normal).
        acct_dr_ridx : Dict[str, int]
            Account name → row index of "Debit" in account DataFrame.
        acct_cr_ridx : Dict[str, int]
            Account name → row index of "Credit" in account DataFrame.
        bs_row_map : Dict[str, int] or None
            Account name → BS row index (only accounts present in BS).
        bs_p2i : np.ndarray (intp, shape n_periods) or None
            Maps account period index → BS column index.  -1 if unmapped.
        cf_row_map : Dict[str, int] or None
            CF line item → CF row index.
        cf_p2i : np.ndarray (intp, shape n_periods) or None
            Maps account period index → CF column index.  -1 if unmapped.
        is_row_map : Dict[str, int] or None
            IS line item → IS row index.
        is_p2i : np.ndarray (intp, shape n_periods) or None
            Maps account period index → IS column index.  -1 if unmapped.
    """
    # -- Account index mapping --
    acct_names_list = list(accounts.keys())
    account_to_idx: Dict[str, int] = {n: i for i, n in enumerate(acct_names_list)}
    n_accounts = len(acct_names_list)

    # -- Period index mapping --
    _sample = next(iter(accounts.values())) if accounts else pd.DataFrame()
    all_periods: List[str] = _sample.columns.tolist() if not _sample.empty else []
    period_to_idx: Dict[str, int] = {p: i for i, p in enumerate(all_periods)}
    n_periods = len(all_periods)

    # -- Account types (0 = debit-normal, 1 = credit-normal) --
    account_types = np.zeros(n_accounts, dtype=np.int8)
    for i, name in enumerate(acct_names_list):
        atype = account_names_dict.get(name, {}).get("type", "Asset")
        if atype not in ("Asset", "Expense"):
            account_types[i] = 1

    # -- Row indices in account DataFrames --
    acct_dr_ridx: Dict[str, int] = {}
    acct_cr_ridx: Dict[str, int] = {}
    for name, df in accounts.items():
        acct_dr_ridx[name] = df.index.get_loc("Debit")
        acct_cr_ridx[name] = df.index.get_loc("Credit")

    # -- Balance sheet mapping --
    bs_row_map: Optional[Dict[str, int]] = None
    bs_p2i_arr: Optional[np.ndarray] = None
    if "balance_sheet" in financial_statements:
        bs_df = financial_statements["balance_sheet"]
        bs_col_list = bs_df.columns.tolist()
        _bs_col_map = {p: i for i, p in enumerate(bs_col_list)}
        bs_row_map = {}
        for name in acct_names_list:
            if name in bs_df.index:
                bs_row_map[name] = bs_df.index.get_loc(name)
        bs_p2i_arr = np.full(n_periods, -1, dtype=np.intp)
        for pi, p_str in enumerate(all_periods):
            if p_str in _bs_col_map:
                bs_p2i_arr[pi] = _bs_col_map[p_str]

    # -- Cashflow statement mapping --
    cf_row_map: Optional[Dict[str, int]] = None
    cf_p2i_arr: Optional[np.ndarray] = None
    if "cashflow_statement" in financial_statements:
        cf_df = financial_statements["cashflow_statement"]
        cf_col_list = cf_df.columns.tolist()
        _cf_col_map = {p: i for i, p in enumerate(cf_col_list)}
        cf_row_map = {label: cf_df.index.get_loc(label) for label in cf_df.index if label in cf_df.index}
        cf_p2i_arr = np.full(n_periods, -1, dtype=np.intp)
        for pi, p_str in enumerate(all_periods):
            if p_str in _cf_col_map:
                cf_p2i_arr[pi] = _cf_col_map[p_str]

    # -- Income statement mapping --
    is_row_map: Optional[Dict[str, int]] = None
    is_p2i_arr: Optional[np.ndarray] = None
    if "income_statement" in financial_statements:
        is_df = financial_statements["income_statement"]
        is_col_list = is_df.columns.tolist()
        _is_col_map = {p: i for i, p in enumerate(is_col_list)}
        is_row_map = {label: is_df.index.get_loc(label) for label in is_df.index if label in is_df.index}
        is_p2i_arr = np.full(n_periods, -1, dtype=np.intp)
        for pi, p_str in enumerate(all_periods):
            if p_str in _is_col_map:
                is_p2i_arr[pi] = _is_col_map[p_str]

    return {
        "account_to_idx": account_to_idx,
        "period_to_idx": period_to_idx,
        "all_periods": all_periods,
        "n_accounts": n_accounts,
        "n_periods": n_periods,
        "account_types": account_types,
        "acct_dr_ridx": acct_dr_ridx,
        "acct_cr_ridx": acct_cr_ridx,
        "bs_row_map": bs_row_map,
        "bs_p2i": bs_p2i_arr,
        "cf_row_map": cf_row_map,
        "cf_p2i": cf_p2i_arr,
        "is_row_map": is_row_map,
        "is_p2i": is_p2i_arr,
    }


# ---------------------------------------------------------------------------
# C.5c  Matrix-Based Flush
# ---------------------------------------------------------------------------

# Structured dtype for matrix entries.  Each row represents one journal entry.
_ENTRY_DTYPE = np.dtype([
    ("debit_acct_idx", np.int32),
    ("credit_acct_idx", np.int32),
    ("amount", np.float64),
    ("period_idx", np.int32),
    ("is_line_item_idx", np.int32),   # -1 = no IS posting
    ("cf_line_item_idx", np.int32),   # -1 = no CF posting
    ("asset_idx", np.int32),          # for reference construction
    ("period_col_idx", np.int32),     # for reference construction
])


def fn_flush_matrix_entries(
    entries: np.ndarray,
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    index_maps: Dict[str, Any],
    reference_prefix: str = "",
    line_item_name: str = "",
    asset_labels: Optional[List[str]] = None,
    period_col_labels: Optional[List[str]] = None,
    interparty_cash_name: Optional[str] = None,
    type_aware_is_posting: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    High-performance flush using pre-indexed structured numpy arrays.

    Parameters
    ----------
    entries : np.ndarray
        Structured array with dtype ``_ENTRY_DTYPE``.  Each row is one entry.
        Use ``fn_allocate_entry_array`` to create and ``fn_trim_entry_array``
        to trim unused rows.
    index_maps : dict
        Pre-computed maps from ``fn_build_flush_index_maps``.
    reference_prefix : str
        Prefix for journal reference strings (e.g. "DC-LA").
    line_item_name : str
        Human-readable name for journal descriptions.
    asset_labels : list of str, optional
        Labels for asset_idx values (for description/reference strings).
    period_col_labels : list of str, optional
        Labels for period_col_idx values (for reference strings).
    interparty_cash_name : str, optional
        Additional cash account name for CF sign resolution (LandCo).
    type_aware_is_posting : bool
        Revenue/Expense-aware IS sign (LandCo = True, DevCo/AssetCo = False).
    """
    if entries is None or len(entries) == 0:
        return accounts, journal, financial_statements

    # Unpack index maps.
    account_to_idx = index_maps["account_to_idx"]
    all_periods = index_maps["all_periods"]
    n_periods = index_maps["n_periods"]
    n_accounts = index_maps["n_accounts"]
    account_types = index_maps["account_types"]
    acct_dr_ridx = index_maps["acct_dr_ridx"]
    acct_cr_ridx = index_maps["acct_cr_ridx"]

    # Reverse mapping for account names.
    idx_to_account = {v: k for k, v in account_to_idx.items()}

    # Extract columns from structured array.
    dr_idx = entries["debit_acct_idx"]
    cr_idx = entries["credit_acct_idx"]
    amounts = entries["amount"]
    p_idx = entries["period_idx"]
    is_idx = entries["is_line_item_idx"]
    cf_idx = entries["cf_line_item_idx"]

    # Filter valid entries (amount > 0, period in range).
    valid = (amounts > 0.0) & (p_idx >= 0) & (p_idx < n_periods)
    if not np.any(valid):
        return accounts, journal, financial_statements

    dr_v = dr_idx[valid]
    cr_v = cr_idx[valid]
    amt_v = amounts[valid]
    p_v = p_idx[valid]
    is_v = is_idx[valid]
    cf_v = cf_idx[valid]

    n_valid = int(valid.sum())

    _asset_indices_valid = entries["asset_idx"][valid]

    # ------------------------------------------------------------------
    # 1. Aggregate debits and credits per (account, period) via np.add.at
    # ------------------------------------------------------------------
    # Build 2D aggregation arrays: (n_accounts, n_periods)
    dr_agg_2d = np.zeros((n_accounts, n_periods), dtype=np.float64)
    cr_agg_2d = np.zeros((n_accounts, n_periods), dtype=np.float64)

    np.add.at(dr_agg_2d, (dr_v, p_v), amt_v)
    np.add.at(cr_agg_2d, (cr_v, p_v), amt_v)

    # ------------------------------------------------------------------
    # 2. Post aggregated debits/credits to account DataFrames
    # ------------------------------------------------------------------
    earliest_touched: Dict[str, int] = {}
    acct_names_list = list(accounts.keys())

    for acct_i, acct_name in enumerate(acct_names_list):
        dr_row = dr_agg_2d[acct_i]
        cr_row = cr_agg_2d[acct_i]
        has_dr = np.any(dr_row > 0.0)
        has_cr = np.any(cr_row > 0.0)
        if not has_dr and not has_cr:
            continue

        raw = accounts[acct_name].values
        if has_dr:
            raw[acct_dr_ridx[acct_name]] += dr_row
            first_dr = int(np.argmax(dr_row > 0.0))
            earliest_touched[acct_name] = first_dr
        if has_cr:
            raw[acct_cr_ridx[acct_name]] += cr_row
            first_cr = int(np.argmax(cr_row > 0.0))
            prev = earliest_touched.get(acct_name)
            if prev is None or first_cr < prev:
                earliest_touched[acct_name] = first_cr

    # ------------------------------------------------------------------
    # 3. Post aggregated cashflow entries
    # ------------------------------------------------------------------
    cf_row_map = index_maps.get("cf_row_map")
    cf_p2i = index_maps.get("cf_p2i")
    has_cf = cf_row_map is not None and cf_p2i is not None

    if has_cf:
        cf_df = financial_statements["cashflow_statement"]
        cf_raw = cf_df.values

        # Resolve cash account indices.
        cash_acct_idx = account_to_idx.get("Cash and Cash Equivalents", -1)
        ip_cash_idx = account_to_idx.get(interparty_cash_name, -1) if interparty_cash_name else -1

        # Entries where CF line item is set.
        cf_mask = cf_v >= 0
        if np.any(cf_mask):
            _cf_dr = dr_v[cf_mask]
            _cf_cr = cr_v[cf_mask]
            _cf_amt = amt_v[cf_mask]
            _cf_p = p_v[cf_mask]
            _cf_items = cf_v[cf_mask]

            # Determine sign: debit cash → positive, credit cash → negative.
            is_cash_dr = (_cf_dr == cash_acct_idx)
            is_cash_cr = (_cf_cr == cash_acct_idx)
            if ip_cash_idx >= 0:
                is_cash_dr = is_cash_dr | (_cf_dr == ip_cash_idx)
                is_cash_cr = is_cash_cr | (_cf_cr == ip_cash_idx)

            cf_signed = np.where(
                is_cash_dr & ~is_cash_cr, _cf_amt,
                np.where(is_cash_cr & ~is_cash_dr, -_cf_amt, 0.0)
            )

            # Aggregate per (cf_item, period) and post.
            cf_agg_2d = np.zeros((cf_raw.shape[0], cf_raw.shape[1]), dtype=np.float64)
            # Map period indices to CF column indices.
            _cf_col = cf_p2i[_cf_p]
            _valid_cf = (_cf_col >= 0) & (cf_signed != 0.0)
            if np.any(_valid_cf):
                np.add.at(cf_agg_2d, (_cf_items[_valid_cf], _cf_col[_valid_cf]), cf_signed[_valid_cf])
                cf_raw += cf_agg_2d

    # ------------------------------------------------------------------
    # 4. Post aggregated income statement entries
    # ------------------------------------------------------------------
    is_row_map = index_maps.get("is_row_map")
    is_p2i = index_maps.get("is_p2i")
    has_is = is_row_map is not None and is_p2i is not None

    if has_is:
        is_df = financial_statements["income_statement"]
        is_raw = is_df.values

        is_mask = is_v >= 0
        if np.any(is_mask):
            _is_dr = dr_v[is_mask]
            _is_cr = cr_v[is_mask]
            _is_amt = amt_v[is_mask]
            _is_p = p_v[is_mask]
            _is_items = is_v[is_mask]

            if type_aware_is_posting:
                # Determine sign from account types.
                _dr_types = account_types[_is_dr]  # 0=Asset/Expense, 1=Liab/Eq/Rev
                _cr_types = account_types[_is_cr]
                # Revenue credited or Expense debited → positive.
                # Revenue debited or Expense credited → negative.
                is_signed = np.where(
                    (_cr_types == 1) | (_dr_types == 0),   # normal direction
                    _is_amt,
                    np.where(
                        (_dr_types == 1) | (_cr_types == 0),  # reversed direction
                        -_is_amt,
                        _is_amt,
                    )
                )
            else:
                is_signed = _is_amt

            is_agg_2d = np.zeros_like(is_raw, dtype=np.float64)
            _is_col = is_p2i[_is_p]
            _valid_is = (_is_col >= 0) & (is_signed != 0.0)
            if np.any(_valid_is):
                np.add.at(is_agg_2d, (_is_items[_valid_is], _is_col[_valid_is]), is_signed[_valid_is])
                is_raw += is_agg_2d

    # ------------------------------------------------------------------
    # 5. Rollforward touched accounts
    # ------------------------------------------------------------------
    for account_name, start_idx in earliest_touched.items():
        account_type = account_names_dict.get(account_name, {}).get("type", "Asset")
        accounts[account_name] = fn_recalculate_account_rollforward(
            account_df=accounts[account_name],
            account_type=account_type,
            start_period_index=start_idx,
        )

    # ------------------------------------------------------------------
    # 6. Sync balance sheet closing balances (vectorized)
    # ------------------------------------------------------------------
    bs_row_map = index_maps.get("bs_row_map")
    bs_p2i = index_maps.get("bs_p2i")
    if bs_row_map is not None and bs_p2i is not None and earliest_touched:
        bs_df = financial_statements["balance_sheet"]
        bs_raw = bs_df.values
        for account_name, start_idx in earliest_touched.items():
            if account_name not in bs_row_map:
                continue
            bs_row = bs_row_map[account_name]
            acct_raw = accounts[account_name].values
            cb_ridx = accounts[account_name].index.get_loc("Closing Balance")
            n_acct = len(all_periods)
            if start_idx < n_acct:
                _bs_cols = bs_p2i[start_idx:n_acct]
                _valid_mask = _bs_cols >= 0
                if np.any(_valid_mask):
                    _src_range = np.arange(start_idx, n_acct)
                    bs_raw[bs_row, _bs_cols[_valid_mask]] = acct_raw[cb_ridx, _src_range[_valid_mask]]
        financial_statements["balance_sheet"] = bs_df

    # ------------------------------------------------------------------
    # 7. Build journal entries (single DataFrame construction)
    # ------------------------------------------------------------------
    _ts = datetime.now().isoformat()
    _journal_start_id = len(journal) + 1

    # Build arrays for journal columns.
    a_idx = _asset_indices_valid
    pc_idx = entries["period_col_idx"][valid]

    j_periods = [all_periods[int(p)] for p in p_v]
    j_dr_names = [idx_to_account.get(int(d), "") for d in dr_v]
    j_cr_names = [idx_to_account.get(int(c), "") for c in cr_v]
    j_amounts = amt_v.tolist()

    # Build description and reference strings.
    if asset_labels and period_col_labels:
        j_descriptions = [
            f"{line_item_name} - Asset {asset_labels[int(ai)]}"
            for ai in a_idx
        ]
        j_references = [
            f"{reference_prefix}-{asset_labels[int(ai)]}-{period_col_labels[int(pi)]}"
            for ai, pi in zip(a_idx, pc_idx)
        ]
    else:
        j_descriptions = [line_item_name] * n_valid
        j_references = [reference_prefix] * n_valid

    j_entry_names = [
        (str(line_item_name or "").strip() or str(j_descriptions[i]).strip() or "Journal Entry")
        for i in range(n_valid)
    ]
    j_entry_ids = [_journal_start_id + i for i in range(n_valid)]

    if _is_financial_statement_trace_enabled(financial_statements):
        fn_record_matrix_entries_financial_statement_trace(
            financial_statements=financial_statements,
            index_maps=index_maps,
            debit_indices=dr_v,
            credit_indices=cr_v,
            amounts=amt_v,
            period_indices=p_v,
            is_line_item_indices=is_v,
            cf_line_item_indices=cf_v,
            account_types=account_types,
            all_periods=all_periods,
            idx_to_account=idx_to_account,
            type_aware_is_posting=type_aware_is_posting,
            interparty_cash_name=interparty_cash_name,
            asset_indices=_asset_indices_valid,
            asset_labels=asset_labels,
            entry_names=j_entry_names,
            entry_descriptions=j_descriptions,
            reference_ids=j_references,
            journal_entry_ids=j_entry_ids,
        )

    new_journal = [
        {
            "entry_id": j_entry_ids[i],
            "period": j_periods[i],
            "debit_account": j_dr_names[i],
            "credit_account": j_cr_names[i],
            "amount": j_amounts[i],
            "description": j_descriptions[i],
            "reference": j_references[i],
            "timestamp": _ts,
        }
        for i in range(n_valid)
    ]
    journal.extend(new_journal)

    return accounts, journal, financial_statements


def fn_flush_matrix_entries_multi(
    entry_batches: List[Dict[str, Any]],
    accounts: Dict[str, pd.DataFrame],
    journal: List[Dict[str, Any]],
    financial_statements: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
    index_maps: Dict[str, Any],
    interparty_cash_name: Optional[str] = None,
    type_aware_is_posting: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    """
    Flush multiple batches of matrix entries with a **single** rollforward.

    Semantically identical to calling ``fn_flush_matrix_entries`` once per
    batch, but avoids redundant per-batch account rollforward / BS-sync
    recomputation.  With *N* batches touching the same accounts, this
    reduces rollforward calls from *N × k* to *k* (once per account).

    Parameters
    ----------
    entry_batches : list of dict
        Each dict must have keys ``entries`` (``_ENTRY_DTYPE`` array),
        ``reference_prefix``, ``line_item_name``, ``asset_labels``,
        ``period_col_labels``.
    interparty_cash_name, type_aware_is_posting :
        Applied uniformly to all batches (same semantics as
        ``fn_flush_matrix_entries``).
    """
    if not entry_batches:
        return accounts, journal, financial_statements

    # --- filter to non-empty batches and record sizes for journal pass ----
    non_empty: List[Dict[str, Any]] = []
    batch_sizes: List[int] = []
    for b in entry_batches:
        e = b["entries"]
        if e is not None and len(e) > 0:
            non_empty.append(b)
            batch_sizes.append(len(e))

    if not non_empty:
        return accounts, journal, financial_statements

    all_entries = np.concatenate([b["entries"] for b in non_empty])
    if len(all_entries) == 0:
        return accounts, journal, financial_statements

    # --- unpack index maps ------------------------------------------------
    account_to_idx = index_maps["account_to_idx"]
    all_periods = index_maps["all_periods"]
    n_periods = index_maps["n_periods"]
    n_accounts = index_maps["n_accounts"]
    account_types = index_maps["account_types"]
    acct_dr_ridx = index_maps["acct_dr_ridx"]
    acct_cr_ridx = index_maps["acct_cr_ridx"]

    idx_to_account = {v: k for k, v in account_to_idx.items()}

    # --- extract columns from concatenated array --------------------------
    dr_idx = all_entries["debit_acct_idx"]
    cr_idx = all_entries["credit_acct_idx"]
    amounts = all_entries["amount"]
    p_idx = all_entries["period_idx"]
    is_idx = all_entries["is_line_item_idx"]
    cf_idx = all_entries["cf_line_item_idx"]

    valid = (amounts > 0.0) & (p_idx >= 0) & (p_idx < n_periods)
    if not np.any(valid):
        return accounts, journal, financial_statements

    dr_v = dr_idx[valid]
    cr_v = cr_idx[valid]
    amt_v = amounts[valid]
    p_v = p_idx[valid]
    is_v = is_idx[valid]
    cf_v = cf_idx[valid]

    # ------------------------------------------------------------------
    # 1. Aggregate debits / credits per (account, period)
    # ------------------------------------------------------------------
    dr_agg_2d = np.zeros((n_accounts, n_periods), dtype=np.float64)
    cr_agg_2d = np.zeros((n_accounts, n_periods), dtype=np.float64)
    np.add.at(dr_agg_2d, (dr_v, p_v), amt_v)
    np.add.at(cr_agg_2d, (cr_v, p_v), amt_v)

    # ------------------------------------------------------------------
    # 2. Post aggregated dr / cr to account DataFrames
    # ------------------------------------------------------------------
    earliest_touched: Dict[str, int] = {}
    acct_names_list = list(accounts.keys())

    for acct_i, acct_name in enumerate(acct_names_list):
        dr_row = dr_agg_2d[acct_i]
        cr_row = cr_agg_2d[acct_i]
        has_dr = np.any(dr_row > 0.0)
        has_cr = np.any(cr_row > 0.0)
        if not has_dr and not has_cr:
            continue
        raw = accounts[acct_name].values
        if has_dr:
            raw[acct_dr_ridx[acct_name]] += dr_row
            first_dr = int(np.argmax(dr_row > 0.0))
            earliest_touched[acct_name] = first_dr
        if has_cr:
            raw[acct_cr_ridx[acct_name]] += cr_row
            first_cr = int(np.argmax(cr_row > 0.0))
            prev = earliest_touched.get(acct_name)
            if prev is None or first_cr < prev:
                earliest_touched[acct_name] = first_cr

    # ------------------------------------------------------------------
    # 3. Post aggregated cashflow entries
    # ------------------------------------------------------------------
    cf_row_map = index_maps.get("cf_row_map")
    cf_p2i = index_maps.get("cf_p2i")
    has_cf = cf_row_map is not None and cf_p2i is not None

    if has_cf:
        cf_df = financial_statements["cashflow_statement"]
        cf_raw = cf_df.values

        cash_acct_idx = account_to_idx.get("Cash and Cash Equivalents", -1)
        ip_cash_idx = (
            account_to_idx.get(interparty_cash_name, -1) if interparty_cash_name else -1
        )

        cf_mask = cf_v >= 0
        if np.any(cf_mask):
            _cf_dr = dr_v[cf_mask]
            _cf_cr = cr_v[cf_mask]
            _cf_amt = amt_v[cf_mask]
            _cf_p = p_v[cf_mask]
            _cf_items = cf_v[cf_mask]

            is_cash_dr = (_cf_dr == cash_acct_idx)
            is_cash_cr = (_cf_cr == cash_acct_idx)
            if ip_cash_idx >= 0:
                is_cash_dr = is_cash_dr | (_cf_dr == ip_cash_idx)
                is_cash_cr = is_cash_cr | (_cf_cr == ip_cash_idx)

            cf_signed = np.where(
                is_cash_dr & ~is_cash_cr, _cf_amt,
                np.where(is_cash_cr & ~is_cash_dr, -_cf_amt, 0.0),
            )

            cf_agg_2d = np.zeros((cf_raw.shape[0], cf_raw.shape[1]), dtype=np.float64)
            _cf_col = cf_p2i[_cf_p]
            _valid_cf = (_cf_col >= 0) & (cf_signed != 0.0)
            if np.any(_valid_cf):
                np.add.at(
                    cf_agg_2d,
                    (_cf_items[_valid_cf], _cf_col[_valid_cf]),
                    cf_signed[_valid_cf],
                )
                cf_raw += cf_agg_2d

    # ------------------------------------------------------------------
    # 4. Post aggregated income statement entries
    # ------------------------------------------------------------------
    is_row_map = index_maps.get("is_row_map")
    is_p2i = index_maps.get("is_p2i")
    has_is = is_row_map is not None and is_p2i is not None

    if has_is:
        is_df = financial_statements["income_statement"]
        is_raw = is_df.values

        is_mask = is_v >= 0
        if np.any(is_mask):
            _is_dr = dr_v[is_mask]
            _is_cr = cr_v[is_mask]
            _is_amt = amt_v[is_mask]
            _is_p = p_v[is_mask]
            _is_items = is_v[is_mask]

            if type_aware_is_posting:
                _dr_types = account_types[_is_dr]
                _cr_types = account_types[_is_cr]
                is_signed = np.where(
                    (_cr_types == 1) | (_dr_types == 0),
                    _is_amt,
                    np.where(
                        (_dr_types == 1) | (_cr_types == 0),
                        -_is_amt,
                        _is_amt,
                    ),
                )
            else:
                is_signed = _is_amt

            is_agg_2d = np.zeros_like(is_raw, dtype=np.float64)
            _is_col = is_p2i[_is_p]
            _valid_is = (_is_col >= 0) & (is_signed != 0.0)
            if np.any(_valid_is):
                np.add.at(
                    is_agg_2d,
                    (_is_items[_valid_is], _is_col[_valid_is]),
                    is_signed[_valid_is],
                )
                is_raw += is_agg_2d

    # ------------------------------------------------------------------
    # 5. Rollforward touched accounts — ONCE
    # ------------------------------------------------------------------
    for account_name, start_idx in earliest_touched.items():
        account_type = account_names_dict.get(account_name, {}).get("type", "Asset")
        accounts[account_name] = fn_recalculate_account_rollforward(
            account_df=accounts[account_name],
            account_type=account_type,
            start_period_index=start_idx,
        )

    # ------------------------------------------------------------------
    # 6. Sync balance sheet closing balances — ONCE
    # ------------------------------------------------------------------
    bs_row_map = index_maps.get("bs_row_map")
    bs_p2i = index_maps.get("bs_p2i")
    if bs_row_map is not None and bs_p2i is not None and earliest_touched:
        bs_df = financial_statements["balance_sheet"]
        bs_raw = bs_df.values
        for account_name, start_idx in earliest_touched.items():
            if account_name not in bs_row_map:
                continue
            bs_row = bs_row_map[account_name]
            acct_raw = accounts[account_name].values
            cb_ridx = accounts[account_name].index.get_loc("Closing Balance")
            n_acct = len(all_periods)
            if start_idx < n_acct:
                _bs_cols = bs_p2i[start_idx:n_acct]
                _valid_mask = _bs_cols >= 0
                if np.any(_valid_mask):
                    _src_range = np.arange(start_idx, n_acct)
                    bs_raw[bs_row, _bs_cols[_valid_mask]] = acct_raw[
                        cb_ridx, _src_range[_valid_mask]
                    ]
        financial_statements["balance_sheet"] = bs_df

    # ------------------------------------------------------------------
    # 7. Build journal entries — per batch (preserves per-item labels)
    # ------------------------------------------------------------------
    _ts = datetime.now().isoformat()
    _trace_enabled = _is_financial_statement_trace_enabled(financial_statements)
    offset = 0
    for bi, batch in enumerate(non_empty):
        batch_n = batch_sizes[bi]
        batch_valid = valid[offset : offset + batch_n]
        offset += batch_n

        if not np.any(batch_valid):
            continue

        b_entries = batch["entries"][batch_valid]
        b_dr = b_entries["debit_acct_idx"]
        b_cr = b_entries["credit_acct_idx"]
        b_amt = b_entries["amount"]
        b_p = b_entries["period_idx"]
        b_a_idx = b_entries["asset_idx"]
        b_pc_idx = b_entries["period_col_idx"]

        _ref = batch["reference_prefix"]
        _name = batch["line_item_name"]
        _a_labels = batch.get("asset_labels")
        _p_labels = batch.get("period_col_labels")

        n_bv = len(b_entries)
        _journal_start_id = len(journal) + 1

        j_periods = [all_periods[int(p)] for p in b_p]
        j_dr_names = [idx_to_account.get(int(d), "") for d in b_dr]
        j_cr_names = [idx_to_account.get(int(c), "") for c in b_cr]
        j_amounts = b_amt.tolist()

        if _a_labels and _p_labels:
            j_descriptions = [
                f"{_name} - Asset {_a_labels[int(ai)]}" for ai in b_a_idx
            ]
            j_references = [
                f"{_ref}-{_a_labels[int(ai)]}-{_p_labels[int(pi)]}"
                for ai, pi in zip(b_a_idx, b_pc_idx)
            ]
        else:
            j_descriptions = [_name] * n_bv
            j_references = [_ref] * n_bv

        j_entry_names = [
            (str(_name or "").strip() or str(j_descriptions[i]).strip() or "Journal Entry")
            for i in range(n_bv)
        ]
        j_entry_ids = [_journal_start_id + i for i in range(n_bv)]

        if _trace_enabled:
            fn_record_matrix_entries_financial_statement_trace(
                financial_statements=financial_statements,
                index_maps=index_maps,
                debit_indices=b_dr,
                credit_indices=b_cr,
                amounts=b_amt,
                period_indices=b_p,
                is_line_item_indices=b_entries["is_line_item_idx"],
                cf_line_item_indices=b_entries["cf_line_item_idx"],
                account_types=account_types,
                all_periods=all_periods,
                idx_to_account=idx_to_account,
                type_aware_is_posting=type_aware_is_posting,
                interparty_cash_name=interparty_cash_name,
                asset_indices=b_a_idx,
                asset_labels=_a_labels,
                entry_names=j_entry_names,
                entry_descriptions=j_descriptions,
                reference_ids=j_references,
                journal_entry_ids=j_entry_ids,
            )

        new_journal = [
            {
                "entry_id": j_entry_ids[i],
                "period": j_periods[i],
                "debit_account": j_dr_names[i],
                "credit_account": j_cr_names[i],
                "amount": j_amounts[i],
                "description": j_descriptions[i],
                "reference": j_references[i],
                "timestamp": _ts,
            }
            for i in range(n_bv)
        ]
        journal.extend(new_journal)

    return accounts, journal, financial_statements


def fn_allocate_entry_array(max_entries: int) -> np.ndarray:
    """Allocate a pre-sized structured array for matrix entries."""
    return np.zeros(max_entries, dtype=_ENTRY_DTYPE)


def fn_trim_entry_array(entries: np.ndarray, count: int) -> np.ndarray:
    """Return the first *count* rows of *entries*."""
    return entries[:count]


# ---------------------------------------------------------------------------
# C.6  Balance Propagation
# ---------------------------------------------------------------------------

def fn_propagate_opening_balances(
    accounts: Dict[str, pd.DataFrame],
    account_names_dict: Dict[str, Dict[str, str]],
) -> Dict[str, pd.DataFrame]:
    """
    Propagate closing balances to opening balances for subsequent periods.
    """
    for account_name, account_df in accounts.items():
        if account_df is None or account_df.empty:
            continue

        periods = account_df.columns.tolist()
        account_type = account_names_dict.get(account_name, {}).get("type", "Asset")

        for i, period in enumerate(periods):
            opening_bal = account_df.loc["Opening Balance", period]
            total_debit = account_df.loc["Debit", period]
            total_credit = account_df.loc["Credit", period]

            if account_type in ["Asset", "Expense"]:
                closing_bal = opening_bal + total_debit - total_credit
            else:
                closing_bal = opening_bal - total_debit + total_credit

            account_df.loc["Closing Balance", period] = closing_bal

            if i < len(periods) - 1:
                next_period = periods[i + 1]
                account_df.loc["Opening Balance", next_period] = closing_bal

        accounts[account_name] = account_df

    return accounts
