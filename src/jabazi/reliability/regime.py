"""V5 regime-change diagnostics for workload/usage time series."""
from __future__ import annotations

import math
from statistics import fmean, pstdev


def detect_regime(values, *, recent=3, baseline=10, z_threshold=2.5, ratio_threshold=0.30):
    values=[float(v) for v in values if v is not None]
    if len(values)<recent+baseline:
        return {
            "detected":False,
            "reason":"INSUFFICIENT_HISTORY",
            "sample_count":len(values),
            "uncertainty_multiplier":1.0,
        }
    old=values[-(recent+baseline):-recent]
    new=values[-recent:]
    old_mean=fmean(old)
    new_mean=fmean(new)
    old_sd=pstdev(old) if len(old)>=2 else 0.0
    shift=new_mean-old_mean
    z=shift/old_sd if old_sd>1e-9 else None
    ratio=abs(shift)/max(abs(old_mean),1.0)
    detected=(z is not None and abs(z)>=z_threshold) or ratio>=ratio_threshold
    severity=min(1.0,max(
        abs(z)/5 if z is not None else 0.0,
        ratio,
    ))
    return {
        "detected":bool(detected),
        "baseline_mean":old_mean,
        "recent_mean":new_mean,
        "absolute_shift":shift,
        "z_shift":z,
        "relative_shift":ratio,
        "sample_count":len(values),
        "uncertainty_multiplier":1.0+0.5*severity if detected else 1.0,
        "reason":"USAGE_REGIME_CHANGE" if detected else "STABLE",
    }


def combine_regimes(series_by_name):
    diagnostics={
        name:detect_regime(values)
        for name,values in series_by_name.items()
        if isinstance(values,(list,tuple))
    }
    active=[name for name,row in diagnostics.items() if row["detected"]]
    return {
        "detected":bool(active),
        "active_series":active,
        "diagnostics":diagnostics,
        "uncertainty_multiplier":max(
            [row["uncertainty_multiplier"] for row in diagnostics.values()] or [1.0]
        ),
    }


def opportunity_proxy(features, threshold=0.25):
    """Low-cost live proxy when only rolling pregame features are available."""
    pairs=(
        ("mean3_opportunities","mean10_opportunities"),
        ("mean3_minutes","mean10_minutes"),
    )
    for short,long in pairs:
        if short in features and long in features:
            recent=float(features[short]); base=float(features[long])
            if not all(math.isfinite(v) for v in (recent,base)):
                continue
            relative=abs(recent-base)/max(abs(base),1.0)
            return {
                "detected":relative>=threshold,
                "recent":recent,
                "baseline":base,
                "relative_shift":relative,
                "reason":"ROLLING_OPPORTUNITY_SHIFT" if relative>=threshold else "STABLE",
                "uncertainty_multiplier":1.0+min(0.5,relative/2) if relative>=threshold else 1.0,
            }
    return {
        "detected":False,
        "reason":"OPPORTUNITY_PROXY_UNAVAILABLE",
        "uncertainty_multiplier":1.0,
    }
