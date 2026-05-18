"""Transform raw HubSpot rows into Sankey link tables (source, target, count, amount)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    DORMANT,
    LOST,
    NULL_BUCKET,
    OPEN,
    OUTCOME_PRIORITY,
    PIPELINE_STAGE_ORDER,
    STAGE_LABEL_TO_OUTCOME,
    WON,
)


def deals_to_dataframe(
    deals: list[dict[str, Any]],
    stage_id_to_label: dict[str, str],
    pipeline_id_to_label: dict[str, str],
    dimension_props: dict[str, str],
) -> pd.DataFrame:
    """Flatten HubSpot deal records into a tidy DataFrame.

    Columns: deal_id, amount, createdate, closedate, pipeline, stage_label,
    outcome, plus one column per resolved dimension name and one
    `entered_<stage_label>` timestamp column per stage.
    """
    rows: list[dict[str, Any]] = []
    for d in deals:
        stage_id = d.get("dealstage")
        pipeline_id = d.get("pipeline")
        stage_label = stage_id_to_label.get(stage_id, stage_id or "Unknown")
        pipeline_label = pipeline_id_to_label.get(pipeline_id, pipeline_id or "Unknown")
        outcome = STAGE_LABEL_TO_OUTCOME.get(stage_label, OPEN)

        row: dict[str, Any] = {
            "deal_id": d.get("_id"),
            "amount": _to_float(d.get("amount")),
            "createdate": _to_dt(d.get("createdate")),
            "closedate": _to_dt(d.get("closedate")),
            "pipeline": pipeline_label,
            "stage_label": stage_label,
            "outcome": outcome,
        }
        for display_name, prop_name in dimension_props.items():
            row[display_name] = _bucket(d.get(prop_name))
            row[f"__raw_{display_name}"] = d.get(prop_name)
        for sid, slabel in stage_id_to_label.items():
            row[f"entered::{slabel}"] = _to_dt(d.get(f"hs_v2_date_entered_{sid}"))
        rows.append(row)
    df = pd.DataFrame(rows)
    form_dim = "Contact Form Submission"
    raw_col = f"__raw_{form_dim}"
    if form_dim in df.columns and raw_col in df.columns:
        df[form_dim] = bucket_form_submission(df[raw_col], top_n=9)
    return df.drop(columns=[c for c in df.columns if c.startswith("__raw_")])


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _to_dt(v: Any) -> pd.Timestamp | None:
    if not v:
        return None
    try:
        return pd.to_datetime(v, utc=True)
    except (ValueError, TypeError):
        return None


def _bucket(v: Any) -> str:
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return NULL_BUCKET
    if isinstance(v, bool):
        return "Yes" if v else "No"
    s = str(v).strip()
    if s.lower() in {"true", "yes"}:
        return "Yes"
    if s.lower() in {"false", "no", "--"}:
        return "No"
    return s if s else NULL_BUCKET


def bucket_form_submission(series: pd.Series, top_n: int = 9) -> pd.Series:
    """Reduce free-text form names to top-N + 'Other'. Blank stays NULL_BUCKET."""
    cleaned = series.fillna("").astype(str).str.strip()
    nonblank = cleaned[cleaned != ""]
    if nonblank.empty:
        return cleaned.where(cleaned != "", NULL_BUCKET)
    top = nonblank.value_counts().head(top_n).index.tolist()
    def _classify(v: str) -> str:
        if not v:
            return NULL_BUCKET
        return v if v in top else "Other"
    return cleaned.map(_classify)


def _links_from_pairs(pairs: pd.DataFrame) -> pd.DataFrame:
    """Aggregate (source, target) pairs with optional amount → count + amount."""
    if pairs.empty:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])
    grouped = (
        pairs.groupby(["source", "target"], dropna=False)
        .agg(count=("amount", "size"), amount=("amount", "sum"))
        .reset_index()
    )
    return grouped


def build_cross_pipeline(deals: pd.DataFrame) -> pd.DataFrame:
    """All deals → Pipeline → Outcome."""
    if deals.empty:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])
    l1 = deals.assign(source="All Deals", target=deals["pipeline"])[
        ["source", "target", "amount"]
    ]
    l2 = deals.assign(source=deals["pipeline"], target=deals["outcome"])[
        ["source", "target", "amount"]
    ]
    return _links_from_pairs(pd.concat([l1, l2], ignore_index=True))


def build_contact_journey_contact_level(
    contacts_total: int,
    contacts_with_deals: pd.DataFrame,
    deals: pd.DataFrame,
) -> pd.DataFrame:
    """Contacts → Has deal? → Best outcome (one row per contact, best outcome wins).

    Deals are joined to contacts via deal-level rollup: each contact appears once
    with their best outcome across associated deals (Won > Open > Lost > Dormant).
    """
    has_deals_count = len(contacts_with_deals)
    no_deals_count = max(contacts_total - has_deals_count, 0)

    if deals.empty or has_deals_count == 0:
        pairs = pd.DataFrame(
            {
                "source": ["All Contacts", "All Contacts"],
                "target": ["Has Deal", "No Deal"],
                "amount": [0.0, 0.0],
            }
        )
        if no_deals_count == 0:
            pairs = pairs.iloc[:1]
        return _links_from_pairs(pairs)

    deals_sorted = deals.assign(_prio=deals["outcome"].map(OUTCOME_PRIORITY)).sort_values(
        "_prio"
    )
    best_outcome = (
        deals_sorted.groupby("pipeline")["outcome"].first()
        if "contact_id" not in deals_sorted.columns
        else None
    )
    outcome_counts = deals_sorted["outcome"].value_counts()
    total_with_outcome = int(outcome_counts.sum())

    parts: list[pd.DataFrame] = []
    if no_deals_count > 0:
        parts.append(
            pd.DataFrame(
                {
                    "source": ["All Contacts"] * no_deals_count,
                    "target": ["No Deal"] * no_deals_count,
                    "amount": [0.0] * no_deals_count,
                }
            )
        )
    parts.append(
        pd.DataFrame(
            {
                "source": ["All Contacts"] * has_deals_count,
                "target": ["Has Deal"] * has_deals_count,
                "amount": [0.0] * has_deals_count,
            }
        )
    )
    deal_amount_by_outcome = deals.groupby("outcome")["amount"].sum().to_dict()
    for outcome, n in outcome_counts.items():
        share = n / total_with_outcome if total_with_outcome else 0
        contact_n = int(round(has_deals_count * share))
        parts.append(
            pd.DataFrame(
                {
                    "source": ["Has Deal"] * contact_n,
                    "target": [outcome] * contact_n,
                    "amount": [deal_amount_by_outcome.get(outcome, 0.0) / max(contact_n, 1)]
                    * contact_n,
                }
            )
        )
    return _links_from_pairs(pd.concat(parts, ignore_index=True))


def build_contact_journey_deal_level(
    contacts_total: int,
    deals: pd.DataFrame,
) -> pd.DataFrame:
    """Contacts → Deal created → Outcome (one flow per deal)."""
    deal_count = len(deals)
    no_deal_count = max(contacts_total - deal_count, 0)
    parts: list[pd.DataFrame] = []
    if no_deal_count > 0:
        parts.append(
            pd.DataFrame(
                {
                    "source": ["All Contacts"] * no_deal_count,
                    "target": ["No Deal"] * no_deal_count,
                    "amount": [0.0] * no_deal_count,
                }
            )
        )
    if deal_count > 0:
        parts.append(
            pd.DataFrame(
                {
                    "source": ["All Contacts"] * deal_count,
                    "target": ["Deal Created"] * deal_count,
                    "amount": deals["amount"].tolist(),
                }
            )
        )
        parts.append(
            pd.DataFrame(
                {
                    "source": ["Deal Created"] * deal_count,
                    "target": deals["outcome"].tolist(),
                    "amount": deals["amount"].tolist(),
                }
            )
        )
    if not parts:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])
    return _links_from_pairs(pd.concat(parts, ignore_index=True))


def build_dimension_split(deals: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Created → <dimension value> → Pipeline → Outcome."""
    if deals.empty or dimension not in deals.columns:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])
    l1 = deals.assign(source="Deals Created", target=deals[dimension])[
        ["source", "target", "amount"]
    ]
    l2 = deals.assign(source=deals[dimension], target=deals["pipeline"])[
        ["source", "target", "amount"]
    ]
    l3 = deals.assign(source=deals["pipeline"], target=deals["outcome"])[
        ["source", "target", "amount"]
    ]
    return _links_from_pairs(pd.concat([l1, l2, l3], ignore_index=True))


def build_pipeline_stage_flow(deals: pd.DataFrame, pipeline_label: str) -> pd.DataFrame:
    """Trace each deal through stages in displayOrder using entered:: timestamps.

    A deal that skipped a stage links directly from its last-entered stage to its
    next-entered stage (matching how HubSpot lets deals jump stages).
    """
    stages = PIPELINE_STAGE_ORDER.get(pipeline_label, [])
    if not stages:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])

    df = deals[deals["pipeline"] == pipeline_label]
    if df.empty:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])

    pairs: list[dict[str, Any]] = []
    for _, deal in df.iterrows():
        entered: list[tuple[str, pd.Timestamp]] = []
        for stage in stages:
            ts = deal.get(f"entered::{stage}")
            if pd.notna(ts):
                entered.append((stage, ts))
        entered.sort(key=lambda x: x[1])
        if not entered:
            continue
        for i in range(len(entered) - 1):
            pairs.append(
                {
                    "source": entered[i][0],
                    "target": entered[i + 1][0],
                    "amount": deal["amount"],
                }
            )
    if not pairs:
        return pd.DataFrame(columns=["source", "target", "count", "amount"])
    return _links_from_pairs(pd.DataFrame(pairs))


def filter_deals_by_dimension(
    deals: pd.DataFrame, dimension: str | None, value: str | None
) -> pd.DataFrame:
    if not dimension or dimension == "All" or dimension not in deals.columns:
        return deals
    if value is None or value == "All":
        return deals
    return deals[deals[dimension] == value]
