"""The suite's PEP 578 audit hook: invariants I-2 to I-6 of DESIGN.md section 10.

arm(mode) checks the interpreter and the environment, then installs one audit hook with
sys.addaudithook. bin/_launch.py calls it before anything imports betangel_research (rx.py and pin.py
refuse to run unarmed). The sys API offers no way to remove an audit hook, and nothing here turns this
one off: no environment variable, config key or function of this module disarms it, and a later hook can
only add refusals. The hook keeps no per-call flag that could leave it skipping events.

What it is not: proof against deliberately adversarial code running in the same process. Such code can
rewrite any Python object, this hook's state and functions included (through gc, function attributes or
this module's globals). That is the same-uid limit of DESIGN.md 9.4 and I-16; the guard catches mistakes,
upstream behaviour and accidental calls, not a determined same-user attacker.

What the hook refuses, in every mode and phase:

  I-2  changing BETANGEL_BETFAIR_FORBID_NETWORK (arm() refuses unless it is "1"), setting any other
       BETFAIR* or BETANGEL_BETFAIR_* variable (arm() refuses if one is set), or changing TMPDIR or
       SQLITE_TMPDIR (arm() refuses unless both are the same absolute text with no "." or ".." component, so
       it differs from its normalised text at most by a redundant or final "/", and that normalised text lies
       inside a write root and, with its links resolved, inside that root's real path);
  I-3  socket connect, sendto and sendmsg, and every name or address lookup;
  I-4  socket bind, except to ("127.0.0.1", port) for a port permitted before seal() and to an absolute,
       normalised Unix socket path in the run directory permitted the same way, matched exactly while the
       run directory still resolves where it did at arm() and the socket path is not itself a link (bind
       follows a dangling one and creates the socket at its target); a relative path, or one with a NUL in
       it (the kernel ends the socket name at the first NUL), is never permitted. And listen(), except on an
       AF_INET socket bound to 127.0.0.1 with a non-zero port (a permitted port-0 bind has its port by then)
       or an AF_UNIX socket bound to a name (listen_refused): CPython raises no listen event, and listen() on
       an unbound AF_INET socket binds it to 0.0.0.0 with no bind event. AF_INET6 is always refused. The hook
       puts a wrapper that raises "socket.listen" on socket.socket.listen at the first socket.__new__ event
       (arm() does it at once if socket is already loaded, and never imports socket), and refuses to create a
       socket whose class would not call that wrapper: a bare _socket.socket, or a subclass with its own listen;
  I-5  os.system, os.exec*, os.spawn*, os.fork and os.forkpty always; subprocess.Popen and os.posix_spawn
       except as below. Always, too:
       - a direct call of _posixsubprocess.fork_exec, which starts a child from C with no audit event of its
         own. arm() replaces it with a wrapper that raises one, "_posixsubprocess.fork_exec", and leaves
         subprocess its own reference to the original, behind the subprocess.Popen event. arm() refuses
         (call_replaced_early) unless both are the C original when it runs;
       - importing multiprocessing (any submodule) or concurrent.futures.process, which start children through
         fork_exec, and ctypes or _ctypes (any submodule), since _ctypes reaches libc through dlsym and
         call_function with no dlopen (import_refused). arm() refuses (module_loaded_early) if one of them is
         already loaded: the import event fires only for a module that is not loaded yet;
       - ctypes.dlopen, plus ctypes.dlsym and ctypes.call_function as a backstop, and SQLite extension loading.
       Threads are unaffected;
  I-6  writes outside the write roots: open with a write flag, mkdir, rmdir, remove, rename (both paths),
       link (both paths: a hard link would alias an outside inode inside the roots), symlink, truncate,
       chmod, chown, chflags, utime, mkfifo, mknod and sqlite3.connect. The write roots are the state
       root in every mode; the suite root only in engine mode, and only while roots.STATE_ROOT_AGREED is
       True; and in vendor mode also the share directory and this checkout's pin/. So the test runner
       never writes under ~/betangel-data, whatever the flag says: its tests use temporary HOMEs. While
       the flag is False a write under ~/betangel-data is refused as state_root_not_agreed, judged on the
       path text alone. A relative path in a write open is refused too: the open event does not say which dir_fd it
       is relative to (the other events do, and a dir_fd is resolved with F_GETPATH). The roots check
       resolves the path as given, as the OS does: "link/.." and a final "/" follow the link.
       That check trusts each root's real path, so arm() first refuses any write root, and TMPDIR, that
       the file system puts in, around or onto ~/betangel-data (roots.check_placement, stat calls only):
       root_overlaps_data_home, or suite_root_misplaced for an engine suite root that is not a real
       directory, or missing, at exactly realpath(~/betangel-data)/suite.noindex. And the hook refuses a
       symlink, hard link or rename that puts a name where a root or TMPDIR really is, or moves one away
       (root_replace_refused): os.symlink(<a data root>, suite.noindex) would otherwise pass as a write in
       the roots and steer the next process. Links elsewhere in the roots stay allowed.
       chmod, chown, utime and truncate on a descriptor (fchmod and the like) are judged by the file's path
       from F_GETPATH, and refused when it has none: a read-only open is never checked, so a descriptor
       does not show that its file lies in the roots. open() of a descriptor is not judged again.
       CPython raises no audit event for os.mkfifo and os.mknod, so arm() replaces them (in os and posix)
       with wrappers that raise one ("os.mkfifo", "os.mknod") before calling the original.
       The sqlite3.connect event covers only the main database file. ATTACH DATABASE and VACUUM INTO create
       further files from C, with no audit event, so arm() also replaces sqlite3.connect with a wrapper
       that sets SQLITE_LIMIT_ATTACHED to 0 on every new connection: both statements then fail. (The audit
       event sqlite3.connect/handle comes too early for that: the connection is not initialised yet.) Each
       connection is a guard subclass whose setlimit refuses that limit (sqlite_limit_refused), and the hook
       refuses every sqlite3.connect event that did not come through the wrapper (sqlite_connect_refused):
       a sqlite3.Connection constructed or re-initialised directly, a connect reference taken before arm(),
       or a factory argument.
       SQLite's temporary files (temp tables, sorts, statement journals) are opened from C too, in a
       directory SQLite picks at that moment: SQLITE_TMPDIR, or /var/tmp or /tmp if that is gone. So the
       wrapper also runs PRAGMA temp_store = MEMORY and refuses the connection (sqlite_connect_refused)
       unless the setting then reads 2, and the hook refuses connect("") (sqlite_connect_refused), whose
       private database is such a temporary file. Rollback journals and WAL files sit beside the database.

Subprocesses by mode (the launcher picks the mode from the command name; nothing else can):

  engine  before seal(), exactly two argv shapes: git -C <dir in the write roots> rev-parse
          --is-inside-work-tree (paths.is_inside_git_worktree, used by config.validate_config) and
          /usr/bin/open http://127.0.0.1:<permitted port>/#c=<code>; after seal(), none. A bare "git"
          must come through subprocess with a search path of /usr/bin and /bin only.
  vendor  before seal(), exactly the four git argvs tools/vendor_research.py runs; after, none.
  test    the test runner never seals. It may start /opt/homebrew/bin/python3.13 or 3.11 (or this
          interpreter) with -I -S -B, /bin/sh on this checkout's bin/suite, and /usr/bin/git only as
          git -C <dir under TMPDIR> [-c <test identity key>=...] <local subcommand> with relative operands,
          no user or system git config and no other GIT_* variable (runner_git_ok). Tests of the engine
          policy run in fresh engine-mode subprocesses, because a hook cannot be taken back.

Every child must keep BETANGEL_BETFAIR_FORBID_NETWORK=1 and carry no stray BETFAIR variable.

This is defence in depth, not a sandbox: same-user code can still write through C extensions (SQLite's
journal beside a database, and its temp files if a PRAGMA sets temp_store back), a child process (in test
mode, an isolated interpreter the runner starts is unguarded unless it imports betangel_suite), a file
descriptor or hard link made before a check, a reference to os.mkfifo or _posixsubprocess.fork_exec taken
before arm(), subprocess's private _fork_exec or _socket.socket.listen called directly, or
sqlite3.Connection.setlimit called on a connection directly. Refusals raise GuardRefusal, whose str() is
the code only, never the path or address.
Standard library only.
"""

import fcntl
import os
import re
import sys
import threading

from . import roots
from .errors import SuiteError

FORBID_NETWORK_ENV = "BETANGEL_BETFAIR_FORBID_NETWORK"
STRAY_PREFIXES = ("BETFAIR", "BETANGEL_BETFAIR_")
PINNED_ENV = (FORBID_NETWORK_ENV, "TMPDIR", "SQLITE_TMPDIR")
ALLOWED_VERSIONS = ((3, 11), (3, 13))                # I-14; bin/_launch.py holds the same tuple
MODES = ("engine", "test", "vendor")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(REPO_ROOT, "bin", "suite")
GIT = "/usr/bin/git"
OPEN = "/usr/bin/open"
SEARCH_DIRS = ("/usr/bin", "/bin")                   # where a bare program name may be found
TEST_INTERPRETERS = ("/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.11")
VENDOR_GIT_PREFIX = (GIT, "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
                     "-c", "core.hooksPath=/dev/null")
# The test runner's git (runner_git_ok): local subcommands only, the synthetic identity, no user config.
TEST_GIT_SUBCOMMANDS = frozenset({"init", "add", "commit", "update-index", "check-ignore", "rev-parse"})
TEST_GIT_CONFIG_KEYS = frozenset({"init.defaultBranch", "user.name", "user.email"})
TEST_GIT_OPTIONS = frozenset({"-q", "--quiet", "--template=", "-f", "-A", "--", "-m", "--add", "--cacheinfo",
                              "--no-index", "--verify"})
TEST_GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
TEST_GIT_ENV_EXTRA = frozenset({"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
                                "GIT_TERMINAL_PROMPT"})

_NETWORK = {
    "socket.connect": "network_refused", "socket.connect_ex": "network_refused",
    "socket.sendto": "network_refused", "socket.sendmsg": "network_refused",
    "socket.getaddrinfo": "name_lookup_refused", "socket.gethostbyname": "name_lookup_refused",
    "socket.gethostbyaddr": "name_lookup_refused", "socket.getnameinfo": "name_lookup_refused",
}
# "_posixsubprocess.fork_exec" is raised by the wrapper arm() installs (_wrap_fork_exec) and, like os.fork, is
# refused in every mode and phase: _check_spawn refuses it before it looks at any argument.
_SPAWN = frozenset({"subprocess.Popen", "os.posix_spawn", "os.system", "os.exec", "os.spawn", "os.fork",
                    "os.forkpty", "_posixsubprocess.fork_exec"})
# Modules whose import the hook refuses (import_refused), with every submodule, and which arm() refuses to find
# already loaded (module_loaded_early). multiprocessing (spawn, the macOS default, and forkserver) and
# concurrent.futures.process start children through _posixsubprocess.fork_exec, which raises no audit event of
# its own (Nuance's PR #2 review, item 3). _ctypes calls into libc with dlsym(RTLD_DEFAULT, name) and
# call_function, which need no dlopen (item 18); the ctypes package imports it.
_REFUSED_IMPORTS = ("multiprocessing", "concurrent.futures.process", "ctypes", "_ctypes")
# ctypes.dlsym, ctypes.dlsym/handle and ctypes.call_function back up the ctypes refusal: _ctypes cannot be loaded
# once the hook is in place, but if it ever were, a symbol lookup or a raw call is refused too.
_LIBRARY_LOADS = frozenset({"ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function",
                            "sqlite3.enable_load_extension", "sqlite3.load_extension"})
# event -> ((index of a path argument, index of its dir_fd argument or None, follows a final symlink,
#            puts a name in place or moves one away: never a root's or TMPDIR's), ...)
_MUTATIONS = {
    "os.mkdir": ((0, 2, False, False),),
    "os.rmdir": ((0, 1, False, False),),
    "os.remove": ((0, 1, False, False),),
    "os.rename": ((0, 2, False, True), (1, 3, False, True)),
    "os.link": ((0, 2, True, False), (1, 3, False, True)),
    "os.symlink": ((1, 2, False, True),),
    "os.truncate": ((0, None, True, False),),
    "os.chmod": ((0, 2, True, False),),
    "os.chown": ((0, 3, True, False),),
    "os.chflags": ((0, None, True, False),),
    "os.utime": ((0, 3, True, False),),
    "os.mkfifo": ((0, 2, False, False),),   # raised by the wrapper arm() installs
    "os.mknod": ((0, 3, False, False),),    # likewise
}
_WATCHED = frozenset(set(_NETWORK) | _SPAWN | set(_MUTATIONS) | _LIBRARY_LOADS
                     | {"socket.bind", "socket.__new__", "socket.listen", "os.putenv", "os.unsetenv", "open",
                        "sqlite3.connect", "import"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_DEVICES = frozenset({"/dev/null"})
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PARTIAL_RE = re.compile(r"betangel-research-[0-9a-f]{12}\.partial")
_URL_RE = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})/#c=[A-Za-z0-9_-]{22}")
_ORIGINAL_NODE_CALLS = {name: getattr(os, name) for name in ("mkfifo", "mknod") if hasattr(os, name)}
_BUILTIN_FUNCTION = type(len)
# _socket.socket's own listen, getsockname and family, and AF_INET and AF_UNIX, kept when the listen wrapper is
# installed (_install_listen). Nothing here imports socket or _socket: arm() must not load them.
_SOCKET_CALLS = {}

_LOCK = threading.Lock()
_STATE = None


class GuardRefusal(SuiteError):
    """Raised from the audit hook; str() is the refusal code only."""


class _State:
    """What the hook enforces, fixed at arm() except for seal() and the bind permits."""

    def __init__(self, mode, tmp_root):
        home = roots.home()
        # The suite root holds licensed derivatives and belongs to the engine alone (DESIGN.md 3.7).
        found = list(roots.write_roots(home)) if mode == "engine" else [roots.state_dir(home)]
        if mode == "vendor":
            found += [roots.share_dir(home), os.path.join(REPO_ROOT, "pin")]
        self.mode = mode
        self.home = home
        self.sealed = False
        self.roots = tuple(found)
        self.real_roots = tuple(os.path.realpath(root) for root in found)
        self.tmp_root = tmp_root
        # Where each root and TMPDIR really are (casefolded: the lab's APFS volume folds case). No name may be
        # put there, and none moved away, so the placement arm() checked holds for the life of the process.
        self.slots = frozenset(real.casefold() for real in self.real_roots + (
            (os.path.realpath(tmp_root),) if tmp_root else ()))
        self.agreed = roots.STATE_ROOT_AGREED
        self.data_home = roots.data_home(home).casefold()
        self.run_dir = roots.run_dir(home)
        run_parent, run_name = os.path.split(self.run_dir)
        self.real_run_dir = os.path.join(os.path.realpath(run_parent), run_name)     # where a real run/ resolves
        self.research = roots.research_clone(home)
        self.deps_root = roots.deps_root(home)
        self.interpreters = frozenset(TEST_INTERPRETERS + (sys.executable,))
        self.ports = set()
        self.unix_paths = set()
        self.connecting = threading.local()     # the sqlite3.connect wrapper's token (_wrap_sqlite_connect)


# --- arming and phases ---------------------------------------------------------------------------

def arm(mode):
    """Check the interpreter and environment, then install the hook; idempotent for the same mode."""
    global _STATE
    with _LOCK:
        if _STATE is not None:
            if _STATE.mode != mode:
                raise SuiteError("guard_mode_conflict")
            return
        if mode not in MODES:
            raise SuiteError("guard_mode_invalid")
        if tuple(sys.version_info[:2]) not in ALLOWED_VERSIONS:
            raise SuiteError("interpreter_version")
        if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
            raise SuiteError("launch_flags")
        if os.environ.get(FORBID_NETWORK_ENV) != "1":
            raise SuiteError("network_not_forbidden")
        if any(_stray(key) for key in os.environ):
            raise SuiteError("stray_environment")
        tmp = os.environ.get("TMPDIR", "")
        state = _State(mode, os.path.normpath(tmp) if os.path.isabs(tmp) else "")
        if not state.tmp_root or tmp != os.environ.get("SQLITE_TMPDIR") or not _tmp_root_ok(state, tmp):
            raise SuiteError("tmpdir_mismatch")
        _check_placement(state)
        _refuse_loaded_modules()
        _wrap_node_calls()
        _wrap_sqlite_connect(state)
        _wrap_fork_exec()
        _wrap_listen()
        sys.addaudithook(_make_hook(state))
        _STATE = state


def seal():
    """End the startup phase: from now on no subprocess and no new bind permit (engine, vendor)."""
    with _LOCK:
        _require_armed().sealed = True


def armed_mode():
    """The mode the guard was armed in, or None."""
    state = _STATE
    return None if state is None else state.mode


def is_sealed():
    state = _STATE
    return state is not None and state.sealed


def require_armed():
    _require_armed()


def require_mode(mode):
    if _require_armed().mode != mode:
        raise SuiteError("guard_mode_conflict")


def permit_loopback_port(port):
    """Allow binding ("127.0.0.1", port); 0 means an ephemeral port. Only before seal()."""
    with _LOCK:
        state = _require_unsealed()
        if type(port) is not int or not 0 <= port <= 65535:
            raise SuiteError("bind_permit_invalid")
        state.ports.add(port)


def permit_unix_socket(path):
    """Allow binding a Unix socket at path: normalised, directly in the run directory. Only before seal().

    A path with a NUL in it is refused: the kernel ends sun_path at the first NUL, so the bind would create a
    different name from the one permitted, and os.path.islink cannot look at such a path (it says False).
    """
    with _LOCK:
        state = _require_unsealed()
        if (not isinstance(path, str) or "\0" in path or not os.path.isabs(path)
                or os.path.normpath(path) != path or os.path.dirname(path) != state.run_dir):
            raise SuiteError("bind_permit_invalid")
        state.unix_paths.add(path)


def _require_armed():
    state = _STATE
    if state is None:
        raise SuiteError("guard_not_armed")
    return state


def _require_unsealed():
    state = _require_armed()
    if state.sealed:
        raise SuiteError("guard_sealed")
    return state


def _stray(key):
    return key != FORBID_NETWORK_ENV and key.upper().startswith(STRAY_PREFIXES)


def _tmp_root_ok(state, tmp):
    """TMPDIR has no "." or ".." component, and lies in a write root as text and, links resolved, in its real path.

    Python's tempfile uses the normalised text (abspath), but SQLite reads SQLITE_TMPDIR from C as given. The OS
    resolves "link/.." through the link and cannot resolve "missing/.." or "file/.." at all (SQLite then falls
    back to /var/tmp or /tmp), while normpath and the non-strict realpath fold all three away. So no "." or ".."
    component is accepted: TMPDIR may differ from its normalised text only by a redundant or final "/", and
    realpath of both (which must agree) must lie inside the matching root's real path. Whether the directory
    exists is not checked here: cli.main creates it (0700) before every handler but vendor's, which makes no
    temporary files.
    """
    if any(part in (os.curdir, os.pardir) for part in tmp.split(os.sep)):
        return False
    real = os.path.realpath(tmp)
    return real == os.path.realpath(state.tmp_root) and any(
        roots.within(state.tmp_root, root) and roots.within(real, real_root)
        for root, real_root in zip(state.roots, state.real_roots))


def _check_placement(state):
    """roots.check_placement on every write root and on TMPDIR (Nuance's PR #2 review, item 1).

    The hook trusts each root's real path, so a root that a link puts in, around or onto ~/betangel-data would
    take every write there: root_overlaps_data_home, or suite_root_misplaced for a suite root that is not a real
    directory (or missing) at exactly realpath(data home)/suite.noindex. Stat calls only; nothing is opened.
    """
    for path in state.roots + (state.tmp_root,):
        roots.check_placement(path, state.home)


def _import_refused(name):
    """True for a module in _REFUSED_IMPORTS or a submodule of one."""
    return isinstance(name, str) and any(name == top or name.startswith(top + ".") for top in _REFUSED_IMPORTS)


def _refuse_loaded_modules():
    """module_loaded_early if a refused module is already loaded: the import event fires only for a module that is
    not in sys.modules yet, so the hook could not stop it, and fail closed is the only safe answer."""
    if any(_import_refused(name) for name in list(sys.modules)):
        raise SuiteError("module_loaded_early")


# --- calls that raise no audit event of their own --------------------------------------------------

def _mkfifo(path, mode=0o666, *, dir_fd=None):
    sys.audit("os.mkfifo", path, mode, -1 if dir_fd is None else dir_fd)
    return _ORIGINAL_NODE_CALLS["mkfifo"](path, mode, dir_fd=dir_fd)


def _mknod(path, mode=0o600, device=0, *, dir_fd=None):
    sys.audit("os.mknod", path, mode, device, -1 if dir_fd is None else dir_fd)
    return _ORIGINAL_NODE_CALLS["mknod"](path, mode, device, dir_fd=dir_fd)


def _wrap_node_calls():
    """Make os.mkfifo and os.mknod (and their posix originals) raise an audit event the hook checks."""
    import posix
    for name, wrapper in (("mkfifo", _mkfifo), ("mknod", _mknod)):
        if name in _ORIGINAL_NODE_CALLS:
            for module in (os, posix):
                if getattr(module, name, None) is _ORIGINAL_NODE_CALLS[name]:
                    setattr(module, name, wrapper)


def _wrap_sqlite_connect(state):
    """sqlite3.connect, making each new connection a guard subclass whose setlimit refuses SQLITE_LIMIT_ATTACHED
    (Nuance's PR #2 review, item 16), and setting on it SQLITE_LIMIT_ATTACHED to 0 (no ATTACH, no VACUUM INTO)
    and temp_store to MEMORY (no temporary file; item 15). A connection whose temp_store does not then read 2 is
    closed and refused.

    The wrapper holds a per-thread token while it constructs the connection, and the hook refuses every
    sqlite3.connect event without one (sqlite_connect_refused), so the limit and temp_store cannot be skipped:
    a sqlite3.Connection constructed directly, a connection re-initialised with __init__ (which would open a
    new database with the default limits), and a connect reference taken before arm() are all refused. So is a
    factory argument: the wrapper picks the class. No authorizer is installed (Nuance's fix).

    Same-process code can still call sqlite3.Connection.setlimit on a connection, or set temp_store back with a
    PRAGMA; neither the suite nor the pinned closure does (the guard catches mistakes, not a determined attacker).
    A SQLite built with SQLITE_TEMP_STORE=0 would read 2 and still use files; the tests check that no temporary
    file is opened, so such a build fails them.
    """
    import sqlite3
    import sqlite3.dbapi2
    original = sqlite3.connect
    base = sqlite3.Connection
    limit = sqlite3.SQLITE_LIMIT_ATTACHED
    token = state.connecting

    class GuardedConnection(base):
        """The class of every connection the wrapper makes: SQLITE_LIMIT_ATTACHED cannot be changed."""

        def setlimit(self, category, value):
            if category == limit:
                raise GuardRefusal("sqlite_limit_refused")
            return base.setlimit(self, category, value)

    def connect(database, *args, **kwargs):
        if len(args) > 4 or "factory" in kwargs:        # factory is the sixth parameter
            raise GuardRefusal("sqlite_connect_refused")
        token.ready = True
        try:
            connection = original(database, *args, factory=GuardedConnection, **kwargs)
        finally:
            token.ready = False
        try:
            base.setlimit(connection, limit, 0)
            connection.execute("PRAGMA temp_store = MEMORY")
            row = connection.execute("PRAGMA temp_store").fetchone()
        except Exception:
            connection.close()
            raise GuardRefusal("guard_internal_error") from None
        if row is None or tuple(row) != (2,):
            connection.close()
            raise GuardRefusal("sqlite_connect_refused")
        return connection

    for module in (sqlite3, sqlite3.dbapi2, sys.modules.get("_sqlite3")):
        if module is not None and getattr(module, "connect", None) is original:
            module.connect = connect


def _wrap_fork_exec():
    """Make a direct call of _posixsubprocess.fork_exec raise "_posixsubprocess.fork_exec", which the hook refuses
    in every mode and phase (Nuance's PR #2 review, item 3).

    fork_exec starts a child from C with no audit event. multiprocessing calls it (spawn, the macOS default, and
    forkserver, through multiprocessing.util.spawnv_passfds), and so can any code that imports _posixsubprocess;
    a child started that way is unguarded and could write anywhere. subprocess calls it too, but subprocess.Popen
    raises its own event first, which _check_spawn judges, and subprocess keeps its own reference, bound when it
    is imported (subprocess._fork_exec). So subprocess is imported here first, and arm() refuses
    (call_replaced_early) unless that reference and _posixsubprocess.fork_exec are both the C original; only the
    module attribute is then replaced. Imported after this, subprocess would bind the wrapper and every Popen,
    the startup git included, would be refused. The wrapper's event carries no arguments: there is no argv the
    hook could judge, and nothing the suite or the pinned closure runs calls fork_exec directly.
    """
    import _posixsubprocess
    import subprocess
    original = _posixsubprocess.fork_exec
    if not (type(original) is _BUILTIN_FUNCTION and getattr(original, "__self__", None) is _posixsubprocess
            and getattr(subprocess, "_fork_exec", None) is original):
        raise SuiteError("call_replaced_early")

    def fork_exec(*args, **kwargs):
        sys.audit("_posixsubprocess.fork_exec")
        return original(*args, **kwargs)

    _posixsubprocess.fork_exec = fork_exec


def _listen(self, *args):
    """socket.socket.listen once the listen wrapper is installed: raises "socket.listen" for the hook first."""
    sys.audit("socket.listen", self)
    return _SOCKET_CALLS["listen"](self, *args)


def _install_listen():
    """Put _listen on socket.socket, once (Nuance's PR #2 review, item 4); False when that cannot be done safely.

    CPython raises no audit event for listen(), and listen() on an unbound AF_INET socket binds it to 0.0.0.0 and
    a free port first, with no socket.bind event. The wrapper raises "socket.listen", which the hook judges
    (_check_listen). It is set on socket.socket, so every socket that module makes (accept, dup, socketpair,
    fromfd and socketserver's included) and every subclass that does not define its own listen calls it. False
    (fail closed) when socket or _socket is not loaded, or when socket.socket already has a listen of its own,
    put there by something other than the guard.
    """
    sockets = sys.modules.get("socket")
    raw = sys.modules.get("_socket")
    base = getattr(sockets, "socket", None)
    raw_class = getattr(raw, "socket", None)
    if not (isinstance(base, type) and isinstance(raw_class, type) and issubclass(base, raw_class)):
        return False
    current = base.__dict__.get("listen")
    if current is _listen:
        return True
    if current is not None:
        return False
    _SOCKET_CALLS.update(listen=raw_class.listen, getsockname=raw_class.getsockname, family=raw_class.family,
                         AF_INET=raw.AF_INET, AF_UNIX=raw.AF_UNIX)
    base.listen = _listen
    return True


def _wrap_listen():
    """arm(): install the listen wrapper now if socket is already loaded (call_replaced_early if it cannot be);
    otherwise the hook installs it at the first socket.__new__ event. A socket made before arm() is then
    covered too, since the wrapper is on the class."""
    if sys.modules.get("socket") is not None and not _install_listen():
        raise SuiteError("call_replaced_early")


# --- the hook ------------------------------------------------------------------------------------

def _make_hook(state):
    # No reentrancy flag: _check raises no watched event itself, and if a future change made it do so,
    # the nested call is checked like any other (or fails closed as guard_internal_error).
    def audit_hook(event, args, _watched=_WATCHED, _check=_check, _refusal=GuardRefusal, _state=state):
        if event not in _watched:
            return
        try:
            _check(_state, event, args)
        except _refusal:
            raise
        except Exception:               # a malformed event or a bug here: fail closed, code only
            raise _refusal("guard_internal_error") from None

    return audit_hook


def _check(state, event, args):
    code = _NETWORK.get(event)
    if code is not None:
        raise GuardRefusal(code)
    if event == "socket.bind":
        _check_bind(state, args[0], args[1])
    elif event == "socket.__new__":
        # Every new socket must call the listen wrapper: installed here the first time, and a socket whose class
        # would bypass it (a bare _socket.socket, or a subclass with its own listen) is refused.
        if not _install_listen() or getattr(type(args[0]), "listen", None) is not _listen:
            raise GuardRefusal("listen_refused")
    elif event == "socket.listen":
        _check_listen(args[0])
    elif event in _SPAWN:
        _check_spawn(state, event, args)
    elif event in _LIBRARY_LOADS:
        if event != "sqlite3.enable_load_extension" or args[1]:
            raise GuardRefusal("dlopen_refused")
    elif event in ("os.putenv", "os.unsetenv"):
        _check_env_change(event, args)
    elif event == "open":
        path, mode, flags = args
        writes = isinstance(flags, int) and flags & _WRITE_FLAGS
        if writes or (isinstance(mode, str) and any(c in mode for c in "wax+")):
            _check_write(state, path, None, True)       # None: the open event does not carry dir_fd
    elif event == "sqlite3.connect":
        _check_sqlite(state, args[0])
    elif event == "import":
        if _import_refused(args[0]):
            raise GuardRefusal("import_refused")
    else:
        for path_index, fd_index, follow, slot in _MUTATIONS[event]:
            _check_write(state, args[path_index], -1 if fd_index is None else args[fd_index], follow, slot)


def _check_bind(state, sock, address):
    sockets = sys.modules.get("socket")     # loaded by whoever made the socket; never imported here
    family = getattr(sock, "family", None)
    if sockets is not None:
        if (family == sockets.AF_INET and isinstance(address, tuple) and len(address) == 2
                and address[0] == "127.0.0.1" and type(address[1]) is int and address[1] in state.ports):
            return
        if family == sockets.AF_UNIX and isinstance(address, (str, bytes)):
            # The exact permitted text (normpath would fold "link/.." that the OS resolves through the link),
            # in a run directory that still resolves where it did at arm() (not replaced by a link), and not
            # itself a link: bind follows a final dangling link and creates the socket at its target, outside
            # the run directory, with no write event. (Any other existing name fails with EADDRINUSE.) No NUL
            # either, whatever was permitted: the kernel ends the name at the first one, and islink cannot see
            # the name before it.
            text = os.fsdecode(address)
            if ("\0" not in text and text in state.unix_paths
                    and os.path.realpath(os.path.dirname(text)) == state.real_run_dir and not os.path.islink(text)):
                return
    raise GuardRefusal("bind_refused")


def _check_listen(sock):
    """listen() only on a socket the bind check has already placed: AF_INET bound to 127.0.0.1 with a non-zero port
    (a permitted port-0 bind has been given one by then) or AF_UNIX bound to a name. Anything else is refused
    (listen_refused): an unbound AF_INET socket would be bound to 0.0.0.0, and the suite never uses AF_INET6.
    _socket's own family and getsockname are used, so a subclass cannot answer for the socket."""
    calls = _SOCKET_CALLS
    family = calls["family"].__get__(sock)
    try:
        name = calls["getsockname"](sock)
    except OSError:
        raise GuardRefusal("listen_refused") from None
    if family == calls["AF_INET"]:
        if (isinstance(name, tuple) and len(name) == 2 and name[0] == "127.0.0.1" and type(name[1]) is int
                and name[1] != 0):
            return
    elif family == calls["AF_UNIX"]:
        if isinstance(name, (str, bytes)) and len(name) > 0:
            return
    raise GuardRefusal("listen_refused")


def _check_spawn(state, event, args):
    if event == "subprocess.Popen":
        executable, argv, _cwd, env = args
    elif event == "os.posix_spawn":
        executable, argv, env = args
    else:
        raise GuardRefusal("subprocess_refused")
    if isinstance(argv, (str, bytes)):
        argv = [argv]
    argv = [os.fsdecode(os.fspath(item)) for item in argv]
    if not argv or (executable is not None and os.fsdecode(os.fspath(executable)) != argv[0]):
        raise GuardRefusal("subprocess_refused")
    names = None if env is None else {os.fsdecode(key): os.fsdecode(value) for key, value in dict(env).items()}
    if not _child_env_ok(names):
        raise GuardRefusal("subprocess_refused")
    if not os.path.isabs(argv[0]):
        # A bare name is looked up on the child's search path (subprocess), or relative to the cwd
        # (os.posix_spawn): only subprocess with /usr/bin and /bin may resolve it.
        if names is None:
            search = os.environ.get("PATH", os.defpath)
        else:
            search = names.get("PATH", os.defpath)
        if event != "subprocess.Popen" or not all(entry in SEARCH_DIRS for entry in search.split(os.pathsep)):
            raise GuardRefusal("subprocess_refused")
    if state.mode == "test":
        if runner_argv_ok(argv, names, state.interpreters, LAUNCHER, state.tmp_root):
            return
    elif not state.sealed:
        if state.mode == "engine" and engine_argv_ok(argv, state.roots, state.ports):
            return
        if state.mode == "vendor" and vendor_argv_ok(argv, state.research, state.deps_root):
            return
    raise GuardRefusal("subprocess_refused")


def _child_env_ok(names):
    """A child's environment (None: this process's, checked by arm()): no stray BETFAIR variable, and the
    network switch kept on. Any child that imports betangel_suite also arms its own guard."""
    if names is None:
        return True
    return not any(_stray(key) for key in names) and names.get(FORBID_NETWORK_ENV) == "1"


def engine_argv_ok(argv, write_roots, ports):
    """The two argvs an engine may start before seal() (DESIGN.md I-5)."""
    if len(argv) == 5 and argv[:2] == ["git", "-C"] and argv[3:] == ["rev-parse", "--is-inside-work-tree"]:
        directory = argv[2]
        return (os.path.isabs(directory) and os.path.normpath(directory) == directory
                and any(roots.within(directory, root) for root in write_roots))
    if len(argv) == 2 and argv[0] == OPEN:
        match = _URL_RE.fullmatch(argv[1])
        return bool(match) and int(match.group(1)) != 0 and int(match.group(1)) in ports
    return False


def vendor_argv_ok(argv, research, deps_root):
    """The four git argvs of tools/vendor_research.py: cat-file -e, clone, checkout --detach, remote remove."""
    prefix = list(VENDOR_GIT_PREFIX)
    if argv[:len(prefix)] != prefix:
        return False
    rest = argv[len(prefix):]

    def partial(path):
        return os.path.dirname(path) == deps_root and bool(_PARTIAL_RE.fullmatch(os.path.basename(path)))

    if len(rest) == 5 and rest[:4] == ["-C", research, "cat-file", "-e"]:
        return rest[4].endswith("^{commit}") and bool(_SHA_RE.fullmatch(rest[4][:-len("^{commit}")]))
    if len(rest) == 6 and rest[:5] == ["clone", "--no-checkout", "--no-hardlinks", "--quiet", research]:
        return partial(rest[5])
    if len(rest) == 6 and rest[0] == "-C" and rest[2:5] == ["checkout", "--quiet", "--detach"]:
        return partial(rest[1]) and bool(_SHA_RE.fullmatch(rest[5]))
    if len(rest) == 5 and rest[0] == "-C" and rest[2:] == ["remote", "remove", "origin"]:
        return partial(rest[1])
    return False


def runner_argv_ok(argv, env, interpreters, launcher, tmp_root):
    """What the test runner may start: isolated interpreters, this checkout's launcher, and local git."""
    if argv[0] in interpreters:
        return argv[1:4] == ["-I", "-S", "-B"]
    if argv[0] == "/bin/sh":
        return len(argv) >= 2 and argv[1] == launcher
    return argv[0] == GIT and runner_git_ok(argv, env, tmp_root)


def runner_git_ok(argv, env, tmp_root):
    """git -C <dir under tmp_root> [-c key=value ...] <local subcommand> <allowed options, relative operands>.

    The environment must be explicit, with no user or system git config and no other GIT_* variable (which
    could inject config, a git dir or an ssh command). No network transport is reachable: every allowed
    subcommand is local. The -C directory must lie under the test temp root, so neither the deploy clone
    nor this checkout is ever touched.
    """
    if env is None or any(env.get(key) != value for key, value in TEST_GIT_ENV.items()):
        return False
    if any(key.startswith("GIT_") and key not in TEST_GIT_ENV and key not in TEST_GIT_ENV_EXTRA for key in env):
        return False
    if len(argv) < 4 or argv[0] != GIT or argv[1] != "-C" or not tmp_root:
        return False
    directory = argv[2]
    if not (os.path.isabs(directory) and os.path.normpath(directory) == directory
            and roots.within(directory, tmp_root)
            and roots.within(os.path.realpath(directory), os.path.realpath(tmp_root))):
        return False
    rest = argv[3:]
    while len(rest) >= 2 and rest[0] == "-c":
        key, equals, _value = rest[1].partition("=")
        if not equals or key not in TEST_GIT_CONFIG_KEYS:
            return False
        rest = rest[2:]
    if not rest or rest[0] not in TEST_GIT_SUBCOMMANDS:
        return False
    for item in rest[1:]:
        if item.startswith("-"):
            if item not in TEST_GIT_OPTIONS:
                return False
        elif os.path.isabs(item) or ".." in item.replace("\\", "/").split("/"):
            return False
    return True


def _check_env_change(event, args):
    key = os.fsdecode(args[0])
    if key in PINNED_ENV or _stray(key):
        if not (event == "os.putenv" and key == FORBID_NETWORK_ENV and os.fsdecode(args[1]) == "1"):
            raise GuardRefusal("environment_change_refused")


def _check_sqlite(state, database):
    if not getattr(state.connecting, "ready", False):
        raise GuardRefusal("sqlite_connect_refused")    # not made by the wrapper (Nuance's PR #2 review, item 16)
    state.connecting.ready = False                      # one connection per wrapper call
    text = os.fsdecode(os.fspath(database))
    if text == "":
        # A private database in a temporary file SQLite opens from C, wherever its temp directory is then, and
        # opened before the wrapper can set temp_store (Nuance's PR #2 review, item 15).
        raise GuardRefusal("sqlite_connect_refused")
    if text == ":memory:":
        return
    if text.startswith("file:"):
        # The suite opens no URI filenames, memory ones included: the event does not say whether URIs are
        # on, and without SQLITE_USE_URI, uri=False opens "file::memory:" as a file in the cwd.
        raise GuardRefusal("write_outside_roots")
    _check_write(state, text, -1, True)


def _check_write(state, path, dir_fd, follow, slot=False):
    if isinstance(path, int):
        if dir_fd is None:
            return                                     # open() of a descriptor: its writes were judged at its open
        # fchmod, fchown, futimens or ftruncate: judged by where the descriptor's file is, since a read-only open
        # is not checked at all (Nuance's PR #2 review, item 17). A descriptor without a path is refused.
        raw, follow = _descriptor_path(path), False
    else:
        raw = os.fsdecode(os.fspath(path))
    if raw in _DEVICES:
        return
    if not os.path.isabs(raw):
        if dir_fd is None:
            raise GuardRefusal("write_outside_roots")  # relative to an unknown directory: refuse
        base = _fd_path(dir_fd) if dir_fd >= 0 else os.getcwd()
        raw = os.path.join(base, raw)
    text = os.path.normpath(raw)                       # for the text checks only: the OS resolves raw
    if not state.agreed and roots.within(text.casefold(), state.data_home):
        raise GuardRefusal("state_root_not_agreed")    # decided on the text: nothing there is touched
    for root, real in zip(state.roots, state.real_roots):
        if roots.within(text, root) or roots.within(text, real):
            # normpath folds "link/.." and drops a final "/", both of which the OS resolves through the link;
            # a final "", "." or ".." makes even a call that does not follow a final link follow it.
            head, tail = os.path.split(raw)
            if follow or tail in ("", ".", ".."):
                resolved = os.path.realpath(raw)
            else:
                resolved = os.path.join(os.path.realpath(head), tail)
            if roots.within(resolved, real):
                if slot and resolved.casefold() in state.slots:
                    # A link, or a name renamed into place, where a root or TMPDIR is (os.symlink(historic-pro,
                    # suite.noindex), say), or a root or TMPDIR moved away: the next process would trust it.
                    raise GuardRefusal("root_replace_refused")
                return
            break
    raise GuardRefusal("write_outside_roots")


def _fd_path(fd):
    """The path of an open descriptor (macOS F_GETPATH): a dir_fd, or the descriptor of a metadata call."""
    buffer = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
    return os.fsdecode(buffer.split(b"\0", 1)[0])


def _descriptor_path(fd):
    """The absolute path F_GETPATH gives for descriptor fd; GuardRefusal(write_outside_roots) when there is none
    (a pipe, a socket, a closed or out-of-range descriptor)."""
    try:
        path = _fd_path(fd)
    except (OSError, OverflowError, ValueError):
        path = ""
    if not os.path.isabs(path):
        raise GuardRefusal("write_outside_roots")
    return path
