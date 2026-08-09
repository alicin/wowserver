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
#
# Block 5 was reserved for Blood Presence and is now PERMANENTLY VACANT. Blood Presence turned
# out to need no custom rank at all (see FLAT_GRANTS), but 90000-90019 is already live on a real
# character and the whole point of a fixed block map is that an ID never moves once it has been
# in a client's cache. Reusing 90100-90119 for something else later would be the one way to
# break that, so the hole stays.
IDS_PER_ABILITY = 20
ABILITY_BLOCKS = {
    "icy_touch":      0,      # 90000-90019   stock rank 1 = 45477   <- shipped first
    "plague_strike":  1,      # 90020-90039   45462
    "blood_strike":   2,      # 90040-90059   45902
    "death_coil":     3,      # 90060-90079   47541
    "death_strike":   4,      # 90080-90099   49998
    "blood_presence": 5,      # 90100-90119   RESERVED, VACANT -- granted as stock, see above
    "blood_boil":     6,      # 90120-90139   48721
    "death_and_decay": 7,     # 90140-90159   43265
    "horn_of_winter": 8,      # 90160-90179   57330
    # Not abilities anyone learns -- the off-hand halves Threat of Thassarian casts. See
    # MIRROR_CHAINS_WHY.
    "death_strike_offhand": 9,   # 90180-90199   66188
    "blood_strike_offhand": 10,  # 90200-90219   66215
}


def spell_id_for(ability_key, rank_index):
    return SPELL_ID_BASE + IDS_PER_ABILITY * ABILITY_BLOCKS[ability_key] + rank_index


def sla_id_for(spell_id):
    return SLA_ID_BASE + (spell_id - SPELL_ID_BASE)


# ------------------------------------------------------------------ the progression spec --
#
# TWO KINDS OF ABILITY, AND THE TEST THAT SEPARATES THEM
# ------------------------------------------------------
# The brief's table has 28 abilities on it. Only eight of them need a custom rank.
#
# The test is derived, not chosen: *does Blizzard themselves re-rank it?* Diff every stock rank
# of a DK ability against rank 1 cell by cell (tools/dkspells.py --check re-runs exactly this
# diff as invariant #19) and the answer is unambiguous. Eight abilities carry a rank-varying
# ABSOLUTE number -- flat damage, flat heal, flat stat points -- and Blizzard ships 2-6 ranks of
# each to keep that number level-appropriate:
#
#     Icy Touch   EffectBasePoints_1/DieSides_1       126/11 -> 226/19  over 5 ranks
#     Plague Strike EffectBasePoints_1                   124 -> 377     over 6
#     Blood Strike  EffectBasePoints_1                   259 -> 763     over 6
#     Death Coil    EffectBasePoints_1                   166 -> 442     over 5
#     Death Strike  EffectBasePoints_1, _3          111, 405 -> 296,1309 over 5
#     Blood Boil  EffectBasePoints_1/DieSides_1        88/19 -> 179/41  over 4
#     Death and Decay EffectBasePoints_1                  25 -> 61      over 4
#     Horn of Winter EffectBasePoints_1, _2           85, 85 -> 154,154 over 2
#
# The other twenty do not have a single rank in the game, because there is nothing in them to
# scale: they are percentages (all three Presences, Anti-Magic Shell, Icebound Fortitude, Death
# Pact), pure weapon-damage multipliers (Rune Strike), or effects with no magnitude at all
# (Death Grip, Mind Freeze, Pestilence, Chains of Ice, Dark Command, Raise Dead, Path of Frost,
# Blood Tap, Strangulate, Empower Rune Weapon, Army of the Dead, Death Gate, Runeforging).
# A level-20 Anti-Magic Shell that absorbs 75% of magic damage IS the level-68 one; cloning it
# would produce a byte-identical record with a different ID.
#
# So those twenty are granted as the STOCK SPELL at the brief's level -- FLAT_GRANTS below.
# That is safe because a known spell is not level-gated anywhere: the only caster-level tests in
# Spell.cpp are for pet spells (:6142, :6164) and item enchants (:7491, :7571), CalcValue only
# consults BaseLevel/SpellLevel when EffectRealPointsPerLevel is non-zero (SpellInfo.cpp:415-427)
# and CalculateLevelPenalty returns 1.0 whenever MaxLevel is 0 (Unit.cpp:3203-3222), which it is
# for every one of them. It is also the cheapest possible implementation: no ID, no DBC record,
# no SkillLineAbility row, no spell_ranks chain, no client patch entry, and nothing that can
# drift from Blizzard's data because it IS Blizzard's data.
#
# WHY SIX LEVELS BETWEEN CUSTOM RANKS
# -----------------------------------
# Blizzard's own DK rank spacing, read off the stock file: Icy Touch 55/61/67/73/78, Plague
# Strike 55/60/65/70/75/80, Death and Decay 60/67/73/80. Six levels, give or take. Starting at
# level 1 and stepping 6 lands the ladder on 1, 7, 13, 19, 25, 31, 37, 43, 49 -- and the next
# step would be 55, which is exactly where the stock rank already sits. The cadence and the
# handoff agree without either being forced. Nine custom ranks over fifty-four levels is the
# same rank density Blizzard uses over levels 55-80; one rank every other level would be
# twenty-five rows of noise and one rank for the whole range would leave a level-50 Death Knight
# hitting for level-1 numbers.
#
# THE POWER CURVE, AND THE SINGLE NUMBER IT IS ANCHORED ON
# --------------------------------------------------------
# There is exactly one hand-calibrated number in this whole feature, and it is already live and
# verified in production: Icy Touch rank 1 does 10-12 at level 1. It was calibrated against real
# level-1 content parsed out of Spell.dbc -- 133 Fireball rank 1 is 14-22 over a 1.5s cast, 78
# Heroic Strike rank 1 is +11 on a swing -- and a Blood Elf DK on the live realm shows that
# tooltip and rolls that damage.
#
# Stock Icy Touch rank 1 averages 132. So the shipped anchor says: level-1 power is 11/132 of
# level-55 power, which is 1/12 exactly. Everything else follows from that one ratio:
#
#     power(L) = 1/12 + (11/12) * (L - 1) / 54          power(1) = 1/12, power(55) = 1
#
# and a custom rank's value for any cell is the STOCK rank-1 value of that same cell scaled by
# power(L) / power(handoff level). Linear, two-point-anchored, no free parameters, and it
# reproduces the shipped 10-12 exactly (see scale_cell). Nothing is typed in twice: the stock
# values are read out of Spell.dbc at generate time, never transcribed here.
#
# Abilities that hand over above 55 (Blood Boil 58, Death and Decay 60, Horn of Winter 65) are
# normalised by power(handoff) rather than power(55), so "the rank you have at level L is
# power(L) of what the first stock rank is worth" holds for all eight uniformly.

RANK_STEP = 6                   # levels between consecutive custom ranks
POWER_TOP_LEVEL = 55            # power(POWER_TOP_LEVEL) == 1 by definition
POWER_AT_LEVEL_1 = 11.0 / 132.0  # = 1/12, from the live, verified Icy Touch rank 1
# A low rank whose die sides scale to 1 would roll one fixed number, which reads as a bug in a
# tooltip that says "$m1 to $M1". Three is the smallest spread that still looks like a damage
# range, and it is what the shipped rank 1 already uses.
MIN_DIE_SIDES = 3

# A SECOND ANCHOR, for flat bonuses added to WEAPON damage.
#
# The 1/12 curve above is calibrated on Icy Touch, where the stock number IS the whole damage.
# Blood Strike's +260 is not: it is a flat bonus added on top of a weapon swing, and the weapon
# itself scales ~20x between level 1 and 55. Taking 1/12 of the level-55 bonus therefore means
# something completely different at each end -- at 55, +260 roughly triples a ~100 hit; at level
# 1, +22 turns a 2-5 hit into 24-27. Same fraction of the stock bonus, an order of magnitude
# more impact. That is a methodology bug, not a tuning preference.
#
# Fixed the same way the spell curve was: anchor on a real peer at the same level, read from
# Spell.dbc rather than asserted. Heroic Strike rank 1 (spell 78, BaseLevel 1) is +11, which is
# the closest analogue any class gets at level 1. Blood Strike stock rank 1 is +260, so
# 11/260 -- roughly half the spell ratio. Corroborated on the other two: Plague Strike lands at
# +5 against Raptor Strike rank 1's +5, and Death Strike at +5 arriving at level 6.
#
# Both curves still reach 1.0 at the handoff, so the 55 transition is unchanged.
POWER_AT_LEVEL_1_WEAPON = 11.0 / 260.0

# SpellEffects.h: the effect types whose EffectBasePoints is a FLAT addition to a weapon swing.
# 121 SPELL_EFFECT_WEAPON_DAMAGE and 58 SPELL_EFFECT_WEAPON_DAMAGE_NOSCHOOL. Derived from the
# DBC at generate time (invariant #24) rather than trusted from this list alone.
WEAPON_DAMAGE_EFFECTS = frozenset((58, 121))


def power(level, weapon_flat=False):
    """Fraction of first-stock-rank power appropriate at `level`. power(55) == 1.

    `weapon_flat` selects the second anchor, for flat bonuses added to a weapon swing rather
    than for self-contained spell damage. See POWER_AT_LEVEL_1_WEAPON.
    """
    at1 = POWER_AT_LEVEL_1_WEAPON if weapon_flat else POWER_AT_LEVEL_1
    return at1 + (1.0 - at1) * (level - 1) / (POWER_TOP_LEVEL - 1)


# DELIBERATE OVERTUNE, 1..54 only.
#
# The curve above is calibrated to sit a low-level DK ALONGSIDE its peers. The user wants them
# noticeably ahead of that: +10% on every custom rank. Applied to the RATIO rather than to the
# final cell so it lands identically on damage, on flat weapon bonuses and on Horn of Winter's
# stat buff, instead of needing a separate rule per effect type.
#
# It TAPERS to nothing at the handoff, rather than being a flat multiplier with a clamp. A flat
# +10% was tried first and invariant #19 rejected it: the top custom rank of five abilities
# already sits at ~90-99% of stock, and +10% rounded it to the SAME INTEGER as the level-55 rank
# it hands off to -- a level-49 Blood Boil hitting for exactly what the level-58 one does. A
# ceiling constant does not fix that either, because the collision happens in the rounding.
#
#     factor(L) = 1 + (OVERTUNE - 1) * (1 - base_ratio(L))
#
# so the boost is full strength where the character is weakest and fades as the stock rank
# approaches: ~+9.2% at level 1, ~+1.0% at level 49, exactly 0 at the handoff. That is also the
# more defensible shape -- the early levels are where a DK feels thin, and the top custom rank is
# where an overtune would break the 55 transition.
OVERTUNE = 1.10


def scale_cell(stock_base_points, stock_die_sides, level, handoff_level, weapon_flat=False):
    """(EffectBasePoints, EffectDieSides) for a custom rank, from the stock rank-1 pair.

    CalcValue (SpellInfo.cpp:429-445) turns the pair into a value three different ways, so this
    does too rather than pretending one formula covers all of them:

        DieSides 0  -> the value is BasePoints exactly
        DieSides 1  -> the value is BasePoints + 1, a fixed number
        DieSides N  -> the value is BasePoints + irand(1, N), i.e. BasePoints+1 .. BasePoints+N

    Sanity check on the third case, which is the one the whole curve is anchored on:
    Icy Touch stock is (126, 11) -> average 132, and at level 1 the ratio is 1/12, so
    die = max(3, round(11/12)) = 3, average = 11, base = round(11 - 2) = 9 -> 10 to 12. That is
    the record that is live on the realm today, reproduced by formula rather than by hand.
    """
    ratio = power(level, weapon_flat) / power(handoff_level, weapon_flat)
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
    """One Spell.dbc value Blizzard re-ranks, named by its EffectBasePoints column.

    `die_sides` is the paired EffectDieSides column, which is always the same index. Both are
    read from the clone source at generate time; nothing about their stock values is written
    down here, so a DBC that disagrees with this file is impossible rather than merely unlikely.
    """

    base_points: str
    die_sides: str
    what: str                       # for the generated comment, e.g. "Frost damage"
    # True when this cell is a FLAT addition to a weapon swing rather than self-contained
    # damage. Selects the weapon anchor; see POWER_AT_LEVEL_1_WEAPON.
    weapon_flat: bool = False


def effect_cells(effect_index, what, weapon_flat=False):
    return ScalingCell(f"EffectBasePoints_{effect_index}", f"EffectDieSides_{effect_index}", what,
                       weapon_flat)


@dataclass(frozen=True)
class CustomRank:
    """One generated Spell.dbc record and its SkillLineAbility row.

    Deliberately carries NO cell values. Everything that ends up in the record other than the ID
    and the level is computed by dkspells.py from the stock record it clones, so this object
    cannot disagree with Spell.dbc.
    """

    spell_id: int
    level: int                  # BaseLevel and SpellLevel; also the module's learn level
    rank_number: int            # position in the renumbered chain, 1-based
    sla_id: int
    superceded_by: int          # SkillLineAbility.SupercededBySpell -- the next rank
    # AcquireMethod 2 = SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN (DBCEnums.h:361). It grants the
    # spell AT CHARACTER CREATION and re-grants it at every login via _LoadSkills ->
    # learnSkillRewardedSpells (Player.cpp:14081), with no level test anywhere in that path
    # (Player.cpp:12237-12311 filters on race, class and MinSkillLineRank only). So it is correct
    # for a rank whose level IS 1 and wrong for every other rank -- a level-2 Death Coil carrying
    # AcquireMethod 2 would be in the spellbook at level 1. Ranks 2+ are 0, which is also
    # mod-learn-spells' filter (mod_learnspells.cpp:446), so that module agrees with us instead
    # of fighting us. Enforced by invariant #6, set by Ability.ranks, never by hand.
    acquire_method: int = 0

    @property
    def subtext(self):
        """NameSubtext_Lang_enUS. Client display only; `.spellinfo` is the sole server reader."""
        return f"Rank {self.rank_number}"


@dataclass(frozen=True)
class Ability:
    """One re-ranked ability: what to clone, where it starts, and which cells scale."""

    key: str
    name: str
    clone_from: int                    # stock Spell.dbc record to memcpy == stock_chain[0]
    skill_line: int                    # SkillLine.dbc id: 770 Blood, 771 Frost, 772 Unholy
    stock_chain: Tuple[int, ...]       # stock ranks, low to high, starting with clone_from
    intro_level: int                   # the brief's level -- when rank 1 becomes available
    handoff_level: int                 # BaseLevel of stock_chain[0]; asserted against Spell.dbc
    scaling: Tuple[ScalingCell, ...]   # the cells Blizzard re-ranks, hence the cells we scale
    # spell_bonus_data row shared by every custom rank, or None when the stock chain has no rows
    # at all. SpellMgr::GetSpellBonusData (SpellMgr.cpp:947-961) falls back to the FIRST spell in
    # the chain, and renumbering makes a custom rank the first spell -- so an ability whose stock
    # ranks all carry explicit rows needs its custom ranks to carry them too, and an ability with
    # no rows anywhere must not suddenly acquire one.
    bonus: Optional[Tuple[float, float, float, float, str]] = None
    # spell_script_names entries keyed on the stock chain. See SCRIPT_REBIND_WHY.
    scripts: Tuple[str, ...] = ()
    # Cells that are NOT scaled but must still be overridden on every clone. Today this is only
    # Horn of Winter's SpellInfoCorrections bake -- see HORN_OF_WINTER below.
    extra_overrides: Dict[str, int] = field(default_factory=dict)
    # False for a chain nobody learns and the module never grants: no SkillLineAbility rows, no
    # progression entry, no handoff grant. It exists only so its RANK NUMBERS keep matching
    # something else's. See MIRROR_CHAINS_WHY.
    learnable: bool = True
    mirror_of: Optional[str] = None    # the ability whose rank count this chain must equal

    @property
    def rank_levels(self) -> Tuple[int, ...]:
        """intro, intro+6, ... while still below the stock rank. Never empty."""
        levels, lvl = [], self.intro_level
        while lvl < self.handoff_level:
            levels.append(lvl)
            lvl += RANK_STEP
        assert levels, f"{self.key}: intro level {self.intro_level} is not below the stock rank"
        return tuple(levels)

    @property
    def ranks(self) -> Tuple[CustomRank, ...]:
        levels = self.rank_levels
        ids = [spell_id_for(self.key, i) for i in range(len(levels))]
        chain = ids + list(self.stock_chain)
        return tuple(
            CustomRank(
                spell_id=ids[i],
                level=levels[i],
                rank_number=i + 1,
                sla_id=sla_id_for(ids[i]),
                superceded_by=chain[i + 1],
                # See CustomRank.acquire_method. Only a rank that is genuinely available at
                # character creation may carry 2, and "available at character creation" means
                # level 1 -- there is no level field on SkillLineAbility to say anything else.
                acquire_method=2 if levels[i] == 1 else 0,
            )
            for i in range(len(levels))
        )

    @property
    def chain(self):
        """Full renumbered chain, low to high. Rank N is chain[N-1]; first_spell_id = chain[0]."""
        return tuple(r.spell_id for r in self.ranks) + self.stock_chain

    @property
    def stock_subtext(self) -> Dict[int, str]:
        """Client-only NameSubtext rewrite so the spellbook renumbers with the chain.

        45477 is rank 10 once nine custom ranks sit below it. Computed, never listed: a
        hand-written map silently goes stale the moment a rank is added or removed.
        """
        n = len(self.ranks)
        return {sid: f"Rank {n + i + 1}" for i, sid in enumerate(self.stock_chain)}


# WHY THE spell_script_names ROWS HAVE TO MOVE, AND WHY THEY BECOME POSITIVE
# --------------------------------------------------------------------------
# `spell_script_names.spell_id < 0` means "this script, for every rank of this chain", and
# ObjectMgr::LoadSpellScriptNames (ObjectMgr.cpp:6377-6390) implements it as:
#
#     if (sSpellMgr->GetFirstSpellInChain(spellId) != uint32(spellId)) { LOG_ERROR(...); continue; }
#     while (spellInfo) { insert(spellInfo->Id, script); spellInfo = spellInfo->GetNextRankSpell(); }
#
# Renumbering a chain moves its first spell. The instant 90060 becomes rank 1 of Death Coil, the
# stock row `-47541 spell_dk_death_coil` fails that test and is DROPPED ENTIRELY -- not just for
# the new ranks, for EVERY rank, including the level-80 Death Coil the existing Death Knights on
# this realm cast. Death Coil's Effect_1 is SPELL_EFFECT_DUMMY and the script is the only thing
# that turns it into damage, so losing it means the ability silently does nothing at all. Four of
# the eight re-ranked abilities are in this position: Death and Decay (-43265), Death Coil
# (-47541), Blood Boil (-48721) and Death Strike (-49998). Icy Touch got away with it in the
# shipped slice only because it has no script row.
#
# The custom ranks need the script for the same reason, so the row has to be re-pointed either
# way. It is re-pointed as ONE POSITIVE ROW PER SPELL rather than as a single `-90060`, and the
# reason is blast radius: this feature ships behind a config flag and is expected to be turned
# off and on. If its SQL is ever rolled back while the script row is not, `-90060` resolves to a
# spell that no longer exists, LoadSpellScriptNames logs and `continue`s, and the whole chain --
# including all five stock ranks -- loses its script. Positive rows degrade one spell at a time.
# The unique key is (spell_id, ScriptName), so a re-run is a clean DELETE of exactly the rows
# this generator owns followed by an INSERT of the same set.
SCRIPT_REBIND_WHY = "chain renumbered; see SCRIPT_REBIND_WHY in tools/dk_spec.py"


# THE ACQUIREMETHOD = 2 FLIPS
# ---------------------------
# Stock row 16231 is (16231, 771, 45477, 0, 32, 0, 0, 1, 49896, 2, 0, 0, 0, 0). AcquireMethod 2
# means learnSkillRewardedSpells hands out the LEVEL 55 Icy Touch the instant a Death Knight
# acquires skill 771, which is at character creation. Leave it at 2 and every new DK starts with
# a 127-137 damage nuke and the feature is silently pointless.
#
# The set is DERIVED, not guessed, and invariant #21 re-derives it from the live database and the
# stock DBC on every run: walk every SkillLineAbility row with AcquireMethod = 2 whose SkillLine
# a class-6 character receives from playercreateinfo_skills at creation, keep the ones that pass
# learnSkillRewardedSpells' race and class filters for a Death Knight (Player.cpp:12264-12274 --
# note ClassMask 0 means NO filter, so a row does not have to be ClassMask 32 to fire), and keep
# the ones whose spell has BaseLevel >= 2. That query returns exactly eight rows. Six are the
# abilities this feature re-ranks or grants and are flipped to 0; the other two are on
# AM2_WAIVERS with the reason they are left alone.
STOCK_SLA_FLIPS = {
    16231: (45477, "Icy Touch",      "re-ranked; custom rank 1 (90000) carries AcquireMethod 2"),
    16238: (45462, "Plague Strike",  "re-ranked; custom rank 1 (90020) carries AcquireMethod 2"),
    16616: (45902, "Blood Strike",   "re-ranked; custom rank 1 (90040) carries AcquireMethod 2"),
    16433: (47541, "Death Coil",     "re-ranked, intro level 2 -- nothing in the chain may carry "
                                     "AcquireMethod 2, which would grant it at level 1"),
    17016: (48266, "Blood Presence", "granted as the stock spell by Reconcile() at level 1"),
    17101: (49576, "Death Grip",     "granted as the stock spell by Reconcile() at level 4"),
}

# The other two rows the derivation finds. Both are hidden passives that are part of the Death
# Knight scaffolding rather than abilities on the brief's table, and both are ClassMask 0 rows on
# a DK-only skill line, i.e. exactly the shape that is easy to miss. Listed here so that invariant
# #21 can insist every derived row is either flipped or waived ON PURPOSE, and so that a stock
# data change that adds a ninth row fails the build instead of slipping through.
AM2_WAIVERS = {
    17035: (49410, "Forceful Deflection",
            "hidden passive (SPELL_ATTR0_PASSIVE), converts Strength into parry rating. Not on "
            "the brief's table, has no ranks, and a level-1 DK having it is stock behaviour for "
            "every other stat passive the class gets for free."),
    19641: (56816, "Rune Strike (passive)",
            "hidden enabler aura for 56815 Rune Strike, SPELL_ATTR0_DO_NOT_DISPLAY so it is not "
            "in the spellbook. It arms the after-a-dodge-or-parry window and does nothing at all "
            "until 56815 itself is known, which Reconcile() grants at level 20. Flipping it would "
            "mean re-granting it from the module for no visible difference."),
}


# What the SLA emitter actually applies. Module-level, not per-ability: the derivation above is
# a property of the realm's creation data, not of any one ability, and emitting it from inside an
# ability would mean either duplicating it or arbitrarily attaching six rows to one of them.
STOCK_SLA_EDITS = {sla_id: {"AcquireMethod": 0} for sla_id in STOCK_SLA_FLIPS}


# ------------------------------------------------------------------------- the eight clones --

ICY_TOUCH = Ability(
    key="icy_touch", name="Icy Touch", clone_from=45477, skill_line=771,
    stock_chain=(45477, 49896, 49903, 49904, 49909),
    intro_level=1, handoff_level=55,
    scaling=(effect_cells(1, "Frost damage"),),
    # Values copied from the stock 45477 row. All five stock ranks have explicit rows, so
    # renumbering first_spell_id cannot disturb them; only the new ranks need one.
    bonus=(0.0, 0.0, 0.1, 0.0, "Death Knight - Icy Touch"),
    # No spell_script_names row anywhere in the chain: Icy Touch is SPELL_EFFECT_SCHOOL_DAMAGE
    # plus SPELL_EFFECT_TRIGGER_SPELL(55095 Frost Fever) and needs no script.
)

PLAGUE_STRIKE = Ability(
    key="plague_strike", name="Plague Strike", clone_from=45462, skill_line=772,
    stock_chain=(45462, 49917, 49918, 49919, 49920, 49921),
    intro_level=1, handoff_level=55,
    # Effect_1 is SPELL_EFFECT_WEAPON_DAMAGE_NOSCHOOL: a FLAT addition on top of Effect_2's 50%
    # weapon damage. The 50% needs no scaling -- it already scales with the weapon.
    scaling=(effect_cells(1, "bonus weapon damage", weapon_flat=True),),
)

BLOOD_STRIKE = Ability(
    key="blood_strike", name="Blood Strike", clone_from=45902, skill_line=770,
    stock_chain=(45902, 49926, 49927, 49928, 49929, 49930),
    intro_level=1, handoff_level=55,
    scaling=(effect_cells(1, "bonus weapon damage", weapon_flat=True),),
)

DEATH_COIL = Ability(
    key="death_coil", name="Death Coil", clone_from=47541, skill_line=772,
    stock_chain=(47541, 49892, 49893, 49894, 49895),
    intro_level=2, handoff_level=55,
    # Effect_1 is SPELL_EFFECT_DUMMY and spell_dk_death_coil reads it with GetEffectValue()
    # (spell_dk.cpp:1381) to decide the damage or the heal. Scaling it scales both.
    scaling=(effect_cells(1, "Shadow damage"),),
    scripts=("spell_dk_death_coil",),
)

DEATH_STRIKE = Ability(
    key="death_strike", name="Death Strike", clone_from=49998, skill_line=772,
    stock_chain=(49998, 49999, 45463, 49923, 49924),
    intro_level=6, handoff_level=56,
    # EffectBasePoints_1 is the flat bonus on top of Effect_2's 75% weapon damage.
    # EffectBasePoints_3 is the Effect_3 dummy value Blizzard also re-ranks; the heal itself is
    # NOT taken from it -- spell_dk_death_strike (spell_dk.cpp:1638) uses
    # Effects[EFFECT_0].DamageMultiplier, a percentage of max health that is identical on all
    # five stock ranks and therefore comes across untouched by the clone. _3 is scaled anyway,
    # because the rule is "scale the cells Blizzard re-ranks" and applying it selectively is how
    # a cell gets forgotten.
    scaling=(effect_cells(1, "bonus weapon damage", weapon_flat=True),
             effect_cells(3, "Effect_3 dummy (tooltip only)")),
    scripts=("spell_dk_death_strike",),
)

BLOOD_BOIL = Ability(
    key="blood_boil", name="Blood Boil", clone_from=48721, skill_line=770,
    stock_chain=(48721, 49939, 49940, 49941),
    intro_level=12, handoff_level=58,
    scaling=(effect_cells(1, "Shadow damage"),),
    bonus=(0.0, 0.0, 0.06, 0.0, "Death Knight - Blood Boil"),
    scripts=("spell_dk_blood_boil",),
)

DEATH_AND_DECAY = Ability(
    key="death_and_decay", name="Death and Decay", clone_from=43265, skill_line=772,
    stock_chain=(43265, 49936, 49937, 49938),
    intro_level=26, handoff_level=60,
    # SPELL_EFFECT_PERSISTENT_AREA_AURA. spell_dk_death_and_decay_aura (spell_dk.cpp:378) feeds
    # aurEff->GetAmount() into the 52212 trigger, so this is the per-second damage.
    scaling=(effect_cells(1, "Shadow damage per second"),),
    scripts=("spell_dk_death_and_decay",),
)

HORN_OF_WINTER = Ability(
    key="horn_of_winter", name="Horn of Winter", clone_from=57330, skill_line=771,
    stock_chain=(57330, 57623),
    intro_level=18, handoff_level=65,
    scaling=(effect_cells(1, "Strength"), effect_cells(2, "Agility")),
    # THE ONE CLONE THAT LOSES SOMETHING, AND THE FIX.
    #
    # A clone keeps everything that is keyed on family/mask/icon, which is why cloning is the
    # whole design. It does NOT keep anything the core hardcodes by spell ID. Grepping
    # SpellInfoCorrections.cpp for every stock ID this feature clones returns exactly one hit:
    #
    #     // Horn of Winter, stacking issues
    #     ApplySpellFix({ 57330, 57623 }, [](SpellInfo* spellInfo) {
    #         spellInfo->Effects[EFFECT_1].TargetA = 0;
    #         spellInfo->AttributesEx2 |= SPELL_ATTR2_IGNORE_LINE_OF_SIGHT;   // 0x4
    #     });                                             -- SpellInfoCorrections.cpp:835-840
    #
    # Without it a cloned Horn of Winter re-applies its own party aura on top of itself. Both
    # mutations are plain Spell.dbc cells, so they are baked into the clone instead: EFFECT_1's
    # TargetA is ImplicitTargetA_2, and AttributesEx2 is stock 0 for both ranks, so the corrected
    # value is 4. Invariant #22 re-greps the pinned core for every cloned ID and fails if a
    # second ability ever grows a correction that is not baked or waived here.
    extra_overrides={"ImplicitTargetA_2": 0, "AttributesEx2": 4},
)

# MIRROR_CHAINS_WHY -- THE OFF-HAND CHAINS, AND THE NULL DEREFERENCE THEY PREVENT
# ------------------------------------------------------------------------------
# Threat of Thassarian (a Frost talent) makes a dual-wielding Death Knight's strikes hit with the
# off-hand too, and spell_dk_threat_of_thassarian does it like this (spell_dk.cpp:2862):
#
#     spellId = sSpellMgr->GetSpellWithRank(spellId, spellInfo->GetRank());
#
# -- take the RANK NUMBER of the main-hand spell that just landed and ask for the off-hand spell
# with the same rank number. SpellMgr::GetSpellWithRank (SpellMgr.cpp:645-655) walks the chain:
#
#     return GetSpellWithRank(node->rank < rank ? node->next->Id : node->prev->Id, rank, strict);
#
# `node->next` is nullptr on the last rank and there is no check. Stock data never trips it
# because the main-hand and off-hand chains are always the same length -- Death Strike 5 and 5,
# Blood Strike 6 and 6. Renumbering the main-hand chain and not the off-hand one breaks exactly
# that assumption, and the first level-80 Death Knight with Threat of Thassarian and an off-hand
# weapon who lands a Death Strike SEGFAULTS THE WORLDSERVER. Not a tooltip bug, a crash, on a
# realm with people on it.
#
# So the two off-hand chains that have a chain at all get the same nine ranks prepended, scaled by
# the same curve from their own stock rank 1 (which is roughly half the main-hand value -- that is
# what an off-hand hit is). Rank k on one side keeps meaning rank k on the other, at every level,
# which is the property the core script actually relies on.
#
# Plague Strike (66216) and Rune Strike (66217) need nothing: they have no spell_ranks chain at
# all, so GetSpellWithRank finds no node and hands back rank 1 unchanged, exactly as it does
# today. Frost Strike (66196) and Obliterate (66198) have chains but their main-hand spells are
# not re-ranked by this feature, so their rank counts still match.
#
# These two are NOT abilities. They are never learned, never granted, have no SkillLineAbility
# rows and never appear in the progression table -- learnable=False. They exist so that a number
# in one table keeps matching a number in another.

DEATH_STRIKE_OFFHAND = Ability(
    key="death_strike_offhand", name="Death Strike (off-hand)", clone_from=66188,
    skill_line=772, stock_chain=(66188, 66950, 66951, 66952, 66953),
    intro_level=DEATH_STRIKE.intro_level, handoff_level=DEATH_STRIKE.handoff_level,
    scaling=(effect_cells(1, "bonus off-hand weapon damage", weapon_flat=True),),
    learnable=False, mirror_of="death_strike",
)

BLOOD_STRIKE_OFFHAND = Ability(
    key="blood_strike_offhand", name="Blood Strike (off-hand)", clone_from=66215,
    skill_line=770, stock_chain=(66215, 66975, 66976, 66977, 66978, 66979),
    intro_level=BLOOD_STRIKE.intro_level, handoff_level=BLOOD_STRIKE.handoff_level,
    scaling=(effect_cells(1, "bonus off-hand weapon damage", weapon_flat=True),),
    learnable=False, mirror_of="blood_strike",
)

ABILITIES = (ICY_TOUCH, PLAGUE_STRIKE, BLOOD_STRIKE, DEATH_COIL, DEATH_STRIKE,
             BLOOD_BOIL, DEATH_AND_DECAY, HORN_OF_WINTER,
             DEATH_STRIKE_OFFHAND, BLOOD_STRIKE_OFFHAND)

LEARNABLE_ABILITIES = tuple(a for a in ABILITIES if a.learnable)

# Stock IDs whose SpellInfoCorrections entry is deliberately NOT baked into the clone, with the
# reason. Empty today: Horn of Winter is the only cloned ability with a correction and it is
# baked. Kept so invariant #22 has somewhere to point when the next one appears.
CORRECTION_WAIVERS: Dict[int, str] = {}


# ------------------------------------------------------------ the twenty stock-spell grants --
#
# (level, spell id, name, why no custom rank). Reconcile() calls learnSpell on these at the
# level given; the record the player gets is Blizzard's own, unmodified, which is why "clean
# handoff at 55" is trivially true for all of them -- there is nothing to hand over from.

FLAT_GRANTS = (
    (1,  48266, "Blood Presence",      "flat percentages: +15% damage, heal for a % of damage "
                                       "dealt. Identical at level 1 and level 80."),
    (4,  49576, "Death Grip",          "a pull and a taunt. No magnitude to scale."),
    (8,  47528, "Mind Freeze",         "an interrupt plus a school lockout duration."),
    (10, 50842, "Pestilence",          "spreads existing diseases; deals no damage of its own."),
    (14, 45524, "Chains of Ice",       "-95% movement, a percentage."),
    (16, 56222, "Dark Command",        "a taunt."),
    (20, 56815, "Rune Strike",         "150% weapon damage plus an attack-power term. Scales with "
                                       "the weapon and with AP, so it is level-correct already."),
    (20, 48263, "Frost Presence",      "flat percentages: +stamina %, +armour %, -damage taken %."),
    (22, 48792, "Icebound Fortitude",  "-30% damage taken plus a defense-rating term."),
    (24, 48707, "Anti-Magic Shell",    "absorbs 75% of magic damage up to 50% of health. Both "
                                       "percentages."),
    (28, 46584, "Raise Dead",          "summons a ghoul; Guardian::InitStatsForLevel scales it to "
                                       "the owner, so the summon is level-correct by itself."),
    (30, 3714,  "Path of Frost",       "water walking. Boolean."),
    (32, 45529, "Blood Tap",           "converts a Blood rune to a Death rune."),
    (34, 47476, "Strangulate",         "a 5 second silence."),
    (36, 48743, "Death Pact",          "heals 40% of max health. A percentage."),
    (38, 48265, "Unholy Presence",     "flat percentages: +attack speed %, +movement %, -GCD."),
    (40, 47568, "Empower Rune Weapon", "refreshes all runes and grants 25 runic power."),
    (45, 42650, "Army of the Dead",    "summons eight ghouls that scale to the owner. A ten "
                                       "minute cooldown channelled cost, not a number."),
)

# The brief's level 18 entry, Horn of Winter, is deliberately NOT here: it is one of the eight
# re-ranked abilities (HORN_OF_WINTER above), because +86 Strength and Agility -- the level-65
# value -- would roughly double a level-18 character's Strength.

# ------------------------------------------------------------------------ the 55+ handoff ----
#
# The last custom rank of each re-ranked ability is superseded by the first STOCK rank, and this
# is what puts the character on it. Granting it from the module rather than leaving it to
# mod-learn-spells is the difference between a handoff and a dependency: DESIGN.md 4 is explicit
# that mod-learn-spells is redundancy, not a requirement, and with it disabled a level-55 Death
# Knight would otherwise keep the level-49 custom rank for the rest of the game.
#
# Only the FIRST stock rank is granted. Everything above it (Icy Touch rank 11 at 61, and so on)
# is left to whatever grants stock ranks on this realm today -- trainers or mod-learn-spells --
# because that is unchanged by this feature and equally true of every DK ability that was never
# re-ranked. Nothing here is typed in: the level is the handoff level, asserted against
# Spell.dbc BaseLevel by invariant #17.

def handoff_grants() -> List[Tuple[int, int]]:
    return sorted((a.handoff_level, a.stock_chain[0]) for a in LEARNABLE_ABILITIES)


# ------------------------------------------------------- what a clone is allowed to differ in --

# The three cells every custom rank overrides regardless of ability. Everything else that changes
# comes from Ability.scaling and Ability.extra_overrides, and NameSubtext_Lang_enUS is set
# separately because it is a string.
FIXED_OVERRIDE_COLUMNS = {
    "ID": lambda rank, ability: rank.spell_id,
    "BaseLevel": lambda rank, ability: rank.level,
    "SpellLevel": lambda rank, ability: rank.level,
}

# Named rather than by index so a core bump that reorders SpellEntryfmt is a loud failure instead
# of a silent one; dkspells.py asserts the resolved indices equal the ones DESIGN.md 3.3
# documents. Only the five the shipped slice used are pinned -- those are the ones a human has
# checked against the file by hand.
DOCUMENTED_OVERRIDE_INDICES = {"ID": 0, "BaseLevel": 38, "SpellLevel": 39,
                               "EffectDieSides_1": 74, "EffectBasePoints_1": 80}

# NameSubtext_Lang_enUS is set from the spec too. For a rank whose subtext is the one the clone
# source already carries ("Rank 1") it resolves to the same string-block offset and the record
# stays byte-identical to the clone apart from the value cells; dkspells.py asserts that rather
# than assuming it, and counts the cell against the override budget for every other rank.
SUBTEXT_COLUMN = "NameSubtext_Lang_enUS"

# Emitting spell_dbc override rows for the stock ranks would keep `.spellinfo` in step with the
# renumbered client subtexts, at the cost of thirty-seven more 234-column rows in the migration
# for a field whose only server-side reader is a GM command (cs_spellinfo.cpp:759). Off. Turning
# it on needs no other change: the emitter, invariant #4 and --check all follow this flag.
MIRROR_STOCK_SUBTEXT_TO_SQL = False


# --------------------------------------------------------- character creation (A7 - A10) --

DK_CLASS = 6                    # CLASS_DEATH_KNIGHT
TEMPLATE_CLASS = 1              # Warrior -- the class whose level 1-54 STATS A1 copies. This is a
                                # class-wide copy with no race in it (player_class_stats is keyed
                                # (Class, Level)); the per-race template that gear and the spawn
                                # point come from is DkRace.template_class, below.

# A7. Moving the spawn off map 609 does three jobs at once: it makes the entire DK starter
# chain unreachable (every questgiver 12593..12801 spawns only on 609, there are zero
# areatrigger_teleport rows targeting 609, and every chain quest is MinLevel 55), it makes
# CalculateTalentsPoints take the normal branch, and it sets the homebind
# (PlayerStorage.cpp:7187). Nothing about the destination is typed in: map, zone AND x/y/z/o are
# all copied VERBATIM from the race's own template row in the live database. The only thing
# asserted about the result is that it is not Acherus.
FORBIDDEN_CREATE_MAP = 609      # Ebon Hold. An emitted row on this map means the feature is off.

OUTFIT_KEY_COLUMNS = ("RaceID", "ClassID", "SexID", "OutfitID")

# ------------------------------------------------------------------- the DK race table (A7) --


@dataclass(frozen=True)
class DkRace:
    """One playable race, and the class whose level-1 starting data its DK copies.

    `template_class` drives BOTH the spawn point (A7) and the starting kit (A8). Everything
    else about the race -- map, zone, coordinates, orientation, the two CharStartOutfit row ids
    -- is looked up from the live DB and the stock DBC at generate time. Only the choice of
    template, the racial button and the reason live here.
    """

    race_id: int
    name: str
    template_class: int
    template_class_name: str
    # A9. The racial ability's action-bar slot, copied from the stock Blizzard bar for this
    # race's Death Knight (.work/ac-src/data/sql/base/db_world/playercreateinfo_action.sql,
    # lines 58-316). The slot is NOT uniform: race 1 puts its racial on button 11 and race 10
    # on button 6, everyone else on button 10. Reproducing the stock slot keeps the bar looking
    # like the one Blizzard shipped instead of like something this feature invented.
    racial_button: int
    racial_spell: int
    racial_name: str
    why: str = ""               # only set where template_class is not Warrior


# WHY WARRIOR IS THE DEFAULT AND WHERE IT IS NOT
# ----------------------------------------------
# Warrior is the class a Death Knight is closest to at level 1: plate, melee, no resource that a
# DK does not have. Eight of the ten races take it unchanged. The two exceptions were both found
# by query, not by reading lore:
#
#   race 10 Blood Elf -- CANNOT be a warrior on 3.3.5a. `SELECT class FROM playercreateinfo
#     WHERE race = 10` returns 2,3,4,5,6,8,9: no 1. (Blood elf warriors are a Cataclysm
#     addition.) Paladin is the fallback: it is the only other plate-wearing melee class in the
#     game, race 10 has it, and its kit's weapon is 23346 Battleworn Claymore -- a two-handed
#     sword, which a Death Knight is proficient with.
#
#   race 6 Tauren -- CAN be a warrior, and the warrior row is still the wrong template. The
#     Tauren warrior kit (CharStartOutfit 27/63) carries exactly one weapon, 2361 Battleworn
#     Hammer, item SubClass 5 = two-handed mace, which maps to SKILL_2H_MACES (160) at
#     ItemTemplate.h:786. A Death Knight created on this realm never learns skill 160:
#     `SELECT racemask, classmask FROM playercreateinfo_skills WHERE skill = 160` is
#     (1061, 3) -- classmask 3 is warrior|paladin, not 32. PlayerStorage.cpp:2363 then returns
#     EQUIP_ERR_NO_REQUIRED_PROFICIENCY, StoreNewItemInBestSlots (Player.cpp:776-787) falls
#     through to the backpack, and the Tauren Death Knight spawns holding nothing. Confirmed
#     against live data: of the 15 class-6 characters on this realm, 15 have skills 43/44/55/172
#     and only 3 have 160, and those three trained it later.
#     Tauren shaman (Worn Mace, SKILL_MACES 54) and druid (Bent Staff, SKILL_STAVES 136) fail
#     the same test. Hunter is the first Tauren kit that passes: it carries 12282 Worn Battleaxe
#     (SubClass 1 -> SKILL_2H_AXES 172), the same starter two-hander every other Horde melee
#     race gets. Its Old Blunderbuss goes to the backpack, which is cosmetic; no weapon at all
#     is not.
#
# Invariant #16 re-derives both choices from the live database on every run, so if this realm's
# data ever changes underneath them the build fails instead of shipping a weaponless character.
DK_RACES = (
    DkRace(1,  "Human",     1, "Warrior", 11, 59752, "Every Man for Himself"),
    DkRace(2,  "Orc",       1, "Warrior", 10, 20572, "Blood Fury"),
    DkRace(3,  "Dwarf",     1, "Warrior", 10,  2481, "Find Treasure"),
    DkRace(4,  "Night Elf", 1, "Warrior", 10, 58984, "Shadowmeld"),
    DkRace(5,  "Undead",    1, "Warrior", 10, 20577, "Cannibalize"),
    DkRace(6,  "Tauren",    3, "Hunter",  10, 20549, "War Stomp",
           why="the Tauren warrior kit's only weapon is a two-handed mace and a Death Knight "
               "never learns SKILL_2H_MACES (160) on this realm"),
    DkRace(7,  "Gnome",     1, "Warrior", 10, 20589, "Escape Artist"),
    DkRace(8,  "Troll",     1, "Warrior", 10, 26297, "Berserking"),
    DkRace(10, "Blood Elf", 2, "Paladin",  6, 50613, "Arcane Torrent",
           why="blood elves cannot be warriors on 3.3.5a; paladin is the other plate melee class"),
    DkRace(11, "Draenei",   1, "Warrior", 10, 59545, "Gift of the Naaru"),
)

# The order invariant #16 walks when it re-derives template_class: melee-plate first, then the
# remaining melee classes, hunter last because its kit's headline weapon is a ranged one and it
# is only ever picked for the two-handed axe that rides along with it. Classes with no melee
# weapon in their level-1 kit at all (priest, mage, warlock) are deliberately absent -- picking
# one would mean a Death Knight who starts with a staff they cannot hold.
TEMPLATE_CLASS_PREFERENCE = (1, 2, 4, 7, 11, 3)

# ItemTemplate::GetSkill (ItemTemplate.h:782-815), transcribed. Index is the item SubClass; the
# value is the SkillLine id PlayerStorage.cpp:2363 demands a non-zero value in before it will let
# the item be equipped. 0 means "no proficiency needed".
ITEM_CLASS_WEAPON = 2
ITEM_CLASS_ARMOR = 4
WEAPON_SUBCLASS_SKILL = (44, 172, 45, 46, 54, 160, 229, 43, 55, 0, 136, 0, 0, 473, 0, 173, 176,
                         253, 226, 228, 356)
ARMOR_SUBCLASS_SKILL = (0, 415, 414, 413, 293, 0, 433, 0, 0, 0, 0)

# InventoryType values that put a weapon in a hand rather than in the ranged slot
# (ItemTemplate.h:269-283). A kit "has a usable weapon" only if one of these is equippable.
MELEE_INVENTORY_TYPES = (13, 17, 21, 22, 23)    # WEAPON, 2HWEAPON, MAINHAND, OFFHAND, HOLDABLE


def item_required_skill(item_class, item_subclass):
    """The SkillLine id an item demands, or 0. ItemTemplate.h:797-812."""
    if item_class == ITEM_CLASS_WEAPON:
        return (WEAPON_SUBCLASS_SKILL[item_subclass]
                if item_subclass < len(WEAPON_SUBCLASS_SKILL) else 0)
    if item_class == ITEM_CLASS_ARMOR:
        return (ARMOR_SUBCLASS_SKILL[item_subclass]
                if item_subclass < len(ARMOR_SUBCLASS_SKILL) else 0)
    return 0


def race_by_id(race_id) -> Optional[DkRace]:
    for r in DK_RACES:
        if r.race_id == race_id:
            return r
    return None


# A8. CharStartOutfit override, not playercreateinfo_item. The single existing DK row
# (0, 6, 40582, -1) is a REMOVAL directive -- negative counts route into
# PlayerCreateInfoAddItemHelper (ObjectMgr.cpp:4482) which zeroes that itemId inside the
# CharStartOutfit entry. Eighteen negative rows plus a positive kit would log an error per miss.
# Which rows to touch is NOT listed here: dkspells.py resolves both the Death Knight row and the
# template row out of CharStartOutfit.dbc by (RaceID, ClassID, SexID), the same key
# GetCharStartOutfitEntry uses at DBCStores.cpp:880 (race | class << 8 | gender << 16). Only the
# ItemID/DisplayItemID/InventoryType arrays are copied -- RaceID/ClassID/SexID/OutfitID stay as
# the DK row already has them, because they are already correct.
OUTFIT_SEXES = (0, 1)           # male, female -- both are required for every race

# A9. Action bar. 6603 = Attack. Button 1 is the custom rank-1 spell; resolved from the spec,
# never hardcoded. Button `racial_button` is the race's own racial, from the table above.
ACTION_BUTTON_ATTACK = 0
ACTION_BUTTON_RANK1 = 1
ATTACK_SPELL = 6603


def action_bar_for(race: DkRace):
    """[(button, action, type)] for a brand-new Death Knight of `race`."""
    return (
        (ACTION_BUTTON_ATTACK, ATTACK_SPELL, 0),
        (ACTION_BUTTON_RANK1, ABILITIES[0].ranks[0].spell_id, 0),
        (race.racial_button, race.racial_spell, 0),
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
# generated header carries. BOTH ARE 30 BECAUSE THE BRIEF SAYS 30 -- the progression table
# the user specified reads "30: Path of Frost, Death Gate, Runeforging". An earlier draft
# defaulted them to 1, which is not a neutral choice: Death Gate at level 1 drops a
# fresh character into Acherus, which is exactly the starting experience this feature
# exists to skip.
UTILITY_SPELLS = (
    ("DEATH_GATE", 50977, "DKLowLevel.DeathGateLevel", 30),
    ("RUNEFORGING", 53428, "DKLowLevel.RuneforgingLevel", 30),
    # RIDING IS ALREADY HANDLED BY STOCK DATA -- do not grant it here.
    # SkillLineAbility 19184 (skill 762 Riding, ClassMask 32, AcquireMethod 2) grants spell
    # 33391 Journeyman Riding to every Death Knight at character creation, and keeps re-granting
    # it on each login via learnSkillRewardedSpells. Granting 33388 Apprentice Riding at level 20
    # on top of that was worse than redundant: SpellMgr::LoadSpellLearnSkills gives 33388 a
    # SpellLearnSkillNode of step*75, so learning it DOWNGRADES the riding skill value that
    # 33391 had already set. Left alone, a DK simply has Journeyman Riding from level 1 -- which
    # is stock Blizzard behaviour for the class, not something this feature introduced.
)


GRANT_CUSTOM = "custom"         # a generated low rank
GRANT_FLAT = "flat"             # a stock spell with nothing to scale
GRANT_HANDOFF = "handoff"       # the first stock rank of a re-ranked ability


def progression_entries() -> List[Tuple[int, int, str, str]]:
    """[(level, spell id, kind, comment)], sorted by level then spell id.

    The three kinds are all `learnSpell(id)` to Reconcile() and differ only in where the id came
    from, but the generated header labels them, because "why does this level-45 entry point at a
    stock Blizzard spell id" is the first question anyone reading it will have.
    """
    out = []
    for a in LEARNABLE_ABILITIES:
        for r in a.ranks:
            out.append((r.level, r.spell_id, GRANT_CUSTOM, f"{a.name} ({r.subtext})"))
    for level, sid, name, _why in FLAT_GRANTS:
        out.append((level, sid, GRANT_FLAT, f"{name} -- stock spell, nothing to scale"))
    for a in LEARNABLE_ABILITIES:
        out.append((a.handoff_level, a.stock_chain[0], GRANT_HANDOFF,
                    f"{a.name} (Rank {len(a.ranks) + 1}) -- stock {a.stock_chain[0]}, "
                    f"the 55+ handoff"))
    out.sort(key=lambda e: (e[0], e[1]))
    return out


def progression_grants() -> List[Tuple[int, int]]:
    """[(level, spell id)] for the whole progression, sorted by level then id.

    This is what becomes kDkProgression[] in the generated header. Reconcile() walks it in
    order and breaks on the first entry above the player's level, so the sort is load-bearing.
    """
    return [(level, sid) for level, sid, _kind, _c in progression_entries()]


def all_custom_spell_ids() -> List[int]:
    return sorted(r.spell_id for a in ABILITIES for r in a.ranks)


def all_custom_sla_ids() -> List[int]:
    return sorted(r.sla_id for a in LEARNABLE_ABILITIES for r in a.ranks)


def rank_by_spell_id(spell_id) -> Optional[CustomRank]:
    for a in ABILITIES:
        for r in a.ranks:
            if r.spell_id == spell_id:
                return r
    return None


def ability_by_spell_id(spell_id) -> Optional[Ability]:
    for a in ABILITIES:
        if any(r.spell_id == spell_id for r in a.ranks):
            return a
    return None


def _self_check():
    """Cheap structural assertions that need no DBC and no database.

    Everything here is a property of this file alone, so it is checked on import rather than
    from a --check pass: a spec that cannot even describe itself consistently must not be able
    to reach the emitter.
    """
    for a in ABILITIES:
        assert a.key in ABILITY_BLOCKS, f"{a.key} has no reserved ID block"
        assert len(a.ranks) <= IDS_PER_ABILITY, (
            f"{a.key}: {len(a.ranks)} ranks does not fit in a {IDS_PER_ABILITY}-ID block")
        assert a.clone_from == a.stock_chain[0], f"{a.key}: clone source is not stock rank 1"
        assert a.intro_level >= 1
    blocks = [ABILITY_BLOCKS[a.key] for a in ABILITIES]
    assert len(set(blocks)) == len(blocks), "two abilities share an ID block"
    ids = [sid for _l, sid, _k, _c in progression_entries()]
    assert len(set(ids)) == len(ids), (
        "a spell id is granted twice by the progression table: "
        + str(sorted({i for i in ids if ids.count(i) > 1})))
    flat = {sid for _l, sid, _n, _w in FLAT_GRANTS}
    reranked = {s for a in ABILITIES for s in a.chain}
    assert not (flat & reranked), (
        f"granted as both a flat stock spell and part of a re-ranked chain: {flat & reranked}")
    by_key = {a.key: a for a in ABILITIES}
    for a in ABILITIES:
        if not a.mirror_of:
            continue
        principal = by_key[a.mirror_of]
        # The whole reason the mirror exists: GetSpellWithRank walks the off-hand chain by the
        # MAIN-HAND rank number and dereferences node->next without a null check.
        assert len(a.chain) == len(principal.chain), (
            f"{a.key} has {len(a.chain)} ranks, {principal.key} has {len(principal.chain)} -- "
            "spell_dk_threat_of_thassarian will walk off the end of the shorter one")
        assert not a.learnable, f"{a.key} mirrors {a.mirror_of} and must not be granted"


_self_check()
