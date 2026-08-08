#!/usr/bin/env bash
# regen.sh -- rebuild the ItemBrowser Lua item database from the live world DB.
#
# Safe to re-run: the generator is deterministic, so a re-run against an unchanged
# item_template rewrites the same bytes. Nothing here writes to any database.
#
# The two-step shape (emit, then --check) is deliberate. --check re-derives everything from
# the DB and byte-compares it with what is now on disk, so a half-written file, a stale shard
# left over from a smaller --shard-rows, or a Lua file that does not parse all fail HERE,
# rather than as an addon that silently fails to load three people's clients later.
#
# usage:  tools/regen.sh [--icon-check] [--client-data DIR] [-- <extra itemdb.py args>]
#
#   --icon-check       additionally probe every icon name against the client's MPQ archives
#                      and print the ones that resolve to no file. Slow (~25 s, it walks
#                      every archive's hash table) and purely informational.
#   --client-data DIR  which client to probe. Default: the working client on this box.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON="$(dirname "$HERE")"
TOOL="$HERE/itemdb.py"
CLIENT_DATA="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Data"
ICON_CHECK=0
EXTRA=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --icon-check)  ICON_CHECK=1; shift;;
        --client-data) CLIENT_DATA="$2"; shift 2;;
        --)            shift; EXTRA=("$@"); break;;
        -h|--help)     sed -n '2,20p' "$0"; exit 0;;
        *) echo "regen.sh: unknown argument '$1' (use -- to pass args straight to itemdb.py)" >&2
           exit 1;;
    esac
done

command -v python3 >/dev/null || { echo "regen.sh: needs python3" >&2; exit 1; }
[[ -f "$TOOL" ]] || { echo "regen.sh: no generator at $TOOL" >&2; exit 1; }

args=()
if [[ $ICON_CHECK -eq 1 ]]; then
    [[ -d "$CLIENT_DATA" ]] || { echo "regen.sh: no client Data/ at $CLIENT_DATA" >&2; exit 1; }
    args+=(--icon-check "$CLIENT_DATA")
fi
if [[ ${#EXTRA[@]} -gt 0 ]]; then
    args+=("${EXTRA[@]}")
fi

echo "== generating"
python3 "$TOOL" ${args[@]+"${args[@]}"}

echo
echo "== verifying"
python3 "$TOOL" --check ${EXTRA[@]+"${EXTRA[@]}"}

echo
echo "Generated files are in $ADDON/ItemBrowser/Data/."
echo "Install them into the working client with:  scripts/client-addons.sh"
