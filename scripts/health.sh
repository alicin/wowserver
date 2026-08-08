#!/usr/bin/env bash
#
# scripts/health.sh -- RSS / grid-creep / swap watch.  docs/hosting.md 7.5, 7.6.
#
#   usage: health.sh            sample once; warn only if a threshold is crossed  (cron)
#          health.sh --report   print the grid-creep trend and say whether the weekly
#                               restart cadence is right
#
# WHY RSS AND NOT CPU. AzerothCore never unloads a map grid once it is loaded -- it stays
# resident until the process exits. worldserver RSS is therefore MONOTONIC within an
# uptime: it only ever goes up, at a rate set by how much of the world the party and the
# bots wander into. There is no configuration that reclaims it and no steady state to
# converge on. On an 8 GB box the only mechanism that returns that memory is a process
# restart, which is why hosting.md 7.6 calls the weekly restart a requirement and a missed
# week an incident.
#
# "Weekly" is a starting cadence, not a measurement. This script is the measurement:
#   - every run appends one sample to $METRICS (a TSV, ~96 lines/day at */15)
#   - a run that crosses a threshold ALSO appends a human line to $LOGFILE
#   - --report turns the TSV into MB/day of creep and a projected crossing date
# If RSS crosses the threshold before Tuesday, move the restart earlier or add a second
# one. If it never crosses in a fortnight, stretch it. The number to watch is the one
# here, not the calendar.
#
# Cron (hosting.md 7.5); bootstrap.sh installs it into /etc/cron.d/wowserver:
#   */15 * * * *  /srv/wow/wowserver/scripts/health.sh 2>> /var/log/wow-health.log
# The redirect is for errors only -- a quiet run prints nothing.
#
# Thresholds, against the hosting.md 1.2 budget for 3 friends + ~40 bots on 8 GB
# (worldserver bare 2.0 GB, +1.0 GB of bots, +2.5 GB of a week's grid creep = 5.5 GB):
#   RSS_WARN_MB    5500   worldserver is into the headroom the restart exists to reclaim
#   SWAP_WARN_MB   1024   swap is an airbag, not a strategy (vm.swappiness=10, 4 GB file)
#   AVAIL_MIN_MB    512   the OOM killer is close, and it does not pick politely
#
set -euo pipefail

usage() {
    cat <<'EOF'
usage: health.sh [--report] [--force-log]

  (no args)     take one sample. Appends to $METRICS always; appends to $LOGFILE and
                prints to stdout only when a threshold is crossed. Exit 0 either way.
  --report      print the grid-creep trend from $METRICS and the OOM/exit state of the
                worldserver container. Read this before changing the restart cadence.
  --force-log   sample and log unconditionally (for testing the plumbing).
  -h, --help

Environment:
  RSS_WARN_MB    5500     worldserver resident set size
  SWAP_WARN_MB   1024     swap in use
  AVAIL_MIN_MB   512      MemAvailable
  METRICS        /var/log/wow-health.tsv
  LOGFILE        /var/log/wow-health.log
  DEPLOY         <repo>/deploy
EOF
}

MODE=sample
case "${1-}" in
    --report)     MODE=report ;;
    --force-log)  MODE=force ;;
    -h | --help)  usage; exit 0 ;;
    '')           ;;
    *)            echo "health.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
DEPLOY=${DEPLOY:-$REPO_ROOT/deploy}

RSS_WARN_MB=${RSS_WARN_MB:-5500}
SWAP_WARN_MB=${SWAP_WARN_MB:-1024}
AVAIL_MIN_MB=${AVAIL_MIN_MB:-512}
METRICS=${METRICS:-/var/log/wow-health.tsv}
LOGFILE=${LOGFILE:-/var/log/wow-health.log}

# Not writable (running as a non-root user, or /var/log is read-only)? Degrade to the
# user's own directory rather than dying -- a health check that dies is worse than useless.
writable() { local f=$1; { [[ -w $f ]] || { [[ ! -e $f ]] && [[ -w $(dirname -- "$f") ]]; }; }; }
writable "$METRICS" || METRICS="${TMPDIR:-/tmp}/wow-health.tsv"
writable "$LOGFILE" || LOGFILE="${TMPDIR:-/tmp}/wow-health.log"

# --------------------------------------------------------------------------- sampling ---
# Container processes are visible in the host PID namespace, so plain `ps` sees
# worldserver even though it runs in a container. `ps -C` exits 1 with no match and
# pipefail would turn that into an abort, hence the `|| true`.
sample_rss_mb() {
    local kb
    kb=$( { ps -o rss= -C worldserver || true; } | awk '{s+=$1} END {print s+0}')
    printf '%d' $((kb / 1024))
}

read -r SWAP_MB AVAIL_MB < <(free -m | awk '
    /^Swap:/ {swap=$3}
    /^Mem:/  {avail=$7}
    END      {printf "%d %d\n", swap+0, avail+0}')

RSS_MB=$(sample_rss_mb)

# Seconds the worldserver process has been up -- `ps -o etimes=` is elapsed seconds, which
# is exactly "time since the last restart", i.e. the window the grid creep accumulated in.
UPTIME_S=$( { ps -o etimes= -C worldserver || true; } | awk 'NR==1 {print $1+0} END {if (NR==0) print 0}')

STAMP_EPOCH=$(date -u +%s)
STAMP_ISO=$(date -Is)

if [[ $MODE != report ]]; then
    if [[ ! -e $METRICS ]]; then
        printf '#epoch\tiso8601\tworldserver_rss_mb\tswap_mb\tmem_avail_mb\tworldserver_uptime_s\n' >"$METRICS"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$STAMP_EPOCH" "$STAMP_ISO" "$RSS_MB" "$SWAP_MB" "$AVAIL_MB" "$UPTIME_S" >>"$METRICS"

    # Deliberately if-blocks and not `[[ ... ]] && warn=1`: under `set -e` a bare AND-list
    # whose test is false IS the script's exit status, so the false case would kill the run.
    warn=0
    if [[ $RSS_MB -gt $RSS_WARN_MB ]]; then warn=1; fi
    if [[ $SWAP_MB -gt $SWAP_WARN_MB ]]; then warn=1; fi
    if [[ $AVAIL_MB -lt $AVAIL_MIN_MB ]]; then warn=1; fi
    if [[ $MODE == force ]]; then warn=1; fi

    if [[ $warn -eq 1 ]]; then
        line="$STAMP_ISO worldserver_rss=${RSS_MB}MB swap=${SWAP_MB}MB avail=${AVAIL_MB}MB uptime=${UPTIME_S}s"
        line="$line (thresholds rss>${RSS_WARN_MB} swap>${SWAP_WARN_MB} avail<${AVAIL_MIN_MB})"
        printf '%s\n' "$line" | tee -a "$LOGFILE"
    fi
    exit 0
fi

# ----------------------------------------------------------------------------- report ---
printf 'wow health report  %s\n\n' "$STAMP_ISO"

if [[ $RSS_MB -eq 0 ]]; then
    printf '  worldserver      NOT RUNNING (no process named worldserver on this host)\n'
else
    printf '  worldserver RSS  %s MB   (warn above %s)\n' "$RSS_MB" "$RSS_WARN_MB"
    printf '  uptime           %s h\n' "$((UPTIME_S / 3600))"
fi
printf '  swap in use      %s MB   (warn above %s)\n' "$SWAP_MB" "$SWAP_WARN_MB"
printf '  mem available    %s MB   (warn below %s)\n\n' "$AVAIL_MB" "$AVAIL_MIN_MB"

if [[ -s $METRICS ]]; then
    # Grid creep is only meaningful WITHIN one uptime -- a restart resets it to ~2 GB, so a
    # slope computed across a restart is meaningless. Take only the samples whose
    # uptime_s is monotonically increasing at the tail of the file, i.e. the current run.
    awk -v now="$STAMP_EPOCH" -v warn="$RSS_WARN_MB" -F'\t' '
        /^#/ { next }
        NF < 6 { next }
        {
            # a drop in uptime means the process restarted: start a new segment
            if ($6 + 0 < prev_up) { n = 0; peak = 0 }
            prev_up = $6 + 0
            n++
            if (n == 1) { t0 = $1 + 0; r0 = $3 + 0 }
            t1 = $1 + 0; r1 = $3 + 0
            peak = (r1 > peak ? r1 : peak)
        }
        END {
            if (n < 2) { print "  grid creep       not enough samples in this uptime yet"; exit }
            hours = (t1 - t0) / 3600.0
            if (hours < 0.5) { printf "  grid creep       %.0f MB over %.1f h -- too short to extrapolate\n", r1 - r0, hours; exit }
            perday = (r1 - r0) / hours * 24.0
            printf "  grid creep       %+.0f MB over %.1f h  =  %+.0f MB/day\n", r1 - r0, hours, perday
            printf "  peak this uptime %.0f MB\n", peak
            if (perday <= 1) {
                print  "  cadence          flat. A weekly restart is comfortable; you could stretch it."
            } else {
                headroom = warn - r1
                days = headroom / perday
                if (days < 0)     printf "  cadence          ALREADY OVER the %d MB threshold. Restart now.\n", warn
                else if (days < 7) printf "  cadence          projected to cross %d MB in %.1f days -- WEEKLY IS TOO SLOW.\n", warn, days
                else if (days > 14) printf "  cadence          projected to cross %d MB in %.1f days -- weekly is conservative.\n", warn, days
                else               printf "  cadence          projected to cross %d MB in %.1f days -- weekly is about right.\n", warn, days
            }
        }
    ' "$METRICS"
else
    printf '  grid creep       no samples in %s yet\n' "$METRICS"
fi
printf '\n'

# An unexplained disappearance is either the OOM killer or an AC error, and the two have
# completely different fixes: OOMKilled=true means raise RAM or lower
# innodb_buffer_pool_size; exit code 1 means read the worldserver log.  hosting.md 7.5
if command -v docker >/dev/null && [[ -d $DEPLOY ]]; then
    for svc in worldserver mysql authserver; do
        cid=$( (cd "$DEPLOY" && docker compose ps -q "$svc" 2>/dev/null) || true)
        [[ -n $cid ]] || { printf '  %-12s (no container)\n' "$svc"; continue; }
        printf '  %-12s %s\n' "$svc" \
            "$(docker inspect --format 'status={{.State.Status}} restarts={{.RestartCount}} oomkilled={{.State.OOMKilled}} exit={{.State.ExitCode}}' "$cid" 2>/dev/null || echo 'inspect failed')"
    done
    printf '\n'
fi

if command -v journalctl >/dev/null; then
    printf '  kernel OOM kills in the last 24h:\n'
    journalctl -k --since '24 hours ago' 2>/dev/null | grep -i 'out of memory\|oom-kill' | tail -5 |
        sed 's/^/    /' || true
    printf '    (nothing above means none)\n\n'
fi

printf '  recent warnings from %s:\n' "$LOGFILE"
if [[ -s $LOGFILE ]]; then tail -5 -- "$LOGFILE" | sed 's/^/    /'; else printf '    (none)\n'; fi
printf '\n  weekly restart:  0 6 * * 2  %s/soap-cmd.sh "server restart 300"\n' "$SCRIPT_DIR"
printf '  Use `server restart` (exit 2, comes back under restart: on-failure), never\n'
printf '  `server shutdown` (exit 0, stays down until somebody notices).\n'
