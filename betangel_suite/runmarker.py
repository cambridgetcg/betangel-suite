"""The run marker: no suite engine while Nuance runs a real backtest or the PRO ingest (DESIGN.md 6.8, I-17).

The marker is a file Nuance's run wrapper creates, outside ~/betangel-data, at ~/.local/state/lab-runs/ACTIVE
(agreed with Nuance, Q-N3). The config key run_marker accepts only that path, so no config edit can point
the check at a file that never exists. Lab-Claude never creates or removes the marker.

Fail closed: any directory entry at the marker path counts as present (a dangling symlink included), and
so does a marker that cannot be checked: an unreadable or unsearchable marker directory, a marker
"directory" that is not a directory, or any error other than "no such file". Only a definite absence of
the marker (or of its directory) lets a command start.

bin/_launch.py calls require_absent() before every command except stop, before anything is created; test
and vendor are checked too, test on both interpreters (Nuance's answers to Q-N14). Later phases call active()
on every actor tick and before every journal or ledger write.
Standard library only.
"""

import os
import stat

from . import config
from .errors import SuiteError

PRESENT = "present"
UNREADABLE = "unreadable"


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
