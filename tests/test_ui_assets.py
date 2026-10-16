"""The browser UI's static files (DESIGN.md 3.4, 8.1, 8.5, 9.1, 9.3 and 11). Synthetic only.

- ui/ticks.json equals a fresh export of rx.ticks.LADDER_CLASSIC by tools/export_ticks.py, checked in
  process and through the tool itself in an engine-mode child;
- ui/manifest.json lists exactly the files in ui/ (ui/tests/ excluded), each with its content type, and
  the server maps static paths from it by exact name (section 9.1);
- every UI file fits the CSP of section 9.3 and the data-handling rules: no external or protocol-relative
  URL, no inline script, style element or style attribute, no inline handler, no eval or Function
  constructor, no data: URL except an image, no storage API or cookie, no other transport than fetch,
  no console output, and a static page title;
- every module import is relative and served by the manifest, and every absolute path the scripts name
  is a route of section 9.1 or a manifest file;
- the page has no credential field (AGENTS.md rule 8) and holds the Phase 0b screen's fixed labels;
- the hygiene scanner finds nothing in the UI files, the export tool or this test.

The JavaScript behaviour itself is tested by node:test under ui/tests/. NodeTests runs that whole suite as part of
bin/suite test (DESIGN.md 3.6, 11): `~/.local/bin/node --test` with every ui/tests/*.test.mjs named explicitly
(node 24 does not take a bare directory), started by an unguarded relay child because the test runner's guard
does not start node. It is skipped when ~/.local/bin/node is missing.
"""

import importlib.util
import json
import os
import re
import subprocess
import unittest

from tests import PYTHON, ROOT, child_env, make_home, run_relayed

UI = os.path.join(ROOT, "ui")
NODE = os.path.join(os.path.expanduser("~"), ".local", "bin", "node")
TOOL = os.path.join(ROOT, "tools", "export_ticks.py")
SCANNER = os.path.join(ROOT, "tools", "hygiene_scan.py")
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
}
ROUTES = frozenset({"/api/v1/bootstrap", "/api/v1/stream", "/api/v1/query", "/api/v1/command"})
NODE_TESTS = ("app", "format", "grid", "keys", "stream", "ticks")
TEXT_SUFFIXES = (".html", ".js", ".mjs", ".css", ".json")
PATH_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*(?:/[a-z0-9][a-z0-9_.-]*)*")

# (code, pattern) for every UI file, the node tests included.
FORBIDDEN = (
    ("external_url", re.compile(r"(?i)\b(?:https?|wss?|ftp)://")),
    ("protocol_relative_url", re.compile(r"[\"'`(=]\s*//[^/\s*]")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("function_constructor", re.compile(r"\bnew\s+Function\b|(?<![.\w])Function\s*\(")),
    ("string_timer", re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]")),
    ("storage", re.compile(r"\b(?:localStorage|sessionStorage|indexedDB|openDatabase|cookieStore|serviceWorker)\b"
                           r"|\.cookie\b|\bcaches\s*\.")),
    ("html_injection", re.compile(r"\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b|\bdocument\.write")),
    ("handler_attribute", re.compile(r"setAttribute\(\s*[\"']on|\.on[a-z]+\s*=\s*[\"'`]|<[A-Za-z][^<>]*\son[a-z]+\s*=")),
    ("style_attribute", re.compile(r"setAttribute\(\s*[\"']style|\.style\b|\bcssText\b|<[A-Za-z][^<>]*\sstyle\s*=")),
    ("style_element", re.compile(r"(?i)<style\b")),
    ("other_transport", re.compile(r"\b(?:WebSocket|EventSource|XMLHttpRequest|sendBeacon)\b")),
    ("console", re.compile(r"\bconsole\s*\.")),
    ("title_write", re.compile(r"\bdocument\s*\.\s*title\b")),
    ("javascript_url", re.compile(r"(?i)javascript:")),
    ("data_url", re.compile(r"(?i)[\"'(=]\s*data:(?!,[\"')]|image/)")),
)
# Only for the served files (the manifest's): every module the page runs is a static, listed import.
# The node tests may import app.js dynamically, after installing a fake DOM.
SERVED_FORBIDDEN = (
    ("dynamic_import", re.compile(r"\bimport\s*\(")),
)


def ui_files(include_tests=False):
    """Paths under ui/, relative with "/" separators; ui/tests/ only when asked."""
    found = []
    for directory, dirs, files in os.walk(UI):
        rel_dir = os.path.relpath(directory, UI)
        if rel_dir == "." and not include_tests:
            dirs[:] = [name for name in dirs if name != "tests"]
        for name in files:
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, "/")
            found.append(rel)
    return sorted(found)


def read_text(rel):
    with open(os.path.join(UI, rel), encoding="utf-8") as handle:
        return handle.read()


def strict_json(text):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def no_constant(name):
        raise ValueError("non-finite number")

    return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constant)


def manifest():
    return strict_json(read_text("manifest.json"))


def manifest_paths():
    return [entry["path"] for entry in manifest()["files"]]


def load_tool():
    spec = importlib.util.spec_from_file_location("betangel_suite_export_ticks", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def without_comments(source):
    """JS source with /* */ and // comments removed (good enough for our own files: no URLs in strings)."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`\\])//.*$", r"\1", source)


class TicksExportTests(unittest.TestCase):

    def test_ticks_json_equals_a_fresh_export(self):
        from betangel_suite import rx
        with open(os.path.join(UI, "ticks.json"), "rb") as handle:
            current = handle.read()
        self.assertEqual(current, load_tool().render(rx.ticks.LADDER_CLASSIC),
                         "ui/ticks.json is stale: re-export it with tools/export_ticks.py")

    def test_ticks_json_holds_the_classic_ladder_as_integers(self):
        from betangel_suite import rx
        doc = strict_json(read_text("ticks.json"))
        self.assertEqual(set(doc), {"schema_version", "ladder", "unit", "source", "count", "ticks"})
        self.assertEqual((doc["schema_version"], doc["ladder"], doc["unit"]), (1, "CLASSIC", "hundredths"))
        self.assertEqual(doc["ticks"], list(rx.ticks.LADDER_CLASSIC))
        self.assertEqual(doc["count"], 350)
        self.assertTrue(all(type(tick) is int and rx.ticks.is_on_ladder(tick) for tick in doc["ticks"]))

    def test_render_refuses_a_ladder_that_is_not_ascending_integers(self):
        tool = load_tool()
        for bad in ([], [101, 101], [102, 101], [101, 1.5], [0, 101], [101, True]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tool.render(bad)

    def test_the_tool_checks_and_prints_the_file_from_an_engine_mode_child(self):
        home = make_home(self, deps=True)
        with open(os.path.join(UI, "ticks.json"), "rb") as handle:
            current = handle.read()
        check = subprocess.run([PYTHON, "-I", "-S", "-B", TOOL, "--check"], env=child_env(home), cwd=home,
                               capture_output=True, timeout=120)
        self.assertEqual(check.returncode, 0, check.stderr[-300:])
        self.assertEqual(check.stderr, b"ticks_json: OK\n")
        self.assertEqual(check.stdout, b"")
        printed = subprocess.run([PYTHON, "-I", "-S", "-B", TOOL], env=child_env(home), cwd=home,
                                 capture_output=True, timeout=120)
        self.assertEqual(printed.returncode, 0, printed.stderr[-300:])
        self.assertEqual(printed.stdout, current)
        self.assertEqual(printed.stderr, b"")

    def test_the_tool_refuses_bad_arguments(self):
        home = make_home(self, deps=True)
        bad = subprocess.run([PYTHON, "-I", "-S", "-B", TOOL, "--write"], env=child_env(home), cwd=home,
                             capture_output=True, timeout=60)
        self.assertEqual((bad.returncode, bad.stdout, bad.stderr), (2, b"", b"refused:bad_arguments\n"))

    def test_the_tool_runs_only_under_the_armed_guard(self):
        home = make_home(self, deps=True)
        env = child_env(home, BETANGEL_BETFAIR_FORBID_NETWORK=None)
        self.assertEqual(run_relayed([PYTHON, "-I", "-S", "-B", TOOL], env, home),
                         (2, "", "refused:network_not_forbidden\n"))
        # Never without -S (site would run Homebrew's .pth files in the child), as in test_launcher.
        for flags in (("-I", "-S"), ("-S", "-B")):
            self.assertEqual(run_relayed([PYTHON, *flags, TOOL], child_env(home), home),
                             (2, "", "refused:launch_flags\n"), flags)


class ManifestTests(unittest.TestCase):

    def test_manifest_lists_exactly_the_ui_files(self):
        self.assertEqual(sorted(manifest_paths()), ui_files())

    def test_manifest_entries_are_exact(self):
        data = manifest()
        self.assertEqual(set(data), {"files"})
        paths = manifest_paths()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("index.html", paths)
        for entry in data["files"]:
            with self.subTest(entry=entry):
                self.assertEqual(set(entry), {"path", "type"})
                self.assertTrue(PATH_RE.fullmatch(entry["path"]), entry["path"])
                self.assertNotIn("..", entry["path"].split("/"))
                self.assertEqual(entry["type"], TYPES[os.path.splitext(entry["path"])[1]])

    def test_the_node_tests_exist_and_are_not_served(self):
        tests = [rel for rel in ui_files(include_tests=True) if rel.startswith("tests/")]
        for name in NODE_TESTS:
            self.assertIn("tests/" + name + ".test.mjs", tests)
        self.assertTrue(all(rel.endswith(".test.mjs") for rel in tests), tests)
        self.assertFalse(any(path.startswith("tests/") for path in manifest_paths()))


class SourceRuleTests(unittest.TestCase):

    def test_no_ui_file_breaks_the_csp_or_data_handling_rules(self):
        served = set(ui_files())
        for rel in ui_files(include_tests=True):
            self.assertTrue(rel.endswith(TEXT_SUFFIXES), rel)
            text = read_text(rel)
            for code, pattern in FORBIDDEN + (SERVED_FORBIDDEN if rel in served else ()):
                with self.subTest(file=rel, rule=code):
                    self.assertIsNone(pattern.search(text), code)

    def test_the_rules_catch_what_they_are_for(self):
        planted = {
            "external_url": "fetch('https:' + '//example.invalid/x')".replace("' + '", ""),
            "protocol_relative_url": "img.src = '//example.invalid/a.png'",
            "eval": "eval('1')",
            "function_constructor": "new Function('return 1')",
            "string_timer": "setTimeout('go()', 10)",
            "storage": "window.localStorage.setItem('k', 'v')",
            "html_injection": "node.innerHTML = text",
            "handler_attribute": "<button onclick=\"go()\">",
            "style_attribute": "<div style=\"color: red\">",
            "style_element": "<style>p { color: red }</style>",
            "dynamic_import": "import('./x.js')",
            "other_transport": "new EventSource('/api/v1/stream')",
            "console": "console.log(frame)",
            "title_write": "document.title = name",
            "javascript_url": "<a href=\"javascript:go()\">",
            "data_url": "<script src=\"data:text/javascript,go()\"></script>",
        }
        rules = dict(FORBIDDEN + SERVED_FORBIDDEN)
        self.assertEqual(set(planted), set(rules))
        for code, text in planted.items():
            with self.subTest(rule=code):
                self.assertIsNotNone(rules[code].search(text), code)
        self.assertIsNone(rules["data_url"].search('<link rel="icon" href="data:,">'))
        self.assertIsNone(rules["protocol_relative_url"].search("const a = 1; // a comment"))

    def test_module_imports_are_relative_and_served(self):
        served = set(manifest_paths())
        for rel in ui_files():
            if not rel.endswith(".js"):
                continue
            source = without_comments(read_text(rel))
            specifiers = re.findall(r"\b(?:import|export)\b[^'\"`;]*?\bfrom\s*['\"]([^'\"]+)['\"]", source)
            specifiers += re.findall(r"\bimport\s*['\"]([^'\"]+)['\"]", source)
            for specifier in specifiers:
                with self.subTest(file=rel, specifier=specifier):
                    self.assertTrue(specifier.startswith("./"), specifier)
                    target = os.path.normpath(os.path.join(os.path.dirname(rel), specifier)).replace(os.sep, "/")
                    self.assertIn(target, served)

    def test_absolute_paths_in_scripts_are_routes_or_manifest_files(self):
        allowed = ROUTES | {"/" + path for path in manifest_paths()}
        named = set()
        for rel in ui_files():
            if rel.endswith(".js"):
                named |= set(re.findall(r"['\"`](/[^'\"`\s]*)['\"`]", without_comments(read_text(rel))))
        self.assertTrue(named, "the scripts name their routes")
        self.assertLessEqual(named, allowed)
        self.assertLessEqual(ROUTES - {"/api/v1/query"}, named)


class PageTests(unittest.TestCase):

    def setUp(self):
        self.html = read_text("index.html")

    def tags(self, name):
        return re.findall(r"(?is)<%s\b[^>]*>" % name, self.html)

    def test_the_title_is_static(self):
        self.assertEqual(re.findall(r"(?is)<title>(.*?)</title>", self.html), ["betangel-suite"])

    def test_scripts_are_external_modules_from_the_manifest(self):
        scripts = re.findall(r"(?is)<script\b([^>]*)>(.*?)</script>", self.html)
        self.assertEqual(len(scripts), len(self.tags("script")))
        self.assertTrue(scripts)
        served = {"/" + path for path in manifest_paths()}
        for attributes, body in scripts:
            self.assertEqual(body.strip(), "")
            self.assertIn('type="module"', attributes)
            self.assertIn(re.search(r'src="([^"]+)"', attributes).group(1), served)

    def test_every_url_is_a_manifest_file_or_the_empty_icon(self):
        served = {"/" + path for path in manifest_paths()}
        urls = re.findall(r"(?i)\s(?:src|href|action|formaction|poster|srcset)\s*=\s*\"([^\"]*)\"", self.html)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url in served or url == "data:,", url)
        links = self.tags("link")
        self.assertEqual(sorted(re.search(r'rel="([^"]+)"', link).group(1) for link in links), ["icon", "stylesheet"])
        for tag in ("base", "form", "iframe", "object", "embed", "frame", "meta http-equiv"):
            self.assertEqual(self.tags(tag), [], tag)

    def test_there_are_no_credential_fields(self):
        inputs = self.tags("input")
        self.assertEqual(len(inputs), 1)
        for tag in inputs:
            self.assertIn('type="text"', tag)
            self.assertIn('autocomplete="off"', tag)
        lowered = self.html.lower()
        for word in ('type="password"', "current-password", "new-password", 'autocomplete="username"',
                     "one-time-code", "login", "sign in", "log in"):
            self.assertNotIn(word, lowered)

    def test_the_phase_0b_screen_holds_its_fixed_parts(self):
        # The tv halving is unverified (F60; Nuance's PR #4 review, item 3), and the label says so.
        for text in ("SYNTHETIC DATA", "Traded volume: PRO basis", "unverified for this total", "IN-PLAY",
                     "STOP (paper)"):
            self.assertIn(text, self.html)
        speeds = re.findall(r'data-speed="([0-9]+)"', self.html)
        self.assertEqual(speeds, ["100", "200", "500", "1000"])
        for element_id in ("market-name", "market-status", "countdown", "play", "seed", "open", "grid-body", "ladder"):
            self.assertIn('id="%s"' % element_id, self.html)
        self.assertIn('<canvas id="ladder"', self.html)


class NodeTests(unittest.TestCase):

    def test_the_node_suite_passes(self):
        if not (os.path.isfile(NODE) and os.access(NODE, os.X_OK)):
            self.skipTest("~/.local/bin/node is not installed")
        files = [os.path.join(UI, rel) for rel in ui_files(include_tests=True)
                 if rel.startswith("tests/") and rel.endswith(".test.mjs")]
        self.assertEqual(sorted(os.path.basename(path) for path in files), sorted(n + ".test.mjs" for n in NODE_TESTS))
        home = make_home(self)
        argv = [NODE, "--test", "--test-concurrency=1", "--test-reporter=tap", *files]
        status, out, err = run_relayed(argv, child_env(home), home, timeout=120)
        summary = dict(re.findall(r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) ([0-9]+)$", out))
        self.assertEqual(status, 0, (out + err)[-3000:])
        self.assertGreater(int(summary.get("tests", "0")), 0, out[-2000:])
        self.assertEqual(summary.get("pass"), summary["tests"], out[-3000:])
        self.assertEqual([summary.get(key) for key in ("fail", "cancelled", "skipped", "todo")], ["0"] * 4)


class HygieneTests(unittest.TestCase):

    def test_the_scanner_finds_nothing_in_the_ui_files(self):
        targets = ["ui", os.path.join("tools", "export_ticks.py"), os.path.join("tests", "test_ui_assets.py")]
        scan = subprocess.run([PYTHON, "-I", "-S", "-B", SCANNER, "--root", ROOT, *targets], env=dict(os.environ),
                              cwd=ROOT, capture_output=True, timeout=120)
        output = (scan.stdout + scan.stderr).decode("utf-8", "replace")
        self.assertEqual(scan.returncode, 0, output)
        self.assertIn("hygiene_scan: OK", output)


if __name__ == "__main__":
    unittest.main()
