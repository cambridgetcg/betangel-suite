"""bin/suite uisnap (DESIGN.md 11 uisnap, test group 7; betangel_suite/uisnap.py, tools/uisnap/uisnap.swift).

Synthetic only. Three tiers:

- Always on, in process: argument parsing, the output directory rules, the child's environment, the record
  parser and report sanitiser, the exit-code table against the Swift source, and a static read of the Swift
  source (never visible, never off the loopback, no file or screen access of its own).
- Always on, in fresh uisnap-mode children (an audit hook cannot be removed): the guard mode itself (before
  seal() only the exact swiftc argv, after it only the built binary, both with the exact environment; nothing
  else, including the engine's git and /usr/bin/open shapes), and the whole command run against the real
  engine in process with a stub binary placed in the build directory layout. The stub is a small Python program
  standing in for WebKit: it reads the URL from stdin, really bootstraps over 127.0.0.1, and prints records.
  /usr/bin/open is never started: its shape is checked through the pure predicate only.
- Heavy, opt-in (`bin/suite test --heavy`, tests.HEAVY): the real swiftc build and a real
  offscreen WKWebView run, twice (the second run reuses the build). swiftc takes about 40 s with a cold module
  cache and WebKit about 15 s per run.

Every engine binds 127.0.0.1 on an ephemeral port in a temporary HOME and is stopped by the command itself; no
test prints a bootstrap code or a session token (the stub keeps them in a 0600 file in its HOME so that the test
can check they appear nowhere else).
"""

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import unittest
import zlib

from betangel_suite import cli, errors, guard, roots, uisnap
from tests import HEAVY, HEAVY_ONLY, PRELUDE, PYTHON, ROOT, child_env, make_home, run_python, run_suite
from tests.test_http_support import control_path, secret_shaped, secrets_in, short_home

SWIFT = os.path.join(ROOT, "tools", "uisnap", "uisnap.swift")
HEX = "b" * 64
STDOUT_LINE = re.compile(
    r"uisnap (?:ok|failed code=[a-z][a-z0-9_]*) seed=[0-9]+ build=(?:built|cached|given) pngs=[0-9]+ "
    r"page_errors=(?:[0-9]+|none) runtime_s=[0-9]+\.[0-9]\n"
    r"|png (?:initial|market|ladder|help|inplay|closed) /[^\s]+\.png\n|report /[^\s]+/report\.json\n")


def tiny_png(width, height):
    """A valid 1-bit greyscale PNG of this size (all black; small after compression)."""
    raw = (b"\x00" + b"\x00" * ((width + 7) // 8)) * height

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (uisnap.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_record(name, width=1470, height=830, data=None):
    data = tiny_png(width, height) if data is None else data
    return {"t": "png", "name": name, "width": width, "height": height,
            "png": base64.b64encode(data).decode("ascii")}


def lines(*records):
    return b"".join(json.dumps(record).encode("ascii") + b"\n" for record in records)


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# --- always on, in process ------------------------------------------------------------------------

class ArgumentTests(unittest.TestCase):

    def test_parse_args(self):
        self.assertEqual(uisnap.parse_args([]), {"seed": 1, "out": None})
        self.assertEqual(uisnap.parse_args(["--seed", "999999999"]), {"seed": 999999999, "out": None})
        self.assertEqual(uisnap.parse_args(["--out", "/a/b/../c", "--seed", "0"]), {"seed": 0, "out": "/a/c"})
        for args in (["--seed"], ["--seed", "x"], ["--seed", "-1"], ["--seed", "1e3"], ["--seed", "1000000000"],
                     ["--seed", "١"], ["--seed", ""], ["--seed", "1", "--seed", "2"], ["--out"],
                     ["--out", "relative/dir"], ["--out", ""], ["--out", "/a\0b"], ["--port", "0"], ["1"],
                     ["--out", "/a", "--out", "/b"], ["--print-url"]):
            with self.assertRaises(errors.SuiteError) as caught:
                uisnap.parse_args(args)
            self.assertEqual(caught.exception.code, "bad_arguments", args)

    def test_the_command_is_wired_in_its_own_guard_mode(self):
        self.assertEqual(cli.guard_mode("uisnap"), "uisnap")
        self.assertIn("uisnap", guard.MODES)
        self.assertEqual(roots.tmp_dir("uisnap", "/h"), roots.tmp_dir("test", "/h"))
        self.assertNotIn("uisnap", cli.NO_RUN_MARKER_CHECK)

    def test_output_directory_rules(self):
        home = make_home(self)
        state = roots.state_dir(home)
        default = uisnap.check_out(None, home)
        self.assertTrue(default.startswith(uisnap.out_root(home) + os.sep), default)
        self.assertEqual(secret_shaped(default), [])
        inside = os.path.join(state, "snaps")
        self.assertEqual(uisnap.check_out(inside, home), inside)
        os.makedirs(inside)
        self.assertEqual(uisnap.check_out(inside, home), inside)              # an empty directory is fine
        open(os.path.join(inside, "x.png"), "wb").close()
        for path, code in ((inside, "uisnap_out_not_empty"), (os.path.join(inside, "x.png"), "not_a_directory"),
                           (os.path.join(home, "elsewhere"), "write_outside_roots"),
                           (os.path.join(ROOT, "docs", "synthetic"), "write_outside_roots"),
                           (os.path.join(roots.data_home(home), "shots"), "state_root_not_agreed")):
            with self.assertRaises(errors.SuiteError) as caught:
                uisnap.check_out(path, home)
            self.assertEqual(caught.exception.code, code, path)
        self.assertFalse(os.path.lexists(roots.data_home(home)))

    def test_child_environment_is_what_the_guard_allows(self):
        env = uisnap.child_env("/h")
        self.assertEqual(set(env), set(guard.UISNAP_ENV_KEYS))
        self.assertEqual((env["PATH"], env[guard.FORBID_NETWORK_ENV], env["HOME"]), ("/usr/bin:/bin", "1", "/h"))
        self.assertEqual(env["TMPDIR"], roots.tmp_dir("uisnap", "/h"))
        directory = os.path.join(uisnap.build_root("/h"), HEX)
        self.assertTrue(guard.uisnap_argv_ok(guard.uisnap_build_argv(directory), env, uisnap.build_root("/h"), False))
        self.assertTrue(guard.uisnap_argv_ok([os.path.join(directory, "uisnap")], env, uisnap.build_root("/h"), True))

    def test_exit_codes_are_listed(self):
        for code in list(uisnap.EXIT_CODES.values()) + ["uisnap_bad_output", "uisnap_timeout", "engine_stopping"]:
            self.assertIn(code, errors.CODES)


class RecordTests(unittest.TestCase):

    def test_well_formed_records(self):
        report = {"t": "report", "code": "ok", "onscreen_windows": 0, "page_errors": 0, "viewport": [1470, 830]}
        pngs, parsed, problem = uisnap.parse_records(lines(*[png_record(s) for s in uisnap.STEPS], report))
        self.assertIsNone(problem)
        self.assertEqual([step for step, _data in pngs], list(uisnap.STEPS))
        self.assertEqual(uisnap.png_size(pngs[0][1]), (1470, 830))
        self.assertEqual(parsed, {"code": "ok", "onscreen_windows": 0, "page_errors": 0, "viewport": [1470, 830]})
        _pngs, _report, problem = uisnap.parse_records(lines(png_record("initial", 2940, 1660)))
        self.assertIsNone(problem)

    def test_malformed_records_are_refused(self):
        good = png_record("initial")
        cases = {
            "not_json": b"hello\n",
            "out_of_order": lines(png_record("market")),
            "repeated": lines(good, png_record("initial")),
            "unknown_step": lines(png_record("desktop")),
            "extra_key": lines(dict(good, url="x")),
            "wrong_size": lines(png_record("initial", 100, 100)),
            "size_mismatch": lines(dict(good, width=2940)),
            "not_png": lines(png_record("initial", data=b"GIF89a" + b"\0" * 40)),
            "bad_base64": lines(dict(good, png="!!!")),
            "unknown_kind": lines({"t": "log", "text": "x"}),
            "after_report": lines({"t": "report", "code": "ok"}, good),
            "array": b"[]\n",
            "too_long": b"x" * (uisnap.MAX_RECORD_BYTES + 1),
        }
        for name, data in cases.items():
            self.assertEqual(uisnap.parse_records(data)[2], "uisnap_bad_output", name)

    def test_report_keeps_codes_counts_and_booleans_only(self):
        report = uisnap.sanitise_report({
            "t": "report", "code": "ok", "evil": "x", "page_errors": None, "csp_violations": 2,
            "error_collection": "verified", "onscreen_windows": 0, "onscreen_samples": 140, "scale": 2,
            "steps": [{"name": "initial", "ok": True, "ms": 12, "code": "fine"},
                      {"name": "elsewhere", "ok": True, "ms": 1}, {"name": "market", "ok": "yes", "ms": 1}],
            "checks": {"market_runners": 8, "raf": True, "note": "has a space", "path": "/x/y",
                       "url": "http://127.0.0.1:1/", "Bad Key": 1, "nested": {"a": 1}, "negative": -1},
            "viewport": [1470, 830, 1], "runtime_ms": 1.5,
        })
        self.assertEqual(report, {
            "code": "ok", "page_errors": None, "csp_violations": 2, "error_collection": "verified",
            "onscreen_windows": 0, "onscreen_samples": 140, "scale": 2,
            "steps": [{"name": "initial", "ok": True, "ms": 12, "code": "fine"}],
            "checks": {"market_runners": 8, "raf": True},
        })


class SwiftSourceTests(unittest.TestCase):
    """A static read of tools/uisnap/uisnap.swift: what it must do, and what it must never contain."""

    @classmethod
    def setUpClass(cls):
        with open(SWIFT, encoding="utf-8") as handle:
            cls.text = handle.read()
        # The code without // comments (the header names the calls it never makes); "http://" keeps its slashes.
        cls.code = re.sub(r"(?m)(^|\s)//.*$", r"\1", cls.text)

    def test_never_visible(self):
        for needle in ("setActivationPolicy(.prohibited)", "CGWindowListCopyWindowInfo([.optionOnScreenOnly]",
                       "styleMask: [.borderless]", "defer: true", "OffscreenWindow(contentRect: viewport",
                       "override var canBecomeKey: Bool { return false }",
                       "override var canBecomeMain: Bool { return false }"):
            self.assertTrue(needle in self.code, needle)
        for needle in ("orderFront", "orderBack", "orderWindow", "makeKey", "makeMain", ".activate(",
                       "activateIgnoringOtherApps", "NSWorkspace", "NSAlert", "NSPanel", "NSOpenPanel", "runModal",
                       "NSStatusBar", "NSMenu", "setActivationPolicy(.regular", "setActivationPolicy(.accessory",
                       "unhide", "NSWindow(", "screencapture", "CGWindowListCreateImage", "SCScreenshot",
                       "CGDisplayCreateImage"):
            self.assertFalse(needle in self.code, needle)

    def test_never_off_the_loopback(self):
        for needle in ("WKWebsiteDataStore.nonPersistent()", ".nonPersistent()",
                       "isFraudulentWebsiteWarningEnabled = false", "upgradeKnownHostsToHTTPS = false",
                       "javaScriptCanOpenWindowsAutomatically = false", ".cancelAuthenticationChallenge",
                       'url.scheme == "http" && url.host == "127.0.0.1" && url.port == input.port'):
            self.assertTrue(needle in self.text, needle)
        self.assertFalse("https://" in self.text)
        for match in re.finditer(r"http://", self.text):
            self.assertTrue(self.text[match.end():].startswith("127"), self.text[match.start():match.start() + 40])
        for needle in ("URLSession.shared", "URLSession(", "dataTask", "NSURLConnection", "Process(", "NSTask", "posix_spawn", "system(", "dlopen",
                       "fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "localStorage",
                       "sessionStorage", "indexedDB", "document.cookie", "eval(", "new Function"):
            self.assertFalse(needle in self.code, needle)
        joined = "".join
        for needle in (joined(("key", "chain")), joined(("betfair", ".com")), joined(("secur", "ity "))):
            self.assertFalse(needle in self.text.casefold(), needle)

    def test_the_navigation_delegates_are_exactly_these(self):
        # The binary runs outside the Python audit hook: these two delegates and allowed() are its only loopback
        # barrier, so their whole text is pinned (the heavy tier also drives a refused navigation for real).
        expected = {
            "navigationAction": """
        decidedActions += 1
        if allowed(navigationAction.request.url) && navigationAction.targetFrame?.isMainFrame == true {
            decisionHandler(.allow)
            return
        }
        refusedNavigations += 1
        decisionHandler(.cancel)
        finish(.navigationRefused)
""",
            "navigationResponse": """
        if navigationResponse.isForMainFrame && allowed(navigationResponse.response.url)
            && navigationResponse.canShowMIMEType {
            decisionHandler(.allow)
            return
        }
        refusedNavigations += 1
        decisionHandler(.cancel)
        finish(.navigationRefused)
""",
            "allowed": """
        guard let url = url else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == input.port && url.user == nil
            && url.password == nil
"""}
        bodies = {}
        for match in re.finditer(r"\n    func (webView\(_ webView: WKWebView, decidePolicyFor (\w+): [^{]*|allowed\(_ url: URL\?\) "
                                 r"-> Bool )\{\n(.*?)\n    \}\n", self.text, re.S):
            bodies[match.group(2) or "allowed"] = "\n" + match.group(3) + "\n"
        self.assertEqual(bodies, expected)
        self.assertEqual(self.text.count("decidePolicyFor"), 4)    # the two delegates and their two selector names

    def test_no_files_arguments_or_stray_output(self):
        # The URL arrives on stdin only, records leave on the original stdout only, and nothing is written to disk.
        for needle in ("CommandLine.arguments", "ProcessInfo.processInfo.arguments", "print(", "NSLog(", "os_log",
                       "FileManager", "FileHandle.standardError", "createFile", "write(to", "write(toFile", "fopen(",
                       "mkdir(", "unlink(", "rename(", "ProcessInfo.processInfo.environment", "getenv("):
            self.assertFalse(needle in self.code, needle)
        self.assertEqual(re.findall(r"\bopen\(([^)]*)\)", self.code), ['"/dev/null", O_WRONLY'])
        self.assertIn("dup2(null, STDOUT_FILENO)", self.code)

    def test_steps_viewport_and_exit_codes_match_the_python_side(self):
        names = re.search(r"let stepNames = \[([^\]]*)\]", self.text).group(1)
        self.assertEqual(tuple(re.findall(r'"([a-z]+)"', names)), uisnap.STEPS)
        self.assertIn("NSRect(x: 0, y: 0, width: %d, height: %d)" % uisnap.VIEWPORT, self.text)
        body = re.search(r"enum Exit: Int32 \{(.*?)\n\}", self.text, re.S).group(1)
        numbers = {name: int(value) for name, value in re.findall(r"case (\w+) = (\d+)", body)}
        names = dict(re.findall(r'case \.(\w+): return "([a-z_]+)"', body))
        self.assertEqual(set(numbers), set(names))
        self.assertEqual(names.pop("ok"), "ok")
        self.assertEqual(numbers.pop("ok"), 0)
        self.assertEqual({numbers[name]: "uisnap_" + code for name, code in names.items()}, uisnap.EXIT_CODES)

    def test_scanner_finds_nothing_in_the_uisnap_files(self):
        targets = [os.path.join("tools", "uisnap"), os.path.join("betangel_suite", "uisnap.py"),
                   os.path.join("tests", "test_uisnap.py")]
        scan = subprocess.run([PYTHON, "-I", "-S", "-B", os.path.join(ROOT, "tools", "hygiene_scan.py"), "--root", ROOT,
                               *targets], env=dict(os.environ), cwd=ROOT, capture_output=True, timeout=120)
        output = (scan.stdout + scan.stderr).decode("utf-8", "replace")
        self.assertEqual(scan.returncode, 0, output)
        self.assertIn("hygiene_scan: OK", output)


class BuildCacheTests(unittest.TestCase):
    """ensure_binary through its run seam: the build layout, the record and the cache. Nothing is compiled here
    (the heavy tier compiles for real); the fake compiler only writes a stub where swiftc would put the binary."""

    def setUp(self):
        try:
            uisnap.toolchain()
        except errors.SuiteError:
            self.skipTest("no Command Line Tools swiftc")
        self.home = make_home(self)
        self.source = os.path.join(self.home, "uisnap.swift")
        self.write_source(b"// synthetic test source 1\n")
        self.calls = []

    def write_source(self, data):
        with open(self.source, "wb") as handle:
            handle.write(data)

    def fake_run(self, status=0, log=b"fake compiler output\n", timeout=False):
        def run(argv, **kwargs):
            self.calls.append(argv)
            directory = os.path.dirname(argv[-1])
            self.assertEqual(argv, guard.uisnap_build_argv(directory))
            self.assertEqual((kwargs["env"], kwargs["cwd"]), (uisnap.child_env(self.home), directory))
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            if timeout:
                raise subprocess.TimeoutExpired(argv, 1)
            if status == 0:
                with open(argv[-2], "wb") as handle:
                    handle.write(b"#!/bin/sh\nexit %d\n" % len(self.calls))
                os.chmod(argv[-2], 0o700)
            return subprocess.CompletedProcess(argv, status, log, None)
        return run

    def ensure(self, run=None):
        return uisnap.ensure_binary(source_path=self.source, home_dir=self.home, run=run or self.fake_run())

    def directory(self):
        with open(self.source, "rb") as handle:
            return os.path.join(uisnap.build_root(self.home), hashlib.sha256(handle.read()).hexdigest())

    def test_built_then_cached_then_rebuilt_when_anything_changed(self):
        binary, how = self.ensure()
        directory = self.directory()
        self.assertEqual((binary, how, len(self.calls)), (os.path.join(directory, "uisnap"), "built", 1))
        self.assertEqual(sorted(os.listdir(directory)), ["build.json", "build.log", "uisnap", "uisnap.swift"])
        record = read_json(os.path.join(directory, "build.json"))
        self.assertEqual(record["argv"], guard.uisnap_build_argv(directory))
        self.assertEqual(record["source_sha256"], os.path.basename(directory))
        self.assertEqual((record["swiftc"], record["sdk"]), (uisnap.toolchain()["swiftc"], uisnap.toolchain()["sdk"]))
        for name, mode in (("build.json", 0o600), ("build.log", 0o600), ("uisnap.swift", 0o600), ("uisnap", 0o700)):
            self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(directory, name)).st_mode), mode, name)
        self.assertEqual(self.ensure(), (binary, "cached"))
        self.assertEqual(len(self.calls), 1)
        with open(binary, "ab") as handle:                     # a changed binary is rebuilt
            handle.write(b"# changed\n")
        self.assertEqual(self.ensure(), (binary, "built"))
        record_path = os.path.join(directory, "build.json")    # so is one built with another SDK
        changed = dict(read_json(record_path), sdk="/elsewhere/MacOSX.sdk")
        with open(record_path, "w") as handle:
            json.dump(changed, handle)
        self.assertEqual(self.ensure(), (binary, "built"))
        self.assertEqual(len(self.calls), 3)
        os.makedirs(os.path.join(uisnap.build_root(self.home), "module-cache", "x"))
        self.write_source(b"// synthetic test source 2\n")      # a new source: a new directory, the old one pruned
        new_binary, how = self.ensure()
        self.assertEqual(how, "built")
        self.assertNotEqual(os.path.dirname(new_binary), directory)
        self.assertEqual(sorted(os.listdir(uisnap.build_root(self.home))),
                         sorted(["build.lock", "module-cache", os.path.basename(os.path.dirname(new_binary))]))

    def test_a_failed_or_slow_build_is_refused_and_retried(self):
        for run in (self.fake_run(status=1, log=b"error: synthetic\n"), self.fake_run(timeout=True)):
            with self.assertRaises(errors.SuiteError) as caught:
                self.ensure(run)
            self.assertEqual(caught.exception.code, "uisnap_build_failed")
            self.assertFalse(os.path.lexists(os.path.join(self.directory(), "build.json")))
            self.assertTrue(os.path.isfile(os.path.join(self.directory(), "build.log")))
        self.assertEqual(self.ensure()[1], "built")

    def test_odd_build_directories_and_sources_are_refused(self):
        os.makedirs(self.directory())
        open(os.path.join(self.directory(), "planted"), "w").close()
        with self.assertRaises(errors.SuiteError) as caught:
            self.ensure()
        self.assertEqual((caught.exception.code, self.calls), ("uisnap_build_failed", []))
        os.remove(self.source)
        os.symlink(SWIFT, self.source)
        with self.assertRaises(errors.SuiteError) as caught:
            self.ensure()
        self.assertEqual(caught.exception.code, "uisnap_source_invalid")


# --- always on: the guard mode, in fresh children --------------------------------------------------

ATTEMPT = """
import json, os, subprocess, sys
from betangel_suite import guard, roots
from betangel_suite.errors import SuiteError
results = {}
def attempt(name, fn):
    try:
        fn()
        results[name] = "ok"
    except SuiteError as exc:
        results[name] = str(exc)
    except Exception as exc:
        results[name] = "other:" + type(exc).__name__
"""

STUB = "#!/bin/sh\nexit 0\n"


def place_stub(path, text=STUB):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o700)
    return path


class GuardModeTests(unittest.TestCase):
    """The uisnap guard mode: exactly the swiftc argv before seal(), exactly the built binary after it."""

    ROOT_DIR = "/h/.local/state/betangel-suite/uisnap/build"

    def env(self, **changes):
        env = uisnap.child_env("/h")
        env.update(changes)
        return {key: value for key, value in env.items() if value is not None}

    def test_pure_shapes(self):
        ok, root = guard.uisnap_argv_ok, self.ROOT_DIR
        directory = os.path.join(root, HEX)
        build, binary = guard.uisnap_build_argv(directory), [os.path.join(directory, "uisnap")]
        self.assertEqual(build[0], "/Library/Developer/CommandLineTools/usr/bin/swiftc")
        self.assertEqual(build[-3:], ["-o", binary[0], os.path.join(directory, "uisnap.swift")])
        self.assertIn(os.path.join(root, "module-cache"), build)
        self.assertTrue(ok(build, self.env(), root, False))
        self.assertTrue(ok(binary, self.env(), root, True))
        self.assertFalse(ok(build, self.env(), root, True))          # the build only before seal()
        self.assertFalse(ok(binary, self.env(), root, False))        # the binary only after it
        for env in (None, self.env(PATH="/usr/local/bin:/usr/bin:/bin"), self.env(DYLD_INSERT_LIBRARIES="/x.dylib"),
                    self.env(PYTHONPATH="/x"), self.env(SQLITE_TMPDIR="/x"), self.env(PATH=None)):
            self.assertFalse(ok(build, env, root, False), env)
            self.assertFalse(ok(binary, env, root, True), env)
        other = os.path.join(root, "c" * 64)
        for argv in (build[:1] + ["-g"] + build[1:], build[:-1] + [os.path.join(other, "uisnap.swift")],
                     guard.uisnap_build_argv(os.path.join(root, "a" * 63)),
                     guard.uisnap_build_argv(os.path.join(root, "A" * 64)),
                     guard.uisnap_build_argv(os.path.join(root, "module-cache")),
                     guard.uisnap_build_argv(os.path.join("/h/elsewhere", HEX)),
                     guard.uisnap_build_argv(os.path.join(root, HEX, "..", HEX)),
                     guard.uisnap_build_argv("relative/" + HEX),
                     ["swiftc"] + build[1:], ["/usr/bin/swiftc"] + build[1:],
                     [part.replace("-O", "-Onone") for part in build],
                     [part.replace("macos14.0", "macos10.9") for part in build],
                     [part.replace("module-cache", "elsewhere") for part in build]):
            self.assertFalse(ok(argv, self.env(), root, False), argv)
        for argv in (binary + ["http://127.0.0.1:1/"], [os.path.join(root, HEX, "uisnap2")],
                     [os.path.join(root, "a" * 63, "uisnap")], [os.path.join("/h/elsewhere", HEX, "uisnap")],
                     [os.path.join(root, HEX, "..", HEX, "uisnap")], ["uisnap"], [os.path.join(root, "uisnap")],
                     ["/usr/bin/open", "http://127.0.0.1:8765/#c=" + "a" * 22],
                     ["git", "-C", "/h/.local/state/betangel-suite", "rev-parse", "--is-inside-work-tree"],
                     [PYTHON, "-I", "-S", "-B", "-c", "pass"]):
            for sealed in (False, True):
                self.assertFalse(ok(argv, self.env(), root, sealed), (argv, sealed))

    def test_the_hook_in_uisnap_mode(self):
        home = make_home(self)
        build_root = uisnap.build_root(home)
        binary = place_stub(os.path.join(build_root, HEX, "uisnap"))
        outside = place_stub(os.path.join(home, "outside", HEX, "uisnap"))
        other = place_stub(os.path.join(build_root, "c" * 64, "uisnap"))        # the layout, but never registered
        linked = os.path.join(build_root, "d" * 64, "uisnap")                  # the layout, a symlink to a program
        os.makedirs(os.path.dirname(linked), mode=0o700)
        os.symlink("/usr/bin/true", linked)
        code = ATTEMPT + "\nguard.arm('uisnap')\n" + """
from betangel_suite import uisnap
env = uisnap.child_env()
directory = os.path.join(uisnap.build_root(), %r)
build = guard.uisnap_build_argv(directory)
binary, outside, other, linked = %r, %r, %r, %r
def run(argv, environment=env):
    subprocess.run(argv, env=environment, capture_output=True, timeout=120)
def replace(path):
    with open(path, "a") as handle:
        handle.write("# changed after it was registered\\n")
attempt("build_before_seal", lambda: run(build))
attempt("build_inherited_env", lambda: run(build, None))
attempt("build_extra_env", lambda: run(build, dict(env, DYLD_INSERT_LIBRARIES="/x.dylib")))
attempt("build_extra_flag", lambda: run(build[:1] + ["-g"] + build[1:]))
attempt("binary_before_seal", lambda: run([binary]))
attempt("git_probe", lambda: run(["git", "-C", roots.state_dir(), "rev-parse", "--is-inside-work-tree"],
                                 dict(env)))
attempt("python", lambda: run([sys.executable, "-I", "-S", "-B", "-c", "pass"]))
attempt("shell", lambda: run(["/bin/sh", "-c", "true"]))
attempt("permit_symlink", lambda: guard.permit_uisnap_binary(linked))
attempt("permit_outside_build_root", lambda: guard.permit_uisnap_binary(outside))
attempt("permit", lambda: guard.permit_uisnap_binary(binary))
attempt("permit_a_second", lambda: guard.permit_uisnap_binary(other))
guard.seal()
attempt("permit_after_seal", lambda: guard.permit_uisnap_binary(other))
attempt("binary_after_seal", lambda: run([binary]))
attempt("binary_posix_spawn", lambda: os.waitpid(os.posix_spawn(binary, [binary], env), 0))
attempt("binary_with_argument", lambda: run([binary, "http://127.0.0.1:1/"]))
attempt("binary_inherited_env", lambda: run([binary], None))
attempt("binary_outside_build_root", lambda: run([outside]))
attempt("binary_not_registered", lambda: run([other]))
attempt("binary_symlinked", lambda: run([linked]))
attempt("build_after_seal", lambda: run(build))
attempt("os_system", lambda: os.system("true"))
attempt("fork", lambda: os.fork())
attempt("dlopen", lambda: __import__("ctypes"))
replace(binary)
attempt("binary_replaced", lambda: run([binary]))
print(json.dumps(results))
""" % (HEX, binary, outside, other, linked)
        result = run_python(code, home, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        results = json.loads(result.stdout.strip().splitlines()[-1])
        # swiftc really starts (and fails at once: the source is missing); without the Command Line Tools the
        # spawn itself fails after the guard has let it through.
        self.assertIn(results.pop("build_before_seal"), ("ok", "other:FileNotFoundError"))
        self.assertEqual(results.pop("permit"), "ok")
        self.assertEqual(results.pop("permit_after_seal"), "guard_sealed")
        self.assertEqual(results.pop("binary_after_seal"), "ok")
        self.assertEqual(results.pop("binary_posix_spawn"), "ok")
        self.assertEqual(results.pop("dlopen"), "dlopen_refused")
        self.assertEqual(set(results.values()), {"subprocess_refused"}, results)

    def test_other_modes_refuse_the_uisnap_shapes(self):
        home = make_home(self)
        binary = place_stub(os.path.join(uisnap.build_root(home), HEX, "uisnap"))
        code = ATTEMPT + "\nguard.arm('engine')\n" + """
from betangel_suite import uisnap
env = uisnap.child_env()
attempt("build", lambda: subprocess.run(guard.uisnap_build_argv(os.path.dirname(%r)), env=env, capture_output=True))
attempt("binary", lambda: subprocess.run([%r], env=env, capture_output=True))
attempt("permit", lambda: guard.permit_uisnap_binary(%r))
guard.seal()
attempt("binary_sealed", lambda: subprocess.run([%r], env=env, capture_output=True))
print(json.dumps(results))
""" % (binary, binary, binary, binary)
        result = run_python(code, home)
        self.assertEqual(result.returncode, 0, result.stderr)
        results = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(results.pop("permit"), "guard_mode_conflict")
        self.assertEqual(set(results.values()), {"subprocess_refused"})
        # This process is the test runner (test mode): it refuses the binary before anything starts.
        with self.assertRaises(guard.GuardRefusal):
            subprocess.run([binary], env=uisnap.child_env(home), capture_output=True, timeout=30)


# --- always on: the command against the real engine, with a stub binary -----------------------------

FAKE = r'''
import base64, http.client, json, os, re, struct, sys, time, zlib

HOME = os.environ["HOME"]
MODE = sys.argv[1]
STEPS = ("initial", "market", "ladder", "help", "inplay", "closed")


def png(width, height):
    raw = (b"\x00" + b"\x00" * ((width + 7) // 8)) * height

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def emit(record):
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def save(name, value):
    fd = os.open(os.path.join(HOME, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle)


save("fake.pid", os.getpid())
data = sys.stdin.buffer.read()
expected = {"HOME", "LANG", "TMPDIR", "PATH", "BETANGEL_BETFAIR_FORBID_NETWORK"}
facts = {"stdin_lines": data.count(b"\n"),
         "env_ok": all(key in os.environ for key in expected) and os.environ["PATH"] == "/usr/bin:/bin",
         "env_extra": sorted(key for key in os.environ if key not in expected
                             and key not in ("PWD", "SHLVL", "_", "OLDPWD", "__CF_USER_TEXT_ENCODING"))}
request = json.loads(data)
facts["keys"] = sorted(request)
match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]+)/#c=([A-Za-z0-9_-]{22})", request["url"])
facts.update(url_ok=bool(match), seed=request["seed"], timeout_s=request["timeout_s"])

if MODE == "ok":
    port, code = int(match.group(1)), match.group(2)
    host = "127.0.0.1:%d" % port

    def bootstrap():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/v1/bootstrap", json.dumps({"code": code}),
                     {"Host": host, "Origin": "http://" + host, "Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body.get("token")

    facts["bootstrap"], token = bootstrap()
    facts["reuse"], _none = bootstrap()                    # the code is single-use
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/v1/stream", headers={"Host": host, "Authorization": "Bearer " + token})
    response = conn.getresponse()
    facts["stream"] = [response.status, json.loads(response.readline()).get("t")]
    conn.close()
    save("secret.json", {"code": code, "token": token})
    save("fake.json", facts)
    for step in STEPS:
        emit({"t": "png", "name": step, "width": 1470, "height": 830,
              "png": base64.b64encode(png(1470, 830)).decode("ascii")})
    sys.stderr.write("some framework noise " + "x" * 40 + "\n")
    emit({"t": "report", "code": "ok", "onscreen_windows": 0, "onscreen_samples": 3, "page_errors": 0,
          "error_collection": "verified", "evil": "x", "viewport": [1470, 830], "scale": 1,
          "steps": [{"name": step, "ok": True, "ms": 1} for step in STEPS],
          "checks": {"market_runners": 8, "note": "has a space", "path": "/x/y"}})
elif MODE == "onscreen":
    save("fake.json", facts)
    emit({"t": "png", "name": "initial", "width": 1470, "height": 830,
          "png": base64.b64encode(png(1470, 830)).decode("ascii")})
    emit({"t": "report", "code": "window_onscreen", "onscreen_windows": 1})
    sys.exit(16)
elif MODE == "garbage":
    save("fake.json", facts)
    print("not a record")
elif MODE == "hang":
    save("fake.json", facts)
    time.sleep(300)
'''

COMMAND = PRELUDE + """
import os, sys
from betangel_suite import errors, guard
guard.arm("uisnap")
errors.install_excepthooks()
os.umask(0o077)
from betangel_suite import roots, uisnap
roots.ensure_dir(os.environ["TMPDIR"])
try:
    status = uisnap.main({"seed": 5, "out": %r}, binary=%r, timeout_s=%d, grace_s=%d)
except errors.SuiteError as exc:
    sys.stderr.write(errors.describe(exc) + "\\n")
    status = 2
sys.exit(status)
"""


class CommandTests(unittest.TestCase):
    """uisnap.main in a uisnap-mode child: the real engine in process, a stub binary in the build layout."""

    def run_command(self, mode, *, out=None, timeout_s=30, grace_s=5):
        """(home, CompletedProcess); out is None or a function of the new HOME giving the --out path."""
        home = short_home(self)
        out = None if out is None else out(home)
        fake = os.path.join(home, "fake_uisnap.py")
        with open(fake, "w") as handle:
            handle.write(FAKE)
        directory = os.path.join(uisnap.build_root(home), hashlib.sha256(mode.encode()).hexdigest())
        binary = place_stub(os.path.join(directory, "uisnap"),
                            "#!/bin/sh\nexec %s -I -S -B %s %s\n" % (PYTHON, fake, mode))
        result = subprocess.run([PYTHON, "-I", "-S", "-B", "-c", COMMAND % (out, binary, timeout_s, grace_s)],
                                env=child_env(home), cwd=home, capture_output=True, text=True, timeout=120)
        self.addCleanup(self.kill_fake, home)
        return home, result

    @staticmethod
    def kill_fake(home):
        path = os.path.join(home, "fake.pid")
        if os.path.exists(path):
            try:
                os.kill(read_json(path), 9)
            except (ProcessLookupError, PermissionError):
                pass

    def assert_engine_gone(self, home):
        from betangel_suite.api import control
        self.assertFalse(os.path.lexists(control_path(home)))
        self.assertFalse(control.engine_running(home))

    def assert_codes_only(self, result, secrets=()):
        for line in result.stdout.splitlines(keepends=True):
            self.assertRegex(line, STDOUT_LINE)
        self.assertEqual(secret_shaped(result.stdout + result.stderr), [])
        self.assertEqual(secrets_in(result.stdout + result.stderr, secrets), 0)

    def test_a_run_writes_the_pngs_and_a_sanitised_report(self):
        home, result = self.run_command("ok")
        # stderr: only the server's own code-only log line for the stub's deliberate reuse of the code
        self.assertEqual((result.returncode, result.stderr), (0, "http:401:bad_code\n"), result.stderr[-2000:])
        facts = read_json(os.path.join(home, "fake.json"))
        secret = read_json(os.path.join(home, "secret.json"))
        self.assertEqual(facts["keys"], ["seed", "timeout_s", "url"])
        self.assertEqual((facts["stdin_lines"], facts["url_ok"], facts["seed"]), (1, True, 5))
        self.assertTrue(facts["env_ok"])
        self.assertEqual(facts["env_extra"], [])
        self.assertEqual((facts["bootstrap"], facts["reuse"]), (200, 401))
        self.assertEqual(facts["stream"], [200, "hb"])
        self.assert_codes_only(result, (secret["code"], secret["token"]))
        lines_out = result.stdout.splitlines()
        self.assertRegex(lines_out[0], r"^uisnap ok seed=5 build=given pngs=6 page_errors=0 ")
        paths = [line.split(" ", 2)[2] for line in lines_out[1:7]]
        self.assertEqual([line.split(" ")[1] for line in lines_out[1:7]], list(uisnap.STEPS))
        out_dir = os.path.dirname(paths[0])
        self.assertTrue(out_dir.startswith(uisnap.out_root(home) + os.sep))
        self.assertEqual(lines_out[7], "report " + os.path.join(out_dir, "report.json"))
        self.assertEqual(sorted(os.listdir(out_dir)), sorted([step + ".png" for step in uisnap.STEPS] + ["report.json"]))
        for name in os.listdir(out_dir):
            info = os.lstat(os.path.join(out_dir, name))
            self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode)), (True, 0o600), name)
        with open(paths[0], "rb") as handle:
            self.assertEqual(uisnap.png_size(handle.read()), (1470, 830))
        report = read_json(os.path.join(out_dir, "report.json"))
        self.assertNotIn("evil", report)
        self.assertEqual(report["checks"], {"market_runners": 8})
        self.assertEqual((report["code"], report["pngs"], report["seed"], report["child_exit"]), ("ok", 6, 5, 0))
        self.assertEqual(report["child_stderr_lines"], 1)
        with open(os.path.join(out_dir, "report.json")) as handle:
            self.assertEqual(secrets_in(handle.read(), (secret["code"], secret["token"])), 0)
        self.assert_engine_gone(home)

    def test_a_window_on_screen_fails_with_its_code(self):
        home, result = self.run_command("onscreen")
        self.assertEqual((result.returncode, result.stderr), (2, "refused:uisnap_window_onscreen\n"))
        self.assert_codes_only(result)
        self.assertRegex(result.stdout, r"^uisnap failed code=uisnap_window_onscreen seed=5 build=given pngs=1 ")
        self.assertIn("\npng initial ", result.stdout)
        self.assert_engine_gone(home)

    def test_stray_output_fails(self):
        home, result = self.run_command("garbage")
        self.assertEqual((result.returncode, result.stderr), (2, "refused:uisnap_bad_output\n"))
        self.assert_codes_only(result)
        self.assertFalse(os.path.lexists(uisnap.out_root(home)))          # nothing to write: no directory
        self.assert_engine_gone(home)

    def test_a_hanging_binary_is_killed_at_the_deadline(self):
        home, result = self.run_command("hang", timeout_s=1, grace_s=0)
        self.assertEqual((result.returncode, result.stderr), (2, "refused:uisnap_timeout\n"))
        self.assert_codes_only(result)
        with self.assertRaises(ProcessLookupError):
            os.kill(read_json(os.path.join(home, "fake.pid")), 0)
        self.assert_engine_gone(home)

    def test_an_explicit_empty_output_directory(self):
        def shots(home):
            path = os.path.join(roots.state_dir(home), "shots")
            os.makedirs(path, mode=0o700)
            return path

        home, result = self.run_command("ok", out=shots)
        self.assertEqual((result.returncode, result.stderr), (0, "http:401:bad_code\n"), result.stderr[-2000:])
        out_dir = os.path.join(roots.state_dir(home), "shots")
        self.assertIn("\nreport %s\n" % os.path.join(out_dir, "report.json"), result.stdout)
        self.assertEqual(len(os.listdir(out_dir)), len(uisnap.STEPS) + 1)
        self.assertFalse(os.path.lexists(uisnap.out_root(home)))
        self.assert_engine_gone(home)


class LauncherRefusalTests(unittest.TestCase):
    """bin/suite uisnap refuses before building or starting anything."""

    def suite(self, home, *args):
        result = run_suite(["uisnap", *args], home)
        return result.returncode, result.stdout, result.stderr

    def assert_nothing_made(self, home):
        self.assertFalse(os.path.lexists(os.path.join(roots.state_dir(home), "uisnap")))
        self.assertFalse(os.path.lexists(roots.data_home(home)))

    def test_any_configured_data_root_is_refused(self):
        home = make_home(self, deps=True)
        path = roots.config_path(home)
        with open(path, "w") as handle:
            json.dump({"data_roots": ["~/betangel-data/historic-pro"]}, handle)
        os.chmod(path, 0o600)
        self.assertEqual(self.suite(home), (2, "", "refused:synthetic_only\n"))
        self.assert_nothing_made(home)

    def test_a_running_engine_is_refused(self):
        home = make_home(self, deps=True)
        os.makedirs(roots.run_dir(home), mode=0o700)
        fd = os.open(os.path.join(roots.run_dir(home), "engine.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.suite(home), (2, "", "refused:engine_running\n"))
        self.assert_nothing_made(home)

    def test_bad_arguments_and_outputs(self):
        home = make_home(self, deps=True)
        for args, code in ((["--seed", "x"], "bad_arguments"), (["--seed"], "bad_arguments"),
                           (["--out", "relative"], "bad_arguments"), (["--print-url"], "bad_arguments"),
                           (["--seed", "1", "--seed", "2"], "bad_arguments"),
                           (["--out", os.path.join(home, "elsewhere")], "write_outside_roots"),
                           (["--out", os.path.join(ROOT, "docs", "synthetic")], "write_outside_roots"),
                           (["--out", os.path.join(roots.data_home(home), "x")], "state_root_not_agreed")):
            self.assertEqual(self.suite(home, *args), (2, "", "refused:%s\n" % code), args)
        self.assert_nothing_made(home)


# --- heavy, opt-in: the real build and a real offscreen WKWebView ------------------------------------

# uisnap.main in a uisnap-mode child with the built binary and another UI (the engine's ui_dir seam): a page whose
# only script navigates away at once, to a loopback URL the binary must refuse (and that stays harmless if not).
PROBE = PRELUDE + """
import os, sys
from betangel_suite import errors, guard
guard.arm("uisnap")
errors.install_excepthooks()
os.umask(0o077)
from betangel_suite import roots, uisnap
roots.ensure_dir(os.environ["TMPDIR"])
try:
    status = uisnap.main({"seed": 1, "out": None}, binary=%r, ui_dir=%r, timeout_s=60, grace_s=10)
except errors.SuiteError as exc:
    sys.stderr.write(errors.describe(exc) + "\\n")
    status = 2
sys.exit(status)
"""
NAVIGATIONS = {
    "localhost": 'location.replace("http://localhost:" + location.port + "/");\n',
    "other_port": 'location.replace("http://127.0.0.1:" + (Number(location.port) === 65535 ? 65534 : '
                  'Number(location.port) + 1) + "/");\n',
}


def probe_ui(directory, script):
    """A UI directory for static.load: index.html loading nav.js, which navigates away."""
    os.makedirs(directory, mode=0o700)
    files = {"index.html": '<!doctype html>\n<html><head><meta charset="utf-8"><title>betangel-suite</title>'
                           '<script src="nav.js"></script></head><body></body></html>\n',
             "nav.js": script,
             "manifest.json": json.dumps({"files": [{"path": "index.html", "type": "text/html; charset=utf-8"},
                                                    {"path": "nav.js", "type": "text/javascript; charset=utf-8"}]})}
    for name, text in files.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    return directory


@unittest.skipUnless(HEAVY, HEAVY_ONLY + " (swiftc and WebKit)")
class RealRunTests(unittest.TestCase):

    def check_run(self, result, home, build):
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout + result.stderr[-2000:])
        for line in result.stdout.splitlines(keepends=True):
            self.assertRegex(line, STDOUT_LINE)
        self.assertEqual(secret_shaped(result.stdout), [])
        first = result.stdout.splitlines()[0]
        self.assertRegex(first, r"^uisnap ok seed=[0-9]+ build=%s pngs=6 page_errors=0 " % build)
        paths = dict(line.split(" ", 2)[1:] for line in result.stdout.splitlines()[1:7])
        self.assertEqual(list(paths), list(uisnap.STEPS))
        for path in paths.values():
            with open(path, "rb") as handle:
                self.assertTrue(uisnap.viewport_size_ok(*uisnap.png_size(handle.read())), path)
        report = read_json(os.path.join(os.path.dirname(paths["initial"]), "report.json"))
        checks = report["checks"]
        self.assertEqual((report["code"], report["onscreen_windows"], report["error_collection"]), ("ok", 0, "verified"))
        self.assertGreater(report["onscreen_samples"], 10)
        self.assertEqual((report["page_errors"], report["rejections"], report["csp_violations"]), (0, 0, 0))
        self.assertEqual(report["viewport"], list(uisnap.VIEWPORT))
        self.assertEqual(checks["initial_visibility"], "visible")
        self.assertTrue(all(value for key, value in checks.items() if key.endswith("_raf")), checks)
        for key in ("initial_title_static", "initial_badge_synthetic", "market_status_open", "market_badge_synthetic",
                    "ladder_speed_10x", "inplay_inplay_badge", "inplay_countdown_inplay", "closed_status_closed"):
            self.assertIs(checks[key], True, key)
        self.assertEqual(checks["market_runners"], 8)
        self.assertGreaterEqual(checks["ladder_ladder_colours"], 8)        # a drawn ladder, not a blank canvas
        with open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8") as handle:     # one item per KEYMAP entry
            self.assertEqual(checks["help_help_items"], handle.read().count("Object.freeze({ key:"))
        self.assertFalse(os.path.lexists(control_path(home)))
        return report

    def test_build_and_snapshot_twice(self):
        home = short_home(self)
        first = run_suite(["uisnap", "--seed", "1"], home, timeout=1500)
        self.check_run(first, home, "built")
        directory = [name for name in os.listdir(uisnap.build_root(home)) if re.fullmatch(r"[0-9a-f]{64}", name)]
        self.assertEqual(len(directory), 1)
        record = read_json(os.path.join(uisnap.build_root(home), directory[0], "build.json"))
        with open(SWIFT, "rb") as handle:
            self.assertEqual(record["source_sha256"], hashlib.sha256(handle.read()).hexdigest())
        self.assertEqual(record["argv"], guard.uisnap_build_argv(os.path.join(uisnap.build_root(home), directory[0])))
        out = os.path.join(roots.state_dir(home), "second")
        second = run_suite(["uisnap", "--seed", "7", "--out", out], home, timeout=900)
        self.check_run(second, home, "cached")
        self.assertEqual(sorted(os.listdir(out)), sorted([step + ".png" for step in uisnap.STEPS] + ["report.json"]))

        # The navigation delegate itself: a page that navigates to another loopback origin ends the run.
        binary = os.path.join(uisnap.build_root(home), directory[0], "uisnap")
        for name, script in NAVIGATIONS.items():
            with self.subTest(navigation=name):
                ui = probe_ui(os.path.join(home, "probe-" + name), script)
                result = subprocess.run([PYTHON, "-I", "-S", "-B", "-c", PROBE % (binary, ui)], env=child_env(home),
                                        cwd=home, capture_output=True, text=True, timeout=300)
                self.assertEqual((result.returncode, result.stderr), (2, "refused:uisnap_navigation_refused\n"),
                                 result.stdout + result.stderr[-2000:])
                for line in result.stdout.splitlines(keepends=True):
                    self.assertRegex(line, STDOUT_LINE)
                self.assertRegex(result.stdout, r"\Auisnap failed code=uisnap_navigation_refused seed=1 build=given "
                                                r"pngs=0 ")
                report = read_json(result.stdout.splitlines()[-1].split(" ", 1)[1])
                self.assertEqual((report["code"], report["child_exit"]), ("navigation_refused", 11))
                self.assertGreaterEqual(report["navigations_refused"], 1)
                self.assertFalse(os.path.lexists(control_path(home)))


if __name__ == "__main__":
    unittest.main()
