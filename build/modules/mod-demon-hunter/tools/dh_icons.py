#!/usr/bin/env python3
"""Paint the Demon Hunter class icon into the client's two class-icon atlases.

    ./make_class_icons.py           extract from the client, paint, verify, write both atlases
    ./make_class_icons.py --check   rebuild in memory and diff against the files already here

Produces, in this directory:

    UI-CharacterCreate-Classes.blp   ships as Interface\\Glues\\CharacterCreate\\...
    UI-Classes-Circles.blp           ships as Interface\\TargetingFrame\\...

Both belong in `patch-Z.MPQ`. Neither is inside the signed FrameXML/GlueXML trees, so neither
depends on the Wow.exe patch -- the *tcoord table* that points at the new cell does, and that is
`Interface\\FrameXML\\Constants.lua`, which somebody else is writing.

Nothing under the client install or /srv is opened for writing. The stock atlases and the source
icon are READ out of the client's own archives with `acdbc.mpqlib`, which is also what decides
which archive wins each path.

WHERE THE ICON GOES, AND WHY EXACTLY THERE
------------------------------------------
The cell is (row 2, column 2) 0-indexed -- the first free one after PALADIN (2,0) and
DEATHKNIGHT (2,1) -- addressed by `{0.49609375, 0.7421875, 0.5, 0.75}`. Times 256 that is
u [127, 190) and v [128, 192): sixty-three texels wide, sixty-four tall.

Sixty-three, not sixty-four, because Blizzard's own table drifts. Read out of
`Interface\\FrameXML\\Constants.lua` (enUS/patch-enUS-3.MPQ, the archive that wins it), the four
columns start at u = 0, 64, 127, 190 -- a 63-texel pitch for the last three -- while every row
starts on an exact 64 boundary. DEATHKNIGHT is the one entry with round numbers, `{0.25, .5}`,
because it was added in Wrath after the drift was baked in.

That single texel of drift is the whole reason the paste offset below is 127 and not 128:

  * The art in the file follows the tcoords. Measured on the stock create atlas, row 2, at
    y = 145/160/175: alpha runs ...255 at x=126, 124 at x=127, 0 at x=128. So the DEATHKNIGHT
    cell really does own x=127, and its rect `{0.25,.5}` -> [64, 128) really does sample it.
  * So the Demon Hunter's rect [127, 190) borrows one texel from the DEATHKNIGHT cell whatever
    we do. Writing x=127 ourselves would change how DEATHKNIGHT looks -- and would drag its DXT
    block (block column 31 covers x 124..127) into a re-encode.
  * Therefore: paste the 64x64 icon as if its column 0 were at x=127, but only write columns
    1..63, into x 128..190. The rect then shows the DEATHKNIGHT cell's own dark rounded border
    column followed by the icon's columns 1..62. Both of the icon's bevel edges survive.

The alternative -- pasting flush at x=128 -- was rendered and compared: the rect then ends at
the icon's column 61 and the icon loses its right-hand bevel entirely, which is visible at the
40-px size the create screen draws these at (`CharacterCreateClassButtonTemplate`'s pushed
texture is 38x38). Column alignment with the source's own DXT blocks would have been a nice
property; a visibly cropped frame is not worth it.

Vertically there is no drift: rows are exactly 64 apart, so the icon's 64 rows land on
y 128..191 unshifted.

HOW THE FILE IS EDITED: BLOCKS, NOT IMAGES
------------------------------------------
Decoding a whole 256x256 DXT5 level and re-encoding it would put every one of the ten stock
class icons through a second generation of lossy compression. `blp.py --selftest` measures what
that costs on these exact files (max 4 per RGB channel where alpha > 0), so it is small -- but
it is also completely avoidable, because the cell is 64x64 at a multiple of 64 and DXT blocks
are 4x4. Only the blocks inside the cell are decoded, repainted and re-encoded; every other byte
of Blizzard's art is copied through untouched. C5 below asserts that, per mip level.

MIPMAPS
-------
The stock atlases carry nine levels (256 down to 1) and the client picks among them by screen
derivative -- the create screen draws 63 texels into ~40 px, which lands on level 0/1, and a
raid frame at 16 px lands near level 2. Dropping the chain to a single level would make those
draws sample level 0 with no filtering; keeping a *stale* chain would show the old (empty) cell
at those sizes. So the chain is kept and the cell's texels are regenerated at every level where
the cell covers whole texels, by box-filtering the painted level-0 pixels directly (alpha
weighted -- see Rgba.halve in blp.py for why straight RGB averaging haloes a masked edge).

That is levels 0..6 (at level 6 the whole 64x64 cell is exactly one texel of the 4x4 image).
Levels 7 and 8 are 2x2 and 1x1, where the cell is a quarter and a sixteenth of a single texel
that also averages four other classes' art; they are left exactly as Blizzard wrote them. To be
sampled at all, the atlas would have to be drawn at two pixels.
"""

import argparse
import hashlib
import os
import sys

# This file lives at build/modules/mod-demon-hunter/tools/, so build/tools is four levels up.
# blp.py moved into acdbc when this script was installed: a BLP2 codec is no more Demon
# Hunter-specific than the WDBC reader next to it, and the class-icon atlases are not the last
# texture this realm will want to edit.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))

from acdbc import blp, mpqlib                                 # noqa: E402

DEFAULT_CLIENT_DATA = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"
# Default OUTPUT is the build artefact directory, not this directory. The two atlases are
# derived from Blizzard's own art plus one of Blizzard's own icons, so they are build output in
# exactly the sense the patched DBCs are -- reproducible from the client, and not committed.
# Flat: the file's basename is unique across both atlases, and the ARCHIVE path it belongs at
# is already carried in ATLASES below, which is what dhspells.py reads when it builds the MPQ.
# Keeping the two facts in one table beats mirroring an Interface\ tree on disk.
OUT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".work", "out", "icons"))

ATLAS = 256          # both atlases are 256x256
CELL = 64            # 256 / 4 -- the real cell size, confirmed against the stock art below

# The art. Interface\Icons\Spell_Shadow_Metamorphosis.blp: SpellIcon.dbc row 90, a horned
# demonic face with burning eyes on near-black. Chosen over the other candidates in the client
# (Achievement_Boss_Illidan, INV_Weapon_Glave_01, Spell_Shadow_DemonForm, Spell_Shadow_FelArmour,
# Ability_Warlock_ChaosBolt, Ability_Warrior_Bladestorm) because it is the art of the class's own
# signature ability and because it still reads as a face at the 16-18 px the party/raid frames
# draw the circle version at, where a thin glaive or a pale portrait collapses into a smudge.
# See NOTES.md for the full comparison. It is 64x64, so it lands in the 64x64 cell with no
# resampling at all.
ICON_PATH = "Interface\\Icons\\Spell_Shadow_Metamorphosis.blp"

ATLASES = (
    ("UI-CharacterCreate-Classes.blp",
     "Interface\\Glues\\CharacterCreate\\UI-CharacterCreate-Classes.blp", False),
    ("UI-Classes-Circles.blp",
     "Interface\\TargetingFrame\\UI-Classes-Circles.blp", True),
)

# Interface\FrameXML\Constants.lua, verbatim (enUS/patch-enUS-3.MPQ, priority 0x43).
STOCK_TCOORDS = {
    "WARRIOR": (0, 0.25, 0, 0.25),
    "MAGE": (0.25, 0.49609375, 0, 0.25),
    "ROGUE": (0.49609375, 0.7421875, 0, 0.25),
    "DRUID": (0.7421875, 0.98828125, 0, 0.25),
    "HUNTER": (0, 0.25, 0.25, 0.5),
    "SHAMAN": (0.25, 0.49609375, 0.25, 0.5),
    "PRIEST": (0.49609375, 0.7421875, 0.25, 0.5),
    "WARLOCK": (0.7421875, 0.98828125, 0.25, 0.5),
    "PALADIN": (0, 0.25, 0.5, 0.75),
    "DEATHKNIGHT": (0.25, .5, 0.5, .75),
}
CELL_OF = {"WARRIOR": (0, 0), "MAGE": (0, 1), "ROGUE": (0, 2), "DRUID": (0, 3),
           "HUNTER": (1, 0), "SHAMAN": (1, 1), "PRIEST": (1, 2), "WARLOCK": (1, 3),
           "PALADIN": (2, 0), "DEATHKNIGHT": (2, 1)}

DH_CLASS = "DEMONHUNTER"            # the ChrClasses.dbc Filename token, per dh_spec.py
DH_CELL = (2, 2)                    # (row, column), 0-indexed
DH_TCOORDS = (0.49609375, 0.7421875, 0.5, 0.75)

# The round mask is lifted from a stock cell rather than drawn, so the new circle has exactly
# the radius, centre and antialiased edge of the other ten. It must come from column 2: measured
# on the stock circles atlas, the opaque runs per column are [3,60] [66,124] [129,186] [192,250],
# i.e. the circle is offset per column exactly as the tcoords are. ROGUE (0,2) and PRIEST (1,2)
# have bit-identical alpha (max |dA| = 0 over all 4096 texels), and so do PALADIN (2,0) and
# DEATHKNIGHT (2,1) -- one shared mask, placed per column. PRIEST is the one used here.
MASK_CELL = "PRIEST"


# ==========================================================================================
# check plumbing (same shape as build/modules/mod-dk-lowlevel/tools/dkspells.py)
# ==========================================================================================

class Checks:
    def __init__(self):
        self.rows = []

    def _add(self, status, tag, msg):
        self.rows.append((status, tag, msg))
        print(f"  [{status:4}] {tag:3} {msg}")

    def ok(self, tag, msg):
        self._add("PASS", tag, msg)

    def fail(self, tag, msg):
        self._add("FAIL", tag, msg)

    def expect(self, cond, tag, msg, detail=""):
        (self.ok if cond else self.fail)(tag, msg + (f"  -- {detail}" if detail and not cond
                                                     else ""))
        return bool(cond)

    @property
    def failed(self):
        return [r for r in self.rows if r[0] == "FAIL"]

    def summary(self):
        n = len(self.rows)
        print(f"\n{len(self.failed)} failed, {n - len(self.failed)} passed, {n} total")
        return 1 if self.failed else 0


# ==========================================================================================
# geometry
# ==========================================================================================

def rect_of(tc):
    """CLASS_ICON_TCOORDS entry -> (x0, y0, x1, y1) in texels, half-open."""
    vals = [t * ATLAS for t in tc]
    for v in vals:
        assert abs(v - round(v)) < 1e-9, f"tcoord {v / ATLAS} is not texel-aligned on {ATLAS}px"
    return (round(vals[0]), round(vals[2]), round(vals[1]), round(vals[3]))


DH_RECT = rect_of(DH_TCOORDS)                       # (127, 128, 190, 192)
PASTE_X, PASTE_Y = DH_RECT[0], DH_RECT[1]           # where the icon's column 0 *would* land
CELL_X0, CELL_Y0 = DH_CELL[1] * CELL, DH_CELL[0] * CELL     # 128, 128 -- the true 64-grid cell
FIRST_COL = CELL_X0 - PASTE_X                       # 1 -- first icon column we may write


def cell_box(row, col):
    return (col * CELL, row * CELL, col * CELL + CELL, row * CELL + CELL)


def covered_texels(lo, hi, level):
    """The texels of `level` whose full level-0 footprint lies inside [lo, hi)."""
    s = 1 << level
    return (-(-lo // s), hi // s)


def box_average(img, x0, y0, s):
    """Alpha-weighted mean of an s x s box. Matches Rgba.halve's rule, applied in one step so
    that a level-N texel is a filter of the level-0 art rather than of N roundings of it."""
    ar = ag = ab = aa = 0
    rr = rg = rb = 0
    for y in range(y0, y0 + s):
        for x in range(x0, x0 + s):
            r, g, b, a = img.get(x, y)
            ar += r * a
            ag += g * a
            ab += b * a
            aa += a
            rr += r
            rg += g
            rb += b
    n = s * s
    if aa:
        return ((ar + aa // 2) // aa, (ag + aa // 2) // aa, (ab + aa // 2) // aa,
                (aa + n // 2) // n)
    return ((rr + n // 2) // n, (rg + n // 2) // n, (rb + n // 2) // n, 0)


# ==========================================================================================
# extraction
# ==========================================================================================

def read_from_client(data_dir, archived_name):
    prio, rel = mpqlib.resolve(data_dir, archived_name)
    if rel is None:
        raise SystemExit(f"{archived_name}: no archive in {data_dir} provides it")
    with mpqlib.Mpq.open(os.path.join(data_dir, rel)) as m:
        return m.read(archived_name), rel, prio


# ==========================================================================================
# the edit
# ==========================================================================================

def paint_level0(stock_img, icon, mask):
    """Stock level 0 with cell (2,2) cleared and the icon written into it."""
    out = stock_img.copy()
    # Clear the whole true-grid cell first. Blizzard left compression residue in the free cells
    # (C3 reports how much); clearing means the cell's mips are a filter of the icon alone.
    out.fill((0, 0, 0, 0), CELL_X0, CELL_Y0, CELL, CELL)
    for c in range(FIRST_COL, CELL):
        for r in range(CELL):
            px = icon.get(c, r)
            if mask is not None:
                px = (px[0], px[1], px[2], mask.get(c, r)[3])
            out.put(PASTE_X + c, PASTE_Y + r, px)
    return out


def splice(out_blp, painted0):
    """Re-encode only the blocks the cell touches, at every level where it covers whole texels.

    Returns [(level, texel rect, blocks touched)] for the report.
    """
    log = []
    for level in range(len(out_blp.levels)):
        tx0, tx1 = covered_texels(CELL_X0, CELL_X0 + CELL, level)
        ty0, ty1 = covered_texels(CELL_Y0, CELL_Y0 + CELL, level)
        if tx0 >= tx1 or ty0 >= ty1:
            log.append((level, None, 0))
            continue
        s = 1 << level
        touched = 0
        for by in range(ty0 // 4, -(-ty1 // 4)):
            for bx in range(tx0 // 4, -(-tx1 // 4)):
                px = out_blp.block_pixels(level, bx, by)
                changed = False
                for i in range(16):
                    x, y = 4 * bx + (i % 4), 4 * by + (i // 4)
                    if tx0 <= x < tx1 and ty0 <= y < ty1:
                        px[i] = box_average(painted0, x * s, y * s, s)
                        changed = True
                if changed:
                    out_blp.put_block_pixels(level, bx, by, px)
                    touched += 1
        log.append((level, (tx0, ty0, tx1, ty1), touched))
    return log


def build(stock_bytes, icon, mask):
    b = blp.Blp.parse(stock_bytes)
    painted0 = paint_level0(b.decode(0), icon, mask)
    out = blp.Blp.parse(stock_bytes)          # a second, independent parse: `b` stays stock
    log = splice(out, painted0)
    return b, out, painted0, log


# ==========================================================================================
# reporting
# ==========================================================================================

# A cell counts as occupied when a quarter of its texels are solid. Measured on the stock
# create atlas: an occupied cell is 3987-4054 of 4096 texels at alpha >= 128 and an occupied
# circles cell is 2652 (the inscribed circle is 65% of the square), while every free cell in
# both files is exactly 0. Nothing lands anywhere near the threshold, so the map is not a
# judgement call. Max alpha alone would not do: the free cells of the create atlas carry
# Blizzard's leftover compression residue, 55-57 texels of alpha up to 68 (see C3).
OPAQUE = 128
OCCUPIED_FRACTION = 0.25


def occupancy(img):
    """(texels at alpha >= OPAQUE, max alpha) per 64x64 cell -- the evidence behind the map."""
    out = {}
    for row in range(4):
        for col in range(4):
            x0, y0, x1, y1 = cell_box(row, col)
            solid = 0
            m = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    a = img.px[4 * (y * img.w + x) + 3]
                    solid += a >= OPAQUE
                    if a > m:
                        m = a
            out[(row, col)] = (solid, m)
    return out


def _glyph(stat):
    return "#" if stat[0] >= OCCUPIED_FRACTION * CELL * CELL else "."


def print_map(name, before, after):
    names = {v: k for k, v in CELL_OF.items()}
    names[DH_CELL] = DH_CLASS
    print(f"\n== {name}: cell occupancy  ('#' = at least a quarter of the 64x64 cell is solid)")
    print("      before   after")
    for row in range(4):
        b = "".join(_glyph(before[(row, c)]) for c in range(4))
        a = "".join(_glyph(after[(row, c)]) for c in range(4))
        who = " ".join(f"{names.get((row, c), '-'):<11}" for c in range(4))
        print(f"  row {row}  {b}     {a}    {who}")
    print("      solid texels of 4096 per cell, before -> after:")
    for row in range(4):
        cells = "  ".join(f"{before[(row, c)][0]:4d}->{after[(row, c)][0]:<4d}" for c in range(4))
        print(f"  row {row}  {cells}")


# ==========================================================================================
# checks
# ==========================================================================================

def check_codec(checks, tag, stock_bytes):
    """C0 -- the codec is exact on *this* input before it is trusted to edit it."""
    b = blp.Blp.parse(stock_bytes)
    checks.expect(b.to_bytes() == stock_bytes, tag,
                  "C0 codec: stock file re-serialises byte-identically")
    img = b.decode(0)
    raw = blp.Blp.from_rgba(img, compression=blp.COMP_BGRA, alpha_bits=8, mips=False)
    checks.expect(blp.Blp.parse(raw.to_bytes()).decode(0).px == img.px, tag,
                  "C0 codec: decode -> raw BGRA -> decode is exact")
    return b, img


def check_header(checks, tag, stock, out):
    got = (stock.compression, stock.alpha_bits, stock.alpha_encoding, stock.width, stock.height,
           len(stock.levels))
    checks.expect(got == (blp.COMP_DXT, 8, blp.DXT5, ATLAS, ATLAS, 9), tag,
                  f"C1 header: stock is {stock.header_line()}",
                  f"expected DXT5 {ATLAS}x{ATLAS} with 9 levels, got {got}")
    same = all(getattr(stock, f) == getattr(out, f) for f in
               ("version", "compression", "alpha_bits", "alpha_encoding", "has_mips",
                "width", "height"))
    checks.expect(same and [len(x) for x in stock.levels] == [len(x) for x in out.levels], tag,
                  "C1 header: output header and mip geometry are the stock ones")


def check_geometry(checks, tag):
    checks.expect(DH_RECT == (127, 128, 190, 192), tag,
                  f"C2 geometry: {DH_TCOORDS} -> texels x[{DH_RECT[0]},{DH_RECT[2]}) "
                  f"y[{DH_RECT[1]},{DH_RECT[3]})")
    write_x = (CELL_X0, PASTE_X + CELL)          # [128, 191)
    inside = (write_x[0] >= CELL_X0 and write_x[1] <= CELL_X0 + CELL
              and PASTE_Y == CELL_Y0)
    checks.expect(inside, tag,
                  f"C2 geometry: every written texel is inside cell {DH_CELL} "
                  f"(x[{write_x[0]},{write_x[1]}) y[{CELL_Y0},{CELL_Y0 + CELL}))")
    checks.expect(CELL_X0 % 4 == 0 and CELL_Y0 % 4 == 0 and CELL % 4 == 0, tag,
                  f"C2 geometry: the cell is DXT-block aligned "
                  f"(block cols {CELL_X0 // 4}..{(CELL_X0 + CELL) // 4 - 1})")


def check_cell_free(checks, tag, stock_img):
    """C3 -- cell (2,2) holds no class icon today.

    Not "is all zero": the create atlas's four unused cells each carry ~56 texels of faint
    residue (alpha up to 68) along their top edge, which is Blizzard's, not ours. What matters
    is that no part of it is opaque art belonging to something, and it is cleared before the
    icon is written either way.
    """
    x0, y0, x1, y1 = cell_box(*DH_CELL)
    solid = faint = 0
    m = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            a = stock_img.px[4 * (y * stock_img.w + x) + 3]
            solid += a >= OPAQUE
            faint += 0 < a < OPAQUE
            m = max(m, a)
    checks.expect(solid == 0, tag,
                  f"C3 free: stock cell {DH_CELL} holds no icon -- 0 of {CELL * CELL} texels "
                  f"are solid; {faint} carry residue, max alpha {m}")


def check_no_harm(checks, tag, stock, out, stock_bytes):
    """C4/C5/C6 -- nothing outside the new cell moved, in texels or in bytes."""
    bad_levels = []
    for level in range(len(stock.levels)):
        tx0, tx1 = covered_texels(CELL_X0, CELL_X0 + CELL, level)
        ty0, ty1 = covered_texels(CELL_Y0, CELL_Y0 + CELL, level)
        a, b = stock.decode(level), out.decode(level)
        for y in range(a.h):
            for x in range(a.w):
                if tx0 <= x < tx1 and ty0 <= y < ty1:
                    continue
                if a.get(x, y) != b.get(x, y):
                    bad_levels.append((level, x, y, a.get(x, y), b.get(x, y)))
                    break
            if bad_levels and bad_levels[-1][0] == level:
                break
    checks.expect(not bad_levels, tag,
                  "C4 no harm: every texel outside the cell is unchanged, all 9 levels",
                  f"first difference {bad_levels[0] if bad_levels else ''}")

    per_level = []
    ok = True
    for level in range(len(stock.levels)):
        _bw, _bh, bsz = stock.block_grid(level)
        tx0, tx1 = covered_texels(CELL_X0, CELL_X0 + CELL, level)
        ty0, ty1 = covered_texels(CELL_Y0, CELL_Y0 + CELL, level)
        bw = stock.block_grid(level)[0]
        allowed = set()
        if tx0 < tx1 and ty0 < ty1:
            for by in range(ty0 // 4, -(-ty1 // 4)):
                for bx in range(tx0 // 4, -(-tx1 // 4)):
                    allowed.add(by * bw + bx)
        changed = {i for i in range(len(stock.levels[level]) // bsz)
                   if stock.levels[level][i * bsz:(i + 1) * bsz]
                   != out.levels[level][i * bsz:(i + 1) * bsz]}
        per_level.append((level, len(changed), len(allowed)))
        if not changed <= allowed:
            ok = False
    checks.expect(ok, tag,
                  "C5 no harm: only blocks inside the cell were rewritten -- "
                  + " ".join(f"L{lv}:{c}/{a}" for lv, c, a in per_level))

    stock0, out0 = stock.decode(0), out.decode(0)
    bad = []
    for cls, tc in STOCK_TCOORDS.items():
        x0, y0, x1, y1 = rect_of(tc)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if stock0.get(x, y) != out0.get(x, y):
                    bad.append((cls, x, y))
                    break
            if bad and bad[-1][0] == cls:
                break
    checks.expect(not bad, tag,
                  "C6 no harm: all ten stock classes' sampled rects are texel-identical",
                  f"{bad[:3]}")

    checks.expect(len(out.to_bytes()) == len(stock_bytes), tag,
                  f"C8 container: output is the same {len(stock_bytes)} bytes as stock")
    checks.expect(blp.Blp.parse(out.to_bytes()).to_bytes() == out.to_bytes(), tag,
                  "C8 container: output re-parses to itself")


def check_cell_quality(checks, tag, out, painted0):
    """C7 -- what the DXT5 round trip cost the icon we painted.

    This is where the 127-not-128 paste offset is paid for. The source icon is itself DXT
    (DXT3), so its texels already sit on per-block interpolation lines; pasting it one column
    off the destination's 4x4 block grid makes every destination block straddle two source
    blocks, and a block that straddles the fire and the hair can hold eight distinct colours
    where DXT stores four. Checked on the worst such block by brute force: no choice of
    endpoints does better in max error than the one this encoder picks (mine 99, best-SSE
    search 132), so this is the format, not the fit.

    Pasting flush at x=128 instead would be near-lossless (measured: max 2) and would crop the
    icon's right-hand bevel out of the sampled rect, which is visible at the size the create
    screen draws. The bound below is therefore on the *distribution*, which is what a real
    regression (wrong offset, wrong mask, wrong level) would move: a handful of interior texels
    may be badly off, the bulk may not.
    """
    got = out.decode(0)
    x0, y0, x1, y1 = cell_box(*DH_CELL)
    worst_rgb = worst_a = 0
    total = n = big = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            p, q = painted0.get(x, y), got.get(x, y)
            worst_a = max(worst_a, abs(p[3] - q[3]))
            if p[3]:
                d = max(abs(p[k] - q[k]) for k in range(3))
                worst_rgb = max(worst_rgb, d)
                total += d
                big += d > 32
                n += 1
    mean = total / max(n, 1)
    # Bounds with room: the two files measure 6.15 and 7.45 mean, 2.0% and 2.7% over 32. A mean
    # of 12 is still under two 5-bit quantisation steps per texel, and anything that breaks the
    # paste offset, the mask or a mip level moves these by far more than the headroom.
    checks.expect(mean < 12.0 and big < 0.08 * n and worst_a <= 32, tag,
                  f"C7 quality: painted cell after DXT5 -- mean rgb delta {mean:.2f}, "
                  f"{big}/{n} texels over 32 ({100.0 * big / max(n, 1):.1f}%), worst {worst_rgb} "
                  f"rgb / {worst_a} alpha")


# ==========================================================================================
# main
# ==========================================================================================

def run(args, checks):
    data = args.client_data
    if not os.path.isdir(data):
        print(f"no client Data directory at {data}", file=sys.stderr)
        return 2

    icon_bytes, icon_rel, icon_prio = read_from_client(data, ICON_PATH)
    icon_blp = blp.Blp.parse(icon_bytes)
    icon = icon_blp.decode(0)
    print(f"== source art\n  {ICON_PATH}\n  {icon_rel} (priority 0x{icon_prio:02x})  "
          f"{icon_blp.header_line()}")
    checks.expect((icon.w, icon.h) == (CELL, CELL), "art",
                  f"C10 art: source icon is {icon.w}x{icon.h}, the cell is {CELL}x{CELL} -- "
                  "no resampling")

    results = []
    for out_name, archived, circular in ATLASES:
        tag = "cre" if not circular else "cir"
        stock_bytes, rel, prio = read_from_client(data, archived)
        print(f"\n== {archived}\n  {rel} (priority 0x{prio:02x})  {len(stock_bytes)} bytes  "
              f"sha256 {hashlib.sha256(stock_bytes).hexdigest()[:16]}")

        stock, stock_img = check_codec(checks, tag, stock_bytes)
        check_geometry(checks, tag)
        check_cell_free(checks, tag, stock_img)

        mask = None
        if circular:
            mx0, my0, _mx1, _my1 = rect_of(STOCK_TCOORDS[MASK_CELL])
            mask = stock_img.crop(mx0, my0, CELL, CELL)
            lit = [mask.px[4 * i + 3] for i in range(CELL * CELL)]
            checks.expect(sum(1 for a in lit if a == 255) > 2000 and lit[0] == 0, tag,
                          f"C9 mask: round mask lifted from the stock {MASK_CELL} cell "
                          f"({sum(1 for a in lit if a)} of {CELL * CELL} texels inside the "
                          "circle)")

        stock, out, painted0, log = build(stock_bytes, icon, mask)
        check_header(checks, tag, stock, out)
        check_no_harm(checks, tag, stock, out, stock_bytes)
        check_cell_quality(checks, tag, out, painted0)

        print("  mip regeneration:")
        for level, rect, touched in log:
            w, h = out.dims(level)
            if rect is None:
                print(f"    L{level} {w:3d}x{h:<3d} skipped -- the cell covers no whole texel "
                      "at this level; stock bytes kept")
            else:
                print(f"    L{level} {w:3d}x{h:<3d} texels x[{rect[0]},{rect[2]}) "
                      f"y[{rect[1]},{rect[3]}), {touched} blocks re-encoded")

        blob = out.to_bytes()
        results.append((out_name, blob, stock_img, out.decode(0)))

    print()
    for out_name, blob, stock_img, new_img in results:
        path = os.path.join(args.out, out_name)
        if args.check:
            if not os.path.exists(path):
                checks.fail("out", f"{out_name} is not on disk; run without --check")
                continue
            with open(path, "rb") as f:
                on_disk = f.read()
            checks.expect(on_disk == blob, "out",
                          f"C11 determinism: {out_name} on disk matches a fresh build")
        else:
            os.makedirs(args.out, exist_ok=True)
            with open(path, "wb") as f:
                f.write(blob)
            print(f"  wrote {path}  {len(blob)} bytes  "
                  f"sha256 {hashlib.sha256(blob).hexdigest()}")
        print_map(out_name, occupancy(stock_img), occupancy(new_img))
    return checks.summary()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory and compare with the files here; writes nothing")
    ap.add_argument("--client-data", default=DEFAULT_CLIENT_DATA,
                    help=f"client Data directory, read only [{DEFAULT_CLIENT_DATA}]")
    ap.add_argument("--out", default=OUT_DIR, help=f"output directory [{OUT_DIR}]")
    args = ap.parse_args(argv)
    return run(args, Checks())


if __name__ == "__main__":
    sys.exit(main())
