"""Make the pinned, read-only, network-free deps clone of betangel-research (DESIGN.md 3.5).

    bin/suite vendor <full-sha> [--bump] [--pin-file PATH]

Run by hand by lab-Claude, never automatically. Steps:

  1. git -C ~/betangel-research cat-file -e <sha>^{commit}: a read-only object lookup in the deploy
     clone. If the commit is not there yet, stop (commit_not_present): wait for the Air's fast-forward.
     Nothing here ever fetches.
  2. git clone --no-checkout --no-hardlinks into
     ~/.local/share/betangel-suite/deps/betangel-research-<sha12>.partial: a local clone, no network.
  3. git checkout --detach <sha>, then git remote remove origin, so no later command can fetch from
     the moving clone.
  4. sha256 of every pinned file (betangel_suite.pin.PINNED_FILES): written to pin/betangel-research.json
     with --bump (a pin bump, reviewed as a PR), otherwise checked against it (a fresh machine).
  5. Rename the directory into place and chmod -R a-w it.

Every git call has protocol.allow=never (only the local file transport is allowed), no hooks and no user
or system git config, and runs with the network switch on, in exactly the environment guard.VENDOR_GIT_ENV
plus HOME. The guard, armed in vendor mode, allows exactly these git argvs with that environment (and none
after them) and writes only under ~/.local/share/betangel-suite, this checkout's pin/ and the state root.
Nothing is ever written into ~/betangel-research. A failure after the clone leaves the .partial
directory for inspection; remove it by hand before running again (partial_exists).
Output is codes and counts only. Standard library only; never imports betangel_research.
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys

_SHA_RE = re.compile(r"[0-9a-f]{40}")


def main(argv):
    from betangel_suite import guard, pin, roots
    from betangel_suite.errors import SuiteError

    guard.require_mode("vendor")
    sha, bump, pin_file = _parse(list(argv), pin.PIN_FILE, SuiteError)
    home = roots.home()
    research = roots.research_clone(home)
    deps_root = roots.deps_root(home)
    dest = os.path.join(deps_root, "betangel-research-" + sha[:12])
    partial = dest + ".partial"

    if _git(home, "-C", research, "cat-file", "-e", sha + "^{commit}") != 0:
        raise SuiteError("commit_not_present")
    if os.path.lexists(partial):
        raise SuiteError("partial_exists")
    if os.path.lexists(dest):
        tree = dest                                   # already vendored: check it again, clone nothing
    else:
        _make_private_dirs(deps_root, roots.share_dir(home))
        tree = partial
        if (_git(home, "clone", "--no-checkout", "--no-hardlinks", "--quiet", research, partial) != 0
                or _git(home, "-C", partial, "checkout", "--quiet", "--detach", sha) != 0
                or _git(home, "-C", partial, "remote", "remove", "origin") != 0):
            raise SuiteError("git_failed")
    guard.seal()                                      # no subprocess from here on
    if _read(os.path.join(tree, ".git", "HEAD")) != (sha + "\n").encode() or b"[remote" in _read(
            os.path.join(tree, ".git", "config")):
        raise SuiteError("git_failed")
    hashes = pin.file_hashes(tree)
    if bump:
        _write_pin(pin_file, {"schema_version": 1, "repo": pin.REPO, "commit": sha,
                              "python_floor": pin.PYTHON_FLOOR, "files": hashes})
    else:
        expected = pin.load(pin_file)
        if expected["commit"] != sha or expected["files"] != hashes:
            raise SuiteError("pin_mismatch")
    if tree == partial:
        os.rename(partial, dest)
    _make_read_only(dest)
    print("vendor_ok commit=%s files=%d mode=%s" % (sha[:12], len(hashes), "bump" if bump else "check"))
    return 0


def _parse(args, default_pin, error):
    if not args or not _SHA_RE.fullmatch(args[0]):
        raise error("bad_arguments")
    sha, bump, pin_file = args.pop(0), False, default_pin
    while args:
        item = args.pop(0)
        if item == "--bump" and not bump:
            bump = True
        elif item == "--pin-file" and pin_file == default_pin and args and os.path.isabs(args[0]):
            pin_file = os.path.normpath(args.pop(0))
        else:
            raise error("bad_arguments")
    return sha, bump, pin_file


def _git(home, *args):
    """Run one allowed git argv; return its exit status. Its output is discarded, never printed.

    The environment is guard.VENDOR_GIT_ENV plus HOME, nothing else: the guard refuses any other (Nuance's PR #2
    review, item 10).
    """
    from betangel_suite import guard
    env = dict(guard.VENDOR_GIT_ENV, HOME=home)
    result = subprocess.run(list(guard.VENDOR_GIT_PREFIX) + list(args), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    return result.returncode


def _make_private_dirs(deps_root, share):
    """~/.local/share/betangel-suite and its deps/ as 0700 directories (the parent must exist)."""
    for directory in (share, deps_root):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        info = os.lstat(directory)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            from betangel_suite.errors import SuiteError
            raise SuiteError("not_a_directory")


def _read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(1 << 16)
    except OSError:
        return b""


def _write_pin(path, value):
    """Write the pin JSON next to its final name, then rename it into place."""
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _make_read_only(tree):
    """chmod a-w every directory and regular file under tree, deepest first; symlinks are left alone."""
    for directory, dirs, files in os.walk(tree, topdown=False):
        for name in files + dirs:
            path = os.path.join(directory, name)
            info = os.lstat(path)
            if not stat.S_ISLNK(info.st_mode):
                os.chmod(path, stat.S_IMODE(info.st_mode) & ~0o222)
    os.chmod(tree, stat.S_IMODE(os.lstat(tree).st_mode) & ~0o222)


if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from betangel_suite import errors, guard
    try:
        guard.arm("vendor")
        errors.install_excepthooks()
        os.umask(0o077)
        sys.exit(main(sys.argv[1:]))
    except errors.SuiteError as exc:
        sys.stderr.write(errors.describe(exc) + "\n")
        sys.exit(2)
