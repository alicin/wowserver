# Hosting

Sizing, host choice, build/deploy topology, networking, MySQL, ops.
Decisions and rationale live in [../README.md](../README.md); this is the infrastructure detail.

---

## 1. Sizing math

### 1.1 Disk

Client data measured directly from the `wowgaming/client-data` **v20.0** release
(`Data.zip`, 1,196,168,257 B), by parsing the zip central directory — 22,284 entries:

| Component | Uncompressed | In-zip | Files |
|---|---:|---:|---:|
| `mmaps/` (pathfinding) | 2.04 GiB | 703 MiB | 3,781 |
| `vmaps/` (LOS/height) | 0.61 GiB | 279 MiB | 12,495 |
| `maps/` (terrain) | 0.27 GiB | 147 MiB | 5,745 |
| `dbc/` | 0.08 GiB | 8 MiB | 248 |
| `Cameras/` | <1 MiB | <1 MiB | 15 |
| **Total** | **3.01 GiB** | **1.11 GiB** | **22,284** |

`mmaps` is two thirds of it. If you ever need to claw back 2 GB you can drop mmaps and set
`MoveMaps.Enable = 0` — creature pathing degrades to straight-line movement. Don't; noted only
because it's the one big lever.

Full picture:

| Item | Min | Comfortable | Note |
|---|---:|---:|---|
| OS (Debian/Ubuntu minimal) + docker engine | 3 GB | 4 GB | |
| Client data, extracted | 3.1 GB | 3.1 GB | above |
| `Data.zip` during install | +1.2 GB | +1.2 GB | transient, delete after unzip |
| `acore_world` | 4 GB | 4 GB | *(verify — single third-party source)* |
| `acore_characters` | 0.2 GB | 1 GB | grows; see gotcha below |
| `acore_auth` | <10 MB | <10 MB | |
| `acore_playerbots` | 0.2 GB | 1 GB | 4th DB, playerbots-only |
| Docker images (core + mysql + one old tag) | 3 GB | 5 GB | AC image carries compiled binaries |
| Swapfile | 4 GB | 4 GB | §7 |
| Local backup retention | 1 GB | 5 GB | compressed dumps |
| **Total consumed** | **~20 GB** | **~28 GB** | |

**Gotcha — playerbots are real characters.** Each bot is a `Player` row in `acore_characters`
with inventory, skills, quest log and mail, plus its own state in `acore_playerbots`. 40 bots is
noise; the `RandomBotMinLevel`/`RandomBotMaxLevel` generator creating hundreds is not. This is a
disk axis that a bot-free server simply doesn't have.

**Why 25 GB doesn't fit.** A DO $6 droplet is 25 GB. The table's minimum column is ~20 GB before
your first backup, and the `acore_world` import needs headroom for InnoDB temp files on top.
You'd be provisioning at >80% full on day one, on the axis that fails hardest — MySQL corrupts
rather than degrades when it runs out of disk.

Those are *consumed* figures. Provision above them — MySQL wants free space to breathe:

- **Minimum: 40 GB provisioned.** **Comfortable: 80 GB** (what CX33 gives you anyway).

### 1.2 RAM

Anchor points, sourced rather than guessed:

| Source | Figure |
|---|---|
| AzerothCore wiki, memory usage | 1–5 players → 4 GB; 10 → 6 GB; 100 → 16 GB. "at least 11 GB" once maps are cached |
| AzerothCore wiki | **once a map grid loads, it never unloads until restart** — RSS is monotonic within an uptime |
| mod-playerbots wiki, hardware | "minimal: 16GB (when all map grids are loaded 11-12GB)", "preferable: 32GB or more" |
| IR77 2026 hosting guide | worldserver alone ~2 GB; ~250 bots → 6 GB; ~500 bots → 8 GB; ~1000 bots → 12 GB *(third-party, measured after bots spread out)* |

The two "16 GB" numbers describe **hundreds of bots roaming the whole world**, which drags every
map grid into memory and never lets go. That is not this server.

Budget for 3 friends + ~40 bots parked near the party:

| Process | Min | Comfortable |
|---|---:|---:|
| `worldserver` bare | 2.0 GB | 2.0 GB |
| + ~40 bots | +0.5 GB | +1.0 GB | 
| + grid creep over a week's uptime | +1.0 GB | +2.5 GB |
| `mysqld` (pool + overhead, §6) | 1.4 GB | 2.5 GB |
| `authserver` | 0.05 GB | 0.05 GB |
| OS + docker + sshd + tailscaled | 0.4 GB | 0.6 GB |
| **Total** | **~5.4 GB** | **~8.7 GB** |

The 40-bot delta is **interpolated** from the 2 GB / 250-bot / 500-bot anchors, not measured —
treat it as an estimate. Grid creep is the term that actually decides your restart cadence: because
grids never unload, that row has no ceiling within an uptime, which is why the scheduled restart in
§7.6 is a requirement rather than housekeeping.

- **Minimum: 8 GB** (with swap, and the weekly restart of §7.6). **Comfortable: 16 GB.**

4 GB is a bot-free server. 1 GB does not start `worldserver`.

### 1.3 CPU

AzerothCore's map update is effectively single-threaded per map; `MapUpdate.Threads` parallelises
*across* maps, not within one. Single-core clock matters more than core count. Playerbots wiki
asks 4 cores / 3.0 GHz minimum, 6 cores / 4.4 GHz preferred. 4 shared vCPU is the floor; the bot
AI tick is the thing that will saturate it first.

---

## 2. Host comparison

**Note — two separate Hetzner events, routinely conflated into one.** They are eight months
apart and only the second is a price change:

1. **Line replacement.** The cost-optimized **CX23/33/43/53 were introduced on 16 October 2025**
   (Cloud API changelog, server type IDs 114–117). A companion entry the same day announced that
   the old shared-Intel plans — CX22/32/42/52, themselves only introduced in June 2024 — would be
   **unorderable from 1 January 2026**. Existing servers keep running; you just cannot create
   one. CX33 has the same specs as the CX32 it replaces.
2. **Price rise.** On **15 June 2026, 08:00 CEST** cloud and dedicated prices went up. That
   adjustment is quoted against the *current* line (CX23…, CPX2x, CAX, CCX); it is not what
   retired the CX2x plans.

So a guide quoting "CX32 at €6.80" is naming a plan you can no longer order at a price that no
longer applies — a staleness marker, not a plan to go looking for. Prices below are ex-VAT,
ex-IPv4, Germany/Finland, as of **2026-08-07**.

| Host / plan | vCPU | RAM | Disk | Price/mo | Verdict |
|---|---:|---:|---:|---:|---|
| DO Basic $6 | 1 | 1 GB | 25 GB | $6 | **Won't run.** Under the floor on RAM, disk and CPU at once |
| DO Basic $12 | 1 | 2 GB | 50 GB | $12 | No |
| DO Basic $24 | 2 | 4 GB | 80 GB | $24 | Bot-free only. Tight |
| DO Basic $48 | 4 | 8 GB | 160 GB | $48 | Works with playerbots. The stay-on-DO answer |
| DO Basic $96 | 8 | 16 GB | 320 GB | $96 | Comfortable, absurd for 3 people |
| DO General Purpose | 2 | 8 GB | 25 GB | $63 | **Disk too small**, and only 2 vCPU |
| Hetzner **CX33** | 4 | 8 GB | 80 GB | **€8.49** | **Pick this.** ~1/5 the DO price for the same box |
| Hetzner CX23 | 2 | 4 GB | 40 GB | €5.49 | Bot-free fallback |
| Hetzner CX43 | 8 | 16 GB | 160 GB | €15.99 | Comfortable tier, still cheaper than DO's 4 GB |
| Hetzner CAX21 (ARM) | 4 | 8 GB | 80 GB | €10.49 | See ARM caveat below |
| Hetzner CAX31 (ARM) | 8 | 16 GB | 160 GB | €20.99 | ditto |
| Hetzner CPX32 | 4 | 8 GB | 160 GB | ~€35 *(verify)* | CPX/CCX more than doubled in June; no longer the value play |
| Self-host on k3v1n + Tailscale | — | — | — | €0 | Best perf/€. Must be awake when friends play |

Sources: [Hetzner price adjustment 15 Jun 2026](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
[Hetzner Cloud API changelog](https://docs.hetzner.cloud/changelog) (16 Oct 2025 entries: the new
types, and the 1 Jan 2026 order stop on the old ones),
[DO droplet pricing](https://www.digitalocean.com/pricing/droplets).

**Deprecated → current name mapping:** CX22→CX23, CX32→**CX33**, CX42→CX43, CX52→CX53.
CPX31 likewise no longer exists; the Gen2 line is CPX22/32/42/52/62.

**Region:** CX and CAX are EU-only (Nuremberg, Falkenstein, Helsinki). One source claims Singapore
was added for cost-optimized plans *(verify)*; no US availability either way. CPX/CCX are in all
regions. If your friends are US-side, Falkenstein adds ~100–120 ms — for PvE WotLK with 3 people
that is fine; it is not fine if anyone wants arena.

**ARM caveat (CAX).** CAX is Ampere ARM64. AzerothCore on ARM64 is not officially validated
*(verify)*, and you would need an arm64 build path. Linux arm64 runners do exist and are free on
public repos (4 vCPU / 16 GB, same table as §3.3; 2 vCPU / 8 GB on private) — otherwise you are
cross-building under QEMU at roughly 5–10× the time.
Not worth €2/mo. Take the x86 CX33.

**Escape hatch — Hetzner Server Auction.** Refurbished dedicated boxes, no setup fee. Typical
finds are Ryzen/Xeon with 64–128 GB RAM in the €40–100/mo range (an EX44, i5-13500 + 64 GB, sits
around €40/mo; an AX101, Ryzen 9 5950X + 128 GB, around €103/mo). *Auction stock and prices move
constantly — check [Server Radar](https://radar.iodev.org/) rather than trusting these figures.*
This is the answer if you ever want the mod-playerbots wiki's actual recommended config —
hundreds of bots questing across the whole world with every map grid resident. Nothing in this
doc changes on a dedicated box except that you stop tuning for scarcity.

---

## 3. Build and deploy topology

### 3.1 Why not on the game server

AzerothCore's own guidance is **2+ GB RAM per compile core**, quad-core 3.0+ GHz recommended,
20 GB free disk minimum (50+ GB SSD recommended). On a 4 vCPU box `make -j4` therefore wants
~8 GB **for the compiler alone** — which is the entire CX33. Add playerbots (a large C++ module
compiled into the core, not a plugin) and you are linking a multi-GB binary on a machine whose
RAM is already committed to `mysqld` and the running `worldserver`.

Realistic outcomes if you try: OOM-killed `cc1plus`, or a 30–60 minute build during which the
server is unplayable, repeated on every module bump. Build times run 20–60 minutes depending on
cores even on healthy hardware.

Build elsewhere. Ship an image.

### 3.2 Flow

```
  repo push / tag
        │
        ▼
  GitHub Actions runner
   ├─ restore ccache from actions/cache
   ├─ docker buildx build  (multi-stage: builder → runtime, SAME base image)
   ├─ push ghcr.io/<user>/wowserver:<sha> and :latest
   └─ save ccache
        │
        ▼
  VPS:  docker compose pull && docker compose up -d
        │
  client data mounted from a volume, fetched once from
  wowgaming/client-data releases — never built in CI, never in the image
```

Keep client data **out of the image**. It is 3 GB of content that changes a few times a year and
is identical across every build; baking it in means re-pulling 3 GB for a one-line config change.
Volume + a one-shot init container that downloads it if absent.

### 3.3 Runner specs and limits

Standard Linux runners, from
[GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
checked **2026-08-07**:

| `runs-on: ubuntu-latest` | Public repo | Private repo |
|---|---|---|
| Linux standard runner | **4 vCPU, 16 GB RAM, 14 GB SSD** | **2 vCPU, 8 GB RAM, 14 GB SSD** |

**This is a real trap.** The README's "free 4 vCPU / 16 GB runner" is the *public repo* runner.
A private repo gets literally half the CPU and half the RAM behind the **same** `runs-on` line —
nothing in the workflow file tells you which one you got, and nothing fails; it is just slower.

What it actually costs, stated precisely rather than as "it won't fit":

- **Wall clock, not OOM.** `-j2` instead of `-j4` roughly doubles a cold build. AC's guidance is
  2+ GB RAM per compile core, and 8 GB across two cores is 4 GB/core — the private runner is not
  RAM-starved, it is *slow*. A cold AzerothCore + playerbots build measured in tens of minutes on
  the public runner can approach two hours here, which starts eating into the 6 h job cap on a
  cache miss.
- **Disk does not scale with the tier at all.** Both rows say **14 GB SSD**, and that volume is
  shared with the preinstalled toolchain image (compilers, browsers, SDKs, seeded docker images).
  AC build artifacts run 1–5 GB and buildx layer cache stacks on top. Free space varies by runner
  image release, so print `df -h /` in the job rather than trusting a number from a doc *(verify
  per image)*, and keep a `docker buildx prune` or free-disk-space step ready.

**Recommendation: make the build repo public.** It carries no secrets — `deploy/.env` is
gitignored (see [bring-up.md](bring-up.md)), the client-data and module URLs are public anyway, and
`GITHUB_TOKEN` is injected at run time. Public repos get double the cores *and* standard runners
are free and unlimited there instead of billing against your minutes allotment. Stay private only
if you have a specific reason, and then accept ~2× build times or pay for a larger runner.

Other limits that bite:

- **6 hours max per job** on GitHub-hosted runners. A cold AzerothCore + playerbots build fits,
  but not with much room on a 2-core runner — cache aggressively.
- **10 GB Actions cache per repository**, LRU-evicted. A ccache directory for a full AC build will
  push against this. Cap it (`ccache -M 4G`) so it doesn't evict itself plus everything else.
- Free plan: 20 concurrent jobs (irrelevant here).

### 3.4 glibc / ABI

The runner's own OS is irrelevant **if and only if** the build happens inside the container.
A binary linked against the runner's glibc and then copied into a different base image fails at
runtime with `GLIBC_2.xx not found` — and it fails on the VPS, not in CI, which is the worst place
to find out.

Rule: one Dockerfile, multi-stage, **builder and runtime stages derive from the same base tag**.

```dockerfile
# syntax=docker/dockerfile:1
# ^ has to be the literal first line, before any other comment or ARG. It pins the BuildKit
#   frontend, which is what makes the COPY heredoc in the runtime stage legal. On a builder
#   older than dockerfile 1.4, write the entrypoint with `RUN printf` instead.
ARG BASE=debian:bookworm-slim
# The core fork pin lives here, not in modules.txt — see modules.md §6.
ARG CORE_REPO=https://github.com/mod-playerbots/azerothcore-wotlk.git
ARG CORE_SHA=092e9ba6ff8dc6d861dddd1f31baa9d404381a85   # branch Playerbot, 2026-08-07

FROM ${BASE} AS builder
ARG CORE_REPO
ARG CORE_SHA
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ccache \
      libboost-all-dev libssl-dev default-libmysqlclient-dev libreadline-dev \
      zlib1g-dev libbz2-dev && rm -rf /var/lib/apt/lists/*
# Boost >= 1.74, OpenSSL >= 3.0.x, CMake >= 3.16 are the AC minimums; bookworm satisfies all three.
WORKDIR /src
# Fetch the pinned commit, not the branch tip: `-b Playerbot --depth 1` would make the
# same repo commit produce a different image tomorrow.
RUN git init -q . && git remote add origin "$CORE_REPO" \
 && git fetch --depth 1 origin "$CORE_SHA" \
 && git checkout --detach FETCH_HEAD
COPY modules.txt /tmp/modules.txt
# Format is owned by modules.md §6: THREE whitespace-separated fields per line —
# owner/name, ref, pinned commit — plus `#` comment lines. `ref` is informational
# (it records which branch the SHA came from); the checkout is always the SHA, so a
# moving branch can never end up in an image. Loop copied from modules.md §6.
# `set -e` matters: without it a failed clone just continues and you ship a core
# built without one of its modules.
RUN set -e; while read -r repo ref sha; do \
      case "$repo" in ''|\#*) continue ;; esac; \
      name="${repo##*/}"; \
      git clone --filter=blob:none "https://github.com/$repo.git" "modules/$name"; \
      git -C "modules/$name" fetch --depth 1 origin "$sha"; \
      git -C "modules/$name" checkout --detach "$sha"; \
    done < /tmp/modules.txt
RUN cmake -S . -B /build \
      -DCMAKE_INSTALL_PREFIX=/opt/ac \
      -DCMAKE_BUILD_TYPE=Release \
      -DTOOLS_BUILD=none -DSCRIPTS=static \
      -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
 && cmake --build /build -j"$(nproc)" && cmake --install /build

FROM ${BASE} AS runtime
# These are the bookworm names for the libs the builder above links against.
# default-libmysqlclient-dev resolves to MariaDB on Debian, hence libmariadb3 (NOT
# libmysqlclient21 — that is a different, also-present package; picking the wrong one
# gives you a runtime "cannot open shared object file", not a build error).
#
# The four libboost-* packages are exactly the four components the core requires.
# deps/boost/CMakeLists.txt:
#   find_package(Boost <ver> REQUIRED COMPONENTS filesystem program_options iostreams regex)
# regex is in that list, and it is the one a hand-written runtime list drops. Upstream's
# apps/docker/Dockerfile gets away without any of them because it configures with
# -DBoost_USE_STATIC_LIBS="ON"; this Dockerfile does not, so Boost links dynamically and all
# four .so files have to be installed here. Miss one and CI stays green while worldserver
# dies on the VPS at exec, before it logs anything:
#   error while loading shared libraries: libboost_regex.so.1.74.0
# No explicit libicu line is needed: libboost-regex1.74.0 depends on libicu72 and apt pulls
# it in. That is the same dependency upstream installs by hand (as libicu74, on its 24.04
# base) — static boost_regex still links ICU dynamically.
# libboost-system1.74.0 is deliberately NOT here. Boost.System has been header-only since
# Boost 1.69, AC does not list it as a component — its CMakeLists carries the comment
# "Boost.System is header-only since 1.69; do not require it explicitly" — and
# libboost-filesystem1.74.0 does not depend on it. Nothing links it. The derivation below
# is how you confirm that instead of taking it on trust.
#
# default-mysql-client is NOT optional and NOT for you to type commands with. AzerothCore's
# DBUpdater does not speak SQL migrations in C++ — it shells out to a `mysql` binary found on
# PATH, and aborts the first boot with "Didn't find any executable MySQL binary" when there
# isn't one (bring-up.md 1.1). On bookworm the metapackage pulls mariadb-client; AzerothCore's
# own runtime image installs this same package.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libboost-filesystem1.74.0 libboost-program-options1.74.0 \
      libboost-iostreams1.74.0 libboost-regex1.74.0 \
      libssl3 libmariadb3 libreadline8 ca-certificates \
      default-mysql-client \
      && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/ac /opt/ac

# The .sql files that client is fed are read off disk at run time, relative to SourceDirectory:
#   <src>/data/sql/base/db_{auth,characters,world}   initial import
#   <src>/data/sql/updates/...                       migrations
#   <src>/modules/<module>/data/sql/...              every module's SQL
# `cmake --install` ships none of it, so copy it out of the builder. These are exactly the two
# directories AzerothCore's own db-import image copies (`COPY data data`, `COPY modules modules`).
COPY --from=builder /src/data    /opt/ac/src/data
COPY --from=builder /src/modules /opt/ac/src/modules

# One image, two binaries. Which one a given container runs is decided by $ACORE_COMPONENT,
# set per service in deploy/docker-compose.yml — which therefore sets no `command:`.
# `exec` matters: worldserver becomes PID 1, so SIGTERM reaches it and its 0/1/2 exit codes
# (§7.2) reach Docker instead of a shell's.
COPY --chmod=0755 <<'EOF' /usr/local/bin/acore-entrypoint
#!/bin/sh
set -eu
case "${ACORE_COMPONENT:-}" in
  worldserver|authserver) ;;
  *) echo "ACORE_COMPONENT must be 'worldserver' or 'authserver' (got '${ACORE_COMPONENT:-}')" >&2
     exit 1 ;;
esac
exec "/opt/ac/bin/${ACORE_COMPONENT}" -c "/opt/ac/etc/${ACORE_COMPONENT}.conf"
EOF
ENTRYPOINT ["/usr/local/bin/acore-entrypoint"]
```

**What the compose file must do with that** ([bring-up.md §5](bring-up.md#5-deploydocker-composeyml)
owns the file): each of the two game services sets `environment: ACORE_COMPONENT: worldserver`
(resp. `authserver`) and sets **no `command:`**. An image with no ENTRYPOINT and a compose file
with no `command:` is two containers that start `bash`, find no tty, and exit 0 — `docker compose
up -d` reports success and you have no server. `-c` is belt and braces (the built-in default is
already `<prefix>/etc/<binary>.conf`), but it makes the path the bind mounts target explicit.

**`/opt/ac/src` is the value of `SourceDirectory`.** Set it in `worldserver.conf`, or as
`AC_SOURCE_DIRECTORY` in the environment — the compiled-in default is the *build-time* CMake
source path, which is `/src` in this Dockerfile and does not exist in the runtime stage.
[bring-up.md §1](bring-up.md#1-prerequisites) states the requirement and gives a one-liner that
checks a candidate image for all of it (mysql client, binaries, SQL tree, module `.conf.dist`)
before you try to boot it.

**Regenerate the runtime package list; do not maintain it by hand.** The set moves whenever AC
bumps a dependency, a module pulls in a new one, or you change base image — and getting it wrong
fails on the VPS, not in CI. From the repo root:

```bash
# 1. build just the builder stage, so the binaries exist somewhere that also has dpkg metadata
docker build --target builder -t wow-builder ./build

# 2. every shared object the two binaries actually pull in, mapped back to the package that
#    ships it. ldd is transitive, so indirect deps show up without you knowing they exist —
#    libicu72 appears here purely because libboost_regex needs it.
docker run --rm wow-builder sh -c '
  ldd /opt/ac/bin/worldserver /opt/ac/bin/authserver |
    sed -n "s/.* => \(\/[^ ]*\).*/\1/p" | sort -u |
    while read -r p; do
      dpkg -S "$p" 2>/dev/null || dpkg -S "$(readlink -f "$p")" 2>/dev/null ||
        echo "UNRESOLVED $p" >&2
    done | cut -d: -f1 | tr -d " " | tr "," "\n" | sort -u'
```

That yields *runtime* package names even though it runs in the builder, where `libboost-all-dev`
is installed: `ldd` resolves each `DT_NEEDED` to a versioned `libfoo.so.N` path, and on Debian
that file belongs to the runtime package — the `-dev` package owns only the unversioned
`libfoo.so` symlink. So you get `libboost-regex1.74.0`, not `libboost-regex-dev`.

**Query both path forms, or the list comes back short.** Bookworm is usr-merged and its dpkg
database is not consistent about it: `ldd` reports `/lib/x86_64-linux-gnu/…`, some packages
(`libc6`, `libselinux1`) are recorded under exactly that, and others (`libpcre2-8-0`) only under
`/usr/lib/x86_64-linux-gnu/…`. A plain `xargs dpkg -S` prints `no path found matching pattern` to
stderr for the second kind and *keeps going*, so you get a list that looks clean and is quietly
missing entries — the same silent underreport that produced the `libboost-regex` bug in the first
place. Hence the `readlink -f` retry, and the loud `UNRESOLVED` on stderr for anything neither
form finds. Do not simplify the loop back into an `xargs`.

Two entries in the Dockerfile's apt list are not in that output and have to be kept by hand:
`default-mysql-client` (a binary on `PATH`, not a linked library) and `ca-certificates` (data,
not a library). `libc6`, `libstdc++6` and `libgcc-s1` will appear and are already in
`bookworm-slim`; listing them is harmless either way.

Then prove the runtime image is actually complete. This is the check that turns a missing
`libboost-regex1.74.0` into a red CI run instead of a dead server:

```bash
# non-zero exit = at least one library is missing from the runtime stage.
# Worth a step in the §3.5 workflow, right after build-push-action.
docker run --rm --entrypoint sh <runtime-image> -c '
  ldd /opt/ac/bin/worldserver /opt/ac/bin/authserver | grep "not found" && exit 1
  exit 0'
```

Two more ABI rules:

- **Never `-march=native`.** The runner CPU is not the VPS CPU. Hetzner shared vCPU fleets are
  mixed silicon; an AVX-512 binary built on a runner will `SIGILL` on the VPS. Leave AC's default
  flags alone.
- **`-DTOOLS_BUILD=none`, and there is no `TOOLS` variable.** The extractors are only needed if
  you extract client data yourself (§4); skipping them cuts build time and image size. Get the
  spelling right, because cmake will not tell you: `conf/dist/config.cmake` (included
  unconditionally by the top-level `CMakeLists.txt`) declares
  `set(BUILD_TOOLS_AVAILABLE_OPTIONS none all db-only maps-only)` and `set(TOOLS_BUILD "none" …)`,
  and `FATAL_ERROR`s on a value outside that list — whereas an **unknown** `-D` is accepted
  silently and cached as an unused variable. `-DTOOLS=0`, which several third-party guides pass,
  is therefore a no-op that reads as load-bearing — and `-DTOOLS=1` does not build anything
  either. `none` is the default in any case; the flag above is documentation of intent.
- Pin every module by commit SHA in `build/modules.txt`, and the core fork by `ARG CORE_SHA` next
  to the base image. AC modules break against each other constantly, and against the Playerbot
  fork especially. Format, the current pin list and the bump procedure are all in
  [modules.md §6](modules.md#6-pinning) — do not fork the format here.

### 3.5 Workflow sketch

```yaml
name: build
on:
  push: { branches: [main], paths: ['build/**', '.github/workflows/build.yml'] }
  workflow_dispatch:

jobs:
  image:
    runs-on: ubuntu-latest
    timeout-minutes: 330            # under the 6h hard cap, fails loud before GitHub kills it
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: ./build
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/wowserver:${{ github.sha }}
            ghcr.io/${{ github.repository_owner }}/wowserver:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**What to cache.** `type=gha` buildx cache stores docker layers and is the single highest-value
cache — an unchanged base + deps layer skips the whole `apt-get`. It shares the same 10 GB
repository cache budget, so `mode=max` (which caches intermediate stages too) is what makes a
module-only change rebuild in minutes instead of an hour. If you additionally mount a ccache
directory via `RUN --mount=type=cache,target=/root/.ccache`, note that buildx cache mounts are
**not** persisted by `type=gha` across runs without extra plumbing — the layer cache is the one
that actually works out of the box.

### 3.6 Deploy

```bash
# on the VPS
docker compose pull && docker compose up -d
```

**You must authenticate to GHCR first, even if the repo is public.** A newly pushed GHCR package
is private by default: per GitHub's own docs the package *inherits the access permissions* of the
linked repository but **not its visibility**. Skip this and the very first command in
[bring-up.md](bring-up.md) §1.1 — the image verification step — fails with `denied`, before
anything else has a chance to go wrong.

Two ways out, in order of preference:

1. **Make the package public.** Once, in the package's settings on GitHub → Change visibility →
   Public. Then the VPS pulls anonymously and there is no credential on the box at all. The image
   contains a compiled server and no secrets, so this is the cleaner option.
2. **Log in with a token.** Create a classic PAT with `read:packages` only, and on the VPS:

   ```bash
   echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_OWNER" --password-stdin
   ```

   Credentials land in `~/.docker/config.json`. Note this is a second token beyond the one CI uses
   to push — CI authenticates with the automatically-provided `GITHUB_TOKEN`, which does not exist
   outside a workflow run.

Tag by SHA and pin the compose file to a SHA rather than `:latest`, so a rollback is a one-line
edit rather than an archaeology exercise. Keep the previous image on disk (that's the "one old
tag" line in the disk table).

---

## 4. Client data

**Canonical source: [`wowgaming/client-data`](https://github.com/wowgaming/client-data/releases).**
Confirmed still current — latest release **v20.0, "AC Data v20 enUS", published 2026-07-19**,
single asset `Data.zip` (1,196,168,257 B / 1.11 GiB). It is the source AzerothCore's own
installers and docker setup pull from.

Contents and sizes: see the table in §1.1. Extracts to `maps/ vmaps/ mmaps/ dbc/ Cameras/`,
3.01 GiB, which drop straight into the worldserver data directory.

```bash
# one-shot, on the VPS or in an init container
DATA=/srv/wow/data
mkdir -p "$DATA" && cd "$DATA"
curl -fL -o Data.zip \
  https://github.com/wowgaming/client-data/releases/download/v20.0/Data.zip
unzip -q Data.zip && rm Data.zip
# -> maps/ vmaps/ mmaps/ dbc/ Cameras/
```

Pin the version tag. `latest` moving under you mid-session is a class of bug you do not want to
debug from a client-side "your data is out of date" error.

### Why this removes the client from the server

The alternative is running AC's own extractors against a full, installed 3.3.5a client:

| Step | Tool | Cost |
|---|---|---|
| DBC + maps | `mapextractor` | minutes |
| VMaps extract | `vmap4extractor` | ~10–30 min |
| VMaps assemble | `vmap4assembler` | ~10–20 min |
| MMaps | `mmaps_generator` | **hours** — the AC wiki says "up to a few hours depending on your computer specs" and warns not to interrupt it |

That path requires ~15–25 GB of installed WoW client on the machine doing the extraction, plus a
build with the extractors switched on — **`-DTOOLS_BUILD=maps-only`**, whose whitelist in
`src/cmake/macros/ConfigureTools.cmake` is exactly `map_extractor`, `mmaps_generator`,
`vmap4_assembler`, `vmap4_extractor` — the `src/tools/` directory names for the four binaries in
the table above. (`all` additionally builds `dbimport`, which this setup does
not use — [bring-up.md §2.4](bring-up.md#24-do-not-copy-azerothcores-own-compose-topology).
`-DTOOLS=1` does nothing at all; see §3.4.)

On a 4 vCPU VPS the mmaps step alone would monopolise the box for most
of a day, and the output is **byte-comparable to what the release already contains**. AC's full
extraction is quoted as anything from 15 minutes to several hours depending on hardware and build
mode.

Do it yourself only if you patch map geometry (custom content, moved doodads). You are not.

**Consequence:** no WoW client on the server, no 15 GB of copyrighted MPQs on a VPS you rent, and
no extractors in the image — `TOOLS_BUILD` stays at its default `none`. Friends need the client;
the server does not.

---

## 5. Networking

### 5.1 Tailscale (recommended)

Three known friends is exactly the case Tailscale wins outright:

- No port forwarding, no NAT traversal work, no router config.
- **Nothing is exposed to the internet.** Ports 3724 and 8085 never appear on a public IP, so
  there is no scanning surface, no DDoS surface, and no brute-force surface on the auth server.
  Private WoW servers get scanned and hit constantly; a 1-realm server for 3 people has no
  business being findable.
- ACLs per-friend, revocable individually. Removing someone is a tailnet change, not a firewall
  edit and an account deletion.
- Works from anywhere they travel with zero reconfiguration.

Cost: everyone installs Tailscale and joins the tailnet. That's the whole ask, and it's the free
tier.

```bash
# VPS
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh --advertise-tags=tag:wow
tailscale ip -4      # -> 100.x.y.z   <- this is the address that matters
```

Bind the game ports to the tailnet interface only, so a misconfigured cloud firewall can't leak
them:

```yaml
# docker-compose.yml — note the explicit bind address
services:
  authserver:
    ports: ["100.x.y.z:3724:3724"]
  worldserver:
    ports: ["100.x.y.z:8085:8085"]
```

That is the bind-address rule, not the whole file — the assembled `docker-compose.yml` lives in
[bring-up.md](bring-up.md).

### 5.2 The realmlist gotcha — the one everybody gets wrong

Logging in is **two connections to two different servers**:

1. Client → `authserver` on **3724**, at whatever address is in the client's `realmlist.wtf`.
2. `authserver` hands back the realm list from `acore_auth.realmlist`. The client then connects to
   `worldserver` on **8085**, at the address **that table told it to use** — *not* the address it
   just authenticated against.

So if `realmlist.address` is `127.0.0.1` (the default), every remote client authenticates fine,
sees your realm, clicks it, and hangs at "Logging in to game server" forever — because it is
dutifully dialling its own loopback. This is the single most common private-server failure and it
looks like an auth problem when it isn't.

`address` must contain **the address the client can reach**. This is the canonical statement of
that row — the only one in this doc set. Run it after `tailscale ip -4`:

```sql
-- acore_auth
UPDATE realmlist
SET address   = '100.x.y.z',   -- the VPS's Tailscale IP; the address friends' clients dial
    port      = 8085,
    gamebuild = 12340
WHERE id = 1;
-- localAddress and localSubnetMask are deliberately NOT touched. See below.
```

**What `localAddress` / `localSubnetMask` actually do.** Verified against
[`Realm::GetAddressForClient`](https://github.com/azerothcore/azerothcore-wotlk/blob/master/src/server/shared/Realms/Realm.cpp),
which is the function that decides what address the realm list hands back:

1. If the connecting client's IP is **loopback**, and either `localAddress` or `address` is itself
   loopback, the client is handed **its own address** (127.0.0.1). If neither is loopback, it is
   handed `localAddress`.
2. Otherwise, if the client's IPv4 falls inside the network formed by
   `localAddress`/`localSubnetMask` (`Acore::Net::IsInNetwork`, i.e. boost's
   `make_network_v4(localAddress, localSubnetMask).hosts()`), it is handed **`localAddress`**.
3. Otherwise it is handed **`address`**.

The feature exists for split-horizon NAT: LAN clients get the private IP, WAN clients get the
public one. With Tailscale there is no horizon to split — every client reaches the VPS at the same
`100.x` address.

**Canonical choice: leave `localAddress` and `localSubnetMask` at their shipped defaults**
(`127.0.0.1` / `255.255.255.0`), because those defaults already produce the right answer on both
branches — `127.0.0.0/24` cannot contain a `100.64.0.0/10` tailnet client, so rule 2 never fires
for a friend and rule 3 hands them `address`, while a client run on the VPS itself still correctly
gets loopback via rule 1. Setting `localAddress` to the tailnet IP with a `255.255.255.255` mask
also works for remote clients, but it edits two more columns to reach the same behaviour and it
changes rule 1 — a client on the VPS is then handed the tailnet IP instead of loopback, which is
only reachable while `tailscaled` is up. Exactly one column is wrong out of the box; fix that one.
[client.md §2](client.md#2-pointing-it-at-the-server) says the same thing from the client side.

**The combinations that genuinely break it.** `localSubnetMask = 0.0.0.0` makes the network
`0.0.0.0/0`, so *every* client matches rule 2 and gets handed `localAddress` — if that is
`127.0.0.1`, everyone hangs at "Logging in to game server". Same outcome if you put a `100.x`
address in `localAddress` with a mask wide enough to cover Tailscale's `100.64.0.0/10` CGNAT
range. Note that `127.0.0.1` with a merely *loose* mask is not one of these cases —
`127.0.0.0/8` still cannot contain a `100.x` address — but there is no reason to widen it either.

Client side is [client.md §2](client.md#2-pointing-it-at-the-server), including the detail that
`Data/<locale>/realmlist.wtf` and `WTF/Config.wtf` are different files with different syntax and
both have to agree.

MagicDNS names work here too (the wiki confirms `address` accepts a hostname), but a raw `100.x` IP
has no resolution path to fail. Use the IP.

### 5.3 Alternative: public IP + ufw

```bash
ufw default deny incoming
ufw allow from <friend-ip> to any port 3724 proto tcp
ufw allow from <friend-ip> to any port 8085 proto tcp
ufw allow 22/tcp
ufw enable
```

…and `realmlist.address` = the public IP.

Worse here, concretely:

- Friends on residential connections have **dynamic IPs**. Either you re-edit ufw whenever someone
  reconnects their router, or you open 3724/8085 to `0.0.0.0/0` and accept the scanning.
- Open 3724 to the world and you get credential-stuffing against `acore_auth`. AC's account
  security is not a hardened auth service, and there's no MFA.
- A public game port on a €8/mo VPS with no DDoS protection is a single annoyed person away from
  being offline.
- You still have to solve the realmlist problem — it does not go away, you just point it at a
  public IP instead.

The only real argument for it: a friend who cannot or will not install Tailscale. Weigh that
against the above.

Either way, keep SSH on Tailscale only (`tailscale up --ssh`, then `ufw deny 22` from public).

---

## 6. MySQL tuning on a shared 8 GB box

### 6.1 Why the wiki number is wrong for you

The mod-playerbots wiki recommends:

```ini
innodb_buffer_pool_size = 32G     # their example, on a 64 GB machine
```

and its installation guide gives `innodb_buffer_pool_size = 4G  # Set to ~50% of total RAM`.

**That 50% rule assumes MySQL owns the machine.** On a CX33, 50% is 4 GB, and §1.2 says
`worldserver` plus 40 bots plus grid creep wants 3.5–5.5 GB. 4 GB buffer pool + 5 GB worldserver +
0.5 GB overhead = 9.5 GB on an 8 GB box. You will OOM-kill `worldserver` mid-session, or thrash
swap until the map update tick blows past `MapUpdateInterval` and the world visibly stutters.

**The structural reason you can go much smaller:** `worldserver` reads `acore_world` almost
entirely at **startup** and caches it in its own process memory. After boot, steady-state DB
traffic is dominated by `acore_characters` and `acore_playerbots` **writes** (player/bot saves),
not `acore_world` reads. The buffer pool needs to hold the hot character/bot working set, not the
4 GB world DB. The cost of a small pool is a slower startup — paid once per restart, not
continuously.

### 6.2 8 GB box (CX33 / DO $48)

```ini
# deploy/mysql.cnf   →   mounted read-only at /etc/mysql/conf.d/wow.cnf
[mysqld]
# --- the number that matters ---
innodb_buffer_pool_size        = 1G      # NOT 4G. ~12% of RAM. worldserver needs the rest.
innodb_buffer_pool_instances   = 1       # forced to 1 below 1G anyway; no benefit at this size

# --- write path: this is a game server, not a bank ---
skip-log-bin                             # no replication here; cuts disk writes hard
innodb_flush_log_at_trx_commit = 2       # see risk note
innodb_flush_method            = O_DIRECT
innodb_log_buffer_size         = 16M
innodb_io_capacity             = 500     # playerbots wiki values; fine for NVMe
innodb_io_capacity_max         = 2500
innodb_use_fdatasync           = ON      # MySQL >= 8.0.26

# --- AC-specific ---
transaction_isolation          = READ-COMMITTED   # playerbots wiki
max_connections                = 100     # see counting rule below

# --- claw back RAM from mysqld's own overhead ---
performance_schema             = OFF     # frees roughly 300-400 MB
table_open_cache               = 2000
tmp_table_size                 = 32M
max_heap_table_size            = 32M
```

**`deploy/mysql.cnf` must exist before the first `docker compose up`.** The compose file mounts it
as `./mysql.cnf:/etc/mysql/conf.d/wow.cnf:ro` ([bring-up.md §5](bring-up.md#5-deploydocker-composeyml)),
and Docker creates a *directory* at a bind-mount source that does not exist — the same trap as
`mysql-backup.cnf` in §7.3. It fails differently here, and worse: `my.cnf`'s
`!includedir /etc/mysql/conf.d/` **silently skips a directory**. Measured on `mysql:8.4` (8.4.11)
with a directory bind-mounted at that path, the server came up clean, logged no warning about it,
and ran on stock defaults — `innodb_buffer_pool_size` 134217728, `transaction_isolation`
`REPEATABLE-READ`, `performance_schema` `1`. So the symptom is not a crash; it is an untuned box
carrying the ~300–400 MB of perf_schema this section exists to reclaim, on the isolation level
playerbots asks you to change. Unlike `mysql-backup.cnf` (generated, 0600, gitignored) this is a
plain repo file — write it and commit it.

Confirm it took, rather than assuming:

```bash
cd /srv/wow/wowserver/deploy
docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf \
  -e "SELECT @@innodb_buffer_pool_size, @@transaction_isolation, @@performance_schema;"
# want: 1073741824   READ-COMMITTED   0
```

Budget: ~1 GB pool + ~0.4 GB engine/connection overhead ≈ **1.4 GB resident**, leaving ~6 GB for
worldserver and the OS. That matches the §1.2 minimum column.

**`innodb_flush_log_at_trx_commit = 2` risk, stated plainly:** on a *host* crash or power loss you
lose up to ~1 second of committed transactions. On a `mysqld` process crash you lose nothing. For
3 friends and some bots that is a second of loot; the fsync reduction is large. If that trade
bothers you, set it to `1` and expect more disk I/O.

**`max_connections` counting rule.** AC opens a synch + worker connection pool **per database**,
and playerbots adds a fourth (`acore_playerbots`, via `PlayerbotsDatabaseInfo`). With
`PlayerbotsDatabase.WorkerThreads`/`SynchThreads` on top, the total is a few dozen. 100 is
comfortable; do not cut it to 40 "to save memory" without adding up
`{World,Character,Login,Playerbots}Database.{Worker,Synch}Threads` first.

### 6.3 4 GB box (CX23 / DO $24) — bot-free only

```ini
[mysqld]
innodb_buffer_pool_size        = 512M
innodb_buffer_pool_instances   = 1
skip-log-bin
innodb_flush_log_at_trx_commit = 2
innodb_flush_method            = O_DIRECT
innodb_io_capacity             = 300
innodb_io_capacity_max         = 1500
transaction_isolation          = READ-COMMITTED
max_connections                = 60
performance_schema             = OFF
table_open_cache               = 1000
```

Leaves ~3 GB for worldserver. That is enough bare, not enough with playerbots — do not try.

### 6.4 If you ever move to a dedicated box

Then the wiki is right and you should follow it: `innodb_buffer_pool_size` = 50% of RAM,
`innodb_buffer_pool_instances = 12`, `innodb_log_buffer_size = 32M`,
`binlog_expire_logs_seconds = 432000`. The advice isn't wrong, it's just scoped to hardware you
don't have yet.

---

## 7. Ops

**Paths on the VPS.** Every script, cron line and `cd` below assumes this layout, and so do the
other docs:

| Path | What |
|---|---|
| `/srv/wow/wowserver` | this repo, checked out on the VPS |
| `/srv/wow/wowserver/deploy` | the compose project directory — `$DEPLOY`, and what cron `cd`s into |
| `/srv/wow/wowserver/scripts` | `bootstrap.sh`, `phase.sh`, `restore.sh`, plus the three files this section is the source for: `backup.sh` (§7.3), `health.sh` (§7.5), `soap-cmd.sh` (§7.6) |
| `/srv/wow/data` | client data (§4), outside the repo |
| `/srv/wow/backups` | dumps, outside the repo |

`deploy/` sits *inside* the checkout because the compose file bind-mounts `../conf/...` — the
conf files are repo files, deliberately, so that `git diff` tells you what the running server is
configured with ([bring-up.md §4.3](bring-up.md#43-three-ways-to-get-the-files-in-and-the-one-to-pick)).
Client data and backups stay outside it: 3 GB of extracted maps and a pile of dumps have no
business in a git working tree.

### 7.1 Swap

**Why AC spikes at startup:** `worldserver` loads the entire world DB, all DBC data and script
tables into process memory before it accepts a single login, and the *first* boot additionally
runs the DB import (quoted at 15–30 minutes). Startup RSS therefore peaks well above the
steady-state figure you sized for. Without swap, an 8 GB box that runs fine all week can get its
`worldserver` OOM-killed during the restart you did to fix something.

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10          # swap is an airbag, not a strategy
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf
```

4 GB. `swappiness=10` keeps the kernel from paging out hot map grids during normal play while
still letting the startup peak land somewhere.

### 7.2 Graceful restarts

```
.server shutdown 300
```

Syntax is `.server shutdown #delay [#exit_code]`. 300 seconds of warning, players get in-game
countdown broadcasts, characters are saved on the way down. Never `docker kill` or `SIGKILL` a
`worldserver` with people online — unsaved character state since the last periodic save is gone.

**How to actually issue it.** AzerothCore ships exactly two server binaries, `worldserver` and
`authserver` — there is no separate CLI tool. Commands go in by one of:

1. **Console (interactive).** `worldserver` reads commands on stdin. Requires the container to
   keep stdin open:

   ```yaml
     worldserver:
       stdin_open: true
       tty: true
   ```
   ```bash
   docker attach wowserver-worldserver-1     # then type: .server shutdown 300
   # detach WITHOUT killing it: Ctrl-P Ctrl-Q
   ```
   The detach sequence matters — Ctrl-C here sends SIGINT to the worldserver.

2. **SOAP (scriptable, use this for cron).** Off by default; enable in `worldserver.conf`:

   ```ini
   SOAP.Enabled = 1
   SOAP.IP      = "127.0.0.1"
   SOAP.Port    = 7878
   ```

   Then POST as a GM account (`.account set gmlevel <acct> 3 -1`):

   ```bash
   curl -s -X POST http://127.0.0.1:7878/ \
     -u "$AC_SOAP_USER:$AC_SOAP_PASS" \
     -H 'Content-Type: application/xml' \
     -d '<?xml version="1.0" encoding="utf-8"?>
         <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
           <SOAP-ENV:Body>
             <ns1:executeCommand xmlns:ns1="urn:AC">
               <command>server shutdown 300</command>
             </ns1:executeCommand>
           </SOAP-ENV:Body>
         </SOAP-ENV:Envelope>'
   ```

   Note the command has **no leading dot** inside the SOAP envelope. Keep `SOAP.IP` on loopback
   (or the tailnet address) — it is HTTP Basic auth over cleartext and must never face the
   internet.

**Exit codes — and the Docker trap.** AzerothCore returns:

| Code | Meaning | Produced by |
|---:|---|---|
| `0` | normal shutdown | `.server shutdown`, `.server exit`, `.server idleshutdown` |
| `1` | error / crash | GUID overflow, bad `Network.Threads`, network init failure |
| `2` | intentional restart | `.server restart`, `.server idlerestart` |

With `restart: always` or `restart: unless-stopped`, `.server shutdown 300` exits 0 and Docker
**immediately starts it again** — the server appears to ignore your shutdown. This is a recurring
confusion in AC's issue tracker and it is a restart-policy problem, not a bug.

Use the policy that matches the exit codes:

```yaml
services:
  worldserver:
    restart: on-failure      # exit 0 -> stays down (you meant it)
                             # exit 2 -> restarts  (you meant that too)
                             # exit 1 -> restarts  (crash recovery)
    stop_grace_period: 6m    # must exceed your longest .server shutdown delay
```

`stop_grace_period` matters: the default 10s means `docker compose stop` SIGKILLs mid-save.

These two keys are a requirement on the compose file, not the compose file itself — that lives in
[bring-up.md](bring-up.md). If it says `restart: always` or `restart: unless-stopped` on
`worldserver`, it is wrong for the reason above.

Phase flips (§ [server-config.md](server-config.md)) are exactly this: rewrite two conf keys,
`.server shutdown 300`, `docker compose up -d`.

### 7.3 Backups

**Back up `acore_auth` + `acore_characters` + `acore_playerbots`. Not `acore_world`.**
`acore_world` is ~4 GB of static content that is byte-reproducible from the AzerothCore sources
and module SQL at any time — backing it up nightly is 4 GB of churn to store something you already
have in git. `acore_characters` is the irreplaceable one; `acore_auth` holds accounts and the
realmlist row; `acore_playerbots` holds bot state (annoying but not fatal to lose — include it,
it's small).

If you keep custom SQL, it lives in `sql/` in this repo, not in a world DB dump.

```bash
#!/usr/bin/env bash
# scripts/backup.sh
set -euo pipefail

DEPLOY=/srv/wow/wowserver/deploy
cd "$DEPLOY"                      # cron runs from $HOME; `docker compose` needs the project dir

# deploy/.env is the single source of truth for MYSQL_ROOT_PASSWORD (bring-up.md owns it).
# Source it — under `set -u` an undefined $MYSQL_ROOT_PASSWORD aborts the script on first
# expansion, which is a nightly backup that silently stops happening.
set -a; . "$DEPLOY/.env"; set +a
: "${MYSQL_ROOT_PASSWORD:?not set in $DEPLOY/.env}"

# Credentials go in a 0600 option file, never on a command line. `-p"$pass"` is visible in
# `ps` on the host (container processes show up there) and in /proc inside the container;
# MySQL's own docs call the -p form insecure.
#
# REQUIREMENT on the compose file: the mysql service must carry
#     - ./mysql-backup.cnf:/etc/mysql/backup.cnf:ro
# because the dumps below run *inside* that container and read the file from there. If the
# mount is missing, every mysqldump fails "access denied" and the backup silently stops
# happening. deploy/mysql-backup.cnf is generated here, 0600, and gitignored — it is the root
# password in cleartext. Rewrite it with `>` as below (truncate in place) and never `mv` a temp
# file over it: a bind-mounted *file* follows the inode, so a rename leaves the running mysql
# container reading the old one.
umask 077
printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" > "$DEPLOY/mysql-backup.cnf"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=/srv/wow/backups
mkdir -p "$OUT"

for DB in acore_auth acore_characters acore_playerbots; do
  docker compose exec -T mysql \
    mysqldump --defaults-extra-file=/etc/mysql/backup.cnf \
              --single-transaction --quick --skip-lock-tables \
              --default-character-set=utf8mb4 "$DB" \
  | zstd -T0 -9 -o "$OUT/${DB}-${STAMP}.sql.zst"
done

# offsite: rclone v1.75.0 with a 'gdrive:' remote is already configured on the dev box
#          (confirmed via `rclone listremotes`); copy that remote's config to the VPS with
#          `rclone config file` -> scp rclone.conf, or re-run `rclone config` there.
rclone copy "$OUT" gdrive:backups/wowserver --include "*-${STAMP}.sql.zst"

# retention
find "$OUT" -name '*.sql.zst' -mtime +14 -delete
rclone delete gdrive:backups/wowserver --min-age 90d
```

`--single-transaction` gives a consistent InnoDB snapshot without locking — the server keeps
running. It implicitly disables `--lock-tables` (which mysqldump's default `--opt` would otherwise
turn on and which *would* stall the world), so the explicit `--skip-lock-tables` above is
belt-and-braces rather than strictly required. `--quick` streams rows instead of buffering whole
tables in mysqld's memory — on an 8 GB box that is not optional.

Three details about the credentials path, all of which bite silently:

- `deploy/.env` is read by two different parsers: Compose's own `.env` reader and, here, `sh`.
  They agree only on plain `KEY=value` with no spaces, no `export`, and no shell expansions.
  Keep the file to that subset — a value that Compose reads literally but `sh` re-expands is a
  password mismatch you will debug as "access denied for user root".
- `--defaults-extra-file` has to come **before** the other options — MySQL's option-file arguments
  are parsed first and "must be given before other options". Put it later and it is ignored, the
  client falls back to prompting for a password, and under `-T` (no TTY) the job fails or hangs.
  If you would rather not mount a file at all, the same content in a 0600 `/root/.my.cnf` *inside*
  the container is picked up automatically and you can drop the flag.
- The value is quoted because in an option file **`#` starts a comment even mid-line**, so an
  unquoted `password=hunter#2` silently becomes `hunter`. Quoting fixes `#`; it does not fix
  backslashes, which are still read as escapes (`\b \t \n \r \\ \s`). Generate the root password
  from `[A-Za-z0-9]` and this whole class of problem goes away.

Nightly via cron at an hour nobody plays:

```cron
17 5 * * *  /srv/wow/wowserver/scripts/backup.sh >> /var/log/wow-backup.log 2>&1
```

**Verify the offsite copy exists**, not just that the script exited 0:

```bash
rclone lsl gdrive:backups/wowserver | tail -5
```

### 7.4 Restore

```bash
# 0. same 0600 credentials file the backup script writes (§7.3). No -p on any command line.
cd /srv/wow/wowserver/deploy

# 1. stop the world so nothing writes while you restore
#    (.server shutdown 60 via console or SOAP — see 7.2)
docker compose stop worldserver authserver

# 2. pull the dump (skip if restoring from local retention)
rclone copy gdrive:backups/wowserver/acore_characters-20260807T051700Z.sql.zst /tmp/

# 3. restore. drop+recreate so stale rows don't survive the import
docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf \
  -e "DROP DATABASE IF EXISTS acore_characters; CREATE DATABASE acore_characters
      DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"

zstd -dc /tmp/acore_characters-20260807T051700Z.sql.zst \
  | docker compose exec -T mysql \
      mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_characters

# 4. rebuild acore_world from source instead of restoring it
docker compose up -d          # AC re-imports/updates world DB on boot
```

If `deploy/mysql-backup.cnf` is missing (fresh VPS, restoring onto a rebuilt box), regenerate it
the way §7.3 does — source `deploy/.env` and write the `[client]` block — before step 3.

Two things to check after any `acore_auth` restore:

- The `realmlist` row still has the **current** `address` (§5.2). A restore from before a VPS
  rebuild will hand out a dead IP and look like a total outage.
- `realmlist.id` still matches `RealmID` in `worldserver.conf`.

**Test the restore path once, on purpose, before you need it.** Restore last night's
`acore_characters` into a scratch DB name and confirm the row count in `characters` looks right.
An untested backup is a hypothesis.

### 7.5 Health and OOM watch

Container-level liveness:

```yaml
  worldserver:
    healthcheck:
      # /proc/net/tcp needs no extra packages; 1F95 is 8085 in hex.
      # (`ss` and `nc` are NOT in debian:*-slim — a healthcheck using them fails
      #  permanently and silently restart-loops the container.)
      test: ["CMD-SHELL", "grep -q ':1F95 ' /proc/net/tcp || exit 1"]
      interval: 60s
      timeout: 5s
      retries: 3
      start_period: 40m      # quoted from bring-up.md's compose file — that file owns the number
```

`start_period` is not padding: the first boot runs the whole database import *and* the initial
playerbot population before the listener ever opens, and a grace period shorter than that
restart-loops the container through it forever. The value lives in
[bring-up.md §5](bring-up.md#5-deploydocker-composeyml) and nowhere else — this snippet quotes it
so the healthcheck reads correctly, it does not own it. Change it there.

Protect the database from the OOM killer. If the kernel has to kill something, `worldserver`
losing a few minutes is recoverable; `mysqld` dying mid-write is the scenario backups exist for:

```yaml
  mysql:
    oom_score_adj: -500
  worldserver:
    oom_score_adj: 200
```

Watch the two things that actually predict trouble — monotonic `worldserver` RSS (grid creep, §1.2)
and swap consumption:

```bash
#!/usr/bin/env bash
# scripts/health.sh  ->  /srv/wow/wowserver/scripts/health.sh on the VPS
RSS_MB=$(ps -o rss= -C worldserver | awk '{s+=$1} END {print int(s/1024)}')
SWAP_MB=$(free -m | awk '/^Swap:/ {print $3}')
AVAIL_MB=$(free -m | awk '/^Mem:/ {print $7}')

if [ "${RSS_MB:-0}" -gt 5500 ] || [ "$SWAP_MB" -gt 1024 ] || [ "$AVAIL_MB" -lt 512 ]; then
  echo "$(date -Is) worldserver_rss=${RSS_MB}MB swap=${SWAP_MB}MB avail=${AVAIL_MB}MB" \
    >> /var/log/wow-health.log
fi
```

It writes its own log line and stays quiet otherwise, so cron only needs somewhere for errors:

```cron
*/15 * * * *  /srv/wow/wowserver/scripts/health.sh 2>> /var/log/wow-health.log
```

Check OOM kills after any unexplained disappearance:

```bash
journalctl -k --since '24 hours ago' | grep -i 'out of memory\|oom-kill'
docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' wowserver-worldserver-1
```

`OOMKilled=true` means raise RAM or lower `innodb_buffer_pool_size`. Exit code `1` means read the
worldserver log — that's an AC error, not a resource problem.

### 7.6 The weekly restart is a requirement, not a suggestion

AzerothCore **never unloads a map grid once it is loaded** — it stays resident until the process
exits (§1.2). `worldserver` RSS is therefore monotonic within an uptime: it only ever goes up, at a
rate set by how much of the world your party and your bots wander into. There is no configuration
that reclaims it and no steady state to converge on. On an 8 GB box the only mechanism that
returns that memory is a process restart, so schedule one and treat a missed week as an incident,
not an inconvenience.

```cron
0 6 * * 2  /srv/wow/wowserver/scripts/soap-cmd.sh "server restart 300"
```

`scripts/soap-cmd.sh` is the §7.2 curl call with `$1` dropped into the `<command>` element, and
nothing else. Its whole contract:

- **One argument: the command *without* its leading dot.** `soap-cmd.sh "server restart 300"`,
  not `".server restart 300"`. It goes verbatim into `<command>`, which §7.2 writes dot-less;
  the console is the one place the dot is optional.
- **Credentials come from `deploy/.env`:** `AC_SOAP_USER` and `AC_SOAP_PASS`, the GM account of
  §7.2, sourced with the same `set -a; . /srv/wow/wowserver/deploy/.env; set +a` idiom
  `scripts/backup.sh` uses for `MYSQL_ROOT_PASSWORD` (§7.3), plain-`KEY=value`-only caveat and
  all. Never on a command line. Note that these are **two keys beyond** the set
  [bring-up.md §5.1](bring-up.md#51-deployenvexample) tabulates — that file owns `deploy/.env`,
  and SOAP is the only thing here that needs them.
- **POSTs to `http://127.0.0.1:7878/`.** Host loopback reaches the container because
  [bring-up.md §5](bring-up.md#5-deploydocker-composeyml) publishes the port as
  `127.0.0.1:7878:7878`, so this runs from host cron with no `docker compose exec` — which is
  just as well, since the runtime image has no `curl` in it (§3.4).

Use `.server restart` (exit 2), not `shutdown` (exit 0) — under `restart: on-failure` the
shutdown code leaves the container down and the server stays offline until someone notices.

Weekly is a starting cadence, not a measurement. The §7.5 health log is what tells you whether it
is right: if `worldserver_rss` is crossing your threshold before Tuesday, move the restart earlier
or add a second one, and if it never crosses in a fortnight you can stretch it. The number to watch
is the one in `scripts/health.sh`, not the calendar.
