"""The betangel-research pin: deps-clone lookup, per-file hashes, sys.path append, origin check (DESIGN.md 3.5).

pin/betangel-research.json names one upstream commit and the sha256 of every file the engine loads from
it: the 25 modules of the verified import closure (section 4.1) and the experiment contract that holds the
month roles. tools/vendor_research.py writes it on a pin bump; nothing else does.

activate() runs once per process, after the guard is armed and before betangel_research is imported. It
hashes the pinned files in ~/.local/share/betangel-suite/deps/betangel-research-<sha12>/ (no git runs; each
file opened below the deps directory with no symlink on the way, O_NONBLOCK, and refused unless it is a regular
file with exactly one link), refuses pin_mismatch on any difference, refuses a deps tree holding bytecode caches (Python would load a
stale .pyc beside a matching .py) or anything Python would import in preference to a pinned .py (an
extension module such as paper.cpython-313-darwin.so, a .pyc, or a package directory named like a pinned
module), refuses a deps directory or any sys.path entry that lies in ~/betangel-research (the moving
deploy clone) by name in any case or by identity, and only then APPENDS the deps directory to sys.path,
so the standard library can never be shadowed. assert_origins() then checks that every loaded
betangel_research module came from that directory.

Standard library only.
"""

import fcntl
import hashlib
import importlib.machinery
import json
import os
import re
import stat
import sys

from . import guard, roots
from .errors import SuiteError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN_FILE = os.path.join(REPO_ROOT, "pin", "betangel-research.json")
REPO = "cambridgetcg/betangel-research"
PYTHON_FLOOR = "3.11"
PIN_KEYS = frozenset({"schema_version", "repo", "commit", "python_floor", "files"})
MAX_PIN_BYTES = 64 << 10

# The engine's import closure at the pin (section 4.1), as files, plus the month-role contract.
PINNED_FILES = (
    "betangel_research/__init__.py",
    "betangel_research/evaluation.py",
    "betangel_research/stream.py",
    "betangel_research/temporal.py",
    "betangel_research/betfair/__init__.py",
    "betangel_research/betfair/book.py",
    "betangel_research/betfair/config.py",
    "betangel_research/betfair/constants.py",
    "betangel_research/betfair/errors.py",
    "betangel_research/betfair/filters.py",
    "betangel_research/betfair/journal.py",
    "betangel_research/betfair/lifecycle.py",
    "betangel_research/betfair/paper.py",
    "betangel_research/betfair/paths.py",
    "betangel_research/betfair/pnl.py",
    "betangel_research/betfair/receipts.py",
    "betangel_research/betfair/schemas.py",
    "betangel_research/betfair/secret.py",
    "betangel_research/betfair/ticks.py",
    "betangel_research/betfair/validate.py",
    "betangel_research/betfair/backtest/__init__.py",
    "betangel_research/betfair/backtest/archive.py",
    "betangel_research/betfair/backtest/contract.py",
    "betangel_research/betfair/backtest/market_index.py",
    "betangel_research/betfair/backtest/path_guard.py",
    "research/experiments/backtest-p0-bsp-v1.json",
)
PACKAGE_DIRS = ("betangel_research", "betangel_research/betfair", "betangel_research/betfair/backtest")
# Files the import system would load instead of (or as well as) a hashed .py: extension modules for any
# interpreter and sourceless bytecode.
SHADOW_SUFFIXES = tuple(sorted(set(importlib.machinery.EXTENSION_SUFFIXES) | set(importlib.machinery.BYTECODE_SUFFIXES)
                               | {".so", ".dylib", ".pyc"}))
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
# Every read here: O_NONBLOCK, so opening a FIFO never waits for a writer (the open of a regular file is unchanged).
_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
# macOS 11 and later: refuse a symlink at any component of the path (ELOOP). Python 3.11 and 3.13 on the lab both
# have it; without it, _open_below walks the path itself, one O_NOFOLLOW component at a time.
_NOFOLLOW_ANY = getattr(os, "O_NOFOLLOW_ANY", 0)

_ACTIVE = None
_HASHES = {}            # relpath -> sha256 of the pin activate() verified (read_pinned)


def load(path=PIN_FILE):
    """The pin as a dict, after strict checks; SuiteError(pin_invalid) otherwise."""
    data = _read_regular(path, MAX_PIN_BYTES)
    if data is None:
        raise SuiteError("pin_invalid")
    try:
        pin = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError):
        pin = None
    if (not isinstance(pin, dict) or set(pin) != PIN_KEYS or type(pin["schema_version"]) is not int
            or pin["schema_version"] != 1 or pin["repo"] != REPO
            or pin["python_floor"] != PYTHON_FLOOR or not isinstance(pin["commit"], str)
            or not _COMMIT_RE.fullmatch(pin["commit"]) or not isinstance(pin["files"], dict)
            or set(pin["files"]) != set(PINNED_FILES)
            or not all(isinstance(v, str) and _SHA256_RE.fullmatch(v) for v in pin["files"].values())):
        raise SuiteError("pin_invalid")
    return pin


def deps_dir(pin, home_dir=None):
    return os.path.join(roots.deps_root(home_dir), "betangel-research-" + pin["commit"][:12])


def file_hashes(tree):
    """{relpath: sha256} of PINNED_FILES under tree; each must be a regular file with one link, reached from tree
    with no symlink on the way (_read_regular); SuiteError(pin_mismatch) otherwise."""
    hashes = {}
    for relpath in PINNED_FILES:
        data = _read_regular(relpath, None, tree)
        if data is None:
            raise SuiteError("pin_mismatch")
        hashes[relpath] = hashlib.sha256(data).hexdigest()
    return hashes


def verify(pin, deps):
    """Refuse unless deps is a real directory holding exactly the pinned bytes and no bytecode caches."""
    try:
        info = os.lstat(deps)
    except OSError:
        info = None
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise SuiteError("deps_missing")
    for package in PACKAGE_DIRS:
        try:
            package_info = os.lstat(os.path.join(deps, package))
        except OSError:
            package_info = None
        if package_info is None or not stat.S_ISDIR(package_info.st_mode):
            raise SuiteError("pin_mismatch")
        if os.path.lexists(os.path.join(deps, package, "__pycache__")):
            raise SuiteError("deps_bytecode_present")
        _refuse_shadows(deps, package)
    if file_hashes(deps) != pin["files"]:
        raise SuiteError("pin_mismatch")


def _refuse_shadows(deps, package):
    """SuiteError(deps_shadow_present) for an entry of one package directory that could shadow a pinned module."""
    stems = {relpath[len(package) + 1:-3] for relpath in PINNED_FILES
             if relpath.endswith(".py") and os.path.dirname(relpath) == package}
    try:
        names = os.listdir(os.path.join(deps, package))
    except OSError:
        names = None
    if names is None:
        raise SuiteError("pin_mismatch")
    for name in names:
        if name.endswith(SHADOW_SUFFIXES):
            raise SuiteError("deps_shadow_present")
        if name in stems:           # a directory book/ (a package) is imported before book.py
            try:
                kind = os.lstat(os.path.join(deps, package, name)).st_mode
            except OSError:
                kind = None
            if kind is None or not stat.S_ISREG(kind):
                raise SuiteError("deps_shadow_present")


def activate(*, home_dir=None, pin_path=PIN_FILE):
    """Verify the deps clone and append it to sys.path; return its path. Idempotent."""
    global _ACTIVE, _HASHES
    guard.require_armed()
    if _ACTIVE is not None:
        return _ACTIVE
    if any(name == "betangel_research" or name.startswith("betangel_research.") for name in sys.modules):
        raise SuiteError("upstream_imported_early")
    pin = load(pin_path)
    deps = deps_dir(pin, home_dir)
    if _in_research(deps, home_dir):
        raise SuiteError("research_clone_on_path")      # an ancestor links there: before any file is read
    verify(pin, deps)
    refuse_research_on_path(home_dir)
    sys.path.append(deps)
    _HASHES = dict(pin["files"])
    _ACTIVE = deps
    return deps


def read_pinned(relpath):
    """The bytes of one PINNED_FILES entry, from the active deps directory, checked against the pin again.

    The month-role JSON (research/experiments/backtest-p0-bsp-v1.json, DESIGN.md 4.1) is read only this way, never
    with open() by path, which follows links and reads whatever is there by then (Nuance's PR #2 review, item 8).
    The file is opened as file_hashes opens it (no symlink below the deps directory, exactly one link, O_NONBLOCK)
    and its sha256 compared with the pin activate() verified, so a change since activate() is refused too. Calls
    activate() first (idempotent; it needs the armed guard). SuiteError(pin_mismatch) for bytes that differ, a file
    that cannot be read that way, or a path that is not a PINNED_FILES entry (it has no pinned bytes).
    """
    deps = activate()
    expected = _HASHES.get(relpath)
    data = None if expected is None else _read_regular(relpath, None, deps)
    if data is None or hashlib.sha256(data).hexdigest() != expected:
        raise SuiteError("pin_mismatch")
    return data


def refuse_research_on_path(home_dir=None):
    """SuiteError(research_clone_on_path) if any sys.path entry lies in ~/betangel-research."""
    for entry in sys.path:
        if isinstance(entry, str) and entry and _in_research(entry, home_dir):
            raise SuiteError("research_clone_on_path")


def _in_research(entry, home_dir=None):
    """True when entry lies in ~/betangel-research, however either path is spelled.

    By text first, as written and resolved, casefolded: the lab's APFS volume folds case and U+017F (long s),
    so /Users/x/BetAngel-Research is the same directory, and a path that does not exist is judged by name.
    Then by identity, for spellings realpath leaves as they are (the /System/Volumes/Data firmlink prefix,
    /.vol/<dev>/<ino>): the kernel's own path for what entry names has neither, nor any link, so its
    directories are the real ancestors, and none may be the clone (compared by st_dev and st_ino; the clone
    itself is only stat()ed, never opened).

    realpath and F_GETPATH get entry as the import system opens it: unchanged when absolute, else joined to
    the cwd without normalising. Normalising first folds "alias/.." away before alias is followed, so with
    alias -> clone/sub the entry alias/../sub, which opens clone/sub, would be judged as a sibling of alias.
    Only the text check also sees the normalised spelling.
    """
    research = roots.research_clone(home_dir)
    forms = (research.casefold(), os.path.realpath(research).casefold())
    raw = entry if os.path.isabs(entry) else os.path.join(os.getcwd(), entry)
    if any(roots.within(candidate.casefold(), form)
           for candidate in (os.path.normpath(raw), os.path.realpath(raw)) for form in forms):
        return True
    try:
        clone = os.stat(research)
    except OSError:
        return False                                   # no clone, so nothing lies in it
    path = _kernel_path(raw)
    while path is not None:
        try:
            if os.path.samestat(os.stat(path), clone):
                return True
        except OSError:
            pass
        parent = os.path.dirname(path)
        path = parent if parent != path else None
    return False


def _kernel_path(path):
    """The kernel's own path (macOS F_GETPATH) for the directory or regular file at path, or None."""
    try:
        mode = os.stat(path).st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            return None                                # a FIFO or a device is not opened
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        buffer = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
    except OSError:
        return None
    finally:
        os.close(fd)
    return os.fsdecode(buffer.split(b"\0", 1)[0])


def assert_origins(deps):
    """Every loaded betangel_research module must come from the deps directory."""
    real = os.path.realpath(deps)
    for name, module in list(sys.modules.items()):
        if name == "betangel_research" or name.startswith("betangel_research."):
            origin = getattr(module, "__file__", None)
            if not isinstance(origin, str) or not roots.within(os.path.realpath(origin), real):
                raise SuiteError("upstream_origin_mismatch")


def read_below(tree, relpath, limit=None):
    """Bytes of the regular file relpath below the directory tree, as file_hashes reads it (no symlink on the way,
    exactly one link, O_NONBLOCK, at most limit bytes), or None. tools/vendor_research.py reads .git/HEAD and
    .git/config this way."""
    return _read_regular(relpath, limit, tree)


def _open_below(tree, relpath):
    """A read-only descriptor for relpath below the directory tree, with no symlink at any component of relpath.

    tree is opened first (O_DIRECTORY, and O_NOFOLLOW: tree itself must not be a link, though its ancestors may be),
    and relpath is opened relative to that descriptor (dir_fd) with O_NOFOLLOW_ANY (macOS 11 and later), which fails
    with ELOOP at a symlink anywhere in it: a deps tree whose research/ links into the deploy clone is refused
    (Nuance's PR #2 review, item 8). Without O_NOFOLLOW_ANY the walk is done here instead, one component at a
    time, each opened O_NOFOLLOW (directories also O_DIRECTORY), which refuses the same links. relpath must be a
    plain relative path (no "", "." or ".." component). OSError otherwise.
    """
    parts = relpath.split("/")
    if os.path.isabs(relpath) or any(part in ("", os.curdir, os.pardir) for part in parts):
        raise OSError("not a plain relative path")
    top = os.open(tree, _READ_FLAGS | os.O_DIRECTORY | os.O_NOFOLLOW)
    current = top
    try:
        if _NOFOLLOW_ANY:
            return os.open(relpath, _READ_FLAGS | _NOFOLLOW_ANY, dir_fd=top)
        for part in parts[:-1]:
            following = os.open(part, _READ_FLAGS | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            if current != top:
                os.close(current)
            current = following
        return os.open(parts[-1], _READ_FLAGS | os.O_NOFOLLOW, dir_fd=current)
    finally:
        if current != top:
            os.close(current)
        os.close(top)


def _read_regular(path, limit, tree=None):
    """Bytes of a regular file with exactly one link, or None.

    tree None: path is opened without following a final symlink (the pin file). Otherwise path is relative to the
    directory tree and no component of it may be a symlink (_open_below). Either way the open is O_NONBLOCK, so a
    FIFO put in a file's place returns at once instead of waiting for a writer (Nuance's PR #2 review, item 22),
    and fstat comes before any read: anything but a regular file, a file over limit bytes, and a file with more
    than one link are refused. A hard link would let the deps tree share an inode with the deploy clone, whose
    bytes then change under the pin and which vendor's chmod would reach (item 8).
    """
    try:
        fd = os.open(path, _READ_FLAGS | os.O_NOFOLLOW) if tree is None else _open_below(tree, path)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (limit is not None and info.st_size > limit)):
            return None
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name):
    raise ValueError("non-finite number")
