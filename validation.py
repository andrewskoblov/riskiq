"""Model validation metrics for the labelled credit dataset.

These are the measures a credit risk or model validation function reports, not
generic classification metrics. Banks quote Gini rather than AUC, KS is the
standard separation statistic in scorecard development, and a scorecard is
expected to be monotonic across bands and calibrated against observed outcomes.

Everything here is computed with numpy and pandas so the app needs no modelling
dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def auc(y_true, scores) -> float:
    """Area under the ROC curve, via the rank based Mann-Whitney identity.

    Rank averaging handles tied scores correctly, which matters here because a
    banded scorecard produces a lot of ties.
    """
    y = np.asarray(y_true).astype(int)
    s = pd.Series(np.asarray(scores, dtype=float))
    n_pos = int(y.sum())
    n_neg = int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = s.rank().to_numpy()
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def gini(y_true, scores) -> float:
    """Gini coefficient. The convention in credit risk: 2 * AUC - 1."""
    a = auc(y_true, scores)
    return float("nan") if np.isnan(a) else 2 * a - 1


def ks_statistic(y_true, scores) -> float:
    """Kolmogorov-Smirnov separation between the good and bad distributions."""
    d = pd.DataFrame({"y": np.asarray(y_true).astype(int), "s": np.asarray(scores, dtype=float)})
    if d["y"].nunique() < 2:
        return float("nan")
    d = d.sort_values("s")
    cum_bad = (d["y"] == 1).cumsum() / max(int((d["y"] == 1).sum()), 1)
    cum_good = (d["y"] == 0).cumsum() / max(int((d["y"] == 0).sum()), 1)
    return float((cum_good - cum_bad).abs().max())


def roc_curve(y_true, scores, points: int = 60) -> pd.DataFrame:
    y = np.asarray(y_true).astype(int)
    s = np.asarray(scores, dtype=float)
    if y.sum() == 0 or (1 - y).sum() == 0:
        return pd.DataFrame({"fpr": [0.0, 1.0], "tpr": [0.0, 1.0]})
    cuts = np.unique(np.quantile(s, np.linspace(0, 1, points)))
    rows = [{"fpr": 1.0, "tpr": 1.0}]
    for c in cuts:
        pred = s >= c
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        rows.append({"fpr": fp / max(int((y == 0).sum()), 1),
                     "tpr": tp / max(int((y == 1).sum()), 1)})
    rows.append({"fpr": 0.0, "tpr": 0.0})
    return pd.DataFrame(rows).sort_values("fpr").reset_index(drop=True)


def band_table(df: pd.DataFrame, band_col: str, label_col: str, order: list[str]) -> pd.DataFrame:
    """Accounts, share of book and observed bad rate per risk band, with lift."""
    base = float(df[label_col].mean()) if len(df) else float("nan")
    rows = []
    for band in order:
        m = df[band_col] == band
        n = int(m.sum())
        if n == 0:
            continue
        rate = float(df.loc[m, label_col].mean())
        rows.append({
            "Band": band,
            "Accounts": n,
            "Share of book": f"{n / len(df):.1%}",
            "Observed default rate": f"{rate:.2%}",
            "Lift vs portfolio": f"{rate / base:.2f}x" if base else "n/a",
        })
    return pd.DataFrame(rows)


def calibration(df: pd.DataFrame, score_col: str, label_col: str, bins: int = 10) -> pd.DataFrame:
    """Observed default rate by score decile, for a monotonicity check."""
    if df.empty:
        return pd.DataFrame(columns=["Decile", "Mean score", "Observed default rate", "Accounts"])
    d = df[[score_col, label_col]].copy()
    d["decile"] = pd.qcut(d[score_col].rank(method="first"), bins, labels=False) + 1
    g = d.groupby("decile", as_index=False).agg(
        mean_score=(score_col, "mean"),
        observed=(label_col, "mean"),
        accounts=(label_col, "size"),
    )
    g.columns = ["Decile", "Mean score", "Observed default rate", "Accounts"]
    return g


def psi(expected, actual, bins: int = 10) -> float:
    """Population Stability Index between two score distributions.

    Convention: below 0.10 is stable, 0.10 to 0.25 warrants monitoring, above
    0.25 indicates a material shift.
    """
    e = np.asarray(expected, dtype=float)
    a = np.asarray(actual, dtype=float)
    if len(e) == 0 or len(a) == 0:
        return float("nan")
    cuts = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(cuts) < 3:
        return float("nan")
    e_pct = np.histogram(e, bins=cuts)[0] / len(e)
    a_pct = np.histogram(a, bins=cuts)[0] / len(a)
    eps = 1e-6
    e_pct = np.clip(e_pct, eps, None)
    a_pct = np.clip(a_pct, eps, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def confusion_at(df: pd.DataFrame, score_col: str, label_col: str, threshold: float) -> dict:
    y = df[label_col].to_numpy().astype(int)
    pred = (df[score_col].to_numpy() >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else float("nan")
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "referral_rate": (tp + fp) / len(df) if len(df) else float("nan"),
    }


def disparate_impact(df: pd.DataFrame, group_col: str, flag_col: str) -> pd.DataFrame:
    """Selection rate by protected group, with the ratio to the highest group.

    The four fifths convention treats a ratio below 0.80 as a signal worth
    investigating. This measures the *scorecard's* behaviour. The attributes
    themselves are never inputs to the score.
    """
    if df.empty or group_col not in df.columns:
        return pd.DataFrame(columns=["Group", "Accounts", "Flag rate", "Ratio to highest"])
    g = df.groupby(group_col, as_index=False).agg(
        accounts=(flag_col, "size"), rate=(flag_col, "mean"))
    top = float(g["rate"].max()) if len(g) else 0.0
    g["Ratio to highest"] = (g["rate"] / top).round(3) if top else float("nan")
    g["Flag rate"] = g["rate"].map(lambda v: f"{v:.2%}")
    g = g.rename(columns={group_col: "Group", "accounts": "Accounts"})
    return g[["Group", "Accounts", "Flag rate", "Ratio to highest"]].sort_values("Group")
