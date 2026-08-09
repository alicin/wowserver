/*
 * mod-utility-npcs -- the off switch and the boot-time guid audit.
 *
 * Read utility_npcs.h first; it carries the hook-name warnings and the generated-header contract.
 */

#include "utility_npcs.h"

#include <string>

UtilityNpcsConfig sUtilityNpcs;

void UtilityNpcsConfig::Load()
{
    // This default MUST match conf/mod_utility_npcs.conf.dist.
    //
    // deploy/docker-compose.yml bind-mounts ../conf/modules over /opt/ac/etc/modules as a
    // DIRECTORY, which shadows the image's installed .conf.dist files entirely, and
    // ConfigMgr::LoadModulesConfigs only ever opens `<name>.conf` -- never `<name>.conf.dist`.
    // A key absent from conf/modules/mod_utility_npcs.conf therefore falls back to the literal
    // below, not to the .dist. Which is also why the repo's .conf lists the key explicitly.
    Enable = sConfigMgr->GetOption<bool>("UtilityNPCs.Enable", true);
}

void utility_npcs_worldscript::OnAfterConfigLoad(bool reload)
{
    sUtilityNpcs.Load();

    // Fires at boot (World.cpp, reached from World::SetInitialWorldSettings after
    // sScriptMgr->Initialize(), so this script is already registered the first time round) and
    // again on every `.reload config`. The log line is how an operator confirms a flip took.
    LOG_INFO("server.loading",
        "mod-utility-npcs: Enable={} reload={} block={}..{} ({} spawns expected)",
        sUtilityNpcs.Enable, reload,
        kUtilityNpcGuidFirst, kUtilityNpcGuidLast, kUtilityNpcSpawnCount);

    if (reload)
    {
        // Honesty about the scope of the switch. Creatures already standing in loaded grids keep
        // whatever visibility they were given when their grid loaded; OnCreatureAddWorld only
        // runs on the next load. Saying so here is cheaper than a support conversation.
        LOG_INFO("server.loading",
            "mod-utility-npcs: the new setting applies to each spawn the next time its grid "
            "loads. Restart the worldserver to apply it everywhere at once.");
    }
}

void utility_npcs_worldscript::OnStartup()
{
    // ------------------------------------------------------------------------------------------
    // The boot-time guid-block audit.
    //
    // tools/gen_spawns.py runs the same three checks, but it runs them against whichever database
    // the author pointed it at, on the day they ran it. This runs them against the database this
    // worldserver just booted on, every boot -- which is the one that catches a world-DB update,
    // a restore from somebody else's dump, or a second module that decided 10,000,000 looked
    // like a nice round number too.
    //
    // Cost: three trivial indexed queries, once, during startup. `guid` is the PRIMARY KEY, so
    // all three are range scans on the clustered index.
    // ------------------------------------------------------------------------------------------

    std::string ours;
    for (uint32 const entry : kUtilityNpcEntries)
        ours += (ours.empty() ? "" : ",") + std::to_string(entry);

    // 1. Is anything foreign parked inside our block? This is the one that would make the next
    //    generator run silently delete somebody else's spawn.
    if (QueryResult r = WorldDatabase.Query(
            "SELECT COUNT(*), MIN(guid) FROM creature WHERE guid BETWEEN {} AND {} "
            "AND id NOT IN ({})",
            kUtilityNpcGuidFirst, kUtilityNpcGuidLast, ours))
    {
        Field* f = r->Fetch();
        if (uint32 const n = f[0].Get<uint32>())
            LOG_ERROR("server.loading",
                "mod-utility-npcs: {} creature spawn(s) inside the reserved guid block "
                "{}..{} are NOT ours (first at guid {}). The next run of tools/gen_spawns.py "
                "WILL DELETE THEM -- move them out of the block or move the block.",
                n, kUtilityNpcGuidFirst, kUtilityNpcGuidLast, f[1].Get<uint32>());
    }

    // 2. Has the rest of the world DB grown into the block from below? An upstream update that
    //    reached 10,000,000 would collide on the very next apply.
    if (QueryResult r = WorldDatabase.Query(
            "SELECT IFNULL(MAX(guid), 0) FROM creature WHERE guid < {}", kUtilityNpcGuidFirst))
    {
        uint32 const highest = r->Fetch()[0].Get<uint32>();
        if (highest >= kUtilityNpcGuidFirst - 100000)
            LOG_ERROR("server.loading",
                "mod-utility-npcs: the world DB's highest guid outside the block is {}, within "
                "100k of the reserved block start {}. Move the block up before the next "
                "world-DB update.", highest, kUtilityNpcGuidFirst);
    }

    // 3. Did the migration actually apply? A mismatch for exactly one boot after the SQL changes
    //    is normal (UpdateFetcher applies it during this same startup, before maps load, so this
    //    should already see the new count). A mismatch that survives a restart means the module's
    //    data/ did not ship -- the classic cause being the repo-root `data/` gitignore rule, see
    //    this module's .gitignore.
    if (QueryResult r = WorldDatabase.Query(
            "SELECT COUNT(*) FROM creature WHERE guid BETWEEN {} AND {} AND id IN ({})",
            kUtilityNpcGuidFirst, kUtilityNpcGuidLast, ours))
    {
        uint32 const n = r->Fetch()[0].Get<uint32>();
        if (n != kUtilityNpcSpawnCount)
            LOG_ERROR("server.loading",
                "mod-utility-npcs: {} spawns in the reserved block, expected {}. The migration "
                "2026_08_08_20_utility_npcs_spawns.sql has not applied (check `updates`), or the "
                "module's data/sql/ did not ship in the image.", n, kUtilityNpcSpawnCount);
        else
            LOG_INFO("server.loading",
                "mod-utility-npcs: {} spawns present in guid block {}..{}.",
                n, kUtilityNpcGuidFirst, kUtilityNpcGuidLast);
    }
}

void utility_npcs_allcreaturescript::OnCreatureAddWorld(Creature* creature)
{
    // Fast path first: on a realm with playerbots this runs for every creature that ever enters
    // a grid, so the common case must be a single branch on a cached bool.
    if (sUtilityNpcs.Enable)
        return;

    if (!IsUtilityNpcSpawn(creature))
        return;

    // Unit::SetVisible(false) (Unit.cpp:11088-11096) raises the creature's server-side visibility
    // requirement to SEC_GAMEMASTER and calls UpdateObjectVisibility. Players cannot see it,
    // cannot target it and cannot gossip it; a GM still can, which is exactly right -- an
    // operator who turns the module off should still be able to find what they turned off.
    //
    // Chosen over DespawnOrUnsummon (which would respawn on the spawntimesecs timer and have to
    // be re-suppressed) and over deleting the rows (which is not a switch, it is a decision).
    creature->SetVisible(false);
}

void AddSC_utility_npcs()
{
    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process. This is the convention every module and core script follows.
    new utility_npcs_worldscript();
    new utility_npcs_allcreaturescript();
}
