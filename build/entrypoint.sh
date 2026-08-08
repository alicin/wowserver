#!/bin/sh
# One image, two binaries. Which one a given container runs is decided by
# $ACORE_COMPONENT, set per service in deploy/docker-compose.yml -- which therefore
# sets no `command:`. See docs/hosting.md 3.4 and docs/bring-up.md 1.1 row 5.
#
# Why this file exists at all, rather than the image starting `worldserver` directly:
# a compose file with no `command:` against an image with no ENTRYPOINT starts /bin/sh,
# finds no tty, and exits 0 -- `docker compose up -d` reports success and you have no
# server.
#
# Three properties are load-bearing and none of them are decoration:
#
#   1. VALIDATE. An unset or misspelled $ACORE_COMPONENT must fail loudly here. Without
#      the case statement, `exec /opt/ac/bin/` is a directory and the error Docker shows
#      you is "permission denied", which sends you looking at file modes for an hour.
#
#   2. `exec`. worldserver has to become PID 1. If this script forks the binary and waits,
#      Docker watches the wrapper: SIGTERM from `docker compose stop` never reaches
#      World::StopNow() (no clean save), and AzerothCore's exit-code protocol
#      -- 0 shutdown / 1 error / 2 restart, docs/bring-up.md 5 -- is replaced by the
#      shell's, so `restart: on-failure` restarts on the wrong things.
#
#   3. NO `set -e` reliance for the exec itself. `set -eu` is here for the unset-variable
#      check; the exec is the last statement either way.
#
# `-c` is belt and braces -- AzerothCore's built-in default is already
# <install-prefix>/etc/<binary>.conf, and CMAKE_INSTALL_PREFIX is /opt/ac -- but it makes
# the path the compose bind mounts target explicit and greppable.
set -eu

case "${ACORE_COMPONENT:-}" in
  worldserver|authserver) ;;
  *)
    echo "acore-entrypoint: ACORE_COMPONENT must be 'worldserver' or 'authserver' (got '${ACORE_COMPONENT:-}')" >&2
    echo "acore-entrypoint: set it in deploy/docker-compose.yml under the service's environment:" >&2
    exit 1
    ;;
esac

exec "/opt/ac/bin/${ACORE_COMPONENT}" -c "/opt/ac/etc/${ACORE_COMPONENT}.conf"
