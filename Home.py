"""RiskIQ overview dashboard."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_service import REAL, REPO_URL, get_scored_data, sidebar_controls
from risk_engine import BAND_COLORS, BANDS, thresholds_for
from utils import band_badge, empty_state, hero, page_setup, stat_card, style_chart

page_setup("Overview")
profile, source = sidebar_controls()
df, pack = get_scored_data(profile)

hero(
    "RiskIQ",
    "Explainable transaction risk scoring. Every score decomposes into the factors that "
    "produced it, weighted by a profile you choose, and carries a confidence value that "
    "reflects how much corroborating evidence stands behind it.",
    link=REPO_URL,
)

if df.empty:
    empty_state("No transactions in the current selection. Raise the transaction volume in the sidebar.")
    st.stop()

st.caption(
    f"**{source}** &nbsp;|&nbsp; {len(df):,} transactions &nbsp;|&nbsp; "
    f"{profile} profile &nbsp;|&nbsp; {pack} factor pack"
)

flagged = df[df["risk_band"].isin(["Critical", "High"])]
value_at_risk = float(flagged["amount"].sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat_card("Transactions scored", f"{len(df):,}",
              "Real data" if source == REAL else "Synthetic data")
with c2:
    stat_card("Flagged (High + Critical)", f"{len(flagged):,}",
              f"{len(flagged) / len(df) * 100:.1f}% of volume")
with c3:
    stat_card("Value at risk", f"${value_at_risk:,.0f}",
              f"of ${df['amount'].sum():,.0f} total")
with c4:
    stat_card("Mean confidence", f"{df['confidence'].mean():.0f}%",
              "across all scored transactions")

st.write("")

left, right = st.columns([3, 2])

with left:
    counts = df["risk_band"].value_counts().reindex(BANDS).fillna(0).astype(int).reset_index()
    counts.columns = ["Band", "Transactions"]
    fig = px.bar(counts, x="Band", y="Transactions", color="Band",
                 color_discrete_map=BAND_COLORS, text="Transactions")
    fig.update_traces(textposition="outside", cliponaxis=False)
    style_chart(fig, "Risk distribution", height=360, showlegend=False)
    st.plotly_chart(fig, width="stretch")

with right:
    mean_score = float(df["risk_score"].mean())
    t = thresholds_for(profile, pack)
    gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=mean_score,
        number={"suffix": " avg", "font": {"size": 30}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": "#4f46e5", "thickness": 0.7},
            "borderwidth": 0,
            "steps": [
                {"range": [0, t["medium"]], "color": "#d1fae5"},
                {"range": [t["medium"], t["high"]], "color": "#fef3c7"},
                {"range": [t["high"], t["critical"]], "color": "#ffedd5"},
                {"range": [t["critical"], 100], "color": "#fee2e2"},
            ],
        },
    ))
    style_chart(gauge, "Portfolio risk level", height=360)
    st.plotly_chart(gauge, width="stretch")

st.write("")
st.markdown("#### Highest risk transactions")

top = df.nlargest(10, "risk_score")[
    ["txn_id", "timestamp", "account_id", "amount", "country", "risk_score", "risk_band", "confidence"]
].copy()

if top.empty:
    empty_state("Nothing scored yet.")
else:
    top["Band"] = top["risk_band"].map(band_badge)
    top["Amount"] = top["amount"].map(lambda v: f"${v:,.2f}")
    top["Score"] = top["risk_score"].map(lambda v: f"{v:.1f}")
    top["Confidence"] = top["confidence"].map(lambda v: f"{v}%")
    top["When"] = top["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    view = top[["txn_id", "When", "account_id", "Amount", "country", "Score", "Band", "Confidence"]]
    view.columns = ["Transaction", "When", "Account", "Amount", "Country", "Score", "Band", "Confidence"]
    st.markdown(view.to_html(escape=False, index=False), unsafe_allow_html=True)

st.write("")
st.caption("Open Case Investigation from the sidebar to see the full factor breakdown for any transaction.")
