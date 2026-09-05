"""Cached data access plus the shared sidebar controls.

Two sources are available. The real source is the UCI Online Retail II dataset,
scored with the retail factor pack. The synthetic source is generated locally
and scored with the full factor pack, which includes signals such as device
fingerprint and email domain that real open datasets rarely publish.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import real_data
from data_generator import generate_transactions
from risk_engine import PROFILES, score_dataframe

DEFAULT_RECORDS = 650
DEFAULT_SEED = 42
DEFAULT_REAL_ROWS = 8000

REPO_URL = "https://github.com/andrewskoblov/riskiq"

REAL = "Real (UCI Online Retail II)"
SYNTHETIC = "Synthetic"
SOURCES = [REAL, SYNTHETIC]

PACK_FOR_SOURCE = {REAL: "retail", SYNTHETIC: "synthetic"}


@st.cache_data(show_spinner=False)
def _load_synthetic(n_records: int, seed: int) -> pd.DataFrame:
    return generate_transactions(n_records=n_records, seed=seed)


@st.cache_data(show_spinner="Loading real transaction data...")
def _load_real(n_rows: int) -> pd.DataFrame:
    df = real_data.load()
    if n_rows and n_rows < len(df):
        df = df.tail(n_rows).reset_index(drop=True)
    # Give the real data the same handles the pages expect.
    df = df.rename(columns={"invoice": "txn_id"})
    df["account_id"] = df["customer_id"]
    return df


@st.cache_data(show_spinner="Scoring transactions...")
def _score(df: pd.DataFrame, profile: str, pack: str) -> pd.DataFrame:
    return score_dataframe(df, profile, pack)


def real_data_available() -> bool:
    return real_data.DATA_PATH.exists()


def get_scored_data(profile: str | None = None) -> tuple[pd.DataFrame, str]:
    """Return (scored dataframe, factor pack) for the active sidebar selection."""
    source = st.session_state.get("source", REAL if real_data_available() else SYNTHETIC)
    profile = profile or st.session_state.get("profile", "General")
    pack = PACK_FOR_SOURCE[source]

    if source == REAL:
        df = _load_real(st.session_state.get("real_rows", DEFAULT_REAL_ROWS))
    else:
        df = _load_synthetic(
            st.session_state.get("n_records", DEFAULT_RECORDS),
            st.session_state.get("seed", DEFAULT_SEED),
        )

    return _score(df, profile, pack), pack


def group_column(df: pd.DataFrame) -> str:
    """The categorical column to break results down by, whichever source is active."""
    return "category" if "category" in df.columns else "country"


def sidebar_controls() -> tuple[str, str]:
    """Render the shared sidebar. Returns the active (profile, source)."""
    has_real = real_data_available()

    with st.sidebar:
        st.markdown("### RiskIQ")
        st.caption("Explainable transaction risk scoring")
        st.divider()

        if has_real:
            source = st.radio("Data source", SOURCES, key="source")
        else:
            source = SYNTHETIC
            st.info("Real dataset not found. Build it with tools/build_real_dataset.py.")

        if source == REAL:
            st.caption(
                f"{real_data.SOURCE_NAME}: 53,628 real invoices from a UK online retailer, "
                "2009 to 2011, aggregated from 1.07 million line items."
            )
            st.slider(
                "Rows to score (most recent)", min_value=1000, max_value=53628,
                value=st.session_state.get("real_rows", DEFAULT_REAL_ROWS),
                step=1000, key="real_rows",
                help="Scoring the full set takes a few seconds on first load, then it is cached.",
            )
        else:
            st.caption("Generated locally, with anomalies injected at a calibrated rate.")
            st.slider(
                "Transaction volume", min_value=100, max_value=2000,
                value=st.session_state.get("n_records", DEFAULT_RECORDS),
                step=50, key="n_records",
            )
            st.number_input(
                "Random seed", min_value=0, max_value=9999,
                value=st.session_state.get("seed", DEFAULT_SEED), step=1, key="seed",
            )

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
        if source == REAL:
            st.caption(
                f"Real transaction data from the [{real_data.SOURCE_NAME}]({real_data.SOURCE_URL}) "
                "dataset. Personal data is not included in the source."
            )
        else:
            st.caption("Synthetic data. No real cardholder information is used anywhere in this app.")

        st.markdown(
            f'<a href="{REPO_URL}" target="_blank" class="riq-repo">View source on GitHub</a>',
            unsafe_allow_html=True,
        )

    return profile, source
