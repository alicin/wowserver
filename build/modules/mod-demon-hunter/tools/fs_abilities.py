#!/usr/bin/env python3
"""The Felsworn baseline ability ladder -- the replacement for `dh_spec.ABILITY_BLOCKS`,
`SINGLES_ORDER` and `ABILITIES`, staged here so it can be reviewed against the port plan before
it lands in `build/modules/mod-demon-hunter/tools/dh_spec.py`.

`.work/felsworn/port-plan.md` is the argument; this file is its section 2.1 table plus its
section 2.2 fix list, expressed as `Ability` records. Nothing here is recalled: every level,
cost, cooldown and rank id below was read out of
`build/tools/ascension/out/felsworn-family20.json`, and every donor id was read out of
`/srv/wow/data/dbc/Spell.dbc`. The two places a number was *chosen* rather than read are named
at the cell that carries it (Oblivion's cost, Chaos Rush's cooldown).

WHY EVERY ROW CARRIES BOTH `source` AND `donor`
-----------------------------------------------
`source` transplants the whole 234-cell Ascension record. `donor` is the stock row that is
cloned first, so a failed import degrades to a working spell of roughly the right shape instead
of to a blank record (`dh_spec.py:852-870`). Donors are therefore chosen for EFFECT SHAPE and
nothing else -- several are creature or item spells, and one is a Death Knight spell -- because
the only thing a donor has to survive is the import failing.

THE PARTITION RULE (plan 2.0), restated because it is what makes this list 30 and not 44
-----------------------------------------------------------------------------------------
Baseline = every player-shaped family-20 spell with no `CharacterAdvancement` node at all, plus
the tab-87 "Class" nodes. Tabs 18 / 37 / 38 are talents. Applied mechanically that resolves all
fourteen previously double-booked ids with zero collisions, which is why Carve, Felrend,
Annihilan Strike, Immolation Aura, Ruin, Felwrath, Felbreak, Bane of Chaos, Azzinoth's Assault
and Felhoof Charge are absent below: they are talent-granted actives (`Talent.dbc Flags = 1`),
not trainer spells.

TWO NAME TRAPS, kept apart below and easy to re-merge by accident:
  * Annihilation is `803904` (tab 87, a guaranteed-crit cooldown -> `annihilation_crit`) AND
    `802059` (no node, a channelled ranged nuke -> `annihilation`).
  * Oblivion is `800215` (no node, the execute -> `oblivion`) AND `572889` (tab 37, a passive,
    which belongs to `dh_talents`).

CUT, per plan 7: Manaburn `805248` (its only effect is `POWER_BURN` bp 0 ds 1 = one mana; every
number would be invented) and the Fel Rift teleports `535595-535600` (`SPELL_EFFECT_TRANS_DOOR`
pointing at six Ascension GameObject ids -- portable, but it is six `gameobject_template` rows
and six taxi nodes, i.e. a separate ticket).

WHAT THE IMPORT MUST NOT CARRY -- TODO for `dhspells.py`'s import pass
---------------------------------------------------------------------
`dh_donors.ALWAYS` closes these traps on a CLONE. An import overwrites the whole record after
the clone, so ALWAYS has to run AGAIN on the imported cells or the trap comes back:

  * `MaxLevel` -- non-zero on 8 of the 30 sources, because Ascension uses it as a rank boundary
    (Twin Slice `801901` is MaxLevel 4, Sargeron Smite `802060` is 8, Oblivion `800215` is 70).
    A non-zero MaxLevel caps `CalcValue`'s per-level ramp and drags
    `Unit::CalculateLevelPenalty` below 1 for the spell's whole life. Must be zeroed.
  * `ShapeshiftMask` -- Manafeed `552210` carries 0x200000 (the warlock's form 22) and Consume
    Magic `800353`, Illidari Intuition `800212` and Annihilation `803904` carry 0x8000000. Both
    are forms this class cannot enter, so `SpellInfo::CheckShapeshift` fails the cast outright.
    Must be zeroed; `INNER_DEMON_STANCE = 1 << 22` is the only mask this kit may set.
  * `ManaCostPct` / `PowerType` -- Betray 15%, Blood of Mannoroth 20% of POWER_HEALTH (-2),
    Greater Man'ari 24%. `Ability.cost` below carries the flat Energy equivalent; the percentage
    cell has to be zeroed or it is charged on top.
  * `Effect_* > 164` / `EffectAura_* > 316` -- `SpellMgr.cpp:3039-3040` ASSERTs on these, so an
    unfiltered import is a worldserver STARTUP CRASH, not a silent no-op. Plan 6.4 item 5 adds
    the check; it must run on the imported record, not on the donor.

SPELL BONUS COEFFICIENTS
------------------------
Plan 6.4 item 4 enumerates seven `spell_bonus_data` coefficients and three of them are baseline
abilities: Doomscar, Sargeron Smite and Consume Magic. Those three carry `ap_bonus`/`sp_bonus`
below. The rest of the kit has `$spfi`/`$sps`/`$AP` clauses in its description strings that the
plan does not enumerate (Fel Fireball `$sps*0.5`, Felspears `$sps*0.45`, Oblivion `$AP*0.35`,
Sunder `$AP*0.2 + $SP*0.25`, Annihilation `$SP*0.35`, Fel Eruption `$sps*0.658`) -- TODO: the
`spell_bonus_data` emitter added by plan 6.4 item 4 needs a second pass over those, because
without a row the ability does not scale with gear AT ALL and the tooltip still promises it will.

NO `ScalingCell` IS USED, AND THAT IS THE POINT
-----------------------------------------------
The Death Knight and the Demon Hunter generate rank values from an anchor ladder. Every row here
takes its numbers from `source`/`source_ranks` instead -- nine real Ascension rank ladders, each
rank its own record with its own cells. So `scaling` is empty on all 30 and `ScalingCell` is
imported only so that a future hand-authored rank does not have to touch the import line.
Six abilities are moved more than two levels from Ascension's own `spell_level` (marked with a
capital DELTA in their comment) and their numbers are NOT re-scaled to the new level: they are
Ascension's own values at Ascension's level, carried across unchanged and unmeasured.
"""

from dh_spec import Ability, ScalingCell            # noqa: F401  -- see the docstring's last

# =============================================================================================
# ID BLOCKS -- plan section 5
# =============================================================================================
#
# ORDERED, and the order IS the block index: block n owns 91000 + 20n .. 91000 + 20n + 19.
# `dh_spec.ABILITY_BLOCKS` is a dict today; plan 5 keeps `spell_id_for()`, `single_spell_id()`
# and `sla_id_for()` unchanged, so the generator's lookup becomes the index of the key in this
# tuple. A block that is reserved and vacant stays reserved and vacant forever -- reusing one
# silently repoints a spell some character already has in `character_spell`.
#
# Blocks 0-9 are the ranked abilities. Blocks 10-24 are the fifteen SECOND RECORDS, which nobody
# learns: a dual-wield strike needs a record per hand, an ability that damages on arrival needs
# a record for the arrival, and the resource and the form are records in their own right.
# Blocks 25-26 are the one-row customs.
ABILITY_BLOCK_ORDER = (
    # ---- 0-9: the rank ladders --------------------------------------------------------------
    ("twin_slice",             "91000-91007  8 ranks  801901, 501257-501261, 547210, 547211"),
    ("sargeron_smite",         "91020-91028  9 ranks  802060, 501314-501321"),
    ("fel_fireball",           "91040-91048  9 ranks  801312, 501281-501288 (+501289-501291 p3)"),
    ("chaos_rush",             "91060-91062  3 ranks  500028, 500422, 500423 (NOT 500424, its "
                               "duplicate)"),
    ("manari_intuition",       "91080-91085  6 ranks  523478-523483 (+523484 phase 2)"),
    ("hateforged_barrier",     "91100-91105  6 ranks  705129, 707523-707527"),
    ("felspears",              "91120-91127  8 ranks  706532, 572281-572287"),
    ("cripple",                "91140-91145  6 ranks  707436-707441 (+707442 phase 2)"),
    ("manafeed",               "91160-91163  4 ranks  552210-552213"),
    ("illidari_intuition",     "91180-91184  5 ranks  800212, 501326-501329"),
    # ---- 10-24: second records. No SkillLineAbility row, no learn level, no spellbook entry.
    ("twin_slice_mh",          "91200  803462  main-hand shell, bp 0, fed by the parent's "
                               "Effect 142 value"),
    ("twin_slice_oh",          "91220  520243  off-hand shell, same shape; needs "
                               "SPELL_ATTR3_REQ_OFFHAND"),
    ("chaos_rush_dash",        "91240  802028  CHARGE_DEST; its e1 -> 802030 is an unrelated "
                               "Chaos Nova leftover, drop"),
    ("felspears_bolt",         "91260  706533  the bouncing bolt all 8 Felspears ranks trigger"),
    ("hateforged_tick",        "91280  705130  the 2 s HoT all 6 Hateforged ranks trigger"),
    ("annihilation_tick",      "91300  803841  the 500 ms tick of the channelled nuke 802059"),
    ("oblivion_dot",           "91320  572132  rebuilt as plain SCHOOL_DAMAGE; its aura 4 DUMMY "
                               "implements nothing"),
    ("felbreak_drain",         "91340  804809  POWER_DRAIN bp 1 ppl 0.5 -- the Spirit-scaled "
                               "drain; belongs to talent Felbreak 800203, no baseline parent"),
    ("sunder_tick",            "91360  707508  the 300 ms accumulator behind Sunder"),
    ("sunder_blast",           "91380  712399  one of the three sequenced explosions 707508 "
                               "sequences"),
    ("reckoning_stack",        "91400  524632  the stacking damage buff Fel Fireball feeds "
                               "during Reckoning"),
    ("annihilation_crit_proc", "91420  807961  what 803904's aura 42 fires to spend a charge"),
    ("betray_rider",           "91440  804349  the Inner Demon damage rider; PHASE 2, see the "
                               "betray entry"),
    ("felfury",                "91460  800058  THE RESOURCE. CumulativeAura 5, not passive, "
                               "SPELL_ATTR0_NO_AURA_CANCEL. Plan 4 C1."),
    # NOT a second record despite sitting in this band: `inner_demon` has an Ability row and
    # therefore a SkillLineAbility row and a learn level. It lives here only because its id was
    # already allocated at 91480 and ABILITY_BLOCK_ORDER is append-only.
    ("inner_demon",            "91480  804216  THE FORM, learnable at L2. Shapeshift 56 -> 23; "
                               "duration is script, not data. Plan 4 C2."),
    # ---- 25-26: one row each, ordered by SINGLES_ORDER ---------------------------------------
    ("singles",                "91500-91519  the twenty abilities that never re-rank"),
    ("singles2",               "91520-91539  RESERVED for phase 3 and the Fel Rift set"),
)

# ABILITY_BLOCKS is what the rest of the toolchain consumes and its shape is a CONTRACT:
# dh_spec.spell_id_for() indexes it by key (dh_spec.py:246), single_spell_id() and
# sla_id_for() go through the same lookup, dh_donors.py:1118 subtracts a set of KEYS from it,
# and dhspells.py branches on `key in spec.ABILITY_BLOCKS` to decide whether an ability owns a
# 20-id block or a single id. A tuple-of-pairs breaks every one of those silently rather than
# loudly -- `'twin_slice' in ABILITY_BLOCKS` simply returns False and the ability quietly
# becomes a single-record entry in another block's id space.
#
# So the documentation above stays a tuple, and the mapping is derived from it. Block index is
# position, which is also why ABILITY_BLOCK_ORDER is APPEND-ONLY: inserting a row renumbers
# every block after it and repoints every `character_spell` row a live character already has.
ABILITY_BLOCKS = {key: i for i, (key, _doc) in enumerate(ABILITY_BLOCK_ORDER)}
assert len(ABILITY_BLOCKS) == len(ABILITY_BLOCK_ORDER), "duplicate key in ABILITY_BLOCK_ORDER"


# The Ascension record each non-ability block transplants. Second records, the resource aura
# and the form are not abilities -- they have no level, no cost and no skill line -- so they
# cannot carry `Ability.source`, but they still have to EXIST: an EffectTriggerSpell pointing
# at an id with no record is a silently dead effect.
SECOND_SOURCES = {
    "twin_slice_mh":          803462,
    "twin_slice_oh":          520243,
    "chaos_rush_dash":        802028,
    "felspears_bolt":         706533,
    "hateforged_tick":        705130,
    "annihilation_tick":      803841,
    "oblivion_dot":           572132,
    "felbreak_drain":         804809,
    "sunder_tick":            707508,
    "sunder_blast":           712399,
    "reckoning_stack":        524632,
    "annihilation_crit_proc": 807961,
    "betray_rider":           804349,
    "felfury":                800058,
    "inner_demon":            804216,
}


# =============================================================================================
# CELLS THE TRANSPLANT GETS WRONG, AND WHAT THEY BECOME
# =============================================================================================
#
# An imported record is the ability, but it is the ability AS ANOTHER ENGINE IMPLEMENTS IT.
# Where Ascension extended the effect or aura enum, the cell that arrives is not a wrong number
# -- it is a number this core cannot represent at all. SpellMgr::LoadSpellInfoStore ASSERTs on
# an effect above 164 or an aura above 316, so each of these is the difference between a realm
# that boots and one that does not.
#
# Applied AFTER the transplant and after dh_donors.ALWAYS, so they are the last word. Every
# entry names the semantic it is preserving, because a remap that merely makes the assert go
# away is worse than no remap: it ships a spell whose tooltip and behaviour disagree.
CELL_OVERRIDES = {
    # Aura 330 is Ascension's "chance to be critically struck by school X from the caster".
    # 179 SPELL_AURA_MOD_ATTACKER_SPELL_CRIT_CHANCE is an exact semantic match and takes the
    # school mask in EffectMiscValue, which the imported cell already holds -- so only the aura
    # id moves. Stock precedent: 12579 Winter's Chill is aura 179 with EffectMiscValue 126.
    "bane_of_fire":  {"EffectAura_2": 179},
    "bane_of_power": {"EffectAura_1": 179},

    # Aura 338 reduces the target's armour. 142 SPELL_AURA_MOD_BASE_RESISTANCE_PCT with
    # EffectMiscValue 1 (armour) and a negative amount is the closest this core has.
    #
    # KNOWN DEVIATION, and it is a real one rather than a rounding difference: 142 reduces the
    # target's armour against EVERYONE, where Ascension's 338 reduced it only against the
    # Felsworn. In a group this is a buff to the whole group. Accepted because the alternative
    # is a script on every damage event against the target; revisit if it matters in PvP.
    "bane_of_frailty": {"EffectAura_1": 142, "EffectMiscValue_1": 1},

    # Illidan's Guile is two problems. Effect 183 does not exist here at all and is dropped
    # outright -- its record is a private Ascension effect, and guessing at what it did would be
    # inventing an ability rather than porting one.
    #
    # Its e0 is aura 106 HOVER, which is not what the tooltip describes ("immune, but unable to
    # act"). The shape that IS that is Ice Block 45438: aura 39 SCHOOL_IMMUNITY plus a self
    # stun, NOT Divine Shield. e1 already carries the immunity, so e0 becomes aura 12
    # SPELL_AURA_MOD_STUN and the pair reads correctly.
    "illidans_guile": {
        "Effect_3": 0, "EffectAura_3": 0, "EffectBasePoints_3": 0,
        "EffectTriggerSpell_3": 0, "ImplicitTargetA_3": 0,
        "EffectAura_1": 12,
    },
}


# One row each inside the `singles` block, in this order. APPEND-ONLY: reordering silently
# repoints every `character_spell` row a live Felsworn already has.
SINGLES_ORDER = (
    "bane_of_fire",             # 91500
    "bane_of_frailty",          # 91501
    "betray",                   # 91502
    "skull_of_guldan",          # 91503
    "consume_magic",            # 91504
    "blur",                     # 91505
    "felbane",                  # 91506
    "bane_of_betrayal",         # 91507
    "bane_of_power",            # 91508
    "doomscar",                 # 91509
    "annihilation_crit",        # 91510
    "illidans_guile",           # 91511
    "whispers_of_the_pit",      # 91512
    "sunder",                   # 91513
    "blood_of_mannoroth",       # 91514
    "greater_manari",           # 91515
    "reckoning",                # 91516
    "fel_eruption",             # 91517
    "annihilation",             # 91518
    "oblivion",                 # 91519
)


# =============================================================================================
# THE LADDER -- plan section 2.1, in the plan's own row order
# =============================================================================================
#
# 27 buttons at the live cap of 60 (`conf/worldserver.conf` MaxPlayerLevel), 30 at 70. The last
# three rows are deliberately out of level order because that is the order plan 2.1 lists them
# in -- Oblivion is the level-70 capstone, and Annihilation and Fel Eruption are pulled DOWN to
# 66 and 62 so that the 60-70 stretch is not one button.
#
# No gap above 4 levels. 40 / 43 / 44 / 49 / 52 / 55 / 56 / 60 have no new button and do not
# need one: they are rank-ups, which is the WotLK shape.
ABILITIES = (

    # -- L1 -- Twin Slice ----------------------------------------- 8 ranks, 1/6/14/24/34/44/52/60
    #
    # REBUILT, and it is the one rebuild that costs damage. R1/R2 use `Effect 64 TRIGGER_SPELL`
    # into per-rank halves that carry their own numbers (808303: eff 121 bp 5 + eff 31 bp 79;
    # 808305: bp 9 / bp 89), while R3-8 use `Effect 142 TRIGGER_SPELL_WITH_VALUE` into the two
    # bp-0 shells 803462 / 520243. Plan 2.2 collapses R1-2 into the R3+ shape: two Effect 142s
    # carrying bp 5 / bp 9. That drops Ascension's deliberate 80%/90% weapon-damage attenuation
    # at levels 1-13, so early melee runs ~15% hot. Accepted, with precedent -- commit f729d9b
    # "dk: +10% overtune below 55" is the same trade. Saves 4 records.
    #
    # e2 is the Felfury generator: `Effect 64 -> 800058`, one of only four places in the whole
    # 858-record family where +1 Felfury is real data rather than something we author.
    Ability("twin_slice", "Twin Slice", 1, 63753,
            "Strike with both weapons and build Felfury.",
            cost=45, ranks=8,
            source=801901,
            source_ranks=(501257, 501258, 501259, 501260, 501261, 547210, 547211),
            rank_levels=(1, 6, 14, 24, 34, 44, 52, 60),
            second_records=("twin_slice_mh", "twin_slice_oh", "felfury"),
            note="63753 Fan of Knives is family 0 and its one effect is 31 "
                 "WEAPON_PERCENT_DAMAGE, so the degraded clone is still level-correct; "
                 "801901's own EquippedItemClass 2 (a weapon requirement) is right and stays"),

    # -- L1 -- Sargeron Smite --------------------------- 9 ranks, 1/10/16/26/34/42/50/56/60
    #
    # THE LEVEL-1 LOOP CLOSES HERE: two Twin Slices (90 Energy, +2 Felfury) pay for one Sargeron
    # Smite (0 Energy, -2 Felfury, +20 Energy back).
    #
    # NOT PURE DATA AS SHIPPED, and the prior pass had this backwards. No rank carries an
    # ENERGIZE effect and no rank references 521213 -- the tooltip's `$521213s1` is display-only.
    # TODO(dhspells import pass): author `Effect_2 = 30 SPELL_EFFECT_ENERGIZE,
    # EffectBasePoints_2 = 19, EffectMiscValue_2 = 3` on all nine ranks, which is standalone
    # 521213's own cells exactly (eff 30, bp 19, misc 3 = +20 Energy). The e2 that IS in the
    # record -- `DUMMY bp=2 -> 706658` -- is DELETED, not converted: 706658 is absent from the
    # dump, so whatever it did is unknowable, and bp 2 is the "Consumes 2 Felfury" marker that
    # plan 4 C1's `OnSpellCast` debit owns.
    Ability("sargeron_smite", "Sargeron Smite", 1, 38628,
            "Spend Felfury to blast an enemy and refund Energy.",
            cost=0, ranks=9,
            source=802060,
            source_ranks=(501314, 501315, 501316, 501317, 501318, 501319, 501320, 501321),
            rank_levels=(1, 10, 16, 26, 34, 42, 50, 56, 60),
            sp_bonus=0.6, ap_bonus=0.19,
            note="38628 Shadow Bolt is a family-0 creature nuke: instant, single target, one "
                 "SCHOOL_DAMAGE effect, no Category and no MaxLevel -- nothing to strip"),

    # -- L2 -- Fel Fireball ------------------------------ 9 ranks, 2/6/12/20/28/36/44/52/60
    #
    # The ranged generator, and the second of the four real `-> 800058` references (e1).
    Ability("fel_fireball", "Fel Fireball", 2, 39329,
            "Hurl fel fire at an enemy and build Felfury.",
            cost=35, ranks=9,
            source=801312,
            source_ranks=(501281, 501282, 501283, 501284, 501285, 501286, 501287, 501288),
            rank_levels=(2, 6, 12, 20, 28, 36, 44, 52, 60),
            second_records=("felfury",),
            note="39329 Void Bolt is family 0 with a real CastingTimeIndex and a non-zero "
                 "EffectRealPointsPerLevel, which is the shape a nine-rank nuke degrades into"),

    # -- L2 -- Inner Demon ------------------------------------------------------------- single
    #
    # THE FORM, and it was missing entirely from plan 2.1's ladder -- an omission the port plan
    # inherited from its own section 4 C2, which assumed the form would still be sitting at the
    # Demon Hunter's `metamorphosis` id 91508. The rewritten SINGLES_ORDER put Bane of Power
    # there, so C1 and C2 both depended on a record nothing emitted. Added here.
    #
    # Level 2 is Ascension's own `SpellLevel` on 804216, not a choice made here, and it is not
    # as strange as it looks for a signature form: Inner Demon is a Felfury DUMP, not a
    # capstone. Its duration is bought with stacks, so at level 2 with a five-stack cap it is a
    # handful of seconds, and it gets longer only as the trees are filled in. Roughly twenty
    # talents gate on it via ShapeshiftMask 1 << 22.
    #
    # `EffectMiscValue_1` arrives as 56 and MUST become 23. Form 56 can be entered but nothing
    # can ever gate on it: SpellInfo::Stances is a uint32 (SpellInfo.h:357-358) and DBCfmt.h:110
    # marks the high dwords `x`, so `1 << 55` is unrepresentable and every one of those twenty
    # talents would silently never apply. 23 is the slot dh_spec.SHAPESHIFT_FORM_ID reserves.
    #
    # The duration is NOT data. Ascension multiplies 803465's +5000 ms SPELLMOD_DURATION by the
    # Felfury spent; Player::ApplySpellMod adds a flat modifier exactly once and never scales it
    # by a stack count, so the multiply is engine code there and script here -- plan 4 C2.
    Ability("inner_demon", "Inner Demon", 2, 47241,
            "Unleash your inner demon, spending Felfury to fuel the form.",
            source=804216,
            note="47241 Metamorphosis is the same donor the Demon Hunter's demon form used: "
                 "aura 36 MOD_SHAPESHIFT with the form in EffectMiscValue_1, which is exactly "
                 "804216's e0 shape"),

    # -- L4 -- Chaos Rush ------------------------------------------------ 3 ranks, 4/24/44
    #
    # Ascension ships "3 charges, 10 sec recharge". SPELL CHARGES DO NOT EXIST IN 3.3.5a
    # (plan 7), so the CHOSEN replacement is a flat 10 s cooldown -- the recharge time, taken
    # literally, with the three-charge burst simply gone. This is the one cooldown in the file
    # that is not read off the record; Ascension's own RecoveryTime is 0.
    #
    # Per-rank cost falls 40 / 35 / 30 in Ascension's own cells; `cost` is rank 1's, and the
    # import carries the other two.
    Ability("chaos_rush", "Chaos Rush", 4, 64872,
            "Dash forward in a rush of fel energy, breaking roots.",
            cost=40, cooldown_ms=10000, ranks=3,
            source=500028,
            source_ranks=(500422, 500423),
            rank_levels=(4, 24, 44),
            second_records=("chaos_rush_dash",),
            note="64872 Steam Rush is CHARGE_DEST from a targetless dest -- the same donor the "
                 "Demon Hunter's Fel Rush uses, and 802028 is the same effect 149"),

    # -- L6 -- Bane of Fire ------------------------------------------------------------ single
    #
    # FIXED: e1's aura 330 does not exist in 3.3.5a (`TOTAL_AURAS = 317`,
    # SpellAuraDefines.h:380) and importing it ASSERTs worldserver dead at boot. It becomes
    # aura 179 SPELL_AURA_MOD_ATTACKER_SPELL_CRIT_CHANCE with `EffectMiscValue` left as the
    # school mask -- an exact semantic match for "chance to be critically struck with Fire
    # spells from you". e0 (aura 271 MOD_DAMAGE_FROM_CASTER) is already legal.
    #
    # "Generates 1 Felfury" is in the tooltip but not in the data; e2 is free, so plan 4 C1's
    # authored `Effect 64 -> felfury` goes there.
    Ability("bane_of_fire", "Bane of Fire", 6, 12579,
            "Burn an enemy's defences against your fire.",
            cost=40,
            source=707901,
            second_records=("felfury",),
            note="12579 Winter's Chill IS the remap target: its only effect is aura 179 on "
                 "TARGET_UNIT_TARGET_ENEMY with EffectMiscValue 126, a school mask"),

    # -- L8 -- Man'ari Intuition ------------------------------- 6 ranks, 8/20/30/40/50/60
    Ability("manari_intuition", "Man'ari Intuition", 8, 9885,
            "Armour and primary stats for one ally.",
            cost=15, ranks=6,
            source=523478,
            source_ranks=(523479, 523480, 523481, 523482, 523483),
            rank_levels=(8, 20, 30, 40, 50, 60),
            note="9885 Mark of the Wild rank 7 is aura 22 misc 1 (armour) + aura 29 misc -1 "
                 "(all stats) on TARGET_UNIT_TARGET_ALLY at DurationIndex 30 -- 523478's e0/e1 "
                 "and its duration index, cell for cell"),

    # -- L10 -- Hateforged Barrier ---------------------------- 6 ranks, 10/20/30/40/50/60
    #
    # The only Stamina-scaled absorb on the realm (`$m1+0+$STA*2`). Ascension keeps the 30 s
    # cooldown in `CategoryRecoveryTime`, shared across all six ranks; `dh_donors.ALWAYS` zeroes
    # both category cells, so it is re-expressed as a per-spell RecoveryTime. Ranks are mutually
    # exclusive in the spellbook (`SkillLineAbility.SupercededBySpell`), so per-spell and
    # per-category are the same thing here.
    Ability("hateforged_barrier", "Hateforged Barrier", 10, 12040,
            "Absorb damage and regenerate while the barrier holds.",
            cost=0, cooldown_ms=30000, ranks=6,
            source=705129,
            source_ranks=(707523, 707524, 707525, 707526, 707527),
            rank_levels=(10, 20, 30, 40, 50, 60),
            second_records=("hateforged_tick",),
            note="12040 Shadow Shield is family 0, self-cast, aura 69 SCHOOL_ABSORB at "
                 "EffectMiscValue 127 with a real EffectRealPointsPerLevel -- 705129's e0 misc "
                 "value exactly, and it carries a second self aura for the HoT to land in"),

    # -- L12 -- Bane of Frailty -------------------------------------------------------- single
    #
    # FIXED: aura 338 is above TOTAL_AURAS and would crash the boot. It becomes aura 142
    # SPELL_AURA_MOD_BASE_RESISTANCE_PCT, misc 1 (armour), negative.
    # DEVIATION, ACCEPTED: 142 reduces the target's armour against EVERY attacker, where
    # Ascension's tooltip promises only "allowing YOU to ignore $s1% of their Armor". The
    # tooltip has to be rewritten to match the data rather than the other way round.
    # e1's aura 68 MOD_STALKED is already legal and is kept as-is.
    Ability("bane_of_frailty", "Bane of Frailty", 12, 1130,
            "Strip an enemy's armour and reveal them.",
            cost=40,
            source=707903,
            second_records=("felfury",),
            note="1130 Hunter's Mark is aura 68 MOD_STALKED + a second debuff aura on "
                 "TARGET_UNIT_TARGET_ENEMY, which is 707903's e1 and the shape plan 2.2 names"),

    # -- L13 -- Felspears -------------------------------- 8 ranks, 13/19/25/31/37/43/49/55
    Ability("felspears", "Felspears", 13, 40938,
            "Hurl three bouncing bolts of fel magic.",
            cost=20, cooldown_ms=15000, ranks=8,
            source=706532,
            source_ranks=(572281, 572282, 572283, 572284, 572285, 572286, 572287),
            rank_levels=(13, 19, 25, 31, 37, 43, 49, 55),
            second_records=("felspears_bolt",),
            note="40938 Illidari Flames is family 0 and its one effect is aura 227 "
                 "PERIODIC_TRIGGER_SPELL_WITH_VALUE firing a bolt record on a period -- "
                 "706532's e0 shape, and its 40939 half is already a vetted donor in dh_donors"),

    # -- L14 -- Cripple ------------------------------------- 6 ranks, 14/22/30/38/46/54
    #
    # FIXED, two ways.
    #   1. `mana_cost 9999` on all seven Ascension ranks is a SENTINEL, not a cost. The real
    #      number is 30 Energy, read off 704371 / 707366. Written flat here.
    #   2. `Mechanic = MECHANIC_SNARE (11)`. With family 16 unknown to the core, DR is
    #      classified by family first and by Mechanic only in the `default:` branch
    #      (SpellMgr.cpp:107-263), so Mechanic is the ONLY diminishing-returns input this class
    #      has. A snare with Mechanic 0 is an undiminished snare, i.e. a PvP bug.
    #
    # The chain is 707436-707441 and NOT 704371: 704371's decaying slow rides
    # SPELL_AURA_PERIODIC_DUMMY (226), whose tick handler is a hardcoded id switch. Ascension
    # names these "Rank 2..8"; they are renumbered to our 1..6 by `rank_levels`.
    Ability("cripple", "Cripple", 14, 29666,
            "Slow an enemy and wound them.",
            cost=30, ranks=6, mechanic=11,
            source=707436,
            source_ranks=(707437, 707438, 707439, 707440, 707441),
            rank_levels=(14, 22, 30, 38, 46, 54),
            note="29666 Frost Shock is family 0 and is aura 33 MOD_DECREASE_SPEED bp -51 plus a "
                 "SCHOOL_DAMAGE effect on TARGET_UNIT_TARGET_ENEMY -- 707436's e0 base points "
                 "and its e0/e2 pairing, identically"),

    # -- L16 -- Betray ------------------------------------------------------ single, DELTA +2
    #
    # The tank button: `Effect 114 ATTACK_ME` + aura 11 MOD_TAUNT.
    # `ManaCostPct 15` on POWER_ENERGY is exactly 15 Energy on a 0-100 bar; written flat anyway,
    # because the percentage cell has to be zeroed for the reason in the module docstring.
    # e2 (`TRIGGER_SPELL -> 804349`) is DROPPED for phase 1: 804349 is two DUMMYs plus a bp-0
    # SCHOOL_DAMAGE, and its real payload is the Inner Demon rider, which returns as the
    # `betray_rider` block once plan 4 C2 exists. Its `$AP*0.5` is the fifth of plan 6.4's seven
    # coefficients and belongs on THAT record, not this one.
    # Mechanic is deliberately 0: plan 6.2 lists Betray under new Mechanic cells but neither
    # plan 2.2 nor stock 56222 (Mechanic 0) names a value, and taunt is not a DR category.
    Ability("betray", "Betray", 16, 56222,
            "Taunt an enemy into attacking you.",
            cost=15, cooldown_ms=8000,
            source=804220,
            note="56222 Dark Command, named by plan 6.2 -- eff 114 + aura 11 is 804220's e0/e1 "
                 "verbatim; its PowerType 1 (rage) and Category 82/8000 are closed by ALWAYS"),

    # -- L18 -- Skull of Gul'dan --------------------------------------------- single, DELTA +2
    Ability("skull_of_guldan", "Skull of Gul'dan", 18, 43833,
            "Raise your maximum health and Energy.",
            cost=0, cooldown_ms=90000,
            source=800225,
            note="43833 Increase Health is family 0, self-cast, one aura 133 "
                 "MOD_INCREASE_HEALTH_PERCENT with a real DurationIndex -- 800225's e0"),

    # -- L20 -- Manafeed -------------------------------------- 4 ranks, 20/36/44/56, DELTA -4
    #
    # Rank 1 is pulled from Ascension's level 24 to 20 to cover the 18-22 stretch; ranks 2-4 sit
    # at Ascension's own levels. Per-rank cost climbs 15 / 20 / 25 / 30 in Ascension's cells;
    # `cost` is rank 1's and the import carries the rest.
    # Its `shapeshift_mask 0x200000` is the warlock's form 22 -- see the docstring.
    Ability("manafeed", "Manafeed", 20, 5138,
            "Burn an enemy's mana and heal for what you burn.",
            cost=15, ranks=4,
            source=552210,
            source_ranks=(552211, 552212, 552213),
            rank_levels=(20, 36, 44, 56),
            note="5138 Drain Mana is aura 64 PERIODIC_MANA_LEECH on a period plus a DUMMY, "
                 "which is 552210's e0/e1; the self-heal e2 arrives with the import"),

    # -- L22 -- Consume Magic ---------------------------------------------------------- single
    #
    # The only spellsteal in the kit. 30449 Spellsteal is the ONLY record in the entire
    # 49,839-row stock Spell.dbc that uses `Effect 126 STEAL_BENEFICIAL_BUFF` -- measured over
    # every record, not assumed -- so there is no donor choice to make here.
    Ability("consume_magic", "Consume Magic", 22, 30449,
            "Steal a beneficial effect from an enemy.",
            cost=30,
            source=800353,
            sp_bonus=0.343, ap_bonus=0.22,
            note="30449 Spellsteal is the sole stock user of Effect 126, which is 800353's e0"),

    # -- L24 -- Illidari Intuition ------------------------------- 5 ranks, 24/32/42/52/60
    Ability("illidari_intuition", "Illidari Intuition", 24, 8098,
            "Empower an ally's Agility with demonic energy.",
            cost=15, ranks=5,
            source=800212,
            source_ranks=(501326, 501327, 501328, 501329),
            rank_levels=(24, 32, 42, 52, 60),
            note="8098 Intellect rank 3 is family 0: one aura 29 MOD_STAT on "
                 "TARGET_UNIT_TARGET_ALLY at DurationIndex 30 -- 800212's e0 and duration "
                 "index, differing only in which EffectMiscValue stat it names"),

    # -- L26 -- Blur ------------------------------------------------------------------- single
    #
    # NOT the Demon Hunter's Blur. Ascension's 578345 is a threat drop (aura 103) plus AoE
    # damage reduction (aura 229), with no dodge in it at all.
    Ability("blur", "Blur", 26, 12685,
            "Blur your outline: shed threat and take less from area damage.",
            cost=20, cooldown_ms=30000,
            source=578345,
            note="12685 Fade is family 0, self-cast, one aura 103 MOD_TOTAL_THREAT with a "
                 "duration -- 578345's e0 exactly"),

    # -- L28 -- Felbane ---------------------------------------------------------------- single
    #
    # `ProcTypeMask` is NOT authored here, unlike Annihilation and Reckoning below: 525001
    # already carries 139936, and so does stock 23920, to the bit. That is the taken-damage /
    # taken-spell set a reflect needs, so restating it would only be a second place for it to
    # disagree with the record.
    Ability("felbane", "Felbane", 28, 23920,
            "Curse an enemy so their next spell rebounds onto them.",
            cost=15, cooldown_ms=30000,
            source=525001,
            note="23920 Spell Reflection is aura 28 REFLECT_SPELLS with ProcTypeMask 139936 and "
                 "ProcCharges 1 -- the same proc mask 525001 carries, so the degraded clone "
                 "behaves"),

    # -- L30 -- Bane of Betrayal ------------------------------------------------------- single
    #
    # A stacking DoT whose stack cap Ascension keeps outside the record: the dump has no
    # `CumulativeAura` column at all (plan's corrections table), so the tooltip's `$u` resolves
    # to nothing. `stack_amount` is deliberately left 0 rather than invented -- the donor's own
    # CumulativeAura 5 survives the clone, which is a real number from a real record instead of
    # a guess. TODO(dh_donors.OVERRIDES): set CumulativeAura once Ascension's cap is measured in
    # a client rather than inferred from a tooltip variable.
    Ability("bane_of_betrayal", "Bane of Betrayal", 30, 11469,
            "Chaotic magic that punishes an enemy for acting.",
            cost=50,
            source=712483,
            second_records=("felfury",),
            note="11469 Deadly Toxin IV is family 0, aura 3 PERIODIC_DAMAGE on "
                 "TARGET_UNIT_TARGET_ENEMY, and is one of the few stock records with a real "
                 "CumulativeAura (5) -- the exact cell 712483 is missing"),

    # -- L32 -- Bane of Power --------------------------------------------- single, DELTA +10
    #
    # Moved from Ascension's level 22 to 32: at 22 it collides with Consume Magic and the
    # 30-34 stretch has nothing in it. Its numbers are Ascension's own at Ascension's level,
    # carried across unchanged and NOT re-measured for level 32.
    # FIXED: aura 330 -> 179, same remap and same reason as Bane of Fire. e1 (aura 79
    # MOD_DAMAGE_PERCENT_DONE, the drawback) is already legal.
    Ability("bane_of_power", "Bane of Power", 32, 12579,
            "Mark an enemy: you crit them harder, they hit harder.",
            cost=50,
            source=707902,
            second_records=("felfury",),
            note="12579 again -- aura 179 with a school-mask EffectMiscValue is precisely what "
                 "707902's e0 becomes, and the donor's misc 126 is the same kind of value"),

    # -- L34 -- Doomscar -------------------------------------------------- single, DELTA +1
    #
    # The raid debuff. `ap_bonus` 0.3 is plan 6.4's first enumerated coefficient (`$AP*0.3` on
    # e1's damage). The description's second clause, `$AGI*0.15` on the attack-power debuff, has
    # no `spell_bonus_data` column to live in -- a stat-scaled AURA amount is plan 4 C6's
    # problem, not a bonus row's.
    Ability("doomscar", "Doomscar", 34, 38067,
            "Scar an enemy so your allies hit them harder.",
            cost=35,
            source=563271,
            ap_bonus=0.3,
            note="38067 Guard's Mark is the ONLY record in stock Spell.dbc carrying aura 165 "
                 "MELEE_ATTACK_POWER_ATTACKER_BONUS -- measured across all 49,839 rows -- which "
                 "is 563271's e0"),

    # -- L36 -- Annihilation (the crit cooldown) --------------------------- single, DELTA +26
    #
    # 803904, the tab-87 node -- NOT 802059, the level-68 channelled nuke that shares its name.
    # Ascension puts it at level 10, which is absurd for a guaranteed-crit cooldown; it moves to
    # 36. Its numbers are Ascension's own at level 10, unchanged and unmeasured at 36.
    #
    # `proc_flags` IS AUTHORED. 803904's e1 is aura 42 PROC_TRIGGER_SPELL -> 807961 with
    # ProcTypeMask 0, because Ascension keeps the condition in engine code. Writing the mask
    # into the DBC makes SpellMgr.cpp:2160-2240 synthesise the proc entry from the record alone,
    # copying SpellFamilyName and the effect's mask and never entering the validator -- so no
    # `spell_proc` row and no `sql.sql` ERROR per boot (plan 4 C0).
    # The value is DONE_MELEE_AUTO_ATTACK 0x4 | DONE_SPELL_MELEE_DMG_CLASS 0x10 |
    # DONE_SPELL_RANGED_DMG_CLASS 0x100 | DONE_SPELL_NONE_DMG_CLASS_NEG 0x1000 |
    # DONE_SPELL_MAGIC_DMG_CLASS_NEG 0x10000 (SpellMgr.h:113-135), i.e. "any direct instance of
    # damage you deal", which is what the tooltip says. READ OUT OF THE HEADER, NOT OBSERVED --
    # plan 7 item 4 expects a debugging pass over exactly these.
    Ability("annihilation_crit", "Annihilation", 36, 35035,
            "Gorge on fel energy: your next strikes are guaranteed critical.",
            cost=0, cooldown_ms=60000,
            source=803904,
            proc_flags=0x00011114,
            note="35035 Countercharge is family 0, self-cast, aura 42 into a trigger with "
                 "ProcCharges 1 and a non-zero ProcTypeMask -- the DBC-only proc shape this "
                 "ability needs, with charges already wired"),

    # -- L38 -- Illidan's Guile ------------------------------------------- single, DELTA +10
    #
    # REBUILT. e0 is aura 106 HOVER, which is not a stun and does nothing the tooltip claims;
    # it becomes aura 12 MOD_STUN on self, keeping e1's aura 39 SCHOOL_IMMUNITY misc 127. That
    # pair is Ice Block (45438), not Divine Shield -- immune AND unable to act.
    # e2 is DELETED: `Effect 183` is above TOTAL_SPELL_EFFECTS and importing it ASSERTs the
    # worldserver dead at boot (SpellMgr.cpp:3039). Its payload was the "+20 yd on your next
    # Chaos Rush" rider, which is a nice-to-have, not a capstone.
    Ability("illidans_guile", "Illidan's Guile", 38, 45438,
            "Become untouchable, and unable to act.",
            cost=0, cooldown_ms=300000,
            source=806109,
            note="45438 Ice Block IS the rebuild target named by plan 2.2: aura 12 MOD_STUN "
                 "plus two aura 39 SCHOOL_IMMUNITY effects on self, which is what 806109's "
                 "e0/e1 become"),

    # -- L42 -- Whispers of the Pit --------------------------------------- single, DELTA +26
    #
    # The class's only hard crowd control, so it is not a level-16 button. Ascension's numbers
    # at level 16, carried unchanged to 42 and not re-measured.
    # `Mechanic = MECHANIC_FEAR (5)` for the same reason Cripple sets SNARE: with family 16
    # unknown to the core, Mechanic is the only DR input, and an undiminished AoE fear is a PvP
    # bug rather than a balance choice.
    # e1 is DELETED (`DUMMY -> 807590`, a self-cast twin of the same spell); e0's aura 7
    # MOD_FEAR and e2's aura 33 at -80% are both legal and both stay.
    # `proc_flags` is NOT authored: 805235 already ships 664232, the taken-damage set that makes
    # "damage caused may interrupt the effect" true.
    Ability("whispers_of_the_pit", "Whispers of the Pit", 42, 30283,
            "Fel whispers scatter and slow everything at a point.",
            cost=0, cooldown_ms=60000, mechanic=5,
            source=805235,
            note="30283 Shadowfury, named by plan 6.2 -- a ground-targeted burst whose effects "
                 "sit on the same implicit target 16 with the same EffectRadiusIndex 14 that "
                 "805235's three effects use"),

    # -- L46 -- Sunder ---------------------------------------------------- single, DELTA +32
    #
    # C++ OR NOTHING (plan 7). The record is one aura 23 firing 707508 every 300 ms; 707508 then
    # sequences three explosions (707509 / 712398 / 712399) plus a PERSISTENT_AREA_AURA, split
    # among everything struck. Neither the sequencing nor the split is expressible in a cell.
    # TODO(felsworn_spells.cpp, plan 4 C5): the channel accumulator, the three-way sequence and
    # the per-target damage split. Plan 7 item 5 flags the falloff as the fiddliest code in the
    # port and the easiest place to write an accidental O(n^2).
    # TODO(felsworn_allspellscript, plan 4 C1): "Consumes 2 Felfury" is in the tooltip only --
    # the gate belongs in OnSpellCheckCast and the debit in OnSpellCast.
    # `sunder_blast` (91380) is triggered BY `sunder_tick`, not by Sunder, so it is not listed
    # as a triggered half here; the generator has no way to express a second-record chain and
    # 707508's EffectTriggerSpell has to be repointed by hand in dh_donors.OVERRIDES.
    Ability("sunder", "Sunder", 46, 1949,
            "Sunder the ground ahead in three advancing detonations.",
            cost=30, cooldown_ms=8000,
            source=705121,
            second_records=("sunder_tick",),
            note="1949 Hellfire is the channel shape already vetted in dh_donors -- aura 23 "
                 "PERIODIC_TRIGGER_SPELL on self driving a separate tick record, which is "
                 "705121's e0"),

    # -- L50 -- Blood of Mannoroth ---------------------------------------- single, DELTA +10
    #
    # A PURE Energy-regen cooldown until a talent is taken, and the tooltip must say so. e0's
    # aura 280 MOD_ARMOR_PENETRATION_PCT is bp = -1, i.e. amount ZERO -- the armour penetration
    # number is supplied by talent 803903 Fel Haze and by nothing else. Shipping the Ascension
    # tooltip verbatim would promise a number the record does not contain.
    # `ManaCostPct 20` of POWER_HEALTH (-2) becomes 20 flat Energy. That is a CHOICE between the
    # two options plan 2.2 offers, made to match Immolation Aura's `-2 -> 3` conversion so the
    # class has exactly one resource; the health cost is not preserved anywhere.
    # e2 (`TRIGGER_SPELL -> 801043`) is DELETED: 801043's only effect is Ascension's private
    # effect 175, which has no 3.3.5a meaning.
    # TODO(felsworn_allspellscript, plan 4 C1): "Generates 6 Felfury" cannot be data.
    # `Unit::_TryStackingOrRefreshingExistingAura` (Unit.cpp:4665) adds exactly ONE stack per
    # triggered cast, so +6 must call the module's GrantFelfury(player, 6) from OnSpellCast.
    Ability("blood_of_mannoroth", "Blood of Mannoroth", 50, 13750,
            "Soak in Mannoroth's blood: Energy floods back.",
            cost=20, cooldown_ms=180000,
            source=802075,
            note="13750 Adrenaline Rush is PowerType 3, RecoveryTime 180000, and its one effect "
                 "is aura 110 MOD_POWER_REGEN_PERCENT at EffectMiscValue 3 (POWER_ENERGY) -- "
                 "802075's e1 and its cooldown, cell for cell"),

    # -- L54 -- Greater Man'ari Intuition ---------------------------------- single, DELTA -6
    #
    # Pulled down from 60 so it is not a cap-level button. `ManaCostPct 24` becomes 24 flat
    # Energy on the 0-100 bar. One rank on purpose: it is the party version of a ladder, and a
    # second rank would need its own Ascension record, which does not exist.
    Ability("greater_manari", "Greater Man'ari Intuition", 54, 21849,
            "Armour and primary stats for the whole party and raid.",
            cost=24,
            source=523495,
            note="21849 Gift of the Wild is aura 22 misc 1 + aura 29 misc -1 on implicit target "
                 "56 at EffectRadiusIndex 12 -- 523495's e0/e1, targets and radius index all "
                 "identical"),

    # -- L58 -- Reckoning --------------------------------------------------------------- single
    #
    # `proc_flags` IS AUTHORED, same mechanism as Annihilation: e2 is aura 42 -> 524632 with
    # ProcTypeMask 0. The proc is "Fel Fireball damage", so the mask is
    # DONE_SPELL_NONE_DMG_CLASS_NEG 0x1000 | DONE_SPELL_MAGIC_DMG_CLASS_NEG 0x10000. BOTH are
    # set deliberately: which one fires depends on the donor's DefenseType, and setting both
    # means the record does not silently depend on that choice. Read out of SpellMgr.h:128-134,
    # not observed -- plan 7 item 4.
    #
    # ONE UNRESOLVED CELL: plan 6.1 says "Reckoning needs two" triggered halves, but plan 5
    # allocates a block only for `reckoning_stack` (524632). The other trigger is e1's
    # `EffectTriggerSpell 521241`, hanging off an aura 107 ADD_FLAT_MODIFIER at
    # EffectMiscValue 17 -- and a spellmod effect does not read EffectTriggerSpell at all.
    # TODO(plan 5): either allocate a block for 521241 or confirm the cell is vestigial and
    # zero it. Shipping it pointing at an Ascension id that our Spell.dbc does not contain is
    # the one option that is definitely wrong.
    Ability("reckoning", "Reckoning", 58, 12042,
            "For a time, Fel Fireball is free, instant, and multiplies.",
            cost=0, cooldown_ms=120000,
            source=802058,
            proc_flags=0x00011000,
            second_records=("reckoning_stack",),
            note="12042 Arcane Power is a self-cast RecoveryTime 120000 cooldown whose effects "
                 "are three aura 108 spellmods -- 802058's own cooldown and its e0/e1 shape; "
                 "its family-3 SpellClassMasks are zeroed by dh_donors.ALWAYS"),

    # -- L70 -- Oblivion --------------------------------------------- single, DELTA +2, PHASE 2
    #
    # The capstone, and the record with the most wrong with it. FOUR fixes:
    #   1. `attributes[0] = 0x40090` sets SPELL_ATTR0_DO_NOT_DISPLAY (0x80). Learned, castable,
    #      and INVISIBLE in the spellbook. Clear the bit.
    #   2. `mana_cost 2500` is a sentinel on a 0-100 Energy bar. Replaced with 30, which is
    #      CHOSEN and not derived -- it matches the kit's other Felfury spenders (Ruin 30,
    #      Felwrath 30, Sunder 30, plan 1). Ascension's cell carries no usable information.
    #   3. `TargetAuraState = 13` AURA_STATE_HEALTHLESS_35_PERCENT (SharedDefines.h:1293),
    #      checked at SpellInfo.cpp:1824, is the whole "only below 35% health" gate, for free.
    #   4. e2's trigger 572132 is rebuilt as plain SCHOOL_DAMAGE; its aura 4 DUMMY implements
    #      nothing.
    # The tooltip's two "(Combo)" clauses -- after Doomscar, after Annihilan Strike -- have NO
    # 3.3.5a data path at all. Drop them and rewrite Description_Lang_enUS rather than shipping
    # a lie. Same for `$u`: e1's stacking heal absorb has no CumulativeAura in the dump, so
    # `stack_amount` is left 0 rather than invented.
    # Ascension keeps the 8 s cooldown in CategoryRecoveryTime, shared with the phase-3 rank
    # ladder 802400-802404; re-expressed as RecoveryTime for the reason given on Hateforged.
    Ability("oblivion", "Oblivion", 70, 5308,
            "Obliterate a dying enemy with both weapons.",
            cost=30, cooldown_ms=8000, target_aura_state=13,
            source=800215,
            second_records=("oblivion_dot",),
            note="5308 Execute is the stock precedent for exactly this shape: a melee finisher "
                 "gated by TargetAuraState (2, AURA_STATE_HEALTHLESS_20_PERCENT) rather than by "
                 "a script, which is the mechanism fix 3 above relies on"),

    # -- L66 -- Annihilation (the channelled nuke) ------------------- single, DELTA -2, PHASE 2
    #
    # 802059, NOT 803904. Pulled from 68 to 66 so the 60-70 stretch has more than one button.
    Ability("annihilation", "Annihilation", 66, 15407,
            "Channel chaotic magic into one enemy.",
            cost=0, cooldown_ms=25000,
            source=802059,
            second_records=("annihilation_tick",),
            note="15407 Mind Flay is the canonical channelled aura 227 "
                 "PERIODIC_TRIGGER_SPELL_WITH_VALUE, firing a tick record on a period with an "
                 "EffectBonusMultiplier -- 802059's e0 shape; its MaxLevel 28 and its "
                 "ShapeshiftMask are closed by dh_donors.ALWAYS"),

    # -- L62 -- Fel Eruption ----------------------------------------- single, DELTA -6, PHASE 2
    #
    # Pulled from 68 to 62 for the same reason. Its "Combo: (Felwrath, This)" clause is the same
    # unportable Ascension system as Oblivion's and is dropped from the tooltip, not faked.
    Ability("fel_eruption", "Fel Eruption", 62, 35759,
            "Erupt fel energy through an enemy, leaving it burning.",
            cost=20,
            source=706534,
            note="35759 Felfire Shock is family 0: SCHOOL_DAMAGE plus an aura 3 PERIODIC_DAMAGE "
                 "on TARGET_UNIT_TARGET_ENEMY -- 706534's e0/e1 exactly"),
)


# =============================================================================================
# Self-check
# =============================================================================================
#
# Runnable with no database, no client and no DBC files, which is what lets it guard a pull
# request:  python3 .work/felsworn/abilities.py
#
# It is a `main` and not a test file for the same reason the rest of the feature is one
# generator: a check that lives next to the data it checks is a check that gets updated with it.

def selftest():
    """Assert the ladder's internal consistency. Raises AssertionError on the first problem."""
    block_keys = [k for k, _ in ABILITY_BLOCK_ORDER]
    assert len(block_keys) == len(set(block_keys)), "ABILITY_BLOCKS has a duplicate key"
    assert len(SINGLES_ORDER) == len(set(SINGLES_ORDER)), "SINGLES_ORDER has a duplicate key"
    # A `singles` block holds 20 ids (dh_spec.IDS_PER_ABILITY); a 21st entry would silently
    # collide with the first id of `singles2`.
    assert len(SINGLES_ORDER) <= 20, (
        f"SINGLES_ORDER has {len(SINGLES_ORDER)} entries but a block holds 20")
    overlap = set(block_keys) & set(SINGLES_ORDER)
    assert not overlap, f"key(s) in both ABILITY_BLOCKS and SINGLES_ORDER: {sorted(overlap)}"

    # 31, not plan 2.1's 30: Inner Demon was missing from that table and is added back. See
    # its entry for why the omission was load-bearing rather than cosmetic.
    assert len(ABILITIES) == 31, f"30 from plan 2.1 + Inner Demon, this is {len(ABILITIES)}"

    seen = set()
    for a in ABILITIES:
        # An ability whose key names no block is a spell the generator will never emit, and the
        # failure is a blank spellbook slot rather than an error.
        where = (a.key in block_keys) + (a.key in SINGLES_ORDER)
        assert where == 1, (
            f"{a.key}: appears in ABILITY_BLOCKS/SINGLES_ORDER {where} times, must be exactly 1")
        assert a.key not in seen, f"{a.key}: two Ability rows share this key"
        seen.add(a.key)

        # `donor` stays REQUIRED alongside `source`: it is the row cloned before the import
        # overwrites it, so a failed import degrades instead of emitting a blank record.
        assert a.source, f"{a.key}: every Felsworn ability is imported and needs source="
        assert a.donor, f"{a.key}: donor= is required even with source= (dh_spec.py:852-870)"

        assert len(a.source_ranks) + 1 == a.ranks, (
            f"{a.key}: ranks={a.ranks} but source_ranks has {len(a.source_ranks)} entries; "
            f"source_ranks EXCLUDES source itself")
        if a.ranks > 1:
            assert len(a.rank_levels) == a.ranks, (
                f"{a.key}: {a.ranks} ranks but {len(a.rank_levels)} rank_levels")
            assert a.rank_levels[0] == a.level, (
                f"{a.key}: rank_levels[0] is {a.rank_levels[0]}, learn level is {a.level}")
            # A rank that is learned at or below the rank under it never supersedes it, so both
            # sit in the spellbook at once and the player picks the wrong one.
            for i in range(1, a.ranks):
                assert a.rank_levels[i] > a.rank_levels[i - 1], (
                    f"{a.key}: rank {i + 1} at level {a.rank_levels[i]} does not ascend past "
                    f"rank {i} at {a.rank_levels[i - 1]}")
            assert a.source not in a.source_ranks, (
                f"{a.key}: source {a.source} is repeated inside source_ranks")
            assert len(set(a.source_ranks)) == len(a.source_ranks), (
                f"{a.key}: source_ranks has a duplicate Ascension id")
        else:
            assert not a.rank_levels, f"{a.key}: single-record ability must not set rank_levels"

        # A triggered half that names no block is an EffectTriggerSpell pointing at nothing.
        for half in a.triggered_halves():
            assert half in block_keys, f"{a.key}: triggered half {half!r} has no ID block"

        assert 1 <= a.level <= 80, f"{a.key}: learn level {a.level} is outside 1..80"
    return True


def main():
    selftest()
    at_cap = sum(1 for a in ABILITIES if a.level <= 60)
    print(f"Felsworn ladder: {len(ABILITIES)} abilities, "
          f"levels {min(a.level for a in ABILITIES)}-{max(a.level for a in ABILITIES)}, "
          f"{at_cap} at the live cap of 60")
    for a in sorted(ABILITIES, key=lambda x: (x.level, x.name)):
        ladder = f"{a.ranks} ranks" if a.ranks > 1 else "single"
        print(f"  L{a.level:<3d} {a.name:26s} src {a.source:<7d} donor {a.donor:<6d} {ladder}")
    print("\nabilities self-check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
