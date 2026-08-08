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
#   * rebuilds and installs the Death Knight client patch (Data/patch-Z.MPQ), and REFUSES to
#     package a client without it while the feature is enabled. AzerothCore marks every
#     Spell.dbc Description locale FT_NA and never reads it, so the server physically cannot
#     send a tooltip -- a friend missing that 5 MB file gets a Death Knight whose only ability
#     has no name, no icon and no spellbook entry. Shipping that silently is the failure mode
#     this check exists to prevent. See docs/death-knights.md.
#   * writes a MANIFEST with the addon pins and the patch sha256, so "which build are you on"
#     and "which spell data is your client on" are both answerable.
#   * emits a sha256 next to the zip.
#
# usage:  scripts/package-client.sh --realmlist <host> [--client DIR] [--out DIR] [--tag NAME]
#                                   [--dk-patch auto|require|skip] [--dk-slot Z|enUS-4]
#
#   --dk-patch  auto     (default) rebuild + verify + require the patch iff
#                        conf/modules/mod_dk_lowlevel.conf says DKLowLevel.Enable = 1
#               require  always, whatever the conf says
#               skip     do not rebuild, verify or require it. An archive already sitting in
#                        the client still ships and is still listed in the manifest -- this
#                        is the escape hatch for packaging on a box where the generator
#                        cannot run (it needs the live MySQL), not a way to omit the file.
#   --dk-slot   client archive slot, same keys as dkspells.py --slot.
#               Z (default) = Data/patch-Z.MPQ, enUS-4 = Data/enUS/patch-enUS-4.MPQ.
#               docs/death-knights.md §4.3.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a"
OUT="/home/ali/games/wow-3.3.5a/dist"
REALM=""
TAG=""

# --- Death Knight client patch (docs/death-knights.md) --------------------------------------
# One generator emits BOTH halves of the custom low-level DK spells: world-DB *_dbc rows (what
# the server rolls) and a patched client Spell.dbc inside this MPQ (what the tooltip says).
# Regenerating here, from the same spec, is what stops the two drifting between packs.
DK_TOOL="$REPO/build/modules/mod-dk-lowlevel/tools/dkspells.py"
DK_CONF="$REPO/conf/modules/mod_dk_lowlevel.conf"
DK_DBC_IN="/srv/wow/data/dbc"   # stock server DBCs, never modified -- they are the clone source
DK_SLOT="Z"                     # slot KEY, same vocabulary as dkspells.py --slot
DK_MODE="auto"

# Slot key -> path under Data/. 'Z' is the top of the client's single-character patch sort, so
# nothing (including the ChromieCraft HD packs) can outrank it; enUS-4 is the documented
# fallback. Keep this map in step with dk_spec.py MPQ_SLOTS.
dk_slot_path() {
    case "$1" in
        Z)      echo "patch-Z.MPQ";;
        enUS-4) echo "enUS/patch-enUS-4.MPQ";;
        *) echo "package-client.sh: --dk-slot must be Z or enUS-4 (got '$1')" >&2; return 1;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --realmlist) REALM="$2"; shift 2;;
        --client)    CLIENT="$2"; shift 2;;
        --out)       OUT="$2"; shift 2;;
        --tag)       TAG="$2"; shift 2;;
        --dk-patch)  DK_MODE="$2"; shift 2;;
        --dk-slot)   DK_SLOT="$2"; shift 2;;
        -h|--help)   sed -n '2,35p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

[[ -n "$REALM" ]] || { echo "package-client.sh: --realmlist is required.
  It is the address YOUR FRIENDS type, i.e. the tailnet IP or hostname of the VPS --
  not 127.0.0.1, which is what the working copy uses. There is no safe default." >&2; exit 1; }
[[ -f "$CLIENT/Wow.exe" ]] || { echo "no Wow.exe under $CLIENT" >&2; exit 1; }

case "$DK_MODE" in
    auto|require|skip) ;;
    *) echo "package-client.sh: --dk-patch must be auto, require or skip (got '$DK_MODE')" >&2; exit 1;;
esac

command -v zip >/dev/null || { echo "package-client.sh: needs 'zip' (pacman -S zip)" >&2; exit 1; }

# Is the low-level Death Knight feature on? conf/modules/ is bind-mounted into the container
# (deploy/docker-compose.yml), so this file IS the live server config, not a template of it.
dk_required() {
    case "$DK_MODE" in
        require) return 0;;
        skip)    return 1;;
        # anchored on purpose: this repo's conf parser has no inline-comment handling, so a
        # value line is the whole line. '= 1' means on; anything else, including a missing
        # file, means off.
        *)       grep -Eq '^[[:space:]]*DKLowLevel\.Enable[[:space:]]*=[[:space:]]*1[[:space:]]*$' "$DK_CONF" 2>/dev/null;;
    esac
}

DK_REL="$(dk_slot_path "$DK_SLOT")"
DK_MPQ="$CLIENT/Data/$DK_REL"

if dk_required; then
    echo "== dk client patch -> Data/$DK_REL"
    if [[ -f "$DK_TOOL" && -d "$DK_DBC_IN" ]]; then
        command -v python3 >/dev/null \
          || { echo "package-client.sh: needs python3 to build $DK_REL (pacman -S python)" >&2; exit 1; }
        mkdir -p "$REPO/.work/out" "$(dirname "$DK_MPQ")"
        # set -euo pipefail: a generator that fails its own invariants (SQL row vs DBC row
        # mismatch, non-dense spell_ranks, wrong column count) aborts the whole package here,
        # which is the point -- a pack built from a half-written MPQ is worse than no pack.
        python3 "$DK_TOOL" \
            --dbc-in "$DK_DBC_IN" \
            --out    "$REPO/.work/out" \
            --slot   "$DK_SLOT" \
            --mpq    "$DK_MPQ"
        # Reproduces the client's archive-priority model and fails if something outranks us
        # for DBFilesClient\Spell.dbc. Cheap, and it runs BEFORE the multi-minute zip.
        python3 "$DK_TOOL" --verify --client-data "$CLIENT/Data" --slot "$DK_SLOT"
    elif [[ -f "$DK_MPQ" ]]; then
        echo "   NOTE: no generator at $DK_TOOL -- shipping the existing archive UNVERIFIED." >&2
        echo "         Its spell data may not match what the server is running." >&2
    else
        echo "package-client.sh: the low-level Death Knight feature is enabled but there is no
  client patch to ship, and no way to build one here.

    wanted:    $DK_MPQ
    generator: $DK_TOOL        $([[ -f "$DK_TOOL"    ]] && echo present || echo MISSING)
    stock DBC: $DK_DBC_IN      $([[ -d "$DK_DBC_IN"  ]] && echo present || echo MISSING)

  Do NOT work around this by re-running with --dk-patch skip unless you mean it. The server
  cannot render a spell tooltip (every Spell.dbc Description locale is FT_NA in AzerothCore),
  so a client without this archive has no Icy Touch at all -- no name, no icon, no button.
  Build it first:  docs/death-knights.md §4.2" >&2
        exit 1
    fi

    [[ -f "$DK_MPQ" ]] \
      || { echo "package-client.sh: generator exited 0 but wrote no $DK_MPQ" >&2; exit 1; }

    # Two copies of the patch in two slots is not fatal -- one of them just loses -- but it
    # makes "which spell data is this client reading" unanswerable. Say so.
    for other in Z enUS-4; do
        rel="$(dk_slot_path "$other")"
        if [[ "$rel" != "$DK_REL" && -f "$CLIENT/Data/$rel" ]]; then
            echo "   WARNING: a second DK patch exists at Data/$rel -- delete it" >&2
        fi
    done
else
    echo "== dk client patch: not required (--dk-patch $DK_MODE)"
fi

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

DK_STAGED="$S/Data/$DK_REL"
if dk_required && [[ ! -f "$DK_STAGED" ]]; then
    echo "package-client.sh: Data/$DK_REL exists in the working client but did not reach the
  stage ($DK_STAGED). Refusing to zip a client that would break Death Knights." >&2
    exit 1
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
    # Ask a friend for these two lines before debugging any "my tooltip is wrong" report:
    # a mismatched sha256 explains it on the spot. docs/death-knights.md §8.
    echo "client patch (custom spell DBC):"
    if [[ -f "$DK_STAGED" ]]; then
        printf '  %-46s %s bytes\n' "Data/$DK_REL" "$(stat -c%s "$DK_STAGED")"
        printf '  %-46s %s\n' "sha256" "$(sha256sum "$DK_STAGED" | cut -d' ' -f1)"
    else
        echo "  none -- stock Death Knights (level 55, Acherus)"
    fi
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
if dk_required; then
    echo
    echo "Spell data changed but nothing else? Do not make anyone re-download 17 GB --"
    echo "send the 5 MB archive on its own, they drop it in <WoW>/Data/ and restart:"
    echo "  $DK_MPQ"
    echo "Then have them confirm it loaded:  /dump GetSpellInfo(90000)   -> \"Icy Touch\", \"Rank 1\""
fi
