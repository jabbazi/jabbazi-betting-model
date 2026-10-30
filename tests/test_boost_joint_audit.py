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


def test_event_cannot_appear_in_test_and_prospective():
    second = dict(sample(), split="prospective", ticket_id="another")
    with pytest.raises(ValueError, match="Event overlap"):
        audit_joint_predictions([sample(), second])


def test_model_version_cannot_change_ticket_outcome():
    second = dict(sample(), model_version="v2", outcome=0)
    with pytest.raises(ValueError, match="Conflicting ticket outcomes"):
        audit_joint_predictions([sample(), second])


@pytest.mark.parametrize("field", ["event_id", "ticket_id", "model_version"])
def test_blank_provenance_rejected(field):
    row = dict(sample(), **{field: ""})
    with pytest.raises(ValueError, match="provenance"):
        audit_joint_predictions([row])


def test_distinct_events_can_have_separate_splits():
    second = dict(sample(), event_id="g2", split="prospective")
    report = audit_joint_predictions([sample(), second])
    assert len(report["reports"]) == 2
    assert report["approved_for_betting"] is False
