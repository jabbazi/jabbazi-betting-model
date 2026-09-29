"""Chronological research-only player opportunity models."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math

from jabazi.models.opportunity import OpportunityEstimate
from jabazi.research.prop_data import timestamp


def _matrix(rows, names, means=None, scales=None):
    import numpy as np
    raw=np.asarray([[float(row["features"][name]) for name in names] for row in rows],dtype=float)
    if means is None: means=raw.mean(axis=0)
    if scales is None: scales=raw.std(axis=0)
    scales=np.where(scales<1e-9,1.0,scales)
    return (raw-means)/scales,means,scales


def fit_opportunity_model(document, *, train_before, test_before, minimum_per_split=100):
    rows=document.get("rows") or []
    if not rows:
        raise ValueError("Opportunity dataset rows required")
    left,right=timestamp(train_before),timestamp(test_before)
    if left>=right:
        raise ValueError("Invalid opportunity split")
    unit=rows[0].get("opportunity_unit")
    if not unit or any(row.get("opportunity_unit")!=unit for row in rows):
        raise ValueError("One consistent opportunity unit required")
    usable=[]
    for row in rows:
        value=row.get("observed_opportunity")
        if isinstance(value,bool):
            raise ValueError("Invalid opportunity label")
        value=float(value)
        if not math.isfinite(value) or value<0:
            raise ValueError("Invalid opportunity label")
        decision=timestamp(row["prediction_at"])
        start=timestamp(row["starts_at"])
        available=timestamp(row["features_available_at"])
        result_at=timestamp(row["result_available_at"])
        if not available<=decision<start<=result_at:
            raise ValueError("Opportunity data leaks future information")
        usable.append((row,value,decision,result_at))
    train=[(r,y) for r,y,d,result_at in usable if d<left and result_at<left]
    calibration=[(r,y) for r,y,d,result_at in usable if left<=d<right and result_at<right]
    test=[(r,y) for r,y,d,_ in usable if d>=right]
    if min(len(train),len(calibration),len(test))<minimum_per_split:
        raise ValueError("Insufficient chronological opportunity data")
    names=sorted(train[0][0]["features"])
    if any(set(row["features"])!=set(names) for row,_ in train+calibration+test):
        raise ValueError("Inconsistent opportunity feature schema")
    import numpy as np
    from sklearn.linear_model import Ridge
    x,means,scales=_matrix([r for r,_ in train],names)
    y=np.asarray([y for _,y in train],dtype=float)
    model=Ridge(alpha=2.0).fit(x,y)
    xt,_,_=_matrix([r for r,_ in test],names,means,scales)
    yt=np.asarray([y for _,y in test],dtype=float)
    pred=np.maximum(0.0,model.predict(xt))
    residual=yt-pred
    rmse=float(np.sqrt(np.mean(residual**2)))
    mae=float(np.mean(np.abs(residual)))
    bias=float(np.mean(pred-yt))
    # Empirical 90% residual interval for honest workload uncertainty.
    low=float(np.quantile(residual,0.05))
    high=float(np.quantile(residual,0.95))
    manifest=document.get("manifest") or {}
    fingerprint=hashlib.sha256(json.dumps({
        "sport":manifest.get("sport"),"unit":unit,"features":names,
        "source_checksum":manifest.get("source_checksum"),
        "coef":model.coef_.tolist(),"intercept":float(model.intercept_),
    },sort_keys=True,separators=(",",":")).encode()).hexdigest()[:12]
    return {
        "artifact_type":"player_opportunity",
        "sport":manifest.get("sport"),
        "unit":unit,
        "provider":manifest.get("provider"),
        "source_checksum":manifest.get("source_checksum"),
        "feature_names":names,
        "scaler":{"mean":means.tolist(),"scale":scales.tolist()},
        "parameters":{"coef":model.coef_.tolist(),"intercept":float(model.intercept_)},
        "residual_interval_90":[low,high],
        "trained_at":datetime.now(UTC).isoformat(),
        "training_cutoff":max(timestamp(r["prediction_at"]) for r,_ in train).isoformat(),
        "stage":"VALIDATING",
        "approved_for_betting":False,
        "validation":{
            "train_n":len(train),"calibration_n":len(calibration),"test_n":len(test),
            "mae":mae,"rmse":rmse,"mean_bias":bias,
            "promotion_passed":False,
            "reason":"Historical workload fit only; frozen prospective validation required",
        },
        "model_version":f"{manifest.get('sport')}-{unit}-opp-0.1.0-{fingerprint}",
    }


def estimate_opportunity(artifact, features):
    names=artifact["feature_names"]
    if set(features)<set(names):
        raise ValueError("Missing opportunity features")
    vector=[]
    for value,mean,scale in zip(
        [float(features[name]) for name in names],
        artifact["scaler"]["mean"],
        artifact["scaler"]["scale"],
    ):
        if not math.isfinite(value):
            raise ValueError("Non-finite opportunity feature")
        vector.append((value-float(mean))/float(scale))
    mean=max(0.0,float(artifact["parameters"]["intercept"])+sum(
        x*float(w) for x,w in zip(vector,artifact["parameters"]["coef"])
    ))
    lo_resid,hi_resid=map(float,artifact["residual_interval_90"])
    return OpportunityEstimate(
        mean=mean,
        low=max(0.0,mean+lo_resid),
        high=max(0.0,mean+hi_resid),
        unit=artifact["unit"],
        model_version=artifact["model_version"],
        inputs_verified=False,
        approved_for_betting=False,
    )
