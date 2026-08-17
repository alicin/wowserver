# The Demon Hunter class icon

Two atlases, painted, plus the BLP2 codec that did it. Everything here was read out of this
machine's own client and server files; nothing was downloaded and no art was invented.

```
.work/dh-parts/icon/
  blp.py                          BLP2 reader/writer + DXT1/DXT3/DXT5 codec, with --selftest
  make_class_icons.py             the generator: extract, paint, verify, write. Re-runnable.
  UI-CharacterCreate-Classes.blp  -> Interface\Glues\CharacterCreate\  in patch-Z.MPQ
  UI-Classes-Circles.blp          -> Interface\TargetingFrame\         in patch-Z.MPQ
  NOTES.md                        this file
```

```
88580  a41e79d343628f52fd008b6530e2db39a44ff2924275217e451f5d07ab25c123  UI-CharacterCreate-Classes.blp
88580  b191ad0111777f5cafad2b843ffec7743e74ac6d9f456217d77c5b4389c37593  UI-Classes-Circles.blp
```

Both outputs are exactly the size of the files they replace, because only payload bytes changed:
same header, same nine mip levels, same offsets and sizes.

**The cell is (row 2, column 2), texcoords `{0.49609375, 0.7421875, 0.5, 0.75}`**, as briefed.
Whoever writes `CLASS_ICON_TCOORDS` wants exactly:

```lua
["DEMONHUNTER"] = {0.49609375, 0.7421875, 0.5, 0.75},
```

Nothing was written under `/home/ali/games/...` or `/srv`. Both atlases and the source icon were
read out of the client archives through `acdbc.mpqlib`, which is also what decided which archive
wins each path.

---

## 1. What the two atlases actually are

Read with `blp.py --info`, not assumed:

| | UI-CharacterCreate-Classes.blp | UI-Classes-Circles.blp |
|---|---|---|
| wins from | `enUS/locale-enUS.MPQ` (priority 0x06) | `enUS/patch-enUS.MPQ` (priority 0x40) |
| magic / version | `BLP2` / 1 | `BLP2` / 1 |
| compression | **2 (DXT)** | 2 |
| alphaBits | 8 | 8 |
| alphaEncoding | **7 (DXT5)** | 7 |
| hasMips | 1 | 1 |
| size | 256 x 256 | 256 x 256 |
| mip levels | 9 | 9 |
| mip sizes | 65536 16384 4096 1024 256 64 16 16 16 | same |
| mip offsets | 1172 66708 83092 87188 88212 88468 88532 88548 88564 | same |
| file bytes | 88580 | 88580 |

Nine levels is the full chain, 256 down to 1x1 (the last three are all 16 bytes because a DXT5
block is 4x4 whatever the image is). The header is a fixed 1172 bytes — 20 bytes of fields, two
16-entry offset/size tables, and a 1024-byte palette that is present and all zero even in a DXT
file. Mip data starts immediately after and is contiguous.

The source icon is a different DXT flavour, which is why the codec had to handle more than one:

    Interface\Icons\Spell_Shadow_Metamorphosis.blp   enUS/locale-enUS.MPQ (0x06)
    compression=2  alphaBits=8  alphaEncoding=1 (DXT3)  hasMips=17  64x64  7 levels

`hasMips` is not a bool. The atlases carry 1; all twelve `Interface\Icons\` files opened for §4
carry 17. Both mean "there are mipmaps"; `blp.py` preserves whatever the source had rather than
normalising it.

## 2. Which BLP variants this client actually ships

The brief allowed re-encoding as uncompressed BGRA (compression 3) *if* the client was verified
to accept it. **It was not verified, so it was not used** — the atlases are written back as
DXT5, the format they already were.

The supporting scan, because "not verified" deserves a number: the archives' listfiles name
**14071** distinct `Interface\*.blp` paths. 1500 of them were sampled at random (seed 1234),
resolved through the client's own archive-priority order, and their headers read:

| compression | alphaBits | alphaEncoding | meaning | files |
|---|---|---|---|---|
| 2 | 8 | 7 | DXT5 | 497 |
| 2 | 8 | 1 | DXT3 | 391 |
| 2 | 0 | 0 | DXT1, opaque | 313 |
| 2 | 1 | 0 | DXT1, 1-bit alpha | 260 |
| 2 | 4 | 1 | DXT3, 4-bit alpha declared | 30 |
| 1 | 8 | 8 | palettised, 8-bit alpha | 8 |
| 1 | 1 | 8 | palettised, 1-bit alpha | 1 |
| **3** | | | **raw BGRA** | **0** |

So there is no example in the client to learn from, and no evidence either way about whether
Wow.exe 12340 renders one. `blp.py` implements compression 3 (it is what makes the lossless
round-trip test possible) and its docstring says plainly that the claim is untested.

## 3. blp.py

Decodes compression 1 (palettised, alphaBits 0/1/4/8), 2 (DXT1/DXT3/DXT5) and 3 (raw BGRA);
encodes 2 and 3. Palettised *encoding* is deliberately missing — it needs a colour quantiser,
nothing here needs one, and a bad one silently posterises Blizzard art, so `from_rgba` raises.

Choices worth knowing about:

* **565 expansion is by bit replication** (`r5<<3 | r5>>2`), the S3TC/D3D behaviour. Pillow's
  BLP plugin truncates (`r5<<3`), which is why the cross-check below allows 7.
* **The 3-colour transparent mode is DXT1-only.** DXT3/DXT5 colour blocks are always 4-colour
  regardless of endpoint order, so the decoder is told the kind rather than inferring it.
* **Endpoints come from a range fit** — project the block onto the principal axis of its
  covariance, take the two extreme pixels — followed by one least-squares refit that is kept
  only on a *strict* improvement. The strictness is what makes re-encoding already-DXT data
  idempotent: such a block already lies on its own endpoint line, the range fit reproduces it
  with zero error, and no refit can beat zero.
* **DXT5 alpha tries both modes.** `a0 > a1` gives eight interpolated values, `a0 <= a1` gives
  six plus a free 0 and 255. Counted on the create atlas's 4096 level-0 blocks, Blizzard writes
  2010 flat-255 blocks as `a0=a1=255`, 1477 flat-0 blocks as `a0=0,a1=1`, and almost every
  graded block as eight-value with `a0=255`. Matching that shape moved the worst-case alpha
  error from 18 to 0 and the byte-identical block count from 3.3% to 56%.

### Round-trip results (`./blp.py --selftest`)

| file | T1 container | T2 lossless pixels | T3 same-format re-encode | T4 vs Pillow |
|---|---|---|---|---|
| UI-CharacterCreate-Classes.blp | **exact** | **exact** (65536 texels) | max 4 rgb (alpha>0) / 15 alpha, mean 0.006; blocks 2302 identical + 1691 equivalent + 103 differ | max 7 |
| UI-Classes-Circles.blp | **exact** | **exact** | max 4 rgb / 8 alpha, mean 0.005; 1740 + 2231 + 125 | max 7 |
| Spell_Shadow_Metamorphosis.blp (DXT3) | **exact** | **exact** | max 2 rgb / 0 alpha; 244 + 11 + 1 | max 7 |
| INV_Weapon_Glave_01.blp (DXT1) | **exact** | **exact** | max 34 rgb; 226 + 13 + 17 | max 7 |

(The Pillow column is the max channel delta against `PIL.BlpImagePlugin`, 7 in every case —
exactly the 565-expansion difference described above, and the reason the tolerance is 7.)

* **T1** parses the file and re-serialises it: byte-identical, so header, offset table, size
  table and palette are all round-tripping.
* **T2** is the brief's "decode, re-encode, decode again, assert the pixels match" — done in a
  *lossless* configuration (raw BGRA), because asserting bit equality through a lossy codec
  would either be a lie or a tolerance dressed up as an assertion. It passes exactly.
* **T3** is the same trip through the file's own DXT and is **measured, not asserted**. It is
  reported three ways on purpose: the RGB of a fully transparent texel is whatever fell out of
  the colour fit and nothing samples it, and a block can be spelled two ways and mean the same
  thing (Blizzard's `a0=0,a1=1` empty block vs this codec's `0,0` — 1477 of the create atlas's
  "differing" blocks are exactly that).
* **T4** is an independent decoder, Pillow's `BlpImagePlugin`, agreeing to within the known
  565-expansion difference.

## 4. The art, and why this one

Everything the client has that is plausibly Demon Hunter, found by searching every archive's
listfile. Descriptions are from looking at the decoded art, and the reference counts are from
`SpellIcon.dbc` (the id) joined against `/srv/wow/data/dbc/Spell.dbc` (`SpellIconID`):

| icon | id | spells using it | what it looks like |
|---|---|---|---|
| **Spell_Shadow_Metamorphosis** | **90** | **99** | horned demonic face, violet skin, two burning orange eyes, near-black ground |
| Spell_Shadow_DemonForm | 3314 | 7 | pale violet screaming demon head — this is the Warlock's *Metamorphosis* (47241) |
| Achievement_Boss_Illidan | 3663 | 0 | Illidan's portrait: white hair, green eye-glow, low contrast |
| INV_Weapon_Glave_01 | 2596 | 0 | a warglaive on a blue field; DXT1, no alpha; small in frame |
| Spell_Shadow_FelArmour | 2297 | 6 | fel-green skull over a shield; the green collides with ROGUE |
| Ability_Warlock_ChaosBolt | — | — | green/gold energy burst, reads as a smear when small |
| Ability_Warrior_Bladestorm | 2782 | 5 | whirling blades — reads Warrior, and Warrior is next to it |
| Ability_UpgradeMoonGlaive | — | — | a moon glaive, silver on violet |
| INV_Inscription_TarotChaos | — | — | a tarot card |
| Spell_Shadow_DemonicEmpathy | — | — | violet skull, flat |
| Spell_Shadow_DemonBreath | — | — | **misnamed**: the art is blue underwater bubbles. Unusable. |

Chosen: **`Interface\Icons\Spell_Shadow_Metamorphosis.blp`**.

1. It is the client's own *Metamorphosis* art, and Metamorphosis is this class's signature
   ability — the one `dh_spec.py` builds the Illidan display (21135) and shapeshift form 23
   around. The class icon being the class ability's icon is the kind of coherence Blizzard's own
   ten cells have.
2. It survives being small. The ten stock cells are drawn at ~40 px on the create screen and at
   16–24 px in party/raid/who frames; a dark ground with two saturated orange eyes still reads
   as a horned face at 18 px, where the glaive becomes a blue smudge and the Illidan portrait
   becomes a pale blob.
3. Its colour is not taken. Against the ten neighbours (blue-white, red, green, brown, orange
   bow, red-gold, cyan, violet, gold, blue-grey) a near-black field with orange highlights is
   the one nobody is using.

Costs, stated: icon 90 is shared with **99** other spell records — mostly summons and
engineering trinkets (Greater Shadow Imp, Explosive Sheep, Goblin Land Mine, Target Dummy). The
atlas holds a *copy* of the art, so nothing is taken from those spells; it just is not an
exclusive image. The runner-up on that axis was `Achievement_Boss_Illidan` (0 spells), which
lost on legibility.

## 5. Geometry: the cell is 64x64, but the tcoords only sample 63 of it

`256 / 4 = 64`, and the cell really is 64 x 64 — the source icon is 64 x 64, so it lands with
**no resampling at all**. But the grid the *texcoords* describe is not a clean 64 pitch, and
this is the one thing about the job that needed real measurement.

From `Interface\FrameXML\Constants.lua` (`enUS/patch-enUS-3.MPQ`, priority 0x43), the stock
table's four columns start at u = 0, 64, **127**, **190** — a 63-texel pitch after the first —
while all rows start on exact 64 boundaries. `DEATHKNIGHT` is the single entry with round
numbers (`{0.25, .5}`), because Wrath added it after the drift was already baked in.

The art in the files follows the tcoords, not the clean grid. Measured:

* Create atlas, row 2, at y = 145 / 160 / 175: alpha is 255 at x=126, **124 at x=127**, 0 at
  x=128. So the DEATHKNIGHT cell owns x=127, and its rect `[64,128)` really does sample it.
* Circles atlas, opaque column runs: `[3,60] [66,124] [129,186] [192,250]` — the circles are
  offset per column exactly as the tcoords are. Row runs: `[3,60] [67,124] [131,188]`, i.e. a
  clean 64 pitch vertically.

Hence the paste offset. The icon is placed **as if its column 0 were at x=127**, but only
columns 1..63 are written, into x 128..190:

* The sampled rect `[127,190)` then shows the DEATHKNIGHT cell's own dark border column followed
  by the icon's columns 1..62 — both of the icon's bevel edges survive.
* Nothing outside cell (2,2) is written, so DEATHKNIGHT's rect stays byte-identical (check C6),
  and its DXT blocks (block column 31 covers x 124..127) are never touched.

The alternative, pasting flush at x=128, was built and rendered side by side. Its right-hand
bevel and rounded corner fall outside the sampled rect and the icon looks cut off against ten
neighbours that are not. It would have been *nearly lossless* (see §8); it was still the wrong
call.

### The round mask is Blizzard's own

For `UI-Classes-Circles.blp` the alpha comes from a stock cell rather than a drawn circle. Two
measurements justify it: ROGUE (0,2) and PRIEST (1,2) have **bit-identical** alpha (max |dA| = 0
over all 4096 texels), as do PALADIN (2,0) and DEATHKNIGHT (2,1) — one shared mask — while ROGUE
vs PALADIN differ in 346 texels, because the mask is offset per column. So the mask is lifted
from PRIEST, the column-2 cell, and lands with the same phase.

Result, straight out of the finished file:

```
DEMONHUNTER (2,2)  circle occupies x 129..186   y 131..188
ROGUE       (0,2)                  x 129..186   y   3..60
PRIEST      (1,2)                  x 129..186   y  67..124
DEATHKNIGHT (2,1)                  x  67..124   y 131..188
PALADIN     (2,0)                  x   3..60    y 131..188
```

Exactly its column's horizontal placement and exactly its row's vertical one.

Cross-checked before relying on it: inside the circle, the circles atlas and the create atlas
hold the *same* RGB (2494 of 2512 texels within 8, worst 64 at a DXT block edge), so Blizzard's
circle really is the square icon with a mask over it, which is what this reproduces.

## 6. Mipmaps

Kept, and regenerated where it matters. The stock chain is nine levels and the client picks
among them by screen-space derivative: 63 texels drawn into ~40 px (the create screen —
`CharacterCreateClassButtonTemplate`'s pushed texture is 38x38) lands on level 0/1, and a 16-px
raid frame lands near level 2. A single-level file would make those draws sample level 0
unfiltered; a *stale* chain would show the old empty cell at those sizes.

So the cell's texels are regenerated at every level where the cell covers whole texels, by box
filtering the painted level-0 pixels directly (alpha-weighted, so the masked edge does not grow
a dark halo), one filter step from level 0 rather than N accumulated roundings:

```
L0 256x256  texels x[128,192) y[128,192)   256 blocks re-encoded
L1 128x128         x[ 64, 96) y[ 64, 96)    64
L2  64x64          x[ 32, 48) y[ 32, 48)    16
L3  32x32          x[ 16, 24) y[ 16, 24)     4
L4  16x16          x[  8, 12) y[  8, 12)     1
L5   8x8           x[  4,  6) y[  4,  6)     1
L6   4x4           x[  2,  3) y[  2,  3)     1     (the whole cell is one texel here)
L7   2x2    skipped -- stock bytes kept
L8   1x1    skipped -- stock bytes kept
```

L7 and L8 are left exactly as Blizzard wrote them. At L7 the cell is a quarter of one texel that
also averages three other (empty) cells; at L8 it is a sixteenth of the single texel that
averages the entire atlas including all ten stock icons. To sample either, the client would have
to draw the whole atlas at two pixels. Touching them would rewrite texels that are pure Blizzard
output today, for no visible gain.

## 7. What the generator verifies

`./make_class_icons.py` runs 30 checks (32 with `--check`) and prints a PASS/FAIL line for each.
The load-bearing ones:

| | check |
|---|---|
| C0 | the codec re-serialises *this* stock file byte-identically, and decode → raw BGRA → decode is exact, before it is trusted to edit anything |
| C1 | stock header is DXT5 256x256 with 9 levels, and the output's header and mip geometry are the stock ones |
| C2 | the tcoords are texel-aligned and give x[127,190) y[128,192); every written texel is inside cell (2,2); the cell is DXT-block aligned (block columns 32..47) |
| C3 | cell (2,2) holds no icon in stock — 0 of 4096 texels are solid. (It is not empty: the create atlas's four unused cells each carry ~56 texels of faint residue, alpha up to 68, along the top edge. Blizzard's. It is cleared.) |
| C4 | **every texel outside the cell is unchanged, at all nine levels** |
| C5 | **only blocks inside the cell were rewritten** — L0 256/256, L1 64/64, L2 16/16, L3 4/4, L4..L6 1/1, L7/L8 0/0 |
| C6 | all ten stock classes' sampled rects are texel-identical before and after |
| C7 | the painted cell's DXT5 round-trip distribution (see §8) |
| C8 | the output is the same 88580 bytes as stock and re-parses to itself |
| C9 | the round mask really came from the stock PRIEST cell (2732 of 4096 texels lit) |
| C10 | the source icon is 64x64, so no resampling happens |
| C11 | `--check`: the files on disk are byte-identical to a fresh build (determinism) |

### Before / after

```
UI-CharacterCreate-Classes.blp                UI-Classes-Circles.blp
      before   after                                before   after
row 0  ####     ####    WARRIOR MAGE ROGUE DRUID     ####     ####
row 1  ####     ####    HUNTER SHAMAN PRIEST WARLOCK ####     ####
row 2  ##..     ###.    PALADIN DEATHKNIGHT [DH] -   ##..     ###.
row 3  ....     ....    -       -           -    -   ....     ....

solid texels (alpha >= 128) of 4096 per cell, before -> after:
  create   row 2   3987->3987   3987->3987      0->3965      0->0
  circles  row 2   2652->2652   2652->2652      0->2644      0->0
```

The new cell lands at 3965 solid texels against neighbours at 3987 (it is one column narrower,
by design) and at 2644 against neighbours at 2642–2652 (the inscribed circle). A cell counts as
occupied when a quarter of it is solid; every occupied cell measures 2642–4054 and every free
one measures exactly 0, so the map is not a judgement call.

## 8. The one cost, stated plainly

Pasting one column off the destination's 4x4 block grid means every destination block straddles
two blocks of the (already DXT3-compressed) source icon. Where a block straddles the fire and
the hair it can hold eight distinct colours, and DXT stores four.

Measured over the cell, painted vs. what the finished file decodes to:

| | create | circles |
|---|---|---|
| mean RGB delta (texels with alpha > 0) | 6.15 | 7.45 |
| texels over 32 | 81 / 3986 (2.0%) | 74 / 2732 (2.7%) |
| worst RGB delta | 99 | 99 |
| worst alpha delta | 17 | 7 |

The worst block was checked by hand: it holds 8 unique colours, and a brute-force search over
endpoint pairs drawn from the block's own colours finds nothing better in max error than this
encoder's fit (encoder 99, best-SSE search 132). That is the format, not the fit — no better
encoder recovers it.

The block-aligned alternative (paste at x=128) measures **max 2, mean 0.001** — effectively a
lossless copy of Blizzard's icon — and crops the icon's right bevel and rounded corner out of
the sampled rect. Both were rendered at 40 px, 64 px and 200 px against the DEATHKNIGHT cell.
At display size the interior artefacts are not visible; the cropped frame is. Hence the choice.
If a future reviewer disagrees, the change is one constant: `FIRST_COL`/`PASTE_X` in
`make_class_icons.py`.

Two smaller things a reviewer should know:

* The Demon Hunter's sampled rect borrows its **leftmost texel column from the DEATHKNIGHT
  cell** (x=127, alpha 124, dark). That is not a bug introduced here — Blizzard's own column-2
  and column-3 icons do the same thing, and it is the reason the icon is not written flush.
  DEATHKNIGHT itself is untouched (C6).
* Mip levels 7 and 8 still describe the pre-Demon-Hunter atlas, deliberately (§6).

## 9. Re-running

```bash
cd .work/dh-parts/icon
./make_class_icons.py            # extract, paint, verify, write both .blp files
./make_class_icons.py --check    # rebuild in memory, prove the files on disk match, write nothing
./blp.py --info    <file.blp>    # print a real header
./blp.py --selftest <file.blp>   # T1/T2/T3/T4 on any BLP2
```

`--client-data` overrides the client `Data` directory (default
`/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data`); `--out` overrides where the `.blp` files
land. The run is deterministic: same client, same bytes, which is what C11 asserts.

Both files still need to be added to the patch archive as
`Interface\Glues\CharacterCreate\UI-CharacterCreate-Classes.blp` and
`Interface\TargetingFrame\UI-Classes-Circles.blp` — backslashes, per `mpqlib`'s assertion — and
`patch-Z.MPQ` is built by one generator only (`acdbc/__init__.py` explains why), so the entries
belong in that build, not in a second archive.
