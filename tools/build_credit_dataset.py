"""Build the credit risk Parquet from the UCI Default of Credit Card Clients archive.

30,000 real credit card accounts from a Taiwanese issuer, April to September
2005, with a real labelled outcome: whether the account defaulted the following
month. The label is what makes this dataset worth adding, because it is what
lets the app report Gini, KS and calibration rather than only a score.

A deliberate choice about protected attributes
----------------------------------------------
The source contains SEX, MARRIAGE, EDUCATION and AGE. Under the US Equal Credit
Opportunity Act and Regulation B, sex and marital status are prohibited bases
for a credit decision, and age is restricted. They are retained in the output
file so that disparate impact can be *monitored*, which is what a real lender
is expected to do, but they are excluded from the scoring factors entirely.
Scoring on them would be illegal in a real deployment, not merely impolite.

Requires xlrd to read the legacy .xls container:
    pip install xlrd
Run:
    python tools/build_credit_dataset.py path/to/default+of+credit+card+clients.zip
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent.parent / "data" / "credit.parquet"

# The observation window closes at the September 2005 statement. Every account
# shares it, so this is a factual reference date rather than a per-row event time.
OBSERVATION_DATE = pd.Timestamp("2005-09-30")

PAY_COLS = ["PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"]
BILL_COLS = [f"BILL_AMT{i}" for i in range(1, 7)]
AMT_COLS = [f"PAY_AMT{i}" for i in range(1, 7)]


def read_xls(zip_path: str) -> pd.DataFrame:
    import xlrd  # imported lazily so the app never needs it

    z = zipfile.ZipFile(zip_path)
    name = next(n for n in z.namelist() if n.lower().endswith(".xls"))
    book = xlrd.open_workbook(file_contents=z.read(name))
    sh = book.sheet_by_index(0)
    header = sh.row_values(1)
    rows = [sh.row_values(r) for r in range(2, sh.nrows)]
    return pd.DataFrame(rows, columns=header)


def build(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={"default payment next month": "defaulted"})

    limit = df["LIMIT_BAL"].astype(float).clip(lower=1.0)
    bill1 = df["BILL_AMT1"].astype(float)

    out = pd.DataFrame({
        "txn_id": "ACC-" + df["ID"].astype(int).astype(str).str.zfill(5),
        "account_id": "ACC-" + df["ID"].astype(int).astype(str).str.zfill(5),
        "timestamp": OBSERVATION_DATE,
        "country": "Taiwan",
        "credit_limit": limit.round(2),
        # Exposure is the current statement balance. The app treats this as the
        # transaction amount, so "value at risk" reads as total exposure.
        "amount": bill1.round(2),
        "defaulted": df["defaulted"].astype(int),
    })

    # --- Scoring features, none of them protected attributes ----------------
    out["utilization"] = (bill1 / limit).clip(-1.0, 3.0).round(4)

    bills = df[BILL_COLS].astype(float)
    out["avg_utilization"] = (bills.mean(axis=1) / limit).clip(-1.0, 3.0).round(4)
    out["balance_trend"] = ((bills["BILL_AMT1"] - bills["BILL_AMT6"]) / limit).clip(-3.0, 3.0).round(4)

    pays = df[PAY_COLS].astype(int)
    # Encoding: -2 no consumption, -1 paid in full, 0 revolving, 1..9 months late.
    out["pay_status_current"] = pays["PAY_0"]
    out["pay_status_worst"] = pays.max(axis=1)
    out["months_delinquent"] = (pays >= 1).sum(axis=1)

    paid = df["PAY_AMT1"].astype(float)
    prior_bill = df["BILL_AMT2"].astype(float)
    # Share of the previous statement actually paid. Undefined when there was
    # nothing owed, which is not a risk signal, so it is treated as fully paid.
    coverage = np.where(prior_bill > 0, paid / prior_bill.where(prior_bill > 0, 1.0), 1.0)
    out["payment_coverage"] = pd.Series(coverage).clip(0.0, 2.0).round(4)

    out["total_repaid_6m"] = df[AMT_COLS].astype(float).sum(axis=1).round(2)

    # Grouping handle for the breakdown charts.
    out["category"] = pd.cut(
        limit,
        bins=[0, 50_000, 100_000, 200_000, 400_000, np.inf],
        labels=["Under 50k", "50k to 100k", "100k to 200k", "200k to 400k", "Over 400k"],
    ).astype(str)

    # --- Monitoring only. Never used as scoring factors. --------------------
    out["monitor_sex"] = df["SEX"].astype(int).map({1: "Male", 2: "Female"}).fillna("Unknown")
    out["monitor_age"] = df["AGE"].astype(int)
    out["monitor_marriage"] = df["MARRIAGE"].astype(int).map(
        {1: "Married", 2: "Single", 3: "Other"}).fillna("Unknown")
    out["monitor_education"] = df["EDUCATION"].astype(int).map(
        {1: "Graduate school", 2: "University", 3: "High school", 4: "Other"}).fillna("Unknown")

    return out


def main() -> None:
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "default+of+credit+card+clients.zip"
    raw = read_xls(zip_path)
    print(f"raw rows: {len(raw):,}")
    df = build(raw)

    print(f"accounts: {len(df):,}")
    print(f"default rate: {df['defaulted'].mean():.2%}")
    print(f"utilization  p50={df['utilization'].median():.3f}  p95={df['utilization'].quantile(.95):.3f}")
    print(f"delinquent now: {(df['pay_status_current'] >= 1).mean():.2%}")
    print(f"limit bands:\n{df['category'].value_counts().to_string()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False, compression="zstd")
    print(f"\nwrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
