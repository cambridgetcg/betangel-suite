"""bin/suite commands (DESIGN.md 3.4). Built: test and vendor (Phase 0a), serve, open and stop (Phase 0b),
ssh-session, uisnap and release (Phase 0c); catalogue, selfcheck, diagnose and ledger-summary refuse with
not_implemented.

bin/_launch.py has already armed the guard, checked TMPDIR and, for every command except stop and vendor,
checked the run marker before main() is called (test is checked too: Nuance's answer to Q-N14). main()
checks the command's arguments first, then creates TMPDIR (0700, through the writer helper) before any
handler runs (DESIGN.md 3.6, 6.8), so SQLite never falls back to a system temp directory. vendor and stop
are the exceptions: vendor must work before the deps clone exists and never imports upstream (which the
writer helper's path_guard needs); stop only talks to the control socket. Neither makes temporary files.
release is the third: it writes only the release copy (guard mode release) and never needs upstream.
Output is codes and counts only.

    serve [--port N]   the engine in synthetic mode on 127.0.0.1 (config port; N = 0 picks a free port);
                       prints "serving port=<n>", never a bootstrap code or token
    open [--port N]    start the engine and hand one bootstrap URL to /usr/bin/open (the URL is never
                       printed), or, with an engine running, take it over through the control socket
    open [--port N] --print-url
                       the same, but the URL goes to stdout instead of /usr/bin/open, for Yu to paste into a
                       Safari Private window (Phase 0c; DESIGN.md 3.6, 8.6 item 1; agents never run it)
    ssh-session [--port N]
                       the viewer key's forced command (Phase 0c; DESIGN.md 8.6 item 2, I-19; only with
                       SUITE_VIA_SSH=1 from bin/suite): start the engine, or take the running one over, and
                       print a single-use URL on this SSH session's stdout, a fresh one per Enter
                       (betangel_suite/api/sshsession.py; agents never run it). Without --port only on 8765,
                       the viewer key's port: any other config or engine port is viewer_port_mismatch
    stop               ask a running engine to stop through the control socket; prints stopped or not_running
    uisnap [--seed N] [--out DIR]
                       PNG snapshots of the UI on a synthetic-only engine (betangel_suite/uisnap.py; guard mode
                       uisnap); prints codes, counts and the PNG paths, never a bootstrap code
    release <tag>      install a read-only release copy of a tag on the local main branch under
                       ~/.local/share/betangel-suite/app/<tag> and switch app/current (betangel_suite/release.py;
                       guard mode release; I-18); prints counts only
    test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]
                       the unittest suite (DESIGN.md 11): the fast tier, plus the heavy tier with --heavy; the test
                       modules run in N worker interpreters (default TEST_JOBS, -j 1 none), whole modules each.
                       Both tiers refuse while the run marker exists (run_marker_present or
                       run_marker_unreadable; Nuance's answer to Q-N14), before any test is loaded

serve, open, ssh-session and stop import socket and http only inside their handlers (test loads the control
socket's module for its engine-lock check), so no other command loads them.
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
NO_TMPDIR = ("stop", "vendor", "release")         # they create no temporary files and must not need upstream
REPO_ROOT = guard.REPO_ROOT
VIA_SSH_ENV = "SUITE_VIA_SSH"                     # set by bin/suite: "1" for ssh-session after its SSH checks, else "0"


def guard_mode(command):
    """The guard mode a command runs in; chosen by command name only."""
    return command if command in ("test", "vendor", "uisnap", "release") else "engine"


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
    check_ssh(command, os.environ.get(VIA_SSH_ENV, ""))
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


def parse_open_args(args):
    """{"port": None or int, "print_url": bool} for `open [--port N] [--print-url]`, in either order."""
    args = list(args)
    print_url = "--print-url" in args
    if print_url:
        args.remove("--print-url")
        if "--print-url" in args:
            raise SuiteError("bad_arguments")
    return dict(parse_port_args(args), print_url=print_url)


def check_ssh(command, via_ssh):
    """bin/suite's SSH checks, once more on the flag it passed through env -i (DESIGN.md 3.6): ssh-session only
    with SUITE_VIA_SSH=1, which bin/suite sets only after its own checks; open and serve never with it."""
    if command == "ssh-session" and via_ssh != "1":
        raise SuiteError("ssh_session_outside_ssh")
    if command in ("open", "serve") and via_ssh not in ("", "0"):
        raise SuiteError("open_over_ssh")


def _serve(options):
    return _run_engine("serve", options)


def _open(options):
    return _run_engine("open", options)


def _run_engine(command, options):
    from . import config
    from .api import server         # here, not at the top: no other command loads socket or http
    cfg = config.load()
    port = cfg["port"] if options["port"] is None else options["port"]
    return server.run(cfg, command=command, port=port, print_url=options.get("print_url", False))


def _ssh_session(options):
    from . import config
    from .api import sshsession     # here, not at the top: no other command loads socket or http
    return sshsession.main(config.load(), port=options["port"])


def _stop(options):
    from .api import control        # here, not at the top: no other command loads socket
    return control.stop_main()


TEST_TIERS = ("fast", "heavy")      # DESIGN.md 11: the fast tier always; --heavy adds the opt-in heavy tests
TEST_JOBS = 3                       # worker interpreters for a run that spans several test modules (-j 1: none)
TEST_JOBS_MAX = 4
_test_tier = "fast"


def test_tier():
    """This run's tier: "heavy" under `bin/suite test --heavy`, else "fast" (tests/__init__.py reads it as HEAVY)."""
    return _test_tier


def parse_test_args(args, version):
    """(verbosity, name pattern or None, tier, jobs) for `test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]`.

    --py311 is read by bin/suite to pick /opt/homebrew/bin/python3.11; here it must agree with the
    interpreter actually running, so the flag can never be silently ignored. --heavy adds the heavy tier's
    tests (TEST_TIERS); -j N runs the test modules in N worker interpreters (1 to TEST_JOBS_MAX, default
    TEST_JOBS; 1 runs everything in this process).
    """
    args = list(args)
    py311 = bool(args) and args[0] == "--py311"
    if py311:
        args.pop(0)
    if py311 != (tuple(version[:2]) == (3, 11)):
        raise SuiteError("bad_arguments")
    verbosity, pattern, tier, jobs = 1, None, "fast", None
    job_counts = [str(count) for count in range(1, TEST_JOBS_MAX + 1)]
    while args:
        item = args.pop(0)
        if item == "-v" and verbosity == 1:
            verbosity = 2
        elif item == "-k" and pattern is None and args and args[0] and not args[0].startswith("-"):
            pattern = args.pop(0)
        elif item == "--heavy" and tier == "fast":
            tier = "heavy"
        elif item == "-j" and jobs is None and args and args[0] in job_counts:
            jobs = int(args.pop(0))
        else:
            raise SuiteError("bad_arguments")
    return verbosity, pattern, tier, TEST_JOBS if jobs is None else jobs


def _test(args):
    import unittest
    global _test_tier
    verbosity, pattern, _test_tier, jobs = parse_test_args(args, sys.version_info)
    from . import rx    # noqa: F401  (verifies the pin and imports upstream under the armed guard)
    from .api import control
    before, running_before = state_listing(), control.engine_running()
    started = time.monotonic()
    tests = _test_loader(pattern).discover(start_dir=os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    modules = _test_modules(tests)
    workers = min(jobs, len(modules or ()))
    if workers > 1:
        passed = _run_workers(modules, workers, verbosity, pattern)
    else:
        workers = 1
        passed = unittest.TextTestRunner(verbosity=verbosity).run(tests).wasSuccessful()
    sys.stderr.write("runtime_s=%.1f python=%d.%d tier=%s jobs=%d\n"
                     % (time.monotonic() - started, *sys.version_info[:2], _test_tier, workers))
    if unexplained_changes(before, state_listing(), running_before, control.engine_running()):
        # Tests write only under TMPDIR: anything new elsewhere in the real state root (the install salt,
        # say) means a test escaped its temporary HOME. Only an engine Yu started or stopped meanwhile is told
        # apart (unexplained_changes).
        sys.stderr.write("refused:state_root_changed\n")
        return 1
    return 0 if passed else 1


def _test_loader(pattern):
    import unittest
    loader = unittest.TestLoader()
    if pattern is not None:
        loader.testNamePatterns = ["*" + pattern + "*"]
    return loader


def _test_modules(suite):
    """The names of the tests.* modules holding the suite's tests, in discovery order; None when a test comes from
    anywhere else (a module that failed to import, say), which runs the whole suite in this process instead."""
    import unittest
    found, pending = [], [suite]
    while pending:
        item = pending.pop()
        if isinstance(item, unittest.TestSuite):
            pending.extend(reversed(list(item)))
            continue
        name = type(item).__module__
        if not name.startswith("tests."):
            return None
        if name not in found:
            found.append(name)
    return found


# A worker of the parallel run: this checkout on sys.path, then cli.test_worker (argv: root, tier, verbosity, pattern).
_WORKER = ("import sys\nsys.path.append(sys.argv[1])\nfrom betangel_suite import cli\n"
           "sys.exit(cli.test_worker(sys.argv[2], int(sys.argv[3]), sys.argv[4] or None))\n")


def _run_workers(modules, count, verbosity, pattern):
    """Run each test module whole in one of count worker interpreters; True when every module passed.

    Each worker is a child of this runner like any test child (this interpreter with -I -S -B, this environment,
    so the same TMPDIR and network switch; the guard's runner_argv_ok), arms its own test-mode guard by importing
    tests, and runs the modules it is sent one at a time: a module's classes and fixtures never split across
    workers. The modules tests.SLOW_FIRST names go first, so no worker is left with a long tail. Each module's
    output is printed when it finishes; then one summary in unittest's own words. The state-root check and the
    runtime line stay with this process.
    """
    import json
    import select
    import subprocess
    hints = tuple(getattr(sys.modules.get("tests"), "SLOW_FIRST", ()))
    pending = sorted(modules, key=lambda name: (hints.index(name) if name in hints else len(hints),
                                                modules.index(name)))
    started = time.monotonic()
    totals = dict.fromkeys(("run", "failures", "errors", "skipped", "expected_failures", "unexpected_successes"), 0)
    passed = True
    busy = {}
    workers = []
    try:
        for _ in range(count):
            worker = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", _WORKER, REPO_ROOT, _test_tier,
                                       str(verbosity), pattern or ""], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            workers.append(worker)

        def assign(worker):
            if pending:
                busy[worker] = pending.pop(0)
                worker.stdin.write((busy[worker] + "\n").encode("ascii"))
                worker.stdin.flush()
            else:
                worker.stdin.close()

        for worker in workers:
            assign(worker)
        while busy:
            for stream in select.select([worker.stdout for worker in busy], [], [])[0]:
                worker = next(item for item in busy if item.stdout is stream)
                module = busy.pop(worker)
                line = stream.readline()
                try:
                    report = json.loads(line.decode("utf-8"))
                except ValueError:
                    report = None
                if not isinstance(report, dict) or report.get("module") != module:
                    sys.stderr.write("\nworker_failed module=%s\n" % module)
                    totals["errors"] += 1
                    passed = False
                    continue                    # this worker is done for; the others carry on
                sys.stderr.write(report["output"])
                sys.stderr.flush()
                for key in totals:
                    totals[key] += report[key]
                passed = passed and report["ok"]
                assign(worker)
        for module in pending:                  # left over only when every worker failed
            sys.stderr.write("worker_failed module=%s\n" % module)
            passed = False
    finally:
        for worker in workers:
            if worker.stdin and not worker.stdin.closed:
                worker.stdin.close()
            try:
                worker.wait(30)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(10)
            worker.stdout.close()
    run = totals["run"]
    sys.stderr.write("-" * 70 + "\nRan %d test%s in %.3fs (%d modules, %d workers)\n\n"
                     % (run, "" if run == 1 else "s", time.monotonic() - started, len(modules), count))
    details = ["%s=%d" % (label, totals[key]) for key, label in (
        ("failures", "failures"), ("errors", "errors"), ("skipped", "skipped"),
        ("expected_failures", "expected failures"), ("unexpected_successes", "unexpected successes")) if totals[key]]
    sys.stderr.write(("OK" if passed else "FAILED") + (" (%s)" % ", ".join(details) if details else "") + "\n")
    return passed


def test_worker(tier, verbosity, pattern):
    """One worker of the parallel run (_run_workers): run the test modules named on stdin, one at a time, and answer
    each with one JSON line of counts and its unittest output. fd 1 is pointed at stderr first, so nothing a test
    or its children print can mix into the answers, which go to a copy of the original stdout."""
    global _test_tier
    import io
    import json
    import unittest
    if tier not in TEST_TIERS:
        raise SuiteError("bad_arguments")
    _test_tier = tier
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    import tests                        # noqa: F401  (arms this process's guard in test mode and the pin)
    loader = _test_loader(pattern)
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        module = line.strip()
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=verbosity)._makeResult()
        result.startTestRun()
        try:
            loader.loadTestsFromName(module)(result)
        finally:
            result.stopTestRun()
        result.printErrors()
        answers.write(json.dumps({
            "module": module, "output": stream.getvalue(), "run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
            "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses), "ok": result.wasSuccessful()}) + "\n")
        answers.flush()


ENGINE_ENTRIES = (("run", True), (os.path.join("run", "engine.lock"), False))
SOCKET_ENTRY = (os.path.join("run", "control.sock"), False)


def unexplained_changes(before, after, running_before, running_after):
    """The state_listing entries that appeared or vanished during a test run, less what a real engine explains.

    Yu may start or stop an engine (serve, open, ssh-session) while an agent's tests run. Its lock (run/engine.lock,
    flock'd while it runs) tells it apart: an engine that holds the lock at the end explains run/, run/engine.lock
    and run/control.sock appearing; one that held it at the start explains run/control.sock vanishing. Nothing
    else is ever explained: any other entry, or those three without a live lock to explain them, still counts.
    """
    before, after = set(before), set(after)
    explained = set()
    if running_after:
        explained |= (after - before) & {*ENGINE_ENTRIES, SOCKET_ENTRY}
    if running_before:
        explained |= (before - after) & {SOCKET_ENTRY}
    return sorted((after ^ before) - explained)


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


def _uisnap(options):
    from . import uisnap            # here, not at the top: no other command loads socket, http or subprocess
    return uisnap.main(options)


def parse_uisnap_args(args):
    from . import uisnap
    return uisnap.parse_args(args)


def _release(options):
    from . import release           # here, not at the top: only release loads tarfile and subprocess
    return release.main(options)


def parse_release_args(args):
    from . import release
    return release.parse_args(args)


_HANDLERS = {"test": _test, "vendor": _vendor, "serve": _serve, "open": _open, "stop": _stop}
_PARSERS = {"serve": parse_port_args, "open": parse_port_args, "stop": parse_no_args}
_HANDLERS["uisnap"] = _uisnap
_PARSERS["uisnap"] = parse_uisnap_args
_HANDLERS["release"] = _release
_PARSERS["release"] = parse_release_args
_PARSERS["open"] = parse_open_args                # Phase 0c: open [--port N] [--print-url]
_HANDLERS["ssh-session"] = _ssh_session
_PARSERS["ssh-session"] = parse_port_args
