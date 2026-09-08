"""Model validation against a real outcome label.

Only the credit portfolio carries a real label, so this page reports metrics
only for that source. Everything here follows credit risk convention rather
than generic classification reporting: Gini rather than AUC, KS for separation,
monotonicity across bands, calibration against observed outcomes, and a
disparate impact check on attributes the scorecard is forbidden to use.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import validation as val
from data_service import CREDIT, get_scored_data, has_labels, sidebar_controls
from risk_engine import BANDS, PROFILES, PROTECTED_ATTRIBUTES, thresholds_for
from utils import empty_state, hero, page_setup, stat_card, style_chart

page_setup("Model Validation")
profile, source = sidebar_controls()
df, pack = get_scored_data(profile)

hero(
    "Model Validation",
    "A score is only worth as much as its measured performance. This page reports the "
    "scorecard against a real outcome label using credit risk convention.",
)

if not has_labels(df):
    empty_state(
        f"The <b>{source}</b> source has no outcome label, so performance cannot be measured "
        "against it. Switch the data source to <b>Real (UCI Credit Default)</b> in the sidebar, "
        "which carries a real default flag for all 30,000 accounts."
    )
    st.stop()

LABEL = "defaulted"
base_rate = float(df[LABEL].mean())

# --- Headline discrimination ------------------------------------------------
g = val.gini(df[LABEL], df["risk_score"])
k = val.ks_statistic(df[LABEL], df["risk_score"])
a = val.auc(df[LABEL], df["risk_score"])

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat_card("Gini coefficient", f"{g:.3f}",
              "above 0.40 is the usual bar" if g >= 0.40 else "below the usual 0.40 bar")
with c2:
    stat_card("KS statistic", f"{k:.3f}", "good/bad separation")
with c3:
    stat_card("AUC", f"{a:.3f}", "rank ordering power")
with c4:
    stat_card("Portfolio default rate", f"{base_rate:.2%}", f"{len(df):,} accounts")

st.caption(
    "Gini is the credit risk convention (2 x AUC - 1). This is a hand weighted expert "
    "scorecard with no fitted parameters, so it trades some discrimination for the fact "
    "that every point of every score is attributable to a named, auditable factor."
)

st.divider()

# --- Rank ordering ----------------------------------------------------------
st.markdown("#### Rank ordering by risk band")
st.caption(
    "A scorecard that does not order risk monotonically is not usable, whatever its Gini. "
    "Each band should show a materially higher default rate than the one below it."
)

bt = val.band_table(df, "risk_band", LABEL, BANDS)
st.dataframe(bt, width="stretch", hide_index=True)

left, right = st.columns(2)

with left:
    cal = val.calibration(df, "risk_score", LABEL, bins=10)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cal["Decile"], y=cal["Observed default rate"],
                         name="Observed default rate", marker={"color": "#4f46e5"}))
    fig.add_hline(y=base_rate, line_dash="dash", line_color="#dc2626",
                  annotation_text="portfolio average", annotation_position="top left")
    style_chart(fig, "Observed default rate by score decile", height=340,
                xaxis={"title": "Score decile (10 = riskiest)"},
                yaxis={"title": "Observed default rate", "tickformat": ".0%"},
                showlegend=False)
    st.plotly_chart(fig, width="stretch")

with right:
    roc = val.roc_curve(df[LABEL], df["risk_score"])
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=roc["fpr"], y=roc["tpr"], mode="lines",
                              name=f"Scorecard (Gini {g:.3f})",
                              line={"color": "#4f46e5", "width": 2.5}))
    fig2.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Random",
                              line={"color": "#9ca3af", "width": 1.5, "dash": "dash"}))
    style_chart(fig2, "ROC curve", height=340,
                xaxis={"title": "False positive rate"}, yaxis={"title": "True positive rate"})
    st.plotly_chart(fig2, width="stretch")

st.divider()

# --- Operating point --------------------------------------------------------
st.markdown("#### Operating point")
st.caption(
    "Where the cutoff sits is a business decision, not a statistical one. Moving it trades "
    "defaults caught against good accounts declined."
)

default_cut = float(thresholds_for(profile, pack)["high"])
cut = st.slider("Decline or refer at or above", 0.0, 100.0, default_cut, step=0.5)
cm = val.confusion_at(df, "risk_score", LABEL, cut)

m1, m2, m3, m4 = st.columns(4)
with m1:
    stat_card("Referral rate", f"{cm['referral_rate']:.1%}", f"{cm['tp'] + cm['fp']:,} accounts")
with m2:
    stat_card("Precision", f"{cm['precision']:.1%}", "of referrals that did default")
with m3:
    stat_card("Recall", f"{cm['recall']:.1%}", "of all defaults captured")
with m4:
    stat_card("F1", f"{cm['f1']:.3f}", "balance of the two")

cmat = pd.DataFrame({
    "": ["Referred", "Approved"],
    "Defaulted": [f"{cm['tp']:,}", f"{cm['fn']:,}"],
    "Did not default": [f"{cm['fp']:,}", f"{cm['tn']:,}"],
})
st.dataframe(cmat, width="stretch", hide_index=True)
st.caption(
    f"At this cutoff the scorecard refers {cm['referral_rate']:.1%} of the book and captures "
    f"{cm['recall']:.1%} of all defaults. The {cm['fn']:,} accounts in the approved and "
    f"defaulted cell are the losses this cutoff accepts."
)

st.divider()

# --- Stability --------------------------------------------------------------
st.markdown("#### Score stability across the book")
st.caption(
    "Population Stability Index between the lower and upper halves of the credit limit "
    "distribution. Below 0.10 is stable, 0.10 to 0.25 warrants monitoring, above 0.25 "
    "indicates a material shift. This is the same test used to detect drift over time once "
    "a scorecard is in production."
)

median_limit = float(df["credit_limit"].median())
low_half = df[df["credit_limit"] <= median_limit]["risk_score"]
high_half = df[df["credit_limit"] > median_limit]["risk_score"]
p = val.psi(low_half, high_half)

s1, s2 = st.columns([1, 3])
with s1:
    verdict = "Stable" if p < 0.10 else ("Monitor" if p < 0.25 else "Material shift")
    stat_card("PSI", f"{p:.3f}", verdict)
with s2:
    comp = pd.concat([
        pd.DataFrame({"Score": low_half, "Segment": f"Limit <= {median_limit:,.0f}"}),
        pd.DataFrame({"Score": high_half, "Segment": f"Limit > {median_limit:,.0f}"}),
    ])
    fig3 = px.histogram(comp, x="Score", color="Segment", nbins=40, barmode="overlay", opacity=0.6)
    style_chart(fig3, None, height=240, xaxis={"title": "Risk score"}, yaxis={"title": "Accounts"})
    st.plotly_chart(fig3, width="stretch")

st.divider()

# --- Fair lending -----------------------------------------------------------
st.markdown("#### Disparate impact review")
st.caption(
    "Sex, marital status, age and education are present in the source and contribute nothing "
    "to any score, because Regulation B prohibits them as a basis for a credit decision. "
    "Excluding an attribute does not guarantee a neutral outcome, so the scorecard's flag "
    "rate is measured across those groups anyway. The four fifths convention treats a ratio "
    "below 0.80 as worth investigating."
)

flagged_col = df["risk_score"] >= cut
review = df.assign(_flagged=flagged_col)

attrs = [c for c in PROTECTED_ATTRIBUTES if c in df.columns and c != "monitor_age"]
tabs = st.tabs([PROTECTED_ATTRIBUTES[c] for c in attrs])
for tab, col in zip(tabs, attrs):
    with tab:
        di = val.disparate_impact(review, col, "_flagged")
        st.dataframe(di, width="stretch", hide_index=True)
        worst = di["Ratio to highest"].min() if len(di) else float("nan")
        if pd.notna(worst):
            if worst < 0.80:
                st.warning(
                    f"Lowest ratio is {worst:.2f}, below the four fifths threshold. In a real "
                    "deployment this would trigger a fair lending review, not an automatic "
                    "rejection of the model."
                )
            else:
                st.success(f"Lowest ratio is {worst:.2f}, above the four fifths threshold.")

st.caption(
    "Age is excluded from this view because it is continuous. Regulation B permits age in an "
    "empirically derived, demonstrably sound scoring system under conditions this scorecard "
    "does not attempt to meet, so it is excluded from scoring entirely."
)
