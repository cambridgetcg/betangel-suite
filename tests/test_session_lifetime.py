"""Phase 0c in process: session lifetime, the ssh-session viewer, claim_control and the viewing commands' arguments
(DESIGN.md 8.6 items 1 and 2, 9.2 item 8, I-16, I-19).

Everything here runs in the test runner's own process with fake clocks, fake links, fake engines and in-memory
stdin and stdout (or a local pipe, filled up): no socket, no subprocess, no wait longer than a fraction of a
second. The real wiring (engine-mode children, the control socket, bin/suite) is in tests/test_session_process.py.

Bootstrap codes printed by the viewer stay in the in-memory stdout of each test; assertions compare redacted
text (shape()) or regex matches, so a failure message never carries a code.
"""

import io
import os
import re
import threading
import time
import unittest
from unittest import mock

from betangel_suite import cli
from betangel_suite.api import auth, lifetime, routes, server, sshsession
from betangel_suite.errors import SuiteError

URL_RE = re.compile(r"http://127\.0\.0\.1:([0-9]+)/#c=([A-Za-z0-9_-]{22})\n")
CODE = "C" * 22


def shape(text):
    """text with every bootstrap code replaced, safe to compare (and to show in a failure)."""
    return re.sub(r"#c=[A-Za-z0-9_-]{22}", "#c=<code>", text)


class Clock:

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# --- api/lifetime.py --------------------------------------------------------------------------------------------

class LifetimeTests(unittest.TestCase):

    def make(self, grace_s=600, max_session_s=14400, viewer_timeout_s=60):
        self.clock = Clock()
        return lifetime.Lifetime(grace_s=grace_s, max_session_s=max_session_s, clock=self.clock,
                                 viewer_timeout_s=viewer_timeout_s)

    def test_limits_must_be_positive_numbers(self):
        for bad in (0, -1, True, "600", None):
            with self.assertRaises(ValueError):
                lifetime.Lifetime(grace_s=bad, max_session_s=10)
            with self.assertRaises(ValueError):
                lifetime.Lifetime(grace_s=10, max_session_s=bad)
        self.assertEqual(lifetime.VIEWER_TIMEOUT_S, 60.0)
        self.assertEqual(sshsession.HEARTBEAT_S, 15.0)

    def test_without_a_terminal_only_the_maximum_time_ends_a_session(self):
        life = self.make()
        self.assertEqual(life.check(False), (None, False))           # serve: nobody, ever, is fine
        self.assertEqual(life.takeover(terminal=False), 1)            # open's takeover
        self.clock.advance(14399)
        self.assertEqual(life.check(False), (None, False))
        self.clock.advance(1)
        self.assertEqual(life.check(True), ("max_session", False))   # watched or not
        self.assertEqual(life.check(True), ("max_session", False))   # and it stays ended
        self.assertFalse(life.heartbeat(1))

    def test_stdin_eof_keeps_the_session_for_the_grace_then_abandons_it(self):
        life = self.make()
        viewer = life.takeover(terminal=True)
        self.clock.advance(5)
        self.assertTrue(life.away(viewer))
        self.assertEqual(life.check(False), (None, False))           # the grace starts now
        self.clock.advance(599)
        self.assertEqual(life.check(False), (None, False))
        self.clock.advance(1)
        self.assertEqual(life.check(False), ("abandoned", False))
        self.assertEqual(life.counts()["ended"], "abandoned")
        self.assertFalse(life.current(viewer))                        # an ended session issues no more codes

    def test_an_open_tab_means_somebody_is_watching(self):
        life = self.make(grace_s=10)
        viewer = life.takeover(terminal=True)
        life.away(viewer)
        self.assertEqual(life.check(True), (None, False))
        self.clock.advance(100)
        self.assertEqual(life.check(True), (None, False))            # the tab kept it
        self.assertEqual(life.check(False), (None, False))           # the tab went: the grace starts now
        self.clock.advance(9)
        self.assertEqual(life.check(False), (None, False))
        self.clock.advance(1)
        self.assertEqual(life.check(False), ("abandoned", False))

    def test_a_takeover_within_the_grace_keeps_the_session(self):
        life = self.make(grace_s=10)
        first = life.takeover(terminal=True)
        life.away(first)
        life.check(False)
        self.clock.advance(9)
        second = life.takeover(terminal=True)                         # a new ssh-session
        self.assertEqual(second, first + 1)
        self.clock.advance(5)
        self.assertEqual(life.check(False), (None, False))
        self.assertFalse(life.heartbeat(first))                       # the old viewer is superseded
        self.assertFalse(life.away(first))
        self.assertFalse(life.current(first))
        self.assertTrue(life.current(second))
        life.away(second)
        life.check(False)
        self.clock.advance(9)
        third = life.takeover(terminal=False)                         # open within the grace
        self.clock.advance(1000)
        self.assertEqual(life.check(False), (None, False))
        self.assertFalse(life.current(third))                         # open's takeover has no terminal to code

    def test_a_silent_viewer_counts_as_gone_and_pauses_once(self):
        life = self.make(grace_s=30, viewer_timeout_s=60)
        viewer = life.takeover(terminal=True)
        self.clock.advance(45)
        self.assertTrue(life.heartbeat(viewer))
        self.clock.advance(59)
        self.assertEqual(life.check(False), (None, False))
        self.clock.advance(1)
        self.assertEqual(life.check(False), (None, True))            # pause once
        self.assertEqual(life.check(False), (None, False))
        self.clock.advance(20)
        self.assertTrue(life.heartbeat(viewer))                       # a late heartbeat: it is there after all
        self.clock.advance(20)
        self.assertEqual(life.check(False), (None, False))
        self.assertFalse(life.counts()["away"])

    def test_bad_generations_are_never_current(self):
        life = self.make()
        viewer = life.takeover(terminal=True)
        for bad in (0, -1, True, 1.0, "1", None, viewer + 1):
            self.assertFalse(life.current(bad), bad)
            self.assertFalse(life.heartbeat(bad), bad)
            self.assertFalse(life.away(bad), bad)
        self.assertTrue(life.current(viewer))


# --- api/sshsession.py: Terminal and Viewer -----------------------------------------------------------------

class Stdin:
    """readline(limit) from lines a test feeds; b"" (EOF) after close()."""

    def __init__(self):
        self._lines = []
        self._cond = threading.Condition()
        self._closed = False
        self.limits = []

    def feed(self, data):
        with self._cond:
            self._lines.append(data)
            self._cond.notify_all()

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def readline(self, limit=-1):
        self.limits.append(limit)
        with self._cond:
            while not self._lines and not self._closed:
                self._cond.wait()
            return self._lines.pop(0) if self._lines else b""


class Stdout(io.StringIO):
    """A text stdout that can be made to fail (a closed SSH channel)."""

    broken = False

    def write(self, text):
        if self.broken:
            raise BrokenPipeError(32, "broken pipe")
        return super().write(text)


class Link:
    """A fake engine side for Viewer: records calls; answers can be set per call kind."""

    def __init__(self):
        self.calls = []
        self.answers = {}
        self.codes = 0

    def attach(self):
        self.calls.append("attach")
        return 8765, CODE, 3

    def code(self, generation):
        self.calls.append(("code", generation))
        self.codes += 1
        return self.answers.get("code", (8765, "D" * 21 + str(self.codes % 10)))

    def heartbeat(self, generation):
        self.calls.append(("heartbeat", generation))
        return self.answers.get("heartbeat", True)

    def away(self, generation):
        self.calls.append(("away", generation))
        return True


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met")
        time.sleep(0.005)


class ViewerTests(unittest.TestCase):

    def make(self, heartbeat_s=15.0):
        self.clock, self.stdin, self.stdout, self.link = Clock(), Stdin(), Stdout(), Link()
        self.terminal = sshsession.Terminal(self.stdin, self.stdout)
        viewer = sshsession.Viewer(self.link, self.terminal, clock=self.clock, heartbeat_s=heartbeat_s)
        self.assertEqual(viewer.attach(), sshsession.ACTIVE)
        self.terminal.start()
        self.addCleanup(self.stdin.close)
        return viewer

    def test_the_first_line_is_the_url_and_nothing_else(self):
        self.make()
        self.assertEqual(self.link.calls, ["attach"])
        match = URL_RE.fullmatch(self.stdout.getvalue())
        self.assertIsNotNone(match, "one URL line")
        self.assertEqual(match.groups(), ("8765", CODE))

    def test_each_enter_prints_a_fresh_code_and_presses_coalesce(self):
        viewer = self.make()
        self.stdin.feed(b"\n")
        wait_for(lambda: self.terminal._presses == 1)
        self.assertEqual(viewer.step(), sshsession.ACTIVE)
        self.stdin.feed(b"anything typed\n")
        self.stdin.feed(b"\n")
        self.stdin.feed(b"no newline yet")                       # a piece without a newline is not a press
        wait_for(lambda: self.terminal._presses == 2)
        time.sleep(0.02)
        self.assertEqual(viewer.step(), sshsession.ACTIVE)
        self.assertEqual(self.link.calls, ["attach", ("code", 3), ("code", 3)])     # two presses, one code
        self.assertEqual(shape(self.stdout.getvalue()), "http://127.0.0.1:8765/#c=<code>\n" * 3)
        self.assertNotIn("anything typed", self.stdout.getvalue())                 # input is never echoed
        self.assertEqual(set(self.stdin.limits), {sshsession.MAX_INPUT_BYTES})

    def test_heartbeats_every_period_and_stdin_eof_goes_away_once(self):
        viewer = self.make(heartbeat_s=15.0)
        viewer.step()
        self.clock.advance(14)
        viewer.step()
        self.clock.advance(1)
        viewer.step()
        self.clock.advance(3600 - 15)                             # 1 h on: the elapsed time is printed
        viewer.step()
        self.assertEqual(shape(self.stdout.getvalue()).splitlines()[1:], ["heartbeat 0:00:15", "heartbeat 1:00:00"])
        self.assertEqual(self.link.calls[1:], [("heartbeat", 3), ("heartbeat", 3)])
        self.stdin.close()
        wait_for(lambda: self.terminal.take()[1])
        self.assertEqual(viewer.step(), sshsession.AWAY)
        self.assertEqual(viewer.step(), sshsession.AWAY)
        self.clock.advance(60)
        viewer.step()
        self.assertEqual(self.link.calls[3:], [("away", 3)])
        self.assertEqual(len(self.stdout.getvalue().splitlines()), 3)   # nothing more after going away

    def test_a_failed_write_goes_away(self):
        viewer = self.make(heartbeat_s=1.0)
        self.stdout.broken = True
        self.clock.advance(1)
        self.assertEqual(viewer.step(), sshsession.AWAY)
        self.assertTrue(self.terminal.failed)
        self.assertEqual(self.link.calls, ["attach", ("away", 3)])

    @staticmethod
    def fill(fd):
        """Write to fd until a write would block: an SSH channel that nobody reads any more."""
        os.set_blocking(fd, False)
        for size in (4096, 1):
            try:
                while True:
                    os.write(fd, b"x" * size)
            except BlockingIOError:
                pass
        os.set_blocking(fd, True)

    def pipe(self):
        """(the read end, non-blocking; a text stdout on the write end)."""
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        self.addCleanup(os.close, write_end)
        os.set_blocking(read_end, False)
        return read_end, os.fdopen(write_end, "w", closefd=False)

    def in_thread(self, read_end, call):
        """call() on a thread, given 3 s; then the pipe is drained, so that a write still blocked there finishes."""
        results = []
        thread = threading.Thread(target=lambda: results.append(call()), daemon=True)
        thread.start()
        thread.join(3.0)
        blocked = thread.is_alive()
        try:
            while os.read(read_end, 65536):
                pass
        except BlockingIOError:
            pass
        thread.join(3.0)
        self.assertFalse(blocked, "the write waited for a reader that never came")
        return results[0]

    def test_a_stdout_that_stops_draining_counts_as_a_failed_write(self):
        # A blocking write would hold server.run's loop: no lifetime check, stop or lock release (DESIGN.md 6.8).
        read_end, out = self.pipe()
        self.fill(out.fileno())
        terminal = sshsession.Terminal(None, out)
        terminal.write_timeout_s = 0.2
        self.assertIs(self.in_thread(read_end, lambda: terminal.write(sshsession.heartbeat_line(15))), False)
        self.assertTrue(terminal.failed)
        read_end, out = self.pipe()                              # a viewer whose heartbeat stalls goes away
        clock, link = Clock(), Link()
        terminal = sshsession.Terminal(Stdin(), out)
        terminal.write_timeout_s = 0.2
        viewer = sshsession.Viewer(link, terminal, clock=clock, heartbeat_s=1.0)
        self.assertEqual(viewer.attach(), sshsession.ACTIVE)
        self.fill(out.fileno())
        clock.advance(1)
        self.assertEqual(self.in_thread(read_end, viewer.step), sshsession.AWAY)
        self.assertEqual(link.calls, ["attach", ("away", 3)])

    def test_a_hangup_goes_away(self):
        viewer = self.make()
        self.terminal.hangup = True
        self.assertEqual(viewer.step(), sshsession.AWAY)
        self.assertEqual(self.link.calls, ["attach", ("away", 3)])

    def test_superseded_and_engine_gone_end_the_viewer_with_a_line(self):
        for answer, state in ((sshsession.SUPERSEDED, "superseded"), (None, "engine_gone")):
            with self.subTest(state=state):
                viewer = self.make(heartbeat_s=1.0)
                self.link.answers["heartbeat"] = answer
                self.clock.advance(1)
                self.assertEqual(viewer.step(), state)
                self.assertEqual(shape(self.stdout.getvalue()).splitlines()[1:],
                                 ["heartbeat 0:00:01", "ended reason=" + state])
                self.assertEqual(viewer.step(), state)
                self.assertNotIn(("away", 3), self.link.calls)
        viewer = self.make()
        self.link.answers["code"] = sshsession.SUPERSEDED
        self.stdin.feed(b"\n")
        wait_for(lambda: self.terminal._presses == 1)
        self.assertEqual(viewer.step(), sshsession.SUPERSEDED)
        self.assertEqual(shape(self.stdout.getvalue()), "http://127.0.0.1:8765/#c=<code>\nended reason=superseded\n")

    def test_the_real_stdin_is_read_by_fd_in_bounded_lines(self):
        import os
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        reader = sshsession.FdReader(read_end)
        os.write(write_end, b"one\ntwo\n" + b"x" * 10 + b"\nlast")
        os.close(write_end)
        lines = [reader.readline(8) for _ in range(6)]
        self.assertEqual(lines, [b"one\n", b"two\n", b"xxxxxxxx", b"xx\n", b"last", b""])

    def test_no_stdin_is_eof_at_once(self):
        terminal = sshsession.Terminal(None, Stdout())
        terminal.start()
        self.assertEqual(terminal.take(), (0, True))

    def test_line_shapes(self):
        self.assertEqual(sshsession.url_line(8765, CODE), "http://127.0.0.1:8765/#c=" + CODE + "\n")
        self.assertEqual(sshsession.heartbeat_line(3725.9), "heartbeat 1:02:05\n")
        self.assertEqual(sshsession.end_line("max_session"), "ended reason=max_session\n")
        self.assertEqual(sshsession.end_line("made up"), "ended reason=unlisted_code\n")


# --- routes.App: takeovers, the viewer commands, the lifetime check, claim_control -----------------------------

class FakeEngine:

    frame_hz = 10

    def __init__(self):
        self.pauses, self.watched, self.stops, self.commands = [], [], [], []

    def pause_external(self, reason, timeout=5.0):
        self.pauses.append(reason)
        return {"ok": True}

    def set_watched(self, watched):
        self.watched.append(watched)

    def stop(self, reason="stopped"):
        self.stops.append(reason)

    def command(self, name, args):
        self.commands.append(name)
        return {"ok": True}

    def latest(self):
        return None


class AppTests(unittest.TestCase):

    def make(self, grace_s=10, max_session_s=100):
        self.clock = Clock()
        self.engine = FakeEngine()
        life = lifetime.Lifetime(grace_s=grace_s, max_session_s=max_session_s, clock=self.clock)
        app = routes.App(self.engine, auth.Auth(register=lambda value: None), {}, port=8765, lifetime=life)
        return app

    def command(self, app, token, name, nonce, args=None):
        return app.command(token, {"nonce": nonce, "command": name, "args": {} if args is None else args})

    def test_attach_viewer_takes_over_and_viewer_commands_name_their_generation(self):
        app = self.make()
        old = app.auth.exchange(app.auth.issue_code())
        reply = app.control("attach_viewer", {"port": 8765})
        self.assertEqual(sorted(reply), ["code", "ok", "port", "viewer"])
        self.assertEqual((reply["ok"], reply["port"], reply["viewer"]), (True, 8765, 1))
        self.assertFalse(app.auth.valid(old))                          # the old token is dead
        self.assertEqual(self.engine.pauses, ["takeover"])
        fresh = app.control("viewer_code", {"viewer": 1})
        self.assertTrue(fresh["ok"] and fresh["code"] != reply["code"])
        self.assertIsNotNone(app.auth.exchange(fresh["code"]))
        self.assertEqual(app.control("viewer_heartbeat", {"viewer": 1}), {"ok": True})
        second = app.control("attach_viewer", {"port": 0})               # 0: any port (ssh-session --port 0)
        self.assertEqual(second["viewer"], 2)
        for command in ("viewer_code", "viewer_heartbeat", "viewer_away"):
            self.assertEqual(app.control(command, {"viewer": 1}), {"ok": False, "code": "superseded"}, command)
        self.assertEqual(app.control("viewer_away", {"viewer": 2}), {"ok": True})
        self.assertEqual(self.engine.pauses, ["takeover", "takeover", "not_watched"])
        for command, args in (("viewer_code", {}), ("viewer_away", {"viewer": True}), ("stop", {"viewer": 2}),
                              ("attach", {"x": 1}), ("kill", {}), ("attach_viewer", {}), ("attach", {"port": 8765}),
                              ("attach_viewer", {"port": True}), ("attach_viewer", {"port": 65536}),
                              ("attach_viewer", {"viewer": 1})):
            self.assertEqual(app.control(command, args), {"ok": False, "code": "control_bad_request"}, command)
        attach = app.control("attach")
        self.assertEqual(sorted(attach), ["code", "ok", "port"])        # open's takeover: no viewer
        self.assertEqual(app.control("viewer_heartbeat", {"viewer": 2}), {"ok": False, "code": "superseded"})

    def test_attach_viewer_on_another_port_is_refused_before_the_takeover(self):
        # The forced command expects 8765 (DESIGN.md 8.6 item 2); an engine started with --port N is not taken over.
        app = self.make()
        app.port = 8766
        old = app.auth.exchange(app.auth.issue_code())
        self.assertEqual(app.control("attach_viewer", {"port": 8765}), {"ok": False, "code": "viewer_port_mismatch"})
        self.assertTrue(app.auth.valid(old))                           # nothing was invalidated ...
        self.assertEqual(self.engine.pauses, [])                       # ... or paused
        self.assertEqual(app.control("viewer_heartbeat", {"viewer": 1}), {"ok": False, "code": "superseded"})
        self.assertEqual(app.control("attach_viewer", {"port": 8766})["viewer"], 1)     # no takeover was counted
        self.assertEqual(self.engine.pauses, ["takeover"])

    def test_control_link_refuses_another_port_and_prints_no_url(self):
        app = self.make()
        app.port = 8766
        old = app.auth.exchange(app.auth.issue_code())

        def request(command, home_dir=None, *, timeout=None, args=None):
            return app.control(command, args)

        stdout = Stdout()
        viewer = sshsession.Viewer(sshsession.ControlLink(None, sshsession.VIEWER_PORT),
                                   sshsession.Terminal(None, stdout), clock=Clock())
        with mock.patch.object(sshsession.control, "request", request):
            with self.assertRaises(SuiteError) as caught:
                viewer.attach()
            self.assertEqual(caught.exception.code, "viewer_port_mismatch")
            self.assertEqual((stdout.getvalue(), self.engine.pauses, app.auth.valid(old)), ("", [], True))
            port, _code, generation = sshsession.ControlLink(None, 0).attach()             # --port 0: any port
        self.assertEqual((port, generation, self.engine.pauses), (8766, 1, ["takeover"]))

    def test_the_lifetime_check_pauses_and_ends_the_session(self):
        app = self.make(grace_s=10, max_session_s=100)
        app.control("attach_viewer", {"port": 0})
        app.control("viewer_away", {"viewer": 1})
        self.assertIsNone(app.check_lifetime())
        self.clock.advance(10)
        self.assertEqual(app.check_lifetime(), "abandoned")
        self.assertEqual((app.stop_reason, self.engine.stops, app.stopping.is_set()),
                         ("abandoned", ["abandoned"], True))
        app = self.make(max_session_s=100)
        token = app.auth.exchange(app.auth.issue_code())
        app.stream_open(token)                                          # watched all along
        self.clock.advance(100)
        self.assertEqual(app.check_lifetime(), "max_session")
        self.assertEqual(self.engine.stops, ["max_session"])
        app = self.make()
        app.control("attach_viewer", {"port": 0})
        self.clock.advance(lifetime.VIEWER_TIMEOUT_S)                 # a silent attached viewer
        self.assertIsNone(app.check_lifetime())
        self.assertEqual(self.engine.pauses, ["takeover", "not_watched"])

    def test_claim_control(self):
        app = self.make()
        first = app.auth.exchange(app.auth.issue_code())
        app.stream_open(first)
        second = app.auth.exchange(app.auth.issue_code())
        refused = (409, {"ok": False, "code": "not_controller"})
        self.assertEqual(self.command(app, second, "play", "nonce-0001"), refused)
        for name in ("place", "seek", "cancel_all", "stop"):    # every command but claim_control, built or not
            self.assertEqual(self.command(app, second, name, "nonce-ro-" + name), refused, name)
        self.assertEqual(self.command(app, first, "place", "nonce-0010"), (200, {"ok": False, "code": "not_implemented"}))
        self.assertEqual(self.command(app, second, "claim_control", "nonce-0002", {"x": 1}),
                         (400, {"ok": False, "code": "bad_args"}))
        self.assertEqual(self.command(app, second, "claim_control", "nonce-0003"), (200, {"ok": True}))
        self.assertEqual(self.engine.watched[-1], False)              # the new controller has no stream: pause
        self.assertEqual(self.command(app, second, "claim_control", "nonce-0003"), (200, {"ok": True}))  # replay
        self.assertEqual(self.command(app, first, "play", "nonce-0004"), refused)
        self.assertEqual(self.command(app, second, "play", "nonce-0005"), (200, {"ok": True}))
        self.assertEqual(self.engine.commands, ["play"])                # claim_control never reaches the actor
        app.stream_open(second)
        self.assertEqual(self.engine.watched[-1], True)
        self.assertEqual(app.query(first, {"query": "session", "args": {}})[1]["controller"], False)
        self.assertEqual(app.query(second, {"query": "session", "args": {}})[1]["controller"], True)

    def test_a_claim_control_that_fails_forgets_its_nonce(self):
        # A replay waits for the first request without a timeout, so a failed claim must not leave its nonce open.
        app = self.make()
        token = app.auth.exchange(app.auth.issue_code())
        self.engine.set_watched = lambda watched: (_ for _ in ()).throw(RuntimeError("synthetic"))
        with self.assertRaises(RuntimeError):
            self.command(app, token, "claim_control", "nonce-0001")
        new, entry = app.nonces.claim("nonce-0001")
        self.assertTrue(new)                                            # forgotten, so it may be sent again
        app.nonces.forget("nonce-0001", entry)


# --- sshsession.main: the forced command's port --------------------------------------------------------------

class ViewerPortTests(unittest.TestCase):
    """Without --port (the forced command) ssh-session serves or attaches only on VIEWER_PORT, the port of the viewer
    key's permitopen and the Air's LocalForward (DESIGN.md 8.6 item 2). server.run is replaced: nothing starts here."""

    def main(self, cfg, port):
        stdout = Stdout()
        with mock.patch.object(server, "run", return_value=0) as run:
            try:
                result = sshsession.main(cfg, port=port, stdin=Stdin(), stdout=stdout)
            except SuiteError as exc:
                result = exc.code
        return result, run.call_args_list, stdout.getvalue()

    def test_the_forced_command_refuses_another_config_port_before_any_engine(self):
        self.assertEqual(self.main({"port": 8766}, None), ("viewer_port_mismatch", [], ""))

    def test_the_viewer_port_and_an_explicit_port_reach_server_run(self):
        for cfg, port, expected in (({"port": 8765}, None, 8765), ({"port": 8766}, 0, 0), ({"port": 8766}, 9000, 9000)):
            with self.subTest(cfg=cfg, port=port):
                result, calls, out = self.main(cfg, port)
                self.assertEqual((result, len(calls), out), (0, 1, ""))
                self.assertEqual((calls[0].kwargs["command"], calls[0].kwargs["port"]), ("ssh-session", expected))
                self.assertEqual(calls[0].kwargs["session"].port, expected)     # what an attach will expect

    def test_the_viewer_port_is_the_config_default(self):
        from betangel_suite import config
        self.assertEqual(sshsession.VIEWER_PORT, config.DEFAULTS["port"])
        self.assertEqual(sshsession.VIEWER_PORT, 8765)


# --- cli.py: arguments, the SSH flag, and the state-root comparison of bin/suite test --------------------------

class CliTests(unittest.TestCase):

    def test_open_arguments(self):
        self.assertEqual(cli.parse_open_args([]), {"port": None, "print_url": False})
        self.assertEqual(cli.parse_open_args(["--print-url"]), {"port": None, "print_url": True})
        self.assertEqual(cli.parse_open_args(["--port", "0", "--print-url"]), {"port": 0, "print_url": True})
        self.assertEqual(cli.parse_open_args(["--print-url", "--port", "8766"]), {"port": 8766, "print_url": True})
        for args in (["--print-url", "--print-url"], ["--print"], ["--port"], ["--print-url", "x"],
                     ["--port", "0", "--print-url", "--port", "0"], ["--PRINT-URL"]):
            with self.assertRaises(SuiteError, msg=args) as caught:
                cli.parse_open_args(args)
            self.assertEqual(caught.exception.code, "bad_arguments")
        self.assertIs(cli._PARSERS["open"], cli.parse_open_args)
        self.assertIs(cli._PARSERS["serve"], cli.parse_port_args)        # serve never takes --print-url
        self.assertIs(cli._PARSERS["ssh-session"], cli.parse_port_args)

    def test_the_ssh_flag_from_bin_suite(self):
        cli.check_ssh("ssh-session", "1")
        for value in ("", "0", "yes", "11"):
            with self.assertRaises(SuiteError, msg=value) as caught:
                cli.check_ssh("ssh-session", value)
            self.assertEqual(caught.exception.code, "ssh_session_outside_ssh")
        for command in ("open", "serve"):
            cli.check_ssh(command, "0")
            cli.check_ssh(command, "")
            for value in ("1", "x"):
                with self.assertRaises(SuiteError) as caught:
                    cli.check_ssh(command, value)
                self.assertEqual(caught.exception.code, "open_over_ssh")
        for command in ("stop", "test", "selfcheck"):
            cli.check_ssh(command, "1")
            cli.check_ssh(command, "0")
        self.assertEqual(cli.VIA_SSH_ENV, "SUITE_VIA_SSH")

    def test_unexplained_state_changes(self):
        lock, socket_entry, run = ("run/engine.lock", False), ("run/control.sock", False), ("run", True)
        salt, stop_file, config = ("install-salt", False), ("run/STOP", False), ("config.json", False)
        empty, base = [], [config]
        changes = cli.unexplained_changes
        # Yu starts the first engine ever during the run: run/, the lock and the socket appear, the lock is held.
        self.assertEqual(changes(base, base + [run, lock, socket_entry], False, True), [])
        # Yu stops an engine during the run: its socket goes; the lock file stays.
        self.assertEqual(changes(base + [run, lock, socket_entry], base + [run, lock], True, False), [])
        # Yu starts an engine where one ran before: only the socket appears.
        self.assertEqual(changes(base + [run, lock], base + [run, lock, socket_entry], False, True), [])
        # Without a live lock to explain them, the same entries count (a test's own engine, say).
        self.assertEqual(changes(base, base + [run, lock, socket_entry], False, False),
                         sorted([run, lock, socket_entry]))
        self.assertEqual(changes(base + [run, lock], base + [run, lock, socket_entry], True, False), [socket_entry])
        self.assertEqual(changes(base + [run, lock, socket_entry], base + [run, lock], False, False), [socket_entry])
        # A live engine never explains anything else, nor a lock or run/ that vanished.
        self.assertEqual(changes(base + [run, lock], base + [run, lock, stop_file, salt], True, True),
                         sorted([stop_file, salt]))
        self.assertEqual(changes(base + [run, lock], base, True, True), sorted([run, lock]))
        self.assertEqual(changes(base, empty, True, True), [config])
        self.assertEqual(changes(base, base, False, False), [])
        # run/realdata.lock: every engine takes it in cli.main before its TMPDIR (DESIGN.md 6.8), so the first engine
        # ever in a HOME makes it too. A live engine explains it appearing; nothing explains it without one, and
        # nothing explains it vanishing (the suite never removes it).
        realdata = ("run/realdata.lock", False)
        self.assertIn(realdata, cli.ENGINE_ENTRIES)
        self.assertEqual(changes(base, base + [run, lock, realdata, socket_entry], False, True), [])
        self.assertEqual(changes(base + [run, lock], base + [run, lock, realdata, socket_entry], False, True), [])
        self.assertEqual(changes(base, base + [run, lock, realdata, socket_entry], False, False),
                         sorted([run, lock, realdata, socket_entry]))
        self.assertEqual(changes(base + [run], base + [run, realdata], False, False), [realdata])
        self.assertEqual(changes(base + [run, lock, realdata], base + [run, lock], True, True), [realdata])


if __name__ == "__main__":
    unittest.main()
