/*
 * mod-dk-lowlevel -- TRUE level-1 Death Knights.  DESIGN.md artefact A15.
 *
 * Read dk_lowlevel.h first; it carries the hook-name warning and the generated-table contract.
 */

#include "dk_lowlevel.h"

DkLowLevelConfig sDkLowLevelConfig;

void DkLowLevelConfig::Load()
{
    // These defaults MUST match conf/mod_dk_lowlevel.conf.dist value for value.
    //
    // deploy/docker-compose.yml bind-mounts ../conf/modules over /opt/ac/etc/modules as a
    // DIRECTORY, which shadows the image's installed .conf.dist files entirely, and
    // ConfigMgr::LoadModulesConfigs only ever opens `<name>.conf` -- never `<name>.conf.dist`.
    // So a key absent from conf/modules/mod_dk_lowlevel.conf silently falls back to the literal
    // below, not to the .dist. That is why every knob is listed in the repo's .conf as well.
    FixAcherusTalents = sConfigMgr->GetOption<bool>("DKLowLevel.FixAcherusTalents", true);
    DeathGateLevel    = sConfigMgr->GetOption<uint8>("DKLowLevel.DeathGateLevel", 1);
    RuneforgingLevel  = sConfigMgr->GetOption<uint8>("DKLowLevel.RuneforgingLevel", 1);
}

namespace
{
    /*
     * Utility spells the skipped Acherus starter chain used to hand out (DESIGN.md 7). Granted
     * directly -- NEVER by casting the quest reward spells 53431 / 53821, because 53821's Effect1
     * is SPELL_EFFECT_BIND with no dst, so re-casting it on every login would silently rebind the
     * player's hearthstone to wherever they logged in (DESIGN.md 7, "Explicitly rejected").
     *
     * Deliberately declared HERE, in an anonymous namespace with module-local names, and not
     * taken from dk_progression.h. tools/dk_spec.py carries the same four IDs in its
     * UTILITY_SPELLS tuple, but only as documentation of intent -- the module owns the gating
     * because the levels are config, not data, and there is nothing to keep in sync with either
     * the client DBC or the SQL. Internal linkage plus distinct names also means the generated
     * header can start exporting DK_SPELL_* constants tomorrow without colliding with these.
     *
     * Retail levels for the two riding tiers, not configurable: they are the same for every other
     * class on this realm, and a DK-only riding level would be a balance decision, not a knob.
     */
    constexpr uint32 kSpellDeathGate        = 50977;
    constexpr uint32 kSpellRuneforging      = 53428;

    constexpr uint8 kLevelApprenticeRiding = 20;

    /*
     * The one mutation this module performs.
     *
     * Player::HasSpell (Player.cpp:4039) returns true for a spell that is known but INACTIVE --
     * it tests State != PLAYERSPELL_REMOVED, not Active. That is exactly the semantics we want:
     * a low rank that Player::addSpell has deactivated in favour of a higher rank is still
     * OWNED, and re-learning it would be churn (and an extra SMSG_SUPERCEDED_SPELL per login for
     * the thirteen existing level-55+ DKs).
     *
     * Player::learnSpell early-returns on HasActiveSpell (Player.cpp:3411-3416), so this guard is
     * belt and braces for correctness. It is not redundant for cost: it keeps the steady state at
     * one unordered_map lookup per table entry, with no string formatting and no debug log line,
     * which matters because PlayerbotMgr.cpp:208 routes every bot login through
     * HandlePlayerLoginFromDB and therefore through OnPlayerLogin.
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
}

/*
 * Reconcile -- grant exactly what this character's level entitles them to, idempotently.
 *
 * Called from login and from level change. Safe to call any number of times, in any order, at
 * any level. The only mutation is Player::learnSpell behind a HasSpell guard, so the function is
 * a pure convergence step: its effect depends only on (level, current spellbook) and running it
 * twice is identical to running it once.
 *
 * Correct in BOTH directions of a GM level change, including the offline case:
 *   * UP, online   -- Player::GiveLevel fires OnPlayerLevelChanged after SetLevel (Player.cpp:2521
 *                     then :2583), so GetLevel() is already the new level here.
 *   * UP, offline  -- `.character level` on an offline character writes raw CHAR_UPD_LEVEL SQL
 *                     with NO script hook at all (cs_character.cpp:1119-1126). The login pass is
 *                     what closes that hole, and it is the reason OnPlayerLogin is not optional.
 *   * DOWN         -- a no-op, deliberately. This function never revokes. The core does not
 *                     revoke on de-level either (a de-levelled warrior keeps every rank), and
 *                     Player::removeSpell removes higher ranks RECURSIVELY, so a revoke pass
 *                     would turn a GM typo into a destroyed spellbook. Levelling back up simply
 *                     re-enters the loop and finds everything already owned.
 *   * restart      -- nothing is cached across sessions; the next login recomputes from scratch.
 *
 * Rank 1 of each ability is ALSO granted by the core itself, for free, via SkillLineAbility
 * AcquireMethod = 2 -> learnSkillRewardedSpells, which runs at creation and again from
 * Player::_LoadSkills on every login (Player.cpp:14081). This function is what covers ranks 2..N.
 * The two paths agree; whichever runs first wins and the other finds HasSpell true.
 */
void dk_lowlevel_playerscript::Reconcile(Player* player)
{
    if (!player)
        return;

    // Master switch, read live rather than cached -- see the comment on DkLowLevelConfig.
    // Everything in this module, including the talent hook, is behind it: at Enable = 0 the
    // module must be indistinguishable from not being compiled in, because it ships that way
    // and only gets flipped on after the player_class_stats gate passes (DESIGN.md 1.2 step 9).
    if (!sConfigMgr->GetOption<bool>("DKLowLevel.Enable", false))
        return;

    // Raw getClass(), NOT IsClass(). Player::IsClass (Player.cpp:1348-1355) consults
    // sScriptMgr->OnPlayerIsClass() first and returns whatever a module answers, so a third-party
    // module could make this test silently wrong in either direction -- skipping real DKs, or
    // firing for non-DKs and handing a mage an Icy Touch. Unit::getClass() (Unit.h:844) reads
    // UNIT_FIELD_BYTES_0 directly and cannot be intercepted.
    if (player->getClass() != CLASS_DEATH_KNIGHT)
        return;

    uint8 const level = player->GetLevel();

    // kDkProgression is asserted ascending-by-level at compile time (dk_lowlevel.h), which is
    // what makes this early-out safe.
    for (DkGrant const& grant : kDkProgression)
    {
        if (grant.level > level)
            break;

        LearnIfMissing(player, grant.spellId);
    }

    // Utilities the Acherus starter chain used to provide. The chain is unreachable under this
    // design (DESIGN.md 7), so these have to come from somewhere; granting the taught spell
    // directly is both simpler and safer than casting the quest reward spell.
    //
    // Death Gate first, and at level 1 by default, because 50977 is load-bearing beyond
    // convenience: Player.cpp:1549, BattleGroundHandler.cpp:187, Group.cpp:2220 and
    // TC9GrpcHandler.cpp:358 all guard on !HasSpell(50977) and would otherwise strand a DK who
    // reached map 609. Its destination is on map 0 (spell_target_position for 53822), so it can
    // never drop a low-level DK into the Acherus talent trap.
    if (LevelGateOpen(sDkLowLevelConfig.DeathGateLevel, level))
        LearnIfMissing(player, kSpellDeathGate);

    // learnSpell(53428) alone is complete -- Player::addSpell (Player.cpp:3377) special-cases
    // SKILL_RUNEFORGING and calls LearnDefaultSkill for it, which also picks up 53341/53343.
    // Casting the quest's 53431 is NOT needed and would be worse.
    if (LevelGateOpen(sDkLowLevelConfig.RuneforgingLevel, level))
        LearnIfMissing(player, kSpellRuneforging);

    // Riding is not something the skip BREAKS -- playercreateinfo_skills gives DKs skill 762 at
    // rank 0 and LearnDefaultSkill bails on rank 0 (Player.cpp:12163-12167), so a DK never got
    // riding at creation even today. It is something the skip fails to PROVIDE, because quest
    // 12687 used to. Deliberately NOT granting 48778 (Acherus Deathcharger): it is a level-55
    // epic mount and handing it to a level-1 character is a different feature.
    // Riding is deliberately NOT granted here. Stock SkillLineAbility 19184 already gives
    // every DK spell 33391 Journeyman Riding at creation (AcquireMethod=2), and granting
    // 33388 Apprentice Riding on top would DOWNGRADE the riding skill value via
    // SpellLearnSkillNode step*75. See tools/dk_spec.py.
}

/*
 * Fires at CharacterHandler.cpp:1131 -- after AddPlayerToMap (:911),
 * SendInitialPacketsAfterAddToMap (:923) and m_playerLoading = false (:1073). The player is fully
 * in world, so learnSpell's `if (IsInWorld()) SendLearnPacket(...)` actually reaches the client
 * and the new button appears without a relog.
 *
 * It also fires BEFORE OnPlayerFirstLogin (:1136), so first login is already covered and no
 * separate hook is needed. OnPlayerCreate is useless for this (CharacterHandler.cpp:598 runs it
 * after SaveToDB on a shared_ptr that is destroyed immediately), and OnPlayerLoadFromDB is too
 * early (PlayerStorage.cpp:5504, before _LoadSkills/_LoadSpells -- the spell map is empty).
 *
 * Known gap, accepted: HandlePlayerLoginToCharInWorld (CharacterHandler.cpp:1142-1280), the
 * reconnect-to-a-still-in-world-character path used when CONFIG_ENABLE_LOGIN_AFTER_DC is on,
 * never calls OnPlayerLogin. That path cannot change a character's level, so there is nothing to
 * reconcile; the next real login covers it either way.
 */
void dk_lowlevel_playerscript::OnPlayerLogin(Player* player)
{
    Reconcile(player);
}

/*
 * Fires at Player.cpp:2583, at the end of Player::GiveLevel. SetLevel already ran at :2521, so
 * player->GetLevel() is the NEW level and the uint8 argument is the OLD one -- which we do not
 * need, because Reconcile derives everything from the current level.
 */
void dk_lowlevel_playerscript::OnPlayerLevelChanged(Player* player, uint8 /*oldLevel*/)
{
    Reconcile(player);
}

/*
 * Close the Acherus talent-wipe hole (DESIGN.md 7.4).
 *
 * Player::CalculateTalentsPoints (Player.cpp:13936-13959) has a DK-on-map-609 branch that returns
 * `level < 56 ? 0 : level - 55` plus quest-reward talents. InitTalentForLevel then does
 * `if (m_usedTalentCount > talentPointsForLevel) resetTalents(true)` and is called from
 * LoadFromDB at PlayerStorage.cpp:5573, AFTER SetMap and AFTER _LoadTalents. So a sub-56 DK who
 * logs out in Acherus has every talent point silently refunded to zero, no gold back, every
 * login. Today that is unreachable because every DK is 55+; under this design a level-30 DK
 * taking Death Gate to a runeforge and logging out is routine.
 *
 * Overwriting with the same formula the core's own non-DK branch uses makes "talents from level
 * 10" true everywhere instead of everywhere-except-609. It is unconditional on quest state, so it
 * also covers a GM `.tele DKZone`.
 *
 * The const_cast is required and safe: GetBonusTalentCount() (Player.h:1761) is a non-const
 * trivial accessor that mutates nothing, and m_questRewardTalentCount has no getter at all. The
 * core uses the same pattern (SpellInfoCorrections.cpp:24-37).
 */
void dk_lowlevel_playerscript::OnPlayerCalculateTalentsPoints(Player const* player, uint32& talentPointsForLevel)
{
    if (!player)
        return;

    if (!sConfigMgr->GetOption<bool>("DKLowLevel.Enable", false))
        return;

    if (!sDkLowLevelConfig.FixAcherusTalents)
        return;

    if (player->getClass() != CLASS_DEATH_KNIGHT)
        return;

    if (player->GetMapId() != MAP_EBON_HOLD)
        return;

    uint32 const base = player->GetLevel() < 10 ? 0 : uint32(player->GetLevel() - 9);

    // The core added m_extraBonusTalentCount just before calling us (Player.cpp:13956) and we are
    // overwriting, not adjusting, so it has to go back on. m_questRewardTalentCount is
    // deliberately NOT re-added: off-609 it is not counted either, and counting it here would
    // give a chain-completing DK more points in Acherus than outside it.
    talentPointsForLevel = base + const_cast<Player*>(player)->GetBonusTalentCount();
}

void dk_lowlevel_worldscript::OnAfterConfigLoad(bool /*reload*/)
{
    sDkLowLevelConfig.Load();

    // Fires on `.reload config` as well as at boot (World.cpp:301, reached from
    // World::SetInitialWorldSettings AFTER Main.cpp:277 sScriptMgr->Initialize(), so this script
    // is already registered the first time round). This line is also the answer to "did my config
    // flip actually take?" -- which matters because DESIGN.md 1.2 turns the module on with a
    // reload, not a restart.
    //
    // The uint8s are widened to uint32 on purpose: fmt would be entitled to render a narrow char
    // type as a character, and "DeathGateLevel=\x01" is not a useful log line.
    LOG_INFO("server.loading", "mod-dk-lowlevel: Enable={} FixAcherusTalents={} DeathGateLevel={} RuneforgingLevel={}",
        sConfigMgr->GetOption<bool>("DKLowLevel.Enable", false),
        sDkLowLevelConfig.FixAcherusTalents,
        uint32(sDkLowLevelConfig.DeathGateLevel),
        uint32(sDkLowLevelConfig.RuneforgingLevel),);
}

void AddSC_dk_lowlevel()
{
    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process. This is the convention every module and core script follows.
    new dk_lowlevel_worldscript();
    new dk_lowlevel_playerscript();
}
