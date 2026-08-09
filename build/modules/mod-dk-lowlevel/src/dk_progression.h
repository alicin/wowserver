/*
 * GENERATED FILE -- DO NOT EDIT.
 *
 * Produced by build/modules/mod-dk-lowlevel/tools/dkspells.py from tools/dk_spec.py.
 * Regenerate with `tools/dkspells.py`; verify with `tools/dkspells.py --check`.
 *
 * WHY THE PROGRESSION IS A COMPILED TABLE AND NOT A WORLD TABLE
 * ------------------------------------------------------------
 * One source of truth. This array, the spell_dbc rows the server reads and the Spell.dbc
 * records the client reads all come out of the same spec in the same run, so they cannot
 * drift. A world table would add a load-order dependency and a second thing to keep in sync,
 * and it would buy nothing: changing the progression means regenerating the client DBC and
 * repackaging the client anyway, which is a rebuild either way.
 *
 * There is also no hot reload available for the spell data (LoadDBCStores has exactly one
 * call site, World.cpp:384), so nothing is gained by making this runtime-editable.
 */

#ifndef MOD_DK_LOWLEVEL_DK_PROGRESSION_H
#define MOD_DK_LOWLEVEL_DK_PROGRESSION_H

#include "Define.h"

struct DkGrant
{
    uint8  level;
    uint32 spellId;
};

// Sorted by level, then spell id. Reconcile() walks this in order and breaks on the first
// entry above the player's level, so the ordering is load-bearing, not cosmetic.
//
// THREE KINDS OF ENTRY, ALL learnSpell(id) TO THE MODULE:
//
//   90xxx  a generated low rank -- a byte-clone of the stock rank 1 with its damage/heal/stat
//          cells scaled to the level, and a spell_ranks row placing it below the stock ranks.
//   stock  an ability with nothing to scale (a percentage, a taunt, a summon that scales to its
//          owner). Blizzard's own record, unmodified, granted early.
//   stock  at 55-65: the FIRST stock rank of a re-ranked ability. This is the handoff. Granting
//          it here rather than leaving it to mod-learn-spells is what makes "from 55 you are on
//          stock Blizzard data" a property of this module instead of a dependency on another
//          one (DESIGN.md 4). Stock ranks ABOVE the first are deliberately absent: how a Death
//          Knight gets Icy Touch rank 11 at 61 is unchanged by this feature.
static constexpr DkGrant kDkProgression[] =
{
    {  1, 48266 },   // Blood Presence -- stock spell, nothing to scale
    {  1, 90000 },   // Icy Touch (Rank 1) -- 11-13 Frost damage
    {  1, 90020 },   // Plague Strike (Rank 1) -- 6 bonus weapon damage
    {  1, 90040 },   // Blood Strike (Rank 1) -- 12 bonus weapon damage
    {  2, 90060 },   // Death Coil (Rank 1) -- 18 Shadow damage
    {  4, 49576 },   // Death Grip -- stock spell, nothing to scale
    {  6, 90080 },   // Death Strike (Rank 1) -- 16 bonus weapon damage, 73 Effect_3 dummy (tooltip only)
    {  7, 90001 },   // Icy Touch (Rank 2) -- 25-27 Frost damage
    {  7, 90021 },   // Plague Strike (Rank 2) -- 20 bonus weapon damage
    {  7, 90041 },   // Blood Strike (Rank 2) -- 42 bonus weapon damage
    {  8, 47528 },   // Mind Freeze -- stock spell, nothing to scale
    {  8, 90061 },   // Death Coil (Rank 2) -- 36 Shadow damage
    { 10, 50842 },   // Pestilence -- stock spell, nothing to scale
    { 12, 90081 },   // Death Strike (Rank 2) -- 28 bonus weapon damage, 116 Effect_3 dummy (tooltip only)
    { 12, 90120 },   // Blood Boil (Rank 1) -- 25-29 Shadow damage
    { 13, 90002 },   // Icy Touch (Rank 3) -- 40-42 Frost damage
    { 13, 90022 },   // Plague Strike (Rank 3) -- 34 bonus weapon damage
    { 13, 90042 },   // Blood Strike (Rank 3) -- 71 bonus weapon damage
    { 14, 45524 },   // Chains of Ice -- stock spell, nothing to scale
    { 14, 90062 },   // Death Coil (Rank 3) -- 54 Shadow damage
    { 16, 56222 },   // Dark Command -- stock spell, nothing to scale
    { 18, 90082 },   // Death Strike (Rank 3) -- 40 bonus weapon damage, 158 Effect_3 dummy (tooltip only)
    { 18, 90121 },   // Blood Boil (Rank 2) -- 34-40 Shadow damage
    { 18, 90160 },   // Horn of Winter (Rank 1) -- 29 Strength, 29 Agility
    { 19, 90003 },   // Icy Touch (Rank 4) -- 52-56 Frost damage
    { 19, 90023 },   // Plague Strike (Rank 4) -- 48 bonus weapon damage
    { 19, 90043 },   // Blood Strike (Rank 4) -- 100 bonus weapon damage
    { 20, 48263 },   // Frost Presence -- stock spell, nothing to scale
    { 20, 56815 },   // Rune Strike -- stock spell, nothing to scale
    { 20, 90063 },   // Death Coil (Rank 4) -- 72 Shadow damage
    { 22, 48792 },   // Icebound Fortitude -- stock spell, nothing to scale
    { 24, 48707 },   // Anti-Magic Shell -- stock spell, nothing to scale
    { 24, 90083 },   // Death Strike (Rank 4) -- 52 bonus weapon damage, 199 Effect_3 dummy (tooltip only)
    { 24, 90122 },   // Blood Boil (Rank 3) -- 43-51 Shadow damage
    { 24, 90161 },   // Horn of Winter (Rank 2) -- 37 Strength, 37 Agility
    { 25, 90004 },   // Icy Touch (Rank 5) -- 66-71 Frost damage
    { 25, 90024 },   // Plague Strike (Rank 5) -- 62 bonus weapon damage
    { 25, 90044 },   // Blood Strike (Rank 5) -- 128 bonus weapon damage
    { 26, 90064 },   // Death Coil (Rank 5) -- 89 Shadow damage
    { 26, 90140 },   // Death and Decay (Rank 1) -- 13 Shadow damage per second
    { 28, 46584 },   // Raise Dead -- stock spell, nothing to scale
    { 30, 3714 },   // Path of Frost -- stock spell, nothing to scale
    { 30, 90084 },   // Death Strike (Rank 5) -- 64 bonus weapon damage, 240 Effect_3 dummy (tooltip only)
    { 30, 90123 },   // Blood Boil (Rank 4) -- 51-61 Shadow damage
    { 30, 90162 },   // Horn of Winter (Rank 3) -- 44 Strength, 44 Agility
    { 31, 90005 },   // Icy Touch (Rank 6) -- 78-84 Frost damage
    { 31, 90025 },   // Plague Strike (Rank 6) -- 75 bonus weapon damage
    { 31, 90045 },   // Blood Strike (Rank 6) -- 156 bonus weapon damage
    { 32, 45529 },   // Blood Tap -- stock spell, nothing to scale
    { 32, 90065 },   // Death Coil (Rank 6) -- 106 Shadow damage
    { 32, 90141 },   // Death and Decay (Rank 2) -- 15 Shadow damage per second
    { 34, 47476 },   // Strangulate -- stock spell, nothing to scale
    { 36, 48743 },   // Death Pact -- stock spell, nothing to scale
    { 36, 90085 },   // Death Strike (Rank 6) -- 76 bonus weapon damage, 279 Effect_3 dummy (tooltip only)
    { 36, 90124 },   // Blood Boil (Rank 5) -- 59-71 Shadow damage
    { 36, 90163 },   // Horn of Winter (Rank 4) -- 52 Strength, 52 Agility
    { 37, 90006 },   // Icy Touch (Rank 7) -- 91-98 Frost damage
    { 37, 90026 },   // Plague Strike (Rank 7) -- 88 bonus weapon damage
    { 37, 90046 },   // Blood Strike (Rank 7) -- 183 bonus weapon damage
    { 38, 48265 },   // Unholy Presence -- stock spell, nothing to scale
    { 38, 90066 },   // Death Coil (Rank 7) -- 122 Shadow damage
    { 38, 90142 },   // Death and Decay (Rank 3) -- 18 Shadow damage per second
    { 40, 47568 },   // Empower Rune Weapon -- stock spell, nothing to scale
    { 42, 90086 },   // Death Strike (Rank 7) -- 87 bonus weapon damage, 318 Effect_3 dummy (tooltip only)
    { 42, 90125 },   // Blood Boil (Rank 6) -- 68-81 Shadow damage
    { 42, 90164 },   // Horn of Winter (Rank 5) -- 59 Strength, 59 Agility
    { 43, 90007 },   // Icy Touch (Rank 8) -- 103-111 Frost damage
    { 43, 90027 },   // Plague Strike (Rank 8) -- 100 bonus weapon damage
    { 43, 90047 },   // Blood Strike (Rank 8) -- 209 bonus weapon damage
    { 44, 90067 },   // Death Coil (Rank 8) -- 138 Shadow damage
    { 44, 90143 },   // Death and Decay (Rank 4) -- 20 Shadow damage per second
    { 45, 42650 },   // Army of the Dead -- stock spell, nothing to scale
    { 48, 90087 },   // Death Strike (Rank 8) -- 98 bonus weapon damage, 356 Effect_3 dummy (tooltip only)
    { 48, 90126 },   // Blood Boil (Rank 7) -- 76-91 Shadow damage
    { 48, 90165 },   // Horn of Winter (Rank 6) -- 66 Strength, 66 Agility
    { 49, 90008 },   // Icy Touch (Rank 9) -- 115-124 Frost damage
    { 49, 90028 },   // Plague Strike (Rank 9) -- 113 bonus weapon damage
    { 49, 90048 },   // Blood Strike (Rank 9) -- 235 bonus weapon damage
    { 50, 90068 },   // Death Coil (Rank 9) -- 154 Shadow damage
    { 50, 90144 },   // Death and Decay (Rank 5) -- 22 Shadow damage per second
    { 54, 90088 },   // Death Strike (Rank 9) -- 108 bonus weapon damage, 394 Effect_3 dummy (tooltip only)
    { 54, 90127 },   // Blood Boil (Rank 8) -- 84-101 Shadow damage
    { 54, 90166 },   // Horn of Winter (Rank 7) -- 73 Strength, 73 Agility
    { 55, 45462 },   // Plague Strike (Rank 10) -- stock 45462, the 55+ handoff
    { 55, 45477 },   // Icy Touch (Rank 10) -- stock 45477, the 55+ handoff
    { 55, 45902 },   // Blood Strike (Rank 10) -- stock 45902, the 55+ handoff
    { 55, 47541 },   // Death Coil (Rank 10) -- stock 47541, the 55+ handoff
    { 56, 49998 },   // Death Strike (Rank 10) -- stock 49998, the 55+ handoff
    { 56, 90145 },   // Death and Decay (Rank 6) -- 25 Shadow damage per second
    { 58, 48721 },   // Blood Boil (Rank 9) -- stock 48721, the 55+ handoff
    { 60, 43265 },   // Death and Decay (Rank 7) -- stock 43265, the 55+ handoff
    { 60, 90167 },   // Horn of Winter (Rank 8) -- 80 Strength, 80 Agility
    { 65, 57330 },   // Horn of Winter (Rank 9) -- stock 57330, the 55+ handoff
};

static constexpr uint32 kDkProgressionCount =
    static_cast<uint32>(sizeof(kDkProgression) / sizeof(kDkProgression[0]));

// Utilities the skipped Acherus starter chain used to hand out. Granted by learnSpell(), never
// by casting the quest reward spells: 53821 (quest 12801) runs SPELL_EFFECT_BIND and would
// silently rebind the player's hearthstone at every login, and 53431 is unnecessary because
// learnSpell(53428) alone drives Player::addSpell's SKILL_RUNEFORGING branch
// (Player.cpp:3377). 48778, the Acherus Deathcharger, is deliberately NOT here.
static constexpr uint32 DK_SPELL_DEATH_GATE         = 50977;   // DKLowLevel.DeathGateLevel, default level 30
static constexpr uint32 DK_SPELL_RUNEFORGING        = 53428;   // DKLowLevel.RuneforgingLevel, default level 30

#endif // MOD_DK_LOWLEVEL_DK_PROGRESSION_H
