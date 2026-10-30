"""Synthetic regressions only; these inputs are not betting evidence."""

from datetime import UTC, datetime, timedelta

import pytest

from jabazi.sheet_images import featured_rows, shortlist_rows


AT = datetime(2026, 9, 23, 12, tzinfo=UTC)


def snapshot(*rows, healthy=True):
    base = {
        "sport": "baseball_mlb",
        "event_id": "test-game",
        "event": "Away @ Home",
        "market": "h2h",
        "selection": "Home",
        "line": None,
        "book": "TEST_ONLY",
        "decimal_odds": "2.0",
        "research_probability": ".60",
        "market_no_vig_probability": ".50",
        "uncertainty": ".08",
        "model_version": "SYNTHETIC_TEST_ONLY",
        "executable": True,
        "book_count": 3,
        "price_time_utc": (AT - timedelta(seconds=20)).isoformat(),
        "starts_at_utc": (AT + timedelta(hours=2)).isoformat(),
    }
    return {
        "payload": {
            "completed_at": AT.isoformat(),
            "healthy": healthy,
            "rows": [base | changes for changes in rows or ({},)],
        }
    }


def test_featured_prices_expire_against_read_time_but_archives_remain_reproducible():
    data = snapshot()
    assert len(featured_rows(data, "mlb", 0, now=AT)) == 1
    assert featured_rows(data, "mlb", 0, now=AT + timedelta(seconds=101)) == []
    assert len(shortlist_rows(data, "mlb", 0)) == 1


def test_future_snapshot_or_started_game_cannot_be_a_current_edge():
    assert featured_rows(snapshot(), "mlb", 0, now=AT - timedelta(seconds=1)) == []
    data = snapshot({"starts_at_utc": (AT + timedelta(seconds=10)).isoformat()})
    assert featured_rows(data, "mlb", 0, now=AT + timedelta(seconds=10)) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"price_time_utc": "2026-09-23T12:00:01Z"},
        {"price_time_utc": "2026-09-23T12:00:00"},
        {"starts_at_utc": "bad"},
        {"research_probability": "NaN"},
        {"model_version": None},
        {"executable": False},
        {"price_stale": True},
        {"in_play": True},
        {"decimal_odds": "1.1"},
        {"market_no_vig_probability": ".65"},
    ],
)
def test_bad_or_nonpositive_rows_never_become_featured(changes):
    assert featured_rows(snapshot(changes), "mlb", 0, now=AT) == []


def test_unhealthy_snapshot_does_not_return_features():
    assert featured_rows(snapshot(healthy=False), "mlb", 0, now=AT) == []


def test_ranked_top_limit_one_selection_per_game_with_deterministic_ties():
    data = snapshot(
        *[{"event_id": str(i), "research_probability": str(0.6 + i / 1000)} for i in range(20)]
    )
    result = featured_rows(data, "mlb", 0, now=AT)
    assert len(result) == 12
    assert result[0]["event_id"] == "19"
    assert result[-1]["event_id"] == "8"
    assert all(r["status"] == "WATCH" for r in result)
    with pytest.raises(ValueError):
        featured_rows(data, "mlb", 0, limit=-1, now=AT)
