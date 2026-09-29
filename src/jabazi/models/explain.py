"""Non-causal feature attribution for linear player-distribution predictors."""
from __future__ import annotations

import math


def linear_feature_contributions(artifact, features, top_n=5):
    names=artifact.get("feature_names") or []
    scaler=artifact.get("scaler") or {}
    params=artifact.get("parameters") or {}
    coef=params.get("coef")
    if not names or not isinstance(coef,list) or len(coef)!=len(names):
        return []
    means=scaler.get("mean") or []
    scales=scaler.get("scale") or []
    if len(means)!=len(names) or len(scales)!=len(names):
        return []
    rows=[]
    for name,weight,mean,scale in zip(names,coef,means,scales):
        try:
            value=float(features[name]); weight=float(weight)
            mean=float(mean); scale=float(scale)
        except (KeyError,TypeError,ValueError):
            return []
        if not all(math.isfinite(x) for x in (value,weight,mean,scale)) or abs(scale)<1e-12:
            return []
        standardized=(value-mean)/scale
        contribution=standardized*weight
        rows.append({
            "feature":name,
            "standardized_value":standardized,
            "linear_predictor_contribution":contribution,
            "direction":"higher" if contribution>0 else "lower" if contribution<0 else "neutral",
        })
    rows.sort(key=lambda row:abs(row["linear_predictor_contribution"]),reverse=True)
    return rows[:max(1,min(int(top_n),10))]


def explanation(artifact, features, top_n=5):
    rows=linear_feature_contributions(artifact,features,top_n)
    return {
        "method":"standardized_linear_predictor_contribution",
        "causal":False,
        "drivers":rows,
        "note":"Associational model contribution only; not a causal explanation.",
    }
