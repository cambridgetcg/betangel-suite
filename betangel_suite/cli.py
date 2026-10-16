"""bin/suite commands (DESIGN.md 3.4). Built: test and vendor (Phase 0a), serve, open and stop (Phase 0b);
every other command refuses with not_implemented.

bin/_launch.py has already armed the guard, checked TMPDIR and, for every command except stop and vendor,
checked the run marker before main() is called (test is checked too: Nuance's answer to Q-N14). main()
checks the command's arguments first, then creates TMPDIR (0700, through the writer helper) before any
handler runs (DESIGN.md 3.6, 6.8), so SQLite never falls back to a system temp directory. vendor and stop
are the exceptions: vendor must work before the deps clone exists and never imports upstream (which the
writer helper's path_guard needs); stop only talks to the control socket. Neither makes temporary files.
Output is codes and counts only.

    serve [--port N]   the engine in synthetic mode on 127.0.0.1 (config port; N = 0 picks a free port);
                       prints "serving port=<n>", never a bootstrap code or token
    open [--port N]    start the engine and hand one bootstrap URL to /usr/bin/open (the URL is never
                       printed), or, with an engine running, take it over through the control socket
    stop               ask a running engine to stop through the control socket; prints stopped or not_running

serve, open and stop import socket and http only inside their handlers, so no other command loads them.
"""

import importlib.util
import os
import sys
import time

from . import guard, roots
from .errors import SuiteError

COMMANDS = ("serve", "open", "ssh-session", "stop", "catalogue", "selfcheck", "diagnose", "ledger-summary",
            "release", "test", "uisnap", "vendor")
# Adaptation E. stop only reduces activity (DESIGN 3.9 rule 6). vendor starts no engine and writes nothing
# under ~/betangel-data. test refuses during a run like the other commands (Nuance's answer to Q-N14).
NO_RUN_MARKER_CHECK = ("stop", "vendor")
NO_TMPDIR = ("stop", "vendor")                    # they create no temporary files and must not need upstream
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
    parser = _PARSERS.get(command)
    if parser is not None:
        args = parser(args)                     # argument errors refuse before anything is created
    if command not in NO_TMPDIR:
        roots.ensure_dir(roots.tmp_dir(command))
    return handler(args)


def parse_port_args(args):
    """{"port": None or int} for `[--port N]`: N is 0 (a free port, for tests) or 1024-65535."""
    args = list(args)
    port = None
    if args:
        if len(args) != 2 or args[0] != "--port" or not args[1].isascii() or not args[1].isdigit() or len(args[1]) > 5:
            raise SuiteError("bad_arguments")
        port = int(args[1])
        if port != 0 and not 1024 <= port <= 65535:
            raise SuiteError("bad_arguments")
    return {"port": port}


def parse_no_args(args):
    if args:
        raise SuiteError("bad_arguments")
    return {}


def _serve(options):
    return _run_engine("serve", options)


def _open(options):
    return _run_engine("open", options)


def _run_engine(command, options):
    from . import config
    from .api import server         # here, not at the top: no other command loads socket or http
    cfg = config.load()
    port = cfg["port"] if options["port"] is None else options["port"]
    return server.run(cfg, command=command, port=port)


def _stop(options):
    from .api import control        # here, not at the top: no other command loads socket
    return control.stop_main()


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


_HANDLERS = {"test": _test, "vendor": _vendor, "serve": _serve, "open": _open, "stop": _stop}
_PARSERS = {"serve": parse_port_args, "open": parse_port_args, "stop": parse_no_args}
