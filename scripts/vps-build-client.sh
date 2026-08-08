#!/usr/bin/env bash
# vps-build-client.sh -- build the distributable client ON THE VPS. Runs on the server, not here.
#
# Why this exists: the dev box uploads at ~1.2 MB/s and the VPS downloads at ~23 MB/s. Pushing a
# 16.6 GB zip up took an estimated 4 hours; having the VPS pull the same bytes from the public
# torrent takes ~12 minutes. So we upload only the ~84 MB of things that are OURS (addons, the
# Death Knight patch MPQ, the realmlist) and let the server assemble the full download itself.
#
# Idempotent: re-running with the base zip already present skips the torrent.

set -euo pipefail

WOW=/srv/wow
DIST="$WOW/dist"
CLIENT="$WOW/client/ChromieCraft_3.3.5a"
REALM="${REALM:-167.233.128.19}"

say() { printf '\n== %s\n' "$*"; }

say "torrent"
cd "$WOW"
if [[ -f ChromieCraft_3.3.5a.zip && ! -f ChromieCraft_3.3.5a.zip.aria2 ]]; then
    echo "   base zip already present, skipping download"
else
    aria2c --seed-time=0 --max-connection-per-server=8 --split=16 --bt-max-peers=100 \
           --summary-interval=60 --console-log-level=warn --dir="$WOW" \
           "$WOW/ChromieCraft_3.3.5a.zip.torrent"
fi

say "unzip base"
rm -rf "$WOW/client"; mkdir -p "$WOW/client"
unzip -q -o "$WOW/ChromieCraft_3.3.5a.zip" -d "$WOW/client"
[[ -f "$CLIENT/Wow.exe" ]] || { echo "no Wow.exe after unzip -- wrong archive layout" >&2; exit 1; }

# Drop the base archive the moment it is extracted. Peak disk was base(16.5 GB) +
# extracted(17 GB) + output(16.6 GB) = ~50 GB on a 71 GB box that also holds 3.1 GB of client
# data, the game image and the databases -- it ran out mid-rezip the first time. The base zip is
# reproducible from the torrent in ~2 minutes, so it is the cheapest thing to throw away.
rm -f "$WOW/ChromieCraft_3.3.5a.zip"
df -h / | tail -1 | awk '{print "   freed base zip; disk free: "$4}'

say "apply our extras"
# Each extras zip is built to unzip over a client ROOT (Interface/AddOns/..., Data/...), so this
# is just an overlay. READMEs are excluded: they are for the friend who downloads the small
# artefact on its own, and would otherwise litter the client root.
shopt -s nullglob
for z in "$DIST"/addons-*.zip "$DIST"/gm-addons-*.zip "$DIST"/dk-patch-*.zip "$DIST"/realmlist-*.zip; do
    echo "   + $(basename "$z")"
    unzip -q -o "$z" -d "$CLIENT" -x 'README*' '*/README*'
done
shopt -u nullglob

say "realmlist -> $REALM"
for d in "$CLIENT"/Data/[a-z][a-z][A-Z][A-Z]; do
    [[ -d "$d" ]] || continue
    rm -f "$d/realmlist.wtf"                       # never write through a hardlink
    printf 'set realmlist %s\n' "$REALM" > "$d/realmlist.wtf"
done
mkdir -p "$CLIENT/WTF"
printf 'SET realmList "%s"\nSET checkAddonVersion "0"\nSET gxApi "d3d9"\n' "$REALM" > "$CLIENT/WTF/Config.wtf"

say "sanity"
echo "   realmlist : $(cat "$CLIENT/Data/enUS/realmlist.wtf")"
echo "   patch-Z   : $([[ -f "$CLIENT/Data/patch-Z.MPQ" ]] && echo present || echo MISSING)"
echo "   addons    : $(find "$CLIENT/Interface/AddOns" -maxdepth 1 -mindepth 1 -type d | wc -l) folders"
echo "   ItemBrowser/AzerothAdmin: $([[ -d "$CLIENT/Interface/AddOns/ItemBrowser" ]] && echo yes || echo NO) / $([[ -d "$CLIENT/Interface/AddOns/AzerothAdmin" ]] && echo yes || echo NO)"

say "rezip"
OUT="$DIST/wow335-release-vps.zip"
rm -f "$OUT" "$OUT.sha256"
cd "$WOW/client"
zip -r -q -1 "$OUT" ChromieCraft_3.3.5a
cd "$DIST"
sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256"

say "done"
ls -la "$OUT" | awk '{printf "   %s  %.2f GB\n", $NF, $5/1073741824}'
cat "$(basename "$OUT").sha256"
# Reclaim: the extracted tree is ~17 GB and is only needed while building.
rm -rf "$WOW/client"
df -h / | tail -1 | awk '{print "   disk free after cleanup: "$4}'
