"""Evidence-based postmortem classification.

Classification is descriptive and conservative. It never rewrites a frozen prediction
and never infers a causal failure without explicit evidence.
"""
from __future__ import annotations

ERRORS={
    "NORMAL_VARIANCE","BAD_PROBABILITY","OPPORTUNITY_MISS","INJURY_ROLE_MISS",
    "STALE_DATA","MARKET_MOVED","MODEL_MISSPECIFICATION","REGIME_CHANGE",
    "EXECUTION_ERROR","IDENTITY_ERROR","UNKNOWN",
}


def classify(*, prediction, result, closing=None, execution=None, context=None):
    context=context or {}
    execution=execution or {}
    reasons=[]
    if context.get("identity_failure"):
        return {"classification":"IDENTITY_ERROR","reasons":["Verified identity mismatch"]}
    if context.get("stale_data"):
        return {"classification":"STALE_DATA","reasons":["Decision used stale or late data"]}
    if execution.get("wrong_market") or execution.get("wrong_price"):
        return {"classification":"EXECUTION_ERROR","reasons":["Placed/executed market differed from frozen decision"]}
    if context.get("injury_role_change_after_prediction") and not context.get("known_before_prediction"):
        return {"classification":"INJURY_ROLE_MISS","reasons":["Material role/injury state changed after freeze"]}
    if context.get("opportunity_error") is not None and abs(float(context["opportunity_error"])) >= float(context.get("opportunity_error_threshold",0.20)):
        return {"classification":"OPPORTUNITY_MISS","reasons":["Observed opportunity materially missed forecast"]}
    if context.get("regime_change"):
        return {"classification":"REGIME_CHANGE","reasons":["Verified structural regime changed"]}
    p=prediction.get("probability")
    y=result.get("outcome")
    if p is None or y not in (0,1):
        return {"classification":"UNKNOWN","reasons":["Insufficient settled probability evidence"]}
    p=float(p)
    if closing and closing.get("consensus_no_vig_probability") is not None:
        close=float(closing["consensus_no_vig_probability"])
        if abs(close-p)>=float(context.get("market_move_threshold",0.08)):
            reasons.append("Closing market materially disagreed with frozen probability")
            if context.get("new_information_before_close"):
                return {"classification":"MARKET_MOVED","reasons":reasons}
    if context.get("repeated_segment_miscalibration"):
        return {"classification":"BAD_PROBABILITY","reasons":["Repeated segment calibration failure"]}
    if context.get("model_specification_failure"):
        return {"classification":"MODEL_MISSPECIFICATION","reasons":["Repeated structural residual pattern"]}
    return {
        "classification":"NORMAL_VARIANCE",
        "reasons":[
            "Settled outcome is compatible with a probabilistic forecast; no verified systematic failure evidence"
        ],
    }


def summarize(postmortems, minimum=20):
    counts={}
    for row in postmortems:
        label=row.get("classification","UNKNOWN")
        if label not in ERRORS:
            label="UNKNOWN"
        counts[label]=counts.get(label,0)+1
    n=sum(counts.values())
    systematic=sum(counts.get(x,0) for x in (
        "BAD_PROBABILITY","OPPORTUNITY_MISS","MODEL_MISSPECIFICATION",
        "REGIME_CHANGE","IDENTITY_ERROR","STALE_DATA","EXECUTION_ERROR"
    ))
    return {
        "n":n,
        "counts":counts,
        "systematic_failure_rate": systematic/n if n else None,
        "enough_for_pattern_review": n>=minimum,
    }
