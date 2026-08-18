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
 * demon_hunter.h:168-173 states the ownership split and it is worth restating from the other
 * side. AllSpellScript, PlayerScript, WorldScript and UnitScript are registered IN CODE and
 * need no row -- AllSpellScript::IsDatabaseBound() is false (AllSpellScript.h:52). SpellScript
 * and AuraScript are the exception: ObjectMgr::LoadSpellScriptNames (ObjectMgr.cpp:6339, the
 * `SELECT spell_id, ScriptName FROM spell_script_names` at :6345) is the ONLY way one of these
 * ever attaches to a spell. So every class below is inert until tools/dhspells.py emits its
 * rows, which is also the switch: a realm that has not applied the generated SQL simply never
 * loads them. That is why nothing in this file reads `DemonHunter.Enable` -- a config lookup on
 * Unit::CalculateSpellDamageTaken's path would cost every spell hit on the realm a string hash
 * to answer a question the absent rows already answer.
 *
 * BOOT-TIME VALIDATION, AND THE ONE RULE THAT DECIDES WHICH KIND EACH CHECK IS
 * ---------------------------------------------------------------------------
 * ObjectMgr::ValidateSpellScripts (ObjectMgr.cpp:6399) instantiates each script once at boot.
 * It calls _Init (:6431/:6439), then _Register (:6432/:6440), then _Validate (:6433/:6441), and
 * ERASES the spell_script_names row (:6447) if either _Validate returns false. _Validate is
 * reached from nowhere else -- neither Spell::LoadScripts (Spell.cpp:8578) nor Aura::LoadScripts
 * (SpellAuras.cpp:2353) call it -- so a Validate() override costs nothing at run time and is the
 * only place in this file where a generator mistake can be made loud.
 *
 * Two failure shapes, and they are not treated the same:
 *
 *   the row names the WRONG SCRIPT for this record -- no cell this bucket reads is present at
 *   all. Validate() LOG_ERRORs the missing cell by name and returns FALSE, so _SpellScript::
 *   _Validate (SpellScript.cpp:24-30) logs a second line and the row is erased. Nothing is lost:
 *   the script could not have done anything for that record anyway.
 *
 *   one OPTIONAL cell is unusable -- an id that resolves to no SpellInfo, say. Validate()
 *   LOG_ERRORs and returns TRUE, and the run-time path skips that one cell. Erasing here would
 *   take the rest of the record's behaviour down with a cell it does not depend on.
 *
 * Separately, ValidateSpellScripts logs `... did not match dbc effect data` for any hook whose
 * effect index/type is absent from the record (SpellScript.cpp:694 for OnEffectPeriodic, :758
 * for OnEffectProc, and so on) WITHOUT erasing anything. Every hook below is therefore either
 * bound with EFFECT_ALL + SPELL_*_ANY, or registered conditionally from the record itself in
 * Register(), so a shared script bound to thirty differently-shaped records logs nothing.
 * `m_scriptSpellId` is set by _Init() before _Register() in both the boot path (:6431-6432) and
 * the runtime path (SpellScriptLoader.cpp:37 for a SpellScript, :58 for an AuraScript, then
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
 *   C7      aura 112 OVERRIDE_CLASS_SCRIPTS  EffectMiscValue (what), EffectMiscValueB (when),
 *                                            EffectSpellClassMaskA (which abilities -- MANDATORY)
 *   C8      aura 42 / aura 4                 EffectMiscValue (N), EffectMiscValueB (counter)
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
     * It means nothing to the core. SPELL_AURA_OVERRIDE_CLASS_SCRIPTS is wired to
     * &AuraEffect::HandleNoImmediateEffect in the handler table (SpellAuraEffects.cpp:177), so
     * applying or removing one does nothing whatsoever; the single place the core reads its
     * MiscValue is AuraEffect::CalculateAmount (SpellAuraEffects.cpp:509-520), a breakable-CC
     * damage cap that matches the literal 7801 and ignores every other value. Both cells are
     * therefore ours to define.
     *
     * IT IS NOT INERT IN THE PROC SYSTEM, and that is a constraint on the generator rather than
     * on this file. SpellMgr.cpp:1975 sets isTriggerAura[SPELL_AURA_OVERRIDE_CLASS_SCRIPTS] and
     * :1986 sets isAlwaysTriggeredAura[...], so a C7 record authored with non-zero ProcFlags
     * gets an auto-generated proc entry (SpellMgr.cpp:2165-2245) and is walked into
     * AuraEffect::HandleProc (SpellAuraEffects.cpp:1285) on every matching event. HandleProc's
     * switch has no case for aura 112 so nothing fires, but Aura::TriggerProcOnEvent calls
     * ConsumeProcCharges afterwards regardless (SpellAuras.cpp:2327). Author C7 records with
     * ProcFlags 0 and ProcCharges 0 -- which is what four of Ascension's five already are.
     *
     * ASCENSION'S CODES. All eight aura-112 effects in family 20, read out of the dump, with the
     * amount each cell computes (every one is DieSides 1, so SpellEffectInfo::CalcValue
     * (SpellInfo.cpp:409-445) reads it as BasePoints + 1):
     *
     *   misc   miscB  record                          amount  what the record's own tooltip says
     *   -----  -----  ------------------------------  ------  --------------------------------
     *   20000     23  92087  Dancing Blades              100  an on-crit TRIGGER. No crit chance
     *                                                         and no health threshold anywhere
     *                                                         in the text.
     *   20000     23  705127 You Cheat, Gul'dan! e0        0  says nothing; e1 carries the talent
     *   20000     28  802180 Fel Cannon                   15  +15% crit CHANCE on two SPELLS
     *   20001     23  705127 You Cheat, Gul'dan! e1       50  +50% crit DAMAGE
     *   20007     23  520833 Doomsayer e1                 25  +25% damage to ONE ability
     *   20007     26  804610 Reckless Assault             15  +15% damage to THREE abilities
     *   20008      4  520249 Cruelty e1                    6  +6% crit chance vs Demons
     *   20008      8  704607 Elemental Bane e0            15  +15% crit chance vs Elementals
     *
     * ONLY 20007 IS UNAMBIGUOUS, so 20007 is the only code this file reads. The other three are
     * rejected individually, and each rejection is a fact about this core, not a preference:
     *
     *   20000 IS THREE DIFFERENT THINGS. 802180 means crit chance; 705127 e0 means nothing at
     *   all; 92087 means an on-crit trigger, which is not a modifier of any kind. 92087's own
     *   implementation record proves it -- 705132 Dancing Blades (Spec Passive) carries the same
     *   tooltip word for word on a plain aura 42 PROC_TRIGGER_SPELL with EffectTriggerSpell
     *   800598, the off-hand cleave. Reading 20000 as "crit chance, in percent" therefore hands
     *   92087's amount of 100 to Unit::RollMeleeOutcomeAgainst, which is entered with
     *   int32(crit_chance * 100) at Unit.cpp:2966 and rolls urand(0, 10000) at :2987: a
     *   GUARANTEED critical on every white swing. There is no cell that distinguishes the three
     *   meanings, so the generator must translate rather than copy, and 92087 must be authored
     *   as 705132's shape (aura 42 -> 800598, crit-only via a spell_proc HitMask row).
     *
     *   20001 AND 20008 ARE NOT REACHABLE FROM ANY HOOK, and they do not fail the same way.
     *   Crit DAMAGE is applied inside Unit::SpellCriticalBonus (Unit.cpp:9422-9425) and
     *   Unit::CalculateMeleeDamage (Unit.cpp:1552-1555); a spell's crit CHANCE comes out of
     *   Unit::SpellDoneCritChance (Unit.cpp:9105). Neither path has a UnitScript or PlayerScript
     *   hook anywhere on it.
     *     20001, the crit-damage half of 705127, has a native expression for its unconditional
     *     form: SPELL_AURA_MOD_CRIT_DAMAGE_BONUS (163) with a school MiscMask, which is exactly
     *     what 704607's own e1 already carries. Only the ">75% health" gate is lost, and that is
     *     a tuning decision for the generator, not a mechanism this file can supply.
     *     20008 has NO expression here at all, and the near-miss is worth naming so nobody
     *     spends an evening on it: SPELL_AURA_MOD_CRIT_PERCENT_VERSUS (169) reads like
     *     "crit chance versus creature type" and is not -- on this fork it is a crit DAMAGE
     *     multiplier (SpellAuraEffects.cpp:234's own comment says "implemented in ...
     *     Unit::SpellCriticalBonus", and Unit.cpp:9425 and :1841 are the two places that use
     *     it). 704607 Elemental Bane is in the ported closure per port-plan section 4's tab-87
     *     census, so its crit-chance-vs-Elementals half belongs in C10 with the aura-317
     *     records: dropped, not deferred.
     *
     * WHICH LEAVES ONE HOOK. See the C7 block at the bottom of the file for why
     * ModifySpellDamageTaken is the only one this script registers.
     */
    enum FelswornClassScriptOp : int32
    {
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
     * Doomsayer's "+25% Sargeron Smite above 75%" and Reckless Assault's "+15% vs slowed" cannot
     * drift apart, and so that a fourth condition is written down once.
     *
     * Note the asymmetry with the DATA half: TargetAuraState 23 (SpellInfo.cpp:1824) already
     * gates whether a spell may be CAST at all. This predicate is for the effects that must let
     * the cast through and change its outcome, which no aura state can express.
     *
     * 802180 Fel Cannon carries MiscValueB 28 for a condition its own tooltip words exactly as
     * 705127's 23 ("enemies above 75% health"), so 28 is NOT a distinct predicate and is not
     * given one here; the generator normalises it to 23.
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
     * The five effect types that put a number into Spell::m_damage, which is what C5 scales.
     * Shared between spell_fs_carve::Load and its Validate so the two cannot disagree about
     * which effect carries the bucket's cells.
     *
     * SPELL_EFFECT_NORMALIZED_WEAPON_DMG (121, SharedDefines.h:887) is the one that matters and
     * the one that is easiest to leave out: 803715 Carve main-hand is effect 31 on e0 and effect
     * 121 on e1, 807422 Carve off-hand is the same, and the Twin Slice shells 803462 / 520243
     * are effect 121 and nothing else. All five funnel into Spell::EffectWeaponDamage
     * (SpellEffects.cpp:3388-3391) and are dealt through Unit::CalculateSpellDamageTaken
     * (Spell.cpp:2833/2836), so a record whose damage lives only on a 121 effect is a normal
     * damage record in every respect except that a switch missing 121 cannot see it.
     */
    // k^index only says anything for 0 < k < 1. k of exactly 1.0 is what an unauthored
    // EffectDamageMultiplier column holds, and everything else is a cell nobody meant.
    bool IsFalloff(float k)
    {
        return k > 0.0f && k < 1.0f;
    }

    bool IsDamageEffect(uint32 effect)
    {
        switch (effect)
        {
            case SPELL_EFFECT_SCHOOL_DAMAGE:
            case SPELL_EFFECT_WEAPON_DAMAGE:
            case SPELL_EFFECT_WEAPON_DAMAGE_NOSCHOOL:
            case SPELL_EFFECT_NORMALIZED_WEAPON_DMG:
            case SPELL_EFFECT_WEAPON_PERCENT_DAMAGE:
                return true;
            default:
                return false;
        }
    }

    /*
     * CAST A SPELL ID THAT CAME OUT OF A DBC CELL.
     *
     * Unit::CastSpell(Unit*, uint32, ...) LOG_ERRORs "CastSpell: unknown spell {} by caster {}"
     * for an id with no SpellInfo (Unit.cpp:1396-1401, the log line at :1399) and every caller
     * in this file is on a path that repeats -- a channel tick every 250 ms, a proc on every
     * swing. Resolving the id first and calling the SpellInfo overload (Unit.h:1678) means an
     * unwritten or mistranslated cell costs one lookup and nothing else.
     *
     * That is not hypothetical for these records. 561216 Fury of the Illidari e0 (aura 226) has
     * MiscValue 3 and 803716 Carve e0 has MiscValue 3, because on Ascension that cell is a
     * SpellModOp (SPELLMOD_EFFECT1) and not a spell id at all. `3` may well resolve to some
     * unrelated stock spell, so the run-time check below is a floor and not the fix: the fix is
     * the generator zeroing EffectMiscValue on every periodic effect it does not use as a
     * marker. Validate() names the record when the cell fails to resolve.
     */
    bool CastFromCell(Unit* caster, Unit* target, uint32 spellId,
        AuraEffect const* triggeredBy = nullptr)
    {
        if (!spellId)
            return false;

        SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId);
        if (!info)
            return false;

        caster->CastSpell(target, info, true, nullptr, triggeredBy);
        return true;
    }

    // True for a cell that is either deliberately unwritten or names a real record. Used only
    // from Validate(), which runs at boot -- World.cpp loads the SpellInfo store at :406 and
    // the rank chains at :415, both long before ValidateSpellScripts at :886.
    bool CellResolves(int32 spellId)
    {
        return spellId <= 0 || sSpellMgr->GetSpellInfo(uint32(spellId)) != nullptr;
    }

    /*
     * WHERE A TRIGGERED PAYLOAD LANDS, decided from the payload's own record rather than from a
     * list of spell ids. Shared by C3 and C8 because both buckets mix the two directions freely:
     * Straight to the Nether leeches the victim while Felguard heals the party, and Sculptor of
     * Doom buffs the caster while Felwracked hits whatever was in front of them. A hardcoded id
     * list would be a second source of truth for a fact SpellInfo::IsPositive already states,
     * and the failure mode -- a talent that silently does nothing -- is the expensive kind.
     *
     * Takes the RESOLVED payload rather than its id: both callers have already had to look it up
     * to keep Unit::CastSpell quiet, and taking the pointer means this can never return nullptr
     * and no caller needs a branch for a case that cannot happen.
     */
    Unit* PayloadTarget(SpellInfo const* payload, Unit* caster, Unit* procTarget)
    {
        return (payload->IsPositive() || !procTarget) ? caster : procTarget;
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
 * AuraEffect::HandleProcTriggerSpellAuraProc (SpellAuraEffects.cpp:6905), casts the payload with
 * its OWN base points rather than with a percentage of the damage that caused the proc.
 *
 * WHY THERE IS NO TARGET LIST HERE. Three of the six payloads are beneficial and three are not,
 * and picking the wrong end of the fight is the sort of bug that reads as "the talent does
 * nothing" for weeks. SpellInfo::IsPositive() (SpellInfo.h:486) already answers it from the
 * payload's own record, so adding a hardcoded id list would be a second, drifting source of
 * truth for a fact the DBC states.
 */
class spell_fs_damage_pct_trigger : public AuraScript
{
    PrepareAuraScript(spell_fs_damage_pct_trigger);

    bool Validate(SpellInfo const* spellInfo) override
    {
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (eff.ApplyAuraName == SPELL_AURA_PROC_TRIGGER_SPELL && eff.TriggerSpell
                && sSpellMgr->GetSpellInfo(eff.TriggerSpell))
                return true;
        }

        // The row names this script for a record that carries nothing to scale. See the
        // BOOT-TIME VALIDATION note at the top: this is the erase-the-row kind.
        LOG_ERROR("spells.scripts",
            "spell_fs_damage_pct_trigger: spell {} has no SPELL_AURA_PROC_TRIGGER_SPELL effect "
            "with a resolvable EffectTriggerSpell -- C3 has nothing to cast a percentage of.",
            spellInfo->Id);
        return false;
    }

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        // A heal proc, an absorb proc or a zeroed hit would all compute 0% of nothing and then
        // cast the payload for zero, which still burns a proc charge and still shows a combat
        // log line. Rejecting here means Aura::GetProcEffectMask returns 0 at
        // SpellAuras.cpp:2202-2203, so Aura::TriggerProcOnEvent -- and with it
        // ConsumeProcCharges (:2327) -- never runs at all.
        DamageInfo const* damageInfo = eventInfo.GetDamageInfo();
        return eventInfo.GetActor() && damageInfo && damageInfo->GetDamage() > 0;
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        Unit* caster = eventInfo.GetActor();
        DamageInfo const* damageInfo = eventInfo.GetDamageInfo();
        // CheckProc above already rejected both, but this hook is one dereference away from a
        // worldserver crash and the two hooks are separate entries in separate HookLists --
        // re-testing costs a branch and removes the dependency between them.
        if (!caster || !damageInfo)
            return;

        uint32 const triggerId =
            aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].TriggerSpell;
        SpellInfo const* payload = triggerId ? sSpellMgr->GetSpellInfo(triggerId) : nullptr;
        if (!payload)
            return;

        int32 const amount = CalculatePct(int32(damageInfo->GetDamage()), aurEff->GetAmount());
        if (amount <= 0)
            return;

        // Only now, with every reason to bail already behind us. Without this the core ALSO
        // fires EffectTriggerSpell with its own base points, so the payload lands twice -- once
        // scaled by us and once at whatever the shell record says. Legal here: AuraScript::
        // PreventDefaultAction (SpellScript.cpp:1000-1013) accepts AURA_SCRIPT_HOOK_EFFECT_PROC,
        // and AuraEffect::HandleProc (SpellAuraEffects.cpp:1287-1289) returns before its switch
        // when it is set.
        PreventDefaultAction();

        caster->CastCustomSpell(triggerId, SPELLVALUE_BASE_POINT0, amount,
            PayloadTarget(payload, caster, eventInfo.GetProcTarget()),
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
 * ALL FIVE ARE EVENT-DRIVEN AND NONE OF THEM IS A PERMANENT REDUCTION, which is worth stating
 * because the opposite reading changes the mechanism entirely. Every one is the payload of an
 * aura 42 SPELL_AURA_PROC_TRIGGER_SPELL on the talent proper, and the talent's own tooltip is
 * the proof:
 *
 *   520240 Nether Strength      -> 520830   "Casting Felfury spenders now reduces the cooldown
 *                                            of ... by $/1000;520830s1 sec."
 *   520244 Perpetual Fury       -> 520816   "Dealing damage with Dancing Blades reduces the
 *                                            cooldown of Fury Unleashed by ... sec."
 *   705135 / 572610 Reachwalker -> 680318   "Casting Chaos Rush now reduces the cooldown of
 *                                            Felhoof Charge by ... sec."
 *   801899 Legionfall           -> 801902   "... chance to reset the cooldown of ..."
 *   300480 Infernal Summoner    -> 301289   "... chance to reset the cooldown of ..."
 *
 * A cast-time SPELL_EFFECT_DUMMY is therefore the right mechanism for these records, and the
 * "shorten a cooldown that is already running" behaviour below is the intended one. What would
 * NOT work is authoring the effect onto the talent's own learned record: a passive spell is cast
 * once, at Player::addSpell time, with nothing on cooldown, and the talent would do literally
 * nothing for the rest of the character's life with no log line to say so. Validate() rejects
 * that shape at boot rather than letting it ship.
 *
 * IF A TALENT EVER DOES NEED A PERMANENT REDUCTION, IT IS DATA AND NOT THIS SCRIPT. On 3.3.5a a
 * permanent cooldown reduction is a SPELLMOD: SPELL_AURA_ADD_FLAT_MODIFIER (107, ms) or
 * SPELL_AURA_ADD_PCT_MODIFIER (108) with EffectMiscValue = SPELLMOD_COOLDOWN (11,
 * SpellDefines.h:87) and the affected abilities in EffectSpellClassMaskA. Player::
 * AddSpellAndCategoryCooldowns consumes it at Player.cpp:11147 for the spell's own
 * RecoveryTime and again at :11151 for its CategoryRecoveryTime, i.e. before either timer is
 * ever written, so nothing has to walk a rank chain and nothing has to worry about underflow.
 * (The other candidate, SPELL_AURA_MOD_COOLDOWN at Player.cpp:11154-11162, is whole SECONDS,
 * applies only to spells the player actually knows, and explicitly does not touch the category
 * cooldown -- narrower, and a worse fit for a shared-cooldown ability like Annihilan Strike.)
 *
 * Both Ascension effects become SPELL_EFFECT_DUMMY (3) carrying EffectMiscValue = the target
 * spell and a value that is the delta in milliseconds. Value 0 means RESET, which is unambiguous
 * because "shift this cooldown by zero" is not something anyone authors. Note the generator must
 * emit the reset rows with DieSides 0 -- 301289's own DieSides 1 would read as a 1 ms shift,
 * since CalcValue turns (0, 1) into 1 and not into 0.
 *
 * TWO TRAPS, BOTH LOAD-BEARING.
 *
 * 1. THE RANK CHAIN IS NOT OPTIONAL. Cooldowns are keyed per spell id, so Reachwalker aimed at
 *    Felhoof Charge has to reach 800204, 803484 AND 803485, and Legionfall aimed at Annihilan
 *    Strike has to reach all seven ranks. Walking the chain is also how the SHARED CATEGORY
 *    cooldown gets cleared without touching the global category store: Player::
 *    AddSpellAndCategoryCooldowns (Player.cpp:11177-11220) writes a separate m_spellCooldowns
 *    entry for every same-family spell in the category, so the per-id entries the walk visits
 *    ARE the category cooldown. Calling Player::RemoveCategoryCooldown (Player.cpp:3691)
 *    instead would iterate sSpellsByCategoryStore and send a clear packet for every unrelated
 *    spell that happens to share the category id.
 *
 * 2. A REDUCTION LARGER THAN THE REMAINING TIME UNDERFLOWS. Player::ModifySpellCooldown
 *    (Player.cpp:11272) is `itr->second.end += cooldown` at :11278 where `end` is uint32
 *    milliseconds and `cooldown` is a signed delta. Subtracting 2000 from 500 ms leaves
 *    4294965796, and Player::HasSpellCooldown (Player.cpp:16706) compares `end > getMSTime()`
 *    at :16709 -- so the ability a talent was supposed to hasten becomes unusable for about 49
 *    days. Clamped below.
 */
class spell_fs_modify_cooldown : public SpellScript
{
    PrepareSpellScript(spell_fs_modify_cooldown);

    bool Validate(SpellInfo const* spellInfo) override
    {
        // See the block comment: a passive record's DUMMY runs exactly once, at learn time.
        if (spellInfo->HasAttribute(SPELL_ATTR0_PASSIVE))
        {
            LOG_ERROR("spells.scripts",
                "spell_fs_modify_cooldown: spell {} is SPELL_ATTR0_PASSIVE. A C4 record must be "
                "the TRIGGERED PAYLOAD of the talent's proc, not the talent's own learned "
                "record -- a passive is cast once at learn time with nothing on cooldown.",
                spellInfo->Id);
            return false;
        }

        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (eff.Effect == SPELL_EFFECT_DUMMY && eff.MiscValue > 0
                && CellResolves(eff.MiscValue))
                return true;
        }

        LOG_ERROR("spells.scripts",
            "spell_fs_modify_cooldown: spell {} has no SPELL_EFFECT_DUMMY effect whose "
            "EffectMiscValue names a real spell -- C4 has no cooldown to move.", spellInfo->Id);
        return false;
    }

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

        int32 const targetSpellId = GetSpellInfo()->Effects[effIndex].MiscValue;
        if (targetSpellId <= 0)
            return;

        int32 const deltaMs = GetEffectValue();

        for (uint32 rank = sSpellMgr->GetFirstSpellInChain(uint32(targetSpellId)); rank;
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
 *   the DAMAGE    803715 / 807422 Carve main- and off-hand (effect 31 on e0 plus effect 121 on
 *                 e1, both into a cone, ImplicitTarget 54), 712399 Sunder's explosion.
 *
 * Cells, all on the effect the hook lands on:
 *   channel  EffectMiscValue   the tick-marker spell id, whose stack count tracks the tick
 *                              number. 0 = do not track.
 *            EffectMiscValueB  a spell cast on the caster ONLY if the channel ran to full
 *                              duration -- Annihilan Rituals' Felfury refund (port-plan C5 d)
 *                              and Whirling Vengeance's 806096. 0 = nothing.
 *            Both are free on aura 23: AuraEffect::HandlePeriodicTriggerSpellAuraTick
 *            (SpellAuraEffects.cpp:6000, reading EffectTriggerSpell at :6003) never touches
 *            either MiscValue column anywhere in its body.
 *   damage   EffectDamageMultiplier  per-additional-target falloff k, applied as k^index.
 *                              <= 0 or >= 1 means no falloff.
 *            EffectMiscValueB  the same tick-marker spell id, read back for the accumulator.
 *
 * THE ACCUMULATOR'S NUMBER IS ASCENSION'S, RE-EXPRESSED, AND THE CONVERSION IS THE GENERATOR'S.
 * Ascension's 803716 is SPELL_AURA_ADD_FLAT_MODIFIER MiscValue 3 (SPELLMOD_EFFECT1) at bp 24
 * DieSides 1 = +25, i.e. +25 percentage POINTS onto Carve's 40% weapon damage per tick. That
 * cannot ship as data here for the reason port-plan section 1 gives about Inner Demon:
 * Player::ApplySpellMod (Player.cpp:10069-10080) sums each modifier once and never multiplies
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
    // Spell::LoadScripts (Spell.cpp:8578) news one SpellScript per Spell object and deletes it
    // with the Spell, so these members cannot leak across casts or across players.
    std::unordered_map<ObjectGuid, uint32> _falloffIndex;
    float _falloff = 0.0f;
    uint32 _markerSpellId = 0;

    bool Validate(SpellInfo const* spellInfo) override
    {
        // The optional-cell kind: this name is also written onto channel records with no damage
        // effect at all, where finding nothing is the correct outcome. Only a cell that IS
        // written and does not name a real spell is worth a line.
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (IsDamageEffect(eff.Effect) && !CellResolves(eff.MiscValueB))
                LOG_ERROR("spells.scripts",
                    "spell_fs_carve: spell {} effect {} has EffectMiscValueB {}, which is not a "
                    "spell id. The C5 accumulator will be skipped for this record.",
                    spellInfo->Id, uint32(i), eff.MiscValueB);
        }

        return true;
    }

    bool Load() override
    {
        /*
         * Read the two cells once per cast rather than once per target, and take the first
         * USABLE value of each rather than everything from the first damage effect. Carve's
         * 803715 is the reason: e0 is SPELL_EFFECT_WEAPON_PERCENT_DAMAGE and e1 is
         * SPELL_EFFECT_NORMALIZED_WEAPON_DMG, and which of the two the generator hangs the
         * falloff and the marker on is its business, not ours.
         *
         * "Usable" and not "non-zero" for the falloff specifically, because 1.0 is the value
         * EffectDamageMultiplier carries when nobody has authored one -- taking it from e0
         * would mask a real 0.6 on e1 and turn the cone flat with no diagnostic. A record with
         * neither cell written leaves both members at 0 and this script is a no-op on it, which
         * is what the channel records want.
         */
        SpellInfo const* info = GetSpellInfo();
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = info->Effects[i];
            if (!IsDamageEffect(eff.Effect))
                continue;

            if (_falloff == 0.0f && IsFalloff(eff.DamageMultiplier))
                _falloff = eff.DamageMultiplier;

            if (!_markerSpellId && eff.MiscValueB > 0)
                _markerSpellId = uint32(eff.MiscValueB);
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
     * Spell::HandleEffects (Spell.cpp:5627) calls the effect script hooks at :5645, BEFORE
     * dispatching to the effect handler at :5649, so inside OnEffectHitTarget the weapon swing
     * has not been rolled yet and GetHitDamage() is whatever earlier effects happened to
     * accumulate -- usually zero. CallScriptOnHitHandlers (Spell.cpp:2754) runs after every
     * effect on the target and before Unit::DealDamage, so GetHitDamage() there is the real,
     * whole number. OnHit is also index-free, so one binding covers a record whose damage is
     * spread over two effects (Carve's 803715 is weapon-percent on e0 plus normalized weapon
     * damage on e1) without scaling it twice.
     */
    void ScaleHitDamage()
    {
        Unit* target = GetHitUnit();
        int32 const original = GetHitDamage();
        if (!target || original <= 0)
            return;

        int32 damage = original;

        /*
         * The accumulator, first.
         *
         * AuraEffect::GetAmount() ON THE MARKER IS ALREADY MULTIPLIED BY THE STACK COUNT, and
         * multiplying again here is the difference between +1250% and +25000% on a 20-tick
         * Carve. AuraEffect::CalculateAmount ends with `amount *= GetBase()->GetStackAmount();`
         * (SpellAuraEffects.cpp:580, immediately after the script hook at :578), and
         * Aura::SetStackAmount (SpellAuras.cpp:942) sets m_stackAmount at :944 and then re-runs
         * CalculateAmount for every effect at :957-959 -- and it is reached on every single
         * stack change, from Aura::ModStackAmount at SpellAuras.cpp:1000. So the marker's
         * per-tick percentage times the number of ticks the channel reached is exactly what
         * GetAmount() returns, with no arithmetic of ours.
         */
        if (_markerSpellId)
        {
            if (Unit* caster = GetCaster())
                if (AuraEffect const* marker = caster->GetAuraEffect(_markerSpellId, EFFECT_0,
                        caster->GetGUID()))
                    AddPct(damage, marker->GetAmount());
        }

        // Then the falloff. A target that never went through the area selection (a single
        // explicit target, or a second effect with its own target type) is absent from the map
        // and correctly takes full damage.
        if (_falloff > 0.0f)
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
         * because SpellScript::TargetHook::CheckEffect (SpellScript.cpp:237, the TargetA/TargetB
         * compare at :242) matches against the exact `targetType` this hook was built with --
         * and the records sharing this script do not agree on one. Carve's 803715 is
         * ImplicitTarget 54 (a cone), Sunder's 712399 is 16 (a destination area). Registering a
         * fixed pair of literals would either miss one of them or log a boot-time mismatch for
         * the other; the loop registers exactly the hooks the record can actually fire.
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
 * It holds no tick counter of its own: AuraEffect::Update increments m_tickNumber at
 * SpellAuraEffects.cpp:940 before calling PeriodicTick at :950, so aurEff->GetTickNumber() is
 * already 1 on the first tick and is authoritative in a way a member int would not be if a tick
 * were ever skipped. The marker aura still carries the count, because it is the only thing the
 * damage record -- a different Spell object, cast from the data chain and not by us -- can read.
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

    bool Validate(SpellInfo const* spellInfo) override
    {
        /*
         * The optional-cell kind, and the reason CastFromCell exists. 561216 Fury of the
         * Illidari e0 is aura 226 with MiscValue 3, and 803716 Carve e0 is aura 107 with
         * MiscValue 3, because on Ascension that column is a SpellModOp. If the generator copies
         * either through, the marker branch below tries to cast spell 3 on every tick. Naming
         * the record at boot is the only way anyone connects that to this cell; the row stays,
         * because 561216 still needs this script for its PERIODIC_DUMMY payload.
         */
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (eff.ApplyAuraName != SPELL_AURA_PERIODIC_TRIGGER_SPELL
                && eff.ApplyAuraName != SPELL_AURA_PERIODIC_DUMMY)
                continue;

            if (!CellResolves(eff.MiscValue))
                LOG_ERROR("spells.scripts",
                    "spell_fs_carve_channel: spell {} effect {} has EffectMiscValue {}, which is "
                    "not a spell id. Zero it unless it is meant to be the tick marker.",
                    spellInfo->Id, uint32(i), eff.MiscValue);

            if (!CellResolves(eff.MiscValueB))
                LOG_ERROR("spells.scripts",
                    "spell_fs_carve_channel: spell {} effect {} has EffectMiscValueB {}, which "
                    "is not a spell id. Zero it unless it is meant to be the full-channel "
                    "reward.", spellInfo->Id, uint32(i), eff.MiscValueB);
        }

        return true;
    }

    void HandleTick(AuraEffect const* aurEff)
    {
        Unit* caster = GetCaster();
        if (!caster)
            return;

        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];

        /*
         * SPELL_AURA_PERIODIC_DUMMY does nothing on this core unless the spell id is one of the
         * hardcoded cases in AuraEffect::HandlePeriodicDummyAuraTick (SpellAuraEffects.cpp:5943),
         * which Ascension's ids obviously are not -- so for 561216 Fury of the Illidari ("6
         * assaults, +1 Felfury each") the script has to fire the payload itself. Aura 23 needs
         * no help: its own handler runs immediately after this hook returns
         * (SpellAuraEffects.cpp:1131 then the switch at :1151).
         */
        if (aurEff->GetAuraType() == SPELL_AURA_PERIODIC_DUMMY)
            CastFromCell(caster, caster, eff.TriggerSpell);

        if (eff.MiscValue <= 0)
            return;

        uint32 const markerId = uint32(eff.MiscValue);
        if (Aura* marker = caster->GetAura(markerId, caster->GetGUID()))
        {
            // ModStackAmount and NOT SetStackAmount: only the former caps against the record's
            // CumulativeAura column (SpellAuras.cpp:973-980), which is where the generator puts
            // the ceiling on how long a channel is allowed to keep ramping.
            //
            // Also NOT CastCustomSpell(..., SPELLVALUE_AURA_STACK, n, ...): on an aura that
            // already exists, Spell::EffectApplyAura (Spell.cpp:3147-3155) treats that value as
            // ModStackAmount rather than as an assignment, so "set the stack to 4" would ADD
            // four stacks to the three already there.
            marker->ModStackAmount(1);
            marker->RefreshDuration();
        }
        else
            CastFromCell(caster, caster, markerId);
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

        if (eff.MiscValue > 0)
            caster->RemoveAurasDueToSpell(uint32(eff.MiscValue), caster->GetGUID());

        /*
         * "On a FULL channel", not "on any removal" -- port-plan C5 (d) is explicit that
         * Annihilan Rituals refunds Felfury for finishing the channel and not for starting one
         * and moving. AuraApplication::GetRemoveMode (SpellAuras.h:73) is the only thing that
         * separates the two: a channel that ran out its duration is AURA_REMOVE_BY_EXPIRE
         * (SpellAuraDefines.h:395), while an interrupt, a cancel, a death or a zone change is
         * not.
         */
        AuraApplication const* application = GetTargetApplication();
        if (_completionFired || eff.MiscValueB <= 0 || !application
            || application->GetRemoveMode() != AURA_REMOVE_BY_EXPIRE)
            return;

        // Latched BEFORE the cast, not after: the completion spell can remove auras of its own
        // and re-enter this hook, and a latch set afterwards would not be standing yet.
        _completionFired = true;
        CastFromCell(caster, caster, uint32(eff.MiscValueB));
    }

    void Register() override
    {
        // Registered from the record for the same reason as the cone hooks above: this name is
        // also written onto damage records with no aura effect at all, and an unconditional
        // periodic hook would log a mismatch for every one of them at boot
        // (ObjectMgr.cpp:6399 -> SpellScript.cpp:694).
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
 * modifier point per unit of source, WITH DieSides 0 so that CalcValue returns it unchanged
 * (the DieSides switch at SpellInfo.cpp:431-437 adds 1 for DieSides 1 and nothing for 0), and
 * names the source in EffectMiscValueB.
 * "+$s2% crit for every 10 points of Energy" (300489) is coefficient 10; "one point of armour
 * per point of dodge percent" is 100. No number is invented in this file -- the amount is
 * entirely (source x cell / 100).
 *
 * THE FAILURE MODE IS SILENCE, SO Validate() BREAKS IT. Every carrier in the dump is bp 0 or
 * bp -1, i.e. a coefficient of 1 or 0 today, and a coefficient of 0 is a talent that does
 * nothing with no symptom at all. The generator authoring MiscValueB but forgetting BasePoints
 * is now a boot-time error and an erased row rather than a bug report six weeks later.
 *
 * THE STALENESS IS REAL AND IT IS NAMED. port-plan section 4 C6 asks for Ascension's 500-9999 ms
 * recompute poll to be replaced with a stat-change hook. There is no such hook on this fork:
 * PlayerScript.h has nothing between OnPlayerBeforeUpdateAttackPowerAndDamage (:478) and
 * OnPlayerApplyItemModsBefore (:567) that fires on Player::UpdateStats or Player::UpdateRating,
 * and UnitScript.h has none either. So the recompute stays a poll. Ascension runs it by having
 * the TALENT re-cast the carrier on an aura-23 timer (803478 every 9999 ms, 574146 every 1499
 * ms, 574145 every 5000 ms, 92089 every 3000 ms); we put the period on the CARRIER instead, as a
 * SPELL_AURA_PERIODIC_DUMMY with an Amplitude, so the recompute is one RecalculateAmount rather
 * than a full re-application. Only the WINDOW shrinks, not the shape: the first value is exact
 * (see the no-apply-hook note in Register below) and every later one is at most one period
 * stale. Replacing the poll properly is a core patch, and it is the only part of C6 that this
 * file cannot do.
 */
class spell_fs_stat_spellmod : public AuraScript
{
    PrepareAuraScript(spell_fs_stat_spellmod);

    bool Validate(SpellInfo const* spellInfo) override
    {
        bool claimed = false;
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (!eff.ApplyAuraName || eff.MiscValueB == FS_STAT_NONE)
                continue;

            claimed = true;

            // Both halves of the contract, because either one alone computes to zero. bp -1
            // with DieSides 1 -- which is what four of the five carriers ship today -- reads as
            // CalcValue 0, and bp 0 with DieSides 1 reads as a coefficient of 1, neither of
            // which is a number anyone chose.
            if (eff.BasePoints == 0 || eff.DieSides != 0)
            {
                LOG_ERROR("spells.scripts",
                    "spell_fs_stat_spellmod: spell {} effect {} names stat source {} in "
                    "EffectMiscValueB, so it needs a non-zero EffectBasePoints with "
                    "EffectDieSides 0 -- it has BasePoints {} and DieSides {}, which is not a "
                    "coefficient.",
                    spellInfo->Id, uint32(i), eff.MiscValueB, eff.BasePoints, eff.DieSides);
                return false;
            }
        }

        if (claimed)
            return true;

        LOG_ERROR("spells.scripts",
            "spell_fs_stat_spellmod: spell {} has no aura effect carrying a stat source in "
            "EffectMiscValueB -- C6 has nothing to compute.", spellInfo->Id);
        return false;
    }

    void CalcAmount(AuraEffect const* aurEff, int32& amount, bool& canBeRecalculated)
    {
        int32 const source = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].MiscValueB;
        if (source == FS_STAT_NONE)
            return;                     // not one of ours; leave the DBC value alone

        Unit const* owner = GetUnitOwner();
        if (!owner)
            return;

        // `amount` arrives as the DBC value, which for these records IS the coefficient. Read
        // it before overwriting it. It has NOT yet been multiplied by the stack count -- that
        // happens at SpellAuraEffects.cpp:580, after this hook returns at :578 -- which is
        // correct here, because these carriers are single-stack.
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
        // already correct: UnitAura's constructor (SpellAuras.cpp:2780) calls LoadScripts at
        // :2784 BEFORE _InitEffects at :2785, and _InitEffects constructs each AuraEffect
        // through CalculateAmount -> CallScriptEffectCalcAmountHandlers
        // (SpellAuraEffects.cpp:578). So CalcAmount above has already run by the time the
        // talent is applied, and an AfterEffectApply that called Recompute would only add a
        // re-entrant ChangeAmount in the middle of AuraEffect::HandleEffect for no change in
        // value.
        //
        // Only where the record actually asks for a poll -- see the staleness note above, and
        // the same boot-noise argument as spell_fs_carve_channel::Register. The generator's
        // ticker of choice is a SPELL_AURA_PERIODIC_DUMMY effect with an Amplitude: its own
        // handler, AuraEffect::HandlePeriodicDummyAuraTick (SpellAuraEffects.cpp:5943), is a
        // hardcoded id switch that no Felsworn id is in, so the tick costs nothing beyond this
        // hook.
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
 * Cells on the proc effect:
 *   EffectMiscValue    N.   <= 1 means "every time" and needs no marker.
 *   EffectMiscValueB   the counter marker spell id -- CumulativeAura >= N - 1
 *   EffectTriggerSpell the payload, fired only on the Nth
 *
 * AURA 42 OR AURA 4, AND THE CORE DOES NOT CARE WHICH. Three of these six carry the shape on
 * SPELL_AURA_PROC_TRIGGER_SPELL and three on SPELL_AURA_DUMMY (560840 and 706268 have nothing
 * else at all; 704374's counter is on aura 42). Both are trigger auras --
 * SpellMgr.cpp:1953 sets isTriggerAura[SPELL_AURA_DUMMY] with the comment "Most dummy auras
 * should require scripting" and :1966 does the same for SPELL_AURA_PROC_TRIGGER_SPELL -- and
 * AuraEffect::HandleProc routes them to the SAME handler through a shared case label
 * (SpellAuraEffects.cpp:1300-1302). Register() therefore binds whichever ONE of the two the
 * record actually uses, which is what keeps `did not match dbc effect data` out of the boot log
 * either way. Aura 42 is still the shape to author: it says what it does.
 *
 * WHICH events count is NOT decided here. It is the record's own ProcTypeMask plus, where a
 * crit-only or chance gate is needed, a spell_proc row -- port-plan section 4 C0. Sculptor of
 * Doom counting only critical strikes is HitMask PROC_HIT_CRITICAL in that row, not an `if` in
 * this function.
 */
class spell_fs_counter : public AuraScript
{
    PrepareAuraScript(spell_fs_counter);

    // Set once in Register() from the record, and the only aura type the two proc hooks below
    // are bound to. 0 means "this record carries neither", which Validate() has already
    // rejected -- Register() still checks, because Register() runs first (ObjectMgr.cpp:6432
    // before :6433) and must not bind a hook it cannot honour.
    uint16 _procAuraName = 0;

    bool Validate(SpellInfo const* spellInfo) override
    {
        for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
        {
            SpellEffectInfo const& eff = spellInfo->Effects[i];
            if (eff.ApplyAuraName != SPELL_AURA_PROC_TRIGGER_SPELL
                && eff.ApplyAuraName != SPELL_AURA_DUMMY)
                continue;

            if (!eff.TriggerSpell || !sSpellMgr->GetSpellInfo(eff.TriggerSpell))
                continue;

            // BOTH CELLS UNWRITTEN IS THE CASE THAT USED TO BE SILENT, and it is the most
            // likely one: this script is bound by a spell_script_names row, so a record only
            // reaches it because a talent DECLARED itself an "every Nth" effect. If N was
            // never authored, the declaration and the data disagree and the talent quietly
            // becomes "every time" -- strictly stronger than intended, which is the direction
            // nobody reports as a bug. 704374 Felwracked is exactly this: aura 42, a real
            // trigger, and MiscValue == MiscValueB == 0.
            //
            // So N is checked on its own rather than only when a marker happens to be present.
            // Still LOG_ERROR and not a rejection: the payload firing every time is wrong but
            // playable, and erasing the row would remove the ability instead of the bug.
            if (eff.MiscValue <= 1)
                LOG_ERROR("spells.scripts",
                    "spell_fs_counter: spell {} effect {} has EffectMiscValue {} -- N was never "
                    "authored, so 'every Nth' degrades to 'every time'. The generator must "
                    "write the period.", spellInfo->Id, uint32(i), eff.MiscValue);
            else if (!CellResolves(eff.MiscValueB))
                LOG_ERROR("spells.scripts",
                    "spell_fs_counter: spell {} effect {} has EffectMiscValueB {}, which is not "
                    "a spell id, so the counter cannot be kept and the payload will fire on "
                    "every event.", spellInfo->Id, uint32(i), eff.MiscValueB);

            return true;
        }

        LOG_ERROR("spells.scripts",
            "spell_fs_counter: spell {} has no SPELL_AURA_PROC_TRIGGER_SPELL or SPELL_AURA_DUMMY "
            "effect with a resolvable EffectTriggerSpell -- C8 has no payload to withhold.",
            spellInfo->Id);
        return false;
    }

    /*
     * The whole validity check, moved OFF the proc path and onto the check path.
     *
     * Aura::TriggerProcOnEvent calls ConsumeProcCharges unconditionally once the hooks have run
     * (SpellAuras.cpp:2327), so a proc that reaches HandleProc and then returns without firing
     * anything has still spent a charge. Rejecting from here instead means Aura::GetProcEffectMask
     * drops the effect (SpellAuras.cpp:2213-2214), and if no effect survives it returns 0 at
     * :2219-2220 and Unit's caller (Unit.cpp:12850) never enters TriggerProcOnEvent at all.
     */
    bool CheckEffectProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        if (!eventInfo.GetActor())
            return false;

        uint32 const payloadId =
            aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].TriggerSpell;
        return payloadId && sSpellMgr->GetSpellInfo(payloadId) != nullptr;
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        Unit* caster = eventInfo.GetActor();
        SpellEffectInfo const& eff = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()];
        SpellInfo const* payload = sSpellMgr->GetSpellInfo(eff.TriggerSpell);
        if (!caster || !payload)
            return;                     // CheckEffectProc proved both; see the C3 note on why

        // The payload must fire on the Nth event only, so the core's own
        // HandleProcTriggerSpellAuraProc -- which would fire it on every one -- is suppressed
        // from here down. Nothing below this line returns without having decided, deliberately,
        // either to fire the payload or to withhold it.
        PreventDefaultAction();

        Unit* target = PayloadTarget(payload, caster, eventInfo.GetProcTarget());
        int32 const period = eff.MiscValue;
        int32 const counterId = eff.MiscValueB;

        // N <= 1 is "every time", and it is also what an unwritten MiscValue looks like. Both
        // read the same way and neither needs the marker.
        if (period <= 1 || counterId <= 0)
        {
            caster->CastSpell(target, payload, true, nullptr, aurEff);
            return;
        }

        Aura* counter = caster->GetAura(uint32(counterId), caster->GetGUID());
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
                CastFromCell(caster, caster, uint32(counterId));

            return;
        }

        // The Nth. Clear the counter BEFORE the payload: the payload may itself proc something
        // that re-enters this function, and a marker still standing at N would fire it twice.
        caster->RemoveAurasDueToSpell(uint32(counterId), caster->GetGUID());
        caster->CastSpell(target, payload, true, nullptr, aurEff);
    }

    void Register() override
    {
        // Bound from the record, and to exactly ONE aura type. Binding both would double-fire
        // on any record that ever carries an aura 4 alongside its aura 42, and binding the one
        // the record does not use is precisely the mismatch line at SpellScript.cpp:758.
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(m_scriptSpellId))
        {
            for (uint8 i = 0; i < MAX_SPELL_EFFECTS; ++i)
            {
                AuraType const type = info->Effects[i].ApplyAuraName;
                if (type == SPELL_AURA_PROC_TRIGGER_SPELL)
                {
                    _procAuraName = SPELL_AURA_PROC_TRIGGER_SPELL;
                    break;              // preferred; stop looking
                }

                if (type == SPELL_AURA_DUMMY && !_procAuraName)
                    _procAuraName = SPELL_AURA_DUMMY;
            }
        }

        if (!_procAuraName)
            return;

        DoCheckEffectProc += AuraCheckEffectProcFn(spell_fs_counter::CheckEffectProc,
            EFFECT_ALL, _procAuraName);
        OnEffectProc += AuraEffectProcFn(spell_fs_counter::HandleProc,
            EFFECT_ALL, _procAuraName);
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
 * of the same talents.
 *
 * ONE OP AND ONE HOOK. The anonymous-namespace block at the top of this file works through all
 * eight of Ascension's aura-112 effects and shows that only MiscValue 20007, "damage done",
 * carries one meaning; read that first. What is left after it is two records:
 *
 *   520833 Doomsayer e1     20007/23  +25% Sargeron Smite damage vs a victim above 75% health
 *   804610 Reckless Assault 20007/26  +15% damage vs slowed enemies, mask 0x00108000
 *
 * Both are damage bonuses on named ABILITIES, and every Felsworn ability is a spell: its damage
 * effect (2, 17, 31, 58 or 121) accumulates into Spell::m_damage and is dealt through
 * Unit::CalculateSpellDamageTaken (Spell.cpp:2833/2836), which dispatches
 * sScriptMgr->ModifySpellDamageTaken at Unit.cpp:1507 -- inside the function, after the school
 * mask is taken and before armour reduction. So ModifySpellDamageTaken sees both records with
 * a real SpellInfo in hand, and it is the only hook this script needs.
 *
 * THE TWO HOOKS THAT ARE DELIBERATELY NOT REGISTERED, and it is not a saving of a few lines.
 * CALL_ENABLED_HOOKS (ScriptMgrMacros.h:72-74) skips the dispatch entirely while
 * EnabledHooks[hook] is EMPTY, so a hook nobody registers costs the realm nothing at all and a
 * hook this script registers costs a loop on every unit, every swing, forever.
 *
 *   ModifyMeleeDamage (Unit.cpp:1763, inside Unit::CalculateMeleeDamage at :1667) sees WHITE
 *   SWINGS and nothing else, and it is handed no SpellInfo. An effect that names abilities
 *   through its SpellClassMask cannot be matched against a swing that has no spell, and an
 *   effect that names none is rejected outright (see Applies below), so there is nothing left
 *   for it to do. A bonus that really did mean "all damage, unconditionally" has a native
 *   expression -- SPELL_AURA_MOD_DAMAGE_PERCENT_DONE -- and would not come through this bucket.
 *
 *   OnBeforeRollMeleeOutcomeAgainst (Unit.cpp:2982) is the crit-chance hook, and the whole tree
 *   has exactly ONE call into the function that dispatches it: Unit::CalculateMeleeDamage at
 *   Unit.cpp:1782 -> Unit::RollMeleeOutcomeAgainst (:2946, then the int32 overload at :2969).
 *   White swings again. An ability's crit is rolled in Unit::SpellDoneCritChance (Unit.cpp:9105)
 *   instead, where this fork has no script hook at all. So the one record that wants a
 *   conditional crit CHANCE, 802180 Fel Cannon ("Fel Fireball and Ruin"), could not be served
 *   from here even if 20000 were unambiguous, and nothing else in the family asks for a
 *   white-swing crit bonus. Registering it anyway is how 92087's amount of 100 became +10000
 *   against a urand(0, 10000) roll.
 *
 *   To bring it back: give melee crit chance its OWN op code -- one we define, not 20000, so a
 *   copied-through Ascension cell can never reach it -- and remember that crit_chance in that
 *   hook is in HUNDREDTHS of a percent (RollMeleeOutcomeAgainst is entered with
 *   int32(crit_chance * 100) at Unit.cpp:2966 and rolls urand(0, 10000) at :2987).
 *
 * ALSO NOT REACHABLE FROM HERE, and listed so nobody re-derives it:
 *   * You Cheat, Gul'dan!'s crit DAMAGE (20001) is Unit::SpellCriticalBonus (Unit.cpp:9422-9425)
 *     and Unit::CalculateMeleeDamage (:1552-1555); no hook, and a native aura 163 does it.
 *   * Annihilan Strike's guaranteed crit is a third path again: SPELLVALUE_FORCED_CRIT_RESULT
 *     (SpellDefines.h:120), set by whoever casts it. Its >75% gate is the DATA half --
 *     TargetAuraState 23, port-plan 2.2 -- so it needs nothing from here. If a fourth caller
 *     ever does, VictimConditionHolds moves out of this file's anonymous namespace into
 *     demon_hunter.h; it is a free function rather than a member for exactly that reason, but
 *     it is not reachable from another translation unit as it stands.
 *
 * COST. Every spell hit on the realm enters ModifySpellDamageTaken, because this script's
 * registration is what makes EnabledHooks[UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN] non-empty.
 * IsFelsworn is therefore first and is one field read plus two compares, which rejects every
 * attacker on the realm before the aura list is even touched. The same argument, and the same
 * shape, as demon_hunter_playerscript::OnPlayerIsClass (demon_hunter.cpp:470, whose own
 * getClass test at :475 is the same idea).
 */
class felsworn_victim_conditions_unitscript : public UnitScript
{
public:
    // Hooks are opted into EXPLICITLY. UnitScript's constructor treats an empty enabledHooks
    // vector as "all hooks" (UnitScript.cpp:148-150), which would put this script on all
    // twenty-one dispatch lists -- including OnUnitUpdate, once per unit per tick -- for the
    // sake of one.
    felsworn_victim_conditions_unitscript() : UnitScript("felsworn_victim_conditions_unitscript",
        true,
    {
        UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN
    }) { }

    void ModifySpellDamageTaken(Unit* target, Unit* attacker, int32& damage,
        SpellInfo const* spellInfo) override
    {
        if (damage <= 0 || !target || !spellInfo || !IsFelsworn(attacker))
            return;

        // Several effects may match at once and they add, which is how the equivalent spellmods
        // would stack if this were expressible as data. Accumulated separately so the bonus is
        // always a percentage of the damage as it arrived, not of a running total.
        int32 bonus = 0;
        for (AuraEffect const* aurEff :
             attacker->GetAuraEffectsByType(SPELL_AURA_OVERRIDE_CLASS_SCRIPTS))
            if (Applies(aurEff, target, spellInfo))
                bonus += CalculatePct(damage, aurEff->GetAmount());

        damage += bonus;
    }

private:
    /*
     * True when this aura-112 effect is one of ours, names this spell, and its victim predicate
     * holds.
     *
     * AN EMPTY SpellClassMask IS REJECTED, AND THAT IS THE WHOLE POINT OF THE FIRST TEST.
     * AuraEffect::IsAffectedOnSpell (SpellAuraEffects.cpp:1106) forwards to SpellInfo::IsAffected
     * (SpellInfo.cpp:1325), whose familyFlags test at :1333 is `if (familyFlags && !(familyFlags
     * & SpellFamilyFlags)) return false;` -- an EMPTY mask skips the test and matches every
     * spell in the family. An unmasked C7 effect would therefore read as "+X% to every family-20
     * spell you cast", which is not what a single one of these records says: Doomsayer names
     * Sargeron Smite, Fel Cannon names Fel Fireball and Ruin, 92087 names melee abilities.
     * Ascension supplied those lists in engine code, so four of its five carry class_mask_a == 0
     * and only 804610 Reckless Assault is masked (0x00108000). The list has to come back as a
     * mask; until it does, the effect is a generator bug and is failed closed exactly like an
     * unknown condition code in VictimConditionHolds.
     *
     * AuraEffect::HasSpellClassMask (SpellAuraEffects.cpp:1118) is the test, rather than
     * reaching into Effects[].SpellClassMask, because it is the same expression the core uses.
     */
    static bool Applies(AuraEffect const* aurEff, Unit const* victim, SpellInfo const* spellInfo)
    {
        // A negative or zero amount is either a cell nobody wrote or a damage REDUCTION nobody
        // asked for. Neither is worth guessing at.
        if (aurEff->GetMiscValue() != FS_CS_DAMAGE_DONE || aurEff->GetAmount() <= 0)
            return false;

        if (!aurEff->HasSpellClassMask() || !aurEff->IsAffectedOnSpell(spellInfo))
            return false;

        return VictimConditionHolds(aurEff->GetMiscValueB(), victim);
    }
};

/*
 * Registration.
 *
 * Called from AddSC_demon_hunter (demon_hunter.cpp:636, the call at :649) alongside the three
 * code-registered scripts, and declared in demon_hunter.h:264 next to it. Kept as its own
 * function rather than folded into that one so that the file that owns C1/C2 can add a third
 * the same way.
 *
 * RegisterSpellScript hands the DB the STRINGIFIED CLASS NAME (SpellScriptLoader.h:88), so the
 * five names below are literally what tools/dh_talents.py SCRIPT_NAMES must contain and what
 * ends up in spell_script_names.ScriptName. Renaming a class here silently unbinds every row
 * that names it -- ObjectMgr::LoadSpellScriptNames logs nothing for a ScriptName with no
 * script, it just resolves to script id 0 and the talent stops working.
 *
 * Carve is the one pair: RegisterSpellAndAuraScriptPair registers under the name of the FIRST
 * class only (SpellScriptLoader.h:90), so both halves share the single name `spell_fs_carve`.
 * Both halves are also validated at boot, and ObjectMgr::ValidateSpellScripts erases the row if
 * EITHER returns false (ObjectMgr.cpp:6433, :6441, :6447) -- which is why spell_fs_carve and
 * spell_fs_carve_channel both return true for a record shaped for the other one.
 */
void AddSC_felsworn_spells()
{
    RegisterSpellScript(spell_fs_damage_pct_trigger);
    RegisterSpellScript(spell_fs_modify_cooldown);
    RegisterSpellAndAuraScriptPair(spell_fs_carve, spell_fs_carve_channel);
    RegisterSpellScript(spell_fs_stat_spellmod);
    RegisterSpellScript(spell_fs_counter);

    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process, the same convention as demon_hunter.cpp:640-642.
    new felsworn_victim_conditions_unitscript();
}
