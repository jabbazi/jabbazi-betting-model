import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from jabazi.models.team_elo import train, replay, validate_history, TeamEloModel
from jabazi.providers.history import mlb_rows, cfb_rows, nfl_rows
from jabazi.domain.models import Decision
from jabazi.domain.recommendation import ActionCard
from jabazi.domain.shopping import PriceCard
from jabazi.discord_review import render, deliver, validate_webhook


def history(sport="americanfootball_nfl"):
    games = []
    for season in (2023, 2024, 2025):
        for index in range(10):
            start = datetime(season, 9, 1, tzinfo=UTC) + timedelta(days=index)
            games.append(
                {
                    "game_id": f"{season}-{index}",
                    "season": season,
                    "starts_at": start.isoformat(),
                    "home_team": "A",
                    "away_team": "B",
                    "home_score": 21 if index % 3 else 7,
                    "away_score": 14,
                    "neutral_site": False,
                    "home_moneyline": -120 if index % 2 else None,
                    "away_moneyline": 110,
                    "odds_observed_at": (start - timedelta(hours=1)).isoformat(),
                }
            )
    return {"sport": sport, "provider": "SYNTHETIC_TEST_ONLY", "games": games}


def card(now=None):
    now = now or datetime.now(UTC)
    return PriceCard(
        "americanfootball_nfl",
        "e",
        "B @ A",
        "h2h",
        None,
        "A",
        None,
        {"DraftKings": Decimal("2.1")},
        "DraftKings",
        Decimal("2.1"),
        Decimal(".5"),
        Decimal(".05"),
        Decimal(0),
        False,
        False,
        ("q",),
        now,
        now,
        now + timedelta(hours=2),
    )


class BaselineTests(unittest.TestCase):
    def build(self, payload, sport="nfl"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name) / "history.json"
        out = Path(directory.name) / "model.json"
        source.write_text(json.dumps(payload))
        return train(source, out, sport, 2025), out

    def test_every_league_has_independent_shadow_artifact(self):
        for short, sport in [
            ("mlb", "baseball_mlb"),
            ("nfl", "americanfootball_nfl"),
            ("cfb", "americanfootball_ncaaf"),
        ]:
            with self.subTest(sport=short):
                model, _ = self.build(history(sport), short)
                self.assertEqual(model["sport"], sport)
                self.assertFalse(model["approved_for_betting"])
                self.assertEqual(model["holdout"]["n"], 10)

    def test_final_season_cannot_select_hyperparameters(self):
        first = history()
        second = json.loads(json.dumps(first))
        for g in second["games"]:
            if g["season"] == 2025:
                g["home_score"], g["away_score"] = g["away_score"], g["home_score"]
        a, _ = self.build(first)
        b, _ = self.build(second)
        self.assertEqual(a["parameters"], b["parameters"])
        self.assertEqual(a["tuning_log_loss"], b["tuning_log_loss"])

    def test_market_comparison_is_paired_and_timestamp_checked(self):
        data = history()
        data["games"][-1]["odds_observed_at"] = "2027-01-01T00:00:00Z"
        model, _ = self.build(data)
        comparison = model["paired_market_diagnostic"]
        self.assertEqual(comparison["model"]["n"], 5)
        self.assertEqual(comparison["model"]["n"], comparison["market"]["n"])
        self.assertEqual(model["timestamp_verified_market_comparison"]["model"]["n"], 4)

    def test_duplicate_ids_rejected(self):
        data = history()
        data["games"].append(data["games"][0])
        with self.assertRaises(ValueError):
            validate_history(data, "nfl")

    def test_same_day_games_cannot_use_each_others_results(self):
        games = history()["games"][:2]
        games[1]["starts_at"] = games[0]["starts_at"]
        _, predictions = replay(games, 24, 50, 0.75)
        self.assertEqual(predictions[0][1], predictions[1][1])

    def test_ties_are_not_counted_as_losses(self):
        data = history()
        data["games"][-1]["home_score"] = 14
        artifact, _ = self.build(data)
        self.assertEqual(artifact["holdout"]["n"], 9)
        self.assertEqual(artifact["holdout_ties_excluded"], 1)

    def test_previous_evening_results_do_not_leak_into_after_midnight_games(self):
        games = history()["games"][:2]
        games[0]["starts_at"] = "2025-09-01T23:30:00+00:00"
        games[1]["starts_at"] = "2025-09-02T00:30:00+00:00"
        games[0]["season"] = games[1]["season"] = 2025
        _, predictions = replay(games, 24, 50, 0.75)
        self.assertEqual(predictions[0][1], predictions[1][1])

    def test_scan_builds_actions_before_closing_ledger(self):
        from types import SimpleNamespace
        from jabazi.automation import AutomaticScanner
        from jabazi.config import Settings

        state = {"closed": False}

        def exposure():
            if state["closed"]:
                raise RuntimeError("closed ledger")
            return Decimal(0)

        with (
            patch("jabazi.automation.Ledger") as ledger,
            patch("jabazi.automation.TheOddsApiProvider") as provider,
            patch("jabazi.automation.build_price_cards", return_value=[card()]),
            patch("jabazi.automation.find_arbitrage", return_value=[]),
            patch("jabazi.automation.load_models", return_value=({}, [])),
            patch.object(
                AutomaticScanner,
                "_active_supported",
                return_value=[{"key": "americanfootball_nfl"}],
            ),
        ):
            ledger.return_value.open_exposure.side_effect = exposure
            ledger.return_value.close.side_effect = lambda: state.update(closed=True)
            provider.return_value.fetch.return_value = SimpleNamespace(
                quotes=(), requests_remaining=100, fetched_at=datetime.now(UTC)
            )
            result = AutomaticScanner(Settings.from_environment()).run()
            self.assertTrue(state["closed"])
            self.assertEqual(len(result.actions), 1)
            self.assertEqual(result.errors, ())

    def test_football_requires_venue_context_and_cannot_promote_flag(self):
        artifact, path = self.build(history())
        artifact["approved_for_betting"] = True
        artifact["history_through_date"] = datetime.now(UTC).date().isoformat()
        path.write_text(json.dumps(artifact))
        now = datetime.fromisoformat(artifact["ratings_effective_at"]) + timedelta(hours=1)
        model = TeamEloModel(path)
        self.assertIsNone(model.estimate(card(now)))
        model = TeamEloModel(path, events={"e": {"neutral_site": False}})
        estimate = model.estimate(card(now))
        self.assertIsNotNone(estimate)
        self.assertFalse(estimate.approved_for_betting)
        self.assertIsNone(model.estimate(replace(card(now), sport="baseball_mlb")))
        self.assertIsNone(model.estimate(replace(card(now), event="Unknown @ A")))
        self.assertIsNone(model.estimate(card(now + timedelta(days=6))))


class AdapterTests(unittest.TestCase):
    def test_postponed_and_suspended_mlb_records_are_excluded(self):
        game = {
            "gamePk": 1,
            "season": "2025",
            "gameType": "R",
            "gameDate": "2025-06-01T18:00:00Z",
            "status": {"abstractGameState": "Final", "codedGameState": "D"},
            "teams": {
                "home": {"team": {"name": "A"}, "score": 3},
                "away": {"team": {"name": "B"}, "score": 2},
            },
        }
        payload = {"dates": [{"games": [game]}]}
        self.assertEqual(mlb_rows(payload), [])
        game["status"]["codedGameState"] = "F"
        self.assertEqual(len(mlb_rows(payload)), 1)
        game["resumeDate"] = "2025-07-01T18:00:00Z"
        self.assertEqual(mlb_rows(payload), [])

    def test_cfb_unfinished_games_are_excluded(self):
        game = {
            "id": 1,
            "season": 2025,
            "startDate": "2025-09-01T18:00:00Z",
            "completed": False,
            "homeTeam": "A",
            "awayTeam": "B",
            "homePoints": 10,
            "awayPoints": 7,
            "neutralSite": True,
        }
        self.assertEqual(cfb_rows([game]), [])
        game["completed"] = True
        self.assertTrue(cfb_rows([game])[0]["neutral_site"])

    def test_nfl_team_identity_and_timezone(self):
        text = "game_id,season,game_type,gameday,gametime,home_team,away_team,home_score,away_score,location\n1,2025,REG,2025-09-07,13:00,LA,NO,21,14,Neutral\n"
        row = nfl_rows(text, [2025])[0]
        self.assertEqual(row["home_team"], "Los Angeles Rams")
        self.assertEqual(row["starts_at"], "2025-09-07T17:00:00+00:00")
        self.assertTrue(row["neutral_site"])


class DiscordTests(unittest.TestCase):
    def action(self):
        return ActionCard(
            card(), Decision.WATCH, Decimal(".55"), None, Decimal(0), None, "Unvalidated"
        )

    def test_card_cannot_look_like_a_paid_pick(self):
        action = self.action()
        payload = render(action)
        self.assertIn("NOT A PICK", payload["embeds"][0]["title"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertIsNone(render(action, datetime.now(UTC) + timedelta(minutes=3)))

    @patch("jabazi.discord_review.webhook_request", return_value={"id": "message"})
    def test_delivery_is_idempotent(self, send):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "delivery.db")
            action = self.action()
            self.assertEqual(
                deliver(action, "https://discord.com/api/webhooks/1/test", db), "delivered"
            )
            self.assertEqual(
                deliver(action, "https://discord.com/api/webhooks/1/test", db),
                "already_delivered_or_requires_review",
            )
            send.assert_called_once()

    @patch("jabazi.discord_review.webhook_request", side_effect=TimeoutError)
    def test_ambiguous_delivery_cannot_resend_silently(self, send):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "delivery.db")
            action = self.action()
            with self.assertRaises(RuntimeError):
                deliver(action, "https://discord.com/api/webhooks/1/test", db)
            self.assertEqual(
                deliver(action, "https://discord.com/api/webhooks/1/test", db),
                "already_delivered_or_requires_review",
            )
            send.assert_called_once()

    @patch("jabazi.discord_review.webhook_request", return_value={"channel_id": "123"})
    def test_wrong_destination_is_rejected(self, request):
        with self.assertRaises(ValueError):
            validate_webhook("https://discord.com/api/webhooks/1/test", "456")
        with self.assertRaises(ValueError):
            validate_webhook("https://example.com/api/webhooks/1/test", "123")

    def test_private_roles_do_not_grant_public_visibility(self):
        path = Path(__file__).parents[1] / "tools" / "discord_setup.py"
        spec = importlib.util.spec_from_file_location("setup", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        values = module.overwrites("guild", "vip", "analyst", "bot", "owner")
        self.assertTrue(int(values[0]["deny"]) & module.VIEW)
        self.assertNotIn("vip", [v["id"] for v in values])
        values = module.overwrites("guild", "vip", "analyst", "bot", "vip")
        role = next(v for v in values if v["id"] == "vip")
        self.assertTrue(int(role["allow"]) & module.VIEW)
        self.assertTrue(int(role["deny"]) & module.SEND)


if __name__ == "__main__":
    unittest.main()
