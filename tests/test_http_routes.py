"""I-7 and the pieces of the local API that need no running server (DESIGN.md 9.1, 9.2).

The closed route table and command enum are asserted by exact equality against lists typed here from the
design, plus the forbidden-name test; the static manifest loader, bootstrap codes and tokens, nonces and
rate limits are tested directly; the server class is checked for its loopback bind and its overrides in
a fresh engine-mode child.
"""

import ast
import io
import json
import os
import socket
import threading
import time
import unittest

from betangel_suite import guard
from betangel_suite.api import auth, routes, server, static
from betangel_suite.errors import CODES, SuiteError
from tests import ROOT, make_home
from tests import test_http_support as support
from tests.test_guard import checks

API_DIR = os.path.join(ROOT, "betangel_suite", "api")
DESIGN_ROUTES = {
    ("POST", "/api/v1/bootstrap"): "bootstrap",
    ("GET", "/api/v1/stream"): "stream",
    ("POST", "/api/v1/query"): "query",
    ("POST", "/api/v1/command"): "command",
}
DESIGN_COMMANDS = ("open_market", "play", "pause", "set_speed", "seek", "jump", "step", "subscribe", "claim_control",
                   "place", "cancel", "cancel_side", "cancel_all", "stop", "resume", "void_and_rewind", "report_problem",
                   "set_prefs", "export_csv")
PHASE_0B_COMMANDS = {"open_market": {"seed": int}, "play": {}, "pause": {}, "set_speed": {"speed_x100": int},
                     "stop": {}}
DESIGN_QUERIES = ("session", "catalogue", "journal", "green_up_preview")       # 9.1: read-only queries
FORBIDDEN = ("live", "account", "funds", "login", "kill", "upload", "share")


def sources():
    for name in sorted(os.listdir(API_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(API_DIR, name), encoding="utf-8") as handle:
                yield name, handle.read()


class RouteTableTests(unittest.TestCase):
    """I-7: no live route; the table and the enum are closed."""

    def test_route_table_is_exactly_the_design(self):
        self.assertEqual(routes.ROUTES, DESIGN_ROUTES)

    def test_command_enum_is_exactly_the_design(self):
        self.assertEqual(routes.COMMANDS, DESIGN_COMMANDS)
        self.assertEqual(routes.EXPLORATION_COMMANDS, ("replace",))
        self.assertNotIn("replace", routes.COMMANDS)
        self.assertEqual(routes.IMPLEMENTED, PHASE_0B_COMMANDS)
        self.assertEqual(routes.CONTROL_COMMANDS, ("attach", "new_code", "pause", "stop"))
        from betangel_suite import engine
        self.assertEqual(set(engine.COMMANDS), set(PHASE_0B_COMMANDS))

    def test_query_enum_is_exactly_the_design(self):
        self.assertEqual(routes.QUERIES, DESIGN_QUERIES)
        self.assertEqual(routes.IMPLEMENTED_QUERIES, ("session",))

    def test_static_paths_never_overlap_the_routes(self):
        if not os.path.exists(os.path.join(ROOT, "ui", "manifest.json")):
            self.skipTest("no ui/ yet")
        table = static.load(os.path.join(ROOT, "ui"))
        self.assertFalse(set(table) & {path for _method, path in routes.ROUTES})
        self.assertFalse([path for path in table if path.lower().startswith("/api/") or path.lower() == "/api"])

    def test_no_route_command_or_query_name_holds_a_forbidden_word(self):
        self.assertEqual(routes.FORBIDDEN_WORDS, FORBIDDEN)
        names = [path for _method, path in routes.ROUTES] + list(routes.ROUTES.values()) + list(routes.COMMANDS)
        names += list(routes.EXPLORATION_COMMANDS) + list(routes.QUERIES) + list(routes.CONTROL_COMMANDS)
        manifest = os.path.join(ROOT, "ui", "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as handle:
                names += ["/" + entry["path"] for entry in json.load(handle)["files"]]
        for name in names:
            for word in FORBIDDEN:
                self.assertNotIn(word, name.lower(), name)

    def test_api_paths_appear_only_in_the_route_table(self):
        # Every "/api/..." text in the API package is one of the four routes, written once, in routes.ROUTES.
        found = []
        for name, text in sources():
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/api"):
                    found.append((name, node.value))
        self.assertEqual(sorted(found), sorted(("routes.py", path) for _method, path in DESIGN_ROUTES))

    def test_handler_methods_are_closed(self):
        methods = {name for name in vars(server.Handler) if name.startswith("do_")}
        self.assertEqual(methods, {"do_GET", "do_POST", "do_OPTIONS", "do_HEAD", "do_PUT", "do_DELETE", "do_PATCH",
                                   "do_TRACE", "do_CONNECT"})
        for name in methods - {"do_GET", "do_POST"}:
            self.assertIs(getattr(server.Handler, name), server.Handler._not_allowed, name)

    def test_every_api_code_is_listed(self):
        for code in server.STATUS_CODES.values():
            self.assertIn(code, CODES)
        for name, text in sources():
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in (
                        "refused", "fail", "SuiteError"):
                    for argument in node.args:
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                            self.assertIn(argument.value, CODES, name)

    def test_no_name_lookup_and_no_tracebacks_in_the_server(self):
        for name, text in sources():
            used = set()
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Attribute):
                    used.add(node.attr)
                elif isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    used |= {alias.name for alias in node.names} | {getattr(node, "module", None) or ""}
            self.assertFalse(used & {"getfqdn", "gethostbyname", "gethostbyaddr", "traceback", "print_exc",
                                     "format_exc", "print", "logging"}, name)
        self.assertEqual(server.Handler.protocol_version, "HTTP/1.1")
        self.assertIs(server.SuiteHTTPServer.allow_reuse_port, False)
        self.assertEqual(server.SuiteHTTPServer.address_family, socket.AF_INET)
        self.assertTrue(server.SuiteHTTPServer.daemon_threads)
        self.assertEqual({name.lower(): value for name, value in server.SECURITY_HEADERS}, support.SECURITY_HEADERS)


class ServerBindTests(unittest.TestCase):
    """I-4 on the server class: 127.0.0.1 only, getsockname asserted, no getfqdn, no fallback port."""

    def test_binds_loopback_only(self):
        home = support.short_home(self)
        results = checks(self, home, body="""
import socket
from betangel_suite.api import server
def no_lookup(*args):
    raise AssertionError("getfqdn called")
socket.getfqdn = no_lookup
attempt("unpermitted", lambda: server.SuiteHTTPServer(0, None))
guard.permit_loopback_port(0)
httpd = server.SuiteHTTPServer(0, None)
results["address"] = list(httpd.socket.getsockname())
results["names"] = [httpd.server_name, httpd.server_port == httpd.socket.getsockname()[1]]
results["family"] = httpd.socket.family == socket.AF_INET
results["reuse_port"] = httpd.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT)
port = httpd.server_port
guard.permit_loopback_port(port)
attempt("in_use", lambda: server.SuiteHTTPServer(port, None))
attempt("bad_port", lambda: server.SuiteHTTPServer(70000, None))
httpd.server_close()
# getsockname is asserted after the bind: a socket that reports another host, or (for a fixed port) another
# port, refuses the start with bind_refused and is closed.
class Reporting:
    def __init__(self, real, address):
        self._real, self._address = real, address
    def getsockname(self):
        return self._address(self._real.getsockname())
    def __getattr__(self, name):
        return getattr(self._real, name)
def lying(address):
    seen = []
    class Lying(server.SuiteHTTPServer):
        def server_bind(self):
            real = self.socket
            seen.append(real)
            self.socket = Reporting(real, address)
            try:
                super().server_bind()
            finally:
                self.socket = real
    return Lying, seen
Lying, seen = lying(lambda real: ("127.0.0.2", real[1]))
attempt("other_host", lambda: Lying(0, None))
results["other_host_closed"] = [sock.fileno() for sock in seen]
Lying, seen = lying(lambda real: (real[0], real[1] + 1))
attempt("other_port", lambda: Lying(port, None))
results["other_port_closed"] = [sock.fileno() for sock in seen]
Lying, seen = lying(lambda real: real)
honest = Lying(port, None)
results["honest"] = [honest.server_port == port, honest.server_name]
honest.server_close()
""")
        self.assertEqual(results["unpermitted"], "bind_refused")
        self.assertEqual(results["address"][0], "127.0.0.1")
        self.assertEqual(results["names"], ["127.0.0.1", True])
        self.assertTrue(results["family"])
        self.assertEqual(results["reuse_port"], 0)
        self.assertEqual(results["in_use"], "port_in_use")
        self.assertEqual(results["bad_port"], "bad_arguments")
        self.assertEqual((results["other_host"], results["other_host_closed"]), ("bind_refused", [-1]))
        self.assertEqual((results["other_port"], results["other_port_closed"]), ("bind_refused", [-1]))
        self.assertEqual(results["honest"], [True, "127.0.0.1"])


class StaticTests(unittest.TestCase):

    def ui(self, files, manifest):
        home = make_home(self)
        directory = os.path.join(home, "ui")
        os.makedirs(directory)
        for name, data in files.items():
            path = os.path.join(directory, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        if manifest is not None:
            with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as handle:
                handle.write(manifest if isinstance(manifest, str) else json.dumps(manifest))
        return directory

    def entry(self, path, kind="text/javascript; charset=utf-8"):
        return {"path": path, "type": kind}

    def test_exact_names_and_index(self):
        directory = self.ui({"index.html": b"<!doctype html>", "app.js": b"export {};", "sounds/tick.wav": b"RIFF"},
                            {"files": [self.entry("index.html", "text/html; charset=utf-8"), self.entry("app.js"),
                                       self.entry("sounds/tick.wav", "audio/wav")]})
        table = static.load(directory)
        self.assertEqual(set(table), {"/", "/index.html", "/app.js", "/sounds/tick.wav"})
        self.assertEqual(table["/"], (b"<!doctype html>", "text/html; charset=utf-8"))
        self.assertEqual(table["/app.js"], (b"export {};", "text/javascript; charset=utf-8"))

    def test_missing_manifest_serves_nothing(self):
        self.assertEqual(static.load(self.ui({"index.html": b"x"}, None)), {})

    def test_malformed_manifests_refuse_the_start(self):
        good = self.entry("index.html", "text/html; charset=utf-8")
        cases = {
            "not_json": "{",
            "duplicate_key": '{"files": [], "files": []}',
            "extra_key": {"files": [good], "x": 1},
            "empty": {"files": []},
            "no_index": {"files": [self.entry("app.js")]},
            "dotdot": {"files": [good, self.entry("../AGENTS.md")]},
            "hidden": {"files": [good, self.entry(".env")]},
            "absolute": {"files": [good, self.entry("/etc/hosts")]},
            "backslash": {"files": [good, self.entry("a\\b.js")]},
            "query": {"files": [good, self.entry("app.js?x")]},
            "unknown_type": {"files": [good, self.entry("app.js", "application/x-sh")]},
            "duplicate": {"files": [good, self.entry("app.js"), self.entry("app.js")]},
            "entry_keys": {"files": [good, {"path": "app.js"}]},
            "missing_file": {"files": [good, self.entry("gone.js")]},
            "directory": {"files": [good, self.entry("sounds")]},
            "api_route": {"files": [good, self.entry("api/v1/stream", "application/json")]},
            "api_prefix": {"files": [good, self.entry("api/app.js")]},
            "api_upper": {"files": [good, self.entry("API/v1/command", "application/json")]},
        }
        for name, manifest in cases.items():
            directory = self.ui({"index.html": b"x", "app.js": b"y", "sounds/a.wav": b"z", "api/v1/stream": b"{}",
                                 "api/app.js": b"y", "API/v1/command": b"{}"}, manifest)
            with self.assertRaises(SuiteError, msg=name) as caught:
                static.load(directory)
            self.assertEqual(caught.exception.code, "manifest_invalid", name)

    def test_symlinks_and_large_files_are_refused(self):
        good = self.entry("index.html", "text/html; charset=utf-8")
        directory = self.ui({"index.html": b"x"}, {"files": [good, self.entry("link.js")]})
        outside = os.path.join(os.path.dirname(directory), "outside.js")
        with open(outside, "w") as handle:
            handle.write("outside")
        os.symlink(outside, os.path.join(directory, "link.js"))
        with self.assertRaises(SuiteError):
            static.load(directory)
        directory = self.ui({"index.html": b"x", "big.js": b"x" * (static.MAX_FILE_BYTES + 1)},
                            {"files": [good, self.entry("big.js")]})
        with self.assertRaises(SuiteError):
            static.load(directory)

    def test_the_repo_ui_manifest_loads(self):
        if not os.path.exists(os.path.join(ROOT, "ui", "manifest.json")):
            self.skipTest("no ui/ yet")
        table = static.load(os.path.join(ROOT, "ui"))
        self.assertIn("/", table)


class AuthTests(unittest.TestCase):

    def setUp(self):
        self.now = [1000.0]
        self.registered = []
        self.auth = auth.Auth(register=self.registered.append, clock=lambda: self.now[0])

    def test_codes_are_single_use_short_lived_and_registered(self):
        code = self.auth.issue_code()
        self.assertRegex(code, r"\A[A-Za-z0-9_-]{22}\Z")
        token = self.auth.exchange(code)
        self.assertRegex(token, r"\A[A-Za-z0-9_-]{43}\Z")
        self.assertEqual(self.registered, [code, token])
        self.assertIsNone(self.auth.exchange(code))
        self.assertEqual(auth.CODE_TTL_S, 120)              # 9.2 item 1: valid for 120 s
        late = self.auth.issue_code()
        self.now[0] += 120
        self.assertIsNone(self.auth.exchange(late))
        fresh = self.auth.issue_code()
        self.now[0] += 119
        self.assertIsNotNone(self.auth.exchange(fresh))
        for bad in (None, 7, "", "x" * 22 + "\n", "é" * 22, token):
            self.assertIsNone(self.auth.exchange(bad), bad)

    def test_header_checks(self):
        token = self.auth.exchange(self.auth.issue_code())
        self.assertEqual(self.auth.check("Bearer " + token), token)
        for header in (None, token, "bearer " + token, "Bearer  " + token, "Bearer " + token + " ", "Basic " + token,
                       "Bearer " + token[:-1], "Bearer " + token[:-1] + "é"):
            self.assertIsNone(self.auth.check(header), header)

    def test_takeover_invalidates_every_code_and_token(self):
        token = self.auth.exchange(self.auth.issue_code())
        spare = self.auth.issue_code()
        self.assertTrue(self.auth.is_controller(token))
        fresh = self.auth.issue_code(takeover=True)
        self.assertFalse(self.auth.valid(token))
        self.assertIsNone(self.auth.check("Bearer " + token))
        self.assertIsNone(self.auth.exchange(spare))
        self.assertIsNotNone(self.auth.exchange(fresh))

    def test_one_controller_while_it_is_watching(self):
        first = self.auth.exchange(self.auth.issue_code())
        self.assertFalse(self.auth.controller_watching())
        self.assertTrue(self.auth.stream_started(first))
        self.assertTrue(self.auth.controller_watching())
        second = self.auth.exchange(self.auth.issue_code())
        self.assertTrue(self.auth.is_controller(first))
        self.assertFalse(self.auth.is_controller(second))
        self.assertTrue(self.auth.stream_started(second))
        self.auth.stream_ended(first)                       # the controller stopped watching
        self.assertFalse(self.auth.controller_watching())
        third = self.auth.exchange(self.auth.issue_code())
        self.assertTrue(self.auth.is_controller(third))
        self.auth.stream_ended(second)
        for _ in range(auth.MAX_STREAMS_PER_TOKEN):
            self.assertTrue(self.auth.stream_started(third))
        self.assertFalse(self.auth.stream_started(third))
        self.assertFalse(self.auth.stream_started("B" * 43))
        self.assertTrue(self.auth.controller_watching())

    def test_evicting_the_watching_controller_stops_the_watch(self):
        first = self.auth.exchange(self.auth.issue_code())
        self.assertTrue(self.auth.stream_started(first))
        for _ in range(auth.MAX_TOKENS):
            self.auth.exchange(self.auth.issue_code())
        self.assertFalse(self.auth.valid(first))
        self.assertFalse(self.auth.controller_watching())

    def test_bounded_numbers_of_codes_and_tokens(self):
        codes = [self.auth.issue_code() for _ in range(auth.MAX_CODES + 3)]
        self.assertIsNone(self.auth.exchange(codes[0]))
        self.assertEqual(self.auth.counts()[0], auth.MAX_CODES)
        tokens = [self.auth.exchange(self.auth.issue_code()) for _ in range(auth.MAX_TOKENS + 2)]
        self.assertFalse(self.auth.valid(tokens[0]))
        self.assertTrue(self.auth.valid(tokens[-1]))
        self.assertEqual(self.auth.counts()[1], auth.MAX_TOKENS)


class WatchingTests(unittest.TestCase):
    """App.watching_changed: the engine's last watched state is the controller's current one, whatever the
    order in which stream, bootstrap and takeover threads run (section 8.6, I-19)."""

    def test_a_stale_state_never_lands_after_a_fresh_one(self):
        entered, calls = threading.Event(), []

        class Engine:
            first_false = True

            def set_watched(self, watched):         # the first False stands for a thread switch mid-update
                if not watched and Engine.first_false:
                    Engine.first_false = False
                    entered.set()
                    time.sleep(0.2)
                calls.append(watched)

        app = routes.App(Engine(), auth.Auth(register=lambda value: None), {})
        token = app.auth.exchange(app.auth.issue_code())
        self.assertTrue(app.stream_open(token))
        closing = threading.Thread(target=app.stream_close, args=(token,))    # the old stream ends ...
        closing.start()
        self.assertTrue(entered.wait(5))
        opening = threading.Thread(target=app.stream_open, args=(token,))     # ... as the reconnect opens
        opening.start()
        closing.join(5)
        opening.join(5)
        self.assertTrue(app.auth.controller_watching())
        self.assertEqual(calls[-1], True, calls)
        self.assertEqual(calls, [True, False, True])


class NonceAndRateTests(unittest.TestCase):

    def test_nonce_cache_returns_the_first_result(self):
        cache = routes.NonceCache()
        new, entry = cache.claim("nonce-001")
        self.assertTrue(new)
        cache.finish("nonce-001", entry, {"ok": True})
        new, again = cache.claim("nonce-001")
        self.assertFalse(new)
        self.assertEqual(again[1], {"ok": True})
        new, entry = cache.claim("nonce-002")
        cache.forget("nonce-002", entry)
        self.assertTrue(cache.claim("nonce-002")[0])
        for index in range(2000):
            new, entry = cache.claim("other-%04d" % index)
            cache.finish("other-%04d" % index, entry, {"ok": True})
        new, again = cache.claim("nonce-001")                 # kept for the process's life: never evicted
        self.assertFalse(new)
        self.assertTrue(again[0].is_set())
        self.assertEqual(again[1], {"ok": True})

    def test_a_replay_of_an_in_flight_nonce_waits_for_its_result(self):
        cache = routes.NonceCache()
        new, entry = cache.claim("nonce-001")
        self.assertTrue(new)
        claimed, seen = threading.Event(), []

        def replay():
            new_again, waiting = cache.claim("nonce-001")
            claimed.set()
            seen.append((new_again, waiting[0].wait(5), waiting[1]))   # woken by finish(), not timed out

        thread = threading.Thread(target=replay)
        thread.start()
        self.assertTrue(claimed.wait(5))
        self.assertFalse(entry[0].is_set())                   # nothing has woken the replay yet
        cache.finish("nonce-001", entry, {"ok": True})
        thread.join(5)
        self.assertEqual(seen, [(False, True, {"ok": True})])
        new, finished = cache.claim("nonce-001")              # later replays get the small finished entry
        self.assertFalse(new)
        self.assertIsNot(finished, entry)
        self.assertTrue(finished[0].is_set())
        self.assertEqual(finished[1], {"ok": True})

    def test_a_replayed_nonce_does_nothing_new_after_many_other_commands(self):
        calls = []

        class Engine:
            def command(self, name, args):
                calls.append(name)
                return {"ok": True, "market_id": "1.999%06d" % len(calls)} if name == "open_market" else {"ok": True}

        app = routes.App(Engine(), auth.Auth(register=lambda value: None), {})
        token = app.auth.exchange(app.auth.issue_code())
        first = {"nonce": "first-nonce", "command": "open_market", "args": {"seed": 1}}
        self.assertEqual(app.command(token, first), (200, {"ok": True, "market_id": "1.999000001"}))
        for index in range(1100):                           # more than the 1024 the old bounded cache kept
            body = {"nonce": "other-%04d" % index, "command": "pause", "args": {}}
            self.assertEqual(app.command(token, body), (200, {"ok": True}))
        self.assertEqual(app.command(token, first), (200, {"ok": True, "market_id": "1.999000001"}))
        self.assertEqual(len(calls), 1101)

    def test_rate_limiter_is_a_sliding_window(self):
        now = [0.0]
        limiter = routes.RateLimiter({"bootstrap": (3, 10.0)}, clock=lambda: now[0])
        self.assertEqual([limiter.allow("bootstrap") for _ in range(4)], [True, True, True, False])
        now[0] = 10.5
        self.assertTrue(limiter.allow("bootstrap"))

    def test_args_must_match_the_schema_exactly(self):
        self.assertTrue(routes.args_ok({"seed": 3}, {"seed": int}))
        for args in ({"seed": True}, {"seed": 3.0}, {"seed": 3, "x": 1}, {}, [], None):
            self.assertFalse(routes.args_ok(args, {"seed": int}), args)
        self.assertTrue(routes.args_ok({}, {}))


class HostAndTypeTests(unittest.TestCase):

    def test_host_values(self):
        for value in ("127.0.0.1:8765", "localhost:8765", "127.0.0.1:1", "localhost:65535"):
            self.assertEqual(server.host_ok([value]), value)
        for values in (None, [], ["127.0.0.1"], ["127.0.0.1:0"], ["127.0.0.1:65536"], ["127.0.0.1:08765"],
                       ["evil.example:8765"], ["127.0.0.1:8765", "127.0.0.1:8765"], ["127.0.0.1:8765 "],
                       ["[::1]:8765"], ["127.0.0.2:8765"], ["LOCALHOST:8765"], ["127.0.0.1:+80"]):
            self.assertIsNone(server.host_ok(values), values)

    def test_json_content_types(self):
        for value in ("application/json", "application/json; charset=utf-8", "Application/JSON;charset=UTF-8"):
            self.assertTrue(server.json_type_ok([value]), value)
        for values in (None, ["text/plain"], ["application/json", "application/json"], ["application/json; x=1"],
                       ["application/json; charset=utf-8; charset=utf-8"], ["application/jsonp"]):
            self.assertFalse(server.json_type_ok(values), values)

    def test_bootstrap_url_shape_is_the_one_the_guard_allows(self):
        url = server.bootstrap_url(8765, "a" * 22)
        self.assertTrue(guard.engine_argv_ok([server.OPEN_ARGV0, url], ("/h/.local/state/betangel-suite",), {8765}))


class RequestLineRefusalTests(unittest.TestCase):
    """9.1 and 9.3 on whichever interpreter runs this suite (bin/suite test --py311 included): a request line
    the base class refuses still gets a status line and every 9.3 header. The socket-level checks in
    test_http_security.py run the server through the launcher, which is always 3.13, and 3.11's parser
    refuses a bad line or version, and HTTP/2.0, before it sets request_version (Astra's review of #4)."""

    def respond(self, head):
        """What Handler writes for one request head, fed in memory (no socket)."""
        class Connection:
            def settimeout(self, value):
                pass

        class Server:
            def __init__(self):
                self.lines = []

            def log(self, text):
                self.lines.append(text)

        handler = server.Handler.__new__(server.Handler)
        handler.connection, handler.server = Connection(), Server()
        handler.rfile, handler.wfile = io.BufferedReader(io.BytesIO(head)), io.BytesIO()
        handler.handle_one_request()
        return handler.wfile.getvalue(), handler.server.lines

    def test_request_line_refusals_have_a_status_line_and_every_header(self):
        cases = {
            b"GARBAGE\r\n\r\n": (400, "bad_request"),
            b"GET / HTTP/x.y\r\n\r\n": (400, "bad_request"),
            b"GET / HTTP/1.1 extra\r\n\r\n": (400, "bad_request"),
            b"GET / HTTP/2.0\r\n\r\n": (505, "http_version_not_supported"),
            b"POST /\r\n": (400, "bad_request"),
            b"GET /\r\n": (400, "bad_request"),           # HTTP/0.9, refused by Handler.parse_request
        }
        for head, (status, code) in cases.items():
            with self.subTest(head=head):
                written, logged = self.respond(head)
                top, _, body = written.partition(b"\r\n\r\n")
                lines = top.decode("latin-1").split("\r\n")
                self.assertTrue(lines[0].startswith("HTTP/1.1 %d " % status), lines[0])
                headers = [(name.lower(), value) for name, _, value in (line.partition(": ") for line in lines[1:])]
                for name, value in support.SECURITY_HEADERS.items():
                    self.assertEqual([v for n, v in headers if n == name], [value], name)
                self.assertEqual([v for n, v in headers if n == "content-type"], ["application/json"])
                self.assertEqual([v for n, v in headers if n == "connection"], ["close"])
                self.assertEqual(json.loads(body), {"ok": False, "code": code})
                self.assertEqual(logged, ["http:%d:%s" % (status, code)])


if __name__ == "__main__":
    unittest.main()
