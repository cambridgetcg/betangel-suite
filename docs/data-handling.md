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
| **Logs, stdout, stderr, HTTP errors** | Error codes, counts, timings, salted identifier hashes | Tracebacks (these go only to 0600 files under `private/`), request bodies, data rows, member paths, ids, names, prices, the bootstrap code or session token |
| **Model context, Collab, the mailbox** (lab-Claude, Nuance, Astra) | Codes, counts, timings and salted hashes, as printed by `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary`; synthetic fixtures; uisnap screenshots of synthetic markets | Real rows, runner names, prices, market ids, per-market results, `ledger/viewed-markets.jsonl`, anything under `private/`, screenshots of real races |
| **Screenshots** | uisnap PNGs of synthetic-only engines. `bin/suite uisnap` writes them (0600) by default under `~/.local/state/betangel-suite/uisnap/out/<UTC stamp>/`, or in a missing or empty `--out DIR` inside the suite's write roots; either way outside every clone. Any kept in git are copied to `docs/synthetic/` by hand | Any screenshot of a real market. Agents have no Screen Recording permission, and `screencapture` is never used on the lab screen |
| **The browser** | A Safari Private window (or a profile with no Betfair login, extensions or iCloud sync); UI preferences in `localStorage` | The session token in storage, cookies, external requests; a page title that names a race (it is always `betangel-suite`) |
| **Disk** | Derivatives under the suite root (0700); data roots are read-only to the suite | Decompressed members anywhere; any derivative outside `~/betangel-data`; temp files outside the suite's own `TMPDIR` |

Phase 0 is synthetic-only, so it writes no licensed derivative. The suite root is agreed
(AGENTS.md, Phase 0 status A): an engine command creates `~/betangel-data/suite.noindex/` and its
`tmp/` (both 0700), and only the engine may write there. Tests use temporary HOMEs and never
write under the real `~/betangel-data`.

## Exceptions

An agent may look at real data only with Yu's explicit OK, given each time in Yu's own words in
Yu's direct channel, scoped to one problem report and named fields (DESIGN.md 8.7). Yu's answer
is recorded in that report's folder, and nothing beyond its scope is read. A relay from another
agent is never that OK.

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
  and bootstrap-code URLs. `--list-rules` lists the codes. For each finding it prints one line,
  `FAIL <rule code> <path withheld>:<line> (entry <n>)`. The text `<path withheld>` is the same
  for every finding: the scanner never prints a path or any part of one, not even a suffix, and
  never the matched text. Line 0 means the finding is about the entry itself (its name, type, size
  or link target). After ten lines for one entry and rule, one line counts the rest
  (`FAIL <rule code> <path withheld>: +<k> more line(s) (entry <n>)`), and a last line gives the
  totals per code.
  - One narrow exemption, from the event-id rule only: a 7- or 8-digit help-centre article
    number in an https URL on the scanner's own host allowlist (`URL_HOST_ALLOWLIST`: four Claude
    and Anthropic help hosts, never a Betfair, Bet Angel or Timeform host), where the path starts
    `/articles/<n>` or `/<locale>/articles/<n>` and `<n>` is followed by `-slug`, `?`, `#` or the
    end of the URL. Digits anywhere else still count: elsewhere in that URL's path, in its query
    or fragment, and everywhere outside it. Every other rule still applies inside such a URL. No
    file uses the exemption yet; Astra reviews it (DESIGN.md Q-A2).
  - uisnap PNGs are synthetic only and live outside the repo (see the table above). The scanner
    fails on any image outside `docs/synthetic/`.
- **Finding the file.** The entry number is the entry's position, from 1, in the list the scan
  worked through. Yu maps it to a file locally, from the repository root, with git (replace `N`):
  - after `--staged` or the pre-commit hook:
    `git -c core.quotepath=off ls-files --stage | sed -n 'Np'`
  - after a working-tree scan (no paths):
    `git -c core.quotepath=off ls-files --cached --others --exclude-standard | LC_ALL=C sort -u | sed -n 'Np'`
    (exact unless a path holds a control character, a double quote or a backslash, which git
    prints quoted, so that path can sort to a different place);
  - after a scan of named paths: scan fewer paths at a time until one entry is left.

  These commands print the path the scanner withholds, so they belong in Yu's own terminal, not
  in a chat, a report or an agent's context.
- **`tools/pre-commit`** runs the scanner on the staged tree and blocks the commit. Install it
  with `ln -s ../../tools/pre-commit .git/hooks/pre-commit`; never bypass it.
- **The engine** maps upstream exceptions to closed error codes at the `rx.py` boundary and
  replaces identifiers with salted hashes (DESIGN.md 9.2 item 9). `TMPDIR` and `SQLITE_TMPDIR`
  point at the suite's own temp dir, and SQLite runs with `temp_store=MEMORY`.

## If something leaks

Stop, and do not repeat the leaked text anywhere, including in the report about it. If it is
staged or committed but not pushed, remove it from the index or the commit. Tell Yu in Yu's
direct channel, with codes and paths only. Anything already pushed, or any history rewrite, is
Yu's decision.
