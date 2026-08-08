#!/usr/bin/env bash
# play.sh -- launch the local 3.3.5a client against the local server.
#
# Uses a DEDICATED wine prefix under the game directory rather than ~/.wine, so nothing here can
# disturb another wine app and the whole thing is deletable in one rm.
#
# usage:  scripts/play.sh [--realmlist HOST] [--reset-prefix] [--windowed]

set -euo pipefail

GAME="/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a"
PREFIX="/home/ali/games/wow-3.3.5a/prefix"
REALM=""
WINDOWED=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --realmlist)    REALM="$2"; shift 2;;
        --reset-prefix) rm -rf "$PREFIX"; echo "prefix removed"; shift;;
        --windowed)     WINDOWED=1; shift;;
        -h|--help)      sed -n '2,8p' "$0"; exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

[[ -f "$GAME/Wow.exe" ]] || { echo "play.sh: no Wow.exe under $GAME" >&2; exit 1; }
command -v wine >/dev/null || { echo "play.sh: wine not installed" >&2; exit 1; }

if [[ -n "$REALM" ]]; then
    for d in "$GAME"/Data/[a-z][a-z][A-Z][A-Z]; do
        [[ -d "$d" ]] && printf 'set realmlist %s\n' "$REALM" > "$d/realmlist.wtf"
    done
    echo "realmlist -> $REALM"
fi

export WINEPREFIX="$PREFIX"
export WINEDEBUG="${WINEDEBUG:--all}"
# XWayland, not the native wayland driver. A 2010 D3D9 game predates everything the wayland
# driver assumes; forcing X11 avoids blank-window and cursor-confinement bugs that look like the
# game hanging. DISPLAY is already :0 on this session.
export DISPLAY="${DISPLAY:-:0}"
unset WAYLAND_DISPLAY

if [[ ! -d "$PREFIX" ]]; then
    echo "== creating wine prefix (first run, takes a minute)"
    WINEDLLOVERRIDES="mscoree=d;mshtml=d" wineboot -u >/dev/null 2>&1 || true
    wineserver -w || true
fi

# Windowed is friendlier on a tiling compositor -- fullscreen D3D9 under Hyprland tends to grab
# the whole output and fight the layout. Config.wtf is the client's own settings file.
CFG="$GAME/WTF/Config.wtf"
mkdir -p "$GAME/WTF"; touch "$CFG"
set_cfg() {
    if grep -qi "^SET $1 " "$CFG"; then sed -i "s|^SET $1 .*|SET $1 \"$2\"|I" "$CFG"
    else printf 'SET %s "%s"\n' "$1" "$2" >> "$CFG"; fi
}
if [[ $WINDOWED -eq 1 ]]; then
    set_cfg gxWindow 1
    set_cfg gxMaximize 1
fi
set_cfg gxApi d3d9

echo "== launching  (prefix: $PREFIX)"
cd "$GAME"
exec wine Wow.exe
