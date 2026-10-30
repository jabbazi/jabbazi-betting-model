"""Safety contract for the isolated Render preview."""
from tools.preview_readonly import HTML, health, Handler
import inspect


def test_preview_has_no_wagering_or_live_data():
    data = health()
    assert data["status"] == "PREVIEW_ONLY"
    assert data["live_data"] is False
    assert data["provider_requests"] is False
    assert data["production_approved"] is False
    assert data["betting_enabled"] is False


def test_preview_is_explicitly_synthetic_and_has_no_secret_or_data_routes():
    assert "NO LIVE PLAYER DATA" in HTML
    assert "All wagers are disabled" in HTML
    assert "LAB PLAYER PROPS UNSUPPORTED" in HTML
    assert "Player rows: unavailable" in HTML
    assert "no provider credentials" in HTML
    source = inspect.getsource(Handler)
    assert "api_key" not in source
    assert "JABBAZI_PLATFORM_DATABASE_URL" not in source
    assert "httpx" not in source
    assert "requests" not in source
    assert 'self.path == "/healthz"' in source
    assert 'self.path in ("/", "/index.html")' in source
    assert "self.send_error(404" in source
