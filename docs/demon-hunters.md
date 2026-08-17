# Demon Hunter — an eleventh playable class

Demon Hunter is a **real class** on this realm, not a reskin and not an opt-in conversion. It is
class **10**, it appears as its own button on the character-creation screen with its own name,
icon and colour, only Night Elves and Blood Elves can roll one, and it levels 1→80 like anybody
else. Rogues are untouched.

This document is the one you read six months from now, or the one you send a friend whose client
shows ten class buttons instead of eleven. It covers what ships, why it needs two patches that
the Death Knight did not, how to build and install it, how to verify it, what is knowingly
unfinished, and how to turn it off.

Server tuning is [server-config.md](server-config.md), client setup is [client.md](client.md),
modules are [modules.md](modules.md), and the feature this one is modelled on is
[death-knights.md](death-knights.md) — **read that first if you have not.** The architecture is
the same and this document does not restate it.

> **Two things here are unlike anything else in this repo.** It carries a core patch
> (`build/patches/`) and it requires a modified `Wow.exe`. Both are small, both are reversible,
> and §2 and §3 are the argument for each. If you are not willing to ship a patched client
> binary to your friends, stop reading — this feature is not for you, and §11 says what the
> alternative would have been.

---

## 1. What ships

| | |
|---|---|
| Class | Demon Hunter, **class 10** — the vacant `//CLASS_UNK` slot between Warlock and Druid |
| Races | **Night Elf (4)** and **Blood Elf (10)**, and nothing else |
| Start | level **1**, in that race's normal starting zone — Teldrassil (map 1, zone 141) or Eversong Woods (map 530, zone 3431) |
| Stats | derived from the **Rogue** — leather, agility, dual-wield, parries |
| Resource | **Energy**, presented as Fury: a 0–100 bar with continuous out-of-combat regeneration |
| Spell family | **16**, previously unused by any of the 49,839 stock spells |
| Talents | three authored trees — **Havoc, Vengeance, Illidari**, 22 talents and 69 points each, tiers 0–10 — opening at level 10 like every other class |
| Demon form | Metamorphosis at 40, shapeshift form **23**, display **21135** (Illidan Stormrage) |
| Abilities | 22, from level 1 to 70 (§4) |

### 1.1 The movement kit

The four movement abilities are the reason anyone wants this class, and they are the part with
the least stock support in a 2008 client. What each one actually is:

| ability | how it works | fidelity |
|---|---|---|
| **Fel Rush** | `SPELL_EFFECT_CHARGE_DEST` from `TARGET_DEST_CASTER_FRONT` — targetless, collision-safe, distance is a radius index | high |
| **Vengeful Retreat** | `SPELL_EFFECT_LEAP_BACK`. There is **no backflip animation in 3.3.5a**; it renders as a jump that translates backwards | mechanically right, visually approximate |
| **Glide** | feather-fall, cancelled on landing by `AuraInterruptFlags` exactly as stock Parachute does it. A forward-speed aura is on the record but **may be inert** — horizontal momentum looks to be fixed at takeoff, so a speed aura applied mid-air may change nothing | descent high, forward drift **unverified** |
| **Double Jump** | **client-side, in the addon.** The stock client never sends a second `MSG_MOVE_JUMP` while airborne — that pattern is literally what jump-hack detection looks for — so the second jump cannot originate on the server | see §7 |

Double Jump is the one place where a player who disables the addon silently loses a feature.
**The class is therefore not balanced around it**, and it is at level 1 precisely because it is a
traversal toy rather than power.

---

## 2. Why the class needs a patched `Wow.exe`

This is the single most important thing to understand about the feature, and it is the reason
the Death Knight needed no exe patch and this does.

**`ChrClasses.dbc` ships exactly ten records** — IDs 1–9 and 11. Ten, not eleven. And
`Interface\GlueXML\CharacterCreate.lua:3` says:

```lua
MAX_CLASSES_PER_RACE = 10;
```

`GetAvailableClasses()` returns one triple per `ChrClasses.dbc` row, and
`CharacterCreateEnumerateClasses` *disables* the race-invalid ones rather than filtering them
out — so `numClasses` is the total row count, not the count for the selected race. At eleven
rows the stock file does this:

```lua
if ( CharacterCreate.numClasses > MAX_CLASSES_PER_RACE ) then
    message("Too many classes!  Update MAX_CLASSES_PER_RACE");
    return;
end
```

and returns, leaving **every class button unconfigured for every race**. Not just the new one —
character creation breaks entirely. `CharacterCreate.xml` also declares exactly ten
`CharacterCreateClassButton` frames, so an eleventh has to be authored too.

Both of those files live inside the **RSA-signed GlueXML tree**.

### 2.1 The signature check is real, and it is fatal

The repo used to say the client's only integrity check covered
`Interface\FrameXML\FrameXML.toc` and `Bindings.xml`. That recon found one of two checks. There
is a second, structurally identical one over `Interface\GlueXML\GlueXML.toc`, and it is the one
that matters here. Disassembled from this install's `Wow.exe`:

```
; --- GlueXML, 0x004da7d2 ---              ; --- FrameXML, 0x0052abc2 ---
push 0x9e2c28     ; 2048-bit RSA key       push 0x9e2c28
push 0x9f4320     ; "...\GlueXML.toc"      push 0xa02fcc   ; "...\FrameXML.toc"
call 0x8165e0     ; verify -> eax          call 0x8165e0
cmp  eax,3                                 cmp  eax,3
ja   0x004da81e   ; -> epilogue, ret       ja   0x0052ac12
jmp  [eax*4+0x4da9b4]                      jmp  [eax*4+0x52aeb4]

  case 0 -> "GlueXML missing signature"     \
  case 1 -> "GlueXML has corrupt signature"  >  log, fall through to the epilogue
  case 2 -> "GlueXML is modified or corrupt" /
  case 3 -> 0x004da835 -> call 0x814340      -- THE ONLY PATH THAT LOADS THE TOC
```

The TOC path string is pushed exactly **twice** in the entire binary: once to verify it, once to
load it — and the load is reachable only from case 3. So a modified GlueXML does not produce a
warning. The glue UI is never loaded at all.

### 2.2 Measured, not reasoned

This was tested rather than argued. Identical archive both runs, only twelve bytes of `Wow.exe`
different, one modified file (`GlueStrings.lua`, with the login button relabelled):

| | stock exe | patched exe |
|---|---|---|
| `Logs/GlueXML.log` | `GlueXML is modified or corrupt` | **not created** |
| D3D9 swapchain | never created | 2560×1600, 4 images |
| realm connection | none | `RESPONSE_CONNECTED` → `AUTH_OK` → character list |
| login button | `Login` | **`Login [DHPATCH]`** |

On the patched client the log-writing branch is unreachable, which is why `GlueXML.log` is not
created at all — that absence is the pass condition, not a missing test.

### 2.3 The patch

`client/tools/patch-wow-exe.py`. Twelve bytes at each of the two sites, replacing
`cmp eax,3 / ja short / jmp [eax*4+table]` with an unconditional `jmp rel32` to that site's
case-3 target, NOP-padded so every following instruction keeps its address:

```
83 f8 03 77 34 ff 24 85 <table:4>   ->   e9 <rel32:4> 90 90 90 90 90 90 90
```

Nothing is relocated, no section grows, the verify call still runs (its result is simply
ignored), and a genuinely corrupt archive still logs. It is idempotent, it keeps a `.orig`
backup, and `--revert` restores the stock bytes **byte-identically** — verified by md5 against
the original.

```bash
client/tools/patch-wow-exe.py --check     # report state, write nothing
client/tools/patch-wow-exe.py             # patch in place
client/tools/patch-wow-exe.py --revert    # undo
```

It refuses outright if the bytes at either site are neither the stock pattern nor its own patch,
which is what happens if you point it at a different client build.

**What it does not touch:** the Warden client, the connection handshake, the archive loader, or
the MPQ `(signature)` check. Only these two UI-integrity checks.

---

## 3. Why the class needs a core patch

`build/patches/0001-demon-hunter-class-10.patch` — eight lines across three files, and that
directory's `README.md` is the full argument. In summary:

* **`CLASSMASK_ALL_PLAYABLE`** does not contain class 10's bit. Ten call sites silently drop
  rows whose class mask is not in it — item `AllowableClass`, quest `RequiredClasses`,
  `playercreateinfo_spell/action/item`, `conditions`, achievement criteria, and, decisively,
  `DBCStores.cpp:554`, which skips any `TalentTab` row that fails the test. Without that one
  line the three talent trees are read from the DBC, skipped, and the class has an **empty
  talent panel for its entire life with no error logged**.
* **Six per-class float tables** have a `0.0f, // ??` at the class-10 index and are read through
  `getClass() - 1` **directly**, not through `Player::IsClass` — so unlike the other ~134 class
  decision points in the core, no module hook can reach them. Left alone they do not mean "no
  bonus"; `StatSystem.cpp:827` evaluates `0*0/(0+0*0)` and every Demon Hunter gets **NaN dodge
  for its entire life**, never dodging or parrying, while the character sheet displays a
  plausible number.

### 3.1 And one patch to a module

`build/patches/0002-learn-spells-skip-demon-hunter.patch`. `mod-learn-spells` is pinned and
enabled, and its `GetSpellFamily` has a `default: return SPELLFAMILY_GENERIC` that class 10 is
the first class ever to reach. Family 0 is the family of every unclassed spell in the game, and
the scan has no class check — so a Demon Hunter would be handed **15 junk spells at level 1**
(Parry, four ranks of Intercept, Vampiric Touch, Flash of Light…), 59 Enchanting recipes at 35
and 38 Alchemy recipes at 45. One `case` label fixes it. The patches README has the full
argument, including why it returns family 14 and not the class's own 16.

### 3.2 Four stock SkillLineAbility rows are widened

Not a patch — SQL, in `01_spells.sql`. A new class does not inherit the spells every other class
takes for granted, and the failure is silent:

| SLA | spell | stock ClassMask | what it costs to leave alone |
|---|---|---|---|
| 610 | 674 Dual Wield | 109 | `CanDualWield` false forever — a dual-wield class that cannot dual wield |
| 2201 | 3127 Parry | 15 | `UpdateParryPercentage` is `if (CanParry() && …)`, so **the core patch's `parry_cap[9]` is dead code without it** |
| 13338 | 25046 Arcane Torrent | 8 (rogue only) | the Blood Elf racial is **on the starting action bar** — a dead button on every Blood Elf |
| 20665 | 21009 Elusiveness | 1085 | the Night Elf racial passive |

(58984 Shadowmeld needs nothing — its row is `ClassMask 0`, i.e. every class. Checked, not
assumed.)

Everything else — stats, creation, spells, talents, the demon form — is SQL rows in the
world-DB `*_dbc` override tables. `/srv/wow/data/dbc/` is never written.

---

## 4. The abilities

Twenty-two, level 1 to 70. Spell IDs are `91000`+ (§8).

| level | ability | spell | donor | cost | cooldown | what it does |
|---|---|---|---|---|---|---|
| 1 | **Demon's Bite** | `91000` | `63753` | — | — | A quick slash that builds Fury. |
| 1 | **Double Jump** | `91500` | `74608` | — | — | Leap again in mid-air. |
| 2 | **Chaos Strike** | `91020` | `63753` | 40 Fury | — | Spend Fury for a strike that ignores armour. |
| 4 | **Fel Rush** | `91040` | `64872` | — | 10 s | Dash forward, damaging everything in the path. |
| 6 | **Glide** | `91501` | `12438` | — | — | Slow your descent and drift forward. |
| 8 | **Throw Glaive** | `91060` | `31935` | 25 Fury | 9 s | Hurl a glaive that bounces between targets. |
| 10 | **Immolation Aura** | `91080` | `50589` | — | 30 s | Burn everything around you. |
| 12 | **Spectral Sight** | `91503` | `34709` | — | 30 s | See the unseen, at the cost of speed. |
| 14 | **Consume Magic** | `91504` | `19505` | — | 15 s | Devour a beneficial effect from your enemy. |
| 16 | **Blade Dance** | `91100` | `63753` | 35 Fury | 15 s | Spin, striking everything nearby. |
| 20 | **Vengeful Retreat** | `91502` | `781` | — | 25 s | Flip backwards out of danger. |
| 24 | **Blur** | `91505` | `5277` | — | 60 s | Become hard to pin down. |
| 28 | **Chaos Nova** | `91506` | `30283` | 25 Fury | 45 s | Detonate chaotic energy, stunning everything close. |
| 32 | **Torment** | `91507` | `56222` | — | 8 s | Taunt your enemy into attacking you. |
| 36 | **Fiery Brand** | `91120` | `348` | — | 60 s | Brand your enemy; they burn, and they hurt you less. |
| 40 | ⭐ **Metamorphosis** | `91508` | `47241` | — | 180 s | Take demonic form. |
| 44 | **Imprison** | `91509` | `20066` | 25 Fury | 45 s | Bind an enemy in place. |
| 48 | **Sigil of Flame** | `91140` | `26573` | 30 Fury | 30 s | Place a sigil that erupts in flame. |
| 52 | **Soul Cleave** | `91160` | `63753` | 35 Fury | — | Cleave nearby enemies and mend yourself. |
| 56 | ⭐ **Eye Beam** | `91180` | `1949` | 30 Fury | 30 s | Unleash a beam of fel energy. |
| 60 | **Darkness** | `91510` | `65070` | — | 300 s | Shroud an area; allies within are harder to hit. |
| 70 | **Infernal Strike** | `91511` | `6544` | — | 20 s | Leap to a point and erupt on landing. |

### 4.1 Why almost none of these have ranks

The Death Knight re-ranks because Blizzard re-ranks: its abilities have stock ladders whose
numbers are absolute, so a level-10 DK holding the level-55 record would hit for the level-55
number. Applied here, the same test comes out the other way, for two reasons that are properties
of the donors rather than of the design:

1. `SPELL_EFFECT_WEAPON_PERCENT_DAMAGE` is **level-correct by construction**. "80% weapon
   damage" is right at level 1 and at level 80 from one record, because the weapon is what
   scales. Every melee strike in the kit uses it.
2. For an absolute number, `CalcValue` (`SpellInfo.cpp:409-427`) already ramps it per level from
   `EffectRealPointsPerLevel`, uncapped as long as `MaxLevel` is 0. Stock precedent: Immolation
   is `(250, +11.5/level)`, Shadowfury is `(342, +1.6)`.

So a Demon Hunter ability is one record that is correct at every level, instead of nine records
plus a `spell_ranks` chain plus a supersede graph.

**The price is not yet paid.** With a rank ladder the tooltip is a literal string in the record
the client is reading, so it cannot be wrong. With `EffectRealPointsPerLevel` the client has to
do the same per-level arithmetic the server does to render `$s1`. It is believed to — that is
how stock Immolation Aura reads correctly at every level — but **this has not been verified on
this client**, and it is the first thing to check in game (§6, step 11).

### 4.2 The level cap is 60 today

`conf/worldserver.conf:276` is `# PHASE MaxPlayerLevel p1=60 p2=70 p3=80`, live at 60. The
ladder is written for the eventual cap and phases in with the realm:

| phase | cap | abilities |
|---|---|---|
| 1 | 60 | 20 of 22, Darkness landing exactly at the cap |
| 2 | 70 | 21 — Infernal Strike |
| 3 | 80 | all 22, and the top of every scaling curve |

That matches the Death Knight, whose own ladder runs to 65 against the same cap. Compressing
everything below 60 would mean re-tuning the class twice as the realm advances.

### 4.3 One ability is not in the class's spell family

**Vengeful Retreat carries `SPELLFAMILY_HUNTER` (9), and it has to.**
`SpellEffects.cpp:5060-5072` ends with

```cpp
unitTarget->JumpTo(speedxy, speedz, m_spellInfo->SpellFamilyName != SPELLFAMILY_HUNTER);
```

and `Unit::JumpTo` opens `float angle = forward ? 0 : M_PI;`. So the leap goes **backward** if
and only if the spell's family is 9. There is no other input. A Vengeful Retreat carrying the
class's own family would leap the player *forwards*, into the thing they are retreating from —
silently, with no error.

It ships family 9 with `SpellClassMask_1/2/3` all zero. The zeroed masks are what make that
safe: `IsAffected` requires a non-zero mask overlap, so no hunter talent, glyph or set bonus can
reach it. No Demon Hunter talent can either, which is an accepted loss — a fixed-distance leap
has nothing worth modifying.

---

## 5. Building and installing

### 5.1 Prerequisites

Same as the Death Knight's (Python 3, StormLib, the stock server DBCs, the working client, **a
reachable world DB**) — see [death-knights.md](death-knights.md) §4.1. The database requirement
is not optional and is the same one: `player_class_stats`, the spawn points and the seven
gametable blocks are all **derived from the live Rogue rows**, never transcribed.

### 5.2 Build the archive

**There is one archive and there cannot be two.** MPQ resolution is whole-file per archived path
by archive priority, so two archives cannot both supply `Spell.dbc` — the higher-priority one
wins outright and the other's records are simply not there. `patch-Z.MPQ` is already the top of
the resolved chain, so there is no second slot either:

* a `patch-Y.MPQ` would be silently shadowed and never read;
* a second generator writing `patch-Z.MPQ` would silently delete every Death Knight rank.

Neither failure produces an error. Both produce a client quietly missing half a class. So the
two generators **chain**, and the wrapper is the documented way to run them:

```bash
scripts/build-client-patch.sh --install
```

which is:

```bash
dkspells.py --no-mpq --out .work/out    # writes 3 patched DBCs, builds no archive
dhspells.py          --out .work/out    # reads those, appends, builds patch-Z.MPQ from the union
```

The finished archive holds **22 files**: seventeen DBCs, three patched UI files and two class-icon
atlases. The build is reproducible — two consecutive runs produce a byte-identical archive.

`scripts/package-client.sh` calls this wrapper too, and additionally **patches the staged
`Wow.exe`**. That is not optional: a pack carrying the archive on a stock binary is a pack whose
character-creation screen has no class buttons at all, for every race (§2). The pack manifest
records the exe's md5 and whether its signature checks are neutralised, so "which build are you
on" stays answerable for both halves.

### 5.3 What is in the archive, and what is not committed

| stored path | what it is |
|---|---|
| `DBFilesClient\Spell.dbc` | stock + 85 Death Knight records + the Demon Hunter's |
| `DBFilesClient\ChrClasses.dbc` | 11 records — class 10 inserted **between** 9 and 11, so the create-screen button lands there too |
| `DBFilesClient\CharBaseInfo.dbc` | 64 records — `(4,10)` and `(10,10)` added, nothing else |
| `DBFilesClient\{SkillLine,SkillRaceClassInfo,TalentTab,Talent,SpellShapeshiftForm,CharStartOutfit,SkillLineAbility}.dbc` | the class's skill lines, talent tabs, demon form and starting outfits |
| `DBFilesClient\gt*.dbc` (7) | the class-10 gametable blocks — see §9.1 |
| `Interface\GlueXML\CharacterCreate.{lua,xml}` | `MAX_CLASSES_PER_RACE = 11`, the 11th button, `CLASS_ICON_TCOORDS.DEMONHUNTER` |
| `Interface\FrameXML\Constants.lua` | `CLASS_SORT_ORDER`, `RAID_CLASS_COLORS`, `CLASS_ICON_TCOORDS` |
| `Interface\Glues\CharacterCreate\UI-CharacterCreate-Classes.blp` | the class-icon atlas, one cell repainted |
| `Interface\TargetingFrame\UI-Classes-Circles.blp` | the in-game round icons, same cell |

**The UI files are stored in this repo as patches, not as copies.** Two reasons, and the second
is load-bearing: a verbatim copy of a Blizzard file is a redistribution question that a 26-line
diff is not, and *a patch fails when the file underneath it changes* while a copy silently wins.
The generator extracts the stock file from the client's own archive chain, applies the patch with
`--fuzz=0`, and adds the result. There is no checked-in copy of a Blizzard file anywhere.

The two `.blp` atlases are likewise build output, rebuilt by `tools/dh_icons.py` from Blizzard's
own atlas plus one of Blizzard's own icons.

### 5.4 The addon

`client/addons/mod-demon-hunter/DemonHunter`, declared in `client/addons.txt`. It is shipped to
**everyone**, not just Demon Hunters, and that is deliberate: `ClassUI.lua` is not class-gated,
because the character who errors on a missing `CLASS_ICON_TCOORDS.DEMONHUNTER` is the priest
grouped with one, not the Demon Hunter.

---

## 6. Verification checklist

Run top to bottom the first time. Each line has one unambiguous pass condition.

**Client, before any Demon Hunter exists**

1. `client/tools/patch-wow-exe.py --check` reports **patched** at both sites.
2. Launch the client. It reaches the login screen. *(If it does not, the exe patch and the
   archive disagree — see §10.)*
3. `Logs/GlueXML.log` **is not created**. Its presence means the signature check fired, i.e. the
   exe is stock and the archive is patched.
4. The character-creation screen shows **eleven** class buttons for a Night Elf, with **Demon
   Hunter** among them, its own icon, and no Lua error.
5. Select Human. Demon Hunter is present but **greyed out and disabled**, with no error dialog.

**Server, before creating anything**

6. Worldserver boots. The log contains no `initial level does not have stats data`.
7. `.lookup spell Demon's Bite` lists **91000**.

**Creation**

8. Create a Night Elf Demon Hunter — it succeeds, and you wake up in **Teldrassil at level 1**.
9. Try to create a Human one with a crafted packet: it fails. `playercreateinfo` having rows for
   exactly two races is the real gate; `CharBaseInfo.dbc` only greys the button out.
10. Character sheet: Agility matches a level-1 Night Elf **Rogue**, energy bar reads 100/100.

**In world**

11. **Action bar slot 1 is Demon's Bite, and its tooltip damage matches what the combat log
    rolls.** This is the acceptance criterion for §4.1 and the one open question in the design.
12. Dodge and parry on the character sheet are non-zero and not `NaN`. If they are wrong, the
    core patch did not apply.
13. `/dump GetSpellInfo(91500)` returns `Double Jump`. Jump, then press the jump key again in
    mid-air — you jump again.
14. At 10, the talent panel opens with **three tabs named Havoc, Vengeance and Illidari**. If it
    is empty, `CLASSMASK_ALL_PLAYABLE` did not get patched.
14a. **Equip a second one-hand weapon.** If the off-hand slot is not offered, SkillLineAbility
    610 was not widened (§3.2) and the class cannot dual wield.
14b. **Level from 1 to 2 and check the spellbook gained nothing but Chaos Strike.** A pile of
    unrelated spells — Parry, Intercept, Vampiric Touch — means
    `build/patches/0002` did not apply and `mod-learn-spells` is treating the class as
    family 0.
15. At 40, Metamorphosis turns you into Illidan and back.

**Robustness**

16. `.character level <name> 20` **offline**, then log in. Everything owed by 20 is present —
    this is what the module's login pass exists for.
17. Log in an existing Rogue. Unchanged: same name, same spells, same talents.
18. Restart worldserver. Nothing regressed, no duplicate spellbook entries.

---

## 7. Double jump, and why it lives in the addon

The client will not send a second `MSG_MOVE_JUMP` while airborne, and that pattern is exactly
what jump-hack detection looks for — so the second jump cannot originate on the server. It has to
be initiated client-side, and every cast entry point the client has is protected against addon
code.

The addon therefore installs a **priority override binding** over the jump key pointing at a
secure action button. Three consequences worth knowing:

* `SetOverrideBindingClick` is `#nocombat`. A key bound — or a `/reload` done — during combat
  cannot install the override. The `Bindings.xml` bodies are diagnostics for exactly that case,
  not fallback actions, so the player is told why nothing happened instead of getting a dead key.
* `SetPropagateKeyboardInput` **does not exist in this client build** (0 hits in `Wow.exe`), so
  raw key sniffing was never an option.
* A player who disables the addon loses the feature silently. **The class is not balanced around
  it.**

---

## 8. ID plan

The trees cost **212 `Spell.dbc` records** — 207 talent ranks plus 5 trigger rows for the proc
talents — at ids 92000–92211, leaving 788 of that band spare. A talent rank *is* a spell: "+2%
per rank, five ranks" is five records carrying 2, 4, 6, 8 and 10 and one `Talent.dbc` row listing
all five ids. That is how every stock tree is built and there is no cheaper shape.

Talent ranks deliberately get **no** `SkillLineAbility` rows — a talent spell is granted by the
talent system, and an SLA row would make it learnable twice.

```
1 ..  80864   stock Spell.dbc, strictly ascending
80865..89999  deliberately unused -- where an "append after max" tool would land
90000..90219  Death Knight, 11 blocks of 20
90220..90999  Death Knight growth buffer -- do not take
91000..91999  DEMON HUNTER abilities, 20-wide blocks
92000..92999  DEMON HUNTER talent ranks
93000..99999  free
100001+       AzerothCore's own serverside band
```

Other bands: SkillLineAbility `23000+` (stock max 21980, the DK took 22000), SkillLine
**800–802** (stock max 788), TalentTab **412–414** (stock max 411), Talent **2300+** (stock max
2285), SkillRaceClassInfo **980+** (stock max 970), CharStartOutfit **368–371** (stock max 367,
which already includes the DK's 348–367), SpellShapeshiftForm **23** (blank in stock).

The ceiling is not a DBC limit. It is the 24-bit action-button packing —
`MAX_ACTION_BUTTON_ACTION_VALUE = 0x00FFFFFF+1` (`Player.h:235`). A spell above that cannot be
dragged onto a bar. We are three orders of magnitude below it.

**Blocks are fixed forever.** A reserved-and-vacant block stays reserved and vacant; reusing one
would silently repoint a spell some character already has in `character_spell`.

---

## 9. Known and accepted anomalies

### 9.1 Blizzard's vacant class slot was not empty, it was full of placeholders

This is the trap that would have been hardest to find in play rather than in a file. The
class-10 rows of the per-class gametables are not zeroed — they are populated with junk:

| gametable | class 10, stock | now (Rogue's) |
|---|---|---|
| `gtChanceToMeleeCritBase` | **0.2** — twenty percent base melee crit | −0.00295 |
| `gtChanceToSpellCritBase` | 0.2 | 0 |
| `gtChanceToMeleeCrit` | 0.01 — about 4× a Rogue's crit per agility | 0.004476 |
| `gtOCTRegenHP` | 1.0 | 0.365854 |
| `gtRegenHPPerSpt` | 0.0 | 1.0 |

All seven are overwritten with the Rogue's block, in both halves — the server reads its
`gt*_dbc` override rows, the client renders the character sheet from its own copy.

### 9.2 Every Demon Hunter is Illidan in demon form

Display **21135** — `Creature\Illidan\Illidan.mdx`, verified present in
`CreatureDisplayInfo.dbc` — for every race and gender. A deliberate trade of personalisation for
iconography: a female blood elf becomes a male night elf demon.

It comes from the form's own DBC row, whose two model columns (alliance and horde) both hold
21135. There are deliberately **no `player_shapeshift_model` rows**:
`Unit::GetModelForShapeshift` (`Unit.cpp:15455`) consults that table first and falls back to the
DBC, and the table is keyed by `(form, race, customizationID, genderID)` — it exists so a druid's
cat form can vary with hair colour, which is a problem this class does not have. Two cells beat
one row per race per gender per customization.

If a per-race demon is ever wanted it becomes rows there, and the column names are not what they
look like: `ShapeshiftID, RaceID, CustomizationID, GenderID, ModelID`. A model missing from
`CreatureDisplayInfo.dbc` makes the loader skip the row with a log line rather than fail
(`ObjectMgr.cpp:1874`).

**The form's flags are copied from row 22 (`0xd8`) and that is load-bearing, not lazy.** Decoded
against `UnitDefines.h:107-123`:

| bit | flag | effect here |
|---|---|---|
| `0x08` | `CAN_NPC_INTERACT` | you can still talk to an NPC in demon form |
| `0x10` | `DONT_USE_WEAPON` | your own weapons are hidden — **wanted**, because the Illidan model carries its own warglaives and the player's would clip through them |
| `0x40`, `0x80` | `CAN_USE_EQUIPPED_ITEMS`, `CAN_USE_ITEMS` | both NYI server-side |

What it must **not** acquire is `0x400 CAN_ONLY_CAST_SHAPESHIFT_SPELLS`. `UnitDefines.h:117`
marks it NYI and that comment is wrong — `SpellInfo::CheckShapeshift` reads it at
`SpellInfo.cpp:1490`, and a form carrying it silences every spell whose `Stances` mask does not
include the form. A Demon Hunter in demon form would be able to cast nothing at all. `0xd8` does
not include it; the generator asserts the copy rather than trusting it.

### 9.3 No backflip animation

3.3.5a has no backflip. Vengeful Retreat renders as a jump translating backwards. Mechanically
correct, visually approximate, and not fixable without importing an animation.

### 9.4 The create-screen flavour text is ours, not Blizzard's

`GlueStrings.lua` has no `CLASS_DEMONHUNTER`, and forking a 77 KB locale file to add four
strings would mean re-forking it after every locale change. The strings are defined defensively
in `CharacterCreate.lua` instead, guarded so a real `GlueStrings` entry would still win.

### 9.5 Playerbots

`mod-playerbots` has no Demon Hunter AI. Bots must not be created as class 10; if
`RandomPlayerbotFactory` starts producing them, that is the first thing to check.

---

## 10. When it goes wrong

| symptom | cause | fix |
|---|---|---|
| Client shows ten class buttons, no Demon Hunter | the archive is not loading | `dhspells.py --verify`; see [death-knights.md](death-knights.md) §4.4 — the ladder is identical |
| **Character creation is broken for every race**, all buttons blank | the archive has 11 `ChrClasses` records and the exe is **stock** | `client/tools/patch-wow-exe.py` |
| `Logs/GlueXML.log` says `modified or corrupt` | same | same |
| Client will not start at all | exe patched against a different build | `--revert`, then re-check the client version |
| Talent panel empty at 10 | `CLASSMASK_ALL_PLAYABLE` not patched | rebuild the image; `git apply --check build/patches/*.patch` |
| Demon Hunter never dodges or parries | the six float tables not patched | same |
| Worldserver exits, `Race N class 10 initial level does not have stats data!` | the boot gate — it is `player_class_stats`, **not** `playercreateinfo`, and the message blames the wrong table | apply `00_class.sql` and restart before anything makes class 10 creatable |
| Vengeful Retreat leaps **forwards** | its `SpellClassSet` is not 9 | §4.3 |
| Tooltip damage ≠ combat log | §4.1's open question | check `EffectRealPointsPerLevel` rendering before assuming drift |

---

## 11. Rollback

In increasing order of thoroughness.

**11.1 Stop new Demon Hunters (seconds, no restart).** `CharacterCreating.Disabled.ClassMask`
is checked at `CharacterHandler.cpp:335`; set bit 9 (512) and `.reload config`.

**11.2 Stop the module granting anything (seconds, no restart).**
`DemonHunter.Enable = 0` in `conf/modules/mod_demon_hunter.conf`, then `.reload config`. Already
granted spells stay granted; this stops future grants.

**11.3 Remove the class (requires a restart).** Write a down-migration — deleting the generated
SQL undoes nothing, because the updater tracks files by name and SHA1 and module rows are exempt
from orphan cleanup. Delete the `chrclasses_dbc`, `player_class_stats`, `spell_dbc`,
`skilllineability_dbc`, `talent*_dbc`, `skillline*_dbc`, `spellshapeshiftform_dbc`,
`charstartoutfit_dbc`, `playercreateinfo*` and gametable rows in the ID bands of §8, then restart.

Characters that already learned a removed spell self-heal: `Player::_addSpell` finds no
`SpellInfo`, calls `DeleteSpellFromAllPlayers` and logs once.

**Existing Demon Hunters are not migrated.** After 11.3 they are characters of a class that no
longer exists. `.character level` them into something else or delete them; there is no automatic
migration and there should not be one.

**11.4 Un-patch the client.** `client/tools/patch-wow-exe.py --revert`, and delete
`Data/patch-Z.MPQ` — but note that removing the archive also removes the **Death Knight**, since
there is one archive for both. Rebuild it with `scripts/build-client-patch.sh` instead if the
Death Knight is meant to survive.

---

## 12. Where everything lives

| thing | path |
|---|---|
| Spec — the source of truth | `build/modules/mod-demon-hunter/tools/dh_spec.py` |
| Donor cells, per ability | `build/modules/mod-demon-hunter/tools/dh_donors.py` |
| The three talent trees, as data | `build/modules/mod-demon-hunter/tools/dh_talents.py` |
| Generator | `build/modules/mod-demon-hunter/tools/dhspells.py` |
| Class icons | `build/modules/mod-demon-hunter/tools/dh_icons.py`, notes in `ICONS.md` |
| Generated SQL | `build/modules/mod-demon-hunter/data/sql/db-world/base/*.sql` |
| Generated progression header | `build/modules/mod-demon-hunter/src/dh_progression.h` |
| Module source | `build/modules/mod-demon-hunter/src/*.cpp` |
| Module config (live, bind-mounted) | `conf/modules/mod_demon_hunter.conf` |
| Client UI patches | `build/modules/mod-demon-hunter/client/*.patch` |
| Addon | `client/addons/mod-demon-hunter/DemonHunter/` |
| Core patch | `build/patches/0001-demon-hunter-class-10.patch` + its `README.md` |
| Module patch (mod-learn-spells) | `build/patches/0002-learn-spells-skip-demon-hunter.patch` |
| Client exe patcher | `client/tools/patch-wow-exe.py` |
| Shared DBC tooling | `build/tools/acdbc/` |
| Build wrapper | `scripts/build-client-patch.sh` |
| Build artefacts | `.work/out/` (gitignored) |
| Server DBCs — **never modified** | `/srv/wow/data/dbc/` |

Numbers worth having memorised: class **10**, races **4** and **10**, spell family **16**,
shapeshift form **23**, display **21135**, spell band **91000+**, talent tabs **412–414**, and
the two patch sites **0x004da7e5** and **0x0052abd9**.
