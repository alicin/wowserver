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
TABS = ((412, "Demonology", 0), (413, "Slaying", 1), (414, "Felblood", 2))

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
# ONE WORD-1 BIT PER ABILITY, derived from the id allocation rather than from the donor table.
#
# It used to read `dh_donors.OVERRIDES[key]["SpellClassMask_1"]`, i.e. whatever bit the donor
# override happened to write. That made sense while every ability was hand-built from a donor.
# It stopped making sense the moment abilities became TRANSPLANTS: an imported record arrives
# with the SOURCE server's SpellClassMask, which is meaningless here, so the bit has to be
# assigned by us and the only stable thing to assign it from is the block index -- the same
# number that already decides the ability's spell id.
#
# Block index is position in ABILITY_BLOCK_ORDER, which is append-only, so a bit never moves
# under a talent that names it. Word 1 is 32 bits and the kit is 27 blocks, which fits with
# room; second records are excluded because each already carries its PARENT's word-1 bit, so a
# talent naming the parent reaches the triggered half for free.
# Ten ranked abilities take bits 0-9, one per ABILITY_BLOCKS block; the twenty single-record
# abilities take 10 + their position in SINGLES_ORDER, i.e. bits 10-29. Two bits spare in the
# word, which is the headroom for phase 3.
#
# The split exists because the two halves of the kit are allocated differently: a ranked
# ability owns a 20-id BLOCK and is identified by the block index, while every single shares
# one block and is identified by its position inside it. Deriving both from `ABILITY_BLOCKS`
# alone would give all twenty singles the same bit, so a talent naming Sunder would also modify
# Oblivion, Blur and eighteen others -- silently, since the mask would still be a legal value.
BIT = {}
for _key, _index in dh_spec.ABILITY_BLOCKS.items():
    if _key in dh_spec.SECOND_SOURCES or _key in ("singles", "singles2"):
        continue
    BIT[_key] = 1 << _index
for _i, _key in enumerate(dh_spec.SINGLES_ORDER):
    BIT[_key] = 1 << (10 + _i)
assert len(set(BIT.values())) == len(BIT), "two abilities share a word-1 bit"
assert max(BIT.values()) < (1 << 32), "the ability kit has outgrown SpellClassMask_1"

# The Demon Hunter's named unions (OFFENSIVE, FURY_SPENDERS) lived here. They are gone rather
# than retargeted: they existed for talents that named "every damaging ability" as one mask,
# and no Felsworn talent does -- each of the three trees declares the specific bits it modifies
# next to the talent that modifies them, which is easier to check and harder to get subtly
# wrong than a union defined four hundred lines away.



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
# A GRANTED ACTIVE'S SPELL-FAMILY BIT -- THE RANGES, not the table.
#
# A talent that hands out a castable spell needs a bit in SpellClassMask_3 when -- and only
# when -- another talent modifies that spell: SpellInfo::IsAffected matches the modifier's
# EffectSpellClassMask against the target's SpellClassMask, so a granted active left at mask 0
# is unreachable by every modifier and the modifier silently does nothing.
#
# The bits themselves are declared by each tree, next to the talent that owns them, because
# that is where a reviewer can see the modifier and the target together. What CANNOT be checked
# there is the only way this goes wrong: two trees picking the same bit, which would make one
# tree's modifier silently affect the other tree's ability. So the trees own the values, this
# file owns the RANGES, and the assertion below verifies the partition after all three load.
TALENT_BIT_RANGES = {
    "demonology": range(0, 8),      # bits 0-7
    "slaying":    range(8, 16),     # bits 8-15
    "felblood":   range(16, 24),    # bits 16-23
}

# The Metamorphosis form mask, for the three form-gated passives (talents.md 2.C).
# `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1460-1476) walks the player's TALENT
# map on every form change and casts any talent spell that is PASSIVE|DO_NOT_DISPLAY and whose
# `Stances` mask includes the new form -- with no id switch anywhere on the path.
# dh_spec.SHAPESHIFT_FORM_ID is 23, and the cell is a mask of (form - 1).
INNER_DEMON_STANCE = 1 << (dh_spec.SHAPESHIFT_FORM_ID - 1)
# The gate kept its VALUE and changed its NAME: form 23 was Metamorphosis and is now
# Inner Demon. Aliased rather than renamed-and-forgotten because the tree modules are
# imported BELOW this line and read it during their own import -- defining the alias
# after them is a circular-import failure, which is exactly how this was found.
METAMORPHOSIS_STANCE = INNER_DEMON_STANCE        # 0x00400000

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

    # ---- A SECOND PER-RANK CELL -------------------------------------------------------------
    #
    # The Demon Hunter's talents were all "one number per rank", so the generator wrote exactly
    # one cell (dhspells.py, `cells[rank_cell] = talent.rank_values[r]`). An imported tree is
    # full of talents that are TWO numbers -- "+3% damage AND +2% crit per rank", where the two
    # live in different effects of the same record. With only one cell written, the second
    # number stays frozen at whatever rank 1 of the source carried, so a five-point talent
    # visibly improves one half and silently does nothing for the other.
    rank_cell_2: str = ""
    rank_values_2: tuple = ()

    # ProcTypeMask. Non-zero makes SpellMgr.cpp:2160+ synthesise the proc entry from the record
    # alone, with no spell_proc row and no validator involvement -- which is how ~35 of these
    # talents proc at all. Zero on a talent that needs one is a passive that never fires, with
    # nothing logged at any level.
    proc_flags: int = 0

    # `source` mirrors Ability.source: the third-party record whose 234 cells are transplanted
    # instead of `donor` being cloned. `donor` stays required for the same reason it does there
    # -- it is the row cloned before the transplant overwrites it.
    source: int = 0


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

# =============================================================================================
# THE TREES
# =============================================================================================
#
# One module per tree, imported rather than written here, for the same reason the ability
# ladder moved to fs_abilities.py: this file is the SHAPE of a talent -- what a Talent row is,
# what a tier gate means, how a prerequisite resolves -- and those are the CONTENT.
#
# Each tree names, per talent, the Ascension record whose cells are transplanted. They are
# separate modules and not one because they are separately reviewable: a tree is the unit a
# person can actually hold in their head and check against the grid, and three 1,400-line
# modules diff far better than one 4,200-line one when a single tier is re-tuned.
import fs_talents_demonology                                        # noqa: E402
import fs_talents_felblood                                          # noqa: E402
import fs_talents_slaying                                           # noqa: E402
from fs_talents_demonology import TALENTS_DEMONOLOGY                # noqa: E402
from fs_talents_felblood import TALENTS_FELBLOOD                    # noqa: E402
from fs_talents_slaying import TALENTS_SLAYING                      # noqa: E402

_DEMONOLOGY = TALENTS_DEMONOLOGY
_SLAYING = TALENTS_SLAYING
_FELBLOOD = TALENTS_FELBLOOD


TALENTS = _DEMONOLOGY + _SLAYING + _FELBLOOD


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
# TRIGGERS -- empty for Felsworn, and that is a real difference rather than an oversight.
#
# The Demon Hunter needed five: a talent whose record had to point at a SECOND record that did
# not exist anywhere, so the generator allocated one and filled the cell in a later pass. An
# imported talent almost never needs that, because the record it points at usually already
# exists in the source kit and comes across as an ordinary transplant with its own id -- which
# `Plan.remap_source_references` then repoints for free.
#
# Where the source's trigger was NOT imported, the reference is zeroed and reported by that
# same pass rather than silently left pointing into another realm's id space. Anything that
# turns out to need a real second record gets an entry here.
TRIGGERS = {}


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
# SCRIPT_NAMES, keyed by GRID POSITION -- (tab, tier, col) -- and merged from the trees, each
# of which declares the scripts its own talents need next to those talents. Keyed by position
# and not by spell id for the reason the generator's #57 check exists: a talent's ranks are
# separate spells and the script has to bind to every one of them, so the position is the only
# stable name the tree can use for a talent whose ids it cannot know.
# The tree tables key by (tier, col) because a tree already knows which tab it is; the tab is
# prepended here so the key is unique across all three.
SCRIPT_NAMES = {}
for _tab, _mod, _table in (
        ("demonology", fs_talents_demonology, "SCRIPT_NAMES_DEMONOLOGY"),
        ("slaying", fs_talents_slaying, "SCRIPT_NAMES_SLAYING"),
        ("felblood", fs_talents_felblood, "SCRIPT_NAMES_FELBLOOD")):
    for _pos, _name in (getattr(_mod, _table, None) or {}).items():
        _key = _pos if len(_pos) == 3 else (_tab,) + tuple(_pos)
        assert _key not in SCRIPT_NAMES, f"two trees claim script slot {_key}"
        SCRIPT_NAMES[_key] = _name


# =============================================================================================
# THE HOLES, NAMED -- the same three tables dh_donors.py keeps, for the same reason
# =============================================================================================

# Cells that need a number and have one only by assertion. There is exactly one in the whole
# tree, because a talent is a percentage or a duration in almost every case and those are
# level-independent by construction -- which is itself the argument for the donors chosen.
# =============================================================================================
# WHAT IS NOT TRUE ABOUT THESE NUMBERS
# =============================================================================================
#
# These three tables carried the Demon Hunter's per-talent caveats: which single talents were
# guessed, which lost half their effect to a generator limitation, which depended on a proc flag
# read out of an enum rather than observed. They are empty now, and emptying them would be a lie
# if it were not replaced by a bigger admission, so here it is.
#
# EVERY NUMBER IN ALL THREE TREES IS ASCENSION'S OWN VALUE, RE-RANKED. Not one of them has been
# measured on this realm, or on any realm running this core. They were balanced by another
# project against another server's stat curves, another item budget, and a classless progression
# where a player could combine them with anything. Ported into a class-based ladder with our
# player_class_stats, they are a STARTING POINT with a real pedigree -- which is far better than
# invented numbers, and is not the same thing as balanced.
#
# What that means concretely, and what to do about it:
#
#   * The per-talent caveat is now the DEFAULT rather than the exception, so listing exceptions
#     conveys nothing. A talent worth flagging is one that is wrong for a STRUCTURAL reason --
#     it needs an effect this core does not have, or a proc flag that never fires -- and those
#     live in the port plan's section 4 and in each tree's own comments, next to the talent.
#   * The first pass of real tuning has to come from play, and it should move dh_donors-style
#     override cells, not these files, so that the imported value stays visible next to the
#     value that replaced it.
#   * ~35 talents depend on a ProcTypeMask authored from SpellMgr.h rather than observed. Expect
#     a debugging pass where several passives simply never fire. That is the single most likely
#     class of silent failure in the whole port.

UNTUNED = ()

# What the one-rank-cell limit cost, and what the kit cost. Every entry is a place where the
# design in talents.md is NOT what this file emits.
DEGRADED = ()

# Decisions this file makes that a human should look at once the panel opens, and the two places
# where the reasoning is read rather than observed.
FLAGGED = ()


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

# 114 across three trees, and NOT equal per tree. The Demon Hunter's 22/22/22 was a symmetry
# this file used to assert; the Felsworn trees are 37/38/39 because that is what the source
# design is, and stock WotLK trees are themselves unequal (20-24). What actually has to hold is
# the tier gate -- a talent at tier N must be reachable with the points available by tier N --
# and that is asserted per tree in each fs_talents_* module against its own grid.
assert len(TALENTS) == 114, f"37 + 38 + 39 across three trees; got {len(TALENTS)}"
_EXPECTED_PER_TAB = {"demonology": 37, "slaying": 38, "felblood": 39}
for _tab in TAB_KEYS:
    _n = sum(1 for _t in TALENTS if _t.tab == _tab)
    assert _n == _EXPECTED_PER_TAB[_tab], (
        f"{_tab}: expected {_EXPECTED_PER_TAB[_tab]} talents, got {_n}")

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

# THE COST OF A FULL CLEAR, and why this is a RANGE now and not the Demon Hunter's flat 69.
#
# The bound that actually matters is talents.md 1.2 and it has two ends. A player has
# `level - 9` points, so 51 at the live cap of 60 and 71 at 80. A tree costing 71 or less can
# be emptied outright at 80, which makes whatever is left over free filler in a second tree; a
# tree costing more than 99 can never be finished at all.
#
# The Demon Hunter hit 69 exactly because it was authored to. Felsworn's trees are imported and
# come out at 66 / 68 / 68 -- inside the safe band but at its cheap end, so at the 80 cap a
# player finishes a tree with 3-5 points spare. Stock WotLK trees have the same property, and
# tightening it would mean padding two trees with talents nobody asked for, so it is accepted
# and recorded rather than engineered away. It is NOT a concern at the live cap of 60, where 51
# points buys about three-quarters of one tree.
_MIN_TREE_POINTS, _MAX_TREE_POINTS = 60, 99
for _tab in TAB_KEYS:
    assert _MIN_TREE_POINTS <= TREE_POINTS[_tab] <= _MAX_TREE_POINTS, (
        f"{_tab} full-clears for {TREE_POINTS[_tab]} points, outside "
        f"{_MIN_TREE_POINTS}-{_MAX_TREE_POINTS}. Below the floor the tree is trivially emptied "
        f"and the other two become filler; above the ceiling it can never be maxed at level 80 "
        f"(71 points). See talents.md 1.2.")
    for _tier in range(1, 11):
        _available = CUMULATIVE[_tab][_tier - 1]
        assert _available >= _tier * 5, (
            f"{_tab} tier {_tier} needs {_tier * 5} points spent above it and only "
            f"{_available} exist -- the tier is unreachable (Player.cpp:14361)")

# ---- the masks --------------------------------------------------------------------------------
# (uniqueness and single-bit-ness are asserted against the talents themselves, further down --
#  the old hand-maintained TALENT_BIT table it used to check no longer exists)

_ACTIVES = tuple(_t for _t in TALENTS if _t.flags == 1)
# What must hold, checked against the talents themselves rather than a parallel list -- a
# hand-maintained table of actives is exactly the thing that goes stale when a tree is retuned.
_ACTIVE_BITS = {}
for _t in TALENTS:
    _bit = _t.overrides.get("SpellClassMask_3", 0)
    if not _bit:
        continue
    assert not (_bit & (_bit - 1)), (
        f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}: SpellClassMask_3 {_bit:#010x} is not a "
        f"single bit")
    assert _bit not in _ACTIVE_BITS, (
        f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r} reuses bit {_bit:#010x}, already held by "
        f"{_ACTIVE_BITS[_bit]} -- a modifier naming it would silently affect BOTH spells")
    _ACTIVE_BITS[_bit] = f"{_t.tab} {_t.name!r}"
    _index = _bit.bit_length() - 1
    assert _index in TALENT_BIT_RANGES[_t.tab], (
        f"{_t.tab} ({_t.tier},{_t.col}) {_t.name!r}: bit {_index} is outside this tree's "
        f"range {TALENT_BIT_RANGES[_t.tab]}, so it can collide with another tree")

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
# Derived from the bits the trees actually assigned, not from a parallel table -- see
# _ACTIVE_BITS above. That is what makes "names a bit no talent-granted spell owns" a real
# check rather than a check against a second copy of the same mistake.
_TALENT_MASK = 0
for _v in _ACTIVE_BITS:
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
assert RANK_ROWS == sum(TREE_POINTS.values()), (
    f"one Spell.dbc record per talent RANK: {sum(TREE_POINTS.values())} expected, got {RANK_ROWS}")

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
