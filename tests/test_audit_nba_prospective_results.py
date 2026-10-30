from datetime import UTC, datetime, timedelta

from tools import audit_nba_prospective_results as audit
from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.research.player_features import REQUIRED_INTEGRITY

NOW = datetime.now(UTC)
START = NOW - timedelta(hours=4)


def game(status="final"):
    return {"id": 77, "datetime": START.isoformat(), "status_state": status}


def stat():
    return {"game": {"id": 77}, "player": {"id": 19},
            "min": "35:10", "pts": 24, "reb": 12, "ast": 4,
            "fg3m": 3, "blk": 1, "stl": 2, "turnover": 3}


def crosswalk():
    row = {
        "sport": "NBA", "bdl_game_id": 77, "bdl_player_id": 19,
        "source_namespace": "ESPN", "source_player_id": "ESPN_ID",
        "source_record_sha256": "a" * 64,
        "canonical_event_id": "canonical-1",
        "canonical_participant": "PRIVATE_PLAYER",
        "event_starts_at": START.isoformat(),
        "reviewed_at": (START - timedelta(hours=1)).isoformat(),
        "independent_source_reviewed": True,
    }
    row["record_sha256"] = crosswalk_digest(row)
    return row


def forecast():
    return {"payload": {
        "sport": "basketball_nba", "event_id": "canonical-1",
        "participant": "PRIVATE_PLAYER", "market": "player_points",
        "starts_at": START.isoformat(),
        "predicted_at": (START - timedelta(hours=1)).isoformat(),
        "feature_snapshot": {
            "research_only": False, "production_inputs_verified": True,
            "provider": "ESPN",
            "integrity": {key: True for key in REQUIRED_INTEGRITY},
        },
    }}


class Provider:
    def __init__(self, status="final"):
        self.calls = []
        self.status = status
    def fetch_all_pages(self, sport, resource, params, *, max_pages):
        self.calls.append((sport, resource, params))
        if resource == "games":
            return {"complete": True, "data": [game(self.status)], "pages": 1}
        if resource == "stats":
            return {"complete": True, "data": [stat()], "pages": 1}
        raise AssertionError("unexpected resource")


class Store:
    def __init__(self, forecasts=None):
        self.forecasts = [forecast()] if forecasts is None else forecasts
    def list_records(self, kind, limit, *, entity):
        if kind == "player_prospective_forecast":
            assert entity == "canonical-1"
            return self.forecasts
        assert kind == "player_prospective_result"
        return []


def run(provider=None, store=None, commit=False, crosswalks=None):
    return audit.audit_nba_result_settlement(
        provider or Provider(), store or Store(),
        game_id=77, game_date=START.date(),
        reviewed_crosswalks=[crosswalk()] if crosswalks is None else crosswalks,
        commit=commit,
    )


def test_default_dry_run_never_writes_results(monkeypatch):
    monkeypatch.setattr(audit, "archive_player_result",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("write")))
    report = run()
    assert report["status"] == "RESEARCH_ONLY"
    assert report["final_market_labels_prepared"] == 12
    assert report["matched_trusted_frozen_forecasts"] == 1
    assert report["new_results_archived"] == 0
    assert report["write_requested"] is False
    assert report["production_approved"] is False
    assert "PRIVATE_PLAYER" not in str(report)


def test_explicit_reviewed_write_archives_only_existing_trusted_forecasts(monkeypatch):
    written = []
    monkeypatch.setattr(audit, "archive_player_result",
                        lambda store, **kwargs: written.append(kwargs) or True)
    report = run(commit=True)
    assert report["status"] == "RESEARCH_ONLY"
    assert report["new_results_archived"] == 1
    assert len(written) == 1
    assert written[0]["market"] == "player_points"
    assert written[0]["observed_value"] == 24
    assert report["betting_enabled"] is False


def test_nonfinal_game_does_not_fetch_stats_or_write(monkeypatch):
    provider = Provider(status="scheduled")
    report = run(provider=provider, commit=True)
    assert report["status"] == "UNAVAILABLE"
    assert report["reason"] == "GAME_NOT_FINAL"
    assert len(provider.calls) == 1


def test_unreviewed_crosswalk_yields_no_labels():
    row = crosswalk()
    row["independent_source_reviewed"] = False
    row["record_sha256"] = crosswalk_digest(row)
    report = run(crosswalks=[row])
    assert report["final_market_labels_prepared"] == 0
    assert report["matched_trusted_frozen_forecasts"] == 0


def test_truncated_frozen_forecast_listing_blocks_settlement():
    report = run(store=Store(forecasts=[forecast()] * 1000), commit=True)
    assert report["reason"] == "FORECAST_PAGE_CAP_REACHED"
    assert report["new_results_archived"] == 0


def test_untrusted_frozen_forecast_is_excluded():
    row = forecast()
    row["payload"]["feature_snapshot"]["production_inputs_verified"] = False
    report = run(store=Store(forecasts=[row]), commit=True)
    assert report["matched_trusted_frozen_forecasts"] == 0
    assert report["new_results_archived"] == 0
