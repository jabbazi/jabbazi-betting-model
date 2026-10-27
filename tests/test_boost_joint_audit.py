from jabazi.boost_joint_audit import audit_joint_predictions
import pytest


def sample(outcome=1):
    return {"sport":"icehockey_nhl","event_id":"g1","ticket_id":"t1",
            "model_version":"v1","split":"test",
            "predicted_at":"2026-10-01T12:00:00Z",
            "starts_at":"2026-10-01T19:00:00Z",
            "probability":.4,"outcome":outcome}


def test_small_sample_never_approved():
    result = audit_joint_predictions([sample()])
    assert result["approved_for_betting"] is False
    assert result["reports"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["reports"][0]["brier"] == pytest.approx(.36)


def test_duplicate_identity_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        audit_joint_predictions([sample(),sample()])


def test_leakage_rejected():
    row = sample()
    row["predicted_at"] = "2026-10-02T12:00:00Z"
    with pytest.raises(ValueError, match="point-in-time"):
        audit_joint_predictions([row])
