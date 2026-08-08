#!/usr/bin/env python3
"""Format-aware WDBC (3.3.5a) reader/writer.

Grown from the round-trip-proven primitive in .work/notes/dbclib.py. That version assumed
`field_count * 4 == record_size`, which holds for Spell.dbc and SkillLineAbility.dbc but NOT
for CharStartOutfit.dbc (77 fields, 296 bytes -- four of the "fields" are single bytes packed
into one DWORD). Byte offsets are therefore computed from the core's format string, never from
the column index. See dbc_tables.py for the format-character table.

THE ONE DESIGN RULE HERE: records are raw bytearrays and a clone is a memcpy.

Cloning a Spell.dbc record byte-for-byte is what makes the whole feature work. Icy Touch's DK
behaviour is not carried by its spell ID -- it is carried by SpellClassSet=15 and
SpellClassMask_1=2, which every talent, glyph and proc entry matches on via
SpellInfo::IsAffected (SpellInfo.cpp:1325). Authoring a row field-by-field would silently drop
whichever of the 234 cells nobody thought about. A memcpy cannot.

The string block is only ever APPENDED to, never rewritten, so the string offsets inside a
cloned record stay valid without any fixup. add_string() reuses an identical existing string
when there is one, which is why cloning "Icy Touch"/"Rank 1" costs zero bytes.
"""

import os
import struct

HDR = struct.Struct("<4sIIII")  # magic, record_count, field_count, record_size, string_block_size


class Dbc:
    """One WDBC file, interpreted through a dbc_tables.DbcTable."""

    def __init__(self, table, path=None):
        self.table = table
        self.records = []               # list[bytearray], each record_size bytes
        self.strings = bytearray(b"\x00")   # offset 0 is always the empty string
        self.field_count = 0
        self.record_size = 0
        self.source_path = None
        if path:
            self.load(path)

    # ---------------------------------------------------------------- io ----
    def load(self, path):
        with open(path, "rb") as f:
            blob = f.read()
        magic, rc, fc, rs, ss = HDR.unpack_from(blob, 0)
        assert magic == b"WDBC", f"{path}: not a WDBC file ({magic!r})"
        assert len(blob) == HDR.size + rc * rs + ss, (
            f"{path}: size mismatch, file={len(blob)} expected={HDR.size + rc * rs + ss}")
        # GENERATOR INVARIANT #1, checked on the way in rather than on the way out: the file's
        # own header must agree with the format string the SERVER will use for the SQL override
        # table. If these ever disagree, every emitted row is misaligned and
        # DBCDatabaseLoader.cpp:124 aborts worldserver at boot.
        assert fc == len(self.table.fmt), (
            f"{path}: field_count {fc} != strlen({self.table.sql_table} format) "
            f"{len(self.table.fmt)}")
        assert rs == self.table.record_size, (
            f"{path}: record_size {rs} != format-implied {self.table.record_size}")
        self.field_count, self.record_size = fc, rs
        base = HDR.size
        self.records = [bytearray(blob[base + i * rs: base + (i + 1) * rs]) for i in range(rc)]
        self.strings = bytearray(blob[base + rc * rs:])
        assert self.strings and self.strings[0] == 0, (
            f"{path}: string block must start with NUL so offset 0 means empty string")
        self.source_path = path
        return self

    def save(self, path):
        rc, fc, rs = len(self.records), self.field_count, self.record_size
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(HDR.pack(b"WDBC", rc, fc, rs, len(self.strings)))
            for r in self.records:
                assert len(r) == rs, f"record length {len(r)} != {rs}"
                f.write(bytes(r))
            f.write(bytes(self.strings))
        return path

    # -------------------------------------------------------- cell access ----
    def _off(self, col):
        return self.table.offsets[col]

    def get_u32(self, row, col):
        return struct.unpack_from("<I", self.records[row], self._off(col))[0]

    def get_i32(self, row, col):
        return struct.unpack_from("<i", self.records[row], self._off(col))[0]

    def get_f32(self, row, col):
        return struct.unpack_from("<f", self.records[row], self._off(col))[0]

    def get_u8(self, row, col):
        return self.records[row][self._off(col)]

    def set_u32(self, row, col, v):
        struct.pack_into("<I", self.records[row], self._off(col), v & 0xFFFFFFFF)

    def set_i32(self, row, col, v):
        struct.pack_into("<i", self.records[row], self._off(col), v)

    def set_f32(self, row, col, v):
        struct.pack_into("<f", self.records[row], self._off(col), v)

    def set_u8(self, row, col, v):
        assert 0 <= v <= 255, f"byte column {self.table.columns[col]} out of range: {v}"
        self.records[row][self._off(col)] = v

    def get_str(self, row, col):
        off = self.get_u32(row, col)
        if off == 0 or off >= len(self.strings):
            return ""
        end = self.strings.index(b"\x00", off)
        return self.strings[off:end].decode("utf-8", "replace")

    def add_string(self, s):
        """Append to the string block, return its offset. '' always maps to 0.

        Reuses an identical NUL-bounded string if the block already holds one, so setting a
        cloned cell to the value it already has is a byte-level no-op.
        """
        if s == "":
            return 0
        b = s.encode("utf-8")
        needle = b"\x00" + b + b"\x00"
        i = self.strings.find(needle)
        if i >= 0:
            return i + 1
        off = len(self.strings)
        self.strings += b + b"\x00"
        return off

    def set_str(self, row, col, s):
        self.set_u32(row, col, self.add_string(s))

    # ----------------------------------------------- kind-dispatched access --
    def cell(self, row, col):
        """The canonical Python value of a cell, chosen by the table's column kind.

        This is the value that gets compared against the SQL side in generator invariant #4,
        so signedness matters: charstartoutfit ItemID_* really do hold -1, and reading them
        unsigned would emit 4294967295 into a signed `int` column and blow up under
        STRICT_TRANS_TABLES.
        """
        from dbc_tables import KIND_FLOAT, KIND_STRING, KIND_UINT8, KIND_INT32
        k = self.table.kind(col)
        if k == KIND_STRING:
            return self.get_str(row, col)
        if k == KIND_FLOAT:
            return self.get_f32(row, col)
        if k == KIND_UINT8:
            return self.get_u8(row, col)
        if k == KIND_INT32:
            return self.get_i32(row, col)
        return self.get_u32(row, col)

    def set_cell(self, row, col, value):
        from dbc_tables import KIND_FLOAT, KIND_STRING, KIND_UINT8, KIND_INT32
        k = self.table.kind(col)
        if k == KIND_STRING:
            self.set_str(row, col, value)
        elif k == KIND_FLOAT:
            self.set_f32(row, col, value)
        elif k == KIND_UINT8:
            self.set_u8(row, col, value)
        elif k == KIND_INT32:
            self.set_i32(row, col, value)
        else:
            self.set_u32(row, col, value)

    def row_values(self, row):
        """Every cell of a record, in format order."""
        return [self.cell(row, c) for c in range(len(self.table.columns))]

    # ------------------------------------------------------------ row ops ----
    def index(self):
        """{index-column value -> row number}."""
        ic = self.table.index_column()
        return {self.get_u32(i, ic): i for i in range(len(self.records))}

    def ids(self):
        ic = self.table.index_column()
        return [self.get_u32(i, ic) for i in range(len(self.records))]

    def clone_row(self, src_row):
        """Deep-clone a row (memcpy). String cells keep pointing at the ORIGINAL offsets,
        which is correct: the old string block is never rewritten, only appended to."""
        self.records.append(bytearray(self.records[src_row]))
        return len(self.records) - 1

    def is_strictly_ascending(self):
        ids = self.ids()
        return all(ids[i] < ids[i + 1] for i in range(len(ids) - 1))
