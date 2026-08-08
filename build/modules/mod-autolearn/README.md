# mod-autolearn

One SQL migration and an empty loader. It closes the single gap between what the realm already
learns automatically and "all classes should autolearn weapon skills, class spells and ranks, pet
all abilities".

Everything else in that sentence was already free. This module exists **only** for weapon
proficiencies, and only for the 37 (class, proficiency) pairs that no other path grants.

---

## 1. What was already automatic before this module

### 1.1 Pet abilities — 100%, core, no module, both level directions

`Pet::InitLevelupSpellsForLevel` (`Pet.cpp:1914-1951`) learns and unlearns pet spells by level. It
is called from all three places a pet's level can change:

| call site | when |
| --- | --- |
| `Pet.cpp:439` (`LoadPetFromDB`) | every time the pet is summoned |
| `Pet.cpp:937` (`GivePetLevel`) | every pet level change |
| `Pet.cpp:2040` (`InitPetCreateSpells`) | a freshly tamed / summoned pet |

The loop iterates the level→spell set in **reverse**, so `itr->first > level` unlearns and anything
else learns (`Pet.cpp:1921-1929`) — de-levelling a pet is handled, not just levelling it.

The data behind it is not a table. `SpellMgr::LoadPetLevelupSpellMap` (`SpellMgr.cpp:2637-2681`)
builds it at boot from `CreatureFamily.dbc.skillLine[2]` crossed with every SkillLineAbility row
whose `AcquireMethod == 2` and whose spell has a non-zero `SpellLevel`. There is **no
`pet_levelupspell` table on this revision** — `SHOW TABLES LIKE 'pet_%'` returns only
`pet_levelstats`, `pet_name_generation`, `pet_name_generation_locale`.

This realm's boot log:

```
>> Loaded 993 Pet Levelup And Default Spells For 39 Families in 0 ms
>> Loaded Addition Spells For 112 Pet Spell Data Entries in 1 ms
```

993 spells, 39 of 40 creature families — reproduced exactly by parsing the DBCs. Spot checks:

* Wolf (family 1): Growl R1–R8, Bite R1–R11, Furious Howl R1–R5, Cower, Avoidance — 28 spells, L1→L80.
* Cat (family 2): Claw, Rake, Prowl, Growl, Cower — 31 spells.
* Imp (23): Firebolt, Blood Pact, Fire Shield, Phase Shift — 25 spells.
* Voidwalker (16): Torment, Sacrifice, Consume Shadows, Suffering — 35 spells.
* Succubus (17), Felhunter (15), Felguard (29): 17 / 21 / 13 spells.

Hunter **and** warlock pets, every rank, automatically. Nothing to add. Pet *talents* are spent by
the player and are correctly not auto-granted.

### 1.2 Class spells and all their ranks — mod-learn-spells

`mod-learn-spells @ 016b92d5` scans the whole spell store per level gained and learns every spell
where `SpellFamilyName == the player's class family` and `BaseLevel == the level just reached`,
provided a SkillLineAbility row exists with `RaceMask == 0 && AcquireMethod == 0`
(`mod_learnspells.cpp:415-467`). Because it walks levels in ascending order and requires
`GetPrevRankSpell()` to already be known (`:449-455`), it grants **every rank**, not just the
highest. Talent rank 1 is excluded (`:457-459`), pet spells are excluded via
`PowerType == POWER_FOCUS` (`:428`), and 315 hand-listed IDs are excluded via `m_ignoreSpells`.

Its complete config surface is three live keys — `LearnSpells.Enable`, `LearnSpells.OnFirstLogin`,
`LearnSpells.MaxLevel` (`:19,33,35`). `LearnSpells.Announce` is in the `.dist` and **is never
read**.

### 1.3 The weapon proficiencies each class starts with — core

`playercreateinfo_skills` (77 stock rows) gives each class its starting skill lines;
`LearnDefaultSkills` turns each into `SetSkill` → `learnSkillRewardedSpells`, which hands out that
line's `AcquireMethod` 1/2 rewards. A human warrior gets 15 proficiency spells this way, a paladin
12, a death knight 14 — before any module runs.

---

## 2. The gap that was real

Every proficiency spell is the `AcquireMethod = 2` reward of **its own skill line** — spell 674
Dual Wield is the reward of skill 118, spell 200 Polearms of skill 229, and so on. So the gate is
never the SkillLineAbility row; it is whether the character *has the skill line*. If they do not,
the only stock way to get it is to pay a Weapon Master. On this realm's own data:

```
SELECT SpellId, COUNT(DISTINCT TrainerId), MIN(ReqLevel), MIN(MoneyCost)
FROM trainer_spell WHERE SpellId IN (196,197,198,199,200,201,202,227,264,266,
                                     674,750,1180,2567,5011,8737,15590,3127) GROUP BY SpellId;
```

returns all 18 — 2 to 7 trainers each, 1g to 2g, ReqLevel 0 for most. That is precisely the trainer
trip this realm installed mod-learn-spells to abolish.

**mod-learn-spells cannot close it, at any setting.** Proficiency spells are filtered out three
separate times: `SpellFamilyName` is 0 (`SPELLFAMILY_GENERIC`) and no player class maps to family 0
(`:422`, `:491-518`); `BaseLevel` is 0 so no level ever matches (`:437`); and their
SkillLineAbility rows are `AcquireMethod = 2`, not 0 (`:446`). Its only proficiency coverage is
four spells hardcoded in `m_additionalSpells`, which bypasses all three filters: parry 3127,
dual wield 674, mail 8737, plate 750.

Counting from `SkillRaceClassInfo.dbc` (the DBC the core itself uses to decide whether a class may
hold a skill) minus `playercreateinfo_skills`, the gap was **44 (class, proficiency) pairs**, of
which mod-learn-spells covers **6**. This module closes the other **37**, in **14 rows**.

| class | gains |
| --- | --- |
| Warrior | Bows, Guns, Staves, Crossbows, Polearms, Fist Weapons |
| Paladin | One-Handed Axes, Two-Handed Axes, Polearms |
| Hunter | Guns, Two-Handed Swords, Staves, Thrown, Crossbows, Polearms, Fist Weapons |
| Rogue | One-Handed Swords, One-Handed Axes, One-Handed Maces, Bows, Guns, Crossbows, Fist Weapons |
| Priest | Daggers |
| Death Knight | One-Handed Maces, Two-Handed Maces |
| Shaman | One-Handed Axes, Two-Handed Axes, Two-Handed Maces, Daggers, Fist Weapons |
| Mage | One-Handed Swords, Daggers |
| Warlock | One-Handed Swords |
| Druid | Two-Handed Maces, Polearms, Fist Weapons |

Left alone on purpose: **Dual Wield (118), Plate Mail (293), Mail (413)** — mod-learn-spells already
grants those at their retail levels (20/40/40) and adding them here would hand them out at level 1.
Shaman Dual Wield is excluded for a second reason: `SkillRaceClassInfo` only permits it so the
Enhancement talent 30798 has somewhere to land.

---

## 3. Why data and not code

`playercreateinfo_skills` is re-read at creation, at **every login**
(`PlayerStorage.cpp:5541`) and on `.reset spells` (`Player.cpp:12074`), and `_LoadSkills`
independently re-runs `learnSkillRewardedSpells` for every held skill on every login
(`Player.cpp:14081`). That is a stronger reconcile than a `PlayerScript` could offer — in
particular it survives the offline `.character level` path, which fires no hook at all — and it is
idempotent for free (`HasSkill` skip at `Player.cpp:12112`, `HasActiveSpell` early-return at
`Player.cpp:3413`). Nothing here is level-dependent, so GM level changes in either direction are
non-events.

And a mistake is inert rather than harmful: a `(race, class, skill)` triple that
`SkillRaceClassInfo.dbc` forbids is dropped while this table is being loaded
(`ObjectMgr.cpp:4568`) and again inside `LearnDefaultSkill` (`Player.cpp:12121`).

## 4. Interaction with mod-dk-lowlevel — none

The two rows that touch class 6 are skill 54 (Maces) and skill 160 (Two-Handed Maces).
`learnSkillRewardedSpells` is per skill line, so it reaches only spells 198 and 199. Skill lines
770 / 771 / 772 — where the six SkillLineAbility rows the DK feature flipped to `AcquireMethod = 0`
live, and where custom spell 90000's `AcquireMethod = 2` row lives — are never touched. The DK
grant path and the six suppressed level-55 abilities are bit-for-bit unaffected.

## 5. Files

```
data/sql/db-world/base/2026_08_08_00_autolearn_weapon_proficiencies.sql   the module
src/autolearn_loader.cpp                                                  empty; see its header
.gitignore                                                                re-includes data/
```

There is no `conf/` and no `.conf.dist`: there is nothing to configure.
