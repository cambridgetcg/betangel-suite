"""Phase 0b end to end: a real synthetic `bin/suite serve`, the UI it serves, its frame stream, and the UI's own
frame code run on what the engine sent (DESIGN.md 6.1, 6.5, 8.5, 8.6 item 1, 9.1-9.3; the shared interfaces 2-4).

One `bin/suite serve --port 0` child runs under a temporary HOME on an ephemeral 127.0.0.1 port; nothing opens a
browser and /usr/bin/open is never run. An unguarded client child (tests/test_http_support.py) then does what the
page does, in order:

  1. GET / and every file of ui/manifest.json, as a page load would (module scripts with and without Origin);
  2. takes a bootstrap code through the control socket (new_code: the same-uid, test-only path; never
     --print-url) and exchanges it for a session token, which never leaves the client child;
  3. opens the stream, opens a synthetic market by seed, plays it at 10x for a few seconds, then at 60x until
     the market is CLOSED, and sends two commands after the end;
  4. runs `bin/suite stop` and reads the stream to its end line.

Every stream line is kept verbatim, with the chunks it arrived in. The tests then check each line against the
shared frame interface (2) exactly (keys, types, integer money, prices on the CLASSIC ladder, best-first ladders,
the reserved namespace), the replay's lifecycle against the generator's own oracle, and the 10x pacing.

Then the UI's own modules (ui/stream.js, grid.js, format.js, ladder.js and app.js's pure parts) run under node on
the captured chunks: every line must parse, validate and apply, every frame must render without throwing, and the
UI may read no field that the interface does not define. A static check of the field names the UI reads runs too.

Last, a second serve child is driven by the UI's own request and stream code (stream.js createApi and
createStreamClient) under node, so the requests the page really builds (headers, bodies, nonces, fetch options)
meet the real server, with only what a browser adds to a same-origin fetch added (the absolute URL, and Origin on
a POST). The node process gets its bootstrap code from a 0600 file in the temporary HOME and prints request shapes,
codes and counts only, never a code or a token.

The test runner's guard does not start node, so node runs from an unguarded child (tests.run_relayed for the
offline check, the HTTP client child for the live one), connecting to nothing but 127.0.0.1. The node tests are
skipped when ~/.local/bin/node is missing.
"""

import hashlib
import json
import os
import re
import unittest

from betangel_suite import engine, roots, rx, synthetic
from tests import LAUNCHER, ROOT, child_env, run_relayed
from tests import test_http_support as support
from tests.test_ui_assets import without_comments

UI = os.path.join(ROOT, "ui")
NODE = os.path.join(os.path.expanduser("~"), ".local", "bin", "node")
SEED = 4242
LIVE_SEED = 4243
TEN_X_S = 2.5

FRAME_KEYS = {"t", "seq", "clock", "market", "runners"}
CLOCK_KEYS = {"pt", "speed_x100", "paused", "pause_reason", "ms_to_off"}
MARKET_KEYS = {"id", "name", "status", "inplay", "version", "invalid_reason"}
RUNNER_KEYS = {"id", "name", "status", "ltp_h", "tv_p", "back", "lay"}
HB_KEYS = {"t", "seq", "paused"}
END_KEYS = {"t", "seq", "reason"}
# Every field path of interface (2), as the node driver below names them.
INTERFACE_PATHS = frozenset(
    ["frame." + key for key in FRAME_KEYS] + ["frame.clock." + key for key in CLOCK_KEYS]
    + ["frame.market." + key for key in MARKET_KEYS] + ["frame.runners[]." + key for key in RUNNER_KEYS]
    + ["hb." + key for key in HB_KEYS] + ["end." + key for key in END_KEYS])
MARKET_STATUSES = {"INACTIVE", "OPEN", "SUSPENDED", "CLOSED"}
RUNNER_STATUSES = {"ACTIVE", "REMOVED", "WINNER", "LOSER", "PLACED", "HIDDEN"}
CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
NAME_RE = re.compile(r"Synthetic ([0-9]+)")


class _ClassScope:
    """addCleanup and assertEqual for the test_http_support helpers, bound to a class's cleanups (setUpClass)."""

    def __init__(self, cls):
        self.cls = cls

    def addCleanup(self, fn, *args):
        self.cls.addClassCleanup(fn, *args)

    def assertEqual(self, first, second, msg=None):
        if first != second:
            raise AssertionError(msg or "%r != %r" % (first, second))


# --- the client: the page's requests, in order ------------------------------------------------------------
# Runs in an unguarded child with test_http_support.CLIENT's helpers; UI_DIR, LAUNCHER_PATH, SEED and TEN_X_S are
# set before it. It never puts the bootstrap code or the session token into `results`.
CLIENT_SCRIPT = r'''
import hashlib, re, subprocess
LINES, TIMES, CHUNKS, COMMANDS = [], [], [], []

def read_message(stream, timeout):
    """The next NDJSON object (its line kept verbatim), None at the end of the stream, or "timeout"."""
    stream.sock.settimeout(timeout)
    try:
        while b"\n" not in stream.pending:
            data = stream._chunk()
            if not data:
                stream.closed = True
                return None
            CHUNKS.append(data.decode("ascii"))
            stream.pending += data
    except socket.timeout:
        return "timeout"
    except EOFError:
        stream.closed = True
        return None
    line, _, stream.pending = stream.pending.partition(b"\n")
    LINES.append(line.decode("ascii"))
    TIMES.append(time.monotonic())
    return json.loads(line.decode("ascii"))

def until(stream, predicate, timeout):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        item = read_message(stream, remaining)
        if item is None or item == "timeout" or predicate(item):
            return item

def is_frame(item):
    return item.get("t") == "frame"

def is_closed(item):
    return is_frame(item) and item["market"]["status"] == "CLOSED" and item["clock"]["pause_reason"] == "end_of_market"

host = "127.0.0.1:%d" % PORT

# 1. the static UI
with open(os.path.join(UI_DIR, "manifest.json"), encoding="utf-8") as handle:
    listed = ["/" + entry["path"] for entry in json.load(handle)["files"]]
static = {}
for path in ["/"] + listed:
    for origin in (False, True):
        headers = {"Host": host}
        if origin:
            headers["Origin"] = "http://" + host
        status, found, body = request("GET", path, headers=headers)
        static[path + (" origin" if origin else "")] = {
            "status": status, "type": found.get("content-type"), "length": found.get("content-length"),
            "sha256": hashlib.sha256(body).hexdigest(), "security": security_headers_ok(found),
            "cookie": "set-cookie" in found}
results["static"] = static
results["unlisted"] = {path: request("GET", path, headers={"Host": host})[0]
                       for path in ("/tests/stream.test.mjs", "/ui/index.html", "/app.js?v=1", "/style.css/",
                                    "/index.htm", "/ticks.json.bak")}

# 2. bootstrap, as stream.js createApi().bootstrap sends it
code = new_code()
status, found, payload = request("POST", "/api/v1/bootstrap", {"code": code})
reply = jbody(payload)
token = reply.get("token")
again_status, _found, again_payload = request("POST", "/api/v1/bootstrap", {"code": code})
results["bootstrap"] = {
    "status": status, "keys": sorted(reply), "ok": reply.get("ok"), "type": found.get("content-type"),
    "token_shape": isinstance(token, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{16,256}", token)),
    "security": security_headers_ok(found), "again": [again_status, jbody(again_payload)]}

def ui_command(name, args):
    """One command as createApi().command sends it: a fresh 32-hex nonce, the token, Origin and JSON."""
    body = {"nonce": os.urandom(16).hex(), "command": name, "args": args}
    status, _found, payload = request("POST", "/api/v1/command", body, token=token)
    COMMANDS.append([name, status, jbody(payload)])

# 3. the stream (GET with the token and no Origin, as the page's fetch sends it), the market and the clock
stream = Stream(token)
results["stream_head"] = {"status": stream.status, "type": stream.headers.get("content-type"),
                          "chunked": stream.headers.get("transfer-encoding"),
                          "security": security_headers_ok(stream.headers)}
results["idle"] = until(stream, lambda item: True, 5.0) not in (None, "timeout")
ui_command("open_market", {"seed": SEED})
results["first"] = until(stream, is_frame, 15.0) not in (None, "timeout")
ui_command("set_speed", {"speed_x100": 1000})
ui_command("play", {})
start = len(LINES)
deadline = time.monotonic() + TEN_X_S
while time.monotonic() < deadline and read_message(stream, 5.0) not in (None, "timeout"):
    pass
results["ten_x"] = [start, len(LINES)]
ui_command("set_speed", {"speed_x100": 6000})
results["closed"] = isinstance(until(stream, is_closed, 120.0), dict)
results["after"] = isinstance(until(stream, lambda item: item.get("t") == "hb", 5.0), dict)
ui_command("play", {})
ui_command("place", {})

# 4. bin/suite stop, then the stream to its end
stop = subprocess.run(["/bin/sh", LAUNCHER_PATH, "stop"], env=dict(os.environ), cwd=HOME, capture_output=True,
                      text=True, timeout=60)
results["stop"] = [stop.returncode, stop.stdout, stop.stderr]
results["stream_ended"] = until(stream, lambda item: False, 20.0) is None
stream.close()
results["lines"] = LINES
results["times"] = TIMES
results["chunks"] = CHUNKS
results["commands"] = COMMANDS
'''

# --- the node driver: the UI's own modules on the captured chunks ------------------------------------------
# Run as `node --input-type=module -e DRIVER <ui dir> <input file>`. It feeds the chunks to stream.js's
# NdjsonParser as bytes, then validates and applies every message with validateMessage and applyMessage, and
# renders each frame the way app.js does (header values, countdown, grid rows, ladder rows). The messages are
# wrapped in recording proxies, so the output lists every field path the UI's code read or checked.
NODE_DRIVER = r'''
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [uiDir, inputPath] = process.argv.slice(1);
const load = (name) => import(pathToFileURL(uiDir + '/' + name).href);
const S = await load('stream.js');
const F = await load('format.js');
const G = await load('grid.js');
const L = await load('ladder.js');
const A = await load('app.js');
const input = JSON.parse(readFileSync(inputPath, 'utf8'));
const map = L.makeTickMap(JSON.parse(readFileSync(uiDir + '/ticks.json', 'utf8')));

const read = new Set();
const checked = new Set();
function wrap(value, path) {
  if (value === null || typeof value !== 'object') {
    return value;
  }
  const array = Array.isArray(value);
  return new Proxy(value, {
    get(target, key, receiver) {
      const found = Reflect.get(target, key, receiver);
      if (typeof key === 'symbol') {
        return found;
      }
      if (array) {
        return /^[0-9]+$/.test(key) ? wrap(found, path + '[]') : found;
      }
      read.add(path + '.' + key);
      return wrap(found, path + '.' + key);
    },
    getOwnPropertyDescriptor(target, key) {
      if (!array && typeof key !== 'symbol') {
        checked.add(path + '.' + key);
      }
      return Reflect.getOwnPropertyDescriptor(target, key);
    },
    has(target, key) {
      if (!array && typeof key !== 'symbol') {
        checked.add(path + '.' + key);
      }
      return Reflect.has(target, key);
    },
  });
}

const problems = {};
const note = (code) => { problems[code] = (problems[code] || 0) + 1; };
const counts = { messages: 0, frame: 0, hb: 0, end: 0, applied: 0, rendered: 0, offTick: 0 };

const parser = new S.NdjsonParser();
const encoder = new TextEncoder();
const messages = [];
for (const chunk of input.chunks) {
  messages.push(...parser.push(encoder.encode(chunk)));
}
parser.finish();
const same = messages.length === input.lines.length
  && messages.every((msg, i) => JSON.stringify(msg) === JSON.stringify(JSON.parse(input.lines[i])));

const state = S.createViewState();
S.resetSequence(state);
let selected = null;
let centre = null;
let win = null;
let last = null;
messages.forEach((raw, i) => {
  const now = input.times[i];
  counts.messages += 1;
  counts[raw.t] = (counts[raw.t] || 0) + 1;
  const msg = wrap(raw, String(raw.t));
  const problem = S.validateMessage(msg);
  if (problem !== null) {
    note(problem);
  }
  if (!S.applyMessage(state, msg, now)) {
    if (raw.t === 'frame') {
      note('frame_not_applied');
    }
    return;
  }
  counts.applied += 1;
  if (raw.t !== 'frame') {
    return;
  }
  last = raw;
  const frame = state.frame;
  // the header and countdown (app.js renderHeader, renderCountdown)
  if (!F.isSyntheticMarketId(raw.market.id)) {
    note('not_synthetic');
  }
  F.formatClockUtc(raw.clock.pt);
  F.formatSpeed(raw.clock.speed_x100);
  F.formatCountdown(S.liveMsToOff(state, now), raw.market.inplay);
  F.invalidReasonText(raw.market.invalid_reason);
  if (raw.clock.pause_reason !== null && F.safeCode(raw.clock.pause_reason) !== raw.clock.pause_reason) {
    note('pause_reason_not_a_code');
  }
  // the grid, and the ladder of the selected runner (app.js render)
  selected = A.chooseRunner(frame.runners, selected);
  for (const runner of frame.runners) {
    G.rowCells(runner);
  }
  for (const runner of raw.runners) {
    for (const level of runner.back.concat(runner.lay)) {
      if (map.indexOf(level[0]) === -1) {
        counts.offTick += 1;
      }
    }
    if (runner.ltp_h !== null && map.indexOf(runner.ltp_h) === -1) {
      counts.offTick += 1;
    }
  }
  const runner = frame.runners.find((item) => item.id === selected) || null;
  centre = L.nextCentre(centre, win, L.referenceIndex(map, runner));
  win = L.ladderWindow(map.count, centre);
  L.ladderRows(map, win, runner);
  counts.rendered += 1;
});

process.stdout.write(JSON.stringify({
  counts: counts, problems: problems, same: same, badLines: parser.badLines, longLines: parser.longLines,
  droppedPartial: parser.droppedPartial, read: [...read].sort(), checked: [...checked].sort(),
  final: { seq: state.seq, paused: state.paused, ended: state.ended, rejected: state.rejected,
    status: last === null ? null : last.market.status },
}) + '\n');
'''


# --- the live node client: the UI's request and stream code against a real serve child --------------------
# Run as `node --input-type=module -e NODE_LIVE <ui dir> <code file> <port> <seed>` by the client child. The
# fetch it hands to createApi and createStreamClient adds only what a browser adds to the page's same-origin
# fetch: the absolute URL, and Origin on a POST. It records the shape of every request the UI built (header
# names, body keys, fetch options, whether the nonce and the Authorization value have the right form), never a
# value, and prints codes and counts only.
NODE_LIVE = r'''
import { readFileSync, unlinkSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [uiDir, codePath, port, seed] = process.argv.slice(1);
const S = await import(pathToFileURL(uiDir + '/stream.js').href);
const base = 'http://127.0.0.1:' + port;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(check, ms) {
  const deadline = Date.now() + ms;
  while (!check()) {
    if (Date.now() > deadline) {
      return false;
    }
    await sleep(20);
  }
  return true;
}

const requests = [];
function fetchImpl(path, init) {
  const headers = init.headers || {};
  const shape = { method: init.method, path: path, headers: Object.keys(headers).sort(), credentials: init.credentials,
    cache: init.cache, redirect: init.redirect, referrerPolicy: init.referrerPolicy, mode: init.mode };
  shape.bearer = headers.Authorization === undefined ? null : /^Bearer [A-Za-z0-9_-]{43}$/.test(headers.Authorization);
  if (typeof init.body === 'string') {
    const body = JSON.parse(init.body);
    shape.body = Object.keys(body).sort();
    if (typeof body.nonce === 'string') {
      shape.nonce = /^[0-9a-f]{32}$/.test(body.nonce);
    }
  }
  requests.push(shape);
  const sent = { ...headers };
  if (init.method === 'POST') {
    // as a browser sends it: fetch()'s default cors mode sends the page's origin; any other mode, with the page's
    // no-referrer policy, sends Origin: null (Fetch, "append a request Origin header"), which the server refuses
    sent.Origin = init.mode === undefined || init.mode === 'cors' ? base : 'null';
  }
  return fetch(base + path, { ...init, headers: sent });
}

let token = null;
let unauthorized = 0;
const api = S.createApi({ fetchImpl: fetchImpl, getToken: () => token, onUnauthorized: () => { unauthorized += 1; },
  fillRandom: (bytes) => globalThis.crypto.getRandomValues(bytes) });
const code = readFileSync(codePath, 'utf8').trim();
unlinkSync(codePath);
const boot = await api.bootstrap(code);
token = boot.ok ? boot.token : null;

const state = S.createViewState();
const seen = [];
const statuses = [];
const client = S.createStreamClient({
  fetchImpl: fetchImpl, getToken: () => token, onConnect: () => S.resetSequence(state),
  onMessage: (msg) => {
    seen.push({ t: msg.t, problem: S.validateMessage(msg) });
    S.applyMessage(state, msg, Date.now());
  },
  onStatus: (status) => statuses.push(status), onUnauthorized: () => { unauthorized += 1; },
});
const running = client.start();
const replies = [];
async function command(name, args) {
  const result = await api.command(name, args);
  replies.push(result.ok ? { name: name, ok: true, reply: result.reply } : { name: name, ok: false, code: result.code });
}
const waits = {};
waits.idle = await waitFor(() => seen.length > 0, 5000);
await command('open_market', { seed: Number(seed) });
waits.opened = await waitFor(() => state.frame !== null, 15000);
await command('set_speed', { speed_x100: 1000 });
await command('play', {});
waits.playing = await waitFor(() => state.frame !== null && !state.paused && state.frame.clock.speed_x100 === 1000, 5000);
const from = state.frame.clock.pt;
await sleep(1000);
await command('pause', {});
waits.paused = await waitFor(() => state.frame.clock.paused && state.frame.clock.pause_reason === 'user', 5000);
await command('place', {});
client.stop();
await running;
const report = {
  boot: boot.ok, unauthorized: unauthorized, statuses: statuses, waits: waits, replies: replies, requests: requests,
  first: seen.length > 0 ? seen[0].t : null, problems: seen.filter((item) => item.problem !== null).length,
  frames: seen.filter((item) => item.t === 'frame').length, rejected: state.rejected, market: state.frame.market.id,
  advanced: state.frame.clock.pt - from, paused: state.paused, reason: state.frame.clock.pause_reason,
};
process.stdout.write(JSON.stringify(report) + '\n', () => process.exit(0));
'''

# The client child of the live test: a bootstrap code into a 0600 file (never stdout), node, then bin/suite stop.
LIVE_CLIENT_SCRIPT = r'''
import subprocess
code_path = os.path.join(HOME, ".local", "state", "betangel-suite", "ui-code")
fd = os.open(code_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, new_code().encode("ascii"))
os.close(fd)
run = subprocess.run([NODE_PATH, "--no-warnings", "--input-type=module", "-e", NODE_LIVE, UI_DIR, code_path, str(PORT),
                      str(SEED)], env=dict(os.environ), cwd=HOME, capture_output=True, text=True, timeout=90)
results["node"] = [run.returncode, run.stdout, run.stderr[-2000:]]
results["code_file_left"] = os.path.lexists(code_path)
stop = subprocess.run(["/bin/sh", LAUNCHER_PATH, "stop"], env=dict(os.environ), cwd=HOME, capture_output=True,
                      text=True, timeout=60)
results["stop"] = [stop.returncode, stop.stdout, stop.stderr]
'''


def node_available():
    return os.path.isfile(NODE) and os.access(NODE, os.X_OK)


def strict_line(line):
    """A stream line as JSON: no float, NaN, Infinity or duplicate key anywhere (AssertionError otherwise)."""
    def no_float(text):
        raise AssertionError("a float in the stream")

    def no_constant(text):
        raise AssertionError("a non-finite number in the stream")

    def no_duplicates(pairs):
        keys = [key for key, _value in pairs]
        if len(keys) != len(set(keys)):
            raise AssertionError("a duplicate key in the stream")
        return dict(pairs)

    return json.loads(line, parse_float=no_float, parse_constant=no_constant, object_pairs_hook=no_duplicates)


def is_int(value):
    return type(value) is int


class EndToEndTests(unittest.TestCase):
    """One serve child and one client session for the whole class; each test checks one side of what happened."""

    @classmethod
    def setUpClass(cls):
        scope = _ClassScope(cls)
        cls.market = synthetic.generate(synthetic.Spec(seed=SEED))      # the generator's own oracle, test side only
        cls.home = support.short_home(scope)
        cls.child, cls.port = support.serve(scope, cls.home)
        prefix = "UI_DIR = %r\nLAUNCHER_PATH = %r\nSEED = %d\nTEN_X_S = %r\n" % (UI, LAUNCHER, SEED, TEN_X_S)
        cls.results = support.client(scope, cls.home, cls.port, prefix + CLIENT_SCRIPT, timeout=240)
        cls.exit_status = cls.child.wait_exit(30)
        cls.messages = [strict_line(line) for line in cls.results["lines"]]
        cls.frames = [item for item in cls.messages if item["t"] == "frame"]

    # --- interface (4) and section 9.3: the static UI ---------------------------------------------------------

    def test_every_manifest_file_is_served_byte_exact_with_its_type_and_headers(self):
        with open(os.path.join(UI, "manifest.json"), encoding="utf-8") as handle:
            entries = json.load(handle)["files"]
        expected = {"/": ("index.html", "text/html; charset=utf-8")}
        expected.update({"/" + entry["path"]: (entry["path"], entry["type"]) for entry in entries})
        static = self.results["static"]
        self.assertEqual(set(static), {path + suffix for path in expected for suffix in ("", " origin")})
        for key, got in static.items():
            relpath, kind = expected[key.split(" ")[0]]
            with open(os.path.join(UI, *relpath.split("/")), "rb") as handle:
                data = handle.read()
            with self.subTest(path=key):
                self.assertEqual(got["status"], 200)
                self.assertEqual(got["type"], [kind])
                self.assertEqual(got["length"], [str(len(data))])
                self.assertEqual(got["sha256"], hashlib.sha256(data).hexdigest())
                self.assertTrue(got["security"])
                self.assertFalse(got["cookie"])
        self.assertEqual(set(self.results["unlisted"].values()), {404}, self.results["unlisted"])

    # --- interface (3): bootstrap and commands ----------------------------------------------------------------

    def test_bootstrap_exchanges_the_code_once_for_a_token(self):
        boot = self.results["bootstrap"]
        self.assertEqual((boot["status"], boot["keys"], boot["ok"], boot["type"]),
                         (200, ["ok", "token"], True, ["application/json"]))
        self.assertTrue(boot["token_shape"])
        self.assertTrue(boot["security"])
        self.assertEqual(boot["again"], [401, {"ok": False, "code": "bad_code"}])

    def test_commands_answer_as_the_interface_says(self):
        self.assertEqual(self.results["commands"], [
            ["open_market", 200, {"ok": True, "market_id": self.market.market_id}],
            ["set_speed", 200, {"ok": True}],
            ["play", 200, {"ok": True}],
            ["set_speed", 200, {"ok": True}],
            ["play", 200, {"ok": False, "code": "end_of_market"}],
            ["place", 200, {"ok": False, "code": "not_implemented"}],
        ])

    # --- interface (2): every stream line ---------------------------------------------------------------------

    def test_the_stream_is_chunked_ndjson_with_the_headers(self):
        head = self.results["stream_head"]
        self.assertEqual((head["status"], head["type"], head["chunked"]),
                         (200, ["application/x-ndjson"], ["chunked"]))
        self.assertTrue(head["security"])
        self.assertTrue(self.results["idle"] and self.results["first"] and self.results["after"])
        self.assertTrue(self.results["stream_ended"])
        self.assertEqual("".join(self.results["chunks"]), "".join(line + "\n" for line in self.results["lines"]))

    def test_every_line_matches_the_frame_interface_exactly(self):
        self.assertGreater(len(self.frames), 30)
        last_seq = 0
        for index, item in enumerate(self.messages):
            with self.subTest(line=index, t=item.get("t")):
                if item["t"] == "frame":
                    self.check_frame(item)
                    self.assertGreater(item["seq"], last_seq)
                    last_seq = item["seq"]
                elif item["t"] == "hb":
                    self.assertEqual(set(item), HB_KEYS)
                    self.assertTrue(is_int(item["seq"]) and type(item["paused"]) is bool)
                    self.assertEqual(item["seq"], last_seq)
                else:
                    self.assertEqual(item["t"], "end")
                    self.assertEqual(set(item), END_KEYS)
                    self.assertEqual(item, {"t": "end", "seq": last_seq, "reason": "stopped"})
                    self.assertEqual(index, len(self.messages) - 1, "the end line is the last line")
        self.assertEqual(self.messages[0], {"t": "hb", "seq": 0, "paused": True})
        self.assertEqual(self.messages[-1]["t"], "end")

    def check_frame(self, frame):
        self.assertEqual(set(frame), FRAME_KEYS)
        self.assertTrue(is_int(frame["seq"]) and frame["seq"] > 0)
        clock, market = frame["clock"], frame["market"]
        self.assertEqual(set(clock), CLOCK_KEYS)
        self.assertTrue(is_int(clock["pt"]) and clock["pt"] > 0)
        self.assertIn(clock["speed_x100"], engine.SPEEDS_X100)
        self.assertIs(type(clock["paused"]), bool)
        if clock["paused"]:
            self.assertIn(clock["pause_reason"], engine.PAUSE_REASONS)
        else:
            self.assertIsNone(clock["pause_reason"])
        self.assertTrue(clock["ms_to_off"] is None or is_int(clock["ms_to_off"]))
        self.assertEqual(set(market), MARKET_KEYS)
        self.assertEqual(market["id"], self.market.market_id)
        self.assertTrue(synthetic.is_synthetic_market_id(market["id"]))
        self.assertIs(type(market["name"]), str)
        self.assertTrue(market["name"].startswith(synthetic.VENUE + " "), "venue first")
        self.assertIn(market["status"], MARKET_STATUSES)
        self.assertIs(type(market["inplay"]), bool)
        self.assertTrue(is_int(market["version"]) and market["version"] >= 0)
        self.assertTrue(market["invalid_reason"] is None or CODE_RE.fullmatch(market["invalid_reason"]))
        runners = frame["runners"]
        self.assertIs(type(runners), list)
        self.assertEqual([runner["id"] for runner in runners], list(self.market.selection_ids), "sortPriority order")
        self.assertEqual([runner["name"] for runner in runners], list(self.market.runner_names))
        ladder = frozenset(rx.ticks.LADDER_CLASSIC)
        for runner in runners:
            self.assertEqual(set(runner), RUNNER_KEYS)
            self.assertTrue(synthetic.is_synthetic_selection_id(runner["id"]))
            self.assertTrue(NAME_RE.fullmatch(runner["name"]))
            self.assertIn(runner["status"], RUNNER_STATUSES)
            self.assertTrue(runner["ltp_h"] is None or (is_int(runner["ltp_h"]) and runner["ltp_h"] in ladder))
            self.assertTrue(is_int(runner["tv_p"]) and runner["tv_p"] >= 0)
            for side in ("back", "lay"):
                levels = runner[side]
                self.assertIs(type(levels), list)
                self.assertLessEqual(len(levels), 3)
                for level in levels:
                    self.assertIs(type(level), list)
                    self.assertEqual(len(level), 2)
                    self.assertTrue(is_int(level[0]) and level[0] in ladder, "price on the CLASSIC ladder")
                    self.assertTrue(is_int(level[1]) and level[1] > 0, "size in whole pence")
                prices = [level[0] for level in levels]
                best_first = sorted(prices, reverse=side == "back")
                self.assertEqual(prices, best_first, side + " best first")
                self.assertEqual(len(set(prices)), len(prices))
            if runner["back"] and runner["lay"]:
                self.assertLess(runner["back"][0][0], runner["lay"][0][0], "not crossed")

    # --- the replay: lifecycle, oracle and pacing -------------------------------------------------------------

    def test_the_market_replays_from_the_opening_image_through_in_play_to_closed(self):
        first, last = self.frames[0], self.frames[-1]
        self.assertEqual((first["clock"]["paused"], first["clock"]["pause_reason"], first["clock"]["speed_x100"]),
                         (True, "ready", 100))
        self.assertEqual(first["clock"]["ms_to_off"], self.market.off_pt - first["clock"]["pt"])
        self.assertEqual((last["market"]["status"], last["clock"]["paused"], last["clock"]["pause_reason"]),
                         ("CLOSED", True, "end_of_market"))
        pts = [frame["clock"]["pt"] for frame in self.frames]
        self.assertEqual(pts, sorted(pts), "the replay clock never goes back")
        self.assertTrue({frame["clock"]["pt"] + frame["clock"]["ms_to_off"] for frame in self.frames}
                        == {self.market.market_time_ms}, "ms_to_off counts down to the published marketTime")
        pre_off = [frame for frame in self.frames if frame["clock"]["ms_to_off"] > 0]
        in_play = [frame for frame in self.frames if frame["market"]["inplay"]]
        self.assertTrue(pre_off and in_play)
        for frame in pre_off:
            self.assertEqual((frame["market"]["status"], frame["market"]["inplay"], frame["market"]["invalid_reason"]),
                             ("OPEN", False, None))
        self.assertTrue(all(frame["clock"]["ms_to_off"] <= 0 for frame in in_play))
        self.assertTrue(any(frame["market"]["status"] == "OPEN" for frame in in_play))
        for frame in self.frames:
            if frame["market"]["status"] != "CLOSED":       # no spoiler: no result before CLOSED
                self.assertEqual({runner["status"] for runner in frame["runners"]}, {"ACTIVE"})
        winners = [runner["id"] for runner in last["runners"] if runner["status"] == "WINNER"]
        self.assertEqual(winners, [self.market.winner_id])
        self.assertTrue(all(frame["runners"] for frame in self.frames))
        self.assertTrue(any(runner["tv_p"] > 0 for runner in last["runners"]))

    def test_play_at_10x_moves_the_replay_clock_ten_times_wall_time(self):
        start, end = self.results["ten_x"]
        window = [(self.results["times"][i], self.messages[i]) for i in range(start, end)
                  if self.messages[i]["t"] == "frame" and not self.messages[i]["clock"]["paused"]
                  and self.messages[i]["clock"]["speed_x100"] == 1000]
        self.assertGreaterEqual(len(window), 10)
        wall_s = window[-1][0] - window[0][0]
        replay_ms = window[-1][1]["clock"]["pt"] - window[0][1]["clock"]["pt"]
        self.assertGreater(wall_s, 1.5)
        self.assertTrue(7.0 <= replay_ms / 1000 / wall_s <= 13.0, (replay_ms, wall_s))
        frame_hz = 10                                       # config.DEFAULTS; the serve child has no config file
        self.assertLessEqual(len(window) - 1, wall_s * frame_hz + 2, "frames come at frame_hz or less")

    # --- the process: output, stop and cleanup ----------------------------------------------------------------

    def test_serve_printed_only_its_port_and_stop_ended_it_cleanly(self):
        self.assertEqual(self.results["stop"], [0, "stopped\n", ""])
        self.assertEqual(self.exit_status, 0)
        self.assertEqual(self.child.stdout(), "serving port=%d\n" % self.port)
        # The server logs one code-only line per refused request: the six unlisted paths and the reused code.
        self.assertEqual(self.child.stderr(), "http:404:not_found\n" * 6 + "http:401:bad_code\n")
        self.assertEqual(support.secret_shaped(self.child.stdout() + self.child.stderr()), [])
        self.assertFalse(os.path.lexists(support.control_path(self.home)))
        self.assertFalse(os.path.lexists(os.path.join(roots.data_home(self.home))))

    # --- the UI's frame code on these frames ------------------------------------------------------------------

    def test_the_fields_the_ui_reads_are_the_interface_fields(self):
        """Static: stream.js validates exactly the interface keys, and no UI script reads a frame field outside it."""
        with open(os.path.join(UI, "stream.js"), encoding="utf-8") as handle:
            stream_js = without_comments(handle.read())
        arrays = {name: set(re.findall(r"'([a-z0-9_]+)'", body))
                  for name, body in re.findall(r"const (FRAME|CLOCK|MARKET|RUNNER)_KEYS = \[([^\]]*)\]", stream_js)}
        self.assertEqual(arrays, {"FRAME": FRAME_KEYS, "CLOCK": CLOCK_KEYS, "MARKET": MARKET_KEYS,
                                  "RUNNER": RUNNER_KEYS})
        self.assertIn("hasKeys(msg, ['t', 'seq', 'paused'])", stream_js)
        self.assertIn("hasKeys(msg, ['t', 'seq', 'reason'])", stream_js)
        found = {"clock": set(), "market": set(), "message": set(), "runner": set()}
        for name in ("app.js", "grid.js", "ladder.js", "stream.js", "format.js"):
            with open(os.path.join(UI, name), encoding="utf-8") as handle:
                source = without_comments(handle.read())
            for part in ("clock", "market"):
                found[part] |= set(re.findall(r"\b(?:frame|msg)\.%s\.([A-Za-z_]\w*)" % part, source))
            found["message"] |= set(re.findall(r"\b(?:frame|msg)\.([A-Za-z_]\w*)", source))
            found["runner"] |= set(re.findall(r"\brunner\.([A-Za-z_]\w*)", source))
        self.assertLessEqual(found["clock"], CLOCK_KEYS)
        self.assertLessEqual(found["market"], MARKET_KEYS)
        self.assertLessEqual(found["message"], FRAME_KEYS | HB_KEYS | END_KEYS)
        self.assertLessEqual(found["runner"], RUNNER_KEYS)
        self.assertEqual(found["runner"], RUNNER_KEYS, "the grid and ladder show every runner field")
        self.assertLessEqual({"pt", "speed_x100", "pause_reason", "ms_to_off"}, found["clock"])
        self.assertLessEqual({"id", "name", "status", "inplay", "invalid_reason"}, found["market"])

    def test_the_ui_and_the_server_share_routes_commands_and_speeds(self):
        """Static: the routes, the command enum and the speeds the UI knows are the server's and the engine's."""
        from betangel_suite.api import routes
        sources = {}
        for name in ("app.js", "stream.js", "index.html"):
            with open(os.path.join(UI, name), encoding="utf-8") as handle:
                sources[name] = without_comments(handle.read()) if name.endswith(".js") else handle.read()
        ui_routes = dict(re.findall(r"(\w+): '(/api/v1/\w+)'", re.search(r"ROUTES = Object\.freeze\(\{([^}]*)\}",
                                                                          sources["stream.js"]).group(1)))
        self.assertEqual(ui_routes, {name: path for (_method, path), name in routes.ROUTES.items()})
        ui_commands = re.findall(r"'([a-z_]+)'", re.search(r"COMMANDS = Object\.freeze\(\[([^\]]*)\]",
                                                            sources["stream.js"]).group(1))
        self.assertEqual(tuple(ui_commands), routes.COMMANDS)
        ui_speeds = [int(value) for value in re.findall(r"[0-9]+", re.search(
            r"SPEEDS_X100 = Object\.freeze\(\[([^\]]*)\]", sources["app.js"]).group(1))]
        self.assertEqual(tuple(ui_speeds), engine.SPEEDS_X100)
        buttons = [int(value) for value in re.findall(r'data-speed="([0-9]+)"', sources["index.html"])]
        self.assertTrue(buttons and set(buttons) <= set(engine.SPEEDS_X100))
        self.assertIn(engine.DEFAULT_SPEED_X100, buttons)

    def test_the_ui_modules_parse_validate_apply_and_render_every_line(self):
        if not node_available():
            self.skipTest("~/.local/bin/node is not installed")
        times = self.results["times"]
        payload = {"chunks": self.results["chunks"], "lines": self.results["lines"],
                   "times": [int((value - times[0]) * 1000) for value in times]}
        path = os.path.join(self.home, "captured-stream.json")      # in the temporary HOME (under TMPDIR)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        argv = [NODE, "--no-warnings", "--input-type=module", "-e", NODE_DRIVER, UI, path]
        status, out, err = run_relayed(argv, child_env(self.home), self.home, timeout=120)
        self.assertEqual(status, 0, err[-2000:])
        report = json.loads(out.strip().splitlines()[-1])
        counts = report["counts"]
        hbs = sum(1 for item in self.messages if item["t"] == "hb")
        self.assertTrue(report["same"], "the parser gives the lines the server wrote, chunk by chunk")
        self.assertEqual((report["badLines"], report["longLines"], report["droppedPartial"]), (0, 0, 0))
        self.assertEqual(report["problems"], {})
        self.assertEqual((counts["messages"], counts["frame"], counts["hb"], counts["end"]),
                         (len(self.messages), len(self.frames), hbs, 1))
        self.assertEqual(counts["rendered"], len(self.frames))
        self.assertEqual(counts["offTick"], 0)
        self.assertEqual(report["final"], {"seq": self.frames[-1]["seq"], "paused": True, "ended": "stopped",
                                           "rejected": 0, "status": "CLOSED"})
        touched = set(report["read"]) | set(report["checked"])
        self.assertLessEqual(touched, INTERFACE_PATHS, "the UI reads no field the frame interface lacks")
        self.assertEqual(touched, INTERFACE_PATHS, "the UI consumes every field of the interface")
        rendered = {"frame.runners[]." + key for key in RUNNER_KEYS} | {"frame.clock.ms_to_off",
                                                                          "frame.clock.speed_x100"}
        self.assertLessEqual(rendered, set(report["read"]))


class UiClientLiveTests(unittest.TestCase):
    """The UI's own request and stream code (stream.js createApi, createStreamClient) against a real serve child."""

    def test_the_ui_client_code_drives_a_real_engine(self):
        if not node_available():
            self.skipTest("~/.local/bin/node is not installed")
        home = support.short_home(self)
        child, port = support.serve(self, home)
        prefix = "UI_DIR = %r\nLAUNCHER_PATH = %r\nSEED = %d\nNODE_PATH = %r\nNODE_LIVE = %r\n" % (
            UI, LAUNCHER, LIVE_SEED, NODE, NODE_LIVE)
        results = support.client(self, home, port, prefix + LIVE_CLIENT_SCRIPT, timeout=180)
        status, out, err = results["node"]
        self.assertEqual(status, 0, err)
        self.assertEqual(support.secret_shaped(out + err), [], "node printed no code or token")
        self.assertFalse(results["code_file_left"])
        report = json.loads(out.strip().splitlines()[-1])
        market_id = "1.999%06d" % (LIVE_SEED % 10 ** 6)
        self.assertEqual((report["boot"], report["unauthorized"], report["statuses"]),
                         (True, 0, ["connecting", "connected"]))
        self.assertEqual(report["waits"], {"idle": True, "opened": True, "playing": True, "paused": True})
        self.assertEqual(report["replies"], [
            {"name": "open_market", "ok": True, "reply": {"ok": True, "market_id": market_id}},
            {"name": "set_speed", "ok": True, "reply": {"ok": True}},
            {"name": "play", "ok": True, "reply": {"ok": True}},
            {"name": "pause", "ok": True, "reply": {"ok": True}},
            {"name": "place", "ok": False, "code": "not_implemented"},
        ])
        self.assertEqual((report["first"], report["problems"], report["rejected"], report["market"]),
                         ("hb", 0, 0, market_id))
        self.assertGreater(report["frames"], 5)
        self.assertTrue(5000 <= report["advanced"] <= 15000, report["advanced"])     # about 1 s of wall at 10x
        self.assertEqual((report["paused"], report["reason"]), (True, "user"))
        options = {"credentials": "omit", "cache": "no-store", "redirect": "error", "referrerPolicy": "no-referrer"}
        boot = dict(options, method="POST", path="/api/v1/bootstrap", headers=["Content-Type"], bearer=None,
                    body=["code"])
        stream = dict(options, method="GET", path="/api/v1/stream", headers=["Authorization"], bearer=True)
        command = dict(options, method="POST", path="/api/v1/command", headers=["Authorization", "Content-Type"],
                       bearer=True, body=["args", "command", "nonce"], nonce=True)
        self.assertEqual(report["requests"], [boot, stream] + [command] * 5)
        self.assertEqual(results["stop"], [0, "stopped\n", ""])
        self.assertEqual(child.wait_exit(30), 0)
        self.assertEqual(child.stdout(), "serving port=%d\n" % port)
        self.assertEqual(child.stderr(), "")
        self.assertFalse(os.path.lexists(support.control_path(home)))


if __name__ == "__main__":
    unittest.main()
