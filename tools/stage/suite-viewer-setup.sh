#!/bin/sh
# tools/stage/suite-viewer-setup.sh: install, or remove with --undo, the Air viewer key and the sshd
# drop-in on the lab (docs/DESIGN.md 8.6 item 2; Yu's ruling R-2). Step by step: tools/stage/README.md.
#
# Staged by lab-Claude for Yu. Yu reads it, then runs it on the lab in Yu's own Terminal, as user (not
# with sudo: it calls sudo itself for the root steps, and sudo asks for Yu's password). Agents never run
# it, except tests/test_stage.py in its harness (see "Test seam" below).
#
#   sh suite-viewer-setup.sh --dry-run KEY.pub   every check and every planned change; no sudo, no writes
#   sh suite-viewer-setup.sh KEY.pub             install: the drop-in first (checked with sshd -t and
#                                                sshd -T), then the authorized_keys line
#   sh suite-viewer-setup.sh --dry-run --undo    what --undo would change
#   sh suite-viewer-setup.sh --undo              remove the viewer line and the drop-in, then sshd -t
#
# KEY.pub is the Air's public key file: exactly one "ssh-ed25519 <base64> <comment>" line, nothing else.
# The line appended to ~/.ssh/authorized_keys is exactly the DESIGN.md 8.6 line, ending with the comment
# yu-air-suite-viewer (the key file's own comment is not copied). The drop-in
# /etc/ssh/sshd_config.d/200-lab.conf holds exactly the five DESIGN.md 8.6 lines.
#
# Before changing anything it checks: the key file; that the key is not already in authorized_keys and is
# not the Air agent key; that no viewer line is there yet; that the release copy exists (the forced
# command runs it); that /etc/ssh/sshd_config Includes sshd_config.d/* before any Match block; and that no
# other sshd config file (sshd_config, the other drop-ins such as 100-macos.conf, and the files they
# Include, such as crypto.conf) sets one of the drop-in's keywords: sshd keeps the first value it reads.
#
# On any failure after the first change, both files are put back: authorized_keys from its backup, and
# the drop-in removed (then sshd -t again). --undo never puts the viewer line back (revoking access wins),
# but it puts the drop-in back if sshd -t fails without it. macOS starts sshd once per connection, so a
# change applies to the next connection with no restart, and a broken sshd config would lock out every
# SSH login, the Air agent's included: hence sshd -t right after every change to it.
#
# Exit status: 0 done (or the dry run found nothing wrong); 1 a change failed and was rolled back (read
# the messages); 2 refused before any change. A refusal prints "refused:<code>" and a hint on stderr.
#
# Test seam (tests/test_stage.py only). --test-harness takes sudo and sshd from PATH and reads
# SUITE_STAGE_SSH_DIR in place of /etc/ssh. It refuses unless HOME is a temporary HOME under
# ~/.local/state/betangel-suite/tmp/, the sudo and sshd it finds are recording fakes (marked
# SUITE-STAGE-FAKE-RECORDER) inside that HOME, and the ssh dir lies inside that HOME too: so it never
# reaches the real sudo, sshd, /etc or ~/.ssh. SUITE_STAGE_SSH_DIR is also accepted with --dry-run, which
# only reads. SUITE_STAGE_FAULT injects a failure and is accepted only with --test-harness. Outside the
# harness a dry run's SUDO is dry_run_sudo, a function that refuses, so even a dry run that got past run_root's
# own refusal could never reach the real sudo.

set -u
umask 077

LAB_HOME=/Users/user
APP_SUITE=/Users/user/.local/share/betangel-suite/app/current/bin/suite
OPTIONS='from="192.168.50.*",restrict,port-forwarding,permitopen="127.0.0.1:8765",command="/Users/user/.local/share/betangel-suite/app/current/bin/suite ssh-session"'
COMMENT=yu-air-suite-viewer
AIR_AGENT_COMMENT=macair-claude-to-betfair-lab-20261014
ED25519_BLOB_PREFIX=AAAAC3NzaC1lZDI1NTE5AAAAI
DROPIN_NAME=200-lab.conf
KEYWORD_NAMES='AllowTcpForwarding, AllowStreamLocalForwarding, PermitListen, ClientAliveInterval, ClientAliveCountMax'

dropin_text() {
    printf '%s\n' 'AllowTcpForwarding local' 'AllowStreamLocalForwarding no' 'PermitListen none' \
        'ClientAliveInterval 15' 'ClientAliveCountMax 4'
}

effective_text() {          # what `sshd -T` prints for those settings
    printf '%s\n' 'allowtcpforwarding local' 'allowstreamlocalforwarding no' 'permitlisten none' \
        'clientaliveinterval 15' 'clientalivecountmax 4'
}

DRY_RUN=0 UNDO=0 HARNESS=0 KEYFILE=
WORK= CHANGED=0 COMMITTED=0 AK_TOUCHED=0 DROPIN_WRITTEN=0 DROPIN_REMOVED=0 UNDO_AK=0 BACKUP=

say() { printf '%s\n' "$*"; }

fail() {                    # fail CODE [HINT]: refused (exit 2) before any change, failed (exit 1) after
    if [ "$CHANGED" = 1 ]; then printf 'failed:%s\n' "$1" >&2; else printf 'refused:%s\n' "$1" >&2; fi
    if [ $# -ge 2 ]; then printf '  %s\n' "$2" >&2; fi
    if [ "$CHANGED" = 1 ]; then exit 1; fi
    exit 2
}

fault() {                   # an injected failure (SUITE_STAGE_FAULT, --test-harness only)
    if [ "${SUITE_STAGE_FAULT:-}" = "$1" ]; then fail "injected_$1" "a test fault (--test-harness only)"; fi
}

run_root() {                # every root step goes through here; never in a dry run
    if [ "$DRY_RUN" = 1 ]; then fail internal_dry_run_root "a dry run must never call sudo"; fi
    "$SUDO" "$@"
}

dry_run_sudo() {            # SUDO in a plain dry run: a second barrier, so no dry run can ever reach the real sudo
    fail internal_dry_run_root "a dry run must never call sudo"
}

# --- arguments and mode ----------------------------------------------------------------------------

USAGE='usage: sh suite-viewer-setup.sh [--dry-run] KEY.pub   or   sh suite-viewer-setup.sh [--dry-run] --undo'
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --undo) UNDO=1 ;;
        --test-harness) HARNESS=1 ;;
        -*) fail usage "$USAGE" ;;
        *) if [ -n "$KEYFILE" ]; then fail usage "$USAGE"; fi
           KEYFILE=$arg ;;
    esac
done
if [ "$UNDO" = 1 ] && [ -n "$KEYFILE" ]; then fail usage "$USAGE"; fi
if [ "$UNDO" = 0 ] && [ -z "$KEYFILE" ]; then fail usage "$USAGE"; fi

if [ "$(id -u)" = 0 ]; then
    fail run_as_root "run it as user, without sudo: it calls sudo itself for the root steps"
fi
if [ -n "${SUITE_STAGE_FAULT:-}" ] && [ "$HARNESS" = 0 ]; then
    fail seam_needs_harness "SUITE_STAGE_FAULT is for tests/test_stage.py only"
fi
if [ -n "${SUITE_STAGE_SSH_DIR:-}" ] && [ "$HARNESS" = 0 ] && [ "$DRY_RUN" = 0 ]; then
    fail seam_needs_dry_run "SUITE_STAGE_SSH_DIR is for tests: it is accepted only with --dry-run"
fi

case "${HOME:-}" in /*) ;; *) fail home_invalid "HOME must be an absolute path" ;; esac
HOME_REAL=$(cd "$HOME" 2>/dev/null && pwd -P) || HOME_REAL=
if [ -z "$HOME_REAL" ]; then fail home_invalid "HOME is not a directory"; fi
ME=$(id -un)
case "$ME" in ''|*[!A-Za-z0-9._-]*) fail user_name_unusual "unexpected user name" ;; esac
PW_HOME=$(eval "cd ~$ME" 2>/dev/null && pwd -P) || PW_HOME=

inside_home() { case "$1/" in "$HOME_REAL"/*) return 0 ;; esac; return 1; }

harness_fake() {            # harness_fake PATH NAME: a marked recording fake inside the temporary HOME
    if [ -z "$1" ] || [ ! -f "$1" ] || [ -L "$1" ]; then
        fail "harness_$2_not_fake" "the harness needs a fake $2 on PATH, a regular file (not a link)"
    fi
    hf_dir=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P) || hf_dir=
    if [ -z "$hf_dir" ] || ! inside_home "$hf_dir"; then
        fail "harness_$2_not_fake" "the $2 on PATH must be a recording fake inside the temporary HOME"
    fi
    if ! grep -q 'SUITE-STAGE-FAKE-RECORDER' "$1"; then
        fail "harness_$2_not_fake" "the $2 on PATH is not a marked recording fake"
    fi
}

if [ "$HARNESS" = 1 ]; then
    if [ -z "$PW_HOME" ]; then fail harness_home "cannot find the user's own home directory"; fi
    case "$HOME_REAL/" in
        "$PW_HOME/.local/state/betangel-suite/tmp/"?*) ;;
        *) fail harness_home "the harness runs only with a temporary HOME under ~/.local/state/betangel-suite/tmp/" ;;
    esac
    SUDO=$(command -v sudo 2>/dev/null) || SUDO=
    SSHD=$(command -v sshd 2>/dev/null) || SSHD=
    harness_fake "$SUDO" sudo
    harness_fake "$SSHD" sshd
    SSH_DIR=$(cd "${SUITE_STAGE_SSH_DIR:-/nonexistent}" 2>/dev/null && pwd -P) || SSH_DIR=
    if [ -z "$SSH_DIR" ] || ! inside_home "$SSH_DIR"; then
        fail harness_ssh_dir "the harness needs SUITE_STAGE_SSH_DIR, a directory inside the temporary HOME"
    fi
else
    PATH=/usr/bin:/bin:/usr/sbin:/sbin
    export PATH
    if [ "$DRY_RUN" = 1 ]; then SUDO=dry_run_sudo; else SUDO=/usr/bin/sudo; fi
    SSHD=/usr/sbin/sshd                             # only ever run as an argument of $SUDO (run_root)
    SSH_DIR=${SUITE_STAGE_SSH_DIR:-/etc/ssh}        # the seam is a dry run only (checked above)
    if [ "$DRY_RUN" = 0 ] && { [ "$HOME_REAL" != "$LAB_HOME" ] || [ "$PW_HOME" != "$LAB_HOME" ]; }; then
        fail home_mismatch "the authorized_keys line names $LAB_HOME: run this as user on the lab"
    fi
fi

USER_SSH="$HOME/.ssh"
AK="$USER_SSH/authorized_keys"
SSHD_CONFIG="$SSH_DIR/sshd_config"
DROPIN_DIR="$SSH_DIR/sshd_config.d"
DROPIN="$DROPIN_DIR/$DROPIN_NAME"
APP_SUITE_HERE="$HOME/.local/share/betangel-suite/app/current/bin/suite"

# --- awk helpers -----------------------------------------------------------------------------------

# parse(line) sets KW (the keyword) and A[1..NA] (its arguments) for an sshd_config line, and returns 0
# for a blank or comment line. Keyword and arguments may be separated by spaces or one "="; an unquoted
# "#" starts a trailing comment.
AWK_PARSE='
function parse(line,   rest, n, i, t) {
    KW = ""; NA = 0
    sub(/^[ \t]+/, "", line)
    if (line == "" || substr(line, 1, 1) == "#") return 0
    if (!match(line, /^[A-Za-z0-9]+/)) { KW = line; return 1 }
    KW = substr(line, 1, RLENGTH)
    rest = substr(line, RLENGTH + 1)
    sub(/^[ \t]*=?[ \t]*/, "", rest)
    n = split(rest, t, /[ \t]+/)
    for (i = 1; i <= n; i++) {
        if (substr(t[i], 1, 1) == "#") break
        if (t[i] != "") A[++NA] = t[i]
    }
    return 1
}
function ours(k) {
    k = tolower(k)
    return k == "allowtcpforwarding" || k == "allowstreamlocalforwarding" || k == "permitlisten" ||
           k == "clientaliveinterval" || k == "clientalivecountmax"
}
'

viewer_count() {            # how many viewer lines authorized_keys holds (by options, comment or command)
    VIEWER_PREFIX="$OPTIONS ssh-ed25519 " VIEWER_TAIL=" $COMMENT" LC_ALL=C awk '
        BEGIN { p = ENVIRON["VIEWER_PREFIX"]; t = ENVIRON["VIEWER_TAIL"] }
        index($0, p) == 1 || (length($0) > length(t) && substr($0, length($0) - length(t) + 1) == t) ||
            index($0, "suite ssh-session") { n++ }
        END { print n + 0 }' "$AK"
}

# --- checks ----------------------------------------------------------------------------------------

key_hint() {
    case "$1" in
        key_file_empty) say "the key file is empty" ;;
        key_file_lines) say "the key file must hold exactly one line" ;;
        key_has_options) say "the line must start with ssh-ed25519: no options before the key" ;;
        key_type_not_ed25519) say "only an ssh-ed25519 key is accepted (ssh-keygen -t ed25519)" ;;
        key_comment_missing) say "the line needs a comment after the key, e.g. yu-air-suite-viewer" ;;
        key_comment_invalid) say "the comment may hold only letters, digits and . _ @ + - (64 at most)" ;;
        key_blob_invalid) say "the base64 part is not an ssh-ed25519 public key" ;;
        *) say "the line must be exactly: ssh-ed25519 <base64> <comment>, single spaces" ;;
    esac
}

check_key_file() {
    if [ ! -f "$KEYFILE" ] || [ -L "$KEYFILE" ]; then
        fail key_file_missing "give the path of the Air's public key file (id_ed25519_lab_suite.pub), a regular file"
    fi
    if [ ! -r "$KEYFILE" ]; then fail key_file_unreadable "the key file cannot be read"; fi
    kf_size=$(wc -c < "$KEYFILE" | tr -d ' ')
    if [ "$kf_size" -gt 65536 ]; then fail key_file_too_large "a public key file is under 1 KB"; fi
    if grep -q 'PRIVATE KEY' "$KEYFILE" || grep -q 'PuTTY-User-Key-File' "$KEYFILE"; then
        fail private_key_file "this is a PRIVATE key: it must never leave the Air. Delete this copy, make a new key pair on the Air, and move only the .pub file"
    fi
    if [ "$kf_size" -gt 1024 ]; then fail key_file_too_large "a public key file is under 1 KB"; fi
    kf_other=$(LC_ALL=C tr -d ' -~\n' < "$KEYFILE" | wc -c | tr -d ' ')
    if [ "$kf_other" != 0 ]; then
        fail key_file_bytes "only printable ASCII is allowed: no tabs, carriage returns or control bytes"
    fi
    kf_code=$(LC_ALL=C awk -v prefix="$ED25519_BLOB_PREFIX" '
        NR == 1 {
            if (NF != 3 || $0 != $1 " " $2 " " $3) {
                if (index($0, " ssh-") > 1 || $1 ~ /[=,"]/) code = "key_has_options"
                else if (NF == 2 && $0 == $1 " " $2) code = "key_comment_missing"
                else code = "key_line_format"
            } else if ($1 != "ssh-ed25519") {
                code = ($1 ~ /^(ssh-|ecdsa-|sk-)/) ? "key_type_not_ed25519" : "key_has_options"
            } else if (length($2) != 68 || substr($2, 1, 25) != prefix || $2 !~ /^[A-Za-z0-9+\/]+$/) {
                code = "key_blob_invalid"
            } else if (length($3) > 64 || $3 !~ /^[A-Za-z0-9._@+-]+$/) {
                code = "key_comment_invalid"
            } else code = "ok"
        }
        END { if (NR == 0) code = "key_file_empty"; else if (NR != 1) code = "key_file_lines"; print code }
    ' "$KEYFILE")
    if [ "$kf_code" != ok ]; then fail "$kf_code" "$(key_hint "$kf_code")"; fi
    B64=$(LC_ALL=C awk '{ print $2 }' "$KEYFILE")
    NEW_LINE="$OPTIONS ssh-ed25519 $B64 $COMMENT"
    # ssh-keygen parses the whole line, options included, from stdin; nothing is written.
    FPR=$(printf '%s\n' "$NEW_LINE" | /usr/bin/ssh-keygen -l -f - 2>/dev/null |
        awk 'NR == 1 && $1 == 256 && $NF == "(ED25519)" { print $2 }')
    if [ -z "$FPR" ]; then fail key_blob_invalid "ssh-keygen cannot read this key"; fi
}

check_authorized_keys() {
    if [ ! -d "$USER_SSH" ] || [ -L "$USER_SSH" ]; then fail ssh_dir_missing "expected the directory ~/.ssh"; fi
    if [ ! -f "$AK" ] || [ -L "$AK" ]; then
        fail authorized_keys_missing "expected ~/.ssh/authorized_keys (a regular file holding the Air agent key)"
    fi
    if [ "$(stat -f '%u' "$AK")" != "$(id -u)" ]; then fail authorized_keys_owner "authorized_keys is not yours"; fi
    for ak_path in "$USER_SSH" "$AK"; do
        case "$(stat -f '%Lp' "$ak_path")" in
            ?[2367]?|??[2367]) fail authorized_keys_mode "group or others can write $ak_path; sshd would ignore the keys" ;;
        esac
    done
}

check_key_is_new() {
    if grep -qF -- "$B64" "$AK"; then
        if grep -F -- "$B64" "$AK" | grep -qF -- "$AIR_AGENT_COMMENT"; then
            fail key_is_air_agent_key "this is the Air agent's key: the viewer needs its own new key (README step 2)"
        fi
        if grep -F -- "$B64" "$AK" | grep -qF -- "suite ssh-session"; then
            fail viewer_key_already_installed "this viewer key is already installed; nothing to do"
        fi
        fail key_already_present "this key is already in authorized_keys; the viewer needs its own new key"
    fi
    if [ "$(viewer_count)" != 0 ]; then
        fail viewer_line_present "a viewer line is already there: run --undo first"
    fi
}

check_release() {
    if [ ! -f "$APP_SUITE_HERE" ] || [ ! -x "$APP_SUITE_HERE" ]; then
        fail release_missing "no release copy at ~/.local/share/betangel-suite/app/current/bin/suite: install a release first (Yu runs bin/suite release <merge-sha> in the clean main checkout, /Users/user/betangel-suite)"
    fi
}

# The files sshd reads besides our drop-in: sshd_config, every other drop-in, and what they Include.
# Absolute Include paths under /etc/ssh/ are read under SSH_DIR (the same thing outside the test harness).
sshd_files() {
    printf '%s\n' "$SSHD_CONFIG"
    set +f
    for sf_file in "$DROPIN_DIR"/*; do
        if [ -f "$sf_file" ] && [ "$sf_file" != "$DROPIN" ]; then printf '%s\n' "$sf_file"; fi
    done
    set -f
}

include_targets() {         # include_targets FILE: the existing files its Include lines name (not the drop-ins)
    while IFS= read -r it_pattern; do
        case "$it_pattern" in
            '') continue ;;
            *[\"\']*|*..*) fail sshd_include_unexpected "a quoted Include path or one with ..: check the sshd configuration by hand" ;;
            /etc/ssh/sshd_config.d/\*|sshd_config.d/\*) continue ;;
            /etc/ssh/*) it_mapped="$SSH_DIR/${it_pattern#/etc/ssh/}" ;;
            /*) fail sshd_include_unexpected "an Include outside /etc/ssh: check the sshd configuration by hand" ;;
            *) it_mapped="$SSH_DIR/$it_pattern" ;;
        esac
        set +f
        for it_target in $it_mapped; do
            if [ -f "$it_target" ]; then printf '%s\n' "$it_target"; fi
        done
        set -f
    done <<EOF
$(LC_ALL=C awk "$AWK_PARSE"'parse($0) && tolower(KW) == "include" { for (i = 1; i <= NA; i++) print A[i] }' "$1")
EOF
}

check_sshd_layout() {
    if [ ! -f "$SSHD_CONFIG" ] || [ ! -r "$SSHD_CONFIG" ]; then fail sshd_config_missing "cannot read $SSHD_CONFIG"; fi
    if [ ! -d "$DROPIN_DIR" ]; then fail dropin_dir_missing "$DROPIN_DIR does not exist"; fi
    sl_include=$(LC_ALL=C awk "$AWK_PARSE"'
        !parse($0) { next }
        tolower(KW) == "match" { if (!inc) m = 1 }
        tolower(KW) == "include" && !m && NA == 1 &&
            (A[1] == "/etc/ssh/sshd_config.d/*" || A[1] == "sshd_config.d/*") { inc = 1 }
        END { print (inc ? "ok" : (m ? "include_after_match" : "missing")) }' "$SSHD_CONFIG")
    case "$sl_include" in
        ok) ;;
        include_after_match) fail sshd_include_after_match "sshd_config must Include /etc/ssh/sshd_config.d/* before any Match block" ;;
        *) fail sshd_include_missing "sshd_config has no Include /etc/ssh/sshd_config.d/* line, so the drop-in would be ignored" ;;
    esac
    SL_FILES=$(sshd_files)
    SL_EXTRA=
    while IFS= read -r sl_file; do
        if [ -z "$sl_file" ]; then continue; fi
        sl_targets=$(include_targets "$sl_file") || exit $?
        if [ -n "$sl_targets" ]; then SL_EXTRA="$SL_EXTRA$sl_targets
"; fi
    done <<EOF
$SL_FILES
EOF
    while IFS= read -r sl_file; do
        if [ -z "$sl_file" ]; then continue; fi
        if LC_ALL=C awk "$AWK_PARSE"'parse($0) && tolower(KW) == "include" { found = 1 } END { exit !found }' "$sl_file"; then
            fail sshd_include_nested "an included file Includes more files: check the sshd configuration by hand"
        fi
    done <<EOF
$SL_EXTRA
EOF
    SL_FILES="$SL_FILES
$SL_EXTRA"
    sl_conflicts=
    while IFS= read -r sl_file; do
        if [ -z "$sl_file" ]; then continue; fi
        sl_found=$(LC_ALL=C awk "$AWK_PARSE"'parse($0) && ours(KW) { print FILENAME ":" FNR ": " KW }' "$sl_file")
        if [ -n "$sl_found" ]; then sl_conflicts="$sl_conflicts$sl_found
"; fi
    done <<EOF
$SL_FILES
EOF
    if [ -n "$sl_conflicts" ]; then
        printf '%s' "$sl_conflicts" | sed 's/^/  already set: /' >&2
        fail sshd_keyword_conflict "another sshd config file sets a drop-in keyword, and sshd keeps the first value it reads: remove that line (or ask lab-Claude) first"
    fi
    SL_READ=$(printf '%s\n' "$SL_FILES" | awk 'NF' | tr '\n' ' ')
}

dropin_state() {            # absent, ours (exactly our text) or other
    if [ ! -e "$DROPIN" ] && [ ! -L "$DROPIN" ]; then echo absent; return; fi
    if [ -f "$DROPIN" ] && [ ! -L "$DROPIN" ] && dropin_text | cmp -s - "$DROPIN"; then echo ours; return; fi
    echo other
}

print_indented() { sed 's/^/    /'; }

# --- rollback --------------------------------------------------------------------------------------

rollback_install() {
    rb_ok=1
    if [ "$AK_TOUCHED" = 1 ]; then
        if cat "$BACKUP" > "$AK" && cmp -s "$BACKUP" "$AK"; then
            say "rollback: put authorized_keys back from $BACKUP" >&2
        else
            rb_ok=0
            say "ROLLBACK PROBLEM: authorized_keys was not put back: copy $BACKUP over it by hand" >&2
        fi
    fi
    if [ "$DROPIN_WRITTEN" = 1 ] && [ ! -e "$DROPIN" ]; then
        say "rollback: the drop-in was never written" >&2
    elif [ "$DROPIN_WRITTEN" = 1 ]; then
        if run_root /bin/rm -f "$DROPIN" && [ ! -e "$DROPIN" ]; then
            say "rollback: removed $DROPIN" >&2
        else
            rb_ok=0
            say "ROLLBACK PROBLEM: $DROPIN was not removed: remove it by hand (sudo rm)" >&2
        fi
        if run_root "$SSHD" -t -f "$SSHD_CONFIG"; then
            say "rollback: sshd -t ok" >&2
        else
            rb_ok=0
            say "ROLLBACK PROBLEM: sshd -t still fails: SSH logins (the Air agent's too) may fail until it is fixed" >&2
        fi
    fi
    if [ "$rb_ok" = 1 ]; then say "rollback: complete; nothing is left changed" >&2; fi
}

rollback_undo() {
    if [ "$DROPIN_REMOVED" = 1 ]; then
        # The saved copy was exactly the drop-in (dropin_state ours) and lies in a directory this user can write:
        # it is checked against the fixed text before root installs it, and the installed file after.
        if ! dropin_text | cmp -s - "$WORK/$DROPIN_NAME.saved"; then
            say "ROLLBACK PROBLEM: the saved drop-in changed, so it was not put back: check $DROPIN and sudo sshd -t by hand" >&2
        elif run_root /usr/bin/install -m 0644 -o root -g wheel "$WORK/$DROPIN_NAME.saved" "$DROPIN" &&
                dropin_text | cmp -s - "$DROPIN" && run_root "$SSHD" -t -f "$SSHD_CONFIG"; then
            say "rollback: put the drop-in back; sshd -t ok" >&2
        else
            say "ROLLBACK PROBLEM: the drop-in was not put back cleanly: check $DROPIN and sudo sshd -t by hand" >&2
        fi
    fi
    if [ "$UNDO_AK" = 1 ]; then say "note: the viewer line stays removed (revoking access is never rolled back)" >&2; fi
}

on_exit() {
    oe_status=$?
    trap - EXIT INT TERM HUP
    if [ "$CHANGED" = 1 ] && [ "$COMMITTED" = 0 ]; then
        if [ "$UNDO" = 1 ]; then rollback_undo; else rollback_install; fi
        if [ "$oe_status" = 0 ]; then oe_status=1; fi
    fi
    if [ -n "$WORK" ]; then rm -rf "$WORK"; fi
    exit "$oe_status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
set -f

make_work() {
    WORK=$(mktemp -d "${TMPDIR:-/tmp}/suite-viewer-setup.XXXXXX") || WORK=
    if [ -z "$WORK" ]; then fail workdir "cannot make a temporary directory"; fi
}

new_backup_name() {
    BACKUP="$AK.bak-suite-viewer-$(date +%Y%m%dT%H%M%S)-$$"
    if [ -e "$BACKUP" ]; then fail backup_exists "$BACKUP already exists"; fi
}

# --- install ---------------------------------------------------------------------------------------

install_viewer() {
    check_key_file
    check_authorized_keys
    check_key_is_new
    check_release
    check_sshd_layout
    STATE=$(dropin_state)
    if [ "$STATE" = other ]; then
        fail dropin_differs "$DROPIN exists with other content: look at it (or ask lab-Claude) first"
    fi
    if [ "$DRY_RUN" = 1 ]; then say "suite-viewer-setup: install, dry run (no sudo, no writes)"
    else say "suite-viewer-setup: install"; fi
    if [ "$HOME_REAL" != "$LAB_HOME" ]; then say "note: HOME is not $LAB_HOME (a preview or test run)"; fi
    say "check: key file: one ssh-ed25519 line, fingerprint $FPR"
    say "check: the key is not in $AK and is not the Air agent key"
    say "check: no viewer line in $AK yet"
    if ! grep -qF -- "$AIR_AGENT_COMMENT" "$AK"; then
        say "note: the Air agent key ($AIR_AGENT_COMMENT) is not in $AK"
    fi
    say "check: release copy present: $APP_SUITE_HERE"
    say "check: $SSHD_CONFIG includes sshd_config.d/* before any Match block"
    say "check: no other sshd config file sets $KEYWORD_NAMES (read: $SL_READ)"
    if [ "$STATE" = ours ]; then
        say "plan 1: $DROPIN already holds exactly the drop-in: left as is"
    else
        say "plan 1: sudo /usr/bin/install -m 0644 -o root -g wheel <temporary copy> $DROPIN, holding exactly:"
        dropin_text | print_indented
    fi
    say "plan 2: sudo $SSHD -t -f $SSHD_CONFIG (the configuration must be valid)"
    say "plan 3: sudo $SSHD -T -f $SSHD_CONFIG must show:"
    effective_text | print_indented
    say "plan 4: copy $AK to $AK.bak-suite-viewer-<time>"
    say "plan 5: append exactly this line to $AK:"
    printf '%s\n' "$NEW_LINE" | print_indented
    say "on failure: authorized_keys is put back from the backup, the drop-in removed, and sshd -t run again"
    if [ "$DRY_RUN" = 1 ]; then
        say "dry run: nothing was changed"
        return 0
    fi

    make_work
    if ! dropin_text > "$WORK/$DROPIN_NAME" || ! effective_text > "$WORK/expected"; then
        fail workdir "cannot write the temporary files"
    fi
    if [ "$STATE" = absent ]; then
        say "step 1: writing $DROPIN (sudo may ask for your password)"
        CHANGED=1
        DROPIN_WRITTEN=1
        if ! dropin_text | cmp -s - "$WORK/$DROPIN_NAME"; then fail dropin_verify "the temporary copy changed"; fi
        if ! run_root /usr/bin/install -m 0644 -o root -g wheel "$WORK/$DROPIN_NAME" "$DROPIN"; then
            fail dropin_write "sudo install did not write the drop-in"
        fi
        # Against the fixed text, not the temporary copy: that lies in a directory any process of this user can
        # write, for example while sudo waits for the password.
        if ! dropin_text | cmp -s - "$DROPIN"; then fail dropin_verify "the drop-in does not hold the expected text"; fi
    else
        say "step 1: $DROPIN already holds exactly the drop-in: left as is"
    fi
    say "step 2: sudo $SSHD -t"
    if ! run_root "$SSHD" -t -f "$SSHD_CONFIG"; then
        fail sshd_t_failed "sshd -t rejected the configuration with the drop-in"
    fi
    say "step 3: sudo $SSHD -T"
    if ! run_root "$SSHD" -T -f "$SSHD_CONFIG" > "$WORK/effective" 2>/dev/null; then
        fail sshd_effective_failed "sshd -T did not print the effective configuration"
    fi
    in_missing=$(LC_ALL=C awk 'NR == FNR { want[$0] = 1; next } ($0 in want) { got[$0] = 1 }
        END { for (w in want) if (!(w in got)) print w }' "$WORK/expected" "$WORK/effective")
    if [ -n "$in_missing" ]; then
        printf '%s\n' "$in_missing" | sed 's/^/  expected, not in sshd -T: /' >&2
        fail sshd_effective_mismatch "sshd does not use the drop-in's values"
    fi
    new_backup_name
    say "step 4: backing up authorized_keys to $BACKUP"
    if ! cp -p "$AK" "$BACKUP" || ! cmp -s "$AK" "$BACKUP"; then fail backup_failed "cannot back up $AK"; fi
    in_nl=0
    if [ -s "$AK" ] && [ "$(tail -c 1 "$AK" | wc -l | tr -d ' ')" = 0 ]; then in_nl=1; fi
    if ! { cat "$BACKUP"; if [ "$in_nl" = 1 ]; then printf '\n'; fi; printf '%s\n' "$NEW_LINE"; } > "$WORK/ak.expected"; then
        fail workdir "cannot write the temporary files"
    fi
    say "step 5: appending the viewer line to $AK"
    CHANGED=1
    AK_TOUCHED=1
    if ! { if [ "$in_nl" = 1 ]; then printf '\n'; fi; printf '%s\n' "$NEW_LINE"; } >> "$AK"; then
        fail append_failed "cannot append to $AK"
    fi
    fault after_append
    if ! cmp -s "$WORK/ak.expected" "$AK" || [ "$(viewer_count)" != 1 ]; then
        fail append_verify "authorized_keys does not hold exactly the expected lines"
    fi
    COMMITTED=1
    say "done: the viewer key is installed and the drop-in is active (macOS starts sshd per connection: no restart)"
    say "fingerprint: $FPR (compare: ssh-keygen -lf ~/.ssh/id_ed25519_lab_suite.pub on the Air)"
    say "backup: $BACKUP"
    say "next: on the Air, run air-viewer-selftest.sh (tools/stage/README.md, step 6)"
}

# --- undo ------------------------------------------------------------------------------------------

undo_viewer() {
    check_authorized_keys
    if [ ! -f "$SSHD_CONFIG" ]; then fail sshd_config_missing "cannot read $SSHD_CONFIG"; fi
    UV_COUNT=$(viewer_count)
    STATE=$(dropin_state)
    if [ "$DRY_RUN" = 1 ]; then say "suite-viewer-setup: undo, dry run (no sudo, no writes)"
    else say "suite-viewer-setup: undo"; fi
    say "check: $UV_COUNT viewer line(s) in $AK"
    case "$STATE" in
        ours) say "check: $DROPIN holds the suite drop-in" ;;
        other) say "note: $DROPIN holds other text: it is left as is" ;;
        *) say "check: no $DROPIN" ;;
    esac
    if [ "$UV_COUNT" = 0 ] && [ "$STATE" != ours ]; then
        say "nothing to undo"
        return 0
    fi
    uv_plan=1
    if [ "$UV_COUNT" != 0 ]; then
        say "plan $uv_plan: copy $AK to $AK.bak-suite-viewer-<time>"
        uv_plan=2
        say "plan $uv_plan: remove the $UV_COUNT viewer line(s) from $AK (this is never rolled back)"
        uv_plan=3
    fi
    if [ "$STATE" = ours ]; then
        say "plan $uv_plan: sudo /bin/rm -f $DROPIN"
        uv_plan=$((uv_plan + 1))
        say "plan $uv_plan: sudo $SSHD -t -f $SSHD_CONFIG (if it fails, the drop-in is put back)"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        say "dry run: nothing was changed"
        return 0
    fi

    make_work
    if [ "$UV_COUNT" != 0 ]; then
        new_backup_name
        say "step: backing up authorized_keys to $BACKUP"
        if ! cp -p "$AK" "$BACKUP" || ! cmp -s "$AK" "$BACKUP"; then fail backup_failed "cannot back up $AK"; fi
        if ! VIEWER_PREFIX="$OPTIONS ssh-ed25519 " VIEWER_TAIL=" $COMMENT" LC_ALL=C awk '
                BEGIN { p = ENVIRON["VIEWER_PREFIX"]; t = ENVIRON["VIEWER_TAIL"] }
                index($0, p) == 1 || (length($0) > length(t) && substr($0, length($0) - length(t) + 1) == t) ||
                    index($0, "suite ssh-session") { next }
                { print }' "$BACKUP" > "$WORK/ak.new"; then
            fail workdir "cannot write the temporary files"
        fi
        say "step: removing the viewer line(s)"
        CHANGED=1
        UNDO_AK=1
        if ! cat "$WORK/ak.new" > "$AK" || ! cmp -s "$WORK/ak.new" "$AK" || [ "$(viewer_count)" != 0 ]; then
            cat "$BACKUP" > "$AK"
            fail undo_write_failed "authorized_keys was put back from $BACKUP: the viewer line is STILL there; remove it by hand"
        fi
        say "step: removed; the viewer key no longer logs in (open connections stay until they close)"
    fi
    if [ "$STATE" = ours ]; then
        if ! cp "$DROPIN" "$WORK/$DROPIN_NAME.saved"; then fail workdir "cannot copy the drop-in"; fi
        say "step: removing $DROPIN (sudo may ask for your password)"
        CHANGED=1
        DROPIN_REMOVED=1
        if ! run_root /bin/rm -f "$DROPIN" || [ -e "$DROPIN" ]; then fail dropin_remove_failed "sudo rm did not remove the drop-in"; fi
        say "step: sudo $SSHD -t"
        if ! run_root "$SSHD" -t -f "$SSHD_CONFIG"; then
            fail sshd_t_failed_after_undo "sshd -t fails without the drop-in, so it is put back; the viewer line stays removed"
        fi
        DROPIN_REMOVED=0
    fi
    COMMITTED=1
    say "done: the viewer line and the drop-in are removed"
    if [ -n "$BACKUP" ]; then say "backup: $BACKUP"; fi
}

if [ "$UNDO" = 1 ]; then undo_viewer; else install_viewer; fi
exit 0
