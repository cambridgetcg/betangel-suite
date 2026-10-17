"""I-13: pin integrity, and never the moving deploy clone (DESIGN.md 3.5, section 10).

Tampering is tested on temporary copies of the pinned files under a temporary HOME; the real deps clone
is only read. Activation and origin checks run in fresh subprocesses.
"""

import ast
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from betangel_suite import pin, roots
from betangel_suite.errors import SuiteError
from tests import ARM_ENGINE, DEPS, PRELUDE, ROOT, make_home, run_python

PINNED_COMMIT = "76f71dc94588a50f0df56dde2c3fabcf6e102f88"


def outcome(case, home, code, timeout=60):
    result = run_python(code, home, timeout=timeout)
    case.assertEqual(result.returncode, 0, result.stderr)
    return result.stdout.strip()


def firmlink_spelling(directory):
    """The same directory through the Data volume's own path (/Users and /private are firmlinks to it)."""
    alias = "/System/Volumes/Data" + os.path.realpath(directory)
    assert os.path.samefile(alias, directory), alias
    return alias


def volfs_spelling(directory):
    """The same directory as /.vol/<st_dev>/<st_ino>."""
    info = os.stat(directory)
    alias = "/.vol/%d/%d" % (info.st_dev, info.st_ino)
    assert os.path.samefile(alias, directory), alias
    return alias


TRY_RX = """
from betangel_suite.errors import SuiteError
try:
    from betangel_suite import rx
    print("imported")
except SuiteError as exc:
    print(exc)
print("upstream_loaded" if any(m.startswith("betangel_research") for m in sys.modules) else "upstream_absent")
"""


class PinFileTests(unittest.TestCase):

    def test_pin_names_the_design_commit_and_the_closure(self):
        loaded = pin.load()
        self.assertEqual(loaded["commit"], PINNED_COMMIT)
        self.assertEqual(set(loaded["files"]), set(pin.PINNED_FILES))
        self.assertEqual(len(pin.PINNED_FILES), 26)
        self.assertEqual(DEPS, pin.deps_dir(loaded, roots.home()))
        self.assertTrue(DEPS.endswith("/betangel-research-" + PINNED_COMMIT[:12]))

    def test_real_deps_clone_verifies(self):
        pin.verify(pin.load(), DEPS)

    def test_pin_json_is_strict(self):
        good = pin.load()
        variants = {
            "duplicate_key": '{"repo": "x", ' + json.dumps(good)[1:],
            "nan": json.dumps(good).replace('"schema_version": 1', '"schema_version": NaN'),
            "bool_version": json.dumps(dict(good, schema_version=True)),
            "extra_key": json.dumps(dict(good, extra=1)),
            "other_repo": json.dumps(dict(good, repo="someone/else")),
            "short_commit": json.dumps(dict(good, commit=good["commit"][:12])),
            "missing_file": json.dumps(dict(good, files={k: v for k, v in list(good["files"].items())[1:]})),
            "extra_file": json.dumps(dict(good, files=dict(good["files"], **{"betangel_research/betfair/risk.py": "0" * 64}))),
            "bad_hash": json.dumps(dict(good, files=dict(good["files"], **{pin.PINNED_FILES[0]: "XYZ"}))),
            "not_json": "{",
        }
        folder = tempfile.mkdtemp(prefix="pin-")
        self.addCleanup(shutil.rmtree, folder)
        for name, text in variants.items():
            path = os.path.join(folder, name + ".json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            with self.assertRaises(SuiteError, msg=name) as caught:
                pin.load(path)
            self.assertEqual(caught.exception.code, "pin_invalid", name)
        link = os.path.join(folder, "link.json")
        os.symlink(pin.PIN_FILE, link)
        with self.assertRaises(SuiteError):
            pin.load(link)


class VerifyCopyTests(unittest.TestCase):
    """Tampered temporary copies are refused with pin_mismatch (or the more specific code)."""

    def setUp(self):
        self.home = make_home(self, deps=True)
        self.pin = pin.load()
        self.deps = pin.deps_dir(self.pin, self.home)

    def assert_refused(self, code):
        with self.assertRaises(SuiteError) as caught:
            pin.verify(self.pin, self.deps)
        self.assertEqual(caught.exception.code, code)

    def test_untouched_copy_verifies(self):
        pin.verify(self.pin, self.deps)

    def test_one_changed_byte(self):
        path = os.path.join(self.deps, "betangel_research", "betfair", "paper.py")
        with open(path, "r+b") as handle:
            first = handle.read(1)
            handle.seek(0)
            handle.write(bytes([first[0] ^ 1]))
        self.assert_refused("pin_mismatch")

    def test_missing_file(self):
        os.remove(os.path.join(self.deps, "research", "experiments", "backtest-p0-bsp-v1.json"))
        self.assert_refused("pin_mismatch")

    def test_symlinked_file_with_the_right_bytes(self):
        path = os.path.join(self.deps, "betangel_research", "betfair", "ticks.py")
        os.remove(path)
        os.symlink(os.path.join(DEPS, "betangel_research", "betfair", "ticks.py"), path)
        self.assert_refused("pin_mismatch")

    def test_links_on_the_way_to_a_pinned_file(self):
        # Nuance's PR #2 review, item 8: a symlinked research/ (or research/experiments/) and a hard-linked ticks.py
        # passed activate(), reading bytes the deploy clone could change. Refused with O_NOFOLLOW_ANY, and by the
        # component walk that replaces it where the flag is missing. The control copy verifies both ways.
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        experiments = os.path.join(self.deps, "research", "experiments")
        ticks = os.path.join(self.deps, "betangel_research", "betfair", "ticks.py")

        def link_directory(path):
            moved = os.path.join(elsewhere, os.path.basename(path))
            os.rename(path, moved)
            os.symlink(moved, path)
            return lambda: (os.remove(path), os.rename(moved, path))

        def hard_link_file(path):
            outside = os.path.join(elsewhere, "ticks.py")
            shutil.copyfile(path, outside)
            os.remove(path)
            os.link(outside, path)
            return lambda: (os.remove(outside),)

        for nofollow_any in (pin._NOFOLLOW_ANY, 0):
            with mock.patch.object(pin, "_NOFOLLOW_ANY", nofollow_any):
                pin.verify(self.pin, self.deps)
                for name, make in (("research", lambda: link_directory(os.path.dirname(experiments))),
                                   ("experiments", lambda: link_directory(experiments)),
                                   ("hard_link", lambda: hard_link_file(ticks))):
                    with self.subTest(nofollow_any=nofollow_any, case=name):
                        undo = make()
                        try:
                            self.assert_refused("pin_mismatch")
                        finally:
                            undo()
                        pin.verify(self.pin, self.deps)

    def test_fifo_in_place_of_a_pinned_file_or_the_pin_does_not_hang(self):
        # Nuance's PR #2 review, item 22 (Astra's half): open() of a FIFO waits for a writer. O_NONBLOCK, then
        # fstat before any read. Run in a child with a timeout, so a hang fails the test instead of the run.
        path = os.path.join(self.deps, "research", "experiments", "backtest-p0-bsp-v1.json")
        os.remove(path)
        os.mkfifo(path)
        fifo_pin = os.path.join(self.home, "pin-fifo.json")
        os.mkfifo(fifo_pin)
        code = ("from betangel_suite import pin\nfrom betangel_suite.errors import SuiteError\n"
                "for call in (lambda: pin.verify(pin.load(), %r), lambda: pin.load(%r)):\n"
                "    try:\n        call()\n        print('ok')\n    except SuiteError as exc:\n        print(exc)\n"
                ) % (self.deps, fifo_pin)
        self.assertEqual(outcome(self, self.home, code, timeout=20).splitlines(), ["pin_mismatch", "pin_invalid"])

    def test_bytecode_cache_present(self):
        os.mkdir(os.path.join(self.deps, "betangel_research", "betfair", "__pycache__"))
        self.assert_refused("deps_bytecode_present")

    def test_files_python_would_import_before_a_pinned_module(self):
        # An extension module or sourceless bytecode beside paper.py is imported in preference to the hashed
        # .py, and a package directory named like a pinned module shadows it too.
        betfair = os.path.join(self.deps, "betangel_research", "betfair")
        for name in ("paper.cpython-313-darwin.so", "paper.cpython-311-darwin.so", "paper.abi3.so", "paper.so",
                     "paper.pyc", "gateway.pyc"):
            with self.subTest(name=name):
                path = os.path.join(betfair, name)
                with open(path, "wb") as handle:
                    handle.write(b"synthetic")
                self.assert_refused("deps_shadow_present")
                os.remove(path)
        for make in (lambda path: os.mkdir(path), lambda path: os.symlink(os.path.join(betfair, "paper.py"), path)):
            path = os.path.join(betfair, "paper")
            make(path)
            self.assert_refused("deps_shadow_present")
            (os.rmdir if not os.path.islink(path) else os.remove)(path)
        with open(os.path.join(betfair, "NOTES.txt"), "wb") as handle:
            handle.write(b"synthetic")
        pin.verify(self.pin, self.deps)          # an unrelated file is harmless

    def test_missing_deps_directory(self):
        shutil.rmtree(self.deps)
        self.assert_refused("deps_missing")

    def test_tampered_copy_refused_before_any_upstream_import(self):
        path = os.path.join(self.deps, "betangel_research", "betfair", "validate.py")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# synthetic tamper\n")
        self.assertEqual(outcome(self, self.home, ARM_ENGINE + TRY_RX).splitlines(),
                         ["pin_mismatch", "upstream_absent"])


class OpenBelowTests(unittest.TestCase):
    """pin._open_below: "tree itself must not be a link, though its ancestors may be", with O_NOFOLLOW_ANY and with
    the component walk that replaces it."""

    def test_the_tree_itself_spelt_with_a_final_slash_or_dot(self):
        # The guard-paths review: a final "/", "/." or "//" makes the kernel follow a link at tree even with
        # O_NOFOLLOW, so tree-link + "/" opened the file below the link's target. No caller passes such a spelling
        # (deps_dir and vendor's partial and dest are joined paths), so this pins the function's own contract: tree
        # must end in its own name, and a real tree spelt that way is refused too.
        home = make_home(self)
        base = os.path.join(home, "trees")
        tree = os.path.join(base, "tree")
        os.makedirs(os.path.join(tree, "a", "b", "c"))
        with open(os.path.join(tree, "a", "b", "c", "f.txt"), "w", encoding="utf-8") as handle:
            handle.write("synthetic")
        tree_link = os.path.join(base, "tree-link")
        os.symlink(tree, tree_link)
        base_link = os.path.join(home, "trees-link")
        os.symlink(base, base_link)

        def opens(spelled):
            try:
                os.close(pin._open_below(spelled, "a/b/c/f.txt"))
            except OSError:
                return False
            return True

        for nofollow_any in (pin._NOFOLLOW_ANY, 0):
            with mock.patch.object(pin, "_NOFOLLOW_ANY", nofollow_any):
                self.assertTrue(opens(tree))
                self.assertTrue(opens(os.path.join(base_link, "tree")))           # an ancestor a link: fine
                self.assertEqual(pin.read_below(tree, "a/b/c/f.txt"), b"synthetic")
                for spelled in (tree_link, tree_link + "/", tree_link + "/.", tree_link + "//", tree_link + "/./",
                                tree + "/", tree + "/.", os.path.join(tree, "a", "..")):
                    with self.subTest(nofollow_any=bool(nofollow_any), tree=spelled[len(base):]):
                        self.assertFalse(opens(spelled))
                        self.assertIsNone(pin.read_below(spelled, "a/b/c/f.txt"))


class ActivationTests(unittest.TestCase):

    def test_unarmed_process_cannot_activate_or_import_rx(self):
        home = make_home(self, deps=True)
        code = PRELUDE + TRY_RX + (
            "from betangel_suite import pin\n"
            "try:\n    pin.activate()\nexcept SuiteError as exc:\n    print(exc)\n")
        self.assertEqual(outcome(self, home, code).splitlines(),
                         ["guard_not_armed", "upstream_absent", "guard_not_armed"])

    def test_engine_imports_rx_from_the_deps_copy(self):
        home = make_home(self, deps=True)
        code = ARM_ENGINE + TRY_RX + (
            "import os\n"
            "import betangel_research\n"
            "from betangel_suite import pin\n"
            "deps = pin.deps_dir(pin.load())\n"
            "print(os.path.realpath(betangel_research.__file__).startswith(os.path.realpath(deps) + os.sep))\n"
            "print(deps not in sys.path)\n")
        self.assertEqual(outcome(self, home, code).splitlines(), ["imported", "upstream_loaded", "True", "True"])

    def test_nothing_but_the_closure_is_imported_from_the_deps_directory(self):
        # Nuance's re-review of #2, F1: activate() appended the deps directory to sys.path, so after seal() every
        # top-level name in the deps tree but betangel_research loaded unhashed: scripts.backup_metadata (real at
        # 76f71dc), a planted module, and the standard library's probes for modules that macOS lacks (nt and _winapi on
        # 3.13, org on 3.11), which reached the deps directory during a plain import of rx. The directory is no longer
        # on sys.path: each planted module below is not found, and none of their code runs, during rx's import or after.
        home = make_home(self, deps=True)
        deps = pin.deps_dir(pin.load(), home)
        names = ("extra_mod", "scripts.backup_metadata", "nt", "_winapi", "_wmi", "org")
        for relpath in ("extra_mod.py", "scripts/__init__.py", "scripts/backup_metadata.py", "nt.py", "_winapi.py",
                        "_wmi.py", "org/__init__.py"):
            path = os.path.join(deps, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("print('synthetic planted module ran: %s')\n" % relpath)
        code = ARM_ENGINE + TRY_RX + """
import importlib
from betangel_suite import guard
guard.seal()
for name in %r:
    try:
        importlib.import_module(name)
        print(name, "imported")
    except ModuleNotFoundError:
        print(name, "not found")
print(%r in sys.path)
""" % (names, deps)
        self.assertEqual(outcome(self, home, code).splitlines(),
                         ["imported", "upstream_loaded"] + ["%s not found" % name for name in names] + ["False"])

    def test_research_clone_on_sys_path_is_refused(self):
        # The lab's APFS volume folds case and U+017F (long s), so BetAngel-Research and betangel-reſearch
        # name the clone too; so do the firmlink and /.vol spellings, which realpath leaves as they are.
        home = make_home(self, deps=True)
        research = roots.research_clone(home)
        sub = os.path.join(research, "sub")
        os.makedirs(sub)
        os.symlink(sub, os.path.join(home, "alias"))
        for entry in (research, sub, os.path.join(home, "alias"),
                      os.path.join(home, "BetAngel-Research"), os.path.join(home, "betangel-reſearch", "sub"),
                      firmlink_spelling(research), firmlink_spelling(sub), volfs_spelling(sub)):
            with self.subTest(entry=entry):
                code = ARM_ENGINE + "sys.path.append(%r)\n" % entry + TRY_RX
                self.assertEqual(outcome(self, home, code).splitlines(), ["research_clone_on_path", "upstream_absent"])

    def test_entry_with_dotdot_after_a_link_into_the_research_clone_is_refused(self):
        # The kernel follows a link before it applies "..": with safe/alias -> clone/sub, safe/alias/../sub
        # opens clone/sub. Folding "alias/.." first would judge safe/sub, a real directory outside the clone.
        # Refused when absolute and when relative (the child's cwd is HOME). safe/alias/.. with nothing after
        # it names the clone itself (Astra's #4 and #5 re-reviews), and folding it would judge safe. The
        # controls keep the same shape but land outside the clone, through a real directory and through a
        # link, and are allowed.
        home = make_home(self, deps=True)
        research = roots.research_clone(home)
        os.makedirs(os.path.join(research, "sub"))
        safe = os.path.join(home, "safe")
        for name in ("sub", "real", os.path.join("outside", "deep")):
            os.makedirs(os.path.join(safe, name))
        os.symlink(os.path.join(research, "sub"), os.path.join(safe, "alias"))
        os.symlink(os.path.join(safe, "outside", "deep"), os.path.join(safe, "elsewhere"))
        cases = ((os.path.join(safe, "alias", "..", "sub"), ["research_clone_on_path", "upstream_absent"]),
                 (os.path.join("safe", "alias", "..", "sub"), ["research_clone_on_path", "upstream_absent"]),
                 (os.path.join(safe, "alias", ".."), ["research_clone_on_path", "upstream_absent"]),
                 (os.path.join("safe", "alias", ".."), ["research_clone_on_path", "upstream_absent"]),
                 (os.path.join(".", "safe", "alias", ".."), ["research_clone_on_path", "upstream_absent"]),
                 (os.path.join(safe, "real", ".."), ["imported", "upstream_loaded"]),
                 (os.path.join(safe, "real", "..", "sub"), ["imported", "upstream_loaded"]),
                 (os.path.join("safe", "elsewhere", "..", "deep"), ["imported", "upstream_loaded"]))
        for entry, expected in cases:
            with self.subTest(entry=entry):
                code = ARM_ENGINE + "sys.path.append(%r)\n" % entry + TRY_RX
                self.assertEqual(outcome(self, home, code).splitlines(), expected)

    def test_deps_reached_through_a_link_into_the_research_clone_is_refused(self):
        # The deps directory itself is real, but an ancestor links into the deploy clone (I-13): refused
        # before its files are read or it is appended, however the link spells its target. (A link to a
        # /.vol/<dev>/<ino> path does not resolve: the kernel reads that spelling only at the start of a path.)
        for spell in (lambda path: path, firmlink_spelling):
            home = make_home(self, deps=True)
            research = roots.research_clone(home)
            os.makedirs(research)
            moved = os.path.join(research, "vendor")
            os.rename(roots.deps_root(home), moved)
            os.symlink(spell(moved), roots.deps_root(home))
            with self.subTest(target=os.readlink(roots.deps_root(home))):
                self.assertEqual(outcome(self, home, ARM_ENGINE + TRY_RX).splitlines(),
                                 ["research_clone_on_path", "upstream_absent"])

    def test_links_in_deps_are_refused_before_any_upstream_import(self):
        # Nuance's PR #2 review, item 8, end to end: a research/ that links into the deploy clone, and a ticks.py hard
        # linked to the clone's copy, each with the right bytes, are refused before betangel_research is imported.
        for case in ("research", "hard_link"):
            home = make_home(self, deps=True)
            research = roots.research_clone(home)
            deps = pin.deps_dir(pin.load(), home)
            os.makedirs(research)
            if case == "research":
                os.rename(os.path.join(deps, "research"), os.path.join(research, "research"))
                os.symlink(os.path.join(research, "research"), os.path.join(deps, "research"))
            else:
                ticks = os.path.join("betangel_research", "betfair", "ticks.py")
                os.makedirs(os.path.dirname(os.path.join(research, ticks)))
                os.rename(os.path.join(deps, ticks), os.path.join(research, ticks))
                os.link(os.path.join(research, ticks), os.path.join(deps, ticks))
            with self.subTest(case=case):
                self.assertEqual(outcome(self, home, ARM_ENGINE + TRY_RX).splitlines(), ["pin_mismatch", "upstream_absent"])

    def test_read_pinned_gives_only_the_pinned_bytes(self):
        # Nuance's PR #2 review, item 8: the month-role JSON is read through pin.read_pinned(), which checks the bytes
        # against the pin again, so a change after activate() (new bytes, or research/ swapped for a link with the
        # same bytes) is refused. So is a path that is not pinned, and a call without the guard. The child is armed in
        # vendor mode, whose write roots hold the deps tree, so it can make those changes itself.
        home = make_home(self, deps=True)
        month_roles = "research/experiments/backtest-p0-bsp-v1.json"
        code = PRELUDE + "from betangel_suite import guard\nguard.arm('vendor')\n" + """
import hashlib, os, shutil
from betangel_suite import pin, roots
from betangel_suite.errors import SuiteError
def attempt(relpath):
    try:
        data = pin.read_pinned(relpath)
        return hashlib.sha256(data).hexdigest() == pin.load()["files"].get(relpath)
    except SuiteError as exc:
        return str(exc)
deps = pin.activate()
results = [attempt(%(month)r), attempt("README.md"), attempt("betangel_research/betfair/risk.py")]
moved = os.path.join(roots.deps_root(), "elsewhere")
os.rename(os.path.join(deps, "research"), moved)
os.symlink(moved, os.path.join(deps, "research"))
results.append(attempt(%(month)r))
os.remove(os.path.join(deps, "research"))
os.rename(moved, os.path.join(deps, "research"))
results.append(attempt(%(month)r))
with open(os.path.join(deps, %(month)r), "ab") as handle:
    handle.write(b" ")
results.append(attempt(%(month)r))
print(results)
""" % {"month": month_roles}
        self.assertEqual(outcome(self, home, code), str([True, "pin_mismatch", "pin_mismatch", "pin_mismatch", True,
                                                         "pin_mismatch"]))
        unarmed = "from betangel_suite import pin\ntry:\n    pin.read_pinned(%r)\nexcept Exception as exc:\n    print(exc)\n"
        self.assertEqual(outcome(self, home, PRELUDE + unarmed % month_roles), "guard_not_armed")

    def test_upstream_imported_before_activation_is_refused(self):
        home = make_home(self, deps=True)
        fake = os.path.join(home, "fake")
        os.makedirs(os.path.join(fake, "betangel_research"))
        with open(os.path.join(fake, "betangel_research", "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        code = ARM_ENGINE + "sys.path.insert(0, %r)\nimport betangel_research\n" % fake + TRY_RX
        self.assertEqual(outcome(self, home, code).splitlines(), ["upstream_imported_early", "upstream_loaded"])

    def test_a_copy_earlier_on_sys_path_is_never_loaded(self):
        # Until the closure finder, a copy of the closure put before the deps directory on sys.path after activate()
        # was loaded, and only the origin check refused it. Now every closure module comes from the deps directory.
        home = make_home(self, deps=True)
        fake = os.path.join(home, "fake")
        for relpath in pin.PINNED_FILES:
            if relpath.startswith("betangel_research/"):
                os.makedirs(os.path.dirname(os.path.join(fake, relpath)), exist_ok=True)
                shutil.copyfile(os.path.join(DEPS, relpath), os.path.join(fake, relpath))
        code = ARM_ENGINE + ("from betangel_suite import pin\ndeps = pin.activate()\nsys.path.insert(0, %r)\n" % fake) + TRY_RX + (
            "import os\n"
            "print(all(os.path.realpath(m.__file__).startswith(os.path.realpath(deps) + os.sep)\n"
            "          for name, m in sys.modules.items() if name.startswith('betangel_research')))\n")
        self.assertEqual(outcome(self, home, code).splitlines(), ["imported", "upstream_loaded", "True"])

    def test_module_from_elsewhere_fails_the_origin_check(self):
        # assert_origins stays as a cross-check: a module object put into sys.modules from elsewhere is refused.
        home = make_home(self, deps=True)
        code = ARM_ENGINE + TRY_RX + (
            "import types\nfrom betangel_suite import pin\n"
            "planted = types.ModuleType('betangel_research.betfair.planted')\n"
            "planted.__file__ = %r\n"
            "sys.modules[planted.__name__] = planted\n"
            "try:\n    pin.assert_origins(pin.activate())\nexcept SuiteError as exc:\n    print(exc)\n"
        ) % os.path.join(home, "fake", "planted.py")
        self.assertEqual(outcome(self, home, code).splitlines(), ["imported", "upstream_loaded", "upstream_origin_mismatch"])

    def test_only_the_closure_is_imported_after_activation(self):
        # Nuance's PR #2 review, item 7: the betangel_research package's __path__ is in the deps directory (which was
        # on sys.path too until Nuance's re-review of #2, F1), so after seal() an unpinned module there (risk.py, say)
        # could be imported and its unhashed code run. The finder refuses it, however it is imported (an import hook
        # would miss import_module), and its code never runs.
        home = make_home(self, deps=True)
        deps = pin.deps_dir(pin.load(), home)
        with open(os.path.join(deps, "betangel_research", "betfair", "risk.py"), "w", encoding="utf-8") as handle:
            handle.write("print('synthetic unpinned module ran')\n")
        code = ARM_ENGINE + TRY_RX + """
import importlib
for name, call in (("statement", lambda: exec("import betangel_research.betfair.risk")),
                   ("from", lambda: exec("from betangel_research.betfair import risk")),
                   ("import_module", lambda: importlib.import_module("betangel_research.betfair.risk")),
                   ("dunder", lambda: __import__("betangel_research.betfair.risk")),
                   ("relative", lambda: importlib.import_module(".risk", "betangel_research.betfair")),
                   ("find_spec", lambda: importlib.util.find_spec("betangel_research.betfair.gateway"))):
    try:
        call()
        print(name, "imported")
    except SuiteError as exc:
        print(name, exc)
print("betangel_research.betfair.risk" in sys.modules)
"""
        self.assertEqual(outcome(self, home, code).splitlines(),
                         ["imported", "upstream_loaded"] + ["%s upstream_import_refused" % name for name in (
                             "statement", "from", "import_module", "dunder", "relative", "find_spec")] + ["False"])

    def test_closure_module_changed_after_activation_is_refused_when_loaded(self):
        # The finder's loader reads each closure module through read_pinned when it is imported, so bytes changed
        # between activate() and the import are refused (the origin check would pass them). The child is armed in
        # vendor mode, whose write roots hold the deps tree, so it can change them itself.
        home = make_home(self, deps=True)
        code = PRELUDE + "from betangel_suite import guard\nguard.arm('vendor')\n" + (
            "from betangel_suite import pin\ndeps = pin.activate()\n"
            "with open(deps + '/betangel_research/betfair/ticks.py', 'a', encoding='utf-8') as handle:\n"
            "    handle.write('\\nSYNTHETIC_CHANGE = 1\\n')\n") + TRY_RX + (
            "print('betangel_research.betfair.ticks' in sys.modules)\n")
        self.assertEqual(outcome(self, home, code).splitlines(), ["pin_mismatch", "upstream_loaded", "False"])


class MovingCloneTests(unittest.TestCase):

    def test_sys_path_never_holds_the_deploy_clone(self):
        pin.refuse_research_on_path()
        research = os.path.realpath(roots.research_clone())
        for entry in sys_path():
            self.assertFalse(roots.within(os.path.realpath(entry), research), entry)
        self.assertFalse(roots.within(os.path.realpath(DEPS), research))

    def test_real_deps_clone_is_read_only_detached_and_has_no_remote(self):
        for relpath in pin.PINNED_FILES:
            self.assertEqual(os.lstat(os.path.join(DEPS, relpath)).st_mode & 0o222, 0, relpath)
        for directory in pin.PACKAGE_DIRS:
            self.assertEqual(os.lstat(os.path.join(DEPS, directory)).st_mode & 0o222, 0, directory)
        with open(os.path.join(DEPS, ".git", "HEAD"), encoding="ascii") as handle:
            self.assertEqual(handle.read(), pin.load()["commit"] + "\n")
        with open(os.path.join(DEPS, ".git", "config"), encoding="utf-8") as handle:
            self.assertNotIn("[remote", handle.read())

    def test_oracle_tests_never_use_the_deploy_clone_as_repo_root(self):
        # run_paper_replay records receipts.git_state(repo_root), which runs `git status` there and can
        # rewrite .git/index (DESIGN.md 4.2): repo_root must always be a temporary clone of the deps clone.
        for name in sorted(os.listdir(os.path.join(ROOT, "tests"))):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(ROOT, "tests", name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "run_paper_replay":
                    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                    self.assertIn("repo_root", keywords, name)
                    text = ast.unparse(keywords["repo_root"])
                    self.assertNotIsInstance(keywords["repo_root"], ast.Constant, name)
                    self.assertNotIn("research_clone", text, name)
                    self.assertNotIn("betangel-research", text, name)


def sys_path():
    import sys
    return [entry for entry in sys.path if isinstance(entry, str) and entry]


if __name__ == "__main__":
    unittest.main()
