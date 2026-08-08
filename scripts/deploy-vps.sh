#!/usr/bin/env bash
#
# scripts/deploy-vps.sh -- take a bare Debian 13 box to a serving realm, driven over SSH from
# this dev box. Idempotent: every stage checks before it acts, and re-running is the normal way
# to move forward after fixing something.
#
#   usage: scripts/deploy-vps.sh [options] [stage ...]
#
# Target: Hetzner CX33, 4 vCPU / 7 GB / 71 GB free, Debian 13 (trixie), PUBLIC IP.
# Friends connect over that public IP -- 3724 and 8085 are open to the internet on purpose.
# There is no Tailscale in this design; see docs/deploying.md for the security posture that
# replaces it.
#
# WHAT THIS SCRIPT DOES NOT RE-SOLVE. It calls into the files that already own these problems,
# because a second copy of the logic is a second copy to get wrong:
#   scripts/bootstrap.sh   docker engine + compose plugin from Docker's own apt repo, the 4 GB
#                          swapfile, /srv/wow/{data,backups}, /etc/cron.d/wowserver, and the
#                          pinned wowgaming/client-data download.  hosting.md 7.1, 4, 7.3-7.6
#   scripts/preflight.sh   the two gitignored files generated from deploy/.env, one of which
#                          (mysql-init/01-databases.sql) has NO second chance.  bring-up.md 6
#   scripts/console.sh     the FIFO trick that lets a command reach the worldserver console
#                          without closing its stdin.  Used here to make the SOAP GM account.
#   docs/bring-up.md 2.4   why worldserver owns all four database migrations and authserver
#                          waits for it -- which is why `up` below is ordered the way it is.
#
# THE THREE THINGS THIS SCRIPT ADDS THAT NONE OF THOSE DO:
#   1. A firewall built for a PUBLIC game port, including the part everybody gets wrong:
#      Docker's published ports bypass ufw entirely. See stage_firewall.
#   2. Shipping the image with no registry -- `docker save | ssh | docker load`, with the
#      loaded image ID verified against the local one. The GitHub token here lacks
#      read:packages, so `docker compose pull` would 403 on our own image.
#   3. Post-deploy verification FROM OUTSIDE the box, which is the only vantage point that can
#      tell you a friend can actually connect.
#
set -euo pipefail

# --------------------------------------------------------------------------------- defaults --
VPS_HOST=${VPS_HOST:-root@167.233.128.19}
PUBLIC_IP=${PUBLIC_IP:-167.233.128.19}
WOW_ROOT=${WOW_ROOT:-/srv/wow}
TIMEZONE=${TIMEZONE:-Etc/UTC}
CLIENT_DATA_TAG=${CLIENT_DATA_TAG:-v20.0}
DIST_SRC=${DIST_SRC:-/home/ali/games/wow-3.3.5a/dist}
SITE_DOMAIN=${SITE_DOMAIN:-}          # empty = plain HTTP on :80; set = a name, 443, Secure cookies
WORLD_TIMEOUT=${WORLD_TIMEOUT:-7200}  # seconds to wait for the first-boot world import
VERIFY_SHA=0                          # re-hash every artefact against downloads.json
DRY_RUN=0
ASSUME_YES=0
SKIP_STAGES=()
MODE=deploy
ROLLBACK_TAG=""
PURGE=0

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
R_REPO="$WOW_ROOT/wowserver"
R_DEPLOY="$R_REPO/deploy"
R_DIST="$WOW_ROOT/dist"

ALL_STAGES=(sync provision firewall image clientdata env up realmlist webapp verify artefacts)

usage() {
    cat <<'EOF'
usage: scripts/deploy-vps.sh [options] [stage ...]

Runs FROM the dev box and drives the VPS over SSH. Never run it on the VPS.

Stages, in the order `all` runs them:

  sync        rsync the repo to /srv/wow/wowserver (secrets excluded, never uploaded)
  provision   timezone, unattended-upgrades, docker log rotation, sshd key-only, then
              scripts/bootstrap.sh (docker engine, 4 GB swap, /srv/wow, cron)
  firewall    ufw 22/3724/8085/80[/443] default-deny, AND the DOCKER-USER chain that ufw
              cannot reach. Read stage_firewall in this file before changing it.
  image       docker save | ssh | docker load, no registry, with a digest check
  clientdata  bootstrap.sh --fetch-client-data (1.1 GB down, 3.01 GiB on disk, ON the VPS)
  env         generate deploy/.env on the VPS if absent, then scripts/preflight.sh
  up          mysql -> worldserver (first boot imports the world, ~20 min) -> authserver
  realmlist   UPDATE acore_auth.realmlist SET address = the public IP.  hosting.md 5.2
  webapp      the download portal: web/sql/grant-webapp.sql, then `up -d web nginx`
              (skipped, loudly, if those services are not in the compose file yet)
  verify      containers, ports FROM OUTSIDE, realmlist row, DK data, portal
  artefacts   rsync the downloads into /srv/wow/dist. LAST because the client zip is ~17 GB
              and resumable; the realm is already playable while it uploads.

  all         every stage above, in that order (the default)

Options:
  --host USER@HOST      default root@167.233.128.19  (env: VPS_HOST)
  --public-ip IP        the address friends dial; goes in realmlist.address
                        default 167.233.128.19  (env: PUBLIC_IP)
  --image REF           local image to ship. Default: ghcr.io/<GHCR_OWNER>/wowserver:<IMAGE_TAG>
                        read from deploy/.env, else the newest local ghcr.io/*/wowserver:*
  --domain NAME         the portal is served at NAME over HTTPS: opens 443, sets
                        PORTAL_TLS=1 so session cookies get the Secure flag. It does NOT
                        obtain the certificate -- web/nginx/portal.conf is plain :80 and a
                        terminator has to exist first. Pass this only once one does, or
                        nobody can log in (a Secure cookie is unsettable over HTTP).
                        No domain of your own? 167-233-128-19.sslip.io resolves to the IP
                        and is on the Public Suffix List. docs/deploying.md 7.2.
  --dist DIR            local artefact directory: the FLAT one scripts/package-extras.sh
                        writes downloads.json into  (default /home/ali/games/wow-3.3.5a/dist)
  --verify-sha          re-hash every artefact against downloads.json before uploading.
                        Off by default -- hashing 17 GB is a minute, and size + presence
                        catches the failure that actually happens (a truncated file)
  --client-data-tag TAG wowgaming/client-data release  (default v20.0)
  --timezone TZ         default Etc/UTC
  --world-timeout SECS  how long `up` waits for the first-boot import (default 7200)
  --skip STAGE          skip a stage (repeatable)
  --dry-run             print what would run remotely; change nothing
  --yes                 do not prompt
  -h, --help

Recovery:
  --rollback [TAG]      point deploy/.env at an older image tag and restart. No TAG lists
                        the tags present on the VPS.
  --teardown            docker compose down (containers + network). VOLUMES SURVIVE.
  --teardown --purge    down -v and rm -rf /srv/wow. Takes a backup first, then asks twice.

Examples:
  scripts/deploy-vps.sh --dry-run all
  scripts/deploy-vps.sh sync image up verify
  scripts/deploy-vps.sh --domain 167-233-128-19.sslip.io firewall webapp verify
  scripts/deploy-vps.sh artefacts          # resumable; safe to run again after a dropped link
EOF
}

# ------------------------------------------------------------------------------------ output --
BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; OFF=""
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; OFF=$'\033[0m'
fi
step() { printf '\n%s== %s%s\n' "$BOLD" "$*" "$OFF"; }
info() { printf '   %s\n' "$*"; }
note() { printf '   %s%s%s\n' "$DIM" "$*" "$OFF"; }
warn() { printf '   %sWARN%s  %s\n' "$YLW" "$OFF" "$*" >&2; }
die()  { printf '\n%sdeploy-vps.sh: %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

confirm() {
    [[ $ASSUME_YES -eq 1 ]] && return 0
    local reply
    read -r -p "   $1 [y/N] " reply
    [[ $reply == [yY] ]]
}

# ----------------------------------------------------------------------------- argument parse --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)             VPS_HOST=$2; shift 2 ;;
        --public-ip)        PUBLIC_IP=$2; shift 2 ;;
        --image)            IMAGE_REF=$2; shift 2 ;;
        --domain)           SITE_DOMAIN=$2; shift 2 ;;
        --dist)             DIST_SRC=$2; shift 2 ;;
        --client-data-tag)  CLIENT_DATA_TAG=$2; shift 2 ;;
        --timezone)         TIMEZONE=$2; shift 2 ;;
        --world-timeout)    WORLD_TIMEOUT=$2; shift 2 ;;
        --verify-sha)       VERIFY_SHA=1; shift ;;
        --skip)             SKIP_STAGES+=("$2"); shift 2 ;;
        --dry-run)          DRY_RUN=1; shift ;;
        --yes|-y)           ASSUME_YES=1; shift ;;
        --rollback)         MODE=rollback
                            # optional argument: only consume the next token if it is not a flag
                            if [[ ${2-} && ${2-} != -* ]]; then ROLLBACK_TAG=$2; shift; fi
                            shift ;;
        --teardown)         MODE=teardown; shift ;;
        --purge)            PURGE=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        -*)                 die "unknown option '$1' (try --help)" ;;
        *)                  break ;;
    esac
done

STAGES=("$@")
[[ ${#STAGES[@]} -eq 0 ]] && STAGES=(all)
if [[ ${STAGES[0]} == all ]]; then STAGES=("${ALL_STAGES[@]}"); fi
for s in "${STAGES[@]}"; do
    printf '%s\n' "${ALL_STAGES[@]}" | grep -qxF "$s" || die "unknown stage '$s' (try --help)"
done

wanted() {
    printf '%s\n' "${STAGES[@]}" | grep -qxF "$1" || return 1
    if [[ ${#SKIP_STAGES[@]} -gt 0 ]] && printf '%s\n' "${SKIP_STAGES[@]}" | grep -qxF "$1"; then
        note "skipping stage: $1"
        return 1
    fi
    return 0
}

# --------------------------------------------------------------------------------- ssh plumbing --
# One multiplexed connection for the whole run. This script makes dozens of round trips and a
# fresh TCP+SSH handshake for each of them turns a two-minute stage into a ten-minute one.
CTL_DIR="${TMPDIR:-/tmp}/deploy-vps-$$"
mkdir -p "$CTL_DIR"
trap 'ssh -O exit -o ControlPath="$CTL_DIR/ctl" "$VPS_HOST" >/dev/null 2>&1 || true; rm -rf "$CTL_DIR"' EXIT

SSH_OPTS=(
    -o ControlMaster=auto
    -o ControlPath="$CTL_DIR/ctl"
    -o ControlPersist=10m
    -o ConnectTimeout=15
    -o StrictHostKeyChecking=accept-new
    # A 20-minute silent stretch is normal while the world DB imports. Without keepalives the
    # NAT in the middle drops the session and the deploy dies at the least convenient moment.
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=10
    -o BatchMode=yes
)

# rsh CMD...  -- run one shell command string on the VPS.
rsh() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '   %s[dry-run ssh]%s %s\n' "$DIM" "$OFF" "$*"
        return 0
    fi
    ssh "${SSH_OPTS[@]}" "$VPS_HOST" "$@"
}

# rsh_quiet CMD... -- same, but never dry-run-suppressed. For read-only probes whose output the
# script's own control flow depends on; suppressing those turns --dry-run into a lie.
rsh_quiet() { ssh "${SSH_OPTS[@]}" "$VPS_HOST" "$@" 2>/dev/null; }

# rsh_script VAR=val ... < script  -- feed a heredoc to a remote bash with named inputs.
# Values are %q-quoted because ssh flattens argv into one string that the remote LOGIN shell
# re-parses; without this, any value with a space silently becomes two arguments.
rsh_script() {
    local a pre=()
    for a in "$@"; do pre+=("$(printf '%q' "$a")"); done
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '   %s[dry-run remote script]%s env %s bash -s <<EOF\n' "$DIM" "$OFF" "${pre[*]-}"
        sed 's/^/     | /'
        printf '   EOF\n'
        return 0
    fi
    ssh "${SSH_OPTS[@]}" "$VPS_HOST" "env ${pre[*]-} bash -s"
}

# One remote SQL statement, credentials from the 0600 option file the compose file mounts.
# --defaults-extra-file MUST be the first argument (hosting.md 7.3).
r_sql() {
    rsh_quiet "cd $R_DEPLOY && docker compose exec -T mysql mysql \
        --defaults-extra-file=/etc/mysql/backup.cnf -N -B -e $(printf '%q' "$1")"
}

# ---------------------------------------------------------------------------------- preflight --
[[ -f "$REPO/deploy/docker-compose.yml" ]] || die "cannot find the repo from $REPO"
command -v ssh   >/dev/null || die "ssh is not installed"
command -v rsync >/dev/null || die "rsync is not installed on this dev box (pacman -S rsync)"
command -v docker >/dev/null || die "docker is not installed on this dev box"

# Refuse to point at ourselves. A `docker compose down -v` aimed at localhost by a mistyped
# --host would destroy the live local stack this repo develops against.
case "${VPS_HOST#*@}" in
    localhost|127.0.0.1|::1) die "--host points at this machine. Refusing." ;;
esac

# =============================================================================== stage: sync ==
stage_sync() {
    step "sync repo -> $VPS_HOST:$R_REPO"

    # rsync is not in a Hetzner Debian 13 base image. Bootstrap it with plain ssh first;
    # everything after this point can assume it exists.
    rsh "command -v rsync >/dev/null || { apt-get update -qq && apt-get install -y -qq rsync; }
         install -d -m 0755 $WOW_ROOT $R_REPO"

    # SECRETS NEVER LEAVE THIS BOX. deploy/.env is generated ON the VPS by stage_env with its
    # own passwords, so a compromise of one side is not automatically a compromise of the other,
    # and the dev box's local-stack credentials are not reused on a public host.
    #
    # The three P (protect) filters matter separately from the excludes: excludes stop files
    # being *sent*, protect stops --delete removing what is already there. Without them the
    # first sync after a fresh checkout would delete the VPS's .env and the generated init SQL,
    # and the init SQL cannot be regenerated into a MySQL volume that already exists.
    local -a filters=(
        --filter='P /deploy/.env'
        --filter='P /deploy/mysql-backup.cnf'
        --filter='P /deploy/mysql-init/01-databases.sql'
        --exclude='/.env'
        --exclude='/deploy/.env'
        --exclude='/deploy/mysql-backup.cnf'
        --exclude='/deploy/mysql-init/01-databases.sql'
        --exclude='/.git/'
        --exclude='/.work/'
        --exclude='/build/cache/'
        --exclude='__pycache__/'
        --exclude='*.pem'
        --exclude='*.key'
        # Release artefacts have their own stage and their own destination. A stray 17 GB zip
        # in the working tree must never ride along inside the repo sync.
        --exclude='*.zip'
        --exclude='*.MPQ'
    )

    if [[ $DRY_RUN -eq 1 ]]; then
        rsync -a --delete --dry-run --itemize-changes "${filters[@]}" \
            -e "ssh ${SSH_OPTS[*]}" "$REPO"/ "$VPS_HOST:$R_REPO/" | sed 's/^/   /' | head -40
        return 0
    fi

    rsync -a --delete --human-readable --info=stats1 "${filters[@]}" \
        -e "ssh ${SSH_OPTS[*]}" "$REPO"/ "$VPS_HOST:$R_REPO/" | sed 's/^/   /'

    # The scripts have to be executable on the far side; rsync -a preserves the bit, but a
    # checkout made on a filesystem without one (or a file created by an editor) would not.
    rsh "chmod 0755 $R_REPO/scripts/*.sh"
    info "conf/, deploy/, scripts/, build/modules/*/data/sql and docs/ are on the box"
}

# ========================================================================== stage: provision ==
stage_provision() {
    step "provision (timezone, unattended-upgrades, sshd, docker log rotation)"

    rsh_script "TZ_WANT=$TIMEZONE" <<'REMOTE'
set -euo pipefail

# --- timezone -------------------------------------------------------------------------------
# UTC by default and on purpose: every log line, every cron entry and every backup stamp in
# this repo is UTC, and a box on local time makes correlating them a mental tax forever.
if [[ "$(timedatectl show -p Timezone --value)" != "$TZ_WANT" ]]; then
    timedatectl set-timezone "$TZ_WANT"
    echo "   timezone -> $TZ_WANT"
else
    echo "   (already done) timezone $TZ_WANT"
fi

export DEBIAN_FRONTEND=noninteractive

# --- unattended-upgrades --------------------------------------------------------------------
if ! dpkg-query -W -f='${Status}' unattended-upgrades 2>/dev/null | grep -q 'ok installed'; then
    apt-get update -qq
    apt-get install -y -qq unattended-upgrades apt-listchanges
    echo "   installed unattended-upgrades"
fi
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
# Automatic-Reboot stays FALSE. An unattended reboot at 06:00 is a worldserver killed without
# a `.server shutdown`, i.e. every character rolled back to its last periodic save. Reboots
# here are a human decision; `needrestart` on login tells you when one is owed.
#
# Debian's default origin list is Debian + Debian-Security only, which deliberately does NOT
# include download.docker.com. That is the behaviour we want: the docker engine must not
# restart itself under a running realm. Upgrade it by hand, after a `.server shutdown 300`.
cat >/etc/apt/apt.conf.d/51wowserver-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
echo "   unattended-upgrades: security only, no automatic reboot"

# --- sshd: keys only ------------------------------------------------------------------------
# Port 22 is open to the internet on this box and it WILL be brute-forced within the hour.
# Key auth already works (that is how this script is talking to you), so turning passwords off
# costs nothing and removes the entire attack. Validated with `sshd -t` before the reload --
# a syntax error in a drop-in that gets reloaded blind is how people lock themselves out.
install -d -m 0755 /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/99-wowserver.conf <<'EOF'
# Managed by scripts/deploy-vps.sh
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
if sshd -t 2>/dev/null; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    echo "   sshd: password auth off, root by key only"
else
    rm -f /etc/ssh/sshd_config.d/99-wowserver.conf
    echo "   WARN  sshd -t rejected the drop-in; reverted, sshd left as it was" >&2
fi

# --- docker log rotation --------------------------------------------------------------------
# worldserver is chatty and json-file logs are UNBOUNDED by default. A first boot alone writes
# hundreds of MB of import chatter; left alone, /var/lib/docker eventually eats the disk and
# MySQL is what notices first. Written before the engine is installed so the very first daemon
# start already has it.
install -d -m 0755 /etc/docker
if [[ -s /etc/docker/daemon.json ]]; then
    grep -q 'log-opts' /etc/docker/daemon.json \
        || echo "   WARN  /etc/docker/daemon.json exists without log-opts -- add max-size yourself" >&2
else
    cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
EOF
    echo "   /etc/docker/daemon.json: json-file, 20m x 3 per container"
fi
REMOTE

    # bootstrap.sh owns docker engine, swap, the directory layout and cron. Two of its six
    # steps are wrong for this deployment and are switched off here:
    #   --no-firewall   its ufw block is tailnet-shaped (`allow in on tailscale0`) and opens
    #                   none of the public game ports. stage_firewall replaces it wholesale.
    #   --no-tailscale  there is no tailnet in this design.
    step "bootstrap.sh (docker engine, swap, $WOW_ROOT, cron)"
    rsh "$R_REPO/scripts/bootstrap.sh --no-firewall --no-tailscale" 2>&1 | sed 's/^/   /'

    rsh "install -d -m 0755 $R_DIST"
    info "$R_DIST is the flat directory the portal serves downloads from"
}

# =========================================================================== stage: firewall ==
stage_firewall() {
    step "firewall"

    local tls_port=""
    [[ -n $SITE_DOMAIN ]] && tls_port=443

    # THE POINT OF THIS WHOLE STAGE, stated once so it is not lost in the code:
    #
    # ufw does NOT filter traffic to a published Docker port. Docker writes its own DNAT in
    # nat/PREROUTING and its own accepts in filter/FORWARD via the DOCKER chain, and both run
    # before anything ufw installed. `ufw status` will happily say "deny incoming" while a
    # container port is answering the internet. Running ufw and stopping there is the single
    # most common false sense of security on a box like this.
    #
    # There are exactly three real controls, and this stage uses all three:
    #
    #   1. THE BIND ADDRESS (strongest -- the socket is never on a public interface at all).
    #      deploy/docker-compose.yml decides this per published port:
    #        127.0.0.1:7878  SOAP.       HTTP Basic over cleartext. Loopback only, forever.
    #        (no publish)    MySQL 3306. The mysql service publishes NOTHING; the game
    #                        containers reach it over the `wow` compose network by name.
    #        (no publish)    the portal's own port 8000. Only nginx is published, and
    #                        web/nginx/portal.conf reaches it as `web:8000` over the
    #                        compose network.
    #      Nothing above can be reached from outside no matter what any firewall says. The
    #      verify stage proves 3306 and 7878 are unreachable rather than assuming it.
    #
    #   2. ufw, for everything that is NOT a container: sshd, and anything anyone adds later.
    #
    #   3. THE DOCKER-USER CHAIN, for everything that IS. Docker creates DOCKER-USER, jumps to
    #      it first in FORWARD, and never flushes it -- it exists precisely so you can filter
    #      container traffic. This is where "deny everything except the game and the site"
    #      actually takes effect for published ports.
    rsh_script "TLS_PORT=$tls_port" <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
command -v ufw >/dev/null || { apt-get update -qq; apt-get install -y -qq ufw; }

# ufw must know about IPv6 or `ufw enable` leaves ip6tables wide open on a box Hetzner gives a
# /64 to. Default is already yes on Debian; assert it rather than hope.
sed -i 's/^IPV6=.*/IPV6=yes/' /etc/default/ufw

ufw --force default deny incoming  >/dev/null
ufw --force default allow outgoing >/dev/null
ufw allow 22/tcp   comment 'ssh'                      >/dev/null
ufw allow 3724/tcp comment 'wow authserver (public)'  >/dev/null
ufw allow 8085/tcp comment 'wow worldserver (public)' >/dev/null
ufw allow 80/tcp   comment 'portal http'              >/dev/null
if [[ -n "${TLS_PORT:-}" ]]; then
    ufw allow 443/tcp comment 'portal https'          >/dev/null
else
    # No domain, no certificate, no reason to answer on 443. Removing it matters: a rule left
    # over from a previous run with --domain is an open port with nothing behind it.
    ufw delete allow 443/tcp >/dev/null 2>&1 || true
fi
ufw --force enable >/dev/null

ufw status verbose | sed 's/^/   /'
REMOTE

    # --- DOCKER-USER -------------------------------------------------------------------------
    # Installed as a script plus a systemd unit rather than typed once, because iptables rules
    # do not survive a reboot and Docker recreates DOCKER-USER *empty* every time the engine
    # starts. A one-shot `iptables -I` here would protect the box until the next `apt upgrade`
    # of docker-ce and then quietly stop.
    #
    # The rules match on --dport, which in the FORWARD chain is the port AFTER DNAT, i.e. the
    # CONTAINER port. That is only the same number as the public port because every published
    # port in this stack is published symmetrically (3724:3724, 8085:8085, 80:80, 443:443).
    # If you ever publish 8080:80, add the container port here, not the host one.
    step "DOCKER-USER chain (the part ufw cannot reach)"
    rsh_script "TLS_PORT=$tls_port" <<'REMOTE'
set -euo pipefail

cat >/usr/local/sbin/wow-docker-firewall <<'SCRIPT'
#!/usr/bin/env bash
# Managed by scripts/deploy-vps.sh -- default-deny for CONTAINER traffic arriving from the
# internet. Docker's published ports bypass ufw; this chain is the one Docker guarantees it
# jumps to first from FORWARD and never flushes.
#
#   usage: wow-docker-firewall            (systemd runs it; safe to run by hand, idempotent)
set -euo pipefail

# The interface the default route leaves by -- on a Hetzner CX33 that is the public NIC.
# Derived, not hardcoded: Debian 13 predictable names differ between images (eth0 / ens3).
WAN=$(ip -4 route show default | awk '{for (i=1;i<NF;i++) if ($i=="dev") print $(i+1); exit}')
[[ -n "$WAN" ]] || { echo "wow-docker-firewall: no default route interface" >&2; exit 1; }

ALLOW_TCP=(3724 8085 80 443)

# systemd reports docker.service started when dockerd signals readiness, which is ORDERED
# BEFORE it finishes writing its iptables chains on some boots. Losing the race would leave
# DOCKER-USER empty -- i.e. wide open -- with a unit that exited 0 and told nobody. Wait for
# the chain rather than assume it.
for _ in $(seq 30); do
    iptables -L DOCKER-USER -n >/dev/null 2>&1 && break
    sleep 1
done

apply() {          # apply <iptables|ip6tables> [required|optional]
    local ipt=$1 mode=${2:-optional}
    if ! command -v "$ipt" >/dev/null || ! "$ipt" -L DOCKER-USER -n >/dev/null 2>&1; then
        # ip6tables' DOCKER-USER only exists when the daemon has ip6tables enabled, and with
        # no IPv6 publishing there is nothing for it to filter -- optional, genuinely fine.
        # The v4 chain missing is a different thing entirely: it means the box is unprotected,
        # and exiting 0 there would report success on exactly the state this unit exists to
        # prevent. Fail, so `systemctl status` is red and somebody sees it.
        [[ $mode == required ]] && {
            echo "wow-docker-firewall: $ipt has no DOCKER-USER chain -- refusing to report" >&2
            echo "  success on an unprotected box. Is dockerd running with iptables enabled?" >&2
            exit 1
        }
        return 0
    fi
    "$ipt" -F DOCKER-USER

    # Replies to connections the box itself opened (apt, curl, the client-data download) come
    # back through FORWARD too. Let them through before anything else looks at them.
    "$ipt" -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN

    # Anything not arriving on the public NIC is container-to-container, loopback, or the
    # docker bridge talking to itself. Not our business.
    "$ipt" -A DOCKER-USER ! -i "$WAN" -j RETURN

    local p
    for p in "${ALLOW_TCP[@]}"; do
        "$ipt" -A DOCKER-USER -i "$WAN" -p tcp --dport "$p" -j RETURN
    done

    # Everything else from the internet to any container: dropped, not rejected. A REJECT
    # answers a port scan; a DROP costs the scanner a timeout and tells them nothing.
    "$ipt" -A DOCKER-USER -i "$WAN" -j DROP
}

apply iptables  required
apply ip6tables optional
SCRIPT
chmod 0755 /usr/local/sbin/wow-docker-firewall

cat >/etc/systemd/system/wow-docker-firewall.service <<'UNIT'
[Unit]
Description=DOCKER-USER default-deny for the wowserver stack
After=docker.service
Requires=docker.service
# PartOf so that `systemctl restart docker` -- which recreates DOCKER-USER empty -- also
# re-runs this. Without it, one engine restart silently removes the protection.
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/wow-docker-firewall

[Install]
WantedBy=multi-user.target docker.service
UNIT

systemctl daemon-reload
systemctl enable wow-docker-firewall.service >/dev/null 2>&1 || true
systemctl restart wow-docker-firewall.service
iptables -L DOCKER-USER -n --line-numbers | sed 's/^/   /'
REMOTE
}

# ============================================================================== stage: image ==
# No registry. CI pushes to ghcr.io/<owner>/wowserver:<sha>, but the token available here has no
# read:packages scope, so `docker compose pull` on the VPS returns 403 for our own image -- and
# a brand-new GHCR package is private even when the repo is public (hosting.md 3.6). Streaming
# the image over the SSH connection we already have avoids the whole problem and needs no
# credential on the VPS at all.

# Read one KEY from the DEV BOX's deploy/.env. Used for GHCR_OWNER only -- passwords are never
# read from here, they are generated on the VPS by stage_env and never travel.
local_env() {
    [[ -f "$REPO/deploy/.env" ]] || return 0
    grep -E "^$1=" "$REPO/deploy/.env" 2>/dev/null | head -1 | cut -d= -f2- || true
}

resolve_image() {
    if [[ -n ${IMAGE_REF-} ]]; then return 0; fi
    local owner tag
    owner=$(local_env GHCR_OWNER)
    tag=$(local_env IMAGE_TAG)
    if [[ -n $owner && -n $tag ]] && docker image inspect "ghcr.io/$owner/wowserver:$tag" >/dev/null 2>&1; then
        IMAGE_REF="ghcr.io/$owner/wowserver:$tag"
        return 0
    fi
    IMAGE_REF=$(docker image ls --format '{{.Repository}}:{{.Tag}}' \
                | grep -E '/wowserver:' | grep -v '<none>' | head -1 || true)
    [[ -n $IMAGE_REF ]] || die "no local wowserver image found; pass --image REF"
}

# Sets GHCR_OWNER_OUT / REMOTE_IMAGE_TAG / REMOTE_IMAGE_REF from the local image's own content
# digest. Deterministic, so stage_env can name the tag stage_image will produce (and vice
# versa) without the two stages having to run in the same invocation.
remote_image_ref() {
    resolve_image
    local id
    id=$(docker image inspect --format '{{.Id}}' "$IMAGE_REF")
    GHCR_OWNER_OUT=$(local_env GHCR_OWNER)
    GHCR_OWNER_OUT=${GHCR_OWNER_OUT:-alicin}
    # Derived from the image digest, not from a branch or a date. Two consequences, both
    # wanted: re-running the image stage with an unchanged image is a no-op (the tag already
    # resolves to that exact ID), and --rollback gets stable, meaningful names to choose from
    # instead of a pile of `:latest` you cannot tell apart.
    REMOTE_IMAGE_TAG="img-${id#sha256:}"
    REMOTE_IMAGE_TAG="${REMOTE_IMAGE_TAG:0:16}"
    REMOTE_IMAGE_REF="ghcr.io/$GHCR_OWNER_OUT/wowserver:$REMOTE_IMAGE_TAG"
    LOCAL_IMAGE_ID=$id
}

stage_image() {
    remote_image_ref
    step "ship image $IMAGE_REF (no registry)"

    local local_id local_size ghcr_owner remote_ref
    local_id=$LOCAL_IMAGE_ID
    local_size=$(docker image inspect --format '{{.Size}}' "$IMAGE_REF")
    ghcr_owner=$GHCR_OWNER_OUT
    remote_ref=$REMOTE_IMAGE_REF
    info "local  $local_id"
    info "remote $remote_ref"

    if [[ $DRY_RUN -eq 0 ]]; then
        local have
        have=$(rsh_quiet "docker image inspect --format '{{.Id}}' $(printf '%q' "$remote_ref")" || true)
        if [[ $have == "$local_id" ]]; then
            info "${GRN}already on the VPS with the same image ID -- nothing to send${OFF}"
            return 0
        fi
    fi

    # zstd on both ends if available. `docker save` writes UNCOMPRESSED layer tars, so this is
    # not a marginal saving -- it is routinely 2-3x on this image.
    local comp="cat" decomp="cat"
    if command -v zstd >/dev/null \
       && { [[ $DRY_RUN -eq 1 ]] || rsh_quiet 'command -v zstd >/dev/null && echo yes' | grep -q yes; }; then
        comp="zstd -3 -T0 -c"
        decomp="zstd -d -c"
    else
        warn "zstd missing on one end -- sending the image uncompressed"
    fi

    local meter=(cat)
    if command -v pv >/dev/null; then
        meter=(pv -s "$local_size" -N "docker save")
    else
        note "install 'pv' for a progress bar; sending ~$((local_size/1024/1024)) MB blind"
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        info "[dry-run] docker save $IMAGE_REF | $comp | ssh $VPS_HOST '$decomp | docker load'"
        return 0
    fi

    # set -o pipefail is on, so a failure anywhere in this pipe fails the stage. Without it a
    # broken `docker save` would still exit 0 through a successful `docker load` of nothing.
    docker save "$IMAGE_REF" \
        | "${meter[@]}" \
        | $comp \
        | ssh "${SSH_OPTS[@]}" "$VPS_HOST" "$decomp | docker load" \
        | sed 's/^/   /'

    # VERIFY. The image ID is the sha256 of the image config, and the config commits to every
    # layer's diff ID -- so an ID match is a match on the whole image, not just its name. This
    # is the check that makes a registry-free transfer trustworthy; a truncated stream loads a
    # different ID (or fails outright), it never loads the right one.
    local loaded
    loaded=$(rsh_quiet "docker image inspect --format '{{.Id}}' $(printf '%q' "$IMAGE_REF")" || true)
    [[ $loaded == "$local_id" ]] \
        || die "image digest mismatch after load
  local:  $local_id
  remote: ${loaded:-<not present>}
  The stream was truncated or the wrong image was saved. Nothing has been deployed."
    info "${GRN}digest verified${OFF} $loaded"

    rsh "docker tag $(printf '%q' "$IMAGE_REF") $(printf '%q' "$remote_ref")"
    info "tagged $remote_ref"

    # Keep exactly the tags that matter: whatever deploy/.env currently points at (so a
    # rollback target survives) plus the two most recent. 1.6 GB each adds up on a 71 GB disk.
    rsh_script "REF_PREFIX=ghcr.io/$ghcr_owner/wowserver" "DEPLOY=$R_DEPLOY" <<'REMOTE'
set -euo pipefail
current=$(grep -E '^IMAGE_TAG=' "$DEPLOY/.env" 2>/dev/null | head -1 | cut -d= -f2- || true)
mapfile -t tags < <(docker image ls --format '{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' \
                    | grep "^${REF_PREFIX}:img-" | sort -k2 -r | cut -f1)
keep=2
i=0
for t in "${tags[@]}"; do
    i=$((i+1))
    [[ $i -le $keep ]] && continue
    [[ -n "$current" && "$t" == "${REF_PREFIX}:${current}" ]] && continue
    echo "   pruning old image tag $t"
    docker rmi "$t" >/dev/null 2>&1 || true
done
REMOTE
}

# ========================================================================= stage: clientdata ==
stage_clientdata() {
    step "client data $CLIENT_DATA_TAG (fetched ON the VPS, never uploaded)"
    # 1.11 GiB down, 3.01 GiB extracted. Hetzner's link to GitHub is an order of magnitude
    # faster than a home upstream, and the bytes are byte-identical either way -- there is no
    # version of "rsync 3 GB of maps from the dev box" that is the right call.  hosting.md 4
    rsh "CLIENT_DATA_TAG=$(printf '%q' "$CLIENT_DATA_TAG") \
         $R_REPO/scripts/bootstrap.sh --fetch-client-data \
             --no-swap --no-firewall --no-tailscale --no-cron" 2>&1 | sed 's/^/   /'

    # bring-up.md 1.2: verify the data BEFORE first boot, not 20 minutes into an import that
    # is going to abort on a missing starting-area map.
    if [[ $DRY_RUN -eq 0 ]]; then
        local have
        have=$(rsh_quiet "cd $WOW_ROOT/data && ls -d -- */ 2>/dev/null | tr -d / | tr '\n' ' '")
        info "have: $have"
        for d in maps vmaps mmaps dbc Cameras; do
            grep -qw "$d" <<<"$have" || die "$WOW_ROOT/data is missing $d/ -- the import will fail"
        done
    fi
}

# ================================================================================ stage: env ==
stage_env() {
    step "deploy/.env on the VPS, then preflight.sh"

    # The passwords are generated ON THE VPS and never travel. The dev box does not learn them
    # and does not need to: everything that reads them (compose, backup.sh, soap-cmd.sh) runs
    # there. Read them back with `ssh $VPS_HOST cat /srv/wow/wowserver/deploy/.env` if you ever
    # actually need one.
    # Recomputed rather than inherited, so `deploy-vps.sh env` works on its own -- the tag is a
    # pure function of the local image, so it names the same thing stage_image would produce.
    remote_image_ref

    rsh_script \
        "DEPLOY=$R_DEPLOY" \
        "GHCR_OWNER_IN=$GHCR_OWNER_OUT" \
        "IMAGE_TAG_IN=$REMOTE_IMAGE_TAG" \
        "PUBLIC_IP=$PUBLIC_IP" \
        "SITE_DOMAIN=$SITE_DOMAIN" \
        <<'REMOTE'
set -euo pipefail
cd "$DEPLOY"
umask 077

gen() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32; }

if [[ ! -f .env ]]; then
    cp -n .env.example .env
    chmod 600 .env
    echo "   created deploy/.env from the template"
fi

# Rewrite one KEY=value in place, preserving the file's mode. Never `mv` a temp file over it:
# .env is not bind-mounted today, but mysql-backup.cnf beside it is, and keeping one habit for
# both is how you avoid discovering the inode trap at 03:00 (hosting.md 7.3).
set_kv() {
    local k=$1 v=$2
    if grep -qE "^${k}=" .env; then
        awk -v k="$k" -v v="$v" '
            { if (index($0, k "=") == 1) print k "=" v; else print }
        ' .env > .env.new && cat .env.new > .env && rm -f .env.new
    else
        printf '%s=%s\n' "$k" "$v" >> .env
    fi
}
get_kv() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }

# Generated once, then left alone forever. Regenerating ACORE_DB_PASSWORD after the MySQL
# volume exists does NOT change the grant -- /docker-entrypoint-initdb.d ran on the empty
# data directory and will never run again -- so the pools would start failing authentication
# with a password that looks correct in every file. preflight.sh prints the same warning.
[[ -n "$(get_kv MYSQL_ROOT_PASSWORD)" ]] || { set_kv MYSQL_ROOT_PASSWORD "$(gen)"; echo "   generated MYSQL_ROOT_PASSWORD"; }
[[ -n "$(get_kv ACORE_DB_PASSWORD)"  ]] || { set_kv ACORE_DB_PASSWORD  "$(gen)"; echo "   generated ACORE_DB_PASSWORD"; }
[[ -n "$(get_kv AC_SOAP_PASS)"       ]] || { set_kv AC_SOAP_PASS       "$(gen | head -c 16)"; echo "   generated AC_SOAP_PASS"; }
[[ -n "$(get_kv AC_SOAP_USER)"       ]] || set_kv AC_SOAP_USER SOAPADMIN

# --- the download portal (web/) ---------------------------------------------------------
# Names come from web/app/config.py, which _req()s the three below and raises at import if
# any is blank -- a misconfigured portal is a container that never becomes healthy rather
# than one signing cookies with "changeme". 48 chars because config.py refuses anything
# under 32 as a placeholder tripwire.
[[ -n "$(get_kv PORTAL_SECRET_KEY)"  ]] || { set_kv PORTAL_SECRET_KEY "$(gen)$(gen | head -c 16)"; echo "   generated PORTAL_SECRET_KEY"; }
[[ -n "$(get_kv PORTAL_DB_PASSWORD)" ]] || { set_kv PORTAL_DB_PASSWORD "$(gen)"; echo "   generated PORTAL_DB_PASSWORD"; }
set_kv PORTAL_REALMLIST "$PUBLIC_IP"

set_kv GHCR_OWNER "$GHCR_OWNER_IN"
[[ -n "$IMAGE_TAG_IN" ]] && set_kv IMAGE_TAG "$IMAGE_TAG_IN"

# THE BIND ADDRESS. Two names for one value, and the reason is worth the two lines:
#   TAILSCALE_IP     what deploy/docker-compose.yml reads TODAY, from the tailnet design.
#                    Set to 0.0.0.0 it publishes the game ports on every interface, which for
#                    this public-IP deployment is exactly right -- the old file degrades
#                    CORRECTLY rather than silently.
#   GAME_BIND_ADDR   the honest name, used by the compose diff in docs/deploying.md.
# Both are written so the deploy works before and after that diff lands. preflight.sh still
# requires TAILSCALE_IP to be non-empty, which this satisfies.
set_kv TAILSCALE_IP   0.0.0.0
set_kv GAME_BIND_ADDR 0.0.0.0

# The address friends' clients dial after they authenticate. Same value goes into
# acore_auth.realmlist.address by the realmlist stage and into PORTAL_REALMLIST above --
# all three must agree, and the realmlist row is the one that decides whether they connect.
set_kv REALM_ADDRESS "$PUBLIC_IP"

# THE MANIFEST FILENAME. web/app/config.py defaults PORTAL_MANIFEST to <root>/manifest.json,
# and scripts/package-extras.sh writes <out>/downloads.json. Two correct halves that do not
# meet. Setting it explicitly is the fix, and it belongs here rather than in either of those
# files -- whichever one changed would break the other.
set_kv PORTAL_MANIFEST /srv/wow/dist/downloads.json

# PORTAL_TLS drives the Secure flag on the session cookie and HSTS. Turning it on without a
# certificate in front makes the cookie unsettable over plain HTTP, i.e. nobody can log in --
# so it tracks whether a domain was actually configured, not what we wish were true.
if [[ -n "$SITE_DOMAIN" ]]; then
    set_kv SITE_ADDRESS "$SITE_DOMAIN"
    set_kv PORTAL_TLS 1
else
    set_kv SITE_ADDRESS ":80"
    set_kv PORTAL_TLS 0
fi

chmod 600 .env
echo "   deploy/.env keys: $(cut -d= -f1 .env | grep -v '^#' | grep -v '^$' | tr '\n' ' ')"
REMOTE

    step "preflight.sh"
    # Owns the two generated files and refuses to let a stack start that cannot work.
    # bring-up.md 6: one of them has no second chance.
    rsh "$R_REPO/scripts/preflight.sh" 2>&1 | sed 's/^/   /'
}

# ================================================================================= stage: up ==
stage_up() {
    step "bring-up"

    # ORDER IS NOT COSMETIC (bring-up.md 2.4). worldserver owns the migrations for ALL FOUR
    # schemas -- including acore_playerbots, which the upstream dbimport tool never touches --
    # and authserver runs with updates disabled and depends_on worldserver being healthy.
    # Starting mysql explicitly first just makes the wait legible in this script's output.
    info "1/3 mysql"
    rsh "cd $R_DEPLOY && docker compose up -d mysql"
    # The mysql healthcheck is start_period 60s + up to 40 retries at 5s, and on FIRST boot the
    # entrypoint also runs /docker-entrypoint-initdb.d before the real server binds 3306. 420s
    # leaves margin over that worst case; anything less reports a healthy box as a failure.
    wait_health mysql 420

    info "2/3 worldserver  (first boot imports the world DB: expect ~20 min, budget up to 30)"
    rsh "cd $R_DEPLOY && docker compose up -d worldserver"
    wait_world

    info "3/3 authserver"
    rsh "cd $R_DEPLOY && docker compose up -d authserver"

    # The SOAP GM account is what makes the weekly `.server restart 300` cron work at all
    # (hosting.md 7.6). It can only be created once the world is up, and only through the
    # console -- scripts/console.sh is the FIFO trick that does it without closing stdin.
    ensure_soap_account
}

wait_health() {   # wait_health SERVICE TIMEOUT
    local svc=$1 timeout=$2 deadline status cid
    [[ $DRY_RUN -eq 1 ]] && { info "[dry-run] would wait for $svc to be healthy"; return 0; }
    deadline=$(( $(date +%s) + timeout ))
    while :; do
        cid=$(rsh_quiet "cd $R_DEPLOY && docker compose ps -q $svc" || true)
        if [[ -n $cid ]]; then
            status=$(rsh_quiet "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $cid" || true)
            [[ $status == healthy || $status == running ]] && { info "   $svc: $status"; return 0; }
            [[ $status == exited ]] && {
                rsh "cd $R_DEPLOY && docker compose logs --tail=40 $svc" | sed 's/^/   | /'
                die "$svc exited during bring-up"
            }
        fi
        (( $(date +%s) < deadline )) || die "$svc did not become healthy within ${timeout}s"
        sleep 5
    done
}

wait_world() {
    [[ $DRY_RUN -eq 1 ]] && { info "[dry-run] would wait for the world import"; return 0; }
    local deadline started last="" status cid line
    started=$(date +%s)
    deadline=$(( started + WORLD_TIMEOUT ))
    cid=$(rsh_quiet "cd $R_DEPLOY && docker compose ps -q worldserver")
    [[ -n $cid ]] || die "worldserver container did not start"

    while :; do
        status=$(rsh_quiet "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $cid" || true)
        case "$status" in
            healthy)
                info "   world is up after $(( ($(date +%s) - started) / 60 )) min"
                return 0 ;;
            exited|dead)
                rsh "cd $R_DEPLOY && docker compose logs --tail=60 worldserver" | sed 's/^/   | /'
                die "worldserver exited during first boot. Exit code 1 is an AC error, not a
  resource problem -- read the log above. bring-up.md 6.1 lists the milestones in order." ;;
        esac

        # One line of progress, and only when it changes. The import is silent for minutes at
        # a time and a frozen cursor for 20 minutes is indistinguishable from a hang.
        line=$(rsh_quiet "cd $R_DEPLOY && docker compose logs --tail=1 --no-log-prefix worldserver | tr -d '\r'" || true)
        if [[ -n $line && $line != "$last" ]]; then
            printf '   %s%-100.100s%s\n' "$DIM" "$line" "$OFF"
            last=$line
        fi

        (( $(date +%s) < deadline )) || die "worldserver still not healthy after $((WORLD_TIMEOUT/60)) min.
  It may still be importing -- check with:
    ssh $VPS_HOST 'cd $R_DEPLOY && docker compose logs -f worldserver'
  Do NOT restart it mid-import; that starts the import again from scratch."
        sleep 20
    done
}

ensure_soap_account() {
    [[ $DRY_RUN -eq 1 ]] && return 0
    local user pass have
    user=$(rsh_quiet "grep -E '^AC_SOAP_USER=' $R_DEPLOY/.env | cut -d= -f2-")
    pass=$(rsh_quiet "grep -E '^AC_SOAP_PASS=' $R_DEPLOY/.env | cut -d= -f2-")
    [[ -n $user && -n $pass ]] || { warn "AC_SOAP_USER/PASS unset -- the weekly restart cron cannot run"; return 0; }

    have=$(r_sql "SELECT COUNT(*) FROM acore_auth.account WHERE username = UPPER('$user');" || echo 0)
    have=${have//[^0-9]/}
    if [[ ${have:-0} -ge 1 ]]; then
        note "SOAP account $user already exists"
        return 0
    fi
    step "creating the SOAP GM account ($user)"
    # Console, not SQL: AccountMgr::CreateAccount computes the SRP6 salt+verifier, and hand-
    # writing that into acore_auth.account is how you get an account that exists and cannot
    # log in. gmlevel 3 at RealmID -1 is what ACSoap requires -- below SEC_ADMINISTRATOR it
    # answers 403 (soap-cmd.sh's header documents the exact ladder).
    rsh "$R_REPO/scripts/console.sh \
            $(printf '%q' "account create $user $pass") \
            $(printf '%q' "account set gmlevel $user 3 -1")" 2>&1 | sed 's/^/   /'
}

# =========================================================================== stage: realmlist ==
stage_realmlist() {
    step "realmlist -> $PUBLIC_IP"
    # THE most common private-server failure, and it does not look like what it is: the client
    # authenticates fine against 3724, sees the realm, clicks it, and hangs at "Logging in to
    # game server" forever, because the realm list handed it 127.0.0.1 and it is dutifully
    # dialling its own loopback.  hosting.md 5.2
    #
    # localAddress / localSubnetMask are deliberately NOT touched. Their shipped defaults
    # (127.0.0.1 / 255.255.255.0) already give the right answer: 127.0.0.0/24 cannot contain a
    # friend's public IP, so Realm::GetAddressForClient falls through to `address`, while a
    # client run on the VPS itself still gets loopback. Exactly one column is wrong out of the
    # box; fix that one.
    if [[ $DRY_RUN -eq 1 ]]; then
        info "[dry-run] UPDATE acore_auth.realmlist SET address='$PUBLIC_IP', port=8085, gamebuild=12340 WHERE id=1;"
        return 0
    fi
    r_sql "UPDATE acore_auth.realmlist
           SET address = '$PUBLIC_IP', port = 8085, gamebuild = 12340
           WHERE id = 1;" >/dev/null
    r_sql "SELECT CONCAT_WS('  ', id, name, address, localAddress, localSubnetMask, port, gamebuild, flag)
           FROM acore_auth.realmlist;" | sed 's/^/   /'
    note "flag 2 = VERSION_MISMATCH, normal while the world is still loading; 0 = joinable"
}

# ============================================================================= stage: webapp ==
# The portal lives in web/ (FastAPI behind nginx) and the compose block that runs it is a
# separate workstream. Rather than fail a deploy that is otherwise complete, this stage checks
# whether the compose file has the services yet and says so plainly if it does not. The game
# realm does not depend on any of it.
#
# Service names come from web/nginx/portal.conf, which hardcodes `server web:8000;` as its
# upstream: the FastAPI service MUST be called `web`, and it must publish nothing -- nginx is
# the only thing that talks to it, and the only thing with a published port.
stage_webapp() {
    step "portal (web + nginx)"
    local services proxy=""
    services=$(rsh_quiet "cd $R_DEPLOY && docker compose config --services" || true)
    if ! grep -qx web <<<"$services"; then
        warn "no 'web' service in deploy/docker-compose.yml yet -- skipping.
         The compose block to add is in docs/deploying.md 6.2. Note the service has to be
         named 'web': web/nginx/portal.conf proxies to the literal upstream 'web:8000'."
        return 0
    fi
    for p in nginx proxy caddy; do
        grep -qx "$p" <<<"$services" && { proxy=$p; break; }
    done
    [[ -n $proxy ]] || warn "no front proxy service (nginx) -- nothing will be reachable on
         port 80, because 'web' publishes no ports and must not."

    # The portal authenticates as `acore_web`, a SELECT-only user on acore_auth and
    # acore_characters -- NOT as `acore`, which holds ALL PRIVILEGES on four schemas. Creating
    # it is a deploy step because it needs the root credentials, and web/sql/grant-webapp.sql
    # is written to be re-runnable (CREATE USER IF NOT EXISTS + ALTER USER + REVOKE ALL), so
    # this doubles as the password-rotation path.
    ensure_portal_db_user

    # --build: the portal image has no CI job and there is no registry to pull it from. Its
    # build context is web/, per web/Dockerfile.
    rsh "cd $R_DEPLOY && docker compose up -d --build web ${proxy}" 2>&1 | sed 's/^/   /'
    wait_health web 180
    [[ -n $proxy ]] && wait_health "$proxy" 120
    return 0
}

ensure_portal_db_user() {
    [[ $DRY_RUN -eq 1 ]] && { info "[dry-run] would apply web/sql/grant-webapp.sql"; return 0; }
    [[ -f "$REPO/web/sql/grant-webapp.sql" ]] || { warn "no web/sql/grant-webapp.sql -- skipping the portal DB user"; return 0; }

    step "portal MySQL user (acore_web, SELECT only)"
    # The password is substituted into the SQL and piped on STDIN, never put in argv --
    # container processes are visible in `ps` on the host, which is the same reason
    # deploy/mysql-backup.cnf exists. web/sql/grant-webapp.sql's own header says this.
    rsh_script "DEPLOY=$R_DEPLOY" "REPO=$R_REPO" <<'REMOTE'
set -euo pipefail
cd "$DEPLOY"
set -a; . ./.env; set +a
: "${PORTAL_DB_PASSWORD:?PORTAL_DB_PASSWORD missing from deploy/.env -- run the env stage}"
sed "s/__PORTAL_DB_PASSWORD__/$PORTAL_DB_PASSWORD/g" "$REPO/web/sql/grant-webapp.sql" \
  | docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf
docker compose exec -T mysql mysql --defaults-extra-file=/etc/mysql/backup.cnf -N -B \
  -e "SHOW GRANTS FOR 'acore_web'@'%';" | sed 's/^/   /'
REMOTE
}

# ========================================================================== stage: artefacts ==
stage_artefacts() {
    step "release artefacts -> $R_DIST"
    # Deliberately the LAST stage. The client zip is ~17 GB; on a home upstream that is hours,
    # and none of it blocks the realm being playable. rsync resumes, so a dropped link costs
    # you the tail of one file and not the transfer.
    #
    # FOUR SEPARATE DOWNLOADS, not one blob. Somebody who already has the client and only needs
    # the 4.4 MB Death Knight patch must not be handed a 17 GB link. The layout below is the
    # contract with the webapp; keep it stable.
    [[ -d $DIST_SRC ]] || die "no artefact directory at $DIST_SRC (pass --dist DIR)"

    # THE LAYOUT IS FLAT, and that is a contract, not a preference. scripts/package-extras.sh
    # writes downloads.json beside the files it describes, and every `filename` in it is a
    # BASENAME -- "never a path". The portal resolves each one relative to the manifest's own
    # directory. Put the client zip in a client/ subdirectory and every link 404s.
    #
    # Nothing here generates a SHA256SUMS: downloads.json already carries a sha256 per
    # artefact, written by the tool that built it, and a second list of hashes maintained by a
    # different script is a second list to drift.
    local manifest="$DIST_SRC/downloads.json"
    [[ -f $manifest ]] || die "no downloads.json in $DIST_SRC.
  The manifest is what the portal reads; the files alone are not a release. Cut it with:
    scripts/package-extras.sh --realmlist $PUBLIC_IP"

    # Validate BEFORE spending hours on the upload. package-extras.sh already drops entries
    # whose file is missing at write time, but the manifest and the directory can drift
    # afterwards -- somebody deletes a stale zip, an rsync is interrupted, a file is rebuilt
    # without re-cutting the manifest. Size is checked always (instant, catches truncation);
    # sha256 only on request, because hashing 17 GB on every deploy is a minute nobody spends
    # willingly and therefore a check that gets skipped.
    step "validating downloads.json"
    python3 - "$manifest" "$VERIFY_SHA" <<'PY' || die "the manifest and $DIST_SRC disagree -- fix that before uploading"
import hashlib, json, pathlib, sys
mf = pathlib.Path(sys.argv[1]); deep = sys.argv[2] == "1"
d = json.loads(mf.read_text()); root = mf.parent; bad = 0
print(f"   schema {d.get('schema')}  realmlist {d.get('realmlist')}  repo {d.get('repo')}")
for a in d.get("artifacts", []):
    p = root / a["filename"]
    if "/" in a["filename"]:
        print(f"   BAD  {a['id']}: filename is a path, must be a basename"); bad += 1; continue
    if not p.is_file():
        print(f"   BAD  {a['id']}: {a['filename']} is missing"); bad += 1; continue
    if p.stat().st_size != a["bytes"]:
        print(f"   BAD  {a['id']}: {p.stat().st_size} bytes on disk, {a['bytes']} in manifest"); bad += 1; continue
    if deep:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""): h.update(chunk)
        if h.hexdigest() != a["sha256"]:
            print(f"   BAD  {a['id']}: sha256 mismatch"); bad += 1; continue
    print(f"   ok   {a['id']:<12} {a['filename']}  ({a.get('size_human','?')})")
sys.exit(1 if bad else 0)
PY

    # The realmlist recorded in the manifest is the address baked into the client zip's
    # realmlist.wtf. If it disagrees with what we are deploying, every friend who downloads
    # that zip gets a client pointed somewhere else -- and it presents as "Unable to connect",
    # which nobody debugs by looking at a manifest.
    local mf_realm
    mf_realm=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("realmlist",""))' "$manifest")
    if [[ $mf_realm != "$PUBLIC_IP" ]]; then
        warn "downloads.json says realmlist '$mf_realm' but this deploy is '$PUBLIC_IP'.
         The packaged client points at the wrong server. Re-cut it:
             scripts/package-extras.sh --realmlist $PUBLIC_IP"
        confirm "upload anyway?" || die "aborted"
    fi

    # Disk guard. 71 GB free, a 17 GB zip, a 3 GB data tree, a growing world DB and 1.6 GB per
    # kept image tag: this is not a box where you can ignore the arithmetic. --delete below
    # would otherwise be the only thing stopping two client zips coexisting.
    if [[ $DRY_RUN -eq 0 ]]; then
        local need_kb free_kb
        need_kb=$(du -sk "$DIST_SRC" | cut -f1)
        free_kb=$(rsh_quiet "df -Pk $R_DIST | awk 'NR==2{print \$4}'")
        if (( free_kb < need_kb + 10485760 )); then
            die "not enough room on the VPS: need $((need_kb/1024/1024)) GB + 10 GB headroom,
  have $((free_kb/1024/1024)) GB free. Remove an old client zip from $R_DIST first."
        fi
    fi

    local -a rflags=(
        -a --human-readable --info=progress2
        # Resumable: --partial-dir keeps the fragment out of the served directory (a half a
        # zip that the webapp happily lists is worse than no zip), and --append-verify
        # checksums the existing prefix before continuing, so a changed source re-sends in
        # full instead of concatenating two different builds.
        --partial --partial-dir=.rsync-partial --append-verify
        # Old client zips are 17 GB each. Deleting them is the point, not a side effect.
        --delete --exclude='.rsync-partial/'
    )
    [[ $DRY_RUN -eq 1 ]] && rflags+=(--dry-run --itemize-changes)

    rsync "${rflags[@]}" -e "ssh ${SSH_OPTS[*]}" "$DIST_SRC"/ "$VPS_HOST:$R_DIST/"

    # World-readable: nginx and the portal both mount this :ro, and web/Dockerfile runs as
    # uid 10001 -- a fixed number precisely so there is something to chmod against here.
    rsh "chmod -R a+rX $R_DIST"
    rsh "du -sh $R_DIST/* 2>/dev/null | sed 's|^|   |'" || true
}

# ============================================================================= stage: verify ==
VERIFY_FAILS=0
check() {  # check "<label>" "<expected>" "<actual>"
    if [[ $2 == "$3" ]]; then
        printf '   %sPASS%s  %-46s %s\n' "$GRN" "$OFF" "$1" "$3"
    else
        printf '   %sFAIL%s  %-46s got %s, want %s\n' "$RED" "$OFF" "$1" "${3:-<empty>}" "$2"
        VERIFY_FAILS=$((VERIFY_FAILS+1))
    fi
}
check_true() {  # check_true "<label>" <exit status of a probe> <detail>
    if [[ $2 -eq 0 ]]; then
        printf '   %sPASS%s  %-46s %s\n' "$GRN" "$OFF" "$1" "${3-}"
    else
        printf '   %sFAIL%s  %-46s %s\n' "$RED" "$OFF" "$1" "${3-}"
        VERIFY_FAILS=$((VERIFY_FAILS+1))
    fi
}

port_open() {   # port_open HOST PORT [TIMEOUT] -- 0 if a TCP connection completes
    timeout "${3:-6}" bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null
}

stage_verify() {
    step "verify"
    [[ $DRY_RUN -eq 1 ]] && { info "[dry-run] would probe $PUBLIC_IP from here"; return 0; }

    # --- containers ---------------------------------------------------------------------
    local ps_out svc cid st
    ps_out=$(rsh_quiet "cd $R_DEPLOY && docker compose ps" || true)
    printf '%s\n' "$ps_out" | sed 's/^/   /'
    for svc in mysql worldserver authserver; do
        cid=$(rsh_quiet "cd $R_DEPLOY && docker compose ps -q $svc" || true)
        st=""
        [[ -n $cid ]] && st=$(rsh_quiet "docker inspect -f '{{.State.Status}}' $cid" || true)
        check "container $svc" "running" "$st"
    done

    # --- ports, FROM OUTSIDE ------------------------------------------------------------
    # This is the only vantage point that answers the question that matters. `ss -ltnp` on the
    # VPS tells you a socket is bound; it tells you nothing about the cloud firewall, ufw, or
    # the DOCKER-USER chain sitting between that socket and a friend. Every probe is wrapped
    # in an `if` rather than tested with `$?` because `set -e` would take a bare failing
    # probe as a reason to abandon the whole verification.
    if port_open "$PUBLIC_IP" 3724; then
        check_true "3724/tcp authserver reachable" 0 "from this dev box"
    else
        check_true "3724/tcp authserver reachable" 1 "no TCP connection -- friends cannot log in"
    fi
    if port_open "$PUBLIC_IP" 8085; then
        check_true "8085/tcp worldserver reachable" 0 "from this dev box"
    else
        check_true "8085/tcp worldserver reachable" 1 "no TCP connection -- 'Logging in to game server' hang"
    fi

    # And the inverse, which is the half people forget to test. A pass here means the port is
    # NOT answering the internet.
    if port_open "$PUBLIC_IP" 3306 3; then
        check_true "3306/tcp MySQL closed" 1 "IT IS OPEN -- mysql must publish no ports at all"
    else
        check_true "3306/tcp MySQL closed" 0 "not reachable, correct"
    fi
    if port_open "$PUBLIC_IP" 7878 3; then
        check_true "7878/tcp SOAP closed" 1 "IT IS OPEN -- must be published on 127.0.0.1 only"
    else
        check_true "7878/tcp SOAP closed" 0 "not reachable, correct"
    fi

    # --- realmlist ----------------------------------------------------------------------
    check "realmlist.address" "$PUBLIC_IP" "$(r_sql 'SELECT address FROM acore_auth.realmlist WHERE id=1;')"
    check "realmlist.port"    "8085"       "$(r_sql 'SELECT port FROM acore_auth.realmlist WHERE id=1;')"
    check "realmlist.gamebuild" "12340"    "$(r_sql 'SELECT gamebuild FROM acore_auth.realmlist WHERE id=1;')"
    local flag
    flag=$(r_sql 'SELECT flag FROM acore_auth.realmlist WHERE id=1;')
    check "realmlist.flag (0 = joinable)" "0" "$flag"

    # --- the Death Knight data --------------------------------------------------------------
    # docs/death-knights.md 7. Spell 90000 is Icy Touch rank 1; ten playercreateinfo rows for
    # class 6 with none on map 609 is "every race can be a DK, and none of them start in
    # Acherus". If the SQL did not apply, both numbers are wrong and every DK is broken.
    check "spell_dbc 90000 (Icy Touch rank 1)" "1" \
        "$(r_sql 'SELECT COUNT(*) FROM acore_world.spell_dbc WHERE ID=90000;')"
    check "DK playercreateinfo rows" "10" \
        "$(r_sql 'SELECT COUNT(*) FROM acore_world.playercreateinfo WHERE class=6;')"
    check "DK rows still on Acherus (map 609)" "0" \
        "$(r_sql 'SELECT COUNT(*) FROM acore_world.playercreateinfo WHERE class=6 AND map=609;')"

    # --- worldserver listener ----------------------------------------------------------
    # `grep -q`, not `grep -c`: a count of zero exits 1, so the `-c` form would have to be
    # rescued with `|| echo 0` and print two zeros. 1F95 is 8085 in hex, and /proc/net/tcp
    # needs no packages -- `ss` and `nc` are not in debian:*-slim.  hosting.md 7.5
    if rsh_quiet "cd $R_DEPLOY && docker compose exec -T worldserver grep -q ':1F95 ' /proc/net/tcp"; then
        check_true "worldserver listening on 8085 (1F95)" 0 "in the container's /proc/net/tcp"
    else
        check_true "worldserver listening on 8085 (1F95)" 1 "8085 is not bound inside the container"
    fi

    # --- the download portal ---------------------------------------------------------------
    local url code
    url="http://$PUBLIC_IP/"
    [[ -n $SITE_DOMAIN ]] && url="https://$SITE_DOMAIN/"
    if rsh_quiet "cd $R_DEPLOY && docker compose config --services" | grep -qx web; then
        code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$url" 2>/dev/null || echo 000)
        # 2xx or 3xx means the whole chain works: firewall, DOCKER-USER, nginx and the app.
        # A redirect to /login is a pass -- the front page being gated is the design.
        if [[ $code =~ ^[23] ]]; then
            check_true "portal $url" 0 "HTTP $code"
        else
            check_true "portal $url" 1 "HTTP $code"
        fi
        # /healthz is answered by the portal without touching MySQL (web/app/routes/portal.py),
        # so a pass here with a failing front page separates "the app is down" from "the app is
        # up and its database is not".
        code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${url}healthz" 2>/dev/null || echo 000)
        if [[ $code == 200 ]]; then
            check_true "portal /healthz" 0 "HTTP 200"
        else
            check_true "portal /healthz" 1 "HTTP $code"
        fi
        # The manifest is what turns files on disk into links on a page. Present but empty is
        # a site with a login and nothing behind it, which reads as "the deploy worked".
        local n
        n=$(rsh_quiet "python3 -c \"import json;print(len(json.load(open('$R_DIST/downloads.json'))['artifacts']))\"" || echo 0)
        if [[ ${n//[^0-9]/} -ge 1 ]]; then
            check_true "downloads.json on the VPS" 0 "$n artefacts"
        else
            check_true "downloads.json on the VPS" 1 "missing or empty -- run the artefacts stage"
        fi
    else
        note "no 'web' service in the compose file yet -- portal not checked"
    fi

    # --- swap and disk, because both bite later ------------------------------------------
    rsh_quiet "free -h | sed 's/^/   /'; df -h $WOW_ROOT | sed 's/^/   /'"

    if [[ $VERIFY_FAILS -eq 0 ]]; then
        printf '\n   %sall checks passed%s -- friends can set realmlist to %s\n\n' "$GRN" "$OFF" "$PUBLIC_IP"
    else
        printf '\n   %s%d check(s) failed%s -- see docs/deploying.md "When a friend cannot connect"\n\n' \
            "$RED" "$VERIFY_FAILS" "$OFF"
        return 1
    fi
}

# ============================================================================ mode: rollback ==
do_rollback() {
    step "rollback"
    local tags
    tags=$(rsh_quiet "docker image ls --format '{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' | grep '/wowserver:img-' | sort -k2 -r")
    if [[ -z $ROLLBACK_TAG ]]; then
        info "image tags on the VPS (newest first):"
        printf '%s\n' "$tags" | sed 's/^/     /'
        info "current: $(rsh_quiet "grep -E '^IMAGE_TAG=' $R_DEPLOY/.env | cut -d= -f2-")"
        info ""
        info "re-run with:  scripts/deploy-vps.sh --rollback img-xxxxxxxxxxxx"
        return 0
    fi
    grep -q ":$ROLLBACK_TAG\b" <<<"$tags" || die "no image tagged '$ROLLBACK_TAG' on the VPS"

    confirm "roll back to $ROLLBACK_TAG and restart worldserver + authserver?" || die "aborted"

    # A rollback restarts the world, so anyone online gets a countdown and a character save
    # rather than a yanked socket. `server restart` (exit 2) and NOT `shutdown` (exit 0):
    # under the compose file's `restart: on-failure` an exit 0 leaves the container down and
    # the realm stays offline until somebody notices.  hosting.md 7.2
    if rsh "$R_REPO/scripts/soap-cmd.sh 'server restart 60'" 2>&1 | sed 's/^/   /'; then
        info "waiting out the 60 s countdown"
        sleep 70
    else
        warn "SOAP restart failed (the server may already be down); continuing without a countdown"
    fi

    rsh_script "DEPLOY=$R_DEPLOY" "TAG=$ROLLBACK_TAG" <<'REMOTE'
set -euo pipefail
cd "$DEPLOY"
awk -v v="$TAG" '{ if (index($0,"IMAGE_TAG=")==1) print "IMAGE_TAG=" v; else print }' .env > .env.new
cat .env.new > .env && rm -f .env.new
docker compose up -d worldserver authserver
REMOTE
    info "rolled back to $ROLLBACK_TAG"
    note "the DATABASE is not rolled back. If the image you are leaving applied world-DB
        migrations, those rows are still there -- an older binary usually tolerates that, but
        check the worldserver log for 'Table ... doesn't exist' before declaring victory."
}

# ============================================================================ mode: teardown ==
do_teardown() {
    # NOT ${PURGE:+...} -- PURGE is 0 or 1 and ':+' fires on the string "0" too, which would
    # print "--purge" on every teardown. A banner that lies about how destructive the next
    # thing is, is worse than no banner.
    step "teardown$( [[ $PURGE -eq 1 ]] && printf ' --purge' )"
    if [[ $PURGE -eq 1 ]]; then
        printf '   %sTHIS DESTROYS THE CHARACTER DATABASE.%s  mysql-data, wow-logs, %s -- all of it.\n' \
            "$RED" "$OFF" "$WOW_ROOT"
        confirm "take a backup first? (strongly recommended)" && {
            rsh "$R_REPO/scripts/backup.sh" 2>&1 | sed 's/^/   /' || warn "backup failed"
        }
        if [[ $ASSUME_YES -eq 0 ]]; then
            local typed
            read -r -p "   type TEARDOWN to confirm: " typed
            [[ $typed == TEARDOWN ]] || die "aborted"
        fi
        rsh "cd $R_DEPLOY && docker compose down -v --remove-orphans; rm -rf $WOW_ROOT"
        rsh "systemctl disable --now wow-docker-firewall.service >/dev/null 2>&1 || true
             rm -f /etc/systemd/system/wow-docker-firewall.service /usr/local/sbin/wow-docker-firewall
             rm -f /etc/cron.d/wowserver
             systemctl daemon-reload"
        info "gone. Docker, swap and ufw are left installed."
    else
        # Containers and the network only. Named volumes survive, which is the whole point:
        # this is the "stop everything while I fix something" path, and mysql-data is 20
        # minutes of world import plus every character anyone has.
        confirm "stop and remove the containers? (volumes survive)" || die "aborted"
        if rsh "$R_REPO/scripts/soap-cmd.sh 'server shutdown 60'" 2>&1 | sed 's/^/   /'; then
            info "waiting out the 60 s countdown"
            sleep 70
        else
            # No backticks in this string: it is double-quoted, and they would be command
            # substitution rather than the quoting they look like.
            warn "SOAP shutdown failed. 'docker compose down' below still sends SIGTERM, which
         worldserver handles as a clean save-and-exit, and stop_grace_period is 6m -- so
         nothing is lost. You just do not get the in-game countdown."
        fi
        rsh "cd $R_DEPLOY && docker compose down --remove-orphans"
        info "down. Volumes kept. Bring it back with: scripts/deploy-vps.sh up realmlist verify"
    fi
}

# ==================================================================================== driver ==
printf '%s\n' "${BOLD}deploy-vps.sh${OFF}  host=$VPS_HOST  public-ip=$PUBLIC_IP${SITE_DOMAIN:+  domain=$SITE_DOMAIN}"
[[ $DRY_RUN -eq 1 ]] && printf '%sDRY RUN -- nothing will be changed on the VPS%s\n' "$YLW" "$OFF"

case "$MODE" in
    rollback) do_rollback; exit 0 ;;
    teardown) do_teardown; exit 0 ;;
esac

# Fail before doing anything if the box is not reachable, rather than half way through.
if [[ $DRY_RUN -eq 0 ]]; then
    rsh_quiet 'echo ok' >/dev/null \
        || die "cannot ssh to $VPS_HOST. Check the key, and that you are not behind a
  network that blocks 22. This script never prompts for a password (BatchMode=yes)."
fi

EXIT_CODE=0

wanted sync       && stage_sync
wanted provision  && stage_provision
wanted firewall   && stage_firewall
wanted image      && stage_image
wanted clientdata && stage_clientdata
wanted env        && stage_env
wanted up         && stage_up
wanted realmlist  && stage_realmlist
wanted webapp     && stage_webapp
# A failing verify must not skip the artefact upload -- the two are independent, and "the
# webapp is not deployed yet" should not also mean "nobody can download the client". Remember
# it and exit non-zero at the end instead.
wanted verify     && { stage_verify || EXIT_CODE=1; }
wanted artefacts  && stage_artefacts

exit $EXIT_CODE
