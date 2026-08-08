# Server config — phases, rates, scaling, bots

Gameplay tuning for the three-phase progression described in [../README.md](../README.md).
Everything here is per-config; none of it needs a code change.

Config keys below were read out of the actual `.conf.dist` files at the versions pinned in
`build/modules.txt`. Where a key is quoted with a default, that default is verbatim from upstream.

---

## 1. The three phases

**This section is the canonical per-phase checklist. If a per-phase value appears anywhere else in
these docs, it is a copy; this is the original.**

Five config files move per phase — `worldserver.conf`, `playerbots.conf`,
`mod-rdf-expansion.conf`, `mod_ahbot.conf` and `mod_assistant.conf` — plus **one SQL statement**,
which is the part everyone forgets. Read
[the account.expansion trap](#the-accountexpansion-trap-read-this-first) immediately below first,
because without that statement flipping the config does nothing for existing players.

What each module is and why it is installed lives in [modules.md](modules.md); the values its keys
take per phase live here.

### The `account.expansion` trap (read this first)

`Expansion` in `worldserver.conf` is **not** the value the game uses. It is a *ceiling* applied at
login. From `src/server/game/Server/WorldSocket.cpp`:

```cpp
uint32 world_expansion = sWorld->getIntConfig(CONFIG_EXPANSION);
if (Expansion > world_expansion)
    Expansion = world_expansion;
```

The session's effective expansion is `min(account.expansion, Expansion)`. And
`AccountMgr::CreateAccount` stamps the `account.expansion` column with `CONFIG_EXPANSION` **at the
moment the account is created**:

```cpp
stmt->SetData(3, uint8(sWorld->getIntConfig(CONFIG_EXPANSION)));
```

So every account created during phase 1 has `account.expansion = 0` permanently. Flipping
`worldserver.conf` to `Expansion = 1` gives `min(0, 1) = 0` — **those accounts stay in Classic
forever**, silently. They will be unable to enter Outland or create a Blood Elf while a brand-new
account made after the flip works fine. This is the single most likely way to break a phase flip.

Fix, on the **auth** database, as part of every flip —
[step 4 of the flip procedure](#flip-procedure) is the exact command to run it with:

```sql
UPDATE account SET expansion = 1;   -- phase 2; use 2 for phase 3
```

Or per account in-game: `.account set addon <accountname> <0-2>`. That command is itself capped by
`CONFIG_EXPANSION`, so raise `worldserver.conf` first, then the column.

This applies to playerbot accounts too (`rndbot%` prefix) — bots need the column raised before they
will path into Outland or Northrend.

### Everything that moves, in one table

Every per-phase change, in every file. Nothing else needs to change. The per-phase blocks below are
the same thing in copy-paste form.

| File | Key | P1 (60) | P2 (70) | P3 (80) | Takes effect on |
|---|---|---|---|---|---|
| `worldserver.conf` | `MaxPlayerLevel` | `60` | `70` | `80` | **restart only** |
| `worldserver.conf` | `Expansion` | `0` | `1` | `2` | **restart only** |
| `worldserver.conf` | `CharacterCreating.Disabled.RaceMask` | `1536` | `0` | `0` | `.reload config` |
| `worldserver.conf` | `CharacterCreating.Disabled.ClassMask` | `32` | `32` | `0` | `.reload config` |
| `playerbots.conf` | `AiPlayerbot.RandomBotMaxLevel` | `60` | `70` | `80` | restart |
| `playerbots.conf` | `AiPlayerbot.RandomBotMaps` | `0,1` | `0,1,530` | `0,1,530,571` | restart |
| `playerbots.conf` | `AiPlayerbot.DisableDeathKnightLogin` | `1` | `1` | `0` | restart |
| `playerbots.conf` | `AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel` | `60` | `70` | `80` | restart |
| `mod-rdf-expansion.conf` | `RDF.Expansion` | `0` | `1` | `2` | restart |
| `mod_ahbot.conf` | `AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel` | `60` | `70` | `80` | restart, or `.ahbot reload` |
| `mod_assistant.conf` | `Assistant.Professions.Master.Enabled` | `0` | `1` | `1` | restart |
| `mod_assistant.conf` | `Assistant.Professions.GrandMaster.Enabled` | `0` | `0` | `1` | restart |
| `mod_assistant.conf` | `Assistant.FlightPaths.WrathOfTheLichKing.Enabled` | `0` | `0` | `1` | restart |
| **`acore_auth`** | `UPDATE account SET expansion` | `0` | `1` | `2` | the account's next login |

Rows marked plain *restart* are marked that way because the flip is a restart regardless; whether
those modules would also pick the key up from `.reload config` is untested and does not matter here.
The two marked **restart only** are different — they say so from the core, not from caution. In
`src/server/game/World/WorldConfig.cpp` both are registered `ConfigValueCache::Reloadable::No`:

```cpp
SetConfigValue<uint32>(CONFIG_MAX_PLAYER_LEVEL, "MaxPlayerLevel", DEFAULT_MAX_LEVEL, ConfigValueCache::Reloadable::No, ...);
SetConfigValue<uint32>(CONFIG_EXPANSION, "Expansion", 2, ConfigValueCache::Reloadable::No);
```

`.reload config` will edit neither, and it tells you so rather than failing silently — from
`ConfigValueCache.h`:

> `Server Config (Name: {}) cannot be changed by reload. A server restart is required to update this config value.`

Grep the console for that line after any flip you attempted without a restart. Since the two keys
that matter most need a restart, **a phase flip is always a restart**; treat `.reload config` as a
tuning tool (see [§4](#4-autobalance-tuning)), not a flip tool.

`mod_ahbot.conf` and `mod_assistant.conf` come from [modules.md](modules.md) §1.4 and §1.5.
`mod_ahbot.conf` additionally needs a **one-time install step** that is not per-phase — see the
note under [phase 1](#phase-1--classic-cap-60) — and until you do it the `MaxLevel` row above is
inert. The other `Assistant.FlightPaths.*` keys (`Vanilla.RequiredLevel = 60`,
`BurningCrusade.RequiredLevel = 70`) are *level* gates, not phase gates — they are already correct
for all three phases and must not be touched.

### Phase 1 — Classic, cap 60

```ini
# worldserver.conf
MaxPlayerLevel = 60
Expansion      = 0

StartPlayerLevel       = 1
StartHeroicPlayerLevel = 55
MinDualSpecLevel       = 40

# Expansion=0 already blocks these via the DBC expansion field on the race/class
# entry (CharacterHandler.cpp: raceEntry->expansion > Expansion()). These masks are
# belt-and-braces: they fail the create screen earlier and cover anything that
# constructs characters without a real session (see the playerbot caveat below).
CharacterCreating.Disabled.RaceMask  = 1536   # 512 Blood Elf + 1024 Draenei
CharacterCreating.Disabled.ClassMask = 32     # Death Knight

Rate.XP.Kill     = 1.5
Rate.XP.Quest    = 1.5
Rate.XP.Quest.DF = 1.5
Rate.XP.Explore  = 1.5
Rate.XP.Pet      = 1.5

# Phase-invariant, but it belongs in this block because this block is what
# bring-up.md tells you to paste before first boot. Default is 0, and there is
# no worldserver-cli binary — without SOAP, scripts/phase.sh and the weekly
# restart in hosting.md §7.6 have no way to reach a running server.
SOAP.Enabled = 1
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMinLevel = 1
AiPlayerbot.RandomBotMaxLevel = 60
AiPlayerbot.RandomBotMaps     = 0,1          # Eastern Kingdoms, Kalimdor only
AiPlayerbot.DisableDeathKnightLogin = 1
AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel = 60
```

```ini
# mod-rdf-expansion.conf
RDF.Expansion = 0
```

```ini
# mod_ahbot.conf
AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel = 60

# mod_assistant.conf
Assistant.Professions.Master.Enabled             = 0
Assistant.Professions.GrandMaster.Enabled        = 0
Assistant.FlightPaths.WrathOfTheLichKing.Enabled = 0
```

> **One-time install step, not a per-phase one — do this once or the `MaxLevel` above is dead
> config.** `mod-ah-bot-plus` ships both level filters **off**, and both ceilings wide open. From
> its `conf/mod_ahbot.conf.dist` at the pinned SHA, and matching the `sConfigMgr->GetOption`
> defaults in `src/AuctionHouseBot.cpp`:
>
> ```ini
> AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled  = false   # <- ships off
> AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel = 999
> AuctionHouseBot.ListedItemLevelRestrict.Enabled           = false   # <- ships off
> AuctionHouseBot.ListedItemLevelRestrict.MaxItemLevel      = 999
> ```
>
> `MaxLevel` is only consulted when `.Enabled` is `true`, so a phase-1 block that sets `MaxLevel`
> alone changes nothing and the level-60 auction house lists level-80 gear. Set the two `.Enabled`
> flags once, at install, alongside the item-level ceiling ([modules.md](modules.md) §1.4):
>
> ```ini
> AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled = true
> AuctionHouseBot.ListedItemLevelRestrict.Enabled          = true
> AuctionHouseBot.ListedItemLevelRestrict.MaxItemLevel     = 80    # tune; not phase-driven
> ```
>
> After that, `MaxLevel` is the only key `scripts/phase.sh` touches in this file, which is what
> [the table above](#everything-that-moves-in-one-table) says. (Heads-up if you go reading the
> conf: the comment block above `EquipItemUseOrEquipLevelRestrict.MaxLevel` claims `Default: 0`,
> but the line it documents — and the code default — is `999`.)

```sql
UPDATE account SET expansion = 0;
```

### Phase 2 — TBC, cap 70

```ini
# worldserver.conf
MaxPlayerLevel = 70
Expansion      = 1

CharacterCreating.Disabled.RaceMask  = 0      # Blood Elf + Draenei open
CharacterCreating.Disabled.ClassMask = 32     # Death Knight still closed
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMaxLevel = 70
AiPlayerbot.RandomBotMaps     = 0,1,530       # + Outland
AiPlayerbot.DisableDeathKnightLogin = 1
AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel = 70
```

```ini
# mod-rdf-expansion.conf
RDF.Expansion = 1
```

```ini
# mod_ahbot.conf
AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel = 70

# mod_assistant.conf
Assistant.Professions.Master.Enabled             = 1   # 375, TBC ceiling
Assistant.Professions.GrandMaster.Enabled        = 0
Assistant.FlightPaths.WrathOfTheLichKing.Enabled = 0
```

```sql
UPDATE account SET expansion = 1;
```

### Phase 3 — WotLK, cap 80

```ini
# worldserver.conf
MaxPlayerLevel = 80
Expansion      = 2

CharacterCreating.Disabled.RaceMask  = 0
CharacterCreating.Disabled.ClassMask = 0
HeroicCharactersPerRealm             = 1      # DKs per account; raise if you want more
CharacterCreating.MinLevelForHeroicCharacter = 55
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMaxLevel = 80
AiPlayerbot.RandomBotMaps     = 0,1,530,571   # + Northrend (upstream default)
AiPlayerbot.DisableDeathKnightLogin = 0
AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel = 80
```

```ini
# mod-rdf-expansion.conf
RDF.Expansion = 2
```

```ini
# mod_ahbot.conf
AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel = 80

# mod_assistant.conf
Assistant.Professions.Master.Enabled             = 1
Assistant.Professions.GrandMaster.Enabled        = 1   # 450, WotLK ceiling
Assistant.FlightPaths.WrathOfTheLichKing.Enabled = 1
```

```sql
UPDATE account SET expansion = 2;
```

### What does *not* change per phase

- **AutoBalance.** Nothing in it keys off `MaxPlayerLevel`; it scales off the actual level of the
  highest player in the instance. It follows the cap automatically. You may still want to retune
  `InflectionPointRaid*` per phase, because the raid content itself changes (40-mans in phase 1,
  Karazhan in phase 2, 10/25s in phase 3) — see [§4](#4-autobalance-tuning).
- **`Rate.XP.*`.** 1.5× throughout.
- **Talents, spellbook, glyphs.** Left at WotLK for all phases, per the brief. Do **not** set
  `AiPlayerbot.LimitTalentsExpansion = 1` — it exists to clamp bot talent trees to 6 rows below level
  61 / 8 rows below 71, which would make bots weaker than the humans they're playing alongside.

### Flip procedure

```bash
# 1. Announce, in-game, a few days ahead and again on the night.
.announce Phase 2 opens in 5 minutes. Dark Portal, Outland, Blood Elves and Draenei. Server restarting.

# 2. Graceful shutdown with a 300s countdown; the client shows a timer and
#    saves are flushed.
.server shutdown 300

# 3. Edit the five confs. Version them; never hand-edit on the box.
#    (scripts/phase.sh does this from the repo copies — spec below.)

# 4. Raise the account column. THIS IS THE STEP THAT GETS MISSED.
#    Run from /srv/wow/wowserver/deploy, same as step 5. There is no mysql client
#    on the host and the mysql service publishes no ports, so the query runs
#    inside the container; the password comes from the mounted 0600 option file,
#    never from -p on a command line (hosting.md 7.3).
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
  -e "UPDATE account SET expansion = 1;"

# 5. Restart.
docker compose up -d

# 6. Verify — see below.
```

`/etc/mysql/backup.cnf` is `deploy/mysql-backup.cnf` bind-mounted into the mysql service — 0600,
gitignored, generated by `scripts/backup.sh` from `deploy/.env`. Where it comes from, why
`--defaults-extra-file` has to be the first argument, and what to do if it is missing:
[hosting.md §7.3](hosting.md#73-backups). Every DB query on this page uses that form.

Verification checklist, in this order — each one catches a different failure:

| Check | How | Expected |
|---|---|---|
| Config actually loaded | worldserver console at boot | no `Missing name`/`Invalid value` lines for the keys you touched |
| Cap moved | on a throwaway char at the old cap, kill something | XP bar advances past the old cap |
| Session expansion | log in a **pre-existing** account, `.account` | expansion reads the new value, not the old |
| Map access | walk a real char through the Dark Portal | no "you must have Burning Crusade" transfer abort |
| Race/class create | character create screen | Blood Elf/Draenei selectable |
| RDF | open Dungeon Finder at cap | random dungeon entry is offered and queueable |
| Bots followed | `.playerbots bot list`, check a bot's level | bots exist above the old cap after a randomize cycle |

The RDF check is the one that fails quietly. Do not skip it.

### `scripts/phase.sh` — spec

One argument, `1`, `2` or `3`. Idempotent: running it twice for the same phase is a no-op plus a
restart. It does four things, in this order.

**1. Rewrite the confs.** The repo holds the deployed `.conf` files; the script rewrites in place
the thirteen keys in [the table above](#everything-that-moves-in-one-table) across the five files,
then writes them to the container's config volume. Rewrite by key (`^\s*Key\s*=`), never by line
number — module confs get new keys upstream and line numbers rot. Refuse to run if a key the script
expects to find is absent: a silently-skipped `Expansion` is exactly the failure §1 opens with.

**2. Announce and shut down.** Needs a channel into the running server, and this is where people
get stuck: **AzerothCore builds no `worldserver-cli`.** `src/server/apps/` contains exactly two
targets, `authserver` and `worldserver`. The GM console is `worldserver`'s own stdin
(`Console.Enable = 1`, the default). Two ways to reach it from a script:

- **`docker attach`.** Upstream's `docker-compose.yml` already sets `stdin_open: true` and
  `tty: true` on `ac-worldserver` precisely so this works, so keep both in yours (compose file:
  [bring-up.md](bring-up.md)). Simple, but `attach` is a shared interactive TTY — detaching cleanly
  needs `--detach-keys`, and a stray Ctrl-C kills the server. Fine at the keyboard, poor in a
  script.
- **SOAP** — the scripted option. All three keys are **off/loopback by default** in
  `worldserver.conf`:

  ```ini
  SOAP.Enabled = 0            # note: "Enabled", though the comment block above it reads "SOAP.Enable"
  SOAP.IP      = "127.0.0.1"
  SOAP.Port    = 7878
  ```

  Set `SOAP.Enabled = 1` and leave `SOAP.IP` on loopback; upstream's compose already publishes
  7878, which you do **not** want reachable from the internet — see
  [hosting.md](hosting.md) for the firewall. It is an HTTP POST with basic auth carrying one GM
  command:

  ```xml
  <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">
    <SOAP-ENV:Body><ns1:executeCommand><command>server shutdown 300</command></ns1:executeCommand></SOAP-ENV:Body>
  </SOAP-ENV:Envelope>
  ```

  The caller needs a real account whose security is **`SEC_ADMINISTRATOR` (gmlevel 3)** — from
  `ACSoap.cpp`, `if (AccountMgr::GetSecurity(accountId) < SEC_ADMINISTRATOR) return 403;` — with a
  row in `account_access` at `RealmID = -1`. Account creation is in [bring-up.md](bring-up.md).

**3. `UPDATE account SET expansion = N` on `acore_auth`.** Unconditional, every flip, including a
re-run. Cheap and idempotent, and it is the step that gets missed. Use the same
`docker compose exec -T mysql mysql --defaults-extra-file=…` form as
[step 4 above](#flip-procedure), from `/srv/wow/wowserver/deploy` — the script must not put a
password on a command line, and it has no host-side mysql client to use even if it wanted to.

**4. Restart and verify.** `docker compose up -d`, then re-run the verification checklist above.
Do not offer a `--reload` mode: `MaxPlayerLevel` and `Expansion` are `Reloadable::No`, so a
reload-only flip is guaranteed to be a half-flip.

### Going backwards

Phases are designed to move forwards. Moving one backwards is not symmetric, so if you are ever
tempted (a phase opened early, a test realm rolled back), know what does and does not reverse.

**Characters above the new cap are not demoted.** `Player::GiveXP` simply returns once
`level >= CONFIG_MAX_PLAYER_LEVEL`, so a level-70 character on a `MaxPlayerLevel = 60` server keeps
its level and stops earning XP forever. It is worse than frozen, though: `ObjectMgr::GetPlayerLevelInfo`
only reads `player_levelstats` for `level <= MaxPlayerLevel` and otherwise falls through to
`BuildPlayerLevelInfo`, which **extrapolates** stats from the last in-range level with a hardcoded
per-class formula. Those characters get synthesised base stats that do not match the real level-70
table, and they are recomputed on the next `InitStatsForLevel`. Do not lower `MaxPlayerLevel` below
any live character's level and expect the character to be intact.

**Bots above the new cap get stranded, not reset.** `RandomPlayerbotMgr::RandomizeFirst` clamps to
`min(RandomBotMaxLevel, MaxPlayerLevel)`, but only for bots it re-rolls from scratch. The ordinary
path is `Randomize()`, which for a bot at or above the cap does
`uint8 level = bot->GetLevel(); factory.Randomize(true)` — it re-rolls gear *at the bot's existing
level* and leaves the level alone. The switch that changes this is
`AiPlayerbot.DowngradeMaxLevelBot`, **default `0`**, described upstream as "Set RandomBotMaxLevel
bots to RandomBotMinLevel". Turning it on does sweep over-cap bots down, but not at boot: it takes
effect per bot as that bot's randomize timer fires, and the floor of that timer is
`AiPlayerbot.MinRandomBotRandomizeTime = 7200` (2 hours), with a ceiling of 14 days. So the sweep is
gradual, and leaving it on permanently means every bot that *reaches* the cap during normal play
gets dumped back to `RandomBotMinLevel` (`1`, in the config above) — which is not what you want. If
you need over-cap bots gone quickly, wiping with `AiPlayerbot.DeleteRandomBotAccounts` (see
[§5](#first-boot-the-bots-are-built-before-the-server-opens)) is the blunt but predictable option.

**The account column is a one-way ratchet in practice.** Lowering `Expansion` in `worldserver.conf`
does clamp everyone immediately — the session takes `min(account.expansion, Expansion)` — so you do
*not* need SQL to walk it back, and the stale-high column is harmless while the config is low. But
it is stale, so a later re-raise of the config silently re-grants the higher expansion without
anyone running the SQL. And you cannot repair a lowered config from in-game: `.account set addon`
refuses anything above the config value —

```cpp
if (!expansion || *expansion > sWorld->getIntConfig(CONFIG_EXPANSION))
    return false;
```

— so raising an account always means raising `worldserver.conf` **and restarting** first. If you go
backwards, run the matching `UPDATE account SET expansion = N` too — same command shape as
[step 4 of the flip procedure](#flip-procedure) — so the column and the config agree and the next
forward flip is honest.

**What reverses cleanly:** `RDF.Expansion`, the `CharacterCreating.Disabled.*` masks (they only gate
the create screen, existing characters are untouched), the AH bot's level restriction, and the
`mod-assistant` toggles. Characters already created stay created — turning the Blood Elf mask back
on does not delete anyone's Blood Elf.

---

## 2. Phase gotchas

### RDF is broken at levels 59–60 and 69–70 without a module

This is the biggest one and it is a **client** limitation, not a server bug.

The 3.3.5 client decides which "Random Dungeon" entry to show you from your level alone. From the
[mod-rdf-expansion](https://github.com/azerothcore/mod-rdf-expansion) README:

> Up to character level 58, you can join the "Random Classic Dungeon". However, once the character
> level hits 59, you can no longer join "Random Classic Dungeon" but you can only join "Random
> Burning Crusade Dungeon". This is a client limitation.

Meanwhile the server filters the LFG list by expansion. From `LFGMgr.cpp`:

```cpp
else if (dungeon->expansion > expansion || (onlySeasonalBosses && !dungeon->seasonal))
    lockData = LFG_LOCKSTATUS_INSUFFICIENT_EXPANSION;
```

```cpp
&& dungeon.expansion <= expansion && dungeon.minlevel <= level && level <= dungeon.maxlevel
```

Put those together for phase 1: a level 59–60 character is offered only "Random Burning Crusade
Dungeon" (expansion 1) by the client, and the server refuses it because the session is expansion 0.
**RDF is completely unusable for the last two levels of phase 1** — exactly the levels your friends
will spend the most time at. Same trap at 69–70 in phase 2.

`azerothcore/mod-rdf-expansion` exists precisely for this. It hijacks the queue type:

```ini
#     RDF.Expansion
#        Description: Allow setting which expansion can be used in LFG
#           2 - WOTLK (Default behaviour)
#           1 - TBC (if the player queues WOTLK RDF, join as TBC RDF)
#           0 - Classic  (if the player queues Wotlk or TBC RDF, join as Classic RDF)
#        Default:     2
RDF.Expansion = 2
```

So this module is **required**, not optional, for phases 1 and 2. Add it to `modules.txt` now.
It is maintained in the azerothcore org and has no core patch. ChromieCraft runs progressive caps on
AzerothCore and hits this same problem; the module living in the official org is the strongest
signal that this is the sanctioned fix. *(That ChromieCraft specifically ships it in their
production config: verify.)*

Note also that RDF only ever hands out dungeons whose `maxlevel` covers you, so at cap the pool is
small. RDF also will not queue a group of three at all, which is the other half of the problem, and
the fix for that is [mod-solo-lfg](https://github.com/azerothcore/mod-solo-lfg) — a plain drop-in
module, no core patch, see [modules.md](modules.md) §1.3. Install it, but read
[§3](#who-owns-dungeon-xp) first: its defaults will pin your dungeon XP to `0.2×` on the way in.

### Death Knights

Blocked automatically at `Expansion < 2`. `CharacterHandler.cpp`:

```cpp
// prevent character creating Expansion class without Expansion account
if (classEntry->expansion > Expansion())
{
    SendCharCreate(CHAR_CREATE_EXPANSION_CLASS);
```

The DK class entry is expansion 2, so phases 1 and 2 reject it with no config needed. The
prerequisite-level option you were looking for is:

| Key | Default | Meaning |
|---|---|---|
| `CharacterCreating.MinLevelForHeroicCharacter` | `55` | requires *another* character of at least this level on the account; `0` disables the requirement; ignored for GMs |
| `HeroicCharactersPerRealm` | `1` | how many DKs one account may have |
| `StartHeroicPlayerLevel` | `55` | level a new DK starts at |

**Do not enable DKs during phase 1.** A DK starts at 55 against a cap of 60 — five levels of content
and an instant free character. Even in phase 3, note that `StartHeroicPlayerLevel = 55` plus a cap of
80 is the Blizzlike arrangement and needs no change.

`AiPlayerbot.DisableDeathKnightLogin = 1` is the matching bot-side switch. The playerbots conf
alludes to this too — "each account has 10 bots (or 9 if WotLK is disabled), one bot for each class."

### Blood Elf / Draenei

Same mechanism, race side — both are expansion 1 in `ChrRaces.dbc`, so `Expansion = 0` rejects them
with `CHAR_CREATE_EXPANSION`.

Gotcha: **their starting zones are on the Classic continents and stay physically reachable.** Eversong
Woods, Ghostlands and Silvermoon are on map 0; Azuremyst, Bloodmyst and The Exodar are on map 1. The
`Expansion` check gates *maps* and *character creation*, not zones-within-a-map. In phase 1 anyone can
walk into Silvermoon, and random bots teleporting around map 0/1 may pick those zones as leveling
targets. Harmless, but it looks odd, and it means the "Classic" phase is not visually Classic.

There is no clean config fix. Live with it, or restrict bot teleport targets (see
`AiPlayerbot.RandomBotMaps`, which is map-level only and so cannot express this).

### Flying mounts

Not a problem in practice, for a reason that surprises people: **there is no flying in Eastern
Kingdoms or Kalimdor in 3.3.5 at all** — Azeroth did not become flyable until Cataclysm. So phase 1
has no flying regardless of config. Phase 2 opens Outland (map 530), where flying works normally.
Cold Weather Flying is a level-77 Northrend skill and is therefore self-gating until phase 3.

The bot-side mount levels are period-flavour only:

```ini
AiPlayerbot.UseGroundMountAtMinLevel     = 20   # was 40 in Vanilla, 30 in TBC
AiPlayerbot.UseFastGroundMountAtMinLevel = 40   # was 60 in Vanilla
AiPlayerbot.UseFlyMountAtMinLevel        = 60   # was 70 in TBC
AiPlayerbot.UseFastFlyMountAtMinLevel    = 70
```

Leave them at defaults unless you care; they only affect what bots use, not players.

### Dual spec

**Works at level 40 in phase 1, and this is probably not what a "Classic" phase should feel like.**
`MinDualSpecLevel` is checked in `PlayerGossip.cpp` against level only — there is no expansion
condition anywhere in the path. Dual spec is a WotLK feature that will be live in your Classic phase.

Consistent with the brief ("all WotLK classes/abilities/talent trees stay available throughout"),
leave `MinDualSpecLevel = 40`. If you'd rather it arrive with its own expansion, set it to `70` in
phase 1 and 2 and drop it to `40` at phase 3 — it costs nothing and it's a nice phase-3 "unlock" to
announce.

### Heirlooms

Not expansion-gated as items — `Expansion` gates maps, races and classes, not the item table. An
heirloom handed to a level-1 character in phase 1 works and scales correctly up to the current cap.

But they are effectively unobtainable in phases 1–2, because the vendors are all in Northrend
(Emblem of Heroism vendors in Dalaran, Champion's Seal vendors at the Argent Tournament) or on
Wintergrasp/BG currency, and map 571 is blocked. *(Exact vendor set: verify.)* Net effect: heirlooms
arrive naturally with phase 3 and you don't have to do anything. If you want the XP bonus earlier,
GM-grant them — nothing will break.

### WotLK content still exists in the world DB at Expansion=0

Yes, and mostly it doesn't matter. `Expansion` performs no filtering of `quest_template`,
`item_template`, or creature spawns on the Classic maps. Concretely, in phase 1 you will still see:

- Northrend-bound quest chains and their questgivers in Stormwind Harbour and Orgrimmar.
- The boats/zeppelins to Northrend, physically present and boardable. Using one produces
  `TRANSFER_ABORT_INSUF_EXPAN_LVL` — from `Player.cpp`:
  ```cpp
  if (GetSession()->Expansion() < mEntry->Expansion())
  ```
  The player gets a "you must have Wrath of the Lich King" popup and stays put. Ugly, not broken.
- WotLK recipes, glyphs and vendor items whose *source* is unreachable.
- Anything Caverns of Time: those instances are separate maps with expansion 1, so they're blocked in
  phase 1 even though the Tanaris entrance is on map 1.

None of this is worth fixing for three friends. It is cosmetic clutter, and it's exactly the "loose
gating" that was asked for. The one thing to actually tell your friends: **quest XP is discarded at
cap**, so turning in a stack of banked quests the moment phase 2 opens gains nothing.

### Known core bug

`worldserver` crashes if `MaxPlayerLevel < 55`. Never set a cap below 55 while experimenting.

---

## 3. XP and rates

```ini
# worldserver.conf
Rate.XP.Kill     = 1.5
Rate.XP.Quest    = 1.5
Rate.XP.Quest.DF = 1.5   # dungeon-finder quest XP
Rate.XP.Explore  = 1.5
Rate.XP.Pet      = 1.5

Rate.Pet.LevelXP = 0.05  # leave at the default; see below
```

`Rate.Pet.LevelXP` **is** a multiplier — the correction matters because the name misleads in the
opposite direction to the effect. It multiplies the XP a pet *requires* per level, not the XP it is
granted. Upstream:

> Modifies the amount of experience required to level up a pet. The lower the rate the less
> experience is required. Default: 0.05

So the default already makes pets level ~20× faster than the raw curve, and *raising* it would slow
them down. Leave it alone; `Rate.XP.Pet = 1.5` is the knob on the granting side.

### The gotcha: AutoBalance silently eats your 1.5×

`AutoBalance.RewardScaling.XP` defaults to `1` (on) with `Method = "dynamic"`, and dynamic means:

> If scaling determines that a creature should have an XP scaling multiplier of .65, the creature
> will create 65% of the XP you would normally recieve from a creature at the scaled level.
> […] The XP and money is evenly split amongst all players in the instance.

So in a 3-player 5-man at the default curve (multiplier `0.6843`, derived in §4), XP per mob is
multiplied by ~0.68. Against your 1.5× that nets **1.5 × 0.6843 ≈ 1.03** — you are running at
effectively 1× inside dungeons while questing outdoors pays 1.5×. Dungeon leveling silently becomes
the *worst* way to level, which is the opposite of what a 3-person server wants.

Three ways out:

| Option | Config | Effect | Tradeoff |
|---|---|---|---|
| **Turn reward scaling off** (recommended) | `AutoBalance.RewardScaling.XP = 0` | full XP from weakened mobs; 1.5× applies cleanly | dungeon grinding becomes clearly the fastest leveling path — usually desirable here, but it will outpace questing |
| Compensate with the modifier | keep `= 1`, set `AutoBalance.RewardScaling.XP.Modifier = 1.5` | roughly restores parity | approximate: the modifier is flat, the scaling multiplier moves with group size, so parity only holds at one group size |
| Leave it alone | defaults | dungeons pay ~1× | fine if you want questing to be the main path |

Take the first. Do the same for money if you care:
`AutoBalance.RewardScaling.Money = 0`.

Note the split clause above: **XP is divided among everyone in the instance**, and playerbots are
players. Five bodies in a 5-man means each person gets a fifth. That is normal group behaviour, but
combined with reward scaling it's the second reason dungeon XP feels bad by default.

### The second gotcha: mod-solo-lfg pins dungeon XP to 0.2×

**`AutoBalance.RewardScaling.XP = 0` does not finish the job.** [mod-solo-lfg](modules.md), which
[§2](#rdf-is-broken-at-levels-5960-and-6970-without-a-module) tells you to install because RDF will
not queue three people, ships these defaults in `SoloLfg.conf.dist`:

```ini
SoloLFG.FixedXP     = 1     # "Set the XP rate in dungeons to FixedXPRate"
SoloLFG.FixedXPRate = 0.2   # "The same XP gained in a full party of 5"
```

That is the module's entire XP behaviour, and its own comment says out loud what it does
(`src/Lfg_Solo.cpp`, verbatim):

```cpp
void OnPlayerRewardKillRewarder(Player* /*player*/, KillRewarder* /*rewarder*/, bool isDungeon, float& rate) override
{
    if (!isDungeon
        || !sConfigMgr->GetOption<bool>("SoloLFG.Enable", true)
        || !sConfigMgr->GetOption<bool>("SoloLFG.FixedXP", true))
    {
        return;
    }

    // Force the rate to FixedXPRate regardless of group size, to encourage group play
    rate = sConfigMgr->GetOption<float>("SoloLFG.FixedXPRate", 0.2);
}
```

Four things make this worse than it looks:

- **It ignores whether you queued.** `isDungeon` in `KillRewarder.cpp` is
  `!_isPvP && sMapStore.LookupEntry(_killer->GetMapId())->IsDungeon()`, and `MapEntry::IsDungeon()`
  is `map_type == MAP_INSTANCE || map_type == MAP_RAID`. Every kill in **every instance and every
  raid** is affected, RDF or not, walked in or not.
- **It is not the group split, it replaces the group split.** The `rate` it overwrites was
  `_groupRate * playerLevel / _aliveSumLevel`, and `_groupRate` for a 3-player non-raid group is
  `1.166f` (`Formulas.h`, `xp_in_group_rate`). Three equal-level friends would normally each take
  `1.166 / 3` ≈ **0.389**; forced to `0.2` they take about **half** of that. The smaller the group,
  the bigger the loss — the opposite of what a module named "solo LFG" implies.
- **It stacks under your 1.5×.** `_RewardXP` does `xp = uint32(xp * rate)` and only then calls
  `GiveXP`, which applies `Rate.XP.Kill`. Net for a grouped player in any instance:
  `1.5 × 0.2 = 0.3×` base kill XP. With `RewardScaling.XP` also left at `1` it is `0.3 × 0.68 ≈ 0.2×`.
- **It only bites when you are in a group.** The `rate` argument is consumed inside
  `if (_group)`, so an ungrouped player is untouched. So the tax lands precisely on the three
  friends running a dungeon together, and never while testing solo. That is why this is easy to
  miss.

Set `SoloLFG.FixedXP = 0`. The module's queue-with-fewer-than-five behaviour is in
`SoloLFG.Enable` and is entirely independent of it.

### Who owns dungeon XP

The brief is that **XP is 1.5× at full rate regardless of group size**. Three separate systems will
quietly modify dungeon XP, and each of them defaults to *on* — plus a fourth key,
`AutoBalance.LevelScaling`, which reaches XP indirectly by rewriting creature levels. Exactly one
may own the number, and that one is `Rate.XP.*`. Every other multiplier must be neutral:

| System | Key | Default | **Set to** | Why |
|---|---|---|---|---|
| Core rates — **the owner** | `Rate.XP.Kill` / `.Quest` / `.Quest.DF` / `.Explore` / `.Pet` | `1` | `1.5` | this is the decision; nothing else gets a vote |
| AutoBalance | `AutoBalance.RewardScaling.XP` | `1` | `0` | dynamic scaling shrinks XP with the group; ~`0.68×` at 3-of-5 |
| AutoBalance | `AutoBalance.RewardScaling.Money` | `1` | `0` | same, for gold |
| AutoBalance | `AutoBalance.LevelScaling` | `1` | `1` — **leave on** | the indirect path: it rewrites creature *levels*, and `BaseGain` prices a kill off the live level. But only outside the `[you − 5, you + 3]` skip window, so it never fires at level-appropriate content, and where it does fire it usually raises XP — worked in [§4](#4-autobalance-tuning), *Does LevelScaling eat your 1.5×?* |
| mod-solo-lfg | `SoloLFG.FixedXP` | `1` | `0` | pins every instance kill to `FixedXPRate` |
| mod-solo-lfg | `SoloLFG.FixedXPRate` | `0.2` | *(irrelevant once `FixedXP = 0`)* | leave it; do not "fix" it by setting it to 1.0 |
| mod-individual-xp | `IndividualXp.DefaultXPRate` | `1` | `1` | per-character, opt-in, multiplies on top — see below |

With that set, three friends in a dungeon get the ordinary group split (≈`0.389` each at equal
levels) times `1.5`, and mobs are still weakened by the AutoBalance curve for free. That is the
intended shape: **AutoBalance makes the content survivable, it does not get to price it.**

The normal group split is *not* something to remove. It is Blizzlike, it is what
`Rate.XP.Kill = 1.5` is compensating for, and the only way to opt out of it is per character via
`mod-individual-xp`.

If dungeon XP ever feels wrong, check those keys before touching anything else. The login banners
these modules print say only that they are installed — none of them mentions XP — so there is no
in-game symptom to follow back to the cause.

### Per-player rates — mod-individual-xp

[`azerothcore/mod-individual-xp`](https://github.com/azerothcore/mod-individual-xp) gives each
character its own multiplier. Use it for a friend who joins two months late, or for alts.

```ini
# individual_xp.conf
IndividualXp.Enabled             = true
IndividualXp.Announce            = true
IndividualXp.AnnounceRatesOnLogin = true
IndividualXp.MaxXPRate           = 10
IndividualXp.DefaultXPRate       = 1
```

Commands, verified against the module README:

| Command | Effect |
|---|---|
| `.xp view` | show current rate |
| `.xp set #` | set rate (capped by `MaxXPRate`) |
| `.xp default` | back to `DefaultXPRate` |
| `.xp disable` | stop gaining XP entirely |
| `.xp enable` | resume |

Two things worth knowing, both read out of `src/individual_xp.cpp`:

- **It multiplies on top of the server rate**, it does not replace it. The hook is
  `OnPlayerGiveXP`, which fires after the core has already applied `Rate.XP.*`:
  ```cpp
  amount = static_cast<uint32>(std::round(static_cast<float>(amount) * data->XPRate));
  ```
  So `.xp set 2` on your 1.5× server is an effective 3.0×. `DefaultXPRate = 1` therefore means
  "just the server rate", which is what you want.
- **It's per character, not per account** — stored against `CharacterGUID` in the `individualxp`
  table. A latecomer needs to run `.xp set` on each character.

`.xp disable` is also the clean way to let someone park an alt at a level to play with a friend.

---

## 4. AutoBalance tuning

> **AutoBalance is pinned to the `stable` tag, not `master`, and the two key sets differ in *both*
> directions.** The pin is `5d2778e3` (2024-09-10) — [modules.md](modules.md) §6.1 — and every key
> on this page was read out of *that* tree's `AutoBalance.conf.dist`. Do not fill a gap from
> `master`'s `conf.dist` or from the module's GitHub README: both describe `master`. Diffing the two
> files key-for-key (253 vs 254 set keys), the entire difference is three lines:
>
> | Key | At the pin (`stable`) | On `master` |
> |---|---|---|
> | `AutoBalance.MinPlayers.Raid` | **absent** | present, default `1` |
> | `AutoBalance.MinPlayers.RaidHeroic` | **absent** | present, default `1` |
> | `AutoBalance.LevelScaling.EndGameBoost` | present, default `0` | **dropped** |
>
> At the pin, `MinPlayers` and `MinPlayers.Heroic` are the only two floors and `LoadMapSettings`
> chooses between them on `IsHeroic()` alone — there is no raid branch — so `MinPlayers` is the key
> that applies to a normal 10-man. `EndGameBoost` exists but is inert; its own comment says *"This
> setting is currently not implemented pending a rewrite. Enabling it here has NO effect."*
>
> A `master`-only key written into your conf is not an error you will ever see. AzerothCore warns
> about keys the *code* asks for and cannot find; it does not warn about keys sitting in the file
> that no code reads. It silently does nothing.
>
> Source citations below are line-accurate against the pin, where the whole module is one file,
> `src/AutoBalance.cpp`. `master` has since split it into `src/ABUtils.cpp`,
> `src/ABCommandScript.h` and friends, so a reader following along on GitHub's default branch will
> not find these lines where this page says they are.

### The curve, worked

AutoBalance multiplies creature stats by a number derived from a hyperbolic tangent over the player
count. From `src/AutoBalance.cpp`, `getDefaultMultiplier()`:

```cpp
uint32 maxNumberOfPlayers = map->ToInstanceMap()->GetMaxPlayers();
float  adjustedPlayerCount = mapABInfo->adjustedPlayerCount;

float diff = ((float)maxNumberOfPlayers/5)*1.5f;

float curveCeilingAdjustment =
    inflectionPointSettings.curveCeiling /
    (((tanh(((float)maxNumberOfPlayers - inflectionPointSettings.value) / diff) + 1.0f) / 2.0f) *
    (inflectionPointSettings.curveCeiling - inflectionPointSettings.curveFloor) + inflectionPointSettings.curveFloor);

float defaultMultiplier =
    ((tanh((adjustedPlayerCount - inflectionPointSettings.value) / diff) + 1.0f) / 2.0f) *
    (inflectionPointSettings.curveCeiling * curveCeilingAdjustment - inflectionPointSettings.curveFloor) +
    inflectionPointSettings.curveFloor;
```

The critical detail, which the conf file never states: **`inflectionPointSettings.value` is not your
config value.** It is your config value multiplied by the instance's max player count
(`AutoBalance.cpp:1096`):

```cpp
float inflectionValue = (float)maxNumberOfPlayers;
...
inflectionValue *= InflectionPoint;
```

So `InflectionPoint = 0.5` in a 5-man means the curve is centred at 2.5 players. Substituting
3 players, 5-man, IP 0.5, floor 0.0, ceiling 1.0:

```
value = 5 × 0.5 = 2.5
diff  = (5/5) × 1.5 = 1.5
adj   = 1.0 / ((tanh((5−2.5)/1.5)+1)/2) = 1.0 / 0.965555 = 1.035673
mult  = ((tanh((3−2.5)/1.5)+1)/2) × 1.035673
      = 0.660759 × 1.035673
      = 0.6843
```

which reproduces the documented `0.6843` exactly. The formula is trustworthy; use it to predict
settings instead of guessing.

### Direction: which way makes small groups easier?

**Raising `InflectionPoint` makes small groups EASIER. Lowering it makes them HARDER.**

This is confirmed three independent ways:

1. **From the formula.** `value = maxPlayers × InflectionPoint`. Raising IP raises `value`, which
   shifts the tanh curve to the right, so at a fixed low player count `(players − value)` is more
   negative, `tanh` is smaller, and the multiplier drops. Weaker mobs.
2. **Numerically** (5-man, 3 players, floor 0.0 / ceiling 1.0):

   | `InflectionPoint` | 1p | 2p | **3p** | 4p | 5p |
   |---|---|---|---|---|---|
   | 0.40 | 0.2124 | 0.5092 | **0.8059** | 0.9522 | 1.0000 |
   | 0.45 | — | 0.4281 | **0.7497** | 0.9349 | 1.0000 |
   | **0.50** (default) | 0.1235 | 0.3513 | **0.6843** | 0.9122 | 1.0000 |
   | 0.55 | — | 0.2823 | **0.6116** | 0.8830 | 1.0000 |
   | 0.60 | 0.0695 | 0.2231 | **0.5347** | 0.8464 | 1.0000 |
   | 0.70 | 0.0391 | 0.1353 | **0.3852** | 0.7502 | 1.0000 |

3. **From community practice.** Server operators report the default `0.5` makes scaled-down 10/25-mans
   *too easy* and drop `InflectionPointRaid` to `0.35` to make them harder — the same direction.

> **Two errors in the upstream conf file, so you don't get misled by them.**
> `AutoBalance.conf.dist` says *"A lower value means that difficulty will increase faster as you add
> players."* Over the full range that is backwards — a **higher** IP gives the steeper ramp (at IP
> 0.4 the 1p→5p range is 0.21→1.00, ~4.7×; at IP 0.8 it is 0.02→1.00, ~44×). Be precise about the
> exception, though: it is not wrong *pointwise* at the bottom of the curve. Between 1 and 3 players
> in a 5-man the lower IP does add more per body (IP 0.40: 0.2124→0.8059, +0.59; IP 0.60:
> 0.0695→0.5347, +0.47), because a low IP has already put those counts on the steep middle of the
> tanh while a high IP still has them out on the flat tail. The comment describes that local
> behaviour and generalises it; the generalisation is what fails.
> Its second example is also numerically wrong: it claims IP 0.8 in a 40-man puts half health at 12
> players. Running the real formula gives **~29** players, not 12. (Its *first* example, IP 0.5 → half
> at 20 of 40, checks out.)
> Trust the formula and the table above, not that comment block.

### The other three knobs

| Knob | Direction | Use it for |
|---|---|---|
| `.CurveFloor` | raise → **easier at low counts only** | lifts the bottom of the curve without touching full-group values. Raising floor to 0.2 takes 1p from 0.1235 → 0.2987 and 3p from 0.6843 → 0.7473 — *harder*, note, because it raises the mob multiplier. Use a **negative** floor to make tiny groups easier still |
| `.CurveCeiling` | raise above 1.0 → harder at full counts | making full groups harder than retail. Leave at 1.0 |
| `.BossModifier` | raise → **easier bosses at low counts** | multiplies `inflectionValue` for bosses only. At 5-man/3p: 0.9 → 0.7497, 1.0 → 0.6843, 1.1 → 0.6116 |

Careful with `CurveFloor`: it raises the *mob* multiplier, so a higher floor is **harder** for the
small group. The conf's phrasing ("make enemies have higher stats for lower player counts") is
correct here. The `BossModifier` comment, by contrast, contains a copy-paste bug — it says both
">1.0 easier" and "<1.0 easier" in the same sentence. The formula says **>1.0 is easier**.

### Scenario A — 3 friends, no bots, a 5-man

Default (`0.5`) puts you at `0.6843`: mobs have 68% health *and* deal 68% damage, against 60% of a
full group's bodies. That is very slightly harder than proportional, and it assumes you have a real
tank and healer among the three. For three friends on whatever specs they feel like, it will be
punishing on normal and impossible on heroic.

```ini
# AutoBalance.conf — normal 5-man
AutoBalance.InflectionPoint             = 0.55   # 3p -> 0.6116
AutoBalance.InflectionPoint.CurveFloor  = 0.0
AutoBalance.InflectionPoint.CurveCeiling = 1.0
AutoBalance.InflectionPoint.BossModifier = 1.1   # bosses 3p -> 0.5270, the usual wall

# heroic 5-man: needs materially more help, WotLK heroics assume a real group
AutoBalance.InflectionPointHeroic             = 0.60   # 3p -> 0.5347
AutoBalance.InflectionPointHeroic.CurveFloor  = 0.0
AutoBalance.InflectionPointHeroic.CurveCeiling = 1.0
AutoBalance.InflectionPointHeroic.BossModifier = 1.15

# Both already default to 1 — these lines are no-ops, kept because the number is
# load-bearing and you want to see it. MinPlayers is a *floor* on the count fed to
# the curve; at 1 the curve is free to scale all the way down. Raise it only if you
# deliberately want a solo player to face 3-player-tuned mobs.
AutoBalance.MinPlayers = 1
AutoBalance.MinPlayers.Heroic = 1

# don't let the trio's XP get taxed for the privilege of the content being scaled
AutoBalance.RewardScaling.XP    = 0
AutoBalance.RewardScaling.Money = 0

AutoBalance.PlayerChangeNotify = 1   # prints the new multiplier when someone joins/leaves
```

If it's still too hard, move `InflectionPoint` up in steps of 0.05 and re-measure with
`.ab mapstat`. If it trivialises, move down. Do not touch `StatModifier.*` until the curve is right —
those are a second multiplier applied *after* the curve and they make the curve harder to reason
about.

### Scenario B — 5 players (real or bot) in 10-man Karazhan

Karazhan is a 10-player raid, so `maxNumberOfPlayers = 10` and the raid keys apply
(`InflectionPointRaid`, or `InflectionPointRaid10M` if you set it — the `10M` variants are blank by
default and fall back to the generic raid values).

| `InflectionPointRaid` | 3p | **5p** | 6p | 8p |
|---|---|---|---|---|
| 0.35 | 0.4229 | **0.7407** | 0.8522 | 0.9651 |
| 0.40 | 0.3455 | **0.6729** | 0.8059 | 0.9522 |
| 0.45 | 0.2758 | **0.5975** | 0.7497 | 0.9349 |
| **0.50** (default) | 0.2161 | **0.5178** | 0.6843 | 0.9122 |

Default gives 5 players a `0.5178` multiplier — almost exactly proportional to half a raid. That
sounds right and in practice is too easy, for a reason specific to your setup: **you are running TBC
content with WotLK classes.** Level-70 WotLK talent trees, spell coefficients and class kits are
substantially stronger than the TBC-era kits Karazhan was tuned against. Proportional scaling on top
of that is a walkover.

```ini
# AutoBalance.conf — target: 5 bodies clear Karazhan and it still feels like a raid
AutoBalance.InflectionPointRaid              = 0.40   # 5p -> 0.6729
AutoBalance.InflectionPointRaid.CurveFloor   = 0.0
AutoBalance.InflectionPointRaid.CurveCeiling = 1.0
AutoBalance.InflectionPointRaid.BossModifier = 1.0    # keep bosses at full curve

AutoBalance.Enable.10M = 1        # on by default; confirm you didn't disable it

# There is NO `AutoBalance.MinPlayers.Raid` at the pinned `stable` tag — it is one of the
# three master-only/stable-only keys listed at the top of this section. The floor that
# actually applies to a normal 10-man at the pin is the plain `AutoBalance.MinPlayers`,
# already set to 1 in Scenario A. Nothing extra to set here.
```

Start at `0.40`. If Prince Malchezaar or Netherspite wall you, go to `0.45`. If you clear it first
night, go to `0.35`. Karazhan's difficulty is very unevenly distributed across its bosses, so expect
to end up using per-instance overrides rather than one global number:

```ini
# Karazhan is InstanceID 532. Note there is NO `InflectionPointRaid.PerInstance` —
# the per-instance override is the generic key, and it wins over the size/difficulty
# defaults for that instance. `-1` skips a field.
#   Format: "[InstanceID] [InflectionPoint] [CurveFloor] [CurveCeiling], ..."
AutoBalance.InflectionPoint.PerInstance = "532 0.40 0.0 1.0"

# Per-instance boss tuning if one fight is the blocker. The value is a
# multiplier on the inflection point (same semantics as BossModifier), not a
# new inflection point.
#   Format: "[InstanceID] [InflectionPointMultiplier], ..."
AutoBalance.InflectionPoint.Boss.PerInstance = "532 1.1"
```

Only these two per-instance inflection keys exist — there are no `Raid`/`Heroic` variants of them.
*(Karazhan = 532: verify against your own `.ab mapstat` output before committing it.)*

### LevelScaling — and a trap given your caps

```ini
AutoBalance.LevelScaling        = 1
AutoBalance.LevelScaling.Method = "dynamic"
AutoBalance.LevelScaling.SkipHigherLevels = 3
AutoBalance.LevelScaling.SkipLowerLevels  = 5
AutoBalance.LevelScaling.DynamicLevel.Ceiling.Dungeons = 1
AutoBalance.LevelScaling.DynamicLevel.Floor.Dungeons   = 5
AutoBalance.LevelScaling.DynamicLevel.Ceiling.Raids    = 3
AutoBalance.LevelScaling.DynamicLevel.Floor.Raids      = 5
```

- **`fixed`** — every creature becomes the level of the highest player. Flattens the instance; a
  trash mob and the final boss are the same level.
- **`dynamic`** (default, and what you want) — preserves the instance's internal level spread relative
  to the highest player. Trash stays below you, bosses stay above, scaled into a window defined by the
  Ceiling/Floor keys.

**You want `LevelScaling = 1` on.** For a group of three who level in lockstep it is the single
setting that makes the whole back catalogue playable — every dungeon is level-appropriate whenever
you feel like running it, which matters enormously when your dungeon pool is capped to one expansion
at a time.

#### Does LevelScaling eat your 1.5×?

Short answer: **no, not at level-appropriate content, and it does not need a compensating key.**
Leave it on. The long answer matters because this is a genuinely different path to reduced XP from
the ones [§3](#who-owns-dungeon-xp) is about, and turning off `RewardScaling.XP` does nothing
about it.

`RewardScaling.XP = 0` stops AutoBalance touching the XP *number*. LevelScaling can still reach it
*indirectly*, because it rewrites the creature's actual level — `AutoBalance.cpp` calls
`creature->SetLevel(selectedLevel)` — and the core prices a kill off that same live level
(`Formulas.cpp`, `Acore::XP::Gain`):

```cpp
gain = BaseGain(playerLevel, unit->GetLevel(), GetContentLevelsForMapAndZone(unit->GetMapId(), unit->GetZoneId()));
```

So the concern is real. It just does not fire where you play.

**The skip window is why.** `SkipHigherLevels = 3` and `SkipLowerLevels = 5` are not per-creature
thresholds; they are compared against the *instance's average creature level*. Levels are rewritten
only when

```cpp
avgCreatureLevel > highestPlayerLevel + skipHigherLevels ||
avgCreatureLevel < highestPlayerLevel - skipLowerLevels
```

Inside `[highest player − 5, highest player + 3]` the module sets `isLevelScalingEnabled = false`
and never calls `SetLevel` at all — creature levels, and therefore kill XP, are exactly Blizzlike.
That asymmetric window *is* the definition of level-appropriate content. **Three friends running
dungeons in their level range never see a LevelScaling XP effect.** Nothing to compensate for, so
do not raise `Rate.XP.*` or reach for `RewardScaling.XP.Modifier` on account of it.

Outside the window it moves XP in both directions, and the direction that fires most often here
moves it **up**:

- **Scaled up** — an old dungeon whose average is more than 5 levels below you. Kill XP goes *up*,
  usually from literally zero. `Formulas::GetGrayLevel(60)` is `51` and `BaseGain` returns `0` for
  anything at or below gray, so Deadmines trash at level 17 is worth nothing at all to a 60. Dynamic
  scaling puts it at `(60 + 1) − (21 − 17)` = **57**, inside the `[55, 61]` band the floor and
  ceiling allow and well clear of gray, where it is worth `284` base. Zero to 284 is a gain, not a
  tax.
- **Scaled down** — content you entered several levels early, average more than 3 above you. Kill XP
  drops, but bounded, because `BaseGain` already caps the above-you bonus at 4 levels
  (`if (nLevelDiff > 4) nLevelDiff = 4;`). Worked for a level-66 character in a dungeon whose
  creatures run 70–72, `Ceiling.Dungeons = 1` / `Floor = 5`, content level `61_70` so
  `nBaseExp = 235`:

  | Creature | Unscaled | Scaled to | `BaseGain` | Change |
  |---|---|---|---|---|
  | boss, level 72 | `+4` capped → `678` | `66 + 1` = **67** | `593` | −12.5% |
  | trash, level 70 | `+4` capped → `678` | `67 − (72−70)` = **65** | `531` | −22% |

  Those are base numbers — the elite ×2 and `ModExperience` multipliers land on both columns
  equally, so the percentages are what carry. Ten to twenty-five percent, only on content taken on
  early, in exchange for the mobs being survivable at all. Not in the same class as §3's `0.68×` or
  `0.2×`.

Quest XP is untouched in every case: it comes from the quest's own level and XP index, not from any
creature's level. And at cap the whole question is moot — XP is discarded there anyway.

The trap: with `SkipLowerLevels = 5`, any dungeon more than 5 levels below your highest player gets
scaled **up**. At the level 60 cap in phase 1 that means Deadmines, Wailing Caverns and everything
else becomes a level-60 dungeon the moment a 60 walks in. You cannot go back and casually farm a
low-level instance, and you cannot power-level a friend's alt through one — the alt's dungeon scales
to *your* level, not theirs.

If that matters (a friend joins late and you want to drag them through content):

```ini
# never scale an instance UP; only ever scale down. 80 = "max level of your server"
AutoBalance.LevelScaling.SkipLowerLevels = 80
```

That preserves low-level dungeons at their native level. The cost is that a same-level group running
old content gets no challenge from it. For a latecomer, the better answer is usually
`mod-individual-xp` (§3) rather than dragging them through scaled dungeons.

### Inspection commands — tune empirically

Verified from the command table in `src/AutoBalance.cpp`. `.autobalance` and `.ab` are aliases for
the same table:

| Command | Security | What it does |
|---|---|---|
| `.ab mapstat` | `SEC_PLAYER` | the whole computed state for the instance you're standing in — player count, adjusted count, the multiplier actually in force |
| `.ab creaturestat` | `SEC_PLAYER` | your current target's original vs scaled level, health, damage, and whether AB considers it a boss |
| `.ab setoffset #` | `SEC_GAMEMASTER` | live-adjust `playerCountDifficultyOffset` without a restart |
| `.ab getoffset` | `SEC_PLAYER` | read it back |

`mapstat` and `creaturestat` are `SEC_PLAYER`, so your friends can run them too — useful for "is this
fight actually overtuned or are we bad".

The tuning loop that avoids restarts:

```
1. Enter the instance, .ab mapstat        -> note the multiplier
2. Target the boss, .ab creaturestat      -> note scaled HP / level
3. Pull it. Wipe or clear.
4. .ab setoffset 1                        -> live, no restart: acts as +1 player
   (or edit AutoBalance.conf and .reload config, which AutoBalance supports)
5. Repeat until it feels right, then write the equivalent InflectionPoint into the conf
```

`setoffset` moves in whole players, which is coarse — use it to bracket the answer quickly, then
convert to a precise `InflectionPoint` using the tables above. `.reload config` does re-read
AutoBalance's settings, so once you're bracketing finely you can edit and reload rather than restart.

Turn on debug logging while tuning, in `worldserver.conf`, after the `Logger.module` line:

```ini
Logger.module.AutoBalance=5,Console Server
Logger.module.AutoBalance_StatGeneration=5,Console Server
```

Also worth knowing: **the player count is combat-locked.** While the map is in combat the adjusted
count only ever ratchets *up*, never down (`combatLockMinPlayers` in `AutoBalance.cpp`). If a bot dies
and releases mid-fight, the encounter does not get easier — which is correct, but it means "we lost
two people and it stayed hard" is expected behaviour, not a bug.

---

## 5. Playerbots tuning for a 3-person server

Upstream defaults assume a populated realm and will flatten an 8 GB box:

```ini
AiPlayerbot.MinRandomBots = 500      # upstream default
AiPlayerbot.MaxRandomBots = 500      # upstream default
```

**`AiPlayerbot.MinRandomBots` / `MaxRandomBots` are the options that control how many random bots
exist** — not `RandomBotAutologin` (that's the on/off switch for the random-bot system as a whole)
and not `RandomBotAccountCount` (that's how many *accounts* get created, and `0` means "work it out
from MaxRandomBots automatically").

500 bots is roughly 25× what you want. The wiki's 16 GB minimum is sized for exactly that number
roaming the world and loading map grids; at 30 bots parked near your party it does not apply.

### A starting `playerbots.conf` for ~3 friends + 30 bots on 8 GB

```ini
# ── population ───────────────────────────────────────────────────────────────
AiPlayerbot.Enabled            = 1
AiPlayerbot.RandomBotAutologin = 1
AiPlayerbot.MinRandomBots      = 30
AiPlayerbot.MaxRandomBots      = 30
AiPlayerbot.RandomBotAccountCount = 0      # auto-size from MaxRandomBots
AiPlayerbot.AddClassAccountPoolSize = 10   # default 50; each account is 10 chars

# ── activity: the single biggest CPU lever ───────────────────────────────────
# Rough % of bots simulated when no real player is near. Bots in combat, in an
# instance, in a BG/LFG queue, or grouped with a real player are ALWAYS active on
# top of this, so a low number here costs you nothing that you can see.
AiPlayerbot.BotActiveAlone = 10
AiPlayerbot.BotActiveAloneDurationSeconds = 30

AiPlayerbot.BotActiveAloneForceWhenInRadius = 150
AiPlayerbot.BotActiveAloneForceWhenInZone   = 1
AiPlayerbot.BotActiveAloneForceWhenInMap    = 0   # keep 0 — 1 wakes a whole continent
AiPlayerbot.BotActiveAloneForceWhenIsFriend = 0
AiPlayerbot.BotActiveAloneForceWhenInGuild  = 1

# SmartScale sheds bot activity automatically when server tick time climbs.
# floor/ceiling are milliseconds of world update time.
AiPlayerbot.botActiveAloneSmartScale = 1
AiPlayerbot.botActiveAloneSmartScaleDiffLimitfloor   = 50
AiPlayerbot.botActiveAloneSmartScaleDiffLimitCeiling = 150   # tighter than the 200 default
AiPlayerbot.botActiveAloneSmartScaleWhenMinLevel = 1
AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel = 60        # == current cap, see §1

# ── level window: bots must not exist above the cap ──────────────────────────
AiPlayerbot.RandomBotMinLevel = 1
AiPlayerbot.RandomBotMaxLevel = 60          # move with the phase
AiPlayerbot.RandomBotMinLevelChance = 0.1
AiPlayerbot.RandomBotMaxLevelChance = 0.4   # default 0.1; bias toward cap so there
                                            # are actually bots to run dungeons with
AiPlayerbot.SyncLevelWithPlayers = 0        # see note below

# ── geography ────────────────────────────────────────────────────────────────
AiPlayerbot.RandomBotMaps = 0,1             # phase 1; add 530, then 571
AiPlayerbot.DisableDeathKnightLogin = 1     # phase 1 and 2
AiPlayerbot.LimitTalentsExpansion   = 0     # keep full WotLK trees, per the brief

# ── things to switch off on a 3-person realm ─────────────────────────────────
AiPlayerbot.RandomBotJoinBG     = 0   # nobody is doing BGs; this burns CPU on
AiPlayerbot.RandomBotAutoJoinBG = 0   # instanced battlegrounds you'll never see
AiPlayerbot.RandomBotJoinLfg    = 0   # bots occupying the LFG queue competes with you
AiPlayerbot.AllowGuildBots      = 0   # skip bot guild simulation
AiPlayerbot.RandomBotGuildCount = 0
AiPlayerbot.RandomBotGuildNearby = 0
AiPlayerbot.RandomBotInvitePlayer = 0 # stop bots cold-inviting your friends
AiPlayerbot.PreQuests           = 0   # default; marking quests complete slows bot creation
AiPlayerbot.EnablePeriodicOnlineOffline = 0  # keep the roster fixed and small

# ── pacing: fewer, gentler background operations ─────────────────────────────
AiPlayerbot.RandomBotUpdateInterval    = 30    # default 20
AiPlayerbot.RandomBotsPerInterval      = 10    # default 60 — this is a burst size
AiPlayerbot.RandomBotCountChangeMinInterval = 1800
AiPlayerbot.RandomBotCountChangeMaxInterval = 7200
AiPlayerbot.MinRandomBotInWorldTime    = 3600
AiPlayerbot.MaxRandomBotInWorldTime    = 28800
AiPlayerbot.MinRandomBotTeleportInterval = 3600
AiPlayerbot.MaxRandomBotTeleportInterval = 18000
```

Notes on the choices that aren't obvious:

- **`RandomBotsPerInterval = 10`.** This is how many bots are logged in/out/updated per manager
  cycle. The default 60 against a 30-bot roster means the manager churns the entire population every
  cycle. Lowering it smooths the sawtooth in tick time at startup.
- **`RandomBotMaxLevelChance = 0.4`.** With 30 bots and the default 10% at-cap chance, you get ~3 bots
  at cap — not enough to fill a dungeon. Biasing this up is the difference between "bots exist" and
  "bots are useful".
- **`SyncLevelWithPlayers`.** Setting this to `1` ties max bot level to the highest online player
  instead of `RandomBotMaxLevel`, which sounds ideal for phase gating but means bots track whoever
  logs in rather than the phase. Leave it `0` and drive `RandomBotMaxLevel` from the phase flip — it
  is explicit and it survives someone being GM-levelled.
- **`RandomBotJoinLfg = 0`** is a real tradeoff. On, bots populate the dungeon finder and your
  queues actually pop; off, you save the CPU and use `.playerbots bot add` instead. With three people
  who play together, adding bots directly is better and more controllable. Turn it back on if you
  ever want RDF to work unattended.
- Watch `AiPlayerbot.BotActiveAlone` first if the box struggles. Going 10 → 5 halves background bot
  simulation and you will not notice, because everything near you is force-active anyway.

### First boot: the bots are built before the server opens

**This is the longest unexplained wait in bring-up and it looks exactly like a hang.** Budget for it
and do not kill the container.

Before `worldserver` accepts a single login, `RandomPlayerbotFactory::CreateRandomBots()` runs
during world load and creates the bot **accounts** and then a full roster of **characters** on each.
This is not the same thing as bots logging in; that happens later and is fast.

How much gets built is not `MaxRandomBots`. It is:

```
accounts    = ceil(MaxRandomBots / charsPerAccount) + AddClassAccountPoolSize
characters  = accounts × charsPerAccount
```

`charsPerAccount` is 10 (one per class) — or **9 when Death Knights are unavailable**, which in
phase 1 they are twice over (`Expansion = 0` and `DisableDeathKnightLogin = 1`). Skewing
`RandomBotAllianceRatio`/`RandomBotHordeRatio` away from 50/50 reduces it further. So for the config
above, in phase 1:

| | accounts | characters |
|---|---|---|
| random bots (`MaxRandomBots = 30`, ÷9) | `ceil(30/9)` = **4** | 36 |
| addclass pool (`AddClassAccountPoolSize = 10`) | **10** | 90 |
| **total built on first boot** | **14** | **126** |

Note which term dominates: the addclass pool, not the bot count. At the upstream defaults (500 bots,
pool 50) it would be ~100 accounts and about a thousand characters — which is the real reason first
boot has a reputation. Dropping the pool from 50 to 10 is most of the saving, and 10 addclass
accounts is still 90 characters to pull a tank or healer from.

What it prints, on the `playerbots` logger, in this order:

```
Creating random bot accounts...
Waiting for 14 accounts loading into database (N queries)...
>> 14 Accounts loaded into database in NNNN ms
Creating random bot characters...
Creating cache for names per gender and race...
Waiting for 126 characters loading into database (N queries)...
>> 126 Characters loaded into database in NNNN ms
>> 14 random bot accounts with 126 characters available     <- server.loading logger; this is "done"
```

Both `Waiting for …` loops just poll the async DB write queue once a second and print nothing in
between, so a long gap after either line is normal, not a stall. The work is MySQL write throughput,
not CPU — if it is slow, that is a database tuning problem ([hosting.md](hosting.md)), and the module
times itself, so the `in NNNN ms` figures tell you exactly where it went. *(Wall-clock on the target
box: measure on the night — the module hands you the number. Minutes rather than seconds is the
right expectation for 126 characters on a small VPS.)*

Two things that make this a one-time cost:

- **Reboots are nearly free.** Both loops skip accounts that already exist and accounts that already
  hold 10 characters, so on every later boot `account_creation` and `bot_creation` are zero and
  neither `Waiting for …` line appears at all. If you see them again, something deleted the accounts.
- **Redoing it is deliberate.** `AiPlayerbot.DeleteRandomBotAccounts = 1` wipes every bot account and
  character, then **stops the server** with `Please reset the AiPlayerbot.DeleteRandomBotAccounts to
  0 and restart the server...`. That is the reset button, and it is the only supported way to change
  `AiPlayerbot.RandomBotAccountPrefix` — the conf says "Do not change this prefix while there are
  existing bot accounts."

After creation, bots log in: up to `RandomBotsPerInterval` bots processed per manager cycle, one
cycle every `RandomBotUpdateInterval` seconds. At `10` per cycle and a 30 s interval, a 30-bot roster
is up in about three cycles — call it a minute and a half. There is also a startup "turbo boost":
while server uptime is under `MaxRandomBots × 0.51` seconds (≈15 s at 30 bots) the manager ignores
`RandomBotUpdateInterval` and re-runs about twice a second. Note that window is measured against
*uptime*, so on a first boot where character creation ran for minutes it will already have expired;
it is really a second-boot optimisation. **The signal to watch is `Random Bots Stats: N online`.**
When N settles between `MinRandomBots` and `MaxRandomBots`, the roster is up.

Bots are created at level 1 and get their level, gear and talents on their *first randomize*, which
happens after they log in — each bot gets one manager action per cycle, so this lands within the
same handful of cycles. So "all the bots are level 1 in white gear" for the first minute or two is
expected and self-corrects. It is only a real problem if it is still true well after
`Random Bots Stats` has stopped climbing.

### Commands

Party control (from the module wiki; `.playerbots` is the command root):

| Command | Effect |
|---|---|
| `.playerbots bot add <name1,name2,...>` | log in your alt-bots into your party |
| `.playerbots bot add *` | log in all your alt-bots |
| `.playerbots bot remove <name1,...>` | log them out |
| `.playerbots bot remove *` | log all of them out |
| `.playerbots bot list` | your alt-bots and available characters |
| `.playerbots bot addclass <class>` | spawn a fresh random bot of that class — use `dk` for Death Knight |

`addclass` is the one you'll actually use: it pulls from the `AddClassAccountPoolSize` pool and gives
you a level-appropriate bot of a chosen class on demand, which is how you fill a tank or healer slot
for a dungeon.

In-party, bots are driven by chat (`summon`, plus the strategy/command system). There are 100+
commands; the [wiki](https://github.com/mod-playerbots/mod-playerbots/wiki) is the reference.

### Addons

Chat-driving five bots is miserable. Client-side addons give you a real UI — see
[client.md](client.md) for the install. The ones that exist:

| Addon | Notes |
|---|---|
| [Wishmaster117/MultiBot-Chatless](https://github.com/Wishmaster117/MultiBot-Chatless) | drives bots without spamming chat |
| [whipowill/wow-addon-playerbots](https://github.com/whipowill/wow-addon-playerbots) | panel UI |
| PlayerbotsPanel | referenced from the module wiki's addons page |

The module wiki maintains the canonical list on its
[Playerbot Addons and Sub-Modules](https://github.com/mod-playerbots/mod-playerbots/wiki/Playerbot-Addons-and-Sub%E2%80%90Modules)
page — check it before installing, since these move.

### Bot caveat at Expansion < 2 — resolved

Playerbots create characters through their own path rather than a real client session, so the
question was whether they respect `Expansion` when rolling races. **They do**, on both counts, and
it is confirmed in `RandomPlayerbotFactory::CreateRandomBot`:

```cpp
// skip disabled with config races
if ((1 << (race - 1)) & sWorld->getIntConfig(CONFIG_CHARACTER_CREATING_DISABLED_RACEMASK))
    continue;
...
if (IsValidRaceClassCombination(race, cls, sWorld->getIntConfig(CONFIG_EXPANSION)))
    raceOptions.push_back(race);
```

Both the race mask and `CONFIG_EXPANSION` are honoured, and the class loop a few lines up applies
`CONFIG_CHARACTER_CREATING_DISABLED_CLASSMASK` the same way. So `Expansion = 0` alone is enough to
keep Blood Elf and Draenei bots from being created, and the
`CharacterCreating.Disabled.RaceMask = 1536` in [§1](#phase-1--classic-cap-60) is genuine
belt-and-braces rather than a required workaround.

The one thing that does *not* follow from this: **bot characters are created once, on first boot**
(see above), against whatever `Expansion` was in force then, and races are chosen at creation and
never re-rolled. Raising `Expansion` at a phase flip does not go back and add Blood Elf or Draenei
bots to the existing roster — the per-account loop is bounded by `cls < MAX_CLASSES - count`, so an
account that already holds a full set is skipped or nearly so, and the classes it would add are the
lowest class IDs, not the newly-unlocked one. Expect your phase-2 and phase-3 bot population to look
like phase 1's, minus the Death Knights you never got. Rebuilding with
`AiPlayerbot.DeleteRandomBotAccounts` is the only way to change that, and it costs you every bot's
level and gear. Worth a sanity check after each flip, from `/srv/wow/wowserver/deploy`:

```bash
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_characters \
  -e "SELECT race, COUNT(*) FROM characters GROUP BY race;"
```

*(Whether a partially populated account gets topped up at all, and with what, is fiddly enough that
it is worth just looking at the counts after the flip rather than predicting it.)*

---

## 6. Bots + AutoBalance interaction

**Playerbots count as players for AutoBalance.** This is not incidental — it is the reason
Playerbots was chosen over NPCBots ([../README.md](../README.md)). AutoBalance builds its player list
straight off the map's player list with no filter (`AutoBalance.cpp`):

```cpp
Map::PlayerList const& playerList = map->GetPlayers();
// ... every Player in the map is pushed into allMapPlayers
mapABInfo->playerCount = mapABInfo->allMapPlayers.size() ? mapABInfo->allMapPlayers.size() : 1;
```

A playerbot is a real `Player` object in that list. So:

> **Bots are an alternative to scaling, not a stack on top of it.**

Every bot you bring pushes the player count up and pushes the difficulty multiplier back toward
1.0 — while also adding a body that fights. The two effects are designed to cancel. What you must
*not* expect is to bring bots *and* keep the 3-player difficulty; you get one or the other.

Worked, for a normal 5-man at `InflectionPoint = 0.55`:

| Party | AB player count | Multiplier | Effective |
|---|---|---|---|
| 3 friends | 3 | 0.6116 | mobs at 61%, 3 bodies — the scaled experience |
| 3 friends + 1 bot | 4 | 0.8830 | mobs at 88%, 4 bodies — close to Blizzlike |
| 3 friends + 2 bots | 5 | 1.0000 | mobs at 100%, 5 bodies — exactly Blizzlike, AB does nothing |

All three are legitimate. They are different *games*, though, and you should pick deliberately:

**Run a 3-man dungeon with no bots.** Three people, `MinPlayers = 1`, let the curve do the work. This
is the better experience — everyone matters, nobody is watching an AI tank, and the loot is split
three ways instead of five. Use AutoBalance as the primary mechanism and reserve bots for when the
composition genuinely doesn't work (no tank, no healer, nothing that can dispel).

**Run 10-man Karazhan with bots to reach 5.** At 3 real players Karazhan scales to `0.2161` at the
default raid curve — a 78% stat cut. Fights with hard mechanics (Opera event, Netherspite's beams,
Chess) do not scale down; they need *bodies* in specific places regardless of how weak the mobs are.
Scaling cannot solve a mechanic that requires four people standing in four spots. Bring bots to five,
accept a `0.6729` multiplier at `InflectionPointRaid = 0.40`, and let the bots be the extra bodies.

The rule of thumb: **scale for numbers, bot for mechanics.** If the content is failing because you
lack damage or healing, lower the curve. If it's failing because a mechanic demands N players, add
bots.

Three consequences to keep in mind:

- **Bots dilute rewards.** XP and money are split across everyone in the instance (§3), and loot rolls
  include bots. Five bodies means 3/5 of the drops go to your friends instead of 3/3. With
  `RewardScaling.XP = 0` the XP hit is just the normal group split, which is survivable — but it is a
  real cost of bringing bots that scaling doesn't have.
- **Adding a bot mid-fight ratchets difficulty up permanently.** Combat locking means the adjusted
  count only rises during combat. Summoning a bot mid-pull raises the multiplier and it will not drop
  when the bot dies. Bring bots *before* you pull.
- **`PlayerChangeNotify = 1`** prints the recalculated multiplier to everyone in the instance when the
  count changes. Leave it on — it makes this whole interaction visible instead of mysterious.

---

## 7. Do-not-do list

**Do not run `mod-solocraft` alongside `mod-autobalance`.** They solve the same problem from opposite
ends and both key off group size, so they compose multiplicatively. Solocraft "adjusts player stats
for raids based on the # of players in the group" — it *buffs the players*. AutoBalance *weakens the
mobs*. Run both and a 3-man 5-man gets mobs at ~61% health facing players with inflated health,
damage and spellpower. Content becomes trivial and, worse, un-tunable: you now have two curves
multiplying and no single knob that predicts the result. Pick one. AutoBalance is the right pick here
because scaling mobs down preserves relative encounter tuning, whereas buffing players breaks every
threat/healing ratio the encounters were built around.

*(There is no upstream "these two conflict" warning — the incompatibility is mechanical, not
documented. Do not go looking for a compatibility flag; there isn't one.)*

Others:

| Don't | Why |
|---|---|
| `MaxPlayerLevel < 55` | known AzerothCore crash |
| Flip `Expansion` without `UPDATE account SET expansion` | existing accounts stay on the old expansion silently — §1 |
| Ship phase 1 or 2 without `mod-rdf-expansion` | RDF is dead at levels 59–60 and 69–70 — §2 |
| `AiPlayerbot.LimitTalentsExpansion = 1` | clamps bot talent trees below the players' — contradicts "full WotLK trees throughout" |
| Enable Death Knights in phase 1 | DK starts at 55 against a cap of 60 |
| Tune `StatModifier.*` before `InflectionPoint` | a second multiplier on top of the curve; makes the curve impossible to reason about |
| `AutoBalance.LevelScaling.Method = "fixed"` | flattens trash and bosses to one level; `dynamic` is strictly better here |
| Stack `mod-individual-xp` rates carelessly | it multiplies *on top of* `Rate.XP.*` — `.xp set 2` on a 1.5× server is 3× |
| Assume NPCBots would work instead | they don't count toward AutoBalance's player count — [../README.md](../README.md) |
| Install `mod-solo-lfg` and leave `SoloLFG.FixedXP = 1` | its default pins **every instance and raid kill** to `FixedXPRate = 0.2`, replacing the group split, under your 1.5× — net `0.3×`. `RewardScaling.XP = 0` does not save you. Set `SoloLFG.FixedXP = 0` — [§3](#who-owns-dungeon-xp) |
| Let more than one system scale dungeon XP | `Rate.XP.*` owns it. `AutoBalance.RewardScaling.XP` and `SoloLFG.FixedXP` both default to *on* and both silently reprice it; `mod-individual-xp` multiplies on top whenever someone has set a rate — [§3](#who-owns-dungeon-xp) |
| Lower `MaxPlayerLevel` below a live character's level | no de-levelling; the character is frozen *and* gets extrapolated stats from `BuildPlayerLevelInfo` instead of the real table — [§1](#going-backwards) |
| Expect `.reload config` to flip a phase | `MaxPlayerLevel` and `Expansion` are `Reloadable::No`; the console says so and the flip half-applies — [§1](#everything-that-moves-in-one-table) |
