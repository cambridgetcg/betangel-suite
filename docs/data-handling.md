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
| **Screenshots** | uisnap PNGs of synthetic-only engines, kept under `docs/synthetic/` | Any screenshot of a real market. Agents have no Screen Recording permission, and `screencapture` is never used on the lab screen |
| **The browser** | A Safari Private window (or a profile with no Betfair login, extensions or iCloud sync); UI preferences in `localStorage` | The session token in storage, cookies, external requests; a page title that names a race (it is always `betangel-suite`) |
| **Disk** | Derivatives under the suite root (0700); data roots are read-only to the suite | Decompressed members anywhere; any derivative outside `~/betangel-data`; temp files outside the suite's own `TMPDIR` |

In Phase 0 nothing is written under `~/betangel-data` at all: the suite root is not agreed yet
(AGENTS.md, Phase 0 status A), and Phase 0 is synthetic-only.

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
  and bootstrap-code URLs. It prints a rule code, a redacted path and a line number, never the
  matched text. When the file may hold data, the whole path is withheld and an entry number
  identifies it; only a suffix on the scanner's fixed list (its own file-type suffixes and common
  code and text ones) is still shown. `--list-rules` lists the codes.
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
