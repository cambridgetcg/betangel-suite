"""Hygiene scanner for betangel-suite (docs/DESIGN.md I-9, sections 5.6 and 9.4).

It keeps licensed Betfair data, real identifiers and secrets out of git. On
any finding it exits 1 and prints one line per finding:

    FAIL <rule code> <path withheld>:<line> (entry <n>)

"<path withheld>" is literal and the same for every finding: the scanner
never prints a path or any part of one (no directory, name or suffix), and
never the text that matched. Line 0 means the finding is about the entry
itself (its name, type, size or link target), not one of its lines. Line
numbers count "\\n" line ends, as git and sed do; the rules also split a
line at CR, NEL, LS and the other str.splitlines() boundaries, and ignore
format characters (Unicode category Cf: a BOM, zero-width spaces). After
ten lines for one entry and rule, one more line counts the rest:

    FAIL <rule code> <path withheld>: +<k> more line(s) (entry <n>)

A last line gives the totals per rule code. The entry number is the
entry's position, counted from 1, in the list the scan worked through:

  --staged         the records of `git ls-files --stage`, in that order
                   (a conflicted path has one record per stage), for the
                   index git names: the real index when run by hand, but a
                   temporary one (GIT_INDEX_FILE) when the pre-commit hook
                   runs under `git commit -a` or `git commit <paths>`
  (no PATH)        the paths of `git ls-files --cached --others
                   --exclude-standard`, de-duplicated and sorted (outside a
                   git work tree: every file under the root, sorted)
  PATH ...         the files under the given paths, sorted

The message and history modes name their items in place of "entry <n>":

  --message        "(message)"
  --push, --range  "(commit <sha> message)", "(tag <sha> message)", and
                   "(commit <sha> entry <k>)" for the k-th record of
                   `git diff-tree -r --no-commit-id --raw --no-renames
                   --root -c <sha>` (deleted paths count, and publish
                   nothing; for a merge, -c lists only the paths that
                   differ from every parent)

docs/data-handling.md shows how Yu maps an entry number to its file
locally.

Run it with the fixed interpreter, standard library only:

    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py --staged
    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py
    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py PATH [PATH ...]
    /opt/homebrew/bin/python3.13 -I -S -B tools/hygiene_scan.py --range origin/main..HEAD

  --staged         scan every entry of the git index (what a commit would hold);
                   tools/pre-commit and tools/pre-merge-commit run this
  (no PATH)        scan the working tree: tracked plus untracked, not ignored
  PATH ...         scan these files or directories, relative to --root
  --message FILE   scan a commit message file; tools/commit-msg runs this
  --push REMOTE    scan what a push to REMOTE publishes, from git's pre-push
                   lines on stdin: every commit not known to be on REMOTE
                   (its message, and each path it adds or changes) and each
                   annotated tag's message; tools/pre-push runs this
  --range RANGE    the same for the commits `git rev-list RANGE` gives
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
Every git command it runs has replace refs and grafts turned off
(GIT_NO_REPLACE_OBJECTS=1, GIT_GRAFT_FILE=/dev/null), so it reads the objects
and parents a commit records and a push sends, never a stand-in.
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
import binascii
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import zlib

EXIT_CLEAN, EXIT_FINDINGS, EXIT_REFUSED = 0, 1, 2

# Size limit. DESIGN.md 5.6 says no file over 512 KB. The largest legitimate
# text file is DESIGN.md (about 185 KB at draft 0.2), and one real PRO member
# decompresses to about 8 MB at the median, so licensed dumps land far above
# the limit. DESIGN.md alone may grow to 2 MiB; it is still content-scanned.
MAX_FILE_BYTES = 512 * 1024
SIZE_ALLOWLIST = {"docs/DESIGN.md": 2 * 1024 * 1024}
SNIFF_BYTES = 8192  # magic bytes are read here, and only this much of an oversize file is read
MAX_REPORTED_LINES = 10  # per file and rule; the rest are counted
MAX_TABLE_LINE = 400  # a table row is matched on its first 400 characters

RULES = {
    "archive_member": "archive or compressed file (.bz2 .tar .gz .zip .xz ..., or by magic bytes)",
    "sqlite_file": "SQLite database or sidecar (.sqlite* .db, or by magic bytes)",
    "jsonl_file": "JSON-lines file (.jsonl .ndjson)",
    "data_file": "tabular or serialised data file (.csv .tsv .xlsx .parquet .pkl ...)",
    "key_file": "key, certificate or secrets file (.pem .key .p12 .crt .env .netrc id_*)",
    "image_outside_synthetic": "image or video outside docs/synthetic/",
    "binary_file": "binary file (a NUL anywhere, or not UTF-8) that is not an allowed media type",
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
    "encoded_blob": "base64, hex or \\xNN-escaped data that decodes to an archive, a zlib stream, "
                    "96+ bytes of binary, or text another rule flags",
    "filter_attribute": "path git gives a filter driver (clean filter, LFS), or a .gitattributes line "
                        "that sets one: git stores the filter's output, which the scan never sees",
}

# Identifier codes that are also checked on the path text itself.
_PATH_ID_CODES = ("market_id", "event_id", "member_path")
# Printed in place of every path. Any part of a path may carry data or a
# secret (a runner's name, a market id, a token used as a directory name),
# and no rule can show that a part is safe, so no part is ever printed.
WITHHELD = "<path withheld>"

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
    """Return the runner-like name if the line looks like a name-and-prices row.

    Only the first MAX_TABLE_LINE characters after the indent are matched, so a long row (many
    price columns, or padding) still counts, and the match stays bounded.
    """
    m = _ROW.match(line.lstrip()[:MAX_TABLE_LINE])
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


def _without_format_chars(line: str) -> str:
    """Drop Unicode format characters (category Cf): a BOM, zero-width spaces and joiners, soft hyphens."""
    if line.isascii():
        return line
    return "".join(c for c in line if unicodedata.category(c) != "Cf")


def _lines(text: str):
    """Yield (line number, line) with format characters removed, for the line rules.

    Line numbers count "\\n", as git, sed and editors do. A line that holds another line
    boundary (CR alone, NEL, LS, PS, VT, FF, FS, GS, RS: str.splitlines()) is split there
    too, and each part keeps the number of its "\\n" line.
    """
    for number, line in enumerate(text.split("\n"), 1):
        if line.endswith("\r"):
            line = line[:-1]
        for part in line.splitlines() or [""]:
            yield number, _without_format_chars(part)


def _text_findings(text: str) -> list:
    """Return (line, code) pairs for one decoded text file."""
    lines = list(_lines(text))
    found = _plain_findings(lines)
    found.extend((number, "encoded_blob") for number in _encoded_blob_lines(lines))
    return found


def _plain_findings(lines) -> list:
    """The line rules and runner_table over (line number, line) pairs."""
    found = []
    rows = []  # (position among the split lines, line number, name)
    for position, (number, line) in enumerate(lines):
        for code in _line_codes(line):
            found.append((number, code))
        name = _table_row_name(line)
        if name is not None:
            rows.append((position, number, name))
    i = 0
    while i < len(rows):
        first = rows[i][0]
        end = i
        while end < len(rows) and rows[end][0] <= first + 7:
            end += 1
        if len({name for _, _, name in rows[i:end]}) >= 3:
            found.append((rows[i][1], "runner_table"))
            i = end
        else:
            i += 1
    return found

# ------------------------------------------------------------ encoded data
#
# encoded_blob (Nuance's #2 review, item 5): data hidden in text as base64, as hex, or as \xNN
# escapes in a string literal. A token is one of:
#   b64  a run of 16+ base64 characters (standard or URL-safe alphabet), with its padding;
#   hex  8+ hex byte pairs, bare or split by single spaces or colons, or 0x-prefixed and
#        comma-separated, or the hex columns of an xxd or `hexdump -C` line;
#   esc  a quoted string literal holding at least one \xNN escape.
# A token that ends its line (only a closing quote, bracket, `;`, `+` or `\` after it) runs on
# into each next line that holds nothing but one token of the same kind: a wrapped dump, or
# implicit string concatenation. A comma ends a run, except after a 0x token, so a list of
# hashes is never joined into one. Each run is decoded and flagged, at its first line, when it
#   - is 24+ bytes that start with an archive or SQLite magic (gzip needs its method byte and
#     clear reserved flags, not just 1f 8b) or form a whole zlib stream;
#   - is 96+ bytes holding a NUL or not UTF-8 (binary data: compressed, encrypted or packed);
#   - is 16+ bytes of UTF-8 text that the line rules or runner_table flag.
# The last two need a base64 run to mix upper case, lower case and digits, and a hex run to
# hold a letter, as encoded binary does; names, paths and decimal numbers do not.

ENCODED_MIN_MAGIC = 24
ENCODED_MIN_BINARY = 96
ENCODED_MIN_TEXT = 16

# The token patterns, by kind: for any token, and for the short last line of a run.
_B64_TOKEN = {False: re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}"), True: re.compile(r"[A-Za-z0-9+/_-]{2,}={0,2}")}
_HEX_TOKEN = {short: re.compile(
    r"(?<![0-9A-Za-z])(?:0[xX][0-9a-fA-F]{2}(?:[ \t]*,[ \t]*0[xX][0-9a-fA-F]{2}){%s}"
    r"|[0-9a-fA-F]{2}(?:[ :]?[0-9a-fA-F]{2}){%s})(?![0-9A-Za-z])" % (count, count))
    for short, count in ((False, "7,"), (True, "0,"))}
_HEX_DUMP = {short: re.compile(
    r"\s*[0-9a-fA-F]{6,10}:?\s+(?P<hex>[0-9a-fA-F]{2}(?: {0,2}[0-9a-fA-F]{2}){%s})(?:\s{2,}.*)?\s*" % count)
    for short, count in ((False, "3,"), (True, "0,"))}
_HEX_DROP = re.compile(r"0[xX]|[^0-9a-fA-F]")
_ESC_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_HAS_XNN = re.compile(r"\\x[0-9a-fA-F]{2}")
_ESC = re.compile(r"\\(x[0-9a-fA-F]{2}|[0-7]{1,3}|.)", re.S)
_ESC_SIMPLE = {"n": 10, "r": 13, "t": 9, "a": 7, "b": 8, "f": 12, "v": 11, "\\": 92, "'": 39, '"': 34}
_PURE_BEFORE = {"b64": re.compile(r"\s*(?:\+\s*)?(?:[bBrRuU]{0,2}[\"'`])?"),
                "hex": re.compile(r"\s*(?:\+\s*)?(?:[bBrRuU]{0,2}[\"'`])?"),
                "esc": re.compile(r"\s*(?:\+\s*)?[bBrRuU]{0,2}")}
_ENDS_LINE = re.compile(r"[\"'`]?\s*[)\]\\;+]*\s*")
_ENDS_LINE_0X = re.compile(r"\s*,?\s*[)\]\\;+]*\s*")
_ENDS_LINE_ESC = re.compile(r"\s*[)\]\\;+]*\s*")
_URLSAFE = str.maketrans("-_", "+/")


def _unescape(body: str) -> bytes:
    """The bytes a string literal's body stands for: \\xNN, octal and one-letter escapes."""
    out = bytearray()
    pos = 0
    for m in _ESC.finditer(body):
        out += body[pos:m.start()].encode("utf-8")
        esc = m.group(1)
        if esc[0] == "x":
            out.append(int(esc[1:], 16))
        elif esc[0] in "01234567":
            out.append(int(esc, 8) & 0xFF)
        elif esc in _ESC_SIMPLE:
            out.append(_ESC_SIMPLE[esc])
        else:
            out += ("\\" + esc).encode("utf-8")
        pos = m.end()
    out += body[pos:].encode("utf-8")
    return bytes(out)


def _segments(kind: str, line: str, short: bool = False) -> list:
    """[(start, end, payload, ends_line, pure)] for one kind of token on one line.

    payload is the token text (b64), its hex digits (hex) or the bytes it stands for (esc).
    short: also tokens below the minimum length (the last line of a wrapped dump).
    """
    if kind == "hex":
        dump = _HEX_DUMP[short].fullmatch(line)
        if dump:  # xxd or hexdump -C: the offset and the character column are not data
            return [(dump.start("hex"), dump.end("hex"), _HEX_DROP.sub("", dump.group("hex")), True, True)]
        matches = list(_HEX_TOKEN[short].finditer(line))
    elif kind == "b64":
        matches = list(_B64_TOKEN[short].finditer(line))
    else:
        if "\\x" not in line:
            return []
        matches = [m for m in _ESC_LITERAL.finditer(line) if _HAS_XNN.search(m.group())]
    segments = []
    for m in matches:
        token = m.group()
        if kind == "hex":
            payload = _HEX_DROP.sub("", token)
            ends = (_ENDS_LINE_0X if token[:2] in ("0x", "0X") else _ENDS_LINE).fullmatch(line, m.end())
        else:
            payload = token if kind == "b64" else _unescape(token[1:-1])
            ends = (_ENDS_LINE if kind == "b64" else _ENDS_LINE_ESC).fullmatch(line, m.end())
        pure = bool(ends) and len(matches) == 1 and bool(_PURE_BEFORE[kind].fullmatch(line, 0, m.start()))
        segments.append((m.start(), m.end(), payload, bool(ends), pure))
    return segments


def _runs(kind: str, lines) -> list:
    """[(first line number, [payload, ...])]: the tokens of one kind, joined across lines as above."""
    runs = []
    current = None
    for number, line in lines:
        segments = _segments(kind, line)
        if current is not None:
            if len(segments) == 1 and segments[0][4]:
                current[1].append(segments[0][2])
                continue
            if not segments:
                tail = _segments(kind, line, short=True)
                if len(tail) == 1 and tail[0][4]:  # a short last line ends the run
                    current[1].append(tail[0][2])
            runs.append(current)
            current = None
        for _start, _end, payload, _ends, _pure in segments[:-1]:
            runs.append((number, [payload]))
        if segments:
            last = segments[-1]
            if last[3]:
                current = (number, [last[2]])
            else:
                runs.append((number, [last[2]]))
    if current is not None:
        runs.append(current)
    return runs


def _decode_run(kind: str, payloads: list):
    """(bytes, mixed) for one run, or (None, False) if it does not decode. mixed: it looks like encoded data."""
    if kind == "esc":
        return b"".join(payloads), True
    text = "".join(payloads)
    if kind == "hex":
        mixed = any(c in "abcdefABCDEF" for c in text)
        return bytes.fromhex(text[: len(text) // 2 * 2]), mixed
    mixed = (any(c.isupper() for c in text) and any(c.islower() for c in text)
             and any(c.isdigit() for c in text))
    bare = text.replace("=", "").translate(_URLSAFE)
    if len(bare) % 4 == 1:
        bare = bare[:-1]
    try:
        return binascii.a2b_base64((bare + "=" * (-len(bare) % 4)).encode("ascii")), mixed
    except (binascii.Error, ValueError):
        return None, False


def _blob_magic(blob: bytes) -> bool:
    if blob[:2] == b"\x1f\x8b":  # gzip: also the deflate method byte and clear reserved flags
        return blob[2] == 8 and blob[3] & 0xE0 == 0
    return _magic_code(blob[:SNIFF_BYTES]) is not None


def _zlib_stream(blob: bytes) -> bool:
    """True for a whole zlib stream (header, deflate data, Adler-32), or one that inflates past 1 MiB."""
    if blob[0] & 0x0F != 8 or blob[0] >> 4 > 7 or blob[1] & 0x20 or (blob[0] << 8 | blob[1]) % 31:
        return False
    inflater = zlib.decompressobj()
    try:
        inflater.decompress(blob, 1 << 20)
    except zlib.error:
        return False
    return inflater.eof or bool(inflater.unconsumed_tail)


def _is_utf8(blob: bytes) -> bool:
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _encoded_blob_lines(lines) -> list:
    """The first line number of every encoded run that decodes to something flagged."""
    flagged = []
    for kind in ("b64", "hex", "esc"):
        for number, payloads in _runs(kind, lines):
            blob, mixed = _decode_run(kind, payloads)
            if blob is None:
                continue
            if len(blob) >= ENCODED_MIN_MAGIC and (_blob_magic(blob) or _zlib_stream(blob)):
                flagged.append(number)
            elif not mixed:
                continue
            elif len(blob) >= ENCODED_MIN_BINARY and (b"\0" in blob or not _is_utf8(blob)):
                flagged.append(number)
            elif (len(blob) >= ENCODED_MIN_TEXT and b"\0" not in blob and _is_utf8(blob)
                    and _plain_findings(list(_lines(blob.decode("utf-8"))))):
                flagged.append(number)
    return flagged

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


# A .gitattributes line that gives a pattern (or an [attr] macro) a filter driver. "-filter" and
# "!filter" unset it and carry no "=".
_SETS_FILTER = re.compile(r"(?:^|\s)filter=\S")


def _content_codes(rel: str, data: bytes, oversize: bool) -> list:
    """Findings for one entry's bytes: all of it, or the first SNIFF_BYTES of an oversize one.

    Binary means a NUL anywhere in what was read, or bytes that are not strict UTF-8, so data
    after 8 KiB of text, a NUL-free zlib stream and text in another encoding (cp500, UTF-16)
    all count. Only text that decodes as UTF-8 reaches the text rules.
    """
    found = []
    magic = _magic_code(data[:SNIFF_BYTES])
    if magic:
        found.append((0, magic))
    if b"\0" in data:
        if not _binary_allowed(rel):
            found.append((0, "binary_file"))
        return found
    if magic or oversize:
        return found
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if not _binary_allowed(rel):
            found.append((0, "binary_file"))
        return found
    found.extend(_text_findings(text))
    if rel.rsplit("/", 1)[-1].casefold() == ".gitattributes":
        found.extend((number, "filter_attribute") for number, line in _lines(text)
                     if not line.lstrip().startswith("#") and _SETS_FILTER.search(line))
    return found


def _rel_id_codes(rel: str) -> list:
    codes = [code for code in _line_codes(rel) if code in _PATH_ID_CODES]
    return [(0, code) for code in codes]


def _size_limit(rel: str) -> int:
    return SIZE_ALLOWLIST.get(rel, MAX_FILE_BYTES)

# ------------------------------------------------------------------- git I/O

GIT = shutil.which("git") or "/usr/bin/git"
# A replace ref (`git replace`, refs/replace/*) or a graft (.git/info/grafts, or GIT_GRAFT_FILE) makes git show one
# object, or one list of parents, in another's place. A commit still records the original blob and a push sends the
# original objects, so a scan that followed them would pass a dirty blob or commit it never saw (round-4 review).
# Every git child below gets this process's environment (the hook's, with GIT_DIR or GIT_INDEX_FILE) plus these.
_NO_STAND_INS = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}


def _git_env() -> dict:
    return {**os.environ, **_NO_STAND_INS}


def _git(root: str, *args: str) -> bytes:
    proc = subprocess.run(
        [GIT, "-C", root, "-c", "core.quotepath=off", *args],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=_git_env())
    if proc.returncode != 0:
        raise Refusal("git_failed")
    return proc.stdout


def _is_git_worktree(root: str) -> bool:
    proc = subprocess.run(
        [GIT, "-C", root, "rev-parse", "--is-inside-work-tree"],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=_git_env())
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def _filtered(rels) -> set:
    """The paths of rels that git gives a filter driver (a clean filter, or LFS).

    git stores what the clean filter makes of a file, and the scan sees only that, so a filter
    could hide anything; each such path is a filter_attribute finding. The attribute is read
    twice: as `git add` reads it (each worktree .gitattributes, or the index's copy where the
    worktree has none, $GIT_DIR/info/attributes and core.attributesFile), and with --cached
    (the index's copies only, which the commit records even when the worktree's differ).
    Configured drivers (filter.<name>.clean, a global filter.lfs) are not read: they act only
    through an attribute.
    Paths with a data-root component are left out, so git reads no .gitattributes along them.
    """
    names = [rel for rel in rels if not _has_data_component(rel)]
    if not names:
        return set()
    stdin = b"".join(rel.encode("utf-8", "surrogateescape") + b"\0" for rel in names)
    flagged = set()
    for cached in ((), ("--cached",)):
        proc = subprocess.run(
            [GIT, "-C", ROOT, "check-attr", *cached, "-z", "--stdin", "filter"],
            input=stdin, capture_output=True, check=False, env=_git_env())
        if proc.returncode != 0:
            raise Refusal("git_check_attr")
        fields = proc.stdout.split(b"\0")  # path, attribute, value; one record per path, in order
        if len(fields) != 3 * len(names) + 1 or fields[-1]:
            raise Refusal("git_check_attr")
        for index, rel in enumerate(names):
            if fields[3 * index + 2] not in (b"unspecified", b"unset"):
                flagged.add(rel)
    return flagged


def _read_exact(stream, n: int) -> bytes:
    chunks = []
    while n > 0:
        chunk = stream.read(min(n, 1 << 16))
        if not chunk:
            raise Refusal("git_short_read")
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


class _Objects:
    """One `git cat-file --batch` for a whole scan: objects are read from git, never from disk."""

    def __init__(self):
        self.proc = None

    def read(self, sha: bytes, limit: int, sniff: int):
        """(type, size, data): all of an object up to limit bytes, else its first sniff bytes."""
        if self.proc is None:
            self.proc = subprocess.Popen(
                [GIT, "-C", ROOT, "cat-file", "--batch"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_git_env())
        self.proc.stdin.write(sha + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            raise Refusal("git_object")
        size = int(header[2])
        keep = size if size <= limit else min(size, sniff)
        data = _read_exact(self.proc.stdout, keep)
        rest = size - keep
        while rest > 0:
            rest -= len(_read_exact(self.proc.stdout, min(rest, 1 << 16)))
        self.proc.stdout.read(1)
        return header[1], size, data

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc.wait()


def _object_entry(objects: _Objects, rel: str, mode: bytes, sha: bytes, filtered=frozenset()) -> list:
    """Findings for one tree or index entry (path, mode, object), reading its blob from git."""
    found = [(0, c) for c in _path_codes(rel)] + _rel_id_codes(rel)
    if rel in filtered:
        found.append((0, "filter_attribute"))
    if mode == b"160000":
        found.append((0, "submodule"))
        return found
    limit = _size_limit(rel)
    kind, size, data = objects.read(sha, limit, SNIFF_BYTES)
    if kind != b"blob":
        raise Refusal("git_object")
    codes = {c for _, c in found}
    if mode == b"120000":
        found.extend((0, c) for c in _symlink_codes(data.decode("utf-8", "replace")))
    elif "data_path" not in codes:
        oversize = size > limit
        if oversize:
            found.append((0, "oversize"))
        found.extend(_content_codes(rel, data, oversize))
    return found


def _staged_entries():
    """Yield (rel, findings, where) for every index entry, reading blobs from git."""
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
    filtered = _filtered(sorted({rel for _mode, _sha, rel in records}))
    objects = _Objects()
    try:
        for index, (mode, sha, rel) in enumerate(records, 1):
            yield rel, _object_entry(objects, rel, mode, sha, filtered), f"entry {index}"
    finally:
        objects.close()

# --------------------------------------------------------- messages, history
#
# Nuance's #2 review, item 20: commit messages, and the history a push publishes, were never
# scanned; a file that one commit adds and a later one deletes passed every tree scan.

_OBJECT_ID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")
MAX_OBJECT_BYTES = 2 * MAX_FILE_BYTES  # a commit or tag object read whole: headers and message


def _message_findings(message: bytes) -> list:
    """A commit or tag message gets the content rules of a file: binary, oversize and text."""
    oversize = len(message) > MAX_FILE_BYTES
    found = [(0, "oversize")] if oversize else []
    return found + _content_codes("", message[:SNIFF_BYTES] if oversize else message, oversize)


def _message_of(data: bytes) -> bytes:
    """The message of a raw commit or tag object: everything after the first blank line."""
    _headers, blank, message = data.partition(b"\n\n")
    return message if blank else b""


def _read_message_file(path: str) -> bytes:
    """The message file git hands commit-msg, read with no link followed and never blocking."""
    _check_lexical(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise Refusal("message_unreadable") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refusal("message_not_regular")
        chunks, left = [], MAX_FILE_BYTES + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _is_commit(sha: str) -> bool:
    proc = subprocess.run(
        [GIT, "-C", ROOT, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{sha}^{{commit}}"],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=_git_env())
    return proc.returncode == 0


def _push_targets(remote: str, lines: bytes):
    """(rev-list arguments, tag objects) for what a push publishes, from git's pre-push lines.

    Each line is "<local ref> <local object> <remote ref> <remote object>". A deletion (local
    object all zeros) publishes nothing. The commits published are those reachable from the
    local objects but from neither the remote's old objects (when this clone has them) nor any
    of this clone's tracking refs for the remote (refs/remotes/<remote>/*): what the remote is
    known to hold already is not scanned again. A remote given as a URL has no tracking refs,
    so everything not reachable from the old objects is scanned.
    """
    tips, known = [], []
    for line in lines.splitlines():
        fields = line.split(b" ")
        if len(fields) != 4 or not (_OBJECT_ID.fullmatch(fields[1]) and _OBJECT_ID.fullmatch(fields[3])):
            raise Refusal("push_input")
        local, old = fields[1].decode(), fields[3].decode()
        if local.strip("0"):
            tips.append(local)
        if old.strip("0") and _is_commit(old):
            known.append(old)
    if not tips:
        return None, []
    return [*tips, "--not", *known, f"--remotes={remote}"], tips


def _peel_tags(objects: _Objects, tips) -> list:
    """The annotated tag objects among tips (and the tags they point at), each read once."""
    tags, seen = [], set()
    for sha in tips:
        while sha not in seen:
            seen.add(sha)
            kind, _size, data = objects.read(sha.encode(), MAX_OBJECT_BYTES, MAX_OBJECT_BYTES)
            if kind != b"tag":
                if kind != b"commit":
                    raise Refusal("push_object_not_commit")
                break
            tags.append((sha, data))
            target = data.split(b"\n", 1)[0].split(b" ")
            if len(target) != 2 or target[0] != b"object" or not _OBJECT_ID.fullmatch(target[1]):
                raise Refusal("git_object")
            sha = target[1].decode()
    return tags


def _diff_records(raw: bytes):
    """(mode, object, path) of each record of `git diff-tree -r -z --raw -c`: the result side.

    A record is ":<modes> <objects> <status>" (one colon per parent) then the path. Deleted
    paths have mode 000000.
    """
    fields = raw.split(b"\0")
    if fields[-1]:
        raise Refusal("git_diff_format")
    for meta, path in zip(fields[0:-1:2], fields[1:-1:2]):
        parents = len(meta) - len(meta.lstrip(b":"))
        parts = meta[parents:].split(b" ")
        if parents < 1 or len(parts) != 2 * parents + 3:
            raise Refusal("git_diff_format")
        yield parts[parents], parts[2 * parents + 1], path.decode("utf-8", "surrogateescape")


def _history_entries(revisions, tips=()):
    """Yield (rel, findings, where) for every commit rev-list gives for revisions, oldest first.

    Each commit's message is one item, then each path it adds or changes, numbered as
    `git diff-tree -r --no-commit-id --raw --no-renames --root -c <commit>` lists them (deleted
    paths count but publish nothing). For a merge, -c lists only paths that differ from every
    parent: whatever came from a parent was scanned in that parent's commit, or is on the remote
    already. Annotated tags among the pushed objects come first, as their messages.
    """
    objects = _Objects()
    try:
        for sha, data in _peel_tags(objects, tips):
            yield "", _message_findings(_message_of(data)), f"tag {sha} message"
        if revisions is None:
            return
        commits = _git(ROOT, "rev-list", "--reverse", "--topo-order", *revisions).decode().split()
        for sha in commits:
            kind, _size, data = objects.read(sha.encode(), MAX_OBJECT_BYTES, MAX_OBJECT_BYTES)
            if kind != b"commit":
                raise Refusal("git_object")
            yield "", _message_findings(_message_of(data)), f"commit {sha} message"
            raw = _git(ROOT, "diff-tree", "-r", "-z", "--no-commit-id", "--raw", "--no-renames", "--root", "-c", sha)
            for index, (mode, blob, rel) in enumerate(_diff_records(raw), 1):
                if mode != b"000000":
                    yield rel, _object_entry(objects, rel, mode, blob), f"commit {sha} entry {index}"
    finally:
        objects.close()

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


def _with_filter(entry, filtered: set):
    rel, found = entry
    if found is not None and rel in filtered:
        found.append((0, "filter_attribute"))
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
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=_git_env())
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().decode("utf-8", "surrogateescape")
    return os.getcwd()

# ----------------------------------------------------------------- output

def _report(results, mode: str, noun: str = "file(s)") -> int:
    """Print the findings of (rel, findings, where) results. Every path shows as WITHHELD, whatever the rule;
    where says which item it is: "entry <n>", "message", "commit <sha> message", "commit <sha> entry <k>" or
    "tag <sha> message"."""
    total = 0
    per_code = {}
    files_with = 0
    scanned = 0
    for _rel, found, where in results:
        if found is None:
            continue
        scanned += 1
        if not found:
            continue
        files_with += 1
        by_code = {}
        for line, code in sorted(set(found)):
            by_code.setdefault(code, []).append(line)
        for code in sorted(by_code):
            lines = by_code[code]
            per_code[code] = per_code.get(code, 0) + len(lines)
            total += len(lines)
            for line in lines[:MAX_REPORTED_LINES]:
                print(f"FAIL {code} {WITHHELD}:{line} ({where})")
            if len(lines) > MAX_REPORTED_LINES:
                print(f"FAIL {code} {WITHHELD}: +{len(lines) - MAX_REPORTED_LINES} more line(s) ({where})")
    if total:
        summary = ", ".join(f"{code}={n}" for code, n in sorted(per_code.items()))
        print(f"hygiene_scan: FAIL {total} finding(s) in {files_with} {noun} [{mode}]: {summary}")
        return EXIT_FINDINGS
    print(f"hygiene_scan: OK {scanned} {noun} scanned [{mode}]")
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
    parser.add_argument("--message")
    parser.add_argument("--push")
    parser.add_argument("--range", dest="revisions")
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
    history = [m for m in (args.message, args.push, args.revisions) if m is not None]
    if len(history) > 1 or (history and (args.staged or args.paths)):
        raise Refusal("one_mode_only")
    if any(not m or m.startswith("-") for m in history):
        raise Refusal("usage")
    root = args.root if args.root else _default_root()
    _check_lexical(os.path.abspath(root))
    ROOT = _safe_resolve(root)
    if args.message is not None:
        found = _message_findings(_read_message_file(args.message))
        return _report([("", found, "message")], "message", "message(s)")
    if args.staged or history:
        if not _is_git_worktree(ROOT):
            raise Refusal("not_a_git_worktree")
    if args.staged:
        return _report(_staged_entries(), "staged")
    if args.push is not None:
        revisions, tips = _push_targets(args.push, sys.stdin.buffer.read(1 << 20))
        return _report(_history_entries(revisions, tips), "push", "item(s)")
    if args.revisions is not None:
        return _report(_history_entries([args.revisions]), "range", "item(s)")
    rels = _tree_rels(args.paths)
    filtered = _filtered(rels) if _is_git_worktree(ROOT) else set()
    results = (_with_filter(_tree_entry(rel), filtered) for rel in rels)
    return _report(((rel, found, f"entry {index}") for index, (rel, found) in enumerate(results, 1)),
                   "paths" if args.paths else "tree")


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
