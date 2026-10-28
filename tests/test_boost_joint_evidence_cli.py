"""JSONL calibration runner tests: local synthetic fixtures only."""
import json

from tools.audit_boost_joint_evidence import inspect_local_archive, main
from tests.test_boost_joint_evidence import row


def test_private_jsonl_outputs_no_ticket_identifiers(tmp_path, capsys):
    archive = tmp_path / "private.jsonl"
    data = row()
    data["event_id"] = "PRIVATE_PLAYER_EVENT_123"
    data["ticket_id"] = "PRIVATE_TICKET_123"
    archive.write_text(json.dumps(data) + "\n")
    result = inspect_local_archive(archive)
    assert result["input_sha256"]
    assert result["research_only"] is True
    assert result["approved_for_betting"] is False
    assert "PRIVATE_PLAYER_EVENT_123" not in json.dumps(result)
    assert "PRIVATE_TICKET_123" not in json.dumps(result)
    assert main(["--input", str(archive)]) == 1
    assert "PRIVATE_TICKET_123" not in capsys.readouterr().out


def test_jsonl_invalid_input_is_safe_failure(tmp_path, capsys):
    path = tmp_path / "secret-filename.jsonl"
    path.write_text("{not-json}")
    assert main(["--input", str(path)]) == 2
    emitted = capsys.readouterr().out
    assert "INVALID_OR_UNVERIFIED_EVIDENCE" in emitted
    assert "secret-filename" not in emitted
    assert "approved_for_betting" in emitted


def test_missing_archive_is_never_approved(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.jsonl"
    assert main(["--input", str(missing)]) == 2
    assert "does-not-exist" not in capsys.readouterr().out


def test_empty_jsonl_does_not_invent_sport_evidence(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    result = inspect_local_archive(empty)
    assert result["reports"] == []
    assert result["all_requested_sports_verified"] is False
    assert result["approved_for_betting"] is False
