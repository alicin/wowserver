# `conf/` — how configuration works on this server

Everything the worldserver and authserver read at runtime, in a form you can `git diff`.

These files are **bind-mounted into the containers**, per
[bring-up.md §4.3](../docs/bring-up.md) and the compose file in
[bring-up.md §5](../docs/bring-up.md):

```yaml
worldserver:
  volumes:
    - ../conf/worldserver.conf:/opt/ac/etc/worldserver.conf:ro
    - ../conf/modules:/opt/ac/etc/modules:ro
authserver:
  volumes:
    - ../conf/authserver.conf:/opt/ac/etc/authserver.conf:ro
```

Pinned versions everything here was verified against:

| | |
|---|---|
| core | `mod-playerbots/azerothcore-wotlk` @ `092e9ba6ff8dc6d861dddd1f31baa9d404381a85` |
| modules | the 18 SHAs in [`build/modules.txt`](../docs/modules.md#61-buildmodulestxt) |

---

## The design decision, and the evidence for it

### Question 1 — does AzerothCore support environment-variable overrides?

**Yes, and the mangling rule in [bring-up.md §4.2](../docs/bring-up.md) is correct.** Verified in
the pinned core's `src/common/Configuration/Config.cpp`, not from a blog:

```cpp
std::string GetEnvVarName(std::string const& configName)
{
    return "AC_" + IniKeyToEnvVarKey(configName);
}
```

`IniKeyToEnvVarKey` upper-cases and inserts `_` at: `.`, `-`, space, a lower→upper case boundary,
and a letter↔digit boundary in either direction. The comment block above it gives upstream's own
examples — `SomeConfig` → `SOME_CONFIG`, `myNestedConfig.opt1` → `MY_NESTED_CONFIG_OPT_1`,
`LogDB.Opt.ClearTime` → `LOG_DB_OPT_CLEAR_TIME`.

The override is checked **before** the file, inside `GetValueDefault`, so it wins over any value
here, and it works for keys that appear in no file at all — including module keys, because module
configs are parsed into the same `_configOptions` map.

### Question 2 — so why are these files not just environment variables?

Because three things make env-only impossible or worse, in descending order of severity:

1. **`Appender.*` and `Logger.*` cannot come from the environment.** `Log::ReadAppendersFromConfig`
   and `ReadLoggersFromConfig` enumerate them with `sConfigMgr->GetKeysByString("Appender." / "Logger.")`,
   which reads the parsed **file** map. A key only enters that map when some code path asks for it
   by name, and nothing asks for `Logger.playerbots` by name — it is discovered by prefix. With no
   `Logger.root`, the core prints *"Wrong Loggers configuration. Review your Logger config section."*
   and falls back to a bare console logger: no `Errors.log`, no `Playerbots.log`, no `sql.updates`
   stream. That alone settles it.
2. **`deploy/.env` is gitignored.** Putting gameplay in it means the running configuration is not
   in the repository, which is the opposite of the requirement that everything be reproducible from
   the repo alone.
3. **`scripts/phase.sh` is specified to rewrite conf files** by key regex
   ([server-config.md §1](../docs/server-config.md#scriptsphasesh--spec)), and the phase flip is a
   restart either way.

So: **environment variables are used for exactly the things that must not be committed or that the
image owns — the four `*DatabaseInfo` strings, `DataDir`/`LogsDir`/`SourceDirectory`, and
`AC_UPDATES_ENABLE_DATABASES` — and everything else lives here.** That is already what the compose
file in bring-up.md §5 does; nothing in this directory changes it.

### Question 3 — why are these files not full copies of the `.conf.dist`?

bring-up.md §4.3 says to seed each file from the `.dist` in the image and commit the result. This
tree does something narrower: **it commits only the keys we deliberately set**, and lets everything
else fall through to the compiled-in default. A 4,966-line `worldserver.conf` drifts from the pinned
core the moment the pin moves, and no human can diff it.

That is only safe if `.conf.dist` values equal compiled-in defaults. **For the core, they do**, and
that was checked rather than assumed: all 494 `SetConfigValue<>` defaults were extracted from
`src/server/game/World/WorldConfig.cpp` at the pin and diffed against the 594 keys in
`worldserver.conf.dist`. Zero real differences. The only ten apparent ones are symbolic constants
(`SEC_CONSOLE` = 4, `SEC_ADMINISTRATOR` = 3, `SEC_MODERATOR` = 1, `HOUR` = 3600,
`REALM_ZONE_DEVELOPMENT` = 1, `GUILD_BANKLOG_MAX_RECORDS` = 25, `GUILD_EVENTLOG_MAX_RECORDS` = 100).

**For modules it is not universally true**, so the same diff was run per module against each one's
source at its pinned SHA. Nine keys ship a value the code does not default to. All nine are carried
explicitly, each with a comment saying why:

| File | Key | `.dist` | code default |
|---|---|---|---|
| `mod_ahbot.conf` | the 120 `AuctionHouseBot.ListProportion.Category*.Quality*` | real proportions | **`0`** |
| `mod_ahbot.conf` | `AuctionHouseBot.DisabledInvalidItemIDs` | ~1200 item IDs | `""` |
| `mod_ahbot.conf` | `AuctionHouseBot.DisabledRecipeProducedItemClassSubClasses` | `2:*,4:*,15:2,15:5` | `""` |
| `mod_ahbot.conf` | `AuctionHouseBot.ListProportion.ListMultipliedItemIDs` | a long list | `""` |
| `mod_ahbot.conf` | `AuctionHouseBot.ItemsPerCycle` | `150` | `75` |
| `AutoBalance.conf` | `AutoBalance.MinHPModifier` | `0.01` | `0.1` |
| `AutoBalance.conf` | `AutoBalance.LevelScaling.DynamicLevel.PerInstance` | `229 -1 -1 1, 230 0 0` | `""` |
| `AutoBalance.conf` | `AutoBalance.LevelScaling.DynamicLevel.DistanceCheck.PerInstance` | `189 500` | `""` |
| `AutoBalance.conf` | `AutoBalance.reward.enable` | `0` | **`1`** |
| `MultiBotBridge.conf` | `MultiBotBridge.EnableConsoleLogs` | `0` | `1` |
| `npc_enchanter.conf` | `Enchanter.EmoteSpell` | `0` | `44940` |
| `instance-reset.conf` | `instanceReset.NormalModeOnly` | `false` | `1` |
| `transmog.conf` | `Transmogrification.PetSpellId` | `200100` | `2000100` |

The `ListProportion` row is why **`mod_ahbot.conf` is the one full copy of a `.conf.dist` in this
tree**. Those keys are read as `GetOption<uint32>(key.c_str(), 0)` — omit them and every listing
proportion is zero and the seller posts nothing, silently, forever. That file is a market model,
not a set of defaults.

Keys whose `.dist` line is **empty** (most of AutoBalance's `StatModifier*`/`InflectionPointRaid*M`
family) are equivalent to omission either way: the empty string fails `Acore::StringTo<T>` and the
code default is used.

### What this costs

`worldserver` will log a `Missing property X in config file, add "X = ..." to this file or define
'AC_X' as an environment variable` **warning for every key it asks for that is not here** — roughly
500 lines at each boot. That is the price of the small file, and it is deliberate:

- It is a **warning**, not an error. `ConfigPolicy::missingOptionSeverity` is `ConfigSeverity::Warn`
  (`Config.h`), and the compiled default is used.
- **Do not silence it** with `AC_CONFIG_POLICY=missing_option=skip`, even though the core supports
  that string. Those warnings are the only runtime signal that a key we *think* we set is actually
  reaching the code. Use the offline checker below instead.

---

## Four rules for editing anything in here

### 1. Never put a comment on the same line as a value

`ConfigMgr::ParseFile` splits on the **first** `=`, trims both sides, strips every `"`, and stops.
There is no inline-comment handling anywhere in the parser.

```ini
MaxPlayerLevel = 60   # PHASE     <-- value is the string "60   # PHASE"
```

`Acore::StringTo<uint32>` requires the whole string to be consumed (`res.ptr == end`), so that
fails, and you get an `Error`-level log plus **the compiled-in default, 80**. Upstream's own
`AutoBalance.conf.dist` has exactly this bug on `AutoBalance.LevelScaling.EndGameBoost`; it is
harmless there only because the key is inert.

This is the single reason the `# PHASE` marker is on its **own line above** the key rather than
trailing it. `scripts/phase.sh` must never write a trailing comment onto a value line.

### 2. A key that does not exist is ignored in total silence

The core warns about keys the *code* asks for and cannot find. It never warns about a key sitting
in a file that no code reads: `AddKey`'s *"Found incorrect option"* path is gated on `isOptional`,
which is `false` for both app configs and module configs, so it can never fire. A typo, a
`master`-only key, a key from a different module — all silently do nothing.

**Verify every new key against the pinned `.conf.dist` before you add it.** The one-liner is at the
bottom of this file.

### 3. Per-phase keys carry a `# PHASE` marker line

Nine keys across five files. The marker sits immediately above its key and carries all three phase
values, so a script needs no table of its own:

```ini
# PHASE  MaxPlayerLevel  p1=60  p2=70  p3=80
MaxPlayerLevel = 60
```

```bash
grep -rn --include='*.conf' -A1 '^# PHASE' conf/
```

| File | Key | P1 | P2 | P3 |
|---|---|---|---|---|
| `worldserver.conf` | `MaxPlayerLevel` | `60` | `70` | `80` |
| `modules/playerbots.conf` | `AiPlayerbot.RandomBotMaxLevel` | `60` | `70` | `80` |
| `modules/playerbots.conf` | `AiPlayerbot.RandomBotMaps` | `0,1` | `0,1,530` | `0,1,530,571` |
| `modules/playerbots.conf` | `AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel` | `60` | `70` | `80` |
| `modules/mod-rdf-expansion.conf` | `RDF.Expansion` | `0` | `1` | `2` |
| `modules/mod_ahbot.conf` | `AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel` | `60` | `70` | `80` |
| `modules/mod_assistant.conf` | `Assistant.Professions.Master.Enabled` | `0` | `1` | `1` |
| `modules/mod_assistant.conf` | `Assistant.Professions.GrandMaster.Enabled` | `0` | `0` | `1` |
| `modules/mod_assistant.conf` | `Assistant.FlightPaths.WrathOfTheLichKing.Enabled` | `0` | `0` | `1` |

That is **nine, not the thirteen in [server-config.md §1](../docs/server-config.md#everything-that-moves-in-one-table)**.
Gating is now level-cap-only, so `Expansion` is `2` in every phase, both
`CharacterCreating.Disabled.*` masks are `0` in every phase,
`AiPlayerbot.DisableDeathKnightLogin` is `0` in every phase, and the
`UPDATE account SET expansion` statement becomes a one-time setup step rather than a per-flip one
(accounts are stamped with `CONFIG_EXPANSION` at creation, so with `Expansion = 2` from first boot
every account and every bot is born at 2).

**A phase flip is still always a restart.** `MaxPlayerLevel` is registered
`ConfigValueCache::Reloadable::No`; `.reload config` refuses it and says so.

### 4. One `.conf` per pinned module that ships a `.conf.dist` — no exceptions

`conf/modules` is bind-mounted **as a directory**, so it *shadows* `/opt/ac/etc/modules` in the
image. A module whose `.conf` is not in this repo does not get a partial config — it gets **no**
config, and every one of its keys falls back to its compiled-in default. `LoadModulesConfigs` logs
the miss at `Error` severity and boots anyway.

There are 17 files here, one for each of the 18 modules in `build/modules.txt` that ships a config.
`noisiver/mod-junk-to-gold` is the exception: its `conf/` holds only `conf.sh.dist` and it has no
runtime keys.

**Adding a module to `build/modules.txt` means adding a file here in the same commit.**

---

## Checking your work

### Are all my keys real? (the important one)

Extract the key names the way `ConfigMgr` does and diff them against the pinned `.conf.dist`.
Anything only in the left column is a key the server will silently ignore:

```bash
# key extractor matching ConfigMgr::ParseFile: trim; skip blank / '#' / '['; split on first '=';
# trim; strip every double quote.
acore_keys() {
  awk '{ l=$0; sub(/^[ \t\r]+/,"",l); sub(/[ \t\r]+$/,"",l)
         if (l=="") next; c=substr(l,1,1); if (c=="#"||c=="[") next
         p=index(l,"="); if (p==0) next
         k=substr(l,1,p-1); sub(/[ \t]+$/,"",k); print k }' "$1" | sort -u
}

# pull the image's shipped .dist tree out once (docker create does not run the entrypoint)
IMG=ghcr.io/<owner>/wowserver:<sha>
CID=$(docker create "$IMG"); docker cp "$CID:/opt/ac/etc/." ./conf-dist/; docker rm "$CID" >/dev/null

comm -23 <(acore_keys conf/worldserver.conf) <(acore_keys conf-dist/worldserver.conf.dist)
comm -23 <(acore_keys conf/authserver.conf)  <(acore_keys conf-dist/authserver.conf.dist)
for f in conf/modules/*.conf; do
  comm -23 <(acore_keys "$f") <(acore_keys "conf-dist/modules/$(basename "$f").dist") \
    | sed "s|^|$(basename "$f"): |"
done
```

### Did I leave an inline comment on a value line?

```bash
grep -rn --include='*.conf' -E '^[[:space:]]*[A-Za-z0-9_.]+[[:space:]]*=.*#' conf/
```

It currently prints nothing, and it should stay that way. The `# PHASE` **marker lines** are
comments starting in column 1, so they correctly do not match. Anything this prints is a broken
setting.

### Is there one conf per pinned module?

```bash
# should print nothing
comm -3 \
  <(awk '!/^#/ && NF {print $1}' build/modules.txt | sed 's|.*/||' | sort) \
  <(printf '%s\n' mod-playerbots mod-autobalance mod-solo-lfg mod-rdf-expansion mod-ah-bot-plus \
      mod-npc-enchanter mod-npc-free-professions mod-assistant mod-aoe-loot mod-junk-to-gold \
      mod-multibot-bridge mod-reset-raid-cooldowns mod-instance-reset mod-transmog \
      mod-learn-spells mod-individual-xp mod-player-bot-level-brackets mod-quest-loot-party | sort)
```

`conf/modules/*.conf` filenames are **not** the module names — they are whatever the module's
`conf/*.conf.dist` is called, because `modules/CMakeLists.txt` globs that filename, strips `.dist`,
and compiles the result into `CONFIG_FILE_LIST`. Hence `mod-ah-bot-plus` → `mod_ahbot.conf`,
`mod-learn-spells` → `mod_learnspells.conf`, `mod-instance-reset` → `instance-reset.conf`.

### Did the server actually load what I wrote?

At boot, on the console:

```bash
docker compose logs worldserver | grep -iE "Missing property|Bad value defined|incorrect option|Empty file|Failed open"
docker compose logs worldserver | grep -A20 "Using modules configuration:"   # should list all 17
docker compose logs worldserver | grep "Using DataDir"                       # /azerothcore/data/
```

`Bad value defined for name '<key>', going to use '<default>' instead` is the line an inline
comment produces. Treat any occurrence as a broken setting, not as noise.

---

## What lives where

| File | Sets | Owns |
|---|---|---|
| `worldserver.conf` | 75 keys | rates (XP 2x, reputation 10x, loot 3x, talents ×1.4), the level cap, `Expansion = 2`, SOAP, paths, 4-vCPU/8 GB tuning, the logging block |
| `authserver.conf` | 13 keys | bind, port, logging, `Updates.EnableDatabases = 0` |
| `modules/playerbots.conf` | 48 keys | 30 bots sized for 8 GB, the bot level window, the CPU levers |
| `modules/AutoBalance.conf` | 33 keys | the difficulty curve, and `RewardScaling.XP = 0` |
| `modules/SoloLfg.conf` | 4 keys | `SoloLFG.FixedXP = 0` — see that file before touching it |
| `modules/mod_ahbot.conf` | 448 keys | the whole economy model; the only full `.dist` copy |
| the other eleven | 1–7 keys each | one job apiece, documented in the file |

Four systems can price XP and exactly one is allowed to: `Rate.XP.*` in `worldserver.conf`. The
other three are neutralised in `AutoBalance.conf` (`RewardScaling.XP = 0`), `SoloLfg.conf`
(`FixedXP = 0`) and `individual_xp.conf` (`DefaultXPRate = 1`), and each of those files carries a
back-reference. If dungeon XP ever feels wrong, check those three before anything else — none of
the modules mentions XP in its login banner, so there is no in-game symptom to follow back.
