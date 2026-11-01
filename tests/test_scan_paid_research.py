"""A full owner scan audits paid sources without inventing model hit probabilities."""
import json
from datetime import date

import httpx
import pytest

from jabazi.scan_paid_research import collect_paid_player_research
from jabazi.vip.paid_models import read_paid_player_models


DAY = date(2026, 11, 1)


def test_all_leagues_are_reported_and_only_supported_lab_feeds_are_queried():
    seen = []

    def reader(key, sport, day, *, request_budget):
        seen.append((key, sport, day, request_budget))
        return {
            "coverage_complete": True,
            "state": "RESEARCH_ONLY",
            "models_found": 2,
            "predictions_seen": 4,
            "rows": [{
                "player_name": "DO_NOT_PRINT_PRIVATE_PLAYER",
                "model_signal_value": .99,
                "bookmaker_price": 1000,
            }],
            "requests_used": 3,
        }

    output = collect_paid_player_research(
        "connected-lab-key", DAY, reader=reader, max_requests_per_sport=7
    )
    assert [(x[1], x[3]) for x in seen] == [("NBA", 7), ("NFL", 7)]
    assert [x["sport"] for x in output["sports"]] == ["NBA", "NFL", "NHL"]
    assert output["sports"][0]["research_signal_rows"] == 1
    assert output["sports"][0]["requests_used"] == 3
    assert output["sports"][2]["reason"] == "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
    assert output["all_sports_coverage_complete"] is False
    assert output["betting_enabled"] is False
    assert output["all_paid_player_hit_probabilities_verified"] is False
    assert "DO_NOT_PRINT_PRIVATE_PLAYER" not in json.dumps(output)
    assert ".99" not in json.dumps(output)
    assert "connected-lab-key" not in json.dumps(output)


def test_missing_key_avoids_paid_calls_and_reports_all_sports():
    def fail(*args, **kwargs):
        raise AssertionError("No paid request may happen without a credential")

    out = collect_paid_player_research("", DAY, reader=fail)
    assert [x["reason"] for x in out["sports"]] == [
        "NO_CREDENTIAL", "NO_CREDENTIAL", "LAB_NHL_PLAYER_PROPS_NOT_SUPPORTED"
    ]
    assert all(x["requests_used"] == 0 for x in out["sports"])


def test_one_sport_failure_cannot_remove_healthy_independent_sport():
    def reader(key, sport, day, *, request_budget):
        if sport == "NBA":
            raise RuntimeError("PRIVATE_KEY_DO_NOT_LOG")
        return {
            "coverage_complete": True, "state": "NO_PREDICTIONS",
            "models_found": 1, "predictions_seen": 0, "rows": [],
            "requests_used": 2,
        }

    result = collect_paid_player_research("ok", DAY, reader=reader)
    assert result["sports"][0]["reason"] == "PAID_RESEARCH_UNAVAILABLE"
    assert result["sports"][1]["coverage_complete"] is True
    assert result["sports"][1]["state"] == "NO_PREDICTIONS"
    assert "PRIVATE_KEY_DO_NOT_LOG" not in json.dumps(result)
    assert result["all_paid_player_hit_probabilities_verified"] is False


@pytest.mark.parametrize("budget", [0, -1, 21, True, 3.5, "4"])
def test_bad_paid_budget_rejected_before_external_access(budget):
    with pytest.raises(ValueError):
        collect_paid_player_research("ok", DAY, max_requests_per_sport=budget)


def test_lab_reader_enforces_request_budget_on_paginated_provider():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [
                {"id": 12, "sport": "nba", "model_type": "player_prop",
                 "prop_type": "points"},
            ], "meta": {}})
        return httpx.Response(200, json={"data": [{"id": 1, "model_id": 12,
            "player_id": 2, "game_id": 3, "predicted_value": 1.7}],
            "meta": {}})

    transport = httpx.MockTransport(respond)
    out = read_paid_player_models("ok", "NBA", DAY, transport=transport, request_budget=1)
    assert out["state"] == "UNAVAILABLE"
    assert out["reason"] == "REQUEST_BUDGET_EXHAUSTED"
    assert out["requests_used"] == 1
    assert calls == ["/lab/v1/models"]
    with pytest.raises(ValueError):
        read_paid_player_models("ok", "NBA", DAY, request_budget=0)
