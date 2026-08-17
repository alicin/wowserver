/*
 * mod-demon-hunter -- the Demon Hunter as a REAL player class, class id 10.
 *
 * Read README.md first; it carries the IsClass context table (the reason a new class is viable
 * at all), the three grants this module makes that no data path can make, and -- sections 8 and
 * 9 -- the findings about OTHER components of this feature that the module cannot fix and must
 * not paper over. Two of those are live defects, not notes.
 *
 * Modelled on mod-dk-lowlevel, deliberately and closely: the shape of the problem is the same
 * (a class whose spellbook the core will not hand out on its own) and there is no value in a
 * second idiom. Where this module differs from that one it is because the Demon Hunter differs
 * from the Death Knight, and the difference is written down at the point it appears.
 *
 * THE MODULE OWNS FOUR THINGS AND NOTHING ELSE:
 *
 *   1. Reconcile()          -- hand out the ability ladder the character has grown into.
 *   2. OnPlayerIsClass()    -- answer, per context, which existing class a Demon Hunter is.
 *   3. Three untrainable spells -- 674 Dual Wield, 3127 Parry, and the race's own gated racial.
 *                              The class has no trainer and the stock SkillLineAbility rows
 *                              predate class 10, so nothing else grants them. README.md 6.
 *   4. The falling gate on Double Jump and Glide -- .work/dh-parts/addon/NOTES.md 5.4.
 *
 * Everything else about the class is DATA: world-DB `*_dbc` override rows, playercreateinfo*
 * rows, and records appended to the client's DBCs, all emitted by tools/dhspells.py from
 * tools/dh_spec.py. This module owns no spell data -- the progression table is GENERATED into
 * dh_progression.h by that same generator in the same run, so the C++ table, the server's damage
 * roll and the client's tooltip cannot drift.
 *
 * CLASS_DEMON_HUNTER DOES NOT EXIST IN THE PINNED CORE. It is added by
 * build/patches/0001-demon-hunter-class-10.patch, which build/Dockerfile applies to /src after
 * the module COPY and before the compile. .work/ac-src/src/server/shared/SharedDefines.h:135 is
 * still `//CLASS_UNK = 10` on disk; do not "fix" the reference to a literal 10 because the
 * checkout does not resolve it.
 */

#ifndef MOD_DEMON_HUNTER_H_
#define MOD_DEMON_HUNTER_H_

#include "Config.h"                 // sConfigMgr
#include "Log.h"
#include "Optional.h"               // Optional<bool> -- src/common/Utilities/Optional.h
#include "Player.h"
#include "ScriptMgr.h"              // pulls AllScriptsObjects.h -> {All,Player,World}Script
#include "SharedDefines.h"          // CLASS_DEMON_HUNTER (via the core patch), SpellCastResult
#include "Spell.h"                  // Spell::GetSpellInfo / GetCaster -- Spell.h:590, :593
#include "UnitDefines.h"            // ClassContext -- src/server/game/Entities/Unit/UnitDefines.h:231-251

#include <cstddef>
#include <iterator>                 // std::size, used once for the boot log line

// GENERATED -- tools/dhspells.py. Do not hand-edit, and do not copy its contents anywhere.
// Contract, asserted below:
//     struct DhGrant { uint8 level; uint32 spellId; };
//     constexpr DhGrant kDhProgression[] = { {1, 91000}, ... };        // ascending by level,
//                                                                      // then by spell id
//
// The struct is DhGrant and the array is kDhProgression -- NOT DkGrant/kDkProgression.
// mod-dk-lowlevel is statically linked into the same worldserver binary and defines a struct of
// its own by that name. Two statically-linked modules defining DIFFERENT structs under ONE name
// is an ODR violation: it links without a diagnostic and misbehaves at run time. The distinct
// names are the whole guard, so do not "harmonise" them.
#include "dh_progression.h"

// The `if (grant.level > level) break;` early-out in Reconcile() is only correct on a table
// sorted by level, and a silently unsorted table hands out a partial spellbook that looks
// entirely plausible in game. Cheaper to make it a compile error. Also catches a level-0 or
// spellId-0 row, either of which means the generator emitted a placeholder.
template<std::size_t N>
constexpr bool DhProgressionIsWellFormed(DhGrant const (&table)[N])
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

static_assert(DhProgressionIsWellFormed(kDhProgression),
    "dh_progression.h is empty, unsorted, or contains a zero level/spellId -- regenerate it with tools/dhspells.py");

// Used once, at boot, to check that the two spell IDs the movement gate is compiled against are
// actually in the ladder. Deliberately NOT a static_assert: whether Double Jump and Glide appear
// in the grant table is tools/dhspells.py's decision, not this module's, and a build that will
// not compile because the generator changed its mind is a worse failure than a log line that
// says exactly what is wrong. See demon_hunter_worldscript::OnAfterConfigLoad.
template<std::size_t N>
constexpr bool DhProgressionHas(DhGrant const (&table)[N], uint32 spellId)
{
    for (std::size_t i = 0; i < N; ++i)
        if (table[i].spellId == spellId)
            return true;

    return false;
}

/*
 * Cached copies of every knob EXCEPT the master switch, refreshed from OnAfterConfigLoad so
 * `.reload config` takes effect without a restart.
 *
 * DemonHunter.Enable is read live at each call site instead. It is checked once per login in
 * Reconcile, once per cast of two spells in the movement gate, and once per IsClass call on a
 * character who is already known to be class 10 -- all of which are nothing next to the cost of
 * getting stuck "on". Reading it live means the module cannot be left enabled by an ordering
 * change that runs OnAfterConfigLoad before this WorldScript is registered.
 */
struct DemonHunterConfig
{
    uint8 DualWieldLevel = 1;
    uint8 ParryLevel     = 1;
    bool  GrantRacials   = true;

    void Load();
};

extern DemonHunterConfig sDemonHunterConfig;

class demon_hunter_playerscript : public PlayerScript
{
public:
    // Hooks are opted into EXPLICITLY. PlayerScript's constructor treats an empty enabledHooks
    // vector as "all hooks" (PlayerScript.cpp:963-971), which would register this script against
    // all 192 dispatch lists (PlayerScript.h:30-224) for the sake of three.
    demon_hunter_playerscript() : PlayerScript("demon_hunter_playerscript",
    {
        PLAYERHOOK_ON_LOGIN,
        PLAYERHOOK_ON_LEVEL_CHANGED,
        PLAYERHOOK_ON_PLAYER_IS_CLASS
    }) { }

    // EVERY PlayerScript virtual on this fork is OnPlayerXxx. `OnLogin` / `OnLevelChanged` exist
    // on upstream AzerothCore but NOT here: writing one compiles clean as a brand-new
    // non-virtual member and the hook simply never fires. Verified signatures:
    //   PlayerScript.h:337  virtual void OnPlayerLogin(Player*)
    //   PlayerScript.h:267  virtual void OnPlayerLevelChanged(Player*, uint8 /*oldlevel*/)
    //   PlayerScript.h:526  [[nodiscard]] virtual Optional<bool> OnPlayerIsClass(Player const*, Classes, ClassContext)
    // `override` on all three is what makes a future rename a build error instead of a no-op.
    void OnPlayerLogin(Player* player) override;
    void OnPlayerLevelChanged(Player* player, uint8 oldLevel) override;
    [[nodiscard]] Optional<bool> OnPlayerIsClass(Player const* player, Classes playerClass, ClassContext context) override;

private:
    static void Reconcile(Player* player);
};

/*
 * The server half of the addon's Double Jump and Glide.
 *
 * An AllSpellScript and NOT a SpellScript, and that is not a style choice. A SpellScript is
 * bound to its spell through the world table `spell_script_names` (ObjectMgr.cpp:6345), so using
 * one would mean this module shipping SQL -- and tools/dh_spec.py is the single source of every
 * SQL statement in this feature. AllSpellScript::IsDatabaseBound() is false
 * (AllSpellScript.h:52): it is registered in code, needs no row, and keeps the generator's
 * ownership of data intact.
 *
 * The one hook is OnSpellCheckCast (AllSpellScript.h:57), dispatched from the very top of
 * Spell::CheckCast (Spell.cpp:5666) -- before the cooldown check at :5672, before power cost,
 * and before Spell::prepare reaches TriggerGlobalCooldown at Spell.cpp:3686. Writing a failure
 * into `res` there is therefore free in exactly the way NOTES.md 5.4 requires.
 */
class demon_hunter_movement_allspellscript : public AllSpellScript
{
public:
    demon_hunter_movement_allspellscript() : AllSpellScript("demon_hunter_movement_allspellscript",
    {
        ALLSPELLHOOK_ON_SPELL_CHECK_CAST
    }) { }

    void OnSpellCheckCast(Spell* spell, bool strict, SpellCastResult& res) override;
};

class demon_hunter_worldscript : public WorldScript
{
public:
    demon_hunter_worldscript() : WorldScript("demon_hunter_worldscript",
    {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD
    }) { }

    // WorldScript.h:53 -- `OnAfterConfigLoad(bool reload)`, NOT `OnWorldAfterConfigLoad`. The
    // OnPlayerXxx renaming is PlayerScript-only; WorldScript kept its original names.
    void OnAfterConfigLoad(bool reload) override;
};

void AddSC_demon_hunter();

#endif // MOD_DEMON_HUNTER_H_
