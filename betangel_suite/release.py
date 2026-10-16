"""Release copies (DESIGN.md 3.4, 8.6; invariant I-18): `bin/suite release <tag>` and the RELEASE.json check.

Every command Yu runs uses a release copy, ~/.local/share/betangel-suite/app/current/bin/suite: a git archive
of a reviewed tag on the local main branch, read-only, with a RELEASE.json that names the tag, the commit,
the git tree and the sha256 of every file.

make(tag), the release command (guard mode "release"), in this order:

  1. refuse a tag that is not a plain name (release_tag_invalid), a checkout that is a release copy or has no
     .git (release_not_a_checkout), an app/current that is not a symlink (release_current_invalid), an
     existing app/<tag> (release_exists) or a left-over app/.<tag>.partial (partial_exists);
  2. git, only through the guard's release argvs (guard.release_argv_ok) on this checkout: a filter driver
     defined in the repository's own config (release_git_filter: git status and git archive would run its
     commands outside the guard; checked first, by a read-only config query); a dirty tree,
     tracked or untracked (release_dirty_tree); an unknown tag, looked up as refs/tags/<tag> only
     (release_tag_unknown); no local main branch (release_main_missing); a tag commit that main does not
     contain (release_not_on_main). Nothing is fetched;
  3. git archive of the tag's commit (by object id, so a moved tag cannot change what is copied) into
     app/.<tag>.partial, regular files and directories only; then guard.seal(): no subprocess from here on;
  4. the git tree id is recomputed from the copied bytes and must equal the commit's tree
     (release_tree_mismatch): what is copied is exactly the tagged tree, whatever .gitattributes say;
  5. RELEASE.json is written, everything is made read-only (files 0400 or 0500, directories 0500), the run
     marker is checked again, the copy is renamed to app/<tag> and verified as a launch would verify it;
  6. app/current is switched atomically (a new relative symlink renamed over the old one).

A failure before the switch removes the partial or new copy. Output is one line of counts.

check_launch(root), called by bin/_launch.py before any command runs: a launcher root below the app root must
be app/<tag> and must match its RELEASE.json exactly: every listed file present with its sha256 and
executable bit, nothing else (no extra file, directory or symlink), nothing writable, everything owned by
this user, and the tree id recomputed from the bytes equal to the recorded tree. Any mismatch refuses with a
release_* code. A root anywhere else is a working checkout and keeps the synthetic-only behaviour.

status() tells engine code which of the two it runs (for session.json later). It enables nothing: in Phase 0
the engine refuses every data root either way (synthetic_only).

The same-user limit of DESIGN.md 9.4 applies: read-only modes stop accidents, not the owner, and a process
that rewrites a copy can rewrite its RELEASE.json too. The recorded tree id is recomputed from the bytes, so
it always names the code that actually runs. Standard library only; never imports betangel_research.
"""

import collections
import hashlib
import json
import os
import re
import stat
import sys

from . import guard, roots
from .errors import SuiteError

FORMAT = 1
MANIFEST = "RELEASE.json"
CURRENT = "current"
MAIN_REF = "refs/heads/main"
MANIFEST_KEYS = frozenset({"format", "tag", "commit", "tree", "files", "executables"})
MAX_FILES = 20000
MAX_BYTES = 64 << 20                 # all files of one copy together
MAX_MANIFEST_BYTES = 8 << 20
GIT_TIMEOUT_S = 120
FILE_MODE, EXEC_MODE, DIR_MODE = 0o400, 0o500, 0o500
REPO_ROOT = guard.REPO_ROOT
_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

Status = collections.namedtuple("Status", "kind tag commit tree")
CHECKOUT = Status("checkout", None, None, None)
_STATUS = None


# --- tags and paths ------------------------------------------------------------------------------

def tag_ok(tag):
    """A plain tag name: guard.RELEASE_TAG_RE, no "..", no ".lock" or "." ending, and never "current"."""
    return (isinstance(tag, str) and bool(guard.RELEASE_TAG_RE.fullmatch(tag)) and ".." not in tag
            and not tag.endswith((".", ".lock")) and tag.casefold() != CURRENT)


def parse_args(args):
    """{"tag": tag} for `release <tag>`."""
    args = list(args)
    if len(args) != 1:
        raise SuiteError("bad_arguments")
    if not tag_ok(args[0]):
        raise SuiteError("release_tag_invalid")
    return {"tag": args[0]}


def relpath_ok(relpath):
    """A relative "/"-separated path with no empty, ".", ".." or .git component and no NUL or backslash."""
    if not isinstance(relpath, str) or not 0 < len(relpath) <= 1024 or "\0" in relpath or "\\" in relpath:
        return False
    try:
        relpath.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return all(part not in ("", ".", "..") and part.casefold() != ".git" for part in relpath.split("/"))


# --- launch-time check and status ----------------------------------------------------------------

def check_launch(root, home_dir=None):
    """bin/_launch.py, before any command: verify a release copy, or note a working checkout; return the Status."""
    global _STATUS
    real = os.path.realpath(root)
    if real != os.path.realpath(REPO_ROOT):
        raise SuiteError("release_layout_invalid")     # the launcher runs code from somewhere else
    _STATUS = status_of(real, home_dir)
    return _STATUS


def status(home_dir=None):
    """The Status of the code this process runs: kind "release" (with tag, commit, tree) or "checkout".

    Computed once per process: bin/_launch.py does it (check_launch) before any command runs.
    """
    global _STATUS
    if _STATUS is None:
        _STATUS = status_of(os.path.realpath(REPO_ROOT), home_dir)
    return _STATUS


def status_of(root, home_dir=None):
    """The Status of the code at root; SuiteError for a release copy that does not match its RELEASE.json.

    Whether root lies in the app root is decided by (st_dev, st_ino), not by spelling: realpath keeps a case
    variant or the /System/Volumes/Data firmlink alias of a copy as given, and such a path must still be verified.
    """
    app = _file_id(roots.app_dir(home_dir))
    real = os.path.realpath(root)
    if app is None:
        return CHECKOUT                                 # no app root, so no release copy
    path, depth = real, 0
    while _file_id(path) != app:
        parent = os.path.dirname(path)
        if parent == path:
            return CHECKOUT
        path, depth = parent, depth + 1
    if depth != 1:
        raise SuiteError("release_layout_invalid")     # only app/<tag> itself is a release copy
    manifest = verify_copy(real)
    return Status("release", manifest["tag"], manifest["commit"], manifest["tree"])


def _file_id(path):
    """(st_dev, st_ino) of path, symlinks followed; None when it does not exist."""
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        raise SuiteError("release_layout_invalid") from None
    return info.st_dev, info.st_ino


def verify_copy(root):
    """Check the release copy at root against its RELEASE.json; return the manifest (I-18)."""
    manifest = load_manifest(root)
    entries = walk(root)
    if any(mode & 0o222 for _kind, mode in entries.values()):
        raise SuiteError("release_writable")
    files = {path for path, (kind, _mode) in entries.items() if kind == "file"} - {MANIFEST}
    expected = set(manifest["files"])
    if expected - files:
        raise SuiteError("release_file_missing")
    needed_dirs = {"/".join(path.split("/")[:depth]) for path in expected for depth in range(1, path.count("/") + 1)}
    dirs = {path for path, (kind, _mode) in entries.items() if kind == "dir" and path}
    if files - expected or dirs != needed_dirs:
        raise SuiteError("release_file_extra")
    algorithm = _algorithm(manifest["commit"])
    hashes, blobs, executables = hash_files(root, expected, algorithm)
    if hashes != manifest["files"] or sorted(executables) != manifest["executables"]:
        raise SuiteError("release_file_modified")
    if tree_id(blobs, executables, algorithm) != manifest["tree"]:
        raise SuiteError("release_tree_mismatch")
    return manifest


def load_manifest(root):
    """RELEASE.json of the copy at root, strictly checked; SuiteError(release_manifest_invalid) otherwise."""
    data = _read_regular(os.path.join(root, MANIFEST), MAX_MANIFEST_BYTES)
    manifest = None
    if data is not None:
        try:
            manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            manifest = None
    if not _manifest_ok(manifest, os.path.basename(root)):
        raise SuiteError("release_manifest_invalid")
    return manifest


def _manifest_ok(manifest, name):
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        return False
    commit, tree, files, executables = (manifest["commit"], manifest["tree"], manifest["files"],
                                        manifest["executables"])
    return (type(manifest["format"]) is int and manifest["format"] == FORMAT and manifest["tag"] == name
            and tag_ok(name) and isinstance(commit, str) and isinstance(tree, str)
            and bool(_OBJECT_ID_RE.fullmatch(commit)) and bool(_OBJECT_ID_RE.fullmatch(tree))
            and len(commit) == len(tree) and isinstance(files, dict) and 0 < len(files) <= MAX_FILES
            and all(relpath_ok(path) and path != MANIFEST and isinstance(value, str) and _SHA256_RE.fullmatch(value)
                    for path, value in files.items())
            and isinstance(executables, list) and executables == sorted(set(executables))
            and all(isinstance(path, str) and path in files for path in executables))


# --- walking, hashing and the git tree id ---------------------------------------------------------

def walk(root):
    """{relpath: ("file" | "dir", permission bits)} for root ("") and everything below it; no symlink followed.

    Anything that is neither a regular file nor a directory (a symlink, FIFO, socket or device) is
    release_file_extra, an entry not owned by this user is wrong_owner, and a name that could not come from
    a git tree is release_file_extra. An entry that vanishes during the walk is release_file_missing.
    """
    found = {}
    uid = os.getuid()
    pending = [""]
    while pending:
        relative = pending.pop()
        path = os.path.join(root, relative) if relative else root
        try:
            info = os.lstat(path)
            names = None
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(path) as listing:
                    names = sorted(entry.name for entry in listing)
        except OSError:
            info = None
        if info is None:
            raise SuiteError("release_file_missing")
        if info.st_uid != uid:
            raise SuiteError("wrong_owner")
        if names is not None:
            found[relative] = ("dir", stat.S_IMODE(info.st_mode))
            for name in names:
                child = relative + "/" + name if relative else name
                if not relpath_ok(child):
                    raise SuiteError("release_file_extra")
                pending.append(child)
        elif stat.S_ISREG(info.st_mode) and relative:
            found[relative] = ("file", stat.S_IMODE(info.st_mode))
        else:
            raise SuiteError("release_file_extra")
        if len(found) > 2 * MAX_FILES:
            raise SuiteError("release_file_extra")
    return found


def hash_files(root, relpaths, algorithm):
    """({relpath: sha256 hex}, {relpath: git blob id bytes}, [executable relpaths]) of regular files under root."""
    hashes, blobs, executables, total = {}, {}, [], 0
    for relpath in sorted(relpaths):
        fd = info = data = None
        try:
            fd = os.open(os.path.join(root, relpath), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(fd)
            total += info.st_size
            if stat.S_ISREG(info.st_mode) and total <= MAX_BYTES:
                data = _read_all(fd, info.st_size)
        except OSError:
            data = None
        finally:
            if fd is not None:
                os.close(fd)
        if data is None:                                # changed under us since the walk, or too large
            raise SuiteError("release_file_modified")
        hashes[relpath] = hashlib.sha256(data).hexdigest()
        blobs[relpath] = _object_id(b"blob", data, algorithm)
        if info.st_mode & stat.S_IXUSR:
            executables.append(relpath)
    return hashes, blobs, executables


def tree_id(blobs, executables, algorithm):
    """The git tree id (hex) of files {relpath: blob id bytes}, 100755 for executables and 100644 otherwise."""
    executables = set(executables)
    nested = {}
    for relpath, blob in blobs.items():
        node = nested
        parts = relpath.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (b"100755" if relpath in executables else b"100644", blob)
    return _tree(nested, algorithm).hex()


def _tree(node, algorithm):
    # git orders tree entries by name bytes, comparing a directory as if its name ended in "/".
    entries = []
    for name, value in node.items():
        raw = name.encode("utf-8")
        if isinstance(value, dict):
            entries.append((raw + b"/", b"40000", raw, _tree(value, algorithm)))
        else:
            entries.append((raw, value[0], raw, value[1]))
    entries.sort()
    body = b"".join(mode + b" " + raw + b"\0" + oid for _key, mode, raw, oid in entries)
    return _object_id(b"tree", body, algorithm)


def _object_id(kind, body, algorithm):
    return hashlib.new(algorithm, kind + b" %d\0" % len(body) + body).digest()


def _algorithm(object_id):
    return "sha1" if len(object_id) == 40 else "sha256"


# --- the release command -------------------------------------------------------------------------

def main(options):
    """cli handler: release options["tag"]; returns 0 or raises SuiteError."""
    return make(options["tag"])


def make(tag, home_dir=None, *, out=None):
    """bin/suite release <tag> (module docstring); prints one line of counts."""
    guard.require_mode("release")
    out = sys.stdout if out is None else out
    if not tag_ok(tag):
        raise SuiteError("release_tag_invalid")
    home = roots.home() if home_dir is None else os.path.normpath(home_dir)
    repo = REPO_ROOT                                    # exactly the -C directory guard.release_argv_ok allows
    app = roots.app_dir(home)
    if (roots.within(os.path.realpath(repo), os.path.realpath(app))
            or not os.path.lexists(os.path.join(repo, ".git"))):
        raise SuiteError("release_not_a_checkout")
    target = os.path.join(app, tag)
    partial = os.path.join(app, "." + tag + ".partial")
    current = os.path.join(app, CURRENT)
    staged_link = os.path.join(app, ".current.partial")
    _check_current(current)
    if os.path.lexists(target):
        raise SuiteError("release_exists")
    if os.path.lexists(partial):
        raise SuiteError("partial_exists")

    git = _Git(repo, home)
    if git.filters_configured():
        raise SuiteError("release_git_filter")
    if git.output("status", "--porcelain=v1", "-z", "--untracked-files=all") != b"":
        raise SuiteError("release_dirty_tree")
    commit = git.object_id("refs/tags/%s^{commit}" % tag)
    if commit is None:
        raise SuiteError("release_tag_unknown")
    main_commit = git.object_id(MAIN_REF + "^{commit}")
    if main_commit is None:
        raise SuiteError("release_main_missing")
    if not git.is_ancestor(commit, main_commit):
        raise SuiteError("release_not_on_main")
    tree = git.object_id(commit + "^{tree}")
    if tree is None or len(tree) != len(commit):
        raise SuiteError("git_failed")

    _make_app_dir(app)
    created = partial
    switched = False
    os.mkdir(partial, 0o700)
    try:
        count, total = git.archive(commit, partial)
        guard.seal()                                    # no subprocess from here on
        manifest = _manifest(partial, tag, commit, tree)
        _write_new(os.path.join(partial, MANIFEST), _manifest_bytes(manifest), FILE_MODE)
        _make_read_only(partial, set(manifest["executables"]))
        _require_no_run_marker()
        if os.path.lexists(target):
            raise SuiteError("release_exists")
        os.rename(partial, target)
        created = target
        os.chmod(target, DIR_MODE)
        if verify_copy(target) != manifest:
            raise SuiteError("release_file_modified")
        _check_current(current)
        if os.path.lexists(staged_link):                # left by an interrupted release
            if not os.path.islink(staged_link):
                raise SuiteError("release_current_invalid")
            os.remove(staged_link)
        os.symlink(tag, staged_link)                    # relative: app/current -> <tag>
        os.rename(staged_link, current)                 # atomic replacement of the old link
        switched = True
    finally:
        if not switched:
            _remove_tree(created)
            if os.path.islink(staged_link):
                os.remove(staged_link)
    out.write("released files=%d bytes=%d current=switched\n" % (count, total))
    out.flush()
    return 0


class _Git:
    """The git argvs guard.release_argv_ok allows, on this checkout only; output is never printed."""

    def __init__(self, repo, home):
        self.prefix = list(guard.RELEASE_GIT_PREFIX) + ["-C", repo]
        tmp = os.environ.get("TMPDIR", "")
        self.env = {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": "C", "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", guard.FORBID_NETWORK_ENV: "1"}
        if tmp:
            self.env["TMPDIR"] = tmp                    # where /usr/bin/git's xcrun shim keeps its cache

    def run(self, *args):
        import subprocess
        try:
            result = subprocess.run(self.prefix + list(args), env=self.env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is None:
            raise SuiteError("git_failed")
        return result.returncode, result.stdout

    def output(self, *args):
        returncode, stdout = self.run(*args)
        if returncode != 0:
            raise SuiteError("git_failed")
        return stdout

    def filters_configured(self):
        """True when the repository's own config, its includes followed, defines any filter.<driver>.* key.

        The prefix switches off hooks, fsmonitor and the global attributes file, but a filter driver set in the
        repository's config runs whenever attributes (.gitattributes or info/attributes) name it: its clean command
        under git status, its smudge command under git archive, as this user and outside the guard. The tree id
        check would catch changed bytes, not what the command did; so no git command but this query runs then.
        """
        returncode, stdout = self.run(*guard.RELEASE_FILTER_QUERY)
        if returncode == 1 and not stdout:
            return False
        if returncode == 0:
            return True
        raise SuiteError("git_failed")

    def object_id(self, revision):
        """The object id revision names, or None when it names nothing (rev-parse --verify --quiet exits 1)."""
        returncode, stdout = self.run("rev-parse", "--verify", "--quiet", revision)
        text = stdout.decode("ascii", "replace").strip()
        if returncode == 0 and _OBJECT_ID_RE.fullmatch(text):
            return text
        if returncode == 1 and not text:
            return None
        raise SuiteError("git_failed")

    def is_ancestor(self, commit, descendant):
        returncode, _stdout = self.run("merge-base", "--is-ancestor", commit, descendant)
        if returncode not in (0, 1):
            raise SuiteError("git_failed")
        return returncode == 0

    def archive(self, commit, dest):
        """git archive --format=tar <commit>, unpacked into dest; returns (files, bytes)."""
        import subprocess
        process = subprocess.Popen(self.prefix + ["archive", "--format=tar", commit], env=self.env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            counts = _unpack(process.stdout, dest)
            _drain(process.stdout)
            returncode = process.wait(GIT_TIMEOUT_S)
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            process.stdout.close()
        if returncode != 0:
            raise SuiteError("git_failed")
        return counts


def _unpack(stream, dest):
    """Regular files and directories of a tar stream into dest (O_EXCL, no symlinks); returns (files, bytes)."""
    import tarfile
    count = total = 0
    try:
        with tarfile.open(fileobj=stream, mode="r|", encoding="utf-8", errors="strict") as archive:
            for member in archive:
                relpath = member.name
                if not relpath_ok(relpath) or relpath == MANIFEST:
                    raise SuiteError("release_archive_invalid")
                if member.isdir():
                    _make_dirs(dest, relpath)
                    continue
                if not member.isreg():
                    raise SuiteError("release_archive_invalid")     # symlinks, links, devices, FIFOs
                count += 1
                total += member.size
                if count > MAX_FILES or total > MAX_BYTES:
                    raise SuiteError("release_archive_invalid")
                if "/" in relpath:
                    _make_dirs(dest, relpath.rpartition("/")[0])
                _write_new(os.path.join(dest, relpath), archive.extractfile(member),
                           0o700 if member.mode & 0o100 else 0o600)
    except (tarfile.TarError, UnicodeError, EOFError):
        raise SuiteError("release_archive_invalid") from None
    return count, total


def _drain(stream):
    """Read what follows the end-of-archive marker: zero padding only, at most 1 MiB."""
    seen = 0
    while True:
        chunk = stream.read(1 << 16)
        if not chunk:
            return
        seen += len(chunk)
        if chunk.strip(b"\0") or seen > 1 << 20:
            raise SuiteError("release_archive_invalid")


def _make_dirs(dest, relpath):
    current = dest
    for part in relpath.split("/"):
        current = os.path.join(current, part)
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(current).st_mode):
            raise SuiteError("release_archive_invalid")


def _write_new(path, source, mode):
    """Create path (O_EXCL, O_NOFOLLOW) with mode and the bytes of source (a file object or bytes)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        if isinstance(source, bytes):
            chunks = (source,)
        else:
            chunks = iter(lambda: source.read(1 << 20), b"")
        for chunk in chunks:
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _manifest(root, tag, commit, tree):
    """RELEASE.json for the unpacked copy at root, after checking its bytes against the commit's tree."""
    entries = walk(root)
    files = {path for path, (kind, _mode) in entries.items() if kind == "file"}
    if not files:
        raise SuiteError("release_archive_invalid")
    algorithm = _algorithm(commit)
    hashes, blobs, executables = hash_files(root, files, algorithm)
    if tree_id(blobs, executables, algorithm) != tree:
        raise SuiteError("release_tree_mismatch")
    return {"format": FORMAT, "tag": tag, "commit": commit, "tree": tree, "files": hashes,
            "executables": sorted(executables)}


def _manifest_bytes(manifest):
    return (json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _make_read_only(root, executables):
    """Files 0400 (0500 if executable), directories 0500, deepest first; root itself is left for the caller."""
    for directory, dirs, files in os.walk(root, topdown=False):
        relative = os.path.relpath(directory, root)
        for name in files:
            relpath = name if relative == "." else relative + "/" + name
            os.chmod(os.path.join(directory, name), EXEC_MODE if relpath in executables else FILE_MODE)
        for name in dirs:
            os.chmod(os.path.join(directory, name), DIR_MODE)


def _remove_tree(path):
    """Remove a partial or new copy: directories made writable again first; symlinks are never followed."""
    import shutil
    if not os.path.lexists(path) or os.path.islink(path):
        return
    for directory, dirs, _files in os.walk(path):
        for name in dirs:
            os.chmod(os.path.join(directory, name), 0o700)
    os.chmod(path, 0o700)
    shutil.rmtree(path)


def _make_app_dir(app):
    """app/ as a real 0700 directory owned by this user; its parent (the share dir) must exist."""
    try:
        parent = os.lstat(os.path.dirname(app))
    except OSError:
        parent = None
    if parent is None or not stat.S_ISDIR(parent.st_mode):
        raise SuiteError("root_parent_missing")
    try:
        os.mkdir(app, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(app)
    if stat.S_ISLNK(info.st_mode):
        raise SuiteError("symlink_refused")
    if not stat.S_ISDIR(info.st_mode):
        raise SuiteError("not_a_directory")
    if info.st_uid != os.getuid():
        raise SuiteError("wrong_owner")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(app, 0o700)


def _check_current(current):
    """app/current must be absent or a symlink (which the switch replaces); anything else is refused."""
    try:
        info = os.lstat(current)
    except FileNotFoundError:
        return
    if not stat.S_ISLNK(info.st_mode):
        raise SuiteError("release_current_invalid")


def _require_no_run_marker():
    from . import config, runmarker
    runmarker.require_absent(runmarker.marker_path(config.load()))


def _read_regular(path, limit):
    """Bytes of a regular file opened without following a final symlink, or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        return _read_all(fd, info.st_size)
    except OSError:
        return None
    finally:
        os.close(fd)


def _read_all(fd, size):
    chunks, seen = [], 0
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        seen += len(chunk)
        if seen > size:
            break
        chunks.append(chunk)
    data = b"".join(chunks)
    if len(data) != size or seen != size:
        raise OSError("size changed")
    return data


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name):
    raise ValueError("non-finite number")
