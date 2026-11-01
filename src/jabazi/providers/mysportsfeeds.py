"""Opt-in NFL/NBA transport for provider evaluation; not a model or live feed.

Routes/auth follow the provider's public v2.1 Python wrapper. Real subscription
entitlements, payload contracts and freshness must be verified before ingestion.
"""
import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx

BASE_URL = "https://api.mysportsfeeds.com/v2.1/pull"
LEAGUES = ("nfl", "nba")
DAILY_FEEDS = {"games": "games.json", "player_gamelogs": "player_gamelogs.json"}
GAME_FEEDS = {"boxscore": "boxscore.json", "lineup": "lineup.json", "playbyplay": "playbyplay.json"}


class ProviderUnavailable(RuntimeError):
    """Only controlled error codes, never provider response bodies or credentials."""


def _reject_nonfinite(value):
    raise ValueError("Non-finite JSON number")


@dataclass(frozen=True)
class MSFConfig:
    api_key: str = field(default="", repr=False)
    enabled: bool = False

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("JABBAZI_MSF_API_KEY", "").strip(),
                   os.getenv("JABBAZI_MSF_ENABLED", "false").lower() == "true")

    def readiness(self):
        return {
            "provider": "MySportsFeeds", "leagues": list(LEAGUES),
            "credential_configured": bool(self.api_key.strip()), "enabled": self.enabled,
            "status": ("AWAITING_CREDENTIAL" if not self.api_key.strip() else
                       "DISABLED" if not self.enabled else "READY_FOR_CONNECTIVITY_TEST"),
            "planned_package": "CORE+STATS+DETAILS", "planned_access": "NON_LIVE",
            "connection_verified": False, "schema_verified": False,
            "model_approved": False, "automatic_ingestion_enabled": False,
        }


@dataclass(frozen=True)
class Receipt:
    url: str
    retrieved_at: str
    payload: bytes = field(repr=False)

    def metadata(self):
        return {"provider": "MySportsFeeds", "url": self.url,
                "retrieved_at": self.retrieved_at,
                "sha256": hashlib.sha256(self.payload).hexdigest(),
                "bytes": len(self.payload), "status": "UNVERIFIED_PROVIDER_RESPONSE",
                "schema_verified": False, "model_approved": False}


def feed_path(league, season, feed, *, day=None, game=None):
    if league not in LEAGUES:
        raise ProviderUnavailable("UNSUPPORTED_LEAGUE")
    if not re.fullmatch(r"20\d{2}(?:-20\d{2})?-(regular|playoff|preseason)", season):
        raise ProviderUnavailable("INVALID_SEASON")
    if feed in DAILY_FEEDS and isinstance(day, date) and not isinstance(day, datetime) and game is None:
        return f"/{league}/{season}/date/{day:%Y%m%d}/{DAILY_FEEDS[feed]}"
    if feed in GAME_FEEDS and isinstance(game, str) and re.fullmatch(r"[0-9]{1,20}", game) and day is None:
        return f"/{league}/{season}/games/{game}/{GAME_FEEDS[feed]}"
    raise ProviderUnavailable("INVALID_FEED_SELECTOR")


class MSFClient:
    """One bounded evaluation batch; no scheduling or production feature writes."""
    max_requests = 6
    max_bytes = 4 * 1024 * 1024
    cache_seconds = 300

    def __init__(self, config=None, *, transport=None, clock=time.monotonic):
        self.config = config or MSFConfig.from_environment()
        self._transport, self._clock = transport, clock
        self._cache = {}
        self.requests = 0

    def fetch(self, league, season, feed, *, day=None, game=None):
        if not self.config.enabled:
            raise ProviderUnavailable("DISABLED")
        if not self.config.api_key.strip():
            raise ProviderUnavailable("AWAITING_CREDENTIAL")
        path = feed_path(league, season, feed, day=day, game=game)
        now = self._clock()
        cached = self._cache.get(path)
        if cached and 0 <= now - cached[0] < self.cache_seconds:
            return cached[1]
        for attempt in range(2):
            if self.requests >= self.max_requests:
                raise ProviderUnavailable("BATCH_REQUEST_LIMIT")
            self.requests += 1
            try:
                result = self._request(BASE_URL + path)
            except (httpx.TimeoutException, httpx.NetworkError):
                code = "PROVIDER_NETWORK_UNAVAILABLE"
            except httpx.HTTPError:
                raise ProviderUnavailable("PROVIDER_PROTOCOL_ERROR") from None
            else:
                if isinstance(result, Receipt):
                    self._cache[path] = (self._clock(), result)
                    return result
                code = {401: "AUTHENTICATION_FAILED", 403: "FEED_ACCESS_DENIED",
                        429: "RATE_LIMITED", 204: "NO_DATA",
                        304: "NOT_MODIFIED_WITHOUT_FRESH_CACHE"}.get(result, f"HTTP_{result}")
                if result not in {500, 502, 503, 504}:
                    raise ProviderUnavailable(code)
            if attempt == 0:
                time.sleep(0.25)
        raise ProviderUnavailable(code) from None

    def _request(self, url):
        started = self._clock()
        with (
            httpx.Client(auth=httpx.BasicAuth(self.config.api_key.strip(), "MYSPORTSFEEDS"),
                         timeout=10, follow_redirects=False, transport=self._transport) as client,
            client.stream("GET", url, headers={"Accept": "application/json"}) as response,
        ):
            if response.status_code != 200:
                return response.status_code
            body = bytearray()
            for chunk in response.iter_bytes():
                if self._clock() - started > 15:
                    raise ProviderUnavailable("RESPONSE_DEADLINE_EXCEEDED")
                body.extend(chunk)
                if len(body) > self.max_bytes:
                    raise ProviderUnavailable("RESPONSE_TOO_LARGE")
            try:
                payload = json.loads(body, parse_constant=_reject_nonfinite)
            except (ValueError, UnicodeError):
                raise ProviderUnavailable("INVALID_JSON_OBJECT") from None
            if not isinstance(payload, dict):
                raise ProviderUnavailable("INVALID_JSON_OBJECT")
            return Receipt(url, datetime.now(UTC).isoformat(), bytes(body))


def main(argv=None):
    """Default is offline; --probe explicitly authorizes one bounded test batch."""
    from ..config import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="MySportsFeeds readiness / opt-in connection test")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--league", choices=LEAGUES)
    parser.add_argument("--season")
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    config = MSFConfig.from_environment()
    if not args.probe:
        print(json.dumps(config.readiness()))
        return 0
    if not all((args.league, args.season, args.date)):
        parser.error("--probe requires --league, --season and --date")
    try:
        receipt = MSFClient(config).fetch(args.league, args.season, "games", day=args.date)
    except ProviderUnavailable as exc:
        print(json.dumps({"status": "UNAVAILABLE", "reason": str(exc), "model_approved": False}))
        return 1
    print(json.dumps(receipt.metadata()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
