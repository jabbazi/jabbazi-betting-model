"""Conservative shared-thesis labels and actual-dollar exposure; no fake coefficients."""

from decimal import Decimal


def tags(card, participant_team=None):
    result = {f"game:{card.event_id}"}
    teams = card.event.split(" @ ")
    if len(teams) != 2:
        return frozenset(result)
    team = (
        card.selection
        if card.selection in teams
        else card.participant
        if card.participant in teams
        else participant_team
    )
    if team in teams:
        result.add(f"team:{card.event_id}:{team}")
        if card.selection in teams or card.selection.lower() == "over":
            result.add(f"offense:{card.event_id}:{team}")
    if card.market in ("totals", "alternate_totals"):
        result.add(f"scoring:{card.event_id}:{card.selection.lower()}")
        if card.selection.lower() == "over":
            result.update(f"offense:{card.event_id}:{t}" for t in teams)
    return frozenset(result)


def graph(positions):
    nodes = {}
    edges = []
    total = Decimal(0)
    scanner = Decimal(0)
    for i, p in enumerate(positions):
        if not p.amount.is_finite() or p.amount < 0:
            raise ValueError("Invalid cash amount")
        total += p.amount
        if p.origin == "scanner":
            scanner += p.amount
        ticket = f"ticket:{i}"
        nodes[ticket] = {"kind": "ticket", "cash_dollars": str(p.amount), "origin": p.origin}
        for node, kind in (
            [(f"game:{p.event}", "game")]
            + [(f"player:{v}", "player") for v in p.players]
            + [(v, "thesis") for v in p.theses]
        ):
            current = nodes.setdefault(node, {"kind": kind, "cash_dollars": "0"})
            current["cash_dollars"] = str(Decimal(current["cash_dollars"]) + p.amount)
            edges.append({"from": node, "to": ticket})
    return {
        "total_cash_dollars": str(total),
        "scanner_cash_dollars": str(scanner),
        "user_choice_cash_dollars": str(total - scanner),
        "nodes": nodes,
        "edges": edges,
        "note": "Overlapping node totals are not additive. Both origins count toward cash risk.",
    }
