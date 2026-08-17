-- mod-toy-robot: the Pocket Concierge item and the robot it unfolds into.
--
-- Two entries, both in ranges this repo owns and both checked free against the live world DB
-- before they were picked:
--     item_template     90000     highest stock entry on this DB is 57576; nothing >= 90000 exists
--     creature_template 9000200   follows 9000000 (Gabriella, mod-assistant) and 9000100
--                                 (Ysolde Ashgrave, mod-utility-npcs)
--
-- Both entries are ALSO declared in src/toy_robot.h, and ToyRobotWorldScript::OnStartup audits
-- this file's rows against those constants on every boot -- including the npcflag bits and the
-- ScriptName, which are the two things that fail silently rather than loudly.
--
-- Column lists verified against SHOW COLUMNS on this exact revision. Notably creature_template
-- has no `scale` column (that is creature_template_model.DisplayScale), which is the kind of
-- thing a copied-from-a-wiki INSERT gets wrong and only discovers at apply time.
--
-- Re-runnable: DELETE-then-INSERT on a single key, like every other file in this repo.
--
-- NOT IN THIS FILE, deliberately: any npc_vendor rows. The robot's two shop menus borrow the
-- Traveler's Tundra Mammoth's vendor lists (32638 Hakmud of Argus for general goods, 32639 Gnimo
-- for reagents) through SendListInventory's vendorEntry override. See src/toy_robot.h.


-- ---------------------------------------------------------------------------------- the item ---

DELETE FROM `item_template` WHERE `entry` = 90000;
INSERT INTO `item_template`
  (`entry`, `class`, `subclass`, `SoundOverrideSubclass`, `name`, `displayid`, `Quality`, `Flags`,
   `BuyCount`, `BuyPrice`, `SellPrice`, `InventoryType`, `AllowableClass`, `AllowableRace`,
   `ItemLevel`, `RequiredLevel`, `RequiredSkill`, `RequiredSkillRank`, `maxcount`, `stackable`,
   `spellid_1`, `spelltrigger_1`, `spellcharges_1`, `spellcooldown_1`, `spellcategory_1`,
   `spellcategorycooldown_1`, `bonding`, `description`, `Material`, `sheath`, `ScriptName`)
VALUES
  (90000,
   -- 15 = ITEM_CLASS_MISCELLANEOUS, subclass 0 = Junk. What every other 3.3.5a toy is.
   15, 0, -1,
   'Pocket Concierge',
   -- 61018 is the item display Jeeves (item 49040) uses on this realm, so it is known-good on
   -- this client rather than a display id copied from a wiki that may not exist in 3.3.5a.
   61018,
   -- 4 = epic. It is a permanent account-wide utility, not a grey.
   4,
   -- 64 = ITEM_FLAG_PLAYERCAST. Copied from Jeeves because we carry Jeeves's spell; it tells the
   -- client the item's spell is player-castable. Deliberately NOT 32 (NO_USER_DESTROY): a player
   -- who wants the bag slot back should be able to destroy it, and ToyRobot.GrantOnLogin = 0 is
   -- how you stop it coming straight back.
   64,
   1,
   -- Free, and worth nothing at a vendor. SellPrice 0 means it cannot be turned into gold, which
   -- also means mod-junk-to-gold has nothing to do with it.
   0, 0,
   -- 0 = INVTYPE_NON_EQUIP.
   0,
   -- -1/-1 = every class, every race.
   -1, -1,
   1, 1,
   -- No engineering requirement, unlike the Jeeves whose spell we borrow.
   0, 0,
   -- maxcount 1 makes it unique-carry. This is what lets the login grant be a simple
   -- HasItemCount check instead of bookkeeping: a second copy cannot exist to be confused about.
   1, 1,
   -- 67826 = Jeeves. Present in this client's Spell.dbc (verified with
   -- mod-dk-lowlevel/tools/dbclib.py against .work/out/dbc/Spell.dbc) and in the server's, which
   -- HandleUseItemOpcode requires -- it rejects the packet outright on an unknown spell id
   -- (SpellHandler.cpp:88-94). The spell is NEVER CAST: item_pocket_concierge::OnUse returns
   -- true, which makes the handler skip CastItemUseSpell. It exists so the client has a real
   -- spell to render a tooltip from and to name in CMSG_USE_ITEM.
   67826,
   -- 0 = ITEM_SPELLTRIGGER_ON_USE.
   0,
   -- 0 charges = unlimited uses.
   0,
   -- -1/-1 = no cooldown and no category cooldown. Nothing enforces them anyway once the cast is
   -- suppressed; using the toy again despawns your previous robot rather than stacking one.
   -1, 0, -1,
   -- 1 = BIND_WHEN_PICKED_UP. Soulbound, so it cannot be traded or mailed to an alt -- every
   -- character gets its own from the login grant.
   1,
   'Unfolds into a small robot of impeccable manners and questionable structural engineering.',
   -- 1 = Metal, which is the pick-up sound. Jeeves uses 4 (Jewelry); a robot is metal.
   1, 0,
   'item_pocket_concierge');


-- ------------------------------------------------------------------------------- the creature ---

DELETE FROM `creature_template` WHERE `entry` = 9000200;
INSERT INTO `creature_template`
  (`entry`, `name`, `subname`, `IconName`, `gossip_menu_id`, `minlevel`, `maxlevel`,
   `faction`, `npcflag`, `unit_class`, `unit_flags`, `type`, `type_flags`,
   `RegenHealth`, `flags_extra`, `AIName`, `MovementType`, `ScriptName`)
VALUES
  (9000200, 'BUTL-R 9000', 'Pocket Concierge',
   -- IconName IS DELIBERATELY EMPTY, AND 'Speak' HERE IS A WORLDSERVER CRASH.
   -- Creature::isVendorWithIconSpeak (Creature.cpp:1672-1675) is
   --     return m_creatureInfo->IconName == "Speak" && m_creatureData->npcflag & UNIT_NPC_FLAG_VENDOR;
   -- and m_creatureData is assigned in exactly one place, Creature.cpp:1717, inside
   -- LoadCreatureFromDB. THIS CREATURE IS NEVER LOADED FROM DB -- it only ever exists as a
   -- TempSummon -- so m_creatureData is always nullptr. With IconName 'Speak' the && does not
   -- short-circuit and the second operand dereferences null.
   -- Reachable: Player::PrepareGossipMenu walks gossip_menu_option MenuID 0, whose OptionID 1 is
   -- OptionType 3 (GOSSIP_OPTION_VENDOR) matching our VENDOR bit, and calls it at
   -- PlayerGossip.cpp:79. We normally never get there because npc_pocket_concierge::OnGossipHello
   -- returns true -- but it returns false when the module is disabled, which is precisely when a
   -- live robot would be clicked. Stock Jeeves (35642) also carries IconName ''.
   -- Gabriella (9000000) gets away with 'Speak' only because she is a real spawn, not a summon.
   '',
   -- 0 gossip_menu_id: the menu is built in C++ by npc_pocket_concierge::OnGossipHello, not from
   -- gossip_menu / gossip_menu_option rows.
   0,
   80, 80,
   -- 35 = FACTION_FRIENDLY, the faction all six utility NPCs already use, so nothing aggroes it
   -- and it aggroes nothing. It is also why the auction house resolves to the NEUTRAL house:
   -- faction template 35 carries neither the Alliance nor the Horde mask, so
   -- GetAuctionHouseEntryFromFactionTemplate falls through to AuctionHouseId::Neutral. Both
   -- factions therefore share one auction house through this robot, which is the intent.
   35,
   -- 73535617 = GOSSIP 0x1 | VENDOR 0x80 | REPAIR 0x1000 | BANKER 0x20000 | AUCTIONEER 0x200000
   --            | STABLEMASTER 0x400000 | MAILBOX 0x4000000
   --          = 1 + 128 + 4096 + 131072 + 2097152 + 4194304 + 67108864
   -- Every bit is load-bearing. Each gossip action re-validates the target through
   -- Player::GetNPCIfCanInteractWith with its own mask, so a dropped bit is one dead menu entry
   -- and the rest working -- which is why toy_robot.h static_asserts this exact number and
   -- OnStartup re-checks it against this row at boot.
   --
   -- REPAIR 0x1000 draws no menu of its own. There is no repair opcode: the repair and
   -- repair-all buttons live inside the client's MerchantFrame and are drawn from the npcflags
   -- the client holds for this creature, which is why the "Repair my equipment" gossip entry
   -- simply opens the merchant window. The core does the same thing -- PlayerGossip.cpp:328-330
   -- falls GOSSIP_OPTION_ARMORER through to the identical SendListInventory as GOSSIP_OPTION_VENDOR.
   --
   -- ONE CONDITIONAL WORTH KNOWING ABOUT REPAIR: Unit::PatchValuesUpdate (Unit.cpp:16910-16914)
   -- strips BOTH REPAIR and VENDOR_MASK out of the npcflags sent to a given player when
   -- Player::CanSeeVendor is false, and CanSeeVendor (Player.cpp) ends in
   -- AnyVendorOptionAvailable(GetGossipMenuId(), creature) -- menu 0 for us. That resolves true
   -- today because gossip_menu_option MenuID 0 / OptionID 1 is OptionType 3 with no `conditions`
   -- row (verified: 0 rows with SourceTypeOrReferenceId 15 AND SourceGroup 0). If someone ever
   -- adds one, the repair and vendor buttons vanish client-side with no error anywhere -- so
   -- OnStartup audits it.
   --
   -- NOT set: VENDOR_REAGENT 0x800. The reagent menu goes through SendListInventory's vendorEntry
   --   override, which validates against UNIT_NPC_FLAG_VENDOR, not the reagent bit.
   -- NOT set: INNKEEPER 0x10000. Set-hearthstone was offered and not asked for.
   -- NOT set: GUILD_BANKER 0x800000. It looks like the bit the guild vault needs and it is a
   --   trap. UnitDefines.h:345 documents it as "cause client to send 997 opcode" -- the client
   --   then sends CMSG_GUILD_BANKER_ACTIVATE carrying the CREATURE's guid, and
   --   GuildHandler.cpp:285 resolves it through GetGameObjectIfCanInteractWith(...,
   --   GAMEOBJECT_TYPE_GUILD_BANK), which can never match a creature. It returns early with no
   --   packet at all. The guild vault is a summoned GAMEOBJECT; see toy_robot.cpp.
   73535617,
   1,
   -- 2 UNIT_FLAG_NON_ATTACKABLE | 256 UNIT_FLAG_IMMUNE_TO_PC
   258,
   -- 9 = CREATURE_TYPE_MECHANICAL. It is a robot.
   9,
   -- 2 = CREATURE_TYPE_FLAG_VISIBLE_TO_GHOSTS. Without this a dead player cannot see or click it
   -- (Player::GetNPCIfCanInteractWith bails on !IsAlive() unless this flag is set), and "check
   -- the mail while running back from a wipe" is exactly when a pocket mailbox earns its place.
   2,
   1,
   -- 258 = 2 CREATURE_FLAG_EXTRA_CIVILIAN | 256 CREATURE_FLAG_EXTRA_NO_TAUNT.
   --
   -- THIS WAS 130 AND 130 IS A TRAP -- it is the value mod-utility-npcs uses for Ysolde
   -- Ashgrave (9000100) under a comment that reads "2 CIVILIAN | 128 NO_TAUNT". That comment is
   -- wrong: CreatureData.h:53-54 has CREATURE_FLAG_EXTRA_TRIGGER = 0x80 (128) and
   -- CREATURE_FLAG_EXTRA_NO_TAUNT = 0x100 (256). 130 therefore says CIVILIAN | TRIGGER.
   --
   -- What TRIGGER does to a visible NPC, in two places, for players only:
   --   Creature.cpp:676-677  if (IsTrigger()) SetUnitFlag(UNIT_FLAG_NOT_SELECTABLE);
   --   Unit.cpp:16955-16960  non-GM viewers are sent GetFirstInvisibleModel() instead of the real
   --                         display; no model of ours is flagged is_trigger, so that resolves to
   --                         CreatureModel::DefaultInvisibleModel.
   -- Net effect of 130: a GM sees and clicks a working robot, and every actual player sees
   -- nothing at all and could not click it if they did. Which is exactly the bug you only find
   -- in production, because the person testing is the GM.
   258,
   '', 0,
   'npc_pocket_concierge');

DELETE FROM `creature_template_model` WHERE `CreatureID` = 9000200;
-- 30076 is the display the real Jeeves (creature 35642) uses on this realm -- an actual robot
-- butler model, known-good on this client rather than a model id copied from a wiki.
INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`)
VALUES (9000200, 0, 30076, 1, 1);
