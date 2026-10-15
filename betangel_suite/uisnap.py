"""bin/suite uisnap: PNG snapshots of the browser UI on a synthetic-only engine (DESIGN.md 11, test group 7).

    bin/suite uisnap [--seed N] [--out DIR]

The launcher arms the guard in mode uisnap (guard.py) and checks the run marker first. Then, in order:

1. Refuse any configured data root (synthetic_only) and a running engine (engine_running), and check --out,
   before anything is built or created. --out must be an absolute path inside the suite's write roots that is
   missing or an empty directory; the default is <state>/uisnap/out/<UTC yyyymmdd.hhmmss>[.n].
2. Build tools/uisnap/uisnap.swift when needed. The source is copied to <state>/uisnap/build/<its sha256>/ and
   compiled there by the Command Line Tools' swiftc with guard.uisnap_build_argv (the one argv the uisnap guard
   mode allows before seal()), with the clang module cache beside the build directories. build.json records
   the argv, the source and binary sha256s and the real paths of swiftc and the SDK; build.log holds the
   compiler's own output. A later run reuses the binary while all of those still match, and a successful build
   removes older build directories. One build at a time (an flock on <state>/uisnap/build/build.lock).
3. Register the binary with the guard (guard.permit_uisnap_binary: its path and sha256). Start the engine in this
   process with api.server.run (command serve, an ephemeral 127.0.0.1 port, its ready line swallowed), which
   seals the guard. In its on_ready hook: issue one bootstrap code in process, start the built binary (the only
   argv the uisnap mode allows after seal(), and only while the file is unchanged; no arguments), write one JSON line
   {"url", "seed", "timeout_s"} to its stdin and close it, read its JSON-lines records under a hard deadline
   (the binary has its own, shorter one), write each PNG and a sanitised report.json through the writer helper
   (0600, never overwriting), then stop the engine.
4. Print codes, counts and paths only:

       uisnap ok seed=<n> build=<built|cached> pngs=<n> page_errors=<n|none> runtime_s=<s>
       png <step> <path>          one per snapshot
       report <path>

   On a failure the first line says "failed code=<code>", the lines for whatever was written follow, and the
   command ends with refused:<code> on stderr and exit status 2. A failed build prints only
   "build_log <path>" (the compiler's output, about our own source) before its refusal.

The URL holds the single-use code, so it goes only down the child's stdin pipe: never argv, stdout, stderr, a
log or a file. The child's stderr is read and dropped (only its line count is kept); its stdout must hold
nothing but well-formed records. Everything the child reports is re-checked here (step names and order, PNG
signature and size, report keys and types) before it is written.

Standard library only; upstream is reached through the engine and the writer helper, never directly.
"""

import base64
import binascii
import datetime
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import threading
import time

from . import config, guard, roots
from .errors import SuiteError

SOURCE = os.path.join(guard.REPO_ROOT, "tools", "uisnap", guard.UISNAP_SOURCE_NAME)
STEPS = ("initial", "market", "ladder", "help", "inplay", "closed")
DEFAULT_SEED = 1
SEED_DIGITS = 9                       # the UI's seed box takes 1-9 digits (ui/app.js parseSeed)
VIEWPORT = (1470, 830)                # the Air's Safari viewport (DESIGN.md 8.1), in points
RUN_TIMEOUT_S = 240                   # the binary's own hard deadline; this process waits RUN_GRACE_S longer
RUN_GRACE_S = 20
BUILD_TIMEOUT_S = 600
LOCK_TIMEOUT_S = 900
MAX_SOURCE_BYTES = 1 << 20
MAX_RECORD_BYTES = 64 << 20           # all of the child's stdout
MAX_PNG_BYTES = 16 << 20
MAX_LOG_BYTES = 256 << 10
MAX_BUILD_RECORD_BYTES = 64 << 10
BUILD_FILES = (guard.UISNAP_SOURCE_NAME, guard.UISNAP_BINARY_NAME, "build.json", "build.log")
LANG = "en_GB.UTF-8"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The binary's exit statuses (tools/uisnap/uisnap.swift, enum Exit) and the codes they become.
EXIT_CODES = {
    10: "uisnap_bad_input", 11: "uisnap_navigation_refused", 12: "uisnap_load_failed", 13: "uisnap_not_connected",
    14: "uisnap_step_failed", 15: "uisnap_snapshot_failed", 16: "uisnap_window_onscreen", 17: "uisnap_timeout",
    18: "uisnap_page_errors", 19: "uisnap_failed",
}
_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_DIGITS_RE = re.compile(r"[0-9]{1,%d}" % SEED_DIGITS)


# --- arguments and places ------------------------------------------------------------------------

def parse_args(args):
    """{"seed": int, "out": absolute normalised path or None} for `[--seed N] [--out DIR]`, each at most once."""
    args = list(args)
    options = {"seed": DEFAULT_SEED, "out": None}
    seen = set()
    while args:
        flag = args.pop(0)
        if flag not in ("--seed", "--out") or flag in seen or not args:
            raise SuiteError("bad_arguments")
        seen.add(flag)
        value = args.pop(0)
        if flag == "--seed":
            if not (value.isascii() and _DIGITS_RE.fullmatch(value)):
                raise SuiteError("bad_arguments")
            options["seed"] = int(value)
        else:
            if not value or not os.path.isabs(value) or "\0" in value:
                raise SuiteError("bad_arguments")
            options["out"] = os.path.normpath(value)
    return options


def build_root(home_dir=None):
    return os.path.join(roots.state_dir(home_dir), *guard.UISNAP_BUILD_PARTS)


def out_root(home_dir=None):
    return os.path.join(roots.state_dir(home_dir), "uisnap", "out")


def check_out(path, home_dir=None):
    """The output directory to use: path (inside the write roots, missing or empty) or a fresh default one."""
    if path is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d.%H%M%S")
        base = os.path.join(out_root(home_dir), stamp)
        candidate, n = base, 1
        while os.path.lexists(candidate):
            n += 1
            candidate = "%s.%d" % (base, n)
        return candidate
    path, _root = roots.place(path, home_dir)            # write_outside_roots, state_root_not_agreed, ...
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return path
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SuiteError("not_a_directory")
    if os.listdir(path):
        raise SuiteError("uisnap_out_not_empty")
    return path


def child_env(home_dir=None):
    """The whole environment of swiftc and of the binary (guard.uisnap_argv_ok checks its keys)."""
    return {"HOME": roots.home() if home_dir is None else home_dir, "LANG": LANG, "PATH": "/usr/bin:/bin",
            "TMPDIR": roots.tmp_dir("uisnap", home_dir), guard.FORBID_NETWORK_ENV: "1"}


# --- the build -------------------------------------------------------------------------------------

def read_source(path=SOURCE):
    """The Swift source bytes: a regular file, not a symlink, at most MAX_SOURCE_BYTES."""
    data = _read_regular(path, MAX_SOURCE_BYTES)
    if data is None:
        raise SuiteError("uisnap_source_invalid")
    return data


def toolchain():
    """{"swiftc": real path, "sdk": real path} of the Command Line Tools; uisnap_toolchain_missing otherwise."""
    if not (os.path.isfile(guard.SWIFTC) and os.access(guard.SWIFTC, os.X_OK) and os.path.isdir(guard.SWIFT_SDK)):
        raise SuiteError("uisnap_toolchain_missing")
    return {"swiftc": os.path.realpath(guard.SWIFTC), "sdk": os.path.realpath(guard.SWIFT_SDK)}


def ensure_binary(*, source_path=SOURCE, home_dir=None, run=subprocess.run):
    """(binary path, "built" or "cached") for the current source; builds it when needed."""
    source = read_source(source_path)
    digest = hashlib.sha256(source).hexdigest()
    tools = toolchain()
    top = build_root(home_dir)
    directory = os.path.join(top, digest)
    binary = os.path.join(directory, guard.UISNAP_BINARY_NAME)
    argv = guard.uisnap_build_argv(directory)
    roots.ensure_dir(top, home_dir=home_dir)
    lock_fd = _lock(os.path.join(top, "build.lock"))
    try:
        if cached_ok(directory, digest, argv, tools):
            return binary, "cached"
        _clear_build(directory)
        roots.ensure_dir(directory, home_dir=home_dir)
        roots.write_new(os.path.join(directory, guard.UISNAP_SOURCE_NAME), source, home_dir=home_dir)
        started = time.monotonic()
        try:
            result = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=child_env(home_dir), cwd=directory, timeout=BUILD_TIMEOUT_S, check=False)
            status, log = result.returncode, result.stdout or b""
        except subprocess.TimeoutExpired:
            status, log = None, b""
        roots.write_new(os.path.join(directory, "build.log"), log[-MAX_LOG_BYTES:], home_dir=home_dir)
        if status != 0 or _executable_digest(binary) is None:
            raise SuiteError("uisnap_build_failed")
        record = {"schema_version": 1, "argv": argv, "source_sha256": digest, "binary_sha256": _executable_digest(binary),
                  "swiftc": tools["swiftc"], "sdk": tools["sdk"], "build_s": round(time.monotonic() - started, 1)}
        roots.write_new(os.path.join(directory, "build.json"),
                        json.dumps(record, indent=1, sort_keys=True).encode("ascii") + b"\n", home_dir=home_dir)
        _prune(top, keep=digest)
        return binary, "built"
    finally:
        os.close(lock_fd)


def cached_ok(directory, digest, argv, tools):
    """True when directory holds a finished build of this source, argv and toolchain, unchanged since."""
    data = _read_regular(os.path.join(directory, "build.json"), MAX_BUILD_RECORD_BYTES)
    try:
        record = json.loads(data.decode("ascii")) if data is not None else None
    except (ValueError, UnicodeDecodeError):
        record = None
    if not isinstance(record, dict):
        return False
    source = _read_regular(os.path.join(directory, guard.UISNAP_SOURCE_NAME), MAX_SOURCE_BYTES)
    return (record.get("schema_version") == 1 and record.get("argv") == argv and record.get("source_sha256") == digest
            and record.get("swiftc") == tools["swiftc"] and record.get("sdk") == tools["sdk"]
            and source is not None and hashlib.sha256(source).hexdigest() == digest
            and isinstance(record.get("binary_sha256"), str)
            and _executable_digest(os.path.join(directory, guard.UISNAP_BINARY_NAME)) == record["binary_sha256"])


def _lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() > deadline:
                os.close(fd)
                raise SuiteError("uisnap_build_failed") from None
            time.sleep(0.2)


def _clear_build(directory):
    """Remove an old or partial build's known files and its directory (a symlink or odd entry refuses)."""
    try:
        info = os.lstat(directory)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise SuiteError("not_a_directory")
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if name not in BUILD_FILES or not stat.S_ISREG(os.lstat(path).st_mode):
            raise SuiteError("uisnap_build_failed")
        os.remove(path)
    os.rmdir(directory)


def _prune(top, keep):
    """Remove the other <sha256> build directories (best effort; the module cache and the lock stay)."""
    for name in os.listdir(top):
        if name != keep and _HEX64_RE.fullmatch(name):
            try:
                _clear_build(os.path.join(top, name))
            except (OSError, SuiteError):
                pass


def _executable_digest(path):
    """sha256 of a regular, executable file owned by this user and writable by nobody else; None otherwise."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022
            or not info.st_mode & stat.S_IXUSR):
        return None
    data = _read_regular(path, 256 << 20)
    return None if data is None else hashlib.sha256(data).hexdigest()


def _read_regular(path, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


# --- the child's records -----------------------------------------------------------------------------

def png_size(data):
    """(width, height) from a PNG's IHDR, or None when data is not a PNG."""
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def viewport_size_ok(width, height):
    """The whole viewport at an integer scale of 1 to 3."""
    return any((width, height) == (VIEWPORT[0] * scale, VIEWPORT[1] * scale) for scale in (1, 2, 3))


def parse_records(data):
    """([(step, png bytes), ...] in step order, report dict or None, code or None) from the child's stdout.

    Anything that is not a well-formed record, a step out of order or repeated, a PNG that is not the whole
    viewport, or a record after the report is uisnap_bad_output.
    """
    pngs, report = [], None
    if len(data) > MAX_RECORD_BYTES:
        return pngs, None, "uisnap_bad_output"
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    for line in lines:
        try:
            record = json.loads(line.decode("ascii"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            return pngs, report, "uisnap_bad_output"
        if not isinstance(record, dict) or report is not None:
            return pngs, report, "uisnap_bad_output"
        kind = record.get("t")
        if kind == "png":
            if set(record) != {"t", "name", "width", "height", "png"}:
                return pngs, report, "uisnap_bad_output"
            expected = STEPS[len(pngs)] if len(pngs) < len(STEPS) else None
            encoded = record["png"]
            if record["name"] != expected or not isinstance(encoded, str) or len(encoded) > MAX_PNG_BYTES * 4 // 3 + 4:
                return pngs, report, "uisnap_bad_output"
            try:
                png = base64.b64decode(encoded.encode("ascii"), validate=True)
            except (binascii.Error, UnicodeEncodeError, ValueError):
                return pngs, report, "uisnap_bad_output"
            size = png_size(png)
            if (size is None or len(png) > MAX_PNG_BYTES or size != (record["width"], record["height"])
                    or not viewport_size_ok(*size)):
                return pngs, report, "uisnap_bad_output"
            pngs.append((expected, png))
        elif kind == "report":
            report = sanitise_report(record)
        else:
            return pngs, report, "uisnap_bad_output"
    return pngs, report, None


def _code(value):
    return isinstance(value, str) and bool(_CODE_RE.fullmatch(value))


def _count(value):
    return type(value) is int and 0 <= value < 1 << 40


def _scalar(value):
    return type(value) is bool or _count(value) or _code(value)


def sanitise_report(record):
    """The child's report reduced to known keys holding codes, counts and booleans; anything else is dropped."""
    out = {}
    if _code(record.get("code")):
        out["code"] = record["code"]
    steps = record.get("steps")
    if isinstance(steps, list):
        kept = []
        for step in steps[:len(STEPS)]:
            if isinstance(step, dict) and step.get("name") in STEPS and type(step.get("ok")) is bool \
                    and _count(step.get("ms")):
                entry = {"name": step["name"], "ok": step["ok"], "ms": step["ms"]}
                if _code(step.get("code")):
                    entry["code"] = step["code"]
                kept.append(entry)
        out["steps"] = kept
    checks = record.get("checks")
    if isinstance(checks, dict):
        out["checks"] = {key: value for key, value in sorted(checks.items())[:64] if _code(key) and _scalar(value)}
    for key in ("page_errors", "rejections", "csp_violations"):
        if key in record and (record[key] is None or _count(record[key])):
            out[key] = record[key]
    for key in ("navigations_refused", "onscreen_windows", "onscreen_samples", "scale", "runtime_ms"):
        if _count(record.get(key)):
            out[key] = record[key]
    if record.get("error_collection") in ("verified", "unverified", "unavailable"):
        out["error_collection"] = record["error_collection"]
    viewport = record.get("viewport")
    if isinstance(viewport, list) and len(viewport) == 2 and all(_count(v) for v in viewport):
        out["viewport"] = viewport
    return out


# --- running the binary --------------------------------------------------------------------------

class Outcome:
    """What one run produced: the code (None for success), written paths, the report and counts."""

    def __init__(self):
        self.code = None
        self.pngs = []                  # [(step, path), ...]
        self.report = None
        self.report_path = None
        self.child_exit = None
        self.stderr_lines = 0

    def fail(self, code):
        if self.code is None:
            self.code = code


def snap(app, binary, seed, out_dir, *, timeout_s=RUN_TIMEOUT_S, grace_s=RUN_GRACE_S, home_dir=None, popen=None):
    """Run the binary against app's engine and write its output into out_dir; returns an Outcome. Never raises
    for a failure of the child: the Outcome carries the code."""
    from .api import server
    outcome = Outcome()
    request = json.dumps({"url": server.bootstrap_url(app.port, app.auth.issue_code()), "seed": seed,
                          "timeout_s": timeout_s}, separators=(",", ":")).encode("ascii") + b"\n"
    try:
        process = (popen or subprocess.Popen)([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, env=child_env(home_dir),
                                              cwd=os.path.dirname(binary), close_fds=True)
    except OSError:
        raise SuiteError("uisnap_failed") from None   # (a guard refusal is a SuiteError and passes through)
    stdout = io.BytesIO()
    readers = [threading.Thread(target=_drain, args=(process.stdout, stdout, MAX_RECORD_BYTES), daemon=True),
               threading.Thread(target=_count_lines, args=(process.stderr, outcome), daemon=True)]
    for reader in readers:
        reader.start()
    try:
        process.stdin.write(request)
        process.stdin.close()
    except OSError:
        pass                                # the child has gone already: its exit status says why
    del request
    deadline = time.monotonic() + timeout_s + grace_s
    while True:
        try:
            outcome.child_exit = process.wait(0.25)
            break
        except subprocess.TimeoutExpired:
            pass
        if app.stopping.is_set():
            outcome.fail("engine_stopping")
        elif time.monotonic() > deadline:
            outcome.fail("uisnap_timeout")
        else:
            continue
        _stop_child(process)
        outcome.child_exit = process.returncode
        break
    for reader in readers:
        reader.join(5.0)
    if outcome.child_exit != 0:
        outcome.fail(EXIT_CODES.get(outcome.child_exit, "uisnap_failed"))
    pngs, report, problem = parse_records(stdout.getvalue())
    if problem is not None:
        outcome.fail(problem)
    if pngs or report is not None:
        roots.ensure_dir(out_dir, home_dir=home_dir)
    for step, png in pngs:
        path = os.path.join(out_dir, step + ".png")
        roots.write_new(path, png, home_dir=home_dir)
        outcome.pngs.append((step, path))
    if report is not None:
        report = dict(report, seed=seed, pngs=len(pngs), child_exit=outcome.child_exit,
                      child_stderr_lines=outcome.stderr_lines)
        outcome.report = report
        outcome.report_path = os.path.join(out_dir, "report.json")
        roots.write_new(outcome.report_path, json.dumps(report, indent=1, sort_keys=True).encode("ascii") + b"\n",
                        home_dir=home_dir)
    if outcome.code is None and (report is None or report.get("code") != "ok" or len(pngs) != len(STEPS)
                                 or report.get("onscreen_windows") != 0):
        outcome.fail("uisnap_bad_output")
    return outcome


def _drain(stream, sink, limit):
    """Copy stream into sink up to limit + 1 bytes, then keep reading (and dropping) until EOF."""
    total = 0
    try:
        while True:
            chunk = stream.read(1 << 16)
            if not chunk:
                break
            if total <= limit:
                sink.write(chunk[:limit + 1 - total])
            total += len(chunk)
    except (OSError, ValueError):
        pass


def _count_lines(stream, outcome):
    try:
        while True:
            chunk = stream.read(1 << 16)
            if not chunk:
                break
            outcome.stderr_lines += chunk.count(b"\n")
    except (OSError, ValueError):
        pass


def _stop_child(process):
    try:
        process.terminate()
        process.wait(3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(5.0)
    except OSError:
        pass


# --- the command -------------------------------------------------------------------------------------

def main(options, *, out=None, binary=None, timeout_s=RUN_TIMEOUT_S, grace_s=RUN_GRACE_S, home_dir=None, ui_dir=None):
    """bin/suite uisnap. binary, timeout_s, grace_s and ui_dir (another UI for the engine to serve) exist for tests;
    the guard still starts only a binary in the build directory layout, registered here before the engine seals
    it (guard.permit_uisnap_binary: that file, unchanged)."""
    from .api import control, server        # here, not at the top: no other command loads socket or http
    out = sys.stdout if out is None else out
    started = time.monotonic()
    cfg = config.load(home_dir)
    if cfg.get("data_roots"):
        raise SuiteError("synthetic_only")          # uisnap never runs against anything but the synthetic engine
    if control.engine_running(home_dir):
        raise SuiteError("engine_running")
    out_dir = check_out(options["out"], home_dir)
    if binary is None:
        try:
            binary, build = ensure_binary(home_dir=home_dir)
        except SuiteError as exc:
            if exc.code == "uisnap_build_failed":
                log = os.path.join(build_root(home_dir), hashlib.sha256(read_source()).hexdigest(), "build.log")
                if os.path.isfile(log):
                    out.write("build_log %s\n" % log)        # the compiler's own output, about our source only
                    out.flush()
            raise
    else:
        build = "given"
    guard.permit_uisnap_binary(binary)              # after seal() the guard starts this file only, unchanged
    results = []

    def on_ready(app):
        try:
            results.append(snap(app, binary, options["seed"], out_dir, timeout_s=timeout_s, grace_s=grace_s,
                                home_dir=home_dir))
        finally:
            app.request_stop("stopped")

    server.run(cfg, command="serve", port=0, on_ready=on_ready, out=io.StringIO(), home_dir=home_dir, ui_dir=ui_dir)
    outcome = results[0] if results else Outcome()
    if not results:
        outcome.fail("uisnap_failed")
    page_errors = None if outcome.report is None else outcome.report.get("page_errors")
    out.write("uisnap %s seed=%d build=%s pngs=%d page_errors=%s runtime_s=%.1f\n" % (
        "ok" if outcome.code is None else "failed code=" + outcome.code, options["seed"], build, len(outcome.pngs),
        "none" if page_errors is None else page_errors, time.monotonic() - started))
    for step, path in outcome.pngs:
        out.write("png %s %s\n" % (step, path))
    if outcome.report_path is not None:
        out.write("report %s\n" % outcome.report_path)
    out.flush()
    if outcome.code is not None:
        raise SuiteError(outcome.code)
    return 0
