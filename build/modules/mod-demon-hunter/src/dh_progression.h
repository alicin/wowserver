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

#endif // MOD_DEMON_HUNTER_DH_PROGRESSION_H
