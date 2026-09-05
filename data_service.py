"""Cached data access plus the shared sidebar controls.

Every page calls :func:`get_scored_data`, so the generator and the scoring pass
run once per (records, seed, profile) combination rather than on every rerun.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_generator import generate_transactions
from risk_engine import PROFILES, score_dataframe

DEFAULT_RECORDS = 650
DEFAULT_SEED = 42


@st.cache_data(show_spinner=False)
def _load(n_records: int, seed: int) -> pd.DataFrame:
    return generate_transactions(n_records=n_records, seed=seed)


@st.cache_data(show_spinner=False)
def _score(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    return score_dataframe(df, profile)


def get_scored_data(n_records: int | None = None, seed: int | None = None,
                    profile: str | None = None) -> pd.DataFrame:
    n_records = n_records if n_records is not None else st.session_state.get("n_records", DEFAULT_RECORDS)
    seed = seed if seed is not None else st.session_state.get("seed", DEFAULT_SEED)
    profile = profile or st.session_state.get("profile", "General")
    return _score(_load(n_records, seed), profile)


def sidebar_controls() -> tuple[str, int]:
    """Render the shared sidebar. Returns the active (profile, n_records)."""
    with st.sidebar:
        st.markdown("### RiskIQ")
        st.caption("Explainable transaction risk scoring")
        st.divider()

        profile = st.selectbox(
            "Risk profile",
            list(PROFILES.keys()),
            index=list(PROFILES.keys()).index(st.session_state.get("profile", "General")),
            key="profile",
            help="Each profile reweights the same factors for a different business model.",
        )
        st.caption(PROFILES[profile]["blurb"])

        st.divider()
        n_records = st.slider(
            "Transaction volume", min_value=100, max_value=2000,
            value=st.session_state.get("n_records", DEFAULT_RECORDS),
            step=50, key="n_records",
        )
        st.number_input(
            "Random seed", min_value=0, max_value=9999,
            value=st.session_state.get("seed", DEFAULT_SEED), step=1, key="seed",
            help="Change the seed to draw a different synthetic population.",
        )

        st.divider()
        st.caption("Synthetic data. No real cardholder information is used anywhere in this app.")

    return profile, n_records
