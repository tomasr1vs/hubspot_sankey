"""Plotly Sankey renderer. Each link is labeled with value + % of source flow."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from config import DORMANT, LOST, OPEN, WON

NODE_COLORS = {
    WON: "#16a34a",
    LOST: "#dc2626",
    DORMANT: "#9ca3af",
    OPEN: "#2563eb",
    "All Contacts": "#7c3aed",
    "All Deals": "#7c3aed",
    "Deal Created": "#0ea5e9",
    "Deals Created": "#0ea5e9",
    "Has Deal": "#0ea5e9",
    "No Deal": "#9ca3af",
}
DEFAULT_NODE_COLOR = "#64748b"


def _color_for(label: str) -> str:
    return NODE_COLORS.get(label, DEFAULT_NODE_COLOR)


def render_sankey(
    links: pd.DataFrame,
    value_field: str = "count",
    title: str = "",
    height: int = 520,
) -> go.Figure:
    """Build a Plotly Sankey from a links DataFrame (source, target, count, amount).

    Args:
        links: aggregated links table from `transforms.py`.
        value_field: "count" or "amount". Drives both edge thickness and labels.
        title: figure title.
    """
    if links is None or links.empty:
        fig = go.Figure()
        fig.update_layout(
            title=title or "(no data in selected range)",
            height=height,
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig

    df = links.copy()
    if value_field == "amount":
        df["value"] = df["amount"].astype(float)
    else:
        df["value"] = df["count"].astype(float)

    df = df[df["value"] > 0]
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=(title or "") + " — (all values are zero)",
            height=height,
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig

    # percentage of source's outflow each link represents
    source_total = df.groupby("source")["value"].transform("sum")
    df["pct_of_source"] = df["value"] / source_total

    labels = pd.unique(df[["source", "target"]].values.ravel("K")).tolist()
    label_to_idx = {label: i for i, label in enumerate(labels)}

    if value_field == "amount":
        edge_labels = [
            f"${v:,.0f} ({p:.0%})" for v, p in zip(df["value"], df["pct_of_source"])
        ]
        hover_template = (
            "%{source.label} → %{target.label}<br>"
            "$%{value:,.0f}<br>"
            "%{customdata:.1%} of source<extra></extra>"
        )
    else:
        edge_labels = [
            f"{int(v):,} ({p:.0%})" for v, p in zip(df["value"], df["pct_of_source"])
        ]
        hover_template = (
            "%{source.label} → %{target.label}<br>"
            "%{value:,} deals<br>"
            "%{customdata:.1%} of source<extra></extra>"
        )

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                label=labels,
                color=[_color_for(l) for l in labels],
                pad=18,
                thickness=18,
                line=dict(color="white", width=0.5),
            ),
            link=dict(
                source=[label_to_idx[s] for s in df["source"]],
                target=[label_to_idx[t] for t in df["target"]],
                value=df["value"].tolist(),
                label=edge_labels,
                customdata=df["pct_of_source"].tolist(),
                hovertemplate=hover_template,
                color="rgba(100, 116, 139, 0.35)",
            ),
        )
    )
    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=20, r=20, t=50, b=20),
        font=dict(size=12),
    )
    return fig
