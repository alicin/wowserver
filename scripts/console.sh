#!/usr/bin/env bash
# console.sh -- run worldserver console commands non-interactively.
#
# AzerothCore ships no `worldserver-cli`; the console is the daemon's own stdin. That makes
# scripted administration awkward in Docker:
#   * `docker compose exec` starts a NEW process and never reaches the console.
#   * `echo cmd | docker attach` writes the command and then closes stdin, which the console
#     reads as EOF and treats as "shut down". You get one command and lose the server.
# The fix is a FIFO held open by a second writer for the life of the batch, so each command is
# an independent open/write/close while the reader never sees EOF.
#
# SOAP (scripts/soap-cmd.sh) is the better tool for routine commands, but it needs a GM account
# to authenticate -- so this is what bootstraps the first one.
#
# usage:  scripts/console.sh "account create foo bar" "account set gmlevel foo 3 -1"
#         scripts/console.sh --file cmds.txt

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO/deploy"

CID="$(docker compose ps -q worldserver)"
[[ -n "$CID" ]] || { echo "console.sh: worldserver is not running" >&2; exit 1; }
[[ "$(docker inspect -f '{{.State.Running}}' "$CID")" == "true" ]] \
    || { echo "console.sh: worldserver container is not running" >&2; exit 1; }

CMDS=()
if [[ "${1:-}" == "--file" ]]; then
    [[ -f "${2:-}" ]] || { echo "console.sh: no such file: ${2:-}" >&2; exit 1; }
    mapfile -t CMDS < <(grep -vE '^\s*(#|$)' "$2")
else
    CMDS=("$@")
fi
[[ ${#CMDS[@]} -gt 0 ]] || { echo "usage: console.sh \"cmd\" [\"cmd\"...]" >&2; exit 1; }

FIFO="$(mktemp -u /tmp/ws-console.XXXXXX)"
OUT="$(mktemp /tmp/ws-out.XXXXXX)"
mkfifo "$FIFO"

HOLDER=""; ATTACH=""
cleanup() {
    # Kill by recorded PID only. NEVER `pkill -f 'docker attach'` -- that pattern also matches
    # the shell running this script, and it will take your own session down with it.
    [[ -n "$HOLDER" ]] && kill "$HOLDER" 2>/dev/null || true
    [[ -n "$ATTACH" ]] && kill "$ATTACH" 2>/dev/null || true
    rm -f "$FIFO"
}
trap cleanup EXIT

# Writer that outlives the batch, so the console never sees EOF.
sleep 120 > "$FIFO" &
HOLDER=$!
# --sig-proxy=false so a Ctrl-C here cannot forward SIGINT into the daemon.
docker attach --sig-proxy=false "$CID" < "$FIFO" > "$OUT" 2>&1 &
ATTACH=$!
sleep 2

for c in "${CMDS[@]}"; do
    printf '  > %s\n' "$c"
    printf '%s\n' "$c" > "$FIFO"
    sleep 2
done
sleep 2

cleanup; trap - EXIT
echo "--- console output ---"
sed 's/\x1b\[[0-9;]*m//g' "$OUT" | grep -vE '^\s*$' || true
rm -f "$OUT"
