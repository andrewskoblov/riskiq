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
# Retail factor pack
#
# Used for the real dataset, which is a UK online retailer. It has no device
# fingerprint, no email domain and no card present flag, so those factors do
# not exist here. Inventing them would mean scoring on fabricated evidence, so
# the pack is built only from fields the source actually contains.
# ---------------------------------------------------------------------------


def _f_cross_border(txn):
    country = txn.get("country")
    if not txn.get("cross_border"):
        return 0.0, f"Domestic order, shipping to {country}"
    return 0.85, f"Cross-border order to {country}, outside the merchant's home market"


def _f_retail_odd_hour(txn):
    hour = int(txn.get("hour") or 12)
    if hour < 8:
        return 0.7, f"Order placed at {hour:02d}:00, before normal trading hours"
    if hour >= 19:
        return 0.55, f"Order placed at {hour:02d}:00, after normal trading hours"
    return 0.0, f"Order placed at {hour:02d}:00, within normal trading hours"


def _f_cancellations(txn):
    n = int(txn.get("prior_cancellations") or 0)
    signal = _clamp(n / 8.0)
    if signal <= 0:
        return 0.0, "No prior cancellations on this account"
    return signal, f"{n} prior cancelled order(s) on this account"


def _f_guest(txn):
    if bool(txn.get("is_guest")):
        return 1.0, "Guest checkout, no customer account and therefore no history to check"
    return 0.0, "Placed from a registered customer account"


def _f_bulk_order(txn):
    units = float(txn.get("n_units") or 0.0)
    signal = _clamp((units - 400.0) / 1600.0)
    if signal <= 0:
        return 0.0, f"{units:,.0f} units, a normal basket size"
    return signal, f"Unusually large basket of {units:,.0f} units"


def _f_high_unit_price(txn):
    price = float(txn.get("max_unit_price") or 0.0)
    signal = _clamp((price - 25.0) / 175.0)
    if signal <= 0:
        return 0.0, f"Highest line item priced at {price:,.2f}, within the usual catalogue range"
    return signal, f"Basket contains a {price:,.2f} line item, well above the usual catalogue range"


def _f_negative_amount(txn):
    amount = float(txn.get("amount") or 0.0)
    if amount < 0:
        return 1.0, f"Negative value of {amount:,.2f}, a refund, return or cancellation"
    if amount == 0:
        return 0.6, "Zero value order, typically a manual adjustment"
    return 0.0, "Positive order value"


RETAIL_FACTORS: list[Factor] = [
    Factor("amount_anomaly", "Amount anomaly", _f_amount_anomaly),
    Factor("velocity", "Order velocity", _f_velocity),
    Factor("cross_border", "Cross-border order", _f_cross_border),
    Factor("odd_hour", "Off hours activity", _f_retail_odd_hour),
    Factor("new_account", "Account tenure", _f_new_account),
    Factor("cancellations", "Cancellation history", _f_cancellations),
    Factor("guest_checkout", "Guest checkout", _f_guest),
    Factor("bulk_order", "Bulk order", _f_bulk_order),
    Factor("high_unit_price", "High value line item", _f_high_unit_price),
    Factor("negative_amount", "Negative or zero value", _f_negative_amount),
]

# ---------------------------------------------------------------------------
# Credit factor pack
#
# For the UCI Default of Credit Card Clients data, which carries a real default
# label. Every factor here is a behavioural or exposure measure.
#
# Sex, marital status, age and education are present in the source and are
# deliberately absent from this list. Under the Equal Credit Opportunity Act and
# Regulation B, sex and marital status are prohibited bases for a credit
# decision and age is restricted. They are carried in the data as monitor_*
# columns so disparate impact can be measured, which is what a lender is
# expected to do, and they never contribute a single point to a score.
# ---------------------------------------------------------------------------


def _f_current_delinquency(txn):
    status = int(txn.get("pay_status_current") or 0)
    if status <= 0:
        return 0.0, "Current on the most recent statement"
    signal = _clamp(status / 4.0)
    return signal, f"{status} month(s) past due on the most recent statement"


def _f_delinquency_depth(txn):
    worst = int(txn.get("pay_status_worst") or 0)
    if worst <= 0:
        return 0.0, "Never past due across the six month window"
    signal = _clamp(worst / 5.0)
    return signal, f"Worst delinquency in the last six months was {worst} month(s) past due"


def _f_delinquency_frequency(txn):
    n = int(txn.get("months_delinquent") or 0)
    if n <= 0:
        return 0.0, "No delinquent months in the six month window"
    signal = _clamp(n / 4.0)
    return signal, f"Past due in {n} of the last 6 months"


def _f_utilization(txn):
    u = float(txn.get("utilization") or 0.0)
    signal = _clamp((u - 0.3) / 0.7)
    if signal <= 0:
        return 0.0, f"Utilisation of {u:.0%} of the credit limit"
    return signal, f"Utilisation of {u:.0%} of the credit limit"


def _f_sustained_utilization(txn):
    u = float(txn.get("avg_utilization") or 0.0)
    signal = _clamp((u - 0.35) / 0.65)
    if signal <= 0:
        return 0.0, f"Six month average utilisation of {u:.0%}"
    return signal, f"Sustained high utilisation, averaging {u:.0%} over six months"


def _f_balance_trend(txn):
    t = float(txn.get("balance_trend") or 0.0)
    signal = _clamp(t / 0.5)
    if signal <= 0:
        return 0.0, "Balance is flat or falling over the six month window"
    return signal, f"Balance has grown by {t:.0%} of the credit limit over six months"


def _f_payment_coverage(txn):
    c = float(txn.get("payment_coverage") if txn.get("payment_coverage") is not None else 1.0)
    signal = _clamp((0.3 - c) / 0.3)
    if signal <= 0:
        return 0.0, f"Paid {c:.0%} of the previous statement"
    return signal, f"Paid only {c:.0%} of the previous statement balance"


def _f_revolving(txn):
    status = int(txn.get("pay_status_current") or 0)
    if status == 0:
        return 0.6, "Revolving the balance rather than paying in full"
    if status < 0:
        return 0.0, "Settled the statement in full"
    return 0.0, "Delinquency is captured by the past due factors"


def _f_limit_size(txn):
    limit = float(txn.get("credit_limit") or 0.0)
    signal = _clamp((120_000 - limit) / 120_000)
    if signal <= 0:
        return 0.0, f"Credit limit of {limit:,.0f}"
    return signal, f"Low credit limit of {limit:,.0f}, typical of a thinner file"


def _f_repayment_volume(txn):
    repaid = float(txn.get("total_repaid_6m") or 0.0)
    limit = max(float(txn.get("credit_limit") or 1.0), 1.0)
    ratio = repaid / limit
    signal = _clamp((0.25 - ratio) / 0.25)
    if signal <= 0:
        return 0.0, f"Repaid {ratio:.0%} of the credit limit over six months"
    return signal, f"Repaid only {ratio:.0%} of the credit limit over six months"


CREDIT_FACTORS: list[Factor] = [
    Factor("current_delinquency", "Current delinquency", _f_current_delinquency),
    Factor("delinquency_depth", "Worst delinquency", _f_delinquency_depth),
    Factor("delinquency_frequency", "Delinquency frequency", _f_delinquency_frequency),
    Factor("utilization", "Credit utilisation", _f_utilization),
    Factor("sustained_utilization", "Sustained utilisation", _f_sustained_utilization),
    Factor("balance_trend", "Rising balance", _f_balance_trend),
    Factor("payment_coverage", "Payment coverage", _f_payment_coverage),
    Factor("revolving", "Revolving behaviour", _f_revolving),
    Factor("limit_size", "Credit limit", _f_limit_size),
    Factor("repayment_volume", "Repayment volume", _f_repayment_volume),
]

# Present in the source, never scored. See the note above.
PROTECTED_ATTRIBUTES = {
    "monitor_sex": "Sex",
    "monitor_marriage": "Marital status",
    "monitor_age": "Age",
    "monitor_education": "Education",
}

FACTOR_PACKS: dict[str, list[Factor]] = {
    "synthetic": FACTORS,
    "retail": RETAIL_FACTORS,
    "credit": CREDIT_FACTORS,
}


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
            "synthetic": {
                "amount_anomaly": 10, "velocity": 12, "geo_mismatch": 12, "new_device": 16,
                "odd_hour": 6, "card_testing": 14, "new_account": 10, "chargebacks": 8,
                "email_risk": 8, "card_not_present": 4,
            },
            "retail": {
                "amount_anomaly": 12, "velocity": 12, "cross_border": 12, "odd_hour": 6,
                "new_account": 10, "cancellations": 14, "guest_checkout": 14,
                "bulk_order": 8, "high_unit_price": 6, "negative_amount": 6,
            },
            "credit": {
                "current_delinquency": 14, "delinquency_depth": 10, "delinquency_frequency": 10,
                "utilization": 14, "sustained_utilization": 12, "balance_trend": 8,
                "payment_coverage": 14, "revolving": 8, "limit_size": 6, "repayment_volume": 4,
            },
        },
        "thresholds": {
            "synthetic": {"critical": 62, "high": 45, "medium": 28},
            "retail": {"critical": 42.9, "high": 30.9, "medium": 27.6},
            "credit": {"critical": 56.6, "high": 47.5, "medium": 32.5},
        },
    },
    "Lending": {
        "blurb": "Tuned for application and first party fraud: thin file accounts and prior loss history dominate the score.",
        "weights": {
            "synthetic": {
                "amount_anomaly": 14, "velocity": 6, "geo_mismatch": 8, "new_device": 8,
                "odd_hour": 4, "card_testing": 4, "new_account": 22, "chargebacks": 20,
                "email_risk": 10, "card_not_present": 4,
            },
            "retail": {
                "amount_anomaly": 14, "velocity": 6, "cross_border": 8, "odd_hour": 4,
                "new_account": 22, "cancellations": 20, "guest_checkout": 14,
                "bulk_order": 4, "high_unit_price": 4, "negative_amount": 4,
            },
            "credit": {
                "current_delinquency": 20, "delinquency_depth": 14, "delinquency_frequency": 14,
                "utilization": 10, "sustained_utilization": 10, "balance_trend": 6,
                "payment_coverage": 14, "revolving": 4, "limit_size": 4, "repayment_volume": 4,
            },
        },
        "thresholds": {
            "synthetic": {"critical": 65, "high": 48, "medium": 30},
            "retail": {"critical": 54.2, "high": 40.0, "medium": 38.4},
            "credit": {"critical": 57.2, "high": 42.4, "medium": 28.6},
        },
    },
    "Payments": {
        "blurb": "Tuned for money movement and laundering typologies: velocity, amount spikes and cross-border flow lead.",
        "weights": {
            "synthetic": {
                "amount_anomaly": 18, "velocity": 20, "geo_mismatch": 16, "new_device": 10,
                "odd_hour": 8, "card_testing": 8, "new_account": 8, "chargebacks": 6,
                "email_risk": 4, "card_not_present": 2,
            },
            "retail": {
                "amount_anomaly": 18, "velocity": 20, "cross_border": 16, "odd_hour": 8,
                "new_account": 8, "cancellations": 8, "guest_checkout": 8,
                "bulk_order": 6, "high_unit_price": 4, "negative_amount": 4,
            },
            "credit": {
                "current_delinquency": 12, "delinquency_depth": 10, "delinquency_frequency": 12,
                "utilization": 12, "sustained_utilization": 12, "balance_trend": 14,
                "payment_coverage": 12, "revolving": 6, "limit_size": 4, "repayment_volume": 6,
            },
        },
        "thresholds": {
            "synthetic": {"critical": 60, "high": 43, "medium": 26},
            "retail": {"critical": 39.1, "high": 25.9, "medium": 18.4},
            "credit": {"critical": 55.4, "high": 46.9, "medium": 31.6},
        },
    },
    "General": {
        "blurb": "Balanced baseline with every factor weighted equally. Useful as a control when comparing the tuned profiles.",
        "weights": {
            "synthetic": {f.key: 10 for f in FACTORS},
            "retail": {f.key: 10 for f in RETAIL_FACTORS},
            "credit": {f.key: 10 for f in CREDIT_FACTORS},
        },
        "thresholds": {
            "synthetic": {"critical": 63, "high": 46, "medium": 28},
            "retail": {"critical": 40.9, "high": 30.0, "medium": 26.0},
            "credit": {"critical": 51.3, "high": 44.5, "medium": 32.0},
        },
    },
}

BANDS = ["Critical", "High", "Medium", "Low"]

BAND_COLORS = {
    "Critical": "#dc2626",
    "High": "#ea580c",
    "Medium": "#d97706",
    "Low": "#059669",
}


def thresholds_for(profile_name: str, pack: str = "synthetic") -> dict:
    return PROFILES[profile_name]["thresholds"][pack]


def weights_for(profile_name: str, pack: str = "synthetic") -> dict:
    return PROFILES[profile_name]["weights"][pack]


def band_for_score(score: float, profile_name: str, pack: str = "synthetic") -> str:
    t = thresholds_for(profile_name, pack)
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


def score_transaction(txn, profile_name: str = "General", pack: str = "synthetic") -> dict:
    """Score one transaction and return the full explanation."""
    if profile_name not in PROFILES:
        raise KeyError(f"Unknown profile: {profile_name!r}")
    if pack not in FACTOR_PACKS:
        raise KeyError(f"Unknown factor pack: {pack!r}")

    weights = weights_for(profile_name, pack)
    contributions = []
    total = 0.0
    active = 0

    for factor in FACTOR_PACKS[pack]:
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
        "band": band_for_score(score, profile_name, pack),
        "confidence": _confidence(active, int(txn.get("prior_txns") or 0)),
        "factors": contributions,
        "active_factors": active,
        "profile": profile_name,
        "pack": pack,
    }


def score_dataframe(df, profile_name: str = "General", pack: str = "synthetic"):
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

    results = [score_transaction(row, profile_name, pack) for row in out.to_dict("records")]
    out["risk_score"] = [r["score"] for r in results]
    out["risk_band"] = [r["band"] for r in results]
    out["confidence"] = [r["confidence"] for r in results]
    out["active_factors"] = [r["active_factors"] for r in results]
    return out
