# RiskIQ

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://andrewskoblovriskiq.streamlit.app/)

**Live app: [andrewskoblovriskiq.streamlit.app](https://andrewskoblovriskiq.streamlit.app/)**

Explainable transaction risk scoring, built with Streamlit.

Most scoring demos hand you a number. RiskIQ shows the arithmetic: every score
decomposes into the factors that produced it, each factor carries its own point
contribution and plain language explanation, and every result comes with a
confidence value describing how much evidence stands behind it.

## What it does

- **Explainable scoring.** Ten factors (amount anomaly, velocity, geography,
  device novelty, off hours activity, card testing, account tenure, chargeback
  history, email domain risk, card present status) each produce a 0 to 1 signal
  that is multiplied by a profile weight. The weights sum to 100, so the score
  is already on a 0 to 100 scale and each factor's point contribution is
  directly readable.
- **Four adaptive profiles.** E-commerce, Lending, Payments and General reweight
  the same factors for different business models and apply their own band
  thresholds. Switch profiles live from the sidebar and the whole app rescores.
- **Confidence scoring.** Signals are weighted by corroboration (how many
  independent factors agree) and by account history depth. A high score driven
  by a single factor on a brand new account is deliberately reported as low
  confidence.
- **Threshold simulator.** On Model Insights, drag the review threshold and
  watch flagged volume, captured value and unreviewed exposure update live.

## Pages

| Page | Purpose |
| --- | --- |
| `Home.py` | Portfolio overview: band distribution, gauge, highest risk cases |
| `pages/1_Risk_Explorer.py` | Filter the population by band, country, category and score |
| `pages/2_Case_Investigation.py` | Full factor breakdown for a single transaction |
| `pages/3_Model_Insights.py` | Threshold simulation, factor importance, profile comparison |
| `pages/4_Model_Validation.py` | Gini, KS, ROC, calibration, PSI and disparate impact against a real label |

## Measured performance

The credit portfolio carries a real default outcome, so the scorecard can be
validated rather than merely demonstrated. On 30,000 real accounts with a
22.12% portfolio default rate, the Lending profile achieves:

| Metric | Value |
| --- | --- |
| Gini coefficient | **0.401** |
| KS statistic | 0.328 |
| AUC | 0.701 |

Gini above 0.40 is the conventional bar for an acceptable behavioural
scorecard. Published gradient boosting models on this dataset reach roughly
0.77 AUC, so this trades some discrimination for the property that every point
of every score is attributable to a named, auditable factor. That is the
tradeoff a model risk committee actually argues about, and the reason the
scorecard reports it openly rather than quoting only the favourable number.

Rank ordering is monotonic across bands:

| Band | Share of book | Observed default rate | Lift |
| --- | --- | --- | --- |
| Critical | 5.0% | 63.20% | 2.86x |
| High | 10.1% | 53.76% | 2.43x |
| Medium | 25.0% | 20.92% | 0.95x |
| Low | 59.9% | 13.85% | 0.63x |

## Regulatory posture

Explainability here is not a presentation feature. Under Fed guidance SR 11-7
a model must have documented validation, and under the Equal Credit Opportunity
Act and Regulation B a declined applicant is owed specific reasons. A score
decomposition that names the contributing factors and their point values is
the input to an adverse action notice.

The credit source contains sex, marital status, age and education. **None of
them contribute a single point to any score.** Regulation B prohibits sex and
marital status as a basis for a credit decision and restricts age. They are
retained in the data solely so the Model Validation page can measure disparate
impact across those groups, which is what a lender is expected to do. Excluding
an attribute from a model does not by itself guarantee a neutral outcome, so
the outcome is measured rather than assumed.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS and Linux

pip install -r requirements.txt
streamlit run Home.py
```

The app opens on `http://localhost:8501`.

## Deployed on Streamlit Community Cloud

Hosted at [andrewskoblovriskiq.streamlit.app](https://andrewskoblovriskiq.streamlit.app/),
deployed from `main` with `Home.py` as the entry point. Streamlit discovers the
`pages/` directory automatically, so the three secondary pages appear in the
sidebar with no extra configuration. See [DEPLOYMENT.md](DEPLOYMENT.md) for the
full setup and redeploy notes.

## Data

Two sources, switchable from the sidebar.

### Real (default)

**53,628 real invoices** from the [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
dataset: a UK based online retailer, December 2009 to December 2011, aggregated
from 1,067,371 invoice line items. 43 countries, 5,943 customers, 8,292
cancellations. The source contains no personal data.

Account history features (rolling average spend, prior transaction count,
prior cancellations, account tenure, 24 hour velocity) are derived in
`real_data.py` from **prior transactions only**. Computing them over the full
history including the current row would leak information the model would not
have had at authorisation time and would flatter the scores.

Guest checkouts have no customer id, so the source groups them all under one
placeholder. Treating that as a single account would invent a history that does
not exist and report absurd velocities, so guest history features are zeroed and
the guest checkout factor carries the signal instead.

Rebuild the Parquet file from the original archive with:

```bash
python tools/build_real_dataset.py path/to/online+retail+ii.zip
```

### Real, credit (labelled)

**30,000 real credit card accounts** from the
[UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)
dataset: a Taiwanese issuer, April to September 2005, with six months of
repayment status, bill amounts and payments per account, and **a real default
outcome for the following month**. Portfolio default rate is 22.12%.

This is the only source with a label, which is what makes the Model Validation
page possible. Rebuild it with:

```bash
pip install xlrd   # only needed for the build script, not the app
python tools/build_credit_dataset.py path/to/default+of+credit+card+clients.zip
```

### Synthetic

Generated by `data_generator.py` with a seeded random number generator. The
anomaly injection is calibrated so a realistic slice of traffic lands in the
High and Critical bands, which keeps the dashboard meaningful and makes scoring
regressions visible. Useful because it carries signals real open datasets rarely
publish, such as device fingerprint and email domain.

### Two factor packs

Real retail data has no device fingerprint, no email domain and no card present
flag. Rather than fabricate them, the engine carries two factor packs and uses
whichever matches the active source:

| Pack | Factors |
| --- | --- |
| `retail` | amount anomaly, order velocity, cross-border, off hours, account tenure, cancellation history, guest checkout, bulk order, high value line item, negative or zero value |
| `credit` | current delinquency, worst delinquency, delinquency frequency, utilisation, sustained utilisation, rising balance, payment coverage, revolving behaviour, credit limit, repayment volume |
| `synthetic` | amount anomaly, velocity, geographic mismatch, new device, off hours, card testing, account tenure, chargeback history, email domain risk, card not present |

Retail thresholds are calibrated against the real score distribution so every
profile flags a comparable share of volume (roughly 0.5% Critical and 3% High),
rather than one profile flooding the queue while another stays silent.

## Project layout

```
Home.py                        overview dashboard and app entry point
risk_engine.py                 factors, factor packs, profiles, scoring, confidence
validation.py                  Gini, KS, ROC, calibration, PSI, disparate impact
real_data.py                   retail loading and account history derivation
data_generator.py              synthetic transaction population
data_service.py                cached loading, scoring, shared sidebar
utils.py                       design system, CSS, chart theming
pages/                         the four secondary pages
data/transactions.parquet      53,628 real invoices (1.1 MB)
data/credit.parquet            30,000 real labelled accounts (0.8 MB)
tools/build_real_dataset.py    rebuilds the retail Parquet
tools/build_credit_dataset.py  rebuilds the credit Parquet
.github/workflows/             daily keep-awake workflow
.streamlit/                    theme configuration
```

## Credits

Chen, D. (2019). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
<https://doi.org/10.24432/C5CG6D>. Licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Yeh, I. C. (2009). *Default of Credit Card Clients* [Dataset]. UCI Machine
Learning Repository. <https://doi.org/10.24432/C55S3H>. Licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
