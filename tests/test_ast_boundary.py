"""I-10 and the rx facade: an AST rule over every Python module of the suite (DESIGN.md 4.1, 4.2, I-10).

tests/test_imports.py proves that only rx.py imports betangel_research, and only allowlisted names. Nuance's
PR #4 review, item 7, found that suite code could still reach ingest_archive and index_archive "through
rx._archive, sys.modules or `__globals__`", and the boundary tests stayed green. This rule parses every module
of the package, bin/ and tools/ (test_imports.python_sources) and refuses:

  test_only_name   a test-only oracle name (test_imports.TEST_ONLY_NAMES), or index_archives, upstream's batch
                   form of index_archive (market_index.py:945; I-10 forbids "index_archive(s)"). Refused as a
                   name, an attribute, an imported name, a keyword or a string outside a docstring, so
                   getattr(x, "ingest_archive") is caught too.
  rx_private       rx used other than as rx.<public name>: rx._archive, rx.__dict__, rx passed as a value,
                   getattr or vars on rx or on anything reached through it, and `from .rx import _archive` or
                   `from .rx import *`.
  globals_escape   __globals__, and the two other doors to a module's globals: f_globals (a frame's) and
                   __builtins__ (which holds __import__). Refused as a name, an attribute or a string.
  sys_modules      sys.modules, and `from sys import modules`. Only a .get() or [] read of a literal module
                   name outside betangel_research is allowed (guard.py looks up socket and _sqlite3 that way),
                   plus the allowlisted functions below.
  computed_import  import_module or __import__ with anything but a literal string first; any import by file
                   or loader (spec_from_file_location, module_from_spec, exec_module, SourceFileLoader, runpy,
                   reload, ...); exec, eval and compile as builtins; and `from ... import` of any of these
                   names, which would hide later calls from this rule.

ALLOWED lists the only exceptions, each with its reason, by (file, enclosing function, rule). An entry that
no longer matches anything fails the test, so the list cannot quietly outlive its reason.

Like the guard (guard.py docstring), this catches mistakes and the paths Nuance listed. It is not proof
against code written to evade it: getattr with a computed name on a local that holds an upstream object is
not refused, because suite code uses computed getattr on its own objects (engine.py, synthetic.py).
"""

import ast
import os
import unittest

from tests import ROOT
from tests.test_imports import TEST_ONLY_NAMES, python_sources, relative

FORBIDDEN_NAMES = frozenset(TEST_ONLY_NAMES) | {"index_archives"}
GLOBALS_NAMES = frozenset({"__globals__", "f_globals", "__builtins__"})
IMPORT_CALLS = frozenset({"import_module", "__import__"})
LOADER_NAMES = frozenset({"spec_from_file_location", "spec_from_loader", "module_from_spec", "exec_module",
                          "load_module", "SourceFileLoader", "SourcelessFileLoader", "ExtensionFileLoader",
                          "run_path", "run_module", "reload"})
CODE_BUILTINS = frozenset({"exec", "eval", "compile"})
REFLECTION = frozenset({"getattr", "setattr", "delattr", "hasattr", "vars", "dir"})
UPSTREAM = "betangel_research"

# (path relative to the checkout, enclosing function, rule) -> why the suite needs it. Nothing else is allowed.
ALLOWED = {
    (os.path.join("betangel_suite", "pin.py"), "activate", "sys_modules"):
        "pin.activate refuses upstream_imported_early: it reads only the names of loaded modules, before rx "
        "imports anything upstream",
    (os.path.join("betangel_suite", "pin.py"), "assert_origins", "sys_modules"):
        "I-13: pin.assert_origins checks that each loaded betangel_research module's __file__ lies in the deps "
        "clone; it returns nothing",
    (os.path.join("betangel_suite", "cli.py"), "_vendor", "computed_import"):
        "bin/suite vendor runs tools/vendor_research.py, a script outside the package, by its fixed path in this "
        "checkout; vendor mode never verifies the pin or imports upstream",
}


def _upstream_name(value):
    return value == UPSTREAM or value.startswith(UPSTREAM + ".")


def _literal_str(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _docstrings(tree):
    """The Constant nodes that are module, class or function docstrings (never code)."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and _literal_str(first.value):
                found.add(first.value)
    return found


class _Checker:
    """Collects (line, function, rule) findings for one parsed module."""

    def __init__(self, tree):
        self.tree = tree
        self.parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.docstrings = _docstrings(tree)
        self.rx_names, self.sys_names, self.rx_packages = set(), set(), set()
        self.findings = []
        self._bindings()

    def _bindings(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                package_import = node.module is None or node.module == "betangel_suite"
                for alias in node.names:
                    if alias.name == "rx" and package_import:
                        self.rx_names.add(alias.asname or "rx")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sys":
                        self.sys_names.add(alias.asname or "sys")
                    elif alias.name == "betangel_suite.rx":
                        if alias.asname:
                            self.rx_names.add(alias.asname)
                        else:
                            self.rx_packages.add("betangel_suite")

    def function_of(self, node):
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return None

    def add(self, node, rule):
        self.findings.append((node.lineno, self.function_of(node), rule))

    def is_rx(self, node):
        """node names the rx module itself."""
        if isinstance(node, ast.Name):
            return node.id in self.rx_names
        return (isinstance(node, ast.Attribute) and node.attr == "rx" and isinstance(node.value, ast.Name)
                and node.value.id in self.rx_packages)

    def reaches_rx(self, node):
        """node is rx, or an attribute, call or subscript chain that starts at rx."""
        while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            if self.is_rx(node):
                return True
            node = node.func if isinstance(node, ast.Call) else node.value
        return self.is_rx(node)

    def run(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                self.import_from(node)
            elif isinstance(node, ast.Name):
                self.name(node)
            elif isinstance(node, ast.Attribute):
                self.attribute(node)
            elif isinstance(node, ast.Call):
                self.call(node)
            elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_NAMES:
                self.add(self.parents[node], "test_only_name")
            elif _literal_str(node) and node not in self.docstrings:
                if node.value in FORBIDDEN_NAMES:
                    self.add(node, "test_only_name")
                if node.value in GLOBALS_NAMES:
                    self.add(node, "globals_escape")
        return self.findings

    def import_from(self, node):
        names = [alias.name for alias in node.names]
        if node.module in ("rx", "betangel_suite.rx") and any(name == "*" or name.startswith("_") for name in names):
            self.add(node, "rx_private")
        if node.module == "sys" and "modules" in names:
            self.add(node, "sys_modules")
        if any(name in FORBIDDEN_NAMES for name in names):
            self.add(node, "test_only_name")
        if any(name in IMPORT_CALLS or name in LOADER_NAMES for name in names):
            self.add(node, "computed_import")

    def name(self, node):
        if node.id in FORBIDDEN_NAMES:
            self.add(node, "test_only_name")
        if node.id in GLOBALS_NAMES:
            self.add(node, "globals_escape")
        if node.id in CODE_BUILTINS or node.id in LOADER_NAMES:
            self.add(node, "computed_import")
        if node.id in IMPORT_CALLS and not self.literal_call(node):
            self.add(node, "computed_import")
        if node.id in self.rx_names and isinstance(node.ctx, ast.Load):
            self.rx_use(node)

    def attribute(self, node):
        if node.attr in FORBIDDEN_NAMES:
            self.add(node, "test_only_name")
        if node.attr in GLOBALS_NAMES:
            self.add(node, "globals_escape")
        if node.attr in LOADER_NAMES:
            self.add(node, "computed_import")
        if node.attr in IMPORT_CALLS and not self.literal_call(node):
            self.add(node, "computed_import")
        if self.is_rx(node):
            self.rx_use(node)
        if node.attr == "modules" and isinstance(node.value, ast.Name) and node.value.id in self.sys_names:
            if not self.literal_module_read(node):
                self.add(node, "sys_modules")

    def call(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id in REFLECTION and node.args and self.reaches_rx(node.args[0]):
            self.add(node, "rx_private")

    def rx_use(self, node):
        """rx may only be the value of a public attribute: rx.ticks, never rx._archive or rx itself."""
        parent = self.parents.get(node)
        if not (isinstance(parent, ast.Attribute) and parent.value is node and not parent.attr.startswith("_")):
            self.add(node, "rx_private")

    def literal_call(self, node):
        """node is called directly with a literal string as its first argument."""
        parent = self.parents.get(node)
        return (isinstance(parent, ast.Call) and parent.func is node and bool(parent.args)
                and _literal_str(parent.args[0]))

    def literal_module_read(self, node):
        """sys.modules.get("<literal>") or sys.modules["<literal>"] (a read), naming no upstream module."""
        parent = self.parents.get(node)
        if isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, ast.Load):
            key = parent.slice
        elif isinstance(parent, ast.Attribute) and parent.attr == "get":
            call = self.parents.get(parent)
            if not (isinstance(call, ast.Call) and call.func is parent and call.args):
                return False
            key = call.args[0]
        else:
            return False
        return _literal_str(key) and not _upstream_name(key.value)


def check_source(text, filename="<planted>"):
    """Sorted (line, enclosing function, rule) findings for one module's source text."""
    return sorted(set(_Checker(ast.parse(text, filename)).run()), key=lambda item: (item[0], item[2]))


def suite_findings():
    """{(path, function, rule): [lines]} over every suite module, before the allowlist is applied."""
    found = {}
    for path in python_sources():
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for line, function, rule in check_source(text, path):
            found.setdefault((relative(path), function, rule), []).append(line)
    return found


class SuiteModuleTests(unittest.TestCase):

    def test_suite_modules_reach_upstream_only_through_public_rx_names(self):
        found = suite_findings()
        refused = {key: lines for key, lines in found.items() if key not in ALLOWED}
        self.assertEqual(refused, {})

    def test_every_allowlist_entry_is_still_needed(self):
        found = suite_findings()
        self.assertEqual([key for key in ALLOWED if key not in found], [])

    def test_the_scan_covers_the_package_bin_and_tools(self):
        scanned = {relative(path) for path in python_sources()}
        for expected in (os.path.join("betangel_suite", "rx.py"), os.path.join("betangel_suite", "engine.py"),
                         os.path.join("betangel_suite", "api", "server.py"), os.path.join("bin", "_launch.py"),
                         os.path.join("tools", "export_ticks.py")):
            self.assertIn(expected, scanned)
        package = [path for path in scanned if path.startswith("betangel_suite" + os.sep)]
        on_disk = [os.path.relpath(os.path.join(directory, name), ROOT)
                   for directory, _dirs, files in os.walk(os.path.join(ROOT, "betangel_suite"))
                   for name in files if name.endswith(".py")]
        self.assertEqual(sorted(package), sorted(on_disk))


class PlantedViolationTests(unittest.TestCase):
    """Each rule on planted source text, so a rule that stops firing fails here, not only on a real slip."""

    REFUSED = {
        "from . import rx\nrx._archive.ingest_archive(a, b)\n": {"rx_private", "test_only_name"},
        "from .. import rx as r\nnamespace = r.__dict__\n": {"rx_private"},
        "from .rx import _archive\n": {"rx_private"},
        "from betangel_suite.rx import *\n": {"rx_private"},
        "from . import rx\nmodule = getattr(rx, 'archive')\n": {"rx_private"},
        "from . import rx\nhelper(rx)\n": {"rx_private"},
        "from . import rx\nfound = getattr(rx.archive.safe_path, name)\n": {"rx_private"},
        "from . import rx\nnames = vars(rx.archive)\n": {"rx_private"},
        "import betangel_suite.rx\nbetangel_suite.rx._paths\n": {"rx_private"},
        "import betangel_suite.rx as facade\nfacade._market_index\n": {"rx_private"},
        "def build(module, root):\n    return module.index_archives(root)\n": {"test_only_name"},
        "oracle = getattr(module, 'run_paper_replay')\n": {"test_only_name"},
        "from x import snapshots_from_recording\n": {"test_only_name"},
        "call(f, index_archive=1)\n": {"test_only_name"},
        "found = function.__globals__['index_archive']\n": {"globals_escape", "test_only_name"},
        "import sys\nnames = sys._getframe(1).f_globals\n": {"globals_escape"},
        "loader = __builtins__['__import__']\n": {"globals_escape"},
        "door = getattr(function, '__globals__')\n": {"globals_escape"},
        "import sys\nmodule = sys.modules['betangel_research.betfair.backtest.archive']\n": {"sys_modules"},
        "import sys\nmodule = sys.modules.get('betangel_research')\n": {"sys_modules"},
        "import sys\nmodule = sys.modules.get(name)\n": {"sys_modules"},
        "import sys as system\ntable = system.modules\n": {"sys_modules"},
        "import sys\nsys.modules['socket'] = fake\n": {"sys_modules"},
        "from sys import modules\n": {"sys_modules"},
        "import importlib\nmodule = importlib.import_module(name)\n": {"computed_import"},
        "module = __import__('betangel' + '_research')\n": {"computed_import"},
        "from importlib import import_module\n": {"computed_import"},
        "load = __import__\n": {"computed_import"},
        "import importlib.util\nspec = importlib.util.spec_from_file_location('x', path)\n": {"computed_import"},
        "import runpy\nrunpy.run_path(path)\n": {"computed_import"},
        "exec(code)\n": {"computed_import"},
        "value = eval(text)\n": {"computed_import"},
    }
    ALLOWED_SOURCE = (
        "from . import rx\nrx.ticks.snap(345, 'down')\nrx.call(rx.book.MarketBookCache, key_type='historical')\n",
        "from .. import rx\nvalue = rx.receipts.parse_utc_ns(text) // 1_000_000\n",
        "import sys\nsockets = sys.modules.get('socket')\nsqlite = sys.modules['_sqlite3']\n",
        "import importlib\nmodule = importlib.import_module('json')\n",
        "import re\npattern = re.compile('x')\n",
        "def handler(self, name):\n    return getattr(self, '_do_' + name, None)\n",
        '"""The engine never calls ingest_archive or index_archive (I-10)."""\n',
        "def f():\n    \"\"\"Not __globals__, not sys.modules.\"\"\"\n    return 1\n",
    )

    def test_each_planted_violation_is_refused(self):
        for text, rules in self.REFUSED.items():
            with self.subTest(text=text):
                self.assertEqual({rule for _line, _function, rule in check_source(text)}, rules)

    def test_ordinary_suite_shapes_pass(self):
        for text in self.ALLOWED_SOURCE:
            with self.subTest(text=text):
                self.assertEqual(check_source(text), [])

    def test_findings_name_the_enclosing_function(self):
        text = "import sys\ndef activate():\n    return [name for name in sys.modules]\n"
        self.assertEqual(check_source(text), [(3, "activate", "sys_modules")])


if __name__ == "__main__":
    unittest.main()
