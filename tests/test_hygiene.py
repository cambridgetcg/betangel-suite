"""Tests for tools/hygiene_scan.py, tools/pre-commit and .gitignore (DESIGN.md I-9).

Each test builds its own temporary git repository (git init in a temp dir),
plants one forbidden thing, and runs the scanner as a subprocess with the
interpreter running the tests (-I -S -B). It asserts the exit status, the rule
code, and that the planted text never appears in the scanner's output.

Every planted value is assembled at runtime from fragments, so no line of this
file matches a scanner rule: the scanner passes over this file too. Planted
"real-shaped" values are invented; nothing here comes from licensed data.
Nothing in this file imports betangel_suite.
"""

from __future__ import annotations

import bz2
import gzip
import importlib.util
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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "hygiene_scan.py"
HOOK = REPO / "tools" / "pre-commit"
GITIGNORE = REPO / ".gitignore"
GIT = "/usr/bin/git"
PY313 = "/opt/homebrew/bin/python3.13"
# The test runner's guard starts a child only with the network switch kept on (betangel_suite/guard.py).
FORBID = {"BETANGEL_BETFAIR_FORBID_NETWORK": "1"}
FAIL_LINE = re.compile(r"^FAIL (\S+) ")


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

    def scan(self, *args: str, root: str | None = None):
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(SCANNER), "--root", root or self.repo, *args],
            env=self.env, capture_output=True, timeout=120)
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        return proc.returncode, out

    @staticmethod
    def codes(out: str) -> set:
        return {m.group(1) for m in map(FAIL_LINE.match, out.splitlines()) if m}

    def assert_flags(self, code: str, secrets=(), modes=("--staged", None)) -> None:
        for mode in modes:
            with self.subTest(mode=mode or "tree", code=code):
                rc, out = self.scan(*([mode] if mode else []))
                self.assertEqual(rc, 1, f"expected findings, got rc={rc}: {out}")
                self.assertIn(code, self.codes(out), out)
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
                self.assertIn("<name withheld>", out)

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

    def test_file_name_with_market_id_is_redacted(self):
        rel = f"notes/{MARKET_2015}-{EVENT}.txt"
        self.plant(rel, "nothing here\n", MARKET_2015, EVENT, code="market_id")
        rc, out = self.scan("--staged")
        self.assertIn("event_id", self.codes(out))
        self.assertIn("<name withheld>", out)


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
                self.assertIn("<name withheld>", out)

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

    def test_withheld_path_shows_only_a_listed_suffix(self):
        # A name can end in a word rather than a file type (a runner name with a dot for the space). A
        # withheld path shows a suffix only from the scanner's short list, compared exactly, so a suffix
        # off that list does not print, in the tree scan or the staged one. File types that are also
        # English words (.swift, .key, .tar, .sh) are off the list too; the previous list showed them.
        name = RUNNER_NAMES[1]
        word = name.split()[-1]
        content = f'row = {{"runnerName": "{name}"}}\n'
        cases = ((name.replace(" ", "."), ""), (f"card.{word.lower()}", ""), (f"{name}.MD", ""),
                 ("card.swift", ""), ("card.key", ""), ("card.tar", ""), ("card.sh", ""),
                 (f"{name}.md", ".md"), (f"{name}.csv", ".csv"), ("card.json", ".json"), ("card.bz2", ".bz2"))
        for base, suffix in cases:
            with self.subTest(base=base):
                self.setUp()
                self.plant(f"notes/{base}", content, name, word, word.lower(), code="runner_record",
                           force=True)
                for mode in ("--staged", None):
                    rc, out = self.scan(*([mode] if mode else []))
                    # Index entries: README.md, notes/<base>, pkg/module.py.
                    self.assertIn(f"FAIL runner_record <name withheld>{suffix}:1 (entry 2)", out)

    def test_private_key_header(self):
        self.plant("conf/notes.txt", PEM_KEY + "\nAAAA\n", PEM_KEY, code="private_key")

    def test_certificate_block(self):
        self.plant("conf/notes2.txt", PEM_CERT + "\nAAAA\n", PEM_CERT, code="pem_block")

    def test_bearer_token(self):
        self.plant("pkg/l.txt", BEARER_LINE + "\n", TOKEN_BODY, code="bearer_token")

    def test_secret_assignment(self):
        self.plant("pkg/m.py", SECRET_LINE + "\n", TOKEN_BODY[:20], code="secret_value")

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
        self.assertIn("FAIL market_id <name withheld>.py:7 (entry 3)", out)
        self.assertNotIn(MARKET_2015, out)
        self.assertNotIn("pkg/p.py", out)


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


def _article(host, scheme="https://", path="/en/articles/", tail="-how-long-do-you-store-my-data"):
    """A help-centre article URL whose 8-digit article number is EVENT (invented)."""
    return _j(scheme, host, path, EVENT, tail)


class UrlExemptionTests(_RepoCase):
    """The event_id rule's one exemption: 8-digit runs inside https URLs on the exact hosts of URL_HOST_ALLOWLIST."""

    def lines_by_code(self, rel: str, mode):
        # An id finding withholds the whole path ("FAIL event_id <name withheld>.md:2 (entry 2)"), so a file's
        # lines are told apart by its entry number. The scanner sorts its file list in both modes, and every file
        # these tests write is staged, so the index and the tree list the same files: the entry is rel's place in
        # the sorted tree (walked here, since the test guard allows no git ls-files).
        listing = []
        for directory, dirs, files in os.walk(self.repo):
            dirs[:] = [name for name in dirs if name != ".git"]
            base = os.path.relpath(directory, self.repo)
            listing += [name if base == "." else base + "/" + name for name in files]
        entry = sorted(listing).index(rel) + 1
        rc, out = self.scan(*([mode] if mode else []))
        found = {}
        for line in out.splitlines():
            match = re.match(r"^FAIL (\S+) .+:([0-9]+) \(entry %d\)$" % entry, line)
            if match:
                found.setdefault(match.group(1), set()).add(int(match.group(2)))
        return rc, out, found

    def test_article_urls_on_allowlisted_hosts_pass(self):
        short_article = _j("https://privacy.claude.com/en/articles/", "712", "34", "56", "-how-long-do-you-store-my-org")
        lines = [
            _article("privacy.claude.com"),
            # The shape of docs/proposals/001-agent-seat.md, Appendix A (the line the scanner flagged in Phase 0a).
            "- **Anthropic:** https://www.anthropic.com/legal/consumer-terms ; " + _article("privacy.claude.com")
            + " ; " + short_article + " ; https://code.claude.com/docs/en/data-usage",
            "[the article](" + _article("support.claude.com") + ")",
            "<" + _article("PRIVACY.Claude.com", tail="") + ">",
            "url = '" + _article("support.anthropic.com") + "'",
            '"' + _article("privacy.anthropic.com", path="/articles/", tail="?lang=en#retention") + '"',
            _article("support.claude.com", path="/pt-BR/articles/"),
        ]
        self.write("docs/sources.md", "\n".join(lines) + "\n")
        self.add("docs/sources.md")
        self.assert_clean()

    def test_lookalike_hosts_other_hosts_and_other_schemes_still_flag(self):
        lookalikes = [
            _article("privacy.claude.com.evil.example"),
            _article("claude.com@evil.example"),
            _article("privacy.claude.com@evil.example"),
            _j("https://evil.example/privacy.claude.com/en/articles/", EVENT),
            _article("privacy.claude.com:443"),
            _article("privacy.claude.com", scheme="http://"),
            "https://web.archive.org/web/2026/" + _article("privacy.claude.com"),
            _article("xprivacy.claude.com"),
            _article("privacy-claude.com"),
            _article("privacy.claude.com\\@evil.example"),
        ]
        never = [
            _article(_j("support.", "betfair", ".com")),
            _article(_j("support.developer.", "betfair", ".com"), path="/hc/en-us/articles/"),
            _article(_j("www.", "betangel", ".com")),
            _article(_j("www.", "timeform", ".com")),
            _article("docs.python.org"),
        ]
        self.write("docs/lookalike.md", "\n".join(lookalikes) + "\n")
        self.write("docs/hosts.md", "\n".join(never) + "\n")
        self.add("docs/lookalike.md", "docs/hosts.md")
        for mode in ("--staged", None):
            with self.subTest(mode=mode or "tree"):
                rc, out, found = self.lines_by_code("docs/lookalike.md", mode)
                self.assertEqual(rc, 1, out)
                self.assertEqual(found, {"event_id": set(range(1, len(lookalikes) + 1))}, out)
                _rc, _out, found = self.lines_by_code("docs/hosts.md", mode)
                self.assertEqual(found, {"event_id": set(range(1, len(never) + 1))}, out)
                self.assertNotIn(EVENT, out)

    def test_no_exemption_outside_the_url(self):
        lines = [
            _j("see ", EVENT, " and ") + _article("privacy.claude.com"),
            "https://privacy.claude.com/en/articles/x " + EVENT,
            "| https://privacy.claude.com/en/articles/x |" + EVENT + "|",
            "https://privacy.claude.com/en/articles/x\t" + EVENT,
        ]
        self.write("docs/outside.md", "\n".join(lines) + "\n")
        self.add("docs/outside.md")
        rc, out, found = self.lines_by_code("docs/outside.md", "--staged")
        self.assertEqual(rc, 1, out)
        self.assertEqual(found, {"event_id": {1, 2, 3, 4}}, out)

    def test_only_the_article_number_of_an_article_path_is_exempt(self):
        # An allowlisted host exempts nothing in the query, the fragment or any other path (Phase 0c review).
        lines = [
            _j("https://support.claude.com/?id=", EVENT),
            _j("https://support.claude.com/#", EVENT),
            _j("https://support.claude.com/x;", EVENT),
            _j("https://support.claude.com/en/", EVENT),
            _j("https://support.claude.com/en/articles/x#", EVENT),
            _j("https://support.claude.com/en/articles/", EVENT, ".html"),
            _j("https://support.claude.com/en/articles/x/", EVENT),
            _article("support.claude.com", tail="-slug?e=" + EVENT),
            _article("support.claude.com", tail="#" + EVENT),
        ]
        self.write("docs/query.md", "\n".join(lines) + "\n")
        self.add("docs/query.md")
        rc, out, found = self.lines_by_code("docs/query.md", "--staged")
        self.assertEqual(rc, 1, out)
        self.assertEqual(found, {"event_id": set(range(1, len(lines) + 1))}, out)
        self.assertNotIn(EVENT, out)

    def test_other_rules_still_apply_inside_allowlisted_urls(self):
        lines = [
            _j("https://privacy.claude.com/en/articles/", MARKET_2015),
            _j("https://support.claude.com/files/", MEMBER),
            _j("https://privacy.claude.com/en/articles/", EVENT, "-x?t=", GH_TOKEN),
        ]
        self.write("docs/inside.md", "\n".join(lines) + "\n")
        self.add("docs/inside.md")
        rc, out, found = self.lines_by_code("docs/inside.md", "--staged")
        self.assertEqual(rc, 1, out)
        self.assertEqual(found.get("market_id"), {1, 2}, out)
        self.assertEqual(found.get("member_path"), {2}, out)
        self.assertEqual(found.get("known_token"), {3}, out)
        self.assertEqual(found.get("event_id"), {2}, "only an article number is exempt, never the id in a file path")
        for text in (MARKET_2015, EVENT, GH_TOKEN):
            self.assertNotIn(text, out)

    def test_allowlist_holds_exact_documentation_hosts_only(self):
        spec = importlib.util.spec_from_file_location("hygiene_scan_under_test", SCANNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hosts = module.URL_HOST_ALLOWLIST
        self.assertTrue(hosts)
        self.assertLessEqual(len(hosts), 8, "a short, reviewed list")
        for host in hosts:
            with self.subTest(host=host):
                self.assertRegex(host, r"\A[a-z0-9-]+(\.[a-z0-9-]+)+\Z")
                for mark in ("betfair", "betangel", "timeform"):
                    self.assertNotIn(mark, host)

    def test_the_scanner_refuses_to_run_with_a_data_host_on_its_allowlist(self):
        source = SCANNER.read_text(encoding="utf-8")
        anchor = '    "support.claude.com",\n'
        self.assertIn(anchor, source)
        for label, extra in (("betfair", _j("support.", "betfair", ".com")), ("timeform", _j("www.", "timeform", ".com")),
                             ("pattern", "*.claude.com")):
            with self.subTest(case=label):
                copy = os.path.join(self.tmp, "scanner-%s.py" % label)
                with open(copy, "w", encoding="utf-8") as handle:
                    handle.write(source.replace(anchor, anchor + '    "%s",\n' % extra))
                proc = subprocess.run([sys.executable, "-I", "-S", "-B", copy, "--root", self.repo],
                                      env=self.env, capture_output=True, timeout=120)
                out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
                self.assertEqual(proc.returncode, 2, out)
                self.assertIn("refused:url_allowlist_invalid", out)


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


@unittest.skipUnless(os.access(PY313, os.X_OK), "the hook needs /opt/homebrew/bin/python3.13")
class PreCommitHookTests(_RepoCase):

    def setUp(self):
        super().setUp()
        tools = os.path.join(self.repo, "tools")
        os.makedirs(tools, exist_ok=True)
        shutil.copy(SCANNER, os.path.join(tools, "hygiene_scan.py"))
        shutil.copy(HOOK, os.path.join(tools, "pre-commit"))
        hooks = os.path.join(self.repo, ".git", "hooks")
        os.makedirs(hooks, exist_ok=True)
        os.symlink("../../tools/pre-commit", os.path.join(hooks, "pre-commit"))

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

    def test_hook_blocks_a_forced_archive(self):
        self.write("data/x.bz2", bz2.compress(b"abc"))
        self.add("data/x.bz2", force=True)
        rc, out = self.commit()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("archive_member", out)


class OwnFilesTests(unittest.TestCase):
    """The scanner passes over its own sources, this file and the governance files."""

    def test_own_files_pass(self):
        names = ["tools/hygiene_scan.py", "tools/pre-commit", "tests/test_hygiene.py",
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
