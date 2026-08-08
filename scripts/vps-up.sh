#!/usr/bin/env bash
# vps-up.sh -- bring the game stack up on the VPS. Runs ON the server.
#
# Deliberately small: the hard parts already exist and are called, not re-solved.
#   scripts/preflight.sh   generates the two gitignored files (DB init SQL + backup creds) and
#                          refuses to continue if .env is wrong. Its failure mode is the
#                          expensive one -- /docker-entrypoint-initdb.d runs exactly once, on an
#                          empty data dir, so a bad password here costs a `down -v` and the whole
#                          world import.
#   docs/bring-up.md       the four-database story and the first-boot sequence.
set -euo pipefail

REPO=/srv/wow/wowserver
cd "$REPO/deploy"

# --- .env, generated once and then left alone ------------------------------------------------
if [[ ! -f .env ]]; then
    gen() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32; }
    cat > .env <<EOF
MYSQL_ROOT_PASSWORD=$(gen)
ACORE_DB_PASSWORD=$(gen)
GHCR_OWNER=alicin
IMAGE_TAG=local
TAILSCALE_IP=167.233.128.19
AC_SOAP_USER=soap
AC_SOAP_PASS=$(gen)
EOF
    chmod 600 .env
    echo "== wrote deploy/.env"
else
    echo "== deploy/.env exists, keeping it"
fi

# TAILSCALE_IP is the variable the compose file uses for the publish address. On this box the
# game must be reachable from the internet, so it holds the PUBLIC ip and the ports bind to
# 0.0.0.0. The name is a leftover from the Tailscale plan; the meaning is "the address clients
# reach us on".
echo "== preflight"
"$REPO/scripts/preflight.sh"

echo "== pull/verify image"
docker image inspect "ghcr.io/alicin/wowserver:local" >/dev/null 2>&1 \
  || { echo "image ghcr.io/alicin/wowserver:local not loaded -- run the docker save|ssh|docker load step" >&2; exit 1; }

echo "== up"
docker compose up -d mysql
for i in $(seq 1 40); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q mysql)" 2>/dev/null)" == healthy ]] && break
    sleep 5
done
echo "   mysql: $(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q mysql)" 2>/dev/null)"
docker compose up -d worldserver authserver

echo "== waiting for the world import (first boot: ~20 min, then playerbot population)"
for i in $(seq 1 200); do
    if docker compose logs worldserver 2>&1 | grep -aq 'worldserver-daemon) ready'; then
        echo "   world is ready after ~$((i*15))s"; break
    fi
    sleep 15
done

echo "== realmlist -> the address friends type"
docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
  -e "UPDATE realmlist SET address='167.233.128.19', localAddress='127.0.0.1', port=8085, gamebuild=12340 WHERE id=1;"
docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf -N acore_auth \
  -e "SELECT CONCAT('   realm: ',name,' @ ',address,':',port,' build ',gamebuild) FROM realmlist;"

echo "== state"
docker compose ps --format '   {{.Service}}  {{.State}}  {{.Status}}'
