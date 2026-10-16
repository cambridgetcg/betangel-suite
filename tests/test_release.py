"""I-18: release copies (betangel_suite/release.py; DESIGN.md 3.4, 8.6) and their check at every launch.

No real release is ever made. Everything runs in a temporary git repository under TMPDIR, built from this
checkout's launcher, package and pin with the runner's local git (guard.runner_git_ok: init, add, commit,
rev-parse), and in temporary HOMEs; nothing here touches the real ~/.local/share/betangel-suite. The runner's
git has no tag subcommand, so tags are written as git refs: v1 an annotated tag object, v2 and side
lightweight. side names a commit that main does not contain (main is pointed back at the first commit).

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

from betangel_suite import guard, release, roots
from betangel_suite.errors import SuiteError
from tests import FORBID, PYTHON, ROOT, child_env, make_home, rmtree, run_relayed, tree_listing

SOURCES = ("bin", "betangel_suite", "pin")
SOURCE_FILES = ("AGENTS.md",)
IDENTITY = {"GIT_AUTHOR_NAME": "Synthetic Tester", "GIT_AUTHOR_EMAIL": "tester@example.invalid",
            "GIT_COMMITTER_NAME": "Synthetic Tester", "GIT_COMMITTER_EMAIL": "tester@example.invalid"}
RELEASED_RE = r"\Areleased files=([0-9]+) bytes=([0-9]+) current=switched\n\Z"


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

    def annotated_tag(self, name, commit):
        """A loose annotated tag object for commit, and refs/tags/<name> naming it (as `git tag -a` would)."""
        body = ("object %s\ntype commit\ntag %s\ntagger Synthetic Tester <tester@example.invalid> 86400 +0000\n\n"
                "synthetic release\n" % (commit, name)).encode("ascii")
        data = b"tag %d\0" % len(body) + body
        object_id = hashlib.sha1(data).hexdigest()
        path = os.path.join(self.path, ".git", "objects", object_id[:2], object_id[2:])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(zlib.compress(data))
        self.write_ref("refs/tags/" + name, object_id)
        return object_id

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


def new_home(base, name):
    """A temporary HOME with .local/state, the state tmp/ and the share dir (whose app/ release creates)."""
    home = os.path.join(base, name)
    os.makedirs(roots.tmp_dir("test", home), mode=0o700)
    os.makedirs(roots.share_dir(home), mode=0o700)
    return home


def launch(home, root, *args):
    """root's bin/_launch.py with args, as bin/suite runs it (env of child_env(home)); (code, stdout, stderr)."""
    result = subprocess.run([PYTHON, "-I", "-S", "-B", os.path.join(root, "bin", "_launch.py"), *args],
                            env=child_env(home), cwd=home, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


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
    """One repository and one release of v1 for the whole class; each test uses its own HOME."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="rel-")
        cls.addClassCleanup(rmtree, cls.base)
        cls.repo = Repo(os.path.join(cls.base, "repo"))
        copy_sources(cls.repo.path)
        cls.c1 = cls.repo.commit("first")
        cls.tree1 = cls.repo.git("rev-parse", "--verify", "-q", cls.c1 + "^{tree}")
        cls.files1 = cls.repo.files()
        cls.repo.annotated_tag("v1", cls.c1)
        cls.repo.write_ref("refs/tags/v2", cls.c1)
        with open(os.path.join(cls.repo.path, "side.txt"), "w", encoding="ascii") as handle:
            handle.write("synthetic side branch\n")
        cls.c2 = cls.repo.commit("side")
        cls.repo.write_ref("refs/tags/side", cls.c2)
        cls.repo.write_ref("refs/heads/main", cls.c1)       # main no longer contains c2
        os.remove(os.path.join(cls.repo.path, "side.txt"))
        cls.repo.git("add", "-A")                            # the index matches c1 again: a clean tree
        cls.home = new_home(cls.base, "home")
        cls.app = roots.app_dir(cls.home)
        cls.copy = os.path.join(cls.app, "v1")
        cls.result = launch(cls.home, cls.repo.path, "release", "v1")

    def release(self, home, tag):
        return launch(home, self.repo.path, "release", tag)

    def fresh_home(self):
        base = tempfile.mkdtemp(prefix="h-", dir=self.base)
        return new_home(base, "home")

    def place_copy(self, home, name="v1", *, current=True):
        """A copy of the class's release under home's app root (modes preserved), and app/current to it."""
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

    def test_tags_are_set_up_as_intended(self):
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/tags/v1^{commit}"), self.c1)
        self.assertNotEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/tags/v1"), self.c1)   # annotated
        self.assertEqual(self.repo.git("rev-parse", "--verify", "-q", "refs/heads/main"), self.c1)

    def test_release_installs_a_read_only_copy_of_the_tag(self):
        code, out, err = self.result
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        files, size = (int(value) for value in re.match(RELEASED_RE, out).groups())
        self.assertEqual(files, len(self.files1))
        self.assertEqual(size, sum(os.path.getsize(os.path.join(self.repo.path, p)) for p in self.files1))
        self.assertNotIn(self.c1, out)
        self.assertEqual(sorted(os.listdir(self.app)), ["current", "v1"])
        self.assertEqual(os.readlink(os.path.join(self.app, "current")), "v1")
        with open(os.path.join(self.copy, "RELEASE.json"), encoding="ascii") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest, {
            "format": 1, "tag": "v1", "commit": self.c1, "tree": self.tree1,
            "files": {path: digest for path, (digest, _x) in self.files1.items()},
            "executables": sorted(path for path, (_d, executable) in self.files1.items() if executable)})
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
        self.assertEqual(status, release.Status("release", "v1", self.c1, self.tree1))
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
        self.assertEqual(release.status_of(spell(target), home), release.Status("release", "v1", self.c1, self.tree1))
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
        self.check_spelling(lambda path: "/APP".join(path.rsplit("/app", 1)))       # .../APP/v1 and .../APP

    def test_the_data_volume_firmlink_spelling_of_a_copy_is_still_verified(self):
        # On macOS /Users is also /System/Volumes/Data/Users, an alias realpath does not resolve.
        self.check_spelling(lambda path: "/System/Volumes/Data" + path)

    def test_a_release_copy_still_refuses_every_data_root(self):
        # Phase 0: the release status enables nothing; serve from a copy refuses a configured data root.
        home = make_home(self, deps=True)
        os.makedirs(roots.share_dir(home), exist_ok=True)
        target = self.place_copy(home)
        with open(roots.config_path(home), "w", encoding="ascii") as handle:
            json.dump({"data_roots": ["~/betangel-data/historic-pro"]}, handle)
        self.assertRefused(launch(home, target, "serve", "--port", "0"), "synthetic_only")
        self.assertFalse(os.path.lexists(roots.data_home(home)))

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
        self.assertRefused(launch(self.home, self.copy, "release", "v2"), "release_not_a_checkout")
        self.assertEqual(tree_listing(self.app), before)

    def test_unknown_and_unreachable_tags_are_refused(self):
        home = self.fresh_home()
        before = tree_listing(home)
        self.assertRefused(self.release(home, "v9"), "release_tag_unknown")
        self.assertRefused(self.release(home, "main"), "release_tag_unknown")     # a branch is not a tag
        self.assertRefused(self.release(home, "side"), "release_not_on_main")
        self.assertRefused(self.release(home, "../v1"), "release_tag_invalid")
        self.assertEqual(launch(home, self.repo.path, "release"), (2, "", "refused:bad_arguments\n"))
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
        self.assertRefused(self.release(home, "v1"), "release_dirty_tree")
        self._restore(tracked, original)
        untracked = os.path.join(self.repo.path, "bin", "untracked.txt")
        self.addCleanup(lambda: os.path.lexists(untracked) and os.remove(untracked))
        with open(untracked, "w", encoding="ascii") as handle:
            handle.write("synthetic\n")
        self.assertRefused(self.release(home, "v1"), "release_dirty_tree")
        self.assertEqual(tree_listing(home), before)

    @staticmethod
    def _restore(path, data):
        with open(path, "wb") as handle:
            handle.write(data)

    def test_a_second_release_switches_current_and_an_existing_one_is_refused(self):
        home = self.fresh_home()
        app = roots.app_dir(home)
        self.assertEqual(self.release(home, "v1")[0], 0)
        os.symlink("v1", os.path.join(app, ".current.partial"))      # left by an interrupted release
        os.mkdir(os.path.join(app, ".v2.partial"))
        self.assertRefused(self.release(home, "v2"), "partial_exists")
        os.rmdir(os.path.join(app, ".v2.partial"))
        code, out, err = self.release(home, "v2")
        self.assertEqual((code, err), (0, ""), err)
        self.assertRegex(out, RELEASED_RE)
        self.assertEqual(os.readlink(os.path.join(app, "current")), "v2")
        self.assertEqual(sorted(os.listdir(app)), ["current", "v1", "v2"])
        before = tree_listing(app)
        self.assertRefused(self.release(home, "v1"), "release_exists")
        self.assertEqual(tree_listing(app), before)
        for tag in ("v1", "v2"):
            manifest = release.verify_copy(os.path.join(app, tag))
            self.assertEqual((manifest["tag"], manifest["commit"], manifest["tree"]), (tag, self.c1, self.tree1))

    def test_current_must_be_a_symlink(self):
        home = self.fresh_home()
        os.makedirs(os.path.join(roots.app_dir(home), "current"))
        before = tree_listing(home)
        self.assertRefused(self.release(home, "v1"), "release_current_invalid")
        self.assertEqual(tree_listing(home), before)

    def test_the_run_marker_refuses_a_release(self):
        home = self.fresh_home()
        marker = os.path.join(home, ".local", "state", "lab-runs", "ACTIVE")
        os.makedirs(os.path.dirname(marker))
        open(marker, "w").close()
        before = tree_listing(home)
        self.assertRefused(self.release(home, "v1"), "run_marker_present")
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
                "errors.install_excepthooks()\nfrom betangel_suite import release\ntry:\n    release.make('v1')\n"
                "except errors.SuiteError as exc:\n    sys.stderr.write(errors.describe(exc) + '\\n')\n    sys.exit(2)\n"
                % self.repo.path)
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
            self.assertRefused(self.release(home, "v1"), "release_git_filter")
        self.assertEqual(os.listdir(marks), [], "no filter command ran")
        self.assertEqual(tree_listing(home), before)

    def test_the_share_dir_must_exist(self):
        home = self.fresh_home()
        rmtree(roots.share_dir(home))
        self.assertRefused(self.release(home, "v1"), "root_parent_missing")
        self.assertFalse(os.path.lexists(roots.share_dir(home)))


class VerifyCopyTests(ReleaseTestCase):
    """Every way a copy can differ from its RELEASE.json, checked in this process on fresh copies."""

    def fresh(self, name="v1"):
        base = tempfile.mkdtemp(prefix="c-", dir=self.base)
        target = os.path.join(base, name)
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
            "format": lambda m: m.__setitem__("format", 2),
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

    def test_the_copy_directory_must_be_named_after_its_tag(self):
        self.assertEqual(self.code_of(self.fresh("v2")), "release_manifest_invalid")
        self.assertEqual(self.code_of(self.fresh("current")), "release_manifest_invalid")


class TagAndTreeTests(unittest.TestCase):

    def test_tag_names(self):
        for tag in ("v1", "v0.1.0", "phase0-c", "2026.10.15", "V_1", "a" * 64):
            self.assertTrue(release.tag_ok(tag), tag)
            self.assertEqual(release.parse_args([tag]), {"tag": tag})
        for tag in ("", "-v", ".v1", "v1.", "v1.lock", "a..b", "../v1", "v1/x", "v 1", "current", "Current", "v1^",
                    "v1~1", "v1:x", "v1@{0}", "v1*", "a" * 65, "v1\n", "é1"):
            self.assertFalse(release.tag_ok(tag), tag)
            with self.assertRaises(SuiteError) as caught:
                release.parse_args([tag])
            self.assertEqual(caught.exception.code, "release_tag_invalid", tag)
        for args in ([], ["v1", "v2"], ["v1", "--force"]):
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
