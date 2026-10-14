import io
import urllib.error
from datetime import UTC, datetime
from unittest.mock import patch

from jabazi.providers.player_features_live import LivePlayerFeatureCollector


def test_provider_key_is_trimmed_and_sent_only_in_header():
    collector = LivePlayerFeatureCollector(sportsdataio_api_key="  test-secret-only\n")
    with patch("urllib.request.urlopen", return_value=io.BytesIO(b"2026")) as open_url:
        assert collector._sportsdata("nfl/scores/json/CurrentSeason") == 2026
    request = open_url.call_args.args[0]
    assert request.full_url == "https://api.sportsdata.io/v3/nfl/scores/json/CurrentSeason"
    assert "test-secret-only" not in request.full_url
    assert request.get_header("Ocp-apim-subscription-key") == "test-secret-only"


def test_missing_key_makes_no_requests():
    with patch("urllib.request.urlopen") as open_url:
        status = LivePlayerFeatureCollector(sportsdataio_api_key=" \n").provider_status()
    assert status["configured"] is False
    open_url.assert_not_called()


def test_unauthorized_status_identifies_endpoint_without_leaking_exception():
    def rejected(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 401, "secret must never appear", {}, None)
    with patch("urllib.request.urlopen", side_effect=rejected):
        status = LivePlayerFeatureCollector(sportsdataio_api_key="test-secret-only").provider_status()
    assert status["nfl"]["endpoint"] == "nfl/scores/json/CurrentSeason"
    assert status["mlb"]["endpoint"].startswith("mlb/projections/json/")
    assert status["nfl"]["error"] == "HTTP_401"
    assert "test-secret-only" not in str(status) and "secret must never appear" not in str(status)
    assert not status["nfl"]["ok"] and not status["mlb"]["ok"]


def test_projection_entitlement_failure_distinct_from_scores_access():
    def response(request, **kwargs):
        if request.full_url.endswith("CurrentSeason"):
            return io.BytesIO(b"2026")
        if request.full_url.endswith("CurrentWeek"):
            return io.BytesIO(b"4")
        if "/nfl/projections/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)
        return io.BytesIO(b"[]")
    with patch("urllib.request.urlopen", side_effect=response):
        status = LivePlayerFeatureCollector(sportsdataio_api_key="test", now=datetime(2026,9,27,tzinfo=UTC)).provider_status()
    assert status["nfl"]["error"] == "HTTP_403"
    assert status["nfl"]["endpoint"].endswith("PlayerGameProjectionStatsByWeek/2026/4")
    assert status["mlb"]["rows"] == 0 and not status["mlb"]["ok"]
