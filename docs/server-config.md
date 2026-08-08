# Server config — phases, rates, scaling, bots

Gameplay tuning for the three-phase progression described in [../README.md](../README.md).
Everything here is per-config; none of it needs a code change.

Config keys below were read out of the actual `.conf.dist` files at the versions pinned in
`build/modules.txt`. Where a key is quoted with a default, that default is verbatim from upstream.

---

## 1. The three phases

**This section is the canonical per-phase checklist. If a per-phase value appears anywhere else in
these docs, it is a copy; this is the original.**

**One key defines a phase: `MaxPlayerLevel`.** Everything else on this page is bookkeeping that has
to stay in step with it — the bot level window, the dungeon finder's expansion, the auction-house
bot's level ceiling, and the mod-assistant profession and flight-path tiers. Five config files
move: `worldserver.conf`, `playerbots.conf`, `mod-rdf-expansion.conf`, `mod_ahbot.conf` and
`mod_assistant.conf`. **No SQL moves.**

`Expansion` stays at `2` in all three phases, so every race and class is available from phase 1 and
the `CharacterCreating.Disabled.*` masks stay at their upstream `0`. That is the deliberate call
described in [../README.md](../README.md#the-tradeoff-outland-is-open-at-58) and restated with its
costs in [§2](#the-accepted-tradeoff-outland-and-northrend-are-reachable) below. It removes the
worst failure mode the strict version had: a per-phase `UPDATE account SET expansion` that, when
missed, silently stranded every existing account on the old expansion.

What each module is and why it is installed lives in [modules.md](modules.md); the values its keys
take per phase live here.

### `account.expansion` — the one-time setup step

Do this **once, before first boot**, not per phase. It is one line and it is easy to skip because
nothing visibly breaks until someone tries to make a Death Knight.

`Expansion` in `worldserver.conf` is **not** the value the game uses. It is a *ceiling* applied at
login. From `src/server/game/Server/WorldSocket.cpp`:

```cpp
uint32 world_expansion = sWorld->getIntConfig(CONFIG_EXPANSION);
if (Expansion > world_expansion)
    Expansion = world_expansion;
```

The session's effective expansion is `min(account.expansion, Expansion)`. The column is stamped by
`AccountMgr::CreateAccount` with `CONFIG_EXPANSION` **at the moment the account is created**:

```cpp
stmt->SetData(3, uint8(sWorld->getIntConfig(CONFIG_EXPANSION)));
```

So the setup step is really "make sure `Expansion = 2` is in `worldserver.conf` before the first
account exists". `2` is also the upstream default (`worldserver.conf.dist` ships `Expansion = 2`),
so the only way to get this wrong is to actively write a lower number and then raise it later.
Playerbot accounts go through the same function — `RandomPlayerbotFactory` calls
`sAccountMgr->CreateAccount(accountName, password)` — so the `rndbot%` accounts are stamped `2`
too, on the first boot that creates them.

Run this once anyway, as a belt-and-braces line in bring-up, and again any time you have restored
an old auth dump:

```sql
UPDATE account SET expansion = 2;
```

Verify rather than assume — one query, and it covers real accounts and bots at once:

```bash
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
  -e "SELECT expansion, COUNT(*) FROM account GROUP BY expansion;"
```

Anything other than a single `2` row means somebody booted once with a lower `Expansion`. The
in-game equivalent is `.account set addon <accountname> 2`, and it is capped by `CONFIG_EXPANSION`,
so the config has to be right first either way.

### Everything that moves, in one table

Every per-phase change, in every file. Nothing else needs to change — and nothing in the auth
database changes at all. The per-phase blocks below are the same thing in copy-paste form.

| File | Key | P1 (60) | P2 (70) | P3 (80) | Takes effect on |
|---|---|---|---|---|---|
| `worldserver.conf` | `MaxPlayerLevel` | `60` | `70` | `80` | **restart only** |
| `playerbots.conf` | `AiPlayerbot.RandomBotMaxLevel` | `60` | `70` | `80` | restart |
| `playerbots.conf` | `AiPlayerbot.RandomBotMaps` | `0,1` | `0,1,530` | `0,1,530,571` | restart |
| `playerbots.conf` | `AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel` | `60` | `70` | `80` | restart |
| `mod-rdf-expansion.conf` | `RDF.Expansion` | `0` | `1` | `2` | restart |
| `mod_ahbot.conf` | `AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel` | `60` | `70` | `80` | restart, or `.ahbot reload` |
| `mod_assistant.conf` | `Assistant.Professions.Master.Enabled` | `0` | `1` | `1` | restart |
| `mod_assistant.conf` | `Assistant.Professions.GrandMaster.Enabled` | `0` | `0` | `1` | restart |
| `mod_assistant.conf` | `Assistant.FlightPaths.WrathOfTheLichKing.Enabled` | `0` | `0` | `1` | restart |

Nine keys across five files, down from thirteen keys plus an `UPDATE`. What left the table, and
why, so nobody reintroduces it from an older draft:

| Was in the table | Now | Why |
|---|---|---|
| `Expansion` | fixed at `2` | all races/classes on from phase 1; the cap is the only gate |
| `CharacterCreating.Disabled.RaceMask` | fixed at `0` (upstream default) | Blood Elf and Draenei are available in phase 1 |
| `CharacterCreating.Disabled.ClassMask` | fixed at `0` (upstream default) | Death Knights are available in phase 1 |
| `AiPlayerbot.DisableDeathKnightLogin` | fixed at `0` (upstream default) | DK bots from phase 1; see [§5](#5-playerbots-tuning-for-a-3-person-server) |
| `UPDATE account SET expansion` | one-time, `2` | [above](#accountexpansion--the-one-time-setup-step) |

Rows marked plain *restart* are marked that way because the flip is a restart regardless; whether
those modules would also pick the key up from `.reload config` is untested and does not matter here.
The one marked **restart only** is different — it says so from the core, not from caution. In
`src/server/game/World/WorldConfig.cpp` it is registered `ConfigValueCache::Reloadable::No`:

```cpp
SetConfigValue<uint32>(CONFIG_MAX_PLAYER_LEVEL, "MaxPlayerLevel", DEFAULT_MAX_LEVEL, ConfigValueCache::Reloadable::No, [](uint32 const& value) { return value > 0 && value <= MAX_LEVEL; }, "> 0 && <= MAX_LEVEL");
SetConfigValue<uint32>(CONFIG_EXPANSION, "Expansion", 2, ConfigValueCache::Reloadable::No);
```

`Expansion` is quoted alongside it because it is the same kind of key and you will want to know
this the one time you *do* change it — its upstream default is `2`, which is what we run.

`.reload config` will edit neither, and it tells you so rather than failing silently — from
`ConfigValueCache.h`:

> `Server Config (Name: {}) cannot be changed by reload. A server restart is required to update this config value.`

Grep the console for that line after any flip you attempted without a restart. Since the key that
defines the phase needs a restart, **a phase flip is always a restart**; treat `.reload config` as
a tuning tool (see [§4](#4-autobalance-tuning)), not a flip tool.

`mod_ahbot.conf` and `mod_assistant.conf` come from [modules.md](modules.md) §1.4 and §1.5.
`mod_ahbot.conf` additionally needs a **one-time install step** that is not per-phase — see the
note under [phase 1](#phase-1--classic-cap-60) — and until you do it the `MaxLevel` row above is
inert. The other `Assistant.FlightPaths.*` keys (`Vanilla.RequiredLevel = 60`,
`BurningCrusade.RequiredLevel = 70`) are *level* gates, not phase gates — they are already correct
for all three phases and must not be touched.

### Phase 1 — Classic, cap 60

```ini
# worldserver.conf
MaxPlayerLevel = 60          # <- the only key that moves between phases

# ── phase-invariant, but this block is what bring-up.md says to paste before
#    first boot, so the whole worldserver decision set lives here ─────────────

Expansion = 2                # upstream default. Does NOT move. All races and
                             # classes on from phase 1; the cap is the only gate.
                             # Cost of this: ../README.md and §2 below.

# Both are upstream defaults (0) and both stay there. Listed explicitly because
# an earlier draft of this page set them, and a stale copy would silently
# re-close Blood Elf, Draenei and Death Knight.
CharacterCreating.Disabled.RaceMask  = 0
CharacterCreating.Disabled.ClassMask = 0

StartPlayerLevel       = 1
StartHeroicPlayerLevel = 55   # DK start level. Validator requires <= MaxPlayerLevel,
                              # so 55 is legal against a cap of 60. See §2.
MinDualSpecLevel       = 40
HeroicCharactersPerRealm = 1  # DKs per account; raise if you want more
CharacterCreating.MinLevelForHeroicCharacter = 55   # needs another 55+ char on the
                                                    # account — the real DK brake

# Rates. §3 owns these numbers and explains what each one does and does not do.
Rate.XP.Kill     = 2
Rate.XP.Quest    = 2
Rate.XP.Quest.DF = 2
Rate.XP.Explore  = 2
Rate.XP.Pet      = 2

Rate.Reputation.Gain = 10
# Rate.Reputation.LowLevel.Kill / .LowLevel.Quest deliberately left at their
# default 1 — they multiply on top of Gain. §3.

Rate.Drop.Item.Poor      = 3
Rate.Drop.Item.Normal    = 3
Rate.Drop.Item.Uncommon  = 3
Rate.Drop.Item.Rare      = 3
Rate.Drop.Item.Epic      = 3
Rate.Drop.Item.Legendary = 3
Rate.Drop.Item.Artifact  = 3
Rate.Drop.Money          = 3
# Rate.Drop.Item.Referenced / .ReferencedAmount / .GroupAmount left at 1. §3.

Rate.Talent = 1.4            # 71 points at 60 / 85 at 70 / 99 at 80. §3.

# Default is 0, and there is no worldserver-cli binary — without SOAP,
# scripts/phase.sh and the weekly restart in hosting.md §7.6 have no way to
# reach a running server.
SOAP.Enabled = 1
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMinLevel = 1
AiPlayerbot.RandomBotMaxLevel = 60
AiPlayerbot.RandomBotMaps     = 0,1          # Eastern Kingdoms, Kalimdor only —
                                             # bots capped at 60 have no business
                                             # in Outland even though it is open
AiPlayerbot.DisableDeathKnightLogin = 0      # upstream default; DK bots from phase 1
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

No SQL. `account.expansion` was set to `2` once at
[setup](#accountexpansion--the-one-time-setup-step) and never moves again.

### Phase 2 — TBC, cap 70

```ini
# worldserver.conf
MaxPlayerLevel = 70
# Expansion stays 2. The masks stay 0. Nothing else in this file moves.
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMaxLevel = 70
AiPlayerbot.RandomBotMaps     = 0,1,530       # + Outland
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

No SQL.

### Phase 3 — WotLK, cap 80

```ini
# worldserver.conf
MaxPlayerLevel = 80
# Expansion is already 2 and always was. This phase changes one number.
```

```ini
# playerbots.conf
AiPlayerbot.RandomBotMaxLevel = 80
AiPlayerbot.RandomBotMaps     = 0,1,530,571   # + Northrend (upstream default)
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

No SQL. Phase 3 is the upstream default configuration in every respect except the rates.

### What does *not* change per phase

- **`Expansion`.** `2`, always. Every race and class is creatable from phase 1 — Death Knight,
  Blood Elf, Draenei. `CharacterCreating.Disabled.RaceMask` and `.ClassMask` stay at their upstream
  `0`. This is the change that makes the flip one key instead of thirteen, and its cost is
  [§2](#the-accepted-tradeoff-outland-and-northrend-are-reachable).
- **`account.expansion`.** Set once at
  [setup](#accountexpansion--the-one-time-setup-step). There is no per-phase `UPDATE` any more, and
  if you find one in an older copy of these notes, delete it — running `UPDATE account SET
  expansion = 0` would lock every account out of two thirds of the game.
- **AutoBalance.** Nothing in it keys off `MaxPlayerLevel`; it scales off the actual level of the
  highest player in the instance. It follows the cap automatically. You may still want to retune
  `InflectionPointRaid*` per phase, because the raid content itself changes (40-mans in phase 1,
  Karazhan in phase 2, 10/25s in phase 3) — see [§4](#4-autobalance-tuning).
- **All four rates.** XP 2×, reputation 10×, loot 3×, `Rate.Talent = 1.4` — throughout, every
  phase. [§3](#3-xp-and-rates).
- **Talents, spellbook, glyphs.** Left at WotLK for all phases, per the brief, and now with 20
  extra points at the phase-1 cap on top. Do **not** set `AiPlayerbot.LimitTalentsExpansion = 1` —
  it exists to clamp bot talent trees to 6 rows below level 61 / 8 rows below 71, which would make
  bots weaker than the humans they're playing alongside, and it interacts badly with a 1.4× point
  budget they can't spend.

### Flip procedure

```bash
# 1. Announce, in-game, a few days ahead and again on the night.
.announce Phase 2 opens in 5 minutes. The cap goes to 70 and Outland is worth doing. Server restarting.

# 2. Graceful shutdown with a 300s countdown; the client shows a timer and
#    saves are flushed.
.server shutdown 300

# 3. Edit the five confs — eight keys. Version them; never hand-edit on the box.
#    (scripts/phase.sh does this from the repo copies — spec below.)

# 4. Restart.
docker compose up -d

# 5. Verify — see below.
```

Four steps, and none of them is SQL. The old step 4 — `UPDATE account SET expansion = N`, the one
that got missed — is gone: the column was set to `2` once at
[setup](#accountexpansion--the-one-time-setup-step) and there is nothing left for a flip to
desync. If you need a database query for anything on this page, the form is:

```bash
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth -e "…"
```

run from `/srv/wow/wowserver/deploy`. There is no mysql client on the host and the mysql service
publishes no ports, so the query runs inside the container; the password comes from the mounted
0600 option file, never from `-p` on a command line. `/etc/mysql/backup.cnf` is
`deploy/mysql-backup.cnf` bind-mounted into the mysql service — 0600, gitignored, generated by
`scripts/backup.sh` from `deploy/.env`. Where it comes from, why `--defaults-extra-file` has to be
the first argument, and what to do if it is missing:
[hosting.md §7.3](hosting.md#73-backups). Every DB query on this page uses that form.

Verification checklist, in this order — each one catches a different failure:

| Check | How | Expected |
|---|---|---|
| Config actually loaded | worldserver console at boot | no `Missing name`/`Invalid value` lines for the keys you touched |
| Cap moved | on a throwaway char at the old cap, kill something | XP bar advances past the old cap |
| Talents scaled with it | `.character level` a throwaway to the new cap, open the talent frame | 85 points at 70, 99 at 80 — `Rate.Talent` multiplies the *total*, so it grows with the cap |
| RDF | open Dungeon Finder at cap | random dungeon entry is offered and queueable, and it offers the phase's expansion |
| Bots followed | `.playerbots bot list`, check a bot's level | bots exist above the old cap after a randomize cycle |
| AH bot ceiling | browse the auction house | nothing listed above the new cap's gear level |

The RDF check is the one that fails quietly. Do not skip it.

Two checks that were in this list and are now permanently unnecessary — do not re-add them from an
older copy: *"session expansion reads the new value"* and *"walk a real char through the Dark
Portal"*. Both tested a per-phase expansion move that no longer happens. The Dark Portal works in
every phase, on purpose.

### `scripts/phase.sh` — spec

One argument, `1`, `2` or `3`. Idempotent: running it twice for the same phase is a no-op plus a
restart. It does three things, in this order.

**1. Rewrite the confs.** The repo holds the deployed `.conf` files; the script rewrites in place
the eight keys in [the table above](#everything-that-moves-in-one-table) across the five files,
then writes them to the container's config volume. Rewrite by key (`^\s*Key\s*=`), never by line
number — module confs get new keys upstream and line numbers rot. Refuse to run if a key the script
expects to find is absent: a silently-skipped `MaxPlayerLevel` is a flip that did nothing but
restart the server.

The script must **not** touch `Expansion`, `CharacterCreating.Disabled.RaceMask`,
`CharacterCreating.Disabled.ClassMask` or `AiPlayerbot.DisableDeathKnightLogin`. They are not
phase keys. A `phase.sh` inherited from the strict-gating draft would set them, and setting
`Expansion = 0` on a realm whose accounts are stamped `2` clamps every session to Classic — the
same outage the old design risked, arrived at from the opposite direction.

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

**3. Restart and verify.** `docker compose up -d`, then re-run the verification checklist above.
Do not offer a `--reload` mode: `MaxPlayerLevel` is `Reloadable::No`, so a reload-only flip changes
the bots and the dungeon finder while leaving the cap where it was — the worst possible half-state.

There is no database step. The script touches no SQL at all, which also means it needs no auth-DB
credentials; if a version of `phase.sh` asks for `deploy/.env`, it is doing something this spec
does not ask for.

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

**Talent points shrink, and the spent points do not come back cleanly.** `CalculateTalentsPoints`
recomputes from level, so dropping the cap 70 → 60 takes a character from 85 points to 71. The
talents themselves are still spent in the tree. Expect to hand out `.reset talents` after any
backwards cap move; see [§3](#talents--ratetalent--14) for the arithmetic.

**`Expansion` no longer participates**, which is most of why going backwards is now survivable at
all. It sits at `2` in every phase, so there is no expansion to walk back, no
`min(account.expansion, Expansion)` clamp to reason about, and no stale auth column waiting to
silently re-grant something at the next forward flip. Leave it alone in both directions.

If you ever do lower it — don't, but if — know that the session clamp bites immediately while the
`account.expansion` column stays high and stale, and that you cannot repair it from in-game,
because `.account set addon` refuses anything above the config value:

```cpp
if (!expansion || *expansion > sWorld->getIntConfig(CONFIG_EXPANSION))
    return false;
```

So raising an account always means raising `worldserver.conf` **and restarting** first. That
asymmetry is exactly what the fixed `Expansion = 2` design exists to avoid.

**What reverses cleanly:** `RDF.Expansion`, the AH bot's level restriction, and the
`mod-assistant` toggles. Characters already created stay created regardless.

---

## 2. Phase gotchas

### The accepted tradeoff: Outland and Northrend are reachable

State this plainly rather than discovering it in play. **With `Expansion = 2` from phase 1, the
Dark Portal works at 58 and the boats and zeppelins to Northrend work at 68.** Nothing is closed.
The level cap is the only gate, and it is a soft one: it makes the next expansion pointless rather
than forbidden.

This was a deliberate call. The reasoning, so it can be re-argued rather than re-litigated:

**Why it is fine.** XP is discarded at cap — `Player::GiveXP` returns immediately once
`level >= CONFIG_MAX_PLAYER_LEVEL` — so a level-60 in Hellfire Peninsula earns nothing, unlocks
nothing and advances no character. There is no race to get ahead because there is no ahead. What
the strict version bought in exchange for its thirteen keys was mostly *aesthetics*: the boats
still existed, the Northrend questgivers still stood in Stormwind Harbour, Silvermoon was still
walkable on map 0. It closed a handful of maps and cost two genuine outages for it — the
`account.expansion` desync that silently stranded existing accounts, and RDF dying at 59–60
because the client offers only TBC dungeons that an expansion-0 session then refuses. Both of
those are now structurally impossible.

**What it costs.** Someone determined can walk through the portal at 58 and come back with Outland
greens and quest rewards that outclass anything phase 1 can drop, and a geared 60 could farm
Ramparts. Dungeon and raid *lockouts* do not care about your level either, so a phase-1 group
could in principle go clear Karazhan. There is no config that closes this without `Expansion = 0`,
which brings both outages back with it. With three friends, "don't do that" is a cheaper
enforcement mechanism than a config key, and cheaper still than the zone-blocker modules that
exist for this — deliberately not installed, because the entire point is that a phase flip is one
key.

Second-order consequences worth knowing before someone finds them:

- **Flying works in Outland in phase 1.** Expert Riding is a level-60 skill in 3.3.5 (it was moved
  down from 70 in patch 3.0.2), so a capped phase-1 character can train it and fly. There is still
  no flying in Eastern Kingdoms or Kalimdor in any phase — Azeroth did not become flyable until
  Cataclysm.
- **Cold Weather Flying is level 77**, so Northrend flight is self-gating until phase 3 regardless.
- **Death Knights exist from phase 1** — see [below](#death-knights).
- **Caverns of Time instances are open**, because they are expansion-1 maps and nothing gates them
  any more.

### RDF at levels 59–60 and 69–70 — the module is still wanted, for a different reason

> Up to character level 58, you can join the "Random Classic Dungeon". However, once the character
> level hits 59, you can no longer join "Random Classic Dungeon" but you can only join "Random
> Burning Crusade Dungeon". This is a client limitation.

The server then filters the LFG list by the session's expansion. From `LFGMgr.cpp`:

```cpp
else if (dungeon->expansion > expansion || (onlySeasonalBosses && !dungeon->seasonal))
    lockData = LFG_LOCKSTATUS_INSUFFICIENT_EXPANSION;
```

```cpp
&& dungeon.expansion <= expansion && dungeon.minlevel <= level && level <= dungeon.maxlevel
```

**`Expansion = 2` defuses the hard failure.** In the strict design a level-59 in phase 1 was
offered only "Random Burning Crusade Dungeon" and the server refused it with
`LFG_LOCKSTATUS_INSUFFICIENT_EXPANSION` — RDF was simply dead for the last two levels of phases 1
and 2, at exactly the levels people spend the most time. With the session at expansion 2 that
lockout cannot fire, so RDF always works.

What is left is a *flavour* problem rather than an outage, and it is still worth fixing: without
the module, a level-59 in phase 1 queues and gets dropped into Hellfire Ramparts. The dungeon
finder becomes the fastest route to the tradeoff described above — it will actively send you to
Outland, unasked, one level before the cap.

`azerothcore/mod-rdf-expansion` hijacks the queue type so that does not happen:

```ini
#     RDF.Expansion
#        Description: Allow setting which expansion can be used in LFG
#           2 - WOTLK (Default behaviour)
#           1 - TBC (if the player queues WOTLK RDF, join as TBC RDF)
#           0 - Classic  (if the player queues Wotlk or TBC RDF, join as Classic RDF)
#        Default:     2
RDF.Expansion = 2
```

At `RDF.Expansion = 0` a phase-1 level-59 who queues the only entry the client will show them gets
a Classic dungeon. **Keep the module and keep the key per-phase** — it is the one thing still
holding the dungeon finder inside the phase. It is maintained in the azerothcore org and has no
core patch. ChromieCraft runs progressive caps on AzerothCore and hits the same client limitation;
the module living in the official org is the strongest signal that this is the sanctioned fix.
*(That ChromieCraft specifically ships it in their production config: verify.)*

Its status has changed, though: it went from **required** (without it, no RDF at all at 59–60) to
**strongly wanted** (without it, RDF works but ships you to the wrong expansion). If a build ever
has to drop it, phases 1 and 2 are playable; they just leak.

Note also that RDF only ever hands out dungeons whose `maxlevel` covers you, so at cap the pool is
small. RDF also will not queue a group of three at all, which is the other half of the problem, and
the fix for that is [mod-solo-lfg](https://github.com/azerothcore/mod-solo-lfg) — a plain drop-in
module, no core patch, see [modules.md](modules.md) §1.3. Install it, but read
[§3](#who-owns-dungeon-xp) first: its defaults will pin your dungeon XP to `0.2×` on the way in.

### Death Knights

**Available from phase 1.** The gate is `CharacterHandler.cpp`:

```cpp
// prevent character creating Expansion class without Expansion account
if (classEntry->expansion > Expansion())
{
    SendCharCreate(CHAR_CREATE_EXPANSION_CLASS);
```

The DK class entry is expansion 2 and the session is expansion 2, so the check passes in every
phase. `CharacterCreating.Disabled.ClassMask` stays at its upstream `0`.

What actually paces DKs is the level prerequisite, and the defaults are the right numbers:

| Key | Default | Meaning |
|---|---|---|
| `CharacterCreating.MinLevelForHeroicCharacter` | `55` | requires *another* character of at least this level on the account; `0` disables the requirement; ignored for GMs |
| `HeroicCharactersPerRealm` | `1` | how many DKs one account may have |
| `StartHeroicPlayerLevel` | `55` | level a new DK starts at |

So nobody rolls a DK on night one: you need a 55 first, which in a phase-1 world is most of the
levelling curve. Then you get one DK per account, starting at 55 against a cap of 60. That is five
levels of content on a free character — a real shortcut, and the accepted price of "all classes on
from phase 1". If it turns out to matter, `MinLevelForHeroicCharacter` is the dial (raise it to
60 and a DK costs you a capped character first); do not reach for `ClassMask`.

`StartHeroicPlayerLevel = 55` is validated against `MaxPlayerLevel`
(`value > 0 && value <= CONFIG_MAX_PLAYER_LEVEL`), so it is legal at a cap of 60 and needs no
per-phase change. Note the corollary: this is another reason never to drop the cap below 55.

**Bot side: `AiPlayerbot.DisableDeathKnightLogin = 0`** — the upstream default, and it now stays
there in all three phases. DK bots handle their own level floor;
`RandomPlayerbotMgr::RandomizeFirst` does

```cpp
if (bot->getClass() == CLASS_DEATH_KNIGHT)
{
    maxLevel = std::max(maxLevel, sWorld->getIntConfig(CONFIG_START_HEROIC_PLAYER_LEVEL));
    minLevel = std::max(minLevel, sWorld->getIntConfig(CONFIG_START_HEROIC_PLAYER_LEVEL));
}
```

so in phase 1 DK bots roll into `[55, 60]` rather than the `[1, 60]` window everyone else uses.
No config needed. The knock-on for first boot is in [§5](#5-playerbots-tuning-for-a-3-person-server):
with DKs available, each bot account holds 10 characters instead of 9.

### Blood Elf / Draenei

**Available from phase 1.** Both are expansion 1 in `ChrRaces.dbc` and the session is expansion 2,
so `CHAR_CREATE_EXPANSION` never fires. `CharacterCreating.Disabled.RaceMask` stays at its upstream
`0` — an earlier draft set it to `1536`, and that number should not reappear anywhere.

The thing this makes moot, worth recording because it was a real argument for the strict design:
their starting zones sit on the Classic continents and were always physically reachable. Eversong
Woods, Ghostlands and Silvermoon are on map 0; Azuremyst, Bloodmyst and The Exodar are on map 1.
`Expansion` gates *maps* and *character creation*, never zones-within-a-map, so phase 1 was never
going to look visually Classic no matter what the mask said. Now the population matches the
scenery.

Bots follow automatically: `RandomPlayerbotFactory::IsValidRaceClassCombination` takes
`CONFIG_EXPANSION`, so at `2` the first-boot roster rolls Blood Elves and Draenei alongside
everything else — see [§5](#bot-roster-composition-settled-at-first-boot).

### Flying mounts

**Flyable in Outland from phase 1**, which surprises people twice over. There is no flying in
Eastern Kingdoms or Kalimdor in 3.3.5 at all — Azeroth did not become flyable until Cataclysm — so
"can they fly?" is only ever a question about Outland and Northrend. Outland is open in every
phase, and Expert Riding is a **level-60** skill in 3.3.5 (moved down from 70 in patch 3.0.2), so a
capped phase-1 character can train it and fly there. Cold Weather Flying is level 77 and therefore
self-gating until phase 3.

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

They are still effectively unobtainable in phases 1–2, but the reason has changed: it is no longer
the map. Northrend is reachable now. It is the **currency**, which is level-gated rather than
expansion-gated — Emblems of Heroism come from level-80 heroics, Champion's Seals from Argent
Tournament dailies that require 80, and Stone Keeper's Shards from Wintergrasp. *(Exact vendor and
currency set: verify.)* A level-60 can walk to Dalaran and look at the vendor; they cannot pay it.

Net effect is unchanged: heirlooms arrive naturally with phase 3 and you do not have to do
anything. If you want the XP bonus earlier, GM-grant them — nothing will break. Note they multiply
on top of the 2×.

### Off-phase content is visible, reachable, and worth nothing

This used to be a section about cosmetic clutter with a hard wall behind it. With `Expansion = 2`
the wall is gone and only the clutter and the cap remain. `Expansion` never filtered
`quest_template`, `item_template` or creature spawns anyway. Concretely, in phase 1:

- Northrend-bound quest chains and their questgivers stand in Stormwind Harbour and Orgrimmar, and
  now you can actually take them.
- The boats and zeppelins to Northrend work. `TRANSFER_ABORT_INSUF_EXPAN_LVL` —
  `if (GetSession()->Expansion() < mEntry->Expansion())` in `Player.cpp` — can no longer fire,
  because the session is always at the ceiling.
- The Dark Portal works at 58.
- Caverns of Time instances are open; they are expansion-1 maps and nothing gates them.
- WotLK recipes, glyphs and vendor items are all sourceable if someone goes and sources them.

**The cap is what makes all of it pointless.** Tell your friends the one thing that actually
matters: **XP is discarded at cap.** Banking quests to turn in the moment phase 2 opens gains
nothing, and levelling in Hellfire at 60 gains nothing. Everything else here is a matter of taste,
and the taste we picked is "the door is open, there is nothing behind it worth having yet" —
[the tradeoff](#the-accepted-tradeoff-outland-and-northrend-are-reachable).

### Known core bug

`worldserver` crashes if `MaxPlayerLevel < 55`. Never set a cap below 55 while experimenting.

---

## 3. XP and rates

Four decisions: **XP 2×, reputation 10×, loot 3×, +20 talent points at the phase-1 cap.** They are
phase-invariant. Each subsection below says who owns the number, what it multiplies, and — the part
that matters most for loot — what it does *not* touch.

Every key on this page was read out of the actual `worldserver.conf.dist` on branch `Playerbot` of
`mod-playerbots/azerothcore-wotlk`, and cross-checked against its registration in
`src/server/game/World/WorldConfig.cpp`. A key that does not exist is silently ignored, so the
registration is the check that matters: if it is in `WorldConfig.cpp`, some code reads it.

### XP — `Rate.XP.*` = 2

```ini
# worldserver.conf
Rate.XP.Kill     = 2
Rate.XP.Quest    = 2
Rate.XP.Quest.DF = 2   # dungeon-finder quest XP
Rate.XP.Explore  = 2
Rate.XP.Pet      = 2

Rate.Pet.LevelXP = 0.05  # leave at the default; see below
```

`Rate.Pet.LevelXP` **is** a multiplier — the correction matters because the name misleads in the
opposite direction to the effect. It multiplies the XP a pet *requires* per level, not the XP it is
granted. Upstream:

> Modifies the amount of experience required to level up a pet. The lower the rate the less
> experience is required. Default: 0.05

So the default already makes pets level ~20× faster than the raw curve, and *raising* it would slow
them down. Leave it alone; `Rate.XP.Pet = 2` is the knob on the granting side.

Not set, deliberately: the six `Rate.XP.BattlegroundKill*` keys and `Rate.XP.BattlegroundBonus`.
They exist, they default to `1`, and nobody on a three-person realm is doing battlegrounds. Same
for `Rate.Honor`.

### The gotcha: AutoBalance silently eats your 2×

`AutoBalance.RewardScaling.XP` defaults to `1` (on) with `Method = "dynamic"`, and dynamic means:

> If scaling determines that a creature should have an XP scaling multiplier of .65, the creature
> will create 65% of the XP you would normally recieve from a creature at the scaled level.
> […] The XP and money is evenly split amongst all players in the instance.

So in a 3-player 5-man at the default curve (multiplier `0.6843`, derived in §4), XP per mob is
multiplied by ~0.68. Against your 2× that nets **2 × 0.6843 ≈ 1.37** — you are running at
effectively 1.37× inside dungeons while questing outdoors pays 2×. Dungeon leveling silently
becomes the *worst* way to level, which is the opposite of what a 3-person server wants, and the
decision is explicitly that **nothing may reduce dungeon XP**.

Three ways out:

| Option | Config | Effect | Tradeoff |
|---|---|---|---|
| **Turn reward scaling off** (the decision) | `AutoBalance.RewardScaling.XP = 0` | full XP from weakened mobs; 2× applies cleanly | dungeon grinding becomes clearly the fastest leveling path — desirable here, but it will outpace questing |
| Compensate with the modifier | keep `= 1`, set `AutoBalance.RewardScaling.XP.Modifier = 1.46` | roughly restores parity | approximate: the modifier is flat, the scaling multiplier moves with group size, so parity only holds at one group size. Rejected — it is a second system pricing XP |
| Leave it alone | defaults | dungeons pay ~1.37× | contradicts the decision |

Take the first. Do the same for money if you care:
`AutoBalance.RewardScaling.Money = 0`.

Note the split clause above: **XP is divided among everyone in the instance**, and playerbots are
players. Five bodies in a 5-man means each person gets a fifth. That is normal group behaviour, but
combined with reward scaling it's the second reason dungeon XP feels bad by default.

### The second gotcha: mod-solo-lfg pins dungeon XP to 0.2×

**`AutoBalance.RewardScaling.XP = 0` does not finish the job.** [mod-solo-lfg](modules.md), which
[§2](#rdf-at-levels-5960-and-6970--the-module-is-still-wanted-for-a-different-reason) tells you to
install because RDF will not queue three people, ships these defaults in `SoloLfg.conf.dist`:

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
- **It stacks under your 2×.** `_RewardXP` does `xp = uint32(xp * rate)` and only then calls
  `GiveXP`, which applies `Rate.XP.Kill`. Net for a grouped player in any instance:
  `2 × 0.2 = 0.4×` base kill XP. With `RewardScaling.XP` also left at `1` it is
  `0.4 × 0.6843 ≈ 0.27×`. Raising XP to 2× makes this *worse* in absolute terms, not better —
  you'd be paying 0.27× while believing you'd paid for 2×.
- **It only bites when you are in a group.** The `rate` argument is consumed inside
  `if (_group)`, so an ungrouped player is untouched. So the tax lands precisely on the three
  friends running a dungeon together, and never while testing solo. That is why this is easy to
  miss.

Set `SoloLFG.FixedXP = 0`. The module's queue-with-fewer-than-five behaviour is in
`SoloLFG.Enable` and is entirely independent of it.

### Who owns dungeon XP

The decision, precisely: **dungeon XP is exactly what three players would earn in vanilla, times
two.** Nothing may reduce it. The vanilla three-player number *includes* the ordinary group split —
that split is the baseline, not a tax — and the 2× goes on top of it.

Three separate systems will quietly modify dungeon XP and each of them defaults to *on*, plus a
fourth key, `AutoBalance.LevelScaling`, which reaches XP indirectly by rewriting creature levels.
Exactly one may own the number, and that one is `Rate.XP.*`. Every other multiplier must be
neutral:

| System | Key | Default | **Set to** | Why |
|---|---|---|---|---|
| Core rates — **the owner** | `Rate.XP.Kill` / `.Quest` / `.Quest.DF` / `.Explore` / `.Pet` | `1` | `2` | this is the decision; nothing else gets a vote |
| AutoBalance | `AutoBalance.RewardScaling.XP` | `1` | `0` | dynamic scaling shrinks XP with the group; ~`0.68×` at 3-of-5 |
| AutoBalance | `AutoBalance.RewardScaling.Money` | `1` | `0` | same, for gold |
| AutoBalance | `AutoBalance.LevelScaling` | `1` | `1` — **leave on** | the indirect path: it rewrites creature *levels*, and `BaseGain` prices a kill off the live level. But only outside the `[you − 5, you + 3]` skip window, so it never fires at level-appropriate content, and where it does fire it usually raises XP — worked in [§4](#4-autobalance-tuning), *Does LevelScaling eat your 2×?* |
| mod-solo-lfg | `SoloLFG.FixedXP` | `1` | `0` | pins every instance kill to `FixedXPRate` |
| mod-solo-lfg | `SoloLFG.FixedXPRate` | `0.2` | *(irrelevant once `FixedXP = 0`)* | leave it; do not "fix" it by setting it to 1.0 |
| mod-individual-xp | `IndividualXp.DefaultXPRate` | `1` | `1` | per-character, opt-in, multiplies on top — see below |

With that set, three friends in a dungeon get the ordinary group split (≈`0.389` each at equal
levels) times `2` — call it `0.778` of a solo kill each, per mob, against `0.389` on a vanilla
realm — and mobs are still weakened by the AutoBalance curve for free. That is the intended shape:
**AutoBalance makes the content survivable, it does not get to price it.**

The normal group split is *not* something to remove. It is Blizzlike, it is the "what 3 players
would earn" the decision is written against, and the only way to opt out of it is per character via
`mod-individual-xp`.

**Nothing else in the build touches XP.** The other sixteen pinned modules in
[modules.md](modules.md) §6.1 were checked file by file — every `.cpp`, `.h` and `.conf.dist` at
the pinned SHA, grepped for `GiveXP`, `OnPlayerGiveXP`, `OnPlayerRewardKillRewarder`, `RATE_XP`,
`Rate.XP` and `XPRate`. Zero hits. `mod-weekend-xp` would be a fourth multiplier and is
deliberately **not** in the build ([modules.md](modules.md) §3). Re-run that grep whenever a module
is added; it is the only way to catch this class of problem, because —

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
  So `.xp set 2` on your 2× server is an effective **4.0×**, and `MaxXPRate = 10` is a ceiling of
  20× in practice. `DefaultXPRate = 1` therefore means "just the server rate", which is what you
  want.
- **It's per character, not per account** — stored against `CharacterGUID` in the `individualxp`
  table. A latecomer needs to run `.xp set` on each character.

`.xp disable` is also the clean way to let someone park an alt at a level to play with a friend.

### Reputation — `Rate.Reputation.Gain` = 10

```ini
# worldserver.conf
Rate.Reputation.Gain = 10

# LEFT AT 1 ON PURPOSE. These multiply on top of Gain — setting them to 10 as well
# would be 100× on the content they cover.
Rate.Reputation.LowLevel.Kill  = 1
Rate.Reputation.LowLevel.Quest = 1
```

**One key owns it.** `Rate.Reputation.Gain` is applied in `ReputationMgr::SetOneFactionReputation`
to every incremental gain, whatever its source:

```cpp
if (incremental)
{
    stand *= sWorld->getRate(RATE_REPUTATION_GAIN);
}
```

That is the whole mechanism — kills, quests, spell-granted rep, all of it, once.

**Why the LowLevel keys stay at 1.** They are applied earlier, in
`Player::CalculateReputationGain`, and the result then goes through `SetOneFactionReputation`, so
they genuinely compose multiplicatively with `Gain`. `10 × 10 = 100×` is the trap the decision is
avoiding. Two corrections to the obvious reading of their names, both from the same function:

```cpp
case REPUTATION_SOURCE_KILL:  rate = sWorld->getRate(RATE_REPUTATION_LOWLEVEL_KILL);  break;
...
if (rate != 1.0f && creatureOrQuestLevel <= Acore::XP::GetGrayLevel(GetLevel()))
    percent *= rate;
```

- They only fire on content **at or below your grey level**. They are not a general low-level
  bonus; they are specifically "rep from things too trivial to give XP".
- The guard is `rate != 1.0f`, so at the default `1` the branch is skipped entirely. Leaving them
  alone is genuinely a no-op, not a `× 1`.

Also left alone: `Rate.Reputation.Gain.WSG` / `.AB` / `.AV`, which upstream documents as *"applied
IN ADDITION to the global Rate.Reputation.Gain"* — battlegrounds, irrelevant here — and
`Rate.Reputation.RecruitAFriendBonus` at its `0.1` default.

Faction-specific overrides in the `reputation_reward_rate` world-DB table also multiply on top
(`percent *= repRate`), and a row with rate `0` disables that faction's rep entirely. Nothing in
the pinned module set writes to that table, but it is the one place a "why is this faction not
moving at 10×" answer could hide.

### Loot — 3×, and be honest about what that means

```ini
# worldserver.conf
Rate.Drop.Item.Poor      = 3
Rate.Drop.Item.Normal    = 3
Rate.Drop.Item.Uncommon  = 3
Rate.Drop.Item.Rare      = 3
Rate.Drop.Item.Epic      = 3
Rate.Drop.Item.Legendary = 3
Rate.Drop.Item.Artifact  = 3
Rate.Drop.Money          = 3

# LEFT AT 1. These are a different mechanism — see below.
Rate.Drop.Item.Referenced       = 1
Rate.Drop.Item.ReferencedAmount = 1
Rate.Drop.Item.GroupAmount      = 1
```

Those seven quality keys are the complete tier list — `Poor` through `Artifact`, matching
`qualityToRate[]` in `LootMgr.cpp`, and the code guards with `pProto->Quality < ITEM_QUALITY_HEIRLOOM`,
so heirlooms (quality 7) are excluded by design.

**This multiplies a drop *chance*, and there are two large categories it cannot touch.** Say so
out loud, because "3× loot" sounds like it means three times the loot and it does not.

**1. Anything already at 100% is untouched.** `LootStoreItem::Roll` returns before the rate is even
looked up:

```cpp
if (_chance >= 100.0f)
    return true;

if (reference)
    return roll_chance_f(_chance * (rate ? sWorld->getRate(RATE_DROP_ITEM_REFERENCED) : 1.0f));

ItemTemplate const* pProto = sObjectMgr->GetItemTemplate(itemid);
float qualityModifier = 1.0f;
if (pProto && pProto->Quality < ITEM_QUALITY_HEIRLOOM && rate)
    qualityModifier = sWorld->getRate(qualityToRate[pProto->Quality]);

return roll_chance_f(_chance * qualityModifier);
```

**2. Grouped loot ignores the quality rates entirely.** A loot *group* is a pick-one bucket, and
`LootTemplate::LootGroup::Roll` walks it on the raw `item->chance` with no quality modifier
anywhere in the function — it subtracts each chance from a single roll and returns the first entry
that wins. Multiplying a pick-one bucket would be meaningless, so the code does not.

Boss loot in AzerothCore is overwhelmingly grouped or referenced-then-grouped, and the guaranteed
drops are guaranteed. **So this 3× is a trash-and-world-drop multiplier.** Concretely:

| What | Effect of 3× | Why |
|---|---|---|
| Random greens off trash | ~3× as often (until a chance saturates at 100%) | non-grouped `Entries`, chance well under 100 |
| World drop epics, rare-mob drops | ~3× as often | same path |
| Quest items, guaranteed boss tokens | **nothing** | `_chance >= 100.0f` returns early |
| The item a boss picks from its loot group | **nothing** | grouped, raw chance |
| Gold from any source | 3× | `Rate.Drop.Money` is applied to the rolled amount, not a chance |

If a real "bosses drop more" is ever wanted, the keys for it are `Rate.Drop.Item.GroupAmount` and
`Rate.Drop.Item.ReferencedAmount` — upstream describes them as *"Makes many dungeon bosses (and
others) drop additional loot"* and *"Makes many raid bosses (and others) drop additional loot"*.
They multiply *counts*, not chances, and `GroupAmount` is read into a `uint32`, so it truncates and
only integer values do anything. They are left at `1` deliberately: tripling every boss's loot pile
is a much larger change than "3× loot" and it is not what was asked for. `Rate.Drop.Item.Referenced`
is left at `1` for the same reason — it is a chance multiplier on whole reference *tables* firing,
not a quality tier.

Nothing in the pinned module set overrides this. `mod-aoe-loot`, `mod-quest-loot-party` and
`mod-junk-to-gold` were grepped for `RATE_DROP` / `Rate.Drop` / `OnItemRoll`: no hits. The one
script hook that could intercept it, `sScriptMgr->OnItemRoll`, is unused by anything installed.

### Talents — `Rate.Talent` = 1.4

**+20 talent points at the level-60 cap: 51 becomes 71.** One key, and it multiplies the *total*,
so it scales with the cap rather than staying a fixed bonus.

```ini
# worldserver.conf
Rate.Talent = 1.4
```

`Player::CalculateTalentsPoints` is the whole calculation:

```cpp
uint32 base_talent = GetLevel() < 10 ? 0 : GetLevel() - 9;
...
talentPointsForLevel += m_extraBonusTalentCount;
sScriptMgr->OnPlayerCalculateTalentsPoints(this, talentPointsForLevel);
return uint32(talentPointsForLevel * sWorld->getRate(RATE_TALENT));
```

**The rounding is a C-style cast to `uint32`, which truncates toward zero — it does not round.**
That matters: `71.4` and `71.9` both give 71. Worked at each cap:

| Level | Base (`level − 9`) | `× 1.4` | **Points** | Gain |
|---|---|---|---|---|
| 60 | 51 | 71.4 | **71** | +20 |
| 70 | 61 | 85.4 | **85** | +24 |
| 80 | 71 | 99.4 | **99** | +28 |

All three land comfortably clear of a boundary, so float imprecision in `1.4f` (which is really
1.39999997…) cannot flip them: the products are 71.3999…, 85.3999… and 99.3999….

Notes on the edges:

- **It applies below the cap too**, at every level from 10 up: a level-20 has `11 × 1.4 = 15`
  points instead of 11. The bonus is proportional throughout levelling, not a lump at cap.
- **It is `Reloadable::Yes`**, with a validator of `>= 0`. So unlike `MaxPlayerLevel` you can
  `.reload config` it — though characters only pick the new total up at their next
  `InitTalentForLevel`.
- **Lowering it later is destructive.** Points already spent stay spent while the budget shrinks;
  expect to hand out `.reset talents`. Same applies to any backwards cap move —
  [§1](#going-backwards).
- **`Rate.Talent.Pet` is a separate key** and stays at `1`. Hunter pet talents are not part of this
  decision.
- **Bots get the same budget**, since they run the same `CalculateTalentsPoints`. This is another
  reason not to set `AiPlayerbot.LimitTalentsExpansion = 1` — a bot handed 71 points and clamped to
  6 talent rows has nowhere to put them.
- **Client side: 71 points spend fine.** The deepest single tree costs 51 points to bottom out, so
  71 buys a full tree plus a 20-point secondary — which is roughly the point of the decision. *(How
  the 3.3.5 talent frame renders a third-tree overflow at 99 points in phase 3: worth a look on the
  night, not worth blocking on.)*

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

#### Does LevelScaling eat your 2×?

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
AiPlayerbot.RandomBotMaps = 0,1             # phase 1; add 530, then 571. Outland is
                                            # OPEN in phase 1 — this is about where
                                            # level-capped bots have any business,
                                            # not about what is reachable
AiPlayerbot.DisableDeathKnightLogin = 0     # upstream default; no longer a phase key.
                                            # DK bots self-clamp to [55, cap] — §2
AiPlayerbot.LimitTalentsExpansion   = 0     # keep full WotLK trees, per the brief,
                                            # and they have 71 points to spend — §3

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

`charsPerAccount` comes from `RandomPlayerbotFactory::CalculateAvailableCharsPerAccount()`:

```cpp
bool noDK = sPlayerbotAIConfig.disableDeathKnightLogin || sWorld->getIntConfig(CONFIG_EXPANSION) != EXPANSION_WRATH_OF_THE_LICH_KING;
uint32 availableChars = noDK ? 9 : 10;
```

**It is 10 here, in every phase** — one per class — because `Expansion = 2` and
`DisableDeathKnightLogin = 0` both hold from phase 1. (An earlier draft of this page had it at 9 in
phases 1 and 2; that arithmetic is stale.) Skewing
`RandomBotAllianceRatio`/`RandomBotHordeRatio` away from 50/50 reduces it. So for the config
above, on a fresh database:

| | accounts | characters |
|---|---|---|
| random bots (`MaxRandomBots = 30`, ÷10) | `ceil(30/10)` = **3** | 30 |
| addclass pool (`AddClassAccountPoolSize = 10`) | **10** | 100 |
| **total built on first boot** | **13** | **130** |

Note which term dominates: the addclass pool, not the bot count. At the upstream defaults (500 bots,
pool 50) it would be ~100 accounts and about a thousand characters — which is the real reason first
boot has a reputation. Dropping the pool from 50 to 10 is most of the saving, and 10 addclass
accounts is still 100 characters to pull a tank, healer or Death Knight from.

What it prints, on the `playerbots` logger, in this order:

```
Creating random bot accounts...
Waiting for 13 accounts loading into database (N queries)...
>> 13 Accounts loaded into database in NNNN ms
Creating random bot characters...
Creating cache for names per gender and race...
Waiting for 130 characters loading into database (N queries)...
>> 130 Characters loaded into database in NNNN ms
>> 13 random bot accounts with 130 characters available     <- server.loading logger; this is "done"
```

Both `Waiting for …` loops just poll the async DB write queue once a second and print nothing in
between, so a long gap after either line is normal, not a stall. The work is MySQL write throughput,
not CPU — if it is slow, that is a database tuning problem ([hosting.md](hosting.md)), and the module
times itself, so the `in NNNN ms` figures tell you exactly where it went. *(Wall-clock on the target
box: measure on the night — the module hands you the number. Minutes rather than seconds is the
right expectation for 130 characters on a small VPS.)*

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

Death Knight bots are the one exception to "created at level 1": `Randomize()` sends any DK below
56 straight to `RandomizeFirst()`, which floors both ends of their level window at
`StartHeroicPlayerLevel`. So they arrive at 55+ and never sit at level 1 for long.

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

### Bot roster composition, settled at first boot

Playerbots create characters through their own path rather than a real client session, so the
question was whether they respect `Expansion` when rolling races and classes. **They do** — from
`RandomPlayerbotFactory::CreateRandomBot`:

```cpp
// skip disabled with config races
if ((1 << (race - 1)) & sWorld->getIntConfig(CONFIG_CHARACTER_CREATING_DISABLED_RACEMASK))
    continue;
...
if (IsValidRaceClassCombination(race, cls, sWorld->getIntConfig(CONFIG_EXPANSION)))
    raceOptions.push_back(race);
```

and `IsValidRaceClassCombination` is the same two-line expansion test the core uses:

```cpp
if (expansion < EXPANSION_THE_BURNING_CRUSADE && (race == RACE_BLOODELF || race == RACE_DRAENEI))
    return false;
if (expansion < EXPANSION_WRATH_OF_THE_LICH_KING && cls == CLASS_DEATH_KNIGHT)
    return false;
```

**At `Expansion = 2` all three tests pass, so the first-boot roster rolls Blood Elves, Draenei and
Death Knights alongside everything else.** The class loop a few lines up applies
`CONFIG_CHARACTER_CREATING_DISABLED_CLASSMASK` the same way, and both masks are `0`.

This used to be a caveat and is now the reason the decision is cheap. **Bot characters are created
once, on first boot**, against whatever `Expansion` was in force then, and races are chosen at
creation and never re-rolled. Under the old strict design that was a permanent defect: a roster
built at `Expansion = 0` would still have no Blood Elves in phase 3, because the per-account loop
is bounded by `cls < MAX_CLASSES - count` and an account already holding a full set is skipped —
and the only fix was `AiPlayerbot.DeleteRandomBotAccounts`, which costs every bot's level and gear.

With `Expansion = 2` from the first boot there is nothing to fix. The roster is built complete and
stays correct across both flips. Still worth eyeballing once, after first boot rather than after
each flip, from `/srv/wow/wowserver/deploy`:

```bash
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_characters \
  -e "SELECT race, class, COUNT(*) FROM characters GROUP BY race, class;"
```

Expect races 10 (Blood Elf) and 11 (Draenei) present, and class 6 (Death Knight) present. If any of
those three is missing, the server booted once with a lower `Expansion` and the roster is stuck
that way — that is the one scenario where `DeleteRandomBotAccounts` is the right answer, and it is
cheapest on day one.

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
| `MaxPlayerLevel < 55` | known AzerothCore crash — and `StartHeroicPlayerLevel = 55` fails its `<= MaxPlayerLevel` validator below it |
| **Move `Expansion` at all** | it is `2` in every phase. Lowering it clamps every session to the lower value while `account.expansion` stays high and stale, and you cannot repair an account from in-game while the config is low — [§1](#going-backwards) |
| **Set `CharacterCreating.Disabled.RaceMask` / `.ClassMask`** | both stay at their upstream `0`. `1536` and `32` appear in older drafts of this page and would silently re-close Blood Elf, Draenei and Death Knight — [§1](#everything-that-moves-in-one-table) |
| **Run a per-phase `UPDATE account SET expansion`** | there is no per-phase account SQL any more. `UPDATE account SET expansion = 0` would lock every account, bots included, out of two thirds of the game — [§1](#accountexpansion--the-one-time-setup-step) |
| Boot the realm once with `Expansion` below 2 | every account and every bot character created on that boot is stamped low and stuck; the bot roster in particular can only be fixed by wiping it — [§5](#bot-roster-composition-settled-at-first-boot) |
| Ship phase 1 or 2 without `mod-rdf-expansion` | RDF still works, but it hands a level-59 an Outland dungeon — §2 |
| `AiPlayerbot.LimitTalentsExpansion = 1` | clamps bot talent trees below the players' — contradicts "full WotLK trees throughout", and a bot with 71 points and 6 rows has nowhere to put them |
| Set `Rate.Reputation.LowLevel.Kill` / `.LowLevel.Quest` to 10 | they multiply on top of `Rate.Reputation.Gain` — that is 100× on grey-level content, not 10× — [§3](#reputation--ratereputationgain--10) |
| Set `Rate.Drop.Item.GroupAmount` / `.ReferencedAmount` to 3 | those multiply loot *counts*, not chances. Tripling every boss's loot pile is a far bigger change than "3× loot" — [§3](#loot--3-and-be-honest-about-what-that-means) |
| Lower `Rate.Talent` after people have spent points | the budget shrinks, the spent points don't — everyone needs `.reset talents` — [§3](#talents--ratetalent--14) |
| Tune `StatModifier.*` before `InflectionPoint` | a second multiplier on top of the curve; makes the curve impossible to reason about |
| `AutoBalance.LevelScaling.Method = "fixed"` | flattens trash and bosses to one level; `dynamic` is strictly better here |
| Stack `mod-individual-xp` rates carelessly | it multiplies *on top of* `Rate.XP.*` — `.xp set 2` on a 2× server is 4× |
| Assume NPCBots would work instead | they don't count toward AutoBalance's player count — [../README.md](../README.md) |
| Install `mod-solo-lfg` and leave `SoloLFG.FixedXP = 1` | its default pins **every instance and raid kill** to `FixedXPRate = 0.2`, replacing the group split, under your 2× — net `0.4×`. `RewardScaling.XP = 0` does not save you. Set `SoloLFG.FixedXP = 0` — [§3](#who-owns-dungeon-xp) |
| Let more than one system scale dungeon XP | `Rate.XP.*` owns it. `AutoBalance.RewardScaling.XP` and `SoloLFG.FixedXP` both default to *on* and both silently reprice it; `mod-individual-xp` multiplies on top whenever someone has set a rate — [§3](#who-owns-dungeon-xp) |
| Lower `MaxPlayerLevel` below a live character's level | no de-levelling; the character is frozen *and* gets extrapolated stats from `BuildPlayerLevelInfo` instead of the real table — [§1](#going-backwards) |
| Expect `.reload config` to flip a phase | `MaxPlayerLevel` and `Expansion` are `Reloadable::No`; the console says so and the flip half-applies — [§1](#everything-that-moves-in-one-table) |
