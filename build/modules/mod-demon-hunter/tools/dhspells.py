#!/usr/bin/env python3
"""ONE generator: turns dh_spec.py into the server's SQL and the client's DBCs, together.

    tools/dh_spec.py                  <- THE source of truth
            |
    tools/dhspells.py                 <- this file
      /            |              \\                    \\
  data/sql/    src/dh_progression.h   <out>/dbc/*.dbc    <out>/patch-Z.MPQ
  (server)     (module grant table)   (client truth)     (shipped to friends)

WHY ONE GENERATOR AND NOT TWO HAND-MAINTAINED HALVES
----------------------------------------------------
The server computes from `spell_dbc` and friends. The client renders tooltips, the character
sheet and the create screen from its own copy of the same files inside patch-Z.MPQ. **The
server cannot render a tooltip** -- `SpellEntryfmt` marks all 32 Description_/AuraDescription_
locale columns FT_NA and `DBCDatabaseLoader` throws them away, and `SpellInfo` has no
Description member at all (`docs/death-knights.md` 2). So the two copies are physically
separate and must be kept identical by construction, not by discipline. The invariants below
compare them cell by cell and fail the run on any difference.

WHY THIS GENERATOR RUNS SECOND, AND WHAT IT READS
-------------------------------------------------
There is exactly one archive. MPQ resolution is whole-file per archived path by archive
priority, so two archives cannot both supply `Spell.dbc` -- the higher-priority one wins
outright and the other's records are simply not there. `patch-Z` is already the top of the
resolved chain, so there is no second slot either: a `patch-Y.MPQ` would be silently invisible,
and a second generator writing `patch-Z.MPQ` would silently delete every Death Knight rank.

Therefore:

    dkspells.py --no-mpq          # writes <out>/dbc/{Spell,SkillLineAbility,CharStartOutfit}.dbc
    dhspells.py                   # reads <out>/dbc, appends, writes ALL of <out>/dbc + the MPQ

`--dbc-in` defaults to `<out>/dbc` and falls back to the stock `/srv/wow/data/dbc` for any file
the Death Knight generator does not touch. `scripts/build-client-patch.sh` runs the pair in
order; running this one alone against stock DBCs produces a correct Demon Hunter and a client
with no Death Knights, which is why the wrapper exists and why `--check` asserts the Death
Knight's records are present.

WHAT IT EMITS, IN DEPENDENCY ORDER
----------------------------------
    00_class.sql        chrclasses_dbc, player_class_stats, the seven gt* blocks,
                        skillline_dbc, skillraceclassinfo_dbc, talenttab_dbc,
                        spellshapeshiftform_dbc, player_shapeshift_model
    01_spells.sql       spell_dbc, skilllineability_dbc, spell_ranks, spell_bonus_data
    02_createinfo.sql   playercreateinfo, playercreateinfo_skills / _action,
                        charstartoutfit_dbc
    03_talents.sql      talent_dbc plus the talent ranks' spell_dbc rows
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
sys.path.insert(0, os.path.join(TOOLS_DIR, "..", "..", "..", "tools"))
sys.path.insert(0, os.path.join(TOOLS_DIR, "..", "..", "..", "tools", "ascension"))

import dh_spec as spec                                             # noqa: E402
from acdbc import dbc_tables, gametable, mpqlib                    # noqa: E402
from acdbc.dbc_tables import KIND_FLOAT, KIND_STRING               # noqa: E402
from acdbc.dbclib import Dbc                                       # noqa: E402


# THE TWO NUMBERS THAT DECIDE WHETHER THE WORLDSERVER BOOTS.
#
# SpellMgr::LoadSpellInfoStore walks every record and ASSERTs that each effect is below
# TOTAL_SPELL_EFFECTS and each aura below TOTAL_AURAS (SharedDefines.h). They are written as
# the last legal VALUE rather than the count, because that is how the check below reads.
#
# They matter here and nowhere else in this repo because this is the only generator that
# transplants records from a DIFFERENT server's client. Ascension extended both enums -- their
# private effects 165/175/183/195 and auras 317/353/354 are ordinary data in their file and a
# fatal assertion in ours. A number nobody would think to check, because for a hand-authored
# record it cannot be wrong.
MAX_SPELL_EFFECT = 164
MAX_SPELL_AURA = 316


# =============================================================================================
# Invariants
# =============================================================================================

class Checks:
    """Every assertion this generator makes, counted and reported rather than assumed.

    Deliberately not `assert`: a failed invariant should name itself, keep going so the run
    reports ALL of its problems rather than the first one, and set a non-zero exit. `-O` also
    strips real asserts, and this is the one program in the repo that must never be run with
    its checks compiled out.
    """

    def __init__(self, verbose=False):
        self.passed = self.failed = self.skipped = 0
        self.verbose = verbose
        self.failures = []

    def ok(self, tag, msg):
        self.passed += 1
        if self.verbose:
            print(f"   [pass] {tag} {msg}")

    def expect(self, cond, tag, msg):
        if cond:
            self.ok(tag, msg)
        else:
            self.failed += 1
            self.failures.append(f"{tag} {msg}")
            print(f"   [FAIL] {tag} {msg}")
        return bool(cond)

    def skip(self, tag, msg):
        self.skipped += 1
        print(f"   [skip] {tag} {msg}")

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{self.failed} failed, {self.skipped} skipped, {self.passed} passed, "
              f"{total} total")
        if self.failures:
            print("\nfailures:")
            for f in self.failures:
                print(f"  {f}")
        return 1 if self.failed else 0


# =============================================================================================
# Database -- read-only, and the reason it is not optional
# =============================================================================================

DEFAULT_MYSQL_CMD = (
    "docker compose -f {repo}/deploy/docker-compose.yml exec -T mysql "
    "mysql --defaults-extra-file=/etc/mysql/backup.cnf"
)


class Db:
    """Read-only access to the live world database.

    The generator refuses to retype values from memory. `player_class_stats` for the Demon
    Hunter is the Rogue's eighty rows, read here; the spawn point for each race is that race's
    Rogue `playercreateinfo` row, read here; the seven gametable blocks are the Rogue's blocks,
    read here. Nothing is transcribed, so a realm that has moved its starting zones or retuned
    its class stats stays correct without anyone remembering to update this file.

    Consequence, and it is not a small one: **the patch cannot be regenerated on a box without
    the server stack running.** `scripts/package-client.sh --dh-patch skip` is the escape hatch
    for packaging somewhere the generator cannot run.
    """

    def __init__(self, cmd=None, repo=spec.REPO_ROOT):
        self.cmd = shlex.split((cmd or DEFAULT_MYSQL_CMD).format(repo=repo))
        self.available = None

    def query(self, sql, db="acore_world"):
        proc = subprocess.run(self.cmd + ["-N", "-B", "-e", f"USE {db}; {sql}"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"mysql failed: {proc.stderr.strip()}\n  query: {sql}")
        rows = []
        for line in proc.stdout.splitlines():
            if not line:
                continue
            rows.append([None if c == "NULL" else c for c in line.split("\t")])
        return rows

    def probe(self):
        if self.available is None:
            try:
                self.query("SELECT 1")
                self.available = True
            except Exception as e:                                  # noqa: BLE001
                self.available = False
                self.error = str(e)
        return self.available


# =============================================================================================
# SQL formatting
# =============================================================================================

_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\x00": "\\0", "\x1a": "\\Z"}


def sql_str(s):
    return "'" + "".join(_ESCAPES.get(c, c) for c in s) + "'"


def f32_text(value):
    """The shortest decimal literal that reproduces this float32 exactly.

    Not cosmetic. These land in FLOAT columns that the client also reads out of the DBC, and a
    value that round-trips differently on the two sides is precisely the drift the whole
    two-halves-one-generator design exists to prevent.
    """
    import struct
    exact = struct.unpack("<f", struct.pack("<f", value))[0]
    for p in range(1, 18):
        t = f"{exact:.{p}g}"
        if struct.unpack("<f", struct.pack("<f", float(t)))[0] == exact:
            return t
    return repr(exact)


def sql_value(v):
    if isinstance(v, str):
        return sql_str(v)
    if isinstance(v, float):
        return f32_text(v)
    return str(int(v))


BANNER = """-- {name}
--
-- GENERATED by build/modules/mod-demon-hunter/tools/dhspells.py from tools/dh_spec.py.
-- DO NOT EDIT BY HAND. Re-run the generator and commit its SQL and its DBC outputs together,
-- or the client and the server drift and the tooltip stops matching the combat log.
--
-- Re-runnable on purpose. UpdateFetcher tracks a migration by bare filename plus a SHA1 of its
-- contents (UpdateFetcher.cpp:326-370): an unchanged file is skipped, but a CHANGED file is
-- re-applied IN FULL. Every statement below is therefore DELETE-then-INSERT per key.
--
{summary}
"""


def insert_rows(table, cols, rows, comment=None):
    """DELETE-then-INSERT, never UPDATE.

    An UPDATE against a row that is not there succeeds and does nothing, which is the exact
    failure mode a class that half-exists cannot afford.
    """
    out = []
    if comment:
        out.append(comment)
    keys = ", ".join(f"`{c}`" for c in cols)
    vals = ",\n  ".join("(" + ", ".join(sql_value(v) for v in r) + ")" for r in rows)
    out.append(f"INSERT INTO `{table}` ({keys}) VALUES\n  {vals};")
    return "\n".join(out)


# =============================================================================================
# The plan
# =============================================================================================

class Plan:
    """Everything the run will emit, computed once, then written and checked."""

    def __init__(self, dbc_in, stock_in, checks):
        self.checks = checks
        self.dbc_in = dbc_in
        self.stock_in = stock_in
        self.dbcs = {}
        self.gametables = {}
        self.sources = {}
        self.rank_chains = []          # (ability key, (rank spell ids...)) for spell_ranks
        self._asc = "unloaded"         # sentinel: None means "tried and failed", do not retry
        self.source_map = {}           # third-party spell id -> the id we gave that record

        for t in spec.DBC_TABLES:
            path, src = self._resolve(t.dbc_file)
            self.dbcs[t.dbc_file] = Dbc(t, path)
            self.sources[t.dbc_file] = src

        for gt in spec.GAMETABLES:
            path, src = self._resolve(gt.dbc_file)
            self.gametables[gt.dbc_file] = gametable.GametableFile(path)
            self.sources[gt.dbc_file] = src

    # WHICH FILES MAY COME FROM THE CHAINED DIRECTORY.
    #
    # Exactly the three the Death Knight generator writes, and it is derived from that
    # generator's own spec rather than transcribed here, so the two cannot drift.
    #
    # This is not a micro-optimisation, it is a correctness fix. `--dbc-in` defaults to
    # `<out>/dbc`, which is also where THIS generator writes. Preferring the chained copy for
    # every file meant that on the second run it read back its OWN previous output -- found
    # class 10 already in ChrClasses.dbc, SkillLine 800 already taken, shapeshift form 23 no
    # longer blank -- and failed nine invariants. Those invariants were right and the input was
    # wrong: a generator that is not idempotent because it eats its own output is a generator
    # that produces a different archive every run.
    #
    # Everything else is read from stock every time, which is what makes a run reproducible.
    def _chained_files(self):
        """The DK generator's three output files, read from its spec so they cannot drift."""
        if not hasattr(self, "_chained_cache"):
            dk_tools = os.path.join(spec.REPO_ROOT, "build", "modules",
                                    "mod-dk-lowlevel", "tools")
            if dk_tools not in sys.path:
                sys.path.insert(0, dk_tools)
            try:
                import dk_spec
                self._chained_cache = frozenset(t.dbc_file for t in dk_spec.DBC_TABLES)
            except ImportError:
                self._chained_cache = frozenset()
        return self._chained_cache

    def _resolve(self, name):
        """Stock, unless this is one of the files the Death Knight generator hands over.

        Returns (path, provenance). Anything not in the chained set is read from stock EVERY
        run -- including the ten files this generator writes itself, which is what stops it
        reading back its own output. See CHAINED above.
        """
        if name in self._chained_files():
            chained = os.path.join(self.dbc_in, name)
            if os.path.exists(chained):
                return chained, "chained"
        return os.path.join(self.stock_in, name), "stock"

    # ------------------------------------------------------------------ ChrClasses row ----
    def build_class_row(self):
        """Append ChrClasses record 10 by cloning the template class's record.

        Cloned, not authored, for the same reason every spell is: the record has 60 columns and
        the five that matter are named in dh_spec.CHRCLASS_ROW. The other 55 are locale name
        slots and FT_NA columns whose meaning nobody has written down, and a class whose
        unknown-column values match a real class's is strictly safer than one whose match zero.
        """
        d = self.dbcs["ChrClasses.dbc"]
        t = d.table
        ids = d.ids()
        self.checks.expect(spec.DH_CLASS not in ids, "#1",
                           f"ChrClasses.dbc has no record {spec.DH_CLASS} yet "
                           f"(present: {ids})")
        src = ids.index(spec.TEMPLATE_CLASS)
        row = d.clone_row(src)
        for col, val in spec.CHRCLASS_ROW.items():
            ci = t.index_of[col]
            if t.kind(ci) == KIND_STRING:
                d.set_str(row, ci, val)
            else:
                d.set_i32(row, ci, val)

        # Blank every locale name slot other than enUS. The clone carries the template's, so a
        # deDE client would render "Schurke" for a Demon Hunter -- worse than an empty string,
        # which the client falls back to enUS for.
        for col in t.columns:
            if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                d.set_str(row, t.index_of[col], "")

        # clone_row appends, which would leave the file 1..9, 11, 10. The server would not care
        # -- LookupEntry goes through an id->record index -- but the create screen enumerates
        # classes in FILE order, so the Demon Hunter button would appear after Druid instead of
        # between Warlock and Druid. Sorting puts it where its id says it belongs.
        d.sort_by_index_column()
        self.checks.expect(d.is_strictly_ascending(), "#2",
                           "ChrClasses.dbc is strictly ascending with 10 between 9 and 11")
        self.class_row = d.index()[spec.DH_CLASS]
        return self.class_row

    # ------------------------------------------------------------------- CharBaseInfo -----
    def build_charbaseinfo(self):
        """Two records, (race, class) byte pairs. Client only -- the server never loads this.

        This is the half that greys the button out for a human. It is presentation, not
        security: a crafted CMSG_CHAR_CREATE ignores it entirely, which is why
        `playercreateinfo` having rows for exactly two races is the real gate.
        """
        d = self.dbcs["CharBaseInfo.dbc"]
        t = d.table
        ri, cinfo = t.index_of["RaceID"], t.index_of["ClassID"]
        have = {(d.get_u8(i, ri), d.get_u8(i, cinfo)) for i in range(len(d.records))}
        added = []
        for r in spec.DH_RACES:
            key = (r.race_id, spec.DH_CLASS)
            if key in have:
                continue
            row = d.clone_row(0)
            d.set_u8(row, ri, r.race_id)
            d.set_u8(row, cinfo, spec.DH_CLASS)
            added.append(key)
        self.checks.expect(len(added) == len(spec.DH_RACES), "#3",
                           f"CharBaseInfo.dbc gained {added} and nothing else")
        # The negative half of "only elves", asserted rather than assumed: no OTHER race may
        # have picked up class 10 from a previous run or a hand edit.
        allowed = {r.race_id for r in spec.DH_RACES}
        others = {(rr, cc) for rr, cc in
                  ((d.get_u8(i, ri), d.get_u8(i, cinfo)) for i in range(len(d.records)))
                  if cc == spec.DH_CLASS and rr not in allowed}
        self.checks.expect(not others, "#4",
                           f"no non-elf race has class {spec.DH_CLASS} in CharBaseInfo.dbc"
                           + (f" -- found {sorted(others)}" if others else ""))
        return added

    # --------------------------------------------------------------------- gametables -----
    def build_gametables(self):
        """Copy the template class's block over the class-10 block in all seven files."""
        report = []
        for gt in spec.GAMETABLES:
            g = self.gametables[gt.dbc_file]
            src_lo, _ = gt.block(spec.TEMPLATE_CLASS)
            dst_lo, dst_hi = gt.block(spec.DH_CLASS)
            before = g.values[dst_lo]
            changed = g.copy_block(src_lo, dst_lo, gt.per_class)
            report.append((gt, dst_lo, dst_hi, before, g.values[dst_lo], len(changed)))
            self.checks.expect(
                g.values[dst_lo] == g.values[src_lo], "#5",
                f"{gt.dbc_file} class-{spec.DH_CLASS} block now equals class-"
                f"{spec.TEMPLATE_CLASS}'s ({gt.comment})")
        self.gametable_report = report
        return report

    # ------------------------------------------------------------------- shapeshift -------
    def build_shapeshift(self):
        """SpellShapeshiftForm record 23 -- the demon form.

        Row 23 is entirely blank in the stock file (verified: every column zero), so this
        OVERWRITES a placeholder rather than appending. That keeps the file's id sequence dense
        and, more importantly, avoids reusing row 22, which is the Warlock's Metamorphosis and
        is what the Warlock's form-gated passives key off.
        """
        d = self.dbcs["SpellShapeshiftForm.dbc"]
        t = d.table
        ids = d.ids()
        self.checks.expect(spec.SHAPESHIFT_FORM_ID in ids, "#6",
                           f"SpellShapeshiftForm.dbc already has record "
                           f"{spec.SHAPESHIFT_FORM_ID} to overwrite")
        row = ids.index(spec.SHAPESHIFT_FORM_ID)
        # `*_Lang_Mask` is a locale-presence bitfield and is non-zero on EVERY row, including
        # the two blank ones (23 and 24 both carry 16712188). Counting it would make "blank"
        # unsatisfiable, so the test is over the columns that describe the form.
        blank = all(d.get_i32(row, i) == 0
                    for i, c in enumerate(t.columns)
                    if c != "ID" and not c.endswith("_Lang_Mask"))
        self.checks.expect(blank, "#7",
                           f"SpellShapeshiftForm record {spec.SHAPESHIFT_FORM_ID} was blank "
                           f"before we wrote it -- overwriting a used form would break it")
        stock22 = ids.index(22)
        cells = {
            "Name_Lang_enUS": spec.SHAPESHIFT_FORM_NAME,
            # Copied from row 22 rather than invented: these bits control whether the client
            # keeps the player's own animations and whether abilities are usable in form.
            "Flags": d.get_i32(stock22, t.index_of["Flags"]),
            "CreatureType": 3,                       # CREATURE_TYPE_DEMON, as row 22
            "CreatureDisplayID_1": spec.METAMORPHOSIS_DISPLAY_ID,
            "CreatureDisplayID_2": spec.METAMORPHOSIS_DISPLAY_ID,   # horde model slot
        }
        for col, val in cells.items():
            ci = t.index_of[col]
            if t.kind(ci) == KIND_STRING:
                d.set_str(row, ci, val)
            else:
                d.set_i32(row, ci, val)

        # THE ONE FLAG THAT MUST NOT BE THERE.
        #
        # SHAPESHIFT_FLAG_CAN_ONLY_CAST_SHAPESHIFT_SPELLS = 0x400. UnitDefines.h:117 marks it
        # NYI and that comment is wrong -- SpellInfo::CheckShapeshift reads it at
        # SpellInfo.cpp:1490 and silences every spell whose Stances mask does not include the
        # form. A Demon Hunter in demon form would be able to cast nothing at all, and the
        # symptom ("my buttons are grey in Metamorphosis") points nowhere near a DBC flag.
        #
        # Row 22's 0xd8 does not include it, so the copy above is safe -- but it is COPIED, and
        # a client whose row 22 differs would carry it in silently. Checked, not trusted.
        flags = d.get_i32(row, t.index_of["Flags"])
        self.checks.expect(not (flags & 0x400), "#50",
                           f"demon form flags 0x{flags:x} do not include 0x400 "
                           f"CAN_ONLY_CAST_SHAPESHIFT_SPELLS, which would silence the class "
                           f"in its own form")
        self.shapeshift_row = row
        return row

    # ---------------------------------------------------------------- skills and tabs -----
    def build_skill_lines(self):
        """Three class skill lines (CategoryID 7) and their SkillRaceClassInfo bindings.

        CategoryID 7 is SKILL_CATEGORY_CLASS -- verified against stock rows 26 "Arms",
        38 "Combat" and 771 "Frost", all category 7. A class skill line is what gives the
        spellbook a named tab; without a SkillRaceClassInfo row binding it to a race/class mask
        the line exists and nobody is eligible for it.
        """
        sl = self.dbcs["SkillLine.dbc"]
        srci = self.dbcs["SkillRaceClassInfo.dbc"]
        template_line = sl.ids().index(38)      # Combat -- a real class line to clone
        added = []
        for n, (sid, name) in enumerate(spec.SKILL_LINES):
            self.checks.expect(sid not in sl.ids(), "#8",
                               f"SkillLine {sid} ({name}) is free")
            row = sl.clone_row(template_line)
            sl.set_i32(row, sl.table.index_of["ID"], sid)
            sl.set_i32(row, sl.table.index_of["CategoryID"], 7)
            sl.set_str(row, sl.table.index_of["DisplayName_Lang_enUS"], name)
            for col in sl.table.columns:
                if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                    sl.set_str(row, sl.table.index_of[col], "")
            sl.set_str(row, sl.table.index_of["Description_Lang_enUS"], "")

            rid = spec.SKILLRACECLASSINFO_ID_BASE + n
            self.checks.expect(rid not in srci.ids(), "#9",
                               f"SkillRaceClassInfo {rid} is free")
            r2 = srci.clone_row(0)
            for col, val in (("ID", rid), ("SkillID", sid),
                             ("RaceMask", spec.DH_RACE_MASK),
                             ("ClassMask", spec.DH_CLASS_MASK),
                             # 1040 is what the Death Knight's own class lines carry
                             # (skill 771 -> SkillRaceClassInfo 897, read from the stock file).
                             ("Flags", 1040), ("MinLevel", 0),
                             ("SkillTierID", 0), ("SkillCostIndex", 0)):
                srci.set_i32(r2, srci.table.index_of[col], val)
            added.append((sid, name, rid))
        self.skill_lines = added

        self.build_skill_eligibility()
        return added

    def build_skill_eligibility(self):
        """Make class 10 eligible for the skills every class is supposed to have.

        Two separate operations on SkillRaceClassInfo, because the stock file expresses
        eligibility two different ways -- see the long note on dh_spec.STOCK_ALL_CLASS_MASKS
        for why this exists at all and what each missing row costs at runtime.

          1. WIDEN the rows that already mean "every class" and merely spell it as a literal
             1503/1535 that predates class 10. Languages, professions, Cloth, Mounts,
             Companions, both racial lines. Nothing else is affected: adding bit 9 to a mask
             that already has every other bit cannot change any other class's eligibility.
          2. CREATE a row per CREATE_SKILL_RCI entry, for the skills whose stock rows are
             genuinely per-class and so have no "all classes" row to widen.
        """
        srci = self.dbcs["SkillRaceClassInfo.dbc"]
        t = srci.table
        cm_i, sk_i, id_i = t.index_of["ClassMask"], t.index_of["SkillID"], t.index_of["ID"]

        widened = []
        for r in range(len(srci.records)):
            before = srci.get_i32(r, cm_i)
            if before in spec.STOCK_ALL_CLASS_MASKS:
                srci.set_i32(r, cm_i, before | spec.DH_CLASS_MASK)
                widened.append((srci.get_i32(r, id_i), srci.get_i32(r, sk_i), before,
                                before | spec.DH_CLASS_MASK))
        self.srci_widenings = widened
        self.checks.expect(widened, "#51",
                           "SkillRaceClassInfo has rows whose ClassMask is a literal "
                           f"'every class' value {spec.STOCK_ALL_CLASS_MASKS} to widen -- none "
                           "found means the client file changed shape and the class would ship "
                           "unable to speak")

        # Languages are the ones that decide whether the class can use chat AT ALL, and through
        # chat whether it can run a single dot command, so they are named and checked rather
        # than left to the mask rule. 98 Common / 109 Orcish are the two faction defaults and
        # 113 Darnassian / 137 Thalassian are the two racial ones for the classes' own races.
        eligible = {srci.get_i32(r, sk_i) for r in range(len(srci.records))
                    if srci.get_i32(r, cm_i) & spec.DH_CLASS_MASK}
        for lang, who in ((98, "Common"), (109, "Orcish"),
                          (113, "Darnassian"), (137, "Thalassian")):
            self.checks.expect(lang in eligible, "#52",
                               f"class {spec.DH_CLASS} is eligible for skill {lang} "
                               f"(Language: {who}) -- without a language ChatHandler.cpp:112 "
                               f"drops every say AND every dot command")

        created = []
        for n, (skill, flags, minlevel, donor) in enumerate(spec.CREATE_SKILL_RCI):
            rid = spec.CREATE_SKILL_RCI_ID_BASE + n
            self.checks.expect(rid not in srci.ids(), "#53",
                               f"SkillRaceClassInfo {rid} is free for skill {skill}")
            didx = srci.index()
            if not self.checks.expect(donor in didx, "#54",
                                      f"donor SkillRaceClassInfo {donor} for skill {skill} "
                                      f"exists"):
                continue
            dr = didx[donor]
            self.checks.expect(srci.get_i32(dr, sk_i) == skill, "#55",
                               f"donor SkillRaceClassInfo {donor} is still skill {skill} "
                               f"(found {srci.get_i32(dr, sk_i)}) -- a client bump moved it")
            self.checks.expect(srci.get_i32(dr, t.index_of["Flags"]) == flags, "#56",
                               f"donor {donor} Flags still {flags} "
                               f"(found {srci.get_i32(dr, t.index_of['Flags'])})")
            row = srci.clone_row(dr)
            for col, val in (("ID", rid), ("SkillID", skill),
                             ("RaceMask", spec.DH_RACE_MASK),
                             ("ClassMask", spec.DH_CLASS_MASK),
                             ("Flags", flags), ("MinLevel", minlevel),
                             ("SkillTierID", 0), ("SkillCostIndex", 0)):
                srci.set_i32(row, t.index_of[col], val)
            created.append((skill, rid, donor))
        self.srci_created = created

        # The invariant that ties this table to playercreateinfo_skills: LearnDefaultSkills
        # walks that table and skips anything with no SkillRaceClassInfo row, so a skill listed
        # there and missing here is granted to nobody, silently.
        self.checks.expect({s for s, _f, _m, _d in spec.CREATE_SKILL_RCI}
                           == {s for s, _n in spec.CREATE_SKILLS}, "#57",
                           "CREATE_SKILL_RCI covers exactly CREATE_SKILLS -- a skill in "
                           "playercreateinfo_skills with no SkillRaceClassInfo row is dropped "
                           "by Player::LearnDefaultSkills with nothing logged")

        srci.sort_by_index_column()
        self.checks.expect(srci.is_strictly_ascending(), "#58",
                           "SkillRaceClassInfo.dbc is strictly ascending after the new rows")
        print(f"   SkillRaceClassInfo: widened {len(widened)} stock row(s) "
              f"({spec.STOCK_ALL_CLASS_MASKS} -> +{spec.DH_CLASS_MASK}), "
              f"created {len(created)} new row(s)")
        return widened, created

    # Every Spell.dbc column whose VALUE IS A SPELL ID. A transplanted record carries the
    # source server's ids in all of them, and each one means something different when it lands
    # in a file where that id does not exist:
    #
    #   EffectTriggerSpell_*   the effect fires nothing. Silent -- the ability still casts, it
    #                          just does none of the damage the tooltip promises.
    #   *AuraSpell             the "requires/excludes aura X" gate can never be satisfied, so
    #                          the spell is either always castable or never castable.
    #   ModalNextSpell         the follow-up button never appears.
    #
    # None of these produce an error on either side. That is the whole reason this list is
    # written out rather than left to "we would notice".
    SPELL_REFERENCE_COLUMNS = (
        "EffectTriggerSpell_1", "EffectTriggerSpell_2", "EffectTriggerSpell_3",
        "CasterAuraSpell", "TargetAuraSpell",
        "ExcludeCasterAuraSpell", "ExcludeTargetAuraSpell",
        "ModalNextSpell",
    )

    def remap_source_references(self, checks):
        """Repoint every spell-id cell in a transplanted record at OUR id for that spell.

        Runs after everything is emitted, because a record may legitimately reference another
        record that had not been created yet when it was itself transplanted -- Twin Slice's
        parent is built before its two shells, and Felspears before the bolt every rank fires.

        Three outcomes per cell, and the third is the point of the whole pass:

          * 0            left alone.
          * mapped       rewritten to our id. This is the common case and it is what makes an
                         imported kit hang together instead of being 158 disconnected records.
          * NOT mapped   zeroed, and reported. The source server had a record for it and we did
                         not import one, so the reference cannot be honoured. Zeroing is the
                         honest failure: an effect that fires nothing is inert, whereas a stale
                         foreign id is a live pointer into whatever OUR file happens to have at
                         that number -- and at 500000-1200000 that is usually nothing, but it
                         only has to be something once.
        """
        d = self.dbcs["Spell.dbc"]
        t = d.table
        if not self.source_map:
            return
        cols = [(c, t.index_of[c]) for c in self.SPELL_REFERENCE_COLUMNS if c in t.index_of]
        ours = set(self.source_map.values())
        remapped = dangling = 0
        seen_dangling = {}
        for row in range(len(d.records)):
            sid = d.get_i32(row, t.index_of["ID"])
            if sid not in ours:
                continue                      # not one of ours; never touch a stock record
            for col, ci in cols:
                ref = d.get_i32(row, ci)
                if not ref:
                    continue
                if ref in self.source_map:
                    d.set_i32(row, ci, self.source_map[ref])
                    remapped += 1
                elif ref not in d.index():
                    d.set_i32(row, ci, 0)
                    dangling += 1
                    seen_dangling.setdefault(ref, []).append(f"{sid}.{col}")
        for ref, where in sorted(seen_dangling.items()):
            # skip(), not expect(False): a dangling reference is EXPECTED for the parts of a
            # kit we deliberately did not import, and the pass has already made it safe by
            # zeroing it. It is reported so the count is visible, not to fail the build.
            checks.skip("#67",
                        f"imported spell reference {ref} has no record on this realm; zeroed in "
                        f"{len(where)} cell(s): {', '.join(where[:4])}"
                        f"{' ...' if len(where) > 4 else ''}")
        print(f"   source references: {remapped} remapped, {dangling} dangling zeroed "
              f"({len(seen_dangling)} distinct)")
        return remapped, dangling

    def _ascension(self, checks):
        """The Ascension client's Spell.dbc, opened once, or None if it is not present.

        Loaded lazily and cached -- including the failure -- because it is a 229 MB read and
        because a checkout with no Ascension client installed must still be able to build every
        donor-based ability. An absent client is a SKIP, not a failure: it degrades the run to
        "no transplanted records", which the per-ability checks then report individually.
        """
        if self._asc == "unloaded":
            try:
                import importer as _importer
                self._asc = _importer.AscensionSpells(
                    self.dbcs["Spell.dbc"].table, spec.ASCENSION_CLIENT_DATA)
                print(f"   Ascension source: {self._asc.count:,} records from "
                      f"{spec.ASCENSION_CLIENT_DATA}")
            except Exception as exc:                       # noqa: BLE001 -- reported, not raised
                self._asc = None
                checks.skip("#64", f"no Ascension client to import from ({exc})")
        return self._asc

    # ------------------------------------------------------------------------ spells -----
    def build_spells(self, checks):
        """Clone one Spell.dbc record per ability, plus its SkillLineAbility row.

        THE ORDER OF OVERRIDES IS LOAD-BEARING and it is: memcpy the donor, then dh_donors.
        ALWAYS, then dh_donors.OVERRIDES[key], then the identity cells (ID, name, level,
        family, mask) which nothing may contradict. ALWAYS comes first so a per-ability entry
        can deliberately reinstate something -- Vengeful Retreat's family is the whole reason
        that ordering matters -- and identity comes last so no data file can accidentally
        rename a spell or move it into another ability's ID block.
        """
        try:
            import dh_donors
        except ImportError:
            checks.skip("#25", "dh_donors.py not present; no ability records emitted")
            self.spells = []
            return []

        d = self.dbcs["Spell.dbc"]
        t = d.table
        sla = self.dbcs["SkillLineAbility.dbc"]
        st = sla.table
        idx = d.index()
        emitted = []

        # Ascending, because Spell.dbc must stay strictly ascending -- DBCFileLoader sizes its
        # index table from the highest id and the client walks the file in order.
        #
        # Ids allocated in THIS loop are tracked separately from `idx`, which was taken before
        # it started. Without that, rank 2 of an ability would be checked for collision against
        # a snapshot that cannot contain rank 1, and two ranks could quietly land on one id.
        taken = set()
        for ability in sorted(spec.ABILITIES, key=lambda a: _ability_spell_id(a)):
            base_sid = _ability_spell_id(ability)
            n_ranks = max(1, ability.ranks)

            # A single-record ability owns exactly one id, so a ladder cannot be hung off it.
            # Caught here rather than by the ascending check later, where it would surface as an
            # unrelated collision in a different ability's block.
            if ability.key not in spec.ABILITY_BLOCKS:
                if not checks.expect(n_ranks == 1, "#59",
                                     f"{ability.name}: has {n_ranks} ranks but is a SINGLES "
                                     f"entry, which owns one id -- give it an ABILITY_BLOCKS "
                                     f"block instead"):
                    continue

            # The per-rank transplant sources, rank 1 first. Empty for a donor-built ability.
            sources = ((ability.source,) + tuple(ability.source_ranks)) if ability.source else ()
            if sources and not checks.expect(
                    len(sources) == n_ranks, "#60",
                    f"{ability.name}: {len(sources)} source record(s) for {n_ranks} rank(s) -- "
                    f"source_ranks must exclude `source` itself"):
                continue

            levels = ability.rank_levels or (ability.level,) * n_ranks
            if not checks.expect(len(levels) == n_ranks, "#61",
                                 f"{ability.name}: {len(levels)} rank_levels for {n_ranks} "
                                 f"ranks"):
                continue
            if not checks.expect(levels[0] == ability.level, "#62",
                                 f"{ability.name}: rank_levels[0] is {levels[0]}, but the "
                                 f"ability is learned at {ability.level}"):
                continue
            if not checks.expect(all(b > a for a, b in zip(levels, levels[1:])), "#63",
                                 f"{ability.name}: rank levels {levels} are not strictly "
                                 f"ascending, so a later rank would supersede an unlearned one"):
                continue

            if not checks.expect(ability.donor in idx, "#26",
                                 f"{ability.name}: donor {ability.donor} exists in Spell.dbc"):
                continue

            rank_ids = []
            for r in range(n_ranks):
                sid = (spec.spell_id_for(ability.key, r) if ability.key in spec.ABILITY_BLOCKS
                       else base_sid)
                if not checks.expect(sid not in idx and sid not in taken, "#27",
                                     f"{ability.name} rank {r + 1}: id {sid} is free"):
                    continue
                taken.add(sid)
                rank_ids.append((r, sid))
            if not rank_ids:
                continue

            emitted_ranks = []
            for r, sid in rank_ids:
                row = d.clone_row(idx[ability.donor])
                cells = {}

                # THE TRANSPLANT. When an ability names a `source`, the donor clone above is
                # immediately overwritten by the third-party record, cell for cell. See
                # build/tools/ascension/importer.py for why this beats a donor and for the one
                # trap: string columns hold OFFSETS into the source file's own string block, so
                # they are resolved to text there and re-added here as text.
                #
                # It is applied BEFORE dh_donors.ALWAYS so the house rules still win -- an
                # imported record carrying a foreign SpellClassSet or a stale
                # CategoryRecoveryTime must not survive into our file.
                if sources:
                    src_id = sources[r]
                    asc = self._ascension(checks)
                    if asc is not None and checks.expect(
                            src_id in asc, "#64",
                            f"{ability.name} rank {r + 1}: source spell {src_id} exists in the "
                            f"Ascension client"):
                        cells.update(asc.cells(src_id))
                        cells.pop("ID", None)          # identity is ours, set below
                        self.source_map[src_id] = sid

                cells.update(dh_donors.ALWAYS)
                cells.update(dh_donors.OVERRIDES.get(ability.key, {}))
                # Last word, and deliberately after ALWAYS: these repair cells that this core
                # cannot represent, and a house rule must not be able to reinstate one.
                cells.update(getattr(spec, "CELL_OVERRIDES", {}).get(ability.key, {}))
                # Identity last. `family` is None for everything but Vengeful Retreat, where
                # SpellEffects.cpp:5067 makes family 9 the only way the leap goes backwards.
                cells.update({
                    "ID": sid,
                    "Name_Lang_enUS": ability.name,
                    # A ladder's ranks are separate spells sharing one name; the client tells
                    # them apart by this subtext alone and the spellbook groups on it. Left
                    # empty for a single-record ability, where "Rank 1" would be a lie.
                    "NameSubtext_Lang_enUS": f"Rank {r + 1}" if n_ranks > 1 else "",
                    "BaseLevel": levels[r],
                    "SpellLevel": levels[r],
                    "SpellClassSet": ability.family if ability.family is not None
                    else spec.CHRCLASS_ROW["SpellClassSet"],
                })
                if ability.cooldown_ms:
                    cells["RecoveryTime"] = ability.cooldown_ms
                if ability.cost:
                    cells["ManaCost"] = ability.cost
                if ability.family is not None:
                    # A borrowed family with a non-zero mask is reachable by that class's
                    # talents. IsAffected needs a mask overlap, so zeroing them severs each one.
                    cells.update({"SpellClassMask_1": 0, "SpellClassMask_2": 0,
                                  "SpellClassMask_3": 0})

                # Cells the Death Knight and the first Demon Hunter never needed. Written only
                # when non-zero: setting them unconditionally would zero a perfectly good
                # Mechanic or ProcTypeMask that arrived with a transplanted record.
                if ability.mechanic:
                    cells["Mechanic"] = ability.mechanic
                if ability.target_aura_state:
                    cells["TargetAuraState"] = ability.target_aura_state
                if ability.stack_amount:
                    cells["CumulativeAura"] = ability.stack_amount
                if ability.proc_flags:
                    cells["ProcTypeMask"] = ability.proc_flags

                for col, val in cells.items():
                    if col not in t.index_of:
                        checks.expect(False, "#28",
                                      f"{ability.name}: {col!r} is not a Spell.dbc column")
                        continue
                    ci = t.index_of[col]
                    if t.kind(ci) == KIND_STRING:
                        d.set_str(row, ci, val)
                    elif t.kind(ci) == KIND_FLOAT:
                        d.set_f32(row, ci, float(val))
                    else:
                        d.set_i32(row, ci, int(val))

                # THE RANGE GATE. SpellMgr.cpp:3039 ASSERTs on an effect above
                # TOTAL_SPELL_EFFECTS or an aura above TOTAL_AURAS, so a single transplanted
                # cell carrying one of Ascension's private effects (175, 183) or auras (317,
                # 353, 354) is not a wrong number -- it is a worldserver that will not boot.
                # Checked on the way out, after every override, because an override is exactly
                # how such a cell is meant to be repaired.
                for k in (1, 2, 3):
                    eff = d.get_i32(row, t.index_of[f"Effect_{k}"])
                    aur = d.get_i32(row, t.index_of[f"EffectAura_{k}"])
                    checks.expect(eff <= MAX_SPELL_EFFECT, "#65",
                                  f"{ability.name} rank {r + 1}: Effect_{k} is {eff}, above "
                                  f"this core's TOTAL_SPELL_EFFECTS ({MAX_SPELL_EFFECT}) -- "
                                  f"the worldserver would assert on load")
                    checks.expect(aur <= MAX_SPELL_AURA, "#66",
                                  f"{ability.name} rank {r + 1}: EffectAura_{k} is {aur}, above "
                                  f"this core's TOTAL_AURAS ({MAX_SPELL_AURA})")

                # Blank every non-enUS locale slot. The clone carries the DONOR's, so a deDE
                # client would render the donor's German name -- worse than an empty string,
                # which the client falls back to enUS for.
                for col in t.columns:
                    if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                        d.set_str(row, t.index_of[col], "")

                slid = spec.sla_id_for(sid)
                srow = sla.clone_row(0)
                for col, val in (
                        ("ID", slid), ("SkillLine", spec.PRIMARY_SKILL_LINE), ("Spell", sid),
                        ("RaceMask", spec.DH_RACE_MASK), ("ClassMask", spec.DH_CLASS_MASK),
                        ("ExcludeRace", 0), ("ExcludeClass", 0), ("MinSkillLineRank", 0),
                        # Filled in below, once every rank of this ability has an id.
                        ("SupercededBySpell", 0),
                        # AcquireMethod 2 = LEARNED_ON_SKILL_LEARN. It grants at creation and
                        # re-grants at every login via _LoadSkills -> learnSkillRewardedSpells
                        # (Player.cpp:14081) with NO level test anywhere in that path. Correct
                        # for a level-1 rank, and a bug for any other -- a level-40 rank
                        # carrying it would be in the spellbook at level 1.
                        ("AcquireMethod", 2 if levels[r] == 1 else 0),
                        ("TrivialSkillLineRankHigh", 0), ("TrivialSkillLineRankLow", 0),
                        ("CharacterPoints_1", 0), ("CharacterPoints_2", 0)):
                    sla.set_i32(srow, st.index_of[col], val)

                emitted_ranks.append((r, sid, slid, srow))
                emitted.append((ability, sid, slid))

            # SUPERSEDING. Without this every rank stays in the spellbook at once: the client
            # hides a superseded rank purely on this column (SkillLineAbility.SupercededBySpell),
            # and the server's Player::addSpell uses it to remove the lower rank on learn. A
            # ladder with the column left at 0 is eight Twin Slice buttons on one action bar.
            for i in range(len(emitted_ranks) - 1):
                _r, _sid, _slid, srow = emitted_ranks[i]
                sla.set_i32(srow, st.index_of["SupercededBySpell"], emitted_ranks[i + 1][1])
            if len(emitted_ranks) > 1:
                self.rank_chains.append(
                    (ability.key, tuple(s for _r, s, _l, _w in emitted_ranks)))

        # SECOND RECORDS. `Ability.second_record` names the spell an ability triggers -- the
        # arrival damage of a dash, the periodic tick of an area aura, the off-hand half of a
        # dual-wield strike. Nobody learns them, they get no SkillLineAbility row and they are
        # not in the progression table -- but they have to EXIST. An EffectTriggerSpell pointing
        # at an id with no record is a silently dead effect: the dash still dashes and simply
        # does no damage on the way through, with nothing logged.
        #
        # Emitted from dh_donors.DONORS rather than from the ABILITIES loop because they are
        # not abilities; they have no level, no cost and no skill line.
        second = []
        # Every triggered half named by any ability, via triggered_halves() so that both
        # spellings are honoured -- `second_record` for the Death Knight-era single, and
        # `second_records` for an ability like Twin Slice that fires a main-hand AND an off-hand
        # record and cannot be expressed with one.
        wanted = sorted({k for a in spec.ABILITIES for k in a.triggered_halves()})
        for key in wanted:
            sid = spec.spell_id_for(key, 0)
            # A second record is transplanted the same way an ability is when the spec names a
            # source for it; dh_donors is the fallback for the hand-built kit. Checked in that
            # order because an imported record is strictly better information than a donor.
            src_id = getattr(spec, "SECOND_SOURCES", {}).get(key)
            donor = dh_donors.DONORS.get(key)
            if donor is None and src_id is not None:
                # Any row will do as the base: the transplant overwrites all 234 cells. Row 0 is
                # used rather than a chosen donor so that a missing donor entry is not fatal for
                # an imported record, which does not need one.
                donor = d.get_i32(0, t.index_of["ID"])
            if not checks.expect(donor is not None, "#33",
                                 f"second record {key!r} has a donor in dh_donors.DONORS or a "
                                 f"source in dh_spec.SECOND_SOURCES"):
                continue
            if not checks.expect(donor in idx, "#34",
                                 f"{key}: donor {donor} exists in Spell.dbc"):
                continue
            row = d.clone_row(idx[donor])
            cells = {}
            if src_id is not None:
                asc = self._ascension(checks)
                if asc is not None and checks.expect(
                        src_id in asc, "#68",
                        f"second record {key!r}: source spell {src_id} exists in the Ascension "
                        f"client"):
                    cells.update(asc.cells(src_id))
                    cells.pop("ID", None)
                    self.source_map[src_id] = sid
            cells.update(dh_donors.ALWAYS)
            cells.update(dh_donors.OVERRIDES.get(key, {}))
            # Second records take CELL_OVERRIDES too. The Felfury aura is the case that forced
            # this: its CumulativeAura arrives as 0 from the source, because Ascension caps the
            # pool in its own engine code rather than in the cell. Here the cell IS the cap --
            # Aura::ModStackAmount clamps against it (SpellAuras.cpp:973-980) -- so a 0 would
            # mean a resource that can never hold more than one charge.
            cells.update(getattr(spec, "CELL_OVERRIDES", {}).get(key, {}))
            # BaseLevel and the NAME come from the PARENT ability, not from the donor.
            #
            # BaseLevel is not cosmetic here, it is the whole per-level ramp. CalcValue
            # (SpellInfo.cpp:409-427) does `if (level < BaseLevel) level = BaseLevel;` and then
            # `level -= max(BaseLevel, SpellLevel)`, so a tick cloned from a level-60 warlock
            # spell and left at BaseLevel 60 contributes ZERO ramp for a level-10 Demon Hunter
            # and pays out the level-60 flat number instead. Setting it to the parent's learn
            # level is what makes the ramp start where the player gets the ability.
            #
            # The name matters for one reason: it is what the combat log prints. "Immolation"
            # in a Demon Hunter's log is the warlock spell it was cloned from.
            # WHO THE PARENT IS, derived from the abilities that actually name this record
            # rather than read out of a second hand-maintained table. dh_donors.SECOND_RECORDS
            # is the fallback for the hand-built kit, where a second record could exist without
            # any ability listing it.
            #
            # A record can have SEVERAL parents -- the Felfury stack aura is triggered by every
            # generator in the kit -- so the earliest-learned one wins. That is the one whose
            # level the per-level ramp has to start at: pick a later parent and the record pays
            # its flat number, with no ramp, for every level in between.
            parents = sorted(
                (a for a in spec.ABILITIES if key in a.triggered_halves()),
                key=lambda a: a.level)
            parent = parents[0] if parents else spec.ABILITIES_BY_KEY.get(
                dh_donors.SECOND_RECORDS.get(key))
            parent_key = parent.key if parent else dh_donors.SECOND_RECORDS.get(key)
            checks.expect(parent is not None, "#35",
                          f"second record {key!r} names parent {parent_key!r}, which is an "
                          f"ability in dh_spec")
            cells.update({"ID": sid, "NameSubtext_Lang_enUS": "",
                          "SpellClassSet": spec.CHRCLASS_ROW["SpellClassSet"]})
            if parent is not None:
                # BaseLevel is the ramp, not decoration: CalcValue (SpellInfo.cpp:409-427)
                # clamps to BaseLevel and then subtracts it, so a tick left at a level-60
                # donor's BaseLevel pays the level-60 flat number to a level-10 character and
                # ramps not at all. Always taken from the parent.
                cells.update({"BaseLevel": parent.level, "SpellLevel": parent.level})
                # The NAME is only borrowed when there is nothing better. A cloned donor
                # carries the DONOR's name -- "Immolation" in the combat log for a spell that
                # is not Immolation -- which is why the Demon Hunter took the parent's. A
                # TRANSPLANTED record already carries its own correct name, and overwriting it
                # with the parent's would relabel "Twin Slice Off-Hand" as "Twin Slice" and
                # make the two halves indistinguishable in the log.
                if src_id is None:
                    cells["Name_Lang_enUS"] = parent.name
            for col, val in cells.items():
                if col not in t.index_of:
                    checks.expect(False, "#28", f"{key}: {col!r} is not a Spell.dbc column")
                    continue
                ci = t.index_of[col]
                if t.kind(ci) == KIND_STRING:
                    d.set_str(row, ci, val)
                elif t.kind(ci) == KIND_FLOAT:
                    d.set_f32(row, ci, float(val))
                else:
                    d.set_i32(row, ci, int(val))
            for col in t.columns:
                if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                    d.set_str(row, t.index_of[col], "")
            second.append((key, sid, donor))
        self.second_records = second

        # STOCK ROWS WIDENED. Not new rows -- these are existing SkillLineAbility records whose
        # ClassMask is edited in place to include class 10, so Dual Wield, Parry and the two
        # racials become reachable. See dh_spec.STOCK_SLA_WIDENINGS for what each one costs if
        # it is left alone; the short version is that without 674 the class cannot dual wield.
        widened = []
        sidx = sla.index()
        for sla_id, spell_id, why in spec.STOCK_SLA_WIDENINGS:
            if not checks.expect(sla_id in sidx, "#37",
                                 f"stock SkillLineAbility {sla_id} exists to widen"):
                continue
            r = sidx[sla_id]
            got = sla.get_i32(r, st.index_of["Spell"])
            if not checks.expect(got == spell_id, "#38",
                                 f"SkillLineAbility {sla_id} still grants spell {spell_id} "
                                 f"(found {got}) -- a core or client bump moved it"):
                continue
            before = sla.get_i32(r, st.index_of["ClassMask"])
            checks.expect(not (before & spec.DH_CLASS_MASK), "#39",
                          f"SkillLineAbility {sla_id} does not already have class "
                          f"{spec.DH_CLASS} (mask {before})")
            sla.set_i32(r, st.index_of["ClassMask"], before | spec.DH_CLASS_MASK)
            widened.append((sla_id, spell_id, before, before | spec.DH_CLASS_MASK, why))
            print(f"   SLA {sla_id:6d} spell {spell_id:6d} ClassMask {before} -> "
                  f"{before | spec.DH_CLASS_MASK}   {why.split(' -- ')[0]}")

        # The same "every class is spelled 1503/1535" rule applied to this table. It has to be
        # applied HERE as well as to SkillRaceClassInfo and not only there, because the two are
        # consulted at different moments: SkillRaceClassInfo decides whether the skill is
        # learned, this decides which spells that skill then rewards. Cloth (4999, spell 9078)
        # is the one that matters most -- it is why a level-1 Demon Hunter could not put its own
        # starting trousers on -- but the rule is applied by mask rather than by id so that the
        # next universal row Blizzard shipped is not a second bug of the same shape.
        already = {sid for sid, _sp, _b, _a2, _w in widened}
        generic = 0
        for r in range(len(sla.records)):
            before = sla.get_i32(r, st.index_of["ClassMask"])
            if before not in spec.STOCK_ALL_CLASS_MASKS:
                continue
            rid = sla.get_i32(r, st.index_of["ID"])
            if rid in already:
                continue
            sla.set_i32(r, st.index_of["ClassMask"], before | spec.DH_CLASS_MASK)
            widened.append((rid, sla.get_i32(r, st.index_of["Spell"]), before,
                            before | spec.DH_CLASS_MASK,
                            f"ClassMask {before} is a literal 'every class' that predates "
                            f"class {spec.DH_CLASS}"))
            generic += 1
        print(f"   SLA generic: widened {generic} row(s) with ClassMask in "
              f"{spec.STOCK_ALL_CLASS_MASKS}")
        self.sla_widenings = widened

        d.sort_by_index_column()
        sla.sort_by_index_column()
        checks.expect(d.is_strictly_ascending(), "#29",
                      "Spell.dbc is strictly ascending after appending the ability records")
        checks.expect(sla.is_strictly_ascending(), "#30",
                      "SkillLineAbility.dbc is strictly ascending")
        am2 = [a.name for a, _s, _l in emitted if a.level == 1]
        checks.expect(all(a.level == 1 for a, _s, _l in emitted if a.level == 1), "#31",
                      f"AcquireMethod 2 is used only at level 1 ({', '.join(am2)})")
        self.spells = emitted
        print(f"   {len(emitted)} ability records, {len(second)} second records, "
              f"{len(emitted)} skill-line rows")
        return emitted

    # ------------------------------------------------------------------------ talents ----
    #
    # A talent RANK is a spell. "+2% damage per rank, five ranks" is five Spell.dbc records
    # carrying 2, 4, 6, 8 and 10, and a single Talent.dbc row listing all five ids in
    # SpellRank_1..5. That is how every stock tree is built and there is no cheaper shape.
    #
    # These deliberately do NOT get dh_donors.ALWAYS. That set exists to turn a creature or
    # cross-class donor into a usable Demon Hunter ABILITY -- it forces PowerType to energy,
    # zeroes ManaCostPct, and imposes the 1-second GCD. A passive talent has no cost and no
    # GCD, and worse, ALWAYS zeroes `ShapeshiftMask`, which is precisely the cell the
    # Metamorphosis-gated talents rely on (talents.md 2.C: AuraEffect::HandleShapeshiftBoosts
    # applies a PASSIVE|DO_NOT_DISPLAY talent whose ShapeshiftMask matches the form). Applying
    # ALWAYS here would silently disable every form-gated talent in the Vengeance tree.
    #
    # What they do get is the narrow set that is wrong on any clone: no level cap, no inherited
    # shared cooldown, and the class's own spell family.
    TALENT_BASE = {
        "MaxLevel": 0,
        "Category": 0,
        "CategoryRecoveryTime": 0,
    }

    def build_talents(self, checks):
        try:
            import dh_talents
        except ImportError:
            checks.skip("#40", "dh_talents.py not present; no talent records emitted")
            self.talents = []
            self.talent_spells = []
            return []

        d = self.dbcs["Spell.dbc"]
        t = d.table
        tal = self.dbcs["Talent.dbc"]
        tt = tal.table
        idx = d.index()
        base = dict(self.TALENT_BASE)
        base["SpellClassSet"] = spec.CHRCLASS_ROW["SpellClassSet"]

        # FOUR values. dh_spec.TALENT_TABS is (id, name, OrderIndex, BackgroundFile), and
        # unpacking three here raised ValueError the instant dh_talents.py appeared -- which is
        # to say this function had never once run against real data before now.
        tab_id = {name.lower(): tid for tid, name, _order, _bg in spec.TALENT_TABS}
        next_spell = spec.TALENT_SPELL_ID_BASE
        next_talent = spec.TALENT_ID_BASE
        emitted, spells = [], []
        # (tab, tier, col) -> Talent.dbc id, so a prereq can be resolved to the row it names.
        by_pos = {}

        for talent in dh_talents.TALENTS:
            if not checks.expect(talent.donor in idx, "#41",
                                 f"talent {talent.name!r}: donor {talent.donor} exists"):
                continue
            rank_ids = []
            for r in range(talent.ranks):
                sid = next_spell
                next_spell += 1
                if not checks.expect(sid < spec.TALENT_SPELL_ID_MAX, "#42",
                                     f"talent spell id {sid} is inside the "
                                     f"{spec.TALENT_SPELL_ID_BASE}-{spec.TALENT_SPELL_ID_MAX} "
                                     f"band"):
                    break
                row = d.clone_row(idx[talent.donor])
                cells = dict(base)
                cells.update(getattr(talent, "overrides", {}) or {})
                cells["ID"] = sid
                cells["Name_Lang_enUS"] = talent.name
                cells["NameSubtext_Lang_enUS"] = f"Rank {r + 1}" if talent.ranks > 1 else ""
                rank_cell = getattr(talent, "rank_cell", "")
                if rank_cell:
                    cells[rank_cell] = talent.rank_values[r]
                for col, val in cells.items():
                    if col not in t.index_of:
                        checks.expect(False, "#43",
                                      f"{talent.name}: {col!r} is not a Spell.dbc column")
                        continue
                    ci = t.index_of[col]
                    if t.kind(ci) == KIND_STRING:
                        d.set_str(row, ci, val)
                    elif t.kind(ci) == KIND_FLOAT:
                        d.set_f32(row, ci, float(val))
                    else:
                        d.set_i32(row, ci, int(val))
                for col in t.columns:
                    if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                        d.set_str(row, t.index_of[col], "")
                rank_ids.append(sid)
                spells.append(sid)

            tid = next_talent
            next_talent += 1
            trow = tal.clone_row(0)
            cells = {"ID": tid, "TabID": tab_id[talent.tab],
                     "TierID": talent.tier, "ColumnIndex": talent.col,
                     "Flags": getattr(talent, "flags", 0),
                     "PrereqTalent_1": 0, "PrereqRank_1": 0,
                     "PrereqTalent_2": 0, "PrereqTalent_3": 0,
                     "PrereqRank_2": 0, "PrereqRank_3": 0,
                     "RequiredSpellID": 0, "CategoryMask_1": 0, "CategoryMask_2": 0}
            # SpellRank_1..5 hold the rank ids; 6..9 exist in the file and the core marks them
            # FT_NA and never reads them, so they are zeroed rather than left at the clone's.
            for k in range(1, 10):
                cells[f"SpellRank_{k}"] = rank_ids[k - 1] if k <= len(rank_ids) else 0
            for col, val in cells.items():
                tal.set_i32(trow, tt.index_of[col], val)
            by_pos[(talent.tab, talent.tier, talent.col)] = (tid, trow, talent)
            emitted.append((talent, tid, tuple(rank_ids)))

        # Prerequisites, in a second pass: an arrow can only point at a talent that already has
        # a Talent.dbc id, and the design does not guarantee declaration order matches tier
        # order. PrereqRank_1 is a 0-BASED floor (Player.cpp:14329), so "@ 4" in the design
        # means "four points spent", i.e. the value 4 with a 5-rank prerequisite.
        for talent, tid, _ranks in emitted:
            pre = getattr(talent, "prereq", None)
            if not pre:
                continue
            ptier, pcol, prank = pre
            key = (talent.tab, ptier, pcol)
            if not checks.expect(key in by_pos, "#44",
                                 f"{talent.name}: prerequisite at {talent.tab} "
                                 f"tier {ptier} col {pcol} exists"):
                continue
            pid, _prow, ptalent = by_pos[key]
            checks.expect(ptier < talent.tier, "#45",
                          f"{talent.name}: prerequisite {ptalent.name!r} is in an earlier tier "
                          f"({ptier} < {talent.tier})")
            _t2, trow, _t3 = by_pos[(talent.tab, talent.tier, talent.col)]
            tal.set_i32(trow, tt.index_of["PrereqTalent_1"], pid)
            tal.set_i32(trow, tt.index_of["PrereqRank_1"], prank)

        # TRIGGER ROWS. A proc talent's aura fires a SECOND spell -- the energize, the buff --
        # and that spell needs a record of its own. dh_talents.Trigger says which talent points
        # at it and through which cell, but not which ID, because the ID is ours: it is
        # allocated here, after the ranks, out of the same band.
        #
        # Written into EVERY rank record of the naming talent, not just rank 1. Five ranks of
        # "Demon's Bite restores 3/6/9 Fury" are five records that all trigger the same
        # energize, and aura 231 PROC_TRIGGER_SPELL_WITH_VALUE passes the per-rank amount to it
        # (SpellAuraEffects.cpp:6933) -- which is the whole reason one trigger row serves them
        # all. A rank whose cell is left at the donor's value points at the DONOR's trigger.
        triggers = []
        for key, trig in sorted(getattr(dh_talents, "TRIGGERS", {}).items()):
            if not checks.expect(trig.donor in idx, "#54",
                                 f"trigger {key!r}: donor {trig.donor} exists"):
                continue
            sid = next_spell
            next_spell += 1
            row = d.clone_row(idx[trig.donor])
            cells = dict(base)
            cells.update(trig.overrides or {})
            cells["ID"] = sid
            for col, val in cells.items():
                if col not in t.index_of:
                    checks.expect(False, "#43", f"trigger {key}: {col!r} is not a column")
                    continue
                ci = t.index_of[col]
                if t.kind(ci) == KIND_STRING:
                    d.set_str(row, ci, val)
                elif t.kind(ci) == KIND_FLOAT:
                    d.set_f32(row, ci, float(val))
                else:
                    d.set_i32(row, ci, int(val))
            for col in t.columns:
                if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                    d.set_str(row, t.index_of[col], "")

            owner = by_pos.get(tuple(trig.used_by))
            if not checks.expect(owner is not None, "#55",
                                 f"trigger {key!r} names talent {trig.used_by}, which exists"):
                continue
            _otid, _orow, otalent = owner
            ranks_of = next((r for tl, _i, r in emitted if tl is otalent), ())
            cidx = t.index_of[trig.cell]
            ridx = d.index()
            for rank_sid in ranks_of:
                d.set_i32(ridx[rank_sid], cidx, sid)
            checks.expect(bool(ranks_of), "#56",
                          f"trigger {key!r}: its talent {otalent.name!r} has rank records to "
                          f"point at it")
            triggers.append((key, sid, trig))
            spells.append(sid)
        self.talent_triggers = triggers

        d.sort_by_index_column()
        tal.sort_by_index_column()
        checks.expect(d.is_strictly_ascending(), "#46",
                      "Spell.dbc is strictly ascending after appending the talent ranks")
        checks.expect(tal.is_strictly_ascending(), "#47",
                      "Talent.dbc is strictly ascending")
        # Every talent must be reachable: three tabs, and nothing outside them.
        used_tabs = {tab_id[t2.tab] for t2, _i, _r in emitted}
        checks.expect(used_tabs <= {tid for tid, _n, _order, _bg in spec.TALENT_TABS}, "#48",
                      f"every talent is in one of the three tabs ({sorted(used_tabs)})")
        self.talents = emitted
        self.talent_spells = spells
        # (tab, tier, col) -> the talent's rank spell ids. dh_talents keys SCRIPT_NAMES by grid
        # position rather than by id, because the ids are ours and it cannot know them.
        self.talent_ranks_by_pos = {
            (tl.tab, tl.tier, tl.col): r for tl, _i, r in emitted}
        print(f"   {len(emitted)} talents, {len(spells) - len(triggers)} rank records, "
              f"{len(triggers)} trigger records, "
              f"ids {spec.TALENT_SPELL_ID_BASE}-{next_spell - 1}")
        return emitted

    def build_talent_tabs(self):
        """Three TalentTab records with ClassMask 512.

        512 is bit 9, i.e. class 10. On a STOCK core these rows are read and then dropped by
        DBCStores.cpp:551-556, because `ClassMask & CLASSMASK_ALL_PLAYABLE` is zero and class
        10's bit is not in that macro -- silently, with no log line, leaving an empty talent
        panel. build/patches/0001 adds the bit. This is the single most important reason the
        core patch is not optional.
        """
        d = self.dbcs["TalentTab.dbc"]
        t = d.table
        template = d.ids().index(182)          # Rogue Assassination -- a real 3-tab class tree
        added = []
        for tab_id, name, order, background in spec.TALENT_TABS:
            self.checks.expect(tab_id not in d.ids(), "#10", f"TalentTab {tab_id} is free")
            row = d.clone_row(template)
            for col, val in (("ID", tab_id), ("ClassMask", spec.DH_CLASS_MASK),
                             ("RaceMask", 0), ("PetTalentMask", 0), ("OrderIndex", order)):
                d.set_i32(row, t.index_of[col], val)
            d.set_str(row, t.index_of["Name_Lang_enUS"], name)
            d.set_str(row, t.index_of["BackgroundFile"], background)
            for col in t.columns:
                if "_Lang_" in col and not col.endswith(("_Mask", "_enUS")):
                    d.set_str(row, t.index_of[col], "")
            added.append((tab_id, name, order))
        self.talent_tabs = added
        return added


# =============================================================================================
# Emitters
# =============================================================================================

def emit_class(plan, db, checks):
    """00_class.sql -- everything that makes class 10 exist and have correct numbers."""
    out = []
    d = plan.dbcs["ChrClasses.dbc"]
    t = d.table
    row = plan.class_row
    cols = list(t.columns)
    vals = [d.cell(row, i) for i in range(len(cols))]

    out.append(f"""
--
-- ChrClasses.dbc record {spec.DH_CLASS}.
--
-- The class's NAME comes from here and nowhere else: `FillLocalizedClassList` is a client C
-- function that reads this file, so "Demon Hunter" on the character sheet, in the create-screen
-- class list and from UnitClass() all follow from column Name_Lang_enUS. Filename is the class
-- TOKEN that FrameXML and GlueXML key CLASS_ICON_TCOORDS and RAID_CLASS_COLORS on.
--
-- DisplayPower {spec.CHRCLASS_ROW['DisplayPower']} = POWER_ENERGY -- a 0-100 bar with continuous
-- out-of-combat regeneration, which is what Fury is. SpellClassSet
-- {spec.CHRCLASS_ROW['SpellClassSet']} = SPELLFAMILY_UNK2, the only family value AzerothCore's
-- own validator leaves unclaimed (SpellMgr.cpp:2089), and the mechanism by which a Demon Hunter
-- talent can modify a Demon Hunter ability with no C++ at all.
--
-- Cloned from class {spec.TEMPLATE_CLASS} so the 55 columns nobody has names for match a real
-- class rather than being zero.
DELETE FROM `chrclasses_dbc` WHERE `ID` = {spec.DH_CLASS};
{insert_rows('chrclasses_dbc', cols, [vals])}
""")

    if db.probe():
        # Column names read off information_schema, not guessed: this table is
        # (Class, Level, BaseHP, BaseMana, Strength, Agility, Stamina, Intellect, Spirit).
        # BaseHP and BaseMana matter as much as the stats -- ObjectMgr.cpp:4883 checks
        # `basehealth == 0` for the start level and exit(1)s on it, the same fatal path the
        # stats check takes.
        stat_cols = ["Class", "Level", "BaseHP", "BaseMana",
                     "Strength", "Agility", "Stamina", "Intellect", "Spirit"]
        stats = db.query(
            f"SELECT {', '.join(stat_cols[1:])} FROM player_class_stats "
            f"WHERE Class = {spec.TEMPLATE_CLASS} ORDER BY Level")
        checks.expect(len(stats) == 80, "#11",
                      f"read {len(stats)} player_class_stats rows for the template class "
                      f"(expected 80)")
        rows = [[spec.DH_CLASS] + [int(c) for c in r] for r in stats]
        out.append(f"""
--
-- player_class_stats, levels 1-80.
--
-- THE BOOT GATE. ObjectMgr.cpp:4878 runs over every race/class pair at startup and calls
-- exit(1) if the START level has no stats row -- reported per RACE, so the error message
-- ("Race N class 10 initial level does not have stats data!") sends you looking in
-- playercreateinfo, which is the wrong table entirely. These 80 rows must be applied and the
-- server must come up cleanly BEFORE anything makes class 10 creatable.
--
-- Read out of the live class-{spec.TEMPLATE_CLASS} rows, never transcribed. This is class x
-- level; player_race_stats is flat per race and is added on top, so there are 80 rows and not
-- 160.
DELETE FROM `player_class_stats` WHERE `Class` = {spec.DH_CLASS};
{insert_rows('player_class_stats', stat_cols, rows)}
""")
    else:
        checks.skip("#11", "player_class_stats: database unreachable")

    for gt, dst_lo, dst_hi, before, after, n in plan.gametable_report:
        g = plan.gametables[gt.dbc_file]
        rows = [[i, g.values[i]] for i in range(dst_lo, dst_hi + 1)]
        src_lo, _ = gt.block(spec.TEMPLATE_CLASS)
        out.append(f"""
-- {gt.sql_table}: {gt.comment}.
-- Blizzard filled the vacant class-{spec.DH_CLASS} slot with a placeholder rather than leaving
-- it empty -- this block read {before:.8g} before we touched it. Overwritten with class
-- {spec.TEMPLATE_CLASS}'s rows {src_lo}..{src_lo + gt.per_class - 1}.
DELETE FROM `{gt.sql_table}` WHERE `ID` BETWEEN {dst_lo} AND {dst_hi};
{insert_rows(gt.sql_table, ['ID', 'Data'], rows)}
""")

    for name, dbcfile, idcol in (("skillline_dbc", "SkillLine.dbc", "ID"),
                                 ("skillraceclassinfo_dbc", "SkillRaceClassInfo.dbc", "ID"),
                                 ("talenttab_dbc", "TalentTab.dbc", "ID"),
                                 ("spellshapeshiftform_dbc", "SpellShapeshiftForm.dbc", "ID")):
        d = plan.dbcs[dbcfile]
        t = d.table
        want = _new_ids_for(plan, dbcfile)
        if not want:
            continue
        idx = d.index()
        rows = [[d.cell(idx[i], c) for c in range(len(t.columns))] for i in sorted(want)]
        lo, hi = min(want), max(want)
        # Deleted by explicit id and NOT by `BETWEEN lo AND hi`. Once skillraceclassinfo_dbc
        # carries widened stock rows the id span is 6..989 -- nearly the whole table -- and a
        # range delete would silently drop any row another module had put in that window.
        ids_sql = ", ".join(str(i) for i in sorted(want))
        out.append(f"""
-- {name}: {len(want)} row(s), ids {lo}..{hi}.
DELETE FROM `{name}` WHERE `{idcol}` IN ({ids_sql});
{insert_rows(name, list(t.columns), rows)}
""")

    summary = (f"-- class {spec.DH_CLASS}, races {[r.race_id for r in spec.DH_RACES]}, "
               f"template class {spec.TEMPLATE_CLASS}")
    return BANNER.format(name=spec.SQL_FILES["class"], summary=summary) + "\n".join(out)


def emit_createinfo(plan, db, checks):
    """02_createinfo.sql -- everything that makes a Demon Hunter rollable and land somewhere."""
    out = []

    if not db.probe():
        checks.skip("#14", "createinfo: database unreachable, cannot derive spawn points")
        return BANNER.format(name=spec.SQL_FILES["createinfo"],
                             summary="-- NOT EMITTED: database unreachable") + "\n"

    # ---- playercreateinfo: where a new Demon Hunter wakes up -------------------------------
    #
    # Read out of each race's own Rogue row, never typed in. That is what makes "only elves"
    # enforceable on the server side at all: `Player::Create` looks up
    # ObjectMgr::GetPlayerInfo(race, class) and fails the creation outright when there is no
    # row, so the set of rows here IS the set of legal races. The client's CharBaseInfo.dbc
    # greys the button out; this is what stops a crafted packet.
    rows, notes = [], []
    for r in spec.DH_RACES:
        got = db.query(
            f"SELECT map, zone, position_x, position_y, position_z, orientation "
            f"FROM playercreateinfo WHERE race = {r.race_id} AND class = {r.template_class}")
        if not checks.expect(len(got) == 1, "#14",
                             f"race {r.race_id} ({r.name}) has exactly one class-"
                             f"{r.template_class} playercreateinfo row to copy"):
            continue
        m, z, x, y, zz, o = got[0]
        rows.append([r.race_id, spec.DH_CLASS, int(m), int(z),
                     float(x), float(y), float(zz), float(o)])
        notes.append(f"--   race {r.race_id:2d} {r.name:10s} <- class {r.template_class}  "
                     f"map {int(m):3d} zone {int(z):4d}")
        # A Demon Hunter must not spawn on the Death Knight's map. Acherus is where a sub-56
        # character's talents get silently refunded on every login (Player.cpp:13936-13959),
        # and it has no way out for a class without Death Gate.
        checks.expect(int(m) != 609, "#15",
                      f"race {r.race_id} spawns on map {int(m)}, not Ebon Hold (609)")

    out.append(f"""
--
-- playercreateinfo -- and this table IS the elves-only rule.
--
-- Player::Create looks up ObjectMgr::GetPlayerInfo(race, class) and fails the creation when
-- there is no row, so the two rows below are the whole server-side gate. CharBaseInfo.dbc greys
-- the button out on the create screen, but that is presentation: a crafted CMSG_CHAR_CREATE
-- ignores it entirely and this is what stops it.
--
-- Map, zone and coordinates are copied from that race's own Rogue row in this realm's live
-- playercreateinfo -- never typed in -- so a realm that moves its starting zones stays correct.
{chr(10).join(notes)}
DELETE FROM `playercreateinfo` WHERE `class` = {spec.DH_CLASS};
{insert_rows('playercreateinfo',
             ['race', 'class', 'map', 'zone',
              'position_x', 'position_y', 'position_z', 'orientation'], rows)}
""")

    # ---- playercreateinfo_skills ------------------------------------------------------------
    skill_rows = []
    for sid, name in spec.SKILL_LINES:
        skill_rows.append([0, spec.DH_CLASS_MASK, sid, 0, f"Demon Hunter: {name}"])
    for sid, name in spec.CREATE_SKILLS:
        skill_rows.append([0, spec.DH_CLASS_MASK, sid, 0, f"Demon Hunter: {name}"])
    out.append(f"""
-- playercreateinfo_skills. classMask {spec.DH_CLASS_MASK} = 1 << (10 - 1); raceMask 0 means
-- "any race that can be this class", which the playercreateinfo rows above already restrict.
--
-- The three class lines give the spellbook its tabs. The weapon and armour skills are the
-- Rogue's set, trimmed -- see CREATE_SKILLS in dh_spec.py for what was dropped and why.
-- Defense (95) and Unarmed (162) are deliberately absent: their stock rows carry classMask 0,
-- so every class already has them and a class-10 row would be a duplicate.
DELETE FROM `playercreateinfo_skills` WHERE `classMask` = {spec.DH_CLASS_MASK};
{insert_rows('playercreateinfo_skills',
             ['raceMask', 'classMask', 'skill', 'rank', 'comment'], skill_rows)}
""")

    # ---- playercreateinfo_action ------------------------------------------------------------
    action_rows = []
    for r in spec.DH_RACES:
        bar = [spec.CREATE_ACTION_ATTACK]
        bar += [spec.spell_id_for(k, 0) for k in spec.STARTING_BAR_ABILITIES]
        race_spell = spec.CREATE_ACTION_RACE_SPELL.get(r.race_id)
        if race_spell:
            bar.append(race_spell)
        for button, action in enumerate(bar):
            action_rows.append([r.race_id, spec.DH_CLASS, button, action, 0])
    out.append(f"""
-- playercreateinfo_action -- the starting action bar, left to right.
--
-- Button 0 is Attack (6603) on every class in the game. The middle buttons are the level-1
-- ranks of the starting abilities, taken from the ability ladder rather than written down, so
-- a change to the ID plan cannot leave a stale button pointing at a spell nobody has. The last
-- is the race's own racial.
DELETE FROM `playercreateinfo_action` WHERE `class` = {spec.DH_CLASS};
{insert_rows('playercreateinfo_action',
             ['race', 'class', 'button', 'action', 'type'], action_rows)}
""")

    # ---- charstartoutfit_dbc ----------------------------------------------------------------
    #
    # Four rows: (race, sex) for two races. Cloned from that race+sex's Rogue outfit, which is
    # leather plus a dagger -- the right shape, and real item ids that exist on this realm.
    outfit = plan.dbcs["CharStartOutfit.dbc"]
    t = outfit.table
    idx = outfit.index()
    added_ids = []
    key_cols = [t.index_of[c] for c in ("RaceID", "ClassID", "SexID")]
    for n, (r, sex) in enumerate((r, s) for r in spec.DH_RACES for s in (0, 1)):
        src = None
        for i in range(len(outfit.records)):
            if (outfit.get_u8(i, key_cols[0]) == r.race_id
                    and outfit.get_u8(i, key_cols[1]) == r.template_class
                    and outfit.get_u8(i, key_cols[2]) == sex):
                src = i
                break
        if not checks.expect(src is not None, "#16",
                             f"CharStartOutfit has a class-{r.template_class} row for race "
                             f"{r.race_id} sex {sex} to clone"):
            continue
        new_id = spec.OUTFIT_ID_BASE + n
        checks.expect(new_id not in idx, "#17", f"CharStartOutfit id {new_id} is free")
        row = outfit.clone_row(src)
        outfit.set_i32(row, t.index_of["ID"], new_id)
        outfit.set_u8(row, key_cols[1], spec.DH_CLASS)
        added_ids.append(new_id)
    outfit.sort_by_index_column()
    checks.expect(outfit.is_strictly_ascending(), "#18",
                  "CharStartOutfit.dbc is strictly ascending after adding the four outfits")

    idx = outfit.index()
    orows = [[outfit.cell(idx[i], c) for c in range(len(t.columns))] for i in sorted(added_ids)]
    if orows:
        out.append(f"""
-- charstartoutfit_dbc -- the gear a new Demon Hunter wears on the character-creation preview
-- and wakes up in. Cloned from that race and sex's Rogue outfit: leather, a dagger, and the
-- race-correct shirt. 368 is the first free id -- the stock file's maximum is 367, which
-- already includes the Death Knight feature's 348-367.
DELETE FROM `charstartoutfit_dbc` WHERE `ID` BETWEEN {min(added_ids)} AND {max(added_ids)};
{insert_rows('charstartoutfit_dbc', list(t.columns), orows)}
""")

    summary = f"-- {len(rows)} spawn rows, {len(skill_rows)} skills, {len(orows)} outfits"
    return BANNER.format(name=spec.SQL_FILES["createinfo"], summary=summary) + "\n".join(out)


def _ability_spell_id(ability):
    if ability.key in spec.ABILITY_BLOCKS:
        return spec.spell_id_for(ability.key, 0)
    return spec.single_spell_id(ability.key)


def emit_spells(plan, checks):
    """01_spells.sql -- the ability records and their SkillLineAbility rows."""
    if not getattr(plan, "spells", None):
        return BANNER.format(name=spec.SQL_FILES["spells"],
                             summary="-- NOT EMITTED: dh_donors.py absent") + "\n"

    out = []
    d = plan.dbcs["Spell.dbc"]
    t = d.table
    idx = d.index()
    # ABILITIES *AND* SECOND RECORDS. Both halves, or the halves drift -- which is the one
    # failure this whole architecture exists to prevent. A second record that is in the client's
    # Spell.dbc but not in the server's spell_dbc means the client can render the triggered
    # spell's tooltip while the server has no SpellInfo for it at all: SpellMgr drops the
    # EffectTriggerSpell silently, the dash does no damage on the way through, and nothing is
    # logged. Emitting 22 rows for 27 records is exactly that bug, and it is invisible until
    # someone plays the class.
    ids = sorted([sid for _a, sid, _l in plan.spells]
                 + [sid for _k, sid, _d in getattr(plan, "second_records", [])])
    rows = [[d.cell(idx[i], c) for c in range(len(t.columns))] for i in ids]

    notes = "\n".join(
        f"--   {sid:6d}  L{a.level:<3d} {a.name:18s} <- {a.donor:6d}   {a.note}"
        for a, sid, _l in sorted(plan.spells, key=lambda x: x[0].level))
    out.append(f"""
--
-- spell_dbc: {len(ids)} Demon Hunter ability records, ids {min(ids)}-{max(ids)}.
--
-- Each is a byte-for-byte memcpy of the donor named below with a handful of named cells
-- overridden. A Spell.dbc record has 234 columns and perhaps a dozen of them are "the spell";
-- authoring one field by field silently drops whichever of the other 222 nobody thought about.
--
-- The overrides are applied in three passes and the ORDER matters: dh_donors.ALWAYS (which
-- strips the traps every creature donor carries -- MaxLevel, Category, ShapeshiftMask,
-- ManaCostPct, a zero GCD), then the per-ability set, then identity (id, name, level, family).
-- Identity is last so no data file can rename a spell or move it into another ID block.
--
{notes}
DELETE FROM `spell_dbc` WHERE `ID` BETWEEN {spec.SPELL_ID_BASE} AND {spec.TALENT_SPELL_ID_BASE - 1};
{insert_rows('spell_dbc', list(t.columns), rows)}
""")

    sla = plan.dbcs["SkillLineAbility.dbc"]
    stt = sla.table
    sidx = sla.index()
    # Our own rows, PLUS the stock rows whose ClassMask we widened. The widened ones are not
    # new -- they are existing records edited in place -- but they still need a spell_dbc-side
    # override row, or the server keeps Blizzard's mask and the class silently cannot dual
    # wield while its client-side spellbook says it can.
    slids = sorted([l for _a, _s, l in plan.spells]
                   + [sid for sid, _sp, _b, _a2, _w in getattr(plan, "sla_widenings", [])])
    srows = [[sla.cell(sidx[i], c) for c in range(len(stt.columns))] for i in slids]
    out.append(f"""
-- skilllineability_dbc: one row per ability, ids {min(slids)}-{max(slids)}.
--
-- RaceMask {spec.DH_RACE_MASK} = Night Elf | Blood Elf, ClassMask {spec.DH_CLASS_MASK} = class 10.
-- AcquireMethod is 2 only for the abilities learned at level 1: it grants at creation and
-- re-grants at every login through _LoadSkills -> learnSkillRewardedSpells (Player.cpp:14081)
-- with no level test in that path, so on anything above level 1 it would put the spell in the
-- book immediately. Everything else is 0 and is granted by the module instead.
DELETE FROM `skilllineability_dbc` WHERE `ID` BETWEEN {spec.SLA_ID_BASE} AND {spec.SLA_ID_BASE + 999};
DELETE FROM `skilllineability_dbc` WHERE `ID` IN ({", ".join(str(s) for s, _sp, _b, _a2, _w in getattr(plan, "sla_widenings", [])) or "0"});
{insert_rows('skilllineability_dbc', list(stt.columns), srows)}
""")

    # spell_ranks. NOT a DBC override -- a real world-DB table, loaded by
    # SpellMgr::LoadSpellRanks (SpellMgr.cpp:1287) as
    #     SELECT first_spell_id, spell_id, rank FROM spell_ranks ORDER BY first_spell_id, rank
    # and it is what makes the core understand that eight records are one ability. Without it:
    # Player::removeSpell never drops the lower rank on learn, SpellMgr::GetFirstSpellInChain
    # returns the rank itself so every talent spell-mask lookup misses the other seven, and
    # SpellMgr::IsRankedSpellNonStackableInSpellBook cannot hide the duplicates.
    #
    # The loader ERRORS on a chain of length 1, so single-rank abilities must not appear here.
    # That is why this is driven off plan.rank_chains, which build_spells only appends to when
    # an ability actually emitted more than one record.
    chains = getattr(plan, "rank_chains", [])
    if chains:
        rank_rows = []
        # `rank_ids`, NOT `ids`. This loop used to bind `ids` and shadowed the record-id list
        # built at the top of the function, so check #36 compared the DBC against the last
        # ladder's five ranks and reported 5 rows where 95 had been written.
        for _key, rank_ids in chains:
            first = rank_ids[0]
            for n, sid in enumerate(rank_ids, start=1):
                rank_rows.append([first, sid, n])
        firsts = ", ".join(str(c[1][0]) for c in chains)
        out.append(f"""
-- spell_ranks: {len(chains)} ladder(s), {len(rank_rows)} rank(s).
--
-- Deleted by first_spell_id rather than by range: this table is shared with every other
-- feature on the realm and a range delete would take out any ladder that happened to sit
-- between our lowest and highest id.
DELETE FROM `spell_ranks` WHERE `first_spell_id` IN ({firsts});
{insert_rows('spell_ranks', ['first_spell_id', 'spell_id', 'rank'], rank_rows)}
""")

    # The count that must match, asserted rather than assumed: every Demon Hunter record in the
    # client's Spell.dbc has a spell_dbc row, and vice versa.
    in_dbc = sorted(i for i in d.ids()
                    if spec.SPELL_ID_BASE <= i < spec.TALENT_SPELL_ID_BASE)
    checks.expect(in_dbc == ids, "#36",
                  f"every Demon Hunter Spell.dbc record has a spell_dbc row: "
                  f"{len(in_dbc)} in the DBC, {len(ids)} in the SQL"
                  + ("" if in_dbc == ids else
                     f" -- only in the DBC: {sorted(set(in_dbc) - set(ids))}"))

    summary = (f"-- {len(plan.spells)} abilities + "
               f"{len(getattr(plan, 'second_records', []))} second records = {len(ids)} "
               f"records, {len(slids)} skill-line rows")
    return BANNER.format(name=spec.SQL_FILES["spells"], summary=summary) + "\n".join(out)


def emit_talents(plan, checks):
    """03_talents.sql -- the three trees, and the rank spells they point at."""
    talents = getattr(plan, "talents", None)
    if not talents:
        return BANNER.format(name=spec.SQL_FILES["talents"],
                             summary="-- NOT EMITTED: dh_talents.py absent") + "\n"

    out = []
    d = plan.dbcs["Spell.dbc"]
    t = d.table
    idx = d.index()
    ids = sorted(plan.talent_spells)
    rows = [[d.cell(idx[i], c) for c in range(len(t.columns))] for i in ids]
    out.append(f"""
--
-- spell_dbc: {len(ids)} talent RANK records, ids {min(ids)}-{max(ids)}.
--
-- A talent rank is a spell. "+2% per rank, five ranks" is five records carrying 2, 4, 6, 8 and
-- 10, and one Talent.dbc row listing all five ids. That is how every stock tree is built.
--
-- These do NOT carry dh_donors.ALWAYS. That set turns a donor into a usable ABILITY -- energy
-- cost, 1-second GCD, ManaCostPct zeroed -- and it also zeroes ShapeshiftMask, which is exactly
-- the cell the Metamorphosis-gated passives depend on. Applying it here would silently disable
-- every form-gated talent in the trees.
DELETE FROM `spell_dbc` WHERE `ID` BETWEEN {spec.TALENT_SPELL_ID_BASE} AND {spec.TALENT_SPELL_ID_MAX - 1};
{insert_rows('spell_dbc', list(t.columns), rows)}
""")

    tal = plan.dbcs["Talent.dbc"]
    tt = tal.table
    tidx = tal.index()
    tids = sorted(tid for _t, tid, _r in talents)
    trows = [[tal.cell(tidx[i], c) for c in range(len(tt.columns))] for i in tids]
    per_tab = {}
    for talent, _tid, _r in talents:
        per_tab.setdefault(talent.tab, []).append(talent)
    shape = "\n".join(
        f"--   {tab:10s} {len(v):2d} talents, "
        f"{sum(x.ranks for x in v):3d} points, tiers "
        f"{min(x.tier for x in v)}-{max(x.tier for x in v)}"
        for tab, v in sorted(per_tab.items()))
    out.append(f"""
-- talent_dbc: {len(tids)} talents, ids {min(tids)}-{max(tids)}.
--
{shape}
--
-- THE TAB ROWS THEMSELVES ARE IN 00_class.sql, and they are the half that needs the core patch:
-- DBCStores.cpp:551-556 drops any TalentTab whose ClassMask is not inside CLASSMASK_ALL_PLAYABLE,
-- and class 10's bit is not in that macro on a stock core. Without build/patches/0001 every row
-- below loads correctly and is then never shown.
--
-- PrereqRank_1 is a ZERO-BASED floor (Player.cpp:14329): a prerequisite written "@ 4" in the
-- design means four points already spent in the parent talent.
DELETE FROM `talent_dbc` WHERE `ID` BETWEEN {spec.TALENT_ID_BASE} AND {spec.TALENT_ID_BASE + 999};
{insert_rows('talent_dbc', list(tt.columns), trows)}
""")

    try:
        import dh_talents
        scripts = getattr(dh_talents, "SCRIPT_NAMES", {}) or {}
    except ImportError:
        scripts = {}
    if scripts:
        # SCRIPT_NAMES is keyed by GRID POSITION, not by spell id -- dh_talents.py cannot know
        # the ids because the generator allocates them. Resolve each position to that talent's
        # rank records and bind the script to EVERY rank: a talent's ranks are separate spells,
        # and a script bound to rank 1 alone would silently stop working the moment the player
        # put a second point in.
        srows = []
        for pos, script in sorted(scripts.items()):
            ranks = getattr(plan, "talent_ranks_by_pos", {}).get(tuple(pos), ())
            if not checks.expect(bool(ranks), "#57",
                                 f"spell_script_names names talent {pos}, which has ranks"):
                continue
            srows.extend([sid, script] for sid in ranks)
        if srows:
            sids = sorted(r[0] for r in srows)
            out.append(f"""
-- spell_script_names: the talents that need an existing core SpellScript rather than a pure DBC
-- clone. One row PER RANK -- a talent's ranks are separate spell ids, and binding rank 1 alone
-- would silently stop working when the player put a second point in.
--
-- Reusing a script is only safe when it is class-agnostic; dh_talents.py records why for each.
-- DELETED BY OUR OWNED ID RANGE, not by the list about to be inserted.
--
-- The narrower form is the obvious one and it is wrong in a way that only shows up months
-- later: a binding that STOPS being emitted is never named again, so nothing ever removes it.
-- Three talents whose script was unbound kept their rows through a full regenerate and went on
-- logging "did not match dbc effect data" once per rank at every boot, because the DELETE only
-- covered the rows the same statement was re-adding.
--
-- The range is this feature's own talent-rank band, so it cannot touch another feature's rows.
DELETE FROM `spell_script_names`
 WHERE `spell_id` BETWEEN {spec.TALENT_SPELL_ID_BASE} AND {spec.TALENT_SPELL_ID_MAX - 1};
{insert_rows('spell_script_names', ['spell_id', 'ScriptName'], srows)}
""")

    # ranks + triggers, not ranks alone. A trigger row is a real Spell.dbc record in the same
    # band and it has to be counted, or this check fails the moment a proc talent exists.
    n_ranks = sum(t2.ranks for t2, _i, _r in talents)
    n_trig = len(getattr(plan, "talent_triggers", []))
    checks.expect(len(ids) == n_ranks + n_trig, "#49",
                  f"every talent rank and trigger has a spell record "
                  f"({len(ids)} records for {n_ranks} ranks + {n_trig} triggers)")

    summary = (f"-- {len(tids)} talents, {len(ids)} rank records, "
               f"{sum(t2.ranks for t2, _i, _r in talents)} points across three trees")
    return BANNER.format(name=spec.SQL_FILES["talents"], summary=summary) + "\n".join(out)


def _felfury_flows(plan, checks):
    """Resolve dh_spec's Felfury economy from keys and talent names to spell ids.

    Returns (generators, spenders, fel_addict, felheart) where the first three are
    [(spell_id, stacks, label)] sorted by id and the last is [(spell_id, label)].

    ABILITY rows carry the RANK 1 id and nothing else, because the module resolves any rank
    back to it with `SpellMgr::GetFirstSpellInChain` (SpellMgr.cpp:603-609). That is only
    correct because emit_spells writes the `spell_ranks` rows this generator's plan.rank_chains
    drives; a ladder missing from that table would leave every rank above 1 costing and
    granting nothing, so the check below is not decoration.

    GENERATOR rows carry `total - from_data`: the share the MODULE must add on top of the
    authored `Effect_N = 64 TRIGGER_SPELL -> felfury`. A generator whose whole grant is data
    contributes no row at all -- there is nothing for the module to do on its cast.
    """
    d = plan.dbcs["Spell.dbc"]
    t = d.table
    idx = d.index()
    chained = {key for key, _ranks in getattr(plan, "rank_chains", [])}
    by_key = {a.key: a for a in spec.ABILITIES}
    felfury_id = spec.spell_id_for("felfury", 0)

    def ability_id(key):
        if key in spec.SINGLES_ORDER:
            return spec.single_spell_id(key)
        return spec.spell_id_for(key, 0)

    def module_share(sid, total, label):
        """`total` minus what the record already grants on its own, or None if unusable.

        Counted off the EMITTED record and never declared, because an authored
        `Effect_N = 64 SPELL_EFFECT_TRIGGER_SPELL -> felfury` reaches the pool through
        Unit::_TryStackingOrRefreshingExistingAura (Unit.cpp:4615), whose ModStackAmount(1) at
        :4665 is worth one stack and no more. Whether a given record has one is decided in
        fs_abilities.py (`second_records`) or inherited from the transplanted Ascension record;
        counting it here means the module's share cannot drift from the data either way.
        """
        if not checks.expect(sid in idx, "#70",
                             f"Felfury generator {label!r} has a Spell.dbc record ({sid})"):
            return None, 0
        row = idx[sid]
        from_data = sum(1 for k in (1, 2, 3)
                        if d.get_i32(row, t.index_of[f"Effect_{k}"]) == 64
                        and d.get_i32(row, t.index_of[f"EffectTriggerSpell_{k}"]) == felfury_id)
        # More authored effects than the ability advertises would have the record and the
        # tooltip disagreeing, and the module cannot subtract its way out of it.
        checks.expect(from_data <= total, "#70",
                      f"Felfury generator {label!r} ({sid}) carries {from_data} authored "
                      f"`Effect 64 -> {felfury_id}` for an advertised total of {total}")
        return total - from_data, from_data

    generators, spenders = [], []

    for key, total in sorted(spec.FELFURY_ABILITY_GENERATORS.items()):
        sid = ability_id(key)
        share, from_data = module_share(sid, total, key)
        if share:
            generators.append((sid, share, f"{key} -- {total} total, {from_data} from data"))

    for key, cost in sorted(spec.FELFURY_ABILITY_SPENDERS.items()):
        sid = ability_id(key)
        ability = by_key.get(key)
        checks.expect(sid in idx, "#70",
                      f"Felfury spender {key!r} has a Spell.dbc record ({sid})")
        # A ladder that is not in spell_ranks is a ladder whose ranks 2..n are free.
        if ability is not None and ability.ranks > 1:
            checks.expect(key in chained, "#71",
                          f"Felfury spender {key!r} has {ability.ranks} ranks and a spell_ranks "
                          f"chain, without which only rank 1 would cost Felfury")
        spenders.append((sid, cost, f"{key} -- {cost} per cast"))

    # ---- the talent-granted half -------------------------------------------------------------
    ranks_by_name = {t.name: r for t, _i, r in getattr(plan, "talents", [])}
    named = (list(spec.FELFURY_TALENT_GENERATORS) + list(spec.FELFURY_TALENT_SPENDERS)
             + list(spec.FEL_ADDICT_TALENTS) + list(spec.FELHEART_TALENTS))

    if not ranks_by_name:
        if named:
            checks.skip("#72", "no talent records were built; the Felfury talent tables are "
                               "emitted empty and every talent generator/spender is inert")
        return generators, spenders, [], []

    def talent_id(name, tag):
        ranks = ranks_by_name.get(name)
        if not checks.expect(bool(ranks), "#72",
                             f"{tag} talent {name!r} is declared in one of the three tab "
                             f"tables -- dh_spec names it, so a missing talent is a rename"):
            return None
        # One rank, because plan 3.4 makes every granted active a one-rank talent: a talent rank
        # IS a spell rank, so a second rank would deactivate the first and the module's single
        # id would stop matching the spell the player actually casts.
        if not checks.expect(len(ranks) == 1, "#73",
                             f"{tag} talent {name!r} has exactly one rank ({len(ranks)} found); "
                             f"more would need a spell_ranks chain the module could walk"):
            return None
        return ranks[0]

    for name, total in sorted(spec.FELFURY_TALENT_GENERATORS.items()):
        sid = talent_id(name, "Felfury generator")
        if not sid:
            continue
        share, from_data = module_share(sid, total, name)
        if share:
            generators.append((sid, share, f"{name} -- {total} total, {from_data} from data"))

    for name, cost in sorted(spec.FELFURY_TALENT_SPENDERS.items()):
        sid = talent_id(name, "Felfury spender")
        if sid:
            spenders.append((sid, cost, f"{name} -- {cost} per cast"))

    fel_addict = []
    for name, bonus in sorted(spec.FEL_ADDICT_TALENTS.items()):
        sid = talent_id(name, "Fel Addict")
        if sid:
            fel_addict.append((sid, bonus, f"{name} -- +{bonus} max Felfury"))

    felheart = []
    for name in sorted(spec.FELHEART_TALENTS):
        sid = talent_id(name, "Felheart")
        if sid:
            felheart.append((sid, name))

    return (sorted(generators), sorted(spenders), sorted(fel_addict), sorted(felheart))


def _felfury_block(plan, checks):
    """The Felfury/Inner Demon half of dh_progression.h, as C++ text."""
    felfury_id = spec.spell_id_for("felfury", 0)
    inner_demon_id = spec.spell_id_for("inner_demon", 0)

    # FELFURY_STACK_CEILING is READ OFF THE RECORD, not declared. It is the DBC cell
    # `Aura::ModStackAmount` clamps the pure-data +1 against (SpellAuras.cpp:973-980), so a
    # constant that merely agreed with dh_spec would be a second opinion about a number only
    # Spell.dbc actually holds. Reading it is what makes the module's static_assert meaningful.
    d = plan.dbcs["Spell.dbc"]
    idx = d.index()
    ceiling = 0
    if checks.expect(felfury_id in idx, "#74",
                     f"the felfury record ({felfury_id}) is in Spell.dbc -- the whole resource "
                     f"is this one row"):
        ceiling = d.get_i32(idx[felfury_id], d.table.index_of["CumulativeAura"])

    checks.expect(inner_demon_id in idx, "#74",
                  f"the inner_demon record ({inner_demon_id}) is in Spell.dbc")

    wanted = spec.FELFURY_MAX_STACKS + max(spec.FEL_ADDICT_TALENTS.values(), default=0)
    checks.expect(ceiling >= wanted, "#74",
                  f"the felfury record's CumulativeAura ({ceiling}) can hold a fully talented "
                  f"pool ({wanted}); below that the data +1 clamps low and Fel Addict does "
                  f"nothing")

    generators, spenders, fel_addict, felheart = _felfury_flows(plan, checks)

    def flow_array(name, rows, why):
        head = "\n".join("// " + line for line in why)
        if not rows:
            return f"{head}\nconstexpr std::array<DhFelfuryFlow, 0> {name} = {{}};"
        body = "\n".join(f"    DhFelfuryFlow{{ {sid}, {n} }},   // {label}"
                         for sid, n, label in rows)
        return (f"{head}\n"
                f"constexpr std::array<DhFelfuryFlow, {len(rows)}> {name} =\n"
                f"{{{{\n{body}\n}}}};")

    generators_array = flow_array("kDhFelfuryGenerators", generators, (
        "`stacks` is what the MODULE adds on top of the authored `Effect 64 -> felfury`, NOT",
        "the ability's advertised total. A generator whose whole grant is data has no row here",
        "and needs none: the resource aura's own ceiling is enforced when that +1 lands.",
    ))
    spenders_array = flow_array("kDhFelfurySpenders", spenders, (
        "`stacks` is the cost. Inner Demon is deliberately absent -- it eats the whole pool,",
        "which is not a cell, and a row here would debit it twice.",
    ))
    fel_addict_array = flow_array("kDhFelAddictRanks", fel_addict, (
        "`stacks` is how much the talent raises the cap. Ascension's own aura 107 carries",
        "SpellModOp 31, which does not exist here (MAX_SPELLMOD is 32, SpellDefines.h:109), so",
        "the cap has to be arithmetic in the module rather than a spell mod.",
    ))

    if felheart:
        felheart_body = "\n".join(f"    {sid},   // {label}" for sid, label in felheart)
        felheart_array = (f"constexpr std::array<uint32, {len(felheart)}> kDhFelheartRanks =\n"
                          f"{{{{\n{felheart_body}\n}}}};")
    else:
        felheart_array = "constexpr std::array<uint32, 0> kDhFelheartRanks = {};"

    return f"""
// =============================================================================================
// THE FELFURY RESOURCE -- read by src/felfury_core.cpp
// =============================================================================================
//
// Declared in tools/dh_spec.py and resolved to ids here, so that "which spells move the
// resource" is one fact in one place. See the comment above dh_spec.FELFURY_ABILITY_GENERATORS.

// The band every Felsworn spell id falls in, used as the cheap first test on hooks that run for
// every cast and every aura application on the realm. MAX is EXCLUSIVE.
constexpr uint32 FELSWORN_SPELL_ID_MIN = {spec.SPELL_ID_BASE};
constexpr uint32 FELSWORN_SPELL_ID_MAX = {spec.TALENT_SPELL_ID_MAX};

constexpr uint32 FELFURY_SPELL_ID     = {felfury_id};   // the resource itself
constexpr uint32 INNER_DEMON_SPELL_ID = {inner_demon_id};   // the form it is spent on

// The untalented cap the module enforces in code, and the CumulativeAura cell on the felfury
// record -- which must be the FULLY TALENTED maximum, because the pure-data +1 goes through
// Aura::ModStackAmount and clamps against it (SpellAuras.cpp:973-980).
constexpr uint8  FELFURY_MAX_STACKS    = {spec.FELFURY_MAX_STACKS};
constexpr uint8  FELFURY_STACK_CEILING = {ceiling};

// Milliseconds of Inner Demon bought by one Felfury. Ascension multiplies 803465's +5000 ms
// SPELLMOD_DURATION by the stacks spent; Player::ApplySpellMod adds a flat mod exactly once and
// never scales it by a stack count (Player.cpp:10077-10078), so the multiply is script.
constexpr uint32 INNER_DEMON_MS_PER_FELFURY = {spec.INNER_DEMON_MS_PER_FELFURY};

// `spellId` is the RANK 1 id of a chain; the module maps any rank back to it with
// SpellMgr::GetFirstSpellInChain (SpellMgr.cpp:603-609), which is why one row covers all nine
// ranks of Sargeron Smite. std::array and not a C array because a table can legitimately be
// EMPTY, and `constexpr DhFelfuryFlow kDhFelAddictRanks[] = {{}};` is ill-formed C++.
//
// The Dh prefix is not decoration: mod-dk-lowlevel is statically linked into the same
// worldserver binary, and two modules defining different types under one name is an ODR
// violation that links without a diagnostic.
struct DhFelfuryFlow
{{
    uint32 spellId;
    uint8  stacks;
}};

{generators_array}

{spenders_array}

{fel_addict_array}

// Felheart's SPELLMOD_ALL_EFFECTS is what raises the resource's three zero-amount haste
// carriers to 1% each. The module recomputes the aura when one of these is learnt or unlearnt.
{felheart_array}
"""


def emit_header(plan, checks):
    """src/dh_progression.h -- the table the module walks on login and level-up.

    A compiled array and not a world table, for the same reason the Death Knight's is: one
    source of truth. This array, the spell_dbc rows the server reads and the Spell.dbc records
    the client reads all come out of the same spec in the same run, so they cannot drift. There
    is also no hot reload for spell data -- LoadDBCStores has exactly one call site,
    World.cpp:384 -- so nothing is gained by making it runtime-editable.
    """
    # PER-RANK LEVEL, not the ability's. `Ability.level` is when the ability is FIRST learned;
    # a rank ladder's later ranks are gated by `rank_levels`, and using the ability's level for
    # all of them hands a level-1 character rank 8 of everything -- which is exactly what
    # shipped: a level-6 Felsworn had Twin Slice rank 8 (a level-60 record) on the action bar,
    # because Reconcile's `if (grant.level > level) break;` never fired.
    #
    # Derived from the id rather than threaded through plan.spells: the rank index IS the
    # offset within the ability's 20-id block, which is what allocated the id in the first
    # place, so there is no second place for the two to disagree.
    def _grant_level(ability, sid):
        if ability.rank_levels and ability.key in spec.ABILITY_BLOCKS:
            index = sid - spec.spell_id_for(ability.key, 0)
            if 0 <= index < len(ability.rank_levels):
                return ability.rank_levels[index]
        return ability.level

    grants = sorted(((_grant_level(a, sid), sid, a.name) for a, sid, _l in getattr(plan, "spells", [])),
                    key=lambda g: (g[0], g[1]))

    # A zero-length array is ILL-FORMED in C++ -- `constexpr DhGrant kDhProgression[] = {};`
    # does not compile. Without this check the generator happily writes a header that breaks
    # the image build about thirty minutes into a Docker compile, and the error names the
    # module rather than the generator that produced it. Emitting nothing is always a bug here:
    # dh_spec.ABILITIES is never legitimately empty.
    # THE CHECK THAT WOULD HAVE CAUGHT IT. Every grant level must equal the SpellLevel on the
    # record it grants. The module gates on the former and the client tooltip shows the latter,
    # so a disagreement is invisible in both halves until somebody notices a level-6 character
    # holding a level-60 rank.
    _d = plan.dbcs["Spell.dbc"]
    _idx = _d.index()
    _lvl_col = _d.table.index_of["SpellLevel"]
    for _lvl, _sid, _name in grants:
        if _sid not in _idx:
            continue
        _record = _d.get_i32(_idx[_sid], _lvl_col)
        checks.expect(_lvl == _record, "#75",
                      f"{_name} ({_sid}): granted at level {_lvl} but its record says "
                      f"SpellLevel {_record} -- the module would hand it out at the wrong level")

    if not checks.expect(bool(grants), "#32",
                         "the progression table is non-empty -- a zero-length C array does not "
                         "compile, and an empty one means the ability records were never built "
                         "(is tools/dh_donors.py present?)"):
        return None

    body = "\n".join(f"    {{ {lvl:3d}, {sid} }},   // {name}" for lvl, sid, name in grants)
    felfury = _felfury_block(plan, checks)
    return f"""/*
 * GENERATED FILE -- DO NOT EDIT.
 *
 * Produced by build/modules/mod-demon-hunter/tools/dhspells.py from tools/dh_spec.py.
 * Regenerate with `scripts/build-client-patch.sh`.
 *
 * WHY THE PROGRESSION IS A COMPILED TABLE AND NOT A WORLD TABLE
 * ------------------------------------------------------------
 * One source of truth. This array, the spell_dbc rows the server reads and the Spell.dbc
 * records the client reads all come out of the same spec in the same run, so they cannot
 * drift. A world table would add a load-order dependency and a second thing to keep in sync,
 * and it would buy nothing: changing the progression means regenerating the client DBC and
 * repackaging the client anyway.
 *
 * There is also no hot reload for spell data (LoadDBCStores has exactly one call site,
 * World.cpp:384), so nothing is gained by making this runtime-editable.
 */

#ifndef MOD_DEMON_HUNTER_DH_PROGRESSION_H
#define MOD_DEMON_HUNTER_DH_PROGRESSION_H

#include "Define.h"

#include <array>

// NOT DkGrant. Two statically-linked modules defining different structs with the same name is
// an ODR violation: it links without a diagnostic and misbehaves at run time.
struct DhGrant
{{
    uint8  level;
    uint32 spellId;
}};

// Sorted by level, then spell id. Reconcile() walks this in order and breaks on the first
// entry above the player's level, so the ordering is load-bearing rather than cosmetic.
constexpr DhGrant kDhProgression[] =
{{
{body}
}};
{felfury}
#endif // MOD_DEMON_HUNTER_DH_PROGRESSION_H
"""


def _new_ids_for(plan, dbcfile):
    """Which ids in this file are ours -- i.e. which rows the SQL half has to carry."""
    if dbcfile == "SkillLine.dbc":
        return {sid for sid, _ in spec.SKILL_LINES}
    if dbcfile == "SkillRaceClassInfo.dbc":
        # Three kinds of row, all of which the server needs and only the first of which is
        # "ours" in the usual sense: the class skill lines, the created weapon/armour rows, and
        # the stock rows whose ClassMask was widened in place. The widened ones are existing
        # Blizzard records -- but the override table is what the worldserver reads, so a widened
        # row that is not emitted here keeps its stock mask server-side while the client's DBC
        # says otherwise, which is the worst of both.
        return ({spec.SKILLRACECLASSINFO_ID_BASE + n for n in range(len(spec.SKILL_LINES))}
                | {rid for _s, rid, _d in getattr(plan, "srci_created", [])}
                | {rid for rid, _s, _b, _a in getattr(plan, "srci_widenings", [])})
    if dbcfile == "TalentTab.dbc":
        return {t[0] for t in spec.TALENT_TABS}
    if dbcfile == "SpellShapeshiftForm.dbc":
        return {spec.SHAPESHIFT_FORM_ID}
    return set()


# =============================================================================================
# Driver
# =============================================================================================

def build_client_files(args, checks):
    """Extract, patch and collect the non-DBC half of the archive.

    Returns [(local_path, archived_name)] ready to hand to mpqlib.write_patch.

    Every stock file is read out of the CLIENT's own archive chain at the priority the client
    itself would resolve -- not out of a checked-in copy, because there is not one (dh_spec
    CLIENT_PATCHES explains why). `patch --fuzz=0` is deliberate: a hunk that no longer applies
    exactly is a ChromieCraft or Blizzard change underneath us, and the only safe response is to
    stop and make somebody look at it.
    """
    import shutil
    import tempfile

    out = []
    stage = os.path.join(args.out, "client")
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage, exist_ok=True)

    # Open every archive in the chain ONCE. mpqlib.resolve reopens the whole chain per call,
    # which is fine for one lookup and absurd for a dozen.
    #
    # THE ARCHIVE WE ARE ABOUT TO WRITE IS EXCLUDED FROM THE CHAIN WE READ, and this is not
    # tidiness -- it is the same self-consumption bug the DBC half already guards against in
    # _chained_files(), in the one place it was left unguarded. A previously installed
    # patch-Z.MPQ sits at the TOP of the resolved chain (0x46, above patch-3 at 0x45), so
    # read_stock would hand back the ALREADY-PATCHED CharacterCreate.lua and patch(1) would
    # answer "Reversed (or previously applied) patch detected" and skip every hunk. The build
    # then succeeds with UI files that only happen to be right because the last build made them
    # so -- and the first time it runs against a client without the archive, or with an older
    # one, it produces a silently different result. "Stock" has to mean stock.
    skip_rel = {os.path.basename(name).lower() for name in spec.MPQ_SLOTS.values()}
    chain = [(p, rel) for p, rel in sorted(mpqlib.chain(args.client_data), reverse=True)
             if os.path.basename(rel).lower() not in skip_rel]
    handles = [(p, rel, mpqlib.Mpq.open(os.path.join(args.client_data, rel)))
               for p, rel in chain]

    def read_stock(archived):
        for prio, rel, m in handles:
            if m.has(archived):
                return m.read(archived), prio, rel
        return None, None, None

    for patch_name, archived in spec.CLIENT_PATCHES:
        patch_path = os.path.join(spec.CLIENT_DIR, patch_name)
        if not checks.expect(os.path.exists(patch_path), "#19",
                             f"{patch_name} exists in {os.path.relpath(spec.CLIENT_DIR, spec.REPO_ROOT)}"):
            continue
        blob, prio, rel = read_stock(archived)
        if not checks.expect(blob is not None, "#20",
                             f"{archived} resolves in the client archive chain"):
            continue

        # patch(1) wants a real tree. The patch headers are `a/Interface/...` -> `b/...`, so
        # -p1 strips the a/ and the file has to sit at the header's path inside the temp root.
        with tempfile.TemporaryDirectory() as tmp:
            rel_posix = archived.replace("\\", "/")
            target = os.path.join(tmp, rel_posix)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(blob)
            proc = subprocess.run(
                ["patch", "-p1", "--fuzz=0", "--no-backup-if-mismatch", "-i", patch_path],
                cwd=tmp, capture_output=True, text=True)
            ok = checks.expect(
                proc.returncode == 0, "#21",
                f"{patch_name} applies cleanly to the stock {archived} "
                f"(from {rel}, priority 0x{prio:02x})"
                + ("" if proc.returncode == 0 else
                   f"\n         patch said: {proc.stdout.strip()} {proc.stderr.strip()}"))
            if not ok:
                continue
            patched = open(target, "rb").read()

        checks.expect(patched != blob, "#22",
                      f"{archived} actually changed ({len(blob):,} -> {len(patched):,} bytes)")
        local = os.path.join(stage, rel_posix)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as f:
            f.write(patched)
        out.append((local, archived))
        print(f"   {archived:44s} {len(blob):>8,} -> {len(patched):>8,}  "
              f"(stock from {rel})")

    # The class-icon atlases. Built here rather than expected to be lying around, so that one
    # command produces a complete archive -- an icon step somebody has to remember is an icon
    # step somebody forgets, and the failure mode is a class button with no art rather than an
    # error.
    icon_dir = os.path.join(args.out, "icons")
    missing = [n for n, _a in spec.CLIENT_ICONS
               if not os.path.exists(os.path.join(icon_dir, n))]
    if missing:
        print(f"   building {len(missing)} class-icon atlas(es) with tools/dh_icons.py")
        proc = subprocess.run(
            [sys.executable, os.path.join(TOOLS_DIR, "dh_icons.py"),
             "--client-data", args.client_data, "--out", icon_dir],
            capture_output=True, text=True)
        checks.expect(proc.returncode == 0, "#23",
                      "tools/dh_icons.py rebuilt the class-icon atlases"
                      + ("" if proc.returncode == 0 else
                         f"\n         it said: {proc.stdout.strip()[-500:]} "
                         f"{proc.stderr.strip()[-500:]}"))

    for icon_name, archived in spec.CLIENT_ICONS:
        local = os.path.join(icon_dir, icon_name)
        if not checks.expect(os.path.exists(local), "#24",
                             f"{icon_name} is present in {icon_dir}"):
            continue
        out.append((local, archived))
        print(f"   {archived:44s} {os.path.getsize(local):>8,} bytes  (icon)")

    for _p, _r, m in handles:
        m.close()
    return out


def sync_addon_spell_ids(checks):
    """Rewrite the addon's two spell-id constants from the spec.

    The addon has to name Double Jump and Glide by numeric id -- it casts them through a secure
    button, and there is no way to look a spell up by name from Lua that is safe in combat. That
    makes the ids a THIRD copy of a number that already exists in dh_spec and in the emitted
    Spell.dbc, and a third copy is a third thing to get wrong.

    It has been wrong once already, which is why this function exists rather than a comment
    asking someone to remember: the file shipped with `91000` and `91001`, and 91000 is not a
    placeholder, it is **Demon's Bite**. A player pressing jump in mid-air would have swung at
    whatever they were looking at. 91001 does not exist at all, so Glide would silently do
    nothing. Neither failure logs.

    Rewriting rather than reading a generated Lua file: the addon must work when it is copied
    into a client on its own, with no generated companion file next to it.
    """
    path = os.path.join(spec.REPO_ROOT, "client", "addons", "mod-felsworn",
                        "Felsworn", "Felfury.lua")
    if not checks.expect(os.path.exists(path), "#51",
                         f"the addon is where the generator expects it "
                         f"({os.path.relpath(path, spec.REPO_ROOT)})"):
        return
    # WHICH IDS THE ADDON NEEDS IS A PROPERTY OF THE CLASS, not of this function.
    #
    # The Demon Hunter needed two: Double Jump and Glide, because its addon bound them to keys
    # and had to cast them by numeric id. Felsworn has neither -- it has no movement toys at all
    # -- and instead needs the ids the UI has to WATCH: the Felfury stack aura, so the resource
    # can be drawn, and Inner Demon, so the form can be. An id the addon does not declare is
    # skipped rather than failed, so the same generator serves a class whose addon is smaller.
    # Not a spell id, but the same problem and the same fix: a number the addon draws that the
    # data owns. It was hand-written as 5 and the pool later became 6.
    want = {"FS_FELFURY_CAP": spec.FELFURY_MAX_STACKS}
    for lua_name, key in (("FS_SPELL_FELFURY", "felfury"),
                          ("FS_SPELL_INNER_DEMON", "inner_demon"),
                          ("DH_SPELL_DOUBLE_JUMP", "double_jump"),
                          ("DH_SPELL_GLIDE", "glide")):
        try:
            want[lua_name] = (spec.spell_id_for(key, 0) if key in spec.ABILITY_BLOCKS
                              else spec.single_spell_id(key))
        except (KeyError, ValueError):
            continue      # this class does not have that ability; nothing to sync
    text = open(path, encoding="utf-8").read()
    out = text
    for name, sid in want.items():
        pat = re.compile(rf"^(local {name}\s*=\s*)(\d+)(.*)$", re.M)
        m = pat.search(out)
        if m is None:
            # Declared in the spec but not in the addon. A skip, not a failure: the two halves
            # of a class can legitimately disagree about which ids the UI cares about.
            checks.skip("#52", f"the addon does not declare {name}; nothing to sync")
            continue
        out = pat.sub(rf"\g<1>{sid}"
                      + ("  -- GENERATED from dh_spec.FELFURY_MAX_STACKS; do not edit"
                         if name == "FS_FELFURY_CAP" else
                         "  -- GENERATED from dh_spec.ABILITY_BLOCKS; do not edit"), out, count=1)
    if out != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        print("   Felfury.lua: " + ", ".join(f"{n}={v}" for n, v in sorted(want.items())))
    # Belt and braces: read it back and confirm both numbers are the ones the spec says, so a
    # regex that silently matched nothing cannot pass.
    back = open(path, encoding="utf-8").read()
    for name, sid in want.items():
        checks.expect(re.search(rf"^local {name}\s*=\s*{sid}\b", back, re.M) is not None, "#69",
                      f"Felfury.lua declares {name} = {sid}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"   {os.path.relpath(path, spec.REPO_ROOT):70s} {len(text):>9,} bytes")
    return path


def do_emit(args, checks):
    db = Db(args.mysql_cmd)
    if not db.probe():
        print(f"!! database unreachable: {db.error}")
        print("   player_class_stats and playercreateinfo cannot be derived without it.")

    print(f"== reading DBCs  chained={args.dbc_in}  stock={args.stock_dbc}")
    plan = Plan(args.dbc_in, args.stock_dbc, checks)
    for name in sorted(plan.sources):
        print(f"   {name:28s} {plan.sources[name]}")

    print("\n== building records")
    plan.build_class_row()
    plan.build_charbaseinfo()
    plan.build_gametables()
    plan.build_shapeshift()
    plan.build_skill_lines()
    plan.build_talent_tabs()
    plan.build_spells(checks)
    plan.build_talents(checks)
    # Last, and it must be last: a transplanted record can reference another record that did
    # not exist yet when it was itself built, so this cannot run inside either builder.
    plan.remap_source_references(checks)

    print(f"\n== SQL -> {os.path.relpath(spec.SQL_DIR, spec.REPO_ROOT)}")
    sql_paths = [
        _write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["class"]),
               emit_class(plan, db, checks)),
        _write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["createinfo"]),
               emit_createinfo(plan, db, checks)),
        _write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["spells"]),
               emit_spells(plan, checks)),
        _write(os.path.join(spec.SQL_DIR, spec.SQL_FILES["talents"]),
               emit_talents(plan, checks)),
    ]

    print("\n== addon spell ids")
    sync_addon_spell_ids(checks)

    header_text = emit_header(plan, checks)
    if header_text:
        print(f"\n== header -> {os.path.relpath(spec.HEADER_PATH, spec.REPO_ROOT)}")
        _write(spec.HEADER_PATH, header_text)

    print(f"\n== client DBCs -> {os.path.join(args.out, 'dbc')}")
    dbc_out = os.path.join(args.out, "dbc")
    os.makedirs(dbc_out, exist_ok=True)
    dbc_paths = {}
    for t in spec.DBC_TABLES:
        p = os.path.join(dbc_out, t.dbc_file)
        plan.dbcs[t.dbc_file].save(p)
        dbc_paths[t.dbc_file] = p
        print(f"   {t.dbc_file:28s} {os.path.getsize(p):>10,} bytes  "
              f"{len(plan.dbcs[t.dbc_file].records):>6,} records")
    for gt in spec.GAMETABLES:
        p = os.path.join(dbc_out, gt.dbc_file)
        plan.gametables[gt.dbc_file].save(p)
        dbc_paths[gt.dbc_file] = p
        print(f"   {gt.dbc_file:28s} {os.path.getsize(p):>10,} bytes  "
              f"{len(plan.gametables[gt.dbc_file].values):>6,} rows")

    if args.no_mpq:
        print("\n== MPQ skipped (--no-mpq)")
        return checks.summary()

    print(f"\n== client UI + textures -> {os.path.join(args.out, 'client')}")
    client_entries = build_client_files(args, checks)

    print(f"\n== patch archive -> {args.out}")
    mpq_path = os.path.join(args.out, os.path.basename(spec.MPQ_SLOTS[args.slot]))
    entries = [(p, "DBFilesClient\\" + n) for n, p in sorted(dbc_paths.items())]
    entries += client_entries
    # max_files defaults to 64 in mpqlib and this archive now carries 17 DBCs plus the Lua and
    # texture overrides, so it is passed explicitly rather than left to a default that used to
    # be comfortable when the archive held three files.
    read_back = mpqlib.write_patch(mpq_path, entries, max_files=256)
    print(f"   {os.path.basename(mpq_path):28s} {os.path.getsize(mpq_path):>10,} bytes  "
          f"{len(entries)} files")
    by_archived = {a: l for l, a in entries}
    for name, blob in read_back:
        local = by_archived.get(name)
        if not checks.expect(local is not None, "#12",
                             f"{name} came back out of the archive but was never put in"):
            continue
        checks.expect(hashlib.sha256(blob).hexdigest() == sha256_file(local), "#12",
                      f"{name} reads back out of the archive sha256-identical")
    header_size, fmt_version = mpqlib.header_info(mpq_path)
    checks.expect(fmt_version == 1 and header_size == 44, "#13",
                  f"{os.path.basename(mpq_path)} is MPQ v2 (headerSize {header_size}, "
                  f"formatVersion {fmt_version}) -- StormLib's 'V1' writes 32/0 and this client "
                  f"ignores it")

    if args.mpq:
        os.makedirs(os.path.dirname(os.path.abspath(args.mpq)), exist_ok=True)
        with open(mpq_path, "rb") as s, open(args.mpq, "wb") as d:
            d.write(s.read())
        print(f"   installed -> {args.mpq}")

    return checks.summary()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=spec.DEFAULT_OUT_DIR)
    ap.add_argument("--dbc-in", default=None,
                    help="chained input, normally <out>/dbc (the Death Knight generator's "
                         "output). Files missing from it fall back to --stock-dbc.")
    ap.add_argument("--stock-dbc", default=spec.DEFAULT_DBC_IN)
    ap.add_argument("--client-data", default=spec.DEFAULT_CLIENT_DATA,
                    help="client Data directory. Read only, and read for a REASON: the stock "
                         "GlueXML and FrameXML files this archive patches are only available "
                         "from the client's own archives.")
    ap.add_argument("--slot", default=spec.DEFAULT_MPQ_SLOT, choices=sorted(spec.MPQ_SLOTS))
    ap.add_argument("--mpq", default=None, help="also install the finished archive here")
    ap.add_argument("--no-mpq", action="store_true",
                    help="write DBCs but do not build the archive")
    ap.add_argument("--mysql-cmd", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.dbc_in is None:
        args.dbc_in = os.path.join(args.out, "dbc")

    checks = Checks(args.verbose)
    return do_emit(args, checks)


if __name__ == "__main__":
    sys.exit(main())
