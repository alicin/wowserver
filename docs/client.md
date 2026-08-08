# Client setup and the addon pack

Everything on the player's machine. Server side lives in [../README.md](../README.md),
[hosting.md](hosting.md), [server-config.md](server-config.md) and [modules.md](modules.md).

Target: **WoW 3.3.5a, build 12340, enUS**. Anything else does not connect — AzerothCore's
`acore_auth.realmlist.gamebuild` defaults to `12340` and the authserver rejects mismatched builds.

---

## 1. Getting a client

AzerothCore does not distribute a client, and says so in its own docs: *"AzerothCore does not
distribute a client. You will need to find your own clean 3.3.5a client on the internet."*
([wiki/docs/client-setup.md](https://github.com/azerothcore/wiki/blob/master/docs/client-setup.md))

ChromieCraft hosts the cleanest widely-mirrored one. Verified live:

| Item | Value |
|---|---|
| Page | <https://www.chromiecraft.com/en/downloads/> |
| Direct | `https://btground.dedyn.io/chmi/ChromieCraft_3.3.5a.zip` (302 → `chmi.btground.dedyn.io`) |
| Torrent | `https://btground.dedyn.io/chmi/ChromieCraft_3.3.5a.zip.torrent` · [magnet](magnet:?xt=urn:btih:2ba2833baf733ce0a16040d43ed09491f2bf2ab2) |
| Mirrors | MEGA `https://mega.nz/file/gs4kjBRD#CdoujnfW3cvR_uy3K_uco0HELKQ2RtbtK_LZLyuGF8Y` · `https://usefulness.altervista.org/WoW/ChromieCraft_3.3.5a.zip.torrent` |
| **Size** | **17,674,749,792 bytes = 16.5 GiB** (exact, from the torrent metainfo `length`) |
| Contents | clean 3.3.5a, ChromieCraft realmlist pre-set — you overwrite it |

Use the torrent. 16.5 GiB × 3 friends off one HTTP mirror is rude, and the torrent has seeders.

### Verifying you actually have 12340

Three independent checks, cheapest first:

```bash
# 1. Login screen, bottom-left corner. Must read exactly:  3.3.5a (12340)

# 2. Binary size/hash of the retail Wow.exe (12340, enUS).
#    Any custom launcher or a patched exe changes this — see awesome_wotlk in §5.
sha1sum Wow.exe

# 3. Ask the server. Build mismatch shows as "Unable to connect" AFTER a successful
#    auth handshake, not at the realm list. Grep authserver:
#    "Unknown Client Build" / rejected build in authserver.log
```

The realmlist `gamebuild` column is the server-side authority; the AzerothCore wiki's build table
lists `12340 → 3.3.5a`, `11723 → 3.3.3a`, `10505 → 3.2.2a`. If a friend downloaded a "WotLK client"
from somewhere else and it says 3.3.3, it will not work and no config fixes it.

---

## 2. Pointing it at the server

Two halves. Both must agree.

### Client side

```
<WoW>/Data/enUS/realmlist.wtf        # one line
```

```
set realmlist wow.example.com
```

Notes that actually bite:

- The path is locale-scoped: `Data/enUS/realmlist.wtf` on an enUS client, `Data/enGB/` on enGB.
  If you have both directories you have a mixed install; delete the one you don't use.
- **Never `localhost`.** AzerothCore's docs call this out explicitly — use `127.0.0.1`. The 3.3.5a
  client's resolver does not handle it reliably.
- `WTF/Config.wtf` also carries a `SET realmList "..."` line, written by the client. When the two
  disagree you get the classic "I changed realmlist.wtf and it still connects to the old server".
  Set both, or delete the `Config.wtf` line and let `realmlist.wtf` seed it. *(Which file wins on a
  given launch is reported inconsistently across community sources — setting both removes the
  question. (verify) if you care about the precise precedence.)*
- Make it read-only so nothing rewrites it:

```bash
chmod 444 "Data/enUS/realmlist.wtf"
```

  The stock `Launcher.exe` rewrites `realmlist.wtf` from its patchlist server. Don't use
  `Launcher.exe` at all — run `Wow.exe` directly. (If you insist, the AC wiki says you must also
  point `set patchlist` at your own host.)
- Do **not** make the whole `WTF/` directory read-only. The client writes settings, keybinds and
  SavedVariables there and will silently reset them every launch.

### Server side

The other half is the `acore_auth.realmlist` row. **[hosting.md](hosting.md) §5.2 owns it** and
carries the single canonical `UPDATE`, including how `address` / `localAddress` /
`localSubnetMask` behave behind Tailscale. Do not set those columns from this doc — the symptom of
getting them wrong is client-side (authenticates fine, then hangs forever at *Logging in to game
server*) but the entire fix is in that table.

One thing worth knowing on this side of the fence: **no realmlist change needs an authserver
restart.** `RealmList::UpdateRealms()` re-runs

```sql
SELECT id, name, address, localAddress, localSubnetMask, port, icon, flag, timezone,
       allowedSecurityLevel, population, gamebuild
FROM realmlist WHERE flag <> 3
```

every `RealmsStateUpdateDelay` seconds (`authserver.conf`, default **20**), and re-resolves
`address` through the DNS resolver on each pass — so a hostname change, a port change and an
`allowedSecurityLevel` change all take effect inside ~20 s. Verified in
[`RealmList.cpp`](https://github.com/azerothcore/azerothcore-wotlk/blob/master/src/server/shared/Realms/RealmList.cpp)
and the `LOGIN_SEL_REALMLIST` prepared statement in
[`LoginDatabase.cpp`](https://github.com/azerothcore/azerothcore-wotlk/blob/master/src/server/database/Database/Implementation/LoginDatabase.cpp).
Note specifically that `allowedSecurityLevel` is **not** an exception to this — it is column 10 of
that same refresh query, re-read on exactly the same tick as `flag` and `address`.

Corollary of the `WHERE flag <> 3`: `flag = 3` is `REALM_FLAG_VERSION_MISMATCH | REALM_FLAG_OFFLINE`
(`Realm.h`), and the refresh query filters those rows out, so such a realm **disappears from the
realm list entirely** rather than showing as offline. If your realm vanishes instead of greying out,
look at `flag`.

---

## 3. Running the client on Linux (Arch + Hyprland)

### The thing that invalidates every old guide

Since **wine 10.8-2 (Arch news, 2025-06-16)** Arch's `wine` and `wine-staging` are **pure WoW64
builds**. Confirmed on this machine — `/usr/lib/wine/` contains `i386-windows`, `x86_64-unix`,
`x86_64-windows` and **no `i386-unix`**. Consequences:

| Consequence | What to do |
|---|---|
| `WINEARCH=win32` prefixes no longer work | Create a **win64** prefix. WoW is a 32-bit PE and runs fine inside it. |
| Existing 32-bit prefixes are broken | Recreate them. Arch's news item says so verbatim. |
| **32-bit apps using OpenGL directly are slower** — a documented WoW64 limitation | So `SET gxApi "opengl"` — the advice in essentially every 3.3.5-on-Linux guide written before 2025 — is now the *wrong* choice on Arch. Use **d3d9 + DXVK**. |
| A few 32-bit apps just break | Escape hatch: `wine32` (AUR) or `wine-stable` (AUR), which still ship real 32-bit builds. |

### Packages

```bash
sudo pacman -S wine wine-mono winetricks lutris gamemode lib32-gamemode
# GPU-specific 32-bit Vulkan ICD — WoW is 32-bit, so the lib32 driver is not optional:
sudo pacman -S lib32-vulkan-radeon      # AMD
sudo pacman -S lib32-vulkan-intel       # Intel
sudo pacman -S lib32-nvidia-utils       # NVIDIA
vulkaninfo --summary | head             # sanity check before blaming Wine
```

### Prefix + DXVK

DXVK's `setup_dxvk.sh` **was removed in DXVK 2.1**. Guides that still say `./setup_dxvk.sh install`
(including the widely-linked [sebyx07 gist](https://gist.github.com/sebyx07/e14b8d64e85e13162db3748ea20caea2))
are stale. Copy the DLLs yourself. Verified: `dxvk-3.0.2.tar.gz` still ships `x32/d3d9.dll`.

```bash
export WINEPREFIX="$HOME/.local/share/wineprefixes/wow335"
WINEARCH=win64 wineboot -u                       # win64 — see above

V=3.0.2
curl -LO "https://github.com/doitsujin/dxvk/releases/download/v$V/dxvk-$V.tar.gz"
tar xf "dxvk-$V.tar.gz"
# 32-bit PE DLLs go in syswow64 even in a pure-WoW64 prefix
cp "dxvk-$V/x32/d3d9.dll" "$WINEPREFIX/drive_c/windows/syswow64/d3d9.dll"
wine reg add 'HKCU\Software\Wine\DllOverrides' /v d3d9 /d native,builtin /f
```

WoW 3.3.5a only ever calls d3d9 — you do not need `d3d11`, `dxgi` or `d3d10core`.
Alternative if you'd rather not hand-manage it: `WINEPREFIX=... winetricks dxvk`.

### Launcher

```bash
#!/usr/bin/env bash
# ~/.local/bin/wow335
set -euo pipefail
export WINEPREFIX="$HOME/.local/share/wineprefixes/wow335"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="d3d9=n,b"

# Wow.exe is a 2008 32-bit binary WITHOUT the LARGE_ADDRESS_AWARE flag -> 2 GB user
# address space. HD MPQ patches + 30 addons will hit that ceiling and die with
# "ERROR #132 (0x85100084) Fatal exception". This env var makes Wine lift it.
export WINE_LARGE_ADDRESS_AWARE=1

export DXVK_STATE_CACHE_PATH="$WINEPREFIX/dxvk-cache"
# export DXVK_HUD=fps,version     # uncomment to confirm DXVK is actually loaded

cd "$HOME/Games/wow-3.3.5a"
exec gamemoderun wine Wow.exe "$@"
```

If `DXVK_HUD=fps` shows nothing, DXVK is not loaded and you are on Wine's builtin
wined3d — check the override and the `lib32-vulkan-*` package.

### Config.wtf

`Config.wtf` is only read at launch and rewritten at exit, so edit it with the game closed.

```
SET gxApi "d3d9"          # d3d9 -> DXVK -> Vulkan. NOT opengl on WoW64 Arch.
SET gxWindow "1"          # windowed; let Hyprland do fullscreen
SET gxMaximize "1"        # borderless-maximised
SET hwDetect "0"          # stop the client re-detecting and stomping your settings
SET hwCursor "0"          # hardware cursor causes stutter/FPS drops; documented on
                          # Win10 too, and it is worse under XWayland
SET gxRefresh "60"
SET readTOS "1"
SET readEULA "1"
SET scriptErrors "1"      # you will want this while installing addons
```

### Wayland / Hyprland

Wine 11.14 ships `winewayland.drv` but the **Wayland driver is not the default** — Wine still
picks X11 (i.e. XWayland) unless you set `HKCU\Software\Wine\Drivers` → `Graphics`. Leave it on
XWayland. The native Wayland driver is still marked experimental, and community reports put the
Wine-Wayland cursor bugs specifically on the *native* driver rather than XWayland/gamescope.

Exclusive fullscreen under a Wayland compositor is the known pain point — Hyprland has open issues
for [misaligned cursors when a game changes resolution](https://github.com/hyprwm/Hyprland/issues/2866)
and [mouse not locking in Wine/Proton](https://github.com/hyprwm/Hyprland/issues/2376). Sidestep it:

```
SET gxWindow "1"
SET gxMaximize "1"
```

then let Hyprland make the window fullscreen. The client never changes the display mode, so nothing
desyncs. Set the in-game resolution to your monitor's native resolution so there is no scaling.

If you still get a drifting cursor or Alt-Tab breaking mouselook, wrap it in gamescope
(`gamescope -f -W 2560 -H 1440 -- wine Wow.exe`) — but note gamescope-nested-under-Hyprland has
its own open issues ([#5076](https://github.com/hyprwm/Hyprland/issues/5076),
[gamescope#2002](https://github.com/ValveSoftware/gamescope/issues/2002)). Windowed-maximised first.

### Other 3.3.5-on-Wine pitfalls

| Symptom | Cause / fix |
|---|---|
| Black screen at launch, no error | Stale cache. `rm -rf Cache/` in the game dir. |
| Launcher.exe does nothing | Don't use it. Run `Wow.exe`. It also rewrites `realmlist.wtf`. |
| No sound | `winetricks sound=pulse` in the prefix. |
| ERROR #132 after adding HD patches | 2 GB address space. `WINE_LARGE_ADDRESS_AWARE=1`, or drop `Patch-H.MPQ`. |
| Settings reset every launch | `hwDetect` back to 1, or you made `WTF/` read-only. |
| Cursor lags but FPS is fine (or vice versa) | Hardware cursor. `SET hwCursor "0"`. |
| Fine on Windows, terrible here | You're on `gxApi "opengl"` under WoW64 wine. Switch to d3d9+DXVK. |

Lutris works too and gives per-game prefix/DXVK management, but there is no maintained
"WoW 3.3.5a" installer script worth trusting over the 12 lines above.

---

## 4. Optional graphics patches

### How `patch-N.MPQ` works

The 3.3.5a client scans `Data/` at startup and loads every `patch-*.MPQ` it finds, **numerics 1–9
first, then letters A–Z**, later files overriding earlier ones. Retail ships `patch.MPQ`,
`patch-2.MPQ`, `patch-3.MPQ`, so custom content starts at `patch-4` and by convention uses letters.
Locale-specific overrides (interface, DBC, sound) go in `Data/enUS/patch-enUS-N.MPQ`; global assets
(models, textures, maps) go in `Data/`.

There is no client-side signature check on `patch-*.MPQ`, which is exactly why this works — but see
the DBC caveat below.

### ChromieCraft's HD pack

`https://btground.dedyn.io/chmi/additional_patches_for_335a.zip` — **3,397,498,676 bytes (3.16 GiB)**.
Verified contents and the bundled `readme.txt`:

| File | Uncompressed | Content | Author |
|---|---|---|---|
| `Patch-H.MPQ` | 2152.7 MB | Characters, WoD-model NPCs, goblin textures | Leeviathan |
| `Patch-F.MPQ` | 824.7 MB | Mounts and creatures | Finsternis |
| `Patch-G.MPQ` | 10.0 MB | Mounts and creatures (cont.) | Finsternis |
| `Patch-T.MPQ` | 418.6 MB | Environment and city textures | Nicolas |
| `Patch-S.MPQ` | 2.1 MB | Better sunlight effect | Nicolas |
| `Patch-X.MPQ` | 1.9 MB | Cata trees | Leeviathan |

Install = copy the `Patch-*.MPQ` files into `Data/`. Remove a file to remove the mod.

**Conflict, straight from the pack's own readme:** *"Patch-X.MPQ is in conflict with Patch-T.MPQ.
It overwrites trees textures with lower resolution ones. If you want to use Patch-T.MPQ please
remove Patch-X.MPQ."* Pick one.

ChromieCraft also links an "Alternative HD Patch" — a whole pre-patched client with a
`patchmenu.exe` toggler, hosted on
[Google Drive](https://drive.google.com/drive/folders/1RmWFmyFKWNDyXvpGdaboB8ytwosy25C1). Heavier,
and it means a second 15 GB download instead of a 3 GB add-on. Skip it.

### Caveats that matter for a private server

- **These are cosmetic-only, and that is what makes them safe.** Models and textures live purely
  client-side. A patch that replaces a `.dbc` the *server also reads* (`Spell.dbc`, `Item.dbc`,
  `ChrRaces.dbc`, …) desyncs you from AzerothCore's own DBC data — that's a modding project, not a
  texture pack. None of the six files above do this. Anything you add later, check.
- **All three friends do not need the same patches.** Because it's cosmetic, mismatched HD packs are
  invisible to everyone else. Don't make it part of the mandatory setup.
- Memory. `Patch-H.MPQ` alone is 2.1 GB of assets against a 2 GB address space. This is the single
  most common cause of ERROR #132 on a modded 3.3.5a client — see `WINE_LARGE_ADDRESS_AWARE` above.
- ChromieCraft's own disclaimer: *"these patches are not official and, while they have proven to
  work fine in most cases, they sometimes might lead to minor glitches or Errors."*

---

## 5. The addon pack

All sources below were checked against the GitHub API — repo exists, not archived, last-push date
noted where it matters. Anything I could not confirm is marked.

### Where the mirrors are

| Collection | What it actually is |
|---|---|
| [NoM0Re/WoW-3.3.5a-Addons](https://github.com/NoM0Re/WoW-3.3.5a-Addons) | 141 curated entries, 117 zips under `src/Addons/`, README links upstream for each. The best single index. |
| [NoM0Re/WoW-3.3.5a-Addons2](https://github.com/NoM0Re/WoW-3.3.5a-Addons2) | **Byte-identical mirror** — same 117 filenames, diffed. Not extra content. Use it only if the first is rate-limited. |
| [locus313/WoW-3.3.5a-Addons](https://github.com/locus313/WoW-3.3.5a-Addons) | Unzipped, versioned, with a per-addon table. Good for the ones with no upstream (Omen, Postal, Bartender4, Recount, Gatherer, Titan, Auctioneer, full DBM suite). |
| [wowgaming/addon-archive](https://github.com/wowgaming/addon-archive) | 400+ historical CurseForge snapshots — the archive ChromieCraft links. Its own README says *"please do not use it. It's just an historical archive"*. Last resort. |

Where an addon has a live GitHub upstream, prefer it. Where it doesn't, the mirror link *is* the
source and I've said so.

### Full UI replacement — pick exactly one

| Addon | What | Source |
|---|---|---|
| **ElvUI** | The 3.3.5a port of ElvUI. Complete replacement: bars, unit frames, nameplates, bags, chat. Folders `ElvUI` + `ElvUI_OptionsUI`. **Recommended.** | [ElvUI-WotLK/ElvUI](https://github.com/ElvUI-WotLK/ElvUI) — tag 6.09, last push 2024-07-31, 475★ |
| ElvUI companions | `ElvUI_AddOnSkins` (skins other addons to match), `ElvUI_Enhanced`. Whole org: 18 repos. | [ElvUI-WotLK](https://github.com/orgs/ElvUI-WotLK/repositories) |
| **DragonUI** | Retail/Dragonflight-styled modular UI for 3.3.5a. Genuinely maintained — v2.5, 138★, pushed 2026-08-07, `## Interface: 30300`. Has an Editor Mode and **shareable layout export codes**, which is useful for making three people's UIs identical. Folders `DragonUI` + `DragonUI_Options`, `/dui` to configure. Modular, so you can take just the action bars. | [NeticSoul/DragonUI](https://github.com/NeticSoul/DragonUI) |
| ~~Tukui~~ | No maintained 3.3.5a Tukui. The two repos that exist ([FuelGhoul/TukUI-Hydra](https://github.com/FuelGhoul/TukUI-Hydra) 1★ "needs alot of fixes", [Phantom59/Tukui-3.3.5](https://github.com/Phantom59/Tukui-3.3.5) last touched 2015) are not worth it. **Don't.** |

> Careful: `Decav/DragonUI` (1★) is a different, near-dead repo with a confusingly identical name.
> The one you want is **NeticSoul**.

ElvUI vs DragonUI: ElvUI is the known quantity but froze in mid-2024; DragonUI is under active
development and looks like modern WoW. Either replaces most of the "action bars / cast bars /
healing frames / bags" rows below. **Do not run both.**

### Action bars & unit frames

| Addon | What | Source |
|---|---|---|
| Bartender4 | The standard action bar replacement. v4.4.2. | [locus313/…/Bartender4](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Bartender4) |
| Dominos | Lighter bar replacement, fewer knobs. | [bkader/Dominos](https://github.com/bkader/Dominos) |
| Shadowed Unit Frames | Unit frame replacement. No live upstream — mirror only. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/ShadowedUnitFrames.zip) |
| Raeli's Unit Frames | Backported alternative. | [bkader/RUF-WoTLK](https://github.com/bkader/RUF-WoTLK) |
| MoveAnything | Drag any default frame anywhere. | [sirus-addons/MoveAnything](https://github.com/sirus-addons/MoveAnything) |

### Boss encounters

| Addon | What | Source |
|---|---|---|
| **DBM (Warmane backport)** | Retail-derived DBM core with modern timers and voice packs. **Recommended.** Despite the name the module coverage is complete for all three phases: `DBM-MC`, `DBM-BWL`, `DBM-AQ20/40`, `DBM-ZG`, `DBM-VanillaNaxx`, `DBM-VanillaOnyxia`, `DBM-Party-Classic`, all of TBC, all of WotLK. | [Zidras/DBM-Warmane](https://github.com/Zidras/DBM-Warmane) — 230★, pushed 2026-08-07 |
| DBM (vanilla-2010 suite) | The original 3.3.5-era DBM, unzipped per-module. Use only if the Warmane backport misbehaves. | [locus313/…/DBM-Core](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/DBM-Core) |
| BigWigs | Exists for 3.3.5a but **only ships WotLK-era modules** (Citadel, Coliseum, Naxxramas, Northrend, Onyxia, Ulduar) — nothing for phase 1 or 2 — and last saw a commit in 2022. | [bkader/BigWigs-WoTLK](https://github.com/bkader/BigWigs-WoTLK) — 2★ |

**Verdict: DBM, and specifically Zidras'.** BigWigs is a phase-3-only answer to a phase-1 problem.

> `pepopo978/BigWigs` (22★, actively maintained) turns up in searches for this. It is
> `## Interface: 11200` — **vanilla 1.12 / Turtle WoW**. Not 3.3.5a.

**DBM install gotcha, from its own README:** the Warmane backport is a retail port and is *not*
compatible with 2010 DBM saved variables. Before installing, delete every `DBM-*` folder from
`Interface/AddOns/` **and** every `DBM-*` file from `WTF/Account/<ACCT>/SavedVariables/` and from
each character's `SavedVariables/`. Skipping this produces Lua errors that look like addon bugs.

### Auras, cooldowns, cast bars

| Addon | What | Source |
|---|---|---|
| **WeakAuras** | Yes, a real WeakAuras 2 backport exists and it's the good one. Folders `WeakAuras`, `WeakAurasOptions`, `WeakAurasArchive`, `WeakAurasModelPaths`. | [Bunny67/WeakAuras-WotLK](https://github.com/Bunny67/WeakAuras-WotLK) — 184★, last push 2024-06-04 |
| WeakAuras (alt build) | v4.0.0, unzipped, same four folders. | [locus313/…/WeakAuras](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/WeakAuras) |
| TellMeWhen | Lighter than WeakAuras for plain cooldown/proc icons. | [bkader/TellMeWhen_3.3.5](https://github.com/bkader/TellMeWhen_3.3.5) |
| OmniCC | Cooldown-count numbers on every icon. | [NoM0Re/OmniCC-WotLK](https://github.com/NoM0Re/OmniCC-WotLK) — pushed 2026-07-08 |
| Quartz | Cast bar replacement with latency display. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Quartz.zip) |
| SexyCooldown | Horizontal cooldown timeline bar. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/SexyCooldown.zip) |
| PowerAuras | The pre-WeakAuras alternative, v3.0.0S. | [locus313/…/PowerAuras](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/PowerAuras) |

### Threat & damage meters

| Addon | What | Source |
|---|---|---|
| Omen | Threat meter, v3.0.9. The 3.3.5 standard; no live upstream. | [locus313/…/Omen](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Omen) |
| **Skada** | Damage/healing meter, modular, much lighter than Details. Recommended for a 3-person server. | [bkader/Skada-WoTLK](https://github.com/bkader/Skada-WoTLK) — 139★ |
| Details! | Prettier, heavier, plugin ecosystem incl. `Details_TinyThreat` (folds threat into the meter, lets you drop Omen). | [Bunny67/Details-WotLK](https://github.com/Bunny67/Details-WotLK) · [locus313 suite](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Details) |
| Recount | The old one. Only if someone insists. | [locus313/…/Recount](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Recount) |
| NotPlater | Plater-inspired threat-aware nameplates. Needs `awesome_wotlk` (below). | [RichSteini/NotPlater](https://github.com/RichSteini/NotPlater) — 44★, pushed 2026-01-11 |
| TidyPlates / ThreatPlates | Classic nameplate replacement with threat colouring. | [bkader/TidyPlates_WoTLK](https://github.com/bkader/TidyPlates_WoTLK) |

### Healing frames

| Addon | What | Source |
|---|---|---|
| Grid2 | Compact grid raid frames, heavily configurable. | [bkader/Grid2-WoTLK](https://github.com/bkader/Grid2-WoTLK) |
| VuhDo | Click-cast healing frames. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/VuhDo.zip) |
| HealBot | The other click-cast option. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/HealBot.zip) |
| Clique | Click-casting bound onto whatever frames you already use. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Clique.zip) |
| Decursive | One-button dispel. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Decursive.zip) |

With three players and bots you'll usually have one healer at most — Grid2 or Clique-on-ElvUI is
plenty. Don't ship VuhDo *and* HealBot.

### Bags, mail, inventory

| Addon | What | Source |
|---|---|---|
| AdiBags | Auto-categorising single-window bags. Actively maintained backport. | [Sattva-108/AdiBags](https://github.com/Sattva-108/AdiBags) — pushed 2025-07-09 |
| Bagnon | Single-window bags with working search + sort. | [RichSteini/Bagnon-3.3.5](https://github.com/RichSteini/Bagnon-3.3.5) · [locus313 suite](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Bagnon) (adds `Bagnon_Forever`, `_GuildBank`, `_Tooltips`) |
| Postal | Bulk mail open/take, v3.3.2. Essential the moment bots start mailing you things. | [locus313/…/Postal](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Postal) |
| CrapAway | Auto-sells greys at any vendor. | [locus313/…/CrapAway](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/CrapAway) |
| Altoholic | Cross-character inventory/profession database. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Altoholic.zip) |

### Quests

| Addon | What | Source |
|---|---|---|
| **Questie** | *The* pick for this server. Explicitly a 3.3.5a fork whose quest data is "a 1:1 match of what is seen on AzerothCore" — the author develops against a local AzerothCore server. Branch `335`, folder must be named `Questie-335`. | [Aldori15/Questie](https://github.com/Aldori15/Questie) — 45★, pushed 2026-08-07 |
| QuestHelper | Route-optimising alternative, v1.4.1. Heavier, older. | [locus313/…/QuestHelper](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/QuestHelper) |
| Carbonite | Map + quest helper in one. | [anzz1/Carbonite-3.3.5](https://github.com/anzz1/Carbonite-3.3.5) |
| Storyline / DialogUI / Immersion | Three different "make quest text not awful" replacements. | [shadovvs/WotLK-Storyline](https://github.com/shadovvs/WotLK-Storyline) · [ghbset/DialogUI-WotLK](https://github.com/ghbset/DialogUI-WotLK) · [s0h2x/Immersion-WotLK](https://github.com/s0h2x/Immersion-WotLK) |
| TurnIn | Auto-accepts and turns in quests and NPC gossip. `/ti window` for options. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/TurnIn-2.1.zip) |

Questie is the highest-value single addon on this list for a small server. Note its Warmane
compat-fix commit — you're not on Warmane, so any version ≥ current is fine.

### Maps, waypoints, gathering

| Addon | What | Source |
|---|---|---|
| Mapster | World map cleanup: scale, coords, fog-of-war removal. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Mapster.zip) |
| Atlas / AtlasLoot Enhanced | Dungeon maps, and boss loot tables in-game. Useful when you're deciding what phase-1 content is worth running. | [Atlas zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Atlas.zip) · [AtlasLoot zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/AtlasLoot.zip) |
| Gatherer | Herb/ore/treasure nodes on map + minimap, v3.1.16. | [locus313/…/Gatherer](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Gatherer) |
| GatherMate + database | GatherMate with a **pre-filled** 3.3.5a node database, so it's useful from day one instead of after 200 hours. | [stevemcqueenz/gathermate-and-database-3.3.5a](https://github.com/stevemcqueenz/gathermate-and-database-3.3.5a) — 2★, pushed 2026-06-29 |
| SexyMap | Minimap reskin/reshape. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/SexyMap.zip) |
| TomTom | Waypoint arrow. Questie's "point arrow towards objective" needs it. **No canonical 3.3.5a upstream** — the only live repos are server-specific forks: [sirus-addons/TomTom](https://github.com/sirus-addons/TomTom) (0★) and [Ascension-Addons/TomTom](https://github.com/Ascension-Addons/TomTom) (0★, "modified for Ascension.gg"). Both exist; neither is verified working on AzerothCore. **(verify)** |

### Auction house

| Addon | What | Source |
|---|---|---|
| **Auctionator** | Cataclysm-era Auctionator ported to 3.3.5a. Simple, fast, the right choice for a 3-person economy. | [alchem1ster/WotLK-Auctionator](https://github.com/alchem1ster/WotLK-Auctionator) — 60★ |
| Auctioneer suite | The full v5.9.4960 stack (16 folders: `Auc-Advanced`, `BeanCounter`, `Enchantrix`, `Informant`, `Stubby`, …). Enormous, scan-heavy. Overkill unless an AH bot module is running and the listings are actually deep. | [locus313 suite](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/Auc-Advanced) |
| TradeSkillMaster v2.8.3 | Full crafting/flipping suite. Almost certainly overkill here. | [andrew6180/TradeSkillMaster](https://github.com/andrew6180/TradeSkillMaster) |
| AuctionHouseDepositFixer | Fixes the deposit cost the client displays. | [locus313/…/AuctionHouseDepositFixer](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/AuctionHouseDepositFixer) |

**Playerbots do not list on the auction house.** Checked directly against `mod-playerbots/master`:
`conf/playerbots.conf.dist` carries 802 `AiPlayerbot.*` keys and **zero** of them mention auctions
or the AH, and no source file in the module is named `*auction*`. The bots' economic interaction
with you is the **trade window** (`AiPlayerbot.EnableRandomBotTrading`), not the AH.
[modules.md](modules.md) §1.4 has the full evidence, including the only two source files that
reference `AuctionHouse` at all — and both do price lookups, not listings.

So the situation here is the opposite of a busy realm: three humans, no listing bots, and an auction
house that is **empty forever** unless you install the Tier-1 AH bot module that
[modules.md](modules.md) §1.4 picks (`NathanHandley/mod-ah-bot-plus`). That makes an AH addon
*more* worth installing, not less — but only in this order:

1. **Server module first.** No `mod-ah-bot-plus`, no listings, and Auctionator has nothing to
   search. An addon cannot manufacture an economy on its own.
2. **Addon second.** Once the bot is seeding the AH, Auctionator is what makes it bearable — the
   stock 3.3.5a auction UI is one page of results at a time with no price history.

If you decide against the module, skip this whole table: nothing in it does anything useful on a
genuinely dead AH, and an Auctionator scan just returns zero rows.

### Chat

| Addon | What | Source |
|---|---|---|
| **CleanerChat** | Chat declutter + chat frame replacement. Backported Glass + ChatCleaner in one package. The most actively maintained of these. | [migwynkriid/CleanerChat-WotLK](https://github.com/migwynkriid/CleanerChat-WotLK) — 22★, pushed 2026-08-05 |
| Chatter | Chat frame overhaul: timestamps, copy, sticky channels. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/Chatter.zip) |
| STFU | Narrower than the name suggests — blocks *opposite-faction spam in neutral cities* specifically. Not a general chat filter. | [Arcitec/STFU_Chat_Filter](https://github.com/Arcitec/STFU_Chat_Filter) — 5★ |
| WIM | Whispers in proper IM windows. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/WIM.zip) |
| xCT+ | Scrolling combat text, MoP 5.4.8 backport, replaces MSBT. | [hypopheria2k/xCT_Plus_wotlk](https://github.com/hypopheria2k/xCT_Plus_wotlk) |

**Chat filtering is not cosmetic on this server.** Playerbots are chatty by default and will flood
your chat frame — that is the whole premise of MultiBot-Chatless below. Take **CleanerChat** (or
Chatter's filter module); STFU does not solve this problem. The server-side half is the
`AiPlayerbot.*` verbosity settings in [server-config.md](server-config.md).

### Inspect / gearscore

| Addon | What | Source |
|---|---|---|
| GearScoreLite: Reborn | Rebuilt GearScoreLite — no database, improved algorithm, works with any unit-frame addon. The one to take. | [Arcitec/GearScoreLite_Reborn](https://github.com/Arcitec/GearScoreLite_Reborn) |
| GearScoreLite | Older lite build with ElvUI/inspect-frame fixes. | [Barsoomx/GearScoreLite](https://github.com/Barsoomx/GearScoreLite) |
| Equipence | Detailed gear overview on inspect. | [s0h2x/Equipence](https://github.com/s0h2x/Equipence) |
| InspectEquip | Shows inspected gear as a paperdoll. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/InspectEquip.zip) |
| RatingBuster | Breaks item stats into "+X% crit" in tooltips. | [Einherjarn/RatingBuster-3.3.5](https://github.com/Einherjarn/RatingBuster-3.3.5) |
| TipTac | Tooltip overhaul. No live upstream. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/TipTac.zip) |

GearScore is a bit absurd for three friends, but it's the fastest way to see whether a playerbot
has been gearing itself or is still in greens.

### Utility

| Addon | What | Source |
|---|---|---|
| Addon Control Panel (ACP) | Enable/disable addons **without logging out**. Install this first; it saves the most time during setup. | [locus313/…/ACP](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/ACP) |
| BugSack + BugGrabber | Collects Lua errors instead of throwing popups. | [NoM0Re zip](https://github.com/NoM0Re/WoW-3.3.5a-Addons/raw/main/src/Addons/BugSack.zip) |
| GTFO | Audio alert when you're standing in fire, v2.5.3. | [locus313/…/GTFO](https://github.com/locus313/WoW-3.3.5a-Addons/tree/main/GTFO) |
| Talented | Sane talent UI — you'll be respeccing a lot across phase flips. | [bkader/Talented_WoTLK](https://github.com/bkader/Talented_WoTLK) |
| SharedMedia | Fonts/textures/sounds other addons pull from. Dependency for several of the above. | [bkader/SharedMedia](https://github.com/bkader/SharedMedia) |
| KPack | ~40 small addons collapsed into one, if you'd rather not manage 40 folders. | [bkader/KPack](https://github.com/bkader/KPack) |

### `awesome_wotlk` — a client patch, not an addon

[FrostAtom/awesome_wotlk](https://github.com/FrostAtom/awesome_wotlk) (82★, pushed 2026-06-03) is a
DLL that patches `Wow.exe` to add Lua API that 3.3.5a never had: `C_NamePlate.GetNamePlates`,
`NAME_PLATE_UNIT_ADDED`, `UnitIsSilenced`, `CopyToClipboard`, `cameraFov` / `nameplateDistance`
CVars, and `-login`/`-password`/`-realmlist` command-line auto-login.

Required by NotPlater and several modern backports. Caveats:

- It **modifies `Wow.exe`** (via `AwesomeWotlkPatch.exe` + Detours). Your 12340 hash check will no
  longer match retail — keep a pristine copy.
- Run the patcher inside the same Wine prefix as the game, from the game root.
- Skip it unless an addon you actually want demands it.

### Playerbot control

Three candidates. They are not equivalent.

| Addon | What it is | Server-side cost | State |
|---|---|---|---|
| **[Wishmaster117/MultiBot-Chatless](https://github.com/Wishmaster117/MultiBot-Chatless)** | Full bot management UI — roster, per-bot inventory/bank/spellbook/talents/glyphs/quests, strategy toggles, raid formations. Uses a structured `MBOT GET~…` protocol instead of parsing bot chat. Explicitly targets [`mod-playerbots/mod-playerbots`](https://github.com/mod-playerbots/mod-playerbots) — **the exact fork chosen in [modules.md](modules.md) §1.1**. | **Requires** the AzerothCore module [`Wishmaster117/mod-multibot-bridge`](https://github.com/Wishmaster117/mod-multibot-bridge) (19★, pushed 2026-08-07) | 33★, pushed **2026-08-08**. Actively developed. |
| [whipowill/wow-addon-playerbots](https://github.com/whipowill/wow-addon-playerbots) | Fork of ike3's original MaNGOS bot addon. Roster window + a control panel that just fires the normal `/bot` chat commands. | **None** — pure chat wrapper, works against any playerbots fork | 73★, last push 2023-05-08. Stale but functional; its README still points at the abandoned `ZhengPeiRu21/mod-playerbots`. |
| [azcguy/PlayerbotsPanel](https://github.com/azcguy/PlayerbotsPanel) | Ambitious Blizzard-native-feeling bot manager. Targets `liyunfan1223/mod-playerbots`, not the `mod-playerbots/mod-playerbots` fork this server uses. | Needs the companion client library `azcguy/PlayerbotsBroker` (0★), and its server side is currently a *communication emulator* (`PlayerbotsPanelEmu`) — there is no real server module to install. | Its own README, first line, verbatim: **"EARLY ALPHA - DOESNT WORK AND DONT REPORT BUGS"**. 16★, last push 2024-06-13. |

Also note `Wishmaster117/MultiBot` (41★) — the chat-parsing predecessor — is **archived**. Don't
install it by mistake; the successor is `MultiBot-Chatless`.

**Install MultiBot-Chatless. Do not install PlayerbotsPanel.** MultiBot-Chatless is the only one of
the three that is both maintained and aimed at your exact core fork; the price is one more module in
the build. PlayerbotsPanel is not a "maybe later" — its own author says it does not work, it has not
been touched since June 2024, and its server half is a test emulator rather than a module. It is
listed here only so nobody rediscovers it and assumes it was overlooked.

That has consequences elsewhere:

- `mod-multibot-bridge` goes into `build/modules.txt` **pinned to a SHA** — see
  [modules.md](modules.md) §6 for the pinning rule and the canonical `modules.txt` format. It's
  pushed near-daily, which is exactly the case pinning exists for.
- It's a client-addon-plus-server-module pair — **the addon and the bridge must be upgraded
  together**. Version-skew between the two is a protocol mismatch, not a graceful degradation.
  MultiBot-Chatless' own README is explicit that without the bridge module the addon cannot use the
  structured `MBOT GET~…` data flow at all.
- Cross-reference: [modules.md](modules.md) §2, *Playerbot fleet management*.

The only real fallback, if you'd rather not add a module: take `whipowill/wow-addon-playerbots`,
accept that it's a 2023 chat-command wrapper, and lean on the ~100 `/bot` chat commands directly.
Nothing about `mod-playerbots` requires a client addon at all.

### AzerothAdmin — the in-game GM panel

[superstyro/AzerothAdmin](https://github.com/superstyro/AzerothAdmin) — 67★, GPLv3,
`## Interface: 30300`, pushed 2026-07-19, not archived. A GUI over AzerothCore's dot-commands,
descended from TrinityAdmin/MangAdmin. Eight tabs (`Frames/Frames_Section*.lua`): **Main, Char,
NPC, GO, Tele, Ticket, Misc, Server** — buttons, sliders, dropdowns and search popups instead of
remembering `.modify speed all 3.5`, `.npc add`, `.gobject set phase` and `.tele add`.

**Pure client-side. No server module, no SQL, nothing added to `build/`.** Every button funnels
into `AzerothAdmin:ChatMsg()` (`Core/AzerothAdmin.lua:1383`), which is a thin wrapper over
`SendChatMessage(msg, "say")`; the server's replies come back by `RawHook`-ing `AddMessage` on all
`NUM_CHAT_WINDOWS` chat frames (`Core/AzerothAdmin.lua:224`) and pattern-matching the system
messages. It is exactly what you would type by hand, so it works against the stock server as
installed. Contrast MultiBot-Chatless above, which genuinely does need `mod-multibot-bridge` — the
two are not comparable in cost.

**No other addon or library required.** Ace3, `FrameLib-1.0` and `Graph-1.0` are vendored under
`Libraries/` and loaded by path from the `.toc`; `## OptionalDeps: Ace3` only means a standalone
Ace3 is reused when some other addon already loaded it. The minimap button asks
`LibStub("LibDBIcon-1.0", true)` and silently skips itself if nothing provides it.

**Opening it:** `/aa` or `/azerothadmin`, or the minimap button. Shift-clicking either reloads the
UI (`Core/AzerothAdmin.lua:381`) — deliberate, not a bug. Escape closes the frames.

#### GM level

The addon does no gating of its own — it fires the command and lets the server refuse. Resolved
against this realm's own `acore_auth` RBAC tables (`rbac_default_permissions` →
`rbac_linked_permissions`):

| What you want to use | Role that grants it | Minimum `gmlevel` |
|---|---|---|
| Ticket tab (`.ticket …`) | Moderator Commands (198) | **1** |
| Char / NPC / GO / Tele / Misc — `.gm`, `.additem`, `.modify speed`, `.character level`, `.learn all …`, `.npc add`, `.gobject add`, `.tele add` | Gamemaster Commands (197) | **2** |
| Server tab — `.reload`, `.reload smart`, `.server restart`, `.server shutdown` — and `.account set gmlevel` | Administrator Commands (196) | **3** |

**Take 3.** At 1 or 2 the higher tabs are still fully drawn and clickable — nothing greys out — so
a permission refusal reads as an addon bug. Granting it is [bring-up.md §7.2](bring-up.md#72-gm-level)
(`.account set gmlevel ALI 3 -1` from the `AC>` console); do not raise your friends' accounts to
run this addon, one admin is enough.

Two behaviours worth knowing before you hand the panel to someone at level 0:

- A dot-command the account may not use is **swallowed, not spoken**, because this server leaves
  `AllowPlayerCommands` at its default of `1` (`WorldConfig.cpp:165`) and the core then answers
  "no such command" instead of falling through to normal chat (`Chat.cpp:242`,
  `ChatHandler.cpp:307`). Set that key to `0` and the same click broadcasts `.gm on` to everyone in
  `/say` — a reason not to change it.
- The search popups scrape `.lookup …` output out of the chat frame, and `Command.LookupMaxResults`
  defaults to `0` = unlimited (`cs_lookup.cpp:133`). A two-letter item search dumps thousands of
  lines. Search with a real substring.

#### Manifest entry

```
superstyro/AzerothAdmin   master   root:AzerothAdmin   eeda6f77…
```

`root:`, not `dirs`, and the folder name is not negotiable:

- `AzerothAdmin.toc` sits at the repo root, so `dirs` would find no addon there at all — and would
  still install something, because `Libraries/Ace3.toc` satisfies the installer's "a directory
  containing a `.toc` is an addon" test. You would get `Interface/AddOns/Libraries/` listed as a
  broken addon and no AzerothAdmin.
- The Lua hardcodes `Interface\AddOns\AzerothAdmin\…` in four places (textures and the minimap
  icon), and the companion `.toc` declares `## Dependencies: AzerothAdmin`. Rename the folder and
  you get a loaded addon with missing art.

Installed and verified against the real client: 79 → 80 top-level `AddOns` directories, the one new
directory being `AzerothAdmin`; `AddOns/AzerothAdmin/AzerothAdmin.toc` present, all 43 files the
`.toc` loads resolve, `Libraries/` nested inside the addon and **not** at top level.

#### The one thing it does not install: `AzerothAdmin_Models`

Upstream ships **two** addons. The release zip contains `AzerothAdmin/` plus
`AzerothAdmin_Models/`, a 5.6 MB `LoadOnDemand` GameObject-model database that the GO tab's model
preview pulls in on first use; it was split out of the main addon to cut its idle memory from
7.5 MB to 1.9 MB. In the repo it lives at `_build/AzerothAdmin_Models/`, and `client/addons.txt`
has no grammar for "install this subdirectory as a second addon", so a `root:` install lands it
nested and inert.

Nothing breaks. `EnsureModelsLoaded()` (`Commands/GO.lua:103`) calls `LoadAddOn`, gets reason 2,
prints `ERROR: Could not load Models addon - Addon missing` and leaves the rest of the GO tab
working; every other tab is unaffected. If you want the model preview, lift it once by hand:

```bash
cd "$HOME/games/wow-3.3.5a/ChromieCraft_3.3.5a/Interface/AddOns"
cp -a AzerothAdmin/_build/AzerothAdmin_Models .
```

`scripts/client-addons.sh` only deletes folders it manages, so the copy survives re-runs — but it
also will not be refreshed by them, so redo it whenever the pinned SHA moves. The clean fix is a
third manifest mode (`sub:<path>:<NAME>`) in the installer; until that exists, this is the honest
state of things.

#### It does not replace an item browser

There is a `Frames_Section*.lua` for Main, Char, GO, NPC, Server, Tele, Ticket and Misc — and none
for items. What item support exists is a name box wired to `.lookup item` /
`.lookup item set` (`Core/AzerothAdmin.lua:2263`) whose chat output is scraped into a plain text
list, plus `.additem`. No icons, no tooltips, no filtering by slot, quality or item level, and no
way to see what an item actually is before you spawn it. That gap is why the in-house item browser
is separate work rather than something AzerothAdmin already covers; the two sit side by side, and
installing this one changes nothing about that plan.

---

## 6. Practical notes

### Paths

```
<WoW>/
├── Data/
│   ├── enUS/
│   │   ├── realmlist.wtf            # set realmlist <host>   (chmod 444)
│   │   └── patch-enUS-4.MPQ         # locale-scoped custom content
│   └── Patch-H.MPQ                  # global custom content, numerics then A-Z
├── Interface/
│   └── AddOns/
│       └── <AddonName>/<AddonName>.toc
└── WTF/
    ├── Config.wtf                   # SET gxApi, SET realmList, ...
    └── Account/<ACCOUNT>/
        ├── SavedVariables/*.lua     # account-wide addon config
        └── <Realm>/<Char>/SavedVariables/*.lua
```

`<ACCOUNT>` is upper-cased by the client. The folder name inside `AddOns/` **must** match the
`.toc` filename — `Questie-335/Questie-335.toc`, not `Questie-335/Questie.toc`.

### The `-main` / `-master` trap

A GitHub zip extracts to `Repo-<branch>/` containing the real addon folders — `-main` or `-master`
depending on the repo's default branch, and these 3.3.5a repos are genuinely split between the two.
Copy the **inner** folders. `Interface/AddOns/ElvUI-master/ElvUI/` does nothing; you need
`Interface/AddOns/ElvUI/`. DBM-Warmane's README calls this out explicitly because it catches
everyone. Repos that contain multiple folders (default branches confirmed via the GitHub API):

| Repo | Default branch | Folders to copy |
|---|---|---|
| `ElvUI-WotLK/ElvUI` | `master` | `ElvUI`, `ElvUI_OptionsUI` |
| `NeticSoul/DragonUI` | `main` | `DragonUI`, `DragonUI_Options` |
| `Bunny67/WeakAuras-WotLK` | `master` | `WeakAuras`, `WeakAurasOptions`, `WeakAurasArchive`, `WeakAurasModelPaths` |
| `Zidras/DBM-Warmane` | `main` | all 35 `DBM-*` folders |

The trap inverts for **Questie**. `Aldori15/Questie` has no wrapper directory — the repo root *is*
the addon (`Questie-335.toc`, `Questie.lua`, `Database/`, `Libs/`, … all sit at the top level).
A zip of branch `335` therefore extracts to `Questie-335/`, which is already the folder name the
`.toc` requires. Keep that directory as-is; do **not** go looking for inner folders to hoist.

### TOC version and "Load out of date AddOns"

3.3.5a's interface version is **30300**. A `.toc` header declaring anything else:

```
## Interface: 30300
## Title: Whatever
## Notes: ...
```

is treated as out of date and greyed out at character select. Fix by ticking **Load out of date
AddOns** in the AddOns dialog (bottom-left of character select) — it persists — or by editing the
`## Interface:` line. Editing is cosmetic; the checkbox is the honest fix, since a backport
declaring `20400` or `30200` usually still works fine.

If an addon still doesn't appear after that, the folder name doesn't match the `.toc`.

### Distributing one agreed pack to three people

Goal: everyone on the same addons, same versions, and updatable without a group chat thread. In
increasing order of effort:

**Recommended — a git repo that *is* the AddOns folder.**

```bash
# in the repo: one directory per addon, at the repo root
wowserver-addons/
├── README.md
├── ACP/
├── DragonUI/
├── DragonUI_Options/
├── Questie-335/
├── DBM-Core/
└── ...
```

```bash
# friend, first time
cd "$HOME/Games/wow-3.3.5a/Interface"
mv AddOns AddOns.bak 2>/dev/null || true
git clone https://github.com/<you>/wowserver-addons.git AddOns

# every time after
cd "$HOME/Games/wow-3.3.5a/Interface/AddOns" && git pull
```

The `.git` directory sitting in `AddOns/` is harmless — WoW only looks for directories containing a
matching `.toc`. Add upstreams as git submodules if you want to track them, or vendor the files and
bump them yourself; vendoring is simpler and matches the SHA-pinning philosophy the server build
already uses.

**For the friend who will not use git:** tag the repo and attach a zip to a GitHub release. Same
content, one link, and the tag tells you what they're actually running when they report a bug.

**Shipping identical *configuration*, not just identical addons.** Addon settings live in
`WTF/Account/<ACCOUNT>/SavedVariables/*.lua`, keyed by account name, so you can't just commit them
verbatim. Options:

- ElvUI and DragonUI both export their entire layout as a **profile string**. Paste one string,
  done. This is the cleanest path and is a real argument for DragonUI, whose export codes cover
  layout *and* addon settings.
- For everything else, commit a `profiles/` directory of exported strings alongside the addons and
  a `README.md` saying which slash command imports which.
- Do not commit `SavedVariables` wholesale — you'll ship your keybinds, your character list and
  possibly your account name.

**Automating updates:** [alchem1ster/AddOns-Update-Tool](https://github.com/alchem1ster/AddOns-Update-Tool)
(29★, pure Python + Dulwich) takes a YAML/JSON map of repo→branch, clones/pulls each into
`Interface/AddOns`, keeps the last 5 backups, and can launch the game afterwards:

```yaml
# addons.yaml — branch names verified against the GitHub API, they are not interchangeable
https://github.com/ElvUI-WotLK/ElvUI          : master
https://github.com/Aldori15/Questie           : 335
https://github.com/Zidras/DBM-Warmane         : main
https://github.com/Bunny67/WeakAuras-WotLK    : master
```

Get the branch wrong and the tool fails on that line rather than falling back to the default —
`ElvUI-WotLK/ElvUI` in particular has only `master` and `pr/739`, **no `main`**, which is exactly
the mistake to make here.

It auto-detects the addon subdirectories inside each repo, which solves the `-main`/`-master` trap
above. Last push 2022 — it works, but it is not actively developed. **(verify)** whether it handles
a repo whose default branch has been renamed.

**What not to use:** [Warperia](https://warperia.com/) is a large private-server addon site with a
Windows-only desktop client and no visible source. Fine as a place to *find* a 3.3.5 addon; not
something to standardise three installs on.

### Suggested minimal pack

Start here, add later. Fewer addons means fewer "it's an addon" bug reports while the server itself
is still settling.

| Slot | Take |
|---|---|
| UI | DragonUI (or ElvUI) |
| Addon manager | ACP |
| Quests | Questie (`335` branch) |
| Boss mods | DBM-Warmane |
| Auras | WeakAuras (Bunny67) |
| Meter | Skada |
| Bags | AdiBags |
| Mail | Postal |
| Chat | CleanerChat |
| Loot reference | AtlasLoot |
| Bots | MultiBot-Chatless + `mod-multibot-bridge` |
| Errors | BugSack |
