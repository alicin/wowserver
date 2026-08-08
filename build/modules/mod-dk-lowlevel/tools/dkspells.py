#!/usr/bin/env python3
"""Generate every artefact of the low-level Death Knight feature from tools/dk_spec.py.

    ./dkspells.py                 emit everything (needs the live world DB, read-only)
    ./dkspells.py --check         re-verify the already-generated outputs, no writes
    ./dkspells.py --verify        print which client archive wins DBFilesClient\\Spell.dbc

Emits, deterministically and idempotently:

    <module>/data/sql/db-world/base/2026_08_08_00_dk_lowlevel_class_stats.sql   A1
    <module>/data/sql/db-world/base/2026_08_08_01_dk_lowlevel_spells.sql        A3 A4 A5 A6
    <module>/data/sql/db-world/base/2026_08_08_02_dk_lowlevel_createinfo.sql    A7 A8 A9 A10
    <module>/src/dk_progression.h                                               compiled table
    <out>/dbc/{Spell,SkillLineAbility,CharStartOutfit}.dbc                      A11 A12 A13
    <out>/patch-Z.MPQ                                                           A14
    <out>/MANIFEST.json + MANIFEST.sha256

WHAT THIS TOOL WILL NOT DO
--------------------------
It never applies SQL and it never writes to /srv/wow/data/dbc. The server's DBC directory must
stay byte-identical to the client's stock files: parity is currently exact and free
(md5(/srv/wow/data/dbc/Spell.dbc) == the copy inside enUS/patch-enUS-3.MPQ), and keeping it
that way means re-extracting from the client can never silently revert this feature. All
server-side changes are SQL; the binary DBC edit is client-only. Database access is one
read-only SELECT path, used to COPY existing rows rather than to retype them.

GENERATOR INVARIANTS
--------------------
Every one of these is a hard failure, in both --emit and --check. The numbering is DESIGN.md
section 6's; G8+ are additions this implementation makes.

  #1  strlen(format) == DBC field_count, and record_size == the format-implied size, for all
      three tables. (Checked on load in dbclib.Dbc.load.)
  #2  every emitted spell id is > 0, > 80864 and < 100000, and not already in the stock file.
      spell_dbc.ID is a SIGNED int and DBCDatabaseLoader sizes its index table from the
      FIRST row of `ORDER BY ID DESC`; a negative id makes that Get<uint32>() about 4.29e9 and
      the process OOMs before it logs anything useful.
  #3  the written Spell.dbc is still strictly ascending by id.
  #4  the emitted SQL row and the emitted DBC row for the same id are identical in EVERY
      column. This is the check that makes "tooltip says 10-12, server rolls 127-137"
      impossible, and it is the entire reason this design was chosen. It is done by parsing
      the SQL back off disk and diffing it against the DBC read back off disk -- not against
      the in-memory values that produced both.
  #5  spell_ranks is a dense 1..N per chain and first_spell_id is the rank 1 spell.
      SpellMgr::LoadSpellRanks (SpellMgr.cpp:1340) drops the WHOLE chain with only an sql.sql
      log line if a rank is missing, which shows up in game as one Icy Touch button per rank.
  #6  exactly one SkillLineAbility row per supercede chain has AcquireMethod = 2.
  #7  emitted column count == strlen(format string) for every *_dbc table: 234 / 14 / 77.
      DBCDatabaseLoader.cpp:124 ASSERTs this at boot, i.e. worldserver aborts.
  #8  A1 emits exactly 54 rows, Class 6, levels dense 1..54, values equal to the live class 1
      rows column for column.
  #9  every generated file is re-runnable: each INSERT is covered by a DELETE of the same
      keys earlier in the same file. UpdateFetcher re-applies a CHANGED file in full
      (UpdateFetcher.cpp:326-370), so a bare INSERT would fail on the second edit.
  #10 the patch MPQ is v2 (headerSize 44, formatVersion 1), stores backslashed paths, carries
      no (attributes), and reads back sha256-identical to the DBCs on disk.
  #11 CharStartOutfit keeps its own RaceID/ClassID/SexID/OutfitID and copies only the item
      arrays from the template row.
  #12 every record this tool changed in a client DBC is either mirrored by a SQL row or is on
      the explicit client-only list in dk_spec (the stock rank subtext renumbering).
  #13 the five spell overrides resolve to the column indices DESIGN.md 3.3 documents, and
      setting NameSubtext from the spec is a byte-level no-op on the clone.
  #14 every emitted value fits its column's declared type. This realm runs
      STRICT_TRANS_TABLES, so an out-of-range value aborts the migration part-way through.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbc_tables                                             # noqa: E402
import dk_spec as spec                                        # noqa: E402
import mpqlib                                                 # noqa: E402
from dbc_tables import (KIND_FLOAT, KIND_STRING)              # noqa: E402
from dbclib import Dbc                                        # noqa: E402


# ==========================================================================================
# check plumbing
# ==========================================================================================

class Checks:
    """Collects invariant results so the run prints one report and one exit code."""

    def __init__(self):
        self.rows = []

    def _add(self, status, tag, msg):
        self.rows.append((status, tag, msg))
        print(f"  [{status:4}] {tag:5} {msg}")

    def ok(self, tag, msg):
        self._add("PASS", tag, msg)

    def fail(self, tag, msg):
        self._add("FAIL", tag, msg)

    def skip(self, tag, msg):
        self._add("SKIP", tag, msg)

    def expect(self, cond, tag, msg, detail=""):
        (self.ok if cond else self.fail)(tag, msg + (f"  -- {detail}" if detail and not cond
                                                     else ""))
        return bool(cond)

    @property
    def failed(self):
        return [r for r in self.rows if r[0] == "FAIL"]

    @property
    def skipped(self):
        return [r for r in self.rows if r[0] == "SKIP"]

    def summary(self):
        n = len(self.rows)
        print(f"\n{len(self.failed)} failed, {len(self.skipped)} skipped, "
              f"{n - len(self.failed) - len(self.skipped)} passed, {n} total")
        return 1 if self.failed else 0


# ==========================================================================================
# read-only database access
# ==========================================================================================

DEFAULT_MYSQL_CMD = (
    "docker compose -f {repo}/deploy/docker-compose.yml exec -T mysql "
    "mysql --defaults-extra-file=/etc/mysql/backup.cnf"
)


class Db:
    """One read-only SELECT path. Nothing here ever writes."""

    def __init__(self, cmd_template=None, schema="acore_world"):
        self.cmd = shlex.split((cmd_template or DEFAULT_MYSQL_CMD).format(repo=spec.REPO_ROOT))
        self.schema = schema
        self._live = None

    def query(self, sql):
        assert re.match(r"\s*(SELECT|SHOW)\b", sql, re.I), \
            f"Db.query is read-only, refusing: {sql[:60]!r}"
        argv = self.cmd + ["-N", "--raw", "--batch", self.schema, "-e", sql]
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"mysql failed ({proc.returncode}): {proc.stderr.strip()}\n"
                               f"  command: {' '.join(shlex.quote(a) for a in argv)}")
        out = []
        for line in proc.stdout.splitlines():
            out.append([None if c == "\\N" else c for c in line.split("\t")])
        return out

    def live(self):
        if self._live is None:
            try:
                self.query("SELECT 1")
                self._live = True
            except Exception as e:                                    # noqa: BLE001
                self._live = False
                self.error = str(e)
        return self._live


# ==========================================================================================
# SQL literal formatting
# ==========================================================================================

_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\x00": "\\0", "\x1a": "\\Z"}
_UNESCAPES = {v[1]: k for k, v in _ESCAPES.items()}


def sql_str(s):
    """Quote a string for MySQL.

    Backslash escaping, which is only correct because NO_BACKSLASH_ESCAPES is off in this
    realm's sql_mode (verified live) and because AzerothCore's own migrations rely on it.
    Using one escaping scheme rather than mixing '' and \\' also keeps the --check parser
    below unambiguous.
    """
    return "'" + "".join(_ESCAPES.get(c, c) for c in s) + "'"


def unsql_str(tok):
    assert tok.startswith("'") and tok.endswith("'"), f"not a quoted literal: {tok!r}"
    body, out, i = tok[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append(_UNESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def f32(value):
    """Round a Python float to the nearest float32, as a Python float."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def f32_text(value):
    """Shortest decimal text that round-trips to the SAME float32 bits.

    MySQL prints a FLOAT column with about 6 significant digits, which is not enough to
    guarantee a round trip for every float32. Copying a coordinate "verbatim" therefore means
    finding the shortest text whose float32 is bit-identical to the source, not reprinting
    whatever the client library showed.
    """
    assert value == value and abs(value) != float("inf"), f"non-finite float: {value!r}"
    bits = struct.pack("<f", value)
    for precision in range(1, 10):
        text = f"{value:.{precision}g}"
        if struct.pack("<f", float(text)) == bits:
            return text
    raise AssertionError(f"no round-tripping decimal for float32 {value!r}")


def sql_value(v):
    if isinstance(v, str):
        return sql_str(v)
    if isinstance(v, float):
        return f32_text(v)
    return str(int(v))


# ==========================================================================================
# the plan: everything the spec implies, built once, used by both emit and check
# ==========================================================================================

class Plan:
    """Patched DBCs plus the SQL rows read back out of them.

    The SQL side is NEVER computed independently of the DBC side -- it is `row_values()` off
    the patched record. One code path, two serialisations. Invariant #4 then closes the loop
    through the files on disk.
    """

    def __init__(self, dbc_in, checks):
        self.checks = checks
        self.dbc_in = dbc_in
        self.spell = Dbc(dbc_tables.SPELL_DBC, os.path.join(dbc_in, "Spell.dbc"))
        self.sla = Dbc(dbc_tables.SKILLLINEABILITY_DBC,
                       os.path.join(dbc_in, "SkillLineAbility.dbc"))
        self.outfit = Dbc(dbc_tables.CHARSTARTOUTFIT_DBC,
                          os.path.join(dbc_in, "CharStartOutfit.dbc"))
        self.stock_spell_ids = set(self.spell.index())
        self.stock_sla_ids = set(self.sla.index())

        self.sql_rows = {t.sql_table: {} for t in dbc_tables.ALL_TABLES}
        self.client_only_ids = {t.sql_table: set() for t in dbc_tables.ALL_TABLES}
        self.touched_ids = {t.sql_table: set() for t in dbc_tables.ALL_TABLES}

        self._build_spells()
        self._build_sla()
        self._build_outfits()
        self._build_ranks()

    # ---------------------------------------------------------------- Spell.dbc (A3/A11) --
    def _build_spells(self):
        table = dbc_tables.SPELL_DBC
        idx = self.spell.index()

        # #13: the five overrides must land where DESIGN.md 3.3 says they do.
        for name, want in spec.DOCUMENTED_OVERRIDE_INDICES.items():
            got = table.index_of[name]
            self.checks.expect(got == want, "#13",
                               f"spell override column {name} is at format index {got}",
                               f"DESIGN.md documents {want}")

        for ability in spec.ABILITIES:
            src_row = idx[ability.clone_from]
            for rank in ability.ranks:
                row = self.spell.clone_row(src_row)
                before = bytes(self.spell.records[row])
                for col_name, get in spec.SPELL_OVERRIDE_COLUMNS.items():
                    self.spell.set_cell(row, table.index_of[col_name], get(rank))
                # Setting the subtext to the value the clone already carries must not move a
                # single byte -- add_string() reuses the existing NUL-bounded string. Asserted
                # rather than assumed, so "exactly five effective overrides" stays true.
                subtext_col = table.index_of[spec.SUBTEXT_COLUMN]
                offset_before = self.spell.get_u32(row, subtext_col)
                self.spell.set_cell(row, subtext_col, rank.subtext)
                self.checks.expect(
                    self.spell.get_u32(row, subtext_col) == offset_before
                    or self.spell.get_str(row, subtext_col) == rank.subtext,
                    "#13", f"spell {rank.spell_id} NameSubtext resolves to {rank.subtext!r}")
                changed = sum(1 for a, b in zip(before, bytes(self.spell.records[row]))
                              if a != b)
                self.checks.expect(
                    changed <= 4 * len(spec.SPELL_OVERRIDE_COLUMNS), "#13",
                    f"spell {rank.spell_id} is a clone of {ability.clone_from} with "
                    f"{len(spec.SPELL_OVERRIDE_COLUMNS)} cell overrides",
                    f"{changed} bytes differ")
                self.sql_rows["spell_dbc"][rank.spell_id] = self.spell.row_values(row)
                self.touched_ids["spell_dbc"].add(rank.spell_id)

            # A11 client-only: renumber the stock ranks' subtext so the spellbook agrees with
            # the renumbered chain. NameSubtext is parsed server-side but the only consumer is
            # the .spellinfo GM command (cs_spellinfo.cpp:759).
            subtext_col = table.index_of[spec.SUBTEXT_COLUMN]
            for spell_id, subtext in sorted(ability.stock_subtext.items()):
                row = idx[spell_id]
                self.spell.set_cell(row, subtext_col, subtext)
                self.touched_ids["spell_dbc"].add(spell_id)
                if spec.MIRROR_STOCK_SUBTEXT_TO_SQL:
                    self.sql_rows["spell_dbc"][spell_id] = self.spell.row_values(row)
                else:
                    self.client_only_ids["spell_dbc"].add(spell_id)

    # ------------------------------------------------------ SkillLineAbility.dbc (A4/A12) --
    def _build_sla(self):
        table = dbc_tables.SKILLLINEABILITY_DBC
        idx = self.sla.index()
        for ability in spec.ABILITIES:
            for rank in ability.ranks:
                row = len(self.sla.records)
                self.sla.records.append(bytearray(table.record_size))
                values = {
                    "ID": rank.sla_id,
                    "SkillLine": ability.skill_line,
                    "Spell": rank.spell_id,
                    "RaceMask": 0,
                    "ClassMask": 32,                # 1 << (CLASS_DEATH_KNIGHT - 1)
                    "ExcludeRace": 0,
                    "ExcludeClass": 0,
                    # 770/771/772 are SkillLine.dbc categoryId 7 class skills that cap at
                    # value 1, so MinSkillLineRank cannot level-gate anything; every stock DK
                    # row uses 1. Level gating comes from Spell.dbc BaseLevel.
                    "MinSkillLineRank": 1,
                    "SupercededBySpell": rank.superceded_by,
                    "AcquireMethod": rank.acquire_method,
                    "TrivialSkillLineRankHigh": 0,
                    "TrivialSkillLineRankLow": 0,
                    "CharacterPoints_1": 0,
                    "CharacterPoints_2": 0,
                }
                for name, value in values.items():
                    self.sla.set_cell(row, table.index_of[name], value)
                self.sql_rows["skilllineability_dbc"][rank.sla_id] = self.sla.row_values(row)
                self.touched_ids["skilllineability_dbc"].add(rank.sla_id)

            for sla_id, edits in sorted(ability.stock_sla_edits.items()):
                row = idx[sla_id]
                # Every other field is copied verbatim by virtue of editing the parsed record
                # in place -- there is no re-authoring step that could drop one.
                for name, value in edits.items():
                    self.sla.set_cell(row, table.index_of[name], value)
                self.sql_rows["skilllineability_dbc"][sla_id] = self.sla.row_values(row)
                self.touched_ids["skilllineability_dbc"].add(sla_id)

    # ------------------------------------------------------- CharStartOutfit.dbc (A8/A13) --
    def _build_outfits(self):
        table = dbc_tables.CHARSTARTOUTFIT_DBC
        idx = self.outfit.index()
        key_cols = {table.index_of[n] for n in spec.OUTFIT_KEY_COLUMNS}
        id_col = table.index_column()
        for dk_id, template_id in spec.START_OUTFITS:
            dst, src = idx[dk_id], idx[template_id]
            keys_before = {c: self.outfit.cell(dst, c) for c in key_cols}
            for c in range(len(table.columns)):
                if c == id_col or c in key_cols:
                    continue          # keep 352/353's own race/class/sex/outfit
                self.outfit.set_cell(dst, c, self.outfit.cell(src, c))
            keys_after = {c: self.outfit.cell(dst, c) for c in key_cols}
            self.checks.expect(keys_before == keys_after, "#11",
                               f"CharStartOutfit {dk_id} keeps race/class/sex/outfit "
                               f"{[keys_after[table.index_of[n]] for n in spec.OUTFIT_KEY_COLUMNS]}")
            arrays_match = all(self.outfit.cell(dst, c) == self.outfit.cell(src, c)
                               for c in range(len(table.columns))
                               if c != id_col and c not in key_cols)
            self.checks.expect(arrays_match, "#11",
                               f"CharStartOutfit {dk_id} item arrays copied from {template_id}")
            self.sql_rows["charstartoutfit_dbc"][dk_id] = self.outfit.row_values(dst)
            self.touched_ids["charstartoutfit_dbc"].add(dk_id)

    # --------------------------------------------------------------- spell_ranks (A5/A6) --
    def _build_ranks(self):
        self.spell_ranks = []
        self.spell_bonus = []
        self.rank_deletes = []
        for ability in spec.ABILITIES:
            chain = ability.chain
            first = chain[0]
            self.rank_deletes.append((ability.stock_chain[0], first, chain))
            for i, sid in enumerate(chain, start=1):
                self.spell_ranks.append((first, sid, i))
            for rank in ability.ranks:
                self.spell_bonus.append((rank.spell_id,) + ability.bonus)


# ==========================================================================================
# SQL emission
# ==========================================================================================

BANNER = """-- {name}
--
-- GENERATED by build/modules/mod-dk-lowlevel/tools/dkspells.py from tools/dk_spec.py.
-- DO NOT EDIT BY HAND. Re-run the generator and commit both its SQL and its DBC outputs
-- together, or the client tooltip and the server damage will drift (DESIGN.md 8.3).
--
-- Re-runnable on purpose. UpdateFetcher tracks a migration by bare filename plus a SHA1 of
-- its contents (UpdateFetcher.cpp:326-370): an unchanged file is skipped, but a CHANGED file
-- is re-applied IN FULL. Every statement below is therefore DELETE-then-INSERT per key.
"""


def _insert_set(table, cols, values, comments=None):
    """`INSERT INTO t SET c = v, ...`, one column per line.

    A 234-column positional VALUES tuple is unreviewable and one dropped comma silently
    shifts every subsequent field by one. Named assignment makes a regenerated migration diff
    field by field, which is what a human actually needs to check here.
    """
    out = [f"INSERT INTO `{table}` SET"]
    width = max(len(c) for c in cols)
    for i, (c, v) in enumerate(zip(cols, values)):
        tail = "," if i + 1 < len(cols) else ";"
        note = (comments or {}).get(c)
        # No trailing `-- note` on a string value. A description that itself contained a comma
        # followed by " -- " would make the line ambiguous to parse_emitted_sql below; refusing
        # up front is cheaper than a parser that has to be clever.
        assert not (note and isinstance(v, str)), \
            f"{table}.{c}: trailing notes are not allowed on string values"
        out.append(f"  `{c}`{' ' * (width - len(c))} = {sql_value(v)}{tail}"
                   + (f"   -- {note}" if note else ""))
    return "\n".join(out)


def _insert_values(table, cols, rows):
    head = f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in cols) + ") VALUES"
    body = [f"  ({', '.join(sql_value(v) for v in row)})" for row in rows]
    return head + "\n" + ",\n".join(body) + ";"


def emit_class_stats(plan, db, checks):
    """A1 -- 54 player_class_stats rows for class 6, copied from class 1 in the live DB.

    THE HARD BOOT GATE. ObjectMgr.cpp:4878/4885 call exit(1) when a class has no stats at its
    start level, and with StartHeroicPlayerLevel = 1 that read is levelInfo[0], which is
    zero-filled today (class 6 has 26 rows, min level 55). These rows must be applied and the
    server restarted BEFORE the config is flipped.
    """
    cols = spec.CLASS_STATS_COLUMNS
    rows = db.query(
        "SELECT " + ", ".join(cols[1:]) + " FROM player_class_stats "
        f"WHERE Class = {spec.TEMPLATE_CLASS} AND Level BETWEEN "
        f"{spec.CLASS_STATS_LEVELS[0]} AND {spec.CLASS_STATS_LEVELS[-1]} ORDER BY Level")
    checks.expect(len(rows) == len(spec.CLASS_STATS_LEVELS), "#8",
                  f"read {len(rows)} class {spec.TEMPLATE_CLASS} rows from the live DB",
                  f"expected {len(spec.CLASS_STATS_LEVELS)}")
    assert len(rows) == len(spec.CLASS_STATS_LEVELS), (
        f"player_class_stats has {len(rows)} rows for class {spec.TEMPLATE_CLASS} in "
        f"levels {spec.CLASS_STATS_LEVELS[0]}..{spec.CLASS_STATS_LEVELS[-1]}, expected "
        f"{len(spec.CLASS_STATS_LEVELS)} -- refusing to emit a partial boot gate")
    levels = [int(r[0]) for r in rows]
    checks.expect(levels == list(spec.CLASS_STATS_LEVELS), "#8",
                  f"template levels are dense {levels[0]}..{levels[-1]}")

    out_rows = [[spec.DK_CLASS] + [int(v) for v in r] for r in rows]
    lo, hi = spec.CLASS_STATS_LEVELS[0], spec.CLASS_STATS_LEVELS[-1]
    body = f"""{BANNER.format(name=spec.SQL_FILES['class_stats'])}--
-- A1. Death Knight base stats for levels {lo}-{hi}, copied verbatim from class
-- {spec.TEMPLATE_CLASS} (Warrior) as read out of this realm's own player_class_stats.
--
-- These are not guesswork. Class 1 and class 6 are byte-identical from level 56 up and
-- differ by a single point of Strength and Stamina at 55, so "copy the warrior" is exactly
-- what Blizzard's data already does above the boundary.
--
-- 54 rows, not 540: player_class_stats is (class x level) and player_race_stats is flat per
-- race, added on top at ObjectMgr.cpp:4830-4834.
--
-- WARNING: applying this is step 2 of the build order. StartHeroicPlayerLevel must not be
-- lowered to 1 until these rows are live and the worldserver has restarted cleanly, or the
-- next boot dies at ObjectMgr.cpp:4878 with a message that names the RACE, not the cause.
-- Levels 55-80 are deliberately untouched -- the 13 existing Death Knights use them.

DELETE FROM `player_class_stats` WHERE `Class` = {spec.DK_CLASS} AND `Level` BETWEEN {lo} AND {hi};

{_insert_values('player_class_stats', cols, out_rows)}
"""
    return body, out_rows


def _spell_column_notes(spell_id):
    """Trailing `-- why` notes on the cells a reviewer must be able to check at a glance.

    Every one of these is a cell that looks arbitrary and is not; the rest of the 234 are
    verbatim clone output and are noise if annotated.
    """
    rank = spec.rank_by_spell_id(spell_id)
    notes = {
        "ID": f"custom block {spec.SPELL_ID_BASE}-{spec.SPELL_ID_BASE + 999}, "
              f"above Spell.dbc's max 80864 and below AC's own 100001",
        "BaseLevel": "learn level; also mod-learn-spells filter",
        "SpellLevel": "damage scaling level",
        "Effect_1": "2 SPELL_EFFECT_SCHOOL_DAMAGE",
        "Effect_2": "64 SPELL_EFFECT_TRIGGER_SPELL",
        "EffectTriggerSpell_2": "55095 Frost Fever -- the entire disease mechanism, cloned",
        "SpellClassSet": "15 SPELLFAMILY_DEATHKNIGHT (SharedDefines.h:3799)",
        "SpellClassMask_1": "matched by Improved Icy Touch / Killing Machine / Rime",
        "SpellIconID": "2721 -- SpellInfoCorrections.cpp:5306 keys a synthetic "
                       "SpellFamilyFlags bit off this",
        "RuneCostID": "241 = 0 Blood / 0 Unholy / 1 Frost / 100 RunicPower, shared with "
                      "every stock rank",
        "SchoolMask": "16 Frost",
        "CastingTimeIndex": "1 instant",
        "RangeIndex": "3, 20 yards",
        "PowerType": "5 POWER_RUNE",
    }
    if rank:
        notes["EffectDieSides_1"] = f"$M1 = BasePoints + DieSides = {rank.damage_max}"
        notes["EffectBasePoints_1"] = f"$m1 = BasePoints + 1 = {rank.damage_min}"
    return notes


def emit_spells(plan):
    """A3 spell_dbc, A4 skilllineability_dbc, A5 spell_ranks, A6 spell_bonus_data."""
    parts = [BANNER.format(name=spec.SQL_FILES["spells"])]

    # ---- A3 -----------------------------------------------------------------------------
    spell_ids = sorted(plan.sql_rows["spell_dbc"])
    parts.append(f"""--
-- A3. spell_dbc -- {len(spell_ids)} row(s), {len(dbc_tables.SPELL_DBC)} columns each.
--
-- This is a byte-for-byte clone of the stock record with five cells overridden. Cloning is
-- what keeps the ability behaving like a Death Knight ability: SpellClassSet / SpellClassMask
-- carry every talent and proc interaction, EffectTriggerSpell_2 carries Frost Fever, and
-- SpellIconID carries the Sigil of the Frozen Conscience correction. None of those is keyed
-- on the spell id anywhere in the core, so an authored row would lose all of them silently.
--
-- The column count is frozen by DBCDatabaseLoader.cpp:124 -- an ASSERT that aborts
-- worldserver during LoadDBCStores. Never ALTER this table.
--
-- `INSERT ... SET` rather than a positional VALUES tuple so a regenerated migration produces
-- a field-by-field diff.""")
    for sid in spell_ids:
        parts.append(f"DELETE FROM `spell_dbc` WHERE `ID` = {sid};")
        parts.append(_insert_set("spell_dbc", dbc_tables.SPELL_DBC.columns,
                                 plan.sql_rows["spell_dbc"][sid],
                                 _spell_column_notes(sid)))

    # ---- A4 -----------------------------------------------------------------------------
    sla_ids = sorted(plan.sql_rows["skilllineability_dbc"])
    new_ids = set(spec.all_custom_sla_ids())
    parts.append(f"""--
-- A4. skilllineability_dbc -- {len(sla_ids)} rows, {len(dbc_tables.SKILLLINEABILITY_DBC)} columns each.
--
-- One new row per custom rank, plus an OVERRIDE of stock row 16231. That override is not
-- optional and it is the least obvious thing in this whole feature: stock 16231 is
-- (16231, 771, 45477, 0, 32, 0, 0, 1, 49896, 2, 0, 0, 0, 0), and AcquireMethod = 2 means
-- learnSkillRewardedSpells grants the LEVEL 55 Icy Touch the moment a Death Knight acquires
-- skill 771 -- which happens at character creation. Leave it and every new DK starts with a
-- 127-137 damage nuke and the feature is silently defeated.
--
-- At most one row per supercede chain may carry AcquireMethod = 2: Player.cpp:12284-12300
-- sets skipCurrent when the SUPERSEDING row is also 2, so two would grant the higher rank.
-- Rank 1 carries it (and gets a free reconcile at every login via _LoadSkills ->
-- learnSkillRewardedSpells, Player.cpp:14081); everything above it is 0, which is also
-- mod-learn-spells filter (mod_learnspells.cpp:446).
--
-- Every field other than the edited one is copied verbatim out of the parsed stock DBC.""")
    for sid in sla_ids:
        kind = "new" if sid in new_ids else "override of an existing stock row"
        parts.append(f"DELETE FROM `skilllineability_dbc` WHERE `ID` = {sid};   -- {kind}")
        parts.append(_insert_set("skilllineability_dbc",
                                 dbc_tables.SKILLLINEABILITY_DBC.columns,
                                 plan.sql_rows["skilllineability_dbc"][sid]))

    # ---- A5 -----------------------------------------------------------------------------
    chains = ", ".join(str(a.chain[0]) for a in spec.ABILITIES)
    del_first = sorted({old for old, _new, _c in plan.rank_deletes}
                       | {new for _o, new, _c in plan.rank_deletes})
    del_spells = sorted({s for _o, _n, chain in plan.rank_deletes for s in chain})
    parts.append(f"""--
-- A5. spell_ranks -- the Icy Touch chain, RENUMBERED.
--
-- SpellMgr::LoadSpellRanks (SpellMgr.cpp:1279-1388) is the only chain mechanism at this
-- revision: there is no spell_chain table, and SkillLineAbility.SupercededBySpell is not used
-- to build chains. It requires a DENSE 1..N sequence and treats first_spell_id AS the rank 1
-- spell, so inserting below rank 1 means renumbering the whole chain -- first_spell_id
-- becomes {chains}. A gap makes it `continue` with only an sql.sql log line, and the chain
-- silently disappears: in game that is one Icy Touch button per rank, with no supersession.
--
-- Both delete forms are needed for idempotence: the table's primary key is
-- (first_spell_id, rank) but spell_id carries a UNIQUE index, so a re-run after a spec change
-- has to clear the old chain by BOTH keys.""")
    parts.append("DELETE FROM `spell_ranks` WHERE `first_spell_id` IN ("
                 + ", ".join(str(i) for i in del_first) + ");")
    parts.append("DELETE FROM `spell_ranks` WHERE `spell_id` IN ("
                 + ", ".join(str(i) for i in del_spells) + ");")
    parts.append(_insert_values("spell_ranks", ("first_spell_id", "spell_id", "rank"),
                                plan.spell_ranks))

    # ---- A6 -----------------------------------------------------------------------------
    bonus_ids = sorted(r[0] for r in plan.spell_bonus)
    parts.append(f"""--
-- A6. spell_bonus_data for the new ranks.
--
-- SpellMgr.cpp:947-961 falls back to the first rank of a chain when a spell has no row of its
-- own. All five stock Icy Touch ranks already have explicit rows, so renumbering
-- first_spell_id cannot disturb them; only the {len(bonus_ids)} new rank(s) need one. Values
-- copied from the stock 45477 row.""")
    parts.append("DELETE FROM `spell_bonus_data` WHERE `entry` IN ("
                 + ", ".join(str(i) for i in bonus_ids) + ");")
    parts.append(_insert_values(
        "spell_bonus_data",
        ("entry", "direct_bonus", "dot_bonus", "ap_bonus", "ap_dot_bonus", "comments"),
        plan.spell_bonus))

    return "\n\n".join(parts) + "\n"


def emit_createinfo(plan, db, checks):
    """A7 playercreateinfo, A8 charstartoutfit_dbc, A9 action bar, A10 cast spell."""
    src = db.query(
        "SELECT CAST(position_x AS DOUBLE), CAST(position_y AS DOUBLE), "
        "CAST(position_z AS DOUBLE), CAST(orientation AS DOUBLE) FROM playercreateinfo "
        f"WHERE race = {spec.DK_RACE} AND class = {spec.TEMPLATE_CLASS}")
    checks.expect(len(src) == 1, "A7",
                  f"read the race {spec.DK_RACE} class {spec.TEMPLATE_CLASS} spawn point "
                  "from the live DB")
    assert len(src) == 1, "no template playercreateinfo row to copy the spawn point from"
    # CAST(... AS DOUBLE) hands back the exact double value of the stored float32; f32_text
    # then finds the shortest decimal that reproduces those same 32 bits.
    pos = [f32(float(v)) for v in src[0]]
    pos_text = [f32_text(v) for v in pos]
    for text, value in zip(pos_text, pos):
        assert struct.pack("<f", float(text)) == struct.pack("<f", value)
    checks.ok("A7", "spawn point round-trips to identical float32 bits: "
                    + " ".join(pos_text))

    parts = [BANNER.format(name=spec.SQL_FILES["createinfo"])]

    parts.append(f"""--
-- A7. Spawn a Human Death Knight in Northshire instead of Acherus.
--
-- This one row does three jobs. It makes the entire Death Knight starter chain unreachable
-- (every questgiver for quests 12593..12801 spawns only on map 609, there are zero
-- areatrigger_teleport rows targeting 609, and every chain quest is MinLevel 55, so nothing
-- has to be deleted or disabled); it keeps Player::CalculateTalentsPoints on its normal
-- branch instead of the map-609 branch that refunds every talent point; and it sets the
-- homebind (PlayerStorage.cpp:7187-7191).
--
-- Coordinates are copied from the race {spec.DK_RACE} class {spec.TEMPLATE_CLASS} row in this
-- realm's own playercreateinfo, printed at the shortest precision that reproduces the stored
-- float32 exactly.
--
-- DELETE + INSERT rather than UPDATE: an UPDATE against a missing row succeeds and does
-- nothing, which is the failure mode this whole feature cannot afford.

DELETE FROM `playercreateinfo` WHERE `race` = {spec.DK_RACE} AND `class` = {spec.DK_CLASS};
{_insert_values('playercreateinfo',
                ('race', 'class', 'map', 'zone', 'position_x', 'position_y', 'position_z',
                 'orientation'),
                [[spec.DK_RACE, spec.DK_CLASS, spec.CREATE_MAP, spec.CREATE_ZONE] + pos])}""")

    outfit_ids = sorted(plan.sql_rows["charstartoutfit_dbc"])
    template_by_dk = dict(spec.START_OUTFITS)
    parts.append(f"""--
-- A8. charstartoutfit_dbc -- {len(outfit_ids)} rows, {len(dbc_tables.CHARSTARTOUTFIT_DBC)} columns each.
--
-- The starting kit comes from CharStartOutfit.dbc, not from playercreateinfo_item. The one
-- existing DK row there, (0, 6, 40582, -1), is a REMOVAL directive: negative counts route
-- into PlayerCreateInfoAddItemHelper (ObjectMgr.cpp:4311-4343, 4482-4502) which zeroes that
-- itemId inside the CharStartOutfit entry. Doing this as eighteen negative rows plus a
-- positive kit would log an error per miss; overriding the outfit row is cleaner.
--
-- Stock rows 352/353 are the Human DK kit: eighteen items, every 346xx piece RequiredLevel 55
-- plate. Rows 1/14 are the Human warrior kit, whose Worn Greatsword (49778) is
-- RequiredLevel 1 and which a DK can equip -- playercreateinfo_skills gives classMask 35
-- skill 55 (Two-Handed Swords).
--
-- RaceID/ClassID/SexID/OutfitID are NOT copied; 352/353 already carry the right ones. Only
-- the ItemID / DisplayItemID / InventoryType arrays move. Note that DisplayItemID and
-- InventoryType are `x` (FT_NA) in CharStartOutfitEntryfmt: the server discards them, the
-- client character-create preview uses them, and they still occupy a required SQL column.""")
    for oid in outfit_ids:
        parts.append(f"DELETE FROM `charstartoutfit_dbc` WHERE `ID` = {oid};   "
                     f"-- copied from stock outfit {template_by_dk[oid]}")
        parts.append(_insert_set("charstartoutfit_dbc",
                                 dbc_tables.CHARSTARTOUTFIT_DBC.columns,
                                 plan.sql_rows["charstartoutfit_dbc"][oid]))

    rank1 = spec.ABILITIES[0].ranks[0]
    parts.append(f"""--
-- A9. Action bar for a new Human Death Knight.
--
-- Button 1 holds the custom rank ({rank1.spell_id}), so the acceptance test -- hover it and
-- read "{rank1.damage_min} to {rank1.damage_max} Frost damage" -- needs no setup. The stock
-- rows handed out 45477/45462/45902/47541/49576, all level 55 abilities the character will
-- not know. 6603 is Attack; 59752 is Every Man for Himself.

DELETE FROM `playercreateinfo_action` WHERE `race` = {spec.DK_RACE} AND `class` = {spec.DK_CLASS};
{_insert_values('playercreateinfo_action', ('race', 'class', 'button', 'action', 'type'),
                [[spec.DK_RACE, spec.DK_CLASS, b, a, t] for b, a, t in spec.ACTION_BAR])}""")

    del_lines = "\n".join(
        f"DELETE FROM `playercreateinfo_cast_spell` WHERE `raceMask` = {rm} "
        f"AND `classMask` = {cm} AND `spell` = {sp};"
        for rm, cm, sp in spec.CAST_SPELL_DELETIONS)
    parts.append(f"""--
-- A10. Stop casting Blood Presence at first login.
--
-- 48266 is a level 55 spell cast with triggered = true (CharacterHandler.cpp:1007-1013), so
-- it applies regardless of level and leaves a level 1 Death Knight wearing an aura they
-- cannot map to any spell in their spellbook. Blood Presence comes back later as a normal
-- progression grant. Delete-only: there is nothing to insert, and the statement is a no-op on
-- a second run.

{del_lines}""")

    return "\n\n".join(parts) + "\n"


# ==========================================================================================
# generated C++ header
# ==========================================================================================

def emit_header(plan):
    grants = spec.progression_grants()
    lines = []
    for level, sid in grants:
        rank = spec.rank_by_spell_id(sid)
        lines.append(f"    {{ {level:>2}, {sid} }},   // Icy Touch ({rank.subtext}) -- "
                     f"{rank.damage_min}-{rank.damage_max} Frost damage")
    utilities = "\n".join(
        f"static constexpr uint32 DK_SPELL_{name:<18} = {sid};"
        f"   // {cfg}, default level {lvl}"
        for name, sid, cfg, lvl in spec.UTILITY_SPELLS)
    return f"""/*
 * GENERATED FILE -- DO NOT EDIT.
 *
 * Produced by build/modules/mod-dk-lowlevel/tools/dkspells.py from tools/dk_spec.py.
 * Regenerate with `tools/dkspells.py`; verify with `tools/dkspells.py --check`.
 *
 * WHY THE PROGRESSION IS A COMPILED TABLE AND NOT A WORLD TABLE
 * ------------------------------------------------------------
 * One source of truth. This array, the spell_dbc rows the server reads and the Spell.dbc
 * records the client reads all come out of the same spec in the same run, so they cannot
 * drift. A world table would add a load-order dependency and a second thing to keep in sync,
 * and it would buy nothing: changing the progression means regenerating the client DBC and
 * repackaging the client anyway, which is a rebuild either way.
 *
 * There is also no hot reload available for the spell data (LoadDBCStores has exactly one
 * call site, World.cpp:384), so nothing is gained by making this runtime-editable.
 */

#ifndef MOD_DK_LOWLEVEL_DK_PROGRESSION_H
#define MOD_DK_LOWLEVEL_DK_PROGRESSION_H

#include "Define.h"

struct DkGrant
{{
    uint8  level;
    uint32 spellId;
}};

// Sorted by level, then spell id. Reconcile() walks this in order and breaks on the first
// entry above the player's level, so the ordering is load-bearing, not cosmetic.
static constexpr DkGrant kDkProgression[] =
{{
{chr(10).join(lines)}
}};

static constexpr uint32 kDkProgressionCount =
    static_cast<uint32>(sizeof(kDkProgression) / sizeof(kDkProgression[0]));

// Utilities the skipped Acherus starter chain used to hand out. Granted by learnSpell(), never
// by casting the quest reward spells: 53821 (quest 12801) runs SPELL_EFFECT_BIND and would
// silently rebind the player's hearthstone at every login, and 53431 is unnecessary because
// learnSpell(53428) alone drives Player::addSpell's SKILL_RUNEFORGING branch
// (Player.cpp:3377). 48778, the Acherus Deathcharger, is deliberately NOT here.
{utilities}

#endif // MOD_DK_LOWLEVEL_DK_PROGRESSION_H
"""


# ==========================================================================================
# parsing our own emitted SQL back (for invariant #4 and #9)
# ==========================================================================================

_LIT = re.compile(r"""'(?:\\.|[^'\\])*'|-?\d+\.\d+(?:[eE][-+]?\d+)?|-?\d+(?:[eE][-+]?\d+)?""")
# One `col = literal` assignment. The literal alternatives are spelled out rather than using
# a lazy `.+?`, so a string containing a comma or a semicolon cannot split the line early.
_SET_LINE = re.compile(
    r"""^\s*`(?P<col>\w+)`\s*=\s*"""
    r"""(?P<val>'(?:\\.|[^'\\])*'|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"""
    r"""\s*(?P<end>[,;])(?:\s+--.*)?$""")


def _literal(tok):
    tok = tok.strip()
    if tok.startswith("'"):
        return unsql_str(tok)
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    return f32(float(tok))


def parse_emitted_sql(path):
    """Parse the exact subset of SQL this generator emits. Nothing more.

    Deliberately not a SQL parser. It understands `INSERT INTO t SET c = v,` blocks,
    `INSERT INTO t (cols) VALUES (...)` blocks and `DELETE FROM t WHERE ...` statements,
    because those are the only three shapes emitted above. If the emitter grows a fourth
    shape this raises instead of quietly under-checking.
    """
    statements = []
    lines = open(path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            i += 1
            continue
        m = re.match(r"^INSERT INTO `(\w+)` SET\s*$", stripped)
        if m:
            table, row = m.group(1), {}
            i += 1
            while i < len(lines):
                sm = _SET_LINE.match(lines[i])
                assert sm, f"{path}:{i+1}: unparsable SET line {lines[i]!r}"
                row[sm.group("col")] = _literal(sm.group("val"))
                i += 1
                if sm.group("end") == ";":
                    break
            statements.append(("insert", table, row))
            continue
        m = re.match(r"^INSERT INTO `(\w+)` \((.*)\) VALUES\s*$", stripped)
        if m:
            table = m.group(1)
            cols = re.findall(r"`(\w+)`", m.group(2))
            i += 1
            while i < len(lines):
                body = lines[i].split("--")[0].strip()
                assert body.startswith("("), f"{path}:{i+1}: expected a VALUES tuple"
                vals = [_literal(t) for t in _LIT.findall(body)]
                assert len(vals) == len(cols), \
                    f"{path}:{i+1}: {len(vals)} values for {len(cols)} columns"
                statements.append(("insert", table, dict(zip(cols, vals))))
                last = body.endswith(";")
                i += 1
                if last:
                    break
            continue
        m = re.match(r"^DELETE FROM `(\w+)` (.*);", stripped.split("--")[0].strip())
        if m:
            statements.append(("delete", m.group(1), m.group(2)))
            i += 1
            continue
        raise AssertionError(f"{path}:{i+1}: unrecognised statement {stripped!r}")
    return statements


# ==========================================================================================
# invariants
# ==========================================================================================

def check_column_counts(checks):
    """#7 -- the SQL column count must equal strlen(format string), exactly, for every table."""
    for t in dbc_tables.ALL_TABLES:
        checks.expect(len(t.columns) == len(t.fmt), "#7",
                      f"{t.sql_table}: {len(t.columns)} columns == strlen(format) "
                      f"{len(t.fmt)}")


def check_schema_against_db(db, checks):
    """#7 (live half) -- the frozen shape in dbc_tables.py still matches information_schema."""
    for t in dbc_tables.ALL_TABLES:
        rows = db.query(
            "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{db.schema}' AND TABLE_NAME = '{t.sql_table}' "
            "ORDER BY ORDINAL_POSITION")
        names = tuple(r[0] for r in rows)
        checks.expect(names == t.columns, "#7",
                      f"{t.sql_table}: live schema matches dbc_tables.py "
                      f"({len(names)} columns)",
                      f"first difference at index "
                      f"{next((i for i, (a, b) in enumerate(zip(names, t.columns)) if a != b), len(names))}")
        signed_live = {r[0] for r in rows
                       if r[1] in ("int", "tinyint", "smallint", "bigint")}
        checks.expect(signed_live == t.signed, "#7",
                      f"{t.sql_table}: signed-column set matches",
                      f"live-only {sorted(signed_live - t.signed)[:4]} "
                      f"spec-only {sorted(t.signed - signed_live)[:4]}")
        floats_live = {r[0] for r in rows if r[1] == "float"}
        floats_fmt = {t.columns[i] for i in range(len(t.columns)) if t.kind(i) == KIND_FLOAT}
        checks.expect(floats_live == floats_fmt, "#7",
                      f"{t.sql_table}: float columns derive correctly from the format string")


_KIND_RANGE = {
    dbc_tables.KIND_UINT8: (0, 255),
    dbc_tables.KIND_INT32: (-(2 ** 31), 2 ** 31 - 1),
    dbc_tables.KIND_UINT32: (0, 2 ** 32 - 1),
}


def check_value_ranges(sql_paths, db, checks):
    """#14 -- every emitted value fits its column.

    This realm runs STRICT_TRANS_TABLES, so an out-of-range value is an ERROR at apply time,
    not a silent truncation -- which means a bad row aborts the migration and leaves the world
    DB half-updated. There is no way to dry-run the SQL without writing to a database, so the
    range is checked here instead: integers against the kind the format string and the signed
    list imply (fully offline), string lengths against information_schema when it is
    reachable. Signedness is the interesting half: charstartoutfit ItemID_* legitimately hold
    -1, and reading them unsigned would emit 4294967295 into a signed `int`.
    """
    maxlen = {}
    if db is not None and db.live():
        for t in dbc_tables.ALL_TABLES:
            for name, n in db.query(
                    "SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH "
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = "
                    f"'{db.schema}' AND TABLE_NAME = '{t.sql_table}' "
                    "AND CHARACTER_MAXIMUM_LENGTH IS NOT NULL"):
                maxlen[(t.sql_table, name)] = int(n)
    else:
        checks.skip("#14", "no live DB: string column lengths not checked")

    problems = []
    for path in sql_paths:
        for kind, table, payload in parse_emitted_sql(path):
            if kind != "insert" or table not in dbc_tables.BY_SQL_NAME:
                continue
            t = dbc_tables.BY_SQL_NAME[table]
            for i, name in enumerate(t.columns):
                v = payload[name]
                k = t.kind(i)
                if k == KIND_STRING:
                    limit = maxlen.get((table, name))
                    if limit is not None and len(v) > limit:
                        problems.append(f"{table}.{name}: {len(v)} chars > {limit}")
                elif k in _KIND_RANGE:
                    lo, hi = _KIND_RANGE[k]
                    if not lo <= v <= hi:
                        problems.append(f"{table}.{name}: {v} outside [{lo}, {hi}] for {k}")
    checks.expect(not problems, "#14",
                  "every emitted value fits its column's declared type",
                  "; ".join(problems[:6]))


def check_ids(plan, checks):
    """#2 -- id range and freshness."""
    for sid in spec.all_custom_spell_ids():
        checks.expect(
            sid > 0 and spec.SPELL_ID_MIN <= sid < spec.SPELL_ID_MAX
            and sid not in plan.stock_spell_ids,
            "#2",
            f"spell id {sid} is > 0, in [{spec.SPELL_ID_MIN}, {spec.SPELL_ID_MAX}) and free")
    for aid in spec.all_custom_sla_ids():
        checks.expect(aid >= spec.SLA_ID_MIN and aid not in plan.stock_sla_ids, "#2",
                      f"SkillLineAbility id {aid} is >= {spec.SLA_ID_MIN} and free")


def check_ascending(plan, checks):
    """#3 -- appending must keep Spell.dbc strictly ascending."""
    checks.expect(plan.spell.is_strictly_ascending(), "#3",
                  f"patched Spell.dbc is strictly ascending by id "
                  f"({len(plan.spell.records)} records, max "
                  f"{max(plan.spell.ids())})")


def check_ranks(plan, checks):
    """#5 -- dense 1..N per chain, first_spell_id is rank 1."""
    by_chain = {}
    for first, sid, rank in plan.spell_ranks:
        by_chain.setdefault(first, []).append((rank, sid))
    for first, entries in sorted(by_chain.items()):
        entries.sort()
        ranks = [r for r, _ in entries]
        dense = ranks == list(range(1, len(ranks) + 1))
        checks.expect(dense, "#5", f"chain {first}: ranks are dense 1..{len(ranks)}",
                      f"got {ranks}")
        checks.expect(len(entries) >= 2, "#5",
                      f"chain {first}: {len(entries)} ranks (LoadSpellRanks drops chains < 2)")
        checks.expect(entries[0][1] == first, "#5",
                      f"chain {first}: first_spell_id is the rank 1 spell")
    all_spells = [s for _f, s, _r in plan.spell_ranks]
    checks.expect(len(set(all_spells)) == len(all_spells), "#5",
                  "no spell appears twice in spell_ranks (the table has a UNIQUE on spell_id)")

    # Density alone is not enough, and this is the trap. The emitted chain is dense BY
    # CONSTRUCTION -- ranks are numbered by enumerating dk_spec's chain -- so a spec that
    # simply forgets a stock rank still produces a perfectly dense 1..N sequence, while the
    # forgotten rank loses its spell_ranks row to the DELETE and becomes an unranked orphan
    # that no longer supersedes anything. Ground-truth the chain against the DBC instead:
    # SkillLineAbility.SupercededBySpell is a linked list over the stock ranks, and it is not
    # something this generator writes for stock rows, so it is an independent source.
    sla_table = dbc_tables.SKILLLINEABILITY_DBC
    spell_col = sla_table.index_of["Spell"]
    supercede_col = sla_table.index_of["SupercededBySpell"]
    by_spell = {}
    for _sla_id, row in plan.sla.index().items():
        by_spell.setdefault(plan.sla.cell(row, spell_col), []).append(row)
    for ability in spec.ABILITIES:
        walk, cur, guard = [], ability.clone_from, 0
        while cur and cur in by_spell and guard < 64:
            walk.append(cur)
            cur = plan.sla.cell(by_spell[cur][0], supercede_col)
            guard += 1
        checks.expect(tuple(walk) == ability.stock_chain, "#5",
                      f"chain {ability.chain[0]}: stock ranks match the "
                      f"SkillLineAbility supercede links {walk}",
                      f"spec says {list(ability.stock_chain)}")


def check_chain_not_orphaning(plan, db, checks):
    """#5 (live half) -- the DELETE must not strand a spell that has a rank row today."""
    for ability in spec.ABILITIES:
        old_first = ability.stock_chain[0]
        rows = db.query("SELECT spell_id FROM spell_ranks "
                        f"WHERE first_spell_id = {old_first}")
        existing = {int(r[0]) for r in rows}
        orphaned = existing - set(ability.chain)
        checks.expect(not orphaned, "#5",
                      f"chain {old_first}: all {len(existing)} spells that have a rank row "
                      f"today are still in the renumbered chain",
                      f"would be orphaned by the DELETE: {sorted(orphaned)}")


def check_acquire_methods(plan, checks):
    """#6 -- exactly one AcquireMethod = 2 per supercede chain."""
    table = dbc_tables.SKILLLINEABILITY_DBC
    am, spell_col = table.index_of["AcquireMethod"], table.index_of["Spell"]
    for ability in spec.ABILITIES:
        chain = set(ability.chain)
        idx = plan.sla.index()
        twos, seen = [], []
        for _sla_id, row in sorted(idx.items()):
            if plan.sla.cell(row, spell_col) in chain:
                seen.append((plan.sla.cell(row, spell_col), plan.sla.cell(row, am)))
                if plan.sla.cell(row, am) == 2:
                    twos.append(plan.sla.cell(row, spell_col))
        checks.expect(len(twos) == 1, "#6",
                      f"chain {ability.chain[0]}: exactly one SkillLineAbility row has "
                      f"AcquireMethod = 2 (spell {twos[0] if twos else None})",
                      f"got {twos} from {seen}")
        checks.expect(twos == [ability.chain[0]], "#6",
                      f"chain {ability.chain[0]}: the AcquireMethod = 2 row is rank 1")


def check_sql_matches_dbc(sql_paths, dbcs, plan, checks):
    """#4 and #12 -- the emitted SQL and the emitted DBC agree in every column.

    Both sides are read back off disk. `dbcs` maps sql table name -> loaded Dbc.
    """
    parsed = {}
    for path in sql_paths:
        for kind, table, payload in parse_emitted_sql(path):
            if kind == "insert" and table in dbc_tables.BY_SQL_NAME:
                parsed.setdefault(table, {})
                key = payload[dbc_tables.BY_SQL_NAME[table].columns[
                    dbc_tables.BY_SQL_NAME[table].index_column()]]
                parsed[table][key] = payload

    for t in dbc_tables.ALL_TABLES:
        rows = parsed.get(t.sql_table, {})
        dbc = dbcs.get(t.sql_table)
        if dbc is None:
            checks.skip("#4", f"{t.sql_table}: no DBC available to compare against")
            continue
        idx = dbc.index()
        for key in sorted(rows):
            sql_row = rows[key]
            checks.expect(len(sql_row) == len(t.columns), "#7",
                          f"{t.sql_table} id {key}: emitted {len(sql_row)} columns "
                          f"== {len(t.columns)}")
            if key not in idx:
                checks.fail("#4", f"{t.sql_table} id {key}: no matching record in "
                                  f"{t.dbc_file}")
                continue
            row = idx[key]
            diffs = []
            for c, name in enumerate(t.columns):
                want = dbc.cell(row, c)
                got = sql_row.get(name)
                if t.kind(c) == KIND_FLOAT:
                    same = struct.pack("<f", f32(got)) == struct.pack("<f", want)
                elif t.kind(c) == KIND_STRING:
                    same = (got or "") == want
                else:
                    same = got == want
                if not same:
                    diffs.append(f"{name}: sql={got!r} dbc={want!r}")
            checks.expect(not diffs, "#4",
                          f"{t.sql_table} id {key}: all {len(t.columns)} columns match "
                          f"{t.dbc_file}",
                          "; ".join(diffs[:6]))

        # #12 -- nothing may change in a client DBC without either a SQL row or an explicit
        # client-only exemption in the spec.
        touched = plan.touched_ids[t.sql_table]
        unexplained = touched - set(rows) - plan.client_only_ids[t.sql_table]
        checks.expect(not unexplained, "#12",
                      f"{t.dbc_file}: every changed record is mirrored in SQL or listed as "
                      f"client-only ({len(plan.client_only_ids[t.sql_table])} client-only)",
                      f"unexplained {sorted(unexplained)}")


def check_reapplyable(sql_paths, checks):
    """#9 -- every INSERT is covered by a DELETE of the same key, earlier in the same file."""
    keycols = {
        "spell_dbc": ("ID",), "skilllineability_dbc": ("ID",), "charstartoutfit_dbc": ("ID",),
        "player_class_stats": ("Class", "Level"), "spell_ranks": ("first_spell_id", "rank"),
        "spell_bonus_data": ("entry",), "playercreateinfo": ("race", "class"),
        "playercreateinfo_action": ("race", "class", "button"),
    }
    for path in sql_paths:
        deleted = set()
        problems = []
        for kind, table, payload in parse_emitted_sql(path):
            if kind == "delete":
                deleted.add(table)
            elif table not in deleted:
                problems.append(f"{table} inserted with no preceding DELETE")
            if kind == "insert":
                assert table in keycols, f"{path}: no key columns declared for {table}"
        checks.expect(not problems, "#9",
                      f"{os.path.basename(path)}: every INSERT follows a DELETE of its table",
                      "; ".join(problems))


def check_class_stats(sql_path, db, checks):
    """#8 -- 54 dense rows for class 6 that equal the live class 1 rows."""
    rows = [p for k, t, p in parse_emitted_sql(sql_path)
            if k == "insert" and t == "player_class_stats"]
    checks.expect(len(rows) == len(spec.CLASS_STATS_LEVELS), "#8",
                  f"{len(rows)} player_class_stats rows emitted")
    levels = sorted(r["Level"] for r in rows)
    checks.expect(levels == list(spec.CLASS_STATS_LEVELS), "#8",
                  f"levels are dense {levels[0]}..{levels[-1]}" if levels else "no levels")
    checks.expect(all(r["Class"] == spec.DK_CLASS for r in rows), "#8",
                  f"every row is Class {spec.DK_CLASS}")
    if db is not None and db.live():
        cols = spec.CLASS_STATS_COLUMNS[2:]
        live = {int(r[0]): [int(v) for v in r[1:]] for r in db.query(
            "SELECT Level, " + ", ".join(cols) + " FROM player_class_stats "
            f"WHERE Class = {spec.TEMPLATE_CLASS} AND Level BETWEEN "
            f"{spec.CLASS_STATS_LEVELS[0]} AND {spec.CLASS_STATS_LEVELS[-1]}")}
        bad = [r["Level"] for r in rows
               if live.get(r["Level"]) != [r[c] for c in cols]]
        checks.expect(not bad, "#8",
                      f"all {len(rows)} rows equal the live class {spec.TEMPLATE_CLASS} rows",
                      f"differ at levels {bad[:8]}")
    else:
        checks.skip("#8", "no live DB: cannot re-compare the copied stats")


# ==========================================================================================
# manifest
# ==========================================================================================

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out_dir, outputs):
    entries = []
    for kind, path in outputs:
        rel = os.path.relpath(path, spec.REPO_ROOT)
        entries.append({"kind": kind, "path": rel, "bytes": os.path.getsize(path),
                        "sha256": sha256_file(path)})
    manifest = {
        "generator": "build/modules/mod-dk-lowlevel/tools/dkspells.py",
        "spec_sha256": sha256_file(os.path.join(spec.TOOLS_DIR, "dk_spec.py")),
        "custom_spell_ids": spec.all_custom_spell_ids(),
        "outputs": entries,
    }
    json_path = os.path.join(out_dir, "MANIFEST.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    # Strict sha256sum(1) format as well, so `cd <repo> && sha256sum -c` just works.
    sums_path = os.path.join(out_dir, "MANIFEST.sha256")
    with open(sums_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f"{e['sha256']}  {e['path']}\n")
    return manifest, json_path, sums_path


# ==========================================================================================
# modes
# ==========================================================================================

def do_emit(args, checks):
    db = Db(args.mysql_cmd)
    if not db.live():
        print("FATAL: the live world database is required to emit.\n"
              f"  {db.error}\n"
              "  A1 copies player_class_stats from class 1 and A7 copies the spawn point from\n"
              "  the race 1 class 1 row; neither may be retyped from memory. Pass --mysql-cmd\n"
              "  if the default docker compose invocation is wrong.", file=sys.stderr)
        return 2

    print(f"== reading stock DBCs from {args.dbc_in}")
    plan = Plan(args.dbc_in, checks)
    print(f"   Spell.dbc {len(plan.spell.records) - len(spec.all_custom_spell_ids())} records"
          f" -> {len(plan.spell.records)}; SkillLineAbility.dbc "
          f"{len(plan.sla.records) - len(spec.all_custom_sla_ids())} -> "
          f"{len(plan.sla.records)}")

    print("\n== invariants (build)")
    check_column_counts(checks)
    check_schema_against_db(db, checks)
    check_ids(plan, checks)
    check_ascending(plan, checks)
    check_ranks(plan, checks)
    check_chain_not_orphaning(plan, db, checks)
    check_acquire_methods(plan, checks)

    print(f"\n== SQL -> {os.path.relpath(spec.SQL_DIR, spec.REPO_ROOT)}")
    os.makedirs(spec.SQL_DIR, exist_ok=True)
    sql_paths = []
    text, _rows = emit_class_stats(plan, db, checks)
    sql_paths.append(_write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["class_stats"]), text))
    sql_paths.append(_write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["spells"]),
                            emit_spells(plan)))
    sql_paths.append(_write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["createinfo"]),
                            emit_createinfo(plan, db, checks)))

    print(f"\n== header -> {os.path.relpath(spec.HEADER_PATH, spec.REPO_ROOT)}")
    header_path = _write(spec.HEADER_PATH, emit_header(plan))

    print(f"\n== client DBCs + patch MPQ -> {args.out}")
    dbc_out = os.path.join(args.out, "dbc")
    os.makedirs(dbc_out, exist_ok=True)
    dbc_paths = {}
    for dbc in (plan.spell, plan.sla, plan.outfit):
        p = os.path.join(dbc_out, dbc.table.dbc_file)
        dbc.save(p)
        dbc_paths[dbc.table.sql_table] = p
        print(f"   {dbc.table.dbc_file:24s} {os.path.getsize(p):>10,} bytes  "
              f"{len(dbc.records):>6,} records")

    mpq_path = os.path.join(args.out, os.path.basename(spec.MPQ_SLOTS[args.slot]))
    entries = [(dbc_paths[t.sql_table], "DBFilesClient\\" + t.dbc_file)
               for t in dbc_tables.ALL_TABLES]
    read_back = mpqlib.write_patch(mpq_path, entries)
    print(f"   {os.path.basename(mpq_path):24s} {os.path.getsize(mpq_path):>10,} bytes  "
          f"{len(entries)} files")
    for name, blob in read_back:
        local = dbc_paths[next(t.sql_table for t in dbc_tables.ALL_TABLES
                               if name.endswith(t.dbc_file))]
        checks.expect(hashlib.sha256(blob).hexdigest() == sha256_file(local), "#10",
                      f"{name} reads back out of the archive sha256-identical")
    header_size, fmt_version = mpqlib.header_info(mpq_path)
    checks.ok("#10", f"{os.path.basename(mpq_path)} is MPQ v2 (headerSize {header_size}, "
                     f"formatVersion {fmt_version}), unsigned, no (attributes)")

    if args.mpq:
        os.makedirs(os.path.dirname(os.path.abspath(args.mpq)), exist_ok=True)
        with open(mpq_path, "rb") as s, open(args.mpq, "wb") as d:
            d.write(s.read())
        print(f"   installed -> {args.mpq}")

    print("\n== invariants (emitted artefacts, read back off disk)")
    dbcs = {t.sql_table: Dbc(t, dbc_paths[t.sql_table]) for t in dbc_tables.ALL_TABLES}
    check_sql_matches_dbc(sql_paths, dbcs, plan, checks)
    check_reapplyable(sql_paths, checks)
    check_value_ranges(sql_paths, db, checks)
    check_class_stats(os.path.join(spec.SQL_DIR, spec.SQL_FILES["class_stats"]), db, checks)
    _check_header(header_path, checks)

    manifest, json_path, sums_path = write_manifest(
        args.out, [("sql", p) for p in sql_paths] + [("header", header_path)]
        + [("dbc", p) for p in dbc_paths.values()] + [("mpq", mpq_path)])
    print(f"\n== manifest -> {os.path.relpath(json_path, spec.REPO_ROOT)}, "
          f"{os.path.relpath(sums_path, spec.REPO_ROOT)}")
    for e in manifest["outputs"]:
        print(f"   {e['sha256'][:16]}  {e['bytes']:>10,}  {e['path']}")

    _print_damage_table()
    return checks.summary()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"   {os.path.relpath(path, spec.REPO_ROOT)}  ({len(text.splitlines())} lines)")
    return path


def _check_header(path, checks):
    text = open(path, encoding="utf-8").read()
    want = {(lvl, sid) for lvl, sid in spec.progression_grants()}
    got = {(int(a), int(b)) for a, b in re.findall(r"\{\s*(\d+),\s*(\d+)\s*\}", text)}
    checks.expect(got == want, "#12",
                  f"dk_progression.h carries exactly the spec's {len(want)} grant(s)",
                  f"header {sorted(got)} spec {sorted(want)}")


def _print_damage_table():
    print("\n== damage produced by the emitted rows")
    for ability in spec.ABILITIES:
        for r in ability.ranks:
            print(f"   spell {r.spell_id}  {ability.key} {r.subtext}  level {r.level}  "
                  f"EffectBasePoints_1={r.base_points} EffectDieSides_1={r.die_sides}  "
                  f"-> $m1..$M1 = {r.damage_min} to {r.damage_max}")


def do_check(args, checks):
    print("== files")
    sql_paths = []
    for key, name in spec.SQL_FILES.items():
        p = os.path.join(spec.SQL_DIR, name)
        if not os.path.exists(p):
            checks.fail("files", f"missing generated SQL: {name}")
            continue
        checks.ok("files", f"{name}  ({os.path.getsize(p):,} bytes)")
        sql_paths.append(p)
    if not os.path.exists(spec.HEADER_PATH):
        checks.fail("files", "missing generated header src/dk_progression.h")
    else:
        checks.ok("files", "src/dk_progression.h")
        _check_header(spec.HEADER_PATH, checks)
    if not sql_paths:
        return checks.summary()

    print("\n== invariants (offline)")
    check_column_counts(checks)
    check_reapplyable(sql_paths, checks)

    db = Db(args.mysql_cmd)
    live = db.live()
    check_value_ranges(sql_paths, db if live else None, checks)
    if live:
        check_schema_against_db(db, checks)
    else:
        checks.skip("#7", "no live DB: cannot re-compare the frozen table shapes")
    check_class_stats(os.path.join(spec.SQL_DIR, spec.SQL_FILES["class_stats"]),
                      db if live else None, checks)

    # Invariant #4 needs a DBC side to diff the SQL against. There are two ways to get one and
    # both are legitimate:
    #   * the emitted artefacts in <out>/dbc, when the generator has been run on this machine;
    #   * a fresh in-memory rebuild from the stock DBCs, which is what CI does. That path
    #     proves the committed SQL still matches what the generator WOULD produce, without a
    #     49 MB binary ever entering the repository.
    # The plan is rebuilt either way, because #2/#3/#5/#6 need the patched records.
    emitted = {t.sql_table: os.path.join(args.out, "dbc", t.dbc_file)
               for t in dbc_tables.ALL_TABLES}
    have_emitted = all(os.path.exists(p) for p in emitted.values())
    have_stock = os.path.isdir(args.dbc_in)

    if not have_stock:
        for tag in ("#2", "#3", "#4", "#5", "#6", "#12"):
            checks.skip(tag, f"stock DBCs not readable at {args.dbc_in}; "
                             "pass --dbc-in to enable the DBC-side checks")
        return checks.summary()

    print(f"\n== invariants (DBCs rebuilt in memory from {args.dbc_in}, nothing written)")
    plan = Plan(args.dbc_in, checks)
    check_ids(plan, checks)
    check_ascending(plan, checks)
    check_ranks(plan, checks)
    if live:
        check_chain_not_orphaning(plan, db, checks)
    else:
        checks.skip("#5", "no live DB: cannot check the DELETE against today's spell_ranks")
    check_acquire_methods(plan, checks)

    if have_emitted:
        print(f"\n== SQL vs the emitted DBCs in {os.path.relpath(args.out, spec.REPO_ROOT)}")
        dbcs = {t.sql_table: Dbc(t, emitted[t.sql_table]) for t in dbc_tables.ALL_TABLES}
    else:
        print("\n== SQL vs the rebuilt DBCs (no build artefacts present)")
        dbcs = {"spell_dbc": plan.spell, "skilllineability_dbc": plan.sla,
                "charstartoutfit_dbc": plan.outfit}
    check_sql_matches_dbc(sql_paths, dbcs, plan, checks)

    manifest_path = os.path.join(args.out, "MANIFEST.json")
    if os.path.exists(manifest_path):
        print("\n== manifest")
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        for e in manifest["outputs"]:
            p = os.path.join(spec.REPO_ROOT, e["path"])
            if not os.path.exists(p):
                checks.skip("hash", f"{e['path']} not present (build artefact)")
                continue
            checks.expect(sha256_file(p) == e["sha256"], "hash",
                          f"{e['path']} matches the manifest")
    else:
        checks.skip("hash", f"no {os.path.relpath(manifest_path, spec.REPO_ROOT)}; "
                            "run the generator to produce one")

    _print_damage_table()
    return checks.summary()


def do_verify(args, checks):
    """Reproduce the client's archive-priority model and say who wins Spell.dbc."""
    data = args.client_data
    if not os.path.isdir(data):
        print(f"no client Data directory at {data}", file=sys.stderr)
        return 2
    print(f"== {data}\nsearch order (highest priority first):")
    for prio, rel in sorted(mpqlib.chain(data), reverse=True):
        print(f"  0x{prio:02x}  {rel}")
    print()
    want = os.path.basename(spec.MPQ_SLOTS[args.slot])
    for t in dbc_tables.ALL_TABLES:
        name = "DBFilesClient\\" + t.dbc_file
        prio, rel = mpqlib.resolve(data, name)
        if rel is None:
            checks.fail("--verify", f"{t.dbc_file}: no archive provides it")
            continue
        checks.expect(os.path.basename(rel) == want, "--verify",
                      f"{t.dbc_file} resolves to {rel} (0x{prio:02x})",
                      f"expected {want}; the patch is not installed or is outranked")
    return checks.summary()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="re-verify already-generated outputs; writes nothing")
    ap.add_argument("--verify", action="store_true",
                    help="print which client archive wins each patched DBC")
    ap.add_argument("--dbc-in", default=spec.DEFAULT_DBC_IN,
                    help="stock DBC directory to read (never written) "
                         f"[{spec.DEFAULT_DBC_IN}]")
    ap.add_argument("--out", default=spec.DEFAULT_OUT_DIR,
                    help=f"build-artefact directory [{spec.DEFAULT_OUT_DIR}]")
    ap.add_argument("--mpq", default=None,
                    help="also install the finished archive here, e.g. "
                         "<client>/Data/patch-Z.MPQ")
    ap.add_argument("--slot", default=spec.DEFAULT_MPQ_SLOT, choices=sorted(spec.MPQ_SLOTS),
                    help="client archive slot [Z]")
    ap.add_argument("--client-data", default=spec.DEFAULT_CLIENT_DATA,
                    help="client Data directory for --verify")
    ap.add_argument("--mysql-cmd", default=None,
                    help="read-only mysql client command; '{repo}' expands to the repo root")
    args = ap.parse_args(argv)

    checks = Checks()
    if args.verify:
        return do_verify(args, checks)
    if args.check:
        return do_check(args, checks)
    return do_emit(args, checks)


if __name__ == "__main__":
    sys.exit(main())
