"""The closed route table, the command and query enums, request schemas and the App (DESIGN.md 9.1, 9.2).

Routes (exact path and method; tests/test_http_routes.py asserts equality):

    GET  /  and the exact names in ui/manifest.json     static UI (static.py)
    POST /api/v1/bootstrap                              {"code": <str>} -> {"ok": true, "token": <str>}
    GET  /api/v1/stream                                 NDJSON frames for this tab (stream.py)
    POST /api/v1/query                                  {"query": <QUERIES>, "args": {}}
    POST /api/v1/command                                {"nonce": <str>, "command": <COMMANDS>, "args": {...}}

The command enum is section 9.1's, in full. Phase 0b implements open_market {"seed": int} (synthetic only),
play, pause, set_speed {"speed_x100": int} and stop; Phase 0c adds claim_control {} (9.2 item 8: a read-only
tab takes control; it is the one command a read-only tab may send). Every other command answers
{"ok": false, "code": "not_implemented"}. Exploration mode's replace is not part of Phase 0.
No route, command or query name holds a word of FORBIDDEN_WORDS (I-7).

The control socket's closed command set (CONTROL_ARGS, each with its exact extra keys): DESIGN.md 9.1's attach,
new_code, pause and stop, plus the ssh-session viewer's attach_viewer, viewer_code, viewer_heartbeat and
viewer_away (Phase 0c: session lifetime, DESIGN.md 8.6 item 2 and I-19), which name the viewer generation that
attach_viewer returned, so an ssh-session that was taken over cannot ask for codes or keep the session alive.

The App joins the engine, the session tokens, the session lifetime (api/lifetime.py) and the control socket.
Its methods return (HTTP status, JSON object); every failure object is {"ok": false, "code": <errors.CODES
entry>}. Requests carry no identifier back into a log: the handler logs status codes and error codes only.
Standard library only.
"""

import re
import threading
import time

from ..errors import SuiteError

ROUTES = {
    ("POST", "/api/v1/bootstrap"): "bootstrap",
    ("GET", "/api/v1/stream"): "stream",
    ("POST", "/api/v1/query"): "query",
    ("POST", "/api/v1/command"): "command",
}
COMMANDS = ("open_market", "play", "pause", "set_speed", "seek", "jump", "step", "subscribe", "claim_control",
            "place", "cancel", "cancel_side", "cancel_all", "stop", "resume", "void_and_rewind", "report_problem",
            "set_prefs", "export_csv")
EXPLORATION_COMMANDS = ("replace",)         # exploration mode (R-7) adds it; not accepted in Phase 0b
QUERIES = ("session", "catalogue", "journal", "green_up_preview")
FORBIDDEN_WORDS = ("live", "account", "funds", "login", "kill", "upload", "share")
# The control socket: command -> the exact extra keys of its request line (each an int viewer generation).
CONTROL_ARGS = {
    "attach": (), "new_code": (), "pause": (), "stop": (),
    "attach_viewer": (), "viewer_code": ("viewer",), "viewer_heartbeat": ("viewer",), "viewer_away": ("viewer",),
}
CONTROL_COMMANDS = tuple(CONTROL_ARGS)
VIEWER_MAX = 2 ** 31 - 1

# Phase 0b and 0c: command -> exact argument schema {key: type}
IMPLEMENTED = {
    "open_market": {"seed": int},
    "play": {},
    "pause": {},
    "set_speed": {"speed_x100": int},
    "stop": {},
    "claim_control": {},
}
APP_COMMANDS = ("claim_control",)           # handled by the App itself, never by the engine's actor
IMPLEMENTED_QUERIES = ("session",)
BODY_KEYS = {
    "bootstrap": frozenset({"code"}),
    "query": frozenset({"query", "args"}),
    "command": frozenset({"nonce", "command", "args"}),
}
NONCE_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
NONCE_CACHE = 1024
# route -> (requests, per seconds)
RATE_LIMITS = {"bootstrap": (30, 60.0), "stream": (60, 60.0), "query": (300, 10.0), "command": (300, 10.0)}
OK = 200


def refused(status, code):
    """(status, {"ok": false, "code": code}) with code forced into errors.CODES."""
    return status, {"ok": False, "code": SuiteError(code).code}


class RateLimiter:
    """A sliding window per route."""

    def __init__(self, limits=RATE_LIMITS, clock=time.monotonic):
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._seen = {route: [] for route in limits}

    def allow(self, route):
        count, window = self._limits[route]
        now = self._clock()
        with self._lock:
            recent = [t for t in self._seen[route] if now - t < window]
            allowed = len(recent) < count
            if allowed:
                recent.append(now)
            self._seen[route] = recent
            return allowed


class NonceCache:
    """nonce -> the first result; a replay waits for an in-flight first request and returns its result."""

    def __init__(self, size=NONCE_CACHE):
        self._size = size
        self._lock = threading.Lock()
        self._entries = {}          # nonce -> [event, result]; insertion order is age

    def claim(self, nonce):
        """(True, entry) for a new nonce (the caller must finish() it), else (False, entry)."""
        with self._lock:
            entry = self._entries.get(nonce)
            if entry is not None:
                return False, entry
            entry = [threading.Event(), None]
            self._entries[nonce] = entry
            while len(self._entries) > self._size:
                del self._entries[next(iter(self._entries))]
            return True, entry

    def finish(self, nonce, entry, result):
        entry[1] = result
        entry[0].set()

    def forget(self, nonce, entry):
        """Drop a claimed nonce whose request was refused before dispatch (it may be sent again)."""
        with self._lock:
            if self._entries.get(nonce) is entry:
                del self._entries[nonce]
        entry[1] = None
        entry[0].set()


def exact_object(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def viewer_ok(value):
    """A viewer generation as attach_viewer returns it: a positive int (never a bool)."""
    return type(value) is int and 0 < value <= VIEWER_MAX


def args_ok(args, schema):
    """args has exactly the schema's keys, each of exactly its type (bool is never an int here)."""
    if not exact_object(args, schema):
        return False
    return all(type(args[key]) is kind for key, kind in schema.items())


class App:
    """The engine, the tokens and the request logic behind the HTTP handler and the control socket."""

    def __init__(self, engine, auth, static_files, *, port=0, lifetime=None):
        from .lifetime import Lifetime
        self.engine = engine
        self.auth = auth
        self.lifetime = Lifetime(grace_s=600, max_session_s=14400) if lifetime is None else lifetime
        self.static = static_files
        self.port = port
        self.limits = RateLimiter()
        self.nonces = NonceCache()
        self._watch_lock = threading.Lock()
        self._takeover_lock = threading.Lock()   # a code and its viewer generation are issued together
        self.stopping = threading.Event()
        self.stop_reason = None

    # --- lifecycle ----------------------------------------------------------------------------------

    def request_stop(self, reason="stopped"):
        if self.stop_reason is None:
            self.stop_reason = reason
        self.engine.stop(reason)
        self.stopping.set()

    # --- the control socket (same uid only; control.py checks the peer) -----------------------------

    def control(self, command, args=None):
        args = {} if args is None else args
        if command not in CONTROL_ARGS or set(args) != set(CONTROL_ARGS[command]):
            return {"ok": False, "code": "control_bad_request"}
        if "viewer" in args and not viewer_ok(args["viewer"]):
            return {"ok": False, "code": "control_bad_request"}
        if command in ("attach", "attach_viewer"):
            port, code, generation = self.takeover(terminal=command == "attach_viewer")
            reply = {"ok": True, "port": port, "code": code}
            if command == "attach_viewer":
                reply["viewer"] = generation
            return reply
        if command == "new_code":
            return {"ok": True, "port": self.port, "code": self.auth.issue_code()}
        if command == "viewer_code":
            code = self.viewer_code(args["viewer"])
            return {"ok": True, "port": self.port, "code": code} if code else {"ok": False, "code": "superseded"}
        if command == "viewer_heartbeat":
            return {"ok": True} if self.viewer_heartbeat(args["viewer"]) else {"ok": False, "code": "superseded"}
        if command == "viewer_away":
            return {"ok": True} if self.viewer_away(args["viewer"]) else {"ok": False, "code": "superseded"}
        if command == "pause":
            result = self.engine.pause_external("control")
            return {"ok": True} if result.get("ok") else result
        if command == "stop":
            self.request_stop("stopped")
            return {"ok": True}
        return {"ok": False, "code": "control_bad_request"}

    # --- takeovers and the ssh-session viewer (DESIGN.md 8.6 item 2, I-19) ---------------------------

    def takeover(self, *, terminal):
        """(port, fresh code, viewer generation): pause, invalidate every earlier code and token, start a new viewer.

        open's attach is a takeover without a terminal; ssh-session's (attach_viewer, or its own start) has one.
        """
        with self._takeover_lock:
            code = self.auth.issue_code(takeover=True)
            generation = self.lifetime.takeover(terminal=terminal)
        self.watching_changed()
        self.engine.pause_external("takeover")
        return self.port, code, generation

    def viewer_code(self, generation):
        """A fresh single-use code for the current terminal viewer (Enter in ssh-session), else None."""
        with self._takeover_lock:                # never a code for a viewer a concurrent takeover replaced
            return self.auth.issue_code() if self.lifetime.current(generation) else None

    def viewer_heartbeat(self, generation):
        return self.lifetime.heartbeat(generation)

    def viewer_away(self, generation):
        """stdin EOF or a failed write: pause, and keep the session for the grace period."""
        if not self.lifetime.away(generation):
            return False
        self.engine.pause_external("not_watched")
        return True

    def check_lifetime(self):
        """The engine main loop's periodic check: pause a silent viewer, end an abandoned or over-long session."""
        reason, pause = self.lifetime.check(self.auth.streams_open())
        if pause:
            self.engine.pause_external("not_watched")
        if reason is not None:
            self.request_stop(reason)
        return reason

    # --- routes -------------------------------------------------------------------------------------

    def bootstrap(self, body):
        if not exact_object(body, BODY_KEYS["bootstrap"]) or not isinstance(body["code"], str):
            return refused(400, "bad_args")
        token = self.auth.exchange(body["code"])
        if token is None:
            return refused(401, "bad_code")
        self.watching_changed()                 # a token evicted by this one may have been the controller
        return OK, {"ok": True, "token": token}

    def query(self, token, body):
        if not exact_object(body, BODY_KEYS["query"]) or not isinstance(body["query"], str):
            return refused(400, "bad_args")
        if body["query"] not in QUERIES:
            return refused(400, "unknown_query")
        if body["query"] not in IMPLEMENTED_QUERIES:
            return OK, {"ok": False, "code": "not_implemented"}
        if body["args"] != {}:
            return refused(400, "bad_args")
        latest = self.engine.latest()
        market = None
        if latest is not None:
            market = {"id": latest.frame["market"]["id"], "name": latest.frame["market"]["name"]}
        from .. import engine as engine_module
        return OK, {"ok": True, "controller": self.auth.is_controller(token), "market": market,
                    "speeds_x100": list(engine_module.SPEEDS_X100), "frame_hz": self.engine.frame_hz,
                    "commands": sorted(IMPLEMENTED)}

    def command(self, token, body):
        if (not exact_object(body, BODY_KEYS["command"]) or not isinstance(body["nonce"], str)
                or not isinstance(body["command"], str) or not isinstance(body["args"], dict)):
            return refused(400, "bad_args")
        if not NONCE_RE.fullmatch(body["nonce"]):
            return refused(400, "bad_args")
        name = body["command"]
        if name not in COMMANDS:
            return refused(400, "unknown_command")
        nonce = body["nonce"]
        new, entry = self.nonces.claim(nonce)
        if not new:                             # a replay: the first result, nothing new (9.2 item 7)
            entry[0].wait(10.0)
            return (OK, entry[1]) if entry[1] is not None else refused(409, "engine_busy")
        if name == "claim_control":             # the one command a read-only tab may send (9.2 item 8)
            if not args_ok(body["args"], IMPLEMENTED[name]):
                self.nonces.forget(nonce, entry)
                return refused(400, "bad_args")
            result = {"ok": True} if self.auth.claim(token) else {"ok": False, "code": "unauthorized"}
            self.watching_changed()             # the clock runs only while the new controller watches
            self.nonces.finish(nonce, entry, result)
            return OK, result
        if not self.auth.is_controller(token):  # before not_implemented: a read-only tab learns nothing else
            self.nonces.forget(nonce, entry)
            return refused(409, "not_controller")
        if name not in IMPLEMENTED:
            result = {"ok": False, "code": "not_implemented"}
            self.nonces.finish(nonce, entry, result)
            return OK, result
        if not args_ok(body["args"], IMPLEMENTED[name]):
            self.nonces.forget(nonce, entry)
            return refused(400, "bad_args")
        try:
            result = self.engine.command(name, body["args"])
        except BaseException:
            self.nonces.forget(nonce, entry)
            raise
        self.nonces.finish(nonce, entry, result)
        return OK, result

    # --- streams ------------------------------------------------------------------------------------

    def stream_open(self, token):
        accepted = self.auth.stream_started(token)
        self.watching_changed()
        return accepted

    def stream_close(self, token):
        self.auth.stream_ended(token)
        self.watching_changed()

    def watching_changed(self):
        """Tell the engine whether the controller tab is watching now (it pauses when not; section 8.6).

        The read and the enqueue happen under one lock, so the engine's queue receives the states in the order
        they were read: the last one queued is never older than the last change (stream, bootstrap or takeover
        threads racing could otherwise queue a stale False after a fresh True)."""
        with self._watch_lock:
            self.engine.set_watched(self.auth.controller_watching())
