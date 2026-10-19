"""I-2 to I-6: the audit hook (betangel_suite/guard.py; DESIGN.md section 10).

Every check of the hook itself runs in a fresh engine-mode subprocess with a temporary HOME, because an
audit hook cannot be removed. Network probes use TEST-NET-1 (192.0.2.1) and the .invalid TLD only; the
hook refuses them before any packet or lookup. /usr/bin/open is never started: its argv shape is tested
through the pure predicate.
"""

import ast
import json
import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

from betangel_suite import config, guard, roots
from betangel_suite.errors import SuiteError
from tests import FORBID, PRELUDE, PYTHON, ROOT, child_env, make_home, rmtree, run_python, run_relayed, run_suite

MODES = guard.MODES                                         # "every mode" below: uisnap and stop included
NON_ENGINE = tuple(mode for mode in MODES if mode != "engine")

ATTEMPT = """
import json, os
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


# Loads extension `name` under `alias` and puts that second instance in sys.modules as `key`, before arm().
EARLY_ALIAS = ("import importlib.machinery, importlib.util, sys\n"
               "loader = importlib.machinery.ExtensionFileLoader(%r, importlib.util.find_spec(%r).origin)\n"
               "sys.modules[%r] = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))\n")


def checks(case, home, body, *, setup="", mode="engine", env=None):
    """Run setup, arm the guard, run body (which fills `results`) in a fresh child; return results."""
    code = ATTEMPT + setup + "\nguard.arm(%r)\n" % mode + body + "\nprint(json.dumps(results))\n"
    result = run_python(code, home, env=env)
    case.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def armed_attempts(case, home, body, *, mode, env=None):
    """Like checks(), but arm() is an attempt too: results["arm"] is "ok" or its refusal code, and body runs only if
    it armed. The suite root counts as agreed, as in the code."""
    code = (ATTEMPT + "roots.STATE_ROOT_AGREED = True\nattempt('arm', lambda: guard.arm(%r))\n" % mode
            + "if results['arm'] == 'ok':\n" + "".join("    " + line + "\n" for line in body.strip("\n").splitlines())
            + "print(json.dumps(results))\n")
    result = run_python(code, home, env=env)
    case.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def parse(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), path)


def environment_uses(tree, keys, names):
    """Every environment access in tree that is not a fixed-key lookup (NoOffSwitchTests)."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name in names for alias in node.names):
            problems.append("imports an environment name")
        elif isinstance(node, ast.Constant) and node.value in names:
            problems.append("names %r in a string" % node.value)
        elif isinstance(node, ast.Name) and node.id in names:
            problems.append("uses a bare " + node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            problem = _environ_use(node, parents, keys)
            if problem:
                problems.append(problem)
    return problems


def _environ_use(node, parents, keys):
    if not (node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"):
        return "uses " + ast.unparse(node)
    parent, key = parents.get(node), None
    if isinstance(parent, ast.Attribute) and parent.attr == "get":
        call = parents.get(parent)
        if isinstance(call, ast.Call) and call.func is parent and call.args:
            key = call.args[0]
    elif isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.ctx, ast.Load):
        key = parent.slice
    elif isinstance(parent, ast.comprehension) and parent.iter is node:
        element = getattr(parents.get(parent), "elt", None)       # only guard.arm's any(_stray(key) ...)
        if (isinstance(element, ast.Call) and ast.unparse(element.func) == "_stray"
                and isinstance(parent.target, ast.Name) and [ast.unparse(a) for a in element.args] == [parent.target.id]):
            return None
        return "iterates os.environ"
    if key is None:
        return "uses os.environ as " + type(parent).__name__
    name = key.value if isinstance(key, ast.Constant) else getattr(key, "id", None)
    return None if name in keys else "reads key %r" % (name,)


def arm_outcome(case, home, env=None, flags=("-I", "-S", "-B")):
    """What guard.arm('engine') says in a child started with env and flags (through a relay).

    sys.dont_write_bytecode is set by hand so that a child started without -B still writes no .pyc into
    the checkout; sys.flags, which the guard checks, still shows the missing flag.
    """
    code = ("import sys\nsys.dont_write_bytecode = True\n" + PRELUDE
            + "from betangel_suite import guard\nfrom betangel_suite.errors import SuiteError\n"
            + "try:\n    guard.arm('engine')\n    print('armed')\nexcept SuiteError as exc:\n    print(exc)\n")
    returncode, stdout, stderr = run_relayed([PYTHON, *flags, "-c", code], child_env(home) if env is None else env, home)
    case.assertEqual(returncode, 0, stderr)
    return stdout.strip()


class EnvironmentTests(unittest.TestCase):
    """I-2: the network switch is always on, and nothing stray reaches the engine."""

    def test_refuses_without_the_network_switch(self):
        home = make_home(self)
        self.assertEqual(arm_outcome(self, home, child_env(home, **{FORBID: None})), "network_not_forbidden")
        self.assertEqual(arm_outcome(self, home, child_env(home, **{FORBID: "0"})), "network_not_forbidden")
        self.assertEqual(arm_outcome(self, home), "armed")

    def test_refuses_stray_betfair_variables(self):
        home = make_home(self)
        for key in ("BETFAIR_APP_KEY", "BETANGEL_BETFAIR_PROFILE", "betfair_user"):
            self.assertEqual(arm_outcome(self, home, child_env(home, **{key: "x"})), "stray_environment", key)

    def test_refuses_tmpdir_outside_the_roots(self):
        home = make_home(self)
        outside = os.path.join(home, "elsewhere")
        self.assertEqual(arm_outcome(self, home, child_env(home, TMPDIR=outside, SQLITE_TMPDIR=outside)),
                         "tmpdir_mismatch")
        self.assertEqual(arm_outcome(self, home, child_env(home, SQLITE_TMPDIR=outside)), "tmpdir_mismatch")
        self.assertEqual(arm_outcome(self, home, child_env(home, HOME="relative/home")), "home_invalid")

    def test_refuses_a_tmpdir_the_os_resolves_outside_the_roots(self):
        # Python's tempfile uses the normalised text, but SQLite reads SQLITE_TMPDIR from C, as given: the OS
        # resolves "alias/.." through the link, and follows a link standing in for the directory itself.
        home = make_home(self)
        state = roots.state_dir(home)
        outside = os.path.join(home, "elsewhere", "deep")
        os.makedirs(outside, mode=0o700)
        os.symlink(outside, os.path.join(state, "alias"))
        dotdot = os.path.join(state, "alias", "..", "tmp")     # normalised: state/tmp; resolved: elsewhere/tmp
        linked = os.path.join(state, "linked")
        os.symlink(outside, linked)
        for tmp in (dotdot, linked):
            self.assertEqual(arm_outcome(self, home, child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp)),
                             "tmpdir_mismatch", tmp)
        # A final "/" or a doubled one changes nothing the OS resolves, so they are still accepted.
        for tmp in (roots.tmp_dir("test", home) + "/", os.path.join(state + "//", "tmp")):
            self.assertEqual(arm_outcome(self, home, child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp)), "armed", tmp)

    def test_refuses_a_tmpdir_with_a_dot_or_dotdot_component(self):
        # normpath and the non-strict realpath both fold "missing/.." and "file/.." away, but the OS cannot
        # resolve either (ENOENT, ENOTDIR), and SQLite would then fall back to /var/tmp or /tmp. No "." or ".."
        # component is accepted, so TMPDIR differs from its normalised text only by a redundant or final "/".
        home = make_home(self)
        state = roots.state_dir(home)
        with open(os.path.join(state, "afile"), "x", encoding="utf-8"):
            pass
        for tmp in (os.path.join(state, "missing", "..", "tmp"), os.path.join(state, "afile", "..", "tmp"),
                    os.path.join(state, ".", "tmp"), roots.tmp_dir("test", home) + "/."):
            self.assertEqual(arm_outcome(self, home, child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp)),
                             "tmpdir_mismatch", tmp)

    def test_arm_checks_the_interpreter_version_itself(self):
        # guard.arm is the only version check when tests or a future entry point start without _launch.py.
        # The child runs on this interpreter; only sys.version_info is replaced before arming.
        home = make_home(self)
        code = ("import json\nfrom betangel_suite import guard\nfrom betangel_suite.errors import SuiteError\n"
                "real = sys.version_info\nout = {}\n"
                "for fake in ((3, 15, 0), (3, 14, 1), (3, 12, 9), (3, 10, 14)):\n"
                "    sys.version_info = fake + ('final', 0)\n"
                "    try:\n        guard.arm('engine')\n        out[repr(fake)] = 'armed'\n"
                "    except SuiteError as exc:\n        out[repr(fake)] = str(exc)\n"
                "sys.version_info = real\nguard.arm('engine')\nout['real'] = guard.armed_mode()\n"
                "print(json.dumps(out))\n")
        result = run_python(code, home)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out.pop("real"), "engine")
        self.assertEqual(set(out.values()), {"interpreter_version"}, out)

    def test_refuses_an_interpreter_started_without_the_launcher_flags(self):
        # Never without -S here: site would run Homebrew's .pth files in the child.
        home = make_home(self)
        self.assertEqual(arm_outcome(self, home, flags=("-I", "-S")), "launch_flags")
        self.assertEqual(arm_outcome(self, home, flags=("-S", "-B")), "launch_flags")

    def test_the_switch_and_the_temp_dirs_cannot_be_changed_after_arming(self):
        home = make_home(self)
        results = checks(self, home, """
attempt("switch_off", lambda: os.environ.__setitem__(guard.FORBID_NETWORK_ENV, "0"))
attempt("switch_deleted", lambda: os.environ.__delitem__(guard.FORBID_NETWORK_ENV))
attempt("putenv_switch", lambda: os.putenv(guard.FORBID_NETWORK_ENV, "0"))
attempt("stray_set", lambda: os.environ.__setitem__("BETFAIR_SESSION", "x"))
attempt("tmpdir_moved", lambda: os.environ.__setitem__("TMPDIR", "/tmp"))
attempt("tmpdir_deleted", lambda: os.environ.__delitem__("TMPDIR"))
attempt("sqlite_tmpdir_moved", lambda: os.environ.__setitem__("SQLITE_TMPDIR", "/tmp"))
attempt("sqlite_tmpdir_deleted", lambda: os.environ.__delitem__("SQLITE_TMPDIR"))
attempt("switch_on_again", lambda: os.environ.__setitem__(guard.FORBID_NETWORK_ENV, "1"))
attempt("ordinary_variable", lambda: os.environ.__setitem__("SUITE_TEST_ORDINARY", "1"))
results["switch_value"] = os.environ.get(guard.FORBID_NETWORK_ENV)
""")
        for name in ("switch_off", "switch_deleted", "putenv_switch", "stray_set", "tmpdir_moved",
                     "tmpdir_deleted", "sqlite_tmpdir_moved", "sqlite_tmpdir_deleted"):
            self.assertEqual(results[name], "environment_change_refused", name)
        self.assertEqual(results["switch_on_again"], "ok")
        self.assertEqual(results["ordinary_variable"], "ok")
        self.assertEqual(results["switch_value"], "1")


class NoOffSwitchTests(unittest.TestCase):
    """I-2: no environment or config read can disable the guard, and the guard has no off function."""

    PUBLIC = {"GuardRefusal", "arm", "seal", "armed_mode", "is_sealed", "require_armed", "require_mode",
              "permit_loopback_port", "permit_unix_socket", "engine_argv_ok", "vendor_argv_ok", "runner_argv_ok",
              "runner_git_ok"}

    def test_guard_public_callables_are_exactly_these(self):
        public = {name for name, value in vars(guard).items()
                  if callable(value) and not name.startswith("_") and getattr(value, "__module__", "") == guard.__name__}
        self.assertEqual(public, self.PUBLIC)

    ENV_KEYS = {"HOME", "TMPDIR", "SQLITE_TMPDIR", "PATH", "FORBID_NETWORK_ENV"}
    ENV_NAMES = {"environ", "environb", "getenv", "getenvb"}

    def test_environment_reads_are_fixed_key_lookups_only(self):
        # An allowlist, not a search for known shapes: os.environ may appear only as os.environ.get(KEY, ...)
        # or os.environ[KEY] with KEY one of ENV_KEYS, plus the one stray-variable scan in guard.arm. So
        # `"X" in os.environ`, .items(), .copy(), dict(os.environ), os.environb, os.getenv, an imported
        # environ and getattr(os, "environ") all fail it.
        sources = [os.path.join(ROOT, "betangel_suite", name) for name in os.listdir(os.path.join(ROOT, "betangel_suite"))
                   if name.endswith(".py")]
        sources += [os.path.join(ROOT, "bin", "_launch.py"), os.path.join(ROOT, "tools", "vendor_research.py")]
        for path in sources:
            name = os.path.relpath(path, ROOT)
            for problem in environment_uses(parse(path), self.ENV_KEYS, self.ENV_NAMES):
                self.fail("%s: %s" % (name, problem))

    def test_the_allowlist_rule_catches_off_switch_shapes(self):
        for source in ('if "SUITE_GUARD_OFF" in os.environ:\n    pass\n', "x = dict(os.environ)\n",
                       "x = os.environ.items()\n", "x = os.getenv('HOME')\n", "x = os.environb\n",
                       "from os import environ\n", "x = getattr(os, 'environ')\n", "x = os.environ.get('OFF')\n",
                       "x = os.environ['OFF']\n", "x = any(k == 'OFF' for k in os.environ)\n",
                       "x = posix.environ\n", "x = os.environ.setdefault('HOME', '')\n"):
            self.assertTrue(environment_uses(ast.parse(source), self.ENV_KEYS, self.ENV_NAMES), source)
        self.assertEqual(environment_uses(ast.parse("x = os.environ.get('HOME', '')\ny = os.environ['TMPDIR']\n"),
                                          self.ENV_KEYS, self.ENV_NAMES), [])

    def test_the_hook_is_installed_unconditionally(self):
        tree = parse(os.path.join(ROOT, "betangel_suite", "guard.py"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == "sys.addaudithook"]
        self.assertEqual(len(calls), 1)
        arm = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "arm")
        withs = [node for node in arm.body if isinstance(node, ast.With)]
        self.assertEqual([ast.unparse(item.context_expr) for item in withs[0].items], ["_LOCK"])
        self.assertTrue(any(isinstance(node, ast.Expr) and node.value is calls[0] for node in withs[0].body),
                        "sys.addaudithook must be a direct statement of arm's `with _LOCK:` body")
        for node in ast.walk(arm):
            self.assertNotIsInstance(node, (ast.Try, ast.For, ast.While, ast.Match), ast.unparse(node)[:60])
        parents = {child: node for node in ast.walk(arm) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(arm):
            if isinstance(node, ast.Return):
                self.assertEqual(ast.unparse(parents[node].test), "_STATE is not None")   # already armed

    def test_guard_imports_nothing_that_could_switch_it(self):
        tree = parse(os.path.join(ROOT, "betangel_suite", "guard.py"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {"%s%s.%s" % ("." * node.level, node.module or "", alias.name) for alias in node.names}
        self.assertEqual(imported, {"fcntl", "os", "re", "stat", "sys", "threading", "posix", "sqlite3",
                                    "sqlite3.dbapi2", "subprocess", "_posixsubprocess", "..roots",
                                    ".errors.SuiteError"})

    def test_config_has_no_key_about_the_guard(self):
        for key in config.DEFAULTS:
            for word in ("guard", "hook", "audit", "network", "forbid", "seal", "sandbox"):
                self.assertNotIn(word, key)

    def test_no_other_module_reaches_into_guard_internals(self):
        for folder in ("betangel_suite", "bin", "tools", "tests"):
            for directory, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for name in files:
                    if not name.endswith(".py") or (folder == "betangel_suite" and name == "guard.py"):
                        continue
                    with open(os.path.join(directory, name), encoding="utf-8") as handle:
                        tree = ast.parse(handle.read())
                    for node in ast.walk(tree):
                        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                                and node.value.id == "guard" and node.attr.startswith("_")
                                and not node.attr.startswith("__")):
                            self.fail(name + " uses guard." + node.attr)

    def test_this_runner_is_armed_in_test_mode(self):
        self.assertEqual(guard.armed_mode(), "test")
        with self.assertRaises(guard.GuardRefusal):
            open(os.path.join(ROOT, "should-never-exist.txt"), "w")
        self.assertFalse(os.path.exists(os.path.join(ROOT, "should-never-exist.txt")))


class HookStateTests(unittest.TestCase):
    """The hook keeps no flag that could switch it off: the gc route a reviewer found is closed.

    Deliberately adversarial same-process code can still rewrite the hook's state (guard.py docstring;
    DESIGN.md 9.4, I-16); this test pins the specific route of a persistent reentrancy flag.
    """

    def test_no_reachable_flag_switches_the_hook_off(self):
        home = make_home(self)
        results = checks(self, home, body="""
import gc, threading
hooks = [o for o in gc.get_objects() if getattr(o, "__qualname__", "").endswith("audit_hook")
         and getattr(o, "__module__", "") == "betangel_suite.guard"]
results["hooks"] = len(hooks)
reachable = [v for hook in hooks for v in tuple(hook.__defaults__ or ())
             + tuple(cell.cell_contents for cell in (hook.__closure__ or ()))]
results["thread_locals"] = sum(isinstance(v, threading.local) for v in reachable)
for value in gc.get_objects():
    if isinstance(value, threading.local):
        try:
            value.busy = True
        except Exception:
            pass
attempt("write_outside_after_flip", lambda: open(os.path.join(os.environ["HOME"], "flip.txt"), "w").close())
attempt("write_outside_again", lambda: open(os.path.join(os.environ["HOME"], "flip2.txt"), "w").close())
""")
        self.assertEqual((results["hooks"], results["thread_locals"]), (1, 0))
        self.assertEqual(results["write_outside_after_flip"], "write_outside_roots")
        self.assertEqual(results["write_outside_again"], "write_outside_roots")
        self.assertFalse(os.path.lexists(os.path.join(home, "flip.txt")))


class NetworkTests(unittest.TestCase):
    """I-3: no outbound network and no name lookups, before or after seal, whatever later hooks do."""

    def test_connections_and_lookups_are_refused_before_any_packet(self):
        home = make_home(self)
        results = checks(self, home, """
import socket, sys, time
started = time.monotonic()
def raw_connect():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(("192.0.2.1", 443))
def raw_connect_ex():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect_ex(("192.0.2.1", 443))
def udp_sendto():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"x", ("192.0.2.1", 9))
attempt("create_connection", lambda: socket.create_connection(("192.0.2.1", 443), timeout=2))
attempt("connect", raw_connect)
attempt("connect_ex", raw_connect_ex)
attempt("sendto", udp_sendto)
def udp_sendmsg():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendmsg([b"x"], [], 0, ("192.0.2.1", 9))
attempt("sendmsg", udp_sendmsg)
attempt("getaddrinfo", lambda: socket.getaddrinfo("example.invalid", 443))
attempt("gethostbyname", lambda: socket.gethostbyname("example.invalid"))
attempt("gethostbyaddr", lambda: socket.gethostbyaddr("192.0.2.1"))
attempt("getnameinfo", lambda: socket.getnameinfo(("192.0.2.1", 443), 0))
sys.addaudithook(lambda event, args: None)
attempt("connect_after_second_hook", raw_connect)
guard.seal()
attempt("connect_after_seal", raw_connect)
results["elapsed_s"] = time.monotonic() - started
""")
        for name in ("connect", "connect_ex", "sendto", "sendmsg", "connect_after_second_hook", "connect_after_seal"):
            self.assertEqual(results[name], "network_refused", name)
        for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyaddr", "getnameinfo"):
            self.assertEqual(results[name], "name_lookup_refused", name)
        self.assertLess(results["elapsed_s"], 1.5)


class BindTests(unittest.TestCase):
    """I-4: loopback only, and only what was permitted before seal()."""

    SUN_PATH_MAX = 104      # macOS sockaddr_un; CPython refuses a longer path before the bind event

    def test_binds(self):
        # The Unix-socket refusals bind short relative names (after a chdir), so they reach the hook whatever
        # the length of HOME; the hook never permits a relative name. The absolute cases run only when the
        # path fits, and the test says so instead of misreporting an OSError.
        home = make_home(self)
        results = checks(self, home, setup="os.makedirs(roots.run_dir(), mode=0o700)\n", body="""
import socket, sys
def bind(family, address):
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind(address)
        return sock.getsockname()
def bind_relative(directory, name):
    before = os.getcwd()
    os.chdir(directory)
    try:
        return bind(socket.AF_UNIX, name)
    finally:
        os.chdir(before)
run = roots.run_dir()
control = os.path.join(run, "c.sock")
guard.permit_loopback_port(0)
guard.permit_unix_socket(control)
attempt("loopback_permitted", lambda: bind(socket.AF_INET, ("127.0.0.1", 0)))
attempt("wildcard", lambda: bind(socket.AF_INET, ("0.0.0.0", 0)))
attempt("port_not_permitted", lambda: bind(socket.AF_INET, ("127.0.0.1", 8765)))
attempt("unix_elsewhere", lambda: bind_relative(os.environ["HOME"], "x.sock"))
attempt("unix_not_permitted", lambda: bind_relative(run, "o.sock"))
attempt("unix_permitted_but_relative", lambda: bind_relative(run, "c.sock"))
results["absolute_fits"] = len(os.fsencode(control)) < %d
if results["absolute_fits"]:
    attempt("unix_absolute_not_permitted", lambda: bind(socket.AF_UNIX, os.path.join(run, "o.sock")))
    attempt("unix_permitted", lambda: bind(socket.AF_UNIX, control))
attempt("permit_outside_run_dir", lambda: guard.permit_unix_socket(os.path.join(os.environ["HOME"], "y.sock")))
attempt("permit_bad_port", lambda: guard.permit_loopback_port(70000))
# Audit-only from here (nothing is bound, so the path length does not matter): normpath would fold "alias/.."
# that the OS resolves through the link, a permitted name that is a dangling link makes bind create the socket
# at the link's target, and a run directory replaced by a link moves every socket in it.
def audit_bind(address):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sys.audit("socket.bind", sock, address)
os.symlink(os.environ["HOME"], os.path.join(run, "alias"))
attempt("unix_dotdot_after_link", lambda: audit_bind(os.path.join(run, "alias", "..", "c.sock")))
attempt("unix_permitted_audit", lambda: audit_bind(control))
dangling = os.path.join(run, "b.sock")              # bind would follow it and create HOME/b-target.sock
guard.permit_unix_socket(dangling)
os.symlink(os.path.join(os.environ["HOME"], "b-target.sock"), dangling)
attempt("unix_permitted_dangling_link", lambda: audit_bind(dangling))
# A NUL ends the kernel's socket name, so "n.sock\\0x" would bind n.sock, here a dangling link out of the run
# directory, and islink cannot see that (it says False for any path with a NUL). The permit refuses it, and
# so does the hook if the NUL name is put in its permits directly (through gc, as HookStateTests does).
nul = os.path.join(run, "n.sock")
os.symlink(os.path.join(os.environ["HOME"], "n-target.sock"), nul)
attempt("permit_embedded_nul", lambda: guard.permit_unix_socket(nul + "\\0x"))
import gc
hook_state = [value for hook in gc.get_objects() if getattr(hook, "__qualname__", "").endswith("audit_hook")
              and getattr(hook, "__module__", "") == "betangel_suite.guard"
              for value in hook.__defaults__ if hasattr(value, "unix_paths")]
results["hook_states"] = len(hook_state)
hook_state[0].unix_paths.add(nul + "\\0x")
attempt("unix_embedded_nul_forced", lambda: audit_bind(nul + "\\0x"))
attempt("unix_embedded_nul_bytes_forced", lambda: audit_bind(os.fsencode(nul) + b"\\0x"))
attempt("permit_noncanonical", lambda: guard.permit_unix_socket(os.path.join(run, "alias", "..", "d.sock")))
attempt("permit_trailing_slash", lambda: guard.permit_unix_socket(control + "/"))
guard.seal()
attempt("permit_after_seal", lambda: guard.permit_loopback_port(9000))
attempt("loopback_after_seal", lambda: bind(socket.AF_INET, ("127.0.0.1", 0)))
# run/ cannot be moved away from inside the suite (it holds the realdata lock's name: run_lock_protected), so the
# run directory replaced by a link is tested in test_a_run_directory_replaced_by_a_link_moves_no_socket.
attempt("rename_run_dir", lambda: os.rename(run, run + "-moved"))
""" % self.SUN_PATH_MAX)
        self.assertEqual(results["loopback_permitted"], "ok")
        self.assertEqual(results["loopback_after_seal"], "ok")
        for name in ("wildcard", "port_not_permitted", "unix_elsewhere", "unix_not_permitted",
                     "unix_permitted_but_relative"):
            self.assertEqual(results[name], "bind_refused", name)
        if results["absolute_fits"]:
            self.assertEqual(results["unix_absolute_not_permitted"], "bind_refused")
            self.assertEqual(results["unix_permitted"], "ok")
        self.assertFalse(os.path.lexists(os.path.join(home, "x.sock")))
        self.assertEqual(results["permit_outside_run_dir"], "bind_permit_invalid")
        self.assertEqual(results["permit_bad_port"], "bind_permit_invalid")
        self.assertEqual(results["permit_after_seal"], "guard_sealed")
        self.assertEqual(results["unix_permitted_audit"], "ok")
        self.assertEqual(results["hook_states"], 1)
        for name in ("unix_dotdot_after_link", "unix_permitted_dangling_link", "unix_embedded_nul_forced",
                     "unix_embedded_nul_bytes_forced"):
            self.assertEqual(results[name], "bind_refused", name)
        for name in ("permit_noncanonical", "permit_trailing_slash", "permit_embedded_nul"):
            self.assertEqual(results[name], "bind_permit_invalid", name)
        self.assertEqual(results["rename_run_dir"], "run_lock_protected")

    def test_a_run_directory_replaced_by_a_link_moves_no_socket(self):
        # The suite cannot move run/ away itself (run_lock_protected), but another process can, while the suite runs.
        # The bind check compares where run/ resolves with where it resolved at arm(): a permitted socket path in a
        # run/ replaced by a link would be created at the link's target. arm() refuses a run/ that is already a link
        # (run_lock_invalid, the guard-paths review), so here a test-mode child (the bind check is the same in every
        # mode) starts an unguarded interpreter that moves the real run/ away and puts a link in its place. The runner
        # starts no interpreter with its own HOME (lab-Claude's round-5 review of F2), so that one gets another HOME.
        home = make_home(self)
        results = checks(self, home, mode="test", setup="""
os.makedirs(os.path.join(os.environ["HOME"], "elsewhere"), mode=0o700)
os.makedirs(roots.run_dir(), mode=0o700)
""", body="""
import socket, subprocess, sys
run, elsewhere = roots.run_dir(), os.path.join(os.environ["HOME"], "elsewhere")
replace = "import os, sys\\nos.rename(sys.argv[1], sys.argv[1] + '.moved')\\nos.symlink(sys.argv[2], sys.argv[1])\\n"
results["replaced"] = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", replace, run, elsewhere],
                                     env=dict(os.environ, HOME=elsewhere)).returncode
results["run_is_link"] = os.path.islink(run)
def audit_bind(address):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sys.audit("socket.bind", sock, address)
control = os.path.join(run, "c.sock")
guard.permit_unix_socket(control)
attempt("unix_run_dir_replaced", lambda: audit_bind(control))
""")
        self.assertEqual((results["replaced"], results["run_is_link"]), (0, True))
        self.assertEqual(results["unix_run_dir_replaced"], "bind_refused")

    # Nuance's PR #2 review, item 4: CPython raises no listen event, and listen() on an unbound AF_INET socket binds
    # it to 0.0.0.0. The refused cases use unbound SOCK_DGRAM sockets, which never listen: if the guard let one
    # through, the kernel would refuse it (EOPNOTSUPP, "other:OSError"), so this test never listens on 0.0.0.0.
    LISTEN = """
import socket, _socket
def unbound(family):
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.listen(1)
def loopback():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
"""

    def test_listen(self):
        home = make_home(self)
        results = checks(self, home, setup="os.makedirs(roots.run_dir(), mode=0o700)\n", body=self.LISTEN + """
def loopback_datagram():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
def unix(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(path)
        sock.listen(1)
class Plain(socket.socket):
    pass
class OwnListen(socket.socket):
    def listen(self, *args):
        return _socket.socket.listen(self, *args)
def subclass(cls):
    with cls(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.listen(1)
control = os.path.join(roots.run_dir(), "c.sock")
guard.permit_loopback_port(0)
guard.permit_unix_socket(control)
attempt("inet_unbound", lambda: unbound(socket.AF_INET))
attempt("inet6_unbound", lambda: unbound(socket.AF_INET6))
attempt("unix_unbound", lambda: unbound(socket.AF_UNIX))
attempt("loopback_port_0", loopback)
attempt("loopback_datagram", loopback_datagram)
attempt("plain_subclass", lambda: subclass(Plain))
attempt("own_listen_subclass", lambda: subclass(OwnListen))
attempt("bare_socket", lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM).close())
results["absolute_fits"] = len(os.fsencode(control)) < %d
if results["absolute_fits"]:
    attempt("unix_permitted", lambda: unix(control))
guard.seal()
attempt("inet_unbound_after_seal", lambda: unbound(socket.AF_INET))
attempt("loopback_after_seal", loopback)
""" % self.SUN_PATH_MAX)
        for name in ("loopback_port_0", "loopback_after_seal"):
            self.assertEqual(results[name], "ok", name)
        # Let through by the guard (127.0.0.1 and a port), then refused by the kernel: a datagram socket.
        self.assertEqual(results["loopback_datagram"], "other:OSError")
        for name in ("inet_unbound", "inet6_unbound", "unix_unbound", "plain_subclass", "own_listen_subclass",
                     "bare_socket", "inet_unbound_after_seal"):
            self.assertEqual(results[name], "listen_refused", name)
        if results["absolute_fits"]:
            self.assertEqual(results["unix_permitted"], "ok")

    def test_listen_in_every_mode_and_on_sockets_made_before_arm(self):
        # A socket made before arm() is covered because arm() installs the wrapper at once when socket is loaded,
        # and arm() fails closed if socket.socket already has a listen of its own.
        home = make_home(self)
        early = "import socket\nearly = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        for mode in MODES:
            results = checks(self, home, setup=early, mode=mode, body=self.LISTEN + """
attempt("early_unbound", lambda: early.listen(1))
early.close()
attempt("inet_unbound", lambda: unbound(socket.AF_INET))
""")
            self.assertEqual(results, {"early_unbound": "listen_refused", "inet_unbound": "listen_refused"}, mode)
        code = (ATTEMPT + "import socket\nsocket.socket.listen = lambda self, *args: None\n"
                + "attempt('arm', lambda: guard.arm('engine'))\nprint(json.dumps(results))\n")
        result = run_python(code, home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["arm"], "call_replaced_early")


class SubprocessTests(unittest.TestCase):
    """I-5: exactly two argv shapes during startup, nothing after seal(), no fork, exec or dlopen."""

    def test_engine_startup_then_seal(self):
        home = make_home(self)
        results = checks(self, home, setup="os.makedirs(roots.state_dir(), exist_ok=True)\n", body="""
import subprocess
state = roots.state_dir()
def run(argv):
    subprocess.run(argv, capture_output=True, timeout=30)
def fork():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
attempt("git_probe_in_roots", lambda: run(["git", "-C", state, "rev-parse", "--is-inside-work-tree"]))
attempt("git_probe_outside_roots", lambda: run(["git", "-C", os.environ["HOME"], "rev-parse", "--is-inside-work-tree"]))
attempt("git_other_argv", lambda: run(["git", "-C", state, "status"]))
attempt("shell", lambda: subprocess.run("true", shell=True))
attempt("os_system", lambda: os.system("true"))
attempt("posix_spawn", lambda: os.posix_spawn("/usr/bin/true", ["/usr/bin/true"], dict(os.environ)))
attempt("fork", fork)
attempt("ctypes", lambda: __import__("ctypes"))
guard.seal()
attempt("git_probe_after_seal", lambda: run(["git", "-C", state, "rev-parse", "--is-inside-work-tree"]))
attempt("security_cli", lambda: run(["/usr/bin/" + "secur" + "ity", "help"]))
results["sealed"] = guard.is_sealed()
print(json.dumps(results))
attempt("execv", lambda: os.execv("/usr/bin/true", ["/usr/bin/true"]))
""")
        self.assertEqual(results["git_probe_in_roots"], "ok")
        for name in ("git_probe_outside_roots", "git_other_argv", "shell", "os_system", "posix_spawn", "fork",
                     "git_probe_after_seal", "security_cli", "execv"):
            self.assertEqual(results[name], "subprocess_refused", name)
        self.assertEqual(results["ctypes"], "import_refused")
        self.assertTrue(results["sealed"])

    def test_engine_bare_git_needs_the_system_search_path(self):
        # engine_argv_ok matches the shape upstream uses (a bare "git"); the hook also requires that the name
        # resolve through /usr/bin and /bin only, so a planted program called git never starts.
        home = make_home(self)
        setup = """
os.makedirs(roots.state_dir(), exist_ok=True)
stub = os.path.join(os.environ["HOME"], "stub")
os.makedirs(stub)
with open(os.path.join(stub, "git"), "w") as handle:
    handle.write("#!/bin/sh\\nexit 0\\n")
os.chmod(os.path.join(stub, "git"), 0o755)
"""
        results = checks(self, home, setup=setup, body="""
import subprocess
argv = ["git", "-C", roots.state_dir(), "rev-parse", "--is-inside-work-tree"]
base = {key: os.environ[key] for key in ("HOME", "TMPDIR", "SQLITE_TMPDIR", guard.FORBID_NETWORK_ENV)}
def run(env):
    subprocess.run(argv, env=env, capture_output=True, timeout=30)
attempt("system_path", lambda: run(dict(base, PATH="/usr/bin:/bin")))
attempt("default_path", lambda: run(dict(base)))
attempt("stub_path", lambda: run(dict(base, PATH=stub)))
attempt("stub_first", lambda: run(dict(base, PATH=stub + ":/usr/bin:/bin")))
attempt("posix_spawn_relative", lambda: os.posix_spawn("git", argv, dict(base, PATH="/usr/bin:/bin")))
os.environ["PATH"] = stub
attempt("inherited_stub_path", lambda: run(None))
""")
        self.assertEqual((results["system_path"], results["default_path"]), ("ok", "ok"))
        for name in ("stub_path", "stub_first", "posix_spawn_relative", "inherited_stub_path"):
            self.assertEqual(results[name], "subprocess_refused", name)

    # Routes to a child process that raise no audit event of their own (Nuance's PR #2 review, item 3). Each would
    # leave a name in outside/ if its child ran: fork_exec with the arguments multiprocessing.util.spawnv_passfds
    # passes on 3.11 and 3.13 runs /usr/bin/touch, and the spawned Process and pool worker run os.mkdir.
    CHILDREN = """
import subprocess, threading
import _posixsubprocess
outside = os.path.join(os.environ["HOME"], "outside")
def fork_exec():
    read, write = os.pipe()
    try:
        pid = _posixsubprocess.fork_exec(
            [b"/usr/bin/touch", os.fsencode(os.path.join(outside, "fork-exec"))], [b"/usr/bin/touch"], True, (),
            None, None, -1, -1, -1, -1, -1, -1, read, write, False, False, -1, None, None, None, -1, None,
            subprocess._USE_VFORK)
    finally:
        os.close(read)
        os.close(write)
    os.waitpid(pid, 0)
def process_start(name):
    import multiprocessing
    process = multiprocessing.Process(target=os.mkdir, args=(os.path.join(outside, name),))
    process.start()
    process.join(20)
def pool_submit(name):
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(1) as pool:
        pool.submit(os.mkdir, os.path.join(outside, name)).result(20)
def thread_runs():
    box = []
    worker = threading.Thread(target=box.append, args=(1,))
    worker.start()
    worker.join(20)
    if box != [1]:
        raise RuntimeError("thread")
def thread_pool_runs():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        if pool.submit(sum, [1, 2]).result(20) != 3:
            raise RuntimeError("thread pool")
"""
    CHILDREN_SETUP = ("os.makedirs(roots.state_dir(), exist_ok=True)\n"
                      "os.makedirs(os.path.join(os.environ['HOME'], 'outside'), exist_ok=True)\n")

    def test_children_without_an_audit_event_are_refused(self):
        # A sealed engine refused subprocess.run, but multiprocessing (spawn, the macOS default),
        # ProcessPoolExecutor and _posixsubprocess.fork_exec all started unguarded children that wrote outside the
        # roots. Startup git, which goes through subprocess, and threads must keep working.
        home = make_home(self)
        results = checks(self, home, setup=self.CHILDREN_SETUP, body=self.CHILDREN + """
state = roots.state_dir()
attempt("git_before_seal", lambda: subprocess.run(["git", "-C", state, "rev-parse", "--is-inside-work-tree"],
                                                  capture_output=True, timeout=30))
attempt("fork_exec_before_seal", fork_exec)
attempt("process_start_before_seal", lambda: process_start("process-1"))
attempt("pool_submit_before_seal", lambda: pool_submit("pool-1"))
attempt("thread_before_seal", thread_runs)
guard.seal()
attempt("fork_exec", fork_exec)
attempt("process_start", lambda: process_start("process-2"))
attempt("pool_submit", lambda: pool_submit("pool-2"))
attempt("thread", thread_runs)
attempt("thread_pool", thread_pool_runs)
results["subprocess_keeps_its_own"] = subprocess._fork_exec is not _posixsubprocess.fork_exec
results["outside"] = sorted(os.listdir(outside))
""")
        for name in ("git_before_seal", "thread_before_seal", "thread", "thread_pool"):
            self.assertEqual(results[name], "ok", name)
        for name in ("fork_exec_before_seal", "fork_exec"):
            self.assertEqual(results[name], "subprocess_refused", name)
        for name in ("process_start_before_seal", "pool_submit_before_seal", "process_start", "pool_submit"):
            self.assertEqual(results[name], "import_refused", name)
        self.assertTrue(results["subprocess_keeps_its_own"])
        self.assertEqual(results["outside"], [])

    def test_children_without_an_audit_event_are_refused_in_every_mode(self):
        home = make_home(self)
        for mode in NON_ENGINE:
            results = checks(self, home, setup=self.CHILDREN_SETUP, mode=mode, body=self.CHILDREN + """
attempt("fork_exec", fork_exec)
attempt("process_start", lambda: process_start("process"))
attempt("pool_submit", lambda: pool_submit("pool"))
attempt("thread_pool", thread_pool_runs)
results["outside"] = sorted(os.listdir(outside))
""")
            self.assertEqual(results, {"fork_exec": "subprocess_refused", "process_start": "import_refused",
                                       "pool_submit": "import_refused", "thread_pool": "ok", "outside": []}, mode)

    def test_ctypes_cannot_reach_libc(self):
        # Nuance's PR #2 review, item 18: _ctypes.call_function(_ctypes.dlsym(RTLD_DEFAULT, "mkdir"), ...) made a
        # directory outside the roots with no dlopen. Importing ctypes or _ctypes is refused however it is spelled,
        # and the symbol lookup and the raw call are refused as a backstop (audit-only: _ctypes cannot load).
        home = make_home(self)
        results = checks(self, home, setup=self.CHILDREN_SETUP, body="""
import importlib, sys
outside = os.path.join(os.environ["HOME"], "outside")
def libc_mkdir(name):
    import _ctypes
    address = _ctypes.dlsym((1 << 64) - 2, "mkdir")       # RTLD_DEFAULT on macOS
    _ctypes.call_function(address, (os.fsencode(os.path.join(outside, name)), 0o700))
def cdll_mkdir(name):
    import ctypes
    ctypes.CDLL(None).mkdir(os.fsencode(os.path.join(outside, name)), 0o700)
attempt("libc_through_ctypes_private", lambda: libc_mkdir("private"))
attempt("libc_through_ctypes", lambda: cdll_mkdir("public"))
attempt("import_module_ctypes", lambda: importlib.import_module("ctypes"))
attempt("import_module_private", lambda: importlib.import_module("_ctypes"))
attempt("import_util", lambda: importlib.import_module("ctypes.util"))
attempt("dunder_import", lambda: __import__("_ctypes"))
attempt("audit_dlsym", lambda: sys.audit("ctypes.dlsym", None, "mkdir"))
attempt("audit_dlsym_handle", lambda: sys.audit("ctypes.dlsym/handle", (1 << 64) - 2, "mkdir"))
attempt("audit_call_function", lambda: sys.audit("ctypes.call_function", 0, ()))
guard.seal()
attempt("libc_after_seal", lambda: libc_mkdir("sealed"))
results["loaded"] = sorted(name for name in sys.modules if "ctypes" in name)
results["outside"] = sorted(os.listdir(outside))
""")
        for name in ("libc_through_ctypes_private", "libc_through_ctypes", "import_module_ctypes",
                     "import_module_private", "import_util", "dunder_import", "libc_after_seal"):
            self.assertEqual(results[name], "import_refused", name)
        for name in ("audit_dlsym", "audit_dlsym_handle", "audit_call_function"):
            self.assertEqual(results[name], "dlopen_refused", name)
        self.assertEqual((results["loaded"], results["outside"]), ([], []))

    # Fresh loads of a refused extension module (Astra's re-review of #2, finding 1; Nuance's re-review, F4). The
    # wrapper sits on one _posixsubprocess instance: popping it from sys.modules and importing again, module_from_spec,
    # _imp.create_dynamic and a dotted ExtensionFileLoader name each gave a module whose fork_exec started
    # /usr/bin/touch outside the roots after seal(). A dotted "x._ctypes" loads _ctypes, and a subinterpreter (its own
    # audit hooks, none of ours) ran os.mkdir outside the roots. Each helper uses what it loaded, so a load that got
    # through leaves a name in outside/.
    FRESH_HELPERS = """
import _imp, importlib, importlib.machinery, importlib.util, subprocess, sys
outside = os.path.join(os.environ["HOME"], "outside")
SUBINTERPRETERS = [name for name in ("_interpreters", "_xxsubinterpreters") if importlib.util.find_spec(name)]
def spawn_with(module, name):
    read, write = os.pipe()
    try:
        pid = module.fork_exec(
            [b"/usr/bin/touch", os.fsencode(os.path.join(outside, name))], [b"/usr/bin/touch"], True, (),
            None, None, -1, -1, -1, -1, -1, -1, read, write, False, False, -1, None, None, None, -1, None,
            subprocess._USE_VFORK)
    finally:
        os.close(read)
        os.close(write)
    os.waitpid(pid, 0)
def reimport():
    saved = sys.modules.pop("_posixsubprocess")
    try:
        import _posixsubprocess as fresh
    finally:
        sys.modules["_posixsubprocess"] = saved
    return fresh
def from_spec():
    return importlib.util.module_from_spec(importlib.util.find_spec("_posixsubprocess"))
def create_dynamic():
    return _imp.create_dynamic(importlib.util.find_spec("_posixsubprocess"))
def dotted(name, as_name):
    loader = importlib.machinery.ExtensionFileLoader(as_name, importlib.util.find_spec(name).origin)
    return importlib.util.module_from_spec(importlib.util.spec_from_loader(as_name, loader))
class Disguised(str):
    # A name that answers the string methods for itself; CPython loads by the characters it holds.
    def rpartition(self, sep):
        return ("", sep, "harmless")
    def startswith(self, *args):
        return False
    def __eq__(self, other):
        return False
    __hash__ = str.__hash__
def disguised():
    spec = importlib.util.find_spec("_posixsubprocess")
    spec = importlib.util.spec_from_loader(Disguised("yy._posixsubprocess"),
                                           importlib.machinery.ExtensionFileLoader("yy._posixsubprocess", spec.origin))
    return importlib.util.module_from_spec(spec)
def reloaded():
    return importlib.reload(sys.modules["_posixsubprocess"])
def run_inside(module, name):
    code = "import os; os.mkdir(%r)" % os.path.join(outside, name)
    if hasattr(module, "run_in_subinterp"):
        module.run_in_subinterp(code)
    else:
        module.run_string(module.create(), code)
"""
    FRESH = FRESH_HELPERS + """
def phase(suffix):
    for label, load in (("reimport", reimport), ("from_spec", from_spec), ("create_dynamic", create_dynamic),
                        ("dotted", lambda: dotted("_posixsubprocess", "zz._posixsubprocess")),
                        ("disguised", disguised), ("reload", reloaded)):
        attempt(label + suffix, lambda: spawn_with(load(), label + suffix))
    attempt("ctypes_dotted" + suffix, lambda: dotted("_ctypes", "zz._ctypes").dlsym)
    for name in SUBINTERPRETERS + ["_testcapi"]:
        attempt(name + suffix, lambda: run_inside(importlib.import_module(name), name + suffix))
        attempt(name + "_dotted" + suffix, lambda: run_inside(dotted(name, "zz." + name), name + "_dotted" + suffix))
    attempt("_testinternalcapi" + suffix, lambda: importlib.import_module("_testinternalcapi"))
    attempt("cached_import" + suffix, lambda: __import__("_posixsubprocess"))
phase("")
guard.seal()
phase("_sealed")
results["still_wrapped"] = type(sys.modules["_posixsubprocess"].fork_exec) is not type(len)
results["subinterpreter_modules"] = len(SUBINTERPRETERS)
results["loaded"] = sorted(name for name in sys.modules if name.rpartition(".")[2] in (
    "_ctypes", "_interpreters", "_xxsubinterpreters", "_testcapi", "_testinternalcapi") or name.startswith(("yy", "zz")))
results["outside"] = sorted(os.listdir(outside))
"""

    def test_fresh_loads_of_a_refused_extension_are_refused_in_every_mode(self):
        home = make_home(self)
        for mode in MODES:
            results = checks(self, home, setup=self.CHILDREN_SETUP, mode=mode, body=self.FRESH)
            with self.subTest(mode=mode):
                self.assertEqual(results.pop("subinterpreter_modules"), 1)     # _interpreters or _xxsubinterpreters
                for suffix in ("", "_sealed"):
                    for label in ("reimport", "from_spec", "create_dynamic", "dotted", "disguised", "ctypes_dotted",
                                  "_testcapi", "_testcapi_dotted", "_testinternalcapi"):
                        self.assertEqual(results.pop(label + suffix), "import_refused", label + suffix)
                    for name in ("_interpreters", "_xxsubinterpreters"):
                        for label in (name, name + "_dotted"):
                            if label + suffix in results:
                                self.assertEqual(results.pop(label + suffix), "import_refused", label + suffix)
                    # reload keeps the wrapper on the one instance, which refuses the call itself.
                    self.assertEqual(results.pop("reload" + suffix), "subprocess_refused", suffix)
                    self.assertEqual(results.pop("cached_import" + suffix), "ok", suffix)
                self.assertEqual(results, {"still_wrapped": True, "loaded": [], "outside": []})

    # Names the dotted-name check missed (Astra's review of #2 at 4fa5835, item 1). CPython finds an extension's init
    # function as PyInit_<last part of the name> with every "-" read as "_", and C ends the name at a NUL. So
    # "zz.-posixsubprocess" and "-posixsubprocess" gave a _posixsubprocess whose fork_exec started /usr/bin/touch
    # outside the roots after arm() and seal(), in every mode, 3.11 did the same for "zz._posixsubprocess" followed by a
    # NUL, and the _ctypes, subinterpreter and test-module aliases got through too. As in FRESH, each helper uses what
    # it loaded, so a load that got through leaves a name in outside/.
    ALIASES = FRESH_HELPERS + r"""
def spellings(name):
    return (("dash", "zz.-" + name[1:]), ("bare_dash", "-" + name[1:]), ("nul", "zz." + name + "\0x"))
def phase(suffix):
    for spelling, alias in spellings("_posixsubprocess"):
        label = "_posixsubprocess_" + spelling + suffix
        attempt(label, lambda: spawn_with(dotted("_posixsubprocess", alias), label))
    for spelling, alias in spellings("_ctypes"):
        attempt("_ctypes_" + spelling + suffix, lambda: dotted("_ctypes", alias).dlsym)
    for name in SUBINTERPRETERS + ["_testcapi"]:
        for spelling, alias in spellings(name):
            label = name + "_" + spelling + suffix
            attempt(label, lambda: run_inside(dotted(name, alias), label))
    for spelling, alias in spellings("_testinternalcapi"):
        attempt("_testinternalcapi_" + spelling + suffix, lambda: dotted("_testinternalcapi", alias))
phase("")
guard.seal()
phase("_sealed")
results["still_wrapped"] = type(sys.modules["_posixsubprocess"].fork_exec) is not type(len)
results["loaded"] = sorted(name for name in sys.modules if name.startswith(("zz", "-")))
results["outside"] = sorted(os.listdir(outside))
"""

    def test_extension_aliases_with_a_dash_or_a_nul_are_refused_in_every_mode(self):
        self.maxDiff = None
        home = make_home(self)
        for mode in MODES:
            results = checks(self, home, setup=self.CHILDREN_SETUP, mode=mode, body=self.ALIASES)
            with self.subTest(mode=mode):
                names = [name for name in ("_interpreters", "_xxsubinterpreters") if name + "_dash" in results]
                self.assertEqual(len(names), 1)             # _interpreters (3.13) or _xxsubinterpreters (3.11)
                # 3.13 itself refuses a NUL in the name (ValueError) before any import event; 3.11 loads the
                # extension, so there the hook must refuse it.
                nul = "import_refused" if sys.version_info[:2] == (3, 11) else "other:ValueError"
                expected = {name + "_" + spelling + suffix: nul if spelling == "nul" else "import_refused"
                            for suffix in ("", "_sealed")
                            for name in ["_posixsubprocess", "_ctypes", "_testcapi", "_testinternalcapi"] + names
                            for spelling in ("dash", "bare_dash", "nul")}
                self.assertEqual(results, dict(expected, still_wrapped=True, loaded=[], outside=[]))

    def test_arm_fails_closed_when_a_child_route_is_already_open(self):
        # The import event fires only for a module not loaded yet, and subprocess binds fork_exec when it is
        # imported, so arm() refuses rather than trust either.
        home = make_home(self)
        for setup, expected in (
                ("import multiprocessing\n", "module_loaded_early"),
                ("import concurrent.futures.process\n", "module_loaded_early"),
                ("import ctypes\n", "module_loaded_early"),
                ("import _ctypes\n", "module_loaded_early"),
                ("import subprocess\nsubprocess._fork_exec = lambda *args: 0\n", "call_replaced_early"),
                ("import _posixsubprocess\noriginal = _posixsubprocess.fork_exec\n"
                 "_posixsubprocess.fork_exec = lambda *args: original(*args)\n", "call_replaced_early"),
                # A subinterpreter runner or a second, unwrapped _posixsubprocess already loaded (Astra's and
                # Nuance's re-reviews of #2): the hook never sees an import that has already happened.
                ("import importlib.util\n__import__(next(name for name in ('_interpreters', '_xxsubinterpreters')"
                 " if importlib.util.find_spec(name)))\n", "module_loaded_early"),
                ("import _testcapi\n", "module_loaded_early"),
                ("import importlib.machinery, importlib.util, sys\n"
                 "loader = importlib.machinery.ExtensionFileLoader('zz._posixsubprocess',"
                 " importlib.util.find_spec('_posixsubprocess').origin)\n"
                 "sys.modules['zz._posixsubprocess'] = importlib.util.module_from_spec("
                 "importlib.util.spec_from_loader('zz._posixsubprocess', loader))\n", "module_loaded_early"),
                # The same under a name CPython reads as the extension's, with a "-" for its "_" or a NUL after it
                # (Astra's review of #2 at 4fa5835, item 1).
                (EARLY_ALIAS % ("zz.-posixsubprocess", "_posixsubprocess", "zz.-posixsubprocess"),
                 "module_loaded_early"),
                (EARLY_ALIAS % ("-posixsubprocess", "_posixsubprocess", "-posixsubprocess"), "module_loaded_early"),
                (EARLY_ALIAS % ("zz.-posixsubprocess", "_posixsubprocess", "zz._posixsubprocess\0x"),
                 "module_loaded_early"),
                (EARLY_ALIAS % ("zz.-ctypes", "_ctypes", "zz.-ctypes"), "module_loaded_early"),
                (EARLY_ALIAS % ("zz.-testcapi", "_testcapi", "zz.-testcapi"), "module_loaded_early"),
                ("import importlib.machinery, importlib.util, sys\n"
                 "NAME = next(name for name in ('_interpreters', '_xxsubinterpreters') if importlib.util.find_spec(name))\n"
                 "loader = importlib.machinery.ExtensionFileLoader('zz.-' + NAME[1:], importlib.util.find_spec(NAME).origin)\n"
                 "sys.modules[loader.name] = importlib.util.module_from_spec("
                 "importlib.util.spec_from_loader(loader.name, loader))\n", "module_loaded_early"),
                ("import _posixsubprocess\n", "ok"),
                ("import subprocess, concurrent.futures\n", "ok")):
            code = ATTEMPT + setup + "attempt('arm', lambda: guard.arm('engine'))\nprint(json.dumps(results))\n"
            result = run_python(code, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["arm"], expected, setup)

    def test_engine_argv_shapes(self):
        state = "/h/.local/state/betangel-suite"
        code = "#c=" + "a" * 22
        ok = guard.engine_argv_ok
        self.assertTrue(ok(["git", "-C", state + "/x", "rev-parse", "--is-inside-work-tree"], (state,), set()))
        self.assertFalse(ok(["git", "-C", state + "/../x", "rev-parse", "--is-inside-work-tree"], (state,), set()))
        self.assertFalse(ok(["git", "-C", "/elsewhere", "rev-parse", "--is-inside-work-tree"], (state,), set()))
        self.assertFalse(ok(["/usr/bin/git", "-C", state, "rev-parse", "--is-inside-work-tree"], (state,), set()))
        self.assertTrue(ok(["/usr/bin/open", "http://127.0.0.1:8765/" + code], (state,), {8765}))
        self.assertFalse(ok(["/usr/bin/open", "http://127.0.0.1:8765/" + code], (state,), set()))
        self.assertFalse(ok(["/usr/bin/open", "http://127.0.0.1:0/" + code], (state,), {0}))
        self.assertFalse(ok(["/usr/bin/open", "http://localhost:8765/" + code], (state,), {8765}))
        self.assertFalse(ok(["/usr/bin/open", "https://127.0.0.1:8765/" + code], (state,), {8765}))
        self.assertFalse(ok(["/usr/bin/open", "http://127.0.0.1:8765/x" + code], (state,), {8765}))
        self.assertFalse(ok(["/usr/bin/open", "-a", "Safari", "http://127.0.0.1:8765/" + code], (state,), {8765}))

    def test_vendor_argv_shapes(self):
        research, deps = "/h/betangel-research", "/h/.local/share/betangel-suite/deps"
        sha = "0123456789abcdef0123456789abcdef01234567"
        partial = deps + "/betangel-research-0123456789ab.partial"
        prefix = list(guard.VENDOR_GIT_PREFIX)
        env = dict(guard.VENDOR_GIT_ENV, HOME="/h")

        def ok(argv, child_env=env):
            return guard.vendor_argv_ok(argv, child_env, research, deps, "/h")

        for rest in (["-C", research, "cat-file", "-e", sha + "^{commit}"],
                     ["-C", research, "merge-base", "--is-ancestor", sha, "refs/heads/main"],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", research, partial],
                     ["-C", partial, "checkout", "--quiet", "--detach", sha],
                     ["-C", partial, "remote", "remove", "origin"]):
            self.assertTrue(ok(prefix + rest), rest)
        for rest in (["-C", research, "fetch"],
                     ["-C", research, "cat-file", "-e", sha],
                     ["-C", research, "merge-base", "--is-ancestor", sha, "main"],
                     ["-C", research, "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main"],
                     ["-C", research, "merge-base", "--is-ancestor", "HEAD", "refs/heads/main"],
                     ["-C", research, "merge-base", sha, "refs/heads/main"],
                     ["-C", partial, "merge-base", "--is-ancestor", sha, "refs/heads/main"],
                     ["-C", research, "status", "--porcelain"],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", "/elsewhere", partial],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", research, deps + "/other"],
                     ["-C", research, "checkout", "--quiet", "--detach", sha],
                     ["-C", partial, "remote", "add", "origin", research],
                     ["-C", research, "worktree", "add", partial]):
            self.assertFalse(ok(prefix + rest), rest)
        self.assertFalse(ok(["/usr/bin/git", "-C", research, "cat-file", "-e", sha + "^{commit}"]))

    def test_vendor_partial_path_in_the_research_clone_is_refused(self):
        # Nuance's PR #2 review, item 2: the partial clone's path text names deps/, but a link on an ancestor can put
        # it in the deploy clone. Refused by name or identity (the firmlink spelling only by identity), as
        # release_argv_ok keeps its repository out of the clone; a real deps root outside the clone passes.
        from tests.test_pin import firmlink_spelling
        home = make_home(self)
        research = roots.research_clone(home)
        inside = os.path.join(research, "vendor-share")
        os.makedirs(inside)
        share, deps = roots.share_dir(home), roots.deps_root(home)
        sha = "0123456789abcdef0123456789abcdef01234567"
        partial = os.path.join(deps, "betangel-research-%s.partial" % sha[:12])
        prefix, env = list(guard.VENDOR_GIT_PREFIX), dict(guard.VENDOR_GIT_ENV, HOME=home)
        shapes = (["clone", "--no-checkout", "--no-hardlinks", "--quiet", research, partial],
                  ["-C", partial, "checkout", "--quiet", "--detach", sha], ["-C", partial, "remote", "remove", "origin"])

        def ok(rest):
            return guard.vendor_argv_ok(prefix + rest, env, research, deps, home)

        os.makedirs(deps)
        self.assertTrue(all(ok(rest) for rest in shapes))
        rmtree(share)
        for target in (inside, firmlink_spelling(inside)):
            os.symlink(target, share)
            for made in (False, True):          # judged at the nearest existing ancestor, then at the path itself
                if made:                        # made where it really is (the guard refuses the firmlink text)
                    os.makedirs(os.path.join(inside, "deps", os.path.basename(partial)))
                for rest in shapes:
                    self.assertFalse(ok(rest), (target, made, rest[:2]))
            rmtree(os.path.join(inside, "deps"))
            os.remove(share)

    def test_vendor_mode_refuses_a_clone_into_the_research_clone(self):
        # The guard's own check, behind the tool's: a synthetic (empty) repository as the clone, with the share
        # directory linked into it. Without the check git clones it into itself.
        home = make_home(self)
        research = roots.research_clone(home)
        os.makedirs(os.path.join(research, "vendor-share"))
        subprocess.run([guard.GIT, "-C", research, "-c", "init.defaultBranch=main", "init", "-q"], check=True,
                       env={"HOME": home, "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null",
                            "GIT_CONFIG_NOSYSTEM": "1", FORBID: "1"}, capture_output=True, timeout=60)
        os.symlink(os.path.join(research, "vendor-share"), roots.share_dir(home))
        results = checks(self, home, mode="vendor", body="""
import subprocess
deps = roots.deps_root()
os.makedirs(deps)
partial = os.path.join(deps, "betangel-research-0123456789ab.partial")
argv = list(guard.VENDOR_GIT_PREFIX) + ["clone", "--no-checkout", "--no-hardlinks", "--quiet", roots.research_clone(),
                                       partial]
attempt("clone", lambda: subprocess.run(argv, env=dict(guard.VENDOR_GIT_ENV, HOME=home), capture_output=True))
results["partial_made"] = os.path.lexists(partial)
""", setup="home = os.environ['HOME']\n")
        self.assertEqual(results, {"clone": "subprocess_refused", "partial_made": False})

    def test_vendor_argv_needs_exactly_the_vendor_environment(self):
        # Nuance's PR #2 review, item 10: GIT_DIR (also when inherited, env=None) detached the clone's HEAD, and
        # GIT_CONFIG_COUNT with an fsmonitor pair ran a command. Only VENDOR_GIT_ENV plus the guard's HOME passes.
        research, deps = "/h/betangel-research", "/h/.local/share/betangel-suite/deps"
        argv = list(guard.VENDOR_GIT_PREFIX) + ["-C", research, "cat-file", "-e", "0" * 40 + "^{commit}"]
        good = dict(guard.VENDOR_GIT_ENV, HOME="/h")
        self.assertTrue(guard.vendor_argv_ok(argv, good, research, deps, "/h"))
        changes = ({"GIT_DIR": research + "/.git"}, {"GIT_WORK_TREE": research},
                   {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "/bin/sh"},
                   {"GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='x'"}, {"GIT_EXEC_PATH": "/x"},
                   {"DEVELOPER_DIR": "/x"}, {"PATH": "/x:/usr/bin:/bin"}, {"GIT_CONFIG_GLOBAL": "/h/.gitconfig"},
                   {"HOME": "/elsewhere"}, {"HOME": None}, {"GIT_CONFIG_NOSYSTEM": None}, {"LANG": None},
                   {"GIT_NO_REPLACE_OBJECTS": None}, {"GIT_GRAFT_FILE": None},
                   {"GIT_GRAFT_FILE": research + "/.git/info/grafts"})
        for change in changes:
            env = {key: value for key, value in dict(good, **change).items() if value is not None}
            self.assertFalse(guard.vendor_argv_ok(argv, env, research, deps, "/h"), change)
        self.assertFalse(guard.vendor_argv_ok(argv, None, research, deps, "/h"))
        # Round-4 review: replace refs, grafts and the per-user attributes file are off in every vendor git child.
        self.assertEqual((good["GIT_NO_REPLACE_OBJECTS"], good["GIT_GRAFT_FILE"]), ("1", "/dev/null"))
        self.assertEqual(guard.VENDOR_GIT_PREFIX[-2:], ("-c", "core.attributesFile=/dev/null"))
        without = argv[:len(guard.VENDOR_GIT_PREFIX) - 2] + argv[len(guard.VENDOR_GIT_PREFIX):]
        self.assertFalse(guard.vendor_argv_ok(without, good, research, deps, "/h"))

    TMP = "/h/.local/state/betangel-suite/tmp"
    REPO = TMP + "/home-x/repo"
    GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", FORBID: "1", "PATH": "/usr/bin:/bin"}

    def test_test_runner_argv_shapes(self):
        interpreters = frozenset(guard.TEST_INTERPRETERS)
        launch_env = dict(self.GIT_ENV, HOME=self.TMP + "/home-x/home")     # a temporary HOME, as tests give one

        def ok(argv, env=self.GIT_ENV):
            return guard.runner_argv_ok(argv, env, interpreters, guard.LAUNCHER, self.TMP, "/h")

        python = "/opt/homebrew/bin/python3.13"
        launch = ROOT + "/bin/_launch.py"
        engine = "import sys\nsys.path.append(%r)\nfrom betangel_suite import guard\nguard.arm('engine')\n" % ROOT
        self.assertTrue(ok([python, "-I", "-S", "-B", "-c", "pass"], launch_env))
        self.assertFalse(ok([python, "-c", "pass"], launch_env))
        self.assertFalse(ok(["/opt/homebrew/bin/python3", "-I", "-S", "-B", "-c", "pass"], launch_env))
        self.assertTrue(ok(["/bin/sh", guard.LAUNCHER, "selfcheck"], launch_env))
        # Every child, not only a launcher one, needs an explicit environment whose HOME keeps it out of the runner's
        # data home (Nuance's re-review of #2, F2; the hook-level cases are in the two tests
        # test_launcher_children_keep_out_of_the_runners_data_home and test_engine_children_...).
        # Lab-Claude's round-5 review: -c code that arms the guard itself, and a launcher after one more interpreter
        # option, passed with env None or the runner's own HOME.
        shapes = [[python, "-I", "-S", "-B", "-c", "pass"], [python, "-I", "-S", "-B", "-c", engine],
                  [python, "-I", "-S", "-B", launch, "selfcheck"], [python, "-I", "-S", "-B", "bin/_launch.py", "test"],
                  ["/opt/homebrew/bin/python3.11", "-I", "-S", "-B", "-c", engine]]
        for extra in (["-X", "utf8"], ["-u"], ["-W", "error"], ["-E"], ["-X", "utf8", "-u"]):
            shapes += [[python, "-I", "-S", "-B", *extra, launch, "vendor"],
                       [python, "-I", "-S", "-B", *extra, "-c", engine]]
        shapes.append(["/bin/sh", guard.LAUNCHER, "selfcheck"])
        for argv in shapes:
            self.assertTrue(ok(argv, launch_env), argv)
            for env in (None, self.GIT_ENV, dict(launch_env, HOME="relative"), dict(launch_env, HOME="/h"),
                        dict(launch_env, HOME="/h/betangel-data/x"), dict(launch_env, HOME="/"),
                        dict(launch_env, HOME="/h/betangel-data/x",
                             TMPDIR="/h/betangel-data/x/.local/state/betangel-suite/tmp"),
                        dict(launch_env, HOME="/h", TMPDIR="/h/betangel-data/tmp"),
                        dict(launch_env, TMPDIR="/h/betangel-data/tmp"),
                        dict(launch_env, SQLITE_TMPDIR="/h/betangel-data/tmp")):
                self.assertFalse(ok(argv, env), (argv, env))
        self.assertFalse(ok(["/bin/sh", "-c", "true"]))
        self.assertTrue(ok(["/usr/bin/git", "-C", self.REPO, "rev-parse", "HEAD"]))
        self.assertFalse(ok(["/usr/bin/git", "status"]))
        self.assertFalse(ok(["/usr/bin/curl", "http://192.0.2.1/"]))

    def test_test_runner_git_shapes(self):
        # Pure predicate only: nothing here is ever run, least of all against the deploy clone.
        repo, research = self.REPO, "/h/betangel-research"

        def ok(argv, env=None):
            return guard.runner_git_ok([guard.GIT, *argv], self.GIT_ENV if env is None else env, self.TMP)

        for argv in (["-C", repo, "-c", "init.defaultBranch=main", "init", "-q", "--template="],
                     ["-C", repo, "add", "-f", "--", "pkg/x.py"], ["-C", repo, "add", "-A"],
                     ["-C", repo, "-c", "user.name=Synthetic", "-c", "user.email=s@example.invalid", "commit", "-q", "-m",
                      "synthetic"],
                     ["-C", repo, "update-index", "--add", "--cacheinfo", "160000,%s,vendor/sub" % ("0" * 40)],
                     ["-C", repo, "check-ignore", "-q", "--no-index", "--", "a/b"],
                     ["-C", repo, "rev-parse", "--verify", "-q", "HEAD"]):
            self.assertTrue(ok(argv), argv)
        for argv in (["-C", research, "status"], ["-C", research, "rev-parse", "HEAD"], ["-C", repo, "status"],
                     ["-C", repo, "fetch"], ["-C", repo, "pull"], ["-C", repo, "push"], ["-C", repo, "remote", "-v"],
                     ["-C", repo, "ls-remote", "https://example.invalid/x"], ["-C", repo, "clone", "https://example.invalid/x"],
                     ["-C", repo, "submodule", "update"], ["-C", repo, "worktree", "add", "x"],
                     ["-C", repo, "-c", "core.fsmonitor=/bin/sh", "add", "-A"], ["-C", repo, "-c", "protocol.allow=always", "init"],
                     ["-C", repo, "-c", "init.defaultBranch", "init"], ["-C", repo, "init", "--separate-git-dir=/elsewhere"],
                     ["-C", repo, "init", "--template=/elsewhere"], ["-C", repo, "add", "--", research + "/x"],
                     ["-C", repo, "add", "--", "../../outside"], ["-C", self.TMP + "/../x", "init"], ["-C", "relative", "init"],
                     ["-C", "/h/elsewhere", "init"], ["init", "-q"], ["--git-dir=" + research + "/.git", "rev-parse"],
                     ["-C", repo, "--exec-path=/x", "init"], ["-C", repo]):
            self.assertFalse(ok(argv), argv)
        self.assertFalse(guard.runner_git_ok([guard.GIT, "-C", repo, "init"], None, self.TMP))
        # The environment is an exact allowlist (Nuance's re-review of #2, F6): the keys test_hygiene's _git_env and
        # test_vendor give, with HOME and TMPDIR under the temp root, pass; any other key or value does not.
        full = dict(self.GIT_ENV, HOME=self.TMP + "/hygiene-x/home", TMPDIR=self.TMP + "/hygiene-x", LANG="en_GB.UTF-8",
                    GIT_AUTHOR_NAME="Synthetic Tester", GIT_AUTHOR_EMAIL="tester@example.invalid",
                    GIT_COMMITTER_NAME="Synthetic Tester", GIT_COMMITTER_EMAIL="tester@example.invalid",
                    GIT_TERMINAL_PROMPT="0")
        self.assertTrue(ok(["-C", repo, "init"], full))
        self.assertTrue(ok(["-C", repo, "init"], {key: full[key] for key in guard.TEST_GIT_ENV}))
        for change in ({"GIT_CONFIG_GLOBAL": None}, {"GIT_CONFIG_NOSYSTEM": None}, {"GIT_CONFIG_GLOBAL": "/h/.gitconfig"},
                       {"GIT_DIR": research + "/.git"}, {"GIT_WORK_TREE": research}, {"GIT_CONFIG_COUNT": "1"},
                       {"GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='x'"}, {"GIT_SSH_COMMAND": "ssh"}, {"GIT_EXEC_PATH": "/x"},
                       {"DEVELOPER_DIR": "/x"}, {"SDKROOT": "/x"}, {"XDG_CONFIG_HOME": "/h/.config"}, {"PAGER": "/bin/sh"},
                       {"EDITOR": "/bin/sh"}, {"DYLD_INSERT_LIBRARIES": "/x"}, {"PYTHONPATH": "/x"},
                       {"PATH": "/x:/usr/bin:/bin"}, {"GIT_TERMINAL_PROMPT": "1"}, {FORBID: None}, {FORBID: "0"},
                       {"HOME": "/h"}, {"HOME": research}, {"HOME": self.TMP + "/../x"}, {"HOME": "relative"},
                       {"TMPDIR": "/private/tmp"}, {"TMPDIR": self.TMP + "/x/"}, {"LANG": "../../x"}, {"LANG": ""}):
            env = {key: value for key, value in dict(full, **change).items() if value is not None}
            self.assertFalse(ok(["-C", repo, "init"], env), change)

    def test_test_runner_children_keep_the_switch_and_a_clean_git_config(self):
        # This process is the test runner: its own guard refuses these before anything starts.
        home = make_home(self)
        env = child_env(home, **{FORBID: None})
        with self.assertRaises(guard.GuardRefusal):
            subprocess.run([PYTHON, "-I", "-S", "-B", "-c", "pass"], env=env, capture_output=True, timeout=30)
        with self.assertRaises(guard.GuardRefusal):
            subprocess.run([guard.GIT, "-C", home, "init", "-q"], env=env, capture_output=True, timeout=30)
        with self.assertRaises(guard.GuardRefusal):     # the switch, but the user's git config
            subprocess.run([guard.GIT, "-C", home, "init", "-q"], env=child_env(home), capture_output=True, timeout=30)
        self.assertFalse(os.path.lexists(os.path.join(home, ".git")))

    def test_test_runner_git_refuses_developer_dir(self):
        # Nuance's re-review of #2, F6: runner_git_ok accepted any non-GIT_ key, and a test-armed child ran /usr/bin/git
        # with DEVELOPER_DIR=<fake>, which made git run <fake>/usr/bin/xcrun. Here a test-mode child with a temporary
        # HOME tries it; the fake xcrun would leave a name in outside/.
        home = make_home(self)
        fake = os.path.join(home, "developer", "usr", "bin")
        os.makedirs(fake)
        os.makedirs(os.path.join(home, "outside"))
        with open(os.path.join(fake, "xcrun"), "w") as handle:
            handle.write("#!/bin/sh\n/usr/bin/touch %s\nexit 1\n" % os.path.join(home, "outside", "xcrun-ran"))
        os.chmod(os.path.join(fake, "xcrun"), 0o755)
        results = checks(self, home, mode="test", setup="import subprocess\n", body="""
home = os.environ["HOME"]
repo = os.path.join(os.environ["TMPDIR"], "repo")
os.mkdir(repo)
env = {"PATH": "/usr/bin:/bin", "HOME": home + "/.local/state/betangel-suite/tmp", "GIT_CONFIG_GLOBAL": "/dev/null",
       "GIT_CONFIG_NOSYSTEM": "1", guard.FORBID_NETWORK_ENV: "1"}
def git(env):
    subprocess.run([guard.GIT, "-C", repo, "init", "-q", "--template="], env=env, capture_output=True, timeout=60)
attempt("developer_dir", lambda: git(dict(env, DEVELOPER_DIR=os.path.join(home, "developer"))))
attempt("sdkroot", lambda: git(dict(env, SDKROOT=os.path.join(home, "developer"))))
attempt("plain", lambda: git(env))
results["repo_made"] = os.path.isdir(os.path.join(repo, ".git"))
results["outside"] = sorted(os.listdir(os.path.join(home, "outside")))
""")
        self.assertEqual(results, {"developer_dir": "subprocess_refused", "sdkroot": "subprocess_refused", "plain": "ok",
                                   "repo_made": True, "outside": []})

    def test_launcher_children_keep_out_of_the_runners_data_home(self):
        # Nuance's re-review of #2, F2: a child of the test runner started with env=None inherits the runner's HOME,
        # the real one under bin/suite test, and an engine-mode child armed with it wrote suite.noindex. The child's
        # own guard judges its roots against its own HOME, so the runner judges a launcher child's HOME, the roots
        # under it and its TMPDIR against the runner's data home, by realpath and identity. Here a test-mode child
        # with a temporary HOME plays the runner; every target is synthetic and inside the temporary tree.
        runner = make_home(self)
        data = roots.data_home(runner)
        os.makedirs(os.path.join(data, "historic-pro"), mode=0o700)
        os.makedirs(os.path.join(data, "lab-state", "state", "betangel-suite", "tmp"), mode=0o700)
        inside = os.path.join(data, "inside")
        os.makedirs(inside, mode=0o700)
        control = make_home(self)
        linked_data, linked_local = make_home(self), make_home(self)
        os.symlink(data, roots.data_home(linked_data))                              # its betangel-data is the runner's
        rmtree(os.path.join(linked_local, ".local"))
        os.symlink(os.path.join(data, "lab-state"), os.path.join(linked_local, ".local"))  # its roots in the data home
        alias = os.path.join(os.path.dirname(control), "alias")
        os.symlink(runner, alias)
        before = sorted(os.listdir(data))
        homes = dict(("spelt_" + name, spelling) for name, spelling in spellings(runner).items())
        homes.update(dotdot=os.path.join(runner, ".local", os.pardir), alias=alias, inside=inside, data_home=data,
                     linked_data=linked_data, linked_local=linked_local)
        envs = {name: child_env(spelled, TMPDIR=roots.tmp_dir("test", control),
                                SQLITE_TMPDIR=roots.tmp_dir("test", control)) for name, spelled in homes.items()}
        envs.update(tmpdir_in_data=child_env(control, TMPDIR=inside, SQLITE_TMPDIR=inside),
                    no_home=child_env(control, HOME=None), relative_home=child_env(control, HOME="home"))
        results = checks(self, runner, mode="test", setup="import subprocess, sys\n", body="""
envs = %r
script = os.path.join(os.path.dirname(guard.LAUNCHER), "_launch.py")
def launch(argv, env):
    result = subprocess.run(argv + ["no-such-command"], env=env, capture_output=True, text=True, timeout=60)
    results["stderr"].add(result.stderr)
results["stderr"] = set()
for name, env in sorted(envs.items()):
    attempt("sh:" + name, lambda: launch(["/bin/sh", guard.LAUNCHER], env))
    attempt("py:" + name, lambda: launch([sys.executable, "-I", "-S", "-B", script], env))
attempt("sh:inherited", lambda: launch(["/bin/sh", guard.LAUNCHER], None))
attempt("py:inherited", lambda: launch([sys.executable, "-I", "-S", "-B", script], None))
# Lab-Claude's round-5 review: one more interpreter option before the script hid it from the old argv[4] check.
for name, extra in (("x_utf8", ["-X", "utf8"]), ("unbuffered", ["-u"]), ("warnings", ["-W", "error"])):
    attempt("py_" + name + ":inherited", lambda: launch([sys.executable, "-I", "-S", "-B", *extra, script], None))
    attempt("py_" + name + ":alias", lambda: launch([sys.executable, "-I", "-S", "-B", *extra, script], envs["alias"]))
    attempt("py_" + name + ":control", lambda: launch([sys.executable, "-I", "-S", "-B", *extra, script],
                                                      envs["control"]))
attempt("interpreter_inherits", lambda: subprocess.run([sys.executable, "-I", "-S", "-B", "-c", "pass"], check=True,
                                                       timeout=60))
results["stderr"] = sorted(results["stderr"])
""" % dict(envs, control=child_env(control)))
        expected = {"interpreter_inherits": "subprocess_refused", "sh:control": "ok", "py:control": "ok",
                    "stderr": ["refused:unknown_command\n"]}
        for name in list(envs) + ["inherited"]:
            expected.update({"sh:" + name: "subprocess_refused", "py:" + name: "subprocess_refused"})
        for name in ("x_utf8", "unbuffered", "warnings"):
            expected.update({"py_%s:inherited" % name: "subprocess_refused", "py_%s:alias" % name: "subprocess_refused",
                             "py_%s:control" % name: "ok"})
        self.assertEqual(results, expected)
        self.assertEqual(sorted(os.listdir(data)), before)
        self.assertEqual(sorted(os.listdir(os.path.join(data, "historic-pro"))), [])
        self.assertFalse(os.path.lexists(roots.data_home(control)))

    def test_engine_children_keep_out_of_the_runners_data_home(self):
        # Lab-Claude's round-5 review of Nuance's re-review of #2, F2: the shape F2 reported is an interpreter child
        # that arms the guard itself, as every engine-policy test child does (-c code calling guard.arm('engine')).
        # Started with env=None, or with the runner's own HOME, it armed engine mode from that HOME and wrote the
        # runner's suite.noindex, because the runner checked launcher children only. Here a test-mode child with a
        # temporary HOME plays the runner, and its data home and suite.noindex are synthetic.
        runner, control = make_home(self), make_home(self)
        for home in (runner, control):
            os.makedirs(os.path.join(roots.data_home(home), "suite.noindex"), mode=0o700)
        code = PRELUDE + ("from betangel_suite import guard\nguard.arm('engine')\nimport os\n"
                          "target = os.path.join(os.environ['HOME'], 'betangel-data', 'suite.noindex', 'written')\n"
                          "with open(target, 'x'):\n    pass\n")
        results = checks(self, runner, mode="test", setup="import subprocess, sys\n", body="""
code, control = %r, %r
def engine(env, *extra):
    subprocess.run([sys.executable, "-I", "-S", "-B", *extra, "-c", code], env=env, check=True, capture_output=True,
                   timeout=60)
attempt("inherited", lambda: engine(None))
attempt("inherited_x_utf8", lambda: engine(None, "-X", "utf8"))
attempt("runner_environ", lambda: engine(dict(os.environ)))
attempt("runner_home", lambda: engine(dict(control, HOME=os.environ["HOME"])))
attempt("control", lambda: engine(control))
""" % (code, child_env(control)))
        self.assertEqual(results, {"inherited": "subprocess_refused", "inherited_x_utf8": "subprocess_refused",
                                   "runner_environ": "subprocess_refused", "runner_home": "subprocess_refused",
                                   "control": "ok"})
        self.assertEqual(os.listdir(os.path.join(roots.data_home(runner), "suite.noindex")), [])
        self.assertEqual(os.listdir(os.path.join(roots.data_home(control), "suite.noindex")), ["written"])

    def test_a_child_gets_exactly_the_environment_the_runner_judged(self):
        # Lab-Claude's recheck of round 5: _check_spawn judged a collapsed copy of a child's environment,
        # {fsdecode(k): fsdecode(v) for k, v in dict(env).items()}, while subprocess and os.posix_spawn hand the child
        # every item and its getenv takes the first of two equal names. A bytes HOME, TMPDIR and SQLITE_TMPDIR put
        # before a temporary HOME's str keys passed the runner's check, and the child armed engine mode from the
        # runner's HOME and wrote its suite.noindex; so did a dict subclass whose items() name the runner's HOME; and
        # a bytes network switch of "0" reached the child. Here a test-mode child with a temporary HOME plays the
        # runner, every data home is synthetic, and each engine child writes a file named after its attempt.
        runner, control = make_home(self), make_home(self)
        for home in (runner, control):
            os.makedirs(os.path.join(roots.data_home(home), "suite.noindex"), mode=0o700)
        code = PRELUDE + ("from betangel_suite import guard\nguard.arm('engine')\nimport os, sys\n"
                          "name = 'written-' + sys.argv[1]\n"
                          "target = os.path.join(os.environ['HOME'], 'betangel-data', 'suite.noindex', name)\n"
                          "with open(target, 'x'):\n    pass\n")
        results = checks(self, runner, mode="test", setup="import subprocess, sys\n", body="""
code, control, switch = %r, %r, %r
def argv(name):
    return [sys.executable, "-I", "-S", "-B", "-c", code, name]
def engine(name, env):
    subprocess.run(argv(name), env=env, check=True, capture_output=True, timeout=60)
def spawn(name, env):
    if os.waitpid(os.posix_spawn(sys.executable, argv(name), env), 0)[1]:
        raise RuntimeError(name)
home, tmp = os.environ["HOME"], os.environ["TMPDIR"]
runner = [(b"HOME", os.fsencode(home)), (b"TMPDIR", os.fsencode(tmp)), (b"SQLITE_TMPDIR", os.fsencode(tmp))]
class Items(dict):
    def items(self):
        return dict(control, HOME=home, TMPDIR=tmp, SQLITE_TMPDIR=tmp).items()
class Text(str):
    pass
attempt("bytes_home_first", lambda: engine("bytes_home_first", dict(runner + list(control.items()))))
attempt("bytes_home_first_posix_spawn", lambda: spawn("posix_spawn", dict(runner + list(control.items()))))
attempt("dict_subclass", lambda: engine("dict_subclass", Items(control)))
attempt("bytes_switch_first", lambda: engine("switch", dict([(os.fsencode(switch), b"0")] + list(control.items()))))
attempt("keys_equal_once_encoded", lambda: engine("encoded", {**control, "\\xc9X": "a", "\\udcc3\\udc89X": "b"}))
attempt("value_not_exactly_str", lambda: engine("value", dict(control, LANG=Text("en_GB.UTF-8"))))
attempt("bytes_value", lambda: engine("bytes_value", dict(control, LANG=b"en_GB.UTF-8")))
attempt("control", lambda: engine("control", control))
""" % (code, child_env(control), FORBID))
        refused = ("bytes_home_first", "bytes_home_first_posix_spawn", "dict_subclass", "bytes_switch_first",
                   "keys_equal_once_encoded", "value_not_exactly_str")
        expected = dict({name: "subprocess_refused" for name in refused}, bytes_value="ok", control="ok")
        self.assertEqual(results, expected)
        self.assertEqual(os.listdir(os.path.join(roots.data_home(runner), "suite.noindex")), [])
        self.assertEqual(sorted(os.listdir(os.path.join(roots.data_home(control), "suite.noindex"))),
                         ["written-bytes_value", "written-control"])

    def test_git_children_get_exactly_the_environment_the_guard_judged(self):
        # The same recheck: a bytes GIT_CONFIG_GLOBAL put before the str one passed the exact allowlists of
        # runner_git_ok and vendor_argv_ok, which saw only the str value, /dev/null, while git read the bytes one. Here
        # the probe config's init.defaultBranch shows whether git read it; vendor's lookup runs in an empty directory.
        home = make_home(self)
        probe = os.path.join(home, "probe.gitconfig")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("[init]\n\tdefaultBranch = probe\n")
        results = checks(self, home, mode="test", setup="import subprocess\n", body="""
probe, tmp = %r, os.environ["TMPDIR"]
env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
       guard.FORBID_NETWORK_ENV: "1"}
def init(name, env):
    repo = os.path.join(tmp, name)
    os.mkdir(repo)
    subprocess.run([guard.GIT, "-C", repo, "init", "-q", "--template="], env=env, check=True, capture_output=True,
                   timeout=60)
def head(name):
    path = os.path.join(tmp, name, ".git", "HEAD")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
dup = dict([(b"GIT_CONFIG_GLOBAL", os.fsencode(probe))] + list(env.items()))
attempt("bytes_global_first", lambda: init("dup", dup))
attempt("plain", lambda: init("plain", env))
results["dup_head"], results["plain_head"] = head("dup"), head("plain")
""" % probe)
        self.assertEqual((results["bytes_global_first"], results["plain"], results["dup_head"]),
                         ("subprocess_refused", "ok", None))
        self.assertNotEqual(results["plain_head"], "ref: refs/heads/probe")
        vendor = make_home(self)
        os.makedirs(roots.research_clone(vendor))
        results = checks(self, vendor, mode="vendor", body="""
import subprocess
env = dict(guard.VENDOR_GIT_ENV, HOME=home)
lookup = list(guard.VENDOR_GIT_PREFIX) + ["-C", roots.research_clone(), "cat-file", "-e", "0" * 40 + "^{commit}"]
dup = dict([(b"GIT_CONFIG_GLOBAL", os.fsencode(%r))] + list(env.items()))
attempt("bytes_global_first", lambda: subprocess.run(lookup, env=dup, capture_output=True, timeout=60))
attempt("dict_subclass", lambda: subprocess.run(lookup, env=type("Env", (dict,), {})(env), capture_output=True,
                                                timeout=60))
attempt("lookup", lambda: subprocess.run(lookup, env=env, capture_output=True, timeout=60))
""" % probe, setup="home = os.environ['HOME']\n")
        self.assertEqual(results, {"bytes_global_first": "subprocess_refused", "dict_subclass": "subprocess_refused",
                                   "lookup": "ok"})

    def test_vendor_mode_refuses_other_git_commands(self):
        home = make_home(self)
        os.makedirs(roots.research_clone(home))
        results = checks(self, home, mode="vendor", body="""
import subprocess
prefix = list(guard.VENDOR_GIT_PREFIX)
env = dict(guard.VENDOR_GIT_ENV, HOME=home)
lookup = prefix + ["-C", roots.research_clone(), "cat-file", "-e", "0" * 40 + "^{commit}"]
attempt("fetch", lambda: subprocess.run(prefix + ["-C", roots.research_clone(), "fetch"], env=env, capture_output=True))
attempt("plain_git", lambda: subprocess.run(["/usr/bin/git", "-C", roots.research_clone(), "status"], env=env,
                                            capture_output=True))
attempt("lookup", lambda: subprocess.run(lookup, env=env, capture_output=True))
attempt("lookup_inherited_env", lambda: subprocess.run(lookup, capture_output=True))
attempt("lookup_git_dir", lambda: subprocess.run(lookup, env=dict(env, GIT_DIR=home), capture_output=True))
""", setup="home = os.environ['HOME']\n")
        self.assertEqual(results, {"fetch": "subprocess_refused", "plain_git": "subprocess_refused", "lookup": "ok",
                                   "lookup_inherited_env": "subprocess_refused", "lookup_git_dir": "subprocess_refused"})


class WriteTests(unittest.TestCase):
    """I-6: writes stay inside the roots; nothing under ~/betangel-data while the suite root is not agreed.

    roots.STATE_ROOT_AGREED is True since Q-N3; the flag-off tests set it to False in the child before arming.
    """

    SETUP = """
home = os.environ["HOME"]
state = roots.state_dir()
outside = os.path.join(home, "outside")
os.makedirs(state, exist_ok=True)
os.makedirs(outside)
with open(os.path.join(outside, "file"), "w") as handle:
    handle.write("synthetic")
os.symlink(outside, os.path.join(state, "link"))
os.makedirs(os.path.join(state, "tree", "a"))
with open(os.path.join(state, "tree", "a", "b"), "w") as handle:
    handle.write("synthetic")
"""

    def test_writes_with_the_suite_root_not_agreed(self):
        home = make_home(self)
        results = checks(self, home, setup=self.SETUP + "roots.STATE_ROOT_AGREED = False\n", body="""
import shutil, sqlite3, tempfile
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
def remove_with_dir_fd():
    fd = os.open(outside, os.O_RDONLY)
    try:
        os.remove("file", dir_fd=fd)
    finally:
        os.close(fd)
def make_temp():
    fd, name = tempfile.mkstemp()
    os.close(fd)
    assert os.path.dirname(name) == os.environ["TMPDIR"]
attempt("write_state", lambda: write(os.path.join(state, "ok.txt")))
attempt("mkdir_state", lambda: os.mkdir(os.path.join(state, "sub")))
attempt("write_outside", lambda: write(os.path.join(home, "outside.txt")))
attempt("os_open_outside", lambda: os.close(os.open(os.path.join(home, "o2"), os.O_WRONLY | os.O_CREAT, 0o600)))
attempt("read_outside", lambda: open(os.path.join(outside, "file")).read())
attempt("mkdir_data_home", lambda: os.mkdir(os.path.join(home, "betangel-data")))
attempt("write_suite_root", lambda: write(os.path.join(home, "betangel-data", "suite.noindex", "x")))
attempt("case_variant", lambda: write(os.path.join(home, "BETANGEL-DATA", "x")))
attempt("rename_out", lambda: os.rename(os.path.join(state, "ok.txt"), os.path.join(home, "moved.txt")))
attempt("remove_outside", lambda: os.remove(os.path.join(outside, "file")))
attempt("remove_outside_dir_fd", remove_with_dir_fd)
attempt("chmod_outside", lambda: os.chmod(os.path.join(outside, "file"), 0o600))
attempt("symlink_escape", lambda: write(os.path.join(state, "link", "escaped.txt")))
attempt("denied_tree", lambda: write(os.path.join(home, "Library", "Application Support", "betangel-research", "betfair", "x")))
attempt("sqlite_outside", lambda: sqlite3.connect(os.path.join(home, "x.sqlite")))
attempt("sqlite_uri", lambda: sqlite3.connect("file:" + os.path.join(home, "u.sqlite"), uri=True))
attempt("sqlite_state", lambda: sqlite3.connect(os.path.join(state, "x.sqlite")).close())
attempt("sqlite_memory", lambda: sqlite3.connect(":memory:").close())
attempt("rmtree_inside", lambda: shutil.rmtree(os.path.join(state, "tree")))
attempt("tempfile", make_temp)
attempt("dev_null", lambda: open(os.devnull, "w").close())
os.chdir(state)
attempt("relative_open", lambda: write("relative.txt"))
attempt("relative_mkdir", lambda: os.mkdir("relative-dir"))
""")
        for name in ("write_state", "mkdir_state", "read_outside", "sqlite_state", "sqlite_memory", "rmtree_inside",
                     "tempfile", "dev_null", "relative_mkdir"):
            self.assertEqual(results[name], "ok", name)
        for name in ("mkdir_data_home", "write_suite_root", "case_variant"):
            self.assertEqual(results[name], "state_root_not_agreed", name)
        for name in ("write_outside", "os_open_outside", "rename_out", "remove_outside", "remove_outside_dir_fd",
                     "chmod_outside", "symlink_escape", "denied_tree", "sqlite_outside", "sqlite_uri", "relative_open"):
            self.assertEqual(results[name], "write_outside_roots", name)
        for name in ("outside.txt", "o2", "moved.txt", "betangel-data", "BETANGEL-DATA", "x.sqlite", "Library"):
            self.assertFalse(os.path.lexists(os.path.join(home, name)), name)
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["file"])

    def test_more_mutations_outside_the_roots(self):
        home = make_home(self)
        results = checks(self, home, setup=self.SETUP + 'os.makedirs(os.path.join(outside, "emptydir"))\n', body="""
victim = os.path.join(outside, "file")
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
attempt("write_state", lambda: write(os.path.join(state, "ok.txt")))
attempt("rmdir_outside", lambda: os.rmdir(os.path.join(outside, "emptydir")))
attempt("link_outside_into_roots", lambda: os.link(victim, os.path.join(state, "alias")))
attempt("link_inside_to_outside", lambda: os.link(os.path.join(state, "ok.txt"), os.path.join(home, "linked")))
attempt("link_inside", lambda: os.link(os.path.join(state, "ok.txt"), os.path.join(state, "ok-link")))
attempt("symlink_outside", lambda: os.symlink(os.path.join(state, "ok.txt"), os.path.join(home, "sym")))
attempt("truncate_outside", lambda: os.truncate(victim, 0))
attempt("chown_outside", lambda: os.chown(victim, os.getuid(), os.getgid()))
attempt("chflags_outside", lambda: os.chflags(victim, 0))
attempt("utime_outside", lambda: os.utime(victim))
attempt("utime_inside", lambda: os.utime(os.path.join(state, "ok.txt")))
""")
        for name in ("write_state", "link_inside", "utime_inside"):
            self.assertEqual(results[name], "ok", name)
        for name in ("rmdir_outside", "link_outside_into_roots", "link_inside_to_outside", "symlink_outside",
                     "truncate_outside", "chown_outside", "chflags_outside", "utime_outside"):
            self.assertEqual(results[name], "write_outside_roots", name)
        with open(os.path.join(home, "outside", "file"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "synthetic")
        self.assertEqual(os.stat(os.path.join(home, "outside", "file")).st_nlink, 1)
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["emptydir", "file"])
        for name in ("linked", "sym"):
            self.assertFalse(os.path.lexists(os.path.join(home, name)), name)

    def test_dot_dot_and_trailing_slash_after_a_link(self):
        # normpath() folds "link/.." and drops a final "/", but the OS resolves both through the link (state/link
        # points at outside/, so state/link/.. is HOME). The guarded process may make such a link itself.
        home = make_home(self)
        setup = self.SETUP + """
for name, link in (("emptydir", "empty"), ("movedir", "movable")):
    os.makedirs(os.path.join(outside, name))
    os.symlink(os.path.join(outside, name), os.path.join(state, link))
"""
        results = checks(self, home, setup=setup, body="""
import sqlite3
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
def mkdir_with_dir_fd():
    fd = os.open(state, os.O_RDONLY)
    try:
        os.mkdir(os.path.join("link", "..", "fd_escaped"), dir_fd=fd)
    finally:
        os.close(fd)
up = os.path.join(state, "link", "..")
attempt("open_dotdot", lambda: write(os.path.join(up, "escaped.txt")))
attempt("mkdir_dotdot", lambda: os.mkdir(os.path.join(up, "escaped_dir")))
attempt("mkdir_dir_fd_dotdot", mkdir_with_dir_fd)
attempt("sqlite_dotdot", lambda: sqlite3.connect(os.path.join(up, "escaped.sqlite")).close())
attempt("rmdir_trailing_slash", lambda: os.rmdir(os.path.join(state, "empty") + "/"))
attempt("rename_trailing_slash", lambda: os.rename(os.path.join(state, "movable") + "/", os.path.join(state, "moved")))
attempt("own_link", lambda: os.symlink(outside, os.path.join(state, "own")))
attempt("open_dotdot_own_link", lambda: write(os.path.join(state, "own", "..", "escaped2.txt")))
attempt("dotdot_inside", lambda: write(os.path.join(state, "tree", "..", "ok.txt")))
attempt("mkdir_trailing_slash_inside", lambda: os.mkdir(os.path.join(state, "newdir") + "/"))
attempt("remove_the_link_itself", lambda: os.remove(os.path.join(state, "empty")))
""")
        for name in ("open_dotdot", "mkdir_dotdot", "mkdir_dir_fd_dotdot", "sqlite_dotdot", "rmdir_trailing_slash",
                     "rename_trailing_slash", "open_dotdot_own_link"):
            self.assertEqual(results[name], "write_outside_roots", name)
        for name in ("own_link", "dotdot_inside", "mkdir_trailing_slash_inside", "remove_the_link_itself"):
            self.assertEqual(results[name], "ok", name)
        self.assertEqual(sorted(os.listdir(home)), [".local", "outside"])
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["emptydir", "file", "movedir"])

    def test_metadata_calls_on_descriptors_are_judged_by_path(self):
        # Nuance's PR #2 review, item 17: fchmod on an O_RDONLY descriptor took a data-home directory to 0755. A
        # read-only open is never checked, so chmod, chown, utime and truncate given a descriptor are now judged by
        # the file's path (F_GETPATH), and refused when it has none.
        for agreed, data_code in ((False, "state_root_not_agreed"), (True, "write_outside_roots")):
            with self.subTest(agreed=agreed):
                self.descriptor_calls(agreed, data_code)

    def descriptor_calls(self, agreed, data_code):
        home = make_home(self)
        historic = os.path.join(roots.data_home(home), "historic-pro")
        os.makedirs(historic, mode=0o700)
        setup = self.SETUP + "roots.STATE_ROOT_AGREED = %r\n" % agreed
        results = checks(self, home, setup=setup, body="""
import stat, tempfile
data_fd = os.open(os.path.join(roots.data_home(), "historic-pro"), os.O_RDONLY)
attempt("fchmod_data_dir", lambda: os.fchmod(data_fd, 0o755))
attempt("chmod_fd_data_dir", lambda: os.chmod(data_fd, 0o755))
attempt("fchown_data_dir", lambda: os.fchown(data_fd, os.getuid(), os.getgid()))
attempt("utime_fd_data_dir", lambda: os.utime(data_fd))
outside_fd = os.open(os.path.join(outside, "file"), os.O_RDONLY)
attempt("fchmod_outside_file", lambda: os.fchmod(outside_fd, 0o644))
attempt("ftruncate_outside_file", lambda: os.ftruncate(outside_fd, 0))
read_end, write_end = os.pipe()
attempt("fchmod_pipe", lambda: os.fchmod(read_end, 0o600))
os.close(write_end)
os.close(read_end)
attempt("fchmod_closed", lambda: os.fchmod(read_end, 0o600))
inside_fd = os.open(os.path.join(state, "ok.txt"), os.O_RDWR | os.O_CREAT, 0o600)
attempt("fchmod_inside", lambda: os.fchmod(inside_fd, 0o600))
attempt("ftruncate_inside", lambda: os.ftruncate(inside_fd, 0))
attempt("utime_fd_inside", lambda: os.utime(inside_fd))
attempt("fchmod_state_dir", lambda: os.fchmod(os.open(state, os.O_RDONLY), 0o700))
attempt("open_descriptor_again", lambda: open(inside_fd, "w", closefd=False).close())
def unlinked_temp_file():
    with tempfile.TemporaryFile() as handle:
        os.fchmod(handle.fileno(), 0o600)
attempt("fchmod_unlinked_temp_file", unlinked_temp_file)
results["data_mode"] = stat.S_IMODE(os.fstat(data_fd).st_mode)
""")
        for name in ("fchmod_data_dir", "chmod_fd_data_dir", "fchown_data_dir", "utime_fd_data_dir"):
            self.assertEqual(results[name], data_code, name)
        for name in ("fchmod_outside_file", "ftruncate_outside_file", "fchmod_pipe", "fchmod_closed"):
            self.assertEqual(results[name], "write_outside_roots", name)
        for name in ("fchmod_inside", "ftruncate_inside", "utime_fd_inside", "fchmod_state_dir",
                     "open_descriptor_again", "fchmod_unlinked_temp_file"):
            self.assertEqual(results[name], "ok", name)
        self.assertEqual(results["data_mode"], 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(historic).st_mode), 0o700)
        with open(os.path.join(home, "outside", "file"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "synthetic")

    def test_calls_without_their_own_audit_event(self):
        # CPython raises no audit event for os.mkfifo or os.mknod; arm() wraps them so that they do.
        for agreed, data_code in ((False, "state_root_not_agreed"), (True, "write_outside_roots")):
            with self.subTest(agreed=agreed):
                self.fifo_and_node_calls(agreed, data_code)

    def fifo_and_node_calls(self, agreed, data_code):
        home = make_home(self)
        os.makedirs(roots.data_home(home), mode=0o700)      # a synthetic ~/betangel-data in the temporary HOME
        setup = self.SETUP + "roots.STATE_ROOT_AGREED = %r\n" % agreed
        results = checks(self, home, setup=setup, body="""
import posix
data = roots.data_home()
def mkfifo_dir_fd():
    fd = os.open(outside, os.O_RDONLY)
    try:
        os.mkfifo("fifo_fd", dir_fd=fd)
    finally:
        os.close(fd)
attempt("mkfifo_outside", lambda: os.mkfifo(os.path.join(home, "fifo_out")))
attempt("mkfifo_data_home", lambda: os.mkfifo(os.path.join(data, "fifo")))
attempt("posix_mkfifo_outside", lambda: posix.mkfifo(os.path.join(home, "fifo_posix")))
attempt("mkfifo_dir_fd_outside", mkfifo_dir_fd)
attempt("mknod_outside", lambda: os.mknod(os.path.join(home, "node_out")))
attempt("mknod_data_home", lambda: os.mknod(os.path.join(data, "node")))
attempt("mkfifo_inside", lambda: os.mkfifo(os.path.join(state, "fifo_in")))
results["wrapped"] = os.mkfifo is posix.mkfifo and os.mkfifo.__module__ == "betangel_suite.guard"
""")
        for name in ("mkfifo_outside", "posix_mkfifo_outside", "mkfifo_dir_fd_outside", "mknod_outside"):
            self.assertEqual(results[name], "write_outside_roots", name)
        for name in ("mkfifo_data_home", "mknod_data_home"):
            self.assertEqual(results[name], data_code, name)
        self.assertEqual(results["mkfifo_inside"], "ok")
        self.assertTrue(results["wrapped"])
        self.assertEqual(os.listdir(roots.data_home(home)), [])
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["file"])
        for name in ("fifo_out", "fifo_posix", "node_out"):
            self.assertFalse(os.path.lexists(os.path.join(home, name)), name)

    def test_sqlite_uri_names_are_refused_whatever_the_uri_flag(self):
        # The event does not say whether URIs are on: without SQLITE_USE_URI, uri=False opens "file::memory:"
        # as a file of that name in the cwd (here outside the roots).
        home = make_home(self)
        results = checks(self, home, setup=self.SETUP, body="""
import sqlite3
os.chdir(outside)
attempt("default", lambda: sqlite3.connect("file::memory:").close())
attempt("uri_false", lambda: sqlite3.connect("file::memory:?mode=rwc", uri=False).close())
attempt("uri_true", lambda: sqlite3.connect("file::memory:", uri=True).close())
attempt("memory", lambda: sqlite3.connect(":memory:").close())
attempt("empty", lambda: sqlite3.connect("").close())
""")
        for name in ("default", "uri_false", "uri_true"):
            self.assertEqual(results[name], "write_outside_roots", name)
        self.assertEqual((results["memory"], results["empty"]), ("ok", "sqlite_connect_refused"))
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["file"])

    def test_sqlite_keeps_temporary_files_in_memory(self):
        # Nuance's PR #2 review, item 15: temp_store=MEMORY was never set, and after a TMPDIR rename plus symlink
        # connect("") opened etilqs_* files outside the roots. SQLite opens its temporary files from C, in whatever
        # temp directory it finds then (/var/tmp or /tmp if TMPDIR is gone), so none may be opened at all. Open
        # descriptors are listed through /dev/fd and named with F_GETPATH; SQLite unlinks a temp file at once, so
        # a directory listing would not show it. The rename and the symlink are refused on their own
        # (root_replace_refused, RootPlacementTests).
        home = make_home(self)
        results = checks(self, home, setup=self.SETUP, body="""
import fcntl, sqlite3, sqlite3.dbapi2
def temp_files():
    found = 0
    for name in os.listdir("/dev/fd"):
        try:
            path = fcntl.fcntl(int(name), fcntl.F_GETPATH, bytes(1024)).split(b"\\0", 1)[0]
        except (OSError, ValueError):
            continue
        found += b"etilqs" in os.path.basename(path)
    return found
def spill(connection):
    connection.execute("CREATE TEMP TABLE t (x TEXT)")
    connection.execute("PRAGMA temp.cache_size = 2")
    connection.executemany("INSERT INTO t VALUES (?)", (("synthetic-%05d" % i + "-" * 400,) for i in range(3000)))
    connection.execute("SELECT x FROM t ORDER BY x DESC").fetchall()
    results["temp_files_" + str(len(results))] = temp_files()
for name, connect, database in (("file", sqlite3.connect, os.path.join(state, "a.sqlite")),
                                ("dbapi2", sqlite3.dbapi2.connect, os.path.join(state, "b.sqlite")),
                                ("memory", sqlite3.connect, ":memory:")):
    connection = connect(database)
    results["temp_store_" + name] = connection.execute("PRAGMA temp_store").fetchone()[0]
    spill(connection)
    connection.close()
attempt("empty_name", lambda: sqlite3.connect(""))
attempt("empty_bytes", lambda: sqlite3.connect(b""))
# The wrapper must fail closed when the setting does not read 2. The guard's connection class (the only one the
# wrapper makes) is given an execute that drops the PRAGMA, then put back.
guarded = [cls for cls in sqlite3.Connection.__subclasses__() if cls.__module__ == "betangel_suite.guard"]
results["guarded_classes"] = len(guarded)
def drop_pragma(self, sql, *args):
    return sqlite3.Connection.execute(self, "SELECT 1" if sql.startswith("PRAGMA temp_store =") else sql, *args)
guarded[0].execute = drop_pragma
attempt("temp_store_not_set", lambda: sqlite3.connect(os.path.join(state, "c.sqlite")))
del guarded[0].execute
attempt("temp_store_set_again", lambda: sqlite3.connect(os.path.join(state, "c.sqlite")).close())
""")
        self.assertEqual((results["guarded_classes"], results["temp_store_set_again"]), (1, "ok"))
        self.assertEqual([value for name, value in results.items() if name.startswith("temp_files_")], [0, 0, 0])
        self.assertEqual([results["temp_store_" + name] for name in ("file", "dbapi2", "memory")], [2, 2, 2])
        for name in ("empty_name", "empty_bytes", "temp_store_not_set"):
            self.assertEqual(results[name], "sqlite_connect_refused", name)

    def test_sqlite_connections_come_only_from_the_wrapper(self):
        # Nuance's PR #2 review, item 16: setlimit(SQLITE_LIMIT_ATTACHED, 10), or calling __init__ again (a new
        # database with the default limits), restored ATTACH and VACUUM INTO outside the roots. Every connection is
        # now the guard's subclass, whose setlimit refuses that limit, and the hook refuses any sqlite3.connect
        # event without the wrapper's token: a direct Connection, a re-initialised one, a connect reference taken
        # before arm(), and a factory argument.
        home = make_home(self)
        setup = self.SETUP + "import sqlite3, _sqlite3, threading\npre_arm_connect = sqlite3.connect\n"
        results = checks(self, home, setup=setup, body="""
attached, vacuumed = os.path.join(home, "attached.db"), os.path.join(home, "vacuumed.db")
def path(name):
    return os.path.join(state, name + ".sqlite")
def attach(connection):
    connection.execute("ATTACH DATABASE ? AS other", (attached,))
def vacuum_into(connection):
    connection.execute("VACUUM INTO ?", (vacuumed,))
inside = sqlite3.connect(path("a"))
results["guarded_class"] = type(inside).__module__ == "betangel_suite.guard"
attempt("setlimit_attached", lambda: inside.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 10))
attempt("setlimit_attached_zero", lambda: inside.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0))
attempt("setlimit_other_limit", lambda: inside.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1000000))
results["limit_after_setlimit"] = inside.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED)
attempt("attach_after_setlimit", lambda: attach(inside))
attempt("reinit", lambda: inside.__init__(path("b")))
attempt("attach_after_reinit", lambda: attach(inside))
attempt("vacuum_into_after_reinit", lambda: vacuum_into(inside))
attempt("direct_connection", lambda: sqlite3.Connection(path("c")))
attempt("direct_guarded_class", lambda: type(inside)(path("d")))
attempt("pre_arm_reference", lambda: pre_arm_connect(path("e")))
attempt("factory_keyword", lambda: sqlite3.connect(path("f"), factory=sqlite3.Connection))
attempt("factory_positional", lambda: sqlite3.connect(path("g"), 5.0, 0, "DEFERRED", True, sqlite3.Connection))
attempt("wrapped_after_refusals", lambda: sqlite3.connect(path("h")).close())
attempt("underscore_module", lambda: _sqlite3.connect(path("i")).close())
attempt("dbapi2_module", lambda: sqlite3.dbapi2.connect(path("j")).close())
attempt("keyword_arguments", lambda: sqlite3.connect(database=path("k"), timeout=5.0, isolation_level=None).close())
def in_thread():
    box = []
    worker = threading.Thread(target=lambda: box.append(sqlite3.connect(path("l")).getlimit(
        sqlite3.SQLITE_LIMIT_ATTACHED)))
    worker.start()
    worker.join()
    assert box == [0], box
attempt("other_thread", in_thread)
inside.close()
results["made"] = sorted(name for name in os.listdir(state) if name.endswith(".sqlite"))
""")
        for path in (os.path.join(home, "attached.db"), os.path.join(home, "vacuumed.db")):
            self.assertFalse(os.path.lexists(path), os.path.basename(path))
        for name in ("attach_after_setlimit", "attach_after_reinit", "vacuum_into_after_reinit"):
            self.assertEqual(results[name], "other:OperationalError", name)
        self.assertEqual(results["setlimit_attached"], "sqlite_limit_refused")
        self.assertEqual(results["setlimit_attached_zero"], "sqlite_limit_refused")
        self.assertEqual((results["setlimit_other_limit"], results["limit_after_setlimit"]), ("ok", 0))
        for name in ("reinit", "direct_connection", "direct_guarded_class", "pre_arm_reference", "factory_keyword",
                     "factory_positional"):
            self.assertEqual(results[name], "sqlite_connect_refused", name)
        for name in ("wrapped_after_refusals", "underscore_module", "dbapi2_module", "keyword_arguments",
                     "other_thread"):
            self.assertEqual(results[name], "ok", name)
        self.assertEqual(results["made"], ["a.sqlite", "h.sqlite", "i.sqlite", "j.sqlite", "k.sqlite", "l.sqlite"])
        self.assertTrue(results["guarded_class"])

    def test_sqlite_cannot_attach_vacuum_into_or_load_extensions(self):
        home = make_home(self)
        results = checks(self, home, setup=self.SETUP, body="""
import sqlite3
inside = sqlite3.connect(os.path.join(state, "a.sqlite"))
memory = sqlite3.connect(":memory:")
memory.execute("CREATE TABLE t (x INTEGER)")
attempt("attach_outside", lambda: inside.execute("ATTACH DATABASE ? AS other", (os.path.join(home, "attached.db"),)))
attempt("attach_inside", lambda: memory.execute("ATTACH DATABASE ? AS other", (os.path.join(state, "b.sqlite"),)))
attempt("vacuum_into_outside", lambda: memory.execute("VACUUM INTO ?", (os.path.join(home, "vacuumed.db"),)))
attempt("enable_extensions", lambda: memory.enable_load_extension(True))
attempt("disable_extensions", lambda: memory.enable_load_extension(False))
attempt("create_table", lambda: inside.execute("CREATE TABLE t (x INTEGER)"))
results["wrapped"] = sqlite3.connect.__module__ == "betangel_suite.guard"
inside.close()
memory.close()
""")
        for name in ("attach_outside", "attach_inside", "vacuum_into_outside"):
            self.assertEqual(results[name], "other:OperationalError", name)
        self.assertEqual(results["enable_extensions"], "dlopen_refused")
        self.assertEqual((results["disable_extensions"], results["create_table"], results["wrapped"]), ("ok", "ok", True))
        for path in (os.path.join(home, "attached.db"), os.path.join(home, "vacuumed.db"),
                     os.path.join(roots.state_dir(home), "b.sqlite")):
            self.assertFalse(os.path.lexists(path), os.path.basename(path))

    def test_writes_with_the_suite_root_agreed(self):
        home = make_home(self)
        os.makedirs(roots.data_home(home), mode=0o700)
        results = checks(self, home, setup=self.SETUP + "roots.STATE_ROOT_AGREED = True\n", body="""
suite = roots.suite_root()
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
attempt("mkdir_suite_root", lambda: os.mkdir(suite, 0o700))
attempt("write_suite_root", lambda: write(os.path.join(suite, "x")))
attempt("write_state", lambda: write(os.path.join(state, "ok.txt")))
attempt("write_data_home", lambda: write(os.path.join(roots.data_home(), "historic.txt")))
attempt("mkdir_data_root", lambda: os.mkdir(os.path.join(roots.data_home(), "historic")))
attempt("write_outside", lambda: write(os.path.join(home, "outside.txt")))
""")
        for name in ("mkdir_suite_root", "write_suite_root", "write_state"):
            self.assertEqual(results[name], "ok", name)
        for name in ("write_data_home", "mkdir_data_root", "write_outside"):
            self.assertEqual(results[name], "write_outside_roots", name)
        self.assertEqual(os.listdir(roots.data_home(home)), ["suite.noindex"])

    def test_only_engine_mode_writes_the_agreed_suite_root(self):
        # The test runner runs with the real HOME, so with the flag on it must still never reach a real
        # ~/betangel-data/suite.noindex; vendor has no use for it either.
        for mode in NON_ENGINE:
            home = make_home(self)
            os.makedirs(roots.data_home(home), mode=0o700)
            results = checks(self, home, mode=mode, setup=self.SETUP + "roots.STATE_ROOT_AGREED = True\n", body="""
suite = roots.suite_root()
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
attempt("mkdir_suite_root", lambda: os.mkdir(suite, 0o700))
attempt("write_suite_root", lambda: write(os.path.join(suite, "x")))
attempt("write_state", lambda: write(os.path.join(state, "ok.txt")))
""")
            self.assertEqual(results, {"mkdir_suite_root": "write_outside_roots",
                                       "write_suite_root": "write_outside_roots", "write_state": "ok"}, mode)
            self.assertEqual(os.listdir(roots.data_home(home)), [], mode)

    def test_uisnap_and_stop_have_the_state_root_alone(self):
        # Nuance's re-review of #2, Q2 conditions 2 and 3, and Astra's: cli.py mapped uisnap (and stop) to engine mode,
        # which can write the suite root. Each now arms a mode of its own, with the state root as its only write root
        # and the state root's tmp/ as its TMPDIR, and starts no child in either phase.
        for mode in ("uisnap", "stop"):
            home = make_home(self)
            os.makedirs(roots.data_home(home), mode=0o700)
            suite_tmp = os.path.join(roots.suite_root(home), "tmp")
            with self.subTest(mode=mode, tmpdir="suite"):    # the engine's TMPDIR is no longer theirs
                self.assertEqual(armed_attempts(self, home, mode=mode, body="pass",
                                                env=child_env(home, TMPDIR=suite_tmp, SQLITE_TMPDIR=suite_tmp)),
                                 {"arm": "tmpdir_mismatch"})
            results = checks(self, home, mode=mode, setup=self.SETUP + "roots.STATE_ROOT_AGREED = True\n", body="""
import sqlite3, subprocess
suite = roots.suite_root()
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
def git():
    subprocess.run(["git", "-C", state, "rev-parse", "--is-inside-work-tree"], capture_output=True, timeout=30)
attempt("mkdir_suite_root", lambda: os.mkdir(suite, 0o700))
attempt("write_suite_root", lambda: write(os.path.join(suite, "x")))
attempt("sqlite_suite_root", lambda: sqlite3.connect(os.path.join(suite, "x.sqlite")).close())
attempt("write_state", lambda: write(os.path.join(state, "ok.txt")))
attempt("sqlite_state", lambda: sqlite3.connect(os.path.join(state, "ok.sqlite")).close())
attempt("git_before_seal", git)
guard.seal()
attempt("git_after_seal", git)
results["mode"] = guard.armed_mode()
""")
            with self.subTest(mode=mode):
                self.assertEqual(results, {"mkdir_suite_root": "write_outside_roots",
                                           "write_suite_root": "write_outside_roots",
                                           "sqlite_suite_root": "write_outside_roots", "write_state": "ok",
                                           "sqlite_state": "ok", "git_before_seal": "subprocess_refused",
                                           "git_after_seal": "subprocess_refused", "mode": mode})
                self.assertEqual(os.listdir(roots.data_home(home)), [])
        # Through bin/suite: with the suite root a link to a data root, which engine mode refuses at arm, stop and uisnap
        # arm their own modes and reach cli.main (their handlers are not built on this branch).
        home = make_home(self)
        historic = os.path.join(roots.data_home(home), "historic-pro")
        os.makedirs(historic, mode=0o700)
        os.symlink(historic, roots.suite_root(home))
        for command, expected in (("stop", "refused:not_implemented\n"), ("uisnap", "refused:not_implemented\n"),
                                  ("selfcheck", "refused:suite_root_misplaced\n")):
            result = run_suite([command], home)
            self.assertEqual((result.returncode, result.stderr), (2, expected), command)
        self.assertEqual(os.listdir(historic), [])


class ReadTests(unittest.TestCase):
    """Reads in ~/betangel-data: refused in every mode but engine (Nuance's re-review of #2, Q2 condition 1).

    Nuance probed that in test and vendor mode reading and listing historic-pro worked; only the append was refused.
    Every check runs in a fresh child with a temporary HOME whose data home holds synthetic files only.
    """

    maxDiff = None

    SETUP = """
home = os.environ["HOME"]
data = roots.data_home()
historic = os.path.join(data, "historic-pro")
outside = os.path.join(home, "outside")
for directory in (historic, os.path.join(data, "locked"), outside, os.path.join(outside, "locked"), roots.state_dir()):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "file"), "w") as handle:
        handle.write("synthetic")
os.symlink(historic, os.path.join(home, "alias"))
for directory in (os.path.join(data, "locked"), os.path.join(outside, "locked")):
    os.chmod(directory, 0)                      # unsearchable: its file can be judged only at the directory
held = os.open(historic, os.O_RDONLY)            # a descriptor opened before arm()
os.chdir(historic)                              # the cwd, before arm(), in the data home
"""

    BODY = """
import glob, shutil
spelt = %r
def read(path):
    with open(path) as handle:
        handle.read()
def os_read(path):
    os.close(os.open(path, os.O_RDONLY))
def walk(top):
    for _ in os.walk(top):
        pass
def fwalk(top):
    os.chdir(outside)               # fwalk opens each directory by its name relative to its parent's descriptor
    for _ in os.fwalk(top):
        pass
attempt("listdir_cwd", lambda: os.listdir())
attempt("scandir_cwd", lambda: list(os.scandir()))
attempt("relative_in_cwd", lambda: read("file"))
attempt("chdir_home", lambda: os.chdir(home))
attempt("relative", lambda: read(os.path.join("betangel-data", "historic-pro", "file")))
attempt("relative_listdir", lambda: os.listdir("betangel-data"))
attempt("open", lambda: read(os.path.join(historic, "file")))
attempt("open_bytes", lambda: read(os.fsencode(os.path.join(historic, "file"))))
attempt("os_open", lambda: os_read(os.path.join(historic, "file")))
attempt("open_directory", lambda: os_read(historic))
attempt("open_data_home", lambda: os_read(data))
attempt("alias", lambda: read(os.path.join(home, "alias", "file")))
for name, path in spelt.items():
    attempt("spelt_" + name, lambda: read(os.path.join(path, "file")))
    attempt("spelt_listdir_" + name, lambda: os.listdir(path))
attempt("behind_locked", lambda: read(os.path.join(data, "locked", "file")))
attempt("listdir", lambda: os.listdir(historic))
attempt("listdir_data_home", lambda: os.listdir(data))
attempt("scandir", lambda: list(os.scandir(historic)))
attempt("listdir_descriptor", lambda: os.listdir(held))      # judged by the descriptor's F_GETPATH path
attempt("scandir_descriptor", lambda: list(os.scandir(held)))
attempt("glob", lambda: glob.glob(os.path.join(historic, "*")))
attempt("walk_home", lambda: walk(home))
attempt("fwalk_home", lambda: fwalk(home))
attempt("copyfile", lambda: shutil.copyfile(os.path.join(historic, "file"), os.path.join(roots.state_dir(), "copy")))
attempt("chdir", lambda: os.chdir(historic))
attempt("fchdir", lambda: os.fchdir(held))
os.chdir(home)
# Controls, the same in every mode: outside the data home, its name in a listing of HOME, and stat-level calls.
attempt("outside_open", lambda: read(os.path.join(outside, "file")))
attempt("outside_listdir", lambda: os.listdir(outside))
attempt("state_open", lambda: read(os.path.join(roots.state_dir(), "file")))
results["home_listing"] = sorted(os.listdir(home))
attempt("stat", lambda: os.stat(os.path.join(historic, "file")))
attempt("outside_locked", lambda: read(os.path.join(outside, "locked", "file")))
attempt("nul", lambda: read(os.path.join(historic, "file") + "\\0x"))
"""

    REFUSED = ("listdir_cwd", "scandir_cwd", "relative_in_cwd", "relative", "relative_listdir", "open", "open_bytes",
               "os_open", "open_directory", "open_data_home", "alias", "behind_locked", "listdir", "listdir_data_home",
               "scandir", "listdir_descriptor", "scandir_descriptor", "glob", "walk_home", "fwalk_home", "copyfile",
               "chdir", "fchdir")

    def test_reads_in_the_data_home_are_refused_outside_engine_mode(self):
        for mode in MODES:
            home = make_home(self)
            historic = os.path.join(roots.data_home(home), "historic-pro")
            os.makedirs(historic)                                   # for spellings(); the child fills it
            spelt = {name: path for name, path in spellings(historic).items() if name != "plain"}
            for locked in (os.path.join(roots.data_home(home), "locked"), os.path.join(home, "outside", "locked")):
                self.addCleanup(lambda path=locked: os.path.isdir(path) and os.chmod(path, 0o700))
            results = checks(self, home, mode=mode, setup=self.SETUP, body=self.BODY % spelt)
            with self.subTest(mode=mode):
                self.assertEqual(results.pop("home_listing"), [".local", "alias", "betangel-data", "outside"])
                expected = {"chdir_home": "ok", "outside_open": "ok", "outside_listdir": "ok", "state_open": "ok",
                            "stat": "ok", "outside_locked": "other:PermissionError", "nul": "other:ValueError"}
                names = list(self.REFUSED) + ["spelt_" + name for name in spelt] + ["spelt_listdir_" + name
                                                                                     for name in spelt]
                for name in names:
                    expected[name] = "data_home_read_refused" if mode != "engine" else "ok"
                if mode == "engine":                                # engine mode reads as before (Phase 1a)
                    expected["behind_locked"] = "other:PermissionError"
                self.assertEqual(results, expected)
                self.assertGreaterEqual(len(spelt), 1)              # the firmlink spelling, at least, on the lab

    def test_reads_judged_through_an_unsearchable_directory(self):
        # roots.lies_in_for_read judges a path whose stat fails (no search permission on the way) at its nearest
        # existing ancestor, so a firmlink spelling into the data home through such a directory is still refused,
        # while one outside the data home is left to fail with its own error.
        home = make_home(self)
        data = roots.data_home(home)
        locked = os.path.join(data, "locked")
        outside = os.path.join(home, "outside", "locked")
        for directory in (locked, outside):
            os.makedirs(directory)
            self.addCleanup(os.chmod, directory, 0o700)
            os.chmod(directory, 0)
        for path, expected in ((FIRMLINK + os.path.realpath(locked) + "/x", True), (locked + "/x", True),
                               (FIRMLINK + os.path.realpath(outside) + "/x", False), (outside + "/x", False)):
            self.assertIs(roots.lies_in_for_read(path, data, "data_home_read_refused"), expected, path)
        missing = os.path.join(home, "no-such-home", "betangel-data")
        self.assertFalse(roots.lies_in_for_read(outside + "/x", missing, "data_home_read_refused"))
        os.chmod(os.path.dirname(data), 0o000)                  # the data home itself cannot be looked at
        self.addCleanup(os.chmod, os.path.dirname(data), 0o700)
        with self.assertRaises(SuiteError) as caught:
            roots.lies_in_for_read("/private/var/x", data, "data_home_read_refused")
        self.assertEqual(caught.exception.code, "data_home_read_refused")


FIRMLINK = "/System/Volumes/Data"       # macOS: the data volume, under which /Users is a firmlink

PLACEMENT = ATTEMPT + """
import sqlite3
roots.STATE_ROOT_AGREED = %(agreed)r
attempt("arm", lambda: guard.arm(%(mode)r))
def write(path):
    with open(path, "w") as handle:
        handle.write("synthetic")
if results["arm"] == "ok":
    attempt("mkdir_state", lambda: os.makedirs(roots.state_dir(), exist_ok=True))
    for label, path in %(writes)r:
        attempt("open:" + label, lambda: write(path))
        attempt("sqlite:" + label, lambda: sqlite3.connect(path + ".sqlite").close())
print(json.dumps(results))
"""


def spellings(target):
    """{name: path} for the existing directory target: as written, and every other spelling this machine resolves to
    the same directory that realpath leaves as it is (the data-volume firmlink, /.vol/<dev>/<ino>, another case)."""
    info = os.stat(target)
    real = os.path.realpath(target)
    found = {"plain": target}
    for name, spelling in (("firmlink", FIRMLINK + real), ("vol", "/.vol/%d/%d" % (info.st_dev, info.st_ino)),
                           ("case", target.replace("betangel-data", "BETANGEL-DATA"))):
        try:
            if spelling != target and os.path.samestat(os.stat(spelling), info):
                found[name] = spelling
        except OSError:
            pass
    return found


class RootPlacementTests(unittest.TestCase):
    """I-6: arm() refuses a write root that the file system puts in, around or onto ~/betangel-data.

    Nuance's PR #2 review, item 1: with ~/.local/state linked to betangel-data/lab-state, open, sqlite3.connect and
    write_new landed there and bin/suite test made lab-state/betangel-suite/tmp; with suite.noindex linked to
    historic-pro, writes landed in historic-pro. Every case here uses a temporary HOME and a synthetic data home.
    The other spellings (firmlink, /.vol, another case) defeat a text check, so the identity walk must see them.
    """

    def placement(self, home, *, agreed, mode="engine", writes=(), env=None, relayed=False):
        """The child's results. relayed: started by an unguarded relay with a HOME of its own, for a HOME the test
        runner refuses to hand a child itself (one whose placement cannot be judged; guard.runner_argv_ok)."""
        code = PLACEMENT % {"agreed": agreed, "mode": mode, "writes": list(writes)}
        if relayed:
            returncode, stdout, stderr = run_relayed([PYTHON, "-I", "-S", "-B", "-c", PRELUDE + code],
                                                     child_env(home) if env is None else env, home,
                                                     relay_home=make_home(self))
        else:
            result = run_python(code, home, env=env)
            returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
        self.assertEqual(returncode, 0, stderr)
        return json.loads(stdout.strip().splitlines()[-1])

    def data_dir(self, home, name):
        path = os.path.join(roots.data_home(home), name)
        os.makedirs(path, mode=0o700)
        return path

    def replace_with_link(self, path, target):
        rmtree(path)
        os.symlink(target, path)

    def test_state_root_linked_into_the_data_home(self):
        for name in ("plain", "firmlink", "vol", "case", "alias"):
            home = make_home(self)
            lab = self.data_dir(home, "lab-state")
            if name == "alias":                         # a link to a link: realpath sees through both
                os.symlink(roots.data_home(home), os.path.join(home, "alias"))
                target = os.path.join(home, "alias", "lab-state")
            else:
                target = spellings(lab).get(name)
            if target is None:
                continue                                # this machine has no such spelling
            self.replace_with_link(os.path.join(home, ".local", "state"), target)
            writes = [("state", os.path.join(roots.state_dir(home), "x"))]
            cases = [(agreed, mode) for agreed in (False, True) for mode in MODES]
            for agreed, mode in cases if name == "plain" else [(False, "engine"), (True, "engine")]:
                with self.subTest(spelling=name, agreed=agreed, mode=mode):
                    results = self.placement(home, agreed=agreed, mode=mode, writes=writes)
                    self.assertEqual(results, {"arm": "root_overlaps_data_home"})
                    self.assertEqual(os.listdir(lab), [])

    def test_roots_that_equal_or_contain_the_data_home(self):
        for kind in ("equal", "contain"):
            home = make_home(self)
            data = self.data_dir(home, "historic-pro")
            target = os.path.dirname(data) if kind == "equal" else home
            for name, spelling in spellings(target).items():
                state = roots.state_dir(home)
                self.replace_with_link(state, spelling)
                writes = [("data", os.path.join(data, "x"))]
                for agreed in (False, True):
                    with self.subTest(kind=kind, spelling=name, agreed=agreed):
                        results = self.placement(home, agreed=agreed, writes=writes)
                        self.assertEqual(results, {"arm": "root_overlaps_data_home"})
                        self.assertEqual(os.listdir(data), [])
                os.remove(state)

    def test_data_home_linked_into_a_root(self):
        home = make_home(self)
        inside = os.path.join(roots.state_dir(home), "data")
        os.makedirs(os.path.join(inside, "historic-pro"))
        elsewhere = os.path.join(home, "elsewhere")
        os.makedirs(elsewhere)
        targets = dict(spellings(inside))
        targets.pop("case", None)
        vol = spellings(elsewhere).get("vol")
        if vol is not None:
            targets["vol_elsewhere"] = vol               # its ancestors could only be found by looking inside it
        for name, spelling in targets.items():
            os.symlink(spelling, roots.data_home(home))
            for agreed in (False, True):
                with self.subTest(spelling=name, agreed=agreed):
                    results = self.placement(home, agreed=agreed)
                    self.assertEqual(results, {"arm": "root_overlaps_data_home"})
            os.remove(roots.data_home(home))
        self.assertEqual(os.listdir(os.path.join(inside, "historic-pro")), [])
        self.assertEqual(os.listdir(elsewhere), [])

    def test_suite_root_linked_to_a_data_root(self):
        home = make_home(self)
        historic = self.data_dir(home, "historic-pro")
        elsewhere = os.path.join(home, "elsewhere")
        os.makedirs(elsewhere)
        suite = roots.suite_root(home)
        writes = [("suite", os.path.join(suite, "x")), ("historic", os.path.join(historic, "y"))]
        targets = dict(spellings(historic), elsewhere=elsewhere)
        for name, spelling in targets.items():
            os.symlink(spelling, suite)
            with self.subTest(spelling=name):
                self.assertEqual(self.placement(home, agreed=True, writes=writes), {"arm": "suite_root_misplaced"})
            os.remove(suite)
        with open(suite, "w") as handle:
            handle.write("synthetic")
        self.assertEqual(self.placement(home, agreed=True), {"arm": "suite_root_misplaced"})
        os.remove(suite)
        os.symlink(historic, suite)
        for mode in NON_ENGINE:                 # the suite root is no write root of theirs
            with self.subTest(mode=mode):
                self.assertEqual(self.placement(home, agreed=True, mode=mode, writes=writes),
                                 {"arm": "ok", "mkdir_state": "ok", "open:suite": "write_outside_roots",
                                  "sqlite:suite": "write_outside_roots", "open:historic": "write_outside_roots",
                                  "sqlite:historic": "write_outside_roots"})
        self.assertEqual(os.listdir(historic), [])
        self.assertEqual(os.listdir(elsewhere), [])

    def test_data_home_behind_a_link_with_a_real_suite_root(self):
        # The control: a data home that is itself a link (another volume, say) is fine, and so is its real
        # suite.noindex, a real directory at exactly realpath(data home)/suite.noindex.
        home = make_home(self)
        external = os.path.join(home, "external", "betangel-data")
        os.makedirs(os.path.join(external, "suite.noindex"))
        os.symlink(external, roots.data_home(home))
        writes = [("suite", os.path.join(roots.suite_root(home), "x"))]
        self.assertEqual(self.placement(home, agreed=True, writes=writes),
                         {"arm": "ok", "mkdir_state": "ok", "open:suite": "ok", "sqlite:suite": "ok"})
        self.assertEqual(sorted(os.listdir(os.path.join(external, "suite.noindex"))), ["x", "x.sqlite"])
        self.assertEqual(self.placement(home, agreed=False, writes=writes),
                         {"arm": "ok", "mkdir_state": "ok", "open:suite": "state_root_not_agreed",
                          "sqlite:suite": "state_root_not_agreed"})

    def test_a_placement_that_cannot_be_judged_is_refused(self):
        # The guard-paths review: check_placement refuses "also when that cannot be judged", but a failed stat read
        # as a missing name. Here the data home links to vault/data, and vault has no search permission when arm()
        # runs, so neither the data home nor the state root can be stat()ed (EACCES), and the state root's link is
        # spelt through the firmlink, which the text check does not see. arm() passed, and once vault was
        # searchable again every write in the state root landed in vault/data/lab-state, in realpath(data home).
        # The test runner refuses to start a child with this HOME itself (its placement cannot be judged against the
        # runner's data home either), so an unguarded relay starts each one.
        home = make_home(self)
        vault = os.path.join(home, "vault")
        lab = os.path.join(vault, "data", "lab-state")
        os.makedirs(os.path.join(vault, "data", "historic-pro"))
        os.rename(os.path.join(home, ".local", "state"), lab)
        os.symlink(os.path.join(vault, "data"), roots.data_home(home))
        before = sorted(os.listdir(os.path.join(lab, "betangel-suite")))
        share_tmp = os.path.join(roots.share_dir(home), "tmp")      # a TMPDIR vendor may use, outside the vault
        os.makedirs(share_tmp)
        self.addCleanup(os.chmod, vault, 0o700)
        for name, target in spellings(lab).items():
            os.symlink(target, os.path.join(home, ".local", "state"))
            os.chmod(vault, 0)
            try:
                for agreed, mode in ((True, "test"), (True, "vendor"), (False, "engine"), (True, "engine")):
                    with self.subTest(spelling=name, agreed=agreed, mode=mode):
                        results = self.placement(home, agreed=agreed, mode=mode, relayed=True)
                        # TMPDIR, in the state root, cannot be looked at either, so arm() may refuse it first
                        # (tmpdir_mismatch); the engine with the suite root agreed may be refused first for its
                        # suite root, which cannot be lstat()ed at realpath(data home)/suite.noindex.
                        codes = {"root_overlaps_data_home", "tmpdir_mismatch"}
                        if agreed and mode == "engine":
                            codes.add("suite_root_misplaced")
                        self.assertIn(results.get("arm"), codes)
                        self.assertEqual(list(results), ["arm"])
                with self.subTest(spelling=name, mode="vendor", tmpdir="share"):
                    # With TMPDIR in the share root, only the state root's placement is left to refuse.
                    results = self.placement(home, agreed=True, mode="vendor", relayed=True,
                                             env=child_env(home, TMPDIR=share_tmp, SQLITE_TMPDIR=share_tmp))
                    self.assertEqual(results, {"arm": "root_overlaps_data_home"})
                for agreed in (False, True):
                    with self.subTest(spelling=name, check_placement=True, agreed=agreed):
                        with mock.patch.object(roots, "STATE_ROOT_AGREED", agreed):
                            with self.assertRaises(SuiteError) as caught:
                                roots.check_placement(roots.state_dir(home), home)
                        self.assertEqual(caught.exception.code, "root_overlaps_data_home")
            finally:
                os.chmod(vault, 0o700)
                os.remove(os.path.join(home, ".local", "state"))
        self.assertEqual(sorted(os.listdir(os.path.join(lab, "betangel-suite"))), before)
        # The control: a root behind a directory in the data home that cannot be searched was already refused (the
        # ancestor walk falls back to the text parent).
        locked = os.path.join(vault, "data", "locked")
        os.makedirs(locked)
        os.rename(lab, os.path.join(locked, "lab-state"))
        os.symlink(FIRMLINK + os.path.realpath(locked) + "/lab-state", os.path.join(home, ".local", "state"))
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o700)
        self.assertEqual(self.placement(home, agreed=True, mode="vendor", relayed=True,
                                        env=child_env(home, TMPDIR=share_tmp, SQLITE_TMPDIR=share_tmp)),
                         {"arm": "root_overlaps_data_home"})

    def test_no_link_or_rename_takes_the_place_of_a_root_or_tmpdir(self):
        # The guard allowed os.symlink(historic-pro, suite.noindex): a write in the roots, as text, that steers the
        # next process. A link, hard link or rename may not put a name where a root or TMPDIR is, nor move one away.
        # Links elsewhere in the roots stay allowed (the own-link design of test_dot_dot_and_trailing_slash...).
        home = make_home(self)
        historic = self.data_dir(home, "historic-pro")
        setup = "roots.STATE_ROOT_AGREED = True\n"
        results = checks(self, home, setup=setup, body="""
home = os.environ["HOME"]
state, suite, tmp = roots.state_dir(), roots.suite_root(), os.environ["TMPDIR"]
historic = os.path.join(roots.data_home(), "historic-pro")
moved = os.path.join(state, "moved")
with open(os.path.join(state, "file"), "w") as handle:
    handle.write("synthetic")
attempt("symlink_onto_suite_root", lambda: os.symlink(historic, suite))
attempt("staged_link", lambda: os.symlink(historic, os.path.join(state, "staged")))
attempt("rename_link_onto_suite_root", lambda: os.rename(os.path.join(state, "staged"), suite))
attempt("replace_link_onto_suite_root", lambda: os.replace(os.path.join(state, "staged"), suite))
attempt("hard_link_onto_suite_root", lambda: os.link(os.path.join(state, "file"), suite))
attempt("symlink_onto_tmpdir", lambda: os.symlink(historic, tmp))
attempt("rename_tmpdir_away", lambda: os.rename(tmp, moved))
attempt("rename_tmpdir_trailing_slash", lambda: os.rename(tmp + "/", moved))
attempt("rename_tmpdir_other_case", lambda: os.rename(os.path.join(state, "TMP"), moved))
attempt("mkdir_suite_root", lambda: os.mkdir(suite, 0o700))
attempt("rename_state_root_away", lambda: os.rename(state, os.path.join(suite, "state")))
attempt("rename_suite_root_away", lambda: os.rename(suite, os.path.join(state, "suite")))
attempt("own_link", lambda: os.symlink(historic, os.path.join(state, "own")))
attempt("rename_own_link", lambda: os.rename(os.path.join(state, "own"), os.path.join(state, "own2")))
attempt("rename_inside_tmpdir", lambda: os.rename(os.path.join(state, "file"), os.path.join(tmp, "file")))
results["suite_is_link"] = os.path.islink(suite)
results["tmp_is_dir"] = os.path.isdir(tmp) and not os.path.islink(tmp)
""")
        for name in ("symlink_onto_suite_root", "rename_link_onto_suite_root", "replace_link_onto_suite_root",
                     "hard_link_onto_suite_root", "symlink_onto_tmpdir", "rename_tmpdir_away",
                     "rename_tmpdir_trailing_slash", "rename_tmpdir_other_case", "rename_state_root_away",
                     "rename_suite_root_away"):
            self.assertEqual(results[name], "root_replace_refused", name)
        for name in ("staged_link", "mkdir_suite_root", "own_link", "rename_own_link", "rename_inside_tmpdir"):
            self.assertEqual(results[name], "ok", name)
        self.assertEqual((results["suite_is_link"], results["tmp_is_dir"]), (False, True))
        self.assertEqual(os.listdir(historic), [])

    def test_no_directory_between_a_root_and_tmpdir_moves_away(self):
        # The guard-paths review: arm() accepts a TMPDIR anywhere in a write root, not only <root>/tmp, but only
        # TMPDIR itself was a slot. Renaming a directory between the root and TMPDIR moved TMPDIR away (as renaming
        # run/ moved the lock, 6aeb1d5), and a link put in its place made TMPDIR resolve outside the roots, where
        # SQLite would put its temporary files if a PRAGMA set temp_store back to FILE.
        home = make_home(self)
        state = roots.state_dir(home)
        tmp = os.path.join(state, "nest", "deeper", "tmp")
        os.makedirs(tmp)
        os.makedirs(os.path.join(state, "nest", "beside"))
        os.makedirs(os.path.join(home, "outside"))
        results = armed_attempts(self, home, mode="test", env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp), body="""
state, tmp, outside = roots.state_dir(), os.environ["TMPDIR"], os.path.join(os.environ["HOME"], "outside")
for label, path in (("nest", os.path.join(state, "nest")), ("nest_other_case", os.path.join(state, "NEST")),
                    ("deeper", os.path.join(state, "nest", "deeper")), ("tmpdir", tmp)):
    attempt("rename_" + label, lambda: os.rename(path, path + "-moved"))
    attempt("link_onto_" + label, lambda: os.symlink(outside, path))
attempt("rename_beside", lambda: os.rename(os.path.join(state, "nest", "beside"), os.path.join(state, "beside")))
attempt("mkdir_in_tmpdir", lambda: os.mkdir(os.path.join(tmp, "sub")))
results["tmpdir_in_place"] = os.path.realpath(tmp) == os.path.join(os.path.realpath(state), "nest", "deeper", "tmp")
""")
        expected = {"arm": "ok", "rename_beside": "ok", "mkdir_in_tmpdir": "ok", "tmpdir_in_place": True}
        for label in ("nest", "nest_other_case", "deeper", "tmpdir"):
            expected.update({"rename_" + label: "root_replace_refused", "link_onto_" + label: "root_replace_refused"})
        self.assertEqual(results, expected)
        self.assertEqual(os.listdir(os.path.join(home, "outside")), [])

    def test_a_tmpdir_with_a_link_below_its_root_is_refused(self):
        # The guard-paths review: TMPDIR a link in the state root to <state>/real-tmp was accepted (I-2 allowed links
        # that resolve inside the root), but only where it resolved was a slot: the link could be removed and one to
        # outside the roots put in its place. A link to a deeper directory, or a link on a directory between the
        # root and TMPDIR, left a directory no slot held on the way (lab-Claude's variants). arm() now refuses a link
        # from the root down to TMPDIR (tmpdir_mismatch), as cli.main's ensure_dir already did for every command but
        # stop and vendor. A link above the root stays allowed (the control at the end).
        def layout(home, name):
            """TMPDIR, and the name below the state root whose replacement would move it."""
            state, tmp = roots.state_dir(home), roots.tmp_dir("test", home)
            os.rmdir(tmp)
            if name in ("link", "relative_link"):
                os.mkdir(os.path.join(state, "real-tmp"))
                os.symlink(os.path.join(state, "real-tmp") if name == "link" else "real-tmp", tmp)
                return tmp, tmp
            if name == "link_to_deeper":
                os.makedirs(os.path.join(state, "x", "real-tmp"))
                os.symlink(os.path.join(state, "x", "real-tmp"), tmp)
                return tmp, os.path.join(state, "x")
            if name == "link_between":
                os.makedirs(os.path.join(state, "b", "tmp"))
                os.symlink(os.path.join(state, "b"), os.path.join(state, "a"))
                return os.path.join(state, "a", "tmp"), os.path.join(state, "a")
            os.symlink(os.path.join(state, "missing"), tmp)                       # dangling
            return tmp, tmp

        for mode in MODES:
            for name in ("link", "relative_link", "link_to_deeper", "link_between", "dangling"):
                home = make_home(self)
                os.makedirs(os.path.join(home, "outside"))
                tmp, swap = layout(home, name)
                results = armed_attempts(self, home, mode=mode, env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp),
                                         body="""
swap, outside = %r, os.path.join(os.environ["HOME"], "outside")
attempt("move_away", lambda: os.remove(swap) if os.path.islink(swap) else os.rename(swap, swap + "-moved"))
attempt("link_in_place", lambda: os.symlink(outside, swap))
results["tmpdir_in_state"] = roots.within(os.path.realpath(os.environ["TMPDIR"]),
                                          os.path.realpath(roots.state_dir()))
""" % swap)
                with self.subTest(mode=mode, layout=name):
                    self.assertEqual(results, {"arm": "tmpdir_mismatch"})
        # The control: the state root itself a link (another volume, say), with a real tmp/ in it.
        home = make_home(self)
        state = roots.state_dir(home)
        elsewhere = os.path.join(home, "elsewhere", "betangel-suite")
        os.makedirs(os.path.dirname(elsewhere))
        os.rename(state, elsewhere)
        os.symlink(elsewhere, state)
        results = armed_attempts(self, home, mode="test", body="""
tmp = os.environ["TMPDIR"]
attempt("write_in_tmpdir", lambda: open(os.path.join(tmp, "x"), "w").close())
attempt("rename_tmpdir", lambda: os.rename(tmp, tmp + "-moved"))
""")
        self.assertEqual(results, {"arm": "ok", "write_in_tmpdir": "ok", "rename_tmpdir": "root_replace_refused"})

    def test_the_realdata_lock_is_never_removed_moved_or_replaced(self):
        # runmarker.py: the suite makes run/realdata.lock once and never unlinks it, since a holder of the old file
        # and Nuance's wrapper locking a new one would not exclude each other. Every mode refuses, however the name
        # is spelt; other files in run/ stay removable. Renaming run/ itself moves the lock with it and splits it the
        # same way (round-4 review), so run/ may not be moved away or replaced either, nor a name put where it is
        # while it is missing.
        refused = ("remove", "unlink", "unlink_dir_fd", "unlink_other_case", "unlink_dot_dot", "rename_away",
                   "rename_onto", "replace_onto", "hard_link_onto", "symlink_onto", "rmtree_run",
                   "rename_run_away", "replace_run_away", "rename_run_other_case", "rename_run_trailing_slash",
                   "move_run_away", "rename_dir_onto_run", "symlink_onto_run")
        for mode in MODES:
            home = make_home(self)
            os.makedirs(roots.run_dir(home), 0o700)
            open(os.path.join(roots.run_dir(home), "realdata.lock"), "w").close()
            results = checks(self, home, mode=mode, body="""
import shutil
run = roots.run_dir()
state = os.path.dirname(run)
lock, other, spare = (os.path.join(run, name) for name in ("realdata.lock", "other", "spare"))
for path in (other, spare):
    open(path, "w").close()
empty = os.path.join(state, "empty")
os.mkdir(empty)
info = os.stat(lock)
fd = os.open(run, os.O_RDONLY)
attempt("remove", lambda: os.remove(lock))
attempt("unlink", lambda: os.unlink(lock))
attempt("unlink_dir_fd", lambda: os.unlink("realdata.lock", dir_fd=fd))
attempt("unlink_other_case", lambda: os.unlink(os.path.join(run, "REALDATA.LOCK")))
attempt("unlink_dot_dot", lambda: os.unlink(os.path.join(run, "..", "run", "realdata.lock")))
attempt("rename_away", lambda: os.rename(lock, other + ".moved"))
attempt("rename_onto", lambda: os.rename(other, lock))
attempt("replace_onto", lambda: os.replace(other, lock))
attempt("hard_link_onto", lambda: os.link(other, lock))
attempt("symlink_onto", lambda: os.symlink(other, lock))
attempt("remove_spare", lambda: os.remove(spare))
attempt("rmtree_run", lambda: shutil.rmtree(run))
attempt("rename_run_away", lambda: os.rename(run, run + ".old"))
attempt("replace_run_away", lambda: os.replace(run, os.path.join(state, "moved")))
attempt("rename_run_other_case", lambda: os.rename(os.path.join(state, "RUN"), run + ".old"))
attempt("rename_run_trailing_slash", lambda: os.rename(run + "/", run + ".old"))
attempt("move_run_away", lambda: shutil.move(run, os.path.join(state, "moved")))
attempt("rename_dir_onto_run", lambda: os.rename(empty, run))
attempt("symlink_onto_run", lambda: os.symlink(empty, run))
attempt("rename_other_dir", lambda: os.rename(empty, empty + ".2"))
now = os.lstat(lock) if os.path.lexists(lock) else None
results["lock_is_file"] = os.path.isfile(lock) and not os.path.islink(lock)
results["lock_same_inode"] = now is not None and (now.st_dev, now.st_ino) == (info.st_dev, info.st_ino)
results["nothing_moved"] = (os.path.isdir(run) and not os.path.islink(run)
                            and not any(os.path.lexists(os.path.join(state, name)) for name in ("run.old", "moved")))
""")
            for name in refused:
                self.assertEqual(results[name], "run_lock_protected", (mode, name))
            self.assertEqual((results["remove_spare"], results["rename_other_dir"]), ("ok", "ok"), mode)
            self.assertEqual((results["lock_is_file"], results["lock_same_inode"], results["nothing_moved"]),
                             (True, True, True), mode)
        # While run/ is missing, nothing may take its place either; making it as a real directory stays allowed.
        for mode in MODES:
            home = make_home(self)
            results = checks(self, home, mode=mode, body="""
run = roots.run_dir()
state = os.path.dirname(run)
os.makedirs(state, exist_ok=True)
empty = os.path.join(state, "empty")
os.mkdir(empty)
attempt("symlink_onto_missing_run", lambda: os.symlink(empty, run))
attempt("rename_dir_onto_missing_run", lambda: os.rename(empty, run))
attempt("mkdir_run", lambda: os.mkdir(run, 0o700))
results["run_is_dir"] = os.path.isdir(run) and not os.path.islink(run)
""")
            self.assertEqual((results["symlink_onto_missing_run"], results["rename_dir_onto_missing_run"]),
                             ("run_lock_protected", "run_lock_protected"), mode)
            self.assertEqual((results["mkdir_run"], results["run_is_dir"]), ("ok", True), mode)

    def test_a_run_directory_or_lock_that_is_a_link_is_refused_at_arm(self):
        # The guard-paths review: run/ made a link before arm() to <state>/run-real, which holds the lock. The slots
        # are where run/ and the lock are named in the state root's real path, but the OS resolves the lock through
        # the link, so in every mode the lock could be removed and run-real renamed. A link to a deeper directory
        # of the root (whose ancestor could be renamed, and a fresh lock made at the same name), one spelt through
        # the firmlink, and a lock that is itself a link (whose target could be removed) escaped the same way
        # (lab-Claude's variants). arm() refuses each (run_lock_invalid), as runmarker.hold_shared already did for
        # the real-data commands. A real run/ and lock, or none, still arm (the test above).
        def layout(home, name):
            state, run = roots.state_dir(home), roots.run_dir(home)
            real = os.path.join(state, "a", "run-real") if name == "nested" else os.path.join(state, "run-real")
            os.makedirs(real, 0o700)
            lock = os.path.join(real, "realdata.lock")
            open(lock, "w").close()
            if name == "lock_is_a_link":
                os.mkdir(run, 0o700)
                os.symlink(lock, os.path.join(run, "realdata.lock"))
            else:
                os.symlink({"sibling": real, "relative": "run-real", "nested": real, "dangling": real + "-missing",
                            "firmlink": FIRMLINK + os.path.realpath(real)}[name], run)
            return lock, os.path.join(state, os.path.relpath(real, state).split(os.sep)[0])

        names = ("sibling", "relative", "nested", "firmlink", "dangling", "lock_is_a_link")
        for mode in MODES:
            for name in names:
                home = make_home(self)
                lock, top = layout(home, name)              # top: the directory below the state root on its way
                results = armed_attempts(self, home, mode=mode, body="""
lock, top = %r, %r
attempt("remove_lock", lambda: os.remove(os.path.join(roots.run_dir(), "realdata.lock")))
attempt("remove_lock_itself", lambda: os.remove(lock))
attempt("rename_its_directory", lambda: os.rename(top, top + "-moved"))
""" % (lock, top))
                with self.subTest(mode=mode, layout=name):
                    self.assertEqual(results, {"arm": "run_lock_invalid"})
                    self.assertTrue(os.path.isfile(lock))

    def test_the_suite_never_creates_or_removes_the_marker_or_the_wrappers_lock(self):
        # Nuance's PR #2 review, item 13: one unlink of lab-runs/ACTIVE lets require_absent pass mid-run. Only
        # Nuance's wrapper creates or removes ACTIVE and its own lab-runs/LOCK. ~/.local/state/lab-runs lies
        # outside every write root, so the hook refuses each of these in every mode, whether the files exist or
        # not.
        for mode in MODES:
            home = make_home(self)
            lab_runs = os.path.join(home, ".local", "state", "lab-runs")
            os.mkdir(lab_runs, 0o700)
            for name in ("ACTIVE", "LOCK"):
                open(os.path.join(lab_runs, name), "w").close()
            results = checks(self, home, mode=mode, body="""
lab_runs = os.path.join(os.environ["HOME"], ".local", "state", "lab-runs")
active, lock = os.path.join(lab_runs, "ACTIVE"), os.path.join(lab_runs, "LOCK")
attempt("create_marker", lambda: os.close(os.open(active, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)))
attempt("truncate_marker", lambda: open(active, "w").close())
attempt("remove_marker", lambda: os.remove(active))
attempt("rename_marker", lambda: os.rename(active, active + ".old"))
attempt("remove_lock", lambda: os.remove(lock))
attempt("replace_lock", lambda: os.replace(active, lock))
attempt("make_beside", lambda: os.mkdir(os.path.join(lab_runs, "x")))
attempt("remove_directory", lambda: os.rmdir(lab_runs))
""")
            self.assertEqual(set(results.values()), {"write_outside_roots"}, (mode, results))
            self.assertEqual(len(results), 8)
            self.assertEqual(sorted(os.listdir(lab_runs)), ["ACTIVE", "LOCK"])

    def test_no_root_lies_in_around_or_onto_the_run_markers_directory(self):
        # Nuance's re-review of #2, F5: with the state root linked to ~/.local/state, arm() succeeded and removing
        # lab-runs/ACTIVE or renaming the wrapper's lab-runs/LOCK were allowed, since lab-runs/ was then inside a
        # root. check_placement now refuses a write root or TMPDIR in, around or onto lab-runs/, by realpath and
        # identity, in every mode; a root elsewhere is refused only in the modes that write it.
        def layout(home, name):
            """Make lab-runs/ with ACTIVE and LOCK, then the named link; return the modes it is a root of."""
            local_state = os.path.join(home, ".local", "state")
            lab = os.path.join(local_state, "lab-runs")
            os.makedirs(os.path.join(lab, "sub"), mode=0o700)
            for marker in ("ACTIVE", "LOCK"):
                open(os.path.join(lab, marker), "w").close()
            state = roots.state_dir(home)
            if name.startswith(("around", "onto", "into")):
                target = {"around": local_state, "onto": lab, "into": os.path.join(lab, "sub")}[name.split("_")[0]]
                if name.endswith("_firmlink"):
                    target = FIRMLINK + os.path.realpath(target)
                rmtree(state)
                os.symlink(target, state)
                return MODES
            if name == "share_into":
                os.rmdir(os.path.join(home, ".local", "share"))
                os.symlink(os.path.join(lab, "sub"), os.path.join(home, ".local", "share"))
                return ("vendor",)
            os.symlink(os.path.join(lab, "sub"), roots.data_home(home))           # suite_root_in: the suite root
            return ("engine",)

        names = ("around", "around_firmlink", "onto", "into", "into_firmlink", "share_into", "suite_root_in")
        for name in names:
            for mode in MODES:
                home = make_home(self)
                refused_in = layout(home, name)
                results = armed_attempts(self, home, mode=mode, body="""
lab = os.path.join(os.environ["HOME"], ".local", "state", "lab-runs")
attempt("remove_marker", lambda: os.remove(os.path.join(lab, "ACTIVE")))
attempt("rename_lock", lambda: os.rename(os.path.join(lab, "LOCK"), os.path.join(lab, "LOCK.old")))
""")
                with self.subTest(layout=name, mode=mode):
                    if mode in refused_in:
                        self.assertEqual(results, {"arm": "root_overlaps_lab_runs"})
                    else:
                        self.assertEqual(results, {"arm": "ok", "remove_marker": "write_outside_roots",
                                                   "rename_lock": "write_outside_roots"})
                    lab = os.path.join(home, ".local", "state", "lab-runs")
                    self.assertEqual(sorted(os.listdir(lab)), ["ACTIVE", "LOCK", "sub"])
                    self.assertEqual(os.listdir(os.path.join(lab, "sub")), [])

    def test_bin_suite_refuses_before_creating_anything(self):
        # The evidence's own commands: bin/suite test made lab-state/betangel-suite/tmp; an engine command would
        # have used historic-pro/tmp as its TMPDIR.
        home = make_home(self)
        lab = self.data_dir(home, "lab-state")
        historic = self.data_dir(home, "historic-pro")
        os.symlink(historic, roots.suite_root(home))
        result = run_suite(["selfcheck"], home)
        self.assertEqual((result.returncode, result.stderr), (2, "refused:suite_root_misplaced\n"))
        self.replace_with_link(os.path.join(home, ".local", "state"), lab)
        for args in (["test", "-k", "no_such_test"], ["selfcheck"]):
            result = run_suite(args, home)
            self.assertEqual((result.returncode, result.stderr), (2, "refused:root_overlaps_data_home\n"), args)
        self.assertEqual(os.listdir(lab), [])
        self.assertEqual(os.listdir(historic), [])


if __name__ == "__main__":
    unittest.main()
