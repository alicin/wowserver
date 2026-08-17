#!/usr/bin/env python3
"""FELBLOOD -- the Felsworn caster tree, as data. Port plan section 3.3, row by row.

Ascension's tab 38 "Felblood" (39 nodes) becomes `TalentTab.dbc` 414 (plan 6.3). Every spell id
below was looked up in `build/tools/ascension/out/felsworn-family20.json` and every core line
number in the pinned checkout at `.work/ac-src`. Nothing here is recalled.

THE PLAN'S OWN TALENT COUNT IS WRONG AND THE TABLE IS RIGHT
-----------------------------------------------------------
Plan 3.3's heading says "28 talents, 68 points". Its grid has **39** cells summing to **68**
points, and `demon-hunter.json` has exactly **39** tab-38 nodes -- so the point total is the
number that was computed and the talent count is the one that was typed. selftest() asserts 68
points and 39 talents; the per-tier running totals reproduce the plan's own gate list
15/24/32/39/46/50/56/60/64/67 exactly, which is the check that the table was transcribed whole.

WHAT `source` IS, AND WHY A TALENT NEEDS IT
-------------------------------------------
`dh_spec.Ability` gained `source` (plan 6.1, dh_spec.py:852-869): the id of an Ascension record
whose whole 234 cells are transplanted over the cloned donor, because "a donor is only ever a
shape that RESEMBLES the ability... while an imported record IS the ability". A Felblood talent
is in exactly that position -- `806103` Wrath of Sargeras is not a spell we are approximating,
it is the spell -- so `Talent` needs the same field, and this file uses it.

`source_ranks` and `rank_levels` do NOT come with it. An Ability's ranks are Ascension's own
ladder re-levelled; a TALENT's ranks are 1-5 WotLK ranks of ONE imported record with `rank_cell`
rewritten per rank, and Ascension's own rank count (2, where it has one at all) does not match.
Where Ascension ships a sibling rank its id and its numbers are named in the talent's comment
and used to set the ceiling -- read, not imported.

FIELDS dh_talents.Talent MUST GAIN BEFORE THIS FILE CAN BE MERGED
-----------------------------------------------------------------
    rank_cell_2: str = ""       plan 6.3 + 6.4.3 -- the second per-rank cell. Fourteen Felsworn
    rank_values_2: tuple = ()   talents scale two numbers; `dhspells.py:878` writes exactly one.
    proc_flags: int = 0         plan 6.3 -- `ProcTypeMask`, authored, so SpellMgr synthesises a
                                proc entry from the DBC row alone (plan 4.C0).
    source: int = 0             the argument above; plan 6.1's field, borrowed.

Until they land, the shim below subclasses the frozen dataclass so this file still imports and
selftest() still runs. The shim deletes itself the moment `dh_talents.Talent` has the fields --
it is an `if`, not a fork.

Two more names exist at module scope for the same reason `dh_talents` has TALENT_BIT and
SCRIPT_NAMES: `Talent` has nowhere to put a family bit or a script name.
    FELBLOOD_TALENT_BIT       word-3 bits for this tree's six granted buttons
    SCRIPT_NAMES_FELBLOOD     the DB-bound scripts of plan section 4

WHAT `ALWAYS` ALREADY DOES FOR AN IMPORTED RECORD, AND THE ONE THING IT DOES NOT
--------------------------------------------------------------------------------
`dh_talents.ALWAYS` was written for donor hygiene and turns out to close exactly the four cells
an Ascension import must not keep -- `SpellClassMask_1/2/3` (Ruin's own mask is `[0,2,0]`, a
family-20 word that would be a family-16 word here), `ShapeshiftMask` (Ascension form 56),
`PowerType`/`ManaCost`/`ManaCostPct` and the equipment gate. It is merged UNDER each talent's
own cells, so the six granted actives set `ManaCost` back and the two form-gated passives set
`ShapeshiftMask` back.

The cell it does NOT close is the PER-EFFECT one, and that cell is a trap: the dump exports only
word A of each effect's three-word mask (`class_mask_a`). Compare `801895` Ruin, whose spell mask
is `[0, 2, 0]` -- word 2 -- which no exported `class_mask_a` can name; and `524950` Black Magic
e1 carries `class_mask_a = 2`, which in family 20 resolves to Whispers of the Pit and in family
16 would resolve to whatever `dh_donors` puts on bit 1. Every talent whose source has a non-zero
`class_mask_a` therefore zeroes `EffectSpellClassMaskA_n` itself. There are six: `524950`,
`560639`, `300489`, `804219`, `803905` and (not imported) `525079`.

For this to hold the generator must import in this order:
    1. memcpy the donor      2. transplant `source`      3. TALENT_BASE      4. ALWAYS+overrides
A `source` pass that ran after step 4 would undo every fix below.

WHAT THIS FILE DELIBERATELY DOES NOT CARRY
-------------------------------------------
  * `ID`, `Name_Lang_enUS`, `NameSubtext_Lang_enUS`, icons -- the generator's, same as
    `dh_talents.py`.
  * `EffectTriggerSpell_*`. Twenty of these talents proc a second record; the id is the
    generator's, so it belongs in `TRIGGERS` (plan 6.3 grows it to ~40) and not here.
  * `EffectSpellClassMaskA_*` NAMING A BASELINE ABILITY. Word 1 is `dh_donors.BIT`'s and plan
    6.2 has not rewritten `dh_donors` yet; writing a provisional bit here would be a second
    source of truth for an allocation this file does not own. Each affected talent names the
    ability(ies) in its comment instead. **This is a hard dependency, not cosmetic**: a proc
    talent with a zero effect mask does not proc off "nothing in particular", it procs off
    EVERYTHING matching ProcFlags, because `SpellMgr.cpp:2232` only copies `SpellFamilyName`
    when the generated entry's mask is non-zero. Ten talents below are unshippable until plan
    6.2 lands. Word 3 IS written, because this tree's own buttons are this file's to allocate.
  * `spell_proc` rows. Plan 4.C0: author `ProcTypeMask` and the core generates the entry from
    the record, INCLUDING the chance (`SpellMgr.cpp:2283` is
    `procEntry.Chance = spellInfo->ProcChance`). A row is needed only for a crit-only `HitMask`;
    the seven talents that need one say so.

THE CalcValue CONVENTION, WHICH DECIDES EVERY NUMBER IN `rank_values`
---------------------------------------------------------------------
Unchanged from `dh_talents.py`: `SpellInfo::CalcValue` adds 1 when `EffectDieSides == 1`, so
`rank_values` are written one BELOW the number that lands. Every Ascension record imported below
carries `die_sides = 1` on the cell the ranks fill -- read out of the dump, and the landing
values are in the comment on every `rank_values` line. `ProcChance` is NOT a base-points cell and
gets no +1; the two talents ranked on it say so.

EVERY NUMBER HERE IS ASCENSION'S OWN, RE-RANKED, AND NOT MEASURED
------------------------------------------------------------------
Plan 6.3 requires this caveat carried forward verbatim, so: nothing below has been observed in
game or in a client. The rule applied throughout is **Ascension's ceiling is our top rank**, with
even steps beneath it, and the source cell that supplies the ceiling is quoted at each talent.
The three places that ceiling was NOT kept are called out in the talent's own comment and say
what replaced it and why (Man'ari Teachings, Illidari Smiter, Illidari Magi). Nothing is invented
silently.
"""

import os
import sys
from dataclasses import dataclass, fields

HERE = os.path.dirname(os.path.abspath(__file__))                   # .work/felsworn
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "build", "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "build", "modules", "mod-demon-hunter", "tools"))

from acdbc import dbc_tables                                        # noqa: E402
import dh_talents                                                   # noqa: E402


# =============================================================================================
# THE DATACLASS, PLUS THE SHIM THAT DELETES ITSELF
# =============================================================================================
#
# See the header. The four fields are plan 6.3's three plus `source`. Subclassing rather than
# editing dh_talents.py keeps THAT file the property of the whole port instead of this tree.
if {"rank_cell_2", "rank_values_2", "proc_flags", "source"} <= {
        _f.name for _f in fields(dh_talents.Talent)}:
    Talent = dh_talents.Talent
else:
    @dataclass(frozen=True)
    class Talent(dh_talents.Talent):
        rank_cell_2: str = ""
        rank_values_2: tuple = ()
        proc_flags: int = 0
        source: int = 0


# =============================================================================================
# CONSTANTS
# =============================================================================================

# `Talent.tab` is the lowercased tab name, which is the key `dhspells.build_talents` resolves
# against `dh_spec.TALENT_TABS`. Plan 6.3 renames the three tabs Demonology/Slaying/Felblood, so
# this string is only resolvable after that rename -- selftest() checks the rename has happened
# rather than asserting against today's ("havoc", "vengeance", "illidari").
TAB = "felblood"

# Plan 6.3 renames `METAMORPHOSIS_STANCE` to `INNER_DEMON_STANCE`; the VALUE is unchanged, which
# is why this is an alias and not a literal. `1 << 22` is form 23, and
# `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1449-1456) casts any talent spell
# that is PASSIVE|DO_NOT_DISPLAY and whose `Stances` mask includes the new form, with no id
# switch anywhere on the path. Two Felblood passives are "while Inner Demon is active" and are
# therefore free of C++ entirely (plan 3.3's own note on 560637).
INNER_DEMON_STANCE = dh_talents.METAMORPHOSIS_STANCE                # 0x00400000

# `SPELL_ATTR0_NOT_SHAPESHIFTED`. THE TRAP ON RUIN. Form 23 copies the warlock row's flags, which
# lack `SHAPESHIFT_FLAG_STANCE`, so a Felsworn in Inner Demon "acts as shifted" and
# `SpellInfo::CheckShapeshift` (SpellInfo.cpp:1474-1476) returns SPELL_FAILED_NOT_SHAPESHIFT for
# anything carrying this bit. Ascension ships `801895` with `attributes[0] = 0x10000`, i.e. this
# bit and nothing else, so Ruin would grey out in the one form the tree is built around.
NOT_SHAPESHIFTED = dh_talents.NOT_SHAPESHIFTED                      # 0x00010000

# ProcTypeMask bits, read out of SpellMgr.h rather than recalled. UNVERIFIED in the sense plan 7.4
# names: which flag a given Felsworn ability actually raises depends on its `DefenseType`, which
# is the DONOR's cell and lives in dh_donors, and none of it has been observed.
PROC_DONE_MELEE_ABILITY = 0x00000010    # DONE_SPELL_MELEE_DMG_CLASS   (SpellMgr.h:116)
PROC_DONE_POSITIVE_CAST = 0x00000400    # DONE_SPELL_NONE_DMG_CLASS_POS(SpellMgr.h:126)
PROC_DONE_MAGIC_ABILITY = 0x00010000    # DONE_SPELL_MAGIC_DMG_CLASS_NEG (SpellMgr.h:134)
PROC_DONE_PERIODIC = 0x00040000         # DONE_PERIODIC                (SpellMgr.h:137)

# =============================================================================================
# THE SIX GRANTED BUTTONS -- SpellClassMask_3
# =============================================================================================
#
# `Talent.dbc Flags = 1` grants a spellbook button, and a granted spell needs its own family bit
# or no later talent can name it (`dh_talents.TALENT_BIT`, same argument, same column). Plan 6.3
# lists twenty granted actives across the three trees; six of them are Felblood's and are the
# only six this file may allocate.
#
# THE BLOCK RULE, so three files written apart cannot collide: eight bits per tree, in tab order.
# Demonology takes 0-7 (it has exactly eight granted actives), Slaying 8-15 (six), Felblood
# 16-23 (six). `dh_talents.TALENT_BIT` absorbs all three blocks and stays append-only; a bit that
# moves silently repoints whatever was keyed on it.
FELBLOOD_TALENT_BIT = {
    "ruin":             0x00010000,     # (1,0)
    "bane_of_chaos":    0x00020000,     # (2,0)
    "felwrath":         0x00040000,     # (3,0)
    "felbreak":         0x00080000,     # (5,0)
    "infernal":         0x00100000,     # (7,0)
    "sargeras_embrace": 0x00200000,     # (10,1)
}


# =============================================================================================
# THE TREE -- 39 talents, 68 points
# =============================================================================================
#
# row | col 0                  | col 1                  | col 2                | col 3
# ----+------------------------+------------------------+----------------------+----------------
#  0  | Wrath of Sargeras    5 | Black Magic          5 | Felfire Adept      5 |
#  1  | Ruin                1* | Gul'dan's Prodigy    3 | Illidari Smiter    2 | Nether Spirit 3
#  2  | Bane of Chaos       1* | Curse of Argus       3 | Cursed Flames      2 | Hidden Power  2
#  3  | Felwrath            1* | Oppressive Ruin    1^  | Fel Cannon         2 | Man'ari Teach 3
#  4  | Doomsayer            2 | Dark Magician        1 | Illidari Magi      2 | Unphased      2
#  5  | Felbreak            1* | Fel Apprentice       1 | Felshock           1 | Archimonde's  1
#  6  | Herald of the Legion 1 | Infernal Doom        1 | Shadow Magi        2 | Withering     2
#  7  | Infernal            1* | Felforged            1 | Chaotic Intuition  1 | Fel Flamecast 1
#  8  | Infernal Summoner    1 | Infernal Ruin        1 | Malice of Gul'dan  1 | Fel Infusion  1
#  9  | Sculptor of Doom     1 | The True Blessing    1 | Fury of Archimonde 1 |
# 10  |                        | Sargeras Embrace    1* |                      |
#
# cumulative points at the end of each row -- these ARE plan 3.3's gate list, recomputed from
# `ranks` by selftest() so a rank change cannot leave a stale comment behind:
#   R0 15 | R1 24 | R2 32 | R3 39 | R4 46 | R5 50 | R6 56 | R7 60 | R8 64 | R9 67 | R10 68
#   needs    5   |   10   |   15  |   20  |   25  |   30  |   35  |   40  |   45  |    50

TALENTS_FELBLOOD = (

    # =========================================================================================
    # ROW 0
    # =========================================================================================

    # -- 0/0 -- Wrath of Sargeras ..................... source 806103 (Ascension R1), donor 13712
    #
    # Two effects, both wanted: aura 79 MOD_DAMAGE_PERCENT_DONE at `misc 126` (every school but
    # Physical) and aura 55 MOD_SPELL_HIT_CHANCE. Ascension ships two ranks -- 806103 is bp 2/bp 1
    # (3% and 2%) and 807902 is bp 5/bp 3 (6% and 4%) -- so 6% and 4% are the ceilings.
    # The damage ladder steps evenly to 6. THE HIT LADDER CANNOT: 4 over five ranks is 0.8 a
    # rank, so rank 5 buys damage only rather than this file inventing a fifth point of spell hit
    # Ascension never wrote. Both effects carry `die_sides 1`.
    Talent(TAB, 0, 0, 5, "Wrath of Sargeras", donor=13712, source=806103,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 2, 3, 4, 5),         # DieSides 1 -> lands 2/3/4/5/6 % magic damage
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(0, 1, 2, 3, 3),       # DieSides 1 -> lands 1/2/3/4/4 % spell hit
           overrides={
               "Description_Lang_enUS":
                   "Increases your magic damage done by $s1% and your spell hit chance by $s2%.",
           },
           note="806103 -- aura 79 misc 126 + aura 55; 807902 is Ascension's rank 2 and supplies "
                "the ceilings (6% / 4%), read but not imported"),

    # -- 0/1 -- Black Magic ........................... source 524950 (Ascension R1), donor 13712
    #
    # Two aura-108 spellmods that are ONE tooltip line in Ascension: `misc 0` SPELLMOD_DAMAGE
    # (SpellDefines.h:76) for Ruin's direct hit and `misc 22` SPELLMOD_DOT (:98) for Bane of
    # Chaos's ticks -- which is why they take one ladder each rather than one frozen at rank 1.
    # 525079 is Ascension's rank 2 at bp 19 on both, i.e. 20%, and that is the ceiling.
    # `class_mask_a = 2` on e1 is the exported half of an Ascension mask (it resolves to Whispers
    # of the Pit in family 20) and is closed here; the real restriction is word 3, below.
    Talent(TAB, 0, 1, 5, "Black Magic", donor=13712, source=524950,
           rank_cell="EffectBasePoints_1",
           rank_values=(3, 7, 11, 15, 19),      # DieSides 1 -> lands 4/8/12/16/20 % on Ruin
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(3, 7, 11, 15, 19),    # the same ladder on Bane of Chaos's DoT
           overrides={
               "EffectSpellClassMaskA_2": 0,    # the dump's class_mask_a, a family-20 fragment
               "EffectSpellClassMaskC_1": FELBLOOD_TALENT_BIT["ruin"],
               "EffectSpellClassMaskC_2": FELBLOOD_TALENT_BIT["bane_of_chaos"],
               "Description_Lang_enUS":
                   "Increases the damage of your Ruin by $s1% and the damage of your Bane of "
                   "Chaos by $s2%.",
           },
           note="524950 -- two aura 108s, SPELLMOD_DAMAGE and SPELLMOD_DOT; both targets are "
                "granted actives in this tree, so the mask is word 3 and knowable here"),

    # -- 0/2 -- Felfire Adept ......................... source 560836 (Ascension R1), donor 14138
    #
    # One effect, aura 107 SPELLMOD_CRITICAL_CHANCE (`misc 7`), flat -- it adds crit chance to one
    # ability rather than to the character. 561345 is rank 2 at bp 19, so 20% is the ceiling, and
    # 20% on one ability at five points is inside stock's own range (13733 Puncturing Wounds is
    # +30% on Backstab at three).
    # MASK HOLE: Sargeron Smite is a BASELINE ability, so its bit is `dh_donors.BIT` word 1 and
    # plan 6.2 has not allocated it. Unmasked, this is +20% crit to every Felsworn spell.
    Talent(TAB, 0, 2, 5, "Felfire Adept", donor=14138, source=560836,
           rank_cell="EffectBasePoints_1",
           rank_values=(3, 7, 11, 15, 19),      # DieSides 1 -> lands 4/8/12/16/20 %
           overrides={
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Sargeron Smite by $s1%.",
           },
           note="560836 -- aura 107 misc 7; needs EffectSpellClassMaskA_1 = BIT['sargeron_smite'] "
                "once plan 6.2 rewrites dh_donors"),

    # =========================================================================================
    # ROW 1
    # =========================================================================================

    # -- 1/0 -- Ruin ...................................... source 801895, donor 686 Shadow Bolt
    #
    # The tree's first button: a 30-Energy, 2-Felfury Shadowflame nuke. Donor 686 is chosen for
    # the cells the dump does not carry -- `DmgClass` magic, PreventionType, InterruptFlags and
    # the missile visual -- and has ONE effect against the source's two, which is the safe
    # direction: a donor effect the import does not overwrite is a live effect nobody chose.
    # `attributes[0] = 0x10000` is SPELL_ATTR0_NOT_SHAPESHIFTED and nothing else; see the
    # constant. Rewritten to IS_ABILITY, which is what the button actually is.
    # FLAGGED: Ruin's own `duration_index` is 0, so its e1 (aura 301 SCHOOL_HEAL_ABSORB) has no
    # duration at all until Oppressive Ruin at (3,1) adds a flat +8000 ms -- which is exactly
    # what 561201's tooltip says ("for $/1000;s1 sec"). Left at Ascension's 0 rather than
    # invented, but an aura whose CalcMaxDuration lands on 0 is not permanent, it is one the next
    # `Aura::Update` expires. First thing to watch when the absorb is tested.
    Talent(TAB, 1, 0, 1, "Ruin", donor=686, source=801895, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["ruin"],
               "Attributes": 0x10,              # IS_ABILITY, from Ascension's bare 0x10000
               "ManaCost": 30,                  # Energy; ALWAYS zeroes the imported cost
               "StartRecoveryCategory": 133,    # the house GCD; Ascension's own gcd_ms is 1000
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Consumes 2 Felfury. Brings doom upon an enemy, dealing $s1 Shadowflame "
                   "damage that pierces absorption effects.",
           },
           note="801895 -- eff 2 SCHOOL_DAMAGE + aura 301 SCHOOL_HEAL_ABSORB; the Felfury debit "
                "is plan 4.C1's script, not a cell"),

    # -- 1/1 -- Gul'dan's Prodigy ......................... source 704378, donor 13712
    #
    # Three effects, one dead: e0 is aura 137 MOD_TOTAL_STAT_PERCENTAGE at `misc 3` with
    # `base_points -1`, i.e. amount ZERO after CalcValue, and it is not in the tooltip either.
    # Deleted rather than carried. The two that matter are aura 108 at `misc 14` SPELLMOD_COST
    # (SpellDefines.h:90) and `misc 10` SPELLMOD_CASTING_TIME (:86), both at bp -16 -> -15%, and
    # both are one tooltip line ("Reduces Energy cost and cast time"), so both take a ladder.
    # -15% is Ascension's ceiling and rank 3 lands on it.
    Talent(TAB, 1, 1, 3, "Gul'dan's Prodigy", donor=13712, source=704378,
           rank_cell="EffectBasePoints_2",
           rank_values=(-6, -11, -16),          # DieSides 1 -> lands -5/-10/-15 % Energy cost
           rank_cell_2="EffectBasePoints_3",
           rank_values_2=(-6, -11, -16),        # the same ladder on cast time
           overrides={
               "Effect_1": 0,                   # aura 137 misc 3 at amount 0 -- a dead cell
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "Description_Lang_enUS":
                   "Reduces the Energy cost and the casting time of your Fel Fireball by $s2%.",
           },
           note="704378 -- e1/e2 are aura 108 SPELLMOD_COST and SPELLMOD_CASTING_TIME; needs "
                "BIT['fel_fireball'] on both once plan 6.2 lands"),

    # -- 1/2 -- Illidari Smiter ........................... source 520246, donor 14138
    #
    # One aura 42 PROC_TRIGGER_SPELL into `800058` Felfury: a Fel Fireball crit generates a stack.
    # THERE IS NO SECOND NUMBER ON THIS RECORD. `base_points -1` is amount zero (the stack is the
    # trigger's, not this effect's), so a second rank has to scale the only other cell the record
    # has, which is ProcChance -- and that cell is not decoration: `SpellMgr.cpp:2283` copies
    # `spellInfo->ProcChance` straight into the generated proc entry, so 50/100 costs no SQL.
    # NOT ASCENSION'S: its node is a single 100% chance. The 50% first rank is this file's, and it
    # is the only shape a two-point talent can take here short of cutting the second point.
    # ProcChance is not a base-points cell, so no +1: 50 means 50.
    Talent(TAB, 1, 2, 2, "Illidari Smiter", donor=14138, source=520246,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           rank_cell="ProcChance",
           rank_values=(50, 100),               # per cent, literal -- CalcValue is not involved
           overrides={
               "Description_Lang_enUS":
                   "Your Fel Fireball critical strikes have a $h% chance to generate 1 Felfury.",
           },
           note="520246 -- aura 42 -> 800058; crit-only needs the one spell_proc row plan 4.C0 "
                "allows (HitMask), and BIT['fel_fireball'] on the effect"),

    # -- 1/3 -- Nether Spirit ............................. source 300477, donor 14138
    #
    # aura 220 MOD_RATING_FROM_STAT with `misc 1024` (CR_CRIT_SPELL, bit 10) and `misc_b 4`
    # (Spirit): spell crit rating from Spirit, which is the whole reason this tree wants Spirit
    # gear at all. Ascension's single node is bp 19 -> 20%, the ceiling; three ranks step to it.
    # Only four stock rows use this aura at all (30482/43045/43046 Molten Armor, 49410 Forceful
    # Deflection), so there is no stock curve to copy -- these thirds are arithmetic.
    Talent(TAB, 1, 3, 3, "Nether Spirit", donor=14138, source=300477,
           rank_cell="EffectBasePoints_1",
           rank_values=(6, 13, 19),             # DieSides 1 -> lands 7/14/20 % of Spirit
           overrides={
               "Description_Lang_enUS":
                   "Increases your spell critical strike chance by $s1% of your Spirit.",
           },
           note="300477 -- aura 220 misc 1024 / miscB 4; no mask, because a rating conversion is "
                "not a spellmod and never reads one"),

    # =========================================================================================
    # ROW 2
    # =========================================================================================

    # -- 2/0 -- Bane of Chaos ............................. source 704368, donor 172 Corruption
    #
    # The tree's DoT button, 40 Energy, and a generator rather than a spender (+1 Felfury). Donor
    # 172 is the canonical family-5 damage-over-time shape and has two effects against the
    # source's two.
    # e1 (aura 23 PERIODIC_TRIGGER_SPELL -> `803717`, 6 s) is the Inner Demon rider and stays; it
    # needs a TRIGGERS row, which is the generator's.
    # "Can only have 1 Bane active on a target at a time" has NO 3.3.5a data path -- the five
    # Banes are separate spell ids with separate aura slots -- so the clause is dropped from the
    # tooltip rather than shipped as a lie.
    Talent(TAB, 2, 0, 1, "Bane of Chaos", donor=172, source=704368, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["bane_of_chaos"],
               "ManaCost": 40,
               "StartRecoveryCategory": 133,
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Unleashes fel magic on an enemy, dealing $o1 Chaos "
                   "damage over $d.",
           },
           note="704368 -- aura 3 PERIODIC_DAMAGE at 3 s + aura 23 -> 803717; duration_index 85"),

    # -- 2/1 -- Curse of Argus ............................ source 704370, donor 14138
    #
    # Ascension's record is a bare aura 42 into `707511`, and `707511` is where the number lives:
    # aura 271 MOD_DAMAGE_PERCENT_TAKEN at bp 0 / die 1, i.e. +1% a stack. A talent whose ranks
    # all point at one trigger row would buy nothing, so this uses THE RANK TRICK -- aura 231
    # PROC_TRIGGER_SPELL_WITH_VALUE passes its own amount into the triggered spell as basepoints0
    # (`dh_talents.py` TRIGGERS block), so three ranks still need one trigger row.
    # ONLY RANK 1 IS ASCENSION'S. Its node is 1% a stack; 2% and 3% are this file's linear
    # extension, because a three-rank talent needs three numbers and the dump has one.
    Talent(TAB, 2, 1, 3, "Curse of Argus", donor=14138, source=704370,
           proc_flags=PROC_DONE_PERIODIC,
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 1, 2),               # DieSides 1 -> the aura's amount is 1/2/3 %,
                                                # and that amount IS what 707511 applies
           overrides={
               "EffectAura_1": 231,             # from 42, so the rank value reaches the trigger
               "EffectDieSides_1": 1,           # the dump has die 0 here; the +1 convention needs
                                                # it, and the TRIGGER row zeroes its own die
               "Description_Lang_enUS":
                   "Each time your Bane of Chaos deals damage, it increases the damage the "
                   "target takes from it by $s1%, stacking.",
           },
           note="704370 -> 707511 (aura 271, bp 0 die 1 = 1%); ranked through aura 231 rather "
                "than through three trigger rows"),

    # -- 2/2 -- Cursed Flames ............................. source 300478, donor 13712
    #
    # Two aura 42s: `300486` (aura 107 misc 7, bp 19 -> +20% crit on the next Fel Fireball) and
    # `301290` "Cursed", the debuff half. The scaling number is on 300486, so e0 takes the same
    # aura-231 rank trick as Curse of Argus and e1 stays a plain proc.
    # 20% is Ascension's ceiling and rank 2 lands on it.
    Talent(TAB, 2, 2, 2, "Cursed Flames", donor=13712, source=300478,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19),                 # DieSides 1 -> the aura's amount is 10/20 %
           overrides={
               "EffectAura_1": 231,             # from 42
               "EffectDieSides_1": 1,           # the dump has die 0; see Curse of Argus
               "Description_Lang_enUS":
                   "Your Fel Fireball critical strikes increase the critical strike chance of "
                   "your next Fel Fireball by $s1%.",
           },
           note="300478 -> 300486 + 301290; crit-only, so one spell_proc row for the HitMask, "
                "and BIT['fel_fireball'] on both effects once plan 6.2 lands"),

    # -- 2/3 -- Hidden Power .............................. source 802108, donor 13712
    #
    # Two aura 174 MOD_SPELL_DAMAGE_OF_STAT_PERCENT effects, `misc 126` (every school but
    # Physical) with `misc_b 3` Intellect and `misc_b 4` Spirit, both bp 14 -> 15%.
    # UNTUNED AND HOT, said plainly: stock's own five-rank version of this cell is 31584-31588
    # Mind Mastery at 3/6/9/12/15 for FIVE points and ONE stat. Ascension prices 15% of two stats
    # at one node. The ceiling is kept because it is Ascension's, and this comment is the flag.
    # The tooltip's second sentence ("Inner Demon increases it further") lives in `801208`, a
    # record this tree does not own.
    Talent(TAB, 2, 3, 2, "Hidden Power", donor=13712, source=802108,
           rank_cell="EffectBasePoints_1",
           rank_values=(6, 14),                 # DieSides 1 -> lands 7/15 % of Intellect
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(6, 14),               # the same ladder on Spirit
           overrides={
               "Description_Lang_enUS":
                   "Increases your spell power by $s1% of your Intellect and $s2% of your Spirit.",
           },
           note="802108 -- aura 174 twice, miscB 3 and 4; the hottest pair of cells in the tree "
                "and Ascension's own"),

    # =========================================================================================
    # ROW 3
    # =========================================================================================

    # -- 3/0 -- Felwrath .................................. source 520236, donor 27285 Seed of
    #                                                       Corruption
    # The AoE spender: 30 Energy, 2 Felfury, damage at `target_a 53` with radius index 14 (8 yd).
    # Donor 27285 is the stock "instant area damage centred on the victim" shape and carries the
    # DmgClass and PreventionType the dump has no column for.
    # TWO OF THREE EFFECTS GO. e1 is aura 4 DUMMY with a 2 s period and no trigger -- Ascension
    # engine plumbing for the 5-target rider, which lives in `520832`/`803479` and is not
    # reachable as data. e2 is aura 271 at `base_points -1`, i.e. amount ZERO. Neither implements
    # anything here, and a DUMMY with a period is a tick that calls nothing every 2 seconds.
    Talent(TAB, 3, 0, 1, "Felwrath", donor=27285, source=520236, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["felwrath"],
               "ManaCost": 30,
               "StartRecoveryCategory": 133,
               "StartRecoveryTime": 1000,
               "Effect_2": 0,                   # aura 4 DUMMY, period 2000, trigger 0
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectAuraPeriod_2": 0,
               "EffectRadiusIndex_2": 0,
               "ImplicitTargetA_2": 0,
               "ImplicitTargetB_2": 0,
               "Effect_3": 0,                   # aura 271 at amount 0
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectRadiusIndex_3": 0,
               "ImplicitTargetA_3": 0,
               "ImplicitTargetB_3": 0,
               "Description_Lang_enUS":
                   "Consumes 2 Felfury. Blasts an enemy and everything near them for $s1 "
                   "Shadowflame damage.",
           },
           note="520236 -- eff 2 SCHOOL_DAMAGE at target 53, radius index 14; the Inner Demon "
                "stacking rider is dropped with e1/e2"),

    # -- 3/1 -- Oppressive Ruin ........................... source 561201, donor 13732
    #
    # One effect, aura 107 SPELLMOD_DURATION (`misc 1`) at bp 7999 -> 8000 ms, and it is what
    # gives Ruin's heal absorb a duration at all (see 1/0). One rank, so the value is an ordinary
    # override rather than a ladder, and it is Ascension's own.
    # The arrow is plan 3.3's only one. PrereqRank 0 is the 0-based floor and Ruin has one rank.
    Talent(TAB, 3, 1, 1, "Oppressive Ruin", donor=13732, source=561201, prereq=(1, 0, 0),
           overrides={
               "EffectBasePoints_1": 7999,      # DieSides 1 -> 8000 ms
               "EffectSpellClassMaskC_1": FELBLOOD_TALENT_BIT["ruin"],
               "Description_Lang_enUS":
                   "Damage dealt by your Ruin absorbs the next healing received by the target "
                   "for $/1000;s1 sec.",
           },
           note="561201 -- aura 107 misc 1; units are milliseconds, same as every cooldown mod"),

    # -- 3/2 -- Fel Cannon ................................ source 802180, donor 14138
    #
    # aura 112 OVERRIDE_CLASS_SCRIPTS at `misc 20000 / misc_b 28`: +15% crit chance on Fel
    # Fireball and Ruin against a victim above 75% health. Plan 4.C7 -- `misc 20000` has no case
    # in `AuraEffect::HandleOverrideClassScriptAuraEffect`'s switch, so the aura is inert on its
    # own (inert, NOT a crash) and the condition is read by a `UnitScript` off
    # `OnBeforeRollMeleeOutcomeAgainst`, whose `crit_chance` is a non-const out-param.
    # NO `spell_script_names` ROW: plan 6.5 -- UnitScript is registered in code, only
    # SpellScript/AuraScript are database-bound (ObjectMgr.cpp:6345).
    # 15% is Ascension's ceiling and rank 2 lands on it.
    Talent(TAB, 3, 2, 2, "Fel Cannon", donor=14138, source=802180,
           rank_cell="EffectBasePoints_1",
           rank_values=(6, 14),                 # DieSides 1 -> lands 7/15 %
           overrides={
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Fel Fireball and Ruin by $s1% "
                   "against enemies above 75% health.",
           },
           note="802180 -- aura 112 misc 20000/28; the shared >75% predicate is "
                "victim->HealthAbovePct(75), the same helper Annihilan Strike wants"),

    # -- 3/3 -- Man'ari Teachings ......................... source 705150, donor 14138
    #
    # aura 163 MOD_CRIT_DAMAGE_BONUS, `misc 126`. THE ONE CEILING IN THIS TREE THAT IS NOT KEPT,
    # and the reason is arithmetic rather than taste: `Unit::SpellCriticalDamageBonus`
    # (Unit.cpp:9415-9428) sets `crit_bonus = damage * 1.5` and only THEN does
    # `AddPct(crit_bonus, crit_mod)`, so this aura scales the whole crit, not the extra half.
    # Ascension's bp 99 is therefore +100% -> a spell crit for 3x base. Stock's largest is 58670
    # Prey on the Weak at 20%, and stock's only three-rank ladder on this aura is 33859/33866/
    # 33867 Predatory Instincts at 3/7/10. That curve is copied exactly.
    # RETUNED, not measured, and the number it replaces is named above.
    Talent(TAB, 3, 3, 3, "Man'ari Teachings", donor=14138, source=705150,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 6, 9),               # DieSides 1 -> lands 3/7/10 %
           overrides={
               "Description_Lang_enUS": "Increases your critical strike damage by $s1%.",
           },
           note="705150 -- aura 163 misc 126; Ascension's own value is 100% and is not shipped"),

    # =========================================================================================
    # ROW 4
    # =========================================================================================

    # -- 4/0 -- Doomsayer ................................. source 520833, donor 13712
    #
    # Two halves that need two different mechanisms. e0 is aura 42 -> `800058` Felfury (a
    # Sargeron Smite crit refunds a stack) and is data plus the crit-only spell_proc row. e1 is
    # aura 112 at `misc 20007 / misc_b 23`, +25% Sargeron Smite damage above 75% health, and is
    # plan 4.C7's `UnitScript::ModifySpellDamageTaken` -- so no script row here either.
    # The ladder is on the damage half, which is the number a second point should buy; the refund
    # is a yes/no and stays at rank 1's behaviour. 25% is Ascension's ceiling.
    Talent(TAB, 4, 0, 2, "Doomsayer", donor=13712, source=520833,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           rank_cell="EffectBasePoints_2",
           rank_values=(11, 24),                # DieSides 1 -> lands 12/25 %
           overrides={
               "Description_Lang_enUS":
                   "Your Sargeron Smite critical strikes refund 1 Felfury, and your Sargeron "
                   "Smite deals $s2% increased damage to enemies above 75% health.",
           },
           note="520833 -- aura 42 -> 800058 plus aura 112 misc 20007/23; e0 needs "
                "BIT['sargeron_smite'] and a HitMask row"),

    # -- 4/1 -- Dark Magician ............................. source 560637, donor 14138
    #
    # aura 42 -> `521243` "Energize +20 energy" (eff 30 ENERGIZE, bp 19 / misc 3), gated on Inner
    # Demon. THE GATE IS FREE: Ascension's `attributes[0] = 448` is already
    # PASSIVE|DO_NOT_DISPLAY|DO_NOT_LOG, which is precisely what
    # `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1449-1456) requires, so a
    # `ShapeshiftMask` naming form 23 is the whole implementation. Plan 3.3 calls this out by
    # name. `ShapeshiftMask` is set here BECAUSE ALWAYS zeroes it -- a talent's own cell wins.
    # One rank, so no ladder; the 20 Energy is `521243`'s and not this record's.
    # UNVERIFIED (plan 7.4): Ruin and Felwrath are magic, Sunder is the channelled cone spender,
    # so both damage-class bits are set. Which one a channel actually raises was read, not seen.
    Talent(TAB, 4, 1, 1, "Dark Magician", donor=14138, source=560637,
           proc_flags=PROC_DONE_MAGIC_ABILITY | PROC_DONE_MELEE_ABILITY,
           overrides={
               "ShapeshiftMask": INNER_DEMON_STANCE,        # form 23, against ALWAYS
               "Description_Lang_enUS":
                   "While Inner Demon is active, your Ruin, Sunder and Felwrath refund 20 Energy.",
           },
           note="560637 -- aura 42 -> 521243; needs the ruin/felwrath word-3 bits plus "
                "BIT['sunder'] on the effect once plan 6.2 lands"),

    # -- 4/2 -- Illidari Magi ............................. source 560639, donor 13712
    #
    # e0 is aura 42 -> `800058` on periodic damage at `proc_chance 20`; e1 is aura 4 DUMMY at
    # amount zero carrying `class_mask_a 2048`, i.e. an Ascension engine marker, and goes.
    # Ranked on ProcChance for the same reason as Illidari Smiter -- the record's only number --
    # and 20% is Ascension's ceiling, so unlike Illidari Smiter the top rank IS Ascension's; only
    # the 10% first rank is this file's.
    Talent(TAB, 4, 2, 2, "Illidari Magi", donor=13712, source=560639,
           proc_flags=PROC_DONE_PERIODIC,
           rank_cell="ProcChance",
           rank_values=(10, 20),                # per cent, literal -- not a base-points cell
           overrides={
               "EffectSpellClassMaskA_1": 0,    # the dump's class_mask_a 544, a family-20 fragment
               "Effect_2": 0,                   # aura 4 DUMMY at amount 0, class_mask_a 2048
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectSpellClassMaskA_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Your periodic damage has a $h% chance to generate 1 Felfury.",
           },
           note="560639 -- aura 42 -> 800058 on DONE_PERIODIC; no spell_proc row, because "
                "SpellMgr.cpp:2283 takes the chance off the record"),

    # -- 4/3 -- Unphased .................................. source 803645, donor 13712
    #
    # e0 is aura 123 MOD_TARGET_RESISTANCE at `misc 124` (every school but Physical and Holy),
    # bp -21 with `per_level -1.0` -- 20 spell penetration plus one a level, and the tooltip's
    # own `${-($m1+0)}` is what makes the sign readable.
    # e1 IS REWRITTEN. Ascension has aura 107 at `misc 3`, which in 3.3.5a is SPELLMOD_EFFECT1
    # (SpellDefines.h:79) and has nothing to do with the tooltip's spell pushback. The real cell
    # is aura 149 SPELL_AURA_REDUCE_PUSHBACK (SpellAuraDefines.h:212), which takes a percentage
    # directly and needs no misc value.
    # DEGRADED: the pushback half is "while Inner Demon is active" in Ascension and ships
    # unconditional here. Half a record cannot be form-gated -- `ShapeshiftMask` is a spell-level
    # cell -- and the spell-penetration half is unconditional, so the gate is the part that goes.
    Talent(TAB, 4, 3, 2, "Unphased", donor=13712, source=803645,
           rank_cell="EffectBasePoints_1",
           rank_values=(-11, -21),              # DieSides 1 -> lands -10/-20 target resistance,
                                                # i.e. 10/20 spell penetration, +1 a level
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(24, 49),              # DieSides 1 -> lands 25/50 % less pushback
           overrides={
               "EffectAura_2": 149,             # REDUCE_PUSHBACK, from aura 107 misc 3
               "EffectMiscValue_2": 0,          # the op number the old aura needed
               "Description_Lang_enUS":
                   "Increases your spell penetration by ${-($s1)} and reduces spell pushback "
                   "suffered from damaging attacks by $s2%.",
           },
           note="803645 -- aura 123 misc 124 kept as-is; the pushback half is rebuilt on the "
                "aura WotLK actually has and loses its Inner Demon gate"),

    # =========================================================================================
    # ROW 5
    # =========================================================================================

    # -- 5/0 -- Felbreak .................................. source 800203, donor 2139 Counterspell
    #
    # The interrupt: 10 Energy, 18 s, off the global cooldown, and a Spirit-scaled mana drain.
    # DONOR CHOSEN FOR A CELL THE DUMP HAS NO COLUMN FOR: 2139 carries `Mechanic = 26`
    # MECHANIC_INTERRUPT (SharedDefines.h:1339), and with family 16 unknown to the core, Mechanic
    # is the ONLY diminishing-returns input there is (SpellMgr.cpp:107-263). Cloning Counterspell
    # brings the DR for free; authoring the row would have lost it silently.
    # e1 goes: `base_points -1`, no trigger, no misc -- it implements nothing (plan 2.2 says the
    # same). e0 (eff 68 INTERRUPT_CAST) and e2 (eff 142 -> `804809`, POWER_DRAIN, legal) stay.
    Talent(TAB, 5, 0, 1, "Felbreak", donor=2139, source=800203, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["felbreak"],
               "ManaCost": 10,
               "RecoveryTime": 18000,           # TALENT_BASE zeroes Category/CategoryRecoveryTime,
                                                # which is harmless on a one-rank talent
               "Effect_2": 0,                   # bp -1, trigger 0, misc 0
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Interrupts spellcasting and prevents any spell in that school from being "
                   "cast for $d, draining mana from the target based on your Spirit.",
           },
           note="800203 -- eff 68 + eff 142 -> 804809; Ascension's gcd_ms is 0 and stays 0, "
                "because an interrupt on the GCD is not an interrupt"),

    # -- 5/1 -- Fel Apprentice ............................ source 92088, donor 13712
    #
    # e0/e1 are plain aura 42 procs into `801891` and `803479` -- Felwrath stack plumbing that is
    # legal data. e2 IS A STARTUP CRASH: aura 353 against `TOTAL_AURAS = 317`
    # (SpellAuraDefines.h:380), and `SpellMgr.cpp:3040-3041` ASSERTs, so this is not a silent
    # no-op. Deleted, exactly as plan 3.3's own note on 92088 requires.
    # The gate is the free ShapeshiftMask trick again; `attributes[0] = 320` is
    # PASSIVE|DO_NOT_DISPLAY, which is what HandleShapeshiftBoosts wants.
    # COINCIDENCE WORTH NAMING: Ascension's own id 92088 sits inside our talent band
    # (TALENT_SPELL_ID_BASE 92000-92999). It is a source id, never an emitted one; the generator
    # allocates a fresh id. Nothing collides, but the two 92xxx numbers mean different things.
    Talent(TAB, 5, 1, 1, "Fel Apprentice", donor=13712, source=92088,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           overrides={
               "ShapeshiftMask": INNER_DEMON_STANCE,
               "Effect_3": 0,                   # aura 353 -- above TOTAL_AURAS, would ASSERT
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "ImplicitTargetA_3": 0,
               "Description_Lang_enUS":
                   "While Inner Demon is active, your Fel Fireball also unleashes a Felstrike on "
                   "your target.",
           },
           note="92088 -- two aura 42s kept, aura 353 deleted; needs BIT['fel_fireball']"),

    # -- 5/2 -- Felshock .................................. source 806235, donor 13712
    #
    # e0 is aura 42 -> `806236`, and 806236 is `effect 177` with `misc 804216` (Inner Demon) at
    # bp 999 -- Ascension's private "extend this aura by 1000 ms" effect. Plan 4.C2 owns it: the
    # four extenders all become the module's AllSpellScript adding to `GetDuration()`. THE SCRIPT
    # BINDS TO 806236's PORT, NOT TO THIS RECORD, so there is no `spell_script_names` row here --
    # and `AllSpellScript` would not take one anyway (plan 6.5).
    # e1 is aura 42 -> `572792` (aura 186, +3% chance to be hit by spells) and is plain data.
    Talent(TAB, 5, 2, 1, "Felshock", donor=13712, source=806235,
           proc_flags=PROC_DONE_MAGIC_ABILITY | PROC_DONE_MELEE_ABILITY,
           overrides={
               "Description_Lang_enUS":
                   "Your Felfury spenders' critical strikes extend Inner Demon by 1 sec and "
                   "leave the target easier to hit with spells.",
           },
           note="806235 -- crit-only, so one spell_proc row for the HitMask; the Felfury-spender "
                "restriction is a word-1 mask union and waits on plan 6.2"),

    # -- 5/3 -- Archimonde's Wrath ........................ source 300489, donor 14138
    #
    # Plan 4.C6: a spellmod computed from a runtime number. Ascension keeps it fresh by
    # re-applying `560087` on a 500 ms `aura 23` tick, and 560087 is aura 107 `misc 7` at bp 0,
    # i.e. +1% crit -- so the real rule is "+1% per 10 Energy" and the poll exists only to
    # recompute it.
    # THE POLL IS THE PART WE DELETE. e1 (the 500 ms tick) goes, e0 stops being a COST carrier
    # (`misc 14`) and becomes the CRITICAL_CHANCE carrier the script writes into, and the
    # recompute moves onto an Energy-change hook. That is the point of the port: it also drops
    # Ascension's up-to-500 ms staleness window.
    Talent(TAB, 5, 3, 1, "Archimonde's Wrath", donor=14138, source=300489,
           overrides={
               "EffectMiscValue_1": 7,          # SPELLMOD_CRITICAL_CHANCE, from 14 SPELLMOD_COST
               "EffectBasePoints_1": 0,         # DieSides 1 -> 1% per 10 Energy, which is
                                                # 560087's own amount
               "Effect_2": 0,                   # aura 23, period 500 -> 560087: the poll
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectAuraPeriod_2": 0,
               "EffectSpellClassMaskA_2": 0,    # the dump's class_mask_a 2
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Felfury spenders by $s1% for "
                   "every 10 Energy you have when you cast them.",
           },
           note="300489 + 560087 -- one aura 107 carrier, recomputed by spell_fs_stat_spellmod "
                "instead of by a 500 ms tick"),

    # =========================================================================================
    # ROW 6
    # =========================================================================================

    # -- 6/0 -- Herald of the Legion ...................... source 807461, donor 14138
    #
    # Plan 4.C3, the cheapest bucket: aura 354 is "trigger spell X with N% of the damage dealt",
    # it is above TOTAL_AURAS, and six talents share it. The rewrite keeps aura 42 with the SAME
    # `EffectTriggerSpell` and the SAME `EffectBasePoints` (49 -> 50%), and one AuraScript does
    # `CastCustomSpell(..., SPELLVALUE_BASE_POINT0, CalculatePct(damage, aurEff->GetAmount()))`.
    # `807554` is already the empty shell that expects it: eff 2 SCHOOL_DAMAGE at `base_points 0`,
    # target 53, radius index 195.
    Talent(TAB, 6, 0, 1, "Herald of the Legion", donor=14138, source=807461,
           proc_flags=PROC_DONE_PERIODIC,
           overrides={
               "EffectAura_1": 42,              # from 354, which would ASSERT at startup
               "Description_Lang_enUS":
                   "Damage dealt by your Bane of Chaos radiates fel energy, dealing $s1% of the "
                   "damage dealt to nearby enemies.",
           },
           note="807461 -- aura 354 -> 42 with bp 49 untouched; the amount is read by the script, "
                "not by the core"),

    # -- 6/1 -- Infernal Doom ............................. source 804219, donor 13732
    #
    # Plan 4.C1's refund roll: Ruin has a chance not to consume Felfury. There is no core path
    # for that -- Felfury is a stacking aura, not a power -- so the number is a cell the module's
    # spender script reads, and aura 107 `misc 18` SPELLMOD_CHANCE_OF_SUCCESS (SpellDefines.h:94)
    # is the honest place to keep it.
    # THE SIGN IS FLIPPED ON PURPOSE. Ascension writes bp -26 (-25%); our script reads the amount
    # as a percentage chance and the client renders `$s1`, so a negative would print "-25% chance".
    # Magnitude unchanged, and it is Ascension's.
    Talent(TAB, 6, 1, 1, "Infernal Doom", donor=13732, source=804219,
           overrides={
               "EffectBasePoints_1": 24,        # DieSides 1 -> 25%, Ascension's -26 unsigned
               "EffectSpellClassMaskA_1": 0,    # the dump's class_mask_a 1 -- which resolves to
                                                # Fel Apprentice in family 20, because Ruin's own
                                                # mask is word 2 and the dump exports word A only
               "EffectSpellClassMaskC_1": FELBLOOD_TALENT_BIT["ruin"],
               "Description_Lang_enUS":
                   "Your Ruin has a $s1% chance not to consume Felfury.",
           },
           note="804219 -- aura 107 misc 18 as the script's storage; no proc flags, the roll "
                "happens in the spender path"),

    # -- 6/2 -- Shadow Magi ............................... source 803905, donor 13712
    #
    # Two aura 107 SPELLMOD_COOLDOWN effects at bp -15001 and -4001 -> -15 s and -4 s.
    # WHICH ANNIHILATION, SETTLED FROM THE DATA RATHER THAN THE NAME: there are two (plan 2.1),
    # and e0's `class_mask_a = 0x20000000` matches exactly one spell in the whole family --
    # `803904`, the 60 s guaranteed-crit cooldown. The channelled nuke `802059` carries
    # `[0, 0x100000, 0]`, a word-2 bit, which a `class_mask_a` cannot name. -15 s off 60 s.
    # Units are milliseconds, so -7501 lands -7500.
    Talent(TAB, 6, 2, 2, "Shadow Magi", donor=13712, source=803905,
           rank_cell="EffectBasePoints_1",
           rank_values=(-7501, -15001),         # DieSides 1 -> lands -7500/-15000 ms
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(-2001, -4001),        # DieSides 1 -> lands -2000/-4000 ms
           overrides={
               "EffectSpellClassMaskA_1": 0,    # the dump's class_mask_a, a family-20 fragment
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Annihilation by $/1000;s1 sec and of your "
                   "Sunder by $/1000;s2 sec.",
           },
           note="803905 -- two SPELLMOD_COOLDOWNs; needs BIT['annihilation_crit'] and "
                "BIT['sunder'] once plan 6.2 lands"),

    # -- 6/3 -- Withering ................................. source 707416, donor 14138
    #
    # THE AURA IS REWRITTEN because the cell and the tooltip disagree in Ascension: the text says
    # "$s1% increased damage" and the cell is aura 107 (FLAT) at `misc 12` SPELLMOD_EFFECT2, which
    # adds 30 raw points to one effect index. aura 108 ADD_PCT_MODIFIER at `misc 0`
    # SPELLMOD_DAMAGE is what the sentence describes.
    # DEGRADED AND FLAGGED, NOT SILENTLY RETUNED: "used with Felforged active" has no data cell.
    # `CasterAuraSpell` gates a CAST, not a passive modifier's application, so as written this
    # ships UNCONDITIONAL and is therefore materially hotter than Ascension's 30%. The fix is to
    # move the modifier onto Felforged's own buff record `806104` (a TRIGGERS row belonging to
    # 7/1), where it is gated by construction -- and where it can no longer be ranked. That trade
    # is a decision for the tuning pass, so the ceiling stays Ascension's and this comment is the
    # flag.
    Talent(TAB, 6, 3, 2, "Withering", donor=14138, source=707416,
           rank_cell="EffectBasePoints_1",
           rank_values=(14, 29),                # DieSides 1 -> lands 15/30 %
           overrides={
               "EffectAura_1": 108,             # ADD_PCT_MODIFIER, from 107 ADD_FLAT_MODIFIER
               "EffectMiscValue_1": 0,          # SPELLMOD_DAMAGE, from 12 SPELLMOD_EFFECT2
               "Description_Lang_enUS":
                   "Increases the damage of your Fel Fireball by $s1%.",
           },
           note="707416 -- the Felforged gate is dropped; description rewritten to match what "
                "the record now does rather than what Ascension's said"),

    # =========================================================================================
    # ROW 7
    # =========================================================================================

    # -- 7/0 -- Infernal .................................. source 560284, donor 1122 Inferno
    #
    # 45 s cooldown: area Fire damage, a horrify, and a summoned Infernal. Donor 1122 is the stock
    # spell this IS -- a meteor that lands, damages, and leaves a pet -- and it has two effects
    # against the source's three, which is the safe direction.
    # `Mechanic` IS SET AND THE DONOR'S IS NOT KEPT: 1122 has Mechanic 0, and an area fear with no
    # Mechanic has no diminishing returns at all, which is a PvP bug rather than a nicety
    # (SpellMgr.cpp:107-263 keys DR off Mechanic and nothing else for an unknown family).
    # e2 (eff 64 -> `572183`) is the summon and needs a TRIGGERS row.
    Talent(TAB, 7, 0, 1, "Infernal", donor=1122, source=560284, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["infernal"],
               "Mechanic": 5,                   # MECHANIC_FEAR (SharedDefines.h:1318)
               "RecoveryTime": 45000,
               "Description_Lang_enUS":
                   "Drops an infernal from the sky, dealing $s2 Fire damage to nearby enemies, "
                   "horrifying them for $d, and summoning an Infernal to fight for you.",
           },
           note="560284 -- aura 5 MOD_FEAR + eff 2 + eff 64; the Inner Demon duration bonus lives "
                "in 807421 and is not ported"),

    # -- 7/1 -- Felforged ................................. source 300490, donor 14138
    #
    # aura 42 -> `806104` at `proc_chance 15`. 806104 is the buff Withering at 6/3 is written
    # against: aura 108 `misc 10` at bp -31, i.e. -30% cast time on the next three Fel Fireballs.
    # Chance comes off the record (SpellMgr.cpp:2283), so no `spell_proc` row.
    Talent(TAB, 7, 1, 1, "Felforged", donor=14138, source=300490,
           proc_flags=PROC_DONE_PERIODIC,
           overrides={
               "Description_Lang_enUS":
                   "Your periodic damage has a $h% chance to make your next 3 Fel Fireballs cast "
                   "30% faster.",
           },
           note="300490 -- aura 42 -> 806104; the spell-level class_mask [4,0,0] is closed by "
                "ALWAYS along with every other imported family-20 mask"),

    # -- 7/2 -- Chaotic Intuition ......................... source 300483, donor 13712
    #
    # Two aura 42s. e0 -> `300481` (aura 163 at bp 0, +1% spell crit damage a stack) is plain
    # data. e1 -> `560643`, which carries `effect 177` at `misc 704371` -- Ascension's private
    # "extend Cripple by 1000 ms". Same bucket as Felshock: plan 4.C2's duration script binds to
    # 560643's port, which is a TRIGGERS row, so this record takes no `spell_script_names` row.
    # Note `560643`'s target is `704371`, the decaying-slow Cripple variant plan 2.2 explicitly
    # says NOT to ship -- the port must retarget it at the `707436` chain.
    Talent(TAB, 7, 2, 1, "Chaotic Intuition", donor=13712, source=300483,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           overrides={
               "Description_Lang_enUS":
                   "Damage dealt by your Felstrikes extends Cripple on the target and increases "
                   "your spell critical strike damage, stacking.",
           },
           note="300483 -> 300481 + 560643; 560643 names Cripple 704371 and must be repointed at "
                "the 707436 chain plan 2.2 ships"),

    # -- 7/3 -- Fel Flamecasting .......................... source 805998, donor 14138
    #
    # aura 42 -> `300491`, and 300491's e1 is `effect 169` -- an Ascension private effect, i.e.
    # another startup ASSERT if imported.
    # PLAN 3.3 TAGS THIS [C7] AND SECTION 4's C7 TABLE DOES NOT LIST IT. C7 is victim-state
    # conditions through aura 112 and this record has no aura 112; the tab-38 legality census in
    # section 4 is the entry that is right ("169 `300491`"). The work is "copy Cripple to two
    # nearby enemies", it lives on the trigger record rather than on this one, and none of the six
    # named scripts covers it -- so this file records the correction instead of inventing a name.
    Talent(TAB, 7, 3, 1, "Fel Flamecasting", donor=14138, source=805998,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           overrides={
               "Description_Lang_enUS":
                   "Damage dealt by your Sargeron Smite spreads your Cripple to 2 nearby enemies.",
           },
           note="805998 -> 300491 (effect 169); the [C7] tag in plan 3.3 disagrees with section "
                "4's own C7 table and with the census row, which names the real problem"),

    # =========================================================================================
    # ROW 8
    # =========================================================================================

    # -- 8/0 -- Infernal Summoner ......................... source 300480, donor 14138
    #
    # aura 42 -> `301289` at `proc_chance 5`, and 301289 is `effect 195` at `misc 560284`:
    # Ascension's "reset that spell's cooldown". Plan 4.C4's rewrite turns the offending effect
    # into SPELL_EFFECT_DUMMY with `EffectMiscValue` = the target spell, and one table-free
    # SpellScript calls `RemoveSpellCooldown(id, true)`.
    # THE ROW BINDS TO 301289's PORT, not to this record -- the DUMMY effect is there. It is in
    # SCRIPT_NAMES_FELBLOOD anyway because the task's contract is "the talent names the script it
    # needs", and this note says which record the generator must attach it to.
    # Note 301289's own tooltip says Annihilation while its `misc` says 560284 Infernal; the cell
    # wins, and it agrees with the talent's name.
    Talent(TAB, 8, 0, 1, "Infernal Summoner", donor=14138, source=300480,
           proc_flags=PROC_DONE_MAGIC_ABILITY | PROC_DONE_MELEE_ABILITY,
           overrides={
               "Description_Lang_enUS":
                   "Your direct damage has a $h% chance to reset the cooldown of your Infernal.",
           },
           note="300480 -> 301289 (effect 195, misc 560284); chance is the record's, so no "
                "spell_proc row"),

    # -- 8/1 -- Infernal Ruin ............................. source 560840, donor 14138
    #
    # Plan 4.C8, "every Nth": one AuraScript holding the count in a hidden aura's stack count so
    # it survives a relog, with `EffectMiscValue` supplying N. Ascension's e0 is a bare aura 4
    # DUMMY with no number at all, so N is written here.
    # FLAGGED, and it is the trap in this bucket: Felwrath is AoE. A done-damage proc fires ONCE
    # PER TARGET, so a single Felwrath into three enemies would advance the counter three times
    # and the third Infernal arrives two casts early. `spell_fs_counter` needs a per-cast guard,
    # not just a counter.
    Talent(TAB, 8, 1, 1, "Infernal Ruin", donor=14138, source=560840,
           proc_flags=PROC_DONE_MAGIC_ABILITY,
           overrides={
               "EffectAura_1": 42,              # from 4 DUMMY -- the script needs a proc to hook
               "EffectMiscValue_1": 3,          # N: every 3rd Ruin or Felwrath
               "Description_Lang_enUS":
                   "Every 3rd Ruin or Felwrath summons an Infernal to fight for you.",
           },
           note="560840 -- N moves from Ascension's engine into EffectMiscValue_1; the summon "
                "itself is a TRIGGERS row"),

    # -- 8/2 -- Malice of Gul'dan ......................... source 800214, donor 13712
    #
    # Two aura 42s at `proc_chance 60` -> `800239` "Fragment of Malice" (aura 290 +10% crit and
    # eff 30 ENERGIZE for 5 Energy) and `802678` Felstrike. e1 is an aura 4 DUMMY at amount zero
    # between them and goes.
    Talent(TAB, 8, 2, 1, "Malice of Gul'dan", donor=13712, source=800214,
           proc_flags=PROC_DONE_MAGIC_ABILITY | PROC_DONE_MELEE_ABILITY,
           overrides={
               "Effect_2": 0,                   # aura 4 DUMMY at amount 0
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Your direct critical strikes have a $h% chance to trigger a Felstrike and "
                   "grant a Fragment of Malice.",
           },
           note="800214 -- crit-only, so one spell_proc row for the HitMask; the 60% chance is "
                "the record's"),

    # -- 8/3 -- Fel Infusion .............................. source 560533, donor 13712
    #
    # `Effect 65` is SPELL_EFFECT_APPLY_AREA_AURA_RAID (SpellInfo.cpp:684) carrying aura 290
    # MOD_CRIT_PCT, plus the same aura on the caster -- which is already the correct shape plan
    # 3.4 has to REBUILD for Betrayer's 520256. Nothing to fix; +3% is Ascension's own on both.
    # "Does not stack with similar effects" is a `spell_group` exclusivity row, not a DBC cell,
    # and is not emitted here -- so it stacks with Leader of the Pack and Rampage until it is.
    Talent(TAB, 8, 3, 1, "Fel Infusion", donor=13712, source=560533,
           overrides={
               "Description_Lang_enUS":
                   "Increases the critical strike chance of all party and raid members within "
                   "$a1 yards by $s1%, and your own by an additional $s2%.",
           },
           note="560533 -- eff 65 + aura 290; the only talent in the tree that needs no fix at "
                "all beyond its description"),

    # =========================================================================================
    # ROW 9
    # =========================================================================================

    # -- 9/0 -- Sculptor of Doom .......................... source 801235, donor 14138
    #
    # Plan 4.C8 again, counting to three direct critical strikes. Ascension's e0 is aura 42 ->
    # `555276`; N is nowhere on the record, so it is written into `EffectMiscValue_1` for the same
    # shared script Infernal Ruin uses.
    Talent(TAB, 9, 0, 1, "Sculptor of Doom", donor=14138, source=801235,
           proc_flags=PROC_DONE_MAGIC_ABILITY | PROC_DONE_MELEE_ABILITY,
           overrides={
               "EffectMiscValue_1": 3,          # N: three direct critical strikes
               "Description_Lang_enUS":
                   "Landing 3 direct critical strikes grants you Sculptor of Doom.",
           },
           note="801235 -- aura 42 -> 555276; crit-only, so one spell_proc row for the HitMask"),

    # -- 9/1 -- The True Blessing ......................... source 560838, donor 14138
    #
    # aura 42 -> `555281` (aura 108 `misc 10` at bp -101: the next Ruin is instant).
    # THE PROC FLAG FOLLOWS FROM WHICH ANNIHILATION THIS IS, and Shadow Magi at 6/2 settles it
    # from the mask data: the tree's Annihilation is `803904`, the guaranteed-crit COOLDOWN. That
    # spell deals no damage, so no done-damage flag can ever fire on it --
    # PROC_FLAG_DONE_SPELL_NONE_DMG_CLASS_POS (SpellMgr.h:126) is the bit a self-buff cast raises.
    # FLAGGED: this is the least certain proc flag in the tree. If it never fires, the next thing
    # to try is a `SpellScript::AfterCast` on Annihilation itself rather than a proc at all.
    Talent(TAB, 9, 1, 1, "The True Blessing", donor=14138, source=560838,
           proc_flags=PROC_DONE_POSITIVE_CAST,
           overrides={
               "Description_Lang_enUS":
                   "Casting Annihilation grants you Sculptor of Doom.",
           },
           note="560838 -- aura 42 -> 555281; needs BIT['annihilation_crit'] on the effect or it "
                "fires off every beneficial cast"),

    # -- 9/2 -- Fury of Archimonde ........................ source 706268, donor 14138
    #
    # Plan 4.C8's odd one out: the trigger is "after generating 10 Felfury", which is not an event
    # `ProcFlags` can name. Felfury is granted by the module's own `GrantFelfury` (plan 4.C1), so
    # THE COUNTER HANGS OFF THAT PATH and `proc_flags` stays 0 deliberately -- a non-zero value
    # here would have SpellMgr synthesise a proc entry that fires on the wrong thing.
    # The aura therefore stays Ascension's aura 4 DUMMY: a marker the C1 script looks for, not a
    # proc. N goes in `EffectMiscValue_1`, same convention as the other two counters.
    # The payoff is `706269` (+50% crit and +50% damage on the next Sargeron Smite), a TRIGGERS
    # row.
    Talent(TAB, 9, 2, 1, "Fury of Archimonde", donor=14138, source=706268,
           overrides={
               "EffectMiscValue_1": 10,         # N: ten Felfury generated
               "Description_Lang_enUS":
                   "After generating 10 Felfury, your next Sargeron Smite gains increased "
                   "critical strike chance and damage.",
           },
           note="706268 -- aura 4 kept as the marker; counted from the Felfury grant path, which "
                "is why this is the one counter with no proc flags"),

    # =========================================================================================
    # ROW 10
    # =========================================================================================

    # -- 10/1 -- Sargeras Embrace ......................... source 800355, donor 689 Drain Life
    #
    # The capstone button: a 30-Energy, 60 s channel that slows through `800833` on a 500 ms tick
    # and detonates for Shadowflame at the end. Donor 689 is the stock channelled-periodic shape
    # and carries the ChannelInterruptFlags the dump has no column for.
    # DEGRADED, and it is a whole tooltip clause: "you may instant cast Fel Fireball and Ruin
    # while channeling and they refund their cost". 3.3.5a has no data path -- starting any cast
    # interrupts a channel -- and no cheap script one either, since the refund would have to
    # unwind a cost the channel never paid. The clause is dropped and the description rewritten
    # rather than shipped as a lie, exactly as plan 7 does for the Combo system.
    Talent(TAB, 10, 1, 1, "Sargeras Embrace", donor=689, source=800355, flags=1,
           overrides={
               "SpellClassMask_3": FELBLOOD_TALENT_BIT["sargeras_embrace"],
               "ManaCost": 30,
               "RecoveryTime": 60000,
               "Description_Lang_enUS":
                   "Channels a beam of fel magic at an enemy, slowing them for $d and dealing "
                   "$s2 Shadowflame damage when the channel ends.",
           },
           note="800355 -- aura 23 -> 800833 at 500 ms + aura 3 at 4900 ms; duration_index 571"),
)


# =============================================================================================
# THE SCRIPT ROWS -- plan section 4, and only the DB-BOUND ones
# =============================================================================================
#
# Keyed by grid position, exactly like `dh_talents.SCRIPT_NAMES`, because that is the only handle
# this file has on a talent whose spell ids the generator allocates. EVERY RANK gets a row --
# `spell_script_names` is keyed by spell id and a two-rank talent is two ids.
#
# WHAT IS NOT HERE, AND WHY IT IS NOT AN OMISSION (plan 6.5 draws the line):
#   * C2 Inner Demon duration (Felshock 5/2, Chaotic Intuition 7/2) and C1's Felfury gate live in
#     the module's `AllSpellScript`, which is registered in code and takes no row at all.
#   * C7 victim conditions (Fel Cannon 3/2, Doomsayer 4/0) live in a `UnitScript`. Same.
#   * Fel Flamecasting 7/3's real work is on a TRIGGERS record and none of the six named scripts
#     covers it; see its comment rather than a guessed name here.
# Where the row must bind to a TALENT'S TRIGGER RECORD rather than to its rank records, the
# talent's own comment says so -- Infernal Summoner is the one case.
SCRIPT_NAMES_FELBLOOD = {
    (5, 3): "spell_fs_stat_spellmod",       # C6 -- crit per 10 Energy, off a stat hook
    (6, 0): "spell_fs_damage_pct_trigger",  # C3 -- aura 354's six talents share this one script
    (6, 1): "spell_fs_felfury_spender",     # C1 -- the chance not to consume Felfury
    (8, 0): "spell_fs_modify_cooldown",     # C4 -- binds to 301289's port, see the note
    (8, 1): "spell_fs_counter",             # C8 -- every 3rd Ruin or Felwrath
    (9, 0): "spell_fs_counter",             # C8 -- three direct critical strikes
    (9, 2): "spell_fs_counter",             # C8 -- ten Felfury generated
}


# =============================================================================================
# selftest
# =============================================================================================

def selftest():
    """Fail here, at import time, rather than in game. Returns the point total.

    The five checks the task names, plus the ones that would otherwise be found by a player:
    the grid, tier reachability, the point total, the rank cap and the arrows.
    """
    cols = set(dbc_tables.SPELL_DBC.columns)
    string_cols = {name for i, name in enumerate(dbc_tables.SPELL_DBC.columns)
                   if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_STRING}
    float_cols = {name for i, name in enumerate(dbc_tables.SPELL_DBC.columns)
                  if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_FLOAT}

    # ---- the grid: no two talents in one cell ------------------------------------------------
    seen = {}
    for t in TALENTS_FELBLOOD:
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert t.tab == TAB, f"{where}: tab is {t.tab!r}, not {TAB!r}"
        assert 0 <= t.tier <= 10, f"{where}: TierID is 0-10"
        assert 0 <= t.col <= 3, f"{where}: ColumnIndex is 0-3 (NUM_TALENT_COLUMNS)"
        assert (t.tier, t.col) not in seen, (
            f"{where}: grid collision, already taken by {seen.get((t.tier, t.col))!r}")
        seen[(t.tier, t.col)] = t.name

    # ---- max_rank ----------------------------------------------------------------------------
    #
    # `Talent.dbc` has SpellRank_1..5 and nothing past it, so 5 is a hard cap rather than a style
    # rule. 4 is excluded because no stock row uses it (dh_talents' own check, 892 rows read).
    for t in TALENTS_FELBLOOD:
        assert t.ranks <= 5, f"({t.tier},{t.col}) {t.name!r}: {t.ranks} ranks, Talent.dbc caps 5"
        assert t.ranks in (1, 2, 3, 5), (
            f"({t.tier},{t.col}) {t.name!r}: {t.ranks} ranks; stock uses 1, 2, 3 and 5, never 4")

    # ---- the point total, against plan 3.3 ---------------------------------------------------
    per_row = {}
    for t in TALENTS_FELBLOOD:
        per_row[t.tier] = per_row.get(t.tier, 0) + t.ranks
    total = sum(per_row.values())
    assert total == 68, (
        f"Felblood full-clears for {total} points, not the 68 plan 3.3 states. The plan's "
        f"heading also says '28 talents' where its own grid has {len(TALENTS_FELBLOOD)}; the "
        f"points are the number that was computed, the count is the number that was typed")
    assert len(TALENTS_FELBLOOD) == 39, (
        f"{len(TALENTS_FELBLOOD)} talents; plan 3.3's grid has 39 cells and demon-hunter.json "
        f"has 39 tab-38 nodes")

    # ---- reachability: 5 points per tier above ------------------------------------------------
    #
    # `Player::LearnTalent`: `if (spentPoints < talentInfo->Row * MAX_TALENT_RANK) return;` with
    # MAX_TALENT_RANK 5, and TalentFrameBase.lua enforces the same rule client-side. The gates
    # this reproduces are plan 3.3's own 15/24/32/39/46/50/56/60/64/67.
    available = 0
    gates = []
    for row in range(11):
        if row:
            assert available >= row * 5, (
                f"row {row} needs {row * 5} points spendable above it and only {available} "
                f"exist -- every talent in that row is unreachable")
        available += per_row.get(row, 0)
        gates.append(available)
    assert gates[:10] == [15, 24, 32, 39, 46, 50, 56, 60, 64, 67], (
        f"the running totals {gates[:10]} are not plan 3.3's gate list -- a rank count moved")

    # ---- the arrows --------------------------------------------------------------------------
    for t in TALENTS_FELBLOOD:
        if not t.prereq:
            continue
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert len(t.prereq) == 3, f"{where}: prereq is (tier, col, rank)"
        ptier, pcol, prank = t.prereq
        tail = [x for x in TALENTS_FELBLOOD if (x.tier, x.col) == (ptier, pcol)]
        assert tail, f"{where}: prerequisite at ({ptier},{pcol}) is not a talent in this tree"
        tail = tail[0]
        # `dhspells.build_talents` check #45 and TalentFrame_DrawLines both require the tail to
        # be in an EARLIER tier; PrereqRank_1 is a 0-based floor (Player.cpp:14329).
        assert ptier < t.tier, (
            f"{where}: prerequisite {tail.name!r} is in tier {ptier}, not earlier than {t.tier}")
        assert 0 <= prank < tail.ranks, (
            f"{where}: prerequisite rank {prank} is outside {tail.name!r}'s {tail.ranks} ranks")

    # ---- the cells ---------------------------------------------------------------------------
    for t in TALENTS_FELBLOOD:
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert isinstance(t.donor, int) and t.donor > 0, f"{where}: donor must be a spell id"
        assert isinstance(t.source, int) and t.source > 0, (
            f"{where}: every Felblood talent imports an Ascension record, and `donor` is still "
            f"required alongside it so a failed import degrades instead of blanking the row")
        for col, value in t.overrides.items():
            assert col in cols, f"{where}: {col!r} is not a Spell.dbc column"
            if col in string_cols:
                assert isinstance(value, str), f"{where}: {col!r} is a string column"
            elif col in float_cols:
                assert isinstance(value, float), f"{where}: {col!r} is a float column"
            else:
                assert isinstance(value, int) and not isinstance(value, bool), (
                    f"{where}: {col!r} must be an int, got {value!r}")
        for cell, values, which in ((t.rank_cell, t.rank_values, "rank_cell"),
                                    (t.rank_cell_2, t.rank_values_2, "rank_cell_2")):
            if not cell:
                assert not values, f"{where}: {which}_values with no {which} would never be read"
                continue
            assert cell in cols and cell not in string_cols, (
                f"{where}: {which} {cell!r} is not a writable Spell.dbc column")
            assert cell not in t.overrides, (
                f"{where}: {cell!r} is in both overrides and {which}; the generator writes the "
                f"override first and the rank value second, so the override would be discarded")
            assert len(values) == t.ranks, (
                f"{where}: {len(values)} {which} values for {t.ranks} ranks")
            assert all(isinstance(v, int) and not isinstance(v, bool) for v in values), (
                f"{where}: {which} values must be ints")
        assert t.rank_cell != t.rank_cell_2 or not t.rank_cell, (
            f"{where}: both rank cells name {t.rank_cell!r}")
        assert t.ranks == 1 or t.rank_cell, (
            f"{where}: {t.ranks} ranks and no rank_cell, so every rank would be the same record "
            f"and the extra points would buy nothing")

    # ---- the granted buttons -----------------------------------------------------------------
    actives = tuple(t for t in TALENTS_FELBLOOD if t.flags == 1)
    assert len(actives) == len(FELBLOOD_TALENT_BIT), (
        f"{len(actives)} talents grant a button but FELBLOOD_TALENT_BIT has "
        f"{len(FELBLOOD_TALENT_BIT)} entries")
    for t in actives:
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert t.ranks == 1, f"{where}: a button-granting talent is one rank, never {t.ranks}"
        bit = t.overrides.get("SpellClassMask_3", 0)
        assert bit in FELBLOOD_TALENT_BIT.values(), (
            f"{where}: SpellClassMask_3 {bit:#x} is not one of this tree's bits")
    assert len({t.overrides["SpellClassMask_3"] for t in actives}) == len(actives), (
        "two granted actives share a SpellClassMask_3 bit")
    # The 8-bit block rule in the FELBLOOD_TALENT_BIT comment, checked rather than trusted: bits
    # 16-23 only, one bit each, so Demonology (0-7) and Slaying (8-15) cannot collide with us.
    for key, bit in FELBLOOD_TALENT_BIT.items():
        assert bit and not (bit & (bit - 1)), f"FELBLOOD_TALENT_BIT[{key!r}] is not one bit"
        assert bit & 0x00FF0000 == bit, (
            f"FELBLOOD_TALENT_BIT[{key!r}] = {bit:#x} is outside the tree's 16-23 block")

    # Word 1 and word 2 belong to the ability kit and its second records; a talent rank record
    # wearing an ability's bit would be modified by every talent that names that ability.
    for t in TALENTS_FELBLOOD:
        for col in ("SpellClassMask_1", "SpellClassMask_2"):
            assert t.overrides.get(col, 0) == 0, (
                f"({t.tier},{t.col}) {t.name!r}: {col} must stay 0 -- it is dh_donors' column")
        for n in (1, 2, 3):
            mask = t.overrides.get(f"EffectSpellClassMaskC_{n}", 0)
            assert mask & ~sum(FELBLOOD_TALENT_BIT.values()) == 0, (
                f"({t.tier},{t.col}) {t.name!r}: EffectSpellClassMaskC_{n} = {mask:#x} names a "
                f"word-3 bit no Felblood button owns")

    # ---- the form-gated pair -----------------------------------------------------------------
    #
    # `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1449-1456) only picks up a
    # passive that is PASSIVE|DO_NOT_DISPLAY, and a granted button must not be one.
    for t in TALENTS_FELBLOOD:
        if t.overrides.get("ShapeshiftMask"):
            where = f"({t.tier},{t.col}) {t.name!r}"
            assert t.overrides["ShapeshiftMask"] == INNER_DEMON_STANCE, (
                f"{where}: the only stance a Felsworn has is form 23")
            assert t.flags == 0, f"{where}: a form-gated passive cannot also grant a button"

    # ---- the script rows ---------------------------------------------------------------------
    for pos, script in SCRIPT_NAMES_FELBLOOD.items():
        assert pos in seen, f"SCRIPT_NAMES_FELBLOOD names {pos}, which is not a talent"
        assert isinstance(script, str) and script.startswith("spell_fs_"), (
            f"SCRIPT_NAMES_FELBLOOD[{pos}] = {script!r} is not one of plan section 4's names")

    # ---- the dump ----------------------------------------------------------------------------
    #
    # `source` is an id in a file, so it is checked against that file rather than against a
    # comment: an id the dump does not have is a talent that imports nothing and ships whatever
    # its donor happened to be. The effect/aura ceilings are the same check one stage earlier
    # than plan 6.4 item 5 asks the generator for, and they are the only assertion in this file
    # whose failure mode is a worldserver STARTUP CRASH -- `SpellMgr.cpp:3039-3040` ASSERTs
    # `Effect < 165` and `ApplyAuraName < 317`, and the import carries Ascension's private
    # effects (165/169/175/177/195) and auras (344/353/354) verbatim unless a cell in
    # `overrides` replaces them. Skipped, not failed, when the dump is not on this machine.
    dump_path = os.path.join(REPO_ROOT, "build", "tools", "ascension", "out",
                             "felsworn-family20.json")
    if os.path.exists(dump_path):
        import json
        with open(dump_path) as handle:
            records = {row["id"]: row for row in json.load(handle)["spells"]}
        for t in TALENTS_FELBLOOD:
            where = f"({t.tier},{t.col}) {t.name!r}"
            assert t.source in records, (
                f"{where}: source {t.source} is not in felsworn-family20.json")
            for n in getattr(t, "source_ranks", ()):
                assert n in records, f"{where}: source rank {n} is not in the dump"
            for i, e in enumerate(records[t.source]["effects"], start=1):
                eff = t.overrides.get(f"Effect_{i}", e["effect"])
                aura = t.overrides.get(f"EffectAura_{i}", e["aura"])
                assert eff <= 164, (
                    f"{where}: {t.source} Effect_{i} = {eff} survives the import and "
                    f"SpellMgr.cpp:3039 ASSERTs on it at startup")
                assert aura <= 316, (
                    f"{where}: {t.source} EffectAura_{i} = {aura} survives the import and "
                    f"SpellMgr.cpp:3040 ASSERTs on it at startup")
            # THE RUIN TRAP, generalised. Form 23's DBC Flags come from row 22 (dhspells.py:438)
            # and carry no SHAPESHIFT_FLAG_STANCE, so `actAsShifted` is true and any granted
            # button whose imported Attributes keep SPELL_ATTR0_NOT_SHAPESHIFTED is
            # SPELL_FAILED_NOT_SHAPESHIFT for as long as the player is in Inner Demon
            # (SpellInfo.cpp:1470-1476). Ruin clears it by hand; this is why.
            if t.flags:
                attrs = t.overrides.get("Attributes", records[t.source]["attributes"][0])
                assert not (attrs & NOT_SHAPESHIFTED), (
                    f"{where}: Attributes {attrs & 0xFFFFFFFF:#x} keeps NOT_SHAPESHIFTED and "
                    f"the button greys out inside Inner Demon")
    else:
        print(f"skipped the Ascension dump check: {dump_path} is not present")

    # ---- the tab -----------------------------------------------------------------------------
    #
    # Not an assert: plan 6.3 renames the tabs and this file is written against the renamed set,
    # so before that lands the mismatch is expected and is reported rather than raised.
    if TAB not in dh_talents.TAB_KEYS:
        print(f"NOTE: dh_talents.TABS is still {dh_talents.TABS} -- plan 6.3 renames them to "
              f"Demonology/Slaying/Felblood before {TAB!r} resolves")

    return total


POINTS = selftest()


if __name__ == "__main__":
    print(f"talents_felblood -- {len(TALENTS_FELBLOOD)} talents, {POINTS} points, "
          f"{sum(t.ranks for t in TALENTS_FELBLOOD)} rank records")
    print(f"                   {len([t for t in TALENTS_FELBLOOD if t.flags])} granted buttons, "
          f"{len(SCRIPT_NAMES_FELBLOOD)} spell_script_names rows, "
          f"{len([t for t in TALENTS_FELBLOOD if t.proc_flags])} authored ProcTypeMasks")
    print()
    print(f"{'row':>3} | {'col 0':<22} | {'col 1':<22} | {'col 2':<22} | col 3")
    print("-" * 3 + "-+-" + "-" * 22 + "-+-" + "-" * 22 + "-+-" + "-" * 22 + "-+-" + "-" * 22)
    for tier in range(11):
        cells = []
        for col in range(4):
            here = [t for t in TALENTS_FELBLOOD if t.tier == tier and t.col == col]
            if not here:
                cells.append(" " * 22)
                continue
            t = here[0]
            cells.append(f"{t.name[:19]:<19}{'*' if t.flags else ' '}"
                         f"{'^' if t.prereq else ' '}{t.ranks}")
        print(f"{tier:>3} | " + " | ".join(cells).rstrip())
    print("(* grants a spellbook button, ^ has a prerequisite arrow, trailing digit = ranks)")
    print()
    for t in TALENTS_FELBLOOD:
        pre = f"  prereq ({t.prereq[0]},{t.prereq[1]}) @ rank {t.prereq[2]}" if t.prereq else ""
        print(f"  ({t.tier},{t.col}) {t.name:<22} {t.ranks} rank(s)  source {t.source:<6} "
              f"donor {t.donor:<6} flags {t.flags}{pre}")
        if t.rank_cell:
            print(f"        {t.rank_cell} = {', '.join(str(v) for v in t.rank_values)}")
        if t.rank_cell_2:
            print(f"        {t.rank_cell_2} = {', '.join(str(v) for v in t.rank_values_2)}")
        if t.proc_flags:
            print(f"        ProcTypeMask = {t.proc_flags:#010x}")
        if (t.tier, t.col) in SCRIPT_NAMES_FELBLOOD:
            print(f"        script: {SCRIPT_NAMES_FELBLOOD[(t.tier, t.col)]}")
