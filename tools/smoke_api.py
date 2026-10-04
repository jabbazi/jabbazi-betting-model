"""Start a disposable local API and verify real HTTP/database behavior.

Uses synthetic evidence, a temporary database and an ephemeral service token.
Never contacts an odds provider or Discord.
"""

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from jabazi.persistence.store import Store


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        url = "sqlite:///" + str(Path(directory) / "service.db")
        database = Store(url, initialize=True)
        database.append(
            "candidate", "SMOKE_TEST", {"decision": "WATCH", "source": "SYNTHETIC_TEST_ONLY"}
        )
        database.close()
        token = secrets.token_urlsafe(32)
        env = {
            **os.environ,
            "PYTHONPATH": str(root / "src"),
            "JABBAZI_PLATFORM_DATABASE_URL": url,
            "JABBAZI_MODEL_TOKEN": token,
            "JABAZI_ODDS_API_KEY": "",
            "JABAZI_ENV": "development",
        }
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "jabazi.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError("API process exited before readiness")
                try:
                    with urllib.request.urlopen(base + "/healthz", timeout=1) as response:
                        health = json.load(response)
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("API did not become ready")
            with urllib.request.urlopen(base + "/readyz", timeout=2) as response:
                readiness = json.load(response)
            unauthorized = None
            try:
                urllib.request.urlopen(base + "/v1/candidates", timeout=2)
            except urllib.error.HTTPError as error:
                unauthorized = error.code
            request = urllib.request.Request(
                base + "/v1/candidates", headers={"Authorization": "Bearer " + token}
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                data = json.load(response)
            request = urllib.request.Request(
                base + "/v1/scans/run",
                data=b"{}",
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            missing_provider = None
            try:
                urllib.request.urlopen(request, timeout=2)
            except urllib.error.HTTPError as error:
                missing_provider = error.code
            assert health["status"] == "ok" and readiness["database"] == "ready"
            assert (
                readiness["betting_enabled"] is False
                and unauthorized == 401
                and missing_provider == 503
            )
            assert data["records"][0]["payload"]["source"] == "SYNTHETIC_TEST_ONLY"
            print(
                json.dumps(
                    {
                        "actual_http_smoke": "passed",
                        "liveness": 200,
                        "readiness": 200,
                        "unauthenticated": unauthorized,
                        "authenticated_database_read": 200,
                        "missing_odds_provider": missing_provider,
                        "betting_enabled": False,
                    }
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stderr:
                process.stderr.close()


if __name__ == "__main__":
    main()
