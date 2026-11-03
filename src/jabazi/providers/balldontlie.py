"""Bounded BALLDONTLIE NBA/NFL ingestion, isolated from model approval.

Raw snapshots retain vendor IDs and observation times. They are research inputs,
not drop-in replacements for features fitted on ESPN/nflverse definitions.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.balldontlie.io"
PATHS = {
    sport: {
        "teams": "/v1/teams" if sport == "nba" else "/nfl/v1/teams",
        "games": f"/{sport}/v1/games",
        "stats": f"/{sport}/v1/stats",
        "injuries": f"/{sport}/v1/player_injuries",
        "props": f"/{sport}/v{'2' if sport == 'nba' else '1'}/odds/player_props",
    }
    for sport in ("nba", "nfl")
}


class BallDontLieError(Exception):
    """Only a safe error code is retained; never a URL, body or credential."""


class BallDontLieProvider:
    def __init__(self, api_key, *, transport=None, interval=13.0, budget=12):
        self._key = api_key.strip()
        self._client = httpx.Client(
            base_url=BASE, timeout=15, follow_redirects=False, transport=transport,
        )
        self._interval = max(0, interval)
        self._remaining = budget
        self._last_request = None

    def close(self):
        self._client.close()

    def fetch(self, sport, resource, params=None):
        if not self._key:
            raise BallDontLieError("MISSING_KEY")
        if sport not in PATHS or resource not in PATHS[sport]:
            raise BallDontLieError("UNSUPPORTED_RESOURCE")
        if self._remaining <= 0:
            raise BallDontLieError("REQUEST_BUDGET_EXHAUSTED")
        if self._last_request is not None:
            time.sleep(max(0, self._interval - (time.monotonic() - self._last_request)))
        self._remaining -= 1
        self._last_request = time.monotonic()
        try:
            with self._client.stream(
                "GET", PATHS[sport][resource], params=params,
                headers={"Authorization": self._key},
            ) as response:
                if response.status_code != 200:
                    raise BallDontLieError(f"HTTP_{response.status_code}")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8_000_000:
                        raise BallDontLieError("RESPONSE_TOO_LARGE")
            payload = json.loads(raw)
        except BallDontLieError:
            raise
        except Exception:
            raise BallDontLieError("TRANSPORT_OR_JSON_ERROR") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise BallDontLieError("INVALID_SCHEMA")
        if not all(isinstance(row, dict) for row in payload["data"]):
            raise BallDontLieError("INVALID_SCHEMA")
        if not isinstance(payload.get("meta", {}), dict):
            raise BallDontLieError("INVALID_SCHEMA")
        return payload

    def capture(self, store, *, now=None):
        now = now or datetime.now(UTC)
        day = now.astimezone(ZoneInfo("America/Chicago")).date()
        report = {
            "provider": "BALLDONTLIE", "configured": bool(self._key),
            "diagnostic_version": 2,
            "credential_format_issue": (
                "BEARER_PREFIX" if self._key.lower().startswith("bearer ") else
                "QUOTED_KEY" if self._key.startswith((chr(34), chr(39))) else
                "INTERNAL_WHITESPACE" if any(c.isspace() for c in self._key) else None
            ),
            "observed_at": now.isoformat(), "research_only": True,
            "model_features_enabled": False, "sports": {},
            "coverage": "Bounded sample: first stats/injury page and one event's props per sport; not a full slate scan.",
        }
        if not self._key:
            return report
        for sport in PATHS:
            status = report["sports"][sport] = {}
            status["authentication"], _ = self._capture_one(store, sport, "teams", [])
            auth_error = status["authentication"].get("error")
            if auth_error == "HTTP_429":
                report["rate_limited"] = True
                return report
            if auth_error:
                status["action_required"] = "Free teams endpoint rejected the request; verify the BALLDONTLIE account key before upgrading any plan."
                continue
            season = day.year - (1 if day.month < (8 if sport == "nba" else 3) else 0)
            queries = [
                ("games", [("dates[]", str(day)), ("dates[]", str(day + timedelta(days=1))), ("per_page", 100)]),
                ("stats", [("seasons[]", season), ("per_page", 100)]),
                ("injuries", [("per_page", 100)]),
            ]
            games = []
            for resource, params in queries:
                result = self._capture_one(store, sport, resource, params)
                status[resource] = result[0]
                if resource == "games":
                    games = result[1]
                if result[0].get("error") == "HTTP_429":
                    report["rate_limited"] = True
                    return report
            candidates = [g for g in games if isinstance(g.get("id"), int)]
            if candidates:
                # Entitlement/data-availability probe, not a selected betting event.
                status["props"], _ = self._capture_one(
                    store, sport, "props", [("game_id", candidates[0]["id"])],
                )
                if status["props"].get("error") == "HTTP_429":
                    report["rate_limited"] = True
                    return report
            else:
                status["props"] = {"status": "NOT_TESTED_NO_EVENT"}
        return report

    def _capture_one(self, store, sport, resource, params):
        try:
            payload = self.fetch(sport, resource, params)
        except BallDontLieError as exc:
            return {"status": "UNAVAILABLE", "error": str(exc)}, []
        observed_at = datetime.now(UTC).isoformat()
        meta = payload.get("meta", {})
        snapshot = {
            "provider": "BALLDONTLIE", "sport": sport, "resource": resource,
            "observed_at": observed_at, "query": params, "research_only": True,
            "payload": payload,
            "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        }
        store.append("balldontlie_snapshot", f"{sport}:{resource}", snapshot)
        return {
            "status": "AVAILABLE" if payload["data"] else "ACCESS_OK_EMPTY",
            "rows": len(payload["data"]), "observed_at": observed_at,
            "has_more": meta.get("next_cursor") is not None,
        }, payload["data"]



def verification_summary(report, *, now=None):
    """Safe member-visible status; sample endpoint access is NOT full-slate validation.

    No raw vendor payload, player identifiers, keys, or protected account details
    leave this summary. A provider 200 is not model approval or an executable quote.
    """
    now = now or datetime.now(UTC)
    observed = report.get("observed_at") if isinstance(report, dict) else None
    age = None
    if isinstance(observed, str):
        try:
            stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                age = (now - stamp.astimezone(UTC)).total_seconds()
        except ValueError:
            pass
    fresh = age is not None and 0 <= age <= 6 * 3600
    output = {}
    for sport in ("nba", "nfl"):
        sports = report.get("sports") if isinstance(report, dict) else None
        data = sports.get(sport, {}) if isinstance(sports, dict) else {}
        if not isinstance(data, dict):
            data = {}
        checks = {}
        for resource in ("authentication", "games", "stats", "injuries", "props"):
            entry = data.get(resource, {})
            entry = entry if isinstance(entry, dict) else {}
            checks[resource] = {
                "status": entry.get("status") if entry.get("status") in {
                    "AVAILABLE", "ACCESS_OK_EMPTY", "NOT_TESTED_NO_EVENT",
                    "UNAVAILABLE"} else "NOT_TESTED",
                "sample_rows": entry.get("rows") if isinstance(entry.get("rows"), int)
                    and 0 <= entry["rows"] <= 1000000 else None,
                "error_code": entry.get("error") if isinstance(entry.get("error"), str)
                    and entry["error"] in {
                        "HTTP_401", "HTTP_403", "HTTP_404", "HTTP_429",
                        "MISSING_KEY", "UNSUPPORTED_RESOURCE",
                        "REQUEST_BUDGET_EXHAUSTED", "INVALID_SCHEMA",
                        "RESPONSE_TOO_LARGE", "TRANSPORT_OR_JSON_ERROR"} else None,
            }
        accessible = all(checks[key]["status"] == "AVAILABLE"
                         for key in ("authentication", "games", "stats", "injuries", "props"))
        output[sport.upper()] = {
            "status": "SAMPLE_ACCESS_CONFIRMED" if fresh and accessible else
                      "STALE" if age is not None and not fresh else "NOT_VERIFIED",
            "sample_only": True,
            "full_slate_coverage_verified": False,
            "model_features_verified": False,
            "model_calibration_verified": False,
            "live_executable_prices_verified": False,
            "checks": checks,
        }
    return {
        "provider": "BALLDONTLIE",
        "observed_at": observed if fresh else None,
        "fresh": fresh,
        "sports": output,
        "notice": "One-event provider samples are not full-slate live player-prop verification. Model approval and executable odds require separate validation.",
    }


def provider_status(store, key):
    records = store.list_records("balldontlie_status", 1, entity="nba-nfl")
    return {
        "configured_on_this_service": bool(key),
        "latest_capture": records[0]["payload"] if records else None,
        "model_features_enabled": False,
    }


def capture_once(database_url, key):
    from jabazi.persistence.store import Store

    store = Store(database_url)
    provider = None
    owner = str(uuid.uuid4())
    acquired = False
    try:
        acquired = store.acquire_lease("balldontlie-capture", owner, ttl=600)
        if not acquired:
            return
        records = store.list_records("balldontlie_status", 1, entity="nba-nfl")
        if records:
            last = datetime.fromisoformat(records[0]["payload"]["observed_at"])
            previous = records[0]["payload"]
            endpoints = [endpoint for sport in previous.get("sports", {}).values()
                         for endpoint in sport.values() if isinstance(endpoint, dict)]
            successful = bool(endpoints) and all(not endpoint.get("error") for endpoint in endpoints)
            if (previous.get("diagnostic_version") == 2 and successful
                    and datetime.now(UTC) - last < timedelta(hours=6)):
                return
        provider = BallDontLieProvider(key)
        report = provider.capture(store)
        store.append("balldontlie_status", "nba-nfl", report)
        print("BALLDONTLIE_CAPTURE " + json.dumps(report), flush=True)
    except Exception as exc:
        print("BALLDONTLIE_CAPTURE_FAILED_" + type(exc).__name__, flush=True)
    finally:
        if provider:
            provider.close()
        if acquired:
            store.release_lease("balldontlie-capture", owner)
        store.close()


def _capture_loop(database_url, key):
    while True:
        capture_once(database_url, key)
        time.sleep(6 * 3600)


def start_capture(database_url, key, role):
    # No secret values; useful even when a service is missing the credential.
    print("BALLDONTLIE_CONFIGURATION " + json.dumps({"role": role, "configured": bool(key)}), flush=True)
    if key:
        threading.Thread(target=_capture_loop, args=(database_url, key), daemon=True).start()
