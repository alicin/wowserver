#!/usr/bin/env bash
#
# scripts/bootstrap.sh -- provision a fresh Debian 13 (trixie) box to run this stack.
#
#   usage: sudo scripts/bootstrap.sh [options]
#
# Target: Hetzner CX33, 4 vCPU / 8 GB / 80 GB, Debian 13. Idempotent -- run it again after
# a change and it does only what is still missing.
#
# It does SIX things and deliberately stops there:
#   1. base packages (docker engine + compose plugin from Docker's own apt repo)
#   2. a 4 GB swapfile with vm.swappiness=10          hosting.md 7.1
#   3. ufw, default-deny, with SSH kept open unless you opt out
#   4. tailscale, INSTALLED but not logged in         hosting.md 5.1
#   5. /srv/wow/{data,backups} and the repo checkout   hosting.md 7
#   6. /etc/cron.d/wowserver -- backup, health, weekly restart   hosting.md 7.3/7.5/7.6
#
# It does NOT deploy. No `docker compose up`, no `tailscale up`, no database. Those are
# docs/bring-up.md 6, and they need secrets this script has no business generating.
#
set -euo pipefail

usage() {
    cat <<'EOF'
usage: sudo scripts/bootstrap.sh [options]

  --no-swap             skip the swapfile
  --no-firewall         skip ufw entirely
  --no-tailscale        skip the tailscale package
  --no-cron             skip /etc/cron.d/wowserver
  --lock-ssh-to-tailnet remove the public SSH allow rule. ONLY after `tailscale up --ssh`
                        works and you have tested it from a second terminal. Getting this
                        wrong on a remote box means a rescue console.
  --fetch-client-data   also download and extract the pinned client data (1.1 GB download,
                        3.01 GiB on disk) into /srv/wow/data. Off by default because it is
                        the slowest step and bring-up.md may already have done it.
  -h, --help

Environment:
  SWAP_SIZE      4G                      passed to fallocate
  SWAPPINESS     10
  WOW_ROOT       /srv/wow
  CLIENT_DATA_TAG  v20.0                 wowgaming/client-data release tag
EOF
}

DO_SWAP=1 DO_FIREWALL=1 DO_TAILSCALE=1 DO_CRON=1 LOCK_SSH=0 FETCH_DATA=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-swap)              DO_SWAP=0 ;;
        --no-firewall)          DO_FIREWALL=0 ;;
        --no-tailscale)         DO_TAILSCALE=0 ;;
        --no-cron)              DO_CRON=0 ;;
        --lock-ssh-to-tailnet)  LOCK_SSH=1 ;;
        --fetch-client-data)    FETCH_DATA=1 ;;
        -h | --help)            usage; exit 0 ;;
        *) echo "bootstrap.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

SWAP_SIZE=${SWAP_SIZE:-4G}
SWAPPINESS=${SWAPPINESS:-10}
WOW_ROOT=${WOW_ROOT:-/srv/wow}
CLIENT_DATA_TAG=${CLIENT_DATA_TAG:-v20.0}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)

step() { printf '\n== %s\n' "$*"; }
info() { printf '   %s\n' "$*"; }
skip() { printf '   (already done) %s\n' "$*"; }
die()  { printf 'bootstrap.sh: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "run me as root (sudo scripts/bootstrap.sh)."

# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == debian ]] || die "this targets Debian; /etc/os-release says ID=${ID:-?}."
CODENAME=${VERSION_CODENAME:?/etc/os-release has no VERSION_CODENAME}
[[ $CODENAME == trixie ]] || info "NOTE: written and verified against Debian 13 (trixie); this box says '$CODENAME'."

export DEBIAN_FRONTEND=noninteractive
APT_UPDATED=0
apt_update_once() { [[ $APT_UPDATED -eq 1 ]] || { apt-get update -qq; APT_UPDATED=1; }; }

# ============================================================================ 1. packages ==
step "base packages"

# Everything here is used by a file in this repo:
#   ca-certificates gnupg curl  -- the two third-party apt repos below
#   zstd                        -- scripts/backup.sh compresses dumps, restore.sh reads them
#   rclone                      -- scripts/backup.sh's OPT-IN offsite push to gdrive:
#   unzip                       -- client data (hosting.md 4)
#   gettext-base                -- envsubst, for deploy/mysql-init/01-databases.sql
#                                  (bring-up.md 6 step 1). See the deviation note below.
#   cron                        -- /etc/cron.d/wowserver
#   git                         -- the repo checkout lives on the box
#   ufw                         -- section 3
BASE_PKGS=(ca-certificates curl gnupg git unzip zstd rclone gettext-base cron ufw)
missing=()
for p in "${BASE_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'ok installed' || missing+=("$p")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    info "installing: ${missing[*]}"
    apt_update_once
    apt-get install -y -qq "${missing[@]}"
else
    skip "all base packages present"
fi
# DEVIATION, flagged: bring-up.md 6 step 1 says "bootstrap.sh does not install [gettext-base]".
# It does now. envsubst is needed exactly once, to generate deploy/mysql-init/01-databases.sql,
# and that file has no second chance -- /docker-entrypoint-initdb.d runs once, on an empty
# data directory, so coming up without it means `docker compose down -v` and another 15-30
# minute world import. A missing binary is not a good reason to lose that.

# ------------------------------------------------------------------------- docker engine --
step "docker engine + compose plugin"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    skip "$(docker --version), $(docker compose version)"
else
    # Conflicting distro packages, per Docker's own install docs. Only removes what is there.
    for p in docker.io docker-doc docker-compose podman-docker containerd runc; do
        if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'ok installed'; then
            info "removing conflicting package: $p"
            apt-get remove -y -qq "$p"
        fi
    done

    install -m 0755 -d /etc/apt/keyrings
    if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
        info "fetching Docker's apt signing key"
        curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
    fi

    arch=$(dpkg --print-architecture)
    line="deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $CODENAME stable"
    if [[ ! -f /etc/apt/sources.list.d/docker.list ]] || ! grep -qxF "$line" /etc/apt/sources.list.d/docker.list; then
        printf '%s\n' "$line" >/etc/apt/sources.list.d/docker.list
        APT_UPDATED=0
    fi

    apt_update_once
    # Exact package names from download.docker.com/linux/debian dists/trixie/stable,
    # checked 2026-08-08. buildx is not needed on the VPS (images are built in CI and
    # pulled from GHCR) but it ships as part of the standard set and costs nothing.
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    info "$(docker --version), $(docker compose version)"
fi

systemctl enable --now docker >/dev/null 2>&1 || true

# Convenience only: let the invoking non-root user drive docker. Membership of the docker
# group is root-equivalent, which is fine on a single-purpose box and worth stating.
if [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]]; then
    if id -nG "$SUDO_USER" | tr ' ' '\n' | grep -qx docker; then
        skip "$SUDO_USER is already in the docker group"
    else
        usermod -aG docker "$SUDO_USER"
        info "added $SUDO_USER to the docker group (root-equivalent; log out and back in)"
    fi
fi

# ================================================================================ 2. swap ==
# worldserver loads the ENTIRE world DB, all DBC data and the script tables into process
# memory before it accepts a single login, and the first boot additionally runs the 15-30
# minute DB import. Startup RSS peaks well above the steady-state figure the box was sized
# for. Without swap, an 8 GB box that runs fine all week gets its worldserver OOM-killed
# during the restart you did to fix something. swappiness=10 keeps the kernel from paging
# out hot map grids during play while still letting the startup peak land somewhere.
# Swap is an airbag, not a strategy.  hosting.md 7.1
if [[ $DO_SWAP -eq 1 ]]; then
    step "swapfile ($SWAP_SIZE) and vm.swappiness=$SWAPPINESS"
    if swapon --show=NAME --noheadings 2>/dev/null | grep -qx /swapfile; then
        skip "/swapfile is active ($(swapon --show=NAME,SIZE --noheadings | grep /swapfile))"
    else
        if [[ ! -f /swapfile ]]; then
            info "allocating /swapfile"
            # fallocate is instant on ext4; the dd path is the fallback for filesystems
            # where a swapfile must not have holes (btrfs, xfs with reflink).
            if ! fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null; then
                [[ $SWAP_SIZE =~ ^([0-9]+)G$ ]] ||
                    die "fallocate refused this filesystem and the dd fallback only
  understands sizes like '4G'; SWAP_SIZE is '$SWAP_SIZE'. Create /swapfile by hand and
  re-run, or set SWAP_SIZE=<n>G."
                dd if=/dev/zero of=/swapfile bs=1M count=$(( ${BASH_REMATCH[1]} * 1024 )) status=none
            fi
        fi
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
        swapon /swapfile
        info "swap on"
    fi
    if grep -qE '^\s*/swapfile\s' /etc/fstab; then
        skip "/swapfile is in /etc/fstab"
    else
        printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
        info "added /swapfile to /etc/fstab"
    fi
    printf 'vm.swappiness=%s\n' "$SWAPPINESS" >/etc/sysctl.d/99-swap.conf
    sysctl -q -w "vm.swappiness=$SWAPPINESS"
    info "vm.swappiness=$(cat /proc/sys/vm/swappiness)"
fi

# ============================================================================ 3. firewall ==
if [[ $DO_FIREWALL -eq 1 ]]; then
    step "ufw"
    ufw --force default deny incoming >/dev/null
    ufw --force default allow outgoing >/dev/null

    # The tailnet is the trust boundary. Everything the game needs arrives on tailscale0.
    ufw allow in on tailscale0 comment 'tailnet' >/dev/null
    # Tailscale's own UDP discovery port, so it can NAT-traverse rather than fall back to
    # a DERP relay. Harmless if tailscale is not installed.
    ufw allow 41641/udp comment 'tailscale wireguard' >/dev/null

    if [[ $LOCK_SSH -eq 1 ]]; then
        ufw delete allow 22/tcp >/dev/null 2>&1 || true
        info "public SSH rule removed -- SSH is tailnet-only from here"
    else
        ufw allow 22/tcp comment 'ssh (public; remove with --lock-ssh-to-tailnet)' >/dev/null
        info "SSH left open on the public interface. Once 'tailscale up --ssh' works and you"
        info "have tested it from a SECOND terminal, re-run with --lock-ssh-to-tailnet."
    fi

    ufw --force enable >/dev/null
    ufw status verbose | sed 's/^/   /'

    # THE THING THAT MAKES PEOPLE THINK ufw IS PROTECTING THEM WHEN IT IS NOT:
    # Docker publishes ports by writing its own iptables rules in the DOCKER chain, which
    # is traversed BEFORE ufw's. A published port is reachable from the internet whatever
    # `ufw status` says. The actual protection for this stack is the bind address, not ufw:
    # deploy/docker-compose.yml publishes 8085 and 3724 on ${TAILSCALE_IP} and 7878 on
    # 127.0.0.1, so nothing is ever bound to 0.0.0.0. Keep it that way -- an empty
    # TAILSCALE_IP would turn ":8085:8085" into every interface, which is why that variable
    # is ${VAR:?}-guarded in the compose file.
    info "note: Docker's published ports bypass ufw. Protection comes from the bind"
    info "      addresses in deploy/docker-compose.yml, not from these rules."
fi

# =========================================================================== 4. tailscale ==
if [[ $DO_TAILSCALE -eq 1 ]]; then
    step "tailscale"
    if command -v tailscale >/dev/null; then
        skip "$(tailscale version | head -1)"
    else
        # Tailscale's documented apt repo for this codename. Verified to exist for trixie
        # on 2026-08-08 (pkgs.tailscale.com/stable/debian/dists/trixie/Release -> 200).
        if [[ ! -s /usr/share/keyrings/tailscale-archive-keyring.gpg ]]; then
            curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.noarmor.gpg" \
                -o /usr/share/keyrings/tailscale-archive-keyring.gpg
            chmod a+r /usr/share/keyrings/tailscale-archive-keyring.gpg
        fi
        curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.tailscale-keyring.list" \
            -o /etc/apt/sources.list.d/tailscale.list
        APT_UPDATED=0
        apt_update_once
        apt-get install -y -qq tailscale
        info "$(tailscale version | head -1)"
    fi
    systemctl enable --now tailscaled >/dev/null 2>&1 || true

    if tailscale status >/dev/null 2>&1; then
        info "tailnet address: $(tailscale ip -4 2>/dev/null | head -1)"
    else
        info "NOT logged in. This step is interactive and deliberately not automated:"
        info "    tailscale up --ssh --advertise-tags=tag:wow"
        info "    tailscale ip -4     # -> 100.x.y.z, and THAT is the address that matters"
        info "It goes in deploy/.env as TAILSCALE_IP, and in acore_auth.realmlist.address."
        info "Those two are different things and both have to be right: realmlist.address is"
        info "what the auth server hands back to a client AFTER it authenticates, so a wrong"
        info "one looks exactly like an auth problem and is not.  hosting.md 5.2"
    fi
fi

# ============================================================================== 5. layout ==
step "directory layout under $WOW_ROOT"
# hosting.md 7. Client data and backups live OUTSIDE the checkout on purpose: 3 GB of
# extracted maps and a pile of dumps have no business in a git working tree. deploy/ lives
# INSIDE it, because the compose file bind-mounts ../conf/... -- the conf files are repo
# files so that `git diff` tells you what the running server is configured with.
install -d -m 0755 "$WOW_ROOT"
install -d -m 0755 "$WOW_ROOT/data"      # world-readable: the container mounts it :ro
install -d -m 0750 "$WOW_ROOT/backups"
info "$WOW_ROOT/data      client data (maps/ vmaps/ mmaps/ dbc/ Cameras/)"
info "$WOW_ROOT/backups   dumps from scripts/backup.sh"

if [[ $REPO_ROOT != "$WOW_ROOT/wowserver" ]]; then
    info ""
    info "NOTE: this checkout is at $REPO_ROOT, not $WOW_ROOT/wowserver."
    info "Every cron line, every doc and every relative bind mount assumes the latter."
    info "    git clone <this repo> $WOW_ROOT/wowserver"
fi

# ------------------------------------------------------------------------- client data ----
# Canonical source: wowgaming/client-data releases -- the same source AzerothCore's own
# installers pull from. Pin the tag; `latest` moving under you mid-session is a bug you do
# not want to debug from a client-side "your data is out of date" error. Extracting it
# yourself from a real 3.3.5a client instead would need 15-25 GB of installed client and
# hours of mmaps_generator for a byte-comparable result.  hosting.md 4
if [[ $FETCH_DATA -eq 1 ]]; then
    step "client data $CLIENT_DATA_TAG"
    if [[ -d $WOW_ROOT/data/maps && -d $WOW_ROOT/data/mmaps && -d $WOW_ROOT/data/dbc ]]; then
        skip "$WOW_ROOT/data already has maps/ mmaps/ dbc/"
    else
        url="https://github.com/wowgaming/client-data/releases/download/${CLIENT_DATA_TAG}/Data.zip"
        info "downloading $url  (~1.11 GiB)"
        curl -fL --retry 3 -o "$WOW_ROOT/data/Data.zip" "$url"
        info "extracting (~3.01 GiB)"
        unzip -q -o "$WOW_ROOT/data/Data.zip" -d "$WOW_ROOT/data"
        rm -f "$WOW_ROOT/data/Data.zip"
        info "have: $(cd "$WOW_ROOT/data" && ls -d -- */ 2>/dev/null | tr -d / | tr '\n' ' ')"
    fi
fi

# ================================================================================ 6. cron ==
if [[ $DO_CRON -eq 1 ]]; then
    step "/etc/cron.d/wowserver"
    CRON_SCRIPTS=$WOW_ROOT/wowserver/scripts
    # A /etc/cron.d file needs a user field, needs a PATH (cron's is minimal and
    # /usr/bin/docker would not be found), must be named [A-Za-z0-9_-]+ (a dot in the name
    # makes cron ignore it silently), and must end with a newline.
    cat >/etc/cron.d/wowserver <<EOF
# Managed by scripts/bootstrap.sh. Edit there, not here.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""

# Nightly dumps of acore_auth + acore_characters + acore_playerbots at an hour nobody
# plays. NOT acore_world -- it is reproducible from source on any boot.  hosting.md 7.3
17 5 * * *  root  $CRON_SCRIPTS/backup.sh >> /var/log/wow-backup.log 2>&1

# RSS / grid-creep / swap watch. Quiet unless a threshold is crossed; the redirect is for
# errors only. Every run appends a sample to /var/log/wow-health.tsv, which is what
# \`health.sh --report\` turns into a restart cadence.  hosting.md 7.5
*/15 * * * *  root  $CRON_SCRIPTS/health.sh 2>> /var/log/wow-health.log

# THE WEEKLY RESTART IS A REQUIREMENT, NOT A SUGGESTION. AzerothCore never unloads a map
# grid once it is loaded, so worldserver RSS is monotonic within an uptime and only a
# process restart returns it. A missed week is an incident.  hosting.md 7.6
#
# \`server restart\` (exit 2) and NOT \`server shutdown\` (exit 0): under the compose file's
# \`restart: on-failure\`, exit 0 leaves the container down and the realm stays offline
# until somebody notices.
0 6 * * 2  root  $CRON_SCRIPTS/soap-cmd.sh "server restart 300" >> /var/log/wow-restart.log 2>&1
EOF
    chmod 0644 /etc/cron.d/wowserver
    info "installed. Every line is inert until deploy/.env exists -- backup.sh and"
    info "soap-cmd.sh both refuse to run without it, loudly, into their logs."
    systemctl enable --now cron >/dev/null 2>&1 || true
fi

# ================================================================================= wrap-up =
cat <<EOF

== bootstrap complete

Not done here, on purpose, in this order (docs/bring-up.md 6):

  1. tailscale up --ssh --advertise-tags=tag:wow   &&  tailscale ip -4
  2. clone this repo to $WOW_ROOT/wowserver (if it is not already there)
  3. cd $WOW_ROOT/wowserver/deploy
     cp -n .env.example .env && chmod 600 .env
     ...fill in MYSQL_ROOT_PASSWORD, ACORE_DB_PASSWORD, GHCR_OWNER, IMAGE_TAG, TAILSCALE_IP
     ...plus AC_SOAP_USER and AC_SOAP_PASS, which scripts/soap-cmd.sh needs
     Generate both passwords from [A-Za-z0-9] ONLY:
         LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32; echo
     '#' starts a comment mid-line in a MySQL option file and ';' is AzerothCore's field
     separator in "host;port;user;password;database", so either one silently truncates a
     password somewhere downstream.
  4. scripts/preflight.sh
     Generates BOTH gitignored files from .env (mysql-init/01-databases.sql and
     mysql-backup.cnf), validates the password charset, clears Docker's bind-mount
     directory trap, and refuses to continue if anything is wrong. Idempotent -- run it
     before every 'up'. One of the two files it writes has NO second chance:
     /docker-entrypoint-initdb.d runs exactly once, on an empty data directory.
  5. the client data, if you skipped --fetch-client-data
  6. seed conf/ from the image's .conf.dist files -- bring-up.md 4.3 -- and apply the
     phase-1 values BEFORE the first boot: scripts/phase.sh --dry-run 1
  7. docker compose pull && docker compose up -d && docker compose logs -f worldserver

Reboot to confirm swap and docker come back on their own before you trust any of it.
EOF
