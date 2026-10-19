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
| **git** (commits, branches, PRs, issues) | Source, docs, the pin file, synthetic fixtures *generators*, synthetic screenshots under `docs/synthetic/` | `*.bz2`, `*.tar`, any archive, `*.sqlite*`, `*.jsonl`, CSV and other exports, `run/`, `exports/`, `ledger/`, `private/` and other state directories, any file over 512 KiB (DESIGN.md is the scanner's one allowlisted file, up to 2 MiB and still scanned; that the rule allows it is asked of Yu on 2026-10-19 (Astra's and Nuance's PR #1 reviews)), real market, event or selection ids, runner names, prices, member paths, keys, tokens |
| **Logs, stdout, stderr, HTTP errors** | Error codes, counts, timings, salted identifier hashes (pseudonymous, not anonymous; DESIGN.md 9.2 item 9) | Tracebacks (Phase 0 writes none anywhere; later, only 0600 files under `private/`, which agents never read), request bodies, data rows, member paths, ids, names, prices, the bootstrap code or session token |
| **Model context, Collab, the mailbox** (lab-Claude, Nuance, Astra) | Codes, counts, timings and salted hashes, as printed by `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary`; synthetic fixtures; uisnap screenshots of synthetic markets | Real rows, runner names, prices, market ids, per-market results; anything under `~/betangel-data`, read, searched or listed (the ledger, `sessions/` and `private/` included); the install salt; screenshots of real races |
| **Screenshots** | uisnap PNGs of synthetic-only engines. `bin/suite uisnap` writes them (0600) by default under `~/.local/state/betangel-suite/uisnap/out/<UTC stamp>/`, or in a missing or empty `--out DIR` inside the suite's write roots; either way outside every clone. Any kept in git are copied to `docs/synthetic/` by hand | Any screenshot of a real market. On the lab, agents have no Screen Recording permission, and `screencapture` is never used on the lab screen. On the Air an agent's shell passes the screen-capture preflight with no prompt, so no agent captures the screen there while a suite page or an `ssh lab-suite` window is open (DESIGN.md 8.6; Nuance's PR #1 review, item 6). A line saying so in the Air's CLAUDE.md (Q-Y10) was approved by Yu on 2026-10-17 and is in (Nuance confirmed it on 2026-10-17): a CLAUDE.md rule for Claude Code sessions on the Air; for Astra and other tools it is conduct only |
| **The browser** | A Safari Private window, on both machines (Q-Y11, answered by Yu on 2026-10-17); UI preferences in `localStorage` | The session token in storage, cookies, external requests; a page title that names a race (it is always `betangel-suite`) |
| **Disk** | Derivatives under the suite root (0700); data roots are read-only to the suite | Decompressed members anywhere; any derivative outside `~/betangel-data`; temp files outside the suite's own `TMPDIR` |

Phase 0 is synthetic-only, so it writes no licensed derivative. Yu agreed the suite root (R-4).
Nuance's review of #5 agrees it as built at 52a9edc, on conditions, to be confirmed at the merge
SHA; Nuance's re-review of #2 accepted `roots.STATE_ROOT_AGREED` staying True meanwhile, on
conditions (lab-Claude's call; AGENTS.md, Phase 0 status A). An engine command creates
`~/betangel-data/suite.noindex/` and its `tmp/` (both 0700), and only the engine may write there.
No engine command runs with the real HOME before the runbook's widened L1 layout check, which
accepts that root, lands on the lab: the lab's betangel-research checkout at a C0 that includes
416702f, with no suite command between that C0's L1 check and the runbook's 5a (lab-Claude's
decision of 2026-10-19; Nuance's condition (b); AGENTS.md, Phase 0 status A; DESIGN.md 3.7). A
`suite.noindex` that is a link, or a state root that a link puts in `~/betangel-data`, is refused
before anything is written (62c39c6).

The test runner itself is confined: its guard mode refuses writes under `~/betangel-data`, and
reads there too, as `vendor`'s, `uisnap`'s, `release`'s and `stop`'s do (0a3ed65). Every
interpreter child it starts and every `bin/suite` child need an explicit environment whose HOME,
the roots under it and `TMPDIR` keep out of the runner's data home, checked at spawn by realpath
and identity (96f8a90, 8e751d6; Nuance's re-review of #2, F2): a child that imports
`betangel_suite` arms its own guard from the HOME it is given. The runner's own `-j` workers, which
inherit its environment and arm test mode, are the one exception. So tests give every child a
temporary HOME. What a child does with its environment after it starts, and a child that never
imports `betangel_suite`, are conduct.

The suite never writes `~/.local/state/lab-runs/`, where Nuance's run wrapper keeps its marker and
lock, and refuses a root in, around or onto it (`root_overlaps_lab_runs`; c3b0c61).

## Exceptions: none without Betfair's specific written agreement naming the provider

No agent looks at real values. When structure is not enough, Yu describes the shape, or
lab-Claude adds a code-only check to `bin/suite diagnose` (DESIGN.md 8.7; Nuance's PR #1 review,
item 2). Q-Y9, as reworded, was answered by Yu on 2026-10-17 ("Lets go with what you recommended
for all :)"): confirmed (DESIGN.md 2.2.1).

Yu's OK alone cannot make an exception. A model context counts as an upload, and the Betfair
Historical Data terms' "No onward distribution" clause prohibits "the use of the Historical
Betfair Data by, another organization or individual" unless "a specific agreement in writing
with Betfair exists". Betfair has not ruled on model providers (the clause as quoted in proposal
001, sections 5.1-5.2; proposal 001 is PR #3, not merged). So real fields reach a model provider
only with Betfair's specific written agreement naming that provider, plus Yu's explicit OK each
time, in Yu's own words in Yu's direct channel, scoped to one problem report and named fields.
Yu's answer would be recorded in that report's folder, and nothing beyond its scope read. A relay
from another agent is never that OK. Until such an agreement exists, exceptions are not available.

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
- **Deny rules for lab-Claude's file tools**, approved by Yu on 2026-10-16 (DESIGN.md Q-Y9):
  Claude Code on the lab denies `Read` and `Edit` of `~/betangel-data`, of everything under it,
  and of `~/.local/state/betangel-suite/install-salt*`. Read and Edit are denied; Grep and Glob
  are unverified; Bash is conduct only. On the lab `claude --version` is 2.1.301, and lab-Claude's
  main session has no Grep or Glob tool, so its searches go through Bash, which the deny rules do
  not cover (DESIGN.md 9.4). For Nuance's SSH shell and Astra, rule 5 is conduct only. The
  optional `~/.ignore` with `/betangel-data/` (Nuance's suggestion) is not added: lab-Claude
  recommended against it, because it would also hide the folder from Yu's own searches, and Yu
  accepted that on 2026-10-17 (DESIGN.md 2.2.1). It would not have helped: it hides a folder only
  from ripgrep, not from Claude Code's shell `grep` or from `find` (Nuance's re-review of #2, F12).
- **`tools/hygiene_scan.py`** fails on archives (by name and by magic bytes), SQLite files,
  JSON-lines and data exports, keys and certificates, images outside `docs/synthetic/`, unknown
  binaries, oversize files, state and data-root directories, symbolic links, submodules,
  market-id, event-id and member-path shapes outside the reserved namespace, runner-name tables
  and records, private-key and PEM headers, bearer tokens, secret-looking values, provider tokens
  and bootstrap-code URLs. It also fails on binary data anywhere (a NUL anywhere, or bytes that are
  not UTF-8), on `encoded_blob` (data hidden in text that decodes to an archive, a zlib stream,
  96 or more bytes of binary, or text another rule flags: base64, hex in its common dump forms,
  `\xNN` escapes, string literals of four or more octal escapes, decimal byte lists and GIT
  binary patches; lists of full 40- or 64-digit hashes,
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
  and the other `str.splitlines()` boundaries, and read each line twice: as written, with format
  characters (a BOM, zero-width spaces) dropped, and with those and the other default-ignorable
  code points dropped, in NFKC form, so a no-break space reads as a space and fullwidth digits as
  ASCII digits (1e39931, 99ed70d). After ten lines for one entry and rule, one line counts the rest
  (`FAIL <rule code> <path withheld>: +<k> more line(s) (entry <n>)`), and a last line gives the
  totals per code. The message and history scans name their items in place of `(entry <n>)`:
  `(message)`, `(commit <sha> message)`, `(tag <sha> message)` and `(commit <sha> entry <k>)`.
  - No URL is exempt. The event-id rule treats a digit run inside a link like one anywhere
    else (Astra's answer to DESIGN.md Q-A2).
  - uisnap PNGs are synthetic only and live outside the repo (see the table above). The scanner
    fails on any image outside `docs/synthetic/`.
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
  from the repository root, and never bypass them (`--no-verify`). On the lab only `pre-commit` is
  live today: the main checkout has only that hook, so the other three links dangle and git skips
  them, and a commit message or a push is scanned only by hand, which is conduct. They go live
  before Phase 1a (AGENTS.md, "Repository hygiene"; DESIGN.md 5.6; Nuance's re-review of #2, F9):
  - `tools/pre-commit` (`ln -s ../../tools/pre-commit .git/hooks/pre-commit`): the staged tree;
  - `tools/pre-merge-commit` (`ln -s ../../tools/pre-merge-commit .git/hooks/pre-merge-commit`):
    the staged tree of a merge that needs no conflict resolution, which never runs pre-commit;
  - `tools/commit-msg` (`ln -s ../../tools/commit-msg .git/hooks/commit-msg`): the commit message;
  - `tools/pre-push` (`ln -s ../../tools/pre-push .git/hooks/pre-push`): every commit and
    annotated tag the push would publish, messages included, so a file one commit adds and a
    later one deletes is still found. It leaves out only commits reachable from the old values
    the remote reports in that push's own lines, when this clone holds them, and never trusts
    this clone's tracking refs, which can be stale until `git fetch --prune` (77271cd). It reads
    each commit and tag object whole, and refuses one over 1 MiB (`object_oversize`; fbd60fa).
- **The engine** maps upstream exceptions to closed error codes at the `rx.py` boundary and
  replaces identifiers with salted hashes (DESIGN.md 9.2 item 9). The hashes are pseudonymous,
  not anonymous: the hashed labels follow the public member layout, so a ref reverses by
  enumeration. So the salt (`~/.local/state/betangel-suite/install-salt`) is never read by an
  agent, and is not regenerated while its `salt-provisioned` marker exists: a missing salt is then
  refused (`salt_missing`), and restoring it is Yu's (8288c76; AGENTS.md, Phase 0 status B). The
  marker sits beside the salt, so losing both together looks like a fresh install, which the
  marker cannot catch: a new salt is made, and the hashes already recorded stop matching
  (DESIGN.md 9.2). The marker holds nothing, so the `install-salt*` deny need not cover it. The
  viewed-markets ledger is reconciled with Nuance's trial ledger at month level, by the counts
  `ledger-summary` prints, with no hash matching (Nuance's answer to Q-N11; DESIGN.md 5.5).
  `TMPDIR` and `SQLITE_TMPDIR` point at the suite's own temp dir. The guard sets
  `temp_store=MEMORY` on every SQLite connection, refuses one where it does not read 2, and
  refuses `connect("")` (06dba20).

## If something leaks

Stop, and do not repeat the leaked text anywhere, including in the report about it. If it is
staged or committed but not pushed, remove it from the index or the commit. Tell Yu in Yu's
direct channel, with codes and paths only. Anything already pushed, or any history rewrite, is
Yu's decision. A pre-push finding in an unpushed commit older than the last one can only be
removed by rewriting history, which is Yu's decision too: tell Yu the codes and the commit SHA.
After Yu has had something removed from a remote, run `git fetch --prune` in every clone: until
then a tracking ref can still name the removed commit, and a manual `--range` scan from it leaves
that commit out (`tools/pre-push` itself does not trust tracking refs; 77271cd).
