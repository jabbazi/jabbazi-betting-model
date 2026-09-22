"""Load each league independently; invalid artifacts fail closed per league."""

import json
import os
from pathlib import Path

from .team_elo import SPORTS, TeamEloModel


def load_models():
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
    return result, errors
