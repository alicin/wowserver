/*
 * mod-dk-lowlevel -- TRUE level-1 Death Knights.
 *
 * DESIGN.md artefact A15. Three hooks and an idempotent reconcile; everything else about this
 * feature is data (world-DB `*_dbc` override rows + a client patch MPQ). This module deliberately
 * owns no spell data of its own -- the progression table is GENERATED into `dk_progression.h` by
 * tools/dkspells.py from the same spec that emits the SQL and the client DBC, so the three can
 * never drift (DESIGN.md 6, risk 8.3).
 */

#ifndef MOD_DK_LOWLEVEL_H_
#define MOD_DK_LOWLEVEL_H_

#include "AreaDefines.h"            // MAP_EBON_HOLD (609) -- src/server/game/Maps/AreaDefines.h:260
#include "Config.h"   // sConfigMgr
#include "Log.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "SharedDefines.h"          // CLASS_DEATH_KNIGHT -- src/server/shared/SharedDefines.h:131

#include <cstddef>

// GENERATED -- tools/dkspells.py. Do not hand-edit, and do not copy its contents anywhere.
// Contract (DESIGN.md 5.2), asserted below:
//     struct DkGrant { uint8 level; uint32 spellId; };
//     static constexpr DkGrant kDkProgression[] = { {1, 90000}, ... };   // ascending by level
#include "dk_progression.h"

// The `if (g.level > lvl) break;` early-out in Reconcile() is only correct on a table sorted by
// level, and a silently unsorted table would hand out a partial spellbook that looks plausible.
// Cheaper to make it a compile error. Also catches a level-0 or spell-0 row, either of which
// would mean the generator emitted a placeholder.
template<std::size_t N>
constexpr bool DkProgressionIsWellFormed(DkGrant const (&table)[N])
{
    for (std::size_t i = 0; i < N; ++i)
    {
        if (table[i].level == 0 || table[i].spellId == 0)
            return false;

        if (i > 0 && table[i - 1].level > table[i].level)
            return false;
    }

    return N > 0;
}

static_assert(DkProgressionIsWellFormed(kDkProgression),
    "dk_progression.h is empty, unsorted, or contains a zero level/spellId -- regenerate it with tools/dkspells.py");

// Cached copies of every knob except the master switch, refreshed from OnAfterConfigLoad so
// `.reload config` takes effect without a restart (DESIGN.md 5.4). The master switch is read
// live inside Reconcile() instead: it is checked once per login, which is nothing, and reading
// it live means the module cannot get stuck "on" if a future ordering change makes
// OnAfterConfigLoad run before our WorldScript is registered.
struct DkLowLevelConfig
{
    bool  FixAcherusTalents = true;
    uint8 DeathGateLevel    = 1;
    uint8 RuneforgingLevel  = 1;

    void Load();
};

extern DkLowLevelConfig sDkLowLevelConfig;

class dk_lowlevel_playerscript : public PlayerScript
{
public:
    // Hooks are opted into EXPLICITLY. PlayerScript's ctor treats an empty vector as "all hooks"
    // (PlayerScript.cpp:963-971), which would register this script against all ~130 dispatch
    // lists for the three we actually implement.
    dk_lowlevel_playerscript() : PlayerScript("dk_lowlevel_playerscript",
    {
        PLAYERHOOK_ON_LOGIN,
        PLAYERHOOK_ON_LEVEL_CHANGED,
        PLAYERHOOK_ON_CALCULATE_TALENTS_POINTS
    }) { }

    // EVERY PlayerScript virtual on this fork is OnPlayerXxx. `OnLogin` / `OnLevelChanged` exist
    // on upstream AzerothCore but NOT here: writing them compiles clean as brand-new non-virtual
    // members and the hook simply never fires. Verified signatures:
    //   PlayerScript.h:337  virtual void OnPlayerLogin(Player*)
    //   PlayerScript.h:267  virtual void OnPlayerLevelChanged(Player*, uint8 /*oldlevel*/)
    //   PlayerScript.h:237  virtual void OnPlayerCalculateTalentsPoints(Player const*, uint32&)
    // `override` on all three is what makes a future rename a build error instead of a no-op.
    void OnPlayerLogin(Player* player) override;
    void OnPlayerLevelChanged(Player* player, uint8 oldLevel) override;
    void OnPlayerCalculateTalentsPoints(Player const* player, uint32& talentPointsForLevel) override;

private:
    static void Reconcile(Player* player);
};

class dk_lowlevel_worldscript : public WorldScript
{
public:
    dk_lowlevel_worldscript() : WorldScript("dk_lowlevel_worldscript",
    {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD
    }) { }

    // WorldScript.h:53 -- `OnAfterConfigLoad(bool reload)`, NOT `OnWorldAfterConfigLoad`. The
    // OnPlayerXxx renaming is PlayerScript-only; WorldScript kept its original names.
    void OnAfterConfigLoad(bool reload) override;
};

void AddSC_dk_lowlevel();

#endif // MOD_DK_LOWLEVEL_H_
