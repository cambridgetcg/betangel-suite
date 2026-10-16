"""Hygiene scanner for betangel-suite (docs/DESIGN.md I-9, sections 5.6 and 9.4).

It keeps licensed Betfair data, real identifiers and secrets out of git. On
any finding it exits 1 and prints only a rule code, a redacted path, a line
number and an entry number. It never prints the text that matched. When the
file may hold data (a data-file, runner, identifier or data-path finding)
the whole path is withheld, and the entry number, the file's position in the
scan, identifies it. A withheld path shows its suffix only when the suffix is
on a fixed list (SHOWN_SUFFIXES), never a word that may come from the name.

Run it with the fixed interpreter, standard library only:

    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py --staged
    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py
    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py PATH [PATH ...]

  --staged         scan every entry of the git index (what a commit would hold);
                   tools/pre-commit runs this
  (no PATH)        scan the working tree: tracked plus untracked, not ignored
  PATH ...         scan these files or directories, relative to --root
  --root DIR       repository root (default: the git toplevel of the cwd, else the cwd)
  --list-rules     print the rule codes and exit

Exit status: 0 clean, 1 findings, 2 refused or internal error.

Reserved synthetic namespace (DESIGN.md 5.6). Fixtures use market ids
1.999 plus six digits, event ids 99 plus six digits, selection ids 9 plus
seven digits, the venue "Synthetic Park" and runners "Synthetic 1..n". The id
rules never match that namespace, and runner names starting "Synthetic" are
exempt from the runner rules.

Safety. The scanner refuses (exit 2) to run with a root inside betangel-data
or a *.noindex directory. It never follows a symbolic link, never reads a
path with a data-root component, and reads working-tree files with O_NOFOLLOW.
Protected names match in any case: data-root components, forbidden
directories, forbidden file names and suffixes, betangel-research copies,
and betangel-data in a link target or text are compared with
str.casefold(), because the lab's APFS volume folds case and matches
U+017F (long s) to "s". The docs/synthetic/ and size allowlists stay
exact, and the media allowlist is not casefolded, so a variant fails closed.

Allowlists live in this file only and change through a reviewed PR (Astra
reviews the scanner, DESIGN.md 3.9). There is no inline suppression comment.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys

EXIT_CLEAN, EXIT_FINDINGS, EXIT_REFUSED = 0, 1, 2

# Size limit. DESIGN.md 5.6 says no file over 512 KB. The largest legitimate
# text file is DESIGN.md (about 185 KB at draft 0.2), and one real PRO member
# decompresses to about 8 MB at the median, so licensed dumps land far above
# the limit. DESIGN.md alone may grow to 2 MiB; it is still content-scanned.
MAX_FILE_BYTES = 512 * 1024
SIZE_ALLOWLIST = {"docs/DESIGN.md": 2 * 1024 * 1024}
SNIFF_BYTES = 8192
MAX_REPORTED_LINES = 10  # per file and rule; the rest are counted
MAX_TABLE_LINE = 400  # longer lines are never table rows

RULES = {
    "archive_member": "archive or compressed file (.bz2 .tar .gz .zip .xz ..., or by magic bytes)",
    "sqlite_file": "SQLite database or sidecar (.sqlite* .db, or by magic bytes)",
    "jsonl_file": "JSON-lines file (.jsonl .ndjson)",
    "data_file": "tabular or serialised data file (.csv .tsv .xlsx .parquet .pkl ...)",
    "key_file": "key, certificate or secrets file (.pem .key .p12 .crt .env .netrc id_*)",
    "image_outside_synthetic": "image or video outside docs/synthetic/",
    "binary_file": "binary file that is not an allowed media type",
    "oversize": "file over 512 KiB (allowlist: SIZE_ALLOWLIST)",
    "forbidden_dir": "path under exports/ run/ screenshots/ private/ ledger/ sessions/ catalogue/ reports/ logs/ tmp/",
    "data_path": "path or symlink into betangel-data, a *.noindex root or a data-root directory",
    "upstream_copy": "a copy of betangel-research inside the repo",
    "symlink": "symbolic link",
    "submodule": "submodule, gitlink or nested repository",
    "special_file": "FIFO, socket or device",
    "market_id": "Betfair market-id shape (1.1 or 1.2 then 8-9 digits); reserved 1.999 never matches",
    "event_id": "8-digit event or selection id shape outside the reserved 9xxxxxxx namespace",
    "member_path": "historical-data member path with a non-reserved event id",
    "runner_table": "three or more rows of a capitalised name (after up to two number cells) and price columns",
    "runner_record": "runner-name field holding a non-synthetic name",
    "stream_record": "exchange-stream runner change (ladder, traded or ltp values) with a non-reserved runner id",
    "data_path_text": "text naming a member or archive path under betangel-data",
    "private_key": "private-key header (PEM, OpenSSH, PGP, PuTTY)",
    "pem_block": "other PEM block (certificate, request, ...)",
    "bearer_token": "Bearer credential",
    "secret_value": "secret-looking value assigned to a key, token, password or session field",
    "known_token": "token with a known provider prefix (GitHub, AWS, Slack, JWT, ...)",
    "bootstrap_code": "suite bootstrap-code URL fragment",
}

# File-level codes whose path may itself carry data, and content codes that
# mark runner data (a runner name in a path is not redacted): the whole path
# is withheld, since any directory may be named after a runner or a market.
# An identifier or data-path finding, in the content or on the path itself,
# withholds it too. The entry number still identifies the file.
_WITHHOLD_NAME = frozenset({
    "archive_member", "sqlite_file", "jsonl_file", "data_file", "key_file",
    "image_outside_synthetic", "binary_file", "oversize", "forbidden_dir",
    "data_path", "upstream_copy", "runner_table", "runner_record", "stream_record",
})
_PATH_ID_CODES = ("market_id", "event_id", "member_path")
_WITHHOLD_CONTENT = frozenset(_PATH_ID_CODES) | {"data_path_text"}

# ---------------------------------------------------------------- path rules

ARCHIVE_EXT = frozenset({
    ".bz2", ".gz", ".tgz", ".tar", ".tbz", ".tbz2", ".txz", ".xz", ".zst",
    ".zip", ".7z", ".lz4", ".lzma", ".rar",
})
SQLITE_EXT = frozenset({".db", ".db3", ".sqlite3"})
SQLITE_SIDECARS = ("-journal", "-wal", "-shm")
JSONL_EXT = frozenset({".jsonl", ".ndjson"})
DATA_EXT = frozenset({
    ".csv", ".tsv", ".xlsx", ".xls", ".numbers", ".parquet", ".feather",
    ".arrow", ".pkl", ".pickle", ".npy", ".npz",
})
KEY_EXT = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der", ".p8", ".jks",
    ".keychain", ".keychain-db",
})
KEY_NAME_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed2")
IMAGE_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".heic", ".heif", ".tif", ".tiff",
    ".webp", ".bmp", ".mov", ".mp4", ".m4v",
})
AUDIO_EXT = frozenset({".wav", ".mp3", ".m4a", ".aif", ".aiff", ".caf", ".ogg"})
SYNTHETIC_DIR = "docs/synthetic/"
SOUNDS_DIR = "ui/sounds/"
FORBIDDEN_DIRS = frozenset({
    "exports", "run", "screenshots", "private", "ledger", "sessions",
    "catalogue", "reports", "logs", "tmp",
})
DATA_COMPONENTS = frozenset({
    "betangel-data", "incoming", "historic", "historic-pro", "lab-state", "lab-runs",
})


def _is_data_component(part: str) -> bool:
    part = part.casefold()
    return part in DATA_COMPONENTS or part.endswith(".noindex")


def _has_data_component(path: str) -> bool:
    return any(_is_data_component(p) for p in path.replace("\\", "/").split("/"))


def _path_codes(rel: str) -> list:
    codes = []
    parts = rel.rstrip("/").split("/")
    dirs, name = parts[:-1], parts[-1]
    low = name.casefold()  # APFS folds U+017F too: x.c\u017fv opens as x.csv
    ext = os.path.splitext(low)[1]
    synthetic = rel.startswith(SYNTHETIC_DIR)
    if any(_is_data_component(p) for p in parts):
        codes.append("data_path")
    if any(d.casefold().startswith("betangel-research") for d in dirs):
        codes.append("upstream_copy")
    if any(d.casefold() in FORBIDDEN_DIRS and not (synthetic and d == "screenshots") for d in dirs):
        codes.append("forbidden_dir")
    if ext in ARCHIVE_EXT:
        codes.append("archive_member")
    if ".sqlite" in low or ext in SQLITE_EXT or low.endswith(SQLITE_SIDECARS):
        codes.append("sqlite_file")
    if ext in JSONL_EXT:
        codes.append("jsonl_file")
    if ext in DATA_EXT:
        codes.append("data_file")
    if (ext in KEY_EXT or low == ".env" or low.startswith(".env.") or low == ".netrc"
            or low.startswith(KEY_NAME_PREFIXES)):
        codes.append("key_file")
    if ext in IMAGE_EXT and not synthetic:
        codes.append("image_outside_synthetic")
    return codes


def _binary_allowed(rel: str) -> bool:
    ext = os.path.splitext(rel.lower())[1]
    if rel.startswith(SYNTHETIC_DIR) and ext in IMAGE_EXT:
        return True
    return rel.startswith(SOUNDS_DIR) and ext in AUDIO_EXT


def _magic_code(head: bytes):
    if head[:3] == b"BZh" and head[4:10] in (b"1AY&SY", b"\x17rE8P\x90"):
        return "archive_member"
    if (head[:2] == b"\x1f\x8b"
            or head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
            or head[:6] in (b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07")
            or head[:4] in (b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18")
            or head[257:262] == b"ustar"):
        return "archive_member"
    if head[:16] == b"SQLite format 3\x00":
        return "sqlite_file"
    return None

# ---------------------------------------------------------------- text rules

_MARKET_ID = re.compile(r"(?<![0-9.])1\.[12][0-9]{8,9}(?![0-9])")
_EVENT_ID = re.compile(r"(?<![0-9A-Za-z.])([1-8][0-9]{7})(?![0-9A-Za-z])(?!-[0-9A-Fa-f]{4}-)")
_MEMBER_PATH = re.compile(
    r"\b(?:PRO|BASIC|ADVANCED)/(?:19|20)[0-9]{2}/[A-Z][a-z]{2}/[0-9]{1,2}/(?!9)[0-9]{5,}")
_DATA_PATH_TEXT = re.compile(
    r"(?i:betangel-data)/[^\s\"'`<>()\[\]{}]{0,300}?"
    r"(?:/(?:PRO|BASIC|ADVANCED)/(?:19|20)[0-9]{2}/|/[0-9a-f]{64}(?![0-9a-f]))")
_DASH5 = "-{5}"
_PRIVATE_KEY = re.compile(
    _DASH5 + r"BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?" + _DASH5 + r"|PuTTY-User-Key-File-[0-9]")
_PEM_BLOCK = re.compile(_DASH5 + r"BEGIN [A-Z0-9 ]{3,40}" + _DASH5)
_BEARER = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9_.~+/-]{20,}=*)")
_SECRET_KEYS = (
    r"(?:api[_-]?key|app[_-]?key|application[_-]?key|x-application|x-authentication"
    r"|authorization|secret|password|passwd|passphrase|token|ssoid|cookie|session[_-]?id"
    r"|private[_-]?key)")
_SECRET_QUOTED = re.compile(
    r"(?i)" + _SECRET_KEYS + r"[A-Za-z0-9_-]*[\"']?\]?\s*[:=]\s*[bru]{0,2}[\"']"
    r"(?:bearer\s+)?([A-Za-z0-9_.~+/-]{16,}=*)[\"']")
_SECRET_BARE = re.compile(
    r"(?i)(?:^|[\s;])(?:export\s+)?[A-Za-z0-9_]*(?:api_?key|app_?key|secret|password|passwd|token|ssoid)"
    r"\s*=\s*([A-Za-z0-9_.~+/-]{16,}=*)\s*$")
_SECRET_HEADER = re.compile(r"(?i)\bx-(?:authentication|application)\s*:\s*([A-Za-z0-9_.~+/=-]{12,})")
_KNOWN_TOKEN = re.compile(
    r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|sk-(?:ant-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|[0-9]{8,10}:AA[A-Za-z0-9_-]{33})")
_BOOTSTRAP = re.compile(r"#c=[A-Za-z0-9_-]{16,}")
_NAME_FIELD_STRICT = re.compile(
    r"[\"'](?:runnerName|runner_name|selectionName|selection_name|horseName|horse_name)[\"']"
    r"\s*:\s*[\"'](?!Synthetic\b)[^\"'<>{}]{2,}[\"']")
_NAME_FIELD = re.compile(
    r"[\"'](?:name|runner|horse|selection)[\"']\s*:\s*[\"'](?!Synthetic\b)"
    r"[A-Z][A-Za-z'.-]{1,30}(?: [A-Z(][A-Za-z'.()-]{0,30}){0,4}[\"']")
_RUNNER_CONTEXT = re.compile(
    r"[\"'](?:sortPriority|selectionId|selection_id|adjustmentFactor|ltp|bsp|spn|spf)[\"']")
_PRICE = re.compile(r"(?<![0-9.])([0-9]{1,3}\.[0-9]{1,2})(?![0-9.])")
# Up to two leading cells before the name: a saddle-cloth or row number ("1", "12a", "(3)") followed by a
# cell separator, a list marker ("1." or "1)") or spaces.
_LEAD_CELL = r"[\"']?(?:[0-9]{1,3}[A-Za-z]?|\([0-9]{1,2}\))[\"']?(?:\s*[|,;\t]\s*|[.)]\s+|\s+)"
_ROW = re.compile(
    r"^[\s|>*#(\[{-]*(?:" + _LEAD_CELL + r"){0,2}[\"']?"
    r"(?P<name>[A-Z][A-Za-z'.-]{1,30}(?: [A-Z(][A-Za-z'.()-]{0,30}){0,4})"
    r"[\"']?\s*(?:[|,;\t]|:\s|\s{2,}|\s-\s)(?P<rest>.*)$")
_PRICE_TOKEN = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,6})?")
# Exchange-stream runner changes: price/size or traded ladders, or ltp/tv values, next to a runner id that
# is outside the reserved 9xxxxxxx selection namespace.
_STREAM_VALUES = re.compile(
    r"[\"'](?:atb|atl|batb|batl|bdatb|bdatl|trd|spb|spl)[\"']\s*:\s*\[\s*\[\s*-?[0-9]"
    r"|[\"'](?:ltp|tv|spn|spf)[\"']\s*:\s*-?[0-9]")
_STREAM_ID = re.compile(r"[\"']id[\"']\s*:\s*[\"']?(?!9[0-9]{7}(?![0-9]))[0-9]{4,10}(?![0-9])")
_ROW_SPLIT = re.compile(r"[\s|,;:()\[\]{}\"']+")
_PLACEHOLDER_MARKS = (
    "xxxx", "example", "placeholder", "redacted", "dummy", "changeme",
    "your_", "your-", "synthetic", "fake", "test",
)
_DOTTED_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_LOWER_IDENT = re.compile(r"[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+")

# 8-digit constants that are not identifiers. Changes need review.
NUMERIC_ALLOWLIST = frozenset({
    "31536000",  # seconds in a 365-day year
    "31557600",  # seconds in a Julian year
    "31622400",  # seconds in a 366-day year
})


def _is_price(token: str) -> bool:
    """A Betfair-range price: decimals up to 6 places (BSP has more than 2), or integer odds 2-1000."""
    if not _PRICE_TOKEN.fullmatch(token):
        return False
    if "." not in token:
        return 2 <= int(token) <= 1000
    return 1.01 <= float(token) <= 1000.0


def _event_exempt(digits: str) -> bool:
    n = int(digits)
    if n % 100000 == 0 or n & (n - 1) == 0 or digits in NUMERIC_ALLOWLIST:
        return True  # round numbers, powers of two, reviewed constants
    if len(set(digits)) == 1:
        return True  # repdigits such as 88888888
    year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    return 1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def _looks_secret(value: str) -> bool:
    if not value or value[0] in "/~.":
        return False
    low = value.lower()
    if any(mark in low for mark in _PLACEHOLDER_MARKS):
        return False
    if _DOTTED_NAME.fullmatch(value) or _LOWER_IDENT.fullmatch(value):
        return False
    if not (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)):
        return False
    return len(set(value)) >= 6


def _any_secret(regex, line: str) -> bool:
    return any(_looks_secret(m.group(1)) for m in regex.finditer(line))


def _line_codes(line: str) -> list:
    codes = []
    if _MARKET_ID.search(line):
        codes.append("market_id")
    if any(not _event_exempt(m.group(1)) for m in _EVENT_ID.finditer(line)):
        codes.append("event_id")
    if _MEMBER_PATH.search(line):
        codes.append("member_path")
    if "betangel-data/" in line.casefold() and _DATA_PATH_TEXT.search(line):
        codes.append("data_path_text")
    if _PRIVATE_KEY.search(line):
        codes.append("private_key")
    elif _PEM_BLOCK.search(line):
        codes.append("pem_block")
    if _any_secret(_BEARER, line):
        codes.append("bearer_token")
    if (_any_secret(_SECRET_QUOTED, line) or _any_secret(_SECRET_BARE, line)
            or _any_secret(_SECRET_HEADER, line)):
        codes.append("secret_value")
    if any(any(c.isdigit() for c in m.group(1)) for m in _KNOWN_TOKEN.finditer(line)):
        codes.append("known_token")
    if _BOOTSTRAP.search(line):
        codes.append("bootstrap_code")
    if _STREAM_VALUES.search(line) and _STREAM_ID.search(line):
        codes.append("stream_record")
    if _NAME_FIELD_STRICT.search(line):
        codes.append("runner_record")
    elif _NAME_FIELD.search(line) and (
            _RUNNER_CONTEXT.search(line)
            or sum(1 for m in _PRICE.finditer(line) if _is_price(m.group(1))) >= 2):
        codes.append("runner_record")
    return codes


def _table_row_name(line: str):
    """Return the runner-like name if the line looks like a name-and-prices row."""
    if len(line) > MAX_TABLE_LINE:
        return None
    m = _ROW.match(line)
    if not m:
        return None
    name = m.group("name")
    if name.startswith("Synthetic") or not any(c.islower() for c in name):
        return None
    prices = words = 0
    for token in _ROW_SPLIT.split(m.group("rest")):
        token = token.strip("£$%x")
        if not token:
            continue
        if _is_price(token):
            prices += 1
        elif any(c.isalpha() for c in token):
            words += 1
    return name if prices >= 2 and words <= 1 else None


def _text_findings(text: str) -> list:
    """Return (line, code) pairs for one decoded text file."""
    found = []
    rows = []
    for number, line in enumerate(text.split("\n"), 1):
        if line.endswith("\r"):
            line = line[:-1]
        for code in _line_codes(line):
            found.append((number, code))
        name = _table_row_name(line)
        if name is not None:
            rows.append((number, name))
    i = 0
    while i < len(rows):
        first = rows[i][0]
        window = [r for r in rows[i:] if r[0] <= first + 7]
        if len({name for _, name in window}) >= 3:
            found.append((first, "runner_table"))
            i += len(window)
        else:
            i += 1
    return found

# ------------------------------------------------------------- scan an entry


class Refusal(Exception):
    """A refusal with a fixed code; never carries paths or content."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _symlink_codes(target: str) -> list:
    codes = ["symlink"]
    if _has_data_component(target) or "betangel-data" in target.casefold():
        codes.append("data_path")
    return codes


def _content_codes(rel: str, data: bytes, oversize: bool) -> list:
    found = []
    magic = _magic_code(data[:SNIFF_BYTES])
    if magic:
        found.append((0, magic))
    if b"\0" in data[:SNIFF_BYTES]:
        if not _binary_allowed(rel):
            found.append((0, "binary_file"))
        return found
    if magic or oversize:
        return found
    found.extend(_text_findings(data.decode("utf-8", "replace")))
    return found


def _rel_id_codes(rel: str) -> list:
    codes = [code for code in _line_codes(rel) if code in _PATH_ID_CODES]
    return [(0, code) for code in codes]


def _size_limit(rel: str) -> int:
    return SIZE_ALLOWLIST.get(rel, MAX_FILE_BYTES)

# ------------------------------------------------------------------- git I/O

GIT = shutil.which("git") or "/usr/bin/git"


def _git(root: str, *args: str) -> bytes:
    proc = subprocess.run(
        [GIT, "-C", root, "-c", "core.quotepath=off", *args],
        stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if proc.returncode != 0:
        raise Refusal("git_failed")
    return proc.stdout


def _is_git_worktree(root: str) -> bool:
    proc = subprocess.run(
        [GIT, "-C", root, "rev-parse", "--is-inside-work-tree"],
        stdin=subprocess.DEVNULL, capture_output=True, check=False)
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def _read_exact(stream, n: int) -> bytes:
    chunks = []
    while n > 0:
        chunk = stream.read(min(n, 1 << 16))
        if not chunk:
            raise Refusal("git_short_read")
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def _staged_entries():
    """Yield (rel, findings) for every index entry, reading blobs from git."""
    raw = _git(ROOT, "ls-files", "-s", "-z")
    records = []
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != 3:
            raise Refusal("git_index_format")
        records.append((fields[0], fields[1], path.decode("utf-8", "surrogateescape")))
    blobs = [r for r in records if r[0] != b"160000"]
    proc = None
    if blobs:
        proc = subprocess.Popen(
            [GIT, "-C", ROOT, "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for mode, sha, rel in records:
            found = [(0, c) for c in _path_codes(rel)] + _rel_id_codes(rel)
            if mode == b"160000":
                found.append((0, "submodule"))
                yield rel, found
                continue
            proc.stdin.write(sha + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise Refusal("git_object")
            size = int(header[2])
            limit = _size_limit(rel)
            keep = size if size <= limit else min(size, SNIFF_BYTES)
            data = _read_exact(proc.stdout, keep)
            rest = size - keep
            while rest > 0:
                rest -= len(_read_exact(proc.stdout, min(rest, 1 << 16)))
            proc.stdout.read(1)
            codes = {c for _, c in found}
            if mode == b"120000":
                found.extend((0, c) for c in _symlink_codes(data.decode("utf-8", "replace")))
            elif "data_path" not in codes:
                oversize = size > limit
                if oversize:
                    found.append((0, "oversize"))
                found.extend(_content_codes(rel, data, oversize))
            yield rel, found
    finally:
        if proc is not None:
            proc.stdin.close()
            proc.stdout.close()
            proc.wait()

# ------------------------------------------------------------- tree I/O


def _lstat_no_follow(rel: str):
    """lstat each component of ROOT/rel; never follow a link. Returns (kind, value)."""
    parts = [p for p in rel.rstrip("/").split("/") if p]
    current = ROOT
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return "missing", None
        if stat.S_ISLNK(st.st_mode):
            return "symlink", os.readlink(current)
        if index < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            return "missing", None
    if stat.S_ISREG(st.st_mode):
        return "file", st.st_size
    if stat.S_ISDIR(st.st_mode):
        return "dir", None
    return "special", None


def _read_file(rel: str, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(os.path.join(ROOT, rel), flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refusal("not_regular")
        chunks, left = [], limit
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _tree_entry(rel: str):
    found = [(0, c) for c in _path_codes(rel)] + _rel_id_codes(rel)
    if any(c == "data_path" for _, c in found):
        return rel, found  # never touched on disk
    kind, value = _lstat_no_follow(rel)
    if kind == "missing":
        return rel, None
    if kind == "symlink":
        found.extend((0, c) for c in _symlink_codes(value))
    elif kind == "dir":
        found.append((0, "submodule"))
    elif kind == "special":
        found.append((0, "special_file"))
    else:
        limit = _size_limit(rel)
        oversize = value > limit
        if oversize:
            found.append((0, "oversize"))
        try:
            data = _read_file(rel, SNIFF_BYTES if oversize else limit)
        except Refusal:
            found.append((0, "special_file"))
            return rel, found
        found.extend(_content_codes(rel, data, oversize))
    return rel, found


def _walk(rel_top: str):
    """Yield file-like entries under ROOT/rel_top without following links."""
    stack = [rel_top]
    while stack:
        rel_dir = stack.pop()
        with os.scandir(os.path.join(ROOT, rel_dir) if rel_dir else ROOT) as it:
            for entry in sorted(it, key=lambda e: e.name):
                if entry.name == ".git":
                    continue
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                if _is_data_component(entry.name):
                    yield rel
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(rel)
                else:
                    yield rel


def _tree_rels(paths):
    if paths:
        rels = []
        for arg in paths:
            full = os.path.normpath(arg if os.path.isabs(arg) else os.path.join(ROOT, arg))
            rel = os.path.relpath(full, ROOT)
            if rel == os.curdir:
                rel = ""
            if rel == os.pardir or rel.startswith(os.pardir + os.sep):
                raise Refusal("path_outside_root")
            rel = rel.replace(os.sep, "/")
            if rel and _has_data_component(rel):
                rels.append(rel)  # flagged from the path alone, never touched
                continue
            kind = _lstat_no_follow(rel)[0] if rel else "dir"
            if kind == "missing":
                raise Refusal("path_missing")
            if kind == "dir":
                rels.extend(_walk(rel))
            else:
                rels.append(rel)
        return sorted(set(rels))
    if _is_git_worktree(ROOT):
        raw = _git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        return sorted({p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p})
    return sorted(_walk(""))

# ------------------------------------------------------------------ roots


def _check_lexical(path: str) -> None:
    if _has_data_component(path):
        raise Refusal("data_root")


def _safe_resolve(path: str) -> str:
    """Resolve links like realpath, refusing before any data path is touched."""
    pending = [p for p in os.path.abspath(path).split("/") if p]
    resolved = "/"
    hops = 0
    while pending:
        part = pending.pop(0)
        if part == ".":
            continue
        if part == "..":
            resolved = os.path.dirname(resolved)
            continue
        candidate = os.path.join(resolved, part)
        _check_lexical(candidate)
        try:
            st = os.lstat(candidate)
        except FileNotFoundError:
            raise Refusal("root_missing") from None
        if stat.S_ISLNK(st.st_mode):
            hops += 1
            if hops > 40:
                raise Refusal("symlink_loop")
            target = os.readlink(candidate)
            _check_lexical(target)
            if target.startswith("/"):
                resolved = "/"
            pending = [p for p in target.split("/") if p] + pending
        else:
            resolved = candidate
    return resolved


def _default_root() -> str:
    _check_lexical(os.getcwd())
    proc = subprocess.run(
        [GIT, "rev-parse", "--show-toplevel"],
        stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().decode("utf-8", "surrogateescape")
    return os.getcwd()

# ----------------------------------------------------------------- output

_HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")
_DIGIT_RUN = re.compile(r"[0-9]{5,}")
# The only suffixes a withheld path still shows: the scanner's own suffix sets plus common code and
# text suffixes. Any other suffix may be a word of the name (a runner's, say), so it is dropped.
# Compared exactly: a case variant shows no suffix.
SHOWN_SUFFIXES = (ARCHIVE_EXT | SQLITE_EXT | JSONL_EXT | DATA_EXT | KEY_EXT | IMAGE_EXT | AUDIO_EXT
                  | {".sqlite", ".py", ".md", ".txt", ".json", ".sh", ".js", ".mjs", ".css", ".html",
                     ".toml", ".yml", ".yaml", ".cfg", ".ini", ".swift"})


def _shown_path(rel: str, withhold_name: bool) -> str:
    if withhold_name:  # every component may carry data
        ext = os.path.splitext(rel.rstrip("/").rpartition("/")[2])[1]
        return "<name withheld>" + (ext if ext in SHOWN_SUFFIXES else "")
    shown = _DIGIT_RUN.sub("<n>", _HEX_RUN.sub("<hex>", rel.rstrip("/")))
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in shown)


def _report(results, mode: str) -> int:
    total = 0
    per_code = {}
    files_with = 0
    scanned = 0
    for index, (rel, found) in enumerate(results, 1):
        if found is None:
            continue
        scanned += 1
        if not found:
            continue
        files_with += 1
        withhold = any(c in _WITHHOLD_NAME or c in _WITHHOLD_CONTENT for _line, c in found)
        shown = _shown_path(rel, withhold)
        by_code = {}
        for line, code in sorted(set(found)):
            by_code.setdefault(code, []).append(line)
        for code in sorted(by_code):
            lines = by_code[code]
            per_code[code] = per_code.get(code, 0) + len(lines)
            total += len(lines)
            for line in lines[:MAX_REPORTED_LINES]:
                print(f"FAIL {code} {shown}:{line} (entry {index})")
            if len(lines) > MAX_REPORTED_LINES:
                print(f"FAIL {code} {shown}: +{len(lines) - MAX_REPORTED_LINES} more line(s) (entry {index})")
    if total:
        summary = ", ".join(f"{code}={n}" for code, n in sorted(per_code.items()))
        print(f"hygiene_scan: FAIL {total} finding(s) in {files_with} file(s) [{mode}]: {summary}")
        return EXIT_FINDINGS
    print(f"hygiene_scan: OK {scanned} file(s) scanned [{mode}]")
    return EXIT_CLEAN

# ------------------------------------------------------------------- main


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # never echo arguments, which may be paths
        print("hygiene_scan: refused:usage", file=sys.stderr)
        raise SystemExit(EXIT_REFUSED)


ROOT = ""


def _main(argv) -> int:
    global ROOT
    parser = _Parser(prog="hygiene_scan.py", add_help=True)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--list-rules", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if args.list_rules:
        for code, text in RULES.items():
            print(f"{code}\t{text}")
        return EXIT_CLEAN
    if args.staged and args.paths:
        raise Refusal("staged_with_paths")
    root = args.root if args.root else _default_root()
    _check_lexical(os.path.abspath(root))
    ROOT = _safe_resolve(root)
    if args.staged:
        if not _is_git_worktree(ROOT):
            raise Refusal("not_a_git_worktree")
        return _report(_staged_entries(), "staged")
    rels = _tree_rels(args.paths)
    return _report((_tree_entry(rel) for rel in rels), "paths" if args.paths else "tree")


def main(argv=None) -> int:
    try:
        return _main(sys.argv[1:] if argv is None else argv)
    except Refusal as refusal:
        print(f"hygiene_scan: refused:{refusal.code}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # codes only: never the message, which may hold paths
        print(f"hygiene_scan: internal_error:{type(exc).__name__}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
