"""Prospective score-model evaluation. Never settles tickets or promotes a model.

Fixed sampling policy: first fresh pregame home-side (or Over) forecast per
schedule game, model version and exact market family. Alternate ladders and
repeat scans therefore contribute at most one observation per bucket/game.
"""

from datetime import UTC, datetime
import math

from sqlalchemy import select

from jabazi.models.team_elo import SPORTS, metrics, timestamp, validate_history
from jabazi.persistence.store import digest, events
from jabazi.reliability.layer import market_bucket

POLICY = "first-fresh-home-or-over-per-game-bucket-v1"


def freeze_candidate(store, card, estimate, reliability, *, now=None):
    now = now or datetime.now(UTC)
    f = estimate.feature_snapshot
    selection = f.get("canonical_selection", card.selection)
    participant = f.get("canonical_participant", card.participant)
    home = f.get("home_team")
    if market_bucket(card.market) == "unsupported":
        return False
    if card.market in {"h2h", "spreads", "alternate_spreads"}:
        if selection != home:
            return False
    elif selection.lower() != "over" or (
        "team_totals" in card.market and participant != home
    ):
        return False
    if getattr(card, "in_play", False) or now.tzinfo is None or card.starts_at <= now:
        return False
    if not all(
        0 <= (now - t).total_seconds() <= 120
        for t in (card.observed_at, card.source_timestamp)
    ):
        return False
    required = (
        "schedule_game_id",
        "feature_schema_version",
        "dataset_hash",
        "code_commit",
        "state_refreshed_at",
        "home_team",
        "away_team",
    )
    if any(not f.get(k) for k in required) or timestamp(f["state_refreshed_at"]) > now:
        return False
    p = float(estimate.probability)
    market_p = float(card.consensus_probability)
    if not (
        math.isfinite(p) and 0 < p < 1 and math.isfinite(market_p) and 0 < market_p < 1
    ):
        return False
    # Non-moneyline pushes need three-outcome evaluation, not binary scoring.
    if card.market != "h2h" and f.get("push_probability", 0) != 0:
        return False
    key = digest(
        [
            POLICY,
            card.sport,
            str(f["schedule_game_id"]),
            estimate.model_version,
            card.market,
        ]
    )
    payload = {
        "policy": POLICY,
        "sport": card.sport,
        "event_id": card.event_id,
        "schedule_game_id": str(f["schedule_game_id"]),
        "model_version": estimate.model_version,
        "market": card.market,
        "bucket": market_bucket(card.market),
        "selection": selection,
        "participant": participant,
        "line": None if card.line is None else str(card.line),
        "home_team": home,
        "away_team": f["away_team"],
        "starts_at": card.starts_at.isoformat(),
        "predicted_at": now.isoformat(),
        "probability": p,
        "market_probability": market_p,
        "feature_schema_version": f["feature_schema_version"],
        "dataset_hash": f["dataset_hash"],
        "code_commit": f["code_commit"],
        "feature_snapshot": f,
        "odds_snapshot": {
            "ids": card.quote_ids,
            "book": card.best_book,
            "decimal": str(card.best_decimal),
            "source_at": card.source_timestamp.isoformat(),
        },
        "reliability": reliability,
        "approved_for_betting": False,
        "settlement_basis": "full_game_score_research_only_not_ticket_settlement",
    }
    with store.transaction() as conn:
        if conn.execute(select(events.c.id).where(events.c.id == key)).first():
            return False
        return store._append(conn, "prospective_forecast", card.event_id, payload, key)


def archive_results(store, sport, games, *, observed_at, source_checksum):
    """Keep first result and subsequent corrections as distinct immutable receipts."""
    if observed_at.tzinfo is None or not source_checksum:
        raise ValueError("Result provenance required")
    short = next(k for k, v in SPORTS.items() if v == sport)
    games = validate_history({"sport": sport, "games": games}, short)
    count = 0
    for game in games:
        if timestamp(game["starts_at"]) >= observed_at:
            continue
        # Stable result identity avoids six-hourly copies of unchanged scores.
        result = {
            k: game[k]
            for k in (
                "game_id",
                "starts_at",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
                "season",
            )
        }
        key = digest(["prospective_result", sport, result])
        payload = result | {
            "sport": sport,
            "observed_at": observed_at.isoformat(),
            "source_checksum": source_checksum,
        }
        with store.transaction() as conn:
            if conn.execute(select(events.c.id).where(events.c.id == key)).first():
                continue
            count += store._append(
                conn,
                "prospective_result",
                sport + ":" + str(game["game_id"]),
                payload,
                key,
            )
    return count


def outcome(forecast, result):
    """Strict schedule identity; ambiguous reschedules remain ungraded."""
    if forecast["sport"] != result["sport"] or str(forecast["schedule_game_id"]) != str(
        result["game_id"]
    ):
        raise ValueError("Result identity mismatch")
    if any(forecast[k] != result[k] for k in ("home_team", "away_team")):
        raise ValueError("Result team orientation mismatch")
    if (
        abs(
            (
                timestamp(forecast["starts_at"]) - timestamp(result["starts_at"])
            ).total_seconds()
        )
        > 60
    ):
        raise ValueError("Result kickoff mismatch")
    if timestamp(forecast["predicted_at"]) >= timestamp(result["starts_at"]):
        raise ValueError("Not a pregame forecast")
    h, a = result["home_score"], result["away_score"]
    if type(h) is not int or type(a) is not int or min(h, a) < 0:
        raise ValueError("Invalid final scores")
    market = forecast["market"]
    if market == "h2h":
        value = h - a
    elif market in {"spreads", "alternate_spreads"}:
        value = h - a + float(forecast["line"])
    elif market in {"totals", "alternate_totals"}:
        value = h + a - float(forecast["line"])
    elif market in {"team_totals", "alternate_team_totals"}:
        value = h - float(forecast["line"])
    else:
        raise ValueError("Unsupported research market")
    if not math.isfinite(value):
        raise ValueError("Invalid threshold")
    return "PUSH" if value == 0 else "WIN" if value > 0 else "LOSS"


def records(store, kind):
    # Streaming DB cursor, no hidden 1,000-row truncation in evidence reports.
    with store.engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(
            select(events.c.id, events.c.payload)
            .where(events.c.kind == kind)
            .order_by(events.c.occurred_at, events.c.id)
        )
        yield from result.mappings()


def calibration_table(pairs):
    rows = []
    for lower in range(0, 100, 5):
        values = [(p, y) for p, y in pairs if lower / 100 <= p < (lower + 5) / 100]
        n = len(values)
        if not n:
            continue
        hit = sum(y for _, y in values) / n
        z = 1.959963984540054
        denominator = 1 + z * z / n
        center = (hit + z * z / (2 * n)) / denominator
        radius = z * math.sqrt(hit * (1 - hit) / n + z * z / (4 * n * n)) / denominator
        rows.append(
            {
                "range": f"{lower}-{lower + 5}",
                "n": n,
                "mean_probability": sum(p for p, _ in values) / n,
                "observed_hit_rate": hit,
                "wilson_95_low": max(0, center - radius),
                "wilson_95_high": min(1, center + radius),
            }
        )
    return rows


def validation_report(store):
    """Recompute against latest result receipts; historical receipts never change."""
    results = {}
    for row in records(store, "prospective_result"):
        r = row["payload"]
        results[(r["sport"], str(r["game_id"]))] = r
    groups = {}
    for row in records(store, "prospective_forecast"):
        f = row["payload"]
        key = (f["sport"], f["model_version"], f["bucket"])
        g = groups.setdefault(
            key,
            {
                "frozen": 0,
                "pending": 0,
                "pushes": 0,
                "identity_failures": 0,
                "pairs": [],
                "market_pairs": [],
                "input_verified": 0,
            },
        )
        g["frozen"] += 1
        r = results.get((f["sport"], str(f["schedule_game_id"])))
        if r is None:
            g["pending"] += 1
            continue
        try:
            label = outcome(f, r)
        except (ValueError, KeyError, TypeError):
            g["identity_failures"] += 1
            continue
        if label == "PUSH":
            g["pushes"] += 1
            continue
        y = int(label == "WIN")
        g["pairs"].append((f["probability"], y))
        g["market_pairs"].append((f["market_probability"], y))
        g["input_verified"] += (
            f["feature_snapshot"].get("production_inputs_verified") is True
        )
    buckets = []
    for (sport, version, bucket), g in sorted(groups.items()):
        calibration = calibration_table(g["pairs"])
        model = metrics(g.pop("pairs"))
        market = metrics(g.pop("market_pairs"))
        record = dict(
            sport=sport,
            model_version=version,
            bucket=bucket,
            **g,
            model=model,
            market=market,
            calibration=calibration,
        )
        from jabazi.reliability.layer import prospective_stage
        stage, approved, reason = prospective_stage(record)
        buckets.append(
            record
            | {
                "stage": stage,
                "approved_for_betting": approved,
                "reason": reason,
            }
        )
    return {
        "policy": POLICY,
        "generated_at": datetime.now(UTC).isoformat(),
        "buckets": buckets,
        "notes": [
            "One first-seen canonical outcome per game/version/market family",
            "Pushes excluded from conditional binary metrics",
            "Score labels are research results, not sportsbook ticket settlements",
            "No automatic promotion; input verification and calibration remain required",
        ],
    }
