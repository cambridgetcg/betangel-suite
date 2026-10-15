"""I-17 (start-time part): no engine while Nuance's run marker exists (DESIGN.md 6.8; adaptation E).

A present marker, an unreadable marker or an unreadable marker directory refuses every command except
stop, test and vendor, before anything is created. All markers live under a temporary HOME.
"""

import json
import os
import unittest

from betangel_suite import config, pin, runmarker
from betangel_suite.errors import SuiteError
from tests import child_env, make_home, run_suite, tree_listing


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

    def test_test_and_vendor_do_not_check_the_marker(self):
        home = make_home(self, deps=True)
        path = marker(home)
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        self.assertEqual(self.suite(home, "vendor"), (2, "refused:bad_arguments\n"))
        returncode, stderr = self.suite(home, "test", "-k", "zzz_no_such_test")
        self.assertEqual(returncode, 0, stderr)
        self.assertIn("Ran 0 tests", stderr)
        self.assertNotIn("run_marker", stderr)


if __name__ == "__main__":
    unittest.main()
