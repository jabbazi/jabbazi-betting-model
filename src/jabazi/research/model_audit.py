"""Inspect saved diagnostic evidence without fitting, tuning, or promoting models."""

import math


def calibration_summary(metrics):
    bins = metrics.get("reliability", [])
    n = metrics.get("n", 0)
    populated = [b for b in bins if b.get("n", 0)]
    if not n or sum(b["n"] for b in populated) != n:
        return {"n": n, "expected_calibration_error": None, "largest_bucket_gap": None}
    gaps = []
    for b in populated:
        p, y = b.get("mean_probability"), b.get("observed_rate")
        if any(
            not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1
            for x in (p, y)
        ):
            raise ValueError("Malformed reliability evidence")
        gaps.append((b["n"], abs(p - y)))
    return {
        "n": n,
        "expected_calibration_error": sum(k * gap for k, gap in gaps) / n,
        "largest_bucket_gap": max(gap for _, gap in gaps),
        "note": "Descriptive bucket gaps, not confidence intervals or proof of edge",
    }


def audit_report(report, artifact):
    if (
        report.get("model_version") != artifact.get("model_version")
        or report.get("source_checksum") != artifact.get("source_checksum")
        or not report.get("model_version")
        or not report.get("source_checksum")
    ):
        raise ValueError("Artifact and diagnostic report provenance mismatch")
    paired = report.get("paired_market_diagnostic", {})
    model, market = paired.get("model", {}), paired.get("market", {})
    comparable = bool(model.get("n")) and model.get("n") == market.get("n")
    delta = None
    if comparable:
        scores = [model.get("brier"), market.get("brier")]
        if any(
            not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1
            for x in scores
        ):
            raise ValueError("Malformed paired scoring evidence")
        delta = scores[0] - scores[1]
    blockers = [
        "No independently approved model promotion",
        "No untouched prospective evaluation with realistic execution, ROI and CLV evidence",
        "Commercial data/derived-output rights require confirmation",
        "Current uncertainty haircut is a policy setting, not a fitted confidence interval",
        "No trained player-prop/anytime-touchdown evidence in these game-score artifacts",
    ]
    if not paired.get("timestamp_verified_prices", 0):
        blockers.append("No decision-time-verified historical market prices")
    if not comparable:
        blockers.append("No paired market comparison sample")
    elif delta >= 0:
        blockers.append("Model does not beat market Brier score on the paired diagnostic sample")
    return {
        "model_version": report["model_version"],
        "source_checksum": report["source_checksum"],
        "status": "RESEARCH_ONLY",
        "approved_for_betting": False,
        "split_counts": report.get("split_counts", {}),
        "model": {
            name: {
                "brier": metric.get("brier"),
                "log_loss": metric.get("log_loss"),
                **calibration_summary(metric),
            }
            for name, metric in report.get("model", {}).items()
        },
        "paired_market_sample": model.get("n", 0) if comparable else 0,
        "brier_model_minus_market": delta,
        "brier_delta_interpretation": "Negative favors model; this alone never proves a profitable edge",
        "blockers": blockers,
    }
