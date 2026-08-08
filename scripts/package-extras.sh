#!/usr/bin/env bash
# package-extras.sh -- build the SMALL downloadable artefacts, and own downloads.json.
#
# package-client.sh cuts one ~17 GB zip. That is the wrong unit for almost every real request:
# "the spell data changed" is 4 MB, "I want your addon set" is ~120 MB, "which address do I
# type" is one line. Making a friend re-pull 17 GB for any of those is how a Tuesday evening
# disappears. This script cuts each of those as its own download, and writes the ONE manifest
# the download webapp reads so a new artefact needs no webapp change.
#
# usage:  scripts/package-extras.sh [--realmlist HOST] [--client DIR] [--out DIR]
#                                   [--stamp STAMP] [--only ID[,ID...]] [--dk-slot Z|enUS-4]
#                                   [--client-zip PATH|none] [--manifest PATH]
#
#   --realmlist HOST   the address FRIENDS type. Required when the `realmlist` artefact is in
#                      scope, or when the manifest has no realmlist recorded yet; otherwise
#                      inherited from the existing manifest. Never defaulted -- shipping
#                      127.0.0.1 is the single most predictable way to waste an evening.
#   --only ID,...      rebuild just these artefacts. The manifest MERGES, so the entries you
#                      did not rebuild survive untouched. This is the whole point of the merge.
#   --client-zip PATH  use this file as the full-client artefact instead of scanning (below).
#                      `none` skips the client entry entirely for this run.
#   --dk-slot          which client archive slot the DK patch ships in, same keys as
#                      package-client.sh: Z (default) = Data/patch-Z.MPQ,
#                      enUS-4 = Data/enUS/patch-enUS-4.MPQ.
#
#
# ===========================================================================================
# THE MANIFEST CONTRACT  (downloads.json -- read by the webapp, written only by this script)
# ===========================================================================================
#
# One JSON object, written to <out>/downloads.json, next to the files it describes. Manifest
# and files travel together (one rsync of the directory), so a path in the manifest is always
# resolvable relative to the manifest itself. The webapp must not hardcode filenames -- they
# carry a build stamp and change every cut; it looks artefacts up by `id`.
#
#   {
#     "schema": 1,                          int, bumped only on a BREAKING change
#     "generated": "2026-08-08T16:12:03+03:00",
#     "realmlist": "167.233.128.19",        what the friend types in realmlist.wtf
#     "repo": "a0f4041",                    short SHA this manifest was cut from, or "unknown".
#                                           Display it small somewhere: it is what makes a
#                                           friend's "my client is weird" report answerable.
#     "artifacts": [ {...}, ... ]           sorted by `order`, ascending
#   }
#
# Every artefact object:
#
#   id          string, STABLE ACROSS BUILDS and unique. The webapp's primary key: link
#               targets, download counters and "you already have this" state all hang off it.
#               Currently: client-full | dk-patch | addons | gm-addons | realmlist
#   kind        coarse type for grouping/iconing: client | patch | addons | config
#   title       human title, headline-cased, no filename in it
#   filename    basename only, relative to the manifest's own directory. Never a path.
#   bytes       int, exact
#   size_human  pre-formatted ("4.4 MB"), so the webapp needs no formatter to agree with us
#   sha256      lowercase hex, of the file named above
#   description what it IS and why it exists. Multi-line, plain text, safe to render as <p>.
#   audience    "who needs this" -- one sentence, imperative, aimed at a friend deciding
#               whether to click. This is the field that stops someone pulling 17 GB twice.
#   install     one line: where it goes. Empty string if not applicable.
#   contains    array of archive-relative paths/globs, for a "what's in it" disclosure
#   order       int sort key, ascending, gaps left on purpose (10,20,30...) so a future
#               artefact can slot in without renumbering
#   built       ISO-8601 with offset, when THIS artefact was cut
#   stamp       the YYYYMMDD-HHMM in its filename, or "" for artefacts we did not stamp
#
# Rules the webapp can rely on:
#   * `artifacts` is never empty and is always sorted by `order`.
#   * Every listed file EXISTS next to the manifest at write time -- entries whose file has
#     gone are dropped (see MERGE below), so a manifest entry is a servable file, not a wish.
#   * A sibling `<filename>.sha256` exists for every artefact, in `sha256sum` format.
#   * Adding fields is not breaking; the webapp must ignore unknown keys. Removing a field or
#     changing a field's meaning bumps `schema`.
#
# MERGE / IDEMPOTENCY
#   Re-running rebuilds only the artefacts in scope and rewrites only those entries. Entries
#   not in scope are carried over verbatim. Then every carried-over entry is re-checked
#   against the filesystem and DROPPED if its file is gone -- a manifest that advertises a
#   deleted file hands a friend a 404, which reads as "the server is broken". Regenerating is
#   cheap; a wrong manifest is not. Superseded files from older stamps are reported, never
#   deleted: this script does not remove things you might still be seeding.
#
# THE FULL-CLIENT ENTRY  (produced by package-client.sh, which this script must not edit)
#   Mechanism: we SCAN <out> for wow335-*.zip and adopt the newest -- but only one that has a
#   matching <name>.zip.sha256 beside it. That sidecar is the completion signal: package-
#   client.sh writes it strictly after `zip` returns, so its presence means the zip is closed
#   and its absence means the zip is still growing. (zip also writes through a random temp
#   name with no .zip suffix while working, so the glob cannot even see a partial file --
#   the sidecar gate is the belt to that suspenders.) The sha256 is READ from the sidecar,
#   never recomputed: re-hashing 17 GB on every extras run is 60+ seconds of nothing.
#   `--client-zip PATH` overrides the scan for a zip kept somewhere else; `--client-zip none`
#   skips it. If no client zip is found, any existing client-full entry is left alone.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a"
OUT="/home/ali/games/wow-3.3.5a/dist"
REALM=""
STAMP=""
ONLY=""
DK_SLOT="Z"
CLIENT_ZIP=""
MANIFEST=""

# The GM tools ship as their own download and are excluded from the general addon pack: they
# are inert without gmlevel >= 2, and a friend at level 0 who installs them gets a panel whose
# every button silently does nothing (§ gm-addons README). Keep this list and the gm-addons
# artefact in step -- they are the two halves of one decision.
GM_ADDONS=(AzerothAdmin ItemBrowser)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --realmlist)  REALM="$2"; shift 2;;
        --client)     CLIENT="$2"; shift 2;;
        --out)        OUT="$2"; shift 2;;
        --stamp)      STAMP="$2"; shift 2;;
        --only)       ONLY="$2"; shift 2;;
        --dk-slot)    DK_SLOT="$2"; shift 2;;
        --client-zip) CLIENT_ZIP="$2"; shift 2;;
        --manifest)   MANIFEST="$2"; shift 2;;
        -h|--help)    sed -n '2,25p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

for t in zip unzip jq sha256sum; do
    command -v "$t" >/dev/null || { echo "package-extras.sh: needs '$t'" >&2; exit 1; }
done
[[ -f "$CLIENT/Wow.exe" ]] || { echo "package-extras.sh: no Wow.exe under $CLIENT" >&2; exit 1; }

ALL_IDS=(dk-patch addons gm-addons realmlist)
if [[ -n "$ONLY" ]]; then
    IFS=',' read -r -a WANT <<< "$ONLY"
    for w in "${WANT[@]}"; do
        # client-full is accepted here so `--only client-full` can refresh just that entry
        # after package-client.sh finishes, without recutting the small zips.
        [[ " ${ALL_IDS[*]} client-full " == *" $w "* ]] \
          || { echo "package-extras.sh: --only: unknown id '$w' (have: ${ALL_IDS[*]} client-full)" >&2; exit 1; }
    done
else
    WANT=("${ALL_IDS[@]}")
fi
in_scope() { [[ " ${WANT[*]} " == *" $1 "* ]]; }

: "${MANIFEST:=$OUT/downloads.json}"
mkdir -p "$OUT"

# realmlist: required if we are cutting that artefact, otherwise inherited. The manifest must
# always carry one -- it is what the webapp prints on the "how do I connect" line.
PREV_REALM=""
[[ -f "$MANIFEST" ]] && PREV_REALM="$(jq -r '.realmlist // ""' "$MANIFEST")"
if [[ -z "$REALM" ]]; then
    REALM="$PREV_REALM"
    [[ -n "$REALM" ]] || { echo "package-extras.sh: --realmlist is required.
  It is the address YOUR FRIENDS type -- the VPS public IP or hostname, not 127.0.0.1, which
  is what the dev working copy uses. Nothing sane can be defaulted here." >&2; exit 1; }
fi
# Moving the realm without recutting the realmlist artefact publishes a realmlist.wtf that
# points at the old address -- the download page would then say one thing and the file a
# friend unzips would say another. Warned at the end, where it will actually be read.
REALM_MOVED=0
if [[ -n "$PREV_REALM" && "$PREV_REALM" != "$REALM" ]] && ! in_scope realmlist; then
    REALM_MOVED=1
fi

case "$DK_SLOT" in
    Z)      DK_REL="Data/patch-Z.MPQ";;
    enUS-4) DK_REL="Data/enUS/patch-enUS-4.MPQ";;
    *) echo "package-extras.sh: --dk-slot must be Z or enUS-4 (got '$DK_SLOT')" >&2; exit 1;;
esac

: "${STAMP:=$(date +%Y%m%d-%H%M)}"
NOW="$(date -Iseconds)"
TMPD="$(mktemp -d)"; trap 'rm -rf "$TMPD"' EXIT
DELTA="$TMPD/delta.json"; echo '[]' > "$DELTA"

human() {  # bytes -> "4.4 MB". Pre-formatted in the manifest so the webapp cannot disagree.
    awk -v b="$1" 'BEGIN{
        split("B KB MB GB TB",u," "); i=1
        while (b>=1024 && i<5) { b/=1024; i++ }
        printf (i==1 ? "%d %s\n" : "%.1f %s\n"), b, u[i]
    }'
}

# Append one artefact entry to the delta. jq --arg everywhere: descriptions are multi-line and
# contain quotes, and hand-rolled JSON quoting in bash is a bug waiting for a bad character.
record() {
    local id="$1" kind="$2" order="$3" title="$4" file="$5" sha="$6" desc="$7" who="$8" inst="$9" stamp="${10}"
    shift 10
    local bytes; bytes="$(stat -c%s "$file")"
    local contains; contains="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
    jq --arg id "$id" --arg kind "$kind" --argjson order "$order" --arg title "$title" \
       --arg filename "$(basename "$file")" --argjson bytes "$bytes" \
       --arg size_human "$(human "$bytes")" --arg sha256 "$sha" \
       --arg description "$desc" --arg audience "$who" --arg install "$inst" \
       --argjson contains "$contains" --arg built "$NOW" --arg stamp "$stamp" \
       '. + [{$id,$kind,$title,$filename,$bytes,$size_human,$sha256,$description,$audience,
              $install,$contains,$order,$built,$stamp}]' \
       "$DELTA" > "$DELTA.new" && mv "$DELTA.new" "$DELTA"
}

# Hash + sidecar in one place. The sidecar is part of the contract: a friend on a flaky
# connection can verify a 17 GB download without asking anyone for the number.
seal() {
    local f="$1"
    ( cd "$(dirname "$f")" && sha256sum "$(basename "$f")" > "$(basename "$f").sha256" )
    cut -d' ' -f1 < "$f.sha256"
}

# ---------------------------------------------------------------------------------------- #
# 1. dk-patch -- the 4 MB file that is the entire reason low-level Death Knights work
# ---------------------------------------------------------------------------------------- #
if in_scope dk-patch; then
    echo "== dk-patch"
    SRC="$CLIENT/$DK_REL"
    if [[ ! -f "$SRC" ]]; then
        echo "package-extras.sh: no $DK_REL in the working client.
  Build it first (docs/death-knights.md §4.2) or pass --dk-slot for the other slot. Shipping
  the pack without it is not an option this script offers: the server cannot send a spell
  tooltip, so an unpatched client has no Icy Touch at all." >&2
        exit 1
    fi
    F="$OUT/dk-patch-$STAMP.zip"; rm -f "$F"
    cat > "$TMPD/README-dk-patch.txt" <<EOF
Death Knight client patch -- $DK_REL
built $NOW   realmlist $REALM

WHAT THIS IS
  A ${DK_SLOT} slot MPQ archive holding a patched Spell.dbc: the client-side half of this
  realm's custom low-level Death Knights. The server half is already live; this file is the
  only piece that lives on your machine.

WHY YOU CANNOT SKIP IT
  AzerothCore marks every Spell.dbc Description locale FT_NA -- it reads the row and throws
  the text away -- so the server physically cannot send a spell description over the wire.
  Custom spell 90000 (Icy Touch, Rank 1) therefore does not exist in a stock client AT ALL:
  no name, no icon, no spellbook entry. The server puts it in your initial spell list and
  your client has nothing to draw. A level-1 Death Knight without this file has an empty
  action bar and no way to cast their only ability.

INSTALL
  1. Fully quit WoW.
  2. Copy the file below into your client's Data folder, keeping the name exactly:
         <WoW>/$DK_REL
     Not <WoW>/Data/Data/, not renamed, not unzipped-into-a-subfolder.
  3. Start Wow.exe (not Launcher.exe).

CHECK IT LOADED
  In game:   /dump GetSpellInfo(90000)
  Expect:    "Icy Touch", "Rank 1".  Anything else (nil, an error) means it did not load --
             re-check the path and that the filename case is exactly as above.

DO NOT INSTALL TWO
  If you also have Data/enUS/patch-enUS-4.MPQ from an older hand-off, delete it. Two copies
  in two slots is not fatal, but one silently loses and nobody can then say which spell data
  your client is reading.

ALREADY IN THE FULL CLIENT ZIP -- you only need this file if you are patching a client you
already have.
EOF
    ( cd "$CLIENT" && zip -q -9 "$F" "$DK_REL" )
    ( cd "$TMPD"   && zip -q -9 "$F" "README-dk-patch.txt" )
    SHA="$(seal "$F")"
    record dk-patch patch 20 "Death Knight spell patch" "$F" "$SHA" \
"The client-side half of this realm's custom low-level Death Knights: one small MPQ archive
containing a patched Spell.dbc.

AzerothCore never sends spell descriptions (every Spell.dbc Description locale is FT_NA in
the core, read and discarded), so custom spell 90000 -- Icy Touch, Rank 1 -- simply does not
exist in an unpatched client. No name, no icon, no spellbook entry, and an empty action bar
on a level-1 Death Knight.

Drops into <WoW>/$DK_REL and needs a full client restart. Verify with
/dump GetSpellInfo(90000), which should answer \"Icy Touch\", \"Rank 1\"." \
"Anyone who already has the client but rolled -- or plans to roll -- a Death Knight, and anyone told the spell data changed. Already inside the full client zip; grab this instead of re-downloading it." \
"Copy into <WoW>/$DK_REL, then restart the client." "$STAMP" \
        "$DK_REL" "README-dk-patch.txt"
    ls -l "$F" | awk '{printf "   %s bytes  %s\n", $5, $NF}'
fi

# ---------------------------------------------------------------------------------------- #
# 2. addons -- the pinned pack, minus stock Blizzard_* and minus the GM tools
# ---------------------------------------------------------------------------------------- #
if in_scope addons; then
    echo "== addons"
    AD="$CLIENT/Interface/AddOns"
    [[ -d "$AD" ]] || { echo "package-extras.sh: no $AD" >&2; exit 1; }

    LIST=(); NAMES=()
    for d in "$AD"/*/; do
        n="$(basename "$d")"
        # Blizzard_* is stock UI that ships inside every 3.3.5a client. Packing it adds weight
        # and, worse, lets an old copy overwrite a friend's matching stock files.
        [[ "$n" == Blizzard_* ]] && continue
        [[ " ${GM_ADDONS[*]} " == *" $n "* ]] && continue
        LIST+=("Interface/AddOns/$n"); NAMES+=("$n")
    done
    [[ ${#LIST[@]} -gt 0 ]] || { echo "package-extras.sh: no shippable addons found in $AD" >&2; exit 1; }

    F="$OUT/addons-$STAMP.zip"; rm -f "$F"
    {
        echo "Addon pack -- $(printf '%s' "${#NAMES[@]}") addons"
        echo "built $NOW   realmlist $REALM"
        echo
        echo "WHAT THIS IS"
        echo "  The addon set the server runs with, pinned by commit in client/addons.txt so"
        echo "  everyone is on the same build. Stock Blizzard_* UI is deliberately NOT in here"
        echo "  -- your client already has it, and overwriting it with an older copy breaks the"
        echo "  default UI. The GM tools are a separate download; they do nothing without a GM"
        echo "  account."
        echo
        echo "INSTALL"
        echo "  1. Fully quit WoW."
        echo "  2. Unzip this OVER YOUR CLIENT FOLDER -- the one with Wow.exe in it. The zip"
        echo "     already carries the Interface/AddOns/ path, so folders land in the right"
        echo "     place and same-named addons are replaced."
        echo "  3. Start Wow.exe. At the character-select screen click AddOns (bottom left),"
        echo "     tick \"Load out of date AddOns\", enable what you want, Okay."
        echo
        echo "  These are 3.3.5a forks and most report an older interface number, so without"
        echo "  that tickbox they show up greyed out and load nothing."
        echo
        echo "SETTINGS"
        echo "  Addon config lives in WTF/Account/<NAME>/ on your machine and is not shipped."
        echo "  Nothing in this zip touches your keybinds or your saved variables."
        echo
        echo "ALREADY IN THE FULL CLIENT ZIP -- take this one only to update a client you have."
        echo
        echo "CONTENTS"
        printf '  %s\n' "${NAMES[@]}"
    } > "$TMPD/README-addons.txt"

    ( cd "$CLIENT" && zip -r -q -9 "$F" "${LIST[@]}" -x '*/.git/*' '*/.github/*' )
    ( cd "$TMPD"   && zip -q -9 "$F" "README-addons.txt" )

    # Assert, do not assume. A stray Blizzard_* or GM folder in here is exactly the kind of
    # mistake that only shows up as "my UI went weird" three days after the hand-off.
    if unzip -Z1 "$F" | grep -qE '^Interface/AddOns/Blizzard_'; then
        echo "package-extras.sh: stock Blizzard_* leaked into the addon pack" >&2; exit 1
    fi
    for g in "${GM_ADDONS[@]}"; do
        if unzip -Z1 "$F" | grep -qE "^Interface/AddOns/$g/"; then
            echo "package-extras.sh: GM tool '$g' leaked into the general addon pack" >&2; exit 1
        fi
    done

    SHA="$(seal "$F")"
    record addons addons 30 "Addon pack (${#NAMES[@]} addons)" "$F" "$SHA" \
"The full addon set this realm plays with, pinned by commit so we are all on the same build:
DragonUI, DBM (all instance modules), WeakAuras, Questie, Skada, Auctionator, AdiBags,
GatherMate, OmniCC, Talented and the rest -- $( printf '%s' "${#NAMES[@]}" ) folders.

Stock Blizzard_* UI is excluded on purpose: every client already has it, and unpacking an
older copy over it is a good way to break the default interface. The GM tools are excluded
too and ship separately.

Unzips over your client root, so Interface/AddOns/ lands where it belongs. Remember to tick
\"Load out of date AddOns\" at character select -- these are 3.3.5a forks and most report an
older interface number." \
"Anyone who already has a client and wants our UI, or wants to match the version everyone else is running. Already inside the full client zip." \
"Unzip over the folder containing Wow.exe." "$STAMP" \
        "Interface/AddOns/*" "README-addons.txt"
    ls -l "$F" | awk '{printf "   %s bytes  %s\n", $5, $NF}'
    echo "   ${#NAMES[@]} addon folders"
fi

# ---------------------------------------------------------------------------------------- #
# 3. gm-addons -- AzerothAdmin + ItemBrowser, useless below gmlevel 2
# ---------------------------------------------------------------------------------------- #
if in_scope gm-addons; then
    echo "== gm-addons"
    LIST=(); NAMES=()
    for n in "${GM_ADDONS[@]}"; do
        [[ -d "$CLIENT/Interface/AddOns/$n" ]] \
          || { echo "package-extras.sh: missing GM addon $n -- run scripts/client-addons.sh" >&2; exit 1; }
        LIST+=("Interface/AddOns/$n"); NAMES+=("$n")
    done

    F="$OUT/gm-addons-$STAMP.zip"; rm -f "$F"
    cat > "$TMPD/README-gm-addons.txt" <<EOF
GM tools -- AzerothAdmin + ItemBrowser
built $NOW   realmlist $REALM

READ THIS FIRST: THESE NEED A GM ACCOUNT
  Neither addon does any permission checking of its own. They compose a dot-command and send
  it; the SERVER decides. On a normal account every button is drawn, clickable, and does
  absolutely nothing -- which reads as "the addon is broken" when it is in fact "you are not
  a GM". There is no point installing these without the gmlevel below.

  gmlevel 1  Ticket tab
  gmlevel 2  Char / NPC / GameObject / Teleport / Misc -- .gm, .additem, .modify speed,
             .character level, .learn all, .npc add, .gobject add, .tele add
  gmlevel 3  Server tab -- .reload, .server restart, .server shutdown, .account set gmlevel

  Worse than silent: a command your account may not use is SWALLOWED rather than spoken,
  because this realm leaves AllowPlayerCommands at 1 and the core answers "no such command"
  instead of falling through to chat. So a refusal looks like a dead button, not a denial.
  (The alternative setting would broadcast your ".gm on" clicks to everyone in /say. We keep
  it as it is.)

WHAT THEY ARE
  AzerothAdmin  a GM control panel. Open with /aa or /azerothadmin, or the minimap button.
                Shift-clicking either reloads the UI on purpose. Escape closes the frames.
                It bundles its own Ace3 in Libraries/, so it needs nothing else installed.
  ItemBrowser   an offline, searchable copy of this realm's item database, generated from
                the live world DB -- browse and look up item IDs without spamming .lookup.

INSTALL
  1. Fully quit WoW.
  2. Unzip OVER YOUR CLIENT FOLDER (the one with Wow.exe). The Interface/AddOns/ path is
     already in the zip. The folder names are load-bearing -- AzerothAdmin hardcodes four
     Interface\\AddOns\\AzerothAdmin paths in its Lua -- so do not rename them.
  3. Character select -> AddOns -> tick "Load out of date AddOns" -> enable -> Okay.

ONE PRACTICAL WARNING
  The search popups scrape .lookup output out of the chat frame, and this realm leaves
  Command.LookupMaxResults at 0 = unlimited. A two-letter item search dumps thousands of
  lines into your chat window. Search with a real substring.
EOF
    ( cd "$CLIENT" && zip -r -q -9 "$F" "${LIST[@]}" -x '*/.git/*' '*/.github/*' )
    ( cd "$TMPD"   && zip -q -9 "$F" "README-gm-addons.txt" )
    SHA="$(seal "$F")"
    record gm-addons addons 40 "GM tools (AzerothAdmin + ItemBrowser)" "$F" "$SHA" \
"AzerothAdmin -- a GM control panel opened with /aa or the minimap button -- plus ItemBrowser,
an offline searchable copy of this realm's item database generated from the live world DB.

Neither addon checks permissions itself: it sends the dot-command and lets the server refuse.
On an ordinary account every button is drawn and clickable and does nothing at all, because
this realm answers a forbidden command with \"no such command\" rather than speaking it in
chat. You need gmlevel 2 for the Char/NPC/GO/Tele tabs and gmlevel 3 for the Server tab.

Unzips over the client root. The folder names are load-bearing -- AzerothAdmin hardcodes its
own path in four places -- so do not rename them." \
"Only the realm admin, and only with gmlevel 2 or higher. On a normal account these do nothing and just look broken." \
"Unzip over the folder containing Wow.exe. Requires gmlevel 2+." "$STAMP" \
        "Interface/AddOns/AzerothAdmin/*" "Interface/AddOns/ItemBrowser/*" "README-gm-addons.txt"
    ls -l "$F" | awk '{printf "   %s bytes  %s\n", $5, $NF}'
fi

# ---------------------------------------------------------------------------------------- #
# 4. realmlist -- three lines of text, and the most common reason a friend cannot connect
# ---------------------------------------------------------------------------------------- #
if in_scope realmlist; then
    echo "== realmlist -> $REALM"
    # Shipped as an actual realmlist.wtf rather than a copy-paste snippet on purpose: Windows
    # hides known extensions, so a friend who "creates realmlist.wtf in Notepad" creates
    # realmlist.wtf.txt, sees the file they expect, and cannot connect. Handing them the file
    # removes the whole failure mode.
    LOCALES=()
    for d in "$CLIENT"/Data/[a-z][a-z][A-Z][A-Z]; do
        [[ -d "$d" ]] && LOCALES+=("$(basename "$d")")
    done
    [[ ${#LOCALES[@]} -gt 0 ]] || LOCALES=(enUS)   # a client with no locale dir is broken anyway

    PAY="$TMPD/realmlist"; rm -rf "$PAY"
    RLPATHS=()
    for loc in "${LOCALES[@]}"; do
        mkdir -p "$PAY/Data/$loc"
        printf 'set realmlist %s\n' "$REALM" > "$PAY/Data/$loc/realmlist.wtf"
        RLPATHS+=("Data/$loc/realmlist.wtf")
    done

    cat > "$PAY/README-realmlist.txt" <<EOF
How to point your client at this server
built $NOW

THE ADDRESS
  $REALM

TWO FILES HAVE TO AGREE
  1. <WoW>/Data/$( printf '%s' "${LOCALES[0]}" )/realmlist.wtf   -- one line:

         set realmlist $REALM

     This zip contains that file already, for every locale folder this realm ships. Unzip it
     over your client folder (the one with Wow.exe) and it is done.

  2. <WoW>/WTF/Config.wtf  -- the client writes this one itself, so it is NOT in the zip.
     Open it in a text editor and make the realmList line read:

         SET realmList "$REALM"

     If the two files disagree you get the classic "I changed realmlist.wtf and it still
     connects to the old server". Fix both, or delete the line from Config.wtf and let
     realmlist.wtf seed it.

WHY WE SHIP THE FILE INSTEAD OF ASKING YOU TO MAKE IT
  Windows hides known file extensions. Creating "realmlist.wtf" in Notepad actually creates
  realmlist.wtf.txt, which looks correct in Explorer and does nothing at all.

THINGS THAT WILL WASTE YOUR EVENING
  * Do not run Launcher.exe. It rewrites realmlist.wtf from Blizzard's patchlist server and
    silently undoes this. Run Wow.exe directly.
  * Never use "localhost" -- the 3.3.5a resolver does not handle it reliably. An IP or a real
    hostname only.
  * If you have more than one Data/<locale>/ folder you have a mixed install; keep the one
    your client actually uses and delete the other.
  * Optional, and worth it: make the file read-only after you set it, so nothing rewrites it.
    Right-click -> Properties -> Read-only. Do NOT make the whole WTF folder read-only -- the
    client stores your settings and keybinds there and will reset them every launch.

STILL STUCK AT "LOGGING IN TO GAME SERVER"?
  That one is on our side, not yours -- the login succeeded. Tell the admin.
EOF

    F="$OUT/realmlist-$STAMP.zip"; rm -f "$F"
    ( cd "$PAY" && zip -r -q -9 "$F" . )
    SHA="$(seal "$F")"
    record realmlist config 50 "Realmlist + connection instructions" "$F" "$SHA" \
"A ready-made realmlist.wtf pointing at $REALM, for every locale folder this client ships,
plus a short page on the two files that have to agree (Data/<locale>/realmlist.wtf and
WTF/Config.wtf) and the handful of things that reliably waste an evening -- running
Launcher.exe, which rewrites the file; using \"localhost\", which the 3.3.5a resolver does not
handle; and Windows' hidden file extensions turning your new realmlist.wtf into
realmlist.wtf.txt.

It ships as an actual file rather than a snippet to copy precisely because of that last one." \
"Anyone whose client points somewhere else, and anyone who cannot get past the login screen. Tiny -- when in doubt, take it." \
"Unzip over the folder containing Wow.exe, then fix the realmList line in WTF/Config.wtf." "$STAMP" \
        "${RLPATHS[@]}" "README-realmlist.txt"
    ls -l "$F" | awk '{printf "   %s bytes  %s\n", $5, $NF}'
fi

# ---------------------------------------------------------------------------------------- #
# 5. the full client zip -- built by package-client.sh, adopted here (see header)
# ---------------------------------------------------------------------------------------- #
if [[ -z "$ONLY" ]] || in_scope client-full; then
    echo "== client-full"
    CZ=""
    if [[ "$CLIENT_ZIP" == "none" ]]; then
        echo "   skipped (--client-zip none)"
    elif [[ -n "$CLIENT_ZIP" ]]; then
        [[ -f "$CLIENT_ZIP" ]] || { echo "package-extras.sh: no such file: $CLIENT_ZIP" >&2; exit 1; }
        CZ="$CLIENT_ZIP"
    else
        # Newest wow335-*.zip that has its sha256 sidecar. No sidecar = package-client.sh has
        # not finished, and adopting a growing file would publish a truncated 17 GB download.
        # By mtime, not by name: the optional --tag sits between the prefix and the stamp, so
        # wow335-release-<older> sorts after wow335-<newer> and a name sort picks the wrong one.
        while read -r c; do
            [[ -n "$c" && -f "$c.sha256" ]] && { CZ="$c"; break; }
        done < <(find "$OUT" -maxdepth 1 -name 'wow335-*.zip' -printf '%T@\t%p\n' 2>/dev/null \
                 | sort -rn | cut -f2-)
        [[ -n "$CZ" ]] || echo "   none ready in $OUT (no wow335-*.zip with a .sha256 beside it)"
    fi

    if [[ -n "$CZ" ]]; then
        if [[ -f "$CZ.sha256" ]]; then
            SHA="$(cut -d' ' -f1 < "$CZ.sha256")"
        else
            echo "   no sidecar -- hashing (this takes a while for a 17 GB file)"
            SHA="$(seal "$CZ")"
        fi
        BASE="$(basename "$CZ")"
        CSTAMP="$(sed -nE 's/^wow335-(.*-)?([0-9]{8}-[0-9]{4})\.zip$/\2/p' <<< "$BASE")"

        # package-client.sh bakes a realmlist into the client it ships and records it in
        # PACK-MANIFEST.txt. If that disagrees with the address we are about to publish, every
        # friend who takes the big download lands on the wrong server and the symptom -- a
        # login screen that never connects -- says nothing about why. Reading one file out of
        # a 17 GB zip costs nothing (unzip seeks the central directory), so always check.
        CZ_REALM="$(unzip -p "$CZ" 'ChromieCraft_3.3.5a/PACK-MANIFEST.txt' 2>/dev/null \
                    | sed -nE 's/^realmlist:[[:space:]]*(.+)$/\1/p' | head -1)"
        if [[ -n "$CZ_REALM" && "$CZ_REALM" != "$REALM" ]]; then
            echo "   WARNING: $BASE was built for realmlist '$CZ_REALM', but this manifest
            says '$REALM'. Friends who take the full client will connect nowhere.
            Recut it:  scripts/package-client.sh --realmlist $REALM" >&2
        elif [[ -z "$CZ_REALM" ]]; then
            echo "   NOTE: no PACK-MANIFEST.txt in $BASE -- cannot confirm its realmlist." >&2
        fi
        # Not under $OUT means the webapp cannot serve it from beside the manifest. Say so
        # loudly rather than writing an entry that 404s.
        [[ "$(cd "$(dirname "$CZ")" && pwd)" == "$(cd "$OUT" && pwd)" ]] \
          || echo "   WARNING: $CZ is not in $OUT -- copy it there before publishing" >&2
        record client-full client 10 "Full WoW 3.3.5a client" "$CZ" "$SHA" \
"The entire game, ready to run: a clean 3.3.5a client with the realmlist already pointed at
$REALM, the addon pack installed, the Death Knight spell patch in place, and all per-machine
state (saved accounts, keybinds, caches, logs) stripped out.

Unzip it anywhere you like and run Wow.exe. Nothing to install, no launcher, no patching.
It is large -- start it before you go to bed.

Everything else on this page is already inside this zip. The separate downloads exist so you
never have to pull this twice." \
"Anyone who does not already have a working 3.3.5a client. If you have one, take the smaller pieces instead." \
"Unzip anywhere, run Wow.exe." "$CSTAMP" \
            "ChromieCraft_3.3.5a/**" "ChromieCraft_3.3.5a/PACK-MANIFEST.txt"
        ls -l "$CZ" | awk '{printf "   %s bytes  %s\n", $5, $NF}'
    fi
fi

# ---------------------------------------------------------------------------------------- #
# 6. merge into downloads.json
# ---------------------------------------------------------------------------------------- #
echo "== manifest -> $MANIFEST"
[[ -f "$MANIFEST" ]] || printf '{"schema":1,"artifacts":[]}\n' > "$MANIFEST"

# Carry over every entry we did not just rebuild, then append the new ones.
jq --slurpfile delta "$DELTA" --arg realmlist "$REALM" --arg now "$NOW" \
   --arg repo "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)" '
    ($delta[0] | map(.id)) as $fresh
    | { schema: 1,
        generated: $now,
        realmlist: $realmlist,
        repo: $repo,
        artifacts: (((.artifacts // []) | map(select(.id as $i | ($fresh | index($i)) | not)))
                    + $delta[0]) }
' "$MANIFEST" > "$MANIFEST.new"

# Drop entries whose file has gone. A manifest is a promise that the file is there; a broken
# link on the download page reads to a friend as "the server is down".
KEEP="$TMPD/keep.json"; echo '[]' > "$KEEP"
DROPPED=0
while read -r id fn; do
    if [[ -f "$OUT/$fn" ]]; then
        jq --arg id "$id" '. + [$id]' "$KEEP" > "$KEEP.new" && mv "$KEEP.new" "$KEEP"
    else
        echo "   dropping '$id': $fn is no longer in $OUT" >&2
        DROPPED=$((DROPPED+1))
    fi
done < <(jq -r '.artifacts[] | "\(.id) \(.filename)"' "$MANIFEST.new")

jq --slurpfile keep "$KEEP" \
   '.artifacts |= (map(select(.id as $i | $keep[0] | index($i))) | sort_by(.order))' \
   "$MANIFEST.new" > "$MANIFEST.tmp" && mv "$MANIFEST.tmp" "$MANIFEST.new"

COUNT="$(jq '.artifacts | length' "$MANIFEST.new")"
[[ "$COUNT" -gt 0 ]] || { echo "package-extras.sh: refusing to write an empty manifest" >&2; exit 1; }
mv "$MANIFEST.new" "$MANIFEST"

echo
# awk, not column(1): column is util-linux on some distros and bsdmainutils on others, and a
# missing formatter must not fail a run whose manifest is already written.
jq -r '.artifacts[] | "\(.id)\t\(.size_human)\t\(.filename)"' "$MANIFEST" \
  | awk -F'\t' '{printf "  %-12s %10s  %s\n", $1, $2, $3}'
echo
echo "  $COUNT artefacts, realmlist $REALM"
[[ "$DROPPED" -eq 0 ]] || echo "  $DROPPED stale entr$( [[ $DROPPED -eq 1 ]] && echo y || echo ies) dropped"

if [[ "$REALM_MOVED" -eq 1 ]]; then
    echo
    echo "  WARNING: the realm moved ($PREV_REALM -> $REALM) but the realmlist artefact was not
           rebuilt, so the realmlist.wtf on the download page still points at the old address.
           Fix:  scripts/package-extras.sh --only realmlist --realmlist $REALM" >&2
fi

# Files from older stamps are left on disk on purpose -- you may still be seeding one, or
# want to diff it. Just say which ones the manifest no longer points at.
mapfile -t LIVE < <(jq -r '.artifacts[].filename' "$MANIFEST")
ORPHANS=()
for f in "$OUT"/dk-patch-*.zip "$OUT"/addons-*.zip "$OUT"/gm-addons-*.zip "$OUT"/realmlist-*.zip "$OUT"/wow335-*.zip; do
    [[ -f "$f" ]] || continue
    b="$(basename "$f")"
    [[ " ${LIVE[*]} " == *" $b "* ]] || ORPHANS+=("$b")
done
if [[ ${#ORPHANS[@]} -gt 0 ]]; then
    echo
    echo "  superseded, not deleted (${#ORPHANS[@]}):"
    printf '    %s\n' "${ORPHANS[@]}"
fi

echo
echo "Publish:  rsync -avP $OUT/ wow:/srv/wow/dist/"
echo "The webapp reads $(basename "$MANIFEST") from that directory and lists artefacts by id."
