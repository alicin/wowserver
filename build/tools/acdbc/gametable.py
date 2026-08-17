#!/usr/bin/env python3
"""gt*.dbc -- the per-class scalar tables, which are not WDBC records in the usual sense.

WHY THIS IS NOT A DbcTable
--------------------------
Their format string is `"df"` -- two SQL columns, `ID` and `Data` -- but the FILE has
`field_count = 1, record_size = 4`: a bare float, no key. `d` is FT_SORT, and
`DBCFileLoader::GetFormatRecordSize` (DBCFileLoader.cpp:146) adds **zero** bytes for it, so the
index is the row number and exists only on the SQL side. Every DbcTable invariant
(`field_count == len(fmt)`, `record_size == format-implied size`) is therefore false for these
files, and forcing them through would mean weakening the assertions that protect the other nine.

WHY THEY MATTER FOR A NEW CLASS
-------------------------------
Blizzard did not leave the vacant class-10 slot empty; they left it full of placeholders. Read
off the live realm and the stock files:

    gtChanceToMeleeCritBase   row 9 (class 10) = 0.2      <- twenty percent base melee crit
    gtChanceToSpellCritBase   row 9 (class 10) = 0.2
    gtChanceToMeleeCrit       rows 900-999     = 0.01     <- ~4x a Rogue's crit-per-agility
    gtOCTRegenHP              rows 900-999     = 1.0
    gtRegenHPPerSpt           rows 900-999     = 0.0

A class that inherits those is not subtly mistuned, it is comically wrong, and the error is
visible on the character sheet before it is visible in combat. Both halves need fixing --
the server computes from its `gt*_dbc` override rows, the client renders the character sheet
from its own copy of the file -- which is the same two-halves-one-generator problem the spell
tooltips have (`docs/death-knights.md` 2).

Layout is `(class - 1) * GT_MAX_LEVEL + (level - 1)` for the per-level tables
(Player.cpp:5268) and `(class - 1)` for the `*Base` ones (Player.cpp:5267), so class 10 owns
rows 900-999 and row 9 respectively. `Gametable.block()` in dbc_tables.py computes both.
"""

import os
import struct

HDR = struct.Struct("<4sIIII")  # magic, record_count, field_count, record_size, string_block


class GametableFile:
    """A flat array of float32. Indexable by row number, which IS the ID."""

    def __init__(self, path=None):
        self.values = []
        self.source_path = None
        if path:
            self.load(path)

    def load(self, path):
        with open(path, "rb") as f:
            blob = f.read()
        magic, rc, fc, rs, ss = HDR.unpack_from(blob, 0)
        assert magic == b"WDBC", f"{path}: not a WDBC file ({magic!r})"
        # Asserted rather than assumed: if a gt file ever grows a second column this reader
        # would silently return every other value.
        assert fc == 1 and rs == 4, (
            f"{path}: expected a single 4-byte float column, got field_count={fc} "
            f"record_size={rs} -- this is not a gametable")
        assert len(blob) == HDR.size + rc * rs + ss, f"{path}: size mismatch"
        self.values = list(struct.unpack_from(f"<{rc}f", blob, HDR.size))
        self.string_block = blob[HDR.size + rc * rs:]
        self.source_path = path
        return self

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(HDR.pack(b"WDBC", len(self.values), 1, 4, len(self.string_block)))
            f.write(struct.pack(f"<{len(self.values)}f", *self.values))
            f.write(self.string_block)
        return path

    def copy_block(self, src_lo, dst_lo, count):
        """Overwrite [dst_lo, dst_lo+count) with [src_lo, src_lo+count).

        Returns the list of (row, old, new) that actually changed, so the caller can report and
        assert on it rather than trusting that anything happened.
        """
        assert src_lo + count <= len(self.values), (
            f"source block {src_lo}..{src_lo + count - 1} runs past the end "
            f"({len(self.values)} rows)")
        assert dst_lo + count <= len(self.values), (
            f"destination block {dst_lo}..{dst_lo + count - 1} runs past the end "
            f"({len(self.values)} rows) -- the file does not have a slot for this class, which "
            f"means the class id is outside what Blizzard reserved")
        changed = []
        for i in range(count):
            old, new = self.values[dst_lo + i], self.values[src_lo + i]
            if _bits(old) != _bits(new):
                changed.append((dst_lo + i, old, new))
            self.values[dst_lo + i] = new
        return changed


def _bits(f):
    """Compare floats by their bit pattern, not by ==, so -0.0 and NaN behave."""
    return struct.pack("<f", f)
