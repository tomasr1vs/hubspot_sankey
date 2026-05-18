"""Thin HubSpot REST client. Pulls pipelines, deals (with stage-entered timestamps), contacts."""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Any, Iterator

import requests

BASE = "https://api.hubapi.com"
SEARCH_PAGE_SIZE = 100


class HubSpotError(RuntimeError):
    pass


def _token() -> str:
    """Prefer Streamlit secrets (cloud), fall back to env (local dev)."""
    try:
        import streamlit as st  # type: ignore

        token = st.secrets.get("HUBSPOT_PRIVATE_APP_TOKEN")
        if token:
            return token
    except Exception:
        pass
    token = os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")
    if not token:
        raise HubSpotError(
            "HUBSPOT_PRIVATE_APP_TOKEN not set. Add it to .env (local) "
            "or Streamlit Cloud → app Settings → Secrets."
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _to_ms(d: date) -> int:
    """HubSpot date filter expects epoch milliseconds, UTC midnight."""
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    url = f"{BASE}{path}"
    for attempt in range(5):
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code >= 400:
            raise HubSpotError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json()
    raise HubSpotError(f"Rate limited 5x on {method} {path}")


def fetch_pipelines() -> dict[str, dict[str, Any]]:
    """Return {pipeline_label: {id, stages: [{id, label, displayOrder, metadata}]}}."""
    data = _request("GET", "/crm/v3/pipelines/deals")
    out: dict[str, dict[str, Any]] = {}
    for p in data.get("results", []):
        stages = sorted(p.get("stages", []), key=lambda s: s.get("displayOrder", 0))
        out[p["label"]] = {
            "id": p["id"],
            "stages": [
                {
                    "id": s["id"],
                    "label": s["label"],
                    "displayOrder": s.get("displayOrder", 0),
                    "metadata": s.get("metadata", {}),
                }
                for s in stages
            ],
        }
    return out


def _stage_id_to_label(pipelines: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {s["id"]: s["label"] for p in pipelines.values() for s in p["stages"]}


def _pipeline_id_to_label(pipelines: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {p["id"]: label for label, p in pipelines.items()}


def _search(path: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        body = dict(payload)
        body["limit"] = SEARCH_PAGE_SIZE
        if after:
            body["after"] = after
        data = _request("POST", path, json=body)
        for r in data.get("results", []):
            yield r
        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            return


def fetch_deals(
    start: date,
    end: date,
    pipelines: dict[str, dict[str, Any]],
    extra_properties: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search deals with createdate in [start, end]. Returns list of property dicts."""
    stage_ids = [s["id"] for p in pipelines.values() for s in p["stages"]]
    date_entered_props = [f"hs_v2_date_entered_{sid}" for sid in stage_ids]

    properties = [
        "dealname",
        "dealstage",
        "pipeline",
        "amount",
        "createdate",
        "closedate",
        "hs_is_closed_won",
        "hs_is_closed",
    ] + date_entered_props + (extra_properties or [])

    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "createdate",
                        "operator": "GTE",
                        "value": str(_to_ms(start)),
                    },
                    {
                        "propertyName": "createdate",
                        "operator": "LTE",
                        "value": str(_to_ms(end)),
                    },
                ]
            }
        ],
        "properties": properties,
        "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
    }
    deals_basic: list[dict[str, Any]] = []
    deal_ids: list[str] = []
    for r in _search("/crm/v3/objects/deals/search", payload):
        props = r.get("properties", {})
        props["_id"] = r.get("id")
        deals_basic.append(props)
        deal_ids.append(r.get("id"))

    contact_ids_by_deal = _batch_read_contact_associations(deal_ids)
    for d in deals_basic:
        d["_contact_ids"] = contact_ids_by_deal.get(d["_id"], [])
    return deals_basic


def _batch_read_contact_associations(deal_ids: list[str]) -> dict[str, list[str]]:
    """For each deal id, return list of associated contact ids. Batch in 100s."""
    out: dict[str, list[str]] = {}
    if not deal_ids:
        return out
    for i in range(0, len(deal_ids), 100):
        chunk = deal_ids[i : i + 100]
        payload = {"inputs": [{"id": did} for did in chunk]}
        data = _request(
            "POST",
            "/crm/v4/associations/deals/contacts/batch/read",
            json=payload,
        )
        for result in data.get("results", []):
            deal_id = result.get("from", {}).get("id")
            if not deal_id:
                continue
            out[deal_id] = [t["toObjectId"] for t in result.get("to", [])]
    return out


def count_distinct_contacts(deals: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    for d in deals:
        for cid in d.get("_contact_ids", []) or []:
            seen.add(str(cid))
    return len(seen)


def fetch_contacts_with_deals(start: date, end: date) -> list[dict[str, Any]]:
    """Search contacts created in [start, end] with >= 1 associated deal."""
    properties = ["createdate", "num_associated_deals", "email"]
    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "createdate",
                        "operator": "GTE",
                        "value": str(_to_ms(start)),
                    },
                    {
                        "propertyName": "createdate",
                        "operator": "LTE",
                        "value": str(_to_ms(end)),
                    },
                    {
                        "propertyName": "num_associated_deals",
                        "operator": "GTE",
                        "value": "1",
                    },
                ]
            }
        ],
        "properties": properties,
    }
    out: list[dict[str, Any]] = []
    for r in _search("/crm/v3/objects/contacts/search", payload):
        props = r.get("properties", {})
        props["_id"] = r.get("id")
        out.append(props)
    return out


def fetch_contacts_total_created(start: date, end: date) -> int:
    """Count of all contacts created in [start, end] (regardless of deals)."""
    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "createdate",
                        "operator": "GTE",
                        "value": str(_to_ms(start)),
                    },
                    {
                        "propertyName": "createdate",
                        "operator": "LTE",
                        "value": str(_to_ms(end)),
                    },
                ]
            }
        ],
        "properties": ["createdate"],
        "limit": 1,
    }
    data = _request("POST", "/crm/v3/objects/contacts/search", json=payload)
    return int(data.get("total", 0))


def list_deal_property_names() -> list[str]:
    """List all deal property internal names. Used to auto-discover dimension properties."""
    data = _request("GET", "/crm/v3/properties/deals")
    return [p["name"] for p in data.get("results", [])]


def resolve_stage_and_pipeline(
    pipelines: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (stage_id_to_label, pipeline_id_to_label)."""
    return _stage_id_to_label(pipelines), _pipeline_id_to_label(pipelines)
