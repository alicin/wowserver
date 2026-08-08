# Bring-up — from a built image to three friends logged in

The other four docs describe a server. None of them starts one. This is the runbook that
gets you from "the CI build went green" to "we cleared a dungeon", in order, once.

Read it once end to end before running step 1. Several failures here cost 15–40 minutes
each to discover, because they surface *after* the world database import rather than before it.

- Infrastructure, image build, networking, MySQL tuning, backups: [hosting.md](hosting.md)
- Phase flips and every gameplay rate: [server-config.md](server-config.md)
- Which modules and how they are pinned: [modules.md](modules.md)
- Client, realmlist syntax, addons: [client.md](client.md)
- Decisions and rationale: [../README.md](../README.md)

Config keys, log strings, command syntax and exit codes below were read out of
`mod-playerbots/azerothcore-wotlk` @ `Playerbot` and `mod-playerbots/mod-playerbots` @ `master`
on **2026-08-07**. Where a default is quoted it is verbatim from upstream. Anything I could not
confirm is marked **(verify)**.

---

## 1. Prerequisites

Four things must exist before step 2. The first three are covered elsewhere; the fourth is the
one that bites.

| Thing | Where it comes from |
|---|---|
| A host | [hosting.md §2](hosting.md#2-host-comparison) — Hetzner CX33, or k3v1n over Tailscale for the first weeks |
| A built image in GHCR | [hosting.md §3](hosting.md#3-build-and-deploy-topology) |
| Client data extracted on the host | [hosting.md §4](hosting.md#4-client-data) — `wowgaming/client-data` v20.0 unzipped to `/srv/wow/data` |
| Swap, docker, Tailscale, firewall | [hosting.md §5](hosting.md#5-networking) and [§7.1](hosting.md#71-swap) |

Everything below assumes these paths on the host. They are the same in every doc, and cron
entries in [hosting.md §7](hosting.md#7-ops) call them by absolute path:

| Path | What |
|---|---|
| `/srv/wow/wowserver` | **this repo, cloned on the VPS.** Not `$HOME`, not `/opt` |
| `/srv/wow/wowserver/deploy` | the Compose project directory. Every `docker compose` command below runs from here, and it is what cron `cd`s into |
| `/srv/wow/wowserver/scripts` | `bootstrap.sh`, `phase.sh`, `backup.sh`, `restore.sh` |
| `/srv/wow/data` | client data — outside the repo: 3 GB, not versionable |
| `/srv/wow/backups` | dumps — outside the repo, for the same reason |

The checkout location is load-bearing rather than taste. `deploy/docker-compose.yml` bind-mounts
`../conf` ([§5](#5-deploydocker-composeyml)), so the compose file and the conf files it serves
have to sit in the same working tree; clone the repo somewhere else and every relative mount in
it points at nothing.

### 1.1 What the image must actually contain

The runtime stage needs more than the two binaries. AzerothCore's database bootstrap is not
implemented in C++ — it **shells out to the MySQL command-line client** and feeds it `.sql`
files off disk. Both of those have to be inside the container.

| # | Requirement | Why, and what happens without it |
|---|---|---|
| 1 | `worldserver` and `authserver` | — |
| 2 | A `mysql` CLI binary on `PATH` | `DBUpdater<T>::Populate()` and `::Update()` both call `DBUpdaterUtil::CheckExecutable()` first. Missing, you get `Didn't find any executable MySQL binary at '...' or in path, correct the path in the *.conf ("MySQLExecutable")` and the boot aborts. AzerothCore's own runtime image installs `default-mysql-client` for exactly this. |
| 3 | The SQL source tree — `data/sql/**` plus every module's `data/sql/**` | `GetBaseFilesDirectory()` resolves under `SourceDirectory`. Missing, you get `>> Directory "..." not exist` and the boot aborts. AC's own db-import image copies the whole `data` and `modules` directories in. |
| 4 | Every module's `*.conf.dist` under `etc/modules/` | The install step puts them there; see [§4](#4-how-conf-files-reach-the-container) for why a `.dist` file alone is not enough. |
| 5 | An `ENTRYPOINT` that dispatches on `$ACORE_COMPONENT` | One image, two daemons. The compose file in [§5](#5-deploydocker-composeyml) sets `ACORE_COMPONENT: worldserver` / `authserver` and deliberately sets **no** `command:`. The entrypoint must `exec` the binary rather than fork it, or Docker watches the wrapper instead of the server: the exit-code protocol in [§5](#5-deploydocker-composeyml) (`0` shutdown / `1` error / `2` restart) stops reaching `restart: on-failure`, and SIGTERM stops reaching `World::StopNow()`. The script is [hosting.md §3](hosting.md#3-build-and-deploy-topology)'s to write. |

`MySQLExecutable` defaults to `""`, and `CheckExecutable()` falls back to searching `PATH` for
`mysql`. So requirement 2 is satisfied by installing a client package — you do not need to set
the key. Requirement 3 does need a key, because the built-in default is the CMake source path
from build time (`/src` in a multi-stage build), which does not exist in the runtime stage:

```ini
# worldserver.conf — point the updater at wherever the image copied the SQL tree
SourceDirectory = "/opt/ac/src"
```

**Check these against the Dockerfile in [hosting.md §3.4](hosting.md#34-glibc--abi) before you
build.** That Dockerfile's runtime stage copies only `/opt/ac`, so items 2, 3 and 5 need adding
there. Two related notes for whoever edits it, so they are not rediscovered here:

- The CMake switch for the tools is **`TOOLS_BUILD`**, taking `all` / `none` / `maps-only` /
  `db-only` — there is no `TOOLS` variable, so `-DTOOLS=0` is silently ignored.
- The `dbimport` binary lives in `src/tools/dbimport`, i.e. it is a *tool*, gated by
  `TOOLS_BUILD`, not an app. You do not need it — see [§2.4](#24-do-not-copy-azerothcores-own-compose-topology).

Verify a candidate image before you trust it:

```bash
IMG=ghcr.io/<you>/wowserver:<sha>
docker run --rm --entrypoint sh "$IMG" -c '
  command -v mysql        || echo "MISSING: mysql client"
  ls /opt/ac/bin/worldserver /opt/ac/bin/authserver >/dev/null || echo "MISSING: binaries"
  ls -d /opt/ac/src/data/sql/base/db_world >/dev/null 2>&1 || echo "MISSING: world SQL tree"
  ls -d /opt/ac/src/modules/*/ >/dev/null 2>&1 || echo "MISSING: module SQL trees"
  ls /opt/ac/etc/modules/*.conf.dist 2>/dev/null | wc -l
'

# Requirement 5, which --entrypoint would hide: the image must carry an entrypoint and no CMD
# that overrides it. Expect the entrypoint script and `cmd=null`.
docker inspect -f 'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}}' "$IMG"
```

Both SQL checks are load-bearing, and the second one is the one people leave out. A runtime stage
that copied `data/` but not `modules/` passes the `db_world` line above, populates the three core
schemas happily, and then dies partway through the module migrations — every module's SQL lives
under `modules/*/data/sql/**`, which is row 3's "plus every module's `data/sql/**`" and is a
separate `COPY`.

### 1.2 Verify the client data before first boot, not during it

The worldserver checks for map files **after** it has imported and migrated the databases. On a
cold box that is 15–30 minutes of work followed by `exit(1)`. Two minutes of checking now saves
that round trip:

```bash
cd /srv/wow/data
ls -d maps vmaps mmaps dbc                 # all four must exist
ls dbc/*.dbc   | wc -l                     # expect 248
ls maps/*.map  | wc -l                     # expect 5745
ls vmaps/      | wc -l                     # expect 12495
ls mmaps/      | wc -l                     # expect 3781
du -sh .                                   # expect ~3.0 GiB
```

Counts are from the v20.0 measurement in [hosting.md §1.1](hosting.md#11-disk).

---

## 2. The four databases

This is the largest gap between the plan and a running server. mod-playerbots adds a **fourth
schema** on top of AzerothCore's standard three, with its own connection key, its own update
switch, and its own bootstrap path — and none of the three is where you would guess.

| Database | Connection key | Lives in | Upstream default |
|---|---|---|---|
| `acore_auth` | `LoginDatabaseInfo` | `authserver.conf` **and** `worldserver.conf` | `"127.0.0.1;3306;acore;acore;acore_auth"` |
| `acore_characters` | `CharacterDatabaseInfo` | `worldserver.conf` | `"127.0.0.1;3306;acore;acore;acore_characters"` |
| `acore_world` | `WorldDatabaseInfo` | `worldserver.conf` | `"127.0.0.1;3306;acore;acore;acore_world"` |
| `acore_playerbots` | `PlayerbotsDatabaseInfo` | **`playerbots.conf`**, not `worldserver.conf` | `"127.0.0.1;3306;acore;acore;acore_playerbots"` |

`acore_auth` appears twice on purpose: both daemons connect to it independently. The format is
`"hostname;port;username;password;database"` in all four cases.

### 2.1 The update flag is not a fourth bit

The obvious guess — that `Updates.EnableDatabases` grows a bit for the fourth database — is
wrong, and setting it to `15` accomplishes nothing. The mask in `worldserver.conf` has exactly
three flags:

```ini
#    Updates.EnableDatabases
#        Description: A mask that describes which databases should be updated.
#        Note:        Following flags are available
#                     DATABASE_LOGIN     = 1, Auth database
#                     DATABASE_CHARACTER = 2, Character database
#                     DATABASE_WORLD     = 4, World database
#        Default:     7 - (All enabled)

Updates.EnableDatabases = 7
```

`DatabaseLoader::DATABASE_PLAYERBOTS = 8` does exist, but only inside `#ifdef MOD_PLAYERBOTS`,
and it is never read from that key. The module builds a **second, separate** `DatabaseLoader`
and ORs the flag in programmatically (`src/Script/Playerbots.cpp`):

```cpp
bool OnDatabasesLoading() override
{
    DatabaseLoader playerbotLoader("server.playerbots");
    playerbotLoader.SetUpdateFlags(sConfigMgr->GetOption<bool>("Playerbots.Updates.EnableDatabases", true)
                                       ? DatabaseLoader::DATABASE_PLAYERBOTS
                                       : 0);
    playerbotLoader.AddDatabase(PlayerbotsDatabase, "Playerbots");

    return playerbotLoader.Load();
}
```

So the switch you want is a **boolean in `playerbots.conf`**:

```ini
Playerbots.Updates.EnableDatabases = 1     # default; 0 disables playerbots DB setup + migrations
```

**Leave `Updates.EnableDatabases = 7` in `worldserver.conf`.** Two consequences of the code
above that are worth knowing:

- Because `SetUpdateFlags` ORs rather than assigns, the playerbots loader still applies its
  migrations even if you set `Updates.EnableDatabases = 0`. The two switches are independent.
- Conversely, `Playerbots.Updates.EnableDatabases = 0` leaves the fourth database unmigrated
  while the other three are fine — a state that looks like a module bug and is not.

> **Typo warning.** The comment block above the setting in `playerbots.conf.dist` calls it
> `Playerbot.Updates.EnableDatabases` (singular). The setting line and the source both use
> `Playerbots.` (plural). Copy the setting line, not the comment.

### 2.2 What is automatic and what is not

| Step | Automatic? | Mechanism |
|---|---|---|
| `CREATE DATABASE` for a missing schema | Yes, conditionally | `DBUpdater<T>::Create()` fires on `ER_BAD_DB_ERROR`, but only when `Updates.AutoSetup = 1` **and** updates are enabled for that pool **and** the configured MySQL user holds `CREATE` |
| Creating the MySQL user and granting it | **No** | Nothing in the core does this |
| Populating an empty schema from `data/sql/base/**` | Yes | `DBUpdater<T>::Populate()`, on `SHOW TABLES` returning nothing |
| Applying `data/sql/updates/**` and module SQL | Yes | `DBUpdater<T>::Update()` |
| Creating `acore_playerbots` specifically | Yes, but **only from `worldserver`** | see [§2.4](#24-do-not-copy-azerothcores-own-compose-topology) |
| Setting `realmlist.address` | **No** | [hosting.md §5.2](hosting.md#52-the-realmlist-gotcha--the-one-everybody-gets-wrong) owns that SQL; you run it at [§7.3](#73-the-other-row-to-set-before-you-hand-out-passwords--realmlistaddress) |

AzerothCore ships `data/sql/create/create_mysql.sql`, and it is **not sufficient here** for two
independent reasons:

```sql
-- what upstream ships: three databases, and a localhost-only user
CREATE USER 'acore'@'localhost' IDENTIFIED BY 'acore' ...;
CREATE DATABASE IF NOT EXISTS `acore_world`      DEFAULT CHARACTER SET UTF8MB4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `acore_characters` DEFAULT CHARACTER SET UTF8MB4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `acore_auth`       DEFAULT CHARACTER SET UTF8MB4 COLLATE utf8mb4_unicode_ci;
```

1. There is no `acore_playerbots`. The module ships table definitions under
   `data/sql/playerbots/base/` but no schema-creation script.
2. `'acore'@'localhost'` is wrong in Docker. Connections arrive from another container's IP, so
   the grant must be on `'acore'@'%'`.

Do it explicitly instead, as two files in `deploy/mysql-init/` — the directory mounted into the
MySQL container's `/docker-entrypoint-initdb.d/` (see [§5](#5-deploydocker-composeyml)). The
committed artefact is **`01-databases.sql.template`**, below. The file MySQL actually runs is
`01-databases.sql`, generated from it by the `envsubst` one-liner in [§6](#6-first-boot) and
gitignored.

```sql
-- deploy/mysql-init/01-databases.sql.template   (committed)
--   -> deploy/mysql-init/01-databases.sql       (generated in section 6, gitignored)
-- Runs once, on first initialisation of an empty MySQL data directory.

CREATE DATABASE IF NOT EXISTS `acore_auth`       DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `acore_characters` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `acore_world`      DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `acore_playerbots` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- '%' not 'localhost': the servers connect from another container.
CREATE USER IF NOT EXISTS 'acore'@'%' IDENTIFIED BY '${ACORE_DB_PASSWORD}';

GRANT ALL PRIVILEGES ON `acore_auth`       . * TO 'acore'@'%';
GRANT ALL PRIVILEGES ON `acore_characters` . * TO 'acore'@'%';
GRANT ALL PRIVILEGES ON `acore_world`      . * TO 'acore'@'%';
GRANT ALL PRIVILEGES ON `acore_playerbots` . * TO 'acore'@'%';

FLUSH PRIVILEGES;
```

**MySQL's init directory does not expand `${...}`.** The entrypoint pipes each file straight into
the `mysql` client, so an unsubstituted copy would set the `acore` password to the literal string
`${ACORE_DB_PASSWORD}`. That is what the template is for; substitute it before the first `up`,
[§6](#6-first-boot) step 1. The `.template` suffix is also what keeps the committed copy inert
while it sits in the mounted directory: `docker_process_init_files` runs `*.sh`, `*.sql`,
`*.sql.bz2`, `*.sql.gz`, `*.sql.xz` and `*.sql.zst`, and for anything else logs
`ignoring /docker-entrypoint-initdb.d/01-databases.sql.template` and moves on.

Do not commit the real password. Three files in `deploy/` hold it and all three are gitignored:
`.env`, the generated `mysql-init/01-databases.sql`, and `mysql-backup.cnf`
([§5](#5-deploydocker-composeyml)). What is committed is the `.template` and
`.env.example` ([§5.1](#51-deployenvexample)); see the layout in [../README.md](../README.md).

Creating the four schemas up front means `DBUpdater::Create()` never has to run, which removes a
dependency on the `acore` user holding `CREATE` and removes the interactive prompt described
next.

### 2.3 The interactive prompt that hangs first boot

When a database *is* missing, `DBUpdater<T>::Create()` does this before creating it:

```cpp
LOG_WARN("sql.updates", "Database \"{}\" does not exist", pool.GetConnectionInfo()->database);

char const* disableInteractive = std::getenv("AC_DISABLE_INTERACTIVE");

if (!sConfigMgr->isDryRun() && (disableInteractive == nullptr || std::strcmp(disableInteractive, "1") != 0))
{
    std::cout << "Do you want to create it? [yes (default) / no]:" << std::endl;
    std::string answer;
    std::getline(std::cin, answer);
    ...
}
```

The container needs `stdin_open` and `tty` for the admin console ([§5](#5-deploydocker-composeyml)).
That same tty means `std::getline` **blocks forever** on this prompt with nobody attached. The
symptom is a worldserver that starts, prints `Database "acore_playerbots" does not exist`, and
then does nothing at all — no crash, no restart, no progress.

Set `AC_DISABLE_INTERACTIVE=1` in the environment. AzerothCore's own images do, with the
comment *"This disables user prompts. The console is still active, however"* — the `AC>` console
keeps working, only the blocking prompts are skipped.

### 2.4 Do not copy AzerothCore's own compose topology

Upstream's `docker-compose.yml` runs a one-shot `ac-db-import` container and sets
`AC_UPDATES_ENABLE_DATABASES=0` on both servers, so migrations happen exactly once in a
dedicated place. That is a good design and it **does not work on this fork**, because
`dbimport` registers three databases and never invokes the module script hook
(`src/tools/dbimport/Main.cpp`):

```cpp
loader
    .AddDatabase(LoginDatabase, "Login")
    .AddDatabase(CharacterDatabase, "Character")
    .AddDatabase(WorldDatabase, "World");
```

There is no `AddDatabase(PlayerbotsDatabase, ...)` and no `sScriptMgr->OnDatabasesLoading()`.
`acore_playerbots` is created, populated and migrated **only by `worldserver`**, via the
module's `PlayerbotsDatabaseScript`. Run the upstream topology and the fourth schema stays
empty; worldserver then fails on the first prepared statement against it.

So: **worldserver owns all four migrations.** Which in turn settles the authserver:

- `authserver.conf` ships `Updates.EnableDatabases = 1` — meaning it will also try to migrate
  `acore_auth`. Two processes racing the same migration on first boot is avoidable, so set
  authserver's to `0` and let worldserver own it.
- With updates disabled, authserver will **not** auto-create `acore_auth` (the auto-create path
  requires updates to be enabled for that pool). It therefore has to start after worldserver has
  done the work. That is what the `depends_on: service_healthy` in [§5](#5-deploydocker-composeyml)
  is for, and it costs nothing — nobody can log in during the first-boot import anyway.

MySQL connection-count budgeting across four pools is in
[hosting.md §6.2](hosting.md#62-8-gb-box-cx33--do-48). Backups deliberately skip `acore_world`
and include `acore_playerbots`; see [hosting.md §7.3](hosting.md#73-backups).

---

## 3. DataDir

`DataDir` is the single key that connects the worldserver to the 3 GB of client data mounted in
[hosting.md §4](hosting.md#4-client-data). Nothing sets it for you, and its default is useless
in a container.

```ini
#    DataDir
#        Description: Data directory setting.
#        Important:   DataDir needs to be quoted, as the string might contain space characters.
#        Example:     "@prefix@\home\youruser\azerothcore\data"
#        Default:     "."
```

`"."` means "the worldserver process's current working directory". The hosting plan puts the
data at `/srv/wow/data` on the host. Left alone, the server looks somewhere else entirely and
dies.

```ini
# worldserver.conf
DataDir = "/azerothcore/data"
```

with `/srv/wow/data` bind-mounted to `/azerothcore/data` in the container. A trailing slash is
optional — the core appends one if absent.

### 3.1 Expected layout

```
/azerothcore/data/          <- DataDir
├── dbc/          248 files, 0.08 GiB    static client tables
├── maps/        5745 files, 0.27 GiB    terrain
├── vmaps/      12495 files, 0.61 GiB    line-of-sight and height
├── mmaps/       3781 files, 2.04 GiB    pathfinding
└── Cameras/       15 files, <1 MiB      cinematic camera paths
```

`Cameras/` comes out of the `wowgaming/client-data` zip but I found no server-side reference to
it in the core tree — it appears to be extractor output kept for completeness rather than
something `worldserver` reads. **(verify)** Harmless either way; leave it.

### 3.2 What the failure looks like

There are four distinct messages, and knowing which one you got tells you what is wrong. All
four call `exit(1)`.

| Log line | Meaning |
|---|---|
| `Incorrect DataDir value in worldserver.conf or ALL required *.dbc files (N) not found by path: <DataDir>dbc` | `DataDir` is wrong, or the mount is missing entirely. The message prints the path it tried — read it. |
| `Some required *.dbc files (X from N) not found or not compatible:` followed by a list | `DataDir` is right, the extraction is incomplete. Re-unzip. |
| `You have _outdated_ DBC data. Please extract correct versions from current using client.` | Wrong client-data version for a 3.3.5a core. Pin the release tag. |
| `Failed to find map files for starting areas` | `dbc/` is fine but `maps/` or `vmaps/` is missing or partial. |

Confirm the value actually took effect — the core logs it on every boot, before any of the
above:

```
Using DataDir /azerothcore/data/
```

Two things make this worse than it sounds, and are the reason for the pre-flight check in
[§1.2](#12-verify-the-client-data-before-first-boot-not-during-it):

- **The map check runs late.** It sits in `World::SetInitialWorldSettings()`, after the database
  import. On a cold box you wait 15–30 minutes to find out.
- **`exit(1)` is the crash code.** Under `restart: on-failure` Docker will restart it, and you
  get a loop that re-runs the import every time. See
  [§10](#10-common-first-boot-failures).

One nicety: the Outland map assertions are skipped while `Expansion = 0`, so a phase-1 server
boots even with map 530 data missing. It will fail the moment you flip to phase 2 — another
reason to verify the full extraction now rather than per phase.

`DataDir` cannot be changed by `.reload config`; the core logs
`DataDir option can't be changed at worldserver.conf reload, using current value (...)` and
keeps the old one. Changing it means a restart.

---

## 4. How conf files reach the container

### 4.1 The `.conf.dist` rule, and the half of it that catches everyone

The build installs **`.dist` files only**. `CopyApplicationConfig` installs
`worldserver.conf.dist` and `authserver.conf.dist` into `etc/`; `CopyModuleConfig` installs each
module's `*.conf.dist` into `etc/modules/`. Nothing installs a `.conf`.

What the server then *reads* is the un-suffixed name. For modules the list is baked in at
compile time — `modules/CMakeLists.txt` globs `conf/*.conf.dist`, strips `.dist`, and compiles
the result into `CONFIG_FILE_LIST`:

```cmake
file(GLOB MODULE_CONFIG_LIST RELATIVE ${MODULE_CONFIG_PATH} ${MODULE_CONFIG_PATH}/*.conf.dist)
foreach(configFileName ${MODULE_CONFIG_LIST})
  CopyModuleConfig("${MODULE_CONFIG_PATH}/${configFileName}")
  string(REGEX REPLACE "\.dist$" "" configFileName ${configFileName})
  set(CONFIG_LIST ${CONFIG_LIST}${configFileName},)
endforeach()
```

So the worldserver looks for `etc/modules/playerbots.conf`, `etc/modules/AutoBalance.conf` and
so on. **AzerothCore's own entrypoint renames the application conf and not the module confs:**

```bash
cp -rnv /azerothcore/env/ref/etc/* "$CONF_DIR"     # seed, never overwrite

CONF="$CONF_DIR/$ACORE_COMPONENT.conf"
CONF_DIST="$CONF_DIR/$ACORE_COMPONENT.conf.dist"
if [[ -f "$CONF_DIST" ]]; then cp -vn "$CONF_DIST" "$CONF"; else touch "$CONF"; fi
```

`$ACORE_COMPONENT` is `worldserver` or `authserver`. Module `.conf.dist` files land in the
directory and are never renamed.

**This is a silent failure, not a loud one.** A missing module conf does not stop the boot —
`LoadModulesConfigs` logs the miss and returns success, and every `AiPlayerbot.*` key falls back
to its compiled-in default. The observable symptom is the server ignoring your tuning: you set
`AiPlayerbot.MaxRandomBots = 30` and get the upstream 500, which on an 8 GB box is the
difference between a working server and a swap-thrashing one. Every value in
[server-config.md](server-config.md) depends on this file being named `.conf`.

### 4.2 Environment variables override any key

Every config key has an environment-variable twin. `ConfigMgr` builds the name as `AC_` plus the
key in upper snake case, splitting on `.`, `-`, space, case boundaries and letter/digit
boundaries:

```
SomeConfig          => AC_SOME_CONFIG
myNestedConfig.opt1 => AC_MY_NESTED_CONFIG_OPT_1
LogDB.Opt.ClearTime => AC_LOG_DB_OPT_CLEAR_TIME
```

Applied to the keys that matter here:

| Config key | Environment variable |
|---|---|
| `DataDir` | `AC_DATA_DIR` |
| `LogsDir` | `AC_LOGS_DIR` |
| `RealmID` | `AC_REALM_ID` |
| `LoginDatabaseInfo` | `AC_LOGIN_DATABASE_INFO` |
| `WorldDatabaseInfo` | `AC_WORLD_DATABASE_INFO` |
| `CharacterDatabaseInfo` | `AC_CHARACTER_DATABASE_INFO` |
| `PlayerbotsDatabaseInfo` | `AC_PLAYERBOTS_DATABASE_INFO` |
| `SourceDirectory` | `AC_SOURCE_DIRECTORY` |
| `Updates.EnableDatabases` | `AC_UPDATES_ENABLE_DATABASES` |
| `Playerbots.Updates.EnableDatabases` | `AC_PLAYERBOTS_UPDATES_ENABLE_DATABASES` |

The override applies even to keys absent from the file, so it works for module keys too.
`MySQLExecutable` mangles to something unusable (`AC_MY_SQLEXECUTABLE`) — leave it at `""` and
rely on the `PATH` search instead.

### 4.3 Three ways to get the files in, and the one to pick

| Approach | Phase flip costs | Reproducible | Problem |
|---|---|---|---|
| Baked into the image | a CI rebuild and a repull | fully | 40-minute turnaround to change `MaxPlayerLevel`. Secrets end up in a registry layer. |
| Named volume, seeded by an entrypoint | edit inside the volume | no | The `cp -n` seeding means the volume shadows the image forever: add a module and its new `.conf.dist` never appears, because the directory is already populated. The volume, not the repo, becomes the source of truth. |
| **Bind-mount `conf/` from the repo** | edit the file, restart | yes, the repo is the truth | You must handle `.conf.dist` → `.conf` yourself, and the restart is not optional. |

**Take the bind mount.** It is the only option where `scripts/phase.sh` rewriting a repo file is
the whole change, and where `git diff` on the host tells you what the running server is
configured with. Concretely:

```
wowserver/
└── conf/
    ├── worldserver.conf          <- .conf, not .conf.dist. Committed.
    ├── authserver.conf
    └── modules/
        ├── playerbots.conf
        ├── AutoBalance.conf
        └── ...
```

Seed each one once, from the `.dist` inside the image, then commit it and edit the copy. **Drive
the module loop off what is actually in the image, never off a hand-written list of module
names** — the reason is two paragraphs down:

```bash
IMG=ghcr.io/<you>/wowserver:<sha>
mkdir -p conf/modules conf-dist

# One container, copy the whole etc/ out of it. `docker create` does not run the entrypoint.
CID=$(docker create "$IMG")
docker cp "$CID:/opt/ac/etc/." ./conf-dist/
docker rm "$CID" >/dev/null

cp conf-dist/worldserver.conf.dist conf/worldserver.conf
cp conf-dist/authserver.conf.dist  conf/authserver.conf

# EVERY module conf the image ships, whatever it is called.
for dist in conf-dist/modules/*.conf.dist; do
  cp "$dist" "conf/modules/$(basename "$dist" .dist)"
done

# These two must be equal. If they are not, a module is running on compiled-in defaults.
ls conf-dist/modules/*.conf.dist | wc -l
ls conf/modules/*.conf          | wc -l
rm -rf conf-dist
```

Cross-check the result against the module list in
[modules.md §6.1](modules.md#61-buildmodulestxt) — one `.conf` per pinned module that ships one.
A hand-maintained list of two or three "the ones I care about" is how the next paragraph happens.

**The one that will bite is `conf/modules/SoloLfg.conf`.** Left unseeded, `SoloLFG.FixedXP` keeps
its compiled-in default of `1`, which pins *every* instance and raid kill to `FixedXPRate = 0.2`
— under `Rate.XP.Kill = 1.5` that is a flat **0.3× base XP for grouped dungeon kills**, the exact
inverse of the "1.5× at full rate regardless of group size" decision this whole doc set exists to
deliver. It is silent, and it only shows up when you are in a party, so a solo test will not find
it: see [server-config.md § Who owns dungeon XP](server-config.md#who-owns-dungeon-xp) for the
full ownership table and [§9](#9-smoke-test) step 12 for the test that does catch it.

**Seeded is not configured — do the edits now, before the first boot.** A freshly seeded tree is
upstream defaults in a new filename; nothing above changes a single value. Apply
[server-config.md's phase-1 block](server-config.md#phase-1--classic-cap-60) and the
[AutoBalance](server-config.md#4-autobalance-tuning),
[playerbots](server-config.md#5-playerbots-tuning-for-a-3-person-server) and
[SoloLFG](server-config.md#the-second-gotcha-mod-solo-lfg-pins-dungeon-xp-to-02) values it
prescribes, commit the result, *then* [§6](#6-first-boot). Those numbers live there; the only
thing this file adds is *when*. Two of them are not retrofittable in practice —
`AiPlayerbot.AddClassAccountPoolSize` is baked into the bot roster on first boot
([§8](#8-first-boot-bot-population)) and `Expansion` is stamped into every account and bot at
creation time ([§7.1](#71-creating-them)).

Re-seed deliberately when you bump a module pin — upstream adds keys, and a stale copy silently
uses compiled-in defaults for anything new. `diff` the new `.dist` against your `.conf` rather
than overwriting. Adding a module means re-running the loop above, not editing it.

### 4.4 What `docker compose up -d` does and does not pick up

This trips people because it looks like it should work.

`docker compose up -d` recreates a container only when something *Compose can see* changed — the
image, environment, ports, mount definitions, labels. Editing the **contents** of a
bind-mounted file changes none of those. Compose prints `up-to-date` and does nothing, and the
worldserver keeps running with the config it read at startup.

So `scripts/phase.sh` edits the file, and the file is live inside the container immediately —
but the process does not re-read it. You need one of:

```bash
# graceful, players get a countdown, characters are saved  (preferred)
#   .server shutdown 300   via console or SOAP  -- hosting.md 7.2
#   exit code 0, `restart: on-failure` leaves it down, then:
docker compose up -d

# no players online
docker compose restart worldserver

# a few keys only, no restart: AutoBalance re-reads, worldserver rates do not.
#   DataDir explicitly refuses to change on reload.
.reload config
```

The first is the sequence [hosting.md §7.2](hosting.md#72-graceful-restarts) prescribes for
phase flips, and it works precisely *because* the shutdown exits the process: `up -d` then finds
no container and starts a fresh one, which re-reads the bind-mounted conf. That subtlety is the
whole reason the ordering in [server-config.md §1](server-config.md#flip-procedure) is
shutdown-then-`up -d` and not `up -d` on its own.

---

## 5. `deploy/docker-compose.yml`

Every other doc points at this file. Here it is.

```yaml
# deploy/docker-compose.yml
#
# Three services. worldserver owns ALL FOUR database migrations (docs/bring-up.md 2.4),
# so authserver waits for it and runs with updates disabled.
#
# Values referenced as ${...} come from deploy/.env (gitignored; see .env.example, 5.1).

name: wowserver

services:

  mysql:
    image: mysql:8.4
    restart: unless-stopped            # no exit-code protocol here; see the note below
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?set MYSQL_ROOT_PASSWORD in .env}
    volumes:
      - mysql-data:/var/lib/mysql
      - ./mysql-init:/docker-entrypoint-initdb.d:ro   # runs ONCE, on an empty data dir
      - ./mysql.cnf:/etc/mysql/conf.d/wow.cnf:ro      # tuning: hosting.md 6.2
      # Root credentials as a 0600 option file, so they never appear on a command
      # line -- container processes are visible in `ps` on the host. Generated from
      # deploy/.env by scripts/backup.sh, gitignored, used by backup/restore
      # (hosting.md 7.3, 7.4) and by 6.2 below. It must EXIST before the first
      # `up`: a bind-mount source that does not exist makes Docker create a
      # *directory* at that path, and then mysqldump reads a directory.
      - ./mysql-backup.cnf:/etc/mysql/backup.cnf:ro
    healthcheck:
      # No credentials, on purpose. `mysqladmin ping` is answered before
      # authentication -- MySQL documents the exit status as "0 even in case of an
      # error such as Access denied, because this means that the server is running
      # but refused the connection". -h 127.0.0.1 forces TCP, so this only passes
      # once the socket the game servers use is actually accepting connections;
      # the temporary server the mysql entrypoint runs during initdb is
      # --skip-networking and correctly reads as unhealthy.
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1"]
      interval: 5s
      timeout: 5s
      retries: 40
      start_period: 60s
    oom_score_adj: -500                # hosting.md 7.5: never let the OOM killer pick mysqld
    networks: [wow]

  worldserver:
    image: ghcr.io/${GHCR_OWNER}/wowserver:${IMAGE_TAG:?pin a SHA, not latest}
    depends_on:
      mysql:
        condition: service_healthy

    # ---- THE RESTART POLICY. Read this before changing it. ----
    # AzerothCore exit codes (World.h, ShutdownExitCode):
    #     0 SHUTDOWN_EXIT_CODE  -> .server shutdown / .server exit / SIGTERM
    #     1 ERROR_EXIT_CODE     -> crash, bad config, missing maps/dbc
    #     2 RESTART_EXIT_CODE   -> .server restart / .server idlerestart
    # `always` and `unless-stopped` restart on 0 too, so `.server shutdown 300`
    # counts down, saves, exits, and Docker instantly brings it back. The server
    # appears to ignore shutdown commands. It is the policy, not a bug.
    restart: on-failure

    # Must exceed the longest `.server shutdown <delay>` you use, or `docker compose
    # stop` SIGKILLs mid-save. SIGTERM is handled: it calls World::StopNow(0), a
    # clean save-and-exit. The default grace period is 10 seconds.
    stop_grace_period: 6m

    # There is no worldserver-cli binary. The ONLY interactive console is this
    # process's stdin, reached with `docker attach`. Detach with Ctrl-P Ctrl-Q --
    # Ctrl-C sends SIGINT and shuts the server down.
    stdin_open: true
    tty: true

    environment:
      # WHICH DAEMON THIS IS. One image, two services. The image's ENTRYPOINT
      # dispatches on this and execs
      #     /opt/ac/bin/$ACORE_COMPONENT -c /opt/ac/etc/$ACORE_COMPONENT.conf
      # There is deliberately NO `command:` on either service. See 1.1 row 5.
      ACORE_COMPONENT: worldserver

      # Skips DBUpdater's blocking "Do you want to create it? [yes (default)/no]"
      # prompt. With a tty allocated and nobody attached, that prompt hangs forever.
      # The AC> console still works.
      AC_DISABLE_INTERACTIVE: "1"

      # Connection strings live here, not in the committed conf files.
      # "host;port;user;password;database"
      AC_LOGIN_DATABASE_INFO:      "mysql;3306;acore;${ACORE_DB_PASSWORD};acore_auth"
      AC_CHARACTER_DATABASE_INFO:  "mysql;3306;acore;${ACORE_DB_PASSWORD};acore_characters"
      AC_WORLD_DATABASE_INFO:      "mysql;3306;acore;${ACORE_DB_PASSWORD};acore_world"
      AC_PLAYERBOTS_DATABASE_INFO: "mysql;3306;acore;${ACORE_DB_PASSWORD};acore_playerbots"

      AC_DATA_DIR:         "/azerothcore/data"
      AC_LOGS_DIR:         "/azerothcore/logs"
      AC_SOURCE_DIRECTORY: "/opt/ac/src"    # where the image keeps data/sql/** (1.1)

    volumes:
      - ../conf/worldserver.conf:/opt/ac/etc/worldserver.conf:ro
      - ../conf/modules:/opt/ac/etc/modules:ro   # .conf, NOT .conf.dist -- see 4.1
      - /srv/wow/data:/azerothcore/data:ro       # 3 GB client data, hosting.md 4
      - wow-logs:/azerothcore/logs

    ports:
      # Bind to the tailnet address only. hosting.md 5.1.
      - "${TAILSCALE_IP}:8085:8085"
      - "127.0.0.1:7878:7878"                    # SOAP, loopback only. hosting.md 7.2

    healthcheck:
      # /proc/net/tcp needs no extra packages; 1F95 is 8085 in hex. `ss` and `nc`
      # are not present in debian-slim. hosting.md 7.5.
      test: ["CMD-SHELL", "grep -q ':1F95 ' /proc/net/tcp || exit 1"]
      interval: 60s
      timeout: 5s
      retries: 3
      # First boot = world DB import PLUS playerbot population (section 8). Both
      # happen before the listener opens. Too short and the container restart-loops
      # through the import forever.
      start_period: 40m

    oom_score_adj: 200
    networks: [wow]

  authserver:
    image: ghcr.io/${GHCR_OWNER}/wowserver:${IMAGE_TAG}
    depends_on:
      worldserver:
        # worldserver creates and migrates acore_auth; authserver cannot (2.4).
        # On first boot this waits out the whole import, which is correct --
        # nobody can log in during it anyway.
        condition: service_healthy
    restart: on-failure
    stop_grace_period: 30s
    environment:
      ACORE_COMPONENT: authserver        # same image, other binary. No `command:`. 1.1 row 5.
      AC_DISABLE_INTERACTIVE: "1"
      AC_UPDATES_ENABLE_DATABASES: "0"   # worldserver owns migrations. 2.4.
      AC_LOGIN_DATABASE_INFO: "mysql;3306;acore;${ACORE_DB_PASSWORD};acore_auth"
      AC_LOGS_DIR: "/azerothcore/logs"
    volumes:
      - ../conf/authserver.conf:/opt/ac/etc/authserver.conf:ro
      - wow-logs:/azerothcore/logs
    ports:
      - "${TAILSCALE_IP}:3724:3724"
    networks: [wow]

volumes:
  mysql-data:
  wow-logs:

networks:
  wow:
```

Notes on the choices that are not obvious:

- **`restart: on-failure` on the game servers, `unless-stopped` on MySQL.** The policy has to
  match the process's exit-code protocol. AzerothCore has one (0/1/2 above), so `on-failure`
  gives you exactly the three behaviours you want: exit 0 stays down because you meant it, exit
  2 comes back because `.server restart` meant that too, exit 1 comes back as crash recovery.
  `mysqld` has no such protocol, so the plain "keep it up" policy is right there.
- **`stop_grace_period: 6m` against a 300-second shutdown.** The margin covers the final
  character-save flush after the countdown ends.
- **`stdin_open` + `tty` together.** `tty` alone gives no writable stdin; `stdin_open` alone
  gives no console. You need both, and then you need `AC_DISABLE_INTERACTIVE=1` so the tty does
  not become a place the boot can block.
- **`ACORE_COMPONENT` and no `command:`.** The two game services differ by exactly one
  environment variable; everything else about the image is shared. Resist adding a `command:` to
  "make it explicit" — Compose's `command` replaces the image's `CMD`, and the entrypoint builds
  its own argv from `$ACORE_COMPONENT`, so at best yours is ignored and at worst it lands on the
  end of the `exec`. If a service ever starts the wrong daemon, that variable is the first thing
  to look at.
- **No credentials in any `test:` or `command:` array.** Compose bakes those into the container
  config verbatim, so they show in `docker inspect`, in `ps` on the host, and in the compose file
  itself if it is ever committed. `mysqladmin ping` needs none; everything that does need them
  reads `/etc/mysql/backup.cnf`. [hosting.md §7.3](hosting.md#73-backups) argues this at length.
  Dropping the credentials does not weaken `depends_on: service_healthy`: the MySQL entrypoint
  runs `docker-entrypoint-initdb.d` against a temporary `--skip-networking` server, so the moment
  a TCP ping succeeds, `01-databases.sql` has already run.
- **No `db-import` service.** [§2.4](#24-do-not-copy-azerothcores-own-compose-topology).
- MySQL tuning (`mysql.cnf`), backups, and the health/OOM rationale are
  [hosting.md §6](hosting.md#6-mysql-tuning-on-a-shared-8-gb-box) and
  [§7](hosting.md#7-ops); the file above only mounts them.

**One-time check on MySQL 8.4:** its default authentication plugin is `caching_sha2_password`,
and `mysql_native_password` is no longer built in. The client library the core links against
(MariaDB Connector/C, per [hosting.md §3.4](hosting.md#34-glibc--abi)) supports
`caching_sha2_password`, so this should be fine — but it is the one thing in this file I have
not seen run. If the servers report an authentication-plugin error against `acore`, pin
`mysql:8.0` instead. **(verify)**

### 5.1 `deploy/.env.example`

The compose file above needs exactly five variables. `.env` itself is gitignored — it holds both
passwords — so this is the committed copy, and it is what [§6](#6-first-boot) copies from:

```bash
# deploy/.env.example -- copy to deploy/.env, fill in, chmod 600. See docs/bring-up.md 6.
#
# TWO parsers read this file: Compose's own .env reader, and `sh`, when scripts/backup.sh
# and section 6's one-liners do `. ./.env`. They agree only on plain KEY=value -- no quotes,
# no `export`, no spaces around `=`, no shell expansions. A value Compose takes literally
# but `sh` re-expands is a password mismatch you will debug as "access denied".
#
# Generate BOTH passwords from [A-Za-z0-9] only, and this whole class of problem is gone:
#     LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32; echo
# `#` starts a comment mid-line inside a MySQL option file, so it would truncate
# MYSQL_ROOT_PASSWORD where it is written to mysql-backup.cnf (hosting.md 7.3), and
# backslashes are still read as escapes there even when quoted. `;` is the field separator
# in AC's "host;port;user;password;database" strings (section 2), so it would split
# ACORE_DB_PASSWORD in half.

MYSQL_ROOT_PASSWORD=
ACORE_DB_PASSWORD=
GHCR_OWNER=
IMAGE_TAG=
TAILSCALE_IP=
```

| Variable | Value, and what an empty one does |
|---|---|
| `MYSQL_ROOT_PASSWORD` | Generated. `${VAR:?}`-guarded: empty and `docker compose` refuses to run at all, printing the message |
| `ACORE_DB_PASSWORD` | Generated. Must be the value `01-databases.sql` granted with — it is read twice from here, once by `envsubst` into that file and once into the four connection strings ([§6](#6-first-boot)) |
| `GHCR_OWNER` | The GitHub user or org the image was pushed under. Empty gives `ghcr.io//wowserver:...`, an invalid reference |
| `IMAGE_TAG` | The image SHA, never `latest` ([hosting.md §3.6](hosting.md#36-deploy)). `${VAR:?}`-guarded |
| `TAILSCALE_IP` | `tailscale ip -4` on the VPS ([hosting.md §5.1](hosting.md#51-tailscale-recommended)). **Not guarded, and it fails silently**: empty, `"${TAILSCALE_IP}:8085:8085"` becomes `":8085:8085"`, which Compose accepts as a publish with no host IP — i.e. every interface, not the tailnet |

---

## 6. First boot

Three files have to exist before the first `up`, and none of them is in the repo. Two of them are
generated from the third.

```bash
cd /srv/wow/wowserver/deploy

# 0. deploy/.env. Both one-liners below source it, as does scripts/backup.sh.
cp -n .env.example .env
chmod 600 .env
#    ...now fill in the five values -- 5.1. Then, and only then, the two generated files:

# 1. The MySQL init SQL. 01-databases.sql.template is committed with a literal
#    ${ACORE_DB_PASSWORD}, and MySQL's init directory does not expand it (2.2).
#    envsubst is /usr/bin/envsubst, from `gettext-base` on Debian/Ubuntu. A minimal install
#    does not have it and bootstrap.sh does not install it: apt-get install -y gettext-base.
#    The SHELL-FORMAT argument is not decoration. Given none, envsubst substitutes EVERY
#    $VAR reference in the input; given one, "only those environment variables that are
#    referenced in SHELL-FORMAT are substituted". Single-quote it so the shell leaves it be.
#    And no `umask 077` on this one, unlike its two neighbours: the MySQL entrypoint re-execs
#    itself as the unprivileged `mysql` user (`exec gosu mysql`) before it reads
#    /docker-entrypoint-initdb.d, so a root-owned 0600 file is one it cannot read.
( set -a; . ./.env; set +a
  envsubst '${ACORE_DB_PASSWORD}' \
    < mysql-init/01-databases.sql.template > mysql-init/01-databases.sql )

# 2. The mysql service bind-mounts ./mysql-backup.cnf, and Docker creates a DIRECTORY at a
#    bind-mount source that does not exist yet. scripts/backup.sh rewrites this file nightly;
#    write it once by hand now, the same way hosting.md 7.3 does.
( umask 077
  set -a; . ./.env; set +a
  printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" > mysql-backup.cnf )

# 3. Sanity-check both before the point of no return. The first must no longer mention the
#    variable at all; the second must be a file, not a directory.
grep -c 'ACORE_DB_PASSWORD' mysql-init/01-databases.sql   # expect 0
test -f mysql-backup.cnf && echo ok

docker compose pull
docker compose up -d
docker compose logs -f worldserver
```

**Step 1 is the one with no second chance.** `/docker-entrypoint-initdb.d` runs exactly once, on
an empty data directory. Come up without `01-databases.sql` and the `acore` user is never
created, all four pools fail authentication, and adding the file later changes nothing — the
volume is no longer empty, so the init directory is never read again. Recovering means
`docker compose down -v`, which destroys `mysql-data` and buys you the whole 15–30 minute import
a second time.

### 6.1 What happens, in order

Milestones, with the log strings to watch for. Nothing is on the network until the last one.

| Stage | What it does | Log signal |
|---|---|---|
| Open pools | Connects the four pools. Creates any missing schema ([§2.2](#22-what-is-automatic-and-what-is-not)) | `Database "..." does not exist` only if you skipped the init SQL |
| Populate | Imports `data/sql/base/**` into each empty schema. This is the bulk of the wait — `acore_world` is ~4 GB | `Database acore_world is empty, auto populating it...` |
| Update | Applies `data/sql/updates/**` plus every module's SQL, per pool | `Updating acore_world database...` |
| Playerbots pool | The module's separate loader does the same for the fourth schema | `Updating acore_playerbots database...` *(exact string: **verify**)* |
| Config + DBC | Reads `DataDir`, loads the DBC stores | `Using DataDir /azerothcore/data/`, then `>> Initialized N Data Stores in M ms` |
| Map check | Asserts the starting-area map and vmap files exist | silence on success; `Failed to find map files for starting areas` on failure |
| Playerbots init | Config load **and first-boot bot population** — [§8](#8-first-boot-bot-population) | the `AzerothCore Playerbots Module` banner, `Load Playerbots Config...` |
| World ready | | `WORLD: World Initialized In N Minutes M Seconds` |
| Listener up | | `<version> (worldserver-daemon) ready...` and the `AC> ` prompt |

Budget **15–30 minutes** for the import on a CX33, plus the bot population in
[§8](#8-first-boot-bot-population). Subsequent boots skip populate entirely (`Populate()`
returns early once `SHOW TABLES` is non-empty) and take a couple of minutes.

### 6.2 How to know it finished

Three independent signals, cheapest first.

```bash
# 1. the log line, and the console prompt that follows it
docker compose logs worldserver | grep -E 'World Initialized|ready\.\.\.'

# 2. the realm flag. worldserver sets VERSION_MISMATCH while booting and clears it
#    when the world is up; flag 0 means connectable.
#    Credentials come from the mounted 0600 option file, never from argv -- and
#    --defaults-extra-file has to be the FIRST argument (hosting.md 7.3).
docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf -N -B \
  -e "SELECT id, name, flag FROM acore_auth.realmlist;"

# 3. the port is actually listening
docker compose exec -T worldserver grep -c ':1F95 ' /proc/net/tcp
```

The realm-flag lifecycle is worth internalising, because it explains what friends see:

| Moment | What worldserver writes | Client sees |
|---|---|---|
| worldserver starts | clears `OFFLINE`, sets `VERSION_MISMATCH` | realm listed but not joinable |
| world finished loading | clears `VERSION_MISMATCH`, `population = 0` | realm joinable |
| clean shutdown | sets `OFFLINE` | realm listed as offline |

So during the entire first-boot import the realm appears in the list and refuses connections.
That is correct behaviour, not a symptom.

### 6.3 The console

```bash
docker attach wowserver-worldserver-1
# AC>
```

The prompt is literally `AC> `. Detach with **Ctrl-P Ctrl-Q**; Ctrl-C sends SIGINT, which is
handled as `World::StopNow(SHUTDOWN_EXIT_CODE)` — a clean shutdown you did not intend. There is
no separate CLI binary; the alternative is SOAP, set up in
[hosting.md §7.2](hosting.md#72-graceful-restarts).

The console accepts a command with or without the leading dot — `CliHandler::ParseCommands`
strips a leading `.` or `!` if present, commented *"Console allows using commands both with and
without leading indicator"*. Keep typing the dot anyway; it is what you type in-game, and SOAP
([hosting.md §7.2](hosting.md#72-graceful-restarts)) requires it omitted, so having exactly one
place where it is optional is easier than having two conventions.

---

## 7. Accounts

Three friends, three accounts, one of them yours with GM. Do this from the `AC>` console — it
needs no character and no client.

### 7.1 Creating them

```
.account create <username> <password> [email]
```

Verified against `cs_account.cpp` / `AccountMgr::CreateAccount`:

- Email is optional; omitted, it is stored empty.
- **Username *and password* are upper-cased before hashing** (`Utf8ToUpperOnlyLatin` on both).
  Passwords are therefore case-insensitive. Tell your friends, or watch someone spend twenty
  minutes on a capital letter.
- Length caps: username `MAX_ACCOUNT_STR` = 17, password `MAX_PASS_STR` = 16, email
  `MAX_EMAIL_STR` = 255. Over the cap returns an error, it does not truncate.
- The command is `Console::Yes`, so it works from `AC>` and in-game for a GM.

```
AC> .account create ALI hunter2
Account created: ALI
AC> .account create FRIENDTWO somepassword
AC> .account create FRIENDTHREE somepassword
```

**The account's expansion column is stamped at creation time**, from the running
`Expansion` value — `stmt->SetData(3, uint8(sWorld->getIntConfig(CONFIG_EXPANSION)));`. Accounts
made during phase 1 are pinned to Classic until you run the `UPDATE` at every flip. That trap,
and the fix, are [server-config.md §1](server-config.md#the-accountexpansion-trap-read-this-first).
It is the single most likely way to break a phase flip, so read it before phase 2, not during.

### 7.2 GM level

```
.account set gmlevel <account> <level> <realmID>
```

Three arguments when you name an account (with a player selected in-game you can drop the
account name and pass two). `realmID` is **required** in the three-argument form:

| `realmID` | Effect |
|---|---|
| `1` | this realm only — must match `RealmID` in `worldserver.conf` and `realmlist.id` |
| `-1` | all realms; implemented as deleting the per-realm `account_access` rows |
| anything else negative | rejected with an invalid-realm error |

Security tiers, from `AccountTypes` in `Common.h`:

| Value | Name | Use |
|---:|---|---|
| `0` | `SEC_PLAYER` | your two friends |
| `1` | `SEC_MODERATOR` | — |
| `2` | `SEC_GAMEMASTER` | most `.` commands, `.gm on`, `.tele`, `.instance unbind` |
| `3` | `SEC_ADMINISTRATOR` | everything, including `.account set gmlevel` and SOAP |
| `4` | `SEC_CONSOLE` | not assignable — this is what the `AC>` console itself runs as |

You may only grant a level **strictly below your own**, and the target must currently be below
you too. From the console you are `SEC_CONSOLE`, so 3 is the ceiling — which is why the first GM
has to be made from the console rather than in-game.

```
AC> .account set gmlevel ALI 3 -1
```

`-1` here saves re-running it if you ever add a second realm. If you use SOAP for scheduled
restarts ([hosting.md §7.2](hosting.md#72-graceful-restarts)), that account needs level 3.

Leave the friends at `0`. They still get `.ab mapstat` and `.ab creaturestat`, which are
`SEC_PLAYER` ([server-config.md §4](server-config.md#inspection-commands--tune-empirically)),
and `.playerbots bot ...`, which is also `SEC_PLAYER`.

Sanity check before you hand out passwords:

```sql
SELECT a.id, a.username, a.expansion, IFNULL(aa.gmlevel, 0) AS gm, aa.RealmID
FROM acore_auth.account a
LEFT JOIN acore_auth.account_access aa ON aa.id = a.id
WHERE a.username NOT LIKE 'RNDBOT%';
```

The `NOT LIKE 'RNDBOT%'` matters — by the time you run this there will be a dozen or more bot
accounts alongside yours. See next.

### 7.3 The other row to set before you hand out passwords — `realmlist.address`

Not an account, but the same shape of job and the same moment: one row, written once, from the
host. Accounts without it get your friends as far as the realm list and no further.
`realmlist` ships pointing at `127.0.0.1`, nothing in the boot changes it
([§2.2](#22-what-is-automatic-and-what-is-not)), and the failure it produces —
authenticate fine, see the realm, click it, hang at "Logging in to game server" forever — reads
as an auth problem and is not.

[hosting.md §5.2](hosting.md#52-the-realmlist-gotcha--the-one-everybody-gets-wrong) owns this
row and explains why `localAddress` and `localSubnetMask` are deliberately left alone. Its SQL,
verbatim, wrapped in the credentials form used everywhere else in this doc
([§6.2](#62-how-to-know-it-finished)):

```bash
cd /srv/wow/wowserver/deploy
tailscale ip -4                      # -> 100.x.y.z, the address friends' clients dial

docker compose exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth -e "
UPDATE realmlist
SET address   = '100.x.y.z',
    port      = 8085,
    gamebuild = 12340
WHERE id = 1;"
```

No restart. `authserver` re-reads the whole table on a timer — `RealmList::UpdateRealms()`
re-runs `LOGIN_SEL_REALMLIST` and reschedules itself every `RealmsStateUpdateDelay` seconds,
which `authserver.conf.dist` ships at `20`. Wait twenty seconds, then verify with step 3 of
[§9](#9-smoke-test); that step only *checks* this row, so if you skipped this one it will be the
first thing that fails.

---

## 8. First-boot bot population

This is the longest unexplained pause in bring-up, and it is not in any log section anyone
thinks to look at, because it happens **inside** world initialisation rather than after it.

`RandomPlayerbotFactory::CreateRandomBots()` is called from `PlayerbotAIConfig::Initialize()`,
which the module runs from its `OnBeforeWorldInitialized` hook. So all of it happens before
`WORLD: World Initialized In ...` — the world is otherwise idle, nothing is listening, and the
only sign of life is the playerbots log channel.

### 8.1 How much gets built, and why it is not 30

**The arithmetic, the per-phase numbers and the full log transcript are in
[server-config.md § First boot: the bots are built before the server opens](server-config.md#first-boot-the-bots-are-built-before-the-server-opens).**
That file owns the tuning values; this one only needs the runbook consequence, which is:

> With the recommended phase-1 config the server builds **14 accounts and 126 characters**
> before it opens the port — not 30. The dominant term is `AddClassAccountPoolSize`, not
> `MaxRandomBots`.

Two things follow for bring-up specifically:

- **Get `conf/modules/playerbots.conf` right before the first boot**, not after. At the upstream
  defaults (`MaxRandomBots = 500`, `AddClassAccountPoolSize = 50`) this is roughly a thousand
  characters instead of 126. Changing your mind afterwards means the
  `AiPlayerbot.DeleteRandomBotAccounts = 1` cycle, which throws away every bot's level and gear
  — and which deliberately stops the server when it finishes, logging
  `Please reset the AiPlayerbot.DeleteRandomBotAccounts to 0 and restart the server...`.
- **Only the first boot pays it.** Later boots find each account already populated
  (`AccountMgr::GetCharactersCount(accountId) >= 10` skips it) and move straight past. Raising
  either count later re-triggers the build for the shortfall.

### 8.2 How to tell it is done

- `>> N random bot accounts with M characters available` is the completion line.
- `>> Loaded playerbots config in N ms` follows it, and that `N` **includes the whole bot
  creation** — it is your measured first-boot bot cost. Write it down; it is the number that
  should drive `start_period` on the worldserver healthcheck.
- Then the boot continues to `WORLD: World Initialized In ...`.

Both `Waiting for ...` lines in that transcript poll the async write queue once a second and
print nothing in between, so a long silent gap after either one is progress, not a hang. Do not
kill the container.

From SQL, at any point during or after:

```sql
SELECT COUNT(*) FROM acore_auth.account       WHERE username LIKE 'RNDBOT%';
SELECT COUNT(*) FROM acore_characters.characters;
```

**How long in wall-clock.** I have not measured this on a CX33 and will not put a number here
that reads as verified. It is dominated by 126 sequential character builds and their async
saves — minutes, not seconds, and bounded by MySQL write throughput rather than CPU. Time your
own first boot from the `ms` figure above and set the healthcheck from that. **(verify)**

---

## 9. Smoke test

In order. Each step isolates a different layer, so a failure tells you where to look rather than
just that something is wrong.

| # | Do | Expected |
|---:|---|---|
| 1 | `docker compose ps` | all three services `running`, worldserver `healthy` |
| 2 | From a friend's machine: `nc -vz <tailscale-ip> 3724` | connection succeeds — authserver is reachable over the tailnet |
| 3 | `SELECT id, name, address, port, flag, gamebuild FROM acore_auth.realmlist;` | `address` = the Tailscale IP, `port` = 8085, `gamebuild` = 12340, `flag` = 0 |
| 4 | Launch the client with `set realmlist <tailscale-ip>` | realm appears in the list, not greyed out |
| 5 | Log in with a `.account create`d account | character-select screen, no "Unable to connect" |
| 6 | Create a character and enter the world | you spawn; `Using DataDir` in the log was not a lie |
| 7 | `.server info` | uptime, player count, core revision — confirms the command channel works from a client session, not just the console |
| 8 | `.playerbots bot addclass <class>` in-game | a levelled bot of that class joins you |
| 9 | Walk the party into a 5-man | AutoBalance announces itself, see below |
| 10 | Kill one non-elite mob **solo, outdoors** | XP matches the table below |
| 11 | Kill one mob **solo, inside the 5-man** (dismiss the bots) | proves `AutoBalance.RewardScaling.XP = 0`; record the number as `N` |
| 12 | Kill the same mob type **in a party**, inside the 5-man | proves `SoloLFG.FixedXP = 0`. **The only step that can catch that one** |

**Step 9, what AutoBalance actually prints.** On entering a dungeon with
`AutoBalance.PlayerChangeNotify = 1`:

```
[AutoBalance] Welcome to <Map> (5-player Normal). There are 4 player(s) in this instance. Difficulty set to 4 player(s).
```

Two numbers, and they must differ from each other only when someone is excluded. If the counts
look wrong, the usual cause is the next message:

```
[AutoBalance] Your GM flag is turned on. AutoBalance will ignore you. Please turn GM off and
exit/re-enter the instance if you'd like to be considering for AutoBalancing.
```

**GM-flagged players are not counted.** Smoke-testing scaling with `.gm on` gives you a
3-players-plus-a-ghost reading. Turn it off and re-enter — re-entering is required, not
optional. Separately, `AutoBalance.Announce = 1` prints
`This server is running the |cff4CFF00AutoBalance |rmodule.` at login, which is a cheap
confirmation the module loaded at all.

Confirm the bot counted as a player: your friends plus bots should equal the first number.
That is the whole reason Playerbots was chosen over NPCBots
([../README.md](../README.md)) and it is worth verifying once with your own eyes.

**Step 10, confirming the 1.5× actually applied.** The core's XP formula for a same-level,
non-elite kill in 1–60 content reduces to `player_level * 5 + 45`, then multiplied by
`Rate.XP.Kill`:

| Character level | Base | Expected at `Rate.XP.Kill = 1.5` |
|---:|---:|---:|
| 10 | 95 | **142** |
| 20 | 145 | **217** |
| 30 | 195 | **292** |

Solo, no group, no rested bonus, a mob of exactly your level with `ModExperience = 1.0`. Elites
double the base before the rate applies. If you see 95 instead of 142, the conf was not loaded —
go back to [§4.1](#41-the-confdist-rule-and-the-half-of-it-that-catches-everyone).

**Step 11, solo inside the instance.** Same kill, in a scaled dungeon, bots dismissed. Two jobs.
First: if the mob happens to qualify for the table above — same level as you, non-elite,
`ModExperience = 1.0` — the number should match it exactly, because
`AutoBalance.RewardScaling.XP = 0` means AutoBalance weakens the mob without repricing it. Coming
in visibly *under* the table means reward scaling is still on and is eating your rate; the
multiplier it applies tracks the number of bodies in the instance, so there is no single
percentage to quote — the curve is [server-config.md §4](server-config.md#4-autobalance-tuning),
the fix is [§3](server-config.md#the-gotcha-autobalance-silently-eats-your-15). Second, and this
one works for any mob: write the number down as **`N`**. Step 12 is scored as a ratio of `N`,
which cancels out the elite ×2 and whatever `ModExperience` the mob carries.

**Step 12, grouped inside the instance — the one that catches `SoloLFG.FixedXP`.** Steps 10 and
11 *cannot* catch it. `mod-solo-lfg` overwrites the kill rate, and `KillRewarder::_RewardXP`
consumes that rate only inside `if (_group)`, so an ungrouped kill is untouched and both earlier
steps go green with `FixedXP` still at `1`. Invite at least one bot
(`.playerbots bot addclass <class>`), keep everyone at the same level, kill the same mob type:

| Party in the instance | Per-head rate applied to `N` | Per head, if `N` = 217 |
|---|---|---:|
| you alone (step 11) | `1.0` | 217 |
| you + 1 bot | `1.0 / 2` = **0.5** | 108 |
| you + 2 bots | `1.166 / 3` ≈ **0.389** | 84 |
| **any of the above, with `SoloLFG.FixedXP` still `1`** | flat **0.2**, frozen | **43** |

`1.0` and `1.166` are `Acore::XP::xp_in_group_rate(count, false)` — `1.0` for one or two members,
`1.166` for three, `1.3` for four, `1.4` for five or more — and the split is level-weighted
(`_groupRate × yourLevel ÷ sum of alive member levels`), which is why the levels must match for
the numbers above to hold. `217` is the level-20 row of the previous table, used here only as a
worked example.

**The tell needs no arithmetic at all: the per-head number must _move_ when you add or remove a
party member.** `FixedXP = 1` replaces the split with a constant, so it does not. If steps 11 and
12 differ by a factor of five and adding a third body changes nothing, `SoloLfg.conf` was never
seeded and you are on a net `1.5 × 0.2 = 0.3×` in every instance and raid —
[server-config.md § Who owns dungeon XP](server-config.md#who-owns-dungeon-xp) and
[§ the second gotcha](server-config.md#the-second-gotcha-mod-solo-lfg-pins-dungeon-xp-to-02).

Two reading notes: rested XP is reported as a separate `(... bonus)` term in the combat log —
use the base figure — and mobs inside an instance are usually elite and often carry a
`ModExperience` other than `1.0`, which is exactly why step 12 is scored as a ratio of `N` rather
than against the absolute table.

**Confirm a bad result from the log rather than re-killing things.** The worldserver prints, on
every boot, the module confs it actually loaded — not the ones it looked for:

```bash
docker compose logs worldserver | grep -A 30 'Using modules configuration:'
docker compose exec -T worldserver grep -i 'FixedXP' /opt/ac/etc/modules/SoloLfg.conf
```

`ConfigMgr::LoadModulesConfigs()` walks the compiled-in `CONFIG_FILE_LIST` — one entry per module
that ships a conf, baked in at build time
([§4.1](#41-the-confdist-rule-and-the-half-of-it-that-catches-everyone)) — and appends a filename
to the printed list **only if the file was found**. So any module in
[modules.md §6.1](modules.md#61-buildmodulestxt) that is absent from the output is running on
compiled-in defaults, and `SoloLfg.conf` missing from it is exactly the failure above. The bind
mount is why there is no middle ground: `../conf/modules` replaces the whole directory, so the
image's `.conf.dist` files are not even present at runtime — the conf is simply absent,
`LoadModulesConfigs` still returns `true`, and the boot carries on without comment.

Finally, record the bot roster's race spread now. It is cheap, and it is the one thing about
the bot population you cannot re-check meaningfully later — bots are rolled once on first boot
and never re-rolled, so this snapshot is what you are stuck with for the whole of phase 1:

```sql
SELECT race, COUNT(*) FROM acore_characters.characters GROUP BY race;
```

Races 10 (Blood Elf) and 11 (Draenei) should be absent at `Expansion = 0`. They will be —
`RandomPlayerbotFactory` honours both `CONFIG_EXPANSION` and the race mask — so treat a hit here
as a sign that `Expansion` was not actually `0` when the bots were built, not as a module bug.
Details, and why the roster does *not* gain those races at a later phase flip, in
[server-config.md § Bot caveat at Expansion < 2](server-config.md#bot-caveat-at-expansion--2--resolved).

---

## 10. Common first-boot failures

| Symptom | Cause | Fix |
|---|---|---|
| Realm not listed at all | authserver cannot reach `acore_auth`, or is not running | `docker compose logs authserver`. On first boot this is expected until worldserver is healthy — authserver `depends_on` it ([§2.4](#24-do-not-copy-azerothcores-own-compose-topology)) |
| Realm listed but greyed out / not joinable | worldserver still booting: it sets `REALM_FLAG_VERSION_MISMATCH` on start and clears it when the world is up | Wait for `World Initialized`. Confirm with `SELECT flag FROM acore_auth.realmlist` — `0` is up ([§6.2](#62-how-to-know-it-finished)) |
| Realm listed as offline after a clean stop | worldserver sets `REALM_FLAG_OFFLINE` on shutdown | Expected. It clears on next start |
| "Unable to connect" at the login screen | Wrong `realmlist.wtf`, wrong client build, or port 3724 not reachable | [client.md §1](client.md#verifying-you-actually-have-12340) for the build check; step 2 of [§9](#9-smoke-test) for reachability |
| Authenticates, then hangs forever on "Logging in to game server" | `realmlist.address` holds an address the *client* cannot route to — classically `127.0.0.1` | The canonical SQL is [hosting.md §5.2](hosting.md#52-the-realmlist-gotcha--the-one-everybody-gets-wrong). Not an auth problem despite appearances |
| Character list empty on a realm you know has characters | `RealmID` in `worldserver.conf` does not equal `realmlist.id` | Make them match. `LoadRealmInfo()`'s return value is ignored by `main()`, so a mismatched realm ID produces no startup error at all |
| worldserver exits immediately, `Incorrect DataDir value ... not found by path: <path>dbc` | `DataDir` unset or the client-data mount is missing | [§3](#3-datadir). The message prints the path it tried |
| worldserver exits immediately, `Failed to find map files for starting areas` | `dbc/` present but `maps/`/`vmaps/` incomplete | Re-extract; verify counts per [§1.2](#12-verify-the-client-data-before-first-boot-not-during-it) |
| **worldserver restart-loop, re-importing the DB every cycle** | Something exits 1 (missing maps, bad config, unreadable conf) and `restart: on-failure` correctly restarts it — but the restart re-enters a long import, so the loop looks like a hang rather than a crash | `docker compose logs worldserver \| head -100` for the *first* error, not the last. Then `docker compose stop worldserver` before debugging, so you are not racing it |
| **`.server shutdown 300` counts down, saves, and the server comes straight back** | `restart: always` or `unless-stopped`. `.server shutdown` exits 0 and Docker restarts it | `restart: on-failure`. This is the single most-reported non-bug in AzerothCore's tracker ([§5](#5-deploydocker-composeyml)) |
| Boot stops dead after `Database "acore_playerbots" does not exist`, no crash, no progress | `DBUpdater::Create()`'s interactive prompt blocking on the allocated tty | `AC_DISABLE_INTERACTIVE=1` ([§2.3](#23-the-interactive-prompt-that-hangs-first-boot)), and pre-create the schemas ([§2.2](#22-what-is-automatic-and-what-is-not)) |
| `Unknown column`/`Table ... doesn't exist` against a `playerbots_*` table | The fourth schema exists but was never migrated | `Playerbots.Updates.EnableDatabases = 1` in `playerbots.conf` — and check you have not copied upstream's `db-import` topology, which never touches it ([§2.4](#24-do-not-copy-azerothcores-own-compose-topology)) |
| `Didn't find any executable MySQL binary at '...' or in path` | No `mysql` CLI in the runtime image | [§1.1](#11-what-the-image-must-actually-contain) |
| `>> Directory "..." not exist` during populate | `SourceDirectory` points nowhere; the SQL tree was not copied into the runtime stage | [§1.1](#11-what-the-image-must-actually-contain) |
| Server boots fine but ignores your tuning — 500 bots, wrong XP | Module confs are still `.conf.dist`, so every key fell back to its compiled-in default | [§4.1](#41-the-confdist-rule-and-the-half-of-it-that-catches-everyone). Silent by design; `LoadModulesConfigs` does not fail the boot |
| **Outdoor XP is right, dungeon XP is a fifth of it, and it does not change with party size** | `SoloLfg.conf` was never seeded from its `.dist`, so `SoloLFG.FixedXP` is at its compiled-in `1` and pins every instance and raid kill to `0.2` under your `1.5×` | Seed **every** module conf, not a chosen few ([§4.3](#43-three-ways-to-get-the-files-in-and-the-one-to-pick)), then confirm from `Using modules configuration:` in the log ([§9](#9-smoke-test) step 12). Ownership table: [server-config.md § Who owns dungeon XP](server-config.md#who-owns-dungeon-xp) |
| mysqldump/`mysql` in the container reports `/etc/mysql/backup.cnf` is a directory | `deploy/mysql-backup.cnf` did not exist when the stack first came up, so Docker created a directory at the bind-mount source | `docker compose down`, `rmdir` the directory, write the file ([§6](#6-first-boot)), `up -d`. `scripts/backup.sh` keeps it current after that |
| You edited a conf, ran `docker compose up -d`, nothing changed | Compose saw no change it tracks, so it did not recreate the container, so the process never re-read the file | [§4.4](#44-what-docker-compose-up--d-does-and-does-not-pick-up) |
| First boot takes far longer than the 15–30 min you budgeted | The playerbot population is running inside world init | [§8](#8-first-boot-bot-population). Check `AddClassAccountPoolSize` is not still `50` |
| `docker compose stop` kills the server mid-save | Default 10-second grace period | `stop_grace_period` longer than your shutdown delay ([§5](#5-deploydocker-composeyml)) |
| Ctrl-C in an attached console shut the server down | Ctrl-C sends SIGINT, handled as a clean `World::StopNow(0)` | Detach with **Ctrl-P Ctrl-Q** ([§6.3](#63-the-console)) |

When something is wrong and the table does not cover it, the ordering in
[§6.1](#61-what-happens-in-order) is the diagnostic: find the last milestone that appeared and
the first that did not. Every stage between them is a short list.
