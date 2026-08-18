/*
 * felfury_core.cpp -- buckets C1 (Felfury accounting) and C2 (Inner Demon) of
 * .work/felsworn/port-plan.md section 4. These are the two scripts the whole class stands on:
 * every generator, every spender and the form all read and write one stacking aura, and nothing
 * else in the kit works if this file is wrong.
 *
 * Read demon_hunter.h first -- it carries the hook-name warning, the generated-table contract,
 * the three-way registration split, and the reason CLASS_DEMON_HUNTER does not exist in the
 * checkout on disk.
 *
 * WHY A SEPARATE TRANSLATION UNIT AND NOT MORE OF demon_hunter.cpp
 * ---------------------------------------------------------------
 * demon_hunter.cpp is the class-plumbing file: Reconcile, OnPlayerIsClass, the three untrainable
 * spells, the falling gate. None of that is gameplay. This file is gameplay and it is the part
 * that will change when the numbers change, so it is separated for the same reason
 * dh_progression.h is: so that a diff to the resource economy does not touch the file that
 * decides whether the class can dual wield.
 *
 * It deliberately does NOT introduce a second AllSpellScript. The existing
 * `demon_hunter_movement_allspellscript` (declared demon_hunter.h:180, OnSpellCheckCast
 * implemented demon_hunter.cpp:540, registered :634) is already in the dispatch lists; a
 * parallel script would mean a second entry in every one of them for no gain. The two new
 * overrides below are members of that same class, defined here.
 *
 * =============================================================================================
 * WHAT THIS FILE READS, AND WHO OWNS IT
 * =============================================================================================
 *
 * Everything numeric comes from the GENERATED src/dh_progression.h -- tools/dhspells.py
 * emit_header, from the declarations in tools/dh_spec.py. Nothing here is a literal spell id or
 * a literal stack count, because both halves of every one of those numbers (the DBC record and
 * the module's arithmetic) have to agree and the generator is the only thing that can make them:
 *
 *     FELSWORN_SPELL_ID_MIN / _MAX      the id band, used as the cheap first test on every hook
 *     FELFURY_SPELL_ID                  the resource record
 *     INNER_DEMON_SPELL_ID              the form record
 *     FELFURY_MAX_STACKS                the untalented cap
 *     FELFURY_STACK_CEILING             the felfury record's own CumulativeAura cell, READ off
 *                                       the emitted Spell.dbc rather than declared
 *     INNER_DEMON_MS_PER_FELFURY        milliseconds of form bought by one stack
 *     kDhFelfuryGenerators              rank-1 id -> stacks the MODULE adds (see below)
 *     kDhFelfurySpenders                rank-1 id -> stacks consumed
 *     kDhFelAddictRanks                 talent id -> how much it raises the cap
 *     kDhFelheartRanks                  talent ids whose spell mod fills the haste carriers
 *
 * A GENERATOR'S CELL IS THE MODULE'S SHARE, NOT THE ABILITY'S TOTAL, and that distinction is
 * the whole reason the table is generated rather than written here. Part of every grant is pure
 * data: an authored `Effect_N = 64 SPELL_EFFECT_TRIGGER_SPELL -> felfury` reaches the pool
 * through Unit::_TryStackingOrRefreshingExistingAura (Unit.cpp:4615), whose ModStackAmount(1) at
 * :4665 is worth exactly one stack -- there is no cell anywhere in Spell.dbc that says "two".
 * emit_header counts those effects on the record it just emitted and writes `total - counted`,
 * dropping the row entirely when that is zero. So Twin Slice and Fel Fireball, whose +1 is
 * genuinely data, are absent from the table and cost this file nothing at run time.
 *
 * THREE PROPERTIES OF THE felfury RECORD THIS FILE ASSUMES (port-plan.md 4.C1, 7.1):
 *   * NOT SPELL_ATTR0_PASSIVE. Aura::CanBeSentToClient (SpellAuras.cpp:1088-1091) is
 *     `!IsPassive() || ...`, so a passive Felfury would have no client aura slot at all: no icon,
 *     no stack count, and nothing for the addon's UnitAura poll to read.
 *   * SPELL_ATTR0_NO_AURA_CANCEL, so a player cannot right-click their own resource off.
 *   * CumulativeAura = FELFURY_STACK_CEILING, which must be the FULLY TALENTED maximum
 *     (FELFURY_MAX_STACKS plus the best Fel Addict rank) and not FELFURY_MAX_STACKS. The +1
 *     generation path is pure data and it goes through Aura::ModStackAmount, which clamps
 *     against the DBC cell at SpellAuras.cpp:973-980. A ceiling equal to FELFURY_MAX_STACKS
 *     makes Fel Addict silently do nothing. The static assert below is what turns that into a
 *     build error instead of a shrug in game; emit_header checks the same thing against the
 *     record, so the two halves cannot disagree.
 */

#include "demon_hunter.h"

#include "SpellAuras.h"     // Aura::{GetStackAmount,ModStackAmount,SetStackAmount,SetDuration}
#include "SpellMgr.h"       // sSpellMgr->GetFirstSpellInChain

#include <algorithm>
#include <array>
#include <cstddef>

namespace
{
    // =========================================================================================
    // COMPILE-TIME CHECKS ON THE GENERATED TABLES
    // =========================================================================================
    //
    // Every one of these is a mistake the generator can make that produces NO log line and no
    // crash -- just an ability that quietly never charges, or a talent that quietly does nothing.
    // Cheaper as a build error. Same argument as DhProgressionIsWellFormed (demon_hunter.h:68).

    constexpr bool FelswornSpellIdInRange(uint32 spellId)
    {
        return spellId >= FELSWORN_SPELL_ID_MIN && spellId < FELSWORN_SPELL_ID_MAX;
    }

    template<std::size_t N>
    constexpr bool FelfuryFlowsAreWellFormed(std::array<DhFelfuryFlow, N> const& table)
    {
        for (std::size_t i = 0; i < N; ++i)
        {
            if (!FelswornSpellIdInRange(table[i].spellId))
                return false;

            // A zero is never meaningful in any of the three tables: a spender that costs
            // nothing is not a spender, a Fel Addict rank that raises the cap by nothing is not
            // a talent, and emit_header drops a generator whose share is zero rather than
            // emitting a row that would make this file do arithmetic to reach a no-op.
            if (table[i].stacks == 0 || table[i].stacks > FELFURY_STACK_CEILING)
                return false;

            for (std::size_t j = 0; j < i; ++j)
                if (table[j].spellId == table[i].spellId)
                    return false;
        }

        return true;
    }

    template<std::size_t N>
    constexpr bool FelfuryFlowsContain(std::array<DhFelfuryFlow, N> const& table, uint32 spellId)
    {
        for (std::size_t i = 0; i < N; ++i)
            if (table[i].spellId == spellId)
                return true;

        return false;
    }

    template<std::size_t N>
    constexpr uint8 LargestStackCell(std::array<DhFelfuryFlow, N> const& table)
    {
        uint8 best = 0;
        for (std::size_t i = 0; i < N; ++i)
            if (table[i].stacks > best)
                best = table[i].stacks;

        return best;
    }

    static_assert(FELFURY_MAX_STACKS >= 1,
        "FELFURY_MAX_STACKS of 0 means every spender is permanently unaffordable");

    static_assert(INNER_DEMON_MS_PER_FELFURY > 0,
        "INNER_DEMON_MS_PER_FELFURY of 0 makes Inner Demon expire on the tick it is entered");

    static_assert(FelswornSpellIdInRange(FELFURY_SPELL_ID) &&
                  FelswornSpellIdInRange(INNER_DEMON_SPELL_ID),
        "the id plan moved -- FELFURY_SPELL_ID / INNER_DEMON_SPELL_ID are outside the band the "
        "cheap first test in OnSpellCast and OnSpellCheckCast filters on");

    static_assert(FELFURY_STACK_CEILING >= FELFURY_MAX_STACKS + LargestStackCell(kDhFelAddictRanks),
        "the felfury record's CumulativeAura cannot hold a fully talented pool: the data +1 path "
        "clamps against it at SpellAuras.cpp:973-980, so Fel Addict would silently do nothing");

    static_assert(FelfuryFlowsAreWellFormed(kDhFelfuryGenerators),
        "kDhFelfuryGenerators has an out-of-band id, a zero grant, or a duplicate rank-1 id");

    static_assert(FelfuryFlowsAreWellFormed(kDhFelfurySpenders),
        "kDhFelfurySpenders has an out-of-band id, a zero cost, or a duplicate rank-1 id");

    static_assert(FelfuryFlowsAreWellFormed(kDhFelAddictRanks),
        "kDhFelAddictRanks has an out-of-band talent id, a zero bonus, or a duplicate");

    // Inner Demon is the one spender whose cost is not a constant -- it eats the whole pool -- so
    // it is handled on its own path. A row in kDhFelfurySpenders would debit it twice.
    static_assert(!FelfuryFlowsContain(kDhFelfurySpenders, INNER_DEMON_SPELL_ID),
        "Inner Demon must not be in kDhFelfurySpenders: its cost is the whole pool, not a cell");

    // GrantFelfury casts FELFURY_SPELL_ID, which re-enters OnSpellCast. That terminates today
    // because the resource is in neither table; a row here would make it a self-feeding loop.
    static_assert(!FelfuryFlowsContain(kDhFelfuryGenerators, FELFURY_SPELL_ID) &&
                  !FelfuryFlowsContain(kDhFelfurySpenders, FELFURY_SPELL_ID),
        "the felfury record itself must not be a generator or a spender -- GrantFelfury casts it");

    // =========================================================================================
    // C1 -- THE RESOURCE
    // =========================================================================================

    Aura* FelfuryAura(Unit const* unit)
    {
        // Keyed on the caster GUID even though nothing else can apply this record: it is free,
        // and it means a future raid-wide Felfury-granting effect cannot be read as the owner's
        // own pool by accident.
        return unit->GetAura(FELFURY_SPELL_ID, unit->GetGUID());
    }

    // Deliberately GetStackAmount and NOT Unit::GetAuraCount. GetAuraCount (Unit.cpp:5954-5968)
    // counts a stack-0 application as ONE, so an aura mid-removal would read as a phantom charge
    // -- and a phantom charge is a spender that fires and then debits nothing.
    uint8 FelfuryStacks(Unit const* unit)
    {
        Aura const* felfury = FelfuryAura(unit);
        return felfury ? felfury->GetStackAmount() : uint8(0);
    }

    /*
     * The talent-aware ceiling.
     *
     * Fel Addict (300487 / 300488) is `aura 107 SPELL_AURA_ADD_FLAT_MODIFIER, EffectMiscValue 31`
     * on Ascension -- and SpellModOp 31 DOES NOT EXIST here. SpellDefines.h:109 stops at 30 with
     * `#define MAX_SPELLMOD 32`, so a mod carrying op 31 is written into an array slot nothing
     * ever reads. That is why the cap is arithmetic in this function rather than a cell.
     *
     * max() and not a sum, because a talent RANK is a spell rank: Player::addSpell deactivates
     * the lower rank when the higher one is learned, so at most one of these auras is ever
     * applied and the generator writes the CUMULATIVE bonus into each rank's cell
     * (port-plan.md 3.4). max() is also the right answer if that ever stops being true, which a
     * sum is not. Both Fel Addict ranks are unplaced today and the table is legitimately empty.
     */
    uint8 EffectiveFelfuryCap(Player const* player)
    {
        // Falling back to the generated value on a 0, for the reason given on
        // InnerDemonMsPerFelfury: a cap of zero has no reading other than "typo", and the one it
        // would produce is Aura::SetStackAmount(0) below -- an aura that is applied, visible, and
        // holding nothing, which is worse than any behaviour an operator could have meant.
        uint32 cap = sDemonHunterConfig.FelfuryMaxStacks ? sDemonHunterConfig.FelfuryMaxStacks
                                                         : FELFURY_MAX_STACKS;

        uint8 bonus = 0;
        for (auto const& rank : kDhFelAddictRanks)
            if (player->HasAura(rank.spellId))
                bonus = std::max(bonus, rank.stacks);

        cap += bonus;

        // Clamping to the DBC cell rather than trusting the knob. Raising Felfury.MaxStacks past
        // CumulativeAura cannot work: the pure-data +1 goes through ModStackAmount, which clamps
        // there (SpellAuras.cpp:973-980), so the pool would sit one short of the configured cap
        // forever and only the scripted multi-grants could reach it. Clamping here makes the knob
        // honest about its own range instead of half-working.
        return uint8(std::min<uint32>(cap, FELFURY_STACK_CEILING));
    }

    /*
     * Enforce the talent-aware ceiling on whatever the pool currently holds.
     *
     * CALLED FROM THE AURA HOOK AND NOT FROM THE CAST HOOK, and that is the fix for a real
     * ordering bug rather than a preference. The obvious place to clamp is OnSpellCast, right
     * after a generator resolves -- but OnSpellCast does not run after the generator's effects
     * on every spell. Spell::_cast (Spell.cpp:3999) only calls handle_immediate() for a spell
     * with `Speed == 0`; a spell with a travel time is put into SPELL_STATE_DELAYED and EVERY
     * one of its effects, including a TARGET_UNIT_CASTER `Effect 64 -> felfury`, runs later in
     * Spell::handle_delayed (:4155) -- long after sScriptMgr->OnSpellCast at :4077. Fel Fireball
     * is the ranged generator and is exactly that shape. Clamping at cast time would therefore
     * clamp before the data +1 landed, and an untalented player would finish one stack above
     * their own cap.
     *
     * The aura hook has no such ordering to get wrong: it fires whenever the pool actually
     * changes through the aura system, whichever half of the grant caused it. Both halves are
     * covered because the hook fires on a REFRESH as well as a first application --
     * Unit::_TryStackingOrRefreshingExistingAura calls sScriptMgr->OnAuraApply at Unit.cpp:4666,
     * immediately after its ModStackAmount(1), and Unit::_ApplyAura calls it at :4807.
     *
     * The clamp cannot recurse. SetStackAmount is HandleAuraSpecificMods plus
     * AuraEffect::ChangeAmount (SpellAuras.cpp:942-966) and neither body contains a
     * sScriptMgr->OnAuraApply call, so nothing re-enters the hook that called this.
     */
    void ClampFelfuryToCap(Player* player, Aura* felfury)
    {
        uint8 const ceiling = EffectiveFelfuryCap(player);
        if (felfury->GetStackAmount() > ceiling)
            felfury->SetStackAmount(ceiling);
    }

    /*
     * Re-derive the Felfury aura's three carrier amounts from the player's CURRENT spell mods.
     *
     * WHY THIS FUNCTION HAS TO EXIST -- and it is the single least obvious thing in the file.
     *
     * The felfury record carries three haste effects (auras 216 HASTE_SPELLS, 192
     * MOD_MELEE_RANGED_HASTE, and a legal substitute for the unimplemented 214) at
     * EffectBasePoints -1 / DieSides 1, i.e. amount ZERO. They are inert carriers. Felheart
     * (301287) is SPELL_AURA_ADD_FLAT_MODIFIER with EffectMiscValue 8 = SPELLMOD_ALL_EFFECTS at
     * amount 1, and its entire job is to raise those zeros to 1% each.
     *
     * The per-stack scaling is then free, twice over:
     *   * SpellEffectInfo::CalcValue applies the mod (SpellInfo.cpp:459 calls
     *     Unit::ApplyEffectModifiers, Unit.cpp:11555, whose first act at :11559 is the
     *     SPELLMOD_ALL_EFFECTS pass), so each carrier computes 0 + 1 = 1;
     *   * AuraEffect::CalculateAmount ENDS with `amount *= GetBase()->GetStackAmount();`
     *     (SpellAuraEffects.cpp:580), and Aura::SetStackAmount re-runs CalculateAmount for every
     *     effect on every stack change (SpellAuras.cpp:957-959).
     * So gaining and spending Felfury already moves the haste with no help from us.
     *
     * WHAT IS NOT FREE is learning or unlearning Felheart while the aura is already up.
     * AuraEffect::ApplySpellMod exists to re-apply exactly this kind of passive recalculation,
     * but its loop is gated on `(aura->IsPassive() || aura->IsPermanent())`
     * (SpellAuraEffects.cpp:850) -- and Felfury is DELIBERATELY neither. It is non-passive
     * because Aura::CanBeSentToClient (SpellAuras.cpp:1088) would otherwise deny it a client aura
     * slot, and it has a real DurationIndex so the pool decays, so IsPermanent() (which tests
     * GetMaxDuration() == -1, SpellAuras.h:139) is false too. The core therefore walks straight
     * past it and the haste stays at zero until the next stack change happens to recompute it.
     * Spending a talent point and seeing no haste until you swing is the bug this prevents.
     *
     * Aura::SetStackAmount(GetStackAmount()) and not AuraEffect::RecalculateAmount(), for two
     * reasons:
     *   * RecalculateAmount early-returns on !CanBeRecalculated() (SpellAuraEffects.h:76-77), and
     *     AuraEffect::SetAmount clears that flag permanently (:66). One ChangeAmount call with
     *     mark = true, from anywhere in the core, would silently disable the path forever.
     *   * SetStackAmount (SpellAuras.cpp:942-966) is unconditional and does the WHOLE job:
     *     HandleAuraSpecificMods off, ChangeAmount(CalculateAmount(caster), false, true) on every
     *     effect -- the onStackOrReapply flag forces the handler to unapply and re-apply even
     *     when the number is unchanged -- HandleAuraSpecificMods on, then
     *     SetNeedClientUpdateForTargets(). It is the core's own "recompute this aura now".
     */
    void RecomputeFelfuryHaste(Unit* unit)
    {
        if (Aura* felfury = FelfuryAura(unit))
            felfury->SetStackAmount(felfury->GetStackAmount());
    }

    /*
     * Add the module's share of a generator's grant.
     *
     * `extra` is the generated cell, which is already `total - what the record grants itself`,
     * so this function adds and never subtracts. A generator whose whole grant is data has no
     * row in kDhFelfuryGenerators at all and never reaches here.
     *
     * The ceiling is enforced here as well as in ClampFelfuryToCap because this path is a script
     * action at a known moment, and leaving it to the aura hook would mean a multi-grant sat
     * above the cap until something else touched the pool -- ModStackAmount clamps against the
     * DBC ceiling (SpellAuras.cpp:973-980), which is the FULLY TALENTED maximum, not this
     * player's.
     */
    void GrantFelfury(Player* player, uint8 extra)
    {
        if (!extra)
            return;

        Aura* felfury = FelfuryAura(player);

        if (!felfury)
        {
            player->CastSpell(player, FELFURY_SPELL_ID, true);

            felfury = FelfuryAura(player);
            if (!felfury)
            {
                LOG_ERROR("module.demon_hunter",
                    "Felfury: casting {} on player {} produced no aura. The record is missing "
                    "from spell_dbc, or something is immune to it. Every spender is now "
                    "unaffordable for this character.",
                    FELFURY_SPELL_ID, player->GetGUID().ToString());
                return;
            }

            // The cast itself is the first stack (Aura ctor, SpellAuras.cpp:357 m_stackAmount(1)).
            --extra;
        }

        // ModStackAmount and not SetStackAmount for the increase: it is the path that refreshes
        // the duration and the charges (SpellAuras.cpp:988-998), which is what "generating"
        // Felfury has to mean, and it clamps at FELFURY_STACK_CEILING on the way.
        if (extra)
            felfury->ModStackAmount(int32(extra));

        ClampFelfuryToCap(player, felfury);
    }

    // Returns how many stacks were actually taken, which is not always `cost` -- see the caller.
    uint8 SpendFelfury(Player* player, uint8 cost)
    {
        Aura* felfury = FelfuryAura(player);
        if (!felfury)
            return 0;

        uint8 const spent = std::min<uint8>(felfury->GetStackAmount(), cost);
        if (!spent)
            return 0;

        // ModStackAmount even for a full debit: it Remove()s the aura itself the moment the count
        // reaches zero (SpellAuras.cpp:982-986), so one entry point covers both cases and the
        // "spend" path is identical whether or not the pool empties. NOTE the aura may be gone
        // when this returns -- nothing below may touch `felfury`.
        felfury->ModStackAmount(-int32(spent));
        return spent;
    }

    // The rank-1 id of a chain, so the generated tables carry ONE row per ability instead of one
    // per rank. Sargeron Smite alone has nine (port-plan.md 2.1). SpellMgr::GetFirstSpellInChain
    // (SpellMgr.cpp:603-609) returns the argument unchanged when the spell is not in a chain, so
    // this is correct for the single-record abilities and for every talent too.
    //
    // It depends on the `spell_ranks` rows tools/dhspells.py emits from plan.rank_chains; without
    // them every rank above 1 would fall out of both tables and silently cost and grant nothing.
    // emit_header checks that each multi-rank spender has a chain, so that dependency is a
    // generator failure rather than a run-time surprise.
    uint32 FelswornRankOne(uint32 spellId)
    {
        return sSpellMgr->GetFirstSpellInChain(spellId);
    }

    template<std::size_t N>
    DhFelfuryFlow const* FindFlow(std::array<DhFelfuryFlow, N> const& table, uint32 spellId)
    {
        for (auto const& entry : table)
            if (entry.spellId == spellId)
                return &entry;

        return nullptr;
    }

    // =========================================================================================
    // C2 -- INNER DEMON
    // =========================================================================================
    //
    // FORM 23, NOT 56, AND 56 IS NOT A CHOICE.
    //
    // Ascension's 804216 is SPELL_AURA_MOD_SHAPESHIFT with EffectMiscValue = 56. A form number
    // above 32 can be ENTERED -- Unit::SetShapeshiftForm writes a byte -- but no spell in the
    // game can ever require or exclude it, which makes it useless for the twenty form-gated
    // dependants this class has:
    //
    //   * SpellInfo::Stances and SpellInfo::StancesNot are `uint32` (SpellInfo.h:357-358);
    //   * SpellInfo::CheckShapeshift builds `uint32 stanceMask = (form ? 1 << (form - 1) : 0);`
    //     (SpellInfo.cpp:1452). For form 56 that is `1 << 55`, which cannot set a bit in a uint32
    //     at all -- it is undefined behaviour on `int` and there is no wider column to hold the
    //     answer even if it were not.
    //
    // Form 23 is the blank SpellShapeshiftForm.dbc row dh_spec.SHAPESHIFT_FORM_ID already
    // reserves, and its mask bit `1 << 22 = 0x400000` makes "Inner Demon only" a free DBC gate on
    // twenty talents with no code at all (port-plan.md 4.C2).
    //
    // KNOWN AND ACCEPTED, inherited from the Demon Hunter: form 23 is absent from the switch in
    // AuraEffect::HandleAuraModShapeshift, so every enter and every leave logs
    // "Auras: Unknown Shapeshift Type: 23" (SpellAuraEffects.cpp:2040). It is noise and nothing
    // else, and the two things that could have made it worse both fall the right way -- the
    // `default:` branch leaves PowerType at POWER_MANA so the setPowerType block at :2085 is
    // skipped entirely, and form 23 is not in the movement-aura-stripping switch that ends at
    // :2072, so RemoveAurasByShapeShift never runs and the Felfury pool survives the
    // transformation. Player::InitDataForForm's own `default:` then restores ChrClasses.powerType
    // (Player.cpp:10781-10787), which is why the Energy bar is still there inside the form.

    // The static_assert above only covers the COMPILED default. `InnerDemon.MsPerFelfury = 0` in
    // the .conf is a typo with no useful reading -- unlike DemonHunter.DualWieldLevel, where 0 is
    // a deliberate off position -- and it would ship a form that expires on the tick it is
    // entered, with nothing logged. Fall back to the generated value rather than honour it.
    uint32 InnerDemonMsPerFelfury()
    {
        uint32 const configured = sDemonHunterConfig.InnerDemonMsPerFelfury;
        return configured ? configured : INNER_DEMON_MS_PER_FELFURY;
    }

    int32 InnerDemonDurationFor(uint8 felfurySpent)
    {
        return int32(felfurySpent) * int32(InnerDemonMsPerFelfury());
    }

    // The most form a re-cast may accumulate: one full pool's worth. Re-entering ADDS to what is
    // left (OnCalcMaxDuration below) because Ascension's model is additive -- all four of the
    // deferred extenders add to a running form -- and additive with no ceiling is a permanent
    // one, since generating a full pool takes far less time than a full pool buys.
    int32 InnerDemonDurationCap(Player const* player)
    {
        return int32(EffectiveFelfuryCap(player)) * int32(InnerDemonMsPerFelfury());
    }

    /*
     * Consume the whole pool. The DURATION IS NOT SET HERE -- see OnCalcMaxDuration.
     *
     * That split is forced by the core and it is worth being exact about, because the obvious
     * shape (compute the duration here, after the debit, from what was spent) silently truncates
     * the form on every re-cast:
     *
     *   * a re-cast does not build a new Aura. Unit::_TryStackingOrRefreshingExistingAura finds
     *     the applied one and calls ModStackAmount(1) on it (Unit.cpp:4665), which reaches
     *     Aura::RefreshTimers (SpellAuras.cpp:856). That does `m_maxDuration = CalcMaxDuration();`
     *     at :858 and RefreshDuration() at :859, in that order;
     *   * so by the time this function runs, the time that was left on the form has ALREADY been
     *     overwritten. Adding to `form->GetDuration()` here would be adding to the number the
     *     hook just wrote, i.e. doubling it, and assigning over it would throw the remainder away.
     *
     * OnCalcMaxDuration is called from inside that same RefreshTimers, BEFORE RefreshDuration
     * replaces the value, so it is the only place in the core where both the remaining time and
     * the pool about to be spent are visible at once. It computes the whole answer; this function
     * only pays for it.
     *
     * WHICH MEANS THE DATA HALF MUST NOT SHIP A SPELLMOD_DURATION AFFECTING INNER DEMON.
     * Aura::CalcMaxDuration applies one at SpellAuras.cpp:810-811, i.e. AFTER our hook has
     * written the right answer, and nothing here can detect or undo it: by the time we run,
     * m_maxDuration and m_duration both already carry it. Ascension supplies exactly such a mod
     * from 803465 (`aura 107 ADD_FLAT_MODIFIER, misc 1 = SPELLMOD_DURATION, bp 4999 ds 1`) and it
     * must not survive the port -- not because it would double anything subtly, but because
     * Player::ApplySpellMod cannot do what Ascension does with it. It accumulates `totalflat`
     * across the matching mods and applies it exactly once (`basevalue = (basevalue + totalflat)
     * > 0 ? ... : 0` for SPELLMOD_DURATION, Player.cpp:10077-10078); there is no input to that
     * arithmetic a stack count can reach, so five Felfury and one Felfury would both get +5000 ms.
     * The multiply is engine code there and script here.
     */
    void EnterInnerDemon(Player* player, uint32 spellId)
    {
        // Looked up by the id that was actually CAST rather than by INNER_DEMON_SPELL_ID. The
        // two are the same today -- Inner Demon has one rank -- but the caller dispatched on
        // GetFirstSpellInChain, so a second rank would leave this lookup finding nothing and the
        // pool never being debited, with no log line. Same asymmetry, same fix, in
        // OnCalcMaxDuration.
        Aura* form = player->GetAura(spellId, player->GetGUID());
        if (!form)
        {
            // The cast happened but the aura did not land -- an immunity, or a linked event that
            // removed it during HandleEffects. Do NOT debit: the player got nothing, so they pay
            // nothing.
            LOG_DEBUG("module.demon_hunter",
                "Inner Demon ({}) cast by player {} left no aura; Felfury not debited.",
                spellId, player->GetGUID().ToString());
            return;
        }

        uint8 const banked = std::min<uint8>(FelfuryStacks(player), EffectiveFelfuryCap(player));
        uint8 const spent = SpendFelfury(player, banked);

        if (!spent)
        {
            /*
             * The pool emptied between CheckCast and here.
             *
             * NOT "the gate was bypassed", which is what this said before and is false: a
             * triggered cast is gated like any other. Spell::prepare calls CheckCast(true) at
             * Spell.cpp:3522 with no IsTriggered() guard at all, and ScriptMgr::OnSpellCheckCast
             * is dispatched from the top of CheckCast at :5666. `.cast` goes the same way.
             *
             * So the reachable causes are all races inside the one cast: the Felfury aura
             * expiring on its own duration, a dispel, or a linked event during handle_immediate
             * removing it. Each of those is a free transformation of the minimum duration --
             * small, but the one bug in this file a player would never report, hence the line.
             */
            LOG_WARN("module.demon_hunter",
                "Inner Demon ({}) entered by player {} with no Felfury banked -- the pool was "
                "emptied between CheckCast and cast. The form has the one-stack minimum.",
                spellId, player->GetGUID().ToString());
        }

        /*
         * The duration is OnCalcMaxDuration's answer, and this is the cheapest place to notice
         * that it never got to give one. Both ways that happens are data defects with no other
         * symptom at all -- the pool is spent and the form is simply shorter than it was paid
         * for:
         *   * SPELL_ATTR1_AURA_UNIQUE on the record makes Aura::ModStackAmount compute
         *     `refresh == false` (SpellAuras.cpp:988), so a RE-cast skips RefreshTimers at :994
         *     and therefore skips our hook entirely;
         *   * a SPELLMOD_DURATION affecting Inner Demon survived the port. Aura::CalcMaxDuration
         *     applies one at SpellAuras.cpp:810-811, AFTER our hook, and Ascension's own is
         *     803465. A negative one shortens what we wrote.
         *
         * A correct run cannot trip this. The accumulation cap is EffectiveFelfuryCap * ms and
         * `spent` never exceeds EffectiveFelfuryCap, so the floor below is always at or under
         * the cap that OnCalcMaxDuration clamps to.
         */
        int32 const minimumDuration = InnerDemonDurationFor(std::max<uint8>(spent, 1));
        if (form->GetDuration() < minimumDuration)
            LOG_ERROR("module.demon_hunter",
                "Inner Demon ({}) on player {} has {} ms left after spending {} Felfury, below "
                "the {} ms that buys. The record carries SPELL_ATTR1_AURA_UNIQUE (which makes a "
                "re-cast skip Aura::RefreshTimers and so our duration hook), or a "
                "SPELLMOD_DURATION affecting it survived the port. Both are data defects.",
                spellId, player->GetGUID().ToString(), form->GetDuration(), uint32(spent),
                minimumDuration);
    }

    /*
     * DELIBERATELY NOT IMPLEMENTED HERE, and named so the next person does not go looking.
     *
     * The four Inner Demon extenders (803089 Azzinoth's Assault +3 s, 806236 Felshock +1 s,
     * 803559 Azzinoth's Battery +1 s, 807548 Demonic Blood +0.5 s -- Ascension effects 177 and
     * 173) belong on this hook per port-plan.md 4.C2, and each is one `form->SetDuration(
     * min(form->GetDuration() + ms, InnerDemonDurationCap(player)))`. They are not written
     * because the four are NOT one shape: 803089/806236/803559 trigger on a CAST and would ride
     * kDhFelfurySpenders-style rows, while 807548 triggers on GENERATING Felfury and would have
     * to hang off GrantFelfury. Two tables, and the generator has neither. Inventing them here
     * would put the id plan in two places, which is the one thing dh_spec.py exists to prevent.
     *
     * On the same list and for the same reason: the Felfury refund rolls (705137 Azzinoth's
     * Battery, 804219 Infernal Doom, "chance not to consume"). Those two Ascension records put
     * the chance in different cells -- 705137 is `aura 42 PROC_TRIGGER_SPELL` at 10, 804219 is
     * `aura 107` at -25 -- so the generator has to normalise them onto one effect before this
     * file can read a number off either. They would go immediately before the SpendFelfury call
     * in OnSpellCast.
     */
}

/*
 * =============================================================================================
 * THE CAST-TIME GATE (C1)
 * =============================================================================================
 *
 * Called from demon_hunter_movement_allspellscript::OnSpellCheckCast, which is dispatched from
 * the very first lines of Spell::CheckCast (Spell.cpp:5664-5669) -- before the cooldown check at
 * :5672, before TakePower, and before Spell::prepare reaches TriggerGlobalCooldown at :3686. A
 * refusal written into `res` therefore returns out of prepare at :3535-3540 having cost the
 * player nothing at all. That is the identical argument already written at demon_hunter.cpp:522.
 *
 * IT GATES TRIGGERED CASTS TOO, which is a deliberate property and not an oversight.
 * Spell::prepare calls CheckCast(true) at :3521 unconditionally -- there is no IsTriggered()
 * guard -- so an internally-triggered spender that cannot afford itself is refused here. That is
 * right for a talent like 800222 The Demon Within, whose own condition is ">= 6 Felfury"; it is
 * worth knowing about for anything else, because Spell::SendCastResult rewrites the result to
 * SPELL_FAILED_DONT_REPORT whenever TRIGGERED_DONT_REPORT_CAST_ERROR is set (:4685-4686), so
 * such a refusal is completely silent.
 *
 * SPELL_FAILED_NO_POWER and not something Felfury-specific because there is nothing
 * Felfury-specific to send: SpellCastResult is Blizzard's enum (SharedDefines.h:935-1022) and the
 * client renders the string it already has. "Not enough energy" is a small lie -- the accurate
 * message is the addon's job, the same division of labour as the stack display
 * (port-plan.md 4.C1) -- and it is a better lie than SPELL_FAILED_DONT_REPORT, which would make
 * the button do nothing with no feedback whatsoever.
 */
void Felsworn::GateFelfurySpender(Spell const* spell, SpellCastResult& res)
{
    if (!spell)
        return;

    // Leave an earlier refusal alone. ScriptMgr::OnSpellCheckCast walks every enabled
    // AllSpellScript in registration order against ONE shared `res` (AllSpellScript.cpp:27-30,
    // through CALL_ENABLED_HOOKS at ScriptMgrMacros.h:72-74) -- there is no short-circuit on
    // failure, so a later script silently overwrites an earlier one's answer. This function
    // therefore only ever writes into an untouched SPELL_CAST_OK.
    if (res != SPELL_CAST_OK)
        return;

    // Cheapest test first: this hook runs on every cast by every player and every bot on the
    // realm, and two integer compares reject all of them. Both bounds come from dh_spec.py's id
    // plan, so a spell that is not this class's cannot get past here.
    uint32 const spellId = spell->GetSpellInfo()->Id;
    if (!FelswornSpellIdInRange(spellId))
        return;

    Unit* caster = spell->GetCaster();
    if (!caster)
        return;

    Player* player = caster->ToPlayer();
    if (!player)
        return;

    // Master switch, read live rather than cached -- see the comment on DemonHunterConfig. Only a
    // caster of a 91000-92999 spell ever pays for the string hash.
    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return;

    uint32 const rankOne = FelswornRankOne(spellId);

    // Inner Demon is not in the spender table -- its cost is the whole pool -- but it still has a
    // floor: entering the form on nothing would grant a free transformation of no duration.
    uint8 cost = 0;
    if (rankOne == INNER_DEMON_SPELL_ID)
        cost = 1;
    else if (DhFelfuryFlow const* spender = FindFlow(kDhFelfurySpenders, rankOne))
        cost = spender->stacks;

    if (!cost)
        return;

    if (FelfuryStacks(player) < cost)
        res = SPELL_FAILED_NO_POWER;
}

/*
 * =============================================================================================
 * DEBIT, MULTI-GRANT AND FORM ENTRY (C1 + C2)
 * =============================================================================================
 *
 * ALLSPELLHOOK_ON_CAST, dispatched from the LAST lines of Spell::_cast (Spell.cpp:4077), after
 * TakePower() at :3923. What it is NOT is "after the spell's effects", and getting that wrong is
 * how the previous version of this file grew an off-by-one:
 *
 *   * for a spell with `Speed == 0` -- everything melee, and Inner Demon -- Spell::_cast reaches
 *     handle_immediate() at :4027 and the effects really have run by the time we are called;
 *   * for a spell with a travel time, the branch at :3999 puts the cast into SPELL_STATE_DELAYED
 *     instead and does NOT call handle_immediate at all. Every effect, caster-targeted ones
 *     included, runs later from Spell::handle_delayed (:4155). Fel Fireball is that shape.
 *
 * So this hook may run before or after a generator's authored `Effect 64 -> felfury`. Nothing
 * below depends on which: the module adds its own share and the ceiling is enforced from the
 * aura hook (ClampFelfuryToCap), which fires whenever the pool actually moves.
 *
 * Inner Demon is the one place the ordering IS load-bearing, and there it holds: the form has no
 * travel time, so its aura exists -- and Aura::CalcMaxDuration, and therefore OnCalcMaxDuration
 * below, have already run -- before we debit here. Nothing is stashed between the two calls;
 * both read the pool off the aura themselves, which is what keeps the pair correct when two
 * Felsworn cast in the same tick and, more to the point, when two MAPS tick in parallel.
 */
void demon_hunter_movement_allspellscript::OnSpellCast(Spell* /*spell*/, Unit* caster,
    SpellInfo const* spellInfo, bool /*skipCheck*/)
{
    if (!caster || !spellInfo)
        return;

    uint32 const spellId = spellInfo->Id;
    if (!FelswornSpellIdInRange(spellId))
        return;

    Player* player = caster->ToPlayer();
    if (!player)
        return;

    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return;

    uint32 const rankOne = FelswornRankOne(spellId);

    if (rankOne == INNER_DEMON_SPELL_ID)
    {
        EnterInnerDemon(player, spellId);
        return;
    }

    if (DhFelfuryFlow const* generator = FindFlow(kDhFelfuryGenerators, rankOne))
    {
        // The cell is the module's share, already net of whatever the record grants itself.
        GrantFelfury(player, generator->stacks);
        return;
    }

    if (DhFelfuryFlow const* spender = FindFlow(kDhFelfurySpenders, rankOne))
    {
        uint8 const spent = SpendFelfury(player, spender->stacks);
        if (spent < spender->stacks)
            LOG_WARN("module.demon_hunter",
                "Spender {} (rank 1 {}) cast by player {} took {} of {} Felfury -- the pool was "
                "emptied between CheckCast and cast.",
                spellId, rankOne, player->GetGUID().ToString(), spent, spender->stacks);
    }
}

/*
 * Inner Demon's duration, bought with the Felfury about to be spent.
 *
 * Fires from Aura::CalcMaxDuration (SpellAuras.cpp:807), which is reached two ways and both
 * matter:
 *   * from the Aura constructor (:363) on a first application -- inside handle_immediate, BEFORE
 *     OnSpellCast debits, so the pool this reads is what is about to be spent rather than what
 *     is left;
 *   * from Aura::RefreshTimers (:858) on a re-cast, BEFORE the RefreshDuration() on the next
 *     line overwrites the time that was remaining.
 *
 * A RE-CAST THEREFORE EXTENDS THE FORM RATHER THAN REPLACING IT, and this is the only hook that
 * can make that true -- see the comment on EnterInnerDemon for why doing it after the debit is
 * not available. Extending and not `max()` because Ascension's model is additive: all four of
 * the deferred extenders add to a running form. The cap is what stops "additive" meaning
 * "permanent", since a full pool is generated in far less time than a full pool buys.
 *
 * The two entries are told apart by identity: on a refresh the aura is already in the target's
 * applied map, so Unit::GetAura (Unit.cpp:5853) hands back this very object. During the
 * constructor it is not in that map yet and the lookup misses -- which is also why m_duration is
 * never read on that path, the constructor not having assigned it at :364 yet.
 *
 * Harmless on login. Player::_LoadAuras builds the aura -- running this hook -- and then
 * overwrites m_maxDuration and m_duration from the saved row via Aura::SetLoadedState
 * (SpellAuras.cpp:1154-1157), so a character who relogs inside the form keeps the time they had
 * left rather than being re-granted a full one.
 */
void demon_hunter_movement_allspellscript::OnCalcMaxDuration(Aura const* aura, int32& maxDuration)
{
    // One dereference and two integer compares reject every other aura application on the realm;
    // only a Felsworn aura pays for the chain walk behind FelswornRankOne.
    if (!aura || !FelswornSpellIdInRange(aura->GetId()))
        return;

    if (FelswornRankOne(aura->GetId()) != INNER_DEMON_SPELL_ID)
        return;

    Unit* caster = aura->GetCaster();
    if (!caster)
        return;

    Player* player = caster->ToPlayer();
    if (!player)
        return;

    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return;

    uint8 const banked = std::min<uint8>(FelfuryStacks(player), EffectiveFelfuryCap(player));

    // max(1) rather than letting a zero through: maxDuration 0 is not "permanent" -- IsPermanent
    // tests for -1 (SpellAuras.h:139) -- it is an aura that expires on the next Unit update, and
    // a form that flickers reads as "Inner Demon is broken" rather than as "you had no Felfury".
    // The gate makes zero unreachable; EnterInnerDemon logs it if it happens anyway.
    int32 duration = InnerDemonDurationFor(std::max<uint8>(banked, 1));

    // `> 0` and not merely non-null: a form somehow left permanent (-1) must not have -1 added
    // to it, and a form on its last millisecond has nothing worth carrying.
    if (aura == player->GetAura(aura->GetId(), player->GetGUID()) && aura->GetDuration() > 0)
        duration = std::min<int32>(duration + aura->GetDuration(), InnerDemonDurationCap(player));

    maxDuration = duration;
}

/*
 * =============================================================================================
 * THE POOL'S OWN CEILING, AND FELHEART'S RECOMPUTATION (C1)
 * =============================================================================================
 *
 * A UnitScript and not a PlayerScript, because both events that matter are an AURA changing and
 * PlayerScript has no hook for one. UNITHOOK_ON_AURA_APPLY / UNITHOOK_ON_AURA_REMOVE
 * (UnitScript.h:33-34, the virtuals at :84 and :86) fire from three places, and all three are on
 * the correct side of what this script needs to see:
 *
 *   apply, first  -- Unit.cpp:4807, AFTER the `aurApp->_HandleEffect(i, true)` loop at
 *                    :4800-4805, which is what reaches AuraEffect::HandleAddModifier and
 *                    registers a spell mod. So by the time we run, Felheart's +1 is live and
 *                    CalculateAmount will see it.
 *   apply, refresh -- Unit.cpp:4666, immediately after the ModStackAmount(1) at :4665 inside
 *                    Unit::_TryStackingOrRefreshingExistingAura (:4615). This is the one that
 *                    makes the Felfury ceiling order-independent: it fires for the pure-data +1
 *                    whenever it lands, including on a delayed spell whose effects resolve after
 *                    OnSpellCast has already returned.
 *   remove        -- Unit.cpp:4900, AFTER the effects have been unapplied, so the mod is already
 *                    gone and the recomputation correctly yields zero.
 *
 * That ordering is also what makes login order irrelevant: whichever of the Felfury aura and the
 * Felheart passive is restored second, this hook fires for the second one.
 *
 * port-plan.md 6.5 puts C7's UnitScript hooks (OnBeforeRollMeleeOutcomeAgainst,
 * ModifySpellDamageTaken, ModifyMeleeDamage) on a UnitScript too; felsworn_spells.cpp registers
 * its own for them rather than adding them here, so that the file that owns a bucket owns its
 * hooks. Nothing here needs to move.
 */
class felsworn_felfury_unitscript : public UnitScript
{
public:
    // Hooks opted into EXPLICITLY -- an empty vector means "all hooks" (UnitScript.cpp:148-150),
    // which would put this script on all twenty-one UnitHook dispatch lists for the sake of two.
    // The second argument is `addToScripts`, NOT the hook list; it is easy to pass the vector
    // there by accident and get a script that registers for everything.
    felsworn_felfury_unitscript() : UnitScript("felsworn_felfury_unitscript", true,
    {
        UNITHOOK_ON_AURA_APPLY,
        UNITHOOK_ON_AURA_REMOVE
    }) { }

    void OnAuraApply(Unit* unit, Aura* aura) override
    {
        if (!unit || !aura)
            return;

        // The range test first, for the same reason every other first test in this file is a
        // pair of integer compares: this hook fires for every aura applied to every unit on the
        // realm, players, pets, bots and creatures alike.
        uint32 const spellId = aura->GetId();
        if (!FelswornSpellIdInRange(spellId))
            return;

        // Master switch, read live and only ever by a unit that just gained a 91000-92999 aura
        // -- see the comment on DemonHunterConfig. `Enable = 0` has to mean inert, and a `.cast`
        // of the resource record onto a GM is the one way one of these can exist anyway.
        if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
            return;

        if (spellId == FELFURY_SPELL_ID)
        {
            // Only the owner's own pool, matching how FelfuryAura looks it up.
            if (aura->GetCasterGUID() != unit->GetGUID())
                return;

            if (Player* player = unit->ToPlayer())
                ClampFelfuryToCap(player, aura);

            return;
        }

        if (IsFelheartRank(spellId))
            RecomputeFelfuryHaste(unit);
    }

    void OnAuraRemove(Unit* unit, AuraApplication* aurApp, AuraRemoveMode /*mode*/) override
    {
        if (!unit || !aurApp)
            return;

        // Nothing to do for the Felfury aura itself here: a removal cannot leave the pool above
        // the cap, and the aura is on its way out. IsFelheartRank does the range test, and the
        // table is empty until Felheart is placed in a tree, so this costs two compares.
        if (!IsFelheartRank(aurApp->GetBase()->GetId()))
            return;

        if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
            return;

        RecomputeFelfuryHaste(unit);
    }

private:
    static bool IsFelheartRank(uint32 spellId)
    {
        if (!FelswornSpellIdInRange(spellId))
            return false;

        for (uint32 const rank : kDhFelheartRanks)
            if (rank == spellId)
                return true;

        return false;
    }
};

void AddSC_felsworn_felfury()
{
    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process. Same convention as AddSC_demon_hunter (demon_hunter.cpp:628-641), which is
    // where this function is called from.
    //
    // Note what is NOT here: demon_hunter_movement_allspellscript is registered exactly once, by
    // AddSC_demon_hunter. This file only adds two overrides to it. Registering it a second time
    // would put it twice in every dispatch list it is enabled for, and every Felfury debit would
    // happen twice.
    new felsworn_felfury_unitscript();
}
