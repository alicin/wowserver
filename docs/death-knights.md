# TRUE level-1 Death Knights

Death Knight is a normal class on this realm. You roll one, you start at **level 1** in Northshire
with warrior-tier stats and gear, you have a rune bar and one rune ability, and you level 1→80 like
anybody else. No Acherus, no free level 55, no starter chain.

This document is the one you read six months from now, or the one you send a friend whose Icy Touch
tooltip says the wrong number. It covers what ships, why it is built the way it is, **how to
generate and install the client patch**, how to verify it, what is knowingly broken, and how to turn
the whole thing off.

The full design record — every decision with its evidence, every conflict between the recon passes
and which side won — is `.work/notes/DESIGN.md`. **`.work/` is gitignored**, so that file lives only
on the dev box and may not be there when you come looking; this document is the durable one, and
every load-bearing fact from the design is restated here with its citation. Server tuning is
[server-config.md](server-config.md), client setup is [client.md](client.md), modules are
[modules.md](modules.md).

> **Before you touch `conf/worldserver.conf`, read [§6 The boot gate](#6-the-boot-gate).**
> Flipping `StartHeroicPlayerLevel` in the wrong order kills worldserver at boot with an error
> message that blames the wrong thing entirely.

---

## 1. What ships

### 1.1 The slice that exists today

| | |
|---|---|
| Class | Death Knight (class 6), Human only for now |
| Start | level **1**, Northshire Abbey (map 0, zone 12, `-8949.95 -132.493 83.5312`) |
| Stats | identical to a level-1 Human warrior (Str 23 etc.) |
| Gear | Recruit's Shirt / Pants / Boots + Worn Greatsword, equipped |
| Resources | 6 runes, 0/100 runic power, both from level 1 |
| Abilities at 1 | **Icy Touch (Rank 1)** — custom spell `90000`, 10–12 Frost damage, 1 Frost rune, 20 yd, instant, applies Frost Fever |
| Utility at 1 | Death Gate (50977), Runeforging (53428) |
| Talents | open at level **10**, like every other class |
| Riding | Apprentice at 20, Journeyman at 40 |
| At 55 | the stock level-55 Icy Touch (45477) supersedes rank 1, and the rest of the stock DK kit arrives on the normal curve |

Everything from level 55 up is untouched. The 13 existing level-55+ DKs on the realm keep their
spells, their damage and their spellbook layout — see [§9.6](#96-existing-55-death-knights).

### 1.2 The Icy Touch ladder

Only **rank 1 is implemented** — it is the only `CustomRank` in `tools/dk_spec.py` today. The
remaining ranks are ID-reserved and will come out of the same generator when they are added to the
spec. The indicative curve is `avg(L) = round(9.5 + (132 − 9.5)·(L−1)/54)`,
`die = max(1, round(0.08·avg))`, `BP = round(avg − (die+1)/2)`, which lands the ladder here:

| rank | learn level | spell ID | damage | status |
|---|---|---|---|---|
| 1 | 1 | **90000** | **10–12** | **shipped** — hand-calibrated, overrides the curve (see below) |
| 2 | 7 | 90001 | 23–24 | planned |
| 3 | 13 | 90002 | 36–38 | planned |
| 4 | 19 | 90003 | 49–52 | planned |
| 5 | 25 | 90004 | 62–66 | planned |
| 6 | 31 | 90005 | 76–81 | planned |
| 7 | 37 | 90006 | 88–94 | planned |
| 8 | 43 | 90007 | 102–109 | planned |
| 9 | 49 | 90008 | 114–122 | planned |
| 10 | 55 | 45477 | 127–137 | **stock**, unchanged |

Spell IDs are `90000 + rank_index` out of the Icy Touch block (§1.3); the levels and damage of the
planned rows are the curve's, and are tunable — the spec is the authority, not this table.

Rank 1 ships as `BasePoints 9 / DieSides 3` → 10–12, not the curve's flat 10, because it was
calibrated against real level-1 content rather than against the top of the curve:

```
133 Fireball       Rank 1   lvl 1   BP 13  die 9   -> 14-22, 1.5 s cast
 78 Heroic Strike  Rank 1   lvl 1   BP 10  die 1   -> +11 on a swing
90000 Icy Touch    Rank 1   lvl 1   BP  9  die 3   -> 10-12, instant, 20 yd, + a disease
```

Frost Fever comes along free on every rank: the cloned row carries `Effect_2 = 64`
(`SPELL_EFFECT_TRIGGER_SPELL`) with `EffectTriggerSpell_2 = 55095`, and 55095 is **not** re-ranked,
so it behaves exactly as it does at 80 (~0 base damage + 0.06325·AP at level 1, plus the −14% attack
speed slow). There is no `spell_linked_spell` row and no SpellScript involved. Do not add one.

**Note on the current slice, in the interest of not being surprised in-game:** between levels 1 and
54 a Death Knight has *one* attack button plus autoattack. Plague Strike, Blood Strike, Death Coil,
Death Strike and the presences are all still level-55 spells. Their ID blocks are reserved
(§1.3) but nothing is granted below 55 yet.

### 1.3 Reserved ID blocks

Fixed now so IDs never move. 20 IDs per stock ability, block index = order in the progression:

```
90000-90019  Icy Touch       (stock rank 1 = 45477)   <- only 90000 exists today
90020-90039  Plague Strike   (45462)
90040-90059  Blood Strike    (45902)
90060-90079  Death Coil      (47541)
90080-90099  Death Strike    (49998)
90100-90119  Blood Presence  (48266)
SkillLineAbility: 22000 + (spellId - 90000)
```

Why this range: above `Spell.dbc`'s real maximum (80864) so appended records keep the file strictly
ascending; below AzerothCore's own server-side band (100001, 100099–100102, 200100); and three
orders of magnitude below the actual ceiling, which is not a DBC limit at all but the 24-bit action
button packing — `MAX_ACTION_BUTTON_ACTION_VALUE = 0x00FFFFFF+1` (`Player.h:235`). A spell above
that cannot be dragged to a bar.

---

## 2. Why the client patch is not optional

This is the single most important thing to understand about the feature, because it is the reason
the build has a client-side half at all — and the reason a friend without the patch has a broken
experience rather than a slightly worse one.

**AzerothCore cannot produce a spell tooltip. Not "does not"; cannot.**

`Spell.dbc` has 234 columns, of which 16 are `Description_Lang_*` and 16 are
`AuraDescription_Lang_*`. AzerothCore's format string for the file marks every one of them `x` =
`FT_NA`:

```cpp
// src/server/shared/DataStores/DBCfmt.h:110  -- 234 characters, one per column
char constexpr SpellEntryfmt[] = "nii…ssssssssssssssssxssssssssssssssssxxxx…xxx…";
```

Decoding the run of interest by index (`n`/`i`/`f` = parsed, `s` = parsed string, `x` = `FT_NA`):

| fmt idx | columns | code |
|---|---|---|
| 136–151 | `Name_Lang_0..15` | `s` — parsed, the server knows the spell's name |
| 153–168 | `NameSubtext_Lang_0..15` | `s` — parsed, the server knows "Rank 1" |
| **170–185** | **`Description_Lang_0..15`** | **`x`** |
| **187–202** | **`AuraDescription_Lang_0..15`** | **`x`** |

Verified on this checkout: `strlen(SpellEntryfmt) == 234`, and indices **169–203 are a solid run of
`x`**. `FT_NA` fields are read from the row and thrown away (`DBCDatabaseLoader.cpp`, `case FT_NA:
break;`). Downstream, `grep -c 'Description\|ToolTip' src/server/game/Spells/SpellInfo.h` → **0**.
There is no `sSpellIconStore` anywhere in `DBCStores.cpp` either.

So the server knows a spell's name, its rank subtext, its damage, its cost and its cooldown, and it
knows nothing whatsoever about the sentence the player reads when they hover the button. **That
sentence comes out of the client's own `Spell.dbc` and nowhere else.**

The consequence, spelled out:

* **Option A — scale the existing level-55 spell server-side** (a SpellScript that multiplies damage
  by level, or `spell_dbc` overrides on 45477 alone) would leave the client rendering the stock
  string. A level-3 DK hitting for 12 would read *"Chills the target for 127 to 137 Frost damage"*.
  Forever. On every rank. There is no configuration, no module and no hook that fixes that, because
  the field the client renders is never sent over the wire.
* **Option B — a real new spell ID in both halves** puts the true numbers in the client's own DBC.
  `$m1`/`$M1` in the description template read the *cloned row's own* `EffectBasePoints_1` /
  `EffectDieSides_1`, so the shipped description string is literally accurate at every rank without
  a single hand-written string. (`$55095s2` and `$55095d` in the same sentence point at Frost Fever,
  which we deliberately do not re-rank, so those stay accurate too.)

Option B was chosen. The price is exactly one thing: **every player needs a ~5 MB MPQ in their
`Data/` directory.** That is what the rest of this document is about.

---

## 3. Architecture

```
                    tools/dk_spec.py                 <- THE source of truth
              (one entry per custom rank: source spell, new id, learn level,
               base points, die sides, rune cost, skill line, supercede target)
                            |
                    tools/dkspells.py                <- ONE generator
             /              |                \                    \
   data/sql/db-world/  src/dk_progression.h   .work/out/dbc/*.dbc   Data/patch-Z.MPQ
   (server truth)      (module's grant table)  (client truth)        (shipped to friends)
```

Two halves, one generator, and that is the entire point: the tooltip the friend reads and the damage
the server rolls are emitted from the same spec in the same run, and the generator refuses to finish
if they disagree (it compares the SQL row and the DBC row column by column). Hand-editing either
output is how you get "tooltip says 10–12, combat log says 127–137".

### 3.1 Server side is pure SQL. The server's DBC files are never touched.

`/srv/wow/data/dbc/*.dbc` stays **byte-identical to stock**. Nothing in this feature writes there.
Re-extracting DBCs from the client is always safe and can never silently revert the feature.

The mechanism is upstream AzerothCore's, not ours. `DBCStores.cpp` passes a world-DB table name
alongside each DBC:

```cpp
LOAD_DBC(sCharStartOutfitStore,   "CharStartOutfit.dbc",    "charstartoutfit_dbc");     // :296
LOAD_DBC(sSkillLineAbilityStore,  "SkillLineAbility.dbc",   "skilllineability_dbc");    // :369
LOAD_DBC(sSpellStore,             "Spell.dbc",              "spell_dbc");               // :371
```

Rows in those tables are layered over the file at load. `DBCDatabaseLoader` explicitly **grows** the
index table when a row's ID exceeds the file's maximum, so brand-new IDs are a supported path, not a
hack — upstream ships `spell_dbc` IDs 100001/100099–100102/200100 itself and
`boss_twin_valkyr.cpp:695` casts 100101, which exists in no `.dbc` file anywhere.

`acore_world.spell_dbc` on this realm already has **4493 rows** before we add anything. This is a
live upstream mechanism we are joining, not one we are inventing.

Three hard rules on those tables:

* **Never `ALTER` them.** `DBCDatabaseLoader.cpp:125` is
  `ASSERT(sqlColumnNumber == result->GetFieldCount(), …)`. Add or drop one column and worldserver
  aborts at boot. Column counts: `spell_dbc` 234, `skilllineability_dbc` 14,
  `charstartoutfit_dbc` 77. Only `ID` is matched by name; every other column is positional.
* **Never insert a negative ID.** The column is signed `int`; the loader sizes the index table from
  the highest ID via `Get<uint32>()`, so one negative row asks for ~4.29 billion pointers and the
  process dies to the OOM killer before it logs anything useful.
* **There is no hot reload.** `LoadDBCStores` has exactly one call site (`World.cpp:384`). Every
  change to these tables is a full worldserver restart. `.reload config` does not touch them.

### 3.2 Client side is one MPQ

`Data/patch-Z.MPQ` contains three files:

| stored path | what changed |
|---|---|
| `DBFilesClient\Spell.dbc` | stock + one appended record (90000) + rank-subtext rewrites on 45477/49896/49903/49904/49909 → "Rank 2".."Rank 6" |
| `DBFilesClient\SkillLineAbility.dbc` | stock + one appended record (22000) + row 16231 `AcquireMethod` 2→0 |
| `DBFilesClient\CharStartOutfit.dbc` | rows 352/353 (Human DK m/f) mirrored from the Human warrior rows — character-creation screen preview only |

It is a build artefact and is **gitignored** (`*.MPQ`). It is reproducible byte-for-byte from the
spec plus the stock DBCs, so it does not belong in git; a 49 MB `Spell.dbc` inside a 5 MB archive
even less so.

### 3.3 The module

`mod-dk-lowlevel` under `build/modules/`, with its config at `conf/modules/mod_dk_lowlevel.conf`.
Its whole job at runtime is a `Reconcile()` on `OnPlayerLogin` and `OnPlayerLevelChanged` that walks
a compiled-in progression table and calls `learnSpell` for anything owed and not held, plus one
`OnPlayerCalculateTalentsPoints` override that stops sub-56 DKs standing in Acherus from having
their talents refunded to zero on every login. Idempotent, no DB queries, no allocation. Details in
`DESIGN.md` §5.

The master switch is `DKLowLevel.Enable`, and it ships **0**.

---

## 4. Generating and installing the client patch

### 4.1 Prerequisites (on the machine that builds the patch — the dev box, not the VPS)

| need | check | install |
|---|---|---|
| Python 3 | `python3 -V` | `pacman -S python` |
| StormLib | `ls /usr/lib/libstorm.so.9` | `pacman -S stormlib` |
| Stock server DBCs | `ls /srv/wow/data/dbc/Spell.dbc` | extracted during bring-up, see [bring-up.md](bring-up.md) |
| The working client | `ls /home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Wow.exe` | [client.md](client.md) §1 |
| **A reachable world DB** | `docker compose -f deploy/docker-compose.yml ps mysql` | the stack must be up — see below |

The generator talks to StormLib through `ctypes`; there is no build step and no Wine involved.

**The database prerequisite is not optional and is easy to trip over.** The generator refuses to
retype values from memory: the 54 `player_class_stats` rows are read out of the live warrior rows,
and the spawn coordinates are read out of the live race-1/class-1 `playercreateinfo` row. It shells
out to

```
docker compose -f <repo>/deploy/docker-compose.yml exec -T mysql \
    mysql --defaults-extra-file=/etc/mysql/backup.cnf
```

(override with `--mysql-cmd`, where `{repo}` expands to the repo root; the queries are read-only).

Consequence: **you cannot regenerate the patch on a box without the server stack running** — not on
the VPS, not on a friend's machine. If you have to cut a client pack somewhere the generator cannot
run, use `scripts/package-client.sh --dk-patch skip`; the archive already sitting in the client is
still packaged and still listed in the manifest, it is just neither rebuilt nor verified.

### 4.2 Generate

```bash
cd /home/ali/labs/src/bunniesinc/wowserver

python3 build/modules/mod-dk-lowlevel/tools/dkspells.py \
    --mpq /home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data/patch-Z.MPQ
```

`--mpq` is the only flag you normally need: it is the "also install the finished archive here" path.
The defaults cover the rest — `--dbc-in /srv/wow/data/dbc`, `--out <repo>/.work/out`, `--slot Z`.

What that produces:

| output | path | goes where |
|---|---|---|
| SQL, 3 files | `build/modules/mod-dk-lowlevel/data/sql/db-world/base/2026_08_08_0{0,1,2}_dk_lowlevel_{class_stats,spells,createinfo}.sql` | applied by the worldserver's own updater at boot; **committed** |
| progression header | `build/modules/mod-dk-lowlevel/src/dk_progression.h` | compiled into the module — **never hand-edit**; committed |
| patched DBCs | `.work/out/dbc/{Spell,SkillLineAbility,CharStartOutfit}.dbc` | intermediate; useful for diffing |
| the archive | `.work/out/patch-Z.MPQ` | copied to `<client>/Data/patch-Z.MPQ` because `--mpq` was given |
| build manifest | `.work/out/MANIFEST.json` | what was emitted, from what |

The generator asserts before it writes anything: 234/14/77 columns emitted, every new ID `> 0` and
`> 80864` and `< 100000` and not already present, `Spell.dbc` still strictly ascending, `spell_ranks`
dense 1..N, exactly one row in each supersede chain carrying `AcquireMethod = 2`, and — the one that
matters most — the SQL row and the DBC row for the same ID identical in every parsed column. Any
failure is a non-zero exit and nothing is installed.

`--check` re-runs every one of those checks against the already-generated outputs and writes
nothing. Use it in CI, or when you want to know whether the committed SQL still matches the
committed header and the DBCs in `.work/out`.

Because SQL and DBC come out of the same run, **regenerating means both halves move together**. If
you change the spec, you must reapply the SQL *and* redistribute the MPQ. Doing one without the
other is precisely the drift this architecture exists to prevent.

### 4.3 Where it lands, and why `patch-Z.MPQ`

The 3.3.5a client builds its archive list from four patterns
(`Data\patch-?.MPQ`, `Data\%s\patch-%s-?.MPQ`, `Data\patch.MPQ`, `Data\%s\patch-%s.MPQ`), sorts the
wildcard matches **descending, case-insensitively**, then opens them from the end of that array
forward, handing out priorities starting at `0x40` and incrementing. Higher priority wins. The net
effect is that a single-character suffix late in the alphabet beats everything else.

Measured on this install (the model was reproduced from `Wow.exe` and then checked against a
symlink farm containing the real archive set plus a `patch-Z.MPQ` and a `patch-4.MPQ`):

```
0x47  patch-Z.MPQ            <- ours
0x46  patch-4.MPQ
0x45  patch-3.MPQ            <- base tier outranks locale tier
0x44  patch-2.MPQ
0x43  enUS/patch-enUS-3.MPQ  <- where the stock Spell.dbc actually lives
0x42  enUS/patch-enUS-2.MPQ
0x41  patch.MPQ
0x40  enUS/patch-enUS.MPQ
0x0a..0x01  expansion, lichking, common, common-2, locale-enUS, speech-enUS, …
```

Three practical consequences:

* `Z` is the top of the alphabet, so the ChromieCraft HD packs (`Patch-H`, `Patch-F`, `Patch-G`,
  `Patch-T`, `Patch-S`, `Patch-X` — see [client.md](client.md) §4) can never shadow it. They also
  contain no DBCs, so there is no conflict to begin with. Friends can install them freely.
* The wildcard is a literal single character. **`patch-10.MPQ` would never be loaded at all.**
* `Data/` (not `Data/enUS/`) is correct even though the stock `Spell.dbc` only ever lived in the
  locale chain. MPQ resolution is per-path across all open archives by priority; it is not
  tier-scoped. `patch-3.MPQ` beating `patch-enUS-3.MPQ` above is the same fact from the other side.

**Fallback slot, if `patch-Z.MPQ` somehow does not take:** `Data/enUS/patch-enUS-4.MPQ`, which beats
`patch-enUS-3.MPQ` under either reading of the priority model. Both the generator and
`package-client.sh` take the same slot keys — **`Z`** and **`enUS-4`** — so you never hand-move the
file:

```bash
CLIENT=/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a
rm -f "$CLIENT/Data/patch-Z.MPQ"

python3 build/modules/mod-dk-lowlevel/tools/dkspells.py \
    --slot enUS-4 --mpq "$CLIENT/Data/enUS/patch-enUS-4.MPQ"

scripts/package-client.sh --realmlist <host> --dk-slot enUS-4
```

If you switch slots, **delete the file from the old slot.** Two copies of the patch is not an error,
but "which spell data is this client actually reading" stops being answerable, and
`package-client.sh` will warn about it.

### 4.4 Verify it loaded

Do this **before** creating any character. It is the single check that settles whether the client
half works at all, and it takes ten seconds.

Launch the client, log in with any existing character, and run either of:

```
/dump GetSpellInfo(90000)
/run print(GetSpellInfo(90000))
```

| result | meaning |
|---|---|
| first return value is the string **`Icy Touch`**, second is **`Rank 1`** | the MPQ is loading, the client accepted a `Spell.dbc` with an extra record and an ID above 80864, and the priority model is right. Continue. |
| `nil` | the client is not reading your archive. Ladder below. |

(`/dump` comes from `Blizzard_DebugTools`, which loads on demand the first time you use it. If it
says "unknown command", use the `/run print(...)` form.)

**If it returns nil**, in order:

1. Ask the tool which archive the client will actually read. This reproduces the priority model
   above against a real `Data/` directory and takes a fifth of a second:

   ```bash
   python3 build/modules/mod-dk-lowlevel/tools/dkspells.py --verify --slot Z \
       --client-data /home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data
   ```

   It prints the full search order and then, per patched DBC, either `patch-Z.MPQ` (pass) or the
   archive that beat it. `no archive provides it` means the file is not in `Data/` at all.
   `package-client.sh` runs this automatically on every pack.
2. Is the file actually there, in `Data/` and not `Data/Data/`, spelled `patch-Z.MPQ`?
   Single character after the dash. Case does not matter; the sort is case-insensitive.
3. Rebuild into the fallback slot (§4.3) and retry. If the fallback works, the slot was the problem
   and you are done — record which slot you are on.
4. If both slots fail, the problem is the archive, not the slot. Two known ways to build an archive
   this client ignores:
   * **Format version.** It must be `MPQ_CREATE_ARCHIVE_V2` (`0x01000000`) →
     `formatVersion = 1, headerSize = 44`. StormLib's "V1" writes `formatVersion 0, headerSize 32`,
     which every stock archive in this install disagrees with.
   * **Slash direction.** Files must be stored as `DBFilesClient\Spell.dbc` with a **backslash**.
     `SFileHasFile` on the forward-slash form returns false; the client behaves the same way.

   Both are asserted by the generator (`--check` re-asserts them), so this only bites an archive
   built by hand.
5. Do **not** go looking for a cache to clear. There is no spell WDB cache in 3.3.5a — the 15
   `*.wdb` files the client writes are creature/item/quest/etc. DBC changes take effect on the next
   client launch with no cache wipe. (`package-client.sh` strips `Cache/` from packs anyway.)

An unsigned archive is fine and normal. `SFileVerifyArchive` returns `ERROR_NO_SIGNATURE` on every
Blizzard archive in this install, and the client's only real integrity check is an RSA check over
`Interface\FrameXML\FrameXML.toc` + `Bindings.xml`, which `DBFilesClient\*` never touches.

### 4.5 Getting it to the friends

**Two routes. Prefer the second for updates.**

**Full pack** — `scripts/package-client.sh` hardlink-copies the whole working client into a stage,
so anything sitting in `<client>/Data/` ships automatically. It also now:

* regenerates the patch into the working client before staging (so a pack is never built from a
  stale MPQ);
* runs `dkspells.py --verify` against the client's `Data/` and aborts if something outranks the
  patch;
* **fails the build** if the feature is enabled and the MPQ is missing, rather than quietly shipping
  a client where Death Knights are broken;
* records the file and its sha256 in `PACK-MANIFEST.txt`.

```bash
scripts/package-client.sh --realmlist wow.example.ts.net --tag dk
```

Manifest excerpt from the resulting zip:

```
client patch (custom spell DBC):
  Data/patch-Z.MPQ                               4608491 bytes
  sha256                                         3f1c…  (64 hex chars)
```

That line is the answer to "which spell data is your client on". Ask for it before debugging
anything else.

Flags: `--dk-patch auto|require|skip` and `--dk-slot Z|enUS-4`.

| `--dk-patch` | rebuild | verify | fail if missing |
|---|---|---|---|
| `auto` (default) | iff `DKLowLevel.Enable = 1` | same | same |
| `require` | always | always | always |
| `skip` | no | no | no |

An archive that is present is **always** recorded in the manifest, in every mode — nothing ships
unlisted. `skip` is the escape hatch for packaging where the generator cannot run (§4.1), not a way
to leave the patch out.

**Incremental** — the patch is ~5 MB and the client zip is ~17 GB. When only the spell data changes,
**do not re-cut the pack.** Send the file:

```bash
CLIENT=/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a
scp "$CLIENT/Data/patch-Z.MPQ" friend:          # or any file transfer at all
sha256sum "$CLIENT/Data/patch-Z.MPQ"
```

(`--mpq` installs a copy straight into the working client; the build's own copy stays in
`.work/out/` alongside the loose patched `.dbc` files and `MANIFEST.json`.)

The friend drops it in `<WoW>/Data/`, overwriting, restarts the client, and runs the §4.4 check.
Compare sha256 with the one from the manifest to confirm they have the same build. Everyone must be
on the same one — a friend running last week's patch sees last week's tooltips and takes this
week's damage.

### 4.6 What a friend without the patch sees

Not "a slightly wrong tooltip". Spell 90000 does not exist in their client at all, so it has no
name, no icon and no spellbook entry — the server sends it in the initial spell list and the client
has nothing to render. A level-1 Death Knight on an unpatched client has an empty action bar and no
way to cast their only ability.

This is why `package-client.sh` treats a missing MPQ as a hard error.

---

## 5. Deploy order

Ten steps. Three of them end at a known-good restart, so if the server fails to come up you know
exactly one step is in scope. **Steps 2 and 8 are order-critical** — see §6.

| # | do | then |
|---|---|---|
| 1 | write/regenerate the spec and generator | — |
| 2 | apply the 54 `player_class_stats` rows (Class 6, levels 1–54) | **restart, confirm boot** ⚠ |
| 3 | module skeleton with `Enable = 0`, image rebuild | restart, confirm boot |
| 4 | run the generator; commit SQL + DBC outputs **together** | — |
| 5 | createinfo SQL (`playercreateinfo`, `charstartoutfit_dbc`, `playercreateinfo_action`, drop the Blood Presence cast row) | — |
| 6 | apply 4 + 5 | restart; `.lookup spell Icy Touch` must list **90000** |
| 7 | build `patch-Z.MPQ` into the working client (§4.2) | §4.4 check must pass |
| 8 | `StartHeroicPlayerLevel = 1`, `CharacterCreating.MinLevelForHeroicCharacter = 0`, `HeroicCharactersPerRealm = 10` | `.reload config` — all three are `Reloadable::Yes` ⚠ |
| 9 | `DKLowLevel.Enable = 1` | `.reload config` |
| 10 | create a Human DK and run §7 | — |

---

## 6. The boot gate

**Read this before editing `conf/worldserver.conf`.**

`player_class_stats` on this realm currently holds **26 rows for class 6, levels 55–80** (verified
live). Nothing below 55 exists, because nothing below 55 was ever reachable.

`ObjectMgr.cpp:4878` runs over every race/class pair at startup:

```cpp
// fatal error if no initial stats data
if (!info->levelInfo
    || (info->levelInfo[getIntConfig(CONFIG_START_PLAYER_LEVEL) - 1].stats[0] == 0 && class_ != CLASS_DEATH_KNIGHT)
    || (info->levelInfo[getIntConfig(CONFIG_START_HEROIC_PLAYER_LEVEL) - 1].stats[0] == 0 && class_ == CLASS_DEATH_KNIGHT))
{
    LOG_ERROR("sql.sql", "Race {} class {} initial level does not have stats data!", race, class_);
    exit(1);
}
```

and again five lines later on `basehealth`.

Set `StartHeroicPlayerLevel = 1` while class 6 has no level-1 row and that indexes `levelInfo[0]`,
which is zero-filled. **Worldserver calls `exit(1)` and does not start.** The container restarts,
fails again, and loops.

The trap is the error message. It says:

```
Race 1 class 6 initial level does not have stats data!
```

You will read that as a race problem, or a `playercreateinfo` problem, and go looking in entirely
the wrong table. It is neither. It is `player_class_stats` missing 54 rows, reported per race
because the loop is per race.

**Therefore, and without exception: the 54 rows go in and the server comes up cleanly *before*
`StartHeroicPlayerLevel` moves off 55.** In that order there is no window in which the server cannot
boot, and because the key is `Reloadable::Yes` the flip itself needs only `.reload config`.

Preflight assertion worth having in `scripts/preflight.sh`: if `conf/worldserver.conf` says
`StartHeroicPlayerLevel = 1`, then

```sql
SELECT COUNT(*) FROM player_class_stats WHERE Class = 6 AND Level = 1;   -- must be 1
```

The 54 rows are not invented numbers. Class 1 and class 6 are byte-identical from level 56 upward
and differ by one point of Str/Sta at 55 — copying warrior 1–54 is what Blizzard's own data does
above the DK start level. 54 rows, not 540: `player_class_stats` is class × level, and
`player_race_stats` is flat per race (10 rows, no level column) and is added on top.

---

## 7. Verification checklist

Run top to bottom the first time. Each line has one unambiguous pass condition. Skip to the bold
lines on later runs.

**Client (before any DK exists)**

1. **`/dump GetSpellInfo(90000)` returns `Icy Touch`, `Rank 1`** — §4.4. If this fails, stop; nothing
   below is worth testing.

**Server (before creating anything)**

2. `.lookup spell Icy Touch` in a GM session lists **90000** alongside 45477/49896/49903/49904/49909.
3. The worldserver log from the boot that applied the SQL contains **no** lines matching
   `does not have proper rank value`, `entry is not needed`, or
   `initial level does not have stats data`.

**Creation**

4. Create screen: Death Knight is clickable with no level-55 character on the account. (It always
   was — the 55 rule is purely server-side on this binary. If it is greyed out, that account's
   `expansion` is < 2, which is an account problem, not a patch problem.)
5. **Create a Human Death Knight — it succeeds.** *"You must have a level 55 character"* means
   `CharacterCreating.MinLevelForHeroicCharacter` did not reload. *"unique class limit"* means
   `HeroicCharactersPerRealm`.

**In world**

6. You are in **Northshire Abbey at level 1**. Not Acherus.
7. Character sheet Strength matches a level-1 Human warrior (23).
8. Rune bar visible, **6 runes**, runic power 0/100.
9. Recruit's Shirt / Pants / Boots and Worn Greatsword are **equipped**, not sitting in bags.
   Hearthstone in bags.
10. **Action bar slot 1 is Icy Touch, and its tooltip reads
    `Chills the target for 10 to 12 Frost damage…`, cost `1 Frost Rune`, 20 yd, instant.**
    This is the acceptance criterion for the entire feature.
11. **Hit a critter. Combat log shows 10–12** (crit 20–24). If the tooltip says 10–12 and the log
    says 127–137 the two halves have drifted — see §8.
12. Target gains **Frost Fever**, 15 s, ticking every 3 s.
13. Spellbook contains **exactly one** Icy Touch, plus the Frost Fever and Runic Focus passives.
    **Not** present: Death Grip, Plague Strike, Blood Strike, Death Coil, Blood Presence, or any
    127–137 Icy Touch.
14. `/dump IsSpellKnown(53428)` and `IsSpellKnown(50977)` → `true`. Cast Death Gate; you land at
    Acherus-over-EPL, which is on map 0.

**Robustness — this is where the design holds or does not**

15. `.character level <name> 9`, then `10`. At 10 the talent panel opens with **1 point**.
16. **Log out at Acherus at level 30, log back in. Talents intact.** Check
    `/dump GetUnspentTalentPoints()` before and after. Without the module's
    `OnPlayerCalculateTalentsPoints` hook this is a guaranteed silent full wipe, no gold refunded,
    every login.
17. **Offline GM level change:** log the DK out, run `.character level <name> 20` from the console
    (this writes raw SQL with no script hook at all), log back in. Everything owed by level 20 must
    be present — this is what `Reconcile()` on login exists for.
18. Restart worldserver, log in. Nothing regressed, no duplicate spellbook entries.
19. **An existing level-60 DK logs in.** Stock Icy Touch, stock damage, no extra button.
20. **`scripts/package-client.sh --realmlist <host> --tag dk`, unzip elsewhere, repeat step 1.**
    Confirms the MPQ actually ships.

---

## 8. When the tooltip is wrong

| symptom | cause | fix |
|---|---|---|
| Icy Touch missing from spellbook; blank action button | client has no `patch-Z.MPQ`, or it is in the wrong slot | §4.4 |
| `GetSpellInfo(90000)` → nil | same | §4.4 ladder |
| Tooltip **10–12**, combat log **127–137** | the client DBC has the override and the server row does not: the SQL was not applied, or the worldserver was not restarted after it was (DBC tables load once, `World.cpp:384`) | check `SELECT ID, BaseLevel, SpellLevel, EffectDieSides_1, EffectBasePoints_1 FROM spell_dbc WHERE ID=90000`, then restart |
| Tooltip **127–137**, combat log **10–12** | the MPQ is stale, or was built from a spec that did not carry the override | regenerate (§4.2), redistribute, compare sha256 with the manifest |
| Two Icy Touch entries in the spellbook, no supersession | `spell_ranks` is not a dense 1..N sequence, so `SpellMgr` dropped the whole chain with only a log line | grep the log for `does not have proper rank value` / `entry is not needed`; the chain must be `90000`=1, `45477`=2, `49896`=3, `49903`=4, `49904`=5, `49909`=6 with `first_spell_id = 90000` throughout |
| A brand-new level-1 DK already has a 127–137 Icy Touch | `SkillLineAbility` row **16231** still has `AcquireMethod = 2`, so the level-55 rank is granted the moment the DK acquires skill 771 — i.e. at creation. This silently defeats the entire feature. | the override row flipping 16231 to `AcquireMethod = 0` must be in `skilllineability_dbc`; restart |
| Two friends see different numbers | different MPQ builds | compare sha256 against the pack manifest |
| Worldserver exits immediately; log says `Race N class 6 initial level does not have stats data!` | the boot gate | §6 — it is `player_class_stats`, not races |
| Talents wiped after logging out in Acherus | module disabled, or `OnPlayerCalculateTalentsPoints` not firing | check `DKLowLevel.Enable` and `DKLowLevel.FixAcherusTalents`; note that a hook written as `OnCalculateTalentsPoints` instead of `OnPlayerCalculateTalentsPoints` compiles fine and never runs |

---

## 9. Known and accepted anomalies

These are decisions, not bugs to be discovered later. Each was looked at and left alone on purpose.

### 9.1 Death Knights start with every old-continent flight path

`PlayerTaxi.cpp:26-33` grants the full Eastern Kingdoms + Kalimdor flight-node set to any
`CLASS_DEATH_KNIGHT` at initialisation, unconditionally. A level-1 DK therefore has the entire
old-world flight network already discovered while a level-1 warrior has none.

**Accepted.** It reads raw `getClass()`, so no script hook can reach it; fixing it needs a core
patch. It is a convenience anomaly, not a break. If it starts to matter, that is the fix.

### 9.2 Ten characters per realm, ten DKs per account

`HeroicCharactersPerRealm` has a hard validator of `value <= 10` (`WorldConfig.cpp:236`), and
`CharactersPerRealm` is `> 0 && <= 10`. "DK is just another class" therefore caps at 10 DKs per
account — which is also the total character cap, so in practice it is not a limit. Set to its
ceiling of 10 and accept. Unlimited requires a core change.

### 9.3 One button from 1 to 54

Only Icy Touch is implemented so far (§1.2). Until the other ability blocks ship, a levelling DK has
one rune ability and autoattack. Known; not a malfunction.

### 9.4 Playerbots

At `StartHeroicPlayerLevel = 1` the playerbot DK level clamps all become `std::max(x, 1)`, i.e.
no-ops, so DK bots spawn across the whole 1–60 range and will have almost nothing to press below 55
until the full progression ships. `PlayerbotFactory::ClearEverything()` will also reset DK bots to
level 1.

Accepted during the slice — the bot DK population is 13 characters. Before any wider rollout, either
ship the full progression or set `AiPlayerbot.DisableDeathKnightLogin = 1` temporarily.

### 9.5 Things the skipped starter chain used to give, that nobody gets back

| lost | disposition |
|---|---|
| Dominion Over Acherus (+74% speed, map 609 only) | accepted, cosmetic and irrelevant off Acherus |
| Ebon Blade + city reputation from the chain | accepted, earnable normally |
| The Acherus Deathcharger (48778) | deliberately **not** granted — it is a level-55 epic mount |
| Runeforging, Death Gate, riding | **not lost** — the module grants them directly (§1.1) |

The chain is skipped by unreachability, not deletion: the spawn moves to map 0 and every questgiver
in it exists only on map 609, there are no area triggers into 609, and every quest in it is
`MinLevel 55`. Nothing was deleted, so nothing has to be restored to undo it.

The chain quests are deliberately **not** marked rewarded, even though that would have been
convenient. Quest 12801's reward spell 53821 has `SPELL_EFFECT_BIND`, and
`learnQuestRewardedSpells` re-casts reward spells at every login — which would silently rebind the
player's hearthstone to wherever they happened to log in. Hard no.

### 9.6 Existing 55+ Death Knights

The rank chain is renumbered (`first_spell_id` 45477 → 90000) and SLA 16231 is flipped, both of
which existing DKs go through at their next login. This is safe by construction: they are granted
90000, `addSpell` sees the higher active rank, marks 90000 inactive and sends
`SMSG_SUPERCEDED_SPELL`. Stock already does exactly this for Blood Strike at every level-80 DK
login. **Test it on one existing DK before assuming it for all of them** (checklist step 19).

---

## 10. Rollback

Turning this off is not one switch, because it has both a data half and a client half. In
increasing order of thoroughness — most incidents only need the first one or two.

### 10.1 Stop making new low-level DKs (seconds, no restart)

```ini
# conf/worldserver.conf
StartHeroicPlayerLevel                       = 55
CharacterCreating.MinLevelForHeroicCharacter = 55
HeroicCharactersPerRealm                     = 1
```

```
.reload config
```

All three keys are `Reloadable::Yes`. New DKs are created at 55 in Acherus again, immediately.
Existing level-1 DKs are unaffected — they stay level 1 and keep their custom rank.

Going back the *other* way later means re-reading §6 first: the 54 stat rows must still be present.

### 10.2 Stop the module granting anything (seconds, no restart)

```ini
# conf/modules/mod_dk_lowlevel.conf
DKLowLevel.Enable = 0
```

```
.reload config
```

`Reconcile()` returns immediately. Already-granted spells stay granted — this stops future grants,
it does not revoke. Note this also disables the Acherus talent fix, so a sub-56 DK logging out in
Acherus goes back to being wiped.

### 10.3 Remove the custom spell (requires a restart)

Write a down-migration — do **not** delete the generated SQL file and expect that to undo anything.
The updater tracks files by name and SHA1, and module rows are exempt from orphan cleanup, so a
deleted migration leaves its data in the database forever.

```sql
-- restore the stock chain
DELETE FROM spell_ranks WHERE first_spell_id = 90000;
INSERT INTO spell_ranks (first_spell_id, spell_id, `rank`) VALUES
 (45477, 45477, 1), (45477, 49896, 2), (45477, 49903, 3),
 (45477, 49904, 4), (45477, 49909, 5);

-- drop the custom rows; the DBC files underneath are stock, so removing the
-- override rows restores stock behaviour exactly
DELETE FROM spell_dbc             WHERE ID = 90000;
DELETE FROM spell_bonus_data      WHERE entry = 90000;
DELETE FROM skilllineability_dbc  WHERE ID IN (22000, 16231);   -- 16231's override, not the DBC row
DELETE FROM charstartoutfit_dbc   WHERE ID IN (352, 353);
```

Then **restart worldserver** — `LoadDBCStores` runs once, at `World.cpp:384`.

Deleting the `skilllineability_dbc` row for 16231 removes the *override*; the stock record in the
`.dbc` file (with `AcquireMethod = 2`) comes back on its own. That is the whole point of keeping the
server's DBC files untouched.

Characters that already learned 90000 self-heal. At their next login `Player::_addSpell` →
`SpellMgr::CheckSpellValid` finds no `SpellInfo`, calls `DeleteSpellFromAllPlayers(90000)` and logs
`Player::addSpell: Non-existed in SpellStore spell #90000 request.` once. The row is removed from
`character_spell` for everyone. You do not need to clean that table by hand.

Also restore `playercreateinfo` for race 1 / class 6 to the Acherus spawn
(`map 609, zone 4298, 2355.84 -5664.77 426.028, o 3.65997`) and re-add
`playercreateinfo_cast_spell (0, 32, 48266)` if you want stock creation back exactly.

### 10.4 Remove the client patch

```bash
rm /home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data/patch-Z.MPQ
```

That is the entire client-side rollback. Nothing else on the client was modified — no files
replaced, no exe patched, no addon installed. Tell the friends to delete the same file.

Do this **after** 10.3, not before: a client without the patch talking to a server that still grants
90000 is exactly the broken state described in §4.6.

### 10.5 Existing level-1 Death Knights

Rollback does not retro-level them. After 10.1 + 10.3 they are level-1 characters of a class whose
first ability is at 55. Either level them the rest of the way, `.character level <name> 55` them, or
delete them. There is no automatic migration and there should not be one.

---

## 11. Where everything lives

| thing | path |
|---|---|
| Design record (authoritative for *why*) | `.work/notes/DESIGN.md` — **gitignored, dev box only** |
| Recon notes (DBC, hooks, MPQ, quest chain) | `.work/notes/{dbc,hooks,mpq,questskip}.md` — same |
| Spec — the source of truth for ranks | `build/modules/mod-dk-lowlevel/tools/dk_spec.py` |
| Generator | `build/modules/mod-dk-lowlevel/tools/dkspells.py` |
| Generated SQL | `build/modules/mod-dk-lowlevel/data/sql/db-world/base/*.sql` |
| Generated progression header | `build/modules/mod-dk-lowlevel/src/dk_progression.h` |
| Module source | `build/modules/mod-dk-lowlevel/src/*.cpp` |
| Module config (live, bind-mounted) | `conf/modules/mod_dk_lowlevel.conf` |
| Config keys for the class itself | `conf/worldserver.conf` (`StartHeroicPlayerLevel` &c.) |
| Build artefacts (patched DBCs, archive, MANIFEST.json) | `.work/out/` (gitignored) |
| The archive | `<client>/Data/patch-Z.MPQ` (gitignored, `*.MPQ`) |
| Packaging | `scripts/package-client.sh` |
| Server DBCs — **never modified** | `/srv/wow/data/dbc/` |

Numbers worth having memorised: spell **90000** (Icy Touch rank 1), SkillLineAbility **22000** (its
row) and **16231** (the stock row that must be flipped to `AcquireMethod = 0`), rune cost row
**241** (1 Frost, 100 runic power), Frost Fever **55095**, skill line **771**, map **609** (Acherus,
the talent trap).
