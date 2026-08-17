#!/usr/bin/env python3
"""Dump every Spell.dbc record in one SpellClassSet (spell family) to JSON.

SpellClassSet is the axis that actually delimits an Ascension class's kit.
CharacterAdvancement only holds the *choosable* nodes; the rank chains, proc
triggers and form spells the nodes refer to are not in it. Family 20 is Felsworn:
858 records against 158 advancement nodes.
"""
import argparse, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import spelldbc as S
from acdbc import mpqlib

ap = argparse.ArgumentParser()
ap.add_argument("--client", default="/mnt/ntfs2t/Ascension/Launcher/resources/ascension-live/Data")
ap.add_argument("--family", type=int, required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

hs = []
for _p, rel in sorted(mpqlib.chain(a.client), reverse=True):
    try: hs.append(mpqlib.Mpq.open(os.path.join(a.client, rel)))
    except Exception: pass
blob = None
for m in hs:
    if m.has("DBFilesClient\\Spell.dbc"): blob = m.read("DBFilesClient\\Spell.dbc"); break
_, rc, fc, rs, _ = struct.unpack_from("<4sIIII", blob, 0)
assert fc == S.FIELD_COUNT, f"Spell.dbc is {fc} fields, offsets assume {S.FIELD_COUNT}"
strs = blob[20 + rc * rs:]
def st(o): return strs[o:strs.index(b"\0", o)].decode("utf8", "replace") if 0 < o < len(strs) else ""

out = []
for i in range(rc):
    r = struct.unpack_from("<" + "i" * fc, blob, 20 + i * rs)
    if r[S.SPELL_CLASS_SET] != a.family: continue
    out.append({
        "id": r[S.ID], "name": st(r[S.NAME]), "rank": st(r[S.RANK]),
        "description": st(r[S.DESCRIPTION]).replace("\n", " "),
        "aura_description": st(r[S.AURA_DESCRIPTION]).replace("\n", " "),
        "spell_level": r[S.SPELL_LEVEL], "base_level": r[S.BASE_LEVEL],
        "max_level": r[S.MAX_LEVEL], "power_type": r[S.POWER_TYPE],
        "mana_cost": r[S.MANA_COST], "mana_cost_pct": r[S.MANA_COST_PCT],
        "cooldown_ms": r[S.RECOVERY_TIME], "category_cd_ms": r[S.CATEGORY_RECOVERY_TIME],
        "gcd_ms": r[S.START_RECOVERY_TIME], "gcd_category": r[S.START_RECOVERY_CATEGORY],
        "cast_time_index": r[S.CASTING_TIME_INDEX], "range_index": r[S.RANGE_INDEX],
        "duration_index": r[S.DURATION_INDEX], "school_mask": r[S.SCHOOL_MASK],
        "attributes": [r[S.ATTRIBUTES + k] for k in range(8)],
        "proc_flags": r[S.PROC_TYPE_MASK], "proc_chance": r[S.PROC_CHANCE],
        "proc_charges": r[S.PROC_CHARGES], "icon_id": r[S.SPELL_ICON_ID],
        "shapeshift_mask": r[S.SHAPESHIFT_MASK],
        "equipped_item_class": r[S.EQUIPPED_ITEM_CLASS],
        "class_mask": [r[S.SPELL_CLASS_MASK + k] for k in range(3)],
        "effects": [{
            "i": k, "effect": r[S.EFFECT + k],
            "effect_name": S.EFFECT_NAMES.get(r[S.EFFECT + k], f"EFFECT_{r[S.EFFECT + k]}"),
            "aura": r[S.EFFECT_AURA + k], "base_points": r[S.EFFECT_BASE_POINTS + k],
            "die_sides": r[S.EFFECT_DIE_SIDES + k], "per_level": r[S.EFFECT_PER_LEVEL + k],
            "misc": r[S.EFFECT_MISC_VALUE + k], "misc_b": r[S.EFFECT_MISC_VALUE_B + k],
            "trigger": r[S.EFFECT_TRIGGER_SPELL + k], "target_a": r[S.EFFECT_TARGET_A + k],
            "target_b": r[S.EFFECT_TARGET_B + k], "radius_index": r[S.EFFECT_RADIUS_INDEX + k],
            "period": r[S.EFFECT_AURA_PERIOD + k], "coefficient": r[S.EFFECT_BONUS_MULTIPLIER + k],
            "chain_targets": r[S.EFFECT_CHAIN_TARGETS + k],
            "class_mask_a": r[S.EFFECT_CLASS_MASK_A + k],
        } for k in range(3) if r[S.EFFECT + k]],
    })
os.makedirs(os.path.dirname(a.out), exist_ok=True)
json.dump({"family": a.family, "count": len(out), "spells": out}, open(a.out, "w"), indent=1)
print(f"family {a.family}: {len(out)} spells -> {a.out} ({os.path.getsize(a.out):,} bytes)")
