"""Real transaction data: loading and account-history feature derivation.

Source is the UCI Online Retail II dataset, a UK based online retailer, roughly
1.07 million invoice lines aggregated to 53,628 invoices over 2009 to 2011.

Every account level feature is computed from *prior* transactions only. Using
the full history including the current row would leak information the model
would not have had at authorisation time and would flatter the scores.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).parent / "data" / "transactions.parquet"

MERCHANT_HOME = "United Kingdom"

SOURCE_NAME = "UCI Online Retail II"
SOURCE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"


def load_raw() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"{DATA_PATH} is missing. Rebuild it with tools/build_real_dataset.py."
        )
    return pd.read_parquet(DATA_PATH)


def derive_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add per account history features, using prior rows only."""
    if df.empty:
        return _empty_derived()

    out = df.sort_values("timestamp").reset_index(drop=True).copy()
    g = out.groupby("customer_id", sort=False)

    # Prior activity counts. cumcount is already exclusive of the current row.
    out["prior_txns"] = g.cumcount()

    # Expanding mean and standard deviation over prior rows only.
    out["acct_avg_amount"] = (
        g["amount"].apply(lambda s: s.shift().expanding().mean()).reset_index(level=0, drop=True)
    )
    out["acct_std_amount"] = (
        g["amount"].apply(lambda s: s.shift().expanding().std()).reset_index(level=0, drop=True)
    )

    # A first ever transaction has no baseline. Fall back to the population
    # median so the amount factor stays neutral rather than firing spuriously.
    pop_median = float(out["amount"].median())
    out["acct_avg_amount"] = out["acct_avg_amount"].fillna(pop_median)
    out["acct_std_amount"] = out["acct_std_amount"].fillna(out["acct_std_amount"].median()).fillna(1.0)

    # Prior cancellations, exclusive of the current row.
    out["prior_cancellations"] = (
        g["is_cancellation"].apply(lambda s: s.shift().astype("float64").fillna(0.0).cumsum())
        .reset_index(level=0, drop=True).fillna(0).astype(int)
    )

    # Account tenure in days since the account's first seen transaction.
    first_seen = g["timestamp"].transform("min")
    out["account_age_days"] = (out["timestamp"] - first_seen).dt.total_seconds().div(86400).round().astype(int)

    # Transactions by the same account in the preceding 24 hours.
    out["txns_24h"] = _rolling_24h(out)

    out["hour"] = out["timestamp"].dt.hour
    out["is_guest"] = out["customer_id"].eq("GUEST")
    out["cross_border"] = out["country"].ne(MERCHANT_HOME)
    out["account_id"] = out["customer_id"]

    # Guest checkouts carry no customer id, so the source lumps them all under a
    # single placeholder. Treating that placeholder as one account would invent
    # a history that does not exist and would report absurd velocities. A guest
    # transaction has no account behind it, so its history features are zeroed
    # and the guest factor itself carries the signal.
    guest = out["is_guest"]
    if guest.any():
        out.loc[guest, ["prior_txns", "prior_cancellations", "account_age_days", "txns_24h"]] = 0
        out.loc[guest, "acct_avg_amount"] = pop_median
        out.loc[guest, "acct_std_amount"] = float(out.loc[~guest, "acct_std_amount"].median())

    return out


def _rolling_24h(df: pd.DataFrame) -> pd.Series:
    """Count of prior transactions per account within a trailing 24h window."""
    counts = np.zeros(len(df), dtype=int)
    window = pd.Timedelta(hours=24)
    positions: dict[str, list] = {}

    for i, (cust, ts) in enumerate(zip(df["customer_id"].to_numpy(), df["timestamp"].to_numpy())):
        hist = positions.setdefault(cust, [])
        cutoff = ts - window.to_timedelta64()
        # Drop entries that have fallen out of the trailing window.
        while hist and hist[0] < cutoff:
            hist.pop(0)
        counts[i] = len(hist)
        hist.append(ts)

    return pd.Series(counts, index=df.index)


def _empty_derived() -> pd.DataFrame:
    cols = {
        "invoice": "object", "timestamp": "datetime64[ns]", "customer_id": "object",
        "account_id": "object", "country": "object", "amount": "float64",
        "n_items": "int64", "n_units": "float64", "max_unit_price": "float64",
        "is_cancellation": "bool", "prior_txns": "int64", "acct_avg_amount": "float64",
        "acct_std_amount": "float64", "prior_cancellations": "int64",
        "account_age_days": "int64", "txns_24h": "int64", "hour": "int64",
        "is_guest": "bool", "cross_border": "bool",
    }
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})


def load() -> pd.DataFrame:
    return derive_features(load_raw())
