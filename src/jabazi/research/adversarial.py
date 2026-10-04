"""Immutable AI/analyst adversarial review contract.

This stores sourced research; it does not browse, predict, place, or promote wagers.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from jabazi.persistence.store import digest

OUTCOMES={"SURVIVES_CHALLENGE","WATCH","PASS","QUARANTINED"}
TIERS={"OFFICIAL":0,"RELIABLE_DATA":1,"BEAT_REPORTER":2,"MAJOR_NEWS":3,"ANALYTICAL":4,"OTHER":5}


def _aware(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Aware adversarial timestamp required")
    return dt.astimezone(UTC)


def validate_review(payload, now=None):
    now=now or datetime.now(UTC)
    required=("sport","event_id","starts_at","market","selection","reviewed_at","outcome","sources")
    if any(payload.get(name) in (None,"") for name in required):
        raise ValueError("Adversarial review identity is incomplete")
    start=_aware(payload["starts_at"]); reviewed=_aware(payload["reviewed_at"])
    if reviewed>now+timedelta(minutes=5) or reviewed>=start:
        raise ValueError("Adversarial review must be pregame and non-future")
    if payload["outcome"] not in OUTCOMES:
        raise ValueError("Invalid adversarial outcome")
    sources=payload["sources"]
    if not isinstance(sources,list) or not sources:
        raise ValueError("At least one sourced finding is required")
    normalized=[]
    domains=set()
    for source in sources:
        if not isinstance(source,dict):
            raise ValueError("Invalid adversarial source")
        url=str(source.get("url") or "")
        domain=urlparse(url).netloc.lower()
        tier=str(source.get("tier") or "")
        observed=_aware(source.get("observed_at"))
        if not domain or tier not in TIERS or observed>reviewed:
            raise ValueError("Invalid source provenance")
        finding=str(source.get("finding") or "").strip()
        if not finding:
            raise ValueError("Source finding required")
        domains.add(domain)
        normalized.append({
            "url":url,"domain":domain,"tier":tier,
            "observed_at":observed.isoformat(),"finding":finding[:1000],
            "contrary":bool(source.get("contrary")),
        })
    # A clean challenge result needs multiple independent sources unless one is
    # official. WATCH/PASS/QUARANTINED may be triggered by a single risk source.
    if payload["outcome"]=="SURVIVES_CHALLENGE":
        if not any(s["tier"]=="OFFICIAL" for s in normalized) and len(domains)<2:
            raise ValueError("Survives-challenge requires independent corroboration")
    return {
        "sport":payload["sport"],
        "event_id":str(payload["event_id"]),
        "starts_at":start.isoformat(),
        "market":payload["market"],
        "selection":payload["selection"],
        "participant":payload.get("participant"),
        "line":payload.get("line"),
        "reviewed_at":reviewed.isoformat(),
        "outcome":payload["outcome"],
        "thesis":str(payload.get("thesis") or "")[:2000],
        "contrary_findings":[str(x)[:1000] for x in payload.get("contrary_findings",[])],
        "sources":normalized,
        "cash_influence":False,
        "research_only":True,
    }


def freeze_review(store,payload,now=None):
    review=validate_review(payload,now)
    identity="|".join([
        review["sport"],review["event_id"],review["market"],review["selection"],
        str(review.get("participant") or ""),str(review.get("line")),
    ])
    key=digest(["adversarial_review",identity,review["reviewed_at"],review["sources"]])
    store.append("adversarial_review",identity,review,key)
    return key


def latest_review(store,card,now=None,max_age_hours=6):
    now=now or datetime.now(UTC)
    identity="|".join([
        card.sport,card.event_id,card.market,card.selection,
        str(card.participant or ""),str(card.line),
    ])
    rows=store.list_records("adversarial_review",20,entity=identity)
    for row in rows:
        review=row["payload"]
        try:
            reviewed=_aware(review["reviewed_at"])
            starts=_aware(review["starts_at"])
        except (ValueError,KeyError,TypeError):
            continue
        if starts!=card.starts_at.astimezone(UTC):
            continue
        if timedelta(0)<=now-reviewed<=timedelta(hours=max_age_hours):
            return review
    return None
