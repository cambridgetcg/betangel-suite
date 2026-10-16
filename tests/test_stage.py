"""The staged viewer setup for Yu (tools/stage/, DESIGN.md 8.6 item 2; R-2).

Nothing here touches the real ~/.ssh, /etc, sudo or sshd, and nothing connects anywhere:

  - every script is only parsed (sh -n, bash -n, dash -n, zsh -n), except as below;
  - suite-viewer-setup.sh runs only with --dry-run or --test-harness, under a temporary HOME laid out like the
    lab (authorized_keys with an Air agent line, app/current/bin/suite, and a copy of the macOS sshd layout in
    place of /etc/ssh). PATH starts with a directory holding recording fakes for sudo and sshd; the dry runs
    must never call them and must write nothing. The script's harness refuses to run unless HOME is such a
    temporary HOME and both fakes are marked recording fakes inside it, which is tested too. Real-mode runs
    appear only in refusal tests that stop before any sudo (and with PATH reset by the script itself);
  - air-viewer-selftest.sh runs against a fake ssh and a fake nc, which simulate a lab that refuses
    everything, one that allows too much, and one that never lets the key log in. The fake ssh answers ssh -G
    for each form the self-test asks about, so a test can give one probe's form a key or a forward that a
    Match block would add.

The test runner's guard does not start shells, so the scripts run from an unguarded relay child (as node does
in tests/test_integration_ui.py), several runs per relay to keep the fast tier quick. The exact texts (the
authorized_keys line, the drop-in, the Air's Host block) are compared with docs/DESIGN.md 8.6 itself.
Synthetic keys are 32 made-up bytes; private-key text is assembled at runtime so no line here matches the
hygiene scanner.
"""

import base64
import hashlib
import json
import os
import re
import stat
import struct
import tempfile
import unittest

from tests import ROOT, child_env, make_home, rmtree, run_python

STAGE = os.path.join(ROOT, "tools", "stage")
SETUP = os.path.join(STAGE, "suite-viewer-setup.sh")
SELFTEST = os.path.join(STAGE, "air-viewer-selftest.sh")
ALIAS = os.path.join(STAGE, "suite-alias.zsh")
SNIPPET = os.path.join(STAGE, "air-ssh-config.snippet")
README = os.path.join(STAGE, "README.md")
DESIGN = os.path.join(ROOT, "docs", "DESIGN.md")
SHELLS = ("/bin/sh", "/bin/bash", "/bin/dash")
ZSH = "/bin/zsh"
AGENT_COMMENT = "macair-claude-to-betfair-lab-20261014"
MARKER = "SUITE-STAGE-FAKE-RECORDER"
CODE = re.compile(r"^(refused|failed):([a-z0-9_]+)$", re.M)


def _j(*parts):
    return "".join(parts)


def _design_block(marker):
    """The fenced block after the first DESIGN.md line containing marker, de-indented, as a list of lines."""
    with open(DESIGN, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    start = next(i for i, line in enumerate(lines) if marker in line)
    fence = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "```")
    indent = len(lines[fence]) - len(lines[fence].lstrip())
    end = next(i for i in range(fence + 1, len(lines)) if lines[i].strip() == "```")
    return [line[indent:] for line in lines[fence + 1:end]]


DESIGN_DROPIN = _design_block("**The sshd drop-in**")
DESIGN_AK_LINE = _design_block("**The lab's `authorized_keys` line:**")
DESIGN_HOST_BLOCK = _design_block("**The Air's `~/.ssh/config`:**")
# The Host block's seven hardening lines (Phase 0c security review): no connection sharing, agent, proxy or
# LocalCommand that a later `Host *` block could add. Its three authentication lines: no password fallback (the
# lab's sshd still takes passwords). DESIGN.md 8.6 carries all ten, and the snippet is exactly that block.
HOST_HARDENING = ["  ControlMaster no", "  ControlPath none", "  ControlPersist no", "  IdentityAgent none",
                  "  ProxyCommand none", "  ProxyJump none", "  PermitLocalCommand no"]
HOST_AUTH = ["  PreferredAuthentications publickey", "  PasswordAuthentication no", "  KbdInteractiveAuthentication no"]
APP_SUITE = re.search(r'command="([^"]+) ssh-session"', DESIGN_AK_LINE[0]).group(1)


def _blob(seed, kind=b"ssh-ed25519"):
    raw = bytes((seed * 37 + i * 11) % 256 for i in range(32))
    return struct.pack(">I", len(kind)) + kind + struct.pack(">I", len(raw)) + raw


def _pubkey(seed):
    """A synthetic ssh-ed25519 public key (base64 of the wire blob around 32 made-up bytes)."""
    return base64.b64encode(_blob(seed)).decode("ascii")


def _fingerprint(seed):
    return "SHA256:" + base64.b64encode(hashlib.sha256(_blob(seed)).digest()).decode("ascii").rstrip("=")


def _viewer_line(key):
    return DESIGN_AK_LINE[0].replace("AAAA...", key)


def _write(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8") if isinstance(text, str) else text)
    os.chmod(path, mode)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _snapshot(top):
    """{relative path: (mode, content hash or link target)} for everything under top."""
    found = {}
    for directory, dirs, files in os.walk(top):
        for name in dirs + files:
            full = os.path.join(directory, name)
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                body = "->" + os.readlink(full)
            elif stat.S_ISREG(info.st_mode):
                with open(full, "rb") as handle:
                    body = hashlib.sha256(handle.read()).hexdigest()
            else:
                body = None
            found[os.path.relpath(full, top)] = (stat.S_IMODE(info.st_mode), body)
    return found


def _relay_many(home, runs, timeout=60, width=4):
    """[(returncode, stdout, stderr)] for each (argv, env) in runs, started by one unguarded relay child (the runner's
    guard starts no shell itself), at most width at a time. Callers batch only runs that do not depend on each
    other's effects."""
    plan = [[list(argv), dict(env)] for argv, env in runs]
    code = ("import json, subprocess\n"
            "plan = %r\n"
            "results = [None] * len(plan)\n"
            "for start in range(0, len(plan), %d):\n"
            "    batch = [(i, subprocess.Popen(argv, env=env, cwd=%r, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,\n"
            "                                  stderr=subprocess.PIPE, text=True))\n"
            "             for i, (argv, env) in enumerate(plan[start:start + %d], start)]\n"
            "    for i, proc in batch:\n"
            "        out, err = proc.communicate(timeout=%d)\n"
            "        results[i] = [proc.returncode, out, err]\n"
            "print(json.dumps(results))\n") % (plan, width, home, width, timeout)
    relay = run_python(code, home, timeout=timeout * len(runs) + 30)
    if relay.returncode != 0:
        raise AssertionError("relay failed: " + relay.stderr[-800:])
    return [tuple(item) for item in json.loads(relay.stdout)]


def _codes(stderr):
    return [match.group(2) for match in CODE.finditer(stderr)]


def _indented_after(stdout, header):
    """The four-space-indented lines right after the first line starting with header, de-indented."""
    lines = stdout.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    block = []
    for line in lines[start + 1:]:
        if not line.startswith("    "):
            break
        block.append(line[4:])
    return block


# --- shared fakes ---------------------------------------------------------------------------------------

_SHARED = {}


def _link_fake(name, text, directory):
    """Hard-link a fake into directory. Each fake is written once per run (macOS checks every new executable on
    its first run, about 0.13 s each); a hard link shares the checked file. The fakes take every path from
    their environment ($HOME, SUITE_STAGE_SSH_DIR, FAKE_STATE), so one copy serves every temporary HOME."""
    if "dir" not in _SHARED:
        _SHARED["dir"] = tempfile.mkdtemp(prefix="stage-fakes-")
    original = os.path.join(_SHARED["dir"], name)
    if not os.path.exists(original):
        _write(original, text, 0o700)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.link(original, os.path.join(directory, name))


def tearDownModule():
    if "dir" in _SHARED:
        rmtree(_SHARED.pop("dir"))


# --- the fake lab: a temporary HOME for suite-viewer-setup.sh -------------------------------------------

FAKE_SUDO = """#!/bin/sh
# SUITE-STAGE-FAKE-RECORDER: stands in for sudo in tests/test_stage.py. It records its argv in $HOME, then runs
# only the commands the setup script uses, as the current user and inside the temporary HOME. It never elevates.
case "$HOME" in */.local/state/betangel-suite/tmp/?*) ;; *) echo 'fake sudo: not a test HOME' >&2; exit 99 ;; esac
{ printf 'sudo'; for a in "$@"; do printf ' %s' "$a"; done; printf '\\n'; } >> "$HOME/fake-calls.log"
for a in "$@"; do
    case "$a" in /etc/*|/private/etc/*|/System/*|/Library/*) echo 'fake sudo: a system path' >&2; exit 98 ;; esac
done
# $HOME/fake-sudo-mode: install-alters changes the script's temporary copy just before installing it (as another
# process of this user could while sudo waits for the password); rm-tampers-saved changes its saved copy first.
mode=$(cat "$HOME/fake-sudo-mode" 2>/dev/null)
case "$1" in
    "$(dirname "$0")/sshd") exec "$@" ;;
    /bin/rm)
        if [ $# = 3 ] && [ "$2" = -f ]; then
            if [ "$mode" = rm-tampers-saved ]; then
                for saved in "${TMPDIR:-/nonexistent}"/suite-viewer-setup.*/200-lab.conf.saved; do
                    if [ -f "$saved" ]; then echo 'AllowAgentForwarding yes' >> "$saved"; fi
                done
            fi
            case "$3" in "$HOME"/*) exec /bin/rm -f "$3" ;; esac
        fi ;;
    /usr/bin/install)
        if [ $# = 9 ] && [ "$2 $3 $4 $5 $6 $7" = '-m 0644 -o root -g wheel' ]; then
            case "$9" in "$HOME"/*)
                if [ "$mode" = install-alters ]; then echo 'AllowAgentForwarding yes' >> "$8"; fi
                exec /usr/bin/install -m 0644 "$8" "$9" ;;
            esac
        fi ;;
esac
echo 'fake sudo: unexpected command' >&2
exit 97
"""

FAKE_SSHD = """#!/bin/sh
# SUITE-STAGE-FAKE-RECORDER: stands in for sshd in tests/test_stage.py. It records its argv in $HOME and answers
# -t and -T from the fake drop-in and a mode file; it reads no real configuration and listens on nothing.
case "$HOME" in */.local/state/betangel-suite/tmp/?*) ;; *) echo 'fake sshd: not a test HOME' >&2; exit 99 ;; esac
{ printf 'sshd'; for a in "$@"; do printf ' %s' "$a"; done; printf '\\n'; } >> "$HOME/fake-calls.log"
dropin="$SUITE_STAGE_SSH_DIR/sshd_config.d/200-lab.conf"
mode=$(cat "$HOME/fake-sshd-mode" 2>/dev/null)
case "$1" in
    -t)
        if [ "$mode" = t-fails-with-dropin ] && [ -f "$dropin" ]; then echo 'fake sshd: bad' >&2; exit 255; fi
        if [ "$mode" = t-fails-without-dropin ] && [ ! -f "$dropin" ]; then echo 'fake sshd: bad' >&2; exit 255; fi
        exit 0 ;;
    -T)
        echo 'port 22'
        if [ -f "$dropin" ] && [ "$mode" != T-ignores-dropin ]; then
            printf '%s\\n' 'allowtcpforwarding local' 'allowstreamlocalforwarding no' 'permitlisten none' \\
                'clientaliveinterval 15' 'clientalivecountmax 4'
        else
            printf '%s\\n' 'allowtcpforwarding yes' 'allowstreamlocalforwarding yes' 'permitlisten any' \\
                'clientaliveinterval 0' 'clientalivecountmax 3'
        fi
        echo 'subsystem sftp /usr/libexec/sftp-server'
        exit 0 ;;
esac
exit 64
"""

SSHD_CONFIG = """# a synthetic stand-in for the macOS sshd_config (tests/test_stage.py)
# Options that appear multiple times keep the first value set.
Include /etc/ssh/sshd_config.d/*

#Port 22
#AllowTcpForwarding yes
#ClientAliveInterval 0
#ClientAliveCountMax 3
AuthorizedKeysFile\t.ssh/authorized_keys
Subsystem\tsftp\t/usr/libexec/sftp-server

# Example of overriding settings on a per-user basis
#Match User anoncvs
#\tAllowTcpForwarding no
"""

MACOS_CONF = """# Options set by macOS that differ from the OpenSSH defaults.
UsePAM yes
AcceptEnv LANG LC_*
Include /etc/ssh/crypto.conf
"""

CRYPTO_CONF = """# synthetic crypto policy
Ciphers ^aes128-gcm@openssh.com,aes256-gcm@openssh.com
KexAlgorithms ^ecdh-sha2-nistp256
"""


class _Lab:
    """A temporary HOME laid out like the lab, with recording fakes for sudo and sshd on PATH."""

    def __init__(self, case):
        self.home = home = make_home(case)
        self.ssh = os.path.join(home, ".ssh")
        os.mkdir(self.ssh, 0o700)
        self.ak = os.path.join(self.ssh, "authorized_keys")
        self.agent_key = _pubkey(1)
        self.viewer_key = _pubkey(2)
        self.ak_text = "no-port-forwarding,no-agent-forwarding ssh-ed25519 %s %s\n" % (self.agent_key, AGENT_COMMENT)
        _write(self.ak, self.ak_text)
        self.app = os.path.join(home, ".local", "share", "betangel-suite", "app", "current", "bin", "suite")
        _write(self.app, "#!/bin/sh\nexit 2\n", 0o700)
        self.etc = self.make_etc("etc-ssh")
        self.dropin = os.path.join(self.etc, "sshd_config.d", "200-lab.conf")
        self.log = os.path.join(home, "fake-calls.log")
        self.bin = os.path.join(home, "fakebin")
        _link_fake("sudo", FAKE_SUDO, self.bin)
        _link_fake("sshd", FAKE_SSHD, self.bin)
        self.key = os.path.join(home, "air", "id_ed25519_lab_suite.pub")
        _write(self.key, "ssh-ed25519 %s yu@air\n" % self.viewer_key, 0o644)

    def make_etc(self, name, **changes):
        """A copy of the macOS sshd layout under HOME; changes maps relative paths to new text (None removes)."""
        etc = os.path.join(self.home, name)
        files = {"sshd_config": SSHD_CONFIG, "sshd_config.d/100-macos.conf": MACOS_CONF,
                 "crypto/apple.conf": CRYPTO_CONF}
        files.update(changes)
        os.makedirs(os.path.join(etc, "sshd_config.d"), mode=0o755)
        for rel, text in files.items():
            if text is not None:
                _write(os.path.join(etc, rel), text, 0o644)
        os.symlink("crypto/apple.conf", os.path.join(etc, "crypto.conf"))
        return etc

    def env(self, **changes):
        changes.setdefault("SUITE_STAGE_SSH_DIR", self.etc)
        changes.setdefault("PATH", self.bin + ":/usr/bin:/bin")
        return child_env(self.home, **changes)

    def argv(self, *args, shell="/bin/sh"):
        return [shell, SETUP, *args]

    def run(self, *args, env=None):
        return _relay_many(self.home, [(self.argv(*args), self.env() if env is None else env)])[0]

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return _read(self.log).splitlines()

    def sshd_mode(self, mode):
        _write(os.path.join(self.home, "fake-sshd-mode"), mode + "\n")

    def sudo_mode(self, mode):
        _write(os.path.join(self.home, "fake-sudo-mode"), mode + "\n")


# --- the staged files themselves ------------------------------------------------------------------------

class StagedFilesTests(unittest.TestCase):

    def test_every_script_parses_in_every_shell(self):
        home = make_home(self)
        env = child_env(home)
        runs = [([shell, "-n", path], env) for shell in SHELLS for path in (SETUP, SELFTEST, ALIAS)]
        runs.append(([ZSH, "-n", ALIAS], env))
        for (argv, _env), (code, out, err) in zip(runs, _relay_many(home, runs)):
            with self.subTest(argv=argv):
                self.assertEqual((code, out, err), (0, "", ""))

    def test_scripts_are_posix_sh_and_not_executable(self):
        for path in (SETUP, SELFTEST):
            with self.subTest(path=path):
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(handle.readline(), "#!/bin/sh\n")
                self.assertFalse(os.stat(path).st_mode & 0o111, "Yu runs them with `sh <script>`")

    def test_design_texts_were_found(self):
        self.assertEqual(len(DESIGN_DROPIN), 5)
        self.assertEqual(len(DESIGN_AK_LINE), 1)
        self.assertTrue(DESIGN_AK_LINE[0].endswith(" ssh-ed25519 AAAA... yu-air-suite-viewer"))
        self.assertEqual(DESIGN_HOST_BLOCK[0], "Host lab-suite")
        self.assertEqual(APP_SUITE, "/Users/user/.local/share/betangel-suite/app/current/bin/suite")

    def test_air_snippet_is_exactly_the_design_host_block(self):
        self.assertEqual([line for line in HOST_AUTH + HOST_HARDENING if line not in DESIGN_HOST_BLOCK], [])
        self.assertEqual(_read(SNIPPET), "\n".join(DESIGN_HOST_BLOCK) + "\n")

    def test_staged_files_use_the_viewer_port(self):
        # ssh-session's forced command serves and attaches only on VIEWER_PORT (viewer_port_mismatch otherwise), so
        # the key's permitopen, the Air's LocalForward and the self-test must all name that one port.
        from betangel_suite import config
        from betangel_suite.api import sshsession
        port = str(sshsession.VIEWER_PORT)
        self.assertEqual(sshsession.VIEWER_PORT, config.DEFAULTS["port"])
        permitopen = r'permitopen="127\.0\.0\.1:([0-9]+)"'
        forward = r"^ *LocalForward 127\.0\.0\.1:([0-9]+) 127\.0\.0\.1:([0-9]+)$"
        options = re.findall(r"^OPTIONS='(.*)'$", _read(SETUP), re.M)
        self.assertEqual(len(options), 1)
        self.assertEqual(re.findall(permitopen, DESIGN_AK_LINE[0]), [port])
        self.assertEqual(re.findall(permitopen, options[0]), [port])
        self.assertEqual(re.findall(forward, "\n".join(DESIGN_HOST_BLOCK), re.M), [(port, port)])
        self.assertEqual(re.findall(forward, _read(SNIPPET), re.M), [(port, port)])
        self.assertEqual(re.findall(r"^VIEWER_PORT=([0-9]+)$", _read(SELFTEST), re.M), [port])

    def test_alias_points_at_the_release_copy(self):
        lines = [line for line in _read(ALIAS).splitlines() if line and not line.startswith("#")]
        self.assertEqual(lines, ["alias suite='%s'" % APP_SUITE])
        home = make_home(self)
        [(code, out, err)] = _relay_many(home, [([ZSH, "-f", "-c", "source %s; alias suite" % ALIAS],
                                                 child_env(home))])
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("suite=") and APP_SUITE in out, out)

    def test_setup_script_constants_are_the_design_texts(self):
        text = _read(SETUP)
        options = DESIGN_AK_LINE[0].split(" ssh-ed25519 ")[0]
        self.assertIn("OPTIONS='%s'\n" % options, text)
        self.assertIn("APP_SUITE=%s\n" % APP_SUITE, text)
        self.assertIn("COMMENT=yu-air-suite-viewer\n", text)
        self.assertIn("AIR_AGENT_COMMENT=%s\n" % AGENT_COMMENT, text)
        for line in DESIGN_DROPIN:
            self.assertIn("'%s'" % line, text)
            self.assertIn("'%s'" % line.lower(), text)

    def test_root_steps_only_through_run_root(self):
        code = [line for line in _read(SETUP).splitlines() if not line.lstrip().startswith("#")]
        self.assertEqual([line.strip() for line in code if re.match(r'\s*"\$SUDO"', line)], ['"$SUDO" "$@"'])
        self.assertFalse([line for line in code if re.search(r"(^|[;&|]\s*|\$\(\s*)sudo\b", line.strip())])
        self.assertFalse([line for line in code if re.search(r"(^|\s)/usr/sbin/sshd\s+-", line)])
        # Two barriers keep a dry run from sudo: run_root refuses first thing, and outside the harness a dry run's
        # SUDO is a shell function that refuses too (the real sudo is named only when DRY_RUN is 0).
        text = _read(SETUP)
        self.assertRegex(text, r'\nrun_root\(\) \{[^\n]*\n    if \[ "\$DRY_RUN" = 1 \]; then fail internal_dry_run_root '
                               r'"[^"\n]*"; fi\n    "\$SUDO" "\$@"\n\}\n')
        self.assertEqual(text.count("/usr/bin/sudo"), 1)
        self.assertIn('if [ "$DRY_RUN" = 1 ]; then SUDO=dry_run_sudo; else SUDO=/usr/bin/sudo; fi\n', text)
        self.assertRegex(text, r'\ndry_run_sudo\(\) \{[^\n]*\n    fail internal_dry_run_root "[^"\n]*"\n\}\n')
        selftest = [line for line in _read(SELFTEST).splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in selftest if re.search(r"\bsudo\b|/usr/bin/open\b|\bopen\s+http", line)])

    def test_readme_walks_through_every_step(self):
        text = _read(README)
        for needle in ("ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_lab_suite", "passphrase", ".pub",
                       "suite-viewer-setup.sh --dry-run", "air-ssh-config.snippet", "air-viewer-selftest.sh",
                       "ssh lab-suite", "Private Window", "Return", "--undo", "CLAUDE.md", "authorized_keys",
                       "verdict: PASS", "Do not add `-N`", "suite-alias.zsh"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


# --- suite-viewer-setup.sh: dry runs ---------------------------------------------------------------------

class SetupDryRunTests(unittest.TestCase):

    def test_dry_run_prints_the_design_texts_and_changes_nothing(self):
        lab = _Lab(self)
        before = _snapshot(lab.home)
        runs = [(lab.argv("--dry-run", "--test-harness", lab.key, shell=shell), lab.env()) for shell in SHELLS]
        runs.append((lab.argv("--dry-run", lab.key), lab.env()))     # the plain dry run, seam accepted
        for (argv, _env), (code, out, err) in zip(runs, _relay_many(lab.home, runs)):
            with self.subTest(argv=argv[:3]):
                self.assertEqual(code, 0, err)
                self.assertEqual(err, "")
                self.assertIn("check: key file: one ssh-ed25519 line, fingerprint %s\n" % _fingerprint(2), out)
                self.assertEqual(_indented_after(out, "plan 1: sudo /usr/bin/install -m 0644 -o root -g wheel"),
                                 DESIGN_DROPIN)
                self.assertIn("plan 1: sudo /usr/bin/install -m 0644 -o root -g wheel <temporary copy> %s,"
                              % lab.dropin, out)
                self.assertEqual(_indented_after(out, "plan 3: sudo "), [line.lower() for line in DESIGN_DROPIN])
                self.assertEqual(_indented_after(out, "plan 5: append exactly this line"),
                                 [_viewer_line(lab.viewer_key)])
                self.assertIn(" -t -f %s/sshd_config (the configuration must be valid)" % lab.etc, out)
                self.assertTrue(out.endswith("dry run: nothing was changed\n"), out)
                self.assertNotIn("yu@air", out, "the key file's own comment is not copied")
        self.assertEqual(lab.calls(), [], "a dry run never calls sudo or sshd")
        self.assertEqual(_snapshot(lab.home), before, "a dry run writes nothing")

    def test_plain_dry_run_names_the_real_tools_but_calls_none(self):
        # The plain dry run resets PATH and would name the real /usr/bin/sudo, so the recording fakes cannot see
        # it. A copy of the script with both of its own dry-run stops removed (run_root's refusal and the early
        # returns), and the real sudo's path pointed at a recorder in this HOME for safety, shows the second
        # barrier: its dry run still reaches no sudo, real or recorded, and fails on the dry-run stand-in.
        lab = _Lab(self)
        text = _read(SETUP)
        refusal = '    if [ "$DRY_RUN" = 1 ]; then fail internal_dry_run_root "a dry run must never call sudo"; fi\n'
        early = '        say "dry run: nothing was changed"\n        return 0\n'
        self.assertEqual((text.count(refusal), text.count(early), text.count("/usr/bin/sudo")), (1, 2, 1))
        recorder = os.path.join(lab.home, "real-sudo-recorder")
        _write(recorder, "#!/bin/sh\necho reached >> %s.log\nexit 1\n" % recorder, 0o700)
        mutant = os.path.join(lab.home, "mutant-setup.sh")
        _write(mutant, text.replace(refusal, "").replace(early, "        :\n").replace("/usr/bin/sudo", recorder))
        before = _snapshot(lab.etc)
        (code, out, err), (m_code, m_out, m_err) = _relay_many(
            lab.home, [(lab.argv("--dry-run", lab.key), lab.env()), (["/bin/sh", mutant, "--dry-run", lab.key], lab.env())])
        self.assertEqual(code, 0, err)
        self.assertIn("plan 2: sudo /usr/sbin/sshd -t -f %s/sshd_config" % lab.etc, out)
        self.assertIn("note: HOME is not /Users/user", out)
        self.assertEqual((m_code, _codes(m_err)), (1, ["internal_dry_run_root"]), m_out + m_err)
        self.assertFalse(os.path.lexists(recorder + ".log"), "a dry run reached the sudo path")
        self.assertEqual(lab.calls(), [])
        self.assertEqual(_snapshot(lab.etc), before)

    def test_dry_run_undo_lists_the_changes_and_changes_nothing(self):
        lab = _Lab(self)
        _write(lab.ak, lab.ak_text + _viewer_line(lab.viewer_key) + "\n")
        _write(lab.dropin, "\n".join(DESIGN_DROPIN) + "\n", 0o644)
        before = _snapshot(lab.home)
        code, out, err = lab.run("--dry-run", "--test-harness", "--undo")
        self.assertEqual(code, 0, err)
        self.assertIn("check: 1 viewer line(s) in %s" % lab.ak, out)
        self.assertIn("plan 2: remove the 1 viewer line(s) from %s" % lab.ak, out)
        self.assertIn("plan 3: sudo /bin/rm -f %s" % lab.dropin, out)
        self.assertIn("(if it fails, the drop-in is put back)", out)
        self.assertEqual(lab.calls(), [])
        self.assertEqual(_snapshot(lab.home), before)

    def test_undo_with_nothing_installed_does_nothing(self):
        lab = _Lab(self)
        before = _snapshot(lab.home)
        code, out, err = lab.run("--test-harness", "--undo")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("nothing to undo", out)
        self.assertEqual(lab.calls(), [])
        self.assertEqual(_snapshot(lab.home), before)


# --- suite-viewer-setup.sh: refusals ---------------------------------------------------------------------

class SetupRefusalTests(unittest.TestCase):

    def assert_refusals(self, lab, cases):
        """cases: (label, args, env, code). Each must refuse with exactly that code, call nothing, write nothing."""
        before = _snapshot(lab.home)
        runs = [(lab.argv(*args), env) for _label, args, env, _code in cases]
        results = _relay_many(lab.home, runs)
        for (label, _args, _env, expected), (code, out, err) in zip(cases, results):
            with self.subTest(case=label):
                self.assertEqual(code, 2, out + err)
                self.assertEqual(_codes(err), [expected], err)
                self.assertNotIn("plan 1:", out)
        self.assertEqual(lab.calls(), [])
        self.assertEqual(_snapshot(lab.home), before)
        return results

    def test_bad_key_files_are_refused(self):
        lab = _Lab(self)
        key = _pubkey(5)
        rsa = base64.b64encode(_blob(6, b"ssh-rsa")).decode("ascii")
        dash5 = "-" * 5
        private = _j(dash5, "BEGIN OPENSSH ", "PRIVATE", " KEY", dash5, "\n", "b3Blbn", "NzaC1rZXktdjEAAAAA\n",
                     dash5, "END OPENSSH ", "PRIVATE", " KEY", dash5, "\n")
        files = {
            "two lines": ("ssh-ed25519 %s a\nssh-ed25519 %s b\n" % (key, _pubkey(7)), "key_file_lines"),
            "rsa": ("ssh-rsa %s yu@air\n" % rsa, "key_type_not_ed25519"),
            "ecdsa": ("ecdsa-sha2-nistp256 %s yu@air\n" % key, "key_type_not_ed25519"),
            "security key": ("sk-ssh-ed25519@openssh.com %s yu@air\n" % key, "key_type_not_ed25519"),
            "restrict prefix": ("restrict ssh-ed25519 %s yu@air\n" % key, "key_has_options"),
            "command prefix": ('command="/bin/sh" ssh-ed25519 %s yu@air\n' % key, "key_has_options"),
            "from prefix": ('from="192.0.2.1" ssh-ed25519 %s yu@air\n' % key, "key_has_options"),
            "private key": (private, "private_key_file"),
            "empty": ("", "key_file_empty"),
            "no comment": ("ssh-ed25519 %s\n" % key, "key_comment_missing"),
            "odd comment": ("ssh-ed25519 %s yu;air\n" % key, "key_comment_invalid"),
            "short blob": ("ssh-ed25519 %s yu@air\n" % key[:-4], "key_blob_invalid"),
            "rsa blob labelled ed25519": ("ssh-ed25519 %s yu@air\n" % rsa[:68], "key_blob_invalid"),
            "tab": ("ssh-ed25519\t%s yu@air\n" % key, "key_file_bytes"),
            "crlf": ("ssh-ed25519 %s yu@air\r\n" % key, "key_file_bytes"),
            "not ascii": ("ssh-ed25519 %s caf\u00e9\n" % key, "key_file_bytes"),
            "two spaces": ("ssh-ed25519  %s yu@air\n" % key, "key_line_format"),
        }
        cases = []
        for label, (text, expected) in files.items():
            path = os.path.join(lab.home, "keys", label.replace(" ", "-") + ".pub")
            _write(path, text, 0o644)
            cases.append((label, ("--dry-run", "--test-harness", path), lab.env(), expected))
        missing = os.path.join(lab.home, "keys", "missing.pub")
        link = os.path.join(lab.home, "keys", "link.pub")
        os.symlink(lab.key, link)
        cases += [("missing", ("--dry-run", "--test-harness", missing), lab.env(), "key_file_missing"),
                  ("symlink", ("--dry-run", "--test-harness", link), lab.env(), "key_file_missing")]
        results = self.assert_refusals(lab, cases)
        self.assertNotIn("b3Blbn", "".join(out + err for _code, out, err in results), "a key file is never echoed")

    def test_keys_already_in_authorized_keys_are_refused(self):
        lab = _Lab(self)
        agent_file = os.path.join(lab.home, "keys", "agent.pub")
        _write(agent_file, "ssh-ed25519 %s copied\n" % lab.agent_key, 0o644)
        self.assert_refusals(lab, [("agent key", ("--dry-run", "--test-harness", agent_file), lab.env(),
                                    "key_is_air_agent_key")])
        for label, extra, expected in (
                ("same key, other line", "ssh-ed25519 %s old-laptop\n" % lab.viewer_key, "key_already_present"),
                ("installed", _viewer_line(lab.viewer_key) + "\n", "viewer_key_already_installed"),
                ("another viewer line", _viewer_line(_pubkey(9)) + "\n", "viewer_line_present")):
            with self.subTest(case=label):
                _write(lab.ak, lab.ak_text + extra)
                self.assert_refusals(lab, [(label, ("--dry-run", "--test-harness", lab.key), lab.env(), expected)])

    def test_authorized_keys_and_release_problems_are_refused(self):
        lab = _Lab(self)
        for label, change, expected in (
                ("no release copy", lambda: os.remove(lab.app), "release_missing"),
                ("group-writable authorized_keys", lambda: os.chmod(lab.ak, 0o620), "authorized_keys_mode"),
                ("world-writable .ssh", lambda: os.chmod(lab.ssh, 0o703), "authorized_keys_mode"),
                ("no authorized_keys", lambda: os.remove(lab.ak), "authorized_keys_missing")):
            with self.subTest(case=label):
                change()
                self.assert_refusals(lab, [(label, ("--dry-run", "--test-harness", lab.key), lab.env(), expected)])

    def test_sshd_layout_problems_are_refused(self):
        lab = _Lab(self)
        no_include = SSHD_CONFIG.replace("Include /etc/ssh/sshd_config.d/*\n", "")
        layouts = {
            "no Include": ({"sshd_config": no_include}, "sshd_include_missing"),
            "Include after Match": ({"sshd_config": no_include + "Match User nobody\n"
                                     "Include /etc/ssh/sshd_config.d/*\n"}, "sshd_include_after_match"),
            "macos drop-in sets a keyword": ({"sshd_config.d/100-macos.conf": MACOS_CONF + "AllowTcpForwarding yes\n"},
                                             "sshd_keyword_conflict"),
            "crypto.conf sets a keyword": ({"crypto/apple.conf": CRYPTO_CONF + "ClientAliveInterval 30\n"},
                                           "sshd_keyword_conflict"),
            "a Match block sets a keyword": ({"sshd_config": SSHD_CONFIG + "Match Address 192.0.2.0/24\n"
                                              "\tPermitListen any\n"}, "sshd_keyword_conflict"),
            "equals form": ({"sshd_config": SSHD_CONFIG + "ClientAliveCountMax=3\n"}, "sshd_keyword_conflict"),
            "a later drop-in, lower case": ({"sshd_config.d/300-other.conf": "allowstreamlocalforwarding yes\n"},
                                            "sshd_keyword_conflict"),
            "nested Include": ({"crypto/apple.conf": CRYPTO_CONF + "Include /etc/ssh/more.conf\n",
                                "more.conf": "LogLevel INFO\n"}, "sshd_include_nested"),
            "Include outside /etc/ssh": ({"sshd_config.d/100-macos.conf": MACOS_CONF + "Include /opt/x.conf\n"},
                                         "sshd_include_unexpected"),
            "a quoted Include": ({"sshd_config.d/100-macos.conf": MACOS_CONF + 'Include "/etc/ssh/crypto.conf"\n'},
                                 "sshd_include_unexpected"),
            "an Include with ..": ({"sshd_config.d/100-macos.conf": MACOS_CONF + "Include /etc/ssh/../x.conf\n"},
                                   "sshd_include_unexpected"),
            "a different 200-lab.conf": ({"sshd_config.d/200-lab.conf": "AllowTcpForwarding yes\n"},
                                         "dropin_differs"),
            "no sshd_config": ({"sshd_config": None}, "sshd_config_missing"),
        }
        cases = []
        for index, (label, (changes, expected)) in enumerate(layouts.items()):
            etc = lab.make_etc("etc-%d" % index, **changes)
            cases.append((label, ("--dry-run", "--test-harness", lab.key), lab.env(SUITE_STAGE_SSH_DIR=etc),
                          expected))
        self.assert_refusals(lab, cases)

    def test_commented_keywords_and_our_own_dropin_are_fine(self):
        lab = _Lab(self)
        _write(lab.dropin, "\n".join(DESIGN_DROPIN) + "\n", 0o644)
        code, out, err = lab.run("--dry-run", "--test-harness", lab.key)
        self.assertEqual(code, 0, err)
        self.assertIn("plan 1: %s already holds exactly the drop-in: left as is" % lab.dropin, out)

    def test_usage_and_seams_are_refused(self):
        lab = _Lab(self)
        no_seam = lab.env(SUITE_STAGE_SSH_DIR=None)
        cases = [
            ("no arguments", (), no_seam, "usage"),
            ("two key files", ("--dry-run", lab.key, lab.key), no_seam, "usage"),
            ("undo with a key", ("--dry-run", "--undo", lab.key), no_seam, "usage"),
            ("unknown option", ("--dry-run", "--force", lab.key), no_seam, "usage"),
            # Real mode (no --dry-run, no --test-harness): each refuses before any check or sudo.
            ("ssh dir seam without a dry run", (lab.key,), lab.env(), "seam_needs_dry_run"),
            ("fault seam without the harness", ("--dry-run", lab.key), lab.env(SUITE_STAGE_FAULT="after_append"),
             "seam_needs_harness"),
            ("a HOME that is not /Users/user", (lab.key,), no_seam, "home_mismatch"),
            ("undo, a HOME that is not /Users/user", ("--undo",), no_seam, "home_mismatch"),
        ]
        self.assert_refusals(lab, cases)

    def test_the_harness_refuses_anything_but_fakes_in_a_temporary_home(self):
        lab = _Lab(self)
        plain = os.path.join(lab.home, "plainbin")
        _write(os.path.join(plain, "sudo"), "#!/bin/sh\nexit 0\n", 0o700)
        _write(os.path.join(plain, "sshd"), "#!/bin/sh\nexit 0\n", 0o700)
        linked = os.path.join(lab.home, "linkbin")
        os.makedirs(linked)
        os.symlink(os.path.join(lab.bin, "sudo"), os.path.join(linked, "sudo"))
        os.symlink(os.path.join(lab.bin, "sshd"), os.path.join(linked, "sshd"))
        outside = os.path.join(lab.home, "..", "outside-etc")
        os.makedirs(outside)
        harness = ("--dry-run", "--test-harness", lab.key)
        cases = [
            ("real sudo on PATH", harness, lab.env(PATH="/usr/bin:/bin:/usr/sbin"), "harness_sudo_not_fake"),
            ("unmarked fakes", harness, lab.env(PATH=plain + ":/usr/bin:/bin"), "harness_sudo_not_fake"),
            ("a symlinked fake", harness, lab.env(PATH=linked + ":/usr/bin:/bin"), "harness_sudo_not_fake"),
            ("no ssh dir", harness, lab.env(SUITE_STAGE_SSH_DIR=None), "harness_ssh_dir"),
            ("an ssh dir outside HOME", harness, lab.env(SUITE_STAGE_SSH_DIR=outside), "harness_ssh_dir"),
            ("a HOME outside the test tmp", harness, lab.env(HOME="/var/empty"), "harness_home"),
            ("the state tmp itself as HOME", harness,
             lab.env(HOME=os.path.dirname(os.path.dirname(lab.home))), "harness_home"),
        ]
        self.assert_refusals(lab, cases)
        self.assertEqual(sorted(os.listdir(outside)), [])


# --- suite-viewer-setup.sh: full runs in the harness ---------------------------------------------------------

class SetupHarnessRunTests(unittest.TestCase):

    def expected_calls(self, lab):
        conf = os.path.join(lab.etc, "sshd_config")
        sshd = os.path.join(lab.bin, "sshd")
        return [("sudo /usr/bin/install -m 0644 -o root -g wheel ", " " + lab.dropin),
                ("sudo %s -t -f %s" % (sshd, conf), ""), ("sshd -t -f %s" % conf, ""),
                ("sudo %s -T -f %s" % (sshd, conf), ""), ("sshd -T -f %s" % conf, "")]

    def assert_calls(self, calls, expected):
        self.assertEqual(len(calls), len(expected), calls)
        for call, (head, tail) in zip(calls, expected):
            self.assertTrue(call.startswith(head) and call.endswith(tail), (call, head, tail))

    def backups(self, lab):
        return sorted(name for name in os.listdir(lab.ssh) if name.startswith("authorized_keys.bak-suite-viewer-"))

    def test_install_then_undo(self):
        lab = _Lab(self)
        code, out, err = lab.run("--test-harness", lab.key)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(_read(lab.ak), lab.ak_text + _viewer_line(lab.viewer_key) + "\n")
        self.assertEqual(stat.S_IMODE(os.stat(lab.ak).st_mode), 0o600)
        self.assertEqual(_read(lab.dropin), "\n".join(DESIGN_DROPIN) + "\n")
        [backup] = self.backups(lab)
        self.assertEqual(_read(os.path.join(lab.ssh, backup)), lab.ak_text)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(lab.ssh, backup)).st_mode), 0o600)
        self.assert_calls(lab.calls(), self.expected_calls(lab))
        self.assertIn("done: the viewer key is installed", out)
        self.assertIn("fingerprint: %s" % _fingerprint(2), out)
        self.assertEqual([name for name in os.listdir(os.path.join(lab.home, ".local", "state", "betangel-suite",
                                                                   "tmp"))], [], "the work dir is removed")

        code, out, err = lab.run("--test-harness", lab.key)
        self.assertEqual((code, _codes(err)), (2, ["viewer_key_already_installed"]))

        os.remove(lab.log)
        code, out, err = lab.run("--test-harness", "--undo")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(_read(lab.ak), lab.ak_text)
        self.assertFalse(os.path.exists(lab.dropin))
        self.assertEqual(len(self.backups(lab)), 2)
        conf = os.path.join(lab.etc, "sshd_config")
        self.assertEqual(lab.calls(), ["sudo /bin/rm -f %s" % lab.dropin,
                                       "sudo %s -t -f %s" % (os.path.join(lab.bin, "sshd"), conf),
                                       "sshd -t -f %s" % conf])

    def test_a_missing_newline_at_the_end_of_authorized_keys_is_kept_apart(self):
        lab = _Lab(self)
        _write(lab.ak, lab.ak_text.rstrip("\n"))
        code, out, err = lab.run("--test-harness", lab.key)
        self.assertEqual(code, 0, err)
        self.assertEqual(_read(lab.ak), lab.ak_text + _viewer_line(lab.viewer_key) + "\n")

    def test_each_failure_puts_both_files_back(self):
        # Independent labs, one failure each, run side by side.
        fault = {"SUITE_STAGE_FAULT": "after_append"}
        labs = {"sshd -t fails": (_Lab(self), "t-fails-with-dropin", {}),
                "sshd -T shows other values": (_Lab(self), "T-ignores-dropin", {}),
                "a failure after the append": (_Lab(self), None, fault),
                "a failure with our drop-in already there": (_Lab(self), None, fault),
                "root installed other text": (_Lab(self), None, {})}
        for lab, mode, _env in labs.values():
            if mode:
                lab.sshd_mode(mode)
        labs["root installed other text"][0].sudo_mode("install-alters")
        identical = labs["a failure with our drop-in already there"][0]
        _write(identical.dropin, "\n".join(DESIGN_DROPIN) + "\n", 0o644)
        runs = [(lab.argv("--test-harness", lab.key), lab.env(**env)) for lab, _mode, env in labs.values()]
        results = dict(zip(labs, _relay_many(identical.home, runs)))
        for label, (lab, _mode, _env) in labs.items():
            with self.subTest(case=label):
                code, out, err = results[label]
                self.assertEqual(code, 1, out + err)
                self.assertEqual(_read(lab.ak), lab.ak_text, "authorized_keys is as before")
                self.assertEqual(os.path.exists(lab.dropin), lab is identical, "only a drop-in we did not write stays")
                self.assertIn("rollback: complete; nothing is left changed", err)

        lab = labs["sshd -t fails"][0]
        code, out, err = results["sshd -t fails"]
        self.assertEqual(_codes(err), ["sshd_t_failed"])
        self.assertEqual(self.backups(lab), [], "authorized_keys was never touched")
        sshd = os.path.join(lab.bin, "sshd")
        self.assertEqual(lab.calls()[-3:], ["sudo /bin/rm -f %s" % lab.dropin,
                                            "sudo %s -t -f %s/sshd_config" % (sshd, lab.etc),
                                            "sshd -t -f %s/sshd_config" % lab.etc])

        code, out, err = results["sshd -T shows other values"]
        self.assertEqual(_codes(err), ["sshd_effective_mismatch"])
        self.assertIn("expected, not in sshd -T: permitlisten none", err)

        lab = labs["a failure after the append"][0]
        code, out, err = results["a failure after the append"]
        self.assertEqual(_codes(err), ["injected_after_append"])
        self.assertIn("rollback: put authorized_keys back from", err)
        self.assertEqual(len(self.backups(lab)), 1, "the backup stays for Yu")

        code, out, err = results["a failure with our drop-in already there"]
        self.assertEqual(_codes(err), ["injected_after_append"])
        self.assertFalse([call for call in identical.calls() if "install" in call or "/bin/rm" in call],
                         "a drop-in that was already there is never written or removed")

        # The installed file is compared with the fixed text, not with the script's own (user-writable) copy.
        lab = labs["root installed other text"][0]
        code, out, err = results["root installed other text"]
        self.assertEqual(_codes(err), ["dropin_verify"])
        self.assertEqual(self.backups(lab), [], "authorized_keys was never touched")
        self.assertEqual(lab.calls()[1:], ["sudo /bin/rm -f %s" % lab.dropin,
                                           "sudo %s -t -f %s/sshd_config" % (os.path.join(lab.bin, "sshd"), lab.etc),
                                           "sshd -t -f %s/sshd_config" % lab.etc])

    def test_undo_puts_the_dropin_back_when_sshd_t_fails_without_it(self):
        lab = _Lab(self)
        code, out, err = lab.run("--test-harness", lab.key)
        self.assertEqual(code, 0, err)
        lab.sshd_mode("t-fails-without-dropin")
        # A second lab, installed by hand, where the undo's saved copy of the drop-in changes before root would put
        # it back: that copy lies in a directory this user can write, so it is checked against the fixed text first
        # and a changed one is left out (Yu is told). Both undos run side by side.
        tampered = _Lab(self)
        _write(tampered.ak, tampered.ak_text + _viewer_line(tampered.viewer_key) + "\n")
        _write(tampered.dropin, "\n".join(DESIGN_DROPIN) + "\n", 0o644)
        tampered.sshd_mode("t-fails-without-dropin")
        tampered.sudo_mode("rm-tampers-saved")
        (code, out, err), (t_code, t_out, t_err) = _relay_many(lab.home, [
            (lab.argv("--test-harness", "--undo"), lab.env()), (tampered.argv("--test-harness", "--undo"), tampered.env())])
        self.assertEqual((code, _codes(err)), (1, ["sshd_t_failed_after_undo"]), out + err)
        self.assertEqual(_read(lab.ak), lab.ak_text, "the viewer line stays removed")
        self.assertEqual(_read(lab.dropin), "\n".join(DESIGN_DROPIN) + "\n", "the drop-in is back")
        self.assertIn("rollback: put the drop-in back; sshd -t ok", err)
        self.assertIn("the viewer line stays removed", err)

        self.assertEqual((t_code, _codes(t_err)), (1, ["sshd_t_failed_after_undo"]), t_out + t_err)
        self.assertIn("ROLLBACK PROBLEM: the saved drop-in changed, so it was not put back", t_err)
        self.assertFalse(os.path.exists(tampered.dropin))
        self.assertEqual(_read(tampered.ak), tampered.ak_text, "the viewer line stays removed")
        self.assertFalse([call for call in tampered.calls() if "install" in call], tampered.calls())


# --- air-viewer-selftest.sh against a fake lab -------------------------------------------------------------

FAKE_SSH = """#!/bin/sh
# Stands in for ssh in tests/test_stage.py: it answers like a lab in the scenario $FAKE_STATE/scenario names,
# and never connects anywhere. Each argv goes to $FAKE_STATE/ssh-argv, one line, each argument followed by a tab.
S=$FAKE_STATE
scenario=$(cat "$S/scenario")
{ printf '%s\\t' "$@"; printf '\\n'; } >> "$S/ssh-argv"
log=/dev/null gflag= nflag= tty= wflag= L= R= cmd= auth=0 opts=
while [ $# -gt 0 ]; do
    case "$1" in
        -v|-T) shift ;;
        -G) gflag=1; shift ;;
        -N) nflag=1; shift ;;
        -tt) tty=1; shift ;;
        -E) log=$2; shift 2 ;;
        -W) wflag=$2; shift 2 ;;
        -L) L="$L $2"; shift 2 ;;
        -R) R="$R $2"; shift 2 ;;
        -o) opts="$opts $2"
            case "$2" in
                PreferredAuthentications=publickey|PasswordAuthentication=no|KbdInteractiveAuthentication=no)
                    auth=$((auth + 1)) ;;
            esac
            shift 2 ;;
        -*) echo 'fake ssh: unexpected option' >&2; exit 64 ;;
        *) host=$1; shift; cmd="$*"; break ;;
    esac
done
[ "$host" = lab-suite ] || exit 64
if [ -n "$gflag" ]; then
    # ssh -G reads the config and connects nowhere. This prints $S/ssh-G (the config as the plain form sees it),
    # changed by what a Match block gives this form, $S/ssh-G-FORM: identityfile and the forward keys add up, and
    # any other key replaces the plain value. The -o options come first and win (ssh keeps the first value). Then
    # the -L and -R options, as OpenSSH 10.2's ssh -G prints them: a -L to a Unix socket also shows as a
    # dynamicforward line. As in OpenSSH, -W drops every forward unless clearallforwardings is no.
    [ -f "$S/ssh-G" ] || { echo 'fake ssh: cannot read the config' >&2; exit 255; }
    form=plain
    if [ -n "$wflag" ]; then form=stdio; elif [ -n "$L" ]; then form=local; elif [ -n "$R" ]; then form=remote
    elif [ -n "$tty" ]; then form=pty; elif [ -n "$cmd" ]; then form=command; fi
    awk -v given="$opts" -v block="$S/ssh-G-$form" -v stdio="$wflag" '
        function fwd(key) { return key == "localforward" || key == "remoteforward" || key == "dynamicforward" }
        BEGIN {
            n = split(given, o, " ")
            for (i = 1; i <= n; i++) {
                eq = index(o[i], "=")
                k = tolower(substr(o[i], 1, eq - 1))
                cl[k] = 1
                print k, substr(o[i], eq + 1)
            }
            while ((getline line < block) > 0) {
                split(line, f, " ")
                k = tolower(f[1])
                if (k in cl) continue
                if (k == "clearallforwardings" && f[2] == "no") keep = 1
                if (k != "identityfile" && !fwd(k)) set[k] = 1
                extra[++m] = line
            }
            drop = stdio != "" && !keep
            for (i = 1; i <= m; i++) {
                split(extra[i], f, " ")
                if (!(drop && fwd(tolower(f[1])))) print extra[i]
            }
        }
        { k = tolower($1) }
        (k in cl) || (k in set) || (drop && fwd(k)) { next }
        { print }
    ' "$S/ssh-G"
    for spec in $L; do
        rest=${spec#127.0.0.1:}
        to=${rest#*:}
        case "$to" in
            /*) printf 'localforward [127.0.0.1]:%s %s\\n' "${rest%%:*}" "$to"
                printf 'dynamicforward [127.0.0.1]:%s\\n' "${rest%%:*}" ;;
            *) printf 'localforward [127.0.0.1]:%s [%s]:%s\\n' "${rest%%:*}" "${to%:*}" "${to##*:}" ;;
        esac
    done
    for spec in $R; do
        case "$spec" in
            /*) to=${spec#*:}; printf 'remoteforward %s [%s]:%s\\n' "${spec%%:*}" "${to%:*}" "${to##*:}" ;;
            *) rest=${spec#127.0.0.1:}; to=${rest#*:}
               printf 'remoteforward [127.0.0.1]:%s [%s]:%s\\n' "${rest%%:*}" "${to%:*}" "${to##*:}" ;;
        esac
    done
    exit 0
fi
# Every login must carry the three public-key-only options, so no real probe could reach a Password: prompt.
[ "$auth" = 3 ] || { echo 'fake ssh: login without the public-key-only options' >&2; exit 64; }
if [ "$scenario" = noauth ]; then
    echo 'user@192.168.50.88: Permission denied (publickey).' >> "$log"
    exit 255
fi
# What ssh -v logs about keys. In the six scenarios below the lab refuses everything, as in secure, but the log
# shows: otherkey, another key accepted; trykey, the viewer key tried without an offer; secondkey, the viewer key
# accepted and then another key tried; offerother, another key offered before the viewer key was accepted;
# attemptother, another key listed, as when a Match block adds one, but never offered, because the viewer key was
# accepted first; acceptother, a lone line accepting another key.
viewer="$HOME/.ssh/id_ed25519_lab_suite ED25519 SHA256:fake explicit"
other="$HOME/.ssh/id_ed25519 ED25519 SHA256:fake explicit"
keylog() { for line in "$@"; do printf 'debug1: %s\\n' "$line"; done; }
case "$scenario" in
    otherkey) keylog "Will attempt key: $other" "Offering public key: $other" "Server accepts key: $other" ;;
    trykey) keylog "Will attempt key: $HOME/.ssh/id_ed25519_lab_suite " \\
                "Trying private key: $HOME/.ssh/id_ed25519_lab_suite" ;;
    secondkey) keylog "Will attempt key: $viewer" "Offering public key: $viewer" "Server accepts key: $viewer" \\
                   "Trying private key: $HOME/.ssh/id_ed25519" ;;
    offerother) keylog "Will attempt key: $other" "Will attempt key: $viewer" "Offering public key: $other" \\
                    "Offering public key: $viewer" "Server accepts key: $viewer" ;;
    attemptother) keylog "Will attempt key: $viewer" "Will attempt key: $other" "Offering public key: $viewer" \\
                      "Server accepts key: $viewer" ;;
    acceptother) keylog "Will attempt key: $viewer" "Offering public key: $viewer" "Server accepts key: $viewer" \\
                     "Server accepts key: $other" ;;
    *) keylog "Will attempt key: $viewer" "Offering public key: $viewer" "Server accepts key: $viewer" ;;
esac >> "$log"
echo 'Authenticated to 192.168.50.88 ([192.168.50.88]:22) using "publickey".' >> "$log"
case "$scenario" in otherkey|trykey|secondkey|offerother|attemptother|acceptother) scenario=secure ;; esac
if [ -n "$wflag" ]; then
    cat > /dev/null
    if [ "$scenario" = secure ]; then
        echo 'channel 0: open failed: administratively prohibited: open failed' >> "$log"
        echo 'stdio forwarding failed' >> "$log"
        exit 255
    fi
    echo 'SSH-2.0-OpenSSH_fake'
    exit 0
fi
if [ -z "$nflag" ]; then
    if [ -n "$tty" ] && [ "$scenario" = secure ]; then echo 'PTY allocation request failed on channel 0' >> "$log"; exit 255; fi
    if [ "$scenario" = secure ] || [ -n "$tty" ]; then echo 'refused:ssh_original_command' >&2; exit 2; fi
    printf '%s\\n' "${cmd#echo }"
    exit 0
fi
for spec in $L; do
    rest=${spec#127.0.0.1:}
    port=${rest%%:*}
    printf '%s %s\\n' "${rest#*:}" "$log" > "$S/listen-$port"
    echo "debug1: Local forwarding listening on 127.0.0.1 port $port." >> "$log"
done
for spec in $R; do
    case "$spec" in
        127.0.0.1:0:*)
            if [ "$scenario" = leaky ]; then
                echo 'debug1: remote forward success for: listen 127.0.0.1:0, connect 127.0.0.1:9' >> "$log"
            else
                echo 'Warning: remote port forwarding failed for listen port 0' >> "$log"
            fi ;;
        /*) echo "Warning: remote port forwarding failed for listen path ${spec%%:*}" >> "$log" ;;
    esac
done
trap 'rm -f "$S"/listen-*; kill $sleeper 2>/dev/null; exit 143' TERM INT
/bin/sleep 20 &
sleeper=$!
wait $sleeper
rm -f "$S"/listen-*
"""

FAKE_NC = """#!/bin/sh
# Stands in for nc in tests/test_stage.py: answers from the fake ssh's listen files; opens no socket.
S=$FAKE_STATE
z=
for a in "$@"; do
    if [ "$a" = -z ]; then z=1; fi
    port=$a
done
if [ -n "$z" ]; then
    if [ "$port" = 8765 ]; then [ -f "$S/viewer-port-busy" ]; exit $?; fi
    [ -f "$S/listen-$port" ]
    exit $?
fi
[ -f "$S/listen-$port" ] || exit 1
cat > /dev/null
read target log < "$S/listen-$port"
if [ "$(cat "$S/scenario")" != leaky ]; then
    echo 'channel 3: open failed: administratively prohibited: open failed' >> "$log"
    exit 0
fi
case "$target" in
    *:22) echo 'SSH-2.0-OpenSSH_fake' ;;
    *) echo 'channel 3: open failed: connect failed: Connection refused' >> "$log" ;;
esac
"""

SSH_G = """User user
hostname 192.168.50.88
addressfamily inet
identitiesonly yes
kbdinteractiveauthentication no
passwordauthentication no
preferredauthentications publickey
addkeystoagent false
exitonforwardfailure yes
stricthostkeychecking true
requesttty false
localforward [127.0.0.1]:8765 [127.0.0.1]:8765
identityfile ~/.ssh/id_ed25519_lab_suite
controlmaster false
permitlocalcommand no
proxyusefdpass no
identityagent none
controlpersist no
"""
# What OpenSSH 10.2's ssh -G prints when a later `Host *` block shares connections (checked with a scratch -F
# config, no connection): the lab-suite block sets none of the four, so they come from Host *.
SHARED = ("controlmaster auto\ncontrolpath /tmp/cm-user@192.168.50.88:22\ncontrolpersist yes\n"
          "identityagent /tmp/agent.sock\n")

# What OpenSSH 10.2's ssh -G prints for authentication when the block sets none of it (checked with a scratch -F
# config, no connection): password and keyboard-interactive on, and no preferredauthentications line.
PASSWORD_DEFAULTS = "kbdinteractiveauthentication yes\npasswordauthentication yes\n"

def _strip_auth(ssh_g):
    """ssh -G output less the three authentication lines."""
    return "".join(line for line in ssh_g.splitlines(keepends=True) if line.split(" ", 1)[0] not in
                   ("kbdinteractiveauthentication", "passwordauthentication", "preferredauthentications"))

def _strip_hardening(ssh_g):
    """ssh -G output less the lines the hardening sets (what the DESIGN block alone leaves to other blocks)."""
    return "".join(line for line in ssh_g.splitlines(keepends=True)
                   if line.split(" ", 1)[0] not in ("controlmaster", "controlpersist", "identityagent"))


ITEMS = ("1 a requested command", "2 a PTY", "3 -L to another port", "4 -L to another host",
         "5 -L to another name", "6 -L to a Unix socket", "7 -W host:22", "8 -R TCP", "9 -R Unix socket")

# The six forms the self-test checks with ssh -G before any login (the fake ssh's names), and the words its
# refusal uses for each.
FORMS = {"plain": "ssh lab-suite", "command": "probe 1 (", "pty": "probe 2 (", "local": "probes 3-6 (",
         "stdio": "probe 7 (", "remote": "probes 8-9 ("}
OTHER_KEY = "identityfile ~/.ssh/id_ed25519\n"
PASSWORD_ON = "passwordauthentication yes\nkbdinteractiveauthentication yes\npreferredauthentications password\n"


def _ssh_calls(state):
    """[(kind, argv)] for each fake ssh call in a state directory: "G" for ssh -G (argv after -G), "login" for a
    login (argv after -v -E LOG)."""
    calls = []
    for line in _read(os.path.join(state, "ssh-argv")).splitlines():
        argv = line.split("\t")[:-1]
        if argv[:1] == ["-G"]:
            calls.append(("G", argv[1:]))
        elif argv[:2] == ["-v", "-E"]:
            calls.append(("login", argv[3:]))
        else:
            calls.append(("other", argv))
    return calls


class SelfTestScriptTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)
        self.bin = os.path.join(self.home, "fakebin")
        _link_fake("ssh", FAKE_SSH, self.bin)
        _link_fake("nc", FAKE_NC, self.bin)
        _write(os.path.join(self.home, ".ssh", "id_ed25519_lab_suite"), "placeholder, not a key\n")

    def state(self, name, scenario, ssh_g=SSH_G, busy=False, blocks=None):
        """The environment for one run. ssh_g is what ssh -G prints for the plain form (None: ssh -G fails), and
        blocks maps a form to what a Match block adds to it or changes in it."""
        path = os.path.join(self.home, "state-" + name)
        _write(os.path.join(path, "scenario"), scenario + "\n")
        if ssh_g is not None:
            _write(os.path.join(path, "ssh-G"), ssh_g)
        for form, block in (blocks or {}).items():
            _write(os.path.join(path, "ssh-G-" + form), block)
        if busy:
            _write(os.path.join(path, "viewer-port-busy"), "")
        return child_env(self.home, PATH=self.bin + ":/usr/bin:/bin", FAKE_STATE=path,
                         SELFTEST_AUTH_TIMEOUT="5", SELFTEST_STEP_TIMEOUT="3")

    @staticmethod
    def statuses(out):
        found = {}
        for line in out.splitlines():
            match = re.match(r"^  (refused|ALLOWED|unclear) +([1-9]) (.+?)(?:  \(.*\))?$", line)
            if match:
                found[match.group(2) + " " + match.group(3)] = match.group(1)
        return found

    def test_scenarios(self):
        runs = [(["/bin/sh", SELFTEST], self.state("secure", "secure")),
                (["/bin/sh", SELFTEST], self.state("leaky", "leaky")),
                (["/bin/sh", SELFTEST], self.state("noauth", "noauth")),
                (["/bin/sh", SELFTEST], self.state("otherkey", "otherkey"))]
        before = _snapshot(os.path.join(self.home, ".local", "state", "betangel-suite", "tmp"))
        secure, leaky, noauth, otherkey = _relay_many(self.home, runs)

        code, out, err = secure
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.statuses(out), {item: "refused" for item in ITEMS})
        self.assertTrue(out.endswith("verdict: PASS (9 of 9 refused)\n"), out)
        # ssh -G ran for the plain form and then for each login's exact arguments, all before the first login.
        calls = _ssh_calls(os.path.join(self.home, "state-secure"))
        self.assertEqual([kind for kind, _argv in calls], ["G"] * 6 + ["login"] * 5, calls)
        self.assertEqual(calls[0][1], ["lab-suite"])
        self.assertEqual([argv for _kind, argv in calls[6:]], [argv for _kind, argv in calls[1:6]])

        code, out, err = leaky
        self.assertEqual(code, 1, out + err)
        expected = {item: "ALLOWED" for item in ITEMS}
        expected["9 -R Unix socket"] = "refused"
        self.assertEqual(self.statuses(out), expected)
        self.assertIn("verdict: FAIL (8 of 9 ALLOWED): remove the key now", out)

        code, out, err = noauth
        self.assertEqual(code, 3, out + err)
        self.assertEqual(self.statuses(out), {item: "unclear" for item in ITEMS})
        self.assertIn("verdict: INCONCLUSIVE (0 of 9 refused", out)

        code, out, err = otherkey      # the lab refused everything, but another key logged in: never a PASS
        self.assertEqual(code, 3, out + err)
        self.assertEqual(self.statuses(out), {item: "unclear" for item in ITEMS})

        after = _snapshot(os.path.join(self.home, ".local", "state", "betangel-suite", "tmp"))
        self.assertEqual(after, before, "the work dir is removed")
        for name in ("secure", "leaky", "noauth", "otherkey"):
            self.assertEqual([entry for entry in os.listdir(os.path.join(self.home, "state-" + name))
                              if entry.startswith("listen-")], [], "every fake ssh was stopped")

    def test_the_log_must_show_the_viewer_key_and_no_other(self):
        # The lab refuses everything in each of these, but the ssh -v log does not show a login with the viewer key
        # alone: the key was tried without an offer (trykey), another key was tried after the viewer key was
        # accepted (secondkey), another key was offered first (offerother), another key was listed but never
        # offered because the viewer key was accepted first (attemptother: "Will attempt key"), or another key was
        # accepted (acceptother: "Server accepts key"). No probe counts as refused. The last two each rest on one
        # pattern of the self-test's other-key rule, so each fails if that pattern goes.
        names = ("trykey", "secondkey", "offerother", "attemptother", "acceptother")
        runs = [(["/bin/sh", SELFTEST], self.state(name, name)) for name in names]
        for name, (code, out, err) in zip(names, _relay_many(self.home, runs)):
            with self.subTest(scenario=name):
                self.assertEqual(code, 3, out + err)
                self.assertEqual(self.statuses(out), {item: "unclear" for item in ITEMS})
                self.assertIn("verdict: INCONCLUSIVE (0 of 9 refused", out)

    def test_a_match_block_that_changes_one_form_is_refused(self):
        # A Match block (sessiontype, command) applies to some forms only. Anywhere in ~/.ssh/config it can add a
        # key or a forward to that form; above the lab-suite block it can also set a single-value option first.
        # Each case changes one probe form only, so ssh lab-suite looks right; each refuses before any login.
        cases = [
            ("command", OTHER_KEY, "air_config_identityfile"),
            ("pty", OTHER_KEY, "air_config_identityfile"),
            ("local", OTHER_KEY, "air_config_identityfile"),
            ("stdio", OTHER_KEY, "air_config_identityfile"),
            ("remote", OTHER_KEY, "air_config_identityfile"),
            ("command", "remoteforward [127.0.0.1]:2222 [127.0.0.1]:22\n", "air_config_remoteforward"),
            ("pty", "dynamicforward 1080\n", "air_config_dynamicforward"),
            ("local", "localforward [127.0.0.1]:9999 [127.0.0.1]:22\n", "air_config_localforward"),
            ("local", "dynamicforward [127.0.0.1]:1080\n", "air_config_dynamicforward"),
            ("stdio", "clearallforwardings no\n", "air_config_localforward"),
            ("remote", "remoteforward [127.0.0.1]:2222 [127.0.0.1]:22\n", "air_config_remoteforward"),
            ("remote", "localforward [127.0.0.1]:9999 [127.0.0.1]:22\n", "air_config_localforward"),
            ("command", "hostname 192.168.50.89\n", "air_config_hostname"),
            ("local", "controlmaster auto\ncontrolpath /tmp/cm-%C\n", "air_config_controlmaster"),
            ("stdio", "identityagent /tmp/agent.sock\n", "air_config_identityagent"),
            ("remote", "proxycommand /usr/bin/nc %h %p\n", "air_config_proxy"),
        ]
        runs = [(["/bin/sh", SELFTEST], self.state("match%d" % i, "secure", blocks={form: block}))
                for i, (form, block, _code) in enumerate(cases)]
        # The control: a Match block that turns passwords on for probe 1's form changes nothing, because the
        # probe's own -o options win. The preflight passes and the lab refuses all nine.
        runs.append((["/bin/sh", SELFTEST], self.state("password", "secure", blocks={"command": PASSWORD_ON})))
        results = _relay_many(self.home, runs)
        for i, ((form, block, expected), (code, out, err)) in enumerate(zip(cases, results)):
            with self.subTest(form=form, block=block):
                self.assertEqual((code, _codes(err)), (2, [expected]), out + err)
                self.assertIn(FORMS[form], err)
                self.assertNotIn("probe 1", out)
                calls = _ssh_calls(os.path.join(self.home, "state-match%d" % i))
                self.assertEqual({kind for kind, _argv in calls}, {"G"}, "no login")
        code, out, err = results[-1]
        self.assertEqual(code, 0, out + err)
        self.assertTrue(out.endswith("verdict: PASS (9 of 9 refused)\n"), out)

    def test_preflight_refusals(self):
        other_key = SSH_G + OTHER_KEY
        # PATHs without ssh or without nc. /bin holds neither, so the real ones in /usr/bin are never reached.
        self.assertFalse([name for name in ("ssh", "nc") if os.path.exists(os.path.join("/bin", name))])
        only_nc = os.path.join(self.home, "only-nc")
        only_ssh = os.path.join(self.home, "only-ssh")
        _link_fake("nc", FAKE_NC, only_nc)
        _link_fake("ssh", FAKE_SSH, only_ssh)
        cases = [
            ("no ssh", dict(self.state("nossh", "secure"), PATH=only_nc + ":/bin"), "no_ssh"),
            ("no nc", dict(self.state("nonc", "secure"), PATH=only_ssh + ":/bin"), "no_nc"),
            ("ssh -G fails", self.state("unreadable", "secure", ssh_g=None), "air_config_unreadable"),
            ("wrong host", self.state("host", "secure", SSH_G.replace("192.168.50.88", "192.168.50.89")),
             "air_config_hostname"),
            ("another user", self.state("user", "secure", SSH_G.replace("User user", "User yu")), "air_config_user"),
            ("any address family", self.state("family", "secure", SSH_G.replace("addressfamily inet",
                                                                                "addressfamily any")),
             "air_config_addressfamily"),
            ("other identities allowed", self.state("only", "secure", SSH_G.replace("identitiesonly yes",
                                                                                    "identitiesonly no")),
             "air_config_identitiesonly"),
            ("forward failures ignored", self.state("eof", "secure", SSH_G.replace("exitonforwardfailure yes",
                                                                                   "exitonforwardfailure no")),
             "air_config_exitonforwardfailure"),
            ("new host keys accepted", self.state("hostkey", "secure", SSH_G.replace(
                "stricthostkeychecking true", "stricthostkeychecking accept-new")), "air_config_stricthostkeychecking"),
            ("a second key", self.state("keys", "secure", other_key), "air_config_identityfile"),
            ("keychain agent", self.state("agent", "secure", SSH_G.replace("addkeystoagent false",
                                                                          "addkeystoagent true")),
             "air_config_addkeystoagent"),
            ("no local forward", self.state("fwd", "secure", SSH_G.replace("localforward", "#")),
             "air_config_localforward"),
            # A later Host * block adds a forward to every form, the plain one included.
            ("a remote forward", self.state("rfwd", "secure",
                                            SSH_G + "remoteforward [127.0.0.1]:2222 [127.0.0.1]:22\n"),
             "air_config_remoteforward"),
            ("a dynamic forward", self.state("dfwd", "secure", SSH_G + "dynamicforward 1080\n"),
             "air_config_dynamicforward"),
            ("viewer port busy", self.state("busy", "secure", busy=True), "viewer_port_busy"),
            ("no temporary directory", dict(self.state("workdir", "secure"),
                                            TMPDIR=os.path.join(self.home, "no-such-dir")), "workdir"),
            # The Host block of the DESIGN text alone, below a Host * that shares connections and an agent.
            ("an inherited ControlMaster", self.state("shared", "secure", _strip_hardening(SSH_G) + SHARED),
             "air_config_controlmaster"),
            ("an inherited ControlPersist", self.state("persist", "secure", SSH_G.replace(
                "controlpersist no", "controlpersist yes")), "air_config_controlpersist"),
            ("an inherited ControlPath", self.state("cpath", "secure", SSH_G + "controlpath /tmp/cm-%C\n"),
             "air_config_controlpath"),
            ("an agent", self.state("agent2", "secure", SSH_G.replace("identityagent none",
                                                                      "identityagent SSH_AUTH_SOCK")),
             "air_config_identityagent"),
            ("a proxy command", self.state("proxy", "secure", SSH_G + "proxycommand /usr/bin/nc %h %p\n"),
             "air_config_proxy"),
            ("a jump host", self.state("jump", "secure", SSH_G + "proxyjump jump.example.invalid\n"),
             "air_config_proxy"),
            ("a local command", self.state("local", "secure", SSH_G.replace("permitlocalcommand no",
                                                                            "permitlocalcommand yes")),
             "air_config_permitlocalcommand"),
            # The block before the authentication lines: OpenSSH's defaults allow a password prompt.
            ("password fallback", self.state("pwauth", "secure", _strip_auth(SSH_G) + PASSWORD_DEFAULTS),
             "air_config_auth"),
            ("password allowed", self.state("pw", "secure", SSH_G.replace("passwordauthentication no",
                                                                          "passwordauthentication yes")),
             "air_config_auth"),
            ("keyboard-interactive allowed", self.state("kbd", "secure", SSH_G.replace(
                "kbdinteractiveauthentication no", "kbdinteractiveauthentication yes")), "air_config_auth"),
            ("other methods preferred", self.state("pref", "secure", SSH_G.replace(
                "preferredauthentications publickey", "preferredauthentications keyboard-interactive,publickey")),
             "air_config_auth"),
        ]
        runs = [(["/bin/sh", SELFTEST], env) for _label, env, _code in cases]
        runs.append((["/bin/sh", SELFTEST, "--force"], self.state("usage", "secure")))
        results = _relay_many(self.home, runs)
        for (label, _env, expected), (code, out, err) in zip(cases, results):
            with self.subTest(case=label):
                self.assertEqual((code, _codes(err)), (2, [expected]), out + err)
                self.assertNotIn("probe 1", out)
        self.assertEqual((results[-1][0], _codes(results[-1][2])), (2, ["usage"]))
        os.remove(os.path.join(self.home, ".ssh", "id_ed25519_lab_suite"))
        [(code, out, err)] = _relay_many(self.home, [(["/bin/sh", SELFTEST], self.state("nokey", "secure"))])
        self.assertEqual((code, _codes(err)), (2, ["key_missing"]))


if __name__ == "__main__":
    unittest.main()
