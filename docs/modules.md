# Module shortlist

Every repo below was resolved against the GitHub API on **2026-08-07/08** (existence, default
branch, last push, archived flag, and the actual `conf/*.conf.dist` filenames). Nothing here is
from memory. Anything I could not confirm is in [§7](#7-unverified--worth-searching-for) and is
not recommended.

Core decisions live in [../README.md](../README.md). Tuning values live in
[server-config.md](server-config.md). This file is *which* modules, not *what values*.

Source of truth for "does this module exist": the azerothcore.org catalogue is generated from the
GitHub topic `azerothcore-module` (324 repos as of 2026-08-07) plus the `azerothcore` org itself.
You can regenerate the list yourself:

```bash
gh api -X GET search/repositories -f q='topic:azerothcore-module' -f per_page=100 -f page=1 \
  --jq '.items[] | [.full_name, .stargazers_count, .pushed_at, .archived] | @tsv'
gh api --paginate '/orgs/azerothcore/repos?per_page=100' --jq '.[].name' | grep '^mod-'
```

---

## 1. Tier 1 — the server does not meet its brief without these

### 1.1 The base you build against

| Repo | Branch | Note |
|---|---|---|
| [`mod-playerbots/azerothcore-wotlk`](https://github.com/mod-playerbots/azerothcore-wotlk) | `Playerbot` (default) | The core. Upstream AzerothCore **will not work** — the module README says so explicitly. |
| [`mod-playerbots/mod-playerbots`](https://github.com/mod-playerbots/mod-playerbots) | `master` (default) | 914★, pushed daily. A `test-staging` branch exists; don't use it. |

The org has exactly two repos. If you find a third "playerbots" anywhere, it's stale — see
[§4](#4-explicitly-skip-and-why).

Fork drift, measured 2026-08-08:

```bash
gh api "repos/azerothcore/azerothcore-wotlk/compare/master...mod-playerbots:azerothcore-wotlk:Playerbot" \
  --jq '[.status, .ahead_by, .behind_by]'
# ["diverged", 575, 88]
```

88 commits behind upstream `master`. That number *is* the compatibility risk for every other
module on this page. The playerbots Installation Guide states it plainly:

> The playerbots AzerothCore fork may lag behind the latest upstream AzerothCore. Modules that
> target the very latest AC version may fail to compile. In this case, find an older
> commit/release of the module that is compatible.

That is the whole argument for [§6 Pinning](#6-pinning).

### 1.2 Scaling

**[`azerothcore/mod-autobalance`](https://github.com/azerothcore/mod-autobalance)** — scales
instance creature health/mana/damage by the number of players inside.

- *Why here:* it is the only reason "3 friends solo a 5-man" and "5 people clear Karazhan" work.
  Playerbots count as players, so bots correctly raise the effective party size.
- *Gotcha:* the README carries a **beta warning on `master`** and points at a `stable` tag:
  `refs/tags/stable` → `5d2778e301ae7684051cdc446efbe81c7ff2a79b`. Current `master` HEAD is
  `73d4ad3c` (2026-01-16). Pin one of the two deliberately; do not track the branch.
- *Prereq:* AC commit `f127e583` or newer (README). Landed upstream 2023-10-08 and confirmed an
  ancestor of the fork's `Playerbot` branch — [§5.2.1](#521-checking-a-minimum-core-commit-properly)
  for the check, which is *not* "the fork is ahead".
- *Config interaction, the important one:* `AutoBalance.RewardScaling.XP` defaults to `1`, which
  shrinks XP in scaled-down instances and silently eats your `Rate.XP.Kill = 1.5`. Set it to `0`.
- *Live tuning without a restart:* `.ab mapstat`, `.ab creaturestat`, `.ab setoffset`,
  `.ab getoffset`, and `.reload config` (all verified in the README's command table). `.ab setoffset`
  is the "tonight feels too hard" knob — no rebuild, no restart.

### 1.3 Small-group dungeon finder, and RDF that survives the level cap

Two modules, two different halves of the same problem. Take both.

#### Who may queue

**[`azerothcore/mod-solo-lfg`](https://github.com/azerothcore/mod-solo-lfg)** — lets RDF queue with
1–4 players instead of a full 5.

**Correction to prior notes: this no longer patches the core.** Both patch files came *out* of the
repo, and neither has been replaced. `lfg-solo.patch` was deleted in commit
[`6bd97792`](https://github.com/azerothcore/mod-solo-lfg/commit/6bd97792) (2022-02-27,
*"fix(cpp): Remove Need for Patch Using New Hook in AC"* — the hook made it unnecessary), and the
last patch-shaped file in the tree, `docker.patch`, was deleted in
[`9b0ad73b`](https://github.com/azerothcore/mod-solo-lfg/commit/9b0ad73b) (2023-06-18,
*"chore: remove docker.patch"*). The repo tree today is `src/LFG_loader.cpp`, `src/Lfg_Solo.cpp`,
`conf/SoloLfg.conf.dist` — no `.patch` or `.diff` anywhere. It is a drop-in module. Any guide
telling you to apply `lfg-solo.patch` is describing the pre-2022 version.

Full config surface (that's all of it):

```ini
# SoloLfg.conf
SoloLFG.Enable      = 1
SoloLFG.Announce    = 1
SoloLFG.FixedXP     = 1     # <-- see below
SoloLFG.FixedXPRate = 0.2   # "the same XP gained in a full party of 5"
```

*Gotcha:* `SoloLFG.FixedXP = 1` pins dungeon XP to `0.2`. Stacked on AutoBalance's own XP scaling
you have **two** modules quietly reducing the XP you set to 1.5×. Decide which one owns dungeon XP
and neutralise the other. Last commit is `3821fe1d` (2025-02-27) — low churn, safe to pin and forget.

#### Which dungeon list the queue resolves to

**[`azerothcore/mod-rdf-expansion`](https://github.com/azerothcore/mod-rdf-expansion)** — **required
in phases 1 and 2.** This was previously parked in [§7](#7-unverified--worth-searching-for) as
unverified. That was wrong; [server-config.md](server-config.md) was right, and the correction is
below.

The problem is a **client** limitation, and the module's README documents it with screenshots: up to
character level 58 the 3.3.5a Dungeon Finder offers *"Random Classic Dungeon"*; at level 59 that
entry disappears and the client will only offer *"Random Burning Crusade Dungeon"*. The server
cannot talk the client out of it. So on a phase-1 server capped at 60, **RDF is dead from 59
onward** — the last two levels, exactly where a 3-person group most wants a queue that fills itself,
have no random dungeon at all. Same shape at 69 in phase 2. Phase 3 is unaffected (WotLK is the
client's own default), which is why this is a phase-1/2 module and not a permanent one.

The module rewrites the queue's dungeon ID. Its entire config surface is one key — that is the whole
of `conf/mod-rdf-expansion.conf.dist`, verified 2026-08-08:

```ini
# mod-rdf-expansion.conf
#   2 - WOTLK   (default behaviour)
#   1 - TBC     (a WOTLK RDF queue joins as TBC RDF)
#   0 - Classic (a WOTLK or TBC RDF queue joins as Classic RDF)
RDF.Expansion = 2
```

The per-phase values (0 / 1 / 2) belong to
[server-config.md §1](server-config.md#1-the-three-phases), which moves them in lockstep with
`Expansion`, `MaxPlayerLevel` and the `UPDATE account SET expansion` statement. Do not set them from
here.

- *Prereq, stated verbatim in the README:* "Requires a version of AC with
  [`azerothcore-wotlk` PR #8196](https://github.com/azerothcore/azerothcore-wotlk/pull/8196) or
  higher" — that PR adds the `OnPlayerQueueRandomDungeon()` hook. Merged upstream 2021-10-02 as
  `775c6744`. Confirmed an ancestor of the fork's `Playerbot` branch — the check, and why the old
  "the fork is ahead" argument was not one, is in
  [§5.2.1](#521-checking-a-minimum-core-commit-properly).
- *No overlap with mod-solo-lfg.* Verified at source level, not assumed:
  `src/RdfExpansion.cpp` registers exactly one hook, `OnPlayerQueueRandomDungeon`, and mutates
  `rDungeonId` (LFGDungeons.dbc IDs 258–262). `mod-solo-lfg` uses `OnPlayerLogin`,
  `OnPlayerRewardKillRewarder` and `sLFGMgr->ToggleTesting()`. Different hooks, different layers —
  solo-lfg changes *who may queue*, rdf-expansion changes *what they queue into*. Run both.
- *It does not gate content by itself.* It rewrites the queue's expansion and nothing else. Gating
  is `Expansion` + `account.expansion`; this module only stops the Dungeon Finder from disagreeing
  with them. The earlier worry in §7 — that it might open content you meant to keep shut — is not
  what the code does.
- *Heroics follow.* At `0`, every random queue resolves to Classic (which has no heroic tier — a
  non-issue in phase 1). At `1`, a WotLK heroic queue is rewritten to the TBC heroic list.
- Low churn: HEAD `c7a91c59` (2025-02-22), 17★, no `.patch`/`.diff` in the tree. Pin and forget.

### 1.4 A working economy

Playerbots **do not list on the auction house.** I checked, 2026-08-08: `playerbots.conf.dist` has
802 `AiPlayerbot.*` keys and zero of them mention auctions, and `AuctionHouse` appears in exactly
two source files — `src/Ai/Base/Actions/LootAction.cpp` and
`src/Ai/Base/Actions/QueryItemUsageAction.cpp`. Neither one creates an auction:

- The only `auctionHouse->AddAuction(...)` in the tree is inside `StoreLootAction::AuctionItem()`,
  an old AhBot-style routine that sits in the `/* … */` block spanning lines 259–353 of
  `LootAction.cpp`. Commented out, not called.
- `QueryItemUsageAction.cpp` only spells the label string `"Auctionhouse"` for the `ITEM_USAGE_AH`
  enum. That tag is assigned in `ItemUsageValue.cpp` from the *item template* — `SellPrice > 0`,
  quality ≥ normal, not soulbound — so it is a "this is worth more than vendor price" verdict
  reached without reading the auction house at all. Items tagged `ITEM_USAGE_AH` get handed to
  another bot by `RpgTradeUsefulAction`, never listed.

Bots do *walk to* auctioneers — auctioneers are RPG/travel targets in `TravelMgr`, which is where
the remaining "auction" strings live. They just never post anything. With 3 humans and no AH bot,
the auction house is empty forever and every crafting profession is dead on arrival.

| Repo | Verdict |
|---|---|
| **[`NathanHandley/mod-ah-bot-plus`](https://github.com/NathanHandley/mod-ah-bot-plus)** | **Take this one.** 110★, 1049-line config, all tuning in the conf file with no SQL. |
| [`azerothcore/mod-ah-bot`](https://github.com/azerothcore/mod-ah-bot) | The official one. Works, but quotas live in the `mod_auctionhousebot` DB table rather than the conf. |

Both use the same conf filename (`mod_ahbot.conf.dist`) and overlapping key names. **Install exactly
one.**

Setup for `mod-ah-bot-plus` (from its README, verified against the conf):

```ini
# mod_ahbot.conf
AuctionHouseBot.EnableSeller   = true
AuctionHouseBot.GUIDs          = 0      # <-- character GUID(s) from the characters DB
AuctionHouseBot.ItemsPerCycle  = 150
AuctionHouseBot.Buyer.Enabled  = false  # turn on so player listings actually sell
```

- *Playerbots prereq, stated verbatim in the README:* "If you are using a bot mod (like playerbots),
  then ensure you use regular non-bot characters for your auctionhouse character(s)." Make a
  dedicated human-owned character, grab its GUID, never log into it.
- *Phase-gating hook — this is the good part.* Without it, phase 1 has Frostmourne-tier mats on the
  level-60 auction house. `mod-ah-bot-plus` can restrict listings by level, so the AH respects your
  `MaxPlayerLevel`:

  ```ini
  # phase 1 (cap 60)
  AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled  = true
  AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel = 60
  AuctionHouseBot.ListedItemLevelRestrict.Enabled           = true
  AuctionHouseBot.ListedItemLevelRestrict.MaxItemLevel      = 80   # tune
  ```

  Both blocks take `ExceptionItemIDs` (comma-separated, dash ranges allowed). Bump `MaxLevel` to
  70/80 in `scripts/phase.sh` alongside `MaxPlayerLevel`.
- *Commands:* `.ahbot reload`, `.ahbot empty`, `.ahbot update`. `.ahbot empty` clears bot listings
  only and refunds bids — that's your phase-transition reset button.
- *Patience:* default 150 items/cycle means the AH takes hours to fill. Crank `ItemsPerCycle` for
  the first day, then drop it back.

### 1.5 The friends you don't have

3.3.5a has **11 primary professions plus 3 secondary** (Cooking, First Aid, Fishing) — 14 in total,
and two primaries per character. Three people can hold six primaries between them at absolute best,
and nobody wants to be the designated enchanter.

| Repo | Conf file | Fills the gap for |
|---|---|---|
| [`azerothcore/mod-npc-enchanter`](https://github.com/azerothcore/mod-npc-enchanter) | `npc_enchanter.conf.dist` | No enchanter alt. NPC applies enchants to gear. `Enchanter.Enable = 1`. |
| [`azerothcore/mod-npc-free-professions`](https://github.com/azerothcore/mod-npc-free-professions) | `mod_npc_free_professions.conf.dist` | Grants a profession at `NpcFreeProfessions.GivenCraftLevel` (default `450`) with all recipes. `NpcFreeProfessions.Enable.<Profession>` toggles, one per profession — exactly 14 of them in the conf, the 11 primaries plus Cooking/FirstAid/Fishing. |
| [`noisiver/mod-assistant`](https://github.com/noisiver/mod-assistant) | `mod_assistant.conf.dist` | Everything else, one NPC (entry `9000000`). |

`mod-assistant` earns Tier 1 on breadth — it is five modules in one, and its toggles map onto the
phase model almost exactly:

```ini
Assistant.Heirlooms.Enabled = 1     # alt leveling
Assistant.Glyphs.Enabled    = 1
Assistant.Gems.Enabled      = 1
Assistant.Enchants.Enabled  = 1
Assistant.Elixirs.Enabled   = 1
Assistant.Food.Enabled      = 1
Assistant.Containers.Enabled= 1     # bag space, for free

# profession skill-ups by tier — gate these per phase
Assistant.Professions.Artisan.Enabled     = 1   # 300, vanilla ceiling
Assistant.Professions.Master.Enabled      = 0   # 375, TBC   -> flip in phase 2
Assistant.Professions.GrandMaster.Enabled = 0   # 450, WotLK -> flip in phase 3

# flight paths, already expansion-shaped
Assistant.FlightPaths.Vanilla.RequiredLevel            = 60
Assistant.FlightPaths.BurningCrusade.RequiredLevel     = 70
Assistant.FlightPaths.WrathOfTheLichKing.Enabled       = 0    # flip in phase 3

# raid/heroic lockout reset, for the re-prog attempt
Assistant.Instances.Heroic.Enabled = 1
Assistant.Instances.Raid.Enabled   = 1
```

Note the overlap: `mod-assistant`'s profession tiers and `mod-npc-free-professions`'
`GivenCraftLevel = 450` do the same job by different routes, and `Assistant.Instances.*` overlaps
[`mod-instance-reset`](#raid-lockouts-blocking-a-re-prog-attempt). Pick per gap, not per module.
Author states up front they do not accept most pull requests — treat it as frozen third-party code
and pin it hard.

### 1.6 Loot friction

| Repo | Conf | Why Tier 1 |
|---|---|---|
| [`azerothcore/mod-aoe-loot`](https://github.com/azerothcore/mod-aoe-loot) | `AOELoot.Enable`, `AOELoot.Range = 55.0`, `AOELoot.Group = 1` | AutoBalance-scaled trash dies in packs. Corpse-by-corpse looting with 3 people is the single most-felt papercut. |
| [`noisiver/mod-junk-to-gold`](https://github.com/noisiver/mod-junk-to-gold) | none — `conf/` holds only `conf.sh.dist`, no runtime keys | Auto-sells greys. Listed as a recommended sub-module **on the playerbots wiki**, because ~30 bots otherwise fill their bags with vendor trash. Always-on, zero config. |

Do not also install `TerraByte-tbwps/mod-aoe-loot` (a separate from-scratch reimplementation, 16★).
One AoE loot module.

---

## 2. Tier 2 — strong QoL, grouped by the problem it solves

### Nobody brought the buffs

| Repo | Notes |
|---|---|
| [`azerothcore/mod-npc-buffer`](https://github.com/azerothcore/mod-npc-buffer) | `npc_buffer.conf.dist`. Lower value than on a bot-free server — playerbots do cast their class buffs — but covers the 3-humans-no-bots session. |
| [`sogladev/mod-reset-raid-cooldowns`](https://github.com/sogladev/mod-reset-raid-cooldowns) | Clears Sated/Exhaustion and resets long cooldowns after an encounter. **The highest-value module in Tier 2 for this server.** 3 people wiping on a boss currently wait 10 minutes for Bloodlust and Rebirth. Default spell list `"42650, 2062, 2894, 1122"` (Army, Fire Ele, Fire Ele Totem, Infernal) + category `26`; `EnableForHeroics = 0` by default, `CombatTimeRequiredInSeconds = 30` stops trash-pull abuse. |

### Corpse runs and wipe recovery

| Repo | Notes |
|---|---|
| [`hallgaeuer/mod-quick-respawn`](https://github.com/hallgaeuer/mod-quick-respawn) | Spawns your ghost at the instance portal instead of the graveyard. One key: `QuickRespawn.Enable`. |
| [`Elmegaard/mod-auto-resurrect`](https://github.com/Elmegaard/mod-auto-resurrect) | Auto-res at the instance entrance on release. Overlaps the above; take one. |

`AnchyDev/DungeonRespawn` solves the same thing and is **archived** — don't.

### Raid lockouts blocking a re-prog attempt

Check the built-ins first — you may need no module at all:

```
.instance listbinds
.instance unbind all
```

Both are core GM commands (verified in `src/server/scripts/Commands/cs_instance.cpp`). With 3
friends and one GM account that may be enough.

Also in `worldserver.conf`, and a real trap for a small group grinding attempts:

```ini
AccountInstancesPerHour = 5        # "max amount of different instances player can enter within hour"
Instance.ResetTimeHour  = 4
Instance.IgnoreRaid     = 0        # ignore raid-group requirement when entering instances
```

Five resets an hour is not many when three people are learning a boss. Raise it.

| Repo | Notes |
|---|---|
| [`azerothcore/mod-instance-reset`](https://github.com/azerothcore/mod-instance-reset) | Gossip NPC (entry `300000`) so players reset their own lockouts without a GM. `instanceReset.NormalModeOnly = false` to include heroics/raids; `instanceReset.TransactionType` 0–3 charges nothing / token / gold / both. |

### Bag space, reagents, mailbox archaeology

| Repo | Notes |
|---|---|
| [`ZhengPeiRu21/mod-reagent-bank`](https://github.com/ZhengPeiRu21/mod-reagent-bank) | Deposit-all-reagents NPC. One key: `ReagentBank.Enable`. 36★, pushed 2026-04. |
| [`silviu20092/mod-improved-bank`](https://github.com/silviu20092/mod-improved-bank) | More bank slots/tabs. |
| [`Day36512/mod-reagent-bank-account`](https://github.com/Day36512/mod-reagent-bank-account) | Account-wide reagent bank with profession integration and shopping lists. **Ships a client addon** — everyone has to install it. Heavier; only if the plain reagent bank isn't enough. |

`Assistant.Containers.Enabled = 1` already hands out free bags, so do that before adding a bank module.

### Alt leveling and account-wide progress

Three people re-rolling is guaranteed. Everything here reduces the cost of alt #2.

| Repo | Notes |
|---|---|
| [`azerothcore/mod-account-achievements`](https://github.com/azerothcore/mod-account-achievements) | `mod_achievements.conf.dist`. Achievements shared across the account. |
| [`azerothcore/mod-account-mounts`](https://github.com/azerothcore/mod-account-mounts) | `mod_account_mount.conf.dist`. |
| [`AlsoNotMehh/AccountBound`](https://github.com/AlsoNotMehh/AccountBound) | Achievements, mounts, pets, titles, reputations, professions, friends — configurable, all in one (`AccountBound.conf.dist`). **Supersedes the two above; do not stack them.** 5★ though — small audience, read the diff before you trust it. |
| [`thanhtong89/mod-shared-professions`](https://github.com/thanhtong89/mod-shared-professions) | Account-wide profession skill + recipes, synced on login. Overlaps `AccountBound`. |
| [`azerothcore/mod-npc-talent-template`](https://github.com/azerothcore/mod-npc-talent-template) | NPC that applies a gear + talent template. The "catch my alt up to the group" button. |
| [`azerothcore/mod-skip-dk-starting-area`](https://github.com/azerothcore/mod-skip-dk-starting-area) | Only relevant from phase 3. Skips the Ebon Hold intro on the second and third DK. |
| [`azerothcore/mod-learn-spells`](https://github.com/azerothcore/mod-learn-spells) | Auto-learns rank-ups on level, Cataclysm-style. Kills the every-two-levels trainer trip. Last commit 2025-03-02, dead simple. |
| **[`azerothcore/mod-individual-xp`](https://github.com/azerothcore/mod-individual-xp)** | **In the build — see below.** `conf/individual_xp.conf.dist`, five keys, all `IndividualXp.*`. Per-character XP multiplier driven by `.xp view` / `.xp set #` / `.xp default` / `.xp disable` / `.xp enable`. 27★, `master`, pushed 2026-04-19; tree is `src/` + `conf/` + `data/sql`, no `.patch`. |

`mod-individual-xp` is **not** a take-it-or-leave-it QoL pick. Like `mod-multibot-bridge`, another
file in this set already depends on it:
[server-config.md](server-config.md) treats it as installed — it holds a row in the
canonical *who owns dungeon XP* table, it is the stated answer for a friend who joins two months
late, and it appears in the do-not-do list — so it has to be in [§6](#6-pinning) or that advice is
unfollowable. Installing it changes nothing on its own: it hooks `OnPlayerGiveXP` and multiplies
*on top of* `Rate.XP.*`, and at the recommended `IndividualXp.DefaultXPRate = 1` that multiplier is
1× until somebody runs `.xp set`. The rates, the stacking arithmetic and the phase policy are
[server-config.md §3](server-config.md#who-owns-dungeon-xp)'s; do not set them from here. One thing
that *is* this file's business: it writes to three tables — `individualxp` in characters,
`command` and `acore_string` in world — and its README carries the `DELETE`/`DROP` statements to
run if you ever pull it back out. Removing it is not just deleting a line from `modules.txt`
([§6.3](#63-why-this-matters-more-here-than-on-a-normal-ac-server), point 5).

### Professions and gathering

| Repo | Notes |
|---|---|
| [`thanhtong89/mod-auto-gather`](https://github.com/thanhtong89/mod-auto-gather) | Auto-gathers nearby nodes and shows both node types on the minimap. Aggressive; treat as a phase-3 convenience, not a default. |
| [`pangolp/mod-quest-loot-party`](https://github.com/pangolp/mod-quest-loot-party) | Everyone in the group gets the quest drop off one NPC. `QuestParty.Enable = true`. Removes the classic "we all need 12 of these, kill it 36 times" tax — genuinely large at 3 players. |

### Travel friction

| Repo | Notes |
|---|---|
| [`BytesGalore/mod-no-hearthstone-cooldown`](https://github.com/BytesGalore/mod-no-hearthstone-cooldown) | Hearthstone CD → 0. |
| [`silviu20092/mod-flightmaster-whistle`](https://github.com/silviu20092/mod-flightmaster-whistle) | Summons the nearest flight master. |
| [`azerothcore/mod-pocket-portal`](https://github.com/azerothcore/mod-pocket-portal) | Portable portals — the mage you don't have. |

### Cosmetics people actually keep logging in for

| Repo | Notes |
|---|---|
| [`azerothcore/mod-transmog`](https://github.com/azerothcore/mod-transmog) | 178★, the most-installed AC module. NPC entry `190010` (`.npc add 190010`). Config is `transmog.conf.dist`, ~40 keys, prefix `Transmogrification.*`. |

**Correction on a widely-repeated claim:** mod-transmog does **not** require `EnablePlayerSettings = 1`
or `DBC.EnforceItemAttributes = 0`. Neither string appears in its README, conf, or source. Its only
stated requirements are AzerothCore v1.0.2+ and core commit `b6cb9247`. What *does* need
`EnablePlayerSettings = 1` (verified by code search across the `azerothcore` org):
`mod-bg-auto-queue`, `mod-quest-helper`, `mod-resurrection-scroll`. Both keys are real
`worldserver.conf` settings (`EnablePlayerSettings = 0`, `DBC.EnforceItemAttributes = 1` by default)
— just not transmog's dependency.

If you were upgrading from a pre-`b34bc28e` AzerothCore you'd need to clear `npc_text` IDs
50000/50001 first. You're building fresh, so skip it — the module uses 601083/601084 now.

### Playerbot fleet management

The first four are the sub-modules the **mod-playerbots wiki itself lists**, i.e. the third-party
modules with a documented playerbots blessing. The fifth is not on that page — it is the server half
of an addon that *is*, and it gets its own subsection below.

| Repo | Notes |
|---|---|
| [`DustinHendrickson/mod-player-bot-level-brackets`](https://github.com/DustinHendrickson/mod-player-bot-level-brackets) | Keeps random bots spread evenly across configurable level brackets, moving them between brackets over time. **Directly relevant to phase gating** — in phase 1 you want the bot population sitting under 60, not scattered to 80. |
| [`Yuof/mod-rndbot-sync`](https://github.com/Yuof/mod-rndbot-sync) | Syncs random bots to the highest online player's level/gear/progression. Simpler answer to the same problem, and it tracks your phase automatically. 6★ — small. Choose one of these two, not both. |
| [`Zerathane/mod-token-turnin`](https://github.com/Zerathane/mod-token-turnin) | Bots auto-redeem tier tokens instead of hoarding them. Only matters once raiding starts. |
| [`jrad7/mod-dungeon-clear`](https://github.com/jrad7/mod-dungeon-clear) | Tank bot runs a dungeon start-to-finish autonomously. **Marked EXPERIMENTAL on the wiki.** 55★, pushed 2026-08-08 — active, but not for a stable config. |
| **[`Wishmaster117/mod-multibot-bridge`](https://github.com/Wishmaster117/mod-multibot-bridge)** | **Server half of the MultiBot-Chatless bot-control UI.** Take it if you take the addon — see below. `conf/MultiBotBridge.conf.dist`, one key: `MultiBotBridge.EnableConsoleLogs = 0`. 19★, `main`, pushed 2026-08-07. |

#### Correction: the bot-control UI is *not* addon-only

Earlier notes filed the client-side bot managers under "addons, not server modules", which implied
they cost the build nothing. That is wrong for the one this project actually wants.

**[`Wishmaster117/MultiBot-Chatless`](https://github.com/Wishmaster117/MultiBot-Chatless)** —
recommended in [client.md](client.md) — **requires a server module**,
[`Wishmaster117/mod-multibot-bridge`](https://github.com/Wishmaster117/mod-multibot-bridge). Both
READMEs say so unambiguously (verified 2026-08-08): the addon README carries a
`requires mod-multibot-bridge` badge and lists the module under *Requirements → Server*; the module
README says "Without the addon, this module does nothing visible by itself. Without this module, the
addon cannot use the new bridge-first / mostly chatless UI refresh paths." The addon's server
requirements name [`mod-playerbots/azerothcore-wotlk`](https://github.com/mod-playerbots/azerothcore-wotlk)
`Playerbot` explicitly — it targets this exact fork.

So choosing that addon adds a **C++ module to the build**, a rebuild, and a config file. It is a
line in [§6](#6-pinning) with a SHA like everything else — not a free client-side download.

*Version lockstep is the real cost, not the build minute.* The two halves speak a versioned protocol
and negotiate at connect:

```text
Addon  -> Server: MBOT HELLO~<protocolVersion>
Server -> Addon:  MBOT HELLO_ACK~<protocolVersion>~mod-multibot-bridge
```

with capability flags (`STATE_FRAMING_V1`, `STRATEGY_MUTATION_V1`) layered on top. **Bump the addon
and the module together, or neither.** A mismatch is a protocol failure, not graceful degradation —
the addon's own fallback switch is `MultiBot.allowLegacyChatFallback`, i.e. reverting to the chat
spam the fork exists to remove. Practically: pin the module SHA here, ship the matching addon
revision in the client pack in [client.md](client.md), and treat a bump of either as a bump of both.

The other client-side managers really are addon-only — checked by tree, not assumed; none of them
contains a `src/` or `conf/`, so none of them adds a line to [§6](#6-pinning):

- [`Lichborne-AC/PlayerbotManager`](https://github.com/Lichborne-AC/PlayerbotManager) — 19★, pushed
  2026-07-03, also named on the wiki's addons page. Pure Lua/XML/BLP. Drives bots with normal chat
  commands, so it works against any playerbots fork.
- [`whipowill/wow-addon-playerbots`](https://github.com/whipowill/wow-addon-playerbots) — 73★, a
  chat-command wrapper, last pushed 2023-05-08, *not* on the current wiki list.
- [`azcguy/PlayerbotsPanel`](https://github.com/azcguy/PlayerbotsPanel) — exists, but see
  [§7](#7-unverified--worth-searching-for): its own README says it does not work.

[client.md](client.md) owns the addon decision and reaches the same conclusion; this section exists
only to say what each choice costs the **build**.

---

## 3. Tier 3 — flavour, add when bored

| Repo | One line |
|---|---|
| [`azerothcore/mod-duel-reset`](https://github.com/azerothcore/mod-duel-reset) | Full health/mana/cooldown reset after a duel. |
| [`azerothcore/mod-boss-announcer`](https://github.com/azerothcore/mod-boss-announcer) | Server-wide announce on world boss kills. Nice with 3 people; you'd otherwise never know. |
| [`azerothcore/mod-congrats-on-level`](https://github.com/azerothcore/mod-congrats-on-level) | Rewards at milestone levels. |
| [`azerothcore/mod-fireworks-on-level`](https://github.com/azerothcore/mod-fireworks-on-level) | Fireworks on ding. |
| [`azerothcore/mod-guildhouse`](https://github.com/azerothcore/mod-guildhouse) | Purchasable guild house with vendor/trainer NPCs. A clubhouse for three. |
| [`azerothcore/mod-world-chat`](https://github.com/azerothcore/mod-world-chat) | Global chat channel. Marginal at 3 humans; useful once bots are chatting. |
| [`azerothcore/mod-instanced-worldbosses`](https://github.com/azerothcore/mod-instanced-worldbosses) | World bosses get per-group instances. Removes the "someone else tagged it" problem — nonexistent here, but it also gives lockouts. |
| [`ZhengPeiRu21/mod-challenge-modes`](https://github.com/ZhengPeiRu21/mod-challenge-modes) | Opt-in hardcore/ironman-style self-imposed rules with rewards. 67★. Good phase-1 content stretcher. |
| [`azerothcore/mod-npc-beastmaster`](https://github.com/azerothcore/mod-npc-beastmaster) | Tame any beast from an NPC. |
| [`azerothcore/mod-1v1-arena`](https://github.com/azerothcore/mod-1v1-arena) / [`mod-arena-3v3-solo-queue`](https://github.com/azerothcore/mod-arena-3v3-solo-queue) | Arena that works below a full team. Playerbots can fill. |
| [`azerothcore/mod-cfbg`](https://github.com/azerothcore/mod-cfbg) | Cross-faction battlegrounds. Requires core commit `d40e8946`+; `CFBG.Enable = 1`. |
| [`azerothcore/mod-random-enchants`](https://github.com/azerothcore/mod-random-enchants) | Diablo-style random affixes on drops. Big flavour change; not blizzlike. |
| [`azerothcore/mod-weekend-xp`](https://github.com/azerothcore/mod-weekend-xp) | Bonus XP weekends. Interacts with your flat 1.5× — layered, not replaced. |
| [`azerothcore/mod-ale`](https://github.com/azerothcore/mod-ale) | Lua scripting engine, if you ever want to write server logic without a rebuild. See the Eluna warning in [§4](#4-explicitly-skip-and-why). |
| [`heyitsbench/mod-arac`](https://github.com/heyitsbench/mod-arac) | All Races All Classes. **Not drop-in** — see [§5](#5-compatibility-and-risk). |

---

## 4. Explicitly skip, and why

| Repo | Why not |
|---|---|
| [`azerothcore/mod-solocraft`](https://github.com/azerothcore/mod-solocraft) | **Double-scales with AutoBalance.** Solocraft buffs *the players* by group size; AutoBalance nerfs *the creatures* by group size. Run both and a 3-man dungeon is adjusted twice in your favour and becomes trivial. Pick one axis. AutoBalance is the one with active development, `.ab` diagnostics, and reward scaling. |
| [`NathanHandley/mod-dungeon-scale`](https://github.com/NathanHandley/mod-dungeon-scale) | An AutoBalance fork. Same reason — never two scalers. |
| [`sokie/mod-autobalance-npcbots`](https://github.com/sokie/mod-autobalance-npcbots) | AutoBalance fork for NPCBots. Irrelevant once you pick Playerbots, and last pushed 2023-11-30. |
| [`azerothcore/mod-playerbots`](https://github.com/azerothcore/mod-playerbots) | **Name trap.** This is *not* the module you want. Description: "NOT READY TO BE USED AS MODULE YET", last push 2021-12-28. The live one is `mod-playerbots/mod-playerbots`. |
| [`azerothcore/mod-eluna-lua-engine`](https://github.com/azerothcore/mod-eluna-lua-engine) | **Archived.** Description is literally "DEPRECATED", last push 2022-03-30. Use `azerothcore/mod-ale`, and note ALE has diverged — its README states plainly that ALE "is NOT compatible with the original Eluna project" and Eluna scripts will not run on it. The Eluna-compatible alternative it points at (`ElunaLuaEngine/ElunaAzerothcore`) is a **whole core fork**, which is unusable when you're already on the Playerbot fork. |
| [`azerothcore/mod-anticheat`](https://github.com/azerothcore/mod-anticheat) | Per-movement-packet validation on a box already running 20–40 bot AI ticks, for a server whose entire threat model is three people you know by name. All cost, no benefit. |
| [`azerothcore/mod-multi-client-check`](https://github.com/azerothcore/mod-multi-client-check) | Blocks multiple clients per network. On a 3-person server, multiboxing an alt *is* a feature. |
| [`azerothcore/mod-progression-system`](https://github.com/azerothcore/mod-progression-system) + [`mod-zone-difficulty`](https://github.com/azerothcore/mod-zone-difficulty) | The ChromieCraft system. Its own README shouts: *"SQL files cannot be 'unloaded' once executed… IT WILL LEAD TO DATABASE POLLUTION IF NOT REVERTED PROPERLY. IF YOU DO NOT KNOW HOW TO REVERT CHANGES, RESET YOUR WORLD DATABASE."* Your phase flips are two conf keys and a restart — reversible. This is not. |
| [`ZhengPeiRu21/mod-individual-progression`](https://github.com/ZhengPeiRu21/mod-individual-progression) | Already assessed as Option B in [../README.md](../README.md). Not a bad module — just a much larger commitment than "stop leveling at 60". |
| [`DustinHendrickson/mod-ollama-chat`](https://github.com/DustinHendrickson/mod-ollama-chat), [`Hokken/mod-llm-chatter`](https://github.com/Hokken/mod-llm-chatter), [`deseven/mod-playerbots-characters`](https://github.com/deseven/mod-playerbots-characters) | LLM-driven bot chat. The playerbots wiki's own entry warns "very cpu/gpu intensive". On an 8 GB **CX33** (4 vCPU / 8 GB / 80 GB) that is already tight for playerbots, no. The CX32 named in earlier drafts is no longer orderable — Hetzner announced the CX22/32/42/52 deprecation on 2025-10-16 and stopped taking orders for them on 2026-01-01, replaced by CX23/33/43/53 (Hetzner Cloud API changelog). Sizing and price are [hosting.md](hosting.md)'s call, not this file's. |
| [`TerraByte-tbwps/mod-aoe-loot`](https://github.com/TerraByte-tbwps/mod-aoe-loot) | Fine module, but a second AoE loot implementation. Pick one. |
| `AnchyDev/*` (StatBooster, DungeonRespawn, HardMode, Prestigious, ExtendedXP, Attriboost, RecycledItems, Recache, BreakingNewsOverride) | All **archived**. They show up high in search results because they have stars. Don't build a server on archived C++. |

---

## 5. Compatibility and risk

### 5.1 What "patches the core" actually means here

I checked the git tree of every Tier 1/2 azerothcore-org candidate for `*.patch` / `*.diff`:

```bash
gh api "repos/$R/git/trees/$(gh api repos/$R --jq .default_branch)?recursive=1" \
  --jq '[.tree[].path | select(test("\\.patch$|\\.diff$"))]'
```

**Result: `[]` for all 22 checked** — mod-solo-lfg, mod-rdf-expansion, mod-solocraft, mod-transmog,
mod-ah-bot, mod-instance-reset, mod-learn-spells, mod-individual-xp, mod-npc-enchanter,
mod-npc-free-professions, mod-cfbg, mod-anticheat, mod-aoe-loot, mod-reagent-bank,
mod-junk-to-gold, mod-account-achievements, mod-account-mounts, mod-random-enchants,
mod-skip-dk-starting-area, mod-npc-talent-template, mod-guildhouse, mod-1v1-arena.
`mod-multibot-bridge` is the same shape —
`conf/` + `src/` + CI workflows, nothing else in the tree.

The AzerothCore module hook API absorbed the cases that used to need patches. **Nothing on this
page's Tier 1 or Tier 2 list requires touching core source.** That kills the merge-conflict-with-the-
Playerbot-fork risk almost entirely.

### 5.2 The risk that remains

| Risk class | Modules | Mitigation |
|---|---|---|
| **Fork lag** — module targets an upstream AC API newer than the fork's 88-commit deficit; fails to compile | any module, any time it updates | Pin. When a pin fails to build, walk the module back, not the fork. |
| **Requires a specific minimum core commit** | see the table in [§5.2.1](#521-checking-a-minimum-core-commit-properly) | All seven checked and satisfied. **Check them with `git merge-base`, not with the ahead-count** — §5.2.1. |
| **Client-side artefacts** — needs files distributed to every player | `heyitsbench/mod-arac` (ships `Patch-A.MPQ` **and** replacement server-side DBCs), `Day36512/mod-reagent-bank-account` (addon) | Not a build risk, a *distribution* risk: it becomes part of the client pack in [client.md](client.md), and the server-side DBC replacement collides with the prebuilt `wowgaming/client-data` drop the Dockerfile pulls. ARAC also fights `Expansion = 0` in phase 1, which blocks Blood Elf/Draenei creation outright. |
| **Applies irreversible SQL** | mod-progression-system, mod-individual-progression | Skipped. |
| **Two modules, one job** | AutoBalance vs Solocraft vs mod-dungeon-scale · mod-ah-bot vs mod-ah-bot-plus (same conf filename!) · mod-aoe-loot ×2 · AccountBound vs mod-account-* vs mod-shared-professions · mod-quick-respawn vs mod-auto-resurrect · level-brackets vs rndbot-sync | Install exactly one per row. |
| **XP multiplier stacking** | `Rate.XP.*` × `AutoBalance.RewardScaling.XP` × `SoloLFG.FixedXPRate` × `IndividualXp.DefaultXPRate` × mod-weekend-xp | Three of these silently modify dungeon XP on defaults, and `IndividualXp` multiplies on top of whatever survives the moment anyone runs `.xp set`. Decide the owner; neutralise the rest. Detail in [server-config.md](server-config.md). |
| **Client addon in lockstep with a server module** | `mod-multibot-bridge` ↔ `MultiBot-Chatless` | Versioned `MBOT HELLO~<protocolVersion>` handshake. Bump both or neither; see [§2](#2-tier-2--strong-qol-grouped-by-the-problem-it-solves) and [client.md](client.md). |

#### 5.2.1 Checking a minimum-core-commit properly

**Correction to the previous reasoning.** Earlier drafts justified "all satisfied" with *"the
Playerbot fork is 575 commits ahead of upstream master."* That is a non sequitur. Ahead-count says
nothing about **containment**: the fork is *diverged*, 575 ahead **and 88 behind**, and the risk
lives entirely in those 88. A module that needs an upstream commit landed inside that 88-commit
window is unsatisfiable no matter how far ahead the fork is on its own line of development. Applied
literally, the old rule would greenlight a module requiring last week's upstream commit.

The real test is ancestry:

```bash
# once, locally
git clone https://github.com/mod-playerbots/azerothcore-wotlk.git ac-fork
cd ac-fork
git remote add upstream https://github.com/azerothcore/azerothcore-wotlk.git
git fetch upstream

# then, per required commit:
git merge-base --is-ancestor <sha> Playerbot && echo CONTAINED || echo MISSING
```

Same question without a clone, if you'd rather — `compare` reports `ahead` or `identical` when the
base is an ancestor of the head, and `diverged` or `behind` when it is not:

```bash
gh api "repos/mod-playerbots/azerothcore-wotlk/compare/<sha>...Playerbot" --jq .status
```

Every stated minimum, checked that way on **2026-08-08** against branch `Playerbot`:

| Module | README requires | Full SHA | Landed upstream | Ancestor of `Playerbot`? |
|---|---|---|---|---|
| mod-autobalance | `f127e583` | `f127e583aae3cfa51a77d056c1892a7de07ffb52` | 2023-10-08 | yes |
| mod-transmog | `b6cb9247` | `b6cb9247ba96a862ee274c0765004e6d2e66e9e4` | 2019-03-25 | yes |
| mod-ah-bot | `9adba48` | `9adba482c236f1087d66a672e97a99f763ba74b3` | 2020-02-27 | yes |
| mod-ah-bot-plus | `3f46e05` | `3f46e05d3691895b6b8a5b3832d17ecb1e210791` | 2025-07-27 | yes |
| mod-cfbg | `d40e8946` | `d40e8946180129b39172c2a1b4d690aa71723917` | 2019-08-06 | yes |
| mod-anticheat | `825db0f` | `825db0f8c1fb6d938d0cec88df0447fe7ee5b3b2` | 2022-08-06 | yes |
| **mod-rdf-expansion** | **PR [#8196](https://github.com/azerothcore/azerothcore-wotlk/pull/8196) "or higher"** | merge commit `775c6744d2f6b1ff4a56480ca08d38ac585953e5` | 2021-10-02 | **yes** |

The conclusion the old text reached is still correct — but only because every one of these predates
the fork point, not because of the ahead-count. Note `mod-ah-bot-plus` (2025-07-27) is the close
one: it is the only requirement recent enough that a fork rebase could plausibly have stranded it.
That is the row to re-run first whenever you move the `CORE_SHA` pin, forwards or backwards.

*Use the full SHAs when you re-run this.* GitHub's REST API resolves short prefixes inconsistently —
`f127e58` (7 chars) resolves fine, while `9adba48` and `825db0f` return `422 No commit found` and
`compare` returns `404`, which reads exactly like "the commit isn't in the fork" when it means
nothing of the sort. Both are real; the full SHAs are in the table above. Expand before querying.

### 5.3 Playerbots compatibility, by evidence level

| Confidence | Modules | Evidence |
|---|---|---|
| **Documented compatible** | mod-player-bot-level-brackets, mod-ollama-chat, mod-dungeon-clear, mod-junk-to-gold, mod-token-turnin | Named as sub-modules on the mod-playerbots wiki's *Playerbot Addons and Sub-Modules* page. |
| **Documented interaction** | mod-ah-bot-plus | README: use non-bot characters for `AuctionHouseBot.GUIDs`. |
| **Built against this exact fork** | mod-multibot-bridge | README *Requirements → Server*: "`mod-playerbots` installed and working"; the paired addon's requirements name [`mod-playerbots/azerothcore-wotlk`](https://github.com/mod-playerbots/azerothcore-wotlk) branch `Playerbot` by URL. Reads Playerbot state directly — it is not fork-agnostic. |
| **Designed for playerbots** | mod-rndbot-sync, mod-optimal-bot-raid, mod-world-buff-bots, mod-playerbots-artisans | Repo descriptions say so. All are small (≤6★) — read before trusting. |
| **Untested by me** | everything else on this page | No patches, no core edits, so the only failure mode is a compile error against the fork — which you find in CI in five minutes, not in production. |

The playerbots wiki publishes **no** incompatibility list. Absence of a warning is not a
compatibility guarantee. Add modules one at a time (README step 4), rebuild, log in.

---

## 6. Pinning

`build/modules.txt` is a convention for *this* repo, not an AzerothCore standard — upstream just
tells you to `git clone` into `modules/`. Format: one module per line, `#` comments, three
whitespace-separated fields — **`owner/name`, `ref`, `commit`**.

> **This file is canonical.** The block below *is* `build/modules.txt`, not an excerpt of it, and it
> is the exact set the Dockerfile in [hosting.md §3](hosting.md) reads with
> `COPY modules.txt` + a `while read -r repo ref sha` loop. If a module is on this page but not in
> this block, it is **not** in the image. Earlier drafts showed a partial list here; that was the
> bug. Add a module in exactly one place — here — and rebuild.

### 6.1 `build/modules.txt`

```
# repo                                     ref         commit
# ---------------------------------------- ----------- ----------------------------------------
# The core fork is NOT here; it lives in build/Dockerfile as CORE_REPO/CORE_SHA (see below).
# Three fields, whitespace-separated. `ref` is the branch or tag the commit came from — it is
# documentation for the bump script, not what gets checked out. `commit` is what gets checked out.

# --- Tier 1: the server does not meet its brief without these -------------------------------
mod-playerbots/mod-playerbots               master      a7b885d27134466dbc1c91d39b8241ea725a1bbb
azerothcore/mod-autobalance                 stable      5d2778e301ae7684051cdc446efbe81c7ff2a79b
azerothcore/mod-solo-lfg                    master      3821fe1d108ade8d2b7ad6611e41154e05864c65
azerothcore/mod-rdf-expansion               master      c7a91c5973cda4529495b52b89375913f98726d6
NathanHandley/mod-ah-bot-plus               master      f685832994c825f90aa5a3dc0e1620aa568e875b
azerothcore/mod-npc-enchanter               master      af32add66eafc0e0eb8775999e76ceed75f18b74
azerothcore/mod-npc-free-professions        master      01d8624f9c0789550c0b04b23c54928b054619ce
noisiver/mod-assistant                      master      77505b1a3d561438a13fd3fabfe40676daa7fdfe
azerothcore/mod-aoe-loot                    master      b5c663572d936985c19dc8b499ecea60e1da570d
noisiver/mod-junk-to-gold                   master      2134690bb03899e5c9e44d0682e8e6abf0bbbaf2

# --- Tier 2: selected. One per "two modules, one job" row in §5.2. --------------------------
Wishmaster117/mod-multibot-bridge           main        fa7d19054e64d710c0fec4ada7bef51082f2934d
sogladev/mod-reset-raid-cooldowns           main        fd2391fb8755673270c982846a29bb3bf5648969
azerothcore/mod-instance-reset              master      1e2c20770f40f5382348b7649291371f47c86812
azerothcore/mod-transmog                    master      0d85cbc53d63ce2df8527169ce6ae47f5f6f6ba8
azerothcore/mod-learn-spells                master      016b92d520f343d074ffd5d46016a94f4a3a6ebd
azerothcore/mod-individual-xp               master      503471f766bc4f21dca0aa05e6a9d3d40718a780
DustinHendrickson/mod-player-bot-level-brackets  main   a1780785f386732527de7455aac960f630d29b5d
pangolp/mod-quest-loot-party                master      6f073c1bef1bba1aa73787d1e30db7429f2b1c7b
```

18 modules — 10 Tier 1, 8 Tier 2. SHAs are real HEADs (or, for `mod-autobalance`, the real `stable`
tag) resolved 2026-08-08 and re-checked against their stated `ref` on the same date; regenerate with
the drift script in [§6.2](#62-bumping-a-pin) before the first build.

Why each of the non-obvious ones is in or out:

| Line | Why |
|---|---|
| `mod-rdf-expansion` | Required in phases 1 and 2 — [§1.3](#13-small-group-dungeon-finder-and-rdf-that-survives-the-level-cap). Omitting it is what killed RDF at 59 in the previous list. |
| `mod-npc-free-professions` + `mod-assistant` | Both Tier 1, and they *do* overlap on profession skill-ups. Not a conflict at install time — resolve it in config: let `mod-assistant` own the per-phase Artisan/Master/GrandMaster gate and leave `NpcFreeProfessions.GivenCraftLevel` alone, or vice versa. [§1.5](#15-the-friends-you-dont-have). |
| `mod-multibot-bridge` | Required by the `MultiBot-Chatless` addon that [client.md](client.md) recommends. Not optional once that addon is in the client pack — and it must be bumped in lockstep with it. |
| `mod-player-bot-level-brackets` | Chosen over `Yuof/mod-rndbot-sync`; §5.2 says one per row. Swap the line if you prefer sync-to-highest-player. |
| `mod-individual-xp` | [server-config.md](server-config.md) recommends it in three places — the *who owns dungeon XP* table, the latecomer answer, and the XP-stacking do-not-do row. Leaving it out of the image is what makes that advice unfollowable. Inert at `DefaultXPRate = 1`; see [§2](#alt-leveling-and-account-wide-progress). |
| `mod-transmog`, `mod-learn-spells`, `mod-instance-reset`, `mod-reset-raid-cooldowns`, `mod-quest-loot-party` | Tier 2, but the five with no live alternative on this page and no config conflict. Everything else in Tier 2/3 is a deliberate later addition — one per commit. |
| *not here:* `mod-ah-bot`, `mod-solocraft`, `mod-dungeon-scale`, `TerraByte-tbwps/mod-aoe-loot`, `mod-rndbot-sync`, `AccountBound` | Each collides with a line above. [§4](#4-explicitly-skip-and-why) / §5.2. |

### 6.2 Bumping a pin

The core fork pin belongs in the Dockerfile next to the base image, not in `modules.txt`, because
changing it is a different class of event from bumping a module:

```dockerfile
ARG CORE_REPO=https://github.com/mod-playerbots/azerothcore-wotlk.git
ARG CORE_SHA=092e9ba6ff8dc6d861dddd1f31baa9d404381a85   # branch Playerbot, 2026-08-07
```

Consuming it in the build — this is the loop [hosting.md](hosting.md)'s Dockerfile runs, and it
reads all three fields (`ref` is carried for the bump script below; only `sha` is checked out):

```bash
while read -r repo ref sha; do
  case "$repo" in ''|\#*) continue ;; esac
  name="${repo##*/}"
  git clone --filter=blob:none "https://github.com/$repo.git" "modules/$name"
  git -C "modules/$name" fetch --depth 1 origin "$sha"
  git -C "modules/$name" checkout --detach "$sha"
done < build/modules.txt
```

Refreshing pins deliberately, one module at a time:

```bash
# what would move, and how far
while read -r repo ref sha; do
  case "$repo" in ''|\#*) continue ;; esac
  head=$(gh api "repos/$repo/commits/$ref" --jq .sha)
  [ "$head" = "$sha" ] || printf '%-45s %s -> %s  (%s)\n' "$repo" "${sha:0:8}" "${head:0:8}" \
    "$(gh api "repos/$repo/compare/$sha...$head" --jq '.ahead_by')"
done < build/modules.txt
```

### 6.3 Why this matters more here than on a normal AC server

1. **You are on a fork that is 88 commits behind upstream.** A module's `master` can adopt an
   upstream API on Tuesday and stop compiling against the fork the same day. Floating branches turn
   that into a broken CI run at an arbitrary future time; a pin turns it into a deliberate decision.
2. **You rebuild via GitHub Actions → GHCR → VPS pull.** Every image must be reproducible from the
   repo alone. A floating `master` means the same commit of this repo produces different images on
   different days, and "roll back to yesterday's image" stops meaning anything.
3. **`mod-autobalance` ships a `stable` tag precisely because `master` is flagged beta.** Pinning is
   how you take the maintainer up on that. Be aware this is the one pin materially older than the
   core: `stable` is `5d2778e3` from 2024-09-10, roughly 23 months behind the core commit you're
   building against. That's a real compile risk on a core bump, and it's the reason §5.2's usual
   "walk the module back to an older commit" remedy is backwards *for this row* — there is nothing
   older to walk back to. If `stable` stops compiling, move **forward** to `master` and accept the
   beta flag, or carry a patch. The consolation is that this one fails in CI in five minutes, not
   on the VPS at 2am.
4. **Several Tier 2 picks are single-maintainer repos with ≤20★** (`mod-rndbot-sync`,
   `AccountBound`, `mod-reset-raid-cooldowns`, `mod-quick-respawn`, `mod-multibot-bridge`). A
   force-push or a rename costs you nothing if you pinned the SHA and mirror the tarball; it costs
   you an evening if you didn't. `mod-multibot-bridge` is the live one — 19★, pushed the same day
   this list was resolved.
5. **Module SQL is applied by the auto-updater at startup.** Rolling a module's *code* back without
   rolling its *SQL* back is how you get a half-migrated world DB. Pin, and keep
   `scripts/backup.sh` running before every deploy.
6. **One line has a client-side twin.** `mod-multibot-bridge` and the `MultiBot-Chatless` addon
   negotiate a protocol version at connect. Bumping the pin without reshipping the addon (or the
   reverse) breaks bot control for everyone at once, and it breaks at login, not at build. Bump
   the pair in one commit and note the addon revision in the message —
   [client.md](client.md) carries the client half.

Bump one pin per commit, with the compare URL in the message. When a build breaks you bisect the
modules file, not the universe.

---

## 7. Unverified / worth searching for

Named for completeness. **Do not install from this list without checking it yourself** — I could not
confirm quality, playerbots compatibility, or in some cases anything beyond existence.

Two entries have left this list since the first draft, both because a claim here turned out to be
wrong rather than merely unchecked. `azerothcore/mod-rdf-expansion` is now **Tier 1** — see
[§1.3](#13-small-group-dungeon-finder-and-rdf-that-survives-the-level-cap); the worry that it might
open gated content is not what the code does. `PlayerbotsPanel` was listed as *not existing*; it
does, and the row below now says so.

| Repo | Why it's here, not above |
|---|---|
| [`Moloch17/mod-auctionsim`](https://github.com/Moloch17/mod-auctionsim) | "Auction House Simulator". Exists (4★, 2026-06-09). A simulated *market* rather than a listing bot would be strictly better for 3 players, but 4★ and no docs I could evaluate. Third AH module — would collide with the other two. |
| [`silviu20092/mod-mythic-plus`](https://github.com/silviu20092/mod-mythic-plus), [`araxiaonline/mod-mythic-plus`](https://github.com/araxiaonline/mod-mythic-plus), [`Old-Man-Warcraft/mod-mythic-enhanced`](https://github.com/Old-Man-Warcraft/mod-mythic-enhanced) | Three unrelated M+ implementations, all real. Excellent *concept* for endgame with 3 people (infinite scaling content), but none verified against AutoBalance — and two scalers is the [§4](#4-explicitly-skip-and-why) trap. Needs its own evaluation. |
| [`InstanceForge/mod-dungeon-master`](https://github.com/InstanceForge/mod-dungeon-master) | Randomly generated dungeons, 47★, active. Interesting for content longevity; unevaluated. |
| [`forumcorex/mod-missing-objectives`](https://github.com/forumcorex/mod-missing-objectives) | Adds missing dungeon/raid objectives. Plausibly useful, unevaluated. |
| [`azcguy/PlayerbotsPanel`](https://github.com/azcguy/PlayerbotsPanel) | **Correction: it exists.** An earlier draft of this section said no repo could be found and told you to treat it as nonexistent — wrong. Verified 2026-08-08: HTTP 200, 16★, branch `main`, not archived, last push 2024-06-13. It is a *client addon*, not a server module, which is why it isn't in [§6](#6-pinning). Still do not install it: its own README opens **"EARLY ALPHA - DOESNT WORK AND DONT REPORT BUGS"**, it needs a second addon (`azcguy/PlayerbotsBroker`, 0★, also last pushed 2024-06-13), and development stalled two years ago against a communication *emulator* rather than a live server. Its README points at `liyunfan1223/mod-playerbots` — that is **not** a different fork, it 301-redirects to `mod-playerbots/mod-playerbots`, the repo in [§1.1](#11-the-base-you-build-against); the old owner name simply predates the org move. [client.md](client.md) reaches the same verdict and owns the addon call. |
| `mod-solo-lfg` alternatives | Nothing found. `mod-solo-lfg` is the only small-group RDF module in the catalogue. |
