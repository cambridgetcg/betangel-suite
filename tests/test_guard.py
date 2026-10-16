"""I-2 to I-6: the audit hook (betangel_suite/guard.py; DESIGN.md section 10).

Every check of the hook itself runs in a fresh engine-mode subprocess with a temporary HOME, because an
audit hook cannot be removed. Network probes use TEST-NET-1 (192.0.2.1) and the .invalid TLD only; the
hook refuses them before any packet or lookup. /usr/bin/open is never started: its argv shape is tested
through the pure predicate.
"""

import ast
import json
import os
import subprocess
import unittest

from betangel_suite import config, guard, roots
from tests import FORBID, PRELUDE, PYTHON, ROOT, child_env, make_home, run_python, run_relayed

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


def checks(case, home, body, *, setup="", mode="engine", env=None):
    """Run setup, arm the guard, run body (which fills `results`) in a fresh child; return results."""
    code = ATTEMPT + setup + "\nguard.arm(%r)\n" % mode + body + "\nprint(json.dumps(results))\n"
    result = run_python(code, home, env=env)
    case.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def parse(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), path)


def environment_uses(tree, keys, names):
    """Every environment access in tree that is not a fixed-key lookup (NoOffSwitchTests).

    keys are the allowed key values. A key given by name must be a module constant of tree (module_constants), and
    its string value is what is compared, so neither a rebound name nor a local of the same name passes."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    constants = module_constants(tree)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name in names for alias in node.names):
            problems.append("imports an environment name")
        elif isinstance(node, ast.Constant) and node.value in names:
            problems.append("names %r in a string" % node.value)
        elif isinstance(node, ast.Name) and node.id in names:
            problems.append("uses a bare " + node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            problem = _environ_use(node, parents, keys, constants)
            if problem:
                problems.append(problem)
    return problems


def module_constants(tree):
    """{name: string} for each top-level `NAME = "literal"` of tree whose name is bound nowhere else in it (no other
    assignment, deletion, parameter, import, global, except or loop name, at any depth)."""
    bound = {}
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names = [node.id]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(alias.asname or alias.name).split(".")[0] for alias in node.names]
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names = list(node.names) * 2                    # never a constant
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names = [node.name]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        for name in names:
            bound[name] = bound.get(name, 0) + 1
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                and bound.get(node.targets[0].id) == 1):
            constants[node.targets[0].id] = node.value.value
    return constants


def _environ_use(node, parents, keys, constants):
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
    if isinstance(key, ast.Constant):
        value = key.value
    elif isinstance(key, ast.Name) and key.id in constants:
        value = constants[key.id]
    else:
        return "reads key %s (not a literal or a module constant)" % ast.unparse(key)
    return None if value in keys else "reads key %r" % (value,)


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
attempt("switch_on_again", lambda: os.environ.__setitem__(guard.FORBID_NETWORK_ENV, "1"))
attempt("ordinary_variable", lambda: os.environ.__setitem__("SUITE_TEST_ORDINARY", "1"))
results["switch_value"] = os.environ.get(guard.FORBID_NETWORK_ENV)
""")
        for name in ("switch_off", "switch_deleted", "putenv_switch", "stray_set", "tmpdir_moved"):
            self.assertEqual(results[name], "environment_change_refused", name)
        self.assertEqual(results["switch_on_again"], "ok")
        self.assertEqual(results["ordinary_variable"], "ok")
        self.assertEqual(results["switch_value"], "1")


class NoOffSwitchTests(unittest.TestCase):
    """I-2: no environment or config read can disable the guard, and the guard has no off function."""

    PUBLIC = {"GuardRefusal", "arm", "seal", "armed_mode", "is_sealed", "require_armed", "require_mode",
              "permit_loopback_port", "permit_unix_socket", "permit_unix_connect", "engine_argv_ok", "vendor_argv_ok",
              "runner_argv_ok", "runner_git_ok", "release_argv_ok", "uisnap_build_argv", "uisnap_argv_ok",
              "permit_uisnap_binary"}

    def test_guard_public_callables_are_exactly_these(self):
        public = {name for name, value in vars(guard).items()
                  if callable(value) and not name.startswith("_") and getattr(value, "__module__", "") == guard.__name__}
        self.assertEqual(public, self.PUBLIC)

    # The allowed keys are values: a key given by name is resolved to its module constant (environment_uses).
    ENV_KEYS = {"HOME", "TMPDIR", "SQLITE_TMPDIR", "PATH", "BETANGEL_BETFAIR_FORBID_NETWORK"}
    # SUITE_VIA_SSH (cli.VIA_SSH_ENV, Phase 0c) is bin/suite's validated SSH flag: it can only refuse a command, and
    # only cli.py may read it.
    MODULE_ENV_KEYS = {os.path.join("betangel_suite", "cli.py"): {"SUITE_VIA_SSH"}}
    ENV_NAMES = {"environ", "environb", "getenv", "getenvb"}

    def test_environment_reads_are_fixed_key_lookups_only(self):
        # An allowlist, not a search for known shapes: os.environ may appear only as os.environ.get(KEY, ...)
        # or os.environ[KEY] with KEY one of ENV_KEYS (a literal, or a module constant holding one), plus the one
        # stray-variable scan in guard.arm. So `"X" in os.environ`, .items(), .copy(), dict(os.environ),
        # os.environb, os.getenv, an imported environ and getattr(os, "environ") all fail it.
        from betangel_suite import cli
        self.assertEqual((guard.FORBID_NETWORK_ENV, cli.VIA_SSH_ENV), ("BETANGEL_BETFAIR_FORBID_NETWORK", "SUITE_VIA_SSH"))
        sources = [os.path.join(ROOT, "betangel_suite", name) for name in os.listdir(os.path.join(ROOT, "betangel_suite"))
                   if name.endswith(".py")]
        sources += [os.path.join(ROOT, "bin", "_launch.py"), os.path.join(ROOT, "tools", "vendor_research.py")]
        for path in sources:
            name = os.path.relpath(path, ROOT)
            keys = self.ENV_KEYS | self.MODULE_ENV_KEYS.get(name, set())
            for problem in environment_uses(parse(path), keys, self.ENV_NAMES):
                self.fail("%s: %s" % (name, problem))

    def test_the_allowlist_rule_catches_off_switch_shapes(self):
        for source in ('if "SUITE_GUARD_OFF" in os.environ:\n    pass\n', "x = dict(os.environ)\n",
                       "x = os.environ.items()\n", "x = os.getenv('HOME')\n", "x = os.environb\n",
                       "from os import environ\n", "x = getattr(os, 'environ')\n", "x = os.environ.get('OFF')\n",
                       "x = os.environ['OFF']\n", "x = any(k == 'OFF' for k in os.environ)\n",
                       "x = posix.environ\n", "x = os.environ.setdefault('HOME', '')\n",
                       # an allowed name holding another key, a rebound or local name, an attribute: never a key
                       'VIA_SSH_ENV = "SUITE_GUARD_OFF"\nif os.environ.get(VIA_SSH_ENV) == "1":\n    pass\n',
                       'KEY = "HOME"\nKEY = "OFF"\nx = os.environ.get(KEY)\n',
                       'KEY = "HOME"\ndef f(KEY="OFF"):\n    return os.environ.get(KEY)\n',
                       'KEY = "HOME"\ndef f():\n    KEY = "OFF"\n    return os.environ[KEY]\n',
                       'KEY = "HOME"\nfor KEY in ("OFF",):\n    pass\nx = os.environ.get(KEY)\n',
                       "x = os.environ.get(guard.FORBID_NETWORK_ENV)\n", "x = os.environ.get(UNDEFINED)\n"):
            self.assertTrue(environment_uses(ast.parse(source), self.ENV_KEYS | {"SUITE_VIA_SSH"}, self.ENV_NAMES),
                            source)
        self.assertEqual(environment_uses(ast.parse("x = os.environ.get('HOME', '')\ny = os.environ['TMPDIR']\n"
                                                    'KEY = "PATH"\nz = os.environ.get(KEY)\n'),
                                          self.ENV_KEYS, self.ENV_NAMES), [])
        via_ssh = 'VIA_SSH_ENV = "SUITE_VIA_SSH"\nx = os.environ.get(VIA_SSH_ENV, "")\n'
        self.assertEqual(environment_uses(ast.parse(via_ssh), self.ENV_KEYS | {"SUITE_VIA_SSH"}, self.ENV_NAMES), [])
        self.assertTrue(environment_uses(ast.parse(via_ssh), self.ENV_KEYS, self.ENV_NAMES), "only cli.py reads it")

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
        # hashlib and stat (Phase 0c): the uisnap binary's sha256 and file checks (permit_uisnap_binary).
        self.assertEqual(imported, {"fcntl", "hashlib", "os", "re", "stat", "sys", "threading", "posix", "sqlite3",
                                    "sqlite3.dbapi2", "..roots", ".errors.SuiteError"})

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
import socket
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
guard.seal()
attempt("permit_after_seal", lambda: guard.permit_loopback_port(9000))
attempt("loopback_after_seal", lambda: bind(socket.AF_INET, ("127.0.0.1", 0)))
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
attempt("dlopen", lambda: __import__("ctypes"))
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
        self.assertEqual(results["dlopen"], "dlopen_refused")
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
        ok = guard.vendor_argv_ok
        for rest in (["-C", research, "cat-file", "-e", sha + "^{commit}"],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", research, partial],
                     ["-C", partial, "checkout", "--quiet", "--detach", sha],
                     ["-C", partial, "remote", "remove", "origin"]):
            self.assertTrue(ok(prefix + rest, research, deps), rest)
        for rest in (["-C", research, "fetch"],
                     ["-C", research, "cat-file", "-e", sha],
                     ["-C", research, "status", "--porcelain"],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", "/elsewhere", partial],
                     ["clone", "--no-checkout", "--no-hardlinks", "--quiet", research, deps + "/other"],
                     ["-C", research, "checkout", "--quiet", "--detach", sha],
                     ["-C", partial, "remote", "add", "origin", research],
                     ["-C", research, "worktree", "add", partial]):
            self.assertFalse(ok(prefix + rest, research, deps), rest)
        self.assertFalse(ok(["/usr/bin/git", "-C", research, "cat-file", "-e", sha + "^{commit}"], research, deps))

    TMP = "/h/.local/state/betangel-suite/tmp"
    REPO = TMP + "/home-x/repo"
    GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", FORBID: "1", "PATH": "/usr/bin:/bin"}

    def test_test_runner_argv_shapes(self):
        interpreters = frozenset(guard.TEST_INTERPRETERS)

        def ok(argv):
            return guard.runner_argv_ok(argv, self.GIT_ENV, interpreters, guard.LAUNCHER, self.TMP)

        self.assertTrue(ok(["/opt/homebrew/bin/python3.13", "-I", "-S", "-B", "-c", "pass"]))
        self.assertFalse(ok(["/opt/homebrew/bin/python3.13", "-c", "pass"]))
        self.assertFalse(ok(["/opt/homebrew/bin/python3", "-I", "-S", "-B", "-c", "pass"]))
        self.assertTrue(ok(["/bin/sh", guard.LAUNCHER, "selfcheck"]))
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
        for change in ({"GIT_CONFIG_GLOBAL": None}, {"GIT_CONFIG_NOSYSTEM": None}, {"GIT_CONFIG_GLOBAL": "/h/.gitconfig"},
                       {"GIT_DIR": research + "/.git"}, {"GIT_WORK_TREE": research}, {"GIT_CONFIG_COUNT": "1"},
                       {"GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='x'"}, {"GIT_SSH_COMMAND": "ssh"}, {"GIT_EXEC_PATH": "/x"}):
            env = {key: value for key, value in dict(self.GIT_ENV, **change).items() if value is not None}
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

    def test_vendor_mode_refuses_other_git_commands(self):
        home = make_home(self)
        os.makedirs(roots.research_clone(home))
        results = checks(self, home, mode="vendor", body="""
import subprocess
prefix = list(guard.VENDOR_GIT_PREFIX)
attempt("fetch", lambda: subprocess.run(prefix + ["-C", roots.research_clone(), "fetch"], capture_output=True))
attempt("plain_git", lambda: subprocess.run(["/usr/bin/git", "-C", roots.research_clone(), "status"], capture_output=True))
""")
        self.assertEqual(results, {"fetch": "subprocess_refused", "plain_git": "subprocess_refused"})


class WriteTests(unittest.TestCase):
    """I-6: writes stay inside the roots; nothing under ~/betangel-data while the suite root is not agreed."""

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
        results = checks(self, home, setup=self.SETUP, body="""
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

    def test_calls_without_their_own_audit_event(self):
        # CPython raises no audit event for os.mkfifo or os.mknod; arm() wraps them so that they do.
        home = make_home(self)
        os.makedirs(roots.data_home(home), mode=0o700)      # a synthetic ~/betangel-data in the temporary HOME
        results = checks(self, home, setup=self.SETUP, body="""
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
            self.assertEqual(results[name], "state_root_not_agreed", name)
        self.assertEqual(results["mkfifo_inside"], "ok")
        self.assertTrue(results["wrapped"])
        self.assertEqual(os.listdir(roots.data_home(home)), [])
        self.assertEqual(sorted(os.listdir(os.path.join(home, "outside"))), ["file"])
        for name in ("fifo_out", "fifo_posix", "node_out"):
            self.assertFalse(os.path.lexists(os.path.join(home, name)), name)

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



class ReleaseModeTests(unittest.TestCase):
    """bin/suite release (guard mode release, I-18): its own git argvs on this checkout only, then nothing; writes
    also under the app root, nowhere else in the share dir. Nothing here runs git on a real repository: allowed
    shapes are checked through the pure predicate, and the live child only meets refusals."""

    REPO = "/h/betangel-suite"
    RESEARCH = "/h/betangel-research"
    APP = "/h/.local/share/betangel-suite/app"
    ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", FORBID: "1", "PATH": "/usr/bin:/bin"}
    COMMIT = "0a1b2c3d4e5f" * 3 + "0a1b"
    TREE = "f" * 40

    def ok(self, rest, env=None, repo=None):
        repo = self.REPO if repo is None else repo
        argv = list(guard.RELEASE_GIT_PREFIX) + ["-C", repo] + list(rest)
        return guard.release_argv_ok(argv, self.ENV if env is None else env, repo, self.RESEARCH, self.APP)

    def test_release_argv_shapes(self):
        for rest in (["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty"],
                     ["ls-files", "--stage", "-z"],
                     ["rev-parse", "--verify", "--quiet", "refs/tags/v0.1.0^{commit}"],
                     ["rev-parse", "--verify", "--quiet", "refs/heads/main^{commit}"],
                     ["rev-parse", "--verify", "--quiet", self.COMMIT + "^{tree}"],
                     ["rev-parse", "--verify", "--quiet", "e" * 64 + "^{tree}"],
                     ["merge-base", "--is-ancestor", self.COMMIT, self.TREE],
                     ["archive", "--format=tar", self.COMMIT],
                     ["config", "--includes", "--null", "--get-regexp", "^filter\\."]):
            self.assertTrue(self.ok(rest), rest)
        for rest in (["fetch"], ["pull"], ["push"], ["ls-remote", "origin"], ["status"], ["status", "--porcelain"],
                     # status never enters a submodule (a nested repository's own filters would run), and the
                     # index query is exactly ls-files --stage -z, never recursing either
                     ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                     ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"],
                     ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty",
                      "--recurse-submodules"],
                     ["ls-files", "--stage"], ["ls-files", "-z", "--stage"], ["ls-files", "--stage", "-z", "x"],
                     ["ls-files", "--stage", "-z", "--recurse-submodules"], ["ls-files", "--stage", "-z", "-o"],
                     ["rev-parse", "--verify", "--quiet", "refs/tags/-x^{commit}"],
                     ["rev-parse", "--verify", "--quiet", "refs/tags/a..b^{commit}"],
                     ["rev-parse", "--verify", "--quiet", "refs/tags/v1"],
                     ["rev-parse", "--verify", "--quiet", "refs/heads/other^{commit}"],
                     ["rev-parse", "--verify", "--quiet", "HEAD^{tree}"],
                     ["rev-parse", "refs/heads/main^{commit}"],
                     ["merge-base", "--is-ancestor", "v1", "main"],
                     ["archive", "--format=tar", "v1"], ["archive", "--format=zip", self.COMMIT],
                     ["archive", "--remote=https://example.invalid/x", "--format=tar", self.COMMIT],
                     ["archive", "--format=tar", "--output=/h/x.tar", self.COMMIT],
                     ["archive", "--format=tar", self.COMMIT, "--exec=/bin/sh"],
                     ["clone", self.REPO, "/h/x"], ["worktree", "add", "/h/x"], ["submodule", "update"],
                     ["tag", "v1"], ["config", "core.fsmonitor", "/bin/sh"], [],
                     # only the exact read-only filter query: no other key, write, file or edit
                     ["config", "--null", "--get-regexp", "^filter\\."],
                     ["config", "--includes", "--null", "--get-regexp", "."],
                     ["config", "--includes", "--null", "--get-regexp", "^filter\\.", "x"],
                     ["config", "--file", "/h/x", "--includes", "--null", "--get-regexp", "^filter\\."],
                     ["config", "--add", "filter.x.clean", "/bin/sh"], ["config", "--edit"]):
            self.assertFalse(self.ok(rest), rest)
        status = ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty"]
        for repo in (self.RESEARCH, self.RESEARCH + "/sub", self.APP + "/v1", "relative", "/h/x/../betangel-suite"):
            self.assertFalse(self.ok(status, repo=repo), repo)
        argv = list(guard.RELEASE_GIT_PREFIX) + ["-C", "/h/other"] + status
        self.assertFalse(guard.release_argv_ok(argv, self.ENV, self.REPO, self.RESEARCH, self.APP))
        self.assertFalse(guard.release_argv_ok(["/usr/bin/git", "-C", self.REPO] + status, self.ENV, self.REPO,
                                               self.RESEARCH, self.APP))
        self.assertFalse(guard.release_argv_ok(["git"] + list(guard.RELEASE_GIT_PREFIX[1:]) + ["-C", self.REPO] + status,
                                               self.ENV, self.REPO, self.RESEARCH, self.APP))
        self.assertFalse(guard.release_argv_ok(list(guard.RELEASE_GIT_PREFIX) + ["-C", self.REPO] + status, None,
                                               self.REPO, self.RESEARCH, self.APP))      # an inherited environment
        for change in ({"GIT_CONFIG_GLOBAL": None}, {"GIT_CONFIG_NOSYSTEM": None}, {"GIT_CONFIG_GLOBAL": "/h/.gitconfig"},
                       {"GIT_DIR": self.RESEARCH + "/.git"}, {"GIT_WORK_TREE": self.RESEARCH}, {"GIT_CONFIG_COUNT": "1"},
                       {"GIT_SSH_COMMAND": "ssh"}, {"GIT_EXEC_PATH": "/x"}, {"GIT_AUTHOR_NAME": "x"}):
            env = {key: value for key, value in dict(self.ENV, **change).items() if value is not None}
            self.assertFalse(self.ok(status, env=env), change)
        self.assertTrue(self.ok(status, env=dict(self.ENV, GIT_TERMINAL_PROMPT="0")))

    def test_release_is_its_own_mode(self):
        from betangel_suite import cli
        self.assertIn("release", guard.MODES)
        self.assertEqual(cli.guard_mode("release"), "release")

    def test_release_mode_writes_and_spawns(self):
        home = make_home(self)
        setup = "os.makedirs(roots.deps_root(), mode=0o700)\nos.makedirs(roots.state_dir(), exist_ok=True)\n"
        results = checks(self, home, mode="release", setup=setup, body="""
import subprocess
home = os.environ["HOME"]
app = roots.app_dir()
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
env = {"HOME": home, "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
       guard.FORBID_NETWORK_ENV: "1", "TMPDIR": os.environ["TMPDIR"]}
prefix = list(guard.RELEASE_GIT_PREFIX)
def run(argv, run_env=env):
    subprocess.run(argv, env=run_env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
attempt("mkdir_app", lambda: os.mkdir(app, 0o700))
attempt("write_app", lambda: write(os.path.join(app, "x")))
attempt("symlink_in_app", lambda: os.symlink("x", os.path.join(app, "current")))
attempt("rename_in_app", lambda: os.rename(os.path.join(app, "current"), os.path.join(app, "current2")))
attempt("chmod_in_app", lambda: os.chmod(os.path.join(app, "x"), 0o400))
attempt("write_share", lambda: write(os.path.join(roots.share_dir(), "x")))
attempt("write_deps", lambda: write(os.path.join(roots.deps_root(), "x")))
attempt("rename_into_deps", lambda: os.rename(os.path.join(app, "x"), os.path.join(roots.deps_root(), "x")))
attempt("write_outside", lambda: write(os.path.join(home, "outside.txt")))
attempt("write_data_home", lambda: write(os.path.join(roots.data_home(), "x")))
attempt("git_without_prefix", lambda: run(["/usr/bin/git", "-C", guard.REPO_ROOT, "status"]))
attempt("git_fetch", lambda: run(prefix + ["-C", guard.REPO_ROOT, "fetch"]))
attempt("git_other_repo", lambda: run(prefix + ["-C", home, "archive", "--format=tar", "0" * 40]))
attempt("git_research", lambda: run(prefix + ["-C", roots.research_clone(), "archive", "--format=tar", "0" * 40]))
attempt("git_inherited_env", lambda: run(prefix + ["-C", guard.REPO_ROOT, "archive", "--format=tar", "0" * 40], None))
attempt("shell", lambda: subprocess.run("true", shell=True))
guard.seal()
attempt("git_after_seal", lambda: run(prefix + ["-C", guard.REPO_ROOT, "archive", "--format=tar", "0" * 40]))
""")
        for name in ("mkdir_app", "write_app", "symlink_in_app", "rename_in_app", "chmod_in_app"):
            self.assertEqual(results[name], "ok", name)
        for name in ("write_share", "write_deps", "rename_into_deps", "write_outside"):
            self.assertEqual(results[name], "write_outside_roots", name)
        self.assertEqual(results["write_data_home"], "state_root_not_agreed")
        for name in ("git_without_prefix", "git_fetch", "git_other_repo", "git_research", "git_inherited_env", "shell",
                     "git_after_seal"):
            self.assertEqual(results[name], "subprocess_refused", name)
        self.assertEqual(os.listdir(roots.deps_root(home)), [])
        self.assertEqual(sorted(os.listdir(roots.share_dir(home))), ["app", "deps"])
        self.assertFalse(os.path.lexists(os.path.join(home, "outside.txt")))

    def test_other_modes_cannot_write_the_app_root(self):
        home = make_home(self)
        setup = "os.makedirs(roots.app_dir(), mode=0o700)\nos.makedirs(roots.state_dir(), exist_ok=True)\n"
        for mode in ("engine", "test", "vendor", "uisnap"):
            results = checks(self, home, mode=mode, setup=setup if mode == "engine" else "", body="""
attempt("write_app", lambda: open(os.path.join(roots.app_dir(), "x"), "w").close())
attempt("symlink_app", lambda: os.symlink("x", os.path.join(roots.app_dir(), "current")))
attempt("mkdir_app_tag", lambda: os.mkdir(os.path.join(roots.app_dir(), "v1")))
""")
            self.assertEqual(results, {"write_app": "write_outside_roots", "symlink_app": "write_outside_roots",
                                       "mkdir_app_tag": "write_outside_roots"}, mode)
        self.assertEqual(os.listdir(roots.app_dir(home)), [])

    def test_vendor_writes_only_its_deps_the_pin_and_the_share_dir_itself(self):
        # vendor may create ~/.local/share/betangel-suite (one mkdir of exactly that path) and write under its
        # deps/; nothing else in the share dir, so never app/ (release copies, app/current).
        home = make_home(self)
        results = checks(self, home, mode="vendor", body="""
share = roots.share_dir()
def write(path):
    with open(path, "w") as handle:
        handle.write("x")
attempt("mkdir_share_unnormalised", lambda: os.mkdir(share + "/../betangel-suite"))
attempt("mkdir_share", lambda: os.mkdir(share, 0o700))
attempt("mkdir_deps", lambda: os.mkdir(roots.deps_root(), 0o700))
attempt("write_deps", lambda: write(os.path.join(roots.deps_root(), "x")))
attempt("mkdir_app", lambda: os.mkdir(roots.app_dir(), 0o700))
attempt("write_share", lambda: write(os.path.join(share, "x")))
attempt("symlink_current", lambda: os.symlink("deps", os.path.join(share, "current")))
attempt("rename_deps", lambda: os.rename(os.path.join(roots.deps_root(), "x"), os.path.join(share, "x")))
attempt("chmod_share", lambda: os.chmod(share, 0o755))
attempt("rmdir_share", lambda: os.rmdir(share))
""")
        self.assertEqual(results, {
            "mkdir_share_unnormalised": "write_outside_roots", "mkdir_share": "ok", "mkdir_deps": "ok",
            "write_deps": "ok", "mkdir_app": "write_outside_roots", "write_share": "write_outside_roots",
            "symlink_current": "write_outside_roots", "rename_deps": "write_outside_roots",
            "chmod_share": "write_outside_roots", "rmdir_share": "write_outside_roots"})
        self.assertEqual(sorted(os.listdir(roots.share_dir(home))), ["deps"])


if __name__ == "__main__":
    unittest.main()
