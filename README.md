# betangel-suite

Yu's personal macOS trading suite for Betfair. The first goal is a spoiler-free replay
ladder and paper-trading trainer over licensed Betfair historical data (GB/IE horse
racing WIN markets). It has no live path.

Status: Phase 0 (scaffold, guards and viewing; synthetic markets only) is built on stacked PRs,
pending review. Nothing reads real data yet. Read [AGENTS.md](AGENTS.md) for the rules every agent
follows and the Phase 0 status, and [docs/DESIGN.md](docs/DESIGN.md) for the design.

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
