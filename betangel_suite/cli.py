"""bin/suite commands (DESIGN.md 3.4). Phase 0a implements test and vendor; every other command refuses.

bin/_launch.py has already armed the guard, checked TMPDIR and, for every command except stop, checked
the run marker before main() is called. main() then, for a command that may touch real data (REALDATA_COMMANDS),
takes the realdata lock shared and checks the marker again under it (runmarker.hold_shared; DESIGN.md 6.8), and
only then creates TMPDIR (0700, through the writer helper) before any handler runs (DESIGN.md 3.6), so SQLite
never falls back to a system temp directory. stop and vendor (NO_TMPDIR) are the exceptions: neither makes
temporary files. stop must work during a run, so it needs neither TMPDIR nor the lock; vendor must work before the
deps clone exists and never imports upstream (which the writer helper's path_guard needs). Output is codes and
counts only.
"""

import importlib.util
import os
import sys
import time

from . import guard, roots
from .errors import SuiteError

COMMANDS = ("serve", "open", "ssh-session", "stop", "catalogue", "selfcheck", "diagnose", "ledger-summary",
            "release", "test", "uisnap", "vendor")
# Adaptation E. stop only reduces activity (DESIGN 3.9 rule 6), so only stop skips the check. test and vendor
# refuse during a run like the other commands (Nuance's answers to Q-N14: "stop stays exempt", and "test and
# vendor refuse under the marker").
NO_RUN_MARKER_CHECK = ("stop",)
# The commands that may read a real data root or write under ~/betangel-data. Each takes LOCK_SH on run/realdata.lock
# before its TMPDIR is created, checks the marker again under the lock and holds it until it exits, so Nuance's
# wrapper, which takes LOCK_EX, waits for it (Nuance's PR #2 review, item 6; PR #1 review, item 5). test, uisnap and
# vendor touch neither and do not take it; stop must work during a run and takes nothing (runmarker.py says why).
# main() refuses (run_lock_not_held) any other command whose TMPDIR would be made under ~/betangel-data.
REALDATA_COMMANDS = ("serve", "open", "ssh-session", "catalogue", "selfcheck", "diagnose", "ledger-summary")
# They create no temporary files, so main() makes no TMPDIR for them and never asks them for the lock. stop must work
# during a run (DESIGN.md 6.8); without this, its TMPDIR under ~/betangel-data made main() refuse it with
# run_lock_not_held (round-4 review). phase0/http has the same tuple and phase0/viewing adds release: merged into
# them, the run_lock_not_held check stays inside the `not in NO_TMPDIR` branch.
NO_TMPDIR = ("stop", "vendor")
REPO_ROOT = guard.REPO_ROOT


def guard_mode(command):
    """The guard mode a command runs in; chosen by command name only."""
    return command if command in ("test", "vendor") else "engine"


def main(argv):
    """Run one command; return the process exit status (0 success, 1 test failure, 2 refusal)."""
    if not argv:
        raise SuiteError("no_command")
    command, args = argv[0], argv[1:]
    if command not in COMMANDS:
        raise SuiteError("unknown_command")
    handler = _HANDLERS.get(command)
    if handler is None:
        raise SuiteError("not_implemented")
    guard.require_mode(guard_mode(command))
    from . import runmarker
    if command in REALDATA_COMMANDS:
        from . import config
        runmarker.hold_shared(runmarker.marker_path(config.load()), runmarker.lock_path())
    if command not in NO_TMPDIR:
        tmp = roots.tmp_dir(command)
        if roots.within(tmp.casefold(), roots.data_home().casefold()) and not runmarker.holding():
            raise SuiteError("run_lock_not_held")       # nothing is made under ~/betangel-data without the lock
        roots.ensure_dir(tmp)
    return handler(args)


def parse_test_args(args, version):
    """(verbosity, name pattern or None) for `test [--py311] [-v] [-k PATTERN]`.

    --py311 is read by bin/suite to pick /opt/homebrew/bin/python3.11; here it must agree with the
    interpreter actually running, so the flag can never be silently ignored.
    """
    args = list(args)
    py311 = bool(args) and args[0] == "--py311"
    if py311:
        args.pop(0)
    if py311 != (tuple(version[:2]) == (3, 11)):
        raise SuiteError("bad_arguments")
    verbosity, pattern = 1, None
    while args:
        item = args.pop(0)
        if item == "-v" and verbosity == 1:
            verbosity = 2
        elif item == "-k" and pattern is None and args and args[0] and not args[0].startswith("-"):
            pattern = args.pop(0)
        else:
            raise SuiteError("bad_arguments")
    return verbosity, pattern


def _test(args):
    import unittest
    from . import config, runmarker
    verbosity, pattern = parse_test_args(args, sys.version_info)
    from . import rx    # noqa: F401  (verifies the pin and imports upstream under the armed guard)
    marker = runmarker.marker_path(config.load())
    before = state_listing()
    started = time.monotonic()
    loader = unittest.TestLoader()
    if pattern is not None:
        loader.testNamePatterns = ["*" + pattern + "*"]
    tests = loader.discover(start_dir=os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    resultclass = marker_stop_result(unittest.TextTestResult, marker)
    result = unittest.TextTestRunner(verbosity=verbosity, resultclass=resultclass).run(tests)
    sys.stderr.write("runtime_s=%.1f python=%d.%d\n" % (time.monotonic() - started, *sys.version_info[:2]))
    if state_listing() != before:
        # Tests write only under TMPDIR: anything new elsewhere in the real state root (the install salt,
        # say) means a test escaped its temporary HOME.
        sys.stderr.write("refused:state_root_changed\n")
        return 1
    if result.run_marker is not None:
        sys.stderr.write("refused:run_marker_%s\n" % result.run_marker)
        return 2
    return 0 if result.wasSuccessful() else 1


def marker_stop_result(base, path):
    """A unittest result class (a subclass of base) that ends the run before its next test once the run marker at
    path is present or cannot be checked (Nuance's PR #4 review, item 14; DESIGN.md 6.8).

    bin/_launch.py checks the marker once, before the run. This checks it again after every test, so a run that
    Nuance announces while the tests run starts no further test. A test that is running when the marker appears
    still runs to its end, with anything it started. run_marker says why the run stopped (None: it did not), and a
    stopped run is never successful, even when every test it ran passed.
    """
    from . import runmarker

    class MarkerStopResult(base):
        run_marker = None

        def stopTest(self, test):
            super().stopTest(test)
            if self.run_marker is None:
                self.run_marker = runmarker.state(path)
                if self.run_marker is not None:
                    self.stop()

        def wasSuccessful(self):
            return self.run_marker is None and super().wasSuccessful()

    return MarkerStopResult


def state_listing(home_dir=None):
    """Sorted (relative path, is directory) under the state root, its tmp/ excluded (no contents read)."""
    top = roots.state_dir(home_dir)
    found = []
    for directory, dirs, files in os.walk(top):
        if directory == top:
            dirs[:] = [name for name in dirs if name != "tmp"]
        found += [(os.path.relpath(os.path.join(directory, name), top), name in dirs) for name in dirs + files]
    return sorted(found)


def _vendor(args):
    path = os.path.join(REPO_ROOT, "tools", "vendor_research.py")
    spec = importlib.util.spec_from_file_location("betangel_suite_vendor_research", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(args)


_HANDLERS = {"test": _test, "vendor": _vendor}
