"""The static UI, mapped from ui/manifest.json by exact name (DESIGN.md 9.1).

The manifest is {"files": [{"path": "index.html", "type": "text/html; charset=utf-8"}, ...]}. Each path is
a plain relative name inside ui/ (letters, digits, '.', '_', '-' and '/' between segments that do not start
with a dot); each type comes from TYPES. No path may lie under api/ (in any case), so the UI manifest can
never shadow a route of the closed table (server.py serves a static match before the token check). GET /
serves index.html, and GET /<path> serves exactly the listed paths (the manifest itself only if it lists
itself). Nothing is ever joined from a request path, and there is no directory listing.

Every file is read once, when the server starts: a regular file opened without following a final symlink,
whose real path lies inside ui/, at most MAX_FILE_BYTES. A manifest that is present but malformed refuses
the start (manifest_invalid). A missing manifest gives an empty table (the API still works; GET / is 404).
Standard library only.
"""

import json
import os
import re
import stat

from ..errors import SuiteError
from . import routes

MANIFEST = "manifest.json"
API_SEGMENT = "api"             # no static path lies under api/ (any case): those are the closed routes' only
MAX_MANIFEST_BYTES = 64 << 10
MAX_FILE_BYTES = 4 << 20
MAX_FILES = 128
TYPES = frozenset({
    "text/html; charset=utf-8", "text/javascript; charset=utf-8", "text/css; charset=utf-8", "application/json",
    "application/json; charset=utf-8", "image/png", "image/svg+xml", "image/x-icon", "audio/wav", "audio/mpeg",
    "font/woff2",
})
_PATH_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}(?:/[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}){0,3}")


def ui_dir(repo_root):
    return os.path.join(repo_root, "ui")


def load(directory):
    """{request path: (body bytes, content type)} for the UI in directory; {} when it has no manifest."""
    manifest_path = os.path.join(directory, MANIFEST)
    if not os.path.lexists(manifest_path):
        return {}
    data = _read(manifest_path, directory, MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        manifest = None
    if not isinstance(manifest, dict) or set(manifest) != {"files"} or not isinstance(manifest["files"], list):
        raise SuiteError("manifest_invalid")
    if not 0 < len(manifest["files"]) <= MAX_FILES:
        raise SuiteError("manifest_invalid")
    table = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "type"}:
            raise SuiteError("manifest_invalid")
        path, kind = entry["path"], entry["type"]
        if not isinstance(path, str) or not _PATH_RE.fullmatch(path):
            raise SuiteError("manifest_invalid")
        if path.split("/", 1)[0].lower() == API_SEGMENT or any("/" + path == route for _m, route in routes.ROUTES):
            raise SuiteError("manifest_invalid")     # the manifest never shadows or joins the closed API routes
        if kind not in TYPES or "/" + path in table:
            raise SuiteError("manifest_invalid")
        table["/" + path] = (_read(os.path.join(directory, *path.split("/")), directory, MAX_FILE_BYTES), kind)
    if "/index.html" not in table:
        raise SuiteError("manifest_invalid")
    table["/"] = table["/index.html"]
    return table


def _read(path, directory, limit):
    """Bytes of a regular file inside directory (no final symlink, real path inside), at most limit bytes."""
    real_dir = os.path.realpath(directory)
    if not os.path.realpath(path).startswith(real_dir + os.sep):
        raise SuiteError("manifest_invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        fd = None
    if fd is None:
        raise SuiteError("manifest_invalid")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise SuiteError("manifest_invalid")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise SuiteError("manifest_invalid")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name):
    raise ValueError("non-finite number")
