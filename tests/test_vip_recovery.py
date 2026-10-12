"""Regression checks for bounded API pools and VIP handoff reliability."""
from pathlib import Path

import pytest

from jabazi.persistence import store as persistence


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
