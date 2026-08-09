-- mod-utility-npcs: the talent master, an NPC this repo OWNS.
--
-- Every other utility NPC here belongs to a pinned third-party module. Gabriella already carries
-- npc_assistant, and AzerothCore binds exactly ONE CreatureScript per creature_template.ScriptName
-- -- so a "reset my talents" option on her would mean forking a module we deliberately pin. A
-- template of our own costs one row and cannot be broken by a module bump.
--
-- Column list verified against SHOW COLUMNS on this exact revision: there is no `scale` column
-- (that lives in creature_template_model.DisplayScale here), which is the kind of thing a
-- copied-from-a-wiki INSERT gets wrong and only discovers at apply time.
--
-- Re-runnable: DELETE-then-INSERT on a single key, like every other file in this module.

DELETE FROM `creature_template` WHERE `entry` = 9000100;
INSERT INTO `creature_template`
  (`entry`, `name`, `subname`, `IconName`, `gossip_menu_id`, `minlevel`, `maxlevel`,
   `faction`, `npcflag`, `unit_class`, `unit_flags`, `type`, `type_flags`,
   `RegenHealth`, `flags_extra`, `AIName`, `MovementType`, `ScriptName`)
VALUES
  (9000100, 'Ysolde Ashgrave', 'Talent Master', 'Speak', 0, 80, 80,
   -- 35 = FACTION_FRIENDLY, the faction the other five utility NPCs already use, so nothing
   -- aggroes them and they aggro nothing.
   35,
   -- 1 = UNIT_NPC_FLAG_GOSSIP only. Deliberately NOT a trainer flag: the client's trainer window
   -- would demand trainer_spell rows and a trainer type, and this is a plain gossip menu.
   1,
   1,
   -- 2 UNIT_FLAG_NON_ATTACKABLE | 256 UNIT_FLAG_IMMUNE_TO_PC
   258,
   -- 7 humanoid, 2 = visible to ghosts
   7, 2,
   1,
   -- 2 CIVILIAN | 128 NO_TAUNT
   130,
   '', 0,
   'npc_talent_master');

DELETE FROM `creature_template_model` WHERE `CreatureID` = 9000100;
-- 19646 is the display the transmog NPCs already use on this realm, so it is known-good on this
-- client rather than a model id copied from a wiki that may not exist in 3.3.5a.
INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`)
VALUES (9000100, 0, 19646, 1, 1);
