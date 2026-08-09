#!/usr/bin/env python3
"""Generate the ItemBrowser addon's Lua item database from the live world DB.

    ./itemdb.py                      emit ItemBrowser/Data/* (needs the live world DB, read-only)
    ./itemdb.py --check              re-verify the already-generated files, no writes
    ./itemdb.py --icon-check DIR     probe every icon name against a client's Data/ MPQ chain
    ./itemdb.py --ac-src DIR         cross-check the proficiency table against a core checkout
    ./itemdb.py --dump-rows FILE     write the raw SELECT as TSV for tools/selftest.lua

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
    Filters.lua     everything the auction-house-style filter bar needs that is NOT per row:
                    category and subcategory LABELS, the per-category row counts, the
                    inventory slots each subcategory actually contains, the pooled
                    class/race/skill restrictions, and the weapon/armour proficiency map
    Items_NN.lua    the sharded rows
    Meta.lua        row count, shard count and a content digest -- what the addon prints in
                    /ib status and what you compare when a friend's results look wrong

WHERE THE DATA COMES FROM
-------------------------
Everything per-item comes from acore_world.item_template except the icon: item_template.displayid
indexes ItemDisplayInfo.dbc, whose field 5 is inventoryIcon[0].

The category NAMES are not invented here and are not copied out of ItemTemplate.h's enums
either. They are read from the client's own ItemClass.dbc (field 3, ClassName_lang[enUS]) and
ItemSubClass.dbc (field 10 DisplayName_lang, field 27 VerboseName_lang), which is exactly where
the stock auction house gets the strings in its category dropdowns. VerboseName wins when it
exists, because DisplayName alone is ambiguous -- weapon subclasses 0 and 1 are both "Axe", and
the AH shows "One-Handed Axes" / "Two-Handed Axes". Skill names come from SkillLine.dbc field 3,
which is the same string the client's GetSkillLineInfo() hands back to the addon.

All DBCs are read straight off /srv/wow/data/dbc; none of them is ever written.

Database access is one read-only SELECT path -- which is why --dump-rows lives here rather
than in the test script: the harness needs the same rows and there should be exactly one place
that talks to the database. This tool never writes to any database, and never writes outside
the addon's own Data/ directory except to the file --dump-rows names.

RECORD PACKING
--------------
Seven small fields are packed into ONE Lua number per item rather than seven parallel arrays:

    meta = quality + 16*(invtype + 32*(class + 32*(subclass + 32*(reqlevel
                   + 128*(itemlevel + 512*restrict)))))

Two reasons, both measured against the live table (see FIELD_WIDTHS for the live maxima):
  * ~640 KB smaller on disk, and several fewer 46k-element Lua tables in the client's heap.
  * The UI only ever decodes the ~13 rows it is drawing, and the filter scan pulls the fields
    it needs straight out of the number with two arithmetic ops apiece. Search touches the
    name array only.
The pack uses multiplication, not bit.bor: WoW's LuaBitOp is 32-bit and this record needs 46
bits. Lua numbers are doubles, so integers up to 2^53 are exact -- the largest value this
scheme can produce is ~7.0e13.

`restrict` is the MOST significant field on purpose. It is a 1-based index into a pool of the
distinct (AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank) tuples, and 0 means
"no restriction at all" -- true of 32,567 of the 46,098 rows, whose packed number is therefore
byte-for-byte what it was before the field existed. Only the restricted minority pays the extra
digits.

WHAT "USABLE" MEANS
-------------------
The filter bar's Usable checkbox mirrors the auction house's, which is server-side
AuctionHouseUsablePlayerInfo::PlayerCanUseItem (src/server/game/AuctionHouse/
AuctionHouseSearcher.cpp:663). That function checks, in order: the weapon/armour proficiency
skill implied by class+subclass, AllowableClass, AllowableRace, RequiredSkill/RequiredSkillRank,
RequiredSpell, and RequiredLevel. Everything except RequiredSpell can be evaluated in the
client, so everything except RequiredSpell is shipped; see the addon's Search.lua for what it
does with it.

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
  #11 every (class, subclass) pair that occurs in the rows has a label, no label is empty,
      and no label carries a '|' or a control character -- same reason as #10, these strings
      go straight into dropdown buttons.
  #12 the restriction pool round-trips: index 0 is exactly (-1, -1, 0, 0), the pool holds no
      duplicates, and unpacking every row's index reproduces the four values the DB gave.
  #13 the weapon/armour proficiency table equals the one ItemTemplate.h::GetSkill() builds in
      the pinned core, and every skill id anything references resolves in SkillLine.dbc.
      The core comparison is SKIPPED -- loudly -- when no checkout is at --ac-src, because
      .work/ is gitignored and a fresh clone does not have one.
  #14 the inventory-slot table agrees with BOTH authorities: every id matches the core's
      `enum InventoryType`, and every token names a real INVTYPE_* string in the CLIENT's
      Interface\\FrameXML\\GlobalStrings.lua (read straight out of the MPQ chain). The two
      spell some slots differently -- the core says INVTYPE_SHOULDERS, the client's global is
      INVTYPE_SHOULDER -- so the check knows the one rule that reconciles them and nothing
      else; see check_inventory_types(). Either half is SKIPPED, loudly, when its source is
      absent.
  #15 every row's InventoryType has a slot entry under its (class, subclass), and those
      per-slot counts sum to the subclass's own count. The slot tier of the category tree is
      built from these, so a slot that went missing would silently hide items.
"""

import argparse
import hashlib
import os
import re
import shlex
import struct
import subprocess
import sys
import zlib
from xml.etree import ElementTree

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.join(os.path.dirname(TOOLS_DIR), "ItemBrowser")
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, "..", "..", "..", ".."))

DEFAULT_DBC_DIR = "/srv/wow/data/dbc"
DEFAULT_CLIENT_DATA = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"
DEFAULT_AC_SRC = os.path.join(REPO_ROOT, ".work", "ac-src")
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
    ("quality",   16,    7),   # Quality        0..7
    ("invtype",   32,   28),   # InventoryType  0..28
    ("class",     32,   16),   # class          0..16
    ("subclass",  32,   20),   # subclass       0..20
    ("reqlevel", 128,  100),   # RequiredLevel  0..100
    ("itemlevel", 512,  435),  # ItemLevel      0..435
    ("restrict", 2048,  727),  # index into the restriction pool, 0 = unrestricted
]

# The one tuple that means "anybody, no skill". Rows carrying it get restrict index 0 and are
# never written into the pool, which is 32,567 of the 46,098 rows and keeps their packed
# number identical to what it was before the field existed.
UNRESTRICTED = (-1, -1, 0, 0)


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
    "InventoryType, AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank, name "
    "FROM item_template ORDER BY entry"
)
ITEM_QUERY_COLUMNS = 13

# What --dump-rows writes for tools/selftest.lua. Deliberately a SEPARATE column order from
# ITEM_QUERY: the harness exists to catch a wrong column being written into the addon, and it
# cannot do that if it reads the same tuple in the same order.
ITEM_TRUTH_QUERY = (
    "SELECT entry, class, subclass, Quality, ItemLevel, RequiredLevel, InventoryType, "
    "AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank, requiredspell, name "
    "FROM item_template ORDER BY entry"
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
# category labels: ItemClass.dbc, ItemSubClass.dbc, SkillLine.dbc
# ==========================================================================================
#
# All three are plain all-uint32 WDBCs whose string fields are offsets into the trailing string
# block. Each loader asserts the record shape it expects, for the same reason load_item_icons
# does: a different client build that shifted a column would otherwise ship 46k plausible rows
# labelled with the wrong words.

def read_dbc(path, field_count, record_size):
    """-> (list of tuples, string-resolver). Hard-fails on an unexpected record shape."""
    with open(path, "rb") as fh:
        blob = fh.read()
    magic, rec_count, fields, rec_size, str_size = struct.unpack_from("<4sIIII", blob, 0)
    if magic != b"WDBC":
        raise Fail(f"{path}: not a WDBC file ({magic!r})")
    if len(blob) != 20 + rec_count * rec_size + str_size:
        raise Fail(f"{path}: header/size mismatch")
    if (fields, rec_size) != (field_count, record_size):
        raise Fail(f"{path}: expected {field_count} fields / {record_size} byte records, "
                   f"got {fields} / {rec_size}")
    strings = blob[20 + rec_count * rec_size:]

    def read_string(off):
        if off == 0 or off >= len(strings):
            return ""
        end = strings.index(b"\x00", off)
        return strings[off:end].decode("latin-1")

    records = [struct.unpack_from(f"<{fields}I", blob, 20 + i * rec_size)
               for i in range(rec_count)]
    return records, read_string


def load_class_names(dbc_dir):
    """class id -> label, from ItemClass.dbc field 3 (ClassName_lang[enUS])."""
    # 20 fields: 0 ID, 1 subclass-map, 2 flags, 3..18 ClassName_lang, 19 locale mask.
    records, text = read_dbc(os.path.join(dbc_dir, "ItemClass.dbc"), 20, 80)
    return {rec[0]: text(rec[3]) for rec in records}


def load_subclass_names(dbc_dir):
    """(class, subclass) -> label, from ItemSubClass.dbc.

    44 fields: 0 ClassID, 1 SubClassID, 2..9 proficiency/animation, 10..26 DisplayName_lang,
    27..43 VerboseName_lang. The auction house shows the VERBOSE name where there is one --
    DisplayName calls weapon subclasses 0 and 1 both "Axe", which is useless in a dropdown.
    """
    records, text = read_dbc(os.path.join(dbc_dir, "ItemSubClass.dbc"), 44, 176)
    out = {}
    for rec in records:
        verbose, display = text(rec[27]), text(rec[10])
        out[(rec[0], rec[1])] = verbose or display
    return out


def load_player_bits(dbc_dir):
    """-> ({CLASS TOKEN: class id}, {RACE TOKEN: race id}).

    AllowableClass / AllowableRace are bitmasks over these ids: class N is bit N-1. The tokens
    are the strings the client's own UnitClass()/UnitRace() hand back as their second return --
    ChrClasses.dbc field 55 is literally "WARRIOR", and ChrRaces.dbc field 11 is literally
    "Scourge", which is what UnitRace says for an undead. Keyed upper-case so the addon can
    match without caring about either side's capitalisation.
    """
    classes, class_text = read_dbc(os.path.join(dbc_dir, "ChrClasses.dbc"), 60, 240)
    races, race_text = read_dbc(os.path.join(dbc_dir, "ChrRaces.dbc"), 69, 276)
    class_bits = {class_text(rec[55]).upper(): rec[0] for rec in classes if class_text(rec[55])}
    race_bits = {race_text(rec[11]).upper(): rec[0] for rec in races if race_text(rec[11])}
    for name, table, limit in (("ChrClasses", class_bits, 32), ("ChrRaces", race_bits, 32)):
        if not table:
            raise Fail(f"{name}.dbc yielded no tokens")
        if max(table.values()) > limit:
            raise Fail(f"{name}.dbc has id {max(table.values())}, past bit {limit}")
    return class_bits, race_bits


def load_skill_names(dbc_dir):
    """skill id -> label, from SkillLine.dbc field 3 (DisplayName_lang[enUS]).

    This is the string the client's own GetSkillLineInfo() returns for a line in the player's
    skill list, which is how the addon decides whether the player has a proficiency.
    """
    # 56 fields: 0 ID, 1 category, 2 costs, 3..19 DisplayName_lang, 20..36 Description_lang,
    # 37 spellIcon, 38..54 AlternateVerb_lang, 55 canLink.
    records, text = read_dbc(os.path.join(dbc_dir, "SkillLine.dbc"), 56, 224)
    return {rec[0]: text(rec[3]) for rec in records}


# ==========================================================================================
# weapon / armour proficiency
# ==========================================================================================
#
# Copied VERBATIM from the pinned core, src/server/game/Entities/Item/ItemTemplate.h, the two
# static arrays inside ItemTemplate::GetSkill() -- with the SkillType constants resolved from
# src/server/shared/SharedDefines.h. Same treatment the DK generator gives DBCfmt.h strings:
# the values live here so the tool works without a checkout, and check_proficiency() re-derives
# them from the checkout and fails on any disagreement.
#
# GetSkill() is the FIRST thing PlayerCanUseItem tests, and it is the only part of "usable"
# that a plain reading of the item row cannot give you: nothing in item_template says a mage
# may not wear plate.
WEAPON_SKILLS = [
    44, 172, 45, 46, 54,       # Axes, Two-Handed Axes, Bows, Guns, Maces
    160, 229, 43, 55, 0,       # Two-Handed Maces, Polearms, Swords, Two-Handed Swords, --
    136, 0, 0, 473, 0,         # Staves, --, --, Fist Weapons, --
    173, 176, 253, 226, 228,   # Daggers, Thrown, Assassination, Crossbows, Wands
    356,                       # Fishing
]
ARMOR_SKILLS = [
    0, 415, 414, 413, 293, 0, 433, 0, 0, 0, 0,
    #  Cloth Leather Mail Plate    Shield
]
ITEM_CLASS_WEAPON = 2
ITEM_CLASS_ARMOR = 4


# ==========================================================================================
# inventory slots
# ==========================================================================================
#
# item_template.InventoryType -> the SUFFIX of the FrameXML global that names the slot, so the
# addon draws whatever INVTYPE_HEAD says in the player's own locale rather than an English
# word baked in here. This is the third tier of the category tree, exactly as the stock
# auction house builds it: GetAuctionInvTypes() hands Blizzard_AuctionUI.lua:678 a list of
# global NAMES and it renders _G[name].
#
# There is no DBC for this. The ids are an enum in the core and the strings are constants in
# the client, and the two do not spell every slot the same way, so neither one alone can
# produce this table -- hence a literal here and invariant #14 to check it against both.
INVENTORY_TYPES = {
    1: "HEAD", 2: "NECK", 3: "SHOULDER", 4: "BODY", 5: "CHEST", 6: "WAIST", 7: "LEGS",
    8: "FEET", 9: "WRIST", 10: "HAND", 11: "FINGER", 12: "TRINKET", 13: "WEAPON",
    14: "SHIELD", 15: "RANGED", 16: "CLOAK", 17: "2HWEAPON", 18: "BAG", 19: "TABARD",
    20: "ROBE", 21: "WEAPONMAINHAND", 22: "WEAPONOFFHAND", 23: "HOLDABLE", 24: "AMMO",
    25: "THROWN", 26: "RANGEDRIGHT", 27: "QUIVER", 28: "RELIC",
}

# The ONLY difference the check tolerates between a core enum name and a client global name.
# The core pluralises three body parts (INVTYPE_SHOULDERS / _WRISTS / _HANDS) where the
# client's GlobalStrings.lua is singular. Encoded as an explicit list rather than as a
# "strip a trailing S" rule so that a genuinely new slot cannot slip through by accident.
INVTYPE_SPELLING = {"SHOULDERS": "SHOULDER", "WRISTS": "WRIST", "HANDS": "HAND"}

GLOBALSTRINGS_PATH = "Interface\\FrameXML\\GlobalStrings.lua"


def check_inventory_types(ac_src, client_data):
    """Invariant #14. Returns notes for the log; raises on disagreement."""
    notes = []

    header = os.path.join(ac_src, "src/server/game/Entities/Item/ItemTemplate.h")
    if os.path.isfile(header):
        with open(header, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        match = re.search(r"enum\s+InventoryType[^{]*\{(.*?)\}\s*;", text, re.S)
        if not match:
            raise Fail("could not find `enum InventoryType` in the core checkout")
        core = {}
        for name, value in re.findall(r"\b(INVTYPE_[A-Z0-9_]+)\s*=\s*(\d+)", match.group(1)):
            core[int(value)] = name[len("INVTYPE_"):]
        core.pop(0, None)                      # INVTYPE_NON_EQUIP: not a slot, never labelled
        ours = {i: INVENTORY_TYPES[i] for i in INVENTORY_TYPES}
        translated = {i: INVTYPE_SPELLING.get(n, n) for i, n in core.items()}
        if translated != ours:
            differing = sorted(set(translated) | set(ours))
            detail = ", ".join(f"{i}: core {core.get(i)!r} -> {translated.get(i)!r} "
                               f"vs ours {ours.get(i)!r}"
                               for i in differing if translated.get(i) != ours.get(i))
            raise Fail(f"INVENTORY_TYPES disagrees with the core's enum InventoryType: {detail}")
        notes.append(f"{len(ours)} inventory slots match enum InventoryType in "
                     f"{os.path.relpath(header, ac_src)}")
    else:
        notes.append(None)

    strings = read_client_globalstrings(client_data)
    if strings is None:
        notes.append(None)
    else:
        missing = [f"INVTYPE_{t}" for t in INVENTORY_TYPES.values()
                   if not strings.get("INVTYPE_" + t)]
        if missing:
            raise Fail("the client's GlobalStrings.lua has no string for: " + ", ".join(missing))
        distinct = len({strings["INVTYPE_" + t] for t in INVENTORY_TYPES.values()})
        # Not an error: INVTYPE_RANGED and INVTYPE_RANGEDRIGHT are both "Ranged", CHEST and
        # ROBE are both "Chest", SHIELD and WEAPONOFFHAND are both "Off Hand". The addon
        # GROUPS slots by the string the client gives them, which is why it can afford to.
        notes.append(f"all {len(INVENTORY_TYPES)} INVTYPE_* strings resolve in the client's "
                     f"GlobalStrings.lua ({distinct} distinct labels)")
    return notes


def read_client_globalstrings(client_data):
    """{GLOBAL: string} from the client's own GlobalStrings.lua, or None if unreadable.

    Straight out of the MPQ chain: the file is not on disk in an installed client, and the
    point of the check is to read what THIS client will actually evaluate.
    """
    if not client_data or not os.path.isdir(client_data):
        return None
    text = None
    for path in mpq_chain(client_data):
        try:
            blob = MpqArchive(path).read(GLOBALSTRINGS_PATH)
        except Exception:                                                    # noqa: BLE001
            continue
        if blob:
            text = blob.decode("latin-1")
            break
    if text is None:
        return None
    return {m.group(1): m.group(2)
            for m in re.finditer(r'^([A-Z0-9_]+)\s*=\s*"((?:[^"\\]|\\.)*)"', text, re.M)}


def proficiency_map():
    """(class -> {subclass -> skill id}) for the subclasses that demand a proficiency."""
    out = {}
    for cls, table in ((ITEM_CLASS_WEAPON, WEAPON_SKILLS), (ITEM_CLASS_ARMOR, ARMOR_SKILLS)):
        for subclass, skill in enumerate(table):
            if skill:
                out.setdefault(cls, {})[subclass] = skill
    return out


def _parse_c_array(text, name):
    """The initialiser list of `const static uint32 <name>[...] = { ... };`, as tokens."""
    match = re.search(re.escape(name) + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\}\s*;", text, re.S)
    if not match:
        raise Fail(f"could not find the {name}[] initialiser in the core checkout")
    body = re.sub(r"//.*?$|/\*.*?\*/", "", match.group(1), flags=re.S | re.M)
    return [tok.strip() for tok in body.split(",") if tok.strip()]


def check_proficiency(ac_src):
    """Invariant #13, core half. Returns a note for the log, or raises."""
    header = os.path.join(ac_src, "src/server/game/Entities/Item/ItemTemplate.h")
    shared = os.path.join(ac_src, "src/server/shared/SharedDefines.h")
    if not (os.path.isfile(header) and os.path.isfile(shared)):
        return None
    with open(header, "r", encoding="utf-8", errors="replace") as fh:
        header_text = fh.read()
    with open(shared, "r", encoding="utf-8", errors="replace") as fh:
        shared_text = fh.read()
    skill_ids = {m.group(1): int(m.group(2))
                 for m in re.finditer(r"\b(SKILL_[A-Z0-9_]+)\s*=\s*(\d+)", shared_text)}

    def resolve(tokens, what):
        values = []
        for tok in tokens:
            if tok == "0":
                values.append(0)
            elif tok in skill_ids:
                values.append(skill_ids[tok])
            else:
                raise Fail(f"{what}: {tok!r} is not a SkillType constant in SharedDefines.h")
        return values

    for name, ours in (("item_weapon_skills", WEAPON_SKILLS),
                       ("item_armor_skills", ARMOR_SKILLS)):
        theirs = resolve(_parse_c_array(header_text, name), name)
        if theirs != ours:
            raise Fail(f"{name}[] in the core is {theirs}, this tool has {ours}. "
                       f"Update the literal in itemdb.py and regenerate.")
    return f"proficiency table matches {os.path.relpath(header, ac_src)} in {ac_src}"


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


def render_filters(categories, order, pool, prof, skill_names, class_bits, race_bits, limits):
    """Everything the filter bar needs that is not per-row.

    categories: {class: {"name": str, "count": int,
                         "sub": [(subclass, count, label, [(invtype, count), ...]), ...]}}
    order:      class ids, ascending -- the order the dropdown lists them in
    pool:       [(allowClass, allowRace, reqSkill, reqRank), ...], 1-based in Lua
    limits:     {"reqLevel": int, "itemLevel": int} -- the live maxima, for slider bounds
    """
    out = [BANNER,
           "-- Auction-house-style filter metadata.\n"
           "--\n"
           "-- Category labels come from the CLIENT's ItemClass.dbc / ItemSubClass.dbc, which is\n"
           "-- where the stock auction house gets the strings in its own dropdowns. Only classes\n"
           "-- and subclasses that at least one item actually uses are listed, so the menus never\n"
           "-- offer a category that cannot return a row.\n"
           "--\n"
           "-- Each subcategory carries a fourth field: the inventory slots that subcategory's\n"
           "-- items ACTUALLY occupy, as flat (InventoryType, count) pairs in ascending slot\n"
           "-- order. That is the tree's third tier, the same one the auction house builds from\n"
           "-- GetAuctionInvTypes(). Counted from the rows rather than assumed, so 'Bows' offers\n"
           "-- Ranged and nothing else, and no branch can be opened onto an empty list.\n",
           "ItemBrowserData.categoryOrder = {\n"]
    out.append(wrap([str(c) for c in order], indent="  "))
    out.append("}\n\nItemBrowserData.category = {\n")
    for cls in order:
        info = categories[cls]
        out.append("  [%d] = { name = %s, count = %d, sub = {\n"
                   % (cls, lua_string(info["name"]), info["count"]))
        out.append(wrap(["{%d,%d,%s,{%s}}"
                         % (sub, count, lua_string(label),
                            ",".join("%d,%d" % pair for pair in slots))
                         for sub, count, label, slots in info["sub"]], indent="    "))
        out.append("  } },\n")
    out.append("}\n")

    out.append(
        "\n-- InventoryType -> the SUFFIX of the client global that names the slot; the addon\n"
        "-- shows _G[\"INVTYPE_\" .. token], so the words are the client's and the locale's, not\n"
        "-- this tool's. Ids checked against the core's enum InventoryType and every token\n"
        "-- checked against the client's own GlobalStrings.lua (invariant #14).\n"
        "--\n"
        "-- Several tokens deliberately share a label: INVTYPE_RANGED and INVTYPE_RANGEDRIGHT\n"
        "-- are both \"Ranged\", CHEST and ROBE are both \"Chest\", SHIELD and WEAPONOFFHAND are\n"
        "-- both \"Off Hand\". The tree groups slots by the LABEL, so those collapse into one\n"
        "-- clickable row that filters on all of the ids behind it.\n"
        "ItemBrowserData.slotToken = {\n")
    out.append(wrap(["[%d]=%s" % (inv, lua_string(token))
                     for inv, token in sorted(INVENTORY_TYPES.items())], indent="  "))
    out.append("}\n")

    out.append(
        "\n-- The live maxima, so the level sliders span exactly what the database contains\n"
        "-- rather than a guessed 1..80. reqLevel is above 80 for a handful of internal rows.\n"
        "ItemBrowserData.limits = {\n"
        "  reqLevel = %d,\n"
        "  itemLevel = %d,\n"
        "}\n" % (limits["reqLevel"], limits["itemLevel"]))

    out.append(
        "\n-- Pooled (AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank), four\n"
        "-- numbers per record. A row's packed `restrict` field is a 1-based index into this;\n"
        "-- 0 means the row has no restriction of any kind and never appears here.\n"
        "ItemBrowserData.restrict = {\n")
    out.append(wrap(["%d,%d,%d,%d" % rec for rec in pool], indent="  "))
    out.append("}\n")

    out.append(
        "\n-- class -> subclass -> the proficiency skill Player::CanUseItem demands, from\n"
        "-- ItemTemplate.h::GetSkill(). Nothing in item_template encodes this: it is why a mage\n"
        "-- with Usable ticked does not see plate.\n"
        "ItemBrowserData.profSkill = {\n")
    for cls in sorted(prof):
        pairs = ", ".join("[%d]=%d" % (sub, skill) for sub, skill in sorted(prof[cls].items()))
        out.append("  [%d] = { %s },\n" % (cls, pairs))
    out.append("}\n")

    out.append(
        "\n-- skill id -> SkillLine.dbc's name for it, which is the string the client's own\n"
        "-- GetSkillLineInfo() returns. Matching on the name is what lets the addon ask 'does\n"
        "-- this character have that proficiency' without a server round trip.\n"
        "--\n"
        "-- A value of `false` means item_template asks for a skill line that SkillLine.dbc\n"
        "-- does not contain -- six vanilla leftovers do. Neither the client nor the server can\n"
        "-- give anybody such a skill, so PlayerCanUseItem would reject those items for every\n"
        "-- character, and so does the Usable filter.\n"
        "ItemBrowserData.skillName = {\n")
    out.append(wrap(["[%d]=%s" % (sid, lua_string(name) if name else "false")
                     for sid, name in sorted(skill_names.items())], indent="  "))
    out.append("}\n")

    out.append(
        "\n-- UnitClass()/UnitRace()'s second return value -> the id whose bit AllowableClass\n"
        "-- and AllowableRace set. ChrClasses.dbc field 55 and ChrRaces.dbc field 11 hold\n"
        "-- exactly those strings; upper-cased here so the addon can match either casing.\n"
        "ItemBrowserData.classBit = {\n")
    out.append(wrap(["[%s]=%d" % (lua_string(token), value)
                     for token, value in sorted(class_bits.items())], indent="  "))
    out.append("}\n\nItemBrowserData.raceBit = {\n")
    out.append(wrap(["[%s]=%d" % (lua_string(token), value)
                     for token, value in sorted(race_bits.items())], indent="  "))
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
             '    <Script file="Icons.lua"/>',
             '    <Script file="Filters.lua"/>']
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
    class_names = load_class_names(dbc_dir)
    subclass_names = load_subclass_names(dbc_dir)
    all_skill_names = load_skill_names(dbc_dir)
    class_bits, race_bits = load_player_bits(dbc_dir)
    prof = proficiency_map()

    raw = db.query(ITEM_QUERY)
    if not raw:
        raise Fail("item_template returned no rows -- is the world DB imported?")

    icon_index, icon_list = {}, []
    pool_index, pool = {UNRESTRICTED: 0}, []
    class_rows, subclass_rows, slot_rows = {}, {}, {}
    limits = {"reqLevel": 0, "itemLevel": 0}
    used_skills = set()
    rows = []
    previous_entry = -1
    for cols in raw:
        if len(cols) != ITEM_QUERY_COLUMNS:
            raise Fail(f"expected {ITEM_QUERY_COLUMNS} columns, got {len(cols)}: {cols[:3]}")
        (entry, displayid, quality, ilvl, rlvl, cls, sub, inv,
         allow_class, allow_race, req_skill, req_rank) = (int(c) for c in cols[:12])
        name = cols[12]

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

        # Restriction pool. Ordered by first appearance, which is entry order, which is what
        # keeps the output byte-deterministic (invariant #8).
        tuple_ = (allow_class, allow_race, req_skill, req_rank)
        restrict = pool_index.get(tuple_)
        if restrict is None:
            pool.append(tuple_)
            restrict = pool_index[tuple_] = len(pool)  # 1-based; 0 is UNRESTRICTED
        if req_skill:
            used_skills.add(req_skill)

        class_rows[cls] = class_rows.get(cls, 0) + 1
        subclass_rows[(cls, sub)] = subclass_rows.get((cls, sub), 0) + 1
        slot_rows[(cls, sub, inv)] = slot_rows.get((cls, sub, inv), 0) + 1
        limits["reqLevel"] = max(limits["reqLevel"], rlvl)
        limits["itemLevel"] = max(limits["itemLevel"], ilvl)

        fields = [quality, inv, cls, sub, rlvl, ilvl, restrict]
        meta = pack_meta(fields)
        # --- invariant #2 ------------------------------------------------------------
        if unpack_meta(meta) != fields:
            raise Fail(f"item {entry}: meta pack/unpack round trip failed")
        # --- invariant #12 -----------------------------------------------------------
        got = UNRESTRICTED if restrict == 0 else pool[restrict - 1]
        if got != tuple_:
            raise Fail(f"item {entry}: restriction pool slot {restrict} holds {got}, "
                       f"not {tuple_}")
        rows.append((entry, name, meta, slot))

    categories, order = build_categories(class_names, subclass_names, class_rows, subclass_rows,
                                         slot_rows)
    # --- invariant #13, DBC half -----------------------------------------------------
    # The proficiency skills MUST resolve: a nameless one would be a parse bug, and the addon
    # would silently stop filtering plate away from mages. A nameless RequiredSkill is a
    # different thing -- item_template genuinely asks six items for skill lines 40 and 242,
    # which this client's SkillLine.dbc does not have. Those are emitted as `false`.
    for by_subclass in prof.values():
        for skill in by_subclass.values():
            if not all_skill_names.get(skill):
                raise Fail(f"proficiency skill {skill} has no name in SkillLine.dbc")
            used_skills.add(skill)
    skill_names = {s: all_skill_names.get(s, "") for s in used_skills}

    files = {
        "Icons.lua": render_icons(icon_list),
        "Filters.lua": render_filters(categories, order, pool, prof, skill_names,
                                      class_bits, race_bits, limits),
    }
    chunks = [rows[i:i + shard_rows] for i in range(0, len(rows), shard_rows)]
    shard_names = ["Items_%02d.lua" % n for n in range(1, len(chunks) + 1)]
    for n, (name, chunk) in enumerate(zip(shard_names, chunks), 1):
        files[name] = render_shard(n, len(chunks), chunk)

    # --- invariant #4 ----------------------------------------------------------------
    emitted = sum(len(c) for c in chunks)
    if emitted != len(rows) or len(rows) != len(raw):
        raise Fail(f"row count drift: selected {len(raw)}, built {len(rows)}, emitted {emitted}")

    digest = hashlib.sha256()
    for name in ["Icons.lua", "Filters.lua"] + shard_names:
        digest.update(files[name].encode("utf-8"))
    files["Meta.lua"] = render_meta(len(rows), len(icon_list), shard_names,
                                    digest.hexdigest()[:16])
    files["Data.xml"] = render_data_xml(shard_names)
    return files, rows, icon_list, pool


def build_categories(class_names, subclass_names, class_rows, subclass_rows, slot_rows):
    """Labels + counts for every class/subclass that at least one row uses. Invariants #11, #15.

    A category with no items is not emitted: offering "Permanent" in a dropdown that can only
    ever return nothing is worse than not offering it. Conversely a class/subclass pair that
    the DBCs have never heard of still gets a row -- item_template really does contain
    class 15 subclass 12 and class 12 subclass 8 -- labelled by number rather than dropped,
    because dropping it would make those items unreachable through the category filter.
    """
    def clean(label, what):
        if not label:
            return None
        if "|" in label or any(ord(ch) < 0x20 for ch in label):
            raise Fail(f"{what} label {label!r} carries '|' or a control character")
        return label

    categories, order = {}, sorted(class_rows)
    for cls in order:
        label = clean(class_names.get(cls), f"class {cls}") or ("Class %d" % cls)
        sub = []
        for (c, s), count in sorted(subclass_rows.items()):
            if c != cls:
                continue
            slabel = (clean(subclass_names.get((c, s)), f"subclass {c}/{s}")
                      or ("Subclass %d" % s))
            # --- invariant #15 -------------------------------------------------------
            # Ascending slot id, which is the canonical head-to-relic order the character
            # pane uses, and the order the AH's own third tier comes out in.
            slots = [(inv, n) for (c2, s2, inv), n in sorted(slot_rows.items())
                     if (c2, s2) == (c, s)]
            covered = sum(n for _, n in slots)
            if covered != count:
                raise Fail(f"class {c} subclass {s}: slot counts sum to {covered}, "
                           f"but the subclass holds {count} rows")
            for inv, _ in slots:
                if inv != 0 and inv not in INVENTORY_TYPES:
                    raise Fail(f"class {c} subclass {s}: InventoryType {inv} has no slot token")
            sub.append((s, count, slabel, slots))
        categories[cls] = {"name": label, "count": class_rows[cls], "sub": sub}
    return categories, order


# ==========================================================================================
# post-build checks that need the rendered files
# ==========================================================================================

SPOT_CHECKS = {
    6948:  ("Hearthstone",  1, "INV_Misc_Rune_01"),
    49623: ("Shadowmourne", 5, "inv_axe_113"),
    25:    ("Worn Shortsword", 1, "INV_Sword_04"),
}

# entry -> (class label, subclass label). The subclass strings are the ones only the VERBOSE
# column carries: DisplayName would call both of Shadowmourne's neighbours "Axe".
CATEGORY_SPOT_CHECKS = {
    49623: ("Weapon", "Two-Handed Axes"),      # class 2, subclass 1
    51220: ("Armor", "Plate"),                 # class 4, subclass 4 -- socketed tier epic
    39:    ("Armor", "Cloth"),                 # class 4, subclass 1 -- a plain grey
    2589:  ("Trade Goods", "Cloth"),           # class 7, subclass 5
    6948:  ("Miscellaneous", "Junk"),          # class 15, subclass 0
}

# entry -> (AllowableClass, AllowableRace, RequiredSkill, RequiredSkillRank), as the live table
# has them. Proves the restriction pool is indexed the way the addon will read it.
RESTRICT_SPOT_CHECKS = {
    25:    (-1, -1, 0, 0),                     # unrestricted -> pool index 0
    49623: (260643, 2147483647, 0, 0),         # Shadowmourne: the plate/mail melee classes
    2589:  (32767, -1, 0, 0),                  # Linen Cloth: every class, any race
}


# (class, subclass) -> {InventoryType: rows}, as the live table has them. The slot tier of the
# category tree is generated, so it needs a spot check of its own: "Bows" offering anything but
# Ranged, or offering nothing at all, is a broken tree rather than a wrong label.
SLOT_SPOT_CHECKS = {
    (2, 2): {13: 1, 15: 303, 26: 4},           # Weapon / Bows -> almost entirely INVTYPE_RANGED
    (4, 6): {14: 686},                         # Armor / Shields -> INVTYPE_SHIELD, nothing else
    (16, 1): {0: 35},                          # Glyph / Warrior -> not equippable at all
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


def check_category_spots(rows, files, pool):
    """Invariant #6, filter half: the labels and restrictions a known item resolves to.

    Re-reads what was EMITTED rather than the intermediate dicts, so a bug in render_filters
    is caught as well as a bug in build_categories.
    """
    text = files["Filters.lua"]
    labels, slots = {}, {}
    for block in re.finditer(r"\[(\d+)\] = \{ name = \"([^\"]*)\", count = \d+, sub = \{(.*?)\n  \} \},",
                             text, re.S):
        cls = int(block.group(1))
        labels[cls] = (block.group(2), {})
        body = re.sub(r"\n\s*", "", block.group(3))
        for sub in re.finditer(r"\{(\d+),\d+,\"([^\"]*)\",\{([\d,]*)\}\}", body):
            labels[cls][1][int(sub.group(1))] = sub.group(2)
            numbers = [int(n) for n in sub.group(3).split(",") if n]
            slots[(cls, int(sub.group(1)))] = dict(zip(numbers[0::2], numbers[1::2]))

    for (cls, sub), want in SLOT_SPOT_CHECKS.items():
        got = slots.get((cls, sub))
        if got != want:
            raise Fail(f"slot spot check: class {cls} subclass {sub} emitted {got}, "
                       f"expected {want}")

    by_entry = {r[0]: r for r in rows}
    for entry, (want_class, want_sub) in CATEGORY_SPOT_CHECKS.items():
        row = by_entry.get(entry)
        if row is None:
            raise Fail(f"category spot check: item {entry} missing from the output")
        _, _, cls, sub, _, _, _ = unpack_meta(row[2])
        got = labels.get(cls)
        if not got:
            raise Fail(f"category spot check: class {cls} (item {entry}) has no emitted label")
        if (got[0], got[1].get(sub)) != (want_class, want_sub):
            raise Fail(f"category spot check: item {entry} is {got[0]!r}/"
                       f"{got[1].get(sub)!r}, expected {want_class!r}/{want_sub!r}")

    for entry, want in RESTRICT_SPOT_CHECKS.items():
        row = by_entry.get(entry)
        if row is None:
            raise Fail(f"restriction spot check: item {entry} missing from the output")
        index = unpack_meta(row[2])[6]
        got = UNRESTRICTED if index == 0 else pool[index - 1]
        if got != want:
            raise Fail(f"restriction spot check: item {entry} resolves to {got}, expected {want}")


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
    emitted = (["Icons.lua", "Filters.lua"]
               + sorted(n for n in files if n.startswith("Items_")) + ["Meta.lua"])
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
            self.blob = fh.read()
        blob = self.blob
        base = None
        for off in range(0, len(blob) - 32, 512):
            if blob[off:off + 4] == b"MPQ\x1a":
                base = off
                break
        if base is None:
            raise RuntimeError(f"{path}: no MPQ header")
        (_, _, _, _, block_pow,
         hash_pos, block_pos, hash_size, block_size) = struct.unpack_from("<4sIIHHIIII",
                                                                         blob, base)
        raw = blob[base + hash_pos: base + hash_pos + hash_size * 16]
        self.entries = _mpq_decrypt(raw, _mpq_hash("(hash table)", 3))
        self.size = hash_size
        self.base = base
        self.sector_size = 512 << block_pow
        self.blocks = _mpq_decrypt(blob[base + block_pos: base + block_pos + block_size * 16],
                                   _mpq_hash("(block table)", 3))

    def _block_of(self, archived_name):
        if not self.size:
            return None
        start = _mpq_hash(archived_name, 0) % self.size
        want1 = _mpq_hash(archived_name, 1)
        want2 = _mpq_hash(archived_name, 2)
        for step in range(self.size):
            i = (start + step) % self.size
            name1, name2, _, _, block = struct.unpack_from("<IIHHI", self.entries, i * 16)
            if block == self.HASH_EMPTY:
                return None
            if block != self.HASH_DELETED and name1 == want1 and name2 == want2:
                return block
        return None

    def has(self, archived_name):
        return self._block_of(archived_name) is not None


class MpqArchive(MpqHashTable):
    """...plus reading one out again.

    Only the shapes a 3.3.5a FrameXML file is actually stored in: uncompressed, or zlib per
    sector. Anything else (PKWARE implode, bzip2, encrypted) raises rather than guesses --
    the caller treats a raise as 'this archive does not have it' and moves down the chain.
    """

    FLAG_EXISTS = 0x80000000
    FLAG_SINGLE_UNIT = 0x01000000
    FLAG_ENCRYPTED = 0x00010000
    FLAG_COMPRESSED = 0x00000200
    FLAG_IMPLODED = 0x00000100

    def read(self, archived_name):
        block = self._block_of(archived_name)
        if block is None:
            return None
        offset, csize, fsize, flags = struct.unpack_from("<IIII", self.blocks, block * 16)
        if not flags & self.FLAG_EXISTS:
            return None
        if flags & self.FLAG_ENCRYPTED or flags & self.FLAG_IMPLODED:
            raise RuntimeError(f"{archived_name}: stored encrypted or imploded")
        raw = self.blob[self.base + offset: self.base + offset + csize]

        def inflate(chunk, want):
            if len(chunk) >= want:            # a sector that did not compress is stored raw
                return chunk[:want]
            if chunk[0] != 0x02:
                raise RuntimeError(f"{archived_name}: compression mask 0x{chunk[0]:02x}")
            return zlib.decompress(chunk[1:])

        if flags & self.FLAG_SINGLE_UNIT or fsize <= self.sector_size:
            if flags & self.FLAG_COMPRESSED:
                return inflate(raw, fsize)
            return raw[:fsize]
        sectors = (fsize + self.sector_size - 1) // self.sector_size
        table = struct.unpack_from(f"<{sectors + 1}I", raw, 0)
        out = bytearray()
        for i in range(sectors):
            chunk = raw[table[i]:table[i + 1]]
            want = min(self.sector_size, fsize - len(out))
            out += inflate(chunk, want) if flags & self.FLAG_COMPRESSED else chunk[:want]
        return bytes(out[:fsize])


def mpq_chain(client_data):
    """Every .MPQ under a client's Data/, in the order the client resolves a path in.

    Highest priority first, so the FIRST archive that has a file is the one whose copy the
    game would use. That ordering is not cosmetic: patch-enUS.MPQ and patch-enUS-3.MPQ both
    contain Interface\\FrameXML\\UI.xsd and GlobalStrings.lua, three patch levels apart, and
    reading the older one would check this addon against a client that no longer exists.

    The rule, from how WoW loads archives: patch archives beat base archives, locale archives
    beat generic ones, and a higher patch number beats a lower one. A single-letter suffix
    (patch-Z.MPQ) is a hand-made archive appended after the numbered ones.
    """
    found = []
    for root, _, names in os.walk(client_data):
        for name in names:
            if name.lower().endswith(".mpq"):
                found.append(os.path.join(root, name))

    def rank(path):
        stem = os.path.splitext(os.path.basename(path).lower())[0]
        parts = stem.split("-")
        is_patch = 1 if parts[0] == "patch" else 0
        # A four-letter alphabetic part is a locale code: "enUS", "deDE".
        is_locale = 1 if any(len(p) == 4 and p.isalpha() for p in parts[1:]) else 0
        suffix, last = 0, parts[-1] if len(parts) > 1 else ""
        if last.isdigit():
            suffix = int(last)
        elif len(last) == 1 and last.isalpha():
            suffix = 99
        return (is_patch, is_locale, suffix, stem)

    return sorted(found, key=rank, reverse=True)


def icon_check(client_data, icons, strict):
    archives = mpq_chain(client_data)
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
    ap.add_argument("--client-data", default=DEFAULT_CLIENT_DATA, metavar="DIR",
                    help="client Data/ directory whose GlobalStrings.lua the inventory-slot "
                         f"tokens are checked against (default: {DEFAULT_CLIENT_DATA}; "
                         "skipped if absent)")
    ap.add_argument("--ac-src", default=DEFAULT_AC_SRC, metavar="DIR",
                    help="core checkout to cross-check the proficiency table against "
                         f"(default: {DEFAULT_AC_SRC}; skipped if absent)")
    ap.add_argument("--dump-rows", metavar="FILE",
                    help="write the raw item_template SELECT to FILE as TSV and exit; "
                         "tools/selftest.lua checks the generated database against it")
    args = ap.parse_args()

    try:
        if args.dump_rows:
            rows = Db(args.mysql_cmd).query(ITEM_TRUTH_QUERY)
            with open(args.dump_rows, "w", encoding="utf-8", newline="\n") as fh:
                for cols in rows:
                    fh.write("\t".join(cols) + "\n")
            print(f"   {len(rows):,} rows -> {args.dump_rows}")
            return 0

        print(f"== reading item_template (read-only) and {os.path.basename(args.dbc)}/"
              "{ItemDisplayInfo,ItemClass,ItemSubClass,SkillLine}.dbc")
        # --- invariant #13, core half ------------------------------------------------
        note = check_proficiency(args.ac_src)
        if note:
            print(f"   {note}")
        else:
            print(f"   !! no core checkout at {args.ac_src} -- invariant #13 (the weapon and "
                  "armour proficiency table matches ItemTemplate.h) NOT CHECKED", file=sys.stderr)
        # --- invariant #14 -----------------------------------------------------------
        core_note, client_note = check_inventory_types(args.ac_src, args.client_data)
        if core_note:
            print(f"   {core_note}")
        else:
            print(f"   !! no core checkout at {args.ac_src} -- invariant #14 (slot ids match "
                  "enum InventoryType) NOT CHECKED", file=sys.stderr)
        if client_note:
            print(f"   {client_note}")
        else:
            print(f"   !! no readable client at {args.client_data} -- invariant #14 (every slot "
                  "token names a string in the client's GlobalStrings.lua) NOT CHECKED",
                  file=sys.stderr)

        files, rows, icons, pool = build(Db(args.mysql_cmd), args.dbc, args.shard_rows)
        check_spots(rows, icons)
        check_category_spots(rows, files, pool)
        check_data_xml(files)
        check_sizes(files, args.max_file_bytes)
        total = sum(len(t.encode("utf-8")) for t in files.values())
        print(f"   {len(rows):,} items, {len(icons):,} distinct icons, "
              f"{len(pool):,} distinct restrictions, {len(files)} files, "
              f"{total:,} bytes total")

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
    # ValueError is in the list because pack_meta() raises it when a field outgrows its width
    # -- invariant #2's tripwire. That is a normal, expected failure with a useful message
    # ("widen FIELD_WIDTHS"), not a bug to print a traceback for.
    except (Fail, RuntimeError, OSError, ValueError) as exc:
        print(f"itemdb.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
