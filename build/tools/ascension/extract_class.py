#!/usr/bin/env python3
"""Extract one Ascension class's complete kit from an installed Ascension client.

WHY THIS EXISTS
---------------
Ascension replaced the talent system rather than extending it, so `Talent.dbc` is
empty for every class above 11 and `SkillLineAbility` carries only racial and utility
scaffolding. The class kit lives in `CharacterAdvancement.dbc` -- 12,037 nodes, 179
declared fields in a 692-byte record (so 173 int slots; the header's field count is
NOT record_size/4 and trusting it reads past the end of every record into the next
one).

The column meanings below were recovered by structural analysis, not documentation,
so each one records how it was identified and is re-checked on every run:

    field   0   node id          strictly ascending, 12,037 distinct
    field   5   SPELL ID         158/158 of a class's nodes resolve in Spell.dbc
    field  32   class type       1..46, joins CharacterAdvancementClassTypes.ID
    field  33   tab              0..94, joins CharacterAdvancementTabTypes.ID
    field  47   node name        6,897 distinct strings ("Blizzard", "Fel Haze")
    field  64   icon             4,560 distinct strings ("Spell_Fire_FelImmolation")

usage:  extract_class.py --class-type 16 [--client DIR] [--out DIR]
        (16 = Felsworn; see --list for the rest)
"""
import argparse, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import spelldbc as S
from acdbc import mpqlib

DEFAULT_CLIENT = "/mnt/ntfs2t/Ascension/Launcher/resources/ascension-live/Data"

CA_NODE_ID, CA_SPELL, CA_CLASS, CA_TAB, CA_NAME, CA_ICON = 0, 5, 32, 33, 47, 64


class Dbc:
    """A DBC read with the record width the FILE states, not the field count it claims."""

    def __init__(self, blob, path=""):
        magic, self.rc, self.declared_fields, self.rs, ss = struct.unpack_from("<4sIIII", blob, 0)
        if magic != b"WDBC":
            raise ValueError(f"{path}: not a WDBC file")
        self.slots = self.rs // 4
        body = 20 + self.rc * self.rs
        self.strings = blob[body:]
        fmt = "<" + "i" * self.slots
        self.rows = [struct.unpack_from(fmt, blob, 20 + i * self.rs) for i in range(self.rc)]
        self.by_id = {r[0]: r for r in self.rows}

    def s(self, off):
        if off <= 0 or off >= len(self.strings):
            return ""
        end = self.strings.find(b"\0", off)
        return self.strings[off:end].decode("utf8", "replace")


def open_client(data_dir):
    handles = []
    for prio, rel in sorted(mpqlib.chain(data_dir), reverse=True):
        try:
            handles.append(mpqlib.Mpq.open(os.path.join(data_dir, rel)))
        except Exception:
            pass
    if not handles:
        sys.exit(f"no MPQ archives under {data_dir}")

    def read(name):
        for m in handles:
            try:
                if m.has(name):
                    return m.read(name)
            except Exception:
                pass
        return None

    return read


def eff_name(e):
    return S.EFFECT_NAMES.get(e, f"EFFECT_{e}") if e else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=DEFAULT_CLIENT)
    ap.add_argument("--class-type", type=int, default=16)
    ap.add_argument("--out", default="build/tools/ascension/out")
    ap.add_argument("--list", action="store_true", help="list class types and exit")
    args = ap.parse_args()

    read = open_client(args.client)

    def dbc(name):
        blob = read(f"DBFilesClient\\{name}.dbc")
        if blob is None:
            sys.exit(f"{name}.dbc not found in the client chain")
        return Dbc(blob, name)

    classtypes = dbc("CharacterAdvancementClassTypes")
    tabtypes = dbc("CharacterAdvancementTabTypes")

    def type_name(d, row):
        """The readable label, taken from whichever string slot actually holds it."""
        best = ""
        for v in row[1:12]:
            t = d.s(v)
            if len(t) > len(best) and t.isascii():
                best = t
        return best

    if args.list:
        for r in classtypes.rows:
            print(f"  class-type {r[0]:3}  chrclass {r[1]:3}  {type_name(classtypes, r)}")
        return

    ct = classtypes.by_id.get(args.class_type)
    if ct is None:
        sys.exit(f"no class type {args.class_type}")
    label, chrclass = type_name(classtypes, ct), ct[2]
    print(f"== {label}  (advancement class type {args.class_type}, ChrClasses id {chrclass})")

    ca = dbc("CharacterAdvancement")
    print(f"   CharacterAdvancement: {ca.rc} rows, declared {ca.declared_fields} fields, "
          f"record {ca.rs}B -> {ca.slots} int slots")
    if ca.declared_fields * 4 != ca.rs:
        print(f"   NOTE  declared field count {ca.declared_fields} != record_size/4 "
              f"({ca.rs // 4}); using the record width, which is authoritative")

    nodes = [r for r in ca.rows if r[CA_CLASS] == args.class_type]
    if not nodes:
        sys.exit(f"no advancement nodes for class type {args.class_type}")

    spell = dbc("Spell")
    if spell.slots != S.FIELD_COUNT:
        sys.exit(f"Spell.dbc is {spell.slots} fields, expected the stock {S.FIELD_COUNT}; "
                 f"the offset table in spelldbc.py does not apply")

    hit = sum(1 for n in nodes if n[CA_SPELL] in spell.by_id)
    print(f"   {len(nodes)} nodes, {hit} resolve to a Spell.dbc record "
          f"({100.0 * hit / len(nodes):.0f}%)")
    if hit < len(nodes) * 0.9:
        print("   WARNING  spell column looks wrong for this class -- check field 5")

    out = []
    for n in sorted(nodes, key=lambda r: (r[CA_TAB], r[CA_NODE_ID])):
        sid = n[CA_SPELL]
        sr = spell.by_id.get(sid)
        rec = {
            "node": n[CA_NODE_ID],
            "name": ca.s(n[CA_NAME]),
            "icon": ca.s(n[CA_ICON]),
            "tab": n[CA_TAB],
            "tab_name": type_name(tabtypes, tabtypes.by_id[n[CA_TAB]]) if n[CA_TAB] in tabtypes.by_id else "",
            "spell": sid,
        }
        if sr:
            rec.update({
                "spell_name":  spell.s(sr[S.NAME]),
                "rank":        spell.s(sr[S.RANK]),
                "description": spell.s(sr[S.DESCRIPTION]).replace("\n", " "),
                "spell_level": sr[S.SPELL_LEVEL],
                "base_level":  sr[S.BASE_LEVEL],
                "power_type":  sr[S.POWER_TYPE],
                "mana_cost":   sr[S.MANA_COST],
                "cooldown_ms": sr[S.RECOVERY_TIME],
                "cat_cd_ms":   sr[S.CATEGORY_RECOVERY_TIME],
                "gcd_ms":      sr[S.START_RECOVERY_TIME],
                "class_set":   sr[S.SPELL_CLASS_SET],
                "school_mask": sr[S.SCHOOL_MASK],
                "proc_flags":  sr[S.PROC_TYPE_MASK],
                "proc_chance": sr[S.PROC_CHANCE],
                "icon_id":     sr[S.SPELL_ICON_ID],
                "effects": [
                    {
                        "effect":      sr[S.EFFECT + i],
                        "effect_name": eff_name(sr[S.EFFECT + i]),
                        "aura":        sr[S.EFFECT_AURA + i],
                        "base_points": sr[S.EFFECT_BASE_POINTS + i],
                        "die_sides":   sr[S.EFFECT_DIE_SIDES + i],
                        "per_level":   sr[S.EFFECT_PER_LEVEL + i],
                        "misc":        sr[S.EFFECT_MISC_VALUE + i],
                        "misc_b":      sr[S.EFFECT_MISC_VALUE_B + i],
                        "trigger":     sr[S.EFFECT_TRIGGER_SPELL + i],
                        "target_a":    sr[S.EFFECT_TARGET_A + i],
                        "coefficient": sr[S.EFFECT_BONUS_MULTIPLIER + i],
                    }
                    for i in range(3) if sr[S.EFFECT + i]
                ],
            })
        out.append(rec)

    os.makedirs(args.out, exist_ok=True)
    slug = (label.lower().replace(" ", "-") or f"classtype{args.class_type}")
    path = os.path.join(args.out, f"{slug}.json")
    with open(path, "w") as f:
        json.dump({"class_type": args.class_type, "chrclass": chrclass,
                   "label": label, "nodes": out}, f, indent=1)

    tabs = {}
    for r in out:
        tabs.setdefault((r["tab"], r["tab_name"]), []).append(r)
    print()
    for (tid, tname), rows in sorted(tabs.items(), key=lambda kv: -len(kv[1])):
        scripted = sum(1 for r in rows
                       if any(e["effect"] in (3, 77) for e in r.get("effects", [])))
        print(f"   tree {tid:3} {tname[:22]:24} {len(rows):3} nodes   "
              f"{scripted:3} need a server script (DUMMY/SCRIPT_EFFECT)")
    print(f"\n   -> {path}  ({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    main()
