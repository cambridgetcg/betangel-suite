"""bin/suite commands (DESIGN.md 3.4). Phase 0a implements test and vendor; every other command refuses.

bin/_launch.py has already armed the guard, checked TMPDIR and, for every command except test and
vendor, checked the run marker before main() is called. main() then creates TMPDIR (0700, through the
writer helper) before any handler runs (DESIGN.md 3.6, 6.8), so SQLite never falls back to a system temp
directory. vendor is the exception: it must work before the deps clone exists, never imports upstream
(which the writer helper's path_guard needs) and makes no temporary files. Output is codes and counts only.
"""

import importlib.util
import os
import sys
import time

from . import guard, roots
from .errors import SuiteError

COMMANDS = ("serve", "open", "ssh-session", "stop", "catalogue", "selfcheck", "diagnose", "ledger-summary",
            "release", "test", "uisnap", "vendor")
NO_RUN_MARKER_CHECK = ("stop", "test", "vendor")  # adaptation E; stop only reduces activity (DESIGN 3.9 rule 6)
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
    if command != "vendor":
        roots.ensure_dir(roots.tmp_dir(command))
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
    verbosity, pattern = parse_test_args(args, sys.version_info)
    from . import rx    # noqa: F401  (verifies the pin and imports upstream under the armed guard)
    before = state_listing()
    started = time.monotonic()
    loader = unittest.TestLoader()
    if pattern is not None:
        loader.testNamePatterns = ["*" + pattern + "*"]
    tests = loader.discover(start_dir=os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    result = unittest.TextTestRunner(verbosity=verbosity).run(tests)
    sys.stderr.write("runtime_s=%.1f python=%d.%d\n" % (time.monotonic() - started, *sys.version_info[:2]))
    if state_listing() != before:
        # Tests write only under TMPDIR: anything new elsewhere in the real state root (the install salt,
        # say) means a test escaped its temporary HOME.
        sys.stderr.write("refused:state_root_changed\n")
        return 1
    return 0 if result.wasSuccessful() else 1


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
