"""Private CLI tests; all inputs are synthetic and never prospective proof."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from jabazi.persistence.store import Store
from tools import boost_joint_capture as capture

NOW = datetime(2026, 10, 28, 14, tzinfo=UTC)


def _frozen():
    legs = [
        {"leg_id": "p", "player_id": "test1", "market": "player_points",
         "side": "over", "line": 19.5},
        {"leg_id": "r", "player_id": "test2", "market": "player_rebounds",
         "side": "under", "line": 8.5},
    ]
    return {
        "sport": "basketball_nba", "event_id": "test-game",
        "ticket_id": "test-ticket", "model_version": "v1", "split": "prospective",
        "joint_probability": 0.42, "legs": legs,
        "starts_at": (NOW + timedelta(days=2)).isoformat(),
        "trained_through": "2026-01-01T00:00:00Z",
        "test_start": "2026-02-01T00:00:00Z",
        "prospective_start": "2026-04-01T00:00:00Z",
        "model_source": {
            "provider": "fake-model",
            "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
            "payload": {
                "event_id": "test-game", "ticket_id": "test-ticket",
                "model_version": "v1", "joint_probability": 0.42,
                "leg_ids": ["p", "r"],
                "features_available_at": (NOW - timedelta(minutes=2)).isoformat(),
            },
        },
    }


def test_cli_requires_explicit_write_without_touching_db(monkeypatch, tmp_path, capsys):
    path = tmp_path / "ticket.json"
    path.write_text(json.dumps(_frozen()))
    monkeypatch.setattr(capture, "_open_store",
                        lambda: pytest.fail("No implicit database access"))
    assert capture.main(["freeze", "--input", str(path)]) == 2
    assert "EXPLICIT_EVIDENCE_WRITE_FLAG_REQUIRED" in capsys.readouterr().out


def test_cli_failure_redacts_raw_private_material(monkeypatch, tmp_path, capsys):
    path = tmp_path / "private-provider-key.json"
    path.write_text('{"ticket_id":"SECRET-PLAYER","not":"valid"}')
    monkeypatch.setattr(capture, "_open_store",
                        lambda: (_ for _ in ()).throw(RuntimeError("PASSWORD")))
    assert capture.main([
        "freeze", "--input", str(path), "--commit-evidence",
    ]) == 2
    output = capsys.readouterr().out
    assert "PASSWORD" not in output
    assert "SECRET-PLAYER" not in output
    assert "private-provider-key" not in output


def test_cli_audit_zero_evidence_is_explicit(monkeypatch, capsys):
    s = Store("sqlite:///:memory:", initialize=True)

    class Context:
        def close(self):
            pass
        @property
        def engine(self):
            return s.engine

    monkeypatch.setattr(capture, "_open_store", lambda: Context())
    try:
        assert capture.main(["audit"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["eligible_resolved_tickets"] == 0
        assert result["report"]["approved_for_betting"] is False
        assert result["approved_for_betting"] is False
    finally:
        s.close()


def test_cli_does_not_echo_invalid_file_path(monkeypatch, capsys):
    monkeypatch.setattr(capture, "_open_store",
                        lambda: pytest.fail("No DB before valid file"))
    assert capture.main([
        "freeze", "--input", "/private/missing-personal-tickets.json",
        "--commit-evidence",
    ]) == 2
    assert "missing-personal-tickets" not in capsys.readouterr().out
