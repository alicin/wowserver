#!/usr/bin/env python3
"""BLP2 codec for 3.3.5a client textures: decode to RGBA8, encode back, splice DXT blocks.

    ./blp.py --info <file.blp> ...       print the real header of each file
    ./blp.py --selftest <file.blp> ...   round-trip every file and report (see SELFTEST below)

WHY THIS EXISTS
---------------
The Demon Hunter class icon has to be painted into two Blizzard atlases
(`Interface\\Glues\\CharacterCreate\\UI-CharacterCreate-Classes.blp` and
`Interface\\TargetingFrame\\UI-Classes-Circles.blp`), which means reading a BLP2, editing 64x64
pixels of it, and writing a BLP2 the 3.3.5a client will still load. Nothing in `build/tools/`
did images; `dbclib` does WDBC and `mpqlib` does archives.

WHAT THE CLIENT ACTUALLY SHIPS -- read, not assumed
---------------------------------------------------
Every number below came out of a file in this install via `mpqlib`, not out of a wiki page:

    Interface\\Glues\\CharacterCreate\\UI-CharacterCreate-Classes.blp  (enUS/locale-enUS.MPQ)
        BLP2 v1  compression=2 alphaBits=8 alphaEncoding=7 hasMips=1  256x256  88580 bytes
        9 mip levels, sizes 65536 16384 4096 1024 256 64 16 16 16, offsets contiguous from 1172
    Interface\\TargetingFrame\\UI-Classes-Circles.blp                  (enUS/patch-enUS.MPQ)
        byte-for-byte the same header and the same mip geometry
    Interface\\Icons\\Spell_Shadow_Metamorphosis.blp                   (enUS/locale-enUS.MPQ)
        compression=2 alphaBits=8 alphaEncoding=1 hasMips=17  64x64  -- DXT3, not DXT5
    Interface\\Icons\\INV_Weapon_Glave_01.blp                          (enUS/locale-enUS.MPQ)
        compression=2 alphaBits=0 alphaEncoding=0 hasMips=17  64x64  -- DXT1, no alpha

So three of the DXT variants turn up in four files picked for one small job, which is why the
decoder implements all three rather than the one the atlases happen to use. `hasMips` is a
*count-ish* byte, not a bool: the atlases carry 1 and the icons carry 17, and both are read by
the client as "there are mipmaps". This codec preserves whatever the source file had.

WHAT IS IMPLEMENTED
-------------------
    decode  compression 1 (palettised, alphaBits 0/1/4/8), 2 (DXT1/DXT3/DXT5), 3 (raw BGRA)
    encode  compression 2 (DXT1/DXT3/DXT5) and 3 (raw BGRA)

Palettised *encoding* is deliberately absent: it needs a colour quantiser, nothing in this repo
needs one, and a bad one would silently posterise Blizzard art. `Blp.from_rgba` raises rather
than guessing.

COMPRESSION 3 (raw BGRA) IS NOT VERIFIED AGAINST THE CLIENT
-----------------------------------------------------------
It is implemented because it makes the lossless round-trip test below possible, and because the
BLP2 header field has an enumerated meaning. It is **not** used for anything that ships, and
this repo has *not* confirmed that Wow.exe 12340 renders a compression=3 BLP. There is no
example to learn from either: 1500 `Interface\\*.blp` files sampled at random out of the 14071
the archives' listfiles name are 1491 DXT and 9 palettised, and **zero** raw BGRA (NOTES.md §2
has the breakdown). Treat "the client accepts raw BGRA" as an untested claim. The atlases are
written back as DXT5, the format they already are, so the question never arises for the shipped
artefact.

DXT DETAILS THAT MATTER
-----------------------
  * 565 unpacking uses bit replication (r5<<3 | r5>>2), the S3TC/D3D behaviour, not the
    truncating (r5<<3) form some tools use. Both are self-consistent; replication is what the
    hardware does and it makes decode->quantise->encode land on the same 5-bit value.
  * The 3-colour "c0 <= c1" mode with a transparent index 3 exists **only in DXT1**. For DXT3
    and DXT5 the colour block is always 4-colour whatever the endpoint order, so the decoder is
    told which kind it is reading instead of inferring it from c0/c1.
  * The encoder picks endpoints by projecting the block's pixels onto the principal axis of
    their covariance and taking the two extreme *pixels* (libsquish's "range fit"), then tries
    one least-squares refit and keeps it only if the squared error strictly drops. That last
    condition is what makes re-encoding already-DXT data idempotent: a block that was produced
    by a DXT decoder already lies exactly on its own endpoint line, the range fit recovers those
    endpoints with zero error, and no refit can beat zero. `--selftest` measures how often that
    actually holds instead of asserting it (see below).

SELFTEST
--------
Three round trips per file, because "decode -> encode -> decode is exact" is only honest for a
lossless format:

    T1 container   parse(bytes).to_bytes() == bytes            exact, asserted
    T2 pixels      decode -> encode as raw BGRA -> decode      exact, asserted
    T3 DXT         decode -> re-encode in the file's own DXT   lossy, measured and reported
    T4 Pillow      decode vs PIL.BlpImagePlugin                asserted to within 7, when Pillow
                   is installed (it expands 565 by truncation where this codec replicates bits)

T3 reports the max RGB delta *among texels with alpha > 0* separately from the max alpha delta,
because the RGB of a fully transparent texel is whatever fell out of the colour fit and nothing
ever samples it; and it splits blocks into byte-identical / decode-identical / actually
different, because a block can be spelled two ways and mean the same thing (Blizzard writes a
fully transparent block as a0=0,a1=1; this codec writes 0,0).

Measured on the two atlases this repo edits: max 4 per RGB channel where alpha > 0, and 3993 of
4096 (create) / 3971 of 4096 (circles) level-0 blocks come back identical or equivalent. That
number is why `make_class_icons.py` splices blocks instead of re-encoding whole images -- 4 is
small, but "0 outside the new cell" is free.
"""

import argparse
import os
import struct
import sys

MAGIC = b"BLP2"

# BLP2 header.compression
COMP_PALETTE = 1
COMP_DXT = 2
COMP_BGRA = 3

# BLP2 header.alphaEncoding, meaningful when compression == COMP_DXT
DXT1 = 0
DXT3 = 1
DXT5 = 7

_HDR = struct.Struct("<4sIBBBBII")      # magic, version, comp, alphaBits, alphaEnc, mips, w, h
_MIPS = 16                              # fixed-size offset/size tables
PALETTE_BYTES = 256 * 4
HEADER_BYTES = _HDR.size + _MIPS * 4 * 2 + PALETTE_BYTES     # 20 + 64 + 64 + 1024 = 1172

_KIND_NAME = {DXT1: "DXT1", DXT3: "DXT3", DXT5: "DXT5"}


# ==========================================================================================
# a plain RGBA8 image
# ==========================================================================================

class Rgba:
    """Row-major RGBA8. No stride, no palette, no surprises."""

    __slots__ = ("w", "h", "px")

    def __init__(self, w, h, px=None):
        self.w, self.h = w, h
        self.px = bytearray(px) if px is not None else bytearray(4 * w * h)
        assert len(self.px) == 4 * w * h, f"{len(self.px)} bytes for a {w}x{h} RGBA image"

    def get(self, x, y):
        i = 4 * (y * self.w + x)
        return (self.px[i], self.px[i + 1], self.px[i + 2], self.px[i + 3])

    def put(self, x, y, rgba):
        i = 4 * (y * self.w + x)
        self.px[i], self.px[i + 1], self.px[i + 2], self.px[i + 3] = rgba

    def copy(self):
        return Rgba(self.w, self.h, self.px)

    def crop(self, x0, y0, w, h):
        out = Rgba(w, h)
        for y in range(h):
            s = 4 * ((y0 + y) * self.w + x0)
            out.px[4 * y * w: 4 * (y + 1) * w] = self.px[s: s + 4 * w]
        return out

    def paste(self, src, x0, y0, sx0=0, sy0=0, w=None, h=None):
        """Copy a rectangle of `src` (RGBA, no blending -- the destination is replaced)."""
        w = src.w - sx0 if w is None else w
        h = src.h - sy0 if h is None else h
        for y in range(h):
            s = 4 * ((sy0 + y) * src.w + sx0)
            d = 4 * ((y0 + y) * self.w + x0)
            self.px[d: d + 4 * w] = src.px[s: s + 4 * w]

    def fill(self, rgba, x0=0, y0=0, w=None, h=None):
        w = self.w - x0 if w is None else w
        h = self.h - y0 if h is None else h
        row = bytes(rgba) * w
        for y in range(y0, y0 + h):
            d = 4 * (y * self.w + x0)
            self.px[d: d + 4 * w] = row

    def halve(self):
        """2x2 box filter with alpha-weighted colour.

        Colour is averaged *premultiplied* and divided back out, because the alternative --
        averaging RGB straight -- drags the colour of fully transparent texels into the visible
        result and puts a dark halo around anything with a soft edge, which is exactly what the
        round mask on UI-Classes-Circles is. Where all four inputs are transparent there is no
        colour to preserve, so the plain mean is used and the texel stays alpha 0 anyway.
        """
        w, h = max(1, self.w // 2), max(1, self.h // 2)
        out = Rgba(w, h)
        for y in range(h):
            for x in range(w):
                acc_r = acc_g = acc_b = acc_a = 0
                raw_r = raw_g = raw_b = 0
                for dy in (0, 1):
                    for dx in (0, 1):
                        sx = min(2 * x + dx, self.w - 1)
                        sy = min(2 * y + dy, self.h - 1)
                        r, g, b, a = self.get(sx, sy)
                        acc_r += r * a
                        acc_g += g * a
                        acc_b += b * a
                        acc_a += a
                        raw_r += r
                        raw_g += g
                        raw_b += b
                if acc_a:
                    out.put(x, y, ((acc_r + acc_a // 2) // acc_a,
                                   (acc_g + acc_a // 2) // acc_a,
                                   (acc_b + acc_a // 2) // acc_a,
                                   (acc_a + 2) // 4))
                else:
                    out.put(x, y, ((raw_r + 2) // 4, (raw_g + 2) // 4, (raw_b + 2) // 4, 0))
        return out

    def diff(self, other):
        """(max channel delta, mean channel delta, count of differing pixels)."""
        assert (self.w, self.h) == (other.w, other.h)
        worst = 0
        total = 0
        ndiff = 0
        for i in range(0, len(self.px), 4):
            d = 0
            for k in range(4):
                dk = abs(self.px[i + k] - other.px[i + k])
                total += dk
                if dk > d:
                    d = dk
            if d:
                ndiff += 1
            if d > worst:
                worst = d
        return worst, total / (len(self.px) or 1), ndiff


# ==========================================================================================
# DXT blocks
# ==========================================================================================

def unpack565(c):
    """RGB565 -> 8-bit per channel by bit replication, which is what the GPU does."""
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def pack565(r, g, b):
    """8-bit per channel -> RGB565, rounded. Exactly inverts unpack565."""
    return (((r * 31 + 127) // 255) << 11) | (((g * 63 + 127) // 255) << 5) | \
           ((b * 31 + 127) // 255)


def block_bytes(kind):
    return 8 if kind == DXT1 else 16


def _colour_palette(c0, c1, four_colour):
    a = unpack565(c0)
    b = unpack565(c1)
    if four_colour:
        return [a, b,
                ((2 * a[0] + b[0]) // 3, (2 * a[1] + b[1]) // 3, (2 * a[2] + b[2]) // 3),
                ((a[0] + 2 * b[0]) // 3, (a[1] + 2 * b[1]) // 3, (a[2] + 2 * b[2]) // 3)]
    return [a, b,
            ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2, (a[2] + b[2]) // 2),
            (0, 0, 0)]


def decode_block(kind, data, off, punchthrough=True):
    """One 4x4 block -> 16 RGBA tuples in row-major order.

    `punchthrough` only means anything for DXT1: it is the file's alphaBits telling us whether
    index 3 of a 3-colour block is transparent black or opaque black.
    """
    alpha = [255] * 16
    if kind == DXT5:
        a0, a1 = data[off], data[off + 1]
        bits = int.from_bytes(data[off + 2: off + 8], "little")
        if a0 > a1:
            tbl = [a0, a1] + [((7 - i) * a0 + i * a1 + 3) // 7 for i in range(1, 7)]
        else:
            tbl = [a0, a1] + [((5 - i) * a0 + i * a1 + 2) // 5 for i in range(1, 5)] + [0, 255]
        for i in range(16):
            alpha[i] = tbl[(bits >> (3 * i)) & 7]
        off += 8
    elif kind == DXT3:
        for i in range(16):
            nib = (data[off + i // 2] >> (4 * (i & 1))) & 0xF
            alpha[i] = nib * 17          # 4-bit -> 8-bit, (n<<4)|n
        off += 8

    c0, c1 = struct.unpack_from("<HH", data, off)
    bits = struct.unpack_from("<I", data, off + 4)[0]
    # 3-colour mode is a DXT1-only encoding; DXT3/DXT5 colour blocks are always 4-colour.
    four = (kind != DXT1) or (c0 > c1)
    pal = _colour_palette(c0, c1, four)
    out = []
    for i in range(16):
        idx = (bits >> (2 * i)) & 3
        r, g, b = pal[idx]
        a = alpha[i]
        if kind == DXT1 and not four and idx == 3 and punchthrough:
            a = 0
        out.append((r, g, b, a))
    return out


def _fit_endpoints(pts):
    """Two extreme pixels along the principal axis of `pts` (list of (r,g,b))."""
    n = len(pts)
    mr = sum(p[0] for p in pts) / n
    mg = sum(p[1] for p in pts) / n
    mb = sum(p[2] for p in pts) / n
    cxx = cyy = czz = cxy = cxz = cyz = 0.0
    for r, g, b in pts:
        dr, dg, db = r - mr, g - mg, b - mb
        cxx += dr * dr
        cyy += dg * dg
        czz += db * db
        cxy += dr * dg
        cxz += dr * db
        cyz += dg * db
    # Seed the power iteration with the bounding-box diagonal: it is the right answer for most
    # blocks already, and it keeps the iteration off the degenerate all-equal start vector.
    vx = max(p[0] for p in pts) - min(p[0] for p in pts)
    vy = max(p[1] for p in pts) - min(p[1] for p in pts)
    vz = max(p[2] for p in pts) - min(p[2] for p in pts)
    if vx == vy == vz == 0:
        return pts[0], pts[0]
    vx, vy, vz = float(vx), float(vy), float(vz)
    for _ in range(8):
        nx = cxx * vx + cxy * vy + cxz * vz
        ny = cxy * vx + cyy * vy + cyz * vz
        nz = cxz * vx + cyz * vy + czz * vz
        m = max(abs(nx), abs(ny), abs(nz))
        if m < 1e-9:
            break
        vx, vy, vz = nx / m, ny / m, nz / m
    lo = hi = None
    lo_d = hi_d = None
    for p in pts:
        d = p[0] * vx + p[1] * vy + p[2] * vz
        if lo_d is None or d < lo_d:
            lo_d, lo = d, p
        if hi_d is None or d > hi_d:
            hi_d, hi = d, p
    return hi, lo


def _index_block(pts, pal):
    """Nearest-palette-entry index per pixel, plus the total squared error."""
    idx = []
    sse = 0
    for r, g, b in pts:
        best = 0
        bestd = None
        for i, (pr, pg, pb) in enumerate(pal):
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if bestd is None or d < bestd:
                bestd, best = d, i
        idx.append(best)
        sse += bestd
    return idx, sse


_LSQ_W = ((1.0, 0.0), (0.0, 1.0), (2 / 3, 1 / 3), (1 / 3, 2 / 3))


def _refit(pts, idx):
    """Least-squares endpoints for a fixed index assignment; None if the system is singular."""
    a2 = b2 = ab = 0.0
    ax = [0.0, 0.0, 0.0]
    bx = [0.0, 0.0, 0.0]
    for p, i in zip(pts, idx):
        wa, wb = _LSQ_W[i]
        a2 += wa * wa
        b2 += wb * wb
        ab += wa * wb
        for k in range(3):
            ax[k] += wa * p[k]
            bx[k] += wb * p[k]
    det = a2 * b2 - ab * ab
    if abs(det) < 1e-9:
        return None
    e0 = []
    e1 = []
    for k in range(3):
        e0.append(min(255, max(0, int(round((b2 * ax[k] - ab * bx[k]) / det)))))
        e1.append(min(255, max(0, int(round((a2 * bx[k] - ab * ax[k]) / det)))))
    return tuple(e0), tuple(e1)


def _pack_indices(idx, bits_each=2):
    bits = 0
    for i, v in enumerate(idx):
        bits |= v << (bits_each * i)
    return bits


def _encode_colour_4(pts):
    """4-colour (opaque) colour block for 16 (r,g,b) pixels -> (c0, c1, indices, sse).

    Endpoints are always emitted with c0 >= c1, which is what selects 4-colour mode in DXT1 and
    is simply the convention everywhere else. Indices are computed against the palette that is
    actually written, so there is no post-hoc index remapping to get wrong.
    """
    def build(ea, eb):
        c0, c1 = pack565(*ea), pack565(*eb)
        if c0 < c1:
            c0, c1 = c1, c0
        if c0 == c1:
            # Every palette entry is the same colour; index 0 is the only one that is also safe
            # if this block is later read as DXT1 3-colour (where index 3 means transparent).
            pal = _colour_palette(c0, c1, True)
            return c0, c1, [0] * 16, sum(
                (p[0] - pal[0][0]) ** 2 + (p[1] - pal[0][1]) ** 2 + (p[2] - pal[0][2]) ** 2
                for p in pts)
        pal = _colour_palette(c0, c1, True)
        idx, sse = _index_block(pts, pal)
        return c0, c1, idx, sse

    hi, lo = _fit_endpoints(pts)
    c0, c1, idx, sse = build(hi, lo)
    if sse:
        # One refinement pass, accepted only on a strict improvement. Keeping the range fit on a
        # tie is what preserves bit-exact re-encoding of already-DXT input (see module docstring).
        ref = _refit(pts, idx)
        if ref is not None:
            c0b, c1b, idxb, sseb = build(*ref)
            if sseb < sse:
                c0, c1, idx, sse = c0b, c1b, idxb, sseb
    return c0, c1, idx, sse


def _encode_colour_3(pts, opaque):
    """DXT1 3-colour block: c0 <= c1, index 3 is transparent black.

    Only reachable when a DXT1 image actually has transparent texels. The endpoints are fitted
    over the opaque texels alone -- letting a transparent texel's leftover RGB pull the line is
    how "why is the edge of my cut-out the wrong colour" happens.
    """
    lit = [p for p, o in zip(pts, opaque) if o] or [(0, 0, 0)]
    hi, lo = _fit_endpoints(lit)
    c0, c1 = pack565(*hi), pack565(*lo)
    if c0 > c1:
        c0, c1 = c1, c0                      # 3-colour mode is selected by c0 <= c1
    pal = _colour_palette(c0, c1, False)[:3]
    idx = []
    sse = 0
    for p, o in zip(pts, opaque):
        if not o:
            idx.append(3)
            continue
        best, bestd = 0, None
        for i, q in enumerate(pal):
            d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
            if bestd is None or d < bestd:
                bestd, best = d, i
        idx.append(best)
        sse += bestd
    return c0, c1, idx, sse


def _alpha_table(a0, a1):
    """The eight alpha values a DXT5 block decodes to, for either endpoint order."""
    if a0 > a1:
        return [a0, a1] + [((7 - i) * a0 + i * a1 + 3) // 7 for i in range(1, 7)]
    return [a0, a1] + [((5 - i) * a0 + i * a1 + 2) // 5 for i in range(1, 5)] + [0, 255]


def _alpha_fit(al, tbl):
    idx = []
    sse = 0
    for a in al:
        best, bestd = 0, None
        for i, v in enumerate(tbl):
            d = (a - v) ** 2
            if bestd is None or d < bestd:
                bestd, best = d, i
        idx.append(best)
        sse += bestd
    return idx, sse


def _encode_alpha_dxt5(al):
    """(a0, a1, 16 indices) for a DXT5 alpha half, trying both of the format's two modes.

    a0 > a1 gives eight values interpolated between the endpoints; a0 <= a1 gives six plus a
    free 0 and 255, which is the better fit when a block holds both a hard cut-out and a ramp,
    because the eight-value mode otherwise spends two of its slots reproducing 0 and 255.

    The three-way split below is the one Blizzard's own encoder used on
    UI-CharacterCreate-Classes.blp level 0, counted block by block: 2010 of 4096 blocks are flat
    255 written as a0=a1=255, 1477 are flat 0, and almost every graded block is eight-value with
    a0=255. Matching that shape is not cosmetic -- it is what lets a re-encode of untouched art
    come back byte-identical instead of merely equivalent.
    """
    hi, lo = max(al), min(al)
    if hi == lo:
        # Flat block. Both modes decode identically; a0 == a1 with index 0 is the canonical form.
        return hi, hi, [0] * 16
    idx, sse = _alpha_fit(al, _alpha_table(hi, lo))
    best = (hi, lo, idx)
    inner = [a for a in al if 0 < a < 255]
    if inner and sse:
        a0, a1 = min(inner), max(inner)          # a0 <= a1 selects the six-value mode
        idx6, sse6 = _alpha_fit(al, _alpha_table(a0, a1))
        if sse6 < sse:
            best = (a0, a1, idx6)
    return best


def encode_block(kind, px16):
    """16 RGBA tuples (row-major) -> one DXT block."""
    assert len(px16) == 16
    out = b""
    if kind == DXT5:
        a0, a1, idx = _encode_alpha_dxt5([p[3] for p in px16])
        out += bytes((a0, a1)) + _pack_indices(idx, 3).to_bytes(6, "little")
    elif kind == DXT3:
        buf = bytearray(8)
        for i, p in enumerate(px16):
            nib = (p[3] * 15 + 127) // 255
            buf[i // 2] |= nib << (4 * (i & 1))
        out += bytes(buf)

    rgb = [(p[0], p[1], p[2]) for p in px16]
    if kind == DXT1:
        # DXT1 carries at most one bit of alpha, and only in 3-colour mode.
        opaque = [p[3] >= 128 for p in px16]
        if not all(opaque):
            c0, c1, idx, _sse = _encode_colour_3(rgb, opaque)
            return out + struct.pack("<HHI", c0, c1, _pack_indices(idx))
    c0, c1, idx, _sse = _encode_colour_4(rgb)
    return out + struct.pack("<HHI", c0, c1, _pack_indices(idx))


# ==========================================================================================
# the file
# ==========================================================================================

class Blp:
    """One BLP2 file. `levels` holds the raw per-mip payload, so a level nobody edits is
    carried through byte-for-byte rather than decoded and re-compressed."""

    def __init__(self, width, height, compression=COMP_DXT, alpha_bits=8, alpha_encoding=DXT5,
                 has_mips=1, version=1, palette=None, levels=None):
        self.width = width
        self.height = height
        self.compression = compression
        self.alpha_bits = alpha_bits
        self.alpha_encoding = alpha_encoding
        self.has_mips = has_mips
        self.version = version
        self.palette = bytearray(palette if palette is not None else bytes(PALETTE_BYTES))
        self.levels = list(levels or [])
        assert len(self.palette) == PALETTE_BYTES

    # ------------------------------------------------------------------------- io ----
    @classmethod
    def parse(cls, blob):
        magic, version, comp, abits, aenc, mips, w, h = _HDR.unpack_from(blob, 0)
        assert magic == MAGIC, f"not a BLP2 file (magic {magic!r})"
        assert version == 1, f"BLP2 version {version}, expected 1"
        offs = struct.unpack_from(f"<{_MIPS}I", blob, _HDR.size)
        sizes = struct.unpack_from(f"<{_MIPS}I", blob, _HDR.size + _MIPS * 4)
        pal = blob[_HDR.size + _MIPS * 8: HEADER_BYTES]
        self = cls(w, h, comp, abits, aenc, mips, version, pal)
        for i in range(_MIPS):
            if not sizes[i]:
                break
            assert offs[i] + sizes[i] <= len(blob), \
                f"mip {i} runs past the end of the file ({offs[i]}+{sizes[i]} > {len(blob)})"
            # bytearray, not bytes: put_block_pixels edits a level in place, and a 256x256
            # level-0 copy per block would be 16 MB of memcpy for one 64x64 cell.
            self.levels.append(bytearray(blob[offs[i]: offs[i] + sizes[i]]))
        assert self.levels, "no mip levels"
        return self

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self):
        offs = [0] * _MIPS
        sizes = [0] * _MIPS
        pos = HEADER_BYTES
        for i, lvl in enumerate(self.levels):
            offs[i], sizes[i] = pos, len(lvl)
            pos += len(lvl)
        out = bytearray()
        out += _HDR.pack(MAGIC, self.version, self.compression, self.alpha_bits,
                         self.alpha_encoding, self.has_mips, self.width, self.height)
        out += struct.pack(f"<{_MIPS}I", *offs)
        out += struct.pack(f"<{_MIPS}I", *sizes)
        out += self.palette
        for lvl in self.levels:
            out += lvl
        return bytes(out)

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.to_bytes())
        return path

    # -------------------------------------------------------------------- geometry ----
    def dims(self, level):
        return (max(1, self.width >> level), max(1, self.height >> level))

    def block_grid(self, level):
        """(blocks across, blocks down, bytes per block). DXT only."""
        assert self.compression == COMP_DXT, "block grid is a DXT concept"
        w, h = self.dims(level)
        return ((w + 3) // 4, (h + 3) // 4, block_bytes(self.alpha_encoding))

    def expected_level_size(self, level):
        w, h = self.dims(level)
        if self.compression == COMP_DXT:
            bw, bh, bsz = self.block_grid(level)
            return bw * bh * bsz
        if self.compression == COMP_BGRA:
            return w * h * 4
        n = w * h
        return n + {0: 0, 1: (n + 7) // 8, 4: (n + 1) // 2, 8: n}[self.alpha_bits]

    # ---------------------------------------------------------------------- pixels ----
    def decode(self, level=0):
        w, h = self.dims(level)
        data = self.levels[level]
        img = Rgba(w, h)
        if self.compression == COMP_DXT:
            kind = self.alpha_encoding
            bw, bh, bsz = self.block_grid(level)
            punch = self.alpha_bits > 0
            for by in range(bh):
                for bx in range(bw):
                    px = decode_block(kind, data, (by * bw + bx) * bsz, punch)
                    for i, p in enumerate(px):
                        x, y = 4 * bx + (i % 4), 4 * by + (i // 4)
                        if x < w and y < h:
                            img.put(x, y, p)
            return img
        if self.compression == COMP_BGRA:
            for i in range(w * h):
                b, g, r, a = data[4 * i: 4 * i + 4]
                img.px[4 * i: 4 * i + 4] = bytes((r, g, b, a))
            return img
        if self.compression == COMP_PALETTE:
            n = w * h
            for i in range(n):
                e = 4 * data[i]
                b, g, r = self.palette[e], self.palette[e + 1], self.palette[e + 2]
                if self.alpha_bits == 8:
                    a = data[n + i]
                elif self.alpha_bits == 4:
                    a = ((data[n + i // 2] >> (4 * (i & 1))) & 0xF) * 17
                elif self.alpha_bits == 1:
                    a = 255 if (data[n + i // 8] >> (i & 7)) & 1 else 0
                else:
                    a = 255
                img.px[4 * i: 4 * i + 4] = bytes((r, g, b, a))
            return img
        raise ValueError(f"unknown BLP2 compression {self.compression}")

    # ------------------------------------------------------- block-level splicing ----
    #
    # The point of these two: editing one 64x64 cell of a 256x256 atlas must not re-compress
    # the other fifteen sixteenths of Blizzard's art. Decode a block, overwrite the texels that
    # are actually changing, encode that block back, leave every other byte alone.

    def block_pixels(self, level, bx, by):
        bw, _bh, bsz = self.block_grid(level)
        return decode_block(self.alpha_encoding, self.levels[level], (by * bw + bx) * bsz,
                            self.alpha_bits > 0)

    def put_block_pixels(self, level, bx, by, px16):
        bw, _bh, bsz = self.block_grid(level)
        off = (by * bw + bx) * bsz
        blk = encode_block(self.alpha_encoding, px16)
        assert len(blk) == bsz
        self.levels[level][off: off + bsz] = blk

    # ----------------------------------------------------------------- construction ----
    @classmethod
    def from_rgba(cls, img, compression=COMP_DXT, alpha_encoding=DXT5, alpha_bits=8,
                  has_mips=1, mips=True):
        if compression == COMP_PALETTE:
            raise NotImplementedError(
                "palettised BLP2 encoding needs a colour quantiser; this codec decodes "
                "compression 1 but will not author it")
        self = cls(img.w, img.h, compression, alpha_bits, alpha_encoding,
                   has_mips if mips else 0)
        cur = img
        while True:
            self.levels.append(self._encode_level(cur))
            if not mips or (cur.w == 1 and cur.h == 1):
                break
            cur = cur.halve()
        return self

    def _encode_level(self, img):
        if self.compression == COMP_BGRA:
            out = bytearray(4 * img.w * img.h)
            for i in range(img.w * img.h):
                r, g, b, a = img.px[4 * i: 4 * i + 4]
                out[4 * i: 4 * i + 4] = bytes((b, g, r, a))
            return out
        if self.compression != COMP_DXT:
            raise NotImplementedError(f"cannot encode compression {self.compression}")
        kind = self.alpha_encoding
        bw, bh = (img.w + 3) // 4, (img.h + 3) // 4
        out = bytearray()
        for by in range(bh):
            for bx in range(bw):
                px = []
                for i in range(16):
                    x = min(4 * bx + (i % 4), img.w - 1)
                    y = min(4 * by + (i // 4), img.h - 1)
                    px.append(img.get(x, y))
                out += encode_block(kind, px)
        return out

    # ------------------------------------------------------------------------ misc ----
    def header_line(self):
        kind = _KIND_NAME.get(self.alpha_encoding, "?") if self.compression == COMP_DXT else \
            {COMP_PALETTE: "palettised", COMP_BGRA: "raw BGRA"}.get(self.compression, "?")
        return (f"BLP2 v{self.version} compression={self.compression} "
                f"alphaBits={self.alpha_bits} alphaEncoding={self.alpha_encoding} "
                f"hasMips={self.has_mips} {self.width}x{self.height} "
                f"{len(self.levels)} levels ({kind})")


# ==========================================================================================
# selftest
# ==========================================================================================

def selftest(paths):
    failed = 0
    for path in paths:
        with open(path, "rb") as f:
            blob = f.read()
        b = Blp.parse(blob)
        print(f"\n== {path}\n   {b.header_line()}")
        print(f"   mip sizes {[len(l) for l in b.levels]}")

        for i in range(len(b.levels)):
            want = b.expected_level_size(i)
            if len(b.levels[i]) != want:
                print(f"   [FAIL] mip {i} is {len(b.levels[i])} bytes, geometry says {want}")
                failed += 1

        # T1 -- container round trip, exact.
        out = b.to_bytes()
        if out == blob:
            print("   [PASS] T1 container: re-serialised file is byte-identical")
        else:
            print(f"   [FAIL] T1 container: {len(out)} bytes vs {len(blob)}")
            failed += 1

        img = b.decode(0)

        # T2 -- lossless pixel round trip through raw BGRA, exact.
        raw = Blp.from_rgba(img, compression=COMP_BGRA, alpha_bits=8, mips=False)
        back = Blp.parse(raw.to_bytes()).decode(0)
        worst, mean, ndiff = img.diff(back)
        if worst == 0:
            print("   [PASS] T2 pixels: decode -> raw BGRA -> decode is exact "
                  f"({img.w}x{img.h}, {img.w * img.h} texels)")
        else:
            print(f"   [FAIL] T2 pixels: max delta {worst}, {ndiff} texels differ")
            failed += 1

        # T3 -- re-encode in the file's own format, lossy, measured.
        #
        # Reported three ways on purpose. A raw "max channel delta" over RGBA is misleading for
        # a cut-out texture: the RGB of a fully transparent texel is whatever fell out of the
        # colour fit and nothing ever samples it. Likewise a block can differ byte-for-byte and
        # still decode to exactly the same sixteen texels, which is what "equivalent" counts.
        if b.compression == COMP_DXT:
            re_enc = Blp.from_rgba(img, compression=COMP_DXT,
                                   alpha_encoding=b.alpha_encoding,
                                   alpha_bits=b.alpha_bits, has_mips=b.has_mips)
            again = re_enc.decode(0)
            worst_rgb = worst_a = 0
            for y in range(img.h):
                for x in range(img.w):
                    p, q = img.get(x, y), again.get(x, y)
                    worst_a = max(worst_a, abs(p[3] - q[3]))
                    if p[3]:
                        worst_rgb = max(worst_rgb, max(abs(p[k] - q[k]) for k in range(3)))
            _worst, mean, ndiff = img.diff(again)
            bsz = block_bytes(b.alpha_encoding)
            n = len(b.levels[0]) // bsz
            same = equiv = 0
            for i in range(n):
                if b.levels[0][i * bsz:(i + 1) * bsz] == re_enc.levels[0][i * bsz:(i + 1) * bsz]:
                    same += 1
                elif decode_block(b.alpha_encoding, b.levels[0], i * bsz, b.alpha_bits > 0) == \
                        decode_block(b.alpha_encoding, re_enc.levels[0], i * bsz,
                                     b.alpha_bits > 0):
                    equiv += 1
            print(f"   [INFO] T3 {_KIND_NAME[b.alpha_encoding]} re-encode: max delta "
                  f"{worst_rgb} rgb (where alpha>0) / {worst_a} alpha, mean {mean:.3f} over "
                  f"RGBA, {ndiff}/{img.w * img.h} texels changed")
            print(f"   [INFO] T3 level-0 blocks: {same}/{n} byte-identical, {equiv} more decode "
                  f"identically, {n - same - equiv} actually differ")

        # optional independent decoder cross-check
        try:
            from PIL import Image as _PILImage       # noqa: PLC0415
        except ImportError:
            print("   [SKIP] Pillow not installed; no independent decoder cross-check")
        else:
            pil = _PILImage.open(path).convert("RGBA")
            if pil.size != (img.w, img.h):
                print(f"   [FAIL] Pillow says {pil.size}, we say {(img.w, img.h)}")
                failed += 1
            else:
                pp = pil.load()
                worst = 0
                for y in range(img.h):
                    for x in range(img.w):
                        a = img.get(x, y)
                        c = pp[x, y]
                        worst = max(worst, max(abs(a[k] - c[k]) for k in range(4)))
                # Pillow's BlpImagePlugin expands 565 by truncation (r5<<3) where this codec
                # replicates bits, so agreement is expected to within 7, not to the byte.
                ok = worst <= 7
                print(f"   [{'PASS' if ok else 'FAIL'}] Pillow cross-check: max channel "
                      f"delta {worst} (<=7 is the 565-expansion difference)")
                failed += 0 if ok else 1
    print(f"\n{failed} failed")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--info", action="store_true", help="print each file's real header")
    ap.add_argument("--selftest", action="store_true", help="round-trip each file")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.files)
    for path in args.files:
        b = Blp.load(path)
        print(f"{path}\n   {b.header_line()}\n   mip sizes {[len(l) for l in b.levels]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
