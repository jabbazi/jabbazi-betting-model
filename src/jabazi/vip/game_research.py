"""Event-level VIP research. No model estimates or wagering approvals are invented."""
from __future__ import annotations

from datetime import datetime
import math


def _valid_probability(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 < number < 1 else None
    except (ValueError, TypeError):
        return None


def _usable_model(row):
    return (
        row.get("model_stage") in {"SHADOW_ONLY", "PRODUCTION_APPROVED"}
        and row.get("status") != "QUARANTINED"
        and row.get("data_health") == "HEALTHY"
        and bool(row.get("model_version"))
        and _valid_probability(row.get("model_probability")) is not None
    )


def matchups(rows, *, sport="", limit=100):
    """Aggregate observed market rows into games, keeping data provenance."""
    events = {}
    for row in rows:
        if sport and row.get("sport") != sport.upper():
            continue
        if row.get("lifecycle") != "UPCOMING":
            continue
        event_id = str(row.get("event_id") or "")
        if not event_id:
            continue
        key = (row.get("sport"), event_id)
        game = events.setdefault(key, {
            "sport": row.get("sport"), "event_id": event_id,
            "event": row.get("event"), "starts_at": row.get("starts_at"),
            "markets": set(), "observed_rows": 0, "fresh_rows": 0,
            "model_supported_rows": 0, "price_at": None,
        })
        game["markets"].add(str(row.get("market") or ""))
        game["observed_rows"] += 1
        game["fresh_rows"] += bool(row.get("fresh"))
        game["model_supported_rows"] += bool(
            _usable_model(row)
        )
        at = row.get("price_at")
        if at and (game["price_at"] is None or at > game["price_at"]):
            game["price_at"] = at
    output = []
    for game in events.values():
        game["markets"] = sorted(game["markets"])
        game["state"] = "FRESH" if game["fresh_rows"] else "PRICE CHECK"
        output.append(game)
    return sorted(output, key=lambda g: (g["starts_at"] or "9999", g["sport"] or "", g["event_id"]))[:limit]


def projection_reason(projection, favorite=None, evidence=None):
    """Short explanation derived from the selected evidence, never invented context."""
    selection = projection.get('selection')
    model = _valid_probability(projection.get('model_probability'))
    market = _valid_probability(projection.get('market_no_vig_probability'))
    if not selection:
        return {'reason': 'No fresh model, market, or reviewed-source evidence supports a winner yet.',
                'caution': 'A pick will appear when sufficient evidence is available.', 'observed_at': None}
    if model is not None:
        reason = f'{selection} has the highest available model win estimate for this matchup at {model:.0%}.'
        if market is not None:
            reason += f' The observed market estimates {market:.0%} after removing the margin.'
        caution = ('This model is still being evaluated. ' if projection.get('model_stage') != 'PRODUCTION_APPROVED' else '')
        caution += 'Most likely winner does not automatically mean best betting value; confirmed lineup and injury context is not included here.'
    elif market is not None:
        reason = f'The observed moneyline market favors {selection}, with a {market:.0%} no-vig implied chance.'
        caution = 'This is a market lean, not an independent model forecast or evidence of a profitable price. Confirmed lineup and injury context is not included here.'
    else:
        source = (evidence or {}).get('source', 'The reviewed source')
        reason = f'{source} supports {selection} in the current reviewed research.'
        caution = 'This is a qualitative research lean; a calibrated probability and betting edge are unavailable.'
    return {'reason': reason, 'caution': caution,
            'observed_at': (favorite or {}).get('price_at') or (evidence or {}).get('retrieved_at')}


def matchup_detail(rows, sport, event_id):
    same = [r for r in rows if r.get("sport") == sport and str(r.get("event_id")) == event_id]
    if not same:
        return None
    moneyline = [r for r in same if r.get("market") == "h2h"]
    favorite = None
    candidates = [
        r for r in moneyline
        if _usable_model(r) and r.get("fresh")
    ]
    model_selected = bool(candidates)
    if candidates:
        favorite = max(candidates, key=lambda r: float(r["model_probability"]))
    else:
        candidates = [
            r for r in moneyline
            if _valid_probability(r.get("market_probability")) is not None and r.get("fresh")
        ]
        if candidates:
            favorite = max(candidates, key=lambda r: float(r["market_probability"]))
    projection = {
        "selection": favorite.get("selection") if favorite else None,
        "source": ("INDEPENDENT MODEL" if model_selected else
                   "MARKET CONSENSUS" if favorite else "UNAVAILABLE"),
        "model_probability": _valid_probability(favorite.get("model_probability")) if model_selected else None,
        "market_no_vig_probability": _valid_probability(favorite.get("market_probability")) if favorite else None,
        "model_version": favorite.get("model_version") if model_selected else None,
        "model_stage": favorite.get("model_stage") if model_selected else "UNAVAILABLE",
        "betting_status": "RESEARCH ONLY",
    }
    return {
        "sport": sport, "event_id": event_id,
        "event": same[0].get("event"), "starts_at": same[0].get("starts_at"),
        "projection": projection,
        "pick_explanation": projection_reason(projection, favorite),
        "markets": sorted(set(r.get("market") for r in same if r.get("market"))),
        "observed_rows": len(same), "fresh_rows": sum(bool(r.get("fresh")) for r in same),
        "price_at": max((r.get("price_at") for r in same if r.get("price_at")), default=None),
        "research": same[:40],
        "simulation": {
            "state": "UNAVAILABLE",
            "reason": "A verified event-specific joint score distribution is required. Moneyline probability alone cannot generate a defensible score simulation.",
            "approved_for_betting": False,
        },
        "first_td": {
            "state": "UNAVAILABLE" if sport == "NFL" else "NOT_APPLICABLE",
            "players": [],
            "reason": "A validated first-touchdown event hazard model with complete scorer outcomes is not connected.",
            "approved_for_betting": False,
        },
    }


def simulate_samples(samples, *, home, away, spread_line=None, total_line=None):
    """Summarize genuine event-specific joint score samples; never generate samples here."""
    from ..models.game_distribution import GameDistribution
    distribution = GameDistribution(tuple(tuple(pair) for pair in samples))
    summary = distribution.summary()
    home_wins = distribution.outcome("h2h", home, None, home, away)
    away_wins = distribution.outcome("h2h", away, None, home, away)
    result = {
        "state": "SHADOW_ONLY",
        "approved_for_betting": False,
        "source": "SUPPLIED_EVENT_SPECIFIC_SCORE_SAMPLES",
        "summary": summary,
        "home": home, "away": away,
        "home_win": home_wins, "away_win": away_wins,
        "spread": None, "total": None,
    }
    if spread_line is not None:
        result["spread"] = distribution.outcome("spreads", home, float(spread_line), home, away)
    if total_line is not None:
        result["total"] = distribution.outcome("totals", "Over", float(total_line), home, away)
    return result


def first_td_distribution(*, team_first_td_probabilities, scorer_shares, no_td_probability):
    """Coherent conditional first-TD event model from explicitly supplied inputs.

    This is a mathematical primitive, not a trained/calibrated player model.
    Team probabilities include offensive, defensive and special-teams first
    touchdowns. Scorer shares must partition all of those outcomes.
    """
    no_td = _valid_probability(no_td_probability)
    if no_td is None and no_td_probability != 0:
        raise ValueError("No-TD probability must be in [0, 1)")
    no_td = float(no_td_probability)
    if not isinstance(team_first_td_probabilities, dict) or len(team_first_td_probabilities) != 2:
        raise ValueError("Two teams required")
    teams = {}
    for team, probability in team_first_td_probabilities.items():
        p = float(probability)
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid team first TD probability")
        teams[str(team)] = p
    if abs(sum(teams.values()) + no_td - 1) > 1e-8:
        raise ValueError("Complete first touchdown outcomes must sum to one")
    output = []
    for team, probability in teams.items():
        shares = scorer_shares.get(team)
        if not isinstance(shares, dict) or not shares:
            raise ValueError("Each team needs complete conditional scorer shares")
        total = sum(float(x) for x in shares.values())
        if abs(total - 1) > 1e-8:
            raise ValueError("Player, other, and defensive/special-teams shares must sum to one")
        for player, share in shares.items():
            share = float(share)
            if not math.isfinite(share) or share < 0:
                raise ValueError("Invalid conditional scorer share")
            output.append({"team": team, "scorer": str(player), "probability": probability * share})
    if abs(sum(x["probability"] for x in output) + no_td - 1) > 1e-8:
        raise ValueError("Invalid first touchdown distribution")
    return {"state": "SHADOW_ONLY", "approved_for_betting": False,
            "outcomes": sorted(output, key=lambda x: -x["probability"]),
            "no_td_probability": no_td, "method": "supplied_conditional_first_touchdown_hazards"}


def score_histograms(distribution):
    """Compact probability histograms computed from the exact underlying measure."""
    from collections import defaultdict
    if hasattr(distribution, 'grid'):
        pairs = distribution.grid.items()
    else:
        pairs = [(pair, 1 / len(distribution.samples)) for pair in distribution.samples]
    masses = {'margin': defaultdict(float), 'total': defaultdict(float)}
    for (home, away), probability in pairs:
        masses['margin'][home-away] += probability
        masses['total'][home+away] += probability
    output = {}
    for name, mass in masses.items():
        lo, hi = min(mass), max(mass)
        width = max(1, math.ceil((hi-lo+1)/20))
        bins = defaultdict(float)
        for value, probability in mass.items():
            bins[int((value-lo)//width)] += probability
        output[name] = [{'low': lo+i*width, 'high': min(hi, lo+(i+1)*width-1), 'probability': p}
                        for i, p in sorted(bins.items())]
    return output


def simulate_current_event(store, *, sport, event_id, rows, spread_line=None, total_line=None):
    """Reuse the canonical fitted score model and its strict identity/freshness gates.

    A successful estimate supplies actual paired score samples. This endpoint
    never manufactures a distribution from a market moneyline.
    """
    from decimal import Decimal
    from ..domain.shopping import PriceCard
    from ..models.team_elo import SPORTS
    from ..models.score_distribution import ScoreDistributionModel

    unavailable = {
        "state": "UNAVAILABLE", "approved_for_betting": False,
        "reason": "No validated, fresh, event-matched score distribution is available.",
    }
    if sport not in {"NFL", "CFB", "NBA", "MLB", "NHL"}:
        return unavailable
    model_sport = SPORTS[sport.lower()]
    artifacts = store.list_records("game_model", 1, entity=model_sport)
    if not artifacts:
        return {**unavailable, "reason": "No fitted score-model artifact has been saved for this sport."}
    artifact = artifacts[0]["payload"]
    if artifact.get("status") in {"UNAVAILABLE", "QUARANTINED"}:
        return {**unavailable, "state": artifact["status"], "reason": "The score model is " + artifact["status"] + "; its validation or inputs must be resolved before simulation."}
    try:
        if sport == "NHL":
            from ..models.nhl_goals import NHLGoalsModel
            model = NHLGoalsModel(artifact)
        else:
            model = ScoreDistributionModel(artifact)
        for row in rows:
            if (row.get("sport") != sport or str(row.get("event_id")) != event_id
                    or row.get("market") != "h2h" or not row.get("fresh")
                    or row.get("lifecycle") != "UPCOMING"
                    or row.get("data_health") != "HEALTHY"
                    or row.get("status") in {"QUARANTINED", "INVALIDATED"}
                    or row.get("model_stage") in {"QUARANTINED", "UNAVAILABLE"}):
                continue
            observed = datetime.fromisoformat(str(row["price_at"]).replace("Z", "+00:00"))
            start = datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00"))
            price = Decimal(str(row["decimal"]))
            market_probability = Decimal(str(row["market_probability"]))
            if not (observed.tzinfo and start.tzinfo and price > 1
                    and 0 < market_probability < 1):
                continue
            card = PriceCard(
                sport=model_sport, event_id=event_id, event=row["event"],
                market="h2h", participant=None, selection=row["selection"], line=None,
                book_prices={str(row.get("book") or "observed"): price},
                best_book=str(row.get("book") or "observed"), best_decimal=price,
                consensus_probability=market_probability, market_relative_ev=Decimal("0"),
                sportsbook_disagreement=Decimal("0"), stale=False, in_play=False,
                quote_ids=(), observed_at=observed, source_timestamp=observed,
                starts_at=start, executable=False,
            )
            estimate = model.estimate(card)
            if estimate is None or not model._cache:
                continue
            if sport == "NHL":
                from .nhl_scenarios import NHLScenarios
                distribution = NHLScenarios(estimate.feature_snapshot)
            else:
                _, distribution = next(iter(model._cache.values()))
            summary = distribution.summary()
            home = estimate.feature_snapshot["home_team"]
            away = estimate.feature_snapshot["away_team"]
            return {
                "state": "SHADOW_ONLY", "approved_for_betting": False,
                "source": "CANONICAL_NHL_WEIGHTED_SCORE_GRID" if sport == "NHL" else "CANONICAL_PAIRED_SCORE_MODEL",
                "settlement": estimate.feature_snapshot.get("settlement"),
                "model_version": estimate.model_version,
                "model_snapshot_id": estimate.feature_snapshot["snapshot_id"],
                "home": home, "away": away,
                "summary": summary,
                "histograms": score_histograms(distribution),
                "input_observed_at": observed.isoformat(),
                "scenario_basis": "Baseline model distribution evaluated at user-selected lines; no roster or scoring assumptions are changed.",
                "home_win": distribution.outcome("h2h", home, None, home, away),
                "away_win": distribution.outcome("h2h", away, None, home, away),
                "spread": ({"home_line": spread_line, **distribution.outcome("spreads", home, spread_line, home, away)}
                           if spread_line is not None else None),
                "total": ({"line": total_line, "selection": "Over", **distribution.outcome("totals", "Over", total_line, home, away)}
                          if total_line is not None else None),
                "notice": "Real model score scenarios, research only. Missing starter, roster, injury or calibration evidence blocks betting approval.",
            }
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, ArithmeticError):
        return unavailable
    return unavailable
