#!/usr/bin/env bash
# build-client-patch.sh -- build the ONE client archive, from both class features, in order.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# There is exactly one patch archive and there cannot be two. MPQ resolution is whole-file per
# archived path by archive priority (build/tools/acdbc/mpqlib.py), so two archives cannot both
# supply `Spell.dbc` -- the higher-priority one wins outright and the other's records are simply
# not there. `patch-Z.MPQ` is already the top of the resolved chain, measured at priority 0x46
# against `patch-3.MPQ` at 0x45, so there is no second slot to move to either:
#
#   * a `patch-Y.MPQ` would be silently shadowed by patch-Z and never read;
#   * a second generator writing `patch-Z.MPQ` would silently delete every Death Knight rank.
#
# Neither failure produces an error. Both produce a client that is quietly missing half a class.
#
# So the two generators CHAIN. dkspells.py writes its three patched DBCs and stops; dhspells.py
# reads that directory rather than the stock one, appends its own records to the same files,
# adds the ten other DBCs, the three patched UI files and the two class-icon atlases, and builds
# the archive from the union.
#
#   dkspells.py --no-mpq --out <out>      ->  <out>/dbc/{Spell,SkillLineAbility,CharStartOutfit}.dbc
#   dhspells.py          --out <out>      ->  <out>/dbc/*.dbc  +  <out>/patch-Z.MPQ
#
# Running dhspells.py alone against /srv/wow/data/dbc is legal and produces a correct Demon
# Hunter -- and a client with no Death Knights. That is why this wrapper exists and why it is
# the documented way to build the archive.
#
# usage:  scripts/build-client-patch.sh [--install] [--slot Z|enUS-4] [--out DIR]
#
#   --install   also copy the finished archive into the working client's Data/ directory
#   --slot      which archive filename to build (default Z; see docs/demon-hunters.md)
#   --out       build directory (default <repo>/.work/out)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="${CLIENT:-/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a}"
OUT="$REPO/.work/out"
SLOT="Z"
INSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=1; shift;;
        --slot)    SLOT="$2"; shift 2;;
        --out)     OUT="$2"; shift 2;;
        --client)  CLIENT="$2"; shift 2;;
        -h|--help) sed -n '2,40p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

case "$SLOT" in
    Z)      ARCHIVE="patch-Z.MPQ";            INSTALL_PATH="$CLIENT/Data/patch-Z.MPQ";;
    enUS-4) ARCHIVE="patch-enUS-4.MPQ";       INSTALL_PATH="$CLIENT/Data/enUS/patch-enUS-4.MPQ";;
    *) echo "unknown slot: $SLOT (expected Z or enUS-4)" >&2; exit 1;;
esac

# Both generators read the live world database -- player_class_stats, playercreateinfo and the
# seven gametable blocks are all DERIVED rather than transcribed. Fail here with a sentence
# rather than four hundred lines into a traceback.
if ! docker compose -f "$REPO/deploy/docker-compose.yml" ps mysql 2>/dev/null | grep -q "Up"; then
    echo "build-client-patch.sh: the mysql container is not up." >&2
    echo "  Both generators read the live world DB rather than retyping its values, so the" >&2
    echo "  archive cannot be built without it. Start the stack, or use" >&2
    echo "  scripts/package-client.sh --dh-patch skip to package the archive already in place." >&2
    exit 1
fi

echo "== 1/2  Death Knight  (writes DBCs, builds no archive)"
python3 "$REPO/build/modules/mod-dk-lowlevel/tools/dkspells.py" --out "$OUT" --no-mpq

echo
echo "== 2/2  Demon Hunter  (appends, then builds $ARCHIVE)"
DH_ARGS=(--out "$OUT" --slot "$SLOT" --client-data "$CLIENT/Data")
[[ $INSTALL -eq 1 ]] && DH_ARGS+=(--mpq "$INSTALL_PATH")
python3 "$REPO/build/modules/mod-demon-hunter/tools/dhspells.py" "${DH_ARGS[@]}"

echo
echo "== archive"
ls -la "$OUT/$ARCHIVE"
sha256sum "$OUT/$ARCHIVE"

if [[ $INSTALL -eq 1 ]]; then
    echo
    echo "== installed -> $INSTALL_PATH"
    # The other slot must not also hold an archive. Two copies is not an error to any tool, but
    # "which spell data is this client actually reading" stops being answerable.
    OTHER="$CLIENT/Data/enUS/patch-enUS-4.MPQ"
    [[ "$SLOT" == "enUS-4" ]] && OTHER="$CLIENT/Data/patch-Z.MPQ"
    if [[ -f "$OTHER" ]]; then
        echo "  !! WARNING: $OTHER also exists." >&2
        echo "     Delete it. With both present the winner is decided by archive priority" >&2
        echo "     rather than by intent, and a stale one silently shadows this build." >&2
    fi
fi
