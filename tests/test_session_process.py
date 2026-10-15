"""Phase 0c end to end: ssh-session, open --print-url and the session lifetime against real engine-mode children
(DESIGN.md 8.6 items 1 and 2, 9.1, 9.2 item 1; I-16, I-19).

Every engine runs synthetic-only on an ephemeral 127.0.0.1 port under a temporary HOME (tests/test_http_support.py),
with tiny heartbeat, grace and maximum times passed to the in-process entry points (sshsession.main, server.run),
never real 10-minute waits. ssh-session children get a stdin pipe this test holds and write their stdout to a 0600
file in their temporary HOME (or to a pipe this test reads, for the failed-write case); the bootstrap codes they
print stay in those files and pipes and in this process's memory. Assertions compare redacted text (shape()), so
no failure message carries a code; client children never print a code or a token.

Nothing here runs /usr/bin/open: the open children replace server.system_opener with one that records a call and
exits, and run with --print-url or an injected opener. bin/suite ssh-session runs once, with SSH_CONNECTION set by
this test and the temporary HOME, on an ephemeral port; never against the real HOME.
"""

import json
import os
import re
import select
import signal
import subprocess
import time
import unittest

from betangel_suite import roots
from tests import LAUNCHER, PYTHON, ROOT, child_env, run_suite
from tests import test_http_support as support

URL_RE = re.compile(r"http://127\.0\.0\.1:([0-9]+)/#c=([A-Za-z0-9_-]{22})\n")
SSH = "192.0.2.10 50000 192.0.2.20 22"         # TEST-NET addresses: only the variable's presence matters
LAUNCH_PY = os.path.join(ROOT, "bin", "_launch.py")

# An ssh-session child: the engine here when none runs, else attached to the running one (sshsession.main).
SESSION = """
from betangel_suite.api import sshsession
from betangel_suite.api.lifetime import Lifetime
def main():
    return sshsession.main(cfg, port=0, heartbeat_s=0.3, poll_s=0.05,
                           lifetime=Lifetime(grace_s=%r, max_session_s=120, viewer_timeout_s=30))
"""

# A serve child with a short lifetime.
SERVE = """
from betangel_suite.api.lifetime import Lifetime
def main():
    return server.run(cfg, command="serve", port=0, poll_s=0.05,
                      lifetime=Lifetime(grace_s=%r, max_session_s=%r, viewer_timeout_s=30))
"""

# open through cli.main, as bin/suite runs it; /usr/bin/open is replaced by a recorder that exits.
OPEN_CLI = """
from betangel_suite import cli
def forbidden_opener(argv):
    fd = os.open(os.path.join(roots.state_dir(), "opener-called"), os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    raise SystemExit(9)
server.system_opener = forbidden_opener
def main():
    return cli.main(%r)
"""

# open through cli.main with /usr/bin/open replaced by a recorder that returns (each argv in its own 0600 file).
OPEN_CLI_RECORD = """
from betangel_suite import cli
calls = []
def recording_opener(argv):
    fd = os.open(os.path.join(roots.state_dir(), "opener-%%d" %% len(calls)), os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                 0o600)
    os.write(fd, json.dumps(argv).encode())
    os.close(fd)
    calls.append(argv)
server.system_opener = recording_opener
def main():
    return cli.main(%r)
"""

# An ssh-session child that imports first, says so (a ready file), and attaches only once the test's go file exists.
SESSION_ON_GO = """
import time
from betangel_suite.api import sshsession
from betangel_suite.api.lifetime import Lifetime
def main():
    from betangel_suite import engine, rx      # the slow imports, before the go
    home = os.environ["HOME"]
    os.close(os.open(os.path.join(roots.state_dir(), "%(name)s-ready"), os.O_WRONLY | os.O_CREAT, 0o600))
    deadline = time.monotonic() + 60
    while not os.path.lexists(os.path.join(home, "%(name)s-go")) and time.monotonic() < deadline:
        time.sleep(0.02)
    return sshsession.main(cfg, port=0, heartbeat_s=0.1, poll_s=0.05,
                           lifetime=Lifetime(grace_s=60, max_session_s=120, viewer_timeout_s=30))
"""

# open's attach with an injected opener that hands the URL over in a 0600 file, as a browser would get it. It starts
# (imports done) and waits for the test's go-open file, so the attach itself is prompt.
OPEN_ATTACH = """
import time
def opener(argv):
    fd = os.open(os.path.join(roots.state_dir(), "opened-url"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, argv[1].encode())
    os.close(fd)
def main():
    from betangel_suite import rx              # the slow imports, before the go
    go = os.path.join(os.environ["HOME"], "go-open")
    deadline = time.monotonic() + 60
    while not os.path.lexists(go) and time.monotonic() < deadline:
        time.sleep(0.02)
    return server.run(cfg, command="open", port=0, opener=opener)
"""


def shape(text):
    return re.sub(r"#c=[A-Za-z0-9_-]{22}", "#c=<code>", text)


def assert_code_lines(case, text, allowed):
    """I-16: an engine's stderr holds only its code-only request log lines (allowed), never a code or a token."""
    case.assertEqual(support.secret_shaped(text), [])
    case.assertLessEqual(set(text.splitlines()), allowed, shape(text)[-500:])


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, text.encode("ascii"))
    os.close(fd)


def wait_path(path, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not os.path.lexists(path):
        if time.monotonic() > deadline:
            raise AssertionError("not created: " + os.path.basename(path))
        time.sleep(0.02)


class PipeChild:
    """An engine-mode python child set up like support.run_child, with a stdin pipe this test holds, stdout to a
    0600 file in its HOME (or a pipe), stderr to a file. Always stopped in cleanup."""

    def __init__(self, case, home, body, *, name, stdout_pipe=False, argv=None, env=None):
        self.home = home
        self.out_path = os.path.join(home, name + ".out")
        self.err_path = os.path.join(home, name + ".err")
        argv = argv or [PYTHON, "-I", "-S", "-B", "-c", support.RUN_CHILD + body + support.RUN_TAIL]
        with open(self.out_path, "w") as out, open(self.err_path, "w") as err:
            os.chmod(self.out_path, 0o600)
            self.process = subprocess.Popen(argv, env=child_env(home) if env is None else env, cwd=home,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE if stdout_pipe else out,
                                            stderr=err)
        self._buffer = b""
        case.addCleanup(self.kill)

    def press_enter(self):
        self.process.stdin.write(b"\n")
        self.process.stdin.flush()

    def close_stdin(self):
        self.process.stdin.close()

    def stdout(self):
        return support.read_text(self.out_path)

    def stderr(self):
        return support.read_text(self.err_path)

    def urls(self):
        return URL_RE.findall(self.stdout())

    def wait_urls(self, count, timeout=30.0):
        """The first count (port, code) pairs of stdout, waiting for them."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.urls()
            if len(found) >= count:
                return found[:count]
            if self.process.poll() is not None:
                break
            time.sleep(0.02)
        raise AssertionError("no URL: exit=%r stderr=%r" % (self.process.poll(), shape(self.stderr())[-300:]))

    def read_line(self, timeout=30.0):
        """The next line of a stdout pipe (bytes decoded), waiting for it."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise AssertionError("no line from the child")
            part = os.read(self.process.stdout.fileno(), 4096)
            if not part:
                raise AssertionError("the child closed its stdout")
            self._buffer += part
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode("ascii") + "\n"

    def wait_exit(self, timeout=20.0):
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self):
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(10)


class AsyncClient:
    """A support.CLIENT script run in the background (the test steps in between through trigger files)."""

    def __init__(self, case, home, port, script, name="client"):
        code = ("PORT = %d\nSECURITY_EXPECTED = %r\n" % (port, support.SECURITY_HEADERS)) + support.CLIENT + script \
            + "\nprint(json.dumps(results))\n"
        self.out_path = os.path.join(home, name + ".out")
        with open(self.out_path, "w") as out:
            self.process = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-c", code], env=child_env(home), cwd=home,
                                            stdout=out, stderr=subprocess.STDOUT)
        case.addCleanup(lambda: self.process.poll() is None and self.process.kill())

    def result(self, case, timeout=60):
        case.assertEqual(self.process.wait(timeout), 0, shape(support.read_text(self.out_path))[-1500:])
        return json.loads(support.read_text(self.out_path).strip().splitlines()[-1])


class EngineHereTests(unittest.TestCase):
    """ssh-session with no engine running: the engine runs in its process (I-19 end to end)."""

    def test_url_enter_heartbeat_failed_write_and_takeover(self):
        home = support.short_home(self)
        first = PipeChild(self, home, SESSION % 1.5, name="ssh-first", stdout_pipe=True)
        line = first.read_line()
        match = URL_RE.fullmatch(line)
        self.assertIsNotNone(match, "the first line is the URL: " + shape(line))
        port = int(match.group(1))
        write_private(os.path.join(home, "code-1"), match.group(2))
        client = AsyncClient(self, home, port, r"""
import re
def wait_file(name, timeout=30):
    deadline = time.monotonic() + timeout
    while not os.path.lexists(os.path.join(HOME, name)):
        if time.monotonic() > deadline:
            raise SystemExit("no " + name)
        time.sleep(0.02)
    return open(os.path.join(HOME, name)).read()
token = bootstrap(wait_file("code-1"))
fd = os.open(os.path.join(HOME, "token-1"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, token.encode())
os.close(fd)
stream = Stream(token)
results["open"] = command(token, "open_market", {"seed": 7})[1]["ok"]
command(token, "set_speed", {"speed_x100": 1000})
results["play"] = command(token, "play")[1]
moving = stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
results["moving"] = moving["t"]
os.close(os.open(os.path.join(HOME, "moving"), os.O_WRONLY | os.O_CREAT, 0o600))
results["second_code"] = request("POST", "/api/v1/bootstrap", {"code": wait_file("code-2")})[0]
results["first_code_again"] = request("POST", "/api/v1/bootstrap", {"code": wait_file("code-1")})[0]
wait_file("closed")
closed = time.monotonic()
paused = stream.until(lambda item: item["t"] == "frame" and item["clock"]["paused"], timeout=10)
results["paused_after_s"] = time.monotonic() - closed
results["pause_reason"] = paused["clock"]["pause_reason"] if isinstance(paused, dict) else paused
os.close(os.open(os.path.join(HOME, "paused"), os.O_WRONLY | os.O_CREAT, 0o600))
# The stream stays open (somebody is watching, so no grace yet) until a new ssh-session takes over.
results["end"] = stream.until(lambda item: item["t"] == "end", timeout=30)
stream.close()
""")
        wait_path(os.path.join(home, "moving"))
        first.press_enter()                                    # a fresh code, e.g. after a page reload
        while True:
            line = first.read_line()
            if not line.startswith("heartbeat "):
                break
            self.assertRegex(line, r"\Aheartbeat 0:00:[0-9]{2}\n\Z")      # every 0.3 s here (15 s shipped)
        second = URL_RE.fullmatch(line)
        self.assertIsNotNone(second, "Enter prints a URL: " + shape(line))
        self.assertEqual(int(second.group(1)), port)
        self.assertTrue(second.group(2) != match.group(2), "Enter gives a fresh code")   # no code in a message
        write_private(os.path.join(home, "code-2"), second.group(2))
        self.assertRegex(first.read_line(), r"\Aheartbeat 0:00:[0-9]{2}\n\Z")
        first.process.stdout.close()                           # the SSH channel is gone: the next write fails
        write_private(os.path.join(home, "closed"), "")
        wait_path(os.path.join(home, "paused"))

        # A new ssh-session within the grace takes over: pause, the old token dies, a fresh code.
        attached = PipeChild(self, home, SESSION % 1.5, name="ssh-attached")
        (attached_port, _code), = attached.wait_urls(1)
        self.assertEqual(int(attached_port), port)
        results = client.result(self)
        self.assertEqual((results["open"], results["play"], results["moving"]), (True, {"ok": True}, "frame"))
        self.assertEqual((results["second_code"], results["first_code_again"]), (200, 401))
        self.assertEqual(results["pause_reason"], "not_watched")
        self.assertLess(results["paused_after_s"], 2.0)        # I-19: within 2 s
        self.assertEqual(results["end"]["reason"], "superseded")
        after = support.client(self, home, port, r"""
import re
old = open(os.path.join(HOME, "token-1")).read()
results["old_token"] = query(old)[0]
code = re.findall(r"#c=([A-Za-z0-9_-]{22})", open(os.path.join(HOME, "ssh-attached.out")).read())[0]
token = bootstrap(code)
results["controller"] = query(token)[1]["controller"]
""")
        self.assertEqual(after, {"old_token": 401, "controller": True})
        self.assertIsNone(first.process.poll(), "the engine keeps running")

        # stdin EOF on the attached viewer: it leaves at once, and the engine keeps the session for the grace (the
        # grace running out, abandoned, is SignalTests'). SIGTERM then stops the hosting process cleanly.
        attached.close_stdin()
        self.assertEqual(attached.wait_exit(10), 0, shape(attached.stderr()))
        self.assertIsNone(first.process.poll(), "the engine keeps the session")
        first.process.send_signal(signal.SIGTERM)
        self.assertEqual(first.wait_exit(20), 0, shape(first.stderr()))
        self.assertRegex(shape(attached.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%d/#c=<code>\n(heartbeat 0:00:[0-9]{2}\n)*\Z" % port)
        assert_code_lines(self, first.stderr(), {"http:401:bad_code", "http:401:unauthorized"})   # I-16
        self.assertEqual(attached.stderr(), "")
        self.assertFalse(os.path.lexists(support.control_path(home)))


class SignalTests(unittest.TestCase):
    """ssh-session's signals: SIGHUP to the process hosting the engine is the viewer leaving (server.py), not a stop;
    SIGTERM to an attached viewer is that viewer leaving (sshsession.py), and the engine runs on. With nobody
    watching, the grace then runs out and the hosting process says so on its stdout: abandoned (I-19)."""

    def test_sighup_keeps_the_hosted_session_and_sigterm_lets_an_attached_viewer_go(self):
        home = support.short_home(self)
        hosting = PipeChild(self, home, SESSION % 1.5, name="ssh-host")
        attached = PipeChild(self, home, SESSION_ON_GO % {"name": "attach"}, name="ssh-attach")
        (port, _code), = hosting.wait_urls(1)                  # its signal handlers are installed by now
        wait_path(os.path.join(roots.state_dir(home), "attach-ready"))
        hosting.process.send_signal(signal.SIGHUP)             # the viewer left: pause, keep the session
        write_private(os.path.join(home, "attach-go"), "")      # a takeover within the 1.5 s grace
        (attached_port, _code), = attached.wait_urls(1)
        self.assertEqual(int(attached_port), int(port), "the hosted engine was taken over, not replaced")
        deadline = time.monotonic() + 10
        while "heartbeat " not in attached.stdout() and time.monotonic() < deadline:
            time.sleep(0.02)                                    # its handlers are installed once it steps
        self.assertIsNone(hosting.process.poll(), "SIGHUP never stops the hosting process")
        attached.process.send_signal(signal.SIGTERM)
        self.assertEqual(attached.wait_exit(10), 0, shape(attached.stderr()))
        left = time.monotonic()
        self.assertIsNone(hosting.process.poll(), "the engine keeps the session for the grace")
        self.assertEqual(hosting.wait_exit(20), 0, shape(hosting.stderr()))
        self.assertTrue(1.0 <= time.monotonic() - left < 10.0, time.monotonic() - left)
        self.assertRegex(shape(attached.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%s/#c=<code>\n(heartbeat 0:00:[0-9]{2}\n)+\Z" % port)
        self.assertRegex(shape(hosting.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%s/#c=<code>\n(heartbeat 0:00:[0-9]{2}\n)*ended reason=abandoned\n\Z"
                         % port)
        self.assertEqual((hosting.stderr(), attached.stderr()), ("", ""))
        self.assertFalse(os.path.lexists(support.control_path(home)))


REFUSED = (2, "", "refused:synthetic_only\n")


def set_data_roots(home, value):
    path = roots.config_path(home)
    with open(path, "w") as handle:
        json.dump({"data_roots": value}, handle)
    os.chmod(path, 0o600)


def viewing_refusals(case, home, open_args):
    """(exit, stdout, stderr), redacted, of bin/suite ssh-session (in the fake SSH environment) and of open through
    cli.main with each of open_args, all started at once; with a data root configured each must be REFUSED."""
    children = [support.Child(case, home, ["/bin/sh", LAUNCHER, "ssh-session", "--port", "0"],
                              env=child_env(home, SSH_CONNECTION=SSH), name="ssh-refused")]
    children += [support.run_child(case, home, OPEN_CLI % (args,), name="open-refused-%d" % index)
                 for index, args in enumerate(open_args)]
    return [(child.wait_exit(60), shape(child.stdout()), shape(child.stderr())) for child in children]


class SyntheticOnlyTests(unittest.TestCase):
    """I-18 for the viewing commands of a working checkout: ssh-session, open and open --print-url refuse a
    configured data root (synthetic_only) before any lock, socket, takeover, URL or /usr/bin/open. Against a running
    engine (the attach path) they are refused the same way: AttachedTests, during its wait."""

    def test_ssh_session_and_open_refuse_a_data_root(self):
        home = support.short_home(self)
        set_data_roots(home, ["~/betangel-data/historic-pro"])
        results = viewing_refusals(self, home, (["open", "--port", "0", "--print-url"], ["open", "--port", "0"]))
        self.assertEqual(results, [REFUSED] * 3)
        self.assertFalse(os.path.lexists(os.path.join(roots.run_dir(home), "engine.lock")))
        self.assertFalse(os.path.lexists(support.control_path(home)))
        self.assertFalse(os.path.lexists(os.path.join(roots.state_dir(home), "opener-called")))
        self.assertFalse(os.path.lexists(roots.data_home(home)))


class AttachedTests(unittest.TestCase):
    """ssh-session attached to a running engine: supersession, open within the grace, and the maximum time."""

    def test_superseded_viewer_stdin_eof_and_open_within_the_grace(self):
        home = support.short_home(self)
        serving = support.run_child(self, home, SERVE % (1.5, 120))
        port = serving.wait_ready()
        old = PipeChild(self, home, SESSION % 1.5, name="ssh-old")
        old.wait_urls(1)
        new = PipeChild(self, home, SESSION % 1.5, name="ssh-new")
        new.wait_urls(1)
        self.assertEqual(old.wait_exit(10), 0, shape(old.stderr()))     # its next heartbeat says superseded
        self.assertTrue(shape(old.stdout()).endswith("ended reason=superseded\n"), shape(old.stdout()))
        self.assertEqual(len(old.urls()), 1)
        client = AsyncClient(self, home, port, r"""
import re
def wait_file(name, timeout=30):
    deadline = time.monotonic() + timeout
    while not os.path.lexists(os.path.join(HOME, name)):
        if time.monotonic() > deadline:
            raise SystemExit("no " + name)
        time.sleep(0.02)
token = bootstrap(re.findall(r"#c=([A-Za-z0-9_-]{22})", open(os.path.join(HOME, "ssh-new.out")).read())[0])
stream = Stream(token)
command(token, "open_market", {"seed": 9})
command(token, "set_speed", {"speed_x100": 1000})
results["play"] = command(token, "play")[1]
stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
os.close(os.open(os.path.join(HOME, "moving"), os.O_WRONLY | os.O_CREAT, 0o600))
wait_file("eof")
eof = time.monotonic()
paused = stream.until(lambda item: item["t"] == "frame" and item["clock"]["paused"], timeout=10)
results["paused_after_s"] = time.monotonic() - eof
results["pause_reason"] = paused["clock"]["pause_reason"] if isinstance(paused, dict) else paused
stream.close()                              # nobody watching from here: the grace runs
os.close(os.open(os.path.join(HOME, "paused"), os.O_WRONLY | os.O_CREAT, 0o600))
""")
        opener = support.run_child(self, home, OPEN_ATTACH, name="open")   # imports now, attaches on go-open
        wait_path(os.path.join(home, "moving"))
        new.close_stdin()                                       # away: pause, and keep the session
        write_private(os.path.join(home, "eof"), "")
        self.assertEqual(new.wait_exit(10), 0, shape(new.stderr()))
        results = client.result(self)
        self.assertEqual(results["play"], {"ok": True})
        self.assertEqual(results["pause_reason"], "not_watched")
        self.assertLess(results["paused_after_s"], 2.0)        # I-19: closing stdin pauses within 2 s
        write_private(os.path.join(home, "go-open"), "")       # open within the 1.5 s grace takes over
        self.assertEqual(opener.wait_exit(20), 0, opener.stderr())
        self.assertEqual(shape(opener.stdout()), "attached port=%d\n" % port)
        waited = time.monotonic()
        # I-18 against this running engine (its config was read at start): with a data root configured now,
        # ssh-session and open --print-url refuse before the attach, so open's code below stays live (no takeover).
        set_data_roots(home, ["~/betangel-data/historic-pro"])
        self.assertEqual(viewing_refusals(self, home, (["open", "--port", "0", "--print-url"],)), [REFUSED] * 2)
        time.sleep(max(0.0, 2.5 - (time.monotonic() - waited)))
        self.assertIsNone(serving.process.poll(), "open's takeover is watched on the lab: never abandoned")
        results = support.client(self, home, port, """
url = open(os.path.join(HOME, ".local/state/betangel-suite/opened-url")).read()
results["bootstrap"] = request("POST", "/api/v1/bootstrap", {"code": url.rsplit("=", 1)[1]})[0]
""")
        self.assertEqual(results, {"bootstrap": 200})
        self.assertEqual(serving.terminate(), 0)
        self.assertEqual(serving.stdout(), "serving port=%d\n" % port)
        self.assertEqual("".join(child.stderr() for child in (serving, old, new, opener)), "")
        self.assertFalse(os.path.lexists(os.path.join(roots.state_dir(home), "opener-called")))

    def test_the_maximum_session_time_ends_it_with_its_own_reason(self):
        home = support.short_home(self)
        serving = support.run_child(self, home, SERVE % (60.0, 2.0))
        port = serving.wait_ready()
        results = support.client(self, home, port, """
token = bootstrap()
stream = Stream(token)
results["end"] = stream.until(lambda item: item["t"] == "end", timeout=15)
""")
        self.assertEqual(results["end"], {"t": "end", "seq": 0, "reason": "max_session"})
        self.assertEqual(serving.wait_exit(10), 0, serving.stderr())
        self.assertEqual(serving.stdout(), "serving port=%d\nended reason=max_session\n" % port)
        self.assertEqual(serving.stderr(), "")


class PrintUrlTests(unittest.TestCase):
    """open --print-url (Yu only, never over SSH): the URL on stdout instead of /usr/bin/open (DESIGN.md 3.6, 8.6)."""

    def test_print_url_starts_or_attaches_and_never_runs_the_opener(self):
        home = support.short_home(self)
        first = support.run_child(self, home, OPEN_CLI % (["open", "--port", "0", "--print-url"],), name="open-1")
        port = first.wait_ready()
        self.assertRegex(shape(first.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%d/#c=<code>\nopened port=%d\n\Z" % (port, port))
        code = URL_RE.findall(first.stdout())[0][1]
        write_private(os.path.join(home, "code-1"), code)
        before = support.client(self, home, port, """
token = bootstrap(open(os.path.join(HOME, "code-1")).read())
results["controller"] = query(token)[1]["controller"]
results["reuse"] = request("POST", "/api/v1/bootstrap", {"code": open(os.path.join(HOME, "code-1")).read()})[0]
fd = os.open(os.path.join(HOME, "token-1"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, token.encode())
os.close(fd)
""")
        self.assertEqual(before, {"controller": True, "reuse": 401})
        second = support.run_child(self, home, OPEN_CLI % (["open", "--port", "0", "--print-url"],), name="open-2")
        self.assertEqual(second.wait_exit(20), 0, second.stderr())
        self.assertRegex(shape(second.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%d/#c=<code>\nattached port=%d\n\Z" % (port, port))
        write_private(os.path.join(home, "code-2"), URL_RE.findall(second.stdout())[0][1])
        after = support.client(self, home, port, """
results["old_token"] = query(open(os.path.join(HOME, "token-1")).read())[0]
results["new_code"] = request("POST", "/api/v1/bootstrap", {"code": open(os.path.join(HOME, "code-2")).read()})[0]
""")
        self.assertEqual(after, {"old_token": 401, "new_code": 200})
        # Plain open (no --print-url) through cli.main: the URL goes to the opener only, never to stdout (I-16).
        third = support.run_child(self, home, OPEN_CLI_RECORD % (["open", "--port", "0"],), name="open-3")
        self.assertEqual(third.wait_exit(20), 0, shape(third.stderr()))
        self.assertEqual(shape(third.stdout()), "attached port=%d\n" % port)
        self.assertEqual(support.secret_shaped(third.stdout() + third.stderr()), [])
        state = roots.state_dir(home)
        self.assertEqual(sorted(name for name in os.listdir(state) if name.startswith("opener")), ["opener-0"])
        with open(os.path.join(state, "opener-0")) as handle:
            argv = json.load(handle)
        self.assertTrue(len(argv) == 2 and argv[0] == "/usr/bin/open" and URL_RE.fullmatch(argv[1] + "\n")
                        and URL_RE.fullmatch(argv[1] + "\n").group(1) == str(port), "the opener got one live URL")
        reopened = support.client(self, home, port, """
url = json.load(open(os.path.join(HOME, ".local/state/betangel-suite/opener-0")))[1]
results["code"] = request("POST", "/api/v1/bootstrap", {"code": url.rsplit("=", 1)[1]})[0]
""")
        self.assertEqual(reopened, {"code": 200})
        self.assertEqual(first.terminate(), 0)
        self.assertFalse(os.path.lexists(os.path.join(roots.state_dir(home), "opener-called")))
        assert_code_lines(self, first.stderr(), {"http:401:bad_code", "http:401:unauthorized"})   # I-16
        self.assertEqual((second.stderr(), third.stderr()), ("", ""))

    def test_serve_never_takes_print_url(self):
        home = support.short_home(self, deps=False)
        for args in (["serve", "--print-url"], ["serve", "--port", "0", "--print-url"]):
            result = run_suite(args, home)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:bad_arguments\n"),
                             args)


class LauncherSessionTests(unittest.TestCase):
    """bin/suite ssh-session end to end in a temporary HOME, and the SSH flag it passes through env -i."""

    def test_bin_suite_ssh_session_prints_one_url_and_stops_cleanly(self):
        home = support.short_home(self)
        env = child_env(home, SSH_CONNECTION=SSH)
        session = PipeChild(self, home, "", name="ssh-launcher",
                            argv=["/bin/sh", LAUNCHER, "ssh-session", "--port", "0"], env=env)
        (port, code), = session.wait_urls(1)
        write_private(os.path.join(home, "code-1"), code)
        results = support.client(self, home, int(port), """
results["bootstrap"] = request("POST", "/api/v1/bootstrap", {"code": open(os.path.join(HOME, "code-1")).read()})[0]
""")
        self.assertEqual(results, {"bootstrap": 200})
        stop = run_suite(["stop"], home)
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "stopped\n", ""))
        self.assertEqual(session.wait_exit(20), 0, shape(session.stderr()))
        self.assertRegex(shape(session.stdout()),
                         r"\Ahttp://127\.0\.0\.1:%s/#c=<code>\n(heartbeat [0-9:]+\n)*ended reason=stopped\n\Z" % port)
        self.assertEqual(session.stderr(), "")
        self.assertFalse(os.path.lexists(support.control_path(home)))

    def test_the_ssh_flag_is_checked_again_after_env_i(self):
        # _launch.py run directly (no bin/suite, so no SUITE_VIA_SSH=1) refuses ssh-session; with the flag set,
        # serve is refused (open's refusal is checked in process: tests/test_session_lifetime.py, never by running
        # open). No deps clone in this HOME: a check that let them through would stop at deps_missing first.
        home = support.short_home(self, deps=False)
        for args, env, code in ((["ssh-session"], child_env(home), "ssh_session_outside_ssh"),
                                (["ssh-session"], child_env(home, SUITE_VIA_SSH="0"), "ssh_session_outside_ssh"),
                                (["serve"], child_env(home, SUITE_VIA_SSH="1"), "open_over_ssh")):
            result = subprocess.run([PYTHON, "-I", "-S", "-B", LAUNCH_PY, *args], env=env, cwd=home,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:%s\n" % code), args)
        # bin/suite itself: --print-url over SSH is refused before env -i; ssh-session needs SSH.
        for args, env, code in ((["selfcheck", "--print-url"], {"SSH_CONNECTION": SSH}, "print_url_over_ssh"),
                                (["ssh-session", "--port", "0"], {}, "ssh_session_outside_ssh")):
            result = run_suite(args, home, env=child_env(home, **env))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:%s\n" % code), args)


if __name__ == "__main__":
    unittest.main()
