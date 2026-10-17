"""The loopback HTTP server and the engine process behind serve and open (DESIGN.md 3.1, 8.5, 8.6, 9.1-9.3).

SuiteHTTPServer is a ThreadingHTTPServer subclass that binds ("127.0.0.1", port) only (the port is
permitted to the guard first; a failed bind aborts, with no fallback port and no IPv6), asserts
getsockname() after the bind, never calls socket.getfqdn, and reports handler failures as an exception
class name only. Handler speaks HTTP/1.1 with keep-alive, sends the section 9.3 headers on every response
(errors before routing included: 400, 414, 431, 501, 505), returns code-only JSON for every error, and
logs nothing but "http:<status>:<code>" and "http:error:<class>" lines. Request checks (section 9.2), in order:

    Host exactly 127.0.0.1:<port> or localhost:<port> (421); the exact route and method (404, 405;
    OPTIONS and other known methods 405); Origin required on POST and checked when present, equal to
    "http://" + Host (403); no request body on GET (400); the session token as Authorization: Bearer on
    every /api/ route but bootstrap (401); then the per-route rate limit (429), so a request without a
    valid token (a hostile page's <img> or no-cors GET of the stream, say) never spends a valid token's
    budget; the stream only for HTTP/1.1 or later, because it is chunked (505); Content-Type
    application/json (415); Content-Length required, at most 64 KiB (411, 413); a strict JSON object
    (receipts.strict_json_loads: duplicate keys and NaN refused) with the route's exact keys (400).

Connections are bounded: at most MAX_CONNECTIONS at once (one over the cap gets a code-only 503 with the
9.3 headers and is closed at once, without waiting on the accept thread); a request's line and headers
must arrive within HEAD_DEADLINE_S of their first byte, and its body (bootstrap included) within
BODY_DEADLINE_S of the start of the body read, however slowly either trickles in (the connection is then
closed with no response); an idle keep-alive connection is closed after Handler.timeout; and the lingering
close lasts LINGER_S in all.

run() is the engine process (serve, open and ssh-session when no engine is running): the single-instance
lock run/engine.lock, the engine, the control socket, the HTTP server, then for open the one /usr/bin/open
argv the guard allows at startup, then guard.seal(), then one stdout line with the port (never a code or a
token; open --print-url adds the URL line before it, for Yu only, and ssh-session prints only its viewer's
lines, api/sshsession.py), and a wait until stop (control socket, SIGTERM, SIGINT, or SIGHUP except under
ssh-session, where a hangup is the viewer leaving), the run marker, an engine failure, or the session's
lifetime (api/lifetime.py: abandoned, max_session). Shutdown ends the streams with an end line, stops the
server and removes the control socket.
"""

import email.utils
import errno
import http.server
import io
import json
import os
import re
import signal
import socket
import socketserver
import sys
import threading
import time

from .. import config, guard, runmarker
from ..errors import SuiteError
from . import auth as auth_module
from . import control, routes, static, stream

MAX_BODY_BYTES = 64 << 10
MAX_CONNECTIONS = 32
HEAD_DEADLINE_S = 10.0          # a request's line and headers, from their first byte
BODY_DEADLINE_S = 10.0          # a request's body, from the start of its read
LINGER_S = 0.25                 # the whole lingering close, not each read
LINGER_BYTES = 1 << 20
SECURITY_HEADERS = (
    ("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'none'"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cache-Control", "no-store"),
)
STATUS_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "bad_origin", 404: "not_found", 405: "method_not_allowed",
    411: "length_required", 413: "body_too_large", 414: "uri_too_long", 415: "unsupported_media_type",
    417: "expectation_failed", 421: "bad_host", 429: "rate_limited", 431: "headers_too_large",
    500: "internal_error", 501: "unsupported_method", 503: "too_many_connections",
    505: "http_version_not_supported",
}
HOST_RE = re.compile(r"(127\.0\.0\.1|localhost):([1-9][0-9]{0,4})")
JSON_TYPE = "application/json"
OPEN_ARGV0 = guard.OPEN
EXIT_OK = 0
POLL_S = 0.25                   # the engine main loop: stop requests, the ssh-session viewer, the lifetime check


def host_ok(values):
    if not values or len(values) != 1:
        return None
    match = HOST_RE.fullmatch(values[0])
    if match is None or int(match.group(2)) > 65535:
        return None
    return values[0]


def json_type_ok(values):
    """Exactly one Content-Type of application/json, with at most a utf-8 charset parameter."""
    if not values or len(values) != 1:
        return False
    parts = [part.strip().lower() for part in values[0].split(";")]
    return parts[0] == JSON_TYPE and all(part in ("charset=utf-8",) for part in parts[1:]) and len(parts) <= 2


class _HeadReader(io.RawIOBase):
    """The handler's socket input. While a request's line and headers are being read, the first byte starts
    the handler's head deadline, and every later read waits only until it (a per-read timeout alone would let a
    client that sends one byte at a time hold its connection for ever); while a body is read, its body deadline
    bounds every read the same way; otherwise each read waits Handler.timeout."""

    def __init__(self, handler):
        super().__init__()
        self._handler = handler
        self._sock = handler.connection

    def readable(self):
        return True

    def readinto(self, buffer):
        handler = self._handler
        timeout = handler.timeout
        deadline = handler._head_deadline if handler._head_deadline is not None else handler._body_deadline
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("request deadline")
            timeout = min(timeout, remaining)
        self._sock.settimeout(timeout)
        count = self._sock.recv_into(buffer)
        if count and handler._reading_head and handler._head_deadline is None:
            handler._head_deadline = time.monotonic() + handler.head_deadline_s
        return count


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "betangel-suite"
    sys_version = ""
    timeout = 60                    # each read and write; an idle keep-alive connection closes after it
    head_deadline_s = HEAD_DEADLINE_S
    body_deadline_s = BODY_DEADLINE_S
    _security_added = False
    _responded = False
    _reading_head = False
    _head_deadline = None
    _body_deadline = None
    _http_1_1 = False

    def setup(self):
        super().setup()
        self.rfile.close()                       # the makefile reader; closing it releases its hold on the socket
        self.rfile = io.BufferedReader(_HeadReader(self))

    def handle_one_request(self):
        self._reading_head, self._head_deadline = True, None
        super().handle_one_request()             # a TimeoutError there closes the connection, with no response

    # --- output: the 9.3 headers on everything, code-only bodies and logs ---------------------------

    def version_string(self):
        return self.server_version

    def log_request(self, code="-", size="-"):
        pass                                     # paths, query strings and headers are never logged

    def log_error(self, format, *args):
        pass

    def log_message(self, format, *args):
        pass

    def send_response(self, code, message=None):
        self._responded = True
        self.send_response_only(code, message)
        self.send_header("Server", self.version_string())
        self.send_header("Date", self.date_time_string())
        self._add_security_headers()

    def end_headers(self):
        self._add_security_headers()             # also covers send_response_only users
        self._security_added = False
        super().end_headers()

    def _add_security_headers(self):
        if not self._security_added:
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self._security_added = True

    def send_error(self, code, message=None, explain=None):
        """Every error, pre-routing ones included: code-only JSON, the 9.3 headers, then close."""
        if self.request_version == "HTTP/0.9":
            # the base class writes no status line or header for HTTP/0.9, and 3.11's parse_request refuses a bad
            # request line or version, and HTTP/2.0, before it sets request_version (3.13 resets it first)
            self.request_version = "HTTP/1.0"
        status = int(code)
        self.reply(status, routes.refused(status, STATUS_CODES.get(status, "bad_request"))[1], close=True)

    def reply(self, status, obj, *, close=False):
        body = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("ascii")
        if status >= 400:
            close = True                         # an unread request body must never become the next request
            self.server.log("http:%d:%s" % (status, obj.get("code", "")))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, status, code):
        self.reply(status, routes.refused(status, code)[1])

    # --- input --------------------------------------------------------------------------------------

    def parse_request(self):
        try:
            parsed = super().parse_request()
        finally:
            self._reading_head, self._head_deadline = False, None     # the head is in (or refused)
            self.connection.settimeout(self.timeout)
        if not parsed:
            return False
        if self.request_version == "HTTP/0.9":
            self.send_error(400)                 # send_error gives the refusal a status line and headers
            return False
        # super() accepted only "HTTP/<digits>.<digits>" below 2.0 here
        major, minor = (int(part) for part in self.request_version.split("/", 1)[1].split("."))
        self._http_1_1 = (major, minor) >= (1, 1)
        return True

    def handle_expect_100(self):
        self.send_error(417)
        return False

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _not_allowed(self):
        self.fail(405, "method_not_allowed")

    do_OPTIONS = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_TRACE = do_CONNECT = _not_allowed

    def _dispatch(self, method):
        self._responded = False
        try:
            self._route(method)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception as exc:
            self.server.log("http:error:" + _class_name(exc))
            self.close_connection = True
            if not self._responded:
                try:
                    self.fail(500, "internal_error")
                except OSError:
                    pass

    def _route(self, method):
        app = self.server.app
        host = host_ok(self.headers.get_all("Host"))
        if host is None:
            return self.fail(421, "bad_host")
        path = self.path
        name = routes.ROUTES.get((method, path))
        is_static = method == "GET" and path in app.static
        if name is None and not is_static:
            known = any(route_path == path for _m, route_path in routes.ROUTES) or path in app.static
            return self.fail(405 if known else 404, "method_not_allowed" if known else "not_found")
        origins = self.headers.get_all("Origin")
        if method == "POST" or origins:
            if not origins or len(origins) != 1 or origins[0] != "http://" + host:
                return self.fail(403, "bad_origin")
        if method == "GET":
            length = self.headers.get_all("Content-Length")
            if self.headers.get_all("Transfer-Encoding") or (length and length != ["0"]):
                return self.fail(400, "bad_request")
        if is_static:
            body, kind = app.static[path]
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        token = None
        if name != "bootstrap":
            authorization = self.headers.get_all("Authorization")
            token = app.auth.check(authorization[0]) if authorization and len(authorization) == 1 else None
            if token is None:
                return self.fail(401, "unauthorized")
        if not app.limits.allow(name):             # after the token: a request without one spends nothing
            return self.fail(429, "rate_limited")
        if name == "stream":
            if not self._http_1_1:                 # the stream is chunked, which HTTP/1.0 does not have
                return self.fail(505, "http_version_not_supported")
            if not app.stream_open(token):
                return self.fail(429, "too_many_connections")
            try:
                stream.serve(self, app, token)
            finally:
                app.stream_close(token)
            return None
        body = self._read_json()
        if body is None:
            return None
        if name == "bootstrap":
            status, obj = app.bootstrap(body)
        elif name == "query":
            status, obj = app.query(token, body)
        else:
            status, obj = app.command(token, body)
        return self.reply(status, obj)

    def _read_json(self):
        """The request's JSON object, or None after sending the refusal."""
        if not json_type_ok(self.headers.get_all("Content-Type")):
            self.fail(415, "unsupported_media_type")
            return None
        if self.headers.get_all("Transfer-Encoding"):
            self.fail(400, "bad_request")
            return None
        lengths = self.headers.get_all("Content-Length")
        if not lengths:
            self.fail(411, "length_required")
            return None
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 12:
            self.fail(400, "bad_request")
            return None
        size = int(lengths[0])
        if size > MAX_BODY_BYTES:
            self.fail(413, "body_too_large")
            return None
        self._body_deadline = time.monotonic() + self.body_deadline_s
        try:
            data = self.rfile.read(size)         # a TimeoutError at the deadline closes the connection, no response
        finally:
            self._body_deadline = None
        if len(data) != size:
            self.close_connection = True
            return None
        from .. import rx
        try:
            body = rx.receipts.strict_json_loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self.fail(400, "bad_json")
            return None
        return body


def _class_name(exc):
    name = type(exc).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "Exception"


class SuiteHTTPServer(http.server.ThreadingHTTPServer):
    """127.0.0.1 only; no getfqdn; code-only error reports; a cap on concurrent connections."""

    address_family = socket.AF_INET
    allow_reuse_address = True
    allow_reuse_port = False
    daemon_threads = True
    block_on_close = False          # server_close must not wait for idle keep-alive connections (stop is prompt)
    request_queue_size = 16

    def __init__(self, port, app, *, log=None):
        if type(port) is not int or not 0 <= port <= 65535:
            raise SuiteError("bad_arguments")
        self.app = app
        self.requested_port = port
        self.log = log or _stderr_log
        self._active = threading.BoundedSemaphore(MAX_CONNECTIONS)
        try:
            super().__init__(("127.0.0.1", port), Handler)
        except OSError as exc:
            code = "port_in_use" if exc.errno == errno.EADDRINUSE else "bind_failed"
            raise SuiteError(code) from None

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)     # HTTPServer.server_bind would call socket.getfqdn
        host, port = self.socket.getsockname()[:2]
        if host != "127.0.0.1" or (self.requested_port and port != self.requested_port):
            raise SuiteError("bind_refused")
        self.server_name = "127.0.0.1"
        self.server_port = port

    def process_request(self, request, client_address):
        if not self._active.acquire(blocking=False):
            self._refuse_busy(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._active.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._active.release()

    def handle_error(self, request, client_address):
        self.log("http:error:" + _class_name(sys.exc_info()[1]))

    def shutdown_request(self, request):
        """A lingering close: after our last byte, drain what the client still sends (LINGER_S in all, however it
        trickles in), so that closing with unread input does not reset the connection before the client has read
        the response."""
        try:
            request.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + LINGER_S
            drained = 0
            while drained < LINGER_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                request.settimeout(remaining)
                part = request.recv(65536)
                if not part:
                    break
                drained += len(part)
        except OSError:
            pass
        self.close_request(request)

    def _refuse_busy(self, request):
        """Over the connection cap: a code-only 503 with the 9.3 headers, then close. This runs on the accept
        thread, so nothing here waits: the send is non-blocking (a fresh socket's buffer takes the few hundred
        bytes whole), and only input that has already arrived is drained before the close."""
        self.log("http:503:too_many_connections")
        try:
            request.setblocking(False)
            request.send(busy_response())
            request.shutdown(socket.SHUT_WR)
            drained = 0
            while drained < LINGER_BYTES:
                part = request.recv(65536)
                if not part:
                    break
                drained += len(part)
        except OSError:
            pass
        self.close_request(request)


def busy_response():
    """The bytes of the 503 too_many_connections response (code-only JSON, the 9.3 headers, Connection: close)."""
    body = json.dumps(routes.refused(503, "too_many_connections")[1], separators=(",", ":")).encode("ascii")
    lines = ["HTTP/1.1 503 Service Unavailable", "Server: " + Handler.server_version,
             "Date: " + email.utils.formatdate(time.time(), usegmt=True)]
    lines += ["%s: %s" % header for header in SECURITY_HEADERS]
    lines += ["Content-Type: application/json", "Content-Length: %d" % len(body), "Connection: close"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def _stderr_log(text):
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


# --- the engine process ---------------------------------------------------------------------------

def system_opener(argv):
    """Run the one /usr/bin/open argv the guard allows at startup (DESIGN.md 8.6, I-5); output discarded."""
    import subprocess
    subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=30, check=False)


def bootstrap_url(port, code):
    return "http://127.0.0.1:%d/#c=%s" % (port, code)


def run(cfg, *, command, port, opener=None, on_ready=None, marker_grace_s=None, ui_dir=None, synthetic=None,
        out=None, home_dir=None, print_url=False, session=None, lifetime=None, poll_s=POLL_S):
    """serve, open or ssh-session: run the engine until it stops; returns the exit status.

    opener (open only) receives the /usr/bin/open argv; the default runs it. print_url (open only; Yu's
    --print-url) writes the URL to out instead, and runs nothing. session (ssh-session only) is an
    sshsession.Session: its viewer takes the new engine over in this process, or, with an engine running,
    takes that one over through the control socket. on_ready(app) runs in this thread after seal() and the
    ready line. marker_grace_s, ui_dir, synthetic, lifetime (an api/lifetime.Lifetime) and poll_s exist for
    tests; by default the lifetime's grace and maximum come from the config (watch_grace_s, max_session_s).
    """
    from .. import engine as engine_module
    from .. import rx
    from .lifetime import Lifetime
    out = sys.stdout if out is None else out
    if command not in ("serve", "open", "ssh-session") or (command == "ssh-session") != (session is not None):
        raise SuiteError("bad_arguments")
    if print_url and command != "open":
        raise SuiteError("bad_arguments")
    if cfg.get("data_roots"):
        raise SuiteError("synthetic_only")
    marker = runmarker.marker_path(cfg, home_dir)
    runmarker.require_absent(marker)
    control.check_path(control.socket_path(home_dir))
    lock_fd = control.acquire_lock(home_dir)
    if lock_fd is None:
        if command == "open":
            return attach(opener=opener, out=out, home_dir=home_dir, print_url=print_url, marker=marker)
        if command == "ssh-session":
            return session.run_attached()
        raise SuiteError("engine_running")
    httpd = control_server = app = None
    serving = None
    try:
        # Again, now that this process holds engine.lock: Nuance writes the marker and then waits for the lock to
        # be free (6.8), so a marker that appeared after the check above refuses the start here.
        runmarker.require_absent(marker)
        grace = engine_module.MARKER_GRACE_S if marker_grace_s is None else marker_grace_s
        engine = engine_module.Engine(cfg, marker_path=marker, synthetic=synthetic, marker_grace_s=grace)
        files = static.load(static.ui_dir(guard.REPO_ROOT) if ui_dir is None else ui_dir)
        auth = auth_module.Auth(register=rx.secret.register)
        if lifetime is None:
            limits = {key: cfg.get(key, config.DEFAULTS[key]) for key in ("watch_grace_s", "max_session_s")}
            lifetime = Lifetime(grace_s=limits["watch_grace_s"], max_session_s=limits["max_session_s"])
        app = routes.App(engine, auth, files, lifetime=lifetime)
        _install_signal_handlers(app, session)
        control_server = control.ControlServer(control.socket_path(home_dir), app.control)
        guard.permit_loopback_port(port)
        httpd = SuiteHTTPServer(port, app)
        app.port = httpd.server_port
        engine.start()
        serving = threading.Thread(target=httpd.serve_forever, name="suite-http", daemon=True)
        serving.start()
        control_server.start()
        url = None
        if command == "open":
            url = bootstrap_url(app.port, auth.issue_code())
            if not print_url:
                if port == 0:
                    guard.permit_loopback_port(app.port)   # the guard checks the URL's port against its permits
                (opener or system_opener)([OPEN_ARGV0, url])
                url = None                      # the /usr/bin/open argv only: never printed (I-16)
        guard.seal()
        if command == "ssh-session":
            session.start_local(app)            # the viewer's first URL, on its own stdout only
        else:
            if url is not None:
                out.write(url + "\n")           # open --print-url: Yu pastes it into a Safari Private window
            out.write("%s port=%d\n" % ("serving" if command == "serve" else "opened", app.port))
            out.flush()
        if on_ready is not None:
            on_ready(app)
        while not app.stopping.wait(poll_s):
            if engine.stopped.is_set():
                break
            if session is not None:
                session.step()
            app.check_lifetime()
        engine.stop(app.stop_reason or "stopped")
        engine.stopped.wait(5.0)
        reason = engine.ended()
        if session is not None:
            session.finish(reason or "stopped")
        elif reason in ("abandoned", "max_session"):
            _write_line(out, "ended reason=%s\n" % reason)
        if reason == "run_marker":
            raise SuiteError("run_marker_present")
        if reason == "engine_failed":
            raise SuiteError("engine_failed")
        return EXIT_OK
    finally:
        _shutdown(app, httpd, serving, control_server)
        os.close(lock_fd)


def _shutdown(app, httpd, serving, control_server):
    """End the engine (streams then send their end line), stop the server, remove the control socket."""
    if app is not None:
        app.engine.stop(app.stop_reason or "stopped")
        if app.engine.started():
            app.engine.stopped.wait(5.0)
        deadline = time.monotonic() + 1.0
        while app.auth.counts()[2] and time.monotonic() < deadline:
            time.sleep(0.02)                    # let open streams write their end line
    if httpd is not None:
        if serving is not None:
            httpd.shutdown()
            serving.join(2.0)
        httpd.server_close()
    if control_server is not None:
        control_server.close()


def _write_line(out, text):
    try:
        out.write(text)
        out.flush()
    except (OSError, ValueError):
        pass


def _install_signal_handlers(app, session=None):
    if threading.current_thread() is not threading.main_thread():
        return

    def handler(signum, frame):
        if signum == signal.SIGHUP and session is not None:
            session.hangup()                    # ssh-session: the viewer left; the grace period keeps the session
        else:
            app.request_stop("stopped")

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):     # a closed terminal stops it cleanly too
        signal.signal(signum, handler)


def attach(*, opener=None, out=None, home_dir=None, print_url=False, marker=None):
    """open with an engine already running: a takeover through the control socket, then /usr/bin/open (or, with
    print_url, the URL on out instead).

    open holds run/realdata.lock shared from cli.main until it exits (DESIGN.md 6.8), and this path waits on nothing
    after the hand-over. server.run checked the marker just before; at marker it is checked once more after the
    takeover's reply (which can take control.CONNECTION_TIMEOUT_S) and before the hand-over: a run announced
    meanwhile refuses with run_marker_present or run_marker_unreadable, and no URL goes to /usr/bin/open or out
    for an engine that is freezing for the run. The takeover itself has happened (the engine paused, earlier codes
    and tokens dead)."""
    out = sys.stdout if out is None else out
    reply = control.request("attach", home_dir)
    if reply is None:
        raise SuiteError("control_unavailable")
    port, code = reply.get("port"), reply.get("code")
    if (not reply.get("ok") or type(port) is not int or not 0 < port <= 65535 or not isinstance(code, str)
            or not auth_module.CODE_RE.fullmatch(code)):
        raise SuiteError("control_failed")
    if marker is not None:
        runmarker.require_absent(marker)
    if print_url:
        guard.seal()
        out.write(bootstrap_url(port, code) + "\n")
    else:
        guard.permit_loopback_port(port)               # the guard checks the URL's port against its permits
        (opener or system_opener)([OPEN_ARGV0, bootstrap_url(port, code)])
        guard.seal()
    out.write("attached port=%d\n" % port)
    out.flush()
    return EXIT_OK
