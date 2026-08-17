/*
 * felfury_core.cpp -- buckets C1 (Felfury accounting) and C2 (Inner Demon) of
 * .work/felsworn/port-plan.md section 4. These are the two scripts the whole class stands on:
 * every generator, every spender and the form all read and write one stacking aura, and nothing
 * else in the kit works if this file is wrong.
 *
 * Read demon_hunter.h first -- it carries the hook-name warning, the generated-table contract,
 * and the reason CLASS_DEMON_HUNTER does not exist in the checkout on disk.
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
 * `demon_hunter_movement_allspellscript` (demon_hunter.h:165, implemented demon_hunter.cpp:534,
 * registered :624) is already registered against ALLSPELLHOOK_ON_SPELL_CHECK_CAST; a parallel
 * script would mean a second entry in every one of those dispatch lists for no gain. The two new
 * overrides below are members of that same class, defined here.
 *
 * =============================================================================================
 * WHAT MUST BE ADDED ELSEWHERE BEFORE THIS FILE COMPILES
 * =============================================================================================
 *
 * 1. demon_hunter.h -- opt the existing script into the two new hooks and declare the overrides.
 *    Hooks are opted into EXPLICITLY: an empty `enabledHooks` vector means "all hooks"
 *    (AllSpellScript.cpp:96-98, and the same rule for PlayerScript at PlayerScript.cpp:967-969),
 *    which would register this script against all fourteen AllSpellHook dispatch lists for the
 *    sake of three.
 *
 *        class demon_hunter_movement_allspellscript : public AllSpellScript
 *        {
 *        public:
 *            demon_hunter_movement_allspellscript()
 *                : AllSpellScript("demon_hunter_movement_allspellscript",
 *            {
 *                ALLSPELLHOOK_ON_SPELL_CHECK_CAST,
 *                ALLSPELLHOOK_ON_CAST,                // NEW -- C1 debit/top-up, C2 form entry
 *                ALLSPELLHOOK_ON_CALC_MAX_DURATION    // NEW -- C2 duration
 *            }) { }
 *
 *            void OnSpellCheckCast(Spell* spell, bool strict, SpellCastResult& res) override;
 *            void OnSpellCast(Spell* spell, Unit* caster, SpellInfo const* spellInfo,
 *                bool skipCheck) override;                                            // NEW
 *            void OnCalcMaxDuration(Aura const* aura, int32& maxDuration) override;    // NEW
 *        };
 *
 *        struct DemonHunterConfig
 *        {
 *            ...
 *            uint8  FelfuryMaxStacks       = FELFURY_MAX_STACKS;
 *            uint32 InnerDemonMsPerFelfury = INNER_DEMON_MS_PER_FELFURY;
 *        };
 *
 *        namespace Felsworn { void GateFelfurySpender(Spell const* spell, SpellCastResult& res); }
 *        void AddSC_felsworn_felfury();
 *
 * 2. demon_hunter.cpp -- four edits, all one line each:
 *      * DemonHunterConfig::Load gains
 *            FelfuryMaxStacks       = sConfigMgr->GetOption<uint8>("Felsworn.Felfury.MaxStacks",
 *                                                                 FELFURY_MAX_STACKS);
 *            InnerDemonMsPerFelfury = sConfigMgr->GetOption<uint32>(
 *                "Felsworn.InnerDemon.MsPerFelfury", INNER_DEMON_MS_PER_FELFURY);
 *      * OnSpellCheckCast gains `Felsworn::GateFelfurySpender(spell, res);` IMMEDIATELY after the
 *        `if (!spell) return;` at demon_hunter.cpp:536-537 -- i.e. BEFORE the Double Jump / Glide
 *        id test, which returns early for everything else.
 *      * AddSC_demon_hunter() gains `AddSC_felsworn_felfury();`.
 *    The gate lives behind a free function rather than in this file's own OnSpellCheckCast
 *    because that override already has a definition in demon_hunter.cpp and a function may only
 *    be defined once. Splitting the gate out is the smaller lie than moving the falling gate,
 *    which has nothing to do with Felfury, into a file named for it.
 *
 * 3. conf/modules/mod_demon_hunter.conf (and the .conf.dist beside it) gain
 *    `Felsworn.Felfury.MaxStacks` and `Felsworn.InnerDemon.MsPerFelfury`. On this deployment
 *    deploy/docker-compose.yml bind-mounts conf/modules over the image's copy, so a key that is
 *    only in the .dist is a key that does not exist -- see the comment on DemonHunterConfig::Load.
 *
 * =============================================================================================
 * WHAT tools/dhspells.py MUST EMIT INTO dh_progression.h (port-plan.md 6.4)
 * =============================================================================================
 *
 *     constexpr uint32 FELSWORN_SPELL_ID_MIN;       // dh_spec.SPELL_ID_BASE,       91000
 *     constexpr uint32 FELSWORN_SPELL_ID_MAX;       // dh_spec.TALENT_SPELL_ID_MAX, 93000, EXCL
 *     constexpr uint32 FELFURY_SPELL_ID;            // spell_id_for("felfury", 0),     91460
 *     constexpr uint32 INNER_DEMON_SPELL_ID;        // spell_id_for("inner_demon", 0), 91480
 *     constexpr uint8  FELFURY_MAX_STACKS;          // dh_spec.FELFURY_MAX_STACKS,          5
 *     constexpr uint8  FELFURY_STACK_CEILING;       // the CumulativeAura cell on the record
 *     constexpr uint32 INNER_DEMON_MS_PER_FELFURY;  // dh_spec.INNER_DEMON_MS_PER_FELFURY, 5000
 *
 *     struct DhFelfuryFlow { uint32 spellId; uint8 stacks; };
 *     constexpr std::array<DhFelfuryFlow, N> kDhFelfuryGenerators;  // rank 1 id -> TOTAL granted
 *     constexpr std::array<DhFelfuryFlow, N> kDhFelfurySpenders;    // rank 1 id -> stacks eaten
 *     constexpr std::array<DhFelfuryFlow, N> kDhFelAddictRanks;     // talent id -> +max stacks
 *     constexpr std::array<uint32, N>        kDhFelheartRanks;      // talent id, ALL_EFFECTS mod
 *
 * The Dh prefix on the arrays and the struct is not decoration. mod-dk-lowlevel is statically
 * linked into the same worldserver binary; two statically-linked modules defining DIFFERENT
 * types under ONE name is an ODR violation that links without a diagnostic and misbehaves at run
 * time. Same argument as DhGrant/kDhProgression, demon_hunter.h:56-61. The SCREAMING_CASE scalars
 * are named exactly as port-plan.md 6.1 names them and are left alone for that reason.
 *
 * std::array and not a C array because a talent that gets cut leaves its table EMPTY, and
 * `constexpr DhFelfuryFlow kDhFelAddictRanks[] = {};` is ill-formed C++. Neither Felheart
 * (301287) nor Fel Addict (300487/300488) is placed in any of the three tab tables in
 * port-plan.md 3.1-3.3, so both tables being empty on the first build is the expected case, not
 * a bug.
 *
 * THREE PROPERTIES OF THE felfury RECORD THIS FILE ASSUMES (port-plan.md 4.C1, 7.1):
 *   * NOT SPELL_ATTR0_PASSIVE. Aura::CanBeSentToClient (SpellAuras.cpp:1088-1091) is
 *     `!IsPassive() || ...`, so a passive Felfury would have no client aura slot at all: no icon,
 *     no stack count, and nothing for the addon's UnitAura poll to read.
 *   * SPELL_ATTR0_NO_AURA_CANCEL, so a player cannot right-click their own resource off.
 *   * CumulativeAura = FELFURY_STACK_CEILING, which must be the FULLY TALENTED maximum
 *     (FELFURY_MAX_STACKS plus the best Fel Addict rank) and not FELFURY_MAX_STACKS. The +1
 *     generation path is pure data -- one authored `Effect_N = 64 TRIGGER_SPELL -> felfury` --
 *     and it goes through Aura::ModStackAmount, which clamps against the DBC cell at
 *     SpellAuras.cpp:973-980. A ceiling of 5 makes Fel Addict silently do nothing. The static
 *     assert below is what turns that into a build error instead of a shrug in game.
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

            // A zero is never meaningful in either table: a generator that grants nothing is not
            // a generator, a spender that costs nothing is not a spender, and the generator path
            // below subtracts the data-supplied +1 from this cell.
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
        "kDhFelAddictRanks has an out-of-band talent id or a duplicate");

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

    // How much of a generator's advertised grant arrives without this file's help: exactly one
    // stack, from the authored `Effect_N = 64 SPELL_EFFECT_TRIGGER_SPELL -> felfury` that
    // port-plan.md 4.C1 puts on every generator. Unit::_TryStackingOrRefreshingExistingAura
    // (Unit.cpp:4665) calls ModStackAmount(1) per triggered cast and there is no cell anywhere in
    // Spell.dbc that says "two" -- which is the whole reason Annihilan Strike's +2 and Burning
    // Hatred's / Blood of Mannoroth's +6 need a script at all.
    constexpr uint8 kFelfuryStacksFromData = 1;

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
     * (port-plan.md 3.4, dhspells.py:878). max() is also the right answer if that ever stops
     * being true, which a sum is not.
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
     *   * SpellEffectInfo::CalcValue applies the mod (SpellInfo.cpp:459 ->
     *     Unit::ApplyEffectModifiers -> Unit.cpp:11559, SPELLMOD_ALL_EFFECTS), so each carrier
     *     computes 0 + 1 = 1;
     *   * AuraEffect::CalculateAmount ENDS with `amount *= GetBase()->GetStackAmount();`
     *     (SpellAuraEffects.cpp:580), and Aura::SetStackAmount re-runs CalculateAmount for every
     *     effect on every stack change (SpellAuras.cpp:957-959).
     * So gaining and spending Felfury already moves the haste with no help from us.
     *
     * WHAT IS NOT FREE is learning or unlearning Felheart while the aura is already up.
     * AuraEffect::ApplySpellMod exists to re-apply exactly this kind of passive recalculation,
     * but its loop is gated on `(aura->IsPassive() || aura->IsPermanent())`
     * (SpellAuraEffects.cpp:850-852) -- and Felfury is DELIBERATELY neither. It is non-passive
     * because Aura::CanBeSentToClient (SpellAuras.cpp:1088) would otherwise deny it a client aura
     * slot, and it has a real DurationIndex so the pool decays, so IsPermanent() is false too.
     * The core therefore walks straight past it and the haste stays at zero until the next stack
     * change happens to recompute it. Spending a talent point and seeing no haste until you swing
     * is the bug this function prevents.
     *
     * Aura::SetStackAmount(GetStackAmount()) and not AuraEffect::RecalculateAmount(), for two
     * reasons:
     *   * RecalculateAmount early-returns on !CanBeRecalculated() (SpellAuraEffects.h:76-78), and
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
     * Add `extra` stacks on top of whatever the authored Effect 64 already granted, then enforce
     * the talent-aware ceiling.
     *
     * `extra == 0` is MEANINGFUL and not a no-op: it is how a plain +1 generator, whose entire
     * grant came from data, still gets the ceiling enforced. The DBC cell is the fully-talented
     * maximum, so an untalented player who casts a generator at cap would otherwise walk past it.
     */
    void GrantFelfury(Player* player, uint8 extra)
    {
        Aura* felfury = FelfuryAura(player);

        if (!felfury)
        {
            // The data half did not land. With nothing to top up there is nothing to do and
            // nothing to clamp -- and no log line either, because the only way here is a
            // generator whose authored Effect 64 is missing, which is a data defect that the
            // generator's own checks (port-plan.md 6.4 item 5) are the right place to catch.
            if (!extra)
                return;

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

        uint8 const ceiling = EffectiveFelfuryCap(player);
        if (felfury->GetStackAmount() > ceiling)
            felfury->SetStackAmount(ceiling);
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
    // this is correct for the single-record abilities too. It depends on the `spell_ranks` rows
    // that port-plan.md 6.4 item 1 adds to the generator; without them every rank above 1 falls
    // out of both tables and silently costs and grants nothing.
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
    // skipped entirely, and form 23 is not in the movement-aura-stripping switch at :2072, so
    // RemoveAurasByShapeShift never runs and the Felfury pool survives the transformation.
    // Player::InitDataForForm's own `default:` then restores ChrClasses.powerType
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

    /*
     * Consume the whole pool and set the form's duration from what was consumed.
     *
     * WHY THIS IS A SCRIPT AND NOT A CELL, which is the single most misread number in the family:
     * Ascension supplies the duration from 803465, `aura 107 ADD_FLAT_MODIFIER, misc 1 =
     * SPELLMOD_DURATION, bp 4999 ds 1` = +5000 ms, and MULTIPLIES it by the Felfury spent.
     * Player::ApplySpellMod cannot do that. It accumulates `totalflat` across the matching mods
     * and applies it exactly once -- `basevalue = (basevalue + totalflat) > 0 ? ... : 0` for
     * SPELLMOD_DURATION at Player.cpp:10077-10078 -- and there is no input to that arithmetic
     * that a stack count could reach. Five Felfury and one Felfury would both yield +5000 ms.
     *
     * THE DATA HALF MUST THEREFORE NOT SHIP A SPELLMOD_DURATION ON INNER DEMON. If one survives
     * the port it is applied by Aura::CalcMaxDuration at SpellAuras.cpp:810-811, i.e. AFTER our
     * OnCalcMaxDuration hook has already written the right answer, and it would add a flat 5000
     * on top of every duration. The explicit SetMaxDuration/SetDuration below is what makes a
     * stray one harmless rather than a five-second bonus nobody can find.
     */
    void EnterInnerDemon(Player* player)
    {
        Aura* form = player->GetAura(INNER_DEMON_SPELL_ID, player->GetGUID());
        if (!form)
        {
            // The cast happened but the aura did not land -- an immunity, or a linked event that
            // removed it during HandleEffects. Do NOT debit: the player got nothing, so they pay
            // nothing. This is a real ordering property and not defensive noise; see the comment
            // on OnSpellCast for why the aura already exists by the time this runs.
            LOG_DEBUG("module.demon_hunter",
                "Inner Demon ({}) cast by player {} left no aura; Felfury not debited.",
                INNER_DEMON_SPELL_ID, player->GetGUID().ToString());
            return;
        }

        uint8 const banked = std::min<uint8>(FelfuryStacks(player), EffectiveFelfuryCap(player));
        uint8 const spent = SpendFelfury(player, banked);

        if (!spent)
        {
            // Only reachable if the cast bypassed GateFelfurySpender -- a `.cast`, a triggered
            // cast, or a future auto-enter talent (800222 The Demon Within). Worth a line: it
            // means free demon-form uptime, which is the one bug in this file a player would
            // never report.
            LOG_WARN("module.demon_hunter",
                "Inner Demon ({}) entered by player {} with no Felfury banked -- the cast-time "
                "gate was bypassed. Falling back to one Felfury's worth of duration.",
                INNER_DEMON_SPELL_ID, player->GetGUID().ToString());
        }

        int32 const duration = InnerDemonDurationFor(std::max<uint8>(spent, 1));

        // SetMaxDuration first so the client's buff timer is drawn against the right total, then
        // SetDuration -- which is the one that calls SetNeedClientUpdateForTargets
        // (SpellAuras.cpp:815-825). withMods stays false: applying SPELLMOD_DURATION here is
        // exactly the double-count the comment above is about.
        form->SetMaxDuration(duration);
        form->SetDuration(duration);
    }

    /*
     * DELIBERATELY NOT IMPLEMENTED HERE, and named so the next person does not go looking.
     *
     * The four Inner Demon extenders (803089 Azzinoth's Assault +3 s, 806236 Felshock +1 s,
     * 803559 Azzinoth's Battery +1 s, 807548 Demonic Blood +0.5 s -- Ascension effects 177 and
     * 173) belong on this hook per port-plan.md 4.C2, and each is one `form->SetDuration(
     * form->GetDuration() + ms)` guarded by a cap. They are not written because the four are NOT
     * one shape: 803089/806236/803559 trigger on a CAST and would ride kDhFelfurySpenders-style
     * rows, while 807548 triggers on GENERATING Felfury and would have to hang off GrantFelfury.
     * Two tables, and the generator has neither. Inventing them here would put the id plan in
     * two places, which is the one thing dh_spec.py exists to prevent.
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
 * refusal written into `res` therefore returns out of prepare at :3538-3541 having cost the
 * player nothing at all. That is the identical argument already written at demon_hunter.cpp:516.
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
    // AllSpellScript in registration order against ONE shared `res` (AllSpellScript.cpp:27-30) --
    // there is no short-circuit on failure, so a later script silently overwrites an earlier one's
    // answer. This function therefore only ever writes into an untouched SPELL_CAST_OK.
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
 * ALLSPELLHOOK_ON_CAST, dispatched from the LAST lines of Spell::_cast (Spell.cpp:4077). The
 * position in that function is what makes this hook the right one, and it is worth being precise
 * about because the whole of C2 depends on it:
 *
 *     TakePower()            Spell.cpp:3923   the Energy half of the cost is already gone
 *     handle_immediate()     Spell.cpp:4027   effects run -- the authored Effect 64 has already
 *                                             granted its +1, and Inner Demon's aura already
 *                                             EXISTS, so Aura::CalcMaxDuration and therefore
 *                                             OnCalcMaxDuration below have ALREADY run
 *     sScriptMgr->OnSpellCast(...)            <- here
 *
 * So OnCalcMaxDuration reads the pool BEFORE it is debited and this function debits it after.
 * Nothing is stashed between the two calls: both read the stack count off the aura themselves,
 * which is what keeps the pair correct when two Felsworn cast in the same tick. A member variable
 * holding "the last n" would not be.
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
        EnterInnerDemon(player);
        return;
    }

    if (DhFelfuryFlow const* generator = FindFlow(kDhFelfuryGenerators, rankOne))
    {
        // The table cell is the TOTAL the ability advertises; the authored Effect 64 has already
        // delivered kFelfuryStacksFromData of it. `stacks >= 1` is a static_assert above, so this
        // subtraction cannot wrap.
        GrantFelfury(player, uint8(generator->stacks - kFelfuryStacksFromData));
        return;
    }

    if (DhFelfuryFlow const* spender = FindFlow(kDhFelfurySpenders, rankOne))
    {
        uint8 const spent = SpendFelfury(player, spender->stacks);
        if (spent < spender->stacks)
            LOG_WARN("module.demon_hunter",
                "Spender {} (rank 1 {}) cast by player {} took {} of {} Felfury -- the cast-time "
                "gate did not run, or the pool was emptied between CheckCast and cast.",
                spellId, rankOne, player->GetGUID().ToString(), spent, spender->stacks);
    }
}

/*
 * Inner Demon's duration, computed from the Felfury about to be spent.
 *
 * Fires from Aura::CalcMaxDuration (SpellAuras.cpp:807), which runs from the Aura constructor
 * (:363) -- i.e. inside handle_immediate, BEFORE OnSpellCast debits. Reading the pool here is
 * therefore reading what is about to be spent, not what is left.
 *
 * The value is written again by EnterInnerDemon after the debit, and both writes exist on
 * purpose: this one is what the client's buff timer is first drawn from, and that one is what
 * survives a stray SPELLMOD_DURATION being applied at SpellAuras.cpp:810-811 after this hook
 * returns.
 *
 * Harmless on login. Player::_LoadAuras builds the aura -- running this hook -- and then
 * overwrites m_maxDuration and m_duration from the saved row via Aura::SetLoadedState
 * (SpellAuras.cpp:1154-1157), so a character who relogs inside the form keeps the time they had
 * left rather than being re-granted a full one.
 */
void demon_hunter_movement_allspellscript::OnCalcMaxDuration(Aura const* aura, int32& maxDuration)
{
    // One dereference and one compare rejects every other aura application on the realm.
    if (!aura || aura->GetId() != INNER_DEMON_SPELL_ID)
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
    maxDuration = InnerDemonDurationFor(std::max<uint8>(banked, 1));
}

/*
 * =============================================================================================
 * FELHEART'S RECOMPUTATION (C1)
 * =============================================================================================
 *
 * A UnitScript and not a PlayerScript, because the event that matters is an AURA changing and
 * PlayerScript has no hook for one. UNITHOOK_ON_AURA_APPLY / UNITHOOK_ON_AURA_REMOVE
 * (UnitScript.h:33-34) fire at Unit.cpp:4807 and :4900, and both are on the correct side of the
 * spell mod:
 *
 *   * apply  -- :4807 is AFTER the `aurApp->_HandleEffect(i, true)` loop at :4800-4805, which is
 *               what reaches AuraEffect::HandleAddModifier and registers the mod. So by the time
 *               we run, Felheart's +1 is live and CalculateAmount will see it.
 *   * remove -- :4900 is AFTER the effects have been unapplied, so the mod is already gone and
 *               the recomputation correctly yields zero.
 *
 * That ordering is also what makes login order irrelevant: whichever of the Felfury aura and the
 * Felheart passive is restored second, this hook fires for the second one.
 *
 * port-plan.md 6.5 puts C7's UnitScript hooks (OnBeforeRollMeleeOutcomeAgainst,
 * ModifySpellDamageTaken, ModifyMeleeDamage) on this same class rather than on a second one.
 * They are added to the enabledHooks list below when that bucket lands; nothing here needs to
 * move for them.
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

        if (IsFelheartRank(aura->GetId()))
            RecomputeFelfuryHaste(unit);
    }

    void OnAuraRemove(Unit* unit, AuraApplication* aurApp, AuraRemoveMode /*mode*/) override
    {
        if (!unit || !aurApp)
            return;

        if (IsFelheartRank(aurApp->GetBase()->GetId()))
            RecomputeFelfuryHaste(unit);
    }

private:
    // The range test first, for the same reason every other first test in this file is a pair of
    // integer compares: these two hooks fire for every aura applied to and removed from every
    // unit on the realm, players, pets, bots and creatures alike.
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
    // of the process. Same convention as AddSC_demon_hunter (demon_hunter.cpp:618-625), which is
    // where this function is called from.
    //
    // Note what is NOT here: demon_hunter_movement_allspellscript is registered exactly once, by
    // AddSC_demon_hunter. This file only adds two overrides to it. Registering it a second time
    // would put it twice in every dispatch list it is enabled for, and every Felfury debit would
    // happen twice.
    new felsworn_felfury_unitscript();
}
