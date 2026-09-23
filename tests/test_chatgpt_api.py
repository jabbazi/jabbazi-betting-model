import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi import chatgpt_api as bridge
from jabazi.persistence.store import Store, digest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "owner-only-test-credential-" + "x" * 32)
    monkeypatch.setenv("JABAZI_ODDS_API_KEY", "fake-provider-key")
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    monkeypatch.setenv("JABBAZI_CHATGPT_TOKEN_VERSION", "1")
    store = Store("sqlite:///" + str(tmp_path / "bridge.db"), initialize=True)
    with patch.object(bridge, "store_factory", return_value=store), patch.object(store, "close"):
        yield TestClient(app), store, {"Authorization": "Bearer " + bridge.scanner_key()}
    store.close()


def request(store, scan_id=None, now=None):
    scan_id = scan_id or str(uuid4())
    assert bridge.submit(store, scan_id, now=now)
    return scan_id


def finish(store, scan_id, now, count=1, **changes):
    action = {
        "event": "Away @ Home", "source_timestamp": now.isoformat(),
        "starts_at": (now + timedelta(hours=2)).isoformat(),
        "model_probability": ".6", "model_version": "test-shadow-model",
        "probability_edge": ".05", "expected_roi": None,
        "stale": False, "in_play": False, "decision": "BET NOW",
    }
    payload = {
        "status": "COMPLETE", "generated_at": now.isoformat(),
        "feeds_scanned": 2, "quotes_archived": 200,
        "actions": [dict(action, selection=str(i)) for i in range(count)],
        "total_actions": count, "errors": [],
    } | changes
    store.append("chatgpt_scan_result", scan_id, payload,
                 digest(["chatgpt_scan_result", scan_id]))


def test_scoped_auth_and_admin_isolation(setup, monkeypatch):
    client, store, headers = setup
    with patch.object(bridge, "run_background") as worker:
        for header in ({}, {"Authorization": "Bearer bad"},
                       {"Authorization": "Bearer owner-only-test-credential-" + "x" * 32}):
            assert client.post("/v1/chatgpt/scans", json={"request_id": str(uuid4())},
                               headers=header).status_code == 401
        worker.assert_not_called()
    assert client.get("/v1/owner/review", headers=headers).status_code == 401
    assert client.post("/v1/owner/chatgpt-key", headers=headers).status_code == 401
    assert client.post("/v1/scans/run", json={}, headers=headers).status_code == 401
    monkeypatch.setenv("JABBAZI_CHATGPT_TOKEN_VERSION", "2")
    assert client.get("/v1/chatgpt/model-status", headers=headers).status_code == 401
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "false")
    assert client.get("/v1/chatgpt/model-status", headers=headers).status_code == 503


def test_owner_key_only_in_authenticated_noncacheable_response(setup):
    client, _, _ = setup
    owner = "owner-only-test-credential-" + "x" * 32
    response = client.post("/v1/owner/chatgpt-key", headers={"Authorization": "Bearer " + owner})
    assert response.json()["api_key"] == bridge.scanner_key()
    assert owner not in response.text
    assert response.headers["cache-control"] == "no-store"
    for url in ("/chatgpt", "/chatgpt/setup.js", "/chatgpt/openapi.json"):
        response = client.get(url)
        assert owner not in response.text and bridge.scanner_key() not in response.text


def test_scan_retry_is_idempotent_and_parallel_new_scan_is_rejected(setup):
    client, _, headers = setup
    scan_id = str(uuid4())
    with patch.object(bridge, "run_background") as worker:
        one = client.post("/v1/chatgpt/scans", json={"request_id": scan_id}, headers=headers)
        two = client.post("/v1/chatgpt/scans", json={"request_id": scan_id}, headers=headers)
        assert one.status_code == two.status_code == 200
        assert one.json()["scan_id"] == two.json()["scan_id"] == scan_id
        assert one.json()["status"] == "RUNNING"
        worker.assert_called_once_with(scan_id)
        other = client.post("/v1/chatgpt/scans", json={"request_id": str(uuid4())}, headers=headers)
        assert other.status_code == 429 and other.headers["retry-after"] == "120"
    invalid = client.post("/v1/chatgpt/scans", json={"request_id": scan_id, "max_credits": 1000}, headers=headers)
    assert invalid.status_code == 422
    assert client.get("/v1/chatgpt/scans/invalid", headers=headers).status_code == 422


def test_results_paginate_and_recheck_price_age_without_upgrading_models(setup):
    client, store, headers = setup
    now = datetime.now(UTC)
    scan_id = request(store)
    finish(store, scan_id, now, count=26, total_actions=40)
    first = bridge.scan_page(store, scan_id, now=now)
    assert len(first.actions) == 25 and first.next_page == 2
    assert first.page_action_count == 25 and first.total_pages == 2
    assert first.total_returned_actions == 26
    assert first.truncated is True and first.total_actions == 40
    assert first.actions[0]["decision"] == "WATCH"
    assert first.actions[0]["probability_status"] == "SHADOW_ONLY"
    assert first.actions[0]["stake_dollars"] == "0"
    late = bridge.scan_page(store, scan_id, now=now + timedelta(seconds=121))
    assert late.actions[0]["decision"] == "STALE DATA"
    response = client.get(f"/v1/chatgpt/scans/{scan_id}?page=2", headers=headers)
    assert response.json()["actions"][0]["selection"] == "25"
    assert response.json()["next_page"] is None
    assert response.json()["page_action_count"] == 1
    assert response.json()["total_pages"] == 2
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/v1/chatgpt/scans/{scan_id}?page=3", headers=headers).status_code == 404
    assert len(response.text) < 100000


def test_missing_provenance_never_returns_market_as_model_probability():
    row = bridge.present_action({"model_probability": ".7", "probability_edge": ".1",
                                 "expected_roi": ".2", "consensus_probability": ".6"}, datetime.now(UTC))
    assert row["model_probability"] is None and row["probability_edge"] is None
    assert row["expected_roi"] is None and row["consensus_probability"] == ".6"
    assert row["probability_status"] == "UNAVAILABLE"
    assert not row["price_is_current"]


def test_pending_read_returns_completion_without_starting_another_scan(setup):
    client, store, headers = setup
    scan_id = request(store)
    with patch.object(bridge.time, "sleep", side_effect=lambda _: finish(
        store, scan_id, datetime.now(UTC)
    )) as pause, patch.object(bridge, "run_background") as worker:
        response = client.get(f"/v1/chatgpt/scans/{scan_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETE"
    assert response.json()["actions"][0]["model_probability"] == ".6"
    assert response.json()["actions"][0]["probability_status"] == "SHADOW_ONLY"
    pause.assert_called_once()
    worker.assert_not_called()


def test_pending_read_has_bounded_wait_and_retains_same_job(setup):
    client, store, headers = setup
    scan_id = request(store)
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    with patch.object(bridge.time, "monotonic", side_effect=lambda: clock[0]), \
         patch.object(bridge.time, "sleep", side_effect=advance), \
         patch.object(bridge, "run_background") as worker:
        response = client.get(f"/v1/chatgpt/scans/{scan_id}", headers=headers)
    assert clock[0] == bridge.RESULT_WAIT_SECONDS
    assert response.json()["status"] == "RUNNING"
    assert response.json()["scan_id"] == scan_id
    assert response.json()["actions"] == []
    assert response.headers["cache-control"] == "no-store"
    worker.assert_not_called()


@pytest.mark.parametrize("state", ["COMPLETE", "EXPIRED", "MISSING"])
def test_terminal_or_missing_read_never_waits(setup, state):
    client, store, headers = setup
    scan_id = str(uuid4())
    if state != "MISSING":
        request(store, scan_id, now=datetime.now(UTC) - timedelta(seconds=601))
    if state == "COMPLETE":
        finish(store, scan_id, datetime.now(UTC))
    with patch.object(bridge.time, "sleep", side_effect=AssertionError("unexpected wait")) as pause, \
         patch.object(bridge, "datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime.now(UTC) + timedelta(seconds=601 if state == "EXPIRED" else 0)
        response = client.get(f"/v1/chatgpt/scans/{scan_id}", headers=headers)
    pause.assert_not_called()
    assert response.status_code == (404 if state == "MISSING" else 200)
    if state != "MISSING":
        assert response.json()["status"] == state


@pytest.mark.parametrize("kind", ["future", "started", "missing", "invalid", "in_play"])
def test_unsafe_timestamps_never_current(kind):
    now = datetime.now(UTC)
    row = {"source_timestamp": now.isoformat(), "starts_at": (now + timedelta(hours=1)).isoformat(),
           "stale": False, "in_play": False}
    if kind == "future":
        row["source_timestamp"] = (now + timedelta(seconds=1)).isoformat()
    elif kind == "started":
        row["starts_at"] = now.isoformat()
    elif kind == "missing":
        del row["source_timestamp"]
    elif kind == "invalid":
        row["source_timestamp"] = "invalid"
    else:
        row["in_play"] = True
    assert bridge.present_action(row, now)["decision"] == "STALE DATA"


def test_interrupted_scan_expires_and_is_not_automatically_requeued(setup):
    _, store, _ = setup
    scan_id = request(store)
    result = bridge.scan_page(store, scan_id, now=datetime.now(UTC) + timedelta(seconds=601))
    assert result.status == "EXPIRED" and result.actions == []
    assert not bridge.submit(store, scan_id)
    with pytest.raises(HTTPException) as error:
        bridge.scan_page(store, str(uuid4()))
    assert error.value.status_code == 404


def test_background_calls_real_shared_scanner_contract_and_sanitizes_failure(setup):
    _, store, _ = setup
    scan_id = request(store)
    with patch("jabazi.api.perform_scan", return_value={
        "feeds_scanned": 2, "actions": [], "errors": [], "model_coverage": {"versions": ["a"]}
    }) as scanner:
        bridge.run_background(scan_id)
    options = scanner.call_args.args[0]
    assert options.mode == "full" and options.max_credits == 15 and options.credit_reserve == 50
    assert scanner.call_args.kwargs == {"model_first": True}
    assert bridge.scan_page(store, scan_id).status == "COMPLETE"
    with patch("jabazi.api.perform_scan", side_effect=RuntimeError("secret-example")):
        failed_id = str(uuid4())
        bridge.run_background(failed_id)
        records = store.list_records("chatgpt_scan_result", entity=failed_id)
    assert "secret-example" not in json.dumps(records, default=str)
    assert records[0]["payload"]["status"] == "FAILED"


def test_public_schema_exposes_only_scoped_actions(setup):
    client, _, _ = setup
    schema = client.get("/chatgpt/openapi.json").json()
    assert set(schema["paths"]) == {
        "/v1/chatgpt/scans", "/v1/chatgpt/scans/{scan_id}", "/v1/chatgpt/model-status"
    }
    assert schema["security"] == [{"scannerKey": []}]
    operation = schema["paths"]["/v1/chatgpt/scans"]["post"]
    assert operation["operationId"] == "scanEverything"
    assert operation["x-openai-isConsequential"] is True
    assert all(p["name"] != "authorization" for p in operation["parameters"])
    assert "localStorage" not in client.get("/chatgpt/setup.js").text
    assert "frame-ancestors 'none'" in client.get("/chatgpt").headers["content-security-policy"]
    response = schema["paths"]["/v1/chatgpt/model-status"]["get"]["responses"]["200"]
    reference = response["content"]["application/json"]["schema"]["$ref"]
    definition = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]
    assert set(definition["properties"]) == {"models", "errors"}
    model_ref = definition["properties"]["models"]["items"]["$ref"]
    model_schema = schema["components"]["schemas"][model_ref.rsplit("/", 1)[1]]
    assert {"sport", "status", "version", "supported_markets", "approved_for_betting"} <= set(model_schema["properties"])


def test_model_status_has_typed_research_only_response(setup):
    client, _, headers = setup
    data = {"models": [{"sport": "americanfootball_nfl", "status": "SHADOW_ONLY",
                        "approved_for_betting": False, "version": "test-model-v1",
                        "supported_markets": ["h2h"], "state_refreshed_at": None}],
            "errors": []}
    with patch("jabazi.api.model_status_data", return_value=data):
        response = client.get("/v1/chatgpt/model-status", headers=headers)
    assert response.status_code == 200 and response.json() == data
    assert response.headers["cache-control"] == "no-store"
    data["models"][0]["approved_for_betting"] = True
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        bridge.ScannerModelStatus.model_validate(data)
