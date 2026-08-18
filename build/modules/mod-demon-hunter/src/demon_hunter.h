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

    /*
     * The two Felfury knobs, defaulted from the GENERATED constants rather than from a literal.
     * A number typed here would be a second opinion about a value dh_spec.py already owns, and
     * the failure it produces is silent: a cap of 4 against a CumulativeAura of 6 is a resource
     * that looks like it works and is one stack short of every tooltip.
     *
     * Neither knob honours a configured ZERO -- see EffectiveFelfuryCap and InnerDemonMsPerFelfury
     * in felfury_core.cpp. Unlike DualWieldLevel, where 0 is a deliberate "off" position, a cap
     * of zero and a duration-per-stack of zero have no reading other than "typo", and the
     * behaviours they would ship (a visible aura holding nothing; a form that expires on the
     * tick it is entered) are worse than anything an operator could have meant.
     */
    uint8  FelfuryMaxStacks       = FELFURY_MAX_STACKS;
    uint32 InnerDemonMsPerFelfury = INNER_DEMON_MS_PER_FELFURY;

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
 * The server half of the addon's Double Jump and Glide, AND the Felfury resource (buckets C1
 * and C2 of .work/felsworn/port-plan.md section 4, implemented in felfury_core.cpp).
 *
 * An AllSpellScript and NOT a SpellScript, and that is not a style choice. A SpellScript is
 * bound to its spell through the world table `spell_script_names` (ObjectMgr.cpp:6345), so using
 * one would mean this module shipping SQL -- and tools/dh_spec.py is the single source of every
 * SQL statement in this feature. AllSpellScript::IsDatabaseBound() is false
 * (AllSpellScript.h:52): it is registered in code, needs no row, and keeps the generator's
 * ownership of data intact.
 *
 * ONE CLASS AND NOT TWO. felfury_core.cpp adds two of the three overrides below rather than
 * introducing a parallel AllSpellScript, because a second script would mean a second entry in
 * every dispatch list it enabled for no gain. It is registered exactly once, by
 * AddSC_demon_hunter -- registering it again from AddSC_felsworn_felfury would put it twice in
 * each list and every Felfury debit would happen twice.
 *
 * The three hooks, all verified in AllSpellScript.h:
 *   OnSpellCheckCast   (:57)  dispatched from the very top of Spell::CheckCast (Spell.cpp:5666),
 *                             before the cooldown check at :5672, before power cost, and before
 *                             Spell::prepare reaches TriggerGlobalCooldown at :3686. A failure
 *                             written into `res` is free in exactly the way NOTES.md 5.4 and
 *                             port-plan 4.C1 both require.
 *   OnSpellCast        (:103) dispatched from the LAST lines of Spell::_cast (Spell.cpp:4077),
 *                             after TakePower (:3923). The Felfury debit and multi-grant.
 *   OnCalcMaxDuration  (:55)  dispatched from Aura::CalcMaxDuration (SpellAuras.cpp:807). Inner
 *                             Demon's duration, which is bought with the Felfury pool.
 *
 * HOOKS ARE OPTED INTO EXPLICITLY. AllSpellScript's constructor treats an empty `enabledHooks`
 * vector as "all hooks" (AllSpellScript.cpp:96-98 -- the same rule PlayerScript has at
 * PlayerScript.cpp:967-969), which would register this script against all fourteen AllSpellHook
 * dispatch lists for the sake of three.
 *
 * The class keeps its name. `demon_hunter_movement_allspellscript` is now half a misnomer --
 * port-plan 6.5 proposes renaming it `felsworn_allspellscript` -- but the name is not free to
 * change: it is the string handed to ScriptObject, so a rename is a rename of the row in
 * `acore_world.scriptnames` too, and it would touch felfury_core.cpp and demon_hunter.cpp in
 * the same breath as a behaviour change. Left for its own commit.
 */
class demon_hunter_movement_allspellscript : public AllSpellScript
{
public:
    demon_hunter_movement_allspellscript() : AllSpellScript("demon_hunter_movement_allspellscript",
    {
        ALLSPELLHOOK_ON_SPELL_CHECK_CAST,
        ALLSPELLHOOK_ON_CAST,
        ALLSPELLHOOK_ON_CALC_MAX_DURATION
    }) { }

    // Defined in demon_hunter.cpp. It calls Felsworn::GateFelfurySpender before its own test.
    void OnSpellCheckCast(Spell* spell, bool strict, SpellCastResult& res) override;

    // Both defined in felfury_core.cpp. `override` is what makes a future signature change in
    // AllSpellScript.h a build error here instead of a silently dead hook.
    void OnSpellCast(Spell* spell, Unit* caster, SpellInfo const* spellInfo,
        bool skipCheck) override;
    void OnCalcMaxDuration(Aura const* aura, int32& maxDuration) override;
};

/*
 * The Felfury cast-time gate, called from demon_hunter_movement_allspellscript::OnSpellCheckCast.
 *
 * A free function and not a fourth override because that override already has a definition in
 * demon_hunter.cpp, and a function may be defined only once. Splitting the gate out is the
 * smaller lie than moving the falling gate -- which has nothing to do with Felfury -- into a
 * file named for it.
 */
namespace Felsworn
{
    void GateFelfurySpender(Spell const* spell, SpellCastResult& res);
}

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

/*
 * Registration, split by translation unit and called in this order from AddSC_demon_hunter.
 *
 *   AddSC_demon_hunter()        demon_hunter.cpp   -- the WorldScript, the PlayerScript and the
 *                                                     one AllSpellScript above.
 *   AddSC_felsworn_felfury()    felfury_core.cpp   -- buckets C1/C2. Registers ONLY its own
 *                                                     UnitScript; the AllSpellScript overrides
 *                                                     it defines belong to the object above.
 *   AddSC_felsworn_spells()     felsworn_spells.cpp -- buckets C3-C8. The DB-bound
 *                                                     SpellScript/AuraScript classes, plus C7's
 *                                                     UnitScript.
 */
void AddSC_demon_hunter();
void AddSC_felsworn_felfury();
void AddSC_felsworn_spells();

#endif // MOD_DEMON_HUNTER_H_
