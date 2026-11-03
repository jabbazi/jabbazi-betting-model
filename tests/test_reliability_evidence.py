from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from dataclasses import replace
import pytest
from jabazi.persistence.store import Store, Conflict
from jabazi.research.evidence import freeze_source, record_lifecycle, persist_clv, freeze_forecast
from jabazi.domain.thesis import graph
from jabazi.domain.portfolio import Position
from jabazi.domain.promotions import Promotion, evaluate
from jabazi.research.calibration_report import report, fit, transform
from jabazi.models.form_features import recency_features, POLICIES


def test_report_regeneration_preserves_original_training_provenance():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools/build_upgrade_report.py"
    spec = importlib.util.spec_from_file_location("upgrade_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifact = {"code_commit": "original-parent"}
    module.attach_training_provenance(artifact, {"source.py": "original-hash"}, {"python": "3.12"})
    module.attach_training_provenance(artifact, {"source.py": "new-hash"}, {"python": "3.13"})
    assert artifact == {
        "code_commit": None,
        "code_parent_commit": "original-parent",
        "training_source_sha256": {"source.py": "original-hash"},
        "runtime": {"python": "3.12"},
    }


def test_source_and_price_lifecycle_are_immutable_and_clv_persists():
    s = Store("sqlite:///:memory:", initialize=True)
    now = datetime.now(UTC)
    pick = dict(
        source="User-supplied source",
        original_selection="Home +1.5",
        posted_at=now,
        observed_at=now,
        sport="baseball_mlb",
        event_id="g",
        market="spreads",
        selection="Home",
        line="1.5",
        settlement_key="full_game:listed_pitchers",
    )
    key = freeze_source(s, pick)
    assert freeze_source(s, pick) == key
    with pytest.raises(Conflict):
        freeze_source(s, pick | {"line": "2.5"})
    entry = dict(
        candidate_id="c",
        phase="confirmed_entry",
        at=now,
        event_id="g",
        market="spreads",
        selection="Home",
        line="1.5",
        period="full_game",
        settlement_key="full_game:listed_pitchers",
        decimal_odds="2",
        evidence_id="e",
    )
    close = entry | dict(
        phase="closing", at=now + timedelta(hours=1), evidence_id="z", no_vig_probability=".55"
    )
    record_lifecycle(s, entry)
    record_lifecycle(s, close)
    assert D(persist_clv(s, entry, close)["probability_clv"]) == D(".05")
    assert len(s.list_records("clv_record")) == 1
    with pytest.raises(ValueError):
        persist_clv(s, entry, close | {"line": "2.5"})
    s.close()


def test_forecasts_cannot_be_overwritten_after_start():
    s = Store("sqlite:///:memory:", initialize=True)
    now = datetime.now(UTC)
    fields = {
        k: "v"
        for k in (
            "model_version",
            "feature_schema_version",
            "dataset_hash",
            "code_commit",
            "feature_snapshot",
            "odds_snapshot",
        )
    }
    freeze_forecast(
        s, prediction_id="x", starts_at=now + timedelta(hours=1), predicted_at=now, payload=fields
    )
    with pytest.raises(Conflict):
        freeze_forecast(
            s,
            prediction_id="x",
            starts_at=now + timedelta(hours=1),
            predicted_at=now,
            payload=fields | {"model_version": "different"},
        )
    with pytest.raises(ValueError):
        freeze_forecast(s, prediction_id="y", starts_at=now, predicted_at=now, payload=fields)
    s.close()


def test_thesis_graph_counts_both_cash_origins_without_double_counting_total():
    p = Position(D(30), "nfl", "g", theses=frozenset({"offense:g:KC"}), origin="scanner")
    r = graph([p, replace(p, amount=D(20), origin="user-choice")])
    assert r["total_cash_dollars"] == "50" and r["scanner_cash_dollars"] == "30"
    assert r["nodes"]["offense:g:KC"]["cash_dollars"] == "50"


def test_boost_does_not_rescue_failed_base_wager():
    now = datetime.now(UTC)
    promo = Promotion(
        "Book",
        "profit_boost",
        now + timedelta(hours=1),
        D(30),
        boost=D(".5"),
        void_rules_verified=True,
    )
    result = evaluate(
        promo,
        book="Book",
        price=2,
        p=".6",
        stake=10,
        legs=1,
        now=now,
        sport="nfl",
        markets=["h2h"],
        base_qualified=False,
    )
    assert result["boosted_roi"] == D(".5") and result["status"] == "PASS"


def test_calibration_probabilities_and_counts():
    p = [0.55] * 100 + [0.65] * 100 + [0.75] * 100 + [0.85] * 100
    y = [1] * 55 + [0] * 45 + [1] * 65 + [0] * 35 + [1] * 75 + [0] * 25 + [1] * 85 + [0] * 15
    r = report(p, y)
    assert sum(b["n"] for b in r["buckets"]) == 400
    for method in ("platt", "isotonic", "beta"):
        c = fit(p, y, method)
        pred = transform(c, [0.55, 0.65, 0.75, 0.85], method)
        assert all(0 <= v <= 1 for v in pred) and list(pred) == sorted(pred)


def test_recency_weakens_old_season_and_rejects_future_result():
    now = datetime(2026, 9, 25, tzinfo=UTC)

    def g(score, age):
        return [
            score,
            20,
            (now - timedelta(days=age)).isoformat(),
            (now - timedelta(days=age - 2)).isoformat(),
            "A",
        ]

    state = {"H": [g(40, 300), g(10, 7)], "A": [g(20, 300), g(20, 7)]}
    x = recency_features(state, "H", "A", now, False, 2, POLICIES["nfl"])
    assert x[0] < 25
    state["A"][-1][3] = (now + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        recency_features(state, "H", "A", now, False, 2, POLICIES["nfl"])
