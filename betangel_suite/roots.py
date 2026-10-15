"""State roots and the single writer helper (DESIGN.md 3.7; Phase 0 adaptations A and B).

Roots, under the home directory taken from $HOME (bin/suite passes the caller's HOME through env -i):

    ~/.local/state/betangel-suite/            0700  config, prefs, run/, tmp/, install-salt (Phase 0)
    ~/.local/share/betangel-suite/deps/       read-only pinned upstream code (written only by the vendor tool)
    ~/betangel-data/suite.noindex/            0700  the suite root, ONLY once STATE_ROOT_AGREED is True

STATE_ROOT_AGREED stays False until Nuance agrees the suite root (Q-N3). While it is False nothing may be
created or written anywhere under ~/betangel-data: the writer helper refuses with state_root_not_agreed
on the path text alone, before touching the file system, and the audit hook (guard.py) refuses the same
writes from any other code. Every command's TMPDIR is then the state root's tmp/. Flipping the flag turns
on the design's behaviour (suite root writable, its tmp/ used by every command except test, uisnap and
vendor). The flip is a two-line reviewed change: this flag and bin/suite's default TMP branch, which a
shell script cannot read from here. The launcher refuses any mismatch between them (tmpdir_mismatch), so
a half-done flip fails closed.

The writer helper creates directories 0700 and files 0600 with O_CREAT|O_EXCL|O_NOFOLLOW, never follows a
symlink below a root, refuses any path outside the roots, and passes each new path through upstream's
path_guard.guard_path (through rx, imported only when a write happens). Before it creates or enters the
suite root it runs the root through upstream archive.check_data_root (DESIGN.md 3.7: outside the repository
and every Git worktree).
"""

import os
import stat

from .errors import SuiteError

STATE_ROOT_AGREED = False           # Q-N3 / R-4: flip with bin/suite's TMP line once Nuance agrees

DATA_HOME_PARTS = ("betangel-data",)
SUITE_ROOT_PARTS = ("betangel-data", "suite.noindex")
STATE_DIR_PARTS = (".local", "state", "betangel-suite")
SHARE_DIR_PARTS = (".local", "share", "betangel-suite")
STATE_TMP_COMMANDS = ("test", "uisnap", "vendor")   # commands whose TMPDIR is always the state root's tmp/


def home():
    """The absolute, normalised home directory from $HOME; SuiteError(home_invalid) otherwise."""
    value = os.environ.get("HOME", "")
    if not value or not os.path.isabs(value) or "\0" in value:
        raise SuiteError("home_invalid")
    return os.path.normpath(value)


def _home(value):
    return home() if value is None else os.path.normpath(value)


def data_home(home_dir=None):
    return os.path.join(_home(home_dir), *DATA_HOME_PARTS)


def suite_root(home_dir=None):
    return os.path.join(_home(home_dir), *SUITE_ROOT_PARTS)


def state_dir(home_dir=None):
    return os.path.join(_home(home_dir), *STATE_DIR_PARTS)


def share_dir(home_dir=None):
    return os.path.join(_home(home_dir), *SHARE_DIR_PARTS)


def deps_root(home_dir=None):
    return os.path.join(share_dir(home_dir), "deps")


def run_dir(home_dir=None):
    return os.path.join(state_dir(home_dir), "run")


def config_path(home_dir=None):
    return os.path.join(state_dir(home_dir), "config.json")


def salt_path(home_dir=None):
    return os.path.join(state_dir(home_dir), "install-salt")       # Phase 0 adaptation B


def research_clone(home_dir=None):
    """The deploy clone the Air fast-forwards; the suite never imports from it or writes into it."""
    return os.path.join(_home(home_dir), "betangel-research")


def tmp_dir(command, home_dir=None):
    """The TMPDIR (and SQLITE_TMPDIR) bin/suite must pass for this command."""
    if STATE_ROOT_AGREED and command not in STATE_TMP_COMMANDS:
        return os.path.join(suite_root(home_dir), "tmp")
    return os.path.join(state_dir(home_dir), "tmp")


def write_roots(home_dir=None):
    """The directories the engine may write under, as a tuple of absolute paths."""
    found = [state_dir(home_dir)]
    if STATE_ROOT_AGREED:
        found.append(suite_root(home_dir))
    return tuple(found)


def within(path, root):
    """True when the normalised absolute path is root or lies below it (text only, no file system)."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def place(path, home_dir=None):
    """(normalised path, its root) for a path the helper may write; SuiteError otherwise.

    Text only: nothing on disk is looked at, so a refused path under ~/betangel-data is never touched.
    """
    if not isinstance(path, str) or not os.path.isabs(path) or "\0" in path:
        raise SuiteError("path_not_absolute")
    path = os.path.normpath(path)
    if within(path.casefold(), data_home(home_dir).casefold()):
        if not STATE_ROOT_AGREED:
            raise SuiteError("state_root_not_agreed")
    for root in write_roots(home_dir):
        if within(path, root):
            return path, root
    raise SuiteError("write_outside_roots")


# --- the writer helper ---------------------------------------------------------------------------

def ensure_dir(path, *, home_dir=None):
    """Create path and every missing directory between its root and it, each 0700; return path.

    The root's parent must already exist. The root and everything below it must be real directories
    owned by this user (no symlinks); an existing one with group or other bits is tightened to 0700.
    """
    path, root = place(path, home_dir)
    parent = os.path.dirname(root)
    try:
        info = os.stat(parent)
    except OSError:
        info = None
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise SuiteError("root_parent_missing")
    if root == suite_root(home_dir):
        _check_suite_root(root)
    current = root
    _make_dir(current)
    for part in os.path.relpath(path, root).split(os.sep):
        if part in ("", "."):
            continue
        current = os.path.join(current, part)
        _make_dir(current)
    return path


def write_new(path, data, *, home_dir=None):
    """Create a new 0600 file holding data (bytes); refuses an existing name, a symlink included."""
    path, root = place(path, home_dir)
    if path == root:
        raise SuiteError("not_a_directory")
    ensure_dir(os.path.dirname(path), home_dir=home_dir)
    if os.path.lexists(path):
        raise SuiteError("already_exists")
    _path_guard(path, prospective=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        fd = None
    if fd is None:
        raise SuiteError("already_exists")
    try:
        view = memoryview(bytes(data))
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        ok = True
    except OSError:
        ok = False
    finally:
        os.close(fd)
    if not ok:
        os.unlink(path)
        raise SuiteError("write_failed")
    return path


def _make_dir(path):
    """mkdir 0700 if missing, then insist on a real, owned directory with no group or other bits."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    if info is None:
        _path_guard(path, prospective=True)
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        info = os.lstat(path)
    else:
        _path_guard(path, prospective=False)
    if stat.S_ISLNK(info.st_mode):
        raise SuiteError("symlink_refused")
    if not stat.S_ISDIR(info.st_mode):
        raise SuiteError("not_a_directory")
    if info.st_uid != os.getuid():
        raise SuiteError("wrong_owner")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o700)


def _check_suite_root(root):
    """upstream archive.check_data_root on the suite root (DESIGN.md 3.7); "missing" is fine, it is made next."""
    from . import rx                # here, not at the top: rx needs the armed guard and the verified pin
    _resolved, problems = rx.archive.check_data_root(root)
    problems = [problem for problem in problems if problem != "data_root:missing"]
    if problems:
        raise SuiteError("suite_root_invalid", problems[0].rpartition(":")[2])


def _path_guard(path, *, prospective):
    """upstream path_guard.guard_path, mapped without a salted hash (the salt itself is written here)."""
    from . import rx                # here, not at the top: rx needs the armed guard and the verified pin
    try:
        rx.path_guard.guard_path(path, "suite_path", prospective=prospective)
        reason = None
    except rx.path_guard.PathDenied as exc:
        reason = str(exc).rpartition(":")[2]
    if reason is not None:
        raise SuiteError("path_denied", reason)
