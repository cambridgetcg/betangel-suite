"""I-14 and the launcher (DESIGN.md 3.6): fixed interpreters, SSH checks before env -i, codes only.

Nothing here runs suite code on /opt/homebrew/bin/python3 (3.15, frozen for Nuance's certification): the
3.15 refusal is tested on the version predicate itself, and the prologue's old-grammar parse shows the
refusal is reached before anything newer is needed.
"""

import ast
import importlib.util
import os
import re
import subprocess
import types
import unittest
from unittest import mock

from betangel_suite import cli, guard, roots
from betangel_suite.errors import SuiteError
from tests import PRELUDE, PYTHON, ROOT, child_env, make_home, run_python, run_relayed, run_suite, tree_listing

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

    def test_guard_mode_is_engine_for_every_command_but_test_vendor_uisnap_and_stop(self):
        # uisnap and stop have modes of their own, so that neither is given the suite root (Nuance's re-review of #2,
        # Q2 conditions 2 and 3; Astra's re-review of #2 found uisnap mapped to engine mode).
        self.assertEqual(cli.OWN_MODE_COMMANDS, ("test", "vendor", "uisnap", "stop"))
        self.assertLessEqual(set(cli.OWN_MODE_COMMANDS), set(guard.MODES))
        for command in cli.COMMANDS:
            expected = command if command in ("test", "vendor", "uisnap", "stop") else "engine"
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
        self.assertEqual(cli.parse_test_args(["--py311", "-v", "-k", "guard"], (3, 11, 17)), (2, "guard"))
        self.assertEqual(cli.parse_test_args([], (3, 13, 16)), (1, None))
        for args, version in ((["--py311"], (3, 13, 16)), ([], (3, 11, 17)), (["-k"], (3, 13, 0)),
                              (["-x"], (3, 13, 0)), (["-v", "-v"], (3, 13, 0)), (["-v", "--py311"], (3, 11, 0)),
                              (["-k", "-v"], (3, 13, 0))):
            with self.assertRaises(SuiteError, msg=args) as caught:
                cli.parse_test_args(args, version)
            self.assertEqual(caught.exception.code, "bad_arguments")


class LauncherTests(unittest.TestCase):

    def suite(self, home, *args, **env):
        result = run_suite(list(args), home, env=child_env(home, **env))
        return result.returncode, result.stdout, result.stderr

    def test_unbuilt_commands_refuse_and_write_nothing(self):
        home = make_home(self)
        before = tree_listing(home)
        for command in cli.COMMANDS:
            if command in ("test", "vendor"):
                continue
            env = {"SSH_CONNECTION": SSH} if command == "ssh-session" else {}
            self.assertEqual(self.suite(home, command, **env), (2, "", "refused:not_implemented\n"), command)
        self.assertEqual(tree_listing(home), before)

    def test_unknown_and_missing_commands(self):
        home = make_home(self)
        self.assertEqual(self.suite(home), (2, "", "refused:no_command\n"))
        self.assertEqual(self.suite(home, "frobnicate"), (2, "", "refused:unknown_command\n"))
        self.assertEqual(self.suite(home, "selfcheck", "--py311"), (2, "", "refused:not_implemented\n"))

    def test_ssh_checks_run_before_env_i(self):
        home = make_home(self)
        self.assertEqual(self.suite(home, "ssh-session"), (2, "", "refused:ssh_session_outside_ssh\n"))
        self.assertEqual(self.suite(home, "ssh-session", SSH_CONNECTION=SSH, SSH_ORIGINAL_COMMAND="ls"),
                         (2, "", "refused:ssh_original_command\n"))
        for command in ("open", "serve"):
            self.assertEqual(self.suite(home, command, SSH_CONNECTION=SSH), (2, "", "refused:open_over_ssh\n"))
            self.assertEqual(self.suite(home, command), (2, "", "refused:not_implemented\n"))
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
        # The shell cannot read roots.py, so its default TMP branch is pinned here; _launch.py refuses a mismatch.
        with open(os.path.join(ROOT, "bin", "suite"), encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip().startswith(("test|uisnap|vendor|stop)", "*)"))]
        self.assertEqual(lines, ['test|uisnap|vendor|stop) TMP="$HOME/.local/state/betangel-suite/tmp" ;;',
                                 '*)                       TMP="$HOME/betangel-data/suite.noindex/tmp" ;;'])
        self.assertEqual(roots.STATE_TMP_COMMANDS, ("test", "uisnap", "vendor", "stop"))
        self.assertIs(roots.STATE_ROOT_AGREED, True)


if __name__ == "__main__":
    unittest.main()
