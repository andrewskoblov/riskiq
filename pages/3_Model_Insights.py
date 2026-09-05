"""Model behaviour: threshold simulation, factor importance and profile comparison."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_service import get_scored_data, sidebar_controls
from risk_engine import FACTOR_PACKS, PROFILES, score_transaction, thresholds_for, weights_for
from utils import empty_state, hero, page_setup, stat_card, style_chart

page_setup("Model Insights")
profile, source = sidebar_controls()
df, pack = get_scored_data(profile)
FACTORS = FACTOR_PACKS[pack]

hero("Model Insights", "Move the review threshold and watch flagged volume and exposure respond in real time.")

if df.empty:
    empty_state("No transactions to analyse. Raise the transaction volume in the sidebar.")
    st.stop()

# --- Threshold simulator ---------------------------------------------------
st.markdown("#### Threshold simulator")
default_high = thresholds_for(profile, pack)["high"]
threshold = st.slider(
    "Flag every transaction scoring at or above", 0, 100, int(default_high), step=1,
    help="The profile default is shown as the starting position. Drag to see the operational trade off.",
)

flagged = df[df["risk_score"] >= threshold]
caught_value = float(flagged["amount"].sum())
review_rate = len(flagged) / len(df) * 100 if len(df) else 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat_card("Flagged for review", f"{len(flagged):,}", f"{review_rate:.1f}% of volume")
with c2:
    stat_card("Value captured", f"${caught_value:,.0f}", "dollars in the flagged queue")
with c3:
    passed = df[df["risk_score"] < threshold]
    stat_card("Passed through", f"{len(passed):,}", f"${passed['amount'].sum():,.0f} unreviewed")
with c4:
    stat_card("Mean confidence", f"{flagged['confidence'].mean():.0f}%" if len(flagged) else "n/a",
              "on flagged cases")

curve = pd.DataFrame({"threshold": range(0, 101)})
curve["flagged"] = [int((df["risk_score"] >= t).sum()) for t in curve["threshold"]]
curve["value"] = [float(df.loc[df["risk_score"] >= t, "amount"].sum()) for t in curve["threshold"]]

fig = go.Figure()
fig.add_trace(go.Scatter(x=curve["threshold"], y=curve["flagged"], name="Transactions flagged",
                         line={"color": "#4f46e5", "width": 2.5}))
fig.add_vline(x=threshold, line_dash="dash", line_color="#dc2626")
style_chart(fig, "Flagged volume across every threshold", height=320,
            xaxis={"title": "Threshold"}, yaxis={"title": "Transactions flagged"})
st.plotly_chart(fig, width="stretch")

st.divider()

# --- Factor importance -----------------------------------------------------
st.markdown("#### What is actually driving scores")

sample = df.head(400).to_dict("records")
totals = {f.key: 0.0 for f in FACTORS}
labels = {f.key: f.label for f in FACTORS}
fire_counts = {f.key: 0 for f in FACTORS}

for row in sample:
    for c in score_transaction(row, profile, pack)["factors"]:
        totals[c["key"]] += c["points"]
        if c["fired"]:
            fire_counts[c["key"]] += 1

imp = pd.DataFrame({
    "Factor": [labels[k] for k in totals],
    "Total points": [round(v, 1) for v in totals.values()],
    "Times fired": [fire_counts[k] for k in totals],
}).sort_values("Total points", ascending=True)

left, right = st.columns(2)
with left:
    fig2 = px.bar(imp, x="Total points", y="Factor", orientation="h", hover_data=["Times fired"])
    style_chart(fig2, f"Cumulative contribution over {len(sample)} transactions", height=380,
                xaxis={"title": "Total points contributed"}, yaxis={"title": ""})
    st.plotly_chart(fig2, width="stretch")

with right:
    weights = weights_for(profile, pack)
    wdf = pd.DataFrame({
        "Factor": [labels[k] for k in weights],
        "Weight": list(weights.values()),
    }).sort_values("Weight", ascending=True)
    fig3 = px.bar(wdf, x="Weight", y="Factor", orientation="h")
    style_chart(fig3, f"Configured weights for the {profile} profile", height=380,
                xaxis={"title": "Maximum points available"}, yaxis={"title": ""})
    st.plotly_chart(fig3, width="stretch")

st.divider()

# --- Profile comparison ----------------------------------------------------
st.markdown("#### How the four profiles score the same traffic")

base = df.drop(columns=["risk_score", "risk_band", "confidence", "active_factors"], errors="ignore")
subset = base.head(300).to_dict("records")

rows = []
for name in PROFILES:
    scores = [score_transaction(r, name, pack)["score"] for r in subset]
    high_cut = thresholds_for(name, pack)["high"]
    flagged_n = sum(1 for s in scores if s >= high_cut)
    rows.append({
        "Profile": name,
        "Mean score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "Flagged at profile threshold": flagged_n,
        "Flag rate": f"{flagged_n / len(scores) * 100:.1f}%" if scores else "n/a",
        "High threshold": high_cut,
    })

st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
st.caption(
    f"Computed on the same {len(subset)} transactions, rescored under each profile. "
    "Differences come entirely from the weights and thresholds, not from different data."
)
