"""The control socket, run/control.sock (DESIGN.md 3.1 item 3, 9.1), and the stop command.

The engine binds an AF_UNIX stream socket at an absolute path directly in the 0700 run directory
(~/.local/state/betangel-suite/run/), permitted through guard.permit_unix_socket before seal(), and
tightens it to 0600. Each connection must come from this uid, checked with the kernel's peer credentials
(LOCAL_PEERCRED, which macOS getpeereid(3) is built on); any other peer is closed with control_peer_refused.
A peer sends one line of strict JSON, {"command": <routes.CONTROL_ARGS key>, ...that command's exact extra
keys}, at most MAX_LINE bytes, and gets one line back:

    attach            open's takeover: pause, invalidate every earlier code and token,
                      {"ok": true, "port": n, "code": c}
    new_code          a fresh single-use code, {"ok": true, "port": n, "code": c}: silently, with no takeover
                      (no CLI caller; tests use it to get codes)
    pause             pause the clock, {"ok": true}
    stop              end the engine, {"ok": true}
    attach_viewer     {"port": p}: ssh-session's takeover (as attach), which also starts a terminal viewer:
                      {"ok": true, "port": n, "code": c, "viewer": g}; viewer_port_mismatch, before any
                      takeover, when p is neither 0 (any) nor this engine's port
    viewer_code       {"viewer": g}: a fresh code for that viewer (Enter), {"ok": true, "port": n, "code": c}
    viewer_heartbeat  {"viewer": g}: the viewer is there (every 15 s), {"ok": true}
    viewer_away       {"viewer": g}: stdin EOF or a failed write; pause, keep the session for the grace period

The viewer commands answer {"ok": false, "code": "superseded"} once a later takeover has replaced viewer g
(api/lifetime.py). Only open and ssh-session ask for a code, and they hand it to /usr/bin/open, the caller's
stdout (open --print-url) or the viewer's terminal; this module never prints or logs one. new_code and
viewer_code mint a code for whichever same-uid process asks, silently: nothing is printed to Yu, opened or paused
(Nuance's PR #1 review). Only conduct keeps agents from sending them to the real socket (DESIGN.md 3.9 rule 6,
9.1, 9.4): a same-uid process could take the session over through attach anyway. The client side
(request) connects through guard.permit_unix_connect, the only connect the guard allows; a sealed client
(ssh-session's attached viewer) keeps the permit it got before seal(). stop (stop_main) needs no engine:
with no engine holding engine.lock it prints not_running, and while one holds the lock without answering yet
(it is still starting) it asks again until its deadline. A lock it cannot check (any error but a missing
file) counts as held, so stop then fails with control_failed at its deadline. It never checks the run
marker, because it only reduces activity (DESIGN.md 3.9 rule 6). Standard library only.
"""

import fcntl
import json
import os
import socket
import stat
import struct
import sys
import threading
import time

from .. import guard, roots
from ..errors import SuiteError
from .routes import CONTROL_ARGS, control_arg_ok

SOCKET_NAME = "control.sock"
LOCK_NAME = "engine.lock"
SUN_PATH_MAX = 104                  # macOS sockaddr_un.sun_path, terminating NUL included
MAX_LINE = 1024
CONNECTION_TIMEOUT_S = 5.0
STOP_WAIT_S = 15.0
SOL_LOCAL = 0                       # <sys/un.h>; LOCAL_PEERCRED returns struct xucred
XUCRED_VERSION = 0


def socket_path(home_dir=None):
    return os.path.join(roots.run_dir(home_dir), SOCKET_NAME)


def lock_path(home_dir=None):
    return os.path.join(roots.run_dir(home_dir), LOCK_NAME)


def check_path(path):
    if len(os.fsencode(path)) >= SUN_PATH_MAX:
        raise SuiteError("control_path_too_long")


def peer_uid(connection):
    """The uid of the process at the other end of a connected AF_UNIX socket (LOCAL_PEERCRED)."""
    data = connection.getsockopt(SOL_LOCAL, socket.LOCAL_PEERCRED, 76)
    version, uid = struct.unpack_from("=II", data)
    if version != XUCRED_VERSION:
        raise SuiteError("control_peer_refused")
    return uid


# --- the single-instance lock --------------------------------------------------------------------

def acquire_lock(home_dir=None):
    """An fd holding run/engine.lock exclusively, or None when another engine holds it."""
    roots.ensure_dir(roots.run_dir(home_dir), home_dir=home_dir)
    fd = os.open(lock_path(home_dir), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise SuiteError("wrong_owner")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    return fd


HELD, FREE, UNKNOWN = "held", "free", "unknown"


def engine_lock_state(home_dir=None):
    """HELD while another process holds run/engine.lock, FREE when nobody can (no lock file or run directory, or the
    lock is free), UNKNOWN when it cannot be checked: an unreadable lock or run directory, a link at the lock path
    (O_NOFOLLOW), no descriptors left. Nothing is created.

    stop and uisnap read UNKNOWN as held (engine_running). bin/suite test's state-root check reads it as not held:
    only an engine that definitely holds the lock explains run/ entries (cli.unexplained_changes).
    """
    try:
        fd = os.open(lock_path(home_dir), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return FREE
    except OSError:
        return UNKNOWN
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return FREE
    except BlockingIOError:             # another process holds it
        return HELD
    except OSError:                     # anything else: cannot tell
        return UNKNOWN
    finally:
        os.close(fd)


def engine_running(home_dir=None):
    """True while some process may hold run/engine.lock (checked without creating anything).

    Fail closed: only a missing lock file (or run directory), or a free lock, is free. Any other error opening or
    locking it (engine_lock_state UNKNOWN) counts as held, so stop never prints not_running or stopped while a lock
    it cannot check may still be held (Nuance's PR #4 review: it "treats errors as free"). A second engine is kept
    out by acquire_lock, which already fails on any such error.
    """
    return engine_lock_state(home_dir) != FREE


# --- the server side -----------------------------------------------------------------------------

class ControlServer:
    """run/control.sock for a running engine; handler(command, args) -> reply dict (args: the extra keys)."""

    def __init__(self, path, handler, *, expected_uid=None):
        check_path(path)
        self.path = path
        self._handler = handler
        self._uid = os.getuid() if expected_uid is None else expected_uid
        self._closing = threading.Event()
        self._thread = None
        guard.permit_unix_socket(path)
        if os.path.lexists(path):
            os.remove(path)                 # stale: the caller holds the engine lock, so nobody serves it
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(path)
            os.chmod(path, 0o600)
            sock.listen(8)
            sock.settimeout(0.25)
        except BaseException:
            sock.close()
            raise
        self._sock = sock
        self._inode = os.lstat(path).st_ino

    def start(self):
        self._thread = threading.Thread(target=self._serve, name="suite-control", daemon=True)
        self._thread.start()

    def close(self):
        """Stop accepting and remove the socket file (only if it is still ours)."""
        self._closing.set()
        if self._thread is not None:
            self._thread.join(2.0)
        self._sock.close()
        try:
            if os.lstat(self.path).st_ino == self._inode:
                os.remove(self.path)
        except OSError:
            pass

    def _serve(self):
        while not self._closing.is_set():
            try:
                connection, _address = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                if self._closing.is_set():
                    return
                continue
            threading.Thread(target=self._one, args=(connection,), name="suite-control-peer", daemon=True).start()

    def _one(self, connection):
        try:
            connection.settimeout(CONNECTION_TIMEOUT_S)
            reply = self._reply(connection)
            connection.sendall(json.dumps(reply, separators=(",", ":")).encode("ascii") + b"\n")
        except (OSError, ValueError):
            pass
        finally:
            connection.close()

    def _reply(self, connection):
        try:
            uid = peer_uid(connection)
        except (OSError, SuiteError, struct.error):
            uid = None
        if uid != self._uid:
            return {"ok": False, "code": "control_peer_refused"}
        data = _read_line(connection)
        try:
            request = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (ValueError, UnicodeDecodeError, RecursionError, AttributeError):
            request = None
        if not request_ok(request):
            return {"ok": False, "code": "control_bad_request"}
        args = {key: value for key, value in request.items() if key != "command"}
        reply = self._handler(request["command"], args)
        return reply if isinstance(reply, dict) else {"ok": False, "code": "control_failed"}


def request_ok(request):
    """A request object with a known command and exactly that command's extra keys, each valid (control_arg_ok)."""
    if not isinstance(request, dict) or not isinstance(request.get("command"), str):
        return False
    extra = CONTROL_ARGS.get(request["command"])
    if extra is None or set(request) != {"command", *extra}:
        return False
    return all(control_arg_ok(key, request[key]) for key in extra)


def _read_line(connection):
    """One newline-terminated request of at most MAX_LINE bytes, or None."""
    data = b""
    while b"\n" not in data:
        part = connection.recv(MAX_LINE + 1 - len(data))
        if not part:
            return None
        data += part
        if len(data) > MAX_LINE:
            return None
    return data.split(b"\n", 1)[0]


# --- the client side (open, ssh-session, stop) ---------------------------------------------------

def request(command, home_dir=None, *, timeout=CONNECTION_TIMEOUT_S, args=None):
    """Send one control command to the running engine; the reply dict, or None when no engine answers."""
    line = {"command": command, **({} if args is None else args)}
    if not request_ok(line):
        raise SuiteError("control_bad_request")
    path = socket_path(home_dir)
    if not os.path.lexists(path):
        return None                     # no engine (an engine always has its socket)
    check_path(path)
    if not guard.is_sealed():
        guard.permit_unix_connect(path)     # once sealed, only a path permitted before seal() connects
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            return None
        sock.sendall(json.dumps(line).encode("ascii") + b"\n")
        data = b""
        while b"\n" not in data and len(data) <= 4 * MAX_LINE:
            part = sock.recv(4 * MAX_LINE)
            if not part:
                break
            data += part
    except OSError:
        raise SuiteError("control_unavailable") from None
    finally:
        sock.close()
    try:
        reply = json.loads(data.split(b"\n", 1)[0].decode("utf-8"), object_pairs_hook=_no_duplicates,
                           parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        reply = None
    if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
        raise SuiteError("control_failed")
    return reply


def stop_main(home_dir=None, *, out=None, wait_s=STOP_WAIT_S):
    """bin/suite stop: ask a running engine to stop and wait until its lock is free. Prints one word."""
    out = sys.stdout if out is None else out
    deadline = time.monotonic() + wait_s
    while True:
        try:
            reply = request("stop", home_dir)
        except SuiteError as exc:
            if exc.code not in ("control_failed", "control_unavailable"):
                raise
            reply = {"ok": False}       # the engine may close before its reply: the lock below decides
        if reply is not None:
            break
        if not engine_running(home_dir):
            out.write("not_running\n")
            return 0
        # engine.lock is held but nothing answers on control.sock: server.run binds it only after building the
        # engine (or has just removed it while stopping), so ask again until the deadline
        if time.monotonic() > deadline:
            raise SuiteError("control_failed")
        time.sleep(0.05)
    while engine_running(home_dir):
        if time.monotonic() > deadline:
            raise SuiteError("control_failed")
        time.sleep(0.05)
    out.write("stopped\n")
    return 0


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name):
    raise ValueError("non-finite number")
