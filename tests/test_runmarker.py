"""I-17: no engine, and nothing on real data, while Nuance's run marker exists (DESIGN.md 6.8; adaptation E).

A present marker, an unreadable marker or an unreadable marker directory refuses every command except
stop, before anything is created. That includes test, on 3.13 and on the 3.11 floor, and vendor (Nuance's
answers to Q-N14). A test run that is already going stops before its next test once the marker appears
(Nuance's PR #4 review, item 14).

The realdata lock (Nuance's PR #2 review, item 6; PR #1 review, item 5): a real-data command holds LOCK_SH on
run/realdata.lock for its life, taken before its TMPDIR and with the marker checked again under it, and a stand-in
for Nuance's wrapper (WRAPPER, which never imports betangel_suite) shows that LOCK_EX waits for the holder. All
markers and locks live under a temporary HOME.
"""

import fcntl
import io
import json
import os
import stat
import subprocess
import time
import unittest

from betangel_suite import cli, config, roots, runmarker
from betangel_suite.errors import SuiteError
from tests import ARM_ENGINE, PYTHON, child_env, make_home, run_python, run_suite, start_suite, tree_listing

PROBE_SENTINEL = "mid-run-marker-probe"     # made only in a temporary HOME, by MidRunTests


def marker(home):
    return runmarker.marker_path(None, home)


class MarkerStateTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)
        self.path = marker(self.home)
        self.directory = os.path.dirname(self.path)

    def assert_state(self, expected):
        self.assertEqual(runmarker.state(self.path), expected)
        self.assertEqual(runmarker.active(self.path), expected is not None)
        if expected is None:
            runmarker.require_absent(self.path)
        else:
            with self.assertRaises(SuiteError) as caught:
                runmarker.require_absent(self.path)
            self.assertEqual(caught.exception.code, "run_marker_" + expected)

    def restore(self, path):
        self.addCleanup(os.chmod, path, 0o700)

    def test_default_path_is_the_proposed_marker(self):
        self.assertEqual(config.DEFAULTS["run_marker"], "~/.local/state/lab-runs/ACTIVE")
        self.assertEqual(self.path, os.path.join(self.home, ".local", "state", "lab-runs", "ACTIVE"))

    def test_no_directory_means_absent(self):
        self.assert_state(None)

    def test_empty_directory_means_absent(self):
        os.makedirs(self.directory)
        self.assert_state(None)

    def test_any_entry_is_present(self):
        os.makedirs(self.directory)
        for make in (lambda: open(self.path, "w").close(), lambda: os.mkdir(self.path),
                     lambda: os.symlink(os.path.join(self.home, "nowhere"), self.path)):
            make()
            self.assert_state(runmarker.PRESENT)
            (os.rmdir if os.path.isdir(self.path) and not os.path.islink(self.path) else os.remove)(self.path)

    def test_unreadable_marker_is_present(self):
        os.makedirs(self.directory)
        open(self.path, "w").close()
        os.chmod(self.path, 0)
        self.assert_state(runmarker.PRESENT)

    def test_unreadable_directory_counts_as_present(self):
        os.makedirs(self.directory)
        for mode in (0, 0o300, 0o600):
            os.chmod(self.directory, mode)
            self.restore(self.directory)
            self.assert_state(runmarker.UNREADABLE)
            os.chmod(self.directory, 0o700)

    def test_unsearchable_parent_counts_as_present(self):
        os.makedirs(self.directory)
        parent = os.path.dirname(self.directory)
        os.chmod(parent, 0)
        self.restore(parent)
        self.assert_state(runmarker.UNREADABLE)

    def test_directory_that_is_a_file_counts_as_present(self):
        with open(self.directory, "w") as handle:
            handle.write("synthetic")
        self.assert_state(runmarker.UNREADABLE)


class StartTimeTests(unittest.TestCase):
    """bin/suite with a temporary HOME: the check runs before anything is created."""

    def suite(self, home, *args):
        result = run_suite(list(args), home, env=child_env(home))
        return result.returncode, result.stderr

    def test_marker_refuses_engine_commands_before_any_write(self):
        home = make_home(self)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        before = tree_listing(home)
        for command in ("serve", "open", "catalogue", "selfcheck", "diagnose", "ledger-summary", "release", "uisnap"):
            self.assertEqual(self.suite(home, command), (2, "refused:run_marker_present\n"), command)
        self.assertEqual(tree_listing(home), before)
        os.remove(path)
        self.assertEqual(self.suite(home, "selfcheck"), (2, "refused:not_implemented\n"))

    def test_unreadable_marker_directory_refuses(self):
        home = make_home(self)
        directory = os.path.dirname(marker(home))
        os.makedirs(directory)
        os.chmod(directory, 0)
        self.addCleanup(os.chmod, directory, 0o700)
        self.assertEqual(self.suite(home, "catalogue"), (2, "refused:run_marker_unreadable\n"))

    def test_config_cannot_move_the_marker(self):
        # A config naming a marker that never exists would switch the start check off (I-17): refused.
        home = make_home(self)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        config_path = os.path.join(home, ".local", "state", "betangel-suite", "config.json")
        for value in ("~/decoy-never-created/ACTIVE", "~/runs/ACTIVE"):
            with open(config_path, "w") as handle:
                json.dump({"run_marker": value}, handle)
            self.assertEqual(self.suite(home, "selfcheck"), (2, "refused:config_invalid_value\n"), value)
        with open(config_path, "w") as handle:
            json.dump({"run_marker": "~/.local/state/lab-runs/ACTIVE"}, handle)
        self.assertEqual(self.suite(home, "selfcheck"), (2, "refused:run_marker_present\n"))

    def test_stop_does_not_check_the_marker(self):
        # stop only reduces activity (DESIGN 3.9 rule 6), so a run in progress must not block it.
        home = make_home(self)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        self.assertEqual(self.suite(home, "stop"), (2, "refused:not_implemented\n"))

    def test_test_refuses_while_the_marker_exists(self):
        # Q-N14, Nuance: "no". Both interpreters refuse, before the arguments are read, any test is loaded or
        # anything is created. Every run names no test or bad arguments, so a regression cannot start a
        # nested full run.
        home = make_home(self, deps=True)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        runs = (("test", "-k", "zzz_no_such_test"), ("test", "--py311", "-v", "-k", "zzz_no_such_test"))
        bad = (("test", "--no-such-flag"), ("test", "--py311", "--no-such-flag"))
        before = tree_listing(home)
        for args in runs + bad:
            self.assertEqual(self.suite(home, *args), (2, "refused:run_marker_present\n"), args)
        self.assertEqual(tree_listing(home), before)
        os.remove(path)
        os.chmod(os.path.dirname(path), 0)
        self.addCleanup(os.chmod, os.path.dirname(path), 0o700)
        for args in runs:
            self.assertEqual(self.suite(home, *args), (2, "refused:run_marker_unreadable\n"), args)
        os.chmod(os.path.dirname(path), 0o700)
        for args in runs:                       # with the marker gone, the same runs start and find no test
            returncode, stderr = self.suite(home, *args)
            self.assertEqual(returncode, 0, stderr)
            self.assertIn("Ran 0 tests", stderr)
        for args in bad:
            self.assertEqual(self.suite(home, *args), (2, "refused:bad_arguments\n"), args)
        self.assertFalse(os.path.lexists(runmarker.lock_path(home)))       # test never takes the realdata lock

    def test_vendor_refuses_while_the_marker_exists(self):
        # vendor was first exempt. Nuance's PR #1 review, answering Q-N14: "test and vendor refuse under
        # the marker; stop stays exempt". vendor writes the deps clone, and pin/ with --bump, and clones the
        # whole of ~/betangel-research. Each run is refused before its arguments are read or anything is made.
        home = make_home(self)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        pin_file = os.path.join(home, "pin.json")          # never this checkout's pin, even if a run started
        runs = (("vendor",), ("vendor", "f" * 40, "--pin-file", pin_file),
                ("vendor", "f" * 40, "--bump", "--pin-file", pin_file))
        before = tree_listing(home)
        for args in runs:
            self.assertEqual(self.suite(home, *args), (2, "refused:run_marker_present\n"), args)
        self.assertEqual(tree_listing(home), before)
        os.remove(path)
        os.chmod(os.path.dirname(path), 0)
        self.addCleanup(os.chmod, os.path.dirname(path), 0o700)
        self.assertEqual(self.suite(home, "vendor"), (2, "refused:run_marker_unreadable\n"))
        os.chmod(os.path.dirname(path), 0o700)
        self.assertEqual(self.suite(home, "vendor"), (2, "refused:bad_arguments\n"))   # no marker: it starts
        self.assertFalse(os.path.lexists(runmarker.lock_path(home)))       # vendor never takes the realdata lock



class RunnerStopTests(unittest.TestCase):
    """cli.marker_stop_result on its own: after each test it checks a marker under a temporary HOME."""

    def run_steps(self, step):
        """Run two tests; the first calls step(marker path). Returns (tests that ran, result)."""
        home = make_home(self)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        ran = []

        class Steps(unittest.TestCase):
            def test_1(inner):
                ran.append(1)
                step(path)

            def test_2(inner):
                ran.append(2)

        runner = unittest.TextTestRunner(stream=io.StringIO(),
                                         resultclass=cli.marker_stop_result(unittest.TextTestResult, path))
        return ran, runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(Steps))

    def test_no_marker_lets_every_test_run(self):
        ran, result = self.run_steps(lambda path: None)
        self.assertEqual((ran, result.run_marker, result.wasSuccessful()), ([1, 2], None, True))

    def test_a_marker_that_appears_stops_the_run_before_the_next_test(self):
        ran, result = self.run_steps(lambda path: open(path, "w").close())
        self.assertEqual((ran, result.testsRun, result.run_marker), ([1], 1, runmarker.PRESENT))
        self.assertFalse(result.wasSuccessful())

    def test_a_marker_directory_that_becomes_unreadable_stops_the_run_too(self):
        def lock(path):
            os.chmod(os.path.dirname(path), 0)
            self.addCleanup(os.chmod, os.path.dirname(path), 0o700)
        ran, result = self.run_steps(lock)
        self.assertEqual((ran, result.run_marker), ([1], runmarker.UNREADABLE))
        self.assertFalse(result.wasSuccessful())


class MidRunProbe(unittest.TestCase):
    """Two steps for MidRunTests's nested `bin/suite test -k mid_run_probe`. They act only under a HOME that
    holds PROBE_SENTINEL, which only MidRunTests makes, in a temporary HOME; anywhere else they pass at once."""

    def probing(self):
        return os.path.exists(os.path.join(os.environ["HOME"], PROBE_SENTINEL))

    def test_mid_run_probe_1_waits_for_the_marker(self):
        if self.probing():
            open(os.path.join(os.environ["TMPDIR"], "probe-1-started"), "w").close()
            deadline = time.monotonic() + 60
            while not runmarker.active(marker(os.environ["HOME"])) and time.monotonic() < deadline:
                time.sleep(0.05)

    def test_mid_run_probe_2_must_not_start(self):
        if self.probing():
            open(os.path.join(os.environ["TMPDIR"], "probe-2-started"), "w").close()


class MidRunTests(unittest.TestCase):

    def test_a_marker_that_appears_mid_run_stops_bin_suite_test_before_its_next_test(self):
        # Nuance's PR #4 review, item 14. The launcher checks the marker once, before the run; the runner checks it
        # again after every test. The nested run's first probe waits until the marker exists, so the marker appears
        # while that test runs. The second probe must then never start, and the run is refused.
        home = make_home(self, deps=True)
        open(os.path.join(home, PROBE_SENTINEL), "w").close()
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        tmp = roots.tmp_dir("test", home)
        child = start_suite(["test", "-k", "mid_run_probe"], home)
        try:
            deadline = time.monotonic() + 60
            while (not os.path.exists(os.path.join(tmp, "probe-1-started")) and child.poll() is None
                   and time.monotonic() < deadline):
                time.sleep(0.05)
            open(path, "w").close()
            _out, err = child.communicate(timeout=120)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
        self.assertEqual(child.returncode, 2, err[-2000:])
        self.assertIn("\nRan 1 test in ", err)
        self.assertTrue(err.endswith("\nrefused:run_marker_present\n"), err[-2000:])
        self.assertTrue(os.path.exists(os.path.join(tmp, "probe-1-started")))
        self.assertFalse(os.path.exists(os.path.join(tmp, "probe-2-started")))


# A stand-in for Nuance's run wrapper, as DESIGN.md 6.8 and Nuance's PR #2 review describe it: it runs outside the
# suite (never imports betangel_suite), creates the marker with O_EXCL, then takes LOCK_EX on the realdata lock,
# waiting up to wait_s and failing closed. A missing lock file counts as free. It removes only its own marker, at
# its end.
WRAPPER = r"""
import fcntl, json, os, sys, time
marker, lock, wait_s = %r, %r, %r
os.makedirs(os.path.dirname(marker), exist_ok=True)
os.close(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
started = time.monotonic()
try:
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
except FileNotFoundError:
    fd = None
result, status = "free", 0
while fd is not None:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = "locked"
        break
    except BlockingIOError:
        if time.monotonic() - started > wait_s:
            result, status = "refused", 3
            break
        time.sleep(0.02)
print(json.dumps({"result": result, "waited_s": round(time.monotonic() - started, 2)}), flush=True)
os.remove(marker)
sys.exit(status)
"""

# An engine-mode child (a stop-mode one for stop), as bin/_launch.py would leave it, that runs cli.main with a
# stand-in handler. signal() and wait_for() use files in its TMPDIR (the temporary HOME's state tmp/), which the
# test watches and writes too.
HOLDER = ARM_ENGINE + r"""
import os, sys, time
from betangel_suite import cli, errors, roots, runmarker
TMP = os.environ["TMPDIR"]

def signal(name):
    open(os.path.join(TMP, name), "w").close()

def wait_for(name):
    deadline = time.monotonic() + 60
    while not os.path.exists(os.path.join(TMP, name)):
        if time.monotonic() > deadline:
            sys.exit(5)
        time.sleep(0.02)

def run(argv):
    try:
        return cli.main(argv)
    except errors.SuiteError as exc:
        sys.stderr.write(errors.describe(exc) + "\n")
        return 2
"""


class RealDataLockTests(unittest.TestCase):
    """runmarker.hold_shared through cli.main, in engine-mode children with a temporary HOME."""

    def setUp(self):
        self.home = make_home(self, deps=True)
        os.mkdir(roots.data_home(self.home), 0o700)         # the suite root's parent, as on the lab
        self.tmp = roots.tmp_dir("test", self.home)
        self.marker = marker(self.home)
        self.lock = runmarker.lock_path(self.home)
        self.suite = roots.suite_root(self.home)

    def start(self, code):
        child = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-c", code], env=child_env(self.home), cwd=self.home,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.reap, child)
        return child

    def reap(self, child):
        if child.poll() is None:
            child.kill()
        child.communicate()

    def holder(self, body, mode="engine"):
        return self.start(HOLDER.replace("guard.arm('engine')", "guard.arm(%r)" % mode, 1) + body)

    def wrapper(self, wait_s):
        return self.start(WRAPPER % (self.marker, self.lock, wait_s))

    def signal(self, name):
        open(os.path.join(self.tmp, name), "w").close()

    def wait_for(self, name, child):
        deadline = time.monotonic() + 60
        path = os.path.join(self.tmp, name)
        while not os.path.exists(path) and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not os.path.exists(path):
            self.fail("%s never came: %r" % (name, child.communicate(timeout=60)))

    def finish(self, child):
        out, err = child.communicate(timeout=120)
        return child.returncode, out, err

    def wrapper_result(self, child):
        status, out, err = self.finish(child)
        self.assertEqual(err, "")
        return status, json.loads(out)

    def test_the_commands_that_take_the_lock(self):
        self.assertEqual(cli.REALDATA_COMMANDS,
                         ("serve", "open", "ssh-session", "catalogue", "selfcheck", "diagnose", "ledger-summary"))
        self.assertLessEqual(set(cli.REALDATA_COMMANDS), set(cli.COMMANDS))
        for command in ("test", "uisnap", "vendor", "stop"):
            self.assertNotIn(command, cli.REALDATA_COMMANDS)
        self.assertEqual(cli.NO_TMPDIR, ("stop", "vendor"))
        self.assertFalse(set(cli.NO_TMPDIR) & set(cli.REALDATA_COMMANDS))
        self.assertEqual(self.lock, os.path.join(self.home, ".local", "state", "betangel-suite", "run", "realdata.lock"))

    def test_a_wrapper_waits_for_a_holder_and_fails_closed_at_its_deadline(self):
        holder = self.holder(r"""
def handler(args):
    signal("holding")
    wait_for("release")
    return 0
cli._HANDLERS["catalogue"] = handler
sys.exit(run(["catalogue"]))
""")
        self.wait_for("holding", holder)
        info = os.lstat(self.lock)
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertTrue(os.path.isdir(os.path.join(self.suite, "tmp")))    # made after the lock was taken
        # A wrapper that waits 1 s refuses its own run: no LOCK_EX while the holder lives.
        status, result = self.wrapper_result(self.wrapper(1.0))
        self.assertEqual((status, result["result"]), (3, "refused"))
        self.assertGreaterEqual(result["waited_s"], 1.0)
        # One that waits longer is still waiting while the holder lives, and gets the lock once it has gone.
        waiting = self.wrapper(60.0)
        # Its clock starts when it has made the marker, not when it was spawned: under load its start-up alone
        # can take tens of ms, so count the 0.5 s from the marker (the first wrapper removed its own).
        deadline = time.monotonic() + 60
        while not os.path.exists(self.marker) and waiting.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.5)
        self.assertIsNone(waiting.poll())
        self.assertIsNone(holder.poll())
        self.signal("release")
        self.assertEqual(self.finish(holder), (0, "", ""))
        status, result = self.wrapper_result(waiting)
        self.assertEqual((status, result["result"]), (0, "locked"))
        self.assertGreaterEqual(result["waited_s"], 0.5)
        self.assertTrue(os.path.lexists(self.lock))                       # never unlinked

    def test_a_headless_holder_stops_at_its_next_member_and_lets_the_wrapper_in(self):
        holder = self.holder(r"""
def handler(args):
    for member in range(3000):
        runmarker.require_clear()
        if member == 0:
            signal("holding")
        time.sleep(0.02)
    return 0
cli._HANDLERS["catalogue"] = handler
sys.exit(run(["catalogue"]))
""")
        self.wait_for("holding", holder)
        waiting = self.wrapper(60.0)
        self.assertEqual(self.finish(holder), (2, "", "refused:run_marker_present\n"))
        status, result = self.wrapper_result(waiting)
        self.assertEqual((status, result["result"]), (0, "locked"))
        self.assertLess(result["waited_s"], 30)

    def test_a_holder_checks_the_marker_again_after_locking(self):
        # The race the lock closes: the launcher's check passed, then the wrapper made the marker before the command
        # took its lock. The command must refuse under the lock, before anything is made under ~/betangel-data, and
        # let the lock go at once, while it is still running.
        holder = self.holder(r"""
runmarker.require_absent(runmarker.marker_path())      # bin/_launch.py's check, passed
signal("checked")
wait_for("go")
def handler(args):
    signal("handler-ran")
    return 0
cli._HANDLERS["catalogue"] = handler
status = run(["catalogue"])
signal("returned")
wait_for("exit")
sys.exit(status)
""")
        self.wait_for("checked", holder)
        os.makedirs(os.path.dirname(self.marker))
        open(self.marker, "w").close()                  # the wrapper makes the marker first
        self.signal("go")
        self.wait_for("returned", holder)
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)    # free while the refused command still runs
        finally:
            os.close(fd)
        self.signal("exit")
        self.assertEqual(self.finish(holder), (2, "", "refused:run_marker_present\n"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "handler-ran")))
        self.assertEqual(os.listdir(roots.data_home(self.home)), [])        # no suite root, no tmp/

    def test_a_lock_the_wrapper_holds_refuses_at_once(self):
        # Between the wrapper removing its marker and letting the lock go, a command sees no marker but cannot lock.
        os.makedirs(os.path.dirname(self.lock), 0o700)
        fd = os.open(self.lock, os.O_RDONLY | os.O_CREAT, 0o600)
        body = r"""
def handler(args):
    signal("handler-ran")
    return 0
cli._HANDLERS["selfcheck"] = handler
sys.exit(run(["selfcheck"]))
"""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.finish(self.holder(body)), (2, "", "refused:run_lock_busy\n"))
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "handler-ran")))
            self.assertEqual(os.listdir(roots.data_home(self.home)), [])
        finally:
            os.close(fd)
        self.assertEqual(self.finish(self.holder(body)), (0, "", ""))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "handler-ran")))

    def test_stop_needs_neither_the_lock_nor_a_tmpdir(self):
        # Round-4 review: cli.main refused stop with run_lock_not_held, because its TMPDIR lies under ~/betangel-data
        # and it takes no lock. stop must work during a run (DESIGN.md 6.8): here the marker exists and the wrapper
        # holds LOCK_EX, and stop (a stand-in handler) still runs, takes nothing and makes nothing.
        os.makedirs(os.path.dirname(self.lock), 0o700)
        os.makedirs(os.path.dirname(self.marker))
        open(self.marker, "w").close()
        fd = os.open(self.lock, os.O_RDONLY | os.O_CREAT, 0o600)
        body = r"""
def handler(args):
    print("stop-ran", runmarker.holding())
    return 0
cli._HANDLERS["stop"] = handler
sys.exit(run(["stop"]))
"""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.finish(self.holder(body, mode="stop")), (0, "stop-ran False\n", ""))
        finally:
            os.close(fd)
        self.assertEqual(os.listdir(roots.data_home(self.home)), [])        # no suite root, no tmp/

    def test_no_tmpdir_under_the_data_home_without_the_lock(self):
        # A command that may touch real data but is missing from REALDATA_COMMANDS refuses before its TMPDIR.
        body = r"""
cli.REALDATA_COMMANDS = ()
cli._HANDLERS["diagnose"] = lambda args: 0
sys.exit(run(["diagnose"]))
"""
        self.assertEqual(self.finish(self.holder(body)), (2, "", "refused:run_lock_not_held\n"))
        self.assertEqual(os.listdir(roots.data_home(self.home)), [])

    def test_a_state_root_it_cannot_write_refuses(self):
        # The round-4 reviewer's state_not_writable probe: run/ cannot be made, so the lock cannot be opened. That
        # was an uncaught PermissionError (exit 1), not a refusal.
        state = roots.state_dir(self.home)
        os.chmod(state, 0o500)
        self.addCleanup(os.chmod, state, 0o700)
        body = r"""
cli._HANDLERS["diagnose"] = lambda args: 0
sys.exit(run(["diagnose"]))
"""
        self.assertEqual(self.finish(self.holder(body)), (2, "", "refused:run_lock_invalid\n"))
        self.assertFalse(os.path.lexists(roots.run_dir(self.home)))
        self.assertEqual(os.listdir(roots.data_home(self.home)), [])

    def test_only_a_real_private_lock_file_is_held(self):
        state = roots.state_dir(self.home)
        cases = []
        for label, make in (("symlink", lambda path: os.symlink(os.path.join(state, "elsewhere"), path)),
                            ("fifo", os.mkfifo), ("directory", os.mkdir),
                            ("group_writable", lambda path: (open(path, "w").close(), os.chmod(path, 0o620))),
                            ("two_links", lambda path: (open(path, "w").close(),
                                                        os.link(path, os.path.join(os.path.dirname(path), "x"))))):
            directory = os.path.join(state, "case-" + label)
            os.mkdir(directory, 0o700)
            make(os.path.join(directory, "realdata.lock"))
            cases.append((label, os.path.join(directory, "realdata.lock")))
        readable = os.path.join(state, "case-readable", "realdata.lock")
        os.mkdir(os.path.dirname(readable), 0o700)
        open(readable, "w").close()
        os.chmod(readable, 0o644)                       # made by someone else with umask 022: still a lock file
        code = ARM_ENGINE + r"""
from betangel_suite import errors, runmarker
marker = runmarker.marker_path()
for label, path in %r + [("missing", %r), ("again", %r)]:
    try:
        runmarker.require_clear() if label == "again" else None
        runmarker.hold_shared(marker, path)
        print(label, "held", runmarker.holding())
    except errors.SuiteError as exc:
        print(label, exc.code, runmarker.holding())
""" % (cases, self.lock, readable)
        result = run_python(code, self.home, timeout=60)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [label + " run_lock_invalid False" for label, _ in cases] + [
            "missing held True", "again run_lock_invalid True"])
        info = os.lstat(self.lock)
        self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode)), (True, 0o600))
        code = ARM_ENGINE + r"""
from betangel_suite import errors, runmarker
runmarker.hold_shared(runmarker.marker_path(), %r)
print("held", runmarker.holding())
""" % (readable,)
        result = run_python(code, self.home, timeout=60)
        self.assertEqual((result.stdout, result.stderr), ("held True\n", ""))

    def test_require_clear_needs_the_lock_on_the_file_still_in_place(self):
        other = os.path.join(roots.state_dir(self.home), "elsewhere", "realdata.lock")
        code = ARM_ENGINE + r"""
import os
from betangel_suite import errors, runmarker

def clear():
    try:
        runmarker.require_clear()
        return "clear"
    except errors.SuiteError as exc:
        return exc.code

lock = %r
print(clear())
runmarker.hold_shared(runmarker.marker_path(), lock)
print(clear())
os.rename(lock, lock + ".old")
os.close(os.open(lock, os.O_RDONLY | os.O_CREAT, 0o600))
print(clear())
""" % (other,)
        result = run_python(code, self.home, timeout=60)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), ["run_lock_not_held", "clear", "run_lock_invalid"])


if __name__ == "__main__":
    unittest.main()
