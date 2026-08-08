#!/usr/bin/env bash
#
# scripts/soap-cmd.sh -- run ONE GM command on the running worldserver, over SOAP.
#
#   usage: soap-cmd.sh <gm-command-without-the-leading-dot>
#
# Why this exists: AzerothCore builds no `worldserver-cli`. `src/server/apps/` contains
# exactly two targets, authserver and worldserver, so the only two channels into a running
# server are the worldserver's own stdin (`docker attach`, a shared interactive TTY that a
# stray Ctrl-C shuts down) and SOAP. Cron gets SOAP.  docs/hosting.md 7.2, 7.6.
#
# Contract (docs/hosting.md 7.6):
#   - The command goes VERBATIM into the <command> element, which is written dot-less:
#         soap-cmd.sh "server restart 300"      not   ".server restart 300"
#     A leading '.' or '!' is stripped here anyway, with a note, because it is a very easy
#     mistake to make. It would in fact have worked: SOAP commands are dispatched through
#     World::ProcessCliCommands -> CliHandler::ParseCommands, which does
#         if (str[0] == '.' || str[0] == '!') str = str.substr(1);
#     (Chat.cpp:987 @ CORE_SHA 092e9ba6, verified 2026-08-08). hosting.md 7.6 says the
#     console is "the one place the dot is optional"; it is optional here too, same handler.
#     Nothing depends on that, so keep typing it dot-less.
#   - Credentials come from deploy/.env: AC_SOAP_USER / AC_SOAP_PASS. Those are TWO KEYS
#     BEYOND the set deploy/.env.example currently carries -- bring-up.md 5.1 owns that
#     file; SOAP is the only thing that needs them.
#   - POSTs to http://127.0.0.1:7878/. Host loopback reaches the container because
#     deploy/docker-compose.yml publishes "127.0.0.1:7878:7878", so this runs from host
#     cron with no `docker compose exec` -- just as well, the runtime image has no curl.
#
# The account named by AC_SOAP_USER must be SEC_ADMINISTRATOR (gmlevel 3) with a row in
# account_access at RealmID = -1. From ACSoap.cpp @ CORE_SHA 092e9ba6:
#     no/blank credentials            -> 401
#     unknown username, bad password  -> 401
#     GetSecurity(accountId) < SEC_ADMINISTRATOR -> 403
#   AC> .account set gmlevel <account> 3 -1        (bring-up.md 7.2)
#
# DEVIATION from the hosting.md 7.2 snippet, deliberate, two of them:
#   1. The password is NOT passed as `-u user:pass`. Everything else in this doc set
#      refuses to put a credential in argv because container and host processes are both
#      visible in `ps`; there is no reason for SOAP to be the exception. curl reads it from
#      a config file on stdin instead, so it never touches argv and never touches disk.
#      Consequence: AC_SOAP_PASS must not contain whitespace or a leading '#'. Generate it
#      the way deploy/.env.example generates the other two secrets ([A-Za-z0-9] only) and
#      that constraint costs nothing.
#   2. Content-Type is `text/xml`, not `application/xml`. text/xml is what SOAP 1.1
#      mandates and what gSOAP itself emits; application/xml is not wrong on the wire but
#      it is the untested one.
#
set -euo pipefail

usage() {
    cat <<'EOF'
usage: soap-cmd.sh <gm-command>        the command WITHOUT its leading dot

  soap-cmd.sh "server restart 300"                 # the weekly restart, hosting.md 7.6
  soap-cmd.sh "server shutdown 300"                # graceful; exit 0, stays down
  soap-cmd.sh "announce Server restarting in 5m."
  soap-cmd.sh server info                          # unquoted works too; args are joined

Reads AC_SOAP_USER / AC_SOAP_PASS from deploy/.env.

Environment overrides:
  DEPLOY        compose project dir      (default: <repo>/deploy)
  ENV_FILE      env file                 (default: $DEPLOY/.env)
  SOAP_URL      endpoint                 (default: http://127.0.0.1:7878/)
  SOAP_TIMEOUT  curl --max-time, seconds (default: 60)

Exit status: 0 command ran; 1 transport/auth/fault; 2 usage.
EOF
}

case "${1-}" in
    -h | --help) usage; exit 0 ;;
    '') usage >&2; exit 2 ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
DEPLOY=${DEPLOY:-$REPO_ROOT/deploy}
ENV_FILE=${ENV_FILE:-$DEPLOY/.env}

if [[ ! -f $ENV_FILE ]]; then
    echo "soap-cmd.sh: $ENV_FILE not found. Copy deploy/.env.example to deploy/.env," >&2
    echo "             chmod 600 it, and add AC_SOAP_USER / AC_SOAP_PASS." >&2
    exit 1
fi

# Same `set -a; . file; set +a` idiom scripts/backup.sh uses, and the same caveat: this
# file is read by TWO parsers, Compose's .env reader and sh. They agree only on plain
# KEY=value -- no quotes, no `export`, no spaces around '=', no shell expansions.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${AC_SOAP_USER:?not set in $ENV_FILE (the gmlevel-3 account SOAP authenticates as)}"
: "${AC_SOAP_PASS:?not set in $ENV_FILE (password for AC_SOAP_USER)}"

SOAP_URL=${SOAP_URL:-http://127.0.0.1:7878/}
SOAP_TIMEOUT=${SOAP_TIMEOUT:-60}

# ---------------------------------------------------------------------------- command --
cmd="$*"
cmd=${cmd#"${cmd%%[![:space:]]*}"}   # ltrim
cmd=${cmd%"${cmd##*[![:space:]]}"}   # rtrim

if [[ $cmd == .* || $cmd == '!'* ]]; then
    echo "soap-cmd.sh: stripping the leading '${cmd:0:1}' -- SOAP takes the command dot-less." >&2
    cmd=${cmd#?}
    cmd=${cmd#"${cmd%%[![:space:]]*}"}
fi

if [[ -z $cmd ]]; then
    echo "soap-cmd.sh: empty command." >&2
    usage >&2
    exit 2
fi

xml_escape() {
    local s=$1
    # The backslashes are load-bearing. Bash 5.2 enables `patsub_replacement` by default,
    # which makes an UNQUOTED '&' in a ${var//pat/rep} replacement expand to the matched
    # text -- so `${s//</&lt;}` turns "<" into "<lt;" and silently corrupts the envelope
    # for any command containing '<' or '&' (`.announce Kara & ICC`, say). Backslash-quoting
    # it is correct on bash 5.1 too, where quote removal just drops the backslash.
    s=${s//&/\&amp;}    # must be first, or it would re-escape the escapes below
    s=${s//</\&lt;}
    s=${s//>/\&gt;}
    printf '%s' "$s"
}

xml_unescape() {
    sed -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&quot;/"/g' -e "s/&apos;/'/g" -e 's/&amp;/\&/g'
}

# ns1 = "urn:AC" is not decorative: it is the prefix gSOAP's namespace table binds, and
# the stub is `int ns1__executeCommand(char* command, char** result);`. Get the namespace
# wrong and the request parses but dispatches to nothing.  ACSoap.cpp, deps/gsoap/gsoap.stub
envelope="<?xml version=\"1.0\" encoding=\"utf-8\"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:ns1=\"urn:AC\">
  <SOAP-ENV:Body>
    <ns1:executeCommand>
      <command>$(xml_escape "$cmd")</command>
    </ns1:executeCommand>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"

# ------------------------------------------------------------------------------- POST --
umask 077
body=$(mktemp) || exit 1
out=$(mktemp) || exit 1
trap 'rm -f -- "$body" "$out"' EXIT
printf '%s\n' "$envelope" >"$body"

set +e
http=$(
    printf 'user = %s:%s\n' "$AC_SOAP_USER" "$AC_SOAP_PASS" |
        curl --silent --show-error \
            --config - \
            --request POST \
            --header 'Content-Type: text/xml; charset=utf-8' \
            --data-binary "@$body" \
            --max-time "$SOAP_TIMEOUT" \
            --output "$out" \
            --write-out '%{http_code}' \
            "$SOAP_URL"
)
curl_rc=$?
set -e

if [[ $curl_rc -ne 0 ]]; then
    echo "soap-cmd.sh: could not reach $SOAP_URL (curl exit $curl_rc)." >&2
    echo "  - is worldserver up?            cd $DEPLOY && docker compose ps" >&2
    echo "  - is SOAP on?                   SOAP.Enabled = 1 in conf/worldserver.conf" >&2
    echo "    (it ships 0, and note the comment block above the key misspells it" >&2
    echo "     'SOAP.Enable' -- the key really is SOAP.Enabled)" >&2
    echo "  - is the port published?        \"127.0.0.1:7878:7878\" in docker-compose.yml" >&2
    exit 1
fi

extract() { # <tagname> -- pull one element's text out of the response
    tr '\n' '\002' <"$out" |
        sed -n "s|.*<$1[^>]*>\(.*\)</$1>.*|\1|p" |
        tr '\002' '\n' |
        xml_unescape
}

case "$http" in
    200)
        result=$(extract result)
        if [[ -n $result ]]; then printf '%s\n' "$result"; fi
        exit 0
        ;;
    401)
        echo "soap-cmd.sh: 401 -- AC_SOAP_USER '$AC_SOAP_USER' is unknown, or the password is wrong." >&2
        echo "  AzerothCore upper-cases BOTH username and password before hashing" >&2
        echo "  (Utf8ToUpperOnlyLatin in AccountMgr), so passwords are case-insensitive," >&2
        echo "  but a stray space in deploy/.env is not." >&2
        exit 1
        ;;
    403)
        echo "soap-cmd.sh: 403 -- '$AC_SOAP_USER' exists but its gmlevel is below 3." >&2
        echo "  ACSoap.cpp: if (AccountMgr::GetSecurity(accountId) < SEC_ADMINISTRATOR) return 403;" >&2
        echo "  Fix from the console:  docker attach wowserver-worldserver-1" >&2
        echo "                         AC> .account set gmlevel $AC_SOAP_USER 3 -1" >&2
        echo "                         (detach with Ctrl-P Ctrl-Q, NOT Ctrl-C)" >&2
        exit 1
        ;;
    500)
        fault=$(extract faultstring)
        echo "soap-cmd.sh: SOAP fault running '.$cmd'" >&2
        printf '%s\n' "${fault:-$(cat "$out")}" >&2
        exit 1
        ;;
    *)
        echo "soap-cmd.sh: unexpected HTTP $http from $SOAP_URL" >&2
        cat "$out" >&2
        exit 1
        ;;
esac
