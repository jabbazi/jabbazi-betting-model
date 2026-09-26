"""Fail-closed health assessment; no approval is inferred from profitable tests."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Health:
    healthy: bool
    reasons: tuple[str, ...]


def assess(
    *,
    now,
    observed_at,
    source_at,
    starts_at,
    model_approved,
    database_ok,
    required_features=(),
    available_features=(),
    lineup_ready=True,
    injury_ready=True,
    weather_ready=True,
    calibration_drift=False,
    clv_deterioration=False,
    provider_agreement=True,
    max_age_seconds=120,
):
    reasons = []
    if not database_ok:
        reasons.append("DATABASE_UNAVAILABLE")
    if not model_approved:
        reasons.append("MODEL_UNAVAILABLE")
    for t in (now, observed_at, source_at, starts_at):
        if t is None or t.tzinfo is None:
            reasons.append("INSUFFICIENT_TIMING_DATA")
            break
    else:
        if min((now - source_at).total_seconds(), (now - observed_at).total_seconds()) < 0:
            reasons.append("FUTURE_TIMESTAMP")
        if (
            max((now - source_at).total_seconds(), (now - observed_at).total_seconds())
            > max_age_seconds
        ):
            reasons.append("STALE_DATA")
        if starts_at <= now:
            reasons.append("LIVE_MODEL_REQUIRED")
    if set(required_features) - set(available_features):
        reasons.append("INSUFFICIENT_FEATURES")
    if not lineup_ready:
        reasons.append("WAIT_FOR_LINEUP")
    if not injury_ready:
        reasons.append("WAIT_FOR_INJURY")
    if not weather_ready:
        reasons.append("WAIT_FOR_WEATHER")
    if calibration_drift:
        reasons.append("CALIBRATION_DRIFT")
    if clv_deterioration:
        reasons.append("CLV_DETERIORATION")
    if not provider_agreement:
        reasons.append("PROVIDER_DISAGREEMENT")
    return Health(not reasons, tuple(reasons))


def allowed_market(sport, market, jurisdiction="LA"):
    if jurisdiction == "LA" and sport == "americanfootball_ncaaf":
        # Explicit allowlist prevents a newly introduced prop key leaking through.
        return market in {
            "h2h",
            "spreads",
            "totals",
            "alternate_spreads",
            "alternate_totals",
            "team_totals",
            "alternate_team_totals",
            "h2h_h1",
            "spreads_h1",
            "totals_h1",
            "h2h_q1",
            "spreads_q1",
            "totals_q1",
        }
    return True
