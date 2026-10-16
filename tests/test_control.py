"""The control socket (DESIGN.md 3.1 item 3, 9.1; I-4) and the guard's one connect permit for it.

run/control.sock is an absolute path in the 0700 run directory, mode 0600, served to same-uid peers only
(LOCAL_PEERCRED, which getpeereid is built on), with the closed command set attach, new_code, pause, stop.
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
def handler(command):
    calls.append(command)
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
                   ("too_long", b'{"command": "' + b"x" * 2000 + b'"}\\n'), ("no_newline", b'{"command": "stop"}')):
    results[name] = talk(data) if name != "no_newline" else None
results["calls"] = calls
server.close()
results["removed"] = not os.path.lexists(path)
""")
        self.assertEqual(os.path.dirname(results["path"]), roots.run_dir(home))
        self.assertEqual((results["socket_mode"], results["run_mode"], results["is_socket"]), ("0o600", "0o700", True))
        self.assertEqual(results["attach"], {"ok": True, "port": 1234, "code": "c" * 22})
        self.assertEqual(results["new_code"]["ok"], True)
        self.assertEqual((results["pause"], results["stop"]), ({"ok": True}, {"ok": True}))
        for name in ("unknown", "extra", "duplicate", "not_json", "array", "nan", "too_long"):
            self.assertEqual(results[name], {"ok": False, "code": "control_bad_request"}, name)
        self.assertEqual(results["calls"], ["attach", "new_code", "pause", "stop"])
        self.assertTrue(results["removed"])

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

    def test_stop_asks_again_while_the_lock_is_held_and_nothing_answers(self):
        # server.run takes engine.lock before it binds control.sock (Astra's review of #4): a stop in between must
        # never print not_running while that engine goes on to start. It asks again until its deadline.
        home = support.short_home(self)
        results = checks(self, home, setup="", body=SERVER + """
import io, time
lock = control.acquire_lock()
out = io.StringIO()
attempt("held", lambda: control.stop_main(out=out, wait_s=0.5))
results["held_out"] = out.getvalue()
results["held_running"] = control.engine_running()
def stopping(command):
    calls.append(command)
    os.close(lock)
    return {"ok": True}
late = []
def bind_late():                            # the engine binds its socket 0.3 s after the stop started
    time.sleep(0.3)
    late.append(control.ControlServer(path, stopping))
    late[0].start()
thread = threading.Thread(target=bind_late)
thread.start()
out = io.StringIO()
attempt("late", lambda: control.stop_main(out=out, wait_s=10))
results["late_out"] = out.getvalue()
thread.join()
late[0].close()
results["calls"] = calls
results["running_after"] = control.engine_running()
""")
        self.assertEqual((results["held"], results["held_out"], results["held_running"]), ("control_failed", "", True))
        self.assertEqual((results["late"], results["late_out"]), ("ok", "stopped\n"))
        self.assertEqual(results["calls"], ["stop"])
        self.assertFalse(results["running_after"])

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
