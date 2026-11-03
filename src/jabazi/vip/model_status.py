"""Member model readiness from persisted evidence only, without provider probes."""
from ..models.registry import load_models
from ..models.player_registry import load_player_models, player_status
from ..models.team_elo import SPORTS
from ..reliability.layer import status_buckets
from ..research.prospective import validation_report


def saved_model_status():
    """Own/close a read-only store handle for the shared nonblocking cache.

    The owner diagnostic also calls live provider endpoints. Member views must
    not use it; loading fitted artifacts and recorded validation evidence is
    sufficient for this display and does not create any promotion evidence.
    """
    from ..api import platform_store
    store = platform_store()
    try:
        models, errors = load_models(store)
        players, player_errors = load_player_models(store)
        prospective = validation_report(store)
        rows = []
        for sport in SPORTS.values():
            team = models.get(sport)
            buckets = status_buckets(team, prospective) if team is not None else {}
            stages = {bucket['stage'] for bucket in buckets.values()}
            stage = ('PRODUCTION_APPROVED' if stages == {'PRODUCTION_APPROVED'}
                     else 'LIMITED_LIVE' if stages & {'PRODUCTION_APPROVED', 'LIMITED_LIVE'}
                     else 'VALIDATING' if 'VALIDATING' in stages
                     else 'SHADOW_ONLY' if stages else 'UNAVAILABLE')
            player = player_status(players, sport)
            rows.append({
                'sport': sport, 'status': stage,
                'version': team.artifact.get('model_version') if team else None,
                'state_refreshed_at': team.artifact.get('state_refreshed_at') if team else None,
                'supported_markets': sorted(team.supported_markets) if team else [],
                'market_buckets': buckets,
                'player_status': player['status'],
                'player_supported_markets': player['supported_markets'],
                'player_market_buckets': player['market_buckets'],
            })
        # Do not expose filesystem paths or exception text in member views.
        return {'models': rows, 'errors': ['MODEL_EVIDENCE_UNAVAILABLE'] if errors or player_errors else [],
                'paid_requests_made': 0, 'source': 'SAVED_MODEL_EVIDENCE'}
    finally:
        store.close()
