#!/usr/bin/env bash
#
# scripts/phase.sh -- flip the realm between phase 1 (cap 60), 2 (cap 70) and 3 (cap 80).
#
#   usage: phase.sh [options] <1|2|3>
#
# ============================================================================ WHAT MOVES
# NINE keys across FIVE conf files. Nothing else. In particular:
#
#   THERE IS NO PER-PHASE SQL, AND `Expansion` DOES NOT MOVE.
#
# docs/server-config.md 1 opens with the account.expansion trap -- the session's effective
# expansion is min(account.expansion, worldserver.conf Expansion), and AccountMgr stamps
# the account column from CONFIG_EXPANSION at creation time, so raising the config without
# raising the column leaves existing players silently stuck. That whole trap is designed
# out here, not worked around:
#
#     Expansion = 2 IN ALL THREE PHASES. Every race and class is open from day one --
#     Death Knight, Blood Elf, Draenei, everything -- and there is no
#     CharacterCreating.Disabled.RaceMask / ClassMask. Accounts are therefore created at
#     expansion = 2 once, at account creation, and never need raising again.
#
#     GATING IS THE LEVEL CAP AND NOTHING ELSE. Outland and Northrend are reachable in
#     phase 1. That is deliberate and accepted: the cap makes them pointless rather than
#     closed. Do not add zone blockers.
#
# So `UPDATE account SET expansion = N` -- step 4 of server-config.md's flip procedure,
# "THE STEP THAT GETS MISSED" -- is gone. What is NOT gone is the check: any account whose
# column is below 2 (created while the config was briefly wrong, or restored from an old
# auth dump) is still broken, so this script counts them every run and can fix them with
# --fix-expansion.
#
# ======================================================================= THE `# PHASE` MARKER
# conf/ marks every per-phase key with a `PHASE` comment. This script cross-checks that
# marker against its own table in both directions and warns on either mismatch -- a key
# the conf carries a marker for but this table does not know about is a key that will
# never move.
#
# THE MARKER MUST BE ON ITS OWN LINE, ABOVE THE KEY. NOT TRAILING ON THE KEY LINE.
# AzerothCore's config parser treats '#' as a comment ONLY as the first character of a
# trimmed line. From src/common/Configuration/Config.cpp ParseFile() @ CORE_SHA 092e9ba6,
# read 2026-08-08:
#       line = Acore::String::Trim(line, in.getloc());
#       if (line.empty()) continue;
#       if (line[0] == '#' || line[0] == '[') continue;      <-- only here
#       auto const equal_pos = line.find('=');
#       auto value = Trim(line.substr(equal_pos + 1, npos));  <-- everything after '='
# There is no mid-line comment stripping, and integer conversion is strict --
# StringConvert::For<integral>::FromString requires `res.ptr == end` from std::from_chars
# and returns nullopt on any trailing character. So
#       MaxPlayerLevel = 60   # PHASE
# parses as the value "60   # PHASE", fails to convert, and the key silently falls back to
# its compiled-in default of 80. That is the exact silent-config failure mode this project
# has already been bitten by once. (Upstream relies on this too, in the other direction:
# AiPlayerbot.WorldBuffMatrix's value is full of '#' characters on purpose.)
# This script therefore HOISTS any trailing comment it finds on a key it owns onto its own
# line above, loudly, and refuses to be the thing that reintroduced the bug.
#
# ============================================================================== PROCEDURE
#   1. rewrite the confs, by key, never by line number
#   2. show a diff and require confirmation
#   3. announce in-game, then `.server shutdown <delay>` over SOAP
#   4. wait for the container to exit, then `docker compose up -d`
#   5. print the verification checklist
#
# A flip is ALWAYS a full restart, never `.reload config`: MaxPlayerLevel is registered
# ConfigValueCache::Reloadable::No in WorldConfig.cpp, so a reload-only flip is guaranteed
# to be a half-flip. There is deliberately no --reload mode.
#
set -euo pipefail

# ---------------------------------------------------------------------------- the table --
# relpath-under-conf/ | key | phase1 | phase2 | phase3
#
# Every key below was read out of the real .conf.dist at the pin in build/modules.txt on
# 2026-08-08, not from memory:
#   MaxPlayerLevel                                     worldserver.conf.dist:2147  (=80)
#   AiPlayerbot.RandomBotMaxLevel                      playerbots.conf.dist:705    (=80)
#   AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel   playerbots.conf.dist:963    (=80)
#   AiPlayerbot.RandomBotMaps                          playerbots.conf.dist:1221   (=0,1,530,571)
#   RDF.Expansion                                      mod-rdf-expansion.conf.dist:15 (=2)
#   AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel
#                                                      mod_ahbot.conf.dist:985     (=999)
#   Assistant.Professions.Master.Enabled               mod_assistant.conf.dist:74  (=0)
#   Assistant.Professions.GrandMaster.Enabled          mod_assistant.conf.dist:76  (=0)
#   Assistant.FlightPaths.WrathOfTheLichKing.Enabled   mod_assistant.conf.dist:53  (=0)
#
PHASE_KEYS=(
    # The cap. The only thing that actually gates progression on this realm.
    # Reloadable::No -- restart required, which is why a flip is always a restart.
    "worldserver.conf|MaxPlayerLevel|60|70|80"

    # Bot level window. RandomBotMaxLevel is belt-and-braces: RandomPlayerbotMgr both
    # clamps it already --
    #     uint32 maxLevel = sPlayerbotAIConfig.randomBotMaxLevel;
    #     if (maxLevel > sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL))
    #         maxLevel = sWorld->getIntConfig(CONFIG_MAX_PLAYER_LEVEL);
    # in RandomizeFirst() and IncreaseLevel() (src/Bot/RandomPlayerbotMgr.cpp @ the pin) --
    # so bots cannot outlevel the cap even if this were left at 80. Move it anyway: it
    # keeps the conf honest, and its neighbour below is NOT clamped by anything.
    "modules/playerbots.conf|AiPlayerbot.RandomBotMaxLevel|60|70|80"

    # SmartScale's level window. Bots OUTSIDE this range ignore SmartScale entirely and
    # always run at the full BotActiveAlone value, so leaving the ceiling at 80 in phase 1
    # would mean the CPU governor stops governing exactly the bots that are at the cap.
    "modules/playerbots.conf|AiPlayerbot.botActiveAloneSmartScaleWhenMaxLevel|60|70|80"

    # Where random bots may be teleported. See the note below the table about map 530.
    "modules/playerbots.conf|AiPlayerbot.RandomBotMaps|0,1|0,1,530|0,1,530,571"

    # Random Dungeon Finder is broken at 59-60 and 69-70 without this module: the retail
    # WotLK dungeon list has no entries a level-60 character qualifies for. 0 = a WotLK or
    # TBC RDF queue joins as Classic RDF, 1 = as TBC, 2 = stock WotLK behaviour.
    # This is the check that fails quietly after a flip. Do not skip it.
    "modules/mod-rdf-expansion.conf|RDF.Expansion|0|1|2"

    # The auction house's level ceiling. INERT unless the one-time install step was done:
    # mod-ah-bot-plus ships AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled =
    # false, and MaxLevel is only consulted when it is true. Preflight checks that below.
    "modules/mod_ahbot.conf|AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel|60|70|80"

    # mod-assistant's profession tiers. Master = 375 (the TBC ceiling), GrandMaster = 450
    # (the WotLK ceiling). The Assistant.FlightPaths.*.RequiredLevel keys are LEVEL gates,
    # not phase gates -- they are already correct for all three phases. Do not touch them.
    "modules/mod_assistant.conf|Assistant.Professions.Master.Enabled|0|1|1"
    "modules/mod_assistant.conf|Assistant.Professions.GrandMaster.Enabled|0|0|1"
    "modules/mod_assistant.conf|Assistant.FlightPaths.WrathOfTheLichKing.Enabled|0|0|1"
)
#
# A NOTE ON AiPlayerbot.RandomBotMaps AND MAP 530, since the final decision changed the
# premise server-config.md's 0,1 was chosen under.
# Map 530 ("Expansion01") is not only Outland: it also carries the Blood Elf and Draenei
# starting zones. server-config.md 1 could leave it out of phase 1 because phase 1 disabled
# those two races. They are open from day one now, so with 0,1 a Blood Elf bot in phase 1
# is periodically relocated to a level-appropriate spot on map 0 or 1 -- Elwynn rather than
# Eversong. That is cosmetic, not broken, and it is why this table still matches the doc.
# It is NOT a level-safety question either way: randomBotMaps is only a FILTER over a list
# that is already level-indexed --
#     TravelMgr::GetTeleportLocations(bot) -> locsPerLevelCache[bot->GetLevel()]
# and RandomPlayerbotMgr::RandomTeleport() then erases every location whose map is not in
# randomBotMaps (src/Bot/RandomPlayerbotMgr.cpp @ the pin) -- so adding 530 in phase 1
# could not send a level-20 bot to Hellfire. If you would rather see Blood Elf and Draenei
# bots in their own starting zones from phase 1, change the p1 field above to 0,1,530 and
# change the matching `# PHASE` marker in conf/modules/playerbots.conf to agree; the
# cross-check below will tell you if you change only one of them.
#
# NOT per-phase any more, and deliberately absent from the table above:
#   worldserver.conf  Expansion                              -- 2 in all three phases
#   worldserver.conf  CharacterCreating.Disabled.RaceMask    -- never set; all races open
#   worldserver.conf  CharacterCreating.Disabled.ClassMask   -- never set; all classes open
#   playerbots.conf   AiPlayerbot.DisableDeathKnightLogin    -- 0 in all three phases
#                     (upstream's own default; DKs are open from phase 1)
#   acore_auth        UPDATE account SET expansion           -- one-time, at expansion 2

# --------------------------------------------------------------------------------- args --
usage() {
    cat <<'EOF'
usage: phase.sh [options] <1|2|3>

  --dry-run          show the diff and the preflight report, change nothing, exit
  --no-restart       write the confs but do not announce, shut down or restart
  --yes              skip the confirmation prompt (for a scripted flip)
  --shutdown-delay N in-game countdown before the restart, seconds (default 300)
  --fix-expansion    also run `UPDATE account SET expansion = 2` on acore_auth for any
                     account below 2. Not per-phase -- a repair, for accounts created
                     while the config was wrong or restored from an old dump.
  -h, --help

Idempotent: running it twice for the same phase rewrites nothing and (unless --no-restart)
restarts the server, which is what server-config.md's spec asks for. You still get the
confirmation prompt, so declining it is the way to say "actually, no restart".

Environment:
  DEPLOY   compose project dir (default: <repo>/deploy)
  CONF_DIR conf tree           (default: <repo>/conf)
EOF
}

DRY_RUN=0
DO_RESTART=1
ASSUME_YES=0
SHUTDOWN_DELAY=300
FIX_EXPANSION=0
PHASE=

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)         DRY_RUN=1 ;;
        --no-restart)      DO_RESTART=0 ;;
        --yes | -y)        ASSUME_YES=1 ;;
        --shutdown-delay)  SHUTDOWN_DELAY=${2:?--shutdown-delay needs a number}; shift ;;
        --fix-expansion)   FIX_EXPANSION=1 ;;
        -h | --help)       usage; exit 0 ;;
        1 | 2 | 3)         PHASE=$1 ;;
        *)                 echo "phase.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ -n $PHASE ]] || { usage >&2; exit 2; }
[[ $SHUTDOWN_DELAY =~ ^[0-9]+$ ]] || { echo "phase.sh: --shutdown-delay must be a number." >&2; exit 2; }

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
DEPLOY=${DEPLOY:-$REPO_ROOT/deploy}
CONF_DIR=${CONF_DIR:-$REPO_ROOT/conf}
export DEPLOY   # scripts/soap-cmd.sh is invoked below and must agree about where .env is

case "$PHASE" in
    1) CAP=60; PHASE_NAME="Classic" ;;
    2) CAP=70; PHASE_NAME="The Burning Crusade" ;;
    3) CAP=80; PHASE_NAME="Wrath of the Lich King" ;;
esac

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; WARNINGS=$((WARNINGS + 1)); }
die()  { printf 'phase.sh: %s\n' "$*" >&2; exit 1; }
WARNINGS=0

[[ -d $CONF_DIR ]] || die "no conf tree at $CONF_DIR. The repo must be checked out whole; \
docker-compose.yml bind-mounts ../conf/worldserver.conf and ../conf/modules."

# ------------------------------------------------------------------------------- helpers --
# Read a key's value. Exact key match on the text left of the first '=', so a dot in the
# key name can never behave as a regex wildcard and match a neighbouring key.
get_key() { # <file> <key>  -> value on stdout, "" and status 1 if absent
    awk -v key="$2" '
        { t = $0; sub(/^[ \t]+/, "", t)
          if (t == "" || substr(t,1,1) == "#" || substr(t,1,1) == "[") next
          eq = index(t, "="); if (eq == 0) next
          k = substr(t, 1, eq-1); sub(/[ \t]+$/, "", k)
          if (k != key) next
          v = substr(t, eq+1); sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
          print v; found = 1; exit }
        END { if (!found) exit 1 }
    ' "$1"
}

# Rewrite one key, to stdout. Exit 3 = key absent, 4 = key present more than once.
# Any trailing comment on the key line is HOISTED to its own line above (see the header).
rewrite_key() { # <file> <key> <newvalue>
    awk -v key="$2" -v newval="$3" '
        { line = $0
          t = line; sub(/^[ \t]+/, "", t)
          if (t == "" || substr(t,1,1) == "#" || substr(t,1,1) == "[") { print line; next }
          eq = index(t, "="); if (eq == 0) { print line; next }
          k = substr(t, 1, eq-1); sub(/[ \t]+$/, "", k)
          if (k != key) { print line; next }

          found++
          oeq  = index(line, "=")
          head = substr(line, 1, oeq)        # indent + key + padding + "=", verbatim
          rest = substr(line, oeq + 1)
          h = index(rest, "#")
          comment = ""
          if (h > 0) { comment = substr(rest, h); sub(/[ \t]+$/, "", comment) }
          curval = (h > 0 ? substr(rest, 1, h - 1) : rest)
          sub(/^[ \t]+/, "", curval); sub(/[ \t]+$/, "", curval)

          # Already correct and nothing to fix: leave the line byte-identical, so a re-run
          # for the same phase produces an empty diff instead of a cosmetic one.
          if (comment == "" && curval == newval) { print line; next }

          if (comment != "") {
              indent = ""
              if (match(line, /^[ \t]+/)) indent = substr(line, RSTART, RLENGTH)
              print indent comment
              printf("HOISTED\t%s\t%s\n", key, comment) > "/dev/stderr"
          }
          # Reusing `head` keeps whatever alignment the conf file uses -- mod_assistant.conf
          # pads its keys into a column, and rewriting that to "Key = v" would show up as a
          # diff on every flip for keys whose value did not actually move.
          print head " " newval
        }
        END { if (found == 0) exit 3; if (found > 1) exit 4 }
    ' "$1"
}

# Every key the conf tree has flagged as per-phase, so the two lists can be compared.
# conf/ writes the marker on the line IMMEDIATELY ABOVE the key, in the form
#     # PHASE  <Key>  p1=<v>  p2=<v>  p3=<v>
# so this reads back the key name AND the three values the conf believes in, and the caller
# diffs them against PHASE_KEYS. Requiring PHASE right after the '#' is what keeps prose
# from arming it -- conf/worldserver.conf contains the lines "They are NOT marked # PHASE"
# and "IN ALL THREE PHASES", both immediately above real keys.
# Output: key<TAB>name-in-marker<TAB>p1<TAB>p2<TAB>p3   (fields 2-5 empty if not stated)
marked_keys() { # <file>
    awk '
        function reset() { pending = 0; pk = ""; pv1 = ""; pv2 = ""; pv3 = "" }
        BEGIN { reset() }
        { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t)
          if (t == "") { reset(); next }
          if (substr(t,1,1) == "#") {
              if (t ~ /^#[ \t]*PHASE([ \t]|$)/) {
                  reset(); pending = 1
                  rest = t; sub(/^#[ \t]*PHASE[ \t]*/, "", rest)
                  n = split(rest, a, /[ \t]+/)
                  if (n >= 1 && a[1] !~ /^p[123]=/) pk = a[1]
                  for (i = 1; i <= n; i++) {
                      if      (a[i] ~ /^p1=/) pv1 = substr(a[i], 4)
                      else if (a[i] ~ /^p2=/) pv2 = substr(a[i], 4)
                      else if (a[i] ~ /^p3=/) pv3 = substr(a[i], 4)
                  }
              }
              next
          }
          if (substr(t,1,1) == "[") { reset(); next }
          eq = index(t, "="); if (eq == 0) { reset(); next }
          k = substr(t, 1, eq-1); sub(/[ \t]+$/, "", k)
          v = substr(t, eq+1)
          h = index(v, "#")
          trailing = (h > 0 && substr(v, h) ~ /PHASE/)
          if (pending || trailing) printf("%s\t%s\t%s\t%s\t%s\n", k, pk, pv1, pv2, pv3)
          reset() }
    ' "$1"
}

# Any key whose VALUE contains a '#'. AzerothCore keeps it as part of the value (see the
# header), so on every key but one this is a config line that is not doing what it reads
# like it does. AiPlayerbot.WorldBuffMatrix is the one legitimate exception at the pin --
# upstream's own default value is a '#'-separated list.
lint_midline_comments() { # <file>
    awk -v f="$1" '
        { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t)
          if (t == "" || substr(t,1,1) == "#" || substr(t,1,1) == "[") next
          eq = index(t, "="); if (eq == 0) next
          k = substr(t, 1, eq-1); sub(/[ \t]+$/, "", k)
          if (k == "AiPlayerbot.WorldBuffMatrix") next
          v = substr(t, eq+1)
          if (index(v, "#") > 0) printf("%s:%d: %s\n", f, FNR, substr(t, 1, 100)) }
    ' "$1"
}

# ------------------------------------------------------------------------------ preflight --
say ""
say "  phase $PHASE -- $PHASE_NAME, level cap $CAP"
say "  conf tree: $CONF_DIR"
say ""

declare -a TOUCHED_FILES=() REL_FILES=()
for entry in "${PHASE_KEYS[@]}"; do
    rel=${entry%%|*}
    f="$CONF_DIR/$rel"
    [[ -f $f ]] || die "missing conf file: $f
  Seed the conf tree from the image's .conf.dist files first -- bring-up.md 4.3. Note the
  filename: the server reads the un-suffixed .conf, and a missing MODULE conf is a silent
  failure (LoadModulesConfigs logs the miss and returns success, and every key in it falls
  back to its compiled-in default)."
    case " ${TOUCHED_FILES[*]-} " in *" $f "*) ;; *) TOUCHED_FILES+=("$f"); REL_FILES+=("$rel") ;; esac
done

# Refuse to run if a key the script expects is absent. A silently-skipped key is exactly
# the failure server-config.md 1 opens with.
missing=0
for entry in "${PHASE_KEYS[@]}"; do
    IFS='|' read -r rel key p1 p2 p3 <<<"$entry"
    if ! get_key "$CONF_DIR/$rel" "$key" >/dev/null; then
        printf 'phase.sh: key not found: %s in conf/%s\n' "$key" "$rel" >&2
        missing=1
    fi
done
[[ $missing -eq 0 ]] || die "refusing to run with keys missing. Re-seed that conf from the
image's .conf.dist and re-apply your edits; do not add the key by hand from memory."

# Marker cross-check, in BOTH directions and on the values too. Advisory -- this table, not
# the marker, decides what gets written -- but a disagreement between the two means one of
# conf/ and this script is lying about what the realm does, and you want to know which.
declare -A KNOWN=() TBL=() SEEN=()
for entry in "${PHASE_KEYS[@]}"; do
    IFS='|' read -r rel key p1 p2 p3 <<<"$entry"
    KNOWN["$rel|$key"]=1
    TBL["$rel|$key|1"]=$p1
    TBL["$rel|$key|2"]=$p2
    TBL["$rel|$key|3"]=$p3
done

for rel in "${REL_FILES[@]}"; do
    while IFS=$'\t' read -r mkey mname mv1 mv2 mv3; do
        [[ -n $mkey ]] || continue
        id="$rel|$mkey"

        if [[ -n $mname && $mname != "$mkey" ]]; then
            warn "conf/$rel: a '# PHASE $mname' marker sits directly above '$mkey'.
         The marker names the key it applies to; one of the two is wrong."
        fi

        if [[ -z ${KNOWN[$id]:-} ]]; then
            warn "conf/$rel: '$mkey' is marked PHASE but this script does not move it.
         Either it belongs in PHASE_KEYS here, or the marker is wrong. As it stands the
         key is frozen at whatever value the file holds, in every phase."
            continue
        fi
        SEEN["$id"]=1

        n=0
        for mv in "$mv1" "$mv2" "$mv3"; do
            n=$((n + 1))
            [[ -n $mv ]] || continue
            if [[ $mv != "${TBL["$id|$n"]}" ]]; then
                warn "conf/$rel: '$mkey' -- the marker says p$n=$mv, this script writes
         p$n=${TBL["$id|$n"]}. The script wins, so a flip to phase $n would silently
         contradict the conf's own documentation. Reconcile them before flipping."
            fi
        done
    done < <(marked_keys "$CONF_DIR/$rel")
done

for entry in "${PHASE_KEYS[@]}"; do
    IFS='|' read -r rel key p1 p2 p3 <<<"$entry"
    if [[ -z ${SEEN["$rel|$key"]:-} ]]; then
        warn "conf/$rel: '$key' is moved by this script but carries no PHASE marker.
         Add this line directly above it -- on its OWN line, never trailing:
             # PHASE  $key  p1=$p1  p2=$p2  p3=$p3"
    fi
done

# Invariants of the final decision, checked rather than assumed.
exp=$(get_key "$CONF_DIR/worldserver.conf" Expansion || echo '<absent>')
[[ $exp == 2 ]] || warn "conf/worldserver.conf: Expansion = $exp, expected 2.
         Expansion is phase-invariant on this realm and must be 2 in all three phases;
         every race and class is open from day one. Anything lower re-arms the
         account.expansion trap in server-config.md 1, and it is Reloadable::No, so
         nobody will notice until a restart."

for k in CharacterCreating.Disabled.RaceMask CharacterCreating.Disabled.ClassMask; do
    v=$(get_key "$CONF_DIR/worldserver.conf" "$k" || echo 0)
    [[ ${v:-0} == 0 ]] || warn "conf/worldserver.conf: $k = $v, expected 0.
         All races and classes are open from phase 1; nothing may gate character creation."
done

soap=$(get_key "$CONF_DIR/worldserver.conf" SOAP.Enabled || echo '<absent>')
[[ $soap == 1 ]] || warn "conf/worldserver.conf: SOAP.Enabled = $soap, expected 1.
         Without it this script has no way to announce or shut the server down, and
         neither does the weekly restart in hosting.md 7.6. (The comment block above the
         key in the .dist misspells it 'SOAP.Enable'; the key really is SOAP.Enabled.)"

ah=$(get_key "$CONF_DIR/modules/mod_ahbot.conf" AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled || echo '<absent>')
case "$ah" in
    true | 1) ;;
    *) warn "conf/modules/mod_ahbot.conf: EquipItemUseOrEquipLevelRestrict.Enabled = $ah.
         MaxLevel is only consulted when this is true, so the per-phase MaxLevel below is
         DEAD CONFIG and the level-60 auction house will list level-80 gear. This is a
         one-time install step, not a per-phase one -- server-config.md 1, phase 1." ;;
esac

# -------------------------------------------------------------------------------- rewrite --
umask 022
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT

declare -a CHANGED=()
hoist_notes=$WORK/hoists
: >"$hoist_notes"

# Flatten conf/modules/playerbots.conf -> modules__playerbots.conf, so two files with the
# same basename in different directories can never collide in the work tree.
workname() { local p=${1#"$CONF_DIR"/}; printf '%s' "$WORK/${p//\//__}"; }

for f in "${TOUCHED_FILES[@]}"; do
    cp -- "$f" "$(workname "$f")"
done

for entry in "${PHASE_KEYS[@]}"; do
    IFS='|' read -r rel key p1 p2 p3 <<<"$entry"
    case "$PHASE" in 1) val=$p1 ;; 2) val=$p2 ;; 3) val=$p3 ;; esac
    tmp=$(workname "$CONF_DIR/$rel")
    out="$tmp.next"
    rc=0
    rewrite_key "$tmp" "$key" "$val" >"$out" 2>>"$hoist_notes" || rc=$?
    case "$rc" in
        0) ;;
        3) die "internal: key '$key' vanished from conf/$rel between preflight and rewrite" ;;
        4) die "conf/$rel defines '$key' more than once. AzerothCore's parser rejects the
  duplicate with 'Duplicate key name' and keeps the FIRST occurrence, which is almost
  never the one you edited. Delete the extra line and re-run." ;;
        *) die "awk failed rewriting '$key' in conf/$rel (exit $rc)" ;;
    esac
    mv -- "$out" "$tmp"
done

if [[ -s $hoist_notes ]]; then
    say "  HOISTED trailing comments off key lines (they would have been parsed as part of"
    say "  the VALUE and silently reverted the key to its compiled-in default):"
    sed 's/^HOISTED\t/    /; s/\t/   <- /' "$hoist_notes" | sed 's/^/  /'
    say ""
fi

for f in "${TOUCHED_FILES[@]}"; do
    w=$(workname "$f")
    if ! diff -q -- "$f" "$w" >/dev/null; then
        CHANGED+=("$f")
        diff -u --label "a/${f#"$REPO_ROOT"/}" --label "b/${f#"$REPO_ROOT"/}" -- "$f" "$w" || true
    fi
done

if [[ ${#CHANGED[@]} -eq 0 ]]; then
    say "  No conf changes: the tree is already at phase $PHASE."
else
    say ""
    say "  ${#CHANGED[@]} file(s) would change."
fi

# Report on the mid-line-comment lint over the files we own, before anything is written.
lint_out=$WORK/lint
: >"$lint_out"
for f in "${TOUCHED_FILES[@]}"; do lint_midline_comments "$f" >>"$lint_out"; done
if [[ -s $lint_out ]]; then
    say ""
    warn "these lines put a '#' inside a VALUE. AzerothCore only strips '#' at the start of
         a line, so everything after '=' -- comment included -- IS the value, and an
         integer key with a trailing comment silently reverts to its compiled-in default:"
    sed 's/^/         /' "$lint_out" >&2
fi

if [[ $WARNINGS -gt 0 ]]; then
    say ""
    say "  $WARNINGS warning(s) above. None of them stops the flip; all of them mean"
    say "  something will not do what the conf says it does."
fi

if [[ $DRY_RUN -eq 1 ]]; then
    say ""
    say "  --dry-run: nothing written, nothing restarted."
    exit 0
fi

# -------------------------------------------------------------------------------- confirm --
say ""
say "  ABOUT TO:"
if [[ ${#CHANGED[@]} -gt 0 ]]; then
    say "    - rewrite ${#CHANGED[@]} conf file(s) in $CONF_DIR"
fi
if [[ $DO_RESTART -eq 1 ]]; then
    say "    - announce phase $PHASE in-game and run '.server shutdown $SHUTDOWN_DELAY' over SOAP"
    say "    - wait for worldserver to exit, then 'docker compose up -d'"
    say "    - players online get a ${SHUTDOWN_DELAY}s countdown and are saved on the way down"
else
    say "    - NOT restart (--no-restart). The running server keeps its old config until you do."
fi
say ""

if [[ $ASSUME_YES -ne 1 ]]; then
    reply=
    # `|| true`: read returns 1 at EOF, which under `set -e` would abort silently.
    read -r -p "Type yes to proceed: " reply || true
    [[ $reply == yes ]] || { say "aborted."; exit 1; }
fi

# ---------------------------------------------------------------------------------- apply --
# Truncate in place with `>`, never `mv` a temp file over the original. conf/worldserver.conf
# is bind-mounted into the container as a FILE, and a bind-mounted file follows the inode:
# a rename would leave a running container attached to the old, now-orphaned inode. The
# restart below re-resolves the path either way, but the repo file and the mount must not
# be allowed to diverge in between.
for f in "${CHANGED[@]}"; do
    cat -- "$(workname "$f")" >"$f"
    say "  wrote ${f#"$REPO_ROOT"/}"
done

if [[ ${#CHANGED[@]} -gt 0 ]]; then
    say ""
    say "  Commit this. conf/ is the source of truth for what the running server is"
    say "  configured with -- that is the whole reason it is bind-mounted from the repo:"
    say "      git -C $REPO_ROOT add conf && git -C $REPO_ROOT commit -m 'phase $PHASE: cap $CAP'"
fi

# ------------------------------------------------------------------ account.expansion check --
# Not a per-phase step any more (see the header). Still worth counting every flip: an
# account below 2 is a player who silently cannot enter Outland, cannot enter Northrend,
# and cannot create a Blood Elf, on a realm where all three are supposed to work.
cd "$DEPLOY" || die "no compose project directory at $DEPLOY"
mysql_cid=$(docker compose ps -q mysql 2>/dev/null || true)
if [[ -f $DEPLOY/mysql-backup.cnf && -n $mysql_cid ]]; then
    stale=$(docker compose exec -T mysql \
        mysql --defaults-extra-file=/etc/mysql/backup.cnf -N -B acore_auth \
        -e "SELECT COUNT(*) FROM account WHERE expansion <> 2;" 2>/dev/null | tr -d '\r' || echo '')
    if [[ -n $stale && $stale != 0 ]]; then
        if [[ $FIX_EXPANSION -eq 1 ]]; then
            say "  repairing $stale account(s) below expansion = 2"
            docker compose exec -T mysql \
                mysql --defaults-extra-file=/etc/mysql/backup.cnf acore_auth \
                -e "UPDATE account SET expansion = 2 WHERE expansion <> 2;"
        else
            warn "$stale account(s) in acore_auth have expansion < 2. They cannot reach
         Outland or Northrend and cannot create a Blood Elf, whatever the cap says.
         This is NOT a per-phase step -- accounts should be stamped 2 at creation -- but
         it is repairable:   scripts/phase.sh --fix-expansion $PHASE"
        fi
    elif [[ -n $stale ]]; then
        say "  acore_auth: all accounts at expansion = 2"
    fi
else
    say "  (skipping the account.expansion check: mysql is not up, or deploy/mysql-backup.cnf"
    say "   is missing. scripts/backup.sh writes that file.)"
fi

if [[ $DO_RESTART -ne 1 ]]; then
    say ""
    say "  Confs written, nothing restarted. MaxPlayerLevel is Reloadable::No, so the"
    say "  running server is STILL on the old cap until you restart it:"
    say "      scripts/soap-cmd.sh \"server shutdown $SHUTDOWN_DELAY\" && cd $DEPLOY && docker compose up -d"
    exit 0
fi

# ------------------------------------------------------------------- announce and shut down --
announce="Phase $PHASE ($PHASE_NAME) opens after this restart. Level cap is now $CAP. Back in a few minutes."
if "$SCRIPT_DIR/soap-cmd.sh" "announce $announce"; then
    say "  announced"
else
    warn "could not announce over SOAP (see above). Falling back to a plain container stop."
fi

stopped=0
if "$SCRIPT_DIR/soap-cmd.sh" "server shutdown $SHUTDOWN_DELAY"; then
    say "  countdown running: ${SHUTDOWN_DELAY}s. Players see an in-game timer; characters"
    say "  are saved on the way down. Exit code 0 under 'restart: on-failure' means the"
    say "  container stays down afterwards, which is what we want."
    cid=$(docker compose ps -aq worldserver 2>/dev/null || true)
    if [[ -n $cid ]]; then
        deadline=$((SECONDS + SHUTDOWN_DELAY + 180))
        while ((SECONDS < deadline)); do
            running=$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null || echo false)
            [[ $running == true ]] || { stopped=1; break; }
            sleep 5
        done
    fi
    if [[ $stopped -eq 1 ]]; then say "  worldserver exited"; fi
fi

if [[ $stopped -ne 1 ]]; then
    warn "worldserver did not exit on its own. Stopping the containers directly.
         SIGTERM is handled -- it calls World::StopNow(0), a clean save-and-exit -- and
         stop_grace_period is 6m in the compose file, so this does not cut a save short."
    docker compose stop worldserver authserver
fi

# ---------------------------------------------------------------------------------- restart --
say "  docker compose up -d"
docker compose up -d

# ------------------------------------------------------------------------------- verify ----
case "$PHASE" in 1) RDF_VAL=0 ;; 2) RDF_VAL=1 ;; 3) RDF_VAL=2 ;; esac
OLD_CAP=$((CAP - 10))
cat <<EOF

  UP. First boot after a flip is quick (populate is skipped once the schemas are
  non-empty), but give it a couple of minutes.

      docker compose logs -f worldserver | grep -Ei 'World Initialized|ready\.\.\.|cannot be changed by reload|Invalid value|Missing name'

  VERIFICATION CHECKLIST -- each line catches a different failure. Do them in order.

    1. config loaded    no 'Missing name' / 'Invalid value' lines for the keys above, and
                        no 'cannot be changed by reload' (you restarted, so there should
                        be none)
    2. cap moved        on a throwaway char at the old cap, kill something: the XP bar
                        advances past $OLD_CAP
    3. session expansion  log in a PRE-EXISTING account and type .account -- it must read
                        expansion 2. It is 2 in every phase on this realm.
    4. map access       walk a real character through the Dark Portal: no "you must have
                        The Burning Crusade" transfer abort (this works in phase 1 too --
                        gating is the cap, not the zone)
    5. race/class       character create screen offers Blood Elf, Draenei and Death Knight
    6. RDF              open Dungeon Finder AT THE CAP: a random dungeon is offered and
                        queueable. THIS IS THE ONE THAT FAILS QUIETLY. Do not skip it.
                        RDF.Expansion is now $RDF_VAL.
    7. bots followed    .playerbots bot list, check a level -- bots exist above the old cap
                        after a randomize cycle (the floor on that timer is
                        AiPlayerbot.MinRandomBotRandomizeTime = 7200s, so give it hours,
                        not minutes)
    8. auction house    an AH listing at the cap is not full of level-80 gear

  Then commit conf/ if you have not: the repo is what says how the realm is configured.
EOF
