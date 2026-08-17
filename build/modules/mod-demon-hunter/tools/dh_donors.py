#!/usr/bin/env python3
"""The per-ability Spell.dbc cell overrides, as data. Imported by dh_spec.py.

`.work/dh-parts/donors.md` is the argument; this file is its conclusion. Every number below was
read out of `/srv/wow/data/dbc/Spell.dbc` (donors.md's Appendix A is a machine-generated dump of
all 68 candidate records, and the numbers quoted in the comments are from it), out of
`SpellDuration.dbc` / `SpellRadius.dbc` / `SpellCastTimes.dbc` directly, or out of the pinned
checkout at `.work/ac-src`. Nothing here is recalled, and nothing here is a second copy of
something dh_spec.py already owns.

WHAT AN ENTRY IS
----------------
A custom spell is a byte-for-byte memcpy of a stock record with a handful of named cells
overridden (`acdbc/dbclib.py:10-20`). So a record is built in four passes, in this order:

    1. memcpy the donor                     Ability.donor, or DONORS below for a second record
    2. apply ALWAYS                         the traps of donors.md 1, closed unconditionally
    3. apply OVERRIDES[key]                 this ability's own cells
    4. apply the generator's cells          ID, BaseLevel, SpellLevel, ManaCost, the names,
                                            NameSubtext, the descriptions, RecoveryTime,
                                            EffectTriggerSpell_* and SpellClassSet

ONLY CELLS THAT CHANGE ARE LISTED. Restating a cell at the donor's own value would be a second
place for it to disagree with `Spell.dbc`, which is the exact failure mode the clone design
exists to prevent (`dk_spec.py:331` -- "Deliberately carries NO cell values ... so this object
cannot disagree with Spell.dbc"). Where donors.md's table says "keep", that decision is a comment
here rather than a cell, so the reasoning survives without the duplication.

WHAT THIS FILE DELIBERATELY DOES NOT CARRY
------------------------------------------
  * `SpellClassSet`. dh_spec.CHRCLASS_ROW["SpellClassSet"] is the class family and
    `Ability.family` is its one exception (Vengeful Retreat, 9, `SpellEffects.cpp:5067`).
    Writing 16 here would be a second place to change it.
  * `ID`, `BaseLevel`, `SpellLevel`, `Name_Lang_enUS`, `NameSubtext_Lang_enUS`,
    `Description_Lang_enUS`, `AuraDescription_Lang_enUS` -- the generator's, from the ladder.
  * `RecoveryTime` -- `Ability.cooldown_ms`. donors.md 1.4's rule is that a Demon Hunter cooldown
    lives in `RecoveryTime` and never in a borrowed `Category`, which is why ALWAYS zeroes both
    category cells and no entry below sets a cooldown.
  * `ManaCost` -- `Ability.cost`. ALWAYS zeroes it first; see the note there, it is load-bearing.
  * `EffectTriggerSpell_*` -- must point at the CLONED second record, whose id only the generator
    knows (`dh_spec.spell_id_for`). donors.md 6 lists the four abilities this bites: Fel Rush,
    Immolation Aura, Eye Beam, Infernal Strike.
  * `SpellIconID`, `ActiveIconID`, `SpellVisualID_1/2`, `SpellMissileID` -- donors.md 7.10: read
    but not chosen. That is the icon survey's job (`.work/dh-parts/icon`). Several donors carry a
    visibly wrong one (Double Jump inherits 15666, the shredder's jets; Infernal Strike inherits
    SpellMissileID 621, the warrior leap missile).

UNVERIFIED, carried through from donors.md 7 and repeated at every cell it touches: the
`AuraInterruptFlags` / `ChannelInterruptFlags` / `InterruptFlags` bit meanings, the
`EquippedItemSubclass = 173555` melee-weapon mask, and `50590`'s `AttributesEx2`.
"""

import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TOOLS_DIR)                      # build/modules/mod-demon-hunter
REPO_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "build", "tools"))

from acdbc import dbc_tables                                       # noqa: E402

# =============================================================================================
# THE RECORDS THIS TABLE COVERS
# =============================================================================================
#
# Twenty-nine, in dh_spec's frozen id order: the ten block abilities, the seven second records,
# then the twelve one-row customs in SINGLES_ORDER. The order is fixed because the SpellClassMask
# bit allocation below is derived from it, and a bit that moves silently repoints every talent
# that was keyed on it.
ABILITY_KEYS = (
    # ABILITY_BLOCKS 0-9 -- the ranked/blocked abilities
    "demons_bite", "chaos_strike", "fel_rush", "throw_glaive", "immolation_aura",
    "blade_dance", "fiery_brand", "sigil_of_flame", "soul_cleave", "eye_beam",
    # ABILITY_BLOCKS 10-16 -- second records. Nobody learns any of these.
    "demons_bite_oh", "chaos_strike_oh", "blade_dance_oh", "immolation_tick",
    "eye_beam_tick", "fel_rush_impact", "infernal_strike_impact",
    # SINGLES_ORDER -- one row each
    "double_jump", "glide", "vengeful_retreat", "spectral_sight", "consume_magic", "blur",
    "chaos_nova", "torment", "metamorphosis", "imprison", "darkness", "infernal_strike",
)

# Which learnable ability each second record belongs to. Asserted below against the mask bits:
# a second record carries its PARENT's SpellClassMask_1 bit as well as its own, so one talent
# reaches both halves of a strike. That is Blizzard's own arrangement, read from the file --
# `51723` Fan of Knives and its off-hand half `52874` both carry family 8 mask_2 = 262144.
SECOND_RECORDS = {
    "demons_bite_oh":         "demons_bite",
    "chaos_strike_oh":        "chaos_strike",
    "blade_dance_oh":         "blade_dance",
    "immolation_tick":        "immolation_aura",
    "eye_beam_tick":          "eye_beam",
    "fel_rush_impact":        "fel_rush",
    "infernal_strike_impact": "infernal_strike",
}

# The donor for each second record. The twenty-two learnable abilities take theirs from
# `dh_spec.Ability.donor` and are NOT repeated here.
#
#   52874 Fan of Knives (off-hand)  the stock off-hand half of `63753`, which is the donor all
#                                   three main-hand strikes clone. It already carries
#                                   `AttributesEx3 = 0x1000000`, i.e.
#                                   SPELL_ATTR3_REQUIRES_OFF_HAND_WEAPON
#                                   (`SharedDefines.h:505`), and that bit is the entire mechanism:
#                                   `Spell::Spell` (`Spell.cpp:594-596`) sets
#                                   `m_attackType = OFF_ATTACK` for a `SPELL_DAMAGE_CLASS_MELEE`
#                                   spell that has it, which is what makes the swing use the
#                                   off-hand weapon and flag `PROC_FLAG_DONE_OFFHAND_ATTACK`
#                                   (`Spell.cpp:2254-2255`). It is also already `PowerType=3`,
#                                   `ManaCost=0`, `RangeIndex=2` (melee) and `StartRecovery 0/0`.
#   50590 Immolation                donors.md 3.8 -- the tick 50589 triggers, and the record that
#                                   carries `EffectRealPointsPerLevel_1 = 11.5`.
#   40939 Illidari Flames           donors.md 3.20 -- Illidan's own cone, family 0, radius 20 yd.
#   20153 Immolation (infernal)     donors.md 3.3 offers `40939` or `20153` for the Fel Rush
#                                   impact. `20153` wins: it is a PBAoE burst centred on the
#                                   caster (`ImplicitTargetA_1 = 22 TARGET_SRC_CASTER` +
#                                   `ImplicitTargetB_1 = 15`), and after a forward dash the things
#                                   you dashed through are BEHIND you, where a cone is not. It is
#                                   also family 0 with `Category = 0`, where `40939` carries
#                                   `Category 50` (100 spells, 23 names).
#   52174 Heroic Leap (the landing) donors.md 3.22 -- the triggered half of `6544`.
DONORS = {
    "demons_bite_oh":         52874,
    "chaos_strike_oh":        52874,
    "blade_dance_oh":         52874,
    "immolation_tick":        50590,
    "eye_beam_tick":          40939,
    "fel_rush_impact":        20153,
    "infernal_strike_impact": 52174,
}

# =============================================================================================
# THE SpellClassMask BIT ALLOCATION
# =============================================================================================
#
# `SpellInfo::IsAffected` (`SpellInfo.cpp:1325-1337`) is the whole mechanism by which a talent
# modifies an ability without C++: the modifier's family must equal the spell's, and the
# modifier's mask must overlap the spell's. So the mask is what makes a talent able to name ONE
# Demon Hunter ability instead of all of them.
#
# 96 bits exist across SpellClassMask_1/2/3. Twenty-nine are spoken for:
#
#   SpellClassMask_1 -- the twenty-two LEARNABLE abilities, in dh_spec's frozen id order
#     bit  0  0x00000001  demons_bite            bit 11  0x00000800  glide
#     bit  1  0x00000002  chaos_strike           bit 12  0x00001000  vengeful_retreat  (UNSET)
#     bit  2  0x00000004  fel_rush               bit 13  0x00002000  spectral_sight
#     bit  3  0x00000008  throw_glaive           bit 14  0x00004000  consume_magic
#     bit  4  0x00000010  immolation_aura        bit 15  0x00008000  blur
#     bit  5  0x00000020  blade_dance            bit 16  0x00010000  chaos_nova
#     bit  6  0x00000040  fiery_brand            bit 17  0x00020000  torment
#     bit  7  0x00000080  sigil_of_flame         bit 18  0x00040000  metamorphosis
#     bit  8  0x00000100  soul_cleave            bit 19  0x00080000  imprison
#     bit  9  0x00000200  eye_beam               bit 20  0x00100000  darkness
#     bit 10  0x00000400  double_jump            bit 21  0x00200000  infernal_strike
#     bits 22-31 reserved for abilities 23 and up.
#
#   SpellClassMask_2 -- the seven SECOND RECORDS, in dh_spec's ABILITY_BLOCKS order
#     bit  0  0x00000001  demons_bite_oh         bit  4  0x00000010  eye_beam_tick
#     bit  1  0x00000002  chaos_strike_oh        bit  5  0x00000020  fel_rush_impact
#     bit  2  0x00000004  blade_dance_oh         bit  6  0x00000040  infernal_strike_impact
#     bit  3  0x00000008  immolation_tick
#     bits 7-31 reserved.
#
#   SpellClassMask_3 -- entirely reserved. Nothing is allocated here yet on purpose: talent-
#     granted spells and whatever comes after the first 22 get a clean column rather than the
#     tail of a column somebody has to count into.
#
# EVERY second record also carries its PARENT's SpellClassMask_1 bit (see SECOND_RECORDS). A
# talent that reads "+X% Chaos Strike damage" is one modifier with one bit, and it has to reach
# the off-hand half or it buffs half the ability. Blizzard does exactly this: `52874` carries
# `51723`'s mask, read from the file.
#
# BIT 12 IS ALLOCATED AND DELIBERATELY UNSET. Vengeful Retreat's record must keep
# `SpellClassSet = 9` (donors.md 4 -- `SpellEffects.cpp:5067` makes family 9 the only thing that
# makes `SPELL_EFFECT_LEAP_BACK` go backwards) and therefore must have an all-zero mask, because
# `SpellInfo.cpp:1333` skips the mask test when the MODIFIER's mask is empty and 67 stock family-9
# maskless modifiers exist. Its bit is reserved anyway so that nothing else ever takes it if the
# ability migrates to donors.md 4's option 2 (a module SpellScript) and rejoins the family.
_MASKLESS = ("vengeful_retreat",)


# =============================================================================================
# THE ALWAYS-APPLIED OVERRIDE SET -- donors.md 2
# =============================================================================================
#
# Applied to every clone before the per-ability overrides, so that no ability can quietly inherit
# one of donors.md 1's traps. An ability that genuinely wants a different value overrides it back
# in OVERRIDES (the seven triggered records all put the GCD back to 0/0, and Metamorphosis keeps
# Blizzard's deliberate off-GCD).
ALWAYS = {
    # ---- the traps, closed unconditionally -------------------------------------------------
    "MaxLevel": 0,                  # donors.md 0.6 -- a non-zero MaxLevel both caps CalcValue's
                                    # per-level ramp (SpellInfo.cpp:409-427) and makes
                                    # Unit::CalculateLevelPenalty return < 1 for the spell's whole
                                    # life (Unit.cpp:3203-3222). Eight donors carry one; the worst
                                    # is 348 Immolate at MaxLevel 5 on a BaseLevel 1 spell.
    "Category": 0,                  # donors.md 1.4 -- an inherited category is a cooldown shared
                                    # with every other spell in it, that nobody intended.
    "CategoryRecoveryTime": 0,      # NOT in donors.md 2's list, and it has to be, because zeroing
                                    # Category alone does NOT drop the cooldown that came with it:
                                    # Player::AddSpellAndCategoryCooldowns reads catrec off the
                                    # record (Player.cpp:11122), then Player.cpp:11172-11173 does
                                    # `catrecTime = catrec ? catrec : 0; recTime = rec ? rec :
                                    # catrecTime`, and with cat == 0 the `if (cat && catrec > 0)`
                                    # branch at :11177 is skipped and the else at :11230 applies
                                    # recTime as a plain per-spell cooldown. Evasion's 180000 would
                                    # still be Blur's cooldown. SpellInfo::GetRecoveryTime
                                    # (SpellInfo.cpp:2798) is max() of the two, so the tooltip
                                    # would have agreed with it.
    "ShapeshiftMask": 0,            # donors.md 1.3 -- SpellInfo::CheckShapeshift (:1483) fails the
                                    # cast outright out of form. 50589 and 50590 both carry
                                    # 0x200000, which is warlock Metamorphosis, form 22.
    "ShapeshiftExclude": 0,         # donors.md 1.3
    "SpellClassMask_1": 0,          # donors.md 1.5 -- no donor's mask survives the clone. The
    "SpellClassMask_2": 0,          # ability's own bit is set back in OVERRIDES; a record that
    "SpellClassMask_3": 0,          # sets none (Vengeful Retreat) ends up all-zero on purpose.
    # ---- the energy class ------------------------------------------------------------------
    "PowerType": 3,                 # POWER_ENERGY (SharedDefines.h:260). Nine donors are 0 (mana),
                                    # 56222 and 6544 and 52174 are 1 (rage), 36100 is 2 (focus).
    "ManaCost": 0,                  # THE COST IS WRITTEN BACK BY THE GENERATOR from Ability.cost,
                                    # but it has to start at zero rather than be written only when
                                    # non-zero: 19505 Devour Magic carries ManaCost 100 and 6544
                                    # Heroic Leap carries 150, and the seven second records have no
                                    # Ability object to take a cost from at all.
    "ManaCostPct": 0,               # donors.md 2 -- SpellInfo::CalcPowerCost (:2821-2837) applies
                                    # it as a percentage of MAX power for POWER_ENERGY, so 50589's
                                    # inherited 64 is a 64-Fury ability. Six recommended donors
                                    # carry one: 50589 (64), 1949 (64), 31935 (26), 30283 (27),
                                    # 26573 (22), 348 (17), 20066 (9).
    "RuneCostID": 0,                # donors.md 2 -- no DK donor survives the recommendation list,
                                    # but a rune cost on an energy spell is unrecoverable, so it is
                                    # closed rather than trusted.
    # ---- the global cooldown ---------------------------------------------------------------
    "StartRecoveryCategory": 133,   # donors.md 0.4 -- 133/1000 is what Blizzard puts on every
    "StartRecoveryTime": 1000,      # energy ability read for that survey (1752, 1329, 16511, 6770,
                                    # 51723, 63753). Eleven donors arrive at 0/0 because they are
                                    # creature spells; five more arrive at 1500.
}


# =============================================================================================
# THE PER-ABILITY OVERRIDES -- donors.md 3
# =============================================================================================
#
# Keyed by dh_spec's ability key. Cells only; the reasoning that produced no cell is a comment.

OVERRIDES = {

    # -- 1 -- Demon's Bite ................................ donor 63753 Fan of Knives (family 0)
    #
    # Effect_1 stays 31 SPELL_EFFECT_WEAPON_PERCENT_DAMAGE: "$s1% of your weapon" is level-correct
    # at 1 and at 80 out of one record (donors.md 0.2), which is why nine of these abilities need
    # no rank ladder at all. Nothing else is inherited -- family 0, no mask, Category 0,
    # ShapeshiftMask 0, MaxLevel 0, DefenseType 2, GCD already 133/1000.
    "demons_bite": {
        "SpellClassMask_1": 0x00000001,
        # 63753 is a PBAoE (18 TARGET_DEST_CASTER + 16 TARGET_UNIT_DEST_AREA_ENEMY, radius index
        # 13 = 10.0 yd). Demon's Bite is one target in melee.
        "ImplicitTargetA_1": 6,         # TARGET_UNIT_TARGET_ENEMY (SharedDefines.h:1419)
        "ImplicitTargetB_1": 0,
        "EffectRadiusIndex_1": 0,
        "RangeIndex": 2,                # min 0 / max 5.0 yd, flags 1 -- the melee row, read off
                                        # 52874; the donor's RangeIndex 1 is 0/0, i.e. self only
        "Speed": 0.0,                   # 18.0 is Fan of Knives' thrown-blade travel time
        "EffectBasePoints_1": 79,       # PLACEHOLDER -- 80% weapon damage. The donor's own value
                                        # is 99, i.e. 100%; donors.md says "tuned % - 1" and gives
                                        # no number.
        # The Fury build. Precedent for effect 30 riding on a melee strike is 52331 Wide Swipe:
        # Effect_1=58, Effect_2=30, EffectMiscValue_2=3, ImplicitTargetA_2=1, family 0.
        "Effect_2": 30,                 # SPELL_EFFECT_ENERGIZE (SharedDefines.h:796)
        "EffectBasePoints_2": 19,       # PLACEHOLDER -- 20 Fury, because DieSides 1 adds one
                                        # (SpellInfo.cpp:430-437)
        "EffectDieSides_2": 1,
        "EffectMiscValue_2": 3,         # POWER_ENERGY -- Spell::EffectEnergize reads
                                        # Powers(Effects[i].MiscValue) (SpellEffects.cpp:1903-1906)
        "ImplicitTargetA_2": 1,         # TARGET_UNIT_CASTER -- energize the caster, not the target
    },

    # -- 2 -- Chaos Strike ................................ donor 63753 Fan of Knives (family 0)
    #
    # Demon's Bite's shape with a cost, a school and no energize. The donor's Effect_2 is already
    # 0, so "no energize" is the absence of the four cells above rather than a zeroing.
    "chaos_strike": {
        "SpellClassMask_1": 0x00000002,
        "ImplicitTargetA_1": 6,
        "ImplicitTargetB_1": 0,
        "EffectRadiusIndex_1": 0,
        "RangeIndex": 2,
        "Speed": 0.0,
        "EffectBasePoints_1": 129,      # PLACEHOLDER -- 130% weapon, i.e. the spender hits for
                                        # more than the builder. donors.md says only "a higher %
                                        # than Demon Bite".
        "SchoolMask": 127,              # all seven schools -- what "chaos damage" is in this
                                        # engine. Read off 42133 Chaos Strike, the raid-boss nuke,
                                        # which is the one cell worth taking from it. Safe with
                                        # DefenseType 2: MeleeSpellHitResult is chosen by DmgClass,
                                        # not by school (Unit.cpp:3666-3670), and the school only
                                        # selects resistance. Do NOT set DefenseType 1 to match, or
                                        # the spell stops using the weapon.
        "AttributesEx": 0x08000000,     # SPELL_ATTR1_DISCOUNT_POWER_ON_MISS (SharedDefines.h:434)
                                        # -- refund the Fury on a miss, which is what 1752 does for
                                        # the rogue (its 0x8000200 is this bit plus 0x200
                                        # INITIATE_COMBAT, SharedDefines.h:416). The donor's
                                        # AttributesEx is 0, so this sets exactly the one bit.
                                        # NOTE donors.md 3.2 writes "+0x8000" for this attribute,
                                        # which is SPELL_ATTR1_IMMUNITY_PURGES_EFFECT and
                                        # contradicts the 0x8000200 it quotes one line later; the
                                        # enum is the tiebreaker. Optional in donors.md, taken.
    },

    # -- 3 -- Fel Rush .................................... donor 64872 Steam Rush (family 0)
    #
    # The only CHARGE_DEST record in the file that is simultaneously targetless, player-shaped and
    # family-free. The dash distance is the EFFECT RADIUS, not the range: Spell.cpp:1684-1717 does
    # `dist = Effects[i].CalcRadius(); MovePositionToFirstCollision(pos, dist, angle)`, which is
    # also what makes it stop at a wall instead of clipping through it. AttributesEx7 = 0x40000
    # SPELL_ATTR7_ATTACK_ON_CHARGE_TO_UNIT is kept.
    "fel_rush": {
        "SpellClassMask_1": 0x00000004,
        "EffectRadiusIndex_1": 18,      # 15.0 yd, read from SpellRadius.dbc row 18. The donor's
                                        # row 21 is 35.0 yd, which is a siege engine.
        "RangeIndex": 1,                # 0/0 yd -- the spell has no target. The donor's row 176 is
                                        # max 70 yd.
        "PowerDisplayID": 0,            # 61 is a vehicle power bar, meaningless on a player
        "EffectMechanic_3": 0,          # MECHANIC_SNARE left on an empty effect slot (Effect_3=0).
                                        # Harmless -- GetAllEffectsMechanicMask skips effects that
                                        # fail IsEffect() (SpellInfo.cpp:1905) -- but zeroed for
                                        # the same reason donors.md 3.6 zeroes 74608's copy of it.
        "AttributesEx6": 0x400,         # drop 0x40 SPELL_ATTR6_FLOATING_COMBAT_TEXT_ON_CAST
                                        # (SharedDefines.h:598), which prints combat text on every
                                        # dash; keep 0x400 NO_AURA_LOG (:602).
        # DefenseType stays 1: the dash itself does no damage (the impact record does), and 1
        # routes to MagicSpellHitResult rather than to donors.md 1.2's unmissable branch.
        # StartRecoveryTime 1500 -> 1000 is ALWAYS. EffectTriggerSpell_2 (64871 -> the cloned
        # fel_rush_impact id) and RecoveryTime are the generator's.
    },

    # -- 4 -- Vengeful Retreat ............................ donor 781 Disengage (family 9, KEPT)
    #
    # THE EMPTY DICT IS DELIBERATE. Everything this ability needs is already covered:
    #   * family 9 stays, from dh_spec's Ability.family -- SpellEffects.cpp:5067 passes
    #     `SpellFamilyName != SPELLFAMILY_HUNTER` as JumpTo's `forward`, and Unit.cpp:15497 turns
    #     that into `angle = forward ? 0 : M_PI`. Family 9 is the ONLY thing in the game that makes
    #     a leap go backwards; any other value, including 0 and including 16, turns Vengeful
    #     Retreat into a forward hop with no error and a normal-looking tooltip.
    #   * SpellClassMask_1/2/3 = 0 is ALWAYS, and it is what makes keeping family 9 safe:
    #     SpellInfo.cpp:1333 blocks every masked hunter modifier once our own mask is empty. The
    #     residual exposure is the 67 stock family-9 maskless modifiers, all of which are hunter
    #     talents or hunter set bonuses that a Demon Hunter can never hold
    #     (IsAffectedBySpellMod only fires for modifiers ON THE CASTER, SpellInfo.cpp:1344-1360).
    #   * ManaCostPct 5 -> 0, PowerType 0 -> 3, StartRecovery 0/0 -> 133/1000: all ALWAYS.
    #   * RecoveryTime 25000 is the donor's and is also dh_spec's cooldown_ms, so the generator
    #     writes the same number back.
    # EffectMiscValue_1 = 200 (speedxy 20.0) and EffectBasePoints_1 = 74 with DieSides 1
    # (speedz 7.5) are left at Disengage's own values: donors.md calls them "tuned" and offers no
    # replacement, and these two are a live, shipped, player-facing leap rather than a guess.
    # FLAGGED, both in FLAGGED below: the 133/1000 GCD (stock Disengage is deliberately off-GCD),
    # and the lost `spell_linked_spell 781 -> 56446`, which makes the clone leap once where stock
    # Disengage leaps twice (donors.md 1.7).
    "vengeful_retreat": {},

    # -- 5 -- Glide ....................................... donor 12438 Slow Fall (family 0)
    #
    # The cleanest record in the survey: one FEATHER_FALL aura on the caster, family 0, no mask, no
    # category, no shapeshift, MaxLevel 0, everything else zero. Not 130 (the mage version is cast
    # on other people, ImplicitTargetA_1 = 57 TARGET_UNIT_TARGET_RAID); not 55001 Parachute, whose
    # useful behaviour lives in a script (spell_item.cpp:3572-3588) and does not survive a clone.
    "glide": {
        "SpellClassMask_1": 0x00000800,
        "DurationIndex": 21,            # -1, i.e. infinite, read from SpellDuration.dbc row 21.
                                        # The donor's row 1 is 10000 ms, which would drop a gliding
                                        # player out of the sky mid-flight. The aura ends on
                                        # landing instead, via:
        "AuraInterruptFlags": 33554432,  # 0x2000000, copied from 55001 Parachute, which is the
                                        # only stock precedent for "cancel this on landing".
                                        # UNVERIFIED (donors.md 7.1): the AURA_INTERRUPT_FLAG_*
                                        # enum was not read, so this bit is copied, not decoded.
        # The forward-momentum half.
        "Effect_2": 6,                  # SPELL_EFFECT_APPLY_AURA (SharedDefines.h:772)
        "EffectAura_2": 31,             # SPELL_AURA_MOD_INCREASE_SPEED (SpellAuraDefines.h:94)
        "EffectDieSides_2": 1,
        "ImplicitTargetA_2": 1,
        "EffectBasePoints_2": 29,       # +30% run speed. UNTUNED and possibly INERT: the
                                        # movement recon found that horizontal momentum is
                                        # fixed at takeoff, in which case a speed aura applied
                                        # mid-air changes nothing at all. A number is set rather
                                        # than left at zero so that IF the mechanism works the
                                        # effect exists; if it does not, the forward drift has
                                        # to come from a KNOCK_BACK_DEST on the same record and
                                        # this cell is harmless. Verify in game before believing
                                        # docs/demon-hunters.md 1.1 on this point.
        # EffectMiscValue_1: donors.md 3.5 says "consider 55001's 917504"; the plain Slow Fall does
        # not set it and nothing says what it does, so it is left at 0.
        # The "only while falling" gate is a module OnCheckCast copying
        # spell_item_flexweave_underlay, not a cell (donors.md 1.7).
    },

    # -- 6 -- Double Jump ................................. donor 74608 Jump Jets (family 0)
    #
    # The complete list of SPELL_EFFECT_LEAP_BACK records was enumerated (donors.md 3.6); 74608 is
    # the only one that is already an energy ability with a 1000 ms GCD.
    "double_jump": {
        "SpellClassMask_1": 0x00000400,
        "EffectMiscValue_1": 0,         # THE override. `speedxy = MiscValue / 10.0f`
                                        # (SpellEffects.cpp:5064) and Unit::JumpTo multiplies
                                        # vcos/vsin by speedXY (Unit.cpp:15502-15511), so zero is a
                                        # pure vertical impulse and the leap's direction -- which
                                        # for a non-hunter family is FORWARD -- stops mattering.
        "EffectMechanic_3": 0,          # MECHANIC_SNARE on an empty effect slot; see fel_rush
        "DefenseType": 0,               # from 1. It never touches an enemy, so donors.md 1.2's
                                        # unmissable branch cannot bite, and 0 is the honest value.
        "AttributesEx6": 0x400,         # drop FLOATING_COMBAT_TEXT_ON_CAST -- otherwise every jump
                                        # prints combat text
        # EffectBasePoints_1 stays 149 (speedz 15.0 with DieSides 1, SpellEffects.cpp:5065).
        # donors.md calls it "tuned" and gives no number; 74608 is a real, shipped player ability,
        # so its own value is the defensible default rather than an invented one.
    },

    # -- 7 -- Throw Glaive .............................. donor 31935 Avenger's Shield (family 10)
    #
    # Every stock spell with EffectChainTargets > 1 and DefenseType 3 was enumerated: the only two
    # shapes are Multi-Shot, which fans, and Avenger's Shield, which BOUNCES. A thrown glaive
    # bounces. Kept as-is: EffectChainTargets_1/2 = 3 (retail Throw Glaive hits 3), DefenseType 3
    # (it is what routes to the ranged miss table, Unit.cpp:3668-3670), Speed 35.0 (missile
    # travel), AttributesEx4 = 0x40000 SPELL_ATTR4_BOUNCY_CHAIN_MISSILES (the visual bounce, and
    # the reason for this donor), RangeIndex 4 (30 yd), DurationIndex 1 (10 s).
    # The snare (EffectAura_2 = 33 MOD_DECREASE_SPEED, EffectMechanic_2 = 11 MECHANIC_SNARE) is
    # KEPT: donors.md 3.7 says retail has none but "the daze is free if wanted", and zeroing the
    # aura while leaving Effect_2 = 6 APPLY_AURA would leave a broken effect behind.
    "throw_glaive": {
        "SpellClassMask_1": 0x00000008,
        "SchoolMask": 1,                # Physical, from 2 (Holy) -- it is a thrown weapon
        "EquippedItemClass": 2,         # Weapon, from 4 (Armor)
        "EquippedItemSubclass": 173555,  # the melee-weapon mask -- a Demon Hunter throws its own
                                        # glaives, it does not equip a shield (the donor's 64).
                                        # UNVERIFIED (donors.md 7.6): the value is what 1752,
                                        # 49998, 16511, 6770 and both Fan of Knives records all
                                        # carry identically, but its bits were not decoded against
                                        # ItemTemplate.h.
        # Category 1158 / CategoryRecoveryTime 30000, MaxLevel 59, ManaCostPct 26, PowerType 0 and
        # StartRecoveryTime 1500 are all ALWAYS. EffectBasePoints_1/EffectDieSides_1 are UNTUNED --
        # 31935 has EffectRealPointsPerLevel_* = 0 and is re-ranked by Blizzard across five ranks,
        # so this is one of the few that needs a scaling scheme rather than one record.
    },

    # -- 8 -- Immolation Aura ............................. donor 50589 Immolation Aura (family 5)
    #
    # The ability by name, icon and shape. Its warlock baggage is unusually small: SpellClassSet 5
    # with SpellClassMask_1/2/3 ALL ZERO, so nothing but the family itself comes across. The
    # shapeshift lock is the trap, and ALWAYS closes it on both records -- without that a Demon
    # Hunter can never cast this at all, because form 22 is the warlock's Metamorphosis.
    # Kept: AttributesEx 0x18000 (IMMUNITY_PURGES_EFFECT | IMMUNITY_TO_HOSTILE_AND_FRIENDLY_EFFECTS
    # -- note it does NOT have 0x40 IS_SELF_CHANNELED, so this is a buff, not a channel) and
    # AttributesEx5 0x2000 SPELL_HASTE_AFFECTS_PERIODIC.
    "immolation_aura": {
        "SpellClassMask_1": 0x00000010,
        "ChannelInterruptFlags": 0,     # 31788 on a record that is not a channel; dead cells,
                                        # cleared for hygiene. UNVERIFIED (donors.md 7.2): the bit
                                        # meanings were never decoded, only the raw integer read.
        # ManaCostPct 64 -> 0 is ALWAYS and is worth restating: carried across unchanged it is a
        # 64-Fury ability, because CalcPowerCost takes the percentage of MAX energy.
        # EffectTriggerSpell_1 (50590 -> the cloned immolation_tick id) is the generator's.
        # FLAGGED: Effect_3 / EffectAura_3 = 77 MECHANIC_IMMUNITY with EffectMiscValue_3 = 16
        # MECHANIC_BANDAGE rides along. donors.md 3.8 does not strip it, while 3.20 strips the
        # identical effect off 1949. See FLAGGED.
    },

    # -- 9 -- Blade Dance ................................. donor 63753 Fan of Knives (family 0)
    #
    # The third use of 63753, this time in its own shape: ImplicitTargetA_1 = 18 TARGET_DEST_CASTER
    # + ImplicitTargetB_1 = 16 TARGET_UNIT_DEST_AREA_ENEMY is exactly the PBAoE Blade Dance wants,
    # so the targeting cells Demon's Bite overrides are all left alone here.
    "blade_dance": {
        "SpellClassMask_1": 0x00000020,
        "EffectRadiusIndex_1": 14,      # 8.0 yd (SpellRadius.dbc row 14) -- retail Blade Dance.
                                        # The donor's row 13 is 10.0 yd.
        "Speed": 0.0,                   # Fan of Knives is a thrown visual; Blade Dance is not
        "EffectBasePoints_1": 89,       # PLACEHOLDER -- 90% weapon damage per target. donors.md
                                        # says "tuned % - 1"; the donor's own is 99.
    },

    # -- 10 -- Spectral Sight ............................. donor 34709 Shadow Sight (family 0)
    #
    # The exact ability: DETECT_STEALTH + MOD_INVISIBILITY_DETECT + a self-debuff, already on one
    # record. The stealth aura is 228 SPELL_AURA_DETECT_STEALTH and not 17 MOD_STEALTH_DETECT --
    # both exist, and this was read rather than assumed.
    "spectral_sight": {
        "SpellClassMask_1": 0x00002000,
        # 34709 is the arena orb: it is cast on whoever picks it up, so all three effects target
        # 25 TARGET_UNIT_TARGET_ANY. Left alone with a non-zero family that is also an UNMISSABLE
        # ENEMY-TARGETABLE spell (donors.md 1.2, DefenseType 0), which is the record's only real
        # defect.
        "ImplicitTargetA_1": 1,         # TARGET_UNIT_CASTER
        "ImplicitTargetA_2": 1,
        "ImplicitTargetA_3": 1,
        "RangeIndex": 1,                # 0/0 yd, self -- from row 4 (30 yd)
        "DurationIndex": 1,             # 10000 ms (SpellDuration.dbc row 1) -- retail Spectral
                                        # Sight is 10 s; the donor's row 8 is 15000 ms
        # StartRecovery 0/0 -> 133/1000 is ALWAYS (donors.md 1.1 -- this is an object spell).
        # EffectBasePoints_3 stays 4, i.e. +5% damage taken, with EffectMiscValue_3 = 127 (all
        # schools) already correct. FLAGGED: dh_spec's one-line summary says "at the cost of
        # speed", which would be aura 33 MOD_DECREASE_SPEED instead. donors.md 3.10 says the
        # damage-taken form is what retail does; the two disagree and the owner has to pick.
    },

    # -- 11 -- Consume Magic .............................. donor 19505 Devour Magic (family 5)
    #
    # THE SHARPEST ID-FREE TRAP IN THE SURVEY, and neither cell looks dangerous alone:
    # SpellEffects.cpp:2689 reads `SpellFamilyName == SPELLFAMILY_WARLOCK && GetCategory() ==
    # SPELLCATEGORY_DEVOUR_MAGIC` (12, SpellMgr.h:43) and then casts 19658 on the caster. A clone
    # that keeps BOTH family 5 and Category 12 gives Consume Magic a hidden self-heal. ALWAYS
    # zeroes Category and dh_spec sets the family, so it is closed from both sides.
    # ImplicitTargetA_1 = 25 TARGET_UNIT_TARGET_ANY is KEPT -- friend or enemy is exactly what an
    # offensive dispel needs -- and is safe here because DefenseType is 1, which routes to
    # MagicSpellHitResult rather than to donors.md 1.2's unmissable branch.
    "consume_magic": {
        "SpellClassMask_1": 0x00004000,
        "EffectBasePoints_2": 0,        # 233 is the felhunter heal amount that the branch above
        "EffectDieSides_2": 0,          # reads, left on an empty effect slot (Effect_2 = 0)
        # MaxLevel 36, Category 12, CategoryRecoveryTime 8000 (which becomes RecoveryTime via
        # dh_spec's cooldown_ms), ManaCost 100, PowerType 0 and StartRecoveryTime 1500 are ALWAYS.
        # SchoolMask 32 (Shadow) is kept: donors.md offers 4 (Fire) and gives no reason to prefer
        # it, and a shadow-school dispel is not wrong for this class.
    },

    # -- 12 -- Blur ....................................... donor 5277 Evasion (family 8)
    #
    # EffectBasePoints_1 stays 49, i.e. +50% dodge, because retail Blur is +50% dodge and the
    # donor already is. DurationIndex 8 (15 s) is kept. PowerType is already 3 -- one of the few
    # donors that needs no resource change. Category 66 brings a 180-second cooldown with it; see
    # the CategoryRecoveryTime note in ALWAYS for why zeroing Category alone would not have
    # removed it.
    "blur": {
        "SpellClassMask_1": 0x00008000,
        # The damage-reduction half, copied from 31224 Cloak of Shadows' Effect_3 with a bigger
        # number and all schools. Precedents for the aura+misc pair read from the file: 65070
        # (-91 / 127) and 34709 (4 / 127).
        "Effect_2": 6,                  # SPELL_EFFECT_APPLY_AURA
        "EffectAura_2": 87,             # SPELL_AURA_MOD_DAMAGE_PERCENT_TAKEN
                                        # (SpellAuraDefines.h:150)
        "EffectBasePoints_2": -21,      # PLACEHOLDER -- -20%, donors.md 3.12's number. Negative is
                                        # the reduction; DieSides 1 adds one.
        "EffectDieSides_2": 1,
        "EffectMiscValue_2": 127,       # all schools
        "ImplicitTargetA_2": 1,
    },

    # -- 13 -- Chaos Nova ................................. donor 30283 Shadowfury (family 5)
    #
    # A reticle-placed nova re-centred on the caster. EffectRadiusIndex_1/2 = 14 (8.0 yd) and
    # DurationIndex 27 (3000 ms of stun) are kept, as is EffectRealPointsPerLevel_1 = 1.6 -- that
    # cell is why this needs no rank ladder (donors.md 0.5), though its value has to be rescaled to
    # the learn level, so it is in UNTUNED with the base points.
    "chaos_nova": {
        "SpellClassMask_1": 0x00010000,
        "ImplicitTargetA_1": 18,        # TARGET_DEST_CASTER (SharedDefines.h:1427) -- centre it on
        "ImplicitTargetA_2": 18,        # the caster instead of on a placed destination
        "ImplicitTargetB_1": 16,        # TARGET_UNIT_DEST_AREA_ENEMY -- the A/B pattern 63753,
        "ImplicitTargetB_2": 16,        # 26573 and 20549 all use
        "Targets": 0,                   # drop 64 TARGET_FLAG_DEST_LOCATION (SpellInfo.h:53) or the
                                        # client still asks for a ground reticle
        "Mechanic": 12,                 # MECHANIC_STUN (SharedDefines.h:1325). donors.md 1.6: with
                                        # family 16 unknown to GetDiminishingReturnsGroupForSpell
                                        # (SpellMgr.cpp:107-263) the mechanic is the ONLY DR input
                                        # this class has. EffectMechanic_2 is already 12 and
                                        # GetAllEffectsMechanicMask unions both, so this is belt
                                        # and braces -- set anyway, because a stun with no DR is
                                        # PvP-broken in the other direction.
        "SchoolMask": 127,              # all schools, for the same reason Chaos Strike takes it;
                                        # the donor is 32 (Shadow) and donors.md offers 4 or 127
        # StartRecoveryTime 500 -> 1000 (500 is a warlock-specific reduced GCD), Category 250,
        # CategoryRecoveryTime 20000, MaxLevel 59 and ManaCostPct 27 are all ALWAYS.
    },

    # -- 14 -- Torment .................................... donor 56222 Dark Command (family 15)
    #
    # Nothing per-ability but the bit. Category 82 (46 spells, 14 names) and its 8000 ms, PowerType
    # 1 (rage), ManaCost, and the off-GCD 0/0 are all handled by ALWAYS; RangeIndex 4 (30 yd) is
    # retail Torment's range and DurationIndex 27 (3 s) is the taunt. DefenseType stays 1, which
    # routes to MagicSpellHitResult -- 0 would make it unmissable (donors.md 1.2).
    # Taunt DR is free and family-proof: SpellMgr.cpp:112-115 returns DIMINISHING_TAUNT for any
    # spell with SPELL_AURA_MOD_TAUNT, before the family switch is ever reached, and this record's
    # EffectAura_2 is 11.
    # Not 355 Taunt (ShapeshiftMask 0x20000, Defensive Stance) and not 62124 Hand of Reckoning: it
    # is the one donor in the survey with a SpellInfoCorrections entry (:549-553), which a clone
    # silently would not get.
    "torment": {
        "SpellClassMask_1": 0x00020000,
    },

    # -- 15 -- Fiery Brand ................................ donor 348 Immolate (family 5)
    #
    # The worst family drag-in in the set -- 81 warlock modifier effects across 40 names reach
    # family 5 mask 4 -- and the worst MaxLevel: 5, on a BaseLevel 1 spell. Both are ALWAYS.
    # DurationIndex 8 (15 s) and AttributesEx4 0x100000 AURA_NEVER_BOUNCES are kept.
    "fiery_brand": {
        "SpellClassMask_1": 0x00000040,
        # The mitigation half. 348's Effect_3 is 77 SPELL_EFFECT_SCRIPT_EFFECT, and the script does
        # not come with the clone, so the slot is free and is rebuilt as the aura Fiery Brand
        # actually needs: the branded target DEALS less damage. Precedent read from the file --
        # 38240 Chilling Touch is EffectAura_1 = 79, EffectBasePoints_1 = -76, EffectMiscValue_1 =
        # 126; 47241 uses the same aura positively with EffectMiscValue_3 = 127.
        "Effect_3": 6,                  # SPELL_EFFECT_APPLY_AURA, from 77 SCRIPT_EFFECT
        "EffectAura_3": 79,             # SPELL_AURA_MOD_DAMAGE_PERCENT_DONE
                                        # (SpellAuraDefines.h:142)
        "EffectBasePoints_3": -41,      # PLACEHOLDER -- -40%, donors.md 3.15's number
        "EffectDieSides_3": 1,
        "EffectMiscValue_3": 127,       # ALL schools including physical, because Fiery Brand is a
                                        # tank cooldown; 38240's 126 excludes physical
        "CastingTimeIndex": 1,          # 0 ms (SpellCastTimes.dbc row 1); Fiery Brand is instant
                                        # and the donor's row 5 is a 2000 ms cast
        "RangeIndex": 2,                # melee (0/5 yd, flags 1), from row 4 (30 yd)
        # ImplicitTargetA_3 is already 6 TARGET_UNIT_TARGET_ENEMY, so only the die needed setting.
        # EffectBasePoints_1 (the DoT tick), EffectBasePoints_2 and EffectRealPointsPerLevel_2 (the
        # direct hit) are UNTUNED.
    },

    # -- 16 -- Metamorphosis .............................. donor 47241 Metamorphosis (family 5)
    #
    # DurationIndex 9 (30 s) is kept; RecoveryTime 180000 is both the donor's and dh_spec's.
    "metamorphosis": {
        "SpellClassMask_1": 0x00040000,
        "EffectMiscValue_1": 23,        # THE override, and it is invisible unless you know that
                                        # effect 6 / aura 36 SPELL_AURA_MOD_SHAPESHIFT reads its
                                        # MiscValue as the form id. 22 is the WARLOCK's
                                        # Metamorphosis; SpellShapeshiftForm.dbc rows 23 and 24 are
                                        # entirely blank in stock (read directly: name '', flags 0,
                                        # every display and preset id 0), which is why taking 23
                                        # means nothing else in the game has an opinion about being
                                        # in it. dh_spec.SHAPESHIFT_FORM_ID is the same 23.
        "StartRecoveryCategory": 0,     # KEEP the donor's 0/0 against ALWAYS. This is one of
        "StartRecoveryTime": 0,         # Blizzard's deliberate off-GCD player abilities
                                        # (donors.md 0.4 lists 5277, 781, 56222, 355, 62124, 47241)
                                        # and retail Metamorphosis is off-GCD too. FLAGGED.
        # EffectBasePoints_2 (599 = +600% armour, a warlock TANK cooldown) and EffectBasePoints_3
        # (19 = +20% damage) are UNTUNED -- donors.md says "tuned" and gives no number, and +600%
        # armour on a Havoc-shaped class is not a number to inherit by accident.
        # spell_linked_spell -47241 -> -50589 ("remove Immolation Aura") is NOT inherited, and
        # should not be: the DH Immolation Aura is not form-gated (donors.md 1.7).
    },

    # -- 17 -- Imprison ................................... donor 20066 Repentance (family 10)
    #
    # Not 710 Banish: its EffectAura_2 = 39 SCHOOL_IMMUNITY with MiscValue 127 makes the target
    # INVULNERABLE, and Mechanic 18 puts it in DIMINISHING_BANISH.
    # Kept, and load-bearing: Mechanic = 14 MECHANIC_KNOCKOUT (SharedDefines.h:1327) is what lands
    # this in DIMINISHING_DISORIENT once the family is unknown (SpellMgr.cpp:275-276) -- and that
    # path also requires SpellIconID != 292, so the icon survey must not pick 292 for this one.
    # AuraInterruptFlags = 2 is kept as "breaks on damage", which is what makes this an
    # incapacitate rather than a stun; UNVERIFIED (donors.md 7.1), the bit was not decoded.
    # RangeIndex 3 (min 0 / max 20.0 yd) and DurationIndex 3 (60000 ms) are kept -- donors.md 7.5
    # records them as "not looked up", but Appendix A resolves both against SpellRange.dbc and
    # SpellDuration.dbc, and 20 yd / 60 s is retail Imprison.
    "imprison": {
        "SpellClassMask_1": 0x00080000,
        "TargetCreatureType": 0,        # 118 is Repentance's "Demons, Dragonkin, Giants, Humanoids
                                        # and Undead" whitelist -- a silent gate that makes the
                                        # spell uncastable on everything else with no error worth
                                        # reading. 0 means anything.
        "SchoolMask": 32,               # Shadow, from 2 (Holy). donors.md offers 32 or 4.
        # ManaCostPct 9, PowerType 0 and StartRecoveryTime 1500 are ALWAYS.
    },

    # -- 18 -- Sigil of Flame ............................. donor 26573 Consecration (family 10)
    #
    # The persistent-area-aura machinery WITHOUT a script: Effect_1 = 27 PERSISTENT_AREA_AURA with
    # EffectAura_1 = 3 PERIODIC_DAMAGE directly on it, EffectAuraPeriod_1 = 1000. 43265 Death and
    # Decay is the reticle-placed version of the same shape but its aura is 226 PERIODIC_DUMMY,
    # which does nothing without spell_dk_death_and_decay -- so its TARGETING is copied here and
    # its record is not. DurationIndex 31 (8000 ms), EffectRadiusIndex_1 14 (8.0 yd) and
    # AttributesEx 0x10000088 (NO_REDIRECTION | NO_REFLECTION | NO_AURA_ICON) are kept.
    "sigil_of_flame": {
        "SpellClassMask_1": 0x00000080,
        "ImplicitTargetA_1": 28,        # TARGET_DEST_DYNOBJ_ENEMY (SharedDefines.h:1436), copied
                                        # from 43265; the donor drops it at the caster's feet (18)
        "Targets": 64,                  # TARGET_FLAG_DEST_LOCATION (SpellInfo.h:53) -- this is
                                        # what gives the client a ground reticle at all
        "RangeIndex": 4,                # 0/30 yd, so the reticle has a range to be placed within;
                                        # the donor's row 1 is 0/0
        "SchoolMask": 4,                # Fire, from 2 (Holy) -- it is a sigil of FLAME
        # MaxLevel 29, Category 932 + 8000, ManaCostPct 22, PowerType 0 and StartRecoveryTime 1500
        # are ALWAYS. EffectBasePoints_1 is UNTUNED.
        # The 2-second arm time has NO Spell.dbc cell and is not solvable here; see FLAGGED.
    },

    # -- 19 -- Soul Cleave ................................ donor 63753 Fan of Knives (family 0)
    #
    # A frontal cleave with the heal on the same record rather than as a triggered spell. Not 49998
    # Death Strike, whose heal is not in the record at all (Effect_3 = 3 DUMMY; the number comes
    # from spell_dk_death_strike reading DamageMultiplier), and not 845 Cleave, whose
    # Attributes bit 0x4 SPELL_ATTR0_ON_NEXT_SWING queues it for the next auto-attack.
    # EffectBasePoints_1 stays 99 (100% weapon): donors.md 3.19's table does not touch it.
    "soul_cleave": {
        "SpellClassMask_1": 0x00000100,
        "ImplicitTargetA_1": 104,       # TARGET_UNIT_CONE_ENEMY_104 (SharedDefines.h:1512) -- the
                                        # frontal cone 46968 Shockwave uses with radius index 13
        "ImplicitTargetB_1": 0,         # a cone target needs no B
        "RangeIndex": 2,                # melee
        "Speed": 0.0,
        "MaxTargets": 5,                # retail hits 5; 20549 War Stomp is the stock precedent for
                                        # using MaxTargets at all
        # The self-heal. Stock pattern read from the file: 36100 Ravenous Bite is Effect_1 = 2
        # SCHOOL_DAMAGE, Effect_2 = 10 HEAL, ImplicitTargetA_2 = 1, family 0, BaseLevel 1.
        "Effect_2": 10,                 # SPELL_EFFECT_HEAL (SharedDefines.h:776)
        "EffectDieSides_2": 1,
        "ImplicitTargetA_2": 1,         # TARGET_UNIT_CASTER
        # EffectRadiusIndex_1 stays 13 (10.0 yd). EffectBasePoints_2 (the heal) is UNTUNED.
    },

    # -- 20 -- Eye Beam ................................... donor 1949 Hellfire (family 5)
    #
    # The only stock construction that is actually channelled AND periodically triggers another
    # spell: AttributesEx 0x18040 includes 0x40 SPELL_ATTR1_IS_SELF_CHANNELED
    # (SharedDefines.h:413), with EffectAura_1 = 23 PERIODIC_TRIGGER_SPELL on the caster. That
    # attribute and ChannelInterruptFlags 31756 are kept (the flag bits are UNVERIFIED,
    # donors.md 7.2). MaxLevel 40, ManaCostPct 64 and StartRecoveryTime 1500 are ALWAYS.
    "eye_beam": {
        "SpellClassMask_1": 0x00000200,
        "EffectAuraPeriod_1": 500,      # four ticks in two seconds rather than two; donors.md 3.20
                                        # offers 500 or the donor's 1000, and AttributesEx5 0x2000
                                        # SPELL_HASTE_AFFECTS_PERIODIC already applies to it
        "DurationIndex": 39,            # 2000 ms, read from SpellDuration.dbc row 39 (the same row
                                        # 52174 uses, resolved in Appendix A). This is the "a
                                        # suitable row was not looked up" hole donors.md 7.5
                                        # records for Eye Beam; the donor's row 8 is 15000 ms,
                                        # which would be a fifteen-second channel.
        # Hellfire damages the CASTER every tick. Eye Beam does not, so Effect_2 goes entirely --
        # and with it the die and target cells that would otherwise sit on a dead slot.
        "Effect_2": 0,
        "EffectAura_2": 0,
        "EffectBasePoints_2": 0,
        "EffectDieSides_2": 0,
        "EffectRealPointsPerLevel_2": 0.0,
        "EffectAuraPeriod_2": 0,
        "ImplicitTargetA_2": 0,
        # Effect_3 is EffectAura_3 = 77 MECHANIC_IMMUNITY / EffectMiscValue_3 = 16
        # MECHANIC_BANDAGE -- warlock baggage, not a Demon Hunter ability.
        "Effect_3": 0,
        "EffectAura_3": 0,
        "EffectBasePoints_3": 0,
        "EffectDieSides_3": 0,
        "EffectMiscValue_3": 0,
        "ImplicitTargetA_3": 0,
        # EffectTriggerSpell_1 (5857 -> the cloned eye_beam_tick id) is the generator's.
    },

    # -- 21 -- Darkness ................................... donor 65070 Defense Matrix (family 0)
    #
    # Exactly the ability already: a persistent area aura carrying MOD_DAMAGE_PERCENT_TAKEN on
    # allies only (ImplicitTargetB_1 = 31 TARGET_UNIT_DEST_AREA_ALLY, kept), with
    # AttributesEx5 = 0x40000000 SPELL_ATTR5_ALWAYS_SHOW_GROUND_TEXTURE -- the flag that draws the
    # circle on the ground, and the reason to prefer this record over building one. DefenseType
    # stays 0: it only ever touches allies, so donors.md 1.2 does not bite.
    "darkness": {
        "SpellClassMask_1": 0x00100000,
        "ImplicitTargetA_1": 28,        # TARGET_DEST_DYNOBJ_ENEMY, the same reticle placement
                                        # Sigil of Flame copies from 43265. The donor's 63
                                        # TARGET_DEST_TARGET_ANY needs a unit target to place the
                                        # zone on, which a self-cast defensive does not have.
        "Targets": 64,                  # TARGET_FLAG_DEST_LOCATION, the reticle
        "EffectBasePoints_1": -21,      # PLACEHOLDER -- -20%, donors.md 3.21's number. The donor's
                                        # -91 is -90%, a boss mechanic.
        "EffectRadiusIndex_1": 14,      # 8.0 yd (SpellRadius.dbc row 14), which is retail Darkness
                                        # per donors.md 3.21's own note; the donor's row 37 is
                                        # 7.0 yd and the two rows donors.md offers (13 = 10 yd,
                                        # 18 = 15 yd) are both wider than what it says retail is
        "CastingTimeIndex": 1,          # 0 ms; the donor's row 16 is a 1500 ms cast
        "DurationIndex": 31,            # 8000 ms (SpellDuration.dbc row 31, the row 26573 uses) --
                                        # retail is 8 s; the donor's row 8 is 15000 ms
        "InterruptFlags": 0,            # 47 on a creature spell. UNVERIFIED bit meanings
                                        # (donors.md 7.2), which is itself the reason to clear it
                                        # rather than carry it.
        # StartRecovery 0/0 -> 133/1000 is ALWAYS (donors.md 1.1 -- creature spell).
    },

    # -- 22 -- Infernal Strike ............................ donor 6544 Heroic Leap (family 0)
    #
    # Family 0 with no mask, and on 3.3.5a not a learnable player spell, which is exactly why it is
    # clean. Kept: Targets = 64 (the reticle IS the ability); the arc cells EffectMiscValue_1 = 10/
    # EffectMiscValueB_1 = 75 / EffectMultipleValue_1 = 4.0, which Spell::CalculateJumpSpeeds
    # (SpellEffects.cpp:1154-1178) reads as min arc 1.0, max arc 7.5 and speed multiplier 4;
    # Effect_3's MECHANIC_IMMUNITY to 7 MECHANIC_ROOT (the "removes immobilisation" half);
    # DurationIndex 407 (100 ms); AttributesEx2 0x4 IGNORE_LINE_OF_SIGHT.
    "infernal_strike": {
        "SpellClassMask_1": 0x00200000,
        "RangeIndex": 4,                # 0/30 yd -- retail Infernal Strike is 30 yd, and the
                                        # donor's row 95 has a MIN range of 8.0 yd, i.e. it cannot
                                        # be aimed at anything close
        "AttributesEx6": 0x400,         # drop FLOATING_COMBAT_TEXT_ON_CAST, keep NO_AURA_LOG
        # Category 1211 + 45000, PowerType 1 (rage), ManaCost 150 and StartRecoveryTime 1500 are
        # ALWAYS. EffectTriggerSpell_2 (52174 -> the cloned infernal_strike_impact id) is the
        # generator's. SpellMissileID 621 is a warrior leap missile -- cosmetic, icon survey.
    },

    # ==========================================================================================
    # SECOND RECORDS. Nobody learns any of these; they are triggered.
    # ==========================================================================================

    # -- off-hand mirror of Demon's Bite .................. donor 52874 Fan of Knives (off-hand)
    #
    # The donor supplies the whole mechanism: AttributesEx3 = 0x1000000 REQUIRES_OFF_HAND_WEAPON,
    # which Spell.cpp:594-596 turns into m_attackType = OFF_ATTACK for a DmgClass MELEE spell.
    # EffectBasePoints_1 = 69 against 63753's 99 is Blizzard's own main-hand/off-hand ratio for
    # this exact pair of records, 0.7, and every mirror below keeps it.
    # NOTHING POINTS AT THIS RECORD YET -- dh_spec's demons_bite carries no second_record. See
    # FLAGGED.
    "demons_bite_oh": {
        "SpellClassMask_1": 0x00000001,  # the PARENT's bit, so one talent reaches both halves
        "SpellClassMask_2": 0x00000001,  # its own
        "ImplicitTargetA_1": 6,         # single target in melee, matching the main hand; the donor
        "ImplicitTargetB_1": 0,         # is the PBAoE shape (18 + 16, radius 14)
        "EffectRadiusIndex_1": 0,
        "Speed": 0.0,
        "EffectBasePoints_1": 55,       # PLACEHOLDER -- 56% weapon, i.e. 0.7 x the main hand's 80%
        "StartRecoveryCategory": 0,     # KEEP the donor's 0/0 against ALWAYS: a triggered half
        "StartRecoveryTime": 0,         # must not eat a second global cooldown
    },

    # -- off-hand mirror of Chaos Strike .................. donor 52874 Fan of Knives (off-hand)
    "chaos_strike_oh": {
        "SpellClassMask_1": 0x00000002,
        "SpellClassMask_2": 0x00000002,
        "ImplicitTargetA_1": 6,
        "ImplicitTargetB_1": 0,
        "EffectRadiusIndex_1": 0,
        "Speed": 0.0,
        "EffectBasePoints_1": 90,       # PLACEHOLDER -- 91% weapon, 0.7 x the main hand's 130%
        "SchoolMask": 127,              # all schools, matching the main hand
        "StartRecoveryCategory": 0,
        "StartRecoveryTime": 0,
    },

    # -- off-hand mirror of Blade Dance ................... donor 52874 Fan of Knives (off-hand)
    #
    # The donor is already the PBAoE shape at radius index 14 (8.0 yd), which is what Blade Dance
    # wants, so its targeting is left alone.
    "blade_dance_oh": {
        "SpellClassMask_1": 0x00000020,
        "SpellClassMask_2": 0x00000004,
        "Speed": 0.0,
        "EffectBasePoints_1": 62,       # PLACEHOLDER -- 63% weapon, 0.7 x the main hand's 90%
        "StartRecoveryCategory": 0,
        "StartRecoveryTime": 0,
    },

    # -- Immolation Aura's tick ........................... donor 50590 Immolation
    #
    # ShapeshiftMask 0x200000 is on THIS record too, not only on 50589 -- ALWAYS closes both.
    # EffectRadiusIndex_1 stays 14 (8.0 yd) and the 18 + 16 targeting is kept.
    # AttributesEx2 = 541065216 (0x20400000 = NO_INITIAL_THREAD | CANT_CRIT) is kept: UNVERIFIED,
    # donors.md 7.7 decodes it but explicitly did not reason about its consequences.
    "immolation_tick": {
        "SpellClassMask_1": 0x00000010,
        "SpellClassMask_2": 0x00000008,
        "StartRecoveryCategory": 0,     # triggered once a second; a GCD here would be absurd
        "StartRecoveryTime": 0,
        # EffectBasePoints_1 / EffectRealPointsPerLevel_1 (250 / 11.5 at BaseLevel 60) are UNTUNED.
        # That pair IS the donors.md 0.5 mechanism -- with BaseLevel at the learn level and
        # MaxLevel 0 it ramps from level 1 to 80 out of one record -- but 250 is a level-60
        # warlock's number, not a level-10 Demon Hunter's.
    },

    # -- Eye Beam's cone tick ............................. donor 40939 Illidari Flames (family 0)
    #
    # Illidan's own spell, which is as close to "fel" as stock data gets. Kept: ImplicitTargetA_1 =
    # 24 TARGET_UNIT_CONE_ENEMY_24, EffectRadiusIndex_1 = 9 (20.0 yd), SchoolMask 4, DefenseType 1.
    # Category 50 (100 spells, 23 names) is ALWAYS.
    "eye_beam_tick": {
        "SpellClassMask_1": 0x00000200,
        "SpellClassMask_2": 0x00000010,
        "StartRecoveryCategory": 0,     # the donor is 133/0, which is ALREADY no GCD --
        "StartRecoveryTime": 0,         # Spell::TriggerGlobalCooldown early-returns on
                                        # StartRecoveryTime == 0 -- but ALWAYS would have given it
                                        # a real one, so both cells go back explicitly
        "AttributesEx": 0x88,           # drop 0x40 IS_SELF_CHANNELED from the donor's 0xC8; the
                                        # CHANNEL is the parent record, this is one tick of it.
                                        # 0x88 keeps NO_REDIRECTION | NO_REFLECTION.
        # EffectBasePoints_1 is UNTUNED: 40939 is 0 with DieSides 1, i.e. one point of damage --
        # it is a scripted boss cone whose damage never came from the record.
    },

    # -- Fel Rush's impact ................................ donor 20153 Immolation (infernal)
    #
    # Family 0, no mask, no category, no shapeshift, MaxLevel 0, SchoolMask 4 (Fire),
    # DefenseType 1, radius index 14 (8.0 yd), and already the PBAoE-at-the-caster shape
    # (22 TARGET_SRC_CASTER + 15 TARGET_UNIT_SRC_AREA_ENEMY). Nothing to strip but the GCD.
    "fel_rush_impact": {
        "SpellClassMask_1": 0x00000004,
        "SpellClassMask_2": 0x00000020,
        "StartRecoveryCategory": 0,
        "StartRecoveryTime": 0,
        # EffectBasePoints_1 / EffectRealPointsPerLevel_1 (24 / 0.5 at BaseLevel 50) are UNTUNED.
    },

    # -- Infernal Strike's landing ........................ donor 52174 Heroic Leap (the landing)
    #
    # Kept: Targets 64 (it is placed where the leap lands), DefenseType 2, and EffectBasePoints_3 =
    # 49, i.e. 50% weapon damage -- a WEAPON_PERCENT_DAMAGE cell is level-correct at every level
    # (donors.md 0.2), so unlike the absolute numbers elsewhere it needs no scaling and no
    # placeholder.
    "infernal_strike_impact": {
        "SpellClassMask_1": 0x00200000,
        "SpellClassMask_2": 0x00000040,
        "SchoolMask": 4,                # Fire, from 1 (Physical) -- it is an INFERNAL strike
        # Effect_1 is a stun (aura 12 MOD_STUN with EffectMechanic_1 = 11 MECHANIC_SNARE). Retail
        # Infernal Strike does not stun, and a stun kept here would additionally need Mechanic = 12
        # for DR (donors.md 1.6). The whole effect goes, leftovers included.
        "Effect_1": 0,
        "EffectAura_1": 0,
        "EffectMechanic_1": 0,
        "EffectBasePoints_1": 0,
        "EffectDieSides_1": 0,
        "ImplicitTargetA_1": 0,
        "EffectRadiusIndex_1": 0,
        # Effect_2 is 121 NORMALIZED_WEAPON_DMG, a flat weapon addition on top of Effect_3's
        # percentage. One damage effect is enough, and the percentage is the one that stays correct
        # at every level, so the flat half goes too.
        "Effect_2": 0,
        "EffectBasePoints_2": 0,
        "EffectDieSides_2": 0,
        "ImplicitTargetA_2": 0,
        "EffectRadiusIndex_2": 0,
        "EffectRadiusIndex_3": 13,      # 10.0 yd for the surviving damage effect; the donor's row
                                        # 8 is 5.0 yd, which is a small landing
        "StartRecoveryCategory": 0,     # triggered -- a GCD here would be wrong
        "StartRecoveryTime": 0,
        # PowerType 1 (rage) -> 3 is ALWAYS, as is ManaCost 0.
    },
}


# =============================================================================================
# THE HOLES, NAMED
# =============================================================================================

# Cells donors.md requires a number for and does not supply one. Every one of these is an
# ABSOLUTE damage/heal/buff magnitude, which is exactly the class of cell that cannot be left at
# the donor's value: the donor's number belongs to a level-50-to-60 spell of another class.
#
# The two ways out are both dh_spec's, not this file's: a rank ladder (Ability.ranks > 1 with
# ScalingCell entries, normalised against POWER_ANCHOR_WEAPON / POWER_ANCHOR_SPELL), or the
# donors.md 0.5 single-record form -- EffectRealPointsPerLevel with BaseLevel at the learn level
# and MaxLevel 0, which ALWAYS guarantees. Every ability listed here has `scaling=()` in dh_spec
# today, so nothing scales them yet.
#
# This tuple exists so that hole is LOUD. A missing number that is only a comment is a number
# somebody ships at the donor's value.
UNTUNED = (
    ("throw_glaive",     "EffectBasePoints_1",         "31935 is 439 with die 97 at BaseLevel 50, "
                                                       "EffectRealPointsPerLevel_1 = 0; Blizzard "
                                                       "re-ranks it across five ranks"),
    ("throw_glaive",     "EffectDieSides_1",           "moves with the base points"),
    ("immolation_tick",  "EffectBasePoints_1",         "50590 is 250 at BaseLevel 60"),
    ("immolation_tick",  "EffectRealPointsPerLevel_1", "50590 is 11.5 per level"),
    ("fel_rush_impact",  "EffectBasePoints_1",         "20153 is 24 at BaseLevel 50"),
    ("fel_rush_impact",  "EffectRealPointsPerLevel_1", "20153 is 0.5 per level"),
    ("fiery_brand",      "EffectBasePoints_1",         "348's DoT tick is 3 every 3000 ms at "
                                                       "BaseLevel 1"),
    ("fiery_brand",      "EffectBasePoints_2",         "348's direct hit is 7"),
    ("fiery_brand",      "EffectRealPointsPerLevel_2", "348 is 0.6 per level on the direct hit"),
    ("sigil_of_flame",   "EffectBasePoints_1",         "26573 is 8 per second at BaseLevel 20, "
                                                       "with no per-level ramp at all"),
    ("soul_cleave",      "EffectBasePoints_2",         "the self-heal; 63753 has no heal effect "
                                                       "at all, so there is no donor number"),
    ("eye_beam_tick",    "EffectBasePoints_1",         "40939 is 0 with die 1 -- one point of "
                                                       "damage; its real damage was never in the "
                                                       "record"),
    ("chaos_nova",       "EffectBasePoints_1",         "30283 is 342 at BaseLevel 50"),
    ("chaos_nova",       "EffectDieSides_1",           "30283 is 65"),
    ("chaos_nova",       "EffectRealPointsPerLevel_1", "30283 is 1.6 per level"),
    # glide.EffectBasePoints_2 WAS here. It now carries 29 (+30% run speed) in OVERRIDES: a
    # cell left at zero is an effect that provably does nothing, whereas a number at least works
    # IF the mechanism does. It stays untuned in the ordinary sense -- see the comment on the
    # cell -- but it is no longer absent, and UNTUNED and OVERRIDES must stay disjoint or the
    # assertion at the bottom of this file fires. (It did.)
    ("metamorphosis",    "EffectBasePoints_2",         "47241 is 599, i.e. +600% armour -- a "
                                                       "warlock TANK cooldown"),
    ("metamorphosis",    "EffectBasePoints_3",         "47241 is 19, i.e. +20% damage done"),
)

# Decisions donors.md explicitly refused to make, plus the three places where following it leaves
# something a human has to look at. Carried as data so a --check can print them rather than
# leaving them buried in comments.
FLAGGED = (
    ("double_jump", "global cooldown",
     "donors.md 3.6 -- stock leaves mobility buttons off-GCD (781, 47241). ALWAYS gives this "
     "133/1000, so Double Jump cannot be chained with Fel Rush inside one GCD, which changes the "
     "feel of the whole kit. Flagged, not decided."),
    ("vengeful_retreat", "global cooldown",
     "donors.md 3.4 -- stock Disengage is deliberately 0/0; ALWAYS gives 133/1000 per the house "
     "rule. Either is defensible."),
    ("vengeful_retreat", "spell_linked_spell",
     "donors.md 1.7 -- stock 781 links to 56446, a second identical LEAP_BACK, so the clone leaps "
     "ONCE where Disengage leaps twice. Either re-point the link in module SQL or tune "
     "EffectMiscValue_1 / EffectBasePoints_1 against the live feel."),
    ("blur", "global cooldown",
     "donors.md 3.12 -- stock Evasion is 0/0."),
    ("torment", "global cooldown",
     "donors.md 3.14 -- every stock taunt is 0/0."),
    ("metamorphosis", "global cooldown",
     "kept at the donor's 0/0 against ALWAYS. donors.md 0.4 lists it among Blizzard's deliberate "
     "off-GCD player abilities and retail Metamorphosis is off-GCD too, but it is a decision, not "
     "a reading."),
    ("spectral_sight", "EffectBasePoints_3",
     "donors.md 3.10 keeps 34709's +5% damage taken as the self-debuff; dh_spec's summary says "
     "'at the cost of speed', which would be aura 33 SPELL_AURA_MOD_DECREASE_SPEED instead. The "
     "two disagree and the record follows donors.md."),
    ("immolation_aura", "Effect_3",
     "50589's EffectAura_3 = 77 MECHANIC_IMMUNITY with EffectMiscValue_3 = 16 MECHANIC_BANDAGE is "
     "inherited. donors.md 3.8 does not strip it, while 3.20 strips the identical effect off 1949 "
     "for Eye Beam."),
    ("sigil_of_flame", "arm time",
     "donors.md 3.18 -- the 2-second delay before the sigil erupts has NO Spell.dbc cell. It is "
     "either CastingTimeIndex (a visible cast bar, wrong feel) or a module script that delays the "
     "persistent aura."),
    ("glide", "OnCheckCast",
     "donors.md 1.7 / 3.5 -- the 'only while falling' gate lives in spell_item_flexweave_underlay "
     "(spell_item.cpp:3572-3588), not in the record, so a clone does not get it."),
    ("demons_bite_oh", "nothing triggers it",
     "dh_spec's demons_bite carries no second_record, so this record is allocated and shaped but "
     "unreachable. Either add second_record= (Effect_2 is taken by the energize, so the trigger "
     "would have to be Effect_3) or cast it from a module script."),
    ("chaos_strike_oh", "nothing triggers it",
     "dh_spec's chaos_strike carries no second_record. Effect_2 is free on that record."),
)


# =============================================================================================
# IMPORT-TIME CHECKS
#
# A typo'd column name must fail here, at import, and not silently do nothing three passes later
# inside a memcpy'd record that still looks plausible.
#
# What is NOT checked here: that the keys match dh_spec.ABILITY_BLOCKS / SINGLES_ORDER. dh_spec
# imports THIS module, so importing it back at module scope would be a cycle. The print-check
# below does it instead, which is why `python3 dh_donors.py` is worth running.
# =============================================================================================

_COLS = set(dbc_tables.SPELL_DBC.columns)
_FLOAT_COLS = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
               if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_FLOAT}
_STRING_COLS = {n for i, n in enumerate(dbc_tables.SPELL_DBC.columns)
                if dbc_tables.SPELL_DBC.kind(i) == dbc_tables.KIND_STRING}

assert set(OVERRIDES) == set(ABILITY_KEYS), (
    "OVERRIDES must cover exactly ABILITY_KEYS: "
    f"missing {sorted(set(ABILITY_KEYS) - set(OVERRIDES))}, "
    f"unexpected {sorted(set(OVERRIDES) - set(ABILITY_KEYS))}")
assert len(ABILITY_KEYS) == len(set(ABILITY_KEYS)), "ABILITY_KEYS has a duplicate"
assert set(SECOND_RECORDS) == set(DONORS), "every second record needs a donor and a parent"
assert set(SECOND_RECORDS) <= set(ABILITY_KEYS), "SECOND_RECORDS names a key that does not exist"
assert set(SECOND_RECORDS.values()) <= set(ABILITY_KEYS), "SECOND_RECORDS names a missing parent"

for _col, _value in ALWAYS.items():
    assert _col in _COLS, f"ALWAYS: {_col!r} is not a Spell.dbc column"
    assert _col not in _STRING_COLS, f"ALWAYS: {_col!r} is a string column"
    assert isinstance(_value, int) and not isinstance(_value, bool), \
        f"ALWAYS: {_col!r} must be an int, got {_value!r}"

for _key, _cells in OVERRIDES.items():
    for _col, _value in _cells.items():
        assert _col in _COLS, f"OVERRIDES[{_key!r}]: {_col!r} is not a Spell.dbc column"
        assert _col not in _STRING_COLS, f"OVERRIDES[{_key!r}]: {_col!r} is a string column"
        if _col in _FLOAT_COLS:
            assert isinstance(_value, float), \
                f"OVERRIDES[{_key!r}]: {_col!r} is a float column, got {_value!r}"
        else:
            assert isinstance(_value, int) and not isinstance(_value, bool), \
                f"OVERRIDES[{_key!r}]: {_col!r} must be an int, got {_value!r}"

for _key, _col, _why in UNTUNED:
    assert _key in OVERRIDES, f"UNTUNED names an unknown ability {_key!r}"
    assert _col in _COLS, f"UNTUNED[{_key!r}]: {_col!r} is not a Spell.dbc column"
    assert _col not in OVERRIDES[_key], \
        f"UNTUNED[{_key!r}] lists {_col!r}, which OVERRIDES already sets -- pick one"

for _key, _what, _why in FLAGGED:
    assert _key in OVERRIDES, f"FLAGGED names an unknown ability {_key!r}"

# The bit allocation, checked rather than trusted: one distinct bit each, and a second record
# carrying its parent's bit as well as its own (the 51723/52874 arrangement).
_OWN_BITS = {}
for _key in ABILITY_KEYS:
    _col = "SpellClassMask_2" if _key in SECOND_RECORDS else "SpellClassMask_1"
    _bit = OVERRIDES[_key].get(_col, 0)
    if _key in _MASKLESS:
        assert _bit == 0, f"{_key} is in _MASKLESS and must carry no mask bit"
        continue
    assert _bit and not (_bit & (_bit - 1)), \
        f"{_key}: {_col} must be exactly one bit, got {_bit:#010x}"
    assert (_col, _bit) not in _OWN_BITS, \
        f"{_key} reuses {_col} bit {_bit:#010x}, already taken by {_OWN_BITS[(_col, _bit)]}"
    _OWN_BITS[(_col, _bit)] = _key

for _key, _parent in SECOND_RECORDS.items():
    assert OVERRIDES[_key].get("SpellClassMask_1") == OVERRIDES[_parent].get("SpellClassMask_1"), \
        (f"{_key} must carry {_parent}'s SpellClassMask_1 bit so one talent reaches both halves "
         f"(stock precedent: 52874 carries 51723's mask)")


if __name__ == "__main__":
    print(f"dh_donors -- {len(ABILITY_KEYS)} records, {len(_COLS)} Spell.dbc columns known")
    print()
    print("ALWAYS (applied to every clone, before the per-ability cells)")
    for col, value in ALWAYS.items():
        print(f"    {col:<24} {value}")
    print()

    # The keys dh_spec must agree with. Imported here and not at module scope: dh_spec imports
    # this module, and a cycle at import time would be a much worse failure than a missing check.
    try:
        import dh_spec
    except ImportError as exc:                                   # pragma: no cover
        print(f"    (dh_spec not importable: {exc}; key cross-check skipped)")
        dh_spec = None
    if dh_spec is not None:
        known = set(dh_spec.ABILITY_BLOCKS) - {"singles"} | set(dh_spec.SINGLES_ORDER)
        unknown = set(ABILITY_KEYS) - known
        uncovered = known - set(ABILITY_KEYS)
        assert not unknown, f"keys dh_spec does not know: {sorted(unknown)}"
        assert not uncovered, f"dh_spec keys with no overrides: {sorted(uncovered)}"
        print(f"    cross-checked against dh_spec: {len(known)} keys, all covered")
        for key in ABILITY_KEYS:
            if key in DONORS:
                continue
            assert key in dh_spec.ABILITIES_BY_KEY, f"{key} has no donor anywhere"
        print()

    total = 0
    for key in ABILITY_KEYS:
        cells = OVERRIDES[key]
        total += len(cells)
        donor = DONORS.get(key)
        if donor is None and dh_spec is not None:
            donor = dh_spec.ABILITIES_BY_KEY[key].donor
        tag = "second record" if key in SECOND_RECORDS else "ability"
        noun = "cell" if len(cells) == 1 else "cells"
        print(f"{key}  ({tag}, donor {donor if donor else '?'}, {len(cells)} {noun})")
        for col, value in cells.items():
            # Bitfields read as hex and as nothing else; everything else is a plain number.
            bitfield = (col.startswith("SpellClassMask") or col.startswith("Attributes")
                        or col.endswith("Flags"))
            print(f"    {col:<28} {value:#010x}" if bitfield else f"    {col:<28} {value}")
        if not cells:
            print("    (none -- ALWAYS and dh_spec cover this record entirely)")
    print()

    print(f"UNTUNED -- {len(UNTUNED)} cells donors.md leaves without a number")
    for key, col, why in UNTUNED:
        print(f"    {key}.{col}: {why}")
    print()
    print(f"FLAGGED -- {len(FLAGGED)} decisions donors.md refused to make")
    for key, what, why in FLAGGED:
        print(f"    {key} [{what}]: {why}")
    print()
    print(f"{total} per-ability cells + {len(ALWAYS)} always-applied, "
          f"{len(_OWN_BITS)} SpellClassMask bits allocated, "
          f"{len(_MASKLESS)} deliberately maskless")


# =============================================================================================
# DECIDED -- the global-cooldown exemptions
# =============================================================================================
#
# dh_donors flagged six abilities where ALWAYS's 133/1000 contradicts what Blizzard does with
# the equivalent stock spell, and refused to choose. Choosing, with the reason:
#
#   double_jump       OFF. This is the one that matters. A Demon Hunter jumps, jumps again and
#                     Fel Rushes out of the second jump -- that is the whole movement kit. On a
#                     one-second GCD the second jump eats the dash and the combination is
#                     impossible. It is also not an ability in any meaningful sense: it costs
#                     nothing, does nothing, and has no target.
#   glide             OFF, same argument. It is cast in mid-air, usually immediately after the
#                     second jump, and a GCD would swallow whichever of the two came second.
#   vengeful_retreat  OFF. Stock 781 Disengage is 0/0 and this is a clone of it; putting the
#                     escape on the same GCD as the damage rotation is what makes an escape
#                     button feel unresponsive.
#   blur              OFF. Stock 5277 Evasion is 0/0. A defensive cooldown that costs a GCD is a
#                     defensive cooldown you press too late.
#   torment           OFF. Every stock taunt is 0/0 -- 355 Taunt, 56222 Dark Command,
#                     62124 Hand of Reckoning. A taunt on the GCD is a tank losing threat.
#   metamorphosis     already 0/0 from the donor and left there; retail Metamorphosis is
#                     off-GCD too.
#
# Everything that deals damage or costs Fury keeps the GCD. The rule this encodes is Blizzard's
# own and not a novel one: the global cooldown exists to pace the damage rotation, and none of
# the six above is part of it.
OFF_GCD = ("double_jump", "glide", "vengeful_retreat", "blur", "torment", "metamorphosis")

for _key in OFF_GCD:
    assert _key in OVERRIDES, f"OFF_GCD names {_key!r}, which has no OVERRIDES entry"
    OVERRIDES[_key]["StartRecoveryCategory"] = 0
    OVERRIDES[_key]["StartRecoveryTime"] = 0
