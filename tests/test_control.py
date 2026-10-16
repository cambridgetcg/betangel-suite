"""The control socket (DESIGN.md 3.1 item 3, 9.1; I-4) and the guard's one connect permit for it.

run/control.sock is an absolute path in the 0700 run directory, mode 0600, served to same-uid peers only
(LOCAL_PEERCRED, which getpeereid is built on), with the closed command set attach, new_code, pause, stop,
and (Phase 0c) the ssh-session viewer's attach_viewer (with the port it expects), viewer_code, viewer_heartbeat and
viewer_away, each with its exact extra keys.
Its clients (open, stop) are engine-mode processes, whose guard refuses every connect except to a Unix
socket path in the run directory permitted before seal(). Each check runs in a fresh engine-mode child
under a temporary HOME short enough for sockaddr_un.
"""

import os
import socket
import unittest

from betangel_suite import roots
from betangel_suite.api import control
from tests import test_http_support as support
from tests.test_guard import checks

SERVER = """
import json, socket, threading
from betangel_suite.api import control
roots.ensure_dir(roots.run_dir())
path = control.socket_path()
calls = []
def handler(command, args):
    calls.append([command, args] if args else command)
    return {"ok": True, "port": 1234, "code": "c" * 22} if command in ("attach", "new_code") else {"ok": True}
def talk(data):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(path)
    sock.sendall(data)
    out = b""
    while not out.endswith(b"\\n"):
        part = sock.recv(4096)
        if not part:
            break
        out += part
    sock.close()
    return json.loads(out.decode()) if out else None
"""


class ConnectPermitTests(unittest.TestCase):
    """The guard change of Phase 0b: an AF_UNIX connect to a permitted run-directory path, nothing else."""

    def test_only_permitted_unix_paths_may_be_connected(self):
        home = support.short_home(self, deps=False)
        results = checks(self, home, setup="os.makedirs(roots.run_dir(), mode=0o700)\n", body="""
import socket
run = roots.run_dir()
good, other = os.path.join(run, "c.sock"), os.path.join(run, "o.sock")
guard.permit_unix_socket(good)
guard.permit_unix_socket(other)
listeners = []
for path in (good, other):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)
    listeners.append(server)
def connect(path, ex=False):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        if ex:
            return sock.connect_ex(path)
        sock.connect(path)
attempt("unpermitted_before", lambda: connect(good))
attempt("permit_outside", lambda: guard.permit_unix_connect(os.path.join(os.environ["HOME"], "x.sock")))
attempt("permit_relative", lambda: guard.permit_unix_connect("c.sock"))
attempt("permit_nested", lambda: guard.permit_unix_connect(os.path.join(run, "sub", "c.sock")))
attempt("permit_dotdot", lambda: guard.permit_unix_connect(os.path.join(run, "..", "c.sock")))
attempt("permit_bytes", lambda: guard.permit_unix_connect(os.fsencode(good)))
guard.permit_unix_connect(good)
attempt("permitted", lambda: connect(good))
attempt("permitted_connect_ex", lambda: connect(good, ex=True))
attempt("other_path", lambda: connect(other))
attempt("tcp_loopback", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1))
def tcp_raw():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", 9))
attempt("tcp_raw", tcp_raw)
attempt("datagram_sendto", lambda: socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(b"x", good))
guard.seal()
attempt("permit_after_seal", lambda: guard.permit_unix_connect(other))
attempt("permitted_after_seal", lambda: connect(good))
""")
        self.assertEqual(results["unpermitted_before"], "network_refused")
        for name in ("permit_outside", "permit_relative", "permit_nested", "permit_dotdot", "permit_bytes"):
            self.assertEqual(results[name], "connect_permit_invalid", name)
        # connect_ex raises the same "socket.connect" audit event as connect, so it follows the same permit.
        for name in ("permitted", "permitted_connect_ex", "permitted_after_seal"):
            self.assertEqual(results[name], "ok", name)
        for name in ("other_path", "tcp_raw", "datagram_sendto"):
            self.assertEqual(results[name], "network_refused", name)
        self.assertEqual(results["tcp_loopback"], "name_lookup_refused")
        self.assertEqual(results["permit_after_seal"], "guard_sealed")


class ControlSocketTests(unittest.TestCase):

    def test_socket_protocol_modes_and_cleanup(self):
        home = support.short_home(self)
        results = checks(self, home, setup="", body=SERVER + """
server = control.ControlServer(path, handler)
server.start()
results["path"] = path
results["socket_mode"] = oct(os.stat(path).st_mode & 0o777)
results["run_mode"] = oct(os.stat(roots.run_dir()).st_mode & 0o777)
results["is_socket"] = __import__("stat").S_ISSOCK(os.lstat(path).st_mode)
guard.permit_unix_connect(path)
for command in ("attach", "new_code", "pause", "stop"):
    results[command] = talk(json.dumps({"command": command}).encode() + b"\\n")
for name, data in (("unknown", b'{"command": "kill"}\\n'), ("extra", b'{"command": "stop", "x": 1}\\n'),
                   ("duplicate", b'{"command": "stop", "command": "pause"}\\n'), ("not_json", b"stop\\n"),
                   ("array", b'["stop"]\\n'), ("nan", b'{"command": NaN}\\n'),
                   ("too_long", b'{"command": "' + b"x" * 2000 + b'"}\\n'), ("no_newline", b'{"command": "stop"}'),
                   ("viewer_missing", b'{"command": "viewer_heartbeat"}\\n'),
                   ("viewer_on_stop", b'{"command": "stop", "viewer": 1}\\n'),
                   ("viewer_attach_args", b'{"command": "attach_viewer", "viewer": 1}\\n'),
                   ("port_missing", b'{"command": "attach_viewer"}\\n'),
                   ("port_on_attach", b'{"command": "attach", "port": 8765}\\n'),
                   ("port_bool", b'{"command": "attach_viewer", "port": true}\\n'),
                   ("port_negative", b'{"command": "attach_viewer", "port": -1}\\n'),
                   ("port_huge", b'{"command": "attach_viewer", "port": 65536}\\n'),
                   ("port_text", b'{"command": "attach_viewer", "port": "8765"}\\n'),
                   ("viewer_zero", b'{"command": "viewer_away", "viewer": 0}\\n'),
                   ("viewer_bool", b'{"command": "viewer_away", "viewer": true}\\n'),
                   ("viewer_text", b'{"command": "viewer_code", "viewer": "1"}\\n'),
                   ("viewer_float", b'{"command": "viewer_code", "viewer": 1.0}\\n'),
                   ("viewer_huge", b'{"command": "viewer_code", "viewer": 2147483648}\\n'),
                   ("viewer_extra", b'{"command": "viewer_code", "viewer": 1, "x": 1}\\n')):
    results[name] = talk(data) if name != "no_newline" else None
for command in ("attach_viewer",):
    results[command] = talk(json.dumps({"command": command, "port": 8765}).encode() + b"\\n")
for command in ("viewer_code", "viewer_heartbeat", "viewer_away"):
    results[command] = talk(json.dumps({"command": command, "viewer": 7}).encode() + b"\\n")
from betangel_suite.errors import SuiteError
for name, call in (("client_unknown", lambda: control.request("kill")),
                   ("client_missing_viewer", lambda: control.request("viewer_code")),
                   ("client_bool_viewer", lambda: control.request("viewer_code", args={"viewer": True})),
                   ("client_missing_port", lambda: control.request("attach_viewer")),
                   ("client_bool_port", lambda: control.request("attach_viewer", args={"port": False}))):
    try:
        call()
        results[name] = "sent"
    except SuiteError as exc:
        results[name] = str(exc)
results["client_viewer"] = control.request("viewer_heartbeat", args={"viewer": 3})
results["client_any_port"] = control.request("attach_viewer", args={"port": 0})
results["calls"] = calls
server.close()
results["removed"] = not os.path.lexists(path)
""")
        self.assertEqual(os.path.dirname(results["path"]), roots.run_dir(home))
        self.assertEqual((results["socket_mode"], results["run_mode"], results["is_socket"]), ("0o600", "0o700", True))
        self.assertEqual(results["attach"], {"ok": True, "port": 1234, "code": "c" * 22})
        self.assertEqual(results["new_code"]["ok"], True)
        self.assertEqual((results["pause"], results["stop"]), ({"ok": True}, {"ok": True}))
        for name in ("unknown", "extra", "duplicate", "not_json", "array", "nan", "too_long", "viewer_missing",
                     "viewer_on_stop", "viewer_attach_args", "viewer_zero", "viewer_bool", "viewer_text",
                     "viewer_float", "viewer_huge", "viewer_extra", "port_missing", "port_on_attach", "port_bool",
                     "port_negative", "port_huge", "port_text"):
            self.assertEqual(results[name], {"ok": False, "code": "control_bad_request"}, name)
        for name in ("attach_viewer", "viewer_code", "viewer_heartbeat", "viewer_away", "client_viewer",
                     "client_any_port"):
            self.assertEqual(results[name], {"ok": True}, name)
        for name in ("client_unknown", "client_missing_viewer", "client_bool_viewer", "client_missing_port",
                     "client_bool_port"):
            self.assertEqual(results[name], "control_bad_request", name)       # refused before anything is sent
        self.assertEqual(results["calls"], ["attach", "new_code", "pause", "stop", ["attach_viewer", {"port": 8765}],
                                            ["viewer_code", {"viewer": 7}], ["viewer_heartbeat", {"viewer": 7}],
                                            ["viewer_away", {"viewer": 7}], ["viewer_heartbeat", {"viewer": 3}],
                                            ["attach_viewer", {"port": 0}]])
        self.assertTrue(results["removed"])

    def test_a_sealed_client_keeps_only_the_permit_it_had_before_the_seal(self):
        # ssh-session's attached viewer (Phase 0c) talks to the engine after guard.seal(): control.request then asks
        # for no new permit (none can be added once sealed) and connects only to a path permitted before.
        home = support.short_home(self)
        results = checks(self, home, setup="", body=SERVER + """
server = control.ControlServer(path, handler)
server.start()
results["before_seal"] = control.request("viewer_heartbeat", args={"viewer": 3})
guard.seal()
results["after_seal"] = control.request("viewer_away", args={"viewer": 3})
server.close()
""")
        self.assertEqual((results["before_seal"], results["after_seal"]), ({"ok": True}, {"ok": True}))
        unpermitted = checks(self, home, setup="", body=SERVER + """
server = control.ControlServer(path, handler)
server.start()
guard.seal()
attempt("sealed_without_permit", lambda: control.request("stop"))
results["calls"] = calls
server.close()
""")
        self.assertEqual(unpermitted, {"sealed_without_permit": "network_refused", "calls": []})

    def test_peer_of_another_uid_is_refused(self):
        # A process of another uid cannot be made here without privileges, so the server is told to expect
        # one: our own connection then stands for the foreign peer, and the handler is never reached.
        home = support.short_home(self)
        results = checks(self, home, setup="", body=SERVER + """
server = control.ControlServer(path, handler, expected_uid=os.getuid() + 1)
server.start()
guard.permit_unix_connect(path)
results["foreign"] = talk(b'{"command": "new_code"}\\n')
results["calls"] = calls
server.close()
""")
        self.assertEqual(results["foreign"], {"ok": False, "code": "control_peer_refused"})
        self.assertEqual(results["calls"], [])

    def test_stale_socket_is_replaced_and_lock_is_single(self):
        home = support.short_home(self)
        results = checks(self, home, setup="", body=SERVER + """
first = control.acquire_lock()
results["second_lock"] = control.acquire_lock()
results["running"] = control.engine_running()
with open(path, "w") as handle:
    handle.write("stale")
server = control.ControlServer(path, handler)
server.start()
results["replaced"] = __import__("stat").S_ISSOCK(os.lstat(path).st_mode)
results["lock_mode"] = oct(os.stat(control.lock_path()).st_mode & 0o777)
server.close()
os.close(first)
results["running_after"] = control.engine_running()
results["client_without_engine"] = control.request("stop")
""")
        self.assertIsNone(results["second_lock"])
        self.assertTrue(results["running"])
        self.assertTrue(results["replaced"])
        self.assertEqual(results["lock_mode"], "0o600")
        self.assertFalse(results["running_after"])
        self.assertIsNone(results["client_without_engine"])

    def test_peer_credentials_name_this_uid(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        self.assertEqual(control.peer_uid(left), os.getuid())

    def test_socket_path_is_absolute_in_the_run_directory_and_fits(self):
        path = control.socket_path("/Users/user")
        self.assertEqual(path, "/Users/user/.local/state/betangel-suite/run/control.sock")
        self.assertTrue(os.path.isabs(path))
        control.check_path(path)
        from betangel_suite.errors import SuiteError
        with self.assertRaises(SuiteError) as caught:
            control.check_path("/" + "x" * 120 + "/control.sock")
        self.assertEqual(caught.exception.code, "control_path_too_long")


if __name__ == "__main__":
    unittest.main()
