#!/usr/bin/env bash
#
# scripts/backup.sh -- nightly dump of the three databases that are not reproducible.
#
#   usage: backup.sh [--offsite|--no-offsite] [--dry-run]
#
# WHAT IS BACKED UP, AND WHAT IS NOT.  docs/hosting.md 7.3.
#   acore_auth         accounts, account_access, and the realmlist row. Tiny, irreplaceable.
#   acore_characters   the one that actually matters. Also holds every playerbot's Player row.
#   acore_playerbots   bot state. Annoying but not fatal to lose; it is small, so take it.
#   acore_world        NOT BACKED UP. ~4 GB of static content that is byte-reproducible from
#                      the AzerothCore sources and module SQL on any boot. Dumping it nightly
#                      is 4 GB of churn to store something already pinned in build/modules.txt.
#                      Custom SQL lives in sql/ in this repo, not in a world dump.
#
# Cron (hosting.md 7.3), at an hour nobody plays:
#   17 5 * * *  /srv/wow/wowserver/scripts/backup.sh >> /var/log/wow-backup.log 2>&1
# scripts/bootstrap.sh installs exactly that line into /etc/cron.d/wowserver.
#
# CREDENTIALS. Never `-p` on a command line: container processes show up in `ps` on the
# host and in /proc inside the container, and MySQL's own docs call the -p form insecure.
# The root password goes into a 0600 option file, deploy/mysql-backup.cnf, which the mysql
# service bind-mounts at /etc/mysql/backup.cnf. That mount is a REQUIREMENT on the compose
# file -- without it every mysqldump here fails "access denied" and the nightly backup
# silently stops happening. It is present in deploy/docker-compose.yml; do not remove it.
#
# The file is rewritten in place with `>` on every run and NEVER by renaming a temp file
# over it: a bind-mounted *file* follows the inode, so a rename leaves the running mysql
# container reading the old one.
#
set -euo pipefail

usage() {
    cat <<'EOF'
usage: backup.sh [options]

  --offsite       push this run's dumps to $RCLONE_REMOTE (same as BACKUP_OFFSITE=1)
  --no-offsite    skip the offsite push even if BACKUP_OFFSITE=1
  --dry-run       print what would happen; touch nothing
  -h, --help

Tunables. Each may be exported, or set as a plain KEY=value line in deploy/.env -- and
deploy/.env WINS over the environment, deliberately: what the box does should not depend
on whose shell ran the script.

  BACKUP_OFFSITE           0        1 = also `rclone copy` to RCLONE_REMOTE. OPT-IN.
  RCLONE_REMOTE            gdrive:backups/wowserver
  BACKUP_DIR               /srv/wow/backups
  LOCAL_RETENTION_DAYS     14       delete local *.sql.zst older than this
  OFFSITE_RETENTION_DAYS   90       rclone delete --min-age; 0 disables offsite pruning
  VERIFY_DUMPS             1        decompress the tail of each dump and require
                                    mysqldump's "-- Dump completed" trailer
  ZSTD_LEVEL               9
  DEPLOY                   <repo>/deploy
EOF
}

OFFSITE_CLI=
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --offsite)    OFFSITE_CLI=1 ;;
        --no-offsite) OFFSITE_CLI=0 ;;
        --dry-run)    DRY_RUN=1 ;;
        -h | --help)  usage; exit 0 ;;
        *)            echo "backup.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
DEPLOY=${DEPLOY:-$REPO_ROOT/deploy}

# cron runs from $HOME and `docker compose` needs the project directory -- the compose file
# bind-mounts ../conf/... and reads ./.env from here.
cd "$DEPLOY" || {
    echo "backup.sh: no compose project directory at $DEPLOY." >&2
    echo "           hosting.md 7 puts this checkout at /srv/wow/wowserver." >&2
    exit 1
}

if [[ ! -f $DEPLOY/.env ]]; then
    echo "backup.sh: $DEPLOY/.env not found. It is the single source of truth for" >&2
    echo "           MYSQL_ROOT_PASSWORD (bring-up.md 5.1)." >&2
    exit 1
fi

# Source it. Under `set -u` an undefined $MYSQL_ROOT_PASSWORD would abort on first
# expansion -- which is a nightly backup that silently stops happening.
set -a
# shellcheck disable=SC1091
. "$DEPLOY/.env"
set +a
: "${MYSQL_ROOT_PASSWORD:?not set in $DEPLOY/.env}"

BACKUP_OFFSITE=${BACKUP_OFFSITE:-0}
if [[ -n $OFFSITE_CLI ]]; then BACKUP_OFFSITE=$OFFSITE_CLI; fi   # --offsite/--no-offsite wins over .env
RCLONE_REMOTE=${RCLONE_REMOTE:-gdrive:backups/wowserver}
BACKUP_DIR=${BACKUP_DIR:-/srv/wow/backups}
LOCAL_RETENTION_DAYS=${LOCAL_RETENTION_DAYS:-14}
OFFSITE_RETENTION_DAYS=${OFFSITE_RETENTION_DAYS:-90}
VERIFY_DUMPS=${VERIFY_DUMPS:-1}
ZSTD_LEVEL=${ZSTD_LEVEL:-9}

DATABASES=(acore_auth acore_characters acore_playerbots)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

log() { printf '%s backup.sh: %s\n' "$(date -Is)" "$*"; }

if [[ $DRY_RUN -eq 1 ]]; then
    log "DRY RUN"
    log "  deploy         $DEPLOY"
    log "  out            $BACKUP_DIR"
    log "  databases      ${DATABASES[*]}"
    log "  stamp          $STAMP"
    log "  offsite        $BACKUP_OFFSITE -> $RCLONE_REMOTE"
    log "  retention      local ${LOCAL_RETENTION_DAYS}d / offsite ${OFFSITE_RETENTION_DAYS}d"
    exit 0
fi

for tool in docker zstd; do
    command -v "$tool" >/dev/null || { echo "backup.sh: '$tool' not on PATH. Run scripts/bootstrap.sh." >&2; exit 1; }
done

# ------------------------------------------------------- the 0600 credentials file -----
# Quoting the password is not decoration: inside a MySQL option file '#' starts a comment
# EVEN MID-LINE, so an unquoted password=hunter#2 silently becomes "hunter" and every
# command below fails "access denied". Quoting fixes '#'; it does NOT fix backslashes,
# which are still read as escapes (\b \t \n \r \\ \s). deploy/.env.example says to generate
# the password from [A-Za-z0-9] only, which retires this whole class of bug.
umask 077
printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" >"$DEPLOY/mysql-backup.cnf"

mkdir -p "$BACKUP_DIR"

# ------------------------------------------------------------------------- the dumps ---
# --defaults-extra-file MUST come before every other option: MySQL parses option-file
# arguments first and documents that they "must be given before other options". Put it
# later and it is ignored, the client falls back to prompting for a password, and under
# -T (no TTY) the job fails or hangs.
#
# --single-transaction  consistent InnoDB snapshot with no locking; the world keeps running.
# --skip-lock-tables    belt-and-braces. --single-transaction already disables the
#                       --lock-tables that mysqldump's default --opt would turn on and that
#                       WOULD stall the world.
# --quick               stream rows instead of buffering whole tables in mysqld's memory.
#                       On an 8 GB box shared with worldserver that is not optional.
# --routines            AzerothCore ships none today; if a module ever adds one, a dump
#                       without this restores a schema that is quietly missing it.
#                       (--triggers is already on by default.)
# No --databases and no CREATE DATABASE in the output: restore.sh drops and recreates the
# schema itself, so these are plain table dumps fed to `mysql <dbname>`.
failed=()
produced=()

for DB in "${DATABASES[@]}"; do
    dest="$BACKUP_DIR/${DB}-${STAMP}.sql.zst"
    log "dumping $DB -> $dest"

    rc=0
    docker compose exec -T mysql \
        mysqldump --defaults-extra-file=/etc/mysql/backup.cnf \
        --single-transaction --quick --skip-lock-tables --routines \
        --default-character-set=utf8mb4 \
        "$DB" |
        zstd -T0 "-$ZSTD_LEVEL" -q -f -o "$dest" || rc=$?

    if [[ $rc -ne 0 ]]; then
        log "FAILED: $DB (exit $rc) -- removing the partial dump"
        rm -f -- "$dest"
        failed+=("$DB")
        continue
    fi

    # A dump that ends without mysqldump's trailer was truncated -- the classic cause is
    # the server going away mid-stream, which does not always surface as a non-zero exit.
    if [[ $VERIFY_DUMPS -eq 1 ]]; then
        if zstd -dc -- "$dest" | tail -c 512 | grep -q -- '-- Dump completed'; then
            :
        else
            log "FAILED: $DB -- dump has no '-- Dump completed' trailer, it is truncated"
            rm -f -- "$dest"
            failed+=("$DB")
            continue
        fi
    fi

    produced+=("$dest")
    log "  ok, $(du -h -- "$dest" | cut -f1)"
done

# ----------------------------------------------------------------------------- offsite -
# OPT-IN. rclone with a 'gdrive:' remote is already configured on the dev box; the VPS
# needs that remote too -- `rclone config file` on the dev box, scp the rclone.conf over,
# or re-run `rclone config` there.  hosting.md 7.3
if [[ $BACKUP_OFFSITE -eq 1 && ${#produced[@]} -gt 0 ]]; then
    if ! command -v rclone >/dev/null; then
        log "BACKUP_OFFSITE=1 but rclone is not installed -- keeping the local copies only"
        failed+=("offsite:rclone-missing")
    elif ! rclone listremotes 2>/dev/null | grep -qx "${RCLONE_REMOTE%%:*}:"; then
        log "BACKUP_OFFSITE=1 but remote '${RCLONE_REMOTE%%:*}:' is not configured on this host"
        log "  rclone listremotes   # to see what is"
        failed+=("offsite:remote-missing")
    else
        log "offsite -> $RCLONE_REMOTE"
        if rclone copy "$BACKUP_DIR" "$RCLONE_REMOTE" --include "*-${STAMP}.sql.zst"; then
            # "exited 0" is not the same as "the bytes are there". hosting.md 7.3 says to
            # verify the remote listing, so verify it here rather than in a runbook.
            for f in "${produced[@]}"; do
                base=$(basename -- "$f")
                if rclone lsf "$RCLONE_REMOTE" --include "$base" 2>/dev/null | grep -qx "$base"; then
                    log "  verified offsite: $base"
                else
                    log "  MISSING OFFSITE: $base"
                    failed+=("offsite:$base")
                fi
            done
        else
            log "rclone copy failed"
            failed+=("offsite:copy")
        fi

        if [[ $OFFSITE_RETENTION_DAYS -gt 0 ]]; then
            rclone delete "$RCLONE_REMOTE" --min-age "${OFFSITE_RETENTION_DAYS}d" || \
                log "offsite prune failed (non-fatal)"
        fi
    fi
elif [[ $BACKUP_OFFSITE -ne 1 ]]; then
    log "offsite push disabled (BACKUP_OFFSITE=$BACKUP_OFFSITE); local copies only"
fi

# --------------------------------------------------------------------------- retention -
# Only prunes after a successful run, so a week of failures cannot silently age out the
# last good dump you have.
if [[ ${#failed[@]} -eq 0 && $LOCAL_RETENTION_DAYS -gt 0 ]]; then
    find "$BACKUP_DIR" -maxdepth 1 -name '*.sql.zst' -mtime "+$LOCAL_RETENTION_DAYS" -print -delete
fi

if [[ ${#failed[@]} -gt 0 ]]; then
    log "FINISHED WITH FAILURES: ${failed[*]}"
    exit 1
fi

log "ok: ${#produced[@]} dumps at stamp $STAMP"
# An untested backup is a hypothesis. Restore last night's acore_characters into a scratch
# schema once, on purpose, before you need it:  scripts/restore.sh --target scratch <dump>
