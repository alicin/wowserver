# mod-toy-robot

A pocket robot that carries the bank, a vendor, the reagent stock, repair, the auction house, a
mailbox, a barber chair, the guild vault and the hunter stable. Every character is handed one at login.

Player-facing documentation is [`docs/utility-npcs.md`](../../../docs/utility-npcs.md) §7. This
file is the mechanics.

## Layout

```
build/modules/mod-toy-robot/
  conf/mod_toy_robot.conf.dist       REQUIRED — a module with no conf.dist never gets its .conf read
  src/toy_robot.h                    entries, npcflag contract, config struct, script declarations
  src/toy_robot.cpp                  the item, the gossip menu, the login grant, the boot audit
  src/toy_robot_loader.cpp           Addmod_toy_robotScripts()
  data/sql/db-world/base/2026_08_16_00_toy_robot.sql
  .gitignore                         re-includes data/ — read it before deleting it
```

Same conventions as `mod-utility-npcs` and `mod-dk-lowlevel`, for the same reasons: no
`CMakeLists.txt` (the core enumerates `modules/*/src` and globs it), a required
`conf/*.conf.dist`, and `data/` re-included by a local `.gitignore` because the repo root ignores
a bare `data/` at any depth.

No Dockerfile change was needed. `build/Dockerfile` already does `COPY modules/ /src/modules/`
after the clone loop.

Not in `build/modules.txt` — that file is the manifest of *cloned* third-party modules. Modules
versioned in this repo live here and are copied wholesale.

## The two entries

| what | entry | why that number |
|---|---:|---|
| `item_template` | 90000 | highest stock entry on this world DB is 57576; nothing ≥ 90000 exists |
| `creature_template` | 9000200 | follows 9000000 (Gabriella, mod-assistant) and 9000100 (Ysolde Ashgrave, mod-utility-npcs) |

Both are declared twice — in `src/toy_robot.h` and in the migration — and
`ToyRobotWorldScript::OnStartup` reconciles the two against the database the worldserver actually
booted on. There is no generator here because there are four constants, not 734 spawns.

## Three things this module does not build

**A spell.** The item carries stock spell **67826 (Jeeves)** and then cancels it.
`item_pocket_concierge::OnUse` returns `true`, which makes `WorldSession::HandleUseItemOpcode`
skip `CastItemUseSpell` entirely (`SpellHandler.cpp:196-201`); the summon is ours. A custom spell
would have to exist in the server's `Spell.dbc` *and* in every player's client copy, which means
another `patch-Z.MPQ` build and a redistribution — a large price for a tooltip.

The cost is that the tooltip a player reads is Jeeves's, and it undersells the toy by three
services. Verified against the client's own DBC with `mod-dk-lowlevel/tools/dbclib.py` rather than
assumed:

```
67826  "Jeeves"  Attributes=0  CastingTimeIndex=1  Effect_1=28 (SUMMON)  EffectMiscValue_1=35642
```

`Attributes = 0` matters twice. It means the spell has no `CANT_USED_IN_COMBAT` bit, so the
server's combat gate never fires for it and **the combat check in `OnUse` is load-bearing**. And
`EffectMiscValue_1 = 35642` is the real Jeeves — which is what the server would summon if the
script ever failed to bind, hence the boot audit on `ScriptName`.

**Vendor stock.** `SendListInventory` takes an optional `vendorEntry` which, when non-zero,
resolves the list through `sObjectMgr->GetNpcVendorItemList()` instead of the clicked creature's
own (`ItemHandler.cpp:883`), and `Player::BuyItemFromVendorSlot` honours the same override via
`GetCurrentVendor()` (`Player.cpp:10942`). So one creature serves two lists and this module owns
no `npc_vendor` rows at all. The two borrowed are the Traveler's Tundra Mammoth's pair — Blizzard's
own portable vendors, which is the right precedent:

| menu | entry | who | stock |
|---|---:|---|---|
| "Show me your wares" | 32638 | Hakmud of Argus, *Traveling Trader* | 26 items — WotLK food, drink, ammo, a bag |
| "I need reagents" | 32639 | Gnimo, *Adventurous Tinker* | 61 items — the complete reagent set, all classes, plus poisons, parchment, vials, thread |

Neither has any `conditions` rows (checked), so nothing silently filters out. Both are audited at
boot, because they are stock rows this module does not own and a world-DB update that retires
either one turns a menu entry into an empty window with no error anywhere.

**A mailbox gameobject.** A creature is a legal mailbox on this core — `MailHandler.cpp:55-57`
branches on `guid.IsAnyTypeCreature()` and checks `UNIT_NPC_FLAG_MAILBOX` alongside the
`GAMEOBJECT_TYPE_MAILBOX` branch. One npcflag bit, no object.

## The nine services split three ways

The split is the design, and the three groups behave completely differently.

**Six are one `WorldSession` call each, gated by an npcflag** — bank, vendor, reagents, auction
house, mailbox, stable.

**Repair is a flag with no call.** There is no repair opcode. The repair and repair-all buttons
live inside the client's `MerchantFrame` and are drawn from the npcflags the client holds for the
creature, so "repair" *is* "open the merchant window while carrying `REPAIR`". The core agrees —
`PlayerGossip.cpp:328-330` falls `GOSSIP_OPTION_ARMORER` through to the identical
`SendListInventory` as `GOSSIP_OPTION_VENDOR`. The separate menu entry exists only so the service
is discoverable.

**Two are gameobjects** — the guild vault and the barber chair. See the props section below.

## The npcflag is most of the feature

```
73535617 = GOSSIP 0x1 | VENDOR 0x80 | REPAIR 0x1000 | BANKER 0x20000
         | AUCTIONEER 0x200000 | STABLEMASTER 0x400000 | MAILBOX 0x4000000
```

Each npcflag-backed action re-validates the creature through
`Player::GetNPCIfCanInteractWith` with its **own** mask, so a dropped bit is one dead menu entry
and the rest working — a failure that looks like a half-finished feature rather than a bad row.
That is why the number is `static_assert`ed in the header against the literal in the SQL *and*
re-checked against the live row at boot.

Three consequences worth knowing:

* **Faction 35** (friendly to all, what every other utility NPC here uses) carries neither the
  Alliance nor the Horde mask, so `GetAuctionHouseEntryFromFactionTemplate` falls through to
  `AuctionHouseId::Neutral`. Both factions share one auction house through this robot. That is
  the intent, not an accident.
* **`type_flags = 2`** (`CREATURE_TYPE_FLAG_VISIBLE_TO_GHOSTS`) — without it a dead player cannot
  see or click the robot, and "check the mail while running back from a wipe" is exactly when a
  pocket mailbox earns its place.
* **`REPAIR` and the vendor mask are conditional client-side.** `Unit::PatchValuesUpdate`
  (`Unit.cpp:16910-16914`) strips both out of the npcflags sent to a given player when
  `Player::CanSeeVendor` is false, and for a creature with `gossip_menu_id 0` that reduces to
  "does `gossip_menu_option` MenuID 0 still carry a condition-free `GOSSIP_OPTION_VENDOR` row".
  It does today (verified: zero `conditions` rows with `SourceTypeOrReferenceId 15` and
  `SourceGroup 0`). If one is ever added, the shop and repair buttons vanish for players while
  the server keeps accepting both, with no log line anywhere — so `OnStartup` audits it.

Deliberately **not** set:

* `VENDOR_REAGENT 0x800` — the reagent menu validates against `VENDOR`, not the reagent bit.
* `INNKEEPER 0x10000` — set-hearthstone was offered and not asked for.
* `GUILD_BANKER 0x800000` — **a trap, not an omission.** `UnitDefines.h:345` documents it as
  "cause client to send 997 opcode": the client then sends `CMSG_GUILD_BANKER_ACTIVATE` carrying
  the *creature's* guid, and `GuildHandler.cpp:285` resolves it through
  `GetGameObjectIfCanInteractWith(..., GAMEOBJECT_TYPE_GUILD_BANK)`, which can never match a
  creature. It returns early with no packet at all — a menu entry that opens nothing.

## The two props, and three ways to get them wrong

Neither the guild vault nor the barber chair is an npcflag; both are `gameobject_template` rows
this module borrows and summons. Entries were picked for having the most live spawns of their
type and an empty `IconName` — `GetGameObjectIfCanInteractWith` returns `nullptr` for **any**
gameobject whose template `IconName` is `"Point"`, before it checks type or distance.

| prop | entry | type | note |
|---|---:|---|---|
| Guild vault | 187299 | 34 `GUILD_BANK` | 9 live spawns; interaction distance 10 yd |
| Barber chair | 191817 | 32 `BARBER_CHAIR` | 2 live spawns; `Data0` (chairheight) = 2; interaction distance 3 yd |

**1. The summoner must be the robot, not the player.** `WorldObject::SummonGameObject` ends in
`if (IsPlayer() || (IsCreature() && summonType == GO_SUMMON_TIMED_OR_CORPSE_DESPAWN))
AddGameObject(go); else go->SetSpawnedByDefault(false);`. A player summoner *always* takes the
first branch, which leaves `m_spawnedByDefault` true; `isSpawned()` is then false for the
object's whole life and `CanSeeOrDetect` refuses it to every observer. The prop would exist and
be **invisible**.

**2. `GO_SUMMON_TIMED_DESPAWN` is not the default, and the default is worse than wrong.** It is
the last of twelve parameters, so omitting it compiles and looks fine for thirty seconds. With
the default you get the invisibility above *and*, on expiry, `GameObject::Update` skips the
despawn branch and falls into `if (isSpawned())` — which by then is true forever. The prop
becomes **permanent**.

**3. `respawnTime` is seconds.** `SummonCreature`'s `despwtime`, three lines away in the same
file, is milliseconds. Passing `DurationSecs * IN_MILLISECONDS` would leave a guild vault standing
in Dalaran for three and a half days. Core scripts get this wrong too — `zone_undercity.cpp:2720`
passes `120 * IN_MILLISECONDS`.

### Why the vault is clicked and the chair is not

The **barber chair** is one action: `GameObject::Use`'s `GAMEOBJECT_TYPE_BARBER_CHAIR` case
teleports the player onto the chair, sends `SMSG_ENABLE_BARBER_SHOP`, and sets the stand state to
`UNIT_STAND_STATE_SIT_LOW_CHAIR + chairheight` — which is the same sum `HandleAlterAppearance`
re-derives on Accept. So the gossip handler places the chair and calls `Use` on it, and both gates
on the haircut are satisfied by that one teleport.

The **guild vault** cannot be opened from gossip at all, and this is impossible rather than
unattempted. Seven guild-bank handlers — activate, query tab, deposit, withdraw, swap, buy tab,
update tab — re-read a banker `ObjectGuid` as the first field of the packet and re-resolve it
through `GetGameObjectIfCanInteractWith`, and `SMSG_GUILD_BANK_LIST` carries no guid for the
client to learn one from. A client that never clicked an object has nothing valid to send, so the
window would open and then silently drop every deposit and withdrawal. So the handler places a
real vault and tells the player to click it.

## One robot per player, and no cooldown

Re-using the toy despawns your previous robot and places a new one, so there is no cooldown to
enforce and no per-player timer state to keep anywhere.

The previous robot is found by searching the caller's own grid for our entry and comparing
`TempSummon::GetSummonerGUID()`. A module-local `std::map<ObjectGuid, ObjectGuid>` would have been
the obvious alternative and is worse: it has to be kept correct across logout, map change, crash
and shutdown. The grid search cannot go stale.

## The login grant is a re-grant

`HasItemCount(90000, 1, true)` — bank included, because `maxcount 1` means a copy in the bank
would make `AddItem` fail every single login otherwise. There is no "already given" flag: destroy
the toy and the next login hands you another. No character can end up permanently without it, and
there is no extra table.

The cost is that a player who wants the bag slot back cannot have it. That is what
`ToyRobot.GrantOnLogin = 0` is for; existing copies keep working.

Per **character**, not per account — each character gets its own, and the item is
`bonding = 1` (bind on pickup) so it cannot be mailed to an alt anyway.

## Turning it off

`ToyRobot.Enable = 0` in `conf/modules/mod_toy_robot.conf` stops the grant, makes an existing copy
say so and do nothing, and silences the gossip menu. Nothing is deleted — `item_template` 90000
and `creature_template` 9000200 are data and stay in the world DB, and copies already in players'
bags stay there. Takes effect on `.reload config` for everything except robots already standing in
the world, which run out their timer.

To remove it entirely: drop this directory, then
`DELETE FROM item_template WHERE entry = 90000; DELETE FROM creature_template WHERE entry = 9000200;`
and delete the migration's row from the `updates` table. Copies in player inventories become
orphaned item GUIDs and are cleaned up by the core's own startup item check.
