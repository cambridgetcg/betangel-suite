"""Error mapping (DESIGN.md 9.1, 9.2 item 9): codes, listed reasons and salted hashes, never identifiers.

Every identifier below is synthetic (reserved namespace, DESIGN.md 5.6: markets 1.999xxxxxx, events
99xxxxxx). The checks assert that no id-like or path text escapes into a mapped error, its traceback,
or what the exception hooks print.
"""

import ast
import hashlib
import os
import re
import traceback
import unittest

from betangel_suite import errors, roots, rx
from betangel_suite.errors import CODES, UPSTREAM_REASONS, SuiteError
from tests import ARM_ENGINE, DEPS, ROOT, make_home, run_python

MARKET = "1.999000001"
EVENT = "99000001"
MEMBER = "PRO/2015/May/1/%s/%s.bz2" % (EVENT, MARKET)
LEAKS = (MARKET, EVENT, "999000001", "PRO/", "May/1", ".bz2")


def leaked(text):
    return [needle for needle in LEAKS if needle in text]


class SuiteErrorTests(unittest.TestCase):

    def test_text_is_code_reason_and_ref_only(self):
        self.assertEqual(str(SuiteError("pin_mismatch")), "pin_mismatch")
        self.assertEqual(str(SuiteError("path_denied", "missing_path")), "path_denied:missing_path")
        self.assertEqual(str(SuiteError("index_problem", "missing", "h0123456789abcdef")),
                         "index_problem:missing ref=h0123456789abcdef")

    def test_unlisted_codes_reasons_and_refs_never_pass_through(self):
        self.assertEqual(str(SuiteError("made up " + MARKET)), "unlisted_code")
        self.assertEqual(SuiteError("pin_mismatch", MARKET).reason, "unlisted_reason")
        self.assertIsNone(SuiteError("pin_mismatch", None, MEMBER).ref)

    def test_enums_are_code_shaped(self):
        for value in CODES | UPSTREAM_REASONS:
            self.assertRegex(value, r"\A[a-z][a-z0-9_]*\Z")

    def test_every_literal_code_in_suite_sources_is_listed(self):
        sources = [os.path.join(ROOT, "betangel_suite", name) for name in os.listdir(os.path.join(ROOT, "betangel_suite"))
                   if name.endswith(".py")]
        sources += [os.path.join(ROOT, "bin", "_launch.py"), os.path.join(ROOT, "tools", "vendor_research.py")]
        names = {"SuiteError", "GuardRefusal", "error"}
        seen = set()
        for path in sources:
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if called in names and isinstance(node.args[0], ast.Constant):
                    self.assertIn(node.args[0].value, CODES, os.path.basename(path))
                    seen.add(node.args[0].value)
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value is not None:
                        self.assertIn(node.args[1].value, UPSTREAM_REASONS)
        self.assertGreater(len(seen), 30)
        # bin/suite prints its SSH refusals before env -i, as literal refused:<code> lines.
        with open(os.path.join(ROOT, "bin", "suite"), encoding="utf-8") as handle:
            launcher = re.findall(r"refused:([a-z0-9_]+)", handle.read())
        self.assertEqual(sorted(set(launcher)), ["open_over_ssh", "print_url_over_ssh", "ssh_original_command",
                                                 "ssh_session_outside_ssh"])
        self.assertLessEqual(set(launcher), CODES)

    def test_listed_reasons_cover_the_pinned_upstream_raise_sites(self):
        # Drift check for pin bumps: every coded reason the closure can put after the last colon must be listed.
        # It visits every construction of the mapped classes (not only raise statements: archive.py builds
        # ArchiveProblem("not_bz2") first and raises it later), follows conditional expressions and a dynamic
        # tail named by a variable assigned string constants in the same module, and, in the backtest
        # package, the constants assigned to `reason` (a member's unreadable reason).
        found = upstream_reasons(DEPS, rx.pin.PINNED_FILES)
        self.assertIn("not_bz2", found)
        self.assertEqual(sorted(set(found) - UPSTREAM_REASONS), [])


KINDS = {"IndexProblem", "ArchiveProblem", "PathDenied", "JournalError", "ValueError", "ConfigError",
         "ContractFileError"}
CODE_SHAPED = re.compile(r"\A[a-z][a-z0-9_]*\Z")
NOT_REASONS = {"root"}      # config.py's "config_object_expected:root": a config path, not a reason


def upstream_reasons(deps, relpaths):
    """{reason: [file:line, ...]} for the coded tails the pinned upstream modules can produce."""
    found = {}
    for relpath in relpaths:
        if not relpath.endswith(".py"):
            continue
        with open(os.path.join(deps, relpath), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        assigned = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(node.value)
        sources = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                func = node.func
                if (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)) in KINDS:
                    sources.append((node.lineno, _tails(node.args[0], assigned)))
        if "/backtest/" in relpath:
            for value in assigned.get("reason", ()):
                sources.append((value.lineno, _constants(value, {})))
        for line, tails in sources:
            for tail in tails:
                tail = tail.rsplit(":", 1)[-1]
                if CODE_SHAPED.match(tail) and tail not in NOT_REASONS:
                    found.setdefault(tail, []).append("%s:%d" % (os.path.basename(relpath), line))
    return found


def _constants(node, assigned):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _constants(node.body, assigned) + _constants(node.orelse, assigned)
    if isinstance(node, ast.Name):
        return [text for value in assigned.get(node.id, ()) for text in _constants(value, {})]
    return []


def _tails(node, assigned):
    if isinstance(node, ast.JoinedStr):
        last = node.values[-1] if node.values else None
        if isinstance(last, ast.Constant):
            return [last.value]
        if isinstance(last, ast.FormattedValue):
            return _constants(last.value, assigned)
        return []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _tails(node.right, assigned)
    return _constants(node, assigned)


class MappingTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)

    def mapped(self, exc):
        return rx.map_error(exc, home_dir=self.home)

    def test_upstream_exceptions_map_to_codes(self):
        cases = (
            (rx.market_index.IndexProblem("raw:" + MEMBER + ":member_hash_mismatch"), "index_problem",
             "member_hash_mismatch", True),
            (rx.market_index.IndexProblem("raw:" + MEMBER + ":unsafe_target"), "index_problem", "unsafe_target", True),
            (rx.archive.ArchiveProblem("raw:" + MEMBER + ":not_regular"), "archive_problem", "not_regular", True),
            (rx.archive.ArchiveProblem("truncated_bz2"), "archive_problem", "truncated_bz2", False),
            (rx.path_guard.PathDenied("member:missing_path"), "path_denied", "missing_path", True),
            (rx.betfair_errors.JournalError("intent_source_invalid"), "journal_error", "intent_source_invalid", False),
            (ValueError("stream_unreliable"), "value_error", "stream_unreliable", False),
            (ValueError("market %s starts without marketTime" % MARKET), "value_error", "unlisted_reason", True),
            (ValueError("invalid literal for int() with base 10: '%s'" % MARKET), "value_error", "unlisted_reason", True),
            (UnicodeDecodeError("utf-8", MARKET.encode() + b"\xff", 11, 12, "invalid start byte"), "value_error",
             "unlisted_reason", True),
        )
        for exc, code, reason, has_ref in cases:
            result = self.mapped(exc)
            self.assertEqual((result.code, result.reason, result.ref is not None), (code, reason, has_ref), str(exc))
            self.assertEqual(leaked(str(result)), [], code)

    def test_same_hidden_text_gives_the_same_ref(self):
        one = self.mapped(rx.market_index.IndexProblem("raw:" + MEMBER + ":missing"))
        two = self.mapped(rx.market_index.IndexProblem("raw:" + MEMBER + ":unreadable"))
        three = self.mapped(rx.market_index.IndexProblem("raw:PRO/2015/May/1/99000002/1.999000002.bz2:missing"))
        self.assertEqual(one.ref, two.ref)
        self.assertNotEqual(one.ref, three.ref)

    def test_boundary_drops_the_original_exception_and_its_traceback(self):
        def boom():
            raise rx.market_index.IndexProblem("raw:" + MEMBER + ":member_hash_mismatch")

        # rx.call hashes with the install salt under $HOME: point HOME at the temporary one for this call,
        # so the test never creates the real salt (os.environ, not mock.patch.dict, whose clean-up would
        # clear the pinned variables the guard refuses to unset).
        real_home = os.environ["HOME"]
        os.environ["HOME"] = self.home
        try:
            with self.assertRaises(SuiteError) as caught:
                rx.call(boom)
        finally:
            os.environ["HOME"] = real_home
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".local", "state", "betangel-suite", "install-salt")))
        exc = caught.exception
        self.assertIsNone(exc.__context__)
        self.assertIsNone(exc.__cause__)
        self.assertEqual(leaked("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))), [])

    def test_unmapped_exceptions_pass_through(self):
        with self.assertRaises(ZeroDivisionError):
            rx.call(lambda: 1 // 0)
        self.assertEqual(rx.call(lambda value: value + 1, 1), 2)


class SaltedHashTests(unittest.TestCase):

    def test_hash_is_stable_per_install_and_differs_between_installs(self):
        first, second = make_home(self), make_home(self)
        one = errors.salted_hash(MARKET, home_dir=first)
        self.assertRegex(one, r"\Ah[0-9a-f]{16}\Z")
        self.assertEqual(one, errors.salted_hash(MARKET, home_dir=first))
        self.assertNotEqual(one, errors.salted_hash(MARKET, home_dir=second))
        self.assertNotIn(hashlib.sha256(MARKET.encode()).hexdigest()[:16], one)

    def test_salt_file_is_private_and_strict(self):
        home = make_home(self)
        errors.salted_hash("x", home_dir=home)
        path = os.path.join(home, ".local", "state", "betangel-suite", "install-salt")
        self.assertEqual(os.lstat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.path.getsize(path), errors.SALT_BYTES)
        for bad_mode, data in ((0o644, b"s" * errors.SALT_BYTES), (0o600, b"short")):
            other = make_home(self)
            bad = os.path.join(other, ".local", "state", "betangel-suite", "install-salt")
            with open(bad, "wb") as handle:
                handle.write(data)
            os.chmod(bad, bad_mode)
            with self.assertRaises(SuiteError) as caught:
                errors.salted_hash("x", home_dir=other)
            self.assertEqual(caught.exception.code, "salt_invalid")

    def test_a_fifo_or_directory_in_the_salts_place_is_refused_at_once(self):
        # Nuance's PR #2 review, item 22: a blocking open of a FIFO waits for a writer for ever. Each hash runs in a
        # child with a timeout, so a regression fails here instead of hanging the whole run.
        for label, make in (("fifo", os.mkfifo), ("directory", os.mkdir)):
            home = make_home(self)
            make(roots.salt_path(home))
            code = ("from betangel_suite import errors\n"
                    "try:\n    errors.salted_hash('x', home_dir=%r)\n"
                    "except errors.SuiteError as exc:\n    print(exc.code)\n") % home
            result = run_python(code, home, timeout=20)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "salt_invalid\n", ""), label)


class ExceptionHookTests(unittest.TestCase):

    def test_hooks_print_class_names_and_codes_only(self):
        home = make_home(self)
        code = ARM_ENGINE + (
            "import threading, gc\n"
            "from betangel_suite import errors\n"
            "errors.install_excepthooks()\n"
            "secret_text = %r\n"
            "thread = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError(secret_text)))\n"
            "thread.start(); thread.join()\n"
            "class Noisy:\n"
            "    def __del__(self):\n"
            "        raise ValueError(secret_text)\n"
            "Noisy(); gc.collect()\n"
            "raise KeyError(secret_text)\n") % ("market " + MARKET + " in " + MEMBER,)
        result = run_python(code, home)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.splitlines(),
                         ["thread:error:RuntimeError", "unraisable:error:ValueError", "error:KeyError"])

    def test_uncaught_suite_error_prints_a_refused_line(self):
        home = make_home(self)
        code = ARM_ENGINE + ("from betangel_suite import errors\nerrors.install_excepthooks()\n"
                             "raise errors.SuiteError('pin_mismatch')\n")
        result = run_python(code, home)
        self.assertEqual((result.returncode, result.stderr), (1, "refused:pin_mismatch\n"))


if __name__ == "__main__":
    unittest.main()
