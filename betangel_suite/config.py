"""Suite configuration: the defaults table of DESIGN.md 3.8 and strict loading of config.json.

The file is ~/.local/state/betangel-suite/config.json. It is optional; every key it holds must be one of
DEFAULTS and must pass its check, or loading refuses with a code (never echoing the key or the value).
The file must be a regular file owned by this user, not a symlink, not writable by group or others, at
most 64 KB of strict JSON (duplicate keys and NaN or Infinity refused). It is opened with O_NONBLOCK and
checked with fstat before anything is read, so a FIFO in its place is refused at once instead of waiting
for a writer (Nuance's PR #2 review, item 22).

Phase 0: no command reads a data root, and the repo's own config.validate_config is not called yet; the
paper config and cap profiles arrive with Phase 1b. Nothing here can weaken the guard: no key names the
network switch, the audit hook or the write roots, state_root accepts only the value of R-4,
run_marker accepts only the marker path of Q-N3 (DESIGN.md 3.8 gives its status; a configurable marker
would let a config edit point the I-17 start check somewhere that never exists), and research_months_ruling accepts
only null or an id in ACCEPTED_RULINGS, which is empty. Only a reviewed change moves any of them;
configuration alone never does.
Standard library only.
"""

import copy
import json
import os
import stat

from . import roots
from .errors import SuiteError

DEFAULTS = {
    "data_roots": [],                                   # until the PRO index exists (Nuance named historic-pro, Q-N4)
    "state_root": "~/betangel-data/suite.noindex",      # R-4, Q-N3; written only while roots.STATE_ROOT_AGREED
    "port": 8765,                                       # loopback only
    "frame_hz": 10,                                     # 5-20
    "cap_profile": "v1-live-mirror",                    # R-7: practise live v1 by default
    "commission_source": "user_package_unverified",     # R-3
    "research_months_ruling": None,                     # research months hidden while null
    "run_marker": "~/.local/state/lab-runs/ACTIVE",     # section 6.8; Q-N3
    "watch_grace_s": 600,                               # section 8.6
    "max_session_s": 14400,                             # section 8.6: a maximum session time of 4 h (Phase 0c)
}
CAP_PROFILES = ("v1-live-mirror", "practice")
COMMISSION_SOURCES = ("user_package_verified", "user_package_unverified", "official_example_basic_2pct")
MAX_CONFIG_BYTES = 64 << 10
MAX_DATA_ROOTS = 8
# The ruling ids research_months_ruling may name (DESIGN.md 5.3 and 14; Nuance's PR #2 review, item 12). Empty: the
# key stays null until Yu rules on Q-Y7, so no config edit alone can put research-month rows in the catalogue. Each
# id is added only by a reviewed PR, after Yu's ruling with Nuance and Astra.
ACCEPTED_RULINGS = frozenset()
# O_NONBLOCK: opening a FIFO never waits for a writer (a regular file's open and read are unchanged); fstat then
# refuses it before any read. O_NOCTTY: a terminal device in the file's place never becomes this process's terminal.
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC


def load(home_dir=None):
    """DEFAULTS overlaid with config.json, if it exists; SuiteError(config_*) for anything not strict."""
    config = copy.deepcopy(DEFAULTS)
    path = roots.config_path(home_dir)
    try:
        fd = os.open(path, _READ_FLAGS)
    except FileNotFoundError:
        return config
    except OSError:
        fd = None
    if fd is None:
        raise SuiteError("config_unreadable")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise SuiteError("config_insecure")
        if info.st_size > MAX_CONFIG_BYTES:
            raise SuiteError("config_too_large")
        data = os.read(fd, MAX_CONFIG_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_CONFIG_BYTES:
        raise SuiteError("config_too_large")
    try:
        loaded = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        loaded = _NOT_JSON
    if loaded is _NOT_JSON:
        raise SuiteError("config_not_json")
    if not isinstance(loaded, dict):
        raise SuiteError("config_not_object")
    if not set(loaded) <= set(DEFAULTS):
        raise SuiteError("config_unknown_key")
    for key, value in loaded.items():
        if not _CHECKS[key](value, home_dir):
            raise SuiteError("config_invalid_value")
        config[key] = value
    return config


def expand(path, home_dir=None):
    """An absolute, normalised path from "~/..." or "/..." text (the config's path form)."""
    if path.startswith("~/"):
        path = os.path.join(roots.home() if home_dir is None else home_dir, path[2:])
    return os.path.normpath(path)


def _is_int(value, low, high):
    return type(value) is int and low <= value <= high


def _path_text(value):
    """ "~/<path>" or "/<path>" naming something below the home or the file-system root."""
    if not (isinstance(value, str) and 0 < len(value) <= 1024 and "\0" not in value):
        return False
    rest = value[2:] if value.startswith("~/") else value[1:] if value.startswith("/") else ""
    return os.path.basename(os.path.normpath("/" + rest)) not in ("", ".", "..")


def _data_roots_ok(value):
    return (isinstance(value, list) and len(value) <= MAX_DATA_ROOTS and all(_path_text(item) for item in value)
            and len(set(value)) == len(value))


# key -> check(value, home_dir); every DEFAULTS key has one.
_CHECKS = {
    "data_roots": lambda value, home_dir: _data_roots_ok(value),
    "state_root": lambda value, home_dir: value == DEFAULTS["state_root"],
    "port": lambda value, home_dir: _is_int(value, 1024, 65535),
    "frame_hz": lambda value, home_dir: _is_int(value, 5, 20),
    "cap_profile": lambda value, home_dir: value in CAP_PROFILES,
    "commission_source": lambda value, home_dir: value in COMMISSION_SOURCES,
    "research_months_ruling": lambda value, home_dir: value is None or (
        isinstance(value, str) and value in ACCEPTED_RULINGS),
    "run_marker": lambda value, home_dir: value == DEFAULTS["run_marker"],
    "watch_grace_s": lambda value, home_dir: _is_int(value, 60, 3600),
    "max_session_s": lambda value, home_dir: _is_int(value, 600, 86400),
}
_NOT_JSON = object()


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name):
    raise ValueError("non-finite number")
