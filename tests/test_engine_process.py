"""The engine process behind serve and open: I-4, I-5 (sealed after startup), I-16, I-17 mid-session, stop.

Every server here is a real engine-mode child on an ephemeral 127.0.0.1 port under a temporary HOME
(tests/test_http_support.py). /usr/bin/open is never started: the open path runs in a python child with an
injected opener, which checks the argv against the guard's own predicate and hands the URL to the test
client through a 0600 file, as a browser would receive it. I-5 is checked for serve, for open once its
opener has run, and for open's attach path once it returns: each probe tries harmless spawns only
(/usr/bin/true, a git rev-parse), never /usr/bin/open, so a broken seal could not open anything.
"""

import json
import os
import time
import unittest

from betangel_suite import pin, roots, runmarker
from betangel_suite.api import control
from tests import LAUNCHER, child_env, run_suite, tree_listing
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
        after = [entry for entry in tree_listing(home) if not entry[0].startswith(os.path.join(".local", "state",
                                                                                                "betangel-suite", "tmp"))]
        self.assertEqual(after, [entry for entry in before if not entry[0].startswith(os.path.join(
            ".local", "state", "betangel-suite", "tmp"))])
        self.assertFalse(os.path.lexists(os.path.join(home, "betangel-data")))

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


if __name__ == "__main__":
    unittest.main()
