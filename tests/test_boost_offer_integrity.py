"""Synthetic vendor contract fixtures only; no paid access or model approval."""
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_offer_integrity import inspect_prop_offer


NOW = datetime(2026, 10, 28, 5, tzinfo=UTC)


def quote(**overrides):
    data = dict(
        id=123, game_id=456, player_id=789,
        vendor="draftkings", prop_type="points",
        line_value="20.5",
        market={"type": "over_under", "over_odds": -110,
                "under_odds": -110},
        updated_at=(NOW - timedelta(minutes=2)).isoformat(),
    )
    data.update(overrides)
    return data


def check(data):
    return inspect_prop_offer(data, 456, observed_at=NOW)


def test_accepted_identity_is_stable_across_vendor_row_id_changes():
    first, error = check(quote())
    second, other = check(quote(id=99999))
    assert error is None and other is None
    assert first == second
    assert first == (456, 789, "draftkings", "points", "20.5", "over_under")


@pytest.mark.parametrize("field,value,expected", [
    ("id", True, "INVALID_PROP_ID"),
    ("game_id", 457, "FOREIGN_GAME_ID"),
    ("player_id", None, "INVALID_PLAYER_ID"),
    ("vendor", "", "INVALID_OFFER_LABELS"),
    ("prop_type", None, "INVALID_OFFER_LABELS"),
    ("line_value", "nan", "INVALID_PROP_LINE"),
    ("line_value", "-2", "INVALID_PROP_LINE"),
    ("market", {"type": "over_under", "over_odds": None}, "INVALID_MARKET_PRICE"),
    ("market", {"type": "unknown", "odds": 120}, "INVALID_MARKET_TYPE"),
    ("updated_at", None, "MISSING_VENDOR_TIMESTAMP"),
    ("updated_at", "yesterday", "INVALID_VENDOR_TIMESTAMP"),
])
def test_rejects_bad_schema(field, value, expected):
    _, error = check(quote(**{field: value}))
    assert error == expected


def test_milestone_and_positive_price_supported():
    identity, error = check(quote(
        line_value="1", market={"type": "milestone", "odds": 125},
    ))
    assert error is None
    assert identity[-1] == "milestone"


def test_stale_and_future_quotes_are_rejected_without_retries():
    for delta in (timedelta(days=1), -timedelta(minutes=1)):
        _, error = check(quote(updated_at=(NOW - delta).isoformat()))
        assert error == "STALE_OR_FUTURE_VENDOR_QUOTE"


def test_timestamps_must_be_aware():
    with pytest.raises(ValueError, match="timezone"):
        inspect_prop_offer(quote(), 456, observed_at=NOW.replace(tzinfo=None))
