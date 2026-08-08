#!/usr/bin/env bash
#
# scripts/restore.sh -- the inverse of backup.sh. DESTROYS live data. docs/hosting.md 7.4.
#
#   usage: restore.sh [options] <dump> [<dump> ...]
#
# A dump is either a local path or an rclone object (anything matching remote:path, e.g.
# gdrive:backups/wowserver/acore_characters-20260807T051700Z.sql.zst), and either .sql.zst
# or plain .sql. The target schema is read off the file name -- acore_characters-<stamp>.sql.zst
# restores into acore_characters -- because that is how backup.sh names them. Override with
# --target when you want the safe thing instead:
#
#     scripts/restore.sh --target scratch_chars --no-stop acore_characters-<stamp>.sql.zst
#
# TEST THE RESTORE PATH ONCE, ON PURPOSE, BEFORE YOU NEED IT. Restore last night's
# acore_characters into a scratch schema and confirm the row count in `characters` looks
# right. An untested backup is a hypothesis.  hosting.md 7.4
#
# acore_world is REFUSED. It is not in the backup set and it must not be in the restore
# set: it is rebuilt from source on the next boot, because AzerothCore's own updater
# populates and migrates it from data/sql/** plus every module's SQL. Restoring a stale
# world dump on top of a newer module pin is how you get a half-migrated world DB.
#
set -euo pipefail

usage() {
    cat <<'EOF'
usage: restore.sh [options] <dump> [<dump> ...]

  --target DB     restore every dump into DB instead of the name in the file. Only legal
                  with a single dump. Use this for the scratch-schema rehearsal.
  --no-stop       do not stop worldserver/authserver first. ONLY safe for a scratch target.
  --no-start      do not `docker compose up -d` at the end.
  --shutdown-delay N   seconds of in-game countdown before the stop (default 60; 0 = no
                  SOAP announce, just `docker compose stop`)
  --yes           skip the confirmation prompt. Do not put this in a cron line.
  -h, --help

Environment:
  DEPLOY   compose project dir (default: <repo>/deploy)
  WORKDIR  where remote dumps are fetched to (default: a mktemp -d, removed on exit)

The mysql root password comes from deploy/.env, via the same 0600 option file backup.sh
writes (deploy/mysql-backup.cnf -> /etc/mysql/backup.cnf in the container). If it is
missing -- fresh VPS, restoring onto a rebuilt box -- this script regenerates it.
EOF
}

TARGET=
DO_STOP=1
DO_START=1
SHUTDOWN_DELAY=60
ASSUME_YES=0
DUMPS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)          TARGET=${2:?--target needs a schema name}; shift ;;
        --no-stop)         DO_STOP=0 ;;
        --no-start)        DO_START=0 ;;
        --shutdown-delay)  SHUTDOWN_DELAY=${2:?--shutdown-delay needs a number}; shift ;;
        --yes | -y)        ASSUME_YES=1 ;;
        -h | --help)       usage; exit 0 ;;
        -*)                echo "restore.sh: unknown option '$1'" >&2; usage >&2; exit 2 ;;
        *)                 DUMPS+=("$1") ;;
    esac
    shift
done

[[ ${#DUMPS[@]} -gt 0 ]] || { usage >&2; exit 2; }
if [[ -n $TARGET && ${#DUMPS[@]} -gt 1 ]]; then
    echo "restore.sh: --target takes exactly one dump, got ${#DUMPS[@]}." >&2
    exit 2
fi
[[ $SHUTDOWN_DELAY =~ ^[0-9]+$ ]] || { echo "restore.sh: --shutdown-delay must be a number." >&2; exit 2; }

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
DEPLOY=${DEPLOY:-$REPO_ROOT/deploy}
export DEPLOY   # scripts/soap-cmd.sh is invoked below and must agree about where .env is
cd "$DEPLOY" || { echo "restore.sh: no compose project directory at $DEPLOY." >&2; exit 1; }

[[ -f $DEPLOY/.env ]] || { echo "restore.sh: $DEPLOY/.env not found." >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. "$DEPLOY/.env"
set +a
: "${MYSQL_ROOT_PASSWORD:?not set in $DEPLOY/.env}"

command -v docker >/dev/null || { echo "restore.sh: docker not on PATH." >&2; exit 1; }
command -v zstd >/dev/null   || { echo "restore.sh: zstd not on PATH." >&2; exit 1; }

CLEANUP_DIR=
if [[ -n ${WORKDIR:-} ]]; then
    mkdir -p "$WORKDIR"
else
    WORKDIR=$(mktemp -d)
    CLEANUP_DIR=$WORKDIR
fi
cleanup() { if [[ -n $CLEANUP_DIR ]]; then rm -rf -- "$CLEANUP_DIR"; fi; }
trap cleanup EXIT

log() { printf '%s restore.sh: %s\n' "$(date -Is)" "$*"; }

# --------------------------------------------------- resolve dumps and target schemas ---
# Same 0600 credentials file the backup script writes. Regenerate it if it is missing --
# on a rebuilt box it will be, and every command below would fail "access denied".
# Rewrite in place with `>`: it is bind-mounted as a FILE, and a bind-mounted file follows
# the inode, so `mv`-ing a temp file over it leaves the container reading the old one.
umask 077
printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" >"$DEPLOY/mysql-backup.cnf"

declare -a FILES=() SCHEMAS=()

for spec in "${DUMPS[@]}"; do
    file=$spec
    # rclone object? "remote:path" -- a colon whose left side is a bare remote name.
    remote=${spec%%:*}
    if [[ $spec == *:* && $spec != /* && $remote != "$spec" && $remote != */* && -n $remote ]]; then
        command -v rclone >/dev/null || { echo "restore.sh: '$spec' looks like an rclone path but rclone is not installed." >&2; exit 1; }
        log "fetching $spec"
        rclone copy "$spec" "$WORKDIR"
        file="$WORKDIR/$(basename -- "$spec")"
    fi
    [[ -f $file ]] || { echo "restore.sh: no such dump: $file" >&2; exit 1; }

    base=$(basename -- "$file")
    if [[ -n $TARGET ]]; then
        schema=$TARGET
    else
        # acore_characters-20260807T051700Z.sql.zst -> acore_characters
        schema=${base%%-*}
        if [[ -z $schema || $schema == "$base" ]]; then
            echo "restore.sh: cannot read a schema name out of '$base'." >&2
            echo "            backup.sh names dumps <schema>-<stamp>.sql.zst; pass --target." >&2
            exit 1
        fi
    fi

    if [[ $schema == acore_world ]]; then
        echo "restore.sh: refusing to restore acore_world." >&2
        echo "            It is not backed up and it does not need to be: AzerothCore" >&2
        echo "            repopulates and migrates it from data/sql/** plus every module's" >&2
        echo "            SQL on the next boot. Just \`docker compose up -d\`." >&2
        exit 1
    fi

    FILES+=("$file")
    SCHEMAS+=("$schema")
done

# ---------------------------------------------------------------------------- confirm ---
echo
echo "  RESTORE PLAN"
for i in "${!FILES[@]}"; do
    printf '    %-22s <-  %s\n' "${SCHEMAS[$i]}" "${FILES[$i]}"
done
echo
echo "  Each target schema is DROPPED and recreated first, so that stale rows cannot"
echo "  survive the import. Everything currently in it is gone."
if [[ $DO_STOP -eq 1 ]]; then
    echo "  worldserver and authserver will be stopped first"
    if [[ $SHUTDOWN_DELAY -gt 0 ]]; then
        echo "  (after a ${SHUTDOWN_DELAY}s in-game countdown over SOAP)"
    fi
fi
echo

if [[ $ASSUME_YES -ne 1 ]]; then
    reply=
    # `|| true`: read returns 1 at EOF, which under `set -e` would abort silently. A
    # non-interactive caller with no --yes should get the word "aborted", not nothing.
    read -r -p "Type RESTORE to proceed: " reply || true
    [[ $reply == RESTORE ]] || { echo "aborted."; exit 1; }
fi

# ------------------------------------------------------------------- stop the servers ---
# Nothing may write while the restore runs.
if [[ $DO_STOP -eq 1 ]]; then
    if [[ $SHUTDOWN_DELAY -gt 0 ]]; then
        if "$SCRIPT_DIR/soap-cmd.sh" "server shutdown $SHUTDOWN_DELAY"; then
            log "countdown running; waiting ${SHUTDOWN_DELAY}s plus a save margin"
            sleep $((SHUTDOWN_DELAY + 20))
        else
            log "SOAP announce failed (server already down?) -- stopping without a countdown"
        fi
    fi
    log "docker compose stop worldserver authserver"
    docker compose stop worldserver authserver
fi

# ------------------------------------------------------------------------- the import ---
# --defaults-extra-file must be the FIRST argument: MySQL parses option-file arguments
# before everything else and documents that they "must be given before other options".
# utf8mb4 / utf8mb4_general_ci matches what AzerothCore's own schema creation uses.
for i in "${!FILES[@]}"; do
    file=${FILES[$i]}
    schema=${SCHEMAS[$i]}

    log "drop + create $schema"
    docker compose exec -T mysql \
        mysql --defaults-extra-file=/etc/mysql/backup.cnf \
        -e "DROP DATABASE IF EXISTS \`$schema\`; CREATE DATABASE \`$schema\`
            DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"

    log "importing $(basename -- "$file") -> $schema"
    case "$file" in
        *.zst)
            zstd -dc -- "$file" |
                docker compose exec -T mysql \
                    mysql --defaults-extra-file=/etc/mysql/backup.cnf "$schema"
            ;;
        *)
            docker compose exec -T mysql \
                mysql --defaults-extra-file=/etc/mysql/backup.cnf "$schema" <"$file"
            ;;
    esac

    rows=$(docker compose exec -T mysql \
        mysql --defaults-extra-file=/etc/mysql/backup.cnf -N -B \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$schema';" | tr -d '\r')
    log "  $schema now has ${rows} tables"
done

# --------------------------------------------------- the two checks after acore_auth ----
# A restore from before a VPS rebuild hands out a dead address and looks like a total
# outage: friends authenticate fine, see the realm, click it, and hang forever at
# "Logging in to game server" because the realmlist row is dutifully pointing them at
# somewhere they cannot reach.  hosting.md 5.2, 7.4
for schema in "${SCHEMAS[@]}"; do
    [[ $schema == acore_auth ]] || continue
    echo
    echo "  acore_auth was restored. CHECK THESE TWO BEFORE ANYONE LOGS IN:"
    echo "    1. realmlist.address is the address clients can reach NOW (tailscale ip -4)"
    echo "    2. realmlist.id still matches RealmID in conf/worldserver.conf"
    echo
    docker compose exec -T mysql \
        mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
        -e "SELECT id, name, address, localAddress, port, gamebuild, flag FROM realmlist;" || true
    echo
    echo "  Fix with (hosting.md 5.2):"
    echo "    docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \\"
    echo "      -e \"UPDATE realmlist SET address='100.x.y.z', port=8085, gamebuild=12340 WHERE id=1;\""
    echo "  Leave localAddress and localSubnetMask at 127.0.0.1 / 255.255.255.0."
    echo
    # Accounts are stamped with account.expansion at creation time. This realm runs
    # Expansion = 2 in all three phases (gating is the level cap only), so anything
    # below 2 in a restored auth DB is a login that silently cannot enter Outland or
    # Northrend and cannot roll a Blood Elf.  server-config.md 1
    echo "  Accounts not at expansion = 2 (should be zero rows):"
    docker compose exec -T mysql \
        mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
        -e "SELECT id, username, expansion FROM account WHERE expansion <> 2;" || true
    echo
done

# ------------------------------------------------------------------------------ start ---
if [[ $DO_START -eq 1 ]]; then
    log "docker compose up -d"
    docker compose up -d
    log "worldserver rebuilds/updates acore_world on boot; follow it with:"
    log "  docker compose logs -f worldserver"
else
    log "not starting (--no-start). Bring it back with: cd $DEPLOY && docker compose up -d"
fi

log "done"
