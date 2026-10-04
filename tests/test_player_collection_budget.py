"""Unavailable prop feeds must not stall independent game-market research."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jabazi.providers.player_features_live import LivePlayerFeatureCollector, _fetch_bytes


@pytest.mark.parametrize('method,empty', [('_nfl_history',[]),('_nfl_depth_charts',[]),('_nfl_available_games',{})])
def test_nfl_public_feed_failure_is_cached_for_one_scan(method,empty):
    collector=LivePlayerFeatureCollector(now=datetime(2026,9,28,tzinfo=UTC))
    with patch('jabazi.providers.player_features_live._fetch_bytes',side_effect=TimeoutError) as fetch:
        with pytest.raises(TimeoutError):getattr(collector,method)()
        assert getattr(collector,method)()==empty
        assert getattr(collector,method)()==empty
        assert fetch.call_count==1


def test_mlb_identity_and_history_failures_are_cached():
    c=LivePlayerFeatureCollector()
    with patch('jabazi.providers.player_features_live._fetch_json',side_effect=TimeoutError) as fetch:
        with pytest.raises(TimeoutError):c._mlb_person('Test Player')
        assert c._mlb_person('Test Player') is None and fetch.call_count==1
    c._mlb_people['test player']={'id':1}
    with patch.object(c,'_mlb_person',return_value={'id':1}),patch('jabazi.providers.player_features_live._fetch_json',side_effect=TimeoutError) as fetch:
        with pytest.raises(TimeoutError):c._mlb_game_logs('Test Player','hitting')
        assert c._mlb_game_logs('Test Player','hitting')==[] and fetch.call_count==1


def test_one_player_budget_spans_multiple_feed_batches():
    c=LivePlayerFeatureCollector(max_seconds=10); clock=[0.0]
    cards=[SimpleNamespace(participant=str(i),in_play=False,sport='americanfootball_nfl',event_id='test',market='player_anytime_td') for i in range(5)]
    def unavailable(card):clock[0]+=11;return None
    with patch('jabazi.providers.player_features_live.time.monotonic',side_effect=lambda:clock[0]),patch.object(c,'nfl_snapshot',side_effect=unavailable) as snapshot:
        assert c.sync(MagicMock(),cards)==0
        assert c.sync(MagicMock(),cards)==0
        assert snapshot.call_count==1
    assert 'PLAYER_FEATURE_BUDGET_EXHAUSTED' in c.diagnostics


def test_history_reads_are_bounded_before_parsing():
    response=MagicMock();response.__enter__.return_value=response;response.read.return_value=b'x'*17
    with patch('jabazi.providers.player_features_live.urllib.request.urlopen',return_value=response):
        with pytest.raises(ValueError):_fetch_bytes('https://example.test/history',max_bytes=16)
    response.read.assert_called_once_with(17)
