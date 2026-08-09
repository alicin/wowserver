#!/usr/bin/env python3
"""Generate mod-utility-npcs' spawn migration from live world-DB data.

    ./gen_spawns.py            emit the SQL and the generated header (needs the world DB)
    ./gen_spawns.py --check    re-verify what is already on disk; writes nothing
    ./gen_spawns.py --plan     print the placement plan and the counts, emit nothing

Emits, deterministically:

    <module>/data/sql/db-world/base/2026_08_08_20_utility_npcs_spawns.sql
    <module>/src/utility_npcs_range.h        the guid range the C++ half enforces at boot

WHAT THIS TOOL WILL NOT DO
--------------------------
It never writes to the database. `Db.query` refuses anything that is not SELECT or SHOW, and the
SQL it produces is applied by UpdateFetcher at worldserver boot like every other module
migration -- which is exactly how mod-dk-lowlevel deployed itself to a fresh VPS with no manual
SQL step. It also never invents a coordinate: every position in the output is derived from a row
that already exists on the realm.

GENERATOR INVARIANTS
--------------------
Hard failures, in --emit and --check alike.

  #1  The `creature` column list this tool writes is EXACTLY the live table's column list, in
      order. AzerothCore's schema moves (this revision has no `modelid1` on creature_template and
      no `id2`/`id3` on creature -- both of which older guides still tell you to write), and a
      column-count mismatch is an apply-time abort part-way through a migration.
  #2  Every emitted guid is inside [GUID_FIRST, GUID_LAST] and unique.
  #3  The highest emitted guid is EXACTLY GUID_LAST. This is the pin that keeps
      ObjectMgr's `_creatureSpawnId = MAX(guid) + 1` above the reserved block, so `.npc add`
      can never hand out an id this module will later delete. See npc_spec.py.
  #4  GUID_LAST < 0xFFFFFF - MIN_HEADROOM_ABOVE. Past 0xFFFFFF the worldserver does not
      complain, it calls World::StopNow (ObjectMgr.cpp:7657).
  #5  The live `creature` table holds NOTHING inside the reserved block that this module did not
      put there -- checked by entry id, not by trust. Also: MAX(guid) outside the block is still
      below GUID_FIRST, i.e. the upstream world DB has not grown into it.
  #6  Every entry in the spec exists in creature_template, is faction 35 (FACTION_FRIENDLY,
      SharedDefines.h:189), has at least one creature_template_model row, and has a non-empty
      ScriptName -- an entry whose module was uninstalled would otherwise spawn a mute statue.
  #7  Every emitted row is stationary and inert: MovementType 0, wander_distance 0, phaseMask 1,
      spawnMask 1, empty ScriptName (so the TEMPLATE's script wins), and npcflag / unit_flags /
      dynamicflags all 0, which ObjectMgr::ChooseCreatureFlags (ObjectMgr.cpp:1659-1676) reads as
      "inherit from the template" rather than as "clear the flag".
  #8  Every INSERT in the emitted file is covered by a DELETE earlier in the same file.
      UpdateFetcher keys a migration on its bare filename plus a SHA1 of the contents and
      re-applies a CHANGED file IN FULL, so a bare INSERT breaks on the second edit.
  #9  Every surprise anchor is corroborated: some existing creature or gameobject spawn is within
      CORROBORATION_RADIUS yards horizontally and CORROBORATION_DZ vertically. A game_tele row is
      curated, but it is curated for a PLAYER teleport, which tolerates a drop; a creature does
      not fall to the floor on spawn, it hovers where you put it.
 #10  Every one of the ten playable races has a start anchor, and no anchor is on map 609
      (Ebon Hold) -- that map has no innkeeper and no reason to hold a shop.
 #11  Two anchors on the same map are never closer than MIN_ANCHOR_SEPARATION yards, so no two
      rings can intersect.
 #12  src/utility_npcs_range.h agrees with the SQL: same range, same entries, same row count.
 #13  Every emitted value fits its column's declared type. This realm runs STRICT_TRANS_TABLES
      (verified: sql_mode is ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,
      ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION on MySQL 8.4.11), so an out-of-range
      value does not clamp -- it aborts the migration PART-WAY THROUGH, leaving the realm with
      some of these NPCs and not others. `EXPLAIN <the statement>` catches a syntax error or a
      wrong column count; only this catches a tinyint holding 300.
"""

import argparse
import math
import os
import re
import shlex
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import npc_spec as spec                                        # noqa: E402


# ==============================================================================================
# check plumbing
# ==============================================================================================

class Checks:
    def __init__(self):
        self.rows = []

    def _add(self, status, tag, msg):
        self.rows.append((status, tag, msg))
        print(f"  [{status:4}] {tag:4} {msg}")

    def ok(self, tag, msg):
        self._add("PASS", tag, msg)

    def fail(self, tag, msg):
        self._add("FAIL", tag, msg)

    def skip(self, tag, msg):
        self._add("SKIP", tag, msg)

    def expect(self, cond, tag, msg, detail=""):
        (self.ok if cond else self.fail)(
            tag, msg + (f"  -- {detail}" if detail and not cond else ""))
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


# ==============================================================================================
# read-only database access
# ==============================================================================================

DEFAULT_MYSQL_CMD = (
    "docker compose -f {repo}/deploy/docker-compose.yml exec -T mysql "
    "mysql --defaults-extra-file=/etc/mysql/backup.cnf"
)


class Db:
    """One read-only SELECT path. Nothing here ever writes.

    Same shape as mod-dk-lowlevel/tools/dkspells.py Db, deliberately: two generators in one repo
    should not have two ways to reach the same database. `--mysql-cmd` exists so this can be
    pointed at the remote realm over ssh without editing the file.
    """

    def __init__(self, cmd_template=None, schema="acore_world"):
        self.cmd = shlex.split((cmd_template or DEFAULT_MYSQL_CMD).format(repo=spec.REPO_ROOT))
        self.schema = schema
        self._live = None
        self.error = ""

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


# ==============================================================================================
# SQL literal formatting
# ==============================================================================================

_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\x00": "\\0", "\x1a": "\\Z"}


def sql_str(s):
    """Quote for MySQL with backslash escapes.

    Correct only because NO_BACKSLASH_ESCAPES is absent from this realm's sql_mode -- verified:
    ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,
    ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION on MySQL 8.4.11.
    """
    return "'" + "".join(_ESCAPES.get(c, c) for c in s) + "'"


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def f32_text(value):
    """Shortest decimal that round-trips to the same float32 bits.

    The destination columns are FLOAT. MySQL prints a FLOAT at about six significant digits,
    which is not always enough to reproduce the stored bits -- so "copy the innkeeper's x
    verbatim" means finding text whose float32 is bit-identical, not reprinting what the client
    showed us.
    """
    assert value == value and abs(value) != float("inf"), f"non-finite float: {value!r}"
    bits = struct.pack("<f", value)
    for precision in range(1, 10):
        text = f"{value:.{precision}g}"
        if struct.pack("<f", float(text)) == bits:
            return text
    raise AssertionError(f"no round-tripping decimal for float32 {value!r}")


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return sql_str(v)
    if isinstance(v, float):
        return f32_text(v)
    return str(int(v))


# ==============================================================================================
# the creature row
# ==============================================================================================
#
# ROSTER NOTES -- why the constant columns are the values they are. Each of these was read out of
# the core, not out of a wiki:
#
#   zoneId, areaId      0. ObjectMgr::LoadCreatures (ObjectMgr.cpp:2325-2333) does not SELECT
#                       them; they are a denormalised cache that the server writes back only when
#                       CONFIG_CALCULATE_CREATURE_ZONE_AREA_DATA is on. 144,975 of this realm's
#                       149,975 existing rows have zoneId 0, so 0 is also what the realm looks
#                       like.
#   spawnMask           1. Non-instanced maps have exactly one difficulty.
#   phaseMask           1. 0 means "visible to nobody" and the core rewrites it to 1 with an
#                       sql.sql error (ObjectMgr.cpp:2472-2476).
#   equipment_id        DERIVED, not constant: MIN(ID) from creature_equip_template for that
#                       entry, else 0. Exactly one of the six has a row -- Beauregard Boneglitter
#                       (601015) ships equip ID 1, item 11343 -- and writing 0 there would strip
#                       the weapon his own module gave him. Writing a nonexistent id logs an
#                       sql.sql error and resets to 0 (ObjectMgr.cpp:2429-2437).
#   spawntimesecs       300. The modal value among this realm's 124 innkeepers (94 of them).
#                       Academic for a faction-35 NPC that cannot die, but it should not be an
#                       outlier.
#   wander_distance     0, and it MUST be 0 while MovementType is 0 or the core logs an sql.sql
#                       error and zeroes it anyway (ObjectMgr.cpp:2462-2470).
#   currentwaypoint     0. No waypoint path.
#   curhealth, curmana  DERIVED from creature_classlevelstats for that template's
#                       (level, unit_class), times HealthModifier -- i.e. the number
#                       Creature::SelectLevel would compute. NOTE these fields are not read at
#                       all while creature_template.RegenHealth = 1, which is true for all six
#                       today (Creature.cpp:1753-1770 takes the GetMaxHealth() branch). They are
#                       filled in correctly anyway so that a future RegenHealth = 0 yields a
#                       normal NPC instead of a 1 hp one.
#   MovementType        0 = IDLE_MOTION_TYPE. A shop does not wander.
#   npcflag             0 -- and 0 here means INHERIT, not "no flags". ObjectMgr::ChooseCreatureFlags
#   unit_flags          (ObjectMgr.cpp:1659-1676) starts from the template and only overrides a
#   dynamicflags        field when the spawn row's value is non-zero. So writing 0 is how the
#                       template's npcflag (1 GOSSIP, or 129 GOSSIP|VENDOR for Gabriella) and its
#                       unit_flags (2 = UNIT_FLAG_NON_ATTACKABLE on three of the six) are
#                       PRESERVED. Copying the template's value in would be equivalent today and
#                       would silently freeze it the day the owning module changes it.
#   ScriptName          '' -- must stay empty. LoadCreatures does
#                       `if (!data.ScriptId) data.ScriptId = cInfo->ScriptID;`
#                       (ObjectMgr.cpp:2394-2395), so an empty spawn-row script means the
#                       template's own script (npc_transmogrifier, npc_assistant, ...) runs.
#                       Naming anything here would replace it and the NPC would do nothing.
#   VerifiedBuild       NULL. Nothing here came out of a sniff.
#   CreateObject        0. The column exists in the schema and is referenced nowhere in
#                       src/server/game -- LoadCreatures does not SELECT it either.
#   Comment             provenance, so a GM who finds one of these with `.npc info` and a
#                       `SELECT * FROM creature WHERE guid = ...` learns where it came from and
#                       what deletes it. Not read by the core.
#
# THERE IS NO `faction` COLUMN ON `creature`. Requirement "give them a friendly faction" is
# therefore satisfied by VERIFYING the template rather than by writing anything: invariant #6
# fails the build unless all six entries are faction 35, which is FACTION_FRIENDLY
# (src/server/shared/SharedDefines.h:189) -- the same faction 5,002 other templates on this realm
# use, including the Spirit Healer and seven of its own innkeepers (Innkeeper Remi Dodoso 19571,
# Ajay Green 29532, ...). Nothing aggroes it and it aggroes nothing.

CREATURE_COLUMNS = (
    "guid", "id", "map", "zoneId", "areaId", "spawnMask", "phaseMask", "equipment_id",
    "position_x", "position_y", "position_z", "orientation", "spawntimesecs", "wander_distance",
    "currentwaypoint", "curhealth", "curmana", "MovementType", "npcflag", "unit_flags",
    "dynamicflags", "ScriptName", "VerifiedBuild", "CreateObject", "Comment",
)

SPAWNTIMESECS = 300


class Placement:
    __slots__ = ("guid", "entry", "map", "x", "y", "z", "o", "kind", "anchor", "comment")

    def __init__(self, entry, mapid, x, y, z, o, kind, anchor):
        self.guid = 0
        self.entry = entry
        self.map = mapid
        self.x, self.y, self.z, self.o = x, y, z, o
        self.kind = kind
        self.anchor = anchor
        self.comment = f"mod-utility-npcs [{kind}] {anchor}"

    def row(self, tmpl):
        return (
            self.guid, self.entry, self.map, 0, 0, 1, 1, tmpl["equipment_id"],
            self.x, self.y, self.z, self.o, SPAWNTIMESECS, 0.0,
            0, tmpl["curhealth"], tmpl["curmana"], 0, 0, 0,
            0, "", None, 0, self.comment,
        )


# ==============================================================================================
# geometry
# ==============================================================================================

def norm_angle(a):
    """Wrap to [0, 2pi). The core stores orientation as a float and normalises on load, but an
    out-of-range value in the table is the kind of thing that makes a later diff unreadable."""
    two_pi = 2.0 * math.pi
    a = math.fmod(a, two_pi)
    return a + two_pi if a < 0.0 else a


def ring(anchor, roster, radius):
    """Place `roster` on a ring of `radius` around `anchor`, fanned off the anchor's facing.

    anchor is (map, x, y, z, o). Z is copied verbatim: the anchor's z IS the floor, which is the
    entire reason we anchor to an existing spawn instead of picking a spot on a map.
    """
    mapid, ax, ay, az, ao = anchor
    out = []
    for i, entry in enumerate(roster):
        theta = ao + math.radians(spec.ANGLE_OFFSETS_DEG[i])
        x = f32(ax + radius * math.cos(theta))
        y = f32(ay + radius * math.sin(theta))
        facing = norm_angle(theta + math.pi) if spec.FACE_INWARD else norm_angle(theta)
        out.append((entry, mapid, x, y, az, f32(facing)))
    return out


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def thin(anchors, sep):
    """Greedy spatial thinning, first-wins, in the order given.

    Order is caller-supplied and deterministic (guid ascending for innkeepers), so the same
    anchors survive on every run and the emitted SQL is stable.
    """
    kept, dropped = [], []
    for a in anchors:
        clash = next((k for k in kept
                      if k["map"] == a["map"]
                      and dist2((k["x"], k["y"], k["z"]), (a["x"], a["y"], a["z"])) < sep * sep),
                     None)
        (dropped if clash else kept).append(a if not clash else dict(a, clashed_with=clash))
    return kept, dropped


# ==============================================================================================
# live data
# ==============================================================================================

def fetch_templates(db, checks):
    """The six entries, plus everything the spawn row needs to derive from them."""
    ids = ",".join(str(e) for e in sorted(spec.NPCS))
    rows = db.query(
        "SELECT ct.entry, ct.name, ct.subname, ct.faction, ct.npcflag, ct.unit_flags, "
        "       ct.minlevel, ct.maxlevel, ct.unit_class, ct.exp, ct.HealthModifier, "
        "       ct.ManaModifier, ct.RegenHealth, ct.ScriptName, "
        "       (SELECT COUNT(*) FROM creature_template_model m WHERE m.CreatureID = ct.entry), "
        "       IFNULL((SELECT MIN(e.ID) FROM creature_equip_template e "
        "               WHERE e.CreatureID = ct.entry), 0) "
        f"FROM creature_template ct WHERE ct.entry IN ({ids}) ORDER BY ct.entry")
    out = {}
    for r in rows:
        out[int(r[0])] = dict(
            entry=int(r[0]), name=r[1], subname=r[2] or "", faction=int(r[3]),
            npcflag=int(r[4]), unit_flags=int(r[5]), minlevel=int(r[6]), maxlevel=int(r[7]),
            unit_class=int(r[8]), exp=int(r[9]), health_mod=float(r[10]),
            mana_mod=float(r[11]), regen_health=int(r[12]), script=r[13] or "",
            n_models=int(r[14]), equipment_id=int(r[15]))

    checks.expect(set(out) == set(spec.NPCS), "#6",
                  f"all {len(spec.NPCS)} spec entries exist in creature_template",
                  f"missing {sorted(set(spec.NPCS) - set(out))}")

    # curhealth / curmana, as Creature::SelectLevel would compute them (Creature.cpp:1511-1529),
    # minus the RATE_CREATURE_*_HP multiplier -- which is deliberate, because Creature.cpp:1760
    # applies _GetHealthMod() to the stored value again at load time.
    for t in out.values():
        lvl = min(t["minlevel"], t["maxlevel"])
        s = db.query("SELECT basehp0, basehp1, basehp2, basemana FROM creature_classlevelstats "
                     f"WHERE level = {lvl} AND class = {t['unit_class']}")
        if not s:
            t["curhealth"], t["curmana"] = 1, 0
            checks.fail("#6", f"no creature_classlevelstats for level {lvl} "
                              f"class {t['unit_class']} (entry {t['entry']})")
            continue
        basehp = (int(s[0][0]), int(s[0][1]), int(s[0][2]))[min(t["exp"], 2)]
        t["curhealth"] = max(1, int(basehp * t["health_mod"]))
        t["curmana"] = int(int(s[0][3]) * t["mana_mod"])

    for t in sorted(out.values(), key=lambda t: t["entry"]):
        checks.expect(t["faction"] == 35, "#6",
                      f"{t['entry']} {t['name']}: faction 35 (FACTION_FRIENDLY)",
                      f"faction is {t['faction']}")
        checks.expect(t["n_models"] > 0, "#6",
                      f"{t['entry']} {t['name']}: has a creature_template_model row")
        checks.expect(bool(t["script"]), "#6",
                      f"{t['entry']} {t['name']}: ScriptName is set ({t['script']})",
                      "empty -- its owning module is not installed, it would be a mute statue")
    return out


_INT_RANGES = {
    "tinyint": (-128, 127), "smallint": (-32768, 32767),
    "mediumint": (-8388608, 8388607), "int": (-2147483648, 2147483647),
    "bigint": (-2**63, 2**63 - 1),
}


def fetch_schema(db, checks):
    """Invariant #1, and the type table invariant #13 needs."""
    rows = db.query("SHOW COLUMNS FROM creature")
    cols = [r[0] for r in rows]
    ok = checks.expect(list(CREATURE_COLUMNS) == cols, "#1",
                       f"creature has exactly the {len(CREATURE_COLUMNS)} columns we write, "
                       "in order",
                       f"live={cols}")
    if ok:
        # Belt and braces on the one that trips everybody up. Older AzerothCore revisions -- and
        # most tutorials still online -- have `id1`/`id2`/`id3` here; this one has a single `id`
        # and keeps alternates in creature_multispawn.
        checks.expect("id" in cols and "id1" not in cols, "#1",
                      "creature uses `id`, not `id1` (alternates live in creature_multispawn)")

    schema = {}
    for r in rows:
        t = r[1].lower()
        base = t.split("(")[0].split(" ")[0]
        unsigned = "unsigned" in t
        lo, hi = _INT_RANGES.get(base, (None, None))
        if lo is not None and unsigned:
            lo, hi = 0, hi * 2 + 1
        schema[r[0]] = dict(base=base, lo=lo, hi=hi, nullable=(r[2] == "YES"))
    return schema


def check_value_types(schema, placements, templates, checks):
    """#13 -- STRICT_TRANS_TABLES turns an out-of-range value into a half-applied migration."""
    bad = []
    for p in placements:
        for col, v in zip(CREATURE_COLUMNS, p.row(templates[p.entry])):
            s = schema.get(col)
            if not s:
                continue
            if v is None:
                if not s["nullable"]:
                    bad.append((p.guid, col, "NULL into NOT NULL"))
                continue
            if s["lo"] is not None:
                if not isinstance(v, int) or isinstance(v, bool):
                    bad.append((p.guid, col, f"{v!r} is not an integer"))
                elif not (s["lo"] <= v <= s["hi"]):
                    bad.append((p.guid, col, f"{v} outside {s['base']} [{s['lo']}, {s['hi']}]"))
            elif s["base"] in ("float", "double"):
                if not isinstance(v, float) or v != v or abs(v) == float("inf"):
                    bad.append((p.guid, col, f"{v!r} is not a finite float"))
    checks.expect(not bad, "#13",
                  f"all {len(placements) * len(CREATURE_COLUMNS):,} emitted values fit their "
                  "column types", f"{bad[:5]}")


def fetch_inn_anchors(db, checks):
    rows = db.query(
        "SELECT c.guid, c.id, ct.name, c.map, c.position_x, c.position_y, c.position_z, "
        "       c.orientation, IFNULL(ge.eventEntry, 0) "
        "FROM creature c "
        "JOIN creature_template ct ON ct.entry = c.id "
        "LEFT JOIN game_event_creature ge ON ge.guid = c.guid "
        f"WHERE (ct.npcflag & {spec.NPCFLAG_INNKEEPER}) "
        "ORDER BY c.guid")
    anchors = [dict(kind="inn", guid=int(r[0]), entry=int(r[1]), label=r[2], map=int(r[3]),
                    x=float(r[4]), y=float(r[5]), z=float(r[6]), o=float(r[7]),
                    event=int(r[8])) for r in rows]
    checks.expect(len(anchors) > 0, "inn", f"{len(anchors)} innkeeper spawns found "
                                           f"(npcflag & {spec.NPCFLAG_INNKEEPER})")
    if spec.WARN_ON_EVENT_ANCHORS:
        for a in anchors:
            if a["event"]:
                print(f"  [note] inn  anchor {a['guid']} {a['label']} belongs to game_event "
                      f"{a['event']}; its inn is permanent but the innkeeper is seasonal")
    return anchors


def fetch_start_anchors(db, checks):
    """One anchor per DISTINCT starting POINT, not per race and not per row.

    `playercreateinfo` has one row per (race, class) -- 60-odd rows for ten races -- and several
    kinds of duplication on top of that:

      * races that genuinely share a start point. Orc and troll both begin in the Valley of
        Trials, dwarf and gnome both in Coldridge Valley. Two rings on the same doorway is not
        twice as helpful, it is one ring drawn twice.
      * the same point stored at two precisions. Gnome classes 4/8/9 read (-6240, 331, 383)
        against (-6240.32, 331.033, 382.758) for classes 1/6 -- 0.4 yards apart, the same patch
        of snow, different float text.

    So the merge is SPATIAL and its threshold is MIN_ANCHOR_SEPARATION -- the same number
    invariant #11 enforces later. Using the same constant for both is not tidiness: anything
    merged less aggressively than #11 demands would simply fail #11, and anything merged more
    aggressively would silently swallow a real second start point.

    Within a merged group the anchor keeps the exact floats of the lowest (race, class) row, so
    the output is stable and never lands on the rounded outlier.
    """
    rows = db.query("SELECT race, class, map, zone, position_x, position_y, position_z, "
                    "orientation FROM playercreateinfo ORDER BY race, class")
    sep2 = spec.MIN_ANCHOR_SEPARATION ** 2
    anchors = []
    for r in rows:
        race, cls, mapid, zone = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        x, y, z, o = (float(r[4]), float(r[5]), float(r[6]), float(r[7]))
        g = next((a for a in anchors
                  if a["map"] == mapid and dist2((a["x"], a["y"], a["z"]), (x, y, z)) < sep2),
                 None)
        if g is None:
            anchors.append(dict(kind="start", guid=0, map=mapid, zone=zone, x=x, y=y, z=z, o=o,
                                races={race}, key=(race, cls)))
        else:
            g["races"].add(race)

    for a in anchors:
        a["races"] = sorted(a["races"])
        a["label"] = ("races " + "/".join(str(r) for r in a["races"])
                      + f" start, map {a['map']} zone {a['zone']}")

    seen = set()
    for a in anchors:
        seen |= set(a["races"])
    checks.expect(seen == {1, 2, 3, 4, 5, 6, 7, 8, 10, 11}, "#10",
                  f"all ten playable races have a start anchor ({len(anchors)} distinct points)",
                  f"covered={sorted(seen)}")
    checks.expect(all(a["map"] != 609 for a in anchors), "#10",
                  "no start anchor is on map 609 (Ebon Hold)")
    return anchors


def fetch_surprise_anchors(db, checks):
    names = ",".join(sql_str(n) for n, _ in spec.SURPRISES)
    rows = db.query("SELECT id, name, map, position_x, position_y, position_z, orientation "
                    f"FROM game_tele WHERE name IN ({names})")
    by_name = {r[1]: r for r in rows}

    anchors = []
    for name, blurb in spec.SURPRISES:
        r = by_name.get(name)
        if not checks.expect(r is not None, "#9", f"game_tele has a row named {name!r}"):
            continue
        mapid = int(r[2])
        x, y, z, o = float(r[3]), float(r[4]), float(r[5]), float(r[6])
        dz = spec.CORROBORATION_DZ
        gap, used = 99999.0, None
        for rad in (spec.CORROBORATION_RADIUS, spec.CORROBORATION_RADIUS_LOOSE):
            best = db.query(
                "SELECT LEAST("
                f"  IFNULL((SELECT MIN(ABS(c.position_z - {z})) FROM creature c "
                f"     WHERE c.map = {mapid} AND c.position_x BETWEEN {x - rad} AND {x + rad} "
                f"       AND c.position_y BETWEEN {y - rad} AND {y + rad}), 99999),"
                f"  IFNULL((SELECT MIN(ABS(g.position_z - {z})) FROM gameobject g "
                f"     WHERE g.map = {mapid} AND g.position_x BETWEEN {x - rad} AND {x + rad} "
                f"       AND g.position_y BETWEEN {y - rad} AND {y + rad}), 99999))")
            gap, used = float(best[0][0]), rad
            if gap <= dz:
                break
        checks.expect(gap <= dz, "#9",
                      f"{name}: an existing spawn corroborates the floor "
                      f"(closest |dz| = {gap:.2f} within {used:.0f} yd)",
                      f"nearest |dz| = {gap:.2f} > {dz} at both radii -- the game_tele z is not "
                      "standable ground here, pick a different tele")
        if gap <= dz and used > spec.CORROBORATION_RADIUS:
            print(f"  [note] #9   {name} needed the loose {used:.0f} yd radius; open ground, "
                  f"|dz| = {gap:.2f}")
        anchors.append(dict(kind="surprise", guid=int(r[0]), tele=name, label=name, map=mapid,
                            x=x, y=y, z=z, o=o, blurb=blurb, corroboration=gap,
                            corroboration_radius=used))
    return anchors


def fetch_block_state(db, checks, n_expected):
    """Invariant #5 -- has anything encroached on the reserved block?"""
    lo, hi = spec.GUID_FIRST, spec.GUID_LAST
    ours = ",".join(str(e) for e in sorted(spec.NPCS))
    foreign = db.query(f"SELECT guid, id FROM creature WHERE guid BETWEEN {lo} AND {hi} "
                       f"AND id NOT IN ({ours}) ORDER BY guid LIMIT 10")
    checks.expect(not foreign, "#5",
                  f"nothing foreign occupies guid {lo:,}..{hi:,}",
                  f"found {[(int(a), int(b)) for a, b in foreign]}")

    below = db.query(f"SELECT IFNULL(MAX(guid), 0) FROM creature WHERE guid < {lo}")
    max_below = int(below[0][0])
    checks.expect(max_below < lo, "#5",
                  f"MAX(guid) outside the block is {max_below:,}, "
                  f"{lo - max_below:,} clear of the block",
                  f"the world DB has grown to {max_below:,} -- move the block")

    above = db.query(f"SELECT IFNULL(MAX(guid), 0) FROM creature WHERE guid > {hi}")
    if int(above[0][0]):
        print(f"  [note] blk  {int(above[0][0]):,} is the highest guid ABOVE the block "
              "(GM `.npc add` spawns) -- expected, and untouched by this module")

    mine = db.query(f"SELECT COUNT(*) FROM creature WHERE guid BETWEEN {lo} AND {hi}")
    live_n = int(mine[0][0])
    if live_n != n_expected:
        print(f"  [note] blk  the live realm holds {live_n} rows in the block, this run plans "
              f"{n_expected}; the difference applies at the next worldserver boot")


# ==============================================================================================
# build
# ==============================================================================================

def build(db, checks):
    templates = fetch_templates(db, checks)
    schema = fetch_schema(db, checks)

    inn_all = fetch_inn_anchors(db, checks)
    inn, inn_dropped = thin(inn_all, spec.MIN_ANCHOR_SEPARATION)
    for d in inn_dropped:
        c = d["clashed_with"]
        print(f"  [note] #11  dropped inn anchor {d['guid']} {d['label']} -- within "
              f"{spec.MIN_ANCHOR_SEPARATION:.0f} yd of {c['guid']} {c['label']}")

    start = fetch_start_anchors(db, checks)
    surprise = fetch_surprise_anchors(db, checks)

    placements = []
    for a in inn:
        for entry, m, x, y, z, o in ring((a["map"], a["x"], a["y"], a["z"], a["o"]),
                                         spec.ROSTER_INN, spec.RING_RADIUS_INN):
            placements.append(Placement(entry, m, x, y, z, o, "inn",
                                        f"{a['guid']} {a['label']}"))
    for a in start:
        for entry, m, x, y, z, o in ring((a["map"], a["x"], a["y"], a["z"], a["o"]),
                                         spec.ROSTER_START, spec.RING_RADIUS_START):
            placements.append(Placement(entry, m, x, y, z, o, "start", a["label"]))
    for a in surprise:
        for entry, m, x, y, z, o in ring((a["map"], a["x"], a["y"], a["z"], a["o"]),
                                         spec.ROSTER_SURPRISE, spec.RING_RADIUS_SURPRISE):
            placements.append(Placement(entry, m, x, y, z, o, "surprise",
                                        f"game_tele {a['guid']} {a['tele']}"))

    # #11 -- no two rings anywhere can intersect. Innkeepers were thinned above; this also
    # catches a surprise tele that happens to sit on top of an inn or a starting zone.
    all_anchors = ([(a["map"], a["x"], a["y"], a["z"], f"inn {a['guid']} {a['label']}")
                    for a in inn]
                   + [(a["map"], a["x"], a["y"], a["z"], f"start {a['label']}") for a in start]
                   + [(a["map"], a["x"], a["y"], a["z"], f"surprise {a['tele']}")
                      for a in surprise])
    sep2 = spec.MIN_ANCHOR_SEPARATION ** 2
    clashes = [(p[4], q[4]) for i, p in enumerate(all_anchors) for q in all_anchors[i + 1:]
               if p[0] == q[0] and dist2(p[1:4], q[1:4]) < sep2]
    checks.expect(not clashes, "#11",
                  f"all {len(all_anchors)} anchors are >= {spec.MIN_ANCHOR_SEPARATION:.0f} yd "
                  "apart on their map", f"{clashes[:4]}")

    # #2 #3 -- guids assigned DOWNWARD from the top of the block, so GUID_LAST is always taken.
    # See npc_spec.py: that is what keeps ObjectMgr's `_creatureSpawnId = MAX(guid) + 1` above
    # the block instead of inside it.
    checks.expect(len(placements) <= spec.GUID_LAST - spec.GUID_FIRST + 1, "#2",
                  f"{len(placements)} spawns fit in the "
                  f"{spec.GUID_LAST - spec.GUID_FIRST + 1:,}-guid block")
    for i, p in enumerate(placements):
        p.guid = spec.GUID_LAST - i
    guids = [p.guid for p in placements]
    checks.expect(len(set(guids)) == len(guids), "#2", "every emitted guid is unique")
    checks.expect(all(spec.GUID_FIRST <= g <= spec.GUID_LAST for g in guids), "#2",
                  "every emitted guid is inside the reserved block")
    checks.expect(max(guids) == spec.GUID_LAST, "#3",
                  f"the top of the block ({spec.GUID_LAST:,}) is occupied, which pins "
                  "_creatureSpawnId above it")
    checks.expect(spec.GUID_LAST < spec.SPAWN_ID_CEILING - spec.MIN_HEADROOM_ABOVE, "#4",
                  f"{spec.SPAWN_ID_CEILING - spec.GUID_LAST:,} spawn ids remain above the block "
                  f"before ObjectMgr::GenerateCreatureSpawnId calls World::StopNow")

    # #7 -- read the finished rows back rather than trusting the constructor.
    bad = []
    for p in placements:
        r = dict(zip(CREATURE_COLUMNS, p.row(templates[p.entry])))
        if (r["MovementType"], r["wander_distance"], r["phaseMask"], r["spawnMask"],
                r["ScriptName"], r["npcflag"], r["unit_flags"], r["dynamicflags"]) != \
                (0, 0.0, 1, 1, "", 0, 0, 0):
            bad.append(p.guid)
    checks.expect(not bad, "#7", "every row is stationary, phase 1, and inherits its template's "
                                 "flags and script", f"{bad[:5]}")

    check_value_types(schema, placements, templates, checks)
    fetch_block_state(db, checks, len(placements))
    return templates, inn, inn_dropped, start, surprise, placements


# ==============================================================================================
# emit
# ==============================================================================================

def sql_text(templates, inn, start, surprise, placements):
    lo, hi = spec.GUID_FIRST, spec.GUID_LAST
    n = len(placements)
    per_kind = {k: sum(1 for p in placements if p.kind == k)
                for k in ("inn", "start", "surprise")}

    L = []
    w = L.append
    w(f"-- {spec.SQL_NAME}")
    w("--")
    w("-- GENERATED by build/modules/mod-utility-npcs/tools/gen_spawns.py from tools/npc_spec.py")
    w("-- against the LIVE world DB. DO NOT EDIT BY HAND -- re-run the generator. Verify with")
    w("-- `tools/gen_spawns.py --check`.")
    w("--")
    w("-- Puts the realm's six utility NPCs where players are: a ring at every inn, a ring at")
    w("-- every starting zone, and a ring at fourteen places chosen to be worth finding.")
    w("--")
    w("-- NOT ONE COORDINATE IN THIS FILE WAS TYPED IN. Every position is an offset from a row")
    w("-- that already exists on this realm -- an innkeeper's spawn, a `playercreateinfo` start")
    w("-- point, or a `game_tele` entry -- because an invented x/y/z lands inside terrain, under")
    w("-- the water table or in the void, and the NPC is then unreachable or falls forever. An")
    w("-- innkeeper in particular is a guarantee of indoors, on valid ground, in a building with")
    w("-- a door, facing into the room.")
    w("--")
    w("-- RE-RUNNABLE ON PURPOSE. UpdateFetcher keys a migration on its bare filename plus a")
    w("-- SHA1 of its contents (UpdateFetcher.cpp): an unchanged file is skipped, a CHANGED file")
    w("-- is re-applied IN FULL. The DELETE below therefore clears the WHOLE reserved guid range,")
    w("-- not just the guids this file inserts, so shrinking the roster converges instead of")
    w("-- leaving orphans. Never a bare INSERT.")
    w("--")
    w("-- ---------------------------------------------------------------------------------------")
    w("-- THE RESERVED GUID BLOCK")
    w("-- ---------------------------------------------------------------------------------------")
    w(f"--   reserved   {lo:>12,} .. {hi:<12,}  ({hi - lo + 1:,} guids)")
    w(f"--   used       {n:>12,}  rows in this file, packed DOWNWARD from the top of the block")
    w(f"--   ceiling    {spec.SPAWN_ID_CEILING:>12,}  = 0xFFFFFF")
    w("--")
    w("-- The ceiling is not the column width. `creature.guid` is INT UNSIGNED, but")
    w("-- ObjectMgr::GenerateCreatureSpawnId (ObjectMgr.cpp:7655-7662) calls World::StopNow -- the")
    w("-- worldserver shuts itself down -- as soon as the next spawn id would reach 0xFFFFFF. The")
    w("-- usable space is 1..16,777,214, so a block up at four billion would be a realm that dies")
    w("-- the first time a GM types `.npc add`.")
    w("--")
    w("-- Why 10,000,000 is safe, measured rather than assumed: the live world DB's MAX(guid) is")
    w("-- 5,300,688 and there is not one row at or above 6,000,000. Upstream would have to nearly")
    w("-- double the entire creature table to reach us, and this block is 100x larger than the")
    w(f"-- {n:,} rows it holds.")
    w("--")
    w("-- WHY THE GUIDS COUNT DOWN. ObjectMgr seeds `_creatureSpawnId = MAX(guid) + 1` at boot")
    w("-- (ObjectMgr.cpp:7616-7618), so this module's highest row decides where GM `.npc add`")
    w("-- starts. Packing upward from the bottom would put the next GM spawn INSIDE the reserved")
    w("-- range, where the next generator run would delete it without asking. Packing downward")
    w(f"-- pins MAX(guid) at exactly {hi:,} for as long as this module has a single spawn, so")
    w("-- `.npc add` always begins one clear of the block.")
    w("--")
    w("-- ---------------------------------------------------------------------------------------")
    w("-- WHAT IS SPAWNED, AND WHERE")
    w("-- ---------------------------------------------------------------------------------------")
    for entry in sorted(spec.NPCS):
        t = templates[entry]
        where = []
        if entry in spec.ROSTER_INN:
            where.append("inns")
        if entry in spec.ROSTER_START:
            where.append("starting zones")
        if entry in spec.ROSTER_SURPRISE:
            where.append("surprises")
        cnt = sum(1 for p in placements if p.entry == entry)
        w(f"--   {entry:<8} {t['name']:<24} {cnt:>4} spawns   {', '.join(where)}")
    w("--")
    w(f"--   {len(inn):>4} inn rings      x {len(spec.ROSTER_INN)} = {per_kind['inn']:>4}")
    w(f"--   {len(start):>4} start rings    x {len(spec.ROSTER_START)} = {per_kind['start']:>4}")
    w(f"--   {len(surprise):>4} surprise rings x {len(spec.ROSTER_SURPRISE)} = "
      f"{per_kind['surprise']:>4}")
    w(f"--   {'':>4}                     {'':>4}   {n:>4} total")
    w("--")
    w("-- 190011 Ethereal Warpweaver is deliberately NOT at every inn. It is the same NPC as")
    w("-- 190010 in every way a player can observe -- same ScriptName, same subname, same faction,")
    w("-- and the same CreatureDisplayID 19646 -- so posting both everywhere would be 122 pairs of")
    w("-- identical twins. It gets the surprise locations instead, where a second transmogrifier")
    w("-- reads as a joke rather than as a bug.")
    w("--")
    w("-- ---------------------------------------------------------------------------------------")
    w("-- THE RING")
    w("-- ---------------------------------------------------------------------------------------")
    w(f"-- Radius {spec.RING_RADIUS_INN} yd indoors, {spec.RING_RADIUS_START} yd outdoors, at "
      f"{'/'.join(f'{a:+.0f}' for a in spec.ANGLE_OFFSETS_DEG)} degrees off the")
    w("-- anchor's own facing. Nothing sits at 0 degrees -- that is the lane a player walks up to")
    w("-- talk to the innkeeper and it has to stay clear -- and nothing at 180, which behind an")
    w("-- innkeeper is the bar, the hearth or the wall. Adjacent spacing at radius R with 60-degree")
    w(f"-- steps is exactly R, so {spec.RING_RADIUS_INN} yd indoors against a worst-case bounding")
    w("-- radius of 0.4213 (creature_model_info, display 31833) leaves ~1.6 yd of air between")
    w("-- neighbours. Z is COPIED from the anchor, never computed: the anchor's z is the floor.")
    w("-- Each NPC faces the anchor, because facing outward would point the back of the ring")
    w("-- nose-first into whatever the innkeeper has behind them.")
    w("")
    w("")
    w("--")
    w("-- 1. Clear the whole reserved range.")
    w("--")
    w("-- The range, not the guid list: if a future run emits fewer rows, the extras must go. The")
    w("-- creature_addon delete is hygiene -- this module never writes one, but the range is ours")
    w("-- and an orphan addon row would attach to whatever landed on that guid next.")
    w("")
    w(f"DELETE FROM `creature_addon` WHERE `guid` BETWEEN {lo} AND {hi};")
    w(f"DELETE FROM `creature` WHERE `guid` BETWEEN {lo} AND {hi};")
    w("")
    w("--")
    w("-- 2. Re-insert.")
    w("--")
    w("-- npcflag / unit_flags / dynamicflags are 0, and 0 means INHERIT rather than 'no flags':")
    w("-- ObjectMgr::ChooseCreatureFlags (ObjectMgr.cpp:1659-1676) starts from the template and")
    w("-- overrides a field only when the spawn row's value is non-zero. That is how each NPC keeps")
    w("-- its own npcflag (1 GOSSIP, 129 GOSSIP|VENDOR for Gabriella) and its unit_flags (2 =")
    w("-- UNIT_FLAG_NON_ATTACKABLE on three of the six). ScriptName is empty for the same reason:")
    w("-- LoadCreatures falls back to the TEMPLATE's script when the spawn row has none")
    w("-- (ObjectMgr.cpp:2394-2395), and naming anything here would replace npc_transmogrifier /")
    w("-- npc_assistant / instance_reset with nothing.")
    w("--")
    w("-- There is no `faction` column on `creature`. All six templates are faction 35,")
    w("-- FACTION_FRIENDLY (SharedDefines.h:189) -- the generator fails if that ever stops being")
    w("-- true. Nothing aggroes them and they aggro nothing.")
    w("")
    cols = ", ".join(f"`{c}`" for c in CREATURE_COLUMNS)
    w(f"INSERT INTO `creature` ({cols}) VALUES")

    ordered = sorted(placements, key=lambda p: p.guid)
    last_anchor = None
    body = []
    for p in ordered:
        if p.anchor != last_anchor:
            body.append(f"-- {p.kind}: {p.anchor}")
            last_anchor = p.anchor
        vals = ", ".join(sql_value(v) for v in p.row(templates[p.entry]))
        body.append(f"  ({vals}),")
    body[-1] = body[-1][:-1] + ";"
    L.extend(body)
    w("")
    return "\n".join(L) + "\n"


def header_text(placements):
    entries = ", ".join(str(e) for e in sorted(spec.NPCS))
    return f"""/*
 * GENERATED by build/modules/mod-utility-npcs/tools/gen_spawns.py. DO NOT HAND-EDIT.
 *
 * The reserved creature.guid block, emitted from the SAME spec that emits
 * data/sql/db-world/base/{spec.SQL_NAME}, so the range the C++ half
 * polices at boot and the range the SQL DELETEs cannot drift apart. That drift is the whole
 * failure mode this header exists to prevent: a C++ constant one digit off from the SQL turns
 * the boot-time encroachment check into a check of the wrong thing, silently.
 */

#ifndef UTILITY_NPCS_RANGE_H_
#define UTILITY_NPCS_RANGE_H_

#include <cstdint>

// Inclusive. See npc_spec.py for why 10,000,000 and why the block is packed downward.
static constexpr uint32_t kUtilityNpcGuidFirst = {spec.GUID_FIRST}u;
static constexpr uint32_t kUtilityNpcGuidLast  = {spec.GUID_LAST}u;

// ObjectMgr::GenerateCreatureSpawnId (ObjectMgr.cpp:7657) calls World::StopNow at this value.
static constexpr uint32_t kUtilityNpcSpawnIdCeiling = 0xFFFFFFu;

// Rows the migration inserts. The boot check warns when the live count differs -- which is the
// normal, expected state for exactly one boot after this file changes, and a real problem if it
// persists.
static constexpr uint32_t kUtilityNpcSpawnCount = {len(placements)}u;

// Every creature_template entry this module is allowed to place. Used by the boot check to tell
// "our rows" from "somebody parked something in our block".
static constexpr uint32_t kUtilityNpcEntries[] = {{ {entries} }};

#endif // UTILITY_NPCS_RANGE_H_
"""


def write_if_changed(path, text):
    old = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            old = fh.read()
    if old == text:
        print(f"   {os.path.relpath(path, spec.REPO_ROOT)}  (unchanged)")
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"   {os.path.relpath(path, spec.REPO_ROOT)}  ({len(text.splitlines())} lines)")
    return True


# ==============================================================================================
# modes
# ==============================================================================================

def print_plan(templates, inn, inn_dropped, start, surprise, placements):
    print("\n== plan")
    print(f"   inn rings        {len(inn):>4}  ({len(inn_dropped)} thinned) "
          f"x {len(spec.ROSTER_INN)} NPCs")
    print(f"   start rings      {len(start):>4}  "
          f"x {len(spec.ROSTER_START)} NPCs")
    print(f"   surprise rings   {len(surprise):>4}  x {len(spec.ROSTER_SURPRISE)} NPCs")
    print(f"   TOTAL SPAWNS     {len(placements):>4}")
    print()
    for entry in sorted(spec.NPCS):
        cnt = sum(1 for p in placements if p.entry == entry)
        print(f"   {entry:<8} {templates[entry]['name']:<24} {cnt:>4}")
    print("\n== starting zones")
    for a in start:
        print(f"   map {a['map']:>3} zone {a['zone']:>4}  races "
              f"{'/'.join(str(r) for r in a['races'])}")
    print("\n== surprises")
    for a in surprise:
        print(f"   map {a['map']:>3}  {a['tele']:<20} (|dz| {a['corroboration']:.2f} yd within "
              f"{a['corroboration_radius']:.0f} yd)")
        print(f"              {a['blurb']}")


def do_emit(args, checks):
    db = Db(args.mysql_cmd)
    if not db.live():
        checks.fail("db", f"world DB unreachable: {db.error.splitlines()[0]}")
        return checks.summary()

    print("== invariants")
    built = build(db, checks)
    templates, inn, inn_dropped, start, surprise, placements = built
    if checks.failed:
        print("\nrefusing to write: fix the failures above")
        return checks.summary()

    print_plan(templates, inn, inn_dropped, start, surprise, placements)

    text = sql_text(templates, inn, start, surprise, placements)
    checks.expect(verify_delete_covers_insert(text), "#8",
                  "every INSERT in the emitted SQL is covered by a DELETE of the same range")

    print(f"\n== SQL -> {os.path.relpath(spec.SQL_DIR, spec.REPO_ROOT)}")
    write_if_changed(spec.SQL_PATH, text)
    print(f"\n== header -> {os.path.relpath(spec.HEADER_PATH, spec.REPO_ROOT)}")
    write_if_changed(spec.HEADER_PATH, header_text(placements))

    print("\n== emitted-file checks")
    check_files(checks, len(placements))
    return checks.summary()


def verify_delete_covers_insert(text):
    """#8 -- read it back off the string rather than trusting that we wrote it."""
    del_ranges = [(int(a), int(b)) for a, b in re.findall(
        r"DELETE FROM `creature` WHERE `guid` BETWEEN (\d+) AND (\d+);", text)]
    if not del_ranges:
        return False
    ins = text.split("VALUES", 1)
    if len(ins) != 2:
        return False
    guids = [int(g) for g in re.findall(r"^\s*\((\d+),", ins[1], re.M)]
    if not guids:
        return False
    return all(any(lo <= g <= hi for lo, hi in del_ranges) for g in guids)


def check_files(checks, expected_rows=None):
    if not os.path.exists(spec.SQL_PATH):
        checks.fail("file", f"missing {os.path.relpath(spec.SQL_PATH, spec.REPO_ROOT)}")
        return
    with open(spec.SQL_PATH, encoding="utf-8") as fh:
        text = fh.read()
    guids = [int(g) for g in re.findall(r"^\s*\((\d+),", text, re.M)]
    checks.expect(bool(guids), "file", f"{spec.SQL_NAME} contains INSERT rows")
    checks.expect(len(set(guids)) == len(guids), "#2", "no duplicate guid in the emitted SQL")
    checks.expect(all(spec.GUID_FIRST <= g <= spec.GUID_LAST for g in guids), "#2",
                  "every guid in the emitted SQL is inside the reserved block")
    checks.expect(guids and max(guids) == spec.GUID_LAST, "#3",
                  f"the emitted SQL occupies the top of the block ({spec.GUID_LAST:,})")
    checks.expect(verify_delete_covers_insert(text), "#8",
                  "every INSERT is covered by a DELETE of the same range")

    ncols = text.count("`,` ") if False else len(CREATURE_COLUMNS)
    first = re.search(r"^\s*\((\d+),.*\)[,;]$", text, re.M)
    if first:
        # split on top-level commas only: no nested parens are ever emitted, and strings are
        # single-quoted with backslash escapes, so a simple scanner is exact here.
        body, depth, cur, parts, in_str, esc = first.group(0).strip()[1:-2], 0, "", [], False, False
        for ch in body:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "'":
                    in_str = False
                cur += ch
                continue
            if ch == "'":
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
                continue
            cur += ch
        parts.append(cur)
        checks.expect(len(parts) == ncols, "#1",
                      f"each VALUES tuple has {ncols} values, matching the column list",
                      f"first tuple has {len(parts)}")

    if not os.path.exists(spec.HEADER_PATH):
        checks.fail("#12", f"missing {os.path.relpath(spec.HEADER_PATH, spec.REPO_ROOT)}")
        return
    with open(spec.HEADER_PATH, encoding="utf-8") as fh:
        hdr = fh.read()

    def const(name):
        m = re.search(rf"{name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)u", hdr)
        return int(m.group(1), 0) if m else None

    checks.expect(const("kUtilityNpcGuidFirst") == spec.GUID_FIRST, "#12",
                  "header kUtilityNpcGuidFirst matches the spec")
    checks.expect(const("kUtilityNpcGuidLast") == spec.GUID_LAST, "#12",
                  "header kUtilityNpcGuidLast matches the spec")
    checks.expect(const("kUtilityNpcSpawnCount") == len(guids), "#12",
                  f"header kUtilityNpcSpawnCount ({const('kUtilityNpcSpawnCount')}) matches the "
                  f"{len(guids)} rows in the SQL")
    hdr_entries = re.search(r"kUtilityNpcEntries\[\]\s*=\s*\{([^}]*)\}", hdr)
    got = sorted(int(x) for x in re.findall(r"\d+", hdr_entries.group(1))) if hdr_entries else []
    checks.expect(got == sorted(spec.NPCS), "#12", "header kUtilityNpcEntries matches the spec")
    sql_entries = sorted({int(m) for m in re.findall(r"^\s*\(\d+,\s*(\d+),", text, re.M)})
    checks.expect(set(sql_entries) <= set(spec.NPCS), "#12",
                  "every entry id in the SQL is one of the spec's", f"{sql_entries}")
    if expected_rows is not None:
        checks.expect(len(guids) == expected_rows, "#12",
                      f"the file on disk has the {expected_rows} rows this run planned")


def do_check(args, checks):
    print("== emitted files")
    check_files(checks)
    db = Db(args.mysql_cmd)
    if not db.live():
        checks.skip("db", f"world DB unreachable, live invariants not run: "
                          f"{db.error.splitlines()[0]}")
        return checks.summary()
    print("\n== live invariants")
    build(db, checks)
    return checks.summary()


def do_plan(args, checks):
    db = Db(args.mysql_cmd)
    if not db.live():
        checks.fail("db", f"world DB unreachable: {db.error.splitlines()[0]}")
        return checks.summary()
    print("== invariants")
    templates, inn, inn_dropped, start, surprise, placements = build(db, checks)
    print_plan(templates, inn, inn_dropped, start, surprise, placements)
    return checks.summary()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="re-verify the already-generated outputs; writes nothing")
    ap.add_argument("--plan", action="store_true",
                    help="print the placement plan and counts; writes nothing")
    ap.add_argument("--mysql-cmd", default=None,
                    help="read-only mysql client command; '{repo}' expands to the repo root")
    args = ap.parse_args(argv)

    checks = Checks()
    if args.check:
        return do_check(args, checks)
    if args.plan:
        return do_plan(args, checks)
    return do_emit(args, checks)


if __name__ == "__main__":
    sys.exit(main())
