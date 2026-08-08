-- 2026_08_08_00_autolearn_weapon_proficiencies.sql
--
-- mod-autolearn -- give every class the weapon proficiencies a Weapon Master would sell it,
-- at character creation and again at every login, with no trainer visit and no C++.
--
-- Re-runnable on purpose, same contract as the mod-dk-lowlevel migrations: UpdateFetcher keys a
-- migration on its bare filename plus a SHA1 of its contents, so an unchanged file is skipped and
-- a CHANGED file is re-applied IN FULL. Hence DELETE-then-INSERT, never a bare INSERT.
--
-- ---------------------------------------------------------------------------------------------
-- WHY THIS TABLE AND NOT CODE
-- ---------------------------------------------------------------------------------------------
-- A proficiency spell is never granted by its own SkillLineAbility row being "reachable" -- it is
-- granted because the character HAS the skill line. Every one of the 14 lines below carries an
-- AcquireMethod = 2 (SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN, DBCEnums.h:361) reward row, and
-- the core hands that reward out through Player::learnSkillRewardedSpells (Player.cpp:12237).
-- Adding the skill line is therefore the whole of the change.
--
-- `playercreateinfo_skills` gets that for free in all four places that matter:
--
--   creation      Player::Create  -> LearnDefaultSkills                  Player.cpp:622
--   EVERY login   Player::LoadFromDB -> LearnDefaultSkills               PlayerStorage.cpp:5541
--   .reset spells Player::resetSpells -> LearnDefaultSkills              Player.cpp:12074
--   spell re-sync _LoadSkills -> learnSkillRewardedSpells per skill      Player.cpp:14081
--
-- Idempotent by construction: LearnDefaultSkills skips a skill the player already has
-- (Player.cpp:12112) and Player::learnSpell early-returns on HasActiveSpell (Player.cpp:3413).
-- Safe in BOTH level directions because nothing here is level-dependent -- these rows are read at
-- login, not at OnLevelChanged, so a GM raising or lowering a level (online or via the offline
-- `.character level` path, which fires no hook at all) cannot desynchronise them. And nothing here
-- can un-grant: learnSkillRewardedSpells only ever calls removeSpell for AcquireMethod == 1 rows
-- whose MinSkillLineRank is above the current skill value (Player.cpp:12277). Every proficiency
-- reward below is AcquireMethod = 2.
--
-- A WRONG ROW IS A NO-OP, NOT A WRONG GRANT. Two independent gates read SkillRaceClassInfo.dbc:
-- ObjectMgr drops any (race, class, skill) triple the DBC disallows while loading this very table
-- (ObjectMgr.cpp:4568), and LearnDefaultSkill bails again on the same lookup (Player.cpp:12121).
-- Every classMask below was derived FROM that DBC, so the two gates are agreement, not luck.
--
-- ---------------------------------------------------------------------------------------------
-- WHAT IS DELIBERATELY NOT HERE
-- ---------------------------------------------------------------------------------------------
-- Three proficiencies are level-gated in retail and mod-learn-spells already grants them at the
-- right level from its hardcoded m_additionalSpells table (mod_learnspells.cpp:74-399). Putting
-- them here would hand them out at level 1 and undo that pacing:
--
--   skill 118 Dual Wield  -> spell 674   warrior/hunter at 20, rogue and DK already have it
--   skill 293 Plate Mail  -> spell 750   warrior/paladin at 40
--   skill 413 Mail        -> spell 8737  hunter/shaman at 40
--
-- Shaman Dual Wield is excluded for a second, stronger reason: SkillRaceClassInfo permits a shaman
-- skill 118 only so the Enhancement talent Dual Wield (30798) has somewhere to land. Granting the
-- skill directly would hand every shaman a talent for free.
--
-- Parry (3127) is not a proficiency-effect spell and needs nothing here. Death knights get it from
-- the core -- SkillLineAbility 17542, skill 95 Defense, ClassMask 32, AcquireMethod 1 -- and
-- warrior/paladin/hunter/rogue get it from mod-learn-spells at levels 6/8/8/12. Shamans cannot
-- parry at all and appear in neither row, which is correct.
--
-- ---------------------------------------------------------------------------------------------
-- CONSEQUENCE WORTH KNOWING
-- ---------------------------------------------------------------------------------------------
-- A newly granted weapon skill arrives at VALUE 1, not at the level cap: LearnDefaultSkill takes
-- the `skillValue = 1` branch (Player.cpp:12133) because AlwaysMaxWeaponSkill is unset in
-- conf/worldserver.conf and defaults to false (WorldConfig.cpp:564). That is exactly what happens
-- when a retail player buys from a Weapon Master, so it is faithful -- but a level-40 character
-- who logs in and finds Polearms at 1/200 will miss with one until they grind it. Setting
-- `AlwaysMaxWeaponSkill = 1` in conf/worldserver.conf removes that grind for every skill at once.
-- That is a realm-wide decision and is deliberately NOT made from inside a module.

DELETE FROM `playercreateinfo_skills` WHERE `comment` LIKE 'mod-autolearn:%';

-- raceMask is 0 on every row: these are class proficiencies, and the per-race legality is already
-- enforced by the SkillRaceClassInfo gate described above.
--
-- classMask bits: 1 Warrior, 2 Paladin, 4 Hunter, 8 Rogue, 16 Priest, 32 Death Knight,
--                 64 Shaman, 128 Mage, 256 Warlock, 1024 Druid.
--
-- The trailing comment on each line is the closure: every spell that skill line's
-- AcquireMethod 1/2 rows will hand the listed classes. Nothing else rides along -- the three
-- ranged lines additionally grant the ranged auto-attack (3018 Shoot / 2764 Throw), which is the
-- correct and expected companion to owning a bow, gun, crossbow or thrown weapon.
--
-- Two rows deliberately overlap a stock row rather than replacing it, because the stock row is
-- race-scoped and this one is not: skill 46 Guns already exists as (36, 4) for dwarf and tauren
-- hunters, and skill 226 Crossbows as (1024, 4) for draenei hunters. The primary key is
-- (raceMask, classMask, skill), so there is no collision, and a dwarf hunter simply appears twice
-- in PlayerInfo::skills -- which LearnDefaultSkills absorbs at Player.cpp:12112 by skipping a
-- skill the character already has. Editing the stock rows instead would be a bigger, race-shaped
-- change for no gain.
INSERT INTO `playercreateinfo_skills` (`raceMask`, `classMask`, `skill`, `rank`, `comment`) VALUES
  (0,  392,  43, 0, 'mod-autolearn: Swords -> 201 One-Handed Swords (rogue, mage, warlock)'),
  (0,   74,  44, 0, 'mod-autolearn: Axes -> 196 One-Handed Axes (paladin, rogue, shaman)'),
  (0,    9,  45, 0, 'mod-autolearn: Bows -> 264 Bows + 3018 Shoot (warrior, rogue)'),
  (0,   13,  46, 0, 'mod-autolearn: Guns -> 266 Guns + 3018 Shoot (warrior, hunter, rogue)'),
  (0,   40,  54, 0, 'mod-autolearn: Maces -> 198 One-Handed Maces (rogue, death knight)'),
  (0,    4,  55, 0, 'mod-autolearn: Two-Handed Swords -> 202 Two-Handed Swords (hunter)'),
  (0,    5, 136, 0, 'mod-autolearn: Staves -> 227 Staves (warrior, hunter)'),
  (0, 1120, 160, 0, 'mod-autolearn: Two-Handed Maces -> 199 Two-Handed Maces (death knight, shaman, druid)'),
  (0,   66, 172, 0, 'mod-autolearn: Two-Handed Axes -> 197 Two-Handed Axes (paladin, shaman)'),
  (0,  208, 173, 0, 'mod-autolearn: Daggers -> 1180 Daggers (priest, shaman, mage)'),
  (0,    4, 176, 0, 'mod-autolearn: Thrown -> 2567 Thrown + 2764 Throw (hunter)'),
  (0,   13, 226, 0, 'mod-autolearn: Crossbows -> 5011 Crossbows + 3018 Shoot (warrior, hunter, rogue)'),
  (0, 1031, 229, 0, 'mod-autolearn: Polearms -> 200 Polearms (warrior, paladin, hunter, druid)'),
  (0, 1101, 473, 0, 'mod-autolearn: Fist Weapons -> 15590 Fist Weapons (warrior, hunter, rogue, shaman, druid)');
