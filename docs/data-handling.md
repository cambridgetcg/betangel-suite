# Data handling

What may and may not go into git, logs, model context and screenshots. This page summarises
docs/DESIGN.md section 3.9 (rules 4 and 5), sections 5.5 and 5.6, section 9.2 item 9, and the
threat model in section 9.4. Where the two differ, DESIGN.md and Yu's own instructions win.

**Licensed data** is Betfair Historical Data and anything derived from it: member files,
indexes, catalogues, journals, `commands.jsonl`, session and problem reports, the viewed-markets
ledger, exports, logs that mention a market, screenshots of real races, and SQLite temp files.
It is for Yu's personal, internal use only. It stays under `~/betangel-data`, outside every git
clone, and is never uploaded or shared. A model context counts as an upload.

## Where things may go

| Destination | Allowed | Never |
|---|---|---|
| **git** (commits, branches, PRs, issues) | Source, docs, the pin file, synthetic fixtures *generators*, synthetic screenshots under `docs/synthetic/` | `*.bz2`, `*.tar`, any archive, `*.sqlite*`, `*.jsonl`, CSV and other exports, `run/`, `exports/`, `ledger/`, `private/` and other state directories, any file over 512 KiB (DESIGN.md is the one allowlisted file), real market, event or selection ids, runner names, prices, member paths, keys, tokens |
| **Logs, stdout, stderr, HTTP errors** | Error codes, counts, timings, salted identifier hashes (pseudonymous, not anonymous; DESIGN.md 9.2 item 9) | Tracebacks (these go only to 0600 files under `private/`), request bodies, data rows, member paths, ids, names, prices, the bootstrap code or session token |
| **Model context, Collab, the mailbox** (lab-Claude, Nuance, Astra) | Codes, counts, timings and salted hashes, as printed by `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary`; synthetic fixtures; uisnap screenshots of synthetic markets | Real rows, runner names, prices, market ids, per-market results; anything under `~/betangel-data`, read, searched or listed (the ledger, `sessions/` and `private/` included); the install salt; screenshots of real races |
| **Screenshots** | uisnap PNGs of synthetic-only engines, kept under `docs/synthetic/` | Any screenshot of a real market. On the lab, agents have no Screen Recording permission, and `screencapture` is never used on the lab screen. On the Air an agent's shell passes the screen-capture preflight with no prompt, so no agent captures the screen there while a suite page or an `ssh lab-suite` window is open (DESIGN.md 8.6; Nuance's PR #1 review, item 6; a line in the Air's CLAUDE.md, Q-Y10: asked of Yu on 2026-10-17, not answered) |
| **The browser** | A Safari Private window (or a profile with no Betfair login, extensions or iCloud sync); UI preferences in `localStorage` | The session token in storage, cookies, external requests; a page title that names a race (it is always `betangel-suite`) |
| **Disk** | Derivatives under the suite root (0700); data roots are read-only to the suite | Decompressed members anywhere; any derivative outside `~/betangel-data`; temp files outside the suite's own `TMPDIR` |

Phase 0 is synthetic-only, so it writes no licensed derivative. Yu agreed the suite root (R-4);
Nuance's agreement is conditional again pending the item 1 re-check, and `roots.STATE_ROOT_AGREED`
stays True meanwhile (lab-Claude's call; AGENTS.md, Phase 0 status A). An engine command creates
`~/betangel-data/suite.noindex/` and its `tmp/` (both 0700), and only the engine may write there.
Tests use temporary HOMEs and never write under the real `~/betangel-data`. A `suite.noindex` that
is a link, or a state root that a link puts in `~/betangel-data`, is refused before anything is
written (62c39c6). The suite never writes `~/.local/state/lab-runs/`, where Nuance's run wrapper
keeps its marker and lock.

## Exceptions: not available pending Q-Y9

No agent looks at real values. When structure is not enough, Yu describes the shape, or
lab-Claude adds a code-only check to `bin/suite diagnose` (DESIGN.md 8.7; Nuance's PR #1 review,
item 2). Q-Y9, as reworded, was asked of Yu on 2026-10-17, not answered.

Yu's OK alone cannot make an exception. A model context counts as an upload, and the licence
prohibits "the use of the Historical Betfair Data by, another organization or individual" unless
"a specific agreement in writing with Betfair exists". Betfair has not ruled on model providers
(proposal 001, sections 5.1-5.2). So real fields would reach a model context only with Betfair's
written agreement naming the model provider, plus Yu's explicit OK each time, in Yu's own words
in Yu's direct channel, scoped to one problem report and named fields. Yu's answer would be
recorded in that report's folder, and nothing beyond its scope read. A relay from another agent is
never that OK.

No "same-shape" fixture is ever derived from a real report: it would still be licensed.

## Synthetic fixtures

Fixtures are generated at test time into temp dirs (`tests/fixtures/gen.py`) and never committed
as binaries. They use only the reserved namespace:

- market ids `1.999` plus six digits; event ids `99` plus six digits; selection ids `9` plus
  seven digits;
- the venue "Synthetic Park" and runners "Synthetic 1..n".

In synthetic mode the engine refuses non-synthetic ids and every configured real data root.

## How it is enforced

- **`.gitignore`** keeps the usual shapes out of `git add`.
- **`tools/hygiene_scan.py`** fails on archives (by name and by magic bytes), SQLite files,
  JSON-lines and data exports, keys and certificates, images outside `docs/synthetic/`, unknown
  binaries, oversize files, state and data-root directories, symbolic links, submodules,
  market-id, event-id and member-path shapes outside the reserved namespace, runner-name tables
  and records, private-key and PEM headers, bearer tokens, secret-looking values, provider tokens
  and bootstrap-code URLs. It also fails on binary data anywhere (a NUL anywhere, or bytes that are
  not UTF-8), on `encoded_blob` (data hidden in text that decodes to an archive, a zlib stream,
  96 or more bytes of binary, or text another rule flags: base64, hex in its common dump forms,
  `\xNN` escapes, decimal byte lists and GIT binary patches; lists of full 40- or 64-digit hashes,
  one per line, up to 64 lines in all in one file or message and not inside a decoded run, are
  not counted as binary, but a signature or a zlib stream at any of their lines still counts;
  DESIGN.md 5.6 lists the encodings it does not decode, the other known gaps, among them binary
  data split into runs of under 96 bytes each, and the known false positives), and on
  `filter_attribute` (a path git gives a clean filter or LFS, or a `.gitattributes` line that sets
  one: git stores the filter's output, which the scan never sees). It reads the objects git
  stores: replace refs and
  grafts, which show one object in another's place, are ignored. `--list-rules` lists the codes. For each finding it prints one line,
  `FAIL <rule code> <path withheld>:<line> (entry <n>)`. The text `<path withheld>` is the same
  for every finding: the scanner never prints a path or any part of one, not even a suffix, and
  never the matched text. Line 0 means the finding is about the entry itself (its name, type, size
  or link target). Line numbers count `\n` line ends; the rules also split lines at CR, NEL, LS
  and the other `str.splitlines()` boundaries, and ignore format characters (a BOM, zero-width
  spaces). After ten lines for one entry and rule, one line counts the rest
  (`FAIL <rule code> <path withheld>: +<k> more line(s) (entry <n>)`), and a last line gives the
  totals per code. The message and history scans name their items in place of `(entry <n>)`:
  `(message)`, `(commit <sha> message)`, `(tag <sha> message)` and `(commit <sha> entry <k>)`.
- **Finding the file.** The entry number is the entry's position, from 1, in the list the scan
  worked through. Yu maps it to a file locally, from the repository root, with git (replace `N`):
  - after `--staged` run by hand:
    `git -c core.quotepath=off ls-files --stage | sed -n 'Np'`
  - after the pre-commit hook: the hook counts the entries of the index the commit would record.
    After `git commit -a` or `git commit <paths>`, git gives the hook a temporary index
    (`GIT_INDEX_FILE`), so its entry numbers need not match `git ls-files --stage`, and the command
    above can name an innocent file. First stage the change with `git add`, then run
    `tools/hygiene_scan.py --staged` by hand, which reads the real index, and map the entry number
    that run prints. A commit with no `-a` and no paths gives the hook the real index;
  - after a working-tree scan (no paths):
    `git -c core.quotepath=off ls-files --cached --others --exclude-standard | LC_ALL=C sort -u | sed -n 'Np'`
    (exact unless a path holds a control character, a double quote or a backslash, which git
    prints quoted, so that path can sort to a different place);
  - after a scan of named paths: scan fewer paths at a time until one entry is left;
  - after `tools/pre-push` or `--range`, `(commit <sha> entry <k>)`:
    `git -c core.quotepath=off diff-tree -r --no-commit-id --raw --no-renames --root -c <sha> | sed -n 'kp'`
    (replace `k`). Deleted paths count. For a merge, `-c` lists only the paths that differ from
    every parent;
  - `(commit <sha> message)`: `git log -1 --format=%B <sha>`;
  - `(tag <sha> message)`: `git cat-file tag <sha>`;
  - after `tools/commit-msg`, `(message)`: the line is a line of the message being committed,
    counted in the message file as git hands it over (comments included).

  These commands print the path the scanner withholds, so they belong in Yu's own terminal, not
  in a chat, a report or an agent's context.
- **The git hooks** each run the scanner and block on any finding. Install each once per clone,
  from the repository root, and never bypass them (`--no-verify`):
  - `tools/pre-commit` (`ln -s ../../tools/pre-commit .git/hooks/pre-commit`): the staged tree;
  - `tools/pre-merge-commit` (`ln -s ../../tools/pre-merge-commit .git/hooks/pre-merge-commit`):
    the staged tree of a merge that needs no conflict resolution, which never runs pre-commit;
  - `tools/commit-msg` (`ln -s ../../tools/commit-msg .git/hooks/commit-msg`): the commit message;
  - `tools/pre-push` (`ln -s ../../tools/pre-push .git/hooks/pre-push`): every commit and
    annotated tag the push would publish, messages included, so a file one commit adds and a
    later one deletes is still found.
- **The engine** maps upstream exceptions to closed error codes at the `rx.py` boundary and
  replaces identifiers with salted hashes (DESIGN.md 9.2 item 9). The hashes are pseudonymous,
  not anonymous: the hashed labels follow the public member layout, so a ref reverses by
  enumeration. So the salt (`~/.local/state/betangel-suite/install-salt`) is never read by an
  agent and never regenerated (AGENTS.md, Phase 0 status B), and the viewed-markets ledger is
  reconciled with Nuance's trial ledger at month level, by the counts `ledger-summary` prints,
  with no hash matching (Nuance's answer to Q-N11; DESIGN.md 5.5). `TMPDIR` and `SQLITE_TMPDIR`
  point at the suite's own temp dir. The guard sets `temp_store=MEMORY` on every SQLite
  connection, refuses one where it does not read 2, and refuses `connect("")` (06dba20).

## If something leaks

Stop, and do not repeat the leaked text anywhere, including in the report about it. If it is
staged or committed but not pushed, remove it from the index or the commit. Tell Yu in Yu's
direct channel, with codes and paths only. Anything already pushed, or any history rewrite, is
Yu's decision. A pre-push finding in an unpushed commit older than the last one can only be
removed by rewriting history, which is Yu's decision too: tell Yu the codes and the commit SHA.
