import httpx
import pytest

from jabazi.providers.balldontlie import BallDontLieError, BallDontLieProvider


def test_pagination_consumes_all_rows_and_cursor():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if "cursor=second" in str(request.url):
            return httpx.Response(200, json={"data": [{"id": 2}], "meta": {"next_cursor": None}})
        return httpx.Response(200, json={"data": [{"id": 1}], "meta": {"next_cursor": "second"}})
    provider = BallDontLieProvider("test", transport=httpx.MockTransport(handler), interval=0)
    try:
        result = provider.fetch_all_pages("nba", "props", [("game_id", 123)])
        assert result == {"data": [{"id": 1}, {"id": 2}], "pages": 2, "complete": True}
        assert len(seen) == 2
        assert all("game_id=123" in url for url in seen)
    finally:
        provider.close()


def test_pagination_fails_closed_on_limit():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": 1}], "meta": {"next_cursor": "next"}})
    provider = BallDontLieProvider("test", transport=httpx.MockTransport(handler), interval=0)
    try:
        with pytest.raises(BallDontLieError, match="PAGINATION_LIMIT_REACHED"):
            provider.fetch_all_pages("nfl", "props", max_pages=1)
    finally:
        provider.close()
