"""The engine process behind serve and open: I-4, I-5 (sealed after startup), I-16, I-17 mid-session and the
realdata lock, startup refusals, stop.

Every server here is a real engine-mode child on an ephemeral 127.0.0.1 port under a temporary HOME
(tests/test_http_support.py). /usr/bin/open is never started: the open path runs in a python child with an
injected opener, which checks the argv against the guard's own predicate and hands the URL to the test
client through a 0600 file, as a browser would receive it; or, to go through cli.main as bin/suite open does
(OPEN_SAFE), with a recorder in place of server.system_opener and a second audit hook that refuses any start
of /usr/bin/open. I-5 is checked for serve, for open once its opener has run, and for open's attach path once
it returns: each probe tries harmless spawns only (/usr/bin/true, a git rev-parse), never /usr/bin/open, so a
broken seal could not open anything.
"""

import fcntl
import json
import os
import stat
import subprocess
import time
import unittest
from unittest import mock

from betangel_suite import pin, roots, runmarker
from betangel_suite.api import control
from betangel_suite.errors import SuiteError
from tests import LAUNCHER, PRELUDE, PYTHON, child_env, make_home, require_no_run_marker, run_suite, tree_listing
from tests import test_engine, test_runmarker
from tests import test_http_support as support

# sealed_probe(): what a sealed engine must refuse (I-5), tried in the child itself. Only harmless spawns.
SEALED_PROBE = """
import subprocess
def sealed_probe():
    from betangel_suite import guard as g
    results = {"sealed": g.is_sealed()}
    state = roots.state_dir()
    def attempt(name, fn):
        try:
            fn()
            results[name] = "ok"
        except errors.SuiteError as exc:
            results[name] = str(exc)
        except Exception as exc:
            results[name] = "other:" + type(exc).__name__
    attempt("git_probe", lambda: subprocess.run(["git", "-C", state, "rev-parse", "--is-inside-work-tree"],
                                                capture_output=True, timeout=10))
    attempt("true", lambda: subprocess.run(["/usr/bin/true"], timeout=10))
    attempt("os_system", lambda: os.system("true"))
    attempt("posix_spawn", lambda: os.posix_spawn("/usr/bin/true", ["/usr/bin/true"], dict(os.environ)))
    attempt("permit_port", lambda: g.permit_loopback_port(9))
    attempt("permit_socket", lambda: g.permit_unix_socket(os.path.join(roots.run_dir(), "x.sock")))
    attempt("permit_connect", lambda: g.permit_unix_connect(os.path.join(roots.run_dir(), "control.sock")))
    return results
"""
SEALED_EXPECTED = {"sealed": True, "git_probe": "subprocess_refused", "true": "subprocess_refused",
                   "os_system": "subprocess_refused", "posix_spawn": "subprocess_refused",
                   "permit_port": "guard_sealed", "permit_socket": "guard_sealed", "permit_connect": "guard_sealed"}

OPEN_CHILD = SEALED_PROBE + """
def record(name, value):                                         # 0600 files inside the child's write roots
    fd = os.open(os.path.join(roots.state_dir(), name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, json.dumps(value).encode())
    os.close(fd)
def opener(argv):
    from betangel_suite import guard as g
    ok = g.engine_argv_ok(argv, roots.write_roots(), {int(argv[1].split(":")[2].split("/")[0])})
    record("opened-url", {"argv": argv, "guard_ok": ok, "sealed": g.is_sealed()})
def on_ready(app):                        # the engine path, after the opener ran and the ready line went out
    record("sealed-on-ready", sealed_probe())
def main():
    status = server.run(cfg, command="open", port=0, opener=opener, on_ready=on_ready)
    record("sealed-after-run", sealed_probe())       # the attach path returns here at once
    return status
"""


# open as bin/_launch.py runs it: an engine-mode child that calls cli.main, so it takes run/realdata.lock and makes its
# TMPDIR as `bin/suite open` does. /usr/bin/open is never started: server.system_opener is replaced by a recorder, and
# a second audit hook (a hook can only add refusals) refuses any process start that names /usr/bin/open, should the
# replacement ever be missed. The child also records "connecting" when it connects to a Unix socket, and "requests",
# the control commands it sent. OPEN_SAFE is that set-up and run(argv); OPEN_CLI runs open with it.
OPEN_SAFE = PRELUDE + """
import json, os, sys
from betangel_suite import guard, errors
guard.arm("engine")
errors.install_excepthooks()
os.umask(0o077)
from betangel_suite import cli, roots
from betangel_suite.api import control, server
real_request, requests = control.request, []
def request(command, *args, **kwargs):
    requests.append(command)
    record("requests", requests)
    return real_request(command, *args, **kwargs)
control.request = request
def record(name, value):
    fd = os.open(os.path.join(roots.state_dir(), name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps(value).encode())
    os.close(fd)
def watch(event, args):
    if event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn", "os.system"):
        if "/usr/bin/open" in repr(args):
            raise RuntimeError("usr_bin_open_refused_by_test")
    elif event == "socket.connect" and isinstance(args[1], str):
        record("connecting", True)
sys.addaudithook(watch)
server.system_opener = lambda argv: record("opened-url", {"argv": argv})
def run(argv):
    try:
        return cli.main(argv)
    except errors.SuiteError as exc:
        sys.stderr.write(errors.describe(exc) + "\\n")
        return 2
"""
OPEN_CLI = OPEN_SAFE + 'sys.exit(run(["open", "--port", "0"]))\n'


def open_cli(case, home, name="open", code=OPEN_CLI):
    """code (OPEN_CLI) as a child of this HOME, with the TMPDIR bin/suite gives open; started after the real marker
    check."""
    require_no_run_marker()
    tmp = roots.tmp_dir("open", home)
    return support.Child(case, home, [PYTHON, "-I", "-S", "-B", "-c", code],
                         env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp), name=name)


def opened_path(home):
    return os.path.join(roots.state_dir(home), "opened-url")


def read_opened(home):
    with open(opened_path(home), encoding="utf-8") as handle:
        return json.load(handle)


def read_recorded(home, name, timeout=15.0):
    """A JSON file the open child records, waiting for it (on_ready runs just after the ready line)."""
    path = os.path.join(roots.state_dir(home), name)
    deadline = time.monotonic() + timeout
    while not os.path.lexists(path) and time.monotonic() < deadline:
        time.sleep(0.05)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class SealedEngineTests(unittest.TestCase):
    """I-5 end to end (deferred from Phase 0a): after startup, a real serve child refuses every subprocess."""

    def test_serve_child_is_sealed_after_startup(self):
        home = support.short_home(self)
        child = support.run_child(self, home, SEALED_PROBE + """
def on_ready(app):
    from betangel_suite import guard as g
    results = sealed_probe()
    def attempt(name, fn):
        try:
            fn()
            results[name] = "ok"
        except errors.SuiteError as exc:
            results[name] = str(exc)
        except Exception as exc:
            results[name] = "other:" + type(exc).__name__
    attempt("bind_other", lambda: __import__("socket").socket().bind(("127.0.0.1", 9)))
    from betangel_suite import rx
    def leaks(value):          # 9.2 item 1: codes and tokens go through upstream secret.register
        try:
            rx.secret.assert_clean(("x" + value + "x").encode(), where="test")
        except Exception as exc:
            return type(exc).__name__
        return "clean"
    code = app.auth.issue_code()
    token = app.auth.exchange(code)
    results["registered"] = [leaks(code), leaks(token), leaks("not-a-registered-value")]
    sys.stdout.write("results " + json.dumps(results) + "\\n")
    sys.stdout.flush()
    app.request_stop()
def main():
    return server.run(cfg, command="serve", port=0, on_ready=on_ready)
""")
        child.wait_ready()
        match = child.wait_line(r"results (\{.*\})\n")
        self.assertEqual(child.wait_exit(), 0, child.stderr())
        results = json.loads(match.group(1))
        self.assertEqual({name: results[name] for name in SEALED_EXPECTED}, SEALED_EXPECTED)
        self.assertEqual(results["bind_other"], "bind_refused")
        self.assertEqual(results["registered"], ["SecretLeak", "SecretLeak", "clean"])
        self.assertFalse(os.path.lexists(support.control_path(home)))


class OpenTests(unittest.TestCase):
    """open: the one /usr/bin/open argv at startup, never printed; attach takes over a running engine."""

    def test_open_starts_the_engine_and_hands_one_url_to_the_opener(self):
        home = support.short_home(self)
        child = support.run_child(self, home, OPEN_CHILD)
        port = child.wait_ready()
        opened = read_opened(home)
        argv = opened["argv"]
        self.assertEqual(argv[0], "/usr/bin/open")
        self.assertEqual(len(argv), 2)
        self.assertRegex(argv[1], r"\Ahttp://127\.0\.0\.1:%d/#c=[A-Za-z0-9_-]{22}\Z" % port)
        self.assertTrue(opened["guard_ok"])
        self.assertFalse(opened["sealed"])             # the opener runs in the startup phase
        # I-5 for open: once the opener has run, the engine is sealed like serve's.
        self.assertEqual(read_recorded(home, "sealed-on-ready"), SEALED_EXPECTED)
        code = argv[1].rsplit("=", 1)[1]
        results = support.client(self, home, port, """
code = open(%r).read()
code = json.loads(code)["argv"][1].rsplit("=", 1)[1]
status, _f, payload = request("POST", "/api/v1/bootstrap", {"code": code})
results["first"] = [status, sorted(jbody(payload))]
token = jbody(payload)["token"]
results["reuse"] = request("POST", "/api/v1/bootstrap", {"code": code})[0]
results["controller"] = query(token)[1]["controller"]
""" % opened_path(home))
        self.assertEqual(results, {"first": [200, ["ok", "token"]], "reuse": 401, "controller": True})
        self.assertEqual(child.terminate(), 0)
        self.assertEqual(read_recorded(home, "sealed-after-run"), SEALED_EXPECTED)
        output = child.stdout() + child.stderr()
        self.assertEqual(child.stdout(), "opened port=%d\n" % port)
        self.assertNotIn(code, output)
        self.assertEqual(support.secret_shaped(output), [])

    def test_open_attaches_to_a_running_engine_and_takes_over(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        before = support.client(self, home, port, """
token = bootstrap()
stream = Stream(token)
results["open"] = command(token, "open_market", {"seed": 5})
results["watch"] = stream.until(lambda item: item["t"] == "frame")["market"]["id"]
fd = os.open(os.path.join(HOME, "old-token"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, token.encode())
os.close(fd)
stream.close()
""")
        self.assertEqual(before["watch"], "1.999000005")
        attacher = support.run_child(self, home, OPEN_CHILD, name="attach")
        self.assertEqual(attacher.wait_exit(), 0, attacher.stderr())
        self.assertEqual(attacher.stdout(), "attached port=%d\n" % port)
        opened = read_opened(home)
        self.assertRegex(opened["argv"][1], r"\Ahttp://127\.0\.0\.1:%d/#c=[A-Za-z0-9_-]{22}\Z" % port)
        self.assertTrue(opened["guard_ok"])
        self.assertFalse(opened["sealed"])             # attach's opener also runs before the seal
        # I-5 for open's attach path: sealed once it returns, with the engine elsewhere.
        self.assertEqual(read_recorded(home, "sealed-after-run"), SEALED_EXPECTED)
        self.assertFalse(os.path.lexists(os.path.join(roots.state_dir(home), "sealed-on-ready")))
        after = support.client(self, home, port, """
old = open(os.path.join(HOME, "old-token")).read()
results["old_token"] = query(old)[0]
code = json.loads(open(%r).read())["argv"][1].rsplit("=", 1)[1]
token = bootstrap(code)
results["controller"] = query(token)[1]["controller"]
stream = Stream(token)
frame = stream.until(lambda item: item["t"] == "frame")
results["clock"] = [frame["clock"]["paused"], frame["clock"]["pause_reason"], frame["market"]["id"]]
stream.close()
""" % opened_path(home))
        self.assertEqual(after["old_token"], 401)
        self.assertTrue(after["controller"])
        self.assertEqual(after["clock"], [True, "takeover", "1.999000005"])
        self.assertEqual(serving.terminate(), 0)
        output = serving.stdout() + serving.stderr() + attacher.stdout() + attacher.stderr()
        self.assertEqual(support.secret_shaped(output), [])

    def test_takeover_ends_the_old_tabs_stream(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        results = support.client(self, home, port, """
token = bootstrap()
stream = Stream(token)
results["first"] = stream.next(5)
reply = control("attach")
results["attach"] = [reply["ok"], reply["port"] == PORT, len(reply["code"])]
results["end"] = stream.until(lambda item: item["t"] == "end", timeout=5)
results["after_end"] = stream.next(2)
results["old_token"] = query(token)[0]
results["new_code_works"] = bootstrap(reply["code"]) is not None
""")
        self.assertEqual(results["first"]["t"], "hb")
        self.assertEqual(results["attach"], [True, True, 22])
        self.assertEqual(results["end"], {"t": "end", "seq": 0, "reason": "superseded"})
        self.assertIsNone(results["after_end"])
        self.assertEqual(results["old_token"], 401)
        self.assertTrue(results["new_code_works"])


class LifecycleTests(unittest.TestCase):
    """serve's single instance lock, synthetic-only config, stop, SIGTERM and I-16 on the outputs."""

    def test_stop_ends_a_running_engine_and_removes_the_socket(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        socket_path = support.control_path(home)
        info = os.stat(socket_path)
        self.assertEqual(oct(info.st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(roots.run_dir(home)).st_mode & 0o777), "0o700")
        second = run_suite(["serve", "--port", "0"], home)
        self.assertEqual((second.returncode, second.stdout, second.stderr), (2, "", "refused:engine_running\n"))
        results = support.client(self, home, port, """
token = bootstrap()
results["open"] = command(token, "open_market", {"seed": 2})[0]
""")
        self.assertEqual(results["open"], 200)
        stop = run_suite(["stop"], home)
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "stopped\n", ""))
        self.assertEqual(serving.wait_exit(), 0, serving.stderr())
        self.assertFalse(os.path.lexists(socket_path))
        again = run_suite(["stop"], home)
        self.assertEqual((again.returncode, again.stdout, again.stderr), (0, "not_running\n", ""))
        self.assertEqual(serving.stdout(), "serving port=%d\n" % port)
        self.assertEqual(serving.stderr(), "")

    def test_stop_during_startup_stops_the_engine(self):
        # server.run holds engine.lock while it builds the engine, before it binds control.sock (Astra's review of
        # #4). A stop in that window must not print not_running and let the engine start: it asks again until the
        # socket answers, then waits for the lock to be free.
        home = support.short_home(self)
        gate = os.path.join(home, "gate")
        child = support.run_child(self, home, """
import time
from betangel_suite.api import static
real_load = static.load
def load(path):                             # engine.lock is held here, and control.sock is not bound yet
    sys.stdout.write("loading\\n")
    sys.stdout.flush()
    deadline = time.monotonic() + 20
    while not os.path.lexists(%r) and time.monotonic() < deadline:
        time.sleep(0.02)
    return real_load(path)
static.load = load
def main():
    return server.run(cfg, command="serve", port=0)
""" % gate)
        child.wait_line(r"loading\n")
        self.assertTrue(control.engine_running(home))
        self.assertFalse(os.path.lexists(support.control_path(home)))
        stopping = support.Child(self, home, ["/bin/sh", LAUNCHER, "stop"], name="stop")
        self.assertIsNone(stopping.wait_exit(2.0), stopping.stdout())       # still asking while the lock is held
        open(gate, "w").close()
        self.assertEqual(stopping.wait_exit(), 0, stopping.stderr())
        self.assertEqual((stopping.stdout(), stopping.stderr()), ("stopped\n", ""))
        self.assertEqual(child.wait_exit(), 0, child.stderr())
        self.assertEqual(child.stderr(), "")
        self.assertFalse(control.engine_running(home))
        self.assertFalse(os.path.lexists(support.control_path(home)))

    def test_serve_and_open_refuse_at_once_while_an_engine_starts(self):
        # DESIGN.md 8.6 item 1 (Astra's re-review of #4): with engine.lock held and no control.sock yet, serve refuses
        # with engine_running and open with control_unavailable. Neither waits for the engine to finish starting, and
        # neither asks again: both have refused while the engine below is still held at its gate.
        home = support.short_home(self)
        gate = os.path.join(home, "gate")
        child = support.run_child(self, home, """
import time
from betangel_suite.api import static
real_load = static.load
def load(path):                             # engine.lock is held here, and control.sock is not bound yet
    sys.stdout.write("loading\\n")
    sys.stdout.flush()
    deadline = time.monotonic() + 60
    while not os.path.lexists(%r) and time.monotonic() < deadline:
        time.sleep(0.02)
    return real_load(path)
static.load = load
def main():
    return server.run(cfg, command="serve", port=0)
""" % gate)
        child.wait_line(r"loading\n")
        serving = run_suite(["serve", "--port", "0"], home)
        self.assertEqual((serving.returncode, serving.stdout, serving.stderr), (2, "", "refused:engine_running\n"))
        opening = open_cli(self, home)
        self.assertEqual(opening.wait_exit(30), 2, opening.stderr())
        self.assertEqual((opening.stdout(), opening.stderr()), ("", "refused:control_unavailable\n"))
        self.assertEqual(read_recorded(home, "requests"), ["attach"])     # asked once
        self.assertFalse(os.path.lexists(opened_path(home)))
        self.assertIsNone(child.process.poll())                         # still starting: nobody waited for it
        self.assertEqual(child.stdout(), "loading\n")
        self.assertFalse(os.path.lexists(support.control_path(home)))
        open(gate, "w").close()
        child.wait_ready()
        self.assertEqual(child.terminate(), 0, child.stderr())

    def test_open_waits_only_for_the_reply_on_a_bound_control_socket(self):
        # The engine binds control.sock a moment before it answers on it. open's one attach request, connected in that
        # moment, waits for its reply up to control.CONNECTION_TIMEOUT_S, then refuses with control_unavailable; one
        # that is answered in time attaches (DESIGN.md 8.6 item 1). It never asks again.
        home = support.short_home(self)
        gate = os.path.join(home, "gate")
        child = support.run_child(self, home, """
import time
from betangel_suite.api import control
real_start = control.ControlServer.start
def start(self):                            # control.sock is bound and listening here, but nothing accepts yet
    sys.stdout.write("bound\\n")
    sys.stdout.flush()
    deadline = time.monotonic() + 60
    while not os.path.lexists(%r) and time.monotonic() < deadline:
        time.sleep(0.02)
    real_start(self)
control.ControlServer.start = start
def main():
    return server.run(cfg, command="serve", port=0)
""" % gate)
        child.wait_line(r"bound\n")
        self.assertTrue(os.path.lexists(support.control_path(home)))
        started = time.monotonic()
        late = open_cli(self, home, name="open-late")
        self.assertEqual(late.wait_exit(60), 2, late.stderr())
        self.assertGreaterEqual(time.monotonic() - started, control.CONNECTION_TIMEOUT_S)
        self.assertEqual((late.stdout(), late.stderr()), ("", "refused:control_unavailable\n"))
        self.assertEqual(read_recorded(home, "requests"), ["attach"])     # asked once
        for name in ("connecting", "requests"):
            os.remove(os.path.join(roots.state_dir(home), name))
        answered = open_cli(self, home, name="open-answered")
        connecting = os.path.join(roots.state_dir(home), "connecting")
        deadline = time.monotonic() + 30
        while not os.path.lexists(connecting) and answered.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(os.path.lexists(connecting), answered.stderr())
        time.sleep(0.5)
        self.assertIsNone(answered.process.poll())                      # waiting for its reply
        open(gate, "w").close()
        port = child.wait_ready()
        self.assertEqual(answered.wait_exit(30), 0, answered.stderr())
        self.assertEqual((answered.stdout(), answered.stderr()), ("attached port=%d\n" % port, ""))
        self.assertEqual(read_recorded(home, "requests"), ["attach"])
        self.assertRegex(read_opened(home)["argv"][1], r"\Ahttp://127\.0\.0\.1:%d/#c=[A-Za-z0-9_-]{22}\Z" % port)
        self.assertEqual(child.terminate(), 0, child.stderr())

    def test_stop_is_prompt_with_an_idle_keep_alive_connection_open(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        results = support.client(self, home, port, """
token = bootstrap()
conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
results["idle_request"] = command(token, "pause", conn=conn)[0]
socket_path = os.path.join(HOME, ".local/state/betangel-suite/run/control.sock")
started = time.monotonic()
results["stop"] = control("stop")
while os.path.lexists(socket_path) and time.monotonic() - started < 20:
    time.sleep(0.05)
results["shutdown_s"] = time.monotonic() - started
conn.close()
""")
        self.assertEqual(results["idle_request"], 200)
        self.assertEqual(results["stop"], {"ok": True})
        self.assertLess(results["shutdown_s"], 5.0)
        self.assertEqual(serving.wait_exit(), 0)

    def test_sigterm_sends_end_to_streams_and_exits_cleanly(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        trigger = os.path.join(home, "stream-open")
        script = """
token = bootstrap()
stream = Stream(token)
command(token, "open_market", {"seed": 4})
results["frame"] = stream.until(lambda item: item["t"] == "frame")["t"]
os.close(os.open(%r, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
results["end"] = stream.until(lambda item: item["t"] == "end", timeout=30)
results["eof"] = stream.next(5)
""" % trigger
        import subprocess
        code = ("PORT = %d\nSECURITY_EXPECTED = %r\n" % (port, support.SECURITY_HEADERS)) + support.CLIENT + script \
            + "\nprint(json.dumps(results))\n"
        from tests import PYTHON
        with open(os.path.join(home, "client.out"), "w") as out:
            client = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-c", code], env=child_env(home), cwd=home,
                                      stdout=out, stderr=subprocess.STDOUT)
        self.addCleanup(lambda: client.poll() is None and client.kill())
        deadline = time.monotonic() + 30
        while not os.path.lexists(trigger) and time.monotonic() < deadline and client.poll() is None:
            time.sleep(0.05)
        self.assertEqual(serving.terminate(), 0, serving.stderr())
        self.assertEqual(client.wait(30), 0)
        results = json.loads(support.read_text(os.path.join(home, "client.out")).strip().splitlines()[-1])
        self.assertEqual(results["frame"], "frame")
        self.assertEqual(results["end"]["reason"], "stopped")
        self.assertIsNone(results["eof"])
        self.assertFalse(os.path.lexists(support.control_path(home)))

    def test_a_taken_port_aborts_with_no_fallback_and_cleans_up(self):
        first_home, second_home = support.short_home(self), support.short_home(self)
        serving, port = support.serve(self, first_home)
        self.assertGreaterEqual(port, 1024)                 # macOS ephemeral ports are 49152-65535
        result = run_suite(["serve", "--port", str(port)], second_home)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:port_in_use\n"))
        self.assertFalse(os.path.lexists(support.control_path(second_home)))
        self.assertEqual(serving.terminate(), 0)

    def test_configured_data_roots_are_refused(self):
        home = support.short_home(self)
        config_path = roots.config_path(home)
        with open(config_path, "w") as handle:
            json.dump({"data_roots": ["~/betangel-data/historic-pro"]}, handle)
        before = tree_listing(home)
        result = run_suite(["serve", "--port", "0"], home)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:synthetic_only\n"))
        # serve took run/realdata.lock shared first (making run/ 0700 and the lock 0600; DESIGN.md 6.8), then made
        # only its TMPDIR, the suite root's tmp/ (0700, empty), before the engine refused the data root.
        tmp = os.path.relpath(roots.tmp_dir("serve", home), home)
        run, lock = os.path.relpath(roots.run_dir(home), home), os.path.relpath(runmarker.lock_path(home), home)
        self.assertEqual(tree_listing(home), sorted(before + [(run, 0o700), (lock, 0o600),
                                                              (os.path.dirname(tmp), 0o700), (tmp, 0o700)]))

    def test_bad_arguments(self):
        home = support.short_home(self, deps=False)
        # The parser is not open's only layer here: with no deps clone in this HOME, a parser that let
        # ["open", "--print"] through would stop at deps_missing before the engine or /usr/bin/open.
        self.assertFalse(os.path.lexists(pin.deps_dir(pin.load(), home)))
        for args in (["serve", "--port"], ["serve", "--port", "80"], ["serve", "--port", "-1"], ["serve", "8765"],
                     ["serve", "--port", "70000"], ["open", "--print"], ["stop", "now"], ["serve", "--port", "１"]):
            result = run_suite(args, home)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:bad_arguments\n"),
                             args)

    def test_outputs_hold_no_code_or_token(self):
        # I-16: whatever the API is asked, the server prints codes, counts and the port only.
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        support.client(self, home, port, """
seen = []
for _ in range(3):
    code = new_code()
    seen.append(code)
    token = bootstrap(code)
    seen.append(token)
    request("POST", "/api/v1/bootstrap", {"code": code})
    request("POST", "/api/v1/query", {"query": "session", "args": {}}, token=token + "x")
    request("GET", "/api/v1/stream?token=" + token, token=token)
    command(token, "open_market", {"seed": 9})
    command(token, "place", {"secret": token})
fd = os.open(os.path.join(HOME, "seen"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, json.dumps(seen).encode())
os.close(fd)
""")
        self.assertEqual(serving.terminate(), 0)
        with open(os.path.join(home, "seen"), encoding="utf-8") as handle:
            seen = json.load(handle)
        output = serving.stdout() + serving.stderr()
        self.assertEqual(support.secrets_in(output, seen), 0)
        self.assertEqual(support.secret_shaped(output), [])
        self.assertEqual(serving.stdout(), "serving port=%d\n" % port)
        for line in serving.stderr().splitlines():
            self.assertRegex(line, r"\Ahttp:[0-9]{3}:[a-z_]+\Z")


class RunMarkerTests(unittest.TestCase):
    """I-17 mid-session (DESIGN.md 6.8): the marker freezes the engine, which exits within the grace period
    without writing anything."""

    def test_marker_mid_session_freezes_then_exits_without_writes(self):
        home = support.short_home(self)
        marker = runmarker.marker_path(None, home)
        os.makedirs(os.path.dirname(marker), mode=0o700)
        child = support.run_child(self, home, """
def main():
    return server.run(cfg, command="serve", port=0, marker_grace_s=2)
""")
        port = child.wait_ready()
        results = support.client(self, home, port, """
token = bootstrap()
stream = Stream(token)
command(token, "open_market", {"seed": 8})
command(token, "set_speed", {"speed_x100": 1000})
results["play"] = command(token, "play")
moving = stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
results["moving"] = moving["clock"]["paused"]
listing = sorted(os.path.relpath(os.path.join(d, n), HOME) for d, ds, fs in os.walk(HOME) for n in ds + fs)
os.close(os.open(%r, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
marked = time.monotonic()
frozen = stream.until(lambda item: item["t"] == "frame" and item["clock"]["pause_reason"] == "run_marker", timeout=5)
results["frozen_after_s"] = time.monotonic() - marked
results["refused"] = [command(token, "play")[1], command(token, "open_market", {"seed": 1})[1]]
later = []
while True:
    item = stream.next(10)
    if item is None or item == "timeout" or item["t"] == "end":
        results["end"] = item
        break
    if item["t"] == "frame":
        later.append(item["clock"]["pt"])
results["exit_after_s"] = time.monotonic() - marked
results["pt_frozen"] = all(pt == frozen["clock"]["pt"] for pt in later)
results["listing_before"] = listing
""" % marker)
        status = child.wait_exit(20)
        after = sorted(os.path.relpath(os.path.join(d, n), home) for d, ds, fs in os.walk(home) for n in ds + fs)
        self.assertEqual(results["play"], [200, {"ok": True}])
        self.assertFalse(results["moving"])
        self.assertLess(results["frozen_after_s"], 1.0)
        self.assertEqual(results["refused"], [{"ok": False, "code": "run_marker_present"}] * 2)
        self.assertEqual(results["end"]["reason"], "run_marker")
        self.assertTrue(results["pt_frozen"])
        self.assertLess(results["exit_after_s"], 2 + 3)
        self.assertEqual(status, 2)
        self.assertEqual(child.stderr(), "refused:run_marker_present\n")
        # Nothing new anywhere but the marker itself; the engine only removed its control socket on exit.
        expected = (set(results["listing_before"]) | {os.path.relpath(marker, home)}) - {
            os.path.relpath(support.control_path(home), home)}
        self.assertEqual(set(after), expected)

    def test_marker_written_as_serve_takes_the_lock_refuses_the_start(self):
        # Nuance writes the marker, then waits for engine.lock to be free (6.8). A marker that appears after
        # serve's first check, just as serve takes the lock, must still refuse the start: serve checks again
        # once it holds the lock, starts nothing, and releases the lock.
        home = support.short_home(self)
        marker = runmarker.marker_path(None, home)
        os.makedirs(os.path.dirname(marker), mode=0o700)
        child = support.run_child(self, home, """
import time
from betangel_suite import engine
from betangel_suite.api import control
real_acquire_lock, real_start, started = control.acquire_lock, engine.Engine.start, []
def acquire_lock(home_dir=None):            # the test writes the marker now, then the real lock is taken
    sys.stdout.write("locking\\n")
    sys.stdout.flush()
    deadline = time.monotonic() + 10
    while not os.path.lexists(%r) and time.monotonic() < deadline:
        time.sleep(0.02)
    return real_acquire_lock(home_dir)
def start(self):
    started.append(True)
    real_start(self)
control.acquire_lock, engine.Engine.start = acquire_lock, start
def main():
    try:
        return server.run(cfg, command="serve", port=0, marker_grace_s=1)
    finally:
        sys.stdout.write("started=%%s lock_held=%%s\\n" %% (json.dumps(started), json.dumps(control.engine_running())))
        sys.stdout.flush()
""" % marker)
        child.wait_line(r"locking\n")
        open(marker, "w").close()
        self.assertEqual(child.wait_exit(20), 2)
        self.assertEqual(child.stderr(), "refused:run_marker_present\n")
        self.assertEqual(child.stdout(), "locking\nstarted=[] lock_held=false\n")
        self.assertFalse(os.path.lexists(support.control_path(home)))

    def test_marker_at_start_refuses_serve_and_open(self):
        home = support.short_home(self)
        marker = runmarker.marker_path(None, home)
        os.makedirs(os.path.dirname(marker), mode=0o700)
        open(marker, "w").close()
        before = tree_listing(home)
        # Only serve: open is never run through bin/suite here (it would reach /usr/bin/open if the check
        # failed); tests/test_runmarker.py covers open's start-time refusal in a HOME without the deps clone.
        result = run_suite(["serve", "--port", "0"], home)
        self.assertEqual((result.returncode, result.stderr), (2, "refused:run_marker_present\n"))
        self.assertEqual(tree_listing(home), before)


class RealDataLockTests(unittest.TestCase):
    """I-17 for serve and open (DESIGN.md 6.8, "Owed on phase0/http and phase0/viewing"): each takes run/realdata.lock
    shared in cli.main before its TMPDIR, checks the marker again under it, refuses with the existing codes, and
    holds it for the engine's life, letting it go within the grace period of the marker appearing. open's attach path
    holds it while it takes a running engine over, and hands on no URL once the marker appears. Everything runs
    under a temporary HOME: serve through bin/suite or cli.main, and open only through cli.main with OPEN_SAFE's
    recorder in place of /usr/bin/open."""

    def lock_free(self, home):
        """True when LOCK_EX on the temporary HOME's realdata lock is granted at once (and let go again)."""
        fd = os.open(runmarker.lock_path(home), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
        finally:
            os.close(fd)

    def hold_exclusive(self, home):
        """LOCK_EX on the realdata lock, as Nuance's wrapper would hold it, until the test ends."""
        os.makedirs(roots.run_dir(home), mode=0o700, exist_ok=True)
        fd = os.open(runmarker.lock_path(home), os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def start(self, home, code):
        require_no_run_marker()
        child = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-c", code], env=child_env(home), cwd=home,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and (child.kill(), child.communicate()))
        return child

    def test_serve_holds_the_lock_shared_for_the_engines_life(self):
        home = support.short_home(self)
        serving, _port = support.serve(self, home)          # bin/suite serve: _launch.py, then cli.main
        info = os.lstat(runmarker.lock_path(home))
        self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode)), (True, 0o600))
        self.assertFalse(self.lock_free(home))
        stop = run_suite(["stop"], home)
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "stopped\n", ""))
        self.assertEqual(serving.wait_exit(), 0, serving.stderr())
        self.assertTrue(self.lock_free(home))

    def test_open_holds_the_lock_shared_for_the_engine_it_starts(self):
        home = support.short_home(self)
        opening = open_cli(self, home)
        port = opening.wait_ready()
        self.assertEqual(opening.stdout(), "opened port=%d\n" % port)
        self.assertRegex(read_opened(home)["argv"][1], r"\Ahttp://127\.0\.0\.1:%d/#c=" % port)
        self.assertFalse(self.lock_free(home))
        stop = run_suite(["stop"], home)
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "stopped\n", ""))
        self.assertEqual(opening.wait_exit(), 0, opening.stderr())
        self.assertTrue(self.lock_free(home))

    def test_a_lock_the_wrapper_holds_refuses_serve_and_open_at_once(self):
        home = support.short_home(self)
        self.hold_exclusive(home)
        before = tree_listing(home)
        serving = run_suite(["serve", "--port", "0"], home, timeout=60)
        self.assertEqual((serving.returncode, serving.stdout, serving.stderr), (2, "", "refused:run_lock_busy\n"))
        opening = open_cli(self, home)
        self.assertEqual(opening.wait_exit(60), 2, opening.stderr())
        self.assertEqual((opening.stdout(), opening.stderr()), ("", "refused:run_lock_busy\n"))
        for name in ("open.out", "open.err"):                      # the open child's own output files
            os.remove(os.path.join(home, name))
        self.assertEqual(tree_listing(home), before)                # no TMPDIR, no engine.lock, no URL

    def test_serve_and_open_check_the_marker_again_under_the_lock(self):
        # The launcher's check passed, then the wrapper made the marker before the command took its lock: the command
        # refuses under the lock, before its TMPDIR or engine.lock, as runmarker.hold_shared does for every real-data
        # command (DESIGN.md 6.8). open runs with OPEN_SAFE, serve as the engine-mode HOLDER of test_runmarker.
        gate = """
def mark(name):
    open(os.path.join(roots.state_dir(), name), "w").close()
def wait_for(name):
    deadline = time.monotonic() + 60
    while not os.path.exists(os.path.join(roots.state_dir(), name)) and time.monotonic() < deadline:
        time.sleep(0.02)
import time
from betangel_suite import runmarker
runmarker.require_absent(runmarker.marker_path())      # bin/_launch.py's check, passed
mark("checked")
wait_for("go")
"""
        for command in ("serve", "open"):
            with self.subTest(command):
                home = support.short_home(self)
                if command == "serve":
                    require_no_run_marker()
                    child = support.Child(self, home, [PYTHON, "-I", "-S", "-B", "-c", test_runmarker.HOLDER
                                                       + "from betangel_suite import roots\n" + gate
                                                       + 'sys.exit(run(["serve", "--port", "0"]))\n'], name=command)
                else:
                    child = open_cli(self, home, code=OPEN_SAFE + gate + 'sys.exit(run(["open", "--port", "0"]))\n')
                state = roots.state_dir(home)
                deadline = time.monotonic() + 60
                while not os.path.exists(os.path.join(state, "checked")) and time.monotonic() < deadline:
                    time.sleep(0.02)
                marker = runmarker.marker_path(None, home)
                os.makedirs(os.path.dirname(marker), mode=0o700)
                open(marker, "w").close()
                open(os.path.join(state, "go"), "w").close()
                self.assertEqual(child.wait_exit(60), 2, child.stderr())
                self.assertEqual((child.stdout(), child.stderr()), ("", "refused:run_marker_present\n"))
                self.assertFalse(os.path.lexists(control.lock_path(home)))      # server.run never ran
                self.assertEqual(os.listdir(roots.data_home(home)), [])       # no suite root, no TMPDIR
                self.assertFalse(os.path.lexists(opened_path(home)))
                self.assertTrue(self.lock_free(home))

    def test_serve_lets_the_lock_go_within_the_grace_period_of_the_marker(self):
        # The engine may hold realdata.lock for about 35 s after the marker appears: its 30 s grace, then its shutdown
        # (DESIGN.md 6.8). Here the grace is 2 s, and a stand-in for Nuance's wrapper, which makes the marker and then
        # waits for LOCK_EX, gets the lock after the grace and within 5 s more.
        home = support.short_home(self)
        grace = 2
        tmp = roots.tmp_dir("serve", home)
        require_no_run_marker()
        serving = support.Child(self, home, [PYTHON, "-I", "-S", "-B", "-c", test_runmarker.HOLDER + r"""
from betangel_suite import engine
engine.MARKER_GRACE_S = %d
sys.exit(run(["serve", "--port", "0"]))
""" % grace], env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp))
        serving.wait_ready()
        self.assertFalse(self.lock_free(home))
        wrapper = self.start(home, test_runmarker.WRAPPER % (runmarker.marker_path(None, home),
                                                            runmarker.lock_path(home), 60.0))
        out, err = wrapper.communicate(timeout=120)
        self.assertEqual((wrapper.returncode, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["result"], "locked")
        self.assertGreaterEqual(result["waited_s"], grace - 0.1)       # held while the engine was frozen
        self.assertLess(result["waited_s"], grace + 5)
        self.assertEqual(serving.wait_exit(), 2)
        self.assertEqual(serving.stderr(), "refused:run_marker_present\n")
        self.assertFalse(control.engine_running(home))

    def test_open_attaching_holds_the_lock_and_hands_on_no_url_once_the_marker_appears(self):
        # open's attach path (an engine already running): cli.main took the lock, which open holds while it takes the
        # engine over and until it exits. A run announced during the takeover refuses before the hand-over
        # (server.attach checks the marker after the reply; round 4b): no URL goes to /usr/bin/open. The engine runs
        # server.run directly (support.run_child), so only open holds the lock; open's attach request waits after
        # its reply for the test's go file, while the test makes the marker.
        home = support.short_home(self)
        serving = support.run_child(self, home, "def main():\n    return server.run(cfg, command='serve', port=0)\n")
        serving.wait_ready()
        held = r"""
import time
inner_request = control.request
def request_then_wait(command, *args, **kwargs):
    reply = inner_request(command, *args, **kwargs)
    if command == "attach":
        open(os.path.join(roots.state_dir(), "attached"), "w").close()
        deadline = time.monotonic() + 60
        while not os.path.exists(os.path.join(roots.state_dir(), "go")) and time.monotonic() < deadline:
            time.sleep(0.02)
    return reply
control.request = request_then_wait
"""
        opening = open_cli(self, home, code=OPEN_SAFE + held + 'sys.exit(run(["open", "--port", "0"]))\n')
        state = roots.state_dir(home)
        deadline = time.monotonic() + 60
        while not os.path.exists(os.path.join(state, "attached")):
            if opening.process.poll() is not None or time.monotonic() > deadline:
                self.fail("no takeover: exit=%r stderr=%r" % (opening.process.poll(), opening.stderr()[-300:]))
            time.sleep(0.02)
        self.assertFalse(self.lock_free(home), "open holds the lock while it takes the engine over")
        marker = runmarker.marker_path(None, home)
        os.makedirs(os.path.dirname(marker), mode=0o700)
        open(marker, "w").close()
        open(os.path.join(state, "go"), "w").close()
        self.assertEqual(opening.wait_exit(60), 2, opening.stderr())
        self.assertEqual((opening.stdout(), opening.stderr()), ("", "refused:run_marker_present\n"))
        self.assertFalse(os.path.lexists(opened_path(home)), "no URL was handed on")
        self.assertEqual(read_recorded(home, "requests"), ["attach"])
        self.assertTrue(self.lock_free(home))


class RunnerMarkerTests(test_engine.EngineCase):
    """Nuance's PR #4 review, item 14: an engine a test starts runs under a temporary HOME, whose marker never
    exists, so the test helpers check the runner's own (real) marker before each launch. Here a stand-in in a
    temporary HOME takes the real marker's place (tests.RUN_MARKER, patched); the real one is never touched."""

    CHILD = "def main():\n    return server.run(cfg, command='serve', port=0)\n"

    def stand_in(self, present):
        place = make_home(self)
        path = os.path.join(place, ".local", "state", "lab-runs", "ACTIVE")
        os.makedirs(os.path.dirname(path), mode=0o700)
        if present:
            open(path, "w").close()
        else:
            os.chmod(os.path.dirname(path), 0)
            self.addCleanup(os.chmod, os.path.dirname(path), 0o700)
        patcher = mock.patch("tests.RUN_MARKER", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check_no_engine_starts(self, code):
        home = support.short_home(self)
        before = tree_listing(home)
        attempts = (
            ("bin/suite serve", lambda: support.serve(self, home)),
            ("python engine child", lambda: support.run_child(self, home, self.CHILD)),
            ("run_suite serve", lambda: run_suite(["serve", "--port", "80"], home)),   # bad port: it never binds
            ("in-process actor", lambda: self.make()),
        )
        for name, attempt in attempts:
            with self.subTest(name):
                with self.assertRaises(SuiteError) as caught:
                    attempt()
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(tree_listing(home), before)
        stop = run_suite(["stop"], home)              # stop stays exempt: it only reduces activity
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "not_running\n", ""))

    def test_no_engine_starts_while_the_real_marker_exists(self):
        self.stand_in(present=True)
        self.check_no_engine_starts("run_marker_present")

    def test_no_engine_starts_while_the_real_marker_is_unreadable(self):
        self.stand_in(present=False)
        self.check_no_engine_starts("run_marker_unreadable")


if __name__ == "__main__":
    unittest.main()
