"""bin/suite test's state-root check with an engine Yu starts or stops meanwhile (Phase 0c; cli.unexplained_changes).

bin/suite test lists the real state root (tmp/ excluded) before and after the run and refuses with
state_root_changed if anything changed: tests write only under TMPDIR, so a change means a test escaped its
temporary HOME. An engine Yu starts or stops during an agent's run (serve, open, ssh-session) changes run/ too; its
lock (run/engine.lock, held while it runs) explains exactly run/, the lock and run/control.sock appearing, and the
socket vanishing, and nothing else.

Each case runs an inner `bin/suite test` under a temporary HOME (short_home, with the deps copy) selecting only
HoldTests below, which holds the inner run open until this test has started or stopped a real synthetic serve child
in the same HOME (or planted a stray file in its state root). The pure comparison is tested in process in
tests/test_session_lifetime.py.
"""

import os
import subprocess
import time
import unittest

from betangel_suite import cli, roots
from betangel_suite.api import control
from tests import LAUNCHER, child_env, run_suite
from tests import test_http_support as support

HOLD = "hold-test-run"          # in the inner run's TMPDIR (outside the listing): its own switch, never the real one


class HoldTests(unittest.TestCase):
    """Only for StateRootTests' inner runs: skipped unless TMPDIR has the hold file, which StateRootTests creates only
    in a temporary HOME's TMPDIR (never in the real one, which concurrent runs share)."""

    def test_hold_while_an_engine_starts_or_stops(self):
        tmp = os.environ["TMPDIR"]
        if not os.path.lexists(os.path.join(tmp, HOLD)):
            self.skipTest("runs only inside StateRootTests")
        fd = os.open(os.path.join(tmp, "held"), os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
        deadline = time.monotonic() + 60
        while not os.path.lexists(os.path.join(tmp, "release")):
            self.assertLess(time.monotonic(), deadline, "never released")
            time.sleep(0.02)


def wait_path(path, process, timeout=60.0):
    deadline = time.monotonic() + timeout
    while not os.path.lexists(path):
        if time.monotonic() > deadline or process.poll() is not None:
            raise AssertionError("not created: " + os.path.basename(path))
        time.sleep(0.02)


class StateRootTests(unittest.TestCase):

    def inner_run(self, home, during):
        """(exit status, stderr) of an inner bin/suite test held open while during() runs."""
        tmp = roots.tmp_dir("test", home)
        open(os.path.join(tmp, HOLD), "w").close()
        err_path = os.path.join(home, "inner.err")
        with open(err_path, "w") as err:
            inner = subprocess.Popen(["/bin/sh", LAUNCHER, "test", "-k", "test_hold_while_an_engine"],
                                     env=child_env(home), cwd=home, stdout=subprocess.DEVNULL, stderr=err)
        self.addCleanup(lambda: inner.poll() is None and inner.kill())
        try:
            wait_path(os.path.join(tmp, "held"), inner)
        except AssertionError:
            inner.poll() is None and inner.kill()
            inner.wait(10)
            raise AssertionError("the inner run did not hold: " + support.read_text(err_path)[-1500:]) from None
        during()
        open(os.path.join(tmp, "release"), "w").close()
        status = inner.wait(60)
        for name in (HOLD, "held", "release"):
            os.remove(os.path.join(tmp, name))
        return status, support.read_text(err_path)

    def test_an_engine_started_during_the_run_is_not_a_state_change(self):
        home = support.short_home(self)
        self.assertFalse(os.path.lexists(roots.run_dir(home)))       # the first engine ever in this HOME
        engines = []
        status, err = self.inner_run(home, lambda: engines.append(support.serve(self, home)))
        self.assertEqual(status, 0, err[-1500:])
        self.assertIn("Ran 1 test", err)
        self.assertNotIn("state_root_changed", err)
        serving, _port = engines[0]
        self.assertEqual(serving.terminate(), 0)

    def test_an_engine_stopped_during_the_run_is_not_a_state_change(self):
        home = support.short_home(self)
        serving, _port = support.serve(self, home)

        def stop():
            result = run_suite(["stop"], home)
            self.assertEqual(result.stdout, "stopped\n")

        status, err = self.inner_run(home, stop)
        self.assertEqual(status, 0, err[-1500:])
        self.assertNotIn("state_root_changed", err)
        self.assertEqual(serving.wait_exit(), 0)

    def test_a_test_caused_change_is_still_refused_with_an_engine_running(self):
        home = support.short_home(self)
        engines = []

        def start_and_stray():
            engines.append(support.serve(self, home))
            open(os.path.join(roots.run_dir(home), "STOP"), "w").close()     # as a test that escaped its HOME

        status, err = self.inner_run(home, start_and_stray)
        self.assertEqual(status, 1, err[-1500:])
        self.assertIn("refused:state_root_changed", err.splitlines())
        engines[0][0].terminate()

    def test_the_footprint_of_a_real_engine(self):
        # What a real serve child adds to the state root is exactly what unexplained_changes may explain.
        home = support.short_home(self)
        before = cli.state_listing(home)
        serving, _port = support.serve(self, home)
        running = cli.state_listing(home)
        self.assertTrue(control.engine_running(home))
        self.assertEqual(sorted(set(running) - set(before)), sorted({*cli.ENGINE_ENTRIES, cli.SOCKET_ENTRY}))
        self.assertEqual(cli.unexplained_changes(before, running, False, True), [])
        self.assertEqual(serving.terminate(), 0)
        after = cli.state_listing(home)
        self.assertFalse(control.engine_running(home))
        self.assertEqual(sorted(set(running) - set(after)), [cli.SOCKET_ENTRY])
        self.assertEqual(cli.unexplained_changes(running, after, True, False), [])
        self.assertEqual(cli.unexplained_changes(before, after, False, False), sorted(cli.ENGINE_ENTRIES))


if __name__ == "__main__":
    unittest.main()
