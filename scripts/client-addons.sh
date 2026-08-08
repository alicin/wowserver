#!/usr/bin/env bash
# client-addons.sh -- install the pinned addon pack into a 3.3.5a client.
#
# Idempotent and destructive per-addon: every managed folder is removed and re-extracted, so
# the result depends only on client/addons.txt and never on what was there before. Anything
# NOT in the manifest is left alone, so hand-installed addons survive.
#
# usage:  scripts/client-addons.sh [/path/to/WoW]
#         (default: /home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="${1:-/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a}"
MANIFEST="$REPO/client/addons.txt"
ADDONS="$CLIENT/Interface/AddOns"

[[ -f "$MANIFEST" ]] || { echo "no manifest: $MANIFEST" >&2; exit 1; }
[[ -d "$CLIENT" ]]   || { echo "no client at: $CLIENT" >&2; exit 1; }
[[ -f "$CLIENT/Wow.exe" ]] || { echo "$CLIENT has no Wow.exe -- wrong directory?" >&2; exit 1; }
mkdir -p "$ADDONS"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
installed=0; folders=0

# Directories that live at a repo root but are not addons.
is_junk() { case "${1,,}" in .github|.git|licenses|docs|spec|tools|screenshots|images|.vscode) return 0;; esac; return 1; }

while read -r repo ref mode sha; do
    [[ -z "${repo:-}" || "$repo" == \#* ]] && continue
    name="${repo##*/}"
    echo "== $repo @ ${sha:0:10}"

    # codeload tarballs work for any SHA and need no git or auth.
    if ! curl -fsSL "https://codeload.github.com/$repo/tar.gz/$sha" -o "$TMP/$name.tgz"; then
        echo "   !! download failed, skipping" >&2; continue
    fi
    src="$TMP/$name"; mkdir -p "$src"
    tar -xzf "$TMP/$name.tgz" -C "$src" --strip-components=1

    case "$mode" in
      root:*)
        # The repo root is the addon. The FOLDER NAME IS LOAD-BEARING: WoW matches
        # AddOns/<Name>/<Name>.toc, and Questie in particular fails silently under any name
        # other than Questie-335.
        dest="${mode#root:}"
        rm -rf "${ADDONS:?}/$dest"
        mkdir -p "$ADDONS/$dest"
        # Copy contents, dropping repo furniture that would confuse the addon scanner.
        ( cd "$src" && tar -cf - --exclude=.git --exclude=.github --exclude=docs --exclude=spec . ) \
            | ( cd "$ADDONS/$dest" && tar -xf - )
        echo "   -> $dest"
        folders=$((folders+1))
        ;;
      dirs)
        found=0
        for d in "$src"/*/; do
            [[ -d "$d" ]] || continue
            b="$(basename "$d")"
            is_junk "$b" && continue
            # An addon folder is one that contains a .toc. Without this check you happily
            # install Libs/ and Assets/ as top-level addons and WoW lists them as broken.
            compgen -G "$d/*.toc" > /dev/null || continue
            rm -rf "${ADDONS:?}/$b"
            cp -a "$d" "$ADDONS/$b"
            echo "   -> $b"
            folders=$((folders+1)); found=$((found+1))
        done
        [[ $found -gt 0 ]] || echo "   !! no .toc-bearing directories found" >&2
        ;;
      *) echo "   !! unknown mode '$mode'" >&2; continue;;
    esac
    installed=$((installed+1))
done < "$MANIFEST"

echo
echo "installed $installed repos -> $folders addon folders in $ADDONS"
echo "total AddOns present: $(find "$ADDONS" -maxdepth 1 -mindepth 1 -type d | wc -l)"
