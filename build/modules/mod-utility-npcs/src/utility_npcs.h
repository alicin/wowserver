/*
 * mod-utility-npcs -- put the realm's six utility NPCs where players actually are.
 *
 * NINETY-NINE PERCENT OF THIS MODULE IS THE SQL MIGRATION under data/sql/db-world/base/, which
 * UpdateFetcher applies at worldserver boot. The C++ here does exactly two things that data
 * cannot:
 *
 *   1. the off switch. `creature` rows have no "enabled" column, so turning the feature off is
 *      a runtime act.
 *   2. the boot-time guid-block audit. The generator checks the reserved block against the DB it
 *      was pointed at, at authoring time. This checks it against the database the server is
 *      ACTUALLY running on, at boot, every boot -- which is the one that matters after a world-DB
 *      update or a restore from someone else's dump.
 *
 * There is deliberately no per-tick, per-player or per-creature-update work. Read the comment on
 * utility_npcs_allcreaturescript before adding any.
 */

#ifndef MOD_UTILITY_NPCS_H_
#define MOD_UTILITY_NPCS_H_

#include "Config.h"                 // sConfigMgr
#include "Creature.h"
#include "DatabaseEnv.h"            // WorldDatabase
#include "Log.h"
#include "ScriptMgr.h"

// GENERATED -- tools/gen_spawns.py, from the SAME spec that emits the SQL migration. Do not
// hand-edit and do not restate its constants anywhere else. Contract:
//     kUtilityNpcGuidFirst / kUtilityNpcGuidLast   inclusive reserved creature.guid range
//     kUtilityNpcSpawnIdCeiling                    0xFFFFFF, ObjectMgr.cpp:7657
//     kUtilityNpcSpawnCount                        rows the migration inserts
//     kUtilityNpcEntries[]                         every creature_template entry we may place
#include "utility_npcs_range.h"

static_assert(kUtilityNpcGuidFirst < kUtilityNpcGuidLast,
    "utility_npcs_range.h: the reserved block is empty or inverted -- regenerate it");
static_assert(kUtilityNpcGuidLast < kUtilityNpcSpawnIdCeiling,
    "utility_npcs_range.h: the reserved block reaches ObjectMgr::GenerateCreatureSpawnId's "
    "0xFFFFFF shutdown threshold -- the worldserver would StopNow on the first `.npc add`");
static_assert(kUtilityNpcSpawnCount <= kUtilityNpcGuidLast - kUtilityNpcGuidFirst + 1,
    "utility_npcs_range.h: more spawns than guids in the block -- regenerate it");
static_assert(sizeof(kUtilityNpcEntries) / sizeof(kUtilityNpcEntries[0]) > 0,
    "utility_npcs_range.h: no entries -- regenerate it");

struct UtilityNpcsConfig
{
    // The one knob. Default matches conf/mod_utility_npcs.conf.dist; see the comment in
    // UtilityNpcsConfig::Load for why that matters more than it looks like it should.
    bool Enable = true;

    void Load();
};

extern UtilityNpcsConfig sUtilityNpcs;

// True for a creature this module spawned. Two integer compares against a compile-time constant
// range; no allocation, no lookup, no DB.
//
// Deliberately keyed on the SPAWN ID and not on the entry. Entry 190010 also legitimately exists
// as a GM-placed `.npc add` spawn or as a future hand-written row, and the off switch has no
// business hiding somebody else's NPC. The reserved block is what this module owns.
inline bool IsUtilityNpcSpawn(Creature const* creature)
{
    ObjectGuid::LowType const id = creature->GetSpawnId();
    return id >= kUtilityNpcGuidFirst && id <= kUtilityNpcGuidLast;
}

class utility_npcs_worldscript : public WorldScript
{
public:
    utility_npcs_worldscript() : WorldScript("utility_npcs_worldscript",
    {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD,
        WORLDHOOK_ON_STARTUP
    }) { }

    // WorldScript.h:53 and :74. NOT `OnWorldAfterConfigLoad` -- the OnPlayerXxx renaming on this
    // fork is PlayerScript-only, WorldScript kept its original names. Hooks are listed
    // explicitly above because WorldScript's constructor treats an empty vector as "every hook"
    // (WorldScript.cpp:87-96), which would register this script against all thirteen dispatch
    // lists for the sake of two.
    void OnAfterConfigLoad(bool reload) override;
    void OnStartup() override;
};

class utility_npcs_allcreaturescript : public AllCreatureScript
{
public:
    utility_npcs_allcreaturescript() : AllCreatureScript("utility_npcs_allcreaturescript") { }

    // AllCreatureScript.h:44. Dispatched from Creature::AddToWorld (Creature.cpp:333), i.e. ONCE
    // per creature per grid load, after Unit::AddToWorld has set IsInWorld -- which is what makes
    // SetVisible's UpdateObjectVisibility legal here.
    //
    // THIS IS THE ONLY HOOK THIS MODULE TAKES, AND THAT IS A COST DECISION. AllCreatureScript
    // also offers OnAllCreatureUpdate, which would let the switch apply instantly instead of at
    // the next grid load -- at the price of one extra virtual dispatch per creature per world
    // tick, forever, on a realm that runs playerbots. A config flip is a rare, deliberate,
    // operator-initiated act; paying for it continuously is the wrong trade.
    //
    // NOT USED, AND IT MUST NOT BE: AllCreatureScript::CanCreatureGossipHello exists in the
    // header (AllCreatureScript.h:67) and is NEVER DISPATCHED on this fork -- the only caller of
    // that name is CreatureScript.cpp:31, which is the per-entry CreatureScript's identically
    // named method. Overriding it here compiles perfectly and does nothing at all.
    void OnCreatureAddWorld(Creature* creature) override;
};

#endif // MOD_UTILITY_NPCS_H_
