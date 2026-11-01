"""Bounded per-sport paid LAB research audit for owner-triggered full scans.

Paid LAB score/confidence fields are *not* calibrated player hit probabilities.
NHL LAB player props are unsupported; never treat HTTP 200 or sportsbook odds
as evidence of calibrated probabilities. This module stores only aggregates.
"""
from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Callable

SPORTS = ("NBA", "NFL", "NHL")
MAX_REQUESTS_PER_SPORT = 20
DEFAULT_REQUESTS_PER_SPORT = 12


def collect_paid_player_research(
    key: str, slate_date: date, *, max_requests_per_sport: int = DEFAULT_REQUESTS_PER_SPORT,
    reader: Callable | None = None,
):
    """Audit all supported LAB sports with an explicit independent quota cap.

    This does not initiate new model training, approve joint odds, or fabricate
    a player threshold hit rate. Each league is isolated so NHL unavailability
    never hides available NBA or NFL evidence.
    """
    if not isinstance(slate_date, date):
        raise ValueError("A valid slate date is required")
    if type(max_requests_per_sport) is not int or not 1 <= max_requests_per_sport <= MAX_REQUESTS_PER_SPORT:
        raise ValueError("Invalid independent paid LAB request budget")
    if reader is None:
        from .vip.paid_models import read_paid_player_models
        reader = read_paid_player_models
    sports = []
    for sport in SPORTS:
        if sport == "NHL":
            sports.append({
                "sport": sport, "state": "UNAVAILABLE",
                "reason": "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED",
                "coverage_complete": False, "models_found": 0,
                "predictions_seen": 0, "research_signal_rows": 0,
                "requests_used": 0, "calibrated_hit_probabilities_verified": False,
                "betting_enabled": False,
            })
            continue
        if not key or not key.strip():
            sports.append({
                "sport": sport, "state": "UNAVAILABLE", "reason": "NO_CREDENTIAL",
                "coverage_complete": False, "models_found": 0,
                "predictions_seen": 0, "research_signal_rows": 0,
                "requests_used": 0, "calibrated_hit_probabilities_verified": False,
                "betting_enabled": False,
            })
            continue
        try:
            report = reader(
                key, sport, slate_date,
            )
            # Never pass raw licensed vendor records or model signals into
            # the scan result/ChatGPT response, even in private account views.
            complete = report.get("coverage_complete") is True
            rows = report.get("rows")
            visible = len(rows) if isinstance(rows, list) and complete else 0
            sports.append({
                "sport": sport,
                "state": report.get("state") if complete else "UNAVAILABLE",
                "reason": report.get("reason") if not complete else None,
                "coverage_complete": complete,
                "models_found": max(0, int(report.get("models_found") or 0)),
                "predictions_seen": max(0, int(report.get("predictions_seen") or 0)),
                "research_signal_rows": visible,
                "requests_used": max(0, int(report.get("requests_used") or 0)),
                "calibrated_hit_probabilities_verified": False,
                "betting_enabled": False,
            })
        except Exception:
            # Fail closed; no credentials or transport exception strings leak.
            sports.append({
                "sport": sport, "state": "UNAVAILABLE",
                "reason": "PAID_RESEARCH_UNAVAILABLE",
                "coverage_complete": False, "models_found": 0,
                "predictions_seen": 0, "research_signal_rows": 0,
                "requests_used": 0, "calibrated_hit_probabilities_verified": False,
                "betting_enabled": False,
            })
    return {
        "slate_date": slate_date.isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "mode": "RESEARCH_ONLY",
        "source": "BALLDONTLIE_LAB_SAVED_PLAYER_MODEL_SIGNALS",
        "sports": sports,
        "all_paid_player_hit_probabilities_verified": False,
        "all_sports_coverage_complete": all(
            item["coverage_complete"] for item in sports
        ),
        "model_calibration_approved": False,
        "betting_enabled": False,
        "notice": (
            "Each owner full scan audits NBA/NFL paid LAB model signals within "
            "an independent capped request budget. LAB signals/confidence and "
            "Sports API bookmaker prices are NOT calibrated model hit chances. "
            "NHL LAB player props are unsupported; NHL sportsbook prop coverage "
            "and JABBAZI NHL model validation require separate audits. "
            "Truncated/missing/denied data stay UNAVAILABLE."
        ),
    }
