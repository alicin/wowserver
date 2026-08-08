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
static constexpr DkGrant kDkProgression[] =
{
    {  1, 90000 },   // Icy Touch (Rank 1) -- 10-12 Frost damage
};

static constexpr uint32 kDkProgressionCount =
    static_cast<uint32>(sizeof(kDkProgression) / sizeof(kDkProgression[0]));

// Utilities the skipped Acherus starter chain used to hand out. Granted by learnSpell(), never
// by casting the quest reward spells: 53821 (quest 12801) runs SPELL_EFFECT_BIND and would
// silently rebind the player's hearthstone at every login, and 53431 is unnecessary because
// learnSpell(53428) alone drives Player::addSpell's SKILL_RUNEFORGING branch
// (Player.cpp:3377). 48778, the Acherus Deathcharger, is deliberately NOT here.
static constexpr uint32 DK_SPELL_DEATH_GATE         = 50977;   // DKLowLevel.DeathGateLevel, default level 1
static constexpr uint32 DK_SPELL_RUNEFORGING        = 53428;   // DKLowLevel.RuneforgingLevel, default level 1

#endif // MOD_DK_LOWLEVEL_DK_PROGRESSION_H
