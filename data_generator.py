"""Synthetic transaction generator.

The anomaly injection is deliberately calibrated so that a realistic slice of
traffic lands in the High and Critical bands. A generator that only produces
clean traffic makes the dashboard look empty and hides scoring regressions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU", "JP", "BR", "MX", "NG", "RU", "VN", "ID", "UA"]
HOME_COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU"]
CATEGORIES = ["Electronics", "Travel", "Digital goods", "Apparel", "Groceries", "Gaming", "Gift cards", "Subscriptions"]
MERCHANTS = ["Northwind Retail", "Blue Harbor", "Vertex Digital", "Olive & Co", "Summit Outfitters",
             "PixelForge", "CardMart", "StreamlyPlus", "Kestrel Travel", "Fenwick Goods"]
CLEAN_DOMAINS = ["gmail.com", "outlook.com", "icloud.com", "yahoo.com", "proton.me"]
DISPOSABLE = ["mailinator.com", "guerrillamail.com", "temp-mail.org", "10minutemail.com"]


def generate_transactions(n_records: int = 650, seed: int = 42) -> pd.DataFrame:
    """Generate ``n_records`` transactions spread across a pool of accounts."""
    if n_records <= 0:
        return _empty_frame()

    rng = np.random.default_rng(seed)
    n_accounts = max(4, n_records // 8)

    # --- Account level attributes -----------------------------------------
    acct_ids = [f"ACC-{i:05d}" for i in range(1, n_accounts + 1)]
    acct_home = rng.choice(HOME_COUNTRIES, n_accounts)
    acct_age = rng.integers(3, 1500, n_accounts)
    acct_avg = np.round(rng.gamma(shape=2.2, scale=48.0, size=n_accounts) + 12.0, 2)
    acct_std = np.round(acct_avg * rng.uniform(0.18, 0.5, n_accounts), 2)
    acct_prior = rng.integers(0, 120, n_accounts)
    acct_cb = rng.choice([0, 0, 0, 0, 0, 1, 1, 2, 3], n_accounts)
    acct_disposable = rng.random(n_accounts) < 0.07

    # Roughly 8 percent of accounts behave like a compromised or mule account.
    compromised = rng.random(n_accounts) < 0.08

    acct = {
        a: {
            "home": acct_home[i],
            "age": int(acct_age[i]),
            "avg": float(acct_avg[i]),
            "std": float(acct_std[i]),
            "prior": int(acct_prior[i]),
            "cb": int(acct_cb[i]),
            "disposable": bool(acct_disposable[i]),
            "bad": bool(compromised[i]),
        }
        for i, a in enumerate(acct_ids)
    }

    # Velocity per account for the 24h window.
    velocity = {}
    for a in acct_ids:
        if acct[a]["bad"]:
            velocity[a] = int(rng.integers(7, 22))
        else:
            velocity[a] = int(rng.integers(1, 6))

    start = pd.Timestamp("2026-08-01")
    rows = []

    for i in range(n_records):
        a = acct_ids[int(rng.integers(0, n_accounts))]
        meta = acct[a]
        bad = meta["bad"]

        # An account flagged as compromised does not make every transaction
        # fraudulent, so anomalies are injected on a subset of its traffic.
        anomalous = bad and rng.random() < 0.62
        mild = (not anomalous) and rng.random() < 0.12

        if anomalous:
            mode = rng.choice(["spike", "testing", "geo"], p=[0.42, 0.28, 0.30])
            if mode == "testing":
                amount = round(float(rng.uniform(0.5, 4.5)), 2)
            elif mode == "spike":
                amount = round(float(meta["avg"] + meta["std"] * rng.uniform(4.0, 11.0)), 2)
            else:
                amount = round(float(max(4.0, rng.normal(meta["avg"], max(meta["std"], 1.0)))), 2)
            country = str(rng.choice(["NG", "RU", "VN", "ID", "UA", "PK"])) if mode == "geo" or rng.random() < 0.55 else meta["home"]
            device_new = rng.random() < 0.85
            hour = int(rng.choice([1, 2, 3, 4, 5])) if rng.random() < 0.6 else int(rng.integers(0, 24))
            card_present = False
        elif mild:
            amount = round(float(max(2.0, rng.normal(meta["avg"] * 1.9, max(meta["std"], 1.0)))), 2)
            country = str(rng.choice(COUNTRIES)) if rng.random() < 0.4 else meta["home"]
            device_new = rng.random() < 0.35
            hour = int(rng.integers(0, 24))
            card_present = rng.random() < 0.5
        else:
            amount = round(float(max(1.5, rng.normal(meta["avg"], max(meta["std"], 1.0)))), 2)
            country = meta["home"] if rng.random() < 0.93 else str(rng.choice(HOME_COUNTRIES))
            device_new = rng.random() < 0.08
            hour = int(rng.integers(6, 23))
            card_present = rng.random() < 0.62

        ts = start + pd.Timedelta(minutes=int(rng.integers(0, 60 * 24 * 30)))
        ts = ts.replace(hour=hour)

        rows.append({
            "txn_id": f"TXN-{100000 + i}",
            "timestamp": ts,
            "account_id": a,
            "amount": amount,
            "category": str(rng.choice(CATEGORIES)),
            "merchant": str(rng.choice(MERCHANTS)),
            "country": country,
            "account_country": meta["home"],
            "device_new": bool(device_new),
            "hour": int(hour),
            "account_age_days": meta["age"] if not bad else min(meta["age"], int(rng.integers(2, 75))),
            "prior_txns": meta["prior"],
            "prior_chargebacks": meta["cb"] if not bad else max(meta["cb"], int(rng.integers(1, 4))),
            "acct_avg_amount": meta["avg"],
            "acct_std_amount": meta["std"],
            "txns_24h": velocity[a],
            "disposable_email": meta["disposable"] or (bad and rng.random() < 0.5),
            "card_present": bool(card_present),
            "email_domain": str(rng.choice(DISPOSABLE if meta["disposable"] else CLEAN_DOMAINS)),
        })

    df = pd.DataFrame(rows)
    return df.sort_values("timestamp").reset_index(drop=True)


def _empty_frame() -> pd.DataFrame:
    cols = {
        "txn_id": "object", "timestamp": "datetime64[ns]", "account_id": "object",
        "amount": "float64", "category": "object", "merchant": "object",
        "country": "object", "account_country": "object", "device_new": "bool",
        "hour": "int64", "account_age_days": "int64", "prior_txns": "int64",
        "prior_chargebacks": "int64", "acct_avg_amount": "float64",
        "acct_std_amount": "float64", "txns_24h": "int64",
        "disposable_email": "bool", "card_present": "bool", "email_domain": "object",
    }
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})
