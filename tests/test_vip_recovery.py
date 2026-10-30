"""Regression checks for bounded API pools and VIP handoff reliability."""
from pathlib import Path

import pytest

from jabazi.persistence import store as persistence
from test_member_portal import portal as _portal_fixture

portal = _portal_fixture


def test_api_shared_pool_is_not_disposed_per_request(monkeypatch):
    class FakeEngine:
        disposed = False
        def dispose(self):
            self.disposed = True
    engine = FakeEngine()
    monkeypatch.setattr(persistence, "_shared_postgres_engine", lambda url: engine)
    first = persistence.Store("postgresql+psycopg://user:pass@localhost/test", shared=True)
    second = persistence.Store("postgresql+psycopg://user:pass@localhost/test", shared=True)
    assert first.engine is second.engine
    first.close()
    assert not engine.disposed
    second.close()
    assert not engine.disposed


def test_shared_pool_rejects_sqlite():
    with pytest.raises(ValueError, match="PostgreSQL"):
        persistence.Store("sqlite:///:memory:", shared=True)


def test_vip_frontend_has_bounded_requests_and_no_auto_ticket_replay():
    source = (Path(__file__).parents[1] / "src/jabazi/static/terminal.js").read_text()
    assert "AbortController()" in source
    assert "controller.abort(),12000" in source
    assert "await api('/v1/member/session'" in source
    assert "history.replaceState(null,'','/vip#home');" in source
    assert "Retry existing session" in source
    assert "Retry this view" in source
    assert "serviceWorker.register(" not in source


def test_vip_home_does_not_project_heavy_board(monkeypatch, portal):
    from jabazi.vip import data
    from test_member_portal import sign_in
    store, client = portal
    sign_in(store, client)
    monkeypatch.setattr(data, "board", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("heavy board read")))
    monkeypatch.setattr(data, "official", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("heavy official read")))
    result = client.get("/v1/vip/home")
    assert result.status_code == 200
    payload = result.json()
    assert payload["load_strategy"] == "on_demand"
    assert payload["research"] == []
    assert payload["official"] == []


def test_model_status_refresh_is_nonblocking(monkeypatch):
    import concurrent.futures
    from jabazi.vip import model_cache
    waiting = concurrent.futures.Future()
    monkeypatch.setattr(model_cache, "_future", None)
    monkeypatch.setattr(model_cache, "_cache", None)
    monkeypatch.setattr(model_cache, "_error_at", 0.0)
    monkeypatch.setattr(model_cache._executor, "submit", lambda fn: waiting)
    first = model_cache.status(lambda: None)
    assert first["state"] == "REFRESHING"
    assert first["data"] is None
    waiting.set_result({"models": [], "errors": []})
    second = model_cache.status(lambda: None)
    assert second["state"] == "READY"
    assert second["data"]["models"] == []
