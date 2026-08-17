#!/usr/bin/env python3
"""THE source of truth for the Demon Hunter class.

Nothing in this feature may be edited anywhere else. `dhspells.py` reads this file and emits,
from it alone:

    data/sql/db-world/base/2026_08_16_00_demon_hunter_class.sql        (the class itself)
    data/sql/db-world/base/2026_08_16_01_demon_hunter_spells.sql       (the ability ladder)
    data/sql/db-world/base/2026_08_16_02_demon_hunter_createinfo.sql   (character creation)
    data/sql/db-world/base/2026_08_16_03_demon_hunter_talents.sql      (the three trees)
    src/dh_progression.h                                               (compiled grant table)
    <out>/dbc/*.dbc                                                    (client truth)
    <out>/patch-Z.MPQ                                                  (shipped to friends)

READ `docs/demon-hunters.md` FIRST. This file is the data; that document is the argument.

WHY THIS IS A REAL CLASS AND NOT A RESKINNED ROGUE
--------------------------------------------------
`ChrClasses.dbc` ships ten records with IDs 1-9 and 11. Ten, not eleven: `//CLASS_UNK = 10` is
a hole in the middle of the enum (`SharedDefines.h:135`) that Blizzard reserved and never used.
`MAX_CLASSES` is already **12**, every array in the core is `[MAX_CLASSES]` indexed by class,
and every bound is `class_ >= MAX_CLASSES` -- so class 10 is inside every one of them today,
with no resize and no core-wide audit. Class *12* is the index that overflows, which is why
this feature takes the hole instead of appending past the end.

The price is two patches, both small and both documented where they live:

  * `build/patches/0001-demon-hunter-class-10.patch` -- eight lines. Six per-class float tables
    have a `0.0f, // ??` at the class-10 index and are read through `getClass() - 1` rather
    than through `Player::IsClass`, so no module hook can reach them and the arithmetic comes
    out NaN. Plus `CLASSMASK_ALL_PLAYABLE`, which silently drops every talent tab.
  * `client/tools/patch-wow-exe.py` -- twelve bytes at each of two sites. `ChrClasses.dbc`
    having exactly ten rows is load-bearing on the client too: `MAX_CLASSES_PER_RACE = 10` in
    `Interface\\GlueXML\\CharacterCreate.lua`, and an eleventh row makes
    `CharacterCreateEnumerateClasses` bail out and leave every class button unconfigured for
    every race. Raising it means editing a file inside the RSA-signed GlueXML tree.

Everything else -- stats, creation, spells, talents, the demon form -- is SQL rows in the
world-DB `*_dbc` override tables and records appended to the client's DBCs. `/srv/wow/data/dbc`
is never written. That is the Death Knight architecture (`docs/death-knights.md` 3), reused
wholesale, and the reason it transfers is that `DBCStores.cpp:284-400` passes an override table
name alongside **every** `LOAD_DBC`, not just the three the Death Knight needed.

WHY CLONE INSTEAD OF AUTHOR
---------------------------
Same reason as the Death Knight, restated because it is the single most load-bearing decision
in the generator: a custom spell is a byte-for-byte memcpy of a stock record with a handful of
named cells overridden. A Spell.dbc record has 234 columns and perhaps a dozen of them are
"the spell"; the rest is icon, visual, sound, interrupt flags, facing requirements, aura
interrupt masks, attribute bits nobody has names for. Authoring a row field by field silently
drops whichever of the 222 nobody thought about. A memcpy cannot.

The one thing that differs from the Death Knight: a DK custom rank clones the stock rank 1 of
an ability the class already has, and hands off to it at level 55. A Demon Hunter ability has
no stock rank to hand off to, because the class did not exist in 3.3.5a. So the ladder runs
1 -> 80 with no handoff, `POWER_TOP_LEVEL` is 80 rather than 55, and the donor is chosen for
its *mechanics* rather than for being the same spell.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------------- paths --

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TOOLS_DIR)                      # build/modules/mod-demon-hunter
REPO_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "build", "tools"))

from acdbc import dbc_tables                                       # noqa: E402

SQL_DIR = os.path.join(MODULE_DIR, "data", "sql", "db-world", "base")
HEADER_PATH = os.path.join(MODULE_DIR, "src", "dh_progression.h")

DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".work", "out")
DEFAULT_DBC_IN = "/srv/wow/data/dbc"
DEFAULT_CLIENT_DATA = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"

# UpdateFetcher tracks a migration by BARE FILENAME plus a SHA1 of its contents
# (UpdateFetcher.cpp:326-370) and LOG_FATALs on a duplicate filename across the core and every
# module (:96-100) -- so the dated, module-qualified prefix is not decoration. A CHANGED file is
# re-applied IN FULL, which is why every statement these emit is DELETE-then-INSERT per key.
SQL_FILES = {
    "class":      "2026_08_16_00_demon_hunter_class.sql",
    "spells":     "2026_08_16_01_demon_hunter_spells.sql",
    "createinfo": "2026_08_16_02_demon_hunter_createinfo.sql",
    "talents":    "2026_08_16_03_demon_hunter_talents.sql",
}

# THE ONE ARCHIVE. MPQ resolution is whole-file per archived path by archive priority, so two
# archives cannot both supply Spell.dbc -- the higher-priority one wins outright and the other's
# records simply are not there. patch-Z is already the top of the resolved chain (measured:
# priority 0x46, above patch-3 at 0x45 and enUS/patch-enUS-3 at 0x43), so there is no second
# slot to move to either. Both class features therefore write ONE archive, and this generator
# builds it last, from the Death Knight generator's output. See acdbc/__init__.py.
MPQ_SLOTS = {
    "Z": "patch-Z.MPQ",
    "enUS-4": os.path.join("enUS", "patch-enUS-4.MPQ"),
}
DEFAULT_MPQ_SLOT = "Z"

# --------------------------------------------------------- what else ships in the archive --
#
# The Death Knight's archive holds three DBCs and nothing else. This one also has to carry UI,
# because a new class is the one kind of change the client's Lua has hardcoded assumptions
# about: `MAX_CLASSES_PER_RACE = 10` and a `CLASS_ICON_TCOORDS` table with exactly ten keys.
#
# STORED AS PATCHES, NOT AS COPIES. Two reasons, and the second is the load-bearing one:
#
#   1. These are Blizzard's files. A 77 KB verbatim copy of `GlueStrings.lua` in this repo is a
#      redistribution question that a 26-line diff simply is not.
#   2. A patch FAILS when the file underneath it changes. A copy silently wins -- it is the
#      highest-priority archive, so a stale copy would quietly revert whatever the real file
#      had gained, and nothing would say so. `patch --fuzz=0` turns "ChromieCraft shipped a new
#      GlueXML" from a silent regression into a build error naming the file.
#
# The generator extracts the stock file from the client's own archive chain, applies the patch,
# and adds the result. It never reads a checked-in copy of a Blizzard file, because there is
# not one.
CLIENT_DIR = os.path.join(MODULE_DIR, "client")
CLIENT_PATCHES = (
    ("Interface_GlueXML_CharacterCreate.lua.patch", "Interface\\GlueXML\\CharacterCreate.lua"),
    ("Interface_GlueXML_CharacterCreate.xml.patch", "Interface\\GlueXML\\CharacterCreate.xml"),
    ("Interface_FrameXML_Constants.lua.patch", "Interface\\FrameXML\\Constants.lua"),
)

# Built by tools/dh_icons.py into <out>/icons/, for the same reason: they are derived from
# Blizzard's own atlas plus one of Blizzard's own icons, so they are build output exactly as
# the patched DBCs are -- reproducible from the client, and not committed.
CLIENT_ICONS = (
    ("UI-CharacterCreate-Classes.blp",
     "Interface\\Glues\\CharacterCreate\\UI-CharacterCreate-Classes.blp"),
    ("UI-Classes-Circles.blp",
     "Interface\\TargetingFrame\\UI-Classes-Circles.blp"),
)

# WHICH DBC FILES THIS FEATURE OWNS. Note this is a superset of the Death Knight's three: the
# archive that ships contains the union, because it is one archive.
DBC_TABLES = (
    dbc_tables.SPELL_DBC,
    dbc_tables.SKILLLINEABILITY_DBC,
    dbc_tables.CHARSTARTOUTFIT_DBC,
    dbc_tables.CHRCLASSES_DBC,
    dbc_tables.SKILLLINE_DBC,
    dbc_tables.SKILLRACECLASSINFO_DBC,
    dbc_tables.TALENTTAB_DBC,
    dbc_tables.TALENT_DBC,
    dbc_tables.SPELLSHAPESHIFTFORM_DBC,
    dbc_tables.CHARBASEINFO_DBC,          # client-only, no SQL half
)
DBC_BY_SQL_NAME = {t.sql_table: t for t in DBC_TABLES if t.sql_table}

# ----------------------------------------------------------------------------- id policy --
#
# The Death Knight occupies 90000-90219 in eleven twenty-wide blocks and is documented as
# reserving room to grow. Live census (acore_world.spell_dbc, plus the stock file) confirms the
# only IDs above the stock Spell.dbc maximum of 80864 are 90000, 100001, 100099-100102 and
# 200100. The Demon Hunter therefore starts at 91000, leaving 90220-90999 as the Death Knight's
# growth buffer and 93000-99999 free for whatever comes third.
#
#   1 ..  80864   stock Spell.dbc, strictly ascending
#   80865..89999  deliberately unused -- the first place an "append after max" tool would land
#   90000..90219  Death Knight, 11 blocks of 20
#   90220..90999  Death Knight growth buffer -- do not take
#   91000..91999  DEMON HUNTER abilities, 50 blocks of 20
#   92000..92999  DEMON HUNTER talent ranks
#   93000..99999  free
#   100001+       AzerothCore's own serverside band (spell_dbc ships 100001, 100099-100102)
#
# The ceiling is not a DBC limit. It is the 24-bit action-button packing:
# MAX_ACTION_BUTTON_ACTION_VALUE = 0x00FFFFFF+1 (Player.h:235). A spell above that cannot be
# dragged onto a bar. We are three orders of magnitude below it.

SPELL_ID_MIN = 80865          # inclusive, must be > stock Spell.dbc max ID
SPELL_ID_MAX = 100000         # exclusive, AC's serverside band begins at 100001
# WHERE IMPORTED RECORDS COME FROM.
#
# An installed Ascension client. Only abilities carrying `Ability.source` read it, and a
# checkout without one still builds every donor-based ability -- the generator degrades to a
# SKIP rather than a failure, so this path being wrong is loud but not fatal.
ASCENSION_CLIENT_DATA = os.environ.get(
    "ASCENSION_CLIENT_DATA",
    "/mnt/ntfs2t/Ascension/Launcher/resources/ascension-live/Data")

SPELL_ID_BASE = 91000         # abilities
TALENT_SPELL_ID_BASE = 92000  # talent ranks
TALENT_SPELL_ID_MAX = 93000

SLA_ID_BASE = 23000           # stock SkillLineAbility.dbc max is 21980; the DK took 22000
IDS_PER_ABILITY = 20

# Fixed now so IDs never move, in progression order. A block that is reserved and vacant stays
# reserved and vacant forever -- reusing one would silently repoint a spell that some character
# already has in `character_spell`.
# ABILITY_BLOCKS and SINGLES_ORDER now live in fs_abilities.py, imported at the bottom of this
# file with ABILITIES itself. They were moved together on purpose: the block table, the singles
# order and the ladder are one fact split three ways, and keeping the id allocation in a
# different file from the abilities it allocates for is how a block ends up owned by nothing.


def spell_id_for(ability_key, rank_index):
    """rank_index is 0-based; rank 1 of an ability is its block base."""
    return SPELL_ID_BASE + IDS_PER_ABILITY * ABILITY_BLOCKS[ability_key] + rank_index


def single_spell_id(key):
    return spell_id_for("singles", SINGLES_ORDER.index(key))


def sla_id_for(spell_id):
    """SkillLineAbility id for an ability spell. Talent ranks get no SLA row -- a talent spell
    is granted by the talent system, and an SLA row would make it learnable twice."""
    assert SPELL_ID_BASE <= spell_id < TALENT_SPELL_ID_BASE, (
        f"{spell_id} is not an ability spell; talent ranks must not get SkillLineAbility rows")
    return SLA_ID_BASE + (spell_id - SPELL_ID_BASE)


# =============================================================================================
# THE CLASS ITSELF
# =============================================================================================

DH_CLASS = 10                   # CLASS_DEMON_HUNTER, added by the core patch

# The class whose numbers the Demon Hunter is derived from, everywhere a derivation is needed:
# `player_class_stats` levels 1-80, the six gt*.dbc per-class blocks, and the six hardcoded
# float tables in the core patch. Rogue, and not as a matter of taste --
#
#   * leather, agility-scaling, dual-wield, parries: the same stat shape;
#   * `ChrClasses.dbc` class 4 DisplayPower is 3 = POWER_ENERGY, a 0-100 bar with continuous
#     out-of-combat regeneration. That IS Fury, with the correct client bar and no DBC surgery;
#   * `StartRecoveryTime` on every Rogue ability is 1000, not 1500 -- the one-second GCD that an
#     energy class needs and that a rage or mana class does not get;
#   * it exists for both elf races already, so every derivation below has a real row to read.
#
# Nothing is *copied from* Rogue at runtime. The generator reads Rogue's rows out of the live
# database and emits them as class-10 rows, so this constant is a pointer to evidence rather
# than an instruction to guess.
TEMPLATE_CLASS = 4

# ChrClasses.dbc row 10. Every cell that is not listed here is zero, which is what the vacant
# slot's neighbours look like for the columns the core marks FT_NA.
CHRCLASS_ROW = {
    "ID": DH_CLASS,
    # DisplayPower 3 = POWER_ENERGY. See TEMPLATE_CLASS above.
    "DisplayPower": 3,
    # PetNameToken is deliberately NOT listed. It is a string offset in the DBC file but an
    # `int` column in the world DB, and the row is cloned from the Rogue -- whose offset already
    # points at "PET", the token nine of the ten stock classes use. Writing it would mean
    # writing an integer offset into a file we are also appending strings to, for no gain: a
    # Demon Hunter has no pet and the token is only ever read to label a pet frame.
    "Name_Lang_enUS": "Felsworn",
    # THE CLASS TOKEN. `FillLocalizedClassList` and `UnitClass()` return it, and FrameXML and
    # GlueXML both key CLASS_ICON_TCOORDS / RAID_CLASS_COLORS on it. It must match the key the
    # patched Constants.lua and CharacterCreate.lua add, exactly, including case.
    "Filename": "FELSWORN",
    # SPELLFAMILY_UNK2.
    #
    # A family is not cosmetic. It is the entire mechanism by which an authored talent modifies
    # an ability without C++: a passive carrying SPELL_AURA_ADD_PCT_MODIFIER, this family, and a
    # SpellClassMask bit the ability also carries. `SpellInfo::IsAffected` (SpellInfo.cpp:1325)
    # short-circuits on `familyName != SpellFamilyName`, so the family is simultaneously what
    # lets Demon Hunter talents reach Demon Hunter spells and what stops every other class's
    # talents, glyphs, set bonuses and spell_proc rows from reaching them.
    #
    # Four values were candidates. Why 16:
    #
    #   0  DISQUALIFIED. `IsAffected` opens with `if (!familyName) return true;` -- a family-0
    #      modifier matches EVERY spell in the game, not the ones you meant. Talents would all
    #      have to be C++ scripts.
    #   12 SPELLFAMILY_UNK2, and the first choice here, on the theory that SpellMgr.cpp:2089
    #      flags `== 14` and `== 16` as a wrong `SpellFamilyName` for a `spell_proc` row and a
    #      talent tree would want procs. That theory is wrong: SpellMgr.cpp:2158-2232 GENERATES
    #      a proc entry from the DBC record for any spell that has a trigger aura and no
    #      explicit `spell_proc` row, reading `SpellFamilyName` and `SpellFamilyMask` straight
    #      off the spell. Proc talents are therefore pure DBC and the validator is never
    #      reached, which leaves 12's two stock users (35126, 42184) as a pure cost.
    #   14 / 16  Zero rows in the entire 49,839-record Spell.dbc -- verified by histogramming
    #      SpellClassSet over every record; the enum comments `// 14 - unused` and
    #      `// 16 - unused` (SharedDefines.h:3798, 3800) are accurate. Nothing in the core
    #      switches on either, so every family-keyed hardcode falls to `default:`.
    #   16 CHOSEN, arbitrarily between the two equivalent ones.
    #
    # The consequence of falling to `default:` that actually matters: diminishing returns is
    # classified by family first (SpellMgr.cpp:107-263) and by `Mechanic` only in the default
    # branch. So every crowd-control ability in the kit MUST set `Mechanic` explicitly -- it is
    # the only DR input a Demon Hunter has. Chaos Nova and Imprison both do.
    #
    # ONE ABILITY IS EXEMPT and it is not negotiable: Vengeful Retreat must carry
    # SPELLFAMILY_HUNTER. See VENGEFUL_RETREAT_FAMILY_WHY below.
    "SpellClassSet": 16,
    # Unread by the server -- `ChrClassesEntry::spellfamily` is declared in DBCStructure.h:692
    # and referenced nowhere in src/server/game. Rogue's value, on the same principle as
    # TEMPLATE_CLASS: when the meaning is unknown, match the class we are shaped like.
    # UNVERIFIED what the client does with it.
    "Flags": 2,
    # No intro cinematic. The Death Knight has 165; every other class has 0, and there is no
    # Demon Hunter cinematic in a 3.3.5a client to point at.
    "CinematicSequenceID": 0,
    # 2 = Wrath. Checked at CharacterHandler.cpp:315 against the account's expansion, and every
    # account on this realm is 2. Matching the Death Knight rather than 0 is deliberate: a
    # Demon Hunter is not a vanilla class and an account that cannot make a DK should not make
    # one of these either.
    "Required_Expansion": 2,
}


@dataclass(frozen=True)
class DhRace:
    """One race that may roll a Demon Hunter.

    `template_class` is the class whose creation row this race copies -- always Rogue here,
    because both elf races have one and it is the right stat shape. The map/zone/coordinates are
    NOT written down: the generator reads them from the live `playercreateinfo` row for
    (race, template_class) so a realm that has moved its starting zones stays correct.
    """

    race_id: int
    name: str
    template_class: int
    faction: str


# "Only elves." Night Elf (4) is Alliance, Blood Elf (10) is Horde, which is also the reason the
# restriction works as a design rather than as a faction lockout.
#
# Enforced in BOTH halves, and neither alone is sufficient:
#   * client -- `CharBaseInfo.dbc` gains (4,10) and (10,10) and nothing else, so
#     `IsRaceClassValid` is false for every other race and CharacterCreate.lua:220-227 greys the
#     button out with no error dialog. This is presentation only; a crafted packet ignores it.
#   * server -- `playercreateinfo` gains rows for exactly these two races, so `Player::Create`
#     fails at `GetPlayerInfo` for anything else. This is the real gate.
DH_RACES = (
    DhRace(4, "Night Elf", TEMPLATE_CLASS, "Alliance"),
    DhRace(10, "Blood Elf", TEMPLATE_CLASS, "Horde"),
)

DH_RACE_MASK = sum(1 << (r.race_id - 1) for r in DH_RACES)   # 0x208 = 520
DH_CLASS_MASK = 1 << (DH_CLASS - 1)                          # 0x200 = 512

# CharStartOutfit.dbc rows: four, one per (race, sex). The stock file's maximum ID is 367 --
# which already includes the Death Knight feature's 348-367, because that generator appends
# them to the client file as well as emitting SQL. 368 is the first free ID.
OUTFIT_ID_BASE = 368
OUTFIT_KEY_COLUMNS = ("RaceID", "ClassID", "SexID", "OutfitID")

# ------------------------------------------------------------------- skills and spellbook --
#
# A class skill line is what gives the spellbook a named tab; CategoryID 7 is
# SKILL_CATEGORY_CLASS (verified: 26 "Arms", 38 "Combat", 771 "Frost" are all category 7).
# Stock SkillLine.dbc runs 6..788, so 800+ is clear.
#
# Three lines, one per talent tree, because that is how every other class is arranged and it is
# what makes the spellbook tabs read correctly.
SKILL_LINE_BASE = 800
SKILL_LINES = (
    (SKILL_LINE_BASE + 0, "Demonology"),
    (SKILL_LINE_BASE + 1, "Slaying"),
    (SKILL_LINE_BASE + 2, "Felblood"),
)
# Which skill line each ability's SkillLineAbility rows point at. Abilities not listed default
# to the first line.
PRIMARY_SKILL_LINE = SKILL_LINES[0][0]

# SkillRaceClassInfo.dbc binds a skill line to a race/class mask; without a row the skill exists
# and nobody is eligible for it. Stock max ID is 970.
#
# Allocation, in one place so the two blocks cannot collide:
#     980 .. 982   the three class skill lines, one per entry in SKILL_LINES
#     983 .. 989   one per entry in CREATE_SKILL_RCI (the weapon/armour skills)
# The generator asserts every id in both ranges is free in the stock file.
SKILLRACECLASSINFO_ID_BASE = 980
CREATE_SKILL_RCI_ID_BASE = SKILLRACECLASSINFO_ID_BASE + 3

# What a Demon Hunter knows at creation, beyond the three class lines above.
#
# Derived from the Rogue's `playercreateinfo_skills` rows (every row whose classmask has bit 8),
# then TRIMMED -- which is a design decision and not a derivation, so it is written down here
# with its reasoning rather than computed:
#
#   kept    43 Swords, 44 Axes, 473 Fist Weapons -- warglaives. Warglaive of Azzinoth (32837)
#           is item class 2 subclass 7, a one-handed sword, and the low-level glaive-looking
#           weapons are spread across these three subclasses.
#   kept    173 Daggers -- every elf starting zone drops them, and a level-3 Demon Hunter has
#           to hold something.
#   kept    176 Thrown -- Throw Glaive is a real ability and it needs the skill.
#   kept    118 Dual Wield -- the entire class fantasy.
#   kept    414 Leather -- the armour class the stat template assumes.
#   DROPPED 45 Bows, 46 Guns, 226 Crossbows -- a Demon Hunter with a rifle is off-brand, and
#           nothing in the kit uses the ranged slot except Throw Glaive, which is Thrown.
#   DROPPED 54 Maces -- no glaive is a mace.
#
# 95 Defense and 162 Unarmed are NOT listed because their stock rows carry classmask 0, i.e.
# every class already gets them; adding a class-10 row would be a duplicate.
CREATE_SKILLS = (
    (43,  "Swords"),
    (44,  "Axes"),
    (118, "Dual Wield"),
    (173, "Daggers"),
    (176, "Thrown"),
    (414, "Leather"),
    (473, "Fist Weapons"),
)

# The starting action bar, read left to right. Slot 0 is Attack on every class in the game.
# The rest are filled by the generator from the ability ladder's level-1 ranks, plus the race
# spell, so this tuple carries only the parts that are not derivable.
CREATE_ACTION_ATTACK = 6603              # "Attack", button 0, universal
CREATE_ACTION_RACE_SPELL = {
    4:  58984,   # Night Elf -- Shadowmeld
    10: 25046,   # Blood Elf -- Arcane Torrent
}

# =============================================================================================
# STOCK SkillLineAbility ROWS THAT HAVE TO BE WIDENED
# =============================================================================================
#
# A new class does not automatically get the spells every other class takes for granted, and
# the failure is silent in the worst way: the spell simply never appears, with nothing logged.
# `learnSkillRewardedSpells` filters on the SkillLineAbility row's `ClassMask`, and four rows
# that matter do not have class 10's bit. Read out of the stock file, not assumed:
#
#     SLA   610  spell   674 Dual Wield      ClassMask  109 = warrior|hunter|rogue|dk|shaman
#     SLA  2201  spell  3127 Parry           ClassMask   15 = warrior|paladin|hunter|rogue
#     SLA 20665  spell 21009 Elusiveness     ClassMask 1085, RaceMask 8  (Night Elf racial)
#     SLA 13338  spell 25046 Arcane Torrent  ClassMask    8 = ROGUE ONLY, RaceMask 512
#
# What each one costs if left alone:
#
#   674   `Player::CanDualWield` is false forever, so `FindEquipSlot` never offers the off-hand
#         slot. A dual-wield class that cannot dual wield. This is the worst of the four.
#   3127  `UpdateParryPercentage` opens `if (CanParry() && parry_cap[pclass] > 0.0f)`
#         (StatSystem.cpp:774) -- so without the spell, the `parry_cap[9]` value the CORE PATCH
#         exists to provide is dead code and the class never parries anyway.
#   25046 The Blood Elf racial. It is on the generated starting action bar, so leaving this
#         alone ships every Blood Elf Demon Hunter a button that does nothing. Note the mask is
#         8 and not 0 -- Arcane Torrent's row is per-class because its effect differs by class.
#   21009 The Night Elf racial passive. (58984 Shadowmeld itself is ClassMask 0 = every class,
#         so that one needs nothing -- checked rather than assumed.)
#
# Widened here, in DATA, rather than granted by the module at login. Three reasons: it is one
# `skilllineability_dbc` override row each instead of runtime work on every login; it fixes the
# client half too, so the spellbook and tooltips agree; and it is how the Death Knight feature
# already edits a stock SLA row (16231's AcquireMethod flip), so there is one pattern and not
# two. The module granting them would still work and would simply become a no-op.
STOCK_SLA_WIDENINGS = (
    (610,   674, "Dual Wield -- without it CanDualWield is false and the off-hand slot is "
                 "never offered"),
    (2201, 3127, "Parry -- without it CanParry() is false and the core patch's parry_cap[9] "
                 "is unreachable"),
    (13338, 25046, "Arcane Torrent, the Blood Elf racial -- it is on the starting action bar, "
                   "and its row is ROGUE-ONLY because the effect differs per class"),
    (20665, 21009, "Elusiveness, the Night Elf racial passive"),

    # ---- WEAPON AND ARMOUR PROFICIENCY -------------------------------------------------------
    # These are the other half of CREATE_SKILL_RCI below, and neither half works alone. The
    # SkillRaceClassInfo row lets Player::LearnDefaultSkill actually SET the skill; this row is
    # what LearnSkillRewardedSpells then filters on to hand out the proficiency SPELL. And it is
    # the spell, not the skill, that sets m_WeaponProficiency / m_ArmorProficiency -- which is
    # what Player::CanUseItem reads. Skill without spell equips nothing.
    #
    # Cloth (SLA 4999, spell 9078) is deliberately absent: its mask is 1535 and it is therefore
    # already covered by STOCK_ALL_CLASS_MASKS. Thrown (SLA 1550, spell 2567) is absent because
    # its mask is a real 0 -- checked, not assumed.
    (252,    201, "One-Handed Swords proficiency -- Warglaive of Azzinoth (32837) is item "
                  "class 2 subclass 7, a one-handed sword, so this is the glaive proficiency"),
    (248,    196, "One-Handed Axes proficiency -- the other subclass low-level glaives use"),
    (1387,  1180, "Daggers proficiency -- both elf start zones hand out a dagger, and without "
                  "this it goes to the backpack instead of the hand"),
    (4998,  9077, "Leather proficiency -- the armour class the stat template assumes"),
    (8438, 15590, "Fist Weapons proficiency"),
)


# =============================================================================================
# "EVERY CLASS" IS SPELLED AS A LITERAL MASK, AND THE LITERAL PREDATES CLASS 10
# =============================================================================================
#
# This is the defect that broke the first live Demon Hunter, and it deserves the space because
# nothing about it is visible in a diff: Blizzard never writes "all classes" as ClassMask 0. It
# writes the number that meant all classes in 2008.
#
#     1535 = 0b10111111111   every class 1..11 EXCEPT 10   <- the Demon Hunter's slot
#     1503 = 1535 & ~32      the same, minus the Death Knight
#     2047 = 0b11111111111   every class 1..11 INCLUDING 10 -- those rows are already correct
#
# So a new class in slot 10 inherits nothing that is nominally universal: not one language, no
# profession, no Cloth, no Mounts, no Companions. Measured on the stock files rather than
# guessed -- a Blood Elf Rogue is eligible for 65 skills, a Blood Elf Demon Hunter for 8.
#
# Everything below traced back to this one cause, which is why it is fixed as a rule and not as
# a list of symptoms:
#
#   * NO LANGUAGE, hence NO CHAT AND NO DOT COMMANDS. ChatHandler.cpp:95-113 drops any
#     CHAT_MSG_SAY whose language skill the sender lacks and returns at :112 -- and
#     ChatHandler::ParseCommands is not reached until :307. A character with no language skill
#     cannot talk and cannot run a single `.` command, GM or otherwise. The account had gmlevel
#     3 the entire time; the class simply could not speak.
#   * NO PROFICIENCY, hence NO STARTING GEAR. Player::CanUseItem fails, so Player::Create's
#     StoreNewItemInBestSlots quietly puts the starting outfit in the BACKPACK rather than on
#     the body. The character looks naked next to a full bag. The shirt is the one thing that
#     equips, because shirts require no proficiency -- which is exactly the symptom seen.
#   * No professions, no mounts, no companion pets, at any level, forever.
#
# The rule is to treat 1503/1535 as what they MEAN rather than what they SAY, and to apply it
# to skillraceclassinfo_dbc AND skilllineability_dbc, because the skill and the spell that the
# skill rewards are gated separately and both gates are shut. Widening a stock row is safe in a
# way that inventing one is not: it adds class 10 to a set that already means "everyone" and
# changes nothing for any other class.
STOCK_ALL_CLASS_MASKS = (1503, 1535)


# SkillRaceClassInfo rows to CREATE for class 10, as opposed to widen. These are the skills
# whose stock rows are genuinely per-class, so there is no "all classes" row to widen: a
# rogue's Daggers row is ClassMask 264 and means it.
#
# The skill list is exactly CREATE_SKILLS, and that is not a coincidence -- it is the invariant.
# playercreateinfo_skills already has a class-10 row for each of these (that table spells "all
# classes" as a real 0, so it needed nothing), and Player::LearnDefaultSkills walks that list
# but calls GetSkillRaceClassInfo per entry and SILENTLY SKIPS any skill with no matching row.
# Both halves or neither; the generator asserts they agree.
#
# Flags and MinLevel are copied from the named stock donor rather than invented, so that a
# client bump which moves them shows up as a failed check instead of a subtly wrong skill.
CREATE_SKILL_RCI = (
    # skill, flags, minlevel, donor SkillRaceClassInfo row it is copied from
    (43,  128, 0, 872),    # Swords        -- rogue row, ClassMask 8
    (44,  128, 0, 335),    # Axes          -- ClassMask 74
    (118, 146, 1, 131),    # Dual Wield    -- rogue row; note MinLevel 1, not 0
    (173, 128, 0, 129),    # Daggers       -- ClassMask 264
    (176, 128, 0, 142),    # Thrown        -- rogue row, ClassMask 8
    (414, 128, 0, 147),    # Leather       -- ClassMask 1135
    (473, 130, 0, 330),    # Fist Weapons  -- ClassMask 1101, and note Flags 130 not 128
)


# Which abilities' rank 1 goes on the starting bar, in order. Every entry must be an ability
# whose ladder starts at level 1, or a new character gets a button for a spell they do not have
# -- which renders as a blank slot rather than an error, i.e. it fails silently. Asserted by the
# generator against the ladder rather than trusted from this tuple.
STARTING_BAR_ABILITIES = ("twin_slice", "sargeron_smite")

# ------------------------------------------------------------------------------- talents --
#
# TalentTab.dbc stock max is 411, Talent.dbc stock max is 2285.
#
# THE TRAP, and the reason half the core patch exists: DBCStores.cpp:551-556 does
#     if ((talentTabInfo->ClassMask & CLASSMASK_ALL_PLAYABLE) == 0) continue;
# with the comment "prevent memory corruption; otherwise cls will become 12 below". Class 10's
# bit is not in that macro on a stock core, so all three tabs below are read out of the DBC,
# skipped, and the class has an empty talent panel for its entire life with no error logged.
TALENT_TAB_ID_BASE = 412
TALENT_ID_BASE = 2300

# OrderIndex 0/1/2 -- the client renders up to three tabs with no UI work and silently ignores
# a fourth. BackgroundFile names an existing texture under Interface\TalentFrame; a name with
# no texture behind it renders as a blank panel, so these reuse real ones.
TALENT_TABS = (
    (TALENT_TAB_ID_BASE + 0, "Demonology", 0, "WarriorArms"),
    (TALENT_TAB_ID_BASE + 1, "Slaying",    1, "RogueAssassination"),
    (TALENT_TAB_ID_BASE + 2, "Felblood",   2, "WarlockDestruction"),
)

# --------------------------------------------------------------------------- demon form --
#
# SpellShapeshiftForm.dbc rows 23 and 24 are entirely blank in the stock file (verified: every
# column zero, empty name). Row 22 is stock Metamorphosis -- flags 0xd8, CreatureType 3 (Demon),
# CreatureDisplayID_1 25277 = Creature\DemonForm\DemonForm.mdx.
#
# The Demon Hunter takes 23 rather than reusing 22 for one reason: form 22 is the Warlock's, and
# entering it is what the Warlock's own form-gated passives key off. Taking a blank slot means
# nothing else in the game has an opinion about being in it.
# THE RESOURCE, and the one number the form is priced in.
#
# Felfury is NOT a power type -- Ascension's own 800058 describes itself as "Represents your
# Felfury charges" and is a stacking self-aura whose three haste effects all carry
# EffectBasePoints -1, i.e. amount ZERO. They are inert carriers that a talent later fills in.
# There is exactly one DisplayPower per class and it is Energy; a second bar is not reachable
# without client work.
#
# Both values are emitted into dh_progression.h and read by the module, so they are declared
# here rather than in the C++: the cap has to agree with the CumulativeAura cell the generator
# writes onto the aura record, and a header constant that disagrees with the data is the
# failure this file exists to prevent.
FELFURY_MAX_STACKS = 5
INNER_DEMON_MS_PER_FELFURY = 5000

SHAPESHIFT_FORM_ID = 23
SHAPESHIFT_FORM_NAME = "Inner Demon"

# Illidan Stormrage, The Betrayer -- creature 22917's display, read from creature_template_model
# on the live realm. Wings, horns, blindfold, warglaives: the demon-hunter silhouette. It is a
# male night elf demon for every race and gender, which is a deliberate trade of personalisation
# for iconography.
METAMORPHOSIS_DISPLAY_ID = 21135

# NO `player_shapeshift_model` ROWS, DELIBERATELY.
#
# `Unit::GetModelForShapeshift` (Unit.cpp:15455-15482) consults that table first and falls back
# to the form's own DBC row:
#
#     if (uint32 ModelId = sObjectMgr->GetModelForShapeshift(form, ToPlayer())) return ModelId;
#     ... modelid = TeamIdForRace(getRace()) == TEAM_ALLIANCE ? formEntry->modelID_A
#                                                             : formEntry->modelID_H;
#
# The table is keyed by the four-tuple (form, race, customizationID, genderID) -- it exists so a
# druid's cat form can vary with hair colour, which is a problem this class does not have. Every
# Demon Hunter is Illidan, so the DBC row's two model columns (both set to
# METAMORPHOSIS_DISPLAY_ID, alliance and horde) already say exactly that, in two cells instead
# of one row per race per gender per customization.
#
# If a per-race demon is ever wanted, it becomes rows in that table -- note the real column
# names, which are NOT what they look like: ShapeshiftID, RaceID, CustomizationID, GenderID,
# ModelID. A model that is not in CreatureDisplayInfo.dbc makes the loader skip the row with a
# log line rather than fail (ObjectMgr.cpp:1874-1879); 21135 is present and resolves to
# Creature\Illidan\Illidan.mdx, verified.

# =============================================================================================
# GAMETABLES -- the class-10 blocks Blizzard left full of placeholders
# =============================================================================================
#
# These are not zeroes, which would at least be obviously broken. gtChanceToMeleeCritBase row 9
# is **0.2** -- twenty percent base melee crit -- and gtOCTRegenHP's class-10 block is a flat
# 1.0. Read, not assumed: the live `gtchancetomeleecritbase_dbc` has ID 9 = 0.2 today.
#
# Every one is fixed by copying the Rogue block. The generator reads the source rows out of the
# live override tables and re-emits them under the class-10 IDs, so there is no transcription.
GAMETABLES = dbc_tables.CLASS_GAMETABLES
GAMETABLE_RATING_SCALAR = dbc_tables.GT_CLASS_COMBAT_RATING_SCALAR

# =============================================================================================
# SCALING
# =============================================================================================
#
# The Death Knight's curve normalises to its stock rank at level 55, because every DK ability
# has one. A Demon Hunter ability has no stock rank at any level -- the class did not exist --
# so the ladder runs to 80 and the two anchors are read off REAL LADDERS in Spell.dbc rather
# than off the ability itself.
#
# Both anchors are (first_rank_spell_id, last_rank_spell_id) pairs. dhspells.py reads all four
# records, asserts the first is BaseLevel 1 and the last is BaseLevel >= 79, and computes the
# ratio from the cells. Nothing about their values is written down here, so a DBC that
# disagrees with this file is impossible rather than merely unlikely.

RANK_STEP = 6                   # levels between consecutive custom ranks
POWER_TOP_LEVEL = 80            # power(80) == 1 by definition. No handoff: there is nothing
                                # above the top custom rank, because there is no stock rank.
MIN_DIE_SIDES = 3               # a die of 1 rolls one fixed number, which reads as a bug in a
                                # tooltip that says "$m1 to $M1"

# WEAPON-FLAT ANCHOR -- Sinister Strike, rank 1 (1752, BaseLevel 1) to rank 12 (48638,
# BaseLevel 80). Verified: Effect_1 = 121 SPELL_EFFECT_WEAPON_DAMAGE throughout,
# EffectDieSides 1 throughout, EffectBasePoints 2 -> 179, i.e. a value of 3 at level 1 and 180
# at level 80. It is the right anchor for two reasons beyond convenience: it is the same
# resource system (energy, 1.0s GCD, StartRecoveryCategory 133 / StartRecoveryTime 1000), and
# it is a flat bonus added to a weapon swing, which is what Demon's Bite and Chaos Strike are.
POWER_ANCHOR_WEAPON = (1752, 48638)

# SPELL-DAMAGE ANCHOR -- Shadow Bolt, rank 1 (686, BaseLevel 1) to rank 13 (47809, BaseLevel
# 79). Verified: Effect_1 = 2 SPELL_EFFECT_SCHOOL_DAMAGE, (11, 5) -> average 14 at level 1 and
# (689, 81) -> average 730 at level 79. Used for self-contained spell damage -- Eye Beam,
# Immolation Aura, Sigil of Flame, Throw Glaive -- where the base points ARE the whole hit.
#
# 79 and not 80 because Shadow Bolt's ladder ends there; the generator normalises by the
# anchor's own top level rather than assuming 80, so this is exact rather than approximate.
POWER_ANCHOR_SPELL = (686, 47809)

# SpellEffects.h: the effect types whose EffectBasePoints is a FLAT addition to a weapon swing
# rather than self-contained damage. 121 SPELL_EFFECT_WEAPON_DAMAGE and 58
# SPELL_EFFECT_WEAPON_DAMAGE_NOSCHOOL. Derived from the DBC at generate time rather than trusted
# from this list alone.
WEAPON_DAMAGE_EFFECTS = frozenset((58, 121))

# DELIBERATE OVERTUNE, tapering to nothing at 80.
#
# Identical in shape to the Death Knight's, and for the same reason: the curve above puts a
# low-level Demon Hunter exactly alongside its peers, and the realm wants them a little ahead of
# that where the class is thinnest. Applied to the RATIO rather than to the final cell, so it
# lands identically on damage, on flat weapon bonuses and on a stat buff instead of needing a
# rule per effect type.
#
#     factor(L) = 1 + (OVERTUNE - 1) * (1 - base_ratio(L))
#
# ~+9.2% at level 1, ~+1% near the top, exactly 0 at 80. The taper is not cosmetic: a flat +10%
# with a clamp rounds the top custom rank into the same integer as the rank below it.
OVERTUNE = 1.10


def power(level, anchor_at_1, anchor_top_level):
    """Fraction of top-rank power appropriate at `level`. power(anchor_top_level) == 1.

    `anchor_at_1` is value(level 1) / value(top) for the relevant anchor ladder, computed by
    dhspells.py from Spell.dbc. Linear in level, exactly as the Death Knight's is -- the shape
    was validated against real content there and there is no reason for this class to differ.
    """
    return anchor_at_1 + (1.0 - anchor_at_1) * (level - 1) / (anchor_top_level - 1)


def scale_cell(stock_base_points, stock_die_sides, level, anchor_at_1, anchor_top_level):
    """(EffectBasePoints, EffectDieSides) for a custom rank, from the donor's top-rank pair.

    CalcValue (SpellInfo.cpp:429-445) turns the pair into a value three different ways, so this
    does too rather than pretending one formula covers all of them:

        DieSides 0  -> the value is BasePoints exactly
        DieSides 1  -> the value is BasePoints + 1, a fixed number
        DieSides N  -> the value is BasePoints + irand(1, N)
    """
    ratio = power(level, anchor_at_1, anchor_top_level)
    ratio *= 1.0 + (OVERTUNE - 1.0) * (1.0 - ratio)
    if stock_die_sides == 0:
        return int(round(stock_base_points * ratio)), 0
    if stock_die_sides == 1:
        return int(round((stock_base_points + 1) * ratio)) - 1, 1
    die = max(MIN_DIE_SIDES, int(round(stock_die_sides * ratio)))
    avg = (stock_base_points + (stock_die_sides + 1) / 2.0) * ratio
    return int(round(avg - (die + 1) / 2.0)), die


@dataclass(frozen=True)
class ScalingCell:
    """One Spell.dbc value that re-ranks, named by its EffectBasePoints column."""

    base_points: str
    die_sides: str
    what: str                       # for the generated comment, e.g. "Chaos damage"
    weapon_flat: bool = False       # selects the weapon anchor rather than the spell anchor


def effect_cells(effect_index, what, weapon_flat=False):
    return ScalingCell(f"EffectBasePoints_{effect_index}", f"EffectDieSides_{effect_index}",
                       what, weapon_flat)


# =============================================================================================
# THE ABILITY LADDER
# =============================================================================================
#
# WHY MOST OF THESE HAVE NO RANKS, AND WHY THAT IS BETTER THAN THE DEATH KNIGHT'S NINE
# ------------------------------------------------------------------------------------
# The Death Knight re-ranks because Blizzard re-ranks: every DK ability has a stock rank ladder
# whose numbers are absolute, and a level-10 Death Knight holding the level-55 record would hit
# for the level-55 number. `dk_spec.py:146-180` applies exactly that test -- eight of its
# twenty-eight abilities scale, the other twenty ship as the stock record because "there is
# nothing in them to scale".
#
# The same test applied here comes out overwhelmingly the other way, for two reasons that are
# properties of the donors rather than of the design:
#
#   1. SPELL_EFFECT_WEAPON_PERCENT_DAMAGE (31) is level-correct by construction. "$s1% weapon
#      damage" is right at level 1 and at level 80 from ONE record, because the weapon is what
#      scales. Every melee strike in the kit uses it.
#   2. For an absolute number, `SpellEffectInfo::CalcValue` (SpellInfo.cpp:409-427) already
#      ramps it per level from `EffectRealPointsPerLevel`, uncapped as long as `MaxLevel` is 0.
#      Stock precedent, read from the file: 50590 Immolation is (250, +11.5/level), 20153
#      Immolation is (24, +0.5), 30283 Shadowfury is (342, +1.6).
#
# So a Demon Hunter ability is one record that is correct at every level, instead of nine
# records plus a `spell_ranks` chain plus a supersede graph plus the AcquireMethod trap. The
# rank machinery above (RANK_STEP, power(), scale_cell(), OVERTUNE) is kept because it is how
# the two anchored ladders are built and because a future ability may need it -- not because
# most of these use it.
#
# THE PRICE, AND IT IS NOT YET PAID: with a rank ladder the client's tooltip is a literal
# string in the record it is reading, so it cannot be wrong. With `EffectRealPointsPerLevel`
# the client has to do the same per-level arithmetic the server does in order to render `$s1`.
# It is believed to (that is how stock Immolation Aura reads correctly at every level) but this
# has NOT been verified on this client, and it is the first thing to check in game. Where an
# ability could reasonably be built either way, the weapon-percent form is preferred precisely
# because it sidesteps the question.

# `EffectLeapBack` -- SpellEffects.cpp:5060-5072 -- ends with
#
#     unitTarget->JumpTo(speedxy, speedz, m_spellInfo->SpellFamilyName != SPELLFAMILY_HUNTER);
#
# and `Unit::JumpTo` (Unit.cpp:15490) opens `float angle = forward ? 0 : M_PI;`. So `forward` is
# false -- i.e. the leap goes BACKWARD -- if and only if the spell's family is 9. There is no
# other input. A Vengeful Retreat carrying the Demon Hunter's family 12 would leap the player
# FORWARDS, into the thing they are retreating from.
#
# It is therefore family 9, with SpellClassMask_1/2/3 all zero. The zeroed masks are what make
# that safe: `IsAffected` requires a non-zero mask overlap, so no hunter talent, glyph or set
# bonus can reach it -- and no Demon Hunter talent can either, which is an accepted loss
# because a fixed-distance leap has nothing worth modifying.
VENGEFUL_RETREAT_FAMILY_WHY = "SpellEffects.cpp:5067 -- family 9 is the only thing that makes " \
                              "LEAP_BACK go backwards"
SPELLFAMILY_HUNTER = 9

# Effect ids referenced by name below, so the table reads as intent rather than as integers.
EFFECT_SCHOOL_DAMAGE = 2
EFFECT_APPLY_AURA = 6
EFFECT_WEAPON_PERCENT_DAMAGE = 31
EFFECT_WEAPON_DAMAGE = 121
EFFECT_LEAP_BACK = 138
EFFECT_CHARGE_DEST = 149
EFFECT_JUMP_DEST = 42


@dataclass(frozen=True)
class Ability:
    """One Demon Hunter ability: what to clone, when it is learned, and how it scales.

    `donor` is the stock spell whose 234-cell record is memcpy'd. It is chosen for MECHANICS,
    not for name -- unlike the Death Knight, where the donor is the same ability's stock rank 1.
    Nine of these clone a family-0 creature or item spell and therefore drag in nothing at all.

    `scaling` is empty for an ability that needs no per-level number: either its damage is a
    percentage of weapon damage, or it has no magnitude. Where it is non-empty the ability gets
    either a rank ladder (`ranks` > 1) or a single record with EffectRealPointsPerLevel.
    """

    key: str                              # must be a key in ABILITY_BLOCKS or SINGLES_ORDER
    name: str
    level: int                            # learn level; also BaseLevel and SpellLevel
    donor: int                            # stock spell id to clone
    summary: str                          # one line, for the generated comment and the docs
    cost: int = 0                         # flat Fury (energy) cost
    cooldown_ms: int = 0                  # RecoveryTime; 0 leaves the donor's
    ranks: int = 1                        # 1 = a single record, > 1 = a rank ladder
    scaling: Tuple[ScalingCell, ...] = ()
    family: Optional[int] = None          # None = the class family; 9 for Vengeful Retreat only
    second_record: Optional[str] = None   # ability key of the triggered half, if any
    note: str = ""                        # why this donor, in one line

    # ---- IMPORTED ABILITIES -----------------------------------------------------------------
    #
    # `source` names a spell in an ALREADY-BUILT third-party 3.3.5a Spell.dbc whose whole
    # 234-cell record is transplanted, instead of `donor` being cloned and hand-overridden.
    # The two mechanisms are mutually exclusive per ability and the generator asserts it.
    #
    # It is a better starting point than any donor when it exists, because a donor is only ever
    # a shape that RESEMBLES the ability -- its value is in the ~222 cells nobody names -- while
    # an imported record IS the ability, including the cells no one thought to name. `donor` is
    # still required alongside it: it supplies the row that gets cloned before the import
    # overwrites it, so a failed import degrades to the old behaviour instead of to a blank row.
    #
    # `source_ranks` is the rest of the ladder in ascending rank order, EXCLUDING `source`
    # itself, so `len(source_ranks) + 1 == ranks`. Each is transplanted the same way and the
    # levels come from `rank_levels`.
    source: Optional[int] = None
    source_ranks: Tuple[int, ...] = ()
    rank_levels: Tuple[int, ...] = ()     # learn level per rank; rank_levels[0] must == level

    # ---- CELLS THE DEMON HUNTER NEVER NEEDED ------------------------------------------------
    #
    # Each of these is a real Spell.dbc column that the first class left at its donor's value
    # because nothing in that kit cared. An imported kit does care, and every one of them is a
    # cell rather than code -- which is the whole reason they are listed here and not in C++.
    #
    #   mechanic          The ONLY diminishing-returns input for a family the core does not
    #                     know. SpellMgr.cpp:107-263 keys DR off Mechanic, so a snare or fear
    #                     with Mechanic 0 is undiminished and therefore a PvP bug.
    #   target_aura_state Free conditional casting: "only below 35% health" is state 13 and
    #                     "only above 75%" is 23, both checked by SpellInfo.cpp:1824.
    #   stack_amount      CumulativeAura. What caps Felfury at five without a line of code.
    #   proc_flags        ProcTypeMask. Non-zero makes SpellMgr.cpp:2160+ synthesise a proc
    #                     entry from the record alone, so a passive can proc with no spell_proc
    #                     row at all.
    #   ap_bonus/sp_bonus spell_bonus_data. Ascension keeps these in description text and in a
    #                     float column; the core needs them in a table or the ability does not
    #                     scale with gear at all.
    mechanic: int = 0
    target_aura_state: int = 0
    stack_amount: int = 0
    proc_flags: int = 0
    ap_bonus: float = 0.0
    sp_bonus: float = 0.0

    # Supersedes `second_record` for abilities that need more than one triggered half -- Twin
    # Slice fires a main-hand AND an off-hand record. `second_record` is kept so the Death
    # Knight-era entries still parse; the generator reads them as a single-element tuple.
    second_records: Tuple[str, ...] = ()

    def triggered_halves(self):
        """Every triggered-half ability key, from either spelling of the field."""
        if self.second_records:
            return tuple(self.second_records)
        return (self.second_record,) if self.second_record else ()


# The progression, level 1 to 70. Twenty-two abilities, ordered so that the class is complete
# enough to be fun at every stage: a builder and a spender by level 2, the first movement toy at
# 1 and the rest by 20, a defensive at 24, the demon form at 40, and the two channelled
# signature abilities in the fifties.
#
# Double Jump is at level 1 on purpose. It is the single most recognisable thing about the
# class, it costs nothing, and it is a traversal toy rather than power -- gating it behind
# twenty levels would be gating the class's identity behind twenty levels.
#
# THE LEVEL CAP IS 60 TODAY, NOT 80. conf/worldserver.conf:276-277 is
# `# PHASE MaxPlayerLevel p1=60 p2=70 p3=80` with the live value at 60, so this ladder is
# written for the eventual cap and phases in with the realm:
#
#     phase 1 (cap 60)  20 of 22 abilities, Darkness landing exactly at the cap
#     phase 2 (cap 70)  21 -- Infernal Strike
#     phase 3 (cap 80)  all 22, and the top of every scaling curve
#
# That is deliberate and it matches the Death Knight, whose own ladder runs to 65 against the
# same cap. The alternative -- compressing everything below 60 -- would mean re-tuning the whole
# class twice as the realm advances, and would leave nothing to look forward to at 70 and 80.
# What it must NOT do is leave the class feeling unfinished at 60, which is why the count at
# the current cap is 20 and not 15.
# =============================================================================================
# THE LADDER
# =============================================================================================
#
# Imported rather than written here. fs_abilities.py holds the 31 Felsworn abilities, each one
# naming the Ascension record whose 234 cells are transplanted (Ability.source) instead of a
# donor being cloned and hand-corrected. It is a separate module for the same reason
# dh_talents.py is: this file is the CLASS -- ids, races, skills, tabs, the shape of things --
# and that one is the CONTENT.
#
# ABILITY_BLOCKS is a Dict[str, int] there as it was here, and that shape is load-bearing:
# spell_id_for() below indexes it by key, and dhspells.py branches on `key in ABILITY_BLOCKS`
# to decide whether an ability owns a 20-id block or a single id.
from fs_abilities import (                                          # noqa: E402
    ABILITIES,
    ABILITY_BLOCK_ORDER,
    ABILITY_BLOCKS,
    SECOND_SOURCES,
    SINGLES_ORDER,
)

ABILITIES_BY_KEY = {a.key: a for a in ABILITIES}


@dataclass(frozen=True)
class CustomRank:
    """One generated Spell.dbc record and its SkillLineAbility row.

    Carries no cell values on purpose. Everything in the record other than the ID and the level
    is computed by dhspells.py from the donor record, so this object cannot disagree with
    Spell.dbc.
    """

    spell_id: int
    level: int                  # BaseLevel and SpellLevel; also the module's learn level
    rank_number: int            # position in the chain, 1-based
    sla_id: int
    superceded_by: int          # SkillLineAbility.SupercededBySpell -- the next rank, or 0
    # AcquireMethod 2 = SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN (DBCEnums.h:361). It grants
    # the spell AT CHARACTER CREATION and re-grants it at every login via _LoadSkills ->
    # learnSkillRewardedSpells (Player.cpp:14081), with NO level test anywhere in that path. So
    # it is correct for a rank whose level IS 1 and wrong for every other rank -- a rank at
    # level 20 carrying AcquireMethod 2 is in the spellbook at level 1. Set by Ability.ranks,
    # never by hand, and enforced by an invariant.
    acquire_method: int = 0

    @property
    def subtext(self):
        """NameSubtext_Lang_enUS. Client display only; `.spellinfo` is the sole server reader."""
        return f"Rank {self.rank_number}"


# =============================================================================================
# Self-check
# =============================================================================================
#
# Everything here is checkable with no database, no client and no DBC files, which is exactly
# what makes it runnable in CI. The generator's own invariants need all three; these do not, so
# they are the half that can guard a pull request.
#
#     python3 build/modules/mod-demon-hunter/tools/dh_spec.py
#
# It is a `main`, not a test file, for the same reason the rest of this feature is one
# generator: a check that lives next to the data it checks is a check that gets updated with it.

def selftest():
    """Internal consistency of the spec. Returns a list of problems; empty means good."""
    bad = []

    def sid_of(key):
        if key in ABILITY_BLOCKS:
            return spell_id_for(key, 0)
        if key in SINGLES_ORDER:
            return single_spell_id(key)
        return None

    seen = {}
    for a in ABILITIES:
        sid = sid_of(a.key)
        if sid is None:
            bad.append(f"{a.key}: no ID block -- add it to ABILITY_BLOCKS or SINGLES_ORDER")
            continue
        if sid in seen:
            bad.append(f"id {sid} claimed by both {seen[sid]!r} and {a.key!r}")
        seen[sid] = a.key
        if not (SPELL_ID_BASE <= sid < TALENT_SPELL_ID_BASE):
            bad.append(f"{a.key}: id {sid} is outside the ability band "
                       f"{SPELL_ID_BASE}..{TALENT_SPELL_ID_BASE - 1}")
        # A second record that names no block is a spell that will never be emitted, and the
        # ability that triggers it would point at nothing. This caught two real ones.
        if a.second_record and a.second_record not in ABILITY_BLOCKS:
            bad.append(f"{a.key}: second_record {a.second_record!r} has no ID block")
        if not 1 <= a.level <= 80:
            bad.append(f"{a.key}: learn level {a.level} is outside 1..80")

    # A starting-bar button for a spell the character does not have yet renders as a BLANK
    # SLOT, not as an error -- so this has to be checked here or not at all.
    for k in STARTING_BAR_ABILITIES:
        ab = ABILITIES_BY_KEY.get(k)
        if ab is None:
            bad.append(f"starting bar names {k!r}, which is not an ability")
        elif ab.level != 1:
            bad.append(f"starting bar names {k!r}, learned at level {ab.level} and not 1 -- "
                       f"a new character would get a blank button")

    if len(SINGLES_ORDER) > IDS_PER_ABILITY:
        bad.append(f"SINGLES_ORDER has {len(SINGLES_ORDER)} entries but a block holds "
                   f"{IDS_PER_ABILITY}")
    if len(set(SINGLES_ORDER)) != len(SINGLES_ORDER):
        bad.append("SINGLES_ORDER has a duplicate")
    if len(set(ABILITY_BLOCKS.values())) != len(ABILITY_BLOCKS):
        bad.append("ABILITY_BLOCKS has two keys sharing a block index")

    # Vengeful Retreat is the one ability that must NOT carry the class family, because
    # SpellEffects.cpp:5067 makes family 9 the only thing that sends LEAP_BACK backwards.
    vr = ABILITIES_BY_KEY.get("vengeful_retreat")
    if vr and vr.family != SPELLFAMILY_HUNTER:
        bad.append("vengeful_retreat must carry SPELLFAMILY_HUNTER or it leaps FORWARDS -- "
                   + VENGEFUL_RETREAT_FAMILY_WHY)
    for a in ABILITIES:
        if a.key != "vengeful_retreat" and a.family is not None:
            bad.append(f"{a.key}: borrows family {a.family}; only vengeful_retreat may, and "
                       f"only for the reason in VENGEFUL_RETREAT_FAMILY_WHY")

    if CHRCLASS_ROW["SpellClassSet"] in (0, 14, 16) and CHRCLASS_ROW["SpellClassSet"] == 0:
        bad.append("SpellClassSet 0 makes every talent modifier match every spell in the game "
                   "(SpellInfo.cpp:1327)")
    return bad


def main():
    import sys as _sys
    problems = selftest()
    print(f"Demon Hunter spec: class {DH_CLASS}, races "
          f"{[r.race_id for r in DH_RACES]}, family {CHRCLASS_ROW['SpellClassSet']}, "
          f"{len(ABILITIES)} abilities levels "
          f"{min(a.level for a in ABILITIES)}-{max(a.level for a in ABILITIES)}")
    for a in sorted(ABILITIES, key=lambda a: (a.level, a.name)):
        sid = spell_id_for(a.key, 0) if a.key in ABILITY_BLOCKS else single_spell_id(a.key)
        print(f"  L{a.level:<3d} {sid}  {a.name:18s} <- donor {a.donor}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nspec self-check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
