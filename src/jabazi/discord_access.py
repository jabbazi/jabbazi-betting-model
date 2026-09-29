"""Explicit VIP-family policy shared by commands and permission repair."""
import re

VIP_NAMES = frozenset({
    "VIP", "JABBAZI VIP", "FOUNDING VIP", "TRIAL VIP",
    # Existing branded role from the production migration; not substring matching.
    "JABBAZI GURU VIP ACCESS",
})


def is_vip_name(name):
    normalized = re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()
    return normalized in VIP_NAMES


def vip_role_ids(roles, configured=()):
    approved = {str(value) for value in configured if str(value).isdigit()}
    return {
        str(role["id"]) for role in roles
        if str(role["id"]) in approved or is_vip_name(role.get("name"))
    }
