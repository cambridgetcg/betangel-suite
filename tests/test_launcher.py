"""I-14 and the launcher (DESIGN.md 3.6): fixed interpreters, SSH checks before env -i, codes only.

Nothing here runs suite code on /opt/homebrew/bin/python3 (3.15, frozen for Nuance's certification): the
3.15 refusal is tested on the version predicate itself, and the prologue's old-grammar parse shows the
refusal is reached before anything newer is needed.
"""

import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time
import types
import unittest
from unittest import mock

from betangel_suite import cli, guard, pin, roots
from betangel_suite.errors import SuiteError
import tests
from tests import (PRELUDE, PYTHON, ROOT, child_env, make_home, run_python, run_relayed, run_suite, stand_in_marker,
                   tree_listing)
from tests import test_runmarker

LAUNCH_PY = os.path.join(ROOT, "bin", "_launch.py")
SSH = "192.0.2.10 50000 192.0.2.20 22"         # TEST-NET addresses: the checks only test presence


def load_launch():
    spec = importlib.util.spec_from_file_location("suite_launch_under_test", LAUNCH_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_launch(args, env, home):
    return subprocess.run([PYTHON, "-I", "-S", "-B", LAUNCH_PY, *args], env=env, cwd=home, capture_output=True,
                          text=True, timeout=60)


class InterpreterPolicyTests(unittest.TestCase):

    def test_only_3_13_and_the_3_11_floor_are_allowed(self):
        # 3.12 is not installed on the lab, so it would be an untested interpreter (DESIGN.md 3.6).
        launch = load_launch()
        for version in ((3, 15, 0), (3, 14, 1), (3, 12, 0), (3, 10, 14), (3, 9, 6), (2, 7, 18), (4, 0, 0)):
            self.assertFalse(launch.interpreter_ok(version), version)
        for version in ((3, 11, 17), (3, 13, 16)):
            self.assertTrue(launch.interpreter_ok(version), version)
        self.assertEqual(launch.ALLOWED_VERSIONS, guard.ALLOWED_VERSIONS)

    def test_prologue_parses_with_old_grammar_and_checks_first(self):
        with open(LAUNCH_PY, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, feature_version=(3, 8))
        top_imports = [alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names]
        self.assertEqual(top_imports, ["os", "sys"])
        self.assertFalse([node for node in tree.body if isinstance(node, ast.ImportFrom)])
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        first_two = [ast.unparse(node.test) for node in main.body[:2]]
        self.assertEqual(first_two, ["not interpreter_ok(sys.version_info)", "not flags_ok(sys.flags)"])

    def test_launcher_names_only_the_two_absolute_interpreters(self):
        with open(os.path.join(ROOT, "bin", "suite"), encoding="utf-8") as handle:
            text = handle.read()
        prefix = "/opt/homebrew/bin/"
        found = []
        for match in re.finditer(r"python", text):
            version = re.match(r"3\.1[13](?![0-9])", text[match.end():])
            self.assertEqual(text[match.start() - len(prefix):match.start()], prefix)
            self.assertIsNotNone(version)
            found.append(version.group(0))
        self.assertEqual(sorted(set(found)), ["3.11", "3.13"])
        self.assertIn("exec /usr/bin/env -i ", text)
        self.assertIn('"$PY" -I -S -B "$ROOT/bin/_launch.py" "$@"', text)

    def test_launch_flags_are_required(self):
        launch = load_launch()
        self.assertTrue(launch.flags_ok(types.SimpleNamespace(isolated=1, no_site=1, dont_write_bytecode=1)))
        for missing in ("isolated", "no_site", "dont_write_bytecode"):
            flags = dict(dict(isolated=1, no_site=1, dont_write_bytecode=1), **{missing: 0})
            self.assertFalse(launch.flags_ok(types.SimpleNamespace(**flags)), missing)
        # End to end, never without -S (site would run Homebrew's .pth files in the child).
        home = make_home(self)
        for flags in (("-I", "-S"), ("-S", "-B")):
            returncode, _out, err = run_relayed([PYTHON, *flags, LAUNCH_PY, "selfcheck"], child_env(home), home)
            self.assertEqual((returncode, err), (2, "refused:launch_flags\n"), flags)

    def test_guard_mode_is_engine_for_every_command_but_test_vendor_uisnap_release_and_stop(self):
        # uisnap and stop have modes of their own, so that neither is given the suite root (Nuance's re-review of #2,
        # Q2 conditions 2 and 3; Astra's re-review of #2 found uisnap mapped to engine mode); release (phase0/viewing)
        # has its own, which writes only the release copies.
        self.assertEqual(cli.OWN_MODE_COMMANDS, ("test", "vendor", "uisnap", "release", "stop"))
        self.assertLessEqual(set(cli.OWN_MODE_COMMANDS), set(guard.MODES))
        for command in cli.COMMANDS:
            expected = command if command in ("test", "vendor", "uisnap", "release", "stop") else "engine"
            self.assertEqual(cli.guard_mode(command), expected, command)
        for other in ("", "frobnicate", "Test", "vendor ", "STOP", "uisnap "):
            self.assertEqual(cli.guard_mode(other), "engine", other)

    def test_launcher_arms_the_mode_of_the_command_first(self):
        # _launch.main arms the guard with cli.guard_mode(command) before any other betangel_suite call.
        with open(LAUNCH_PY, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        tries = [node for node in main.body if isinstance(node, ast.Try)]
        self.assertEqual(len(tries), 1)
        self.assertEqual(ast.unparse(tries[0].body[0]), "guard.arm(cli.guard_mode(command))")
        before = main.body[:main.body.index(tries[0])]
        for node in ast.walk(ast.Module(body=before, type_ignores=[])):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(ast.unparse(node.func.value), ("cli", "errors", "guard", "config", "roots", "runmarker"),
                                 ast.unparse(node))

    def test_py311_flag_must_match_the_interpreter(self):
        self.assertEqual(cli.parse_test_args(["--py311", "-v", "-k", "guard"], (3, 11, 17)),
                         (2, "guard", "fast", cli.TEST_JOBS))
        self.assertEqual(cli.parse_test_args([], (3, 13, 16)), (1, None, "fast", cli.TEST_JOBS))
        self.assertEqual(cli.parse_test_args(["--heavy", "-j", "1"], (3, 13, 16)), (1, None, "heavy", 1))
        self.assertEqual(cli.parse_test_args(["--py311", "-j", "4", "--heavy"], (3, 11, 0)), (1, None, "heavy", 4))
        for args, version in ((["--py311"], (3, 13, 16)), ([], (3, 11, 17)), (["-k"], (3, 13, 0)),
                              (["-x"], (3, 13, 0)), (["-v", "-v"], (3, 13, 0)), (["-v", "--py311"], (3, 11, 0)),
                              (["-k", "-v"], (3, 13, 0)), (["--heavy", "--heavy"], (3, 13, 0)), (["-j"], (3, 13, 0)),
                              (["-j", "0"], (3, 13, 0)), (["-j", "5"], (3, 13, 0)), (["-j", "2", "-j", "2"], (3, 13, 0)),
                              (["-j", "x"], (3, 13, 0)), (["--heavy=1"], (3, 13, 0))):
            with self.assertRaises(SuiteError, msg=args) as caught:
                cli.parse_test_args(args, version)
            self.assertEqual(caught.exception.code, "bad_arguments")


class LauncherTests(unittest.TestCase):

    def suite(self, home, *args, **env):
        result = run_suite(list(args), home, env=child_env(home, **env))
        return result.returncode, result.stdout, result.stderr

    def test_unbuilt_commands_refuse_and_write_nothing(self):
        # serve, open and stop are built (Phase 0b): they are never run here without arguments, because a bare
        # serve would bind the configured port and a bare open would start an engine and call /usr/bin/open.
        home = make_home(self)
        before = tree_listing(home)
        for command in cli.COMMANDS:
            if command in ("test", "vendor", "serve", "open", "stop", "release", "ssh-session", "uisnap"):
                continue                # ssh-session (Phase 0c): tests/test_session_process.py; uisnap: tests/test_uisnap.py
            env = {"SSH_CONNECTION": SSH} if command == "ssh-session" else {}
            self.assertEqual(self.suite(home, command, **env), (2, "", "refused:not_implemented\n"), command)
        # release is built (Phase 0c, tests/test_release.py): without its tag it refuses before anything else.
        self.assertEqual(self.suite(home, "release"), (2, "", "refused:bad_arguments\n"))
        self.assertEqual(tree_listing(home), before)

    def test_unknown_and_missing_commands(self):
        home = make_home(self)
        self.assertEqual(self.suite(home), (2, "", "refused:no_command\n"))
        self.assertEqual(self.suite(home, "frobnicate"), (2, "", "refused:unknown_command\n"))
        self.assertEqual(self.suite(home, "selfcheck", "--py311"), (2, "", "refused:not_implemented\n"))

    def test_ssh_checks_run_before_env_i(self):
        home = make_home(self)
        # open runs below; with no deps clone in this HOME, any check that let it through would stop at
        # deps_missing before the engine or /usr/bin/open.
        self.assertFalse(os.path.lexists(pin.deps_dir(pin.load(), home)))
        self.assertEqual(self.suite(home, "ssh-session"), (2, "", "refused:ssh_session_outside_ssh\n"))
        self.assertEqual(self.suite(home, "ssh-session", SSH_CONNECTION=SSH, SSH_ORIGINAL_COMMAND="ls"),
                         (2, "", "refused:ssh_original_command\n"))
        for command in ("open", "serve"):
            self.assertEqual(self.suite(home, command, SSH_CONNECTION=SSH), (2, "", "refused:open_over_ssh\n"))
            self.assertEqual(self.suite(home, command, "--no-such-option"), (2, "", "refused:bad_arguments\n"))
        self.assertEqual(self.suite(home, "selfcheck", "--print-url", SSH_CONNECTION=SSH),
                         (2, "", "refused:print_url_over_ssh\n"))
        self.assertEqual(self.suite(home, "selfcheck", "--print-url"), (2, "", "refused:not_implemented\n"))

    def test_env_i_drops_stray_and_python_variables(self):
        home = make_home(self)
        decoy = os.path.join(home, "decoy")
        os.makedirs(os.path.join(decoy, "betangel_suite"))
        with open(os.path.join(decoy, "betangel_suite", "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("raise SystemExit('decoy imported')\n")
        env = child_env(home, BETFAIR_APP_KEY="x", BETANGEL_BETFAIR_PROFILE="x", PYTHONPATH=decoy,
                        PYTHONHOME=decoy, PYTHONSTARTUP=os.path.join(decoy, "x.py"))
        returncode, out, err = run_relayed(["/bin/sh", os.path.join(ROOT, "bin", "suite"), "selfcheck"], env, home)
        self.assertEqual((returncode, out, err), (2, "", "refused:not_implemented\n"))

    def test_tmpdir_must_match_roots(self):
        home = make_home(self)
        other = os.path.join(home, ".local", "state", "betangel-suite", "other-tmp")
        result = run_launch(["selfcheck"], child_env(home, TMPDIR=other, SQLITE_TMPDIR=other), home)
        self.assertEqual((result.returncode, result.stderr), (2, "refused:tmpdir_mismatch\n"))

    def test_runs_at_the_maximum_niceness(self):
        # os.nice(10) fails with EPERM-like errors at niceness 20; the launcher carries on.
        home = make_home(self)
        returncode, out, err = run_relayed(["/usr/bin/nice", "-n", "20", "/bin/sh", os.path.join(ROOT, "bin", "suite"),
                                            "selfcheck"], child_env(home), home)
        self.assertEqual((returncode, out, err), (2, "", "refused:not_implemented\n"))

    def test_main_creates_tmpdir_0700_before_any_handler(self):
        # DESIGN.md 3.6 and 6.8: TMPDIR exists before a command does any work, so SQLite never falls back to a
        # system temp directory. A stand-in handler reports what it finds, in a fresh engine-mode child. With
        # the suite root agreed (the default since Q-N3) TMPDIR is its tmp/, made with the suite root itself;
        # with the flag off it is the state root's tmp/, and ~/betangel-data stays empty.
        for agreed in (True, False):
            home = make_home(self, deps=True)
            os.makedirs(roots.data_home(home), mode=0o700)      # a synthetic ~/betangel-data in the temporary HOME
            with mock.patch.object(roots, "STATE_ROOT_AGREED", agreed):
                tmp = roots.tmp_dir("selfcheck", home)
            if not agreed:
                os.rmdir(tmp)
            code = PRELUDE + (
                "from betangel_suite import roots\nroots.STATE_ROOT_AGREED = %r\n"
                "from betangel_suite import guard\nguard.arm('engine')\n"
                "import os, stat\nfrom betangel_suite import cli\n"
                "def handler(args):\n"
                "    info = os.lstat(os.environ['TMPDIR'])\n"
                "    print(stat.S_ISDIR(info.st_mode), oct(stat.S_IMODE(info.st_mode)))\n"
                "    return 0\n"
                "cli._HANDLERS['selfcheck'] = handler\n"
                "sys.exit(cli.main(['selfcheck']))\n") % agreed
            result = run_python(code, home, env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "True 0o700\n", ""), agreed)
            listing = [(path, mode) for path, mode in tree_listing(roots.data_home(home))]
            self.assertEqual(listing, [("suite.noindex", 0o700), ("suite.noindex/tmp", 0o700)] if agreed else [], agreed)

    def test_vendor_creates_no_tmpdir(self):
        home = make_home(self)
        os.rmdir(roots.tmp_dir("vendor", home))
        self.assertEqual(run_suite(["vendor"], home).stderr, "refused:bad_arguments\n")
        self.assertFalse(os.path.lexists(roots.tmp_dir("vendor", home)))


class StateRootFlagTests(unittest.TestCase):
    """Adaptation A in both settings, in a child whose roots.STATE_ROOT_AGREED is set before _launch.main.

    The flag is on since Q-N3: roots.py and bin/suite's default TMP branch changed together. Each setting
    accepts only its own TMPDIR for an engine command, so a half flip either way fails closed.
    """

    def launch(self, home, agreed, tmp, *args):
        code = (PRELUDE + "import importlib.util\nfrom betangel_suite import roots\nroots.STATE_ROOT_AGREED = %r\n"
                "spec = importlib.util.spec_from_file_location('launch_under_test', %r)\n"
                "launch = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(launch)\n"
                "sys.exit(launch.main(%r))\n") % (agreed, LAUNCH_PY, list(args))
        result = run_python(code, home, env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp))
        return result.returncode, result.stderr

    def test_half_flip_is_refused(self):
        home = make_home(self)
        os.makedirs(roots.data_home(home), mode=0o700)
        state_tmp = roots.tmp_dir("test", home)
        suite_tmp = os.path.join(roots.suite_root(home), "tmp")
        self.assertEqual(self.launch(home, True, state_tmp, "selfcheck"), (2, "refused:tmpdir_mismatch\n"))
        self.assertEqual(self.launch(home, False, suite_tmp, "selfcheck"), (2, "refused:tmpdir_mismatch\n"))
        self.assertEqual(os.listdir(roots.data_home(home)), [])

    def test_full_flip_uses_the_suite_root_tmp(self):
        home = make_home(self)
        os.makedirs(roots.data_home(home), mode=0o700)
        suite_tmp = os.path.join(roots.suite_root(home), "tmp")
        state_tmp = roots.tmp_dir("test", home)
        self.assertEqual(self.launch(home, True, suite_tmp, "selfcheck"), (2, "refused:not_implemented\n"))
        self.assertEqual(self.launch(home, False, state_tmp, "selfcheck"), (2, "refused:not_implemented\n"))
        for agreed in (True, False):
            self.assertEqual(self.launch(home, agreed, state_tmp, "vendor"), (2, "refused:bad_arguments\n"), agreed)
        self.assertEqual(os.listdir(roots.data_home(home)), [])

    def test_bin_suite_matches_the_flag(self):
        # The shell cannot read roots.py, so its TMP branches are pinned here; _launch.py refuses a mismatch.
        state = "|".join(roots.STATE_TMP_COMMANDS) + ")"
        with open(os.path.join(ROOT, "bin", "suite"), encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip().startswith((state, "*)"))]
        self.assertEqual(lines, [state + ' TMP="$HOME/.local/state/betangel-suite/tmp" ;;',
                                 '*)                               TMP="$HOME/betangel-data/suite.noindex/tmp" ;;'])
        self.assertEqual(roots.STATE_TMP_COMMANDS, ("test", "uisnap", "release", "vendor", "stop"))
        self.assertIs(roots.STATE_ROOT_AGREED, True)


class ParallelRunnerTests(unittest.TestCase):
    """bin/suite test's worker interpreters (cli._run_workers, cli.test_worker): whole modules in children of the
    runner (the guard's runner_argv_ok), each module's output, then one summary in unittest's words. The workers
    check the runner's real marker (tests.RUN_MARKER), or a stand-in for it (tests.stand_in_marker)."""

    def run_workers(self, modules, count, pattern=None):
        """(passed, output); the run must not have stopped for the marker."""
        passed, stopped, output = self.run_workers_with_marker(modules, count, pattern)
        self.assertIsNone(stopped, output)
        return passed, output

    def run_workers_with_marker(self, modules, count, pattern=None):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            passed, stopped = cli._run_workers(modules, count, 1, pattern, tests.RUN_MARKER)
            return passed, stopped, sys.stderr.getvalue()
        finally:
            sys.stderr = saved

    def test_no_module_goes_to_a_worker_while_the_marker_exists(self):
        # Nuance's PR #4 review, item 14: a run announced while the tests run starts no further module.
        for present, state in ((True, "present"), (False, "unreadable")):
            with self.subTest(present=present):
                stand_in_marker(self, present)
                passed, stopped, output = self.run_workers_with_marker(["tests.test_layout", "tests.test_roots"], 2)
                self.assertEqual((passed, stopped), (False, state))
                self.assertRegex(output, r"\nRan 0 tests in [0-9.]+s \(2 modules, 2 workers\)\n\nFAILED\n\Z")
                self.assertNotIn("worker_failed", output)

    def test_a_worker_checks_the_marker_before_each_module(self):
        # A module sent just before the marker appeared is answered without running a test.
        stand_in_marker(self, True)
        worker = subprocess.run([PYTHON, "-I", "-S", "-B", "-c", cli._WORKER, ROOT, "fast", "1", "", tests.RUN_MARKER],
                                input=b"tests.test_layout\n", capture_output=True, timeout=120)
        self.assertEqual(worker.returncode, 0, worker.stderr[-2000:])
        answer = json.loads(worker.stdout.decode("utf-8"))
        self.assertEqual((answer["module"], answer["run"], answer["ok"], answer["run_marker"]),
                         ("tests.test_layout", 0, False, "present"))

    def test_a_worker_stops_a_module_before_its_next_test_once_the_marker_appears(self):
        # Nuance's answers to Q-N14 in a worker: a module that is running when the marker appears starts no further
        # test (cli.marker_stop_result, which test_worker uses), and its answer says why. The worker runs under a
        # temporary HOME holding test_runmarker's probe sentinel, with that HOME's marker: the first probe test waits
        # for the marker, which this test makes once the probe has started; the second must never start.
        home = make_home(self, deps=True)
        open(os.path.join(home, test_runmarker.PROBE_SENTINEL), "w").close()
        marker = test_runmarker.marker(home)
        os.makedirs(os.path.dirname(marker))
        tmp = roots.tmp_dir("test", home)
        argv = [PYTHON, "-I", "-S", "-B", "-c", cli._WORKER, ROOT, "fast", "1", "mid_run_probe", marker]
        worker = subprocess.Popen(argv, env=child_env(home), cwd=home, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        self.addCleanup(lambda: worker.poll() is None and (worker.kill(), worker.communicate()))
        worker.stdin.write(b"tests.test_runmarker\n")
        worker.stdin.flush()                    # communicate() closes stdin below (3.11's flushes it first)
        deadline = time.monotonic() + 60
        while not os.path.exists(os.path.join(tmp, "probe-1-started")):
            if worker.poll() is not None or time.monotonic() > deadline:
                self.fail("the first probe never started: exit=%r" % worker.poll())
            time.sleep(0.05)
        open(marker, "w").close()
        out, err = worker.communicate(timeout=120)
        self.assertEqual(worker.returncode, 0, err[-2000:])
        answer = json.loads(out.decode("utf-8"))
        self.assertEqual((answer["module"], answer["run"], answer["ok"], answer["run_marker"]),
                         ("tests.test_runmarker", 1, False, "present"))
        self.assertEqual((answer["failures"], answer["errors"]), (0, 0))
        self.assertFalse(os.path.exists(os.path.join(tmp, "probe-2-started")))

    def test_modules_run_whole_in_workers_with_one_summary(self):
        modules = ["tests.test_layout", "tests.test_roots"]
        count = unittest.TestLoader().loadTestsFromNames(modules).countTestCases()
        passed, output = self.run_workers(modules, 2)
        self.assertTrue(passed, output)
        self.assertRegex(output, r"\nRan %d tests in [0-9.]+s \(2 modules, 2 workers\)\n\nOK\n\Z" % count)

    def test_a_failing_module_fails_the_run_and_a_pattern_narrows_it(self):
        passed, output = self.run_workers(["tests.test_layout", "tests.test_no_such_module"], 2)
        self.assertFalse(passed)
        self.assertRegex(output, r"\nFAILED \(errors=1\)\n\Z")
        passed, output = self.run_workers(["tests.test_layout", "tests.test_roots"], 2, pattern="zzz_no_such_test")
        self.assertTrue(passed, output)
        self.assertRegex(output, r"\nRan 0 tests in [0-9.]+s \(2 modules, 2 workers\)\n\nOK\n\Z")

    def test_the_modules_of_a_suite(self):
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromNames(["tests.test_roots", "tests.test_layout"])
        self.assertEqual(cli._test_modules(suite), ["tests.test_roots", "tests.test_layout"])
        self.assertEqual(cli._test_modules(unittest.TestSuite()), [])
        stray = unittest.FunctionTestCase(lambda: None)        # a test from outside tests.*: the run stays serial
        self.assertIsNone(cli._test_modules(unittest.TestSuite([suite, stray])))


if __name__ == "__main__":
    unittest.main()
