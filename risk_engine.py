"""RiskIQ scoring engine.

Every score is explainable: scoring a transaction returns the individual
factors that fired, the point contribution of each, and a confidence value
describing how much corroborating evidence backs the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HIGH_RISK_COUNTRIES = {"NG", "RU", "VN", "ID", "UA", "PK", "BY"}
DISPOSABLE_DOMAINS = {"mailinator.com", "guerrillamail.com", "temp-mail.org", "10minutemail.com"}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Factor definitions
#
# Each factor takes a transaction row (a mapping) and returns a raw signal in
# the range 0..1 plus a human readable explanation of why it fired.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    describe: object = field(repr=False)

    def evaluate(self, txn) -> tuple[float, str]:
        return self.describe(txn)


def _f_amount_anomaly(txn):
    avg = float(txn.get("acct_avg_amount") or 0.0)
    std = max(float(txn.get("acct_std_amount") or 0.0), 1.0)
    amount = float(txn["amount"])
    z = (amount - avg) / std
    signal = _clamp((z - 1.5) / 4.0)
    if signal <= 0:
        return 0.0, f"${amount:,.2f} is in line with the account average of ${avg:,.2f}"
    return signal, f"${amount:,.2f} is {z:.1f} standard deviations above this account's ${avg:,.2f} average"


def _f_velocity(txn):
    n = int(txn.get("txns_24h") or 0)
    signal = _clamp((n - 3) / 12.0)
    if signal <= 0:
        return 0.0, f"{n} transactions in 24h is within normal range"
    return signal, f"{n} transactions from this account in the last 24 hours"


def _f_geo_mismatch(txn):
    country = txn.get("country")
    home = txn.get("account_country")
    if country == home:
        return 0.0, f"Transaction country matches account home country ({home})"
    if country in HIGH_RISK_COUNTRIES:
        return 1.0, f"Cross-border into {country}, a jurisdiction on the elevated risk list (account is {home})"
    return 0.6, f"Cross-border transaction: {country} vs account home country {home}"


def _f_new_device(txn):
    if bool(txn.get("device_new")):
        return 1.0, "First time this device fingerprint has been seen on the account"
    return 0.0, "Known device for this account"


def _f_odd_hour(txn):
    hour = int(txn.get("hour") or 12)
    if 1 <= hour <= 5:
        return 0.8, f"Transaction placed at {hour:02d}:00 local, inside the overnight low activity window"
    return 0.0, f"Transaction placed at {hour:02d}:00 local, normal activity hours"


def _f_card_testing(txn):
    amount = float(txn["amount"])
    n = int(txn.get("txns_24h") or 0)
    if amount < 5.0 and n > 6:
        return 1.0, f"Micro amount (${amount:,.2f}) combined with {n} attempts in 24h, a classic card testing pattern"
    if amount < 5.0:
        return 0.35, f"Unusually small authorisation of ${amount:,.2f}"
    return 0.0, "Amount is above the card testing range"


def _f_new_account(txn):
    age = int(txn.get("account_age_days") or 0)
    signal = _clamp((60 - age) / 60.0)
    if signal <= 0:
        return 0.0, f"Established account, {age} days old"
    return signal, f"Account is only {age} days old"


def _f_chargebacks(txn):
    cb = int(txn.get("prior_chargebacks") or 0)
    signal = _clamp(cb / 3.0)
    if signal <= 0:
        return 0.0, "No prior chargebacks on this account"
    return signal, f"{cb} prior chargeback(s) on this account"


def _f_email_risk(txn):
    if bool(txn.get("disposable_email")):
        return 1.0, "Account registered with a disposable email domain"
    return 0.0, "Account email domain looks legitimate"


def _f_card_not_present(txn):
    if not bool(txn.get("card_present")):
        return 0.5, "Card not present transaction"
    return 0.0, "Card present transaction"


FACTORS: list[Factor] = [
    Factor("amount_anomaly", "Amount anomaly", _f_amount_anomaly),
    Factor("velocity", "Transaction velocity", _f_velocity),
    Factor("geo_mismatch", "Geographic mismatch", _f_geo_mismatch),
    Factor("new_device", "New device", _f_new_device),
    Factor("odd_hour", "Off hours activity", _f_odd_hour),
    Factor("card_testing", "Card testing pattern", _f_card_testing),
    Factor("new_account", "Account tenure", _f_new_account),
    Factor("chargebacks", "Chargeback history", _f_chargebacks),
    Factor("email_risk", "Email domain risk", _f_email_risk),
    Factor("card_not_present", "Card not present", _f_card_not_present),
]

FACTOR_BY_KEY = {f.key: f for f in FACTORS}


# ---------------------------------------------------------------------------
# Profiles
#
# A profile is a set of factor weights (summing to 100, so the raw score is
# already on a 0..100 scale) plus the band thresholds for that business model.
# ---------------------------------------------------------------------------

PROFILES: dict[str, dict] = {
    "E-commerce": {
        "blurb": "Tuned for card not present retail fraud: device churn, card testing and shipping mismatches carry the most weight.",
        "weights": {
            "amount_anomaly": 10, "velocity": 12, "geo_mismatch": 12, "new_device": 16,
            "odd_hour": 6, "card_testing": 14, "new_account": 10, "chargebacks": 8,
            "email_risk": 8, "card_not_present": 4,
        },
        "thresholds": {"critical": 62, "high": 45, "medium": 28},
    },
    "Lending": {
        "blurb": "Tuned for application and first party fraud: thin file accounts and prior loss history dominate the score.",
        "weights": {
            "amount_anomaly": 14, "velocity": 6, "geo_mismatch": 8, "new_device": 8,
            "odd_hour": 4, "card_testing": 4, "new_account": 22, "chargebacks": 20,
            "email_risk": 10, "card_not_present": 4,
        },
        "thresholds": {"critical": 65, "high": 48, "medium": 30},
    },
    "Payments": {
        "blurb": "Tuned for money movement and laundering typologies: velocity, amount spikes and cross-border flow lead.",
        "weights": {
            "amount_anomaly": 18, "velocity": 20, "geo_mismatch": 16, "new_device": 10,
            "odd_hour": 8, "card_testing": 8, "new_account": 8, "chargebacks": 6,
            "email_risk": 4, "card_not_present": 2,
        },
        "thresholds": {"critical": 60, "high": 43, "medium": 26},
    },
    "General": {
        "blurb": "Balanced baseline with every factor weighted equally. Useful as a control when comparing the tuned profiles.",
        "weights": {k: 10 for k in FACTOR_BY_KEY},
        "thresholds": {"critical": 63, "high": 46, "medium": 28},
    },
}

BANDS = ["Critical", "High", "Medium", "Low"]

BAND_COLORS = {
    "Critical": "#dc2626",
    "High": "#ea580c",
    "Medium": "#d97706",
    "Low": "#059669",
}


def band_for_score(score: float, profile_name: str) -> str:
    t = PROFILES[profile_name]["thresholds"]
    if score >= t["critical"]:
        return "Critical"
    if score >= t["high"]:
        return "High"
    if score >= t["medium"]:
        return "Medium"
    return "Low"


def _confidence(active_count: int, prior_txns: int) -> int:
    """How much should an analyst trust this score?

    Two inputs: corroboration (independent factors pointing the same way) and
    history depth (how much baseline we have for this account). A high score
    driven by one signal on a brand new account is deliberately low confidence.
    """
    corroboration = _clamp(active_count / 4.0)
    history = _clamp(prior_txns / 40.0)
    raw = 0.5 * corroboration + 0.5 * history
    return int(round(25 + raw * 74))


def score_transaction(txn, profile_name: str = "General") -> dict:
    """Score one transaction and return the full explanation."""
    if profile_name not in PROFILES:
        raise KeyError(f"Unknown profile: {profile_name!r}")

    weights = PROFILES[profile_name]["weights"]
    contributions = []
    total = 0.0
    active = 0

    for factor in FACTORS:
        weight = weights.get(factor.key, 0)
        signal, detail = factor.evaluate(txn)
        points = signal * weight
        total += points
        if signal > 0.15:
            active += 1
        contributions.append({
            "key": factor.key,
            "label": factor.label,
            "signal": round(signal, 3),
            "weight": weight,
            "points": round(points, 2),
            "detail": detail,
            "fired": signal > 0.15,
        })

    score = round(_clamp(total, 0.0, 100.0), 1)
    contributions.sort(key=lambda c: c["points"], reverse=True)

    return {
        "score": score,
        "band": band_for_score(score, profile_name),
        "confidence": _confidence(active, int(txn.get("prior_txns") or 0)),
        "factors": contributions,
        "active_factors": active,
        "profile": profile_name,
    }


def score_dataframe(df, profile_name: str = "General"):
    """Score every row of a dataframe. Returns a copy with score columns added.

    Empty frames are passed through with the expected columns present so that
    downstream charts and filters do not need to special case them.
    """
    import pandas as pd

    out = df.copy()
    if out.empty:
        out["risk_score"] = pd.Series(dtype="float64")
        out["risk_band"] = pd.Series(dtype="object")
        out["confidence"] = pd.Series(dtype="int64")
        out["active_factors"] = pd.Series(dtype="int64")
        return out

    results = [score_transaction(row, profile_name) for row in out.to_dict("records")]
    out["risk_score"] = [r["score"] for r in results]
    out["risk_band"] = [r["band"] for r in results]
    out["confidence"] = [r["confidence"] for r in results]
    out["active_factors"] = [r["active_factors"] for r in results]
    return out
