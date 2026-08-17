/*
 * mod-toy-robot -- a pocket robot that carries the bank, a vendor, the reagent stock, the
 * auction house and a mailbox, granted to every character.
 *
 * THE SHAPE OF IT. One item (90000) which, on use, summons one creature (9000200) next to you
 * for five minutes. The creature's gossip menu is nine entries. There is no new bank, no new
 * auction house and no new mail store here -- the robot is mostly a set of npcflags standing
 * close enough to click.
 *
 * THE NINE SERVICES SPLIT THREE WAYS, and the split is the whole design:
 *   1. Six are ONE WorldSession CALL each, gated by an npcflag on the creature:
 *      bank, vendor, reagents, auction house, mailbox, stable.
 *   2. Repair is a FLAG WITH NO CALL. There is no repair opcode -- the repair buttons live
 *      inside the client's MerchantFrame and are drawn from the npcflags the client holds for
 *      the creature. So the "repair" entry just opens the merchant window, exactly as the core
 *      does for GOSSIP_OPTION_ARMORER (PlayerGossip.cpp:328-330 falls it through to the same
 *      SendListInventory as GOSSIP_OPTION_VENDOR).
 *   3. Two are GAMEOBJECTS, not npcflags -- the guild vault and the barber chair. Both are
 *      summoned props. See SummonProp in the .cpp; the gotchas there are severe and non-obvious.
 *
 * WHY THE ITEM BORROWS A STOCK SPELL AND THEN CANCELS IT. A custom spell would have to exist in
 * BOTH the server's Spell.dbc and every player's client copy, which on this realm means another
 * patch-Z.MPQ build and a redistribution to all three of them (docs/death-knights.md §457).
 * That is a large price for a tooltip. Instead the item carries spell 67826 -- Jeeves, the stock
 * WotLK engineering robot butler -- and item_pocket_concierge::OnUse returns true, which makes
 * WorldSession::HandleUseItemOpcode skip CastItemUseSpell entirely (SpellHandler.cpp:196-201).
 * The spell is never cast; it is there so the client has something real to render and to send.
 *
 * Verified against the client's own Spell.dbc via mod-dk-lowlevel/tools/dbclib.py rather than
 * assumed:
 *     67826  name "Jeeves"  Attributes=0  CastingTimeIndex=1  Effect_1=28 (SUMMON)
 *            EffectMiscValue_1=35642  <- the real Jeeves creature, which we do NOT summon
 *     description: "Requests the presence of Jeeves, the perfect gentleman robot butler, who
 *     will attend to your needs for $68054d. Jeeves can grant bank access ... and perform
 *     mundane tasks such as buying, selling, and repairing for anyone."
 *
 * So the tooltip a player reads is Jeeves's, and it undersells us by three services. That is the
 * whole cost of not shipping a DBC.
 *
 * Attributes = 0 means the stock spell has NO combat restriction, so the server-side combat gate
 * in HandleUseItemOpcode (which only fires for spells failing CanBeUsedInCombat) does not apply.
 * The combat check in OnUse is therefore ours and is load-bearing, not decoration.
 *
 * WHY THE VENDOR LISTS ARE BORROWED TOO. WorldSession::SendListInventory takes an optional
 * vendorEntry which, when non-zero, resolves the list through sObjectMgr->GetNpcVendorItemList()
 * instead of the clicked creature's own (ItemHandler.cpp:883), and Player::BuyItemFromVendorSlot
 * honours the same override via GetCurrentVendor() (Player.cpp:10942). So one creature serves two
 * different stock lists and neither needs a single npc_vendor row of our own. The two entries
 * borrowed are the Traveler's Tundra Mammoth's pair, which is exactly the right precedent --
 * they are Blizzard's own portable vendors:
 *     32638  Hakmud of Argus  "Traveling Trader"  26 items, WotLK food/drink/ammo/bags
 *     32639  Gnimo            "Adventurous Tinker" 61 items, the complete reagent set
 * Neither has any `conditions` rows (checked), so nothing silently filters out.
 */

#ifndef MOD_TOY_ROBOT_H_
#define MOD_TOY_ROBOT_H_

#include "Config.h"                 // sConfigMgr
#include "Creature.h"
#include "Log.h"
#include "ObjectMgr.h"              // sObjectMgr, for the boot audit
#include "Player.h"
#include "ScriptMgr.h"

namespace ToyRobot
{
    // These four numbers are the contract between this header and
    // data/sql/db-world/base/2026_08_16_00_toy_robot.sql. There is no generator here to keep the
    // two in step -- there are four constants, not 734 spawns -- so ToyRobotWorldScript::OnStartup
    // checks them against the database the worldserver actually booted on instead. Change one
    // here and the SQL fails the audit loudly on the next boot rather than quietly doing nothing.
    constexpr uint32 ITEM_ENTRY = 90000;        // "Pocket Concierge"
    constexpr uint32 NPC_ENTRY  = 9000200;      // "BUTL-R 9000", follows 9000000 / 9000100

    // Borrowed vendor lists -- see the header comment. Stock creature entries, not ours.
    constexpr uint32 VENDOR_GENERAL = 32638;    // Hakmud of Argus
    constexpr uint32 VENDOR_REAGENT = 32639;    // Gnimo

    // Borrowed gameobject_template rows, for the two services that are objects rather than
    // npcflags. Same deal as the vendor lists: stock rows we do not own, audited at boot.
    // Both picked for having the most live spawns of their type (i.e. the most proven-good on a
    // real client) and an empty IconName -- Player::GetGameObjectIfCanInteractWith returns
    // nullptr for ANY gameobject whose template IconName is "Point", before it even checks
    // distance, which would make the object un-clickable and produce no error anywhere.
    constexpr uint32 GO_GUILD_VAULT  = 187299;  // "Guild Vault", type 34, 9 live spawns
    constexpr uint32 GO_BARBER_CHAIR = 191817;  // "Barber Chair", type 32, 2 live spawns

    // gameobject_template.Data0 of GO_BARBER_CHAIR. GameObject::Use seats the player at
    // UNIT_STAND_STATE_SIT_LOW_CHAIR + chairheight and WorldSession::HandleAlterAppearance
    // re-derives the same sum when the haircut is accepted, so the two cannot disagree -- this
    // constant exists only so the boot audit notices if the borrowed row's Data0 ever moves.
    constexpr uint32 BARBER_CHAIRHEIGHT = 2;

    // The stock spell the item carries so the client has something to render. Never cast.
    constexpr uint32 BORROWED_SPELL = 67826;    // Jeeves

    // Every npcflag the five gossip options need. The gossip entries themselves are built in C++,
    // but the flags are NOT cosmetic: each of the five WorldSession calls re-validates the target
    // through Player::GetNPCIfCanInteractWith with the matching mask, so a missing bit here is a
    // menu entry that opens nothing.
    //   GOSSIP 0x1 | VENDOR 0x80 | REPAIR 0x1000 | BANKER 0x20000 | AUCTIONEER 0x200000
    //   | STABLEMASTER 0x400000 | MAILBOX 0x4000000
    //
    // Neither gameobject service appears here: GAMEOBJECT_TYPE_GUILD_BANK and
    // GAMEOBJECT_TYPE_BARBER_CHAIR are resolved through GetGameObjectIfCanInteractWith, which
    // never looks at a creature. In particular GUILD_BANKER 0x800000 is NOT set -- see the long
    // note in the SQL for why it is a trap rather than an omission.
    constexpr uint32 REQUIRED_NPCFLAGS =
        0x1 | 0x80 | 0x1000 | 0x20000 | 0x200000 | 0x400000 | 0x4000000;
    static_assert(REQUIRED_NPCFLAGS == 73535617u,
        "REQUIRED_NPCFLAGS no longer matches the npcflag literal in 2026_08_16_00_toy_robot.sql");

    enum Action : uint32
    {
        ACTION_BANK = 1,
        ACTION_VENDOR,
        ACTION_REAGENTS,
        ACTION_REPAIR,
        ACTION_AUCTION,
        ACTION_MAIL,
        ACTION_GUILDBANK,
        ACTION_BARBER,
        ACTION_STABLE,
    };
}

struct ToyRobotConfig
{
    // Defaults MUST match conf/mod_toy_robot.conf.dist. deploy/docker-compose.yml bind-mounts
    // conf/modules over /opt/ac/etc/modules as a DIRECTORY, which shadows the image's installed
    // .conf.dist entirely, and ConfigMgr::LoadModulesConfigs only ever opens `<name>.conf`. A key
    // absent from conf/modules/mod_toy_robot.conf falls back to the literal here, not to the
    // .dist -- the same trap documented at length in mod-utility-npcs.
    bool     Enable       = true;
    bool     GrantOnLogin = true;
    uint32   DurationSecs = 300;    // 5 minutes, to match what the borrowed Jeeves tooltip claims

    void Load();
};

extern ToyRobotConfig sToyRobot;

class ToyRobotWorldScript : public WorldScript
{
public:
    ToyRobotWorldScript() : WorldScript("ToyRobotWorldScript",
    {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD,
        WORLDHOOK_ON_STARTUP
    }) { }

    // WorldScript.h:28 and :35. NOT `OnWorldAfterConfigLoad` -- the OnPlayerXxx renaming on this
    // fork is PlayerScript-only. The hook list is explicit because WorldScript's constructor
    // treats an empty vector as "register for every hook" (WorldScript.cpp:87-96).
    void OnAfterConfigLoad(bool reload) override;
    void OnStartup() override;
};

class ToyRobotPlayerScript : public PlayerScript
{
public:
    // PlayerScript.h:230 takes the enabled-hook list as its second argument, and this script
    // wants exactly one of them. Same reasoning as WorldScript above: an empty list registers
    // against every dispatch list, and on a realm running playerbots that is not free.
    ToyRobotPlayerScript() : PlayerScript("ToyRobotPlayerScript", { PLAYERHOOK_ON_LOGIN }) { }

    // PlayerScript.h:337. `OnPlayerLogin`, not `OnLogin` -- this fork renamed the PlayerScript
    // hooks and the old name compiles fine while never being called.
    void OnPlayerLogin(Player* player) override;
};

#endif // MOD_TOY_ROBOT_H_
