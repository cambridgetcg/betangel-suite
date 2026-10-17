"""I-6 and I-13: the guard's path checks under other spellings and layouts, and its SQLite parts.

guard.py with roots.py decides where the suite's own code may write and which directories count as its roots;
pin._open_below decides which files the pin reads. These cases follow Nuance's PR #2 review, items 1 (write roots
that resolve into the data home), 8 (links on the way to a pinned file), 15 (SQLite temporary files), 16 (the
SQLite ATTACH limit) and 17 (metadata changes through read-only descriptors), and 6aeb1d5 (run/ protected like
realdata.lock). A write root or TMPDIR is spelt through the data-volume firmlink, /.vol, another letter case, a
symlinked parent at each level and ".." segments, each pointing into a synthetic ~/betangel-data in a temporary
HOME; hard links are tried where one applies (files: APFS has no directory hard links). Every check of the armed
hook runs in a fresh child, because a hook cannot be removed. Nothing here reads the real ~/betangel-data.

Lab-Claude's guard-paths review (round 4) wrote this file. Its tests of the five findings it reported are not repeated
here: they live, adapted to the fixes and widened to their variants, in tests/test_guard.py (RootPlacementTests:
test_a_placement_that_cannot_be_judged_is_refused, test_no_directory_between_a_root_and_tmpdir_moves_away,
test_a_tmpdir_with_a_link_below_its_root_is_refused, test_a_run_directory_or_lock_that_is_a_link_is_refused_at_arm)
and tests/test_pin.py (OpenBelowTests.test_the_tree_itself_spelt_with_a_final_slash_or_dot).
"""

import json
import os
import shutil
import textwrap
import unittest
from unittest import mock

from betangel_suite import pin, roots
from betangel_suite.errors import SuiteError
from tests import child_env, make_home, run_python

FIRMLINK = "/System/Volumes/Data"       # macOS: the data volume, under which /Users and /private are firmlinks

CHILD = """
import json, os, sys
from betangel_suite import guard, roots
from betangel_suite.errors import SuiteError
results = {}
def attempt(name, fn):
    try:
        fn()
        results[name] = "ok"
    except SuiteError as exc:
        results[name] = str(exc)
    except Exception as exc:
        results[name] = "other:" + type(exc).__name__
def write(path):
    with open(path, "w") as handle:
        handle.write("synthetic")
home = roots.home()
state = roots.state_dir()
data = roots.data_home()
suite = roots.suite_root()
"""


def child(case, home, body="", *, setup="", mode="engine", agreed=True, env=None):
    """Run setup, set roots.STATE_ROOT_AGREED, arm the guard in mode and, if it armed, run body, in a fresh child.

    Returns the results dict: results["arm"] is "ok" or arm()'s refusal code, then one entry per attempt.
    """
    code = (CHILD + setup + "\nroots.STATE_ROOT_AGREED = %r\n" % agreed
            + "attempt('arm', lambda: guard.arm(%r))\n" % mode
            + "if results['arm'] == 'ok':\n" + textwrap.indent(body.strip("\n") or "pass", "    ") + "\n"
            + "print(json.dumps(results))\n")
    result = run_python(code, home, env=env)
    case.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def tmp_env(home, tmp):
    return child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp)


def firmlink(path):
    """path through the data volume's own mount point, or None where this machine has no such spelling."""
    alias = FIRMLINK + os.path.realpath(path)
    try:
        return alias if os.path.samefile(alias, path) else None
    except OSError:
        return None


def volfs(path):
    """path as /.vol/<st_dev>/<st_ino>, or None."""
    info = os.stat(path)
    alias = "/.vol/%d/%d" % (info.st_dev, info.st_ino)
    try:
        return alias if os.path.samestat(os.stat(alias), info) else None
    except OSError:
        return None


def upper_data(path):
    """path with betangel-data in upper case, when the volume folds case (the lab's APFS does), or None."""
    alias = path.replace("betangel-data", "BETANGEL-DATA")
    try:
        return alias if alias != path and os.path.samefile(alias, path) else None
    except OSError:
        return None


def listing(path):
    found = []
    for directory, dirs, files in os.walk(path):
        found += [os.path.relpath(os.path.join(directory, name), path) for name in dirs + files]
    return sorted(found)


class Case(unittest.TestCase):
    maxDiff = None


def data_dir(home, name):
    path = os.path.join(roots.data_home(home), name)
    os.makedirs(path, mode=0o700)
    return path


class RootLinkLevelTests(Case):
    """A link at each level of the state root's path (~/.local, ~/.local/state, the root itself) into the data home,
    its target spelt six ways: arm() and roots.check_placement refuse every one (root_overlaps_data_home), and a
    link at the same levels to a directory outside the data home is allowed (DESIGN.md 3.7, "Placement")."""

    LEVELS = {"local": (".local",), "state": (".local", "state"), "root": roots.STATE_DIR_PARTS}

    def targets(self, home, link, target):
        """{spelling: link text} for a link at link to the existing directory target."""
        os.makedirs(os.path.join(home, "outside"), exist_ok=True)
        found = {"plain": target, "firmlink": firmlink(target), "vol": volfs(target), "case": upper_data(target),
                 "relative": os.path.relpath(target, os.path.dirname(link)),
                 "dotdot": os.path.join(home, "outside", os.pardir, os.path.relpath(target, home))}
        return {name: spelling for name, spelling in found.items() if spelling is not None}

    def test_a_link_at_each_level_into_the_data_home_is_refused(self):
        for level, parts in self.LEVELS.items():
            home = make_home(self)
            link = os.path.join(home, *parts)
            target = data_dir(home, "lab-" + level)
            os.rmdir(target)
            os.rename(link, target)             # the root and its tmp/ now really live in the data home
            before = listing(target)
            for name, spelling in self.targets(home, link, target).items():
                os.symlink(spelling, link)
                try:
                    with self.subTest(level=level, spelling=name):
                        # The layout works (a link to a /.vol path does not resolve here, but is refused all the same).
                        self.assertEqual(os.path.isdir(roots.tmp_dir("test", home)), name != "vol")
                        for agreed in (False, True):
                            with mock.patch.object(roots, "STATE_ROOT_AGREED", agreed):
                                for path in (roots.state_dir(home), roots.tmp_dir("test", home)):
                                    with self.assertRaises(SuiteError) as caught:
                                        roots.check_placement(path, home)
                                    self.assertEqual(caught.exception.code, "root_overlaps_data_home", (agreed, path))
                        results = child(self, home, "write(os.path.join(state, 'x'))\n")
                        self.assertEqual(results, {"arm": "root_overlaps_data_home"})
                        self.assertEqual(listing(target), before)
                finally:
                    os.remove(link)

    def test_a_link_at_each_level_outside_the_data_home_is_allowed(self):
        for level, parts in self.LEVELS.items():
            home = make_home(self)
            data_dir(home, "historic-pro")
            link = os.path.join(home, *parts)
            target = os.path.join(home, "elsewhere", level)
            os.makedirs(os.path.dirname(target))
            os.rename(link, target)
            os.symlink(target, link)
            with self.subTest(level=level):
                roots.check_placement(roots.state_dir(home), home)
                results = child(self, home, "attempt('write_state', lambda: write(os.path.join(state, 'x')))\n",
                                mode="test")
                self.assertEqual(results, {"arm": "ok", "write_state": "ok"})


class HomeSpellingTests(Case):
    """HOME given through the firmlink, in another case, with a final or doubled "/" or with a ".." segment: the
    roots follow HOME's normalised text (roots.home), so arm() and writes behave as with the plain HOME, and a
    state root that a link puts in the data home is still refused (root_overlaps_data_home)."""

    def spellings(self, home):
        found = {"firmlink": firmlink(home), "trailing_slash": home + "/",
                 "double_slash": os.path.dirname(home) + "//" + os.path.basename(home),
                 "dotdot": os.path.join(home, ".local", os.pardir)}
        upper = os.path.join(os.path.dirname(home), os.path.basename(home).upper())
        try:
            if os.path.samefile(upper, home):
                found["case"] = upper
        except OSError:
            pass                                            # a volume that does not fold case
        return {name: spelling for name, spelling in found.items() if spelling is not None}

    def test_home_spellings(self):
        for name in ("firmlink", "case", "trailing_slash", "double_slash", "dotdot"):
            home = make_home(self)
            historic = data_dir(home, "historic-pro")
            os.makedirs(roots.suite_root(home), mode=0o700)
            spelled = self.spellings(home).get(name)
            if spelled is None:
                continue                                    # no such spelling on this machine
            env = child_env(spelled)
            body = """
attempt("write_state", lambda: write(os.path.join(state, "x")))
attempt("write_suite", lambda: write(os.path.join(suite, "x")))
attempt("write_data_spelled", lambda: write(os.path.join(data, "historic-pro", "x")))
attempt("write_data_plain", lambda: write(os.path.join(%r, "x")))
""" % historic
            with self.subTest(home=name, agreed=True):
                results = child(self, home, body, env=env)
                self.assertEqual(results, {"arm": "ok", "write_state": "ok", "write_suite": "ok",
                                           "write_data_spelled": "write_outside_roots",
                                           "write_data_plain": "write_outside_roots"})
            with self.subTest(home=name, agreed=False):
                results = child(self, home, body, env=env, agreed=False)
                self.assertEqual((results["arm"], results["write_state"], results["write_suite"],
                                  results["write_data_spelled"]),
                                 ("ok", "ok", "state_root_not_agreed", "state_root_not_agreed"))
                # Judged on the text: a plain spelling of a firmlink HOME's data home is not its text, but it is
                # still refused, as a write outside the roots.
                self.assertIn(results["write_data_plain"], ("state_root_not_agreed", "write_outside_roots"))
            self.assertEqual(os.listdir(historic), [])
            # ~/.local/state linked into the data home, and the data home linked into a root.
            lab = data_dir(home, "lab-state")
            os.rename(os.path.join(home, ".local", "state"), os.path.join(lab, "moved"))
            os.symlink(os.path.join(lab, "moved"), os.path.join(home, ".local", "state"))
            for agreed, mode in ((True, "engine"), (False, "engine"), (True, "test")):
                with self.subTest(home=name, agreed=agreed, mode=mode, layout="state_in_data"):
                    results = child(self, home, "write(os.path.join(state, 'x'))\n", env=env, agreed=agreed,
                                    mode=mode)
                    self.assertEqual(results, {"arm": "root_overlaps_data_home"})
            os.remove(os.path.join(home, ".local", "state"))
            os.rename(os.path.join(lab, "moved"), os.path.join(home, ".local", "state"))
            inside = os.path.join(roots.state_dir(home), "data")
            os.rename(roots.data_home(home), inside)
            os.symlink(inside, roots.data_home(home))
            with self.subTest(home=name, layout="data_in_state"):
                self.assertEqual(child(self, home, env=env), {"arm": "root_overlaps_data_home"})
            self.assertEqual(os.listdir(os.path.join(inside, "historic-pro")), [])


class TmpdirSpellingTests(Case):
    """TMPDIR (and SQLITE_TMPDIR) must be the same absolute text with no "." or ".." component, lie in a write root
    as text and, links resolved, in that root's real path (guard.py I-2): otherwise tmpdir_mismatch."""

    def test_tmpdir_spellings_into_the_data_home(self):
        home = make_home(self)
        historic = data_dir(home, "historic-pro")
        state = roots.state_dir(home)
        tmp = roots.tmp_dir("test", home)
        os.makedirs(os.path.join(home, "outside"))
        # Links in the state root into the data home, the target spelt four ways.
        links = {"plain": historic, "firmlink": firmlink(historic), "case": upper_data(historic),
                 "relative": os.path.relpath(historic, state)}
        cases = {}
        for name, target in links.items():
            if target is not None:
                os.symlink(target, os.path.join(state, "to-" + name))
                cases["link_" + name] = os.path.join(state, "to-" + name)
                cases["under_link_" + name] = os.path.join(state, "to-" + name, "tmp")    # a symlinked parent
        cases.update({
            "firmlink": firmlink(tmp), "vol": volfs(tmp),
            "dotdot_into_data": os.path.join(state, os.pardir, os.pardir, os.pardir, "betangel-data", "historic-pro"),
            "dotdot_back": os.path.join(tmp, os.pardir, "tmp"),
            "data_home_case": os.path.join(home, "BETANGEL-DATA", "suite.noindex", "tmp"),
        })
        for name, spelled in cases.items():
            if spelled is None:
                continue
            for mode in ("test", "engine") if name in ("link_plain", "firmlink", "data_home_case") else ("test",):
                with self.subTest(tmpdir=name, mode=mode):
                    results = child(self, home, "write(os.path.join(os.environ['TMPDIR'], 'x'))\n", mode=mode,
                                    env=tmp_env(home, spelled))
                    self.assertEqual(results, {"arm": "tmpdir_mismatch"})
        self.assertEqual(os.listdir(historic), [])

    def test_sqlite_tmpdir_spelt_otherwise_than_tmpdir(self):
        home = make_home(self)
        tmp = roots.tmp_dir("test", home)
        other = firmlink(tmp)
        if other is None:
            self.skipTest("no firmlink spelling on this machine")
        env = child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=other)
        self.assertEqual(child(self, home, mode="test", env=env), {"arm": "tmpdir_mismatch"})

    def test_tmpdir_in_another_case_is_the_same_directory(self):
        # Allowed: the text lies in the state root and resolves in its real path (a case-folding volume finds the
        # same directory). The hook's slots are casefolded, so the directory still cannot be moved away.
        home = make_home(self)
        tmp = roots.tmp_dir("test", home)
        upper = os.path.join(os.path.dirname(tmp), "TMP")
        if not os.path.samefile(upper, tmp):
            self.skipTest("the volume does not fold case")
        results = child(self, home, """
attempt("write_tmp", lambda: write(os.path.join(os.environ["TMPDIR"], "x")))
attempt("rename_tmp", lambda: os.rename(%r, os.path.join(state, "moved")))
attempt("rename_tmp_as_spelt", lambda: os.rename(os.environ["TMPDIR"], os.path.join(state, "moved")))
""" % tmp, mode="test", env=tmp_env(home, upper))
        self.assertEqual(results, {"arm": "ok", "write_tmp": "ok", "rename_tmp": "root_replace_refused",
                                   "rename_tmp_as_spelt": "root_replace_refused"})

    def test_engine_tmpdir_in_the_suite_root(self):
        home = make_home(self)
        historic = data_dir(home, "historic-pro")
        suite = roots.suite_root(home)
        os.makedirs(suite, mode=0o700)
        tmp = roots.tmp_dir("serve", home)
        self.assertEqual(child(self, home, env=tmp_env(home, tmp)), {"arm": "ok"})        # missing: made later
        os.symlink(historic, tmp)
        self.assertEqual(child(self, home, env=tmp_env(home, tmp)), {"arm": "tmpdir_mismatch"})
        os.remove(tmp)
        os.symlink(os.path.relpath(historic, suite), tmp)
        self.assertEqual(child(self, home, env=tmp_env(home, tmp)), {"arm": "tmpdir_mismatch"})
        self.assertEqual(os.listdir(historic), [])


class SuiteRootPlacementTests(Case):
    """The engine's suite root must be a real directory, or missing, at exactly realpath(data home)/suite.noindex
    (suite_root_misplaced); a sibling or a nested path is not it (DESIGN.md 3.7)."""

    def test_check_placement_by_text(self):
        home = make_home(self)
        data = roots.data_home(home)
        os.makedirs(os.path.join(data, "historic-pro"), mode=0o700)
        with mock.patch.object(roots, "STATE_ROOT_AGREED", True):
            for parts in (("suite.noindex",), ("suite.noindex", "tmp"), ("suite.noindex", "tmp", "deeper")):
                roots.check_placement(os.path.join(data, *parts), home)          # missing: fine
            os.makedirs(os.path.join(data, "suite.noindex", "tmp"))
            roots.check_placement(os.path.join(data, "suite.noindex", "tmp"), home)
            for parts in ((), ("suite.noindex2",), ("suite.noindex.old",), ("SUITE.NOINDEX",), ("historic-pro",),
                          ("historic-pro", "suite.noindex"), ("lab-state",)):
                with self.subTest(parts=parts):
                    with self.assertRaises(SuiteError) as caught:
                        roots.check_placement(os.path.join(data, *parts), home)
                    self.assertEqual(caught.exception.code, "root_overlaps_data_home", parts)

    def test_suite_root_layouts(self):
        home = make_home(self)
        data = roots.data_home(home)
        historic = data_dir(home, "historic-pro")
        suite = roots.suite_root(home)
        sibling = data_dir(home, "suite.noindex.real")
        nested = os.path.join(historic, "suite.noindex")
        os.makedirs(nested)
        layouts = {
            "sibling": lambda: os.symlink(sibling, suite),
            "sibling_relative": lambda: os.symlink("suite.noindex.real", suite),
            "nested": lambda: os.symlink(nested, suite),
            "nested_dotdot": lambda: os.symlink(os.path.join(sibling, os.pardir, "historic-pro", "suite.noindex"),
                                                suite),
            "self_through_firmlink": lambda: os.symlink(FIRMLINK + os.path.realpath(data) + "/suite.noindex", suite),
        }
        writes = "attempt('write_suite', lambda: write(os.path.join(suite, 'x')))\n"
        for name, make in layouts.items():
            make()
            with self.subTest(layout=name):
                self.assertEqual(child(self, home, writes), {"arm": "suite_root_misplaced"})
            os.remove(suite)
        self.assertEqual(child(self, home, writes), {"arm": "ok", "write_suite": "other:FileNotFoundError"})
        os.mkdir(os.path.join(data, "Suite.NoIndex"), 0o700)           # the same name to a case-folding volume
        if os.path.isdir(suite):
            with self.subTest(layout="other_case_on_disk"):
                self.assertEqual(child(self, home, writes), {"arm": "ok", "write_suite": "ok"})
        for path in (sibling, nested, historic):
            self.assertEqual(os.listdir(path), [] if path != historic else ["suite.noindex"])

    def test_data_home_behind_a_link_with_a_nested_suite_root(self):
        home = make_home(self)
        external = os.path.join(home, "external")
        nested = os.path.join(external, "historic-pro", "suite.noindex")
        os.makedirs(nested)
        os.symlink(external, roots.data_home(home))
        os.symlink(nested, os.path.join(external, "suite.noindex"))
        self.assertEqual(child(self, home), {"arm": "suite_root_misplaced"})
        os.remove(os.path.join(external, "suite.noindex"))
        os.mkdir(os.path.join(external, "suite.noindex"))
        self.assertEqual(child(self, home), {"arm": "ok"})
        self.assertEqual(os.listdir(nested), [])


class RenameAfterArmTests(Case):
    """After arm(): a root's parent lies outside the roots, so no spelling may rename it (write_outside_roots); a
    root, TMPDIR and run/ may not be moved away or have a name put in their place (root_replace_refused,
    run_lock_protected), however they are spelt."""

    SETUP = """
os.makedirs(roots.run_dir(), exist_ok=True)
open(os.path.join(roots.run_dir(), "realdata.lock"), "a").close()
os.makedirs(os.path.join(state, "sub"), exist_ok=True)
os.makedirs(os.path.join(home, ".local", "state", "sibling"), exist_ok=True)
os.symlink(os.path.join(home, ".local", "state", "sibling"), os.path.join(state, "to-sibling"))
os.symlink(os.path.join(state, "sub"), os.path.join(state, "to-sub"))
os.symlink(state, os.path.join(state, "to-self"))
"""

    BODY = """
def rename_with_dir_fd(directory, name):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.rename(name, name + "-moved", src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        os.close(fd)
local = os.path.join(home, ".local")
attempt("state_parent", lambda: os.rename(os.path.join(local, "state"), os.path.join(local, "state-moved")))
attempt("state_grandparent", lambda: os.rename(local, local + "-moved"))
attempt("home", lambda: os.rename(home, home + "-moved"))
attempt("data_home", lambda: os.rename(data, data + "-moved"))
attempt("state_parent_dotdot", lambda: os.rename(state + "/..", os.path.join(local, "state-moved")))
attempt("state_parent_through_link", lambda: os.rename(os.path.join(state, "to-sibling", ".."),
                                                       os.path.join(local, "state-moved")))
attempt("state_parent_dir_fd", lambda: rename_with_dir_fd(local, "state"))
attempt("onto_state_parent_through_link", lambda: os.rename(os.path.join(state, "sub"),
                                                            os.path.join(state, "to-sibling", "..")))
attempt("suite_parent_dotdot", lambda: os.rename(suite + "/..", data + "-moved"))
attempt("state_root_through_link", lambda: os.rename(os.path.join(state, "to-sub", ".."), state + "-moved"))
attempt("run_dir_fd", lambda: rename_with_dir_fd(state, "run"))
attempt("run_through_link", lambda: os.rename(os.path.join(state, "to-self", "run"),
                                              os.path.join(state, "to-self", "run-moved")))
parent = os.path.dirname(os.environ["TMPDIR"])     # the suite root (engine, agreed) or the state root
moved = os.path.join(state, "moved") if parent != state else state + "-moved"
attempt("tmpdir_parent", lambda: os.rename(parent, moved))
results["in_place"] = all(os.path.isdir(path) and not os.path.islink(path)
                          for path in (state, suite, roots.run_dir(), os.environ["TMPDIR"]))
"""

    def test_roots_and_their_parents_stay_in_place(self):
        refused = {"state_parent": "write_outside_roots", "state_grandparent": "write_outside_roots",
                   "home": "write_outside_roots", "data_home": "write_outside_roots",
                   "state_parent_dotdot": "write_outside_roots", "state_parent_through_link": "write_outside_roots",
                   "state_parent_dir_fd": "write_outside_roots", "suite_parent_dotdot": "write_outside_roots",
                   "onto_state_parent_through_link": "write_outside_roots",
                   "state_root_through_link": "root_replace_refused", "run_dir_fd": "run_lock_protected",
                   "run_through_link": "run_lock_protected", "tmpdir_parent": "root_replace_refused"}
        for agreed, mode in ((True, "engine"), (False, "engine"), (True, "test")):
            home = make_home(self)
            data_dir(home, "historic-pro")
            os.makedirs(roots.suite_root(home))
            tmp = roots.tmp_dir("serve" if agreed and mode == "engine" else "test", home)
            os.makedirs(tmp, exist_ok=True)
            with self.subTest(agreed=agreed, mode=mode):
                results = child(self, home, self.BODY, setup=self.SETUP, agreed=agreed, mode=mode,
                                env=tmp_env(home, tmp))
                expected = dict(refused, arm="ok", in_place=True)
                if not agreed:
                    expected.update(data_home="state_root_not_agreed", suite_parent_dotdot="state_root_not_agreed")
                self.assertEqual(results, expected)

    def test_an_empty_tmpdir_may_be_removed_but_not_replaced(self):
        # Allowed: os.rmdir is not among the calls the slots refuse (guard.py I-6; DESIGN.md 3.6 covers a TMPDIR
        # that is gone with temp_store=MEMORY). A link or a renamed directory in its place is refused, and a new
        # real directory may be made there.
        home = make_home(self)
        os.makedirs(os.path.join(home, "outside"))
        results = child(self, home, """
tmp = os.environ["TMPDIR"]
os.mkdir(os.path.join(state, "spare"))
attempt("rmdir_tmpdir", lambda: os.rmdir(tmp))
attempt("link_in_place", lambda: os.symlink(os.path.join(home, "outside"), tmp))
attempt("rename_in_place", lambda: os.rename(os.path.join(state, "spare"), tmp))
attempt("mkdir_again", lambda: os.mkdir(tmp, 0o700))
results["tmpdir_is_dir"] = os.path.isdir(tmp) and not os.path.islink(tmp)
""", mode="test")
        self.assertEqual(results, {"arm": "ok", "rmdir_tmpdir": "ok", "link_in_place": "root_replace_refused",
                                   "rename_in_place": "root_replace_refused", "mkdir_again": "ok",
                                   "tmpdir_is_dir": True})


class HardLinkTests(Case):
    """Hard links apply to files only (APFS has no directory hard links): no link may alias a data-home file inside
    the roots or put a name from the roots in the data home. A hard link made before arm() is a documented limit
    (guard.py: "a file descriptor or hard link made before a check")."""

    def test_hard_links_between_the_roots_and_the_data_home(self):
        for agreed in (False, True):
            home = make_home(self)
            historic = data_dir(home, "historic-pro")
            os.makedirs(roots.suite_root(home))
            with open(os.path.join(historic, "file"), "w") as handle:
                handle.write("synthetic")
            os.link(os.path.join(historic, "file"), os.path.join(roots.state_dir(home), "made-before"))
            results = child(self, home, """
historic = os.path.join(data, "historic-pro")
write(os.path.join(state, "mine"))
attempt("data_into_state", lambda: os.link(os.path.join(historic, "file"), os.path.join(state, "alias")))
attempt("data_into_suite", lambda: os.link(os.path.join(historic, "file"), os.path.join(suite, "alias")))
attempt("state_into_data", lambda: os.link(os.path.join(state, "mine"), os.path.join(historic, "alias")))
attempt("dotdot_into_state", lambda: os.link(os.path.join(state, "..", "..", "..", "betangel-data", "historic-pro",
                                                          "file"), os.path.join(state, "alias2")))
attempt("directory", lambda: os.link(historic, os.path.join(state, "dir-alias")))
attempt("write_through_link_made_before", lambda: open(os.path.join(state, "made-before"), "a").close())
""", agreed=agreed)
            with self.subTest(agreed=agreed):
                data_code = "write_outside_roots" if agreed else "state_root_not_agreed"
                self.assertEqual(results, {"arm": "ok", "data_into_state": data_code,
                                           "data_into_suite": data_code, "state_into_data": data_code,
                                           "dotdot_into_state": data_code, "directory": data_code,
                                           "write_through_link_made_before": "ok"})
                self.assertEqual(sorted(os.listdir(historic)), ["file"])
                self.assertEqual(os.stat(os.path.join(historic, "file")).st_nlink, 2)


class DescriptorPathTests(Case):
    """chmod, chown, utime and truncate given a read-only descriptor of a file outside the roots are judged by the
    file's F_GETPATH path, however the descriptor was opened (Nuance's PR #2 review, item 17)."""

    SETUP = """
outside = os.path.join(home, "outside")
os.makedirs(outside)
for directory in (outside, os.path.join(data, "historic-pro")):
    with open(os.path.join(directory, "file"), "w") as handle:
        handle.write("synthetic")
    os.chmod(os.path.join(directory, "file"), 0o600)
    os.chmod(directory, 0o700)
os.symlink(outside, os.path.join(state, "to-outside"))
before_arm = os.open(os.path.join(outside, "file"), os.O_RDONLY)
"""

    BODY = """
import stat
def opened_with_dir_fd():
    directory = os.open(outside, os.O_RDONLY)
    try:
        return os.open("file", os.O_RDONLY, dir_fd=directory)
    finally:
        os.close(directory)
firm = "/System/Volumes/Data" + os.path.realpath(os.path.join(outside, "file"))
descriptors = {
    "outside_file": os.open(os.path.join(outside, "file"), os.O_RDONLY),
    "outside_dir": os.open(outside, os.O_RDONLY),
    "data_file": os.open(os.path.join(data, "historic-pro", "file"), os.O_RDONLY),
    "data_dir": os.open(os.path.join(data, "historic-pro"), os.O_RDONLY),
    "through_link_in_state": os.open(os.path.join(state, "to-outside", "file"), os.O_RDONLY),
    "dir_fd": opened_with_dir_fd(),
    "before_arm": before_arm,
}
if os.path.exists(firm):
    descriptors["firmlink"] = os.open(firm, os.O_RDONLY)
calls = {
    "chmod": lambda fd: os.chmod(fd, 0o640), "fchmod": lambda fd: os.fchmod(fd, 0o640),
    "chown": lambda fd: os.chown(fd, os.getuid(), os.getgid()), "fchown": lambda fd: os.fchown(fd, -1, -1),
    "utime": lambda fd: os.utime(fd), "utime_times": lambda fd: os.utime(fd, (0, 0)),
    "truncate": lambda fd: os.truncate(fd, 0), "ftruncate": lambda fd: os.ftruncate(fd, 0),
}
for label, fd in descriptors.items():
    for name, call in calls.items():
        attempt(label + ":" + name, lambda: call(fd))
inside = os.open(os.path.join(state, "inside"), os.O_RDWR | os.O_CREAT, 0o600)
for name, call in calls.items():
    attempt("inside:" + name, lambda: call(inside))
def mode_of(path):
    try:
        return oct(stat.S_IMODE(os.stat(path).st_mode))
    except OSError:
        return "unreadable"         # a directory above it lost its search bit
results["modes"] = sorted({mode_of(path) for path in (
    os.path.join(outside, "file"), os.path.join(data, "historic-pro", "file"), outside,
    os.path.join(data, "historic-pro"))})
"""

    def test_descriptors_of_files_outside_the_roots(self):
        for agreed in (False, True):
            home = make_home(self)
            data_dir(home, "historic-pro")
            results = child(self, home, self.BODY, setup=self.SETUP, agreed=agreed)
            with self.subTest(agreed=agreed):
                self.assertEqual(results.pop("arm"), "ok")
                modes = results.pop("modes")
                data_code = "write_outside_roots" if agreed else "state_root_not_agreed"
                for name, value in results.items():
                    label = name.partition(":")[0]
                    if label == "inside":
                        expected = "ok"
                    elif label.startswith("data_"):
                        expected = data_code
                    else:
                        expected = "write_outside_roots"
                    self.assertEqual(value, expected, name)
                self.assertGreaterEqual(len([name for name in results if not name.startswith("inside:")]), 56)
                self.assertEqual(modes, ["0o600", "0o700"])
            for path in (os.path.join(home, "outside", "file"),
                         os.path.join(roots.data_home(home), "historic-pro", "file")):
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), "synthetic")


class SqlitePathTests(Case):
    """The sqlite3.connect wrapper: temp_store=MEMORY and SQLITE_LIMIT_ATTACHED=0 on every new connection (items 15
    and 16), whatever an earlier connection did; backup() and deserialize() open no file outside the roots."""

    SETUP = """
outside = os.path.join(home, "outside")
os.makedirs(outside, exist_ok=True)
"""

    TEMP_FILES = """
import fcntl, sqlite3, sqlite3.dbapi2, threading
def temp_files():
    found = set()
    for name in os.listdir("/dev/fd"):
        try:
            path = fcntl.fcntl(int(name), fcntl.F_GETPATH, bytes(1024)).split(b"\\0", 1)[0]
        except (OSError, ValueError):
            continue
        if b"etilqs" in os.path.basename(path):
            found.add((name, os.fsdecode(path)))
    return found
def spill(connection, table):
    # The temporary files SQLite opens for this connection's spill: another connection's stay open beside them.
    before = temp_files()
    connection.execute("CREATE TEMP TABLE %s (x TEXT)" % table)
    connection.execute("PRAGMA temp.cache_size = 2")
    connection.executemany("INSERT INTO %s VALUES (?)" % table,
                           (("synthetic-%05d" % i + "-" * 400,) for i in range(3000)))
    connection.execute("SELECT x FROM %s ORDER BY x DESC" % table).fetchall()
    return sorted(path for _fd, path in temp_files() - before)
"""

    def test_temp_store_after_a_pragma_and_on_a_second_connection(self):
        home = make_home(self)
        results = child(self, home, self.TEMP_FILES + """
first = sqlite3.connect(os.path.join(state, "first.sqlite"), isolation_level=None)
results["first"] = first.execute("PRAGMA temp_store").fetchone()[0]
first.execute("PRAGMA temp_store = FILE")                    # the documented limit: a PRAGMA sets it back
results["first_after_pragma"] = first.execute("PRAGMA temp_store").fetchone()[0]
spilled = spill(first, "a")
results["first_spills"] = bool(spilled)
results["first_spills_in_tmpdir"] = all(os.path.dirname(path) == os.path.realpath(os.environ["TMPDIR"])
                                        for path in spilled)
second = sqlite3.connect(os.path.join(state, "second.sqlite"), isolation_level=None)
results["second"] = second.execute("PRAGMA temp_store").fetchone()[0]
second.execute("PRAGMA temp_store_directory = %r" % outside)  # no effect while temp_store is MEMORY
results["second_spills"] = spill(second, "b")
first.close()
results["second_spills_after_first_closed"] = spill(second, "c")
results["dbapi2"] = sqlite3.dbapi2.connect(":memory:").execute("PRAGMA temp_store").fetchone()[0]
box = []
worker = threading.Thread(target=lambda: box.append(
    sqlite3.connect(os.path.join(state, "third.sqlite")).execute("PRAGMA temp_store").fetchone()[0]))
worker.start()
worker.join()
results["other_thread"] = box
second.close()
""", setup=self.SETUP, mode="test")
        self.assertEqual(results, {"arm": "ok", "first": 2, "first_after_pragma": 1, "first_spills": True,
                                   "first_spills_in_tmpdir": True, "second": 2, "second_spills": [],
                                   "second_spills_after_first_closed": [], "dbapi2": 2, "other_thread": [2]})
        self.assertEqual(os.listdir(os.path.join(home, "outside")), [])

    def test_attach_limit_on_new_connections(self):
        home = make_home(self)
        results = child(self, home, """
import sqlite3
limit = sqlite3.SQLITE_LIMIT_ATTACHED
fresh = sqlite3.connect(os.path.join(state, "fresh.sqlite"))
results["fresh"] = fresh.getlimit(limit)
attempt("setlimit_fresh", lambda: fresh.setlimit(limit, 10))
attempt("setlimit_by_number", lambda: fresh.setlimit(7, 10))
attempt("setlimit_keywords", lambda: fresh.setlimit(category=limit, value=10))
attempt("attach", lambda: fresh.execute("ATTACH DATABASE ? AS other", (os.path.join(outside, "a.db"),)))
attempt("vacuum_into", lambda: fresh.execute("VACUUM INTO ?", (os.path.join(outside, "v.db"),)))
attempt("plain_vacuum", lambda: fresh.execute("VACUUM"))
# The documented limit: sqlite3.Connection.setlimit called on a connection directly raises it there only.
attempt("base_setlimit", lambda: sqlite3.Connection.setlimit(fresh, limit, 10))
results["raised"] = fresh.getlimit(limit)
later = sqlite3.connect(os.path.join(state, "later.sqlite"))
results["later"] = later.getlimit(limit)
attempt("attach_later", lambda: later.execute("ATTACH DATABASE ? AS other", (os.path.join(outside, "b.db"),)))
results["memory"] = sqlite3.connect(":memory:").getlimit(limit)
fresh.close()
later.close()
""", setup=self.SETUP)
        self.assertEqual(results, {"arm": "ok", "fresh": 0, "setlimit_fresh": "sqlite_limit_refused",
                                   "setlimit_by_number": "sqlite_limit_refused",
                                   "setlimit_keywords": "sqlite_limit_refused", "attach": "other:OperationalError",
                                   "vacuum_into": "other:OperationalError",
                                   # ATTACHED=0 also stops a plain VACUUM, which attaches a temporary database.
                                   "plain_vacuum": "other:OperationalError", "base_setlimit": "ok", "raised": 10,
                                   "later": 0, "attach_later": "other:OperationalError", "memory": 0})
        self.assertEqual(os.listdir(os.path.join(home, "outside")), [])

    def test_backup_into_a_file_outside_the_roots(self):
        for agreed in (False, True):
            home = make_home(self)
            historic = data_dir(home, "historic-pro")
            os.makedirs(roots.suite_root(home))
            results = child(self, home, """
import sqlite3
source = sqlite3.connect(os.path.join(state, "source.sqlite"))
source.execute("CREATE TABLE t (x TEXT)")
source.execute("INSERT INTO t VALUES ('synthetic')")
source.commit()
os.symlink(os.path.join(outside, "linked.sqlite"), os.path.join(state, "to-outside.sqlite"))
def backup_into(path):
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        target.close()
attempt("outside", lambda: backup_into(os.path.join(outside, "copy.sqlite")))
attempt("data_root", lambda: backup_into(os.path.join(data, "historic-pro", "copy.sqlite")))
attempt("link_in_state", lambda: backup_into(os.path.join(state, "to-outside.sqlite")))
attempt("dotdot", lambda: backup_into(os.path.join(state, "..", "..", "..", "outside", "dotdot.sqlite")))
attempt("memory", lambda: backup_into(":memory:"))
attempt("state", lambda: backup_into(os.path.join(state, "copy.sqlite")))
attempt("suite", lambda: backup_into(os.path.join(suite, "copy.sqlite")))
source.close()
""", setup=self.SETUP, agreed=agreed)
            with self.subTest(agreed=agreed):
                self.assertEqual(results, {"arm": "ok", "outside": "write_outside_roots",
                                           "data_root": "write_outside_roots" if agreed else "state_root_not_agreed",
                                           "link_in_state": "write_outside_roots", "dotdot": "write_outside_roots",
                                           "memory": "ok", "state": "ok",
                                           "suite": "ok" if agreed else "state_root_not_agreed"})
                self.assertEqual(os.listdir(os.path.join(home, "outside")), [])
                self.assertEqual(os.listdir(historic), [])

    def test_deserialize_keeps_the_limits_and_writes_nothing_outside(self):
        home = make_home(self)
        results = child(self, home, self.TEMP_FILES + """
source = sqlite3.connect(":memory:")
source.execute("CREATE TABLE t (x TEXT)")
source.execute("INSERT INTO t VALUES ('synthetic')")
source.commit()
image = source.serialize()
for name, database in (("memory", ":memory:"), ("file", os.path.join(state, "target.sqlite"))):
    target = sqlite3.connect(database, isolation_level=None)
    attempt(name + ":deserialize", lambda: target.deserialize(image))
    results[name + ":rows"] = target.execute("SELECT count(*) FROM t").fetchone()[0]
    results[name + ":limit"] = target.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED)
    results[name + ":temp_store"] = target.execute("PRAGMA temp_store").fetchone()[0]
    attempt(name + ":attach", lambda: target.execute("ATTACH DATABASE ? AS o", (os.path.join(outside, "a.db"),)))
    attempt(name + ":vacuum_into", lambda: target.execute("VACUUM INTO ?", (os.path.join(outside, "v.db"),)))
    results[name + ":spills"] = spill(target, "s")
    target.close()
""", setup=self.SETUP)
        expected = {"arm": "ok"}
        for name in ("memory", "file"):
            expected.update({name + ":deserialize": "ok", name + ":rows": 1, name + ":limit": 0,
                             name + ":temp_store": 2, name + ":attach": "other:OperationalError",
                             name + ":vacuum_into": "other:OperationalError", name + ":spills": []})
        self.assertEqual(results, expected)
        self.assertEqual(os.listdir(os.path.join(home, "outside")), [])


class OpenBelowTests(Case):
    """pin._open_below and read_below: no symlink at any component of relpath, tree itself not a link, its
    ancestors free to be links (Nuance's PR #2 review, item 8); with O_NOFOLLOW_ANY and with the component walk."""

    def setUp(self):
        self.home = make_home(self)
        self.base = os.path.join(self.home, "trees")
        self.tree = os.path.join(self.base, "tree")
        self.elsewhere = os.path.join(self.base, "elsewhere")
        os.makedirs(os.path.join(self.tree, "a", "b", "c"))
        with open(os.path.join(self.tree, "a", "b", "c", "f.txt"), "w", encoding="utf-8") as handle:
            handle.write("synthetic")
        shutil.copytree(self.tree, self.elsewhere)

    def opens(self, tree, relpath="a/b/c/f.txt"):
        try:
            fd = pin._open_below(tree, relpath)
        except OSError:
            return False
        os.close(fd)
        return True

    def both_ways(self):
        for nofollow_any in (pin._NOFOLLOW_ANY, 0):
            with mock.patch.object(pin, "_NOFOLLOW_ANY", nofollow_any):
                yield nofollow_any

    def test_a_symlink_at_each_level_is_refused(self):
        levels = ("a", "a/b", "a/b/c", "a/b/c/f.txt")
        for nofollow_any in self.both_ways():
            self.assertTrue(self.opens(self.tree))
            self.assertEqual(pin.read_below(self.tree, "a/b/c/f.txt"), b"synthetic")
            for level in levels:
                path = os.path.join(self.tree, *level.split("/"))
                for kind, target in (("elsewhere", os.path.join(self.elsewhere, *level.split("/"))),
                                     ("inside_tree", os.path.join(self.tree, "moved")), ("dangling", "missing"),
                                     ("relative", os.path.join("..", "moved") if "/" in level else "moved")):
                    with self.subTest(nofollow_any=bool(nofollow_any), level=level, kind=kind):
                        os.rename(path, os.path.join(self.tree, "moved"))
                        os.symlink(target, path)
                        try:
                            self.assertFalse(self.opens(self.tree))
                            self.assertIsNone(pin.read_below(self.tree, "a/b/c/f.txt"))
                        finally:
                            os.remove(path)
                            os.rename(os.path.join(self.tree, "moved"), path)
            self.assertEqual(pin.read_below(self.tree, "a/b/c/f.txt"), b"synthetic")

    def test_the_tree_and_its_ancestors(self):
        tree_link = os.path.join(self.base, "tree-link")
        os.symlink(self.tree, tree_link)
        ancestor_link = os.path.join(self.home, "trees-link")
        os.symlink(self.base, ancestor_link)
        for nofollow_any in self.both_ways():
            with self.subTest(nofollow_any=bool(nofollow_any)):
                self.assertFalse(self.opens(tree_link))                                # tree itself a link
                self.assertTrue(self.opens(os.path.join(ancestor_link, "tree")))       # an ancestor a link: fine
                self.assertTrue(self.opens(os.path.join(self.base, "..", "trees", "tree")))

    def test_relpaths_that_are_not_plain(self):
        for nofollow_any in self.both_ways():
            for relpath in ("", "a//b/c/f.txt", "./a/b/c/f.txt", "a/./b/c/f.txt", "a/b/../b/c/f.txt",
                            "a/b/c/f.txt/", os.path.join(self.tree, "a/b/c/f.txt"), "../tree/a/b/c/f.txt"):
                with self.subTest(nofollow_any=bool(nofollow_any), relpath=relpath[-30:]):
                    self.assertFalse(self.opens(self.tree, relpath))

    def test_a_hard_link_or_a_fifo_opens_but_is_not_read(self):
        target = os.path.join(self.tree, "a", "b", "c", "f.txt")
        os.link(os.path.join(self.elsewhere, "a", "b", "c", "f.txt"), os.path.join(self.tree, "a", "linked.txt"))
        os.mkfifo(os.path.join(self.tree, "a", "fifo"))
        for nofollow_any in self.both_ways():
            with self.subTest(nofollow_any=bool(nofollow_any)):
                self.assertTrue(self.opens(self.tree, "a/linked.txt"))
                self.assertIsNone(pin.read_below(self.tree, "a/linked.txt"))
                self.assertTrue(self.opens(self.tree, "a/fifo"))                 # O_NONBLOCK: no wait for a writer
                self.assertIsNone(pin.read_below(self.tree, "a/fifo"))
                self.assertEqual(pin.read_below(self.tree, "a/b/c/f.txt", 9), b"synthetic")
                self.assertIsNone(pin.read_below(self.tree, "a/b/c/f.txt", 8))  # over the limit
        self.assertTrue(os.path.isfile(target))


class VerifyLinkLevelTests(Case):
    """pin.verify on a copy of the deps clone with a link at each directory level of the pinned files: pin_mismatch
    (or deps_missing for the deps directory itself), and a link above the deps directory is allowed."""

    def setUp(self):
        self.home = make_home(self, deps=True)
        self.pin = pin.load()
        self.deps = pin.deps_dir(self.pin, self.home)

    def test_a_link_at_each_directory_level(self):
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        levels = sorted({os.path.dirname(relpath) for relpath in pin.PINNED_FILES} | {"research"})
        for level in levels:
            path = os.path.join(self.deps, *level.split("/"))
            moved = os.path.join(elsewhere, level.replace("/", "-"))
            os.rename(path, moved)
            os.symlink(moved, path)
            try:
                with self.subTest(level=level):
                    with self.assertRaises(SuiteError) as caught:
                        pin.verify(self.pin, self.deps)
                    self.assertEqual(caught.exception.code, "pin_mismatch", level)
            finally:
                os.remove(path)
                os.rename(moved, path)
            pin.verify(self.pin, self.deps)

    def test_the_deps_directory_and_its_ancestors(self):
        deps_root = os.path.dirname(self.deps)
        moved = os.path.join(self.home, "moved-deps")
        os.rename(self.deps, moved)
        os.symlink(moved, self.deps)
        with self.assertRaises(SuiteError) as caught:
            pin.verify(self.pin, self.deps)
        self.assertEqual(caught.exception.code, "deps_missing")
        os.remove(self.deps)
        os.rename(moved, self.deps)
        moved_root = os.path.join(self.home, "moved-root")
        os.rename(deps_root, moved_root)
        os.symlink(moved_root, deps_root)
        pin.verify(self.pin, self.deps)                         # a link above the deps directory: allowed
        os.remove(deps_root)
        os.rename(moved_root, deps_root)


if __name__ == "__main__":
    unittest.main()
