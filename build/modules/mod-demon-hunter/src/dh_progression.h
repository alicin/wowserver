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
    {   1, 91000 },   // Demon's Bite
    {   1, 91500 },   // Double Jump
    {   2, 91020 },   // Chaos Strike
    {   4, 91040 },   // Fel Rush
    {   6, 91501 },   // Glide
    {   8, 91060 },   // Throw Glaive
    {  10, 91080 },   // Immolation Aura
    {  12, 91503 },   // Spectral Sight
    {  14, 91504 },   // Consume Magic
    {  16, 91100 },   // Blade Dance
    {  20, 91502 },   // Vengeful Retreat
    {  24, 91505 },   // Blur
    {  28, 91506 },   // Chaos Nova
    {  32, 91507 },   // Torment
    {  36, 91120 },   // Fiery Brand
    {  40, 91508 },   // Metamorphosis
    {  44, 91509 },   // Imprison
    {  48, 91140 },   // Sigil of Flame
    {  52, 91160 },   // Soul Cleave
    {  56, 91180 },   // Eye Beam
    {  60, 91510 },   // Darkness
    {  70, 91511 },   // Infernal Strike
};

#endif // MOD_DEMON_HUNTER_DH_PROGRESSION_H
