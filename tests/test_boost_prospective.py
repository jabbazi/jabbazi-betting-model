"""Synthetic fixture tests of immutable research capture; NEVER historical evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.boost_joint_evidence import audit_frozen_joint_evidence
from jabazi.boost_prospective import (
    audit_ready_rows, archive_joint_outcome, freeze_joint_ticket,
)
from jabazi.persistence.store import Conflict, Store


NOW = datetime(2026, 10, 28, 15, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store("sqlite:///:memory:", initialize=True)
    yield s
    s.close()


def legs():
    return [
        {"leg_id": "a", "player_id": "nba-p1", "market": "player_points",
         "side": "over", "line": 19.5},
        {"leg_id": "b", "player_id": "nba-p2", "market": "player_rebounds",
         "side": "under", "line": 8.5},
    ]


def ticket(*, sport="basketball_nba", market=True):
    out = {
        "sport": sport, "event_id": "event-1", "ticket_id": "ticket-1",
        "model_version": "research-joint-v1", "split": "prospective",
        "trained_through": "2026-07-01T00:00:00Z",
        "test_start": "2026-08-01T00:00:00Z",
        "prospective_start": "2026-10-01T00:00:00Z",
        "starts_at": (NOW + timedelta(hours=3)).isoformat(),
        "joint_probability": 0.42, "legs": legs(),
        "model_source": {
            "provider": "internal_model",
            "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
            "payload": {
                "event_id": "event-1", "ticket_id": "ticket-1",
                "model_version": "research-joint-v1",
                "joint_probability": 0.42, "leg_ids": ["a", "b"],
                "features_available_at": (NOW - timedelta(minutes=2)).isoformat(),
                "model_fit_provenance": "synthetic-test-only",
            },
        },
    }
    if market:
        out["market_source"] = {
            "provider": "independent_combined_quote_archiver",
            "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
            "payload": {
                "baseline_kind": "independently_quoted_combined_ticket",
                "event_id": "event-1", "ticket_id": "ticket-1",
                "leg_ids": ["a", "b"], "book": "test-book",
                "no_vig_probability": 0.4,
            },
        }
    return out


def settled(*, forecast_id, values=(22, 7), statuses=("final", "final")):
    return [
        {"leg_id": "a", "player_id": "nba-p1", "market": "player_points",
         "status": statuses[0], "observed_value": values[0]},
        {"leg_id": "b", "player_id": "nba-p2", "market": "player_rebounds",
         "status": statuses[1], "observed_value": values[1]},
    ]


def settle(store, fid, *, results=None):
    now = NOW + timedelta(hours=5)
    observations = results if results is not None else settled(forecast_id=fid)
    receipt = {
        "provider": "verified-synthetic-source",
        "observed_at": (now - timedelta(minutes=1)).isoformat(),
        "payload": {
            "event_id": "event-1", "ticket_id": "ticket-1",
            "forecast_id": fid, "leg_results": observations,
            "event_status": "final",
            "completed_at": (now - timedelta(hours=1)).isoformat(),
        },
    }
    return archive_joint_outcome(
        store, forecast_id=fid, leg_results=observations,
        result_source=receipt, observed_at=now,
    )


def test_freeze_settle_reconcile_with_existing_immutable_store(store):
    frozen = freeze_joint_ticket(store, ticket(), observed_at=NOW)
    assert frozen["created"] is True
    assert frozen["state"] == "RESEARCH_ONLY"
    fid = frozen["forecast_id"]
    assert len(fid) == 64
    assert not freeze_joint_ticket(store, ticket(), observed_at=NOW)["created"]
    outcome = settle(store, fid)
    assert outcome == {
        "created": True, "status": "FINAL",
        "outcome": 1, "research_only": True,
    }
    assert not settle(store, fid)["created"]
    rows = audit_ready_rows(store)
    assert len(rows) == 1
    assert rows[0]["outcome"] == 1
    assert rows[0]["split"] == "prospective"
    assert rows[0]["market_baseline_kind"] == "independently_quoted_combined_ticket"
    assert len(rows[0]["forecast_snapshot_sha256"]) == 64
    assert len(rows[0]["result_snapshot_sha256"]) == 64
    report = audit_frozen_joint_evidence(rows, minimum_events=1)
    assert report["approved_for_betting"] is False
    assert report["reports"][0]["status"] == "MISSING_EVIDENCE"  # no test split
    assert report["reports"][1]["independent_events"] == 1


def test_frozen_probability_cannot_be_replaced_under_same_identity(store):
    freeze_joint_ticket(store, ticket(), observed_at=NOW)
    changed = ticket()
    changed["joint_probability"] = 0.49
    changed["model_source"]["payload"]["joint_probability"] = 0.49
    with pytest.raises(Conflict, match="different evidence"):
        freeze_joint_ticket(store, changed, observed_at=NOW)


def test_unmatched_forecast_source_fails_before_write(store):
    inconsistent = ticket()
    inconsistent["model_source"]["payload"]["ticket_id"] = "other"
    with pytest.raises(ValueError, match="does not match"):
        freeze_joint_ticket(store, inconsistent, observed_at=NOW)
    assert store.list_records("boost_joint_forecast") == []


def test_mismatched_combined_quote_cannot_be_frozen(store):
    invalid = ticket()
    invalid["market_source"]["payload"]["leg_ids"] = ["a", "not-b"]
    with pytest.raises(ValueError, match="leg identity"):
        freeze_joint_ticket(store, invalid, observed_at=NOW)


def test_missing_independent_market_baseline_remains_ineligible_for_audit(store):
    frozen = freeze_joint_ticket(store, ticket(market=False), observed_at=NOW)
    assert settle(store, frozen["forecast_id"])["status"] == "FINAL"
    assert audit_ready_rows(store) == []
    assert store.list_records("boost_joint_forecast")


@pytest.mark.parametrize("change,match", [
    ({"starts_at": NOW.isoformat()}, "after event"),
    ({"split": "test"}, "genuinely prospective"),
    ({"joint_probability": 1.0}, "probability"),
])
def test_invalid_forecast_rejected(store, change, match):
    invalid = ticket()
    invalid.update(change)
    with pytest.raises(ValueError, match=match):
        freeze_joint_ticket(store, invalid, observed_at=NOW)


def test_future_feature_snapshot_does_not_enter_archive(store):
    invalid = ticket()
    invalid["model_source"]["payload"]["features_available_at"] = (
        NOW + timedelta(minutes=2)).isoformat()
    with pytest.raises(ValueError, match="Future features"):
        freeze_joint_ticket(store, invalid, observed_at=NOW)


def test_void_and_push_are_excluded_from_binary_calibration(store):
    fid = freeze_joint_ticket(store, ticket(), observed_at=NOW)["forecast_id"]
    values = settled(forecast_id=fid, statuses=("void", "final"))
    assert settle(store, fid, results=values)["status"] == "EXCLUDED"
    assert audit_ready_rows(store) == []
    # Independent ticket/store for push; the voided ticket is immutable.
    second = Store("sqlite:///:memory:", initialize=True)
    try:
        fid2 = freeze_joint_ticket(second, ticket(), observed_at=NOW)["forecast_id"]
        pushed = settled(forecast_id=fid2, values=(19.5, 7))
        assert settle(second, fid2, results=pushed)["status"] == "EXCLUDED"
        assert audit_ready_rows(second) == []
    finally:
        second.close()


def test_wrong_resolution_receipt_or_identity_refused(store):
    fid = freeze_joint_ticket(store, ticket(), observed_at=NOW)["forecast_id"]
    now = NOW + timedelta(hours=5)
    values = settled(forecast_id=fid)
    source = {
        "provider": "official_results",
        "observed_at": (now - timedelta(minutes=1)).isoformat(),
        "payload": {
            "event_id": "event-1", "ticket_id": "ticket-1",
            "forecast_id": fid, "leg_results": deepcopy(values),
            "event_status": "final",
            "completed_at": (now - timedelta(hours=1)).isoformat(),
        },
    }
    changed = deepcopy(values)
    changed[0]["observed_value"] = 900
    with pytest.raises(ValueError, match="does not match resolved"):
        archive_joint_outcome(
            store, forecast_id=fid, leg_results=changed,
            result_source=source, observed_at=now,
        )
    changed = deepcopy(values)
    changed[0]["player_id"] = "wrong-player"
    source["payload"]["leg_results"] = changed
    with pytest.raises(ValueError, match="identity mismatch"):
        archive_joint_outcome(
            store, forecast_id=fid, leg_results=changed,
            result_source=source, observed_at=now,
        )
    assert audit_ready_rows(store) == []


def test_pregame_result_cannot_be_archived(store):
    fid = freeze_joint_ticket(store, ticket(), observed_at=NOW)["forecast_id"]
    values = settled(forecast_id=fid)
    source = {
        "provider": "official_results", "observed_at": NOW.isoformat(),
        "payload": {
            "event_id": "event-1", "ticket_id": "ticket-1",
            "forecast_id": fid, "leg_results": values,
            "event_status": "final", "completed_at": NOW.isoformat(),
        },
    }
    with pytest.raises(ValueError, match="final event completion"):
        archive_joint_outcome(
            store, forecast_id=fid, leg_results=values,
            result_source=source, observed_at=NOW,
        )


def test_no_fabricated_results_when_only_frozen_forecast_exists(store):
    frozen = freeze_joint_ticket(store, ticket(), observed_at=NOW)
    assert frozen["created"]
    assert store.list_records("boost_joint_result") == []
    assert audit_ready_rows(store) == []


def test_final_leg_numbers_without_authoritative_game_final_are_rejected(store):
    fid = freeze_joint_ticket(store, ticket(), observed_at=NOW)["forecast_id"]
    now = NOW + timedelta(hours=5)
    values = settled(forecast_id=fid)
    source = {
        "provider": "unverified-result",
        "observed_at": (now - timedelta(minutes=1)).isoformat(),
        "payload": {
            "event_id": "event-1", "ticket_id": "ticket-1",
            "forecast_id": fid, "leg_results": values,
            "event_status": "in_progress",
            "completed_at": (now - timedelta(hours=1)).isoformat(),
        },
    }
    with pytest.raises(ValueError, match="final event completion"):
        archive_joint_outcome(
            store, forecast_id=fid, leg_results=values,
            result_source=source, observed_at=now,
        )
    assert audit_ready_rows(store) == []



def test_inventory_distinguishes_missing_baselines_and_pending_results(store):
    from jabazi.boost_prospective_inventory import capture_inventory
    frozen = freeze_joint_ticket(store, ticket(market=False), observed_at=NOW)
    summary = capture_inventory(store)
    nba = summary["sports"]["basketball_nba"]
    assert summary["status"] == "RESEARCH_ONLY"
    assert nba["frozen"] == 1
    assert nba["pending_result"] == 1
    assert nba["missing_market_baseline"] == 1
    assert nba["fully_resolved_with_baseline"] == 0
    assert summary["integrity_failures"] == 0
    assert summary["approved_for_betting"] is False
    assert "nba-p1" not in str(summary)
    assert "event-1" not in str(summary)
    assert frozen["forecast_id"] not in str(summary)


def test_inventory_counts_final_and_excluded_without_promoting(store):
    from jabazi.boost_prospective_inventory import capture_inventory
    fid = freeze_joint_ticket(store, ticket(), observed_at=NOW)["forecast_id"]
    assert settle(store, fid)["status"] == "FINAL"
    summary = capture_inventory(store)
    nba = summary["sports"]["basketball_nba"]
    assert nba["settled_final"] == 1
    assert nba["fully_resolved_with_baseline"] == 1
    assert nba["pending_result"] == 0
    assert summary["integrity_failures"] == 0
    assert summary["approved_for_betting"] is False


def test_corrupted_nested_source_hash_blocks_inventory(store):
    from jabazi.boost_prospective_inventory import capture_inventory
    from jabazi.boost_prospective import FORECAST
    frozen = freeze_joint_ticket(store, ticket(), observed_at=NOW)
    raw = store.list_records(FORECAST, 1)[0]["payload"]
    corrupt = deepcopy(raw)
    corrupt["model_source"]["sha256"] = "0" * 64
    quarantined = Store("sqlite:///:memory:", initialize=True)
    try:
        quarantined.append(FORECAST, "event-1", corrupt, key=frozen["forecast_id"])
        summary = capture_inventory(quarantined)
        assert summary["status"] == "INTEGRITY_BLOCKED"
        assert summary["sports"]["basketball_nba"]["invalid_evidence"] == 1
        assert summary["integrity_failures"] == 1
        assert summary["approved_for_betting"] is False
    finally:
        quarantined.close()


def test_orphan_resolution_blocks_scoring_without_leaking_ids(store):
    from jabazi.boost_prospective_inventory import capture_inventory
    from jabazi.boost_prospective import RESULT
    store.append(RESULT, "orphan-event", {
        "forecast_id": "a" * 64,
        "status": "FINAL",
        "outcome": 1,
        "private_player": "SECRET_PLAYER_ID",
    })
    summary = capture_inventory(store)
    assert summary["status"] == "INTEGRITY_BLOCKED"
    assert summary["orphan_results"] == 1
    assert "SECRET_PLAYER_ID" not in str(summary)


def test_inventory_enforces_cap_instead_of_partial_counts(store):
    from jabazi.boost_prospective_inventory import capture_inventory
    from jabazi.boost_prospective import RESULT
    for x in range(2):
        store.append(RESULT, "orphan", {"forecast_id": str(x), "outcome": 0})
    with pytest.raises(ValueError, match="no partial evidence"):
        capture_inventory(store, limit=1)
