# wowserver

A private WotLK 3.3.5a server for ~3 friends, phased Classic → TBC → WotLK **by level cap alone**,
with bots and small-group instance scaling.

This repo — [`bunnies-inc/wowserver`](https://github.com/bunnies-inc/wowserver), public — holds the
**source, config and scripts**. The server itself runs on a remote box: a Hetzner CX33 in
Falkenstein, `debian-8gb-fsn1-1`, `167.233.128.19`. Nothing is deployed to it yet.

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

**Progression: the level cap is the only gate.** `MaxPlayerLevel` goes 60 → 70 → 80 and that is
the decision. `Expansion` stays at `2` in all three phases, so every race and class — Death
Knight, Blood Elf, Draenei — is available from day one, and there is **no per-phase auth-DB
`UPDATE`**: accounts are stamped `expansion = 2` once, at creation. What still moves per phase is
bookkeeping — the bot level window, the dungeon finder's expansion, the AH bot's level ceiling and
the mod-assistant profession/flight-path tiers.
[docs/server-config.md](docs/server-config.md) §1 holds the canonical checklist — trust it over
any count quoted here. This is looser gating than the first draft, deliberately; the cost is
[spelled out below](#the-tradeoff-outland-is-open-at-58).

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
Three phases, one key. The full flip checklist (bot level window, dungeon-finder expansion, AH
bot ceiling, mod-assistant tiers) is in [docs/server-config.md](docs/server-config.md) §1.

| Phase | `MaxPlayerLevel` | `Expansion` | What the cap makes worth doing |
|---|---|---|---|
| 1 · Classic | `60` | `2` | Vanilla Azeroth, MC → Naxx40. Outland is reachable and pointless |
| 2 · TBC | `70` | `2` | Outland, Kara → Sunwell. Northrend is reachable and pointless |
| 3 · WotLK | `80` | `2` | Northrend, Naxx80 → ICC, heroics, full RDF |

`Expansion` does not move. Every race and class is on from phase 1 — no
`CharacterCreating.Disabled.RaceMask`, no `ClassMask`, no per-phase `UPDATE account SET expansion`.
The single account-side step is a one-time `expansion = 2`, which
[AzerothCore stamps automatically at account creation](docs/server-config.md#accountexpansion--the-one-time-setup-step)
once `Expansion = 2` is in the conf before first boot.

No character wipe, no DB surgery. XP earned at cap is discarded, so nobody banks a windfall
and shoots to 70 on day one of phase 2. You get the full WotLK talent trees and spellbook
throughout — you're just capped at what level 60 grants, which is what you asked for.

#### The tradeoff: Outland is open at 58

Being honest about what "level cap only" buys and costs, because it is a real change from the
first draft and the cost lands on the honour system rather than on a config key.

`Expansion = 2` gates nothing but expansion-flagged maps, races and classes — and at `2` it gates
none of them. So in phase 1 the Dark Portal works at 58, the boats to Northrend work at 68, and a
level-60 character can train Expert Riding and fly around Outland.

**Why that's fine.** The cap is what makes content pointless rather than forbidden. XP is
discarded at cap (`Player::GiveXP` returns early), so walking into Hellfire Peninsula at 60 earns
nothing, unlocks nothing, and advances no character. Nobody rushes ahead because there is nowhere
ahead to get to. It also deletes the two nastiest failure modes of the strict version: the silent
`account.expansion` desync that stranded existing accounts on the old expansion, and RDF dying
outright at levels 59–60 because the client offers only TBC dungeons the server then refuses.

**What it costs.** A determined player can walk through the portal at 58 and fetch Outland greens
and quest rewards that outclass anything in phase 1's loot tables, and a level-60 group could go
grief Ramparts for gear. That is a real hole and there is no config that closes it without
`Expansion = 0`, which brings the DK/BE/Draenei lockout and the RDF break back with it. With three
friends, a house rule is cheaper than a config flag.

The module that *would* close it properly is Option B below — it gates content per player rather
than per realm, which is the only honest fix. We are deliberately not taking it. The whole point of
this design is that a phase flip is one key.

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
| **Hetzner CX33** | **4 vCPU / 8 GB / 80 GB** | **€8.49/mo** | **Chosen, bought, running.** Falkenstein |
| Your own box + Tailscale | whatever k3v1n has | free | Best perf, needs to be awake when friends play |

Prices ex-VAT and ex-IPv4. Two separate Hetzner events to keep straight: the CX22/32/42/52
line was **replaced** by CX23/33/43/53 (announced 2025-10-16, no new orders from 2026-01-01),
and then prices **rose** on 15 June 2026. So a guide quoting **CX32 at €6.80** is naming a
plan that can no longer be ordered, at a price that no longer applies. CPX31 is gone too, and
the Gen2 CPX line roughly doubled, so it's no longer the value option some guides still call it.

**Decided and provisioned: Hetzner CX33 in Falkenstein**, `debian-8gb-fsn1-1`, Debian 13, at
`167.233.128.19`. It's a couple of euros more than the droplet originally budgeted, and it's the
difference between "works" and "doesn't". Nothing is deployed on it yet.

Still worth doing: **run it on k3v1n over Tailscale for the first couple of weeks** while you're
still adding modules and rebuilding constantly. Move it to the VPS once the config has settled —
the box being paid for doesn't make it the right place to iterate.

---

## Rates and scaling, as asked

```ini
# worldserver.conf
Rate.XP.Kill     = 2
Rate.XP.Quest    = 2
Rate.XP.Quest.DF = 2
Rate.XP.Explore  = 2
Rate.XP.Pet      = 2

Rate.Reputation.Gain = 10   # LowLevel.Kill / LowLevel.Quest stay at 1 — they multiply
                            # on top of this, and 10 there too would be 100×

Rate.Drop.Item.Poor      = 3
Rate.Drop.Item.Normal    = 3
Rate.Drop.Item.Uncommon  = 3
Rate.Drop.Item.Rare      = 3
Rate.Drop.Item.Epic      = 3
Rate.Drop.Item.Legendary = 3
Rate.Drop.Item.Artifact  = 3
Rate.Drop.Money          = 3

Rate.Talent = 1.4           # 71 talent points at 60 instead of 51
```

Four numbers, and [docs/server-config.md](docs/server-config.md) §3 says for each one who owns it,
what it actually multiplies, and what it does *not* do:

- **XP 2×.** Everything else that touches XP is neutralised so this is the only multiplier in play.
- **Reputation 10×.** One key. `Rate.Reputation.LowLevel.Kill` / `.LowLevel.Quest` are *not* set to
  10 — they multiply on top of `Gain`, so that would be 100× on grey-level content.
- **Loot 3×, and it does less than it sounds.** It multiplies a drop *chance*, and AzerothCore
  returns early on any entry already at 100% and never applies quality rates to grouped entries at
  all. Boss loot is almost entirely grouped or guaranteed, so 3× lands on trash and world drops.
  Deliberate — it is loot-while-levelling, not a raid-gear shortcut.
- **Talents +20 at cap 60.** `Rate.Talent = 1.4` multiplies the whole point total and truncates:
  51 → **71** at 60, 61 → **85** at 70, 71 → **99** at 80.

**Decided: full XP regardless of group size.** AutoBalance reduces rewards in scaled-down
instances by default, which would quietly eat the 2× exactly when there are fewer of you.
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

Nothing else in the 18 pinned modules touches XP: every `.cpp`/`.h`/`.conf.dist` in the other
sixteen was grepped for `GiveXP` / `RewardKillRewarder` / `Rate.XP` and comes back clean.
`mod-individual-xp` is the one remaining multiplier and it is inert at `DefaultXPRate = 1` until
someone runs `.xp set`.

Two related notes so this actually holds in play:

- Core WoW already splits kill XP across the party, so a 3-man group earns *more* per head than
  a 5-man does. Nothing to configure — smaller groups are already favoured, and this split is
  exactly the "what 3 players would earn" baseline the 2× multiplies.
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

**Runner sizing: already settled by the repo being public.** The free 4 vCPU / 16 GB runner is the
*public*-repo tier; a private repo gets 2 vCPU / 8 GB. `bunnies-inc/wowserver` is public, so we get
the 4-core runner and unmetered minutes without splitting `build/` out into a second repo — that
option is off the table, and everything stays in one tree. The constraint that *doesn't* scale
with tier is disk: ~14 GB either way, shared with the preinstalled toolchain image, which is the
real ceiling on a cold build. Details in [docs/hosting.md](docs/hosting.md).

The repo being public also means the GHCR package needs its own decision: a package inherits the
repo's *permissions* but **not** its *visibility*, so a public repo still publishes a private
image by default. Either flip the package to public too, or keep a `read:packages` token on the
VPS ([docs/hosting.md](docs/hosting.md) §3.6). Nothing secret is in the image — but nothing
secret is in the repo either, and `.env` stays gitignored regardless.

## Repo layout

```
wowserver/                        # github.com/bunnies-inc/wowserver, public
├── README.md
├── .env                          # Hetzner API token. gitignored. Keep it that way
├── docs/                         # the five planning docs linked at the top
├── build/
│   ├── Dockerfile                # core fork + modules, compiled. CORE_REPO/CORE_SHA live here
│   └── modules.txt               # pinned module repos + refs + commit SHAs
├── deploy/                       # lives at /srv/wow/wowserver/deploy on the VPS
│   ├── docker-compose.yml        # worldserver, authserver, mysql — restart: on-failure,
│   ├── .env.example              #   NOT always. AC exits 0 on `.server shutdown`
│   ├── mysql-init/               # CREATE DATABASE + GRANT for the four schemas
│   ├── mysql.cnf                 # innodb_buffer_pool_size etc. for a shared 8 GB box
│   └── mysql-backup.cnf          # 0600, gitignored, generated by backup.sh
├── conf/
│   ├── worldserver.conf          # phase-1 values; §1 of server-config.md is the source
│   ├── authserver.conf
│   └── modules/                  # playerbots.conf, AutoBalance.conf, SoloLfg.conf,
│                                 #   mod-rdf-expansion.conf, mod_ahbot.conf,
│                                 #   mod_assistant.conf, individual_xp.conf, ...
├── sql/                          # realmlist address, accounts, any custom data
├── scripts/
│   ├── bootstrap.sh              # provision: docker, tailscale, swap, ufw
│   ├── phase.sh                  # flip 1→2→3: rewrite conf keys, graceful restart
│   ├── backup.sh                 # mysqldump auth + characters + playerbots, offsite
│   ├── restore.sh
│   ├── soap-cmd.sh               # run a server command over SOAP (no worldserver-cli exists)
│   └── health.sh                 # RSS / grid-creep watch, feeds the weekly restart call
└── .github/
    └── workflows/
        └── build.yml             # builds the image on the 4-core public-repo runner, pushes GHCR
```

Pin module commits in `modules.txt`. AzerothCore modules break against each other constantly
and "it worked last Tuesday" is not a recoverable state without pins.

Note the backup scope: **Playerbots adds a fourth database**, `acore_playerbots`, on top of
`acore_auth` / `acore_characters` / `acore_world`. Three of those need backing up —
`acore_world` is reproducible from the importer, the other three are not.

## Suggested order of work

1. ~~Decide bots + host.~~ Done — Playerbots, Hetzner CX33 Falkenstein. Everything downstream
   depended on these two and they are now fixed.
2. Stand it up locally on k3v1n: core fork + MySQL + prebuilt client data, no modules. Log in.
3. Add AutoBalance + the bot module. Get a 3-man dungeon feeling right before adding anything else.
4. Layer in Tier-1 QoL modules one at a time, rebuilding between each.
5. Move to the VPS: Dockerfile, CI build, compose, Tailscale, backups.
6. Set phase 1 conf, hand out clients + addon pack, play.
7. Flip phases when you're bored of the current one.

## Settled

- **Core:** AzerothCore, via the `mod-playerbots/azerothcore-wotlk` fork on branch `Playerbot`.
- **Bots:** Playerbots. This is what fixes the base repo.
- **Gating:** level cap only. `MaxPlayerLevel` 60 → 70 → 80, three phases, `Expansion = 2`
  throughout. All races and classes on from phase 1.
- **XP:** 2×, full rate regardless of group size.
- **Reputation:** 10× (`Rate.Reputation.Gain`; the LowLevel keys stay at 1).
- **Loot:** 3× on every quality tier and on money. Trash and world drops, mostly.
- **Talents:** `Rate.Talent = 1.4` — 71 points at 60, 85 at 70, 99 at 80.

## Where this actually stands

- **Host: bought and running.** Hetzner CX33 `debian-8gb-fsn1-1` — 4 vCPU / 8 GB / 80 GB, Debian
  13, **Falkenstein**, `167.233.128.19`. €8.49/mo ex-VAT. The region question is answered; the DO
  comparison above is kept for the reasoning, not as a live option.
- **Nothing is deployed to it yet.** Everything in this repo is local artifacts. Bring-up is
  [docs/bring-up.md](docs/bring-up.md).
- **Repo: public**, at `github.com/bunnies-inc/wowserver`. That settles the CI runner question —
  4 vCPU / 16 GB, unmetered, no need to split `build/` out. The GHCR *package* visibility is a
  separate switch and still needs deciding at first push; see
  [Build and deploy topology](#build-and-deploy-topology).
- **`.env` holds a live Hetzner API token.** It is gitignored and must stay that way. Never commit
  it, never paste it into a doc.

Still open, and genuinely open rather than rhetorical:

- **Does the first couple of weeks happen on k3v1n over Tailscale?** The argument for it is
  unchanged — rebuilds are constant while modules are being added, and the VPS is a slow place to
  iterate. The box is already paid for either way.
- **GHCR package public or a `read:packages` token on the VPS?** One command either way; decide it
  when the first image pushes.
