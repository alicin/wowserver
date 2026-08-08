#!/usr/bin/env bash
# package-client.sh -- build a distributable client zip for the friends.
#
# The flow this exists for: we keep ONE unzipped working client, keep improving it (addons,
# custom features, patch MPQs), and re-cut a zip whenever it is worth re-downloading. The zip
# is served from the VPS so three people can pull it without a torrent.
#
# What it does that a plain `zip -r` does not:
#   * rewrites realmlist to the address the FRIENDS use, not the one on this dev box. Shipping
#     a client pointing at 127.0.0.1 is the single most predictable way to waste an evening.
#   * strips per-machine state (WTF/Account, Cache, Logs, Errors) so nobody inherits your
#     keybinds, your saved account name or a stale addon cache.
#   * writes a MANIFEST with the addon pins, so "which build are you on" is answerable.
#   * emits a sha256 next to the zip.
#
# usage:  scripts/package-client.sh --realmlist <host> [--client DIR] [--out DIR] [--tag NAME]

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a"
OUT="/home/ali/games/wow-3.3.5a/dist"
REALM=""
TAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --realmlist) REALM="$2"; shift 2;;
        --client)    CLIENT="$2"; shift 2;;
        --out)       OUT="$2"; shift 2;;
        --tag)       TAG="$2"; shift 2;;
        -h|--help)   sed -n '2,18p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

[[ -n "$REALM" ]] || { echo "package-client.sh: --realmlist is required.
  It is the address YOUR FRIENDS type, i.e. the tailnet IP or hostname of the VPS --
  not 127.0.0.1, which is what the working copy uses. There is no safe default." >&2; exit 1; }
[[ -f "$CLIENT/Wow.exe" ]] || { echo "no Wow.exe under $CLIENT" >&2; exit 1; }

command -v zip >/dev/null || { echo "package-client.sh: needs 'zip' (pacman -S zip)" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M)"
NAME="wow335-${TAG:+$TAG-}$STAMP"
STAGE="$(mktemp -d)/$NAME"
mkdir -p "$STAGE" "$OUT"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT

echo "== staging (hardlink copy, no 17 GB duplication)"
cp -al "$CLIENT" "$STAGE/ChromieCraft_3.3.5a" 2>/dev/null \
  || cp -a "$CLIENT" "$STAGE/ChromieCraft_3.3.5a"
S="$STAGE/ChromieCraft_3.3.5a"

echo "== stripping per-machine state"
rm -rf "$S/WTF/Account" "$S/Cache" "$S/Logs" "$S/Errors" "$S/Screenshots"
find "$S" -maxdepth 1 -iname '*.log' -delete 2>/dev/null || true

echo "== realmlist -> $REALM"
for d in "$S"/Data/[a-z][a-z][A-Z][A-Z]; do
    [[ -d "$d" ]] && printf 'set realmlist %s\n' "$REALM" > "$d/realmlist.wtf"
done
mkdir -p "$S/WTF"
# Config.wtf uses a DIFFERENT syntax from realmlist.wtf: quoted, camel-cased key.
if [[ -f "$S/WTF/Config.wtf" ]]; then
    sed -i -E "s|^SET realmList .*|SET realmList \"$REALM\"|I" "$S/WTF/Config.wtf"
    grep -qi '^SET realmList ' "$S/WTF/Config.wtf" || printf 'SET realmList "%s"\n' "$REALM" >> "$S/WTF/Config.wtf"
else
    printf 'SET realmList "%s"\nSET checkAddonVersion "0"\nSET gxApi "d3d9"\n' "$REALM" > "$S/WTF/Config.wtf"
fi

echo "== manifest"
{
    echo "wowserver client pack"
    echo "build:     $NAME"
    echo "realmlist: $REALM"
    echo "built:     $(date -Iseconds)"
    echo "repo:      $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo
    echo "addons (pinned):"
    grep -E '^[A-Za-z]' "$REPO/client/addons.txt" 2>/dev/null | awk '{printf "  %-46s %s\n",$1,substr($4,1,10)}'
    echo
    echo "AddOns folders: $(find "$S/Interface/AddOns" -maxdepth 1 -mindepth 1 -type d | wc -l)"
} > "$S/PACK-MANIFEST.txt"

echo "== zipping (this takes a few minutes for ~17 GB)"
( cd "$STAGE" && zip -r -q -1 "$OUT/$NAME.zip" "ChromieCraft_3.3.5a" )

echo "== sha256"
( cd "$OUT" && sha256sum "$NAME.zip" > "$NAME.zip.sha256" )

ls -la "$OUT/$NAME.zip" | awk '{printf "\n  %s  (%.1f GB)\n", $NF, $5/1073741824}'
echo "  $(cat "$OUT/$NAME.zip.sha256")"
echo
echo "Serve it from the VPS, e.g.:"
echo "  rsync -avP $OUT/$NAME.zip* wow:/srv/wow/dist/"
