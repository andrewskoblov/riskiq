"""Per transaction drill down with the full factor breakdown."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from data_service import get_scored_data, sidebar_controls
from risk_engine import score_transaction
from utils import band_badge, empty_state, hero, page_setup, stat_card, style_chart

page_setup("Case Investigation")
profile, _ = sidebar_controls()
df = get_scored_data(profile=profile)

hero("Case Investigation", "Every point of a score traced back to the factor that contributed it.")

if df.empty:
    empty_state("No transactions available. Raise the transaction volume in the sidebar.")
    st.stop()

ranked = df.sort_values("risk_score", ascending=False)
only_flagged = st.checkbox("Show only High and Critical cases", value=True)
pool = ranked[ranked["risk_band"].isin(["Critical", "High"])] if only_flagged else ranked

if pool.empty:
    empty_state(
        "No High or Critical cases in the current population. "
        "Untick the filter above to investigate lower banded transactions."
    )
    st.stop()

labels = [
    f"{r.txn_id}  |  {r.risk_band}  |  score {r.risk_score:.1f}  |  ${r.amount:,.2f}"
    for r in pool.itertuples()
]
choice = st.selectbox("Select a case", labels, index=0)
txn_id = choice.split("  |  ")[0]

row = pool[pool["txn_id"] == txn_id]
if row.empty:
    empty_state("That transaction is no longer in the filtered set.")
    st.stop()

txn = row.iloc[0].to_dict()
result = score_transaction(txn, profile)

st.write("")
c1, c2, c3, c4 = st.columns(4)
with c1:
    stat_card("Risk score", f"{result['score']:.1f}", f"Profile: {profile}")
with c2:
    st.markdown(
        f'<div class="riq-card"><div class="lbl">Band</div>'
        f'<div class="val" style="font-size:1.3rem; margin-top:.35rem;">{band_badge(result["band"])}</div>'
        f'<div class="sub">{result["active_factors"]} factors fired</div></div>',
        unsafe_allow_html=True,
    )
with c3:
    stat_card("Confidence", f"{result['confidence']}%", "evidence and account history")
with c4:
    stat_card("Amount", f"${txn['amount']:,.2f}", str(txn["category"]))

st.write("")
left, right = st.columns([3, 2])

with left:
    st.markdown("#### Score decomposition")
    for f in result["factors"]:
        if f["points"] <= 0 and not f["fired"]:
            continue
        cls = "riq-factor on" if f["fired"] else "riq-factor"
        st.markdown(
            f'<div class="{cls}"><span class="fpts">+{f["points"]:.1f}</span>'
            f'<div class="fname">{f["label"]}</div>'
            f'<div class="fdetail">{f["detail"]}</div></div>',
            unsafe_allow_html=True,
        )

    dormant = [f for f in result["factors"] if f["points"] <= 0 and not f["fired"]]
    if dormant:
        with st.expander(f"{len(dormant)} factors contributed nothing"):
            for f in dormant:
                st.markdown(f"**{f['label']}** &mdash; {f['detail']}".replace("&mdash;", ":"))

with right:
    st.markdown("#### Contribution")
    contributing = [f for f in result["factors"] if f["points"] > 0]
    if not contributing:
        empty_state("No factor contributed points to this score.")
    else:
        fig = go.Figure(go.Bar(
            x=[f["points"] for f in contributing][::-1],
            y=[f["label"] for f in contributing][::-1],
            orientation="h",
            marker={"color": "#4f46e5"},
            text=[f"{f['points']:.1f}" for f in contributing][::-1],
            textposition="outside",
        ))
        style_chart(fig, None, height=max(240, 34 * len(contributing)),
                    xaxis={"title": "Points"}, yaxis={"title": ""}, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Account context")
    st.markdown(
        f"- Account **{txn['account_id']}**, home country **{txn['account_country']}**\n"
        f"- **{txn['account_age_days']}** days old, **{txn['prior_txns']}** prior transactions\n"
        f"- **{txn['prior_chargebacks']}** prior chargeback(s)\n"
        f"- Typical spend **${txn['acct_avg_amount']:,.2f}** (sd ${txn['acct_std_amount']:,.2f})\n"
        f"- **{txn['txns_24h']}** transactions in the last 24 hours\n"
        f"- Email domain **{txn['email_domain']}**"
    )
