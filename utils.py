"""Shared UI helpers: the design system and consistent chart theming."""

from __future__ import annotations

import streamlit as st

INK = "#111827"
MUTED = "#6b7280"
GRID = "#e5e7eb"
ACCENT = "#4f46e5"

CHART_SEQUENCE = ["#4f46e5", "#0891b2", "#7c3aed", "#059669", "#d97706", "#dc2626"]


def page_setup(title: str, icon: str = "shield") -> None:
    st.set_page_config(page_title=f"{title} | RiskIQ", page_icon=":material/security:", layout="wide")
    inject_css()


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, -apple-system, sans-serif; }

        .block-container { padding-top: 2.2rem; max-width: 1280px; }

        .riq-hero {
            background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 55%, #0891b2 100%);
            border-radius: 16px;
            padding: 2rem 2.2rem;
            color: #fff;
            margin-bottom: 1.6rem;
        }
        .riq-hero h1 { font-size: 2.05rem; font-weight: 700; margin: 0 0 .4rem 0; letter-spacing: -.02em; }
        .riq-hero p { font-size: 1rem; opacity: .92; margin: 0; max-width: 62ch; line-height: 1.5; }

        .riq-card {
            background: #fff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 1.1rem 1.25rem;
            height: 100%;
        }
        .riq-card .lbl {
            font-size: .74rem; text-transform: uppercase; letter-spacing: .07em;
            color: #6b7280; font-weight: 600; margin-bottom: .3rem;
        }
        .riq-card .val { font-size: 1.85rem; font-weight: 700; color: #111827; line-height: 1.1; }
        .riq-card .sub { font-size: .82rem; color: #6b7280; margin-top: .25rem; }

        .riq-badge {
            display: inline-block; padding: .2rem .6rem; border-radius: 999px;
            font-size: .75rem; font-weight: 600; letter-spacing: .01em;
        }
        .riq-critical { background: #fee2e2; color: #991b1b; }
        .riq-high     { background: #ffedd5; color: #9a3412; }
        .riq-medium   { background: #fef3c7; color: #92400e; }
        .riq-low      { background: #d1fae5; color: #065f46; }

        .riq-factor {
            border-left: 3px solid #e5e7eb;
            padding: .5rem .85rem; margin-bottom: .5rem; background: #f9fafb;
            border-radius: 0 8px 8px 0;
        }
        .riq-factor.on { border-left-color: #dc2626; background: #fef8f8; }
        .riq-factor .fname { font-weight: 600; font-size: .9rem; color: #111827; }
        .riq-factor .fdetail { font-size: .84rem; color: #6b7280; margin-top: .15rem; line-height: 1.45; }
        .riq-factor .fpts { float: right; font-weight: 700; font-size: .9rem; color: #4f46e5; }

        [data-testid="stSidebar"] { background: #f6f7fb; border-right: 1px solid #e5e7eb; }
        footer, #MainMenu { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="riq-hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str, sub: str = "") -> None:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="riq-card"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def band_badge(band: str) -> str:
    return f'<span class="riq-badge riq-{band.lower()}">{band}</span>'


def style_chart(fig, title: str | None = None, height: int = 340, **overrides):
    """Apply consistent theming to a plotly figure.

    Caller supplied ``overrides`` are merged into the base layout dict before a
    single ``update_layout`` call. Building one merged dict is what keeps this
    from raising "got multiple values for keyword argument" when a caller passes
    something the base layout already sets, such as ``margin`` or ``showlegend``.
    """
    layout = {
        "height": height,
        "margin": {"l": 10, "r": 10, "t": 46 if title else 14, "b": 10},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, system-ui, sans-serif", "size": 12, "color": INK},
        "colorway": CHART_SEQUENCE,
        "hoverlabel": {"font_family": "Inter, system-ui, sans-serif"},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0},
        "xaxis": {"gridcolor": GRID, "zeroline": False, "linecolor": GRID},
        "yaxis": {"gridcolor": GRID, "zeroline": False, "linecolor": GRID},
    }
    if title:
        layout["title"] = {"text": title, "font": {"size": 15, "color": INK}, "x": 0, "xanchor": "left"}

    for key, value in overrides.items():
        # Merge one level deep so a caller can tweak a single axis property
        # without discarding the themed defaults for that axis.
        if isinstance(value, dict) and isinstance(layout.get(key), dict):
            merged = dict(layout[key])
            merged.update(value)
            layout[key] = merged
        else:
            layout[key] = value

    fig.update_layout(**layout)
    return fig


def empty_state(message: str) -> None:
    st.markdown(
        f'<div class="riq-card" style="text-align:center; padding:2.4rem 1rem; color:#6b7280;">{message}</div>',
        unsafe_allow_html=True,
    )
