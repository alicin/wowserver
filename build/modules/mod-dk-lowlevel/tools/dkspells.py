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
  #15 every race this realm lets a Death Knight be created as has a playercreateinfo row, an
      action bar and a MALE AND FEMALE charstartoutfit_dbc row in the emitted SQL, and none of
      those spawn points is map 609. A race missing from the spec is otherwise silent: it keeps
      its stock rows and produces a level-1 character in Acherus in RequiredLevel 55 plate.
  #16 the per-race template kit is one a level-1 Death Knight can actually wear -- every item
      RequiredLevel <= 1, and at least one melee weapon that clears the proficiency gate at
      PlayerStorage.cpp:2363 -- and the template class is the first entry in
      spec.TEMPLATE_CLASS_PREFERENCE that satisfies that, so the two non-warrior choices are
      re-derived rather than trusted.
  #17 the level ladder: every ability's rank 1 is at the brief's level, ranks are exactly
      RANK_STEP apart, the last one is below the stock rank and no further below it than one
      step, BaseLevel and SpellLevel in the emitted record equal the ladder level, and the
      whole progression table is sorted with every level in 1..80.
  #18 the 55+ handoff: the last custom rank and the first stock rank are ADJACENT in the chain,
      no stock rank gets a spell_dbc override row, and the module itself grants the first stock
      rank at its BaseLevel so the handoff does not depend on mod-learn-spells.
  #19 the curve: minimum and maximum both rise strictly with every rank, the last custom rank is
      strictly weaker than stock rank 1, no rank rounds to zero, and Icy Touch rank 1 is still
      exactly 10-12 -- the one hand-calibrated number, live on a real character.
  #20 rune costs: every stock rank of a cloned ability points at a DIFFERENT SpellRuneCost.dbc
      row, so "the clone keeps the stock cost" is only true because those rows are identical.
      Checked, not assumed.
  #21 the AcquireMethod = 2 set is RE-DERIVED from this realm's playercreateinfo_skills and the
      stock DBC by reproducing learnSkillRewardedSpells' filters, and every row it finds whose
      spell has BaseLevel >= 2 must be flipped by the spec or waived with a reason.
  #22 every cloned stock id is grepped against the pinned core's SpellInfoCorrections.cpp: a
      correction is keyed on the spell id and does NOT survive cloning, so any hit must be baked
      into the clone as cells or explicitly waived.
  #23 every script the live spell_script_names table binds to a chain this feature renumbers is
      re-pointed onto every rank of the new chain. Missing one silently unhooks the script from
      the STOCK ranks too (ObjectMgr.cpp:6377-6381), which is a live-realm regression.
  #24 a mirror chain has exactly as many ranks, at exactly the same levels, as the chain it
      mirrors. spell_dk_threat_of_thassarian looks the off-hand spell up BY THE MAIN-HAND RANK
      NUMBER and SpellMgr::GetSpellWithRank (SpellMgr.cpp:650) follows `node->next->Id` with no
      null check, so a shorter off-hand chain is a worldserver segfault, not a wrong number.
      See MIRROR_CHAINS_WHY in dk_spec.py.
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
import textwrap

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

def _read_spell_rune_costs(path):
    """{id: (blood, unholy, frost, runic power)} from SpellRuneCost.dbc, or {} if absent.

    Five uint32 columns, 475 rows, no strings -- small enough that a dbc_tables entry would be
    more machinery than the one invariant that uses it deserves.
    """
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        blob = f.read()
    magic, rc, fc, rs, _ss = struct.unpack_from("<4sIIII", blob, 0)
    assert magic == b"WDBC" and fc == 5 and rs == 20, f"{path}: unexpected shape {fc}x{rs}"
    out = {}
    for i in range(rc):
        v = struct.unpack_from("<5I", blob, 20 + i * rs)
        out[v[0]] = v[1:]
    return out


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
        # Snapshot BEFORE any edit: invariant #21 needs to know what the stock file said, and
        # _build_sla is about to overwrite six of these in place.
        _am = dbc_tables.SKILLLINEABILITY_DBC.index_of["AcquireMethod"]
        self.stock_sla_acquire_methods = {sla_id: self.sla.cell(row, _am)
                                          for sla_id, row in self.sla.index().items()}
        # SpellRuneCost.dbc is not one of the three tables this feature patches, so it has no
        # entry in dbc_tables. It is read raw, purely so invariant #20 can prove that cloning
        # rank 1's RuneCostID gives every custom rank the stock rune cost.
        self.rune_costs = _read_spell_rune_costs(os.path.join(dbc_in, "SpellRuneCost.dbc"))

        self.sql_rows = {t.sql_table: {} for t in dbc_tables.ALL_TABLES}
        self.client_only_ids = {t.sql_table: set() for t in dbc_tables.ALL_TABLES}
        self.touched_ids = {t.sql_table: set() for t in dbc_tables.ALL_TABLES}

        self._build_spells()
        self._build_sla()
        self._build_outfits()
        self._build_ranks()

    # ---------------------------------------------------------------- Spell.dbc (A3/A11) --
    def stock_cell(self, ability, column):
        """A named cell of the ability's clone source, read out of the stock DBC."""
        return self.spell.cell(self.spell.index()[ability.clone_from],
                               dbc_tables.SPELL_DBC.index_of[column])

    def rank_overrides(self, ability, rank):
        """Every cell a custom rank overrides on its clone source, and its value.

        The scaled values are computed HERE, from the stock record, and never appear in
        dk_spec.py -- which is the whole reason the curve is a function of the stock cell rather
        than a table of numbers. A Spell.dbc that disagrees with the spec is not possible; the
        spec has nothing to disagree with.
        """
        out = {name: get(rank, ability)
               for name, get in spec.FIXED_OVERRIDE_COLUMNS.items()}
        for cell in ability.scaling:
            base = self.stock_cell(ability, cell.base_points)
            die = self.stock_cell(ability, cell.die_sides)
            # INVARIANT #24, inline: the spec's weapon_flat flag must agree with what
            # Spell.dbc actually says the effect is. The flag picks which power curve applies,
            # and getting it wrong is silent -- the numbers just come out at roughly double or
            # half. Deriving the truth here means the spec cannot drift from the DBC.
            eff_index = cell.base_points.rsplit("_", 1)[1]
            eff_type = self.stock_cell(ability, f"Effect_{eff_index}")
            is_weapon = eff_type in spec.WEAPON_DAMAGE_EFFECTS
            if is_weapon != cell.weapon_flat:
                raise SystemExit(
                    f"[FAIL] #24 {ability.key} {cell.base_points}: Effect_{eff_index}="
                    f"{eff_type} says weapon_flat={is_weapon}, spec says {cell.weapon_flat}")
            out[cell.base_points], out[cell.die_sides] = spec.scale_cell(
                base, die, rank.level, ability.handoff_level, cell.weapon_flat)
        out.update(ability.extra_overrides)
        return out

    @staticmethod
    def cell_range(base_points, die_sides):
        """($m, $M) -- the low and high value CalcValue can produce from a cell pair."""
        if die_sides == 0:
            return base_points, base_points
        return base_points + 1, base_points + die_sides

    def rank_ranges(self, ability, rank):
        """[(ScalingCell, low, high)] for one custom rank, for comments and invariant #19."""
        ov = self.rank_overrides(ability, rank)
        return [(c,) + self.cell_range(ov[c.base_points], ov[c.die_sides])
                for c in ability.scaling]

    def stock_ranges(self, ability):
        return [(c,) + self.cell_range(self.stock_cell(ability, c.base_points),
                                       self.stock_cell(ability, c.die_sides))
                for c in ability.scaling]

    def rank_summary(self, ability, rank):
        """'10-12 Frost damage', or the multi-cell form. Comment text only."""
        parts = []
        for cell, lo, hi in self.rank_ranges(ability, rank):
            parts.append(f"{lo} {cell.what}" if lo == hi else f"{lo}-{hi} {cell.what}")
        return ", ".join(parts)

    def _build_spells(self):
        table = dbc_tables.SPELL_DBC
        idx = self.spell.index()

        # #13: the five original overrides must land where DESIGN.md 3.3 says they do.
        for name, want in spec.DOCUMENTED_OVERRIDE_INDICES.items():
            got = table.index_of[name]
            self.checks.expect(got == want, "#13",
                               f"spell override column {name} is at format index {got}",
                               f"DESIGN.md documents {want}")

        self.overrides = {}                 # spell id -> {column: value}
        for ability in spec.ABILITIES:
            src_row = idx[ability.clone_from]
            # #17 (spec half): the declared handoff level must be the stock record's own
            # BaseLevel. It is the number the whole rank ladder is built from -- get it wrong and
            # every custom rank of that ability is at the wrong level with no other symptom.
            # A mirror chain has BaseLevel 0 (it is cast, never learned) and takes its levels
            # from the ability it mirrors; #24 checks that instead.
            if ability.learnable:
                self.checks.expect(
                    self.stock_cell(ability, "BaseLevel") == ability.handoff_level, "#17",
                    f"{ability.key}: handoff level {ability.handoff_level} is "
                    f"{ability.clone_from}'s own Spell.dbc BaseLevel",
                    f"BaseLevel is {self.stock_cell(ability, 'BaseLevel')}")
            # Horn of Winter's baked SpellInfoCorrections values assume the stock cell is what
            # the core's `|=` was applied to. Assert the premise rather than the conclusion.
            for name, value in ability.extra_overrides.items():
                stock = self.stock_cell(ability, name)
                self.checks.expect(
                    stock != value, "#22",
                    f"{ability.key}: extra override {name} = {value} actually changes the clone "
                    f"(stock {stock})",
                    "the override is a no-op; the correction it mirrors has moved or is stale")

            for rank in ability.ranks:
                row = self.spell.clone_row(src_row)
                before = bytes(self.spell.records[row])
                overrides = self.rank_overrides(ability, rank)
                self.overrides[rank.spell_id] = overrides
                for col_name, value in overrides.items():
                    self.spell.set_cell(row, table.index_of[col_name], value)
                # Setting the subtext to the value the clone already carries must not move a
                # single byte -- add_string() reuses the existing NUL-bounded string. Asserted
                # rather than assumed, which is why rank 1 stays exactly as many cells from its
                # clone source as the override list says.
                subtext_col = table.index_of[spec.SUBTEXT_COLUMN]
                offset_before = self.spell.get_u32(row, subtext_col)
                self.spell.set_cell(row, subtext_col, rank.subtext)
                self.checks.expect(
                    self.spell.get_str(row, subtext_col) == rank.subtext, "#13",
                    f"spell {rank.spell_id} NameSubtext resolves to {rank.subtext!r}")
                budget = 4 * (len(overrides)
                              + (0 if self.spell.get_u32(row, subtext_col) == offset_before
                                 else 1))
                changed = sum(1 for a, b in zip(before, bytes(self.spell.records[row]))
                              if a != b)
                self.checks.expect(
                    changed <= budget, "#13",
                    f"spell {rank.spell_id} is a clone of {ability.clone_from} with "
                    f"{len(overrides)} cell override(s) -- {self.rank_summary(ability, rank)}",
                    f"{changed} bytes differ, budget {budget}")
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
        for ability in spec.LEARNABLE_ABILITIES:
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

        # The AcquireMethod flips. Module-level rather than per-ability: the set is derived from
        # this realm's creation data (see STOCK_SLA_FLIPS in dk_spec.py), and two of the six --
        # Blood Presence and Death Grip -- belong to abilities that have no custom ranks at all,
        # so there is no ability to hang them off.
        for sla_id, edits in sorted(spec.STOCK_SLA_EDITS.items()):
            row = idx[sla_id]
            # Every other field is copied verbatim by virtue of editing the parsed record
            # in place -- there is no re-authoring step that could drop one.
            for name, value in edits.items():
                self.sla.set_cell(row, table.index_of[name], value)
            self.sql_rows["skilllineability_dbc"][sla_id] = self.sla.row_values(row)
            self.touched_ids["skilllineability_dbc"].add(sla_id)

    # ------------------------------------------------------- CharStartOutfit.dbc (A8/A13) --
    def outfit_items(self, outfit_id):
        """The positive ItemID_* cells of one CharStartOutfit row, in file order."""
        table = dbc_tables.CHARSTARTOUTFIT_DBC
        row = self.outfit.index()[outfit_id]
        ids = (self.outfit.cell(row, table.index_of[f"ItemID_{k}"]) for k in range(1, 25))
        return [i for i in ids if i > 0]

    def _index_outfits_by_key(self):
        """(RaceID, ClassID, SexID) -> outfit row id.

        The same key GetCharStartOutfitEntry builds at DBCStores.cpp:880
        (`race | class_ << 8 | gender << 16`). Resolving the row ids this way rather than
        listing them is what makes the race table a list of races instead of a list of
        magic numbers -- and it is the only way to be sure the ids are right, because the
        DK block is not contiguous (races 6 and 7 are 348-351, races 1-5/8/10/11 are
        352-367).
        """
        table = dbc_tables.CHARSTARTOUTFIT_DBC
        cols = [table.index_of[n] for n in ("RaceID", "ClassID", "SexID")]
        id_col = table.index_column()
        out = {}
        for row in range(len(self.outfit.records)):
            key = tuple(self.outfit.cell(row, c) for c in cols)
            # sCharStartOutfitMap is a std::map, so a second row with the same key would be
            # silently unreachable and this generator would be patching a record the server
            # never reads. The stock file has no duplicates; refuse to guess if that changes.
            assert key not in out, f"duplicate CharStartOutfit key race/class/sex {key}"
            out[key] = self.outfit.cell(row, id_col)
        return out

    def _build_outfits(self):
        table = dbc_tables.CHARSTARTOUTFIT_DBC
        idx = self.outfit.index()
        key_cols = {table.index_of[n] for n in spec.OUTFIT_KEY_COLUMNS}
        id_col = table.index_column()
        self.outfit_by_key = self._index_outfits_by_key()
        # [(race id, sex, dk outfit id, template outfit id)], the emit order for A8.
        self.start_outfits = []
        for race in spec.DK_RACES:
            for sex in spec.OUTFIT_SEXES:
                dk_key = (race.race_id, spec.DK_CLASS, sex)
                tpl_key = (race.race_id, race.template_class, sex)
                missing = [k for k in (dk_key, tpl_key) if k not in self.outfit_by_key]
                if not self.checks.expect(
                        not missing, "#15",
                        f"CharStartOutfit has a {race.name} DK row and a "
                        f"{race.template_class_name} template row for sex {sex}",
                        f"missing race/class/sex {missing}"):
                    continue
                dk_id = self.outfit_by_key[dk_key]
                template_id = self.outfit_by_key[tpl_key]
                self.start_outfits.append((race.race_id, sex, dk_id, template_id))
                dst, src = idx[dk_id], idx[template_id]
                keys_before = {c: self.outfit.cell(dst, c) for c in key_cols}
                for c in range(len(table.columns)):
                    if c == id_col or c in key_cols:
                        continue      # keep the DK row's own race/class/sex/outfit
                    self.outfit.set_cell(dst, c, self.outfit.cell(src, c))
                keys_after = {c: self.outfit.cell(dst, c) for c in key_cols}
                self.checks.expect(
                    keys_before == keys_after, "#11",
                    f"CharStartOutfit {dk_id} keeps race/class/sex/outfit "
                    f"{[keys_after[table.index_of[n]] for n in spec.OUTFIT_KEY_COLUMNS]}")
                arrays_match = all(self.outfit.cell(dst, c) == self.outfit.cell(src, c)
                                   for c in range(len(table.columns))
                                   if c != id_col and c not in key_cols)
                self.checks.expect(
                    arrays_match, "#11",
                    f"CharStartOutfit {dk_id} item arrays copied from {template_id} "
                    f"({race.name} {race.template_class_name})")
                self.sql_rows["charstartoutfit_dbc"][dk_id] = self.outfit.row_values(dst)
                self.touched_ids["charstartoutfit_dbc"].add(dk_id)

    # ----------------------------------------------------- spell_ranks / bonus / scripts --
    def _build_ranks(self):
        self.spell_ranks = []
        self.spell_bonus = []
        self.rank_deletes = []
        # [(ScriptName, negative stock row to remove, [spell ids to bind])]
        self.script_binds = []
        for ability in spec.ABILITIES:
            chain = ability.chain
            first = chain[0]
            self.rank_deletes.append((ability.stock_chain[0], first, chain))
            for i, sid in enumerate(chain, start=1):
                self.spell_ranks.append((first, sid, i))
            if ability.bonus is not None:
                for rank in ability.ranks:
                    self.spell_bonus.append((rank.spell_id,) + ability.bonus)
            for script in ability.scripts:
                self.script_binds.append((script, -ability.stock_chain[0], list(chain)))


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


def _spell_column_notes(plan, spell_id):
    """Trailing `-- why` notes on the cells a reviewer must be able to check at a glance.

    Every one of these is a cell that looks arbitrary and is not; the rest of the 234 are
    verbatim clone output and are noise if annotated. The scaled cells get their resolved
    tooltip value spelled out, because "EffectBasePoints_1 = 61" is not something anyone can
    check and "$m1 = 62" against a tooltip is.
    """
    ability = spec.ability_by_spell_id(spell_id)
    rank = spec.rank_by_spell_id(spell_id)
    notes = {
        "ID": f"custom block {spec.SPELL_ID_BASE}-{spec.SPELL_ID_MAX - 1}, above Spell.dbc's "
              f"max 80864 and below AC's own 100001",
        "BaseLevel": "learn level; also mod-learn-spells' filter",
        "SpellLevel": "damage scaling level",
        "SpellClassSet": "15 SPELLFAMILY_DEATHKNIGHT (SharedDefines.h:3799) -- cloned, and the "
                         "only reason talents and glyphs still see this rank",
        "SpellClassMask_1": "cloned; SpellInfo::IsAffected matches talents/procs on this",
        "RuneCostID": f"cloned from {ability.clone_from if ability else '?'}; every stock rank "
                      f"of this ability shares the same SpellRuneCost values (invariant #20)",
    }
    if ability and rank:
        for cell, lo, hi in plan.rank_ranges(ability, rank):
            notes[cell.base_points] = (f"$m = {lo}" if lo == hi
                                       else f"$m = BasePoints + 1 = {lo}")
            if plan.rank_overrides(ability, rank)[cell.die_sides] > 1:
                notes[cell.die_sides] = f"$M = BasePoints + DieSides = {hi}"
        for name in ability.extra_overrides:
            notes[name] = "SpellInfoCorrections.cpp bake -- see HORN_OF_WINTER in dk_spec.py"
    return notes


def emit_spells(plan):
    """A3 spell_dbc, A4 skilllineability_dbc, A5 spell_ranks, A6 spell_bonus_data."""
    parts = [BANNER.format(name=spec.SQL_FILES["spells"])]

    # ---- A3 -----------------------------------------------------------------------------
    spell_ids = sorted(plan.sql_rows["spell_dbc"])
    ability_table = "".join(
        f"--   {a.name:<24} {len(a.ranks)} ranks at levels "
        f"{', '.join(str(l) for l in a.rank_levels)}, then stock {a.stock_chain[0]}"
        + (f" at {a.handoff_level}\n" if a.learnable
           else f"\n--   {'':<24} NEVER LEARNED -- rank-count mirror of "
                f"{a.mirror_of}, see MIRROR_CHAINS_WHY\n")
        for a in spec.ABILITIES)
    parts.append(f"""--
-- A3. spell_dbc -- {len(spell_ids)} rows, {len(dbc_tables.SPELL_DBC)} columns each,
-- {len(spec.ABILITIES)} abilities.
--
{ability_table}--
-- Each row is a byte-for-byte clone of that ability's stock rank 1 with a handful of cells
-- overridden -- ID, BaseLevel, SpellLevel, NameSubtext and the cells Blizzard themselves
-- re-rank. Cloning is what keeps the ability behaving like a Death Knight ability:
-- SpellClassSet / SpellClassMask carry every talent and proc interaction, EffectTriggerSpell
-- carries the diseases, SpellIconID carries the Sigil of the Frozen Conscience correction, and
-- RuneCostID carries the rune cost. None of those is keyed on the spell id anywhere in the
-- core, so an authored row would lose all of them silently.
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
                                 _spell_column_notes(plan, sid)))

    # ---- A4 -----------------------------------------------------------------------------
    sla_ids = sorted(plan.sql_rows["skilllineability_dbc"])
    new_ids = set(spec.all_custom_sla_ids())
    flip_table = "".join(
        f"--   {sla_id} -> spell {sp:<6} {name:<16} {why}\n"
        for sla_id, (sp, name, why) in sorted(spec.STOCK_SLA_FLIPS.items()))
    parts.append(f"""--
-- A4. skilllineability_dbc -- {len(sla_ids)} rows, {len(dbc_tables.SKILLLINEABILITY_DBC)} columns each.
--
-- One new row per custom rank, plus {len(spec.STOCK_SLA_EDITS)} OVERRIDES of stock rows. Those
-- overrides are not optional and they are the least obvious thing in this whole feature: stock
-- 16231 is (16231, 771, 45477, 0, 32, 0, 0, 1, 49896, 2, 0, 0, 0, 0), and AcquireMethod = 2
-- means learnSkillRewardedSpells grants the LEVEL 55 Icy Touch the moment a Death Knight
-- acquires skill 771 -- which happens at character creation. Leave it and every new DK starts
-- with a 127-137 damage nuke and the feature is silently defeated. The set is derived from the
-- live database, not guessed; see STOCK_SLA_FLIPS and AM2_WAIVERS in tools/dk_spec.py and
-- invariant #21.
--
{flip_table}--
-- At most one row per supercede chain may carry AcquireMethod = 2: Player.cpp:12284-12300
-- sets skipCurrent when the SUPERSEDING row is also 2, so two would grant the higher rank. A
-- chain gets its one 2 only when its rank 1 is a LEVEL 1 ability, because AcquireMethod 2 grants
-- at character creation and there is no level field on SkillLineAbility to say otherwise --
-- so Icy Touch, Plague Strike and Blood Strike have one and the other five have none, and their
-- rank 1 comes from the module's Reconcile() instead. Everything above rank 1 is 0, which is
-- also mod-learn-spells' filter (mod_learnspells.cpp:446).
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
-- A5. spell_ranks -- {len(spec.ABILITIES)} chains, RENUMBERED.
--
-- SpellMgr::LoadSpellRanks (SpellMgr.cpp:1279-1388) is the only chain mechanism at this
-- revision: there is no spell_chain table, and SkillLineAbility.SupercededBySpell is not used
-- to build chains. It requires a DENSE 1..N sequence and treats first_spell_id AS the rank 1
-- spell, so inserting below rank 1 means renumbering the whole chain -- first_spell_id
-- becomes {chains}. A gap makes it `continue` with only an sql.sql log line, and the chain
-- silently disappears: in game that is one Icy Touch button per rank, with no supersession.
--
-- It is also what the A16 script rebind below depends on, and what puts a character on stock
-- Blizzard data at the handoff: the last custom rank of each chain is immediately followed by
-- that ability's stock rank 1, so Player::addSpell supersedes the custom rank the moment the
-- stock one is learned.
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
    with_bonus = ", ".join(a.name for a in spec.ABILITIES if a.bonus is not None)
    without = ", ".join(a.name for a in spec.ABILITIES if a.bonus is None)
    parts.append(f"""--
-- A6. spell_bonus_data for the new ranks -- {len(bonus_ids)} rows.
--
-- SpellMgr::GetSpellBonusData (SpellMgr.cpp:947-961) falls back to the FIRST spell in the chain
-- when a spell has no row of its own, and renumbering makes a custom rank the first spell. That
-- cuts both ways, so the rule is: an ability whose stock ranks all carry explicit rows must give
-- its custom ranks explicit rows too, and an ability with no rows anywhere must not acquire one.
--
--   rows emitted : {with_bonus}
--   no rows      : {without}
--
-- Values are copied verbatim from that ability's stock rank 1 row, which is where the two
-- coefficients below came from. Every stock rank of both abilities already has its own row, so
-- renumbering first_spell_id cannot disturb them.""")
    parts.append("DELETE FROM `spell_bonus_data` WHERE `entry` IN ("
                 + ", ".join(str(i) for i in bonus_ids) + ");")
    parts.append(_insert_values(
        "spell_bonus_data",
        ("entry", "direct_bonus", "dot_bonus", "ap_bonus", "ap_dot_bonus", "comments"),
        plan.spell_bonus))

    # ---- A16 ----------------------------------------------------------------------------
    def _stock_of(script):
        return next(a.stock_chain for a in spec.ABILITIES if script in a.scripts)

    if plan.script_binds:
        rows, deletes = [], []
        for script, negative, chain in plan.script_binds:
            deletes.append((script, [negative] + chain))
            rows.extend((sid, script) for sid in chain)
        listing = "".join(
            f"--   {script:<28} was one row {negative}, now {len(chain)} rows: "
            f"custom {chain[0]}-{chain[len(chain) - len(_stock_of(script)) - 1]} "
            f"plus stock {', '.join(str(s) for s in _stock_of(script))}\n"
            for script, negative, chain in plan.script_binds)
        parts.append(f"""--
-- A16. spell_script_names -- re-point the scripts of every RENUMBERED chain.
--
-- THE MOST DANGEROUS ROW IN THIS FILE IF IT IS MISSING. `spell_id < 0` means "this script, for
-- every rank of this chain", and ObjectMgr::LoadSpellScriptNames (ObjectMgr.cpp:6377-6390) is:
--
--     if (sSpellMgr->GetFirstSpellInChain(spellId) != uint32(spellId)) {{ LOG_ERROR(...); continue; }}
--     while (spellInfo) {{ insert(spellInfo->Id, script); spellInfo = spellInfo->GetNextRankSpell(); }}
--
-- A5 above moves the first spell of four chains. The instant it does, the stock negative row
-- fails that test and the script is dropped for EVERY rank -- including the level-80 ones the
-- Death Knights already on this realm cast. Death Coil's Effect_1 is SPELL_EFFECT_DUMMY and the
-- script is the only thing that turns it into damage, so the failure mode is a spell that costs
-- runic power and does nothing, with one line in sql.sql at boot.
--
{listing}--
-- One POSITIVE row per spell rather than one negative row for the new chain head, deliberately.
-- This feature ships behind a config flag and is expected to be toggled: if its SQL is ever
-- rolled back while these rows are not, a negative row would point at a spell that no longer
-- exists and take all the stock ranks down with it. Positive rows fail one spell at a time.
--
-- The DELETE names both the ScriptName and the exact spell ids this generator owns, so it
-- cannot touch the other rows these scripts have (52212 for Death and Decay's trigger, 52375
-- and -62900 for Death Coil's talent chain).""")
        for script, ids in deletes:
            parts.append(f"DELETE FROM `spell_script_names` WHERE `ScriptName` = "
                         f"{sql_str(script)} AND `spell_id` IN ("
                         + ", ".join(str(i) for i in ids) + ");")
        parts.append(_insert_values("spell_script_names", ("spell_id", "ScriptName"),
                                    sorted(rows)))

    return "\n\n".join(parts) + "\n"


def emit_createinfo(plan, db, checks):
    """A7 playercreateinfo, A8 charstartoutfit_dbc, A9 action bar, A10 cast spell.

    All four are emitted for EVERY Death-Knight-capable race, from spec.DK_RACES. Nothing in
    here is race 1 specific any more; the Human rows it produces are byte-identical to the ones
    the Human-only slice produced, which is the regression test for this generalisation.
    """
    spawn, race_notes = {}, []
    for race in spec.DK_RACES:
        src = db.query(
            "SELECT map, zone, CAST(position_x AS DOUBLE), CAST(position_y AS DOUBLE), "
            "CAST(position_z AS DOUBLE), CAST(orientation AS DOUBLE) FROM playercreateinfo "
            f"WHERE race = {race.race_id} AND class = {race.template_class}")
        checks.expect(len(src) == 1, "A7",
                      f"read the race {race.race_id} ({race.name}) class "
                      f"{race.template_class} ({race.template_class_name}) spawn point "
                      "from the live DB")
        assert len(src) == 1, (
            f"no playercreateinfo row for race {race.race_id} class {race.template_class} to "
            "copy the spawn point from")
        map_id, zone_id = int(src[0][0]), int(src[0][1])
        # CAST(... AS DOUBLE) hands back the exact double value of the stored float32; f32_text
        # then finds the shortest decimal that reproduces those same 32 bits.
        pos = [f32(float(v)) for v in src[0][2:]]
        for text, value in zip((f32_text(v) for v in pos), pos):
            assert struct.pack("<f", float(text)) == struct.pack("<f", value)
        # The whole point of A7 is being somewhere that is not Ebon Hold. Asserting that
        # directly is stronger than hardcoding a destination map, and it survives a template
        # class change.
        checks.expect(map_id != spec.FORBIDDEN_CREATE_MAP, "A7",
                      f"race {race.race_id} {race.name} spawns on map {map_id} zone {zone_id}, "
                      f"not {spec.FORBIDDEN_CREATE_MAP} (Ebon Hold): "
                      + " ".join(f32_text(v) for v in pos))
        spawn[race.race_id] = (map_id, zone_id, pos)
        race_notes.append(
            f"--   {race.race_id:>2} {race.name:<10} <- class {race.template_class} "
            f"{race.template_class_name:<8} map {map_id:>3} zone {zone_id:>4}")
        # The two non-warrior templates carry their reason inline. Wrapped rather than left as
        # one long line so the migration stays readable in a terminal-width diff.
        race_notes.extend(f"--                 {line}"
                          for line in textwrap.wrap(race.why, 74))

    parts = [BANNER.format(name=spec.SQL_FILES["createinfo"])]

    race_list = ", ".join(str(r.race_id) for r in spec.DK_RACES)
    parts.append("""--
-- A7. Spawn every Death Knight in their own race's starting zone instead of Acherus.
--
-- These rows do three jobs each. They make the entire Death Knight starter chain unreachable
-- (every questgiver for quests 12593..12801 spawns only on map 609, there are zero
-- areatrigger_teleport rows targeting 609, and every chain quest is MinLevel 55, so nothing
-- has to be deleted or disabled); they keep Player::CalculateTalentsPoints on its normal
-- branch instead of the map-609 branch that refunds every talent point; and they set the
-- homebind (PlayerStorage.cpp:7187-7191).
--
-- Map, zone AND coordinates are copied from that race's own template row in this realm's
-- playercreateinfo -- never typed in -- and the floats are printed at the shortest precision
-- that reproduces the stored float32 exactly. Warrior is the template everywhere it exists and
-- its kit is usable; the two exceptions are derived, not chosen, and re-derived by invariant
-- #16 on every run:
--
--   race  name       template                 destination
"""
                 + "\n".join(race_notes) + """
--
-- DELETE + INSERT rather than UPDATE: an UPDATE against a missing row succeeds and does
-- nothing, which is the failure mode this whole feature cannot afford.

DELETE FROM `playercreateinfo` WHERE `class` = """ + str(spec.DK_CLASS)
                 + f" AND `race` IN ({race_list});\n"
                 + _insert_values(
                     'playercreateinfo',
                     ('race', 'class', 'map', 'zone', 'position_x', 'position_y', 'position_z',
                      'orientation'),
                     [[r.race_id, spec.DK_CLASS, spawn[r.race_id][0], spawn[r.race_id][1]]
                      + spawn[r.race_id][2] for r in spec.DK_RACES]))

    template_by_dk = {dk_id: (race_id, sex, tpl_id)
                      for race_id, sex, dk_id, tpl_id in plan.start_outfits}
    outfit_ids = sorted(plan.sql_rows["charstartoutfit_dbc"])
    n_out, n_races = len(outfit_ids), len(spec.DK_RACES)
    n_cols = len(dbc_tables.CHARSTARTOUTFIT_DBC)
    parts.append(f"""--
-- A8. charstartoutfit_dbc -- {n_out} rows ({n_races} races x male/female), {n_cols} columns each.
--
-- The starting kit comes from CharStartOutfit.dbc, not from playercreateinfo_item. The one
-- existing DK row there, (0, 6, 40582, -1), is a REMOVAL directive: negative counts route
-- into PlayerCreateInfoAddItemHelper (ObjectMgr.cpp:4311-4343, 4482-4502) which zeroes that
-- itemId inside the CharStartOutfit entry. Doing this as eighteen negative rows plus a
-- positive kit would log an error per miss; overriding the outfit row is cleaner.
--
-- Every stock class-6 row is the SAME kit regardless of race: eighteen items, every 346xx
-- piece RequiredLevel 55 plate. Each is replaced by that race's own template kit, whose
-- weapon a level-1 Death Knight is proficient with -- checked item by item against
-- PlayerStorage.cpp:2363 by invariant #16, not assumed.
--
-- Row ids are resolved out of the DBC by (RaceID, ClassID, SexID), the key
-- GetCharStartOutfitEntry uses at DBCStores.cpp:880, because the DK block is not contiguous:
-- Tauren and Gnome are 348-351, everyone else is 352-367.
--
-- RaceID/ClassID/SexID/OutfitID are NOT copied; the DK rows already carry the right ones. Only
-- the ItemID / DisplayItemID / InventoryType arrays move. Note that DisplayItemID and
-- InventoryType are `x` (FT_NA) in CharStartOutfitEntryfmt: the server discards them, the
-- client character-create preview uses them, and they still occupy a required SQL column.""")
    for oid in outfit_ids:
        race_id, sex, tpl_id = template_by_dk[oid]
        race = spec.race_by_id(race_id)
        parts.append(f"DELETE FROM `charstartoutfit_dbc` WHERE `ID` = {oid};   "
                     f"-- {race.name} {'female' if sex else 'male'}, copied from stock outfit "
                     f"{tpl_id} ({race.template_class_name})")
        parts.append(_insert_set("charstartoutfit_dbc",
                                 dbc_tables.CHARSTARTOUTFIT_DBC.columns,
                                 plan.sql_rows["charstartoutfit_dbc"][oid]))

    rank1 = spec.ABILITIES[0].ranks[0]
    action_rows = [[r.race_id, spec.DK_CLASS, b, a, t]
                   for r in spec.DK_RACES for b, a, t in spec.action_bar_for(r)]
    racial_notes = "\n".join(
        f"--   {r.race_id:>2} {r.name:<10} button {r.racial_button:>2}  "
        f"{r.racial_spell:>5}  {r.racial_name}" for r in spec.DK_RACES)
    btn = spec.ACTION_BUTTON_RANK1
    dmg = plan.rank_summary(spec.ABILITIES[0], rank1)
    parts.append(f"""--
-- A9. Action bar for a new Death Knight of each race -- {len(action_rows)} rows.
--
-- Button {btn} holds the custom rank ({rank1.spell_id}), so the acceptance test -- hover it
-- and read "{dmg}" -- needs no setup. The stock rows handed out
-- 45477/45462/45902/47541/49576, all level 55 abilities the character will not know.
-- {spec.ATTACK_SPELL} is Attack. The third button is the race's own racial, on the slot and
-- with the spell Blizzard shipped for that race's Death Knight; the slot is not uniform:
--
{racial_notes}

DELETE FROM `playercreateinfo_action` WHERE `class` = {spec.DK_CLASS} AND `race` IN ({race_list});
{_insert_values('playercreateinfo_action', ('race', 'class', 'button', 'action', 'type'),
                action_rows)}""")

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
    entries = spec.progression_entries()
    lines = []
    for level, sid, kind, comment in entries:
        detail = ""
        if kind == spec.GRANT_CUSTOM:
            ability = spec.ability_by_spell_id(sid)
            detail = " -- " + plan.rank_summary(ability, spec.rank_by_spell_id(sid))
        lines.append(f"    {{ {level:>2}, {sid} }},   // {comment}{detail}")
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
//
// THREE KINDS OF ENTRY, ALL learnSpell(id) TO THE MODULE:
//
//   90xxx  a generated low rank -- a byte-clone of the stock rank 1 with its damage/heal/stat
//          cells scaled to the level, and a spell_ranks row placing it below the stock ranks.
//   stock  an ability with nothing to scale (a percentage, a taunt, a summon that scales to its
//          owner). Blizzard's own record, unmodified, granted early.
//   stock  at 55-65: the FIRST stock rank of a re-ranked ability. This is the handoff. Granting
//          it here rather than leaving it to mod-learn-spells is what makes "from 55 you are on
//          stock Blizzard data" a property of this module instead of a dependency on another
//          one (DESIGN.md 4). Stock ranks ABOVE the first are deliberately absent: how a Death
//          Knight gets Icy Touch rank 11 at 61 is unchanged by this feature.
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
        if tuple(walk) == ability.stock_chain:
            checks.ok("#5", f"chain {ability.chain[0]}: stock ranks match the "
                            f"SkillLineAbility supercede links {walk}")
        else:
            # Horn of Winter is the exception and it is Blizzard's, not ours: SLA row 19674 has
            # SupercededBySpell = 0 even though 57623 is plainly its rank 2 (subtexts "Rank 1"
            # and "Rank 2", BaseLevel 65 and 75, and the live spell_ranks table chains them).
            # So this source is unusable for that ability; say so out loud and let
            # check_chain_against_live_ranks do the grounding instead of quietly passing.
            checks.expect(
                len(walk) == 1 and walk[0] == ability.clone_from, "#5",
                f"chain {ability.chain[0]} ({ability.name}): stock SkillLineAbility rows carry "
                f"no supercede links, so the chain is ground-truthed against live spell_ranks "
                f"instead",
                f"partial walk {walk}, spec says {list(ability.stock_chain)} -- a link exists "
                f"but disagrees, which is worse than none at all")


def check_chain_not_orphaning(plan, db, checks):
    """#5 (live half) -- the DELETE must not strand a spell that has a rank row today.

    Also the ONLY ground truth left for an ability whose stock SkillLineAbility rows carry no
    supercede links (Horn of Winter), so it checks the shape of the live chain, not just that
    nothing is orphaned by it.
    """
    for ability in spec.ABILITIES:
        old_first = ability.stock_chain[0]
        rows = db.query("SELECT spell_id FROM spell_ranks "
                        f"WHERE first_spell_id = {old_first} ORDER BY `rank`")
        existing_order = tuple(int(r[0]) for r in rows)
        existing = set(existing_order)
        orphaned = existing - set(ability.chain)
        checks.expect(not orphaned, "#5",
                      f"chain {old_first}: all {len(existing)} spells that have a rank row "
                      f"today are still in the renumbered chain",
                      f"would be orphaned by the DELETE: {sorted(orphaned)}")
        # An empty result means this chain has already been renumbered by a previous run of this
        # generator, which is the steady state on a live realm -- not a failure.
        if existing_order:
            checks.expect(existing_order == ability.stock_chain, "#5",
                          f"chain {old_first} ({ability.name}): the live spell_ranks chain is "
                          f"exactly the stock chain the spec declares",
                          f"live {list(existing_order)} spec {list(ability.stock_chain)}")
        else:
            head = ability.chain[0]
            live = tuple(int(r[0]) for r in db.query(
                f"SELECT spell_id FROM spell_ranks WHERE first_spell_id = {head} "
                "ORDER BY `rank`"))
            checks.expect(set(ability.stock_chain) <= set(live) or not live, "#5",
                          f"chain {old_first} ({ability.name}): already renumbered under "
                          f"{head}; every stock rank is still in the live chain",
                          f"live chain under {head} is {list(live)}")


def check_acquire_methods(plan, checks):
    """#6 -- at most one AcquireMethod = 2 per chain, on rank 1, and only if rank 1 is level 1.

    Two rows with AcquireMethod = 2 in one chain would grant the HIGHER rank
    (Player.cpp:12284-12300 sets skipCurrent when the superseding row is also 2). Zero rows is
    legitimate and is the common case here: AcquireMethod 2 fires at CHARACTER CREATION with no
    level test anywhere in learnSkillRewardedSpells, so an ability that starts at level 2 or
    later must not have one at all and is granted by the module's Reconcile() instead.
    """
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
        want = ([ability.chain[0]]
                if ability.learnable and ability.ranks[0].level == 1 else [])
        checks.expect(twos == want, "#6",
                      f"chain {ability.chain[0]} ({ability.name}, rank 1 at level "
                      f"{ability.ranks[0].level}): AcquireMethod = 2 rows are {twos or 'none'}",
                      f"expected {want or 'none'} from {seen}")


def check_acquire_method_derivation(plan, db, checks):
    """#21 -- re-derive, from the live realm, every spell a DK is handed at character creation.

    THE CHECK THAT STOPS THE FEATURE BEING SILENTLY POINTLESS. Reproduces
    Player::learnSkillRewardedSpells (Player.cpp:12237-12311) against the stock DBC and this
    realm's playercreateinfo_skills:

      * the skill must be one a class-6 character receives at creation;
      * AcquireMethod must be 2 (LEARNED_ON_SKILL_LEARN -- granted the moment the skill is);
      * RaceMask and ClassMask must pass, and ZERO MEANS NO FILTER, so a row does not have to be
        ClassMask 32 to fire on a Death Knight. That is the trap: two of the eight rows this
        finds are ClassMask 0 on a DK-only skill line.

    Anything it finds whose spell has BaseLevel >= 2 is a level-55-ish ability being handed to a
    level-1 character. Each one must be either flipped by the spec or on AM2_WAIVERS with a
    reason. A ninth row appearing in stock data fails the build instead of shipping.
    """
    table = dbc_tables.SKILLLINEABILITY_DBC
    spell_table = dbc_tables.SPELL_DBC
    dk_classmask = 1 << (spec.DK_CLASS - 1)

    creation_skills = {}
    for rm, cm, sk in db.query(
            "SELECT racemask, classmask, skill FROM playercreateinfo_skills"):
        creation_skills.setdefault(int(sk), []).append((int(rm), int(cm)))

    spell_idx = plan.spell.index()
    found = {}
    for sla_id, row in sorted(plan.sla.index().items()):
        if plan.sla.cell(row, table.index_of["AcquireMethod"]) != 2:
            continue
        skill = plan.sla.cell(row, table.index_of["SkillLine"])
        if skill not in creation_skills:
            continue
        if not any(cm == 0 or cm & dk_classmask for _rm, cm in creation_skills[skill]):
            continue
        class_mask = plan.sla.cell(row, table.index_of["ClassMask"])
        if class_mask and not (class_mask & dk_classmask):
            continue
        sid = plan.sla.cell(row, table.index_of["Spell"])
        if sid not in spell_idx:
            continue
        base = plan.spell.cell(spell_idx[sid], spell_table.index_of["BaseLevel"])
        if base < 2:
            continue
        found[sla_id] = (sid, base)

    # plan.sla already has the flips applied, so a flipped row will not be in `found`. Compare
    # against the union instead, which is what makes this a derivation and not a tautology.
    handled = set(spec.STOCK_SLA_FLIPS) | set(spec.AM2_WAIVERS)
    unexplained = {k: v for k, v in found.items() if k not in handled}
    checks.expect(
        not unexplained, "#21",
        f"every AcquireMethod = 2 row a Death Knight receives at creation with BaseLevel >= 2 "
        f"is either flipped ({len(spec.STOCK_SLA_FLIPS)}) or waived with a reason "
        f"({len(spec.AM2_WAIVERS)})",
        "unexplained " + ", ".join(f"sla {k} -> spell {v[0]} BaseLevel {v[1]}"
                                   for k, v in sorted(unexplained.items())))
    # And the flips must actually still be needed -- a stock data change that set one of them to
    # 0 upstream would leave this file overriding a row for no reason.
    stale = [sla_id for sla_id in spec.STOCK_SLA_FLIPS
             if sla_id not in plan.stock_sla_acquire_methods
             or plan.stock_sla_acquire_methods[sla_id] != 2]
    checks.expect(not stale, "#21",
                  f"all {len(spec.STOCK_SLA_FLIPS)} flipped rows really are AcquireMethod = 2 "
                  f"in the stock DBC",
                  f"already 0 upstream, override is dead weight: {stale}")
    for sla_id, (sp, name, why) in sorted(spec.AM2_WAIVERS.items()):
        checks.ok("#21", f"waived: sla {sla_id} -> {sp} {name} -- {why.split('.')[0]}.")


def check_progression(plan, checks):
    """#17 -- the level ladder itself: no gaps, no overlap, and a clean handoff at the top.

    Everything about WHEN a rank arrives, checked against the DBC rather than against the spec's
    own arithmetic. The failure this exists for is quiet: a rank whose level is above the stock
    rank's is never reachable, and a chain whose last custom rank sits above the handoff means
    the character is superseded onto stock data before the ladder finishes.
    """
    table = dbc_tables.SPELL_DBC
    idx = plan.spell.index()
    for ability in spec.ABILITIES:
        levels = [r.level for r in ability.ranks]
        checks.expect(levels[0] == ability.intro_level, "#17",
                      f"{ability.name}: rank 1 is at level {levels[0]}, the brief's level")
        checks.expect(all(b - a == spec.RANK_STEP for a, b in zip(levels, levels[1:])), "#17",
                      f"{ability.name}: {len(levels)} ranks, one every {spec.RANK_STEP} levels "
                      f"({levels[0]}..{levels[-1]})",
                      f"levels {levels}")
        checks.expect(levels[-1] < ability.handoff_level, "#17",
                      f"{ability.name}: last custom rank (level {levels[-1]}) is below the "
                      f"stock rank (level {ability.handoff_level}), gap "
                      f"{ability.handoff_level - levels[-1]}")
        checks.expect(ability.handoff_level - levels[-1] <= spec.RANK_STEP, "#17",
                      f"{ability.name}: the gap to the stock rank is no wider than one rank "
                      f"step, so there is no dead stretch of levels at the top")
        # And the level really is what the emitted record says, not what the spec computed.
        for rank in ability.ranks:
            base = plan.spell.cell(idx[rank.spell_id], table.index_of["BaseLevel"])
            slvl = plan.spell.cell(idx[rank.spell_id], table.index_of["SpellLevel"])
            checks.expect(base == rank.level and slvl == rank.level, "#17",
                          f"spell {rank.spell_id}: BaseLevel and SpellLevel are both "
                          f"{rank.level}",
                          f"BaseLevel {base}, SpellLevel {slvl}")

        # #18 -- the handoff. The chain must run custom..custom, stock rank 1, ..stock rank N
        # with the join exactly at the boundary and nothing of Blizzard's touched on the far
        # side of it except the client-only subtext renumbering.
        chain = ability.chain
        join = len(ability.ranks)
        checks.expect(chain[join - 1] == ability.ranks[-1].spell_id
                      and chain[join] == ability.stock_chain[0], "#18",
                      f"{ability.name}: chain rank {join} is custom {chain[join - 1]} and rank "
                      f"{join + 1} is stock {chain[join]} -- immediately adjacent")
        checks.expect(
            all(sid not in plan.sql_rows["spell_dbc"] for sid in ability.stock_chain), "#18",
            f"{ability.name}: no stock rank gets a spell_dbc override row, so from level "
            f"{ability.handoff_level} the server reads Blizzard's own record")
        if ability.learnable:
            checks.expect(
                (ability.handoff_level, ability.stock_chain[0]) in spec.progression_grants(),
                "#18",
                f"{ability.name}: the module grants stock {ability.stock_chain[0]} at level "
                f"{ability.handoff_level}, so the handoff does not depend on mod-learn-spells")
        else:
            checks.expect(
                not any(sid in {r.spell_id for r in ability.ranks} | set(ability.stock_chain)
                        for _l, sid in spec.progression_grants()), "#18",
                f"{ability.name}: nothing in this chain is ever granted -- it is cast by a core "
                f"script, not learned")

    # #24 -- a mirror chain must have EXACTLY as many ranks as the chain it mirrors.
    by_key = {a.key: a for a in spec.ABILITIES}
    for ability in spec.ABILITIES:
        if not ability.mirror_of:
            continue
        principal = by_key[ability.mirror_of]
        checks.expect(len(ability.chain) == len(principal.chain), "#24",
                      f"{ability.name}: {len(ability.chain)} ranks, same as {principal.name}. "
                      f"GetSpellWithRank (SpellMgr.cpp:650) walks this chain by the main-hand "
                      f"rank number and dereferences node->next with no null check",
                      f"{len(ability.chain)} vs {len(principal.chain)} -- "
                      f"spell_dk_threat_of_thassarian would segfault the worldserver")
        checks.expect(
            [r.level for r in ability.ranks] == [r.level for r in principal.ranks], "#24",
            f"{ability.name}: rank levels track {principal.name} exactly")

    entries = spec.progression_entries()
    lv = [e[0] for e in entries]
    checks.expect(lv == sorted(lv), "#17",
                  f"the progression table is sorted by level ({lv[0]}..{lv[-1]}); Reconcile() "
                  f"breaks on the first entry above the player's level")
    checks.expect(all(1 <= l <= 80 for l in lv), "#17", "every grant level is in 1..80")
    for _lvl, sid, kind, _c in entries:
        if kind == spec.GRANT_CUSTOM:
            continue
        checks.expect(sid in idx, "#17",
                      f"stock grant {sid} ({_c}) exists in Spell.dbc")


def check_value_curve(plan, checks):
    """#19 -- values rise with rank, and the last custom rank is below the stock one.

    A ladder that is not monotonic is a ladder where levelling up makes you weaker, and rounding
    a linear curve at low values is exactly where that happens. Checked on the resolved
    $m/$M pair rather than on the raw cells, because that pair is what the player sees and what
    CalcValue rolls.
    """
    for ability in spec.ABILITIES:
        for cell in ability.scaling:
            series = []
            for rank in ability.ranks:
                ov = plan.rank_overrides(ability, rank)
                series.append((rank.level, rank.spell_id)
                              + plan.cell_range(ov[cell.base_points], ov[cell.die_sides]))
            stock_lo, stock_hi = plan.cell_range(
                plan.stock_cell(ability, cell.base_points),
                plan.stock_cell(ability, cell.die_sides))
            lows = [lo for _l, _s, lo, _hi in series]
            highs = [hi for _l, _s, _lo, hi in series]
            checks.expect(all(a < b for a, b in zip(lows, lows[1:])), "#19",
                          f"{ability.name} {cell.base_points}: minimum rises with every rank "
                          f"({lows[0]} -> {lows[-1]})",
                          f"not strictly increasing: {lows}")
            checks.expect(all(a < b for a, b in zip(highs, highs[1:])), "#19",
                          f"{ability.name} {cell.base_points}: maximum rises with every rank "
                          f"({highs[0]} -> {highs[-1]})",
                          f"not strictly increasing: {highs}")
            checks.expect(highs[-1] < stock_hi and lows[-1] < stock_lo, "#19",
                          f"{ability.name} {cell.base_points}: the last custom rank "
                          f"({lows[-1]}-{highs[-1]}) is weaker than stock rank 1 "
                          f"({stock_lo}-{stock_hi}) -- no overlap at the handoff")
            checks.expect(lows[0] >= 1, "#19",
                          f"{ability.name} {cell.base_points}: rank 1 is a positive value "
                          f"({lows[0]})",
                          "the curve rounded a value to zero or below")

    # THE ANCHOR, pinned -- but pinned to the BASE curve, not to the shipped number.
    #
    # Icy Touch rank 1 at 10-12 is the one hand-calibrated value in the feature and the whole
    # power curve is derived from it, so it must not drift by accident. It IS however allowed to
    # move by INTENT: spec.OVERTUNE is a deliberate, reviewed multiplier. Pinning the shipped
    # value would make every future balance pass fail this check and train someone to edit the
    # assertion, which is how a guard stops being a guard.
    #
    # So the check is: with the overtune backed out, does the curve still produce exactly 10-12?
    # That proves the calibration is intact while leaving tuning free.
    it = spec.ICY_TOUCH
    lo, hi = plan.rank_ranges(it, it.ranks[0])[0][1:]
    saved = spec.OVERTUNE
    try:
        spec.OVERTUNE = 1.0
        base_bp, base_die = spec.scale_cell(
            plan.stock_cell(it, "EffectBasePoints_1"), plan.stock_cell(it, "EffectDieSides_1"),
            it.ranks[0].level, it.handoff_level,
            any(c.weapon_flat for c in it.scaling))
    finally:
        spec.OVERTUNE = saved
    base_lo, base_hi = Plan.cell_range(base_bp, base_die)
    checks.expect((base_lo, base_hi) == (10, 12), "#19",
                  "Icy Touch rank 1 base curve is still 10-12, the value verified in production",
                  f"backing the overtune out gives {base_lo}-{base_hi}")
    checks.ok("#19", f"Icy Touch rank 1 ships at {lo}-{hi} "
                     f"(base 10-12 x{spec.OVERTUNE:g} overtune, tapering to 0 at the handoff)")


def check_rune_costs(plan, checks):
    """#20 -- cloning rank 1's RuneCostID really does give the stock rune cost.

    Requirement: rune costs, cast times, cooldowns and ranges come across untouched from the
    clone. Cast time, cooldown and range are single cells and cloning them is self-evident;
    RuneCostID is an INDEX into SpellRuneCost.dbc, and every stock rank has a DIFFERENT index, so
    "cloned" only means "correct" if all those rows hold the same numbers. They do -- but that is
    an observation about the stock file, so it gets checked rather than assumed.
    """
    if not plan.rune_costs:
        checks.skip("#20", "SpellRuneCost.dbc not present; rune cost identity not checked")
        return
    col = dbc_tables.SPELL_DBC.index_of["RuneCostID"]
    idx = plan.spell.index()
    for ability in spec.ABILITIES:
        ids = [plan.spell.cell(idx[s], col) for s in ability.stock_chain]
        costs = {plan.rune_costs.get(i) for i in ids}
        checks.expect(len(costs) == 1 and None not in costs, "#20",
                      f"{ability.name}: all {len(ids)} stock ranks cost "
                      f"{next(iter(costs))} (blood/unholy/frost/runic power), so the clone's "
                      f"RuneCostID {ids[0]} is the stock cost",
                      f"rune costs differ across ranks: {dict(zip(ids, (plan.rune_costs.get(i) for i in ids)))}")
        for rank in ability.ranks:
            checks.expect(plan.spell.cell(idx[rank.spell_id], col) == ids[0], "#20",
                          f"spell {rank.spell_id}: RuneCostID {ids[0]} came across from the "
                          f"clone untouched")


CORE_CORRECTIONS = os.path.join(
    spec.REPO_ROOT, ".work", "ac-src", "src", "server", "game", "Spells",
    "SpellInfoCorrections.cpp")


def check_corrections_baked(checks, path=CORE_CORRECTIONS):
    """#22 -- a clone loses every core fix keyed on the stock spell ID. Find them.

    Cloning preserves everything matched by family, mask or icon -- which is the entire reason
    for the design. It preserves NOTHING the core hardcodes by ID, and SpellInfoCorrections.cpp
    is a wall of `ApplySpellFix({ id, id, ... }, ...)`. Today exactly one cloned ID appears
    there (Horn of Winter, whose two mutations are baked into the clone as ordinary cells), but
    "today" is a property of a pinned core, so re-grep it whenever the source is around.
    """
    if not os.path.exists(path):
        checks.skip("#22", f"core source not present at {os.path.relpath(path, spec.REPO_ROOT)}; "
                           "cannot re-grep SpellInfoCorrections for cloned spell ids")
        return
    text = open(path, encoding="utf-8", errors="replace").read()
    fixed = set()
    for args in re.findall(r"ApplySpellFix\(\s*\{([^}]*)\}", text, re.S):
        fixed.update(int(m) for m in re.findall(r"\b(\d{3,6})\b", args))
    for ability in spec.ABILITIES:
        if ability.clone_from not in fixed:
            checks.ok("#22", f"{ability.name}: stock {ability.clone_from} has no ID-keyed "
                             f"SpellInfoCorrections entry, so the clone loses nothing")
            continue
        baked = bool(ability.extra_overrides)
        waived = ability.clone_from in spec.CORRECTION_WAIVERS
        checks.expect(baked or waived, "#22",
                      f"{ability.name}: stock {ability.clone_from} HAS a SpellInfoCorrections "
                      f"entry and the clone carries "
                      + (f"{len(ability.extra_overrides)} baked cell override(s) "
                         f"{sorted(ability.extra_overrides)}" if baked
                         else f"an explicit waiver"),
                      "the correction is keyed on the stock spell id and will not apply to the "
                      "custom ranks -- bake it into extra_overrides or waive it in "
                      "CORRECTION_WAIVERS with a reason")


def check_script_binding(plan, db, checks):
    """#23 -- every renumbered chain that has a script keeps it, on every rank.

    LoadSpellScriptNames drops a `-id` row whole when `id` is no longer the first spell in its
    chain (ObjectMgr.cpp:6377-6381), so renumbering silently unhooks the script from the STOCK
    ranks as well as failing to hook it to the new ones. Two halves: the spec must cover every
    script the live table has for a chain we touch, and the emitted rows must cover every spell
    in that chain.
    """
    spec_scripts = {}
    for ability in spec.ABILITIES:
        for script in ability.scripts:
            spec_scripts.setdefault(ability.clone_from, set()).add(script)

    for script, negative, chain in plan.script_binds:
        ability = next(a for a in spec.ABILITIES if -negative == a.clone_from)
        checks.expect(set(chain) == set(ability.chain), "#23",
                      f"{script}: bound to all {len(chain)} ranks of the renumbered "
                      f"{ability.name} chain, custom and stock")

    if db is None or not db.live():
        checks.skip("#23", "no live DB: cannot re-derive which chains have script rows")
        return
    touched = {s for a in spec.ABILITIES for s in a.chain}
    rows = db.query("SELECT spell_id, ScriptName FROM spell_script_names WHERE ABS(spell_id) IN ("
                    + ", ".join(str(s) for s in sorted(touched)) + ")")
    live = {}
    for sid, name in rows:
        live.setdefault(abs(int(sid)), set()).add(name)
    for ability in spec.ABILITIES:
        needed = set()
        for sid in ability.chain:
            needed |= live.get(sid, set())
        declared = set(ability.scripts)
        checks.expect(needed <= declared, "#23",
                      f"{ability.name}: the spec re-points every script the live table binds to "
                      f"this chain ({sorted(declared) or 'none'})",
                      f"live table also has {sorted(needed - declared)} -- renumbering would "
                      f"drop it for every rank, including the level-80 one")


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
        "spell_script_names": ("spell_id", "ScriptName"),
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


def check_race_coverage(sql_paths, db, checks):
    """#15 -- every DK-capable race has a createinfo row, an action bar and an outfit PAIR.

    THE POINT OF THIS CHECK. A race that is simply missing from spec.DK_RACES does not fail
    loudly anywhere else: it keeps its stock playercreateinfo row, which is map 609 zone 4298,
    and it keeps its stock CharStartOutfit rows, which are eighteen pieces of RequiredLevel 55
    plate. That is a character created at level 1, standing in Acherus, wearing gear they cannot
    use, with an action bar full of abilities they do not know -- exactly the state this feature
    exists to prevent, produced silently. So the build fails instead.

    "DK-capable" is not a constant. It is read from the live DB: the set of races that have a
    class-6 playercreateinfo row, which is precisely the set CharacterHandler will accept a DK
    creation for (ObjectMgr::GetPlayerInfo is nullptr otherwise). Both blood elves and draenei
    are in it -- ChrRaces.dbc field 68 gives them expansion 1, this realm's accounts are
    expansion 2, and CharacterHandler.cpp:309 only rejects `raceEntry->expansion > Expansion()`.
    """
    created, actioned, outfitted = {}, {}, {}
    for path in sql_paths:
        for kind, table, payload in parse_emitted_sql(path):
            if kind != "insert":
                continue
            if table == "playercreateinfo" and payload["class"] == spec.DK_CLASS:
                created[payload["race"]] = (payload["map"], payload["zone"])
            elif table == "playercreateinfo_action" and payload["class"] == spec.DK_CLASS:
                actioned.setdefault(payload["race"], set()).add(payload["button"])
            elif table == "charstartoutfit_dbc" and payload["ClassID"] == spec.DK_CLASS:
                outfitted.setdefault(payload["RaceID"], set()).add(payload["SexID"])

    spec_races = {r.race_id for r in spec.DK_RACES}
    for race_id in sorted(spec_races):
        race = spec.race_by_id(race_id)
        checks.expect(race_id in created, "#15",
                      f"race {race_id} {race.name}: playercreateinfo row emitted")
        checks.expect(created.get(race_id, (spec.FORBIDDEN_CREATE_MAP,))[0]
                      != spec.FORBIDDEN_CREATE_MAP, "#15",
                      f"race {race_id} {race.name}: emitted spawn is off map "
                      f"{spec.FORBIDDEN_CREATE_MAP}",
                      f"map {created.get(race_id, ('?',))[0]}")
        checks.expect(outfitted.get(race_id) == set(spec.OUTFIT_SEXES), "#15",
                      f"race {race_id} {race.name}: charstartoutfit_dbc pair emitted "
                      f"(sexes {sorted(spec.OUTFIT_SEXES)})",
                      f"got sexes {sorted(outfitted.get(race_id, ()))}")
        want_buttons = {b for b, _a, _t in spec.action_bar_for(race)}
        checks.expect(actioned.get(race_id) == want_buttons, "#15",
                      f"race {race_id} {race.name}: action bar emitted "
                      f"(buttons {sorted(want_buttons)})",
                      f"got {sorted(actioned.get(race_id, ()))}")

    if db is not None and db.live():
        live = {int(r[0]) for r in
                db.query(f"SELECT race FROM playercreateinfo WHERE class = {spec.DK_CLASS}")}
        checks.expect(live == spec_races, "#15",
                      f"spec covers exactly the {len(live)} races this realm lets a Death "
                      f"Knight be created as: {sorted(live)}",
                      f"live-only {sorted(live - spec_races)} spec-only "
                      f"{sorted(spec_races - live)}")
    else:
        checks.skip("#15", "no live DB: cannot re-derive the DK-capable race set")


def check_template_kits(plan, db, checks):
    """#16 -- each race's template kit is one a LEVEL 1 Death Knight can actually wear.

    Reproduces the two gates that decide what a new character ends up holding:

      * PlayerStorage.cpp:2343-2365 -- `GetSkillValue(item->GetSkill()) == 0` returns
        EQUIP_ERR_NO_REQUIRED_PROFICIENCY, where GetSkill() is the item Class/SubClass ->
        SkillLine map at ItemTemplate.h:782-815 (transcribed into dk_spec).
      * Player::StoreNewItemInBestSlots (Player.cpp:759-792) -- an item that fails to equip is
        NOT an error, it goes quietly into the backpack. That is what makes this worth checking
        mechanically: the failure mode is a character who spawns holding nothing, with no log
        line anywhere.

    A Death Knight's starting skills come from playercreateinfo_skills via LearnDefaultSkills
    (Player.cpp:622), filtered by racemask and classmask, so the answer is per race.
    """
    dk_classmask = 1 << (spec.DK_CLASS - 1)
    skill_rows = [(int(a), int(b), int(c)) for a, b, c in
                  db.query("SELECT racemask, classmask, skill FROM playercreateinfo_skills")]
    classes_by_race = {}
    for r, c in db.query("SELECT race, class FROM playercreateinfo"):
        classes_by_race.setdefault(int(r), set()).add(int(c))

    # One query for every item any candidate kit could contain, rather than one per kit.
    wanted = set()
    for race in spec.DK_RACES:
        for cls in spec.TEMPLATE_CLASS_PREFERENCE:
            row_id = plan.outfit_by_key.get((race.race_id, cls, 0))
            if row_id is not None:
                wanted |= set(plan.outfit_items(row_id))
    protos = {}
    if wanted:
        for row in db.query(
                "SELECT entry, class, subclass, InventoryType, RequiredLevel, AllowableClass "
                "FROM item_template WHERE entry IN ("
                + ",".join(str(i) for i in sorted(wanted)) + ")"):
            protos[int(row[0])] = tuple(int(v) for v in row[1:])

    def usable(item_id, skills):
        proto = protos.get(item_id)
        if proto is None:
            return False, 0             # unknown item: ObjectMgr skips it, so does the player
        item_class, subclass, inv_type, req_level, allow = proto
        need = spec.item_required_skill(item_class, subclass)
        ok = ((need == 0 or need in skills) and req_level <= 1
              and (allow == -1 or bool(allow & dk_classmask)))
        return ok, inv_type

    def kit_weapon(race_id, cls, skills):
        """The first melee weapon in this kit a level-1 DK can hold, 0 if none, None if the
        kit is not a candidate at all (race cannot be that class, or the pair is incomplete).

        BOTH sexes have to arm the character. They carry the same items in every stock kit,
        but "in every stock kit" is an observation about today's DBC, not a guarantee, and
        checking the male row only would let a female-specific gap through silently.
        """
        if cls not in classes_by_race.get(race_id, ()):
            return None
        rows = [plan.outfit_by_key.get((race_id, cls, s)) for s in spec.OUTFIT_SEXES]
        if any(r is None for r in rows):
            return None
        found = set()
        for row in rows:
            found.add(next((i for i in plan.outfit_items(row)
                            if usable(i, skills)[0]
                            and usable(i, skills)[1] in spec.MELEE_INVENTORY_TYPES), 0))
        return 0 if 0 in found else sorted(found)[0]

    for race in spec.DK_RACES:
        rmask = 1 << (race.race_id - 1)
        skills = {s for rm, cm, s in skill_rows
                  if (cm == 0 or cm & dk_classmask) and (rm == 0 or rm & rmask)}

        weapon = kit_weapon(race.race_id, race.template_class, skills)
        checks.expect(bool(weapon), "#16",
                      f"race {race.race_id} {race.name}: the {race.template_class_name} kit "
                      f"arms a level-1 DK (item {weapon})",
                      "no melee weapon in the kit passes PlayerStorage.cpp:2363 for class 6"
                      if weapon == 0 else
                      f"class {race.template_class} is not a candidate kit for this race")

        # DELIBERATELY NOT "must be the first class in preference order that passes".
        #
        # An earlier version asserted that, and it was too strong -- it made this generator's
        # correctness depend on ANOTHER module's data. mod-autolearn adds creation-time
        # playercreateinfo_skills rows granting Death Knights skills 54 and 160 (one- and
        # two-handed maces), which is blizzlike: WotLK DKs really are mace-proficient and
        # AzerothCore's stock data is the thing that is wrong. With those rows applied, the
        # Tauren WARRIOR kit and its Battleworn Hammer become equippable, warrior wins the
        # preference order, and this assertion failed -- even though nothing about the Tauren
        # Death Knight had changed or broken.
        #
        # What actually matters is the property the user cares about: the character spawns
        # ARMED. So assert exactly that, against STOCK creation-time proficiencies only. The
        # Hunter kit satisfies it whether or not mod-autolearn is installed, which is the point:
        # a Tauren DK must not become unarmed because someone disabled an unrelated module.
        first = next((c for c in spec.TEMPLATE_CLASS_PREFERENCE
                      if kit_weapon(race.race_id, c, skills)), None)
        if first != race.template_class:
            checks.ok("#16",
                        f"race {race.race_id} {race.name}: kit is class "
                        f"{race.template_class} ({race.template_class_name}); class {first} "
                        f"would also arm it. Both work -- this one is chosen because it holds "
                        f"under stock proficiencies alone.")

        # And nothing in the kit may be level-gated. A RequiredLevel 55 piece is the Acherus
        # failure all over again, just with different item ids.
        row_id = plan.outfit_by_key.get((race.race_id, race.template_class, 0))
        gated = [i for i in (plan.outfit_items(row_id) if row_id is not None else [])
                 if protos.get(i) and protos[i][3] > 1]
        checks.expect(not gated, "#16",
                      f"race {race.race_id} {race.name}: every item in the "
                      f"{race.template_class_name} kit is RequiredLevel <= 1",
                      f"level-gated items {gated}")


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
    check_acquire_method_derivation(plan, db, checks)
    check_progression(plan, checks)
    check_value_curve(plan, checks)
    check_rune_costs(plan, checks)
    check_corrections_baked(checks)
    check_script_binding(plan, db, checks)
    check_template_kits(plan, db, checks)

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
    check_race_coverage(sql_paths, db, checks)
    check_class_stats(os.path.join(spec.SQL_DIR, spec.SQL_FILES["class_stats"]), db, checks)
    _check_header(header_path, checks)

    manifest, json_path, sums_path = write_manifest(
        args.out, [("sql", p) for p in sql_paths] + [("header", header_path)]
        + [("dbc", p) for p in dbc_paths.values()] + [("mpq", mpq_path)])
    print(f"\n== manifest -> {os.path.relpath(json_path, spec.REPO_ROOT)}, "
          f"{os.path.relpath(sums_path, spec.REPO_ROOT)}")
    for e in manifest["outputs"]:
        print(f"   {e['sha256'][:16]}  {e['bytes']:>10,}  {e['path']}")

    _print_damage_table(plan)
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


def _print_damage_table(plan):
    print("\n== values produced by the emitted rows (stock rank 1 on the last line of each)")
    for ability in spec.ABILITIES:
        print(f"   {ability.name}  ->  stock {ability.stock_chain[0]} at level "
              f"{ability.handoff_level}")
        for r in ability.ranks:
            ov = plan.rank_overrides(ability, r)
            cells = "  ".join(f"{c.base_points.replace('EffectBasePoints_', 'bp')}="
                              f"{ov[c.base_points]}/"
                              f"{ov[c.die_sides]}" for c in ability.scaling)
            print(f"     {r.spell_id}  {r.subtext:<8} level {r.level:>2}  {cells:<24}"
                  f"-> {plan.rank_summary(ability, r)}")
        stock = "  ".join(
            f"{lo}-{hi} {c.what}" if lo != hi else f"{lo} {c.what}"
            for c, lo, hi in plan.stock_ranges(ability))
        print(f"     {ability.stock_chain[0]}  Rank {len(ability.ranks) + 1:<3} "
              f"level {ability.handoff_level:>2}  {'(stock)':<24}-> {stock}")


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
    check_race_coverage(sql_paths, db if live else None, checks)
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
        for tag in ("#2", "#3", "#4", "#5", "#6", "#12", "#16", "#17", "#18", "#19",
                    "#20", "#21", "#22", "#23", "#24"):
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
    check_progression(plan, checks)
    check_value_curve(plan, checks)
    check_rune_costs(plan, checks)
    check_corrections_baked(checks)
    check_script_binding(plan, db if live else None, checks)
    if live:
        check_acquire_method_derivation(plan, db, checks)
        check_template_kits(plan, db, checks)
    else:
        checks.skip("#21", "no live DB: cannot re-derive the AcquireMethod = 2 set")
        checks.skip("#16", "no live DB: cannot re-derive the per-race template kits")

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

    _print_damage_table(plan)
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
