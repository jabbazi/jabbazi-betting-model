"""Canonical NBA franchise identities; exclude exhibitions and All-Star teams."""

NBA_TEAMS = frozenset({
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
    "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
    "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
    "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
    "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
    "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors",
    "Utah Jazz", "Washington Wizards",
})
NBA_ALIASES = {"LA Clippers": "Los Angeles Clippers"}


def canonical_team(name):
    name = str(name or "").strip()
    name = NBA_ALIASES.get(name, name)
    return name if name in NBA_TEAMS else None
