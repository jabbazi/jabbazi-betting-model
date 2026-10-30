"""Read-only/synthetic verification for the date-scoped daily cheat-sheet contract."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from PIL import Image

from jabazi.discord_daily import freeze_daily_moneyline, daily_moneyline, render_game_card, render_text
from jabazi.persistence.store import Store


def main():
    store = Store("sqlite:///:memory:", initialize=True)
    try:
        now = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)  # 9:00 AM CDT
        record = {
            "id": "synthetic-daily-verification",
            "payload": {
                "completed_at": "2026-10-12T13:58:00+00:00",
                "healthy": True,
                "truncated": False,
                "slate_events": [
                    {"sport":"americanfootball_nfl","event_id":"g1","event":"Away One @ Home One","starts_at_utc":"2026-10-12T18:00:00+00:00"},
                    {"sport":"basketball_nba","event_id":"g2","event":"Away Two @ Home Two","starts_at_utc":"2026-10-13T00:00:00+00:00"},
                    {"sport":"basketball_nba","event_id":"future","event":"Tomorrow @ Later","starts_at_utc":"2026-10-13T18:00:00+00:00"},
                    {"sport":"basketball_nba","event_id":"g2","event":"Away Two @ Home Two","starts_at_utc":"2026-10-13T00:00:00+00:00"},
                ],
                "rows": [
                    {"sport":"americanfootball_nfl","event_id":"g1","event":"Away One @ Home One","market":"h2h","selection":"Home One","book":"FanDuel","decimal_odds":"1.80","price_time_utc":"2026-10-12T13:57:30+00:00","starts_at_utc":"2026-10-12T18:00:00+00:00","market_no_vig_probability":"0.56","research_probability":"0.61","model_version":"verify-nfl","uncertainty":"0.04","probability_edge":"0.05","status":"WATCH","reason":"Synthetic model edge for verification only.","price_stale":False,"executable":True,"book_count":4,"data_health":"HEALTHY","model_can_influence_cash":False},
                    {"sport":"americanfootball_nfl","event_id":"g1","event":"Away One @ Home One","market":"h2h","selection":"Away One","book":"DraftKings","decimal_odds":"2.10","price_time_utc":"2026-10-12T13:57:30+00:00","starts_at_utc":"2026-10-12T18:00:00+00:00","market_no_vig_probability":"0.44","research_probability":"0.39","model_version":"verify-nfl","uncertainty":"0.04","probability_edge":"-0.05","status":"PASS","reason":"Synthetic opposite side.","price_stale":False,"executable":True,"book_count":4,"data_health":"HEALTHY","model_can_influence_cash":False},
                    {"sport":"basketball_nba","event_id":"g2","event":"Away Two @ Home Two","market":"h2h","selection":"Home Two","book":"Caesars","decimal_odds":"1.72","price_time_utc":"2026-10-12T13:57:30+00:00","starts_at_utc":"2026-10-13T00:00:00+00:00","market_no_vig_probability":"0.59","research_probability":None,"model_version":None,"uncertainty":None,"probability_edge":None,"status":"RESEARCH / NOT AN OFFICIAL PICK","reason":"market only","price_stale":False,"executable":True,"book_count":5,"data_health":"HEALTHY","model_can_influence_cash":False},
                    {"sport":"basketball_nba","event_id":"g2","event":"Away Two @ Home Two","market":"h2h","selection":"Away Two","book":"BetMGM","decimal_odds":"2.30","price_time_utc":"2026-10-12T13:57:30+00:00","starts_at_utc":"2026-10-13T00:00:00+00:00","market_no_vig_probability":"0.41","research_probability":None,"model_version":None,"uncertainty":None,"probability_edge":None,"status":"RESEARCH / NOT AN OFFICIAL PICK","reason":"market only","price_stale":False,"executable":True,"book_count":5,"data_health":"HEALTHY","model_can_influence_cash":False},
                    {"sport":"basketball_nba","event_id":"future","event":"Tomorrow @ Later","market":"h2h","selection":"Later","book":"FanDuel","decimal_odds":"1.50","price_time_utc":"2026-10-12T13:57:30+00:00","starts_at_utc":"2026-10-13T18:00:00+00:00","market_no_vig_probability":"0.66","research_probability":"0.70","model_version":"verify-future","uncertainty":"0.03","probability_edge":"0.04","status":"WATCH","reason":"must not leak","price_stale":False,"executable":True,"book_count":4,"data_health":"HEALTHY","model_can_influence_cash":False},
                ],
            },
        }
        _, created = freeze_daily_moneyline(store, record, now=now)
        frozen = daily_moneyline(store, now=now)
        if not created or frozen is None:
            raise RuntimeError("freeze/readback failed")
        payload = frozen["payload"]
        if payload["eligible_game_count"] != 2 or payload["row_count"] != 2:
            raise RuntimeError("same-day slate count failed")
        if any(row["event_id"] == "future" for row in payload["rows"]):
            raise RuntimeError("future event leaked")
        if {row["projected_winner"] for row in payload["rows"]} != {"Home One", "Home Two"}:
            raise RuntimeError("winner projection failed")
        if next(row for row in payload["rows"] if row["event_id"] == "g2")["model_probability"] is not None:
            raise RuntimeError("market fallback fabricated model probability")
        sizes = []
        for row in payload["rows"]:
            raw = render_game_card(frozen, row)
            image = Image.open(io.BytesIO(raw))
            if image.format != "PNG" or image.size != (1200, 900):
                raise RuntimeError("game card render failed")
            sizes.append(len(raw))
        text = render_text(frozen)
        if "Tomorrow" in text or "2 eligible games" not in text:
            raise RuntimeError("daily index filter failed")
        print("JABBAZI_DAILY_CHEATSHEET_VERIFICATION " + json.dumps({
            "status":"VERIFIED",
            "eligible_games":payload["eligible_game_count"],
            "game_cards":payload["row_count"],
            "future_events":0,
            "model_winner":"Home One",
            "market_fallback_winner":"Home Two",
            "market_fallback_model_probability":None,
            "png_sizes":sizes,
        }, separators=(",", ":")), flush=True)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
