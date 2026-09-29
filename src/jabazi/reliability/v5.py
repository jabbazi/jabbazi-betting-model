"""V5 calibration segmentation and automatic evidence kill switches."""
from __future__ import annotations

from jabazi.research.prospective import calibration_table


def segment_key(row):
    p=float(row["probability"])
    market=float(row["market_probability"])
    gap=abs(p-market)
    return (
        row["sport"],
        row["bucket"],
        "favorite" if market>=0.5 else "underdog",
        "edge_0_2" if gap<0.02 else "edge_2_5" if gap<0.05 else "edge_5_plus",
    )


def segmented_calibration(rows):
    groups={}
    for row in rows:
        y=row.get("outcome")
        if y not in (0,1):
            continue
        groups.setdefault(segment_key(row),[]).append((float(row["probability"]),int(y)))
    output=[]
    for key,pairs in sorted(groups.items()):
        table=calibration_table(pairs)
        ece=sum(
            bucket["n"]/len(pairs)*abs(bucket["mean_probability"]-bucket["observed_hit_rate"])
            for bucket in table
        ) if pairs else None
        output.append({
            "sport":key[0],"bucket":key[1],"market_side":key[2],"edge_band":key[3],
            "n":len(pairs),"ece":ece,"calibration":table,
        })
    return output


def kill_switch(*, data_health, drift, calibration_ece, recent_brier_delta, identity_failures,
                provider_failures=0, sample_count=0):
    """Return the strongest fail-closed state supported by current evidence."""
    reasons=[]
    if identity_failures:
        reasons.append("IDENTITY_FAILURE")
    if not data_health:
        reasons.append("DATA_UNHEALTHY")
    if drift:
        reasons.append("FEATURE_DRIFT")
    if provider_failures>=3:
        reasons.append("REPEATED_PROVIDER_FAILURE")
    if calibration_ece is not None and sample_count>=100 and calibration_ece>0.08:
        reasons.append("CALIBRATION_DETERIORATION")
    if recent_brier_delta is not None and sample_count>=100 and recent_brier_delta>0.02:
        reasons.append("MARKET_RELATIVE_BRIER_DETERIORATION")
    if identity_failures or not data_health:
        state="QUARANTINED"
    elif reasons:
        state="WATCH"
    else:
        state="NORMAL"
    return {"state":state,"reasons":reasons,"cash_influence":state=="NORMAL"}
