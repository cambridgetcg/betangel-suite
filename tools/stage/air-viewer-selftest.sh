#!/bin/sh
# tools/stage/air-viewer-selftest.sh: on the Air, right after the viewer key is installed on the lab,
# try each thing the key must NOT be able to do (docs/DESIGN.md 8.6 item 2) and report each one as
# refused or ALLOWED, then an overall verdict. Step by step: tools/stage/README.md, step 6.
#
# Yu runs it in Terminal on the Air (Nuance may start it, but only Yu types the key's passphrase):
#     sh air-viewer-selftest.sh              five SSH logins: type the passphrase at each prompt
#     sh air-viewer-selftest.sh --keep-logs  also keep the ssh -v logs (host, user and key path; no secrets)
#
# It uses only the "lab-suite" Host of ~/.ssh/config (tools/stage/air-ssh-config.snippet) and refuses to
# start unless `ssh -G lab-suite` shows that block, public-key-only authentication, connection sharing
# (ControlMaster, ControlPath, ControlPersist), the agent, proxies and LocalCommand included. Run it while no `ssh lab-suite` viewer session is open:
# the Host's LocalForward needs port 8765 on the Air.
#
# No probe starts an engine on the lab: probes 3-9 open no session at all (-N, -W), and probes 1-2 send a
# command, which the forced command (bin/suite ssh-session) refuses (refused:ssh_original_command).
#   1  a requested command           ssh lab-suite 'echo <marker>'
#   2  a PTY                         ssh -tt lab-suite 'echo <marker>'
#   3  -L to another port            -L 127.0.0.1:<p>:127.0.0.1:22
#   4  -L to another host            -L 127.0.0.1:<p>:192.168.50.88:22
#   5  -L to another name            -L 127.0.0.1:<p>:localhost:8765 (permitopen names 127.0.0.1 only)
#   6  -L to a Unix socket           -L 127.0.0.1:<p>:/tmp/suite-selftest-<n>.sock
#   7  -W host:22                    -W 127.0.0.1:22
#   8  -R TCP                        -R 127.0.0.1:0:127.0.0.1:9
#   9  -R Unix socket                -R /tmp/suite-selftest-<n>.sock:127.0.0.1:9
# Probes 3-6 share one login and probes 8-9 another. A probe counts as refused only with evidence: the
# login used the viewer key (ssh -v shows "Server accepts key: ...id_ed25519_lab_suite") and the lab's
# refusal was seen (refused:ssh_original_command, "PTY allocation request failed", "administratively
# prohibited", "stdio forwarding failed", "remote port forwarding failed").
#
# Verdict and exit status: PASS (0) only if all nine were refused. FAIL (1) if anything was ALLOWED: then
# remove the key at once (on the lab: sh suite-viewer-setup.sh --undo) and tell lab-Claude. INCONCLUSIVE
# (3) if a probe could not tell (no login, a timeout, an unknown answer). Refused to start (2).
#
# SELFTEST_AUTH_TIMEOUT (default 180 s, to type the passphrase and log in) and SELFTEST_STEP_TIMEOUT
# (default 15 s per probe after login) may be set in the environment; tests/test_stage.py sets them low.

set -u

HOST=lab-suite
LAB_IP=192.168.50.88
KEY_NAME=id_ed25519_lab_suite
VIEWER_PORT=8765
AUTH_TIMEOUT=${SELFTEST_AUTH_TIMEOUT:-180}
STEP_TIMEOUT=${SELFTEST_STEP_TIMEOUT:-15}
KEEP_LOGS=0
WORK=
SSH_PID=

refuse() {
    printf 'refused:%s\n' "$1" >&2
    if [ $# -ge 2 ]; then printf '  %s\n' "$2" >&2; fi
    exit 2
}

for arg in "$@"; do
    case "$arg" in
        --keep-logs) KEEP_LOGS=1 ;;
        *) refuse usage "usage: sh air-viewer-selftest.sh [--keep-logs]" ;;
    esac
done
for value in "$AUTH_TIMEOUT" "$STEP_TIMEOUT"; do
    case "$value" in ''|*[!0-9]*) refuse usage "SELFTEST_AUTH_TIMEOUT and SELFTEST_STEP_TIMEOUT are whole seconds" ;; esac
done

stop_ssh() {
    if [ -n "$SSH_PID" ]; then
        kill "$SSH_PID" 2>/dev/null
        wait "$SSH_PID" 2>/dev/null
        SSH_PID=
    fi
}

on_exit() {
    oe_status=$?
    trap - EXIT INT TERM HUP
    stop_ssh
    if [ -n "$WORK" ]; then
        if [ "$KEEP_LOGS" = 1 ]; then printf 'logs kept in %s\n' "$WORK"; else rm -rf "$WORK"; fi
    fi
    exit "$oe_status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# --- preflight -------------------------------------------------------------------------------------

command -v ssh >/dev/null 2>&1 || refuse no_ssh "ssh is not on PATH"
command -v nc >/dev/null 2>&1 || refuse no_nc "nc is not on PATH"
CFG=$(ssh -G "$HOST" 2>/dev/null | awk '{ $1 = tolower($1); print }') || CFG=
if [ -z "$CFG" ]; then refuse air_config_unreadable "ssh -G $HOST failed"; fi

cfg_has() {                 # cfg_has KEY VALUE...: the Host's KEY is one of the VALUEs
    ch_key=$1
    shift
    ch_got=$(printf '%s\n' "$CFG" | awk -v k="$ch_key" '$1 == k { $1 = ""; sub(/^ /, ""); print }')
    for ch_want in "$@"; do
        if [ "$ch_got" = "$ch_want" ]; then return 0; fi
    done
    return 1
}

CONFIG_HINT="put the lab-suite block (tools/stage/air-ssh-config.snippet) at the TOP of ~/.ssh/config: ssh keeps the first value it reads"
cfg_has hostname "$LAB_IP" || refuse air_config_hostname "$CONFIG_HINT"
cfg_has user user || refuse air_config_user "$CONFIG_HINT"
cfg_has addressfamily inet || refuse air_config_addressfamily "$CONFIG_HINT"
cfg_has identitiesonly yes true || refuse air_config_identitiesonly "$CONFIG_HINT"
cfg_has addkeystoagent no false || refuse air_config_addkeystoagent "$CONFIG_HINT"
cfg_has exitonforwardfailure yes true || refuse air_config_exitonforwardfailure "$CONFIG_HINT"
cfg_has stricthostkeychecking yes true || refuse air_config_stricthostkeychecking "$CONFIG_HINT"
cfg_has localforward "[127.0.0.1]:$VIEWER_PORT [127.0.0.1]:$VIEWER_PORT" "127.0.0.1:$VIEWER_PORT 127.0.0.1:$VIEWER_PORT" ||
    refuse air_config_localforward "$CONFIG_HINT"
# Public-key login only: the lab's sshd still takes passwords, so a refused viewer key would otherwise end at a
# Password: prompt, and the lab password typed there would open a full shell with no forced command.
cfg_has preferredauthentications publickey || refuse air_config_auth "$CONFIG_HINT"
cfg_has passwordauthentication no false || refuse air_config_auth "$CONFIG_HINT"
cfg_has kbdinteractiveauthentication no false || refuse air_config_auth "$CONFIG_HINT"
# No shared connection and no agent: a master connection left by `ssh lab-suite` (ControlMaster/ControlPersist
# from a later Host * block) would let any process on the Air open sessions through it without the passphrase,
# and an agent could sign with a copy of the key. ssh -G prints no controlpath, proxycommand or proxyjump line
# once the block sets them to none.
cfg_has controlmaster false no || refuse air_config_controlmaster "$CONFIG_HINT"
cfg_has controlpersist no false || refuse air_config_controlpersist "$CONFIG_HINT"
cfg_has controlpath "" none || refuse air_config_controlpath "$CONFIG_HINT"
cfg_has identityagent none || refuse air_config_identityagent "$CONFIG_HINT"
cfg_has proxycommand "" none || refuse air_config_proxy "$CONFIG_HINT"
cfg_has proxyjump "" none || refuse air_config_proxy "$CONFIG_HINT"
cfg_has permitlocalcommand no false || refuse air_config_permitlocalcommand "$CONFIG_HINT"
IDENTITIES=$(printf '%s\n' "$CFG" | awk '$1 == "identityfile" { $1 = ""; sub(/^ /, ""); print }')
case "$IDENTITIES" in
    *"
"*) refuse air_config_identityfile "lab-suite must offer one key only, ~/.ssh/$KEY_NAME: $CONFIG_HINT" ;;
    "~/.ssh/$KEY_NAME") KEY_PATH="$HOME/.ssh/$KEY_NAME" ;;
    */"$KEY_NAME") KEY_PATH=$IDENTITIES ;;
    *) refuse air_config_identityfile "lab-suite must offer one key only, ~/.ssh/$KEY_NAME: $CONFIG_HINT" ;;
esac
if [ ! -f "$KEY_PATH" ]; then refuse key_missing "no $KEY_PATH: make the key first (README step 2)"; fi
if nc -z -w 2 127.0.0.1 "$VIEWER_PORT" >/dev/null 2>&1; then
    refuse viewer_port_busy "port $VIEWER_PORT is in use on this Mac: close the viewer session (ssh lab-suite) first"
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/air-viewer-selftest.XXXXXX") || WORK=
if [ -z "$WORK" ]; then refuse workdir "cannot make a temporary directory"; fi
MARK="suite-selftest-$$-$(date +%s)"
SOCK="/tmp/suite-selftest-$$.sock"
printf 'SUITE-SELFTEST\r\n' > "$WORK/hello"
: > "$WORK/results"

# --- helpers ---------------------------------------------------------------------------------------

now() { date +%s; }

wait_until() {              # wait_until SECONDS COMMAND...: poll every 0.1 s until COMMAND succeeds
    wu_end=$(( $(now) + $1 ))
    shift
    while :; do
        if "$@"; then return 0; fi
        if [ "$(now)" -ge "$wu_end" ]; then return 1; fi
        sleep 0.1
    done
}

running() { [ -n "$SSH_PID" ] && kill -0 "$SSH_PID" 2>/dev/null; }
exited() { ! running; }
log_has() { grep -qF -- "$2" "$WORK/$1.log"; }

authed() {                  # authed NAME: the login succeeded with the viewer key and no other key
    { grep -F 'Server accepts key: ' "$WORK/$1.log" | grep -qF "/$KEY_NAME " ||
        grep -F 'Trying private key: ' "$WORK/$1.log" | grep -qF "/$KEY_NAME"; } || return 1
    if grep -F 'Server accepts key: ' "$WORK/$1.log" | grep -vqF "/$KEY_NAME "; then return 1; fi
    log_has "$1" 'Authenticated to ' || log_has "$1" 'Authentication succeeded'
}

record() {                  # record STATUS NUMBER ITEM [DETAIL]
    printf '%s|%s|%s|%s\n' "$1" "$2" "$3" "${4:-}" >> "$WORK/results"
    printf '  %-8s %s %s%s\n' "$1" "$2" "$3" "${4:+  ($4)}"
}

start_ssh() {               # start_ssh NAME STDIN ARGS...: ssh in the background, logging to WORK/NAME.*
    ss_name=$1
    ss_in=$2
    shift 2
    : > "$WORK/$ss_name.log"
    ssh -v -E "$WORK/$ss_name.log" "$@" < "$ss_in" > "$WORK/$ss_name.out" 2> "$WORK/$ss_name.err" &
    SSH_PID=$!
}

lines_of() { wc -l < "$WORK/$1.log" | tr -d ' '; }
since() { tail -n "+$(( $2 + 1 ))" "$WORK/$1.log"; }

# --- 1 and 2: sessions with a command --------------------------------------------------------------

probe_session() {           # probe_session NAME NUMBER ITEM SSH-OPTION
    printf 'probe %s: %s (type the passphrase when asked)\n' "$2" "$3"
    start_ssh "$1" /dev/null "$4" "$HOST" "echo $MARK"
    if ! wait_until $(( AUTH_TIMEOUT + STEP_TIMEOUT )) exited; then
        stop_ssh
        if grep -qF -- "$MARK" "$WORK/$1.out"; then record ALLOWED "$2" "$3" "the command ran"; return; fi
        record unclear "$2" "$3" "still running after $(( AUTH_TIMEOUT + STEP_TIMEOUT )) s"
        return
    fi
    wait "$SSH_PID" 2>/dev/null
    SSH_PID=
    if grep -qF -- "$MARK" "$WORK/$1.out"; then record ALLOWED "$2" "$3" "the command ran"; return; fi
    if grep -qF 'http://127.0.0.1' "$WORK/$1.out"; then record ALLOWED "$2" "$3" "a viewer URL was printed"; return; fi
    if ! authed "$1"; then record unclear "$2" "$3" "no login with the viewer key"; return; fi
    if [ "$1" = pty ]; then
        if log_has pty 'PTY allocation request failed'; then record refused "$2" "$3"
        else record ALLOWED "$2" "$3" "a PTY was granted"; fi
        return
    fi
    if grep -qF 'refused:ssh_original_command' "$WORK/$1.err"; then record refused "$2" "$3"
    else record unclear "$2" "$3" "no refused:ssh_original_command from the lab"; fi
}

# --- 3 to 6: local forwards, one login -------------------------------------------------------------

free_port() {               # the first port from $1 up that nothing listens on
    fp_port=$1
    while nc -z -w 1 127.0.0.1 "$fp_port" >/dev/null 2>&1; do fp_port=$(( fp_port + 1 )); done
    echo "$fp_port"
}

all_listening() {
    for al_port in $P3 $P4 $P5 $P6; do
        log_has local "listening on 127.0.0.1 port $al_port" || return 1
    done
}

forward_listening_or_gone() { all_listening || exited; }

local_decided() {           # a probe's answer has arrived (in the log since $LD_MARK, or as reply bytes)
    since local "$LD_MARK" | grep -qF -e 'open failed' -e 'administratively prohibited' && return 0
    [ -s "$WORK/reply" ]
}

probe_local() {             # probe_local NUMBER ITEM PORT
    LD_MARK=$(lines_of local)
    : > "$WORK/reply"
    nc -w 5 127.0.0.1 "$3" < "$WORK/hello" 2>/dev/null | head -c 64 > "$WORK/reply"
    wait_until "$STEP_TIMEOUT" local_decided
    pl_new=$(since local "$LD_MARK")
    case "$pl_new" in
        *'administratively prohibited'*) record refused "$1" "$2" ;;
        *'open failed: connect failed'*) record ALLOWED "$1" "$2" "the lab tried to connect" ;;
        *) if [ -s "$WORK/reply" ]; then record ALLOWED "$1" "$2" "bytes came back"
           else record unclear "$1" "$2" "no answer within $STEP_TIMEOUT s"; fi ;;
    esac
}

probe_local_forwards() {
    P3=$(free_port 47110)
    P4=$(free_port $(( P3 + 1 )))
    P5=$(free_port $(( P4 + 1 )))
    P6=$(free_port $(( P5 + 1 )))
    printf 'probe 3-6: -L forwards to other places (type the passphrase when asked)\n'
    start_ssh local /dev/null -N -o ExitOnForwardFailure=yes \
        -L "127.0.0.1:$P3:127.0.0.1:22" -L "127.0.0.1:$P4:$LAB_IP:22" \
        -L "127.0.0.1:$P5:localhost:$VIEWER_PORT" -L "127.0.0.1:$P6:$SOCK" "$HOST"
    wait_until $(( AUTH_TIMEOUT + STEP_TIMEOUT )) forward_listening_or_gone
    if ! running || ! authed local || ! all_listening; then
        pf_why="no login with the viewer key"
        if authed local; then pf_why="the forwards did not start"; fi
        stop_ssh
        for pf_item in "3|-L to another port" "4|-L to another host" "5|-L to another name" "6|-L to a Unix socket"; do
            record unclear "${pf_item%%|*}" "${pf_item#*|}" "$pf_why"
        done
        return
    fi
    probe_local 3 "-L to another port" "$P3"
    probe_local 4 "-L to another host" "$P4"
    probe_local 5 "-L to another name" "$P5"
    probe_local 6 "-L to a Unix socket" "$P6"
    stop_ssh
}

# --- 7: -W ---------------------------------------------------------------------------------------

probe_stdio() {
    printf 'probe 7: -W 127.0.0.1:22 (type the passphrase when asked)\n'
    start_ssh stdio "$WORK/hello" -W 127.0.0.1:22 "$HOST"
    if ! wait_until $(( AUTH_TIMEOUT + STEP_TIMEOUT )) exited; then stop_ssh; fi
    wait "$SSH_PID" 2>/dev/null
    SSH_PID=
    if grep -q '^SSH-' "$WORK/stdio.out"; then record ALLOWED 7 "-W host:22" "the lab's sshd answered"; return; fi
    if ! authed stdio; then record unclear 7 "-W host:22" "no login with the viewer key"; return; fi
    if log_has stdio 'administratively prohibited' || log_has stdio 'stdio forwarding failed'; then
        record refused 7 "-W host:22"
    elif log_has stdio 'open failed: connect failed'; then record ALLOWED 7 "-W host:22" "the lab tried to connect"
    else record unclear 7 "-W host:22" "no answer seen"; fi
}

# --- 8 and 9: remote forwards, one login ---------------------------------------------------------

remote_tcp_state() {
    if log_has remote 'remote forward success for: listen 127.0.0.1:0'; then echo allowed
    elif log_has remote 'remote port forwarding failed for listen port 0' ||
            log_has remote 'remote forward failure for: listen 127.0.0.1:0'; then echo refused
    else echo unknown; fi
}

remote_unix_state() {
    if log_has remote "remote forward success for: listen $SOCK"; then echo allowed
    elif log_has remote "remote port forwarding failed for listen path $SOCK" ||
            log_has remote "remote forward failure for: listen $SOCK"; then echo refused
    else echo unknown; fi
}

remote_decided() {
    { [ "$(remote_tcp_state)" != unknown ] && [ "$(remote_unix_state)" != unknown ]; } || exited
}

probe_remote_forwards() {
    printf 'probe 8-9: -R listeners on the lab (type the passphrase when asked)\n'
    start_ssh remote /dev/null -N -o ExitOnForwardFailure=no \
        -R "127.0.0.1:0:127.0.0.1:9" -R "$SOCK:127.0.0.1:9" "$HOST"
    wait_until $(( AUTH_TIMEOUT + STEP_TIMEOUT )) remote_decided
    stop_ssh
    if ! authed remote; then
        record unclear 8 "-R TCP" "no login with the viewer key"
        record unclear 9 "-R Unix socket" "no login with the viewer key"
        return
    fi
    case "$(remote_tcp_state)" in
        refused) record refused 8 "-R TCP" ;;
        allowed) record ALLOWED 8 "-R TCP" "the lab listened" ;;
        *) record unclear 8 "-R TCP" "no answer seen" ;;
    esac
    case "$(remote_unix_state)" in
        refused) record refused 9 "-R Unix socket" ;;
        allowed) record ALLOWED 9 "-R Unix socket" "the lab listened; remove $SOCK on the lab" ;;
        *) record unclear 9 "-R Unix socket" "no answer seen" ;;
    esac
}

# --- run -----------------------------------------------------------------------------------------

printf 'air-viewer-selftest: nine forbidden actions through Host %s (%s), five logins\n' "$HOST" "$LAB_IP"
probe_session command 1 "a requested command" -T
probe_session pty 2 "a PTY" -tt
probe_local_forwards
probe_stdio
probe_remote_forwards

N_REFUSED=$(grep -c '^refused|' "$WORK/results")
N_ALLOWED=$(grep -c '^ALLOWED|' "$WORK/results")
N_ALL=$(wc -l < "$WORK/results" | tr -d ' ')
if [ "$N_ALLOWED" != 0 ]; then
    printf 'verdict: FAIL (%s of %s ALLOWED): remove the key now (on the lab: sh suite-viewer-setup.sh --undo) and tell lab-Claude\n' \
        "$N_ALLOWED" "$N_ALL"
    exit 1
fi
if [ "$N_REFUSED" = 9 ] && [ "$N_ALL" = 9 ]; then
    printf 'verdict: PASS (9 of 9 refused)\n'
    exit 0
fi
printf 'verdict: INCONCLUSIVE (%s of %s refused, the rest unclear): run it again, or rerun with --keep-logs and tell lab-Claude\n' \
    "$N_REFUSED" "$N_ALL"
exit 3
