"""Synthetic fixtures check evidence handling; they are not model validation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.features.advanced import AdvancedContext, SCHEMA
from jabazi.providers.advanced_stats import (
    innings_to_outs,
    mlb_pitcher_snapshot,
    nfl_team_snapshots,
)


def evidence(event, day=1):
    start = datetime(2025, 6, day, 17, tzinfo=UTC)
    return {
        "snapshot_id": event,
        "event_id": event,
        "starts_at": start.isoformat(),
        "ended_at": (start + timedelta(hours=3)).isoformat(),
        "observed_at": (start + timedelta(hours=4)).isoformat(),
        "raw_sha256": "a" * 64,
        "archive_reference": "SYNTHETIC_TEST_ONLY",
    }


def document(rows):
    return {
        "manifest": {
            "schema": SCHEMA,
            "provider": "SYNTHETIC_TEST_ONLY",
            "data_mode": "real",
            "id_namespace": "TEST",
            "research_rights_reference": "TEST_NOT_A_LICENSE",
        },
        "snapshots": rows,
    }


def request(sport="americanfootball_nfl", event="target"):
    return {
        "event_id": event,
        "sport": sport,
        "home_id": "HOME",
        "away_id": "AWAY",
        "starts_at": "2025-06-10T17:00:00Z",
        "prediction_at": "2025-06-10T16:00:00Z",
    }


def nfl_rows():
    return [
        {
            **evidence(f"g{i}", i),
            "snapshot_id": f"g{i}:{team}",
            "entity_id": team,
            "kind": "nfl_team",
            "status": "final",
            "values": {
                "offense_plays": 10 * i,
                "offense_epa": i,
                "offense_successes": i,
                "defense_plays": 10,
                "defense_epa_allowed": -1,
                "defense_successes_allowed": 3,
            },
        }
        for i in range(1, 5)
        for team in ("HOME", "AWAY")
    ]


def starter(team, pitcher, event="target", status="confirmed"):
    return {
        "snapshot_id": f"{event}:{team}:starter",
        "event_id": event,
        "entity_id": team,
        "kind": "mlb_starter",
        "status": status,
        "pitcher_id": pitcher,
        "starts_at": "2025-06-10T17:00:00Z",
        "observed_at": "2025-06-10T15:00:00Z",
        "raw_sha256": "b" * 64,
        "archive_reference": "SYNTHETIC_TEST_ONLY",
    }


def mlb_rows():
    rows = [starter("HOME", "P1"), starter("AWAY", "P2")]
    for i in range(1, 5):
        for p in ("P1", "P2"):
            rows.append(
                mlb_pitcher_snapshot(
                    {
                        "inningsPitched": "5.2",
                        "battersFaced": 24,
                        "strikeOuts": 6,
                        "baseOnBalls": 2,
                        "earnedRuns": 2,
                        "numberOfPitches": 90,
                    },
                    pitcher_id=p,
                    started=True,
                    evidence=evidence(f"{i}:{p}", i),
                )
            )
    return rows


def test_weighted_rates_and_future_revision_do_not_rewrite_old_features():
    rows = nfl_rows()
    old = AdvancedContext(document(rows)).build(request())
    assert old["status"] == "FEATURES_AVAILABLE"
    assert old["features"]["home_offense_epa_per_play"] == pytest.approx(0.1)
    assert old["features"]["home_defense_epa_allowed_per_play"] == pytest.approx(-0.1)
    revision = deepcopy(rows[0])
    revision.update(snapshot_id="later", observed_at="2025-06-11T00:00:00Z")
    revision["values"]["offense_epa"] = 10000
    new = AdvancedContext(document(rows + [revision])).build(request())
    assert new["features"] == old["features"] and new["feature_version"] == old["feature_version"]
    assert new["source_checksum"] != old["source_checksum"]
    assert not new["approved_for_betting"] and new["model_probability"] is None


def test_backfilled_or_late_published_statistics_unavailable_at_old_decision():
    for field in ("observed_at", "published_at"):
        rows = nfl_rows()
        for row in rows:
            row[field] = "2025-06-11T00:00:00Z"
        result = AdvancedContext(document(rows)).build(request())
        assert result["features"] is None and result["status"] == "INSUFFICIENT_DATA"


def test_latest_eligible_revision_replaces_counts_and_void_removes_old_record():
    rows = nfl_rows()
    revised = deepcopy(rows[0])
    revised.update(snapshot_id="revision", observed_at="2025-06-09T00:00:00Z")
    revised["values"]["offense_epa"] = 11
    output = AdvancedContext(document(rows + [revised])).build(request())
    assert output["features"]["home_offense_epa_per_play"] == pytest.approx(0.2)
    assert len(output["used_snapshots"]) == 8
    revised.update(status="void", values={})
    output = AdvancedContext(document(rows + [revised])).build(request())
    assert output["features"] is None and output["history_counts"]["home"] == 3


def test_pitcher_features_require_announced_identity_and_correct_baseball_innings():
    rows = mlb_rows()
    output = AdvancedContext(document(rows)).build(request("baseball_mlb"))
    assert output["features"]["home_starter_era"] == pytest.approx(54 / 17)
    assert output["features"]["home_starter_k_rate"] == 0.25
    assert output["features"]["home_starter_outs_per_start"] == 17
    output = AdvancedContext(document(rows[2:])).build(request("baseball_mlb"))
    assert output["features"] is None
    assert any("missing archived starter" in r for r in output["reasons"])


@pytest.mark.parametrize(
    "change",
    [
        {"status": "scratched", "pitcher_id": None},
        {"status": "unknown", "pitcher_id": None},
        {"status": "probable"},
        {"pitcher_id": "NEW_PITCHER_WITHOUT_HISTORY"},
        {"starts_at": "2025-06-10T18:00:00Z"},
    ],
)
def test_new_starter_snapshot_never_falls_back_to_old_confirmed_pitcher(change):
    rows = mlb_rows()
    latest = deepcopy(rows[0])
    latest.update(snapshot_id="changed", observed_at="2025-06-10T15:30:00Z", **change)
    output = AdvancedContext(document(rows + [latest])).build(request("baseball_mlb"))
    assert output["features"] is None
    assert "changed" in [r["snapshot_id"] for r in output["used_snapshots"]]


def test_doubleheader_exact_event_identity_and_stale_starter():
    rows = mlb_rows()
    assert (
        AdvancedContext(document(rows)).build(request("baseball_mlb", "game_two"))["features"]
        is None
    )
    rows[0]["observed_at"] = "2025-06-10T01:00:00Z"
    assert AdvancedContext(document(rows)).build(request("baseball_mlb"))["features"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"observed_at": "2025-06-01T18:00:00Z"},
        {"observed_at": "2025-06-01T21:00:00"},
        {"raw_sha256": "missing"},
        {"archive_reference": ""},
        {"status": "in_progress"},
    ],
)
def test_invalid_evidence_is_rejected(change):
    rows = nfl_rows()
    rows[0].update(change)
    with pytest.raises(ValueError):
        AdvancedContext(document(rows))


def test_ambiguous_revisions_invalid_numbers_trial_and_caller_mutation():
    rows = nfl_rows()
    duplicate = deepcopy(rows[0])
    duplicate["snapshot_id"] = "other-id"
    with pytest.raises(ValueError):
        AdvancedContext(document(rows + [duplicate]))
    for value in (float("nan"), True, "0.2"):
        bad = deepcopy(rows)
        bad[0]["values"]["offense_epa"] = value
        with pytest.raises(ValueError):
            AdvancedContext(document(bad))
    bad = document(rows)
    bad["manifest"]["data_mode"] = "scrambled"
    with pytest.raises(ValueError):
        AdvancedContext(bad)
    context = AdvancedContext(document(rows))
    rows[0]["values"]["offense_epa"] = 1000
    assert context.build(request())["features"]["home_offense_epa_per_play"] == pytest.approx(0.1)


def test_source_adapter_filters_plays_counts_sacks_and_signs_correctly():
    plays = [
        {
            "game_id": "nfl",
            "play_id": i,
            "play_type": typ,
            "posteam": offense,
            "defteam": "AWAY" if offense == "HOME" else "HOME",
            "epa": epa,
            "qb_kneel": kneel,
            "qb_spike": spike,
        }
        for i, (typ, offense, epa, kneel, spike) in enumerate(
            [
                ("pass", "HOME", -2, 0, 0),
                ("run", "HOME", 1, 0, 0),
                ("pass", "AWAY", 0.5, 0, 0),
                ("run", "HOME", -0.1, 1, 0),
                ("pass", "HOME", -0.5, 0, 1),
                ("no_play", "AWAY", 0, 0, 0),
                ("kickoff", "HOME", 0, 0, 0),
            ],
            start=1,
        )
    ]
    kwargs = dict(
        home_id="HOME", away_id="AWAY", complete_final_game=True, evidence=evidence("nfl")
    )
    out = nfl_team_snapshots(plays, **kwargs)
    AdvancedContext(document(out))
    assert out[0]["values"]["offense_plays"] == 2
    assert out[0]["values"]["offense_epa"] == -1
    assert out[1]["values"]["defense_epa_allowed"] == -1
    assert out[0]["values"]["offense_successes"] == 1
    for broken in (
        plays + [plays[0]],
        [dict(plays[0], epa=None)],
        [dict(plays[0], game_id="wrong")],
    ):
        with pytest.raises(ValueError):
            nfl_team_snapshots(broken, **kwargs)
    with pytest.raises(ValueError):
        nfl_team_snapshots(plays, **(kwargs | {"complete_final_game": False}))


@pytest.mark.parametrize("invalid", ["5.3", "-1.0", 5.2, "NaN", "5.20"])
def test_invalid_baseball_notation_is_rejected(invalid):
    with pytest.raises(ValueError):
        innings_to_outs(invalid)


def test_same_game_results_are_never_target_features_and_requests_are_pregame():
    rows = nfl_rows()
    output = AdvancedContext(document(rows)).build(request(event="g4"))
    assert output["features"] is None and output["history_counts"]["home"] == 3
    with pytest.raises(ValueError):
        AdvancedContext(document(rows)).build(request() | {"prediction_at": "2025-06-10T17:00:00Z"})


def test_offline_command_outputs_auditable_features_without_a_probability(
    tmp_path, monkeypatch, capsys
):
    import json
    from jabazi.features.advanced import main

    source, requests, output = (
        tmp_path / name for name in ("snapshots.json", "requests.json", "output.json")
    )
    source.write_text(json.dumps(document(nfl_rows())))
    requests.write_text(json.dumps([request()]))
    monkeypatch.setattr(
        "sys.argv",
        [
            "advanced",
            "--snapshots",
            str(source),
            "--requests",
            str(requests),
            "--output",
            str(output),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["features_available"] == 1
    result = json.loads(output.read_text())["results"][0]
    assert len(result["used_snapshots"]) == 8 and result["model_probability"] is None
    requests.write_text(json.dumps([request(), request()]))
    with pytest.raises(ValueError, match="Duplicate"):
        main()
