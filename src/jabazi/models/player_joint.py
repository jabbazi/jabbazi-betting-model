"""Two-prop empirical checkerboard copula, fitted on aligned historical games.

Each rank cell is uniform; cells retain empirical dependence. Marginal probabilities
come from current player models. No hand-set rho or independent leg product is used
as the joint estimate. More than two props and mixed team/prop tickets fail closed.
"""

import json
from pathlib import Path
from decimal import Decimal as D
from math import isfinite

SPORT = "americanfootball_nfl"
ARTIFACT = Path(__file__).with_name("artifacts") / "nfl_player_joint.json"


def checkerboard_joint(ranks, probabilities, positive):
    n = len(ranks)
    if n < 2 or len(probabilities) != 2 or len(positive) != 2:
        raise ValueError("Invalid joint support")
    if any(not isfinite(float(p)) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("Invalid marginals")
    total = 0.0
    for row in ranks:
        fractions = []
        for rank, p, high in zip(row, probabilities, positive, strict=True):
            lo, hi = rank / n, (rank + 1) / n
            overlap = max(0.0, hi - max(lo, 1 - p)) if high else max(0.0, min(hi, p) - lo)
            fractions.append(min(1.0, overlap * n))
        total += fractions[0] * fractions[1]
    return min(min(probabilities), max(max(0.0, sum(probabilities) - 1), total / n))


def position(snapshot):
    f = snapshot.get("features", {})
    roles = [r.upper() for r in ("qb", "rb", "wr", "te") if f.get("position_" + r) == 1]
    if len(roles) != 1:
        raise ValueError("VERIFIED_PLAYER_POSITION_REQUIRED")
    return roles[0]


class JointPlayerModel:
    def __init__(self, artifact):
        if (
            artifact.get("schema_version") != 1
            or artifact.get("sport") != SPORT
            or artifact.get("approved_for_betting") is not False
        ):
            raise ValueError("Invalid joint-player artifact")
        if not artifact.get("source_checksum") or not artifact.get("model_version"):
            raise ValueError("Joint-player provenance missing")
        for b in artifact["buckets"]:
            ranks = b["ranks"]
            n = len(ranks)
            if n < 100 or b["training_unique_games"] < 100:
                raise ValueError("Insufficient independent game evidence")
            if any(len(row) != 2 for row in ranks):
                raise ValueError("Malformed rank support")
            for axis in (0, 1):
                if sorted(row[axis] for row in ranks) != list(range(n)):
                    raise ValueError("Copula rank columns must be permutations")
        self.artifact = artifact

    def scenarios(self, prices, models):
        if len(prices) != 2 or any(p.sport != SPORT for p in prices):
            raise ValueError("TWO_NFL_PLAYER_LEGS_REQUIRED")
        estimates = []
        for p in prices:
            m = models.get((p.sport, p.market))
            e = m.estimate(p) if m else None
            if e is None:
                raise ValueError("PLAYER_MODEL_INPUTS_UNAVAILABLE")
            required = (
                "event_identity",
                "player_identity",
                "role",
                "availability",
                "fresh_features",
            )
            if not all(e.feature_snapshot.get("integrity", {}).get(k) is True for k in required):
                raise ValueError("PLAYER_IDENTITY_OR_ROLE_UNVERIFIED")
            estimates.append(e)
        snapshots = [e.feature_snapshot for e in estimates]
        # Use provider IDs, not matching display names, for relationship identity.
        ids = [s.get("player_id") for s in snapshots]
        if not all(ids):
            raise ValueError("VERIFIED_PLAYER_IDS_REQUIRED")
        relation = "same_player" if ids[0] == ids[1] else "same_team"
        if relation == "same_team":
            teams = [s.get("team") for s in snapshots]
            if not all(teams) or teams[0] != teams[1]:
                raise ValueError("VERIFIED_SAME_TEAM_REQUIRED")
        roles = [position(s) for s in snapshots]
        for bucket in self.artifact["buckets"]:
            if bucket["relationship"] != relation:
                continue
            for order in ((0, 1), (1, 0)):
                if [prices[i].market for i in order] != bucket["markets"] or [
                    roles[i] for i in order
                ] != bucket["positions"]:
                    continue
                if not bucket.get("research_admitted"):
                    raise ValueError("PLAYER_CORRELATION_HOLDOUT_NOT_IMPROVED")
                if [estimates[i].model_version for i in order] != bucket["marginal_versions"]:
                    raise ValueError("JOINT_MARGINAL_VERSION_MISMATCH")
                ps = [float(estimates[i].probability) for i in order]
                high = [prices[i].selection.lower() in {"over", "yes"} for i in order]
                joint = D(str(checkerboard_joint(bucket["ranks"], ps, high)))
                p0, p1 = (e.probability for e in estimates)
                joint = min(p0, p1, max(D(0), p0 + p1 - 1, joint))
                weights = [joint, p0 - joint, p1 - joint, 1 - p0 - p1 + joint]
                return (
                    [[True, True], [True, False], [False, True], [False, False]],
                    weights,
                    estimates,
                    "full_game_player_active_book_rules_confirmed",
                    {
                        "joint_model_version": self.artifact["model_version"],
                        "relationship": relation,
                        "markets": bucket["markets"],
                        "training_unique_games": bucket["training_unique_games"],
                        "training_pairs": len(bucket["ranks"]),
                        "holdout": bucket["holdout"],
                        "rank_correlation": bucket["rank_correlation"],
                        "source_checksum": self.artifact["source_checksum"],
                        "assumption": "Historical residual-rank dependence transfers to current players",
                        "prospective_sgp_validation": "NOT_COMPLETED",
                    },
                )
        raise ValueError("SUPPORTED_PLAYER_CORRELATION_UNAVAILABLE")


def load_joint_player_model():
    try:
        return JointPlayerModel(json.loads(ARTIFACT.read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return None
