import argparse
import time
from decimal import Decimal

from .catalog import FEATURED_MARKETS, MARKET_FAMILIES, SPORTS, expand_alternates
from .config import Settings
from .domain.models import Decision
from .domain.recommendation import recommend_price
from .domain.risk import RiskPolicy
from .domain.shopping import build_price_cards
from .persistence.factory import ledger as Ledger
from .providers.the_odds_api import TheOddsApiProvider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jabazi", description="Jabazi multisport price scanner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="List configured sports and market families")
    scan = sub.add_parser("scan", help="Run a real featured-market scan")
    scan.add_argument("--sport", required=True, help="Provider sport key, e.g. baseball_mlb")
    scan.add_argument("--markets", default="h2h,spreads,totals")
    scan.add_argument("--database", default="jabazi-local.db")
    scan.add_argument("--top", type=int, default=20)
    events = sub.add_parser("events", help="List upcoming event IDs without consuming odds quota")
    events.add_argument("--sport", required=True)
    deep = sub.add_parser(
        "scan-event", help="Scan props, periods, or alternate lines for one event"
    )
    deep.add_argument("--sport", required=True)
    deep.add_argument("--event-id", required=True)
    deep.add_argument("--markets", required=True, help="Comma-separated provider market keys")
    deep.add_argument("--database", default="jabazi-local.db")
    deep.add_argument("--top", type=int, default=30)
    automatic = sub.add_parser("auto-scan", help="Run a credit-aware automatic scan pass")
    automatic.add_argument("--mode", choices=("quick", "full"), default="quick")
    automatic.add_argument("--database", default="jabazi-local.db")
    automatic.add_argument("--credit-reserve", type=int, default=50)
    automatic.add_argument("--max-credits", type=int, default=30)
    daemon = sub.add_parser("daemon", help="Run the automatic scanner continuously")
    daemon.add_argument("--mode", choices=("quick", "full"), default="quick")
    daemon.add_argument("--interval", type=int, default=7200, help="Seconds between passes")
    daemon.add_argument("--database", default=None)
    daemon.add_argument("--credit-reserve", type=int, default=50)
    daemon.add_argument("--max-credits", type=int, default=15)
    backfill = sub.add_parser("backfill-mlb", help="Download canonical MLB history")
    backfill.add_argument("--seasons", required=True, help="Comma-separated seasons")
    backfill.add_argument("--output", default="data/mlb_games.json")
    train = sub.add_parser("train-mlb", help="Train and validate the MLB moneyline model")
    train.add_argument("--input", default="data/mlb_games.json")
    train.add_argument("--output", default="models/mlb_moneyline.json")
    history = sub.add_parser("history", help="Download real completed result history")
    history.add_argument("--sport", choices=("mlb", "nfl", "cfb"), required=True)
    history.add_argument("--seasons", default="2021,2022,2023,2024,2025,2026")
    history.add_argument("--as-of", required=True, help="Exclude games on/after this UTC date")
    history.add_argument("--output", required=True)
    history.add_argument("--csv", default=None, help="Optional local nflverse schedule CSV")
    baseline = sub.add_parser(
        "train-baseline", help="Train a shadow-only league moneyline baseline"
    )
    baseline.add_argument("--sport", choices=("mlb", "nfl", "cfb"), required=True)
    baseline.add_argument("--input", required=True)
    baseline.add_argument("--output", required=True)
    baseline.add_argument("--holdout", type=int, default=2025)
    return parser


def _catalog() -> int:
    print("Sports")
    for sport, keys in SPORTS.items():
        print(f"  {sport}: {', '.join(keys)}")
    print("\nMarket families")
    for family, markets in MARKET_FAMILIES.items():
        print(f"  {family}: {', '.join(expand_alternates(markets))}")
    return 0


def _show_batch(batch, database: str, top: int, settings: Settings) -> int:
    ledger = Ledger(database)
    digest = ledger.archive_batch(batch)
    policy = RiskPolicy(
        bankroll=settings.bankroll,
        unit_size=settings.unit_size,
        daily_exposure_limit=settings.daily_exposure_limit,
        minimum_edge=settings.minimum_edge,
    )
    cards = build_price_cards(batch.quotes, policy.stale_after_seconds)
    from .models.registry import load_models

    models, model_errors = load_models()
    actions = []
    for card in cards:
        model = models.get(card.sport)
        estimate = model.estimate(card) if model else None
        actions.append(
            recommend_price(
                card,
                policy,
                current_exposure=ledger.open_exposure(),
                model_probability=estimate.probability if estimate else None,
                uncertainty=estimate.uncertainty if estimate else Decimal(0),
                model_validated=False,
                jurisdiction=settings.jurisdiction,
            )
        )
    if model_errors:
        print("model_errors:", ", ".join(model_errors))
    print(
        f"Archived {len(batch.quotes)} quotes from {len(set(q.event_id for q in batch.quotes))} events"
    )
    print(
        f"Snapshot {digest[:12]} | quota used={batch.requests_used} remaining={batch.requests_remaining}"
    )
    for action in actions[:top]:
        card = action.price
        line = "" if card.line is None else f" {card.line}"
        prices = ", ".join(f"{book} {price}" for book, price in sorted(card.book_prices.items()))
        print(
            f"{action.decision.value:7} | {card.event} | {card.market} | "
            f"{card.participant or ''} {card.selection}{line} | {prices} | "
            f"best {card.best_book} {card.best_decimal} | market-EV {card.market_relative_ev:.2%}"
        )
    counts = {decision.value: sum(a.decision == decision for a in actions) for decision in Decision}
    print("Decisions:", counts)
    ledger.close()
    return 0


def _scan(args: argparse.Namespace) -> int:
    settings = Settings.from_environment()
    markets = tuple(item.strip() for item in args.markets.split(",") if item.strip())
    unsupported = set(markets) - set(FEATURED_MARKETS)
    if unsupported:
        raise SystemExit(
            "Featured scan accepts h2h, spreads, totals, or outrights. "
            "Props and alternates require event-scoped discovery."
        )
    provider = TheOddsApiProvider(args.sport, markets=markets, api_key=settings.api_key)
    batch = provider.fetch()
    return _show_batch(batch, args.database, args.top, settings)


def _events(args: argparse.Namespace) -> int:
    settings = Settings.from_environment()
    provider = TheOddsApiProvider(args.sport, markets=("h2h",), api_key=settings.api_key)
    for event in provider.list_events():
        print(
            f"{event['id']} | {event.get('commence_time')} | "
            f"{event.get('away_team')} @ {event.get('home_team')}"
        )
    return 0


def _scan_event(args: argparse.Namespace) -> int:
    settings = Settings.from_environment()
    markets = tuple(item.strip() for item in args.markets.split(",") if item.strip())
    provider = TheOddsApiProvider(args.sport, markets=("h2h",), api_key=settings.api_key)
    available = provider.list_event_markets(args.event_id)
    union = set().union(*available.values()) if available else set()
    missing = set(markets) - union
    if missing:
        raise SystemExit(f"Markets not recently seen for this event: {', '.join(sorted(missing))}")
    return _show_batch(
        provider.fetch_event(args.event_id, markets), args.database, args.top, settings
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "history":
        import os
        from .config import load_dotenv
        from .providers.history import backfill_mlb, backfill_nfl, backfill_cfb

        load_dotenv()
        seasons = [int(s) for s in args.seasons.split(",")]
        if args.sport == "mlb":
            count = backfill_mlb(seasons, args.output, args.as_of)
        elif args.sport == "nfl":
            count = backfill_nfl(seasons, args.output, args.as_of, args.csv)
        else:
            count = backfill_cfb(
                seasons, args.output, args.as_of, os.getenv("JABBAZI_CFBD_API_KEY", "")
            )
        print(f"completed_games={count} sport={args.sport}")
        return 0
    if args.command == "train-baseline":
        import json
        from .models.team_elo import train

        result = train(args.input, args.output, args.sport, args.holdout)
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "sport",
                        "status",
                        "history_games",
                        "holdout",
                        "paired_market_diagnostic",
                    )
                },
                indent=2,
            )
        )
        return 0
    if args.command == "catalog":
        return _catalog()
    if args.command == "events":
        return _events(args)
    if args.command == "scan-event":
        return _scan_event(args)
    if args.command == "auto-scan":
        from .automation import AutomaticScanner

        settings = Settings.from_environment()
        result = AutomaticScanner(
            settings, args.database, args.credit_reserve, args.max_credits
        ).run(args.mode)
        print(
            f"feeds={result.feeds_scanned} quotes={result.quotes_archived} "
            f"new_actions={len(result.new_actions)} arbitrages={len(result.arbitrages)} "
            f"credits_remaining={result.credits_remaining}"
        )
        for opportunity in result.arbitrages:
            print(
                f"ARBITRAGE {opportunity.event} {opportunity.market} "
                f"profit={opportunity.guaranteed_profit:.2f} roi={opportunity.roi:.2%}"
            )
            for leg in opportunity.legs:
                print(f"  {leg.sportsbook}: {leg.selection} {leg.decimal_odds} stake={leg.stake}")
        if result.errors:
            print("errors:", ", ".join(result.errors))
        return 0
    if args.command == "backfill-mlb":
        from .providers.sportsdataio import SportsDataIOMlbProvider

        settings = Settings.from_environment()
        seasons = [int(value.strip()) for value in args.seasons.split(",") if value.strip()]
        count = SportsDataIOMlbProvider(settings.sportsdataio_api_key).backfill(
            seasons, args.output
        )
        print(f"saved_games={count} seasons={','.join(map(str, sorted(set(seasons))))}")
        return 0
    if args.command == "train-mlb":
        from .models.mlb_elo import train_mlb_elo

        artifact = train_mlb_elo(args.input, args.output)
        print(
            f"validated_games={artifact.games_validated} brier={artifact.brier:.6f} "
            f"market_brier={artifact.market_brier} approved={artifact.approved_for_betting}"
        )
        if artifact.validation_reasons:
            print("validation_blocks:", "; ".join(artifact.validation_reasons))
        return 0
    if args.command == "daemon":
        from datetime import datetime, timezone
        from pathlib import Path
        from .automation import AutomaticScanner

        settings = Settings.from_environment()
        database = args.database or settings.database_path
        if args.interval < 300:
            raise SystemExit("Daemon interval must be at least 300 seconds")
        while True:
            try:
                result = AutomaticScanner(
                    settings, database, args.credit_reserve, args.max_credits
                ).run(args.mode)
                print(
                    f"{datetime.now(timezone.utc).isoformat()} feeds={result.feeds_scanned} "
                    f"quotes={result.quotes_archived} new={len(result.new_actions)} "
                    f"arbs={len(result.arbitrages)} remaining={result.credits_remaining}",
                    flush=True,
                )
                import os

                if (
                    not result.errors
                    and os.getenv("JABBAZI_DISCORD_REVIEW_ENABLED", "false").lower() == "true"
                ):
                    from .discord_review import validate_webhook, deliver, render

                    webhook = os.environ.get("JABBAZI_DISCORD_REVIEW_WEBHOOK", "")
                    channel = os.environ.get("JABBAZI_DISCORD_REVIEW_CHANNEL_ID", "")
                    validate_webhook(webhook, channel)
                    candidates = [a for a in result.actions if render(a) is not None][:5]
                    for action in candidates:
                        deliver(action, webhook, str(Path(database).with_suffix(".delivery.db")))
                if not result.errors:
                    Path("/data/healthy" if Path("/data").exists() else "jabazi.healthy").touch()
            except Exception as exc:
                print(
                    f"{datetime.now(timezone.utc).isoformat()} scan_failed={type(exc).__name__}",
                    flush=True,
                )
            time.sleep(args.interval)
    return _scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
