import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi import chatgpt_api as bridge, scanner_mcp as mcp
from jabazi.persistence.store import Store, digest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("JABBAZI_MODEL_TOKEN", "test-owner-" + "x" * 40)
    monkeypatch.setenv("JABAZI_ODDS_API_KEY", "test-provider")
    monkeypatch.setenv("JABBAZI_CHATGPT_ENABLED", "true")
    monkeypatch.setenv("JABBAZI_MCP_ENABLED", "true")
    monkeypatch.setenv("JABBAZI_MCP_TOKEN_VERSION", "1")
    store = Store("sqlite:///" + str(tmp_path / "mcp.db"), initialize=True)
    with patch.object(bridge, "store_factory", return_value=store), patch("jabazi.api.platform_store", return_value=store), patch.object(store, "close"):
        yield TestClient(app, base_url=mcp.ORIGIN), store
    store.close()


def params():
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {"client_id": mcp.CLIENT, "redirect_uri": mcp.REDIRECT,
            "response_type": "code", "scope": mcp.SCOPE, "state": "state-" * 8,
            "resource": mcp.RESOURCE, "code_challenge": challenge,
            "code_challenge_method": "S256"}, verifier


def consent_form(client, change=None):
    p, verifier = params()
    p.update(change or {})
    response = client.get("/oauth/authorize", params=p)
    if response.status_code != 200:
        return response, {}, verifier
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', response.text))
    return response, fields, verifier


def grant(client):
    response, fields, verifier = consent_form(client)
    assert response.status_code == 200
    fields["scanner_key"] = bridge.scanner_key()
    response = client.post("/oauth/authorize", data=fields, headers={"Origin": mcp.ORIGIN}, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = urlparse(response.headers["location"])
    assert location.scheme + "://" + location.netloc + location.path == mcp.REDIRECT
    q = parse_qs(location.query)
    assert q["iss"] == [mcp.ORIGIN] and q["state"] == [fields["state"]]
    return {"grant_type": "authorization_code", "code": q["code"][0],
            "code_verifier": verifier, "client_id": mcp.CLIENT,
            "redirect_uri": mcp.REDIRECT, "resource": mcp.RESOURCE}


def access(client):
    response = client.post("/oauth/token", data=grant(client))
    assert response.status_code == 200
    return response.json()


def rpc(client, credential, method, params=None, ident=1, **kwargs):
    headers = {"Authorization": "Bearer " + credential} if credential else {}
    headers.update(kwargs.pop("headers", {}))
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": ident,
                       "method": method, "params": params or {}}, headers=headers, **kwargs)


def test_discovery_consent_headers_no_secrets(setup):
    client, _ = setup
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.json()["resource"] == mcp.RESOURCE
    assert client.get("/.well-known/oauth-protected-resource/mcp").json() == r.json()
    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["authorization_response_iss_parameter_supported"] is True
    response, _, _ = consent_form(client)
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    # Browser-native form submissions must retain Origin for the server's CSRF
    # check and be allowed to follow the one registered HTTPS OAuth callback.
    assert response.headers["referrer-policy"] == "same-origin"
    directives = dict(part.strip().split(" ", 1)
                      for part in response.headers["content-security-policy"].split(";"))
    assert directives["form-action"].split() == ["'self'", mcp.REDIRECT]
    assert "HttpOnly" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert bridge.scanner_key() not in response.text


@pytest.mark.parametrize("field,value", [
    ("redirect_uri", "https://attacker.invalid/callback"), ("resource", "https://attacker.invalid/mcp"),
    ("client_id", "other-client"), ("scope", "admin"), ("code_challenge_method", "plain"),
    ("state", "short"), ("code_challenge", "bad"), ("response_type", "token"),
])
def test_invalid_oauth_requests_do_not_redirect(setup, field, value):
    client, _ = setup
    response, _, _ = consent_form(client, {field: value})
    assert response.status_code == 400 and "location" not in response.headers


def test_consent_requires_owner_key_csrf_and_origin(setup):
    client, _ = setup
    _, form, _ = consent_form(client)
    form["scanner_key"] = bridge.scanner_key()
    assert client.post("/oauth/authorize", data=form).status_code == 400
    for origin in ("null", "https://attacker.invalid"):
        assert client.post("/oauth/authorize", data=form,
                           headers={"Origin": origin}).status_code == 400
    bad = dict(form, csrf="bad")
    assert client.post("/oauth/authorize", data=bad, headers={"Origin": mcp.ORIGIN}).status_code == 400
    bad = dict(form, scanner_key="bad")
    assert client.post("/oauth/authorize", data=bad, headers={"Origin": mcp.ORIGIN}).status_code == 401
    bad = dict(form, stamp="1")
    assert client.post("/oauth/authorize", data=bad, headers={"Origin": mcp.ORIGIN}).status_code == 400
    client.cookies.clear()
    assert client.post("/oauth/authorize", data=form, headers={"Origin": mcp.ORIGIN}).status_code == 400


def test_callback_and_token_responses_suppress_referrers(setup):
    client, _ = setup
    _, fields, verifier = consent_form(client)
    fields["scanner_key"] = bridge.scanner_key()
    response = client.post("/oauth/authorize", data=fields,
                           headers={"Origin": mcp.ORIGIN}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["referrer-policy"] == "no-referrer"
    q = parse_qs(urlparse(response.headers["location"]).query)
    token = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": q["code"][0],
        "code_verifier": verifier, "client_id": mcp.CLIENT,
        "redirect_uri": mcp.REDIRECT, "resource": mcp.RESOURCE,
    })
    assert token.status_code == 200
    assert token.headers["referrer-policy"] == "no-referrer"
    assert rpc(client, token.json()["access_token"], "tools/list").status_code == 200


def test_auth_rate_limit_and_no_credentials_in_store(setup):
    client, store = setup
    _, form, _ = consent_form(client)
    form["scanner_key"] = "invalid-key-not-for-storage"
    for _ in range(10):
        assert client.post("/oauth/authorize", data=form, headers={"Origin": mcp.ORIGIN}).status_code == 401
    form["scanner_key"] = bridge.scanner_key()
    assert client.post("/oauth/authorize", data=form, headers={"Origin": mcp.ORIGIN}).status_code == 429
    with store.engine.connect() as conn:
        saved = str(conn.execute(mcp.select(mcp.events)).all())
    assert "invalid-key-not-for-storage" not in saved and bridge.scanner_key() not in saved


@pytest.mark.parametrize("field,value", [
    ("code_verifier", "x" * 64), ("redirect_uri", "https://evil.invalid"),
    ("resource", "https://evil.invalid"), ("client_id", "other"), ("scope", "admin"),
])
def test_exchange_binding_pkce_and_single_use(setup, field, value):
    client, _ = setup
    body = grant(client)
    assert client.post("/oauth/token", data=body | {field: value}).status_code == 400
    assert client.post("/oauth/token", data=body).status_code == 200
    assert client.post("/oauth/token", data=body).status_code == 400


def test_tokens_are_scoped_expiring_revocable_and_hashed(setup, monkeypatch):
    client, store = setup
    issued = access(client)
    key = issued["access_token"]
    assert rpc(client, key, "ping").status_code == 200
    for path in ("/v1/owner/review", "/v1/chatgpt/model-status", "/v1/operations"):
        assert client.get(path, headers={"Authorization": "Bearer " + key}).status_code == 401
    assert rpc(client, bridge.scanner_key(), "ping").status_code == 401
    assert rpc(client, None, "ping").headers["www-authenticate"] == mcp.CHALLENGE
    with store.engine.connect() as conn:
        saved = str(conn.execute(mcp.select(mcp.events)).all())
    assert key not in saved and issued["refresh_token"] not in saved and bridge.scanner_key() not in saved
    monkeypatch.setenv("JABBAZI_MCP_TOKEN_VERSION", "2")
    assert rpc(client, key, "ping").status_code == 401
    monkeypatch.setenv("JABBAZI_MCP_TOKEN_VERSION", "1")
    with patch.object(mcp.time, "time", return_value=mcp.time.time() + 3700):
        assert rpc(client, key, "ping").status_code == 401
    monkeypatch.setenv("JABBAZI_MCP_ENABLED", "false")
    assert rpc(client, key, "ping").status_code == 503


def test_refresh_rotation_and_original_expiry(setup):
    client, _ = setup
    issued = access(client)
    body = {"grant_type": "refresh_token", "refresh_token": issued["refresh_token"],
            "client_id": mcp.CLIENT, "resource": mcp.RESOURCE}
    response = client.post("/oauth/token", data=body)
    assert response.status_code == 200
    assert response.json()["refresh_token"] != issued["refresh_token"]
    assert client.post("/oauth/token", data=body).status_code == 400
    assert rpc(client, response.json()["access_token"], "ping").status_code == 401
    body["refresh_token"] = response.json()["refresh_token"]
    assert client.post("/oauth/token", data=body).status_code == 400
    issued = access(client)
    body["refresh_token"] = issued["refresh_token"]
    with patch.object(mcp.time, "time", return_value=mcp.time.time() + 31*86400):
        assert client.post("/oauth/token", data=body).status_code == 400


def test_mcp_protocol_and_tool_surface(setup):
    client, _ = setup
    key = access(client)["access_token"]
    for version in mcp.VERSIONS:
        r = rpc(client, key, "initialize", {"protocolVersion": version})
        assert r.json()["result"]["protocolVersion"] == version
    r = rpc(client, key, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in r} == {"scan_everything", "get_scan_results", "get_model_status"}
    assert r[0]["annotations"]["readOnlyHint"] is False
    assert r[1]["annotations"]["readOnlyHint"] is True
    assert all(t["securitySchemes"][0]["scopes"] == [mcp.SCOPE] for t in r)
    assert rpc(client, key, "notifications/initialized", ident=None).status_code == 202
    assert rpc(client, key, "unknown").json()["error"]["code"] == -32601
    assert rpc(client, key, "tools/call", {"name": "place_bet"}).json()["result"]["isError"]
    assert rpc(client, key, "ping", headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert rpc(client, key, "ping", headers={"MCP-Protocol-Version": "invalid"}).status_code == 400
    assert rpc(client, key, "ping", ident=None).status_code == 400
    assert client.get("/mcp", headers={"Authorization": "Bearer " + key}).status_code == 405


def test_real_bridge_job_idempotence_probability_provenance_and_stale_guard(setup):
    client, store = setup
    key = access(client)["access_token"]
    scan_id = str(uuid4())
    with patch.object(bridge, "run_background") as background:
        for _ in range(2):
            r = rpc(client, key, "tools/call", {"name": "scan_everything", "arguments": {"request_id": scan_id}})
            result = r.json()["result"]
            assert not result["isError"] and result["structuredContent"]["scan_id"] == scan_id
        background.assert_called_once_with(scan_id)
        other = rpc(client, key, "tools/call", {"name": "scan_everything", "arguments": {"request_id": str(uuid4())}})
        assert other.json()["result"]["isError"]
    now = datetime.now(UTC)
    action = {"event": "Test @ Fixture", "sport": "americanfootball_nfl",
              "source_timestamp": (now-timedelta(minutes=3)).isoformat(),
              "starts_at": (now+timedelta(hours=2)).isoformat(),
              "model_probability": ".537", "model_version": "test-shadow-version",
              "consensus_probability": ".510", "uncertainty": ".08", "expected_roi": None,
              "stale": False, "in_play": False}
    store.append("chatgpt_scan_result", scan_id, {"status": "COMPLETE", "generated_at": now.isoformat(),
                 "actions": [action]*26, "total_actions": 26, "errors": []}, digest(["chatgpt_scan_result", scan_id]))
    r = rpc(client, key, "tools/call", {"name": "get_scan_results", "arguments": {"scan_id": scan_id, "page": 2}})
    data = r.json()["result"]["structuredContent"]
    assert data["page_action_count"] == 1 and data["total_returned_actions"] == 26
    assert data["betting_enabled"] is False
    row = data["actions"][0]
    assert row["model_probability"] == ".537" and row["model_version"] == "test-shadow-version"
    assert row["consensus_probability"] == ".510" and row["probability_status"] == "SHADOW_ONLY"
    assert row["decision"] == "STALE DATA" and row["stake_dollars"] == "0"
    assert row["expected_roi"] is None and row["maximum_playable_price"] is None
    assert json.loads(r.json()["result"]["content"][0]["text"]) == data


def test_oauth_duplicate_fields_and_rpc_body_limits(setup):
    client, _ = setup
    assert client.post("/oauth/token", content="client_id=a&client_id=b",
                       headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 400
    key = access(client)["access_token"]
    r = rpc(client, key, "ping", {"oversized": "x" * 17000})
    assert r.status_code == 400


def test_official_mcp_client_discovers_tools_and_calls_shared_model_registry(setup):
    import asyncio
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    client, _ = setup
    key = access(client)["access_token"]

    async def check():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                     headers={"Authorization": "Bearer " + key}) as http:
            async with streamable_http_client(mcp.RESOURCE, http_client=http, terminate_on_close=False) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    assert initialized.server_info.name == "jabbazi-private-scanner"
                    tools = await session.list_tools()
                    assert len(tools.tools) == 3
                    result = await session.call_tool("get_model_status", {})
                    assert not result.is_error
                    models = result.structured_content["models"]
                    assert any(r["sport"] == "americanfootball_nfl" for r in models)
                    assert any(r["sport"] == "baseball_mlb" for r in models)
                    assert all(r["approved_for_betting"] is False for r in models)
    asyncio.run(check())
