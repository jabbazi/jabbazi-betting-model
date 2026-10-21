"""Refresh NHL schedules/results without retraining or promoting parameters."""

from datetime import timedelta

from jabazi.models.nhl_goals import NHLGoalsModel, team_state
from jabazi.models.team_elo import timestamp
from jabazi.providers.nhl import SPORT, fetch_clubs


def update_state(artifact, games, *, now, checksum):
    if not checksum or not games or any(g["season"] != artifact["active_season"] for g in games):
        raise ValueError("NHL current-season coverage unavailable")
    ids = [g["game_id"] for g in games]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate NHL refresh game")
    additions = team_state(games, now)
    state = {t: list(v) for t, v in artifact["team_state"].items()}
    for team, history in additions.items():
        merged = {r[4]: r for r in state.get(team, [])}
        merged.update({r[4]: r for r in history})
        state[team] = sorted(merged.values(), key=lambda r: (r[2], r[4]))[-100:]
    future = [
        g
        for g in games
        if not g["completed"]
        and g["scheduled"]
        and now < timestamp(g["starts_at"]) <= now + timedelta(days=10)
    ]
    updated = artifact | {
        "team_state": state,
        "events": future,
        "state_refreshed_at": now.isoformat(),
        "state_source_checksum": checksum,
    }
    NHLGoalsModel(updated)
    return updated


def fetch_update(artifact, *, now, result_store=None):
    games, checksum = fetch_clubs(artifact["active_season"], artifact["clubs"])
    updated = update_state(artifact, games, now=now, checksum=checksum)
    if result_store is not None:
        from jabazi.research.prospective import archive_results

        completed = [g for g in games if g["completed"]
                     and timestamp(g["available_at"]) < now
                     and timestamp(g["starts_at"]) >= now - timedelta(days=30)]
        # Opening week has a valid future schedule and zero completed games.
        # The historical-result validator correctly rejects empty training data;
        # there is simply nothing to archive in this refresh yet.
        if completed:
            archive_results(result_store, SPORT, completed, observed_at=now,
                            source_checksum=checksum)
    return updated
