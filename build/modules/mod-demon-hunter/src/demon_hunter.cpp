/*
 * mod-demon-hunter -- the Demon Hunter as a REAL player class, class id 10.
 *
 * Read demon_hunter.h first; it carries the hook-name warning, the generated-table contract and
 * the reason CLASS_DEMON_HUNTER does not exist in the checkout on disk.
 */

#include "demon_hunter.h"

DemonHunterConfig sDemonHunterConfig;

void DemonHunterConfig::Load()
{
    // These defaults MUST match conf/mod_demon_hunter.conf.dist value for value.
    //
    // deploy/docker-compose.yml bind-mounts ../conf/modules over /opt/ac/etc/modules as a
    // DIRECTORY, which shadows the image's installed .conf.dist files entirely, and
    // ConfigMgr::LoadModulesConfigs only ever opens `<name>.conf` -- never `<name>.conf.dist`.
    // So a key absent from conf/modules/mod_demon_hunter.conf silently falls back to the literal
    // below, not to the .dist. That is why every knob is listed in the repo's .conf as well.
    DualWieldLevel = sConfigMgr->GetOption<uint8>("DemonHunter.DualWieldLevel", 1);
    ParryLevel     = sConfigMgr->GetOption<uint8>("DemonHunter.ParryLevel", 1);
    GrantRacials   = sConfigMgr->GetOption<bool>("DemonHunter.GrantRacials", true);
}

namespace
{
    /*
     * THE THREE SPELLS THE CLASS CANNOT OBTAIN ANY OTHER WAY.
     *
     * A Demon Hunter has no class trainer -- there is no creature on the realm whose trainer
     * template offers class 10 -- and every stock SkillLineAbility row was authored when class
     * 10 did not exist, so its ClassMask cannot contain bit 512. Both halves of the normal
     * acquisition path are therefore shut, and these are the spells that fall through the gap.
     * Each one was found by reading the stock SkillLineAbility.dbc row and the live
     * acore_world.npc_trainer table, not by guessing.
     *
     * Granted here, from the module, rather than by widening the stock ClassMask in
     * `skilllineability_dbc`. Both work; the module is chosen because widening a stock row edits
     * a record every other class reads, while a learnSpell behind a HasSpell guard touches
     * nothing but this character. If the data half ever takes them over, these calls become
     * no-ops the first time HasSpell answers true -- the two paths agree, whichever runs first.
     *
     * Deliberately declared HERE, in an anonymous namespace, and not taken from
     * dh_progression.h. None of them is a Demon Hunter spell: they are Blizzard's own records,
     * they have nothing to do with the ability ladder, and the generator has no business
     * knowing about them.
     */

    // 674 Dual Wield. SkillLineAbility(SkillLine 118, ClassMask 109, RaceMask 0, AcquireMethod 2)
    // -- read out of /srv/wow/data/dbc/SkillLineAbility.dbc. ClassMask 109 is
    // warrior|hunter|rogue|death knight|shaman; class 10's bit 512 is not in it, and
    // Player::learnSkillRewardedSpells skips any row whose ClassMask misses the player
    // (Player.cpp:12270-12274). So the skill 118 row that dh_spec.py puts in
    // playercreateinfo_skills gives the Demon Hunter the SKILL and not the SPELL.
    //
    // Without the spell, Unit::CanDualWield() is false for the character's entire life --
    // SPELL_EFFECT_DUAL_WIELD (Spell::EffectDualWield, SpellEffects.cpp:2700-2705) is the only
    // thing in the core that sets it for a player -- and Player::FindEquipSlot never offers
    // EQUIPMENT_SLOT_OFFHAND (PlayerStorage.cpp:186-187). A dual-wielding class that cannot
    // equip an off-hand is not a partial feature, it is the wrong class.
    //
    // 674 is PASSIVE (Attributes 0x50, bit 0x40 set), so learnSpell is sufficient on its own:
    // Player::addSpell casts a learnt passive at Player.cpp:3317-3321, and _LoadSpells re-runs
    // addSpell on every login, so CanDualWield survives a relog. It also has to be OWNED and not
    // merely applied, because Player::resetTalents (Player.cpp:3938-3939) and
    // Player::ActivateSpec (Player.cpp:15663-15664) both revoke CanDualWield from anyone who
    // does not HasSpell(674).
    constexpr uint32 kSpellDualWield = 674;

    // 3127 Parry. Two stock SkillLineAbility rows, neither reachable:
    //   (SkillLine 95 Defense, ClassMask 15, AcquireMethod 0) -- trainer-taught, and the live
    //      acore_world.npc_trainer has exactly four rows for it (IDs 200001/200004/200014/200016,
    //      ReqLevel 6/8/8/12). All four sit on class trainers a Demon Hunter cannot use.
    //   (SkillLine 95 Defense, ClassMask 32, AcquireMethod 1) -- the Death Knight's automatic
    //      grant. ClassMask 32 is class 6 only.
    //
    // Player::SetCanParry is reached from exactly two places: SPELL_AURA_MOD_PARRY_PERCENT
    // (SpellAuraEffects.cpp:4606) and SPELL_EFFECT_PARRY (SpellEffects.cpp:4690-4697), which is
    // 3127's Effect_1. Player::UpdateParryPercentage opens with
    // `if (CanParry() && parry_cap[pclass] > 0.0f)` (StatSystem.cpp:774) -- BOTH halves are
    // required, so without the spell build/patches/0001's `parry_cap[9] = 145.560408f`, added
    // specifically because a Demon Hunter parries, is dead code. The character sheet would show
    // 0% and be telling the truth.
    //
    // Also passive (Attributes 0x50), so the same learnSpell-is-enough argument applies.
    constexpr uint32 kSpellParry = 3127;

    /*
     * THE RACIAL EACH ELF RACE GATES BY CLASS.
     *
     * Most racials carry ClassMask 0 and reach a Demon Hunter untouched: read from
     * SkillLineAbility.dbc, a Night Elf gets 20583 Nature Resistance, 20582 Quickness, 20585
     * Wisp Spirit and 58984 Shadowmeld, and a Blood Elf gets 822 Magic Resistance and 28877
     * Arcane Affinity, all with ClassMask 0. Exactly one row per race is class-gated, and in
     * both cases the gate is a list of melee classes that a Demon Hunter would obviously be on
     * if the row had been written after 2008.
     */

    // 21009 Elusiveness -- "Reduces the chance enemies have to detect you while Shadowmelded or
    // Stealthed". SkillLineAbility(126, ClassMask 1085, RaceMask 0x8, AcquireMethod 2); 1085 is
    // warrior|hunter|rogue|death knight|shaman|druid. The Demon Hunter HAS Shadowmeld (58984,
    // ClassMask 0), so this is the one racial whose absence would be visible in play.
    constexpr uint32 kSpellElusiveness = 21009;

    // 25046 Arcane Torrent -- the ENERGY variant. SkillLineAbility(756, ClassMask 8, RaceMask
    // 0x200, AcquireMethod 2); ClassMask 8 is Rogue alone, because in 3.3.5a the Rogue was the
    // only Blood Elf class on energy. The other two rows on skill 756 are 28730 (ClassMask 406,
    // the mana classes) and 50613 (ClassMask 32, runic power). A Fury class wants 25046 and only
    // 25046, which is also what dh_spec.py CREATE_ACTION_RACE_SPELL puts on button 2 of a Blood
    // Elf's starting bar -- so without this grant that button is blank at character creation.
    constexpr uint32 kSpellArcaneTorrent = 25046;

    /*
     * THE TWO MOVEMENT SPELL IDS THE CLIENT ADDON CASTS.
     *
     * Derived here the way tools/dh_spec.py derives them, rather than written as two literals,
     * because the arithmetic is the thing that has to stay true:
     *
     *     spell_id_for(key, rank) = SPELL_ID_BASE + IDS_PER_ABILITY * ABILITY_BLOCKS[key] + rank
     *     single_spell_id(key)    = spell_id_for("singles", SINGLES_ORDER.index(key))
     *
     * with SPELL_ID_BASE 91000, IDS_PER_ABILITY 20, ABILITY_BLOCKS["singles"] 25 and
     * SINGLES_ORDER beginning ("double_jump", "glide", ...).
     *
     * BEWARE: the inline comments beside SINGLES_ORDER in dh_spec.py say 91300 and 91301. They
     * are stale -- they predate the singles block moving from index 15 to index 25, which the
     * ABILITY_BLOCKS comment ("singles": 25, # 91500-91519) and single_spell_id() both agree on.
     * The code is right and the comments are wrong. This matters beyond tidiness: NOTES.md 5.2
     * asks for these two numbers to be pasted into the two marked PLACEHOLDER lines at the top
     * of the addon's Movement.lua, and pasting 91300 there produces a keybind that casts a spell
     * nobody owns, silently.
     */
    constexpr uint32 kDhSpellIdBase   = 91000;   // dh_spec.py SPELL_ID_BASE
    constexpr uint32 kDhIdsPerAbility = 20;      // dh_spec.py IDS_PER_ABILITY
    constexpr uint32 kDhSinglesBlock  = 25;      // dh_spec.py ABILITY_BLOCKS["singles"]
    constexpr uint32 kDhSinglesBase   = kDhSpellIdBase + kDhIdsPerAbility * kDhSinglesBlock;

    constexpr uint32 kSpellDoubleJump = kDhSinglesBase + 0;   // SINGLES_ORDER[0]
    constexpr uint32 kSpellGlide      = kDhSinglesBase + 1;   // SINGLES_ORDER[1]

    static_assert(kSpellDoubleJump == 91500 && kSpellGlide == 91501,
        "the singles block moved -- re-derive these from dh_spec.py and reship the addon's Movement.lua");

    /*
     * The one mutation this module performs.
     *
     * Player::HasSpell (Player.cpp:4039) returns true for a spell that is known but INACTIVE --
     * it tests State != PLAYERSPELL_REMOVED, not Active. That is the semantics we want: a low
     * rank that Player::addSpell has deactivated in favour of a higher one is still OWNED, and
     * re-learning it would be churn plus an extra SMSG_SUPERCEDED_SPELL per login.
     *
     * Player::learnSpell early-returns on HasActiveSpell (Player.cpp:3412-3417), so this guard is
     * belt and braces for correctness. It is not redundant for cost: it keeps the steady state at
     * one unordered_map lookup per table entry, with no string formatting and no debug log line,
     * which matters because mod-playerbots routes every bot login through
     * WorldSession::HandlePlayerLoginFromDB (CharacterHandler.cpp:802) and therefore through
     * the OnPlayerLogin dispatch at :1131.
     */
    void LearnIfMissing(Player* player, uint32 spellId)
    {
        if (player->HasSpell(spellId))
            return;

        player->learnSpell(spellId);
    }

    // A level knob of 0 means "never grant", not "grant at level 0". Without this, 0 would read
    // as `level >= 0` -- always true -- and the knob would have no off position at all.
    bool LevelGateOpen(uint8 configuredLevel, uint8 playerLevel)
    {
        return configuredLevel != 0 && playerLevel >= configuredLevel;
    }

    // getRace(true) and not getRace(). Unit::getRaceMask (Unit.h:839) is
    // `1 << (getRace(true) - 1)`, and getRaceMask is what learnSkillRewardedSpells matches the
    // stock racial rows against (Player.cpp:12265-12267). Using the current race here instead of
    // the original one would hand a race-changed character a different racial from the one the
    // core's own path would have given them.
    uint32 RacialSpellForRace(uint8 race)
    {
        switch (race)
        {
            case RACE_NIGHTELF: return kSpellElusiveness;
            case RACE_BLOODELF: return kSpellArcaneTorrent;
            default:            return 0;
        }
    }
}

/*
 * Reconcile -- grant exactly what this character's level entitles them to, idempotently.
 *
 * Called from login and from level change. Safe to call any number of times, in any order, at
 * any level. The only mutation is Player::learnSpell behind a HasSpell guard, so the function is
 * a pure convergence step: its effect depends only on (level, race, current spellbook) and
 * running it twice is identical to running it once.
 *
 * Correct in BOTH directions of a GM level change, including the offline case:
 *   * UP, online   -- Player::GiveLevel fires OnPlayerLevelChanged after SetLevel (Player.cpp:2521
 *                     then :2583), so GetLevel() is already the new level here.
 *   * UP, offline  -- `.character level` on an offline character writes raw CHAR_UPD_LEVEL SQL
 *                     with NO script hook at all (cs_character.cpp:271-276). The login pass is
 *                     what closes that hole, and it is the reason OnPlayerLogin is not optional.
 *   * DOWN         -- a no-op, deliberately. This function never revokes. The core does not
 *                     revoke on de-level either (a de-levelled warrior keeps every rank), and
 *                     Player::removeSpell (Player.cpp:3492) removes higher ranks RECURSIVELY, so
 *                     a revoke pass would turn a GM typo into a destroyed spellbook. Levelling
 *                     back up simply re-enters the loop and finds everything already owned.
 *   * restart      -- nothing is cached across sessions; the next login recomputes from scratch.
 *
 * UNLIKE THE DEATH KNIGHT, THERE IS NO SECOND PATH. mod-dk-lowlevel can note that rank 1 of its
 * level-1 abilities is also granted for free by SkillLineAbility AcquireMethod = 2, and that
 * mod-learn-spells independently hands out ranks 2+. Neither is true here: a Demon Hunter
 * ability is family 16, and mod-learn-spells resolves an unknown class to SPELLFAMILY_GENERIC
 * and never looks at family 16 at all (README.md 8). This loop is the only thing on the realm
 * that gives a Demon Hunter a Demon Hunter spell.
 */
void demon_hunter_playerscript::Reconcile(Player* player)
{
    if (!player)
        return;

    // Master switch, read live rather than cached -- see the comment on DemonHunterConfig.
    // Everything in this module is behind it: at Enable = 0 the module must be indistinguishable
    // from not being compiled in, because it ships that way and only gets flipped on after the
    // class-stats gate passes.
    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return;

    // Raw getClass(), NOT IsClass(). Player::IsClass (Player.cpp:1348-1355) consults
    // sScriptMgr->OnPlayerIsClass() first and returns whatever a module answers -- and in this
    // module's case the module answering is THIS FILE, twenty lines further down. Asking IsClass
    // here would be asking our own answer to a question it exists to answer, and it would be
    // wrong in a way that is genuinely hard to see: OnPlayerIsClass returns
    // `playerClass == CLASS_ROGUE` for the stat contexts, so a Demon Hunter would answer false to
    // `IsClass(CLASS_DEMON_HUNTER, CLASS_CONTEXT_STATS)`. Unit::getClass() (Unit.h:844) reads
    // UNIT_FIELD_BYTES_0 directly and cannot be intercepted by anything.
    if (player->getClass() != CLASS_DEMON_HUNTER)
        return;

    uint8 const level = player->GetLevel();

    // kDhProgression is asserted ascending-by-level at compile time (demon_hunter.h), which is
    // what makes this early-out safe.
    for (DhGrant const& grant : kDhProgression)
    {
        if (grant.level > level)
            break;

        LearnIfMissing(player, grant.spellId);
    }

    // The untrainable three. Each is a Blizzard record with a stock ClassMask that predates
    // class 10; the long comments on the constants say which row and what breaks without it.
    if (LevelGateOpen(sDemonHunterConfig.DualWieldLevel, level))
        LearnIfMissing(player, kSpellDualWield);

    if (LevelGateOpen(sDemonHunterConfig.ParryLevel, level))
        LearnIfMissing(player, kSpellParry);

    // No level gate on the racial, and that is not an oversight: every other elf has theirs from
    // creation, and dh_spec.py's playercreateinfo_action already puts a Blood Elf's Arcane
    // Torrent on button 2 of the starting bar. Any level other than 1 would mean shipping a
    // character whose action bar has a hole in it, so the level is not a decision anyone should
    // be offered. GrantRacials is a bool for the same reason.
    if (sDemonHunterConfig.GrantRacials)
        if (uint32 const racial = RacialSpellForRace(player->getRace(true)))
            LearnIfMissing(player, racial);
}

/*
 * Fires at CharacterHandler.cpp:1131 -- after AddPlayerToMap, SendInitialPacketsAfterAddToMap and
 * m_playerLoading = false. The player is fully in world, so learnSpell's
 * `if (IsInWorld()) SendLearnPacket(...)` (Player.cpp:3427-3428) actually reaches the client and
 * the new button appears without a relog.
 *
 * It also fires BEFORE OnPlayerFirstLogin (CharacterHandler.cpp:1136), so first login is already
 * covered and no separate hook is needed. OnPlayerCreate is useless for this
 * (CharacterHandler.cpp:598 runs it after SaveToDB on a shared_ptr that is destroyed
 * immediately), and OnPlayerLoadFromDB is too early (PlayerStorage.cpp:5504, before
 * _LoadSkills/_LoadSpells -- the spell map is empty).
 *
 * Known gap, accepted: HandlePlayerLoginToCharInWorld (CharacterHandler.cpp:1142-1280), the
 * reconnect-to-a-still-in-world-character path used when CONFIG_ENABLE_LOGIN_AFTER_DC is on,
 * never calls OnPlayerLogin. That path cannot change a character's level, so there is nothing to
 * reconcile; the next real login covers it either way.
 */
void demon_hunter_playerscript::OnPlayerLogin(Player* player)
{
    Reconcile(player);
}

/*
 * Fires at Player.cpp:2583, at the end of Player::GiveLevel. SetLevel already ran at :2521, so
 * player->GetLevel() is the NEW level and the uint8 argument is the OLD one -- which we do not
 * need, because Reconcile derives everything from the current level.
 */
void demon_hunter_playerscript::OnPlayerLevelChanged(Player* player, uint8 /*oldLevel*/)
{
    Reconcile(player);
}

/*
 * =============================================================================================
 * THE CENTREPIECE. What existing class does a Demon Hunter answer as, and when?
 * =============================================================================================
 *
 * Player::IsClass (Player.cpp:1348-1355) asks this hook before comparing getClass(), and returns
 * our answer verbatim when we give one:
 *
 *     Optional<bool> scriptResult = sScriptMgr->OnPlayerIsClass(this, unitClass, context);
 *     if (scriptResult != std::nullopt)
 *         return *scriptResult;
 *     else
 *         return (getClass() == unitClass);
 *
 * That is the whole reason an eleventh class is viable without a core-wide audit: 149 IsClass(CLASS_...
 * call sites across 26 files funnel through it, each carrying a ClassContext
 * (UnitDefines.h:231-251) that says WHY it is asking. std::nullopt means "I have no opinion, use
 * your own comparison", which for a Demon Hunter evaluates to false against every existing class
 * -- so nullopt is not a shrug, it is the positive answer "a Demon Hunter is a Demon Hunter
 * here", and it is the right answer far more often than not.
 *
 * The census below was taken by grepping every CLASS_CONTEXT_* value in .work/ac-src/src and
 * reading the call sites, not from the enum:
 *
 *   ctx                     n   answer   why, from the call site
 *   ----------------------------------------------------------------------------------------
 *   NONE                   22   nullopt  Reached by every IsClass() call that omits the
 *                                        argument (Player.h:1132 defaults it). All twenty-two
 *                                        are class flavour: the DK's Trial of the Champion gate
 *                                        (LFGMgr.cpp:511), moonglade druid flights, paladin seal
 *                                        handling (Spell.cpp:2794), Sindragosa's healer picker,
 *                                        tournament pennants. A Demon Hunter is none of them.
 *   INIT                    6   nullopt  Player::Create. `!IsClass(DK, INIT)` chooses
 *                                        START_PLAYER_LEVEL over START_HEROIC_PLAYER_LEVEL
 *                                        (Player.cpp:573) and START_PLAYER_MONEY over the heroic
 *                                        one (:588); it also decides 10 food vs 4 (:653), the
 *                                        Ebon Hold collector's voucher (:673), and whether
 *                                        GetStartPosition overrides the playercreateinfo row
 *                                        (:11590). A Demon Hunter starts at level 1 in an elf
 *                                        starting zone with an ordinary purse; false is correct
 *                                        on every one.
 *   TELEPORT                5   nullopt  All five are the same anti-stranding check --
 *                                        "DK on map 609 who does not know Death Gate"
 *                                        (Player.cpp:1549, Group.cpp:2220,
 *                                        BattleGroundHandler.cpp:187, TC9GrpcHandler.cpp:358,
 *                                        ArenaSpectator.cpp:45). A Demon Hunter is never in
 *                                        Acherus and has no Death Gate. Answering DK here would
 *                                        VETO their far teleports.
 *   QUEST                   5   nullopt  Player.cpp:6657 is the DK duel exception for quest
 *                                        12733; the other four are moonglade druid quests.
 *   STATS                  20   ROGUE    THE ONE THAT MATTERS. StatSystem.cpp:399 puts
 *                                        rogue/hunter/shaman on melee AP = level*2 + STR + AGI
 *                                        - 20, and :370 puts rogue/warrior on ranged AP = level
 *                                        + AGI - 10. With no answer a Demon Hunter falls past
 *                                        every branch to val2 = 0 for melee AP -- not a small
 *                                        number, zero -- while the ranged branch's `else` gives
 *                                        AGI - 10. Rogue and not druid or hunter because the
 *                                        class is leather, agility, dual-wield and energy, which
 *                                        is exactly what dh_spec.py TEMPLATE_CLASS = 4 says
 *                                        every other derivation in this feature already uses.
 *                                        Returning `playerClass == CLASS_ROGUE` keeps every
 *                                        non-rogue test false, so the mage/priest/warlock branch
 *                                        (:484), the shaman/paladin Mental Quickness branch
 *                                        (:534), the druid feral-AP-from-weapon block
 *                                        (Player.cpp:7060) and the three hunter checks in
 *                                        spell_generic.cpp are all unaffected.
 *   TAXI                    5   nullopt  Player.cpp:10533 is the DK's own flight mount at node
 *                                        315; the rest is moonglade druid flight paths.
 *   SKILL                   2   nullopt  Player::LearnDefaultSkill (Player.cpp:12143, :12176)
 *                                        gives a DK weapon skills at (level-1)*5 because a DK is
 *                                        created at 55. A Demon Hunter is created at 1, so
 *                                        skillValue 1 growing with use is exactly right, and
 *                                        answering DK would hand a level-1 character a skill
 *                                        value of 1 anyway -- the same number by a wronger route.
 *   TALENT_POINT_CALC       1   nullopt  Player::CalculateTalentsPoints (Player.cpp:13941) gives
 *                                        a DK standing on map 609 `level - 55` points. Answering
 *                                        DK would import the Acherus talent-wipe that
 *                                        mod-dk-lowlevel exists to patch out. false gives the
 *                                        normal `level - 9`, which is what we want everywhere.
 *   ABILITY                24   nullopt  Rune regeneration and grace periods (Player.cpp:1812,
 *                                        :1842, PlayerUpdates.cpp:1555, Unit.cpp:10683),
 *                                        InitRunes (:13775), rune cost and conversion in
 *                                        Spell.cpp/SpellEffects.cpp/SpellAuraEffects.cpp, the
 *                                        priest's Spirit of Redemption (Unit.cpp:14101), the
 *                                        paladin's Righteous Fury strip on spec change
 *                                        (:15669), shaman totem enchants (:5189), and rogue
 *                                        PICKPOCKETING in LootHandler.cpp:94, :173, :442. Not
 *                                        one is a mechanic a Demon Hunter has. Answering rogue
 *                                        here to "match the template" would let a Demon Hunter
 *                                        loot a live creature's pickpocket loot.
 *                                        Vehicle.cpp:80 also passes ABILITY but is unreachable
 *                                        from this hook: `_me` there is a Creature, and
 *                                        Creature does not override IsClass, so it resolves to
 *                                        the plain Unit::IsClass (Unit.h:845) which never
 *                                        consults a script.
 *   ABILITY_REACTIVE        7   nullopt  Unit.cpp:12792 reads `if (!IsClass(CLASS_ROGUE, ...))
 *                                        // skip Rogue Riposte` -- the rogue is the ONE class
 *                                        that does not get AURA_STATE_DEFENSE on a dodge.
 *                                        Answering rogue would opt a Demon Hunter out of a
 *                                        state it has no Riposte to justify losing, and the
 *                                        aura state is what a future Vengeance talent would key
 *                                        on. The other six are hunter Counterattack and warrior
 *                                        Overpower.
 *   PET                    20   nullopt  Every one asks "is my owner the class this pet belongs
 *                                        to": warlock/mage/DK/hunter pet scaling in Pet.cpp,
 *                                        Player::CanResummonPet (Player.cpp:14582-14598), the
 *                                        stable-master gossip option (PlayerGossip.cpp:113),
 *                                        hunter taming in SpellEffects.cpp. A Demon Hunter has
 *                                        no pet. nullopt hides the stable option and leaves
 *                                        CanResummonPet on its HasSpell fallback.
 *   PET_CHARM               3   nullopt  Warlock-charms-a-demon, Unit.cpp:14697, :14763, :14891.
 *   EQUIP_RELIC            13   nullopt  Librams, idols, totems and sigils, in
 *                                        Player::FindEquipSlot (PlayerStorage.cpp:225-241),
 *                                        BotCanUseItem (:920-935) and CanRollForItemInLFG
 *                                        (:2496-2514). A Demon Hunter's ranged slot holds a
 *                                        thrown glaive. Answering any of these four classes
 *                                        would let one equip that class's relic and would offer
 *                                        it in the LFG need roll.
 *   EQUIP_SHIELDS           3   nullopt  PlayerStorage.cpp:2488-2490. The class dual-wields and
 *                                        has no Shield proficiency in dh_spec.py CREATE_SKILLS,
 *                                        so even a true answer would still fail the skill check
 *                                        two lines earlier. false is both correct and honest.
 *   EQUIP_ARMOR_CLASS      11   ROGUE    PlayerStorage.cpp:2544 sets subclassToCompare =
 *                                        ITEM_SUBCLASS_ARMOR_LEATHER for a rogue AND returns
 *                                        EQUIP_ERR_CANT_DO_RIGHT_NOW for anything carrying
 *                                        spell power -- exactly the need-before-greed rule an
 *                                        agility leather class wants. With no answer the chain
 *                                        falls to the initial ITEM_SUBCLASS_ARMOR_CLOTH, and a
 *                                        Demon Hunter would be told leather is an upgrade-class
 *                                        violation in every LFG roll. The same answer at :2356
 *                                        correctly leaves the heirloom plate/mail "morph"
 *                                        branch alone.
 *   WEAPON_SWAP             2   ROGUE    PlayerStorage.cpp:1950 and :2859 pick the in-combat
 *                                        weapon-swap lockout spell: 6123 for a rogue, 6119 for
 *                                        everyone else. Read out of Spell.dbc, those are both
 *                                        "Combat Swap (DND)" with StartRecoveryTime 1000 and
 *                                        1500 respectively. The Demon Hunter's global cooldown
 *                                        is 1000 (dh_spec.py TEMPLATE_CLASS, and the reason the
 *                                        class is on energy at all), so 6119 would lock the
 *                                        class out of its own abilities for 500 ms longer than
 *                                        its GCD after every in-combat swap -- a penalty no
 *                                        other energy class pays.
 *   GRAVEYARD               0   nullopt  ZERO call sites. The enumerator exists at
 *   CLASS_TRAINER           0   nullopt  UnitDefines.h:249 and :250 and nothing in the entire
 *                                        tree ever passes either one, so no answer is
 *                                        observable. Listed explicitly so the next person does
 *                                        not spend an evening deciding what a Demon Hunter's
 *                                        graveyard behaviour should be. If a future core bump
 *                                        starts using them, this switch will still fall to
 *                                        nullopt, which is the safe default.
 *
 * COST. Every IsClass call on the realm enters this function, not just Demon Hunters', because
 * ScriptMgr::OnPlayerIsClass (PlayerScript.cpp:576-588) only short-circuits when the hook list is
 * empty and ours is not. The getClass() test is therefore FIRST and load-bearing: it is one
 * UNIT_FIELD_BYTES_0 read and a compare, and it rejects every non-Demon-Hunter before anything
 * more expensive happens. The config lookup below it costs a string hash, and only a real Demon
 * Hunter ever pays it.
 */
Optional<bool> demon_hunter_playerscript::OnPlayerIsClass(Player const* player, Classes playerClass, ClassContext context)
{
    if (!player)
        return std::nullopt;

    if (player->getClass() != CLASS_DEMON_HUNTER)
        return std::nullopt;

    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return std::nullopt;

    switch (context)
    {
        // The three contexts where "what shape is this character" is the real question, and the
        // answer is the stat template the whole feature is built on.
        case CLASS_CONTEXT_STATS:
        case CLASS_CONTEXT_EQUIP_ARMOR_CLASS:
        case CLASS_CONTEXT_WEAPON_SWAP:
            return playerClass == CLASS_ROGUE;

        // Everything else. Falling through to the core's own getClass() == unitClass is the
        // correct answer, not the lazy one -- see the table above, context by context.
        default:
            return std::nullopt;
    }
}

/*
 * DOUBLE JUMP AND GLIDE -- the server half of .work/dh-parts/addon/DemonHunter/Movement.lua.
 *
 * THE PROTOCOL IS A SPELL CAST, NOT AN ADDON MESSAGE. The addon binds a key to a
 * SecureActionButtonTemplate whose `spell` attribute is the numeric spell id, so the CLIENT
 * casts through its own SECURE_ACTIONS.spell -> CastSpellByID path (Movement.lua:280-285) and
 * what arrives here is an ordinary CMSG_CAST_SPELL. There is no addon channel to wire up and
 * nothing for this module to parse. (For the record, had there been one: this fork has no
 * `OnPlayerChat` at all. Addon traffic surfaces as the five PlayerScript::OnPlayerCanUseChat
 * overloads -- PlayerScript.h:659, :672, :685, :698, :711 -- keyed on `language == LANG_ADDON`,
 * dispatched from ChatHandler.cpp:469-656, and CHAT_MSG_ADDON only ever rides on
 * PARTY/RAID/GUILD/BATTLEGROUND/WHISPER (ChatHandler.cpp:186-195).)
 *
 * So the only thing the client cannot do, and therefore the only thing left for the server, is
 * NOTES.md 5.4:
 *
 *     "A cast of either spell while the caster is not falling must fail silently and cost no
 *      global cooldown (SPELL_FAILED_DONT_REPORT)."
 *
 * That requirement is not a nicety, and NOTES.md 2.4 proves it: the addon physically cannot make
 * this decision during combat. `IsFalling` is not in the restricted environment (that section
 * cites RestrictedEnvironment.lua:99-183), there is no `falling` macro conditional anywhere in
 * the client binary, and insecure code cannot hand the value into a secure snippet under
 * lockdown. The glide key therefore stays bound at all times and a grounded press reaches us.
 * If we do not reject it here, nobody does, and the player eats a global cooldown for pressing
 * Glide while standing still.
 *
 * WHY IT FAILS FOR FREE. This hook is dispatched from the very first lines of Spell::CheckCast
 * (Spell.cpp:5664-5669), and Spell::prepare calls CheckCast at :3522 and only reaches
 * TriggerGlobalCooldown at :3686 -- so a failure written into `res` returns out of prepare at
 * :3538-3541 before the GCD, before the power cost and before any cooldown is set.
 * Spell::SendCastResult drops SPELL_FAILED_DONT_REPORT without sending a packet, so the player
 * sees nothing at all.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO -- and it is a REQUIREMENT ON THE DATA HALF, written up in
 * README.md 7: it does not rate-limit the double jump. The addon holds the jump key down and
 * sends repeated casts on purpose ("the server's cooldown is the authority", NOTES.md 7), and
 * SPELL_EFFECT_LEAP_BACK applies a fresh upward impulse every time it lands
 * (SpellEffects.cpp:5056-5077), so a Double Jump record with RecoveryTime 0 is an infinite
 * levitation exploit. RecoveryTime is a Spell.dbc cell and therefore dh_spec.py's business, not
 * this module's; dh_spec.py's Ability for double_jump currently leaves cooldown_ms at its 0
 * default. This module owns the falling gate because there is no Spell.dbc cell that can express
 * it; it does not own the cooldown because there is one and using it would be a second source of
 * truth.
 */
void demon_hunter_movement_allspellscript::OnSpellCheckCast(Spell* spell, bool /*strict*/, SpellCastResult& res)
{
    if (!spell)
        return;

    // Cheapest test first: two integer compares reject every other cast on the realm, and this
    // hook runs on every cast by every player and every bot.
    uint32 const spellId = spell->GetSpellInfo()->Id;
    if (spellId != kSpellDoubleJump && spellId != kSpellGlide)
        return;

    if (!sConfigMgr->GetOption<bool>("DemonHunter.Enable", false))
        return;

    // Deliberately NOT gated on the caster being a Demon Hunter. The rule belongs to the spell,
    // not to the class: a GM who `.learn 91500`s Double Jump onto a mage should get the same
    // grounded-cast behaviour, and adding a class test would be one more thing to be wrong.
    Unit const* caster = spell->GetCaster();
    if (!caster)
        return;

    /*
     * Unit::IsFalling (Unit.h:1718, defined Unit.cpp:15933) and NOT Player::IsFalling
     * (Player.h:1137, Player.cpp:2189). Neither is virtual and the Player one HIDES the Unit one,
     * so which of them runs is decided by the static type of this pointer -- hold a Player* and
     * you silently get the wrong function.
     *
     * They are not two spellings of one idea:
     *   Unit::IsFalling  -- MOVEMENTFLAG_FALLING | MOVEMENTFLAG_FALLING_FAR from the last
     *                       movement packet, plus a falling spline. This is the same fact the
     *                       addon's own IsFalling() reads, which is the fact the protocol is
     *                       specified in terms of.
     *   Player::IsFalling -- `GetPositionZ() < m_lastFallZ && !IsInFlight()`, i.e. "below where
     *                       this fall started". It is FALSE for the whole rising half of a jump,
     *                       so using it would reject the double jump at the apex -- the exact
     *                       moment the ability exists for.
     */
    if (caster->IsFalling())
        return;

    res = SPELL_FAILED_DONT_REPORT;
}

void demon_hunter_worldscript::OnAfterConfigLoad(bool /*reload*/)
{
    sDemonHunterConfig.Load();

    bool const enabled = sConfigMgr->GetOption<bool>("DemonHunter.Enable", false);

    // Fires on `.reload config` as well as at boot (World.cpp:301, reached from
    // World::SetInitialWorldSettings AFTER Main.cpp:277 sScriptMgr->Initialize(), so this script
    // is already registered the first time round). This line is also the answer to "did my config
    // flip actually take?", which matters because the module is turned on with a reload, not a
    // restart.
    //
    // The uint8s are widened to uint32 on purpose: fmt would be entitled to render a narrow char
    // type as a character, and "ParryLevel=\x01" is not a useful log line.
    LOG_INFO("server.loading", "mod-demon-hunter: Enable={} DualWieldLevel={} ParryLevel={} GrantRacials={} grants={}",
        enabled,
        uint32(sDemonHunterConfig.DualWieldLevel),
        uint32(sDemonHunterConfig.ParryLevel),
        sDemonHunterConfig.GrantRacials,
        uint32(std::size(kDhProgression)));

    if (!enabled)
        return;

    // The movement gate is compiled against two literal spell ids derived from dh_spec.py's id
    // plan. If the generator ever moves the singles block, or drops Double Jump or Glide from the
    // ladder, the gate silently stops matching the spell the client actually casts and a grounded
    // Glide starts costing a global cooldown again -- a failure with no symptom anyone would
    // connect to this module. Checked here rather than as a static_assert because WHICH spells
    // are in the ladder is the generator's decision, and a module that refuses to build over it
    // would be the worse failure. Gated on Enable so a realm that has not applied the SQL yet
    // does not get an error line about data it deliberately has not shipped.
    if (!DhProgressionHas(kDhProgression, kSpellDoubleJump) || !DhProgressionHas(kDhProgression, kSpellGlide))
        LOG_ERROR("server.loading",
            "mod-demon-hunter: Double Jump ({}) and/or Glide ({}) are not in dh_progression.h. "
            "The id plan in tools/dh_spec.py has moved: re-derive both, fix the two PLACEHOLDER "
            "lines in the client addon's Movement.lua, and rebuild -- until then a grounded cast "
            "of either spell is not suppressed.",
            kSpellDoubleJump, kSpellGlide);
}

void AddSC_demon_hunter()
{
    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process. This is the convention every module and core script follows.
    new demon_hunter_worldscript();
    new demon_hunter_playerscript();
    new demon_hunter_movement_allspellscript();
}
