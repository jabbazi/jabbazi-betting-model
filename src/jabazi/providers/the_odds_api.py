"""Licensed The Odds API adapter.

The adapter never logs or returns the API key. Callers choose the sport and markets
explicitly because each region/market combination consumes quota.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from jabazi.domain.models import DataQuality, Quote
from jabazi.providers.base import OddsProvider, ProviderBatch

Transport = Callable[[str], tuple[bytes, dict[str, str]]]


def _default_transport(url: str) -> tuple[bytes, dict[str, str]]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read(), dict(response.headers.items())


class TheOddsApiProvider(OddsProvider):
    base_url = "https://api.the-odds-api.com/v4/sports"

    def __init__(
        self,
        sport: str,
        markets: tuple[str, ...] = ("h2h", "spreads", "totals"),
        bookmakers: tuple[str, ...] | None = None,
        api_key: str | None = None,
        transport: Transport = _default_transport,
    ) -> None:
        self.sport = sport
        self.markets = markets
        self.bookmakers = (
            bookmakers
            if bookmakers is not None
            else tuple(
                value.strip()
                for value in os.getenv(
                    "JABAZI_BOOKMAKERS",
                    "draftkings,fanduel,williamhill_us,betmgm,betrivers,espnbet",
                ).split(",")
                if value.strip()
            )
        )
        # Up to ten specified books count as one region for quota budgeting.
        if not 1 <= len(set(self.bookmakers)) <= 10 or len(set(self.bookmakers)) != len(
            self.bookmakers
        ):
            raise ValueError("Configure 1–10 distinct sportsbook keys")
        self._api_key = api_key or os.getenv("JABAZI_ODDS_API_KEY", "")
        self._transport = transport
        if not self._api_key:
            raise ValueError("JABAZI_ODDS_API_KEY is required")

    def fetch(self) -> ProviderBatch:
        query = urllib.parse.urlencode(
            {
                "apiKey": self._api_key,
                "regions": "us",
                "markets": ",".join(self.markets),
                "bookmakers": ",".join(self.bookmakers),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
        )
        raw, headers = self._transport(f"{self.base_url}/{self.sport}/odds?{query}")
        return self._parse(raw, headers)

    def fetch_event(self, event_id: str, markets: tuple[str, ...]) -> ProviderBatch:
        """Fetch props, periods, and alternate lines for exactly one event."""
        if not event_id or not markets:
            raise ValueError("event_id and at least one market are required")
        query = urllib.parse.urlencode(
            {
                "apiKey": self._api_key,
                "regions": "us",
                "markets": ",".join(markets),
                "bookmakers": ",".join(self.bookmakers),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
        )
        raw, headers = self._transport(
            f"{self.base_url}/{self.sport}/events/{urllib.parse.quote(event_id)}/odds?{query}"
        )
        return self._parse(raw, headers)

    def list_events(self) -> list[dict]:
        """List live/upcoming events. Provider documents this endpoint as quota-free."""
        query = urllib.parse.urlencode({"apiKey": self._api_key, "dateFormat": "iso"})
        raw, _ = self._transport(f"{self.base_url}/{self.sport}/events?{query}")
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Unexpected events response")
        return payload

    def list_event_markets(self, event_id: str) -> dict[str, set[str]]:
        """Discover recently seen market keys by book before spending deeper-query credits."""
        query = urllib.parse.urlencode(
            {
                "apiKey": self._api_key,
                "regions": "us",
                "bookmakers": ",".join(self.bookmakers),
                "dateFormat": "iso",
            }
        )
        raw, _ = self._transport(
            f"{self.base_url}/{self.sport}/events/{urllib.parse.quote(event_id)}/markets?{query}"
        )
        payload = json.loads(raw)
        result: dict[str, set[str]] = {}
        for book in payload.get("bookmakers", []):
            result[str(book["key"])] = {str(market["key"]) for market in book.get("markets", [])}
        return result

    def _parse(self, raw: bytes, headers: dict[str, str]) -> ProviderBatch:
        fetched_at = datetime.now(timezone.utc)
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = [payload]
        quotes: list[Quote] = []
        for event in payload:
            event_id = str(event["id"])
            event_name = f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"
            commence = event.get("commence_time")
            commence_time = (
                datetime.fromisoformat(str(commence).replace("Z", "+00:00")) if commence else None
            )
            for book in event.get("bookmakers", []):
                sportsbook = str(book["key"])
                for market in book.get("markets", []):
                    market_key = str(market["key"])
                    source_time = market.get("last_update") or book.get("last_update")
                    if not source_time:
                        raise ValueError("Provider source timestamp is missing")
                    timestamp = datetime.fromisoformat(str(source_time).replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        raise ValueError("Provider source timestamp lacks a timezone")
                    for index, outcome in enumerate(market.get("outcomes", [])):
                        point = outcome.get("point")
                        line = Decimal(str(point)) if point is not None else None
                        name = str(outcome["name"])
                        description = outcome.get("description")
                        selection = f"{description}|{name}" if description else name
                        quote_id = (
                            f"{event_id}|{sportsbook}|{market_key}|{selection}|{line}|"
                            f"{timestamp.isoformat()}|{index}"
                        )
                        quotes.append(
                            Quote(
                                provider_quote_id=quote_id,
                                event_id=event_id,
                                market_key=market_key,
                                selection_key=selection,
                                sportsbook=sportsbook,
                                decimal_odds=Decimal(str(outcome["price"])),
                                line=line,
                                observed_at=fetched_at,
                                source_timestamp=timestamp,
                                quality=DataQuality.DELAYED,
                                sport=str(event.get("sport_key", self.sport)),
                                event_name=event_name,
                                commence_time=commence_time,
                            )
                        )
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        integer = lambda key: int(normalized_headers[key]) if normalized_headers.get(key) else None
        return ProviderBatch(
            "the_odds_api",
            fetched_at,
            raw,
            tuple(quotes),
            integer("x-requests-used"),
            integer("x-requests-remaining"),
        )
