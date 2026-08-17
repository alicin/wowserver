#!/usr/bin/env python3
"""SLAYING -- the Felsworn melee-DPS tree, as data. Port plan section 3.2, row by row.

This is a FRAGMENT of the rewritten `dh_talents.py` (plan 6.3). It carries one tree so the three
can be written and reviewed independently; the merge concatenates
`_DEMONOLOGY + TALENTS_SLAYING + _FELBLOOD` into `TALENTS` and folds `SCRIPT_NAMES_SLAYING` into
`SCRIPT_NAMES`. Everything the merge has to change is named below rather than left to be
discovered.

WHAT dh_talents HAS TO GAIN BEFORE THIS FILE IS MORE THAN A FRAGMENT
-------------------------------------------------------------------
  1. `Talent` gains `rank_cell_2: str`, `rank_values_2: tuple` and `proc_flags: int` (plan 6.3),
     and `dhspells.py:1031` -- `cells[rank_cell] = talent.rank_values[r]`, which 6.4.3 cites as
     :878 and which has since moved -- learns to write the second per-rank cell. FIVE talents
     here rank two numbers -- Spite, Slice & Dice, Burning Rage, Azzinoth's Rage and Glaiving.
     3.4's list of two-number talents names only Slice & Dice out of this tree because it is
     enumerating the ones the Demonology tree would otherwise freeze; the count of cells the
     generator has to learn to write is what matters, not the list. Until 6.3 lands, the shim at
     the top of this file supplies the three fields so the module imports and `selftest()` runs.
  2. `TRIGGERS` must allow TWO entries per talent. Azzinoth's Assault and Annihilan Strike each
     fire a main-hand AND an off-hand record, exactly as `dh_spec.Ability` gained
     `second_records` for Twin Slice, so the assertion at `dh_talents.py:2395`
     (`len({used_by}) == len(TRIGGERS)`) has to key on (used_by, cell) instead of used_by.
  3. `spell_script_names` emission must cover TRIGGERS rows, not only talent ranks
     (`dhspells.py:1619-1644`, which 6.4.5 cites as :1456; it walks SCRIPT_NAMES by grid
     position and emits one row per RANK id). Three C4 talents here put their dummy cooldown
     effect on the triggered row, which is where the script has to bind (plan 4 C4).

Sixteen talents below carry `SPELL_AURA_PROC_TRIGGER_SPELL` with `EffectTriggerSpell_*` left
UNWRITTEN, because the id belongs to a row only the generator can number -- the same hole
`dh_talents.TRIGGERS` already fills for five Demon Hunter talents. Each one's `note` names the
Ascension record the TRIGGERS entry is built from. A talent given no entry does not fail: it
silently keeps its donor's own trigger (12319 -> 12966 Flurry, 17793 -> 17800), which is why
every one of them is named rather than left to be noticed. One of the sixteen, (5,0) Twin Fury,
wants an ABILITY id rather than a new row -- it triggers the Felfury record itself -- which
`TRIGGERS` has no way to express today.

WHY THE ASCENSION IDS LIVE IN `note` AND THE SCRIPT NAMES IN A DICT
------------------------------------------------------------------
Plan 6.3 says `Talent` gains exactly three fields, and it keeps `SCRIPT_NAMES` -- a dict keyed by
grid position -- as the way a talent names a C++ script ("SCRIPT_NAMES grows from one entry to
~30"). So neither an Ascension `source` field nor a `script` field is invented here:

  * every talent's `note` begins `src <id>[,<id>...] -- `, listing the Ascension spell ids the
    row is derived from. `selftest()` parses that prefix and cross-checks every id against
    `build/tools/ascension/out/felsworn-family20.json`, so a typo is an import error rather
    than a dangling id in a DBC. This is the one convention this file adds to the house style,
    and it exists because the plan's talent record is a stock clone plus overrides -- there is
    no `source` import path for talents the way `dh_spec.Ability` now has one.
  * `SCRIPT_NAMES_SLAYING` is `dh_talents.SCRIPT_NAMES`'s shape, keyed by (tab, tier, col).

EVERY ID IN SECTION 3.2 IS REAL. Cross-checked against the 858-record dump: all 38 talent spells,
all 17 triggered/second records they reference, and 705143 (Pit Lord's Rage's second buff, which
3.2 does not name) are present. Nothing had to be substituted. Two things the dump says that the
plan does not:

  * 3.2's header reads "28 talents"; the grid it prints has 38 cells. 68 points and the gate row
    `15/25/33/37/44/48/53/59/64/67` -- which is the CUMULATIVE point total through rows 0..9, the
    same convention 3.1 uses -- both reconcile with 38 and with nothing else. The grid is the
    plan; the header count is a typo, and `selftest()` asserts 38/68 against the gate row.
  * Ascension's tab 37 has 39 nodes (`demon-hunter.json`). The 39th is `572889` Oblivion, the
    tab-37 PASSIVE (not the level-70 execute `800215`). 2.1 names the pair as a name trap but
    3.2's grid has no cell for it, so it is dropped here rather than wedged in.

THE NUMBERS, AND WHERE THEY COME FROM
-------------------------------------
Ascension ranks a talent zero, one or two times; this tree ranks it up to five. EVERY per-rank
value below is Ascension's own top value RE-RANKED and NOT MEASURED:

    landing value of rank r of N  =  round(ascension_value * r / N)

stated once here and cited per talent as "re-rank of <n>%". Where Ascension already ships exactly
as many ranks as the tree wants -- Azzinoth's Rage (3) and Pit Lord's Strength (2) -- its ladder
is copied verbatim and the comment says so. No number in this file was tuned against a
measurement, and none should be presented as if it were.

`rank_values` are written ONE BELOW the landing value wherever the ranked cell is an
EffectBasePoints on a donor whose EffectDieSides is 1: `SpellEffectInfo::CalcValue`
(`SpellInfo.cpp:409-437`) does `basePoints += 1` for a die of 1. Every donor's die is stated at
the talent. `ProcChance` is NOT an effect cell -- the three talents that rank a chance write the
landing percentage directly.

Cooldown modifiers (`SPELLMOD_COOLDOWN`, op 11) are milliseconds: -60001 lands -60000 ms.

DEGRADED -- where this file is not section 3.2, with the reason
--------------------------------------------------------------
  (0,0) Spite        the dodge half tops out at 5% where Ascension's rank 2 is 6%, so that the
                     five ranks step by a uniform 1%. The Agility half is exact.
  (4,2) Pit Lord's Rage   ships the Chaos Rush half only. The Felhoof Charge half (`705143`) is
                     a second proc condition on one record and `spell_proc` is per-spell, not
                     per-effect -- plan 4 C7 names this and offers the data alternative taken
                     here.
  (6,1) Nether Champion / (7,2) Perpetual Fury   both read "when Dancing Blades triggers". The
                     cleave (`800598`) is a TRIGGERS row with no family bit, so both proc off the
                     same event Dancing Blades does (a melee-ability crit). For Nether Champion
                     that is exact -- its prerequisite IS Dancing Blades, whose ProcChance is 100.
                     For Perpetual Fury it is not: it has no prerequisite, so a player who skips
                     Dancing Blades still gets the cooldown reduction.
  (6,2) Fury Unleashed    Bladestorm's `SPELL_AURA_ALLOW_ONLY_ABILITY` third effect becomes
                     Ascension's `MOD_INCREASE_SPEED`; Ascension does not lock the bar out.
  (3,1) Annihilan Strike  `TargetAuraState = 23` (plan 2.2, 6.2) is checked by
                     `SpellInfo::CheckTarget`, so it does not only gate the guaranteed crit --
                     it makes the button UNCASTABLE below 75% target health. Ascension's tooltip
                     has no such restriction. The cell is authored because 2.2 asks for it; the
                     cost is named here rather than discovered in game.
  (8,3) Felcaked Blades   Ascension re-applies the Agility scaling on a 1-second aura-23 poll.
                     Plan 4 C6 replaces the poll with a stat-change hook, so the record ships
                     with amount 0 and `spell_fs_stat_spellmod` owns the number.

FLAGGED -- read once the panel opens
------------------------------------
  * `proc_flags` on all sixteen proc talents was read out of `SpellMgr.h:108-146`, not observed.
    Which flag a Felsworn ability actually raises is unverified, exactly as `dh_talents.FLAGGED`
    says of the Demon Hunter's three. Plan 7.4 budgets a debugging pass for this.
  * Four talents need a `spell_proc` row for a crit-only HitMask, which plan 4 C0 says costs one
    `sql.sql` log line per boot at `SpellFamilyName 20`: (5,0) Twin Fury, (5,1) Dancing Blades,
    (6,0) Demonic Machinations, (9,0) Chaotic. Everything else here procs from the DBC record
    alone.
  * Nothing in this file has been rendered by a client. Not one row.
"""

import dataclasses
import json
import os
import re
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))                 # .work/felsworn
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DH_TOOLS = os.path.join(REPO_ROOT, "build", "modules", "mod-demon-hunter", "tools")

sys.path.insert(0, DH_TOOLS)

import dh_talents                                                 # noqa: E402
from acdbc import dbc_tables                                      # noqa: E402  (dh_talents adds
                                                                  # build/tools to sys.path)

# THE SHIM, and it is temporary by construction. `Talent` gains rank_cell_2 / rank_values_2 /
# proc_flags in plan 6.3; until that lands, passing them to the stock dataclass is a TypeError at
# import and this file could not even be selftested. Appending DEFAULTED fields to a frozen
# dataclass is legal (every field the base declares after `donor` already has a default), so the
# subclass is byte-identical in behaviour to what 6.3 will produce. Delete on merge.
_WANTED = {"rank_cell_2", "rank_values_2", "proc_flags"}
if _WANTED <= {f.name for f in dataclasses.fields(dh_talents.Talent)}:
    Talent = dh_talents.Talent
else:
    @dataclass(frozen=True)
    class Talent(dh_talents.Talent):                              # noqa: F811
        """dh_talents.Talent + the three cells plan 6.3 adds.

        rank_cell_2/rank_values_2: the SECOND per-rank cell. Fourteen Felsworn talents are two
        numbers (plan 3.4) and the generator writes exactly one today.
        proc_flags: ProcTypeMask. Non-zero makes `SpellMgr.cpp:2160+` synthesise a proc entry
        from the record alone, which is the whole of plan 4 C0.
        """

        rank_cell_2: str = ""
        rank_values_2: tuple = ()
        proc_flags: int = 0


TAB = "slaying"                     # TalentTab.dbc 413, OrderIndex 1 (plan 6.3)

# Plan 6.3: `METAMORPHOSIS_STANCE` is renamed, the VALUE is unchanged -- form 23's mask bit,
# `1 << (23 - 1)`. Aliased rather than re-derived so the two names cannot drift apart.
INNER_DEMON_STANCE = dh_talents.METAMORPHOSIS_STANCE              # 0x00400000

# `SharedDefines.h:374-378`, via dh_talents: IS_ABILITY|PASSIVE|DO_NOT_DISPLAY|DO_NOT_LOG.
# `AuraEffect::HandleShapeshiftBoosts` (SpellAuraEffects.cpp:1450-1453) SKIPS a talent spell that
# is not PASSIVE|DO_NOT_DISPLAY, so the three form-gated talents at row 9 must carry it.
PASSIVE_ATTRS = dh_talents.PASSIVE_ATTRS                          # 0x1D0
NOT_SHAPESHIFTED = dh_talents.NOT_SHAPESHIFTED                    # 0x00010000


# =============================================================================================
# THE TWO BIT TABLES -- PROVISIONAL, AND THAT IS THE POINT
# =============================================================================================
#
# `SpellInfo::IsAffected` (SpellInfo.cpp:1325-1337) is the only mechanism by which a talent
# reaches an ability without C++: same family, overlapping mask. dh_talents DERIVES its ability
# bits from `dh_donors.OVERRIDES` and never copies them, because a bit that moves in dh_donors
# must move at every talent keyed on it. The Felsworn `dh_donors` does not exist yet, so this
# fragment cannot derive; it names the bits symbolically and allocates them by a RULE the merge
# can reproduce, so the merge is a rename and not a renumber:
#
#     word 1 (the baseline kit)  bit = the ability's `ABILITY_BLOCKS` index for blocks 0-9;
#                                bit = 10 + `SINGLES_ORDER` index for the one-row customs.
#                                Both orders are plan 5's and both are append-only there.
#     word 3 (talent-granted)    EIGHT BITS PER TREE, in tab order: Demonology 0-7, Slaying
#                                8-15, Felblood 16-23, then position within the tree's block in
#                                TALENTS declaration order.
#
# Word 3 is shared by all three trees and the three files are written apart, so the per-tree
# block is what keeps them from colliding: talents_demonology.py:1524-1527 asserts its eight
# actives are inside 0x01-0x80 and talents_felblood.py:183-190 takes 16-23, which leaves 8-15 and
# only 8-15 for this file. Demonology has EIGHT granted actives, not six, so its block is full
# and nothing here may start below bit 8. Nothing outside this file may key on the LITERALS; key
# on the names.
KIT_BIT = {
    "twin_slice":         1 << 0,      # ABILITY_BLOCKS 0
    "sargeron_smite":     1 << 1,      # ABILITY_BLOCKS 1
    "chaos_rush":         1 << 3,      # ABILITY_BLOCKS 3
    "annihilation_crit":  1 << 20,     # SINGLES_ORDER 10 -- 803904, the guaranteed-crit cooldown
    "sunder":             1 << 23,     # SINGLES_ORDER 13
    "blood_of_mannoroth": 1 << 24,     # SINGLES_ORDER 14
}

# The six talents in this tree with `Talent.dbc Flags = 1`. A granted active is a spell like any
# other and needs its own bit, or no later talent can name it -- which is exactly what six
# talents below do (Chaos Soldier and Fel Instincts both modify Azzinoth's Assault, Burning Rage
# modifies Immolation Aura, Glaiving modifies Fury Unleashed).
SLAYING_BIT = {
    "azzinoths_assault":    1 << 8,    # (1,1)
    "immolation_aura":      1 << 9,    # (2,1)
    "annihilan_strike":     1 << 10,   # (3,1)
    "felhoof_charge":       1 << 11,   # (5,3)
    "fury_unleashed":       1 << 12,   # (6,2)
    "fury_of_the_illidari": 1 << 13,   # (10,1)
}

# ProcTypeMask literals, `SpellMgr.h:113-146`. Named so the intent reads as English at the talent
# and so the FLAGGED caveat above has something to point at.
PROC_MELEE_AUTO = 0x00000004          # PROC_FLAG_DONE_MELEE_AUTO_ATTACK
PROC_MELEE_ABILITY = 0x00000010       # PROC_FLAG_DONE_SPELL_MELEE_DMG_CLASS
PROC_CAST_NONE_POS = 0x00000400       # PROC_FLAG_DONE_SPELL_NONE_DMG_CLASS_POS -- Chaos Rush is
                                      # a targetless dash that deals no damage in this port
                                      # (plan 2.2), so a done-damage flag can never fire on it


# =============================================================================================
# THE TREE -- 38 talents, 68 points
# =============================================================================================
#
# row | col 0                 | col 1                 | col 2                | col 3
# ----+-----------------------+-----------------------+----------------------+------------------
#  0  | Spite               5 | Slice & Dice        5 | Chaos Soldier      5 |
#  1  | Fel Instincts       3 | Azzinoth's Assault 1* | Burning Rage       3 | Azzinoth's Rage  3
#  2  | A Thousand Cuts    3^ | Immolation Aura    1* | Consumed By Fel    2 | Scars of the Past 2
#  3  | Fel Blades         1^ | Annihilan Strike   1* | Reachwalker        1 | Unbound          1
#  4  | Scars of Suffering  1 | You Cheat, Gul'dan! 2 | Pit Lord's Rage    1 | Reckless Assault 3
#  5  | Twin Fury           1 | Dancing Blades      1 | Fel Haze           1 | Felhoof Charge  1*
#  6  | Demonic Machinat.   1 | Nether Champion    1^ | Fury Unleashed    1* | Pit Lord's Str.  2
#  7  | Azzinoth's Battery  2 | Glaiving           3^ | Perpetual Fury     1 |
#  8  | Legionfall          2 | Whirling Vengeance 1^ | Felguard           1 | Felcaked Blades  1
#  9  | Chaotic             1 | True Self           1 | Blighted Strikes   1 |
# 10  |                       | Fury of the Illid. 1* |                      |
#
# cumulative points through each row, recomputed from `ranks` by selftest() and checked against
# plan 3.2's own gate row -- they agree exactly, which is the strongest confirmation available
# that no rank count here has drifted from the plan:
#   r0 15 | r1 25 | r2 33 | r3 37 | r4 44 | r5 48 | r6 53 | r7 59 | r8 64 | r9 67 | r10 68
#   gate      5   |   10  |   15  |   20  |   25  |   30  |   35  |   40  |   45  |   50

TALENTS_SLAYING = (

    # ---------------------------------------------------------------------------------- row 0 --

    # -- 0/0 -- Spite ..................................... donor 31216 Sinister Calling (fam 8)
    #
    # Ascension ships two ranks of one record: `800188` is aura 137 MOD_TOTAL_STAT_PERCENTAGE
    # misc 1 (Agility) at bp 7 plus aura 49 MOD_DODGE_PERCENT at bp 2; `803840` is bp 14 / bp 5.
    # 31216 already carries the Agility half at exactly the five-rank ladder Ascension's rank 2
    # ends on -- stock 31216-31220 is bp 2/5/8/11/14, i.e. 3/6/9/12/15%. Only its SECOND effect
    # has to move: aura 108 SPELLMOD_EFFECT2 becomes aura 49, which needs no misc value at all.
    # Both donor effects carry DieSides 1.
    Talent(TAB, 0, 0, 5, "Spite", 31216,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 5, 8, 11, 14),       # DieSides 1 -> lands 3/6/9/12/15 % Agility
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(0, 1, 2, 3, 4),       # DieSides 1 -> lands 1/2/3/4/5 % dodge
           overrides={
               "EffectAura_2": 49,              # MOD_DODGE_PERCENT, from 108 ADD_PCT_MODIFIER.
                                                # The donor's EffectMiscValue_2 (12,
                                                # SPELLMOD_EFFECT2) is left alone rather than
                                                # zeroed: aura 49 never reads a misc value, and
                                                # restating a dead cell is one more place for it
                                                # to disagree with Spell.dbc.
               "EffectSpellClassMaskB_1": 0,    # the donor's Backstab/Hemorrhage word-2 bits
               "Description_Lang_enUS":
                   "Increases your Agility by $s1% and your dodge chance by $s2%.",
           },
           note="src 800188,803840 -- Spite R1/R2. Agility half is exact at rank 5 (Ascension's "
                "own 15%); the dodge half is trimmed 6% -> 5% for a uniform 1%/rank step"),

    # -- 0/1 -- Slice & Dice .............................. donor 49226 Nerves of Cold Steel
    #
    # Ascension `704361`/`707845`: aura 122 MOD_OFFHAND_DAMAGE_PCT at bp 24/49 (+25/+50%) and
    # aura 107 SPELLMOD_COST at bp -6/-11 (-5/-10 Energy on Twin Slice, which costs 45).
    # 49226's aura-122 half is the only stock one that sits next to a second self aura, and the
    # rogue Dual Wield Specialization ladder (13715-13852, bp 9/19/29/39/49) is exactly the
    # five-rank shape whose top is Ascension's rank 2. The donor's aura 54 MOD_HIT_CHANCE becomes
    # the cost modifier: same effect slot, same DieSides 1, no effect authored from nothing.
    # `EquippedItemClass 2 / subclass 41105` (one-handed weapons) is cleared by dh_talents.ALWAYS
    # -- left alone it would make the whole talent inert while a glaive is in the off hand.
    Talent(TAB, 0, 1, 5, "Slice & Dice", 49226,
           rank_cell="EffectBasePoints_2",
           rank_values=(9, 19, 29, 39, 49),     # DieSides 1 -> lands 10/20/30/40/50 % off-hand
           rank_cell_2="EffectBasePoints_1",
           rank_values_2=(-3, -5, -7, -9, -11),  # DieSides 1 -> lands -2/-4/-6/-8/-10 Energy
           overrides={
               "EffectAura_1": 107,             # ADD_FLAT_MODIFIER, from 54 MOD_HIT_CHANCE
               "EffectMiscValue_1": 14,         # SPELLMOD_COST (SpellDefines.h:92)
               "EffectSpellClassMaskA_1": KIT_BIT["twin_slice"],
               "Description_Lang_enUS":
                   "Increases your off-hand weapon damage by $s2% and reduces the Energy cost "
                   "of your Twin Slice by $s1.",
           },
           note="src 704361,707845 -- Slice & Dice R1/R2; both halves re-ranked to five, both "
                "tops are Ascension's own rank 2 (+50% off-hand, -10 Energy)"),

    # -- 0/2 -- Chaos Soldier ............................. donor 13733 Puncturing Wounds
    #
    # Ascension `560057` is one effect: aura 107 misc 7 SPELLMOD_CRITICAL_CHANCE at bp 4, i.e.
    # +5% crit on Azzinoth's Assault and Sargeron Smite. FLAT, not percent -- it adds crit chance
    # to two abilities rather than to the character. 13733's second effect is the same aura aimed
    # at Mutilate through the SECOND mask word and has to go, mask and all, or it lands on
    # whatever Felsworn spells ever take word-2 bits (the second records).
    # THE TWO ABILITIES LIVE IN DIFFERENT MASK WORDS -- Sargeron Smite is baseline (word 1),
    # Azzinoth's Assault is granted by (1,1) (word 3) -- and ONE effect still reaches both:
    # `IsAffected` tests `!(familyFlags & SpellFamilyFlags)`, `flag96::operator&` ANDs all three
    # words and `flag96::operator bool` (`Util.h:556-559`) is true if ANY of them survives. Five
    # talents in this tree rely on that; it is checked, not assumed.
    Talent(TAB, 0, 2, 5, "Chaos Soldier", 13733,
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 1, 2, 3, 4),         # DieSides 1 -> lands 1/2/3/4/5 %
           overrides={
               "EffectSpellClassMaskA_1": KIT_BIT["sargeron_smite"],
               "EffectSpellClassMaskC_1": SLAYING_BIT["azzinoths_assault"],
               "Effect_2": 0,                   # the Mutilate half
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "EffectSpellClassMaskB_2": 0,
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Azzinoth's Assault and "
                   "Sargeron Smite by $s1%.",
           },
           note="src 560057 -- re-rank of Ascension's single +5% over five ranks"),

    # ---------------------------------------------------------------------------------- row 1 --

    # -- 1/0 -- Fel Instincts ............................. donor 17793 Improved Shadow Bolt
    #
    # Ascension `560645` is two effects: aura 42 PROC_TRIGGER_SPELL into `560646` (aura 138
    # MOD_MELEE_HASTE at bp 19 = +20%, DurationIndex 28 = 5000 ms) and aura 108 SPELLMOD_DAMAGE
    # at bp 9 = +10%. 17793 is that exact pair in stock, which is why it is here and not 18427.
    # THE HASTE BUFF STAYS FLAT at Ascension's +20% across all three ranks: it lives in a TRIGGERS
    # row, not in a cell of this record, so the one-per-rank-cell limit is not what freezes it --
    # ranking it would need aura 231 PROC_TRIGGER_SPELL_WITH_VALUE and a fourth rewrite.
    # `EffectTriggerSpell_1` is deliberately absent: only the generator knows the trigger row's id.
    Talent(TAB, 1, 0, 3, "Fel Instincts", 17793,
           rank_cell="EffectBasePoints_2",
           rank_values=(2, 6, 9),               # DieSides 1 -> lands 3/7/10 % damage
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "ProcChance": 100,               # the donor's 20 is Shadow Bolt's, not this
               "EffectSpellClassMaskB_1": 0,    # the donor's Shadow Bolt bit, second word
               "EffectSpellClassMaskC_1": SLAYING_BIT["azzinoths_assault"],
               "EffectSpellClassMaskC_2": SLAYING_BIT["azzinoths_assault"],
               "Description_Lang_enUS":
                   "Increases the damage of your Azzinoth's Assault by $s2% and causes it to "
                   "increase your melee haste by 20% for 5 sec.",
           },
           note="src 560645,560646 -- damage half re-ranked to three (top = Ascension's 10%); "
                "the +20%/5 s haste buff is a TRIGGERS row and is flat at every rank"),

    # -- 1/1 -- Azzinoth's Assault ........................ donor 1329 Mutilate (family 8)
    #
    # THE DUAL-WIELD SHELL SHAPE, in stock, ready to use: 1329's Effect_2 and Effect_3 are two
    # TRIGGER_SPELLs into `5374`/`27576`, the main-hand and off-hand halves. Ascension `801904` is
    # the same picture one effect id further on -- Effect 142 TRIGGER_SPELL_WITH_VALUE into
    # `520262`/`572585`, both bp-0 `SPELL_EFFECT_NORMALIZED_WEAPON_DMG` shells fed by the
    # parent's value (plan 7.6 is the risk that that propagation differs; it is the same risk
    # Twin Slice runs). So Effect_2/_3 move 64 -> 142 and the two trigger cells stay unwritten
    # for TRIGGERS to fill. Effect_1 (ADD_COMBO_POINTS, SharedDefines.h:846) goes: combo points
    # are target-bound and this class has none (plan 4 C1).
    # LEVEL SCALING IS ASCENSION'S OWN LADDER, not a curve invented here: bp 14 at level 11
    # (`801904`) to bp 90 at level 60 (`803475`) is +1.55 per level. `CalcValue` subtracts
    # `max(BaseLevel, SpellLevel)` before multiplying (`SpellInfo.cpp:417-427`), so both are set
    # to 11 or the ramp starts from the donor's level 40 and the ability is dead below it. That
    # is not a new trick here: `dhspells.py:859-869` already writes the parent's learn level onto
    # every second record for exactly this reason, and says so at length.
    # Felfury is charged by the C1 script from the spender set in `dh_progression.h`, not by a
    # cell on this record -- there is no "costs N stacks" column in Spell.dbc.
    Talent(TAB, 1, 1, 1, "Azzinoth's Assault", 1329, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["azzinoths_assault"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,   # 0x50010 -> 0x40010; the donor greys
                                                           # out in any form and Inner Demon is
                                                           # the form this class lives in
               "Effect_1": 0,                   # SPELL_EFFECT_ADD_COMBO_POINTS
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "Effect_2": 142,                 # TRIGGER_SPELL_WITH_VALUE, from 64 TRIGGER_SPELL
               "Effect_3": 142,
               "EffectBasePoints_2": 14,        # DieSides 1 -> 15 added to each weapon's swing
               "EffectBasePoints_3": 14,
               "EffectDieSides_2": 1,
               "EffectDieSides_3": 1,
               "EffectRealPointsPerLevel_2": 1.55,
               "EffectRealPointsPerLevel_3": 1.55,
               "BaseLevel": 11,
               "SpellLevel": 11,
               "ManaCost": 20,                  # Energy; PowerType 3 comes from ALWAYS
               "Description_Lang_enUS":
                   "Consumes 2 Felfury. Strike an enemy with both weapons for weapon damage "
                   "plus $s2.",
           },
           note="src 801904,520262,572585,803470,803475 -- R1 numbers, R1->R7 slope for the "
                "per-level ramp; the two shells are TRIGGERS rows"),

    # -- 1/2 -- Burning Rage .............................. donor 37441 Improved Arcane Blast
    #
    # Ascension `707907` is three effects, all aura 108: misc 0 at bp 19 (+20% damage), misc 22
    # SPELLMOD_DOT at bp 19, and misc 14 at bp -21 (-20% cost). 37441 is the stock damage+cost
    # pair on one record. The DOT third is dropped rather than frozen: neither Sunder nor
    # Immolation Aura has a DOT component after plan 2.2 deletes Immolation Aura's aura-226 half.
    # Attributes 192 (PASSIVE|DO_NOT_DISPLAY) is written up to the canonical passive set.
    Talent(TAB, 1, 2, 3, "Burning Rage", 37441,
           rank_cell="EffectBasePoints_2",
           rank_values=(6, 12, 19),             # DieSides 1 -> lands 7/13/20 % damage
           rank_cell_2="EffectBasePoints_1",
           rank_values_2=(-8, -14, -21),        # DieSides 1 -> lands -7/-13/-20 % cost
           overrides={
               "Attributes": PASSIVE_ATTRS,
               "EffectSpellClassMaskA_1": KIT_BIT["sunder"],
               "EffectSpellClassMaskB_1": 0,    # the donor's Arcane Blast bit, second word
               "EffectSpellClassMaskC_1": SLAYING_BIT["immolation_aura"],
               "EffectSpellClassMaskA_2": KIT_BIT["sunder"],
               "EffectSpellClassMaskC_2": SLAYING_BIT["immolation_aura"],
               "Description_Lang_enUS":
                   "Increases the damage of your Sunder and Immolation Aura by $s2% and reduces "
                   "their Energy cost by $s1%.",
           },
           note="src 707907 -- both halves re-ranked to three from Ascension's single 20%; its "
                "third effect (SPELLMOD_DOT) has nothing left to modify and is dropped"),

    # -- 1/3 -- Azzinoth's Rage ........................... donor 29140 Vitality (family 0)
    #
    # THE ONE TALENT IN THIS TREE WHOSE LADDER IS COPIED AND NOT RE-RANKED: Ascension ships
    # exactly three ranks, `804611`/`807901`/`807914`, at aura 280 MOD_ARMOR_PENETRATION_PCT
    # bp 9/19/29 and aura 240 MOD_EXPERTISE bp 3/7/11. Both columns below are those cells.
    # 29140 is the only stock talent shape with an expertise effect sitting beside two spare stat
    # auras; its Stamina effect becomes the armour penetration and its Strength effect goes.
    Talent(TAB, 1, 3, 3, "Azzinoth's Rage", 29140,
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19, 29),             # DieSides 1 -> lands 10/20/30 % armour pen
           rank_cell_2="EffectBasePoints_3",
           rank_values_2=(3, 7, 11),            # DieSides 1 -> lands 4/8/12 expertise
           overrides={
               "EffectAura_1": 280,             # MOD_ARMOR_PENETRATION_PCT, from 137
                                                # MOD_TOTAL_STAT_PERCENTAGE. The donor's misc 2
                                                # (STAT_STAMINA) stays: aura 280 reads no misc.
               "Effect_2": 0,                   # aura 137 misc 0, the Strength half
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Increases your armor penetration by $s1% and your expertise by $s3.",
           },
           note="src 804611,807901,807914 -- Ascension's own three ranks, both columns verbatim"),

    # ---------------------------------------------------------------------------------- row 2 --

    # -- 2/0 -- A Thousand Cuts ........................... donor 12319 Flurry (family 0)
    #
    # Ascension `704610` is one aura-42 effect into `520262`, Azzinoth's Assault's OWN main-hand
    # shell, at ProcChance 30. So the extra swing is free data once the proc entry exists, and the
    # rank cell is the CHANCE rather than an amount -- which is why `ProcChance` is the rank cell
    # here and why these three values are the landing percentages with no die adjustment.
    # THE MASK IS NOT OPTIONAL. `SpellMgr::LoadSpellProcs` (:2200-2210) only copies
    # `SpellFamilyName` onto the generated entry when the effect's mask is non-zero; 12319's is
    # zero, so an unmasked clone would proc off everything the ProcTypeMask allows.
    Talent(TAB, 2, 0, 3, "A Thousand Cuts", 12319, prereq=(1, 0, 2),
           rank_cell="ProcChance",
           rank_values=(10, 20, 30),            # a chance column, NOT an effect: no +1 die
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "EffectSpellClassMaskC_1": SLAYING_BIT["azzinoths_assault"],
               "Description_Lang_enUS":
                   "Your Azzinoth's Assault has a $h% chance to strike an additional time with "
                   "your main-hand weapon.",
           },
           note="src 704610,520262 -- re-rank of Ascension's own ProcChance 30 over three ranks; "
                "the trigger is Azzinoth's Assault's main-hand shell, a TRIGGERS row"),

    # -- 2/1 -- Immolation Aura ........................... donor 50589 Immolation Aura (warlock)
    #
    # The stock demon-form Immolation Aura is the same spell one class over: aura 23
    # PERIODIC_TRIGGER_SPELL into `50590` every 1000 ms. Ascension `800207` uses aura 227
    # (PERIODIC_TRIGGER_SPELL_WITH_VALUE) so its seven ranks can feed one bp-0 tick record
    # `800208`; a talent is never ranked (plan 3.4), so aura 23 with the damage ON the tick row is
    # the cheaper shape and the one the donor already has.
    # THREE CELLS ARE ASCENSION'S AND ONE IS ARITHMETIC:
    #   * PowerType -2 POWER_HEALTH -> 3 and the cost flat, per plan 2.2. 15 Energy is `501270`'s
    #     own cost at its level 22 -- row 2 of a tree is reached at about level 20 (one talent
    #     point per level from 10), so that is the rank a player actually meets here.
    #   * DurationIndex 3 = 60000 ms, read out of SpellDuration.dbc; Ascension's own. The donor's
    #     row 8 is 15000.
    #   * the donor's 30 s RecoveryTime goes: no Ascension rank has a cooldown.
    #   * ShapeshiftMask 0x200000 (the WARLOCK's form 22) and ManaCostPct 64 are cleared by
    #     ALWAYS. Either left alone makes the button uncastable.
    Talent(TAB, 2, 1, 1, "Immolation Aura", 50589, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["immolation_aura"],
               "Attributes": 0x10,              # IS_ABILITY only. The donor's whole Attributes
                                                # word is NOT_SHAPESHIFTED and nothing else, and
                                                # clearing it would leave the record at 0.
               "ManaCost": 15,
               "RecoveryTime": 0,
               "DurationIndex": 3,              # 60000 ms
               "SchoolMask": 4,                 # Fire -- the donor's already, restated because
                                                # Ascension's `800207` agrees and the tick row
                                                # must match it
               "Effect_3": 0,                   # aura 77 MECHANIC_IMMUNITY, warlock plumbing
               "EffectAura_3": 0,
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectMiscValue_3": 0,
               "ImplicitTargetA_3": 0,
               "StartRecoveryCategory": 133,    # the house GCD, from the donor's 133/1500
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Wreathe yourself in fel fire for $d, dealing Fire damage to nearby enemies "
                   "every 1 sec.",
           },
           note="src 800207,800208,501270 -- R1 shape, R2's cost, R1's 60 s duration; the tick "
                "record (aura 344 -> 99 MOD_ATTACK_POWER, plan 2.2) is a TRIGGERS row"),

    # -- 2/2 -- Consumed By Fel ........................... donor 18427 Aggression (family 8)
    #
    # Ascension `300485` e1 is aura 108 with EffectMiscValue 19 at bp -26. SpellModOp 19 is
    # SPELLMOD_ACTIVATION_TIME, and on a periodic aura that is the TICK INTERVAL: `AuraEffect::
    # CalculatePeriodic` applies it to `m_amplitude` at `SpellAuraEffects.cpp:646`. So "increases
    # the tick rate" is one cell, not a script. No stock spell carries misc 19, so the op is
    # written onto the cleanest single-effect aura-108 donor in the file (the same one three
    # Demon Hunter talents use) rather than a multi-effect one that would need zeroing.
    Talent(TAB, 2, 2, 2, "Consumed By Fel", 18427,
           rank_cell="EffectBasePoints_1",
           rank_values=(-14, -26),              # DieSides 1 -> lands -13/-25 % tick interval
           overrides={
               "EffectMiscValue_1": 19,         # SPELLMOD_ACTIVATION_TIME, from 0 SPELLMOD_DAMAGE
               "EffectSpellClassMaskA_1": 0,    # the donor's Sinister Strike/Backstab bits
               "EffectSpellClassMaskC_1": SLAYING_BIT["immolation_aura"],
               "Description_Lang_enUS":
                   "Your Immolation Aura deals damage $s1% more often.",
           },
           note="src 300485 -- re-rank of Ascension's single -25% over two ranks"),

    # -- 2/3 -- Scars of the Past ......................... donor 17793 Improved Shadow Bolt
    #
    # Ascension `520805`: aura 42 into `520806` (a heal, `$m1 + $STA*0.2 + $AP*0.33`) plus aura
    # 107 SPELLMOD_COST at bp -6, i.e. -5 Energy on Chaos Rush. Same donor as (1,0) for the same
    # reason -- proc effect beside a modifier effect -- with the modifier moved from aura 108 to
    # aura 107 because Ascension's is flat Energy and not a percentage.
    # The heal's stat coefficients are `spell_bonus_data` on the TRIGGERS row (plan 6.4.4); they
    # do not survive a clone and they are not cells on this record.
    Talent(TAB, 2, 3, 2, "Scars of the Past", 17793,
           rank_cell="EffectBasePoints_2",
           rank_values=(-4, -6),                # DieSides 1 -> lands -3/-5 Energy
           proc_flags=PROC_CAST_NONE_POS,
           overrides={
               "ProcChance": 100,               # the donor's 20 is Shadow Bolt's
               "EffectSpellClassMaskA_1": KIT_BIT["chaos_rush"],
               "EffectSpellClassMaskB_1": 0,    # the donor's Shadow Bolt bit, second word
               "EffectAura_2": 107,             # ADD_FLAT_MODIFIER, from 108 ADD_PCT_MODIFIER
               "EffectMiscValue_2": 14,         # SPELLMOD_COST
               "EffectSpellClassMaskA_2": KIT_BIT["chaos_rush"],
               "Description_Lang_enUS":
                   "Reduces the Energy cost of your Chaos Rush by $s2, and casting it heals you.",
           },
           note="src 520805,520806 -- cost half re-ranked to two (top = Ascension's -5); the "
                "heal is a TRIGGERS row and its AP/STA coefficients are spell_bonus_data"),

    # ---------------------------------------------------------------------------------- row 3 --

    # -- 3/0 -- Fel Blades ................................ donor 12319 Flurry (family 0)
    #
    # Ascension `300484` is a bare aura-42 proc into `300482`: aura 101 MOD_RESISTANCE_PCT misc 1
    # (armour) at bp -5, DurationIndex 1 = 10000 ms, stacking. All of that is the TRIGGERS row's;
    # the talent record is the proc and its mask, which is why one rank and no rank cell.
    Talent(TAB, 3, 0, 1, "Fel Blades", 12319, prereq=(2, 0, 2),
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "EffectSpellClassMaskC_1": SLAYING_BIT["azzinoths_assault"],
               "Description_Lang_enUS":
                   "Damage dealt by your Azzinoth's Assault reduces the enemy's armor by 4% for "
                   "10 sec, stacking up to 3 times.",
           },
           note="src 300484,300482 -- the debuff, its stack cap and its 10 s are TRIGGERS cells"),

    # -- 3/1 -- Annihilan Strike .......................... donor 1329 Mutilate (family 8)
    #
    # The same shell shape as (1,1), pointed at Ascension's OTHER pair of halves: `801903` fires
    # `801913`/`801914`, whose effect is 31 SPELL_EFFECT_WEAPON_PERCENT_DAMAGE rather than a flat
    # addition -- so the value the parent passes is a PERCENTAGE of weapon damage, 145 at rank 1.
    # Ascension ranks that percentage (bp 144 at level 16 -> 179 at level 52, `572804`), which is
    # +0.97 a level, so the same BaseLevel/SpellLevel + RealPointsPerLevel treatment applies.
    # `CategoryRecoveryTime 10000` is shared across all seven Ascension ranks; a one-rank talent
    # has nothing to share it with and `dhspells.TALENT_BASE` zeroes the category anyway, so it
    # becomes a plain 10 s RecoveryTime.
    # TargetAuraState 23 -- see DEGRADED. It is what plan 2.2 asks for and it costs more than the
    # plan says it does.
    Talent(TAB, 3, 1, 1, "Annihilan Strike", 1329, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["annihilan_strike"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,
               "TargetAuraState": 23,           # AURA_STATE_HEALTH_ABOVE_75_PERCENT
                                                # (SharedDefines.h:1303), read by
                                                # SpellInfo::CheckTarget
               "Effect_1": 0,                   # SPELL_EFFECT_ADD_COMBO_POINTS
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "ImplicitTargetA_1": 0,
               "Effect_2": 142,                 # TRIGGER_SPELL_WITH_VALUE
               "Effect_3": 142,
               "EffectBasePoints_2": 144,       # DieSides 1 -> 145% weapon damage per weapon
               "EffectBasePoints_3": 144,
               "EffectDieSides_2": 1,
               "EffectDieSides_3": 1,
               "EffectRealPointsPerLevel_2": 0.97,
               "EffectRealPointsPerLevel_3": 0.97,
               "BaseLevel": 16,
               "SpellLevel": 16,
               "ManaCost": 40,
               "RecoveryTime": 10000,
               "Description_Lang_enUS":
                   "Generates 2 Felfury. Unleash a devastating attack, dealing $s2% weapon "
                   "damage with both weapons. Guaranteed to critically strike.",
           },
           note="src 801903,801913,801914,572804 -- R1 numbers, R1->R7 slope; the guaranteed "
                "crit is plan 4 C7 (UnitScript, no spell_script_names row)"),

    # -- 3/2 -- Reachwalker ............................... donor 12319 Flurry (family 0)
    #
    # Ascension `705135` procs `680318`, whose only effect is 165 -- an Ascension effect id above
    # `TOTAL_SPELL_EFFECTS`, which `SpellMgr.cpp:3039` ASSERTs on and which therefore CRASHES
    # worldserver at boot if imported (plan 4 C10). Plan 4 C4 rewrites it as
    # `SPELL_EFFECT_DUMMY` with EffectMiscValue = the target spell and EffectBasePoints = the
    # delta in ms, read back by one shared script. That rewrite lands on the TRIGGERS row, so the
    # `spell_fs_modify_cooldown` binding does too -- see the header note about rank-scoped
    # emission.
    # Felhoof Charge is a rank chain (`800204`/`803484`/`803485`), and a cooldown is per spell id,
    # so the script must walk it (plan 4 C4's first trap).
    Talent(TAB, 3, 2, 1, "Reachwalker", 12319,
           proc_flags=PROC_CAST_NONE_POS,
           overrides={
               "EffectSpellClassMaskA_1": KIT_BIT["chaos_rush"],
               "Description_Lang_enUS":
                   "Casting Chaos Rush reduces the cooldown of your Felhoof Charge by 2 sec.",
           },
           note="src 705135,680318 -- -2000 ms is Ascension's own; effect 165 is out of range "
                "and becomes the C4 dummy on the TRIGGERS row"),

    # -- 3/3 -- Unbound ................................... donor 13712 Lightning Reflexes
    #
    # FREE, exactly as plan 3.2 says, but not by import: Ascension `574153` e1/e2 are already
    # aura 220 MOD_RATING_FROM_STAT at misc 224 and misc 4, and both cells transcribe onto a
    # stock donor with two self auras. `Player::UpdateRating` (`PlayerUpdates.cpp:611-623`) reads
    # MiscValue as a COMBAT RATING MASK and MiscValueB as the `Stats` index:
    #     4   = 1 << CR_DODGE
    #     224 = 1 << CR_HIT_MELEE | CR_HIT_RANGED | CR_HIT_SPELL
    #     MiscValueB 1 = STAT_AGILITY
    # e0 (aura 4 DUMMY, misc 1792) is dropped -- it is in no tooltip and implements nothing.
    # NOTE THE ORDER TRAP: Ascension's description reads "dodge by $s1%... hit rating by $s2%"
    # but its $s1 effect carries the HIT mask and $s2 the DODGE mask. The masks win; the numbers
    # below are 15% of Agility to dodge and 6% to hit, which is what the data says.
    Talent(TAB, 3, 3, 1, "Unbound", 13712,
           overrides={
               "EffectAura_1": 220,             # MOD_RATING_FROM_STAT, from 49 MOD_DODGE_PERCENT
               "EffectBasePoints_1": 14,        # DieSides 1 -> 15% of Agility
               "EffectMiscValue_1": 4,          # CR_DODGE
               "EffectMiscValueB_1": 1,         # STAT_AGILITY
               "EffectAura_2": 220,             # from 138 MOD_MELEE_HASTE
               "EffectBasePoints_2": 5,         # DieSides 1 -> 6% of Agility
               "EffectMiscValue_2": 224,        # the three hit ratings
               "EffectMiscValueB_2": 1,
               "Description_Lang_enUS":
                   "Increases your dodge rating by $s1% of your Agility and your hit rating by "
                   "$s2% of your Agility.",
           },
           note="src 574153 -- both amounts are Ascension's own cells; only the donor changes"),

    # ---------------------------------------------------------------------------------- row 4 --

    # -- 4/0 -- Scars of Suffering ........................ donor 12319 Flurry (family 0)
    #
    # Ascension `570158` procs `570159`, aura 165 MELEE_ATTACK_POWER_ATTACKER_BONUS at bp 4 plus
    # `$AGI*0.15`, DurationIndex 1 = 10000 ms -- a debuff that raises EVERY attacker's melee
    # attack power against the target, which is what "your allies' attack power" means and which
    # is legal WotLK data. The Agility coefficient is `spell_bonus_data` on the TRIGGERS row.
    Talent(TAB, 4, 0, 1, "Scars of Suffering", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "EffectSpellClassMaskC_1": SLAYING_BIT["azzinoths_assault"],
               "Description_Lang_enUS":
                   "Your Azzinoth's Assault scars the enemy, increasing the attack power of all "
                   "attackers against them for 10 sec.",
           },
           note="src 570158,570159 -- aura 165 is in range and needs no rewrite"),

    # -- 4/1 -- You Cheat, Gul'dan! ....................... donor 11170 Shatter (family 3)
    #
    # Ascension `705127` is two aura-112 OVERRIDE_CLASS_SCRIPTS effects, misc 20000 at amount 0
    # and misc 20001 at bp 49. Only the second carries a number, so only the second is kept.
    # KEEPING AURA 112 IS THE SAFE CHOICE, not laziness: `AuraEffect::HandleNoImmediateEffect`
    # (`SpellAuraEffects.cpp:177`) means the aura does nothing on application, and every consumer
    # is a `switch (GetMiscValue())` with no case for the 20000 range (e.g. `Unit.cpp:9508-9520`)
    # -- so the record is INERT until plan 4 C7's UnitScript reads it, instead of silently
    # applying +50% crit damage against everything. Those hooks are registered in code and take
    # no `spell_script_names` row (plan 6.5), which is why this talent is absent from
    # SCRIPT_NAMES_SLAYING.
    # An EMPTY effect mask is deliberate: `IsAffected` returns true for an empty familyFlags
    # (`SpellInfo.cpp:1333`), so family 16 with no mask is "every Felsworn spell", which is what
    # a flat crit-damage bonus against a health threshold should be.
    Talent(TAB, 4, 1, 2, "You Cheat, Gul'dan!", 11170,
           rank_cell="EffectBasePoints_1",
           rank_values=(24, 49),                # DieSides 1 -> lands 25/50 % crit damage
           overrides={
               "EffectMiscValue_1": 20001,      # Ascension's own script id, kept as the C7 key
               "EffectSpellClassMaskA_1": 0,    # the donor's frost-spell mask
               "Description_Lang_enUS":
                   "Increases your critical strike damage by $s1% against enemies above 75% "
                   "health.",
           },
           note="src 705127 -- re-rank of Ascension's single +50% over two ranks; its misc-20000 "
                "effect carries amount 0 and is dropped"),

    # -- 4/2 -- Pit Lord's Rage ........................... donor 12319 Flurry (family 0)
    #
    # Ascension `705141` has TWO proc conditions on one record -- Chaos Rush grants `705142`
    # (aura 79 MOD_DAMAGE_PERCENT_DONE misc 1 at bp 14, physical, 10 s) and Felhoof Charge grants
    # `705143` (crit chance, DurationIndex 8 = 15000 ms). `spell_proc` is keyed per SPELL, not
    # per effect, so the pair cannot both be data. Plan 4 C7 offers the alternative taken here:
    # ship the Chaos Rush half. The Felhoof Charge half needs `SpellScript::AfterCast` on the
    # ability record and is not shipped.
    Talent(TAB, 4, 2, 1, "Pit Lord's Rage", 12319,
           proc_flags=PROC_CAST_NONE_POS,
           overrides={
               "EffectSpellClassMaskA_1": KIT_BIT["chaos_rush"],
               "Description_Lang_enUS":
                   "Casting Chaos Rush increases your Physical damage done by 15% for 10 sec.",
           },
           note="src 705141,705142 -- 705143, the Felhoof Charge half, is real (dur 15 s) and is "
                "deliberately not shipped; see DEGRADED"),

    # -- 4/3 -- Reckless Assault .......................... donor 11170 Shatter (family 3)
    #
    # Ascension `804610`, one aura-112 effect at misc 20007, bp 14. Same carrier argument as
    # (4,1); the predicate is `victim->HasAuraType(SPELL_AURA_MOD_DECREASE_SPEED)` and lives in
    # the C7 UnitScript. Unlike (4,1) the mask is NOT empty -- Ascension names three abilities
    # and two of them are this tree's granted actives, so the mask spans word 1 and word 3.
    Talent(TAB, 4, 3, 3, "Reckless Assault", 11170,
           rank_cell="EffectBasePoints_1",
           rank_values=(4, 9, 14),              # DieSides 1 -> lands 5/10/15 %
           overrides={
               "EffectMiscValue_1": 20007,      # Ascension's own script id, kept as the C7 key
               "EffectSpellClassMaskA_1": KIT_BIT["twin_slice"],
               "EffectSpellClassMaskC_1": (SLAYING_BIT["azzinoths_assault"]
                                           | SLAYING_BIT["annihilan_strike"]),
               "Description_Lang_enUS":
                   "Increases the damage of your Twin Slice, Azzinoth's Assault and Annihilan "
                   "Strike by $s1% against slowed enemies.",
           },
           note="src 804610 -- re-rank of Ascension's single +15% over three ranks"),

    # ---------------------------------------------------------------------------------- row 5 --

    # -- 5/0 -- Twin Fury ................................. donor 12319 Flurry (family 0)
    #
    # Ascension `801892` e0 is aura 42 pointed straight at `800058` Felfury -- the resource
    # record itself -- so "+1 Felfury on a crit" is one trigger cell and no script (plan 4 C1:
    # "+1 generation is pure data"). The id is `dh_spec.spell_id_for("felfury", 0)`, which only
    # the generator knows, so `EffectTriggerSpell_1` is left for the merge exactly as a TRIGGERS
    # cell would be -- but note that it points at an ABILITY record, not at a new row, which is a
    # case `TRIGGERS` does not currently express.
    # Its e1 (aura 107 misc 23 SPELLMOD_EFFECT3 at bp 9) is dropped: no Felsworn record this
    # talent can reach has a third effect worth +10.
    # CRIT-ONLY needs a `spell_proc` row with a HitMask; see FLAGGED.
    Talent(TAB, 5, 0, 1, "Twin Fury", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "EffectSpellClassMaskA_1": KIT_BIT["twin_slice"],
               "EffectSpellClassMaskC_1": SLAYING_BIT["annihilan_strike"],
               "Description_Lang_enUS":
                   "Critically striking with Twin Slice or Annihilan Strike generates 1 "
                   "additional Felfury.",
           },
           note="src 801892,800058 -- the trigger is the Felfury record, an ability id the "
                "generator owns"),

    # -- 5/1 -- Dancing Blades ............................ donor 12319 Flurry (family 0)
    #
    # PLAN 3.2 PICKS THE TWIN, and it is right: node spell `92087` is aura 112 at misc 20000 with
    # nothing behind it, while `705132` is the same talent as pure data -- aura 42 at bp 9 into
    # `800598` (one `SPELL_EFFECT_NORMALIZED_WEAPON_DMG` effect at target 22 with a radius),
    # ProcChance 100. So the record here is `705132`'s shape, not `92087`'s.
    # The mask is empty on purpose: "critical strikes with melee abilities" IS every Felsworn
    # spell once ProcTypeMask restricts it to melee-class ability damage and the `spell_proc`
    # HitMask restricts it to crits. `SPELL_ATTR3_REQ_OFFHAND` belongs on the cleave (a TRIGGERS
    # row), not here.
    Talent(TAB, 5, 1, 1, "Dancing Blades", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "ProcChance": 100,               # `705132`'s own
               "Description_Lang_enUS":
                   "Critical strikes with your melee abilities strike up to 3 nearby enemies "
                   "for off-hand weapon damage.",
           },
           note="src 705132,800598,92087 -- 92087 is the aura-112 node, 705132 the data twin"),

    # -- 5/2 -- Fel Haze .................................. donor 19549 Improved Aspect of Monkey
    #
    # Ascension `803903` is one effect: aura 107 ADD_FLAT_MODIFIER, misc 3 SPELLMOD_EFFECT1, at
    # bp 99. The +100 lands on Blood of Mannoroth's FIRST effect, which is aura 280
    # MOD_ARMOR_PENETRATION_PCT at bp -1 -- amount ZERO (plan 2.2). That is the whole design:
    # Blood of Mannoroth is a pure Energy-regen cooldown until this talent raises its dead effect
    # from 0 to 100% armour penetration. 19549 is the cleanest stock misc-3 flat modifier.
    Talent(TAB, 5, 2, 1, "Fel Haze", 19549,
           overrides={
               "EffectBasePoints_1": 99,        # DieSides 1 -> +100 on an amount of 0
               "EffectSpellClassMaskA_1": KIT_BIT["blood_of_mannoroth"],
               "Description_Lang_enUS":
                   "While Blood of Mannoroth is active you ignore all enemy armor.",
           },
           note="src 803903,802075 -- Ascension's own +100; 802075's aura 280 is bp -1, i.e. 0"),

    # -- 5/3 -- Felhoof Charge ............................ donor 20252 Intercept (Rank 1)
    #
    # Ascension `800204` triggers `800200` (`SPELL_EFFECT_CHARGE`) and then deals its own
    # `SPELL_EFFECT_SCHOOL_DAMAGE`; Intercept charges directly and triggers its stun. Keeping the
    # donor's Effect_1 CHARGE and turning its Effect_2 from TRIGGER_SPELL into SCHOOL_DAMAGE is
    # the same picture with one less record, and it drops the stun Ascension does not have.
    # bp 59 at level 29 (`800204`) to bp 149 at level 68 (`803484`) is +2.31 a level.
    # `Category 1158 / CategoryRecoveryTime 30000` are zeroed by TALENT_BASE, so Ascension's own
    # 20 s category cooldown is restated as a plain RecoveryTime -- which is also what Reachwalker
    # at (3,2) reduces.
    # `$AP*0.285` is `spell_bonus_data` (plan 6.4.4), not a cell.
    Talent(TAB, 5, 3, 1, "Felhoof Charge", 20252, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["felhoof_charge"],
               "Attributes": 537198608 & ~NOT_SHAPESHIFTED,   # 0x20050010 -> 0x20040010
               "Effect_2": 2,                   # SCHOOL_DAMAGE, from 64 TRIGGER_SPELL (the stun)
               "EffectTriggerSpell_2": 0,       # 20253, which would stun for 3 s
               "EffectBasePoints_2": 59,        # DieSides 1 -> 60 damage at level 29
               "EffectDieSides_2": 1,
               "EffectRealPointsPerLevel_2": 2.31,
               "BaseLevel": 29,
               "SpellLevel": 29,
               "ManaCost": 0,                   # Ascension charges no Energy for this
               "RecoveryTime": 20000,
               "StartRecoveryCategory": 133,    # the donor has no GCD cells at all
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Charge an enemy, dealing $s2 Physical damage.",
           },
           note="src 800204,800200,803484 -- R1 numbers, R1->R2 slope; the +1 Felfury is one "
                "authored TRIGGER_SPELL into the Felfury record (plan 4 C1)"),

    # ---------------------------------------------------------------------------------- row 6 --

    # -- 6/0 -- Demonic Machinations ...................... donor 12319 Flurry (family 0)
    #
    # Plan 4 C3, the cheapest bucket: Ascension `806111` is aura 354 -- above `TOTAL_AURAS`, so a
    # boot crash if imported -- carrying "trigger `806112` with N% of the damage dealt".
    # The rewrite keeps aura 42 with the SAME trigger and the SAME base points and one shared
    # AuraScript multiplies. `806112` is the Deep Wounds shape: aura 3 PERIODIC_DAMAGE, period
    # 1000, DurationIndex 28 = 5000 ms.
    # THE RECORD AND THE TOOLTIP DISAGREE: bp 9 is 10%, the description says 50%. The record wins
    # and plan 4 C3 reads it the same way. Ascension's tooltips are wrong elsewhere in this file
    # too (see (3,3)).
    Talent(TAB, 6, 0, 1, "Demonic Machinations", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "EffectBasePoints_1": 9,         # DieSides 1 -> 10, the percentage C3 reads
               "ProcChance": 100,
               "EffectSpellClassMaskA_1": KIT_BIT["sargeron_smite"],
               "Description_Lang_enUS":
                   "Critical strikes with your Sargeron Smite cause the target to bleed for an "
                   "additional $s1% of the damage dealt over 5 sec.",
           },
           note="src 806111,806112 -- 10% is the record's; its own tooltip claims 50%"),

    # -- 6/1 -- Nether Champion ........................... donor 12319 Flurry (family 0)
    #
    # Ascension `705145` procs `705146`, aura 108 SPELLMOD_DAMAGE at bp 7 (+8% Sargeron Smite),
    # DurationIndex 18 = 20000 ms, stacking. "Triggering Dancing Blades" is not expressible as a
    # mask -- the cleave is a TRIGGERS row with no family bit -- so this procs off the event
    # Dancing Blades procs off. Exact here, because the prerequisite IS Dancing Blades and its
    # ProcChance is 100. See DEGRADED for the case where it is not exact, at (7,2).
    Talent(TAB, 6, 1, 1, "Nether Champion", 12319, prereq=(5, 1, 0),
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "ProcChance": 100,
               "Description_Lang_enUS":
                   "Triggering Dancing Blades increases the damage of your next Sargeron Smite "
                   "by 8% for 20 sec, stacking up to 3 times.",
           },
           note="src 705145,705146 -- the buff, its 20 s and its stack cap are TRIGGERS cells"),

    # -- 6/2 -- Fury Unleashed ............................ donor 46924 Bladestorm (family 4)
    #
    # A closer donor than any rogue spell: Bladestorm is aura 23 PERIODIC_TRIGGER_SPELL into a
    # whirlwind every 1000 ms PLUS aura 147 MECHANIC_IMMUNITY_MASK at misc 1733 -- and Ascension
    # `555738` e2 is aura 147 at misc 1733, the same literal. Its third effect differs and moves:
    # `SPELL_AURA_ALLOW_ONLY_ABILITY` (263) becomes `MOD_INCREASE_SPEED` (31) at Ascension's own
    # +30%, because Ascension does not lock the action bar out.
    # DurationIndex 28 = 5000 ms is Ascension's; the donor's row 32 is 6000. Cost 60 Energy and
    # the 180 s cooldown are `555738`'s own. The whirlwind record (`555739`: eff 31 at bp 149 =
    # 150% weapon damage plus an off-hand half) is a TRIGGERS row.
    Talent(TAB, 6, 2, 1, "Fury Unleashed", 46924, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["fury_unleashed"],
               "Attributes": 327696 & ~NOT_SHAPESHIFTED,
               "EffectAura_3": 31,              # MOD_INCREASE_SPEED, from 263 ALLOW_ONLY_ABILITY
               "EffectBasePoints_3": 29,        # DieSides 1 -> +30% movement speed
               "EffectSpellClassMaskC_2": 0,    # the donor's own Bladestorm bit on the immunity
               "DurationIndex": 28,             # 5000 ms
               "ManaCost": 60,
               "RecoveryTime": 180000,
               "StartRecoveryTime": 1000,       # the house GCD, from the donor's 1500
               "Description_Lang_enUS":
                   "Spin your glaives for $d, increasing movement speed by $s3% and striking all "
                   "nearby enemies with both weapons every 1 sec. You are immune to movement "
                   "impairing and loss of control effects.",
           },
           note="src 555738,555739 -- cost, cooldown, duration and the immunity mask are all "
                "Ascension's own cells"),

    # -- 6/3 -- Pit Lord's Strength ....................... donor 14747 Improved Inner Fire
    #
    # Ascension ships two ranks and this tree wants two, so the ladder is copied: `802076` and
    # `802110` are aura 107 misc 4 SPELLMOD_CHARGES at bp 0 and bp 1. The target is `803904`
    # Annihilation, the tab-87 guaranteed-crit cooldown whose `ProcCharges` is 5 -- NOT `802059`,
    # the level-68 channelled nuke, which has no charges to add to (plan 2.1's name trap).
    # 14747's Effect_1 is a masked Inner Fire modifier and goes with all three of its mask words.
    Talent(TAB, 6, 3, 2, "Pit Lord's Strength", 14747,
           rank_cell="EffectBasePoints_3",
           rank_values=(0, 1),                  # DieSides 1 -> lands +1/+2 charges on a base of 5
           overrides={
               "Effect_1": 0,
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "EffectSpellClassMaskA_3": KIT_BIT["annihilation_crit"],
               "Description_Lang_enUS":
                   "Your Annihilation affects $s3 additional attacks.",
           },
           note="src 802076,802110,803904 -- Ascension's own two ranks, verbatim"),

    # ---------------------------------------------------------------------------------- row 7 --

    # -- 7/0 -- Azzinoth's Battery ........................ donor 12319 Flurry (family 0)
    #
    # "A chance not to CONSUME Felfury" is not a proc at all -- there is nothing to trigger, and
    # the roll has to happen inside the debit that plan 4 C1 puts in `OnSpellCast`. So the aura
    # becomes a plain `SPELL_AURA_DUMMY` whose AMOUNT is the chance, which the Felfury script
    # reads with `GetAuraEffect`, and ProcTypeMask stays zero so `SpellMgr` synthesises nothing.
    # Ascension's `705137` is aura 42 at ProcChance 30 into `801024`, whose only effect is 175 --
    # out of range, a boot crash, and it says "+2 Felfury" rather than "do not spend".
    Talent(TAB, 7, 0, 2, "Azzinoth's Battery", 12319,
           rank_cell="EffectBasePoints_1",
           rank_values=(14, 29),                # DieSides 1 -> lands a 15/30 % chance
           overrides={
               "EffectAura_1": 4,               # SPELL_AURA_DUMMY, from 42 PROC_TRIGGER_SPELL
               "EffectTriggerSpell_1": 0,       # 12966, Flurry's own buff
               "ProcTypeMask": 0,               # the donor's 0x14; nothing may synthesise a proc
               "ProcChance": 0,
               "Description_Lang_enUS":
                   "Your Azzinoth's Assault has a $s1% chance not to consume Felfury.",
           },
           note="src 705137,801024 -- re-rank of Ascension's ProcChance 30 over two ranks, "
                "carried as an amount because the roll belongs to the C1 spender path"),

    # -- 7/1 -- Glaiving .................................. donor 37441 Improved Arcane Blast
    #
    # Ascension `560578`: aura 107 misc 3 SPELLMOD_EFFECT1 at bp 49 and aura 108 misc 14 at
    # bp -51, described as one number, "$s1%", for both halves. The damage half moves from a FLAT
    # modifier on effect 1 to a PERCENTAGE modifier on damage: Fury Unleashed's damage is 150% of
    # weapon damage on a triggered record, so +50 flat on the parent's aura-23 effect (whose
    # amount is 0) would buy nothing, while SPELLMOD_DAMAGE reaches the triggered row through the
    # bit it carries.
    Talent(TAB, 7, 1, 3, "Glaiving", 37441, prereq=(6, 2, 0),
           rank_cell="EffectBasePoints_2",
           rank_values=(16, 32, 49),            # DieSides 1 -> lands 17/33/50 % damage
           rank_cell_2="EffectBasePoints_1",
           rank_values_2=(-18, -34, -51),       # DieSides 1 -> lands -17/-33/-50 % cost
           overrides={
               "Attributes": PASSIVE_ATTRS,
               "EffectSpellClassMaskA_1": 0,    # the donor's Arcane Blast bits, words 1 and 2
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": SLAYING_BIT["fury_unleashed"],
               "EffectSpellClassMaskC_2": SLAYING_BIT["fury_unleashed"],
               "Description_Lang_enUS":
                   "Increases the damage of your Fury Unleashed by $s2% and reduces its Energy "
                   "cost by $s1%.",
           },
           note="src 560578 -- both halves re-ranked to three from Ascension's single 50%; the "
                "damage half moves from SPELLMOD_EFFECT1 flat to SPELLMOD_DAMAGE percent"),

    # -- 7/2 -- Perpetual Fury ............................ donor 12319 Flurry (family 0)
    #
    # Ascension `520244` procs `520816`, whose only effect is 165 at bp -1001 with misc `555738`
    # -- the same out-of-range cooldown operation as (3,2), rewritten the same way by plan 4 C4
    # and bound to the same shared script on the TRIGGERS row.
    # Procs off a melee-ability crit rather than off "Dancing Blades damage"; see DEGRADED.
    Talent(TAB, 7, 2, 1, "Perpetual Fury", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "ProcChance": 100,
               "Description_Lang_enUS":
                   "Triggering Dancing Blades reduces the cooldown of your Fury Unleashed by "
                   "1 sec.",
           },
           note="src 520244,520816 -- -1000 ms is Ascension's own; effect 165 becomes the C4 "
                "dummy on the TRIGGERS row"),

    # ---------------------------------------------------------------------------------- row 8 --

    # -- 8/0 -- Legionfall ................................ donor 12319 Flurry (family 0)
    #
    # Ascension `801899` is aura 42 at ProcChance 15 into `801902`, which is BOTH halves of the
    # talent: aura 4 DUMMY misc 14 at bp -101 (a -100% cost modifier) and effect 195 (reset the
    # cooldown of `801903`). 195 is out of range; plan 4 C4 turns it into the shared dummy, and
    # names the trap -- Annihilan Strike's cooldown is a CategoryRecoveryTime shared across all
    # seven Ascension ranks, so the script must clear the category and not the spell.
    # The "next one is free" half is data once the script fires: a one-charge SPELLMOD_COST at
    # -100%, which is what `801902`'s own first effect already is.
    Talent(TAB, 8, 0, 2, "Legionfall", 12319,
           rank_cell="ProcChance",
           rank_values=(8, 15),                 # a chance column, NOT an effect: no +1 die
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "Description_Lang_enUS":
                   "Your melee ability damage has a $h% chance to reset the cooldown of your "
                   "Annihilan Strike and make its next cast free.",
           },
           note="src 801899,801902,801903 -- re-rank of Ascension's ProcChance 15 over two ranks"),

    # -- 8/1 -- Whirling Vengeance ........................ donor 13742 Endurance (family 8)
    #
    # Two halves, and only one is data. Ascension `704602` is aura 107 misc 11 SPELLMOD_COOLDOWN
    # at bp -60001, i.e. -60 s on Fury Unleashed's 180 -- which is exactly what 13742 already is
    # (its own bp is -30001 on Sprint and Evasion). The other half, "when Fury Unleashed ends,
    # strike all nearby enemies", is `AuraScript::AfterRemove` casting `806096` and is plan 4 C5.
    # `806096` itself is legal data: SCHOOL_DAMAGE at target 22 plus aura 271 MOD_DAMAGE_FROM_
    # CASTER, so only the "when it ends" is code.
    # The donor's Stamina second effect belongs to a tank tree and goes.
    Talent(TAB, 8, 1, 1, "Whirling Vengeance", 13742, prereq=(7, 1, 2),
           overrides={
               "EffectBasePoints_1": -60001,    # DieSides 1 -> -60000 ms
               "EffectSpellClassMaskA_1": 0,    # the donor's Sprint/Evasion bits, words 1 and 2
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": SLAYING_BIT["fury_unleashed"],
               "Effect_2": 0,                   # aura 137, +Stamina
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Fury Unleashed by $/1000;s1 sec. When Fury "
                   "Unleashed ends, you strike all nearby enemies for Shadowflame damage and "
                   "increase the damage they take from your Sunder.",
           },
           note="src 704602,806096 -- -60000 ms is Ascension's own; the expiry strike is C5"),

    # -- 8/2 -- Felguard .................................. donor 55610 Improved Icy Talons (DK)
    #
    # The only stock record that is a RAID-WIDE haste aura sitting beside a second self aura, and
    # both halves of Ascension `560542` need exactly that: effect 65 APPLY_AREA_AURA_RAID with
    # aura 192 MOD_MELEE_RANGED_HASTE at +10%, plus an aura-354 leech at 15% into `560627`.
    # The donor's raid aura is 138 MOD_MELEE_HASTE (melee only) and becomes 192 (melee AND
    # ranged), which is Ascension's; its self-haste second effect becomes the C3 leech proc.
    # PowerType 5 (runic) and RuneCostID 1205 are cleared by ALWAYS -- a rune cost on an Energy
    # class is unrecoverable, which is precisely why ALWAYS closes it.
    Talent(TAB, 8, 2, 1, "Felguard", 55610,
           proc_flags=PROC_MELEE_AUTO | PROC_MELEE_ABILITY,
           overrides={
               "EffectAura_1": 192,             # MOD_MELEE_RANGED_HASTE, from 138
               "EffectBasePoints_1": 9,         # DieSides 1 -> +10% to party and raid
               "EffectSpellClassMaskA_1": 0,    # three words of Icy Talons/Frost Fever bits
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": 0,
               "EffectAura_2": 42,              # PROC_TRIGGER_SPELL, from a second aura 192
               "EffectBasePoints_2": 14,        # DieSides 1 -> 15, the percentage C3 reads
               "ProcChance": 100,
               "Description_Lang_enUS":
                   "Party and raid members within 30 yards gain $s1% melee and ranged haste. "
                   "While Inner Demon is active you heal for $s2% of all melee damage dealt.",
           },
           note="src 560542,560627 -- aura 354 is out of range and becomes the C3 aura-42 "
                "rewrite; the Inner Demon condition is the C3 script's, not a ShapeshiftMask, "
                "because the raid aura must apply out of form"),

    # -- 8/3 -- Felcaked Blades ........................... donor 19549 Improved Aspect of Monkey
    #
    # Ascension `574145` is aura 23 firing `574150` (aura 107 misc 3 at amount 0, coefficient 1.0)
    # on a timer -- a POLL, whose only job is to recompute a modifier from Agility, because no
    # 3.3.5a cell scales a spellmod by a stat (`EffectRealPointsPerLevel` scales by level,
    # `EffectBonusMultiplier` by SP/AP). Plan 4 C6 replaces the poll with a stat-change hook, so
    # the record ships as the modifier itself at amount 0 and `spell_fs_stat_spellmod` writes the
    # amount whenever Agility moves. A `spell_bonus_data` row is NOT a substitute: it is global
    # per spell id and cannot be gated on owning this talent.
    Talent(TAB, 8, 3, 1, "Felcaked Blades", 19549,
           overrides={
               "EffectBasePoints_1": 0,         # the amount is the C6 script's, recomputed
               "EffectDieSides_1": 0,           # ... so the +1 the die would add must not happen
               "EffectSpellClassMaskA_1": (KIT_BIT["twin_slice"]
                                           | KIT_BIT["sargeron_smite"]),
               "Description_Lang_enUS":
                   "Your Twin Slice and Sargeron Smite additionally scale with your Agility.",
           },
           note="src 574145,574150 -- Ascension's own amount is 0 too; the number is the poll's "
                "and the poll is what C6 removes"),

    # ---------------------------------------------------------------------------------- row 9 --

    # -- 9/0 -- Chaotic ................................... donor 12319 Flurry (family 0)
    #
    # FREE, per plan 3.2: with Inner Demon as form 23, "while Inner Demon is active" is a
    # `ShapeshiftMask` and nothing else. `AuraEffect::HandleShapeshiftBoosts` walks the talent map
    # on every form change and casts any talent spell that is PASSIVE|DO_NOT_DISPLAY whose
    # Stances mask includes the new form -- no id switch anywhere on the path.
    # The energize is Ascension's `592521`: effect 30 SPELL_EFFECT_ENERGIZE, misc 3 POWER_ENERGY,
    # bp 2 -> 3 Energy. A TRIGGERS row.
    # Crit-only, so it needs a `spell_proc` HitMask row; see FLAGGED.
    Talent(TAB, 9, 0, 1, "Chaotic", 12319,
           proc_flags=PROC_MELEE_ABILITY,
           overrides={
               "ShapeshiftMask": INNER_DEMON_STANCE,
               "Attributes": PASSIVE_ATTRS,
               "ProcChance": 100,
               "Description_Lang_enUS":
                   "While Inner Demon is active, critical strikes with your direct melee "
                   "abilities restore 3 Energy.",
           },
           note="src 574143,592521 -- the form gate is a cell, not a script"),

    # -- 9/1 -- True Self ................................. donor 13712 Lightning Reflexes
    #
    # FREE the same way, and plan 3.2 says where the numbers are: `574140` itself is a bare DUMMY
    # marker, and the effects live in `800707` "Demon Form (Slaying)" -- aura 163
    # MOD_CRIT_DAMAGE_BONUS misc 127 at bp 9 and aura 49 MOD_DODGE_PERCENT at bp 9. Both are
    # copied onto the record here and the DUMMY is deleted.
    # 13712 already carries the dodge half; its melee-haste effect becomes the crit damage.
    Talent(TAB, 9, 1, 1, "True Self", 13712,
           overrides={
               "ShapeshiftMask": INNER_DEMON_STANCE,
               "Attributes": PASSIVE_ATTRS,
               "EffectBasePoints_1": 9,         # DieSides 1 -> +10% dodge
               "EffectAura_2": 163,             # MOD_CRIT_DAMAGE_BONUS, from 138 MOD_MELEE_HASTE
               "EffectMiscValue_2": 127,        # all seven schools
               "EffectBasePoints_2": 9,         # DieSides 1 -> +10% critical damage
               "Description_Lang_enUS":
                   "While Inner Demon is active, your dodge chance is increased by $s1% and your "
                   "critical strike damage by $s2%.",
           },
           note="src 574140,800707 -- both amounts are 800707's own cells"),

    # -- 9/2 -- Blighted Strikes .......................... donor 12319 Flurry (family 0)
    #
    # Same form gate. Ascension `570077` is aura 42 into `567578`: aura 118 MOD_HEALING_PCT at
    # bp -21 (-20% healing received), DurationIndex 31 = 8000 ms, stacking, at its own ProcChance
    # 20 -- but the CHANCE belongs to the talent record here, and Ascension's talent-side chance
    # is 100 for "your melee attacks", so the debuff row's 20 is not carried up.
    Talent(TAB, 9, 2, 1, "Blighted Strikes", 12319,
           proc_flags=PROC_MELEE_AUTO | PROC_MELEE_ABILITY,
           overrides={
               "ShapeshiftMask": INNER_DEMON_STANCE,
               "Attributes": PASSIVE_ATTRS,
               "ProcChance": 100,
               "Description_Lang_enUS":
                   "While Inner Demon is active, your melee attacks reduce the healing the "
                   "target receives by 20% for 8 sec, stacking up to 3 times.",
           },
           note="src 570077,567578 -- the debuff, its 8 s and its stack cap are TRIGGERS cells"),

    # --------------------------------------------------------------------------------- row 10 --

    # -- 10/1 -- Fury of the Illidari ..................... donor 51690 Killing Spree (family 8)
    #
    # THE CLOSEST DONOR IN THE WHOLE PORT. Killing Spree is aura 226 PERIODIC_DUMMY at misc 3
    # with a period, a bare DUMMY effect and aura 263 ALLOW_ONLY_ABILITY; Ascension `561216` is
    # aura 226 at misc 3, a bare DUMMY effect and aura 263. Same three effects in the same order.
    # `AuraEffect::HandlePeriodicDummyAuraTick` is a hardcoded id switch, so the tick is plan 4
    # C5's `AuraScript::OnEffectPeriodic`: six assaults, +1 Felfury each. Killing Spree's own
    # script is bound by `spell_script_names` to id 51690, so a clone inherits none of it.
    # 2 charges on a 90 s recharge is not portable -- 3.3.5a has no spell charges (plan 7) -- so
    # it ships as a flat 90 s cooldown. THAT 90 IS THE TOOLTIP'S NUMBER: `561216`'s own
    # RecoveryTime is 0, because Ascension keeps the recharge in its charge system.
    Talent(TAB, 10, 1, 1, "Fury of the Illidari", 51690, flags=1,
           overrides={
               "SpellClassMask_3": SLAYING_BIT["fury_of_the_illidari"],
               "Attributes": 65552 & ~NOT_SHAPESHIFTED,    # 0x10010 -> 0x10
               "ManaCost": 25,
               "RecoveryTime": 90000,
               "DurationIndex": 66,             # 2500 ms
               "SchoolMask": 32,                # Shadow, from 1 Physical
               "Description_Lang_enUS":
                   "Move quickly from enemy to enemy, striking with both weapons until 6 "
                   "assaults are made and generating 1 Felfury with each strike. You are immune "
                   "to crowd control effects.",
           },
           note="src 561216 -- cost, school and duration are its own; the 90 s cooldown is its "
                "tooltip's, since the record's RecoveryTime is 0"),
)


# =============================================================================================
# THE C++ BINDINGS -- plan section 4, keyed exactly as dh_talents.SCRIPT_NAMES is
# =============================================================================================
#
# A `spell_script_names` row exists only for a DATABASE-BOUND script: `SpellScript` and
# `AuraScript` are looked up by spell id at `ObjectMgr.cpp:6345`, while `AllSpellScript`,
# `PlayerScript`, `WorldScript` and `UnitScript` are registered in code and take no row (plan
# 6.5). That split is why five C-marked talents in this tree are ABSENT from this table:
#
#   (3,1) Annihilan Strike, (4,1) You Cheat Gul'dan!, (4,2) Pit Lord's Rage,
#   (4,3) Reckless Assault, (5,1) Dancing Blades   -- all plan 4 C7, whose hooks are
#   `UnitScript::OnBeforeRollMeleeOutcomeAgainst` / `ModifySpellDamageTaken` / `ModifyMeleeDamage`
#   and which filter by family bit rather than by a bound id.
#
# `spell_fs_counter` (plan 4 C8) is not used by this tree at all: all six "every Nth" talents are
# in Demonology and Felblood.
#
# THREE OF THESE BIND TO A TRIGGERS ROW AND NOT TO THE RANK RECORD -- the C4 cooldown dummy lives
# on the triggered spell, so the generator's emission has to reach TRIGGERS. Named at the top of
# this file as change 3.
SCRIPT_NAMES_SLAYING = {
    (TAB, 3, 2): "spell_fs_modify_cooldown",     # Reachwalker      -- C4, on the TRIGGERS row
    (TAB, 6, 0): "spell_fs_damage_pct_trigger",  # Demonic Machin.  -- C3
    (TAB, 7, 0): "spell_fs_felfury_spender",     # Azzinoth's Batt. -- C1, the refund roll
    (TAB, 7, 2): "spell_fs_modify_cooldown",     # Perpetual Fury   -- C4, on the TRIGGERS row
    (TAB, 8, 0): "spell_fs_modify_cooldown",     # Legionfall       -- C4, on the TRIGGERS row
    (TAB, 8, 1): "spell_fs_carve",               # Whirling Veng.   -- C5, the expiry strike
    (TAB, 8, 2): "spell_fs_damage_pct_trigger",  # Felguard         -- C3
    (TAB, 8, 3): "spell_fs_stat_spellmod",       # Felcaked Blades  -- C6
    (TAB, 10, 1): "spell_fs_carve",              # Fury of the Ill. -- C5, the periodic counter
}


# =============================================================================================
# SELFTEST
# =============================================================================================
#
# Called at import, not only under __main__, because dh_talents' own argument applies unchanged:
# a design error must fail HERE and not in game. The plan's own numbers are recomputed from
# `ranks` rather than trusted, so a talent whose rank count drifts cannot leave a stale grid
# comment behind claiming the tree still adds up.

PLAN_TALENTS = 38                   # section 3.2's grid; its header says 28 (see the docstring)
PLAN_POINTS = 68                    # section 3.2's header, and the only figure that reconciles
PLAN_GATE_ROW = (15, 25, 33, 37, 44, 48, 53, 59, 64, 67)   # cumulative points through rows 0..9

MAX_TALENT_RANK = 5                 # Player.cpp:14360, `spentPoints < Row * MAX_TALENT_RANK`
MAX_TIER = 10
MAX_COL = 3

DUMP_PATH = os.path.join(REPO_ROOT, "build", "tools", "ascension", "out",
                         "felsworn-family20.json")


def _source_ids(talent):
    """The Ascension spell ids in `note`'s mandatory `src <ids> -- ` prefix."""
    head = talent.note.split(" -- ", 1)[0]
    assert head.startswith("src "), (
        f"{talent.name!r}: note must open `src <id>[,<id>...] -- `, so that the Ascension "
        f"derivation is data and not prose; got {talent.note[:40]!r}")
    return tuple(int(x) for x in re.findall(r"\d+", head))


def selftest():
    cols = set(dbc_tables.SPELL_DBC.columns)
    string_cols = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
                   if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_STRING}
    float_cols = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
                  if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_FLOAT}

    # ---- the grid: no two talents in one cell ------------------------------------------------
    seen = {}
    for t in TALENTS_SLAYING:
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert t.tab == TAB, f"{where}: this file is the {TAB} tree only, got {t.tab!r}"
        assert 0 <= t.tier <= MAX_TIER, f"{where}: TierID is 0-{MAX_TIER}"
        assert 0 <= t.col <= MAX_COL, f"{where}: ColumnIndex is 0-{MAX_COL}"
        assert (t.tier, t.col) not in seen, (
            f"{where}: cell already taken by {seen.get((t.tier, t.col))!r}")
        seen[(t.tier, t.col)] = t.name

    # ---- ranks -------------------------------------------------------------------------------
    for t in TALENTS_SLAYING:
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert 1 <= t.ranks <= MAX_TALENT_RANK, (
            f"{where}: {t.ranks} ranks. Talent.dbc has SpellRank_1..5 and Player.cpp:14329 "
            f"iterates to MAX_TALENT_RANK, so 5 is the hard ceiling")
        assert t.ranks in (1, 2, 3, 5), (
            f"{where}: {t.ranks} ranks. Stock uses 1, 2, 3 and 5 and NEVER 4")
        assert t.flags in (0, 1), f"{where}: Talent.dbc Flags is 0 or 1"
        if t.flags:
            assert t.ranks == 1, (
                f"{where}: a talent that grants a button must be one rank, or several ids of "
                f"the same button land in the spellbook")
            assert t.overrides.get("SpellClassMask_3") in SLAYING_BIT.values(), (
                f"{where}: a granted active needs its own word-3 family bit")

    # ---- the word-3 block, which is the ONLY thing keeping three separately-written files from
    # handing two different buttons the same bit. `SpellInfo::IsAffected` (SpellInfo.cpp:1325-1337)
    # matches on mask OVERLAP, so a shared bit means every Demonology modifier naming Carve also
    # lands on Azzinoth's Assault. Slaying's block is 8-15; 0-7 is Demonology's eight actives and
    # 16-23 is Felblood's six.
    assert len(set(SLAYING_BIT.values())) == len(SLAYING_BIT), "two granted actives share a bit"
    for key, bit in SLAYING_BIT.items():
        assert bit and not (bit & (bit - 1)), f"SLAYING_BIT[{key!r}] must be exactly one bit"
        assert 0x100 <= bit <= 0x8000, (
            f"SLAYING_BIT[{key!r}] = {bit:#x} is outside bits 8-15, this tree's word-3 block")

    # ---- the per-rank cells ------------------------------------------------------------------
    for t in TALENTS_SLAYING:
        where = f"({t.tier},{t.col}) {t.name!r}"
        for cell, values in ((t.rank_cell, t.rank_values), (t.rank_cell_2, t.rank_values_2)):
            if not cell:
                assert not values, f"{where}: rank values with no cell to write them into"
                continue
            assert cell in cols, f"{where}: rank cell {cell!r} is not a Spell.dbc column"
            assert cell not in string_cols and cell not in float_cols, (
                f"{where}: rank cell {cell!r} must be an integer column")
            assert cell not in t.overrides, (
                f"{where}: {cell!r} is in BOTH overrides and a rank cell; the generator writes "
                f"overrides first, so the override would be silently discarded")
            assert len(values) == t.ranks, (
                f"{where}: {len(values)} values for {t.ranks} ranks")
            assert all(isinstance(v, int) and not isinstance(v, bool) for v in values), (
                f"{where}: rank values must be ints")
        assert t.rank_cell != t.rank_cell_2 or not t.rank_cell_2, (
            f"{where}: both rank cells name {t.rank_cell!r}")
        assert t.ranks == 1 or t.rank_cell, (
            f"{where}: {t.ranks} ranks and no rank cell, so every rank is the same record")

    # ---- the cells ---------------------------------------------------------------------------
    for t in TALENTS_SLAYING:
        where = f"({t.tier},{t.col}) {t.name!r}"
        for col, value in t.overrides.items():
            assert col in cols, f"{where}: {col!r} is not a Spell.dbc column"
            if col in string_cols:
                assert isinstance(value, str), f"{where}: {col!r} is a string column"
            elif col in float_cols:
                assert isinstance(value, float), f"{where}: {col!r} is a float column"
            else:
                assert isinstance(value, int) and not isinstance(value, bool), (
                    f"{where}: {col!r} must be an int, got {value!r}")
        # Words 1 and 2 of a talent's OWN mask belong to the ability kit and its second records;
        # a talent rank wearing an ability's bit is modified by every talent naming that ability.
        for col in ("SpellClassMask_1", "SpellClassMask_2"):
            assert t.overrides.get(col, 0) == 0, f"{where}: {col} must stay 0"
        # Effect ids and aura ids above the core's tables are a worldserver STARTUP CRASH, not a
        # no-op: SpellMgr.cpp:3039-3040 ASSERTs both (plan 4 C10).
        for n in (1, 2, 3):
            assert t.overrides.get(f"Effect_{n}", 0) <= 164, f"{where}: Effect_{n} out of range"
            assert t.overrides.get(f"EffectAura_{n}", 0) <= 316, (
                f"{where}: EffectAura_{n} out of range")

    # ---- the form gate -----------------------------------------------------------------------
    for t in TALENTS_SLAYING:
        if t.overrides.get("ShapeshiftMask"):
            where = f"({t.tier},{t.col}) {t.name!r}"
            assert t.overrides["ShapeshiftMask"] == INNER_DEMON_STANCE, (
                f"{where}: the only form a Felsworn has is Inner Demon (form "
                f"{dh_talents.dh_spec.SHAPESHIFT_FORM_ID})")
            assert t.overrides.get("Attributes", 0) & 0xC0 == 0xC0, (
                f"{where}: HandleShapeshiftBoosts skips a talent that is not "
                f"PASSIVE|DO_NOT_DISPLAY, so the form gate would silently never apply")
            assert t.flags == 0, f"{where}: a form-gated passive cannot also grant a button"

    # ---- the arrows: every prerequisite is a talent in THIS tree ------------------------------
    for t in TALENTS_SLAYING:
        if not t.prereq:
            continue
        where = f"({t.tier},{t.col}) {t.name!r}"
        assert len(t.prereq) == 3, f"{where}: prereq is (tier, col, rank)"
        ptier, pcol, prank = t.prereq
        tail = [x for x in TALENTS_SLAYING if (x.tier, x.col) == (ptier, pcol)]
        assert tail, f"{where}: prerequisite ({ptier},{pcol}) is not a talent in this tree"
        tail = tail[0]
        assert ptier < t.tier, (
            f"{where}: prerequisite {tail.name!r} is in tier {ptier}, which is not EARLIER "
            f"than {t.tier} -- TalentFrame_DrawLines cannot draw that arrow")
        assert 0 <= prank < tail.ranks, (
            f"{where}: prerequisite rank {prank} is outside {tail.name!r}'s {tail.ranks} ranks "
            f"(Player.cpp:14329 reads it as a 0-BASED floor)")

    # ---- the tier gate: every row is reachable ------------------------------------------------
    #
    # `Player::LearnTalent` (Player.cpp:14360-14362): `if (spentPoints < talentInfo->Row *
    # MAX_TALENT_RANK) return;`. So row N needs 5N points spendable ABOVE it, and the client
    # enforces the same rule at TalentFrameBase.lua:184.
    per_tier = {}
    for t in TALENTS_SLAYING:
        per_tier[t.tier] = per_tier.get(t.tier, 0) + t.ranks
    cumulative = []
    run = 0
    for tier in range(MAX_TIER + 1):
        run += per_tier.get(tier, 0)
        cumulative.append(run)
    for tier in range(1, MAX_TIER + 1):
        if tier not in per_tier:
            continue
        available = cumulative[tier - 1]
        assert available >= tier * MAX_TALENT_RANK, (
            f"row {tier} needs {tier * MAX_TALENT_RANK} points spent above it and only "
            f"{available} exist -- the row is unreachable (Player.cpp:14361)")

    # ---- the totals, against what plan 3.2 states ---------------------------------------------
    assert len(TALENTS_SLAYING) == PLAN_TALENTS, (
        f"{len(TALENTS_SLAYING)} talents; section 3.2's grid has {PLAN_TALENTS} cells")
    assert cumulative[-1] == PLAN_POINTS, (
        f"the tree full-clears for {cumulative[-1]} points, not the {PLAN_POINTS} section 3.2 "
        f"states")
    assert tuple(cumulative[:10]) == PLAN_GATE_ROW, (
        f"cumulative points by row are {tuple(cumulative[:10])}, but section 3.2's gate row is "
        f"{PLAN_GATE_ROW} -- one of the rank counts has drifted from the plan")

    # ---- the script table --------------------------------------------------------------------
    for pos, script in SCRIPT_NAMES_SLAYING.items():
        assert pos[0] == TAB and (pos[1], pos[2]) in seen, (
            f"SCRIPT_NAMES_SLAYING names {pos}, which is not a talent in this tree")
        assert script.startswith("spell_fs_"), (
            f"{pos}: {script!r} is not one of the module-registered names in plan section 4")

    # ---- every Ascension id this file names is really in the dump -----------------------------
    #
    # The task the plan sets is explicit: an id that is not in the 858-record family-20 dump is a
    # DANGLING ID in a shipped DBC. Checked here rather than asserted in a comment. Skipped, with
    # no failure, when the dump is not on this machine -- the generator must run on a box that
    # has only the DBCs.
    if os.path.exists(DUMP_PATH):
        with open(DUMP_PATH) as fh:
            known = {s["id"] for s in json.load(fh)["spells"]}
        for t in TALENTS_SLAYING:
            ids = _source_ids(t)
            assert ids, f"({t.tier},{t.col}) {t.name!r}: note names no Ascension id"
            for sid in ids:
                assert sid in known, (
                    f"({t.tier},{t.col}) {t.name!r}: Ascension id {sid} is not in "
                    f"{os.path.basename(DUMP_PATH)}")


selftest()


if __name__ == "__main__":
    points = sum(t.ranks for t in TALENTS_SLAYING)
    actives = sum(1 for t in TALENTS_SLAYING if t.flags)
    print(f"slaying -- {len(TALENTS_SLAYING)} talents, {points} points, {points} rank records, "
          f"{actives} granted buttons, {len(SCRIPT_NAMES_SLAYING)} script rows")
    print(f"{'row':>3} | {'col 0':<23} | {'col 1':<23} | {'col 2':<23} | col 3")
    print("-" * 3 + "-+-" + "-" * 23 + "-+-" + "-" * 23 + "-+-" + "-" * 23 + "-+-" + "-" * 23)
    for tier in range(MAX_TIER + 1):
        cells = []
        for col in range(MAX_COL + 1):
            here = [t for t in TALENTS_SLAYING if (t.tier, t.col) == (tier, col)]
            if not here:
                cells.append(" " * 23)
                continue
            t = here[0]
            star = "*" if t.flags else " "
            arrow = "^" if t.prereq else " "
            cells.append(f"{t.name[:20]:<20}{star}{arrow}{t.ranks}")
        print(f"{tier:>3} | " + " | ".join(cells).rstrip())
    print()
    run = 0
    for tier in range(MAX_TIER + 1):
        run += sum(t.ranks for t in TALENTS_SLAYING if t.tier == tier)
        print(f"  row {tier:>2}: {run:>3} points available, gate needs {tier * 5:>2}")
    print()
    for t in TALENTS_SLAYING:
        pre = f"  <- ({t.prereq[0]},{t.prereq[1]}) @ rank {t.prereq[2]}" if t.prereq else ""
        script = SCRIPT_NAMES_SLAYING.get((TAB, t.tier, t.col), "")
        print(f"  ({t.tier},{t.col}) {t.name:<22} {t.ranks} rank(s)  donor {t.donor:<6} "
              f"flags {t.flags}  proc {t.proc_flags:#x}{pre}")
        if t.rank_cell:
            print(f"        {t.rank_cell} = {', '.join(str(v) for v in t.rank_values)}")
        if t.rank_cell_2:
            print(f"        {t.rank_cell_2} = {', '.join(str(v) for v in t.rank_values_2)}")
        if script:
            print(f"        script: {script}")
        print(f"        {t.note}")
