/*
 * mod-toy-robot -- the item, the robot, the nine services, and the login grant.
 *
 * Read toy_robot.h first; it carries the design decisions (why the item borrows a stock spell,
 * why the vendor lists are borrowed, what the npcflags are for).
 */

#include "toy_robot.h"

#include "Chat.h"
#include "ConditionMgr.h"            // sConditionMgr, for the CanSeeVendor tripwire in the audit
#include "GameObject.h"              // GameObject::Use / ::Delete -- the two prop services call
                                     // both directly, so the complete type is required here
#include "ScriptedGossip.h"          // AddGossipItemFor et al; also pulls GossipDef.h for
                                     // GOSSIP_ICON_*, which is why they are not redeclared here
#include "TemporarySummon.h"         // TempSummon::GetSummonerGUID / UnSummon. Reachable via
                                     // ObjectMgr.h today, but this file is the one that needs
                                     // the complete type, so it asks for it directly.
#include "WorldSession.h"            // SendShowBank / SendListInventory / SendAuctionHello /
                                     // SendShowMailBox -- the whole feature, really

#include <cmath>                     // M_PI
#include <list>
#include <string_view>
#include <tuple>                     // std::tuple, for the borrowed-gameobject audit loop
#include <utility>                   // std::pair, for the borrowed-vendor audit loop

ToyRobotConfig sToyRobot;

void ToyRobotConfig::Load()
{
    Enable       = sConfigMgr->GetOption<bool>("ToyRobot.Enable", true);
    GrantOnLogin = sConfigMgr->GetOption<bool>("ToyRobot.GrantOnLogin", true);
    DurationSecs = sConfigMgr->GetOption<uint32>("ToyRobot.DurationSecs", 300);

    // A zero here would summon a TEMPSUMMON_TIMED_DESPAWN with a 0 ms timer, which despawns on
    // the first update tick -- the robot would appear and vanish before anyone could click it,
    // and it would read as "the toy is broken" rather than "the config is 0".
    if (DurationSecs == 0)
    {
        LOG_ERROR("server.loading",
            "mod-toy-robot: ToyRobot.DurationSecs = 0 would despawn the robot on its first tick. "
            "Using 300.");
        DurationSecs = 300;
    }

    // SummonCreature takes the despawn time as a uint32 of MILLISECONDS, so the seconds value
    // here is multiplied by 1000 before it gets there. Anything above ~4.29 million seconds wraps
    // and produces a near-instant despawn -- the same symptom as 0, arrived at from the opposite
    // direction and far harder to guess at. An hour is already well past any sane use.
    constexpr uint32 MAX_DURATION_SECS = 3600;
    if (DurationSecs > MAX_DURATION_SECS)
    {
        LOG_ERROR("server.loading",
            "mod-toy-robot: ToyRobot.DurationSecs = {} is above the {}s ceiling. Using {}.",
            DurationSecs, MAX_DURATION_SECS, MAX_DURATION_SECS);
        DurationSecs = MAX_DURATION_SECS;
    }
}

void ToyRobotWorldScript::OnAfterConfigLoad(bool reload)
{
    sToyRobot.Load();

    LOG_INFO("server.loading",
        "mod-toy-robot: Enable={} GrantOnLogin={} DurationSecs={} reload={} (item {}, npc {})",
        sToyRobot.Enable, sToyRobot.GrantOnLogin, sToyRobot.DurationSecs, reload,
        ToyRobot::ITEM_ENTRY, ToyRobot::NPC_ENTRY);
}

void ToyRobotWorldScript::OnStartup()
{
    // ----------------------------------------------------------------------------------------
    // The boot-time audit. Same argument as mod-utility-npcs's guid audit: the constants in
    // toy_robot.h were checked against a database on the day they were written, and this checks
    // them against the database this worldserver actually booted on, every boot.
    //
    // Every check here catches a SILENT failure -- something that leaves the worldserver running
    // happily while the feature quietly does the wrong thing or nothing at all. None of them
    // catch a crash, because none of these failures crash. That is the whole reason they exist.
    // ----------------------------------------------------------------------------------------

    // 1. Did the migration apply at all? UpdateFetcher runs before this, so a miss here that
    //    survives a restart means the module's data/ did not ship in the image -- the classic
    //    cause being the repo-root `data/` gitignore rule, see this module's .gitignore.
    ItemTemplate const* item = sObjectMgr->GetItemTemplate(ToyRobot::ITEM_ENTRY);
    if (!item)
    {
        LOG_ERROR("server.loading",
            "mod-toy-robot: item_template {} does not exist. 2026_08_16_00_toy_robot.sql has not "
            "applied (check the `updates` table), or the module's data/sql/ did not ship. Nothing "
            "will be granted and the toy cannot be used.", ToyRobot::ITEM_ENTRY);
    }
    else if (item->ScriptId != sObjectMgr->GetScriptId("item_pocket_concierge"))
    {
        // This is the nastiest failure mode in the module: the item exists, players get it,
        // right-clicking it casts Jeeves for real and summons Blizzard's Jeeves (creature 35642)
        // instead of ours -- which has no auction house, no mailbox and no reagent list. It
        // looks like a half-working feature rather than a misconfiguration.
        LOG_ERROR("server.loading",
            "mod-toy-robot: item_template {} exists but its ScriptName is not "
            "'item_pocket_concierge'. The use-handler will not run, so the item will cast the "
            "borrowed Jeeves spell for real and summon creature 35642 instead of {}.",
            ToyRobot::ITEM_ENTRY, ToyRobot::NPC_ENTRY);
    }

    // 2. The creature, and -- more easily got wrong -- its flags. Each npcflag-backed service
    //    re-validates through GetNPCIfCanInteractWith with its own mask, so a dropped bit is one
    //    dead menu entry and the rest working: a half-finished feature rather than a bad row.
    CreatureTemplate const* npc = sObjectMgr->GetCreatureTemplate(ToyRobot::NPC_ENTRY);
    if (!npc)
    {
        LOG_ERROR("server.loading",
            "mod-toy-robot: creature_template {} does not exist. Using the toy will summon "
            "nothing.", ToyRobot::NPC_ENTRY);
    }
    else if ((npc->npcflag & ToyRobot::REQUIRED_NPCFLAGS) != ToyRobot::REQUIRED_NPCFLAGS)
    {
        LOG_ERROR("server.loading",
            "mod-toy-robot: creature_template {} has npcflag {} but needs {} -- missing bits {}. "
            "The gossip entries for the missing services will open nothing.",
            ToyRobot::NPC_ENTRY, npc->npcflag, ToyRobot::REQUIRED_NPCFLAGS,
            ToyRobot::REQUIRED_NPCFLAGS & ~npc->npcflag);
    }

    // 3. The two borrowed vendor lists. These are stock world-DB rows this module does not own,
    //    which is exactly why they are worth checking: a world-DB update that retires Hakmud or
    //    Gnimo turns a menu entry into an empty vendor window with no error anywhere.
    for (auto const& [entry, what] : { std::pair<uint32, char const*>{ToyRobot::VENDOR_GENERAL, "general goods"},
                                       std::pair<uint32, char const*>{ToyRobot::VENDOR_REAGENT, "reagents"} })
    {
        VendorItemData const* items = sObjectMgr->GetNpcVendorItemList(entry);
        if (!items || items->Empty())
            LOG_ERROR("server.loading",
                "mod-toy-robot: borrowed {} vendor list (creature {}) is missing or empty. That "
                "menu entry will open an empty vendor window. Pick another entry in toy_robot.h.",
                what, entry);
        else
            LOG_INFO("server.loading",
                "mod-toy-robot: borrowed {} vendor list (creature {}): {} items.",
                what, entry, items->GetItemCount());
    }

    // 4. The two borrowed gameobject_template rows. Same argument as the vendor lists, with one
    //    extra check that has nothing to do with existence: Player::GetGameObjectIfCanInteractWith
    //    returns nullptr for ANY gameobject whose template IconName is the literal "Point",
    //    BEFORE it checks type or distance. A borrowed row that acquires that IconName in a
    //    world-DB update becomes permanently un-clickable and says nothing about it.
    for (auto const& [entry, wantType, what] :
         { std::tuple<uint32, uint32, char const*>{ToyRobot::GO_GUILD_VAULT,
                                                   GAMEOBJECT_TYPE_GUILD_BANK,  "guild vault"},
           std::tuple<uint32, uint32, char const*>{ToyRobot::GO_BARBER_CHAIR,
                                                   GAMEOBJECT_TYPE_BARBER_CHAIR, "barber chair"} })
    {
        GameObjectTemplate const* go = sObjectMgr->GetGameObjectTemplate(entry);
        if (!go)
            LOG_ERROR("server.loading",
                "mod-toy-robot: borrowed {} gameobject_template {} does not exist. That menu "
                "entry will place nothing.", what, entry);
        else if (go->type != wantType)
            LOG_ERROR("server.loading",
                "mod-toy-robot: borrowed {} gameobject_template {} is type {}, expected {}. It "
                "will spawn and every click on it will be ignored.", what, entry, go->type, wantType);
        else if (go->IconName == "Point")
            LOG_ERROR("server.loading",
                "mod-toy-robot: borrowed {} gameobject_template {} has IconName 'Point', which "
                "makes GetGameObjectIfCanInteractWith reject it outright. Pick another entry.",
                what, entry);
        else
            LOG_INFO("server.loading",
                "mod-toy-robot: borrowed {} gameobject {} ok (type {}).", what, entry, go->type);
    }

    // 5. The chair height the barber path depends on. Cosmetic drift only -- GameObject::Use and
    //    HandleAlterAppearance both read Data0, so they cannot disagree with each other. This
    //    catches the CONSTANT in toy_robot.h going stale, not a real failure.
    if (GameObjectTemplate const* chair = sObjectMgr->GetGameObjectTemplate(ToyRobot::GO_BARBER_CHAIR))
        if (chair->type == GAMEOBJECT_TYPE_BARBER_CHAIR
            && chair->barberChair.chairheight != ToyRobot::BARBER_CHAIRHEIGHT)
            LOG_INFO("server.loading",
                "mod-toy-robot: barber chair {} chairheight is {}, toy_robot.h says {}. Harmless "
                "-- the two consumers both read the row -- but the constant is stale.",
                ToyRobot::GO_BARBER_CHAIR, chair->barberChair.chairheight,
                ToyRobot::BARBER_CHAIRHEIGHT);

    // 6. The tripwire that silently removes the vendor AND repair buttons from the client.
    //    Unit::PatchValuesUpdate (Unit.cpp:16910-16914) strips UNIT_NPC_FLAG_REPAIR and the whole
    //    vendor mask out of the npcflags sent to a player when Player::CanSeeVendor is false, and
    //    for a creature with gossip_menu_id 0 that reduces to "does menu 0 still offer a
    //    condition-free GOSSIP_OPTION_VENDOR row". It does today. If a conditions row is ever
    //    added against it, the shop and the repair button vanish for players while the server
    //    happily keeps accepting both -- there is no log line anywhere on that path.
    {
        // CanSeeVendor has two legs and this is the first: a conditions row hung on OUR entry as
        // an npc_vendor condition (SourceTypeOrReferenceId 23, SourceGroup = our entry,
        // SourceEntry 0) fails the whole check before the menu is ever consulted. We own entry
        // 9000200 and add no such row, so this is a tripwire for somebody else's data, not ours.
        if (!sConditionMgr->GetConditionsForNpcVendorEvent(ToyRobot::NPC_ENTRY, 0).empty())
            LOG_INFO("server.loading",
                "mod-toy-robot: creature {} has npc_vendor conditions attached. Player::CanSeeVendor "
                "evaluates them per player, so the shop and repair buttons may be hidden for some "
                "characters.", ToyRobot::NPC_ENTRY);

        GossipMenuItemsMapBounds const bounds = sObjectMgr->GetGossipMenuItemsMapBounds(0);

        // An EMPTY menu 0 is fine, and getting this backwards would produce a boot error on a
        // perfectly healthy realm: AnyVendorOptionAvailable's first act is
        //     if (menuItemBounds.first == menuItemBounds.second) return true;
        // so no rows at all means "yes, visible". Only a populated menu 0 that offers no usable
        // vendor option is a problem.
        if (bounds.first != bounds.second)
        {
            bool unconditional = false;
            bool conditional   = false;
            for (auto itr = bounds.first; itr != bounds.second; ++itr)
                if (itr->second.OptionType == GOSSIP_OPTION_VENDOR)
                {
                    if (itr->second.Conditions.empty())
                        unconditional = true;
                    else
                        conditional = true;
                }

            if (!unconditional && !conditional)
                LOG_ERROR("server.loading",
                    "mod-toy-robot: gossip_menu_option MenuID 0 is populated but has no "
                    "GOSSIP_OPTION_VENDOR row, so Player::CanSeeVendor is false for creature {} "
                    "and the client is sent npcflags with VENDOR and REPAIR removed. The shop and "
                    "repair buttons will not appear, though the server would still accept both.",
                    ToyRobot::NPC_ENTRY);
            else if (!unconditional)
                // Conditions are evaluated PER PLAYER, so this is not decidable at boot -- it is
                // a heads-up, not a verdict. Some characters may see the buttons and others not.
                LOG_INFO("server.loading",
                    "mod-toy-robot: every GOSSIP_OPTION_VENDOR row on MenuID 0 carries conditions. "
                    "CanSeeVendor is then per-player, so the shop and repair buttons may be absent "
                    "for some characters. Nothing is wrong at boot; check in game if reported.");
        }
    }
}

void ToyRobotPlayerScript::OnPlayerLogin(Player* player)
{
    if (!sToyRobot.Enable || !sToyRobot.GrantOnLogin)
        return;

    // inBankAlso = true. The item is maxcount 1, so a copy sitting in the bank would make AddItem
    // fail with EQUIP_ERR_CANT_CARRY_MORE_OF_THIS anyway -- checking the bank turns that into "do
    // nothing" instead of "fail every single login".
    if (player->HasItemCount(ToyRobot::ITEM_ENTRY, 1, true))
        return;

    // This is deliberately a re-grant, not a one-time gift: destroy the toy, log back in, get
    // another. There is no per-character "already given" flag to keep, no extra table, and no way
    // to end up permanently without it. The cost is that a player who genuinely wants the bag
    // slot back cannot have it -- which is what ToyRobot.GrantOnLogin is for.
    if (!player->AddItem(ToyRobot::ITEM_ENTRY, 1))
    {
        // AddItem fails on a full inventory. Say so rather than failing silently, because the
        // retry is automatic and the player only needs to know to make room.
        //
        // string_view for the same reason as item_pocket_concierge::Reject: a bare char const*
        // binds to the fmt-formatting template overload instead of the plain one.
        ChatHandler(player->GetSession()).PSendSysMessage(
            std::string_view("Your Pocket Concierge could not be delivered - your bags are full. "
                             "Make a slot and log in again."));
    }
}

namespace
{
    // Put one of the robot's two prop gameobjects on the ground beside it, replacing any earlier
    // copy of the same prop. Both props exist because the service behind them is a GAMEOBJECT
    // rather than an npcflag, and neither can be conjured from a packet.
    //
    // THREE THINGS HERE ARE LOAD-BEARING AND NONE OF THEM ARE OBVIOUS.
    //
    // 1. THE SUMMONER MUST BE THE ROBOT, NOT THE PLAYER. WorldObject::SummonGameObject ends in
    //        if (IsPlayer() || (IsCreature() && summonType == GO_SUMMON_TIMED_OR_CORPSE_DESPAWN))
    //            ToUnit()->AddGameObject(go);
    //        else
    //            go->SetSpawnedByDefault(false);
    //    A player summoner ALWAYS takes the first branch, which leaves m_spawnedByDefault true;
    //    GameObject::isSpawned() is then false for the object's whole life, IsInvisibleDueToDespawn
    //    is true, and CanSeeOrDetect refuses it to every observer. The prop would exist, be
    //    interactable in principle, and be invisible. Summoning from the creature with the type
    //    below takes the else branch instead.
    //
    // 2. GO_SUMMON_TIMED_DESPAWN IS NOT THE DEFAULT, and the default is worse than wrong. It is
    //    the last of twelve parameters, so leaving it off compiles and looks fine for the first
    //    thirty seconds. With the default, the same first branch is taken (invisible, as above)
    //    AND on expiry GameObject::Update skips the despawn branch and falls into `if
    //    (isSpawned())` -- which by then evaluates true, forever. The prop becomes PERMANENT.
    //
    // 3. respawnTime IS SECONDS. SummonCreature's despwtime, three lines away in this same file,
    //    is milliseconds. Passing DurationSecs * IN_MILLISECONDS here would leave a guild vault
    //    standing in Dalaran for three and a half days. Core scripts get this wrong too --
    //    zone_undercity.cpp:2720 passes `120 * IN_MILLISECONDS`.
    GameObject* SummonProp(Creature* robot, Player* player, uint32 entry, uint32 seconds)
    {
        // Replace this robot's previous copy of the prop rather than stacking a second one.
        //
        // THE GetSpawnId() TEST IS NOT A REFINEMENT, IT IS THE WHOLE SAFETY ARGUMENT. Searching
        // by entry alone finds PERMANENT WORLD SPAWNS of the same entry, and Delete() does not
        // care where an object came from -- it ends in AddObjectToRemoveList(). Entry 187299 has
        // nine live rows in `gameobject` (Dalaran guid 59749, Shattrath 42953/42954, Gadgetzan
        // 17352/17353, Booty Bay 50356/50357, Ratchet 14641, Dalaran-Northrend 49095) and 191817
        // has two (Shattrath 505, Silvermoon 504). Without this test, a player standing in
        // Dalaran who asked the robot for a guild vault would have DELETED THE REAL ONE, for
        // everybody. m_spawnId is non-zero only for objects loaded from the `gameobject` table
        // (GameObject.h:144), so zero means "something summoned this" and is the exact line
        // between our furniture and the world's.
        //
        // The radius is small for the same reason it is centred on the robot: our prop is always
        // placed two yards off the robot's flank, so five yards is enough to find ours and tight
        // enough not to reach across a room. Residual case, accepted on a three-player realm: two
        // people using the SAME robot share one prop, and the second one to ask replaces the
        // first's. The guild vault does not care -- it opens the clicker's own guild bank either
        // way -- but it will close an open bank window belonging to the other player.
        std::list<GameObject*> existing;
        robot->GetGameObjectListWithEntryInGrid(existing, entry, 5.0f);
        for (GameObject* old : existing)
            if (!old->GetSpawnId())
                old->Delete();

        float x, y, z;
        // Off to the robot's left rather than in front of it, so the prop does not land on top of
        // the player who is standing there reading its gossip menu.
        robot->GetClosePoint(x, y, z, robot->GetObjectSize(), 2.0f, static_cast<float>(M_PI_2));

        return robot->SummonGameObject(entry, x, y, z, player->GetOrientation() + static_cast<float>(M_PI),
                                       0.0f, 0.0f, 0.0f, 0.0f, seconds,
                                       true, GO_SUMMON_TIMED_DESPAWN);
    }

    class item_pocket_concierge : public ItemScript
    {
    public:
        item_pocket_concierge() : ItemScript("item_pocket_concierge") { }

        bool OnUse(Player* player, Item* item, SpellCastTargets const& /*targets*/) override
        {
            // Returning FALSE here means "not handled" and lets HandleUseItemOpcode fall through
            // to CastItemUseSpell -- which would cast Jeeves for real and summon creature 35642.
            // So every path out of this function that is not a successful summon must still
            // return true. There is no safe `return false`.
            if (!sToyRobot.Enable)
            {
                Reject(player, item, "The Pocket Concierge is switched off on this realm.");
                return true;
            }

            // The borrowed spell has Attributes = 0, so it has no SPELL_ATTR0_CANT_USED_IN_COMBAT
            // bit and the server's own combat gate in HandleUseItemOpcode never fires for it.
            // Without this check a player could park a bank in the middle of a boss fight.
            if (player->IsInCombat())
            {
                Reject(player, item, "You cannot call the Pocket Concierge while in combat.");
                return true;
            }

            // One robot per player. Re-using the toy replaces rather than accumulates, which
            // means there is no cooldown to enforce and no per-player timer state to keep.
            //
            // Keyed on the summoner rather than on a map of our own: the search is over the
            // caller's own grid for our entry only, and TempSummon::GetSummonerGUID is the
            // authoritative link. A module-local std::map would have to be kept correct across
            // logout, map change, crash and shutdown; this cannot go stale.
            std::list<Creature*> existing;
            player->GetCreatureListWithEntryInGrid(existing, ToyRobot::NPC_ENTRY, 100.0f);
            for (Creature* c : existing)
                if (TempSummon* summon = c->ToTempSummon())
                    if (summon->GetSummonerGUID() == player->GetGUID())
                        summon->UnSummon();

            float x, y, z;
            // Two yards out, on the player's own facing, offset by the pair's collision size so
            // the robot does not spawn inside them. GetClosePoint does the terrain and LOS work;
            // hand-computing x/y from a sin/cos is what puts NPCs inside walls.
            player->GetClosePoint(x, y, z, player->GetObjectSize(), 2.0f);

            // + pi so the robot faces back at the player. M_PI is a double and Position takes
            // floats; the cast is explicit so the narrowing is a decision rather than a warning.
            Position const pos(x, y, z, static_cast<float>(player->GetOrientation() + M_PI));

            if (!player->SummonCreature(ToyRobot::NPC_ENTRY, pos, TEMPSUMMON_TIMED_DESPAWN,
                                        sToyRobot.DurationSecs * IN_MILLISECONDS))
            {
                Reject(player, item, "The Pocket Concierge could not unfold here.");
                return true;
            }

            // The item is left in the client's "pending cast" grey state by the suppressed cast.
            // EQUIP_ERR_NONE is the core's own idiom for clearing it -- see the note at
            // SpellHandler.cpp:195 and item_petrov_cluster_bombs (item_scripts.cpp:160).
            player->SendEquipError(EQUIP_ERR_NONE, item, nullptr);
            return true;
        }

    private:
        // Every rejection has to do both halves: un-grey the item AND say why. Doing only the
        // first leaves the player clicking a toy that does nothing.
        //
        // std::string_view, not char const*, and that is not style. ChatHandler has BOTH a
        // non-template PSendSysMessage(std::string_view) and a variadic template
        // PSendSysMessage(char const* fmt, Args&&...) which forwards to Acore::StringFormat ->
        // fmt::vformat. A char const* argument is an exact match for the template, so it wins
        // overload resolution and the message gets treated as a FORMAT STRING. That is fmt, not
        // printf, so the classic `PSendSysMessage("%s", text)` silently prints the literal "%s" --
        // vformat has no replacement field to fill and quietly ignores the extra argument. It
        // compiles, it runs, and it is wrong. Passing a string_view picks the non-template
        // overload, which formats nothing.
        static void Reject(Player* player, Item* item, std::string_view why)
        {
            player->SendEquipError(EQUIP_ERR_NONE, item, nullptr);
            ChatHandler(player->GetSession()).PSendSysMessage(why);
        }
    };

    class npc_pocket_concierge : public CreatureScript
    {
    public:
        npc_pocket_concierge() : CreatureScript("npc_pocket_concierge") { }

        bool OnGossipHello(Player* player, Creature* creature) override
        {
            // NOT `return false` when disabled, which is what this used to do and which was
            // wrong in two directions. Returning false hands the click to
            // Player::PrepareGossipMenu, which builds the DEFAULT menu from gossip_menu_option
            // MenuID 0 filtered by our npcflags -- so a "disabled" robot would have offered a
            // working bank, shop, auction house, stable and repair. It is also the only path that
            // reaches Creature::isVendorWithIconSpeak, which is a null dereference on a
            // TempSummon (see the IconName note in the SQL). An empty menu is what disabled
            // should look like, and it keeps us out of the core's menu builder entirely.
            if (!sToyRobot.Enable)
            {
                SendGossipMenuFor(player, DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
                return true;
            }

            // Unconditional entries first and in a fixed order, conditional ones last, so that a
            // hunter's menu and a mage's menu agree on the position of everything above them --
            // muscle memory for "third option is reagents" should not depend on your class.
            AddGossipItemFor(player, GOSSIP_ICON_MONEY_BAG, "Open my bank",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_BANK);
            AddGossipItemFor(player, GOSSIP_ICON_VENDOR,    "Show me your wares",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_VENDOR);
            AddGossipItemFor(player, GOSSIP_ICON_VENDOR,    "I need reagents",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_REAGENTS);
            AddGossipItemFor(player, GOSSIP_ICON_VENDOR,    "Repair my equipment",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_REPAIR);
            AddGossipItemFor(player, GOSSIP_ICON_MONEY_BAG, "Open the auction house",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_AUCTION);
            AddGossipItemFor(player, GOSSIP_ICON_INTERACT_1, "Open my mailbox",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_MAIL);
            AddGossipItemFor(player, GOSSIP_ICON_INTERACT_1, "Set down the barber chair",
                             GOSSIP_SENDER_MAIN, ToyRobot::ACTION_BARBER);

            // Guild vault only for the guilded. GetGuildId() is a plain field read; GetGuild()
            // would do a GuildMgr lookup to answer the same question. Offering it to everyone
            // would place a vault that answers ERR_GUILD_PLAYER_NOT_IN_GUILD after the player has
            // already walked over and clicked it.
            if (player->GetGuildId())
                AddGossipItemFor(player, GOSSIP_ICON_MONEY_BAG, "Set down the guild vault",
                                 GOSSIP_SENDER_MAIN, ToyRobot::ACTION_GUILDBANK);

            // Stable only for hunters, and this gate is the ONLY thing preventing a real loss:
            // WorldSession::HandleBuyStableSlot has no class check of its own, so a non-hunter
            // who reaches the panel can buy stable slots -- hundreds of gold across all four --
            // that they can never use.
            // IsClass(..., CLASS_CONTEXT_PET) rather than getClass() is what the core's own
            // GOSSIP_OPTION_STABLEPET case uses (PlayerGossip.cpp:112-115).
            if (player->IsClass(CLASS_HUNTER, CLASS_CONTEXT_PET))
                AddGossipItemFor(player, GOSSIP_ICON_CHAT, "Stable my pet",
                                 GOSSIP_SENDER_MAIN, ToyRobot::ACTION_STABLE);

            SendGossipMenuFor(player, DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
            return true;
        }

        bool OnGossipSelect(Player* player, Creature* creature, uint32 /*sender*/,
                            uint32 action) override
        {
            if (!sToyRobot.Enable)
                return false;

            ClearGossipMenuFor(player);

            // THE COMBAT GATE HAS TO BE HERE TOO, not only on the item. item_pocket_concierge::
            // OnUse refuses to summon in combat, and on its own that stops nothing: the robot
            // lasts five minutes, so summoning it in the corridor and pulling the boss to it
            // reaches every service on this menu mid-fight -- which is exactly the "park a bank
            // in the middle of a boss fight" the OnUse comment claims to prevent. None of the
            // core handlers behind these services check combat either (GetNPCIfCanInteractWith
            // tests flight, death, faction and range, never combat), so if we do not do it, it
            // is not done.
            if (player->IsInCombat())
            {
                CloseGossipMenuFor(player);
                ChatHandler(player->GetSession()).PSendSysMessage(
                    std::string_view("BUTL-R 9000 will not serve you in combat."));
                return true;
            }

            // The six npcflag-backed services re-validate the creature through
            // Player::GetNPCIfCanInteractWith with their own mask, so none of them can be reached
            // by a client that fabricates a gossip action against something else. That is also
            // why REQUIRED_NPCFLAGS is audited at boot. The two gameobject services validate the
            // same way but through GetGameObjectIfCanInteractWith against the prop, not the
            // robot, and repair has nothing to validate because it sends no packet of its own.
            //
            // The menu is closed BEFORE each call, not after: SendShowBank and friends open a
            // client window anchored to the same creature, and leaving the gossip frame up means
            // the bank opens behind it.
            switch (action)
            {
                case ToyRobot::ACTION_BANK:
                    CloseGossipMenuFor(player);
                    player->GetSession()->SendShowBank(creature->GetGUID());
                    break;

                case ToyRobot::ACTION_VENDOR:
                    CloseGossipMenuFor(player);
                    player->GetSession()->SendListInventory(creature->GetGUID(),
                                                            ToyRobot::VENDOR_GENERAL);
                    break;

                case ToyRobot::ACTION_REAGENTS:
                    CloseGossipMenuFor(player);
                    player->GetSession()->SendListInventory(creature->GetGUID(),
                                                            ToyRobot::VENDOR_REAGENT);
                    break;

                case ToyRobot::ACTION_AUCTION:
                    CloseGossipMenuFor(player);
                    // Resolves the house from the creature's faction template, and faction 35 has
                    // neither the Alliance nor the Horde mask, so it falls through to
                    // AuctionHouseId::Neutral (AuctionHouseMgr.cpp) -- the goblin AH, usable by
                    // both sides. That is the correct house for a faction-neutral robot.
                    player->GetSession()->SendAuctionHello(creature->GetGUID(), creature);
                    break;

                case ToyRobot::ACTION_MAIL:
                    CloseGossipMenuFor(player);
                    // A CREATURE is a legal mailbox on this core: MailHandler.cpp:55-57 branches
                    // on guid.IsAnyTypeCreature() and checks UNIT_NPC_FLAG_MAILBOX, alongside the
                    // GAMEOBJECT_TYPE_MAILBOX branch. No gameobject needed.
                    player->GetSession()->SendShowMailBox(creature->GetGUID());
                    break;

                case ToyRobot::ACTION_REPAIR:
                    CloseGossipMenuFor(player);
                    // Deliberately identical to ACTION_VENDOR, and not redundant. There is no
                    // repair opcode to send: the repair and repair-all buttons are drawn by the
                    // client inside MerchantFrame from the npcflags it holds for this creature,
                    // so "repair" IS "open the merchant window while carrying REPAIR". The core
                    // agrees -- PlayerGossip.cpp:328-330 falls GOSSIP_OPTION_ARMORER through to
                    // the same SendListInventory as GOSSIP_OPTION_VENDOR. The entry exists as its
                    // own line purely so the service is discoverable.
                    //
                    // The vendorEntry argument is load-bearing here exactly as it is for the shop:
                    // passing 0 would resolve to this creature's own (nonexistent) vendor list and
                    // the client would get "vendor has no inventory" with no window at all -- and
                    // therefore no repair button either.
                    player->GetSession()->SendListInventory(creature->GetGUID(),
                                                            ToyRobot::VENDOR_GENERAL);
                    break;

                case ToyRobot::ACTION_STABLE:
                    CloseGossipMenuFor(player);
                    // THE DISMOUNT IS NOT OPTIONAL AND IT IS NOT COSMETIC.
                    //
                    // Calling SendStablePet directly is what the core's own gossip path does, but
                    // the core reaches it through WorldSession::HandleStablePet, which does this
                    // first (NPCHandler.cpp:347-350) under the comment:
                    //     "remove mounts this fix bug where getting pet from stable while mounted
                    //      deletes pet."
                    // Going straight to SendStablePet skips that guard, which would make this
                    // robot the one stable master in the game capable of eating a hunter's pet.
                    // So we reproduce it.
                    //
                    // The visible consequence is that asking for the stable dismounts you, which
                    // on a flying mount is a fall -- hence the menu entry reads "Stable my pet"
                    // rather than anything that invites a curious click.
                    if (player->IsMounted())
                        player->RemoveAurasByType(SPELL_AURA_MOUNTED);

                    player->GetSession()->SendStablePet(creature->GetGUID());
                    break;

                case ToyRobot::ACTION_GUILDBANK:
                {
                    CloseGossipMenuFor(player);
                    // THE VAULT CANNOT BE OPENED FROM HERE, and that is not a shortcut not taken
                    // -- it is impossible. Seven of the guild-bank handlers (activate, query tab,
                    // deposit, withdraw, swap, buy tab, update tab) re-read a banker ObjectGuid
                    // as the first field of the packet and re-resolve it through
                    // GetGameObjectIfCanInteractWith(..., GAMEOBJECT_TYPE_GUILD_BANK), and
                    // SMSG_GUILD_BANK_LIST carries no guid for the client to learn one from. A
                    // client that never clicked an object has nothing valid to send, so the
                    // window would open and then silently drop every deposit and withdrawal.
                    // The player has to click a real object. So we put one down.
                    GameObject* vault = SummonProp(creature, player, ToyRobot::GO_GUILD_VAULT,
                                                   sToyRobot.DurationSecs);
                    if (!vault)
                    {
                        ChatHandler(player->GetSession()).PSendSysMessage(
                            std::string_view("The guild vault could not be unfolded here."));
                        break;
                    }

                    ChatHandler(player->GetSession()).PSendSysMessage(
                        std::string_view("The guild vault is beside me - click it to open your "
                                         "guild bank. Stay within ten yards of it, and finish "
                                         "within five minutes: once it folds away, deposits stop "
                                         "working with no warning."));
                    break;
                }

                case ToyRobot::ACTION_BARBER:
                {
                    CloseGossipMenuFor(player);
                    // The barber, unlike the vault, IS one action. GameObject::Use's
                    // GAMEOBJECT_TYPE_BARBER_CHAIR case does all three things the haircut needs:
                    // it teleports the player onto the chair, sends SMSG_ENABLE_BARBER_SHOP, and
                    // sets the stand state to UNIT_STAND_STATE_SIT_LOW_CHAIR + chairheight --
                    // which is the same sum HandleAlterAppearance re-derives when the player
                    // clicks Accept. So we place the chair and sit them in it ourselves.
                    //
                    // Both of the gates on the Accept are satisfied by that teleport: the chair
                    // has to be within 5 yards at commit time and the stand state has to match.
                    // Both break if the player walks away mid-haircut, which is also true of
                    // every barbershop in the game.
                    GameObject* chair = SummonProp(creature, player, ToyRobot::GO_BARBER_CHAIR,
                                                   sToyRobot.DurationSecs);
                    if (!chair)
                    {
                        ChatHandler(player->GetSession()).PSendSysMessage(
                            std::string_view("The barber chair could not be unfolded here."));
                        break;
                    }

                    chair->Use(player);
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

void AddSC_toy_robot()
{
    // Registered with `new` and never deleted -- ScriptMgr owns script objects for the lifetime
    // of the process. Convention every module and core script follows.
    new ToyRobotWorldScript();
    new ToyRobotPlayerScript();
    new item_pocket_concierge();
    new npc_pocket_concierge();
}
