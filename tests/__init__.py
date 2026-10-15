"""betangel-suite tests (DESIGN.md section 11). Synthetic only: nothing here reads ~/betangel-data.

Run them with `bin/suite test` (python3.13) or `bin/suite test --py311`. Importing this package arms the
guard in test mode (bin/_launch.py already has, when run through bin/suite) and appends the pinned deps
clone through betangel_suite.pin, so tests may import test-only oracles from betangel_research.

The test-mode guard confines this process's writes to ~/.local/state/betangel-suite (TMPDIR is its tmp/),
refuses all network use, and lets the runner start only isolated interpreters, this checkout's bin/suite
and local git in repositories under TMPDIR (guard.runner_git_ok), each child with the network switch on.
Every audit-hook test runs in a fresh subprocess, because a hook cannot be removed. Each test makes its own
temporary HOME (make_home) under TMPDIR and removes it afterwards; bin/suite test fails the run if anything
in the real state root outside tmp/ changed (cli.state_listing).
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile

from betangel_suite import guard, pin, roots

guard.arm("test")
DEPS = pin.activate()
roots.ensure_dir(os.environ["TMPDIR"])       # guard.arm checked that it lies in the state root

ROOT = guard.REPO_ROOT
LAUNCHER = guard.LAUNCHER
PYTHON = sys.executable
FORBID = guard.FORBID_NETWORK_ENV
PRELUDE = "import sys\nsys.path.append(%r)\n" % ROOT
ARM_ENGINE = PRELUDE + "from betangel_suite import guard\nguard.arm('engine')\n"


def rmtree(path):
    """Remove a test tree, first making read-only directories writable again (vendored copies)."""
    if not os.path.lexists(path):
        return
    for directory, dirs, _files in os.walk(path):
        for name in dirs:
            child = os.path.join(directory, name)
            if not os.path.islink(child):
                os.chmod(child, 0o700)
    os.chmod(path, 0o700)
    shutil.rmtree(path)


def make_home(case, *, deps=False):
    """A temporary HOME with .local/state, .local/share and the state tmp/ (all 0700); removed after case.

    deps=True also copies the pinned files of the real deps clone to the fake home's deps path, so a
    child with this HOME can verify the pin and import betangel_research.
    """
    base = tempfile.mkdtemp(prefix="home-")
    case.addCleanup(rmtree, base)
    home = os.path.join(base, "home")
    for parts in ((".local", "state"), (".local", "share")):
        os.makedirs(os.path.join(home, *parts), mode=0o700)
    os.makedirs(roots.tmp_dir("test", home), mode=0o700)
    if deps:
        target = pin.deps_dir(pin.load(), home)
        for relpath in pin.PINNED_FILES:
            destination = os.path.join(target, relpath)
            os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
            shutil.copyfile(os.path.join(DEPS, relpath), destination)
    return home


def child_env(home, **changes):
    """The environment bin/suite would give a child, for this HOME; a None value removes a key."""
    tmp = roots.tmp_dir("test", home)
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": "en_GB.UTF-8", "TMPDIR": tmp, "SQLITE_TMPDIR": tmp,
           FORBID: "1", "PYTHONDONTWRITEBYTECODE": "1"}
    for key, value in changes.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_python(code, home, *, env=None, flags=("-I", "-S", "-B"), timeout=60):
    """Run code in a fresh interpreter like this one (same version), with this checkout on sys.path."""
    return subprocess.run([PYTHON, *flags, "-c", PRELUDE + code], env=child_env(home) if env is None else env,
                          cwd=home, capture_output=True, text=True, timeout=timeout)


def run_relayed(argv, env, home, *, timeout=60):
    """(returncode, stdout, stderr) of argv run with env by an unguarded relay child.

    The test runner's own guard refuses to start a child with a stray BETFAIR variable or without the
    launcher flags; the refusal tests need exactly such children, so a plain interpreter (which never
    imports betangel_suite) starts them instead.
    """
    code = ("import json, subprocess\n"
            "r = subprocess.run(%r, env=%r, cwd=%r, capture_output=True, text=True, timeout=%d)\n"
            "print(json.dumps([r.returncode, r.stdout, r.stderr]))\n") % (list(argv), dict(env), home, timeout)
    relay = run_python(code, home, timeout=timeout + 30)
    if relay.returncode != 0:
        raise AssertionError("relay failed: " + relay.stderr[-500:])
    return tuple(__import__("json").loads(relay.stdout))


def run_suite(args, home, *, env=None, timeout=120):
    """Run bin/suite through /bin/sh with this HOME (the launcher applies env -i itself)."""
    return subprocess.run(["/bin/sh", LAUNCHER, *args], env=child_env(home) if env is None else env, cwd=home,
                          capture_output=True, text=True, timeout=timeout)


def tree_listing(path):
    """Sorted (relative path, mode) pairs under path, for before/after comparisons."""
    found = []
    for directory, dirs, files in os.walk(path):
        for name in sorted(dirs + files):
            full = os.path.join(directory, name)
            found.append((os.path.relpath(full, path), stat.S_IMODE(os.lstat(full).st_mode)))
    return sorted(found)
