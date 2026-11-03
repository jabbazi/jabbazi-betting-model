"""External research-source registry for JABBAZI scanner provenance.

The registry is intentionally non-secret and non-authoritative. It tells scanner
clients which external research sources are available and what role each source
may play. External sources may confirm or contradict a JABBAZI thesis, but they
must not overwrite a model probability or bypass reliability/portfolio gates.
"""

from __future__ import annotations

import os
from typing import Any


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def external_research_sources() -> dict[str, dict[str, Any]]:
    """Return safe source capabilities without exposing credentials."""

    unabated_key = bool(os.getenv("JABBAZI_UNABATED_API_KEY", "").strip())
    pff_key = bool(os.getenv("JABBAZI_PFF_API_KEY", "").strip())
    optic_key = bool(
        os.getenv("JABBAZI_OPTICODDS_API_KEY", "").strip()
        or os.getenv("JABBAZI_ODDSJAM_API_KEY", "").strip()
    )

    return {
        "unabated": {
            "display_name": "Unabated",
            "mode": "OFFICIAL_API",
            "enabled": unabated_key,
            "credential_configured": unabated_key,
            "role": "sharp-market benchmark, no-vig reference, line movement and price validation",
            "sports": ["multi-sport"],
            "cash_influence": False,
            "notes": "Use as market evidence only; do not replace JABBAZI model probabilities.",
        },
        "outlier": {
            "display_name": "Outlier",
            "mode": "WEB_VALIDATION",
            "enabled": _enabled("JABBAZI_OUTLIER_WEB_ENABLED", True),
            "credential_configured": None,
            "role": "player-prop context, line movement and sportsbook comparison",
            "sports": ["multi-sport"],
            "cash_influence": False,
            "notes": "No verified public developer API is assumed; use only lawfully accessible web research.",
        },
        "pff": {
            "display_name": "PFF",
            "mode": "OFFICIAL_API",
            "enabled": pff_key,
            "credential_configured": pff_key,
            "role": "NFL/CFB grades, premium stats and matchup feature enrichment",
            "sports": ["americanfootball_nfl", "americanfootball_ncaaf"],
            "cash_influence": False,
            "notes": "Feature/context evidence only unless separately validated inside a model artifact.",
        },
        "action_network": {
            "display_name": "Action Network",
            "mode": "WEB_VALIDATION",
            "enabled": _enabled("JABBAZI_ACTION_WEB_ENABLED", True),
            "credential_configured": None,
            "role": "injuries, weather, line movement, betting-market context and news validation",
            "sports": ["multi-sport"],
            "cash_influence": False,
            "notes": "No verified public developer API is assumed; never bypass subscriptions or access controls.",
        },
        "oddsjam_opticodds": {
            "display_name": "OddsJam / OpticOdds",
            "mode": "OFFICIAL_API",
            "enabled": optic_key,
            "credential_configured": optic_key,
            "role": "multi-book odds, alternate markets, props, injuries and historical line validation",
            "sports": ["multi-sport"],
            "cash_influence": False,
            "notes": "Treat overlapping sportsbook prices as correlated market evidence, not independent votes.",
        },
    }
