"""Read-only BALLDONTLIE LAB player-model research, isolated from odds and wagering.

The regular BALLDONTLIE Player Props API contains *bookmaker odds*, not
calibrated hit probabilities. LAB predictions may contain statistical
projections and confidence scores; confidence is NOT a verified hit probability.
Nothing returned here is eligible to authorize a bet or replace JABBAZI models.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

BASE = "https://api.balldontlie.io"
SPORTS = {"NBA": "nba", "NFL": "nfl", "NHL": "nhl"}
# Per published BDL LAB model-type docs: NHL supports game models only.
LAB_PLAYER_PROP_SPORTS = frozenset({"NBA", "NFL"})
MAX_MODEL_PAGES = 4
MAX_MODELS_PER_SPORT = 12
MAX_PREDICTION_PAGES = 3
MAX_REQUESTS = 35
MAX_RESPONSE_BYTES = 2_000_000


class LabUnavailable(Exception):
    """A redacted provider error code; never includes request URL or payload."""


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def _name(value):
    return str(value)[:100] if isinstance(value, str) and value.strip() else None


class LabReader:
    """Quota-bounded and fail-closed; uses existing key without changing billing."""

    def __init__(self, key: str, *, transport=None, budget=MAX_REQUESTS):
        self._key = key.strip()
        self._remaining = budget
        self._client = httpx.Client(
            base_url=BASE, transport=transport, timeout=12,
            follow_redirects=False,
        )

    def close(self):
        self._client.close()

    def _get(self, path: str, params: dict) -> dict:
        if not self._key:
            raise LabUnavailable("NO_CREDENTIAL")
        if self._remaining <= 0:
            raise LabUnavailable("REQUEST_BUDGET_EXHAUSTED")
        self._remaining -= 1
        try:
            with self._client.stream("GET", path, params=params,
                                     headers={"Authorization": self._key}) as response:
                if response.status_code != 200:
                    code = response.status_code
                    if code in (401, 403):
                        raise LabUnavailable("LAB_ACCESS_DENIED")
                    if code == 429:
                        raise LabUnavailable("LAB_RATE_LIMITED")
                    raise LabUnavailable(f"LAB_HTTP_{code}" if code in (400, 404, 500, 502, 503) else "LAB_HTTP_ERROR")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise LabUnavailable("RESPONSE_TOO_LARGE")
            import json
            value = json.loads(raw)
        except LabUnavailable:
            raise
        except Exception:
            raise LabUnavailable("LAB_TRANSPORT_OR_SCHEMA_ERROR") from None
        if (not isinstance(value, dict) or
                not isinstance(value.get("data"), list) or
                any(not isinstance(row, dict) for row in value["data"]) or
                not isinstance(value.get("meta", {}), dict)):
            raise LabUnavailable("LAB_INVALID_SCHEMA")
        return value

    def pages(self, path: str, params: dict, *, limit: int):
        items = []
        cursors = set()
        cursor = None
        for page in range(limit):
            query = {**params}
            if cursor is not None:
                query["cursor"] = cursor
            payload = self._get(path, query)
            items.extend(payload["data"])
            cursor = payload["meta"].get("next_cursor")
            if cursor is None:
                return items, True
            if (isinstance(cursor, bool) or
                    not isinstance(cursor, (str, int)) or
                    not str(cursor) or
                    str(cursor) in cursors):
                raise LabUnavailable("LAB_BAD_CURSOR")
            cursors.add(str(cursor))
        return items, False


def _project(row: dict, model: dict):
    """Allowlist safe fields. Neither LAB score nor confidence is a hit chance."""
    model_id = _positive_id(model.get("id"))
    game = row.get("game") if isinstance(row.get("game"), dict) else {}
    player = row.get("player") if isinstance(row.get("player"), dict) else {}
    prediction_model = _positive_id(row.get("model_id"))
    if prediction_model is not None and prediction_model != model_id:
        return None
    value = _number(row.get("predicted_value"))
    if value is None:
        return None
    confidence = _number(row.get("confidence"))
    if confidence is not None and not (0 <= confidence <= 1):
        confidence = None
    return {
        "id": _positive_id(row.get("id")),
        "sport": str(model["sport"]).upper(),
        "model_id": model_id,
        "model_name": _name(model.get("name")),
        "market": _name(model.get("prop_type")),
        "game_id": _positive_id(row.get("game_id")) or _positive_id(game.get("id")),
        "player_id": _positive_id(row.get("player_id")) or _positive_id(player.get("id")),
        "player_name": _name(row.get("player_name")) or _name(player.get("name")),
        "starts_at": _name(game.get("date")) or _name(game.get("datetime")),
        # LAB predicted_value is a MODEL SIGNAL/SCORE, not a projected stat total.
        "predicted_value": value,
        "model_signal_value": value,
        "stat_total_projection": None,
        "stat_total_projection_verified": False,
        "predicted_side": _name(row.get("predicted_side")),
        "market_line": _number(row.get("market_value")),
        "provider_confidence_raw": confidence,
        "model_hit_probability": None,
        "hit_probability_verified": False,
        "created_at": _name(row.get("created_at")),
        "provenance": "BALLDONTLIE_LAB_PROJECTION",
        "approval": "RESEARCH_ONLY",
    }


def read_paid_player_models(key: str, sport: str, slate_date: date, *, transport=None):
    """Return a bounded, VIP-only per-sport snapshot of saved LAB predictions.

    No model creation or generation job is triggered, and ordinary scanner
    credits remain unchanged. An incomplete page, missing entitlement or
    empty model/prediction set never becomes a success verdict.
    """
    if sport not in SPORTS:
        raise ValueError("Unsupported sport")
    if not isinstance(slate_date, date):
        raise ValueError("Invalid slate date")
    report: dict[str, Any] = {
        "provider": "BALLDONTLIE_LAB", "sport": sport,
        "slate_date": slate_date.isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "state": "UNAVAILABLE", "reason": "NO_CREDENTIAL",
        "models_found": 0, "models_checked": 0,
        "predictions_seen": 0, "rows": [],
        "coverage_complete": False, "betting_enabled": False,
        "model_hit_probabilities_verified": False,
        "source_player_prop_supported": sport in LAB_PLAYER_PROP_SPORTS,
        "notice": "BDL LAB model score and confidence are not projected stat totals or calibrated hit chances. NHL LAB has game models only. Live sportsbook prop odds are separate. Research only.",
    }
    if sport not in LAB_PLAYER_PROP_SPORTS:
        # Prevent a misleading NHL API fetch, success state, or fabricated props.
        report["reason"] = "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
        return report
    if not key or not key.strip():
        return report
    client = LabReader(key, transport=transport)
    try:
        models, complete = client.pages(
            "/lab/v1/models", {"sport": SPORTS[sport], "per_page": 100},
            limit=MAX_MODEL_PAGES,
        )
        owned = [
            m for m in models
            if m.get("sport") == SPORTS[sport]
            and m.get("model_type") == "player_prop"
            and _positive_id(m.get("id")) is not None
        ]
        report["models_found"] = len(owned)
        if not complete or len(owned) > MAX_MODELS_PER_SPORT:
            report["reason"] = "MODEL_COVERAGE_LIMIT"
            # Don't silently truncate a model set and call it full coverage.
            return report
        seen = set()
        for model in owned:
            report["models_checked"] += 1
            rows, fully_paged = client.pages(
                "/lab/v1/predictions", {
                    "model_id": model["id"],
                    "start_date": slate_date.isoformat(),
                    "end_date": (slate_date + timedelta(days=1)).isoformat(),
                    "per_page": 100,
                }, limit=MAX_PREDICTION_PAGES,
            )
            if not fully_paged:
                report["reason"] = "PREDICTION_COVERAGE_LIMIT"
                report["rows"] = []  # no deceptively complete board
                return report
            report["predictions_seen"] += len(rows)
            for row in rows:
                item = _project(row, model)
                if item is None:
                    continue
                identity = (item["model_id"], item["id"], item["game_id"], item["player_id"])
                if identity in seen:
                    continue
                seen.add(identity)
                report["rows"].append(item)
        report["coverage_complete"] = True
        report["state"] = "RESEARCH_ONLY" if report["rows"] else "NO_PREDICTIONS"
        report["reason"] = None if report["rows"] else ("NO_PLAYER_PROP_MODELS" if not owned else "NO_PREDICTIONS_ON_DATE")
    except LabUnavailable as exc:
        report["state"] = "UNAVAILABLE"
        report["reason"] = str(exc)
        report["rows"] = []
    finally:
        client.close()
    return report
