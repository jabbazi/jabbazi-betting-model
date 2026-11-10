"""Synthetic audit regressions, never evidence of a calibrated sports model."""
import pytest

from jabazi.boost_joint_evidence import audit_frozen_joint_evidence
from tests.test_boost_joint_evidence import row


def test_offsetting_errors_are_visible_in_probability_bins():
    result = audit_frozen_joint_evidence([
        row(event="low", probability=.1, outcome=1),
        row(event="high", probability=.9, outcome=0),
    ])
    report = result["reports"][0]
    assert report["calibration_gap"] == pytest.approx(0)
    assert report["calibration"]["event_weighted_ece"] == pytest.approx(.9)
    assert len(report["calibration"]["bins"]) == 2
    assert result["research_review_eligible"] is False


def test_duplicate_tickets_do_not_overweight_one_event():
    sample = [row(event="first", probability=.2, outcome=1),
              row(event="second", probability=.2, outcome=0)]
    base = audit_frozen_joint_evidence(sample)["reports"][0]
    sample += [row(event="first", ticket=str(i), probability=.2, outcome=1)
               for i in range(20)]
    repeated = audit_frozen_joint_evidence(sample)["reports"][0]
    assert repeated["calibration"]["event_weighted_ece"] == pytest.approx(
        base["calibration"]["event_weighted_ece"])


@pytest.mark.parametrize("probability,eligible", [(.8, True), (.2, False)])
def test_both_partitions_and_market_improvement_required(probability, eligible):
    sample = [row(sport=sport, split=split, event=split,
                  probability=probability, market=.5, outcome=1)
              for sport in ("basketball_nba", "icehockey_nhl")
              for split in ("test", "prospective")]
    report = audit_frozen_joint_evidence(sample, minimum_events=1)
    assert report["research_review_eligible"] is eligible
    assert report["release_ready"] is False
    assert report["approved_for_betting"] is False
    assert audit_frozen_joint_evidence(sample)["research_review_eligible"] is False


@pytest.mark.parametrize("argument", ["minimum_events", "max_quote_age_seconds"])
def test_boolean_does_not_reduce_required_evidence(argument):
    with pytest.raises(ValueError):
        audit_frozen_joint_evidence([], **{argument: True})
