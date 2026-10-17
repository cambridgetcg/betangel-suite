# betangel-suite

Yu's personal macOS trading suite for Betfair. The first goal is a spoiler-free replay
ladder and paper-trading trainer over licensed Betfair historical data (GB/IE horse
racing WIN markets). It has no live path.

## Status

Phase 0, synthetic only: no command reads real data or trades on paper yet (AGENTS.md,
"Phase 0 status"). The work is in stacked pull requests under review, each built on the
one before:

- PR #1, `design/mvp-draft-0.2`: the design (docs only).
- PR #2, `phase0/foundation`: the launcher `bin/suite`, the guard, the upstream pin and its
  vendor tool, the state roots, the run marker and real-data lock, the `rx.py` boundary,
  and the hygiene scanner with its git hooks.
- PR #4, `phase0/http`, and PR #5, `phase0/viewing`: the later Phase 0 steps
  (DESIGN.md section 12).

## Where to read

- [docs/DESIGN.md](docs/DESIGN.md): the design, its decisions and the open questions.
- [AGENTS.md](AGENTS.md): the binding rules for every agent, review routing, and the
  Phase 0 status.
- [docs/data-handling.md](docs/data-handling.md): what may go into git, logs, model
  context and screenshots.

## Tests

From the repository root, on the lab:

    nice -n 10 bin/suite test           # python3.13
    nice -n 10 bin/suite test --py311   # the same tests on python3.11

Tests use temporary HOMEs and synthetic fixtures only. `bin/suite test` refuses while
Nuance's run marker exists (AGENTS.md rule 7). Install the git hooks as AGENTS.md,
"Repository hygiene", describes.

## Ground rules

- **No licensed data in git.** Betfair historical data, and anything derived from it
  (journals, catalogues, exports, screenshots of real races), stays under
  `~/betangel-data` on the lab Mac, outside every clone. Tests use synthetic fixtures only.
- **No Betfair credentials.** There is no login, app key, certificate or account code
  path. The engine refuses to start without `BETANGEL_BETFAIR_FORBID_NETWORK=1`.
- **betangel-research is read-only.** The suite uses `cambridgetcg/betangel-research` at a
  pinned commit and never edits it. Upstream changes are made there, by its owner.
- **Live features come later, separately approved.** Anything that could place a real
  order needs an approved policy change first (DESIGN.md sections 12 and 14).

## Roles

- Lab-Claude (on the lab MacBook Pro) builds the offline replay and paper MVP.
- Nuance (Claude on Yu's MacBook Air) and Astra review it. Nuance owns betangel-research,
  policy changes, and Air-side and live work.
- Yu decides.
