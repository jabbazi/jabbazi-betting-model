from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum


class Decision(StrEnum):
    BET_NOW = "BET_NOW"
    WAIT = "WAIT"
    WATCH = "WATCH"
    PASS = "PASS"


class DataQuality(StrEnum):
    REALTIME = "realtime"
    DELAYED = "delayed"
    CACHED = "cached"
    MANUAL = "manual"
    FIXTURE = "fixture"


@dataclass(frozen=True)
class Quote:
    provider_quote_id: str
    event_id: str
    market_key: str
    selection_key: str
    sportsbook: str
    decimal_odds: Decimal
    line: Decimal | None
    observed_at: datetime
    source_timestamp: datetime
    quality: DataQuality
    sport: str | None = None
    event_name: str | None = None
    commence_time: datetime | None = None

    def age_seconds(self, now: datetime | None = None) -> Decimal:
        now = now or datetime.now(timezone.utc)
        return Decimal(str((now - self.source_timestamp).total_seconds()))


@dataclass(frozen=True)
class Candidate:
    event_id: str
    market_key: str
    selection_key: str
    model_probability: Decimal
    uncertainty: Decimal
    model_version: str
    quotes: tuple[Quote, ...]
    exposure_tags: frozenset[str] = field(default_factory=frozenset)
    model_validated: bool = False


@dataclass(frozen=True)
class Recommendation:
    decision: Decision
    reason: str
    best_sportsbook: str | None
    best_decimal_odds: Decimal | None
    market_probability: Decimal | None
    adjusted_probability: Decimal
    ev: Decimal | None
    stake: Decimal
    max_playable_decimal: Decimal | None
    quote_ids: tuple[str, ...]
