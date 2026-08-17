/*
 * mod-demon-hunter -- the Felsworn's SHARED, DATABASE-BOUND spell and aura scripts.
 *
 * Read demon_hunter.h first, then .work/felsworn/port-plan.md section 4. This file holds that
 * section's buckets C3 through C9: one script name per bucket for the five DB-bound ones,
 * plus C7 as a code-registered UnitScript and C9 as nothing at all (see below). C1 (Felfury
 * accounting) and C2 (Inner Demon) are NOT here -- port-plan 6.5 puts both on the existing
 * demon_hunter_movement_allspellscript, and they live in their own translation unit.
 *
 * WHY THESE ARE THE ONLY CLASSES IN THE FEATURE THAT NEED A SQL ROW
 * -----------------------------------------------------------------
 * demon_hunter.h:150-163 states the ownership split and it is worth restating from the other
 * side. AllSpellScript, PlayerScript, WorldScript and UnitScript are registered IN CODE and
 * need no row -- AllSpellScript::IsDatabaseBound() is false (AllSpellScript.h:52). SpellScript
 * and AuraScript are the exception: ObjectMgr::LoadSpellScriptNames (ObjectMgr.cpp:6345) reads
 * `SELECT spell_id, ScriptName FROM spell_script_names` and that table is the ONLY way one of
 * these ever attaches to a spell. So every class below is inert until tools/dhspells.py emits
 * its rows, which is also the switch: a realm that has not applied the generated SQL simply
 * never loads them. That is why nothing in this file reads `DemonHunter.Enable` -- a config
 * lookup on Unit::RollMeleeOutcomeAgainst's path would cost every melee swing on the realm a
 * string hash to answer a question the absent rows already answer.
 *
 * ObjectMgr::ValidateSpellScripts (ObjectMgr.cpp:6399) instantiates each script once at boot
 * and logs `... did not match dbc effect data` for any hook whose effect index/type is absent
 * from the record. It does NOT erase the row for that -- only Validate() returning false does
 * (:6431, :6441). Every hook below is therefore either bound with EFFECT_ALL + SPELL_*_ANY, or
 * registered conditionally from the record itself in Register(), so a shared script bound to
 * thirty differently-shaped records logs nothing -- provided the generator emits the effect
 * that bucket's contract names. `m_scriptSpellId` is set by _Init() before _Register() in both
 * the boot path (:6430-6431) and the runtime path (SpellScriptLoader.cpp:37 then
 * Spell.cpp:8583-8595), which is what makes reading the record from Register() legal.
 *
 * THE CELL CONTRACT
 * -----------------
 * Ascension keeps these conditions in engine code, in effect ids (165/195) and aura ids
 * (354/112) that do not exist below TOTAL_SPELL_EFFECTS/TOTAL_AURAS. We author every record,
 * so each bucket instead reads real 3.3.5a columns that its own effect type leaves unused.
 * The generator writes them; nothing here is hardcoded to a spell id.
 *
 *   bucket  record shape                     cells this file reads
 *   ------  -------------------------------  ------------------------------------------------
 *   C3      aura 42 PROC_TRIGGER_SPELL       EffectTriggerSpell, EffectBasePoints (percent)
 *   C4      effect 3 DUMMY                   EffectMiscValue (target spell), value (delta ms)
 *   C5      aura 23/226 periodic + damage    EffectMiscValue/B, EffectDamageMultiplier
 *   C6      aura 107/108 spellmod            EffectMiscValueB (stat), EffectBasePoints (coeff)
 *   C7      aura 112 OVERRIDE_CLASS_SCRIPTS  EffectMiscValue (what), EffectMiscValueB (when)
 *   C8      aura 42 PROC_TRIGGER_SPELL       EffectMiscValue (N), EffectMiscValueB (counter)
 *
 * C9 (Fel Torpedo replacing Chaos Rush) has NO class here and that is the plan's own decision,
 * not an omission: port-plan section 4 C9 ships it as a talent-granted second button because
 * 3.3.5a has no data or script mechanism for swapping a spellbook entry, and 500610 is
 * otherwise pure data.
 *
 * Every number quoted in a comment below is Ascension's own cell, read out of
 * build/tools/ascension/out/felsworn-family20.json and cited by spell id. Where a value had to
 * be re-expressed to fit a 3.3.5a column the comment says so and says who does the conversion.
 * Nothing here was measured.
 */

#include "demon_hunter.h"

#include "SpellAuraEffects.h"       // AuraEffect::GetAmount / GetMiscValue / IsAffectedOnSpell
#include "SpellAuras.h"             // Aura::ModStackAmount, AuraApplication::GetRemoveMode
#include "SpellMgr.h"               // sSpellMgr -- rank chains, SpellInfo lookup
#include "SpellScript.h"
#include "Util.h"                   // CalculatePct / AddPct -- src/common/Utilities/Util.h

#include <algorithm>
#include <cmath>
#include <unordered_map>

namespace
{
    /*
     * WHAT AN aura-112 EFFECT MEANS TO US.
     *
     * AuraEffect::HandleOverrideClassScriptAuraEffect is a switch on MiscValue and Ascension's
     * 20000-range ids have no case, so the aura is inert on this core and the two cells are
     * ours to define. They are kept at Ascension's own numbers wherever those are unambiguous,
     * so the generator can copy the cell through rather than translate it:
     *
     *   MiscValue  20000  92087 e1 / 705127 e0 / 802180  -- a critical-strike CHANCE bonus
     *   MiscValue  20007  520833 e1 / 804610             -- a DAMAGE DONE bonus
     *   MiscValueB    23  705127 / 520833 e1             -- "victim above 75% health"
     *   MiscValueB    26  804610                         -- "victim is slowed"
     *
     * 802180 Fel Cannon carries MiscValueB 28 for a condition its own tooltip words exactly as
     * 705127's 23 ("enemies above 75% health"), so 28 is NOT a distinct predicate and is not
     * given one here; the generator normalises it to 23.
     */
    enum FelswornClassScriptOp : int32
    {
        FS_CS_CRIT_CHANCE   = 20000,
        FS_CS_DAMAGE_DONE   = 20007,
    };

    enum FelswornVictimCondition : int32
    {
        FS_VICTIM_ANY               = 0,
        FS_VICTIM_ABOVE_75_HEALTH   = 23,
        FS_VICTIM_SLOWED            = 26,
    };

    /*
     * The shared victim predicate. port-plan section 4 C7 asks for exactly one of these so that
     * Annihilan Strike's "guaranteed crit above 75%" and You Cheat, Gul'dan!'s "+crit damage
     * above 75%" cannot drift apart from Doomsayer's "+25% Sargeron Smite above 75%".
     *
     * Note the asymmetry with the DATA half: TargetAuraState 23 (SpellInfo.cpp:1824) already
     * gates whether a spell may be CAST at all. This predicate is for the effects that must let
     * the cast through and change its outcome, which no aura state can express.
     */
    bool VictimConditionHolds(int32 condition, Unit const* victim)
    {
        switch (condition)
        {
            case FS_VICTIM_ANY:
                return true;
            case FS_VICTIM_ABOVE_75_HEALTH:
                return victim->HealthAbovePct(75);
            case FS_VICTIM_SLOWED:
                return victim->HasAuraType(SPELL_AURA_MOD_DECREASE_SPEED);
            default:
                // An unknown code is a generator bug, and silently meaning "always" would hide
                // it behind a talent that merely looks overtuned. Fail closed instead.
                return false;
        }
    }

    /*
     * WHICH RUNTIME NUMBER A C6 SPELLMOD SCALES WITH -- EffectMiscValueB on the aura 107/108
     * effect. That cell is free: AuraEffect::CalculateSpellMod (SpellAuraEffects.cpp:690-706)
     * builds the SpellModifier from GetMiscValue() (the SpellModOp), the aura type and the
     * effect's SpellClassMask, and never looks at MiscValueB.
     *
     * The stat codes are `Stats + 1` so that 0 keeps its natural meaning of "cell not written".
     */
    enum FelswornStatSource : int32
    {
        FS_STAT_NONE            = 0,
        FS_STAT_STRENGTH        = 1,
        FS_STAT_AGILITY         = 2,    // Felblade 574146, Felcaked Blades 574145
        FS_STAT_STAMINA         = 3,
        FS_STAT_INTELLECT       = 4,
        FS_STAT_SPIRIT          = 5,    // also the upper bound of the GetStat range below
        FS_STAT_DODGE_PERCENT   = 10,   // Burning Commander 92089, Pure Hatred 803478
        FS_STAT_ENERGY          = 20,   // Archimonde's Wrath 300489
    };

    float ReadStatSource(Unit const* owner, int32 source)
    {
        if (source >= FS_STAT_STRENGTH && source <= FS_STAT_SPIRIT)
            return owner->GetStat(Stats(source - FS_STAT_STRENGTH));

        switch (source)
        {
            case FS_STAT_DODGE_PERCENT:
                // Burning Commander 92089 and Pure Hatred 803478 both say "dodge rating".
                // This is deliberately the PERCENT the rating buys, not the raw rating points:
                // Player::GetRatingBonusValue (Player.cpp:5362) multiplies the field by
                // GetRatingMultiplier, so the value is already level-normalised and the
                // coefficient the generator authors does not have to be re-tuned per bracket.
                // Only a Player has combat ratings at all.
                return owner->IsPlayer() ? owner->ToPlayer()->GetRatingBonusValue(CR_DODGE) : 0.0f;
            case FS_STAT_ENERGY:
                // Archimonde's Wrath 300489: "$s2% for every 10 points of Energy". Energy moves
                // every tick, so this source is only as fresh as the last recalculation -- see
                // the staleness note on spell_fs_stat_spellmod.
                return float(owner->GetPower(POWER_ENERGY));
            default:
                return 0.0f;
        }
    }

    /*
     * WHERE A TRIGGERED PAYLOAD LANDS, decided from the payload's own record rather than from a
     * list of spell ids. Shared by C3 and C8 because both buckets mix the two directions freely:
     * Straight to the Nether leeches the victim while Felguard heals the party, and Sculptor of
     * Doom buffs the caster while Felwracked hits whatever was in front of them. A hardcoded id
     * list would be a second source of truth for a fact SpellInfo::IsPositive already states,
     * and the failure mode -- a talent that silently does nothing -- is the expensive kind.
     *
     * Returns nullptr when the payload id has no record at all, which is a generator bug worth
     * failing quietly on rather than feeding to Unit::CastSpell's "unknown spell" log line on
     * every proc.
     */
    Unit* PayloadTarget(uint32 payloadId, Unit* caster, Unit* procTarget)
    {
        SpellInfo const* info = sSpellMgr->GetSpellInfo(payloadId);
        if (!info)
            return nullptr;

        return (info->IsPositive() || !procTarget) ? caster : procTarget;
    }

    // Cheapest possible rejection for the UnitScript hot path: a type-id test and one
    // UNIT_FIELD_BYTES_0 compare. CLASS_DEMON_HUNTER is class id 10, added by
    // build/patches/0001-demon-hunter-class-10.patch -- the enumerator keeps the Demon Hunter
    // name because the patch does; the class the realm ships in that slot is the Felsworn.
    bool IsFelsworn(Unit const* unit)
    {
        return unit && unit->IsPlayer() && unit->getClass() == CLASS_DEMON_HUNTER;
    }
}

/*
 * =============================================================================================
 * C3 -- "trigger spell X with N% of the damage dealt"
 * =============================================================================================
 *
 * Ascension aura 354, which does not exist below TOTAL_AURAS. Six talents share it and every
 * one of them is the same sentence with a different percentage and a different payload:
 *
 *   560503 Straight to the Nether  bp 19 -> 20%  -> 705124  (HEALTH_LEECH)
 *   560542 Felguard e1             bp 14 -> 15%  -> 560627  (HEAL)
 *   805239 Burning Hatred e0       bp 49 -> 50%  -> 807347  (HEALTH_LEECH, a legal effect 9)
 *   806111 Demonic Machinations    bp  9 -> 10%  -> 806112  (aura 3, the Deep Wounds shape)
 *   807461 Herald of the Legion    bp 49 -> 50%  -> 807554  (SCHOOL_DAMAGE)
 *   805236 Grommash's Folly        bp 24 -> 25%  -> 807426  -> 560839 (HEAL)
 *
 * (bp+1 because every one of those cells is DieSides 1, and SpellEffectInfo::CalcValue
 * (SpellInfo.cpp:409-445) reads DieSides 1 as "BasePoints + 1, fixed".)
 *
 * The record keeps stock aura 42 SPELL_AURA_PROC_TRIGGER_SPELL with the same EffectTriggerSpell
 * and the same EffectBasePoints; this script is only here because the core's own handler,
 * AuraEffect::HandleProcTriggerSpellAuraProc, casts the payload with its OWN base points rather
 * than with a percentage of the damage that caused the proc.
 *
 * WHY THERE IS NO TARGET LIST HERE. Three of the six payloads are beneficial and three are not,
 * and picking the wrong end of the fight is the sort of bug that reads as "the talent does
 * nothing" for weeks. SpellInfo::IsPositive() (SpellInfo.cpp) already answers it from the
 * payload's own record, so adding a hardcoded id list would be a second, drifting source of
 * truth for a fact the DBC states.
 */
class spell_fs_damage_pct_trigger : public AuraScript
{
    PrepareAuraScript(spell_fs_damage_pct_trigger);

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        // A heal proc, an absorb proc or a zeroed hit would all compute 0% of nothing and then
        // cast the payload for zero, which still burns a proc charge and still shows a combat
        // log line. Reject them before Aura::ConsumeProcCharges (SpellAuras.cpp:2327) runs.
        DamageInfo const* damageInfo = eventInfo.GetDamageInfo();
        return eventInfo.GetActor() && damageInfo && damageInfo->GetDamage() > 0;
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        // Without this the core ALSO fires EffectTriggerSpell with its own base points, so the
        // payload lands twice -- once scaled by us and once at whatever the shell record says.
        // Legal here: AuraScript::PreventDefaultAction (SpellScript.cpp:1011) accepts
        // AURA_SCRIPT_HOOK_EFFECT_PROC, and AuraEffect::HandleProc (SpellAuraEffects.cpp:1287)
        // returns before its switch when it is set.
        PreventDefaultAction();

        Unit* caster = eventInfo.GetActor();
        DamageInfo const* damageInfo = eventInfo.GetDamageInfo();
        uint32 const triggerId =
            aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].TriggerSpell;
        // CheckProc above already rejected a null DamageInfo, but this hook is one dereference
        // away from a worldserver crash and the two hooks are separate entries in separate
        // HookLists -- re-testing costs a branch and removes the dependency between them.
        if (!caster || !damageInfo || !triggerId)
            return;

        int32 const amount = CalculatePct(int32(damageInfo->GetDamage()), aurEff->GetAmount());
        if (amount <= 0)
            return;

        Unit* target = PayloadTarget(triggerId, caster, eventInfo.GetProcTarget());
        if (!target)
            return;

        caster->CastCustomSpell(triggerId, SPELLVALUE_BASE_POINT0, amount, target,
            TRIGGERED_FULL_MASK, nullptr, aurEff);
    }

    void Register() override
    {
        DoCheckProc += AuraCheckProcFn(spell_fs_damage_pct_trigger::CheckProc);
        // EFFECT_ALL and not EFFECT_0: on 560542 the proc effect is e1 (e0 is an
        // APPLY_AREA_AURA_PARTY haste aura), and on the other five it is e0. One binding covers
        // both without the generator having to tell us which index it used.
        OnEffectProc += AuraEffectProcFn(spell_fs_damage_pct_trigger::HandleProc,
            EFFECT_ALL, SPELL_AURA_PROC_TRIGGER_SPELL);
    }
};

/*
 * =============================================================================================
 * C4 -- cooldown operations (Ascension effects 165 and 195)
 * =============================================================================================
 *
 *   520830 Nether Strength   three x effect 165, bp -1001 DieSides 1 -> -1000 ms each, on
 *                            MiscValue 705129 / 800209 / 805239
 *   520816 Perpetual Fury    effect 165, -1000 ms on 555738
 *   680318 Reachwalker       effect 165, -2000 ms on 800204
 *   801902 Legionfall e1     effect 195, reset 801903
 *   301289 Infernal Summoner effect 195, reset 560284
 *
 * Both effects become SPELL_EFFECT_DUMMY (3) carrying EffectMiscValue = the target spell and a
 * value that is the delta in milliseconds. Value 0 means RESET, which is unambiguous because
 * "shift this cooldown by zero" is not something anyone authors. Note the generator must emit
 * the reset rows with DieSides 0 -- 301289's own DieSides 1 would read as a 1 ms shift, since
 * CalcValue turns (0, 1) into 1 and not into 0.
 *
 * TWO TRAPS, BOTH LOAD-BEARING.
 *
 * 1. THE RANK CHAIN IS NOT OPTIONAL. Cooldowns are keyed per spell id, so Reachwalker aimed at
 *    Felhoof Charge has to reach 800204, 803484 AND 803485, and Legionfall aimed at Annihilan
 *    Strike has to reach all seven ranks. Walking the chain is also how the SHARED CATEGORY
 *    cooldown gets cleared without touching the global category store: Player::
 *    AddSpellAndCategoryCooldowns (Player.cpp:11177-11212) writes a separate m_spellCooldowns
 *    entry for every same-family spell in the category, so the per-id entries the walk visits
 *    ARE the category cooldown. Calling Player::RemoveCategoryCooldown instead would iterate
 *    sSpellsByCategoryStore and send a clear packet for every unrelated spell that happens to
 *    share the category id.
 *
 * 2. A REDUCTION LARGER THAN THE REMAINING TIME UNDERFLOWS. Player::ModifySpellCooldown
 *    (Player.cpp:11278) is `itr->second.end += cooldown` where `end` is uint32 milliseconds and
 *    `cooldown` is a signed delta. Subtracting 2000 from 500 ms leaves 4294965796, and
 *    Player::HasSpellCooldown (Player.cpp:16709) compares `end > getMSTime()` -- so the ability
 *    a talent was supposed to hasten becomes unusable for about 49 days. Clamped below.
 */
class spell_fs_modify_cooldown : public SpellScript
{
    PrepareSpellScript(spell_fs_modify_cooldown);

    static void ClearCooldown(Player* caster, uint32 spellId)
    {
        caster->RemoveSpellCooldown(spellId, true);
    }

    void HandleCooldownOp(SpellEffIndex effIndex)
    {
        // The cooldowns being moved are the CASTER's, never the hit unit's, even when the
        // record is authored self-targeted and the two are the same object.
        Unit* casterUnit = GetCaster();
        Player* caster = casterUnit ? casterUnit->ToPlayer() : nullptr;
        if (!caster)
            return;

        uint32 const targetSpellId = uint32(GetSpellInfo()->Effects[effIndex].MiscValue);
        if (!targetSpellId)
            return;

        int32 const deltaMs = GetEffectValue();

        for (uint32 rank = sSpellMgr->GetFirstSpellInChain(targetSpellId); rank;
             rank = sSpellMgr->GetNextSpellInChain(rank))
        {
            // GetFirstSpellInChain returns its argument for an unchained spell and
            // GetNextSpellInChain returns 0 (SpellMgr.cpp:603, :619), so a single-rank ability
            // costs exactly one iteration and needs no special case.
            if (!caster->HasSpellCooldown(rank))
                continue;

            if (deltaMs == 0)
            {
                ClearCooldown(caster, rank);
                continue;
            }

            uint32 const remaining = caster->GetSpellCooldownDelay(rank);
            if (deltaMs < 0 && uint32(-deltaMs) >= remaining)
                ClearCooldown(caster, rank);         // see trap 2 above
            else
                caster->ModifySpellCooldown(rank, deltaMs);
        }
    }

    void Register() override
    {
        // EFFECT_ALL because Nether Strength 520830 carries three of these on one record, one
        // per ability it hastens, and each has its own MiscValue.
        OnEffectHitTarget += SpellEffectFn(spell_fs_modify_cooldown::HandleCooldownOp,
            EFFECT_ALL, SPELL_EFFECT_DUMMY);
    }
};

/*
 * =============================================================================================
 * C5 -- channel accumulators and the per-target cone falloff
 * =============================================================================================
 *
 * Two records, one script name. RegisterSpellAndAuraScriptPair (SpellScriptLoader.h:90) binds
 * both halves under the name of the first class, so `spell_fs_carve` is still one ScriptName
 * string for the generator to write, on both the channel record and the damage record:
 *
 *   the CHANNEL   800206 Carve (aura 23 -> 807423 every 2499 ms, aura 23 -> 803716 every 250
 *                 ms), 705121 Sunder (aura 23 -> 707508 every 300 ms), 561216 Fury of the
 *                 Illidari (aura 226 PERIODIC_DUMMY every 500 ms), 555738 Fury Unleashed for
 *                 Whirling Vengeance's on-expiry strike.
 *   the DAMAGE    803715 / 807422 Carve main- and off-hand (both weapon-percent into a cone,
 *                 ImplicitTarget 54), 712399 Sunder's explosion.
 *
 * Cells, all on the effect the hook lands on:
 *   channel  EffectMiscValue   the tick-marker spell id, whose stack count tracks the tick
 *                              number. 0 = do not track.
 *            EffectMiscValueB  a spell cast on the caster ONLY if the channel ran to full
 *                              duration -- Annihilan Rituals' Felfury refund (port-plan C5 d)
 *                              and Whirling Vengeance's 806096. 0 = nothing.
 *            Both are free on aura 23: AuraEffect::HandlePeriodicTriggerSpellAuraTick
 *            (SpellAuraEffects.cpp:6003) reads only EffectTriggerSpell.
 *   damage   EffectDamageMultiplier  per-additional-target falloff k, applied as k^index.
 *                              <= 0 or >= 1 means no falloff.
 *            EffectMiscValueB  the same tick-marker spell id, read back for the accumulator.
 *
 * THE ACCUMULATOR'S NUMBER IS ASCENSION'S, RE-EXPRESSED, AND THE CONVERSION IS THE GENERATOR'S.
 * Ascension's 803716 is SPELL_AURA_ADD_FLAT_MODIFIER MiscValue 3 (SPELLMOD_EFFECT1) at bp 24
 * DieSides 1 = +25, i.e. +25 percentage POINTS onto Carve's 40% weapon damage per tick. That
 * cannot ship as data here for the reason port-plan section 1 gives about Inner Demon:
 * Player::ApplySpellMod (Player.cpp:10070-10080) sums each modifier once and never multiplies
 * it by the aura's stack count, so a 20-stack ramp would add 25 rather than 500. This script
 * therefore does the multiply -- but against the COMPUTED damage, not against the effect's base
 * points, because by the time the hook runs the weapon swing has already been rolled. +25 onto
 * a base of 40 is +62.5% of the computed damage; the generator authors the marker's amount in
 * that second form. Same tuning, different denominator, and the arithmetic is not done here.
 */
class spell_fs_carve : public SpellScript
{
    PrepareSpellScript(spell_fs_carve);

    // CAST-SCOPED, and that is a property of the framework rather than of this declaration:
    // Spell::LoadScripts (Spell.cpp:8583) news one SpellScript per Spell object and deletes it
    // with the Spell, so these members cannot leak across casts or across players.
    std::unordered_map<ObjectGuid, uint32> _falloffIndex;
    float _falloff = 0.0f;
    uint32 _markerSpellId = 0;

    bool Load() override
    {
        // Read the two cells once per cast rather than once per target. Both live on the first
        // effect that actually does damage; a record with none simply leaves them at 0 and this
        // script becomes a no-op on it.
        SpellInfo const* info = GetSpellInfo();
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = info->Effects[i];
            if (eff.Effect != SPELL_EFFECT_SCHOOL_DAMAGE
                && eff.Effect != SPELL_EFFECT_WEAPON_DAMAGE
                && eff.Effect != SPELL_EFFECT_WEAPON_DAMAGE_NOSCHOOL
                && eff.Effect != SPELL_EFFECT_WEAPON_PERCENT_DAMAGE)
                continue;

            _falloff = eff.DamageMultiplier;
            _markerSpellId = uint32(eff.MiscValueB);
            break;
        }

        return true;
    }

    /*
     * HOW THIS AVOIDS BOTH FAILURES port-plan section 7.5 names.
     *
     * ORDER DEPENDENCE. Spell::SearchAreaTargets fills the list in grid order, which is a
     * function of where the objects happen to sit in the cell tree -- two identical casts on
     * the same five mobs can hand the same mob a different position, so a falloff keyed on list
     * position would silently deal different damage each time and would never reproduce in a
     * test. std::list::sort is stable, which PRESERVES that arbitrary order for ties rather
     * than fixing it, so the comparator has to be a TOTAL order: squared distance first, then
     * ObjectGuid, which is unique and stable for the life of the object. Sorting here also
     * means the closest target is index 0, which is the only reading of "falloff" a player
     * would accept.
     *
     * O(n^2). Two separate ways in, both closed. (a) The obvious one is looking a target up in
     * the ordered list from the per-target hook, which is a linear scan per target; the map
     * makes it a hash lookup, so the whole cast is O(n log n) to sort plus O(n) to apply.
     * (b) The subtle one is that this hook runs once PER AREA EFFECT -- Carve's 803715 has two
     * of them -- and re-sorting plus re-indexing every time would multiply the work by the
     * effect count and, worse, would renumber targets that the first pass had already placed.
     * emplace() only inserts when the key is absent and takes the running size as the value, so
     * the second and third passes append genuinely new targets at the end and leave every index
     * already assigned exactly where it was.
     */
    void OrderConeTargets(std::list<WorldObject*>& targets)
    {
        Unit const* caster = GetCaster();
        if (!caster || targets.empty())
            return;

        targets.sort([caster](WorldObject const* lhs, WorldObject const* rhs)
        {
            float const lhsDist = caster->GetExactDist2dSq(lhs);
            float const rhsDist = caster->GetExactDist2dSq(rhs);
            if (lhsDist != rhsDist)
                return lhsDist < rhsDist;

            return lhs->GetGUID() < rhs->GetGUID();
        });

        for (WorldObject const* target : targets)
            _falloffIndex.emplace(target->GetGUID(), uint32(_falloffIndex.size()));
    }

    /*
     * OnHit AND NOT OnEffectHitTarget, which is a correction to the plan's own wording and the
     * one thing in this bucket that would fail silently if copied verbatim.
     *
     * Spell::HandleEffects (Spell.cpp:5645) calls the effect script hooks BEFORE dispatching to
     * the effect handler at :5649, so inside OnEffectHitTarget the weapon swing has not been
     * rolled yet and GetHitDamage() is whatever earlier effects happened to accumulate --
     * usually zero. CallScriptOnHitHandlers (Spell.cpp:2754) runs after every effect on the
     * target and before Unit::DealDamage, so GetHitDamage() there is the real, whole number.
     * OnHit is also index-free, so one binding covers a record whose damage is spread over two
     * effects (Carve's 803715 is weapon-percent on e0 plus flat weapon damage on e1) without
     * scaling it twice.
     */
    void ScaleHitDamage()
    {
        Unit* target = GetHitUnit();
        int32 const original = GetHitDamage();
        if (!target || original <= 0)
            return;

        int32 damage = original;

        // The accumulator, first: the marker's own amount is the per-tick percentage and its
        // stack count is the number of ticks the channel actually reached.
        if (_markerSpellId)
        {
            if (Unit* caster = GetCaster())
                if (AuraEffect const* marker = caster->GetAuraEffect(_markerSpellId, EFFECT_0,
                        caster->GetGUID()))
                    AddPct(damage,
                        marker->GetAmount() * int32(marker->GetBase()->GetStackAmount()));
        }

        // Then the falloff. A target that never went through the area selection (a single
        // explicit target, or a second effect with its own target type) is absent from the map
        // and correctly takes full damage.
        if (_falloff > 0.0f && _falloff < 1.0f)
        {
            auto const itr = _falloffIndex.find(target->GetGUID());
            if (itr != _falloffIndex.end() && itr->second > 0)
                damage = int32(float(damage) * std::pow(_falloff, float(itr->second)));
        }

        if (damage == original)
            return;

        // Never round a nearby target down to a zero-damage hit: 0 reads as a miss in the
        // combat log and suppresses the on-damage procs the rest of the kit is built on.
        SetHitDamage(std::max(1, damage));
    }

    void Register() override
    {
        /*
         * The area hooks are registered FROM THE RECORD rather than from a literal target type,
         * because SpellScript::TargetHook::CheckEffect (SpellScript.cpp:242) matches
         * TargetA/TargetB against the exact `targetType` this hook was built with -- and the
         * records sharing this script do not agree on one. Carve's 803715 is ImplicitTarget 54
         * (a cone), Sunder's 712399 is 16 (a destination area). Registering a fixed pair of
         * literals would either miss one of them or log a boot-time mismatch for the other; the
         * loop registers exactly the hooks the record can actually fire.
         */
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(m_scriptSpellId))
        {
            for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
            {
                SpellEffectInfo const& eff = info->Effects[i];
                if (!eff.Effect)
                    continue;

                if (eff.TargetA.IsArea())
                    OnObjectAreaTargetSelect += SpellObjectAreaTargetSelectFn(
                        spell_fs_carve::OrderConeTargets, i, uint16(eff.TargetA.GetTarget()));

                if (eff.TargetB.IsArea())
                    OnObjectAreaTargetSelect += SpellObjectAreaTargetSelectFn(
                        spell_fs_carve::OrderConeTargets, i, uint16(eff.TargetB.GetTarget()));
            }
        }

        OnHit += SpellHitFn(spell_fs_carve::ScaleHitDamage);
    }
};

/*
 * The channel half of C5. Registered under the same name as the class above.
 *
 * It holds no tick counter of its own: AuraEffect::Update (SpellAuraEffects.cpp:939) increments
 * m_tickNumber before calling PeriodicTick, so aurEff->GetTickNumber() is already 1 on the
 * first tick and is authoritative in a way a member int would not be if a tick were ever
 * skipped. The marker aura still carries the count, because it is the only thing the damage
 * record -- a different Spell object, cast from the data chain and not by us -- can read.
 */
class spell_fs_carve_channel : public AuraScript
{
    PrepareAuraScript(spell_fs_carve_channel);

    // BOTH hooks below are bound EFFECT_ALL, so on Carve's 800206 -- two periodic effects, one
    // at 2499 ms and one at 250 ms -- every handler runs twice per removal. The marker and the
    // tick bump are naturally idempotent (only the effect carrying the cell acts, and removing
    // an absent aura is a no-op); firing the completion spell twice is not, so it is latched.
    // Scoped to the Aura, because that is what an AuraScript instance lives and dies with.
    bool _completionFired = false;

    void HandleTick(AuraEffect const* aurEff)
    {
        Unit* caster = GetCaster();
        if (!caster)
            return;

        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];

        /*
         * SPELL_AURA_PERIODIC_DUMMY does nothing on this core unless the spell id is one of the
         * hardcoded cases in AuraEffect::HandlePeriodicDummyAuraTick, which Ascension's ids
         * obviously are not -- so for 561216 Fury of the Illidari ("6 assaults, +1 Felfury
         * each") the script has to fire the payload itself. Aura 23 needs no help: its own
         * handler runs immediately after this hook returns (SpellAuraEffects.cpp:1131 then the
         * switch at :1151).
         */
        if (aurEff->GetAuraType() == SPELL_AURA_PERIODIC_DUMMY && eff.TriggerSpell)
            caster->CastSpell(caster, eff.TriggerSpell, true);

        uint32 const markerId = uint32(eff.MiscValue);
        if (!markerId)
            return;

        if (Aura* marker = caster->GetAura(markerId, caster->GetGUID()))
        {
            // ModStackAmount and NOT SetStackAmount: only the former caps against the record's
            // CumulativeAura column (SpellAuras.cpp:968-980), which is where the generator puts
            // the ceiling on how long a channel is allowed to keep ramping.
            //
            // Also NOT CastCustomSpell(..., SPELLVALUE_AURA_STACK, n, ...): on an aura that
            // already exists, Spell::EffectApplyAura (Spell.cpp:3149-3155) treats that value as
            // ModStackAmount rather than as an assignment, so "set the stack to 4" would ADD
            // four stacks to the three already there.
            marker->ModStackAmount(1);
            marker->RefreshDuration();
        }
        else
            caster->CastSpell(caster, markerId, true);
    }

    void HandleChannelEnd(AuraEffect const* aurEff, AuraEffectHandleModes /*mode*/)
    {
        // SPELL_AURA_ANY on the binding means this also fires for the non-periodic riders a
        // channel record may carry (Fury Unleashed 555738 has aura 31 and aura 147 alongside
        // its aura 23), and those effects' MiscValue columns mean something else entirely.
        AuraType const type = aurEff->GetAuraType();
        if (type != SPELL_AURA_PERIODIC_TRIGGER_SPELL && type != SPELL_AURA_PERIODIC_DUMMY)
            return;

        Unit* caster = GetCaster();
        if (!caster)
            return;

        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];

        if (uint32 const markerId = uint32(eff.MiscValue))
            caster->RemoveAurasDueToSpell(markerId, caster->GetGUID());

        /*
         * "On a FULL channel", not "on any removal" -- port-plan C5 (d) is explicit that
         * Annihilan Rituals refunds Felfury for finishing the channel and not for starting one
         * and moving. AuraApplication::GetRemoveMode (SpellAuras.h:73) is the only thing that
         * separates the two: a channel that ran out its duration is AURA_REMOVE_BY_EXPIRE,
         * while an interrupt, a cancel, a death or a zone change is not.
         */
        AuraApplication const* application = GetTargetApplication();
        if (_completionFired || !application
            || application->GetRemoveMode() != AURA_REMOVE_BY_EXPIRE)
            return;

        if (uint32 const completionId = uint32(eff.MiscValueB))
        {
            _completionFired = true;
            caster->CastSpell(caster, completionId, true);
        }
    }

    void Register() override
    {
        // Registered from the record for the same reason as the cone hooks above: this name is
        // also written onto damage records with no aura effect at all, and an unconditional
        // periodic hook would log a mismatch for every one of them at boot
        // (ObjectMgr.cpp:6399 -> SpellScript.cpp:692).
        SpellInfo const* info = sSpellMgr->GetSpellInfo(m_scriptSpellId);
        if (!info)
            return;

        bool hasPeriodic = false;
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS && !hasPeriodic; ++i)
            hasPeriodic = info->Effects[i].ApplyAuraName == SPELL_AURA_PERIODIC_TRIGGER_SPELL
                       || info->Effects[i].ApplyAuraName == SPELL_AURA_PERIODIC_DUMMY;

        if (!hasPeriodic)
            return;

        OnEffectPeriodic += AuraEffectPeriodicFn(spell_fs_carve_channel::HandleTick,
            EFFECT_ALL, SPELL_AURA_ANY);
        AfterEffectRemove += AuraEffectRemoveFn(spell_fs_carve_channel::HandleChannelEnd,
            EFFECT_ALL, SPELL_AURA_ANY, AURA_EFFECT_HANDLE_REAL);
    }
};

/*
 * =============================================================================================
 * C6 -- spellmods computed from a stat at runtime
 * =============================================================================================
 *
 *   92089  Burning Commander -> 500531  two aura-22 MOD_RESISTANCE effects, both bp -1
 *   803478 Pure Hatred       -> 801894  aura 107 MiscValue 3, bp 0, mask 0x04000000
 *   574146 Felblade          -> 804105  three aura-107s, all bp 0
 *   574145 Felcaked Blades   -> 574150  aura 107 MiscValue 3, bp 0, mask 0x00100000
 *   300489 Archimonde's Wrath          aura 107 MiscValue 14 (SPELLMOD_CRITICAL_CHANCE), bp -1
 *
 * Every one of those amounts is zero in the dump, because on Ascension the number is supplied
 * by engine code that reads a stat. No 3.3.5a cell can: EffectRealPointsPerLevel scales by
 * level and EffectBonusMultiplier by spell power or attack power, and neither is a stat.
 *
 * The generator therefore writes the COEFFICIENT into EffectBasePoints, in hundredths of a
 * modifier point per unit of source, and names the source in EffectMiscValueB. "+$s2% crit for
 * every 10 points of Energy" (300489) is coefficient 10; "one point of armour per point of
 * dodge percent" is 100. No number is invented in this file -- the amount is entirely
 * (source x cell / 100).
 *
 * THE STALENESS IS REAL AND IT IS NAMED. port-plan section 4 C6 asks for Ascension's 500-9999 ms
 * recompute poll to be replaced with a stat-change hook. There is no such hook on this fork:
 * PlayerScript.h has nothing between OnPlayerBeforeUpdateAttackPowerAndDamage (:478) and
 * OnPlayerApplyItemModsBefore (:567) that fires on Player::UpdateStats or Player::UpdateRating,
 * and UnitScript.h has none either. So the recompute stays a poll, and it runs at whatever
 * period the generator authors on the carrier record. Only the WINDOW shrinks, not the shape:
 * the first value is exact (see the no-apply-hook note in Register below) and every later one
 * is at most one period stale. Replacing the poll properly is a core patch, and it is the only
 * part of C6 that this file cannot do.
 */
class spell_fs_stat_spellmod : public AuraScript
{
    PrepareAuraScript(spell_fs_stat_spellmod);

    void CalcAmount(AuraEffect const* aurEff, int32& amount, bool& canBeRecalculated)
    {
        int32 const source = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].MiscValueB;
        if (source == FS_STAT_NONE)
            return;                     // not one of ours; leave the DBC value alone

        Unit const* owner = GetUnitOwner();
        if (!owner)
            return;

        // `amount` arrives as the DBC value, which for these records IS the coefficient. Read
        // it before overwriting it.
        int32 const coefficient = amount;
        amount = int32(ReadStatSource(owner, source) * float(coefficient) / 100.0f);

        // Without this AuraEffect::RecalculateAmount (SpellAuraEffects.h:76) returns early
        // forever and the poll below is dead code.
        canBeRecalculated = true;
    }

    void Recompute()
    {
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
            if (AuraEffect* effect = GetEffect(i))
                effect->RecalculateAmount();
    }

    void HandleTick(AuraEffect const* /*aurEff*/)
    {
        Recompute();
    }

    void Register() override
    {
        // SPELL_AURA_ANY, because the same computation feeds three different aura types:
        // 107/108 spellmods on 801894/804105/574150/300489 and plain aura 22 MOD_RESISTANCE on
        // Burning Commander's 500531. What makes an effect ours is EffectMiscValueB, not the
        // aura id, and CalcAmount returns untouched when that cell is 0.
        DoEffectCalcAmount += AuraEffectCalcAmountFn(spell_fs_stat_spellmod::CalcAmount,
            EFFECT_ALL, SPELL_AURA_ANY);

        // THERE IS DELIBERATELY NO APPLY HOOK. The first computation is already free and
        // already correct: UnitAura's constructor (SpellAuras.cpp:2781-2785) calls LoadScripts
        // BEFORE _InitEffects, and _InitEffects constructs each AuraEffect through
        // CalculateAmount -> CallScriptEffectCalcAmountHandlers (SpellAuraEffects.cpp:578). So
        // CalcAmount above has already run by the time the talent is applied, and an
        // AfterEffectApply that called Recompute would only add a re-entrant ChangeAmount in
        // the middle of AuraEffect::HandleEffect for no change in value.
        //
        // Only where the record actually asks for a poll -- see the staleness note above, and
        // the same boot-noise argument as spell_fs_carve_channel::Register. The generator's
        // ticker of choice is a SPELL_AURA_PERIODIC_DUMMY effect with an Amplitude: its own
        // handler, AuraEffect::HandlePeriodicDummyAuraTick, is a hardcoded id switch that no
        // Felsworn id is in, so the tick costs nothing beyond this hook.
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(m_scriptSpellId))
            for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
                if (info->Effects[i].Amplitude && info->Effects[i].ApplyAuraName)
                {
                    OnEffectPeriodic += AuraEffectPeriodicFn(spell_fs_stat_spellmod::HandleTick,
                        EFFECT_ALL, SPELL_AURA_ANY);
                    break;
                }
    }
};

/*
 * =============================================================================================
 * C8 -- "every Nth"
 * =============================================================================================
 *
 *   704374 Felwracked           every 3rd Twin Slice or Fel Fireball
 *   560840 Infernal Ruin        every 3rd Ruin or Felwrath
 *   801235 Sculptor of Doom     3 direct critical strikes
 *   706268 Fury of Archimonde   after generating 10 Felfury
 *   520257 Demonic Embrace      Inner Demon cast at >= 6 Felfury
 *   800222 The Demon Within     auto-enter at 6
 *
 * The count lives in a hidden aura's stack count and not in a member of this object, which is
 * the whole reason the bucket needs a marker record at all: an AuraScript instance dies with
 * its Aura, so a member would reset on every relog, on every spec change and on every dispel,
 * and "my third Twin Slice did not proc" is not a bug anyone would report cleanly.
 *
 * Cells on the aura 42 effect:
 *   EffectMiscValue    N
 *   EffectMiscValueB   the counter marker spell id -- CumulativeAura >= N - 1
 *   EffectTriggerSpell the payload, fired only on the Nth
 *
 * WHICH events count is NOT decided here. It is the record's own ProcTypeMask plus, where a
 * crit-only or chance gate is needed, a spell_proc row -- port-plan section 4 C0. Sculptor of
 * Doom counting only critical strikes is HitMask PROC_HIT_CRITICAL in that row, not an `if` in
 * this function.
 */
class spell_fs_counter : public AuraScript
{
    PrepareAuraScript(spell_fs_counter);

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        return eventInfo.GetActor() != nullptr;
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        // The payload must fire on the Nth event only, so the core's own
        // HandleProcTriggerSpellAuraProc -- which would fire it on every one -- is suppressed
        // unconditionally and re-issued below when the count comes round.
        PreventDefaultAction();

        Unit* caster = eventInfo.GetActor();
        if (!caster)
            return;

        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];
        uint32 const payloadId = eff.TriggerSpell;
        uint32 const counterId = uint32(eff.MiscValueB);
        int32 const period = eff.MiscValue;

        Unit* target = payloadId ? PayloadTarget(payloadId, caster, eventInfo.GetProcTarget())
                                 : nullptr;
        if (!target)
            return;

        // N <= 1 is "every time", and it is also what an unwritten MiscValue looks like. Both
        // read the same way and neither needs the marker.
        if (period <= 1 || !counterId)
        {
            caster->CastSpell(target, payloadId, true, nullptr, aurEff);
            return;
        }

        Aura* counter = caster->GetAura(counterId, caster->GetGUID());
        uint32 const count = (counter ? counter->GetStackAmount() : 0u) + 1u;

        if (int32(count) < period)
        {
            if (counter)
            {
                // See the CumulativeAura and SPELLVALUE_AURA_STACK notes on
                // spell_fs_carve_channel::HandleTick -- the same two traps apply verbatim.
                counter->ModStackAmount(1);
                counter->RefreshDuration();
            }
            else
                caster->CastSpell(caster, counterId, true);

            return;
        }

        // The Nth. Clear the counter BEFORE the payload: the payload may itself proc something
        // that re-enters this function, and a marker still standing at N would fire it twice.
        caster->RemoveAurasDueToSpell(counterId, caster->GetGUID());
        caster->CastSpell(target, payloadId, true, nullptr, aurEff);
    }

    void Register() override
    {
        DoCheckProc += AuraCheckProcFn(spell_fs_counter::CheckProc);
        OnEffectProc += AuraEffectProcFn(spell_fs_counter::HandleProc,
            EFFECT_ALL, SPELL_AURA_PROC_TRIGGER_SPELL);
    }
};

/*
 * =============================================================================================
 * C7 -- conditions on the victim
 * =============================================================================================
 *
 * A UnitScript and not a SpellScript, because the question is asked about the DEFENDER at a
 * moment when the attacker's spell is not the thing being dispatched. It is registered in code
 * and needs no spell_script_names row; it is in this file anyway because it is the other half
 * of the same five talents.
 *
 *   92087  Dancing Blades       20000/23  melee-ability crit -> off-hand cleave 800598
 *   705127 You Cheat, Gul'dan!  20001/23  +50% crit DAMAGE vs a victim above 75% health
 *   802180 Fel Cannon           20000/28  +15% crit CHANCE on Fel Fireball and Ruin vs > 75%
 *   520833 Doomsayer e1         20007/23  +25% Sargeron Smite damage vs > 75%
 *   804610 Reckless Assault     20007/26  +15% damage vs slowed enemies
 *
 * WHAT THE THREE HOOKS ACTUALLY REACH, stated plainly because two of the five are outside them:
 *
 *   ModifySpellDamageTaken     Unit.cpp:1507, inside CalculateSpellDamageTaken and before
 *                              armour. Carries a SpellInfo, so a class-mask filter works. This
 *                              is where Doomsayer and Reckless Assault land -- every Felsworn
 *                              "weapon damage" strike is a spell, not a white swing.
 *   ModifyMeleeDamage          Unit.cpp:1763. White swings only, and there is NO SpellInfo, so
 *                              a masked effect cannot be matched against anything and is
 *                              skipped rather than guessed at.
 *   OnBeforeRollMeleeOutcome-  Unit.cpp:2982. crit_chance here is in HUNDREDTHS of a percent:
 *   Against                    Unit::RollMeleeOutcomeAgainst is entered with
 *                              int32(crit_chance * 100) at :2966 and rolls urand(0, 10000) at
 *                              :2987. +15% is +1500, and getting that wrong by a factor of a
 *                              hundred is a talent that either does nothing or crits always.
 *
 * NOT REACHABLE FROM HERE, and neither is a matter of effort:
 *   * Fel Cannon's SPELL crit chance goes through Unit::isSpellCrit / SpellDoneCritChance, and
 *     there is no UnitScript or PlayerScript hook anywhere on that path (checked: PlayerScript.h
 *     has no crit virtual at all).
 *   * You Cheat, Gul'dan!'s crit DAMAGE goes through Unit::SpellCriticalDamageBonus, and
 *     ModifySpellDamageTaken cannot tell a crit from a normal hit -- the flag is not in its
 *     signature.
 *   * Annihilan Strike's guaranteed crit is a THIRD path again: SPELLVALUE_FORCED_CRIT_RESULT
 *     (SpellDefines.h:120), set by whoever casts it. Its >75% gate is the DATA half --
 *     TargetAuraState 23, port-plan 2.2 -- so it needs nothing from here. If a fourth caller
 *     ever does, VictimConditionHolds moves out of this file's anonymous namespace into
 *     demon_hunter.h; it is a free function rather than a member for exactly that reason, but
 *     it is not reachable from another translation unit as it stands.
 *
 * COST. Every melee swing and every spell hit on the realm enters these three functions --
 * ScriptMgr only short-circuits when the hook list is empty and ours is not. IsFelsworn is
 * therefore first and is one field read plus two compares, which rejects every attacker on the
 * realm before the aura list is even touched. The same argument, and the same shape, as
 * demon_hunter_playerscript::OnPlayerIsClass (demon_hunter.cpp:462-471).
 */
class felsworn_victim_conditions_unitscript : public UnitScript
{
public:
    // Hooks are opted into EXPLICITLY. UnitScript's constructor treats an empty enabledHooks
    // vector as "all hooks" (UnitScript.cpp:148-150), which would put this script on all
    // twenty-one dispatch lists -- including OnUnitUpdate, once per unit per tick -- for the
    // sake of three.
    felsworn_victim_conditions_unitscript() : UnitScript("felsworn_victim_conditions_unitscript",
        true,
    {
        UNITHOOK_MODIFY_MELEE_DAMAGE,
        UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN,
        UNITHOOK_ON_BEFORE_ROLL_MELEE_OUTCOME_AGAINST
    }) { }

    void ModifySpellDamageTaken(Unit* target, Unit* attacker, int32& damage,
        SpellInfo const* spellInfo) override
    {
        if (damage <= 0 || !target || !IsFelsworn(attacker) || !spellInfo)
            return;

        damage += ConditionalDamageBonus(attacker, target, damage, spellInfo);
    }

    void ModifyMeleeDamage(Unit* target, Unit* attacker, uint32& damage) override
    {
        if (!damage || !target || !IsFelsworn(attacker))
            return;

        // int32 arithmetic and a clamp, not AddPct on the uint32: CalculatePct multiplies by a
        // float and converts back, so a negative modifier on a uint32 would wrap to roughly
        // four billion rather than to zero.
        int32 const bonus = ConditionalDamageBonus(attacker, target, int32(damage), nullptr);
        damage = uint32(std::max<int32>(0, int32(damage) + bonus));
    }

    void OnBeforeRollMeleeOutcomeAgainst(Unit const* attacker, Unit const* victim,
        WeaponAttackType /*attType*/, int32& /*attackerMaxSkillValueForLevel*/,
        int32& /*victimMaxSkillValueForLevel*/, int32& /*attackerWeaponSkill*/,
        int32& /*victimDefenseSkill*/, int32& crit_chance, int32& /*miss_chance*/,
        int32& /*dodge_chance*/, int32& /*parry_chance*/, int32& /*block_chance*/) override
    {
        if (!victim || !IsFelsworn(attacker))
            return;

        for (AuraEffect const* aurEff :
             attacker->GetAuraEffectsByType(SPELL_AURA_OVERRIDE_CLASS_SCRIPTS))
        {
            if (!Applies(aurEff, victim, nullptr, FS_CS_CRIT_CHANCE))
                continue;

            // See the hundredths-of-a-percent note in the block comment above.
            crit_chance += aurEff->GetAmount() * 100;
        }
    }

private:
    /*
     * True when this aura-112 effect is one of ours, does the operation asked for, and its
     * victim predicate holds.
     *
     * `spellInfo` nullptr means "a white melee swing". A modifier that names abilities through
     * its SpellClassMask cannot be matched against a swing that has no spell, so it is skipped
     * -- letting it through would quietly hand Reckless Assault's "+15% to Azzinoth's Assault,
     * Annihilan Strike and Twin Slice" to auto-attacks as well.
     *
     * The mask test itself is AuraEffect::IsAffectedOnSpell (SpellAuraEffects.h:94), which is
     * SpellInfo::IsAffected (SpellInfo.cpp:1325) on the aura's OWN family and the effect's own
     * SpellClassMask -- so the filter is by family bit, as port-plan C7 requires, and never by
     * a hardcoded id list that the generator would have to keep in step.
     */
    static bool Applies(AuraEffect const* aurEff, Unit const* victim, SpellInfo const* spellInfo,
        int32 op)
    {
        if (aurEff->GetMiscValue() != op || !aurEff->GetAmount())
            return false;

        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];
        if (spellInfo)
        {
            if (!aurEff->IsAffectedOnSpell(spellInfo))
                return false;
        }
        else if (eff.SpellClassMask)
            return false;

        return VictimConditionHolds(aurEff->GetMiscValueB(), victim);
    }

    // Returns the ADDITION, not the new total, so both callers keep their own overflow rules.
    // Several effects may match at once and they add, which is how the equivalent spellmods
    // would stack if this were expressible as data.
    static int32 ConditionalDamageBonus(Unit const* attacker, Unit const* victim, int32 damage,
        SpellInfo const* spellInfo)
    {
        int32 bonus = 0;
        for (AuraEffect const* aurEff :
             attacker->GetAuraEffectsByType(SPELL_AURA_OVERRIDE_CLASS_SCRIPTS))
            if (Applies(aurEff, victim, spellInfo, FS_CS_DAMAGE_DONE))
                bonus += CalculatePct(damage, aurEff->GetAmount());

        return bonus;
    }
};

/*
 * Registration.
 *
 * Called from AddSC_demon_hunter (demon_hunter.cpp:618) alongside the three code-registered
 * scripts, and declared in demon_hunter.h next to it. Kept as its own function rather than
 * folded into that one so that the file that owns C1/C2 can add a third the same way.
 *
 * RegisterSpellScript hands the DB the STRINGIFIED CLASS NAME (SpellScriptLoader.h:88), so the
 * five names below are literally what tools/dh_talents.py SCRIPT_NAMES must contain and what
 * ends up in spell_script_names.ScriptName. Renaming a class here silently unbinds every row
 * that names it -- ObjectMgr::LoadSpellScriptNames logs nothing for a ScriptName with no
 * script, it just resolves to script id 0 and the talent stops working.
 *
 * Carve is the one pair: RegisterSpellAndAuraScriptPair registers under the name of the FIRST
 * class only (SpellScriptLoader.h:90), so both halves share the single name `spell_fs_carve`.
 */
void AddSC_felsworn_spells()
{
    RegisterSpellScript(spell_fs_damage_pct_trigger);
    RegisterSpellScript(spell_fs_modify_cooldown);
    RegisterSpellAndAuraScriptPair(spell_fs_carve, spell_fs_carve_channel);
    RegisterSpellScript(spell_fs_stat_spellmod);
    RegisterSpellScript(spell_fs_counter);

    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process, the same convention as demon_hunter.cpp:622-624.
    new felsworn_victim_conditions_unitscript();
}
