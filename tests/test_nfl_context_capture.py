"""Synthetic source fixtures, not predictive validation."""

import gzip
import importlib.util
import io
import csv
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jabazi.features.advanced import AdvancedContext, SCHEMA

spec = importlib.util.spec_from_file_location(
    "capture_nfl", Path(__file__).parents[1] / "tools/capture_nfl_context.py"
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def request():
    return {
        "version": 1,
        "provider": "nflverse",
        "schedule_commit": "a" * 40,
        "assets": [
            {
                "season": 2025,
                "filename": "play_by_play_2025.csv.gz",
                "size": 1000,
                "url": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2025.csv.gz",
                "sha256": "b" * 64,
            }
        ],
    }


def test_fixed_source_request_cannot_fetch_other_hosts_or_unbounded_assets():
    capture.validate_request(request())
    for change in (
        {"url": "https://example.org/secret"},
        {"filename": "../../escape"},
        {"season": 2027},
        {"size": 99_000_000},
        {"sha256": ""},
    ):
        value = request()
        value["assets"][0].update(change)
        with pytest.raises(ValueError):
            capture.validate_request(value)
    value = request()
    value["assets"] *= 2
    with pytest.raises(ValueError):
        capture.validate_request(value)


def test_download_integrity_and_size_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(
        capture.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"abc")
    )
    receipt = capture.download(
        "https://example.org",
        tmp_path / "valid",
        limit=3,
        sha256="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    )
    assert receipt["bytes"] == 3 and datetime.fromisoformat(receipt["observed_at"]).tzinfo
    with pytest.raises(ValueError, match="size budget"):
        capture.download("https://example.org", tmp_path / "large", limit=2)
    with pytest.raises(ValueError, match="digest"):
        capture.download("https://example.org", tmp_path / "wrong", limit=3, sha256="f" * 64)


def fixture(tmp_path):
    game = {
        "game_id": "2025_01_A_H",
        "season": "2025",
        "game_type": "REG",
        "gameday": "2025-09-07",
        "gametime": "13:00",
        "home_team": "H",
        "away_team": "A",
        "home_score": "7",
        "away_score": "3",
    }
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(game))
    writer.writeheader()
    writer.writerow(game)
    games = capture.schedule_rows(buf.getvalue(), {2025})
    plays = [
        {
            "game_id": game["game_id"],
            "play_id": str(i),
            "play_type": "run",
            "posteam": side,
            "defteam": "A" if side == "H" else "H",
            "epa": "0.5",
            "qb_kneel": "0",
            "qb_spike": "0",
            "home_team": "H",
            "away_team": "A",
            "total_home_score": "7",
            "total_away_score": "3",
        }
        for i, side in enumerate(("H", "A"), start=1)
    ]
    path = tmp_path / "plays.csv.gz"
    with gzip.open(path, "wt") as source:
        writer = csv.DictWriter(source, fieldnames=list(plays[0]))
        writer.writeheader()
        writer.writerows(plays)
    receipt = {"sha256": "a" * 64, "observed_at": "2026-09-23T15:00:00+00:00"}
    return path, games, receipt


def test_real_capture_time_is_never_backdated_to_historical_game(tmp_path):
    path, games, receipt = fixture(tmp_path)
    rows, report = capture.aggregate_season(path, games, receipt, receipt, "TEST_ARCHIVE")
    assert report["games_imported"] == 1 and report["rejected"] == []
    assert all(r["observed_at"] == receipt["observed_at"] == r["completed_by"] for r in rows)
    assert all("ended_at" not in r for r in rows)
    context = AdvancedContext(
        {
            "manifest": {
                "schema": SCHEMA,
                "provider": "TEST",
                "id_namespace": "TEST",
                "data_mode": "real",
                "research_rights_reference": "TEST",
            },
            "snapshots": rows,
        }
    )
    request = {
        "sport": "americanfootball_nfl",
        "event_id": "next",
        "home_id": "H",
        "away_id": "A",
        "starts_at": "2025-09-14T17:00:00Z",
        "prediction_at": "2025-09-14T16:00:00Z",
    }
    assert context.build(request, minimum_games=1)["features"] is None
    # An old game captured now must not sneak past the actual-game-date lookback.
    request.update(starts_at="2026-09-24T17:00:00Z", prediction_at="2026-09-23T16:00:00Z")
    assert context.build(request, minimum_games=1)["features"] is None
    assert context.build(request, minimum_games=1, lookback_days=400)["features"] is not None


def test_score_mismatch_cannot_claim_a_completed_game(tmp_path):
    path, games, receipt = fixture(tmp_path)
    games = deepcopy(games)
    games["2025_01_A_H"]["home_score"] = "10"
    rows, report = capture.aggregate_season(path, games, receipt, receipt, "TEST_ARCHIVE")
    assert rows == [] and report["rejected"][0]["reason"] == "final score reconciliation failed"


def test_schema_accepts_previous_actual_end_evidence_but_rejects_ambiguous_completion():
    from test_advanced_features import document, nfl_rows

    payload = document(nfl_rows())
    payload["manifest"]["schema"] = "advanced-context-0.1.0"
    AdvancedContext(payload)
    payload["snapshots"][0]["completed_by"] = datetime.now(UTC).isoformat()
    with pytest.raises(ValueError, match="exactly one"):
        AdvancedContext(payload)
