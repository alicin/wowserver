/*
 * GENERATED FILE -- DO NOT EDIT.
 *
 * Produced by build/modules/mod-demon-hunter/tools/dhspells.py from tools/dh_spec.py.
 * Regenerate with `scripts/build-client-patch.sh`.
 *
 * WHY THE PROGRESSION IS A COMPILED TABLE AND NOT A WORLD TABLE
 * ------------------------------------------------------------
 * One source of truth. This array, the spell_dbc rows the server reads and the Spell.dbc
 * records the client reads all come out of the same spec in the same run, so they cannot
 * drift. A world table would add a load-order dependency and a second thing to keep in sync,
 * and it would buy nothing: changing the progression means regenerating the client DBC and
 * repackaging the client anyway.
 *
 * There is also no hot reload for spell data (LoadDBCStores has exactly one call site,
 * World.cpp:384), so nothing is gained by making this runtime-editable.
 */

#ifndef MOD_DEMON_HUNTER_DH_PROGRESSION_H
#define MOD_DEMON_HUNTER_DH_PROGRESSION_H

#include "Define.h"

#include <array>

// NOT DkGrant. Two statically-linked modules defining different structs with the same name is
// an ODR violation: it links without a diagnostic and misbehaves at run time.
struct DhGrant
{
    uint8  level;
    uint32 spellId;
};

// Sorted by level, then spell id. Reconcile() walks this in order and breaks on the first
// entry above the player's level, so the ordering is load-bearing rather than cosmetic.
constexpr DhGrant kDhProgression[] =
{
    {   1, 91000 },   // Twin Slice
    {   1, 91001 },   // Twin Slice
    {   1, 91002 },   // Twin Slice
    {   1, 91003 },   // Twin Slice
    {   1, 91004 },   // Twin Slice
    {   1, 91005 },   // Twin Slice
    {   1, 91006 },   // Twin Slice
    {   1, 91007 },   // Twin Slice
    {   1, 91020 },   // Sargeron Smite
    {   1, 91021 },   // Sargeron Smite
    {   1, 91022 },   // Sargeron Smite
    {   1, 91023 },   // Sargeron Smite
    {   1, 91024 },   // Sargeron Smite
    {   1, 91025 },   // Sargeron Smite
    {   1, 91026 },   // Sargeron Smite
    {   1, 91027 },   // Sargeron Smite
    {   1, 91028 },   // Sargeron Smite
    {   2, 91040 },   // Fel Fireball
    {   2, 91041 },   // Fel Fireball
    {   2, 91042 },   // Fel Fireball
    {   2, 91043 },   // Fel Fireball
    {   2, 91044 },   // Fel Fireball
    {   2, 91045 },   // Fel Fireball
    {   2, 91046 },   // Fel Fireball
    {   2, 91047 },   // Fel Fireball
    {   2, 91048 },   // Fel Fireball
    {   2, 91480 },   // Inner Demon
    {   4, 91060 },   // Chaos Rush
    {   4, 91061 },   // Chaos Rush
    {   4, 91062 },   // Chaos Rush
    {   6, 91500 },   // Bane of Fire
    {   8, 91080 },   // Man'ari Intuition
    {   8, 91081 },   // Man'ari Intuition
    {   8, 91082 },   // Man'ari Intuition
    {   8, 91083 },   // Man'ari Intuition
    {   8, 91084 },   // Man'ari Intuition
    {   8, 91085 },   // Man'ari Intuition
    {  10, 91100 },   // Hateforged Barrier
    {  10, 91101 },   // Hateforged Barrier
    {  10, 91102 },   // Hateforged Barrier
    {  10, 91103 },   // Hateforged Barrier
    {  10, 91104 },   // Hateforged Barrier
    {  10, 91105 },   // Hateforged Barrier
    {  12, 91501 },   // Bane of Frailty
    {  13, 91120 },   // Felspears
    {  13, 91121 },   // Felspears
    {  13, 91122 },   // Felspears
    {  13, 91123 },   // Felspears
    {  13, 91124 },   // Felspears
    {  13, 91125 },   // Felspears
    {  13, 91126 },   // Felspears
    {  13, 91127 },   // Felspears
    {  14, 91140 },   // Cripple
    {  14, 91141 },   // Cripple
    {  14, 91142 },   // Cripple
    {  14, 91143 },   // Cripple
    {  14, 91144 },   // Cripple
    {  14, 91145 },   // Cripple
    {  16, 91502 },   // Betray
    {  18, 91503 },   // Skull of Gul'dan
    {  20, 91160 },   // Manafeed
    {  20, 91161 },   // Manafeed
    {  20, 91162 },   // Manafeed
    {  20, 91163 },   // Manafeed
    {  22, 91504 },   // Consume Magic
    {  24, 91180 },   // Illidari Intuition
    {  24, 91181 },   // Illidari Intuition
    {  24, 91182 },   // Illidari Intuition
    {  24, 91183 },   // Illidari Intuition
    {  24, 91184 },   // Illidari Intuition
    {  26, 91505 },   // Blur
    {  28, 91506 },   // Felbane
    {  30, 91507 },   // Bane of Betrayal
    {  32, 91508 },   // Bane of Power
    {  34, 91509 },   // Doomscar
    {  36, 91510 },   // Annihilation
    {  38, 91511 },   // Illidan's Guile
    {  42, 91512 },   // Whispers of the Pit
    {  46, 91513 },   // Sunder
    {  50, 91514 },   // Blood of Mannoroth
    {  54, 91515 },   // Greater Man'ari Intuition
    {  58, 91516 },   // Reckoning
    {  62, 91517 },   // Fel Eruption
    {  66, 91518 },   // Annihilation
    {  70, 91519 },   // Oblivion
};

// =============================================================================================
// THE FELFURY RESOURCE -- read by src/felfury_core.cpp
// =============================================================================================
//
// Declared in tools/dh_spec.py and resolved to ids here, so that "which spells move the
// resource" is one fact in one place. See the comment above dh_spec.FELFURY_ABILITY_GENERATORS.

// The band every Felsworn spell id falls in, used as the cheap first test on hooks that run for
// every cast and every aura application on the realm. MAX is EXCLUSIVE.
constexpr uint32 FELSWORN_SPELL_ID_MIN = 91000;
constexpr uint32 FELSWORN_SPELL_ID_MAX = 93000;

constexpr uint32 FELFURY_SPELL_ID     = 91460;   // the resource itself
constexpr uint32 INNER_DEMON_SPELL_ID = 91480;   // the form it is spent on

// The untalented cap the module enforces in code, and the CumulativeAura cell on the felfury
// record -- which must be the FULLY TALENTED maximum, because the pure-data +1 goes through
// Aura::ModStackAmount and clamps against it (SpellAuras.cpp:973-980).
constexpr uint8  FELFURY_MAX_STACKS    = 6;
constexpr uint8  FELFURY_STACK_CEILING = 6;

// Milliseconds of Inner Demon bought by one Felfury. Ascension multiplies 803465's +5000 ms
// SPELLMOD_DURATION by the stacks spent; Player::ApplySpellMod adds a flat mod exactly once and
// never scales it by a stack count (Player.cpp:10077-10078), so the multiply is script.
constexpr uint32 INNER_DEMON_MS_PER_FELFURY = 5000;

// `spellId` is the RANK 1 id of a chain; the module maps any rank back to it with
// SpellMgr::GetFirstSpellInChain (SpellMgr.cpp:603-609), which is why one row covers all nine
// ranks of Sargeron Smite. std::array and not a C array because a table can legitimately be
// EMPTY, and `constexpr DhFelfuryFlow kDhFelAddictRanks[] = {};` is ill-formed C++.
//
// The Dh prefix is not decoration: mod-dk-lowlevel is statically linked into the same
// worldserver binary, and two modules defining different types under one name is an ODR
// violation that links without a diagnostic.
struct DhFelfuryFlow
{
    uint32 spellId;
    uint8  stacks;
};

// `stacks` is what the MODULE adds on top of the authored `Effect 64 -> felfury`, NOT
// the ability's advertised total. A generator whose whole grant is data has no row here
// and needs none: the resource aura's own ceiling is enforced when that +1 lands.
constexpr std::array<DhFelfuryFlow, 9> kDhFelfuryGenerators =
{{
    DhFelfuryFlow{ 91000, 1 },   // twin_slice -- 1 total, 0 from data
    DhFelfuryFlow{ 91040, 1 },   // fel_fireball -- 1 total, 0 from data
    DhFelfuryFlow{ 91500, 1 },   // bane_of_fire -- 1 total, 0 from data
    DhFelfuryFlow{ 91501, 1 },   // bane_of_frailty -- 1 total, 0 from data
    DhFelfuryFlow{ 91507, 1 },   // bane_of_betrayal -- 1 total, 0 from data
    DhFelfuryFlow{ 91508, 1 },   // bane_of_power -- 1 total, 0 from data
    DhFelfuryFlow{ 91514, 6 },   // blood_of_mannoroth -- 6 total, 0 from data
    DhFelfuryFlow{ 92038, 6 },   // Burning Hatred -- 6 total, 0 from data
    DhFelfuryFlow{ 92100, 2 },   // Annihilan Strike -- 2 total, 0 from data
}};

// `stacks` is the cost. Inner Demon is deliberately absent -- it eats the whole pool,
// which is not a cell, and a row here would debit it twice.
constexpr std::array<DhFelfuryFlow, 6> kDhFelfurySpenders =
{{
    DhFelfuryFlow{ 91020, 2 },   // sargeron_smite -- 2 per cast
    DhFelfuryFlow{ 91513, 2 },   // sunder -- 2 per cast
    DhFelfuryFlow{ 92015, 2 },   // Carve -- 2 per cast
    DhFelfuryFlow{ 92084, 2 },   // Azzinoth's Assault -- 2 per cast
    DhFelfuryFlow{ 92149, 2 },   // Ruin -- 2 per cast
    DhFelfuryFlow{ 92166, 2 },   // Felwrath -- 2 per cast
}};

// `stacks` is how much the talent raises the cap. Ascension's own aura 107 carries
// SpellModOp 31, which does not exist here (MAX_SPELLMOD is 32, SpellDefines.h:109), so
// the cap has to be arithmetic in the module rather than a spell mod.
constexpr std::array<DhFelfuryFlow, 0> kDhFelAddictRanks = {};

// Felheart's SPELLMOD_ALL_EFFECTS is what raises the resource's three zero-amount haste
// carriers to 1% each. The module recomputes the aura when one of these is learnt or unlearnt.
constexpr std::array<uint32, 0> kDhFelheartRanks = {};

#endif // MOD_DEMON_HUNTER_DH_PROGRESSION_H
