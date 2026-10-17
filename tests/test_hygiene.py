"""Tests for tools/hygiene_scan.py, tools/pre-commit and .gitignore (DESIGN.md I-9).

Each test builds its own temporary git repository (git init in a temp dir),
plants one forbidden thing, and runs the scanner as a subprocess with the
interpreter running the tests (-I -S -B). It asserts the exit status, the rule
code, that every finding line shows "<path withheld>" in place of the path, and
that the planted text never appears in the scanner's output.

Every planted value is assembled at runtime from fragments, so no line of this
file matches a scanner rule: the scanner passes over this file too. Planted
"real-shaped" values are invented; nothing here comes from licensed data.
Nothing in this file imports betangel_suite.
"""

from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "hygiene_scan.py"
HOOK = REPO / "tools" / "pre-commit"
HISTORY_HOOKS = {"commit-msg": "--message", "pre-merge-commit": "--staged", "pre-push": "--push"}
ZERO = "0" * 40
GITIGNORE = REPO / ".gitignore"
GIT = "/usr/bin/git"
PY313 = "/opt/homebrew/bin/python3.13"
# The test runner's guard starts a child only with the network switch kept on (betangel_suite/guard.py).
FORBID = {"BETANGEL_BETFAIR_FORBID_NETWORK": "1"}
FAIL_LINE = re.compile(r"^FAIL (\S+) ")
# Every finding prints the same placeholder for its path, whatever the rule: no directory, name or suffix.
WITHHELD = "<path withheld>"
FINDING_SHAPE = re.compile(r"FAIL [a-z_]+ <path withheld>:(?:[0-9]+| \+[0-9]+ more line\(s\)) \((?:entry [0-9]+|message"
                           r"|(?:commit|tag) [0-9a-f]{40} message|commit [0-9a-f]{40} entry [0-9]+)\)")


def _j(*parts: str) -> str:
    return "".join(parts)


# Real-shaped identifiers (invented), built so this file never matches a rule.
MARKET_2015 = _j("1.", "118", "765", "432")
MARKET_2024 = _j("1.", "2", "29", "876", "543")
EVENT = _j("274", "56", "789")
SELECTION = _j("123", "45", "678")
MEMBER = _j("PRO/", "2015/", "May/", "3/", EVENT, "/", MARKET_2015, ".bz2")
DATA_SHA = _j("ab12" * 8, "cd34" * 8)
DATA_TEXT_PATH = _j("~/betangel", "-data/historic/raw/", DATA_SHA, "/x")
RUNNER_NAMES = (_j("Bold", "mere Lad"), _j("Copper", " Kettle"), _j("Dancing", " Brave Two"))

# Reserved synthetic namespace (DESIGN.md 5.6).
SYN_MARKET = _j("1.", "999", "000", "101")
SYN_EVENT = _j("99", "000", "101")
SYN_SELECTION = _j("9", "123", "4567")
SYN_MEMBER = _j("PRO/", "2015/", "May/", "3/", SYN_EVENT, "/", SYN_MARKET, ".bz2")

# Secret-shaped values (invented).
TOKEN_BODY = _j("q7Rz", "K2mW", "p9Lx", "V4nB", "t8Hc", "J3dF", "y6Gs")
BEARER_LINE = _j("Authorization: ", "Bear", "er ", TOKEN_BODY)
SECRET_LINE = _j('APP', '_KEY = "', TOKEN_BODY[:20], '"')
GH_TOKEN = _j("gh", "p_", TOKEN_BODY, "Ab12Cd34Ef")
BOOT_URL = _j("http://127.0.0.1:8765/", "#c", "=", TOKEN_BODY[:22])
PEM_KEY = _j("-" * 5, "BEGIN ", "RSA PRIVATE", " KEY", "-" * 5)
PEM_CERT = _j("-" * 5, "BEGIN ", "CERTI", "FICATE", "-" * 5)
TOKEN_DIR = _j("Vq7", "Lm2", "Rz9", "Kt4", "Wx6", "Pb")  # a token-like directory name: no rule matches it


def _stream_text(salt: int = 0, lines: int = 30) -> str:
    """Invented exchange-stream lines with real-shaped ids: as plain text the scanner flags them (the control)."""
    runner_id = _j("123", "4567")
    return "".join(
        _j('{"op":"mcm","pt":', str(1431000000000 + 250 * i + salt), ',"mc":[{"id":"', MARKET_2015,
           '","rc":[{"at', 'b":[[', f"{2 + i % 7}.{i % 10}", ',10.0]],"id":', runner_id, "}]}]}\n")
        for i in range(lines))


def _wrap(text: str, width: int, fmt: str = "{}\n") -> str:
    return "".join(fmt.format(text[i:i + width]) for i in range(0, len(text), width))


def _escaped(data: bytes) -> str:
    return "".join(f"\\x{b:02x}" for b in data)


def _xxd(data: bytes) -> str:
    """xxd's default layout: offset, eight groups of four hex digits, the printable characters."""
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        groups = " ".join(chunk.hex()[i:i + 4] for i in range(0, 2 * len(chunk), 4))
        shown = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08x}: {groups:<39}  {shown}\n")
    return "".join(lines)


def _hexdump_c(data: bytes) -> str:
    """`hexdump -C`'s layout: offset, two halves of eight pairs, the printable characters in bars."""
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        left, right = (" ".join(f"{b:02x}" for b in half) for half in (chunk[:8], chunk[8:]))
        shown = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08x}  {left:<23}  {right:<23}  |{shown}|\n")
    return "".join(lines)


def _od(data: bytes) -> str:
    """`od`'s default layout: an octal offset, then eight 16-bit words in octal, low byte first; the end offset last."""
    padded = data + b"\0" * (len(data) % 2)
    lines = []
    for off in range(0, len(padded), 16):
        words = [padded[i] | padded[i + 1] << 8 for i in range(off, min(off + 16, len(padded)), 2)]
        lines.append(f"{off:07o}" + "".join(f"  {w:06o}" for w in words) + "\n")
    return "".join(lines) + f"{len(data):07o}\n"


def _git_binary_patch(data: bytes) -> str:
    """What `git diff --binary` prints for a new file holding data: the zlib stream in lines of a length letter
    ('A'-'Z' for 1-26 bytes, 'a'-'z' for 27-52) and base85, then the empty reverse hunk."""
    packed = zlib.compress(data)
    lines = []
    for i in range(0, len(packed), 52):
        chunk = packed[i:i + 52]
        letter = chr(ord("A") + len(chunk) - 1) if len(chunk) <= 26 else chr(ord("a") + len(chunk) - 27)
        lines.append(letter + base64.b85encode(chunk, pad=True).decode())
    return ("diff --git a/pkg/m.bin b/pkg/m.bin\nnew file mode 100644\nGIT binary patch\n"
            f"literal {len(data)}\n" + "\n".join(lines) + "\n\nliteral 0\nHcmV?d00001\n\n")


def _png(width: int = 24, height: int = 24) -> bytes:
    """A small synthetic RGB image in PNG form, as a screenshot tool writes one."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
    rows = b"".join(b"\0" + bytes((x * 7 + y * 3) % 256 for x in range(width * 3)) for y in range(height))
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return bytes([0x89]) + b"PNG\r\n" + bytes([0x1a]) + b"\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _pdf() -> bytes:
    """A minimal synthetic PDF with a compressed page stream."""
    body = zlib.compress(b"BT /F1 12 Tf 72 712 Td (synthetic page) Tj ET\n" * 8)
    return (b"%PDF-1.4\n%" + bytes([0xe2, 0xe3, 0xcf, 0xd3]) + b"\n1 0 obj << /Length " + str(len(body)).encode()
            + b" /Filter /FlateDecode >>\nstream\n" + body + b"\nendstream\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n")


def _without_nul(make) -> bytes:
    """The first of make(0), make(1), ... that holds no NUL byte."""
    for salt in range(1000):
        data = make(salt)
        if b"\0" not in data:
            return data
    raise AssertionError("no NUL-free variant")


def _git_env(home: str, tmp: str) -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": home,
        "LANG": "en_GB.UTF-8",
        "TMPDIR": tmp,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Synthetic Tester",
        "GIT_AUTHOR_EMAIL": "tester@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic Tester",
        "GIT_COMMITTER_EMAIL": "tester@example.invalid",
        **FORBID,
    }


class _RepoCase(unittest.TestCase):
    """A fresh temporary git repository per test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.home)
        os.mkdir(self.repo)
        self.env = _git_env(self.home, self.tmp)
        self.git("-c", "init.defaultBranch=main", "init", "-q", "--template=")
        self.write("README.md", "# synthetic repository\n")
        self.write("pkg/module.py", "def add(a, b):\n    return a + b\n")
        self.add("README.md", "pkg/module.py")

    # helpers ---------------------------------------------------------------

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [GIT, "-C", self.repo, *args], env=self.env, capture_output=True,
            check=check, timeout=60)

    def write(self, rel: str, content) -> str:
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def add(self, *rels: str, force: bool = False) -> None:
        self.git("add", *(["-f"] if force else []), "--", *rels)

    def scan(self, *args: str, root: str | None = None, env: dict | None = None, stdin: bytes = b"",
             timeout: float = 120):
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(SCANNER), "--root", root or self.repo, *args],
            env=env or self.env, input=stdin, capture_output=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        return proc.returncode, out

    @staticmethod
    def codes(out: str) -> set:
        return {m.group(1) for m in map(FAIL_LINE.match, out.splitlines()) if m}

    def assert_withheld(self, out: str) -> None:
        """Each line is a finding with the path withheld, or the scanner's own summary or refusal."""
        for line in out.splitlines():
            if not line.startswith("hygiene_scan: "):
                self.assertIsNotNone(FINDING_SHAPE.fullmatch(line), f"not a withheld finding: {line}")

    def assert_flags(self, code: str, secrets=(), modes=("--staged", None)) -> None:
        for mode in modes:
            with self.subTest(mode=mode or "tree", code=code):
                rc, out = self.scan(*([mode] if mode else []))
                self.assertEqual(rc, 1, f"expected findings, got rc={rc}: {out}")
                self.assertIn(code, self.codes(out), out)
                self.assert_withheld(out)
                for secret in secrets:
                    self.assertNotIn(secret, out, "scanner echoed planted text")

    def assert_clean(self, modes=("--staged", None)) -> None:
        for mode in modes:
            with self.subTest(mode=mode or "tree"):
                rc, out = self.scan(*([mode] if mode else []))
                self.assertEqual(rc, 0, out)
                self.assertIn("hygiene_scan: OK", out)

    def plant(self, rel: str, content, *secrets: str, code: str, force: bool = False) -> None:
        self.write(rel, content)
        self.add(rel, force=force)
        self.assert_flags(code, secrets)


class CleanAndSyntheticTests(_RepoCase):

    def test_clean_repo_passes(self):
        self.assert_clean()
        rc, out = self.scan("README.md", "pkg")
        self.assertEqual(rc, 0, out)

    def test_reserved_synthetic_namespace_passes(self):
        rows = "\n".join(f"| Synthetic {i} | {2 + i}.5 | {2 + i}.52 |" for i in range(1, 6))
        text = "\n".join([
            f"market = '{SYN_MARKET}'",
            f"event = {SYN_EVENT}",
            f"selection = {SYN_SELECTION}",
            f"member = '{SYN_MEMBER}'",
            '{"name": "Synthetic Park", "sortPriority": 1}',
            '{"runnerName": "Synthetic 3"}',
            "venue = 'Synthetic Park'",
            rows,
            "day = 20151015  # a date, not an id",
            "ms_per_day = 86400000",
            "two_to_24 = 16777216",
            "sha = '76f71dc94588a50f0df56dde2c3fabcf6e102f88'",
            "uuid = '12345678-5ec0-40c0-93f4-4adfd5acd836'",
            "pi = 3.14159265",
            "Authorization: Bearer <token>",
            "url = 'http://127.0.0.1:8765/#c=<code>'",
            "token = secrets.token_urlsafe(32)",
            "~/betangel-data/suite.noindex is the proposed suite root",
        ]) + "\n"
        self.write(f"tests/fixtures/{SYN_MARKET}.txt", text)
        self.add(f"tests/fixtures/{SYN_MARKET}.txt")
        self.assert_clean()

    def test_synthetic_screenshot_allowed_under_docs_synthetic(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
        self.write("docs/synthetic/screenshots/ladder.png", png)
        self.add("docs/synthetic/screenshots/ladder.png", force=True)
        self.assert_clean(modes=("--staged",))

    def test_design_md_size_allowlist(self):
        big = ("synthetic design prose line\n" * 24000)  # about 650 KB
        self.write("docs/DESIGN.md", big)
        self.add("docs/DESIGN.md")
        self.assert_clean()

    def test_list_rules(self):
        rc, out = self.scan("--list-rules")
        self.assertEqual(rc, 0)
        for code in ("archive_member", "market_id", "event_id", "private_key", "bearer_token"):
            self.assertIn(code, out)


class FileRuleTests(_RepoCase):

    def test_bz2_member(self):
        payload = bz2.compress(b'{"op":"mcm","pt":1}\n' * 10)
        self.plant(f"data/{MARKET_2015}.bz2", payload, MARKET_2015, code="archive_member", force=True)

    def test_archives_by_extension_and_magic(self):
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w") as tar:
            info = tarfile.TarInfo("member.txt")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"abc"))
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("member.txt", "abc")
        cases = {
            "a/archive.tar": tar_buf.getvalue(),
            "b/archive.gz": gzip.compress(b"abc"),
            "c/archive.zip": zip_buf.getvalue(),
            "d/disguised.txt": gzip.compress(b"abc"),
            "e/disguised.dat": bz2.compress(b"abc"),
            "f/disguised.bin": tar_buf.getvalue(),
        }
        for rel, data in cases.items():
            with self.subTest(rel=rel):
                self.setUp()
                self.plant(rel, data, code="archive_member", force=True)

    def test_sqlite_by_extension_and_magic(self):
        for rel in ("state/catalogue.sqlite", "state/disguised.bin"):
            with self.subTest(rel=rel):
                self.setUp()
                path = os.path.join(self.tmp, "made.db")
                conn = sqlite3.connect(path)
                conn.execute("CREATE TABLE t (x INTEGER)")
                conn.commit()
                conn.close()
                with open(path, "rb") as handle:
                    self.plant(rel, handle.read(), code="sqlite_file", force=True)

    def test_sqlite_sidecar_name(self):
        self.plant("state/journal.sqlite-wal", "x\n", code="sqlite_file", force=True)

    def test_jsonl(self):
        self.plant("data/commands.jsonl", '{"op": "x"}\n', code="jsonl_file", force=True)

    def test_csv_export(self):
        self.plant("out/practice.csv", "a,b\n1,2\n", code="data_file", force=True)

    def test_long_s_suffix_variants(self):
        # Forbidden names compare with str.casefold(): APFS here matches U+017F (long s) to "s", so
        # out/practice.c\u017fv opens as out/practice.csv.
        for rel, code in (("out/practice.c\u017fv", "data_file"), ("data/commands.j\u017fonl", "jsonl_file"),
                          ("state/x.\u017fqlite3", "sqlite_file"), ("state/x.db-\u017fhm", "sqlite_file"),
                          ("conf/id_r\u017fa", "key_file")):
            with self.subTest(rel=rel):
                self.setUp()
                self.plant(rel, "a,b\n1,2\n", code=code, force=True)

    def test_oversize(self):
        self.plant("docs/notes.md", "synthetic line\n" * 40000, code="oversize")

    def test_key_files(self):
        for rel in ("conf/client.pem", "conf/.env", "conf/client.crt"):
            with self.subTest(rel=rel):
                self.setUp()
                self.plant(rel, "placeholder\n", code="key_file", force=True)

    def test_image_outside_synthetic(self):
        self.plant("ui/race.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64, code="image_outside_synthetic",
                   force=True)

    def test_binary_file(self):
        self.plant("pkg/blob.bin", b"\0\1\2\3" * 64, code="binary_file")

    def test_forbidden_dirs(self):
        for directory in ("exports", "run", "screenshots", "private", "ledger", "sessions"):
            with self.subTest(directory=directory):
                self.setUp()
                self.plant(f"{directory}/note.txt", "x\n", code="forbidden_dir", force=True)

    def test_case_variant_forbidden_dirs_and_upstream_copy(self):
        # The lab's APFS volume folds case. The screenshots exemption under docs/synthetic/ stays
        # exact, so a case variant there fails closed.
        for rel, code in (("Exports/note.txt", "forbidden_dir"), ("a/LOGS/note.txt", "forbidden_dir"),
                          ("docs/synthetic/Screenshots/note.txt", "forbidden_dir"),
                          (_j("Vendor/Betangel", "-Research-copy/x.py"), "upstream_copy")):
            with self.subTest(rel=rel):
                self.setUp()
                self.plant(rel, "x = 1\n", code=code, force=True)

    def test_data_root_component(self):
        self.plant(_j("betangel", "-data/historic/note.txt"), "x\n", code="data_path", force=True)

    def test_noindex_component(self):
        self.plant("suite.noindex/note.txt", "x\n", code="data_path", force=True)

    def test_case_variant_data_root_component(self):
        # Compared with str.casefold(): APFS also folds U+017F (long s), so the last name is historic.
        for name in (_j("Betangel", "-Data"), "Historic", "Suite.NoIndex", "hi\u017ftoric"):
            with self.subTest(name=name):
                self.setUp()
                self.plant(f"{name}/note.txt", "x\n", code="data_path", force=True)
                rc, out = self.scan(name)
                self.assertEqual(rc, 1, out)
                self.assertIn("data_path", self.codes(out), out)
                self.assertIn(WITHHELD, out)
                self.assert_withheld(out)
                self.assertNotIn(name, out)

    def test_upstream_copy(self):
        self.plant("vendor/betangel-research-copy/x.py", "x = 1\n", code="upstream_copy")

    def test_symlink_into_data_root(self):
        link = os.path.join(self.repo, "data-link")
        # A dangling target inside the repo: it names a data root but can never
        # resolve to the real one, and nothing ever follows it.
        os.symlink(_j("missing.invalid/betangel", "-data/historic/raw"), link)
        self.add("data-link")
        self.assert_flags("data_path")
        self.assert_flags("symlink")

    def test_symlink_into_case_variant_data_root(self):
        # Dangling targets, as above: a case-variant data-root component, and the name inside a longer one.
        for target in (_j("missing.invalid/Betangel", "-Data"),
                       _j("missing.invalid/OLD-BETANGEL", "-DATA.bak")):
            with self.subTest(target=target):
                self.setUp()
                os.symlink(target, os.path.join(self.repo, "data-link"))
                self.add("data-link")
                self.assert_flags("data_path")

    def test_plain_symlink(self):
        os.symlink("README.md", os.path.join(self.repo, "readme-link"))
        self.add("readme-link")
        self.assert_flags("symlink")

    def test_gitlink_submodule(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.git("update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/sub")
        self.assert_flags("submodule", modes=("--staged",))

    def test_nested_repo_in_tree(self):
        nested = os.path.join(self.repo, "nested")
        os.mkdir(nested)
        subprocess.run([GIT, "-C", nested, "init", "-q", "--template="], env=self.env, check=True,
                       capture_output=True)
        with open(os.path.join(nested, "f.txt"), "w") as handle:
            handle.write("x\n")
        self.assert_flags("submodule", modes=(None,))

    def test_file_name_with_market_id_is_withheld(self):
        rel = f"notes/{MARKET_2015}-{EVENT}.txt"
        self.plant(rel, "nothing here\n", MARKET_2015, EVENT, code="market_id")
        rc, out = self.scan("--staged")
        self.assertIn("event_id", self.codes(out))
        self.assertIn(WITHHELD, out)


class ContentRuleTests(_RepoCase):

    def test_market_id_2015_shape(self):
        self.plant("pkg/a.py", f"MARKET = '{MARKET_2015}'\n", MARKET_2015, code="market_id")

    def test_market_id_2020s_shape(self):
        self.plant("pkg/b.md", f"see {MARKET_2024} for detail\n", MARKET_2024, code="market_id")

    def test_event_id(self):
        self.plant("pkg/c.json", f'{{"eventId": "{EVENT}"}}\n', EVENT, code="event_id")

    def test_selection_id_outside_namespace(self):
        self.plant("pkg/d.py", f"SELECTION = {SELECTION}\n", SELECTION, code="event_id")

    def test_member_path(self):
        self.plant("docs/e.md", f"opened {MEMBER} today\n", EVENT, MARKET_2015, code="member_path")

    def test_data_path_text(self):
        self.plant("docs/f.md", f"path: {DATA_TEXT_PATH}\n", DATA_SHA, code="data_path_text")

    def test_data_path_text_case_variant(self):
        path = _j("~/Betangel", "-Data/Historic/raw/", DATA_SHA, "/x")
        self.plant("docs/f2.md", f"path: {path}\n", DATA_SHA, code="data_path_text")

    def test_runner_table_markdown(self):
        rows = "\n".join(f"| {n} | {3 + i}.4 | {3 + i}.45 |" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/g.md", "| Runner | Back | Lay |\n|---|---|---|\n" + rows + "\n",
                   *RUNNER_NAMES, code="runner_table")

    def test_runner_table_python_tuples(self):
        rows = "\n".join(f'    ("{n}", {4 + i}.2, {4 + i}.3),' for i, n in enumerate(RUNNER_NAMES))
        self.plant("pkg/h.py", "ROWS = [\n" + rows + "\n]\n", *RUNNER_NAMES, code="runner_table")

    def test_runner_table_csv_in_text(self):
        rows = "\n".join(f"{n},{5 + i}.6,{5 + i}.7,{6 + i}.0" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/i.txt", rows + "\n", *RUNNER_NAMES, code="runner_table")

    def test_runner_table_with_saddle_cloth_numbers(self):
        rows = "\n".join(f"| {i + 1} | {n} | {3 + i}.4 | {3 + i}.45 |" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/g2.md", "| No | Runner | Back | Lay |\n|---|---|---|---|\n" + rows + "\n",
                   *RUNNER_NAMES, code="runner_table")

    def test_runner_table_csv_with_number_column(self):
        rows = "\n".join(f"{i + 1},{n},{3 + i}.4,{3 + i}.45" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/i2.txt", rows + "\n", *RUNNER_NAMES, code="runner_table")

    def test_runner_table_with_bsp_style_prices(self):
        rows = "\n".join(f"{n}, {4 + i}.1234, {5 + i}.6789" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/i3.txt", rows + "\n", *RUNNER_NAMES, code="runner_table")

    def test_runner_table_with_integer_prices(self):
        rows = "\n".join(f"| {n} | {5 + 2 * i} | {6 + 2 * i} |" for i, n in enumerate(RUNNER_NAMES))
        self.plant("docs/i4.md", rows + "\n", *RUNNER_NAMES, code="runner_table")

    def test_stream_record_with_a_real_shaped_runner_id(self):
        runner_id = _j("123", "4567")
        line = _j('{"op":"mcm","pt":', "1431", "000000000", ',"mc":[{"rc":[{"at', 'b":[[2.5,10.0],[2.4,5]],"id":',
                  runner_id, "}]}]}")
        self.plant("docs/stream.txt", line + "\n", runner_id, code="stream_record")

    def test_stream_record_in_the_reserved_namespace_passes(self):
        line = _j('{"op":"mcm","pt":', "1431", "000000000", ',"mc":[{"rc":[{"at', 'b":[[2.5,10.0],[2.4,5]],"id":',
                  SYN_SELECTION, "}]}]}")
        self.write("docs/syn-stream.txt", line + "\n")
        self.add("docs/syn-stream.txt")
        self.assert_clean()

    def test_runner_record_definition(self):
        name = RUNNER_NAMES[0]
        line = f'{{"id": 9100001, "name": "{name}", "sortPriority": 1}}\n'
        self.plant("pkg/j.json", line, name, code="runner_record")

    def test_runner_record_named_field(self):
        name = RUNNER_NAMES[1]
        self.plant("pkg/k.py", f'row = {{"runnerName": "{name}"}}\n', name, code="runner_record")

    def test_runner_named_file_is_withheld(self):
        # A file holding runner data may be named after the runner; plant() checks the name never prints.
        rows = "\n".join(f"| {n} | {3 + i}.4 | {3 + i}.45 |" for i, n in enumerate(RUNNER_NAMES))
        runner_id = _j("123", "4567")
        stream = _j('{"op":"mcm","pt":', "1431", "000000000", ',"mc":[{"rc":[{"at',
                    'b":[[2.5,10.0],[2.4,5]],"id":', runner_id, "}]}]}")
        name = RUNNER_NAMES[1]
        cases = (("runner_record", f"notes/{name}.txt", f'row = {{"runnerName": "{name}"}}\n'),
                 ("runner_table", f"docs/{name}.md", rows + "\n"),
                 ("stream_record", f"docs/{name}.txt", stream + "\n"))
        for code, rel, content in cases:
            with self.subTest(code=code):
                self.setUp()
                self.plant(rel, content, name, code=code)
                rc, out = self.scan("--staged")
                self.assertIn(WITHHELD, out)

    def test_withheld_path_hides_runner_named_directories_and_id_files(self):
        # Any component may carry data: the whole path is withheld, and identifier or data-path content
        # withholds it too. plant() checks in both modes that neither the name nor the id prints.
        name = RUNNER_NAMES[1]
        cases = (("runner_record", f"notes/{name}/card.txt", f'row = {{"runnerName": "{name}"}}\n'),
                 ("market_id", f"notes/{name}.txt", f"see {MARKET_2015}\n"),
                 ("event_id", f"notes/{name}/ids.txt", f"event {EVENT}\n"),
                 ("data_path_text", f"docs/{name}.md", f"path: {DATA_TEXT_PATH}\n"))
        for code, rel, content in cases:
            with self.subTest(code=code):
                self.setUp()
                self.plant(rel, content, name, MARKET_2015, EVENT, DATA_SHA, code=code)

    def test_withheld_path_shows_no_suffix(self):
        # A name can end in a word rather than a file type (a runner name with a dot for the space), and a
        # file type can be a word too (.swift, .key, .tar). No suffix prints, whatever it is, in the tree
        # scan or the staged one; the finding line is the same for every one of these names.
        name = RUNNER_NAMES[1]
        word = name.split()[-1]
        content = f'row = {{"runnerName": "{name}"}}\n'
        for base in (name.replace(" ", "."), f"card.{word.lower()}", f"{name}.MD", "card.swift", "card.key",
                     "card.tar", "card.sh", f"{name}.md", f"{name}.csv", "card.json", "card.bz2"):
            suffix = os.path.splitext(base)[1]
            with self.subTest(base=base):
                self.setUp()
                self.plant(f"notes/{base}", content, name, word, word.lower(), suffix, code="runner_record",
                           force=True)
                for mode in ("--staged", None):
                    rc, out = self.scan(*([mode] if mode else []))
                    # Index entries: README.md, notes/<base>, pkg/module.py.
                    self.assertIn("FAIL runner_record <path withheld>:1 (entry 2)", out)

    def test_private_key_header(self):
        self.plant("conf/notes.txt", PEM_KEY + "\nAAAA\n", PEM_KEY, code="private_key")

    def test_certificate_block(self):
        self.plant("conf/notes2.txt", PEM_CERT + "\nAAAA\n", PEM_CERT, code="pem_block")

    def test_bearer_token(self):
        self.plant("pkg/l.txt", BEARER_LINE + "\n", TOKEN_BODY, code="bearer_token")

    def test_secret_assignment(self):
        self.plant("pkg/m.py", SECRET_LINE + "\n", TOKEN_BODY[:20], code="secret_value")

    def test_secret_values_after_a_colon_or_a_space(self):
        # Round-4 review: "password: <value>", "api_key: <value>", "app key: <value>", "ssoid <value>" and "session
        # token is <value>" passed, in a YAML file and in a commit message (commit-msg and pre-push scan those now).
        value = TOKEN_BODY[:20]
        lines = (_j("pass", "word: ", value), _j("api", "_key: ", value), _j("app", " key: ", value),
                 _j("sso", "id ", TOKEN_BODY), _j("session", " token is ", TOKEN_BODY, "="))
        for index, line in enumerate(lines):
            with self.subTest(case=index):
                self.setUp()
                self.plant("conf/settings.yaml", "betfair:\n  " + line + "\n", value, code="secret_value")
                self.write(".git/MSG", "synthetic subject\n\n" + line + "\n")
                rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.codes(out), {"secret_value"})
                self.assertNotIn(value, out)

    def test_words_after_a_secret_name_stay_clean(self):
        # The same forms with type names, placeholders and plain words: _looks_secret keeps them out.
        self.write("pkg/types.py", "def check(token: str, password: SomeTypeName) -> None:\n    pass\n")
        self.write("conf/example.yaml", _j("pass", "word: changeme\n", "api", "_key: ${APP_KEY}\n",
                                           "session", " token is valid\n", "sso", "id synthetic-", TOKEN_BODY, "\n"))
        self.add("pkg/types.py", "conf/example.yaml")
        self.assert_clean()

    def test_known_token_prefix(self):
        self.plant("pkg/n.txt", f"token: {GH_TOKEN}\n", GH_TOKEN, code="known_token")

    def test_bootstrap_code(self):
        self.plant("pkg/o.txt", BOOT_URL + "\n", TOKEN_BODY[:22], code="bootstrap_code")

    def test_line_number_reported_without_text(self):
        body = "clean\n" * 6 + f"m = '{MARKET_2015}'\n"
        self.write("pkg/p.py", body)
        self.add("pkg/p.py")
        rc, out = self.scan("--staged")
        self.assertEqual(rc, 1)
        # Index entries: README.md, pkg/module.py, pkg/p.py; the entry number identifies the withheld path.
        self.assertIn("FAIL market_id <path withheld>:7 (entry 3)", out)
        self.assertNotIn(MARKET_2015, out)
        self.assertNotIn("p.py", out)

    def test_lines_past_the_limit_are_counted_with_the_path_withheld(self):
        body = "".join(f"m{i} = '{MARKET_2015}'\n" for i in range(12))
        self.write("pkg/p.py", body)
        self.add("pkg/p.py")
        for mode in ("--staged", None):
            with self.subTest(mode=mode or "tree"):
                rc, out = self.scan(*([mode] if mode else []))
                self.assertEqual(rc, 1, out)
                self.assertIn("FAIL market_id <path withheld>:10 (entry 3)", out)
                self.assertIn("FAIL market_id <path withheld>: +2 more line(s) (entry 3)", out)
                self.assert_withheld(out)
                self.assertNotIn(MARKET_2015, out)


class LineShapeTests(_RepoCase):
    """Tables and ids are found whatever ends a line, however long a row is, and with invisible format
    characters inside (Nuance's #2 review, item 21)."""

    ROWS = tuple(f"| {n} | {3 + i}.4 | {3 + i}.45 |" for i, n in enumerate(RUNNER_NAMES))

    def test_rows_ended_by_cr_nel_ls_or_ps(self):
        for label, sep in (("CR", "\r"), ("NEL", "\x85"), ("LS", " "), ("PS", " ")):
            with self.subTest(sep=label):
                self.setUp()
                self.plant("docs/t.md", sep.join(self.ROWS) + sep, *RUNNER_NAMES, code="runner_table")

    def test_rows_longer_than_400_characters(self):
        rows = [_j(n, ",", ",".join(f"{3 + i}.{k % 10}" for k in range(120))) for i, n in enumerate(RUNNER_NAMES)]
        self.assertTrue(all(len(row) > 400 for row in rows))
        self.plant("docs/t.csv.txt", "\n".join(rows) + "\n", *RUNNER_NAMES, code="runner_table")

    def test_a_bom_before_the_first_row(self):
        self.plant("docs/t.md", "﻿" + "\n".join(self.ROWS) + "\n", *RUNNER_NAMES, code="runner_table")

    def test_format_characters_inside_names(self):
        marks = ("​", "­", "⁠")  # zero-width space, soft hyphen, word joiner
        rows = [row.replace(n, n[:2] + mark + n[2:]) for row, n, mark in zip(self.ROWS, RUNNER_NAMES, marks)]
        self.plant("docs/t.md", "\n".join(rows) + "\n", *RUNNER_NAMES, code="runner_table")

    def test_table_renderings_accents_and_capitals(self):
        # Round-4 review: SQLite's .mode box and DuckDB (box-drawing bars), HTML cells, LaTeX's &, a fullwidth bar,
        # accented names and names in capitals were all missed. Each shape holds the same three invented rows.
        rows = [(n, f"{3 + i}.4", f"{3 + i}.45") for i, n in enumerate(RUNNER_NAMES)]
        light, heavy, double, full = "\u2502", "\u2503", "\u2551", "\uff5c"
        accented = ["\u00c9" + RUNNER_NAMES[0][1:], RUNNER_NAMES[1].replace("o", "\u00f3", 1),
                    RUNNER_NAMES[2].replace("e", "\u00e9", 1)]
        shapes = {
            "box": ("".join(f"{light} {n:<20}{light} {a:<6}{light} {b:<6}{light}\n" for n, a, b in rows), RUNNER_NAMES),
            "duckdb": ("".join(f"{light} {n:<20}{light} {a:>8} {light} {b:>8} {light}\n" for n, a, b in rows),
                       RUNNER_NAMES),
            "heavy and double bars": ("".join(f"{heavy} {n} {double} {a} {double} {b} {heavy}\n" for n, a, b in rows),
                                      RUNNER_NAMES),
            "html": ("<table>\n" + "".join(f"<tr><td>{n}</td><td>{a}</td><td>{b}</td></tr>\n" for n, a, b in rows)
                     + "</table>\n", RUNNER_NAMES),
            "html with attributes and markup": ("".join(f'<tr class="r"><TD align="left"><b>{n}</b></TD><td>{a}</td>'
                                                        f"<td>{b}</td></tr>\n" for n, a, b in rows), RUNNER_NAMES),
            "latex": ("".join(f"{n} & {a} & {b} \\\\\n" for n, a, b in rows), RUNNER_NAMES),
            "fullwidth bar": ("".join(f"{full}{n}{full}{a}{full}{b}{full}\n" for n, a, b in rows), RUNNER_NAMES),
            "accented": ("".join(f"| {n} | {a} | {b} |\n" for n, (_, a, b) in zip(accented, rows)), accented),
            "capitals": ("".join(f"| {n.upper()} | {a} | {b} |\n" for n, a, b in rows),
                         [n.upper() for n in RUNNER_NAMES]),
        }
        for name, (text, names) in shapes.items():
            with self.subTest(shape=name):
                self.setUp()
                self.plant("docs/t.md", text, *names, code="runner_table")

    def test_capitals_with_another_word_are_not_a_runner_table(self):
        # A name in capitals counts only when its row holds prices and nothing else: a heading or code with a word
        # beside its numbers is not a runner row.
        rows = "".join(f"| {n.upper()} | fast | {3 + i}.4 | {3 + i}.45 |\n" for i, n in enumerate(RUNNER_NAMES))
        self.write("docs/t.md", rows)
        self.add("docs/t.md")
        self.assert_clean()

    def test_format_character_inside_a_market_id(self):
        hidden = MARKET_2015[:5] + "​" + MARKET_2015[5:]
        self.plant("pkg/u.py", f"m = '{hidden}'\n", MARKET_2015, hidden, code="market_id")

    def test_line_numbers_count_newlines_only(self):
        self.write("docs/v.md", f"one\rtwo\nthree\x0bfour\nm = '{MARKET_2015}'\n")
        self.add("docs/v.md")
        for mode in ("--staged", None):
            with self.subTest(mode=mode or "tree"):
                rc, out = self.scan(*([mode] if mode else []))
                # Index entries: README.md, docs/v.md, pkg/module.py.
                self.assertIn("FAIL market_id <path withheld>:3 (entry 2)", out)
                self.assertNotIn(MARKET_2015, out)


class BinaryAnywhereTests(_RepoCase):
    """Binary data is caught wherever it sits in a file, with or without a NUL (Nuance's #2 review, item 5)."""

    def test_control_text_is_flagged(self):
        self.plant("data/control.txt", _stream_text(), MARKET_2015, code="market_id")
        self.assert_flags("stream_record", (MARKET_2015,))

    def test_nul_free_zlib_stream(self):
        data = _without_nul(lambda salt: zlib.compress(_stream_text(salt).encode()))
        self.plant("data/blob.dat", data, MARKET_2015, code="binary_file")

    def test_text_in_another_encoding(self):
        data = _stream_text().encode("cp500")
        self.assertNotIn(b"\0", data)
        self.plant("data/notes.txt", data, MARKET_2015, code="binary_file")

    def test_archive_after_8_kib_of_text(self):
        prose = ("synthetic notes line\n" * 440).encode()
        self.assertGreater(len(prose), 8192)
        self.plant("docs/notes.md", prose + bz2.compress(_stream_text().encode()), MARKET_2015, code="binary_file")

    def test_allowed_media_without_a_nul_stays_clean(self):
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(1, 256))
        self.write("docs/synthetic/screenshots/ladder.png", png)
        self.add("docs/synthetic/screenshots/ladder.png", force=True)
        self.assert_clean()


class EncodedDataTests(_RepoCase):
    """Data hidden in text as base64, hex or \\xNN escapes (Nuance's #2 review, item 5). Every payload is
    built here from invented stream lines; none is written into this file."""

    def plant_shapes(self, shapes: dict) -> None:
        for name, text in shapes.items():
            with self.subTest(shape=name):
                self.setUp()
                self.plant("pkg/blob.py", text, MARKET_2015, code="encoded_blob")

    def test_base64_of_an_archive_member(self):
        member = bz2.compress(_stream_text().encode())
        text = base64.b64encode(member).decode()
        self.plant_shapes({
            "wrapped at 76": base64.encodebytes(member).decode(),
            "one line": f'DATA = "{text}"\n',
            "implicit concatenation": "DATA = (\n" + _wrap(text, 60, '    "{}"\n') + ")\n",
            "URL-safe": base64.urlsafe_b64encode(member).decode() + "\n",
            "a JSON value": '{"payload": "' + text + '", "n": 1}\n',
        })

    def test_hex_of_an_archive_member(self):
        member = bz2.compress(_stream_text().encode())
        text = member.hex()
        pairs = [text[i:i + 2] for i in range(0, len(text), 2)]
        self.plant_shapes({
            "one line": text + "\n",
            "wrapped at 60": _wrap(text, 60),
            "spaced pairs": "".join(" ".join(pairs[i:i + 16]) + "\n" for i in range(0, len(pairs), 16)),
            "C array": "const unsigned char d[] = {\n"
                       + "".join("    " + ", ".join("0x" + p for p in pairs[i:i + 12]) + ",\n"
                                 for i in range(0, len(pairs), 12)) + "};\n",
            "xxd": _xxd(member),
            "hexdump -C": _hexdump_c(member),
        })

    def test_escaped_bytes_of_an_archive_member(self):
        member = bz2.compress(_stream_text().encode())
        pieces = [member[i:i + 16] for i in range(0, len(member), 16)]
        self.plant_shapes({
            "bytes repr": f"DATA = {member!r}\n",
            "wrapped repr": "DATA = (\n" + "".join(f"    {piece!r}\n" for piece in pieces) + ")\n",
            "C string": f'const char d[] = "{_escaped(member)}";\n',
            # A quote that never closes comes first: the other kind is still read (round-4 finishing review).
            "C string after an unclosed quote": f'/* it\'s */ const char d[] = "{_escaped(member)}";\n',
        })

    def test_runs_joined_across_lines(self):
        # No single line here decodes to anything flagged: each run needs all its lines, and a zlib stream
        # needs its short last line too (the Adler-32 check), so these test the joining.
        text = _stream_text(lines=3).encode()
        stream = zlib.compress(text)
        noise = bytes((i * 131 + 7) % 251 for i in range(150))  # no magic, not UTF-8, 150 bytes
        shapes = {}
        for label, data in (("zlib", stream), ("binary", noise), ("text", text)):
            shapes[f"base64 {label}"] = _wrap(base64.b64encode(data).decode(), 20)
            shapes[f"hex {label}"] = _wrap(data.hex(), 20)
            shapes[f"escapes {label}"] = "D = (\n" + "".join(
                f"    b'{_escaped(data[i:i + 10])}'\n" for i in range(0, len(data), 10)) + ")\n"
        self.plant_shapes(shapes)

    def test_a_short_last_line_closes_a_run(self):
        # A zlib stream under 96 bytes is flagged only whole, and its Adler-32 check sits on the last line,
        # which here is shorter than a token on its own (16 base64 characters, or 8 hex pairs).
        stream = zlib.compress(_j('{"op":"mcm","id":"', MARKET_2015, '"}').encode())
        self.assertLess(len(stream), 96)
        shapes = {}
        for label, text in (("base64", base64.b64encode(stream).decode()), ("hex", stream.hex())):
            width = next(w for w in range(16, 40, 2) if 2 <= len(text) % w < 16)
            shapes[label] = _wrap(text, width)
        self.plant_shapes(shapes)

    def test_small_zlib_stream_and_gzip(self):
        record = _j('{"op":"mcm","id":"', MARKET_2015, '"}').encode()
        self.plant_shapes({
            "zlib": f'x = "{base64.b64encode(zlib.compress(record)).decode()}"\n',
            "gzip": f'x = "{base64.b64encode(gzip.compress(record)).decode()}"\n',
        })

    def test_encodings_that_tools_emit(self):
        # Round-4 review: a GIT binary patch (git diff --binary, format-patch), a decimal byte list (list(data),
        # Array.from(buf), od -An -tu1), od's own output and a PostgreSQL bytea literal all passed.
        member = bz2.compress(_stream_text().encode())
        rows = [member[i:i + 16] for i in range(0, len(member), 16)]
        self.plant_shapes({
            "GIT binary patch": _git_binary_patch(member),
            "decimal list": "DATA = [\n" + "".join("    " + ", ".join(map(str, row)) + ",\n" for row in rows) + "]\n",
            "decimal list on one line": f"DATA = {list(member)}\n",
            "decimal list of text": f"DATA = {list(_stream_text(lines=2).encode())}\n",
            "od -An -tu1": "".join("".join(f"{b:4d}" for b in row) + "\n" for row in rows),
            "od -An -tx1": "".join("        " + "".join(f"  {b:02x}" for b in row) + "\n" for row in rows),
            "od": _od(member),
            "bytea literal": "INSERT INTO t VALUES ('\\x" + member.hex() + "');\n",
        })

    def test_encodings_nested_or_behind_a_line_marker(self):
        # Round-4 review: base64 of base64 passed, and so did a dump whose every line starts with a comment or list
        # marker when its first line holds no magic (each marked line was too short to count on its own).
        member = bz2.compress(_stream_text().encode())
        text = base64.b64encode(member).decode()
        tail = base64.b64encode(member[60:]).decode()
        self.plant_shapes({
            "base64 of base64": base64.encodebytes(text.encode()).decode(),
            "hex of base64": _wrap(text.encode().hex(), 64),
            "hash comments": _wrap(tail, 76, "# {}\n"),
            "slash comments, hex": _wrap(member[60:].hex(), 64, "// {}\n"),
            "YAML list": "blob:\n" + _wrap(tail, 76, "  - {}\n"),
            "quoted mail": _wrap(tail, 76, "> {}\n"),
        })

    def test_near_misses_stay_clean(self):
        hashes = [hashlib.sha256(f"synthetic {i}".encode()).hexdigest() for i in range(12)]
        magic = (b"\x1f\x8b", b"PK\x03\x04", b"PK\x05\x06", b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd")
        reserved = _j('{"op":"mcm","id":"', SYN_MARKET, '","rc":[{"id":', SYN_SELECTION, "}]}").encode()
        files = {
            "pkg/hashes.py": "HASHES = [\n" + "".join(f'    "{h}",\n' for h in hashes) + "]\n",
            "pkg/pins.json": "{\n" + "".join(f'  "pkg/m{i}.py": "{h}",\n' for i, h in enumerate(hashes)) + "}\n",
            "pkg/magic.py": "".join(f'    or head[:4] in (b"{_escaped(m)}", b"{_escaped(m)}")\n' for m in magic),
            "pkg/short.py": "MAGIC = (\n" + "".join(f'    b"{_escaped(m)}"\n' for m in magic[:2]) + ")\n",
            "pkg/names.py": "".join(f"    def test_a_rather_long_name_number_{i}(self):\n        pass\n"
                                    for i in range(30)),
            "docs/names.md": "".join(f"some_long_identifier_name_{i}\n" for i in range(40)),
            "docs/paths.md": "".join(f"docs/proposals/section{i}/appendix\n" for i in range(40)),
            "docs/numbers.md": "".join(", ".join(str(10 + (i * 7 + k) % 89) for k in range(16)) + ",\n"
                                       for i in range(20)),
            "docs/words.md": "we add a bad bed to the cafe; dead beef faced a decade\n" * 10,
            "pkg/ids.py": f"sha = '{hashes[0][:40]}'\nrun = '12345678-5ec0-40c0-93f4-4adfd5acd836'\n" * 5,
            "pkg/png.py": f'PNG = b"{_escaped(bytes([0x89]))}PNG\\r\\n{_escaped(bytes([0x1a]))}\\n"\n',
            "docs/reserved.md": base64.b64encode(reserved).decode() + "\n",
            # A price ladder in hundredths, as ui/ticks.json holds it: sorted, so not data.
            "ui/ladder.json": '{"ticks": [\n' + "".join("    " + ", ".join(str(t) for t in range(k, k + 16)) + ",\n"
                                                      for k in range(101, 1000, 16)) + "]}\n",
            "docs/list.md": "".join(f"- SyntheticRunnerNameNumber{chr(65 + i)}\n" for i in range(20))
                            + "".join(f"# some_long_identifier_name_{i}\n" for i in range(20)),
            "pkg/counts.py": "COUNTS = [\n" + "".join("    " + ", ".join(str((i * 5 + k) % 31) for k in range(16))
                                                     + ",\n" for i in range(12)) + "]\n",
        }
        for rel, text in files.items():
            self.write(rel, text)
        self.add(*files)
        self.assert_clean()

    def test_lists_of_full_hashes_stay_clean(self):
        # Round-4 recheck: read without its markers, a bulleted or commented list of full commit or file hashes was
        # one hex run of 96+ bytes, flagged as binary, in a file and in a commit message. A run whose every line is
        # one whole 40- or 64-digit token is a list of hashes: only a magic, a zlib stream or flagged text counts.
        sha1 = [hashlib.sha1(f"synthetic {i}".encode()).hexdigest() for i in range(64)]
        sha256 = [hashlib.sha256(f"synthetic {i}".encode()).hexdigest() for i in range(64)]
        lists = {
            "- sha1 x8": "".join(f"- {h}\n" for h in sha1[:8]),
            "# sha1 x8": "".join(f"# {h}\n" for h in sha1[:8]),
            "- sha256 x4": "".join(f"- {h}\n" for h in sha256[:4]),
            "* sha1 and words x6": "".join(f"* {h} synthetic subject words\n" for h in sha1[:6]),
            "- `sha1` x8": "".join(f"- `{h}`\n" for h in sha1[:8]),
            "bare sha256 x4": "".join(f"{h}\n" for h in sha256[:4]),
            "indented, both lengths": "".join(f"  - {h}\n" for h in sha1[:3] + sha256[:3]),
            # The longest run that still counts as a list of hashes (round-4 finishing review).
            "- sha1 x64": "".join(f"- {h}\n" for h in sha1),
            "bare sha256 x64": "".join(f"{h}\n" for h in sha256),
        }
        for name, text in lists.items():
            with self.subTest(shape=name):
                self.setUp()
                self.write("docs/commits.md", "The fixes:\n" + text)
                self.add("docs/commits.md")
                self.assert_clean()
                self.write(".git/MSG", "synthetic subject\n\nThe fixes:\n" + text
                           + "\nCo-Authored-By: Synthetic Tester <tester@example.invalid>\n")
                rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
                self.assertEqual((rc, out.strip()), (0, "hygiene_scan: OK 1 message(s) scanned [message]"))

    def test_data_in_whole_hash_lines_is_still_caught(self):
        # The same shape holding an archive, a zlib stream or flagged text, padded with spaces so every line is one
        # whole 40- or 64-digit token, as in a list of hashes.
        member = bz2.compress(_stream_text().encode())
        record = _j('{"op":"mcm","id":"', MARKET_2015, '"}').encode()

        def lines(data: bytes, width: int, fmt: str) -> str:
            return _wrap((data + b" " * (-len(data) % (width // 2))).hex(), width, fmt)

        shapes = {
            "bz2, - 40": lines(member, 40, "- {}\n"),
            "bz2, # 64": lines(member, 64, "# {}\n"),
            "bz2, bare 64": lines(member, 64, "{}\n"),
            "zlib, - 40": lines(zlib.compress(record), 40, "- {}\n"),
            "gzip, * 64": lines(gzip.compress(record), 64, "* {}\n"),
            "text, - 40": lines(_stream_text(lines=2).encode(), 40, "- {}\n"),
        }
        self.plant_shapes(shapes)
        for name in ("bz2, - 40", "text, - 40"):
            with self.subTest(shape=name, mode="--message"):
                self.write(".git/MSG", "synthetic subject\n\nThe fixes:\n" + shapes[name])
                rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.codes(out), {"encoded_blob"})
                self.assertNotIn(MARKET_2015, out)

    def test_data_after_a_real_hash_or_with_one_odd_byte_is_still_caught(self):
        # Round-4 finishing review: the magic and zlib tests looked only at a run's first byte, and one NUL or 0xFF
        # byte made a run binary, which skipped the text test. So data after one real hash line, as a commit message
        # cites a commit, and text holding one such byte, passed in the layouts of a list of hashes. Its recheck:
        # UTF-16 text, read with each NUL as a line end, put each character on a line of its own, and passed.
        member = bz2.compress(_stream_text().encode())
        record = _j('{"op":"mcm","id":"', MARKET_2015, '"}').encode()
        text = _stream_text(lines=2).encode()
        table = "".join(f"| {name} | 3.5 | 4.25 |\n" for name in RUNNER_NAMES).encode()
        lead = {40: hashlib.sha1(b"synthetic lead").hexdigest(), 64: hashlib.sha256(b"synthetic lead").hexdigest()}

        def lines(data: bytes, width: int, fmt: str, first: bool = True) -> str:
            body = _wrap((data + b" " * (-len(data) % (width // 2))).hex(), width, fmt)
            return (fmt.format(lead[width]) if first else "") + body

        shapes = {
            "bz2 after a hash, bare 40": lines(member, 40, "{}\n"),
            "bz2 after a hash, - 40": lines(member, 40, "- {}\n"),
            "gzip after a hash, quoted 64": lines(gzip.compress(record), 64, '"{}"\n'),
            "zlib after a hash, # 64": lines(zlib.compress(record), 64, "# {}\n"),
            "SQLite after a hash, - `40`": lines(b"SQLite format 3\x00" + bytes(range(16, 112)), 40, "- `{}`\n"),
            "text after a hash, bare 40": lines(text, 40, "{}\n"),
            "text with a NUL, bare 64": lines(b"\0" + text, 64, "{}\n", first=False),
            "text with a 0xFF byte, quoted 40": lines(b"\xff" + text, 40, '"{}"\n', first=False),
            "a table with a NUL, - 40": lines(b"\0" + table, 40, "- {}\n", first=False),
            "UTF-16LE text, bare 64": lines(text.decode().encode("utf-16-le"), 64, "{}\n", first=False),
            "UTF-16 text with a BOM after a hash, - 40": lines(text.decode().encode("utf-16"), 40, "- {}\n"),
        }
        self.plant_shapes(shapes)
        for name in ("bz2 after a hash, - 40", "text with a NUL, bare 64", "UTF-16LE text, bare 64"):
            with self.subTest(shape=name, mode="--message"):
                self.write(".git/MSG", "synthetic subject\n\nThe fixes:\n" + shapes[name])
                rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.codes(out), {"encoded_blob"})
                self.assertNotIn(MARKET_2015, out)

    def test_images_documents_and_long_runs_in_hash_lines_are_caught(self):
        # Round-4 finishing review: a list of hashes is never binary data, so images and PDFs, which have no archive
        # magic, passed in its layouts, as did any binary data with no magic, however long. Images and documents now
        # count by their signatures, and a run of more than 64 such lines is binary data again.
        lead = hashlib.sha1(b"synthetic lead").hexdigest()
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw deflate: no header, no magic
        raw = packer.compress(_stream_text(lines=400).encode() + bytes(range(256)) * 8) + packer.flush()
        self.assertGreater(len(raw), 64 * 32)

        def lines(data: bytes, width: int, fmt: str) -> str:
            return _wrap((data + b" " * (-len(data) % (width // 2))).hex(), width, fmt)

        shapes = {
            "PNG, - 40": lines(_png(), 40, "- {}\n"),
            "PNG after a hash, bare 64": lead + "\n" + lines(_png(), 64, "{}\n"),
            "PDF, # 64": lines(_pdf(), 64, "# {}\n"),
            "PDF after a hash, - 40": f"- {lead}\n" + lines(_pdf(), 40, "- {}\n"),
            "raw deflate, 65+ lines of 64": lines(raw, 64, "{}\n"),
            "raw deflate, 65+ lines of - 40": lines(raw, 40, "- {}\n"),
        }
        for name, text in shapes.items():
            with self.subTest(shape=name):
                self.setUp()
                self.plant("docs/dump.md", text, code="encoded_blob")
        with self.subTest(shape="PNG, - 40", mode="--message"):
            self.write(".git/MSG", "synthetic subject\n\nThe fixes:\n" + shapes["PNG, - 40"])
            rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
            self.assertEqual(rc, 1, out)
            self.assertEqual(self.codes(out), {"encoded_blob"})


class ScanTimeTests(_RepoCase):
    """One long line scans in linear time (round-4 recheck, issue 1). _SECRET_LOOSE took 212 s on one 120 KB
    snake_case line, and an audit of every pattern found more that backtrack the same way: a secret name repeated
    in one word, a JWT-like run, and whitespace after a token (the end-of-line checks were quadratic or cubic). The
    round-4 finishing review found one more: an unclosed string literal full of escaped quotes, on a line holding
    "\\x", was read again from every quote (16 minutes for 512 KB)."""

    SIZE = 200 * 1024
    BOUND = 10  # seconds for one 200 KB line; the quadratic versions took minutes, the cubic ones far longer

    # (head, unit repeated to SIZE characters, tail). Each line is its own file: two of them would be oversize.
    SHAPES = {
        "snake_case": ("", "x_", ""),
        "kebab-case": ("", "a-", ""),
        "underscores": ("", "_", "!"),
        "base64url alphabet": ("", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", ""),
        "a secret name repeated in one word": ("", "token_", ""),
        "JWT-like run": ("", "eyJ-", ""),
        "spaces after a base64 token": ("A" * 24, " ", "!"),
        "spaces after a 0x list": (", ".join(["0x5a"] * 8), " ", "!"),
        "tabs after a byte list": (" ".join(["7"] * 16), "\t", "!"),
        "spaces after an escaped literal": ('"' + "\\x5a" * 4 + '"', " ", "!"),
        "an unclosed literal of escaped single quotes": ("\\x41 '", "\\'", ""),
        "an unclosed literal of escaped double quotes": ('\\x41 "', '\\"', ""),
        "letters": ("", "a", ""),
        "digits": ("", "7", ""),
        "'=' and ':'": ("token", "=:", ""),
        "quotes": ("", "\"'`", ""),
        "hex digits": ("", "0123456789abcdef", "!"),
        "key words": ("", "key key app ", ""),
        "table cells": ("", "| Aaaa | 1.5 ", "|"),
        "box drawing": ("", "│ 1.5 ", ""),
    }

    def test_long_lines_scan_in_linear_time(self):
        for index, (name, (head, unit, tail)) in enumerate(self.SHAPES.items()):
            line = head + (unit * (self.SIZE // len(unit) + 1))[:self.SIZE] + tail + "\n"
            rel = f"docs/long{index}.txt"
            self.write(rel, line)
            with self.subTest(shape=name):
                try:
                    rc, out = self.scan(rel, timeout=self.BOUND)
                except subprocess.TimeoutExpired:
                    self.fail(f"no result within {self.BOUND} s")
                self.assertIn(rc, (0, 1), out)
                self.assertRegex(out.splitlines()[-1], r"^hygiene_scan: (OK|FAIL) ")
                self.assert_withheld(out)


class FilterAttributeTests(_RepoCase):
    """A clean filter changes what git stores, so the staged scan never sees the file itself (Nuance's #2
    review, item 19). Here the "digits" filter turns 0-9 into a-j, which no content rule can see through."""

    def setUp(self):
        super().setUp()
        # Written into the file: the test runner's guard lets tests run only a few local git subcommands.
        with open(os.path.join(self.repo, ".git", "config"), "a") as handle:
            handle.write('[filter "digits"]\n\tclean = tr 0-9 a-j\n\tsmudge = cat\n')

    def plant_hidden(self) -> None:
        self.write("notes/a.txt", f"m = '{MARKET_2015}'\n")
        self.add("notes/a.txt")

    def global_config(self, text: str) -> dict:
        """The environment for a scan with this global git config (git children of tests keep /dev/null)."""
        config = os.path.join(self.home, "gitconfig")
        with open(config, "w") as handle:
            handle.write(text)
        return {**self.env, "GIT_CONFIG_GLOBAL": config}

    def staged_out(self, env: dict | None = None) -> str:
        rc, out = self.scan("--staged", env=env)
        self.assertEqual(rc, 1, out)
        self.assert_withheld(out)
        self.assertNotIn(MARKET_2015, out)
        self.assertNotIn("market_id", self.codes(out), "the staged blob holds no id: only the attribute shows")
        return out

    def test_worktree_gitattributes(self):
        self.write(".gitattributes", "*.txt filter=digits\n")  # never staged: `git add` still reads it
        self.plant_hidden()
        # Index entries: README.md, notes/a.txt, pkg/module.py.
        self.assertIn("FAIL filter_attribute <path withheld>:0 (entry 2)", self.staged_out())
        self.assert_flags("filter_attribute", (MARKET_2015,), modes=(None,))

    def test_gitattributes_changed_after_staging(self):
        self.write(".gitattributes", "*.txt filter=digits\n")
        self.add(".gitattributes")
        self.plant_hidden()
        # The worktree copy now sets no filter, but the staged one (what the commit records) does: only
        # check-attr --cached reads it. (A missing worktree copy would not do: git then reads the index.)
        self.write(".gitattributes", "*.txt text\n")
        out = self.staged_out()
        # Index entries: .gitattributes, README.md, notes/a.txt, pkg/module.py.
        self.assertIn("FAIL filter_attribute <path withheld>:0 (entry 3)", out)
        self.assertIn("FAIL filter_attribute <path withheld>:1 (entry 1)", out)

    def test_info_attributes_and_a_global_attributes_file(self):
        info = os.path.join(self.repo, ".git", "info")
        os.makedirs(info, exist_ok=True)
        with open(os.path.join(info, "attributes"), "w") as handle:
            handle.write("*.txt filter=digits\n")
        self.plant_hidden()
        self.assertIn("FAIL filter_attribute <path withheld>:0 (entry 2)", self.staged_out())
        os.unlink(os.path.join(info, "attributes"))
        attributes = os.path.join(self.home, "attributes")
        with open(attributes, "w") as handle:
            handle.write("*.txt filter=digits\n")
        env = self.global_config(f"[core]\n\tattributesFile = {attributes}\n")
        self.assertIn("FAIL filter_attribute <path withheld>:0 (entry 2)", self.staged_out(env))

    def test_gitattributes_lines_that_set_a_filter(self):
        for line in ("*.dat filter=digits", "[attr]packed filter=digits -diff", "docs/** text filter=x eol=lf"):
            with self.subTest(line=line):
                self.setUp()
                self.plant(".gitattributes", f"# synthetic\n{line}\n", code="filter_attribute")
                rc, out = self.scan("--staged")
                self.assertIn("FAIL filter_attribute <path withheld>:2 (entry 1)", out)

    def test_attributes_without_a_filter_stay_clean(self):
        self.write(".gitattributes", "# filter=digits is not used\n* -filter\n*.txt !filter\n*.sh text eol=lf\n")
        self.write("notes/a.txt", "synthetic notes\n")
        self.add(".gitattributes", "notes/a.txt")
        self.assert_clean()

    def test_a_global_lfs_filter_does_not_block(self):
        # `git lfs install` writes these driver lines into the global config; no attribute uses them here.
        env = self.global_config('[filter "lfs"]\n\tclean = git-lfs clean -- %f\n\tsmudge = git-lfs smudge -- %f\n'
                                 "\tprocess = git-lfs filter-process\n\trequired = true\n")
        self.write("notes/a.txt", "synthetic notes\n")
        self.add("notes/a.txt")
        for mode in ("--staged", None):
            with self.subTest(mode=mode or "tree"):
                rc, out = self.scan(*([mode] if mode else []), env=env)
                self.assertEqual(rc, 0, out)


class WithheldPathTests(_RepoCase):
    """Secret, symlink, submodule and special-file findings withhold the whole path too (Astra's re-review
    of #2). Every name is invented; each test checks that no part of the path prints."""

    def assert_paths_scan(self, args, line: str, hidden) -> None:
        rc, out = self.scan(*args)
        self.assertEqual(rc, 1, out)
        self.assertIn(line, out)
        self.assert_withheld(out)
        for text in hidden:
            self.assertNotIn(text, out, "scanner echoed part of the path")

    def test_secret_value_under_a_token_named_directory(self):
        # The directory name alone is no finding; the content's secret_value is, and the name stays hidden.
        hidden = (TOKEN_DIR, "conf", "settings", TOKEN_BODY[:20])
        self.plant(f"conf/{TOKEN_DIR}/settings.py", SECRET_LINE + "\n", *hidden, code="secret_value")
        self.assert_paths_scan(("conf",), "FAIL secret_value <path withheld>:1 (entry 1)", hidden)

    def test_secret_findings_under_a_runner_named_path(self):
        name = RUNNER_NAMES[2]
        cases = (("private_key", PEM_KEY + "\nAAAA\n", PEM_KEY), ("pem_block", PEM_CERT + "\nAAAA\n", PEM_CERT),
                 ("bearer_token", BEARER_LINE + "\n", TOKEN_BODY),
                 ("secret_value", SECRET_LINE + "\n", TOKEN_BODY[:20]),
                 ("known_token", f"token: {GH_TOKEN}\n", GH_TOKEN), ("bootstrap_code", BOOT_URL + "\n", TOKEN_BODY[:22]))
        for code, content, secret in cases:
            with self.subTest(code=code):
                self.setUp()
                self.plant(f"notes/{name}/{name}.txt", content, name, name.split()[0], secret, code=code)

    def test_dangling_symlink(self):
        name = RUNNER_NAMES[0]
        os.mkdir(os.path.join(self.repo, "links"))
        os.symlink(os.path.join("missing.invalid", TOKEN_DIR), os.path.join(self.repo, "links", name))
        self.add(f"links/{name}")
        hidden = (name, name.split()[0], "links", TOKEN_DIR)
        self.assert_flags("symlink", hidden)
        self.assert_paths_scan((f"links/{name}",), "FAIL symlink <path withheld>:0 (entry 1)", hidden)

    def test_gitlink_and_nested_repository(self):
        name = RUNNER_NAMES[1]
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.git("update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/{name}")
        os.makedirs(os.path.join(self.repo, "vendor", name))      # so the tree scan finds the gitlink too
        self.assert_flags("submodule", (name, name.split()[0], "vendor"))
        self.setUp()                                               # a fresh repository: no gitlink in it
        nested = os.path.join(self.repo, "nested", TOKEN_DIR)
        os.makedirs(nested)
        subprocess.run([GIT, "-C", nested, "init", "-q", "--template="], env=self.env, check=True,
                       capture_output=True)
        self.assert_flags("submodule", ("nested", TOKEN_DIR), modes=(None,))

    def test_fifo_named_by_path(self):
        # Explicit-path mode: git lists no FIFO, and the scanner never opens one.
        name = RUNNER_NAMES[2]
        os.mkdir(os.path.join(self.repo, "notes"))
        os.mkfifo(os.path.join(self.repo, "notes", name))
        hidden = (name, name.split()[0], "notes")
        self.assert_paths_scan((f"notes/{name}",), "FAIL special_file <path withheld>:0 (entry 1)", hidden)
        self.assert_paths_scan(("notes",), "FAIL special_file <path withheld>:0 (entry 1)", hidden)


class ModeTests(_RepoCase):

    def test_staged_scans_the_index_not_the_worktree(self):
        self.write("pkg/q.py", "x = 1\n")
        self.add("pkg/q.py")
        self.write("pkg/q.py", f"x = '{MARKET_2015}'\n")  # unstaged change
        rc, out = self.scan("--staged")
        self.assertEqual(rc, 0, out)
        rc, out = self.scan()
        self.assertEqual(rc, 1, out)
        self.add("pkg/q.py")
        self.write("pkg/q.py", "x = 1\n")  # staged bad, worktree clean
        rc, out = self.scan("--staged")
        self.assertEqual(rc, 1, out)
        self.assertNotIn(MARKET_2015, out)

    def test_ignored_file_is_still_caught_when_forced_into_the_index(self):
        self.write(".gitignore", "*.bz2\n")
        self.write("data/x.bz2", bz2.compress(b"abc"))
        self.add(".gitignore")
        self.assert_clean()  # ignored and unstaged: nothing to commit
        self.add("data/x.bz2", force=True)
        self.assert_flags("archive_member")

    def test_explicit_paths(self):
        self.write("pkg/r.py", f"x = '{MARKET_2015}'\n")
        rc, out = self.scan("pkg/r.py")
        self.assertEqual(rc, 1, out)
        rc, out = self.scan("README.md")
        self.assertEqual(rc, 0, out)
        rc, out = self.scan("pkg")
        self.assertEqual(rc, 1, out)

    def test_refuses_paths_outside_root_and_missing_paths(self):
        rc, out = self.scan("../home")
        self.assertEqual(rc, 2, out)
        self.assertIn("refused:path_outside_root", out)
        rc, out = self.scan("no/such/file")
        self.assertEqual(rc, 2, out)

    def test_refuses_a_root_inside_a_data_root(self):
        root = os.path.join(self.tmp, _j("betangel", "-data"), "repo")
        os.makedirs(root)
        rc, out = self.scan(root=root)
        self.assertEqual(rc, 2, out)
        self.assertIn("refused:data_root", out)

    def test_refuses_a_root_reached_through_a_link_into_a_data_root(self):
        target = os.path.join(self.tmp, "suite.noindex")
        os.mkdir(target)
        link = os.path.join(self.tmp, "innocent")
        os.symlink(target, link)
        rc, out = self.scan(root=link)
        self.assertEqual(rc, 2, out)
        self.assertIn("refused:data_root", out)

    def test_refuses_a_root_inside_a_case_variant_data_root(self):
        # One parent per name: on the lab's case-insensitive APFS, Historic and the long-s spelling
        # (U+017F) are the same directory.
        for index, name in enumerate((_j("Betangel", "-Data"), "SUITE.NOINDEX", "Historic", "hi\u017ftoric")):
            with self.subTest(name=name):
                root = os.path.join(self.tmp, f"case{index}", name, "repo")
                os.makedirs(root)
                rc, out = self.scan(root=root)
                self.assertEqual(rc, 2, out)
                self.assertIn("refused:data_root", out)

    def test_refuses_a_root_reached_through_a_link_into_a_case_variant_data_root(self):
        target = os.path.join(self.tmp, "Suite.NoIndex")
        os.mkdir(target)
        link = os.path.join(self.tmp, "innocent")
        os.symlink(target, link)
        rc, out = self.scan(root=link)
        self.assertEqual(rc, 2, out)
        self.assertIn("refused:data_root", out)

    def test_staged_needs_a_git_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        rc, out = self.scan("--staged", root=plain)
        self.assertEqual(rc, 2, out)

    def test_usage_errors_do_not_echo_arguments(self):
        rc, out = self.scan(_j("--", MARKET_2015))
        self.assertEqual(rc, 2, out)
        self.assertNotIn(MARKET_2015, out)


class GitignoreTests(_RepoCase):

    def setUp(self):
        super().setUp()
        shutil.copyfile(GITIGNORE, os.path.join(self.repo, ".gitignore"))

    def ignored(self, rel: str) -> bool:
        return self.git("check-ignore", "-q", "--no-index", "--", rel, check=False).returncode == 0

    def test_licensed_shapes_are_ignored(self):
        for rel in ("x.bz2", "a/b.tar", "a/b.tar.gz", "c.zip", "d.sqlite", "d.sqlite-wal",
                    "e.jsonl", "f.csv", "exports/g.txt", "run/engine.lock",
                    "screenshots/a.png", "a/private/x", "ledger/v.txt", "s.noindex/x",
                    "ui/race.png", "docs/synthetic/x.bz2", "k.pem", ".env", "__pycache__/m.pyc"):
            with self.subTest(rel=rel):
                self.assertTrue(self.ignored(rel))

    def test_synthetic_screenshots_and_sources_are_not_ignored(self):
        for rel in ("docs/synthetic/ladder.png", "docs/synthetic/screenshots/a.png",
                    "README.md", "pin/betangel-research.json", "ui/manifest.json",
                    "betangel_suite/data/catalogue.py", "betangel_suite/data/ledger.py",
                    "tools/pre-commit"):
            with self.subTest(rel=rel):
                self.assertFalse(self.ignored(rel))


class HistoryTests(_RepoCase):
    """Commit messages, tag messages and every commit a push publishes (Nuance's #2 review, item 20).

    The test runner's guard lets tests run only a few local git subcommands (no merge, push, tag or
    update-ref), so refs, HEAD, MERGE_HEAD and a tag object are written into the temporary .git here.
    """

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def write_ref(self, ref: str, value: str) -> None:
        self.write(os.path.join(".git", ref), value + "\n")

    def push_scan(self, *lines: str, remote: str = "origin"):
        return self.scan("--push", remote, stdin="".join(line + "\n" for line in lines).encode())

    def assert_push_flags(self, out: str, *expected: str) -> None:
        for line in expected:
            self.assertIn(line, out)
        self.assert_withheld(out)
        self.assertNotIn(MARKET_2015, out)
        self.assertNotIn("notes", out)

    def history_only_file(self):
        """base, then A adds a file holding an id, then B deletes it: the tip holds nothing."""
        base = self.commit("base")
        self.write("notes/a.txt", f"m = '{MARKET_2015}'\n")
        self.add("notes/a.txt")
        added = self.commit("add notes")
        os.unlink(os.path.join(self.repo, "notes", "a.txt"))
        self.git("add", "-A")
        return base, added, self.commit("drop notes")

    def test_a_file_only_in_history_is_found(self):
        base, added, tip = self.history_only_file()
        self.assert_clean()
        rc, out = self.push_scan(f"refs/heads/main {tip} refs/heads/main {ZERO}")
        self.assertEqual(rc, 1, out)
        self.assert_push_flags(out, f"FAIL market_id {WITHHELD}:1 (commit {added} entry 1)")
        rc, out = self.scan("--range", f"{base}..{tip}")
        self.assertEqual(rc, 1, out)
        self.assert_push_flags(out, f"FAIL market_id {WITHHELD}:1 (commit {added} entry 1)")

    def test_what_the_remote_holds_is_not_scanned_again(self):
        _base, added, tip = self.history_only_file()
        rc, out = self.push_scan(f"refs/heads/main {tip} refs/heads/main {added}")  # the remote's old value
        self.assertEqual((rc, out.strip()), (0, "hygiene_scan: OK 1 item(s) scanned [push]"))
        self.write_ref("refs/remotes/origin/main", added)  # or a tracking ref for this remote
        rc, out = self.push_scan(f"refs/heads/main {tip} refs/heads/main {ZERO}")
        self.assertEqual(rc, 0, out)
        rc, out = self.push_scan(f"refs/heads/main {tip} refs/heads/main {ZERO}", remote="elsewhere")
        self.assertEqual(rc, 1, out)

    def test_commit_and_tag_messages(self):
        self.commit("base")
        self.write("pkg/t.py", "x = 1\n")
        self.add("pkg/t.py")
        flagged = self.commit(f"note {MARKET_2015}")
        body = (f"object {flagged}\ntype commit\ntag v-syn\n"
                f"tagger Synthetic Tester <tester@example.invalid> 1700000000 +0000\n\ntag {MARKET_2015}\n").encode()
        raw = b"tag " + str(len(body)).encode() + b"\0" + body
        tag = hashlib.sha1(raw).hexdigest()
        self.write(os.path.join(".git", "objects", tag[:2], tag[2:]), zlib.compress(raw))
        rc, out = self.push_scan(f"refs/tags/v-syn {tag} refs/tags/v-syn {ZERO}")
        self.assertEqual(rc, 1, out)
        self.assert_push_flags(out, f"FAIL market_id {WITHHELD}:1 (tag {tag} message)",
                               f"FAIL market_id {WITHHELD}:1 (commit {flagged} message)")

    def test_a_merge_is_scanned_for_what_differs_from_every_parent(self):
        base = self.commit("base")
        self.write_ref("refs/heads/side", base)
        self.write(".git/HEAD", "ref: refs/heads/side\n")
        self.write("side.txt", f"s = '{MARKET_2015}'\n")
        self.add("side.txt")
        side = self.commit("side")
        self.write(".git/HEAD", "ref: refs/heads/main\n")  # main is still base; the index keeps side.txt
        self.write(".git/MERGE_HEAD", side + "\n")
        self.write(".git/MERGE_MODE", "no-ff")  # as `git merge --no-ff` leaves it: keep both parents
        self.write("pkg/zz.py", f"e = '{MARKET_2015}'\n")
        self.add("pkg/zz.py")
        merge = self.commit("merge side")
        parents = self.git("rev-parse", f"{merge}^1", f"{merge}^2").stdout.decode().split()
        self.assertEqual(parents, [base, side])
        rc, out = self.push_scan(f"refs/heads/main {merge} refs/heads/main {ZERO}")
        self.assertEqual(rc, 1, out)
        # side.txt is the merge's but equals side's copy, so only the side commit lists it.
        self.assert_push_flags(out, f"FAIL market_id {WITHHELD}:1 (commit {side} entry 1)",
                               f"FAIL market_id {WITHHELD}:1 (commit {merge} entry 1)", "market_id=2")

    def test_a_deletion_publishes_nothing_and_bad_input_is_refused(self):
        tip = self.commit("base")
        rc, out = self.push_scan(f"(delete) {ZERO} refs/heads/gone {tip}")
        self.assertEqual((rc, out.strip()), (0, "hygiene_scan: OK 0 item(s) scanned [push]"))
        blob = self.git("rev-parse", "HEAD:README.md").stdout.decode().strip()
        for lines, code in (((f"refs/heads/main {tip}",), "push_input"),
                            ((f"refs/heads/main {blob} refs/heads/main {ZERO}",), "push_object_not_commit")):
            with self.subTest(code=code):
                rc, out = self.push_scan(*lines)
                self.assertEqual((rc, out.strip()), (2, f"hygiene_scan: refused:{code}"))
        for args in (("--range", "--all"), ("--push", ""), ("--message", "m", "--range", tip),
                     ("--staged", "--range", tip)):
            with self.subTest(args=args):
                rc, out = self.scan(*args)
                self.assertEqual(rc, 2, out)

    # git replace and grafts show one object, or one list of parents, in another's place, while a commit records and
    # a push sends the original (round-4 review). The scan must read what git stores. The replace refs, the stand-in
    # objects and the graft files are written into the temporary .git by hand.

    def loose(self, kind: str, body: bytes) -> str:
        """Write a loose object; return its id."""
        raw = kind.encode() + b" " + str(len(body)).encode() + b"\0" + body
        sha = hashlib.sha1(raw).hexdigest()
        self.write(os.path.join(".git", "objects", sha[:2], sha[2:]), zlib.compress(raw))
        return sha

    def rev(self, name: str) -> str:
        return self.git("rev-parse", name).stdout.decode().strip()

    def assert_found(self, *scans) -> None:
        for args, stdin in scans:
            with self.subTest(args=args):
                rc, out = self.scan(*args, stdin=stdin)
                self.assertEqual(rc, 1, out)
                self.assertIn("market_id", self.codes(out))
                self.assert_withheld(out)
                self.assertNotIn(MARKET_2015, out)

    def test_a_blob_replaced_by_a_clean_one_is_scanned_as_stored(self):
        base = self.commit("base")
        self.write("notes.txt", f"m = '{MARKET_2015}'\n")
        self.add("notes.txt")
        dirty = self.rev(":notes.txt")
        clean = self.loose("blob", b"clean synthetic notes\n")
        self.write_ref(f"refs/replace/{dirty}", clean)
        self.assert_found((("--staged",), b""))
        tip = self.commit("notes")
        self.assertEqual(self.rev(f"{tip}:notes.txt"), dirty)          # the commit records the dirty blob
        self.assert_found((("--range", f"{base}..{tip}"), b""),
                          (("--push", "origin"), f"refs/heads/main {tip} refs/heads/main {base}\n".encode()))

    def test_a_commit_replaced_by_a_clean_twin_is_scanned_as_stored(self):
        base = self.commit("base")
        self.write("notes.txt", f"m = '{MARKET_2015}'\n")
        self.add("notes.txt")
        dirty = self.commit("notes")
        stamp = "Synthetic Tester <tester@example.invalid> 1700000000 +0000"
        tree = self.rev(base + "^{tree}")                                # the twin adds nothing to base
        twin = self.loose("commit", f"tree {tree}\nparent {base}\nauthor {stamp}\ncommitter {stamp}\n\nnotes\n".encode())
        self.write_ref(f"refs/replace/{dirty}", twin)
        self.assert_found((("--range", f"{base}..{dirty}"), b""),
                          (("--push", "origin"), f"refs/heads/main {dirty} refs/heads/main {ZERO}\n".encode()),
                          (("--push", "origin"), f"refs/heads/main {dirty} refs/heads/main {base}\n".encode()))

    def test_a_graft_hides_no_commit(self):
        base, added, tip = self.history_only_file()                  # added holds the id; tip deletes it again
        self.write(".git/info/grafts", f"{tip} {base}\n")             # git would now skip added
        outside = os.path.join(self.tmp, "grafts")
        with open(outside, "w") as handle:
            handle.write(f"{tip} {base}\n")
        scans = ((("--range", f"{base}..{tip}"), b""),
                 (("--push", "origin"), f"refs/heads/main {tip} refs/heads/main {base}\n".encode()))
        self.assert_found(*scans)
        os.unlink(os.path.join(self.repo, ".git", "info", "grafts"))
        for args, stdin in scans:                                       # and a graft file named by the environment
            with self.subTest(args=args, graft_file="environment"):
                rc, out = self.scan(*args, stdin=stdin, env={**self.env, "GIT_GRAFT_FILE": outside})
                self.assertEqual(rc, 1, out)
                self.assertIn("market_id", self.codes(out))

    def test_push_input_past_the_limit_is_refused_not_cut_short(self):
        # Round-4 review: only the first 1 MiB of git's pre-push lines was read. A cut at a line end dropped every
        # later ref, so a push of about 8,900 refs or more could publish commits that no scan saw.
        _base, _added, tip = self.history_only_file()
        filler = f"(delete) {ZERO} refs/heads/{'f' * 25} {ZERO}\n"
        self.assertEqual(len(filler), 128)                               # 8192 lines fill exactly 1 MiB
        real = f"refs/heads/main {tip} refs/heads/main {ZERO}\n"
        rc, out = self.scan("--push", "origin", stdin=(filler * 8192 + real).encode())
        self.assertEqual((rc, out.strip()), (2, "hygiene_scan: refused:push_input"))
        rc, out = self.scan("--push", "origin", stdin=(filler * 8191 + real).encode())     # under the limit
        self.assertEqual(rc, 1, out)
        self.assertIn("market_id", self.codes(out))

    def test_message_files(self):
        member = bz2.compress(_stream_text().encode())
        cases = {"market_id": f"synthetic subject\n\nsee {MARKET_2015}\n".encode(),
                 "binary_file": _stream_text().encode("cp500"),
                 "encoded_blob": b"synthetic subject\n\n" + base64.encodebytes(member)}
        for code, data in cases.items():
            with self.subTest(code=code):
                self.write(".git/MSG", data)
                rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
                self.assertEqual(rc, 1, out)
                self.assertIn(code, self.codes(out))
                self.assert_withheld(out)
                self.assertNotIn(MARKET_2015, out)
        self.write(".git/MSG", "synthetic subject\n\nA clean body.\n")
        rc, out = self.scan("--message", os.path.join(self.repo, ".git", "MSG"))
        self.assertEqual((rc, out.strip()), (0, "hygiene_scan: OK 1 message(s) scanned [message]"))

    def test_message_files_that_are_not_plain_files_are_refused(self):
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        link = os.path.join(self.tmp, "link")
        os.symlink(os.path.join(self.repo, "README.md"), link)
        inside = os.path.join(self.tmp, _j("betangel", "-data"), "MSG")
        for path, code in ((fifo, "message_not_regular"), (link, "message_unreadable"), (inside, "data_root")):
            with self.subTest(code=code):
                rc, out = self.scan("--message", path)
                self.assertEqual((rc, out.strip()), (2, f"hygiene_scan: refused:{code}"))


class HookScriptTests(unittest.TestCase):
    """The history hooks: POSIX sh, executable, the scanner mode each needs, and their install line."""

    def test_each_hook_runs_its_scan(self):
        for name, flag in HISTORY_HOOKS.items():
            with self.subTest(hook=name):
                path = REPO / "tools" / name
                self.assertTrue(os.access(path, os.X_OK), "not executable")
                text = path.read_text()
                self.assertTrue(text.startswith("#!/bin/sh\n"))
                self.assertIn(f'"$PY" -I -S -B "$SCAN" --root "$ROOT" {flag}', text)
                self.assertIn(f"ln -s ../../tools/{name} .git/hooks/{name}", text)
                self.assertIn("PY=/opt/homebrew/bin/python3.13", text)


@unittest.skipUnless(os.access(PY313, os.X_OK), "the hook needs /opt/homebrew/bin/python3.13")
class PreCommitHookTests(_RepoCase):

    def setUp(self):
        super().setUp()
        tools = os.path.join(self.repo, "tools")
        os.makedirs(tools, exist_ok=True)
        shutil.copy(SCANNER, os.path.join(tools, "hygiene_scan.py"))
        hooks = os.path.join(self.repo, ".git", "hooks")
        os.makedirs(hooks, exist_ok=True)
        for name in ("pre-commit", *HISTORY_HOOKS):
            shutil.copy(REPO / "tools" / name, os.path.join(tools, name))
            os.symlink(f"../../tools/{name}", os.path.join(hooks, name))

    def commit(self):
        proc = self.git("commit", "-q", "-m", "synthetic", check=False)
        return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")

    def test_hook_allows_a_clean_commit(self):
        rc, out = self.commit()
        self.assertEqual(rc, 0, out)

    def test_hook_blocks_a_planted_id_without_echoing_it(self):
        self.write("pkg/s.py", f"x = '{MARKET_2015}'\n")
        self.add("pkg/s.py")
        rc, out = self.commit()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("market_id", out)
        self.assertIn("pre-commit: commit blocked", out)
        self.assertNotIn(MARKET_2015, out)
        head = self.git("rev-parse", "--verify", "-q", "HEAD", check=False)
        self.assertNotEqual(head.returncode, 0, "nothing should have been committed")

    def test_commit_msg_blocks_an_id_in_the_message(self):
        self.write("pkg/t.py", "x = 1\n")
        self.add("pkg/t.py")
        proc = self.git("commit", "-q", "-m", f"synthetic {MARKET_2015}", check=False)
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn(f"FAIL market_id {WITHHELD}:1 (message)", out)
        self.assertIn("commit-msg: commit blocked", out)
        self.assertNotIn(MARKET_2015, out)
        head = self.git("rev-parse", "--verify", "-q", "HEAD", check=False)
        self.assertNotEqual(head.returncode, 0, "nothing should have been committed")

    def test_pre_merge_commit_runs_the_staged_scan(self):
        # git runs pre-merge-commit only for `git merge`, which tests may not run; core.hooksPath gives
        # `git commit` the script as its pre-commit hook instead, to show it blocks on the staged tree.
        hooks = os.path.join(self.tmp, "merge-hooks")
        os.mkdir(hooks)
        os.symlink(os.path.join(self.repo, "tools", "pre-merge-commit"), os.path.join(hooks, "pre-commit"))
        with open(os.path.join(self.repo, ".git", "config"), "a") as handle:
            handle.write(f"[core]\n\thooksPath = {hooks}\n")
        self.write("pkg/s.py", f"x = '{MARKET_2015}'\n")
        self.add("pkg/s.py")
        rc, out = self.commit()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("pre-merge-commit: merge blocked", out)
        self.assertNotIn(MARKET_2015, out)

    def test_hook_blocks_a_forced_archive(self):
        self.write("data/x.bz2", bz2.compress(b"abc"))
        self.add("data/x.bz2", force=True)
        rc, out = self.commit()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("archive_member", out)


class OwnFilesTests(unittest.TestCase):
    """The scanner passes over its own sources, this file and the governance files."""

    def test_own_files_pass(self):
        names = ["tools/hygiene_scan.py", "tools/pre-commit", *(f"tools/{name}" for name in HISTORY_HOOKS),
                 "tests/test_hygiene.py",
                 ".gitignore", "AGENTS.md", "docs/data-handling.md", "docs/DESIGN.md"]
        present = [n for n in names if (REPO / n).is_file()]
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_GB.UTF-8", **FORBID}
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(SCANNER), "--root", str(REPO), *present],
            env=env, capture_output=True, timeout=120)
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, out)

    def test_whole_checkout_passes(self):
        # I-9 for every file of this checkout, tracked or not (not ignored): the core package, bin/, pin/
        # and every test, not only the governance files above. Tree mode lists files with git ls-files.
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_GB.UTF-8", "HOME": os.environ["HOME"],
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", **FORBID}
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(SCANNER), "--root", str(REPO)],
            env=env, capture_output=True, timeout=120)
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("[tree]", out)


if __name__ == "__main__":
    unittest.main()
