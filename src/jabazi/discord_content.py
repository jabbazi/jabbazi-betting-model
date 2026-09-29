"""Standardized premium Discord content renderers."""
from __future__ import annotations

from decimal import Decimal
import os

STATUS_COLORS={
    "BET NOW":0x2ECC71,
    "WATCH":0xF1C40F,
    "PRICE CHECK":0x3498DB,
    "PASS":0x95A5A6,
    "QUARANTINED":0xE74C3C,
}


def american(decimal):
    d=float(decimal)
    return round((d-1)*100) if d>=2 else round(-100/(d-1))


def official_pick_embed(payload):
    reliability=payload.get("reliability") or {}
    decision=str(payload.get("decision") or "").replace("_"," ")
    stake=Decimal(str(payload.get("stake") or 0))
    if decision!="BET NOW" or stake<=0 or not reliability.get("model_can_influence_cash"):
        return None
    price=payload["price"]
    model=payload.get("model_probability")
    market=price.get("consensus_probability")
    edge=payload.get("probability_edge")
    unit=Decimal(os.getenv("JABAZI_UNIT_SIZE", "30"))
    units=stake/unit
    fields=[
        {"name":"Selection","value":f"{price.get('selection')} {price.get('line') or ''}".strip(),"inline":True},
        {"name":"Sportsbook","value":f"{price.get('best_book')} {american(price.get('best_decimal')):+d}","inline":True},
        {"name":"Stake","value":f"{units:.2f}u • ${stake:.2f}","inline":True},
        {"name":"Model","value":"—" if model is None else f"{float(model):.1%}","inline":True},
        {"name":"Market no-vig","value":"—" if market is None else f"{float(market):.1%}","inline":True},
        {"name":"Edge","value":"—" if edge is None else f"{float(edge):.1%}","inline":True},
        {"name":"Model version","value":str(payload.get("model_version") or "—")[:1024],"inline":False},
        {"name":"Risk","value":str(payload.get("reason") or "Review current price and data health.")[:1024],"inline":False},
    ]
    return {
        "title":f"🟢 JABBAZI MAIN CARD • {price.get('event')}",
        "color":STATUS_COLORS["BET NOW"],"fields":fields,
        "footer":{"text":"Official recommendation • price-sensitive • no wager is guaranteed"},
    }


def best_two_embed(candidate):
    if not candidate or not candidate.get("legs"):
        return None
    status=candidate.get("status","WATCH")
    legs=[]
    for i,leg in enumerate(candidate["legs"],1):
        label=leg.get("participant") or leg.get("selection")
        legs.append(f"{i}. {leg.get('event')} — {label} {leg.get('line') or ''}".strip())
    fields=[
        {"name":"Exact legs","value":"\n".join(legs)[:1024],"inline":False},
        {"name":"Status","value":status,"inline":True},
        {"name":"Joint method","value":str(candidate.get("method") or "—"),"inline":True},
        {"name":"Requested ceiling","value":f"{candidate.get('requested_stake_units','2')}u","inline":True},
        {"name":"Current recommendation","value":str(candidate.get("recommended_stake_units") or "PRICE CHECK"),"inline":True},
        {"name":"Why","value":"; ".join(candidate.get("reasons") or [])[:1024],"inline":False},
    ]
    return {
        "title":"🟣 JABBAZI BEST-2 RESEARCH",
        "color":STATUS_COLORS.get(status,0x8B35E8),"fields":fields,
        "footer":{"text":"External sheets are discovery evidence only • exact combined quote required"},
    }


def scanner_status_embed(text):
    healthy="RUNNING" in text or "READY" in text
    return {
        "title":"JABBAZI SCANNER STATUS",
        "description":text[:3900],
        "color":0x2ECC71 if healthy else 0xE67E22,
    }


def performance_text(report):
    lines=["📊 **JABBAZI RESULTS / TRANSPARENCY**", report.get("provenance","OWNER_REPORTED_LEDGER")]
    groups=report.get("groups") or []
    if not groups:
        lines.append("No settled official ledger positions yet.")
    for group in groups[:25]:
        settled=group.get("settled",0)
        if not settled:
            continue
        roi=group.get("roi")
        roi_text="—" if roi is None else f"{float(roi):+.1%}"
        lines.append(
            f"**{group.get('sport')} • {group.get('market')} • {group.get('origin')}** "
            f"{group.get('wins',0)}-{group.get('losses',0)} "
            f"({group.get('pushes_or_voids',0)} push/void) • "
            f"{float(group.get('profit_units',0)):+.2f}u • ROI {roi_text}"
        )
    lines.append("Results come from the owner-reported ledger; corrections remain auditable.")
    return "\n".join(lines)[:3900]
