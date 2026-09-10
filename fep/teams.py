"""The 32 NFL teams: how ESPN abbreviates them, and what colour they are.

The dashboard used to abbreviate a team by taking the first three letters of
its nickname, which gave COM for the Commanders, STE for the Steelers and 49E
for the 49ers. None of those is what a scoreboard says. This module is the one
place that knows the real answer, so every surface says the same thing.

Two facts per team:

    abbr    ESPN's scoreboard abbreviation. The season file already stores it
            per game (`game["opponent"]`), so this table matches that source
            rather than inventing a second convention.
    color   The team colour to fill a chip with. White text sits on top of it,
            so a colour is only listed here if white clears WCAG AA (4.5:1)
            against it. That rules out several teams' best-known colour --
            Steelers gold, Saints gold, Bengals orange, Chargers powder blue --
            and each of those falls back to the other half of the team's own
            primary pair rather than to a tint nobody would recognise.
"""

from __future__ import annotations

import re

# nickname -> (ESPN abbreviation, city/full name, white-safe primary colour)
TEAMS = {
    "Cardinals":  ("ARI", "Arizona Cardinals",       "#97233F"),
    "Falcons":    ("ATL", "Atlanta Falcons",         "#A71930"),
    "Ravens":     ("BAL", "Baltimore Ravens",        "#241773"),
    "Bills":      ("BUF", "Buffalo Bills",           "#00338D"),
    # Process blue is 4.0:1 against white, so the chip takes the black.
    "Panthers":   ("CAR", "Carolina Panthers",       "#101820"),
    "Bears":      ("CHI", "Chicago Bears",           "#0B162A"),
    # Bengal orange is 3.4:1 against white.
    "Bengals":    ("CIN", "Cincinnati Bengals",      "#000000"),
    "Browns":     ("CLE", "Cleveland Browns",        "#311D00"),
    "Cowboys":    ("DAL", "Dallas Cowboys",          "#003594"),
    # Broncos orange is 3.4:1 against white.
    "Broncos":    ("DEN", "Denver Broncos",          "#0C2340"),
    "Lions":      ("DET", "Detroit Lions",           "#0076B6"),
    "Packers":    ("GB",  "Green Bay Packers",       "#203731"),
    "Texans":     ("HOU", "Houston Texans",          "#03202F"),
    "Colts":      ("IND", "Indianapolis Colts",      "#002C5F"),
    "Jaguars":    ("JAX", "Jacksonville Jaguars",    "#006778"),
    "Chiefs":     ("KC",  "Kansas City Chiefs",      "#E31837"),
    "Raiders":    ("LV",  "Las Vegas Raiders",       "#000000"),
    # Powder blue is 4.3:1 against white.
    "Chargers":   ("LAC", "Los Angeles Chargers",    "#002A5E"),
    "Rams":       ("LAR", "Los Angeles Rams",        "#003594"),
    # Aqua is 4.0:1 against white.
    "Dolphins":   ("MIA", "Miami Dolphins",          "#005778"),
    "Vikings":    ("MIN", "Minnesota Vikings",       "#4F2683"),
    "Patriots":   ("NE",  "New England Patriots",    "#002244"),
    # Old gold is 1.9:1 against white.
    "Saints":     ("NO",  "New Orleans Saints",      "#101820"),
    "Giants":     ("NYG", "New York Giants",         "#0B2265"),
    "Jets":       ("NYJ", "New York Jets",           "#125740"),
    "Eagles":     ("PHI", "Philadelphia Eagles",     "#004C54"),
    # Steelers gold is 1.8:1 against white.
    "Steelers":   ("PIT", "Pittsburgh Steelers",     "#101820"),
    "49ers":      ("SF",  "San Francisco 49ers",     "#AA0000"),
    "Seahawks":   ("SEA", "Seattle Seahawks",        "#002244"),
    "Buccaneers": ("TB",  "Tampa Bay Buccaneers",    "#D50A0A"),
    "Titans":     ("TEN", "Tennessee Titans",        "#0C2340"),
    "Commanders": ("WSH", "Washington Commanders",   "#5A1414"),
}

# White text is the one thing every colour above is chosen to carry, so the
# chip's foreground is a constant rather than a per-team field.
INK = "#FFFFFF"

# What a chip falls back to when a nickname is not one of the 32. A team that
# renames itself mid-season should look plainly unstyled rather than silently
# borrowing another team's colour.
UNKNOWN_COLOR = "#22282C"

_BY_ABBR = {abbr: nickname for nickname, (abbr, _, _) in TEAMS.items()}


def nickname(name: str) -> str:
    """The dictionary key for whatever form of a team's name we were handed.

    Accepts the nickname ("Commanders"), the abbreviation ("WSH"), or the full
    name ("Washington Commanders"), because the three arrive from three
    different places: labels, the season file, and hand-written copy.
    """
    if not name:
        return ""
    text = name.strip()
    if text in TEAMS:
        return text
    if text.upper() in _BY_ABBR:
        return _BY_ABBR[text.upper()]
    for key, (_, full, _) in TEAMS.items():
        if full.lower() == text.lower():
            return key
    return ""


def abbr(name: str) -> str:
    """"Commanders" -> "WSH". Unknown names keep their first three letters."""
    key = nickname(name)
    if key:
        return TEAMS[key][0]
    return name.strip()[:3].upper()


def color(name: str) -> str:
    """The chip fill for a team, or the neutral fill for an unknown one."""
    key = nickname(name)
    return TEAMS[key][2] if key else UNKNOWN_COLOR


def from_label(label: str) -> str:
    """"vs. Jaguars (London)" -> "Jaguars".

    Same shape of label `cms.split_label` takes apart, reduced to the one piece
    a chip needs. Duplicated deliberately: cms imports nothing from here, and a
    chip should not have to pull in the CMS layer to name a team.
    """
    cleaned = re.sub(r"\([^)]*\)", "", label or "")
    return re.sub(r"^\s*(vs\.?|@|at)\s*", "", cleaned, flags=re.I).strip()


def payload() -> dict:
    """The table in the shape a page consumes: nickname -> abbr, color, name."""
    return {nick: {"abbr": ab, "color": col, "name": full}
            for nick, (ab, full, col) in TEAMS.items()}
