"""Close-rate KPIs and dimension breakdowns."""
from __future__ import annotations

from datetime import date

import pandas as pd

from config import DIMENSIONS, LOST, WON


def close_rate_by_create(deals: pd.DataFrame) -> float:
    """Won / Created — deals whose createdate falls in the period."""
    if deals.empty:
        return 0.0
    created = len(deals)
    won = int((deals["outcome"] == WON).sum())
    return won / created if created else 0.0


def close_rate_by_close(deals: pd.DataFrame, start: date, end: date) -> float:
    """Won / (Won + Lost) for deals whose closedate falls in the period."""
    if deals.empty or "closedate" not in deals.columns:
        return 0.0
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    closed = deals[
        deals["closedate"].notna()
        & (deals["closedate"] >= start_ts)
        & (deals["closedate"] < end_ts)
        & deals["outcome"].isin([WON, LOST])
    ]
    if closed.empty:
        return 0.0
    won = int((closed["outcome"] == WON).sum())
    return won / len(closed)


def kpi_strip(
    deals: pd.DataFrame, contacts_total: int, contacts_with_deals: int, start: date, end: date
) -> dict[str, float | int]:
    return {
        "Contacts created": contacts_total,
        "Contacts with deal": contacts_with_deals,
        "Deals created": len(deals),
        "Closed Won": int((deals["outcome"] == WON).sum()) if not deals.empty else 0,
        "Closed Lost": int((deals["outcome"] == LOST).sum()) if not deals.empty else 0,
        "Open": int((deals["outcome"].isin(["Open"])).sum()) if not deals.empty else 0,
        "Won $": float(deals.loc[deals["outcome"] == WON, "amount"].sum()) if not deals.empty else 0.0,
        "Close rate by create": close_rate_by_create(deals),
        "Close rate by close": close_rate_by_close(deals, start, end),
    }


def close_rates_by_dimension(deals: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Long-format table: dimension, value, deals, won, lost, rate_by_create, rate_by_close."""
    rows: list[dict[str, object]] = []
    for dim in DIMENSIONS.keys():
        if dim not in deals.columns:
            continue
        for value, group in deals.groupby(dim, dropna=False):
            rows.append(
                {
                    "Dimension": dim,
                    "Value": value,
                    "Deals created": len(group),
                    "Won": int((group["outcome"] == WON).sum()),
                    "Lost": int((group["outcome"] == LOST).sum()),
                    "Close rate by create": close_rate_by_create(group),
                    "Close rate by close": close_rate_by_close(group, start, end),
                }
            )
    return pd.DataFrame(rows)
