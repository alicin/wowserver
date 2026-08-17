#!/usr/bin/env python3
"""The three Demon Hunter talent trees, as data. Imported by dhspells.py's `build_talents`.

`.work/dh-parts/talents.md` is the argument; this file is its conclusion, reconciled against the
ability kit that actually exists (`dh_spec.ABILITIES`, `dh_donors.OVERRIDES`) rather than the kit
talents.md assumed. Every donor id below was read out of `/srv/wow/data/dbc/Spell.dbc` with
`build/tools/acdbc`, every effect layout quoted in a comment came off that read, and every core
line number was checked in the pinned checkout at `.work/ac-src`. Nothing here is recalled.

WHAT AN ENTRY IS
----------------
A talent RANK is a spell, and a talent is `ranks` of them sharing one `Talent.dbc` row
(`SpellRank_1..5`). Each rank record is built by `dhspells.build_talents` in four passes:

    1. memcpy the donor                     Talent.donor
    2. apply dhspells.TALENT_BASE           MaxLevel/Category/CategoryRecoveryTime 0, family 16
    3. apply ALWAYS + Talent.overrides      this file, merged at import (see the ALWAYS block)
    4. write ID, Name, NameSubtext, and     the generator's
       overrides[rank_cell] = rank_values[r]

ONLY CELLS THAT CHANGE ARE LISTED, exactly as `dh_donors.py` does it: restating a cell at the
donor's own value is a second place for it to disagree with `Spell.dbc`. Where the reasoning
produced no cell it is a comment.

WHAT THIS FILE DELIBERATELY DOES NOT CARRY
------------------------------------------
  * `ID`, `Name_Lang_enUS`, `NameSubtext_Lang_enUS` -- the generator's.
  * `SpellClassSet` -- `dhspells.TALENT_BASE` writes `dh_spec.CHRCLASS_ROW["SpellClassSet"]`.
  * `MaxLevel`, `Category`, `CategoryRecoveryTime` -- `TALENT_BASE` again.
  * `SpellIconID` / `ActiveIconID` / `SpellVisualID_*` -- the icon survey's job
    (`.work/dh-parts/icon`), the same split `dh_donors.py` makes.
  * `EffectTriggerSpell_*` on the five talents that need a second record: the id belongs to a
    row only the generator can number, so TRIGGERS below names the cell and the generator fills
    it (`dh_donors.py` has the same hole for Fel Rush / Immolation Aura / Eye Beam).

THE TAB IDS ARE 412/413/414, AND THIS WAS CHECKED, NOT TRUSTED
--------------------------------------------------------------
talents.md 1.3 proposes 401/402/403. That is wrong in the sense that matters here: it is not the
block `dh_spec` reserved, and two sources of truth for a DBC id is how a feature ends up with two
half-written tabs. Read out of the stock file with acdbc:

    TalentTab.dbc  33 rows, ids 41..411  -- max is 411, so 401-408 AND 412-420 are all free

401-403 are free as talents.md says; `dh_spec.TALENT_TAB_ID_BASE` is 412 and dh_spec is the
authority the generator reads, so 412/413/414 it is. The stock file's own block layout agrees:
398-400 are the Death Knight's and 409-411 are the three HUNTER PET tabs (Tenacity/Ferocity/
Cunning, `PetTalentMask` 2/1/4), so 412 is the first id past every tab Blizzard shipped and the
DH block stays contiguous instead of being wedged between the DK and the pet tabs.
`Talent.dbc` max id is 2285, so `dh_spec.TALENT_ID_BASE = 2300` is likewise clear.

THE KIT MOVED, AND WITH IT ELEVEN TALENTS
-----------------------------------------
talents.md 3.2 is explicit that its ability->bit table is an assumption ("If the real kit differs,
the bit numbers move and the talents move with them -- the design does not change, only the
`EffectSpellClassMaskA` literals") and 9.2 repeats it. The real kit differs in five ways that
cost more than a literal, and each is carried below as a comment at the talent it touched:

  1. THERE IS NO SHEAR AND NO DEMON SPIKES. The 22 learnable abilities are `dh_spec.ABILITIES`;
     the Vengeance filler is Demon's Bite, the same as Havoc's. Improved Shear became
     Improved Soul Cleave, and Burning Alive / Malevolence name Demon's Bite where they named
     Shear. Demon Spikes came back as a TALENT-GRANTED active at Vengeance (3,1), which is what
     lets Feed the Demon keep its job.
  2. EYE BEAM AND FIERY BRAND ARE BASELINE (levels 56 and 36). Both were talent-granted actives
     in talents.md. Havoc (6,1) is now Glaive Tempest and Vengeance (4,1)'s slot became the
     Feed the Demon / Demon Spikes pair described above.
  3. DEMON'S BITE COSTS NOTHING (`dh_spec.Ability.cost == 0`) and GENERATES 20 Fury on
     `EffectBasePoints_2` (`dh_donors.OVERRIDES["demons_bite"]`). talents.md's "-4 Fury cost of
     Demon's Bite" is therefore a talent that does nothing at all; Improved Demon's Bite adds to
     the generation instead, which is one `EffectMiscValue` away from the same donor.
  4. VENGEFUL RETREAT IS UNREACHABLE. It keeps `SpellClassSet = 9` because family 9 is the only
     thing that makes `SPELL_EFFECT_LEAP_BACK` go backwards (`SpellEffects.cpp:5067`), with all
     three `SpellClassMask` words zero -- and `dh_spec.py:723-725` already names the consequence:
     "no Demon Hunter talent can [reach it] either, which is an accepted loss". `IsAffected`
     needs family 16 == family 16 (`SpellInfo.cpp:1329`), so BOTH talents talents.md hung off
     Vengeful Retreat had to move: Improved Vengeful Retreat became Improved Chaos Nova, and
     Momentum of the Hunt now triggers off Throw Glaive.
  5. SOUL CLEAVE'S HEAL IS `Effect_2`, not `Effect_3`. talents.md 9.2 predicted exactly this
     ("Vengeance 5/1's SpellModOp changes from 23 to 12"); Soul Rending carries `SPELLMOD_EFFECT2`
     (12) and the prediction is what happened.

ONE SCALING CELL PER TALENT
---------------------------
The generator writes exactly one per-rank cell (`cells[rank_cell] = rank_values[r]`), so a design
whose ranks scale two numbers has to give one up. Every such case is in DEGRADED below with what
was dropped and why, rather than being quietly rounded off.

THE CalcValue CONVENTION, WHICH DECIDES EVERY NUMBER IN `rank_values`
---------------------------------------------------------------------
`SpellInfo::CalcValue` (SpellInfo.cpp:430-437) is `basePoints += 1` when `EffectDieSides == 1`
and nothing when it is 0. EVERY donor below carries `EffectDieSides = 1` on the effect the ranks
fill -- read, not assumed, and stated per talent -- so `rank_values` are written one BELOW the
number that lands, which is Blizzard's own convention (13732 Improved Sinister Strike is
`EffectBasePoints_1 = -4` for a tooltip that reads "3") and `dh_donors.py`'s ("EffectBasePoints_2:
19, # PLACEHOLDER -- 20 Fury, because DieSides 1 adds one"). The landing values are in the comment
on every `rank_values` line. The die is NOT zeroed to make the arithmetic prettier: the client
computes the tooltip from the same two cells, and a record whose die disagrees with Blizzard's
own talent rows is a tooltip that disagrees with the server for reasons nobody will find.

Cooldown modifiers (`SPELLMOD_COOLDOWN`, op 11) are in MILLISECONDS: -2001 lands -2000 ms.
Negative values are ordinary for costs, cooldowns and damage taken.

UNVERIFIED, carried through from talents.md 9 and repeated at the talent it touches:
  * Nothing here has been rendered in a client (talents.md 9.1).
  * Every percentage is a design proposal, not a measurement (talents.md 9.5).
  * `SPELL_EFFECT_CHARGE` at 30 yd -- The Hunt (talents.md 9.6).
  * Deathblow loses Cold Blood's charge refund on a fizzled cast, because `Spell.cpp:2702` calls
    `RestoreSpellMods(this, 14177)` on a hardcoded id (talents.md 5, the one named degradation).
  * The proc-flag -> spell-shape mapping on the three proc talents: the `ProcFlags` values were
    read out of `SpellMgr.h:113-134`, but which flag a Demon Hunter ability actually raises has
    not been observed. See FLAGGED.
"""

import os
import sys
from dataclasses import dataclass, field

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TOOLS_DIR)                      # build/modules/mod-demon-hunter
REPO_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "build", "tools"))
sys.path.insert(0, TOOLS_DIR)

from acdbc import dbc_tables                                       # noqa: E402
import dh_donors                                                   # noqa: E402
import dh_spec                                                     # noqa: E402


# =============================================================================================
# THE TABS
# =============================================================================================
#
# Mirrors dh_spec.TALENT_TABS (id, name, OrderIndex) and is asserted against it at the bottom of
# this file, so the two cannot drift. `Talent.tab` is the lowercased name because that is the key
# dhspells.build_talents looks up (`tab_id = {name.lower(): tid ...}`).
TABS = ((412, "Havoc", 0), (413, "Vengeance", 1), (414, "Illidari", 2))

TAB_KEYS = tuple(name.lower() for _id, name, _order in TABS)


# =============================================================================================
# THE ABILITY -> BIT TABLE, IMPORTED RATHER THAN RETYPED
# =============================================================================================
#
# `SpellInfo::IsAffected` (SpellInfo.cpp:1325-1337) is the whole mechanism: the modifier's family
# must equal the spell's, and the modifier's mask must overlap the spell's. dh_donors.py owns the
# allocation, one bit per learnable ability in `SpellClassMask_1`, so it is DERIVED here and never
# copied -- a bit that moves in dh_donors must move every talent keyed on it, and a second copy of
# the table would let it move in only one place.
#
# SECOND RECORDS ARE EXCLUDED ON PURPOSE. Each of the seven carries its PARENT's
# `SpellClassMask_1` bit as well as its own `SpellClassMask_2` bit (dh_donors asserts it, stock
# precedent 51723/52874), so a talent that names `BIT["chaos_strike"]` already reaches the
# off-hand half. Including them here would produce duplicate values and invite a second bit for
# something that must never have one.
BIT = {key: dh_donors.OVERRIDES[key]["SpellClassMask_1"]
       for key in dh_donors.ABILITY_KEYS
       if key not in dh_donors.SECOND_RECORDS and key not in dh_donors._MASKLESS}

# Named unions, so the intent of a mask reads as English at the talent that uses it.
#
# EVERYTHING THAT DEALS DAMAGE. Deathblow's "next offensive ability" and nothing else.
OFFENSIVE = (BIT["demons_bite"] | BIT["chaos_strike"] | BIT["fel_rush"] | BIT["throw_glaive"]
             | BIT["immolation_aura"] | BIT["blade_dance"] | BIT["fiery_brand"]
             | BIT["sigil_of_flame"] | BIT["soul_cleave"] | BIT["eye_beam"] | BIT["chaos_nova"]
             | BIT["infernal_strike"])

# EVERYTHING THAT COSTS FURY AND DEALS DAMAGE -- dh_spec.Ability.cost > 0, minus Imprison, which
# costs 25 and deals nothing, so a damage modifier on it would be a cell with no consequence.
FURY_SPENDERS = (BIT["chaos_strike"] | BIT["throw_glaive"] | BIT["blade_dance"]
                 | BIT["sigil_of_flame"] | BIT["soul_cleave"] | BIT["eye_beam"]
                 | BIT["chaos_nova"])

# THE FIRE KIT. Immolation Aura's damage lives on its tick record, which carries the parent's
# mask_1 bit (dh_donors.SECOND_RECORDS), so this one literal reaches both halves.
FIRE_AOE = BIT["immolation_aura"] | BIT["sigil_of_flame"]


# =============================================================================================
# THE TALENT-GRANTED ACTIVES -- SpellClassMask_3
# =============================================================================================
#
# Eleven talents grant a castable button (`Talent.dbc.Flags = 1`, Player.cpp:14377). Each is a
# spell like any other and needs its own family bit, or a later talent cannot name it -- which is
# exactly what Blizzard does (Mutilate, Overkill and Hunger For Blood all carry mask bits).
#
# They go in `SpellClassMask_3`, which dh_donors reserved for this in as many words:
# "SpellClassMask_3 -- entirely reserved. Nothing is allocated here yet on purpose: talent-granted
# spells and whatever comes after the first 22 get a clean column rather than the tail of a column
# somebody has to count into." Word 1 stays the ability kit's, word 2 stays the second records',
# word 3 is the talents'. A modifier naming one of these sets `EffectSpellClassMaskC_n` -- the
# third word of the modifier's mask against the third word of the spell's
# (`SpellInfo::IsAffected` ANDs the whole 96-bit flags, `SpellInfo.h` `flag96`). Feed the Demon is
# the only talent that does.
#
# Order is the order the talents appear in TALENTS, which is also the order their spell ids are
# allocated. A bit that moves silently repoints whatever was keyed on it, so this list is append-
# only, exactly like dh_spec.ABILITY_BLOCKS.
TALENT_BIT = {
    "glaive_tempest":     0x00000001,   # Havoc     (6,1)
    "deathblow":          0x00000002,   # Havoc     (8,1)
    "chaos_blades":       0x00000004,   # Havoc     (10,1)
    "demon_spikes":       0x00000008,   # Vengeance (3,1)
    "void_reaver":        0x00000010,   # Vengeance (6,1)
    "demonic_fortitude":  0x00000020,   # Vengeance (8,1)
    "nether_bulwark":     0x00000040,   # Vengeance (10,1)
    "netherwalk":         0x00000080,   # Illidari  (4,1)
    "fel_eruption":       0x00000100,   # Illidari  (6,1)
    "vanishing_step":     0x00000200,   # Illidari  (8,1)
    "the_hunt":           0x00000400,   # Illidari  (10,1)
}

# The Metamorphosis form mask, for the three form-gated passives (talents.md 2.C).
# `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1460-1476) walks the player's TALENT
# map on every form change and casts any talent spell that is PASSIVE|DO_NOT_DISPLAY and whose
# `Stances` mask includes the new form -- with no id switch anywhere on the path.
# dh_spec.SHAPESHIFT_FORM_ID is 23, and the cell is a mask of (form - 1).
METAMORPHOSIS_STANCE = 1 << (dh_spec.SHAPESHIFT_FORM_ID - 1)        # 0x00400000

# The canonical passive attribute set, `SharedDefines.h:374-378`:
#   IS_ABILITY 0x10 | PASSIVE 0x40 | DO_NOT_DISPLAY 0x80 | DO_NOT_LOG 0x100
# It is what 40 of the 55 passive donors below already carry, and what talents.md 2.C requires for
# a form-gated passive. Only Nether Resistance has to be written back to it, because its donor is
# an active.
PASSIVE_ATTRS = 0x1D0                                               # 464

# `SPELL_ATTR0_NOT_SHAPESHIFTED` (SharedDefines.h:386). THE TRAP ON FIVE OF THE ELEVEN ACTIVES.
# `SpellInfo::CheckShapeshift` (SpellInfo.cpp:1475) returns SPELL_FAILED_NOT_SHAPESHIFT for a
# spell carrying this bit whenever the current form "acts as shifted" -- which is decided by
# `SHAPESHIFT_FLAG_STANCE` on the form's own row, and dhspells copies form 23's flags from the
# warlock's row 22 (0xd8), which does NOT have that bit. So a Demon Hunter in Metamorphosis
# counts as shifted, and Challenging Shout, Shield Wall, Cold Blood, Consecration and Intercept
# all carry 0x10000 in the stock file. Left alone, five talent buttons grey out in demon form --
# which is the one form this class is built around.
NOT_SHAPESHIFTED = 0x00010000


# =============================================================================================
# THE ALWAYS-APPLIED OVERRIDE SET
# =============================================================================================
#
# Merged UNDER every talent's own cells at the bottom of this file (a talent that wants a
# different value simply sets it). This exists because `dhspells.TALENT_BASE` -- which is the
# generator's, and correctly narrow -- covers only MaxLevel, Category, CategoryRecoveryTime and
# the family. Everything below is a cell that is WRONG ON ANY CLONE and that no talent should
# have to remember.
#
# The same argument, and the same shape, as `dh_donors.ALWAYS`; the contents differ because a
# talent is not an ability. No GCD cells here (a passive has no cast; the eleven actives set
# their own), and no `ShapeshiftMask` exception (the three form-gated talents set it back).
ALWAYS = {
    # ---- the donor's own family mask, which must never survive ------------------------------
    "SpellClassMask_1": 0,          # THE quiet one. dhspells.TALENT_BASE writes SpellClassSet 16
    "SpellClassMask_2": 0,          # onto the clone but leaves the donor's mask, so Chaos Blades
    "SpellClassMask_3": 0,          # (from 12292 Death Wish, mask_1 0x100000) would arrive
                                    # carrying Darkness's bit -- and Long Night, which extends
                                    # "the spell with bit 0x100000", would extend Chaos Blades
                                    # too. Eleven of the donors below carry a non-zero mask.
                                    # The eleven granted actives set mask_3 back to their own bit.
    # ---- the form gate ---------------------------------------------------------------------
    "ShapeshiftMask": 0,            # 12295 Tactical Mastery and 29593 Improved Defensive Stance
                                    # both carry 0x20000 (Defensive Stance) and 20252/20253 carry
                                    # 0x40000. On a PASSIVE this does not fail a cast, it stops
                                    # the passive from ever being applied
                                    # (Player::IsNeedCastPassiveSpellAtLearn, Player.cpp:3401-3408
                                    # only casts it if the stance matches) -- i.e. the talent
                                    # silently does nothing. Set back by the three §2.C talents.
    "ShapeshiftExclude": 0,
    # ---- the energy class ------------------------------------------------------------------
    "PowerType": 3,                 # POWER_ENERGY. 51271 is 5 (runic power), 871/1161/12292/20252
    "ManaCost": 0,                  # /20253 are 1 (rage). Costs are set per active, in Fury.
    "ManaCostPct": 0,               # 26573 Consecration is 22, i.e. 22% of MAX Fury
                                    # (SpellInfo::CalcPowerCost, :2821-2837).
    "RuneCostID": 0,                # 51271 carries 1202. A rune cost on an energy spell is
                                    # unrecoverable, so it is closed rather than trusted.
    # ---- the equipment gate ----------------------------------------------------------------
    "EquippedItemClass": -1,        # 871 Shield Wall is class 4 subclass 64: A SHIELD. A Demon
    "EquippedItemSubclass": 0,      # Hunter never equips one, so Nether Bulwark would be
    "EquippedItemInvTypes": 0,      # uncastable forever, with the client's own "you have no
                                    # shield" error being the only clue. -1 is "no requirement"
                                    # (SpellInfo::CheckItems tests `EquippedItemClass >= 0`).
}


# =============================================================================================
# THE TALENT
# =============================================================================================

@dataclass(frozen=True)
class Talent:
    """One Talent.dbc row plus the `ranks` Spell.dbc rows it points at.

    `tab` is the lowercased tab name, which is the key dhspells.build_talents resolves against
    dh_spec.TALENT_TABS. `prereq` is the GRID POSITION of the arrow's tail plus the 0-BASED rank
    floor -- `(0, 2, 4)` is "Malice, at rank 5", because `Player.cpp:14329` iterates
    `for (rank = DependsOnRank; rank < MAX_TALENT_RANK; ++rank)`. The generator resolves the
    position to a TalentID in a second pass, so declaration order does not matter.
    """

    tab: str                        # "havoc" | "vengeance" | "illidari"
    tier: int                       # TierID, 0-10
    col: int                        # ColumnIndex, 0-3
    ranks: int                      # 1, 2, 3 or 5 -- NEVER 4 (talents.md 1.4)
    name: str
    donor: int                      # stock Spell.dbc id to memcpy
    flags: int = 0                  # Talent.dbc Flags; 1 = grants a spellbook button
    prereq: tuple = None            # (tier, col, rank) of the prerequisite, or None
    rank_values: tuple = ()         # the value written into rank_cell, rank 1 first
    overrides: dict = field(default_factory=dict)   # Spell.dbc cells, EXCLUDING the per-rank one
    rank_cell: str = ""             # which cell rank_values fills
    note: str = ""                  # why this donor, one line


@dataclass(frozen=True)
class Trigger:
    """A second Spell.dbc row that a talent's own record points at.

    Five talents need one. The id is the generator's -- it is allocated out of the same
    92000-92999 band after the rank records -- so `used_by` and `cell` say which record's cell to
    fill in, and nothing here can name an id it cannot know. Same hole, same shape, as
    `dh_donors.py`'s note on EffectTriggerSpell_*.
    """

    donor: int
    used_by: tuple                  # (tab, tier, col) of the talent that triggers it
    cell: str                       # the cell on THAT talent's record to point at this row
    overrides: dict = field(default_factory=dict)
    note: str = ""


# =============================================================================================
# TREE 0 -- HAVOC (412, OrderIndex 0) -- 22 talents, 69 points
# =============================================================================================
#
# tier | col 0                | col 1                | col 2                | col 3
# -----+----------------------+----------------------+----------------------+------------------
#   0  | Demonic Wrath      5 | Improved Demon's B 2 | Malice             5 |
#   1  | Piercing Glaives   5 | Unbound Fury       3 |                      |
#   2  | Insatiable Hunger  1 | Fel Lethality      5 | Blade Rhythm       3 |
#   3  |                      | Furious Throws     3 | Chaos Bloom        5 |
#   4  | Improved Blade Dan 3 | Momentum           1 |                      | Reckless Abandon 3
#   5  |                      | Demonic Appetite   3 | Blind Fury         3 |
#   6  |                      | Glaive Tempest     1 | Unleashed Power    3 |
#   7  | Cycle of Hatred    5 |                      | Serrated Glaives   3 |
#   8  |                      | Deathblow          1 |                      |
#   9  |                      | Demonic Origins    5 |                      |
#  10  |                      | Chaos Blades       1 |                      |
#
# cumulative points by the end of each tier, reproduced from talents.md 5 and re-checked at
# import against `spentPoints >= TierID * 5` (Player.cpp:14360-14362):
#  T0 12 | T1 20 | T2 29 | T3 37 | T4 44 | T5 50 | T6 54 | T7 62 | T8 63 | T9 68 | T10 69
#  gate     5  |   10  |   15  |   20  |   25  |   30  |   35  |   40  |   45  |    50

_HAVOC = (

    # -- 0/0 -- Demonic Wrath ............................. donor 18427 Aggression (family 8)
    #
    # One effect, aura 108 SPELL_AURA_ADD_PCT_MODIFIER with EffectMiscValue_1 = 0
    # (SPELLMOD_DAMAGE, SpellDefines.h:76), DieSides 1, and no baggage at all: Attributes 464,
    # no category, no shapeshift, MaxLevel 0. The single cleanest damage-modifier donor in the
    # file, which is why three talents below use it.
    Talent("havoc", 0, 0, 5, "Demonic Wrath", 18427,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "EffectSpellClassMaskA_1": BIT["demons_bite"] | BIT["chaos_strike"],
               "Description_Lang_enUS":
                   "Increases the damage of your Demon's Bite and Chaos Strike by $s1%.",
           },
           note="18427 -- aura 108 SPELLMOD_DAMAGE(0), one effect, nothing else to strip"),

    # -- 0/1 -- Improved Demon's Bite ..................... donor 13732 Improved Sinister Strike
    #
    # NOT A COST REDUCTION ANY MORE, and this is the reconciliation that would have shipped a
    # dead talent: `dh_spec.ABILITIES` gives Demon's Bite `cost=0` and `dh_donors` gives it
    # `Effect_2 = 30 SPELL_EFFECT_ENERGIZE, EffectBasePoints_2 = 19` (20 Fury). A -4 Fury cost
    # modifier on a free ability is a talent point that buys nothing.
    # The donor is unchanged and so is the aura (107 ADD_FLAT_MODIFIER); only the op moves, from
    # 14 SPELLMOD_COST to 12 SPELLMOD_EFFECT2. DBC `Effect_2` is core EFFECT_1, and CalcValue
    # applies SPELLMOD_EFFECT2 to exactly that index (SpellInfo.cpp:445-455).
    Talent("havoc", 0, 1, 2, "Improved Demon's Bite", 13732,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3),                  # DieSides 1 -> lands +2/+4 Fury on a base of 20
           overrides={
               "EffectMiscValue_1": 12,         # SPELLMOD_EFFECT2 (SpellDefines.h:88), from 14
               "EffectSpellClassMaskA_1": BIT["demons_bite"],
               "Description_Lang_enUS":
                   "Your Demon's Bite generates $s1 additional Fury.",
           },
           note="13732 -- aura 107 flat spellmod; the donor's own -4/DieSides 1 pair is the "
                "proof that the +1 convention holds for negatives too (its tooltip reads 3)"),

    # -- 0/2 -- Malice .................................... donor 14138 Malice (family 0)
    #
    # NO MASK, DELIBERATELY. Aura 52 SPELL_AURA_MOD_WEAPON_CRIT_PERCENT is not a spellmod: it is
    # read by Player::GetUnitCriticalChance with no family and no mask anywhere on the path, so
    # the EffectSpellClassMask cells are dead cells here rather than a missing restriction.
    Talent("havoc", 0, 2, 5, "Malice", 14138,
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 1, 2, 3, 4),         # DieSides 1 -> lands 1/2/3/4/5 %
           overrides={
               "Description_Lang_enUS": "Increases your melee critical strike chance by $s1%.",
           },
           note="14138 -- the rogue talent of the same name, family 0 already, aura 52"),

    # -- 1/0 -- Piercing Glaives .......................... donor 13733 Puncturing Wounds
    #
    # Two effects in stock (Backstab at +10%, Mutilate at +5% via a mask on the SECOND word), and
    # the second is why this needs more than a mask swap: EffectSpellClassMaskB_2 = 6 would land
    # on whatever DH spells ever take word-2 bits, which is the seven second records.
    Talent("havoc", 1, 0, 5, "Piercing Glaives", 13733,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "EffectSpellClassMaskA_1": BIT["chaos_strike"],
               "Effect_2": 0,                   # the Mutilate half, mask and all
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Chaos Strike by $s1%.",
           },
           note="13733 -- aura 107 SPELLMOD_CRITICAL_CHANCE(7); flat, so it adds crit CHANCE to "
                "one ability rather than to the character"),

    # -- 1/1 -- Unbound Fury .............................. donor 31122 Vitality (family 0)
    #
    # Aura 110 SPELL_AURA_MOD_POWER_REGEN_PERCENT with EffectMiscValue_1 = 3 POWER_ENERGY, which
    # is the same power the Demon Hunter uses (dh_spec.CHRCLASS_ROW DisplayPower 3), so the misc
    # value needs no change. The donor's Effect_2 is already 0 but its die and base points are
    # not; they are dead cells on a dead slot and are cleared for the same reason dh_donors
    # clears fel_rush's EffectMechanic_3.
    Talent("havoc", 1, 1, 3, "Unbound Fury", 31122,
           rank_cell="EffectBasePoints_1",
           rank_values=(7, 15, 23),             # DieSides 1 -> lands 8/16/24 %
           overrides={
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS": "Increases your Fury regeneration rate by $s1%.",
           },
           note="31122 -- aura 110 misc 3; POWER_ENERGY is Fury on this class"),

    # -- 2/0 -- Insatiable Hunger ......................... donor 14983 Vigor (family 8)
    #
    # One rank, so the value is an ordinary override rather than a rank_cell. The donor's
    # SpellClassMask_2 = 4194304 is a rogue mask on the SPELL, not on the effect, and is cleared
    # by ALWAYS.
    Talent("havoc", 2, 0, 1, "Insatiable Hunger", 14983,
           overrides={
               "EffectBasePoints_1": 19,        # DieSides 1 -> +20 maximum Fury
               "Description_Lang_enUS": "Increases your maximum Fury by $s1.",
           },
           note="14983 -- aura 35 MOD_INCREASE_ENERGY misc 3; stock Vigor is +10, this is +20"),

    # -- 2/1 -- Fel Lethality ............................. donor 14128 Lethality (family 8)
    #
    # The arrow is talents.md's and it is DIAGONAL -- (0,2) to (2,1) -- which is legal and rare
    # (12 of the 892 stock rows, e.g. Subtlety's 681 depending on 1123). PrereqRank 4 is the
    # 0-based floor, i.e. all five points in Malice.
    Talent("havoc", 2, 1, 5, "Fel Lethality", 14128, prereq=(0, 2, 4),
           rank_cell="EffectBasePoints_1",
           rank_values=(5, 11, 17, 23, 29),     # DieSides 1 -> lands 6/12/18/24/30 %
           overrides={
               "EffectSpellClassMaskA_1": (BIT["demons_bite"] | BIT["chaos_strike"]
                                           | BIT["blade_dance"]),
               "EffectSpellClassMaskA_2": 0,    # the donor's second word, 262
               "Description_Lang_enUS":
                   "Increases the critical strike damage bonus of your Demon's Bite, Chaos "
                   "Strike and Blade Dance by $s1%.",
           },
           note="14128 -- aura 108 SPELLMOD_CRIT_DAMAGE_BONUS(15)"),

    # -- 2/2 -- Blade Rhythm .............................. donor 49223 Dirge (family 15)
    #
    # THE RANK TRICK, talents.md 2.B: aura 231 SPELL_AURA_PROC_TRIGGER_SPELL_WITH_VALUE passes
    # its OWN amount into the triggered spell as basepoints0 (SpellAuraEffects.cpp:6922-6936),
    # so three ranks need one trigger row rather than three.
    # NO `spell_proc` ROW, also talents.md 2.B: SpellMgr::LoadSpellProcs generates one for any
    # spell with a trigger aura and proc flags (SpellMgr.cpp:2159-2232), taking the family and
    # mask off the effect -- and SpellMgr.cpp:2089 rejects family 16 in that table by name, so
    # an explicit row would print an error at every boot.
    # ProcTypeMask 0x15410 is the donor's and is kept: 0x10 DONE_SPELL_MELEE_DMG_CLASS is the
    # bit Demon's Bite raises (DefenseType 2), and the other four bits cannot fire because the
    # generated proc entry's family mask restricts it to Demon's Bite anyway.
    Talent("havoc", 2, 2, 3, "Blade Rhythm", 49223,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 5, 8),               # DieSides 1 -> the aura's amount is 3/6/9, and
                                                # that amount IS the Fury restored (the trigger
                                                # row's own die is zeroed, see TRIGGERS)
           overrides={
               "EffectSpellClassMaskA_1": BIT["demons_bite"],
               "EffectSpellClassMaskA_2": 0,    # the donor's 128
               "Description_Lang_enUS": "Your Demon's Bite restores an additional $s1 Fury.",
           },
           note="49223 -- aura 231; the trigger row is TRIGGERS['blade_rhythm_energize'] and "
                "the generator writes EffectTriggerSpell_1"),

    # -- 3/1 -- Furious Throws ............................ donor 18427 Aggression (family 8)
    #
    # talents.md gives this two scaling numbers (+10%/rank damage AND -0.5 s/rank cooldown) off
    # 35446 Improved Mortal Strike, whose two effects are exactly that pair. The generator writes
    # ONE per-rank cell, so the cooldown half is dropped and the donor moves to the single-effect
    # 18427 rather than carrying a zeroed Effect_2 around. See DEGRADED.
    Talent("havoc", 3, 1, 3, "Furious Throws", 18427,
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 %
           overrides={
               "EffectSpellClassMaskA_1": BIT["throw_glaive"],
               "Description_Lang_enUS": "Increases the damage of your Throw Glaive by $s1%.",
           },
           note="18427 again -- one effect, so nothing has to be zeroed; 35446's cooldown half "
                "could not be ranked (DEGRADED)"),

    # -- 3/2 -- Chaos Bloom ............................... donor 47236 Demonic Pact (family 5)
    #
    # Only `Effect_3` is wanted: aura 79 SPELL_AURA_MOD_DAMAGE_PERCENT_DONE with
    # EffectMiscValue_3 = 36 = SPELL_SCHOOL_MASK_FIRE(4) | SPELL_SCHOOL_MASK_SHADOW(32), which is
    # already the pair of schools this talent wants. The other two effects are a warlock DUMMY
    # and a masked spell-power modifier and both go, with their masks.
    Talent("havoc", 3, 2, 5, "Chaos Bloom", 47236,
           rank_cell="EffectBasePoints_3",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Effect_1": 0,                   # aura 4 DUMMY misc 12 -- warlock pet plumbing
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "Effect_2": 0,                   # aura 107 misc 18, +100% of something warlock
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS": "Increases your Fire and Shadow damage done by $s3%.",
           },
           note="47236 Effect_3 -- aura 79 misc 36 (Fire|Shadow), the two schools the DH kit "
                "actually deals"),

    # -- 4/0 -- Improved Blade Dance ...................... donor 16966 Shredding Attacks
    #
    # Blade Dance costs 35 Fury (dh_spec), so -21 at three ranks leaves 14. The donor's second
    # effect is the same aura pointed at Lacerate through the SECOND mask word and goes with it.
    Talent("havoc", 4, 0, 3, "Improved Blade Dance", 16966,
           rank_cell="EffectBasePoints_1",
           rank_values=(-8, -15, -22),          # DieSides 1 -> lands -7/-14/-21 Fury
           overrides={
               "EffectSpellClassMaskA_1": BIT["blade_dance"],
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "Description_Lang_enUS":
                   "Reduces the Fury cost of your Blade Dance by $s1.",
           },
           note="16966 -- aura 107 SPELLMOD_COST(14), flat"),

    # -- 4/1 -- Momentum .................................. donor 12319 Flurry (family 0)
    #
    # Aura 42 SPELL_AURA_PROC_TRIGGER_SPELL, one rank, so the buff's size lives in the trigger
    # row and not here.
    # THE MASK IS NOT OPTIONAL. 12319's effect mask is ZERO, and `SpellMgr::LoadSpellProcs`
    # (:2200-2210) only sets `procEntry.SpellFamilyName` when the mask is non-zero -- a cloned
    # Flurry with an empty mask would generate a proc entry with family 0 and no mask, i.e. one
    # that fires off EVERYTHING matching ProcFlags.
    # ProcTypeMask is REPLACED, not kept: the donor's 0x14 is melee auto-attack plus
    # DONE_SPELL_MELEE_DMG_CLASS, and Fel Rush is `DefenseType 1` (magic) whose damage arrives on
    # the fel_rush_impact record. 0x10000 DONE_SPELL_MAGIC_DMG_CLASS_NEG is the bit that record
    # raises; 0x1000 DONE_SPELL_NONE_DMG_CLASS_NEG is belt and braces for the dash itself.
    # UNVERIFIED -- see FLAGGED; this is read off SpellMgr.h:113-134, not observed.
    Talent("havoc", 4, 1, 1, "Momentum", 12319,
           overrides={
               "EffectSpellClassMaskA_1": BIT["fel_rush"],
               "ProcTypeMask": 0x00011000,
               "Description_Lang_enUS":
                   "After using Fel Rush, your damage done is increased by 15% for 6 sec.",
           },
           note="12319 -- aura 42; the trigger row is TRIGGERS['momentum_buff']"),

    # -- 4/3 -- Reckless Abandon .......................... donor 14165 Improved Slice and Dice
    #
    # AURA 108 IS A PERCENTAGE. talents.md asks for "+4 s per rank" but SPELLMOD_DURATION through
    # an ADD_PCT_MODIFIER is a percentage of the spell's own duration, and there is no flat
    # duration donor in the survey. Metamorphosis is 30 s (DurationIndex 9), so 10%/rank is
    # +3 s/rank -- the same shape as the design, one second smaller. See DEGRADED.
    Talent("havoc", 4, 3, 3, "Reckless Abandon", 14165,
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 % of 30 s
           overrides={
               "EffectSpellClassMaskA_1": BIT["metamorphosis"],
               "Description_Lang_enUS":
                   "Increases the duration of your Metamorphosis by $s1%.",
           },
           note="14165 -- aura 108 SPELLMOD_DURATION(1), percentage"),

    # -- 5/1 -- Demonic Appetite .......................... donor 47236 Demonic Pact (family 5)
    #
    # TIER C, talents.md 2.C: PASSIVE|DO_NOT_DISPLAY plus a `ShapeshiftMask` naming form 23 is
    # applied on entering the form and removed on leaving it, by
    # `AuraEffect::HandleShapeshiftBoosts` walking the talent map -- no id switch, no script.
    # The donor is 47236 and NOT talents.md's 15473 Shadowform, which would have been the one
    # genuinely dangerous clone in the tree: Shadowform's `Effect_1` is aura 36 MOD_SHAPESHIFT
    # with `EffectMiscValue_1 = 28`, so a Demon Hunter entering Metamorphosis would have been
    # put into the PRIEST's Shadowform as well. 47236 is already Attributes 464 and its Effect_3
    # is the same aura 79 with a school mask that only has to widen from 36 to 127.
    Talent("havoc", 5, 1, 3, "Demonic Appetite", 47236,
           rank_cell="EffectBasePoints_3",
           rank_values=(2, 5, 8),               # DieSides 1 -> lands 3/6/9 %
           overrides={
               "ShapeshiftMask": METAMORPHOSIS_STANCE,   # form 23, against ALWAYS
               "EffectMiscValue_3": 127,        # all seven schools, from 36 (Fire|Shadow)
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS":
                   "While in Metamorphosis, your damage done is increased by $s3%.",
           },
           note="47236 Effect_3 + ShapeshiftMask 0x400000; 15473 Shadowform was rejected because "
                "its Effect_1 shapeshifts the caster into form 28"),

    # -- 5/2 -- Blind Fury ................................ donor 14076 Dirty Tricks (family 8)
    #
    # THE EMPTY MASK IS THE TALENT. `SpellInfo::IsAffected` (SpellInfo.cpp:1325-1337) returns
    # true when the MODIFIER's familyFlags are empty and the families match, so family 16 with a
    # zero mask is "every Demon Hunter spell" and nothing else. The donor's Effect_2 already has
    # no mask, so the cell that makes this work is the ABSENCE of one -- and the donor's Effect_1
    # (a masked range modifier) has to go or it drags Blind and Sap's bits in.
    Talent("havoc", 5, 2, 3, "Blind Fury", 14076,
           rank_cell="EffectBasePoints_2",
           rank_values=(-6, -11, -16),          # DieSides 1 -> lands -5/-10/-15 %
           overrides={
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Description_Lang_enUS":
                   "Reduces the Fury cost of all your abilities by $s2%.",
           },
           note="14076 Effect_2 -- aura 108 SPELLMOD_COST(14) with no mask at all"),

    # -- 6/1 -- Glaive Tempest ............................ donor 26573 Consecration (family 10)
    #
    # REPLACES talents.md's Eye Beam, which is a BASELINE ability at level 56 (dh_spec.ABILITIES)
    # and cannot also be a talent -- the talent would grant a second, unrelated spell with the
    # same name. Glaive Tempest is the retail Havoc talent that fills the same slot: a spinning
    # AoE at the caster's feet, and 26573 is already exactly that shape --
    # `Effect_1 = 27 PERSISTENT_AREA_AURA` with `EffectAura_1 = 3 PERIODIC_DAMAGE` directly on it
    # and `EffectAuraPeriod_1 = 1000`, dropped at `ImplicitTargetA_1 = 18 TARGET_DEST_CASTER`,
    # radius index 14 (8.0 yd), DurationIndex 31 (8000 ms). All kept.
    # 43265 Death and Decay is the same shape with a reticle, and is NOT used: its aura is 226
    # PERIODIC_DUMMY, which does nothing without `spell_dk_death_and_decay`.
    Talent("havoc", 6, 1, 1, "Glaive Tempest", 26573, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["glaive_tempest"],
               "Attributes": 0x10,              # IS_ABILITY only. The donor's 0x10000 is
                                                # NOT_SHAPESHIFTED, which would grey this button
                                                # out in Metamorphosis (see NOT_SHAPESHIFTED).
               "SchoolMask": 4,                 # Fire, from 2 (Holy)
               "RecoveryTime": 30000,
               "ManaCost": 30,                  # Fury; ALWAYS zeroed the donor's ManaCostPct 22,
                                                # which would have been 22% of MAX Fury
               "StartRecoveryCategory": 133,    # the house GCD, from the donor's 133/1500
               "StartRecoveryTime": 1000,
               "EffectBasePoints_1": 24,        # UNTUNED -- 25 damage a second at every level.
                                                # See UNTUNED; this is the one number in the tree
                                                # that is an absolute magnitude.
               "Description_Lang_enUS":
                   "Glaives whirl around you, dealing $s1 Fire damage every 1 sec to nearby "
                   "enemies for $d.",
           },
           note="26573 -- persistent area aura with the periodic ON the effect, so no trigger "
                "row and no script"),

    # -- 6/2 -- Unleashed Power ........................... donor 13742 Endurance (family 8)
    #
    # The prerequisite moved. talents.md hangs this off Eye Beam at (6,1), which is (a) the same
    # tier -- and `dhspells.build_talents` check #45 requires the tail to be in an EARLIER tier
    # -- and (b) a talent that no longer exists. It now hangs off Blind Fury at (5,2), which is
    # the vertical arrow directly above it and the shape talents.md 1.4 says these trees use.
    Talent("havoc", 6, 2, 3, "Unleashed Power", 13742, prereq=(5, 2, 0),
           rank_cell="EffectBasePoints_1",
           rank_values=(-2001, -4001, -6001),   # DieSides 1 -> lands -2000/-4000/-6000 ms
           overrides={
               "EffectSpellClassMaskA_1": BIT["blade_dance"] | BIT["eye_beam"],
               "EffectSpellClassMaskB_1": 0,    # the donor's Evasion bit, second word
               "Effect_2": 0,                   # aura 137 +Stamina, Endurance's other half
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Blade Dance and Eye Beam by $/1000;s1 sec.",
           },
           note="13742 -- aura 107 SPELLMOD_COOLDOWN(11); the units are milliseconds"),

    # -- 7/0 -- Cycle of Hatred ........................... donor 13712 Lightning Reflexes
    #
    # Effect_2 is aura 138 SPELL_AURA_MOD_MELEE_HASTE, which is not a spellmod and needs no mask.
    # Effect_1 is +dodge and belongs to the tank tree, so it goes.
    Talent("havoc", 7, 0, 5, "Cycle of Hatred", 13712,
           rank_cell="EffectBasePoints_2",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "Description_Lang_enUS": "Increases your melee attack speed by $s2%.",
           },
           note="13712 Effect_2 -- aura 138, family-free"),

    # -- 7/2 -- Serrated Glaives .......................... donor 31234 Find Weakness (family 8)
    #
    # "Every Fury-costing ability" is FURY_SPENDERS, which is dh_spec's own cost table minus
    # Imprison (25 Fury, no damage). The donor's Effect_2 is the same aura at SPELLMOD_DOT and
    # goes, along with all three of its mask words.
    Talent("havoc", 7, 2, 3, "Serrated Glaives", 31234,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 5, 8),               # DieSides 1 -> lands 3/6/9 %
           overrides={
               "EffectSpellClassMaskA_1": FURY_SPENDERS,
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Increases the damage of your Fury-costing abilities by $s1%.",
           },
           note="31234 -- aura 108 SPELLMOD_DAMAGE(0)"),

    # -- 8/1 -- Deathblow ................................. donor 14177 Cold Blood (family 8)
    #
    # THE ONE ACCEPTED DEGRADATION IN ALL THREE TREES, carried through from talents.md 5 exactly
    # as written there. Cold Blood's spellmod is generic and clones perfectly, but
    # `Spell.cpp:2702` calls `RestoreSpellMods(this, 14177)` on a HARDCODED ID to give the charge
    # back when the empowered cast fails. That refund does not follow a clone: a fizzled cast
    # eats the charge. It degrades toward LESS power, fixing it is a core edit, and it is
    # accepted. (If it becomes annoying the cheap fix is a short buff duration so a failed cast
    # is retryable -- still not a C++ change.)
    # ProcCharges 1, ProcTypeMask 0x15550 and DurationIndex 21 (infinite) are the donor's and are
    # what make it "your NEXT ability": the aura is consumed by the proc machinery, not by time.
    Talent("havoc", 8, 1, 1, "Deathblow", 14177, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["deathblow"],
               "Attributes": 33882128 & ~NOT_SHAPESHIFTED,      # 0x2050010 -> 0x2040010
               "EffectSpellClassMaskA_1": OFFENSIVE,
               "EffectSpellClassMaskA_2": 0,    # the donor's second word, 262415
               "RecoveryTime": 120000,          # 2 min, from the donor's 180000
               "Description_Lang_enUS":
                   "When activated, your next offensive ability is a critical strike.",
           },
           note="14177 -- aura 107 SPELLMOD_CRITICAL_CHANCE(7) at +100% with one charge; the "
                "lost refund is Spell.cpp:2702 and is accepted, not fixed"),

    # -- 9/1 -- Demonic Origins ........................... donor 30902 Deadliness (family 0)
    Talent("havoc", 9, 1, 5, "Demonic Origins", 30902,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Description_Lang_enUS": "Increases your attack power by $s1%.",
           },
           note="30902 -- aura 166 MOD_ATTACK_POWER_PCT, one effect, family 0"),

    # -- 10/1 -- Chaos Blades ............................. donor 12292 Death Wish (family 4)
    #
    # Zero core references, which is why talents.md chose it over 13877 Blade Flurry (whose
    # extra-target half is `spell_rogue.cpp:110` and would not survive a clone).
    # `Mechanic = 31 MECHANIC_ENRAGE` is dropped: it is what makes Death Wish removable by
    # Tranquilizing Shot and Soothe Animal, and a Demon Hunter's signature cooldown being
    # dispellable by a hunter is a mechanic nobody chose.
    Talent("havoc", 10, 1, 1, "Chaos Blades", 12292, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["chaos_blades"],
               "Mechanic": 0,                   # from 31 MECHANIC_ENRAGE
               "DurationIndex": 18,             # 20000 ms (SpellDuration.dbc row 18, read from
                                                # the file); the donor's row 9 is 30000
               "StartRecoveryTime": 1000,       # the house GCD, from 1500
               "Description_Lang_enUS":
                   "Your blades burn with chaos, increasing your Physical damage done by $s1% "
                   "but increasing all damage taken by $s3%. Lasts $d.",
           },
           note="12292 -- Effect_1 aura 79 misc 1 (+20% physical), Effect_3 aura 87 misc 127 "
                "(+5% taken); RecoveryTime 180000 is already the donor's"),
)


# =============================================================================================
# TREE 1 -- VENGEANCE (413, OrderIndex 1) -- 22 talents, 69 points
# =============================================================================================
#
# tier | col 0                | col 1                | col 2                | col 3
# -----+----------------------+----------------------+----------------------+------------------
#   0  | Fel Hardiness      5 | Improved Soul Clea 2 | Thick Hide         5 |
#   1  | Deflection         5 | Charred Flesh      3 |                      |
#   2  |                      | Vengeful Wards     5 | Burning Alive      3 |
#   3  |                      | Demon Spikes       1 | Fiery Demise       5 |
#   4  | Blood Rite         3 | Feed the Demon     3 |                      | Demonic Wards    3
#   5  |                      | Soul Rending       3 | Painbringer        3 |
#   6  |                      | Void Reaver        1 | Roaring Fire       3 |
#   7  | Bladed Armor       5 |                      | Spell Deflection   3 |
#   8  |                      | Demonic Fortitude  1 | Illidari Durabilit 3 |
#   9  |                      | Malevolence        3 |                      |
#  10  |                      | Nether Bulwark     1 |                      |
#
# cumulative points by the end of each tier:
#  T0 12 | T1 20 | T2 28 | T3 34 | T4 43 | T5 49 | T6 53 | T7 61 | T8 65 | T9 68 | T10 69
#  gate     5  |   10  |   15  |   20  |   25  |   30  |   35  |   40  |   45  |    50
#
# T3 is 34 where talents.md 6 prints 36, and that is the one number in this file that disagrees
# with the document: Demon Spikes (1 point) and Feed the Demon (3 points) swapped tiers so that
# the talent which reduces a cooldown sits BELOW the talent that grants the ability, with a real
# arrow between them. Six points in tier 3 instead of eight, nine in tier 4 instead of seven, and
# the tree still totals 69 with every gate satisfied by a wide margin.

_VENGEANCE = (

    # -- 0/0 -- Fel Hardiness ............................. donor 16252 Toughness (family 0)
    #
    # Effect_1 is aura 137 MOD_TOTAL_STAT_PERCENTAGE with EffectMiscValue_1 = 2 STAT_STAMINA.
    # Effect_2 (-7% snare duration) is the second scaling number this record cannot carry and
    # goes; Illidari's Fleet of Foot owns that job for the class. See DEGRADED.
    Talent("vengeance", 0, 0, 5, "Fel Hardiness", 16252,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS": "Increases your total Stamina by $s1%.",
           },
           note="16252 Effect_1 -- aura 137 misc 2 (STAT_STAMINA)"),

    # -- 0/1 -- Improved Soul Cleave ...................... donor 13732 Improved Sinister Strike
    #
    # WAS "Improved Shear". There is no Shear: `dh_spec.ABILITIES` has no such ability and the
    # Vengeance filler is Demon's Bite, which costs nothing to begin with. Soul Cleave is the
    # tank's spender (35 Fury, dh_spec) and is the only Vengeance-shaped ability a cost reduction
    # can bite on. Donor, aura and op are talents.md's, unchanged; only the mask moved.
    Talent("vengeance", 0, 1, 2, "Improved Soul Cleave", 13732,
           rank_cell="EffectBasePoints_1",
           rank_values=(-6, -11),               # DieSides 1 -> lands -5/-10 Fury of 35
           overrides={
               "EffectSpellClassMaskA_1": BIT["soul_cleave"],
               "Description_Lang_enUS": "Reduces the Fury cost of your Soul Cleave by $s1.",
           },
           note="13732 -- aura 107 SPELLMOD_COST(14), flat"),

    # -- 0/2 -- Thick Hide ................................ donor 12299 Toughness (family 0)
    #
    # Effect_1 is aura 142 MOD_BASE_RESISTANCE_PCT with EffectMiscValue_1 = 1 -- armour from
    # ITEMS, which is the number a tank stacks. Effect_2 is the same -7% snare duration as 16252
    # and goes for the same reason (DEGRADED).
    Talent("vengeance", 0, 2, 5, "Thick Hide", 12299,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS": "Increases your armor value from items by $s1%.",
           },
           note="12299 Effect_1 -- aura 142 misc 1; NOT 16252, whose Effect_1 is Stamina"),

    # -- 1/0 -- Deflection ................................ donor 16462 Deflection (family 0)
    #
    # Five ranks in stock, aura 47 MOD_PARRY_PERCENT, one effect, family 0. Nothing to strip.
    # The float tables in `0001-demon-hunter-class-10.patch` are what make this do anything at
    # all: with `parry_cap` left at 0.0f the class's avoidance is NaN and it never parries
    # (build/patches/README.md), which would make this talent look broken rather than absent.
    Talent("vengeance", 1, 0, 5, "Deflection", 16462,
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 1, 2, 3, 4),         # DieSides 1 -> lands 1/2/3/4/5 %
           overrides={
               "Description_Lang_enUS": "Increases your Parry chance by $s1%.",
           },
           note="16462 -- aura 47, family 0, already a 5-rank talent"),

    # -- 1/1 -- Charred Flesh ............................. donor 18427 Aggression (family 8)
    #
    # NOT talents.md's 16513 Vile Poisons / SPELLMOD_DOT(22), and the reason is a fact about the
    # kit: Immolation Aura's damage is not a DoT. `dh_donors` builds it as a
    # PERIODIC_TRIGGER_SPELL that casts the `immolation_tick` record once a second, and that
    # record's damage is a plain SCHOOL_DAMAGE effect -- SPELLMOD_DOT would miss it entirely.
    # SPELLMOD_DAMAGE(0) reaches both that and Sigil of Flame's genuine periodic, and the tick
    # record carries its parent's mask bit (dh_donors.SECOND_RECORDS), so one literal covers it.
    Talent("vengeance", 1, 1, 3, "Charred Flesh", 18427,
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 %
           overrides={
               "EffectSpellClassMaskA_1": FIRE_AOE,
               "Description_Lang_enUS":
                   "Increases the damage of your Immolation Aura and Sigil of Flame by $s1%.",
           },
           note="18427 -- aura 108 SPELLMOD_DAMAGE(0); 16513's SPELLMOD_DOT would not see the "
                "Immolation Aura tick record"),

    # -- 2/1 -- Vengeful Wards ............................ donor 27900 Spell Warding (family 6)
    #
    # Aura 87 MOD_DAMAGE_PERCENT_TAKEN with EffectMiscValue_1 = 126, i.e. every school EXCEPT
    # physical (127 & ~1). One effect, nothing else on the record.
    Talent("vengeance", 2, 1, 5, "Vengeful Wards", 27900,
           rank_cell="EffectBasePoints_1",
           rank_values=(-3, -5, -7, -9, -11),   # DieSides 1 -> lands -2/-4/-6/-8/-10 %
           overrides={
               "Description_Lang_enUS": "Reduces all spell damage taken by $s1%.",
           },
           note="27900 -- aura 87 misc 126 (all magic schools)"),

    # -- 2/2 -- Burning Alive ............................. donor 12295 Tactical Mastery (fam 4)
    #
    # SHEAR BECAME DEMON'S BITE. The threat trio is the filler, the spender and the aura, which
    # for this kit is Demon's Bite, Soul Cleave and Immolation Aura.
    # `ShapeshiftMask = 0x20000` (Defensive Stance) is on this record and is closed by ALWAYS --
    # left alone it would not fail a cast, it would stop the passive from ever being applied
    # (Player.cpp:3401-3408), i.e. a talent that silently does nothing.
    Talent("vengeance", 2, 2, 3, "Burning Alive", 12295,
           rank_cell="EffectBasePoints_2",
           rank_values=(14, 29, 44),            # DieSides 1 -> lands 15/30/45 %
           overrides={
               "EffectSpellClassMaskA_2": (BIT["demons_bite"] | BIT["soul_cleave"]
                                           | BIT["immolation_aura"]),
               "Effect_1": 0,                   # aura 4 DUMMY -- the rage-retention half
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Effect_3": 0,                   # the second threat mod, Mortal Strike's
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectMiscValue_3": 0,
               "ImplicitTargetA_3": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS":
                   "Increases the threat generated by your Demon's Bite, Soul Cleave and "
                   "Immolation Aura by $s2%.",
           },
           note="12295 Effect_2 -- aura 108 SPELLMOD_THREAT(2)"),

    # -- 3/1 -- Demon Spikes .............................. donor 51271 Unbreakable Armor (fam 15)
    #
    # REPLACES talents.md's Fiery Brand, which is a BASELINE ability at level 36 and cannot also
    # be a talent. Demon Spikes is the ability talents.md's own Feed the Demon was written
    # against, so putting it back here is what lets that talent keep its text -- and it moves up
    # one tier so the arrow points the right way (see the tier note above).
    # The donor is the only stock short-cooldown armour buff with no SpellScript: 12975 Last
    # Stand is `spell_warrior.cpp:231`, 48792 Icebound Fortitude and 31850 Ardent Defender are
    # both scripted, and 51271 has zero references in `src/server` (grepped).
    # Effect_1 (aura 101 MOD_RESISTANCE_PCT misc 1, +25% armour) is kept as-is. Effect_2 is
    # aura 137 +20% Strength in stock and becomes the parry half -- the effect is already
    # APPLY_AURA on the caster with DieSides 1, so only the aura id and the value change.
    Talent("vengeance", 3, 1, 1, "Demon Spikes", 51271, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["demon_spikes"],
               "EffectAura_2": 47,              # MOD_PARRY_PERCENT, from 137
               "EffectBasePoints_2": 14,        # DieSides 1 -> +15% parry
               "DurationIndex": 32,             # 6000 ms (SpellDuration.dbc row 32, read from
                                                # the file); the donor's row 18 is 20000
               "RecoveryTime": 20000,           # from 60000
               "Description_Lang_enUS":
                   "Demonic spikes erupt from your skin, increasing your armor by $s1% and your "
                   "Parry chance by $s2% for $d.",
           },
           note="51271 -- Effect_1 aura 101 misc 1 kept; RuneCostID 1202 and PowerType 5 are "
                "closed by ALWAYS"),

    # -- 3/2 -- Fiery Demise .............................. donor 47236 Demonic Pact (family 5)
    #
    # The same Effect_3 Chaos Bloom uses, narrowed from 36 (Fire|Shadow) to 4 (Fire).
    Talent("vengeance", 3, 2, 5, "Fiery Demise", 47236,
           rank_cell="EffectBasePoints_3",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "EffectMiscValue_3": 4,          # SPELL_SCHOOL_MASK_FIRE, from 36
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS": "Increases your Fire damage done by $s3%.",
           },
           note="47236 Effect_3 -- aura 79 MOD_DAMAGE_PERCENT_DONE"),

    # -- 4/0 -- Blood Rite ................................ donor 29593 Improved Defensive Stance
    #
    # Two traps on one record, both closed here: `ShapeshiftMask = 0x20000` (ALWAYS, or the
    # passive never applies) and `Effect_2`, an aura 42 PROC_TRIGGER_SPELL pointing at 57514, a
    # warrior Enrage. A clone that kept it would give a Demon Hunter a warrior buff on every
    # block/parry/dodge -- and would ALSO generate a proc entry for this talent
    # (SpellMgr.cpp:2159-2232 keys on the presence of a trigger aura), which is the opposite of
    # what a flat damage-reduction passive wants.
    Talent("vengeance", 4, 0, 3, "Blood Rite", 29593,
           rank_cell="EffectBasePoints_1",
           rank_values=(-3, -5, -7),            # DieSides 1 -> lands -2/-4/-6 %
           overrides={
               "EffectMiscValue_1": 1,          # SPELL_SCHOOL_MASK_NORMAL (physical), from 126
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectTriggerSpell_2": 0,       # 57514, a warrior Enrage
               "ProcTypeMask": 0,               # 174760, now that nothing procs
               "ProcChance": 0,
               "Attributes": PASSIVE_ATTRS,     # the donor is 448 (no IS_ABILITY); 464 is the
                                                # canonical passive set and costs nothing
               "Description_Lang_enUS": "Reduces all Physical damage taken by $s1%.",
           },
           note="29593 Effect_1 -- aura 87 MOD_DAMAGE_PERCENT_TAKEN, misc narrowed to physical"),

    # -- 4/1 -- Feed the Demon ............................ donor 13742 Endurance (family 8)
    #
    # THE ONLY TALENT THAT MODIFIES A TALENT-GRANTED SPELL, and therefore the only one that
    # writes the THIRD mask word: Demon Spikes' own bit lives in `SpellClassMask_3`
    # (TALENT_BIT), so the modifier names it through `EffectSpellClassMaskC_1`.
    # `SpellInfo::IsAffected` ANDs the whole 96-bit flag96, so word 3 against word 3 is the same
    # test as word 1 against word 1.
    Talent("vengeance", 4, 1, 3, "Feed the Demon", 13742, prereq=(3, 1, 0),
           rank_cell="EffectBasePoints_1",
           rank_values=(-2001, -4001, -6001),   # DieSides 1 -> lands -2000/-4000/-6000 ms
           overrides={
               "EffectSpellClassMaskA_1": 0,    # the donor's Sprint/Evasion bits
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": TALENT_BIT["demon_spikes"],
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Demon Spikes by $/1000;s1 sec.",
           },
           note="13742 -- aura 107 SPELLMOD_COOLDOWN(11), milliseconds, third mask word"),

    # -- 4/3 -- Demonic Wards ............................. donor 31380 Deadened Nerves (family 8)
    #
    # TIER C, form-gated (talents.md 2.C). The donor is already one effect, Attributes 464 and
    # aura 87 with misc 127; the whole talent is that record plus a stance mask.
    Talent("vengeance", 4, 3, 3, "Demonic Wards", 31380,
           rank_cell="EffectBasePoints_1",
           rank_values=(-4, -7, -10),           # DieSides 1 -> lands -3/-6/-9 %
           overrides={
               "ShapeshiftMask": METAMORPHOSIS_STANCE,
               "Description_Lang_enUS":
                   "While in Metamorphosis, all damage taken is reduced by $s1%.",
           },
           note="31380 + ShapeshiftMask 0x400000 -- the cheapest possible form-gated passive"),

    # -- 5/1 -- Soul Rending .............................. donor 16998 Savage Fury (family 7)
    #
    # talents.md 9.2 SAID THIS WOULD HAPPEN: "If Soul Cleave's heal turns out to be Effect_2
    # rather than Effect_3, Vengeance 5/1's SpellModOp changes from 23 to 12". It is Effect_2
    # (`dh_donors.OVERRIDES["soul_cleave"]` puts `Effect_2 = 10 SPELL_EFFECT_HEAL` on the
    # record), so the op is 12 SPELLMOD_EFFECT2 and the donor's Effect_3 -- which is the same
    # aura 108 at op 23 -- needs exactly one cell changed.
    Talent("vengeance", 5, 1, 3, "Soul Rending", 16998,
           rank_cell="EffectBasePoints_3",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 %
           overrides={
               "EffectMiscValue_3": 12,         # SPELLMOD_EFFECT2, from 23 SPELLMOD_EFFECT3
               "EffectSpellClassMaskA_3": BIT["soul_cleave"],
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS":
                   "Increases the healing done by your Soul Cleave by $s3%.",
           },
           note="16998 Effect_3 -- aura 108 with the op moved to 12 because the heal is Effect_2"),

    # -- 5/2 -- Painbringer ............................... donor 55129 Anticipation (family 0)
    #
    # Aura 49 MOD_DODGE_PERCENT. EffectMiscValue_1 = 95 is on the stock record and is not read by
    # `HandleAuraModDodgePercent`; it is left alone rather than tidied, because a cell nobody
    # reads is not worth a line of divergence from the file.
    Talent("vengeance", 5, 2, 3, "Painbringer", 55129,
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 1, 2),               # DieSides 1 -> lands 1/2/3 %
           overrides={
               "Description_Lang_enUS": "Increases your Dodge chance by $s1%.",
           },
           note="55129 -- aura 49, one effect, family 0"),

    # -- 6/1 -- Void Reaver ............................... donor 1161 Challenging Shout (fam 4)
    #
    # `ImplicitTargetA_1 = 22 TARGET_SRC_CASTER` + `ImplicitTargetB_1 = 15 TARGET_UNIT_SRC_AREA_
    # ENEMY` at radius index 13 (10.0 yd) is already "everything within 10 yards", and aura 11
    # MOD_TAUNT is already the taunt. Taunt diminishing returns come free and family-proof:
    # `SpellMgr.cpp:112-115` returns DIMINISHING_TAUNT for any spell with that aura, BEFORE the
    # family switch that family 16 would fall out of.
    # OFF-GCD, which is `dh_donors`' own decided rule for this class: "Every stock taunt is 0/0
    # -- 355 Taunt, 56222 Dark Command, 62124 Hand of Reckoning. A taunt on the GCD is a tank
    # losing threat." The donor is 133/1500, so both cells are written.
    # The `case 1161:` in `SpellEffects.cpp:2393` is a SummonProperties id in EffectSummonType,
    # not a spell id -- checked, because a hardcoded donor id is exactly what §2.E rules out.
    Talent("vengeance", 6, 1, 1, "Void Reaver", 1161, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["void_reaver"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,        # 0x50010 -> 0x40010
               "RecoveryTime": 60000,           # from 180000
               "StartRecoveryCategory": 0,      # off-GCD, against the donor's 133/1500
               "StartRecoveryTime": 0,
               "Description_Lang_enUS":
                   "Forces all enemies within $a1 yards to attack you for $d.",
           },
           note="1161 -- aura 11 MOD_TAUNT, source-area targeting already correct"),

    # -- 6/2 -- Roaring Fire .............................. donor 16757 Arctic Reach (family 3)
    #
    # Effect_2 is aura 108 at op 6 SPELLMOD_RADIUS, which is the rarest useful spellmod in the
    # file. Effect_1 is the same aura at op 5 (range) and goes with both its mask words.
    Talent("vengeance", 6, 2, 3, "Roaring Fire", 16757,
           rank_cell="EffectBasePoints_2",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 %
           overrides={
               "EffectSpellClassMaskA_2": FIRE_AOE,
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Description_Lang_enUS":
                   "Increases the radius of your Immolation Aura and Sigil of Flame by $s2%.",
           },
           note="16757 Effect_2 -- aura 108 SPELLMOD_RADIUS(6)"),

    # -- 7/0 -- Bladed Armor .............................. donor 48978 Bladed Armor (family 15)
    #
    # Aura 285 MOD_ATTACK_POWER_OF_ARMOR, and the amount is a DIVISOR:
    # `StatSystem.cpp:511-514` is `attPowerMod += int32(GetArmor() / (*iter)->GetAmount())`.
    # So a SMALLER number is a bigger bonus, and a value of ZERO would divide by zero -- which is
    # why the assertion block below refuses a non-positive rank value on this aura.
    # The rank values are Blizzard's own for this exact spell, read from ranks 1-5 (48978, 49390,
    # 49391, 49392, 49393): 179/89/59/44/35, i.e. 1 AP per 180/90/60/45/36 armour.
    # Effect_2 is a SPELL_EFFECT_DUMMY carrying the rank number for the tooltip's `$m2`; the
    # description below does not use it, so it goes.
    Talent("vengeance", 7, 0, 5, "Bladed Armor", 48978,
           rank_cell="EffectBasePoints_1",
           rank_values=(179, 89, 59, 44, 35),   # DieSides 1 -> divisors 180/90/60/45/36
           overrides={
               "Effect_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Increases your attack power by 1 for every $s1 armor value you have.",
           },
           note="48978 -- aura 285; the amount is a divisor, so the ranks descend"),

    # -- 7/2 -- Spell Deflection .......................... donor 49145 Spell Deflection (fam 0)
    #
    # THE ONE TIER-D TALENT: one `spell_script_names` row, no C++ (talents.md 2.D). See
    # SCRIPT_NAMES at the bottom of this file for why reusing a Death Knight script is safe.
    # Aura 69 SCHOOL_ABSORB with misc 126 and ProcTypeMask 0x20000 are the donor's and are what
    # the script hangs off; the values are stock Spell Deflection's own (15/30/45%).
    Talent("vengeance", 7, 2, 3, "Spell Deflection", 49145,
           rank_cell="EffectBasePoints_1",
           rank_values=(14, 29, 44),            # DieSides 1 -> lands 15/30/45 %
           overrides={
               "Description_Lang_enUS":
                   "You have a chance equal to your Parry chance of taking $s1% less damage "
                   "from a direct damage spell.",
           },
           note="49145 -- aura 69; the absorb percentage is read by the script off its OWN "
                "EFFECT_0, which is why the clone needs no other cell"),

    # -- 8/1 -- Demonic Fortitude ......................... donor 51271 Unbreakable Armor
    #
    # The same donor as Demon Spikes, used the other way round: Effect_1 (armour) goes and
    # Effect_2 becomes Stamina. Chosen over 12975 Last Stand precisely because Last Stand's
    # health grant is a SpellScript (`spell_warrior.cpp:231`) that a clone does not get, whereas
    # aura 137 with `EffectMiscValue = 2` is dispatched on aura type alone.
    # Off-GCD: the donor is 0/0 and a defensive cooldown that costs a global is one you press too
    # late (`dh_donors`' decided rule for Blur).
    Talent("vengeance", 8, 1, 1, "Demonic Fortitude", 51271, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["demonic_fortitude"],
               "EffectMiscValue_2": 2,          # STAT_STAMINA, from 0 (STAT_STRENGTH)
               "EffectBasePoints_2": 29,        # DieSides 1 -> +30% Stamina
               "Effect_1": 0,                   # the +25% armour half
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "RecoveryTime": 180000,          # from 60000
               "Description_Lang_enUS":
                   "Draw on demonic reserves, increasing your total Stamina by $s2% for $d.",
           },
           note="51271 Effect_2 -- aura 137 MOD_TOTAL_STAT_PERCENTAGE; DurationIndex 18 (20 s) "
                "is the donor's"),

    # -- 8/2 -- Illidari Durability ....................... donor 33853 Survival of the Fittest
    #
    # Aura 187 MOD_ATTACKER_MELEE_CRIT_CHANCE. -6% at three ranks is the same number Survival of
    # the Fittest, Sacred Duty and Shield Specialization give, so a Vengeance Demon Hunter
    # reaches crit immunity on exactly the same defence budget as any other WotLK tank
    # (talents.md 6).
    Talent("vengeance", 8, 2, 3, "Illidari Durability", 33853,
           rank_cell="EffectBasePoints_2",
           rank_values=(-3, -5, -7),            # DieSides 1 -> lands -2/-4/-6 %
           overrides={
               "Effect_1": 0,                   # aura 137 misc -1, +all attributes
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Effect_3": 0,                   # SPELL_EFFECT_DUMMY, the bear-form armour half
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "ImplicitTargetA_3": 0,
               "Description_Lang_enUS":
                   "Reduces the chance you will be critically hit by melee attacks by $s2%.",
           },
           note="33853 Effect_2 -- aura 187"),

    # -- 9/1 -- Malevolence ............................... donor 18427 Aggression (family 8)
    #
    # SHEAR BECAME DEMON'S BITE here too: the tank's two strikes are Demon's Bite and Soul Cleave.
    Talent("vengeance", 9, 1, 3, "Malevolence", 18427,
           rank_cell="EffectBasePoints_1",
           rank_values=(4, 9, 14),              # DieSides 1 -> lands 5/10/15 %
           overrides={
               "EffectSpellClassMaskA_1": BIT["demons_bite"] | BIT["soul_cleave"],
               "Description_Lang_enUS":
                   "Increases the damage of your Demon's Bite and Soul Cleave by $s1%.",
           },
           note="18427 -- the third use of the cleanest damage modifier in the file"),

    # -- 10/1 -- Nether Bulwark ........................... donor 871 Shield Wall (family 4)
    #
    # THREE traps on one record and all three are fatal to a Demon Hunter:
    #   * `EquippedItemClass 4 / EquippedItemSubclass 64` -- it REQUIRES A SHIELD. Closed by
    #     ALWAYS, which is the only reason those cells are in that set.
    #   * `Attributes 0x10000` NOT_SHAPESHIFTED -- would grey the button out in Metamorphosis.
    #   * `ShapeshiftMask 0x20000` (Defensive Stance) -- would grey it out everywhere else.
    # Category 132 + CategoryRecoveryTime 12000 are `dhspells.TALENT_BASE`'s.
    Talent("vengeance", 10, 1, 1, "Nether Bulwark", 871, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["nether_bulwark"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,        # 0x50010 -> 0x40010
               "EffectBasePoints_1": -51,       # DieSides 1 -> -50% damage taken, from -61
               "RecoveryTime": 180000,          # 3 min, from 300000
               "Description_Lang_enUS":
                   "Nether energy shields you, reducing all damage taken by $s1% for $d.",
           },
           note="871 -- aura 87 misc 127; DurationIndex 29 is 12000 ms, read from "
                "SpellDuration.dbc, and is already what the design asks for"),
)


# =============================================================================================
# TREE 2 -- ILLIDARI (414, OrderIndex 2) -- 22 talents, 69 points
# =============================================================================================
#
# tier | col 0                | col 1                | col 2                | col 3
# -----+----------------------+----------------------+----------------------+------------------
#   0  | Fleet of Foot      5 | Improved Fel Rush  2 | Unwavering Will    5 |
#   1  | Improved Chaos Nov 3 | Shattered Restora  5 |                      |
#   2  |                      | Demonic Presence   5 | Consume Magic Mast 3 |
#   3  |                      | Master of the Gla  3 | Rush of Chaos      5 |
#   4  | Unrestrained Fury  3 | Netherwalk         1 |                      | Long Night       3
#   5  |                      | Illidari Knowledge 3 | Blur Mastery       3 |
#   6  |                      | Fel Eruption       1 | Nether Resistance  3 |
#   7  | Momentum of the Hu 5 |                      | Unnatural Malice   3 |
#   8  |                      | Vanishing Step     1 | Demonic Mending    3 |
#   9  |                      | Illidari Bond      3 |                      |
#  10  |                      | The Hunt           1 |                      |
#
# cumulative points by the end of each tier, unchanged from talents.md 7:
#  T0 12 | T1 20 | T2 28 | T3 36 | T4 43 | T5 49 | T6 53 | T7 61 | T8 65 | T9 68 | T10 69
#  gate     5  |   10  |   15  |   20  |   25  |   30  |   35  |   40  |   45  |    50

_ILLIDARI = (

    # -- 0/0 -- Fleet of Foot ............................. donor 31208 Fleet Footed (family 0)
    #
    # Three effects: two aura 232 MECHANIC_DURATION_MOD (misc 11 SNARE, misc 7 ROOT) and one
    # aura 31 MOD_INCREASE_SPEED. Only the speed scales -- the two duration halves stay at the
    # donor's own shipped -15%, flat at every rank, because the generator writes one per-rank
    # cell. See DEGRADED. This is the one place a flat component is kept rather than zeroed:
    # -15% snare duration is the whole reason a tier-0 mobility talent exists, and it is the
    # donor's number rather than an invented one.
    Talent("illidari", 0, 0, 5, "Fleet of Foot", 31208,
           rank_cell="EffectBasePoints_3",
           rank_values=(2, 5, 8, 11, 14),       # DieSides 1 -> lands 3/6/9/12/15 %
           overrides={
               "Attributes": PASSIVE_ATTRS,     # the donor is 448
               "Description_Lang_enUS":
                   "Increases your movement speed by $s3% and reduces the duration of movement "
                   "impairing effects on you by $s1%.",
           },
           note="31208 -- Effect_3 aura 31; Effects 1 and 2 stay at the donor's -16/-16"),

    # -- 0/1 -- Improved Fel Rush ......................... donor 29888 Improved Intercept
    #
    # RETUNED, and it had to be: Fel Rush's cooldown is 10 s (`dh_spec.ABILITIES`), so
    # talents.md's -5 s per rank over two ranks removes the cooldown entirely -- an infinite
    # dash, which is not a talent, it is a bug with a tooltip. -2 s per rank leaves 6 s.
    Talent("illidari", 0, 1, 2, "Improved Fel Rush", 29888,
           rank_cell="EffectBasePoints_1",
           rank_values=(-2001, -4001),          # DieSides 1 -> lands -2000/-4000 ms of 10000
           overrides={
               "EffectSpellClassMaskA_1": BIT["fel_rush"],
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Fel Rush by $/1000;s1 sec.",
           },
           note="29888 -- aura 107 SPELLMOD_COOLDOWN(11); the donor's -5001 is 5 seconds"),

    # -- 0/2 -- Unwavering Will ........................... donor 14522 Unbreakable Will (fam 0)
    #
    # Three aura 232 effects, misc 12 STUN / 5 FEAR / 9 SILENCE. Only the stun half scales; the
    # other two stay at the donor's -7%. See DEGRADED -- this is the talent the one-rank-cell
    # limit costs the most, and zeroing two thirds of a stock record to hide that would be worse.
    Talent("illidari", 0, 2, 5, "Unwavering Will", 14522,
           rank_cell="EffectBasePoints_1",
           rank_values=(-4, -7, -10, -13, -16),  # DieSides 1 -> lands -3/-6/-9/-12/-15 %.
                                                 # NEGATIVE IS THE REDUCTION, read from
                                                 # Unit.cpp:11629-11646: the mod is summed by
                                                 # GetTotalAuraModifierByMiscValue and applied
                                                 # with AddPct(duration, mod), so a positive
                                                 # value would EXTEND the stun. The two
                                                 # untouched effects keep the donor's -7.
           overrides={
               "Description_Lang_enUS":
                   "Reduces the duration of Stun effects by $s1% and of Fear and Silence "
                   "effects by $s2%.",
           },
           note="14522 -- three aura-232 effects; only misc 12 (STUN) is ranked"),

    # -- 1/0 -- Improved Chaos Nova ....................... donor 12312 Improved Disciplines
    #
    # WAS "Improved Vengeful Retreat", WHICH CANNOT EXIST. Vengeful Retreat keeps
    # `SpellClassSet = 9` because family 9 is the only thing that makes SPELL_EFFECT_LEAP_BACK go
    # backwards (`SpellEffects.cpp:5067`), and `IsAffected` requires family equality
    # (`SpellInfo.cpp:1329`) -- a family-16 modifier can never reach it. dh_spec.py:723-725 calls
    # that "an accepted loss because a fixed-distance leap has nothing worth modifying", and this
    # is the talent that pays for it. Chaos Nova (45 s, dh_spec) is the tree's other control
    # button and the same shape of talent.
    Talent("illidari", 1, 0, 3, "Improved Chaos Nova", 12312,
           rank_cell="EffectBasePoints_1",
           rank_values=(-5001, -10001, -15001),  # DieSides 1 -> lands -5/-10/-15 s of 45
           overrides={
               "EffectSpellClassMaskA_1": BIT["chaos_nova"],
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_1": 0,
               "EffectBasePoints_2": 0,         # dead cells on an empty Effect_2 slot
               "EffectDieSides_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Chaos Nova by $/1000;s1 sec.",
           },
           note="12312 -- aura 107 SPELLMOD_COOLDOWN(11), the same donor Rush of Chaos uses"),

    # -- 1/1 -- Shattered Restoration ..................... donor 63646 Divinity (family 0)
    #
    # Effect_1 is aura 118 MOD_HEALING_PCT with misc 127 -- healing RECEIVED. Effect_2 is aura 136
    # (healing done) and goes: a Demon Hunter heals nobody.
    Talent("illidari", 1, 1, 5, "Shattered Restoration", 63646,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> lands 2/4/6/8/10 %
           overrides={
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS": "Increases all healing effects on you by $s1%.",
           },
           note="63646 Effect_1 -- aura 118"),

    # -- 2/1 -- Demonic Presence .......................... donor 13712 Lightning Reflexes
    Talent("illidari", 2, 1, 5, "Demonic Presence", 13712,
           rank_cell="EffectBasePoints_2",
           rank_values=(0, 1, 2, 3, 4),         # DieSides 1 -> lands 1/2/3/4/5 %
           overrides={
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "Description_Lang_enUS": "Increases your melee attack speed by $s2%.",
           },
           note="13712 Effect_2 -- aura 138, the same donor as Havoc's Cycle of Hatred"),

    # -- 2/2 -- Consume Magic Mastery ..................... donor 12313 Improved Disarm (fam 4)
    #
    # RETUNED: Consume Magic's cooldown is 15 s (`dh_spec.ABILITIES`), so talents.md's -4 s per
    # rank over three ranks would leave 3 s -- an interrupt on a shorter cooldown than the global.
    # -2 s per rank leaves 9 s.
    # Effect_2 is aura 107 at op 12 SPELLMOD_EFFECT2 and goes; it is also, incidentally, the
    # stock precedent for the op Improved Demon's Bite and Soul Rending use.
    Talent("illidari", 2, 2, 3, "Consume Magic Mastery", 12313,
           rank_cell="EffectBasePoints_1",
           rank_values=(-2001, -4001, -6001),   # DieSides 1 -> lands -2/-4/-6 s of 15
           overrides={
               "EffectSpellClassMaskA_1": BIT["consume_magic"],
               "EffectSpellClassMaskB_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Consume Magic by $/1000;s1 sec.",
           },
           note="12313 Effect_1 -- aura 107 SPELLMOD_COOLDOWN(11)"),

    # -- 3/1 -- Master of the Glaive ...................... donor 19498 Hawk Eye (family 9)
    #
    # Aura 107 at op 5 SPELLMOD_RANGE, three ranks in stock, +2 yd each. The donor is a HUNTER
    # talent and carries hunter masks in all three words; all three are cleared, and the family
    # itself is overwritten by `dhspells.TALENT_BASE`.
    Talent("illidari", 3, 1, 3, "Master of the Glaive", 19498,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 5, 8),               # DieSides 1 -> lands +3/6/9 yards
           overrides={
               "EffectSpellClassMaskA_1": BIT["throw_glaive"] | BIT["consume_magic"],
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskA_3": 0,
               "Description_Lang_enUS":
                   "Increases the range of your Throw Glaive and Consume Magic by $s1 yards.",
           },
           note="19498 -- aura 107 SPELLMOD_RANGE(5); the value is in yards, not milliseconds"),

    # -- 3/2 -- Rush of Chaos ............................. donor 12312 Improved Disciplines
    #
    # Metamorphosis is a 180 s cooldown (`dh_spec.ABILITIES`), so five ranks take it to 120 s.
    Talent("illidari", 3, 2, 5, "Rush of Chaos", 12312,
           rank_cell="EffectBasePoints_1",
           rank_values=(-12001, -24001, -36001, -48001, -60001),   # lands -12..-60 s of 180
           overrides={
               "EffectSpellClassMaskA_1": BIT["metamorphosis"],
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_1": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Metamorphosis by $/1000;s1 sec.",
           },
           note="12312 -- aura 107 SPELLMOD_COOLDOWN(11)"),

    # -- 4/0 -- Unrestrained Fury ......................... donor 14983 Vigor (family 8)
    Talent("illidari", 4, 0, 3, "Unrestrained Fury", 14983,
           rank_cell="EffectBasePoints_1",
           rank_values=(4, 9, 14),              # DieSides 1 -> lands +5/10/15 maximum Fury
           overrides={
               "Description_Lang_enUS": "Increases your maximum Fury by $s1.",
           },
           note="14983 -- aura 35 MOD_INCREASE_ENERGY misc 3, ranked this time"),

    # -- 4/1 -- Netherwalk ................................ donor 31224 Cloak of Shadows (fam 8)
    #
    # THE CLONE PROBLEM RUNNING BACKWARDS, and it is worth reading twice. `Effect_2` is a
    # SPELL_EFFECT_TRIGGER_SPELL pointing at 35729, and 35729 is handled by a HARDCODED CASE in
    # `SpellEffects.cpp:850` ("remove all harmful spells on you"). Everywhere else in this
    # feature a hardcoded id means the behaviour does not survive a clone -- here it survives
    # precisely BECAUSE the cell keeps pointing at the stock id, which the core still recognises.
    # So the trigger is kept and no trigger row is allocated for it.
    # Effect_3 is aura 87 misc 1 with `EffectBasePoints_3 = -1`, i.e. -0% physical damage taken:
    # a stock no-op, removed rather than shipped.
    Talent("illidari", 4, 1, 1, "Netherwalk", 31224, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["netherwalk"],
               "Effect_3": 0,
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectMiscValue_3": 0,
               "ImplicitTargetA_3": 0,
               "RecoveryTime": 120000,          # 2 min, from 90000
               "Description_Lang_enUS":
                   "You slip into the Nether, removing all harmful effects and giving harmful "
                   "spells a $s1% chance to miss you for $d.",
           },
           note="31224 -- Effect_1 aura 186 MOD_ATTACKER_SPELL_HIT_CHANCE misc 126 at -90%; "
                "DurationIndex 28 is 5000 ms and the GCD is already 133/1000"),

    # -- 4/3 -- Long Night ................................ donor 14165 Improved Slice and Dice
    #
    # A percentage, like Reckless Abandon -- but here the arithmetic is exact: Darkness is 8 s
    # (`dh_donors.OVERRIDES["darkness"]["DurationIndex"] = 31`, 8000 ms), so +25%/rank is
    # +2 s/rank, which is talents.md's number to the second.
    Talent("illidari", 4, 3, 3, "Long Night", 14165,
           rank_cell="EffectBasePoints_1",
           rank_values=(24, 49, 74),            # DieSides 1 -> lands 25/50/75 % of 8 s
           overrides={
               "EffectSpellClassMaskA_1": BIT["darkness"],
               "Description_Lang_enUS": "Increases the duration of your Darkness by $s1%.",
           },
           note="14165 -- aura 108 SPELLMOD_DURATION(1)"),

    # -- 5/1 -- Illidari Knowledge ........................ donor 33853 Survival of the Fittest
    #
    # Effect_1 is aura 137 with `EffectMiscValue_1 = -1`, which is the "all stats" sentinel
    # (`HandleAuraModTotalStatPercentage` loops all five when the misc value is negative).
    Talent("illidari", 5, 1, 3, "Illidari Knowledge", 33853,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5),               # DieSides 1 -> lands 2/4/6 %
           overrides={
               "Effect_2": 0,                   # aura 187, the crit-immunity half -- Vengeance's
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Effect_3": 0,                   # SPELL_EFFECT_DUMMY
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "ImplicitTargetA_3": 0,
               "EffectSpellClassMaskB_1": 0,
               "Description_Lang_enUS": "Increases all your attributes by $s1%.",
           },
           note="33853 Effect_1 -- aura 137 with misc -1 (all stats)"),

    # -- 5/2 -- Blur Mastery .............................. donor 11252 Arcane Shielding (fam 3)
    #
    # Effect_2 is aura 108 at op 3 SPELLMOD_EFFECT1, and Blur's dodge is `EffectBasePoints_1`
    # (`dh_donors.OVERRIDES["blur"]` keeps the donor's 49, +50%), so the op is already right.
    # RETUNED from talents.md's +33%/rank: +99% of a +50% dodge buff is 99.5% dodge, which is
    # not a talent, it is immunity. +10%/rank takes Blur to 65% dodge at three ranks.
    Talent("illidari", 5, 2, 3, "Blur Mastery", 11252,
           rank_cell="EffectBasePoints_2",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 %
           overrides={
               "EffectSpellClassMaskA_2": BIT["blur"],
               "Effect_1": 0,                   # aura 108 op 27, the Mana Shield half
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "Description_Lang_enUS":
                   "Increases the Dodge chance granted by your Blur by $s2%.",
           },
           note="11252 Effect_2 -- aura 108 SPELLMOD_EFFECT1(3)"),

    # -- 6/1 -- Fel Eruption .............................. donor 20253 Intercept (Rank 1)
    #
    # Chosen over 12809 Concussion Blow because 20253 has no SPELL_EFFECT_DUMMY third effect to
    # script (talents.md 7). Three things the clone has to be told, and two of them are
    # `SpellInfoCorrections` entries that do NOT follow a clone (`:4958` fixes 20253 by id):
    #   * `Attributes` loses NOT_SHAPESHIFTED -- the correction strips it too, and without it the
    #     button is dead in Metamorphosis.
    #   * `AttributesEx7` gains NO_ATTACK_DODGE|NO_ATTACK_PARRY (SharedDefines.h:652-653), which
    #     is the other half of that same correction. A stun that can be parried is a stun that
    #     misses for reasons the player cannot see.
    #   * The damage. 20253's `Effect_2` is SCHOOL_DAMAGE with `EffectBasePoints_2 = 0` -- its
    #     real damage is `${1+$AP*0.12}`, an attack-power coefficient that lives in the
    #     `spell_bonus_data` TABLE keyed by spell id, not in the record, so a clone would hit for
    #     exactly 1. It becomes SPELL_EFFECT_WEAPON_PERCENT_DAMAGE (31), which is level-correct
    #     from one record at every level (the argument dh_donors makes for nine of the ten
    #     strikes) and needs `DefenseType 2` to route through the weapon at all.
    Talent("illidari", 6, 1, 1, "Fel Eruption", 20253, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["fel_eruption"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,        # 0x50010 -> 0x40010
               "AttributesEx7": 0x01800000,     # NO_ATTACK_DODGE | NO_ATTACK_PARRY
               "Mechanic": 12,                  # MECHANIC_STUN. With family 16 unknown to
                                                # GetDiminishingReturnsGroupForSpell
                                                # (SpellMgr.cpp:107-263) the mechanic is the only
                                                # DR input this class has -- dh_donors makes the
                                                # same argument for Chaos Nova.
               "Effect_2": 31,                  # WEAPON_PERCENT_DAMAGE, from 2 SCHOOL_DAMAGE
               "EffectBasePoints_2": 49,        # DieSides 1 -> 50% weapon damage
               "DefenseType": 2,                # MELEE, so the weapon effect uses the weapon
               "RangeIndex": 3,                 # 0/20 yd (SpellRange.dbc row 3); the donor's
                                                # row 95 has a MIN range of 8 yd, i.e. it cannot
                                                # be cast on anything standing next to you
               "RecoveryTime": 30000,
               "ManaCost": 20,                  # Fury
               "StartRecoveryCategory": 133,
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Erupts fel energy under the target, stunning it for $d and dealing weapon "
                   "damage.",
           },
           note="20253 -- Effect_1 aura 12 MOD_STUN with EffectMechanic 12 and DurationIndex 27 "
                "(3000 ms), both the donor's"),

    # -- 6/2 -- Nether Resistance ......................... donor 31224 Cloak of Shadows (fam 8)
    #
    # The same donor as Netherwalk, made into a passive: Attributes 464, the 35729 trigger and
    # the no-op third effect removed, an infinite duration and no cooldown. What is left is one
    # aura 186 effect, which is what the talent is.
    Talent("illidari", 6, 2, 3, "Nether Resistance", 31224,
           rank_cell="EffectBasePoints_1",
           rank_values=(-3, -5, -7),            # DieSides 1 -> lands -2/-4/-6 %
           overrides={
               "Attributes": PASSIVE_ATTRS,
               "Effect_2": 0,                   # THE TRIGGER. A passive that dispels everything
               "EffectBasePoints_2": 0,         # harmful the moment you learn it is not this
               "EffectDieSides_2": 0,           # talent.
               "ImplicitTargetA_2": 0,
               "EffectTriggerSpell_2": 0,
               "Effect_3": 0,
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectMiscValue_3": 0,
               "ImplicitTargetA_3": 0,
               "DurationIndex": 21,             # -1, infinite (SpellDuration.dbc row 21)
               "RecoveryTime": 0,
               "StartRecoveryCategory": 0,
               "StartRecoveryTime": 0,
               "PreventionType": 0,
               "Description_Lang_enUS":
                   "Reduces the chance harmful spells will hit you by $s1%.",
           },
           note="31224 Effect_1 -- aura 186 misc 126, made passive"),

    # -- 7/0 -- Momentum of the Hunt ...................... donor 50880 Icy Talons (family 15)
    #
    # RETARGETED FROM VENGEFUL RETREAT TO THROW GLAIVE, for the same reason Improved Chaos Nova
    # exists: Vengeful Retreat is family 9 with an empty mask and no family-16 proc entry can
    # ever name it. Throw Glaive is the tree's other repeatable button and already has a talent
    # here (Master of the Glaive), so the tree keeps its shape.
    # Aura 231 again, so five ranks share one trigger row (talents.md 2.B). ProcTypeMask is
    # replaced: the donor's 0x1010 is DONE_SPELL_MELEE_DMG_CLASS plus magic, and Throw Glaive is
    # `DefenseType 3` (ranged, from 31935 Avenger's Shield), whose flag is 0x100
    # DONE_SPELL_RANGED_DMG_CLASS (SpellMgr.h:122). UNVERIFIED -- see FLAGGED.
    Talent("illidari", 7, 0, 5, "Momentum of the Hunt", 50880,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5, 7, 9),         # DieSides 1 -> the aura's amount is 2/4/6/8/10,
                                                # and that amount is what aura 231 passes into
                                                # the buff row as basepoints0
           overrides={
               "EffectSpellClassMaskA_1": BIT["throw_glaive"],
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "ProcTypeMask": 0x00000100,      # DONE_SPELL_RANGED_DMG_CLASS, from 0x1010
               "Effect_2": 0,                   # SPELL_EFFECT_DUMMY, the DK's rank counter
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "Attributes": PASSIVE_ATTRS,     # the donor is 448
               "Description_Lang_enUS":
                   "After you land a Throw Glaive, your damage done is increased by $s1% for "
                   "6 sec.",
           },
           note="50880 -- aura 231 PROC_TRIGGER_SPELL_WITH_VALUE; the trigger row is "
                "TRIGGERS['momentum_of_the_hunt_buff']"),

    # -- 7/2 -- Unnatural Malice .......................... donor 47236 Demonic Pact (family 5)
    #
    # The fourth use of Effect_3, this time at misc 127 -- every school.
    Talent("illidari", 7, 2, 3, "Unnatural Malice", 47236,
           rank_cell="EffectBasePoints_3",
           rank_values=(1, 3, 5),               # DieSides 1 -> lands 2/4/6 %
           overrides={
               "EffectMiscValue_3": 127,
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "EffectSpellClassMaskC_2": 0,
               "Description_Lang_enUS": "Increases all damage you deal by $s3%.",
           },
           note="47236 Effect_3 -- aura 79 at every school"),

    # -- 8/1 -- Vanishing Step ............................ donor 36554 Shadowstep (family 8)
    #
    # TALENTS.MD HAS THE TWO TRIGGERS THE WRONG WAY ROUND, and it matters, because one of them is
    # the entire ability. Read from the file:
    #   36563  Effect_1 = 5 SPELL_EFFECT_TELEPORT_UNITS, ImplicitTargetB_1 = 65
    #          TARGET_DEST_TARGET_BACK  <- THIS is the teleport
    #   44373  one aura 108 SPELLMOD_THREAT effect with rogue masks  <- a threat modifier
    # talents.md 7 names 44373 as "the teleport" and 36563 as "a rogue-family damage buff that
    # could never affect DH spells" and zeroes the wrong one. Keeping 44373 and dropping 36563
    # would have shipped a 30-second cooldown that does nothing but a speed buff.
    # So `Effect_1`'s trigger is kept and re-pointed at a CLONE of 36563 (TRIGGERS), because the
    # stock row also carries two rogue spellmods and a proc charge that would sit on the player
    # as a dead buff; `Effect_2`'s trigger goes entirely.
    # Off-GCD, following dh_donors' decided rule for Vengeful Retreat and Blur: the donor is
    # already 0/0 and a movement escape on the damage rotation's global feels broken.
    Talent("illidari", 8, 1, 1, "Vanishing Step", 36554, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["vanishing_step"],
               "Effect_2": 0,                   # the 44373 trigger, a rogue threat modifier
               "EffectTriggerSpell_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskC_1": 0,
               "EffectSpellClassMaskC_2": 0,
               "ManaCost": 0,                   # the donor's 10 energy; this is a mobility
                                                # button and mobility is free in this kit
               "Description_Lang_enUS":
                   "Step through the shadows to appear behind your target, increasing your "
                   "movement speed by $s3% for $d.",
           },
           note="36554 -- Effect_3 aura 31 at +70% is the donor's, as are DurationIndex 27 "
                "(3000 ms) and RangeIndex 34 (0/25 yd); the teleport is "
                "TRIGGERS['vanishing_step_teleport'] and the generator writes "
                "EffectTriggerSpell_1"),

    # -- 8/2 -- Demonic Mending ........................... donor 63646 Divinity (family 0)
    #
    # RENAMED. talents.md calls this "Soul Rending", which is also the name of Vengeance (5,1).
    # Two different talents with one name is legal in the DBC and unreadable in the panel, and
    # the Vengeance one is the one that matches the retail ability, so this is the one that moved.
    # TIER C, form-gated: the same Divinity Effect_1 as Shattered Restoration plus a stance mask.
    Talent("illidari", 8, 2, 3, "Demonic Mending", 63646,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 5, 8),               # DieSides 1 -> lands 3/6/9 %
           overrides={
               "ShapeshiftMask": METAMORPHOSIS_STANCE,
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "While in Metamorphosis, all healing effects on you are increased by $s1%.",
           },
           note="63646 Effect_1 + ShapeshiftMask 0x400000"),

    # -- 9/1 -- Illidari Bond ............................. donor 53137 Abomination's Might
    #
    # `Effect_1 = 65 SPELL_EFFECT_APPLY_AREA_AURA_PARTY` carrying aura 166 MOD_ATTACK_POWER_PCT
    # is a party-wide attack power aura in one effect, which is the only reason this donor was
    # chosen over 30902. Effect_3 is the same thing for RANGED attack power (aura 167) and goes:
    # nothing in this kit uses a ranged weapon. Effect_2 (+Strength) goes with it.
    Talent("illidari", 9, 1, 3, "Illidari Bond", 53137,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 3, 5),               # DieSides 1 -> lands 2/4/6 %
           overrides={
               "EffectRadiusIndex_1": 11,       # 45.0 yd (SpellRadius.dbc row 11, read from the
                                                # file); the donor's row 12 is 100.0 yd
               "Effect_2": 0,
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Effect_3": 0,
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "ImplicitTargetA_3": 0,
               "EffectRadiusIndex_3": 0,
               "Attributes": PASSIVE_ATTRS,     # the donor is 80 (IS_ABILITY|PASSIVE only)
               "Description_Lang_enUS":
                   "Increases the attack power of you and your party members within $a1 yards "
                   "by $s1%.",
           },
           note="53137 Effect_1 -- effect 65 APPLY_AREA_AURA_PARTY with aura 166"),

    # -- 10/1 -- The Hunt ................................. donor 20252 Intercept (family 4)
    #
    # `Effect_1 = 96 SPELL_EFFECT_CHARGE` (SharedDefines.h:862) with `Effect_2 = 64
    # TRIGGER_SPELL` at the stun is the whole ability in one stock record.
    # UNVERIFIED, carried through from talents.md 9.6: the charge range comes from `RangeIndex`
    # and whether the pathing behaves at 30 yd -- Intercept is 8-25 -- has not been tested.
    # The trigger points at a CLONE of 20253, not at the stock row and not at Fel Eruption's
    # record: talents.md 8.1 considered sharing one row and rejected it ("possible and saves
    # exactly one row; it is not worth the coupling"), and pointing at stock 20253 would give the
    # warrior's rage-costing, stance-gated version.
    Talent("illidari", 10, 1, 1, "The Hunt", 20252, flags=1,
           overrides={
               "SpellClassMask_3": TALENT_BIT["the_hunt"],
               "Attributes": 537198608 & ~NOT_SHAPESHIFTED,     # 0x20050010 -> 0x20040010.
                                                # 20252 carries the bit too, and so does
                                                # `SpellInfoCorrections.cpp:4951`, which strips
                                                # it from the stock spell by id and therefore
                                                # not from a clone.
               "RangeIndex": 4,                 # 0/30 yd (SpellRange.dbc row 4); the donor's
                                                # row 95 is 8/25
               "RecoveryTime": 60000,
               "StartRecoveryCategory": 133,
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Charge to your target, stunning it and everything in your path.",
           },
           note="20252 -- Category 1158 and its 30 s are TALENT_BASE's; the stun is "
                "TRIGGERS['the_hunt_stun'] and the generator writes EffectTriggerSpell_2"),
)


TALENTS = _HAVOC + _VENGEANCE + _ILLIDARI


# =============================================================================================
# THE TRIGGER ROWS -- talents.md 2.B and 8.1
# =============================================================================================
#
# Five extra Spell.dbc records, one per talent that triggers something. They are NOT talents: no
# Talent.dbc row, no rank, nobody learns them. The generator allocates their ids out of the same
# 92000-92999 band after the rank records and then writes each one back into `cell` on the
# record named by `used_by`, because that id is the one thing this file cannot know.
#
# `EffectDieSides_1 = 0` ON THE TWO aura-231 TRIGGERS IS LOAD-BEARING, and it is the sort of
# thing that would otherwise be found in game by a player counting Fury. `AuraEffect::
# HandleProcTriggerSpellWithValueAuraProc` passes the aura's amount as basepoints0
# (SpellAuraEffects.cpp:6922-6936), and `SpellInfo::CalcValue` STILL adds the die on top of an
# explicit basepoints (`basePoints = bp ? *bp : BasePoints;` and only then the die switch). With
# the donor's die of 1 every rank would land one point high. Zeroing the die on the trigger --
# and only on the trigger -- makes the value the aura passes the value that arrives.
TRIGGERS = {

    # -- Blade Rhythm's Fury ............................ donor 51206 Dirge (the DK's own trigger)
    "blade_rhythm_energize": Trigger(
        donor=51206, used_by=("havoc", 2, 2), cell="EffectTriggerSpell_1",
        overrides={
            "EffectMiscValue_1": 3,             # POWER_ENERGY, from 6 POWER_RUNIC_POWER.
                                                # Spell::EffectEnergize reads
                                                # Powers(Effects[i].MiscValue) directly
                                                # (SpellEffects.cpp:1903-1906), so this one cell
                                                # is the difference between Fury and nothing.
            "EffectDieSides_1": 0,              # see the block comment -- the amount comes from
            "EffectBasePoints_1": 0,            # the aura, not from this record
            "EffectSpellClassMaskA_1": 0,       # the donor's 3, a DK mask on an energize effect
            "SpellClassSet": 16,                # the generator's TALENT_BASE covers talent RANK
                                                # records; a trigger row is not one, so the
                                                # family is written here
            "SpellClassMask_1": 0,
            "SpellClassMask_2": 0,
            "SpellClassMask_3": 0,
            "Category": 0,
            "CategoryRecoveryTime": 0,
            "MaxLevel": 0,
            "PowerType": 3,
            "ManaCost": 0,
            "ManaCostPct": 0,
            "RuneCostID": 0,
            "StartRecoveryCategory": 0,         # triggered; a GCD here would be absurd
            "StartRecoveryTime": 0,
            "Name_Lang_enUS": "Blade Rhythm",
            "Description_Lang_enUS": "Restores Fury.",
        },
        note="51206 -- SPELL_EFFECT_ENERGIZE, the row talents.md 2.B names as the canonical "
             "aura-231 partner"),

    # -- Momentum's buff ................................ donor 12880 Enrage (family 0)
    "momentum_buff": Trigger(
        donor=12880, used_by=("havoc", 4, 1), cell="EffectTriggerSpell_1",
        overrides={
            "EffectMiscValue_1": 127,           # all schools, from 1 (physical only)
            "EffectBasePoints_1": 14,           # DieSides 1 -> +15% damage done
            "DurationIndex": 32,                # 6000 ms (SpellDuration.dbc row 32); the donor's
                                                # row 29 is 12000
            "Mechanic": 0,                      # from 31 MECHANIC_ENRAGE -- otherwise the buff is
                                                # removable by Tranquilizing Shot and Soothe
                                                # Animal, which is not a drawback anyone chose
            "Category": 0,                      # the donor's 21, which would be a shared cooldown
            "CategoryRecoveryTime": 0,
            "MaxLevel": 0,
            "SpellClassSet": 16,
            "SpellClassMask_1": 0,
            "SpellClassMask_2": 0,
            "SpellClassMask_3": 0,
            "StartRecoveryCategory": 0,
            "StartRecoveryTime": 0,
            "Name_Lang_enUS": "Momentum",
            "Description_Lang_enUS": "Damage done increased by $s1%.",
        },
        note="12880 -- one aura 79 MOD_DAMAGE_PERCENT_DONE effect on the caster"),

    # -- Momentum of the Hunt's buff .................... donor 12880 Enrage (family 0)
    "momentum_of_the_hunt_buff": Trigger(
        donor=12880, used_by=("illidari", 7, 0), cell="EffectTriggerSpell_1",
        overrides={
            "EffectMiscValue_1": 127,
            "EffectDieSides_1": 0,              # the amount is the aura's, see the block comment
            "EffectBasePoints_1": 0,
            "DurationIndex": 32,                # 6000 ms
            "Mechanic": 0,
            "Category": 0,
            "CategoryRecoveryTime": 0,
            "MaxLevel": 0,
            "SpellClassSet": 16,
            "SpellClassMask_1": 0,
            "SpellClassMask_2": 0,
            "SpellClassMask_3": 0,
            "StartRecoveryCategory": 0,
            "StartRecoveryTime": 0,
            "Name_Lang_enUS": "Momentum of the Hunt",
            "Description_Lang_enUS": "Damage done increased by $s1%.",
        },
        note="12880 again -- ONE row for all five ranks, which is the whole point of aura 231"),

    # -- Vanishing Step's teleport ...................... donor 36563 Shadowstep (family 8)
    "vanishing_step_teleport": Trigger(
        donor=36563, used_by=("illidari", 8, 1), cell="EffectTriggerSpell_1",
        overrides={
            "Effect_2": 0,                      # aura 108, a rogue damage modifier
            "EffectAura_2": 0,
            "EffectBasePoints_2": 0,
            "EffectDieSides_2": 0,
            "ImplicitTargetA_2": 0,
            "EffectSpellClassMaskB_2": 0,
            "Effect_3": 0,                      # aura 108 at op 3, another one
            "EffectAura_3": 0,
            "EffectBasePoints_3": 0,
            "EffectDieSides_3": 0,
            "EffectMiscValue_3": 0,
            "ImplicitTargetA_3": 0,
            "EffectSpellClassMaskB_1": 0,
            "EffectSpellClassMaskC_1": 0,
            "ProcTypeMask": 0,                  # 16, with ProcCharges 1 -- the machinery for the
            "ProcCharges": 0,                   # rogue modifiers that just went
            "DurationIndex": 0,                 # nothing here applies an aura any more
            "SpellClassSet": 16,
            "SpellClassMask_1": 0,
            "SpellClassMask_2": 0,
            "SpellClassMask_3": 0,
            "Category": 0,
            "CategoryRecoveryTime": 0,
            "MaxLevel": 0,
            "PowerType": 3,
            "ManaCost": 0,
            "ManaCostPct": 0,
            "StartRecoveryCategory": 0,
            "StartRecoveryTime": 0,
            "Name_Lang_enUS": "Vanishing Step",
            "Description_Lang_enUS": "Teleports you behind your target.",
        },
        note="36563 Effect_1 -- SPELL_EFFECT_TELEPORT_UNITS (5) with ImplicitTargetB_1 = 65 "
             "TARGET_DEST_TARGET_BACK and EffectRadiusIndex_1 = 7 (2.0 yd) as the offset. THIS "
             "is Shadowstep's teleport; talents.md names 44373, which is a threat modifier"),

    # -- The Hunt's stun ................................ donor 20253 Intercept (Rank 1)
    "the_hunt_stun": Trigger(
        donor=20253, used_by=("illidari", 10, 1), cell="EffectTriggerSpell_2",
        overrides={
            "Attributes": 327696 & ~NOT_SHAPESHIFTED,
            "AttributesEx7": 0x01800000,        # NO_ATTACK_DODGE | NO_ATTACK_PARRY, the half of
                                                # SpellInfoCorrections.cpp:4958 a clone loses
            "Mechanic": 12,                     # MECHANIC_STUN, the only DR input family 16 has
            "ShapeshiftMask": 0,                # 0x40000, a warrior stance
            "Effect_2": 0,                      # SCHOOL_DAMAGE with BasePoints 0: the real
            "EffectBasePoints_2": 0,            # number lives in `spell_bonus_data` keyed by
            "EffectDieSides_2": 0,              # spell id and does not follow a clone, so it
            "ImplicitTargetA_2": 0,             # would hit for exactly 1. The charge is the
                                                # ability; the stun is this row.
            "RangeIndex": 4,                    # 0/30 yd, matching the charge that triggers it
            "SpellClassSet": 16,
            "SpellClassMask_1": 0,
            "SpellClassMask_2": 0,
            "SpellClassMask_3": 0,
            "Category": 0,
            "CategoryRecoveryTime": 0,
            "MaxLevel": 0,
            "PowerType": 3,
            "ManaCost": 0,
            "ManaCostPct": 0,
            "StartRecoveryCategory": 0,
            "StartRecoveryTime": 0,
            "Name_Lang_enUS": "The Hunt",
            "Description_Lang_enUS": "Stunned.",
        },
        note="20253 -- Effect_1 aura 12 MOD_STUN, EffectMechanic_1 12, DurationIndex 27 (3 s). "
             "A separate row from Fel Eruption's on purpose (talents.md 8.1)"),
}


# =============================================================================================
# THE ONE SQL SCRIPT ROW -- talents.md 2.D
# =============================================================================================
#
# Keyed by grid position, because that is the only handle this file has on a talent whose spell
# ids the generator allocates. EVERY RANK gets a row: `spell_script_names` is keyed by spell id,
# and the three ranks of Spell Deflection are three ids.
#
# WHY REUSING A DEATH KNIGHT SCRIPT IS SAFE, from reading it rather than from its name
# (`spell_dk.cpp:2295-2328`):
#
#     float chance = GetTarget()->GetUnitParryChance();
#     if (GetTarget()->IsNonMeleeSpellCast(false, false, true) ||
#         GetTarget()->HasUnitState(UNIT_STATE_CONTROLLED))
#         chance = 0.0f;
#     if ((dmgInfo.GetDamageType() == SPELL_DIRECT_DAMAGE) && roll_chance_f(chance))
#         absorbAmount = CalculatePct(dmgInfo.GetDamage(), absorbPct);
#
# where `absorbPct` is read from the script's OWN `Effects[EFFECT_0]` amount in OnEffectApply.
# There is no rune, no family test, no spell id, and no DK-specific state anywhere in it -- the
# only inputs are the target's parry chance and the aura's own value. The `-49145` in the file's
# comment is AzerothCore's "all ranks of" notation, and the loader binds by the ids in this
# table, not by that comment.
SCRIPT_NAMES = {
    ("vengeance", 7, 2): "spell_dk_spell_deflection",
}


# =============================================================================================
# THE HOLES, NAMED -- the same three tables dh_donors.py keeps, for the same reason
# =============================================================================================

# Cells that need a number and have one only by assertion. There is exactly one in the whole
# tree, because a talent is a percentage or a duration in almost every case and those are
# level-independent by construction -- which is itself the argument for the donors chosen.
UNTUNED = (
    ("havoc", 6, 1, "EffectBasePoints_1",
     "Glaive Tempest is the only talent that deals ABSOLUTE damage: 25 a second for 8 seconds, "
     "at every level from 30 to 80. The donor (26573 Consecration) is 8 per second at BaseLevel "
     "20 with EffectBonusMultiplier 0.04, so it does have spell-power scaling, but the flat half "
     "is a guess. The two ways out are dh_spec's, not this file's: EffectRealPointsPerLevel with "
     "BaseLevel at the talent's tier, or a rank ladder -- and a one-rank talent cannot have the "
     "second one."),
)

# What the one-rank-cell limit cost, and what the kit cost. Every entry is a place where the
# design in talents.md is NOT what this file emits.
DEGRADED = (
    ("havoc", 3, 1, "Furious Throws",
     "talents.md scales two numbers (+10%/rank damage AND -0.5 s/rank cooldown) off 35446 "
     "Improved Mortal Strike, whose two effects are exactly that pair. The generator writes one "
     "per-rank cell (dhspells.py: `cells[rank_cell] = talent.rank_values[r]`), so the cooldown "
     "half is dropped rather than frozen at rank 1's value. Restoring it needs either a second "
     "rank cell in the generator or a second talent."),
    ("havoc", 4, 3, "Reckless Abandon",
     "'+4 s per rank' becomes '+10% per rank', i.e. +3 s on a 30-second Metamorphosis. Aura 108 "
     "SPELLMOD_DURATION is a PERCENTAGE (AddPct in Unit::CalcSpellDuration) and no flat-duration "
     "spellmod donor exists in the survey."),
    ("vengeance", 0, 0, "Fel Hardiness",
     "16252's second effect (-7%/rank snare duration) dropped -- one rank cell."),
    ("vengeance", 0, 2, "Thick Hide",
     "12299's second effect (-7%/rank snare duration) dropped -- one rank cell. The class keeps "
     "snare-duration reduction through Illidari's Fleet of Foot, which carries the donor's own "
     "flat -15%."),
    ("illidari", 0, 0, "Fleet of Foot",
     "Effects 1 and 2 (-15% snare and root duration) stay FLAT at the donor's own value at every "
     "rank; only the movement speed scales. The alternative was zeroing them, which would leave "
     "the class with no snare mitigation anywhere."),
    ("illidari", 0, 2, "Unwavering Will",
     "Only the Stun third scales; Fear and Silence stay flat at the donor's -6%. The most "
     "expensive case of the one-rank-cell limit in the three trees."),
    ("havoc", 8, 1, "Deathblow",
     "THE NAMED DEGRADATION (talents.md 5). Cold Blood's charge refund on a failed cast is "
     "`Spell.cpp:2702`, `RestoreSpellMods(this, 14177)`, on a hardcoded id: a fizzled cast eats "
     "the charge. Accepted -- it degrades toward less power and fixing it is a core edit."),
    ("illidari", 1, 0, "Improved Chaos Nova",
     "REPLACES Improved Vengeful Retreat, which cannot be built: Vengeful Retreat is family 9 "
     "with an empty mask (dh_spec.py:723-725) and IsAffected requires family equality."),
    ("illidari", 7, 0, "Momentum of the Hunt",
     "Triggers off Throw Glaive instead of Vengeful Retreat, for the same reason."),
    ("illidari", 8, 2, "Demonic Mending",
     "Renamed from talents.md's 'Soul Rending', which collides with Vengeance (5,1)."),
    ("havoc", 6, 1, "Glaive Tempest",
     "REPLACES Eye Beam, which dh_spec teaches at level 56 as a baseline ability."),
    ("vengeance", 3, 1, "Demon Spikes",
     "REPLACES Fiery Brand, which dh_spec teaches at level 36. Demon Spikes is the ability "
     "talents.md's own Feed the Demon was written against, and moving it one tier up (swapping "
     "with Feed the Demon) is what lets that talent point at something a player can already own."),
    ("havoc", 0, 1, "Improved Demon's Bite",
     "A Fury-cost reduction on Demon's Bite is inert -- dh_spec gives it cost=0 and dh_donors "
     "gives it a 20-Fury energize. It adds to the generation instead (SPELLMOD_EFFECT2)."),
    ("illidari", 0, 1, "Improved Fel Rush",
     "-5 s/rank over two ranks removes Fel Rush's entire 10 s cooldown. Retuned to -2 s/rank."),
    ("illidari", 2, 2, "Consume Magic Mastery",
     "-4 s/rank over three ranks would leave a 3-second interrupt. Retuned to -2 s/rank."),
    ("illidari", 5, 2, "Blur Mastery",
     "+33%/rank of Blur's +50% dodge is 99.5% dodge at three ranks. Retuned to +10%/rank."),
)

# Decisions this file makes that a human should look at once the panel opens, and the two places
# where the reasoning is read rather than observed.
FLAGGED = (
    ("havoc", 4, 1, "ProcTypeMask",
     "Momentum's proc flags are 0x11000 (DONE_SPELL_MAGIC_DMG_CLASS_NEG | "
     "DONE_SPELL_NONE_DMG_CLASS_NEG, SpellMgr.h:128-134) because Fel Rush is DefenseType 1 and "
     "its damage arrives on the fel_rush_impact record. UNVERIFIED: which flag a targetless dash "
     "actually raises was read out of the enum, not observed. If it never procs, the next thing "
     "to try is 0x1 KILLED/0x4 DONE_MELEE_AUTO_ATTACK -- or moving the trigger to the impact."),
    ("illidari", 7, 0, "ProcTypeMask",
     "Momentum of the Hunt uses 0x100 DONE_SPELL_RANGED_DMG_CLASS because Throw Glaive is "
     "DefenseType 3. Same class of assumption. Note the talent reads 'after you LAND a Throw "
     "Glaive' rather than 'after you use one' precisely because a done-damage proc flag cannot "
     "fire on a miss."),
    ("illidari", 10, 1, "RangeIndex",
     "The Hunt charges 30 yd where stock Intercept is 8-25. talents.md 9.6 flags the pathing as "
     "untested and it stays untested here."),
    ("havoc", 6, 1, "Description_Lang_enUS",
     "Every description in this file is authored, because the generator does not write one and "
     "a clone otherwise inherits the donor's -- 'Increases the damage of your Sinister Strike' "
     "on a Demon Hunter talent. What is NOT authored is AuraDescription_Lang_enUS, which is the "
     "text on the buff icon for the eleven granted actives; those still read as the donor's."),
    ("vengeance", 7, 0, "Bladed Armor",
     "The rank values are Blizzard's own for this spell (48978/49390/49391/49392/49393 = "
     "179/89/59/44/35). They are a DIVISOR -- StatSystem.cpp:513 is `GetArmor() / GetAmount()` "
     "-- so if the tuning pass wants a different curve it must keep every value positive."),
)


# =============================================================================================
# ALWAYS, APPLIED
# =============================================================================================
#
# Merged UNDER each talent's own cells, in the same place and for the same reason dh_donors.py
# applies its OFF_GCD block at the bottom of the file: the data above reads as the design, and
# the cells that are wrong on every clone are stated once. A talent that sets the cell itself
# wins -- which is how the three form-gated talents keep their ShapeshiftMask and the eleven
# granted actives keep their SpellClassMask_3 bit.
for _t in TALENTS:
    for _col, _value in ALWAYS.items():
        _t.overrides.setdefault(_col, _value)


# =============================================================================================
# IMPORT-TIME CHECKS
#
# A design error must fail HERE, at import, and not in game. Everything below is checked rather
# than trusted, including the numbers this file's own comments quote: the per-tier point totals
# in the three grid comments are recomputed from `ranks` and re-tested against the tier gate, so
# a talent whose rank count changes cannot leave a stale comment behind claiming it is fine.
# =============================================================================================

_COLS = set(dbc_tables.SPELL_DBC.columns)
_FLOAT_COLS = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
               if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_FLOAT}
_STRING_COLS = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
                if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_STRING}

# ---- the tabs, against dh_spec ---------------------------------------------------------------
assert TABS == tuple((tid, name, order) for tid, name, order, _bg in dh_spec.TALENT_TABS), (
    f"TABS {TABS} disagrees with dh_spec.TALENT_TABS {dh_spec.TALENT_TABS} -- dh_spec is the "
    f"authority the generator reads")
assert TABS[0][0] == dh_spec.TALENT_TAB_ID_BASE == 412, (
    "the tab block is 412/413/414: TalentTab.dbc's stock maximum is 411 (33 rows, ids 41..411), "
    "and talents.md's 401-403 is a different free block that dh_spec did not reserve")

# ---- the grid ---------------------------------------------------------------------------------
_seen = {}
for _t in TALENTS:
    _where = f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}"
    assert _t.tab in TAB_KEYS, f"{_where}: unknown tab"
    assert 0 <= _t.tier <= 10, (
        f"{_where}: TierID is 0-10. The frame renders 15 (MAX_NUM_TALENT_TIERS) but the "
        f"5-points-per-tier gate makes 10 the deepest reachable tier, and every stock tree "
        f"stops there")
    assert 0 <= _t.col <= 3, f"{_where}: ColumnIndex must be 0-3 (NUM_TALENT_COLUMNS)"
    assert _t.ranks in (1, 2, 3, 5), (
        f"{_where}: {_t.ranks} ranks. Stock uses 1, 2, 3 and 5 and NEVER 4 -- 892 rows checked "
        f"(talents.md 1.4)")
    assert (_t.tab, _t.tier, _t.col) not in _seen, (
        f"{_where}: already taken by {_seen.get((_t.tab, _t.tier, _t.col))!r}")
    _seen[(_t.tab, _t.tier, _t.col)] = _t.name
    assert _t.flags in (0, 1), f"{_where}: Talent.dbc Flags is 0 or 1, nothing else"
    assert isinstance(_t.donor, int) and _t.donor > 0, f"{_where}: donor must be a spell id"

assert len(TALENTS) == 66, f"66 talents, 22 per tree; got {len(TALENTS)}"
for _tab in TAB_KEYS:
    _n = sum(1 for _t in TALENTS if _t.tab == _tab)
    assert _n == 22, f"{_tab}: 22 talents, got {_n}"

# ---- the cells --------------------------------------------------------------------------------
for _t in TALENTS:
    _where = f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}"
    for _col, _value in _t.overrides.items():
        assert _col in _COLS, f"{_where}: {_col!r} is not a Spell.dbc column"
        if _col in _STRING_COLS:
            assert isinstance(_value, str), f"{_where}: {_col!r} is a string column"
        elif _col in _FLOAT_COLS:
            assert isinstance(_value, float), f"{_where}: {_col!r} is a float column"
        else:
            assert isinstance(_value, int) and not isinstance(_value, bool), (
                f"{_where}: {_col!r} must be an int, got {_value!r}")
    if _t.rank_cell:
        assert _t.rank_cell in _COLS, f"{_where}: rank_cell {_t.rank_cell!r} is not a column"
        assert _t.rank_cell not in _STRING_COLS, f"{_where}: rank_cell cannot be a string column"
        assert _t.rank_cell not in _t.overrides, (
            f"{_where}: {_t.rank_cell!r} is in BOTH overrides and rank_cell. The generator writes "
            f"overrides first and the rank value second, so the override would be silently "
            f"discarded -- pick one")
        assert len(_t.rank_values) == _t.ranks, (
            f"{_where}: {len(_t.rank_values)} rank_values for {_t.ranks} ranks")
        assert all(isinstance(_v, int) and not isinstance(_v, bool) for _v in _t.rank_values), (
            f"{_where}: rank_values must be ints")
    else:
        assert not _t.rank_values, (
            f"{_where}: rank_values with no rank_cell -- nothing would write them")
    assert _t.ranks == 1 or _t.rank_cell, (
        f"{_where}: {_t.ranks} ranks and no rank_cell, so every rank would be an identical "
        f"record and the extra points would buy nothing")

# Aura 285 MOD_ATTACK_POWER_OF_ARMOR is a DIVISOR (StatSystem.cpp:513), so a zero or negative
# value is a division by zero on every stat update. Checked by name because there is exactly one.
for _t in TALENTS:
    if _t.donor == 48978:
        assert all(_v > 0 for _v in _t.rank_values), (
            f"{_t.name}: aura 285's amount divides GetArmor(); every rank value must be > 0")

# ---- the arrows -------------------------------------------------------------------------------
for _t in TALENTS:
    if not _t.prereq:
        continue
    _where = f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}"
    assert len(_t.prereq) == 3, f"{_where}: prereq is (tier, col, rank)"
    _ptier, _pcol, _prank = _t.prereq
    _tail = [x for x in TALENTS if (x.tab, x.tier, x.col) == (_t.tab, _ptier, _pcol)]
    assert _tail, f"{_where}: prerequisite at ({_ptier},{_pcol}) does not exist in {_t.tab}"
    _tail = _tail[0]
    # dhspells.build_talents check #45 requires this, and so does the client: an arrow whose tail
    # is in the same tier or below cannot be drawn by TalentFrame_DrawLines.
    assert _ptier < _t.tier, (
        f"{_where}: prerequisite {_tail.name!r} is in tier {_ptier}, which is not EARLIER than "
        f"{_t.tier}")
    # PrereqRank_1 is a 0-based floor (Player.cpp:14329 iterates `rank = DependsOnRank; rank <
    # MAX_TALENT_RANK`), so it must be a rank the tail actually has.
    assert 0 <= _prank < _tail.ranks, (
        f"{_where}: prerequisite rank {_prank} is outside {_tail.name!r}'s {_tail.ranks} ranks "
        f"(the value is a 0-BASED floor, so 'fully ranked' is ranks - 1)")

# ---- the tier gate ----------------------------------------------------------------------------
#
# `Player::LearnTalent` (Player.cpp:14360-14362): `if (spentPoints < talentInfo->Row *
# MAX_TALENT_RANK) return;`, with MAX_TALENT_RANK 5. So every tier N needs 5N points spendable
# ABOVE it, and the client enforces the same rule at TalentFrameBase.lua:184.
TIER_POINTS = {}
for _t in TALENTS:
    TIER_POINTS.setdefault(_t.tab, {}).setdefault(_t.tier, 0)
    TIER_POINTS[_t.tab][_t.tier] += _t.ranks

TREE_POINTS = {_tab: sum(_tiers.values()) for _tab, _tiers in TIER_POINTS.items()}

CUMULATIVE = {}
for _tab, _tiers in TIER_POINTS.items():
    _run = 0
    CUMULATIVE[_tab] = {}
    for _tier in range(11):
        _run += _tiers.get(_tier, 0)
        CUMULATIVE[_tab][_tier] = _run

for _tab in TAB_KEYS:
    assert TREE_POINTS[_tab] == 69, (
        f"{_tab} full-clears for {TREE_POINTS[_tab]} points, not 69. 69 is the load-bearing "
        f"number in talents.md 1.2: below 71 the whole tree is buyable at the level-60 cap and "
        f"the third tree is free filler; above 99 it can never be maxed at 80.")
    for _tier in range(1, 11):
        _available = CUMULATIVE[_tab][_tier - 1]
        assert _available >= _tier * 5, (
            f"{_tab} tier {_tier} needs {_tier * 5} points spent above it and only "
            f"{_available} exist -- the tier is unreachable (Player.cpp:14361)")

# ---- the masks --------------------------------------------------------------------------------
assert len(set(TALENT_BIT.values())) == len(TALENT_BIT), "TALENT_BIT has a duplicate bit"
for _key, _bit in TALENT_BIT.items():
    assert _bit and not (_bit & (_bit - 1)), f"TALENT_BIT[{_key!r}] must be exactly one bit"

_ACTIVES = tuple(_t for _t in TALENTS if _t.flags == 1)
assert len(_ACTIVES) == len(TALENT_BIT), (
    f"{len(_ACTIVES)} talents grant a spellbook button but TALENT_BIT has {len(TALENT_BIT)} "
    f"entries -- every granted active needs its own family bit or no later talent can name it")
for _t in _ACTIVES:
    _where = f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}"
    assert _t.ranks == 1, (
        f"{_where}: Flags = 1 with {_t.ranks} ranks. Every stock active-granting talent is one "
        f"rank, and more than one would put several ids of the same button in the spellbook")
    _own = _t.overrides.get("SpellClassMask_3", 0)
    assert _own in TALENT_BIT.values(), (
        f"{_where}: SpellClassMask_3 is {_own:#x}, which is not one of TALENT_BIT's bits")
assert len({_t.overrides["SpellClassMask_3"] for _t in _ACTIVES}) == len(_ACTIVES), (
    "two granted actives share a SpellClassMask_3 bit")

# Nothing may write word 1 or word 2 of its own mask: those belong to dh_donors' ability kit and
# to its second records, and a talent rank record wearing an ability's bit would be modified by
# every talent that names that ability.
for _t in TALENTS:
    for _col in ("SpellClassMask_1", "SpellClassMask_2"):
        assert _t.overrides.get(_col, 0) == 0, (
            f"{_t.name}: {_col} must stay 0 -- words 1 and 2 are the ability kit's "
            f"(dh_donors.BIT and dh_donors.SECOND_RECORDS)")

# Every modifier mask a talent writes must name bits that exist. Words A and B are the ability
# kit's, word C is TALENT_BIT's.
_KIT_MASK = 0
for _v in BIT.values():
    _KIT_MASK |= _v
_TALENT_MASK = 0
for _v in TALENT_BIT.values():
    _TALENT_MASK |= _v
for _t in TALENTS:
    for _n in (1, 2, 3):
        _m = _t.overrides.get(f"EffectSpellClassMaskA_{_n}", 0)
        assert _m & ~_KIT_MASK == 0, (
            f"{_t.name}: EffectSpellClassMaskA_{_n} = {_m:#x} names a word-1 bit no ability owns "
            f"(the kit is {_KIT_MASK:#x})")
        _m = _t.overrides.get(f"EffectSpellClassMaskC_{_n}", 0)
        assert _m & ~_TALENT_MASK == 0, (
            f"{_t.name}: EffectSpellClassMaskC_{_n} = {_m:#x} names a word-3 bit no talent-"
            f"granted spell owns")

# ---- the form-gated three ---------------------------------------------------------------------
#
# talents.md 2.C: the passive must be PASSIVE|DO_NOT_DISPLAY for HandleShapeshiftBoosts to pick
# it up (SpellAuraEffects.cpp:1450-1453 skips anything that is not), and it must not be one of
# the granted actives.
for _t in TALENTS:
    if _t.overrides.get("ShapeshiftMask"):
        _where = f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}"
        assert _t.overrides["ShapeshiftMask"] == METAMORPHOSIS_STANCE, (
            f"{_where}: the only stance a Demon Hunter has is form "
            f"{dh_spec.SHAPESHIFT_FORM_ID}")
        assert _t.flags == 0, f"{_where}: a form-gated passive cannot also grant a button"

# ---- the triggers -----------------------------------------------------------------------------
for _key, _trg in TRIGGERS.items():
    assert isinstance(_trg.donor, int) and _trg.donor > 0, f"TRIGGERS[{_key!r}]: bad donor"
    _owner = [x for x in TALENTS if (x.tab, x.tier, x.col) == _trg.used_by]
    assert _owner, f"TRIGGERS[{_key!r}]: used_by {_trg.used_by} is not a talent"
    _owner = _owner[0]
    assert _trg.cell in _COLS and _trg.cell.startswith("EffectTriggerSpell_"), (
        f"TRIGGERS[{_key!r}]: {_trg.cell!r} is not an EffectTriggerSpell_* column")
    assert _trg.cell not in _owner.overrides, (
        f"TRIGGERS[{_key!r}]: {_owner.name} already sets {_trg.cell!r}; the generator owns that "
        f"cell because only it knows the trigger row's id")
    for _col, _value in _trg.overrides.items():
        assert _col in _COLS, f"TRIGGERS[{_key!r}]: {_col!r} is not a Spell.dbc column"
        if _col in _STRING_COLS:
            assert isinstance(_value, str), f"TRIGGERS[{_key!r}]: {_col!r} is a string column"
        else:
            assert isinstance(_value, int) and not isinstance(_value, bool), (
                f"TRIGGERS[{_key!r}]: {_col!r} must be an int")
assert len({_t.used_by for _t in TRIGGERS.values()}) == len(TRIGGERS), (
    "two triggers claim the same talent; the generator would write one cell twice")

# ---- the script row ---------------------------------------------------------------------------
for _pos, _script in SCRIPT_NAMES.items():
    assert [x for x in TALENTS if (x.tab, x.tier, x.col) == _pos], (
        f"SCRIPT_NAMES names {_pos}, which is not a talent")
    assert isinstance(_script, str) and _script, "SCRIPT_NAMES values are script names"

# ---- the id budget ----------------------------------------------------------------------------
RANK_ROWS = sum(_t.ranks for _t in TALENTS)
TRIGGER_ROWS = len(TRIGGERS)
SPELL_ROWS = RANK_ROWS + TRIGGER_ROWS
ID_BAND = dh_spec.TALENT_SPELL_ID_MAX - dh_spec.TALENT_SPELL_ID_BASE
assert SPELL_ROWS <= ID_BAND, (
    f"{SPELL_ROWS} Spell.dbc rows do not fit in the {ID_BAND}-id band "
    f"{dh_spec.TALENT_SPELL_ID_BASE}-{dh_spec.TALENT_SPELL_ID_MAX - 1}")
assert RANK_ROWS == 207, f"3 x 69 = 207 rank records expected, got {RANK_ROWS}"

# ---- the tables at the bottom -----------------------------------------------------------------
for _tab, _tier, _col, _cell, _why in UNTUNED:
    assert (_tab, _tier, _col) in _seen, f"UNTUNED names a talent that does not exist: {_cell}"
    assert _cell in _COLS, f"UNTUNED names {_cell!r}, which is not a Spell.dbc column"
for _row in DEGRADED + FLAGGED:
    assert (_row[0], _row[1], _row[2]) in _seen, f"{_row[0]} ({_row[1]},{_row[2]}) is not a talent"


if __name__ == "__main__":
    print(f"dh_talents -- {len(TALENTS)} talents, {RANK_ROWS} rank records + {TRIGGER_ROWS} "
          f"trigger records = {SPELL_ROWS} Spell.dbc rows")
    print(f"             ids {dh_spec.TALENT_SPELL_ID_BASE}-"
          f"{dh_spec.TALENT_SPELL_ID_BASE + SPELL_ROWS - 1} of the "
          f"{dh_spec.TALENT_SPELL_ID_BASE}-{dh_spec.TALENT_SPELL_ID_MAX - 1} band "
          f"({ID_BAND - SPELL_ROWS} spare)")
    print(f"             Talent.dbc ids {dh_spec.TALENT_ID_BASE}-"
          f"{dh_spec.TALENT_ID_BASE + len(TALENTS) - 1}; TalentTab.dbc "
          f"{', '.join(str(t) for t, _n, _o in TABS)}")
    print()

    for tab_id, tab_name, order in TABS:
        key = tab_name.lower()
        rows = [t for t in TALENTS if t.tab == key]
        print(f"=== {tab_id}  {tab_name}  (OrderIndex {order}) -- {len(rows)} talents, "
              f"{TREE_POINTS[key]} points")
        print(f"{'tier':>4} | {'col 0':<22} | {'col 1':<22} | {'col 2':<22} | col 3")
        print("-" * 4 + "-+-" + "-" * 22 + "-+-" + "-" * 22 + "-+-" + "-" * 22 + "-+-" + "-" * 22)
        for tier in range(11):
            cells = []
            for col in range(4):
                here = [t for t in rows if t.tier == tier and t.col == col]
                if not here:
                    cells.append(" " * 22)
                    continue
                t = here[0]
                star = "*" if t.flags else " "
                arrow = "^" if t.prereq else " "
                cells.append(f"{t.name[:19]:<19}{star}{arrow}{t.ranks}")
            print(f"{tier:>4} | " + " | ".join(cells).rstrip())
        avail = "  ".join(f"T{t}{CUMULATIVE[key][t]:>3}" for t in range(11))
        gate = "  ".join(f"T{t}{t * 5:>3}" for t in range(11))
        print(f"     cumulative {avail}")
        print(f"     gate needs {gate}")
        print()

    print("(* grants a spellbook button, ^ has a prerequisite arrow, trailing digit = ranks)")
    print()

    for tab_id, tab_name, order in TABS:
        key = tab_name.lower()
        print(f"--- {tab_name} ---")
        for t in [x for x in TALENTS if x.tab == key]:
            pre = f"  prereq ({t.prereq[0]},{t.prereq[1]}) @ rank {t.prereq[2]}" if t.prereq else ""
            print(f"  ({t.tier},{t.col}) {t.name:<24} {t.ranks} rank(s)  donor {t.donor:<6}"
                  f"  flags {t.flags}{pre}")
            if t.rank_cell:
                print(f"        {t.rank_cell} = {', '.join(str(v) for v in t.rank_values)}")
            for col, value in t.overrides.items():
                if col in _STRING_COLS:
                    print(f"        {col:<26} {value!r}")
                elif col.startswith(("SpellClassMask", "EffectSpellClassMask", "Attributes")):
                    print(f"        {col:<26} {value:#010x}")
                else:
                    print(f"        {col:<26} {value}")
            if t.note:
                print(f"        note: {t.note}")
        print()

    print(f"TRIGGERS -- {len(TRIGGERS)} extra records the generator must number and point at")
    for key, trg in TRIGGERS.items():
        owner = [x for x in TALENTS if (x.tab, x.tier, x.col) == trg.used_by][0]
        print(f"  {key}: donor {trg.donor} -> {owner.name} ({trg.used_by[0]} "
              f"{trg.used_by[1]},{trg.used_by[2]}).{trg.cell}, {len(trg.overrides)} cells")
        print(f"      {trg.note}")
    print()

    print(f"SCRIPT_NAMES -- {len(SCRIPT_NAMES)} spell_script_names row(s), one per RANK")
    for pos, script in SCRIPT_NAMES.items():
        owner = [x for x in TALENTS if (x.tab, x.tier, x.col) == pos][0]
        print(f"  {owner.name} ({pos[0]} {pos[1]},{pos[2]}), {owner.ranks} ranks -> {script}")
    print()

    print(f"UNTUNED -- {len(UNTUNED)} cell(s) with a number nobody measured")
    for tab, tier, col, cell, why in UNTUNED:
        print(f"  {tab} ({tier},{col}).{cell}: {why}")
    print()

    print(f"DEGRADED -- {len(DEGRADED)} place(s) where this file is NOT talents.md")
    for tab, tier, col, name, why in DEGRADED:
        print(f"  {name} ({tab} {tier},{col}): {why}")
    print()

    print(f"FLAGGED -- {len(FLAGGED)} decision(s) a human should look at once the panel opens")
    for tab, tier, col, what, why in FLAGGED:
        print(f"  {tab} ({tier},{col}) [{what}]: {why}")
    print()

    print(f"{sum(len(t.overrides) for t in TALENTS)} per-talent cells + {len(ALWAYS)} "
          f"always-applied, {len(BIT)} ability bits imported from dh_donors, "
          f"{len(TALENT_BIT)} talent bits allocated in SpellClassMask_3")
