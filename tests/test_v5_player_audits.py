"""Player V5 calibration and slate verification fail-closed contracts."""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.vip.player_audit import calibration_audit, full_slate_audit

NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)


def _snapshot(resource, rows, *, game_id=None, cursor=None, observed=NOW):
    query = ([["game_id", game_id]] if game_id is not None else
             [["dates[]", "2026-10-26"], ["dates[]", "2026-10-27"]])
    return {"payload": {"observed_at": observed.isoformat(),
                        "query": query, "resource": resource,
                        "payload": {"data": rows, "meta": {"next_cursor": cursor}}}}


def test_single_sampled_game_never_passes_full_slate():
    store = Mock()
    store.list_records.side_effect = lambda kind, limit, entity=None: (
        [_snapshot("games", [{"id": 101}, {"id": 102}])]
        if entity == "nba:games" else
        [_snapshot("props", [{"id": 1}], game_id=101)]
        if entity == "nba:props" else [])
    result = full_slate_audit(store, now=NOW, slate_date="2026-10-26")
    nba = result["sports"]["NBA"]
    assert nba["scheduled_games"] == 2
    assert nba["covered_games"] == 1
    assert nba["missing_game_ids"] == [102]
    assert not nba["all_game_props_verified"]
    assert not nba["executable_prices_verified"]


def test_full_vendor_pages_only_mean_capture_not_executable_quotes():
    store = Mock()
    store.list_records.side_effect = lambda kind, limit, entity=None: (
        [_snapshot("games", [{"id": 101}])] if entity == "nba:games" else
        [_snapshot("props", [{"id": 1}], game_id=101)] if entity == "nba:props" else [])
    result = full_slate_audit(store, now=NOW, slate_date="2026-10-26")
    assert result["sports"]["NBA"]["all_game_props_verified"]
    assert not result["sports"]["NBA"]["executable_prices_verified"]
    assert not result["sports"]["NBA"]["model_calibration_verified"]


def test_incomplete_pagination_or_stale_quotes_fail_closed():
    store = Mock()
    store.list_records.side_effect = lambda kind, limit, entity=None: (
        [_snapshot("games", [{"id": 101}], cursor="more")] if entity == "nba:games" else
        [_snapshot("props", [{"id": 1}], game_id=101,
                   observed=NOW-timedelta(minutes=6))] if entity == "nba:props" else [])
    result = full_slate_audit(store, now=NOW, slate_date="2026-10-26")
    assert not result["sports"]["NBA"]["games_snapshot_complete"]
    assert not result["sports"]["NBA"]["all_game_props_verified"]


def test_calibration_empty_archive_never_approves(monkeypatch):
    from jabazi.vip import player_audit
    monkeypatch.setattr(player_audit, "validation_report",
                        lambda store: {"buckets": []})
    store = Mock()
    store.list_records.return_value = []
    result = calibration_audit(store)
    assert result["model_count"] == 0
    assert result["approved_count"] == 0


def test_audit_endpoints_require_member_context():
    client = TestClient(app)
    for path in ("/v1/vip/player-calibration-audit",
                 "/v1/vip/player-full-slate-audit"):
        response = client.get(path)
        assert response.status_code in (401, 403, 503)
        assert "promotion_eligible" not in response.text
        assert "missing_game_ids" not in response.text
