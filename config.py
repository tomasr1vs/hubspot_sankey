"""Static config: outcome classification, dimension property names, period presets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


PIPELINE_LABELS = {
    "Direct Sales": "Direct Sales",
    "Channel Sales": "Channel Sales",
    "Partnerships": "Partnerships",
}

OPEN = "Open"
WON = "Closed Won"
LOST = "Closed Lost"
DORMANT = "Closed Dormant"

OUTCOMES = [WON, OPEN, LOST, DORMANT]
OUTCOME_PRIORITY = {WON: 0, OPEN: 1, LOST: 2, DORMANT: 3}

STAGE_LABEL_TO_OUTCOME = {
    "Closed Won": WON,
    "Closed Won- Reseller": WON,
    "Closed Won- Referral": WON,
    "Closed Lost": LOST,
    "Closed lost": LOST,
    "Closed Lost/Dormant": LOST,
    "Closed Dormant": DORMANT,
    "Closed Dormant/Timing": DORMANT,
    "Legacy Vuln": LOST,
}

PIPELINE_STAGE_ORDER = {
    "Direct Sales": [
        "Demo Scheduled",
        "Follow-up",
        "Legal",
        "Closed Won",
        "Closed Lost",
        "Closed Dormant",
    ],
    "Channel Sales": [
        "Scoping Call Scheduled",
        "Follow up",
        "Legal",
        "Closed Won",
        "Closed Dormant/Timing",
        "Closed lost",
    ],
    "Partnerships": [
        "Demo Scheduled",
        "No Opportunity Yet",
        "Opps Presented - None Closed",
        "Closed Won- Reseller",
        "Closed Won- Referral",
        "Closed Lost/Dormant",
        "Legacy Vuln",
    ],
}

DIMENSIONS = {
    "Contact Form Submission": "contact_form_submission",
    "Attributable to Ads": "attributable_to_ads",
    "Demo Source": "demo_source",
}

NULL_BUCKET = "(blank)"


@dataclass(frozen=True)
class Period:
    label: str
    start: date
    end: date


def get_preset_periods(today: date) -> dict[str, Period]:
    """Return preset date ranges relative to `today`."""
    return {
        "2025–2026 YTD": Period("2025–2026 YTD", date(2025, 1, 1), today),
        "2026 YTD": Period("2026 YTD", date(2026, 1, 1), today),
    }
