import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi.chatgpt_api import scanner_key
from jabazi.persistence.store import Store
from jabazi.scan_health import recent_scan_health, safe_error


def test_scan_health_reads_bounded_evidence_and_redacts_secrets(monkeypatch):
    store = Store("sqlite:///:memory:", initialize=True)
    errors = [
        "baseball_mlb:HTTPError", "MONTHLY_QUOTA_LIMIT",
        "americanfootball_nfl:" + "a" * 32 + ":model_ValueError",
        "icehockey_nhl:player_shots_on_goal:player_model_load_ValueError",
        "https://provider.test?api_key=secret-value", "Bearer secret-value",
    ]
    for _ in range(25):
        identifier = str(uuid4())
        store.append("scan_run", identifier, {
            "completed_at": "2026-09-30T14:01:16+00:00",
            "healthy": False, "errors": errors,
            "feeds_scanned": 4, "quotes_archived": 100,
            "event_market_coverage": {"stop_reason": "MONTHLY_QUOTA_LIMIT",
                                      "private_data": "secret-value"},
            "best_two_sheet_candidate": {"private": "secret-value"},
        }, identifier)
    before = store.list_records("scan_run", 30)
    summaries = recent_scan_health(store)
    assert len(summaries) == 20
    assert summaries[0]["errors"] == errors[:4] + ["REDACTED_ERROR"] * 2
    assert summaries[0]["error_count"] == 6
    assert summaries[0]["healthy"] is False
    assert summaries[0]["stop_reason"] == "MONTHLY_QUOTA_LIMIT"
    assert "secret-value" not in json.dumps(summaries)
    assert before == store.list_records("scan_run", 30)

    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "test-owner-key-" + "x" * 32)
    client = TestClient(app)
    with patch("jabazi.api.model_status_data", return_value={
        "models": [], "errors": [], "recent_scan_health": summaries,
    }) as status:
        assert client.get("/v1/chatgpt/model-status").status_code == 401
        status.assert_not_called()
        response = client.get("/v1/chatgpt/model-status", headers={
            "Authorization": "Bearer " + scanner_key(),
        })
    assert response.status_code == 200
    assert response.json()["recent_scan_health"] == summaries
    assert response.headers["cache-control"] == "no-store"
    store.close()


def test_unknown_error_text_fails_closed():
    for value in (None, {"token": "secret"}, "baseball_mlb:secret",
                  "baseball_mlb:HTTPError?api_key=secret", "secret:ValueError"):
        assert safe_error(value) == "REDACTED_ERROR"
