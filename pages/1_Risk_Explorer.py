"""Filterable view of the full scored population."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from data_service import get_scored_data, group_column, sidebar_controls
from risk_engine import BAND_COLORS, BANDS
from utils import empty_state, hero, page_setup, stat_card, style_chart

page_setup("Risk Explorer")
profile, source = sidebar_controls()
df, pack = get_scored_data(profile)
GROUP = group_column(df)

hero("Risk Explorer", "Slice the scored population by band, geography, category and score range.")

if df.empty:
    empty_state("No transactions to explore. Raise the transaction volume in the sidebar.")
    st.stop()

f1, f2, f3 = st.columns([2, 2, 3])
with f1:
    bands = st.multiselect("Risk band", BANDS, default=BANDS)
with f2:
    countries = st.multiselect("Country", sorted(df["country"].unique()), default=[])
with f3:
    lo, hi = st.slider("Score range", 0, 100, (0, 100))

view = df[df["risk_band"].isin(bands)]
if countries:
    view = view[view["country"].isin(countries)]
view = view[(view["risk_score"] >= lo) & (view["risk_score"] <= hi)]

if view.empty:
    empty_state("No transactions match these filters. Widen the band, country or score selection.")
    st.stop()

c1, c2, c3 = st.columns(3)
with c1:
    stat_card("Matching", f"{len(view):,}", f"{len(view) / len(df) * 100:.1f}% of population")
with c2:
    stat_card("Total value", f"${view['amount'].sum():,.0f}")
with c3:
    stat_card("Mean score", f"{view['risk_score'].mean():.1f}",
              f"mean confidence {view['confidence'].mean():.0f}%")

st.write("")
left, right = st.columns(2)

with left:
    fig = px.histogram(view, x="risk_score", nbins=28, color="risk_band",
                       color_discrete_map=BAND_COLORS)
    style_chart(fig, "Score distribution", height=330,
                xaxis={"title": "Risk score"}, yaxis={"title": "Transactions"})
    st.plotly_chart(fig, width="stretch")

with right:
    by_cat = view.groupby(GROUP, as_index=False).agg(
        transactions=("txn_id", "count"), mean_score=("risk_score", "mean"))
    by_cat = by_cat.sort_values("mean_score", ascending=True).tail(12)
    fig2 = px.bar(by_cat, x="mean_score", y=GROUP, orientation="h",
                  hover_data=["transactions"])
    style_chart(fig2, f"Mean score by {GROUP}", height=330,
                xaxis={"title": "Mean risk score"}, yaxis={"title": ""})
    st.plotly_chart(fig2, width="stretch")

st.write("")
fig3 = px.scatter(view, x="amount", y="risk_score", color="risk_band",
                  color_discrete_map=BAND_COLORS, size="confidence", size_max=13,
                  hover_data=["txn_id", "account_id", "country"], opacity=0.75)
style_chart(fig3, "Amount against risk score (bubble size is confidence)", height=380,
            xaxis={"title": "Transaction amount (USD)"}, yaxis={"title": "Risk score"})
st.plotly_chart(fig3, width="stretch")

st.write("")
st.markdown("#### Matching transactions")
cols = ["txn_id", "timestamp", "account_id", "amount", GROUP, "country",
        "risk_score", "risk_band", "confidence"]
cols = list(dict.fromkeys(cols))  # GROUP may already be "country"
table = view[cols].sort_values("risk_score", ascending=False)
st.dataframe(
    table, width="stretch", hide_index=True, height=380,
    column_config={
        "txn_id": "Transaction",
        "timestamp": st.column_config.DatetimeColumn("When", format="YYYY-MM-DD HH:mm"),
        "account_id": "Account",
        "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
        "category": "Category",
        "country": "Country",
        "risk_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
        "risk_band": "Band",
        "confidence": st.column_config.NumberColumn("Confidence", format="%d%%"),
    },
)
