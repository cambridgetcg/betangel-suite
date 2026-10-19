"""Shared support for the Phase 0b HTTP, engine-process and control-socket tests (no tests of its own).

The test runner's own guard (test mode) refuses every connect, so clients never run in this process:
client() runs a script in a fresh, unguarded interpreter (it never imports betangel_suite), with the
helpers of CLIENT below, and returns the JSON the script prints. Servers run as real engine-mode children:
`bin/suite serve --port 0` (Serve) or a python child that calls betangel_suite.api.server.run with test
seams (an injected opener, an on_ready hook, a short run-marker grace). Every server binds 127.0.0.1 on an
ephemeral port, under a temporary HOME short enough for the control socket path (sockaddr_un holds 104
bytes), and is stopped and its socket removed in cleanup, on failure too. /usr/bin/open is never run: the
open path is driven only with an injected opener. Each server starts only after the real run marker is
checked (tests.require_no_run_marker), because its own check looks at its temporary HOME.

The client scripts never print a bootstrap code or a session token; when a test needs them it reads them
from a 0600 file in the temporary HOME.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from betangel_suite import pin, roots
from tests import DEPS, LAUNCHER, PRELUDE, PYTHON, child_env, require_no_run_marker, rmtree

CODE_RE = re.compile(r"[A-Za-z0-9_-]{22}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_LONG_WORD = re.compile(r"[A-Za-z0-9_-]{22,}")
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                               "form-action 'none'",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "cache-control": "no-store",
}


class _Cleanup:
    """addCleanup for setUpClass users: a list run in reverse by run()."""

    def __init__(self):
        self.calls = []

    def addCleanup(self, fn, *args):
        self.calls.append((fn, args))

    def run(self):
        while self.calls:
            fn, args = self.calls.pop()
            fn(*args)


def short_home(case, *, deps=True):
    """A temporary HOME (TMPDIR/h-XXXXXXXX) with .local/state, .local/share, the state tmp/, an empty
    betangel-data (0700, as on the lab) and the deps copy.

    make_home's longer path would push run/control.sock past the 104 bytes of sockaddr_un. The engine's
    TMPDIR is the suite root's tmp/ (roots.STATE_ROOT_AGREED), and the writer helper creates the suite root
    only inside an existing ~/betangel-data (root_parent_missing otherwise).
    """
    home = tempfile.mkdtemp(prefix="h-")
    case.addCleanup(rmtree, home)
    for parts in ((".local", "state"), (".local", "share"), roots.DATA_HOME_PARTS):
        os.makedirs(os.path.join(home, *parts), mode=0o700)
    os.makedirs(roots.tmp_dir("test", home), mode=0o700)
    if deps:
        target = pin.deps_dir(pin.load(), home)
        for relpath in pin.PINNED_FILES:
            destination = os.path.join(target, relpath)
            os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
            shutil.copyfile(os.path.join(DEPS, relpath), destination)
    if len(os.fsencode(os.path.join(roots.run_dir(home), "control.sock"))) >= 104:
        raise unittest.SkipTest("temporary HOME too long for a control socket")
    return home


def control_path(home):
    return os.path.join(roots.run_dir(home), "control.sock")


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


class Child:
    """A server child whose stdout and stderr go to files in its HOME; always stopped in cleanup."""

    def __init__(self, case, home, argv, *, env=None, name="serve"):
        self.home = home
        self.out_path = os.path.join(home, name + ".out")
        self.err_path = os.path.join(home, name + ".err")
        with open(self.out_path, "w") as out, open(self.err_path, "w") as err:
            self.process = subprocess.Popen(argv, env=child_env(home) if env is None else env, cwd=home,
                                            stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        case.addCleanup(self.kill)

    def wait_line(self, pattern, timeout=30.0):
        """The first match of pattern in stdout, waiting for it; AssertionError if the child exits first."""
        deadline = time.monotonic() + timeout
        regex = re.compile(pattern)
        while time.monotonic() < deadline:
            match = regex.search(self.stdout())
            if match:
                return match
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        raise AssertionError("child not ready: exit=%r stderr=%r" % (self.process.poll(), self.stderr()[-400:]))

    def wait_ready(self, timeout=30.0):
        return int(self.wait_line(r"(?:serving|opened) port=([0-9]+)\n", timeout).group(1))

    def stdout(self):
        return read_text(self.out_path)

    def stderr(self):
        return read_text(self.err_path)

    def wait_exit(self, timeout=20.0):
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self, timeout=20.0):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        return self.wait_exit(timeout)

    def kill(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(10)
        path = control_path(self.home)
        if os.path.lexists(path):
            os.remove(path)


def serve(case, home, *args):
    """bin/suite serve --port 0 [args] as a child; returns (Child, port)."""
    require_no_run_marker()
    child = Child(case, home, ["/bin/sh", LAUNCHER, "serve", "--port", "0", *args])
    return child, child.wait_ready()


RUN_CHILD = PRELUDE + """
import json, os, sys
from betangel_suite import guard, errors
guard.arm("engine")
errors.install_excepthooks()
os.umask(0o077)
from betangel_suite import config, roots
from betangel_suite.api import server
roots.ensure_dir(os.environ["TMPDIR"])
cfg = config.load()
"""


RUN_TAIL = """
try:
    status = main()
except errors.SuiteError as exc:          # as bin/_launch.py does: one refused:<code> line, exit 2
    sys.stderr.write(errors.describe(exc) + "\\n")
    status = 2
sys.exit(status)
"""


def run_child(case, home, body, *, name="engine"):
    """A python engine-mode child set up as bin/_launch.py would; body defines main(), which returns server.run(...).

    Its TMPDIR is the one bin/suite gives serve and open: the suite root's tmp/ while the flag is on.
    """
    require_no_run_marker()
    code = RUN_CHILD + body + RUN_TAIL
    tmp = roots.tmp_dir("serve", home)
    env = child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp)
    return Child(case, home, [PYTHON, "-I", "-S", "-B", "-c", code], env=env, name=name)


# --- the unguarded client ---------------------------------------------------------------------------

CLIENT = r'''
import http.client, json, os, socket, sys, time
HOME = os.environ["HOME"]
results = {}

def headers_of(lines):
    found = {}
    for line in lines:
        name, _, value = line.partition(":")
        found.setdefault(name.strip().lower(), []).append(value.strip())
    return found

def parse(data):
    """(status, {lower name: [values]}, body) of one raw HTTP response (Content-Length or chunked)."""
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    found = headers_of(lines[1:])
    if found.get("transfer-encoding") == ["chunked"]:
        body = b""
        while rest:
            size_text, _, rest = rest.partition(b"\r\n")
            size = int(size_text, 16)
            if size == 0:
                break
            body += rest[:size]
            rest = rest[size + 2:]
    else:
        body = rest[:int(found.get("content-length", ["0"])[0])]
    return status, found, body

def raw(data, timeout=5.0):
    """Send raw bytes on a fresh connection; everything the server sends until it closes (or timeout)."""
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    try:
        try:
            sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)       # nothing more: the server's lingering close ends at once
        except OSError:
            pass                                # the server may refuse before reading everything
        out = b""
        while True:
            try:
                part = sock.recv(65536)
            except socket.timeout:
                break
            if not part:
                break
            out += part
        return out
    finally:
        sock.close()

def base_headers(host=None):
    host = host or "127.0.0.1:%d" % PORT
    return {"Host": host, "Origin": "http://" + host, "Content-Type": "application/json"}

def request(method, path, body=None, headers=None, token=None, conn=None):
    """(status, {lower name: [values]}, body bytes); uses conn when given (keep-alive)."""
    own = conn is None
    if own:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    sent = dict(base_headers() if headers is None else headers)
    if token is not None:
        sent["Authorization"] = "Bearer " + token
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for name, value in sent.items():
        conn.putheader(name, value)
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    response = conn.getresponse()
    payload = response.read()
    found = headers_of(["%s: %s" % item for item in response.getheaders()])
    if own:
        conn.close()
    return response.status, found, payload

def jbody(payload):
    return json.loads(payload.decode())

def control(command, raw_line=None):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(os.path.join(HOME, ".local/state/betangel-suite/run/control.sock"))
    sock.sendall(raw_line if raw_line is not None else json.dumps({"command": command}).encode() + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        part = sock.recv(4096)
        if not part:
            break
        data += part
    sock.close()
    return json.loads(data.decode()) if data else None

def new_code():
    return control("new_code")["code"]

def bootstrap(code=None):
    status, _h, payload = request("POST", "/api/v1/bootstrap", {"code": code or new_code()})
    return jbody(payload)["token"] if status == 200 else None

NONCE = [0]
def command(token, name, args=None, nonce=None, conn=None):
    NONCE[0] += 1
    body = {"nonce": nonce or "n%08d-%d" % (NONCE[0], os.getpid()), "command": name, "args": args or {}}
    status, _h, payload = request("POST", "/api/v1/command", body, token=token, conn=conn)
    return status, jbody(payload)

def query(token, name="session"):
    status, _h, payload = request("POST", "/api/v1/query", {"query": name, "args": {}}, token=token)
    return status, jbody(payload)

class Stream:
    """GET /api/v1/stream on a raw socket, decoding chunks into NDJSON objects."""

    def __init__(self, token, headers=None):
        self.sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        sent = dict(headers or {"Host": "127.0.0.1:%d" % PORT})
        sent["Authorization"] = "Bearer " + token
        text = "GET /api/v1/stream HTTP/1.1\r\n" + "".join("%s: %s\r\n" % kv for kv in sent.items()) + "\r\n"
        self.sock.sendall(text.encode())
        self.buffer = b""
        while b"\r\n\r\n" not in self.buffer:
            self._fill()
        head, _, self.buffer = self.buffer.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        self.status = int(lines[0].split()[1])
        self.headers = headers_of(lines[1:])
        self.raw_chunks = []
        self.pending = b""
        self.closed = False

    def _fill(self):
        part = self.sock.recv(65536)
        if not part:
            raise EOFError
        self.buffer += part

    def _chunk(self):
        while b"\r\n" not in self.buffer:
            self._fill()
        size_text, _, self.buffer = self.buffer.partition(b"\r\n")
        size = int(size_text, 16)
        while len(self.buffer) < size + 2:
            self._fill()
        data, self.buffer = self.buffer[:size], self.buffer[size + 2:]
        self.raw_chunks.append(size)
        return data

    def next(self, timeout=10.0):
        """The next NDJSON object, or None at the end of the stream (or on timeout: "timeout")."""
        self.sock.settimeout(timeout)
        try:
            while b"\n" not in self.pending:
                data = self._chunk()
                if not data:
                    self.closed = True
                    return None
                self.pending += data
        except socket.timeout:
            return "timeout"
        except EOFError:
            self.closed = True
            return None
        line, _, self.pending = self.pending.partition(b"\n")
        return json.loads(line.decode())

    def until(self, predicate, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.next(max(0.1, deadline - time.monotonic()))
            if item is None or item == "timeout":
                return item
            if predicate(item):
                return item
        return "timeout"

    def close(self):
        self.sock.close()

def security_headers_ok(found):
    expected = SECURITY_EXPECTED
    return all(found.get(name) == [value] for name, value in expected.items()) and not any(
        name.startswith("access-control-") for name in found)
'''


def client(case, home, port, script, *, timeout=90):
    """Run script in a fresh unguarded interpreter with CLIENT's helpers; returns the `results` dict."""
    code = ("PORT = %d\nSECURITY_EXPECTED = %r\n" % (port, SECURITY_HEADERS)) + CLIENT + script \
        + "\nprint(json.dumps(results))\n"
    env = child_env(home)
    result = subprocess.run([PYTHON, "-I", "-S", "-B", "-c", code], env=env, cwd=home, capture_output=True, text=True,
                            timeout=timeout)
    case.assertEqual(result.returncode, 0, result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def secret_shaped(text):
    """Words of 22 or more URL-safe characters holding an upper-case letter or a digit (codes and tokens do;
    the suite's own lower_case codes do not)."""
    return [word for word in _LONG_WORD.findall(text) if any(c.isupper() or c.isdigit() for c in word)]


def secrets_in(text, values):
    """The number of values (codes, tokens) that appear in text."""
    return sum(1 for value in values if value and value in text)
