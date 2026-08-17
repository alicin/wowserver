"""Import whole Spell.dbc records out of an installed Ascension client.

WHY THIS REPLACES THE DONOR MECHANISM
-------------------------------------
The Death Knight and the first Demon Hunter were built by memcpy-ing a stock Blizzard
spell and overriding named cells (dh_donors.py). That exists because there was no
record anywhere that already described the ability -- the donor's value was in the ~222
cells nobody names.

For an Ascension port there IS such a record, and it is better than any donor: it is the
ability. Ascension kept Blizzard's layout exactly -- 234 fields, 936-byte records,
verified on open -- so their record can be transplanted whole and only the identity cells
rewritten.

THE ONE THING THAT MAKES THIS NON-TRIVIAL: string columns hold OFFSETS into the file's
own string block, not text. A raw byte copy carries offsets that index into OUR string
block and produce garbage -- or, worse, a valid-looking wrong string. Every string column
is therefore resolved to text here and re-added on the way in. That is the whole reason
this returns a dict of Python values rather than bytes.
"""
import os
import struct

from acdbc import mpqlib

DEFAULT_CLIENT = "/mnt/ntfs2t/Ascension/Launcher/resources/ascension-live/Data"
SPELL_PATH = "DBFilesClient\\Spell.dbc"


class AscensionSpells:
    """Every Spell.dbc record in an Ascension client, addressable by id.

    `table` is our own dbc_tables.SPELL_DBC. Passing it in is what lets this class hand
    back cells keyed by the column names the generator already uses, and it is also the
    check that the two files really are the same shape: a layout drift shows up as a
    field-count mismatch on construction rather than as silently shifted data.
    """

    def __init__(self, table, client_data=DEFAULT_CLIENT, blob=None):
        self.table = table
        if blob is None:
            blob = self._read_from_client(client_data)
        magic, rc, fc, rs, ss = struct.unpack_from("<4sIIII", blob, 0)
        if magic != b"WDBC":
            raise ValueError("Ascension Spell.dbc is not a WDBC file")
        if fc != len(table.columns):
            raise ValueError(
                f"Ascension Spell.dbc has {fc} fields, our SPELL_DBC has "
                f"{len(table.columns)} -- the layouts have diverged and a transplant "
                f"would shift every cell")
        if rs != fc * 4:
            raise ValueError(f"Ascension Spell.dbc record is {rs}B, expected {fc * 4}B")
        self.count = rc
        self._fmt = "<" + "i" * fc
        self._rs = rs
        self._blob = blob
        self._strings = blob[20 + rc * rs:]
        self._index = {}
        for i in range(rc):
            self._index[struct.unpack_from("<i", blob, 20 + i * rs)[0]] = i

    @staticmethod
    def _read_from_client(client_data):
        if not os.path.isdir(client_data):
            raise FileNotFoundError(f"no Ascension client at {client_data}")
        for _prio, rel in sorted(mpqlib.chain(client_data), reverse=True):
            try:
                m = mpqlib.Mpq.open(os.path.join(client_data, rel))
            except Exception:
                continue
            try:
                if m.has(SPELL_PATH):
                    return m.read(SPELL_PATH)
            except Exception:
                continue
        raise FileNotFoundError(f"{SPELL_PATH} not found in the archive chain at {client_data}")

    def __contains__(self, spell_id):
        return spell_id in self._index

    def ids(self):
        return set(self._index)

    def _str(self, off):
        if off <= 0 or off >= len(self._strings):
            return ""
        end = self._strings.find(b"\0", off)
        return self._strings[off:end].decode("utf8", "replace")

    def raw(self, spell_id):
        i = self._index[spell_id]
        return struct.unpack_from(self._fmt, self._blob, 20 + i * self._rs)

    def cells(self, spell_id):
        """The record as {column_name: value}, strings as text and floats as floats.

        Reinterpreting the int for float columns rather than reading the file twice: the
        record was unpacked as int32 for speed, and a float cell's bits are the same bits.
        """
        row = self.raw(spell_id)
        out = {}
        for i, col in enumerate(self.table.columns):
            kind = self.table.kind(i)
            v = row[i]
            if kind == "s":
                out[col] = self._str(v)
            elif kind == "f":
                out[col] = struct.unpack("<f", struct.pack("<i", v))[0]
            else:
                out[col] = v
        return out

    def name(self, spell_id):
        return self._str(self.raw(spell_id)[self.table.index_of["Name_Lang_enUS"]])
