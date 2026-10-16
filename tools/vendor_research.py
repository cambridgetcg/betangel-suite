"""Make the pinned, read-only, network-free deps clone of betangel-research (DESIGN.md 3.5).

    bin/suite vendor <full-sha> [--bump] [--pin-file PATH]

Run by hand by lab-Claude, never automatically. Steps:

  1. git -C ~/betangel-research cat-file -e <sha>^{commit}: a read-only object lookup in the deploy
     clone. If the commit is not there yet, stop (commit_not_present): wait for the Air's fast-forward.
     Nothing here ever fetches. Then git -C ~/betangel-research merge-base --is-ancestor <sha>
     refs/heads/main, read only too: only a commit on the research main branch can be pinned
     (commit_not_on_main; Nuance's Q-N2 answer in her PR #2 review), since cat-file -e also finds an
     unmerged or a dangling commit.
  2. git clone --no-checkout --no-hardlinks into
     ~/.local/share/betangel-suite/deps/betangel-research-<sha12>.partial: a local clone, no network.
  3. git checkout --detach <sha>, then git remote remove origin, so no later command can fetch from
     the moving clone.
  4. sha256 of every pinned file (betangel_suite.pin.PINNED_FILES): written to pin/betangel-research.json
     with --bump (a pin bump, reviewed as a PR), otherwise checked against it (a fresh machine).
  5. Rename the directory into place and chmod -R a-w it, after a pre-pass over the whole tree (also run
     before step 4): a real directory outside the deploy clone, holding only directories, symlinks and
     regular files with one link (deps_link_present), so no chmod can reach a clone file through a link.

Every git call has protocol.allow=never (only the local file transport is allowed), no hooks, no user
or system git config and no per-user attributes file, ignores replace refs and grafts (so merge-base judges
the commits the clone really holds), and runs with the network switch on, in exactly the environment
guard.VENDOR_GIT_ENV plus HOME. The guard, armed in vendor mode, allows exactly these git argvs with that environment (and none
after them) and writes only under ~/.local/share/betangel-suite, this checkout's pin/ and the state root.
Nothing is ever written into ~/betangel-research: before any git call or mkdir, and again just before the
clone, vendor refuses (research_clone_on_path) a deps root, pin directory or checkout that lies in the clone
by name or by identity (roots.lies_in), and the guard refuses a partial clone path that does. A failure
after the clone leaves the .partial directory for inspection; remove it by hand before running again
(partial_exists).
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

    # Before any git call or mkdir: nothing this tool writes may land in the deploy clone (Nuance's PR #2 review,
    # item 2). git writes from a child the guard cannot see, and a link on an ancestor (~/.local/share linked
    # into the clone, say) passes every text check, so each target is judged by identity, at its nearest
    # existing ancestor when it does not exist yet. guard.REPO_ROOT holds pin/, the default pin directory.
    _refuse_research((deps_root, os.path.dirname(pin_file), guard.REPO_ROOT), research, SuiteError)
    if _git(home, "-C", research, "cat-file", "-e", sha + "^{commit}") != 0:
        raise SuiteError("commit_not_present")
    on_main = _git(home, "-C", research, "merge-base", "--is-ancestor", sha, guard.VENDOR_MAIN_REF)
    if on_main == 1:                                  # git's answer "not an ancestor"; anything else is a failure
        raise SuiteError("commit_not_on_main")
    if on_main != 0:
        raise SuiteError("git_failed")
    if os.path.lexists(partial):
        raise SuiteError("partial_exists")
    if os.path.lexists(dest):
        tree = dest                                   # already vendored: check it again, clone nothing
    else:
        _make_private_dirs(deps_root, roots.share_dir(home))
        _refuse_research((deps_root,), research, SuiteError)    # again, now it exists: just before the clone
        tree = partial
        if (_git(home, "clone", "--no-checkout", "--no-hardlinks", "--quiet", research, partial) != 0
                or _git(home, "-C", partial, "checkout", "--quiet", "--detach", sha) != 0
                or _git(home, "-C", partial, "remote", "remove", "origin") != 0):
            raise SuiteError("git_failed")
    guard.seal()                                      # no subprocess from here on
    _check_tree(tree, research, SuiteError)           # before the pin is hashed or written, and before any chmod
    head = pin.read_below(tree, ".git/HEAD", 1 << 16)
    config = pin.read_below(tree, ".git/config", 1 << 16)
    if head != (sha + "\n").encode() or config is None or b"[remote" in config:
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
    _make_read_only(dest, research, SuiteError)
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


def _refuse_research(paths, research, error):
    """error(research_clone_on_path) if any of paths lies in the deploy clone (roots.lies_in: stat calls only)."""
    from betangel_suite import roots
    for path in paths:
        if roots.lies_in(path, research, "research_clone_on_path"):
            raise error("research_clone_on_path")


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


def _check_tree(tree, research, error):
    """Every directory and regular file under tree, deepest first, then tree itself; error() unless all is in order.

    The pre-pass before any chmod (Nuance's PR #2 review, item 8: a re-check of an existing deps tree chmodded
    deploy-clone files to 0444). tree must be a real directory (not a link: os.walk would follow it) that is not in
    the deploy clone (research_clone_on_path), and every entry under it a directory, a symlink (left alone), or a
    regular file with exactly one link: a hard link shares its inode, and so its mode, with a file elsewhere, in the
    clone say (deps_link_present, which also covers a FIFO, socket or device). A directory that cannot be listed
    raises OSError rather than being skipped.
    """
    info = os.lstat(tree)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise error("not_a_directory")
    _refuse_research((tree,), research, error)
    found = []
    for directory, dirs, files in os.walk(tree, topdown=False, onerror=_raise):
        for name in files + dirs:
            path = os.path.join(directory, name)
            mode = os.lstat(path)
            if stat.S_ISLNK(mode.st_mode):
                continue
            if not (stat.S_ISDIR(mode.st_mode) or (stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1)):
                raise error("deps_link_present")
            found.append(path)
    return found + [tree]


def _raise(exc):
    raise exc


def _make_read_only(tree, research, error):
    """chmod a-w every directory and regular file under tree, deepest first; symlinks are left alone. The pre-pass
    (_check_tree) runs first, so nothing is changed unless every entry passes it, and each entry is looked at again
    just before its chmod, which never follows a link."""
    for path in _check_tree(tree, research, error):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise error("deps_link_present")
        os.chmod(path, stat.S_IMODE(info.st_mode) & ~0o222, follow_symlinks=False)


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
