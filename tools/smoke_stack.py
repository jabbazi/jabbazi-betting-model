"""Exercise a disposable CI stack. Refuses ordinary/production invocation."""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta


def main():
    if os.getenv("JABBAZI_STACK_TEST_MODE") != "1":
        raise SystemExit("This creates synthetic ledger records; disposable CI only")
    token = os.environ["JABBAZI_STACK_TEST_TOKEN"]
    base = "http://127.0.0.1:18000"

    def request(path, data=None, auth=True):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(data).encode() if data else None,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": "Bearer " + token} if auth else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    if os.getenv("JABBAZI_STACK_EXPECT_OUTAGE") == "1":
        assert request("/readyz")[0] == 503
        assert request("/v1/scans/run", {"mode": "quick"})[0] == 503
        print(json.dumps({"database_outage": "passed", "no_actionable_scan": True}))
        return
    assert request("/healthz")[0] == 200
    assert request("/readyz")[1]["betting_enabled"] is False
    assert request("/v1/ledger", auth=False)[0] == 401
    body = {
        "idempotency_key": "ci-only-ticket",
        "sport": "americanfootball_nfl",
        "event_id": "ci-event",
        "market": "h2h",
        "selection": "Synthetic test team",
        "sportsbook": "CI fixture",
        "decimal_odds": "2.0",
        "stake": "15.00",
        "placed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "ticket_reference": "SYNTHETIC CI TEST",
        "theses": ["ci-event:test"],
    }
    assert request("/v1/ledger/import", body)[0] == 200
    assert request("/v1/ledger/import", body)[1]["created"] is False
    assert float(request("/v1/ledger")[1]["open_exposure"]) == 15
    settlement = {
        "idempotency_key": "ci-only-settlement",
        "result": "loss",
        "evidence_reference": "SYNTHETIC CI RESULT",
    }
    assert request("/v1/ledger/ci-only-ticket/settle", settlement)[1]["profit"] == "-15.00"
    assert len(request("/v1/ledger/ci-only-ticket/history")[1]["events"]) == 2
    assert request("/v1/ledger/ci-only-ticket/clv")[1]["status"] == "UNAVAILABLE"
    for _ in range(20):
        workers = request("/v1/operations")[1]["workers"]
        if workers:
            break
        time.sleep(0.5)
    assert workers and workers[0]["payload"]["status"] == "WAITING_FOR_ODDS_CREDENTIAL"
    assert request("/v1/scans/run", {"mode": "quick"})[0] == 503
    print(
        json.dumps(
            {
                "postgres_docker_http": "passed",
                "owner_ledger": "passed",
                "worker_heartbeat": "passed",
                "missing_provider": "fail_closed",
                "betting_enabled": False,
            }
        )
    )


if __name__ == "__main__":
    main()
