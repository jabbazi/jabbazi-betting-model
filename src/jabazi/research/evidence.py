"""Versioned append-only research evidence on the existing transactional event store."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from jabazi.persistence.store import digest


class SourcePick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source: str = Field(min_length=1, max_length=120)
    original_selection: str = Field(min_length=1, max_length=2000)
    posted_at: datetime
    observed_at: datetime
    sport: str
    event_id: str
    market: str
    selection: str
    period: str = "full_game"
    settlement_key: str
    line: Decimal | None = None
    odds_decimal: Decimal | None = Field(None, gt=1)
    claimed_units: Decimal | None = Field(None, ge=0)
    supplied_probability: Decimal | None = Field(None, ge=0, le=1)
    source_url: str | None = None
    independently_agreed: bool | None = None

    @model_validator(mode="after")
    def times(self):
        if (
            self.posted_at.tzinfo is None
            or self.observed_at.tzinfo is None
            or self.posted_at > self.observed_at
        ):
            raise ValueError("Verified aware source timestamps required")
        return self


class PriceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    candidate_id: str
    phase: Literal[
        "opening",
        "first_observation",
        "model_prediction",
        "recommendation",
        "confirmed_entry",
        "closing",
        "result",
        "correction",
    ]
    at: datetime
    event_id: str
    market: str
    selection: str
    line: Decimal | None = None
    period: str = "full_game"
    settlement_key: str
    decimal_odds: Decimal | None = Field(None, gt=1)
    no_vig_probability: Decimal | None = Field(None, ge=0, le=1)
    stake_dollars: Decimal | None = Field(None, ge=0)
    model_version: str | None = None
    evidence_id: str
    corrects: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def audit(self):
        if self.at.tzinfo is None:
            raise ValueError("Timezone required")
        if self.phase == "correction" and not (self.corrects and self.reason):
            raise ValueError("Correction reference and reason required")
        return self


def freeze_source(store, pick):
    payload = SourcePick.model_validate(pick).model_dump(mode="json")
    identity = digest(
        ["source_pick", payload["source"], payload["posted_at"], payload["original_selection"]]
    )
    store.append("source_pick", payload["event_id"], payload, identity)
    return identity


def record_lifecycle(store, event):
    payload = PriceLifecycleEvent.model_validate(event).model_dump(mode="json")
    identity = digest(
        ["price_lifecycle", payload["candidate_id"], payload["phase"], payload["evidence_id"]]
    )
    store.append("price_lifecycle", payload["candidate_id"], payload, identity)
    return identity


def persist_clv(store, entry, close):
    identity = ("event_id", "market", "selection", "line", "period", "settlement_key")
    if any(entry.get(k) != close.get(k) for k in identity):
        raise ValueError("CLV market/settlement mismatch")
    if entry["phase"] != "confirmed_entry" or close["phase"] != "closing":
        raise ValueError("Entry and close required")
    a = PriceLifecycleEvent.model_validate(entry)
    b = PriceLifecycleEvent.model_validate(close)
    if a.at >= b.at or a.decimal_odds is None or b.no_vig_probability is None:
        raise ValueError("Comparable timed prices required")
    payload = dict(
        entry_id=a.evidence_id,
        close_id=b.evidence_id,
        probability_clv=str(b.no_vig_probability - 1 / a.decimal_odds),
        price_clv=str(a.decimal_odds * b.no_vig_probability - 1),
        line_clv=None,
        benchmark="closing_no_vig_consensus",
        schema_version=1,
    )
    key = digest(["clv_record", a.candidate_id, a.evidence_id, b.evidence_id])
    store.append("clv_record", a.candidate_id, payload, key)
    return payload


def freeze_forecast(store, *, prediction_id, starts_at, predicted_at, payload):
    if starts_at.tzinfo is None or predicted_at.tzinfo is None or predicted_at >= starts_at:
        raise ValueError("Only pregame frozen predictions admitted")
    required = (
        "model_version",
        "feature_schema_version",
        "dataset_hash",
        "code_commit",
        "feature_snapshot",
        "odds_snapshot",
    )
    if any(not payload.get(k) for k in required):
        raise ValueError("Incomplete prediction provenance")
    record = payload | {
        "predicted_at": predicted_at.isoformat(),
        "starts_at": starts_at.isoformat(),
    }
    store.append(
        "frozen_forecast", prediction_id, record, digest(["frozen_forecast", prediction_id])
    )
