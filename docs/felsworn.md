# Felsworn — an eleventh playable class

Felsworn is a **real class** on this realm, not a reskin and not an opt-in conversion. It is
class **10**, it appears as its own button on the character-creation screen with its own name,
icon and colour, only Night Elves and Blood Elves can roll one, and it levels 1→80 like anybody
else. Rogues are untouched.

**Its content is imported, not invented.** The abilities, the talent trees and every balance
number come from Project Ascension's class 14, read directly out of an installed Ascension
client and transplanted record-for-record. §13 is how that works and what it does and does not
give you. The class that previously occupied slot 10 was a hand-built Felsworn; it is
preserved on the `demon-hunter-v1` branch and §11 is still its rollback.

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
| Class | Felsworn, **class 10** — the vacant `//CLASS_UNK` slot between Warlock and Druid |
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
  bonus"; `StatSystem.cpp:827` evaluates `0*0/(0+0*0)` and every Felsworn gets **NaN dodge
  for its entire life**, never dodging or parrying, while the character sheet displays a
  plausible number.

### 3.1 And one patch to a module

`build/patches/0002-learn-spells-skip-demon-hunter.patch`. `mod-learn-spells` is pinned and
enabled, and its `GetSpellFamily` has a `default: return SPELLFAMILY_GENERIC` that class 10 is
the first class ever to reach. Family 0 is the family of every unclassed spell in the game, and
the scan has no class check — so a Felsworn would be handed **15 junk spells at level 1**
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

Thirty-one abilities, levels 1 to 70, plus 114 talents across three trees. Every one is an
Ascension record transplanted whole — see §13 — so the numbers are theirs, re-ranked to our
level ladder rather than re-invented.

### 4.1 The resource, and why it is not a power bar

The bar under the character is **Energy**, and it cannot be anything else: `ChrClasses.dbc` has
exactly one `DisplayPower` per class. Layered on top is **Felfury**, which is *not* a power
type. It is a stacking self-aura — spell 91460, whose own imported description reads
"Represents your Felfury charges" — capped at five by its `CumulativeAura` cell.

That cell is the cap. The talented generation path runs through the module and can clamp to
anything; the pure-data path is an authored `TRIGGER_SPELL -> felfury` on the generators, and
`Aura::ModStackAmount` clamps that against `CumulativeAura` and nothing else
(`SpellAuras.cpp:973-980`). Ascension ships the cell as **0** because their engine caps the pool
in code, so the transplant brings a 0 across and the pool would hold exactly one charge forever.
`fs_abilities.CELL_OVERRIDES` writes the real cap, and the generator asserts it agrees with
`dh_spec.FELFURY_MAX_STACKS`, which is what the module and the conf read.

The loop at level 1 is complete: two Twin Slices (45 Energy each, +1 Felfury each) pay for one
Sargeron Smite, which costs 0 Energy, spends 2 Felfury and refunds 20 Energy.

### 4.2 Inner Demon

Spell 91480, learnable at level 2 — Ascension's own `SpellLevel`, not a choice made here. It is
a genuine shapeshift (`SPELL_AURA_MOD_SHAPESHIFT`) and it is a Felfury **dump**, not a capstone:
its duration is bought with the pool at `INNER_DEMON_MS_PER_FELFURY` per stack.

Its `EffectMiscValue` arrives as form **56** and must become **23**. Form 56 can be entered but
nothing can ever gate on it — `SpellInfo::Stances` is a `uint32` (`SpellInfo.h:357-358`) and
`DBCfmt.h:110` marks the high dwords `x`, so `1 << 55` is unrepresentable and every form-gated
talent would silently never apply. 23 is the slot `dh_spec.SHAPESHIFT_FORM_ID` reserves.

The duration is script and not data. `Player::ApplySpellMod` applies a flat `SPELLMOD_DURATION`
exactly once and never multiplies it by a stack count, so Ascension's +5000 ms modifier would
give one Felfury and five Felfury the same five seconds.

### 4.3 The ladder

Nine abilities are real rank ladders — Twin Slice has eight ranks, Sargeron Smite and Fel
Fireball nine each — which is the first time this repo has generated one. A ladder needs three
things the Death Knight never did: consecutive ids out of the ability's 20-id block,
`SkillLineAbility.SupercededBySpell` chaining (without it all eight Twin Slice ranks sit on the
action bar at once), and `spell_ranks` rows, which is what tells the core that eight records are
one ability.

`build/modules/mod-demon-hunter/tools/fs_abilities.py` is the list, and it is the source of
truth. Do not read the ladder out of this document.
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
| `DBFilesClient\Spell.dbc` | stock + 85 Death Knight records + the Felsworn's |
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
**everyone**, not just Felsworn, and that is deliberate: `ClassUI.lua` is not class-gated,
because the character who errors on a missing `CLASS_ICON_TCOORDS.DEMONHUNTER` is the priest
grouped with one, not the Felsworn.

---

## 6. Verification checklist

Run top to bottom the first time. Each line has one unambiguous pass condition.

**Client, before any Felsworn exists**

1. `client/tools/patch-wow-exe.py --check` reports **patched** at both sites.
2. Launch the client. It reaches the login screen. *(If it does not, the exe patch and the
   archive disagree — see §10.)*
3. `Logs/GlueXML.log` **is not created**. Its presence means the signature check fired, i.e. the
   exe is stock and the archive is patched.
4. The character-creation screen shows **eleven** class buttons for a Night Elf, with **Demon
   Hunter** among them, its own icon, and no Lua error.
5. Select Human. Felsworn is present but **greyed out and disabled**, with no error dialog.

**Server, before creating anything**

6. Worldserver boots. The log contains no `initial level does not have stats data`.
7. `.lookup spell Demon's Bite` lists **91000**.

**Creation**

8. Create a Night Elf Felsworn — it succeeds, and you wake up in **Teldrassil at level 1**.
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

## 7. The addon, and what it is for

The Demon Hunter's addon existed to cast two movement spells from a key. Felsworn has no
movement abilities at all, so `Bindings.xml` is gone and `Movement.lua` has been replaced by
`Felfury.lua`, which does the one job the default UI cannot.

Felfury is a stacking buff, not a power type, so the client has no concept of it being a
resource. Without the addon a player reads their own resource by finding an icon in the buff
tray and squinting at its stack count. `Felfury.lua` puts the count above the player frame,
green while banking and gold at cap, with a marker while Inner Demon is up.

It depends on one thing that can break silently: `UnitAura` can only see an aura the server
sent, and the server only sends an aura with a client-visible slot. `CanBeSentToClient`
(`SpellAuras.cpp:1088`) denies a slot to a **passive** aura, so the Felfury record must never
carry `SPELL_ATTR0_PASSIVE`. If it ever does, the tracker keeps working, finds nothing, and
reports zero forever — because "the player has no Felfury" is an ordinary thing for it to see.
That is the first thing to check if the counter never moves.

The two spell ids in that file are **generated**. `dhspells.py` rewrites them from the id
allocation on every build. This is not hypothetical caution: the Demon Hunter left
`DH_SPELL_DOUBLE_JUMP = 91500` behind, and under Felsworn 91500 is Bane of Fire — the jump key
would have cast a debuff at whatever the player was looking at.
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

### 9.0 Thirty baseline passives were dropped, and one of them is load-bearing

**This is the largest known gap in the port.** Ascension's class 14 has four advancement tabs,
not three: Demonology, Slaying and Felblood became our talent trees, and a fourth tab named
"Class" holds **37 passives** that modify the baseline abilities. WotLK renders exactly three
talent tabs, so that fourth tab had nowhere to go. Seven of its nodes are castable and became
baseline abilities; the other **thirty were dropped**.

They are where the class's depth lives — *Felstrider*, *Doomstride* and *Mark of Chaos* all
modify Chaos Rush; *Infernal Armor*, *Illidari Barrier* and *Anti-Magic* all modify Hateforged
Barrier; *Cruelty*, *Demonic Evasion* and *Elemental Bane* are flat combat stats. Without them
the abilities work and do not interact.

**Felheart (301287) is the one that matters most.** Its description is "Each Felfury active now
increases your haste by $s1%", and it is the only thing that gives Felfury's three carrier auras
a non-zero amount — they all ship with `EffectBasePoints -1`, i.e. **amount zero**, by design,
waiting for exactly this passive to fill them in. Without Felheart, banking Felfury does nothing
at all until it is spent: the resource is a currency and not a ramp, which is half the mechanic.
`dh_progression.h` reflects this honestly — `kDhFelheartRanks` is generated **empty**, and the
module's recompute path is therefore dead code today.

Fixing it means finding room for a fourth tree's worth of passives in a three-tab UI. The
options are to fold the best of them into the existing trees as extra tiers, to attach them to
the baseline ladder as level-gated passives, or to accept a shallower class. None is done.

### 9.0.1 Every number is Ascension's, and none has been measured here

Carried forward verbatim from `dh_talents.py`, because it is the caveat that matters most: not
one value in the ladder or the trees has been measured on this realm. They were balanced by
another project against another server's stat curves, another item budget, and a **classless**
progression where any ability could be combined with any other. Ported into a class-based ladder
they are a starting point with a real pedigree, which is not the same thing as balanced.

Roughly 35 talents also depend on a `ProcTypeMask` authored from `SpellMgr.h` rather than
observed. Expect a pass where several passives simply never fire.


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

### 9.2 Every Felsworn is Illidan in demon form

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
include the form. A Felsworn in demon form would be able to cast nothing at all. `0xd8` does
not include it; the generator asserts the copy rather than trusting it.

### 9.3 No backflip animation

3.3.5a has no backflip. Vengeful Retreat renders as a jump translating backwards. Mechanically
correct, visually approximate, and not fixable without importing an animation.

### 9.4 The create-screen flavour text is ours, not Blizzard's

`GlueStrings.lua` has no `CLASS_DEMONHUNTER`, and forking a 77 KB locale file to add four
strings would mean re-forking it after every locale change. The strings are defined defensively
in `CharacterCreate.lua` instead, guarded so a real `GlueStrings` entry would still win.

### 9.5 Playerbots

`mod-playerbots` has no Felsworn AI. Bots must not be created as class 10; if
`RandomPlayerbotFactory` starts producing them, that is the first thing to check.

---

## 10. When it goes wrong

| symptom | cause | fix |
|---|---|---|
| Client shows ten class buttons, no Felsworn | the archive is not loading | `dhspells.py --verify`; see [death-knights.md](death-knights.md) §4.4 — the ladder is identical |
| **Character creation is broken for every race**, all buttons blank | the archive has 11 `ChrClasses` records and the exe is **stock** | `client/tools/patch-wow-exe.py` |
| `Logs/GlueXML.log` says `modified or corrupt` | same | same |
| Client will not start at all | exe patched against a different build | `--revert`, then re-check the client version |
| Talent panel empty at 10 | `CLASSMASK_ALL_PLAYABLE` not patched | rebuild the image; `git apply --check build/patches/*.patch` |
| Felsworn never dodges or parries | the six float tables not patched | same |
| Worldserver exits, `Race N class 10 initial level does not have stats data!` | the boot gate — it is `player_class_stats`, **not** `playercreateinfo`, and the message blames the wrong table | apply `00_class.sql` and restart before anything makes class 10 creatable |
| Vengeful Retreat leaps **forwards** | its `SpellClassSet` is not 9 | §4.3 |
| Tooltip damage ≠ combat log | §4.1's open question | check `EffectRealPointsPerLevel` rendering before assuming drift |

---

## 11. Rollback

In increasing order of thoroughness.

**11.1 Stop new Felsworn (seconds, no restart).** `CharacterCreating.Disabled.ClassMask`
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

**Existing Felsworn are not migrated.** After 11.3 they are characters of a class that no
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


---

## 13. Where the content came from

The class is an **import**. `build/tools/ascension/` reads an installed Project Ascension client
and transplants whole `Spell.dbc` records; nothing about the abilities was authored here.

**Why a transplant beats a donor.** Every previous class in this repo was built by memcpy-ing a
stock Blizzard spell and overriding named cells (`dh_donors.py`). That exists because no record
anywhere described the ability, so the donor's value was in the ~222 cells nobody names. For an
import there *is* such a record and it is better than any donor: it **is** the ability, including
the cells no one thought to name. Ascension kept Blizzard's layout exactly — 234 fields,
936-byte records, verified on open — so the record transplants whole.

**The one thing that makes it non-trivial.** String columns hold *offsets into the source file's
own string block*, not text. A raw byte copy carries offsets that index into our string block and
produce garbage — or, worse, a valid-looking wrong string. `importer.py` resolves every string
column to text on the way through, which is why it returns a dict of Python values and not bytes.

**Four generator capabilities exist only because of this**, and each is inert for a hand-built
class — the Demon Hunter rebuilt byte-identical after every one:

| capability | why |
|---|---|
| rank ladders + `SupercededBySpell` | nine imported abilities have real rank chains |
| `spell_ranks` emission | without it the core does not know eight records are one ability |
| the effect/aura range gate | `SpellMgr.cpp:3039` **asserts** on effects > 164 or auras > 316. Ascension's private effects (175, 183) and auras (317, 353, 354) are ordinary data in their file and a worldserver that will not boot in ours |
| source-reference remapping | a transplanted record's `EffectTriggerSpell` and `*AuraSpell` cells hold the *source server's* ids. Each is remapped to ours, or zeroed and reported. A stale foreign id is a live pointer into whatever our file happens to have at that number |

`extract_class.py` also re-derives and re-checks its recovered column offsets on every run —
`CharacterAdvancement.dbc`'s header field count is **not** `record_size / 4`, so trusting it
reads past the end of every record into the next one. An Ascension patch that moves a field
fails loudly instead of importing garbage.

**What did not come across.** Balance and tree structure did. Behaviour did only where it fits
WotLK's vocabulary: 12 distinct spell effects and 50 aura types, dominated by
`PROC_TRIGGER_SPELL` and the two spell-modifier auras, which is stock talent machinery. What
needed C++ was the dummy auras, the class-script overrides, and six genuinely custom effects.
Cut as unportable: aura 317 (three talents), spell charges, Ascension's combo system, a second
power bar, and `Manaburn` — whose tooltip promises "200% of your Stamina" while its only effect
is `POWER_BURN` base 0, die sides 1, i.e. **one mana**.
