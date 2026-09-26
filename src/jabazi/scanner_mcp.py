"""Private single-owner MCP bridge with OAuth code/PKCE and rotating refresh grants.

Only scan/status/results are exposed. All execution reuses chatgpt_api's quota,
idempotence, persistence and shadow-only presentation. No provider key leaves here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from . import chatgpt_api as bridge
from .persistence.store import digest, events

router = APIRouter()
ORIGIN = bridge.ORIGIN
RESOURCE = ORIGIN + "/mcp"
CLIENT = "jabbazi-chatgpt"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
SCOPE = "scanner:research"
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}
CHALLENGE = f'Bearer resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource", scope="{SCOPE}"'
COOKIE = "__Host-jabbazi-mcp-consent"


def enabled():
    if os.getenv("JABBAZI_MCP_ENABLED", "true").lower() != "true":
        raise HTTPException(503, "Private scanner connection disabled")
    bridge.scanner_key()  # Existing global disable/revocation also applies.


def epoch():
    enabled()
    return digest([bridge.scanner_key(), os.getenv("JABBAZI_MCP_TOKEN_VERSION", "1")])


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def row(conn, kind, entity):
    return bridge.record(conn, kind, entity)


def append(store, conn, kind, entity, payload):
    store._append(conn, kind, entity, payload, digest([kind, entity]))


def oauth_error(code="invalid_request", status=400):
    return JSONResponse({"error": code}, status_code=status, headers=HEADERS)


def consent_params(values):
    required = {"client_id", "redirect_uri", "response_type", "scope", "state",
                "code_challenge", "code_challenge_method", "resource"}
    if not required.issubset(values):
        raise ValueError("Incomplete authorization request")
    p = {k: values[k] for k in required}
    if (p["client_id"] != CLIENT or p["redirect_uri"] != REDIRECT
            or p["response_type"] != "code" or p["resource"] != RESOURCE
            or p["scope"] != SCOPE or p["code_challenge_method"] != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", p["code_challenge"])
            or not 16 <= len(p["state"]) <= 1024):
        raise ValueError("Invalid authorization request")
    return p


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def resource_metadata():
    enabled()
    return JSONResponse({"resource": RESOURCE, "authorization_servers": [ORIGIN],
                         "scopes_supported": [SCOPE], "resource_name": "JABBAZI Private Scanner"},
                        headers=HEADERS)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_metadata():
    enabled()
    return JSONResponse({
        "issuer": ORIGIN, "authorization_endpoint": ORIGIN + "/oauth/authorize",
        "token_endpoint": ORIGIN + "/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"], "scopes_supported": [SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }, headers=HEADERS)


@router.get("/oauth/authorize", include_in_schema=False)
def consent(request: Request):
    enabled()
    try:
        p = consent_params(dict(request.query_params))
    except ValueError:
        return oauth_error()
    nonce = secrets.token_urlsafe(32)
    stamp = str(int(time.time()))
    binding = hmac.new(epoch().encode(), (digest(p) + nonce + stamp).encode(), hashlib.sha256).hexdigest()
    fields = p | {"csrf": binding, "stamp": stamp}
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v, quote=True)}">'
                     for k, v in fields.items())
    body = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect JABBAZI</title>
<style>body{{font:17px system-ui;background:#100b1e;color:#eee;margin:0;padding:32px}}
main{{max-width:520px;margin:4vh auto}}input,button{{box-sizing:border-box;width:100%;padding:16px;
margin:12px 0;border-radius:10px;font:inherit}}button{{background:#8648ef;color:white;border:0}}</style>
<main><h1>Connect your private JABBAZI scanner</h1>
<p>Authorize ChatGPT to start research scans and read NFL/MLB model probabilities and scan results.
Each new scan uses the configured odds-provider credit budget within your existing limits.</p>
<p>This connection cannot place bets, edit your ledger, publish to Discord or access your provider keys.
Models remain research only.</p>
<form method="post" action="/oauth/authorize">{hidden}
<label for="key">Private scanner key</label>
<input id="key" name="scanner_key" type="password" autocomplete="off" required
 placeholder="Your existing JABBAZI Scanner GPT key">
<p>Use the scanner key from your owner setup page. Never paste it into a chat.</p>
<button type="submit">Authorize my ChatGPT connection</button></form></main></html>'''
    response = HTMLResponse(body, headers=HEADERS | {
        # A native form POST with no-referrer sends Origin: null, which correctly
        # fails approve()'s origin check. Keep the real origin on same-origin
        # submits; suppress referrers when leaving this site. Other OAuth
        # responses keep HEADERS' no-referrer policy.
        "Referrer-Policy": "same-origin",
        # Chromium also checks form-action on the 303 OAuth callback redirect.
        # Permit only our form target and the existing, exact ChatGPT callback.
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            f"form-action 'self' {REDIRECT}; base-uri 'none'; frame-ancestors 'none'"
        ),
        "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
    })
    response.set_cookie(COOKIE, nonce, max_age=600, secure=True, httponly=True, samesite="strict", path="/")
    return response


async def form_values(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise ValueError("Form required")
    raw = await limited_body(request, 8192)
    values = parse_qs(raw.decode(), keep_blank_values=True, max_num_fields=20)
    if any(len(v) != 1 for v in values.values()):
        raise ValueError("Duplicate parameter")
    return {k: v[0] for k, v in values.items()}


async def limited_body(request, limit):
    parts = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > limit:
            raise ValueError("Request too large")
        parts.append(part)
    return b"".join(parts)


def issue_code(p, supplied_key, request_ip):
    # Persist rate limits across restarts; never store a credential or IP address.
    identity = hmac.new(epoch().encode(), request_ip.encode(), hashlib.sha256).hexdigest()
    store = bridge.store_factory()
    try:
        with store.transaction() as conn:
            recent = conn.execute(select(events.c.id).where(
                events.c.kind == "mcp_auth_attempt", events.c.entity == identity,
                events.c.occurred_at > datetime.now(UTC) - timedelta(minutes=10),
            ).limit(10)).all()
            if len(recent) >= 10:
                return oauth_error("temporarily_unavailable", 429)
            store._append(conn, "mcp_auth_attempt", identity, {}, secrets.token_hex(32))
            if not hmac.compare_digest(supplied_key.encode(), bridge.scanner_key().encode()):
                return oauth_error("access_denied", 401)
            code = secrets.token_urlsafe(32)
            append(store, conn, "mcp_auth_code", hashed(code), p | {"expires": time.time() + 300, "epoch": epoch()})
        response = RedirectResponse(REDIRECT + "?" + urlencode({"code": code, "state": p["state"], "iss": ORIGIN}), status_code=303, headers=HEADERS)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
    finally:
        store.close()


@router.post("/oauth/authorize", include_in_schema=False)
async def approve(request: Request):
    enabled()
    try:
        if request.headers.get("origin") != ORIGIN:
            raise ValueError("Cross-origin consent blocked")
        values = await form_values(request)
        p = consent_params(values)
        nonce = request.cookies.get(COOKIE, "")
        stamp = values.get("stamp", "")
        if not nonce or not 0 <= time.time() - int(stamp) <= 600:
            raise ValueError("Consent expired")
        expected = hmac.new(epoch().encode(), (digest(p) + nonce + stamp).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(values.get("csrf", ""), expected):
            raise ValueError("Invalid consent binding")
    except (ValueError, UnicodeError):
        return oauth_error()
    return await run_in_threadpool(issue_code, p, values.get("scanner_key", ""), request.client.host if request.client else "unknown")


def exchange(values):
    enabled()
    if values.get("client_id") != CLIENT or values.get("resource") != RESOURCE:
        return oauth_error("invalid_client")
    kind = values.get("grant_type")
    if kind not in ("authorization_code", "refresh_token"):
        return oauth_error("unsupported_grant_type")
    if "scope" in values and values["scope"] != SCOPE:
        return oauth_error("invalid_scope")
    store = bridge.store_factory()
    try:
        with store.transaction() as conn:
            is_code = kind == "authorization_code"
            value = values.get("code" if is_code else "refresh_token", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
                return oauth_error("invalid_grant")
            identity = hashed(value)
            grant = row(conn, "mcp_auth_code" if is_code else "mcp_refresh", identity)
            consumed = row(conn, "mcp_consumed", identity)
            if not grant:
                return oauth_error("invalid_grant")
            payload = grant["payload"]
            family = identity if is_code else payload["family"]
            if consumed:
                if not is_code:
                    append(store, conn, "mcp_revoked", family, {})
                return oauth_error("invalid_grant")
            if row(conn, "mcp_revoked", family):
                return oauth_error("invalid_grant")
            if payload["expires"] <= time.time() or payload["epoch"] != epoch():
                return oauth_error("invalid_grant")
            if is_code:
                verifier = values.get("code_verifier", "")
                if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                    return oauth_error("invalid_grant")
                proof = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                if values.get("redirect_uri") != REDIRECT or not hmac.compare_digest(proof, payload["code_challenge"]):
                    return oauth_error("invalid_grant")
            append(store, conn, "mcp_consumed", identity, {})
            access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            # A refresh never extends the original 30-day owner authorization.
            deadline = time.time() + 30 * 86400 if is_code else payload["expires"]
            common = {"epoch": epoch(), "client_id": CLIENT, "resource": RESOURCE, "scope": SCOPE, "family": family}
            append(store, conn, "mcp_access", hashed(access), common | {"expires": min(time.time() + 3600, deadline)})
            append(store, conn, "mcp_refresh", hashed(refresh), common | {"expires": deadline})
        return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": int(min(3600, deadline-time.time())),
                             "refresh_token": refresh, "scope": SCOPE}, headers=HEADERS)
    finally:
        store.close()


@router.post("/oauth/token", include_in_schema=False)
async def token(request: Request):
    try:
        values = await form_values(request)
    except (ValueError, UnicodeError):
        return oauth_error()
    return await run_in_threadpool(exchange, values)


def authenticate(header):
    enabled()
    supplied = header[7:] if header and header.startswith("Bearer ") else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", supplied):
        raise HTTPException(401, "Connect your private scanner", headers={"WWW-Authenticate": CHALLENGE} | HEADERS)
    store = bridge.store_factory()
    try:
        with store.engine.connect() as conn:
            grant = row(conn, "mcp_access", hashed(supplied))
            revoked = row(conn, "mcp_revoked", grant["payload"]["family"]) if grant else None
        p = grant["payload"] if grant else {}
        if (revoked or p.get("expires", 0) <= time.time() or p.get("epoch") != epoch()
                or p.get("resource") != RESOURCE or p.get("scope") != SCOPE or p.get("client_id") != CLIENT):
            raise HTTPException(401, "Reconnect your private scanner", headers={"WWW-Authenticate": CHALLENGE} | HEADERS)
    finally:
        store.close()


def tool(name, description, properties, required, readonly):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            "annotations": {"readOnlyHint": readonly, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": not readonly},
            "securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}],
            "_meta": {"securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}]}}


TOOLS = [
    tool("scan_everything", "Use when the owner says scan everything or requests a new JABBAZI model scan. Starts the real cloud scanner with current team and deployed NFL/MLB player-model research probabilities plus supported odds. Uses the configured provider-credit budget and persists research records. Reuse the same UUID on retries. Poll get_scan_results until complete; running responses include live progress when available. Never infer unsupported probabilities or betting approval. No wagers or Discord posts.",
         {"request_id": {"type": "string", "format": "uuid", "description": "A new UUID per explicit new scan; reuse on retries."}}, ["request_id"], False),
    tool("get_scan_results", "Read one real scan page, waiting up to 10 seconds if RUNNING. Continue the same scan_id until terminal. Each page contains at most 25 rows. Total coverage is across all pages; fetch further pages for full retained coverage. Report scan ID, generated time, model version and coverage. Keep market consensus separate from model probability; all estimates remain research only. Stale prices are unavailable for action.",
         {"scan_id": {"type": "string", "format": "uuid"}, "page": {"type": "integer", "minimum": 1, "maximum": 11, "default": 1}}, ["scan_id"], True),
    tool("get_model_status", "Read deployed NFL/MLB model versions, refresh timestamps, coverage and SHADOW_ONLY/UNAVAILABLE status without consuming odds-provider credits. Model readiness does not mean betting approval or profitable edge.", {}, [], True),
]


def invoke(name, args, tasks):
    auth = "Bearer " + bridge.scanner_key()
    if name == "scan_everything":
        body = bridge.ScanEverythingRequest.model_validate(args)
        return bridge.start_scan(body, tasks, auth)
    if name == "get_scan_results":
        if set(args) - {"scan_id", "page"} or "scan_id" not in args:
            raise ValueError("Invalid result arguments")
        page = args.get("page", 1)
        if type(page) is not int or not 1 <= page <= 11:
            raise ValueError("Invalid page")
        return bridge.get_results(UUID(args["scan_id"]), page, auth)
    if name == "get_model_status" and not args:
        return bridge.model_status(auth)
    raise ValueError("Unknown tool or invalid arguments")


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp(request: Request, tasks: BackgroundTasks):
    enabled()
    # No browser-origin MCP access. ChatGPT calls this endpoint server-to-server.
    origin = request.headers.get("origin")
    if origin and origin not in (ORIGIN, "https://chatgpt.com"):
        raise HTTPException(403, "Origin not permitted")
    await run_in_threadpool(authenticate, request.headers.get("authorization"))
    if request.method != "POST":
        return Response(status_code=405, headers=HEADERS | {"Allow": "POST"})
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return Response(status_code=415, headers=HEADERS)
    if request.headers.get("mcp-protocol-version", VERSIONS[0]) not in VERSIONS:
        return Response(status_code=400, headers=HEADERS)
    ident = None
    try:
        message = json.loads(await limited_body(request, 16384))
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC request")
        ident = message.get("id")
        if ident is not None and (type(ident) not in (int, str) or len(str(ident)) > 128):
            ident = None
            raise ValueError("Invalid ID")
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("Invalid params")
        if ident is None:
            if method not in ("notifications/initialized", "notifications/cancelled"):
                raise ValueError("Request ID required")
            return Response(status_code=202, headers=HEADERS)
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in VERSIONS else VERSIONS[0],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "jabbazi-private-scanner", "version": "1.0.0"},
                      "instructions": "Use scan_everything for explicit new scans, then poll get_scan_results. Never substitute guessed probabilities. Respect each returned team/player market validation stage; only PRODUCTION_APPROVED may influence cash. No wagering or publishing tools."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            args = params.get("arguments", {})
            if not isinstance(args, dict):
                raise ValueError("Invalid arguments")
            try:
                response = await run_in_threadpool(invoke, params.get("name"), args, tasks)
                data = json.loads(response.body)
                result = {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": False}
            except (HTTPException, ValueError, TypeError):
                # Generic errors don't expose credentials, provider details or request bodies.
                result = {"content": [{"type": "text", "text": "Scanner request unavailable or invalid. Check model status or retrieve the existing scan. Do not invent results or repeatedly launch scans."}], "isError": True}
        else:
            return JSONResponse({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}}, headers=HEADERS)
        return JSONResponse({"jsonrpc": "2.0", "id": ident, "result": result}, headers=HEADERS)
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"jsonrpc": "2.0", "id": ident, "error": {"code": -32600, "message": "Invalid request"}}, status_code=400, headers=HEADERS)
