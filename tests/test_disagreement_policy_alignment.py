from jabazi.reliability.layer import anomaly


def _checks():
    return {
        "event_identity": True,
        "line_identity": True,
        "fresh_features": True,
        "schema": True,
        "variance": True,
        "pairing": True,
        "no_duplicate_event": True,
        "starter": True,
        "injuries": True,
        "roster": True,
        "calibration": True,
    }


def test_legacy_anomaly_path_uses_new_disagreement_boundaries():
    checks = _checks()
    assert anomaly(0.549, 0.50, checks)["state"] == "NORMAL"
    assert anomaly(0.55, 0.50, checks)["state"] == "LARGE_DISAGREEMENT"
    assert anomaly(0.60, 0.50, checks)["state"] == "LARGE_DISAGREEMENT"
    assert anomaly(0.601, 0.50, checks)["state"] == "EXTREME_DISAGREEMENT"
