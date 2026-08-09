/*
 * npc_talent_master -- free talent and pet-talent respec, plus a catch-up "learn what I missed".
 *
 * WHY A NEW NPC RATHER THAN A GOSSIP OPTION ON GABRIELLA.
 * Gabriella (9000000) already carries `npc_assistant` from the pinned third-party mod-assistant,
 * and AzerothCore binds exactly ONE CreatureScript per creature_template.ScriptName. Adding an
 * option to her means forking a module we deliberately pin and do not own; every future bump
 * would have to re-apply the patch. A creature entry of our own costs one template row and stays
 * ours.
 *
 * WHY THE CONFIRMATION DIALOG RATHER THAN AN IMMEDIATE RESET.
 * Player::SendTalentWipeConfirm (Player.cpp:9113) is the same path a real class trainer uses:
 * the client shows its native "are you sure" with the cost, and the actual wipe happens when the
 * player accepts, via CMSG_TALENT_WIPE_CONFIRM -> SpellEffects.cpp. Doing it that way means we
 * inherit Blizzard's own flow instead of re-implementing one, and a misclick is recoverable.
 *
 * WHY IT IS FREE.
 * Player::resetTalents(bool noResetCost) with noResetCost = true skips the escalating gold cost
 * (cs_reset.cpp:246 uses the same call). On a three-friend realm the point of a respec NPC is to
 * let people try builds; a cost curve that punishes the fourth experiment defeats it. If that
 * ever needs to change it is one bool.
 */

#include "Config.h"
#include "Creature.h"
#include "Chat.h"
#include "Pet.h"
#include "Player.h"
#include "ScriptedGossip.h"
#include "ObjectMgr.h"
#include "ScriptMgr.h"

namespace
{
    constexpr uint32 GOSSIP_ICON_TALK = 0;      // GOSSIP_ICON_CHAT
    constexpr uint32 GOSSIP_ICON_TRAIN = 3;     // GOSSIP_ICON_TRAINER

    enum TalentMasterAction : uint32
    {
        ACTION_RESET_TALENTS = 1,
        ACTION_RESET_PET_TALENTS,
        ACTION_LEARN_MISSING,
    };

    bool ModuleEnabled()
    {
        return sConfigMgr->GetOption<bool>("UtilityNPCs.Enable", true);
    }

    class npc_talent_master : public CreatureScript
    {
    public:
        npc_talent_master() : CreatureScript("npc_talent_master") { }

        bool OnGossipHello(Player* player, Creature* creature) override
        {
            if (!ModuleEnabled())
                return false;                    // fall through to the default "I have nothing to say"

            // Talents do not exist below 10, so do not offer a menu entry that cannot do
            // anything -- Player::resetTalents would succeed and reset nothing, which reads as a
            // bug. CalculateTalentsPoints returns 0 below 10 (Player.cpp:13936).
            if (player->GetLevel() >= 10)
                AddGossipItemFor(player, GOSSIP_ICON_TRAIN, "Reset my talents",
                                 GOSSIP_SENDER_MAIN, ACTION_RESET_TALENTS);

            // Hunter pet talents only exist for a pet that is present and is a hunter beast.
            if (Pet* pet = player->GetPet())
                if (pet->getPetType() == HUNTER_PET)
                    AddGossipItemFor(player, GOSSIP_ICON_TRAIN, "Reset my pet's talents",
                                     GOSSIP_SENDER_MAIN, ACTION_RESET_PET_TALENTS);

            AddGossipItemFor(player, GOSSIP_ICON_TALK, "Teach me anything I have missed",
                             GOSSIP_SENDER_MAIN, ACTION_LEARN_MISSING);

            SendGossipMenuFor(player, DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
            return true;
        }

        bool OnGossipSelect(Player* player, Creature* creature, uint32 /*sender*/,
                            uint32 action) override
        {
            if (!ModuleEnabled())
                return false;

            ClearGossipMenuFor(player);

            switch (action)
            {
                case ACTION_RESET_TALENTS:
                    CloseGossipMenuFor(player);
                    // Native confirmation. The wipe itself happens on accept.
                    player->SendTalentWipeConfirm(creature->GetGUID());
                    break;

                case ACTION_RESET_PET_TALENTS:
                    CloseGossipMenuFor(player);
                    player->ResetPetTalents();
                    ChatHandler(player->GetSession()).PSendSysMessage("Your pet's talents have been reset.");
                    break;

                case ACTION_LEARN_MISSING:
                {
                    // mod-learn-spells already grants class spells on level up, so this is a
                    // CATCH-UP path, not the primary one: it matters after a GM level change,
                    // after a server-side data fix, or for a character that levelled before a
                    // spell existed. LearnDefaultSkills + the skill-reward pass is exactly what
                    // login does, so this is "re-run my login grants" rather than new behaviour.
                    // LearnDefaultSkills alone is not enough: it early-outs on any skill the
                    // player already HAS (Player.cpp:12112), so it grants nothing to an existing
                    // character. The spells hang off the skill, so the second pass is the one
                    // that matters -- and it walks the race/class creation skill list from
                    // ObjectMgr rather than indexing raw player fields, which is both safer and
                    // exactly the set login would have granted.
                    player->LearnDefaultSkills();
                    if (PlayerInfo const* info = sObjectMgr->GetPlayerInfo(player->getRace(),
                                                                          player->getClass()))
                        for (auto const& s : info->skills)
                            if (player->HasSkill(s.SkillId))
                                player->learnSkillRewardedSpells(s.SkillId,
                                                                 player->GetSkillValue(s.SkillId));

                    CloseGossipMenuFor(player);
                    ChatHandler(player->GetSession()).PSendSysMessage(
                        "Anything you were owed for your level has been taught.");
                    break;
                }

                default:
                    CloseGossipMenuFor(player);
                    break;
            }
            return true;
        }
    };
}

void AddSC_npc_talent_master()
{
    new npc_talent_master();
}
