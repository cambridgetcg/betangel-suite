"""State roots and the single writer helper (DESIGN.md 3.7; Phase 0 adaptations A and B).

The flag roots.STATE_ROOT_AGREED is on since Nuance agreed the suite root (Q-N3). Both settings are still
tested, against a temporary HOME, with mock.patch for the setting that is not the default. With the flag
off, a write under ~/betangel-data is refused on the path text alone: the tests make that directory
unreadable first, so any file-system access there would surface as a different error.
"""

import os
import stat
import unittest
from unittest import mock

from betangel_suite import cli, roots
from betangel_suite.errors import SuiteError
from tests import make_home, rmtree


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


class RootPathTests(unittest.TestCase):

    def test_flag_is_on_since_q_n3(self):
        self.assertIs(roots.STATE_ROOT_AGREED, True)

    def test_root_locations(self):
        home = "/h"
        self.assertEqual(roots.state_dir(home), "/h/.local/state/betangel-suite")
        self.assertEqual(roots.deps_root(home), "/h/.local/share/betangel-suite/deps")
        self.assertEqual(roots.suite_root(home), "/h/betangel-data/suite.noindex")
        self.assertEqual(roots.salt_path(home), "/h/.local/state/betangel-suite/install-salt")
        self.assertEqual(roots.config_path(home), "/h/.local/state/betangel-suite/config.json")
        self.assertEqual(roots.research_clone(home), "/h/betangel-research")

    def test_flag_off_every_command_uses_the_state_tmp(self):
        with mock.patch.object(roots, "STATE_ROOT_AGREED", False):
            for command in cli.COMMANDS:
                self.assertEqual(roots.tmp_dir(command, "/h"), "/h/.local/state/betangel-suite/tmp", command)
            self.assertEqual(roots.write_roots("/h"), ("/h/.local/state/betangel-suite",))

    def test_flag_on_restores_the_design(self):
        with mock.patch.object(roots, "STATE_ROOT_AGREED", True):
            self.assertEqual(roots.write_roots("/h"), ("/h/.local/state/betangel-suite", "/h/betangel-data/suite.noindex"))
            for command in cli.COMMANDS:
                expected = "/h/.local/state/betangel-suite/tmp" if command in ("test", "uisnap", "vendor") else (
                    "/h/betangel-data/suite.noindex/tmp")
                self.assertEqual(roots.tmp_dir(command, "/h"), expected, command)

    def test_place_is_text_only(self):
        for agreed in (False, True):
            with mock.patch.object(roots, "STATE_ROOT_AGREED", agreed):
                self.assertEqual(roots.place("/h/.local/state/betangel-suite/a/../b", "/h"),
                                 ("/h/.local/state/betangel-suite/b", "/h/.local/state/betangel-suite"))
                data = "write_outside_roots" if agreed else "state_root_not_agreed"
                for path, code in (("relative/x", "path_not_absolute"),
                                   ("/h/.local/state/betangel-suite/../x", "write_outside_roots"),
                                   ("/h/.local/state/betangel-suite-other/x", "write_outside_roots"),
                                   ("/h/betangel-data/suite.noindex.other/x", data), ("/h/betangel-data/historic/x", data),
                                   ("/h/Betangel-Data/x", data), ("/h/betangel-data", data),
                                   ("/h/BETANGEL-DATA/suite.noindex/x", data),
                                   ("/h/betangel-data/suite.noindex/x", None if agreed else data)):
                    if code is None:
                        self.assertEqual(roots.place(path, "/h"), (path, "/h/betangel-data/suite.noindex"))
                        continue
                    with self.assertRaises(SuiteError, msg=(agreed, path)) as caught:
                        roots.place(path, "/h")
                    self.assertEqual(caught.exception.code, code, (agreed, path))


class WriterTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)
        self.state = roots.state_dir(self.home)

    def refused(self, code, fn, *args, **kwargs):
        with self.assertRaises(SuiteError) as caught:
            fn(*args, home_dir=self.home, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_write_new_makes_private_directories_and_file(self):
        path = os.path.join(self.state, "a", "b", "file")
        self.assertEqual(roots.write_new(path, b"synthetic", home_dir=self.home), path)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"synthetic")
        self.assertEqual(mode(path), 0o600)
        for directory in (self.state, os.path.dirname(os.path.dirname(path)), os.path.dirname(path)):
            self.assertEqual(mode(directory), 0o700, directory)

    def test_existing_names_are_never_overwritten_or_followed(self):
        path = os.path.join(self.state, "file")
        roots.write_new(path, b"one", home_dir=self.home)
        self.refused("already_exists", roots.write_new, path, b"two")
        link = os.path.join(self.state, "dangling")
        os.symlink(os.path.join(self.home, "nowhere"), link)
        self.refused("already_exists", roots.write_new, link, b"x")
        self.assertFalse(os.path.lexists(os.path.join(self.home, "nowhere")))

    def test_symlinks_below_the_root_are_refused(self):
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.state, "link"))
        self.refused("symlink_refused", roots.write_new, os.path.join(self.state, "link", "x"), b"x")
        self.refused("symlink_refused", roots.ensure_dir, os.path.join(self.state, "link", "deeper"))
        self.assertEqual(os.listdir(elsewhere), [])

    def test_symlinked_root_is_refused(self):
        other_home = make_home(self)
        real = os.path.join(self.home, "real-state")
        os.makedirs(real)
        rmtree(roots.state_dir(other_home))
        os.symlink(real, roots.state_dir(other_home))
        with self.assertRaises(SuiteError) as caught:
            roots.ensure_dir(os.path.join(roots.state_dir(other_home), "x"), home_dir=other_home)
        self.assertEqual(caught.exception.code, "symlink_refused")

    def test_non_directory_component_and_missing_parent(self):
        with open(os.path.join(self.state, "plain"), "w") as handle:
            handle.write("synthetic")
        self.refused("not_a_directory", roots.ensure_dir, os.path.join(self.state, "plain", "x"))
        bare = os.path.join(os.path.dirname(self.home), "bare-home")
        os.makedirs(bare)
        with self.assertRaises(SuiteError) as caught:
            roots.ensure_dir(os.path.join(roots.state_dir(bare), "x"), home_dir=bare)
        self.assertEqual(caught.exception.code, "root_parent_missing")

    def test_existing_root_is_tightened_to_0700(self):
        os.chmod(self.state, 0o755)
        roots.ensure_dir(os.path.join(self.state, "x"), home_dir=self.home)
        self.assertEqual(mode(self.state), 0o700)

    def test_outside_the_roots(self):
        self.refused("write_outside_roots", roots.write_new, os.path.join(self.home, "x"), b"x")
        self.refused("write_outside_roots", roots.ensure_dir, os.path.join(self.home, ".local", "share", "x"))
        self.refused("path_not_absolute", roots.write_new, "relative", b"x")
        self.assertFalse(os.path.lexists(os.path.join(self.home, "x")))

    DENIED_TREES = (("Library", "Application Support", "betangel-research", "betfair"),
                    (".config", "betangel-research", "betfair"),
                    ("library", "application support", "BETANGEL-RESEARCH", "Betfair"))

    def denied(self, fn, *args):
        with self.assertRaises(SuiteError) as caught:
            fn(*args, home_dir=self.home)
        self.assertEqual((caught.exception.code, caught.exception.reason), ("path_denied", "denied_live_state_tree"))

    def test_path_guard_denied_trees_inside_the_root(self):
        # DESIGN.md 3.7 and I-6: every new path goes through upstream path_guard.guard_path, which refuses the
        # client's live-state and certificate trees wherever they are reached, inside a write root included.
        for parts in self.DENIED_TREES:
            with self.subTest(parts=parts):
                tree = os.path.join(self.state, *parts)
                self.denied(roots.ensure_dir, os.path.join(tree, "x"))
                self.denied(roots.write_new, os.path.join(tree, "x"), b"synthetic")
                self.assertFalse(os.path.lexists(tree))

    def test_path_guard_follows_a_symlink_into_a_denied_tree(self):
        # A link made before the call (outside the writer helper) into a denied tree: path_guard refuses it
        # before the helper's own symlink check is reached.
        target = os.path.join(self.home, *self.DENIED_TREES[0])
        os.makedirs(target)
        os.symlink(target, os.path.join(self.state, "alias"))
        self.denied(roots.ensure_dir, os.path.join(self.state, "alias", "deeper"))
        self.denied(roots.write_new, os.path.join(self.state, "alias", "x"), b"synthetic")
        self.assertEqual(os.listdir(target), [])

    def test_data_home_refused_without_touching_it_while_not_agreed(self):
        data_home = roots.data_home(self.home)
        os.makedirs(data_home)
        os.chmod(data_home, 0)
        self.addCleanup(os.chmod, data_home, 0o700)
        suite = roots.suite_root(self.home)
        with mock.patch.object(roots, "STATE_ROOT_AGREED", False):
            self.refused("state_root_not_agreed", roots.ensure_dir, suite)
            self.refused("state_root_not_agreed", roots.write_new, os.path.join(suite, "x"), b"x")
            self.refused("state_root_not_agreed", roots.write_new, os.path.join(self.home, "BETANGEL-DATA", "x"), b"x")
        self.assertEqual(mode(data_home), 0)

    def test_agreed_suite_root_is_writable_and_data_roots_are_not(self):
        data_home = roots.data_home(self.home)
        os.makedirs(data_home, mode=0o700)
        suite = roots.suite_root(self.home)
        with mock.patch.object(roots, "STATE_ROOT_AGREED", True):
            roots.ensure_dir(os.path.join(suite, "sessions"), home_dir=self.home)
            roots.write_new(os.path.join(suite, "x"), b"synthetic", home_dir=self.home)
            self.refused("write_outside_roots", roots.write_new, os.path.join(data_home, "historic", "x"), b"x")
            self.refused("write_outside_roots", roots.ensure_dir, os.path.join(data_home, "historic"))
        self.assertEqual(mode(suite), 0o700)
        self.assertEqual(mode(os.path.join(suite, "sessions")), 0o700)
        self.assertEqual(mode(os.path.join(suite, "x")), 0o600)
        self.assertEqual(os.listdir(data_home), ["suite.noindex"])

    def test_writer_refuses_a_root_that_a_link_puts_in_the_data_home(self):
        # Nuance's PR #2 review, item 1: with ~/.local/state linked to betangel-data/lab-state, write_new wrote
        # there. The writer helper now runs check_placement on the root of every path it writes.
        lab = os.path.join(roots.data_home(self.home), "lab-state")
        os.makedirs(lab, mode=0o700)
        rmtree(os.path.join(self.home, ".local", "state"))
        os.symlink(lab, os.path.join(self.home, ".local", "state"))
        for agreed in (False, True):
            with self.subTest(agreed=agreed), mock.patch.object(roots, "STATE_ROOT_AGREED", agreed):
                self.refused("root_overlaps_data_home", roots.write_new, os.path.join(self.state, "x"), b"x")
                self.refused("root_overlaps_data_home", roots.ensure_dir, os.path.join(self.state, "sub"))
                self.refused("root_overlaps_data_home", roots.check_placement, self.state)
        self.assertEqual(os.listdir(lab), [])

    def test_writer_refuses_a_suite_root_that_is_not_a_real_directory_in_place(self):
        historic = os.path.join(roots.data_home(self.home), "historic-pro")
        os.makedirs(historic, mode=0o700)
        suite = roots.suite_root(self.home)
        os.symlink(historic, suite)
        with mock.patch.object(roots, "STATE_ROOT_AGREED", True):
            self.refused("suite_root_misplaced", roots.write_new, os.path.join(suite, "x"), b"x")
            self.refused("suite_root_misplaced", roots.ensure_dir, os.path.join(suite, "tmp"))
            self.refused("suite_root_misplaced", roots.check_placement, os.path.join(suite, "tmp"))
            os.remove(suite)
            os.makedirs(suite)
            roots.check_placement(os.path.join(suite, "tmp"), home_dir=self.home)     # a real directory: fine
            os.symlink(historic, os.path.join(suite, "tmp"))                          # in it, but resolving out
            self.refused("suite_root_misplaced", roots.check_placement, os.path.join(suite, "tmp"))
        self.assertEqual(os.listdir(historic), [])

    def test_agreed_suite_root_must_pass_check_data_root(self):
        # DESIGN.md 3.7: the suite root lies outside the repository and every Git worktree
        # (upstream archive.check_data_root), checked before anything is created in it.
        data_home = roots.data_home(self.home)
        os.makedirs(os.path.join(data_home, ".git"), mode=0o700)
        suite = roots.suite_root(self.home)
        with mock.patch.object(roots, "STATE_ROOT_AGREED", True):
            with self.assertRaises(SuiteError) as caught:
                roots.ensure_dir(os.path.join(suite, "tmp"), home_dir=self.home)
        self.assertEqual((caught.exception.code, caught.exception.reason), ("suite_root_invalid", "inside_git_worktree"))
        self.assertEqual(os.listdir(data_home), [".git"])


class LiesInTests(unittest.TestCase):
    """roots.lies_in, which vendor and the guard use to keep writes out of the deploy clone (Nuance's PR #2 review,
    item 2): by text in any case, through links, and by identity at the nearest existing ancestor."""

    def test_lies_in(self):
        from tests.test_pin import firmlink_spelling
        home = make_home(self)
        clone = roots.research_clone(home)
        os.makedirs(os.path.join(clone, "sub"))
        outside = os.path.join(home, "outside")
        os.makedirs(outside)
        links = {"plain": os.path.join(clone, "sub"), "firm": firmlink_spelling(os.path.join(clone, "sub")),
                 "dangling_firm": os.path.join(firmlink_spelling(clone), "missing"), "elsewhere": outside}
        for name, target in links.items():
            os.symlink(target, os.path.join(home, name))

        def judged(*parts):
            return roots.lies_in(os.path.join(home, *parts), clone, "research_clone_on_path")

        for parts in (("betangel-research",), ("betangel-research", "sub", "missing", "deeper"), ("BetAngel-Research",),
                      ("betangel-reſearch", "sub"), ("plain",), ("plain", "missing", "deeper"), ("firm",),
                      ("firm", "missing", "deeper"), ("dangling_firm", "deeper")):
            self.assertTrue(judged(*parts), parts)
        for parts in (("outside",), ("elsewhere", "missing"), ("betangel-research-2",), ("missing", "deeper")):
            self.assertFalse(judged(*parts), parts)
        self.assertTrue(roots.lies_in(firmlink_spelling(os.path.join(clone, "sub")), clone, "research_clone_on_path"))
        rmtree(clone)                                   # no clone: only the text can place a path in it
        self.assertFalse(judged("firm"))
        self.assertTrue(judged("betangel-research", "sub"))


if __name__ == "__main__":
    unittest.main()
