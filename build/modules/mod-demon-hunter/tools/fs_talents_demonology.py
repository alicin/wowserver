#!/usr/bin/env python3
"""DEMONOLOGY -- tree 0 of the Felsworn port, exactly as port-plan.md 3.1 lays it out.

Read by the merged `dh_talents.py` (plan 6.3) as one third of `TALENTS`. Every id below was
read out of `build/tools/ascension/out/felsworn-family20.json` (858 records) and
`build/tools/ascension/out/demon-hunter.json` (158 advancement nodes); every stock donor was
read out of `/srv/wow/data/dbc/Spell.dbc` with `build/tools/acdbc`; every core line number was
checked in the pinned checkout at `.work/ac-src`. Nothing here is recalled.

WHAT dh_talents.Talent MUST GAIN BEFORE THIS FILE IMPORTS
---------------------------------------------------------
Six fields. Three are the plan's, in as many words (6.3: "`Talent` gains `rank_cell_2: str` +
`rank_values_2: tuple` (see 6.4) and `proc_flags: int`"):

    rank_cell_2:   str      the SECOND per-rank cell, written the same way rank_cell is
    rank_values_2: tuple    its values, rank 1 first; len must equal `ranks`
    proc_flags:    int      ProcTypeMask. Non-zero makes SpellMgr.cpp:2160-2240 synthesise a
                            proc entry from the DBC record alone, so a proc passive needs no
                            `spell_proc` row and prints no sql.sql error (plan 4.C0)

Two mirror the extension `dh_spec.Ability` just took (dh_spec.py:861-878), because a Felsworn
talent is an IMPORTED record and not a hand-overridden clone, and this file has to be able to
say which record:

    source:        Optional[int]        the Ascension id whose whole 234-cell record is
                                        transplanted onto the clone
    source_ranks:  Tuple[int, ...]      the rest of Ascension's ladder, ascending, EXCLUDING
                                        `source`, under the same `len + 1 == ranks` contract
                                        dh_spec states. Where we ship MORE ranks than Ascension
                                        does, this is left empty ON PURPOSE and the extra ids
                                        are named in the talent's comment instead -- see
                                        Nether Disciple and Outland Slaver.

`donor` is still required alongside `source` and is still chosen by EFFECT SHAPE: it is the row
memcpy'd before the import overwrites it, so a failed or partial import degrades to a sane
passive instead of to a blank record. Every donor below is named with what its effect layout is
and why nothing else in the stock file fits better.

The sixth is this file's own, and it exists because of a constraint on the file rather than on
the design:

    script:        str      the `spell_script_names` value for this talent's rank records

`dh_talents` keeps that in a module-level `SCRIPT_NAMES` dict keyed by grid position
(dh_talents.py:2061); this file is required to define exactly one module-level name, so the
script name rides on the talent. The merge may keep the field or fold it back into
`SCRIPT_NAMES` -- `{(t.tab, t.tier, t.col): t.script for t in TALENTS_DEMONOLOGY if t.script}`
is the whole conversion.

EVERY NUMBER HERE IS ASCENSION'S OWN, RE-RANKED. NONE OF IT IS MEASURED.
------------------------------------------------------------------------
Plan 6.3: "Everything numeric below is Ascension's own value re-ranked, **not measured**; carry
that caveat forward verbatim." It is carried forward verbatim, and every talent whose ladder has
more ranks than Ascension ships says so on the `rank_values` line in the form "RE-RANKED". The
rule used everywhere, and the only one used, is: Ascension's top value is the top rank's value,
and the ranks below it step evenly down to it. That makes rank 1 of a re-ranked talent WEAKER
than Ascension's and the full-rank talent IDENTICAL to Ascension's, which is the direction a
port should degrade in. Where a talent is one rank on both sides, the number is Ascension's
unchanged and is not marked.

The DieSides convention is dh_talents' (dh_talents.py:87-100) and is not restated per talent:
`SpellInfo::CalcValue` (SpellInfo.cpp:430-437) adds 1 when `EffectDieSides == 1`, so a value is
written one BELOW the number that lands. The landing values are in the comment on every line.
Ascension's own records use the same convention -- 705123 Outland Slaver is `bp -4 / ds 1` for a
tooltip that reads "3" -- which is why its cells transcribe across unchanged.

THE GRID, AND THE ONE PLACE THIS FILE DISAGREES WITH THE PLAN'S PROSE
---------------------------------------------------------------------
The table in plan 3.1 is reproduced cell for cell. Its own heading says "30 talents, 66 points":
the 66 is right and is asserted below, the 30 is a miscount -- the table has 37 cells, and 37
cells at the rank counts the table prints is exactly what sums to 66 and to the gate row
"12/19/28/35/39/47/52/57/62/65". So the count in the heading is the thing that is wrong, not the
table, and the table is what is emitted.

`Burning Commander 92089` is NOT emitted. Plan 3.1's footnote offers it at (0,3) "if a 31st cell
is wanted"; taking it would put the tree at 71 points and move every gate, and the plan's own
grid prints (0,3) empty. Its `Effect_3 = 155 SPELL_EFFECT_TITAN_GRIP` and its [C6] dodge->armour
half are ported nowhere else, so if it is wanted later it arrives with a new point budget.

    row | col 0                 | col 1                  | col 2                | col 3
    ----+-----------------------+------------------------+----------------------+---------------
      0 | Nether Disciple     5 | Infernal Constitution 5| Illidari Training  2 |
      1 | Abyssal Conditioning3 | Carve                1*| Outland Slaver     3 |
      2 | Demonic Will       1* | Unholy Endurance     3^| Vengeance          3 | Hulking Demon 2
      3 | Demon Hide          2 | Quick Carving          2| Felrend           1* | Fel Daze      2
      4 | Pure Hatred         1 | Annihilan Rituals    1^| Tyrant's Gaze     1* | Burning Hatred1*
      5 | Dark Lord           2 | Straight to the Nether2| Illidan's Favor    1 | Doomscarring  3
      6 | Nether Strength     2 | Hellfire Carver        1| Felblade           1 | Mannoroth's R.1
      7 | Demonic Fortitude   2 | Vengeance Is Mine      1| Expose             1 | Fel Torpedo  1*
      8 | Fel Monstrosity     3 |                        | Infernal Whipcr.  1* | Betrayer      1
      9 |                       | Grommash's Folly       1| Taskmaster's Army 1^ | Eye of the T. 1
     10 |                       | Tyrannical Resolve   1*|                      |
    (* grants a spellbook button, ^ has a prerequisite arrow, trailing digit = ranks)

    points by row  12  7  9  7  4  8  5  5  5  3  1   = 66
    cumulative     12 19 28 35 39 47 52 57 62 65 66   <- plan 3.1's gate row, reproduced
    tier gate       -  5 10 15 20 25 30 35 40 45 50   <- Player.cpp:14360-14362, 5 per row

THE TWO KINDS OF CELL THIS FILE IS NOT ALLOWED TO FILL IN
----------------------------------------------------------
1. TRIGGER IDS. Sixteen talents point at a second Spell.dbc record and Betrayer points at two,
   so seventeen cells in all. Those ids are allocated by `dhspells.build_talents` out of the
   92000-92999 band, so a talent cannot name one -- the
   `TRIGGERS` table in dh_talents names the CELL and the generator writes the id
   (dh_talents.py:1864-1879). Every such cell is called out as "TRIGGER HOLE" in the comment and
   is deliberately absent from `overrides`, because dh_talents asserts a trigger's cell is not
   also an override (dh_talents.py:2385). Leaving it absent means the DONOR's own trigger id
   survives if the merge forgets the TRIGGERS row -- Carve would tick Hellfire's fire damage --
   so each hole names what the row has to be.

2. ABILITY-KIT FAMILY BITS. `SpellInfo::IsAffected` (SpellInfo.cpp:1325-1337) needs the
   modifier's mask to overlap the spell's, and word 1 of that mask is `dh_donors`' allocation,
   one bit per learnable ability, DERIVED at import and never copied (dh_talents.py:156). This
   file cannot derive it: dh_donors still holds the Demon Hunter's 22 keys and will not hold
   `fel_fireball` or `twin_slice` until 6.2 is done. So each such cell is written as an explicit
   `0` with a "MASK HOLE" comment naming the ability keys it must become. A zero mask is not
   harmless -- it means "every Felsworn spell" (dh_talents.py:648-652 uses exactly that on
   purpose) -- which is why the holes are written down and asserted in `selftest` rather than
   left to be noticed in game.

Word 3 of the mask IS this file's, because Demonology is tree 0 and therefore takes the first
bits: the eight granted actives get 0x01..0x80 in declaration order, leaving 0x100 upward for
Slaying and Felblood. That mirrors dh_talents.TALENT_BIT, which is append-only for the same
reason (a bit that moves silently repoints whatever named it). If the merge concatenates the
trees in another order these eight literals move with them.

FIVE CELLS THIS FILE DELIBERATELY DOES NOT CARRY, same split as dh_talents.py:25-35:
`ID`, `Name_Lang_enUS`, `NameSubtext_Lang_enUS`, `SpellClassSet` and the icon columns are the
generator's. `MaxLevel`, `Category` and `CategoryRecoveryTime` are `dhspells.TALENT_BASE`'s.
`SpellClassMask_1/2/3`, `ShapeshiftMask`, `PowerType`, `ManaCost`, `ManaCostPct`, `RuneCostID`
and the equipment gate are `dh_talents.ALWAYS`'s and are restated only where a talent overrides
them back (the three form-gated passives and the eight granted actives).

SCRIPTS: FIVE OF THE SIX NAMES IN PLAN 4 ARE USED HERE
-------------------------------------------------------
`spell_fs_carve` (Carve, Annihilan Rituals, Hellfire Carver -- one channel accumulator, three
talents), `spell_fs_damage_pct_trigger` (the C3 aura-354 rewrite, three talents),
`spell_fs_modify_cooldown` (Nether Strength), `spell_fs_stat_spellmod` (Pure Hatred, Felblade),
`spell_fs_counter` (Tyrannical Resolve's absorb cap and absorbed-instance count).
`spell_fs_felfury_spender` is NOT used in this tree: the only Felfury spender in Demonology is
Carve, whose 2-charge debit is part of `spell_fs_carve` (plan 4.C5(a)).

Dark Lord is the one talent that needs C++ and carries no script name, and that is not an
oversight: plan 4.C7 puts the ">75% health" predicate on `UnitScript` hooks
(`OnBeforeRollMeleeOutcomeAgainst`, `ModifySpellDamageTaken`), and plan 6.5 states the ownership
split -- `UnitScript` is registered in code and takes no `spell_script_names` row, only
`SpellScript`/`AuraScript` are database-bound (ObjectMgr.cpp:6345).

NOT VERIFIED, and the list is short on purpose:
  * Nothing here has been rendered in a client. 37 rows, none seen (plan 7.2).
  * Which proc flag a dodge, a parry or a channel actually raises was read out of
    `SpellMgr.h:108-146`, not observed (plan 7.4). Every `proc_flags` value below is that class
    of assumption and says so.
  * Six talents want a `HitMask` (crit-only, dodge-only) that the DBC cannot express, so they
    need a real `spell_proc` row and one sql.sql line per boot at `SpellMgr.cpp:2089` -- called
    out per talent. This is the exact trade plan 4.C0 describes, taken knowingly.
"""

import os
import re
import sys
from dataclasses import dataclass, fields

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DH_TOOLS = os.path.join(_REPO_ROOT, "build", "modules", "mod-demon-hunter", "tools")

sys.path.insert(0, _DH_TOOLS)

import dh_talents                                                   # noqa: E402

# THE SHIM, and it deletes itself. `dh_talents.Talent` (dh_talents.py:290-311) stops at `note`,
# so every keyword the header lists above is a TypeError at import until plan 6.3 lands --
# `python3 talents_demonology.py` could not even be run. The same shim is in
# talents_slaying.py:145-160 and talents_felblood.py:126-134, deliberately written the same way
# so the merge deletes three identical blocks. Appending DEFAULTED fields to a frozen dataclass
# is legal because every field the base declares after `donor` already has a default, so the
# subclass behaves exactly as 6.3's edited base will.
_WANTED = {"rank_cell_2", "rank_values_2", "proc_flags", "source", "source_ranks", "script"}
if _WANTED <= {_f.name for _f in fields(dh_talents.Talent)}:
    Talent = dh_talents.Talent
else:
    @dataclass(frozen=True)
    class Talent(dh_talents.Talent):                                # noqa: F811
        rank_cell_2: str = ""
        rank_values_2: tuple = ()
        proc_flags: int = 0
        source: int = 0
        source_ranks: tuple = ()
        script: str = ""


# =============================================================================================
# TREE 0 -- DEMONOLOGY (TalentTab.dbc 412, OrderIndex 0) -- 37 talents, 66 points
# =============================================================================================
#
# Tab 18 in Ascension's `CharacterAdvancement` has 43 nodes. Six are not talents here and each
# has a reason: 520885 Burning Legionnaire, 705122 Bulwark of Azzinoth and 704611 Battle Finesse
# are folded INTO the talent the plan pairs them with (`+` in plan 3.1); 92089 Burning Commander
# is the deliberately-unspent 31st cell; 706267 Felspill and 807438 Demonic Blood have no cell in
# plan 3.1's grid at all.
#
# The row of a talent is Ascension's own depth, not a fresh design: plan 3 anchors it on
# `row = (ascension_level - 10) / 5`, and the four nodes whose descriptions state a level land
# where that arithmetic puts them -- Hulking Demon "Level 20" at row 2, Felblade "Level 40" at
# row 6, Fel Monstrosity "Level 50" at row 8. The granted actives agree through their
# `spell_level` instead: Carve 11 at row 1, Demonic Will 13 at row 2, Felrend 17 at row 3,
# Tyrant's Gaze and Burning Hatred 29 at row 4, Infernal Whipcrack 57 at row 8, Tyrannical
# Resolve 59 at row 10. Hellfire Carver is the single exception -- its own text says "Level 30",
# which is row 4, and plan 3.1 puts it at (6,1) next to the other Carve talents. The plan's grid
# wins; it is noted at the talent.

TALENTS_DEMONOLOGY = (

    # -- 0/0 -- Nether Disciple ........... source 560576 (+561343), donor 50054 Quick Feet
    #
    # 560576 is two effects and nothing else: aura 49 MOD_DODGE_PERCENT and aura 47
    # MOD_PARRY_PERCENT, both `bp 2 / ds 1` (3%); 561343 is the identical record at bp 5 (6%).
    # 50054 is one of only three stock rows carrying that exact pair, and the only one that is
    # not an active -- 31567 Deterrence has a cooldown and a 5-second duration, 51601 Bonk is a
    # creature attack that makes both NEGATIVE.
    # source_ranks IS EMPTY DESPITE ASCENSION HAVING A LADDER: the contract is
    # `len(source_ranks) + 1 == ranks` and we ship five ranks against Ascension's two, so 561343
    # is named here instead of being passed as a rank record the generator cannot place.
    Talent("demonology", 0, 0, 5, "Nether Disciple", 50054,
           source=560576,
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 2, 3, 4, 5),          # RE-RANKED: lands 2/3/4/5/6 % dodge. Ascension
                                                 # is 3/6 over two ranks; rank 5 is its ceiling.
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(1, 2, 3, 4, 5),        # the same number on parry, as 560576 has it
           overrides={
               "Attributes": 0x1D0,              # the donor is 0x0, i.e. a castable buff.
                                                 # IS_ABILITY|PASSIVE|DO_NOT_DISPLAY|DO_NOT_LOG,
                                                 # SharedDefines.h:374-378
               "DurationIndex": 21,              # SpellDuration.dbc row 21 is -1 (infinite),
                                                 # read from the file; the donor's row 28 is
                                                 # 5000 ms, which would expire the passive
               "Description_Lang_enUS":
                   "Increases your dodge and parry chance by $s1%.",
           },
           note="50054 -- the only non-active stock row pairing aura 49 with aura 47"),

    # -- 0/1 -- Infernal Constitution ..... source 805256, donor 13715 Dual Wield Specialization
    #
    # 805256 is aura 133 MOD_INCREASE_HEALTH_PERCENT at bp 9 (+10% health) and aura 122
    # MOD_OFFHAND_DAMAGE_PCT at bp 29 (+30% off-hand). NO stock row carries both, so the donor is
    # chosen for the half that is harder to author safely: 13715 is aura 122 alone, family 8,
    # Attributes 464, DurationIndex 21, no mask, and it ships in five stock ranks -- the same
    # count this talent has. The health half is authored as Effect_2.
    # Plan 3.4 lists this talent as one that must freeze its second number. rank_cell_2 is
    # exactly the generator change (6.4.3) that lifts the freeze, so both numbers move.
    Talent("demonology", 0, 1, 5, "Infernal Constitution", 13715,
           source=805256,
           rank_cell="EffectBasePoints_1",
           rank_values=(5, 11, 17, 23, 29),      # RE-RANKED: lands 6/12/18/24/30 % off-hand
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(1, 3, 5, 7, 9),        # RE-RANKED: lands 2/4/6/8/10 % max health
           overrides={
               "EffectAura_1": 122,              # MOD_OFFHAND_DAMAGE_PCT. THE IMPORT PUTS THESE
                                                 # TWO AURAS THE OTHER WAY ROUND -- 805256 is
                                                 # health on e1 and off-hand on e2 -- so without
                                                 # this pin the record would carry aura 133
                                                 # twice, grant no off-hand damage at all, and
                                                 # hand the off-hand ladder to max health.
               "Effect_2": 6,                    # APPLY_AURA. MOD_INCREASE_HEALTH_PERCENT, which
               "EffectAura_2": 133,              # is the half the DEGRADED path has to author
                                                 # because the donor has one effect.
               "EffectDieSides_2": 1,            # matches the donor's own die, so both rank
                                                 # cells obey the same +1 convention
               "ImplicitTargetA_2": 1,           # TARGET_UNIT_CASTER
               "Description_Lang_enUS":
                   "Increases your maximum health by $s2% and the damage done by your off-hand "
                   "weapon by $s1%.",
           },
           note="13715 -- aura 122 with nothing attached; the aura-133 half is authored"),

    # -- 0/2 -- Illidari Training ......... source 805249 (+521210), donor 49223 Dirge
    #
    # THE RANK TRICK, dh_talents.py:477-488: 805249 is aura 42 into 521210, whose whole content
    # is `SPELL_EFFECT_ENERGIZE bp 2 ds 1 misc 3` = 3 Energy. The scaling number therefore lives
    # in the TRIGGERED row, where two ranks would need two rows. Aura 231
    # PROC_TRIGGER_SPELL_WITH_VALUE passes the aura's OWN amount in as basepoints0
    # (SpellAuraEffects.cpp:6922-6936), so one row serves both ranks -- and 49223 is the stock
    # aura-231 donor dh_talents already vetted.
    # TRIGGER HOLE: `EffectTriggerSpell_1` must become the energize row (donor 51206, misc 3
    # POWER_ENERGY, and `EffectDieSides_1 = 0` on the trigger or every rank lands one high).
    # The donor's own 51206 pointer survives if the merge forgets, which would restore Runic
    # Power to a class that has none.
    Talent("demonology", 0, 2, 2, "Illidari Training", 49223,
           source=805249,
           proc_flags=0x00000028,                # TAKEN_MELEE_AUTO_ATTACK | TAKEN_SPELL_MELEE_
                                                 # DMG_CLASS (SpellMgr.h:114,117). READ, NOT
                                                 # OBSERVED. A dodge is an outcome of a taken
                                                 # attack, so the flag is the attack's and the
                                                 # outcome needs the HitMask below.
           rank_cell="EffectBasePoints_1",
           rank_values=(1, 2),                   # RE-RANKED: the aura's amount is 2/3, and that
                                                 # amount IS the Energy restored. Ascension's
                                                 # single 521210 is 3.
           overrides={
               "EffectAura_1": 231,              # PROC_TRIGGER_SPELL_WITH_VALUE. THE RANK TRICK
                                                 # IS A CELL, NOT THE DONOR'S: 805249's own e0 is
                                                 # aura 42, which the import writes over 49223's
                                                 # 231, and aura 42 discards the amount -- both
                                                 # ranks would restore 521210's flat 3 Energy.
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x1101 is a Death Knight mask; a
                                                 # dodge is not a spell, so no mask is wanted and
                                                 # the generated proc entry stays family-free
               "Description_Lang_enUS":
                   "Dodging an attack generates $s1 Energy.",
           },
           note="49223 -- aura 231; NEEDS a spell_proc row for HitMask PROC_EX_DODGE "
                "(SpellMgr.h:203), which the DBC cannot express -- one sql.sql line per boot"),

    # -- 1/0 -- Abyssal Conditioning ...... source 807431 (+521234), donor 49223 Dirge
    #
    # Same shape and the same argument as Illidari Training: 807431 is aura 42 into 521234, and
    # 521234 is one effect, aura 110 MOD_POWER_REGEN_PERCENT `bp 4 ds 1 misc 3` = +5% Energy
    # regeneration, stacking. Aura 231 moves the number onto the rank record.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the stacking regen buff (donor 31122 Vitality,
    # aura 110 misc 3 already; `CumulativeAura` for the stack, `EffectDieSides_1 = 0`).
    Talent("demonology", 1, 0, 3, "Abyssal Conditioning", 49223,
           source=807431,
           proc_flags=0x00011010,                # DONE_SPELL_MELEE_DMG_CLASS | DONE_SPELL_NONE_
                                                 # DMG_CLASS_NEG | DONE_SPELL_MAGIC_DMG_CLASS_NEG
                                                 # (SpellMgr.h:116,128,134). READ, NOT OBSERVED:
                                                 # the Felfury spenders are split across melee
                                                 # (Carve, Sunder) and magic (Sargeron Smite),
                                                 # so all three bits are set rather than guessing
                                                 # which one a spender raises.
           rank_cell="EffectBasePoints_1",
           rank_values=(0, 2, 4),                # RE-RANKED: lands 1/3/5 % per stack. Ascension
                                                 # is one node at 5%.
           overrides={
               "EffectAura_1": 231,              # PROC_TRIGGER_SPELL_WITH_VALUE, over 807431's
                                                 # own aura 42 -- same pin, same reason, as 0/2
               "EffectSpellClassMaskA_1": 0,     # the donor's DK mask again -- see 0/2
               "Description_Lang_enUS":
                   "Casting a Felfury spender increases your Energy regeneration by $s1% for "
                   "$d, stacking up to $u times.",
           },
           note="49223 again -- one trigger row for all three ranks is the whole point of "
                "aura 231"),

    # -- 1/1 -- Carve ..................... source 800206, donor 1949 Hellfire        [C5] *
    #
    # THE TALENT THIS WHOLE TREE IS BUILT AROUND: four other talents modify it and a fifth
    # depends on it. 800206 is a 2500 ms channel (DurationIndex 66 -- SpellDuration.dbc row 66 is
    # 2500 ms in the STOCK file too, read from it, so Ascension's own index transcribes) with two
    # aura-23 effects: one at 2499 ms into 807423 and one at 250 ms into 803716, which is the
    # tick counter the finisher scales off. Cost is 20 Energy plus 2 Felfury, and a stacking aura
    # cannot be a WotLK power cost, so the debit is the script's (plan 4.C5(a)).
    # 1949 is the donor because the channel plumbing is the part a clone cannot author: its
    # `InterruptFlags`, `ChannelInterruptFlags`, `AttributesEx` CHANNELED bit and the aura-23
    # periodic-into-a-trigger layout are exactly this shape. Its self-damage (e2) and mechanic
    # immunity (e3) go.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the per-tick stack marker (803716's shape). The
    # donor's own 5857 is Hellfire's fire tick and MUST NOT survive.
    Talent("demonology", 1, 1, 1, "Carve", 1949, flags=1,
           source=800206,
           script="spell_fs_carve",
           overrides={
               "SpellClassMask_3": 0x00000001,   # the first granted active in tree 0
               "Attributes": 0x00000010,         # IS_ABILITY only. The donor's 0x10000 is
                                                 # NOT_SHAPESHIFTED (SharedDefines.h:386) and
                                                 # would grey out this button inside Inner Demon,
                                                 # which is the form four of its own modifiers
                                                 # require (dh_talents.py:227-235)
               "SchoolMask": 1,                  # Physical, from the donor's 4 (Fire); 800206 is
                                                 # school_mask 1
               "DurationIndex": 66,              # 2500 ms, Ascension's own index and the same
                                                 # row in the stock file
               "ManaCost": 20,                   # Energy. The 2 Felfury are the script's.
               "StartRecoveryCategory": 133,     # the house GCD, from the donor's 133/1500
               "StartRecoveryTime": 1000,
               "EffectAuraPeriod_1": 250,        # Ascension's fast tick; the 2499 ms half
                                                 # collapses into the script's finisher
               "EffectBasePoints_1": 0,          # the tick carries no number of its own
               "EffectDieSides_1": 0,
               "Effect_2": 0,                    # Hellfire's self-damage: aura 3 PERIODIC_DAMAGE
               "EffectAura_2": 0,                # on the caster, with real numbers and a
               "EffectBasePoints_2": 0,          # per-level coefficient. Nothing about Carve
               "EffectDieSides_2": 0,            # damages its own caster.
               "EffectRealPointsPerLevel_2": 0.0,
               "ImplicitTargetA_2": 0,
               "EffectAuraPeriod_2": 0,
               "Effect_3": 0,                    # aura 77 MECHANIC_IMMUNITY misc 16, Hellfire's
               "EffectAura_3": 0,                # own no-interrupt clause
               "EffectBasePoints_3": 0,
               "EffectDieSides_3": 0,
               "EffectMiscValue_3": 0,
               "ImplicitTargetA_3": 0,
               "Description_Lang_enUS":
                   "Consumes 2 Felfury. Charge up an attack over $d, then slash in front of you "
                   "for increased weapon damage with both weapons based on how long you "
                   "channelled, dealing less damage to each additional target.",
           },
           note="1949 -- the stock channel whose aura 23 already points at a triggered tick; "
                "everything Carve does past counting those ticks is spell_fs_carve"),

    # -- 1/2 -- Outland Slaver ............ source 705123 (+707846, +520885), donor 13732
    #
    # THREE Ascension records fold into one row, which is why it has three effects:
    #   705123 e0  aura 107 SPELLMOD_COST(14) bp -4  -> -3 Energy on Felrend and Fel Fireball
    #   705123 e1  aura 108 SPELLMOD_DAMAGE(0) bp 14 -> +15% on the same two
    #   520885 e0  aura 107 SPELLMOD_COST(14) bp -11 -> -10 Energy on Twin Slice and Sunder
    # 707846 is Ascension's rank 2 (-6 Energy, +30%) and is the ceiling the three ranks below
    # reproduce; it is not passed as `source_ranks` because we ship three ranks and the contract
    # is `len + 1 == ranks`.
    # 520885's -10 is the THIRD number and stays flat at Ascension's value on every rank: one
    # talent gets two rank cells and no more (plan 6.4.3), and freezing the number that belongs
    # to the folded-in node is the cheapest of the three freezes available.
    # 13732 is the donor because its single effect IS the cost half, at the same op, with the
    # same die -- and its own `bp -4 / ds 1` for a tooltip that reads "3" is the proof the +1
    # convention holds for negatives.
    Talent("demonology", 1, 2, 3, "Outland Slaver", 13732,
           source=705123,
           rank_cell="EffectBasePoints_2",
           rank_values=(9, 19, 29),              # RE-RANKED: lands 10/20/30 % damage; 707846's
                                                 # 30% is rank 3
           rank_cell_2="EffectBasePoints_1",
           rank_values_2=(-3, -5, -7),           # RE-RANKED: lands -2/-4/-6 Energy; 707846's
                                                 # -6 is rank 3
           overrides={
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- dh_donors.BIT["fel_fireball"].
                                                 # The donor's 0x2 is Sinister Strike's bit and
                                                 # must not survive.
               "EffectSpellClassMaskC_1": 0x00000004,   # Felrend, this tree's (3,2)
               "Effect_2": 6,                    # APPLY_AURA -- authored
               "EffectAura_2": 108,              # ADD_PCT_MODIFIER
               "EffectMiscValue_2": 0,           # SPELLMOD_DAMAGE (SpellDefines.h:76)
               "EffectDieSides_2": 1,
               "ImplicitTargetA_2": 1,
               "EffectSpellClassMaskA_2": 0,     # MASK HOLE -- dh_donors.BIT["fel_fireball"]
               "EffectSpellClassMaskC_2": 0x00000004,   # Felrend
               "Effect_3": 6,                    # APPLY_AURA -- authored, 520885's half
               "EffectAura_3": 107,              # ADD_FLAT_MODIFIER
               "EffectMiscValue_3": 14,          # SPELLMOD_COST (SpellDefines.h:90)
               "EffectBasePoints_3": -11,        # 520885's own value, FROZEN: lands -10 Energy
               "EffectDieSides_3": 1,
               "ImplicitTargetA_3": 1,
               "EffectSpellClassMaskA_3": 0,     # MASK HOLE -- BIT["twin_slice"]|BIT["sunder"]
               "Description_Lang_enUS":
                   "Reduces the Energy cost of your Felrend and Fel Fireball by $s1 and "
                   "increases their damage by $s2%. Also reduces the Energy cost of your Twin "
                   "Slice and Sunder by $s3.",
           },
           note="13732 -- aura 107 SPELLMOD_COST at the same op Ascension uses; the damage and "
                "the Twin Slice/Sunder halves are authored"),

    # -- 2/0 -- Demonic Will .............. source 800209, donor 48792 Icebound Fortitude    *
    #
    # 800209 is a 45 s defensive cooldown at `spell_level 13`: aura 87 MOD_DAMAGE_PERCENT_TAKEN
    # at bp -31 (-30%, all schools), aura 42 into 500497 ("direct damage heals you", a
    # SPELL_EFFECT_HEAL_MECHANICAL row) and an aura-49 dodge effect whose bp is -1, i.e. amount
    # ZERO, which implements nothing and is dropped.
    # 48792 is the donor because its Effect_3 is already aura 87 misc 127 at bp -31 -- the exact
    # cell, the exact value -- and because everything else it carries is cleared by
    # dh_talents.ALWAYS: PowerType 6, ManaCost 200, RuneCostID 561, SpellClassMask 0x100000.
    # Its Effect_1 (aura 77 stun immunity) goes: Demonic Will is not a stun break, and shipping
    # one by accident is the sort of thing that gets found in an arena.
    # FELFURY HOLE: Ascension generates 1 Felfury on cast. Plan 4.C1 makes that pure data -- one
    # `Effect 64 TRIGGER_SPELL` at the felfury record -- but that id is an ability-block id
    # (91460, plan 5) the generator owns, so the effect is authored by the merge, not here.
    Talent("demonology", 2, 0, 1, "Demonic Will", 48792, flags=1,
           source=800209,
           overrides={
               "SpellClassMask_3": 0x00000002,
               "Attributes": 0x00000010,         # IS_ABILITY only, over 800209's own 0x10010.
                                                 # 0x10000 is NOT_SHAPESHIFTED, and form 23
                                                 # copies row 22's Flags 0xd8, which has no
                                                 # SHAPESHIFT_FLAG_STANCE -- so a Felsworn "acts
                                                 # as shifted" and SpellInfo.cpp:1475 greys this
                                                 # button out in the form the tree is built on.
               "RecoveryTime": 45000,            # Ascension's; the donor is 120000
               "DurationIndex": 1,               # 10000 ms (SpellDuration.dbc row 1), Ascension's
                                                 # own index; the donor's row 29 is 12000
               "Effect_1": 0,                    # aura 77 MECHANIC_IMMUNITY misc 12 -- a stun
               "EffectAura_1": 0,                # immunity nobody asked for
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "Effect_2": 6,                    # the donor's Effect_2 is a bare aura 4 DUMMY;
               "EffectAura_2": 42,               # it becomes the heal proc. TRIGGER HOLE:
               "EffectBasePoints_2": 0,          # EffectTriggerSpell_2 -> 500497's shape
               "EffectDieSides_2": 1,            # (HEAL_MECHANICAL, 3% of max health).
               "ImplicitTargetA_2": 1,
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Strengthen your will, reducing damage taken by $s3% "
                   "for $d. While active, your direct damage heals you.",
           },
           note="48792 -- Effect_3 is already aura 87 misc 127 at -30%, the number and the cell "
                "Ascension uses; the donor's own Defense-scaling half is spell_dk.cpp:1735 and "
                "binds by spell id, so a clone does not inherit it"),

    # -- 2/1 -- Unholy Endurance .......... source 300466, donor 18427 Aggression
    #
    # ->Carve, which is the arrow plan 3.1 draws. The prerequisite rank is 0 because Carve has
    # exactly one rank and `PrereqRank_1` is a 0-BASED floor (Player.cpp:14329).
    # 300466 is two aura-108 effects at bp 14 (+15%): misc 0 SPELLMOD_DAMAGE and misc 2
    # SPELLMOD_THREAT, both masked to Carve. Plan 3.4 names the threat half as the one that would
    # have been frozen; rank_cell_2 keeps it moving.
    Talent("demonology", 2, 1, 3, "Unholy Endurance", 18427, prereq=(1, 1, 0),
           source=300466,
           rank_cell="EffectBasePoints_1",
           rank_values=(4, 9, 14),               # RE-RANKED: lands 5/10/15 % damage
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(4, 9, 14),             # RE-RANKED: lands 5/10/15 % threat
           overrides={
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x20006 is three rogue abilities
               "EffectSpellClassMaskC_1": 0x00000001,   # Carve
               "Effect_2": 6,                    # APPLY_AURA -- authored, the donor has one
               "EffectAura_2": 108,              # ADD_PCT_MODIFIER
               "EffectMiscValue_2": 2,           # SPELLMOD_THREAT (SpellDefines.h:78)
               "EffectDieSides_2": 1,
               "ImplicitTargetA_2": 1,
               "EffectSpellClassMaskC_2": 0x00000001,   # Carve
               "Description_Lang_enUS":
                   "Increases the damage and the threat generated by your Carve by $s1%.",
           },
           note="18427 -- aura 108 SPELLMOD_DAMAGE, one effect, nothing to strip but the mask"),

    # -- 2/2 -- Vengeance ................. source 520817, donor 12319 Flurry
    #
    # 520817 is aura 42 into 800058 Felfury at `proc_chance 60`: "Twin Slice and Felrend have a
    # 60% chance to generate 1 additional Felfury". The record has NO number of its own -- the
    # grant is one stack -- so the only cell that can carry three ranks is `ProcChance`, which is
    # a spell-level column and needs no die.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the felfury record (91460). The donor's 12966 is
    # Flurry's own haste buff and must not survive.
    Talent("demonology", 2, 2, 3, "Vengeance", 12319,
           source=520817,
           proc_flags=0x00000010,                # DONE_SPELL_MELEE_DMG_CLASS (SpellMgr.h:116).
                                                 # READ, NOT OBSERVED. Both generators are
                                                 # DefenseType 2 weapon abilities.
           rank_cell="ProcChance",
           rank_values=(20, 40, 60),             # RE-RANKED: Ascension is one node at 60%.
                                                 # ProcChance is not an effect basepoint, so the
                                                 # +1 die convention does not apply to it.
           overrides={
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- dh_donors.BIT["twin_slice"]
               "EffectSpellClassMaskC_1": 0x00000004,   # Felrend
               "Description_Lang_enUS":
                   "Your Twin Slice and Felrend have a $h% chance to generate 1 additional "
                   "Felfury.",
           },
           note="12319 -- aura 42 with an empty mask, the same donor dh_talents uses for its "
                "two proc talents"),

    # -- 2/3 -- Hulking Demon ............. source 805246, donor 56339 Hunter vs. Wild
    #
    # 805246 says "Level 20 Passive" in its own description, which is row 2 under plan 3's
    # `(level - 10) / 5` -- one of the four places Ascension states the depth outright.
    # Two effects: aura 268 MOD_ATTACK_POWER_OF_STAT_PERCENT misc 2 (Stamina) at bp 29, and
    # aura 220 MOD_RATING_FROM_STAT `misc 160 / miscB 1` at bp 5. misc 160 is
    # CR_HIT_MELEE|CR_HIT_SPELL (1<<5 | 1<<7) and miscB 1 is STAT_AGILITY.
    # Only seven stock rows carry aura 268 at all and only Hunter vs. Wild's three ranks are at
    # misc 2 (Stamina), which is what makes 56339 the donor rather than a preference; its
    # Effect_2 (aura 212, ranged AP from the same stat) becomes the rating half.
    Talent("demonology", 2, 3, 2, "Hulking Demon", 56339,
           source=805246,
           rank_cell="EffectBasePoints_1",
           rank_values=(14, 29),                 # RE-RANKED: lands 15/30 % of Stamina as AP
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(2, 5),                 # RE-RANKED: lands 3/6 % of Agility as hit
           overrides={
               "EffectAura_2": 220,              # MOD_RATING_FROM_STAT, from the donor's 212
               "EffectMiscValue_2": 160,         # CR_HIT_MELEE | CR_HIT_SPELL
               "EffectMiscValueB_2": 1,          # STAT_AGILITY
               "Description_Lang_enUS":
                   "Increases your attack power by $s1% of your Stamina and your hit rating by "
                   "$s2% of your Agility.",
           },
           note="56339 -- aura 268 misc 2 verbatim; only the second effect's aura moves"),

    # -- 3/0 -- Demon Hide ................ source 520252 (+520253, +705122), donor 16929
    #
    # THE ONE FORM-GATED PASSIVE IN THIS ROW, and it is free: PASSIVE|DO_NOT_DISPLAY plus a
    # `ShapeshiftMask` naming form 23 is applied on entering Inner Demon and removed on leaving
    # it by `AuraEffect::HandleShapeshiftBoosts` walking the talent map, with no id switch on the
    # path (dh_talents.py:610-616).
    # 520252/520253 are aura 107 misc 12 at bp 119/239 for "Armor contribution from cloth and
    # leather items increased by 120%/240%" -- an op that does not mean that in 3.3.5a. The
    # honest 3.3.5a cell is aura 142 MOD_BASE_RESISTANCE_PCT misc 1, which is what stock 16929
    # Thick Hide uses for the same sentence. DEVIATION, and it is not small: 142 has no
    # cloth-and-leather filter, so this scales ALL base armour. The numbers are Ascension's
    # unchanged, which makes this the loudest tuning risk in the tree.
    # 705122 Bulwark of Azzinoth is the folded-in node; its own number lives in 500031 (aura 87
    # misc 127 at bp -11, i.e. -10% damage taken) and becomes Effect_2 here, ranked rather than
    # frozen (plan 3.4 lists it under the freezes rank_cell_2 removes).
    Talent("demonology", 3, 0, 2, "Demon Hide", 16929,
           source=520252, source_ranks=(520253,),
           rank_cell="EffectBasePoints_1",
           rank_values=(119, 239),               # Ascension's own two ranks, unchanged: 120/240 %
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(-6, -11),              # RE-RANKED: lands -5/-10 % damage taken;
                                                 # 500031's own -10 is rank 2
           overrides={
               "ShapeshiftMask": 0x00400000,     # 1 << (23 - 1). Form 23 is
                                                 # dh_spec.SHAPESHIFT_FORM_ID and the cell is a
                                                 # mask of (form - 1); plan 6.3 renames the
                                                 # constant INNER_DEMON_STANCE, value unchanged.
               "EffectAura_1": 142,              # MOD_BASE_RESISTANCE_PCT, and it is a pin, not
               "EffectMiscValue_1": 1,           # a preference: 520252's own aura 107 misc 12 is
                                                 # SPELLMOD_EFFECT2, so the import would turn
                                                 # 120%/240% armour into a flat +120/+240 on
                                                 # effect 2 of every spell the mask reaches.
                                                 # misc 1 is SPELL_SCHOOL_MASK_NORMAL, armour.
               "EffectSpellClassMaskA_1": 0,     # aura 142 reads no mask; 520252's own arrives
                                                 # with the import and would only be read if the
                                                 # aura pin above were ever dropped
               "Effect_2": 6,                    # APPLY_AURA -- authored, 705122/500031's half
               "EffectAura_2": 87,               # MOD_DAMAGE_PERCENT_TAKEN
               "EffectMiscValue_2": 127,         # all seven schools, as 500031 has it
               "EffectDieSides_2": 1,
               "ImplicitTargetA_2": 1,
               "Description_Lang_enUS":
                   "While Inner Demon is active, your Armor is increased by $s1% and your "
                   "damage taken is reduced by $s2%.",
           },
           note="16929 -- the stock spell whose tooltip is this talent's sentence, at the aura "
                "3.3.5a actually implements it with"),

    # -- 3/1 -- Quick Carving ............. source 520254 (+704611), donor 13742 Endurance
    #
    # 520254 is aura 107 misc 1 SPELLMOD_DURATION at bp -1001, i.e. Carve channels 1 s less. Its
    # second effect (aura 108 misc 19 SPELLMOD_ACTIVATION_TIME at -40%) has no visible job on a
    # channel and is dropped rather than transcribed for the sake of it.
    # 704611 Battle Finesse is the folded-in node: "while channelling Carve your dodge is
    # increased, up to 10%". Its own basepoints are 0 -- the number ramps with channel length,
    # which is the C5 tick counter's business, not a cell's -- so it stays with `spell_fs_carve`
    # at Ascension's 10% ceiling and does not rank. That is a real degradation and it is the
    # reason this talent has one rank cell where the plan pairs two nodes.
    # 13742 is the donor because its own cell is a cooldown spellmod in MILLISECONDS at
    # bp -30001: same aura, same units, only the op moves from 11 to 1.
    Talent("demonology", 3, 1, 2, "Quick Carving", 13742,
           source=520254,
           rank_cell="EffectBasePoints_1",
           rank_values=(-501, -1001),            # RE-RANKED: lands -500/-1000 ms of channel;
                                                 # Ascension's single node is -1000
           overrides={
               "EffectMiscValue_1": 1,           # SPELLMOD_DURATION (SpellDefines.h:77), from
                                                 # the donor's 11 SPELLMOD_COOLDOWN
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x60, Sprint and Evasion
               "EffectSpellClassMaskB_1": 0,     # and its second word, 0x20
               "EffectSpellClassMaskC_1": 0x00000001,   # Carve
               "Effect_2": 0,                    # aura 137 +Stamina, Endurance's other half
               "EffectAura_2": 0,
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Description_Lang_enUS":
                   "Your Carve channels $/1000;s1 sec faster, and you dodge more while "
                   "channelling it.",
           },
           note="13742 -- aura 107 in milliseconds already; Battle Finesse's dodge ramp is "
                "spell_fs_carve's and stays flat at Ascension's 10%"),

    # -- 3/2 -- Felrend ................... source 800210, donor 63753 Fan of Knives         *
    #
    # 800210 at `spell_level 17` is `Effect 121 WEAPON_DAMAGE_NOSCHOOL` plus
    # `Effect 142 TRIGGER_SPELL_WITH_VALUE` into 803476, i.e. a main-hand strike and an off-hand
    # shell, at target 22/15 with radius index 193, for 40 Energy and 1 Felfury.
    # 63753 is plan 6.2's named donor for exactly this shape and it makes the off-hand shell
    # unnecessary: Fan of Knives is a single `Effect 31 WEAPON_PERCENT_DAMAGE` that "throws BOTH
    # weapons", already at 100%, already targetless-AoE at ImplicitTarget 18/16. One record, no
    # bp-0 shell, and therefore none of the `SPELLVALUE_BASE_POINT0` propagation risk plan 7.6
    # names as the way every dual-wield strike in the kit silently deals zero.
    # FELFURY HOLE: the +1 is an authored `Effect 64` at the felfury record (91460), the merge's.
    # It lands in `Effect_2`, which the overrides below clear for exactly that reason.
    Talent("demonology", 3, 2, 1, "Felrend", 63753, flags=1,
           source=800210,
           overrides={
               "SpellClassMask_3": 0x00000004,
               # THE ONE-RECORD ARGUMENT ABOVE IS ONLY TRUE IF THESE SIX CELLS SAY SO. `source`
               # transplants 800210's two effects over Fan of Knives', so without them the record
               # ships Effect 121 plus a dangling Effect 142 -> 803476 and the bp-0-shell risk is
               # back. All six values are read off 63753 itself.
               "Effect_1": 31,                   # WEAPON_PERCENT_DAMAGE, from 121
               "EffectBasePoints_1": 99,         # DieSides 1 -> 100% of both weapons
               "EffectDieSides_1": 1,
               "EffectRadiusIndex_1": 13,
               "ImplicitTargetA_1": 18,
               "Effect_2": 0,                    # 800210's off-hand shell -> 803476, which this
               "EffectBasePoints_2": 0,          # donor does not need and which nothing would
               "EffectDieSides_2": 0,            # renumber
               "ImplicitTargetA_2": 0,
               "ManaCost": 40,                   # Energy, Ascension's; the donor is 30
               "StartRecoveryTime": 1000,        # the house GCD; the donor is already 133/1000
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Erupt in a whirlwind of felfury, striking all nearby "
                   "enemies with both weapons for $s1% weapon damage.",
           },
           note="63753 -- the donor plan 6.2 names for weapon-percent AoE; its EquippedItemClass "
                "2/173555 is cleared by dh_talents.ALWAYS"),

    # -- 3/3 -- Fel Daze .................. source 705131, donor 13733 Puncturing Wounds
    #
    # 705131 is aura 107 misc 7 SPELLMOD_CRITICAL_CHANCE at bp 9 (+10% crit on Fel Fireball) plus
    # aura 42 into 707360, which is aura 54 MOD_HIT_CHANCE at bp -4 (-3% to hit) for 6 s.
    # Only the crit half can rank: the hit debuff's number lives in the shared triggered row, so
    # it stays at Ascension's -3% on both ranks. That is the second of this tree's frozen
    # numbers and it is frozen for the reason plan 3.4 gives, not for lack of a rank cell.
    # TRIGGER HOLE: `EffectTriggerSpell_2` -> 707360's shape (aura 54, DurationIndex 32 = 6000 ms
    # in the stock file). The donor has no trigger of its own, so a forgotten row is a dead
    # effect rather than a wrong one.
    Talent("demonology", 3, 3, 2, "Fel Daze", 13733,
           source=705131,
           proc_flags=0x00010000,                # DONE_SPELL_MAGIC_DMG_CLASS_NEG
                                                 # (SpellMgr.h:134). READ, NOT OBSERVED: Fel
                                                 # Fireball is a ranged magic nuke.
           rank_cell="EffectBasePoints_1",
           rank_values=(4, 9),                   # RE-RANKED: lands +5/+10 % critical strike
           overrides={
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- dh_donors.BIT["fel_fireball"].
                                                 # The donor's 0x4 is Backstab's bit.
               "Effect_2": 6,                    # the donor's Effect_2 is the Mutilate half of
               "EffectAura_2": 42,               # Puncturing Wounds, masked on the SECOND word;
               "EffectBasePoints_2": 0,          # it becomes the hit-debuff proc
               "EffectDieSides_2": 1,
               "EffectMiscValue_2": 0,           # from the donor's 7
               "ImplicitTargetA_2": 1,
               "EffectSpellClassMaskB_2": 0,     # the donor's 0x6
               "Description_Lang_enUS":
                   "Increases the critical strike chance of your Fel Fireball by $s1%, and its "
                   "damage reduces the target's chance to hit.",
           },
           note="13733 -- aura 107 SPELLMOD_CRITICAL_CHANCE; the second effect is repurposed "
                "rather than zeroed, which is one fewer cell than zeroing it and authoring one"),

    # -- 4/0 -- Pure Hatred ............... source 803478 (+801894), donor 13732        [C6]
    #
    # "Hateforged Barrier also scales with your dodge rating." Ascension implements it by
    # re-applying 801894 (aura 107 misc 3 SPELLMOD_EFFECT1, bp 0) on a 9999 ms timer purely to
    # recompute the amount. Plan 4.C6 is explicit that the poll is the thing being ported OUT:
    # no 3.3.5a cell scales a spellmod by a stat, so the amount is written by
    # `spell_fs_stat_spellmod` on a stat-change hook, which also drops Ascension's staleness
    # window.
    # `EffectBasePoints_1` is 0 ON PURPOSE: if the script is missing the talent does nothing,
    # which is the failure mode to prefer over a flat buff nobody chose.
    Talent("demonology", 4, 0, 1, "Pure Hatred", 13732,
           source=803478,
           script="spell_fs_stat_spellmod",
           overrides={
               "EffectAura_1": 107,              # ADD_FLAT_MODIFIER. THIS IS THE PORT: 803478's
               "EffectTriggerSpell_1": 0,        # own e0 is aura 23 firing 801894 every 9999 ms,
               "EffectAuraPeriod_1": 0,          # i.e. the poll itself, and the import brings it
                                                 # in pointing at an id our DBC does not have.
                                                 # 801894's own aura 107 misc 3 moves onto this
                                                 # record and the timer is deleted.
               "EffectMiscValue_1": 3,           # SPELLMOD_EFFECT1 (SpellDefines.h:79), which is
                                                 # the op 801894 uses; from the donor's 14
               "EffectBasePoints_1": 0,          # the script writes the amount from dodge rating
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- BIT["hateforged_barrier"]
               "Description_Lang_enUS":
                   "Your Hateforged Barrier also absorbs damage based on your dodge rating.",
           },
           note="13732 -- a flat spellmod at the op 801894 uses; the amount is the script's, so "
                "the cell stays 0 and a missing script is a no-op"),

    # -- 4/1 -- Annihilan Rituals ......... source 520831, donor 12535               [C5]
    #
    # ->Quick Carving at rank 1, the 0-based floor meaning both of its points -- an arrow onto a
    # 2-rank talent is fully-ranked by stock convention (dh_talents.py:2279-2283).
    # 520831 is one bare `aura 4 DUMMY, bp 0` and the entire talent is in its text: "fully
    # channelling Carve refunds 1 Felfury". Plan 4.C5(d) puts it in `AfterEffectRemove` gated on
    # `GetRemoveMode()`, so that the refund does NOT happen on an interrupt. There is no cell for
    # any of that; the record is a marker the script tests for.
    # 12535 is the marker donor used three times in this tree: family 0, Attributes 464,
    # DurationIndex 21 (infinite), ONE aura-4 DUMMY effect, no mask, no proc flags, no cost, and
    # zero references anywhere under `.work/ac-src/src` -- so nothing about it can leak.
    Talent("demonology", 4, 1, 1, "Annihilan Rituals", 12535, prereq=(3, 1, 1),
           source=520831,
           script="spell_fs_carve",
           overrides={
               "Description_Lang_enUS":
                   "Fully channelling your Carve refunds 1 Felfury.",
           },
           note="12535 -- the cleanest bare-DUMMY passive in the stock file, and it is a marker "
                "on purpose: every number this talent has belongs to spell_fs_carve"),

    # -- 4/2 -- Tyrant's Gaze ............. source 805240, donor 8092 Mind Blast           *
    #
    # 805240 at `spell_level 29` is one `SPELL_EFFECT_SCHOOL_DAMAGE` at bp 219 / ds 1 with a
    # per-level of 4.0, school mask 36 (Fire|Shadow), radius index 14 and 25 chain targets, for
    # 30 Energy on a 10 s cooldown -- and it is usable only below 35% target health.
    # THAT LAST CLAUSE IS FREE: `TargetAuraState = 13` is checked by SpellInfo.cpp:1824 with no
    # code at all (plan 2.2 uses the same cell for Oblivion's execute gate).
    # NOT FREE, and named rather than faked: the tooltip's `$AP*0.35` coefficient and the heal
    # are a `spell_bonus_data` row (plan 6.4.4 lists Tyrant's Gaze by name) and an authored
    # Effect. `Talent` has no `ap_bonus` field, so the merge writes that row from dh_spec's side.
    Talent("demonology", 4, 2, 1, "Tyrant's Gaze", 8092, flags=1,
           source=805240,
           overrides={
               "SpellClassMask_3": 0x00000008,
               "Attributes": 0x00000010,         # IS_ABILITY only. The donor's 0x10000 is
                                                 # NOT_SHAPESHIFTED and would grey this out in
                                                 # Inner Demon.
               "TargetAuraState": 13,            # "target below 35% health", SharedDefines.h:1293
               "SchoolMask": 36,                 # Fire|Shadow, Ascension's; the donor is Shadow
               "RecoveryTime": 10000,
               "ManaCost": 30,                   # Energy
               "StartRecoveryCategory": 133,     # the house GCD, from the donor's 133/1500
               "StartRecoveryTime": 1000,
               "EffectBasePoints_1": 219,        # Ascension's own; lands 220 with the die below
               "EffectDieSides_1": 1,            # from the donor's 5, so the value is a number
                                                 # and not a 5-wide roll
               "EffectRealPointsPerLevel_1": 4.0,      # Ascension's own per-level
               "EffectRadiusIndex_1": 14,        # 8.0 yd, the same index Consecration uses
               "EffectChainTargets_1": 25,       # "and all enemies nearby", Ascension's own
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Set your gaze upon an enemy and all enemies nearby, "
                   "dealing $s1 Shadowflame damage. Only usable below 35% health.",
           },
           note="8092 -- an instant single-target nuke with a category cooldown; its family, "
                "mask, MaxLevel, Shadowform stance and ManaCostPct are all cleared by "
                "TALENT_BASE and ALWAYS, which is most of why it is a safe clone"),

    # -- 4/3 -- Burning Hatred ............ source 805239, donor 12292 Death Wish     [C3] *
    #
    # 805239 at `spell_level 29` is a 120 s, 15 s-duration enrage: aura 354 at bp 49 into 807347
    # (a legal `SPELL_EFFECT_HEALTH_LEECH` row) for "melee damage leeches 50% as Chaos", plus
    # `Effect 175` -- an Ascension-private effect, above TOTAL_SPELL_EFFECTS -- for +6 Felfury.
    # Aura 354 does not exist below TOTAL_AURAS = 317 (SpellAuraDefines.h:380) and importing it
    # is a worldserver ASSERT at SpellMgr.cpp:3039, not a silent no-op. Plan 4.C3 keeps aura 42
    # with the same trigger and the same amount and lets one shared AuraScript do
    # `CastCustomSpell(..., CalculatePct(damage, aurEff->GetAmount()))`.
    # The +6 Felfury is NOT this talent's script: plan 4.C1 puts multi-grants in the module's
    # existing `ALLSPELLHOOK_ON_CAST`, which is registered in code and takes no row.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> 807347's shape (HEALTH_LEECH, bp 0).
    Talent("demonology", 4, 3, 1, "Burning Hatred", 12292, flags=1,
           source=805239,
           script="spell_fs_damage_pct_trigger",
           proc_flags=0x00000014,                # DONE_MELEE_AUTO_ATTACK | DONE_SPELL_MELEE_DMG_
                                                 # CLASS (SpellMgr.h:113,116). READ, NOT
                                                 # OBSERVED: "your melee damage" is both.
           overrides={
               "SpellClassMask_3": 0x00000010,
               "Mechanic": 0,                    # from 31 MECHANIC_ENRAGE, which is what makes
                                                 # Death Wish removable by Tranquilizing Shot --
                                                 # a drawback nobody chose (dh_talents.py:803)
               "RecoveryTime": 120000,           # Ascension's; the donor is 180000
               "DurationIndex": 8,               # 15000 ms (SpellDuration.dbc row 8), Ascension's
                                                 # own index; the donor's row 9 is 30000
               "EffectAura_1": 42,               # PROC_TRIGGER_SPELL, over 805239's own 354
               "EffectBasePoints_1": 49,         # Ascension's own: the script reads GetAmount()
               "EffectMiscValue_1": 0,           # as the percentage, so 49 lands 50%
               "Effect_2": 0,                    # 805239's `Effect 175` (misc 5 -> 800058), the
               "EffectMiscValue_2": 0,           # Ascension-private "+6 Felfury". 175 is above
                                                 # TOTAL_SPELL_EFFECTS 165 and the import puts it
                                                 # in the DBC, where SpellMgr.cpp:3039 ASSERTs on
                                                 # it -- a worldserver STARTUP CRASH. The grant
                                                 # is plan 4.C1's OnSpellCast, so the cell is
                                                 # deleted rather than rewritten.
               "Effect_3": 0,                    # 805239's e3 is `Effect 64 -> 800058`, the +1
               "EffectAura_3": 0,                # Felfury data grant, which would stack on top of
               "EffectBasePoints_3": 0,          # the script's 6. It also names an ASCENSION id
               "EffectDieSides_3": 0,            # that does not exist in our DBC. Deleted for
               "EffectMiscValue_3": 0,           # both reasons. (The donor's own e3, +5% damage
               "ImplicitTargetA_3": 0,           # TAKEN, is what this clears in the degraded path.)
               "Description_Lang_enUS":
                   "Generates 6 Felfury and causes your melee damage to leech $s1% of the "
                   "damage dealt as Chaos damage for $d.",
           },
           note="12292 -- an activated self-buff with a real duration and zero core references; "
                "its aura 79 is repurposed into the leech proc"),

    # -- 5/0 -- Dark Lord ................. source 300470 (+801573), donor 12292      [C7]
    #
    # "While above 75% health, damage taken -X% and damage done +Y%." Ascension polls it: aura 23
    # every 500 ms re-applying 801573, whose two effects are aura 87 misc 127 at bp -6 (-5%) and
    # aura 79 misc 127 at bp 4 (+5%).
    # BOTH EFFECTS LIVE ON THIS RECORD and the PREDICATE is the only thing that moves: plan 4.C7
    # puts ">75% health" on `UnitScript::ModifySpellDamageTaken` / `ModifyMeleeDamage` with
    # `victim->HealthAbovePct(75)`, shared with Annihilan Strike's guaranteed crit.
    # NO `script` VALUE, and that is deliberate rather than missing: plan 6.5 states the
    # ownership split -- `UnitScript` is registered in code and takes no `spell_script_names`
    # row; only `SpellScript`/`AuraScript` are database-bound (ObjectMgr.cpp:6345).
    # KNOWN FAILURE MODE, worth stating because it is the wrong direction: with the UnitScript
    # missing this passive is UNCONDITIONAL, i.e. strictly stronger than intended, rather than
    # inert. The other C-bucket talents in this tree all fail toward doing nothing.
    Talent("demonology", 5, 0, 2, "Dark Lord", 12292,
           source=300470,
           rank_cell="EffectBasePoints_1",
           rank_values=(2, 4),                   # RE-RANKED: lands +3/+5 % damage done
           rank_cell_2="EffectBasePoints_3",
           rank_values_2=(-4, -6),               # RE-RANKED: lands -3/-5 % damage taken;
                                                 # 801573's own -5% is rank 2
           overrides={
               "Attributes": 0x1D0,              # a passive, from the donor's activated
                                                 # 0x8040010
               "DurationIndex": 21,              # infinite; the donor's row 9 is 30000 ms
               "RecoveryTime": 0,                # the donor's 180000
               "Mechanic": 0,                    # from 31 MECHANIC_ENRAGE
               "Effect_1": 6,                    # APPLY_AURA / MOD_DAMAGE_PERCENT_DONE. THE POLL
               "EffectAura_1": 79,               # IS WHAT THIS TALENT EXISTS TO DELETE: 300470's
               "EffectTriggerSpell_1": 0,        # own e0 is aura 23 re-applying 801573 every
               "EffectAuraPeriod_1": 0,          # 500 ms, and the import brings that timer in
                                                 # pointing at an id our DBC does not have. Both
                                                 # of 801573's effects move onto this record.
               "Effect_2": 0,                    # 300470's e1, a bare aura 4 DUMMY (misc 3) that
               "EffectAura_2": 0,                # nothing in 3.3.5a reads. The ">75% health"
               "EffectBasePoints_2": 0,          # predicate is plan 4.C7's UnitScript, not a
               "EffectDieSides_2": 0,            # cell, so the marker implements nothing here.
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 0,
               "Effect_3": 6,                    # APPLY_AURA / MOD_DAMAGE_PERCENT_TAKEN --
               "EffectAura_3": 87,               # authored, because 300470 has only two effects
               "EffectDieSides_3": 1,            # and 801573's second half has to land somewhere
               "ImplicitTargetA_3": 1,
               "EffectMiscValue_3": 127,         # all seven schools, as 801573 has it
               "EffectMiscValue_1": 127,         # all seven schools, from the donor's 1
                                                 # (physical); 801573 is 127 on both effects
               "Description_Lang_enUS":
                   "While above 75% health, your damage done is increased by $s1% and your "
                   "damage taken is reduced by $s3%.",
           },
           note="12292 again -- its Effect_1 aura 79 and Effect_3 aura 87 are the exact pair "
                "801573 carries, which is why the same donor serves a cooldown and a passive"),

    # -- 5/1 -- Straight to the Nether .... source 560503 (+705124), donor 12319 Flurry [C3]
    #
    # 560503 is aura 354 at bp 19 into 705124 (`SPELL_EFFECT_HEALTH_LEECH`, bp 0) -- "while Inner
    # Demon is active, Carve and Sargeron Smite leech 20% of the initial strike". Same rewrite as
    # Burning Hatred: aura 42, same trigger, same amount, one shared script.
    # The form gate is free -- `ShapeshiftMask` plus PASSIVE|DO_NOT_DISPLAY, which the donor's
    # Attributes 0x400c0 already satisfies (0x40|0x80).
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> 705124's shape. The donor's 12966 must not survive.
    Talent("demonology", 5, 1, 2, "Straight to the Nether", 12319,
           source=560503,
           script="spell_fs_damage_pct_trigger",
           proc_flags=0x00000010,                # DONE_SPELL_MELEE_DMG_CLASS (SpellMgr.h:116).
                                                 # READ, NOT OBSERVED.
           rank_cell="EffectBasePoints_1",
           rank_values=(9, 19),                  # RE-RANKED: lands 10/20 % leeched; 560503's
                                                 # own 20% is rank 2
           overrides={
               "ShapeshiftMask": 0x00400000,     # form 23, Inner Demon only
               "EffectAura_1": 42,               # PROC_TRIGGER_SPELL. THE IMPORT IS WHAT MAKES
                                                 # THIS CELL MANDATORY: `source` transplants
                                                 # 560503's own aura 354, which is above
                                                 # TOTAL_AURAS 317 and ASSERTs at
                                                 # SpellMgr.cpp:3039 -- a worldserver STARTUP
                                                 # CRASH, not a dead talent. The donor's own 42
                                                 # does not survive the import.
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- BIT["sargeron_smite"]
               "EffectSpellClassMaskC_1": 0x00000001,   # Carve
               "Description_Lang_enUS":
                   "While Inner Demon is active, your Carve and Sargeron Smite leech $s1% of "
                   "the damage dealt as Shadowflame.",
           },
           note="12319 -- aura 42 into a triggered row, which is all aura 354 ever was"),

    # -- 5/2 -- Illidan's Favor ........... source 520592, donor 14076 Dirty Tricks
    #
    # 520592 has two halves and only one survives. The half that goes is aura 107 misc 17
    # SPELLMOD_JUMP_TARGETS on Manaburn, and it goes because Manaburn goes: plan 7 cuts 805248
    # outright ("its only effect is POWER_BURN bp 0 ds 1 = 1 mana; every number would be
    # invented"). What is left is aura 108 misc 14 SPELLMOD_COST at -101, i.e. Felbane costs
    # nothing.
    # 14076's Effect_2 is that cell at that op already; its Effect_1 (a masked range modifier
    # carrying Blind and Sap's bits on both words) has to go or those bits arrive with it.
    Talent("demonology", 5, 2, 1, "Illidan's Favor", 14076,
           source=520592,
           overrides={
               "Effect_1": 0,                    # aura 107 misc 5 SPELLMOD_RANGE, masked
               "EffectAura_1": 0,
               "EffectBasePoints_1": 0,
               "EffectDieSides_1": 0,
               "EffectMiscValue_1": 0,
               "ImplicitTargetA_1": 0,
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x1000080
               "EffectSpellClassMaskB_1": 0,     # and its second word, the same value
               "EffectBasePoints_2": -101,       # Ascension's own: lands -100% of the cost
               "EffectSpellClassMaskA_2": 0,     # MASK HOLE -- dh_donors.BIT["felbane"]
               "Description_Lang_enUS":
                   "Your Felbane no longer costs Energy.",
           },
           note="14076 Effect_2 -- aura 108 SPELLMOD_COST; the Manaburn half is dropped with "
                "Manaburn (plan 7)"),

    # -- 5/3 -- Doomscarring .............. source 685321, donor 12319 Flurry
    #
    # 685321 is aura 42 into 563271 Doomscar -- which is a BASELINE ability at level 34 (plan
    # 2.1), not a talent record. "Melee critical strikes deal $AP*0.3 extra and apply Doomscar."
    # The record carries no number of its own: the damage and the raid AP debuff are Doomscar's.
    # So `ProcChance` is the rank cell, for the same reason as Vengeance.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the baseline Doomscar id (91509 in plan 5's
    # SINGLES_ORDER). A talent cannot name it and the generator can.
    Talent("demonology", 5, 3, 3, "Doomscarring", 12319,
           source=685321,
           proc_flags=0x00000014,                # DONE_MELEE_AUTO_ATTACK | DONE_SPELL_MELEE_DMG_
                                                 # CLASS (SpellMgr.h:113,116). READ, NOT OBSERVED.
           rank_cell="ProcChance",
           rank_values=(33, 66, 100),            # RE-RANKED: Ascension is one node at 100%
           overrides={
               "Description_Lang_enUS":
                   "Your melee critical strikes have a $h% chance to scar the target with "
                   "Doomscar.",
           },
           note="12319 -- NEEDS a spell_proc row for HitMask PROC_EX_CRITICAL_HIT "
                "(SpellMgr.h:200): 'on a critical strike' is not a ProcTypeMask bit, so this is "
                "one of the six rows plan 4.C0 pays a boot-time log line for"),

    # -- 6/0 -- Nether Strength ........... source 520240 (+520830), donor 12319      [C4]
    #
    # 520240 is aura 42 into 520830, and 520830 is THREE `Effect 165` rows -- an Ascension-private
    # effect -- each `bp -1001 / misc <spell id>`: Hateforged Barrier 705129, Demonic Will 800209
    # and Burning Hatred 805239, one second off each. Plan 4.C4 turns each into
    # `SPELL_EFFECT_DUMMY` with the id in `EffectMiscValue` and the delta in `EffectBasePoints`,
    # read by one table-free script.
    # THE RANK CELL IS ProcChance AND THAT IS A DEGRADATION, stated rather than hidden: the three
    # deltas live on the single shared triggered row, and `SPELLVALUE_BASE_POINT0` reaches only
    # effect 0, so two ranks cannot carry two deltas. Splitting the CHANCE (50%/100%) is the only
    # data-shaped way to rank this at all; Ascension's own node is a flat 100% at -1 s.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the three-DUMMY cooldown row.
    # SCRIPT PLACEMENT, worth being precise about: `spell_fs_modify_cooldown` binds to that
    # TRIGGERED row, not to these rank records. `SCRIPT_NAMES` is rank-keyed today
    # (dh_talents.py:2041-2044), so the merge needs the same field on `Trigger`.
    Talent("demonology", 6, 0, 2, "Nether Strength", 12319,
           source=520240,
           script="spell_fs_modify_cooldown",
           proc_flags=0x00011010,                # the Felfury-spender set, as Abyssal
                                                 # Conditioning. READ, NOT OBSERVED.
           rank_cell="ProcChance",
           rank_values=(50, 100),                # RE-RANKED, and see the note above: the -1 s
                                                 # delta is Ascension's and cannot be ranked
           overrides={
               "Description_Lang_enUS":
                   "Casting a Felfury spender has a $h% chance to reduce the cooldown of your "
                   "Hateforged Barrier, Demonic Will and Burning Hatred by 1 sec.",
           },
           note="12319 -- aura 42; the three cooldown targets are EffectMiscValue on the "
                "triggered row, so no per-talent C++ exists at all"),

    # -- 6/1 -- Hellfire Carver ........... source 707444, donor 12535               [C5]
    #
    # ROW NOTE: 707444's own description says "Level 30 Passive", which plan 3's
    # `(level - 10) / 5` puts at row 4, and plan 3.1's grid puts it at (6,1) with the other Carve
    # talents. The grid wins -- it is the authority for placement -- and the disagreement is
    # written down here rather than silently resolved.
    # The record is a bare `aura 4 DUMMY` and the talent is entirely in its text: after Carve,
    # the next Fel Fireball is instant and chains to up to 10 targets, both scaled by how long
    # the channel ran. Plan 4.C5 says outright that Hellfire Carver reuses `spell_fs_carve`'s
    # tick counter; the chain count is a runtime number and no cell can hold it.
    Talent("demonology", 6, 1, 1, "Hellfire Carver", 12535,
           source=707444,
           script="spell_fs_carve",
           overrides={
               "Description_Lang_enUS":
                   "After channelling Carve, your next Fel Fireball is instant and strikes "
                   "additional enemies based on how long you channelled.",
           },
           note="12535 -- the marker donor again; the tick count Hellfire Carver reads is the "
                "one spell_fs_carve already keeps for Carve itself"),

    # -- 6/2 -- Felblade .................. source 574146 (+804105), donor 12535      [C6]
    #
    # "Level 40 Passive" in Ascension's own text -- row 6 under `(level - 10) / 5`, which is
    # where plan 3.1 puts it.
    # 574146 is aura 23 re-applying 804105 every 1499 ms, and 804105 is three aura-107s with
    # `bp 0`, one per ability: Fel Fireball, Sargeron Smite, Twin Slice all scale with Agility.
    # Plan 4.C6 names the cheaper form explicitly: `SpellScript::OnEffectHitTarget` adding
    # `GetCaster()->GetStat(STAT_AGILITY) * k` on the three ABILITIES, with the talent as the
    # gate. So the rows for `spell_fs_stat_spellmod` land on the ability records (plan 6.4.5
    # extends `spell_script_names` emission to abilities for exactly this), and this record is a
    # marker. A `spell_bonus_data` `ap_bonus` row is NOT a substitute -- it is global per spell
    # id and cannot be gated on owning a talent.
    Talent("demonology", 6, 2, 1, "Felblade", 12535,
           source=574146,
           script="spell_fs_stat_spellmod",
           overrides={
               "EffectAura_1": 4,                # DUMMY -- a marker is only a marker if the poll
               "EffectTriggerSpell_1": 0,        # is deleted. `source` transplants 574146's own
               "EffectAuraPeriod_1": 0,          # aura 23 firing 804105 every 1499 ms, an id our
                                                 # DBC does not have, so the record would ship
                                                 # Ascension's timer pointed at nothing. These
                                                 # three cells are the donor's own e0.
               "Description_Lang_enUS":
                   "The damage of your Fel Fireball, Sargeron Smite and Twin Slice also scales "
                   "with your Agility.",
           },
           note="12535 -- marker; the script rows belong on the three abilities, not on this "
                "record, which is the same indirection Nether Strength needs"),

    # -- 6/3 -- Mannoroth's Rage .......... source 805255, donor 13742 Endurance
    #
    # 805255 is aura 107 misc 11 SPELLMOD_COOLDOWN at bp -60001 (-60 s) plus aura 108 misc 14
    # SPELLMOD_COST at -101 (no Energy cost), both on Burning Hatred.
    # It stays a SEPARATE one-rank talent rather than becoming rank 2 of Burning Hatred, and
    # plan 3.4 gives the reason in one line: "a talent rank is a spell rank: learning rank 2
    # unlearns rank 1, so a 'rank 2' that is a passive would delete the button".
    # 13742's own cell is already a cooldown spellmod in milliseconds; only the value, the mask
    # and the second effect move.
    Talent("demonology", 6, 3, 1, "Mannoroth's Rage", 13742,
           source=805255,
           overrides={
               "EffectBasePoints_1": -60001,     # Ascension's own: lands -60000 ms
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x60, Sprint and Evasion
               "EffectSpellClassMaskB_1": 0,     # and its second word
               "EffectSpellClassMaskC_1": 0x00000010,   # Burning Hatred, this tree's (4,3)
               "EffectAura_2": 108,              # ADD_PCT_MODIFIER, from the donor's 137
               "EffectMiscValue_2": 14,          # SPELLMOD_COST
               "EffectBasePoints_2": -101,       # Ascension's own: lands -100% of the cost
               "EffectSpellClassMaskC_2": 0x00000010,   # Burning Hatred
               "Description_Lang_enUS":
                   "Reduces the cooldown of your Burning Hatred by $/1000;s1 sec and removes "
                   "its Energy cost.",
           },
           note="13742 -- aura 107 SPELLMOD_COOLDOWN in milliseconds; its Stamina half is "
                "repurposed into the cost modifier"),

    # -- 7/0 -- Demonic Fortitude ......... source 805245 (+524634), donor 12319 Flurry
    #
    # 805245 is aura 42 into 524634 (an `Effect 64` at 800058 Felfury) at `proc_chance 20`, with
    # the whole condition in text: "while Demonic Will OR Hateforged Barrier are active".
    # DEVIATION, named: `CasterAuraSpell` is a single id, so 3.3.5a can express "while X" and not
    # "while X or Y". This ships UNCONDITIONAL, which is stronger than Ascension's. The two ways
    # out both cost something -- gate on Demonic Will alone via `CasterAuraSpell` (a generator
    # hole, since that id is the talent band's) and halve the talent, or spend a C7-style
    # `UnitScript` on it. Neither is in the plan, so the deviation is the shipped behaviour.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> the felfury record (91460).
    Talent("demonology", 7, 0, 2, "Demonic Fortitude", 12319,
           source=805245,
           proc_flags=0x00100028,                # TAKEN_MELEE_AUTO_ATTACK | TAKEN_SPELL_MELEE_
                                                 # DMG_CLASS | TAKEN_DAMAGE (SpellMgr.h:114,117,
                                                 # 140). READ, NOT OBSERVED: "damage taken OR
                                                 # avoided" is the taken-attack flags for the
                                                 # avoidance half and TAKEN_DAMAGE for the rest.
           rank_cell="ProcChance",
           rank_values=(10, 20),                 # RE-RANKED: Ascension is one node at 20%
           overrides={
               "Description_Lang_enUS":
                   "While Demonic Will or Hateforged Barrier is active, damage you take or "
                   "avoid has a $h% chance to generate 1 Felfury.",
           },
           note="12319 -- aura 42; the 'while X or Y' gate has no 3.3.5a cell and is dropped"),

    # -- 7/1 -- Vengeance Is Mine ......... source 804822 (+807163), donor 12319 Flurry
    #
    # 804822 is aura 42 into 807163 at `proc_chance 10`, and it is the one node in this tab whose
    # own `proc_flags` is non-zero in the dump (4 = the melee auto-attack bit). 807163 is the
    # buff: aura 108 at +30% damage plus aura 42 into 800060, for the next 10 Twin Slices.
    # The 10-instance budget is the triggered row's `ProcCharges`, not a cell here.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> 807163's shape.
    Talent("demonology", 7, 1, 1, "Vengeance Is Mine", 12319,
           source=804822,
           proc_flags=0x00000028,                # TAKEN_MELEE_AUTO_ATTACK | TAKEN_SPELL_MELEE_
                                                 # DMG_CLASS. READ, NOT OBSERVED -- and note it
                                                 # disagrees with the dump's own `proc_flags 4`
                                                 # (a DONE bit), which cannot be right for a
                                                 # talent that triggers on being attacked.
           overrides={
               "EffectSpellClassMaskA_1": 0,     # MASK HOLE -- dh_donors.BIT["twin_slice"]
               "Description_Lang_enUS":
                   "Dodging or parrying has a $h% chance to make your next 10 Twin Slices deal "
                   "increased damage and generate 1 Felfury.",
           },
           note="12319 -- NEEDS a spell_proc row for HitMask PROC_EX_DODGE|PROC_EX_PARRY "
                "(SpellMgr.h:203-204)"),

    # -- 7/2 -- Expose .................... source 300474 (+300475), donor 12319 Flurry
    #
    # 300474 is aura 42 into 300475, which is the debuff worth having: aura 271
    # MOD_DAMAGE_FROM_CASTER at +10% and aura 197 MOD_ATTACKER_SPELL_AND_WEAPON_CRIT_CHANCE at
    # +3% for the whole raid. Both are ordinary 3.3.5a auras and need nothing.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> 300475's shape (DurationIndex 31 = 8000 ms).
    Talent("demonology", 7, 2, 1, "Expose", 12319,
           source=300474,
           proc_flags=0x00010000,                # DONE_SPELL_MAGIC_DMG_CLASS_NEG
                                                 # (SpellMgr.h:134). READ, NOT OBSERVED: the
                                                 # trigger is "direct Fire and Shadow spell
                                                 # damage", which is the magic damage class.
           overrides={
               "Description_Lang_enUS":
                   "Your direct Fire and Shadow damage applies Expose, increasing the damage "
                   "the target takes from you and your allies' critical strike chance against "
                   "it.",
           },
           note="12319 -- aura 42; both halves of the debuff are stock auras, so the only C++ "
                "anywhere near this talent is none"),

    # -- 7/3 -- Fel Torpedo ............... source 500610, donor 64872 Steam Rush   [C9] *
    #
    # `source` IS 500610, NOT 520853. 520853 is the advancement node and its only content is a
    # bare DUMMY whose text says "transforms your Chaos Rush into Fel Torpedo" -- and 3.3.5a has
    # no data mechanism for swapping a spellbook entry. Plan 4.C9 takes the cheapest port with no
    # C++: make it a granted button that teaches Fel Torpedo ALONGSIDE Chaos Rush. So the record
    # this talent imports is the ability itself.
    # 500610 is entirely data: aura 107 SPELLMOD_RADIUS, `Effect 64` into 802028 (`CHARGE_DEST`)
    # and aura 23 into 500761 for the path damage. 64872 is plan 6.2's named donor for exactly
    # that shape -- `SPELL_EFFECT_CHARGE_DEST` at ImplicitTarget 47, targetless, plus a triggered
    # second effect.
    # Cooldown is a flat 10 s because spell charges do not exist in 3.3.5a (plan 2.2, 7).
    # TWO ABILITY HOLES, and they are holes rather than TRIGGERS rows because both targets are
    # records the ABILITY side numbers: `EffectTriggerSpell_2` -> 802028, which plan 5 gives to
    # `chaos_rush_dash` at 91240, and `EffectTriggerSpell_3` -> 500761, the path damage, which
    # has no block yet. Left absent so the import's Ascension ids are visible to the merge
    # instead of being silently overwritten with zero.
    # NOTE FOR THE TOOLTIP PASS: five tab-87 passives read `$?s520853[Fel Torpedo][Chaos Rush]`;
    # with both buttons present those conditionals resolve to the Fel Torpedo branch and say so
    # even when the player is pressing Chaos Rush.
    Talent("demonology", 7, 3, 1, "Fel Torpedo", 64872, flags=1,
           source=500610,
           overrides={
               "SpellClassMask_3": 0x00000020,
               "RecoveryTime": 10000,            # Chaos Rush's shipped cooldown; the donor's is
                                                 # 15000 and Ascension's is charge-based
               "ManaCost": 55,                   # Energy, 500610's own
               "StartRecoveryCategory": 133,     # the house GCD, from the donor's 133/1500
               "StartRecoveryTime": 1000,
               "Description_Lang_enUS":
                   "Generates 1 Felfury. Torpedo forward, dealing Shadowflame damage to enemies "
                   "in your path. Scales with modifiers to Chaos Rush.",
           },
           note="64872 -- CHARGE_DEST with a triggered rider, the same donor shape the Demon "
                "Hunter's Fel Rush uses; the talent teaches a second button rather than "
                "swapping one, which is what makes C9 cost no C++"),

    # -- 8/0 -- Fel Monstrosity ........... source 500067, donor 16252 Toughness
    #
    # "Level 50 Passive" in Ascension's own text -- row 8, which is where plan 3.1 puts it.
    # 500067 is aura 137 MOD_TOTAL_STAT_PERCENTAGE misc 2 at bp 24 (+25% Stamina) and aura 61
    # MOD_SCALE at bp 9 (+10% size). Its third effect is aura 55 at bp -1, i.e. amount ZERO, and
    # is dropped for the same reason Demonic Will's dodge effect is.
    # Plan 3.4 names the size half as the frozen one; rank_cell_2 unfreezes it, and size is
    # exactly the kind of number that should move with the ranks because it is what the talent
    # LOOKS like.
    # 16252 is dh_talents' own Fel Hardiness donor: family 0, Attributes 464, aura 137 misc 2 at
    # ds 1. Its Effect_2 (aura 232, snare duration) becomes the scale.
    Talent("demonology", 8, 0, 3, "Fel Monstrosity", 16252,
           source=500067,
           rank_cell="EffectBasePoints_1",
           rank_values=(8, 16, 24),              # RE-RANKED: lands +9/+17/+25 % Stamina
           rank_cell_2="EffectBasePoints_2",
           rank_values_2=(3, 6, 9),              # RE-RANKED: lands +4/+7/+10 % size
           overrides={
               "EffectAura_2": 61,               # MOD_SCALE, from the donor's 232
               "EffectMiscValue_2": 0,           # from the donor's 11
               "Description_Lang_enUS":
                   "Increases your Stamina by $s1% and your size by $s2%.",
           },
           note="16252 -- aura 137 misc 2 verbatim; only the second effect's aura moves"),

    # -- 8/2 -- Infernal Whipcrack ........ source 805243, donor 2825 Bloodlust           *
    #
    # 805243 at `spell_level 57` is the raid cooldown: three effects at ImplicitTarget 22/56
    # (caster area party) -- aura 87 at bp -16 (-15% damage taken), aura 192 at bp 9 (+10% melee
    # and ranged haste) and aura 216 at bp 9 (+10% spell haste) -- for 90 s on a 10 s duration.
    # 2825 is the donor because its three effects are already three raid-wide auras at the same
    # implicit target and radius, with `ds 1` on each; only the aura numbers and the values move.
    # A CLONE IS SAFE AND THIS IS THE INTERESTING PART: everything that makes Bloodlust Bloodlust
    # is applied by id and does not follow. `SpellInfoCorrections.cpp:986` sets
    # `ExcludeTargetAuraSpell = 57724` (Sated) on id 2825 only, so the clone has no Sated
    # exclusion and needs none; `spell_dk.cpp:2442` and `SmartScript.cpp:2902` likewise key on
    # the literal id.
    Talent("demonology", 8, 2, 1, "Infernal Whipcrack", 2825, flags=1,
           source=805243,
           overrides={
               "SpellClassMask_3": 0x00000040,
               "Attributes": 0x00000010,         # IS_ABILITY only, over 805243's own 0x10000 --
                                                 # NOT_SHAPESHIFTED, which SpellInfo.cpp:1475
                                                 # turns into SPELL_FAILED_NOT_SHAPESHIFT inside
                                                 # Inner Demon. Same trap as Carve at (1,1) and
                                                 # Ruin in talents_felblood.py.
               "RecoveryTime": 90000,            # Ascension's; the donor is 300000
               "DurationIndex": 1,               # 10000 ms (SpellDuration.dbc row 1),
                                                 # Ascension's own index
               "StartRecoveryTime": 1000,        # the house GCD, from the donor's 1500
               "EffectAura_1": 87,               # MOD_DAMAGE_PERCENT_TAKEN, from 192
               "EffectMiscValue_1": 127,         # all seven schools
               "EffectBasePoints_1": -16,        # Ascension's own: lands -15%
               "EffectAura_2": 192,              # MOD_MELEE_RANGED_HASTE, from the donor's 61
               "EffectBasePoints_2": 9,          # lands +10%
               "EffectAura_3": 216,              # HASTE_SPELLS, from the donor's 65
               "EffectBasePoints_3": 9,          # lands +10%
               "Description_Lang_enUS":
                   "Enrage your party, reducing their damage taken by $s1% and increasing "
                   "their haste by $s2% for $d.",
           },
           note="2825 -- three party-wide auras at one implicit target; its Sated exclusion is "
                "a core correction on the literal id and does not clone"),

    # -- 8/3 -- Betrayer .................. source 300476 (+804336, +520256), donor 12319
    #
    # Two procs on one dodge: 804336 (an off-hand weapon strike at 40%) and 520256 (a raid crit
    # buff). 520256 MUST BE REBUILT and plan 3.4 says why: Ascension has it as aura 290 on SELF
    # with a radius, which reaches nobody in 3.3.5a; it needs
    # `SPELL_EFFECT_APPLY_AREA_AURA_RAID (65)`, which is what 560549 Eye of the Tyrant at (9,3)
    # already uses correctly.
    # TRIGGER HOLES, two of them: `EffectTriggerSpell_1` -> 804336's shape (WEAPON_PERCENT_DAMAGE
    # at 40%, with `SPELL_ATTR3_REQ_OFFHAND`), `EffectTriggerSpell_2` -> the rebuilt 520256.
    Talent("demonology", 8, 3, 1, "Betrayer", 12319,
           source=300476,
           proc_flags=0x00000028,                # TAKEN_MELEE_AUTO_ATTACK | TAKEN_SPELL_MELEE_
                                                 # DMG_CLASS. READ, NOT OBSERVED.
           overrides={
               "Effect_2": 6,                    # APPLY_AURA -- authored; the donor has one
               "EffectAura_2": 42,               # effect and this talent procs two rows
               "EffectBasePoints_2": 0,
               "EffectDieSides_2": 1,
               "ImplicitTargetA_2": 1,
               "Description_Lang_enUS":
                   "Dodging an attack strikes the attacker with your off-hand and enrages your "
                   "party, increasing their critical strike chance.",
           },
           note="12319 -- NEEDS a spell_proc row for HitMask PROC_EX_DODGE; and 520256 is one "
                "of the two records plan 3.4 says must be rebuilt as effect 65"),

    # -- 9/1 -- Grommash's Folly .......... source 805236 (+807426), donor 12319   [C3]
    #
    # Three clauses, and they do not all port the same way. 805236 is aura 42 at bp 24 into
    # 807426 -- itself an aura 354 into 560839, i.e. the same "leech N% of the damage" shape as
    # Burning Hatred, so the C3 script takes it; aura 107 misc 12 at bp 14, which the description
    # calls "+15% melee haste" and which misc 12 (SPELLMOD_EFFECT2) does not mean -- rewritten to
    # aura 138 MOD_MELEE_HASTE, the cell 3.3.5a implements that sentence with; and a Carve crit
    # ramp that "increases up to 60% with each strike based on how long you channel", which is
    # the C5 tick counter's and has no cell.
    # The form gate is free: PASSIVE|DO_NOT_DISPLAY plus `ShapeshiftMask`.
    # TRIGGER HOLE: `EffectTriggerSpell_1` -> 560839's shape (SPELL_EFFECT_HEAL, bp 0).
    Talent("demonology", 9, 1, 1, "Grommash's Folly", 12319,
           source=805236,
           script="spell_fs_damage_pct_trigger",
           proc_flags=0x00000004,                # DONE_MELEE_AUTO_ATTACK (SpellMgr.h:113).
                                                 # READ, NOT OBSERVED: the clause is "critical
                                                 # strikes with AUTO ATTACKS" specifically.
           overrides={
               "ShapeshiftMask": 0x00400000,     # form 23, Inner Demon only
               "EffectBasePoints_1": 24,         # Ascension's own: the script reads GetAmount()
                                                 # as the percentage, so 24 lands 25%
               "Effect_2": 6,                    # APPLY_AURA -- authored
               "EffectAura_2": 138,              # MOD_MELEE_HASTE; not a spellmod, so no mask
               "EffectBasePoints_2": 14,         # Ascension's own: lands +15%
               "EffectDieSides_2": 1,
               "ImplicitTargetA_2": 1,
               "Description_Lang_enUS":
                   "While Inner Demon is active, your melee haste is increased by $s2% and your "
                   "critical auto attacks heal you for $s1% of the damage dealt.",
           },
           note="12319 -- NEEDS a spell_proc row for HitMask PROC_EX_CRITICAL_HIT; the Carve "
                "crit ramp is spell_fs_carve's and is not a cell here"),

    # -- 9/2 -- Taskmaster's Army ......... source 800220, donor 13742 Endurance
    #
    # ->Infernal Whipcrack, the arrow plan 3.1 draws, at rank 0 (it has one rank).
    # 800220 is three aura-107s on Whipcrack: `misc 34` at bp 16, `misc 6` at bp 14 (+15 yd
    # radius) and `misc 11` at bp -30001 (-30 s cooldown).
    # SpellModOp 34 DOES NOT EXIST -- the enum stops at 30 (SpellDefines.h:106,
    # `MAX_SPELLMOD 32`) -- and plan 3.4 says to port it as op 17 SPELLMOD_JUMP_TARGETS, which is
    # what "affects all allies" means in 3.3.5a terms.
    # The donor's own `bp -30001` is bit-for-bit Ascension's cooldown value, which is the reason
    # 13742 is the donor for this talent as well as for two others.
    Talent("demonology", 9, 2, 1, "Taskmaster's Army", 13742, prereq=(8, 2, 0),
           source=800220,
           overrides={
               "EffectSpellClassMaskA_1": 0,     # the donor's Sprint/Evasion bits
               "EffectSpellClassMaskB_1": 0,
               "EffectSpellClassMaskC_1": 0x00000040,   # Infernal Whipcrack
               "EffectAura_2": 107,              # ADD_FLAT_MODIFIER, from the donor's 137
               "EffectMiscValue_2": 6,           # SPELLMOD_RADIUS (SpellDefines.h:82)
               "EffectBasePoints_2": 14,         # Ascension's own: lands +15 yd
               "EffectDieSides_2": 1,
               "EffectSpellClassMaskC_2": 0x00000040,
               "Effect_3": 6,                    # APPLY_AURA -- authored
               "EffectAura_3": 107,
               "EffectMiscValue_3": 17,          # SPELLMOD_JUMP_TARGETS, from Ascension's
                                                 # nonexistent op 34
               "EffectBasePoints_3": 16,         # Ascension's own
               "EffectDieSides_3": 1,
               "ImplicitTargetA_3": 1,
               "EffectSpellClassMaskC_3": 0x00000040,
               "Description_Lang_enUS":
                   "Your Infernal Whipcrack affects all allies, its radius is increased by $s2 "
                   "yds and its cooldown is reduced by $/1000;s1 sec.",
           },
           note="13742 -- its own -30001 IS Ascension's number; op 34 becomes op 17 because 34 "
                "is past MAX_SPELLMOD"),

    # -- 9/3 -- Eye of the Tyrant ......... source 560549, donor 55610 Improved Icy Talons
    #
    # 560549 is `SPELL_EFFECT_APPLY_AREA_AURA_PARTY (65)` carrying aura 192 at bp 9 (+10% melee
    # and ranged haste for the raid) plus aura 166 MOD_ATTACK_POWER_PCT at bp 4 (+5% AP for the
    # caster). Plan 3.4 singles this record out as the one that "already uses 65 correctly", in
    # contrast to Betrayer's 520256.
    # 55610 is the ONLY stock row in the file that pairs effect 65 with aura 192, which makes the
    # donor choice a search result rather than a preference. Its three mask words carry Death
    # Knight bits and all three have to go.
    Talent("demonology", 9, 3, 1, "Eye of the Tyrant", 55610,
           source=560549,
           overrides={
               "Attributes": 0x1D0,              # the donor is 0x50; this is a passive
               "EffectAura_1": 192,              # MOD_MELEE_RANGED_HASTE, from the donor's 138
                                                 # (melee only) -- 560549 grants both
               "EffectBasePoints_1": 9,          # Ascension's own: lands +10%
               "EffectSpellClassMaskA_1": 0,     # the donor's 0x2,
               "EffectSpellClassMaskB_1": 0,     # 0xc01af7
               "EffectSpellClassMaskC_1": 0,     # and 0x400085 -- all Death Knight bits
               "EffectAura_2": 166,              # MOD_ATTACK_POWER_PCT, from the donor's 192
               "EffectBasePoints_2": 4,          # Ascension's own: lands +5%
               "Description_Lang_enUS":
                   "Increases the melee and ranged haste of party and raid members within $a1 "
                   "yds by $s1%, and your attack power by $s2%.",
           },
           note="55610 -- the only stock record pairing SPELL_EFFECT_APPLY_AREA_AURA_PARTY with "
                "aura 192; PowerType 5 and RuneCostID 1205 are cleared by dh_talents.ALWAYS"),

    # -- 10/1 -- Tyrannical Resolve ....... source 804823 (+704233), donor 48707     [C5] *
    #
    # The capstone, at `spell_level 59` -- row 10 under `(level - 10) / 5`, which is how plan 3
    # anchors this tree's depth in the first place.
    # 804823 is aura 69 SCHOOL_ABSORB `misc 127 / miscB 30` on a 180 s cooldown for 30 s, plus a
    # taunt through 704233 (aura 11 MOD_TAUNT at radius index 14). The absorb's `bp -1` means
    # amount ZERO: the number is "ignore N% of all damage taken, up to 100% of your maximum
    # health", which is a running total, not a cell. Plan 4.C5 gives the script two jobs -- cap
    # the absorb at max health and COUNT absorbed instances so expiry can fire a scaled Felfire
    # Blast -- and the counting is why `spell_fs_counter` is the right name of the six.
    # 48707 is the donor: aura 69 with a school mask, a real duration, a real cooldown, and every
    # Death Knight cell on it (PowerType 6, ManaCost 200, RuneCostID 522, CategoryRecoveryTime)
    # cleared by ALWAYS and TALENT_BASE. Its own runic-power energize is `spell_dk.cpp:1069`,
    # bound by spell id, and does not clone.
    # TRIGGER HOLE: `EffectTriggerSpell_2` -> 704233's shape (aura 11 MOD_TAUNT, radius 14,
    # DurationIndex 35 = 4000 ms in the stock file).
    Talent("demonology", 10, 1, 1, "Tyrannical Resolve", 48707, flags=1,
           source=804823,
           script="spell_fs_counter",
           overrides={
               "SpellClassMask_3": 0x00000080,
               "Attributes": 0x00000010,         # IS_ABILITY only, over 804823's own 0x10000
                                                 # NOT_SHAPESHIFTED -- the capstone defensive is
                                                 # the last button that may be uncastable in
                                                 # Inner Demon (SpellInfo.cpp:1475).
               "RecoveryTime": 180000,           # Ascension's; the donor is 45000
               "DurationIndex": 9,               # 30000 ms (SpellDuration.dbc row 9),
                                                 # Ascension's own index; the donor's row 28 is
                                                 # 5000
               "StartRecoveryCategory": 133,     # the house GCD; the donor has none at all
               "StartRecoveryTime": 1000,
               "Effect_1": 6,                    # APPLY_AURA / SCHOOL_ABSORB. 804823 carries the
               "EffectAura_1": 69,               # absorb on e1 and a bare aura 108 on e0, so the
                                                 # import puts ADD_PCT_MODIFIER where the donor
                                                 # had the absorb -- and the misc 127 below would
                                                 # then be SpellModOp 127, which does not exist
                                                 # (MAX_SPELLMOD 32). Without this pin the
                                                 # capstone defensive absorbs nothing.
               "EffectMiscValue_1": 127,         # all seven schools, from the donor's 126
               "EffectMiscValueB_1": 30,         # Ascension's own
               "EffectBasePoints_1": 0,          # the script owns the amount and the cap
               "EffectMechanic_1": 0,            # the donor's 26 MECHANIC_IMMUNE_SHIELD, which
                                                 # would make this dispel-immune for free
               "Effect_2": 64,                   # TRIGGER_SPELL -- the taunt, from the donor's
               "EffectAura_2": 0,                # aura 267 (immunity to a school), which
               "EffectBasePoints_2": 0,          # Tyrannical Resolve does not grant
               "EffectDieSides_2": 0,
               "EffectMiscValue_2": 0,
               "ImplicitTargetA_2": 1,
               "Description_Lang_enUS":
                   "Taunt nearby enemies and ignore a portion of all damage taken for $d, up to "
                   "100% of your maximum health. When it ends, you unleash a Felfire Blast "
                   "scaled by how many times you were struck.",
           },
           note="48707 -- aura 69 with a school mask and a real duration; the absorb amount and "
                "the instance count are spell_fs_counter's, so the cell stays 0"),
)


# =============================================================================================
# SELFTEST
# =============================================================================================

def selftest():
    """Every claim this file makes about its own shape, checked rather than asserted in prose.

    Import-time in dh_talents (dh_talents.py:2180-2419) becomes a function here because this
    file is a plan artefact that has to be runnable on its own before the merge. The merge
    should fold these into that block, where they run on every generator invocation.
    """
    talents = TALENTS_DEMONOLOGY

    # ---- the grid: no two talents in one cell -------------------------------------------
    seen = {}
    for t in talents:
        where = f"demonology ({t.tier},{t.col}) {t.name!r}"
        assert t.tab == "demonology", f"{where}: wrong tab {t.tab!r}"
        assert 0 <= t.tier <= 10, (
            f"{where}: TierID is 0-10; the 5-points-per-tier gate makes 10 the deepest "
            f"reachable row and every stock tree stops there")
        assert 0 <= t.col <= 3, f"{where}: ColumnIndex must be 0-3 (NUM_TALENT_COLUMNS)"
        assert (t.tier, t.col) not in seen, (
            f"{where}: cell already taken by {seen.get((t.tier, t.col))!r}")
        seen[(t.tier, t.col)] = t.name
    assert len(talents) == 37, (
        f"plan 3.1's table has 37 cells; got {len(talents)}. (The plan's heading says 30, which "
        f"is the miscount named in this file's docstring -- the table is the authority.)")

    # ---- max_rank, and the shapes stock uses --------------------------------------------
    for t in talents:
        where = f"demonology ({t.tier},{t.col}) {t.name!r}"
        assert 1 <= t.ranks <= 5, (
            f"{where}: {t.ranks} ranks. Talent.dbc has SpellRank_1..5 and nothing past 5 can be "
            f"stored at all")
        assert t.ranks in (1, 2, 3, 5), (
            f"{where}: {t.ranks} ranks. Stock uses 1, 2, 3 and 5 and NEVER 4 (dh_talents.py:2213)")

    # ---- the per-rank cells --------------------------------------------------------------
    for t in talents:
        where = f"demonology ({t.tier},{t.col}) {t.name!r}"
        for cell, values, which in ((t.rank_cell, t.rank_values, "rank_values"),
                                    (t.rank_cell_2, t.rank_values_2, "rank_values_2")):
            if cell:
                assert len(values) == t.ranks, (
                    f"{where}: {len(values)} {which} for {t.ranks} ranks")
                assert cell not in t.overrides, (
                    f"{where}: {cell!r} is in BOTH overrides and a rank cell; the generator "
                    f"writes overrides first, so the override would be silently discarded")
            else:
                assert not values, f"{where}: {which} with no cell -- nothing would write them"
        assert t.rank_cell or t.ranks == 1, (
            f"{where}: {t.ranks} ranks and no rank_cell, so every rank would be an identical "
            f"record and the extra points would buy nothing")
        assert not (t.rank_cell_2 and not t.rank_cell), (
            f"{where}: rank_cell_2 without rank_cell")
        if t.rank_cell and t.rank_cell_2:
            assert t.rank_cell != t.rank_cell_2, f"{where}: both rank cells name {t.rank_cell!r}"

    # ---- the point budget, against plan 3.1 ---------------------------------------------
    by_row = {row: 0 for row in range(11)}
    for t in talents:
        by_row[t.tier] += t.ranks
    total = sum(by_row.values())
    assert total == 66, (
        f"plan 3.1 states 'Demonology -- 30 talents, 66 points'; this tree full-clears for "
        f"{total}")

    cumulative, run = {}, 0
    for row in range(11):
        run += by_row[row]
        cumulative[row] = run
    # The gate row plan 3.1 prints after the point total, reproduced and checked rather than
    # trusted: it is the cumulative points available through each of rows 0-9.
    assert tuple(cumulative[row] for row in range(10)) == (12, 19, 28, 35, 39, 47, 52, 57, 62,
                                                           65), (
        f"the per-row totals {[cumulative[r] for r in range(10)]} disagree with plan 3.1's "
        f"'gates 12/19/28/35/39/47/52/57/62/65'")

    # ---- reachability: Player::LearnTalent, Player.cpp:14360-14362 ------------------------
    for row in range(1, 11):
        if not any(t.tier == row for t in talents):
            continue
        available = cumulative[row - 1]
        assert available >= row * 5, (
            f"row {row} needs {row * 5} points spent above it and only {available} exist -- "
            f"every talent in it is unreachable (`if (spentPoints < talentInfo->Row * "
            f"MAX_TALENT_RANK) return;`)")

    # ---- the arrows ----------------------------------------------------------------------
    for t in talents:
        if not t.prereq:
            continue
        where = f"demonology ({t.tier},{t.col}) {t.name!r}"
        assert len(t.prereq) == 3, f"{where}: prereq is (tier, col, rank)"
        ptier, pcol, prank = t.prereq
        tail = [x for x in talents if (x.tier, x.col) == (ptier, pcol)]
        assert tail, f"{where}: prerequisite at ({ptier},{pcol}) is not a talent in this tree"
        tail = tail[0]
        assert ptier < t.tier, (
            f"{where}: prerequisite {tail.name!r} is in row {ptier}, which is not EARLIER than "
            f"{t.tier}; TalentFrame_DrawLines cannot draw that arrow and build_talents rejects it")
        assert 0 <= prank < tail.ranks, (
            f"{where}: prerequisite rank {prank} is outside {tail.name!r}'s {tail.ranks} ranks "
            f"(PrereqRank_1 is a 0-BASED floor, so 'fully ranked' is ranks - 1)")

    # ---- the granted actives and their word-3 bits ---------------------------------------
    actives = [t for t in talents if t.flags == 1]
    assert len(actives) == 8, (
        f"plan 3.1 marks eight cells with `*`; got {len(actives)}")
    bits = []
    for t in actives:
        where = f"demonology ({t.tier},{t.col}) {t.name!r}"
        assert t.ranks == 1, (
            f"{where}: Flags = 1 with {t.ranks} ranks would put several ids of the same button "
            f"in the spellbook")
        bit = t.overrides.get("SpellClassMask_3", 0)
        assert bit and not (bit & (bit - 1)), f"{where}: SpellClassMask_3 must be exactly one bit"
        assert bit <= 0x80, (
            f"{where}: {bit:#x} is outside 0x01-0x80, which is Demonology's block as tree 0; "
            f"0x100 upward belongs to Slaying and Felblood")
        bits.append(bit)
    assert len(set(bits)) == len(bits), "two granted actives share a SpellClassMask_3 bit"
    for t in talents:
        if t.flags == 0:
            assert "SpellClassMask_3" not in t.overrides, (
                f"{t.name}: only a granted active may own a word-3 bit")
        for col in ("SpellClassMask_1", "SpellClassMask_2"):
            assert col not in t.overrides, (
                f"{t.name}: {col} belongs to dh_donors' ability kit and its second records")

    # ---- the mask holes, so none of them can be forgotten quietly ------------------------
    #
    # Keyed by grid position, value = the dh_donors keys the cell must become. An effect mask of
    # zero means "every Felsworn spell" (SpellInfo.cpp:1325-1337), so a hole left open is a
    # modifier applying to the whole kit -- which is why they are enumerated rather than trusted
    # to the comments.
    mask_holes = {
        (1, 2): {"EffectSpellClassMaskA_1": "fel_fireball",
                 "EffectSpellClassMaskA_2": "fel_fireball",
                 "EffectSpellClassMaskA_3": "twin_slice|sunder"},
        (2, 2): {"EffectSpellClassMaskA_1": "twin_slice"},
        (3, 3): {"EffectSpellClassMaskA_1": "fel_fireball"},
        (4, 0): {"EffectSpellClassMaskA_1": "hateforged_barrier"},
        (5, 1): {"EffectSpellClassMaskA_1": "sargeron_smite"},
        (5, 2): {"EffectSpellClassMaskA_2": "felbane"},
        (7, 1): {"EffectSpellClassMaskA_1": "twin_slice"},
    }
    for pos, cells in mask_holes.items():
        owner = [t for t in talents if (t.tier, t.col) == pos]
        assert owner, f"mask_holes names {pos}, which is not a talent"
        for cell, keys in cells.items():
            assert owner[0].overrides.get(cell, None) == 0, (
                f"{owner[0].name}: {cell} must be present and 0 until dh_donors owns "
                f"BIT[{keys!r}] -- an absent cell lets the donor's own mask survive")

    # ---- the script names, against plan 4 -------------------------------------------------
    known = {"spell_fs_felfury_spender", "spell_fs_damage_pct_trigger",
             "spell_fs_modify_cooldown", "spell_fs_carve", "spell_fs_stat_spellmod",
             "spell_fs_counter"}
    for t in talents:
        if t.script:
            assert t.script in known, (
                f"{t.name}: {t.script!r} is not one of the six script names plan 4 defines")

    # ---- every Ascension id names a real record ------------------------------------------
    #
    # The dump is the authority plan 3.1's ids were checked against, so the check is run rather
    # than described. It is skipped, loudly, when the file is not there -- this module is a plan
    # artefact and has to import outside a checkout too.
    dump = os.path.join(_REPO_ROOT, "build", "tools", "ascension", "out",
                        "felsworn-family20.json")
    if os.path.exists(dump):
        import json
        with open(dump) as handle:
            records = {row["id"]: row for row in json.load(handle)["spells"]}
        known_ids = set(records)
        for t in talents:
            for sid in (t.source,) + tuple(t.source_ranks):
                assert sid in known_ids, (
                    f"{t.name}: Ascension id {sid} is not in felsworn-family20.json")
        assert len(known_ids) == 858, (
            f"the dump has {len(known_ids)} records, not the 858 plan 3 was written against")

        # ---- the import must not carry an effect the core ASSERTs on ----------------------
        #
        # This is the ONLY check in this file whose failure mode is a worldserver STARTUP CRASH
        # rather than a wrong number: `SpellMgr.cpp:3039-3040` ASSERTs `Effect < 165` and
        # `ApplyAuraName < 317`, and `source` transplants Ascension's own cells, including the
        # private effects 165/175/183 and auras 344/353/354. A comment saying an effect is
        # rewritten is not the rewrite -- only a cell in `overrides` is -- so the two are
        # compared here. Plan 6.4 item 5 asks the generator for the same check; this runs it a
        # stage earlier, where the fix is one line.
        for t in talents:
            for i, e in enumerate(records[t.source]["effects"], start=1):
                eff = t.overrides.get(f"Effect_{i}", e["effect"])
                aura = t.overrides.get(f"EffectAura_{i}", e["aura"])
                assert eff <= 164, (
                    f"{t.name}: {t.source} Effect_{i} = {eff} survives the import; "
                    f"SpellMgr.cpp:3039 ASSERTs on it at startup")
                assert aura <= 316, (
                    f"{t.name}: {t.source} EffectAura_{i} = {aura} survives the import; "
                    f"SpellMgr.cpp:3040 ASSERTs on it at startup")

        # ---- a rank ladder may not land on an aura that throws the amount away -------------
        #
        # Auras 42 PROC_TRIGGER_SPELL, 23 PERIODIC_TRIGGER_SPELL and 4 DUMMY all ignore
        # `EffectBasePoints` -- the number they act on lives in the TRIGGERED record, which is
        # one row shared by every rank. So a talent whose rank cell lands on one of those buys
        # nothing at rank 2 and above, silently. Six of Ascension's tab-18 nodes are exactly that
        # shape and the fix is a cell (aura 231 PROC_TRIGGER_SPELL_WITH_VALUE, which passes the
        # amount through at SpellAuraEffects.cpp:6922-6936, or moving the aura outright), so the
        # check is that the cell is present, not that the number is right.
        inert = {4: "DUMMY", 23: "PERIODIC_TRIGGER_SPELL", 42: "PROC_TRIGGER_SPELL"}
        for t in talents:
            for cell in (t.rank_cell, t.rank_cell_2):
                match = re.match(r"EffectBasePoints_(\d)$", cell or "")
                if not match:
                    continue
                i = int(match.group(1))
                if f"EffectAura_{i}" in t.overrides or f"Effect_{i}" in t.overrides:
                    continue
                effects = records[t.source]["effects"]
                aura = effects[i - 1]["aura"] if i <= len(effects) else 0
                assert aura not in inert, (
                    f"{t.name}: {cell} ranks a value onto {t.source}'s imported aura {aura} "
                    f"{inert[aura]}, which discards it; pin EffectAura_{i}")

        # ---- no granted button may arrive NOT_SHAPESHIFTED --------------------------------
        #
        # `SpellShapeshiftForm.dbc` row 23 copies row 22's `Flags` 0xd8 (dhspells.py:438), which
        # has no SHAPESHIFT_FLAG_STANCE, so `SpellInfo::CheckShapeshift` sets `actAsShifted` and
        # any spell carrying SPELL_ATTR0_NOT_SHAPESHIFTED (0x10000) returns
        # SPELL_FAILED_NOT_SHAPESHIFT (SpellInfo.cpp:1470-1476) for the whole time the player is
        # in Inner Demon. Six of Ascension's own tab-18 actives carry that bit, so the clear is
        # checked here rather than left to whoever writes the next one.
        for t in talents:
            if not t.flags:
                continue
            attrs = t.overrides.get("Attributes", records[t.source]["attributes"][0])
            assert not (attrs & 0x00010000), (
                f"{t.name}: Attributes {attrs & 0xFFFFFFFF:#x} keeps NOT_SHAPESHIFTED, so the "
                f"button greys out inside Inner Demon; override Attributes to clear 0x10000")
    else:
        print(f"skipped the Ascension id check: {dump} is not present")

    return total


if __name__ == "__main__":
    points = selftest()
    print(f"demonology -- {len(TALENTS_DEMONOLOGY)} talents, {points} points, "
          f"{sum(t.ranks for t in TALENTS_DEMONOLOGY)} rank records")
    print(f"{'row':>3} | {'col 0':<24} | {'col 1':<24} | {'col 2':<24} | col 3")
    print("-" * 3 + "-+-" + ("-" * 24 + "-+-") * 3 + "-" * 24)
    for tier in range(11):
        cells = []
        for col in range(4):
            here = [t for t in TALENTS_DEMONOLOGY if (t.tier, t.col) == (tier, col)]
            if not here:
                cells.append(" " * 24)
                continue
            t = here[0]
            star = "*" if t.flags else " "
            arrow = "^" if t.prereq else " "
            cells.append(f"{t.name[:21]:<21}{star}{arrow}{t.ranks}")
        print(f"{tier:>3} | " + " | ".join(cells).rstrip())
    print()
    for t in TALENTS_DEMONOLOGY:
        pre = f"  ->({t.prereq[0]},{t.prereq[1]}) @ rank {t.prereq[2]}" if t.prereq else ""
        ranks = f"+{','.join(str(r) for r in t.source_ranks)}" if t.source_ranks else ""
        print((f"  ({t.tier},{t.col}) {t.name:<24} {t.ranks} rank(s)  source {t.source}{ranks}"
               f"  donor {t.donor:<6} {t.script or '':<28}{pre}").rstrip())
