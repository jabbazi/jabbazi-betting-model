from datetime import UTC, datetime

from jabazi.models.refresh import nba_schedule_rows


NOW = datetime(2026, 9, 28, 19, tzinfo=UTC)


def test_nba_schedule_refresh_separates_completed_and_future_games():
    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        "1,2026,2,2026-04-01T00:00:00+00:00,false,true,Boston Celtics,New York Knicks,110,101\n"
        "2,2027,2,2026-10-01T00:00:00+00:00,false,false,Los Angeles Lakers,Golden State Warriors,,\n"
    ).encode()
    games, events = nba_schedule_rows(raw, NOW)
    assert len(games) == 1
    assert games[0]["season"] == 2025
    assert games[0]["home_score"] == 110
    assert len(events) == 1
    assert events[0]["season"] == 2026
    assert events[0]["home_team"] == "Los Angeles Lakers"


def test_nba_schedule_refresh_fails_closed_on_bad_rows():
    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        ",2027,2,not-a-date,false,false,Same,Same,,\n"
    ).encode()
    games, events = nba_schedule_rows(raw, NOW)
    assert games == []
    assert events == []


def test_nba_preseason_refresh_falls_back_without_enabling_stale_inference(monkeypatch):
    import json
    import urllib.error
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update

    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        "1,2026,2,2026-06-15T00:00:00+00:00,false,true,Boston Celtics,New York Knicks,110,101\n"
    ).encode()
    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return raw

    def urlopen(url, timeout=45):
        calls.append(url)
        if "nba_schedule_2027.csv" in url:
            raise urllib.error.HTTPError(url, 404, "not published", {}, None)
        assert "nba_schedule_2026.csv" in url
        return Response()

    monkeypatch.setattr("jabazi.models.refresh.urllib.request.urlopen", urlopen)
    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    updated = fetch_update(artifact, now=NOW)
    assert len(calls) == 2
    assert updated["state_refreshed_at"] == NOW.isoformat()
    assert updated["events"] == []
    assert updated["state_latest_game_at"].startswith("2026-06-15")


def test_nba_preseason_refresh_falls_back_from_empty_upcoming_release(monkeypatch):
    import json
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update

    empty = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
    ).encode()
    prior = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        "1,2026,2,2026-06-15T00:00:00+00:00,false,true,Boston Celtics,New York Knicks,110,101\n"
    ).encode()
    calls = []

    class Response:
        def __init__(self, raw):
            self.raw = raw
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return self.raw

    def urlopen(url, timeout=45):
        calls.append(url)
        return Response(empty if "nba_schedule_2027.csv" in url else prior)

    monkeypatch.setattr("jabazi.models.refresh.urllib.request.urlopen", urlopen)
    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    updated = fetch_update(artifact, now=NOW)
    assert len(calls) == 2
    assert updated["events"] == []
    assert updated["state_latest_game_at"].startswith("2026-06-15")


def test_nba_offseason_empty_release_preserves_bundled_state_without_events(monkeypatch):
    import json
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update
    from jabazi.models.score_distribution import ScoreDistributionModel

    empty = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
    ).encode()

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return empty

    monkeypatch.setattr(
        "jabazi.models.refresh.urllib.request.urlopen",
        lambda url, timeout=45: Response(),
    )
    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    original_state = artifact["team_state"]
    updated = fetch_update(artifact, now=NOW)
    assert updated["team_state"] == original_state
    assert updated["events"] == []
    assert updated["offseason_context"] is True
    assert updated["state_refreshed_at"] == NOW.isoformat()
    assert updated["production_context"] == {
        "starter_verified": False,
        "roster_verified": False,
        "injuries_verified": False,
        "calibration_verified": False,
    }
    ScoreDistributionModel(updated)


def test_nba_offseason_state_cannot_infer_without_current_event():
    import json
    from types import SimpleNamespace
    from jabazi.models.refresh import BUNDLE_DIR, nba_offseason_state
    from jabazi.models.score_distribution import ScoreDistributionModel

    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    updated = nba_offseason_state(artifact, now=NOW, response_checksum="offseason")
    model = ScoreDistributionModel(updated)
    price = SimpleNamespace(
        sport="basketball_nba",
        market="h2h",
        event="New York Knicks @ Boston Celtics",
        event_id="future-test",
        starts_at=NOW + __import__("datetime").timedelta(days=1),
        observed_at=NOW,
        in_play=False,
        selection="Boston Celtics",
        line=None,
        participant=None,
    )
    assert model.estimate(price) is None


def test_nba_offseason_empty_results_do_not_call_prospective_archiver(monkeypatch):
    import json
    from unittest.mock import patch
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update

    empty = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
    ).encode()

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return empty

    monkeypatch.setattr(
        "jabazi.models.refresh.urllib.request.urlopen",
        lambda url, timeout=45: Response(),
    )
    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    with patch("jabazi.research.prospective.archive_results") as archive:
        updated = fetch_update(artifact, now=NOW, result_store=object())
    archive.assert_not_called()
    assert updated["events"] == []
    assert updated["offseason_context"] is True


def test_nba_october_preseason_schedule_is_clean_research_state(monkeypatch):
    import json
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update
    from jabazi.models.score_distribution import ScoreDistributionModel

    raw = (
        "game_id,season,season_type,game_date_time,neutral_site,status_type_completed,"
        "home_display_name,away_display_name,home_score,away_score\n"
        "2,2027,2,2026-10-08T23:30:00+00:00,false,false,Boston Celtics,New York Knicks,,\n"
    ).encode()

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return raw

    monkeypatch.setattr(
        "jabazi.models.refresh.urllib.request.urlopen",
        lambda url, timeout=45: Response(),
    )
    artifact = json.loads((BUNDLE_DIR / "nba_scores.json").read_text())
    now = datetime(2026, 10, 2, 18, tzinfo=UTC)
    updated = fetch_update(artifact, now=now)
    assert updated["preseason_context"] is True
    assert len(updated["events"]) == 1
    assert updated["events"][0]["home_team"] == "Boston Celtics"
    assert updated["production_context"] == {
        "starter_verified": False,
        "roster_verified": False,
        "injuries_verified": False,
        "calibration_verified": False,
    }
    ScoreDistributionModel(updated)


def test_opening_night_finals_wait_for_availability_without_poisoning_model(monkeypatch):
    import json
    from unittest.mock import Mock
    from jabazi.models.refresh import BUNDLE_DIR, fetch_update
    from jabazi.models.score_distribution import ScoreDistributionModel

    raw = (
        'game_id,season,season_type,game_date_time,neutral_site,status_type_completed,'
        'home_display_name,away_display_name,home_score,away_score\n'
        '1,2027,2,2026-10-20T23:30:00+00:00,false,true,Boston Celtics,New York Knicks,110,101\n'
        '2,2027,2,2026-10-22T23:30:00+00:00,false,false,Boston Celtics,New York Knicks,,\n'
    ).encode()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return raw
    monkeypatch.setattr('jabazi.models.refresh.urllib.request.urlopen', lambda *a, **k: Response())
    archive = Mock()
    monkeypatch.setattr('jabazi.research.prospective.archive_results', archive)
    artifact = json.loads((BUNDLE_DIR / 'nba_scores.json').read_text())
    updated = fetch_update(artifact, now=datetime(2026, 10, 21, 14, tzinfo=UTC), result_store=object())
    assert updated['inference_status'] == 'WAITING_FOR_ELIGIBLE_HISTORY'
    assert updated['history_available_after'] == '2026-10-22T00:00:00+00:00'
    assert updated['team_state'] == artifact['team_state']
    assert len(updated['events']) == 1
    assert updated['preseason_context'] is False
    archive.assert_not_called()
    ScoreDistributionModel(updated)
    # Once the result is available, normal refresh resumes without a waiting flag.
    ready = fetch_update(artifact, now=datetime(2026, 10, 22, 1, tzinfo=UTC))
    assert 'inference_status' not in ready
    assert ready['team_state']['Boston Celtics'][-1][0] == 110


def test_nba_schedule_excludes_exhibitions_and_canonicalizes_clippers():
    raw = (
        'game_id,season,season_type,game_date_time,neutral_site,status_type_completed,'
        'home_display_name,away_display_name,home_score,away_score\n'
        '1,2026,2,2026-04-01T00:00:00+00:00,false,true,Team LeBron,Team Shaq,110,101\n'
        '2,2027,2,2026-10-01T00:00:00+00:00,false,false,LA Clippers,Boston Celtics,,\n'
    ).encode()
    games, events = nba_schedule_rows(raw, NOW)
    assert games == []
    assert len(events) == 1
    assert events[0]['home_team'] == 'Los Angeles Clippers'


def test_nba_training_capture_excludes_exhibitions(tmp_path, monkeypatch):
    from tools import capture_nba_sportsdataverse as capture
    import json
    raw = (
        'game_id,season,season_type,game_date_time,neutral_site,status_type_completed,'
        'home_display_name,away_display_name,home_score,away_score\n'
        '1,2026,2,2026-04-01T00:00:00+00:00,false,true,Team LeBron,Team Shaq,110,101\n'
        '2,2026,2,2026-04-02T00:00:00+00:00,false,true,LA Clippers,Boston Celtics,110,101\n'
    ).encode()
    monkeypatch.setattr(capture, 'fetch', lambda *a, **k: raw)
    capture.capture(tmp_path, (2026,), team_only=True)
    games = json.loads((tmp_path / 'nba_team_history.json').read_text())['games']
    assert len(games) == 1
    assert games[0]['home_team'] == 'Los Angeles Clippers'


def test_new_nba_artifact_refreshes_without_waiting_six_hours(monkeypatch):
    import json
    from jabazi.models.refresh import BUNDLE_DIR, refresh_models
    from jabazi.persistence.store import Store
    store = Store('sqlite:///:memory:', initialize=True)
    artifact = json.loads((BUNDLE_DIR / 'nba_scores.json').read_text())
    sport = artifact['sport']
    store.append('model_refresh_attempt', sport, {'attempted_at': NOW.isoformat()})
    store.append('game_model', sport, artifact | {'model_version': 'old-version'})
    calls = []
    def fetch(value, **kwargs):
        calls.append(value['sport'])
        return value
    monkeypatch.setattr('jabazi.models.refresh.fetch_update', fetch)
    try:
        result = refresh_models(store, now=NOW)
        assert sport in calls
        assert result['nba']['version'] == artifact['model_version']
    finally:
        store.close()
