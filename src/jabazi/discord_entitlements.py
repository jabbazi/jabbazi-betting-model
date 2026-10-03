"""Auditable Discord VIP entitlement state."""
from __future__ import annotations

from datetime import UTC, datetime
from .persistence.store import digest

ACTIVE={"active","trialing","lifetime"}


def set_entitlement(store, *, member_id, status, plan, provider, provider_ref, expires_at=None, now=None):
    now=now or datetime.now(UTC)
    if not str(member_id).isdigit() or int(member_id)<=0:
        raise ValueError("Valid Discord member ID required")
    if status not in ACTIVE|{"canceled","expired","past_due"}:
        raise ValueError("Invalid entitlement status")
    if not plan or not provider or not provider_ref:
        raise ValueError("Entitlement provenance required")
    expiry=None
    if expires_at:
        expiry=datetime.fromisoformat(str(expires_at).replace("Z","+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Entitlement expiry must be timezone-aware")
        expiry=expiry.astimezone(UTC).isoformat()
    payload={
        "member_id":str(member_id),"status":status,"plan":plan,
        "provider":provider,"provider_ref":provider_ref,
        "expires_at":expiry,"recorded_at":now.isoformat(),
    }
    key=digest(["discord_entitlement",member_id,status,plan,provider,provider_ref,expiry,now.isoformat()])
    store.append("discord_entitlement",str(member_id),payload,key)
    return key


def latest_entitlement(store, member_id, *, now=None):
    now=now or datetime.now(UTC)
    rows=store.list_records("discord_entitlement",1,entity=str(member_id))
    if not rows:
        return None
    p=rows[0]["payload"]
    active=p.get("status") in ACTIVE
    expiry=p.get("expires_at")
    if expiry:
        dt=datetime.fromisoformat(expiry)
        active=active and dt>now
    return {**p,"active":bool(active)}


def active_members(store, *, limit=1000, now=None):
    now=now or datetime.now(UTC)
    rows=store.list_records("discord_entitlement",limit)
    latest={}
    for row in rows:
        p=row["payload"]
        latest.setdefault(str(p["member_id"]),p)
    result=set()
    for member,p in latest.items():
        active=p.get("status") in ACTIVE
        if p.get("expires_at"):
            active=active and datetime.fromisoformat(p["expires_at"])>now
        if active:
            result.add(int(member))
    return result
