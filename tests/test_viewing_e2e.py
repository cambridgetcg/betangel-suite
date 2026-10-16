"""Phase 0c end to end through bin/suite from a release copy (DESIGN.md 8.6 items 1 and 2, 11; I-16, I-18, I-19).

A temporary git repository holds this checkout's launcher, package, pin and UI. `bin/suite release v1` (this
interpreter on that repository's bin/_launch.py, so the child's guard, mode release, holds the repository as its
own checkout) installs app/v1 and app/current in a short temporary HOME, as Yu's release would. Everything then
runs through that copy's own bin/suite, started by an unguarded relay (the runner's guard starts only this
checkout's launcher), in a fake SSH environment: SSH_CONNECTION is set to TEST-NET addresses and no sshd is
involved. Engines bind 127.0.0.1 on ephemeral ports (ssh-session --port 0).

  1. ssh-session prints one URL on its stdout (a pipe this test holds); a client bootstraps with it, opens a
     synthetic market, plays it and streams;
  2. stdin EOF pauses the clock within 2 s (not_watched), and the session is kept;
  3. a second ssh-session within the grace takes over: a fresh URL, the old tab's stream ends as superseded, the
     old token dies, the new code works, and the engine keeps running; the second one's own stdin EOF ends it;
  4. a tampered copy refuses to launch (release_file_modified) and takes nothing over;
  5. bin/suite stop ends the engine; the first terminal (away, not gone) reads "ended reason=stopped".

The heavy tier adds the expiry through the same path, which takes a minute: with watch_grace_s at its minimum
(60 s) and nobody watching, stdin EOF ends the session as abandoned after the grace. The same expiry runs in the
fast tier with tiny graces through the in-process seams (tests/test_session_process.py).

Bootstrap codes stay in the pipes and 0600 files of the temporary HOME and in this process's memory; assertions
compare redacted text (shape), and no client prints a code or a token. /usr/bin/open is never run.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

from betangel_suite import roots
from tests import (HEAVY, HEAVY_ONLY, PYTHON, ROOT, child_env, require_no_run_marker, rmtree, run_relayed, run_suite,
                   tree_listing)
from tests import test_http_support as support
from tests.test_release import Repo, launch, writable
from tests.test_session_process import (SSH, SUITE_TMP_ONLY, URL_RE, AsyncClient, PipeChild, assert_code_lines, shape,
                                        wait_path, write_private)

SOURCES = ("bin", "betangel_suite", "pin", "ui")
SOURCE_FILES = ("AGENTS.md",)
# An unguarded relay that becomes /bin/sh on the release copy's bin/suite (stdin and stdout stay the test's pipes).
RELAY = "import os, sys\nos.execv('/bin/sh', ['/bin/sh'] + sys.argv[1:])\n"


def copy_sources(dest):
    """This checkout's launcher, package, pin and UI (regular files only, no caches) into dest."""
    for top in SOURCES:
        for directory, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(name for name in dirs if name != "__pycache__")
            for name in files:
                source = os.path.join(directory, name)
                if os.path.islink(source) or not os.path.isfile(source) or name.endswith((".pyc", ".swp", "~")):
                    continue
                target = os.path.join(dest, os.path.relpath(source, ROOT))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
    for name in SOURCE_FILES:
        shutil.copy2(os.path.join(ROOT, name), os.path.join(dest, name))


class ReleaseViewingTests(unittest.TestCase):
    """One repository for the class; each test releases v1 into its own short HOME."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="e2e-")
        cls.addClassCleanup(rmtree, cls.base)
        cls.repo = Repo(os.path.join(cls.base, "repo"))
        copy_sources(cls.repo.path)
        cls.commit = cls.repo.commit("synthetic release")
        cls.repo.write_ref("refs/tags/v1", cls.commit)

    def released_home(self, config=None):
        """A short HOME (deps copy included) with app/v1 released from the class's repository; (home, copy)."""
        home = support.short_home(self)
        if config is not None:
            with open(roots.config_path(home), "w", encoding="ascii") as handle:
                json.dump(config, handle)
        code, out, err = launch(home, self.repo.path, "release", "v1")
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, r"\Areleased files=[0-9]+ bytes=[0-9]+ current=switched\n\Z")
        return home, os.path.join(roots.app_dir(home), "v1")     # removed with home (tests.rmtree)

    def session(self, home, name, *, stdout_pipe=False):
        """The copy's bin/suite ssh-session --port 0 (through app/current), in the fake SSH environment."""
        suite = os.path.join(roots.app_dir(home), "current", "bin", "suite")
        argv = [PYTHON, "-I", "-S", "-B", "-c", RELAY, suite, "ssh-session", "--port", "0"]
        return PipeChild(self, home, "", name=name, stdout_pipe=stdout_pipe, argv=argv,
                         env=child_env(home, SSH_CONNECTION=SSH))

    def test_ssh_session_from_a_release_copy_eof_takeover_tamper_and_stop(self):
        home, copy = self.released_home()
        first = self.session(home, "ssh-first", stdout_pipe=True)
        match = URL_RE.fullmatch(first.read_line(timeout=60))
        self.assertIsNotNone(match, "the first line is the URL")
        port = int(match.group(1))
        write_private(os.path.join(home, "code-1"), match.group(2))
        client = AsyncClient(self, home, port, r"""
def wait_file(name, timeout=30):
    deadline = time.monotonic() + timeout
    while not os.path.lexists(os.path.join(HOME, name)):
        if time.monotonic() > deadline:
            raise SystemExit("no " + name)
        time.sleep(0.02)
    return open(os.path.join(HOME, name)).read()
token = bootstrap(wait_file("code-1"))
fd = os.open(os.path.join(HOME, "token-1"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, token.encode())
os.close(fd)
stream = Stream(token)
results["open"] = command(token, "open_market", {"seed": 11})[1]["ok"]
command(token, "set_speed", {"speed_x100": 1000})
results["play"] = command(token, "play")[1]
moving = stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
results["moving"] = moving["t"] if isinstance(moving, dict) else moving
os.close(os.open(os.path.join(HOME, "moving"), os.O_WRONLY | os.O_CREAT, 0o600))
wait_file("eof")
eof = time.monotonic()
paused = stream.until(lambda item: item["t"] == "frame" and item["clock"]["paused"], timeout=10)
results["paused_after_s"] = time.monotonic() - eof
results["pause_reason"] = paused["clock"]["pause_reason"] if isinstance(paused, dict) else paused
os.close(os.open(os.path.join(HOME, "paused"), os.O_WRONLY | os.O_CREAT, 0o600))
# The tab still streams (somebody watches: no grace runs) until the second ssh-session takes over.
results["end"] = stream.until(lambda item: item["t"] == "end", timeout=30)
stream.close()
""")
        wait_path(os.path.join(home, "moving"))
        first.close_stdin()                                    # stdin EOF: pause, and keep the session
        write_private(os.path.join(home, "eof"), "")
        wait_path(os.path.join(home, "paused"))

        second = self.session(home, "ssh-second")              # within the grace: a takeover, not a refusal
        (second_port, _code), = second.wait_urls(1, timeout=60)
        self.assertEqual(int(second_port), port)
        results = client.result(self)
        self.assertEqual((results["open"], results["play"], results["moving"]), (True, {"ok": True}, "frame"))
        self.assertEqual(results["pause_reason"], "not_watched")
        self.assertLess(results["paused_after_s"], 2.0)        # I-19: closing stdin pauses within 2 s
        self.assertEqual(results["end"]["reason"], "superseded")
        after = support.client(self, home, port, r"""
import re
results["old_token"] = query(open(os.path.join(HOME, "token-1")).read())[0]
code = re.findall(r"#c=([A-Za-z0-9_-]{22})", open(os.path.join(HOME, "ssh-second.out")).read())[0]
token = bootstrap(code)
results["controller"] = query(token)[1]["controller"]
""")
        self.assertEqual(after, {"old_token": 401, "controller": True})
        self.assertIsNone(first.process.poll(), "the session is kept: the engine still runs")
        second.close_stdin()                                   # the attached viewer leaves at once
        self.assertEqual(second.wait_exit(20), 0, shape(second.stderr()))
        self.assertRegex(shape(second.stdout()), r"\Ahttp://127\.0\.0\.1:%d/#c=<code>\n(heartbeat [0-9:]+\n)*\Z" % port)
        self.assertEqual(second.stderr(), "")

        # I-18: a modified file in the release copy refuses every launch from it, before anything is taken over.
        victim = os.path.join(copy, "betangel_suite", "release.py")
        with writable(os.path.dirname(victim), victim):
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("# tampered\n")
        suite = os.path.join(roots.app_dir(home), "current", "bin", "suite")
        require_no_run_marker()                 # its own check looks at the temporary HOME
        refused = run_relayed(["/bin/sh", suite, "ssh-session", "--port", "0"], child_env(home, SSH_CONNECTION=SSH),
                              home)
        # Redacted before comparing: a failure message must never carry a code (rule 11, I-16).
        self.assertEqual((refused[0], shape(refused[1]), shape(refused[2])), (2, "", "refused:release_file_modified\n"))
        self.assertIsNone(first.process.poll())

        stop = run_suite(["stop"], home)                       # this checkout's launcher: stop only reduces activity
        self.assertEqual((stop.returncode, stop.stdout, stop.stderr), (0, "stopped\n", ""))
        self.assertEqual(first.wait_exit(20), 0, shape(first.stderr()))
        rest = ""
        while True:
            try:
                rest += first.read_line(timeout=5)
            except AssertionError:
                break                                          # the child closed its stdout
        self.assertRegex(rest, r"\A(heartbeat [0-9:]+\n)*ended reason=stopped\n\Z")
        assert_code_lines(self, first.stderr(), {"http:401:bad_code", "http:401:unauthorized"})   # I-16
        self.assertFalse(os.path.lexists(support.control_path(home)))
        self.assertEqual(tree_listing(roots.data_home(home)), SUITE_TMP_ONLY)     # its TMPDIR only, left empty

    @unittest.skipUnless(HEAVY, HEAVY_ONLY + " (waits out the 60 s minimum watch_grace_s)")
    def test_stdin_eof_with_nobody_watching_ends_as_abandoned_after_the_grace(self):
        home, _copy = self.released_home(config={"watch_grace_s": 60})
        first = self.session(home, "ssh-alone", stdout_pipe=True)
        self.assertIsNotNone(URL_RE.fullmatch(first.read_line(timeout=60)))
        first.close_stdin()
        eof = time.monotonic()
        self.assertEqual(first.wait_exit(120), 0, shape(first.stderr()))
        elapsed = time.monotonic() - eof
        self.assertTrue(60.0 <= elapsed < 75.0, elapsed)
        rest = ""
        while True:
            try:
                rest += first.read_line(timeout=5)
            except AssertionError:
                break
        self.assertRegex(rest, r"\A(heartbeat [0-9:]+\n)*ended reason=abandoned\n\Z")
        self.assertEqual(first.stderr(), "")
        self.assertFalse(os.path.lexists(support.control_path(home)))


if __name__ == "__main__":
    unittest.main()
