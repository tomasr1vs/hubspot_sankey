"""Streamlit dashboard: HubSpot deal & customer journey Sankeys.

Run: `streamlit run app.py`
Requires HUBSPOT_PRIVATE_APP_TOKEN in env or .streamlit/secrets.toml.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import hubspot_client as hs
import kpis
import transforms as tf
from config import DIMENSIONS, NULL_BUCKET, PIPELINE_STAGE_ORDER, get_preset_periods
from sankey import render_sankey

load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(
    page_title="HubSpot Deal & Customer Journey",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=600, show_spinner=False)
def _load_pipelines() -> dict:
    return hs.fetch_pipelines()


@st.cache_data(ttl=600, show_spinner=False)
def _load_deal_property_names() -> list[str]:
    return hs.list_deal_property_names()


@st.cache_data(ttl=600, show_spinner=False)
def _load_data(start: date, end: date, dimension_props_tuple: tuple[tuple[str, str], ...]):
    pipelines = _load_pipelines()
    stage_id_to_label, pipeline_id_to_label = hs.resolve_stage_and_pipeline(pipelines)
    dimension_props = dict(dimension_props_tuple)

    raw_deals = hs.fetch_deals(
        start, end, pipelines, extra_properties=list(dimension_props.values())
    )
    deals = tf.deals_to_dataframe(
        raw_deals, stage_id_to_label, pipeline_id_to_label, dimension_props
    )
    distinct_contacts = hs.count_distinct_contacts(raw_deals)
    return deals, distinct_contacts, distinct_contacts, pipelines


def _resolve_dimension_props(available: list[str]) -> dict[str, str]:
    """For each DIMENSIONS display name, pick the first matching property internal name.

    Falls back to the default name in config; if missing in HubSpot, the dimension
    column will be all-blank in the dataframe (rendered as `(blank)`).
    """
    resolved: dict[str, str] = {}
    lower_set = {p.lower(): p for p in available}
    for display, default_name in DIMENSIONS.items():
        candidates = [
            default_name,
            display.lower().replace(" ", "_"),
            display.lower().replace(" ", ""),
        ]
        match = next((lower_set[c.lower()] for c in candidates if c.lower() in lower_set), None)
        resolved[display] = match or default_name
    return resolved


# ───────── Sidebar ─────────
st.sidebar.title("Filters")

today = date.today()
presets = get_preset_periods(today)

period_choice = st.sidebar.radio(
    "Date range",
    options=[*presets.keys(), "Custom"],
    index=0,
)
if period_choice in presets:
    start, end = presets[period_choice].start, presets[period_choice].end
else:
    start = st.sidebar.date_input("Start", value=date(2026, 1, 1))
    end = st.sidebar.date_input("End", value=today)

if start > end:
    st.sidebar.error("Start date must be on or before end date.")
    st.stop()

dim_filter = st.sidebar.selectbox(
    "Slice by dimension",
    options=["All", *DIMENSIONS.keys()],
)

if st.sidebar.button("🔄 Refresh from HubSpot"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption(f"Range: {start} → {end}")

# ───────── Data load ─────────
try:
    available_props = _load_deal_property_names()
except hs.HubSpotError as e:
    st.error(str(e))
    st.info(
        "Add your token: create `.env` next to `app.py` with "
        "`HUBSPOT_PRIVATE_APP_TOKEN=...` (scopes: deals/contacts/pipelines read)."
    )
    st.stop()

dimension_props = _resolve_dimension_props(available_props)

with st.spinner("Fetching from HubSpot…"):
    try:
        deals, contacts_total, contacts_with_deals, pipelines = _load_data(
            start, end, tuple(dimension_props.items())
        )
    except hs.HubSpotError as e:
        st.error(f"HubSpot error: {e}")
        st.stop()

if dim_filter != "All" and dim_filter in deals.columns:
    dim_values = ["All", *sorted(v for v in deals[dim_filter].dropna().unique())]
    value_pick = st.sidebar.selectbox(f"{dim_filter} value", options=dim_values)
    deals = tf.filter_deals_by_dimension(deals, dim_filter, value_pick)

# ───────── Header + KPIs ─────────
st.title("HubSpot Deal & Customer Journey")
st.caption(
    f"{period_choice} — {len(deals):,} deals · {contacts_total:,} distinct contacts "
    f"linked to those deals"
)

kpi = kpis.kpi_strip(deals, contacts_total, contacts_with_deals, start, end)
cols = st.columns(7)
cols[0].metric("Contacts", f"{kpi['Contacts created']:,}")
cols[1].metric("Deals", f"{kpi['Deals created']:,}")
cols[2].metric("Won", f"{kpi['Closed Won']:,}")
cols[3].metric("Lost", f"{kpi['Closed Lost']:,}")
cols[4].metric("Open", f"{kpi['Open']:,}")
cols[5].metric("Close rate (create)", f"{kpi['Close rate by create']:.1%}")
cols[6].metric("Close rate (close)", f"{kpi['Close rate by close']:.1%}")

# ───────── Tabs ─────────
tab_overview, tab_contact, tab_deal, tab_dims, tab_pipes, tab_rates = st.tabs(
    [
        "Overview",
        "Contact journey",
        "Deal journey",
        "By dimension",
        "Pipeline stages",
        "Close rates",
    ]
)


def _two_views(links_df: pd.DataFrame, title: str) -> None:
    """Render a Sankey twice: by count and by amount."""
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            render_sankey(links_df, "count", f"{title} — by count"),
            use_container_width=True,
        )
    with right:
        st.plotly_chart(
            render_sankey(links_df, "amount", f"{title} — by $ amount"),
            use_container_width=True,
        )


# Overview
with tab_overview:
    st.subheader("All deals → Pipeline → Outcome")
    _two_views(tf.build_cross_pipeline(deals), "Cross-pipeline outcomes")

# Contact-level journey
with tab_contact:
    st.subheader("Contact-level journey (best outcome per contact)")
    links = tf.build_contact_journey_contact_level(
        contacts_total, pd.DataFrame({"placeholder": [1] * contacts_total}), deals
    )
    _two_views(links, "Contacts → Has deal → Best outcome")
    st.caption(
        "Every contact shown was associated with at least one deal created in "
        "the period. Best-outcome rollup: Won > Open > Lost > Dormant."
    )

# Deal-level journey
with tab_deal:
    st.subheader("Deal-level journey (one flow per deal)")
    _two_views(
        tf.build_contact_journey_deal_level(contacts_total, deals),
        "Contacts → Deal created → Outcome",
    )
    st.caption(
        "A contact with N deals contributes N flows. Use this view when you "
        "care about deal economics (sum of $) rather than per-contact conversion."
    )

# By dimension
with tab_dims:
    st.subheader("Deal outcomes split by attribution dimension")
    for display in DIMENSIONS.keys():
        if display not in deals.columns:
            continue
        st.markdown(f"### {display}")
        _two_views(tf.build_dimension_split(deals, display), display)
        non_blank = (deals[display] != NULL_BUCKET).sum()
        if non_blank == 0:
            st.warning(
                f"All deals are blank for `{display}` (looking up internal name "
                f"`{dimension_props.get(display)}`). Confirm the property exists "
                f"and update `config.DIMENSIONS` if it lives under a different name."
            )

# Pipeline stages
with tab_pipes:
    st.subheader("Per-pipeline stage flow")
    pipeline_tabs = st.tabs(list(PIPELINE_STAGE_ORDER.keys()))
    for tab, pipeline_label in zip(pipeline_tabs, PIPELINE_STAGE_ORDER.keys()):
        with tab:
            st.caption(
                "Each deal walks through the stages it actually entered, in "
                "chronological order (using HubSpot's `hs_v2_date_entered_<stage>`)."
            )
            _two_views(
                tf.build_pipeline_stage_flow(deals, pipeline_label),
                pipeline_label,
            )

# Close rates
with tab_rates:
    st.subheader("Close rates by dimension")
    rates = kpis.close_rates_by_dimension(deals, start, end)
    if rates.empty:
        st.info("No dimension data yet — confirm the property names in `config.py`.")
    else:
        st.dataframe(
            rates.style.format(
                {
                    "Close rate by create": "{:.1%}",
                    "Close rate by close": "{:.1%}",
                }
            ),
            use_container_width=True,
        )
