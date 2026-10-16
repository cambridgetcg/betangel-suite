"""I-17 (start-time part): no engine while Nuance's run marker exists (DESIGN.md 6.8; adaptation E).

A present marker, an unreadable marker or an unreadable marker directory refuses every command except
stop, before anything is created. That includes test, on 3.13 and on the 3.11 floor, and vendor (Nuance's
answers to Q-N14). A test run that is already going stops before its next test once the marker appears
(Nuance's PR #4 review, item 14). All markers live under a temporary HOME.
"""

import io
import json
import os
import time
import unittest

from betangel_suite import cli, config, pin, roots, runmarker
from betangel_suite.errors import SuiteError
from tests import child_env, make_home, run_suite, start_suite, tree_listing

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
        # open runs below; with no deps clone in this HOME, a marker check that let it through would stop
        # at deps_missing before the engine or /usr/bin/open.
        self.assertFalse(os.path.lexists(pin.deps_dir(pin.load(), home)))
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
        self.assertEqual(self.suite(home, "stop"), (0, ""))          # no engine running: prints not_running

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

    def test_vendor_refuses_while_the_marker_exists(self):
        # vendor was first exempt. Nuance's answer to Q-N14 in her PR #1 review: "test and vendor refuse under
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


if __name__ == "__main__":
    unittest.main()
