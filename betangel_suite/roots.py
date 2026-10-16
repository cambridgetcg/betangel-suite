"""State roots and the single writer helper (DESIGN.md 3.7; Phase 0 adaptations A and B).

Roots, under the home directory taken from $HOME (bin/suite passes the caller's HOME through env -i):

    ~/.local/state/betangel-suite/            0700  config, prefs, run/, tmp/, install-salt (Phase 0)
    ~/.local/share/betangel-suite/deps/       read-only pinned upstream code (written only by the vendor tool)
    ~/betangel-data/suite.noindex/            0700  the suite root, ONLY while STATE_ROOT_AGREED is True

STATE_ROOT_AGREED is True: Yu agreed the suite root (R-4), and Nuance agreed it on three conditions
(Q-N3; DESIGN.md 3.7). So the suite root is writable (by the engine only: guard.py gives it to no other
mode), and its tmp/ is the TMPDIR of every command except test, uisnap and vendor. The flag and
bin/suite's default TMP branch, which a shell script cannot read from here, change together. The launcher
refuses any mismatch between them (tmpdir_mismatch), so a half-done change fails closed.

With the flag False (tests still cover it, under temporary HOMEs) nothing may be created or written
anywhere under ~/betangel-data: the writer helper refuses with state_root_not_agreed on the path text
alone, before touching the file system, the audit hook (guard.py) refuses the same writes from any other
code, and every command's TMPDIR is the state root's tmp/.

The writer helper creates directories 0700 and files 0600 with O_CREAT|O_EXCL|O_NOFOLLOW, never follows a
symlink below a root, refuses any path outside the roots, and passes each new path through upstream's
path_guard.guard_path (through rx, imported only when a write happens). Before it creates or enters the
suite root it runs the root through upstream archive.check_data_root (DESIGN.md 3.7: outside the repository
and every Git worktree).

Path text is not enough for the roots themselves: a link on an ancestor (~/.local/state pointing into
~/betangel-data/lab-state, say) or a suite.noindex that is a link to a data root would put every write there.
So check_placement() judges each root on the file system, with stat calls only (Nuance's PR #2 review, item 1).
guard.arm() runs it on every write root and TMPDIR, and the writer helper on the root of every path it writes.
"""

import os
import stat

from .errors import SuiteError

STATE_ROOT_AGREED = True            # R-4 (Yu) and Q-N3 (Nuance); changes only with bin/suite's TMP line

DATA_HOME_PARTS = ("betangel-data",)
SUITE_ROOT_PARTS = ("betangel-data", "suite.noindex")
STATE_DIR_PARTS = (".local", "state", "betangel-suite")
SHARE_DIR_PARTS = (".local", "share", "betangel-suite")
STATE_TMP_COMMANDS = ("test", "uisnap", "vendor")   # commands whose TMPDIR is always the state root's tmp/
_MAX_ANCESTORS = 256                                 # deeper than any real tree: past it, fail closed


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


# --- where the roots really are ------------------------------------------------------------------

def check_placement(path, home_dir=None):
    """Refuse a write root, or a path in one (TMPDIR), that the file system puts in the wrong place relative to
    ~/betangel-data (Nuance's PR #2 review, item 1; DESIGN.md 3.7, I-6). Stat calls only: realpath's lstat and
    readlink, and os.stat. Nothing is opened, read or listed.

    While STATE_ROOT_AGREED, the suite root and every path in it (by text): the suite root must be a real
    directory, or missing, at exactly realpath(data home)/suite.noindex, and path must resolve inside it. A
    suite.noindex that is a link, to historic-pro say, is refused, so no write can be steered into a data root.
    SuiteError(suite_root_misplaced) otherwise.

    Any other path must not equal, lie in or contain the data home: root_overlaps_data_home otherwise, and also
    when that cannot be judged. Two comparisons, each both ways:
      - text: path and the data home, each as written and with its links resolved (realpath), casefolded
        (the lab's APFS volume folds case);
      - identity: the data home's (st_dev, st_ino) must not be that of path or of any directory above it, and
        path's must not be that of the data home or of any directory above it. Directories above are found with
        "..", as the kernel resolves it, so spellings that realpath leaves alone (the /System/Volumes/Data
        firmlink prefix, /.vol/<dev>/<ino>) and links on any ancestor are seen. Nothing inside the data home is
        looked up: its own walk starts at its parent, so a data home spelt through /.vol (whose parent only a
        lookup inside it could find) is refused.
    """
    path = os.path.normpath(path)
    suite = suite_root(home_dir)
    if STATE_ROOT_AGREED and within(path, suite):
        expected = os.path.join(os.path.realpath(data_home(home_dir)), SUITE_ROOT_PARTS[-1])
        if not (_real_dir_or_missing(expected) and os.path.realpath(suite) == expected
                and within(os.path.realpath(path), expected)):
            raise SuiteError("suite_root_misplaced")
        return
    if _overlaps_data_home(path, home_dir):
        raise SuiteError("root_overlaps_data_home")


def _overlaps_data_home(path, home_dir):
    data = data_home(home_dir)
    real_data = os.path.realpath(data)
    real = os.path.realpath(path)
    for mine in (path.casefold(), real.casefold()):
        for theirs in (data.casefold(), real_data.casefold()):
            if within(mine, theirs) or within(theirs, mine):
                return True
    if real_data.casefold().startswith("/.vol/"):
        return True
    data_id = _identity(data)
    if data_id is not None and data_id in _lineage(real):
        return True
    path_id = _identity(real)
    return path_id is not None and (path_id == data_id or path_id in _lineage(os.path.dirname(real_data)))


def _real_dir_or_missing(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode)


def _identity(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_dev, info.st_ino


def _directory(path):
    """os.stat(path) when it is a directory, else None."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info if stat.S_ISDIR(info.st_mode) else None


def _lineage(path):
    """The (st_dev, st_ino) of the nearest existing directory at or above path (by text) and of every directory
    above that one, as the kernel resolves ".." (so through a firmlink or /.vol spelling too). If ".." cannot be
    looked up (no search permission, a name too long), the step falls back to the text parent, which is the same
    directory for a path realpath has resolved. SuiteError(root_overlaps_data_home) when nothing can be judged.
    """
    current, info = path, _directory(path)
    while info is None:
        parent = os.path.dirname(current)
        if parent == current:
            raise SuiteError("root_overlaps_data_home")
        current, info = parent, _directory(parent)
    found = set()
    for _ in range(_MAX_ANCESTORS):
        found.add((info.st_dev, info.st_ino))
        above_path = os.path.join(current, os.pardir)
        above = _directory(above_path)
        if above is None:
            above_path = os.path.dirname(os.path.normpath(current))
            above = _directory(above_path)
            if above is None:
                raise SuiteError("root_overlaps_data_home")
        if (above.st_dev, above.st_ino) == (info.st_dev, info.st_ino):
            return found
        current, info = above_path, above
    raise SuiteError("root_overlaps_data_home")


# --- the writer helper ---------------------------------------------------------------------------

def ensure_dir(path, *, home_dir=None):
    """Create path and every missing directory between its root and it, each 0700; return path.

    The root's parent must already exist, and the root must pass check_placement() (no link on an ancestor
    may put it in, around or onto ~/betangel-data). The root and everything below it must be real directories
    owned by this user (no symlinks); an existing one with group or other bits is tightened to 0700.
    """
    path, root = place(path, home_dir)
    check_placement(root, home_dir)
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
