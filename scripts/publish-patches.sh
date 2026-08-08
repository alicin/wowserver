#!/usr/bin/env bash
# publish-patches.sh -- publish the loose client patches + a manifest the updater reads.
#
# The release zips are for first install. This is for AFTERWARDS: when spell data changes, a
# friend should fetch ~4 MB, not 16.6 GB. The updater scripts (client/updater/) read the manifest
# this writes, compare sha256 against what is on their disk, and download only what differs.
#
# Deliberately files-not-archives: an MPQ is already compressed, so zipping it buys nothing and
# costs the updater an unzip step and a temp file.
#
# usage:  scripts/publish-patches.sh [--client DIR] [--out DIR]

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a"
OUT="/home/ali/games/wow-3.3.5a/dist"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --client) CLIENT="$2"; shift 2;;
        --out)    OUT="$2"; shift 2;;
        -h|--help) sed -n '2,12p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

PATCHDIR="$OUT/patches"
mkdir -p "$PATCHDIR"

# What the updater is allowed to manage. Each entry is  <source path>  <dest relative to WoW root>.
# Keep this list SHORT and explicit: the updater deletes/overwrites exactly these paths on a
# friend's machine, so anything added here is a thing we can break remotely.
ENTRIES=(
    "$CLIENT/Data/patch-Z.MPQ|Data/patch-Z.MPQ|Custom Death Knight spell data (low-level ranks, tooltips)"
)

say() { printf '  %s\n' "$*"; }
echo "== collecting patches"

json_items=""
for e in "${ENTRIES[@]}"; do
    IFS='|' read -r src dest desc <<< "$e"
    if [[ ! -f "$src" ]]; then
        echo "publish-patches.sh: missing $src" >&2; exit 1
    fi
    name="$(basename "$dest")"
    cp -f "$src" "$PATCHDIR/$name"
    sum="$(sha256sum "$PATCHDIR/$name" | cut -d' ' -f1)"
    size="$(stat -c%s "$PATCHDIR/$name")"
    # awk, not bc: bc is not installed on this box and is not present by default on Debian
    # either, so a size display should not be the thing that breaks a release script.
    say "$(awk -v n="$name" -v b="$size" -v h="${sum:0:12}" \
             'BEGIN{printf "%-18s %8.2f MB  %s", n, b/1048576, h}')"
    [[ -n "$json_items" ]] && json_items+=","
    json_items+=$(printf '\n    {"file": "%s", "dest": "%s", "bytes": %s, "sha256": "%s", "description": "%s"}' \
        "$name" "$dest" "$size" "$sum" "$desc")
done

cat > "$OUT/patches.json" <<EOF
{
  "schema": 1,
  "generated": "$(date -Iseconds)",
  "realmlist": "167.233.128.19",
  "base_url": "https://wow.allahaema.net/files/patches/",
  "note": "Updater manifest. Each entry is copied to <WoW>/<dest> only when the local sha256 differs.",
  "patches": [$json_items
  ]
}
EOF

echo "== manifest"
say "$OUT/patches.json"
python3 -c "import json;d=json.load(open('$OUT/patches.json'));print('  %d patch(es), schema %d'%(len(d['patches']),d['schema']))"
