"""I-1: no credential code path (DESIGN.md 4.1, section 10).

Only betangel_suite/rx.py imports betangel_research, only the allowlisted modules and names; a fresh
engine process loads exactly the 25-module closure and none of the credential, order or network modules;
the suite's own sources hold no credential-store, security-CLI, exchange-host or order-method strings; and the
pinned closure holds no order-method literals. The searched-for strings are built by concatenation so
that this file does not contain them.
"""

import ast
import json
import os
import unittest

from betangel_suite import pin
from tests import ARM_ENGINE, DEPS, ROOT, make_home, run_python


def _j(*parts):
    return "".join(parts)


EXPECTED_CLOSURE = frozenset({
    "betangel_research", "betangel_research.stream", "betangel_research.temporal",
    "betangel_research.evaluation", "betangel_research.betfair",
    "betangel_research.betfair.book", "betangel_research.betfair.config", "betangel_research.betfair.constants",
    "betangel_research.betfair.errors", "betangel_research.betfair.filters", "betangel_research.betfair.journal",
    "betangel_research.betfair.lifecycle", "betangel_research.betfair.paper", "betangel_research.betfair.paths",
    "betangel_research.betfair.pnl", "betangel_research.betfair.receipts", "betangel_research.betfair.schemas",
    "betangel_research.betfair.secret", "betangel_research.betfair.ticks", "betangel_research.betfair.validate",
    "betangel_research.betfair.backtest", "betangel_research.betfair.backtest.archive",
    "betangel_research.betfair.backtest.contract", "betangel_research.betfair.backtest.market_index",
    "betangel_research.betfair.backtest.path_guard",
})
FORBIDDEN_MODULES = ("gateway", "cli", "auth", "credentials", "transport", "api", "esa", "recorder", "killswitch",
                     "arming", "presence", "reconcile", "risk", "capability")
NETWORK_MODULES = ("socket", "_socket", "ssl", "_ssl", "http", "http.client", "urllib.request", "ctypes", "_ctypes")
# On python3.11 the standard library's own pathlib imports urllib.parse (string helpers, no network code);
# 3.13 does not. Nothing else from urllib may load.
URLLIB_ALLOWED = {"urllib", "urllib.parse"}

# DESIGN.md section 4.1 (interfaces as used) plus the exception classes of section 9.2 item 9, typed here
# independently of rx.ALLOWLIST so that widening the facade needs a reviewed change to this test too.
SECTION_4_1 = {
    "ticks": {"LADDER_CLASSIC", "parse_money", "parse_price", "to_hundredths", "to_pence", "is_on_ladder",
              "tick_index", "tick_offset", "ticks_between", "snap"},
    "constants": {"MIN_BET_PENCE_GBP", "CLASSIC_BANDS", "MARKET_STATUSES", "COMMISSION_SOURCES", "ABSOLUTE_CEILINGS"},
    "book": {"MarketBookCache", "replay_market_time"},
    "schemas": {"BOOK_SNAPSHOT_KEYS", "RUNNER_KEYS", "SNAPSHOT_KEY_TYPES", "INSTRUCTION_V1_KEYS", "ORDER_STATES",
                "UNRESOLVED_STATES", "validate_book_snapshot", "validate_instruction_v1"},
    "validate": {"validate_place", "validate_cancel", "make_customer_ref", "make_customer_order_ref",
                 "profit_ratio_ok"},
    "paper": {"PaperExchange", "PAPER_MODEL", "PAPER_ASSUMPTIONS", "PARAM_KEYS", "REPLAY_STATUS", "book_time_ms",
              "paper_bet_id"},
    "lifecycle": {"TRANSITIONS", "PAPER_REFUSAL_CODES", "PAPER_FAILED_CODES", "transition", "classify_place_report",
                  "classify_cancel_report"},
    "journal": {"OrderJournal", "JournalFolder", "KINDS", "INTENT_PAYLOAD_KEYS", "INTENT_SOURCES",
                "CLOCK_REGRESSION_NS"},
    "pnl": {"order_pnl_pence", "market_realized", "EXCLUDING_RESULTS"},
    "evaluation": {"settled_market_costs"},
    "config": {"DEFAULTS", "validate_config"},
    "paths": {"FORBID_NETWORK_ENV", "network_forbidden", "overrides_allowed", "StatePaths"},
    "receipts": {"utc_from_ns", "parse_utc_ns", "canonical_sha256", "file_sha256", "atomic_write_json",
                 "append_jsonl", "strict_json_loads"},     # no SystemClock: nothing uses it (Nuance, Q-N1)
    "secret": {"register", "assert_clean", "refuse_forbidden"},
    "betfair_errors": {"JournalError"},
    "archive": {"CHUNK_BYTES", "LIMIT_CEILINGS", "Limits", "DEFAULT_LIMITS", "market_month", "month_gate",
                "parse_member_path", "check_data_root", "HashingReader", "safe_path", "safe_target", "ArchiveProblem"},
    "market_index": {"HEAD_FILE", "MARKETS_FILE", "loads_strict", "market_sort_key", "load_manifest", "archive_shas",
                     "IndexProblem"},
    "path_guard": {"guard_path", "PathDenied", "denied_sequence"},
    "contract": {"SEALED_HOLDOUT", "INSPECTED_MONTHS", "EXPOSED_MONTHS", "NOT_PROSPECTIVE_DATES"},
}
# rx's import alias -> SECTION_4_1 key
RX_IMPORTS = {
    ("betangel_research", "evaluation"): "evaluation",
    ("betangel_research.betfair", "book"): "book", ("betangel_research.betfair", "config"): "config",
    ("betangel_research.betfair", "constants"): "constants", ("betangel_research.betfair", "errors"): "betfair_errors",
    ("betangel_research.betfair", "journal"): "journal", ("betangel_research.betfair", "lifecycle"): "lifecycle",
    ("betangel_research.betfair", "paper"): "paper", ("betangel_research.betfair", "paths"): "paths",
    ("betangel_research.betfair", "pnl"): "pnl", ("betangel_research.betfair", "receipts"): "receipts",
    ("betangel_research.betfair", "schemas"): "schemas", ("betangel_research.betfair", "secret"): "secret",
    ("betangel_research.betfair", "ticks"): "ticks", ("betangel_research.betfair", "validate"): "validate",
    ("betangel_research.betfair.backtest", "archive"): "archive",
    ("betangel_research.betfair.backtest", "contract"): "contract",
    ("betangel_research.betfair.backtest", "market_index"): "market_index",
    ("betangel_research.betfair.backtest", "path_guard"): "path_guard",
}
# Names rx must never export. risk's two stay listed although risk is no longer a test oracle (Q-N1).
TEST_ONLY_NAMES = ("run_paper_replay", "ORDER_FILE_KEYS", "snapshots_from_recording", "_messages", "ingest_archive",
                   "index_archive", "worst_case_market_loss", "exposure_by_market")
ORDER_METHODS = (_j("place", "Orders"), _j("cancel", "Orders"), _j("replace", "Orders"), _j("update", "Orders"),
                 _j("Heartbeat", "APING"))
FORBIDDEN_TEXT = ORDER_METHODS + (_j("key", "chain"), _j("betfair", ".com"), _j("/usr/bin/", "secur", "ity"),
                                  _j("find-", "generic-", "password"), _j("add-", "generic-", "password"),
                                  _j("find-", "internet-", "password"))


def module_and_package(relpath):
    """(module name, package its relative imports start from) of a pinned .py path."""
    if relpath.endswith("/__init__.py"):
        name = relpath[:-len("/__init__.py")].replace("/", ".")
        return name, name
    name = relpath[:-len(".py")].replace("/", ".")
    return name, name.rpartition(".")[0]


def upstream_imports(tree, package, is_module):
    """(line, module) for every betangel_research module a parsed source imports, anywhere in it (inside functions
    too); "<dynamic>" for an import_module or __import__ call whose module is not a literal absolute name.

    `import a.b.c` imports a, a.b and a.b.c. `from <base> import name` imports base, and base.name too when
    is_module(base.name) says that is a module (a file or package directory in the pinned tree), not an attribute.
    Relative imports are resolved against package.
    """
    found = []

    def add(name, line):
        parts = name.split(".")
        found.extend((line, ".".join(parts[:end])) for end in range(1, len(parts) + 1))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                parts = parts[:len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            else:
                base = node.module
            add(base, node.lineno)
            for alias in node.names:
                if alias.name != "*" and is_module(base + "." + alias.name):
                    add(base + "." + alias.name, node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called in ("import_module", "__import__"):
                literal = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                if isinstance(literal, str) and literal and not literal.startswith("."):
                    add(literal, node.lineno)
                else:
                    found.append((node.lineno, "<dynamic>"))
    return [(line, name) for line, name in found
            if name == "<dynamic>" or name == "betangel_research" or name.startswith("betangel_research.")]


def deps_module(name):
    """True when name is a module of the real deps clone: a .py file or a package directory (read only)."""
    path = os.path.join(DEPS, *name.split("."))
    return os.path.isfile(path + ".py") or os.path.isdir(path)


def python_sources():
    """Every Python file of the suite outside tests/: the package, the launcher and the tools."""
    found = []
    for folder in ("betangel_suite", "bin", "tools"):
        for directory, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            found += [os.path.join(directory, name) for name in files if name.endswith(".py")]
    return sorted(found)


def scanned_sources():
    """The sources the engine runs or that touch upstream: the package, bin/ and the vendor tool.

    tools/hygiene_scan.py is not scanned here: it names credential-store file extensions to block them.
    """
    found = [path for path in python_sources() if not path.startswith(os.path.join(ROOT, "tools"))]
    return found + [os.path.join(ROOT, "bin", "suite"), os.path.join(ROOT, "tools", "vendor_research.py")]


def relative(path):
    return os.path.relpath(path, ROOT)


def parse(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), path)


class SoleImporterTests(unittest.TestCase):

    def test_only_rx_imports_betangel_research(self):
        importers = set()
        for path in python_sources():
            for node in ast.walk(parse(path)):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                    func = node.func
                    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                    if called in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                        names = [node.args[0].value]
                if any(name == "betangel_research" or name.startswith("betangel_research.") for name in names):
                    importers.add(relative(path))
        self.assertEqual(importers, {os.path.join("betangel_suite", "rx.py")})

    def test_rx_imports_only_allowlisted_modules_as_private_aliases(self):
        seen = {}
        for node in ast.walk(parse(os.path.join(ROOT, "betangel_suite", "rx.py"))):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name.startswith("betangel_research") for alias in node.names))
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("betangel_research"):
                for alias in node.names:
                    self.assertTrue(alias.asname and alias.asname.startswith("_"), alias.name)
                    seen[(node.module, alias.name)] = alias.asname
        self.assertEqual(set(seen), set(RX_IMPORTS))

    def test_rx_allowlist_equals_section_4_1(self):
        tree = parse(os.path.join(ROOT, "betangel_suite", "rx.py"))
        assigned = [node.value for node in tree.body if isinstance(node, ast.Assign)
                    and [getattr(t, "id", None) for t in node.targets] == ["ALLOWLIST"]]
        self.assertEqual(len(assigned), 1)
        allowlist = ast.literal_eval(assigned[0])
        self.assertEqual({key: set(names) for key, names in allowlist.items()}, SECTION_4_1)

    def test_rx_reads_only_allowlisted_attributes_of_upstream_modules(self):
        tree = parse(os.path.join(ROOT, "betangel_suite", "rx.py"))
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("betangel_research"):
                for alias in node.names:
                    aliases[alias.asname] = RX_IMPORTS[(node.module, alias.name)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                self.assertIn(node.attr, SECTION_4_1[aliases[node.value.id]], node.value.id)

    def test_rx_namespaces_hold_exactly_the_allowlisted_names(self):
        from betangel_suite import rx
        for key, names in SECTION_4_1.items():
            self.assertEqual(set(vars(getattr(rx, key))), names, key)
        exported = {name for key in SECTION_4_1 for name in vars(getattr(rx, key))}
        for name in TEST_ONLY_NAMES:
            self.assertNotIn(name, exported)


class ReferenceMakerTests(unittest.TestCase):
    """DESIGN.md 4.1: refs come from a deterministic rng; upstream would default to secrets.token_hex."""

    def test_upstream_signatures_at_the_pin(self):
        import inspect
        from betangel_research.betfair import validate as upstream      # test-only: the module rx already loaded
        for name in ("make_customer_ref", "make_customer_order_ref"):
            parameters = inspect.signature(getattr(upstream, name)).parameters
            self.assertEqual(list(parameters), ["now_ns", "rng"], name)
            self.assertIsNone(parameters["rng"].default, name)          # why rx wraps them

    def test_rx_requires_the_rng(self):
        from betangel_suite import rx
        from betangel_suite.errors import SuiteError
        now_ns = 1_431_000_000 * 1_000_000_000

        def rng(nbytes):
            return "0123456789abcdef"[:nbytes * 2]

        for name, prefix in (("make_customer_ref", "brq"), ("make_customer_order_ref", "bro")):
            make = getattr(rx.validate, name)
            self.assertEqual(make(now_ns, rng), make(now_ns, rng))
            self.assertTrue(make(now_ns, rng).startswith(prefix) and make(now_ns, rng).endswith("-0123456789abcdef"))
            with self.assertRaises(SuiteError) as caught:
                make(now_ns, None)
            self.assertEqual(caught.exception.code, "rng_required")
            with self.assertRaises(TypeError):
                make(now_ns)

    def test_a_falsy_rng_is_still_the_rng(self):
        # Nuance's PR #2 review, item 9: upstream takes `rng or secrets.token_hex`, so an rng whose truth value is
        # False (here a tape that has run out, by its __len__) gave random refs. The tape must be used, and only once
        # per ref: rx draws nothing from it beforehand.
        from betangel_suite import rx
        now_ns = 1_431_000_000 * 1_000_000_000

        class Tape:
            def __init__(self, tokens):
                self.tokens, self.draws = list(tokens), []

            def __len__(self):
                return 0                                  # falsy, but callable

            def __call__(self, nbytes):
                self.draws.append(nbytes)
                return self.tokens.pop(0)

        for name in ("make_customer_ref", "make_customer_order_ref"):
            tape = Tape(["00000000000000a1", "00000000000000b2"])
            self.assertFalse(tape)
            make = getattr(rx.validate, name)
            self.assertTrue(make(now_ns, tape).endswith("-00000000000000a1"), name)
            self.assertTrue(make(now_ns, tape).endswith("-00000000000000b2"), name)
            self.assertEqual(tape.draws, [8, 8], name)


class ClosureTests(unittest.TestCase):

    def test_closure_list_matches_pinned_files(self):
        modules = set()
        for relpath in pin.PINNED_FILES:
            if relpath.endswith("/__init__.py"):
                modules.add(relpath[:-len("/__init__.py")].replace("/", "."))
            elif relpath.endswith(".py"):
                modules.add(relpath[:-3].replace("/", "."))
        self.assertEqual(modules, EXPECTED_CLOSURE)
        self.assertEqual(len(EXPECTED_CLOSURE), 25)

    def test_pinned_files_import_only_the_closure(self):
        # Nuance's PR #2 review, item 7: the deps clone is on sys.path, so a pinned module that imported anything
        # outside the closure (a lazy import in a function, say) would load unhashed code. Every import statement and
        # literal import call in the 25 pinned modules must name closure modules only, and none may be dynamic.
        problems = []
        for relpath in pin.PINNED_FILES:
            if relpath.endswith(".py"):
                _name, package = module_and_package(relpath)
                for line, name in upstream_imports(parse(os.path.join(DEPS, relpath)), package, deps_module):
                    if name not in EXPECTED_CLOSURE:
                        problems.append((relpath, line, name))
        self.assertEqual(problems, [])

    def test_the_closure_import_rule_catches_planted_imports(self):
        def is_module(name):
            return name.rsplit(".", 1)[-1] in ("risk", "gateway", "paper", "book", "archive")

        package = "betangel_research.betfair"
        for source, expected in (
                ("import betangel_research.betfair.risk\n", ["betangel_research.betfair.risk"]),
                ("from betangel_research.betfair import risk\n", ["betangel_research.betfair.risk"]),
                ("from .risk import exposure_by_market\n", ["betangel_research.betfair.risk"]),
                ("from . import risk, paper\n", ["betangel_research.betfair.risk"]),
                ("def later():\n    import betangel_research.betfair.gateway as g\n", ["betangel_research.betfair.gateway"]),
                ("import importlib\nm = importlib.import_module('betangel_research.betfair.risk')\n",
                 ["betangel_research.betfair.risk"]),
                ("m = __import__(name)\n", ["<dynamic>"]),
                ("import importlib\nm = importlib.import_module('.risk', 'betangel_research.betfair')\n", ["<dynamic>"]),
                ("from betangel_research.betfair import paper, book\nfrom .book import MarketBookCache\n", []),
                ("from ..betfair.backtest import archive\nimport json\n", []),
                ("from betangel_research.betfair.ticks import snap, LADDER_CLASSIC\n", [])):
            names = [name for _line, name in upstream_imports(ast.parse(source), package, is_module)]
            self.assertEqual(sorted(set(names) - EXPECTED_CLOSURE), expected, source)

    def test_fresh_engine_loads_exactly_the_closure(self):
        home = make_home(self, deps=True)
        code = ARM_ENGINE + (
            "import json\n"
            "from betangel_suite import rx\n"
            "after_rx = sorted(m for m in sys.modules if m.startswith('betangel_research'))\n"
            "network = [m for m in %r if m in sys.modules]\n"
            "urllib = sorted(m for m in sys.modules if m == 'urllib' or m.startswith('urllib.'))\n"
            "from betangel_suite import cli, config, errors, guard, pin, roots, runmarker\n"
            "after_all = sorted(m for m in sys.modules if m.startswith('betangel_research'))\n"
            "print(json.dumps({'after_rx': after_rx, 'after_all': after_all, 'network': network, 'urllib': urllib}))\n"
        ) % (NETWORK_MODULES,)
        result = run_python(code, home)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(set(report["after_rx"]), EXPECTED_CLOSURE)
        self.assertEqual(report["after_all"], report["after_rx"])
        self.assertEqual(report["network"], [])
        self.assertLessEqual(set(report["urllib"]), URLLIB_ALLOWED)
        for name in report["after_all"]:
            self.assertNotIn(name.rsplit(".", 1)[-1], FORBIDDEN_MODULES)


class StaticScanTests(unittest.TestCase):

    def test_suite_sources_hold_no_credential_host_or_order_strings(self):
        hits = []
        for path in scanned_sources():
            with open(path, encoding="utf-8") as handle:
                text = handle.read().casefold()
            hits += [(relative(path), index) for index, needle in enumerate(FORBIDDEN_TEXT)
                     if needle.casefold() in text]
        self.assertEqual(hits, [])

    def test_pinned_closure_holds_no_order_method_literals(self):
        hits = []
        for relpath in pin.PINNED_FILES:
            if relpath.endswith(".py"):
                with open(os.path.join(DEPS, relpath), encoding="utf-8") as handle:
                    text = handle.read()
                hits += [(relpath, needle) for needle in ORDER_METHODS if needle in text]
        self.assertEqual(hits, [])

    def test_this_file_builds_its_needles(self):
        with open(__file__, encoding="utf-8") as handle:
            text = handle.read()
        self.assertFalse([needle for needle in FORBIDDEN_TEXT if needle in text])


if __name__ == "__main__":
    unittest.main()
