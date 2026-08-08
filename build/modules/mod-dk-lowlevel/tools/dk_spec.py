#!/usr/bin/env python3
"""THE source of truth for low-level Death Knight progression.

Nothing in this feature may be edited anywhere else. `dkspells.py` reads this file and emits,
from it alone:

    data/sql/db-world/base/2026_08_08_00_dk_lowlevel_class_stats.sql   (A1)
    data/sql/db-world/base/2026_08_08_01_dk_lowlevel_spells.sql        (A3 A4 A5 A6)
    data/sql/db-world/base/2026_08_08_02_dk_lowlevel_createinfo.sql    (A7 A8 A9 A10)
    src/dk_progression.h                                               (compiled table)
    <out>/dbc/{Spell,SkillLineAbility,CharStartOutfit}.dbc              (A11 A12 A13)
    <out>/patch-Z.MPQ                                                   (A14)

WHY ONE GENERATOR AND NOT TWO HAND-MAINTAINED FILES (DESIGN.md 8.3)
-------------------------------------------------------------------
The server computes damage from `spell_dbc`. The client renders the tooltip from
`Spell.dbc` inside the patch MPQ. The server CANNOT render a tooltip -- SpellEntryfmt marks
every Description_Lang_* column FT_NA and DBCDatabaseLoader throws them away, and SpellInfo
has no Description member at all. So the two copies are physically separate and must be kept
identical by construction, not by discipline. Generator invariant #4 compares them cell by
cell and fails the run on any difference. That check is the entire reason this design was
picked over "just script the damage server-side".

WHY CLONE INSTEAD OF AUTHOR (DESIGN.md 3.3)
-------------------------------------------
A custom rank is a byte-for-byte memcpy of a stock record with a handful of named cells
overridden. Icy Touch's DK-ness lives in SpellClassSet=15 / SpellClassMask_1=2 (matched by
Improved Icy Touch, Killing Machine, Deathchill, Rime, ...) , its Frost Fever application
lives in Effect_2=64 + EffectTriggerSpell_2=55095, and its Sigil of the Frozen Conscience
interaction lives in SpellIconID=2721 (SpellInfoCorrections.cpp:5306). None of that is
referenced by spell ID anywhere in the core. Clone and they all survive; author and they all
quietly do not.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------------- paths --

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TOOLS_DIR)                       # build/modules/mod-dk-lowlevel
REPO_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", "..", ".."))

SQL_DIR = os.path.join(MODULE_DIR, "data", "sql", "db-world", "base")
HEADER_PATH = os.path.join(MODULE_DIR, "src", "dk_progression.h")

# `.work/` is gitignored: a 49 MB DBC and a 4.6 MB archive are build artefacts, not source
# (DESIGN.md 2, reason 3). The SQL and the header ARE source and are committed.
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".work", "out")
DEFAULT_DBC_IN = "/srv/wow/data/dbc"
DEFAULT_CLIENT_DATA = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"

# UpdateFetcher tracks migrations by BARE FILENAME plus a SHA1 of the contents
# (UpdateFetcher.cpp:326-370) and LOG_FATALs on a duplicate filename anywhere across the core
# and all 18 modules (:96-100). Hence the dated, module-qualified prefix. A changed file is
# re-applied IN FULL, which is why every statement these emit is DELETE-then-INSERT per key.
SQL_FILES = {
    "class_stats": "2026_08_08_00_dk_lowlevel_class_stats.sql",
    "spells":      "2026_08_08_01_dk_lowlevel_spells.sql",
    "createinfo":  "2026_08_08_02_dk_lowlevel_createinfo.sql",
}

# `--slot` picks where the patch archive is installed in the client. Data/patch-Z.MPQ is the
# decision (DESIGN.md 0.1); the enUS slot is the documented fallback if the client turns out
# not to read the locale-agnostic band for a file Blizzard only ever shipped in the locale
# chain (DESIGN.md 8.4, 9.1 item 4).
MPQ_SLOTS = {
    "Z": "patch-Z.MPQ",
    "enUS-4": os.path.join("enUS", "patch-enUS-4.MPQ"),
}
DEFAULT_MPQ_SLOT = "Z"

# ----------------------------------------------------------------------------- id policy --

# Stock Spell.dbc tops out at 80864 and the file is strictly ascending; appending above the
# max keeps it that way. AzerothCore's own serverside spells start at 100001, so 90000-99999
# is a clear band between the two. The real ceiling is not a DBC limit at all: it is the
# 24-bit action-button packing, MAX_ACTION_BUTTON_ACTION_VALUE = 0x01000000 (Player.h:235),
# enforced at Player.cpp:5756 -- a spell above that cannot go on an action bar.
SPELL_ID_MIN = 80865          # inclusive, must be > stock Spell.dbc max ID
SPELL_ID_MAX = 100000         # exclusive, AC's serverside band begins at 100001
SPELL_ID_BASE = 90000

# Stock SkillLineAbility.dbc max ID is 21980 -- parsed, not the 20683 one recon report claimed
# (DESIGN.md 0.2). 21000+ would have collided.
SLA_ID_MIN = 22000
SLA_ID_BASE = 22000

# 20 IDs per stock ability, block index fixed now so IDs never move when more abilities ship.
# spell id = SPELL_ID_BASE + 20*block + rank_index ; sla id = SLA_ID_BASE + (spell - 90000).
IDS_PER_ABILITY = 20
ABILITY_BLOCKS = {
    "icy_touch":      0,      # 90000-90019   stock rank 1 = 45477   <- THE SLICE
    "plague_strike":  1,      # 90020-90039   45462
    "blood_strike":   2,      # 90040-90059   45902
    "death_coil":     3,      # 90060-90079   47541
    "death_strike":   4,      # 90080-90099   49998
    "blood_presence": 5,      # 90100-90119   48266
}


def spell_id_for(ability_key, rank_index):
    return SPELL_ID_BASE + IDS_PER_ABILITY * ABILITY_BLOCKS[ability_key] + rank_index


def sla_id_for(spell_id):
    return SLA_ID_BASE + (spell_id - SPELL_ID_BASE)


# ------------------------------------------------------------------ the progression spec --

@dataclass(frozen=True)
class CustomRank:
    """One generated Spell.dbc record and its SkillLineAbility row."""

    spell_id: int
    level: int                  # BaseLevel and SpellLevel; also the module's learn level
    base_points: int            # EffectBasePoints_1 -- tooltip $m1 = base_points + 1
    die_sides: int              # EffectDieSides_1   -- tooltip $M1 = base_points + die_sides
    subtext: str                # NameSubtext_Lang_enUS, e.g. "Rank 1". Client display only.
    sla_id: int
    superceded_by: int          # SkillLineAbility.SupercededBySpell
    # AcquireMethod 2 = SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN (DBCEnums.h:359). Exactly ONE
    # row per supercede chain may carry it: Player.cpp:12284-12300 sets skipCurrent when the
    # superseding row is also 2, so two would grant the HIGHER rank. Rank 1 carries it and gets
    # a free reconcile at every login via _LoadSkills -> learnSkillRewardedSpells
    # (Player.cpp:14081). Ranks 2+ must be 0, which is also mod-learn-spells' filter
    # (mod_learnspells.cpp:446), so that module agrees with us instead of fighting us.
    acquire_method: int = 2

    @property
    def damage_min(self):
        return self.base_points + 1

    @property
    def damage_max(self):
        return self.base_points + self.die_sides


@dataclass(frozen=True)
class Ability:
    key: str
    clone_from: int                    # stock Spell.dbc record to memcpy
    skill_line: int                    # SkillLine.dbc id (771 = Frost, class skill)
    stock_chain: Tuple[int, ...]       # stock ranks, low to high, starting with clone_from
    ranks: Tuple[CustomRank, ...]      # custom ranks, low to high, prepended to the chain
    bonus: Tuple[float, float, float, float, str]   # spell_bonus_data row for each custom rank
    # SkillLineAbility rows that already exist in the stock DBC and must be edited in place.
    # {sla id: {column: new value}}
    stock_sla_edits: Dict[int, Dict[str, int]] = field(default_factory=dict)
    # Client-only NameSubtext rewrites on the stock ranks so the spellbook renumbers with the
    # chain: 45477 is rank 2 once 90000 is rank 1. {spell id: new subtext}
    stock_subtext: Dict[int, str] = field(default_factory=dict)

    @property
    def chain(self):
        """Full renumbered chain, low to high. Rank N is chain[N-1]; first_spell_id = chain[0]."""
        return tuple(r.spell_id for r in self.ranks) + self.stock_chain


ICY_TOUCH = Ability(
    key="icy_touch",
    clone_from=45477,
    skill_line=771,
    stock_chain=(45477, 49896, 49903, 49904, 49909),
    ranks=(
        CustomRank(
            spell_id=spell_id_for("icy_touch", 0),         # 90000
            level=1,
            # Calibrated against real level-1 content parsed out of Spell.dbc:
            #   133 Fireball      R1  BP1=13 die1=9  -> 14-22 over a 1.5s cast
            #    78 Heroic Strike R1  BP1=10 die1=1  -> +11 on a swing
            # BP1=9 die1=3 -> 10-12, instant, 20 yd, plus Frost Fever's -14% attack speed.
            base_points=9,
            die_sides=3,
            subtext="Rank 1",
            sla_id=sla_id_for(spell_id_for("icy_touch", 0)),   # 22000
            superceded_by=45477,
            acquire_method=2,
        ),
    ),
    # spell_bonus_data is per spell id with a first-rank fallback (SpellMgr.cpp:947-961). All
    # five stock ranks have explicit rows, so renumbering first_spell_id cannot disturb them;
    # only the new rank needs one. Values copied from the 45477 row.
    bonus=(0.0, 0.0, 0.1, 0.0, "Death Knight - Icy Touch"),
    stock_sla_edits={
        # THE FLIP THE WHOLE FEATURE DEPENDS ON (DESIGN.md 3.5, risk 8.6). Stock row 16231 is
        # (16231, 771, 45477, 0, 32, 0, 0, 1, 49896, 2, 0, 0, 0, 0) -- AcquireMethod 2 means
        # learnSkillRewardedSpells hands out the LEVEL 55 Icy Touch the instant a Death Knight
        # acquires skill 771, which is at character creation. Leave it at 2 and every new DK
        # starts with a 127-137 damage nuke and the feature is silently pointless.
        16231: {"AcquireMethod": 0},
        # ...AND THE FIVE SIBLINGS. Flipping only 16231 was a real bug caught in review: it
        # fixes Icy Touch and leaves the other five stock level-55 DK abilities auto-granted at
        # character creation, so a level-1 DK would open the spellbook holding Plague Strike,
        # Blood Strike, Blood Presence, Death Coil and Death Grip at full 55 power.
        #
        # The criterion is derived, not guessed. Of the 31 SkillLineAbility rows with
        # AcquireMethod=2 whose skill a class-6 character receives at creation, 16 are
        # DK-exclusive (ClassMask == 32) and of those exactly 6 grant a spell with
        # BaseLevel >= 55. Those 6 are precisely the abilities this feature re-ranks:
        #     16231 -> 45477 Icy Touch        16616 -> 45902 Blood Strike
        #     16238 -> 45462 Plague Strike    17016 -> 48266 Blood Presence
        #     16433 -> 47541 Death Coil       17101 -> 49576 Death Grip
        #
        # The other 10 DK-exclusive rows are BaseLevel 0/1 and MUST KEEP AcquireMethod=2 --
        # they are the free scaffolding a DK is supposed to have: Runic Focus (61455), the
        # Frost Fever holder (59921), Offensive State (45903), First Aid (10846), Sigil
        # (52665), Command (54562), Journeyman Riding (33391) and the racials. The remaining
        # 15 non-exclusive rows are shared weapon proficiencies (ClassMask 111, 431, 1535...);
        # flipping those would silently break warriors, paladins and everyone else.
        16238: {"AcquireMethod": 0},   # Plague Strike 45462
        16433: {"AcquireMethod": 0},   # Death Coil    47541
        16616: {"AcquireMethod": 0},   # Blood Strike  45902
        17016: {"AcquireMethod": 0},   # Blood Presence 48266
        17101: {"AcquireMethod": 0},   # Death Grip    49576
    },
    # Client-only. NameSubtext is parsed server-side (`s` in SpellEntryfmt) but the only thing
    # that reads it is the `.spellinfo` GM command (cs_spellinfo.cpp:759), so no matching
    # spell_dbc override row is emitted -- see MIRROR_STOCK_SUBTEXT_TO_SQL below.
    stock_subtext={45477: "Rank 2", 49896: "Rank 3", 49903: "Rank 4",
                   49904: "Rank 5", 49909: "Rank 6"},
)

ABILITIES = (ICY_TOUCH,)

# The five cells that differ between a custom rank and its clone source, BY NAME. Named rather
# than by index so a core bump that reorders SpellEntryfmt is a loud failure instead of a
# silent one; dkspells.py still asserts the resolved indices equal the ones DESIGN.md 3.3
# documents (0 / 38 / 39 / 74 / 80).
SPELL_OVERRIDE_COLUMNS = {
    "ID": lambda rank: rank.spell_id,
    "BaseLevel": lambda rank: rank.level,
    "SpellLevel": lambda rank: rank.level,
    "EffectDieSides_1": lambda rank: rank.die_sides,
    "EffectBasePoints_1": lambda rank: rank.base_points,
}
DOCUMENTED_OVERRIDE_INDICES = {"ID": 0, "BaseLevel": 38, "SpellLevel": 39,
                               "EffectDieSides_1": 74, "EffectBasePoints_1": 80}

# NameSubtext_Lang_enUS is set from the spec too, but for rank 1 it resolves to the string the
# clone source already holds ("Rank 1"), so add_string() reuses the existing offset and the
# record stays byte-identical to the clone apart from the five overrides above. dkspells.py
# asserts that no-op rather than assuming it.
SUBTEXT_COLUMN = "NameSubtext_Lang_enUS"

# Emitting spell_dbc override rows for the five stock ranks would keep `.spellinfo` in step
# with the renumbered client subtexts, at the cost of five more 234-column rows in the
# migration. DESIGN.md A3 specifies exactly one spell_dbc row, so this ships off. Turning it
# on needs no other change: the emitter, invariant #4 and --check all follow this flag.
MIRROR_STOCK_SUBTEXT_TO_SQL = False

# Future ranks, for when the full progression ships (DESIGN.md 3.2). Not used by the slice;
# kept here so the curve lives with the data it describes rather than in a comment somewhere.
FULL_PROGRESSION_LEVELS = (1, 7, 13, 19, 25, 31, 37, 43, 49)


def curve(level, low_avg=9.5, high_avg=132.0, top_level=55):
    """(base_points, die_sides) for a rank learned at `level`, DESIGN.md 3.2."""
    avg = round(low_avg + (high_avg - low_avg) * (level - 1) / (top_level - 1))
    die = max(1, round(0.08 * avg))
    return int(round(avg - (die + 1) / 2)), int(die)


# --------------------------------------------------------- character creation (A7 - A10) --

DK_RACE = 1                     # Human
DK_CLASS = 6                    # CLASS_DEATH_KNIGHT
TEMPLATE_CLASS = 1              # Warrior -- the class whose level 1-54 data we copy

# A7. Moving the spawn off map 609 does three jobs at once: it makes the entire DK starter
# chain unreachable (every questgiver 12593..12801 spawns only on 609, there are zero
# areatrigger_teleport rows targeting 609, and every chain quest is MinLevel 55), it makes
# CalculateTalentsPoints take the normal branch, and it sets the homebind
# (PlayerStorage.cpp:7187). Map/zone are fixed here; x/y/z/o are copied VERBATIM from the
# race 1 class 1 row in the live database, never typed in.
CREATE_MAP = 0
CREATE_ZONE = 12                # Elwynn Forest / Northshire

# A8. CharStartOutfit override, not playercreateinfo_item. The single existing DK row
# (0, 6, 40582, -1) is a REMOVAL directive -- negative counts route into
# PlayerCreateInfoAddItemHelper (ObjectMgr.cpp:4482) which zeroes that itemId inside the
# CharStartOutfit entry. Eighteen negative rows plus a positive kit would log an error per
# miss. Rows 352/353 are Human DK male/female; rows 1/14 are Human warrior male/female. Only
# the ItemID/DisplayItemID/InventoryType arrays are copied -- RaceID/ClassID/SexID/OutfitID
# stay as they are in 352/353, because they are already correct.
START_OUTFITS = ((352, 1), (353, 14))   # (death knight outfit id, warrior template outfit id)
OUTFIT_KEY_COLUMNS = ("RaceID", "ClassID", "SexID", "OutfitID")

# A9. Action bar. 6603 = Attack, 59752 = Every Man for Himself (Human racial). Button 1 is the
# custom rank-1 spell; resolved from the spec, never hardcoded.
ACTION_BAR = (
    (0, 6603, 0),
    (1, ICY_TOUCH.ranks[0].spell_id, 0),
    (11, 59752, 0),
)

# A10. 48266 Blood Presence is a level-55 spell cast on first login with triggered=true
# (CharacterHandler.cpp:1007), so it would apply anyway and leave a level-1 DK with an aura
# they cannot map to a known spell. Delete the row; Blood Presence comes back as a normal
# progression grant later.
CAST_SPELL_DELETIONS = ((0, 32, 48266),)

# A1. player_class_stats is (class x level); player_race_stats is flat per race and is added
# on top at ObjectMgr.cpp:4830, so this is 54 rows, not 540. Class 1 and class 6 are
# byte-identical from level 56 up and differ by one point of Str/Sta at 55, so "copy warrior"
# is what Blizzard's own data does above the boundary. Read from the live DB, never typed.
CLASS_STATS_LEVELS = tuple(range(1, 55))
CLASS_STATS_COLUMNS = ("Class", "Level", "BaseHP", "BaseMana",
                       "Strength", "Agility", "Stamina", "Intellect", "Spirit")

# ----------------------------------------------- utilities the skipped chain used to give --

# Granted by the module's Reconcile(), never by casting the quest reward spells. Casting 53821
# (the quest 12801 reward) would run SPELL_EFFECT_BIND with MiscValue 4342 and silently rebind
# the player's hearthstone wherever they logged in; casting 53431 is unnecessary because
# learnSpell(53428) alone drives Player::addSpell's SKILL_RUNEFORGING branch
# (Player.cpp:3377). Levels are config-overridable in the module; these are the defaults the
# generated header carries for reference.
UTILITY_SPELLS = (
    ("DEATH_GATE", 50977, "DKLowLevel.DeathGateLevel", 1),
    ("RUNEFORGING", 53428, "DKLowLevel.RuneforgingLevel", 1),
    # RIDING IS ALREADY HANDLED BY STOCK DATA -- do not grant it here.
    # SkillLineAbility 19184 (skill 762 Riding, ClassMask 32, AcquireMethod 2) grants spell
    # 33391 Journeyman Riding to every Death Knight at character creation, and keeps re-granting
    # it on each login via learnSkillRewardedSpells. Granting 33388 Apprentice Riding at level 20
    # on top of that was worse than redundant: SpellMgr::LoadSpellLearnSkills gives 33388 a
    # SpellLearnSkillNode of step*75, so learning it DOWNGRADES the riding skill value that
    # 33391 had already set. Left alone, a DK simply has Journeyman Riding from level 1 -- which
    # is stock Blizzard behaviour for the class, not something this feature introduced.
)


def progression_grants() -> List[Tuple[int, int]]:
    """[(level, spell id)] for every custom rank, sorted by level then id.

    This is what becomes kDkProgression[] in the generated header. Reconcile() walks it in
    order and breaks on the first entry above the player's level, so the sort is load-bearing.
    """
    out = [(r.level, r.spell_id) for a in ABILITIES for r in a.ranks]
    out.sort()
    return out


def all_custom_spell_ids() -> List[int]:
    return sorted(r.spell_id for a in ABILITIES for r in a.ranks)


def all_custom_sla_ids() -> List[int]:
    return sorted(r.sla_id for a in ABILITIES for r in a.ranks)


def rank_by_spell_id(spell_id) -> Optional[CustomRank]:
    for a in ABILITIES:
        for r in a.ranks:
            if r.spell_id == spell_id:
                return r
    return None
