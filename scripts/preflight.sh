#!/usr/bin/env bash
# preflight.sh -- turn deploy/.env into the generated files compose needs, then refuse to let
# you start a stack that cannot possibly work.
#
# Why this exists as a script rather than a checklist item: the two files below are gitignored,
# generated once, and one of them has NO SECOND CHANCE. MySQL runs
# /docker-entrypoint-initdb.d exactly once, on an empty data directory. Get it wrong and the
# `acore` user is never created, all four AzerothCore pools fail with "Access denied", and the
# only fix is `docker compose down -v` -- which throws away the world DB import you just waited
# half an hour for. bootstrap.sh used to print these as step 4 of a wrap-up message. Printed
# instructions do not run.
#
# Idempotent. Safe to run before every `docker compose up`. Run it from anywhere.
#
# usage: scripts/preflight.sh [--quiet]

set -euo pipefail

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO/deploy"

ok()   { [[ $QUIET -eq 1 ]] || printf '  ok    %s\n' "$*"; }
made() { printf '  MADE  %s\n' "$*"; }
die()  { printf '\npreflight: %s\n' "$*" >&2; exit 1; }

[[ $QUIET -eq 1 ]] || printf '\n== preflight (%s)\n' "$DEPLOY"

# --------------------------------------------------------------------------------- .env ---
[[ -f "$DEPLOY/.env" ]] || die "deploy/.env does not exist.
  cp -n deploy/.env.example deploy/.env && chmod 600 deploy/.env
  then fill it in. See docs/bring-up.md 6."

# shellcheck disable=SC1091
set -a; . "$DEPLOY/.env"; set +a

REQUIRED=(MYSQL_ROOT_PASSWORD ACORE_DB_PASSWORD GHCR_OWNER IMAGE_TAG TAILSCALE_IP)
MISSING=()
for v in "${REQUIRED[@]}"; do
    [[ -n "${!v:-}" ]] || MISSING+=("$v")
done
[[ ${#MISSING[@]} -eq 0 ]] || die "deploy/.env is missing: ${MISSING[*]}"

# AC_SOAP_* are only needed by soap-cmd.sh / phase.sh, so warn rather than fail.
for v in AC_SOAP_USER AC_SOAP_PASS; do
    [[ -n "${!v:-}" ]] || printf '  warn  %s unset -- scripts/phase.sh cannot restart the server\n' "$v"
done

# Password charset. '#' opens a comment mid-line in a MySQL option file and ';' is
# AzerothCore's field separator in "host;port;user;password;database" -- either one silently
# truncates the password somewhere downstream, and the failure surfaces as "Access denied"
# with a password that looks correct in the file.
for v in MYSQL_ROOT_PASSWORD ACORE_DB_PASSWORD; do
    [[ "${!v}" =~ ^[A-Za-z0-9]+$ ]] || die "$v must be [A-Za-z0-9] only (it is parsed by
  Compose, by sh, by a MySQL option file and by AzerothCore's ';'-separated DSN).
  Regenerate:  LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32; echo"
    [[ ${#MYSQL_ROOT_PASSWORD} -ge 16 ]] || die "$v is shorter than 16 characters."
done
ok ".env present, required vars set, passwords parse-safe"

# ------------------------------------------------------- the Docker bind-mount directory trap ---
# Compose bind-mounts these as FILES. If the source path does not exist when the container
# starts, Docker silently creates a DIRECTORY there. mysqld then either ignores it (my.cnf's
# !includedir skips directories without a word of complaint, so you get an untuned server) or
# a later --defaults-extra-file read fails with a confusing error. Catch it before `up`.
for f in mysql.cnf mysql-backup.cnf; do
    if [[ -d "$DEPLOY/$f" ]]; then
        if rmdir "$DEPLOY/$f" 2>/dev/null; then
            printf '  FIXED %s was an empty directory (Docker made it); removed\n' "$f"
        else
            die "deploy/$f is a NON-EMPTY directory. Docker created it on a previous 'up'
  before the real file existed. Inspect and remove it, then re-run."
        fi
    fi
done

[[ -f "$DEPLOY/mysql.cnf" ]] || die "deploy/mysql.cnf is missing -- it is committed, so your
  checkout is incomplete. git checkout -- deploy/mysql.cnf"
ok "mysql.cnf present as a file"

# ----------------------------------------------------------------- mysql-backup.cnf (0600) ---
if [[ ! -f "$DEPLOY/mysql-backup.cnf" ]]; then
    ( umask 077; printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" \
        > "$DEPLOY/mysql-backup.cnf" )
    made "mysql-backup.cnf (0600)"
else
    # Regenerate if the password rotated, otherwise backup.sh fails at 03:00 and the log
    # nobody reads is the only place that says so.
    if ! grep -qF "password=\"$MYSQL_ROOT_PASSWORD\"" "$DEPLOY/mysql-backup.cnf"; then
        ( umask 077; printf '[client]\nuser=root\npassword="%s"\n' "$MYSQL_ROOT_PASSWORD" \
            > "$DEPLOY/mysql-backup.cnf" )
        made "mysql-backup.cnf regenerated (password in .env had changed)"
    else
        ok "mysql-backup.cnf matches .env"
    fi
    chmod 600 "$DEPLOY/mysql-backup.cnf"
fi

# ------------------------------------------------------------- mysql-init/01-databases.sql ---
TPL="$DEPLOY/mysql-init/01-databases.sql.template"
SQL="$DEPLOY/mysql-init/01-databases.sql"

[[ -f "$TPL" ]] || die "deploy/mysql-init/01-databases.sql.template is missing from the checkout."
command -v envsubst >/dev/null || die "envsubst not found. It is in 'gettext-base', which
  scripts/bootstrap.sh installs as part of BASE_PKGS. On a box that did not run bootstrap.sh:
  sudo apt-get install -y gettext-base"

REGEN=0
if [[ ! -f "$SQL" ]]; then
    REGEN=1
elif grep -q '\${\?ACORE_DB_PASSWORD}\?' "$SQL"; then
    # The literal placeholder survived -- someone copied the template instead of substituting.
    REGEN=1
    printf '  warn  01-databases.sql still contains the placeholder; regenerating\n'
elif ! grep -qF "'$ACORE_DB_PASSWORD'" "$SQL"; then
    REGEN=1
    printf '  warn  01-databases.sql does not match ACORE_DB_PASSWORD in .env; regenerating\n'
fi

if [[ $REGEN -eq 1 ]]; then
    # Substitute ONLY this one variable. A bare `envsubst` would eat any other $TOKEN in the
    # SQL, and MySQL user/host strings are full of things that look like shell variables.
    envsubst '${ACORE_DB_PASSWORD}' < "$TPL" > "$SQL"
    grep -q '\${\?ACORE_DB_PASSWORD}\?' "$SQL" && die "substitution failed, placeholder remains in $SQL"
    made "mysql-init/01-databases.sql"
else
    ok "01-databases.sql matches .env"
fi

# All four schemas must be in there -- playerbots adds a fourth beyond AzerothCore's three,
# and AC's own create_mysql.sql does not know about it.
for db in acore_auth acore_characters acore_world acore_playerbots; do
    grep -q "$db" "$SQL" || die "$SQL never mentions $db. All four schemas are required;
  mod-playerbots adds acore_playerbots. Check the template."
done
ok "all four schemas present (incl. acore_playerbots)"

# ----------------------------------------------------------- has initdb already been spent? ---
# The single most expensive mistake available here. If the mysql volume already has data,
# 01-databases.sql will NOT run again no matter what it says.
VOL="$(cd "$DEPLOY" && docker compose config --format json 2>/dev/null \
        | python3 -c 'import json,sys;d=json.load(sys.stdin);print(next(iter(d.get("volumes",{})),""))' 2>/dev/null || true)"
if [[ -n "$VOL" ]] && docker volume inspect "$(basename "$DEPLOY" | tr -d '.')_${VOL}" >/dev/null 2>&1; then
    printf '  NOTE  the mysql volume already exists -- /docker-entrypoint-initdb.d will NOT
        re-run. If you changed ACORE_DB_PASSWORD you must either ALTER USER by hand or
        `docker compose down -v`, which also discards the world DB import.\n'
fi

# ------------------------------------------------------------------------ compose validity ---
if ( cd "$DEPLOY" && docker compose config -q 2>/dev/null ); then
    ok "docker compose config parses"
else
    die "docker compose config failed. Run it yourself for the message:
  ( cd deploy && docker compose config )"
fi

[[ $QUIET -eq 1 ]] || printf '\n== preflight passed -- safe to: cd deploy && docker compose up -d\n\n'
