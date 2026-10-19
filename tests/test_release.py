"""I-18: release copies (betangel_suite/release.py; DESIGN.md 3.4, 8.6) and their check at every launch.

No real release is ever made. Everything runs in a temporary git repository under TMPDIR, built from this
checkout's launcher, package and pin with the runner's local git (guard.runner_git_ok: init, add, commit,
rev-parse), and in temporary HOMEs; nothing here touches the real ~/.local/share/betangel-suite. A release names
its commit by full object id (Nuance's PR #1 review: "`release` takes the merge SHA"), and takes only a commit that
refs/remotes/origin/main contains: GitHub's main as the operator last fetched it, never the local main (Nuance's
re-review of PR #1, finding 13). The runner's git cannot fetch, so the tests write that ref by hand, as a fetch
would leave it (Repo.fetched). Since round 6 release also takes only a merge commit, one with a second parent
(release_not_merge_commit): every PR lands with gh pr merge --merge (DESIGN.md 3.9, 8.6). So every commit a test
releases is landed as such a merge (Repo.land), written by hand as a loose object (the runner's git has no merge).
The class repository has root, then on main the merges c1 (of an empty branch off root) and c3 (of later, a branch
off c1), and c3 is also the checkout's HEAD and origin/main; c2 (side) is a commit main does not contain (main is
pointed back at c1 before later is made). v1 is an annotated tag of c1, a loose tag object written by hand (the
runner's git has no tag subcommand), whose own id names no commit. OriginMainTests has its own repository, whose
local main is ahead of origin/main, and FirstParentTests one whose main merges a side branch.

bin/suite release runs as this interpreter on the temporary repository's bin/_launch.py, so the child's guard
(mode release) holds that repository as its own checkout. Launches from a copy go through the copy's own
bin/suite (by an unguarded relay: the runner starts only this checkout's launcher) or its bin/_launch.py.
The command launched from a copy is stop: with no engine running it prints not_running and touches nothing.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import zlib

from betangel_suite import cli, guard, release, roots
from betangel_suite.errors import SuiteError
from tests import (FORBID, PYTHON, ROOT, child_env, make_home, require_no_run_marker, rmtree, run_relayed,
                   stand_in_marker, tree_listing)

SOURCES = ("bin", "betangel_suite", "pin")
SOURCE_FILES = ("AGENTS.md",)
IDENTITY = {"GIT_AUTHOR_NAME": "Synthetic Tester", "GIT_AUTHOR_EMAIL": "tester@example.invalid",
            "GIT_COMMITTER_NAME": "Synthetic Tester", "GIT_COMMITTER_EMAIL": "tester@example.invalid"}
RELEASED_RE = r"\Areleased files=([0-9]+) bytes=([0-9]+) current=switched\n\Z"
ORIGIN_MAIN = "refs/remotes/origin/main"            # written by hand: the runner's git cannot fetch
# Keys of a release git child's environment that git reads and its xcrun shim never does; the runner's git does not
# accept them (guard.runner_git_ok), so shim_env leaves them out.
GIT_ONLY_KEYS = ("GIT_NO_REPLACE_OBJECTS", "GIT_GRAFT_FILE")


class Repo:
    """A temporary git repository driven only through the runner's allowed git argvs."""

    def __init__(self, path):
        self.path = path
        os.mkdir(path, 0o700)
        self.env = {"PATH": "/usr/bin:/bin", "HOME": os.path.dirname(path), "LANG": "en_GB.UTF-8",
                    "TMPDIR": os.environ["TMPDIR"], "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                    FORBID: "1", **IDENTITY}
        self.git("-c", "init.defaultBranch=main", "init", "-q", "--template=")

    def git(self, *args):
        result = subprocess.run([guard.GIT, "-C", self.path, *args], env=self.env, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise AssertionError("git %s failed" % args[0])
        return result.stdout.decode("ascii").strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "--verify", "-q", "HEAD")

    def write_ref(self, ref, object_id):
        path = os.path.join(self.path, ".git", *ref.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="ascii") as handle:
            handle.write(object_id + "\n")

    def fetched(self, commit):
        """refs/remotes/origin/main naming commit, as `git fetch` from GitHub leaves it."""
        self.write_ref(ORIGIN_MAIN, commit)

    def loose_object(self, kind, body):
        """Write a loose object of kind with body (bytes) into the repository; returns its id."""
        data = kind.encode("ascii") + b" %d\0" % len(body) + body
        object_id = hashlib.sha1(data).hexdigest()
        path = os.path.join(self.path, ".git", "objects", object_id[:2], object_id[2:])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(zlib.compress(data))
        return object_id

    def annotated_tag(self, name, commit):
        """A loose annotated tag object for commit, and refs/tags/<name> naming it (as `git tag -a` would)."""
        body = ("object %s\ntype commit\ntag %s\ntagger Synthetic Tester <tester@example.invalid> 86400 +0000\n\n"
                "synthetic release\n" % (commit, name)).encode("ascii")
        object_id = self.loose_object("tag", body)
        self.write_ref("refs/tags/" + name, object_id)
        return object_id

    def merge_commit(self, tree, parents, message):
        """A loose commit object with tree and these parents, first parent first, as `git merge` leaves one."""
        lines = ["tree " + tree] + ["parent " + parent for parent in parents]
        lines += ["author Synthetic Tester <tester@example.invalid> 86400 +0000",
                  "committer Synthetic Tester <tester@example.invalid> 86400 +0000", "", message, ""]
        return self.loose_object("commit", "\n".join(lines).encode("ascii"))

    def tree_of(self, commit):
        return self.git("rev-parse", "--verify", "-q", commit + "^{tree}")

    def land(self, onto, message, branch=None):
        """Land a branch on main as every PR lands (gh pr merge --merge; DESIGN.md 3.9): a merge commit whose first
        parent is onto, main's tip before the branch, and second the branch's commit, with the branch's tree.
        branch defaults to one commit off onto with onto's tree (an empty branch). main, and so HEAD, then name the
        merge, and an index that matched the branch's tree matches it; returns its id."""
        if branch is None:
            branch = self.merge_commit(self.tree_of(onto), (onto,), message)
        merge = self.merge_commit(self.tree_of(branch), (onto, branch), "merge: " + message)
        self.write_ref("refs/heads/main", merge)
        return merge

    def files(self):
        """{relpath: (sha256, executable)} of the working tree, .git excluded."""
        found = {}
        for directory, dirs, files in os.walk(self.path):
            dirs[:] = [name for name in dirs if name != ".git"]
            for name in files:
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                found[os.path.relpath(path, self.path)] = (digest, bool(os.stat(path).st_mode & stat.S_IXUSR))
        return found


def copy_sources(dest):
    """This checkout's launcher, package and pin (regular files only, no caches) into dest."""
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


def shim_env(home):
    """The environment a release git child gets in home, as release._Git builds it with the TMPDIR bin/suite gives
    release (guard.release_git_env), less GIT_ONLY_KEYS: the same HOME, TMPDIR, PATH and LANG, and no DEVELOPER_DIR,
    SDKROOT or TOOLCHAINS, which is all /usr/bin/git's xcrun shim reads."""
    env = guard.release_git_env(home, roots.tmp_dir("release", home))
    for key in GIT_ONLY_KEYS:
        del env[key]
    return env


def new_home(base, name):
    """A temporary HOME with .local/state, the state tmp/ and the share dir (whose app/ release creates).

    Then /usr/bin/git's xcrun shim runs once in it, with release's own environment (shim_env), so a cache the shim
    keeps in TMPDIR is there before any test takes a footprint baseline of the HOME (Astra's review of #5 at
    52a9edc, item 2: on a fresh macOS cache the first release git made TMPDIR/xcrun_db after the baseline, and ten
    tests failed on each interpreter). On the lab xcrun keeps its cache in the per-user temp dir, so it passed there;
    under a seatbelt profile that denies mach lookups xcrun falls back to TMPDIR, and the ten failed on the lab too
    before this (DESIGN.md Appendix F, Round 6, phase0/viewing). git -C home rev-parse finds no repository and
    writes nothing.
    """
    home = os.path.join(base, name)
    os.makedirs(roots.tmp_dir("test", home), mode=0o700)
    os.makedirs(roots.share_dir(home), mode=0o700)
    subprocess.run([guard.GIT, "-C", home, "rev-parse", "--verify", "-q", "HEAD"], env=shim_env(home),
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    return home


def launch(home, root, *args):
    """root's bin/_launch.py with args, as bin/suite runs it (child_env(home) with the TMPDIR bin/suite gives the
    command, roots.tmp_dir); (code, stdout, stderr).

    As tests.run_suite does, every command the launcher checks the marker for is first checked against the runner's
    real marker: the child's own check reads only the temporary HOME's (Nuance's PR #4 review, item 14).
    """
    if not args or args[0] not in cli.NO_RUN_MARKER_CHECK:
        require_no_run_marker()
    tmp = roots.tmp_dir(args[0] if args else "", home)
    result = subprocess.run([PYTHON, "-I", "-S", "-B", os.path.join(root, "bin", "_launch.py"), *args],
                            env=child_env(home, TMPDIR=tmp, SQLITE_TMPDIR=tmp), cwd=home, capture_output=True,
                            text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


class ShimEnvTests(unittest.TestCase):

    def test_the_shim_runs_with_releases_own_environment(self):
        # new_home runs /usr/bin/git's xcrun shim before any footprint baseline (Astra's review of #5 at 52a9edc,
        # item 2), with what a release git child gets in that HOME: everything but GIT_ONLY_KEYS, which git reads and
        # the shim never does, and which the runner's git refuses.
        home = os.path.join(os.environ["TMPDIR"], "h", "home")
        tmp = roots.tmp_dir("release", home)
        self.assertEqual(tmp, roots.tmp_dir("test", home))                       # the TMPDIR new_home makes
        expected = guard.release_git_env(home, tmp)
        self.assertTrue(set(GIT_ONLY_KEYS) <= set(expected) and all(key.startswith("GIT_") for key in GIT_ONLY_KEYS))
        self.assertEqual(shim_env(home), {key: value for key, value in expected.items() if key not in GIT_ONLY_KEYS})
        argv = [guard.GIT, "-C", home, "rev-parse", "--verify", "-q", "HEAD"]
        self.assertTrue(guard.runner_git_ok(argv, shim_env(home), os.environ["TMPDIR"]))


class RunnerMarkerTests(unittest.TestCase):
    """launch() starts commands, serve among them, from release copies under temporary HOMEs, whose own marker checks
    never see a real run. So it checks the runner's real marker first ("check it before each engine launch", Nuance's
    PR #4 review, item 14). A stand-in takes the real marker's place (tests.stand_in_marker)."""

    def test_launch_checks_the_runner_marker_before_it_starts_anything(self):
        base = tempfile.mkdtemp(prefix="release-marker-")
        self.addCleanup(rmtree, base)
        for present, code in ((True, "run_marker_present"), (False, "run_marker_unreadable")):
            with self.subTest(present=present):
                stand_in_marker(self, present)
                home = new_home(base, code)
                before = tree_listing(home)
                for args in (("serve", "--port", "0"), ("release", "-not-a-commit"), ()):
                    with self.assertRaises(SuiteError) as caught:
                        launch(home, ROOT, *args)
                    self.assertEqual(caught.exception.code, code, args)
                self.assertEqual(tree_listing(home), before)
                _code, _out, err = launch(home, ROOT, "stop")              # stop skips it, as in bin/suite
                self.assertNotIn("run_marker", err)


def modes_under(path):
    """{relative path: permission bits} of path and everything below it (no symlink followed)."""
    found = {".": stat.S_IMODE(os.lstat(path).st_mode)}
    for relative, mode in tree_listing(path):
        found[relative] = mode
    return found


@contextlib.contextmanager
def writable(*directories):
    """Make directories owner-writable for the duration, then restore their modes."""
    saved = [(path, stat.S_IMODE(os.lstat(path).st_mode)) for path in directories]
    for path, mode in saved:
        os.chmod(path, mode | 0o200)
    try:
        yield
    finally:
        for path, mode in reversed(saved):
            if os.path.lexists(path):
                os.chmod(path, mode)


class ReleaseTestCase(unittest.TestCase):
    """One repository and one release of c1 (while HEAD is c3) for the whole class; each test uses its own HOME."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="rel-")
        cls.addClassCleanup(rmtree, cls.base)
        cls.repo = Repo(os.path.join(cls.base, "repo"))
        copy_sources(cls.repo.path)
        cls.root = cls.repo.commit("first")                  # main's first commit: no merge, so never released
        cls.c1 = cls.repo.land(cls.root, "first branch")     # the first merge on main, with root's tree
        cls.tree1 = cls.repo.tree_of(cls.c1)
        cls.files1 = cls.repo.files()
        cls.tag1 = cls.repo.annotated_tag("v1", cls.c1)    # a tag object: its id is no commit
        with open(os.path.join(cls.repo.path, "side.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic side branch\n")
        cls.c2 = cls.repo.commit("side")
        cls.repo.write_ref("refs/heads/main", cls.c1)       # main no longer contains c2
        os.remove(os.path.join(cls.repo.path, "side.txt"))
        cls.repo.git("add", "-A")                            # the index matches c1 again
        with open(os.path.join(cls.repo.path, "later.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic later commit\n")
        cls.later = cls.repo.commit("later")                 # a branch off c1
        cls.c3 = cls.repo.land(cls.c1, "later", cls.later)  # main and HEAD: c1, then c3; a clean tree
        cls.repo.fetched(cls.c3)                             # and origin/main, as fetched: c1, then c3
        cls.tree3 = cls.repo.git("rev-parse", "--verify", "-q", cls.c3 + "^{tree}")
        cls.name1, cls.name3 = cls.c1[:12], cls.c3[:12]
        cls.home = new_home(cls.base, "home")
        cls.app = roots.app_dir(cls.home)
        cls.copy = os.path.join(cls.app, cls.name1)
        cls.result = launch(cls.home, cls.repo.path, "release", cls.c1)

    def release(self, home, commit):
        return launch(home, self.repo.path, "release", commit)

    def fresh_home(self):
        base = tempfile.mkdtemp(prefix="h-", dir=self.base)
        return new_home(base, "home")

    def place_copy(self, home, name=None, *, current=True):
        """A copy of the class's release under home's app root (modes preserved), and app/current to it."""
        name = self.name1 if name is None else name
        app = roots.app_dir(home)
        os.makedirs(app, mode=0o700, exist_ok=True)
        target = os.path.join(app, name)
        shutil.copytree(self.copy, target)
        if current:
            os.symlink(name, os.path.join(app, "current"))
        return target

    def assertRefused(self, outcome, code):
        self.assertEqual(outcome, (2, "", "refused:%s\n" % code))


class ReleaseCommandTests(ReleaseTestCase):

    def test_commits_are_set_up_as_intended(self):
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/tags/v1^{commit}"), self.c1)
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/tags/v1"), self.tag1)     # annotated
        self.assertNotEqual(self.tag1, self.c1)
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/heads/main"), self.c3)
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/remotes/origin/main"), self.c3)
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "HEAD"), self.c3)
        self.assertNotEqual(self.name1, self.name3)
        git = self.repo.git
        self.assertEqual([git("rev-parse", "--verify", "-q", self.c3 + suffix) for suffix in ("^1", "^2")],
                         [self.c1, self.later])
        self.assertEqual(git("rev-parse", "--verify", "-q", self.c1 + "^1"), self.root)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.c1 + "^2" + "^1"), self.root)
        self.assertEqual((self.tree1, self.repo.tree_of(self.c3)), (self.repo.tree_of(self.root), self.tree3))

    def test_a_commit_that_is_not_a_merge_is_refused(self):
        # Every PR lands with gh pr merge --merge (Nuance's reviews of #1 at af960fd, F2, and of #5 at 52a9edc, N5-2;
        # lab-Claude's decision), so release takes only a merge commit: <id>^2 must name a commit
        # (release_not_merge_commit). root is on main's first-parent line but has no second parent; later, c3's
        # second parent, is off that line and keeps its own code.
        home = self.fresh_home()
        before = tree_listing(home)
        self.assertRefused(self.release(home, self.root), "release_not_merge_commit")
        self.assertRefused(self.release(home, self.later), "release_not_first_parent")
        self.assertEqual(tree_listing(home), before)

    def test_release_installs_a_read_only_copy_of_the_commit_not_the_checkouts_head(self):
        code, out, err = self.result
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        files, size = (int(value) for value in re.match(RELEASED_RE, out).groups())
        self.assertEqual(files, len(self.files1))
        self.assertEqual(size, sum(os.path.getsize(os.path.join(self.repo.path, p)) for p in self.files1))
        self.assertNotIn(self.c1, out)
        self.assertEqual(sorted(os.listdir(self.app)), sorted(["current", self.name1]))
        self.assertEqual(os.readlink(os.path.join(self.app, "current")), self.name1)
        with open(os.path.join(self.copy, "RELEASE.json"), encoding="ascii") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest, {
            "format": 2, "commit": self.c1, "tree": self.tree1,
            "files": {path: digest for path, (digest, _x) in self.files1.items()},
            "executables": sorted(path for path, (_d, executable) in self.files1.items() if executable)})
        self.assertNotIn("later.txt", manifest["files"])     # c1's tree, although HEAD and the checkout hold c3
        self.assertIn("bin/suite", manifest["executables"])
        self.assertFalse(os.path.lexists(os.path.join(self.copy, ".git")))
        for relative, mode in modes_under(self.copy).items():
            path = os.path.join(self.copy, relative)
            if os.path.isdir(path):
                self.assertEqual(mode, 0o500, relative)
            else:
                expected = 0o500 if relative in manifest["executables"] else 0o400
                self.assertEqual(mode, expected, relative)
        self.assertEqual(release.verify_copy(self.copy), manifest)
        self.assertEqual(stat.S_IMODE(os.lstat(self.app).st_mode), 0o700)

    def test_launch_from_the_release_copy(self):
        returncode, out, err = run_relayed(["/bin/sh", os.path.join(self.app, "current", "bin", "suite"), "stop"],
                                           child_env(self.home), self.home)
        self.assertEqual((returncode, out, err), (0, "not_running\n", ""))
        status = release.status_of(os.path.join(self.app, "current"), self.home)
        self.assertEqual(status, release.Status("release", self.c1, self.tree1))
        self.assertEqual(release.status_of(ROOT, self.home), release.CHECKOUT)
        self.assertEqual(release.status(), release.status_of(ROOT))     # this runner's own code, as launched
        with self.assertRaises(SuiteError) as caught:
            release.status_of(self.app, self.home)                      # the app root itself is no copy
        self.assertEqual(caught.exception.code, "release_layout_invalid")

    def check_spelling(self, spell):
        """status_of through another spelling, spell(path), of a copy and of its app root: still a release copy,
        verified against its RELEASE.json (a changed file is caught), and the app root still no copy."""
        home = self.fresh_home()
        target = os.path.realpath(self.place_copy(home))
        app = os.path.dirname(target)
        if not os.path.exists(spell(target)) or not os.path.samefile(spell(target), target):
            self.skipTest("this volume has no such spelling of the temporary HOME")
        self.assertNotEqual(spell(target), target)
        self.assertEqual(release.status_of(spell(target), home), release.Status("release", self.c1, self.tree1))
        with self.assertRaises(SuiteError) as caught:
            release.status_of(spell(app), home)
        self.assertEqual(caught.exception.code, "release_layout_invalid")
        victim = os.path.join(target, "betangel_suite", "release.py")
        with writable(os.path.dirname(victim), victim):
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("# tampered\n")
        with self.assertRaises(SuiteError) as caught:
            release.status_of(spell(target), home)
        self.assertEqual(caught.exception.code, "release_file_modified")

    def test_a_case_variant_spelling_of_a_copy_is_still_verified(self):
        # realpath keeps the case as given, so status_of compares (st_dev, st_ino), never the spelling.
        self.check_spelling(lambda path: "/APP".join(path.rsplit("/app", 1)))       # .../APP/<sha12> and .../APP

    def test_the_data_volume_firmlink_spelling_of_a_copy_is_still_verified(self):
        # On macOS /Users is also /System/Volumes/Data/Users, an alias realpath does not resolve.
        self.check_spelling(lambda path: "/System/Volumes/Data" + path)

    def test_a_release_copy_still_refuses_every_data_root(self):
        # Phase 0: the release status enables nothing; serve from a copy refuses a configured data root.
        home = make_home(self, deps=True)
        os.makedirs(roots.share_dir(home), exist_ok=True)
        os.makedirs(roots.data_home(home), mode=0o700)          # as on the lab: serve's TMPDIR is the suite root's
        target = self.place_copy(home)
        with open(roots.config_path(home), "w", encoding="ascii") as handle:
            json.dump({"data_roots": ["~/betangel-data/historic-pro"]}, handle)
        self.assertRefused(launch(home, target, "serve", "--port", "0"), "synthetic_only")
        # Under ~/betangel-data only the suite root's tmp/ (0700) was made, before the refusal, and it is empty.
        self.assertEqual(tree_listing(roots.data_home(home)), [("suite.noindex", 0o700),
                                                               (os.path.join("suite.noindex", "tmp"), 0o700)])

    def test_launch_refuses_a_tampered_copy(self):
        home = self.fresh_home()
        target = self.place_copy(home)
        current_suite = os.path.join(roots.app_dir(home), "current", "bin", "suite")
        victim = os.path.join(target, "betangel_suite", "release.py")
        with writable(os.path.dirname(victim), victim):
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("# tampered\n")
        returncode, out, err = run_relayed(["/bin/sh", current_suite, "stop"], child_env(home), home)
        self.assertEqual((returncode, out, err), (2, "", "refused:release_file_modified\n"))
        self.assertRefused(launch(home, target, "frobnicate"), "release_file_modified")
        rmtree(target)
        target = self.place_copy(home, current=False)
        os.chmod(os.path.join(target, "bin", "_launch.py"), 0o600)
        self.assertRefused(launch(home, target, "stop"), "release_writable")

    def test_release_from_a_release_copy_is_refused(self):
        before = tree_listing(self.app)
        self.assertRefused(launch(self.home, self.copy, "release", self.c3), "release_not_a_checkout")
        self.assertEqual(tree_listing(self.app), before)

    def test_unknown_unreachable_and_named_commits_are_refused(self):
        home = self.fresh_home()
        before = tree_listing(home)
        for unknown in ("f" * 40, self.tag1, self.tree1, "e" * 64):   # nothing; a tag's id; a tree's; SHA-256 here
            self.assertRefused(self.release(home, unknown), "release_commit_unknown")
        self.assertRefused(self.release(home, self.c2), "release_not_on_main")
        for name in ("v1", "main", "HEAD", "refs/heads/main", "origin/main", "refs/remotes/origin/main", self.name1,
                     self.c1.upper(), self.c1 + "^{commit}", "../" + self.c1, self.c3[:-1]):
            self.assertRefused(self.release(home, name), "release_commit_invalid")
        self.assertEqual(launch(home, self.repo.path, "release"), (2, "", "refused:bad_arguments\n"))
        self.assertEqual(tree_listing(home), before)

    def test_replace_refs_and_grafts_are_ignored(self):
        # A replace ref or a graft in the checkout makes git see other objects (round 4b; as for vendor on
        # phase0/foundation): refs/replace/<c1> naming c2 would copy c2's tree under c1's id and record it as c1's
        # tree, and a graft giving c1 the parent c2 would put c2 on main. release's git runs with neither
        # (guard.RELEASE_GIT_ENV: GIT_NO_REPLACE_OBJECTS=1, GIT_GRAFT_FILE=/dev/null).
        replace = os.path.join(self.repo.path, ".git", "refs", "replace", self.c1)
        grafts = os.path.join(self.repo.path, ".git", "info", "grafts")
        self.addCleanup(lambda: os.path.lexists(replace) and os.remove(replace))
        self.addCleanup(lambda: os.path.lexists(grafts) and os.remove(grafts))
        self.repo.write_ref("refs/replace/" + self.c1, self.c2)
        tree2 = self.repo.git("rev-parse", "--verify", "-q", self.c2 + "^{tree}")
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", self.c1 + "^{tree}"), tree2)  # plain git: c2's
        home = self.fresh_home()
        code, out, err = self.release(home, self.c1)
        self.assertEqual((code, err), (0, ""), err)
        manifest = release.verify_copy(os.path.join(roots.app_dir(home), self.name1))
        self.assertEqual((manifest["commit"], manifest["tree"]), (self.c1, self.tree1))
        self.assertNotIn("side.txt", manifest["files"])
        os.remove(replace)
        os.makedirs(os.path.dirname(grafts), exist_ok=True)
        with open(grafts, "w", encoding="ascii") as handle:
            handle.write("%s %s\n" % (self.c1, self.c2))          # c1's parent would be c2, so c2 on main
        home = self.fresh_home()
        before = tree_listing(home)
        self.assertRefused(self.release(home, self.c2), "release_not_on_main")
        self.assertEqual(tree_listing(home), before)

    def test_a_dirty_tree_is_refused(self):
        home = self.fresh_home()
        before = tree_listing(home)
        tracked = os.path.join(self.repo.path, "AGENTS.md")
        with open(tracked, "rb") as handle:
            original = handle.read()
        self.addCleanup(self._restore, tracked, original)
        with open(tracked, "ab") as handle:
            handle.write(b"\nsynthetic edit\n")
        self.assertRefused(self.release(home, self.c1), "release_dirty_tree")
        self._restore(tracked, original)
        untracked = os.path.join(self.repo.path, "bin", "untracked.txt")
        self.addCleanup(lambda: os.path.lexists(untracked) and os.remove(untracked))
        with open(untracked, "w", encoding="ascii") as handle:
            handle.write("synthetic\n")
        self.assertRefused(self.release(home, self.c1), "release_dirty_tree")
        self.assertEqual(tree_listing(home), before)

    @staticmethod
    def _restore(path, data):
        with open(path, "wb") as handle:
            handle.write(data)

    def test_a_second_release_switches_current_and_an_existing_one_is_refused(self):
        home = self.fresh_home()
        app = roots.app_dir(home)
        self.assertEqual(self.release(home, self.c1)[0], 0)
        os.symlink(self.name1, os.path.join(app, ".current.partial"))      # left by an interrupted release
        os.mkdir(os.path.join(app, "." + self.name3 + ".partial"))
        self.assertRefused(self.release(home, self.c3), "partial_exists")
        os.rmdir(os.path.join(app, "." + self.name3 + ".partial"))
        code, out, err = self.release(home, self.c3)
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        self.assertEqual(os.readlink(os.path.join(app, "current")), self.name3)
        self.assertEqual(sorted(os.listdir(app)), sorted(["current", self.name1, self.name3]))
        before = tree_listing(app)
        self.assertRefused(self.release(home, self.c1), "release_exists")
        self.assertEqual(tree_listing(app), before)
        for commit, tree in ((self.c1, self.tree1), (self.c3, self.tree3)):
            manifest = release.verify_copy(os.path.join(app, commit[:12]))
            self.assertEqual((manifest["commit"], manifest["tree"]), (commit, tree))
            self.assertEqual("later.txt" in manifest["files"], commit == self.c3)

    def test_current_must_be_a_symlink(self):
        home = self.fresh_home()
        os.makedirs(os.path.join(roots.app_dir(home), "current"))
        before = tree_listing(home)
        self.assertRefused(self.release(home, self.c1), "release_current_invalid")
        self.assertEqual(tree_listing(home), before)

    def test_the_run_marker_refuses_a_release(self):
        home = self.fresh_home()
        marker = os.path.join(home, ".local", "state", "lab-runs", "ACTIVE")
        os.makedirs(os.path.dirname(marker))
        open(marker, "w").close()
        before = tree_listing(home)
        self.assertRefused(self.release(home, self.c1), "run_marker_present")
        self.assertEqual(tree_listing(home), before)

    def test_the_run_marker_is_checked_again_just_before_the_copy_goes_live(self):
        # bin/_launch.py refuses a release while the marker exists; make() checks again right before the rename,
        # for a run announced meanwhile. Here make() is called past the launcher (a release-mode child of the
        # temporary repository's own package), with the marker there, so only that second check can refuse.
        home = self.fresh_home()
        marker = os.path.join(home, ".local", "state", "lab-runs", "ACTIVE")
        os.makedirs(os.path.dirname(marker))
        open(marker, "w").close()
        code = ("import sys\nsys.path.append(%r)\nfrom betangel_suite import errors, guard\nguard.arm('release')\n"
                "errors.install_excepthooks()\nfrom betangel_suite import release\ntry:\n    release.make(%r)\n"
                "except errors.SuiteError as exc:\n    sys.stderr.write(errors.describe(exc) + '\\n')\n    sys.exit(2)\n"
                % (self.repo.path, self.c1))
        result = subprocess.run([PYTHON, "-I", "-S", "-B", "-c", code], env=child_env(home), cwd=home,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "", "refused:run_marker_present\n"))
        self.assertEqual(os.listdir(roots.app_dir(home)), [], "no copy, partial copy or current link is left")

    def test_a_filter_driver_in_the_repository_config_is_refused(self):
        # git status would run a filter's clean command and git archive its smudge command, as this user and outside
        # the guard: a filter.<driver>.* key in the repository's config, or in a file it includes, refuses first.
        home = self.fresh_home()
        marks = tempfile.mkdtemp(prefix="marks-", dir=self.base)
        config = os.path.join(self.repo.path, ".git", "config")
        attributes = os.path.join(self.repo.path, ".git", "info", "attributes")
        included = os.path.join(self.base, "included.config")
        with open(config, "rb") as handle:
            original = handle.read()
        self.addCleanup(self._restore, config, original)
        self.addCleanup(lambda: os.path.lexists(attributes) and os.remove(attributes))
        os.makedirs(os.path.dirname(attributes), exist_ok=True)
        with open(attributes, "w", encoding="ascii") as handle:
            handle.write("* filter=synthetic\n")
        driver = '[filter "synthetic"]\n\tclean = touch %s/clean && cat\n\tsmudge = touch %s/smudge && cat\n' % (marks,
                                                                                                                marks)
        with open(included, "w", encoding="ascii") as handle:
            handle.write(driver)
        before = tree_listing(home)
        for label, extra in (("direct", driver), ("included", "[include]\n\tpath = %s\n" % included)):
            with open(config, "wb") as handle:
                handle.write(original + extra.encode("ascii"))
            self.assertRefused(self.release(home, self.c1), "release_git_filter")
        self.assertEqual(os.listdir(marks), [], "no filter command ran")
        self.assertEqual(tree_listing(home), before)

    def test_the_share_dir_must_exist(self):
        home = self.fresh_home()
        rmtree(roots.share_dir(home))
        self.assertRefused(self.release(home, self.c1), "root_parent_missing")
        self.assertFalse(os.path.lexists(roots.share_dir(home)))


class OriginMainTests(unittest.TestCase):
    """release takes a commit only if refs/remotes/origin/main contains it (Nuance's re-review of PR #1, finding 13;
    lab-Claude's decision in round 5). The local main can hold merges nobody has reviewed yet: Nuance's probe, in a
    throwaway repository, had an unreviewed local commit pass against refs/heads/main and be refused against
    refs/remotes/origin/main. Here local main and HEAD are c2, ahead of origin/main at c1. The ref is named in
    full, so neither a tag nor a local branch called main or origin/main stands in for it. The suite never fetches:
    the operator does, before release."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="rel-origin-")
        cls.addClassCleanup(rmtree, cls.base)
        cls.repo = Repo(os.path.join(cls.base, "repo"))
        copy_sources(cls.repo.path)
        cls.c1 = cls.repo.land(cls.repo.commit("base"), "reviewed")
        cls.repo.fetched(cls.c1)
        with open(os.path.join(cls.repo.path, "unreviewed.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic local merge\n")
        cls.c2 = cls.repo.commit("unreviewed")              # local main and HEAD; a clean tree

    def release(self, commit):
        base = tempfile.mkdtemp(prefix="h-", dir=self.base)
        home = new_home(base, "home")
        before = tree_listing(home)
        outcome = launch(home, self.repo.path, "release", commit)
        return home, before, outcome

    def refs(self):
        """Every ref file and FETCH_HEAD under .git, with its content: what a fetch would change."""
        found = {}
        git_dir = os.path.join(self.repo.path, ".git")
        for directory, _dirs, files in os.walk(os.path.join(git_dir, "refs")):
            for name in files:
                with open(os.path.join(directory, name), encoding="ascii") as handle:
                    found[os.path.relpath(os.path.join(directory, name), git_dir)] = handle.read()
        found["FETCH_HEAD"] = os.path.lexists(os.path.join(git_dir, "FETCH_HEAD"))
        return found

    def test_a_commit_only_on_the_local_main_is_refused(self):
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/heads/main"), self.c2)   # local main's tip
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", ORIGIN_MAIN), self.c1)
        refs = self.refs()
        home, before, outcome = self.release(self.c2)
        self.assertEqual(outcome, (2, "", "refused:release_not_on_main\n"))
        self.assertEqual(tree_listing(home), before)
        home, _before, (code, out, err) = self.release(self.c1)
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        manifest = release.verify_copy(os.path.join(roots.app_dir(home), self.c1[:12]))
        self.assertEqual(manifest["commit"], self.c1)
        self.assertNotIn("unreviewed.txt", manifest["files"])
        self.assertEqual(self.refs(), refs, "release fetched nothing and moved no ref")

    def test_no_tag_or_branch_named_main_or_origin_main_stands_in_for_it(self):
        added = ("refs/tags/main", "refs/tags/origin/main", "refs/heads/origin/main", "refs/remotes/origin/HEAD")
        for ref in added:
            self.addCleanup(lambda ref=ref: os.remove(os.path.join(self.repo.path, ".git", *ref.split("/"))))
            self.repo.write_ref(ref, self.c2)
        _home, _before, outcome = self.release(self.c2)
        self.assertEqual(outcome, (2, "", "refused:release_not_on_main\n"))

    def test_without_a_fetched_origin_main_nothing_is_released(self):
        path = os.path.join(self.repo.path, ".git", *ORIGIN_MAIN.split("/"))
        os.remove(path)
        self.addCleanup(self.repo.fetched, self.c1)
        home, before, outcome = self.release(self.c1)
        self.assertEqual(outcome, (2, "", "refused:release_main_missing\n"))
        self.assertEqual(tree_listing(home), before)
        self.assertFalse(os.path.lexists(os.path.join(self.repo.path, ".git", "FETCH_HEAD")))


class FirstParentTests(unittest.TestCase):
    """release also takes a commit only on refs/remotes/origin/main's first-parent line (Nuance's answer of 2026-10-18
    to lab-Claude's round-5 question, which lab-Claude adopts): "Ancestry alone admits side-branch commits inside a
    merge, which were never a reviewed main tip." After the ancestry check, rev-list --first-parent of the id that
    ref gave must list the commit, else release_not_first_parent.

    Here c1 is the base, itself a merge on main (release takes only a merge commit since round 6); side is a commit
    on a side branch off c1, itself a merge of its own branch commit so that only the first-parent line decides, and
    m1 the main line's next merge after c1, of the branch commit later. merge has the parents m1 and side, in that
    order: the main line merging the side branch. HEAD, local main and origin/main name it, and its tree is m1's, so
    the checkout is clean. back has the same parents the other way round, side first, as when main is moved to a
    branch that merged main in; origin/main names it only in the test of that case."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="rel-first-parent-")
        cls.addClassCleanup(rmtree, cls.base)
        cls.repo = Repo(os.path.join(cls.base, "repo"))
        copy_sources(cls.repo.path)
        cls.root = cls.repo.commit("root")
        cls.c1 = cls.repo.land(cls.root, "base")
        with open(os.path.join(cls.repo.path, "side.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic side branch\n")
        cls.side_branch = cls.repo.commit("side")
        cls.side = cls.repo.land(cls.c1, "side", cls.side_branch)
        cls.repo.write_ref("refs/heads/main", cls.c1)       # back to c1 for the main line
        os.remove(os.path.join(cls.repo.path, "side.txt"))
        cls.repo.git("add", "-A")                            # the index matches c1 again
        with open(os.path.join(cls.repo.path, "later.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic main line\n")
        cls.later = cls.repo.commit("main line")
        cls.m1 = cls.repo.land(cls.c1, "main line", cls.later)
        tree = cls.repo.tree_of(cls.m1)
        cls.merge = cls.repo.merge_commit(tree, (cls.m1, cls.side), "merge the side branch")
        cls.back = cls.repo.merge_commit(tree, (cls.side, cls.m1), "merge main into the side branch")
        cls.repo.write_ref("refs/heads/main", cls.merge)     # local main and HEAD; m1's tree, so a clean checkout
        cls.repo.fetched(cls.merge)                          # and origin/main, as fetched

    def release(self, commit):
        base = tempfile.mkdtemp(prefix="h-", dir=self.base)
        home = new_home(base, "home")
        before = tree_listing(home)
        outcome = launch(home, self.repo.path, "release", commit)
        return home, before, outcome

    def assertReleased(self, commit, outcome, home):
        code, out, err = outcome
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        self.assertEqual(release.verify_copy(os.path.join(roots.app_dir(home), commit[:12]))["commit"], commit)

    def test_commits_are_set_up_as_intended(self):
        git = self.repo.git
        self.assertEqual(git("rev-parse", "--verify", "-q", ORIGIN_MAIN), self.merge)
        self.assertEqual(git("rev-parse", "--verify", "-q", "HEAD"), self.merge)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.merge + "^1"), self.m1)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.merge + "^2"), self.side)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.back + "^1"), self.side)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.back + "^2"), self.m1)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.m1 + "^1"), self.c1)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.side + "^1"), self.c1)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.m1 + "^2"), self.later)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.side + "^2"), self.side_branch)
        self.assertEqual(git("rev-parse", "--verify", "-q", self.c1 + "^1"), self.root)

    def test_a_commit_inside_a_merged_branch_is_refused(self):
        # side is an ancestor of origin/main, so the ancestry check alone released it (before round 5 close)
        home, before, outcome = self.release(self.side)
        self.assertEqual(outcome, (2, "", "refused:release_not_first_parent\n"))
        self.assertEqual(tree_listing(home), before)

    def test_the_first_parent_line_is_released(self):
        for commit in (self.merge, self.m1, self.c1):        # origin/main itself, then its first parents
            with self.subTest(commit=commit):
                home, _before, outcome = self.release(commit)
                self.assertReleased(commit, outcome, home)
        # Its first commit has no second parent (release_not_merge_commit, since round 6); a branch's own commit
        # inside a merge stays off the line.
        for commit, code in ((self.root, "release_not_merge_commit"), (self.later, "release_not_first_parent"),
                             (self.side_branch, "release_not_first_parent")):
            with self.subTest(commit=commit):
                home, before, outcome = self.release(commit)
                self.assertEqual(outcome, (2, "", "refused:%s\n" % code))
                self.assertEqual(tree_listing(home), before)

    def test_the_first_parent_decides_not_ancestry_or_the_tree(self):
        self.addCleanup(self.repo.fetched, self.merge)
        self.repo.fetched(self.back)                         # side first: m1 is now the merged-in branch
        home, before, outcome = self.release(self.m1)
        self.assertEqual(outcome, (2, "", "refused:release_not_first_parent\n"))
        self.assertEqual(tree_listing(home), before)
        home, _before, outcome = self.release(self.side)
        self.assertReleased(self.side, outcome, home)
        self.repo.fetched(self.m1)                           # ancestry is checked first, and keeps its own code
        home, before, outcome = self.release(self.side)
        self.assertEqual(outcome, (2, "", "refused:release_not_on_main\n"))
        self.assertEqual(tree_listing(home), before)


class VerifyCopyTests(ReleaseTestCase):
    """Every way a copy can differ from its RELEASE.json, checked in this process on fresh copies."""

    def fresh(self, name=None):
        base = tempfile.mkdtemp(prefix="c-", dir=self.base)
        target = os.path.join(base, self.name1 if name is None else name)
        shutil.copytree(self.copy, target)
        return target

    def edit_manifest(self, root, change):
        path = os.path.join(root, "RELEASE.json")
        with open(path, encoding="ascii") as handle:
            manifest = json.load(handle)
        change(manifest)
        with writable(root, path):
            with open(path, "w", encoding="ascii") as handle:
                json.dump(manifest, handle)

    def code_of(self, root):
        try:
            release.verify_copy(root)
        except SuiteError as exc:
            return exc.code
        return "ok"

    def test_an_untouched_copy_passes(self):
        self.assertEqual(self.code_of(self.fresh()), "ok")

    def test_changed_files(self):
        root = self.fresh()
        victim = os.path.join(root, "bin", "_launch.py")
        with writable(os.path.dirname(victim), victim):
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("\n")
        self.assertEqual(self.code_of(root), "release_file_modified")
        root = self.fresh()
        os.chmod(os.path.join(root, "bin", "suite"), 0o400)                 # the executable bit is recorded
        self.assertEqual(self.code_of(root), "release_file_modified")
        root = self.fresh()
        os.chmod(os.path.join(root, "AGENTS.md"), 0o500)
        self.assertEqual(self.code_of(root), "release_file_modified")

    def test_a_consistently_edited_manifest_still_fails_the_tree(self):
        # Rewriting a file and its sha256 in RELEASE.json together is caught: the tree id is recomputed from bytes.
        root = self.fresh()
        victim = os.path.join(root, "AGENTS.md")
        with writable(root, victim):
            with open(victim, "ab") as handle:
                handle.write(b"\nsynthetic\n")
        with open(victim, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.edit_manifest(root, lambda manifest: manifest["files"].__setitem__("AGENTS.md", digest))
        self.assertEqual(self.code_of(root), "release_tree_mismatch")

    def test_missing_and_extra_entries(self):
        cases = {
            "missing": (lambda root: os.remove(os.path.join(root, "AGENTS.md")), (".",), "release_file_missing"),
            "extra_file": (lambda root: os.close(os.open(os.path.join(root, "bin", "extra.py"), os.O_CREAT, 0o400)),
                           ("bin",), "release_file_extra"),
            "extra_dir": (lambda root: os.mkdir(os.path.join(root, "docs"), 0o500), (".",), "release_file_extra"),
            "symlink": (lambda root: os.symlink("suite", os.path.join(root, "bin", "link")), ("bin",),
                        "release_file_extra"),
            "git_dir": (lambda root: os.mkdir(os.path.join(root, ".git"), 0o500), (".",), "release_file_extra"),
            "fifo": (lambda root: os.mkfifo(os.path.join(root, "pin", "fifo"), 0o400), ("pin",), "release_file_extra"),
            "replaced_by_symlink": (lambda root: (os.remove(os.path.join(root, "AGENTS.md")),
                                                  os.symlink("pin", os.path.join(root, "AGENTS.md"))), (".",),
                                    "release_file_extra"),
        }
        for name, (change, parents, code) in cases.items():
            root = self.fresh()
            with writable(*(os.path.normpath(os.path.join(root, parent)) for parent in parents)):
                change(root)
            self.assertEqual(self.code_of(root), code, name)

    def test_writable_entries(self):
        for relative, mode in (("bin/_launch.py", 0o600), ("bin", 0o700), (".", 0o700), ("RELEASE.json", 0o644),
                               ("pin/betangel-research.json", 0o420)):
            root = self.fresh()
            os.chmod(os.path.normpath(os.path.join(root, relative)), mode)
            self.assertEqual(self.code_of(root), "release_writable", relative)

    def test_the_manifest_itself(self):
        cases = {
            "garbage": lambda root, path: open(path, "w").write("{"),
            "missing": lambda root, path: os.remove(path),
            "duplicate_key": lambda root, path: open(path, "w").write('{"format": 1, "format": 1}'),
            "nan": lambda root, path: open(path, "w").write('{"format": NaN}'),
        }
        for name, change in cases.items():
            root = self.fresh()
            path = os.path.join(root, "RELEASE.json")
            with writable(root, path):
                change(root, path)
            self.assertEqual(self.code_of(root), "release_manifest_invalid", name)
        edits = {
            "format": lambda m: m.__setitem__("format", 1),
            "tag_key": lambda m: m.__setitem__("tag", "v1"),           # format 1's key
            "other_commit": lambda m: m.__setitem__("commit", "0" * 40),
            "format_bool": lambda m: m.__setitem__("format", True),
            "extra_key": lambda m: m.__setitem__("note", "x"),
            "short_commit": lambda m: m.__setitem__("commit", m["commit"][:12]),
            "tree_length": lambda m: m.__setitem__("tree", m["tree"] + "0" * 24),
            "bad_path": lambda m: m["files"].__setitem__("../outside", "0" * 64),
            "manifest_listed": lambda m: m["files"].__setitem__("RELEASE.json", "0" * 64),
            "unsorted_executables": lambda m: m.__setitem__("executables", ["bin/suite", "bin/suite"]),
            "unknown_executable": lambda m: m.__setitem__("executables", ["bin/nothing"]),
            "no_files": lambda m: m.__setitem__("files", {}),
        }
        for name, change in edits.items():
            root = self.fresh()
            self.edit_manifest(root, change)
            self.assertEqual(self.code_of(root), "release_manifest_invalid", name)

    def test_the_copy_directory_must_be_named_after_its_commit(self):
        for name in ("v1", "current", self.name3, self.c1[:11], self.c1[:13], self.c1, self.name1.upper()):
            self.assertEqual(self.code_of(self.fresh(name)), "release_manifest_invalid", name)


class NestedRepositoryTests(unittest.TestCase):
    """A repository nested in the checkout, whose own config defines a filter that the parent's filter query never
    sees. git status would enter a gitlink's repository and run that filter's clean command outside the guard, so
    a gitlink in the index refuses first (release_gitlink). Each test builds its own repositories: the class
    fixture's is shared, and the runner's git cannot remove a gitlink again."""

    def make_repo(self):
        """(base, repo, its first commit)."""
        base = tempfile.mkdtemp(prefix="rel-")
        self.addCleanup(rmtree, base)
        repo = Repo(os.path.join(base, "repo"))
        copy_sources(repo.path)
        return base, repo, repo.commit("first")

    @staticmethod
    def make_nested(repo):
        nested = Repo(os.path.join(repo.path, "nested"))
        with open(os.path.join(nested.path, "f.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic-1\n")
        nested.commit("nested")
        return nested

    @staticmethod
    def plant_filter(nested, marks):
        """A clean filter in the nested repository's own config, then a same-size edit that only it can judge."""
        os.makedirs(os.path.join(nested.path, ".git", "info"), exist_ok=True)
        with open(os.path.join(nested.path, ".git", "info", "attributes"), "w", encoding="ascii") as handle:
            handle.write("* filter=synthetic\n")
        with open(os.path.join(nested.path, ".git", "config"), "a", encoding="ascii") as handle:
            handle.write('[filter "synthetic"]\n\tclean = touch %s/clean && cat\n' % marks)
        sample = os.path.join(nested.path, "f.txt")
        with open(sample, "w", encoding="ascii") as handle:
            handle.write("synthetic-2\n")
        later = os.stat(sample).st_mtime + 3600
        os.utime(sample, (later, later))

    def check(self, base, repo, commit, code):
        home = new_home(base, "home")
        before = tree_listing(home)
        self.assertEqual(launch(home, repo.path, "release", commit), (2, "", "refused:%s\n" % code))
        self.assertEqual(tree_listing(home), before)

    def test_a_gitlink_is_refused_before_git_status_can_enter_it(self):
        for committed in (False, True):
            base, repo, commit = self.make_repo()
            nested = self.make_nested(repo)
            repo.git("add", "nested")                   # an embedded repository is added as a gitlink
            if committed:
                repo.git("commit", "-q", "-m", "gitlink")
            marks = tempfile.mkdtemp(prefix="marks-", dir=base)
            self.plant_filter(nested, marks)
            self.check(base, repo, commit, "release_gitlink")
            self.assertEqual(os.listdir(marks), [], "no filter command ran (committed=%s)" % committed)

    def test_status_still_sees_an_untracked_nested_repository_and_a_removed_gitlink(self):
        # git status never enters a submodule (--ignore-submodules=dirty), but still reports what the parent
        # records: an untracked repository, and a gitlink in HEAD whose removal is staged (=all would hide that).
        base, repo, commit = self.make_repo()
        marks = tempfile.mkdtemp(prefix="marks-", dir=base)
        self.plant_filter(self.make_nested(repo), marks)
        self.check(base, repo, commit, "release_dirty_tree")
        self.assertEqual(os.listdir(marks), [])
        base, repo, commit = self.make_repo()
        nested = self.make_nested(repo)
        repo.git("add", "nested")
        repo.git("commit", "-q", "-m", "gitlink")
        rmtree(nested.path)
        repo.git("add", "-A")                           # stages the gitlink's removal: the index has none now
        self.check(base, repo, commit, "release_dirty_tree")


class CommitAndTreeTests(unittest.TestCase):

    def test_commit_names(self):
        for commit in ("0123456789abcdef" * 2 + "01234567", "f" * 40, "0" * 64, "a1" * 32):
            self.assertTrue(release.commit_ok(commit), commit)
            self.assertEqual(release.parse_args([commit]), {"commit": commit})
            self.assertEqual(release.copy_name(commit), commit[:12])
        for commit in ("", "v1", "main", "HEAD", "current", "refs/heads/main", "f" * 12, "f" * 39, "f" * 41, "f" * 63,
                       "f" * 65, "F" * 40, "g" * 40, "f" * 40 + "\n", " " + "f" * 40, "f" * 40 + "^{commit}",
                       "f" * 38 + "~1", "../" + "f" * 40, "é" * 40):
            self.assertFalse(release.commit_ok(commit), repr(commit))
            with self.assertRaises(SuiteError) as caught:
                release.parse_args([commit])
            self.assertEqual(caught.exception.code, "release_commit_invalid", repr(commit))
        self.assertFalse(release.commit_ok(None))
        for args in ([], ["f" * 40, "e" * 40], ["f" * 40, "--force"]):
            with self.assertRaises(SuiteError) as caught:
                release.parse_args(args)
            self.assertEqual(caught.exception.code, "bad_arguments", args)

    def test_tree_id_matches_git(self):
        # Names chosen to exercise git's tree order (a directory sorts as if its name ended in "/").
        base = tempfile.mkdtemp(prefix="tree-")
        self.addCleanup(rmtree, base)
        repo = Repo(os.path.join(base, "repo"))
        names = ("a.txt", "a/b.txt", "a-b/c", "a0", "ab/x/y/z.txt", "b.sh", "B", "a/b/c.txt", "empty")
        for index, relpath in enumerate(names):
            path = os.path.join(repo.path, *relpath.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"" if relpath == "empty" else b"synthetic %d\n" % index)
        os.chmod(os.path.join(repo.path, "b.sh"), 0o755)
        commit = repo.commit("tree")
        hashes, blobs, executables = release.hash_files(repo.path, list(names), "sha1")
        self.assertEqual(executables, ["b.sh"])
        self.assertEqual(release.tree_id(blobs, executables, "sha1"), repo.git("rev-parse", "--verify", "-q",
                                                                                commit + "^{tree}"))
        self.assertEqual(hashes["empty"], hashlib.sha256(b"").hexdigest())

    def test_relpaths(self):
        for path in ("a", "a/b", "bin/suite", ".gitignore", "a.git"):
            self.assertTrue(release.relpath_ok(path), path)
        for path in ("", "/a", "a/", "a//b", "./a", "a/./b", "a/../b", "..", ".git", "a/.GIT/b", "a\\b", "a\0b",
                     "\udcff"):
            self.assertFalse(release.relpath_ok(path), repr(path))


if __name__ == "__main__":
    unittest.main()
