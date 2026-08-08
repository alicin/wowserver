"""WotLK lookup tables and the formatters the templates use.

These are the numbers the client itself uses — race and class ids as stored in
acore_characters.characters, Blizzard's class colours, AzerothCore's security levels.
They are constants of the 3.3.5a data, not configuration, so they live in code.
"""

from __future__ import annotations

from datetime import datetime, timezone

# ChrRaces.dbc ids present in 3.3.5a. 9 (Goblin) exists in the DBC but is not playable.
RACES: dict[int, str] = {
    1: "Human",
    2: "Orc",
    3: "Dwarf",
    4: "Night Elf",
    5: "Undead",
    6: "Tauren",
    7: "Gnome",
    8: "Troll",
    10: "Blood Elf",
    11: "Draenei",
}

ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})
HORDE_RACES = frozenset({2, 5, 6, 8, 10})

# ChrClasses.dbc ids. 10 is unused in 3.3.5a.
CLASSES: dict[int, str] = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    6: "Death Knight",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    11: "Druid",
}

# Blizzard's RAID_CLASS_COLORS, with two adjustments for a dark page. Death Knight
# (#C41F3B) and Shaman (#0070DE) are both too dark to read as body text on this
# background; they are lifted in luminance with the hue kept, so a player still reads
# "that is the red one" and "that is the blue one". The other eight are canonical.
CLASS_COLORS: dict[int, str] = {
    1: "#C79C6E",  # Warrior  — canonical
    2: "#F58CBA",  # Paladin  — canonical
    3: "#ABD473",  # Hunter   — canonical
    4: "#FFF569",  # Rogue    — canonical
    5: "#FFFFFF",  # Priest   — canonical
    6: "#E24A60",  # Death Knight — lifted from #C41F3B
    7: "#3D9BFF",  # Shaman   — lifted from #0070DE
    8: "#69CCF0",  # Mage     — canonical
    9: "#9482C9",  # Warlock  — canonical
    11: "#FF7D0A",  # Druid   — canonical
}

FALLBACK_CLASS_COLOR = "#C7B99A"

# AzerothCore AccountTypes (Common.h): SEC_PLAYER .. SEC_CONSOLE.
GM_LEVELS: dict[int, str] = {
    0: "Player",
    1: "Moderator",
    2: "Game Master",
    3: "Administrator",
    4: "Console",
}

EXPANSIONS: dict[int, str] = {
    0: "Classic",
    1: "The Burning Crusade",
    2: "Wrath of the Lich King",
}


def class_color(class_id: int) -> str:
    return CLASS_COLORS.get(class_id, FALLBACK_CLASS_COLOR)


def faction_of(race_id: int) -> str:
    if race_id in ALLIANCE_RACES:
        return "Alliance"
    if race_id in HORDE_RACES:
        return "Horde"
    return "Neutral"


def played(seconds: int) -> str:
    """Seconds -> the game's own /played shape: '4d 12h', '3h 20m', '14m'."""
    if seconds <= 0:
        return "never played"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def filesize(num_bytes: int) -> str:
    """Binary units, because that is what a download client will show them."""
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"  # unreachable, kept so every path returns a str


def when(value: datetime | None) -> str:
    """A timestamp a person can read. MySQL hands these back naive and in UTC."""
    if value is None:
        return "never"
    return value.strftime("%d %b %Y, %H:%M")


def age(value: datetime | None) -> str:
    """'3 days ago'. Used next to last_login, where recency is the interesting part."""
    if value is None:
        return ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = now - value
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    if seconds < 86400 * 30:
        return f"{seconds // 86400} days ago"
    return ""
