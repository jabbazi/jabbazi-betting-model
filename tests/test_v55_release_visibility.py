"""Ensure V5.5 shell updates are visible instead of reusing stale PWA assets."""
from fastapi.testclient import TestClient

from jabazi.api import app
from jabazi import member_api


def test_release_identity_and_versioned_assets(monkeypatch):
    commit = "a" * 40
    monkeypatch.setenv("RENDER_GIT_COMMIT", commit)
    client = TestClient(app)
    response = client.get("/vip")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f'/vip/terminal.js?v={commit}' in response.text
    assert f'/vip/terminal.css?v={commit}' in response.text
    assert f'<meta name="jabbazi-release" content="{commit}">' in response.text
    assert "V5.5 · +EV INTELLIGENCE" in response.text
    version = client.get("/vip/version")
    assert version.status_code == 200
    assert version.json() == {"release": commit}
    assert version.headers["cache-control"] == "no-store"


def test_release_never_reflects_arbitrary_environment_values(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "private-value<script>")
    assert member_api._vip_release() == "development"
    response = TestClient(app).get("/vip")
    assert "private-value" not in response.text
    assert "__JABBAZI_RELEASE__" not in response.text


def test_vip_update_notice_is_wired_and_script_valid():
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parents[1] / "src/jabazi/static"
    html = (root / "terminal.html").read_text()
    script = (root / "terminal.js").read_text()
    assert 'id="update-notice"' in html
    assert "function checkRelease()" in script
    assert "window.addEventListener('focus',checkRelease)" in script
    result = subprocess.run(["node", "--check", str(root / "terminal.js")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
