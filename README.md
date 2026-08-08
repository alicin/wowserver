# wowserver

Plan for a private WotLK 3.3.5a server for ~3 friends, gated Classic → TBC → WotLK,
with bots and small-group instance scaling.

This repo holds the **source, config and scripts**. The server itself runs on a remote box.

- [docs/hosting.md](docs/hosting.md) — sizing math, host comparison, build/deploy topology, networking, backups
- [docs/bring-up.md](docs/bring-up.md) — first-boot runbook: databases, compose file, accounts, smoke test
- [docs/server-config.md](docs/server-config.md) — progression phases, rates, AutoBalance and bot tuning
- [docs/modules.md](docs/modules.md) — module shortlist, tiered, with known conflicts
- [docs/client.md](docs/client.md) — getting a 3.3.5a client, realmlist, addon list

---

## TL;DR

**Core: AzerothCore.** Not TrinityCore, not MaNGOS. Every single thing you asked for —
bots, dungeon scaling, progression gating, XP rates, QoL — already exists as an AzerothCore
module maintained by someone else. TrinityCore has no module system and you'd be
maintaining patches by hand.

**The $5 droplet will not work.** Not "will be slow" — will not boot the stack. Numbers in
[docs/hosting.md](docs/hosting.md); the summary is that a 1 GB / 1 vCPU / 25 GB droplet is
under the floor on all three axes at once. Cheapest thing that actually runs this is a
**Hetzner CX33 (4 vCPU / 8 GB / 80 GB) at €8.49/mo** — call it 40–70% more than the droplet
you were budgeting once IPv4 and VAT land, and still about a fifth of the DigitalOcean tier
that can actually run this ($48/mo for 8 GB / 4 vCPU).

**Progression: one edit pass per phase.** A handful of conf keys across a few files, one
`UPDATE` on the auth DB, and a restart. `MaxPlayerLevel` and `Expansion` do the heavy lifting;
the rest is keeping bots, the dungeon finder and the auction house in step with the cap.
[docs/server-config.md](docs/server-config.md) §1 holds the canonical checklist — trust it over
any count quoted here. It's still the "loose gating" you asked for, and it's the model
ChromieCraft runs in production.

**Bots: pick one, it decides your base repo.** Playerbots and NPCBots are both *core forks* —
you build against their AzerothCore, not upstream. You can't have both, and you can't
change your mind cheaply. Recommendation below.

---

## The three decisions that shape everything else

### 1. Bots — Playerbots vs NPCBots

|  | **mod-playerbots** | **mod-npcbots** |
|---|---|---|
| What a bot is | a real `Player` object with a character | a creature/companion |
| Feel | other players — they quest, gear up, run dungeons, queue BGs | hired mercenaries that follow you |
| Cost | heavy. Upstream wiki asks for **16 GB RAM min, 32 GB preferred, 4–6 cores, 3.0 GHz+** | much lighter |
| Base repo | [`mod-playerbots/azerothcore-wotlk`](https://github.com/mod-playerbots/azerothcore-wotlk) branch `Playerbot` | [`trickerer/AzerothCore-wotlk-with-NPCBots`](https://github.com/trickerer/AzerothCore-wotlk-with-NPCBots) |
| Control | 100+ chat commands, plus a client addon ([MultiBot-Chatless](https://github.com/Wishmaster117/MultiBot-Chatless)) | NPC gossip menus |
| **Counts toward AutoBalance player count** | **yes** | **no** |

That last row is the tiebreaker for your use case. AutoBalance scales instances by how many
*players* are inside. Playerbots are players, so "3 friends + 2 bots in a 5-man" correctly
scales as a full group, and "3 friends + 2 bots in Karazhan" correctly scales a 10-man down
to 5. NPCBots are invisible to it — a 3-friend + 2-NPCBot group reads as 3 players, gets
scaled down to 3-player difficulty, and then you also have two extra bodies. Content becomes
trivial. (Someone maintains a [forked AutoBalance for NPCBots](https://github.com/sokie/mod-autobalance-npcbots)
precisely because of this, but you'd be on a fork of a fork.)

**Decided: Playerbots**, on an 8 GB box. Ignore the 16 GB figure — that's sized for a few
hundred random bots roaming and loading map grids across the whole world. You want maybe
20–40, mostly parked near your party. Tuning for that is in [docs/server-config.md](docs/server-config.md).

This also settles the base repo: everything gets built against
`mod-playerbots/azerothcore-wotlk` @ `Playerbot`, and every other module has to be compatible
with that fork. Note the project moved orgs from `liyunfan1223` — most guides you'll find
online are stale on this.

Because playerbots are full `Player` objects — each with a row in `acore_characters`, an
inventory, and state in a fourth database of their own — an 8 GB box is a real floor rather
than a nice-to-have. NPCBots was the option that would have fit 4 GB, and it's off the table.

One thing they *don't* do: **playerbots never list on the auction house.** There isn't a
single `auction` reference in the module's 802 config keys. With three real players that
leaves the AH genuinely dead, so an AH-populating module is Tier 1 rather than flavour — see
[docs/modules.md](docs/modules.md).

### 2. Gating — manual flips vs a progression module

**Option A — manual (recommended, matches "not too strictly").**
Three phases. The two keys below are what define each phase; the full flip checklist
(bot level windows, dungeon-finder expansion, the auth-DB `UPDATE`) is in
[docs/server-config.md](docs/server-config.md) §1.

| Phase | `MaxPlayerLevel` | `Expansion` | What opens |
|---|---|---|---|
| 1 · Classic | `60` | `0` | Azeroth only. No Outland, no DKs, no Blood Elf/Draenei, no flying |
| 2 · TBC | `70` | `1` | Dark Portal, Outland, Kara → Sunwell, BE + Draenei, flying |
| 3 · WotLK | `80` | `2` | Northrend, Death Knights, Naxx80 → ICC, full RDF |

No character wipe, no DB surgery. XP earned at cap is discarded, so nobody banks a windfall
and shoots to 70 on day one of phase 2. You still get the full WotLK talent trees and
spellbook throughout — you're just capped at what level 60 grants, which is what you asked for.

**Option B — [mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression).**
17 tiers, per-player, boss-gated, level caps 60/70/80 baked in, explicit Playerbots support.
It is *exactly* the 60→70→80 shape you described and it's the real deal — pre-nerf raid
stats, vanilla reagents, catch-up mechanics removed. The catch: to reach TBC you must clear
Molten Core → BWL → AQ → Naxxramas-40. With 3 people and bots that's a genuinely great
campaign, or a wall you never get past. It also adds a lot of surface area on top of a core
fork.

Take A. Revisit B in a year if the server survives.

### 3. Hosting — where it actually lives

Full comparison in [docs/hosting.md](docs/hosting.md). Short version:

| Option | Specs | Cost | Verdict |
|---|---|---|---|
| DO Basic $6 | 1 GB / 1 vCPU / 25 GB | $6/mo | **Won't run.** Out of RAM, CPU and disk simultaneously |
| DO Basic $24 | 4 GB / 2 vCPU / 80 GB | $24/mo | Bot-free only. Playerbots won't fit |
| DO Basic $48 | 8 GB / 4 vCPU / 160 GB | $48/mo | Works with Playerbots |
| **Hetzner CX33** | **4 vCPU / 8 GB / 80 GB** | **€8.49/mo** | **Best value by a mile.** EU regions only |
| Your own box + Tailscale | whatever k3v1n has | free | Best perf, needs to be awake when friends play |

Prices ex-VAT and ex-IPv4. Two separate Hetzner events to keep straight: the CX22/32/42/52
line was **replaced** by CX23/33/43/53 (announced 2025-10-16, no new orders from 2026-01-01),
and then prices **rose** on 15 June 2026. So a guide quoting **CX32 at €6.80** is naming a
plan that can no longer be ordered, at a price that no longer applies. CPX31 is gone too, and
the Gen2 CPX line roughly doubled, so it's no longer the value option some guides still call it.

If you're EU/TR, Hetzner Falkenstein or Helsinki is the obvious answer. It's a couple of euros
more than the droplet you were budgeting, and it's the difference between "works" and "doesn't".

Worth doing regardless: **run it on k3v1n over Tailscale for the first couple of weeks**
while you're still adding modules and rebuilding constantly. Move it to the VPS once the
config has settled.

---

## Rates and scaling, as asked

```ini
# worldserver.conf
Rate.XP.Kill     = 1.5
Rate.XP.Quest    = 1.5
Rate.XP.Quest.DF = 1.5
Rate.XP.Explore  = 1.5
Rate.XP.Pet      = 1.5
```

**Decided: full XP regardless of group size.** AutoBalance reduces rewards in scaled-down
instances by default, which would quietly eat the 1.5× exactly when there are fewer of you.
Turn it off:

```ini
# AutoBalance.conf
AutoBalance.RewardScaling.XP    = 0
AutoBalance.RewardScaling.Money = 0   # same logic; drop this line if you want gold to scale

# SoloLfg.conf — this one is the trap
SoloLFG.FixedXP = 0                   # ships as 1, which pins dungeon XP to a flat 0.2×
```

That second block matters more than the first. `mod-solo-lfg` — the module that lets three of
you queue for a five-man at all — ships with `SoloLFG.FixedXP = 1` and `SoloLFG.FixedXPRate = 0.2`.
Install it and leave the defaults and you get **0.2× XP in dungeons even with AutoBalance's
reward scaling already off.** Both have to be handled for the full-rate decision to hold.

Two related notes so this actually holds in play:

- Core WoW already splits kill XP across the party, so a 3-man group earns *more* per head than
  a 5-man does. Nothing to configure — smaller groups are already favoured.
- `AutoBalance.LevelScaling` can rewrite creature levels toward the party, and the core XP
  formula keys off creature level. That's a second, indirect path to less XP per kill.
  [docs/server-config.md](docs/server-config.md) works out whether it bites in practice at
  level-appropriate content, and what to set if it does.

5-man Karazhan and 3-man dungeons both come from [mod-autobalance](https://github.com/azerothcore/mod-autobalance).
Starting values and the tuning loop are in [docs/server-config.md](docs/server-config.md).

---

## Build and deploy topology

You cannot compile AzerothCore on the game server — the build wants ~8–16 GB and an hour of
several cores, and it would be competing with the thing it's replacing.

```
  this repo  ──push──>  GitHub Actions runner
                             │
                             │  builds core fork + pinned modules
                             ▼
                        GHCR image  ──pull──>  VPS: docker compose up -d
                                                     │
  client data (maps/vmaps/mmaps/dbc) ────────────────┘
  from wowgaming/client-data releases — prebuilt, no client needed on the server
```

That last line means the WoW client never has to touch the server, and skips hours of
`mmaps_generator`. The v20.0 archive is a 1.19 GB download that extracts to 3.01 GiB, of which
mmaps alone is 2.04 GiB.

**Runner sizing is worth a decision.** The free 4 vCPU / 16 GB runner is the *public*-repo
tier; a private repo gets 2 vCPU / 8 GB. That's the same 4 GB per core either way, so it isn't
a memory problem — it's wall clock, and `-j2` roughly doubles a cold build, which starts
crowding the 6 h job cap on a cache miss. The constraint that *doesn't* scale with tier is
disk: ~14 GB on both, shared with the preinstalled toolchain image. Since this lives inside
`dotfiles`, splitting `build/` into a public repo buys double the cores and unmetered minutes.
Details in [docs/hosting.md](docs/hosting.md).

## Proposed repo layout

```
wowserver/
├── README.md
├── docs/
├── build/
│   ├── Dockerfile            # core fork + modules, compiled
│   └── modules.txt           # pinned module repos + commit SHAs
├── deploy/                   # lives at /srv/wow/wowserver/deploy on the VPS
│   ├── docker-compose.yml    # worldserver, authserver, mysql — restart: on-failure,
│   ├── .env.example          #   NOT always. AC exits 0 on `.server shutdown`
│   ├── mysql-init/           # CREATE DATABASE + GRANT for the four schemas
│   ├── mysql.cnf             # innodb_buffer_pool_size etc. for a shared 8 GB box
│   └── mysql-backup.cnf      # 0600, gitignored, generated by backup.sh
├── conf/
│   ├── worldserver.conf
│   ├── authserver.conf
│   └── modules/              # playerbots.conf, AutoBalance.conf, ...
├── sql/                      # realmlist address, accounts, any custom data
└── scripts/
    ├── bootstrap.sh          # provision: docker, tailscale, swap, ufw
    ├── phase.sh              # flip 1→2→3: rewrite conf keys, graceful restart
    ├── backup.sh             # mysqldump auth + characters + playerbots, offsite
    ├── restore.sh
    ├── soap-cmd.sh           # run a server command over SOAP (no worldserver-cli exists)
    └── health.sh             # RSS / grid-creep watch, feeds the weekly restart call
└── .github/workflows/build.yml
```

Pin module commits in `modules.txt`. AzerothCore modules break against each other constantly
and "it worked last Tuesday" is not a recoverable state without pins.

Note the backup scope: **Playerbots adds a fourth database**, `acore_playerbots`, on top of
`acore_auth` / `acore_characters` / `acore_world`. Three of those need backing up —
`acore_world` is reproducible from the importer, the other three are not.

## Suggested order of work

1. Decide bots + host (the two above). Everything downstream depends on them.
2. Stand it up locally on k3v1n: core fork + MySQL + prebuilt client data, no modules. Log in.
3. Add AutoBalance + the bot module. Get a 3-man dungeon feeling right before adding anything else.
4. Layer in Tier-1 QoL modules one at a time, rebuilding between each.
5. Move to the VPS: Dockerfile, CI build, compose, Tailscale, backups.
6. Set phase 1 conf, hand out clients + addon pack, play.
7. Flip phases when you're bored of the current one.

## Settled

- Core: AzerothCore.
- Bots: Playerbots (fixes the base repo).
- Gating: manual `MaxPlayerLevel` + `Expansion` flips, three phases.
- XP: 1.5×, full rate regardless of group size.

## Open questions for you

- **Region?** Decides Hetzner (EU-only on the cost-optimized tiers) vs staying on DigitalOcean
  at $48/mo.
- **Is the ~$6/mo figure a hard ceiling?** Playerbots needs 8 GB, so the realistic floor is
  €8.49/mo at Hetzner, $48/mo at DO, or free on your own box over Tailscale. If the ceiling is
  truly hard, Hetzner is the only paid option that comes close.
- **Public build repo?** Splitting `build/` into a public repo doubles the CI runner you get
  for free. Everything in it is config and a Dockerfile — no secrets — but it's your call.
  Note these are two separate switches: a GHCR package inherits the repo's *permissions* but
  **not** its *visibility*, so a public repo still publishes a private image. Either flip the
  package to public too, or keep a `read:packages` token on the VPS
  ([docs/hosting.md](docs/hosting.md) §3.6).
