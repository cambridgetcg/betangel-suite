"""DESIGN.md 11 group 6: the local API's security against a real server (9.1-9.3; I-4, I-7, I-16).

One `bin/suite serve --port 0` child per class, synthetic only, on an ephemeral 127.0.0.1 port under a
temporary HOME; an unguarded client child (tests/test_http_support.py) makes the requests, because this
test runner's guard refuses every connect. Bootstrap codes come from the control socket, as open and
ssh-session get theirs; no client script prints a code or a token.
"""

import os
import unittest

from tests import test_http_support as support


class _ServerCase(unittest.TestCase):
    """A shared serve child for the class, stopped (SIGTERM) and checked for a clean exit afterwards."""

    @classmethod
    def setUpClass(cls):
        cls._cleanup = support._Cleanup()
        try:
            cls.home = support.short_home(cls._cleanup)
            cls.child, cls.port = support.serve(cls._cleanup, cls.home)
        except BaseException:
            cls._cleanup.run()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls.exit_status = cls.child.terminate()
        finally:
            cls._cleanup.run()

    def client(self, script):
        return support.client(self, self.home, self.port, script)


class HeaderAndRoutingChecks:
    """9.1 routes and 9.3 headers, including errors raised before routing."""

    def test_pre_routing_errors_are_code_only_json_with_every_header(self):
        results = self.client(r'''
cases = {
    "garbage": b"GARBAGE\r\n\r\n",
    "uri_too_long": b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT,
    "header_too_long": b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Long: " % PORT + b"b" * 70000 + b"\r\n\r\n",
    "http2": b"GET / HTTP/2.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT,
    "bad_version": b"GET / HTTP/x.y\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT,
    "unknown_method": b"BREW / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT,
    "http09": b"GET /\r\n",
    "expect": b"POST /api/v1/bootstrap HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nExpect: 100-continue\r\n\r\n" % PORT,
}
for name, data in cases.items():
    status, found, body = parse(raw(data))
    results[name] = [status, jbody(body), security_headers_ok(found), found.get("content-type")]
''')
        expected = {"garbage": (400, "bad_request"), "uri_too_long": (414, "uri_too_long"),
                    "header_too_long": (431, "headers_too_large"), "http2": (505, "http_version_not_supported"),
                    "bad_version": (400, "bad_request"), "unknown_method": (501, "unsupported_method"),
                    "http09": (400, "bad_request"), "expect": (417, "expectation_failed")}
        for name, (status, code) in expected.items():
            got = results[name]
            self.assertEqual(got[0], status, name)
            self.assertEqual(got[1], {"ok": False, "code": code}, name)
            self.assertTrue(got[2], name)
            self.assertEqual(got[3], ["application/json"], name)

    def test_closed_routes_methods_and_no_cors(self):
        results = self.client(r'''
token = bootstrap()
for name, method, path in (("options", "OPTIONS", "/api/v1/command"), ("head", "HEAD", "/"),
                           ("put", "PUT", "/api/v1/command"), ("delete", "DELETE", "/api/v1/stream"),
                           ("get_command", "GET", "/api/v1/command"), ("post_stream", "POST", "/api/v1/stream"),
                           ("unknown", "GET", "/api/v1/live"), ("traversal", "GET", "/../README.md"), ("dotdot_ui", "GET", "/ui/../AGENTS.md"),
                           ("readme", "GET", "/README.md"), ("v2", "POST", "/api/v2/command"),
                           ("trailing", "POST", "/api/v1/command/")):
    headers = base_headers()
    headers["Access-Control-Request-Method"] = "POST"
    status, found, body = request(method, path, b"{}" if method in ("POST", "PUT") else None, headers=headers,
                                  token=token)
    results[name] = [status, jbody(body) if body else None, security_headers_ok(found)]
# A valid token in the query string and none in a header: never a stream (9.2 item 1: no query-string tokens).
# A raw request with a short timeout, so that a regression fails here at once instead of hanging on a stream.
status, found, body = parse(raw(b"GET /api/v1/stream?token=%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n"
                                % (token.encode(), PORT), timeout=3))
results["query_string"] = [status, jbody(body) if body else None, security_headers_ok(found)]
''')
        for name in ("options", "put", "delete", "get_command", "post_stream"):
            self.assertEqual(results[name][:2], [405, {"ok": False, "code": "method_not_allowed"}], name)
        self.assertEqual(results["head"][0], 405)
        for name in ("unknown", "query_string", "traversal", "dotdot_ui", "readme", "v2", "trailing"):
            self.assertEqual(results[name][:2], [404, {"ok": False, "code": "not_found"}], name)
        for name, got in results.items():
            self.assertTrue(got[2], name)

    def test_static_files_come_from_the_manifest_by_exact_name(self):
        results = self.client(r'''
manifest = json.load(open(os.path.join(ROOT, "ui", "manifest.json")))
results["paths"] = {}
for entry in manifest["files"]:
    status, found, body = request("GET", "/" + entry["path"], headers={"Host": "127.0.0.1:%d" % PORT})
    on_disk = open(os.path.join(ROOT, "ui", entry["path"]), "rb").read()
    results["paths"][entry["path"]] = [status, found.get("content-type") == [entry["type"]], body == on_disk,
                                       security_headers_ok(found)]
status, found, body = request("GET", "/", headers={"Host": "127.0.0.1:%d" % PORT})
results["root"] = [status, found.get("content-type"), body == open(os.path.join(ROOT, "ui", "index.html"), "rb").read(),
                   security_headers_ok(found)]
status, _f, _b = request("GET", "/", headers={"Host": "localhost:%d" % PORT})
results["localhost"] = status
for name, path in (("unlisted", "/tests/index.html"), ("case", "/INDEX.HTML"), ("slash", "/index.html/"),
                   ("encoded", "/index%2Ehtml"), ("double", "//index.html/..")):
    results[name] = request("GET", path, headers={"Host": "127.0.0.1:%d" % PORT})[0]
'''.replace("ROOT", repr(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        self.assertTrue(results["paths"])
        for path, got in results["paths"].items():
            self.assertEqual(got, [200, True, True, True], path)
        self.assertEqual(results["root"], [200, ["text/html; charset=utf-8"], True, True])
        self.assertEqual(results["localhost"], 200)
        for name in ("unlisted", "case", "slash", "encoded", "double"):
            self.assertEqual(results[name], 404, name)


class RequestChecks:
    """9.2 items 2-6: Host, Origin, Content-Type, body size and strict JSON, against the real server."""

    def test_host_must_be_loopback_with_a_numeric_port(self):
        results = self.client(r'''
token = bootstrap()
for name, host in (("evil", "evil.example:%d" % PORT), ("no_port", "127.0.0.1"), ("rebind", "attacker.invalid"),
                   ("big_port", "127.0.0.1:99999"), ("zero_port", "127.0.0.1:0"), ("ipv6", "[::1]:%d" % PORT),
                   ("upper", "LOCALHOST:%d" % PORT), ("space", "127.0.0.1 :%d" % PORT)):
    status, found, body = request("POST", "/api/v1/query", {"query": "session", "args": {}},
                                  headers=dict(base_headers(), Host=host), token=token)
    results[name] = [status, jbody(body), security_headers_ok(found)]
session = {"query": "session", "args": {}}
results["localhost"] = request("POST", "/api/v1/query", session, headers=base_headers("localhost:%d" % PORT),
                               token=token)[0]
results["other_port"] = request("POST", "/api/v1/query", session, headers=base_headers("127.0.0.1:8766"),
                                token=token)[0]
status, found, body = parse(raw(b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nHost: evil.example\r\n\r\n" % PORT))
results["two_hosts"] = [status, jbody(body)]
status, found, body = parse(raw(b"GET / HTTP/1.1\r\n\r\n"))
results["missing"] = [status, jbody(body)]
''')
        for name in ("evil", "no_port", "rebind", "big_port", "zero_port", "ipv6", "upper", "space"):
            self.assertEqual(results[name][:2], [421, {"ok": False, "code": "bad_host"}], name)
            self.assertTrue(results[name][2], name)
        for name in ("two_hosts", "missing"):
            self.assertEqual(results[name], [421, {"ok": False, "code": "bad_host"}], name)
        self.assertEqual((results["localhost"], results["other_port"]), (200, 200))

    def test_origin_is_required_on_post_and_must_match_the_host(self):
        results = self.client(r'''
token = bootstrap()
body = {"query": "session", "args": {}}
def post(origin, host=None):
    headers = base_headers(host)
    if origin is None:
        del headers["Origin"]
    else:
        headers["Origin"] = origin
    return request("POST", "/api/v1/query", body, headers=headers, token=token)
for name, origin in (("missing", None), ("evil", "http://evil.example"), ("null", "null"),
                     ("https", "https://127.0.0.1:%d" % PORT), ("other_host", "http://localhost:%d" % PORT),
                     ("other_port", "http://127.0.0.1:1")):
    status, found, payload = post(origin)
    results[name] = [status, jbody(payload), security_headers_ok(found)]
results["match"] = post("http://127.0.0.1:%d" % PORT)[0]
results["match_localhost"] = post("http://localhost:%d" % PORT, host="localhost:%d" % PORT)[0]
stream_headers = {"Host": "127.0.0.1:%d" % PORT, "Origin": "http://evil.example"}
status, found, payload = request("GET", "/api/v1/stream", headers=stream_headers, token=token)
results["stream_evil"] = [status, jbody(payload)]
status, found, payload = parse(raw(
    b"POST /api/v1/bootstrap HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\n"
    b"Origin: http://evil.example\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}" % (PORT, PORT)))
results["two_origins"] = [status, jbody(payload)]
''')
        for name in ("missing", "evil", "null", "https", "other_host", "other_port"):
            self.assertEqual(results[name][:2], [403, {"ok": False, "code": "bad_origin"}], name)
            self.assertTrue(results[name][2], name)
        for name in ("stream_evil", "two_origins"):
            self.assertEqual(results[name], [403, {"ok": False, "code": "bad_origin"}], name)
        self.assertEqual((results["match"], results["match_localhost"]), (200, 200))

    def test_posts_must_be_json_and_bounded(self):
        results = self.client(r'''
token = bootstrap()
def post(data, content_type="application/json", path="/api/v1/query", extra=None):
    headers = base_headers()
    if content_type is None:
        del headers["Content-Type"]
    else:
        headers["Content-Type"] = content_type
    headers.update(extra or {})
    status, found, payload = request("POST", path, data, headers=headers, token=token)
    return [status, jbody(payload) if payload else None, security_headers_ok(found)]
good = json.dumps({"query": "session", "args": {}}).encode()
for name, kind in (("text", "text/plain"), ("form", "application/x-www-form-urlencoded"),
                   ("multipart", "multipart/form-data; boundary=x"), ("missing_type", None),
                   ("latin1", "application/json; charset=latin-1"), ("jsonish", "application/jsonx"),
                   ("two_params", "application/json; charset=utf-8; x=1")):
    results[name] = post(good, kind)
results["charset"] = post(good, "application/json; charset=utf-8")[0]
results["upper"] = post(good, "Application/JSON")[0]
results["too_large"] = post(b'{"query": "' + b"x" * 70000 + b'", "args": {}}')
for name, data in (("not_json", b"query=session"), ("nan", b'{"query": "session", "args": {}, "x": NaN}'),
                   ("duplicate", b'{"query": "session", "query": "session", "args": {}}'),
                   ("array", b'[1, 2]'), ("bad_utf8", b'{"query": "\xff", "args": {}}'),
                   ("infinity", b'{"query": "session", "args": {"x": 1e400}}')):
    results[name] = post(data)
results["extra_key"] = post(b'{"query": "session", "args": {}, "extra": 1}')
results["wrong_type"] = post(b'{"query": 1, "args": {}}')
results["unknown_query"] = post(b'{"query": "funds", "args": {}}')
sock_data = (b"POST /api/v1/query HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\n"
             b"Content-Type: application/json\r\nAuthorization: Bearer %s\r\n\r\n" % (PORT, PORT, token.encode()))
status, found, payload = parse(raw(sock_data))
results["no_length"] = [status, jbody(payload)]
chunked = sock_data[:-2] + b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
status, found, payload = parse(raw(chunked))
results["chunked_body"] = [status, jbody(payload)]
status, found, payload = parse(raw(b"GET /api/v1/stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n"
                                   b"Content-Length: 5\r\n\r\nhello" % (PORT, token.encode())))
results["get_body"] = [status, jbody(payload)]
''')
        for name in ("text", "form", "multipart", "missing_type", "latin1", "jsonish", "two_params"):
            self.assertEqual(results[name][:2], [415, {"ok": False, "code": "unsupported_media_type"}], name)
            self.assertTrue(results[name][2], name)
        self.assertEqual((results["charset"], results["upper"]), (200, 200))
        self.assertEqual(results["too_large"][:2], [413, {"ok": False, "code": "body_too_large"}])
        for name in ("not_json", "nan", "duplicate", "array", "bad_utf8", "infinity"):
            self.assertEqual(results[name][:2], [400, {"ok": False, "code": "bad_json"}], name)
        for name in ("extra_key", "wrong_type"):
            self.assertEqual(results[name][:2], [400, {"ok": False, "code": "bad_args"}], name)
        self.assertEqual(results["unknown_query"][:2], [400, {"ok": False, "code": "unknown_query"}])
        self.assertEqual(results["no_length"], [411, {"ok": False, "code": "length_required"}])
        self.assertEqual(results["chunked_body"], [400, {"ok": False, "code": "bad_request"}])
        self.assertEqual(results["get_body"], [400, {"ok": False, "code": "bad_request"}])


    def test_a_refused_request_closes_its_connection(self):
        # An unread body must never become the next request: a refused POST whose body is a complete second
        # request (forged Origin, application/json) gets exactly one response, Connection: close, then EOF.
        results = self.client(r'''
inner = (b"POST /api/v1/bootstrap HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\n"
         b"Content-Type: application/json\r\nContent-Length: 20\r\n\r\n{\"code\": \"%s\"}" % (PORT, PORT, b"A" * 8))
inner_get = b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT
for name, origin, kind, body in (("bad_origin", b"http://evil.example", b"text/plain", inner),
                                 ("not_json", b"http://127.0.0.1:%d" % PORT, b"text/plain", inner_get)):
    outer = (b"POST /api/v1/bootstrap HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: %s\r\nContent-Type: %s\r\n"
             b"Content-Length: %d\r\n\r\n" % (PORT, origin, kind, len(body))) + body
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    sock.sendall(outer)                     # and nothing more: the connection stays open on this side
    data = b""
    try:
        while True:
            part = sock.recv(65536)
            if not part:
                break
            data += part
        eof = True
    except socket.timeout:
        eof = False
    sock.close()
    status, found, payload = parse(data)
    results[name] = [status, jbody(payload), found.get("connection"), data.count(b"HTTP/1.1 "), eof,
                     security_headers_ok(found)]
''')
        self.assertEqual(results["bad_origin"], [403, {"ok": False, "code": "bad_origin"}, ["close"], 1, True, True])
        self.assertEqual(results["not_json"],
                         [415, {"ok": False, "code": "unsupported_media_type"}, ["close"], 1, True, True])


class TokenTests(_ServerCase):
    """9.2 item 1: single-use codes, Bearer tokens on every API route but bootstrap, no cookies."""

    def test_bootstrap_code_is_single_use_and_tokens_are_required(self):
        results = self.client(r'''
code = new_code()
status, found, payload = request("POST", "/api/v1/bootstrap", {"code": code})
token = jbody(payload)["token"]
results["first"] = [status, sorted(jbody(payload)), len(token), security_headers_ok(found), "set-cookie" in found]
status, found, payload = request("POST", "/api/v1/bootstrap", {"code": code})
results["reused"] = [status, jbody(payload)]
for name, value in (("unknown", "A" * 22), ("short", "abc"), ("number", 7), ("token_as_code", token)):
    status, found, payload = request("POST", "/api/v1/bootstrap", {"code": value})
    results[name] = [status, jbody(payload)]
body = {"query": "session", "args": {}}
results["no_token"] = request("POST", "/api/v1/query", body)[0]
results["wrong_token"] = request("POST", "/api/v1/query", body, token="B" * 43)[0]
results["code_as_token"] = request("POST", "/api/v1/query", body, token=new_code())[0]
headers = dict(base_headers(), Authorization="bearer " + token)
results["lower_scheme"] = request("POST", "/api/v1/query", body, headers=headers)[0]
headers = dict(base_headers(), Authorization="Basic " + token)
results["basic"] = request("POST", "/api/v1/query", body, headers=headers)[0]
headers = dict(base_headers(), Cookie="token=" + token)
results["cookie"] = request("POST", "/api/v1/query", body, headers=headers)[0]
results["stream_no_token"] = request("GET", "/api/v1/stream", headers={"Host": "127.0.0.1:%d" % PORT})[0]
status, found, payload = request("POST", "/api/v1/command", {"nonce": "abcdefgh", "command": "pause", "args": {}})
results["command_no_token"] = [status, jbody(payload)]
status, found, payload = request("POST", "/api/v1/query", body, token=token)
results["good"] = [status, jbody(payload)["ok"], security_headers_ok(found), "set-cookie" in found]
''')
        self.assertEqual(results["first"], [200, ["ok", "token"], 43, True, False])
        for name in ("reused", "unknown", "short", "number", "token_as_code"):
            expected = 400 if name == "number" else 401
            self.assertEqual(results[name][0], expected, name)
        self.assertEqual(results["reused"][1], {"ok": False, "code": "bad_code"})
        for name in ("no_token", "wrong_token", "code_as_token", "lower_scheme", "basic", "cookie", "stream_no_token"):
            self.assertEqual(results[name], 401, name)
        self.assertEqual(results["command_no_token"], [401, {"ok": False, "code": "unauthorized"}])
        self.assertEqual(results["good"], [200, True, True, False])

    def test_one_controller_tab(self):
        results = self.client(r'''
first = bootstrap()
watching = Stream(first)
results["first_stream"] = watching.status
second = bootstrap()
results["second_controller"] = query(second)[1]["controller"]
results["first_controller"] = query(first)[1]["controller"]
results["second_command"] = command(second, "pause")
results["second_unimplemented"] = command(second, "claim_control")
results["first_command"] = command(first, "set_speed", {"speed_x100": 200})
watching.close()
time.sleep(0.8)
third = bootstrap()
results["third_controller"] = query(third)[1]["controller"]
results["first_after"] = command(first, "set_speed", {"speed_x100": 100})
''')
        self.assertEqual(results["first_stream"], 200)
        self.assertEqual((results["first_controller"], results["second_controller"]), (True, False))
        self.assertEqual(results["second_command"], [409, {"ok": False, "code": "not_controller"}])
        self.assertEqual(results["second_unimplemented"], [200, {"ok": False, "code": "not_implemented"}])
        self.assertEqual(results["first_command"], [200, {"ok": True}])
        self.assertTrue(results["third_controller"])        # the old controller tab stopped watching
        self.assertEqual(results["first_after"], [409, {"ok": False, "code": "not_controller"}])


class CommandChecks:
    """9.1 command enum, 9.2 item 7 nonce idempotency, HTTP/1.1 keep-alive."""

    def test_command_enum_and_not_implemented(self):
        from betangel_suite.api import routes
        results = self.client(r'''
token = bootstrap()
results["commands"] = {}
for name in %r:
    results["commands"][name] = command(token, name)
results["unknown"] = command(token, "kill_all")
results["replace"] = command(token, "replace")
results["bad_nonce"] = command(token, "pause", nonce="short")
results["bad_args"] = command(token, "set_speed", {"speed_x100": "fast"})
results["bad_speed"] = command(token, "set_speed", {"speed_x100": 150})
results["extra_args"] = command(token, "play", {"x": 1})
results["bool_seed"] = command(token, "open_market", {"seed": True})
''' % (routes.COMMANDS,))
        for name, got in results["commands"].items():
            if name in routes.IMPLEMENTED:
                self.assertNotEqual(got[1], {"ok": False, "code": "not_implemented"}, name)
            else:
                self.assertEqual(got, [200, {"ok": False, "code": "not_implemented"}], name)
        self.assertEqual(results["commands"]["stop"], [200, {"ok": True}])
        for name in ("unknown", "replace"):
            self.assertEqual(results[name], [400, {"ok": False, "code": "unknown_command"}], name)
        for name in ("bad_nonce", "bad_args", "extra_args", "bool_seed"):
            self.assertEqual(results[name], [400, {"ok": False, "code": "bad_args"}], name)
        self.assertEqual(results["bad_speed"], [200, {"ok": False, "code": "bad_args"}])

    def test_replayed_nonce_returns_the_first_result_and_does_nothing(self):
        results = self.client(r'''
token = bootstrap()
stream = Stream(token)
results["open"] = command(token, "open_market", {"seed": 11}, nonce="replay-0001")
first = stream.until(lambda item: item["t"] == "frame")
results["replay"] = command(token, "open_market", {"seed": 12}, nonce="replay-0001")
results["replay_other_command"] = command(token, "play", {}, nonce="replay-0001")
results["fresh"] = command(token, "set_speed", {"speed_x100": 500}, nonce="replay-0002")
later = stream.until(lambda item: item["t"] == "frame" and item["clock"]["speed_x100"] == 500)
results["market_ids"] = [first["market"]["id"], later["market"]["id"]]
results["paused"] = later["clock"]["paused"]
stream.close()
''')
        self.assertEqual(results["open"], [200, {"ok": True, "market_id": "1.999000011"}])
        self.assertEqual(results["replay"], results["open"])
        self.assertEqual(results["replay_other_command"], results["open"])
        self.assertEqual(results["fresh"], [200, {"ok": True}])
        self.assertEqual(results["market_ids"], ["1.999000011", "1.999000011"])
        self.assertTrue(results["paused"])



class ApiTests(HeaderAndRoutingChecks, RequestChecks, CommandChecks, _ServerCase):
    """One server for the checks that do not depend on each other's state."""


class StreamTests(_ServerCase):
    """6.5 and 8.5: the hand-chunked NDJSON stream, integer frames, heartbeats while paused or idle; 9.2 item 6:
    only valid tokens spend the stream's rate limit."""

    def test_http_1_0_cannot_have_the_chunked_stream(self):
        results = self.client(r'''
token = bootstrap()
status, found, body = parse(raw(b"GET /api/v1/stream HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n\r\n"
                                % (PORT, token.encode()), timeout=3))
results["http10"] = [status, jbody(body), "transfer-encoding" in found, security_headers_ok(found)]
''')
        self.assertEqual(results["http10"], [505, {"ok": False, "code": "http_version_not_supported"}, False, True])

    def test_requests_without_a_valid_token_spend_no_stream_budget(self):
        # A hostile page can make Yu's browser send Origin-less, token-less GETs of the stream (an <img>, a
        # no-cors fetch). They are refused 401 before the per-route rate limit, so the controller's own stream
        # still opens after more of them than the whole budget.
        from betangel_suite.api import routes
        limit = routes.RATE_LIMITS["stream"][0]
        results = self.client(r'''
statuses = set()
for index in range(%d + 10):
    headers = {"Host": "127.0.0.1:%%d" %% PORT}
    if index %% 2:
        headers["Authorization"] = "Bearer " + "B" * 43           # a wrong token
    statuses.add(request("GET", "/api/v1/stream", headers=headers)[0])
results["refused"] = sorted(statuses)
token = bootstrap()
stream = Stream(token)
results["valid"] = [stream.status, stream.next(5)["t"] in ("hb", "frame")]
stream.close()
time.sleep(0.8)                         # leave no watching controller behind for the next test
''' % limit)
        self.assertEqual(results["refused"], [401])
        self.assertEqual(results["valid"], [200, True])

    def test_stream_is_chunked_ndjson_with_integer_frames_and_heartbeats(self):
        results = self.client(r'''
token = bootstrap()
stream = Stream(token)
results["status"] = stream.status
results["headers"] = [stream.headers.get("content-type"), stream.headers.get("transfer-encoding"),
                      security_headers_ok(stream.headers), "content-length" in stream.headers]
results["idle"] = stream.next(5)
results["open"] = command(token, "open_market", {"seed": 3})
frame = stream.until(lambda item: item["t"] == "frame")
results["frame"] = frame
results["speed"] = command(token, "set_speed", {"speed_x100": 6000})
results["play"] = command(token, "play")
seqs, playing = [], None
for _ in range(12):
    item = stream.until(lambda item: item["t"] == "frame")
    seqs.append(item["seq"])
    playing = item
results["seqs"] = seqs
results["playing_clock"] = playing["clock"]
results["pause"] = command(token, "pause")
paused = stream.until(lambda item: item["t"] == "frame" and item["clock"]["paused"])
results["paused_clock"] = paused["clock"]
results["paused_seq"] = paused["seq"]
hb = stream.until(lambda item: item["t"] == "hb", timeout=5)
results["hb"] = hb
results["chunk_sizes_ok"] = all(size > 0 for size in stream.raw_chunks)
stream.close()
''')
        self.assertEqual(results["status"], 200)
        self.assertEqual(results["headers"], [["application/x-ndjson"], ["chunked"], True, False])
        self.assertEqual(results["idle"], {"t": "hb", "seq": 0, "paused": True})
        frame = results["frame"]
        self.assertEqual(set(frame), {"t", "seq", "clock", "market", "runners"})
        self.assertEqual(set(frame["clock"]), {"pt", "speed_x100", "paused", "pause_reason", "ms_to_off"})
        self.assertEqual(set(frame["market"]), {"id", "name", "status", "inplay", "version", "invalid_reason"})
        self.assertEqual(frame["market"]["id"], "1.999000003")
        self.assertEqual(frame["clock"]["pause_reason"], "ready")
        self.assertEqual(frame["clock"]["ms_to_off"], 600_000)
        for runner in frame["runners"]:
            self.assertEqual(set(runner), {"id", "name", "status", "ltp_h", "tv_p", "back", "lay"})
            self.assertTrue(runner["name"].startswith("Synthetic "))
            self.assertLessEqual(len(runner["back"]), 3)
            self.assertEqual(runner["back"], sorted(runner["back"], reverse=True))
            self.assertEqual(runner["lay"], sorted(runner["lay"]))
        assert_integers(self, frame)
        self.assertEqual(results["seqs"], sorted(set(results["seqs"])))
        self.assertFalse(results["playing_clock"]["paused"])
        self.assertEqual(results["playing_clock"]["speed_x100"], 6000)
        self.assertEqual(results["paused_clock"]["pause_reason"], "user")
        self.assertEqual(results["hb"], {"t": "hb", "seq": results["paused_seq"], "paused": True})
        self.assertTrue(results["chunk_sizes_ok"])

    def test_keep_alive_serves_several_requests_on_one_connection(self):
        results = self.client(r'''
token = bootstrap()
conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
statuses, sockets = [], set()
for _ in range(4):
    status, payload = command(token, "set_speed", {"speed_x100": 100}, conn=conn)
    statuses.append(status)
    sockets.add(id(conn.sock))
status, found, payload = request("POST", "/api/v1/query", {"query": "session", "args": {}}, token=token, conn=conn)
statuses.append(status)
sockets.add(id(conn.sock))
results["statuses"] = statuses
results["one_socket"] = len(sockets) == 1 and conn.sock is not None
results["connection_header"] = found.get("connection")
conn.close()
pipelined = b"".join(b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT for _ in range(2))
data = raw(pipelined + b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % PORT)
results["pipelined"] = data.count(b"HTTP/1.1 200 OK")
''')
        self.assertEqual(results["statuses"], [200] * 5)
        self.assertTrue(results["one_socket"])
        self.assertIsNone(results["connection_header"])
        self.assertEqual(results["pipelined"], 3)


class WatchTests(_ServerCase):
    """8.6 and I-19 through the real server (its own, because it opens and plays a market)."""

    def test_dropping_the_stream_pauses_the_clock(self):
        # I-19 through the real server: the client goes away, stream.serve returns, App.stream_close tells the
        # engine, and the clock pauses with reason not_watched within 2 s of the drop.
        results = self.client(r'''
token = bootstrap()
stream = Stream(token)
results["open"] = command(token, "open_market", {"seed": 6})
results["speed"] = command(token, "set_speed", {"speed_x100": 500})
results["play"] = command(token, "play")
moving = stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
results["moving"] = moving["clock"]["paused"]
stream.close()
dropped = time.monotonic()
time.sleep(1.0)                         # the server notices a gone client within stream.POLL_S
again = Stream(token)
frame = again.until(lambda item: item["t"] == "frame", timeout=5)
results["after"] = [frame["clock"]["paused"], frame["clock"]["pause_reason"]]
results["paused_within_s"] = time.monotonic() - dropped
later = again.until(lambda item: item["t"] in ("frame", "hb"), timeout=3)
results["still_paused"] = later["paused"] if later["t"] == "hb" else later["clock"]["paused"]
again.close()
''')
        self.assertEqual([results["open"][0], results["speed"], results["play"]], [200, [200, {"ok": True}],
                                                                                    [200, {"ok": True}]])
        self.assertFalse(results["moving"])
        self.assertEqual(results["after"], [True, "not_watched"])
        self.assertLess(results["paused_within_s"], 2.0)
        self.assertTrue(results["still_paused"])


class RateLimitTests(_ServerCase):
    """9.2 item 6: per-route rate limits (bootstrap: 30 a minute), refused with 429 and every header."""

    def test_bootstrap_attempts_are_rate_limited(self):
        from betangel_suite.api import routes
        limit = routes.RATE_LIMITS["bootstrap"][0]
        results = self.client(r'''
statuses = []
for _ in range(%d + 2):
    status, found, payload = request("POST", "/api/v1/bootstrap", {"code": "A" * 22})
    statuses.append(status)
results["statuses"] = statuses
results["last"] = [jbody(payload), security_headers_ok(found)]
results["other_route"] = request("POST", "/api/v1/query", {"query": "session", "args": {}})[0]
''' % limit)
        self.assertEqual(results["statuses"], [401] * limit + [429, 429])
        self.assertEqual(results["last"], [{"ok": False, "code": "rate_limited"}, True])
        self.assertEqual(results["other_route"], 401)        # limits are per route


class SlowClientTests(unittest.TestCase):
    """Connections are bounded: a client over the cap gets a code-only 503 with the 9.3 headers, and a request
    head trickled in a byte at a time is cut off at the head deadline, so slow clients cannot hold every slot."""

    def test_over_cap_gets_503_and_trickled_heads_are_cut_off(self):
        home = support.short_home(self)
        # A small cap and deadline for the test; the shipped values are server.MAX_CONNECTIONS (32) and
        # server.HEAD_DEADLINE_S (10 s).
        child = support.run_child(self, home, """
server.MAX_CONNECTIONS = 3
server.Handler.head_deadline_s = 1.5
def main():
    return server.run(cfg, command="serve", port=0)
""")
        port = child.wait_ready()
        results = support.client(self, home, port, r'''
import select
holders = []
for _ in range(3):
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    sock.sendall(b"GET / HTTP/1.1\r\nHost: ")
    holders.append((sock, time.monotonic()))
time.sleep(0.3)                         # all three are accepted and hold the three slots
over = socket.create_connection(("127.0.0.1", PORT), timeout=5)
data = b""
while True:
    part = over.recv(65536)
    if not part:
        break
    data += part
over.close()
status, found, body = parse(data)
results["over_cap"] = [status, jbody(body), found.get("connection"), security_headers_ok(found)]
# Each holder keeps sending a byte every 0.5 s (so no single read ever times out); the deadline still ends it.
closed, next_byte, deadline = {}, 0.0, time.monotonic() + 8
while len(closed) < len(holders) and time.monotonic() < deadline:
    now = time.monotonic()
    if now >= next_byte:
        for index, (sock, started) in enumerate(holders):
            if index not in closed:
                try:
                    sock.sendall(b"x")
                except OSError:
                    closed[index] = now - started
        next_byte = now + 0.5
    waiting = [sock for index, (sock, _started) in enumerate(holders) if index not in closed]
    for sock in select.select(waiting, [], [], 0.1)[0]:
        index = [held for held, _started in holders].index(sock)
        try:
            part = sock.recv(65536)
        except OSError:
            part = b""
        if not part:
            closed[index] = time.monotonic() - holders[index][1]
results["closed_after_s"] = sorted(closed.values())
for sock, _started in holders:
    sock.close()
results["after"] = request("GET", "/", headers={"Host": "127.0.0.1:%d" % PORT})[0]
''')
        self.assertEqual(results["over_cap"], [503, {"ok": False, "code": "too_many_connections"}, ["close"], True])
        self.assertEqual(len(results["closed_after_s"]), 3, results["closed_after_s"])
        for seconds in results["closed_after_s"]:
            self.assertTrue(1.0 <= seconds < 4.0, results["closed_after_s"])
        self.assertEqual(results["after"], 200)
        self.assertEqual(child.terminate(), 0, child.stderr())
        self.assertIn("http:503:too_many_connections", child.stderr().splitlines())
        for line in child.stderr().splitlines():
            self.assertRegex(line, r"\Ahttp:[0-9]{3}:[a-z_]+\Z")


def assert_integers(case, value, where="frame"):
    """No float anywhere in a frame: money and prices are integers (DESIGN.md 8.5)."""
    if isinstance(value, float):
        case.fail("float at " + where)
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_integers(case, item, where + "." + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_integers(case, item, "%s[%d]" % (where, index))


if __name__ == "__main__":
    unittest.main()
