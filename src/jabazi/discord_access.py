"""Explicit VIP/staff role policy shared by commands and permission repair."""
import re

VIP_NAMES = frozenset({
    "VIP", "JABBAZI VIP", "FOUNDING VIP", "TRIAL VIP", "INNER CIRCLE",
    # Existing branded legacy role from the production migration.
    "JABBAZI GURU VIP ACCESS",
})
STAFF_NAMES = frozenset({"JABBAZI TEAM", "MODERATOR"})


def normalize_role_name(name):
    return re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper()).strip()


def is_vip_name(name):
    return normalize_role_name(name) in VIP_NAMES


def is_staff_name(name):
    return normalize_role_name(name) in STAFF_NAMES


def vip_role_ids(roles, configured=()):
    approved = {str(value) for value in configured if str(value).isdigit()}
    return {
        str(role["id"]) for role in roles
        if str(role["id"]) in approved or is_vip_name(role.get("name"))
    }
