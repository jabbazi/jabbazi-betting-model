"""Load each league independently; invalid artifacts fail closed per league."""

import json
import os
from pathlib import Path

from .team_elo import SPORTS, TeamEloModel


def load_models(store=None):
    result, errors = {}, []
    for short, sport in SPORTS.items():
        path = Path(os.getenv(f"JABBAZI_{short.upper()}_BASELINE", f"models/{short}_baseline.json"))
        if not path.exists():
            continue
        try:

            def optional_mapping(suffix):
                value = os.getenv(f"JABBAZI_{short.upper()}_{suffix}", "")
                return json.loads(Path(value).read_text()) if value else {}

            model = TeamEloModel(
                path, optional_mapping("ALIASES"), optional_mapping("EVENT_CONTEXT")
            )
            if model.sport != sport:
                raise ValueError("Artifact league mismatch")
            result[sport] = model
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f"{sport}:model_load_{type(exc).__name__}")
    from .refresh import BUNDLE_DIR
    from .score_distribution import ScoreDistributionModel

    for short in ("nfl", "mlb", "cfb"):
        sport = SPORTS[short]
        records = store.list_records("game_model", 1, entity=sport) if store else []
        path = BUNDLE_DIR / f"{short}_scores.json"
        if not records and not path.exists():
            continue
        # A malformed or failed latest cloud refresh must not revive old files.
        result.pop(sport, None)
        try:
            artifact = records[0]["payload"] if records else json.loads(path.read_text())
            if artifact.get("status") == "UNAVAILABLE":
                raise ValueError("Model refresh unavailable")
            model = ScoreDistributionModel(artifact)
            if model.sport != sport:
                raise ValueError("Artifact league mismatch")
            result[sport] = model
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f"{sport}:score_model_load_{type(exc).__name__}")
    return result, errors
