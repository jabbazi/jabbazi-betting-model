"""Safe, specific forecast-unavailability reasons shared by member surfaces.

No raw provider errors, private feature payloads, credentials, or guessed input
facts are exposed. Unknown diagnostic strings map to a generic explanation.
"""
REASONS = {
    'UNVERIFIED_NEGATIVE_SIDE_CALIBRATION': 'This older model has no verified under/no-side calibration.',
    'EVENT_INVALIDATED': 'This event was cancelled, postponed or invalidated.',
    'MODEL_QUARANTINED': 'This forecast is quarantined pending review.',
    'MODEL_MARKET_DISAGREEMENT_REVIEW': 'Model/market disagreement requires a safety review.',
    'UNVERIFIED_EVENT_IDENTITY': 'Game identity has not passed verification.',
    'UNVERIFIED_PLAYER_IDENTITY': 'Player identity has not passed verification.',
    'UNVERIFIED_LINE_IDENTITY': 'The exact market and line have not passed verification.',
    'UNVERIFIED_FRESH_FEATURES': 'Current pregame model inputs are unverified.',
    'UNVERIFIED_SCHEMA': 'Model inputs do not have a verified schema.',
    'UNVERIFIED_VARIANCE': 'The statistical distribution is unverified.',
    'UNVERIFIED_PAIRING': 'Comparable market outcomes are incomplete.',
    'UNVERIFIED_NO_DUPLICATE_EVENT': 'Unique game identity has not passed verification.',
    'UNVERIFIED_STARTER': 'Required role or starter evidence is missing.',
    'UNVERIFIED_ROSTER': 'Required roster evidence is missing.',
    'UNVERIFIED_INJURIES': 'Required injury evidence is missing.',
    'UNVERIFIED_CALIBRATION': 'This disagreement requires calibration evidence.',
    'FEATURE_DISTRIBUTION_DRIFT': 'Model inputs are outside the accepted distribution.',
    'MISSING_MODEL_VERSION': 'No versioned model forecast is saved for this selection.',
    'NO_MODEL_ARTIFACT_FOR_MARKET': 'No fitted model is loaded for this market.',
    'MODEL_INPUTS_UNAVAILABLE_OR_REJECTED': 'The model exists but its required inputs are missing or rejected.',
    'MODEL_DATA_HEALTH_UNVERIFIED': 'The saved forecast has not passed data-integrity checks.',
    'MODEL_STAGE_UNAVAILABLE': 'The model is not in an eligible research stage.',
    'STALE_MODEL_SNAPSHOT': 'The saved forecast is stale; a successful model refresh is required.',
    'STALE_PLAYER_FEATURES': 'The player inputs have expired; current pregame evidence is required.',
    'NO_VALID_EXACT_LINE_MODEL_ESTIMATE': 'No usable model probability is saved for this exact selection.',
    'MODEL_OR_FEATURES_UNAVAILABLE': 'A current verified forecast is unavailable.',
    'PUBLISHING_PAUSED': 'Research publication is paused by an administrator.',
}


def explanation(code):
    return REASONS.get(str(code), REASONS['MODEL_OR_FEATURES_UNAVAILABLE'])


def unavailable_reasons(raw, *, invalidated, quarantined, safety_review,
                        model_fresh, model_at, snapshot_at, now, age_ok, stages):
    """Reasons reflect saved evidence; missing optional fields are not fabricated."""
    reasons = []
    if invalidated:
        reasons.append('EVENT_INVALIDATED')
    audit = raw.get('anomaly_reasons')
    if isinstance(audit, (list, tuple)):
        reasons.extend(r for r in audit if isinstance(r, str) and r in REASONS)
    if quarantined:
        reasons.append('MODEL_QUARANTINED')
    if safety_review:
        reasons.append('MODEL_MARKET_DISAGREEMENT_REVIEW')
    code = raw.get('model_routing_reason')
    if isinstance(code, str) and code in REASONS:
        reasons.append(code)
    if not raw.get('model_version'):
        reasons.append('MISSING_MODEL_VERSION')
    if raw.get('model_stage') not in stages:
        reasons.append('MODEL_STAGE_UNAVAILABLE')
    if raw.get('data_health') != 'HEALTHY':
        reasons.append('MODEL_DATA_HEALTH_UNVERIFIED')
    if not age_ok(snapshot_at, now, 10800) or not age_ok(model_at, now, 10800):
        reasons.append('STALE_MODEL_SNAPSHOT')
    if raw.get('features_available_at') and not age_ok(raw['features_available_at'], now, 3600):
        reasons.append('STALE_PLAYER_FEATURES')
    if not reasons:
        reasons.append('NO_VALID_EXACT_LINE_MODEL_ESTIMATE' if model_fresh else 'MODEL_OR_FEATURES_UNAVAILABLE')
    return list(dict.fromkeys(reasons))
