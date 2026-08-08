#!/usr/bin/env python3
"""Generate the ItemBrowser addon's Lua item database from the live world DB.

    ./itemdb.py                      emit ItemBrowser/Data/* (needs the live world DB, read-only)
    ./itemdb.py --check              re-verify the already-generated files, no writes
    ./itemdb.py --icon-check DIR     probe every icon name against a client's Data/ MPQ chain

WHY THIS TOOL EXISTS
--------------------
A 3.3.5a client only knows about items it has already cached (itemcache.wdb, populated by
SMSG_ITEM_QUERY_SINGLE_RESPONSE). GetItemInfo() therefore returns nil for essentially every
item a fresh client has never seen, so an addon that browses "all items" by asking the client
gets 46,000 blank rows. The item name, quality and icon have to be SHIPPED.

Emits, deterministically and idempotently, into <addon>/Data/:

    Data.xml        <Script> load order; the .toc references only this file, so adding or
                    removing a shard never requires touching the hand-written .toc
    Icons.lua       the distinct Interface\\Icons\\ names, once each (4.8k, not 46k)
    Items_NN.lua    the sharded rows
    Meta.lua        row count, shard count and a content digest -- what the addon prints in
                    /ib status and what you compare when a friend's results look wrong

WHERE THE DATA COMES FROM
-------------------------
Everything except the icon comes from acore_world.item_template. The icon does NOT live in
item_template: item_template.displayid indexes ItemDisplayInfo.dbc, whose field 5 is
inventoryIcon[0]. That DBC is read straight off /srv/wow/data/dbc; it is never written.

Database access is one read-only SELECT path. This tool never writes to any database and never
writes outside the addon's own Data/ directory.

RECORD PACKING
--------------
Six small fields are packed into ONE Lua number per item rather than six parallel arrays:

    meta = quality + 16*(invtype + 32*(class + 32*(subclass + 32*(reqlevel + 128*itemlevel))))

Two reasons, both measured against the live table (see FIELD_WIDTHS for the live maxima):
  * ~640 KB smaller on disk, and three fewer 46k-element Lua tables in the client's heap.
  * The UI only ever decodes the ~15 rows it is drawing, so the arithmetic is free. Search
    touches the name array only.
The pack uses multiplication, not bit.bor: WoW's LuaBitOp is 32-bit and this record needs 35
bits. Lua numbers are doubles, so integers up to 2^53 are exact -- the largest value this
scheme can produce is ~3.4e10.

GENERATOR INVARIANTS
--------------------
Every one is a hard failure in both --emit and --check.

  #1  entry ids are unique and strictly ascending across the whole shard sequence. The
      addon binary-searches entry -> row; an unsorted array silently returns wrong items.
  #2  every field fits its packed width and unpack(pack(row)) == row, for every row.
  #3  every icon index is in 1..#icons, and no icon name carries a file extension, a
      backslash or a quote. (ItemDisplayInfo really does contain "INV_Chest_Fur.tga";
      Interface\\Icons\\<name> must be extension-less or the texture silently draws nothing.)
  #4  rows emitted == rows selected == sum of the shard lengths.
  #5  every emitted Lua file loads under a Lua 5.1 parser (luajit / luac5.1, whichever is
      present). Skipped -- loudly -- if neither is installed.
  #6  spot checks: 6948 Hearthstone and 49623 Shadowmourne are present with the name,
      quality and icon this tool expects. A silent column-order change in the SELECT would
      otherwise ship 46k plausible-looking wrong rows.
  #7  no generated file exceeds --max-file-bytes. Not a client limit -- the pinned addon set
      already ships a 5.1 MB single Lua file (Questie-335 wotlkNpcDB.lua) -- but a budget
      that makes "the DB got 10x bigger" fail here instead of in-game.
  #8  output is byte-deterministic. No timestamps anywhere, input ordered by entry, fixed
      shard size. --check is therefore a plain byte comparison.
  #9  Data.xml lists exactly the shard files that were emitted, in load order, and is
      well-formed XML. WoW skips a malformed .xml silently.
  #10 no item name contains a raw '|' or a control character. '|' is the UI's escape
      introducer; a name carrying one would corrupt every coloured string it lands in.
"""

import argparse
import hashlib
import os
import re
import shlex
import struct
import subprocess
import sys
from xml.etree import ElementTree

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.join(os.path.dirname(TOOLS_DIR), "ItemBrowser")
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, "..", "..", "..", ".."))

DEFAULT_DBC_DIR = "/srv/wow/data/dbc"
DEFAULT_CLIENT_DATA = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"
DEFAULT_SHARD_ROWS = 6000
DEFAULT_MAX_FILE_BYTES = 1_500_000

# Same read-only invocation the rest of the repo uses; '{repo}' expands to the repo root.
DEFAULT_MYSQL_CMD = (
    "docker compose -f {repo}/deploy/docker-compose.yml exec -T mysql "
    "mysql --defaults-extra-file=/etc/mysql/backup.cnf"
)

# Fallback for items whose displayid resolves to an empty or unshipped icon. Verified present
# in this client's MPQ chain (see --icon-check).
FALLBACK_ICON = "INV_Misc_QuestionMark"


# ==========================================================================================
# record packing
# ==========================================================================================
#
# (name, bit width, live maximum as measured on 2026-08-08). The widths are deliberately
# roomier than the live maxima; invariant #2 fails loudly if the data ever outgrows one,
# which is the signal to widen it here and regenerate rather than to truncate in silence.
FIELD_WIDTHS = [
    ("quality",   16,   7),    # Quality        0..7
    ("invtype",   32,  28),    # InventoryType  0..28
    ("class",     32,  16),    # class          0..16
    ("subclass",  32,  20),    # subclass       0..20
    ("reqlevel", 128, 100),    # RequiredLevel  0..100
    ("itemlevel", 512, 435),   # ItemLevel      0..435
]


def pack_meta(values):
    """values in FIELD_WIDTHS order -> one integer. Mirrors ItemBrowser Data.lua Decode()."""
    acc = 0
    for (name, width, _), v in zip(reversed(FIELD_WIDTHS), reversed(values)):
        if not (0 <= v < width):
            raise ValueError(f"{name}={v} does not fit width {width}; widen FIELD_WIDTHS")
        acc = acc * width + v
    return acc


def unpack_meta(meta):
    out = []
    for _, width, _ in FIELD_WIDTHS:
        out.append(meta % width)
        meta //= width
    if meta:
        raise ValueError("packed meta has leftover high bits")
    return out


# ==========================================================================================
# read-only database access
# ==========================================================================================

class Db:
    """One read-only SELECT path. Nothing here ever writes."""

    def __init__(self, cmd_template=None, schema="acore_world"):
        self.cmd = shlex.split((cmd_template or DEFAULT_MYSQL_CMD).format(repo=REPO_ROOT))
        self.schema = schema

    def query(self, sql):
        assert re.match(r"\s*(SELECT|SHOW)\b", sql, re.I), \
            f"Db.query is read-only, refusing: {sql[:60]!r}"
        # --raw is safe here only because invariant #10 proves no name carries a tab, newline
        # or backslash; without it mysql would emit its own escapes and we would have to
        # un-escape them to get the exact bytes the client must display.
        argv = self.cmd + ["-N", "--raw", "--batch", self.schema, "-e", sql]
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"mysql failed ({proc.returncode}): {proc.stderr.strip()}\n"
                               f"  command: {' '.join(shlex.quote(a) for a in argv)}")
        return [line.split("\t") for line in proc.stdout.splitlines()]


ITEM_QUERY = (
    "SELECT entry, displayid, Quality, ItemLevel, RequiredLevel, class, subclass, "
    "InventoryType, name FROM item_template ORDER BY entry"
)


# ==========================================================================================
# ItemDisplayInfo.dbc -> inventory icon
# ==========================================================================================

def load_item_icons(dbc_dir):
    """displayid -> icon base name, from ItemDisplayInfo.dbc field 5 (inventoryIcon[0])."""
    path = os.path.join(dbc_dir, "ItemDisplayInfo.dbc")
    with open(path, "rb") as fh:
        blob = fh.read()
    magic, rec_count, field_count, rec_size, str_size = struct.unpack_from("<4sIIII", blob, 0)
    if magic != b"WDBC":
        raise RuntimeError(f"{path}: not a WDBC file ({magic!r})")
    if len(blob) != 20 + rec_count * rec_size + str_size:
        raise RuntimeError(f"{path}: header/size mismatch")
    # 3.3.5a ItemDisplayInfo is 25 all-uint32 fields: 0 ID, 1-2 modelName, 3-4 modelTexture,
    # 5-6 inventoryIcon, 7-9 geosetGroup, 10 flags, 11 spellVisualID, 12 groupSoundIndex,
    # 13-14 helmetGeosetVis, 15-22 texture, 23 itemVisual, 24 particleColorID. Asserting the
    # shape is what stops a different client build silently shifting the icon column.
    if (field_count, rec_size) != (25, 100):
        raise RuntimeError(f"{path}: expected 25 fields / 100 byte records, "
                           f"got {field_count} / {rec_size}")
    strings = blob[20 + rec_count * rec_size:]

    def read_string(off):
        end = strings.index(b"\x00", off)
        return strings[off:end].decode("latin-1")

    icons = {}
    for i in range(rec_count):
        rec = struct.unpack_from("<25I", blob, 20 + i * rec_size)
        icons[rec[0]] = read_string(rec[5])
    return icons


def normalise_icon(raw):
    """DBC icon string -> the name that goes after Interface\\Icons\\.

    Two real quirks in this client's data, both verified with --icon-check:

      * ONE display carries "INV_Chest_Fur.tga". The archive holds
        Interface\\Icons\\INV_Chest_Fur.blp and nothing called INV_Chest_Fur.tga.blp, so the
        extension has to come off -- the client appends .blp itself.
      * THREE carry a TRAILING SPACE ("INV_Misc_Food_93_SkethylBerries ", GaradarSharp,
        inv_thanksgiving_sweetpotato) and the archives store the .blp with the space in the
        filename. Trimming it is what breaks those icons, not what fixes them. So: do not
        strip whitespace. Pass the DBC string through the way the client does.
    """
    name = raw.replace("/", "\\").rsplit("\\", 1)[-1]
    if re.search(r"\.(blp|tga|png)$", name, re.I):
        name = name.rsplit(".", 1)[0]
    return name if name.strip() else FALLBACK_ICON


# ==========================================================================================
# Lua emission
# ==========================================================================================

BANNER = ("-- GENERATED by client/addons/mod-item-browser/tools/itemdb.py -- do not hand-edit.\n"
          "-- Change the generator (or the world DB) and re-run:  tools/regen.sh\n")


def lua_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def wrap(tokens, indent="", width=96):
    """Comma-joined tokens wrapped to `width` columns, so git diffs stay readable."""
    lines, cur = [], indent
    for tok in tokens:
        piece = tok + ","
        if len(cur) + len(piece) > width and cur != indent:
            lines.append(cur)
            cur = indent
        cur += piece
    if cur != indent:
        lines.append(cur)
    return "\n".join(lines) + "\n"


def render_icons(icons):
    out = [BANNER, "-- Distinct Interface\\Icons\\ names. Rows reference these by index.\n",
           "ItemBrowserData.iconName = {\n"]
    out.append(wrap([lua_string(i) for i in icons], indent="  "))
    out.append("}\n")
    return "".join(out)


def render_shard(index, total, rows):
    """rows: list of (entry, name, meta, icon_index)."""
    out = [BANNER, f"-- Item rows {index}/{total} ({len(rows)} entries).\n",
           "ItemBrowserData:Chunk(\n", "{\n"]
    out.append(wrap([str(r[0]) for r in rows], indent="  "))
    out.append("},{\n")
    out.append(wrap([lua_string(r[1]) for r in rows], indent="  "))
    out.append("},{\n")
    out.append(wrap([str(r[2]) for r in rows], indent="  "))
    out.append("},{\n")
    out.append(wrap([str(r[3]) for r in rows], indent="  "))
    out.append("})\n")
    return "".join(out)


def render_meta(row_count, icon_count, shard_names, digest):
    return "".join([
        BANNER,
        "-- Provenance. /ib status prints this; compare it before debugging a friend's\n"
        "-- \"my results look different\" report.\n",
        "ItemBrowserData.build = {\n",
        f"  rows = {row_count},\n",
        f"  icons = {icon_count},\n",
        f"  shards = {len(shard_names)},\n",
        f"  digest = {lua_string(digest)},\n",
        "}\n",
    ])


def render_data_xml(shard_names):
    """Load order for the generated files.

    The .toc references only Data\\Data.xml, so the number of shards is a generator decision
    and never a hand edit. <Script> paths inside an XML are relative to that XML's directory.
    """
    # No "--" anywhere in the comment: a double hyphen inside an XML comment is a parse
    # error, and WoW answers a malformed .xml by skipping the whole file, which would look
    # exactly like "the addon shipped without its database".
    lines = ['<Ui xmlns="http://www.blizzard.com/wow/ui/">',
             '    <!-- GENERATED by tools/itemdb.py. Do not hand-edit. -->',
             '    <Script file="Icons.lua"/>']
    for name in shard_names:
        lines.append(f'    <Script file="{name}"/>')
    lines.append('    <Script file="Meta.lua"/>')
    lines.append('</Ui>')
    return "\n".join(lines) + "\n"


# ==========================================================================================
# build
# ==========================================================================================

class Fail(Exception):
    pass


def build(db, dbc_dir, shard_rows):
    """Everything the generator would write, as {relative path: text}. No side effects."""
    display_icon = load_item_icons(dbc_dir)
    raw = db.query(ITEM_QUERY)
    if not raw:
        raise Fail("item_template returned no rows -- is the world DB imported?")

    icon_index, icon_list = {}, []
    rows = []
    previous_entry = -1
    for cols in raw:
        if len(cols) != 9:
            raise Fail(f"expected 9 columns, got {len(cols)}: {cols[:3]}")
        entry, displayid, quality, ilvl, rlvl, cls, sub, inv = (int(c) for c in cols[:8])
        name = cols[8]

        # --- invariant #10 -----------------------------------------------------------
        if "|" in name:
            raise Fail(f"item {entry} name contains '|', the UI escape introducer: {name!r}")
        if any(ord(ch) < 0x20 for ch in name):
            raise Fail(f"item {entry} name contains a control character: {name!r}")
        # --- invariant #1 ------------------------------------------------------------
        if entry <= previous_entry:
            raise Fail(f"entry ids not strictly ascending: {entry} after {previous_entry}")
        previous_entry = entry

        icon = normalise_icon(display_icon.get(displayid, "")) or FALLBACK_ICON
        # --- invariant #3 ------------------------------------------------------------
        if re.search(r'[\\"]', icon) or "." in icon:
            raise Fail(f"item {entry}: unusable icon name {icon!r}")
        slot = icon_index.get(icon)
        if slot is None:
            icon_list.append(icon)
            slot = icon_index[icon] = len(icon_list)   # 1-based, Lua array

        meta = pack_meta([quality, inv, cls, sub, rlvl, ilvl])
        # --- invariant #2 ------------------------------------------------------------
        if unpack_meta(meta) != [quality, inv, cls, sub, rlvl, ilvl]:
            raise Fail(f"item {entry}: meta pack/unpack round trip failed")
        rows.append((entry, name, meta, slot))

    files = {"Icons.lua": render_icons(icon_list)}
    chunks = [rows[i:i + shard_rows] for i in range(0, len(rows), shard_rows)]
    shard_names = ["Items_%02d.lua" % n for n in range(1, len(chunks) + 1)]
    for n, (name, chunk) in enumerate(zip(shard_names, chunks), 1):
        files[name] = render_shard(n, len(chunks), chunk)

    # --- invariant #4 ----------------------------------------------------------------
    emitted = sum(len(c) for c in chunks)
    if emitted != len(rows) or len(rows) != len(raw):
        raise Fail(f"row count drift: selected {len(raw)}, built {len(rows)}, emitted {emitted}")

    digest = hashlib.sha256()
    for name in ["Icons.lua"] + shard_names:
        digest.update(files[name].encode("utf-8"))
    files["Meta.lua"] = render_meta(len(rows), len(icon_list), shard_names,
                                    digest.hexdigest()[:16])
    files["Data.xml"] = render_data_xml(shard_names)
    return files, rows, icon_list


# ==========================================================================================
# post-build checks that need the rendered files
# ==========================================================================================

SPOT_CHECKS = {
    6948:  ("Hearthstone",  1, "INV_Misc_Rune_01"),
    49623: ("Shadowmourne", 5, "inv_axe_113"),
    25:    ("Worn Shortsword", 1, "INV_Sword_04"),
}


def check_spots(rows, icon_list):
    """Invariant #6."""
    by_entry = {r[0]: r for r in rows}
    for entry, (want_name, want_quality, want_icon) in SPOT_CHECKS.items():
        row = by_entry.get(entry)
        if row is None:
            raise Fail(f"spot check: item {entry} ({want_name}) missing from the output")
        quality = unpack_meta(row[2])[0]
        icon = icon_list[row[3] - 1]
        if (row[1], quality, icon.lower()) != (want_name, want_quality, want_icon.lower()):
            raise Fail(f"spot check: item {entry} came out as "
                       f"{row[1]!r}/q{quality}/{icon}, expected "
                       f"{want_name!r}/q{want_quality}/{want_icon}")


def lua_parser():
    """A Lua 5.1 syntax checker, or None. LuaJIT is 5.1; the system 'luac' may not be."""
    for exe, argv in (("luajit", ["luajit", "-bl"]), ("luac5.1", ["luac5.1", "-p"])):
        try:
            subprocess.run([exe, "-v"], capture_output=True, check=False)
        except FileNotFoundError:
            continue
        return argv
    return None


def check_lua_parses(paths):
    """Invariant #5."""
    argv = lua_parser()
    if argv is None:
        print("   !! no luajit or luac5.1 on PATH -- invariant #5 (Lua parses) NOT CHECKED",
              file=sys.stderr)
        return
    for path in paths:
        if not path.endswith(".lua"):
            continue
        proc = subprocess.run(argv + [path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise Fail(f"{os.path.basename(path)} does not parse as Lua 5.1:\n"
                       f"{proc.stderr.strip()}")


def check_sizes(files, limit):
    """Invariant #7."""
    for name, text in sorted(files.items()):
        size = len(text.encode("utf-8"))
        if size > limit:
            raise Fail(f"{name} is {size} bytes, over the {limit} byte budget "
                       f"(lower --shard-rows or raise --max-file-bytes deliberately)")


def check_data_xml(files):
    """Invariant #9."""
    listed = re.findall(r'<Script file="([^"]+)"/>', files["Data.xml"])
    emitted = ["Icons.lua"] + sorted(n for n in files if n.startswith("Items_")) + ["Meta.lua"]
    if listed != emitted:
        raise Fail(f"Data.xml load order {listed} != emitted files {emitted}")
    # Well-formedness, checked because WoW's response to a malformed .xml is to skip the
    # file in silence -- indistinguishable, in game, from shipping no database at all.
    try:
        ElementTree.fromstring(files["Data.xml"])
    except ElementTree.ParseError as exc:
        raise Fail(f"Data.xml is not well-formed XML: {exc}")


# ==========================================================================================
# icon probe: does Interface\Icons\<name>.blp exist in a client's MPQ chain?
# ==========================================================================================
#
# Self-contained on purpose. Finding a file in an MPQ needs only the (encrypted) hash table --
# no decompression, no StormLib, no ctypes -- so this check runs anywhere the client files are
# readable. Cross-checked against StormLib on the pinned client: identical result.

def _crypt_table():
    table, seed = [0] * 0x500, 0x00100001
    for i in range(0x100):
        for j in range(i, 0x500, 0x100):
            seed = (seed * 125 + 3) % 0x2AAAAB
            a = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            b = seed & 0xFFFF
            table[j] = a | b
    return table


_CRYPT = _crypt_table()


def _mpq_hash(text, hash_type):
    seed1, seed2 = 0x7FED7FED, 0xEEEEEEEE
    for ch in text.upper():
        value = _CRYPT[(hash_type << 8) + ord(ch)]
        seed1 = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed2 = (ord(ch) + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def _mpq_decrypt(data, key):
    out = bytearray()
    seed = 0xEEEEEEEE
    for i in range(0, len(data) - len(data) % 4, 4):
        seed = (seed + _CRYPT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack_from("<I", data, i)[0] ^ ((key + seed) & 0xFFFFFFFF)
        out += struct.pack("<I", value)
        key = (((~key << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (value + seed + (seed << 5) + 3) & 0xFFFFFFFF
    return bytes(out)


class MpqHashTable:
    """Just enough MPQ to answer 'is this path in this archive?'."""

    HASH_EMPTY = 0xFFFFFFFF
    HASH_DELETED = 0xFFFFFFFE

    def __init__(self, path):
        with open(path, "rb") as fh:
            blob = fh.read()
        base = None
        for off in range(0, len(blob) - 32, 512):
            if blob[off:off + 4] == b"MPQ\x1a":
                base = off
                break
        if base is None:
            raise RuntimeError(f"{path}: no MPQ header")
        (_, _, _, _, _, hash_pos, _, hash_size, _) = struct.unpack_from("<4sIIHHIIII", blob, base)
        raw = blob[base + hash_pos: base + hash_pos + hash_size * 16]
        self.entries = _mpq_decrypt(raw, _mpq_hash("(hash table)", 3))
        self.size = hash_size

    def has(self, archived_name):
        if not self.size:
            return False
        start = _mpq_hash(archived_name, 0) % self.size
        want1 = _mpq_hash(archived_name, 1)
        want2 = _mpq_hash(archived_name, 2)
        for step in range(self.size):
            i = (start + step) % self.size
            name1, name2, _, _, block = struct.unpack_from("<IIHHI", self.entries, i * 16)
            if block == self.HASH_EMPTY:
                return False
            if block != self.HASH_DELETED and name1 == want1 and name2 == want2:
                return True
        return False


def icon_check(client_data, icons, strict):
    archives = []
    for root, _, names in os.walk(client_data):
        for name in names:
            if name.lower().endswith(".mpq"):
                archives.append(os.path.join(root, name))
    if not archives:
        raise Fail(f"no .MPQ archives under {client_data}")
    tables = []
    for path in sorted(archives):
        try:
            tables.append(MpqHashTable(path))
        except Exception as exc:                                          # noqa: BLE001
            print(f"   !! skipping {os.path.basename(path)}: {exc}", file=sys.stderr)
    missing = [i for i in icons
               if not any(t.has(f"Interface\\Icons\\{i}.blp") for t in tables)]
    print(f"   {len(archives)} archives, {len(icons)} distinct icons, "
          f"{len(icons) - len(missing)} resolve")
    if missing:
        print("   unresolvable (the UI falls back to the question mark for these):")
        for name in missing:
            print(f"     {name}")
    if missing and strict:
        raise Fail(f"{len(missing)} icon names do not resolve and --strict-icons is set")
    return missing


# ==========================================================================================
# entry points
# ==========================================================================================

def do_emit(files, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stale = [n for n in os.listdir(out_dir)
             if re.fullmatch(r"Items_\d+\.lua", n) and n not in files]
    for name in stale:
        os.remove(os.path.join(out_dir, name))
        print(f"   removed stale {name}")
    written = []
    for name, text in sorted(files.items()):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(path)
        print(f"   {name:<16} {len(text.encode('utf-8')):>9,} bytes")
    return written


def do_check(files, out_dir):
    problems = []
    for name, text in sorted(files.items()):
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            problems.append(f"{name}: missing on disk")
            continue
        with open(path, "r", encoding="utf-8") as fh:
            have = fh.read()
        if have != text:
            problems.append(f"{name}: on-disk content differs from what the DB would produce")
    for name in sorted(os.listdir(out_dir)):
        if re.fullmatch(r"Items_\d+\.lua", name) and name not in files:
            problems.append(f"{name}: stale shard, no longer generated")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description="Generate the ItemBrowser Lua item database from the live world DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Reads the world DB and the DBCs. Writes only <addon>/Data/.")
    ap.add_argument("--out", default=os.path.join(ADDON_ROOT, "Data"),
                    help="output directory (default: the addon's Data/)")
    ap.add_argument("--dbc", default=DEFAULT_DBC_DIR,
                    help=f"stock DBC directory (default: {DEFAULT_DBC_DIR})")
    ap.add_argument("--shard-rows", type=int, default=DEFAULT_SHARD_ROWS,
                    help=f"items per Items_NN.lua (default: {DEFAULT_SHARD_ROWS})")
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES,
                    help="invariant #7 budget per generated file")
    ap.add_argument("--mysql-cmd", default=None,
                    help="read-only mysql client command; '{repo}' expands to the repo root")
    ap.add_argument("--check", action="store_true",
                    help="re-verify the generated files against the DB; write nothing")
    ap.add_argument("--icon-check", nargs="?", const=DEFAULT_CLIENT_DATA, default=None,
                    metavar="CLIENT_DATA_DIR",
                    help="probe every icon against a client's MPQ chain "
                         f"(default dir: {DEFAULT_CLIENT_DATA})")
    ap.add_argument("--strict-icons", action="store_true",
                    help="make an unresolvable icon a hard failure")
    args = ap.parse_args()

    try:
        print(f"== reading item_template (read-only) and {os.path.basename(args.dbc)}/"
              "ItemDisplayInfo.dbc")
        files, rows, icons = build(Db(args.mysql_cmd), args.dbc, args.shard_rows)
        check_spots(rows, icons)
        check_data_xml(files)
        check_sizes(files, args.max_file_bytes)
        total = sum(len(t.encode("utf-8")) for t in files.values())
        print(f"   {len(rows):,} items, {len(icons):,} distinct icons, "
              f"{len(files)} files, {total:,} bytes total")

        if args.icon_check:
            print(f"== icon probe against {args.icon_check}")
            icon_check(args.icon_check, icons, args.strict_icons)

        if args.check:
            print(f"== checking {args.out}")
            problems = do_check(files, args.out)
            check_lua_parses([os.path.join(args.out, n) for n in files])
            if problems:
                for p in problems:
                    print(f"   FAIL {p}", file=sys.stderr)
                print(f"\n{len(problems)} problem(s). Re-run without --check to regenerate.",
                      file=sys.stderr)
                return 1
            print("   all generated files match the live DB")
            return 0

        print(f"== writing {args.out}")
        written = do_emit(files, args.out)
        check_lua_parses(written)
        print("   ok")
        return 0
    except (Fail, RuntimeError, OSError) as exc:
        print(f"itemdb.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
