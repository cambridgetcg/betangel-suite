"""The run marker and the realdata lock: nothing touches real data while Nuance runs a real backtest or the PRO ingest
(DESIGN.md 6.8, I-17).

The marker is a file Nuance's run wrapper creates, outside ~/betangel-data, at ~/.local/state/lab-runs/ACTIVE
(agreed with Nuance, Q-N3). The config key run_marker accepts only that path, so no config edit can point
the check at a file that never exists. Lab-Claude never creates or removes the marker, and the suite never creates
or removes it, or the wrapper's own lock file beside it (lab-runs/LOCK).

Fail closed: any directory entry at the marker path counts as present (a dangling symlink included), and
so does a marker that cannot be checked: an unreadable or unsearchable marker directory, a marker
"directory" that is not a directory, or any error other than "no such file". Only a definite absence of
the marker (or of its directory) lets a command start.

bin/_launch.py calls require_absent() before every command except stop, before anything is created; test
and vendor are checked too, test on both interpreters (Nuance's answers to Q-N14). Later phases call active()
on every actor tick and before every journal or ledger write.

The realdata lock (Nuance's PR #2 review, item 6, and PR #1 review, item 5). A check at start alone leaves a race: a
command that passed it just before the marker appeared would go on writing under ~/betangel-data, and nothing would
make the wrapper wait for it. So:

  - the lock is run/realdata.lock in the state root (roots.realdata_lock_path), beside engine.lock and not
    engine.lock itself (a wrapper holding engine.lock makes `bin/suite stop` fail with control_failed: Nuance's
    probe). The suite creates it once, 0600, and never unlinks, renames or replaces it: a holder of the old file and
    a wrapper locking a new one would not exclude each other. The guard refuses those calls in every mode
    (run_lock_protected, guard.py I-6);
  - every command that may read a real data root or write under ~/betangel-data (cli.REALDATA_COMMANDS) calls
    hold_shared() before it creates its TMPDIR: LOCK_SH, without waiting, then the marker checked again under the
    lock, then the lock held until the process exits. The descriptor is close-on-exec, so no child keeps it;
  - headless commands (catalogue, selfcheck --sample N, diagnose) call require_clear() between members, and stop at
    the first marker; engines call active() on every tick and exit within their grace period;
  - Nuance's wrapper creates the marker first, then takes LOCK_EX, waiting 60 s or more and failing closed. A missing
    lock file can count as free, as for engine.lock (DESIGN.md 6.8): every holder creates it before it locks.

Why the re-check comes after the lock: macOS flock gives a waiting LOCK_EX no priority over a new LOCK_SH (probed on
the lab), so without it a command starting during the wrapper's wait could take the lock after the marker exists and
hold the wrapper off. With it, a command that locks after the marker appeared refuses at once and lets go; one that
locked before is waited for, and stops at its next check. LOCK_SH never waits: a lock the wrapper holds refuses at
once (run_lock_busy), since a run is ending or under way.

test, uisnap and vendor do not take the lock: none of them reads a data root or writes under ~/betangel-data (the
guard refuses it in their modes), each refuses under the marker at start, and holding the lock would let a long test
run make Nuance's wrapper fail closed. A test run stops before its next test once the marker appears
(cli.marker_stop_result). stop takes nothing: it must work during a run, and only reduces activity.
Standard library only.
"""

import fcntl
import os
import stat

from . import config, roots
from .errors import SuiteError

PRESENT = "present"
UNREADABLE = "unreadable"
# O_CREAT without O_EXCL: the file is made once and then reused for ever. O_NOFOLLOW: no link in its place. O_NONBLOCK:
# a FIFO in its place is opened at once (and then refused), never waited on. Read-only: flock needs no write access,
# and nothing is ever written to the file.
_LOCK_FLAGS = os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC

_HELD = None    # (lock path, descriptor, marker path) once hold_shared() succeeded; kept until the process exits


def marker_path(cfg=None, home_dir=None):
    """The absolute marker path from the config (DEFAULTS when cfg is None)."""
    value = (config.DEFAULTS if cfg is None else cfg)["run_marker"]
    return config.expand(value, home_dir)


def state(path):
    """None when the marker is definitely absent, else PRESENT or UNREADABLE."""
    directory = os.path.dirname(path)
    try:
        info = os.stat(directory)
    except FileNotFoundError:
        return None                                    # no marker directory: no run announced
    except OSError:
        return UNREADABLE
    if not stat.S_ISDIR(info.st_mode) or not os.access(directory, os.R_OK | os.X_OK):
        return UNREADABLE
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        return UNREADABLE
    return PRESENT


def active(path):
    """True while a run may be in progress (present or uncheckable); the per-tick check."""
    return state(path) is not None


def require_absent(path):
    """The start-time check: SuiteError(run_marker_present or run_marker_unreadable) unless absent."""
    found = state(path)
    if found == PRESENT:
        raise SuiteError("run_marker_present")
    if found == UNREADABLE:
        raise SuiteError("run_marker_unreadable")


# --- the realdata lock ---------------------------------------------------------------------------

def lock_path(home_dir=None):
    """run/realdata.lock in the state root (roots.realdata_lock_path)."""
    return roots.realdata_lock_path(home_dir)


def hold_shared(marker, lock):
    """Take LOCK_SH on the realdata lock at lock for the rest of this process's life, then check the marker again.

    Called once per process, before anything is created under ~/betangel-data (cli.main, before TMPDIR). Creates
    run/ (through the writer helper) and the lock file (0600) if they are missing. SuiteError, with the lock let go
    again, when:
      - run_lock_busy: the lock is not granted at once (Nuance's wrapper holds LOCK_EX);
      - run_lock_invalid: the file cannot be opened or locked; it is not a regular file owned by this user with one
        link and no group or other write bit; or it is no longer the file at lock once locked (replaced meanwhile);
        or this process already holds a lock;
      - run_marker_present or run_marker_unreadable: the marker exists, or cannot be checked, once the lock is held.
    """
    global _HELD
    if _HELD is not None:
        raise SuiteError("run_lock_invalid")
    roots.ensure_dir(os.path.dirname(lock))
    fd = _open_lock(lock)
    try:
        code = _lock_shared(fd)
        if code is None and not _same_file(fd, lock):
            code = "run_lock_invalid"
        if code is None:
            require_absent(marker)                     # again, now under the lock: the wrapper makes the marker first
    except BaseException:
        os.close(fd)
        raise
    if code is not None:
        os.close(fd)
        raise SuiteError(code)
    _HELD = (lock, fd, marker)


def holding():
    """True once hold_shared() has succeeded in this process (the lock is then held until it exits)."""
    return _HELD is not None


def require_clear():
    """Between the members of a headless command, and wherever a long-lived holder looks again: SuiteError unless this
    process holds the realdata lock (run_lock_not_held), on the file still at its path (run_lock_invalid), and the
    marker is absent (run_marker_present or run_marker_unreadable). The caller then stops without further writes."""
    held = _HELD
    if held is None:
        raise SuiteError("run_lock_not_held")
    lock, fd, marker = held
    if not _same_file(fd, lock):
        raise SuiteError("run_lock_invalid")
    require_absent(marker)


def _open_lock(lock):
    try:
        fd = os.open(lock, _LOCK_FLAGS, 0o600)
    except OSError:
        fd = None
    if fd is None:
        raise SuiteError("run_lock_invalid")
    try:
        info = os.fstat(fd)
        ok = (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
              and not info.st_mode & 0o022)
    except OSError:
        ok = False
    if not ok:
        os.close(fd)
        raise SuiteError("run_lock_invalid")
    return fd


def _lock_shared(fd):
    """None once LOCK_SH is held on fd, else the refusal code. Never waits."""
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return "run_lock_busy"
    except OSError:
        return "run_lock_invalid"
    return None


def _same_file(fd, lock):
    """True when the file at lock (not following a link) is the one open on fd."""
    try:
        here, held = os.lstat(lock), os.fstat(fd)
    except OSError:
        return False
    return (here.st_dev, here.st_ino) == (held.st_dev, held.st_ino)
