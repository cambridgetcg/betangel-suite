"""tools/vendor_research.py (DESIGN.md 3.5) against a synthetic upstream repository.

Each test builds a small git repository with synthetic files at the pinned paths, as the temporary HOME's
~/betangel-research, and runs `bin/suite vendor` with that HOME and a temporary pin file. The real deploy
clone, the real deps clone and the checkout's own pin file are never touched.
"""

import ast
import hashlib
import json
import os
import subprocess
import unittest

from betangel_suite import guard, pin, roots
from tests import ROOT, make_home, rmtree, run_suite


def snapshot(tree):
    """(relative path, size, mtime_ns, mode) of everything under tree, for an unchanged-tree check."""
    found = []
    for directory, dirs, files in os.walk(tree):
        for name in dirs + files:
            path = os.path.join(directory, name)
            info = os.lstat(path)
            found.append((os.path.relpath(path, tree), info.st_size, info.st_mtime_ns, info.st_mode))
    return sorted(found)


class VendorToolTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)
        self.research = roots.research_clone(self.home)
        self.contents = {}
        for relpath in pin.PINNED_FILES + ("README.md",):
            path = os.path.join(self.research, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = ("# synthetic %s\n" % relpath).encode()
            with open(path, "wb") as handle:
                handle.write(data)
            self.contents[relpath] = data
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-q", "-m", "synthetic")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.pin_file = os.path.join(roots.state_dir(self.home), "pin-under-test.json")
        self.dest = os.path.join(roots.deps_root(self.home), "betangel-research-" + self.sha[:12])

    def git(self, *args):
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
               guard.FORBID_NETWORK_ENV: "1"}
        return subprocess.run([guard.GIT, "-C", self.research, *args], env=env, capture_output=True, text=True,
                              check=True, timeout=60).stdout

    def vendor(self, *args):
        result = run_suite(["vendor", *args], self.home)
        return result.returncode, result.stdout, result.stderr

    def test_bump_then_check(self):
        before = snapshot(self.research)
        returncode, out, err = self.vendor(self.sha, "--bump", "--pin-file", self.pin_file)
        self.assertEqual((returncode, err), (0, ""))
        self.assertEqual(out, "vendor_ok commit=%s files=26 mode=bump\n" % self.sha[:12])
        with open(self.pin_file, encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(written["commit"], self.sha)
        self.assertEqual(written["files"], {relpath: hashlib.sha256(self.contents[relpath]).hexdigest()
                                            for relpath in pin.PINNED_FILES})
        self.assertEqual(pin.load(self.pin_file), written)
        self.assertFalse(os.path.lexists(self.dest + ".partial"))
        with open(os.path.join(self.dest, ".git", "HEAD"), encoding="ascii") as handle:
            self.assertEqual(handle.read(), self.sha + "\n")
        with open(os.path.join(self.dest, ".git", "config"), encoding="utf-8") as handle:
            self.assertNotIn("[remote", handle.read())
        for directory, dirs, files in os.walk(self.dest):
            for name in dirs + files:
                path = os.path.join(directory, name)
                if not os.path.islink(path):
                    self.assertEqual(os.lstat(path).st_mode & 0o222, 0, os.path.relpath(path, self.dest))
        self.assertEqual(snapshot(self.research), before)
        returncode, out, err = self.vendor(self.sha, "--pin-file", self.pin_file)
        self.assertEqual((returncode, out, err), (0, "vendor_ok commit=%s files=26 mode=check\n" % self.sha[:12], ""))

    def test_check_refuses_a_different_pin_and_keeps_the_partial(self):
        self.assertEqual(self.vendor(self.sha, "--bump", "--pin-file", self.pin_file)[0], 0)
        written = pin.load(self.pin_file)
        written["files"][pin.PINNED_FILES[0]] = "0" * 64
        os.remove(self.pin_file)
        with open(self.pin_file, "w", encoding="utf-8") as handle:
            json.dump(written, handle)
        rmtree(self.dest)
        self.assertEqual(self.vendor(self.sha, "--pin-file", self.pin_file), (2, "", "refused:pin_mismatch\n"))
        self.assertTrue(os.path.isdir(self.dest + ".partial"))
        self.assertFalse(os.path.lexists(self.dest))
        self.assertEqual(self.vendor(self.sha, "--pin-file", self.pin_file), (2, "", "refused:partial_exists\n"))

    def test_unknown_commit_is_refused_before_anything_is_created(self):
        self.assertEqual(self.vendor("f" * 40, "--bump", "--pin-file", self.pin_file),
                         (2, "", "refused:commit_not_present\n"))
        self.assertFalse(os.path.lexists(roots.share_dir(self.home)))
        self.assertFalse(os.path.lexists(self.pin_file))

    def test_bad_arguments(self):
        for args in ((), ("abc",), (self.sha.upper(),), (self.sha, "--pin-file", "relative.json"),
                     (self.sha, "--fetch"), (self.sha, "--bump", "--bump")):
            self.assertEqual(self.vendor(*args), (2, "", "refused:bad_arguments\n"), args)

    def test_tool_source_names_no_fetching_git_command(self):
        with open(os.path.join(ROOT, "tools", "vendor_research.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for word in ("fetch", "pull", "push", "submodule", "worktree", "status", "remote add", "ls-remote"):
            self.assertNotIn(word, strings)


if __name__ == "__main__":
    unittest.main()
