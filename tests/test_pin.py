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

from betangel_suite import pin, roots
from betangel_suite.errors import SuiteError
from tests import ARM_ENGINE, DEPS, PRELUDE, ROOT, make_home, run_python

PINNED_COMMIT = "76f71dc94588a50f0df56dde2c3fabcf6e102f88"


def outcome(case, home, code):
    result = run_python(code, home)
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
            "print(sys.path[-1] == deps)\n")
        self.assertEqual(outcome(self, home, code).splitlines(), ["imported", "upstream_loaded", "True", "True"])

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
        # Refused when absolute and when relative (the child's cwd is HOME). The controls keep the same
        # shape but land outside the clone, through a real directory and through a link, and are allowed.
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

    def test_upstream_imported_before_activation_is_refused(self):
        home = make_home(self, deps=True)
        fake = os.path.join(home, "fake")
        os.makedirs(os.path.join(fake, "betangel_research"))
        with open(os.path.join(fake, "betangel_research", "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        code = ARM_ENGINE + "sys.path.insert(0, %r)\nimport betangel_research\n" % fake + TRY_RX
        self.assertEqual(outcome(self, home, code).splitlines(), ["upstream_imported_early", "upstream_loaded"])

    def test_module_loaded_from_elsewhere_fails_the_origin_check(self):
        home = make_home(self, deps=True)
        fake = os.path.join(home, "fake")
        for relpath in pin.PINNED_FILES:
            if relpath.startswith("betangel_research/"):
                os.makedirs(os.path.dirname(os.path.join(fake, relpath)), exist_ok=True)
                shutil.copyfile(os.path.join(DEPS, relpath), os.path.join(fake, relpath))
        code = ARM_ENGINE + ("from betangel_suite import pin\npin.activate()\nsys.path.insert(0, %r)\n" % fake) + TRY_RX
        self.assertEqual(outcome(self, home, code).splitlines()[0], "upstream_origin_mismatch")


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
